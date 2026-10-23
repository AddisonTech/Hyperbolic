"""Estimate prompt version 7 on a recorded version 6 run, as an evaluation, never a recorded run.

    python scripts/evaluate_fit.py RUN_DIR

The run's own replies are sent hour by hour through its own rules (the 0.8.0 envelope, unchanged)
on a fresh CityLearn month with zero model calls:

  control  the replies as recorded, on the recorded prompt version. It must reproduce the run's
           published KPIs exactly, or the script stops.
  fit      the same replies as an agent that keeps inside the envelope would send them, on prompt
           version 7: cooling and battery moved into the cooling_range and battery_range its
           observation shows, and a held trim left to null sent at the top of its range. The
           envelope applied nearly the same actions anyway, so the clamps left are the ones the
           agent could not have avoided by seeing the constraint.
  battery  fit, with every battery at strategy_battery: the run's own cooling with the battery
           plan followed exactly.

The replies are fixed, so later hours do not react to what changed, and nothing here measures how
a model reads the version 7 prompt. It prints the KPIs, clamped hours, clamps by rule and the
exact ramping split (scripts/split_ramping.py) for all three.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from evaluate_hold import KPI_KEYS, clamp_rules  # noqa: E402
from split_ramping import split, table  # noqa: E402

from hyperbolic.envelope import Envelope, EnvelopeConfig  # noqa: E402
from hyperbolic.model import Budget, CallResult, RecordedReplySupervisor, observation_from_request  # noqa: E402
from hyperbolic.runner import AgentController, NullWriter, run_session  # noqa: E402

FIT_PROMPT_VERSION = 7


def fit_reply(reply: dict, obs: dict, battery_plan: bool = False) -> dict:
    """A reply moved inside the ranges a version 7 observation shows."""
    out = json.loads(json.dumps(reply))
    for b, s in obs["buildings"].items():
        acts = out[b]
        rng, held = s["cooling_range"], s["trim"]["state"] in ("hold", "ease")
        if acts.get("end_trim") or rng is None:
            acts["cooling"] = None
        elif acts["cooling"] is None:
            acts["cooling"] = rng[1] if held else None
        else:
            acts["cooling"] = min(max(acts["cooling"], rng[0]), rng[1])
        lo, hi = s["battery_range"]
        if battery_plan:
            acts["battery"] = s["strategy_battery"]
        elif acts["battery"] is not None:
            acts["battery"] = min(max(acts["battery"], lo), hi)
    return out


class FittedReplySupervisor(RecordedReplySupervisor):
    """A recorded run's replies, hour by hour, fitted to each version 7 request's ranges."""

    kind = "recorded"

    def __init__(self, calls_path: Path, model_key: str, battery_plan: bool = False) -> None:
        super().__init__(calls_path, model_key)
        self.battery_plan = battery_plan

    def call(self, step: int, request: dict) -> CallResult:
        res = super().call(step, request)
        if res.text is None:
            return res
        res.text = json.dumps(fit_reply(json.loads(res.text), observation_from_request(request), self.battery_plan))
        return res


def evaluate(run_dir: Path, mode: str) -> dict:
    from hyperbolic.sim import CityLearnSimulator

    class KeepEnv(CityLearnSimulator):
        def close(self) -> None:  # keep the finished env for the ramping split
            pass

    m = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    sup = m["supervisor"]
    calls = run_dir / "calls.jsonl"
    if mode == "control":
        supervisor, version = RecordedReplySupervisor(calls, sup["model_key"]), int(sup.get("prompt_version", 1))
    else:
        supervisor, version = FittedReplySupervisor(calls, sup["model_key"], mode == "battery"), FIT_PROMPT_VERSION
    ctl = AgentController(supervisor=supervisor, envelope=Envelope(EnvelopeConfig.from_manifest(m["envelope"])),
                          budget=Budget(limit_usd=float(sup["budget_usd"])), max_tokens=int(sup["max_tokens"]),
                          effort=sup["effort"], prompt_version=version)
    sim, w = KeepEnv(control=True), NullWriter()
    res = run_session(sim, ctl, w, hours=m.get("hours_limit"), sim_info={"kind": "citylearn", "control": True},
                      log=lambda *_: None)
    return {"result": res, "steps": w.steps, "split": split(sim.env, w.steps)}


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if len(args) != 1:
        print(__doc__.splitlines()[2].strip(), file=sys.stderr)
        return 2
    run_dir = Path(args[0])
    m = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    if not (m.get("envelope") or {}).get("trim_hold") or int(m["supervisor"].get("prompt_version", 1)) != 6:
        print("this needs a prompt version 6 run recorded with the trim hold", file=sys.stderr)
        return 2
    published = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))["district_kpis"]
    runs = {mode: evaluate(run_dir, mode) for mode in ("control", "fit", "battery")}
    got = runs["control"]["result"]["district_kpis"]
    if got != published:
        diff = {k: (published.get(k), got.get(k)) for k in set(published) | set(got) if published.get(k) != got.get(k)}
        print(f"control does not reproduce the published KPIs: {diff}", file=sys.stderr)
        return 1
    print(f"{run_dir.name}: its own replies through its own rules (control), fitted to the version 7 ranges (fit), "
          "and fitted with the battery plan followed (battery); evaluations, not recorded runs")
    print("control reproduces the published KPIs exactly: yes")
    print(f"  {'CityLearn KPI (district)':<46}" + "".join(f"{k:>10}" for k in runs))
    for k in KPI_KEYS:
        print(f"  {k:<46}" + "".join(f"{r['result']['district_kpis'][k]:>10.4f}" for r in runs.values()))
    for name, ev in runs.items():
        r = ev["result"]
        print(f"  {name}: clamped hours {r['clamped_steps']}, fallback hours {r['fallback_steps']}; "
              f"clamps by rule (hours, clamps) {clamp_rules(ev['steps'])}")
    print()
    print(table({name: ev["split"] for name, ev in runs.items()}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
