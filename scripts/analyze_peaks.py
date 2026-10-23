"""Where the peaks of a recorded prompt version 8 run come from, and how much of each the agent's
departures from its strategy explain (0.11.0).

    python scripts/analyze_peaks.py RUN_DIR [RUN_DIR ...] [--top 5] [--jobs N] [--out FILE]

CityLearn's all_time_peak_average is the district's highest hourly net draw over the episode over
the no-control run's; daily_peak_average is the mean of each day's highest hour over the same for
the no-control run (days are 24 hour blocks from the first hour). So one hour sets the all-time
peak and every day's top hour sets the daily peak.

Peak hours. For the run and for the scripted version 8 strategy on the same month, the hour of the
all-time peak and of the top daily peaks, district and per building, with what the model sent and
what the strategy would have sent for the very observation the model saw (the observation's own
strategy) in that hour and the three before it, and the deviation classes there
(scripts/analyze_deviations.py, which now reads version 8 runs).

Attribution. The run's replies are replayed on a fresh episode of the same month through the
unchanged envelope: control (must reproduce the published KPIs), the scripted strategy, every
departure class put back to the strategy on its own, and all at once. A class's share of the gap
on a KPI is (control - class) / (control - strategy). Classes are ranked by the all-time peak, then
the daily peak, then ramping, summed over the runs given.

These are evaluations, never recorded runs, and run only on the month set (never the holdout).
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import analyze_deviations as ad  # noqa: E402

from hyperbolic.model import observation_from_request  # noqa: E402
from hyperbolic.runner import load_jsonl  # noqa: E402

PEAK_KPIS = ("all_time_peak_average", "daily_peak_average", "ramping_average")
LOOKBACK = 3  # hours before a peak whose departures are listed with it


def district(grid_kwh: dict[str, list[float]]) -> list[float]:
    n = min(len(v) for v in grid_kwh.values())
    return [sum(v[t] for v in grid_kwh.values()) for t in range(n)]


def peak_hours(grid_kwh: dict[str, list[float]], top: int = 5) -> dict:
    """The all-time peak hour and the top daily peak hours, district and per building."""
    net = district(grid_kwh)
    days = collections.defaultdict(list)
    for t, v in enumerate(net):
        days[t // 24].append((v, t))
    daily = sorted((max(h) for h in days.values()), reverse=True)
    at = max(range(len(net)), key=lambda t: net[t])
    return {
        "all_time": {"step": at, "kwh": net[at], "buildings": {b: v[at] for b, v in grid_kwh.items()}},
        "daily_mean_kwh": sum(v for v, _ in daily) / len(daily),
        "top_daily": [{"step": t, "kwh": v, "buildings": {b: x[t] for b, x in grid_kwh.items()}} for v, t in daily[:top]],
        "building_peaks": {b: {"step": max(range(len(v)), key=lambda t: v[t]), "kwh": max(v)} for b, v in grid_kwh.items()},
    }


def around(run_dir: Path, step: int, lookback: int = LOOKBACK) -> list[dict]:
    """What the model sent and what its strategy would have sent, per building, in step and the hours before."""
    calls = {c["step"]: c for c in load_jsonl(run_dir / "calls.jsonl")}
    out = []
    for t in range(max(0, step - lookback), step + 1):
        rec = calls.get(t)
        if rec is None or not rec["reply"].get("text"):
            out.append({"step": t, "fallback": True})
            continue
        obs, reply = observation_from_request(rec["request"]), json.loads(rec["reply"]["text"])
        plan = ad.strategy_for(obs)
        out.append({
            "step": t, "hour": obs["hour"], "top_price_now": obs["price_plan"]["top_price_now"],
            "district_load_now_kwh": obs["peak"]["district_load_now_kwh"],
            "forecast_today_kwh": obs["peak"]["forecast_today_kwh"],
            "buildings": {b: {"model": {d: reply[b].get(d) for d in ("cooling", "battery")},
                              "strategy": {d: plan[b].get(d) for d in ("cooling", "battery")},
                              "soc": obs["buildings"][b]["battery"]["soc"]} for b in sorted(obs["buildings"])},
            "classes": sorted(f"{b} {c}" for b, c in ad.classify(obs, reply, plan)),
        })
    return out


def analyze(run_dir: Path, top: int = 5, jobs: int | None = None) -> dict:
    rows = ad.deviations(run_dir)
    results = ad.attribute(run_dir, rows, jobs)
    published = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))["district_kpis"]
    if any(results["control"]["kpis"][k] != published[k] for k in ad.KPI_KEYS):
        raise AssertionError(f"{run_dir.name}: control does not reproduce the published KPIs")
    live, strat = peak_hours(results["control"]["grid_kwh"], top), peak_hours(results["strategy"]["grid_kwh"], top)
    return {
        "run": run_dir.name, "summary": ad.summary(rows), "shares": ad.shares(results),
        "kpis": {n: r["kpis"] for n, r in results.items()},
        "peaks": {"model": live, "strategy": strat},
        "at_peak": {"model_all_time": around(run_dir, live["all_time"]["step"]),
                    "model_top_daily": [around(run_dir, p["step"], 0)[0] for p in live["top_daily"]]},
        "class_peaks": {n: peak_hours(r["grid_kwh"], 1)["all_time"] for n, r in results.items()},
    }


def ranking(analyses: list[dict]) -> list[tuple[str, dict[str, float]]]:
    """Classes by how much of the gap they explain, summed over runs: all-time peak, daily peak, ramping.
    Each value is the KPI points (control - class), so runs add up."""
    total: dict[str, dict[str, float]] = collections.defaultdict(lambda: dict.fromkeys(PEAK_KPIS, 0.0))
    for a in analyses:
        c = a["kpis"]["control"]
        for name, k in a["kpis"].items():
            if name in ("control", "strategy", "all"):
                continue
            for x in PEAK_KPIS:
                total[name][x] += c[x] - k[x]
    return sorted(total.items(), key=lambda kv: tuple(-kv[1][x] for x in PEAK_KPIS))


def _fmt_hour(a: dict) -> str:
    if a.get("fallback"):
        return f"    step {a['step']}: fallback"
    bs = "; ".join(f"{b[-1]} cool {v['model']['cooling']}/{v['strategy']['cooling']} bat {v['model']['battery']}/"
                   f"{v['strategy']['battery']} soc {v['soc']}" for b, v in a["buildings"].items())
    return (f"    step {a['step']} h{a['hour']}{' top' if a['top_price_now'] else ''} load {a['district_load_now_kwh']} "
            f"fc {a['forecast_today_kwh']}: {bs}  {', '.join(a['classes']) or 'as the strategy'}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("run_dirs", type=Path, nargs="+")
    ap.add_argument("--top", type=int, default=5, help="top daily peaks to list (default 5)")
    ap.add_argument("--jobs", type=int, default=None, help="parallel simulations (default: one per CPU)")
    ap.add_argument("--out", type=Path, default=None, help="optionally write every result as JSON")
    args = ap.parse_args(argv)
    analyses = []
    for d in args.run_dirs:
        a = analyze(d, args.top, args.jobs)
        analyses.append(a)
        k, pm, ps = a["kpis"], a["peaks"]["model"], a["peaks"]["strategy"]
        print(f"\n{d.name}: control reproduces the published KPIs exactly")
        print(f"  {'replay':<22}" + "".join(f"{x[:16]:>18}" for x in PEAK_KPIS) + f"{'peak step':>11}{'peak kWh':>10}")
        for n in ["control", "strategy", "all", *sorted(n for n in k if n not in ("control", "strategy", "all"))]:
            cp = a["class_peaks"][n]
            print(f"  {n:<22}" + "".join(f"{k[n][x]:>18.4f}" for x in PEAK_KPIS) + f"{cp['step']:>11}{cp['kwh']:>10.2f}")
        for who, p in (("model", pm), ("strategy", ps)):
            print(f"  {who} all-time peak: step {p['all_time']['step']} {p['all_time']['kwh']:.2f} kWh "
                  f"({', '.join(f'{b[-1]} {v:.2f}' for b, v in p['all_time']['buildings'].items())}); "
                  f"mean daily peak {p['daily_mean_kwh']:.2f} kWh; building peaks "
                  + ", ".join(f"{b[-1]} {v['kwh']:.2f} at {v['step']}" for b, v in p["building_peaks"].items()))
        print("  model at its all-time peak (model/strategy):")
        for h in a["at_peak"]["model_all_time"]:
            print(_fmt_hour(h))
        print("  model at its top daily peaks:")
        for h in a["at_peak"]["model_top_daily"]:
            print(_fmt_hour(h))
    print("\nclasses ranked by KPI points explained (control - class), summed over the runs")
    print(f"  {'class':<22}" + "".join(f"{x[:16]:>18}" for x in PEAK_KPIS))
    for name, v in ranking(analyses):
        print(f"  {name:<22}" + "".join(f"{v[x]:>+18.4f}" for x in PEAK_KPIS))
    if args.out:
        args.out.write_text(json.dumps(analyses, indent=1, sort_keys=True), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
