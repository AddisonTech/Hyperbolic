"""Prompt version 12 (0.15.0), rules in words: exactly the version 11 observation, the version 11 system prompt
plus the version 10 strategy section worded as an instruction, the envelope's own reply schema, the shadow
strategy logged every hour as in version 11 and never sent, scripted version 12 equal to scripted version 9,
and the envelope, versions 1 to 11 and every recorded run unchanged."""

import dataclasses
import hashlib
import json
from pathlib import Path

import pytest
from conftest import BUILDINGS, FIXTURES, needs_citylearn
from fakes import FakeDistrict
from test_prompt_v8 import _obs
from test_prompt_v11 import ENVELOPE_SHA256, NullSupervisor

from hyperbolic import prompt as P
from hyperbolic.envelope import Envelope, EnvelopeConfig, proposal_json_schema
from hyperbolic.model import Budget, ScriptedSupervisor, StrategyParamsV9, observation_from_request, strategy_plan_v9
from hyperbolic.prompt import PROMPT_VERSION, RULES_IN_WORDS, build_request, observe, reply_json_schema, \
    shadow_strategy, system_prompt_v10, system_prompt_v11, system_prompt_v12, system_text
from hyperbolic.runner import AgentController, NullWriter, RunWriter, controller_settings, load_jsonl, replay_run, \
    run_session

ROOT = Path(__file__).parents[1]

# Taken from 0.14.0 before version 12 was written: the version 11 system prompt (default rules, these three
# buildings) and its reply schema. Versions 1 to 10 are pinned in test_prompt_v10.py and test_prompt_v11.py.
V11_SYSTEM_SHA256 = "bb19a8bf18653aea8f7369920872f1f777253350bd99f1357030313a6cc15b2a"
V11_SCHEMA_SHA256 = "8c71b48d29f16ad3a8e10bae647cf3b3a8d6b167bc8f7310188859cb46403cc4"
# Words that would mean a computed action reached the model: the suggestion of version 10, the strategy
# field of versions 8 and 9, and the shadow itself.
COMPUTED = ("suggestion", "strategy_reason", '"strategy"', "shadow", "deviation_reason")


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def _rules(text: str) -> str:
    """The three numbered rules of a strategy section, from "1. Cooling." to the tank rule."""
    start = text.index("1. Cooling.")
    end = text.index("3. Leave the hot water tank at 0.") + len("3. Leave the hot water tank at 0.")
    return text[start:end]


def _request_has_no_computed_action(req: dict) -> None:
    """No computed suggestion anywhere in the request: the observation is the version 11 one, and no part of
    the request (system prompt, observation or schema) names a suggestion, a strategy field or the shadow."""
    text = json.dumps(req).lower()
    for word in COMPUTED:
        assert word not in text, word
    obs = observation_from_request(req)
    for ob in obs["buildings"].values():
        assert not ({"suggestion", "strategy", "strategy_battery", "reference_action"} & set(ob))


# -- the observation, the prompt and the schema ------------------------------------------------


def test_v12_is_selectable_and_not_the_default():
    assert PROMPT_VERSION == 9 and RULES_IN_WORDS == 12 and P.PROMPT_VERSIONS[-1] == 12
    assert controller_settings(False, 12) == (12, EnvelopeConfig())
    assert not P.free_mode(12) and P.logs_shadow(12) and P.logs_shadow(11)
    assert not any(P.logs_shadow(v) for v in range(1, 11))


def test_v12_observation_is_exactly_v11():
    st, ctx, look, env, _ = _obs(version=11)
    assert observe(12, st, ctx, None, look, env) == observe(11, st, ctx, None, look, env)


def test_v12_schema_is_the_envelopes_with_end_trim():
    s = reply_json_schema(BUILDINGS, 12)
    assert s == proposal_json_schema(BUILDINGS, True) == reply_json_schema(BUILDINGS, 11)
    for b in BUILDINGS:
        assert s["properties"][b]["required"] == ["cooling", "dhw", "battery", "end_trim"]
        assert "deviation_reason" not in s["properties"][b]["properties"]
    st, ctx, look, env, v12 = _obs(version=12)
    assert build_request(v12, env.config, BUILDINGS, "haiku", prompt_version=12)["output_config"]["format"]["schema"] == s


def test_v12_prompt_is_v11_plus_the_strategy_section():
    cfg = EnvelopeConfig()
    v11, v12 = system_prompt_v11(cfg, BUILDINGS), system_prompt_v12(cfg, BUILDINGS)
    section = P.strategy_section_v12()
    # version 11's text, every character of it, with the section and a blank line added before the actions
    assert v12.replace(section + "\n\n", "", 1) == v11
    assert v12.index("What you see:") < v12.index(section) < v12.index("Actions per building.")


