"""Pick the rule-based policy's settings on the first week of the episode only.

    python scripts/tune_rules.py            # full grid
    python scripts/tune_rules.py --quick    # only the shipped defaults and the starting point

The package ships one 2023 dataset (the phase 2 local evaluation month) and the repo has
no other, so there is no separate 2023 tuning set. To keep the reported month honest,
settings are chosen on the first 167 hourly decisions (one week) and the full 719 hour
month is used only for reporting. Every candidate runs through the same request, reply,
envelope and simulator path as a live model.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import itertools
import multiprocessing as mp
import json
import sys
from dataclasses import asdict, replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hyperbolic import district as dc  # noqa: E402
from hyperbolic.envelope import Envelope, EnvelopeConfig  # noqa: E402
from hyperbolic.model import Budget, RuleParams, ScriptedSupervisor  # noqa: E402
from hyperbolic.runner import AgentController, BaselineController, NullWriter, run_session  # noqa: E402

KEYS = ("cost_total", "carbon_emissions_total", "discomfort_proportion")
COMFORT_SLACK = 0.005  # discomfort may not rise by more than half a percentage point


def kpis(controller, control: bool, hours: int) -> dict:
    from hyperbolic.sim import CityLearnSimulator

    res = run_session(CityLearnSimulator(control=control), controller, NullWriter(), hours=hours,
                      log=lambda *_: None)
    k = res["district_kpis"]
    return {key: k.get(key) for key in KEYS} | {"clamped": res["clamped_steps"], "fallback": res["fallback_steps"]}


def agent_kpis(params: RuleParams, hours: int) -> dict:
    return kpis(agent(params), True, hours)


def agent(params: RuleParams) -> AgentController:
    return AgentController(supervisor=ScriptedSupervisor(params=params), envelope=Envelope(EnvelopeConfig()),
                           budget=Budget(limit_usd=1.0))


# Where the search starts: the hand-set values before tuning. Fixed here, not taken from the
# RuleParams defaults (which hold the tuned result), so the search reproduces.
START = RuleParams(charge_price_rank=0.1, charge_carbon_rank=0.35, charge_rate=0.6, peak_ratio=0.95, peak_spread=1.3,
                   discharge_rate=0.4, soc_target=0.9, soc_reserve=0.15, solar_soak=True, dhw_charge=0.1,
                   dhw_discharge=0.2, precool=0.0, precool_hours=2, peak_ease=0.0, max_step=0.5)
STAGE_1 = {
    "charge_carbon_rank": (0.2, 0.35, 0.5),
    "charge_rate": (0.3, 0.6),
    "discharge_rate": (0.4, 0.8),
    "dhw_charge": (0.0, 0.1),
    "precool": (0.0, 0.08),
    "peak_ease": (0.0, 0.08),
}
STAGE_2 = {  # refined around the stage 1 winner
    "charge_carbon_rank": (0.1, 0.2),
    "soc_target": (0.8, 0.95),
    "soc_reserve": (0.1, 0.2),
    "peak_ratio": (0.8, 0.95),
    "dhw_discharge": (0.0, 0.2),
}


def grid(start: RuleParams, space: dict) -> list[RuleParams]:
    names = list(space)
    return [replace(start, **dict(zip(names, combo))) for combo in itertools.product(*space.values())]


def score(k: dict) -> float:
    """Equal weight on the cost and emissions ratios; lower is better."""
    return k["cost_total"] + k["carbon_emissions_total"]


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

    def evaluate(candidates: list[RuleParams], stage: int) -> dict:
        todo = []
        for p in candidates:
            key = json.dumps(asdict(p), sort_keys=True)
            if key not in seen:
                seen.add(key)
                todo.append(p)
        # spawn, not fork: forking after torch has started its threads can deadlock.
        with cf.ProcessPoolExecutor(max_workers=args.jobs, mp_context=mp.get_context("spawn")) as pool:
            results = list(pool.map(agent_kpis, todo, [args.hours] * len(todo)))
        for p, k in zip(todo, results):
            ok = k["discomfort_proportion"] <= base["discomfort_proportion"] + COMFORT_SLACK
            rows.append({"stage": stage, "params": asdict(p), "kpis": k, "comfort_ok": ok, "score": score(k)})
            print(f"  {len(rows):3d} cost {k['cost_total']:.4f} emissions {k['carbon_emissions_total']:.4f} "
                  f"discomfort {k['discomfort_proportion']:.4f}{'' if ok else ' (comfort worse)'}", flush=True)
        feasible = [r for r in rows if r["comfort_ok"]] or rows
        return min(feasible, key=lambda r: (r["score"], json.dumps(r["params"], sort_keys=True)))

    if args.quick:
        best = evaluate([RuleParams(), START], 1)
    else:
        best = evaluate(grid(START, STAGE_1), 1)
        best = evaluate(grid(RuleParams(**best["params"]), STAGE_2), 2)
    changed = {k: v for k, v in best["params"].items() if v != asdict(RuleParams())[k]}
    print(f"best: cost {best['kpis']['cost_total']:.4f}, emissions {best['kpis']['carbon_emissions_total']:.4f}, "
          f"discomfort {best['kpis']['discomfort_proportion']:.4f}")
    print(f"best settings differ from the RuleParams defaults in: {changed or 'nothing'}")
    if args.out:
        args.out.write_text(json.dumps({"baseline": base, "rows": rows, "best": best}, indent=2, sort_keys=True),
                            encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
