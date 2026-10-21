"""Pick the rule-based policy's settings on the first week of the episode only.

    python scripts/tune_rules.py            # full grid
    python scripts/tune_rules.py --quick    # only the shipped defaults and the starting point

The package ships one 2023 dataset (the phase 2 local evaluation month) and the repo has
no other, so there is no separate 2023 tuning set. To keep the reported month honest,
settings are chosen on the first 167 hourly decisions (one week) and the full 719 hour
month is used only for reporting. Every candidate runs through the same request, reply,
envelope and simulator path as a live model, with prompt version 3 and the peak limiter,
so the bar it sets is a fair one for the agent.

0.4.0 searches the version 3 policy (RuleParams) together with the two peak limiter
settings in EnvelopeConfig. The 0.3.0 search for the version 2 policy is in the git
history; its result is kept in RuleParamsV2.

A candidate qualifies when, on the tuning week, discomfort is no more than half a point
above the baseline and the daily and all-time peaks are at or below the baseline's. The
qualifying candidate with the lowest cost plus emissions wins.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import itertools
import json
import multiprocessing as mp
import sys
from dataclasses import asdict, replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hyperbolic import district as dc  # noqa: E402
from hyperbolic.envelope import Envelope, EnvelopeConfig  # noqa: E402
from hyperbolic.model import Budget, RuleParams, ScriptedSupervisor  # noqa: E402
from hyperbolic.runner import AgentController, BaselineController, NullWriter, run_session  # noqa: E402

KEYS = ("cost_total", "carbon_emissions_total", "discomfort_proportion", "daily_peak_average",
        "all_time_peak_average")
COMFORT_SLACK = 0.005  # discomfort may not rise by more than half a percentage point
# Peaks count as at or below the baseline's to four decimals: the baseline action under
# active control rounds the heat pump fraction to 4 decimals, which by itself moves a peak
# ratio by about 1e-5 (an idle-storage hour scores 1.000012).
PEAK_TOLERANCE = 5e-5
ENVELOPE_KEYS = ("peak_target_fraction", "peak_forecast_days")

# Where the search starts: hand-set values before tuning. Fixed here, not taken from the
# defaults (which hold the tuned result), so the search reproduces.
START = {
    "rule": asdict(RuleParams(charge_rank=0.2, charge_max_signal=0.2, charge_rate=0.2, discharge_min_signal=0.6,
                              discharge_rate=0.8, shave=0.0, soc_target=0.95, soc_reserve=0.1, solar_soak=True,
                              endgame_hours=12, max_step=0.5, min_move=0.01)),
    "envelope": {"peak_target_fraction": 1.0, "peak_forecast_days": 2},
}
STAGE_1 = {
    "charge_rank": (0.15, 0.3),
    "charge_max_signal": (0.15, 0.3),
    "charge_rate": (0.15, 0.3),
    "discharge_min_signal": (0.55, 0.7),
    "shave": (0.0, 0.95),
    "peak_target_fraction": (0.85, 1.0),
}
STAGE_2 = {  # refined around the stage 1 winner
    "discharge_rate": (0.5, 0.8),
    "soc_target": (0.85, 0.95),
    "soc_reserve": (0.1, 0.2),
    "endgame_hours": (6, 24),
    "peak_forecast_days": (1, 2),
}


def kpis(controller, control: bool, hours: int) -> dict:
    import torch

    torch.set_num_threads(1)  # one simulation per process; avoid oversubscribing the CPU
    from hyperbolic.sim import CityLearnSimulator

    res = run_session(CityLearnSimulator(control=control), controller, NullWriter(), hours=hours,
                      log=lambda *_: None)
    k = res["district_kpis"]
    return {key: k.get(key) for key in KEYS} | {"clamped": res["clamped_steps"], "fallback": res["fallback_steps"]}


def agent(candidate: dict) -> AgentController:
    return AgentController(supervisor=ScriptedSupervisor(params=RuleParams(**candidate["rule"])),
                           envelope=Envelope(EnvelopeConfig(**candidate["envelope"])), budget=Budget(limit_usd=1.0))


def agent_kpis(candidate: dict, hours: int) -> dict:
    return kpis(agent(candidate), True, hours)


def grid(start: dict, space: dict) -> list[dict]:
    names = list(space)
    out = []
    for combo in itertools.product(*space.values()):
        rule, env = dict(start["rule"]), dict(start["envelope"])
        for k, v in zip(names, combo):
            (env if k in ENVELOPE_KEYS else rule)[k] = v
        out.append({"rule": rule, "envelope": env})
    return out


def score(k: dict) -> float:
    """Equal weight on the cost and emissions ratios; lower is better."""
    return k["cost_total"] + k["carbon_emissions_total"]


def qualifies(k: dict, base: dict) -> bool:
    return (k["discomfort_proportion"] <= base["discomfort_proportion"] + COMFORT_SLACK
            and k["daily_peak_average"] <= 1.0 + PEAK_TOLERANCE and k["all_time_peak_average"] <= 1.0 + PEAK_TOLERANCE)


def shipped() -> dict:
    env = EnvelopeConfig()
    return {"rule": asdict(RuleParams()), "envelope": {k: getattr(env, k) for k in ENVELOPE_KEYS}}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--hours", type=int, default=dc.TUNING_HOURS)
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--jobs", type=int, default=None, help="parallel simulations (default: one per CPU)")
    ap.add_argument("--out", type=Path, default=None, help="optionally write every result as JSON")
    args = ap.parse_args(argv)

    base = kpis(BaselineController(), False, args.hours)
    print(f"tuning on the first {args.hours} hours; baseline discomfort {base['discomfort_proportion']:.4f}")
    rows: list[dict] = []
    seen: set[str] = set()

    def evaluate(candidates: list[dict], stage: int) -> dict:
        todo = []
        for c in candidates:
            key = json.dumps(c, sort_keys=True)
            if key not in seen:
                seen.add(key)
                todo.append(c)
        # spawn, not fork: forking after torch has started its threads can deadlock.
        with cf.ProcessPoolExecutor(max_workers=args.jobs, mp_context=mp.get_context("spawn")) as pool:
            results = list(pool.map(agent_kpis, todo, [args.hours] * len(todo)))
        for c, k in zip(todo, results):
            ok = qualifies(k, base)
            rows.append({"stage": stage, "params": c, "kpis": k, "qualifies": ok, "score": score(k)})
            print(f"  {len(rows):3d} cost {k['cost_total']:.4f} emissions {k['carbon_emissions_total']:.4f} "
                  f"discomfort {k['discomfort_proportion']:.4f} daily peak {k['daily_peak_average']:.4f} "
                  f"all-time peak {k['all_time_peak_average']:.4f}{'' if ok else ' (does not qualify)'}", flush=True)
        pool_rows = [r for r in rows if r["qualifies"]] or rows
        return min(pool_rows, key=lambda r: (r["score"], json.dumps(r["params"], sort_keys=True)))

    if args.quick:
        best = evaluate([shipped(), START], 1)
    else:
        best = evaluate(grid(START, STAGE_1), 1)
        best = evaluate(grid(best["params"], STAGE_2), 2)
    k = best["kpis"]
    print(f"best: cost {k['cost_total']:.4f}, emissions {k['carbon_emissions_total']:.4f}, "
          f"discomfort {k['discomfort_proportion']:.4f}, daily peak {k['daily_peak_average']:.4f}, "
          f"all-time peak {k['all_time_peak_average']:.4f}")
    ref = shipped()
    changed = {f"{part}.{name}": v for part in ("rule", "envelope") for name, v in best["params"][part].items()
               if v != ref[part][name]}
    print(f"best settings differ from the shipped defaults in: {changed or 'nothing'}")
    if args.out:
        args.out.write_text(json.dumps({"baseline": base, "rows": rows, "best": best}, indent=2, sort_keys=True),
                            encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
