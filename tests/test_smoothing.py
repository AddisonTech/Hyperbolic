"""Prompt version 5 and its scripted strategy: smoothing the district load (0.7.0)."""

import copy
import json

import pytest
from fakes import FakeDistrict

from hyperbolic import district as dc
from hyperbolic.envelope import Envelope, EnvelopeConfig
from hyperbolic.model import Budget, ScriptedSupervisor, StrategyParamsV5, strategy_plan_v5
from hyperbolic.prompt import Lookahead, build_request, observe, system_prompt_v5
from hyperbolic.runner import AgentController, NullWriter, context_from_state, run_session
from hyperbolic.signals import PeakTracker, PriceOutlook


def _states(n):
    sim = FakeDistrict()
    st = sim.start(n)
    out = []
    while st is not None:
        out.append(st)
        _, st = sim.step(None)
    return out


def _obs(n=27, envelope=None):
    states = _states(n + 3)
    look, peaks = Lookahead(), PeakTracker()
    for st in states[:n]:
        look.update(st)
        peaks.update(st)
    st = states[n - 1]
    t = st["time_step"]
    ctx = context_from_state(st, peaks.info(t), PriceOutlook(st["shared"]["price_forecast"][0],
                                                            tuple(look.outlook(t)["price"])))
    env = envelope or Envelope(EnvelopeConfig())
    return st, ctx, look, peaks, env, observe(5, st, ctx, None, look, env)


def test_peak_tracker_reports_last_hour_and_next_hour_as_yesterday():
    states = _states(30)
    peaks = PeakTracker()
    for st in states[:27]:
        peaks.update(st)
    info = peaks.info(26)
    assert info.last_hour_grid_kwh == pytest.approx(sum(s["grid_kwh"] for s in states[26]["buildings"].values()))
    assert info.next_hour_load_kwh == pytest.approx(sum(s["load_kwh"] for s in states[3]["buildings"].values()))
    assert peaks.info(5).next_hour_load_kwh is None  # no yesterday yet


def test_envelope_remembers_each_buildings_trim_and_forgets_it_on_fallback():
    st, ctx, *_ = _obs()
    env = Envelope(EnvelopeConfig.v070())  # the record alone; the fake room sits at its setpoint
    base = st["baseline"]["Building_1"]["cooling"]
    prop = {"reason": "t", "buildings": {b: {"cooling": None, "dhw": None, "battery": None} for b in st["buildings"]}}
    prop["buildings"]["Building_1"]["cooling"] = base - 0.08
    env.apply(prop, ctx)
    assert env.trims["Building_1"] == pytest.approx(-0.08) and env.trims["Building_2"] == 0.0
    env.fallback(ctx, "test")
    assert env.trims == {}


def test_v5_observation_adds_the_smoothing_view_to_v4():
    env = Envelope(EnvelopeConfig())
    env.trims = {"Building_1": -0.06}
    st, ctx, look, peaks, env, obs = _obs(envelope=env)
    v4 = observe(4, st, ctx, None, look, env)
    assert all(obs[k] == v for k, v in v4.items() if k != "buildings")
    for b, s in v4["buildings"].items():
        assert all(obs["buildings"][b][k] == v for k, v in s.items())
    sm = obs["smoothing"]
    assert set(sm) == {"district_draw_last_hour_kwh", "district_load_now_kwh", "district_load_next_hour_kwh"}
    assert sm["district_draw_last_hour_kwh"] == round(ctx.peak.last_hour_grid_kwh, 2)
    assert sm["district_load_next_hour_kwh"] == round(ctx.peak.next_hour_load_kwh, 2)
    assert obs["buildings"]["Building_1"]["cooling_trim_last_hour"] == -0.06
    assert obs["buildings"]["Building_2"]["cooling_trim_last_hour"] == 0.0
    req = build_request(obs, env.config, tuple(st["buildings"]), "haiku", prompt_version=5)
    assert '"smoothing"' in req["messages"][0]["content"] and "reference_action" in req["system"]


def test_v5_prompt_states_the_smoothing_numbers_it_was_tuned_with():
    sp = StrategyParamsV5()
    text = system_prompt_v5(EnvelopeConfig(), ("Building_1",))
    for phrase in (f"within {sp.trim_hold_c:g} C of its setpoint", f"ease it off by at most {sp.trim_step:g} per hour",
                   f"rising by at most {sp.charge_step:g} per hour", "evenly over the top-price hours left",
                   "a step up costs and a step down does not", "cooling_trim_last_hour", "district_draw_last_hour_kwh",
                   "2. Peaks and smoothness:", "grid_charging_ok is false"):
        assert phrase in text, phrase
    assert f"at most {dc.REASON_TARGET_CHARS} characters" in text
    assert chr(0x2014) not in text


def _cold_obs(gap, trim_last, occupied=True):
    *_, obs = _obs()
    obs = copy.deepcopy(obs)
    obs["price_plan"].update(top_price_now=False)
    for s in obs["buildings"].values():
        s["occupied"] = occupied
        s["indoor_vs_setpoint_c"] = gap
        s["cooling_trim_last_hour"] = trim_last
        s["baseline_action"]["cooling"] = 0.4
        s["battery"]["grid_charging_ok"] = False
    return obs


def _trim(reply):
    c = reply["Building_1"]["cooling"]
    return 0.0 if c is None else round(c - 0.4, 3)


