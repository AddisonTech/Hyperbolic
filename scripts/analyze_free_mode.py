"""Where a free-mode (prompt version 10) run left its suggestion, and what each departure was worth (0.13.0);
from 0.14.0 the same for a blind-mode (prompt version 11) run against its shadow strategy, with agreement,
and from 0.15.0 for a rules-in-words (prompt version 12) run, which shows the same observation and logs
the same shadow strategy, so everything said of blind mode below holds for it too.

    python scripts/analyze_free_mode.py RUN_DIR [--jobs N] [--out FILE]

Blind mode (0.14.0). A version 11 run shows the model no suggestion. Its reference is the version 9
strategy's action for the same observation, which the run logs every hour as shadow_strategy; here it
is worked out again from each recorded observation and checked against the log, so "suggestion" below
means the shadow strategy. There is no deviation_reason, so no hour is rejected for a missing one and
every departure has no reason. Agreement is the share of building-hours whose action is within the
0.10.0 tolerances of the shadow strategy, per device and with all three devices at once, over the
building-hours whose reply parsed (null counts as baseline_action; an end_trim counts as a cooling
disagreement). It is the measure the 0.14.0 acceptance rule's readings use.

Deviations. Every hour, building and device of the recorded reply is compared with the suggestion the
model saw (the version 9 strategy's action, shown in the observation), with the 0.10.0 tolerances
(0.002 for cooling, 0.005 for storage), and sorted into one class by what it did, using the 0.10.0
classes (scripts/analyze_deviations.py) with extra cooling split in two:

  precool        cooling above the suggestion before the day's top-price hours (some still ahead)
  extra_cooling  cooling above the suggestion at any other time

Each departure keeps the model's deviation_reason, so its stated hypothesis can be set beside what the
class did.

Attribution. The run's own replies are sent again on a fresh CityLearn month (its own month of the
month set, never the holdout) through its own envelope, with zero model calls:

  control   the replies as recorded. It must reproduce the run's KPIs exactly.
  <class>   that class's building-hours put back to the suggestion, worked out on the observation of
            the new run, so the rooms and batteries react to the change.
  all       every departure put back at once. It must equal the strategy run exactly.
  strategy  the scripted version 10 controller on its own: the suggestion every hour (v9 scripted).

A departure is any device whose recorded value is not exactly the suggestion's (null and a number are
different, since the envelope applies the unrounded baseline for null). Departures too small for the
0.10.0 classes go in their own class, small. In every replay, a device the model left at its suggestion
takes the suggestion of the new observation: once a put-back moves the rooms and batteries, the recorded
number belongs to a state that no longer exists, and the model's choice there was to follow. (0.11.0 kept
the recorded number in those hours, so its "every departure put back" row did not equal its strategy.)
A departure not being put back keeps its recorded value and its recorded deviation_reason, so a
building-hour the free-mode check rejected in the run (a departure with no reason) is rejected again.
A building-hour the check accepted in the run can, once the replay has moved away from it, differ from
the new suggestion by more than the tolerance without a reason; there a placeholder deviation_reason
is added in the evaluation only, so the replay does not invent a fallback the run never had. These are
evaluations, never recorded runs.

A class's worth is control minus the replay with it put back: negative dollars or KPI points mean the
departures saved money or improved the KPI, positive mean they cost. Dollars are CityLearn's own hourly
cost summed over the buildings and the month, kg the same for emissions.
"""

from __future__ import annotations

import argparse
import collections
import concurrent.futures as cf
import json
import multiprocessing as mp
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from analyze_deviations import CLASSES as BASE_CLASSES  # noqa: E402
from analyze_deviations import COOLING_TOL, STORAGE_TOL, classify, context, month_schema_for  # noqa: E402
from evaluate_hold import KPI_KEYS  # noqa: E402

