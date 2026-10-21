"""Agent controller on the mock simulator: fallback paths, budget stop, key handling."""

import json
from types import SimpleNamespace

import pytest

from hyperbolic.envelope import Envelope
from hyperbolic.mock import MockBoptest
from hyperbolic.model import (
    Budget,
    CallResult,
    KeyMissing,
    LiveSupervisor,
    ScriptedSupervisor,
    call_cost_usd,
    resolve_api_key,
    worst_case_cost_usd,
)
from hyperbolic.runner import AgentController, RunWriter, load_jsonl, run_session

quiet = lambda *_: None  # noqa: E731


class FakeSupervisor:
    kind = "fake"

    def __init__(self, replies, model_key="haiku", tokens=(0, 0)):
        self.replies = list(replies)
        self.model_key = model_key
        self.tokens = tokens
        self.calls = 0

    def call(self, step, request):
        self.calls += 1
        r = self.replies[min(step, len(self.replies) - 1)]
        if isinstance(r, Exception):
            raise r
        if isinstance(r, CallResult):
            return r
        return CallResult(r, *self.tokens, stop_reason="end_turn")


def good_reply(heat=20.5):
    z = {"heat_c": heat, "cool_c": None}
    return json.dumps({"reason": "hold", "nor": z, "eas": z, "sou": z, "wes": z, "cor": z, "supply_air_c": None})


def run(tmp_path, sup, hours=10, budget=2.0, name="a"):
    ctl = AgentController(supervisor=sup, envelope=Envelope(), budget=Budget(limit_usd=budget))
    res = run_session(MockBoptest(), ctl, RunWriter(tmp_path / name), "typical_heat_day", hours=hours,
                      sim_info={"kind": "mock"}, log=quiet)
    return res, load_jsonl(tmp_path / name / "steps.jsonl"), load_jsonl(tmp_path / name / "calls.jsonl")


def test_invalid_reply_falls_back_to_baseline(tmp_path):
    sup = FakeSupervisor([good_reply()] * 7 + ["{broken", good_reply()])
    res, steps, _ = run(tmp_path, sup)
    s = steps[7]
    assert s["decision"]["status"] == "fallback"
    assert "invalid reply" in s["decision"]["fallback"]
    assert all(v == 0 for k, v in s["u"].items() if k.endswith("_activate"))
    assert steps[8]["decision"]["status"] in ("ok", "clamped")
    assert res["fallback_steps"] == 1


def test_missing_reply_and_client_exception_fall_back(tmp_path):
    sup = FakeSupervisor([good_reply()] * 7 + [CallResult(None, error="timeout"), RuntimeError("socket closed"),
                                                good_reply()])
    res, steps, calls = run(tmp_path, sup)
    assert steps[7]["decision"]["fallback"] == "no usable reply: timeout"
    assert "client error: RuntimeError" in steps[8]["decision"]["fallback"]
    assert res["fallback_steps"] == 2
    assert len(calls) == 10  # every attempt is recorded, including failed ones


def test_scripted_faults_exercise_every_path(tmp_path):
    faults = {6: "too_fast", 7: "out_of_range", 8: "malformed", 9: "below_comfort", 10: "missing", 11: "schema"}
    res, steps, _ = run(tmp_path, ScriptedSupervisor(faults=faults), hours=14)
    status = {s["step"]: s["decision"]["status"] for s in steps}
    assert status[6] == status[7] == status[9] == "clamped"
    assert status[8] == status[10] == status[11] == "fallback"
    rules_7 = {c["rule"] for c in steps[7]["decision"]["clamps"]}
    assert "range" in rules_7
    rules_9 = {c["rule"] for c in steps[9]["decision"]["clamps"]}
    assert "comfort" in rules_9