def test_a_trim_starts_at_once_in_a_cold_room():
    p = StrategyParamsV5(cold_margin_c=0.5, cold_trim=0.1, cold_ramp_c=1.0)
    assert _trim(strategy_plan_v5(_cold_obs(-1.5, 0.0), p)) == pytest.approx(-0.1, abs=0.003)  # 0.001 kept clear of the limit
    assert _trim(strategy_plan_v5(_cold_obs(-0.3, 0.0), p)) == 0.0  # not cold enough to start


def test_a_trim_is_held_until_the_room_is_nearly_back_then_eased_off_slowly():
    p = StrategyParamsV5(cold_margin_c=0.5, trim_hold_c=0.25, trim_step=0.02)
    # -0.4 C: no longer cold enough to start a trim, but not yet within 0.25 C, so the trim holds.
    assert _trim(strategy_plan_v5(_cold_obs(-0.4, -0.08), p)) == pytest.approx(-0.08, abs=0.002)
    # -0.1 C: within the hold band, so it eases off by at most 0.02 an hour.
    assert _trim(strategy_plan_v5(_cold_obs(-0.1, -0.08), p)) == pytest.approx(-0.06, abs=0.002)
    # At or above the setpoint the room needs cooling: back to the baseline at once.
    assert strategy_plan_v5(_cold_obs(0.0, -0.08), p)["Building_1"]["cooling"] is None
    # Unoccupied: no new trim, an old one eases off.
    assert _trim(strategy_plan_v5(_cold_obs(-1.5, -0.08, occupied=False), p)) == pytest.approx(-0.06, abs=0.002)


def test_charging_starts_small_and_discharge_spreads_over_the_top_price_hours():
    p = StrategyParamsV5(charge_step=0.05, charge_rate=0.15, shave=0.0)
    *_, obs = _obs()  # hour 3 of day two in the fake district: cheap, top price later
    obs = copy.deepcopy(obs)
    for s in obs["buildings"].values():
        s["battery"]["grid_charging_ok"] = True
        s["battery"]["soc"] = 0.3
        s["last_action"] = {"battery": 0.0, "cooling": None, "dhw": 0.0}
    reply = strategy_plan_v5(obs, p)
    assert 0 < reply["Building_1"]["battery"] <= 0.05
    for s in obs["buildings"].values():
        s["last_action"]["battery"] = 0.05
    assert reply["Building_1"]["battery"] < strategy_plan_v5(obs, p)["Building_1"]["battery"] <= 0.1
    # A top-price hour with two more ahead: a third of the usable charge at most.
    obs["price_plan"].update(top_price_now=True, top_price_hours_ahead=[1, 2])
    for s in obs["buildings"].values():
        s["battery"]["soc"] = 0.9
        s["load_now_kwh"] = 5.0
    spare = 0.9 - 0.2 - 0.001
    assert -spare / 3 - 1e-3 <= strategy_plan_v5(obs, p)["Building_1"]["battery"] < 0


def test_v5_run_on_the_fake_district_replays_identically(tmp_path):
    from hyperbolic.runner import RunWriter, load_jsonl, replay_run

    ctl = AgentController(ScriptedSupervisor(tokens=(3000, 250)), Envelope(EnvelopeConfig()), Budget(2.0),
                          prompt_version=5)
    run_session(FakeDistrict(), ctl, RunWriter(tmp_path / "v5"), hours=48, log=lambda *_: None)
    calls = load_jsonl(tmp_path / "v5" / "calls.jsonl")
    assert '"cooling_trim_last_hour"' in calls[1]["request"]["messages"][0]["content"]
    rep = replay_run(tmp_path / "v5")
    assert rep.deterministic and rep.api_calls == 0 and rep.identical_steps == 48, (rep.mismatched_steps, rep.error)
    replay_run(tmp_path / "v5", out_dir=tmp_path / "again")
    assert (tmp_path / "again" / "steps.jsonl").read_bytes() == (tmp_path / "v5" / "steps.jsonl").read_bytes()


def test_a_changed_trim_memory_is_detected_on_replay(tmp_path, monkeypatch):
    from hyperbolic.runner import RunWriter, replay_run

    ctl = AgentController(ScriptedSupervisor(), Envelope(EnvelopeConfig()), Budget(2.0), prompt_version=5)
    run_session(FakeDistrict(), ctl, RunWriter(tmp_path / "v5"), hours=48, log=lambda *_: None)
    # If the observation reported a different trim last hour, the recorded requests no longer match.
    import hyperbolic.prompt as pr

    original = pr.build_observation_v5

    def shifted(*a, **k):
        obs = original(*a, **k)
        obs["buildings"]["Building_1"]["cooling_trim_last_hour"] = -0.5
        return obs

    monkeypatch.setattr(pr, "build_observation_v5", shifted)
    rep = replay_run(tmp_path / "v5")
    assert not rep.deterministic and "request differs" in rep.error


def test_the_strategy_reasons_fit_the_target_length():
    w = NullWriter()
    run_session(FakeDistrict(), AgentController(ScriptedSupervisor(), Envelope(EnvelopeConfig()), Budget(2.0),
                                                prompt_version=5), w, hours=48, log=lambda *_: None)
    assert max(len(json.dumps(s["decision"]["reason"])) for s in w.steps) <= dc.REASON_TARGET_CHARS + 2
