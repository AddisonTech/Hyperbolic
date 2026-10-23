"""Where a recorded prompt version 7 run left its own strategy, and what each departure cost (0.10.0).

    python scripts/analyze_deviations.py RUN_DIR [--jobs N] [--out FILE]

Deviations. For every hour, building and device the recorded reply is compared with what the
scripted version 7 strategy (strategy_plan_v7: strategy_battery, the version 5 cooling trim fitted
into cooling_range, the tank at 0) sends for the very observation the model saw. A value counts as
the strategy's within 0.002 for cooling (the trim hold's rounding allowance) and 0.005 for storage
(the strategy truncates to 3 decimals). Each departure falls into exactly one class (CLASSES),
counted with when it happened: the price period, occupancy, outdoor temperature, the battery's
state of charge, how far the room was from its setpoint, and the building.

Attribution. The run's own replies are sent again on a fresh CityLearn month through its own rules
(the 0.9.0 envelope, unchanged), with zero model calls:

  control   the replies as recorded. It must reproduce the run's published KPIs exactly.
  <class>   the replies with that one class replaced by the strategy's action, worked out on the
            observation of the new run, so the battery and rooms react to the change.
  all       every class replaced at once.
  strategy  the scripted version 7 strategy on its own: the gap the classes are measured against.

Estimates for prompt version 8, the same way, with the version 8 strategy (strategy_plan_v8, which
reads only what a version 7 observation already has):

  v8 top class   trim_not_started replaced by the version 8 strategy's cooling.
  v8 cooling     every hour's cooling from the version 8 strategy, the model's own battery and tank:
                 a model that sends strategy.cooling as given and its battery as it did.
  v8 strategy    the scripted version 8 strategy on its own.

A class's share of the gap is (control - class) / (control - strategy) on each KPI. The classes
interact (a trim started earlier changes the rooms later), so the shares need not add up to 1.
These are evaluations, never recorded runs.
"""

from __future__ import annotations

import argparse
import collections
import concurrent.futures as cf
import json
import multiprocessing as mp
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from evaluate_hold import KPI_KEYS  # noqa: E402

from hyperbolic.envelope import Envelope, EnvelopeConfig  # noqa: E402
from hyperbolic.model import (  # noqa: E402
    Budget,
    CallResult,
    RecordedReplySupervisor,
    ScriptedSupervisor,
    StrategyParamsV7,
    observation_from_request,
    strategy_plan_v7,
    strategy_plan_v8,
)
from hyperbolic.runner import AgentController, NullWriter, load_jsonl, run_session  # noqa: E402

COOLING_TOL = 0.002  # EnvelopeConfig.trim_min_depth: a trim is cooling more than this below the baseline
STORAGE_TOL = 0.005

# class -> (device, what the model did against the strategy)
CLASSES = {
    "trim_not_started": ("cooling", "no trim in an occupied, overcooled room where the strategy trims"),
    "trim_shallower": ("cooling", "a shallower trim than the strategy's"),
    "trim_deeper": ("cooling", "a deeper trim than the strategy's"),
    "trim_unwanted": ("cooling", "a trim where the strategy has none"),
    "trim_ended_early": ("cooling", "ended a held trim early with end_trim"),
    "extra_cooling": ("cooling", "cooling above the strategy's"),
    "top_discharge_short": ("battery", "discharged less than the strategy in a top-price hour"),
    "top_discharge_over": ("battery", "discharged more than the strategy in a top-price hour"),
    "shave_skipped": ("battery", "skipped or cut a peak-shaving discharge"),
    "charge_skipped": ("battery", "charged less than the strategy in a charging hour"),
    "charge_over": ("battery", "charged more than the strategy in a charging hour"),
    "charge_off_plan": ("battery", "charged when the strategy holds or only stores solar"),
    "discharge_off_plan": ("battery", "discharged when the strategy does not"),
    "dhw_used": ("dhw", "used the hot water tank (the strategy leaves it at 0)"),
}


