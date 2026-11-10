"""scripts/analyze_free_mode.py (0.13.0): classes of a free-mode run's departures, the put-back replays
with zero model calls, and the control replay reproducing the run. From 0.14.0 the same for a blind-mode
run against its logged shadow strategy, and the agreement measure."""

import json
import sys
from pathlib import Path

import pytest
from conftest import needs_citylearn

sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))

import analyze_free_mode as fm  # noqa: E402

from hyperbolic.model import CallResult, ScriptedSupervisor, observation_from_request  # noqa: E402


class PrecoolingSupervisor:
    """The suggestion, except: cooling 0.05 above it before the top-price hours, and the battery charged
    0.02 more in hours 2 and 3, each with a reason; with slip_at, also the tank at 0.01 in Building_1 in that
    hour with no reason, which the free-mode check rejects."""

    kind = "scripted"
    model_key = "haiku"

    def __init__(self, slip_at=None):
        self.slip_at = slip_at

    def call(self, step, request):
        obs = observation_from_request(request)
        reply = json.loads(ScriptedSupervisor().call(step, request).text)
        pp = obs["price_plan"]
        before_top = not pp["flat_24h"] and not pp["top_price_now"] and bool(pp["top_price_hours_ahead"])
        for b, s in obs["buildings"].items():
            base = s["baseline_action"]["cooling"]
            rng = s["cooling_range"]
            if before_top and rng and base is not None:
                cur = base if reply[b]["cooling"] is None else reply[b]["cooling"]
                up = min(round(cur + 0.05, 3), rng[1])
                if up > cur + 0.01:
                    reply[b]["cooling"] = up
                    reply[b]["deviation_reason"] = "pre-cool while cheap to cut cost at the top price"
            if step in (2, 3) and b == "Building_2":
                reply[b]["battery"] = round((reply[b]["battery"] or 0.0) + 0.02, 3)
                reply[b]["deviation_reason"] = "charge a little more in a cheap hour"
            if step == self.slip_at and b == "Building_1":
                reply[b]["dhw"] = 0.01
                reply[b]["deviation_reason"] = None
        return CallResult(json.dumps(reply), stop_reason="end_turn", model="scripted")


class BlindPrecoolingSupervisor:
    """Blind mode (version 11): the shadow strategy, except cooling 0.05 above it before the top-price
    hours, and the battery left at null in hours 2 and 3 in Building_2."""

    kind = "scripted"
    model_key = "sonnet"

    def call(self, step, request):
        obs = observation_from_request(request)
        reply = json.loads(ScriptedSupervisor().call(step, request).text)
        assert "suggestion" not in obs["buildings"]["Building_1"]
        pp = obs["price_plan"]
        before_top = not pp["flat_24h"] and not pp["top_price_now"] and bool(pp["top_price_hours_ahead"])
        for b, s in obs["buildings"].items():
            base, rng = s["baseline_action"]["cooling"], s["cooling_range"]
            if before_top and rng and base is not None:
                cur = base if reply[b]["cooling"] is None else reply[b]["cooling"]
                up = min(round(cur + 0.05, 3), rng[1])
                if up > cur + 0.01:
                    reply[b]["cooling"] = up
            if step in (2, 3) and b == "Building_2":
                reply[b]["battery"] = None
        return CallResult(json.dumps(reply), stop_reason="end_turn", model="scripted")


def _blind_fake_run(tmp_path, supervisor, hours=48):
    from fakes import FakeDistrict

    from hyperbolic.envelope import Envelope, EnvelopeConfig
    from hyperbolic.model import Budget
    from hyperbolic.runner import AgentController, RunWriter, run_session

    run = tmp_path / "blind"
    ctl = AgentController(supervisor, Envelope(EnvelopeConfig()), Budget(2.0), prompt_version=11)
    run_session(FakeDistrict(), ctl, RunWriter(run), hours=hours, log=lambda *_: None)
    return run


def test_blind_reference_is_the_shadow_strategy(tmp_path):
    from hyperbolic.model import strategy_plan_v9

    run = _blind_fake_run(tmp_path, ScriptedSupervisor("sonnet"))
    assert fm.check_shadow(run) == 48
    rec = fm.load_jsonl(run / "calls.jsonl")[20]
    obs = observation_from_request(rec["request"])
    assert fm.is_blind(obs)
    plan = strategy_plan_v9(obs)
    assert fm.suggestion_of(obs) == {b: {d: plan[b][d] for d in ("cooling", "dhw", "battery")} for b in obs["buildings"]}
    # scripted version 11 sends the shadow: no departure, full agreement, nothing rejected
    assert fm.deviations(run) == [] and fm.departures_of(run) == set() and fm.rejected_of(run) == set()
    agr = fm.agreement(run)
    assert agr["building_hours"] == 144 and agr["unusable_building_hours"] == 0
    assert agr["share"] == {"cooling": 1.0, "dhw": 1.0, "battery": 1.0, "all": 1.0}


