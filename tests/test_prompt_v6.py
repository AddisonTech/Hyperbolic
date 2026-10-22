"""Prompt version 6 (0.8.0): the trim hold in the prompt, end_trim in the reply, and the version 5
strategy's battery plan in place of the 0.4.0 reference action."""

import json

import pytest
from fakes import FakeDistrict

from hyperbolic import district as dc
from hyperbolic.envelope import Envelope, EnvelopeConfig, parse_reply, proposal_json_schema
from hyperbolic.model import (
    Budget,
    RecordedReplySupervisor,
    ScriptedSupervisor,
    battery_plan_v5,
    observation_from_request,
    strategy_plan_v5,
)
from hyperbolic.prompt import Lookahead, build_request, observe, system_prompt_v5, system_prompt_v6
from hyperbolic.runner import AgentController, NullWriter, RunWriter, context_from_state, run_session
from hyperbolic.signals import PeakTracker, PriceOutlook

BUILDINGS = ("Building_1", "Building_2", "Building_3")


def _obs(version, n=40, envelope=None):
    """An observation late in the second day of the fake district, so every outlook is filled."""
    sim = FakeDistrict()
    st = sim.start(n + 3)
    look, peaks = Lookahead(), PeakTracker()
    for _ in range(n):
        look.update(st)
        peaks.update(st)
        last = st
        _, st = sim.step(None)
    t = last["time_step"]
    ctx = context_from_state(last, peaks.info(t), PriceOutlook(last["shared"]["price_forecast"][0],
                                                              tuple(look.outlook(t)["price"])))
    env = envelope or Envelope(EnvelopeConfig())
    return last, ctx, look, env, observe(version, last, ctx, None, look, env)


def test_schema_adds_a_nullable_end_trim_per_building_only_for_version_6():
    v5, v6 = proposal_json_schema(BUILDINGS), proposal_json_schema(BUILDINGS, end_trim=True)
    assert "end_trim" not in v5["properties"]["Building_1"]["properties"]
    dev = v6["properties"]["Building_1"]
    assert dev["properties"]["end_trim"] == {"anyOf": [{"type": "string"}, {"type": "null"}]}
    assert "end_trim" in dev["required"] and dev["additionalProperties"] is False
    assert proposal_json_schema(BUILDINGS) == v5  # the cached older schema is not touched


def _reply(**b1):
    r = {"reason": "t"}
    for b in BUILDINGS:
        r[b] = {"cooling": None, "dhw": None, "battery": None, **(b1 if b == "Building_1" else {})}
    return json.dumps(r)


def test_end_trim_parses_for_version_6_and_is_refused_before_it():
    p, err = parse_reply(_reply(end_trim="room needs it"), BUILDINGS, end_trim=True)
    assert err is None and p["end_trim"] == {"Building_1": "room needs it"}
    assert set(p["buildings"]["Building_1"]) == {"cooling", "dhw", "battery"}
    p, err = parse_reply(_reply(end_trim=None), BUILDINGS, end_trim=True)
    assert err is None and p["end_trim"] == {}
    p, err = parse_reply(_reply(), BUILDINGS, end_trim=True)  # left out: same as null
    assert err is None and p["end_trim"] == {}
    for bad in ("", "x" * (dc.REASON_MAX_CHARS + 1), 3):
        p, err = parse_reply(_reply(end_trim=bad), BUILDINGS, end_trim=True)
        assert p is None and "end_trim" in err
    p, err = parse_reply(_reply(end_trim="no"), BUILDINGS)  # version 5 has no such field
    assert p is None and "end_trim" in err
    p, err = parse_reply(_reply(), BUILDINGS)
    assert err is None and "end_trim" not in p


def test_v6_observation_swaps_the_reference_action_for_the_strategy_battery_plan():
    env = Envelope(EnvelopeConfig())
    st, ctx, look, env, v6 = _obs(6, envelope=env)
    v5 = observe(5, st, ctx, None, look, env)
    assert "reference_reason" not in v6 and "reference_action" not in json.dumps(v6)
    assert {k for k in v6 if k != "strategy_battery_reason"} == {k for k in v5 if k != "reference_reason"}
    battery, why = battery_plan_v5(v5)
    assert v6["strategy_battery_reason"] == why
    for b in BUILDINGS:
        assert set(v6["buildings"][b]) == set(v5["buildings"][b]) - {"reference_action"} | {
            "strategy_battery", "cooling_trim_held"}
        assert v6["buildings"][b]["strategy_battery"] == battery[b]
        assert v6["buildings"][b]["cooling_trim_held"] == 0.0