def test_v12_strategy_is_the_v10_rules_word_for_word_as_an_instruction():
    cfg = EnvelopeConfig()
    v10, v12 = system_prompt_v10(cfg, BUILDINGS), system_prompt_v12(cfg, BUILDINGS)
    assert _rules(v12) == _rules(v10)
    assert "Strategy (suggestion already applies it):" in v10
    assert "Strategy (apply it every hour, in every building, to choose cooling, dhw and battery):" in v12
    low = v12.lower()
    for word in ("suggestion", "free mode", "deviation_reason", "already applies"):
        assert word not in low, word
    assert chr(0x2014) not in v12 and chr(0x2013) not in v12


def test_v12_prompt_prints_the_strategy_numbers():
    sp = StrategyParamsV9()
    flat = " ".join(system_prompt_v12(EnvelopeConfig(), BUILDINGS).split())
    for phrase in (f"more than {sp.cold_margin_c:g} C below its setpoint is overcooled",
                   f"to {sp.cold_trim:g} at {sp.cold_margin_c + sp.cold_ramp_c:g} C or more below",
                   f"from 0 at {sp.warm_margin_c:g} C above its setpoint to {sp.warm_boost:g} at "
                   f"{sp.warm_margin_c + sp.warm_ramp_c:g} C or more above",
                   f"keeping {sp.evening_reserve:g} above the floor",
                   f"at least {sp.shave:g} x forecast_today_kwh",
                   f"up to {sp.charge_rate:g} of capacity per hour",
                   f"to be near {sp.soc_target:g} when the top price starts",
                   "Leave the hot water tank at 0."):
        assert phrase in flat, phrase


def test_v12_prompt_follows_strategy_params(monkeypatch):
    """The numbers come from StrategyParamsV9 itself, so the prompt cannot drift from the code's strategy."""
    odd = dataclasses.replace(StrategyParamsV9(), cold_margin_c=0.77, shave=0.61, soc_target=0.71)
    monkeypatch.setattr(P, "StrategyParamsV9", lambda: odd)
    text = system_prompt_v12(EnvelopeConfig(), BUILDINGS)
    assert "more than 0.77 C below" in text and "0.61 x forecast_today_kwh" in text and "near 0.71" in text


def test_a_v12_request_carries_no_computed_suggestion():
    st, ctx, look, env, v12 = _obs(version=12)
    for cache in (False, True):
        req = build_request(v12, env.config, BUILDINGS, "haiku", prompt_version=12, prompt_cache=cache)
        _request_has_no_computed_action(req)
        assert system_text(req) == system_prompt_v12(env.config, BUILDINGS)


def test_v12_system_prompt_is_long_enough_to_cache():
    assert len(system_prompt_v12(EnvelopeConfig(), BUILDINGS)) >= 4 * 512


# -- the shadow strategy -----------------------------------------------------------------------


def test_v12_shadow_is_strategy_plan_v9_exactly():
    st, ctx, look, env, v9 = _obs(version=9)
    shadow = shadow_strategy(observe(12, st, ctx, None, look, env))
    assert shadow == strategy_plan_v9(v9)
    for b in BUILDINGS:
        assert {d: shadow[b][d] for d in ("cooling", "dhw", "battery")} == v9["buildings"][b]["strategy"]


def _run(version, hours=48, run_dir=None):
    w = RunWriter(run_dir) if run_dir else NullWriter()
    ctl = AgentController(ScriptedSupervisor(), Envelope(EnvelopeConfig()), Budget(2.0), prompt_version=version)
    res = run_session(FakeDistrict(), ctl, w, hours=hours, log=lambda *_: None)
    assert res["fallback_steps"] == 0
    return res, (load_jsonl(run_dir / "steps.jsonl") if run_dir else w.steps)


def test_scripted_v12_matches_scripted_v9_and_logs_the_shadow_every_hour(tmp_path):
    _, v9 = _run(9, run_dir=tmp_path / "v9")
    _, v11 = _run(11, run_dir=tmp_path / "v11")
    _, v12 = _run(12, run_dir=tmp_path / "v12")
    v9_replies = [json.loads(c["reply"]["text"]) for c in load_jsonl(tmp_path / "v9" / "calls.jsonl")]
    assert len(v9) == len(v12) == 48
    for a, b, c, plan in zip(v9, v11, v12, v9_replies):
        assert a["actions"] == c["actions"] and a["decision"]["actions"] == c["decision"]["actions"]
        assert "shadow_strategy" not in a and "deviations" not in c
        # logged exactly as in version 11: the version 9 strategy on the version 9 observation of the same hour
        assert c["shadow_strategy"] == b["shadow_strategy"] == plan
    for call, s in zip(load_jsonl(tmp_path / "v12" / "calls.jsonl"), v12):
        assert json.loads(call["reply"]["text"]) == s["shadow_strategy"]
        _request_has_no_computed_action(call["request"])


