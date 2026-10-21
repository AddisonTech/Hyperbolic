"""Baseline, agent and replay runners.

A run directory holds everything needed to replay it with zero network calls:
  manifest.json  settings, envelope config, initial measurements
  steps.jsonl    per hour: forecast, overwrites sent, measurements back, KPIs, decision
  calls.jsonl    per model call: full request, reply, tokens, cost
  result.json    final KPIs and counts
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import __version__
from . import testcase as tc
from .boptest import Simulator
from .envelope import Decision, Envelope, EnvelopeConfig, StepContext, parse_reply
from .model import (
    Budget,
    MODELS,
    ReplayMismatch,
    ReplaySupervisor,
    Supervisor,
    call_cost_usd,
    request_sha256,
    worst_case_cost_usd,
)
from .prompt import build_observation, build_request

FORECAST_HORIZON_S = 12 * 3600


def _dump(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


class RunWriter:
    def __init__(self, run_dir: Path) -> None:
        self.dir = run_dir
        self.manifest: dict = {}

    def start(self, manifest: dict) -> None:
        # Files are created only once the simulator has accepted the scenario.
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
    mode = "baseline"

    def describe(self) -> dict:
        return {"kind": "none"}

    def decide(self, step: int, y: dict, fc: dict, writer: RunWriter) -> tuple[Decision | None, dict | None]:
        return None, None

    @staticmethod
    def overwrites(decision: Decision | None, time_s: float) -> dict[str, float]:
        return {}


@dataclass
class AgentController:
    supervisor: Supervisor
    envelope: Envelope
    budget: Budget
    electricity_price: str = tc.DEFAULT_ELECTRICITY_PRICE
    max_tokens: int = 2000
    effort: str = "low"
    last: Decision | None = None
    mode: str = "agent"
    counts: dict = field(default_factory=lambda: {"calls": 0, "clamped": 0, "fallback": 0, "budget_skipped": 0})

    def describe(self) -> dict:
        return {
            "kind": self.supervisor.kind,
            "model_key": self.supervisor.model_key,
            "model_id": MODELS[self.supervisor.model_key]["id"],
            "budget_usd": self.budget.limit_usd,
            "max_tokens": self.max_tokens,
            "effort": self.effort,
        }

    def decide(self, step: int, y: dict, fc: dict, writer: RunWriter) -> tuple[Decision, dict | None]:
        obs = build_observation(y, fc, self.last, self.electricity_price)
        ctx = StepContext(time_s=float(y["time"]), band_lower_c=obs["comfort_band_c"]["lower"],
                          band_upper_c=obs["comfort_band_c"]["upper"])
        request = build_request(obs, self.envelope.config, self.supervisor.model_key, self.max_tokens, self.effort)
        worst = worst_case_cost_usd(self.supervisor.model_key, request)
        call_info = None
        if not self.budget.allows(worst):
            decision = self.envelope.fallback(self.budget.stop_reason or "budget stop")
            self.counts["budget_skipped"] += 1
        else:
            try:
                res = self.supervisor.call(step, request)
            except ReplayMismatch:
                raise
            except Exception as exc:  # any client failure is a missing reply, never a crash
                from .model import CallResult

                res = CallResult(None, error=f"client error: {type(exc).__name__}")
            cost = call_cost_usd(self.supervisor.model_key, res.input_tokens, res.output_tokens)
            self.budget.charge(cost)
            self.counts["calls"] += 1
            sha = request_sha256(request)
            writer.call({
                "step": step,
                "request_sha256": sha,
                "request": request,
                "reply": {
                    "text": res.text,
                    "input_tokens": res.input_tokens,
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
                decision = self.envelope.fallback(f"no usable reply: {res.error}")
            else:
                proposal, err = parse_reply(res.text)
                decision = self.envelope.apply(proposal, ctx, None if err is None else f"invalid reply: {err}")
        if decision.status == "clamped":
            self.counts["clamped"] += 1
        elif decision.status == "fallback":
            self.counts["fallback"] += 1
        self.last = decision
        return decision, call_info

    @staticmethod
    def overwrites(decision: Decision | None, time_s: float) -> dict[str, float]:
        return {} if decision is None else decision.to_boptest_u(time_s)


def new_run_dir(runs_dir: Path, scenario: str, mode: str, sim_kind: str) -> Path:
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return runs_dir / f"{scenario}_{mode}_{sim_kind}_{stamp}"


def run_session(
    sim: Simulator,
    controller: BaselineController | AgentController,
    writer: RunWriter,
    scenario: str,
    electricity_price: str = tc.DEFAULT_ELECTRICITY_PRICE,
    hours: int | None = None,
    kpi_every: int = 1,
    sim_info: dict | None = None,
    log=print,
) -> dict:
    if scenario not in tc.SCENARIOS:
        raise ValueError(f"unknown scenario {scenario}")
    sc = tc.SCENARIOS[scenario]
    total_hours = (sc["end_day"] - sc["start_day"]) * 24
    sim.select(tc.TESTCASE)
    if hasattr(sim, "wait_until_running"):
        sim.wait_until_running()
    try:
        sim.set_step(tc.STEP_SECONDS)
        y = sim.set_scenario(scenario, electricity_price)
        start_time = float(y["time"])
        end_time = start_time + total_hours * 3600
        envelope_cfg = controller.envelope.config.as_dict() if isinstance(controller, AgentController) else None
        writer.start({
            "schema": 1,
            "tool_version": __version__,
            "mode": controller.mode,
            "testcase": tc.TESTCASE,
            "scenario": scenario,
            "electricity_price": electricity_price,
            "step_s": tc.STEP_SECONDS,
            "hours_limit": hours,
            "scenario_hours": total_hours,
            "kpi_every": kpi_every,
            "simulator": sim_info or {"kind": type(sim).__name__},
            "supervisor": controller.describe(),
            "envelope": envelope_cfg,
            "started_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "y0": y,
        })
        points = tc.forecast_points(electricity_price)
        step = 0
        while True:
            t = float(y["time"])
            fc = sim.forecast(points, FORECAST_HORIZON_S, tc.STEP_SECONDS)
            decision, call_info = controller.decide(step, y, fc, writer)
            u = controller.overwrites(decision, t)
            y_next = sim.advance(u)
            if not y_next:
                break
            kpi = sim.kpi() if kpi_every and (step + 1) % kpi_every == 0 else None
            writer.step({
                "step": step,
                "time": t,
                "forecast": fc,
                "u": u,
                "y": y_next,
                "kpi": kpi,
                "decision": None if decision is None else decision.as_dict(),
                "call": call_info,
            })
            if decision is not None and decision.status != "ok":
                why = decision.fallback or "; ".join(f"{c.point} {c.rule}" for c in decision.clamps)
                log(f"  hour {step:3d}: {decision.status}: {why}")
            y = y_next
            step += 1
            if step % 24 == 0:
                log(f"  day {step // 24} of {total_hours // 24} done")
            if hours and step >= hours:
                break
            if float(y["time"]) >= end_time - 1:
                break
        final_kpi = sim.kpi()
    finally:
        sim.stop()
    counts = getattr(controller, "counts", {})
    budget = getattr(controller, "budget", None)
    result = {
        "steps": step,
        "complete": step >= total_hours,
        "final_kpi": final_kpi,
        "calls": counts.get("calls", 0),
        "clamped_steps": counts.get("clamped", 0),
        "fallback_steps": counts.get("fallback", 0),
        "budget_skipped_steps": counts.get("budget_skipped", 0),
        "cost_usd": round(budget.spent_usd, 6) if budget else 0.0,
        "budget_stopped": bool(budget and budget.stopped),
        "budget_stop_reason": budget.stop_reason if budget else None,
        "finished_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
    }
    writer.finish(result)
    return result


# -- replay ---------------------------------------------------------------------


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


class RecordedSimulator:
    """Serves a run's recorded simulator responses and checks every overwrite sent."""

    def __init__(self, run_dir: Path) -> None:
        self.manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
        self.steps = load_jsonl(run_dir / "steps.jsonl")
        result_path = run_dir / "result.json"
        self.result = json.loads(result_path.read_text(encoding="utf-8")) if result_path.exists() else {}
        self.testid: str | None = None
        self.i = 0
        self.u_mismatches: list[int] = []
        self._kpi_seen: set[int] = set()

    def select(self, testcase: str) -> str:
        self.testid = "replay"
        return self.testid

    def set_step(self, seconds: int) -> None:
        pass

    def set_scenario(self, time_period: str, electricity_price: str) -> dict:
        return dict(self.manifest["y0"])

    def forecast(self, points, horizon, interval) -> dict:
        return self.steps[self.i]["forecast"] if self.i < len(self.steps) else {}

    def advance(self, u: dict) -> dict:
        if self.i >= len(self.steps):
            return {}
        rec = self.steps[self.i]
        if json.loads(_dump(u)) != rec["u"]:
            self.u_mismatches.append(self.i)
        self.i += 1
        return rec["y"]

    def kpi(self) -> dict:
        # First call after an advance is that step's KPI; a second call is the final KPI.
        if self.i > 0 and self.i not in self._kpi_seen:
            self._kpi_seen.add(self.i)
            return self.steps[self.i - 1]["kpi"]
        return self.result.get("final_kpi") or (self.steps[-1]["kpi"] if self.steps else {})

    def stop(self) -> None:
        self.testid = None


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

    @property
    def deterministic(self) -> bool:
        return self.error is None and not self.mismatched_steps and self.identical_steps == self.steps