def test_v6_observation_shows_the_trim_the_envelope_will_hold():
    env = Envelope(EnvelopeConfig())
    env.holds = {"Building_2": 0.06}
    st, ctx, look, env, obs = _obs(6, envelope=env)
    st_b2 = ctx.buildings["Building_2"]
    assert obs["buildings"]["Building_2"]["cooling_trim_held"] == -round(env.held_trim("Building_2", st_b2)[0], 3)


def test_battery_plan_is_the_v5_strategys_own_battery_action():
    st, ctx, look, env, v5 = _obs(5)
    battery, why = battery_plan_v5(v5)
    full = strategy_plan_v5(v5)
    assert battery == {b: full[b]["battery"] for b in BUILDINGS}
    assert why and len(why) <= dc.REASON_TARGET_CHARS and "cooling" not in why


def test_v6_system_prompt_states_the_hold_and_the_early_end():
    cfg = EnvelopeConfig()
    text = system_prompt_v6(cfg, BUILDINGS)
    for phrase in ("holds a trim in code", "more than 0.5 C below its setpoint", "at most 0.02 per hour",
                   "end_trim", "strategy_battery", "null keeps a held trim", "cooling above a held trim"):
        assert phrase in text
    assert "reference_action" not in text and chr(0x2014) not in text
    assert "held trim" not in system_prompt_v6(EnvelopeConfig.v070(), BUILDINGS).split("It will clamp:")[1]


def test_v6_request_stays_close_to_v5_in_size():
    st, ctx, look, env, v6 = _obs(6)
    v5 = observe(5, st, ctx, None, look, env)
    r5 = build_request(v5, env.config, BUILDINGS, "haiku", prompt_version=5)
    r6 = build_request(v6, env.config, BUILDINGS, "haiku", prompt_version=6)
    assert "end_trim" in json.dumps(r6["output_config"]) and "end_trim" not in json.dumps(r5["output_config"])
    assert len(json.dumps(r6)) < 1.06 * len(json.dumps(r5))
    assert len(r6["system"]) < 1.07 * len(system_prompt_v5(env.config, BUILDINGS))


def test_scripted_v6_reply_follows_the_strategy_battery_and_never_ends_a_trim():
    st, ctx, look, env, obs = _obs(6)
    req = build_request(obs, env.config, BUILDINGS, "haiku", prompt_version=6)
    res = ScriptedSupervisor().call(5, req)
    reply = json.loads(res.text)
    for b in BUILDINGS:
        assert reply[b]["battery"] == obs["buildings"][b]["strategy_battery"] and reply[b]["end_trim"] is None
    p, err = parse_reply(res.text, BUILDINGS, end_trim=True)
    assert err is None and p["end_trim"] == {}


def test_v6_run_on_the_fake_district_is_clean():
    ctl = AgentController(ScriptedSupervisor(), Envelope(EnvelopeConfig()), Budget(2.0), prompt_version=6)
    w = NullWriter()
    res = run_session(FakeDistrict(), ctl, w, hours=48, log=lambda *_: None)
    assert res["fallback_steps"] == 0 and ctl.describe()["prompt_version"] == 6


def test_recorded_replies_are_served_by_hour_whatever_the_request(tmp_path):
    run = tmp_path / "v6"
    ctl = AgentController(ScriptedSupervisor(tokens=(5000, 780)), Envelope(EnvelopeConfig()), Budget(2.0),
                          prompt_version=6)
    run_session(FakeDistrict(), ctl, RunWriter(run), hours=24, log=lambda *_: None)
    sup = RecordedReplySupervisor(run / "calls.jsonl", "haiku")
    calls = [json.loads(x) for x in (run / "calls.jsonl").read_text(encoding="utf-8").splitlines()]
    got = sup.call(3, {"messages": [{"role": "user", "content": "anything"}]})
    assert got.text == calls[3]["reply"]["text"] and got.input_tokens == 5000
    assert sup.call(99, {}).error == "no recorded reply for this hour"
    assert observation_from_request(calls[3]["request"])["time_step"] == 3


@pytest.mark.parametrize("version", [1, 2, 3, 4, 5])
def test_older_prompt_versions_build_the_same_requests(version):
    """Requests for versions 1 to 5 carry no end_trim, so recorded runs keep their hashes."""
    st, ctx, look, env, obs = _obs(version)
    req = build_request(obs, EnvelopeConfig.v070(), BUILDINGS, "haiku", prompt_version=version)
    assert "end_trim" not in json.dumps(req)
