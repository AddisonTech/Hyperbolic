"""Command line: hyperbolic baseline | run | replay | compare | serve."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from . import district as dc
from .envelope import Envelope
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
from .prompt import PROMPT_VERSION, PROMPT_VERSIONS
from .runner import (
    RULE_PROMPT_VERSION,
    AgentController,
    BaselineController,
    RunWriter,
    controller_settings,
    new_run_dir,
    replay_run,
    run_session,
)
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
    sim = _sim(control=False)
    try:
        sim.check_hours(args.hours)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    out = new_run_dir(args.runs_dir, "baseline", "citylearn")
    print(f"baseline, {dc.DATASET} -> {out}")
    res = run_session(sim, BaselineController(), RunWriter(out), args.hours,
                      {"kind": "citylearn", "control": False})
    _print_result(res)
    return 0


def cmd_run(args) -> int:
    if args.inject_faults and not args.scripted:
        print("error: --inject-faults needs --scripted", file=sys.stderr)
        return 2
    if not args.scripted:
        try:
            _, source = resolve_api_key()
        except KeyMissing as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        print(f"model key found in {source}")
    hours = args.hours or dc.EPISODE_HOURS
    try:
        sim = _sim(control=True)
        sim.check_hours(args.hours)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    faults = ScriptedSupervisor.default_faults(hours) if args.inject_faults else None
    sup = ScriptedSupervisor(args.model, faults=faults) if args.scripted else LiveSupervisor(args.model)
    prompt_version, envelope_cfg = controller_settings(args.scripted, args.prompt_version)
    ctl = AgentController(
        supervisor=sup,
        envelope=Envelope(envelope_cfg),
        budget=Budget(limit_usd=args.budget),
        max_tokens=args.max_tokens,
        effort=args.effort,
        prompt_version=prompt_version,
    )
    out = new_run_dir(args.runs_dir, "agent", "citylearn")
    print(f"agent, {dc.DATASET}, {sup.kind} replies, {MODELS[args.model]['id']}, "
          f"budget ${args.budget:.2f} -> {out}")
    res = run_session(sim, ctl, RunWriter(out), args.hours, {"kind": "citylearn", "control": True})
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
    others = []
    for d in args.against or []:
        try:
            others.append(_against(Path(d), s["hours"]))
        except (OSError, ValueError, KeyError) as exc:
            print(f"error: --against {d}: {exc}", file=sys.stderr)
            return 1
    print(f"\n{s['name']} ({s['hours']} h{', agent side is a SAMPLE' if s['agent_sample'] else ''})")
    print(f"  {s['headline']['text']}")
    print(f"  {'CityLearn KPI (district)':<44}{'baseline':>10}{'agent':>10}" + "".join(f"{o[0]:>12}" for o in others))
    for k in data["kpis"]:
        b, a = s["baseline"]["kpi"].get(k["id"]), s["agent"]["kpi"].get(k["id"])
        if b is None and a is None:
            continue
        print(f"  {k['id'] + ' (' + k['unit'] + ')':<44}{_fmt(b):>10}{_fmt(a):>10}"
              + "".join(f"{_fmt(o[1].get(k['id'])):>12}" for o in others))
    for label, _, d in others:
        print(f"  {label}: {d}")
    r = s["agent_run"]
    print(f"  model calls {r['calls']}, clamped hours {r['clamped_hours']}, fallback hours {r['fallback_hours']}, "
          f"cost ${r['cost_usd']:.4f} of ${r['budget_usd']:.2f}{' (budget stop hit)' if r['budget_stopped'] else ''}")
    print(f"\nviewer data written to {args.out}")
    return 0


def cmd_serve(args) -> int:
    from .live import serve

    try:
        return serve(port=args.port, host=args.host, runs_dir=args.runs_dir, docs=args.docs,
                     open_browser=not args.no_browser)
    except (ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"error: could not listen on 127.0.0.1:{args.port} ({exc.strerror or exc}); try --port", file=sys.stderr)
        return 2


def _against(run_dir: Path, hours: int) -> tuple[str, dict, Path]:
    """A finished agent run to print beside the compared pair, for example the rule-based controller."""
    m = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    r = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
    if m.get("mode") != "agent" or m.get("dataset") != dc.DATASET:
        raise ValueError("not an agent run on this dataset")
    if int(r.get("steps", 0)) != hours:
        raise ValueError(f"it covers {r.get('steps')} hours, the compared runs {hours}")
    sup = m.get("supervisor") or {}
    if sup.get("kind") == "scripted":
        pv = int(sup.get("prompt_version", 1))
        label = "rule-based" if pv <= RULE_PROMPT_VERSION else f"v{pv} script"
    else:
        label = str(sup.get("model_key") or sup.get("kind"))
    return label, r.get("district_kpis") or {}, run_dir


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
    r.add_argument("--scripted", action="store_true",
                   help="replies from the deterministic rule-based policy, no API calls")
    r.add_argument("--inject-faults", action="store_true",
                   help="with --scripted, send a bad reply now and then to exercise clamps and fallback")
    r.add_argument("--prompt-version", type=int, default=None, choices=PROMPT_VERSIONS,
                   help=f"observation and prompt version (default: {PROMPT_VERSION}; with --scripted, "
                        f"{RULE_PROMPT_VERSION}, the 0.4.0 rule-based controller, while versions 4 and 5 "
                        "run their strategies literally and version 6 runs the version 5 strategy with the "
                        "trim hold)")
    r.set_defaults(func=cmd_run)

    rp = sub.add_parser("replay", help="re-run a saved run from its files with zero model or simulator calls")
    rp.add_argument("run_dir", type=Path)
    rp.add_argument("--out", type=Path, default=None, help="optionally write the replayed run to this new folder")
    rp.set_defaults(func=cmd_replay)

    c = sub.add_parser("compare", help="compare the baseline and agent runs and write the viewer data")
    c.add_argument("--runs-dir", type=Path, default=Path("runs"))
    c.add_argument("--pair", nargs=2, metavar=("BASELINE_DIR", "AGENT_DIR"))
    c.add_argument("--out", type=Path, default=DEFAULT_VIEWER_DATA)
    c.add_argument("--against", action="append", metavar="AGENT_DIR",
                   help="also print this finished agent run's KPIs, for example the rule-based controller "
                        "(repeatable; the viewer data is unchanged)")
    c.set_defaults(func=cmd_compare)

    sv = sub.add_parser("serve", help="watch a run live in the browser (local only, 127.0.0.1)")
    sv.add_argument("--port", type=int, default=8765, help="port on 127.0.0.1 (default: 8765)")
    sv.add_argument("--host", default="127.0.0.1", help="only 127.0.0.1 or localhost are accepted")
    sv.add_argument("--runs-dir", type=Path, default=Path("runs"), help="where live runs are recorded")
    sv.add_argument("--docs", type=Path, default=Path("docs"), help="the viewer folder; Publish writes its data/")
    sv.add_argument("--no-browser", action="store_true", help="do not open a browser tab")
    sv.set_defaults(func=cmd_serve)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