def test_the_v12_shadow_follows_the_state_a_model_left_and_replays(tmp_path):
    run = tmp_path / "null"
    ctl = AgentController(NullSupervisor(), Envelope(EnvelopeConfig()), Budget(2.0), prompt_version=12)
    run_session(FakeDistrict(), ctl, RunWriter(run), hours=48, log=lambda *_: None)
    steps, calls = load_jsonl(run / "steps.jsonl"), load_jsonl(run / "calls.jsonl")
    for s, c in zip(steps, calls):
        assert s["shadow_strategy"] == strategy_plan_v9(observation_from_request(c["request"]))
        assert system_text(c["request"]) == system_prompt_v12(EnvelopeConfig(), BUILDINGS)
    assert any(s["shadow_strategy"][b]["battery"] for s in steps for b in BUILDINGS)
    rep = replay_run(run)
    assert rep.deterministic and rep.identical_steps == 48 and rep.api_calls == 0
    lines = (run / "steps.jsonl").read_text(encoding="utf-8").splitlines()
    rec = json.loads(lines[30])
    rec["shadow_strategy"]["Building_1"]["battery"] = 0.123
    lines[30] = json.dumps(rec)
    (run / "steps.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    assert not replay_run(run).deterministic


# -- nothing earlier changes -------------------------------------------------------------------


def test_the_envelope_is_unchanged():
    data = (ROOT / "hyperbolic" / "envelope.py").read_bytes().replace(b"\r\n", b"\n")
    assert hashlib.sha256(data).hexdigest() == ENVELOPE_SHA256


def test_version_11_prompt_and_schema_are_byte_identical():
    assert _sha(system_prompt_v11(EnvelopeConfig(), BUILDINGS)) == V11_SYSTEM_SHA256
    assert _sha(json.dumps(reply_json_schema(BUILDINGS, 11), sort_keys=True)) == V11_SCHEMA_SHA256


def test_versions_1_to_11_requests_are_unchanged_by_version_12():
    """Every earlier version builds the same request it did before: none logs a shadow but version 11, and
    none of their system prompts carries the version 12 heading."""
    st, ctx, look, env, _ = _obs(version=9)
    for v in range(1, 12):
        obs = observe(v, st, ctx, None, look, env)
        text = system_text(build_request(obs, env.config, BUILDINGS, "haiku", prompt_version=v))
        assert "apply it every hour" not in text, v
        assert P.logs_shadow(v) == (v == 11)


@pytest.mark.parametrize("name", ["agent_fixture", "baseline_fixture"])
def test_recorded_fixture_runs_still_replay(name):
    rep = replay_run(FIXTURES / "runs" / name)
    assert rep.deterministic and rep.api_calls == 0


# Every recorded agent run on disk (runs/ is not in git, so CI skips these): the live, smoke and rule runs,
# the 0.13.0 and 0.14.0 runs, and the 0.15.0 runs once they exist. Replay reads the recorded files and makes
# no model or simulator call.
RECORDED = sorted(p.parent for p in (ROOT / "runs").rglob("calls.jsonl")) if (ROOT / "runs").is_dir() else []


@pytest.mark.skipif(not RECORDED, reason="no recorded runs on disk")
@pytest.mark.parametrize("run", RECORDED, ids=lambda p: p.relative_to(ROOT / "runs").as_posix()[-40:])
def test_every_recorded_run_still_replays(run):
    rep = replay_run(run)
    assert rep.deterministic and rep.api_calls == 0 and rep.identical_steps == rep.steps


@needs_citylearn
def test_v12_scripted_matches_v9_on_24_hours_of_citylearn(tmp_path):
    from hyperbolic.sim import CityLearnSimulator

    out = {}
    for v in (9, 12):
        _, cfg = controller_settings(True, v)
        ctl = AgentController(ScriptedSupervisor(), Envelope(cfg), Budget(2.0), prompt_version=v)
        run_dir = tmp_path / f"v{v}"
        res = run_session(CityLearnSimulator(control=True), ctl, RunWriter(run_dir), hours=24, log=lambda *_: None,
                          sim_info={"kind": "citylearn", "control": True})
        assert res["steps"] == 24 and res["fallback_steps"] == 0
        out[v] = (load_jsonl(run_dir / "steps.jsonl"), load_jsonl(run_dir / "calls.jsonl"))
    (s9, c9), (s12, c12) = out[9], out[12]
    assert [s["actions"] for s in s9] == [s["actions"] for s in s12]
    for s, c in zip(s12, c9):
        assert s["shadow_strategy"] == json.loads(c["reply"]["text"])  # strategy_plan_v9 on the v9 observation
    for c in c12:
        _request_has_no_computed_action(c["request"])
        assert c["request"]["system"][0]["cache_control"] == {"type": "ephemeral"}
        assert system_text(c["request"]) == system_prompt_v12(cfg, BUILDINGS)
    rep = replay_run(tmp_path / "v12")
    assert rep.deterministic and rep.api_calls == 0 and rep.identical_steps == 24
