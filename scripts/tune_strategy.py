"""Pick the scripted strategy's numbers on a separate 2023 dataset, never the reported month.

    python scripts/tune_strategy.py                # version 5 grid (0.7.0)
    python scripts/tune_strategy.py --quick        # the shipped version 5 defaults only
    python scripts/tune_strategy.py --version 4    # the 0.6.0 version 4 search, as it was run
    python scripts/tune_strategy.py --version 6    # 0.8.0 check: the trim hold, nothing tuned
    python scripts/tune_strategy.py --version 7    # 0.9.0 battery plan without step changes
    python scripts/tune_strategy.py --version 8    # 0.10.0 extra cooling in a warm room

Tuning set: citylearn_challenge_2023_phase_2_online_evaluation_1 from CityLearn v3.0.2, copied
unchanged into scripts/tuning_data. It has the same three buildings, batteries and LSTM models as
the reported phase 2 local evaluation month, but June, July and August of a different period:
other weather, loads, solar, carbon intensity and tariff, and no hour in common with it. Each
month is run as its own episode, the way the reported month is.

hyperbolic.model.strategy_plan_v4 executes the version 4 prompt's strategy literally, and
the prompt states the numbers it takes (StrategyParams), so tuning one tunes the other. A candidate qualifies when,
averaged over the three months, it is at least as comfortable as the baseline, keeps the daily
and all-time peaks, ramping and the daily load factor at or below the baseline's, and beats the
0.4.0 rule-based controller on both cost and emissions. The qualifying candidate with the lowest
cost plus emissions wins. The envelope's spread check has no tuned number: it uses each battery's
own efficiency curve and standing loss.

Version 5 (0.7.0) searches how strategy_plan_v5 smooths the district load (StrategyParamsV5). A
candidate qualifies when, averaged over the three
months, ramping is below the baseline and cost, emissions, discomfort and both peaks are no worse
than the 0.6.0 tuned version 4 strategy on the same months. The qualifying candidate with the
lowest ramping plus daily load factor wins, cost plus emissions breaking ties.

Version 6 (0.8.0) tunes nothing. The envelope's trim hold takes its numbers from the version 5
strategy (hold within 0.5 C, ease by 0.02 per hour), and the check runs the shipped version 5
strategy through the 0.7.0 rules and through the 0.8.0 rules (prompt version 6, trim hold on),
so its effect is measured on the tuning months before anything is reported on the test month.
The version 4 and 5 searches run with the 0.7.0 rules they were made with.

Version 7 (0.9.0) searches the battery plan's smoothing (StrategyParamsV7: the soft cap on how fast
a battery action may rise, on charging and discharging or on a discharge winding down only, valley
filling, and the charge rate) with the 0.8.0 rules, unchanged.
The strategy keeps every action inside the ranges the version 7 observation shows. A cap of 1 is
no cap, so the grid includes version 6's own battery plan (the shipped StrategyParamsV7), and that
candidate is the reference: the cooling is the same in every candidate, so only the battery plan
differs. A candidate qualifies when, averaged over the three months, ramping is below the
reference's and cost, emissions, discomfort and both peaks are no worse than it. The qualifying
candidate with the lowest ramping plus daily load factor wins, cost plus emissions breaking ties;
with none, the reference stays. The version 6 strategy is printed beside them.

Version 8 (0.10.0) searches the extra cooling the strategy gives an occupied room that runs warm
(StrategyParamsV8: how far above its setpoint, how much above the baseline action, and over how
many degrees it ramps in) and a night without trims (StrategyParamsV8.night_from_hour and
night_until_hour: none starts and a held one is ended, so the room cools back to the reference's
cushion overnight), alone and together, with the 0.8.0 rules, unchanged. The reference is the shipped version 7
strategy. Comfort comes first, as in the prompt's goals: a candidate qualifies when its too-warm
share is at or below the baseline's on every tuning month, its mean too-cool share is no more than
0.001 above the reference's, and its mean ramping and both peaks stay at or below the baseline's.
The qualifying candidate with the lowest cost plus emissions wins, the lower too-warm share
breaking ties; with none, no extra cooling is shipped. (A first rule that also held cost,
emissions, both peaks and ramping within 0.001 of the reference qualified none of the 36: the
cheapest full fix costs about 0.002 of cost, and the night rule costs more and clears no warm hour.)
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import itertools
import json
import multiprocessing as mp
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hyperbolic import months as mo  # noqa: E402
from hyperbolic.envelope import Envelope, EnvelopeConfig  # noqa: E402
from hyperbolic.model import (  # noqa: E402
    Budget,
    ScriptedSupervisor,
    StrategyParams,
    StrategyParamsV5,
    StrategyParamsV7,
    StrategyParamsV8,
)
from hyperbolic.runner import AgentController, BaselineController, NullWriter, run_session  # noqa: E402

TUNING_DATASET = mo.TUNING_DATASET
KEYS = ("cost_total", "carbon_emissions_total", "discomfort_proportion", "daily_peak_average", "all_time_peak_average",
        "ramping_average", "daily_one_minus_load_factor_average")
COMFORT = ("discomfort_cold_proportion", "discomfort_hot_proportion")
# A ratio counts as at or below the baseline's to four decimals: the baseline action under active
# control rounds the heat pump fraction, which by itself moves a ratio by about 1e-5.
TOLERANCE = 5e-5

START = asdict(StrategyParams(cold_margin_c=1.0, cold_trim=0.15, cold_ramp_c=0.0, charge_rate=0.25, shave=0.0,
                              even_discharge=False))
GRID = {
    "cold_margin_c": (0.5, 1.0, 1.5),
    "cold_trim": (0.05, 0.1, 0.15),
    "cold_ramp_c": (0.0, 1.0),
    "charge_rate": (0.15, 0.25),
    "shave": (0.0, 0.9, 1.0),
    "even_discharge": (False, True),
}
# Version 5: the smoothing knobs, around the shipped version 4 numbers. A trim_step of 1 releases a
# trim at once. An evening reserve was tried at 0.03, 0.05 and 0.1: it lowers ramping further but
# raises cost above the 0.6.0 strategy's on every setting, so it stays at 0 and out of the grid.
GRID_V5 = {
    "trim_hold_c": (0.0, 0.25, 0.5),
    "trim_step": (0.02, 0.05, 1.0),
    "charge_step": (0.05, 0.15),
}
# Version 7: the battery plan's smoothing, everything else at the shipped version 5 numbers.
GRID_V7 = {
    "rise_step": (1.0, 0.25, 0.15, 0.1, 0.05),
    "rise_charge": (True, False),
    "fill_valley": (False, True),
    "charge_rate": (0.1, 0.15),
}
# Version 8: everything else at the shipped version 7 numbers. Two families and their mix: extra
# cooling in a warm room (no night rule), no trim at night (no extra cooling), and the night rule
# with the two mildest boosts that cleared every warm hour.
GRID_V8_WARM = {
    "warm_margin_c": (0.5, 1.0, 1.5),
    "warm_boost": (0.05, 0.1, 0.15),
    "warm_ramp_c": (0.0, 1.0),
}
GRID_V8_NIGHT = {
    "night_from_hour": (18, 20, 22),
    "night_until_hour": (5, 7),
}
GRID_V8_MIX = ({"warm_margin_c": 1.5, "warm_boost": 0.1, "warm_ramp_c": 0.0},
               {"warm_margin_c": 1.0, "warm_boost": 0.1, "warm_ramp_c": 1.0})
GRID_V8 = (*GRID_V8_WARM, *GRID_V8_NIGHT)
V8_SLACK = 0.001


def month_datasets(out: Path) -> list[Path]:
    """One dataset folder per calendar month of the tuning set, each a full episode (hyperbolic.months)."""
    return [mo.month_schema(m, out).parent for m in mo.months() if m.rows is not None]


def kpis(job: tuple[str, dict | None, str]) -> dict:
    """job: (kind, params or None, schema path). kind is baseline, rule, strategy (version 4),
    strategy5 (version 5), strategy6 (version 5's strategy with the 0.8.0 trim hold), strategy7
    (the version 7 strategy, same rules) or strategy8 (the version 8 strategy, same rules)."""
    import torch

    torch.set_num_threads(1)  # one simulation per process
    from hyperbolic.sim import CityLearnSimulator

    kind, params, schema = job
    if kind == "baseline":
        controller, control = BaselineController(), False
    elif kind == "rule":
        controller = AgentController(ScriptedSupervisor(), Envelope(EnvelopeConfig.v040()), Budget(1.0), prompt_version=3)
        control = True
    elif kind == "strategy":
        controller = AgentController(ScriptedSupervisor(strategy=StrategyParams(**params)),
                                     Envelope(EnvelopeConfig.v070()), Budget(1.0), prompt_version=4)
        control = True
    elif kind == "strategy5":
        controller = AgentController(ScriptedSupervisor(strategy_v5=StrategyParamsV5(**params)),
                                     Envelope(EnvelopeConfig.v070()), Budget(1.0), prompt_version=5)
        control = True
    elif kind == "strategy6":  # the same strategy, prompt version 6, with the 0.8.0 trim hold
        controller = AgentController(ScriptedSupervisor(strategy_v5=StrategyParamsV5(**params)),
                                     Envelope(EnvelopeConfig()), Budget(1.0), prompt_version=6)
        control = True
    elif kind == "strategy7":  # prompt version 7, the same 0.8.0 rules
        controller = AgentController(ScriptedSupervisor(strategy_v7=StrategyParamsV7(**params)),
                                     Envelope(EnvelopeConfig()), Budget(1.0), prompt_version=7)
        control = True
    else:  # strategy8: prompt version 8, the same 0.8.0 rules
        controller = AgentController(ScriptedSupervisor(strategy_v8=StrategyParamsV8(**params)),
                                     Envelope(EnvelopeConfig()), Budget(1.0), prompt_version=8)
        control = True
    res = run_session(CityLearnSimulator(control=control, schema=Path(schema)), controller, NullWriter(),
                      log=lambda *_: None)
    k = res["district_kpis"]
    return ({key: k.get(key) for key in (*KEYS, *COMFORT)}
            | {"clamped": res["clamped_steps"], "fallback": res["fallback_steps"]})


def mean(rows: list[dict]) -> dict:
    return {k: sum(r[k] for r in rows) / len(rows) for k in (*KEYS, "clamped") if k in rows[0]}


def qualifies(k: dict, base: dict, rule: dict) -> bool:
    return (k["discomfort_proportion"] <= base["discomfort_proportion"] + 1e-9
            and all(k[x] <= 1.0 + TOLERANCE for x in ("daily_peak_average", "all_time_peak_average", "ramping_average",
                                                       "daily_one_minus_load_factor_average"))
            and k["cost_total"] < rule["cost_total"] and k["carbon_emissions_total"] < rule["carbon_emissions_total"])


def score(k: dict) -> float:
    return k["cost_total"] + k["carbon_emissions_total"]


def qualifies_v5(k: dict, ref: dict) -> bool:
    """Ramping below the baseline; cost, emissions, discomfort and both peaks no worse than ref."""
    return (k["ramping_average"] < 1.0
            and all(k[x] <= ref[x] + TOLERANCE for x in ("cost_total", "carbon_emissions_total", "discomfort_proportion",
                                                          "daily_peak_average", "all_time_peak_average")))


def score_v5(k: dict) -> tuple[float, float]:
    return (k["ramping_average"] + k["daily_one_minus_load_factor_average"], score(k))


def grid_v5() -> list[dict]:
    return [{**asdict(StrategyParamsV5()), **dict(zip(GRID_V5, combo))} for combo in itertools.product(*GRID_V5.values())]


def grid_v7() -> list[dict]:
    """Without a cap, whether it covers charging makes no difference, so that pair runs once."""
    return [{**asdict(StrategyParamsV7()), **dict(zip(GRID_V7, combo))} for combo in itertools.product(*GRID_V7.values())
            if combo[0] < 1.0 or combo[1]]


def qualifies_v7(k: dict, ref: dict) -> bool:
    """Ramping below ref's; cost, emissions, discomfort and both peaks no worse than ref."""
    return (k["ramping_average"] < ref["ramping_average"] - TOLERANCE
            and all(k[x] <= ref[x] + TOLERANCE for x in ("cost_total", "carbon_emissions_total", "discomfort_proportion",
                                                          "daily_peak_average", "all_time_peak_average")))


def line(name: str, k: dict) -> str:
    return (f"{name:>10} cost {k['cost_total']:.4f} emissions {k['carbon_emissions_total']:.4f} "
            f"discomfort {k['discomfort_proportion']:.4f} daily peak {k['daily_peak_average']:.4f} "
            f"all-time peak {k['all_time_peak_average']:.4f} ramping {k['ramping_average']:.4f} "
            f"load factor {k['daily_one_minus_load_factor_average']:.4f}"
            + (f" clamped {k['clamped']:.1f}" if "clamped" in k else ""))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--version", type=int, default=5, choices=(4, 5, 6, 7, 8))
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--jobs", type=int, default=None, help="parallel simulations (default: one per CPU)")
    ap.add_argument("--out", type=Path, default=None, help="optionally write every result as JSON")
    args = ap.parse_args(argv)

    if args.version == 5:
        return main_v5(args)
    if args.version == 6:
        return main_v6(args)
    if args.version == 7:
        return main_v7(args)
    if args.version == 8:
        return main_v8(args)
    with tempfile.TemporaryDirectory() as tmp:
        months = [str(d / "schema.json") for d in month_datasets(Path(tmp))]
        candidates = [asdict(StrategyParams())] if args.quick else [
            {**START, **dict(zip(GRID, combo))} for combo in itertools.product(*GRID.values())]
        jobs = [("baseline", None, m) for m in months] + [("rule", None, m) for m in months]
        jobs += [("strategy", c, m) for c in candidates for m in months]
        # spawn, not fork: forking after torch has started its threads can deadlock.
        with cf.ProcessPoolExecutor(max_workers=args.jobs, mp_context=mp.get_context("spawn")) as pool:
            results = list(pool.map(kpis, jobs))
    n = len(months)
    base, rule = mean(results[:n]), mean(results[n:2 * n])
    print(f"tuning set: {TUNING_DATASET.name}, {n} months, mean over months")
    print(line("baseline", base))
    print(line("rule 0.4.0", rule))
    rows = []
    for i, c in enumerate(candidates):
        k = mean(results[2 * n + i * n:2 * n + (i + 1) * n])
        rows.append({"params": c, "kpis": k, "qualifies": qualifies(k, base, rule), "score": score(k)})
    pool_rows = [r for r in rows if r["qualifies"]] or rows
    best = min(pool_rows, key=lambda r: (r["score"], json.dumps(r["params"], sort_keys=True)))
    print(f"{sum(r['qualifies'] for r in rows)} of {len(rows)} candidates qualify")
    print(line("best", best["kpis"]) + ("" if best["qualifies"] else " (does not qualify)"))
    shipped = asdict(StrategyParams())
    changed = {k: v for k, v in best["params"].items() if v != shipped[k]}
    print(f"best settings differ from the shipped defaults in: {changed or 'nothing'}")
    if args.out:
        args.out.write_text(json.dumps({"baseline": base, "rule": rule, "rows": rows, "best": best}, indent=2,
                                       sort_keys=True), encoding="utf-8")
    return 0


def main_v5(args) -> int:
    with tempfile.TemporaryDirectory() as tmp:
        months = [str(d / "schema.json") for d in month_datasets(Path(tmp))]
        candidates = [asdict(StrategyParamsV5())] if args.quick else grid_v5()
        jobs = [("baseline", None, m) for m in months] + [("rule", None, m) for m in months]
        jobs += [("strategy", asdict(StrategyParams()), m) for m in months]
        jobs += [("strategy5", c, m) for c in candidates for m in months]
        with cf.ProcessPoolExecutor(max_workers=args.jobs, mp_context=mp.get_context("spawn")) as pool:
            results = list(pool.map(kpis, jobs))
    n = len(months)
    base, rule, v4 = mean(results[:n]), mean(results[n:2 * n]), mean(results[2 * n:3 * n])
    print(f"tuning set: {TUNING_DATASET.name}, {n} months, mean over months")
    print(line("baseline", base))
    print(line("rule 0.4.0", rule))
    print(line("v4 0.6.0", v4))
    rows = []
    for i, c in enumerate(candidates):
        k = mean(results[3 * n + i * n:3 * n + (i + 1) * n])
        rows.append({"params": c, "kpis": k, "qualifies": qualifies_v5(k, v4), "score": score_v5(k)})
    pool_rows = [r for r in rows if r["qualifies"]] or rows
    best = min(pool_rows, key=lambda r: (r["score"], json.dumps(r["params"], sort_keys=True)))
    print(f"{sum(r['qualifies'] for r in rows)} of {len(rows)} candidates qualify")
    print(line("best", best["kpis"]) + ("" if best["qualifies"] else " (does not qualify)"))
    ref = asdict(StrategyParamsV5())
    changed = {k: v for k, v in best["params"].items() if v != ref[k]}
    print(f"best settings differ from the shipped defaults in: {changed or 'nothing'}")
    if args.out:
        args.out.write_text(json.dumps({"baseline": base, "rule": rule, "v4": v4, "rows": rows, "best": best},
                                       indent=2, sort_keys=True), encoding="utf-8")
    return 0


def main_v6(args) -> int:
    """The trim hold on the tuning months: the shipped version 5 strategy with and without it."""
    params = asdict(StrategyParamsV5())
    with tempfile.TemporaryDirectory() as tmp:
        months = [str(d / "schema.json") for d in month_datasets(Path(tmp))]
        jobs = [("baseline", None, m) for m in months] + [("strategy5", params, m) for m in months]
        jobs += [("strategy6", params, m) for m in months]
        with cf.ProcessPoolExecutor(max_workers=args.jobs, mp_context=mp.get_context("spawn")) as pool:
            results = list(pool.map(kpis, jobs))
    n = len(months)
    base, v5, v6 = mean(results[:n]), mean(results[n:2 * n]), mean(results[2 * n:3 * n])
    print(f"tuning set: {TUNING_DATASET.name}, {n} months, mean over months")
    print(line("baseline", base))
    print(line("0.7 rules", v5))
    print(line("0.8 hold", v6))
    worse = [k for k in KEYS if v6[k] > v5[k] + TOLERANCE]
    print("with the trim hold, worse than without on: " + (", ".join(worse) if worse else "nothing"))
    for i in range(n):
        a, b = results[n + i], results[2 * n + i]
        print(f"  month {i + 1}: ramping {a['ramping_average']:.4f} -> {b['ramping_average']:.4f}, "
              f"cost {a['cost_total']:.4f} -> {b['cost_total']:.4f}, "
              f"discomfort {a['discomfort_proportion']:.4f} -> {b['discomfort_proportion']:.4f}")
    if args.out:
        args.out.write_text(json.dumps({"baseline": base, "v5_070": v5, "v5_080": v6, "months": results},
                                       indent=2, sort_keys=True), encoding="utf-8")
    return 0


def main_v7(args) -> int:
    """The version 7 battery plan on the tuning months, against the shipped version 6 strategy."""
    with tempfile.TemporaryDirectory() as tmp:
        months = [str(d / "schema.json") for d in month_datasets(Path(tmp))]
        candidates = [asdict(StrategyParamsV7())] if args.quick else grid_v7()
        jobs = [("baseline", None, m) for m in months] + [("rule", None, m) for m in months]
        jobs += [("strategy6", asdict(StrategyParamsV5()), m) for m in months]
        jobs += [("strategy7", c, m) for c in candidates for m in months]
        with cf.ProcessPoolExecutor(max_workers=args.jobs, mp_context=mp.get_context("spawn")) as pool:
            results = list(pool.map(kpis, jobs))
    n = len(months)
    base, rule, v6 = mean(results[:n]), mean(results[n:2 * n]), mean(results[2 * n:3 * n])
    print(f"tuning set: {TUNING_DATASET.name}, {n} months, mean over months")
    print(line("baseline", base))
    print(line("rule 0.4.0", rule))
    print(line("v6 0.8.0", v6))
    shipped = asdict(StrategyParamsV7())
    ks = [mean(results[3 * n + i * n:3 * n + (i + 1) * n]) for i in range(len(candidates))]
    ref = ks[candidates.index(shipped)]
    print(line("v7 shipped", ref))
    rows = []
    for c, k in zip(candidates, ks):
        rows.append({"params": c, "kpis": k, "qualifies": qualifies_v7(k, ref), "score": score_v5(k)})
        print(line(" ".join(f"{g}={c[g]}" for g in GRID_V7), k) + (" qualifies" if rows[-1]["qualifies"] else ""))
    pool_rows = [r for r in rows if r["qualifies"]] or [r for r in rows if r["params"] == shipped]
    best = min(pool_rows, key=lambda r: (r["score"], json.dumps(r["params"], sort_keys=True)))
    print(f"{sum(r['qualifies'] for r in rows)} of {len(rows)} candidates qualify")
    print(line("best", best["kpis"]) + ("" if best["qualifies"] else " (does not qualify)"))
    changed = {k: v for k, v in best["params"].items() if v != shipped[k]}
    print(f"best settings differ from the shipped defaults in: {changed or 'nothing'}")
    if args.out:
        args.out.write_text(json.dumps({"baseline": base, "rule": rule, "v6": v6, "rows": rows, "best": best},
                                       indent=2, sort_keys=True), encoding="utf-8")
    return 0


def grid_v8() -> list[dict]:
    off = asdict(StrategyParamsV8())  # no extra cooling, no night rule: the version 7 strategy
    warm = [dict(zip(GRID_V8_WARM, c)) for c in itertools.product(*GRID_V8_WARM.values())]
    night = [dict(zip(GRID_V8_NIGHT, c)) for c in itertools.product(*GRID_V8_NIGHT.values())]
    return ([{**off, **w} for w in warm] + [{**off, **n} for n in night]
            + [{**off, **n, **w} for n in night for w in GRID_V8_MIX])


def qualifies_v8(k: dict, months: list[dict], base_months: list[dict], ref: dict) -> bool:
    """Too warm at or below the baseline on every month, too cool within V8_SLACK of ref, and ramping
    and both peaks at or below the baseline, on the mean."""
    return (all(m["discomfort_hot_proportion"] <= b["discomfort_hot_proportion"] + 1e-9
                for m, b in zip(months, base_months))
            and k["discomfort_cold_proportion"] <= ref["discomfort_cold_proportion"] + V8_SLACK
            and all(k[x] <= 1.0 + TOLERANCE for x in ("ramping_average", "daily_peak_average", "all_time_peak_average")))


def mean_all(rows: list[dict]) -> dict:
    return {k: sum(r[k] for r in rows) / len(rows) for k in (*KEYS, *COMFORT, "clamped")}


def line_v8(name: str, k: dict) -> str:
    return line(name, k) + f" too cool {k['discomfort_cold_proportion']:.4f} too warm {k['discomfort_hot_proportion']:.4f}"


def main_v8(args) -> int:
    """Extra cooling in a warm room on the tuning months, against the shipped version 7 strategy."""
    with tempfile.TemporaryDirectory() as tmp:
        months = [str(d / "schema.json") for d in month_datasets(Path(tmp))]
        candidates = [asdict(StrategyParamsV8())] if args.quick else grid_v8()
        jobs = [("baseline", None, m) for m in months] + [("strategy7", asdict(StrategyParamsV7()), m) for m in months]
        jobs += [("strategy8", c, m) for c in candidates for m in months]
        with cf.ProcessPoolExecutor(max_workers=args.jobs, mp_context=mp.get_context("spawn")) as pool:
            results = list(pool.map(kpis, jobs))
    n = len(months)
    base_months, ref_months = results[:n], results[n:2 * n]
    base, ref = mean_all(base_months), mean_all(ref_months)
    print(f"tuning set: {TUNING_DATASET.name}, {n} months, mean over months")
    print(line_v8("baseline", base))
    print(line_v8("v7 shipped", ref))
    print("  too warm by month, baseline: " + ", ".join(f"{m['discomfort_hot_proportion']:.4f}" for m in base_months)
          + "; v7: " + ", ".join(f"{m['discomfort_hot_proportion']:.4f}" for m in ref_months))
    rows = []
    for i, c in enumerate(candidates):
        got = results[2 * n + i * n:2 * n + (i + 1) * n]
        k = mean_all(got)
        ok = qualifies_v8(k, got, base_months, ref)
        rows.append({"params": c, "kpis": k, "months": got, "qualifies": ok,
                     "score": (score(k), k["discomfort_hot_proportion"])})
        print(line_v8(" ".join(f"{g}={c[g]}" for g in GRID_V8), k) + (" qualifies" if ok else "")
              + "  too warm by month " + ", ".join(f"{m['discomfort_hot_proportion']:.4f}" for m in got))
    pool_rows = [r for r in rows if r["qualifies"]]
    print(f"{len(pool_rows)} of {len(rows)} candidates qualify")
    best = None
    if pool_rows:
        best = min(pool_rows, key=lambda r: (r["score"], json.dumps(r["params"], sort_keys=True)))
        print(line_v8("best", best["kpis"]))
        shipped = asdict(StrategyParamsV8())
        changed = {k: v for k, v in best["params"].items() if v != shipped[k]}
        print(f"best settings differ from the shipped defaults in: {changed or 'nothing'}")
    else:
        print("none qualifies: no extra cooling")
    if args.out:
        args.out.write_text(json.dumps({"baseline": base, "v7": ref, "rows": rows, "best": best},
                                       indent=2, sort_keys=True), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
