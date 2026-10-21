"""Command line: hyperbolic baseline | run | replay | compare."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from . import testcase as tc
from .boptest import DEFAULT_URL, BoptestClient, BoptestError
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
from .viewer import find_latest_pairs, write_viewer_data

DEFAULT_VIEWER_DATA = Path("docs/data/viewer.json")


def _sim_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--scenario", action="append", choices=sorted(tc.SCENARIOS),
                   help="BOPTEST time period; repeat for several (default: typical_heat_day and peak_heat_day)")
    p.add_argument("--price", default=tc.DEFAULT_ELECTRICITY_PRICE, choices=sorted(tc.PRICE_POINT),
                   help="BOPTEST electricity price scenario (default: dynamic)")
    p.add_argument("--url", default=DEFAULT_URL, help=f"BOPTEST service URL (default: {DEFAULT_URL})")
    p.add_argument("--mock", action="store_true", help="use the offline mock simulator instead of BOPTEST")
    p.add_argument("--hours", type=int, default=None, help="stop after this many hours (default: full scenario)")
    p.add_argument("--kpi-every", type=int, default=1, help="read running KPIs every N hours (default: 1)")
    p.add_argument("--runs-dir", type=Path, default=Path("runs"), help="where run folders go (default: runs)")


def _make_sim(args):
    if args.mock:
        from .mock import MockBoptest

        return MockBoptest(), {"kind": "mock"}
    return BoptestClient(url=args.url), {"kind": "boptest", "url": args.url}


def _scenarios(args) -> list[str]:
    return args.scenario or list(tc.DEFAULT_SCENARIOS)


def cmd_baseline(args) -> int:
    for sc in _scenarios(args):
        sim, info = _make_sim(args)
        out = new_run_dir(args.runs_dir, sc, "baseline", info["kind"])
        print(f"baseline {sc} ({info['kind']}) -> {out}")
        res = run_session(sim, BaselineController(), RunWriter(out), sc, args.price, args.hours, args.kpi_every, info)
        _print_result(res)
    return 0


def cmd_run(args) -> int:
    scripted = args.scripted or (args.mock and not args.live_model)
    if not scripted:
        try:
            _, source = resolve_api_key()
        except KeyMissing as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        print(f"model key found in {source}")
    for sc in _scenarios(args):
        sim, info = _make_sim(args)
        if scripted:
            hours = args.hours or (tc.SCENARIOS[sc]["end_day"] - tc.SCENARIOS[sc]["start_day"]) * 24
            sup = ScriptedSupervisor(args.model, faults=ScriptedSupervisor.default_faults(hours))
        else:
            sup = LiveSupervisor(args.model)
        ctl = AgentController(
            supervisor=sup,
            envelope=Envelope(EnvelopeConfig()),
            budget=Budget(limit_usd=args.budget),
            electricity_price=args.price,
            max_tokens=args.max_tokens,
            effort=args.effort,
        )
        out = new_run_dir(args.runs_dir, sc, "agent", info["kind"])
        print(f"agent {sc} ({info['kind']}, {sup.kind} replies, {MODELS[args.model]['id']}, "
              f"budget ${args.budget:.2f}) -> {out}")
        res = run_session(sim, ctl, RunWriter(out), sc, args.price, args.hours, args.kpi_every, info)
        _print_result(res)
    return 0


def cmd_replay(args) -> int:
    rep = replay_run(args.run_dir, out_dir=args.out)
    print(f"replayed {args.run_dir}: {rep.steps} hours, {rep.calls} recorded calls, {rep.api_calls} API calls")
    print(f"  identical decisions and overwrites: {rep.identical_steps}/{rep.steps}")
    print(f"  clamped hours {rep.clamped_steps}, fallback hours {rep.fallback_steps}, recorded cost ${rep.cost_usd:.4f}")
    if rep.deterministic:
        print("  deterministic: yes")
        return 0
    print(f"  deterministic: NO, first mismatches at hours {rep.mismatched_steps[:10]}")
    if rep.error:
        print(f"  stopped: {rep.error}")
    return 1


def cmd_compare(args) -> int:
    if args.pair:
        pairs = [(Path(b), Path(a)) for b, a in args.pair]
    else:
        # Per scenario: BOPTEST runs win, mock runs fill in as a labeled sample.
        pairs = find_latest_pairs(args.runs_dir, args.scenario, "mock" if args.mock else None)
    if not pairs:
        print("no matching baseline and agent runs found; run `hyperbolic baseline` and `hyperbolic run` first",
              file=sys.stderr)
        return 1
    data = write_viewer_data(pairs, args.out)
    for s in data["scenarios"]:
        print(f"\n{s['name']} ({s['id']}, price {s['electricity_price']}, {s['hours']} h"
              f"{', SAMPLE' if s['sample'] else ''})")
        print(f"  {s['headline']['text']}")
        print(f"  {'KPI':<28}{'baseline':>12}{'agent':>12}{'change':>9}")
        for k in data["kpis"]:
            b, a = s["baseline"]["kpi"].get(k["id"]), s["agent"]["kpi"].get(k["id"])
            if b is None and a is None:
                continue
            ch = "" if (b in (None, 0) or a is None) else f"{(a - b) / abs(b) * 100:+.1f}%"
            name = f"{k['id']} ({k['unit']})"
            print(f"  {name:<28}{_fmt(b):>12}{_fmt(a):>12}{ch:>9}")
        r = s["agent_run"]
        print(f"  model calls {r['calls']}, clamped hours {r['clamped_hours']}, fallback hours {r['fallback_hours']}, "
              f"cost ${r['cost_usd']:.4f} of ${r['budget_usd']:.2f}{' (budget stop hit)' if r['budget_stopped'] else ''}")
    print(f"\nviewer data written to {args.out}")
    return 0


def _fmt(v):
    return "n/a" if v is None else f"{v:.4f}"


def _print_result(res: dict) -> None:
    k = res["final_kpi"] or {}
    parts = [f"{key}={k[key]:.4f}" for key in ("tdis_tot", "ener_tot", "cost_tot") if k.get(key) is not None]
    print(f"  done: {res['steps']} hours{'' if res['complete'] else ' (partial)'}; " + ", ".join(parts))
    if res.get("calls"):
        print(f"  model calls {res['calls']}, clamped {res['clamped_steps']}, fallback {res['fallback_steps']}, "
              f"cost ${res['cost_usd']:.4f}{'; ' + res['budget_stop_reason'] if res['budget_stopped'] else ''}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="hyperbolic", description="Supervisory control experiments on BOPTEST.")
    p.add_argument("--version", action="version", version=f"hyperbolic {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("baseline", help="run the test case's own control with no overwrites")
    _sim_args(b)
    b.set_defaults(func=cmd_baseline)

    r = sub.add_parser("run", help="run the supervisor through the safety envelope")
    _sim_args(r)
    r.add_argument("--model", default=DEFAULT_MODEL, choices=sorted(MODELS), help="model (default: haiku)")
    r.add_argument("--budget", type=float, default=DEFAULT_BUDGET_USD, help="hard USD budget per run (default: 2)")
    r.add_argument("--max-tokens", type=int, default=DEFAULT_MAX_TOKENS)
    r.add_argument("--effort", default=DEFAULT_EFFORT, choices=["low", "medium", "high"])
    r.add_argument("--scripted", action="store_true", help="deterministic scripted replies, no API calls")
    r.add_argument("--live-model", action="store_true", help="with --mock, call the real model anyway")
    r.set_defaults(func=cmd_run)

    rp = sub.add_parser("replay", help="re-run a saved run from its files with zero API calls")
    rp.add_argument("run_dir", type=Path)
    rp.add_argument("--out", type=Path, default=None, help="optionally write the replayed run to this new folder")
    rp.set_defaults(func=cmd_replay)

    c = sub.add_parser("compare", help="compare baseline and agent runs and write the viewer data")
    c.add_argument("--runs-dir", type=Path, default=Path("runs"))
    c.add_argument("--scenario", action="append", choices=sorted(tc.SCENARIOS))
    c.add_argument("--pair", nargs=2, action="append", metavar=("BASELINE_DIR", "AGENT_DIR"))
    c.add_argument("--mock", action="store_true", help="use only mock runs (the labeled sample)")
    c.add_argument("--out", type=Path, default=DEFAULT_VIEWER_DATA)
    c.set_defaults(func=cmd_compare)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except BoptestError as exc:
        print(f"BOPTEST error: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