from hyperbolic.envelope import DEVICE_KEYS, Envelope, EnvelopeConfig, parse_reply  # noqa: E402
from hyperbolic.model import (  # noqa: E402
    Budget,
    CallResult,
    RecordedReplySupervisor,
    ScriptedSupervisor,
    observation_from_request,
)
from hyperbolic.prompt import FREE_MODE_FROM, differing_devices, shadow_strategy  # noqa: E402
from hyperbolic.runner import AgentController, NullWriter, load_jsonl, run_session  # noqa: E402

CLASSES = {"precool": ("cooling", "cooled above the suggestion before the day's top-price hours"),
           **BASE_CLASSES,
           "extra_cooling": ("cooling", "cooled above the suggestion at any other time"),
           "small": ("any", "differed from the suggestion by less than the 0.10.0 class tolerances")}
PLACEHOLDER = "recorded action, replayed for evaluation"

# What a hypothesis says it is for, by keyword. A reason can name several.
CLAIMS = {
    "cost": re.compile(r"cost|cheap|price|\$|tariff|bill|sav", re.I),
    "carbon": re.compile(r"carbon|emission|clean|co2", re.I),
    "peak": re.compile(r"peak|shave|ramp|load factor|spike|smooth", re.I),
    "comfort": re.compile(r"comfort|too warm|too cool|too cold|overcool|overheat|setpoint|band", re.I),
}


def is_blind(obs: dict) -> bool:
    """A version 11 (blind mode) or version 12 (rules in words) observation: version 10's fields without the
    suggestion."""
    first = next(iter(obs["buildings"].values()))
    return "suggestion" not in first and "cooling_power_kw" in first


def suggestion_of(obs: dict) -> dict:
    """The reference each building is measured against: the suggestion shown in a version 10 observation,
    or for a version 11 observation the shadow strategy (the version 9 strategy) worked out on it."""
    first = next(iter(obs["buildings"].values()))
    if "suggestion" in first:
        return {b: s["suggestion"] for b, s in obs["buildings"].items()}
    if is_blind(obs):
        plan = shadow_strategy(obs)
        return {b: {d: plan[b][d] for d in DEVICE_KEYS} for b in obs["buildings"]}
    raise ValueError("this needs a prompt version 10 (free mode), 11 (blind mode) or 12 (rules in words) run")


def check_shadow(run_dir: Path) -> int:
    """For a blind-mode run, that the shadow_strategy logged each hour equals the version 9 strategy worked
    out again on that hour's recorded observation. Returns the hours checked (0 for a free-mode run)."""
    steps = {s["step"]: s for s in load_jsonl(run_dir / "steps.jsonl")}
    checked = 0
    for rec in load_jsonl(run_dir / "calls.jsonl"):
        obs = observation_from_request(rec["request"])
        if not is_blind(obs):
            return 0
        if steps[rec["step"]].get("shadow_strategy") != json.loads(json.dumps(shadow_strategy(obs))):
            raise ValueError(f"hour {rec['step']}: the logged shadow_strategy is not the strategy on its observation")
        checked += 1
    return checked


def _close(a: float, s: float, tol: float) -> bool:
    return abs(a - s) <= tol + 1e-9


