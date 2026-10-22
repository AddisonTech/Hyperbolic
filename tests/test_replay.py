"""Replay from recorded CityLearn runs: deterministic, zero API or simulator calls, tamper evident."""

import json
import shutil

import pytest

import hyperbolic.model as model
from hyperbolic.runner import load_jsonl, replay_run


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("replay must not construct an API client")

    monkeypatch.setattr(model, "LiveSupervisor", boom)


def test_recorded_agent_run_replays_identically(fixture_runs):
    _, agent = fixture_runs
    rep = replay_run(agent)
    assert rep.steps == 36
    assert rep.deterministic, (rep.mismatched_steps, rep.error)
    assert rep.api_calls == 0
    assert rep.calls == len(load_jsonl(agent / "calls.jsonl"))
    assert rep.clamped_steps > 0 and rep.fallback_steps > 0


def test_recorded_baseline_run_replays_identically(fixture_runs):
    base, _ = fixture_runs
    assert replay_run(base).deterministic


def test_replay_needs_no_simulator(fixture_runs, monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "citylearn", None)  # importing CityLearn would now fail
    _, agent = fixture_runs
    assert replay_run(agent).deterministic


def test_replay_twice_writes_identical_files(fixture_runs, tmp_path):
    _, agent = fixture_runs
    replay_run(agent, out_dir=tmp_path / "r1")
    replay_run(agent, out_dir=tmp_path / "r2")
    for name in ("steps.jsonl", "calls.jsonl"):
        assert (tmp_path / "r1" / name).read_bytes() == (tmp_path / "r2" / name).read_bytes()
    orig = [s["decision"] for s in load_jsonl(agent / "steps.jsonl")]
    again = [s["decision"] for s in load_jsonl(tmp_path / "r1" / "steps.jsonl")]
    assert orig == again


def test_changed_reply_is_detected(fixture_runs, tmp_path):
    _, agent = fixture_runs
    copy = tmp_path / "tampered"
    shutil.copytree(agent, copy)
    calls = load_jsonl(copy / "calls.jsonl")
    reply = json.loads(calls[30]["reply"]["text"])
    reply["Building_2"]["battery"] = -0.3
    calls[30]["reply"]["text"] = json.dumps(reply)
    (copy / "calls.jsonl").write_text("".join(json.dumps(c) + "\n" for c in calls), encoding="utf-8")
    rep = replay_run(copy)
    assert not rep.deterministic
    assert 30 in rep.mismatched_steps
    # The next hour's request carries hour 30's decision, so replay stops there.
    assert rep.error and "step 31" in rep.error


def test_changed_envelope_config_is_detected(fixture_runs, tmp_path):
    _, agent = fixture_runs
    copy = tmp_path / "cfg"
    shutil.copytree(agent, copy)
    m = json.loads((copy / "manifest.json").read_text())
    m["envelope"]["battery_rate_per_step"] = 0.2
    (copy / "manifest.json").write_text(json.dumps(m))
    # The system prompt states the limits, so the request hash changes and replay stops at hour 0.
    rep = replay_run(copy)
    assert not rep.deterministic
    assert "request differs" in rep.error and 0 in rep.mismatched_steps


def _record_v4(run_dir):
    from fakes import FakeDistrict

    from hyperbolic.envelope import Envelope, EnvelopeConfig
    from hyperbolic.model import Budget, ScriptedSupervisor
    from hyperbolic.runner import AgentController, RunWriter, run_session

    ctl = AgentController(ScriptedSupervisor(tokens=(2800, 200)), Envelope(EnvelopeConfig()), Budget(2.0),
                          prompt_version=4)
    run_session(FakeDistrict(), ctl, RunWriter(run_dir), hours=48, log=lambda *_: None)


def test_recorded_v4_run_with_the_reference_and_spread_check_replays_identically(tmp_path):
    run = tmp_path / "v4"
    _record_v4(run)
    steps = load_jsonl(run / "steps.jsonl")
    rules = {c["rule"] for s in steps for c in s["decision"]["clamps"]}
    calls = load_jsonl(run / "calls.jsonl")
    assert '"reference_action"' in calls[0]["request"]["messages"][0]["content"]
    rep = replay_run(run)
    assert rep.deterministic and rep.api_calls == 0 and rep.identical_steps == 48, (rep.mismatched_steps, rep.error)
    replay_run(run, out_dir=tmp_path / "again")
    assert (tmp_path / "again" / "steps.jsonl").read_bytes() == (run / "steps.jsonl").read_bytes()
    assert rules <= {"spread", "peak", "soc", "rate", "deviation", "comfort"}


def test_a_changed_reference_policy_is_detected(tmp_path, monkeypatch):
    import hyperbolic.model as m
    from hyperbolic.model import RuleParams

    run = tmp_path / "v4"
    _record_v4(run)
    # The reference action is part of every recorded request, so a different rule-based plan
    # cannot replay silently.
    original = m.rule_plan_v3
    monkeypatch.setattr("hyperbolic.prompt.rule_plan_v3",
                        lambda obs, p=None: original(obs, RuleParams(charge_rate=0.05, charge_rank=1.0,
                                                                     charge_max_signal=1.0)))
    rep = replay_run(run)
    assert not rep.deterministic and "request differs" in rep.error
