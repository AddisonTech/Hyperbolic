"""Prompt version 7 (0.9.0): what the envelope allows each building this hour, the version 7 battery
plan, and the envelope left exactly as it was in 0.8.0."""

import json
import random
from dataclasses import replace
from pathlib import Path

import pytest
from conftest import BUILDINGS, bstate, needs_citylearn, proposal
from fakes import FakeDistrict

from hyperbolic import district as dc
from hyperbolic.envelope import Clamp, Decision, Envelope, EnvelopeConfig, StepContext, parse_reply
from hyperbolic.model import (
    Budget,
    ScriptedSupervisor,
    StrategyParamsV7,
    battery_plan_v5,
    battery_plan_v7,
    strategy_plan_v7,
)
from hyperbolic.prompt import (
    Lookahead,
    battery_range,
    build_request,
    cooling_range,
    observe,
    system_prompt_v6,
    system_prompt_v7,
    trim_view,
)
from hyperbolic.runner import (
    AgentController,
    NullWriter,
    RunWriter,
    context_from_state,
    load_jsonl,
    replay_run,
    run_session,
)
from hyperbolic.signals import PeakTracker, PriceOutlook

COLD, NEAR, AT = 22.5, 23.7, 24.0  # indoor C against a 24.0 C setpoint
LIVE_080 = (Path(__file__).parents[1] / "runs" / "live"
            / "citylearn_challenge_2023_phase_2_local_evaluation_agent_citylearn_20261022T222703Z")

# Every EnvelopeConfig field as 0.8.0 shipped it (the 0.8.0 live run's manifest records the same).
ENVELOPE_080 = {
    "cooling_min": 0.0, "cooling_max": 1.0, "storage_min": -1.0, "storage_max": 1.0,
    "cooling_rate_per_step": 0.35, "dhw_rate_per_step": 0.5, "battery_rate_per_step": 0.5,
    "soc_min": 0.1, "soc_max": 0.95, "comfort_band_k": 2.0, "comfort_margin_k": 0.5,
    "cooling_max_deviation": 0.15, "overcool_guard_unoccupied": True, "peak_limit": True,
    "peak_target_fraction": 1.0, "peak_forecast_days": 2, "spread_check": True,
    "trim_hold": True, "trim_hold_c": 0.5, "trim_release_step": 0.02, "trim_min_depth": 0.002,
}


def _obs(version=7, n=40, envelope=None, last=None):
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
    env = envelope or Envelope(EnvelopeConfig())
    return prev, ctx, look, env, observe(version, prev, ctx, last, look, env)


def _held(depth=0.08, **b1):
    """An envelope holding a Building_1 trim of depth, and this hour's context."""
    env = Envelope(EnvelopeConfig())
    env.holds = {"Building_1": depth}
    env.memory = {"Building_1.cooling": 0.4 - depth}
    ctx = StepContext(time_step=10, buildings={b: bstate(**(b1 if b == "Building_1" else {})) for b in BUILDINGS})
    return env, ctx


# -- the envelope is unchanged ------------------------------------------------------


def test_envelope_config_defaults_match_0_8_0_exactly():
    assert EnvelopeConfig().as_dict() == ENVELOPE_080
    assert EnvelopeConfig.v070().as_dict() == {**ENVELOPE_080, "trim_hold": False}
    assert EnvelopeConfig.v040().as_dict() == {**ENVELOPE_080, "trim_hold": False, "spread_check": False}


@pytest.mark.skipif(not LIVE_080.exists(), reason="the 0.8.0 live run is kept locally in runs/live")
def test_the_0_8_0_live_month_still_replays_hour_for_hour():
    m = json.loads((LIVE_080 / "manifest.json").read_text(encoding="utf-8"))
    assert EnvelopeConfig.from_manifest(m["envelope"]) == EnvelopeConfig()
    rep = replay_run(LIVE_080)
    assert rep.deterministic and rep.identical_steps == 719 and rep.api_calls == 0 and rep.clamped_steps == 312