def agreement(run_dir: Path) -> dict:
    """Share of building-hours whose action is within the 0.10.0 tolerances (COOLING_TOL for cooling,
    STORAGE_TOL for the tank and battery) of the reference (the shadow strategy in blind mode), per device
    and with all three at once. null counts as baseline_action on either side, and an end_trim is a
    cooling disagreement. Building-hours whose reply was unusable (no reply, or one the envelope's parse
    rejected) are left out and counted."""
    tol = {"cooling": COOLING_TOL, "dhw": STORAGE_TOL, "battery": STORAGE_TOL}
    agree = collections.Counter()
    total = unusable = 0
    for rec in load_jsonl(run_dir / "calls.jsonl"):
        obs = observation_from_request(rec["request"])
        names = tuple(obs["buildings"])
        proposal, err = parse_reply(rec["reply"].get("text"), names, end_trim=True)
        if err is not None:
            unusable += len(names)
            continue
        ref = suggestion_of(obs)
        for b in names:
            base = obs["buildings"][b]["baseline_action"]
            mine = proposal["buildings"][b]
            ok = {}
            for d in DEVICE_KEYS:
                a = base[d] if mine.get(d) is None else mine[d]
                s = base[d] if ref[b].get(d) is None else ref[b][d]
                ok[d] = (a is None and s is None) or (a is not None and s is not None and _close(a, s, tol[d]))
            if (proposal.get("end_trim") or {}).get(b) is not None:
                ok["cooling"] = False
            total += 1
            for d in DEVICE_KEYS:
                agree[d] += ok[d]
            agree["all"] += all(ok.values())
    share = {k: (agree[k] / total if total else None) for k in (*DEVICE_KEYS, "all")}
    return {"building_hours": total, "unusable_building_hours": unusable, "agree": dict(agree), "share": share}


def classify_v10(obs: dict, reply: dict) -> list[tuple[str, str]]:
    """(building, class) for every departure of a version 10 reply from its suggestion."""
    pp = obs["price_plan"]
    before_top = (not pp["flat_24h"]) and (not pp["top_price_now"]) and bool(pp["top_price_hours_ahead"])
    out = []
    for b, cls in classify(obs, reply, suggestion_of(obs)):
        if cls == "extra_cooling" and before_top:
            cls = "precool"
        out.append((b, cls))
    return out


def deviations(run_dir: Path) -> list[dict]:
    """Every departure in a recorded version 10 or 11 run, with its class, the model's and the reference's
    values, when it happened and the model's deviation_reason for that building and hour (None in blind
    mode). A blind-mode run's logged shadow_strategy is checked against its observations first."""
    check_shadow(run_dir)
    rows = []
    for rec in load_jsonl(run_dir / "calls.jsonl"):
        reply = _reply_of(rec)
        if reply is None:
            continue
        obs = observation_from_request(rec["request"])
        plan = suggestion_of(obs)
        classed = [(b, cls, CLASSES[cls][0]) for b, cls in classify_v10(obs, reply)]
        covered = {(b, d) for b, _, d in classed}
        for b in sorted(obs["buildings"]):
            for d in raw_departures(reply[b], plan[b]):
                if (b, d) not in covered:
                    classed.append((b, "small", d))
        for b, cls, device in classed:
            base = obs["buildings"][b]["baseline_action"].get(device) or 0.0
            mine, sug = reply[b].get(device), plan[b].get(device)
            rows.append({"step": rec["step"], "building": b, "class": cls, "device": device,
                         "model": base if mine is None else float(mine), "suggestion": base if sug is None else float(sug),
                         "reason": reply[b].get("deviation_reason"), **context(obs, b)})
    return rows


def _reply_of(rec: dict) -> dict | None:
    """A recorded reply as a JSON object with every building an object, or None (no reply, not JSON, or a
    building missing: the hour fell back, and there is no action of the model's to compare)."""
    text = rec["reply"].get("text")
    if not text:
        return None
    try:
        reply = json.loads(text)
    except ValueError:
        return None
    obs_buildings = observation_from_request(rec["request"])["buildings"]
    if not isinstance(reply, dict) or not all(isinstance(reply.get(b), dict) for b in obs_buildings):
        return None
    return reply


def raw_departures(sent: dict, suggestion: dict) -> list[str]:
    """Devices whose sent value is not exactly the suggestion's (null and a number differ)."""
    out = []
    for d in DEVICE_KEYS:
        a, s = sent.get(d), suggestion.get(d)
        if (a is None) != (s is None) or (a is not None and abs(float(a) - float(s)) > 1e-12):
            out.append(d)
    return out


