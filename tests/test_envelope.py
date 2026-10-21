import json
import math

import pytest
from conftest import ctx, proposal

from hyperbolic.envelope import Envelope, EnvelopeConfig, parse_reply


def rules(decision):
    return {(c.point, c.rule) for c in decision.clamps}


def test_in_range_proposal_passes_unchanged(envelope):
    d = envelope.apply(proposal(nor=(20.5, 24.0), supply_air_c=13.0), ctx(10))
    assert d.status == "ok"
    assert d.heat_c["nor"] == 20.5 and d.cool_c["nor"] == 24.0
    assert d.supply_air_c == 13.0
    assert d.heat_c["eas"] is None  # null leaves the point to stock control


def test_out_of_range_is_clamped_to_equipment_limits(envelope):
    envelope.apply(proposal(cor=(22.0, None)), ctx(9))
    envelope.apply(proposal(cor=(23.5, None)), ctx(10))
    d = envelope.apply(proposal(cor=(27.5, None)), ctx(11))
    assert ("cor.heat_c", "range") in rules(d)
    # 24 C is the range ceiling, then the deadband under the 24 C comfort ceiling leaves 23 C.
    assert ("cor.heat_c", "deadband") in rules(d)
    assert d.heat_c["cor"] == 23.0


def test_out_of_range_low_cooling_clamped(envelope):
    d = envelope.apply(proposal(eas=(None, 15.0)), ctx(10))
    assert ("eas.cool_c", "range") in rules(d)
    # 21 C is the range floor, then the rate limit from 24 caps the move at 2 K.
    assert d.cool_c["eas"] == 22.0


def test_too_fast_is_rate_limited(envelope):
    d = envelope.apply(proposal(nor=(23.0, None)), ctx(10))  # from stock 20 C
    assert ("nor.heat_c", "rate") in rules(d)
    assert d.heat_c["nor"] == 22.0
    d = envelope.apply(proposal(nor=(23.0, None)), ctx(11))
    assert d.heat_c["nor"] == 23.0 and d.status == "ok"


def test_rate_limit_for_supply_air(envelope):
    d = envelope.apply(proposal(supply_air_c=18.0), ctx(8))
    assert ("supply_air_c", "rate") in rules(d)
    assert d.supply_air_c == 13.5


def test_rate_limit_follows_stock_schedule_steps(envelope):
    # Preheat ramp before occupancy, then the stock step from 12 to 20 C at 06:00.
    for hour, val in ((3, 14.0), (4, 16.0), (5, 18.0)):
        assert envelope.apply(proposal(nor=(val, None)), ctx(hour)).status == "ok"
    d = envelope.apply(proposal(nor=(20.5, None)), ctx(6))
    assert d.status == "ok" and d.heat_c["nor"] == 20.5


def test_partial_preheat_then_occupied_is_not_clamped(envelope):
    envelope.apply(proposal(nor=(14.0, None)), ctx(4))
    envelope.apply(proposal(nor=(16.0, None)), ctx(5))
    d = envelope.apply(proposal(nor=(20.0, None)), ctx(6))
    assert d.status == "ok"


def test_comfort_band_wins_over_rate_limit(envelope):
    d = envelope.apply(proposal(wes=(18.0, 26.0)), ctx(10))
    assert ("wes.heat_c", "comfort") in rules(d)
    assert ("wes.cool_c", "comfort") in rules(d)
    assert d.heat_c["wes"] == 20.0 and d.cool_c["wes"] == 24.0


def test_deadband_enforced(envelope):
    envelope.apply(proposal(sou=(21.0, 23.0)), ctx(9))
    d = envelope.apply(proposal(sou=(22.5, 23.0)), ctx(10))
    assert ("sou.cool_c", "deadband") in rules(d)
    assert d.cool_c["sou"] - d.heat_c["sou"] >= 1.0 - 1e-9


