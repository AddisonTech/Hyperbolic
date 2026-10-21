"""Command line: hyperbolic baseline | run | replay | compare."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from . import district as dc
from .envelope import Envelope, EnvelopeConfig
from .model import (
    DEFAULT_BUDGET_USD,
    DEFAULT_EFFORT,
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL,
    MODELS,
    Budget,
    KeyMissing,
    LiveSupervisor,
    ScriptedSupervisor,
    resolve_api_key,
)
from .runner import AgentController, BaselineController, RunWriter, new_run_dir, replay_run, run_session
from .viewer import find_latest_pair, write_viewer_data

DEFAULT_VIEWER_DATA = Path("docs/data/viewer.json")


def _common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--hours", type=int, default=None,
                   help=f"stop after this many hours (default: the full {dc.EPISODE_HOURS} hour episode)")
    p.add_argument("--runs-dir", type=Path, default=Path("runs"), help="where run folders go (default: runs)")


def _sim(control: bool):
    from .sim import CityLearnSimulator

    return CityLearnSimulator(control=control)


def cmd_baseline(args) -> int:
    out = new_run_dir(args.runs_dir, "baseline", "citylearn")
    print(f"baseline, {dc.DATASET} -> {out}")
    res = run_session(_sim(control=False), BaselineController(), RunWriter(out), args.hours,
                      {"kind": "citylearn", "control": False})
    _print_result(res)
    return 0


def cmd_run(args) -> int:
    if not args.scripted:
        try:
            _, source = resolve_api_key()
        except KeyMissing as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        print(f"model key found in {source}")
    hours = args.hours or dc.EPISODE_HOURS
    sup = (ScriptedSupervisor(args.model, faults=ScriptedSupervisor.default_faults(hours)) if args.scripted
           else LiveSupervisor(args.model))
    ctl = AgentController(
        supervisor=sup,
        envelope=Envelope(EnvelopeConfig()),
        budget=Budget(limit_usd=args.budget),
        max_tokens=args.max_tokens,
        effort=args.effort,
    )
    out = new_run_dir(args.runs_dir, "agent", "citylearn")
    print(f"agent, {dc.DATASET}, {sup.kind} replies, {MODELS[args.model]['id']}, "
          f"budget ${args.budget:.2f} -> {out}")
    res = run_session(_sim(control=True), ctl, RunWriter(out), args.hours, {"kind": "citylearn", "control": True})
    _print_result(res)
    return 0


def cmd_replay(args) -> int:
    rep = replay_run(args.run_dir, out_dir=args.out)
    print(f"replayed {args.run_dir}: {rep.steps} hours, {rep.calls} recorded calls, {rep.api_calls} API calls")
    print(f"  identical decisions and actions: {rep.identical_steps}/{rep.steps}")
    print(f"  clamped hours {rep.clamped_steps}, fallback hours {rep.fallback_steps}, recorded cost ${rep.cost_usd:.4f}")
    if rep.deterministic:
        print("  deterministic: yes")
        return 0
    print(f"  deterministic: NO, first mismatches at hours {rep.mismatched_steps[:10]}")
    if rep.error:
        print(f"  stopped: {rep.error}")
    return 1


def cmd_compare(args) -> int:
    pair = ((Path(args.pair[0]), Path(args.pair[1])) if args.pair
            else find_latest_pair(args.runs_dir, (Path("results"),)))
    if not pair:
        print("no matching baseline and agent runs found; run `hyperbolic baseline` and `hyperbolic run` first",
              file=sys.stderr)
        return 1
    data = write_viewer_data(pair, args.out)
    s = data["scenarios"][0]
    print(f"\n{s['name']} ({s['hours']} h{', agent side is a SAMPLE' if s['agent_sample'] else ''})")
    print(f"  {s['headline']['text']}")
    print(f"  {'CityLearn KPI (district)':<44}{'baseline':>10}{'agent':>10}")
    for k in data["kpis"]:
        b, a = s["baseline"]["kpi"].get(k["id"]), s["agent"]["kpi"].get(k["id"])
        if b is None and a is None:
            continue
        print(f"  {k['id'] + ' (' + k['unit'] + ')':<44}{_fmt(b):>10}{_fmt(a):>10}")
    r = s["agent_run"]
    print(f"  model calls {r['calls']}, clamped hours {r['clamped_hours']}, fallback hours {r['fallback_hours']}, "
          f"cost ${r['cost_usd']:.4f} of ${r['budget_usd']:.2f}{' (budget stop hit)' if r['budget_stopped'] else ''}")
    print(f"\nviewer data written to {args.out}")
    return 0


def _fmt(v):
    return "n/a" if v is None else f"{v:.4f}"


def _print_result(res: dict) -> None:
    k = res["district_kpis"]
    parts = [f"{key}={k[key]:.4f}" for key in dc.HEADLINE_KPIS if k.get(key) is not None]
    print(f"  done: {res['steps']} hours{'' if res['complete'] else ' (partial)'}; " + ", ".join(parts))
    if res.get("calls"):
        print(f"  model calls {res['calls']}, clamped {res['clamped_steps']}, fallback {res['fallback_steps']}, "
              f"cost ${res['cost_usd']:.4f}{'; ' + res['budget_stop_reason'] if res['budget_stopped'] else ''}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="hyperbolic", description="Supervisory control experiments on CityLearn.")
    p.add_argument("--version", action="version", version=f"hyperbolic {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("baseline", help="run CityLearn's no-control reference")
    _common(b)
    b.set_defaults(func=cmd_baseline)

    r = sub.add_parser("run", help="run the supervisor through the safety envelope")
    _common(r)
    r.add_argument("--model", default=DEFAULT_MODEL, choices=sorted(MODELS), help="model (default: haiku)")
    r.add_argument("--budget", type=float, default=DEFAULT_BUDGET_USD, help="hard USD budget per run (default: 2)")
    r.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    r.add_argument("--effort", default=DEFAULT_EFFORT, choices=["low", "medium", "high"])
    r.add_argument("--scripted", action="store_true", help="deterministic scripted replies, no API calls")
    r.set_defaults(func=cmd_run)

    rp = sub.add_parser("replay", help="re-run a saved run from its files with zero model or simulator calls")
    rp.add_argument("run_dir", type=Path)
    rp.add_argument("--out", type=Path, default=None, help="optionally write the replayed run to this new folder")
    rp.set_defaults(func=cmd_replay)

    c = sub.add_parser("compare", help="compare the baseline and agent runs and write the viewer data")
    c.add_argument("--runs-dir", type=Path, default=Path("runs"))
    c.add_argument("--pair", nargs=2, metavar=("BASELINE_DIR", "AGENT_DIR"))
    c.add_argument("--out", type=Path, default=DEFAULT_VIEWER_DATA)
    c.set_defaults(func=cmd_compare)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