def departures_of(run_dir: Path) -> set[tuple[int, str, str]]:
    """(step, building, device) of every raw departure in a recorded run, end_trim counted on cooling."""
    out = set()
    for rec in load_jsonl(run_dir / "calls.jsonl"):
        reply = _reply_of(rec)
        if reply is None:
            continue
        obs = observation_from_request(rec["request"])
        ref = suggestion_of(obs)
        for b in obs["buildings"]:
            acts = reply.get(b) or {}
            for d in raw_departures(acts, ref[b]):
                out.add((rec["step"], b, d))
            if acts.get("end_trim") is not None:
                out.add((rec["step"], b, "cooling"))
    return out


def rejected_of(run_dir: Path) -> set[tuple[int, str]]:
    """(step, building) where the run's reply departed from the suggestion without a deviation_reason,
    which the free-mode check rejected (that hour fell back). Blind mode has no such check: always empty."""
    out = set()
    for rec in load_jsonl(run_dir / "calls.jsonl"):
        text = rec["reply"].get("text")
        if not text:
            continue
        obs = observation_from_request(rec["request"])
        if is_blind(obs):
            return set()
        try:
            reply = json.loads(text)
        except ValueError:
            continue
        for b, s in obs["buildings"].items():
            acts = reply.get(b)
            if isinstance(acts, dict) and acts.get("deviation_reason") is None and \
                    differing_devices(acts, s["suggestion"], s["baseline_action"], acts.get("end_trim")):
                out.add((rec["step"], b))
    return out


def claims(reason: str | None) -> list[str]:
    return [] if not reason else [k for k, rx in CLAIMS.items() if rx.search(reason)]


class PutBackSupervisor(RecordedReplySupervisor):
    """A free-mode run's replies, re-sent on the new observation: each recorded departure keeps its
    value and reason unless listed in replace, every other device takes the new suggestion, and a
    placeholder deviation_reason goes only where a building-hour the run accepted would now be rejected
    (see the module note)."""

    kind = "recorded"

    def __init__(self, calls_path: Path, model_key: str, replace: set[tuple[int, str, str]],
                 departures: set[tuple[int, str, str]], rejected: set[tuple[int, str]]) -> None:
        super().__init__(calls_path, model_key)
        self.replace, self.departures, self.rejected = set(replace), set(departures), set(rejected)

    def call(self, step: int, request: dict) -> CallResult:
        res = super().call(step, request)
        if res.text is None:
            return res
        try:
            reply = json.loads(res.text)
        except ValueError:
            return res
        obs = observation_from_request(request)
        if not isinstance(reply, dict):
            return res
        ref = suggestion_of(obs)
        blind = is_blind(obs)
        for b, ob in obs["buildings"].items():
            acts = reply.get(b)
            if not isinstance(acts, dict):
                continue
            kept = {d for d in DEVICE_KEYS if (step, b, d) in self.departures and (step, b, d) not in self.replace}
            for d in DEVICE_KEYS:
                if d not in kept:
                    acts[d] = ref[b][d]
            if "cooling" not in kept:
                acts["end_trim"] = None
            # Blind mode has no deviation_reason: its schema allows none, so nothing is added.
            if not blind and (step, b) not in self.rejected and acts.get("deviation_reason") is None and \
                    differing_devices(acts, ref[b], ob["baseline_action"], acts.get("end_trim")):
                acts["deviation_reason"] = PLACEHOLDER
        res.text = json.dumps(reply)
        return res


class SeriesWriter(NullWriter):
    """Keeps each hour's dollars, kg and grid draw summed over the buildings."""

    def __init__(self) -> None:
        super().__init__()
        self.usd = self.kg = 0.0
        self.grid_kwh: list[float] = []

    def step(self, rec: dict) -> None:
        o = rec["outcome"].values()
        self.usd += sum(x["cost_usd"] for x in o)
        self.kg += sum(x["emission_kg"] for x in o)
        self.grid_kwh.append(sum(x["grid_kwh"] for x in o))


