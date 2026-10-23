"""Prompt versions, the 24 hour outlook and forecast horizons."""

import json

import pytest
from conftest import needs_citylearn
from fakes import FakeDistrict

from hyperbolic import district as dc
from hyperbolic.envelope import Envelope, EnvelopeConfig
from hyperbolic.model import Budget, ScriptedSupervisor, observation_from_request
from hyperbolic.prompt import (
    PROMPT_VERSION,
    Lookahead,
    build_observation,
    build_observation_v2,
    build_request,
    observe,
    system_prompt_v2,
)
from hyperbolic.runner import AgentController, NullWriter, context_from_state, controller_settings, run_session


def fake_states(n):
    sim = FakeDistrict()
    st = sim.start(n)
    out = []
    while st is not None:
        out.append(st)
        _, st = sim.step(None)
    return out


def test_default_prompt_is_version_7_and_the_rule_based_controller_stays_on_3():
    assert PROMPT_VERSION == 7
    assert AgentController(ScriptedSupervisor(), Envelope(), Budget(1.0)).describe()["prompt_version"] == 7
    # The rule-based controller is the frozen 0.4.0 reference: prompt version 3, no spread check.
    assert controller_settings(True) == (3, EnvelopeConfig.v040())
    assert controller_settings(False) == (7, EnvelopeConfig())
    # Versions before 6 keep the 0.7.0 rules; versions 6 and 7 run the 0.8.0 rules with the trim hold.
    assert controller_settings(True, 4) == (4, EnvelopeConfig.v070())
    assert controller_settings(True, 5) == (5, EnvelopeConfig.v070())
    assert controller_settings(False, 5) == (5, EnvelopeConfig.v070())
    assert controller_settings(True, 6) == (6, EnvelopeConfig())
    assert controller_settings(True, 7) == (7, EnvelopeConfig()) == controller_settings(False, 7)
    assert EnvelopeConfig.v040().spread_check is False and EnvelopeConfig().spread_check is True
    assert EnvelopeConfig().trim_hold is True
    assert EnvelopeConfig.v070().trim_hold is False and EnvelopeConfig.v040().trim_hold is False


def test_lookahead_places_forecasts_at_their_real_horizons():
    look = Lookahead()
    st = fake_states(1)[0]
    st["shared"]["price_forecast"] = [0.1, 0.6, 0.12, 0.24]
    st["shared"]["forecast_horizons_h"] = [0, 6, 12, 24]
    look.update(st)
    out = look.outlook(0)
    assert out["price"][5] == 0.6 and out["price"][11] == 0.12 and out["price"][23] == 0.24
    assert out["price"][0] is None  # hour 1 ahead is not known from a single observation
    assert out["price_source"][5] == "f" and out["price_source"][0] == "-"
    # No carbon forecast exists: only 24 hours ahead is known, as the same hour as now.
    assert out["carbon"] == [None] * 23 + [st["shared"]["carbon_intensity"]]


def test_lookahead_after_a_day_covers_every_hour_from_forecasts():
    look = Lookahead()
    states = fake_states(30)
    for st in states[:26]:
        look.update(st)
    out = look.outlook(25)
    assert out["price_source"] == "f" * 24
    # Carbon is the same hour yesterday, taken from what was observed.
    assert out["carbon"][0] == states[2]["shared"]["carbon_intensity"]


def test_lookahead_never_uses_states_not_yet_seen():
    states = fake_states(40)
    look = Lookahead()
    for st in states[:10]:
        look.update(st)
    before = look.outlook(9)
    for st in states[10:]:
        look.update(st)
    # Values for times after hour 9 that were unknown at hour 9 stayed unknown in the early outlook.
    assert before["price"].count(None) > 0
    assert all(look.carbon.get(9 + j - 24) is None for j in range(1, 15))


