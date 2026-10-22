"""The 0.6.0 spread check: grid charging is blocked only when it cannot pay back the battery's losses."""

import pytest
from conftest import BUILDINGS, proposal

from hyperbolic.envelope import BuildingState, Envelope, EnvelopeConfig, StepContext
from hyperbolic.signals import PriceOutlook, charge_spread

OFF, SHOULDER, TOP = 0.0289, 0.0292, 0.0587


def bstate(load_kwh=1.0, battery_soc=0.5, round_trip=0.88, loss=0.0001) -> BuildingState:
    return BuildingState(indoor_c=24.0, setpoint_c=24.0, occupied=True, battery_soc=battery_soc, dhw_soc=0.5,
                         baseline={"cooling": 0.4, "dhw": 0.0, "battery": 0.0},
                         bounds={"cooling": (0.0, 1.0), "dhw": (-1.0, 1.0), "battery": (-0.83, 0.83)},
                         load_kwh=load_kwh, cooling_power_kw=4.0, battery_capacity_kwh=4.0, dhw_capacity_kwh=2.0,
                         dhw_heater_efficiency=0.9, battery_round_trip_min=round_trip, battery_loss_per_hour=loss)


def day(start_hour: int, hours: int = 24) -> tuple[float, ...]:
    """A weekday tariff seen from start_hour: top price at hours 16 to 18, cheapest overnight."""
    out = []
    for j in range(1, hours + 1):
        h = (start_hour + j - 1) % 24 + 1
        out.append(TOP if 16 <= h <= 18 else OFF if h >= 23 or h <= 7 else SHOULDER)
    return tuple(out)


def ctx(now: float, ahead: tuple, **b) -> StepContext:
    return StepContext(time_step=100, buildings={x: bstate(**b) for x in BUILDINGS},
                       prices=PriceOutlook(now=now, ahead=ahead))


def charge_all(v=0.3):
    return proposal(**{b: {"battery": v} for b in BUILDINGS})


def test_charging_at_the_top_price_is_blocked_with_a_reason():
    env = Envelope(EnvelopeConfig(peak_limit=False))
    d = env.apply(charge_all(), ctx(TOP, day(16)))
    assert all(d.actions[b]["battery"] == 0.0 for b in BUILDINGS)
    clamps = [c for c in d.clamps if c.rule == "spread"]
    assert {c.point for c in clamps} == {f"{b}.battery" for b in BUILDINGS}
    c = clamps[0]
    assert c.requested == 0.3 and c.applied == 0.0
    assert c.reason.startswith(f"price {TOP:.4f} now, best ahead {TOP:.4f}")
    assert "12% round trip and standing losses" in c.reason and "grid charging blocked" in c.reason
    assert "a cheaper hour comes in 3 h" in c.reason  # 5 and 6 pm are still at the top price
    assert d.as_dict()["clamps"][0]["rule"] == "spread"


@pytest.mark.parametrize("hour,price", [(3, OFF), (12, SHOULDER), (20, SHOULDER)])
def test_charging_that_the_coming_peak_pays_back_is_allowed(hour, price):
    env = Envelope(EnvelopeConfig(peak_limit=False))
    d = env.apply(charge_all(), ctx(price, day(hour)))
    assert not d.clamps and all(d.actions[b]["battery"] == 0.3 for b in BUILDINGS)


def test_a_flat_outlook_does_not_block_because_the_next_peak_may_lie_beyond_it():
    # A weekend: no price difference in the next 24 hours, but Monday's peak can still pay back a charge.
    env = Envelope(EnvelopeConfig(peak_limit=False))
    d = env.apply(charge_all(), ctx(OFF, (OFF,) * 24))
    assert not d.clamps


def test_a_cheaper_hour_ahead_with_nothing_that_pays_blocks():
    # Friday evening: the weekend ahead is flat and slightly cheaper, so charging now is dominated.
    env = Envelope(EnvelopeConfig(peak_limit=False))
    d = env.apply(charge_all(), ctx(SHOULDER, (SHOULDER,) * 3 + (OFF,) * 21))
    assert {c.rule for c in d.clamps} == {"spread"}
    assert "a cheaper hour comes in 4 h" in d.clamps[0].reason


def test_standing_losses_count_against_a_distant_peak():
    # 0.0587 kept at 0.89 x (1 - 0.0016)^20 is worth about 0.0505, less than 0.051 now.
    prices = PriceOutlook(now=0.051, ahead=(0.03,) * 19 + (0.0587,) + (0.03,) * 4)
    lossy = charge_spread(prices, 0.89, 0.0016)
    tight = charge_spread(prices, 0.89, 0.0)
    assert lossy.blocked and lossy.best_hours_ahead == 20 and lossy.keep == pytest.approx(0.89 * 0.9984 ** 20)
    assert not tight.blocked and tight.pays


def test_spare_solar_may_still_be_stored():
    # Load before storage of -0.6 kWh is solar the building would export for nothing: 0.15 of 4 kWh.
    env = Envelope(EnvelopeConfig(peak_limit=False))
    d = env.apply(charge_all(0.4), ctx(TOP, day(16), load_kwh=-0.6))
    assert all(d.actions[b]["battery"] == 0.15 for b in BUILDINGS)
    assert all(c.reason.endswith("spare solar still stored") for c in d.clamps)


def test_discharging_and_holding_are_never_touched():
    env = Envelope(EnvelopeConfig(peak_limit=False))
    d = env.apply(proposal(Building_1={"battery": -0.3}, Building_2={"battery": 0.0}), ctx(OFF, (OFF,) * 6 + day(6)[6:]))
    assert not d.clamps and d.actions["Building_1"]["battery"] == -0.3


def test_off_for_older_runs_and_the_rule_based_reference():
    for cfg in (EnvelopeConfig.from_manifest({}), EnvelopeConfig.from_manifest({"peak_limit": True}),
                EnvelopeConfig.v040()):
        d = Envelope(cfg).apply(charge_all(), ctx(TOP, day(16)))
        assert not [c for c in d.clamps if c.rule == "spread"]


def test_without_price_or_battery_data_the_check_stands_aside():
    env = Envelope(EnvelopeConfig(peak_limit=False))
    no_prices = StepContext(time_step=1, buildings={b: bstate() for b in BUILDINGS})
    assert not env.apply(charge_all(), no_prices).clamps
    assert not env.apply(charge_all(), ctx(TOP, (None,) * 24)).clamps
    assert not env.apply(charge_all(), ctx(TOP, day(16), round_trip=None)).clamps


def test_the_check_runs_before_the_peak_limiter():
    # A blocked charge is gone before the limiter looks, so the limiter has nothing left to trim.
    from hyperbolic.signals import PeakInfo

    env = Envelope(EnvelopeConfig())
    c = ctx(TOP, day(16))
    c = StepContext(time_step=c.time_step, buildings=c.buildings, prices=c.prices,
                    peak=PeakInfo(load_now_kwh=3.0, today_load_peak_kwh=3.0, forecast_peak_kwh=3.0,
                                  today_grid_peak_kwh=None, month_grid_peak_kwh=None))
    d = env.apply(charge_all(), c)
    assert {cl.rule for cl in d.clamps} == {"spread"}