def test_budget_stop_halts_model_calls_and_falls_back(tmp_path):
    # Each call reports 200k input and 20k output tokens on haiku: $0.03 per call.
    sup = FakeSupervisor([good_reply()], tokens=(200_000, 20_000))
    per_call = call_cost_usd("haiku", 200_000, 20_000)
    res, steps, calls = run(tmp_path, sup, hours=12, budget=0.10)
    assert res["budget_stopped"] is True
    assert res["cost_usd"] <= 0.10 + per_call  # spent is checked before every call
    assert sup.calls == len(calls) and sup.calls < 12
    stopped = [s for s in steps if s["call"] is None]
    assert stopped and all("budget stop" in s["decision"]["fallback"] for s in stopped)
    # Once stopped it stays stopped.
    first = stopped[0]["step"]
    assert all(s["call"] is None for s in steps if s["step"] >= first)


def test_budget_checks_worst_case_before_calling(tmp_path):
    sup = FakeSupervisor([good_reply()])
    res, steps, calls = run(tmp_path, sup, hours=3, budget=0.0001)
    assert sup.calls == 0 and calls == []
    assert res["budget_stopped"] and res["cost_usd"] == 0.0


def test_worst_case_cost_is_an_upper_bound():
    req = {"model": "x", "max_tokens": 2000, "messages": [{"role": "user", "content": "a" * 9000}]}
    assert worst_case_cost_usd("haiku", req) >= call_cost_usd("haiku", 3000, 2000)
    assert worst_case_cost_usd("sonnet", req) > worst_case_cost_usd("haiku", req)


def test_key_resolution_order():
    assert resolve_api_key({"HYPERBOLIC_ANTHROPIC_KEY": "a", "TRIAGE_ANTHROPIC_KEY": "b"}) == (
        "a", "HYPERBOLIC_ANTHROPIC_KEY")
    assert resolve_api_key({"HYPERBOLIC_ANTHROPIC_KEY": "  ", "TRIAGE_ANTHROPIC_KEY": "b"}) == (
        "b", "TRIAGE_ANTHROPIC_KEY")
    with pytest.raises(KeyMissing):
        resolve_api_key({})


def _fake_response(text, stop="end_turn", inp=2500, out=150):
    return SimpleNamespace(
        content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(input_tokens=inp, output_tokens=out, cache_read_input_tokens=0,
                              cache_creation_input_tokens=0),
        stop_reason=stop,
        model="claude-haiku-5-5",
    )


def test_live_supervisor_path_without_network(tmp_path, monkeypatch):
    secret = "sk-test-DO-NOT-LOG-1234567890"
    monkeypatch.setenv("HYPERBOLIC_ANTHROPIC_KEY", secret)
    sup = LiveSupervisor("haiku")
    seq = [_fake_response(good_reply())] * 3 + [_fake_response("", stop="refusal"),
                                                _fake_response('{"reason": "cut', stop="max_tokens")]
    sent = []

    def create(**kwargs):
        sent.append(kwargs)
        return seq[min(len(sent) - 1, len(seq) - 1)]

    monkeypatch.setattr(sup._client.messages, "create", create)
    res, steps, calls = run(tmp_path, sup, hours=5)
    assert sent[0]["model"] == "claude-haiku-5-5"
    assert sent[0]["output_config"]["format"]["type"] == "json_schema"
    assert steps[3]["decision"]["fallback"] == "no usable reply: model declined the request"
    assert "max_tokens" in steps[4]["decision"]["fallback"]
    assert res["cost_usd"] == pytest.approx(5 * call_cost_usd("haiku", 2500, 150))
    for f in (tmp_path / "a").iterdir():
        assert secret not in f.read_text(encoding="utf-8"), f.name


def test_sonnet_selectable(tmp_path, monkeypatch):
    monkeypatch.setenv("HYPERBOLIC_ANTHROPIC_KEY", "sk-test")
    sup = LiveSupervisor("sonnet")
    sent = []
    monkeypatch.setattr(sup._client.messages, "create",
                        lambda **kw: sent.append(kw) or _fake_response(good_reply()))
    run(tmp_path, sup, hours=1)
    assert sent[0]["model"] == "claude-sonnet-5-5"