def battery_mode(obs: dict, b: str, strategy_battery: float, p: StrategyParamsV7 | None = None) -> str:
    """Which branch of battery_plan_v7 the strategy is in for building b: top, shave, solar, charge or idle."""
    p = p or StrategyParamsV7()
    s, pk = obs["buildings"][b], obs["peak"]
    load = s["load_now_kwh"]
    if load is None or not s["battery"]["capacity_kwh"]:
        return "idle"
    if obs["price_plan"]["top_price_now"] and load > 0:
        return "top"
    now, forecast = pk["district_load_now_kwh"], pk["forecast_today_kwh"]
    if p.shave > 0 and now is not None and forecast and now >= p.shave * forecast and load > 0:
        return "shave"
    if load < -0.05:
        return "solar"
    return "charge" if strategy_battery > 0 else "idle"


def _value(acts: dict, device: str, base: float) -> float:
    return base if acts.get(device) is None else float(acts[device])


def classify(obs: dict, reply: dict, strategy: dict | None = None) -> list[tuple[str, str]]:
    """(building, class) for every departure of a version 7 reply from the strategy on this observation."""
    strategy = strategy or strategy_plan_v7(obs)
    out = []
    for b, s in sorted(obs["buildings"].items()):
        mine, plan = reply[b], strategy[b]
        base = s["baseline_action"]["cooling"]
        hc, sc = _value(mine, "cooling", base), _value(plan, "cooling", base)
        trimmed, planned = hc < base - COOLING_TOL, sc < base - COOLING_TOL
        if mine.get("end_trim"):
            out.append((b, "trim_ended_early"))
        elif abs(hc - sc) > COOLING_TOL:
            if planned and not trimmed:
                out.append((b, "trim_not_started" if s["trim"]["state"] == "off" else "trim_shallower"))
            elif planned:
                out.append((b, "trim_shallower" if hc > sc else "trim_deeper"))
            elif trimmed:
                out.append((b, "trim_unwanted"))
            elif hc > sc:
                out.append((b, "extra_cooling"))
        hb, sb = _value(mine, "battery", 0.0), _value(plan, "battery", 0.0)
        if abs(hb - sb) > STORAGE_TOL:
            mode = battery_mode(obs, b, sb)
            if mode == "top":
                out.append((b, "top_discharge_short" if hb > sb else "top_discharge_over"))
            elif mode == "shave" and hb > sb:
                out.append((b, "shave_skipped"))
            elif mode == "charge":
                out.append((b, "charge_skipped" if hb < sb else "charge_over"))
            elif hb > sb:
                out.append((b, "charge_off_plan"))
            else:
                out.append((b, "discharge_off_plan"))
        if abs(_value(mine, "dhw", 0.0)) > STORAGE_TOL:
            out.append((b, "dhw_used"))
    return out


def _bin(v: float | None, edges: tuple[float, ...], labels: tuple[str, ...]) -> str:
    if v is None:
        return "n/a"
    for edge, label in zip(edges, labels):
        if v < edge:
            return label
    return labels[-1]


def context(obs: dict, b: str) -> dict:
    """When a departure happened."""
    pp, s = obs["price_plan"], obs["buildings"][b]
    period = ("flat" if pp["flat_24h"] else "top" if pp["top_price_now"]
              else "low" if pp["now"] <= pp["low_24h"] + 1e-9 else "mid")
    return {
        "price": period,
        "occupied": "occupied" if s["occupied"] else "empty",
        "outdoor_c": _bin(obs["outdoor_c"], (22.0, 26.0, 30.0), ("<22", "22-26", "26-30", ">=30")),
        "soc": _bin(s["battery"]["soc"], (0.3, 0.6, 0.9), ("<0.3", "0.3-0.6", "0.6-0.9", ">=0.9")),
        "room": _bin(s["indoor_vs_setpoint_c"], (-1.5, -1.0, -0.5, 0.0),
                     ("<-1.5", "-1.5 to -1", "-1 to -0.5", "-0.5 to 0", ">=0")),
        "building": b,
    }


def deviations(run_dir: Path) -> list[dict]:
    """Every departure in a recorded version 7 run: step, building, class, device, the model's and the
    strategy's values and when it happened."""
    rows = []
    for rec in load_jsonl(run_dir / "calls.jsonl"):
        text = rec["reply"].get("text")
        if not text:
            continue
        obs = observation_from_request(rec["request"])
        if "cooling_range" not in next(iter(obs["buildings"].values())):
            raise ValueError("this needs a prompt version 7 run")
        reply, plan = json.loads(text), strategy_plan_v7(obs)
        for b, cls in classify(obs, reply, plan):
            device = CLASSES[cls][0]
            base = obs["buildings"][b]["baseline_action"].get(device) or 0.0
            rows.append({"step": rec["step"], "building": b, "class": cls, "device": device,
                         "model": _value(reply[b], device, base), "strategy": _value(plan[b], device, base),
                         **context(obs, b)})
    return rows