def _replay(job: tuple[str, str, list]) -> dict:
    import tempfile

    import torch

    torch.set_num_threads(1)  # one simulation per process
    from hyperbolic.sim import CityLearnSimulator

    name, run, replace = job
    run_dir = Path(run)
    m = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    sup = m["supervisor"]
    if int(sup["prompt_version"]) < FREE_MODE_FROM:
        raise ValueError("this needs a prompt version 10 (free mode) run")
    calls = run_dir / "calls.jsonl"
    if name == "strategy":
        supervisor = ScriptedSupervisor(sup["model_key"])
    elif name == "control":
        supervisor = RecordedReplySupervisor(calls, sup["model_key"])
    else:
        supervisor = PutBackSupervisor(calls, sup["model_key"], {tuple(x) for x in replace}, departures_of(run_dir),
                                       rejected_of(run_dir))
    with tempfile.TemporaryDirectory() as tmp:
        schema = month_schema_for(m, Path(tmp))
        ctl = AgentController(supervisor=supervisor, envelope=Envelope(EnvelopeConfig.from_manifest(m["envelope"])),
                              budget=Budget(limit_usd=1e9), max_tokens=int(sup["max_tokens"]), effort=sup["effort"],
                              prompt_version=int(sup["prompt_version"]), prompt_cache=bool(sup.get("prompt_cache")))
        writer = SeriesWriter()
        res = run_session(CityLearnSimulator(control=True, schema=schema), ctl, writer, hours=m.get("hours_limit"),
                          sim_info={"kind": "citylearn", "control": True}, log=lambda *_: None)
    return {"name": name, "kpis": {k: res["district_kpis"][k] for k in KPI_KEYS}, "usd": round(writer.usd, 4),
            "kg": round(writer.kg, 3), "clamped": res["clamped_steps"], "fallback": res["fallback_steps"],
            "steps": res["steps"]}


def attribute(run_dir: Path, rows: list[dict], jobs: int | None = None) -> dict:
    points = collections.defaultdict(set)
    for r in rows:
        points[r["class"]].add((r["step"], r["building"], r["device"]))
    classes = [c for c in CLASSES if points[c]]
    work = [("control", str(run_dir), []), ("strategy", str(run_dir), [])]
    work += [(c, str(run_dir), sorted(points[c])) for c in classes]
    if classes:
        every = departures_of(run_dir)
        work.append(("all", str(run_dir), sorted(every)))
        # Two groups across the classes: the hours the free-mode check rejected (a departure with no
        # reason makes the whole hour fall back), and the departures that came with a hypothesis.
        bad_steps = {s for s, _ in rejected_of(run_dir)}
        reasoned = {(r["step"], r["building"]) for r in rows if r["reason"]}
        if bad_steps:
            work.append(("rejected hours", str(run_dir), sorted(p for p in every if p[0] in bad_steps)))
        if reasoned:
            work.append(("reasoned", str(run_dir), sorted(p for p in every if (p[0], p[1]) in reasoned)))
    # spawn, not fork: forking after torch has started its threads can deadlock.
    with cf.ProcessPoolExecutor(max_workers=jobs, mp_context=mp.get_context("spawn")) as pool:
        return {r["name"]: r for r in pool.map(_replay, work)}