# -- what each building sees ----------------------------------------------------------


def test_v7_observation_shows_the_envelope_view_per_building():
    st, ctx, look, env, v7 = _obs()
    v6 = observe(6, st, ctx, None, look, env)
    assert "last_clamps" not in v7 and "reference_reason" not in v7
    assert set(v7) == set(v6) - {"last_clamps"}
    for b in BUILDINGS:
        got = set(v7["buildings"][b])
        assert {"trim", "cooling_range", "battery_range", "strategy_battery"} <= got
        assert not got & {"reference_action", "cooling_trim_last_hour", "cooling_trim_held", "last_clamp"}
        # Hour 17 in the fake district: occupied, the room at its setpoint, so no trim may run.
        assert v7["buildings"][b]["trim"] == {"depth": 0.0, "state": "end", "end_trim_ok": False,
                                              "why": "at or above setpoint"}
        assert v7["buildings"][b]["cooling_range"] == [0.3, 0.45]


def test_trim_view_states_min_depth_and_end_trim_ok():
    env, ctx = _held(indoor=COLD)
    assert trim_view(env, "Building_1", ctx.buildings["Building_1"]) == {
        "depth": 0.08, "state": "hold", "end_trim_ok": True, "why": "1.5 C below setpoint", "min_depth": 0.08}
    env, ctx = _held(indoor=NEAR)
    assert trim_view(env, "Building_1", ctx.buildings["Building_1"]) == {
        "depth": 0.08, "state": "ease", "end_trim_ok": True, "why": "within 0.5 C of setpoint", "min_depth": 0.06}
    for kw, why in (({"indoor": AT}, "at or above setpoint"), ({"indoor": COLD, "occupied": False}, "unoccupied"),
                    ({"indoor": COLD, "cooling_base": 0.0}, "no baseline cooling")):
        env, ctx = _held(**kw)
        assert trim_view(env, "Building_1", ctx.buildings["Building_1"]) == {
            "depth": 0.08, "state": "end", "end_trim_ok": False, "why": why}
    env = Envelope(EnvelopeConfig())
    assert trim_view(env, "Building_1", bstate(indoor=COLD)) == {"depth": 0.0, "state": "off", "end_trim_ok": False}


def test_cooling_range_is_the_held_trim_and_null_is_only_allowed_without_one():
    env, ctx = _held(indoor=COLD)
    assert cooling_range(env, "Building_1", ctx.buildings["Building_1"]) == [0.25, 0.32]
    env, ctx = _held(indoor=NEAR)
    assert cooling_range(env, "Building_1", ctx.buildings["Building_1"]) == [0.25, 0.34]
    env, ctx = _held(indoor=AT)
    assert cooling_range(env, "Building_1", ctx.buildings["Building_1"]) == [0.4, 0.55]
    # Unoccupied and cool: the overcool guard and the end of the hold leave only the exact baseline.
    env, ctx = _held(indoor=21.0, occupied=False)
    assert cooling_range(env, "Building_1", ctx.buildings["Building_1"]) == [0.4, 0.4]
    st = bstate(indoor=21.0, occupied=False, cooling_base=0.30731)
    assert cooling_range(Envelope(EnvelopeConfig()), "Building_1", st) is None


def test_battery_range_applies_rate_and_charge_limits():
    env = Envelope(EnvelopeConfig())
    assert battery_range(env, "Building_1", bstate(battery_soc=0.5)) == [-0.4, 0.45]
    env.memory = {"Building_1.battery": -0.3}
    assert battery_range(env, "Building_1", bstate(battery_soc=0.9)) == [-0.8, 0.05]
    assert battery_range(env, "Building_1", bstate(battery_soc=0.97)) == [-0.8, 0.0]


