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
from hyperbolic.runner import AgentController, NullWriter, context_from_state, run_session


def fake_states(n):
    sim = FakeDistrict()
    st = sim.start(n)
    out = []
    while st is not None:
        out.append(st)
        _, st = sim.step(None)
    return out


def test_default_prompt_is_version_2():
    assert PROMPT_VERSION == 2
    assert AgentController(ScriptedSupervisor(), Envelope(), Budget(1.0)).describe()["prompt_version"] == 2


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
    for version in (1, 2):
        obs = observe(version, st, ctx, None, Lookahead())
        req = build_request(obs, EnvelopeConfig(), tuple(st["buildings"]), "haiku", prompt_version=version)
        assert observation_from_request(req) == json.loads(json.dumps(obs))
    with pytest.raises(ValueError):
        observe(3, st, ctx, None, Lookahead())


def test_rule_policy_charges_cheap_and_discharges_into_the_peak():
    # Fake district: price 0.05 most of the day and 0.25 from hour 16 to 20.
    ctl = AgentController(ScriptedSupervisor(), Envelope(EnvelopeConfig()), Budget(1.0))
    w = NullWriter()
    run_session(FakeDistrict(), ctl, w, hours=48, log=lambda *_: None)
    by_hour = {}
    for s in w.steps[24:]:  # after one day of carbon history
        by_hour[s["state"]["time_step"] % 24] = s["actions"]["Building_1"]["battery"]
    assert any(by_hour[h] < 0 for h in range(16, 21))
    assert all(by_hour[h] <= 0 for h in range(16, 21))
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
