"""Prompt version 10 (0.13.0), free mode: the version 9 strategy shown as a suggestion, the extra fields,
the reply schema with deviation_reason, the rule that a departure carries one, the envelope and versions
1 to 9 unchanged, and runs that log, replay and show their deviations."""

import hashlib
import json
from pathlib import Path

import pytest
from conftest import BUILDINGS, FIXTURES, needs_citylearn
from fakes import FakeDistrict
from test_prompt_v8 import _obs

from hyperbolic import prompt as P
from hyperbolic.envelope import Envelope, EnvelopeConfig, proposal_json_schema
from hyperbolic.model import Budget, CallResult, ScriptedSupervisor, StrategyParamsV9, observation_from_request, \
    strategy_plan_v9
from hyperbolic.prompt import (
    DEVIATION_REASON_MAX_CHARS,
    FREE_MODE_FROM,
    PROMPT_VERSION,
    build_request,
    observe,
    parse_reply_v10,
    reply_json_schema,
    system_prompt_v10,
)
from hyperbolic.runner import AgentController, NullWriter, RunWriter, controller_settings, load_jsonl, replay_run, \
    run_session
from hyperbolic.viewer import _decision

ROOT = Path(__file__).parents[1]

# Fingerprints taken from 0.12.0 before version 10 was written: the envelope's source, every earlier
# system prompt (default rules, these three buildings) and both earlier reply schemas.
ENVELOPE_SHA256 = "4527158b52613a5657e4050002de359898c23dd52f2917f65b7c4aa9efee356d"
SYSTEM_SHA256 = {
    1: "843b2d2dd8f2d827901327ae3e8da4d4563a976acd2ade689778c31318259eba",
    2: "9144c90d2d1ae72a78239c9f5b023306e2c00e41e05832b47f69406aa6b8a76e",
    3: "f751bd925d18ebc7ae5cf8d2854b51538416a8ce66f198f0f2fbb2a37e8f8744",
    4: "3949115a5aabd1df2a1b19a8f4d4d18bdd6ebe65022ca0b72dd0a93eb4a5af83",
    5: "017060f37d675b3d8dd653fc663eced80e30129ba6c3abaa9a34ad65b875874f",
    6: "97308128e85269dca862b2e3dcc3f1666cf011cc2ba937da879269fa2f4fce11",
    7: "13c33f7b4494dfc6f9fbe6c5dca83a55c77fcb26d1f90d28fd925904c91e3616",
    8: "980bc32a9ee56525c48686c4d5b0cda35dfb38e9249f1aebff0b5c04c55971da",
    9: "e04b38d2b8ac649e1428eb9dfee23606a3fd5a60862ffda0d9805d083c734138",
}
SCHEMA_SHA256 = {False: "01a41da7745ff6b39a7905c99accc804b50afa45afbd70c498c743b1fe778726",
                 True: "8c71b48d29f16ad3a8e10bae647cf3b3a8d6b167bc8f7310188859cb46403cc4"}
SYSTEM_PROMPTS = {1: P.system_prompt, 2: P.system_prompt_v2, 3: P.system_prompt_v3, 4: P.system_prompt_v4,
                  5: P.system_prompt_v5, 6: P.system_prompt_v6, 7: P.system_prompt_v7, 8: P.system_prompt_v8,
                  9: P.system_prompt_v9}


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def _schema_sha(schema: dict) -> str:
    return _sha(json.dumps(schema, sort_keys=True))


def _reply(obs, reason="Follow the suggestion.", **changes):
    """The suggestion exactly, with changes per building: {device: value, "deviation_reason": text}."""
    out = {"reason": reason}
    for b in BUILDINGS:
        acts = {**obs["buildings"][b]["suggestion"], "end_trim": None, "deviation_reason": None}
        acts.update(changes.get(b, {}))
        out[b] = acts
    return json.dumps(out)


# -- the observation and the suggestion ----------------------------------------------------


def test_v10_is_selectable_and_not_the_default():
    assert PROMPT_VERSION == 9 and FREE_MODE_FROM == 10 and 10 in P.PROMPT_VERSIONS
    assert controller_settings(False, 10) == (10, EnvelopeConfig()) and controller_settings(False, 9)[1] == EnvelopeConfig()


