"""The 0.11.0 peak diagnosis (scripts/analyze_peaks.py, scripts/analyze_deviations.py on version 8 runs) and the
version 9 acceptance rule (scripts/tune_strategy.py)."""

import json
import sys
from dataclasses import asdict
from pathlib import Path

import pytest
from conftest import BUILDINGS, needs_citylearn
from test_prompt_v8 import _obs, _warm

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

import analyze_deviations as ad  # noqa: E402
import analyze_peaks as ap  # noqa: E402
import tune_strategy as ts  # noqa: E402

from hyperbolic import months as mo  # noqa: E402
from hyperbolic.envelope import Envelope, EnvelopeConfig  # noqa: E402
from hyperbolic.model import (  # noqa: E402
    Budget,
    CallResult,
    ScriptedSupervisor,
    StrategyParamsV8,
    StrategyParamsV9,
    observation_from_request,
    strategy_plan_v8,
)
from hyperbolic.prompt import build_request  # noqa: E402
from hyperbolic.runner import AgentController, RunWriter, run_session  # noqa: E402

# -- peak hours ------------------------------------------------------------------------


def test_peak_hours_find_the_all_time_and_daily_peaks_district_and_per_building():
    a = [1.0] * 48
    b = [0.5] * 48
    a[20], b[20] = 6.0, 1.0   # day 1's peak, and the all-time peak (7.0)
    a[30], b[33] = 4.0, 5.5   # day 2: the district peaks at 33 (6.5); Building_1 alone at 30
    got = ap.peak_hours({"Building_1": a, "Building_2": b}, top=2)
    assert got["all_time"] == {"step": 20, "kwh": 7.0, "buildings": {"Building_1": 6.0, "Building_2": 1.0}}
    assert [p["step"] for p in got["top_daily"]] == [20, 33]
    assert got["daily_mean_kwh"] == pytest.approx((7.0 + 6.5) / 2)
    assert got["building_peaks"] == {"Building_1": {"step": 20, "kwh": 6.0}, "Building_2": {"step": 33, "kwh": 5.5}}


def test_ranking_orders_classes_by_all_time_peak_then_daily_peak_then_ramping():
    def k(at, daily, ramp):
        return {"all_time_peak_average": at, "daily_peak_average": daily, "ramping_average": ramp}

    runs = [{"kpis": {"control": k(0.90, 0.89, 1.0), "strategy": k(0.85, 0.88, 0.99), "all": k(0.85, 0.88, 0.99),
                      "shave_skipped": k(0.86, 0.885, 0.995), "charge_skipped": k(0.90, 0.889, 0.98),
                      "trim_not_started": k(0.90, 0.887, 1.01)}},
            {"kpis": {"control": k(0.95, 0.90, 1.0), "strategy": k(0.95, 0.90, 1.0),
                      "shave_skipped": k(0.95, 0.899, 1.0), "charge_skipped": k(0.95, 0.90, 0.99),
                      "trim_not_started": k(0.95, 0.90, 1.0)}}]
    got = ap.ranking(runs)
    assert [n for n, _ in got] == ["shave_skipped", "trim_not_started", "charge_skipped"]
    assert got[0][1]["all_time_peak_average"] == pytest.approx(0.04)
    assert got[0][1]["daily_peak_average"] == pytest.approx(0.006)
    assert got[2][1]["ramping_average"] == pytest.approx(0.03)


# -- deviation classes on version 8 runs -----------------------------------------------------


def test_a_v8_observation_is_measured_against_its_own_strategy():
    *_, obs = _obs(version=8)
    assert ad.strategy_for(obs) == {b: obs["buildings"][b]["strategy"] for b in BUILDINGS}
    assert ad.classify(obs, json.loads(json.dumps(strategy_plan_v8(obs))), ad.strategy_for(obs)) == []
    *_, v6 = _obs(version=6)
    with pytest.raises(ValueError):
        ad.strategy_for(v6)


def test_cooling_below_the_strategys_warm_room_boost_is_warm_skipped():
    *_, obs = _obs(version=8)
    _warm(obs, gap=3.0)
    plan = strategy_plan_v8(obs)
    assert plan["Building_1"]["cooling"] > 0.3 + ad.COOLING_TOL
    reply = json.loads(json.dumps(plan))
    reply["Building_1"]["cooling"] = None
    assert ad.classify(obs, reply, plan) == [("Building_1", "warm_skipped")]
    reply["Building_1"]["cooling"] = plan["Building_1"]["cooling"] + 0.02
    assert ad.classify(obs, reply, plan) == [("Building_1", "extra_cooling")]


def test_replays_run_on_the_month_the_run_was_recorded_on_and_never_the_holdout(tmp_path):
    assert ad.month_schema_for({"dataset": mo.PHASE2 and "citylearn_challenge_2023_phase_2_local_evaluation"},
                               tmp_path) is None
    got = ad.month_schema_for({"dataset": mo.month("tuning-07").dataset}, tmp_path)
    assert got.name == "schema.json" and got.parent.name == "tuning-07"
    with pytest.raises(ValueError):
        ad.month_schema_for({"dataset": mo.month("holdout-07").dataset}, tmp_path)


def test_around_shows_the_model_and_the_strategy_with_the_classes(tmp_path):
    *_, env, obs = _obs(version=8)
    req = build_request(obs, env.config, BUILDINGS, "haiku", prompt_version=8)
    plan = strategy_plan_v8(observation_from_request(req))
    mine = json.loads(json.dumps(plan))
    mine["Building_2"]["battery"] = round(plan["Building_2"]["battery"] + 0.1, 3)
    with (tmp_path / "calls.jsonl").open("w", encoding="utf-8") as f:
        for step, reply in ((3, plan), (4, mine)):
            f.write(json.dumps({"step": step, "request": req, "reply": {"text": json.dumps(reply)}}) + "\n")
    got = ap.around(tmp_path, 4, lookback=1)
    assert [h["step"] for h in got] == [3, 4] and got[0]["classes"] == []
    assert got[1]["buildings"]["Building_2"]["model"]["battery"] == mine["Building_2"]["battery"]
    assert got[1]["buildings"]["Building_2"]["strategy"]["battery"] == plan["Building_2"]["battery"]
    assert len(got[1]["classes"]) == 1 and got[1]["classes"][0].startswith("Building_2 ")


