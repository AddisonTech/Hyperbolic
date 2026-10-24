"""Baseline, agent and replay runners.

A run directory holds everything needed to replay it with zero model or simulator calls:
  manifest.json  settings, dataset, envelope config
  steps.jsonl    per hour: district state, actions applied, outcome, decision
  calls.jsonl    per model call: full request, reply, tokens, cost. The reply's input_tokens is
                 uncached input, beside cache_read_input_tokens and cache_creation_input_tokens
                 (runs from before prompt caching record no cache counts and no cache reads).
  result.json    CityLearn KPIs and counts, token totals and the cache hit rate
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol

from . import __version__
from . import district as dc
from .envelope import BuildingState, Decision, Envelope, EnvelopeConfig, StepContext, parse_reply
from .model import (
    MODELS,
    Budget,
    CallResult,
    ReplayMismatch,
    ReplaySupervisor,
    Supervisor,
    cache_hit_rate,
    call_cost_usd,
    request_sha256,
    worst_case_cost_usd,
)
from .prompt import PROMPT_VERSION, Lookahead, build_request, end_trim_field, observe
from .signals import PeakInfo, PeakTracker, PriceOutlook


# The rule-based controller is the 0.4.0 reference, kept frozen so its result reproduces: prompt
# version 3 and the 0.4.0 envelope. Prompt versions 4 and 5 show its plan to the model each hour.
RULE_PROMPT_VERSION = 3
# Prompt version 6 is the first that knows the envelope holds cooling trims (0.8.0). Version 7
# (0.9.0) runs the same rules.
HOLD_PROMPT_VERSION = 6


def controller_settings(rule_based: bool, prompt_version: int | None = None) -> tuple[int, EnvelopeConfig]:
    """Prompt version and envelope rules for a new run. Without a prompt version, models get the
    current one and the rule-based controller the 0.4.0 one, each with its own envelope. Prompt
    versions before 6 run with the 0.7.0 rules, as they did then; versions 6 and 7 add the trim hold."""
    if prompt_version is None:
        prompt_version = RULE_PROMPT_VERSION if rule_based else PROMPT_VERSION
    if rule_based and prompt_version <= RULE_PROMPT_VERSION:
        return prompt_version, EnvelopeConfig.v040()
    if prompt_version < HOLD_PROMPT_VERSION:
        return prompt_version, EnvelopeConfig.v070()
    return prompt_version, EnvelopeConfig()


class Simulator(Protocol):
    """What the runners need from a simulator. CityLearnSimulator and RecordedSimulator satisfy it."""

    kind: str

    def start(self, hours: int | None) -> dict: ...
    def step(self, actions: dict | None) -> tuple[dict, dict | None]: ...
    def kpis(self) -> list[dict]: ...
    def close(self) -> None: ...


def _dump(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _opt(s: dict, key: str) -> float | None:
    return None if s.get(key) is None else float(s[key])


def context_from_state(state: dict, peak: PeakInfo | None = None, prices: PriceOutlook | None = None) -> StepContext:
    return StepContext(
        time_step=int(state["time_step"]),
        peak=peak,
        prices=prices,
        buildings={
            b: BuildingState(
                indoor_c=float(s["indoor_c"]),
                setpoint_c=float(s["setpoint_c"]),
                occupied=float(s["occupants"]) > 0,
                battery_soc=float(s["battery_soc"]),
                dhw_soc=float(s["dhw_soc"]),
                baseline={d: float(v) for d, v in state["baseline"][b].items()},
                bounds={d: (float(v[0]), float(v[1])) for d, v in state["bounds"][b].items()},
                load_kwh=_opt(s, "load_kwh"),
                cooling_power_kw=_opt(s, "cooling_power_kw"),
                battery_capacity_kwh=_opt(s, "battery_capacity_kwh"),
                dhw_capacity_kwh=_opt(s, "dhw_capacity_kwh"),
                dhw_heater_efficiency=_opt(s, "dhw_heater_efficiency"),
                battery_round_trip_min=_opt(s, "battery_round_trip_min"),
                battery_loss_per_hour=_opt(s, "battery_loss_per_hour"),
            )
            for b, s in state["buildings"].items()
        },
    )


class RunWriter:
    def __init__(self, run_dir: Path) -> None:
        self.dir = run_dir
        self.manifest: dict = {}

    def start(self, manifest: dict) -> None:
        # Files are created only once the simulator has started.
        self.dir.mkdir(parents=True, exist_ok=False)
        self._steps = (self.dir / "steps.jsonl").open("w", encoding="utf-8")
        self._calls = (self.dir / "calls.jsonl").open("w", encoding="utf-8")
        self.manifest = manifest
        (self.dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    def step(self, rec: dict) -> None:
        self._steps.write(_dump(rec) + "\n")
        self._steps.flush()

    def call(self, rec: dict) -> None:
        self._calls.write(_dump(rec) + "\n")
        self._calls.flush()

    def finish(self, result: dict) -> None:
        self._steps.close()
        self._calls.close()
        (self.dir / "result.json").write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")


class NullWriter(RunWriter):
    """Collects records in memory; used by replay."""

    def __init__(self) -> None:  # noqa: D401 - no files
        self.steps: list[dict] = []
        self.calls: list[dict] = []
        self.manifest = {}
        self.result: dict = {}

    def start(self, manifest: dict) -> None:
        self.manifest = manifest

    def step(self, rec: dict) -> None:
        self.steps.append(json.loads(_dump(rec)))

    def call(self, rec: dict) -> None:
        self.calls.append(json.loads(_dump(rec)))

    def finish(self, result: dict) -> None:
        self.result = result


class BaselineController:
    """CityLearn's no-control reference: storage idle, heat pump meeting the ideal load."""

    mode = "baseline"
    envelope = None

    def describe(self) -> dict:
        return {"kind": "none"}

    def decide(self, step: int, state: dict, writer: RunWriter) -> tuple[Decision | None, dict | None]:
        return None, None