def report(run_dir: Path, rows: list[dict], results: dict) -> dict:
    recorded = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))["district_kpis"]
    control = results["control"]
    out = {"run": run_dir.name, "control_reproduces": all(abs(control["kpis"][k] - recorded[k]) < 1e-9
                                                          for k in KPI_KEYS if recorded.get(k) is not None),
           "control": control, "strategy": results["strategy"], "classes": {}}
    for cls in CLASSES:
        mine = [r for r in rows if r["class"] == cls]
        if not mine:
            continue
        r = results[cls]
        stated = collections.Counter(c for x in mine for c in claims(x["reason"]))
        out["classes"][cls] = {
            "what": CLASSES[cls][1], "building_hours": len(mine), "hours": len({x["step"] for x in mine}),
            "mean_gap": round(sum(abs(x["model"] - x["suggestion"]) for x in mine) / len(mine), 4),
            "worth_usd": round(control["usd"] - r["usd"], 4), "worth_kg": round(control["kg"] - r["kg"], 3),
            "worth_kpi": {k: round(control["kpis"][k] - r["kpis"][k], 6) for k in KPI_KEYS},
            "fallback_in_replay": r["fallback"],
            "reasons_given": sum(1 for x in mine if x["reason"]), "claims": dict(stated),
            "sample_reasons": [x["reason"] for x in mine if x["reason"]][:5],
            "when": {k: dict(collections.Counter(x[k] for x in mine).most_common()) for k in ("price", "building")},
        }
    if "all" in results:
        out["all_equals_strategy"] = (results["all"]["kpis"] == results["strategy"]["kpis"]
                                      and results["all"]["usd"] == results["strategy"]["usd"])
    for name in ("all", "rejected hours", "reasoned"):
        if name in results:
            r = results[name]
            out[name] = {"worth_usd": round(control["usd"] - r["usd"], 4), "worth_kg": round(control["kg"] - r["kg"], 3),
                         "worth_kpi": {k: round(control["kpis"][k] - r["kpis"][k], 6) for k in KPI_KEYS},
                         "fallback_in_replay": r["fallback"]}
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("run_dir", type=Path)
    ap.add_argument("--jobs", type=int, default=None)
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args(argv)
    rows = deviations(args.run_dir)
    print(f"{len(rows)} departures in {len({r['step'] for r in rows})} hours")
    rep = report(args.run_dir, rows, attribute(args.run_dir, rows, args.jobs))
    print(f"control reproduces the run's KPIs: {'yes' if rep['control_reproduces'] else 'NO'}")
    print(f"{'class':<22}{'b-hours':>8}{'$ worth':>10}{'cost':>10}{'emis':>10}{'disc':>10}{'ramp':>10}"
          f"{'daily pk':>10}{'all pk':>10}")
    for cls, c in rep["classes"].items():
        k = c["worth_kpi"]
        print(f"{cls:<22}{c['building_hours']:>8}{c['worth_usd']:>+10.2f}{k['cost_total']:>+10.4f}"
              f"{k['carbon_emissions_total']:>+10.4f}{k['discomfort_proportion']:>+10.4f}{k['ramping_average']:>+10.4f}"
              f"{k['daily_peak_average']:>+10.4f}{k['all_time_peak_average']:>+10.4f}")
    for name in ("all", "rejected hours", "reasoned"):
        if name in rep:
            k = rep[name]["worth_kpi"]
            print(f"{name:<22}{'':>8}{rep[name]['worth_usd']:>+10.2f}{k['cost_total']:>+10.4f}"
                  f"{k['carbon_emissions_total']:>+10.4f}{k['discomfort_proportion']:>+10.4f}{k['ramping_average']:>+10.4f}"
                  f"{k['daily_peak_average']:>+10.4f}{k['all_time_peak_average']:>+10.4f}")
    if "all" in rep:
        same = rep["all_equals_strategy"]
        print(f"every departure put back equals the strategy run: {'yes' if same else 'NO'}")
    shadow_hours = check_shadow(args.run_dir)
    agr = agreement(args.run_dir)
    rep["agreement"] = agr
    if shadow_hours:
        print(f"shadow_strategy matches the strategy on every recorded observation ({shadow_hours} hours)")
    print(f"agreement over {agr['building_hours']} building-hours ({agr['unusable_building_hours']} unusable left out): "
          + ", ".join(f"{k} {100 * v:.1f}%" for k, v in agr["share"].items() if v is not None))
    if args.out:
        args.out.write_text(json.dumps({"rows": rows, "report": rep}, indent=2), encoding="utf-8")
        print(f"written to {args.out}")
    return 0 if rep["control_reproduces"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
