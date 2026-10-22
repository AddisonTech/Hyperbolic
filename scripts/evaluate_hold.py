"""Estimate the 0.8.0 trim hold on a recorded live run, as an evaluation, never a recorded run.

    python scripts/evaluate_hold.py RUN_DIR

The run's own replies are sent hour by hour, unchanged, through two envelopes on a fresh
CityLearn month with zero model calls:

  control  the rules the run was recorded with. It must reproduce the run's published KPIs
           exactly, or the script stops: that proves the replay path itself changes nothing.
  hold     the same rules with the trim hold on (EnvelopeConfig.trim_hold).

The replies are fixed, so later hours do not react to what the hold changed (a warmer or cooler
room), and nothing here measures what a version 6 prompt would change. It prints both sets of
KPIs, the clamps by rule, the hold's actions, trim episodes counted as in the 0.7.0 diagnosis,
and the exact ramping split (scripts/split_ramping.py) for both.
"""

from __future__ import annotations

import collections
import dataclasses
import json
import statistics
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from split_ramping import split, table  # noqa: E402

from hyperbolic.envelope import Envelope, EnvelopeConfig  # noqa: E402
from hyperbolic.model import Budget, RecordedReplySupervisor  # noqa: E402
from hyperbolic.runner import AgentController, NullWriter, load_jsonl, run_session  # noqa: E402

KPI_KEYS = ("cost_total", "carbon_emissions_total", "electricity_consumption_total", "discomfort_proportion",
            "discomfort_cold_proportion", "discomfort_hot_proportion", "daily_peak_average", "all_time_peak_average",
            "ramping_average", "daily_one_minus_load_factor_average", "power_outage_normalized_unserved_energy_total")
TRIM_MIN = 0.002


def evaluate(run_dir: Path, cfg: EnvelopeConfig) -> dict:
    from hyperbolic.sim import CityLearnSimulator

    class KeepEnv(CityLearnSimulator):
        def close(self) -> None:  # keep the finished env for the ramping split
            pass

    m = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    sup = m["supervisor"]
    ctl = AgentController(
        supervisor=RecordedReplySupervisor(run_dir / "calls.jsonl", sup["model_key"]),
        envelope=Envelope(cfg),
        budget=Budget(limit_usd=float(sup["budget_usd"])),
        max_tokens=int(sup["max_tokens"]),
        effort=sup["effort"],
        prompt_version=int(sup.get("prompt_version", 1)),
    )
    sim, w = KeepEnv(control=True), NullWriter()
    res = run_session(sim, ctl, w, hours=m.get("hours_limit"), sim_info={"kind": "citylearn", "control": True},
                      log=lambda *_: None)
    return {"result": res, "steps": w.steps, "split": split(sim.env, w.steps)}


def trim_episodes(steps: list[dict]) -> dict:
    """Trim episodes as the 0.7.0 diagnosis counted them: cooling more than 0.002 below the
    baseline action, and episodes that ended within the month. An end broke the version 5 rule
    when the room was occupied, still below its setpoint and the baseline still had cooling to
    trim, and either the room was more than 0.5 C too cold or the trim dropped more than 0.02."""
    lengths, occupied_ends, cold_ends, fast_ends = [], 0, 0, 0
    for b in steps[0]["actions"]:
        run, depth = 0, 0.0
        for s in steps:
            d = s["state"]["baseline"][b]["cooling"] - s["actions"][b]["cooling"]
            if d > TRIM_MIN:
                run, depth = run + 1, d
                continue
            if run:
                lengths.append(run)
                st = s["state"]["buildings"][b]
                gap = st["indoor_c"] - st["setpoint_c"]
                if st["occupants"] > 0:
                    occupied_ends += 1
                    if gap < 0 and s["state"]["baseline"][b]["cooling"] > TRIM_MIN:
                        if gap < -0.5:
                            cold_ends += 1
                        elif depth > 0.02 + 1e-9:
                            fast_ends += 1
            run = 0
    return {"episodes": len(lengths), "median_hours": statistics.median(lengths) if lengths else 0,
            "one_hour": sum(1 for x in lengths if x == 1), "ended_occupied": occupied_ends,
            "broke_rule": cold_ends + fast_ends, "ended_too_cold": cold_ends, "dropped_fast": fast_ends}


def clamp_rules(steps: list[dict]) -> dict:
    hours, clamps = collections.Counter(), collections.Counter()
    for s in steps:
        rules = [c["rule"] for c in (s["decision"] or {}).get("clamps", [])]
        clamps.update(rules)
        hours.update(set(rules))
    return {r: (hours[r], clamps[r]) for r in sorted(clamps)}


def hold_actions(steps: list[dict]) -> dict:
    out = collections.Counter()
    for s in steps:
        for h in (s["decision"] or {}).get("holds", []):
            kind = h["action"]
            if kind == "end":
                kind = ("end: no baseline cooling" if "baseline" in h["reason"] else
                        "end: unoccupied" if "unoccupied" in h["reason"] else "end: at or above setpoint")
            out[kind] += 1
    return dict(sorted(out.items()))


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1:
        print(__doc__.splitlines()[2].strip(), file=sys.stderr)
        return 2
    run_dir = Path(args[0])
    m = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    published = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))["district_kpis"]
    control_cfg = EnvelopeConfig.from_manifest(m["envelope"])
    if control_cfg.trim_hold:
        print("this run was recorded with the trim hold already on", file=sys.stderr)
        return 2
    control = evaluate(run_dir, control_cfg)
    got = control["result"]["district_kpis"]
    if got != published:
        diff = {k: (published.get(k), got.get(k)) for k in set(published) | set(got) if published.get(k) != got.get(k)}
        print(f"control does not reproduce the published KPIs: {diff}", file=sys.stderr)
        return 1
    hold = evaluate(run_dir, dataclasses.replace(control_cfg, trim_hold=True))
    recorded = load_jsonl(run_dir / "steps.jsonl")
    if [s["actions"] for s in control["steps"]] != [s["actions"] for s in recorded]:
        print("control actions differ from the recording", file=sys.stderr)
        return 1
    hk = hold["result"]["district_kpis"]
    print(f"{run_dir.name}: its own replies through the {m.get('tool_version')} rules (control) and with the "
          "trim hold (evaluation, not a recorded run)")
    print("control reproduces the published KPIs exactly: yes")
    print(f"  {'CityLearn KPI (district)':<46}{'control':>10}{'hold':>10}{'change':>10}")
    for k in KPI_KEYS:
        print(f"  {k:<46}{got[k]:>10.4f}{hk[k]:>10.4f}{hk[k] - got[k]:>+10.4f}")
    for name, ev in (("control", control), ("hold", hold)):
        r = ev["result"]
        print(f"  {name}: clamped hours {r['clamped_steps']}, fallback hours {r['fallback_steps']}; "
              f"clamps by rule (hours, clamps) {clamp_rules(ev['steps'])}")
        print(f"  {name}: trims {trim_episodes(ev['steps'])}")
    print(f"  hold actions: {hold_actions(hold['steps'])}")
    print()
    print(table({"control": control["split"], "hold": hold["split"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