def summary(rows: list[dict]) -> dict:
    """Counts and size per class, and per class the split by each context field."""
    out = {}
    for cls in CLASSES:
        mine = [r for r in rows if r["class"] == cls]
        if not mine:
            continue
        out[cls] = {"count": len(mine), "hours": len({r["step"] for r in mine}),
                    "mean_gap": round(sum(abs(r["model"] - r["strategy"]) for r in mine) / len(mine), 4),
                    **{k: dict(collections.Counter(r[k] for r in mine).most_common())
                       for k in ("price", "occupied", "outdoor_c", "soc", "room", "building")}}
    return out


PLANS = {7: strategy_plan_v7, 8: strategy_plan_v8}


class ReplacingSupervisor(RecordedReplySupervisor):
    """A recorded run's replies with the listed (step, building, device) values replaced by the
    version 7 (or 8) strategy's, worked out on the request actually sent this hour."""

    kind = "recorded"

    def __init__(self, calls_path: Path, model_key: str, replace: set[tuple[int, str, str]], plan: int = 7) -> None:
        super().__init__(calls_path, model_key)
        self.by_step: dict[int, set[tuple[str, str]]] = collections.defaultdict(set)
        for s, b, d in replace:
            self.by_step[s].add((b, d))
        self.plan = PLANS[plan]

    def call(self, step: int, request: dict) -> CallResult:
        res = super().call(step, request)
        points = self.by_step.get(step)
        if res.text is None or not points:
            return res
        reply, plan = json.loads(res.text), self.plan(observation_from_request(request))
        for b, d in points:
            reply[b][d] = plan[b][d]
            if d == "cooling":
                reply[b]["end_trim"] = None
        res.text = json.dumps(reply)
        return res


def _replay(job: tuple[str, str, list, int]) -> dict:
    """job: (name, run dir, points to replace, strategy version). control replays the recorded replies;
    strategy and v8 strategy run that version's scripted strategy on its own."""
    import torch

    torch.set_num_threads(1)  # one simulation per process
    from hyperbolic.sim import CityLearnSimulator

    name, run, replace, plan = job
    run_dir = Path(run)
    m = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    sup = m["supervisor"]
    calls = run_dir / "calls.jsonl"
    version = int(sup["prompt_version"])
    if name in ("strategy", "v8 strategy"):
        supervisor, version = ScriptedSupervisor(sup["model_key"]), plan
    elif name == "control":
        supervisor = RecordedReplySupervisor(calls, sup["model_key"])
    else:
        supervisor = ReplacingSupervisor(calls, sup["model_key"], {tuple(x) for x in replace}, plan)
    ctl = AgentController(supervisor=supervisor, envelope=Envelope(EnvelopeConfig.from_manifest(m["envelope"])),
                          budget=Budget(limit_usd=float(sup["budget_usd"])), max_tokens=int(sup["max_tokens"]),
                          effort=sup["effort"], prompt_version=version)
    res = run_session(CityLearnSimulator(control=True), ctl, NullWriter(), hours=m.get("hours_limit"),
                      sim_info={"kind": "citylearn", "control": True}, log=lambda *_: None)
    return {"name": name, "kpis": {k: res["district_kpis"][k] for k in KPI_KEYS},
            "clamped": res["clamped_steps"], "fallback": res["fallback_steps"]}