def test_supply_air_released_outside_occupied_hours(envelope):
    d = envelope.apply(proposal(supply_air_c=14.0), ctx(2))
    assert d.supply_air_c is None
    assert ("supply_air_c", "schedule") in rules(d)


@pytest.mark.parametrize(
    "text",
    [
        None,
        "",
        "   ",
        "not json at all",
        '{"reason": "x", "nor": {"heat_c": 21',
        "[1, 2, 3]",
        '"just a string"',
    ],
)
def test_malformed_replies_rejected(text):
    p, why = parse_reply(text)
    assert p is None and why


def _valid():
    z = {"heat_c": 21.0, "cool_c": None}
    return {"reason": "ok", "nor": z, "eas": z, "sou": z, "wes": z, "cor": z, "supply_air_c": 14.0}


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.pop("cor"),
        lambda d: d.pop("supply_air_c"),
        lambda d: d.update(extra_field=1),
        lambda d: d.update(supply_air_c="fifteen"),
        lambda d: d.update(supply_air_c=True),
        lambda d: d["nor"].update(heat_c="21"),
        lambda d: d["nor"].update(fan=1.0),
        lambda d: d.update(reason=""),
        lambda d: d.update(reason="x" * 301),
        lambda d: d.update(reason=7),
    ],
)
def test_schema_violations_rejected(mutate):
    d = _valid()
    mutate(d)
    p, why = parse_reply(json.dumps(d))
    assert p is None and "schema" in why


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_numbers_rejected(bad):
    text = json.dumps(_valid()).replace("14.0", bad)
    p, why = parse_reply(text)
    assert p is None


def test_integers_accepted_as_numbers():
    d = _valid()
    d["supply_air_c"] = 14
    p, why = parse_reply(json.dumps(d))
    assert why is None and p.supply_air_c == 14.0


def test_invalid_reply_falls_back_to_baseline_and_resets_memory(envelope):
    envelope.apply(proposal(nor=(22.0, None)), ctx(10))
    p, why = parse_reply("garbage")
    d = envelope.apply(p, ctx(11), why)
    assert d.status == "fallback" and "JSON" in d.fallback
    assert all(v is None for v in d.heat_c.values())
    assert all(v is None for v in d.cool_c.values())
    assert d.supply_air_c is None
    u = d.to_boptest_u(ctx(11).time_s)
    assert all(v == 0 for k, v in u.items() if k.endswith("_activate"))
    # After the fallback the rate limit measures from stock again.
    d = envelope.apply(proposal(nor=(24.0, None)), ctx(12))
    assert d.heat_c["nor"] == 22.0


def test_overwrite_dict_units_and_flags(envelope):
    d = envelope.apply(proposal(nor=(21.0, None), supply_air_c=13.0), ctx(10))
    u = d.to_boptest_u(ctx(10).time_s)
    assert u["hvac_oveZonSupNor_TZonHeaSet_activate"] == 1
    assert math.isclose(u["hvac_oveZonSupNor_TZonHeaSet_u"], 294.15)
    assert u["hvac_oveZonSupNor_TZonCooSet_activate"] == 0
    assert u["hvac_oveAhu_TSupSet_activate"] == 1
    assert math.isclose(u["hvac_oveAhu_TSupSet_u"], 286.15)
    for k, v in u.items():
        if k.endswith("_u"):
            assert 285.15 <= v <= 313.15


def test_every_clamp_has_a_reason(envelope):
    d = envelope.apply(proposal(nor=(30.0, 15.0), cor=(10.0, 35.0), supply_air_c=25.0), ctx(10))
    assert d.status == "clamped"
    assert d.clamps and all(c.reason for c in d.clamps)


def test_config_is_respected():
    env = Envelope(EnvelopeConfig(zone_rate_k_per_step=0.5))
    d = env.apply(proposal(nor=(21.0, None)), ctx(10))
    assert d.heat_c["nor"] == 20.5
