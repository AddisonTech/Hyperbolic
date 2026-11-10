"""Prompt version 11 (0.14.0), blind mode: the version 10 observation without the suggestion, a system prompt
with no strategy, the envelope's own reply schema, the shadow strategy logged every hour and never sent,
scripted version 11 equal to scripted version 9, and the envelope and versions 1 to 10 unchanged."""

import dataclasses
import hashlib
import json
import re
from pathlib import Path

import pytest
from conftest import BUILDINGS, FIXTURES, needs_citylearn
from fakes import FakeDistrict
from test_prompt_v8 import _obs

from hyperbolic import district as dc
from hyperbolic import prompt as P
from hyperbolic.envelope import Envelope, EnvelopeConfig, proposal_json_schema
from hyperbolic.model import Budget, ScriptedSupervisor, StrategyParamsV9, strategy_plan_v9
from hyperbolic.prompt import BLIND_MODE, PROMPT_VERSION, build_request, observe, reply_json_schema, shadow_strategy, \
    system_prompt_v11, system_text
from hyperbolic.runner import AgentController, NullWriter, RunWriter, controller_settings, load_jsonl, replay_run, \
    run_session

ROOT = Path(__file__).parents[1]

# The envelope's source, as pinned in 0.13.0 (test_prompt_v10.py); 0.14.0 must not change a byte.
ENVELOPE_SHA256 = "4527158b52613a5657e4050002de359898c23dd52f2917f65b7c4aa9efee356d"
# Taken from 0.13.0 before version 11 was written: the version 10 system prompt (default rules, these
# three buildings) and its reply schema. Versions 1 to 9 are pinned in test_prompt_v10.py.
V10_SYSTEM_SHA256 = "7cdb34968512a8fe1c62b0bc6a756c8523e63d7f4ef7358d26e95ba2d33a9b78"
V10_SCHEMA_SHA256 = "1cc2083d53df7a3eecb9e349da079fb1e8a913e129cfadc134b4cb5300dccf79"
BANNED = ("suggestion", "strategy")


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def _numbers(text: str) -> set[float]:
    return {float(x) for x in re.findall(r"(?<![\w.])-?\d+(?:\.\d+)?", text)}


def _strategy_values() -> set[float]:
    """Every number in StrategyParamsV9, and the two ramp ends the earlier prompts printed from them."""
    sp = StrategyParamsV9()
    vals = {float(v) for v in dataclasses.asdict(sp).values() if isinstance(v, (int, float)) and not isinstance(v, bool)}
    return vals | {sp.cold_margin_c + sp.cold_ramp_c, sp.warm_margin_c + sp.warm_ramp_c}


def _allowed_numbers(cfg: EnvelopeConfig) -> set[float]:
    """Numbers the version 11 prompt may print, each from something other than the strategy: the envelope's
    limits, the forecast horizons and the 24 hour outlook, the reason length rule, the building count and
    the dataset's year."""
    env = {float(v) for v in cfg.as_dict().values() if isinstance(v, (int, float)) and not isinstance(v, bool)}
    return env | {float(h) for h in dc.FORECAST_HORIZONS_H} | {24.0, float(dc.REASON_TARGET_CHARS),
                                                               float(dc.REASON_MAX_CHARS), float(len(BUILDINGS)), 2023.0}


def _strings(x):
    if isinstance(x, dict):
        for k, v in x.items():
            yield str(k)
            yield from _strings(v)
    elif isinstance(x, list):
        for v in x:
            yield from _strings(v)
    elif isinstance(x, str):
        yield x


def _request_has_no_strategy(req: dict) -> None:
    text = json.dumps(req).lower()
    for word in BANNED:
        assert word not in text, word
    assert "deviation_reason" not in text


# -- the observation, the prompt and the schema ------------------------------------------------