@pytest.mark.parametrize("seed", range(6))
def test_any_value_inside_the_ranges_passes_the_envelope_unclamped(seed):
    """The ranges are worked out read only from the envelope; a value inside them is never clamped,
    except where a held trim reaches below cooling 0, which no reply can avoid."""
    rng = random.Random(seed)
    for _ in range(300):
        cfg = EnvelopeConfig()
        env = Envelope(cfg)
        base = rng.choice([0.0, 0.05, 0.12, rng.uniform(0.0, 0.9)])
        depth = rng.choice([0.0, 0.0, rng.uniform(0.003, 0.15)])
        if depth:
            env.holds = {"Building_1": depth}
        env.memory = {"Building_1.cooling": min(1.0, max(0.0, base + rng.uniform(-0.5, 0.5))),
                      "Building_1.battery": rng.uniform(-0.8, 0.8)}
        st = bstate(indoor=24.0 + rng.uniform(-3.5, 2.5), occupied=rng.random() < 0.7, cooling_base=base,
                    battery_soc=rng.uniform(0.05, 1.0))
        ctx = StepContext(time_step=5, buildings={b: st if b == "Building_1" else bstate() for b in BUILDINGS})
        need, kind, _ = env.held_trim("Building_1", st)
        if kind in ("hold", "ease") and depth > cfg.trim_min_depth and base - need < 0:
            continue
        cr, br = cooling_range(env, "Building_1", st), battery_range(env, "Building_1", st)
        for _ in range(4):
            cool = None if cr is None else round(rng.uniform(*cr), 4)
            bat = round(rng.uniform(*br), 4)
            trial = Envelope(cfg)
            trial.holds, trial.memory = dict(env.holds), dict(env.memory)
            d = trial.apply(proposal(Building_1={"cooling": cool, "battery": bat}), ctx)
            assert not [c for c in d.clamps if c.point.startswith("Building_1")], (st, env.holds, cr, br, cool, bat)


def test_a_held_trim_left_to_null_is_clamped_and_the_top_of_the_range_is_not():
    env, ctx = _held(indoor=COLD)
    hi = cooling_range(env, "Building_1", ctx.buildings["Building_1"])[1]
    d = replace_env(env).apply(proposal(Building_1={"cooling": None}), ctx)
    assert [c.rule for c in d.clamps] == ["trim_hold"]
    d = replace_env(env).apply(proposal(Building_1={"cooling": hi}), ctx)
    assert not d.clamps and d.actions["Building_1"]["cooling"] == hi


def replace_env(env):
    e = Envelope(env.config)
    e.holds, e.memory = dict(env.holds), dict(env.memory)
    return e


def test_last_clamp_is_shown_on_its_building_with_its_reason():
    last = Decision(actions={b: {"cooling": None, "dhw": None, "battery": None} for b in BUILDINGS},
                    clamps=[Clamp("Building_2.cooling", "trim_hold", 0.3065, 0.2604, "trim held at 0.046")],
                    reason="t")
    *_, obs = _obs(last=last)
    assert obs["buildings"]["Building_2"]["last_clamp"] == "cooling trim_hold 0.3065 to 0.2604: trim held at 0.046"
    assert "last_clamp" not in obs["buildings"]["Building_1"] and "last_clamp" not in obs["buildings"]["Building_3"]


# -- the battery plan and guidance --------------------------------------------------


@pytest.mark.parametrize("n", [20, 30, 40, 45])
def test_shipped_battery_plan_is_version_5s_and_fits_battery_range(n):
    st, ctx, look, env, obs = _obs(n=n)
    plan, _ = battery_plan_v7(obs)
    v5, _ = battery_plan_v5(observe(5, st, ctx, None, look, env))
    assert plan == v5
    for b in BUILDINGS:
        lo, hi = obs["buildings"][b]["battery_range"]
        assert lo <= obs["buildings"][b]["strategy_battery"] <= hi
        assert obs["buildings"][b]["strategy_battery"] == min(max(plan[b], lo), hi)


