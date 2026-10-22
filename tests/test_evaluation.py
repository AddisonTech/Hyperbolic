"""scripts/split_ramping.py and scripts/evaluate_hold.py: the 0.8.0 diagnosis and estimate tools."""

import dataclasses
import json
import sys
from pathlib import Path

import pytest
from conftest import needs_citylearn

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

import evaluate_hold  # noqa: E402
import split_ramping  # noqa: E402

from hyperbolic.envelope import Envelope, EnvelopeConfig  # noqa: E402
from hyperbolic.model import Budget, ScriptedSupervisor  # noqa: E402
from hyperbolic.runner import AgentController, RunWriter, run_session  # noqa: E402


@pytest.mark.parametrize("start, deltas", [(0.5, [0.3, -0.9, 0.2]), (-1.0, [0.4, 0.4, 0.4]), (2.0, [0.0, -0.5])])
def test_shapley_shares_add_up_to_the_rise(start, deltas):
    phi = split_ramping._shapley(start, deltas)
    assert sum(phi) == pytest.approx(max(0.0, start + sum(deltas)) - max(0.0, start))


def test_equal_causes_get_equal_shares():
    a, b = split_ramping._shapley(0.0, [0.3, 0.3])
    assert a == pytest.approx(b) == pytest.approx(0.3)


@needs_citylearn
def test_evaluation_control_reproduces_a_recorded_run_and_the_split_adds_up(tmp_path):
    from hyperbolic.sim import CityLearnSimulator

    run = tmp_path / "v5"
    ctl = AgentController(ScriptedSupervisor(), Envelope(EnvelopeConfig.v070()), Budget(2.0), prompt_version=5)
    run_session(CityLearnSimulator(control=True), ctl, RunWriter(run), hours=47, log=lambda *_: None,
                sim_info={"kind": "citylearn", "control": True})
    published = json.loads((run / "result.json").read_text(encoding="utf-8"))["district_kpis"]
    control = evaluate_hold.evaluate(run, EnvelopeConfig.v070())
    assert control["result"]["district_kpis"] == published
    s = control["split"]
    assert s["ramping_average"] == pytest.approx(published["ramping_average"], abs=1e-6)
    assert s["reference_kwh"] + sum(s["shares_kwh"].values()) == pytest.approx(s["ramping_kwh"])
    hold = evaluate_hold.evaluate(run, dataclasses.replace(EnvelopeConfig.v070(), trim_hold=True))
    assert hold["result"]["steps"] == 47
    env, steps = split_ramping.resimulate(run)
    assert split_ramping.split(env, steps)["ramping_kwh"] == pytest.approx(s["ramping_kwh"])
    assert evaluate_hold.trim_episodes(control["steps"])["episodes"] >= 0