def test_v11_is_selectable_and_not_the_default():
    assert PROMPT_VERSION == 9 and BLIND_MODE == 11 and P.PROMPT_VERSIONS[-2:] == (10, 11)
    assert controller_settings(False, 11) == (11, EnvelopeConfig())
    assert not P.free_mode(11) and P.free_mode(10)


def test_v11_observation_is_v10_without_the_suggestion():
    st, ctx, look, env, _ = _obs(version=10)
    v10 = observe(10, st, ctx, None, look, env)
    v11 = observe(11, st, ctx, None, look, env)
    assert set(v11) == set(v10) - {"suggestion_reason"}
    for k in v11:
        if k != "buildings":
            assert v11[k] == v10[k], k
    for b in BUILDINGS:
        want = {k: v for k, v in v10["buildings"][b].items() if k != "suggestion"}
        assert v11["buildings"][b] == want
    # what version 10 added beyond version 9 stays: the solar forecast and the ratings
    assert "solar_forecast" in v11 and "cooling_power_kw" in v11["buildings"]["Building_1"]


def test_v11_schema_is_the_envelopes_with_end_trim():
    s = reply_json_schema(BUILDINGS, 11)
    assert s == proposal_json_schema(BUILDINGS, True)
    for b in BUILDINGS:
        assert s["properties"][b]["required"] == ["cooling", "dhw", "battery", "end_trim"]
        assert "deviation_reason" not in s["properties"][b]["properties"]
    st, ctx, look, env, v11 = _obs(version=11)
    assert build_request(v11, env.config, BUILDINGS, "sonnet", prompt_version=11)["output_config"]["format"]["schema"] == s


def test_v11_system_prompt_states_no_strategy():
    cfg = EnvelopeConfig()
    text = system_prompt_v11(cfg, BUILDINGS)
    flat = " ".join(text.split())
    low = flat.lower()
    for word in (*BANNED, "deviation_reason", "free mode", "pre-cool", "precool", "top-price hours", "evenly"):
        assert word not in low, word
    assert "null means baseline_action" in flat
    for phrase in ("Goals, in this order", "What you see:", "cooling_range and battery_range", "end_trim",
                   "Clamps are logged against you", "Reply with one JSON object only"):
        assert phrase in flat, phrase
    assert chr(0x2014) not in text and chr(0x2013) not in text
    # every number it prints comes from the envelope, the forecasts, the reply rules, the district or the
    # dataset, and none of the strategy's own numbers appears
    nums = _numbers(text)
    assert nums <= _allowed_numbers(cfg), nums - _allowed_numbers(cfg)
    strategy_only = _strategy_values() - _allowed_numbers(cfg)
    assert strategy_only and not (nums & strategy_only), nums & strategy_only


def test_v11_system_prompt_does_not_depend_on_strategy_params(monkeypatch):
    before = system_prompt_v11(EnvelopeConfig(), BUILDINGS)
    odd = dataclasses.replace(StrategyParamsV9(), cold_margin_c=0.77, cold_trim=0.33, shave=0.61, soc_target=0.71,
                              charge_rate=0.27, evening_reserve=0.09, warm_margin_c=1.9, warm_boost=0.13)
    monkeypatch.setattr(P, "StrategyParamsV9", lambda: odd)
    assert system_prompt_v11(EnvelopeConfig(), BUILDINGS) == before


def test_v11_observation_carries_no_strategy_but_shave_now(monkeypatch):
    """Nothing in the observation names the strategy, and no string in it holds one of the strategy's own
    numbers. Its values do not depend on StrategyParamsV9, except peak.shave_now, kept from version 10:
    true when the district load is at least the strategy's shave share of today's forecast peak."""
    st, ctx, look, env, v11 = _obs(version=11)
    low = json.dumps(v11).lower()
    assert not any(w in low for w in BANNED)
    strategy_only = _strategy_values() - _allowed_numbers(EnvelopeConfig())
    for s in _strings(v11):
        assert not (_numbers(s) & strategy_only), s
    odd = dataclasses.replace(StrategyParamsV9(), shave=1.5, cold_margin_c=0.77, evening_reserve=0.09)
    monkeypatch.setattr(P, "StrategyParamsV9", lambda: odd)
    patched = observe(11, st, ctx, None, look, env)
    assert v11["peak"].pop("shave_now") is True and patched["peak"].pop("shave_now") is False
    assert patched == v11