def _battery_obs(last=-0.3, load=1.2, soc=0.6, top=False, solar=False):
    *_, obs = _obs(n=30)
    obs["price_plan"]["top_price_now"] = top
    obs["peak"]["district_load_now_kwh"] = 0.0  # no peak shaving
    for b in BUILDINGS:
        s = obs["buildings"][b]
        s["last_action"] = {"cooling": 0.3, "dhw": 0.0, "battery": last}
        s["load_now_kwh"] = -1.0 if solar else load
        s["battery"]["soc"] = soc
    return obs


def test_the_soft_cap_winds_a_discharge_down_and_leaves_spare_solar_alone():
    capped = StrategyParamsV7(rise_step=0.1)
    plan, why = battery_plan_v7(_battery_obs(), capped)
    assert all(v == pytest.approx(-0.2) for v in plan.values()) and why == "Wind a discharge down slowly"
    assert all(v > 0.1 for v in battery_plan_v7(_battery_obs())[0].values())  # shipped, no cap: -0.3 to a charge
    plan, _ = battery_plan_v7(_battery_obs(soc=0.1), capped)  # nothing left to discharge
    assert all(v == 0.0 for v in plan.values())
    plan, _ = battery_plan_v7(_battery_obs(last=0.0, solar=True), capped)  # storing spare solar is exempt
    assert all(v > 0.1 for v in plan.values())


def test_valley_filling_charges_only_up_to_the_higher_of_last_and_next_hour():
    obs = _battery_obs(last=0.0, load=0.6, soc=0.3)
    obs["price_plan"].update({"top_price_now": False, "top_price_hours_ahead": [3]})
    obs["peak"]["headroom_kwh"] = 10.0
    for b in BUILDINGS:
        obs["buildings"][b]["battery"]["grid_charging_ok"] = True
    sm = obs["smoothing"]
    sm.update({"district_load_now_kwh": 1.8, "district_draw_last_hour_kwh": 2.1, "district_load_next_hour_kwh": 1.5})
    free, _ = battery_plan_v7(obs, StrategyParamsV7())
    filled, _ = battery_plan_v7(obs, StrategyParamsV7(fill_valley=True))
    assert all(v == pytest.approx(0.15) for v in free.values())
    cap = obs["buildings"]["Building_1"]["battery"]["capacity_kwh"]
    assert sum(v * cap for v in filled.values()) <= 2.1 - 1.8 + 1e-6


def test_v7_system_prompt_states_the_ranges_the_trim_and_the_battery_guidance():
    cfg = EnvelopeConfig()
    text = system_prompt_v7(cfg, BUILDINGS)
    for phrase in ("cooling_range and battery_range", "Stay inside them and nothing is clamped",
                   "cooling_range null", "min_depth", "end_trim_ok", "last_clamp",
                   "null is exactly baseline_action: use it only when trim state is off or end",
                   "send it as given", "stay within 0.1 of", "never skip a peak-shaving discharge",
                   "at most 0.02 per hour", "more than 0.5 C below its setpoint"):
        assert phrase in text, phrase
    assert "Raise a battery action" not in text  # the shipped plan has no cap, so the prompt states none
    assert chr(0x2014) not in text and "reference_action" not in text


def test_v7_request_is_no_larger_than_v6():
    st, ctx, look, env, v7 = _obs()
    v6 = observe(6, st, ctx, None, look, env)
    r6 = build_request(v6, env.config, BUILDINGS, "haiku", prompt_version=6)
    r7 = build_request(v7, env.config, BUILDINGS, "haiku", prompt_version=7)
    assert r7["output_config"] == r6["output_config"]  # same reply schema, end_trim included
    assert len(r7["system"]) < len(system_prompt_v6(env.config, BUILDINGS))
    assert len(json.dumps(r7)) < 1.02 * len(json.dumps(r6))


# -- the scripted version 7 strategy ---------------------------------------------------