def test_v2_observation_labels_and_storage():
    states = fake_states(3)
    look = Lookahead()
    for st in states:
        look.update(st)
    st = states[-1]
    obs = build_observation_v2(st, context_from_state(st), None, look)
    assert set(obs["outdoor_c_forecast"]) == {"in_6h", "in_12h", "in_24h"}
    assert "outdoor_c_next_1_2_3h" not in obs and "price_per_kwh_now_and_next_3h" not in obs
    assert len(obs["next_24h"]["price"]) == len(obs["next_24h"]["hour"]) == 24
    assert obs["next_24h"]["hour"][0] == st["shared"]["hour"] % 24 + 1
    b = obs["buildings"]["Building_1"]
    assert set(b["battery"]) == {"soc", "capacity_kwh", "max_fraction_per_hour"}
    assert b["battery"]["soc"] == 0.5 and "soc" in b["dhw_tank"]
    assert {"rank_now", "min", "max", "hours_to_max"} <= set(obs["price_outlook"])


def test_v1_observation_is_unchanged():
    # The v0.2.0 keys stay exactly as they were so its recorded runs replay.
    st = fake_states(1)[0]
    obs = observe(1, st, context_from_state(st), None, Lookahead())
    assert obs == build_observation(st, context_from_state(st), None)
    assert "price_per_kwh_now_and_next_3h" in obs and "outdoor_c_next_1_2_3h" in obs


def test_v2_prompt_states_the_strategy_and_the_rules():
    text = system_prompt_v2(EnvelopeConfig(), ("Building_1",))
    for phrase in ("cheapest, cleanest hours", "Discharge into the peak", "Pre-cooling", "6, 12 and 24 hours ahead",
                   "earns nothing", "away from the baseline_action"):
        assert phrase in text
    assert chr(0x2014) not in text  # no em dashes
    legacy = system_prompt_v2(EnvelopeConfig.from_manifest({}), ("Building_1",))
    assert "away from the baseline_action" not in legacy


def test_request_carries_the_observation_for_each_version():
    st = fake_states(1)[0]
    ctx = context_from_state(st)
    for version in (1, 2, 3, 4, 5, 6, 7):
        obs = observe(version, st, ctx, None, Lookahead())
        req = build_request(obs, EnvelopeConfig(), tuple(st["buildings"]), "haiku", prompt_version=version)
        assert observation_from_request(req) == json.loads(json.dumps(obs))
    with pytest.raises(ValueError):
        observe(8, st, ctx, None, Lookahead())


@pytest.mark.parametrize("version", [3, 4, 5, 6, 7])
def test_rule_policy_charges_cheap_and_discharges_into_the_peak(version):
    # Fake district: price 0.05 most of the day and 0.25 from hour 16 to 20. Version 3 runs the
    # 0.4.0 rule; versions 4 to 7 run their scripted strategies, without peak shaving, which the
    # fake's flat daytime load would trigger all day.
    from hyperbolic.model import StrategyParams, StrategyParamsV5, StrategyParamsV7

    version, cfg = controller_settings(True, version)
    sup = ScriptedSupervisor(strategy=StrategyParams(shave=0.0), strategy_v5=StrategyParamsV5(shave=0.0),
                             strategy_v7=StrategyParamsV7(shave=0.0))
    ctl = AgentController(sup, Envelope(cfg), Budget(1.0), prompt_version=version)
    w = NullWriter()
    run_session(FakeDistrict(), ctl, w, hours=48, log=lambda *_: None)
    by_hour = {}
    for s in w.steps[24:]:  # after one day of carbon history
        by_hour[s["state"]["time_step"] % 24] = s["actions"]["Building_1"]["battery"]
    assert any(by_hour[h] < 0 for h in range(16, 21))
    assert all(by_hour[h] <= 0 for h in range(16, 21))
    assert any(by_hour[h] > 0 for h in range(0, 16))
    assert all(s["decision"]["status"] != "fallback" for s in w.steps)


