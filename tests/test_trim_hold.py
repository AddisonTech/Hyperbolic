"""The envelope's cooling trim hold (0.8.0): on, hold, ease, end, early end, logging and replay."""

import json

import pytest
from conftest import BUILDINGS, bstate, proposal
from fakes import FakeDistrict

from hyperbolic.envelope import Envelope, EnvelopeConfig, StepContext, parse_reply
from hyperbolic.model import Budget, ScriptedSupervisor
from hyperbolic.runner import AgentController, RunWriter, load_jsonl, replay_run, run_session

COLD, NEAR, AT = 22.5, 23.7, 24.0  # indoor C against a 24.0 C setpoint: 1.5 below, 0.3 below, at it


def step(t=10, **b1) -> StepContext:
    """Building_1 as given (indoor, occupied, cooling_base); the others at their setpoint."""
    return StepContext(time_step=t, buildings={b: bstate(**(b1 if b == "Building_1" else {})) for b in BUILDINGS})


def hold_rules(d):
    return [c for c in d.clamps if c.rule == "trim_hold"]


def actions(d):
    return [h["action"] for h in d.holds]


@pytest.fixture
def env():
    """A trim of 0.08 (cooling 0.32 against a 0.4 baseline) already started in a cold room."""
    e = Envelope(EnvelopeConfig())
    d = e.apply(proposal(Building_1={"cooling": 0.32}), step(indoor=COLD))
    assert actions(d) == ["start"] and not d.clamps and e.holds == {"Building_1": 0.08}
    return e


def test_a_trim_starts_and_is_recorded(env):
    assert env.trims["Building_1"] == pytest.approx(-0.08)


def test_hold_keeps_the_trim_while_the_room_is_more_than_half_a_degree_cold(env):
    d = env.apply(proposal(), step(indoor=22.8))  # null cooling: the held trim stays on
    assert d.actions["Building_1"]["cooling"] == pytest.approx(0.32)
    assert actions(d) == ["hold"] and len(hold_rules(d)) == 1
    d = env.apply(proposal(Building_1={"cooling": 0.47}), step(indoor=22.9, cooling_base=0.5))
    assert d.actions["Building_1"]["cooling"] == pytest.approx(0.42)  # follows the baseline, same depth
    c = hold_rules(d)[0]
    assert c.point == "Building_1.cooling" and c.requested == 0.47 and "more than 0.5 C below" in c.reason


def test_a_deeper_trim_is_allowed(env):
    d = env.apply(proposal(Building_1={"cooling": 0.3}), step(indoor=COLD))
    assert d.actions["Building_1"]["cooling"] == 0.3 and not d.clamps and not d.holds
    assert env.holds["Building_1"] == pytest.approx(0.1)


def test_within_half_a_degree_the_trim_eases_by_at_most_0_02_per_hour(env):
    d = env.apply(proposal(), step(indoor=NEAR))
    assert d.actions["Building_1"]["cooling"] == pytest.approx(0.34) and actions(d) == ["ease"]
    assert "eases off" in hold_rules(d)[0].reason
    for want in (0.36, 0.38):
        d = env.apply(proposal(Building_1={"cooling": 0.4}), step(indoor=NEAR))
        assert d.actions["Building_1"]["cooling"] == pytest.approx(want)
    d = env.apply(proposal(), step(indoor=NEAR))
    assert d.actions["Building_1"]["cooling"] is None and actions(d) == ["release"]
    assert env.holds == {}


def test_a_miss_smaller_than_rounding_is_not_clamped_but_still_held(env):
    d = env.apply(proposal(Building_1={"cooling": 0.3215}), step(indoor=COLD))  # 0.0015 short
    assert not d.clamps and env.holds["Building_1"] == pytest.approx(0.08)
    d = env.apply(proposal(Building_1={"cooling": 0.3245}), step(indoor=COLD))  # still measured from 0.08
    assert d.actions["Building_1"]["cooling"] == pytest.approx(0.32) and len(hold_rules(d)) == 1


@pytest.mark.parametrize("where, why", [
    ({"indoor": AT}, "at or above the setpoint"),
    ({"indoor": 24.6}, "at or above the setpoint"),
    ({"indoor": COLD, "occupied": False}, "unoccupied"),
    ({"indoor": COLD, "cooling_base": 0.0}, "no cooling to trim"),
])
def test_the_trim_ends_at_once(env, where, why):
    d = env.apply(proposal(), step(**where))
    assert actions(d) == ["end"] and why in d.holds[0]["reason"]
    assert d.actions["Building_1"]["cooling"] is None and not d.clamps and env.holds == {}


def test_a_trim_asked_for_where_the_hold_has_ended_goes_back_to_the_baseline(env):
    d = env.apply(proposal(Building_1={"cooling": 0.3}), step(indoor=AT))
    assert d.actions["Building_1"]["cooling"] == 0.4
    assert "trim ended" in hold_rules(d)[0].reason and env.holds == {}
    fresh = Envelope(EnvelopeConfig())  # no trim on yet: none may start in an empty room either
    d = fresh.apply(proposal(Building_1={"cooling": 0.3}), step(indoor=COLD, occupied=False))
    assert d.actions["Building_1"]["cooling"] == 0.4 and actions(d) == ["end"] and fresh.holds == {}


def _v6_reply(**b1) -> dict:
    reply = {"reason": "test"}
    for b in BUILDINGS:
        reply[b] = {"cooling": None, "dhw": None, "battery": None, "end_trim": None, **(b1 if b == "Building_1" else {})}
    p, err = parse_reply(json.dumps(reply), BUILDINGS, end_trim=True)
    assert err is None
    return p


