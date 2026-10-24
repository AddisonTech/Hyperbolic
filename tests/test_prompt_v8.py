"""Prompt version 8 (0.10.0): the strategy's whole action per building, the warm-room cooling, version 7
still selectable, and the 0.9.0 envelope and live month unchanged."""

import json
from pathlib import Path

import pytest
from conftest import BUILDINGS, needs_citylearn
from fakes import FakeDistrict

from hyperbolic.envelope import Envelope, EnvelopeConfig, parse_reply
from hyperbolic.model import (
    NIGHT_END_TRIM,
    WARM_NOTE,
    Budget,
    ScriptedSupervisor,
    StrategyParamsV8,
    night_now,
    strategy_plan_v7,
    strategy_plan_v8,
)
from hyperbolic.prompt import PROMPT_VERSION, PROMPT_VERSIONS, Lookahead, build_request, observe, system_prompt_v7, system_prompt_v8
from hyperbolic.runner import AgentController, RunWriter, context_from_state, load_jsonl, replay_run, run_session
from hyperbolic.signals import PeakTracker, PriceOutlook

LIVE_090 = (Path(__file__).parents[1] / "runs" / "live"
            / "citylearn_challenge_2023_phase_2_local_evaluation_agent_citylearn_20261023T135430Z")


def _obs(version=8, n=40):
    """An observation late in the second day of the fake district, so every outlook is filled."""
    sim = FakeDistrict()
    st = sim.start(n + 3)
    look, peaks = Lookahead(), PeakTracker()
    for _ in range(n):
        look.update(st)
        peaks.update(st)
        prev = st
        _, st = sim.step(None)
    t = prev["time_step"]
    ctx = context_from_state(prev, peaks.info(t), PriceOutlook(prev["shared"]["price_forecast"][0],
                                                              tuple(look.outlook(t)["price"])))
    env = Envelope(EnvelopeConfig())
    return prev, ctx, look, env, observe(version, prev, ctx, None, look, env)


def _warm(obs, b="Building_1", gap=2.0, **over):
    """Make building b an occupied room gap C above its setpoint, with no trim held."""
    s = obs["buildings"][b]
    s.update({"occupied": True, "indoor_vs_setpoint_c": gap, "power_outage": False, "cooling_range": [0.3, 0.45],
              "trim": {"depth": 0.0, "state": "end", "end_trim_ok": False, "why": "at or above setpoint"}})
    s["baseline_action"]["cooling"] = 0.3
    s.update(over)
    return obs


# -- what each building sees ----------------------------------------------------------


def test_v7_and_v8_stay_selectable():
    assert PROMPT_VERSION == 9 and PROMPT_VERSIONS[-3:] == (7, 8, 9)
    st, ctx, look, env, v8 = _obs()
    v7 = observe(7, st, ctx, None, look, env)
    assert "strategy_battery" in v7["buildings"]["Building_1"] and "signal_outlook" in v7


def test_v8_observation_carries_the_strategys_whole_action_per_building():
    st, ctx, look, env, v8 = _obs()
    v7 = observe(7, st, ctx, None, look, env)
    assert set(v8) == set(v7) - {"strategy_battery_reason", "signal_outlook"} | {"strategy_reason"}
    plan = strategy_plan_v8(v8)
    assert v8["strategy_reason"] == plan["reason"]
    for b in BUILDINGS:
        got = v8["buildings"][b]
        assert set(got) == set(v7["buildings"][b]) - {"strategy_battery"} | {"strategy"}
        assert got["strategy"] == {d: plan[b][d] for d in ("cooling", "dhw", "battery")}
        # The battery is version 7's strategy_battery, and every value is inside the envelope's ranges.
        assert got["strategy"]["battery"] == v7["buildings"][b]["strategy_battery"]
        lo, hi = got["battery_range"]
        assert lo <= got["strategy"]["battery"] <= hi and got["strategy"]["dhw"] == 0.0
        c = got["strategy"]["cooling"]
        assert c is None or got["cooling_range"][0] <= c <= got["cooling_range"][1]


