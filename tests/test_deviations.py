"""scripts/analyze_deviations.py (0.10.0): the deviation classes, when they happen, and the attribution
replays that put one class at a time back to the strategy."""

import json
import sys
from pathlib import Path

import pytest
from conftest import BUILDINGS, needs_citylearn
from test_prompt_v8 import _obs

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

import analyze_deviations as ad  # noqa: E402

from hyperbolic.envelope import Envelope, EnvelopeConfig  # noqa: E402
from hyperbolic.model import Budget, CallResult, ScriptedSupervisor, observation_from_request, strategy_plan_v7  # noqa: E402
from hyperbolic.prompt import build_request  # noqa: E402
from hyperbolic.runner import AgentController, RunWriter, run_session  # noqa: E402


def _v7(n=40):
    *_, obs = _obs(version=7, n=n)
    return obs


def _cold(obs, b="Building_1", state="off"):
    """Building b occupied and 1.2 C below its setpoint, where the strategy trims."""
    s = obs["buildings"][b]
    s.update({"occupied": True, "indoor_vs_setpoint_c": -1.2, "cooling_range": [0.15, 0.45],
              "trim": {"depth": 0.0, "state": state, "end_trim_ok": False}})
    s["baseline_action"]["cooling"] = 0.3
    return obs


def _reply(plan, changes):
    """The strategy's reply with {(building, device): value} changes."""
    out = json.loads(json.dumps(plan))
    for (b, d), v in changes.items():
        out[b][d] = v
    return out


def test_the_strategys_own_reply_has_no_deviation():
    obs = _cold(_v7())
    assert ad.classify(obs, strategy_plan_v7(obs)) == []


def test_cooling_classes():
    obs = _cold(_v7())
    plan = strategy_plan_v7(obs)
    trim = plan["Building_1"]["cooling"]
    assert trim is not None and trim < 0.3 - ad.COOLING_TOL
    assert ad.classify(obs, _reply(plan, {("Building_1", "cooling"): None})) == [("Building_1", "trim_not_started")]
    for cls, value in (("trim_shallower", round(trim + 0.02, 3)), ("trim_deeper", round(trim - 0.02, 3))):
        assert ad.classify(obs, _reply(plan, {("Building_1", "cooling"): value})) == [("Building_1", cls)]
    # The same missed trim while the envelope already holds one is a shallower trim, not a missed start.
    held = _cold(_v7(), state="hold")
    assert ad.classify(held, _reply(strategy_plan_v7(held), {("Building_1", "cooling"): 0.3})) == [
        ("Building_1", "trim_shallower")]
    # Where the strategy keeps the baseline: a trim it does not want, and cooling above it.
    warm = _v7()
    plan = strategy_plan_v7(warm)
    assert plan["Building_2"]["cooling"] is None
    assert ad.classify(warm, _reply(plan, {("Building_2", "cooling"): 0.25})) == [("Building_2", "trim_unwanted")]
    assert ad.classify(warm, _reply(plan, {("Building_2", "cooling"): 0.35})) == [("Building_2", "extra_cooling")]
    assert ad.classify(warm, _reply(plan, {("Building_2", "end_trim"): "warm"})) == [("Building_2", "trim_ended_early")]


@pytest.mark.parametrize("mode, setup, value, cls", [
    ("top", {"top_price_now": True}, 0.0, "top_discharge_short"),
    ("top", {"top_price_now": True}, -0.8, "top_discharge_over"),
    ("shave", {"shave": True}, 0.0, "shave_skipped"),
    ("idle", {}, 0.2, "charge_off_plan"),
    ("idle", {}, -0.2, "discharge_off_plan"),
])
def test_battery_classes(mode, setup, value, cls):
    obs = _v7()
    obs["price_plan"]["top_price_now"] = setup.get("top_price_now", False)
    obs["peak"]["district_load_now_kwh"] = 100.0 if setup.get("shave") else 0.0
    obs["peak"]["forecast_today_kwh"] = 10.0
    for b in BUILDINGS:
        obs["buildings"][b]["load_now_kwh"] = 1.2
        obs["buildings"][b]["battery"]["soc"] = 0.6
        obs["buildings"][b]["battery_range"] = [-0.8, 0.3]
    plan = strategy_plan_v7(obs)
    assert ad.battery_mode(obs, "Building_1", plan["Building_1"]["battery"]) == mode
    assert ad.classify(obs, _reply(plan, {("Building_1", "battery"): value})) == [("Building_1", cls)]


def test_charge_classes_and_the_tank():
    obs = _v7()
    obs["price_plan"]["top_price_now"] = False
    obs["peak"]["district_load_now_kwh"] = 0.0
    obs["buildings"]["Building_1"]["load_now_kwh"] = 1.2
    plan = strategy_plan_v7(obs)
    plan["Building_1"]["battery"] = 0.15  # as if the strategy were charging from the grid this hour
    assert ad.battery_mode(obs, "Building_1", 0.15) == "charge"
    assert ad.classify(obs, _reply(plan, {("Building_1", "battery"): 0.0}), plan) == [("Building_1", "charge_skipped")]
    assert ad.classify(obs, _reply(plan, {("Building_1", "battery"): 0.3}), plan) == [("Building_1", "charge_over")]
    assert ad.classify(obs, _reply(strategy_plan_v7(obs), {("Building_3", "dhw"): 0.2})) == [("Building_3", "dhw_used")]
    # Inside the tolerance is the strategy's value.
    near = strategy_plan_v7(obs)
    assert ad.classify(obs, _reply(near, {("Building_3", "battery"): near["Building_3"]["battery"] + 0.004})) == []