@needs_citylearn
def test_citylearn_forecasts_are_6_12_24_hours_ahead():
    """Regression for the v0.2.0 bug: these were presented to the model as the next 1, 2 and 3 hours."""
    from hyperbolic.sim import CityLearnSimulator

    sim = CityLearnSimulator(control=False)
    st = sim.start(47)
    states = []
    while st is not None:
        states.append(st)
        _, st = sim.step(None)
    sim.close()
    assert states[0]["shared"]["forecast_horizons_h"] == [0, *dc.FORECAST_HORIZONS_H] == [0, 6, 12, 24]
    price = [s["shared"]["price_forecast"][0] for s in states]
    for t in range(0, len(states) - 24):
        f = states[t]["shared"]["price_forecast"]
        assert (f[1], f[2], f[3]) == (price[t + 6], price[t + 12], price[t + 24])
    # And they are not the next hours: hour 15 sees the evening spike 1 hour ahead but not in f[1].
    t = next(t for t in range(len(price) - 1) if price[t + 1] > price[t] * 1.3)
    assert states[t]["shared"]["price_forecast"][1] != price[t + 1]


def test_v3_observation_has_peak_signal_and_month_end():
    from hyperbolic.signals import PeakTracker

    states = fake_states(30)
    look, peaks = Lookahead(), PeakTracker()
    env = Envelope(EnvelopeConfig())
    for st in states[:27]:
        look.update(st)
        peaks.update(st)
    st = states[26]
    ctx = context_from_state(st, peaks.info(26))
    obs = observe(3, st, ctx, None, look, env)
    assert {"district_load_now_kwh", "target_kwh", "headroom_kwh", "forecast_today_kwh", "today_peak_so_far_kwh",
            "month_peak_so_far_kwh", "limiter_on"} == set(obs["peak"])
    assert obs["peak"]["target_kwh"] == round(env.peak_target(ctx), 2)
    sig = obs["signal_outlook"]
    assert len(sig["next_24h"]) == 24 and sig["weights"] == dc.SIGNAL_WEIGHTS
    assert all(1 <= h <= 24 for h in sig["lowest_hours_ahead"] + sig["highest_hours_ahead"])
    assert obs["hours_left_in_month"] == dc.EPISODE_HOURS - 26
    assert "load_now_kwh" in obs["buildings"]["Building_1"]
    # Version 3 only adds to version 2, so a version 2 replay is unaffected.
    v2 = observe(2, st, ctx, None, look)
    assert all(obs[k] == v for k, v in v2.items() if k != "buildings")


def test_v3_prompt_orders_the_goals_and_limits_the_reason():
    from hyperbolic.prompt import system_prompt_v3

    text = system_prompt_v3(EnvelopeConfig(), ("Building_1",))
    order = [text.index(s) for s in ("1. Comfort:", "2. Peaks:", "3. Cost and carbon:")]
    assert order == sorted(order)
    assert f"at most {dc.REASON_TARGET_CHARS} characters" in text and str(dc.REASON_MAX_CHARS) in text
    assert "headroom_kwh" in text and "spread it" in text and "use the signal, not" in text
    assert chr(0x2014) not in text
    assert "peak.target_kwh" not in system_prompt_v3(EnvelopeConfig(peak_limit=False), ("Building_1",))


def _v4_context(n=27):
    from hyperbolic.signals import PeakTracker, PriceOutlook

    states = fake_states(n + 3)
    look, peaks = Lookahead(), PeakTracker()
    for st in states[:n]:
        look.update(st)
        peaks.update(st)
    st = states[n - 1]
    t = st["time_step"]
    prices = PriceOutlook(st["shared"]["price_forecast"][0], tuple(look.outlook(t)["price"]))
    return st, context_from_state(st, peaks.info(t), prices), look


