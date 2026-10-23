"""scripts/split_ramping.py, scripts/evaluate_hold.py and scripts/evaluate_fit.py: the 0.8.0 and 0.9.0
diagnosis and estimate tools, and the version 7 search grid."""

import dataclasses
import json
import sys
from pathlib import Path

import pytest
from conftest import needs_citylearn

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

import evaluate_fit  # noqa: E402
import evaluate_hold  # noqa: E402
import split_ramping  # noqa: E402
import tune_strategy  # noqa: E402

from hyperbolic.envelope import Envelope, EnvelopeConfig  # noqa: E402
from hyperbolic.model import Budget, ScriptedSupervisor, StrategyParamsV7, StrategyParamsV8  # noqa: E402
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


def _fit_obs(state="hold", rng=(0.2, 0.25), battery_range=(-0.3, 0.2)):
    b = {"trim": {"state": state}, "cooling_range": None if rng is None else list(rng),
         "battery_range": list(battery_range), "strategy_battery": -0.1}
    return {"buildings": {"Building_1": b}}


def test_fit_reply_moves_a_reply_inside_the_version_7_ranges():
    reply = {"reason": "r", "Building_1": {"cooling": None, "dhw": None, "battery": 0.5, "end_trim": None}}
    out = evaluate_fit.fit_reply(reply, _fit_obs())
    assert out["Building_1"]["cooling"] == 0.25 and out["Building_1"]["battery"] == 0.2  # held trim: top of range
    assert reply["Building_1"]["cooling"] is None  # the recorded reply is not changed
    assert evaluate_fit.fit_reply(reply, _fit_obs(state="off"))["Building_1"]["cooling"] is None
    reply["Building_1"]["cooling"] = 0.4
    assert evaluate_fit.fit_reply(reply, _fit_obs(state="off"))["Building_1"]["cooling"] == 0.25
    assert evaluate_fit.fit_reply(reply, _fit_obs(rng=None))["Building_1"]["cooling"] is None
    reply["Building_1"]["end_trim"] = "room is warming"
    assert evaluate_fit.fit_reply(reply, _fit_obs())["Building_1"]["cooling"] is None
    assert evaluate_fit.fit_reply(reply, _fit_obs(), battery_plan=True)["Building_1"]["battery"] == -0.1


def test_v7_grid_holds_the_shipped_battery_plan_once():
    grid = tune_strategy.grid_v7()
    shipped = dataclasses.asdict(StrategyParamsV7())
    assert grid.count(shipped) == 1 and len(grid) == len({json.dumps(c, sort_keys=True) for c in grid})
    assert StrategyParamsV7().rise_step >= StrategyParamsV7().max_step and not StrategyParamsV7().fill_valley


def test_v8_grid_holds_the_shipped_numbers_once_and_the_rule_puts_comfort_first():
    grid = tune_strategy.grid_v8()
    shipped = dataclasses.asdict(StrategyParamsV8())
    assert grid.count(shipped) == 1 and len(grid) == 36 == len({json.dumps(c, sort_keys=True) for c in grid})
    base = [{"discomfort_hot_proportion": 0.05}, {"discomfort_hot_proportion": 0.003}]
    ref = {"discomfort_cold_proportion": 0.011}
    ok = {"discomfort_cold_proportion": 0.0115, "ramping_average": 0.99, "daily_peak_average": 0.89,
          "all_time_peak_average": 0.85, "cost_total": 0.95}
    months = [{"discomfort_hot_proportion": 0.01}, {"discomfort_hot_proportion": 0.003}]
    assert tune_strategy.qualifies_v8(ok, months, base, ref)
    assert not tune_strategy.qualifies_v8(ok, [months[0], {"discomfort_hot_proportion": 0.004}], base, ref)
    assert not tune_strategy.qualifies_v8({**ok, "discomfort_cold_proportion": 0.0125}, months, base, ref)
    assert not tune_strategy.qualifies_v8({**ok, "ramping_average": 1.01}, months, base, ref)
