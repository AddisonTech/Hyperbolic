"""0.4.0: combined signal, peak tracking, the envelope's peak limiter and the reason guard."""

import json
import random

import pytest
from conftest import BUILDINGS, needs_citylearn, proposal

from hyperbolic import district as dc
from hyperbolic.envelope import BuildingState, Envelope, EnvelopeConfig, StepContext, parse_reply
from hyperbolic.model import CallResult, observation_from_request
from hyperbolic.signals import PeakInfo, PeakTracker, combined_signal, peak_target_kwh

# -- combined signal ------------------------------------------------------------------


def test_signal_weights_and_scaling():
    sig = combined_signal([0.03, 0.05, 0.03], [0.40, 0.50, 0.50])
    assert sig == [0.0, 1.0, 0.5]  # cheapest and cleanest, worst on both, cheap but dirty
    assert dc.SIGNAL_WEIGHTS == {"price": 0.5, "carbon": 0.5}


def test_signal_flat_input_drops_out():
    # A flat price says nothing about which hour is better; carbon alone decides.
    sig = combined_signal([0.0289] * 3, [0.38, 0.47, 0.42])
    assert sig[0] == 0.0 and sig[1] == 1.0 and 0.0 < sig[2] < 1.0
    # And a price spike alone reaches the top of the scale when carbon is flat.
    assert combined_signal([0.05, 0.25], [0.4, 0.4]) == [0.0, 1.0]


def test_signal_handles_unknown_hours():
    # A single known carbon value is flat, so price alone decides.
    assert combined_signal([0.03, None, 0.05], [None, None, 0.4]) == [0.0, None, 1.0]
    assert combined_signal([None, None], [None, None]) == [None, None]


def test_signal_respects_custom_weights():
    assert combined_signal([0.0, 1.0], [1.0, 0.0], {"price": 3.0, "carbon": 1.0}) == [0.25, 0.75]


# -- peak tracking and target ---------------------------------------------------------


def _state(t, loads, grids=None):
    return {"time_step": t, "buildings": {b: {"load_kwh": loads[i], "grid_kwh": (grids or loads)[i]}
                                          for i, b in enumerate(BUILDINGS)}}


def test_peak_tracker_forecast_and_measured_peaks():
    pt = PeakTracker(forecast_days=2)
    for t in range(72):
        day = t // 24
        base = {0: 3.0, 1: 5.0, 2: 1.0}[day]
        pt.update(_state(t, [base, 1.0, 1.0 if t % 24 != 20 else 4.0]))
    info = pt.info(71)
    assert info.forecast_peak_kwh == pytest.approx(min(3.0 + 1 + 4, 5.0 + 1 + 4))  # lowest of the last two days
    assert info.today_load_peak_kwh == pytest.approx(1.0 + 1 + 4)
    assert info.load_now_kwh == pytest.approx(3.0)
    assert info.month_grid_peak_kwh == pytest.approx(10.0)
    # The draw observed at hour t is hour t - 1's, so hour 71's own draw is not known yet.
    assert 70 in pt.grid and 71 not in pt.grid


def test_peak_tracker_without_load_data():
    pt = PeakTracker()
    pt.update({"time_step": 0, "buildings": {b: {"grid_kwh": 1.0} for b in BUILDINGS}})
    info = pt.info(0)
    assert info.load_now_kwh is None and info.today_load_peak_kwh is None


def test_peak_target():
    assert peak_target_kwh(0.9, None, 10.0) is None
    assert peak_target_kwh(0.9, 4.0, None) == 4.0
    assert peak_target_kwh(0.9, 4.0, 10.0) == 9.0
    assert peak_target_kwh(0.9, 12.0, 10.0) == 12.0


# -- the limiter ----------------------------------------------------------------------