def test_suggestion_is_exactly_the_v9_strategy():
    st, ctx, look, env, v9 = _obs(version=9)
    v10 = observe(10, st, ctx, None, look, env)
    plan = strategy_plan_v9(v9)
    assert v10["suggestion_reason"] == v9["strategy_reason"] == plan["reason"]
    for b in BUILDINGS:
        assert v10["buildings"][b]["suggestion"] == v9["buildings"][b]["strategy"]
        assert v10["buildings"][b]["suggestion"] == {d: plan[b][d] for d in ("cooling", "dhw", "battery")}


def test_v10_keeps_every_v9_field_and_adds_only_what_the_state_already_held():
    st, ctx, look, env, v9 = _obs(version=9)
    v10 = observe(10, st, ctx, None, look, env)
    assert set(v10) == (set(v9) - {"strategy_reason"}) | {"suggestion_reason", "solar_forecast"}
    for k in set(v9) - {"strategy_reason", "buildings"}:
        assert v10[k] == v9[k], k
    assert v10["solar_forecast"] == {"direct_w_m2": {"now": 300.0, "in_6h": 320.0, "in_12h": 340.0, "in_24h": 360.0}}
    assert st["shared"]["direct_solar_forecast"] == [300.0, 320.0, 340.0, 360.0]
    for b in BUILDINGS:
        old, new = v9["buildings"][b], v10["buildings"][b]
        assert set(new) == (set(old) - {"strategy"}) | {"suggestion", "cooling_power_kw"}
        for k in set(old) - {"strategy", "battery", "dhw_tank"}:
            assert new[k] == old[k], k
        assert set(new["battery"]) == set(old["battery"]) | {"power_kw", "loss_per_hour"}
        assert set(new["dhw_tank"]) == set(old["dhw_tank"]) | {"heater_efficiency"}
        s = st["buildings"][b]
        assert new["battery"]["power_kw"] == (None if s.get("battery_power_kw") is None
                                              else round(s["battery_power_kw"], 2))


def test_the_suggestion_never_ends_a_trim_early():
    # The night rule is off in the shipped strategy, so a reply's end_trim is always a departure.
    assert StrategyParamsV9().night_from_hour == 0


def test_v10_system_prompt_offers_the_freedom_and_asks_for_a_hypothesis():
    text = " ".join(system_prompt_v10(EnvelopeConfig(), BUILDINGS).split())
    for phrase in ("It is a suggestion, not an instruction", "cool a room ahead of the top-price hours while power "
                   "is cheap", "without losing comfort or making the daily or monthly peak worse",
                   "deviation_reason", "your hypothesis", f"{DEVIATION_REASON_MAX_CHARS + 1} characters or more",
                   "solar_forecast", "cooling_power_kw", "Where you see no gain, send the suggestion exactly"):
        assert phrase in text, phrase
    assert chr(0x2014) not in text and chr(0x2013) not in text and "strategy_battery" not in text


# -- the reply schema and the deviation rule ---------------------------------------------------


def test_v10_schema_requires_deviation_reason_in_every_building():
    s = reply_json_schema(BUILDINGS, 10)
    for b in BUILDINGS:
        dev = s["properties"][b]
        assert dev["required"] == ["cooling", "dhw", "battery", "end_trim", "deviation_reason"]
        assert dev["properties"]["deviation_reason"] == {"anyOf": [{"type": "string"}, {"type": "null"}]}
        assert dev["additionalProperties"] is False
    st, ctx, look, env, v10 = _obs(version=10)
    assert build_request(v10, env.config, BUILDINGS, "sonnet", prompt_version=10)["output_config"]["format"]["schema"] == s


def test_earlier_schemas_and_system_prompts_are_byte_identical():
    reply_json_schema(BUILDINGS, 10)  # building the version 10 schema must not touch the shared one
    assert _schema_sha(proposal_json_schema(BUILDINGS, False)) == SCHEMA_SHA256[False]
    assert _schema_sha(proposal_json_schema(BUILDINGS, True)) == SCHEMA_SHA256[True]
    for v in range(1, 10):
        assert reply_json_schema(BUILDINGS, v) == proposal_json_schema(BUILDINGS, P.end_trim_field(v))
        _, cfg = controller_settings(v <= 3, v)
        assert _sha(SYSTEM_PROMPTS[v](cfg, BUILDINGS)) == SYSTEM_SHA256[v], v


def test_the_envelope_is_unchanged():
    data = (ROOT / "hyperbolic" / "envelope.py").read_bytes().replace(b"\r\n", b"\n")
    assert hashlib.sha256(data).hexdigest() == ENVELOPE_SHA256