def test_blind_agreement_counts_each_device_against_the_shadow(tmp_path):
    run = _blind_fake_run(tmp_path, BlindPrecoolingSupervisor())
    steps = {s["step"]: s for s in fm.load_jsonl(run / "steps.jsonl")}
    calls = fm.load_jsonl(run / "calls.jsonl")
    want = {"cooling": 0, "dhw": 0, "battery": 0, "all": 0}
    for c in calls:
        obs = observation_from_request(c["request"])
        reply, shadow = json.loads(c["reply"]["text"]), steps[c["step"]]["shadow_strategy"]
        for b, s in obs["buildings"].items():
            base = s["baseline_action"]
            ok = {}
            for d, tol in (("cooling", 0.002), ("dhw", 0.005), ("battery", 0.005)):
                a = base[d] if reply[b][d] is None else reply[b][d]
                r = base[d] if shadow[b][d] is None else shadow[b][d]
                ok[d] = abs(a - r) <= tol + 1e-9
                want[d] += ok[d]
            want["all"] += all(ok.values())
    agr = fm.agreement(run)
    assert agr["agree"] == want and agr["building_hours"] == 144
    assert agr["share"]["dhw"] == 1.0 and agr["share"]["cooling"] < 1.0
    # the null battery is a departure only where the shadow moves the battery
    battery = {(r["step"], r["building"]) for r in fm.deviations(run) if r["device"] == "battery"}
    assert battery <= {(2, "Building_2"), (3, "Building_2")}
    assert all(r["reason"] is None for r in fm.deviations(run))


def test_blind_agreement_leaves_out_unusable_replies_and_counts_end_trim(tmp_path):
    class Odd(BlindPrecoolingSupervisor):
        def call(self, step, request):
            if step == 5:
                return CallResult('{"reason": "cut off', stop_reason="end_turn", model="scripted")
            reply = json.loads(ScriptedSupervisor().call(step, request).text)
            if step == 6:
                reply["Building_3"]["end_trim"] = "room is fine"
                reply["Building_3"]["cooling"] = None
            return CallResult(json.dumps(reply), stop_reason="end_turn", model="scripted")

    run = _blind_fake_run(tmp_path, Odd(), hours=12)
    agr = fm.agreement(run)
    assert agr["unusable_building_hours"] == 3 and agr["building_hours"] == 33
    assert agr["agree"]["cooling"] == 32 and agr["agree"]["dhw"] == 33 and agr["agree"]["battery"] == 33
    assert fm.deviations(run) and fm.check_shadow(run) == 12