def peak_ctx(loads=(2.0, 2.0, 2.0), today=6.0, forecast=8.0, soc=0.3, dhw_soc=0.3, t=10):
    buildings = {}
    for b, load in zip(BUILDINGS, loads):
        buildings[b] = BuildingState(
            indoor_c=24.0, setpoint_c=24.0, occupied=True, battery_soc=soc, dhw_soc=dhw_soc,
            baseline={"cooling": 0.4, "dhw": 0.0, "battery": 0.0},
            bounds={"cooling": (0.0, 1.0), "dhw": (-1.0, 1.0), "battery": (-1.0, 1.0)},
            load_kwh=load, cooling_power_kw=4.0, battery_capacity_kwh=4.0, dhw_capacity_kwh=2.0,
            dhw_heater_efficiency=0.9)
    info = PeakInfo(load_now_kwh=sum(loads), today_load_peak_kwh=today, forecast_peak_kwh=forecast,
                    today_grid_peak_kwh=None, month_grid_peak_kwh=None)
    return StepContext(time_step=t, buildings=buildings, peak=info)


def test_limiter_trims_battery_charging_to_the_target():
    env = Envelope(EnvelopeConfig(peak_target_fraction=1.0))
    ctx = peak_ctx()  # load 6 kWh, target 8 kWh: 2 kWh of charging fits
    d = env.apply(proposal(**{b: {"battery": 0.5} for b in BUILDINGS}), ctx)  # asks for 6 kWh
    assert env.district_load(d.actions, ctx) <= 8.0 + 1e-9
    assert env.district_load(d.actions, ctx) == pytest.approx(8.0, abs=0.01)
    peaks = [c for c in d.clamps if c.rule == "peak"]
    assert {c.point for c in peaks} == {f"{b}.battery" for b in BUILDINGS}
    assert all("peak target 8.00 kWh" in c.reason for c in peaks)
    assert d.status == "clamped"


def test_limiter_leaves_room_alone_and_never_touches_discharge_or_cooling():
    env = Envelope(EnvelopeConfig(peak_target_fraction=1.0))
    ctx = peak_ctx()
    small = env.apply(proposal(**{b: {"battery": 0.1} for b in BUILDINGS}), ctx)  # 1.2 kWh, fits
    assert not small.clamps
    env = Envelope(EnvelopeConfig(peak_target_fraction=1.0))
    d = env.apply(proposal(Building_1={"battery": -0.2, "cooling": 0.5}, Building_2={"battery": 0.5}), ctx)
    assert d.actions["Building_1"]["battery"] == -0.2 and d.actions["Building_1"]["cooling"] == 0.5
    assert env.district_load(d.actions, ctx) <= 8.0 + 1e-9


def test_limiter_cuts_battery_before_the_tank():
    env = Envelope(EnvelopeConfig(peak_target_fraction=1.0))
    ctx = peak_ctx()
    # 2 kWh fits: 0.25 of a 4 kWh battery is 1 kWh, the tank at 0.4 adds 0.89 kWh: fits.
    d = env.apply(proposal(Building_1={"battery": 0.5, "dhw": 0.4}), ctx)
    assert d.actions["Building_1"]["dhw"] == 0.4  # the tank kept its charge
    assert d.actions["Building_1"]["battery"] < 0.5
    assert env.district_load(d.actions, ctx) <= 8.0 + 1e-9


def test_limiter_when_load_alone_is_over_the_target():
    env = Envelope(EnvelopeConfig())
    ctx = peak_ctx(loads=(4.0, 4.0, 4.0), today=12.0, forecast=8.0)  # target is today's 12 kWh
    d = env.apply(proposal(**{b: {"battery": 0.3, "dhw": 0.3} for b in BUILDINGS}), ctx)
    assert all(d.actions[b]["battery"] == 0.0 and d.actions[b]["dhw"] == 0.0 for b in BUILDINGS)