@dataclass
class AgentController:
    supervisor: Supervisor
    envelope: Envelope
    budget: Budget
    max_tokens: int = 2000
    effort: str = "low"
    prompt_version: int = PROMPT_VERSION
    # New runs cache the system prompt; replay passes the manifest's value (absent before caching).
    prompt_cache: bool = True
    last: Decision | None = None
    lookahead: Lookahead = field(default_factory=Lookahead)
    peaks: PeakTracker | None = None
    mode: str = "agent"
    counts: dict = field(default_factory=lambda: {"calls": 0, "clamped": 0, "fallback": 0, "budget_skipped": 0})
    tokens: dict = field(default_factory=lambda: {"input": 0, "cache_read": 0, "cache_write": 0, "output": 0})

    def describe(self) -> dict:
        return {
            "kind": self.supervisor.kind,
            "model_key": self.supervisor.model_key,
            "model_id": MODELS[self.supervisor.model_key]["id"],
            "budget_usd": self.budget.limit_usd,
            "max_tokens": self.max_tokens,
            "effort": self.effort,
            "prompt_version": self.prompt_version,
            "prompt_cache": self.prompt_cache,
        }

    def decide(self, step: int, state: dict, writer: RunWriter) -> tuple[Decision, dict | None]:
        if self.peaks is None:
            self.peaks = PeakTracker(self.envelope.config.peak_forecast_days)
        self.peaks.update(state)
        self.lookahead.update(state)
        t = int(state["time_step"])
        prices = PriceOutlook(float(state["shared"]["price_forecast"][0]), tuple(self.lookahead.outlook(t)["price"]))
        ctx = context_from_state(state, self.peaks.info(t), prices)
        buildings = tuple(state["buildings"])
        obs = observe(self.prompt_version, state, ctx, self.last, self.lookahead, self.envelope)
        request = build_request(obs, self.envelope.config, buildings, self.supervisor.model_key,
                                self.max_tokens, self.effort, self.prompt_version, self.prompt_cache)
        worst = worst_case_cost_usd(self.supervisor.model_key, request)
        call_info = None
        if not self.budget.allows(worst):
            decision = self.envelope.fallback(ctx, self.budget.stop_reason or "budget stop")
            self.counts["budget_skipped"] += 1
        else:
            try:
                res = self.supervisor.call(step, request)
            except ReplayMismatch:
                raise
            except Exception as exc:  # any client failure is a missing reply, never a crash
                res = CallResult(None, error=f"client error: {type(exc).__name__}")
            cost = call_cost_usd(self.supervisor.model_key, res.input_tokens, res.output_tokens,
                                 res.cache_read_input_tokens, res.cache_creation_input_tokens)
            self.budget.charge(cost)
            self.counts["calls"] += 1
            for k, v in (("input", res.input_tokens), ("cache_read", res.cache_read_input_tokens),
                         ("cache_write", res.cache_creation_input_tokens), ("output", res.output_tokens)):
                self.tokens[k] += v
            sha = request_sha256(request)
            writer.call({
                "step": step,
                "request_sha256": sha,
                "request": request,
                "reply": {
                    "text": res.text,
                    "input_tokens": res.input_tokens,
                    "cache_read_input_tokens": res.cache_read_input_tokens,
                    "cache_creation_input_tokens": res.cache_creation_input_tokens,
                    "output_tokens": res.output_tokens,
                    "stop_reason": res.stop_reason,
                    "error": res.error,
                    "model": res.model,
                    "latency_s": round(res.latency_s, 3),
                },
                "cost_usd": round(cost, 8),
            })
            call_info = {"request_sha256": sha, "cost_usd": round(cost, 8), "error": res.error}
            if res.error:
                decision = self.envelope.fallback(ctx, f"no usable reply: {res.error}")
            else:
                proposal, err = parse_reply(res.text, buildings, end_trim_field(self.prompt_version))
                decision = self.envelope.apply(proposal, ctx, None if err is None else f"invalid reply: {err}")
        if decision.status == "clamped":
            self.counts["clamped"] += 1
        elif decision.status == "fallback":
            self.counts["fallback"] += 1
        self.last = decision
        return decision, call_info