def attribute(run_dir: Path, rows: list[dict], jobs: int | None = None, classes: list[str] | None = None,
              estimates: bool = True) -> dict:
    """KPIs for control, each class replaced on its own, all classes, the strategy and, with
    estimates, the three prompt version 8 replays."""
    points = collections.defaultdict(set)
    for r in rows:
        points[r["class"]].add((r["step"], r["building"], r["device"]))
    classes = [c for c in (classes or CLASSES) if points[c]]
    every = sorted(set().union(*(points[c] for c in classes))) if classes else []
    work = [("control", str(run_dir), [], 7), ("strategy", str(run_dir), [], 7)]
    work += [(c, str(run_dir), sorted(points[c]), 7) for c in classes] + [("all", str(run_dir), every, 7)]
    if estimates:
        steps = sorted({r["step"] for r in load_jsonl(run_dir / "calls.jsonl")})
        buildings = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))["buildings"]
        work += [("v8 top class", str(run_dir), sorted(points["trim_not_started"]), 8),
                 ("v8 cooling", str(run_dir), [(s, b, "cooling") for s in steps for b in buildings], 8),
                 ("v8 strategy", str(run_dir), [], 8)]
    # spawn, not fork: forking after torch has started its threads can deadlock.
    with cf.ProcessPoolExecutor(max_workers=jobs, mp_context=mp.get_context("spawn")) as pool:
        results = {r["name"]: r for r in pool.map(_replay, work)}
    return results


def shares(results: dict) -> dict[str, dict[str, float | None]]:
    """Each class's share of the gap between control and the strategy, per KPI."""
    c, s = results["control"]["kpis"], results["strategy"]["kpis"]
    out = {}
    for name, r in results.items():
        if name in ("control", "strategy") or name.startswith("v8 "):
            continue
        out[name] = {k: None if abs(c[k] - s[k]) < 1e-6 else round((c[k] - r["kpis"][k]) / (c[k] - s[k]), 4)
                     for k in KPI_KEYS}
    return out


SHOW = ("cost_total", "carbon_emissions_total", "discomfort_proportion", "discomfort_hot_proportion",
        "ramping_average", "daily_peak_average", "all_time_peak_average")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("run_dir", type=Path)
    ap.add_argument("--jobs", type=int, default=None, help="parallel simulations (default: one per CPU)")
    ap.add_argument("--out", type=Path, default=None, help="optionally write every result as JSON")
    args = ap.parse_args(argv)
    rows = deviations(args.run_dir)
    summ = summary(rows)
    print(f"{args.run_dir.name}: departures from the version 7 strategy, by class (building-hours)")
    for cls, s in sorted(summ.items(), key=lambda x: -x[1]["count"]):
        print(f"  {cls:<20} {s['count']:>4} in {s['hours']:>3} hours, mean gap {s['mean_gap']:.4f}: {CLASSES[cls][1]}")
        for k in ("price", "occupied", "outdoor_c", "soc", "room", "building"):
            print(f"      {k:<9} " + ", ".join(f"{v} {n}" for v, n in s[k].items()))
    results = attribute(args.run_dir, rows, args.jobs)
    published = json.loads((args.run_dir / "result.json").read_text(encoding="utf-8"))["district_kpis"]
    if any(results["control"]["kpis"][k] != published[k] for k in KPI_KEYS):
        print("control does not reproduce the published KPIs", file=sys.stderr)
        return 1
    print("\ncontrol reproduces the published KPIs exactly: yes")
    sh = shares(results)
    order = ["control", "strategy", "all", *sorted((n for n in sh if n != "all"),
                                                    key=lambda n: -(sh[n]["cost_total"] or 0.0))]
    print(f"  {'replay':<20}" + "".join(f"{k[:14]:>15}" for k in SHOW) + f"{'clamped':>9}")
    for n in order:
        r = results[n]
        print(f"  {n:<20}" + "".join(f"{r['kpis'][k]:>15.4f}" for k in SHOW) + f"{r['clamped']:>9}")
    print("\nshare of the control to strategy gap explained")
    for n in order[2:]:
        print(f"  {n:<20}" + "".join(f"{'n/a' if sh[n][k] is None else format(sh[n][k], '.2f'):>15}" for k in SHOW))
    print("\nestimates for prompt version 8: the model's replies with the version 8 strategy filled in")
    for n in ("control", "v8 top class", "v8 cooling", "v8 strategy"):
        r = results[n]
        print(f"  {n:<20}" + "".join(f"{r['kpis'][k]:>15.4f}" for k in SHOW) + f"{r['clamped']:>9}")
    if args.out:
        args.out.write_text(json.dumps({"summary": summ, "results": results, "shares": sh}, indent=2, sort_keys=True),
                            encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