def test_following_the_suggestion_needs_no_reason():
    *_, obs = _obs(version=10)
    p, err, devs = parse_reply_v10(_reply(obs), BUILDINGS, obs)
    assert err is None and devs == {}
    for b in BUILDINGS:
        assert p["buildings"][b] == obs["buildings"][b]["suggestion"]


def test_a_departure_without_deviation_reason_is_invalid():
    *_, obs = _obs(version=10)
    s = obs["buildings"]["Building_2"]["suggestion"]
    moved = round((s["battery"] or 0.0) + 0.05, 3)
    _, err, devs = parse_reply_v10(_reply(obs, Building_2={"battery": moved}), BUILDINGS, obs)
    assert err == "Building_2 differs from its suggestion (battery) without deviation_reason" and devs == {}
    p, err, devs = parse_reply_v10(_reply(obs, Building_2={"battery": moved, "deviation_reason": "charge early"}),
                                   BUILDINGS, obs)
    assert err is None and p["buildings"]["Building_2"]["battery"] == moved
    assert devs == {"Building_2": {"devices": ["battery"], "reason": "charge early"}}


def test_what_counts_as_a_departure():
    *_, obs = _obs(version=10)
    b = "Building_1"
    ob = obs["buildings"][b]
    base, sug = ob["baseline_action"], ob["suggestion"]
    diff = P.differing_devices
    assert diff(sug, sug, base) == []
    # null is baseline_action, on either side
    assert diff({**sug, "cooling": base["cooling"]}, {**sug, "cooling": None}, base) == []
    assert diff({**sug, "cooling": None}, {**sug, "cooling": round(base["cooling"] - 0.05, 3)}, base) == ["cooling"]
    # within the tolerance is the same action; beyond it is not
    assert diff({**sug, "dhw": (sug["dhw"] or 0.0) + 0.0004}, sug, base) == []
    assert diff({**sug, "dhw": (sug["dhw"] or 0.0) + 0.002}, sug, base) == ["dhw"]
    assert diff(sug, sug, base, end_trim="room is back at setpoint") == ["end_trim"]
    # an end_trim needs a reason like any other departure
    _, err, _ = parse_reply_v10(_reply(obs, Building_1={"cooling": None, "end_trim": "warm"}), BUILDINGS, obs)
    assert err is not None and "without deviation_reason" in err


def test_deviation_reason_shape_is_checked():
    *_, obs = _obs(version=10)
    missing = json.loads(_reply(obs))
    del missing["Building_3"]["deviation_reason"]
    assert parse_reply_v10(json.dumps(missing), BUILDINGS, obs)[1] == \
        "reply failed schema at Building_3.deviation_reason: Field required"
    s = obs["buildings"]["Building_3"]["suggestion"]
    moved = {"battery": round((s["battery"] or 0.0) - 0.05, 3)}
    ok = "x" * DEVIATION_REASON_MAX_CHARS
    assert DEVIATION_REASON_MAX_CHARS == 149  # under 150 characters
    assert parse_reply_v10(_reply(obs, Building_3={**moved, "deviation_reason": ok}), BUILDINGS, obs)[1] is None
    for bad in (ok + "x", "", 3):
        assert "deviation_reason" in parse_reply_v10(_reply(obs, Building_3={**moved, "deviation_reason": bad}),
                                                     BUILDINGS, obs)[1]
    # a reason with no departure is kept and logged
    _, err, devs = parse_reply_v10(_reply(obs, Building_1={"deviation_reason": "suggestion looks right"}), BUILDINGS, obs)
    assert err is None and devs == {"Building_1": {"devices": [], "reason": "suggestion looks right"}}
    # everything else is still the envelope's own parse
    assert parse_reply_v10(_reply(obs, Building_1={"battery": "half"}), BUILDINGS, obs)[1].startswith("reply failed schema")
    assert parse_reply_v10(None, BUILDINGS, obs)[1] == "empty or missing reply"


# -- runs ----------------------------------------------------------------------------------


class DepartingSupervisor:
    """Sends the suggestion, but from hour 30 charges Building_1's battery 0.05 more with a reason
    (or without one when reasoned is False)."""

    kind = "scripted"
    model_key = "haiku"

    def __init__(self, reasoned=True):
        self.reasoned = reasoned

    def call(self, step, request):
        obs = observation_from_request(request)
        reply = json.loads(ScriptedSupervisor().call(step, request).text)
        if step >= 30:
            b = reply["Building_1"]
            b["battery"] = round((b["battery"] or 0.0) + 0.05, 3)
            b["deviation_reason"] = "charge a little more while cheap" if self.reasoned else None
        assert "suggestion" in obs["buildings"]["Building_1"]
        return CallResult(json.dumps(reply), stop_reason="end_turn", model="scripted")


