"""Split CityLearn's district ramping by cause, exactly (the 0.8.0 diagnosis).

    python scripts/split_ramping.py RUN_DIR [RUN_DIR ...]

CityLearn's ramping_average is R(E) / R(E_ref). R adds up every hour-to-hour rise of a series
(a fall counts for nothing), E is the district's net draw, and E_ref is CityLearn's own
reference for the same run: its net draw with storage taken out and cooling put back to the
ideal load (net_electricity_consumption_without_storage_and_partial_load). It is not the
baseline run: in an outage hour E is 0 whatever the actions, but E_ref still has the cooling
difference taken off, so extra cooling in an outage lowers E_ref there and adds a rise to it.

Each run is simulated again from its recorded actions (the outcomes must match the recording).
Per building, by construction, net = ref + battery + hot water storage + cooling gap, where the
cooling gap is (net - storage) - ref. Each hour's rise max(0, dE) is split among the causes
below with Shapley values, starting from the reference's own change that hour, so the shares
add up exactly: R(E) = R(E_ref) + sum of the shares.

  battery_charge, battery_discharge  the positive and negative parts of the battery's draw
  dhw_storage                        the hot water tank's draw
  trim_start, trim_end, trim_depth   the cooling gap while cooling is more than 0.002 below the
                                     baseline action: the hour a trim starts, the hour it ends,
                                     and changes in its depth in between
  extra_cooling                      the cooling gap while cooling is more than 0.002 above it
  cooling_rounding                   the remaining cooling gap (actions rounded to 4 decimals)
  outage_hours                       everything in a building's outage hours, where the grid
                                     draw is 0 whatever the actions
"""

from __future__ import annotations

import itertools
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from hyperbolic.runner import load_jsonl  # noqa: E402

CAUSES = ("battery_charge", "battery_discharge", "dhw_storage", "trim_start", "trim_end", "trim_depth",
          "extra_cooling", "cooling_rounding", "outage_hours")
TRIM_MIN = 0.002  # a trim is cooling more than this below the baseline action (EnvelopeConfig.trim_min_depth)


def resimulate(run_dir: Path):
    """Run a recorded run's actions through CityLearn again. Returns (CityLearnEnv, steps)."""
    from hyperbolic.sim import CityLearnSimulator

    steps = load_jsonl(Path(run_dir) / "steps.jsonl")
    m = json.loads((Path(run_dir) / "manifest.json").read_text(encoding="utf-8"))
    sim = CityLearnSimulator(control=steps[0]["actions"] is not None)
    state = sim.start(m.get("hours_limit"))
    i = 0
    while state is not None and i < len(steps):
        outcome, state = sim.step(steps[i]["actions"])
        if outcome != steps[i]["outcome"]:
            raise ValueError(f"{run_dir}: hour {i} does not reproduce the recorded outcome")
        i += 1
    return sim.env, steps


def _rise(x: np.ndarray) -> float:
    return float(np.clip(np.diff(x), 0.0, None).sum())


def _shapley(start: float, deltas: list[float]) -> list[float]:
    """Exact Shapley shares of max(0, start + sum(deltas)) - max(0, start)."""
    phi = [0.0] * len(deltas)
    live = [i for i, d in enumerate(deltas) if abs(d) > 1e-12]
    m = len(live)
    for i in live:
        others = [j for j in live if j != i]
        for r in range(m):
            w = math.factorial(r) * math.factorial(m - r - 1) / math.factorial(m)
            for sub in itertools.combinations(others, r):
                s = start + sum(deltas[j] for j in sub)
                phi[i] += w * (max(0.0, s + deltas[i]) - max(0.0, s))
    return phi


def split(env, steps: list[dict]) -> dict:
    """The exact split for a finished CityLearn env and the run's step records."""
    n = len(steps)
    ref_total = np.zeros(n)
    net_total = np.zeros(n)
    inc = {c: np.zeros(n) for c in CAUSES}
    for b in env.buildings:
        name = b.name
        net = np.asarray(b.net_electricity_consumption, dtype=float)[:n]
        ws = np.asarray(b.net_electricity_consumption_without_storage, dtype=float)[:n]
        ref = np.asarray(b.net_electricity_consumption_without_storage_and_partial_load, dtype=float)[:n]
        bat = np.asarray(b.electrical_storage_electricity_consumption, dtype=float)[:n]
        dhw = net - ws - bat  # all other storage: the hot water tank here
        gap = ws - ref
        act = np.array([s["actions"][name]["cooling"] for s in steps])
        base = np.array([s["state"]["baseline"][name]["cooling"] for s in steps])
        out = np.array([bool(s["state"]["buildings"][name].get("power_outage")) for s in steps])
        trimmed, extra = (act < base - TRIM_MIN) & ~out, (act > base + TRIM_MIN) & ~out
        level = {
            "battery_charge": np.where(out, 0.0, np.clip(bat, 0.0, None)),
            "battery_discharge": np.where(out, 0.0, np.clip(bat, None, 0.0)),
            "dhw_storage": np.where(out, 0.0, dhw),
            "extra_cooling": np.where(extra, gap, 0.0),
            "cooling_rounding": np.where(~trimmed & ~extra & ~out, gap, 0.0),
            "outage_hours": np.where(out, bat + dhw + gap, 0.0),
        }
        for c, x in level.items():
            inc[c][1:] += np.diff(x)
        trim = np.where(trimmed, gap, 0.0)
        d = np.diff(trim)
        for t in range(1, n):
            kind = ("trim_depth" if trimmed[t] and trimmed[t - 1] else "trim_start" if trimmed[t]
                    else "trim_end" if trimmed[t - 1] else None)
            if kind:
                inc[kind][t] += d[t - 1]
        ref_total += ref
        net_total += net
    dref = np.zeros(n)
    dref[1:] = np.diff(ref_total)
    shares = dict.fromkeys(CAUSES, 0.0)
    for t in range(1, n):
        for c, v in zip(CAUSES, _shapley(dref[t], [inc[c][t] for c in CAUSES])):
            shares[c] += v
    r, r_ref = _rise(net_total), _rise(ref_total)
    if abs(r_ref + sum(shares.values()) - r) > 1e-6:
        raise AssertionError("the shares do not add up to the run's ramping")
    return {"ramping_kwh": r, "reference_kwh": r_ref, "ramping_average": r / r_ref, "shares_kwh": shares}


def table(results: dict[str, dict]) -> str:
    names = list(results)
    lines = [f"{'cause, points of ramping_average':<34}" + "".join(f"{n:>18}" for n in names)]
    for c in CAUSES:
        lines.append(f"{c:<34}" + "".join(f"{results[n]['shares_kwh'][c] / results[n]['reference_kwh'] * 100:>+18.2f}"
                                          for n in names))
    lines.append(f"{'reference rises (kWh)':<34}" + "".join(f"{results[n]['reference_kwh']:>18.2f}" for n in names))
    lines.append(f"{'ramping_average':<34}" + "".join(f"{results[n]['ramping_average']:>18.4f}" for n in names))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    dirs = [Path(a) for a in (argv if argv is not None else sys.argv[1:])]
    if not dirs:
        print(__doc__.splitlines()[2].strip(), file=sys.stderr)
        return 2
    results = {}
    for d in dirs:
        env, steps = resimulate(d)
        results[d.name[-16:]] = split(env, steps)
    print(table(results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