def test_v8_system_prompt_says_send_the_strategy_and_states_the_warm_room_rule():
    cfg = EnvelopeConfig()
    text = system_prompt_v8(cfg, BUILDINGS)
    p = StrategyParamsV8()
    for phrase in ("strategy in each building", "Send it as given", "That starts a trim when state is off",
                   "never null", "running warm", f"from 0 at {p.warm_margin_c:g} C", f"to {p.warm_boost:g} at "
                   f"{p.warm_margin_c + p.warm_ramp_c:g} C or more above", "too cool or too warm",
                   "Leave the hot water tank at 0", "end_trim_ok"):
        assert phrase in text, phrase
    # The version 7 line the 0.9.0 live month read as "send null when the trim is off" is gone.
    assert "use it only when trim state is off or end" in system_prompt_v7(cfg, BUILDINGS)
    assert "use it only when trim state is off or end" not in text
    assert chr(0x2014) not in text and "strategy_battery" not in text and "signal_outlook" not in text
    assert "local evaluation" not in text  # the same prompt serves every month of the month set


def test_v8_request_is_smaller_than_v7_with_the_same_reply_schema():
    st, ctx, look, env, v8 = _obs()
    v7 = observe(7, st, ctx, None, look, env)
    r7 = build_request(v7, env.config, BUILDINGS, "haiku", prompt_version=7)
    r8 = build_request(v8, env.config, BUILDINGS, "haiku", prompt_version=8)
    assert r8["output_config"] == r7["output_config"]
    assert len(r8["system"]) < 0.8 * len(r7["system"])
    assert len(json.dumps(r8)) < 0.92 * len(json.dumps(r7))


# -- the version 8 strategy --------------------------------------------------------------


def test_warm_room_gets_extra_cooling_ramping_in_above_the_margin():
    p = StrategyParamsV8()
    *_, obs = _obs()
    for gap, boost in ((p.warm_margin_c - 0.1, 0.0), (p.warm_margin_c + p.warm_ramp_c / 2, p.warm_boost / 2),
                       (p.warm_margin_c + p.warm_ramp_c + 0.5, p.warm_boost)):
        reply = strategy_plan_v8(_warm(json.loads(json.dumps(obs)), gap=gap))
        got = reply["Building_1"]["cooling"]
        if boost == 0.0:
            assert got is None
        else:
            assert got == pytest.approx(0.3 + boost - 0.001, abs=0.0015) and WARM_NOTE in reply["reason"]


@pytest.mark.parametrize("over", [{"power_outage": True}, {"occupied": False}, {"cooling_range": None},
                                  {"trim": {"depth": 0.05, "state": "hold", "end_trim_ok": True, "min_depth": 0.05}},
                                  {"cooling_range": [0.3, 0.3]}])
def test_no_extra_cooling_in_an_outage_an_empty_room_a_held_trim_or_outside_the_range(over):
    *_, obs = _obs()
    reply = strategy_plan_v8(_warm(obs, gap=3.0, **over))
    assert reply["Building_1"]["cooling"] != pytest.approx(0.349, abs=0.002)
    if "trim" not in over:
        assert reply["Building_1"]["cooling"] is None


def test_without_a_warm_room_v8_is_the_version_7_strategy():
    for n in (20, 30, 40, 45):
        *_, obs = _obs(n=n)
        for b in BUILDINGS:
            obs["buildings"][b]["indoor_vs_setpoint_c"] = min(obs["buildings"][b]["indoor_vs_setpoint_c"], 0.5)
        assert strategy_plan_v8(obs) == strategy_plan_v7(obs)


def test_the_night_rule_is_off_and_when_on_ends_a_held_trim():
    assert StrategyParamsV8().night_from_hour == 0 and not night_now(23, StrategyParamsV8())
    night = StrategyParamsV8(night_from_hour=22, night_until_hour=6)
    assert night_now(23, night) and night_now(2, night) and not night_now(6, night) and not night_now(21, night)
    *_, obs = _obs()
    obs["hour"] = 23
    obs["buildings"]["Building_1"]["trim"] = {"depth": 0.05, "state": "hold", "end_trim_ok": True, "min_depth": 0.05}
    reply = strategy_plan_v8(obs, night)
    assert reply["Building_1"]["cooling"] is None and reply["Building_1"]["end_trim"] == NIGHT_END_TRIM