def new_run_dir(runs_dir: Path, mode: str, sim_kind: str, dataset: str = dc.DATASET) -> Path:
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return runs_dir / f"{dataset}_{mode}_{sim_kind}_{stamp}"


def district_kpis(kpis: list[dict]) -> dict[str, float | None]:
    return {k["cost_function"]: k["value"] for k in kpis if k.get("level") == "district"}


class RunControl(Protocol):
    """Lets a caller pause or stop a run between hours (used by `hyperbolic serve`)."""

    def checkpoint(self) -> bool:
        """Block while paused; return False once a stop has been asked for."""
        ...


def run_session(
    sim: Simulator,
    controller: BaselineController | AgentController,
    writer: RunWriter,
    hours: int | None = None,
    sim_info: dict | None = None,
    log=print,
    on_step: Callable[[dict], None] | None = None,
    control: RunControl | None = None,
    max_steps: int | None = None,
    dataset: str = dc.DATASET,
) -> dict:
    """Run one episode of `hours` hourly decisions (the full month if None).

    on_step receives each hour's record right after it is written. control may pause or
    stop the run between hours; a stopped run is saved as partial. max_steps ends the run
    early without changing the episode length the simulator was started with, so a short
    run sees the same outages as the longer one it is compared with. dataset names the month
    in the manifest (0.10.0: a tuning month of the month set; hyperbolic.months).
    """
    state = sim.start(hours)
    stopped = False
    # The month's own length: 719 hours for the phase 2 month, 743 for a 31 day tuning month.
    month_hours = int(getattr(sim, "episode_end_t", dc.EPISODE_HOURS))
    episode_hours = hours or month_hours
    try:
        envelope_cfg = controller.envelope.config.as_dict() if controller.envelope else None
        writer.start({
            "schema": 2,
            "tool_version": __version__,
            "mode": controller.mode,
            "dataset": dataset,
            "buildings": list(state["buildings"]),
            "step_s": dc.STEP_SECONDS,
            "hours_limit": hours,
            "episode_hours": month_hours,
            "simulator": sim_info or {"kind": sim.kind},
            "supervisor": controller.describe(),
            "envelope": envelope_cfg,
            "started_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        })
        step = 0
        while state is not None:
            if max_steps is not None and step >= max_steps:
                break
            if control is not None and not control.checkpoint():
                stopped = True
                break
            decision, call_info = controller.decide(step, state, writer)
            actions = None if decision is None else decision.resolved(context_from_state(state))
            outcome, next_state = sim.step(actions)
            rec = {
                "step": step,
                "state": state,
                "actions": actions,
                "outcome": outcome,
                "decision": None if decision is None else decision.as_dict(),
                "call": call_info,
            }
            writer.step(rec)
            if on_step is not None:
                on_step(rec)
            if decision is not None and decision.status != "ok":
                why = decision.fallback or "; ".join(f"{c.point} {c.rule}" for c in decision.clamps)
                log(f"  hour {step:3d}: {decision.status}: {why}")
            step += 1
            if step % 168 == 0:
                log(f"  week {step // 168} done")
            state = next_state
            if hours and step >= hours:
                break
        kpis = sim.kpis()
    finally:
        sim.close()
    counts = getattr(controller, "counts", {})
    budget = getattr(controller, "budget", None)
    result = {
        "steps": step,
        "complete": step >= episode_hours,
        "kpis": kpis,
        "district_kpis": district_kpis(kpis),
        "calls": counts.get("calls", 0),
        "clamped_steps": counts.get("clamped", 0),
        "fallback_steps": counts.get("fallback", 0),
        "budget_skipped_steps": counts.get("budget_skipped", 0),
        "cost_usd": round(budget.spent_usd, 6) if budget else 0.0,
        "budget_stopped": bool(budget and budget.stopped),
        "budget_stop_reason": budget.stop_reason if budget else None,
        "finished_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
    }
    tokens = getattr(controller, "tokens", None)
    if tokens is not None:
        result["tokens"] = dict(tokens)
        rate = cache_hit_rate(tokens["input"], tokens["cache_read"], tokens["cache_write"])
        result["cache_hit_rate"] = None if rate is None else round(rate, 4)
    if stopped:
        result["stopped"] = True
        result["stop_reason"] = f"stopped by the user after {step} of {episode_hours} hours"
    writer.finish(result)
    return result


# -- replay ---------------------------------------------------------------------


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class RecordedSimulator:
    """Serves a run's recorded states and outcomes and checks every action sent."""

    kind = "replay"

    def __init__(self, run_dir: Path) -> None:
        self.manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
        self.steps = load_jsonl(run_dir / "steps.jsonl")
        result_path = run_dir / "result.json"
        self.result = json.loads(result_path.read_text(encoding="utf-8")) if result_path.exists() else {}
        self.i = 0
        self.action_mismatches: list[int] = []

    def start(self, hours: int | None) -> dict:
        self.i = 0
        return self.steps[0]["state"]

    def step(self, actions: dict | None) -> tuple[dict, dict | None]:
        rec = self.steps[self.i]
        if json.loads(_dump(actions)) != rec["actions"]:
            self.action_mismatches.append(self.i)
        self.i += 1
        nxt = self.steps[self.i]["state"] if self.i < len(self.steps) else None
        return rec["outcome"], nxt

    def kpis(self) -> list[dict]:
        return self.result.get("kpis", [])

    def close(self) -> None:
        pass


@dataclass
class ReplayReport:
    steps: int
    identical_steps: int
    mismatched_steps: list[int]
    calls: int
    api_calls: int
    cost_usd: float
    clamped_steps: int
    fallback_steps: int
    error: str | None = None
    cache_hit_rate: float | None = None

    @property
    def deterministic(self) -> bool:
        return self.error is None and not self.mismatched_steps and self.identical_steps == self.steps


def replay_run(run_dir: Path, out_dir: Path | None = None, log=lambda *_: None) -> ReplayReport:
    """Re-run a recorded run through the same code path with zero model or simulator calls."""
    sim = RecordedSimulator(run_dir)
    m = sim.manifest
    if m["mode"] == "baseline":
        controller: BaselineController | AgentController = BaselineController()
    else:
        sup = m["supervisor"]
        controller = AgentController(
            supervisor=ReplaySupervisor(run_dir / "calls.jsonl", sup["model_key"]),
            envelope=Envelope(EnvelopeConfig.from_manifest(m["envelope"])),
            budget=Budget(limit_usd=float(sup["budget_usd"])),
            max_tokens=int(sup["max_tokens"]),
            effort=sup["effort"],
            # Runs recorded before prompt versions existed used version 1.
            prompt_version=int(sup.get("prompt_version", 1)),
            # Runs recorded before prompt caching sent the system prompt as a plain string.
            prompt_cache=bool(sup.get("prompt_cache", False)),
        )
    writer: RunWriter = RunWriter(out_dir) if out_dir is not None else NullWriter()
    error = None
    try:
        run_session(sim, controller, writer, hours=len(sim.steps),
                    sim_info={"kind": "replay", "source": run_dir.name}, log=log)
    except ReplayMismatch as exc:
        error = str(exc)
        if out_dir is not None:
            writer.finish({"replay_error": error})
    replayed = writer.steps if isinstance(writer, NullWriter) else load_jsonl(out_dir / "steps.jsonl")  # type: ignore[operator]
    mismatched = sorted(set(sim.action_mismatches))
    identical = 0
    for orig, new in zip(sim.steps, replayed):
        if orig.get("decision") == new.get("decision") and orig["actions"] == new["actions"]:
            identical += 1
        elif orig["step"] not in mismatched:
            mismatched.append(orig["step"])
    if len(replayed) != len(sim.steps):
        mismatched.append(min(len(replayed), len(sim.steps)))
    calls = load_jsonl(run_dir / "calls.jsonl")
    counts = getattr(controller, "counts", {})
    replies = [c.get("reply") or {} for c in calls]
    hit_rate = cache_hit_rate(*(sum(r.get(k, 0) or 0 for r in replies) for k in
                                ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")))
    return ReplayReport(
        steps=len(sim.steps),
        identical_steps=identical,
        mismatched_steps=sorted(set(mismatched)),
        calls=len(calls),
        api_calls=0,
        cost_usd=round(sum(c.get("cost_usd", 0.0) for c in calls), 6),
        clamped_steps=counts.get("clamped", 0),
        fallback_steps=counts.get("fallback", 0),
        error=error,
        cache_hit_rate=hit_rate,
    )