def replay_run(run_dir: Path, out_dir: Path | None = None, log=lambda *_: None) -> ReplayReport:
    """Re-run a recorded run through the same code path with zero network calls."""
    sim = RecordedSimulator(run_dir)
    m = sim.manifest
    hours = len(sim.steps)
    if m["mode"] == "baseline":
        controller: BaselineController | AgentController = BaselineController()
    else:
        sup = m["supervisor"]
        controller = AgentController(
            supervisor=ReplaySupervisor(run_dir / "calls.jsonl", sup["model_key"]),
            envelope=Envelope(EnvelopeConfig(**m["envelope"])),
            budget=Budget(limit_usd=float(sup["budget_usd"])),
            electricity_price=m["electricity_price"],
            max_tokens=int(sup["max_tokens"]),
            effort=sup["effort"],
        )
    writer: RunWriter = RunWriter(out_dir) if out_dir is not None else NullWriter()
    error = None
    try:
        run_session(sim, controller, writer, m["scenario"], m["electricity_price"], hours=hours,
                    kpi_every=int(m.get("kpi_every", 1)), sim_info={"kind": "replay", "source": run_dir.name},
                    log=log)
    except ReplayMismatch as exc:
        error = str(exc)
        if out_dir is not None:
            writer.finish({"replay_error": error})
    if isinstance(writer, NullWriter):
        replayed = writer.steps
    else:
        replayed = load_jsonl(out_dir / "steps.jsonl")  # type: ignore[operator]
    mismatched = sorted(set(sim.u_mismatches))
    identical = 0
    for orig, new in zip(sim.steps, replayed):
        if orig.get("decision") == new.get("decision") and orig["u"] == new["u"]:
            identical += 1
        else:
            if orig["step"] not in mismatched:
                mismatched.append(orig["step"])
    if len(replayed) != len(sim.steps):
        mismatched.append(min(len(replayed), len(sim.steps)))
    calls = load_jsonl(run_dir / "calls.jsonl")
    counts = getattr(controller, "counts", {})
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
    )
