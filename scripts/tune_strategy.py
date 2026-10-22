"""Pick the scripted strategy's numbers on a separate 2023 dataset, never the reported month.

    python scripts/tune_strategy.py                # version 5 grid (0.7.0)
    python scripts/tune_strategy.py --quick        # the shipped version 5 defaults only
    python scripts/tune_strategy.py --version 4    # the 0.6.0 version 4 search, as it was run

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
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import csv
import itertools
import json
import multiprocessing as mp
import shutil
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hyperbolic.envelope import Envelope, EnvelopeConfig  # noqa: E402
from hyperbolic.model import Budget, ScriptedSupervisor, StrategyParams, StrategyParamsV5  # noqa: E402
from hyperbolic.runner import AgentController, BaselineController, NullWriter, run_session  # noqa: E402

TUNING_DATASET = ROOT / "scripts" / "tuning_data" / "citylearn_challenge_2023_phase_2_online_evaluation_1"
SERIES = ("Building_1.csv", "Building_2.csv", "Building_3.csv", "carbon_intensity.csv", "pricing.csv", "weather.csv")
KEYS = ("cost_total", "carbon_emissions_total", "discomfort_proportion", "daily_peak_average", "all_time_peak_average",
        "ramping_average", "daily_one_minus_load_factor_average")
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


def month_datasets(out: Path) -> list[Path]:
    """One dataset folder per calendar month of the tuning set, each a full episode."""
    with (TUNING_DATASET / "Building_1.csv").open(encoding="utf-8") as f:
        months = [row["month"] for row in csv.DictReader(f)]
    spans, start = [], 0
    for i in range(1, len(months) + 1):
        if i == len(months) or months[i] != months[start]:
            spans.append((months[start], start, i))
            start = i
    schema = json.loads((TUNING_DATASET / "schema.json").read_text(encoding="utf-8"))
    dirs = []
    for month, a, b in spans:
        d = out / f"month_{int(month):02d}"
        d.mkdir(parents=True, exist_ok=True)
        for name in SERIES:
            lines = (TUNING_DATASET / name).read_text(encoding="utf-8").splitlines(keepends=True)
            (d / name).write_text("".join([lines[0], *lines[1 + a:1 + b]]), encoding="utf-8")
        for pth in TUNING_DATASET.glob("*.pth"):
            shutil.copy(pth, d / pth.name)
        (d / "schema.json").write_text(json.dumps({**schema, "simulation_start_time_step": 0,
                                                   "simulation_end_time_step": b - a - 1}), encoding="utf-8")
        dirs.append(d)
    return dirs


def kpis(job: tuple[str, dict | None, str]) -> dict:
    """job: (kind, params or None, schema path). kind is baseline, rule, strategy (version 4) or
    strategy5 (version 5)."""
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
        controller = AgentController(ScriptedSupervisor(strategy=StrategyParams(**params)), Envelope(EnvelopeConfig()),
                                     Budget(1.0), prompt_version=4)
        control = True
    else:
        controller = AgentController(ScriptedSupervisor(strategy_v5=StrategyParamsV5(**params)), Envelope(EnvelopeConfig()),
                                     Budget(1.0), prompt_version=5)
        control = True
    res = run_session(CityLearnSimulator(control=control, schema=Path(schema)), controller, NullWriter(),
                      log=lambda *_: None)
    k = res["district_kpis"]
    return {key: k.get(key) for key in KEYS} | {"clamped": res["clamped_steps"], "fallback": res["fallback_steps"]}


def mean(rows: list[dict]) -> dict:
    return {k: sum(r[k] for r in rows) / len(rows) for k in KEYS}


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


def line(name: str, k: dict) -> str:
    return (f"{name:>10} cost {k['cost_total']:.4f} emissions {k['carbon_emissions_total']:.4f} "
            f"discomfort {k['discomfort_proportion']:.4f} daily peak {k['daily_peak_average']:.4f} "
            f"all-time peak {k['all_time_peak_average']:.4f} ramping {k['ramping_average']:.4f} "
            f"load factor {k['daily_one_minus_load_factor_average']:.4f}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--version", type=int, default=5, choices=(4, 5))
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--jobs", type=int, default=None, help="parallel simulations (default: one per CPU)")
    ap.add_argument("--out", type=Path, default=None, help="optionally write every result as JSON")
    args = ap.parse_args(argv)

    if args.version == 5:
        return main_v5(args)
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


if __name__ == "__main__":
    raise SystemExit(main())