def test_context_bins_say_when_it_happened():
    obs = _cold(_v7())
    obs["outdoor_c"] = 31.0
    obs["buildings"]["Building_1"]["battery"]["soc"] = 0.95
    c = ad.context(obs, "Building_1")
    assert c == {"price": c["price"], "occupied": "occupied", "outdoor_c": ">=30", "soc": ">=0.9",
                 "room": "-1.5 to -1", "building": "Building_1"}
    assert c["price"] in ("flat", "top", "low", "mid")


def test_summary_counts_hours_and_splits():
    rows = [{"step": s, "building": b, "class": "trim_not_started", "device": "cooling", "model": 0.3,
             "strategy": 0.25, "price": "low", "occupied": "occupied", "outdoor_c": ">=30", "soc": "<0.3",
             "room": "<-1.5"} for s, b in ((1, "Building_1"), (1, "Building_3"), (2, "Building_1"))]
    got = ad.summary(rows)["trim_not_started"]
    assert got["count"] == 3 and got["hours"] == 2 and got["mean_gap"] == 0.05
    assert got["building"] == {"Building_1": 2, "Building_3": 1} and got["price"] == {"low": 3}


def test_shares_measure_each_replay_against_the_gap():
    k = lambda cost, disc: {key: 0.5 for key in ad.KPI_KEYS} | {"cost_total": cost, "discomfort_proportion": disc}  # noqa: E731
    results = {"control": {"kpis": k(0.92, 0.09)}, "strategy": {"kpis": k(0.90, 0.04)},
               "a": {"kpis": k(0.91, 0.04)}, "v8 cooling": {"kpis": k(0.0, 0.0)}}
    sh = ad.shares(results)
    assert set(sh) == {"a"}
    assert sh["a"]["cost_total"] == pytest.approx(0.5) and sh["a"]["discomfort_proportion"] == pytest.approx(1.0)
    assert sh["a"]["ramping_average"] is None  # no gap to explain


class _Recorded:
    """Writes a calls.jsonl with one reply per hour."""

    @staticmethod
    def write(path: Path, replies: dict[int, dict]) -> None:
        with path.open("w", encoding="utf-8") as f:
            for step, reply in replies.items():
                f.write(json.dumps({"step": step, "request_sha256": "x", "request": {},
                                    "reply": {"text": json.dumps(reply)}, "cost_usd": 0.0}) + "\n")


def test_replacing_supervisor_swaps_only_the_listed_points(tmp_path):
    *_, env, obs = _obs(version=7)
    _cold(obs)
    req = build_request(obs, env.config, BUILDINGS, "haiku", prompt_version=7)
    plan = strategy_plan_v7(observation_from_request(req))
    mine = _reply(plan, {("Building_1", "cooling"): None, ("Building_2", "battery"): 0.0,
                           ("Building_1", "end_trim"): "because"})
    calls = tmp_path / "calls.jsonl"
    _Recorded.write(calls, {0: mine, 1: mine})
    sup = ad.ReplacingSupervisor(calls, "haiku", {(0, "Building_1", "cooling")})
    got = json.loads(sup.call(0, req).text)
    assert got["Building_1"]["cooling"] == plan["Building_1"]["cooling"] and got["Building_1"]["end_trim"] is None
    assert got["Building_2"]["battery"] == 0.0  # not listed, left as recorded
    assert json.loads(sup.call(1, req).text) == mine  # another hour, untouched
    v8 = ad.ReplacingSupervisor(calls, "haiku", {(0, "Building_1", "cooling")}, plan=8)
    assert v8.plan is ad.PLANS[8]
    assert isinstance(sup.call(5, req), CallResult) and sup.call(5, req).text is None


def _skip_trim_starts(obs: dict) -> dict:
    """The version 7 strategy, except that it never starts a cooling trim."""
    reply = strategy_plan_v7(obs)
    for b, s in obs["buildings"].items():
        if s["trim"]["state"] == "off":
            reply[b]["cooling"] = None
    return reply


class _NoStarts(ScriptedSupervisor):
    def call(self, step: int, request: dict) -> CallResult:
        return CallResult(json.dumps(_skip_trim_starts(observation_from_request(request))), stop_reason="end_turn",
                          model="scripted")


@needs_citylearn
def test_deviations_and_attribution_on_a_recorded_citylearn_run(tmp_path):
    """A 47 hour version 7 run that never starts a trim: its departures are missed trim starts, the
    control replay reproduces it exactly, and putting that class back changes the month."""
    from hyperbolic.sim import CityLearnSimulator

    run = tmp_path / "nostarts"
    ctl = AgentController(_NoStarts(), Envelope(EnvelopeConfig()), Budget(2.0), prompt_version=7)
    run_session(CityLearnSimulator(control=True), ctl, RunWriter(run), hours=47, log=lambda *_: None,
                sim_info={"kind": "citylearn", "control": True})
    rows = ad.deviations(run)
    assert rows and {r["class"] for r in rows} == {"trim_not_started"}
    published = json.loads((run / "result.json").read_text(encoding="utf-8"))["district_kpis"]
    control = ad._replay(("control", str(run), [], 7))
    assert all(control["kpis"][k] == published[k] for k in ad.KPI_KEYS)
    points = sorted({(r["step"], r["building"], r["device"]) for r in rows})
    fixed = ad._replay(("trim_not_started", str(run), points, 7))
    strategy = ad._replay(("strategy", str(run), [], 7))
    assert fixed["kpis"] != control["kpis"]
    assert abs(fixed["kpis"]["discomfort_proportion"] - strategy["kpis"]["discomfort_proportion"]) <= abs(
        control["kpis"]["discomfort_proportion"] - strategy["kpis"]["discomfort_proportion"])