def test_a_v11_request_names_no_strategy():
    st, ctx, look, env, v11 = _obs(version=11)
    for cache in (False, True):
        req = build_request(v11, env.config, BUILDINGS, "sonnet", prompt_version=11, prompt_cache=cache)
        _request_has_no_strategy(req)
        assert system_text(req) == system_prompt_v11(env.config, BUILDINGS)


def test_v11_system_prompt_is_long_enough_to_cache():
    # Sonnet 5.5 and Haiku 5.5 cache a prefix of 512 tokens or more. Plain English runs about 4 characters a
    # token, so this is about 720 tokens before the reply schema; the smoke test reads the cache hits.
    assert len(system_prompt_v11(EnvelopeConfig(), BUILDINGS)) >= 4 * 512


# -- the shadow strategy -----------------------------------------------------------------------


def test_shadow_strategy_is_strategy_plan_v9_exactly():
    st, ctx, look, env, v9 = _obs(version=9)
    v11 = observe(11, st, ctx, None, look, env)
    v10 = observe(10, st, ctx, None, look, env)
    shadow = shadow_strategy(v11)
    assert shadow == strategy_plan_v9(v9)
    assert shadow["reason"] == v9["strategy_reason"] == v10["suggestion_reason"]
    for b in BUILDINGS:
        assert {d: shadow[b][d] for d in ("cooling", "dhw", "battery")} == v9["buildings"][b]["strategy"] \
            == v10["buildings"][b]["suggestion"]
        assert shadow[b]["end_trim"] is None


def _run(version, hours=48, run_dir=None):
    w = RunWriter(run_dir) if run_dir else NullWriter()
    ctl = AgentController(ScriptedSupervisor(), Envelope(EnvelopeConfig()), Budget(2.0), prompt_version=version)
    res = run_session(FakeDistrict(), ctl, w, hours=hours, log=lambda *_: None)
    assert res["fallback_steps"] == 0
    return res, (load_jsonl(run_dir / "steps.jsonl") if run_dir else w.steps)


def test_scripted_v11_matches_scripted_v9_and_logs_the_shadow_every_hour(tmp_path):
    _, v9 = _run(9, run_dir=tmp_path / "v9")
    _, v11 = _run(11, run_dir=tmp_path / "v11")
    v9_replies = [json.loads(c["reply"]["text"]) for c in load_jsonl(tmp_path / "v9" / "calls.jsonl")]
    for a, b, plan in zip(v9, v11, v9_replies):
        assert a["actions"] == b["actions"] and a["decision"]["actions"] == b["decision"]["actions"]
        assert "shadow_strategy" not in a and "deviations" not in b
        # the shadow is the version 9 strategy on the version 9 observation of the same hour
        assert b["shadow_strategy"] == plan
    # scripted version 11 sends the shadow, so its reply each hour is the logged shadow
    for c, s in zip(load_jsonl(tmp_path / "v11" / "calls.jsonl"), v11):
        assert json.loads(c["reply"]["text"]) == s["shadow_strategy"]
        _request_has_no_strategy(c["request"])


class NullSupervisor:
    """Replies null everywhere: a model that never acts, so the shadow is not what was sent."""

    kind = "scripted"
    model_key = "sonnet"

    def call(self, step, request):
        from hyperbolic.model import CallResult, observation_from_request

        obs = observation_from_request(request)
        reply = {"reason": "Hold."}
        reply.update({b: {"cooling": None, "dhw": None, "battery": None, "end_trim": None} for b in obs["buildings"]})
        return CallResult(json.dumps(reply), stop_reason="end_turn", model="scripted")