def test_a_changed_shadow_log_is_caught(tmp_path):
    run = _blind_fake_run(tmp_path, ScriptedSupervisor("sonnet"), hours=12)
    lines = (run / "steps.jsonl").read_text(encoding="utf-8").splitlines()
    rec = json.loads(lines[7])
    rec["shadow_strategy"]["Building_1"]["battery"] = 0.5
    lines[7] = json.dumps(rec)
    (run / "steps.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(ValueError):
        fm.check_shadow(run)


@needs_citylearn
def test_attribution_on_a_recorded_blind_mode_run(tmp_path):
    from hyperbolic import months as mo
    from hyperbolic.envelope import Envelope, EnvelopeConfig
    from hyperbolic.model import Budget
    from hyperbolic.runner import AgentController, RunWriter, run_session
    from hyperbolic.sim import CityLearnSimulator

    month = mo.month("tuning-07")
    run = tmp_path / "run"
    ctl = AgentController(BlindPrecoolingSupervisor(), Envelope(EnvelopeConfig()), Budget(2.0), prompt_version=11)
    res = run_session(CityLearnSimulator(control=True, schema=mo.month_schema(month, tmp_path / "m")), ctl,
                      RunWriter(run), hours=36, log=lambda *_: None, sim_info={"kind": "citylearn", "control": True},
                      dataset=month.dataset)
    assert res["fallback_steps"] == 0
    assert fm.check_shadow(run) == 36 and fm.rejected_of(run) == set()
    rows = fm.deviations(run)
    kinds = {r["class"] for r in rows}
    assert "precool" in kinds and kinds <= set(fm.CLASSES)
    assert all(r["reason"] is None for r in rows)
    results = fm.attribute(run, rows, jobs=4)
    rep = fm.report(run, rows, results)
    assert rep["control_reproduces"] and rep["all_equals_strategy"]
    assert all(r["fallback"] == 0 for r in results.values())
    assert "rejected hours" not in results and "reasoned" not in results
    pre = rep["classes"]["precool"]
    assert pre["reasons_given"] == 0 and pre["claims"] == {}


def test_claims_read_the_hypothesis():
    assert fm.claims("pre-cool while cheap to cut cost at the top price") == ["cost"]
    assert set(fm.claims("shave the evening peak, keep comfort")) == {"peak", "comfort"}
    assert fm.claims(None) == []


def test_needs_a_free_mode_observation():
    with pytest.raises(ValueError):
        fm.suggestion_of({"buildings": {"Building_1": {"strategy": {}}}})


@needs_citylearn
def test_attribution_on_a_recorded_free_mode_run(tmp_path):
    from hyperbolic import months as mo
    from hyperbolic.envelope import Envelope, EnvelopeConfig
    from hyperbolic.model import Budget
    from hyperbolic.runner import AgentController, RunWriter, run_session
    from hyperbolic.sim import CityLearnSimulator

    month = mo.month("tuning-07")
    run = tmp_path / "run"
    ctl = AgentController(PrecoolingSupervisor(), Envelope(EnvelopeConfig()), Budget(2.0), prompt_version=10)
    res = run_session(CityLearnSimulator(control=True, schema=mo.month_schema(month, tmp_path / "m")), ctl,
                      RunWriter(run), hours=36, log=lambda *_: None, sim_info={"kind": "citylearn", "control": True},
                      dataset=month.dataset)
    assert res["fallback_steps"] == 0
    rows = fm.deviations(run)
    kinds = {r["class"] for r in rows}
    assert "precool" in kinds and kinds <= set(fm.CLASSES)
    assert all(r["reason"] for r in rows)  # every classified departure carries the model's hypothesis
    battery = [r for r in rows if r["device"] == "battery"]
    assert {r["step"] for r in battery} == {2, 3} and all(r["building"] == "Building_2" for r in battery)

    results = fm.attribute(run, rows, jobs=4)
    rep = fm.report(run, rows, results)
    assert rep["control_reproduces"] and results["control"]["fallback"] == 0
    # with every departure put back, the run is the suggestion every hour: the scripted strategy exactly
    assert results["all"]["kpis"] == results["strategy"]["kpis"] and results["all"]["usd"] == results["strategy"]["usd"]
    assert all(r["fallback"] == 0 for r in results.values())
    pre = rep["classes"]["precool"]
    assert pre["reasons_given"] == pre["building_hours"] and pre["claims"] == {"cost": pre["building_hours"]}
    assert pre["worth_usd"] == pytest.approx(results["control"]["usd"] - results["precool"]["usd"], abs=1e-4)


@needs_citylearn
def test_a_rejected_hour_stays_rejected_in_every_replay_that_keeps_it(tmp_path):
    from hyperbolic import months as mo
    from hyperbolic.envelope import Envelope, EnvelopeConfig
    from hyperbolic.model import Budget
    from hyperbolic.runner import AgentController, RunWriter, run_session
    from hyperbolic.sim import CityLearnSimulator

    month = mo.month("tuning-07")
    run = tmp_path / "run"
    ctl = AgentController(PrecoolingSupervisor(slip_at=20), Envelope(EnvelopeConfig()), Budget(2.0), prompt_version=10)
    res = run_session(CityLearnSimulator(control=True, schema=mo.month_schema(month, tmp_path / "m")), ctl,
                      RunWriter(run), hours=36, log=lambda *_: None, sim_info={"kind": "citylearn", "control": True},
                      dataset=month.dataset)
    assert res["fallback_steps"] == 1
    assert fm.rejected_of(run) == {(20, "Building_1")}
    rows = fm.deviations(run)
    at_slip = {r["class"] for r in rows if (r["step"], r["building"]) == (20, "Building_1")}
    assert "dhw_used" in at_slip
    results = fm.attribute(run, rows, jobs=4)
    assert fm.report(run, rows, results)["control_reproduces"] and results["control"]["fallback"] == 1
    # a replay keeps the rejection unless it puts back every departure of that building-hour
    for name, r in results.items():
        cleared = name in ("all", "strategy", "rejected hours") or at_slip == {name}
        assert r["fallback"] == (0 if cleared else 1), name
    assert results["all"]["kpis"] == results["strategy"]["kpis"]
    # the groups: the rejected hour put back, and every reasoned departure put back (the slip stays)
    rep = fm.report(run, rows, results)
    assert rep["rejected hours"]["fallback_in_replay"] == 0 and rep["reasoned"]["fallback_in_replay"] == 1