def test_scripted_v7_reply_stays_inside_the_ranges_and_never_leaves_a_held_trim_to_null():
    env, ctx = _held(indoor=COLD)
    st, _, look, _, obs = _obs(envelope=env)
    obs["buildings"]["Building_1"].update({"trim": {"depth": 0.08, "state": "hold", "end_trim_ok": True,
                                                    "why": "1.5 C below setpoint", "min_depth": 0.08},
                                           "cooling_range": [0.15, 0.22], "occupied": True,
                                           "indoor_vs_setpoint_c": -0.3})
    obs["buildings"]["Building_1"]["baseline_action"]["cooling"] = 0.3
    reply = strategy_plan_v7(obs)
    assert reply["Building_1"]["cooling"] == 0.22
    for b in BUILDINGS:
        lo, hi = obs["buildings"][b]["battery_range"]
        assert lo <= reply[b]["battery"] <= hi and reply[b]["end_trim"] is None and reply[b]["dhw"] == 0.0
    req = build_request(obs, env.config, BUILDINGS, "haiku", prompt_version=7)
    p, err = parse_reply(ScriptedSupervisor().call(5, req).text, BUILDINGS, end_trim=True)
    assert err is None and p["end_trim"] == {}


def test_v7_run_on_the_fake_district_is_clean_and_replays(tmp_path):
    run = tmp_path / "v7"
    ctl = AgentController(ScriptedSupervisor(), Envelope(EnvelopeConfig()), Budget(2.0), prompt_version=7)
    res = run_session(FakeDistrict(), ctl, RunWriter(run), hours=48, log=lambda *_: None)
    assert res["fallback_steps"] == 0 and res["clamped_steps"] == 0 and ctl.describe()["prompt_version"] == 7
    rep = replay_run(run)
    assert rep.deterministic and rep.identical_steps == 48


@needs_citylearn
def test_v7_dry_run_and_replay(tmp_path):
    """24 hours of the scripted version 7 strategy on CityLearn, through the 0.8.0 rules, and replay."""
    from hyperbolic.runner import controller_settings
    from hyperbolic.sim import CityLearnSimulator

    version, cfg = controller_settings(rule_based=True, prompt_version=7)
    assert cfg == EnvelopeConfig()
    ctl = AgentController(ScriptedSupervisor(), Envelope(cfg), Budget(2.0), prompt_version=version)
    run_dir = tmp_path / "v7"
    res = run_session(CityLearnSimulator(control=True), ctl, RunWriter(run_dir), hours=24, log=lambda *_: None,
                      sim_info={"kind": "citylearn", "control": True})
    assert res["steps"] == 24 and res["fallback_steps"] == 0
    calls = load_jsonl(run_dir / "calls.jsonl")
    assert "cooling_range" in calls[5]["request"]["system"]
    rep = replay_run(run_dir)
    assert rep.deterministic and rep.api_calls == 0 and rep.identical_steps == 24


@needs_citylearn
def test_v7_strategy_full_month_cuts_clamps_and_keeps_the_v6_month():
    """The scripted version 7 month: the version 6 strategy's KPIs (139 clamped hours in 0.8.0), with
    clamps only where no reply can avoid them."""
    from hyperbolic.sim import CityLearnSimulator

    ctl = AgentController(ScriptedSupervisor(), Envelope(EnvelopeConfig()), Budget(2.0), prompt_version=7)
    w = NullWriter()
    res = run_session(CityLearnSimulator(control=True), ctl, w, hours=dc.EPISODE_HOURS, log=lambda *_: None)
    k = res["district_kpis"]
    assert res["complete"] and res["fallback_steps"] == 0 and res["clamped_steps"] <= 30
    assert k["ramping_average"] < 0.9957 and abs(k["cost_total"] - 0.9017) < 0.0005
    assert abs(k["discomfort_proportion"] - 0.0430) < 0.0005 and k["all_time_peak_average"] < 0.9593 + 5e-5
    for s in w.steps:
        for c in s["decision"]["clamps"]:
            assert c["rule"] == "peak" or (c["rule"] == "trim_hold" and c["requested"] == c["applied"] == 0.0), c