class _NoShave(ScriptedSupervisor):
    """The version 8 strategy, except that it never discharges outside a top-price hour."""

    def call(self, step: int, request: dict) -> CallResult:
        obs = observation_from_request(request)
        reply = strategy_plan_v8(obs)
        if not obs["price_plan"]["top_price_now"]:
            for b in reply:
                if b != "reason" and reply[b]["battery"] < 0:
                    reply[b]["battery"] = 0.0
        return CallResult(json.dumps(reply), stop_reason="end_turn", model="scripted")


@needs_citylearn
def test_peak_diagnosis_on_a_recorded_citylearn_run(tmp_path):
    """A version 8 run on tuning July that never shaves: its departures are skipped shaves, the control
    replay reproduces it, its series gives the peak hours, and putting the class back changes the month."""
    from hyperbolic.sim import CityLearnSimulator

    run = tmp_path / "noshave"
    m = mo.month("tuning-07")
    ctl = AgentController(_NoShave(), Envelope(EnvelopeConfig()), Budget(2.0), prompt_version=8)
    run_session(CityLearnSimulator(control=True, schema=mo.month_schema(m, tmp_path / "data")), ctl, RunWriter(run),
                hours=95, log=lambda *_: None, sim_info={"kind": "citylearn", "control": True}, dataset=m.dataset)
    rows = ad.deviations(run)
    assert rows and {r["class"] for r in rows} <= {"shave_skipped", "discharge_off_plan"}
    published = json.loads((run / "result.json").read_text(encoding="utf-8"))["district_kpis"]
    control = ad._replay(("control", str(run), [], 8))
    assert all(control["kpis"][k] == published[k] for k in ad.KPI_KEYS)
    peaks = ap.peak_hours(control["grid_kwh"])
    assert len(control["grid_kwh"]["Building_1"]) == 95 and peaks["all_time"]["kwh"] == max(ap.district(control["grid_kwh"]))
    points = sorted({(r["step"], r["building"], r["device"]) for r in rows if r["class"] == "shave_skipped"})
    fixed = ad._replay(("shave_skipped", str(run), points, 8))
    assert fixed["kpis"] != control["kpis"]


# -- the version 9 acceptance rule -------------------------------------------------------------


def _k(**over):
    base = {"cost_total": 0.9087, "carbon_emissions_total": 0.9582, "discomfort_proportion": 0.0208,
            "discomfort_hot_proportion": 0.0059, "all_time_peak_average": 0.8797, "ramping_average": 0.9873,
            ts.OUTAGE: 0.1711}
    return base | over


@pytest.mark.parametrize("over, ok", [
    ({"all_time_peak_average": 0.8790, "ramping_average": 0.9870}, True),
    ({"all_time_peak_average": 0.8790, "ramping_average": 0.9870, "cost_total": 0.9087 + 0.001}, True),
    ({"all_time_peak_average": 0.8797, "ramping_average": 0.9870}, False),   # peak not lower
    ({"all_time_peak_average": 0.8790, "ramping_average": 0.9873}, False),   # ramping not lower
    ({"all_time_peak_average": 0.8790, "ramping_average": 0.9870, "cost_total": 0.9098}, False),
    ({"all_time_peak_average": 0.8790, "ramping_average": 0.9870, "carbon_emissions_total": 0.9593}, False),
    ({"all_time_peak_average": 0.8790, "ramping_average": 0.9870, "discomfort_proportion": 0.0219}, False),
    ({"all_time_peak_average": 0.8790, "ramping_average": 0.9870, "discomfort_hot_proportion": 0.0070}, False),
    ({"all_time_peak_average": 0.8790, "ramping_average": 0.9870, ts.OUTAGE: 0.171101}, False),
    ({"all_time_peak_average": 0.8790, "ramping_average": 0.9870, ts.OUTAGE: 0.1700}, True),
])
def test_acceptance_rule_as_written_in_the_changelog(over, ok):
    assert ts.accepts_v9(_k(**over), _k()) is ok


def test_pick_takes_the_lowest_peak_plus_ramping_then_the_lower_cost_and_none_without_a_pass():
    rows = [{"params": {"n": 1}, "accepted": True, "kpis": _k(all_time_peak_average=0.87, ramping_average=0.985)},
            {"params": {"n": 2}, "accepted": True, "kpis": _k(all_time_peak_average=0.86, ramping_average=0.99,
                                                              cost_total=0.9090)},
            {"params": {"n": 3}, "accepted": True, "kpis": _k(all_time_peak_average=0.86, ramping_average=0.99)},
            {"params": {"n": 4}, "accepted": False, "kpis": _k(all_time_peak_average=0.80, ramping_average=0.90)}]
    assert ts.pick_v9(rows)["params"] == {"n": 3}
    assert ts.pick_v9([dict(r, accepted=False) for r in rows]) is None


def test_the_v9_grid_starts_from_v8_and_the_shipped_numbers_are_in_it():
    grid = ts.grid_v9()
    assert len(grid) == 44 and grid[0] == asdict(StrategyParamsV8())
    assert asdict(StrategyParamsV9()) in grid
    assert all(set(c) == set(asdict(StrategyParamsV8())) for c in grid)