def test_the_shadow_follows_the_state_a_model_left_and_replays(tmp_path):
    run = tmp_path / "null"
    ctl = AgentController(NullSupervisor(), Envelope(EnvelopeConfig()), Budget(2.0), prompt_version=11)
    run_session(FakeDistrict(), ctl, RunWriter(run), hours=48, log=lambda *_: None)
    steps = load_jsonl(run / "steps.jsonl")
    calls = load_jsonl(run / "calls.jsonl")
    for s, c in zip(steps, calls):
        from hyperbolic.model import observation_from_request

        assert s["shadow_strategy"] == strategy_plan_v9(observation_from_request(c["request"]))
    assert any(s["shadow_strategy"][b]["battery"] for s in steps for b in BUILDINGS)  # the strategy acts; the model did not
    rep = replay_run(run)
    assert rep.deterministic and rep.identical_steps == 48 and rep.api_calls == 0
    # a replay whose shadow would differ is caught
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


def test_version_10_prompt_and_schema_are_byte_identical():
    assert _sha(P.system_prompt_v10(EnvelopeConfig(), BUILDINGS)) == V10_SYSTEM_SHA256
    assert _sha(json.dumps(reply_json_schema(BUILDINGS, 10), sort_keys=True)) == V10_SCHEMA_SHA256


def test_scripted_v10_still_matches_v9():
    _, v9 = _run(9)
    _, v10 = _run(10)
    assert [s["actions"] for s in v9] == [s["actions"] for s in v10]
    assert all(s["deviations"] == {} and "shadow_strategy" not in s for s in v10)


@pytest.mark.parametrize("name", ["agent_fixture", "baseline_fixture"])
def test_recorded_fixture_runs_still_replay(name):
    rep = replay_run(FIXTURES / "runs" / name)
    assert rep.deterministic and rep.api_calls == 0


V10_RUNS = sorted((ROOT / "runs" / "v10").glob("*_agent_citylearn_*"))


@pytest.mark.skipif(not V10_RUNS, reason="the 0.13.0 free-mode runs are not on disk")
@pytest.mark.parametrize("run", V10_RUNS, ids=lambda p: p.name[-16:])
def test_the_0130_free_mode_runs_still_replay(run):
    rep = replay_run(run)
    assert rep.deterministic and rep.api_calls == 0 and rep.identical_steps == rep.steps


@needs_citylearn
def test_v11_scripted_matches_v9_on_24_hours_of_citylearn(tmp_path):
    from hyperbolic.sim import CityLearnSimulator

    out = {}
    for v in (9, 11):
        _, cfg = controller_settings(True, v)
        ctl = AgentController(ScriptedSupervisor(), Envelope(cfg), Budget(2.0), prompt_version=v)
        run_dir = tmp_path / f"v{v}"
        res = run_session(CityLearnSimulator(control=True), ctl, RunWriter(run_dir), hours=24, log=lambda *_: None,
                          sim_info={"kind": "citylearn", "control": True})
        assert res["steps"] == 24 and res["fallback_steps"] == 0
        out[v] = (load_jsonl(run_dir / "steps.jsonl"), load_jsonl(run_dir / "calls.jsonl"))
    (s9, c9), (s11, c11) = out[9], out[11]
    assert [s["actions"] for s in s9] == [s["actions"] for s in s11]
    for s, c in zip(s11, c9):
        assert s["shadow_strategy"] == json.loads(c["reply"]["text"])  # strategy_plan_v9 on the v9 observation
    for c in c11:
        _request_has_no_strategy(c["request"])
        assert c["request"]["system"][0]["cache_control"] == {"type": "ephemeral"}
    rep = replay_run(tmp_path / "v11")
    assert rep.deterministic and rep.api_calls == 0 and rep.identical_steps == 24