def test_scripted_v10_sends_the_suggestion_and_matches_scripted_v9_hour_for_hour():
    runs = {}
    for v in (9, 10):
        w = NullWriter()
        ctl = AgentController(ScriptedSupervisor(), Envelope(EnvelopeConfig()), Budget(2.0), prompt_version=v)
        res = run_session(FakeDistrict(), ctl, w, hours=48, log=lambda *_: None)
        assert res["fallback_steps"] == 0
        runs[v] = w.steps
    for a, b in zip(runs[9], runs[10]):
        assert a["actions"] == b["actions"] and a["decision"]["actions"] == b["decision"]["actions"]
        assert "deviations" not in a and b["deviations"] == {}


def test_a_departing_run_logs_replays_and_shows_its_deviations(tmp_path):
    run = tmp_path / "v10"
    ctl = AgentController(DepartingSupervisor(), Envelope(EnvelopeConfig()), Budget(2.0), prompt_version=10)
    res = run_session(FakeDistrict(), ctl, RunWriter(run), hours=48, log=lambda *_: None)
    assert res["fallback_steps"] == 0
    steps = load_jsonl(run / "steps.jsonl")
    assert all(s["deviations"] == {} for s in steps[:30])
    late = [s for s in steps[30:] if s["deviations"]]
    assert late and all(s["deviations"]["Building_1"]["reason"] == "charge a little more while cheap" for s in late)
    view = _decision(late[0])
    assert view["deviations"] == [{"building": "Building_1", "devices": ["battery"],
                                   "reason": "charge a little more while cheap"}]
    assert "deviations" not in _decision(steps[0])
    rep = replay_run(run)
    assert rep.deterministic and rep.identical_steps == 48 and rep.api_calls == 0
    # a replay that would drop or change a hypothesis is caught
    lines = (run / "steps.jsonl").read_text(encoding="utf-8").splitlines()
    rec = json.loads(lines[40])
    rec["deviations"] = {}
    lines[40] = json.dumps(rec)
    (run / "steps.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert not replay_run(run).deterministic


def test_a_departure_without_a_reason_falls_back_for_that_hour():
    w = NullWriter()
    ctl = AgentController(DepartingSupervisor(reasoned=False), Envelope(EnvelopeConfig()), Budget(2.0),
                          prompt_version=10)
    res = run_session(FakeDistrict(), ctl, w, hours=40, log=lambda *_: None)
    assert res["fallback_steps"] == 10
    assert "without deviation_reason" in w.steps[35]["decision"]["fallback"]


@pytest.mark.parametrize("name", ["agent_fixture", "baseline_fixture"])
def test_recorded_fixture_runs_still_replay(name):
    rep = replay_run(FIXTURES / "runs" / name)
    assert rep.deterministic and rep.api_calls == 0


@needs_citylearn
def test_v10_scripted_matches_v9_on_24_hours_of_citylearn(tmp_path):
    from hyperbolic.sim import CityLearnSimulator

    out = {}
    for v in (9, 10):
        _, cfg = controller_settings(True, v)
        ctl = AgentController(ScriptedSupervisor(), Envelope(cfg), Budget(2.0), prompt_version=v)
        run_dir = tmp_path / f"v{v}"
        res = run_session(CityLearnSimulator(control=True), ctl, RunWriter(run_dir), hours=24, log=lambda *_: None,
                          sim_info={"kind": "citylearn", "control": True})
        assert res["steps"] == 24 and res["fallback_steps"] == 0
        out[v] = load_jsonl(run_dir / "steps.jsonl")
        if v == 10:
            req = load_jsonl(run_dir / "calls.jsonl")[5]["request"]
            assert '"suggestion":' in req["messages"][0]["content"] and '"solar_forecast":' in req["messages"][0]["content"]
            assert req["system"][0]["cache_control"] == {"type": "ephemeral"}  # caching is on for new runs
            rep = replay_run(run_dir)
            assert rep.deterministic and rep.api_calls == 0 and rep.identical_steps == 24
    assert [s["actions"] for s in out[9]] == [s["actions"] for s in out[10]]