def test_the_model_can_end_a_trim_early_only_with_a_reason(env):
    d = env.apply(_v6_reply(end_trim="Room heading for an outage, keep it cool"), step(indoor=COLD))
    assert d.actions["Building_1"]["cooling"] is None and not d.clamps
    assert d.holds == [{"building": "Building_1", "action": "end_early", "depth_before": 0.08, "depth_after": 0.0,
                        "reason": "Room heading for an outage, keep it cool"}]
    assert env.holds == {}


def test_an_early_end_that_still_asks_for_a_trim_is_brought_back_to_the_baseline(env):
    d = env.apply(_v6_reply(cooling=0.3, end_trim="done"), step(indoor=COLD))
    assert d.actions["Building_1"]["cooling"] == 0.4 and actions(d) == ["end_early"]
    assert "ended it early: done" in hold_rules(d)[0].reason


def test_end_trim_without_a_trim_on_does_nothing():
    e = Envelope(EnvelopeConfig())
    d = e.apply(_v6_reply(end_trim="nothing to end"), step(indoor=COLD))
    assert not d.holds and not d.clamps and d.status == "ok"


def test_every_hold_action_is_logged_in_the_decision(env):
    d = env.apply(proposal(), step(indoor=22.8))
    rec = d.as_dict()
    assert rec["status"] == "clamped" and rec["clamps"][0]["rule"] == "trim_hold"
    assert rec["holds"][0]["action"] == "hold" and rec["holds"][0]["depth_after"] == 0.08
    quiet = env.apply(proposal(Building_1={"cooling": 0.32}), step(indoor=22.8)).as_dict()
    assert "holds" not in quiet and quiet["status"] == "ok"  # nothing to record, no key


def test_fallback_forgets_the_hold(env):
    env.fallback(step(indoor=COLD), "test")
    assert env.holds == {}
    d = env.apply(proposal(), step(indoor=COLD))
    assert d.actions["Building_1"]["cooling"] is None and not d.holds


def test_deviation_and_comfort_rules_still_come_first():
    e = Envelope(EnvelopeConfig())
    d = e.apply(proposal(Building_1={"cooling": 0.1}), step(indoor=COLD))
    assert {c.rule for c in d.clamps} == {"deviation"} and e.holds["Building_1"] == pytest.approx(0.15)
    # Near the bottom of the band extra cooling is still refused, and the trim is untouched.
    d = e.apply(proposal(Building_1={"cooling": 0.5}), step(indoor=22.2))
    assert {c.rule for c in d.clamps} == {"comfort", "trim_hold"}
    assert d.actions["Building_1"]["cooling"] == pytest.approx(0.25)


def test_without_the_hold_the_0_7_0_rules_are_unchanged():
    e = Envelope(EnvelopeConfig.v070())
    e.apply(proposal(Building_1={"cooling": 0.32}), step(indoor=COLD))
    d = e.apply(proposal(), step(indoor=22.8))
    assert d.actions["Building_1"]["cooling"] is None and not d.clamps and not d.holds and e.holds == {}
    assert "holds" not in d.as_dict()


def test_older_runs_rebuild_their_rules_without_the_hold():
    old = EnvelopeConfig.v070().as_dict()
    for key in ("trim_hold", "trim_hold_c", "trim_release_step", "trim_min_depth"):
        old.pop(key)
    assert EnvelopeConfig.from_manifest(old) == EnvelopeConfig.v070()  # a 0.6.0 or 0.7.0 manifest
    assert EnvelopeConfig.from_manifest({}).trim_hold is False
    assert EnvelopeConfig.from_manifest(EnvelopeConfig().as_dict()) == EnvelopeConfig()


class ColdDistrict(FakeDistrict):
    """The fake district with a 25 C setpoint, so occupied rooms start a degree too cold and the
    scripted strategy trims them; trimming warms them (FakeDistrict's indoor model)."""

    def state(self):
        st = super().state()
        for s in st["buildings"].values():
            s["setpoint_c"] = 25.0
        return st


def _record_v6(run_dir):
    ctl = AgentController(ScriptedSupervisor(tokens=(5000, 780)), Envelope(EnvelopeConfig()), Budget(2.0),
                          prompt_version=6)
    run_session(ColdDistrict(), ctl, RunWriter(run_dir), hours=48, log=lambda *_: None)


def test_a_v6_run_with_hold_actions_replays_byte_for_byte(tmp_path):
    run = tmp_path / "v6"
    _record_v6(run)
    steps = load_jsonl(run / "steps.jsonl")
    kinds = {h["action"] for s in steps for h in s["decision"].get("holds", [])}
    assert {"start", "hold", "release"} <= kinds
    assert any(c["rule"] == "trim_hold" for s in steps for c in s["decision"]["clamps"])
    assert json.loads((run / "manifest.json").read_text(encoding="utf-8"))["envelope"]["trim_hold"] is True
    rep = replay_run(run)
    assert rep.deterministic and rep.api_calls == 0 and rep.identical_steps == 48, (rep.mismatched_steps, rep.error)
    replay_run(run, out_dir=tmp_path / "again")
    assert (tmp_path / "again" / "steps.jsonl").read_bytes() == (run / "steps.jsonl").read_bytes()


def test_a_run_replayed_under_other_hold_rules_is_detected(tmp_path):
    run = tmp_path / "v6"
    _record_v6(run)
    m = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    m["envelope"]["trim_release_step"] = 1.0  # release at once instead
    (run / "manifest.json").write_text(json.dumps(m), encoding="utf-8")
    assert not replay_run(run).deterministic