@pytest.mark.parametrize("seed", range(5))
def test_limiter_never_exceeds_the_target(seed):
    rng = random.Random(seed)
    for _ in range(200):
        loads = tuple(rng.uniform(-1.0, 5.0) for _ in BUILDINGS)
        ctx = peak_ctx(loads=loads, today=max(sum(loads), 0.0) + rng.uniform(0, 1), forecast=rng.uniform(0, 15),
                       soc=rng.uniform(0.1, 0.9), dhw_soc=rng.uniform(0.1, 0.9))
        env = Envelope(EnvelopeConfig(peak_target_fraction=rng.choice([0.8, 0.9, 1.0])))
        env.memory = {f"{b}.{d}": rng.uniform(-0.5, 0.5) for b in BUILDINGS for d in ("battery", "dhw")}
        p = proposal(**{b: {"battery": rng.uniform(-1, 1), "dhw": rng.uniform(-1, 1),
                            "cooling": rng.choice([None, rng.uniform(0, 1)])} for b in BUILDINGS})
        d = env.apply(p, ctx)
        target = env.peak_target(ctx)
        no_charge = {b: {**d.actions[b], "battery": min(0.0, d.actions[b]["battery"] or 0.0),
                         "dhw": min(0.0, d.actions[b]["dhw"] or 0.0)} for b in BUILDINGS}
        floor = env.district_load(no_charge, ctx)
        assert env.district_load(d.actions, ctx) <= max(target, floor) + 1e-9
        for c in d.clamps:
            if c.rule == "peak":
                assert c.applied <= c.requested and c.applied >= 0


def test_limiter_off_for_legacy_runs_and_without_load_data():
    legacy = Envelope(EnvelopeConfig.from_manifest({}))
    assert legacy.config.peak_limit is False
    d = legacy.apply(proposal(**{b: {"battery": 0.5} for b in BUILDINGS}), peak_ctx())
    assert not [c for c in d.clamps if c.rule == "peak"]
    env = Envelope(EnvelopeConfig())
    ctx = StepContext(time_step=0, buildings=peak_ctx().buildings, peak=None)
    assert env.peak_target(ctx) is None
    assert not env.apply(proposal(**{b: {"battery": 0.5} for b in BUILDINGS}), ctx).clamps


# -- reason guard ---------------------------------------------------------------------


def _reply(reason):
    return json.dumps({"reason": reason, **{b: {"cooling": None, "dhw": 0.0, "battery": 0.1} for b in BUILDINGS}})


def test_reason_length_guard():
    ok, err = parse_reply(_reply("x" * dc.REASON_MAX_CHARS), BUILDINGS)
    assert err is None and len(ok["reason"]) == dc.REASON_MAX_CHARS
    bad, err = parse_reply(_reply("x" * (dc.REASON_MAX_CHARS + 1)), BUILDINGS)
    assert bad is None and f"at most {dc.REASON_MAX_CHARS} characters" in err
    assert dc.REASON_TARGET_CHARS <= dc.REASON_MAX_CHARS // 2


# -- end to end on CityLearn ----------------------------------------------------------


class ChargeEverything:
    """Asks every battery for a full charge every hour, so the limiter has work to do."""

    kind = "fake"
    model_key = "haiku"

    def call(self, step, request):
        obs = observation_from_request(request)
        reply = {"reason": "Charge everything."}
        reply.update({b: {"cooling": None, "dhw": 0.0, "battery": 0.5} for b in obs["buildings"]})
        return CallResult(json.dumps(reply), stop_reason="end_turn")


@needs_citylearn
def test_limiter_on_citylearn_holds_the_target_and_replays(tmp_path):
    from hyperbolic.model import Budget
    from hyperbolic.runner import AgentController, RunWriter, load_jsonl, replay_run, run_session
    from hyperbolic.sim import CityLearnSimulator

    hours = 71  # three days, so a forecast exists from day two
    ctl = AgentController(ChargeEverything(), Envelope(EnvelopeConfig()), Budget(1.0))
    run_dir = tmp_path / "charge"
    run_session(CityLearnSimulator(control=True), ctl, RunWriter(run_dir), hours=hours, log=lambda *_: None,
                sim_info={"kind": "citylearn", "control": True})
    steps = load_jsonl(run_dir / "steps.jsonl")
    peak_clamps = [c for s in steps for c in s["decision"]["clamps"] if c["rule"] == "peak"]
    assert peak_clamps
    # Measured draw stays within the target wherever the limiter acted (estimate error is tiny).
    for s in steps:
        if any(c["rule"] == "peak" for c in s["decision"]["clamps"]):
            target = float(s["decision"]["clamps"][-1]["reason"].split("peak target ")[1].split(" kWh")[0])
            drawn = sum(o["grid_kwh"] for o in s["outcome"].values())
            assert drawn <= target + 0.05
    rep = replay_run(run_dir)
    assert rep.deterministic and rep.identical_steps == hours