def test_scripted_v8_reply_is_the_strategy_the_observation_shows():
    st, ctx, look, env, obs = _obs()
    req = build_request(obs, env.config, BUILDINGS, "haiku", prompt_version=8)
    p, err = parse_reply(ScriptedSupervisor().call(5, req).text, BUILDINGS, end_trim=True)
    assert err is None and p["end_trim"] == {}
    for b in BUILDINGS:
        assert p["buildings"][b] == obs["buildings"][b]["strategy"]


def test_v8_run_on_the_fake_district_is_clean_and_replays(tmp_path):
    run = tmp_path / "v8"
    ctl = AgentController(ScriptedSupervisor(), Envelope(EnvelopeConfig()), Budget(2.0), prompt_version=8)
    res = run_session(FakeDistrict(), ctl, RunWriter(run), hours=48, log=lambda *_: None)
    assert res["fallback_steps"] == 0 and res["clamped_steps"] == 0 and ctl.describe()["prompt_version"] == 8
    rep = replay_run(run)
    assert rep.deterministic and rep.identical_steps == 48


@needs_citylearn
def test_v8_dry_run_and_replay(tmp_path):
    """24 hours of the scripted version 8 strategy on CityLearn, through the 0.9.0 rules, and replay."""
    from hyperbolic.runner import controller_settings
    from hyperbolic.sim import CityLearnSimulator

    version, cfg = controller_settings(rule_based=True, prompt_version=8)
    assert cfg == EnvelopeConfig()
    ctl = AgentController(ScriptedSupervisor(), Envelope(cfg), Budget(2.0), prompt_version=version)
    run_dir = tmp_path / "v8"
    res = run_session(CityLearnSimulator(control=True), ctl, RunWriter(run_dir), hours=24, log=lambda *_: None,
                      sim_info={"kind": "citylearn", "control": True})
    assert res["steps"] == 24 and res["fallback_steps"] == 0
    calls = load_jsonl(run_dir / "calls.jsonl")
    assert '"strategy":' in calls[5]["request"]["messages"][0]["content"]
    rep = replay_run(run_dir)
    assert rep.deterministic and rep.api_calls == 0 and rep.identical_steps == 24


# -- the envelope and the 0.9.0 live month are unchanged ------------------------------------


@pytest.mark.skipif(not LIVE_090.exists(), reason="the 0.9.0 live run is kept locally in runs/live")
def test_the_0_9_0_live_month_still_replays_hour_for_hour():
    m = json.loads((LIVE_090 / "manifest.json").read_text(encoding="utf-8"))
    assert EnvelopeConfig.from_manifest(m["envelope"]) == EnvelopeConfig()
    assert m["supervisor"]["prompt_version"] == 7
    rep = replay_run(LIVE_090)
    assert rep.deterministic and rep.identical_steps == 719 and rep.api_calls == 0 and rep.clamped_steps == 27


@needs_citylearn
def test_v8_strategy_full_month_fixes_the_hot_side_and_keeps_outage_energy():
    """The scripted version 8 month: fewer too-warm hours than the baseline (0.0176) where version 7
    had more (0.0181), unserved energy in outages at the baseline's, clamps only where no reply can
    avoid them."""
    from hyperbolic import district as dc
    from hyperbolic.runner import NullWriter
    from hyperbolic.sim import CityLearnSimulator

    ctl = AgentController(ScriptedSupervisor(), Envelope(EnvelopeConfig()), Budget(2.0), prompt_version=8)
    w = NullWriter()
    res = run_session(CityLearnSimulator(control=True), ctl, w, hours=dc.EPISODE_HOURS, log=lambda *_: None)
    k = res["district_kpis"]
    assert res["complete"] and res["fallback_steps"] == 0 and res["clamped_steps"] <= 30
    assert k["discomfort_hot_proportion"] < 0.0176 and k["discomfort_proportion"] < 0.0430
    assert abs(k["power_outage_normalized_unserved_energy_total"] - 0.6844) < 5e-5
    assert k["cost_total"] < 0.905 and k["ramping_average"] < 1.0
    for s in w.steps:
        for c in s["decision"]["clamps"]:
            assert c["rule"] == "peak" or (c["rule"] == "trim_hold" and c["requested"] == c["applied"] == 0.0), c
