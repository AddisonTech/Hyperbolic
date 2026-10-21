"""Regenerate the recorded runs and golden viewer data used by the tests.

    python tests/fixtures/make_fixtures.py

Only needed when the run file format, the envelope or the mock changes on purpose.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from hyperbolic.envelope import Envelope
from hyperbolic.mock import MockBoptest
from hyperbolic.model import Budget, ScriptedSupervisor
from hyperbolic.runner import AgentController, BaselineController, RunWriter, run_session
from hyperbolic.viewer import build_viewer_data, dumps

HERE = Path(__file__).parent
RUNS = HERE / "runs"
SCENARIO = "typical_heat_day"
HOURS = 30
FAULTS = {4: "too_fast", 8: "out_of_range", 10: "malformed", 12: "below_comfort", 14: "missing", 16: "schema"}
BASELINE = RUNS / f"{SCENARIO}_baseline_mock_fixture"
AGENT = RUNS / f"{SCENARIO}_agent_mock_fixture"
GOLDEN = HERE / "viewer_golden.json"


def make_agent_controller() -> AgentController:
    return AgentController(
        supervisor=ScriptedSupervisor("haiku", faults=FAULTS, tokens=(2400, 180)),
        envelope=Envelope(),
        budget=Budget(limit_usd=2.0),
    )


def main() -> None:
    shutil.rmtree(RUNS, ignore_errors=True)
    quiet = lambda *_: None  # noqa: E731
    run_session(MockBoptest(), BaselineController(), RunWriter(BASELINE), SCENARIO, hours=HOURS,
                sim_info={"kind": "mock"}, log=quiet)
    run_session(MockBoptest(), make_agent_controller(), RunWriter(AGENT), SCENARIO, hours=HOURS,
                sim_info={"kind": "mock"}, log=quiet)
    for d in (BASELINE, AGENT):
        # Fixed timestamps so the fixture files are stable in git.
        for name in ("manifest.json", "result.json"):
            p = d / name
            data = json.loads(p.read_text(encoding="utf-8"))
            for key in ("started_at", "finished_at"):
                if key in data:
                    data[key] = "2026-01-01T00:00:00+00:00"
            p.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    GOLDEN.write_text(dumps(build_viewer_data([(BASELINE, AGENT)])), encoding="utf-8")
    print(f"wrote {BASELINE}, {AGENT}, {GOLDEN}")


if __name__ == "__main__":
    main()