def test_v4_observation_carries_the_rule_based_reference_action():
    from hyperbolic.model import rule_plan_v3

    st, ctx, look = _v4_context()
    env = Envelope(EnvelopeConfig())
    obs = observe(4, st, ctx, None, look, env)
    v3 = observe(3, st, ctx, None, look, env)
    ref = rule_plan_v3(v3)
    # The reference is exactly what the rule-based controller replies to the same hour.
    rule_req = build_request(v3, EnvelopeConfig.v040(), tuple(st["buildings"]), "haiku", prompt_version=3)
    assert json.loads(ScriptedSupervisor().call(0, rule_req).text) == ref
    for b in st["buildings"]:
        assert obs["buildings"][b]["reference_action"] == ref[b]
    assert obs["reference_reason"] == ref["reason"]
    req = build_request(obs, EnvelopeConfig(), tuple(st["buildings"]), "haiku", prompt_version=4)
    sent = observation_from_request(req)
    assert sent["buildings"]["Building_1"]["reference_action"] == ref["Building_1"]
    assert "reference_action" in req["system"] and "reference_reason" in req["system"]
    # Version 4 only adds to version 3.
    assert all(obs[k] == v for k, v in v3.items() if k != "buildings")
    for b, s in v3["buildings"].items():
        assert all(obs["buildings"][b][k] == v for k, v in s.items() if k != "battery")
        assert set(s["battery"]) < set(obs["buildings"][b]["battery"])


def test_v4_observation_has_the_price_plan_and_the_battery_limits():
    st, ctx, look = _v4_context()  # hour 3 of day two in the fake district: cheap, top price at 16 to 20
    obs = observe(4, st, ctx, None, look, Envelope(EnvelopeConfig()))
    pp = obs["price_plan"]
    assert pp["now"] == 0.05 and pp["top_24h"] == 0.25 and pp["low_24h"] == 0.05
    assert not pp["top_price_now"] and not pp["flat_24h"]
    ahead = look.outlook(st["time_step"])["price"]
    assert pp["top_price_hours_ahead"] and all(ahead[j - 1] == 0.25 for j in pp["top_price_hours_ahead"])
    b = obs["buildings"]["Building_1"]
    assert b["battery"]["soc_floor"] == 0.2 and b["battery"]["usable_kwh"] == 1.2
    assert b["battery"]["round_trip_min"] == 0.88 and b["battery"]["grid_charging_ok"] is True
    assert b["indoor_vs_setpoint_c"] == round(st["buildings"]["Building_1"]["indoor_c"] - 24.0, 2)
    # At the top price, with cheaper hours coming, grid charging is not ok.
    st, ctx, look = _v4_context(24 + 17)
    obs = observe(4, st, ctx, None, look, Envelope(EnvelopeConfig()))
    assert obs["price_plan"]["top_price_now"] is True
    assert obs["buildings"]["Building_1"]["battery"]["grid_charging_ok"] is False
    # Without the spread check there is no verdict to show.
    off = observe(4, st, ctx, None, look, Envelope(EnvelopeConfig.v040()))
    assert off["buildings"]["Building_1"]["battery"]["grid_charging_ok"] is None


def test_v4_prompt_puts_price_first_and_names_the_reference():
    from hyperbolic.prompt import system_prompt_v4

    text = system_prompt_v4(EnvelopeConfig(), ("Building_1",))
    order = [text.index(s) for s in ("1. Comfort:", "2. Peaks:", "3. Cost first, then carbon:")]
    assert order == sorted(order)
    for phrase in ("reference_action", "top_price_now", "grid_charging_ok", "soc_floor", "indoor_vs_setpoint_c",
                   "Hold the battery for the top-price hours", "flat_24h", "cut its cooling", "keep district load"):
        assert phrase in text
    assert f"at most {dc.REASON_TARGET_CHARS} characters" in text
    assert chr(0x2014) not in text
    assert "grid_charging_ok is false" in text
    assert "grid_charging_ok is false" not in system_prompt_v4(EnvelopeConfig.v040(), ("Building_1",))
