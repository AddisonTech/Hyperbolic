import json
import math

import pytest
from conftest import BUILDINGS, ctx, proposal

from hyperbolic.envelope import Envelope, EnvelopeConfig, parse_reply, proposal_json_schema


def rules(decision):
    return {(c.point, c.rule) for c in decision.clamps}


def test_in_range_proposal_passes_unchanged(envelope):
    d = envelope.apply(proposal(Building_1={"cooling": 0.5, "battery": 0.2, "dhw": -0.1}), ctx())
    assert d.status == "ok"
    assert d.actions["Building_1"] == {"cooling": 0.5, "dhw": -0.1, "battery": 0.2}
    assert d.actions["Building_2"]["battery"] is None  # null keeps the baseline action


def test_null_resolves_to_baseline(envelope):
    c = ctx()
    d = envelope.apply(proposal(Building_1={"battery": 0.2}), c)
    resolved = d.resolved(c)
    assert resolved["Building_1"] == {"cooling": 0.4, "dhw": 0.0, "battery": 0.2}
    assert resolved["Building_3"] == {"cooling": 0.4, "dhw": 0.0, "battery": 0.0}


def test_out_of_range_is_clamped_to_action_space(envelope):
    d = envelope.apply(proposal(Building_1={"battery": 1.8}, Building_2={"cooling": -0.5}), ctx())
    assert ("Building_1.battery", "range") in rules(d)
    assert ("Building_2.cooling", "range") in rules(d)
    # Range takes cooling to 0, then the ramp limit from the 0.4 baseline holds it at 0.05.
    assert d.actions["Building_2"]["cooling"] == 0.05
    # Range takes the battery to the 0.83 bound, the ramp limit to 0.5, the 0.95 charge limit to 0.45.
    assert d.actions["Building_1"]["battery"] == 0.45


def test_too_fast_is_rate_limited(envelope):
    envelope.apply(proposal(Building_1={"battery": -0.4}), ctx(t=10))
    d = envelope.apply(proposal(Building_1={"battery": 0.6}), ctx(t=11))
    assert ("Building_1.battery", "rate") in rules(d)
    # Allowed window spans last hour's -0.4 and the baseline 0.0, plus 0.5 either way.
    assert d.actions["Building_1"]["battery"] == 0.45


def test_returning_to_baseline_is_never_too_fast(envelope):
    envelope.apply(proposal(Building_1={"battery": 0.45}), ctx(t=10))
    d = envelope.apply(proposal(Building_1={"battery": 0.0}), ctx(t=11))
    assert d.status == "ok"


def test_cooling_rate_measured_from_baseline_too(envelope):
    # Last hour cooling 0.1, baseline now 0.9: 0.9 itself is always allowed.
    envelope.apply(proposal(Building_1={"cooling": 0.1}), ctx(t=10, Building_1={"cooling_base": 0.1}))
    d = envelope.apply(proposal(Building_1={"cooling": 0.9}), ctx(t=11, Building_1={"cooling_base": 0.9}))
    assert d.status == "ok"


def test_battery_soc_limits(envelope):
    c = ctx(Building_1={"battery_soc": 0.9}, Building_2={"battery_soc": 0.15})
    d = envelope.apply(proposal(Building_1={"battery": 0.3}, Building_2={"battery": -0.3}), c)
    assert ("Building_1.battery", "soc") in rules(d)
    assert ("Building_2.battery", "soc") in rules(d)
    assert d.actions["Building_1"]["battery"] == pytest.approx(0.05)
    assert d.actions["Building_2"]["battery"] == pytest.approx(-0.05)


def test_soc_already_outside_limits_blocks_only_further_moves(envelope):
    c = ctx(Building_1={"battery_soc": 0.05})
    d = envelope.apply(proposal(Building_1={"battery": -0.2}), c)
    assert d.actions["Building_1"]["battery"] == 0.0
    d = envelope.apply(proposal(Building_1={"battery": 0.2}), ctx(t=11, Building_1={"battery_soc": 0.05}))
    assert d.actions["Building_1"]["battery"] == 0.2


def test_dhw_tank_soc_limits(envelope):
    d = envelope.apply(proposal(Building_3={"dhw": 0.4}), ctx(Building_3={"dhw_soc": 0.8}))
    assert ("Building_3.dhw", "soc") in rules(d)
    assert d.actions["Building_3"]["dhw"] == pytest.approx(0.15)


def test_comfort_holds_cooling_when_warm(envelope):
    c = ctx(Building_1={"indoor": 25.8, "setpoint": 24.0})  # band top 26.0, margin 0.5
    d = envelope.apply(proposal(Building_1={"cooling": 0.1}), c)
    assert ("Building_1.cooling", "comfort") in rules(d)
    assert d.actions["Building_1"]["cooling"] == 0.4


def test_comfort_holds_cooling_when_cool(envelope):
    c = ctx(Building_1={"indoor": 22.3, "setpoint": 24.0})
    d = envelope.apply(proposal(Building_1={"cooling": 0.7}), c)
    assert ("Building_1.cooling", "comfort") in rules(d)
    assert d.actions["Building_1"]["cooling"] == 0.4


def test_comfort_rule_only_in_occupied_hours(envelope):
    c = ctx(Building_1={"indoor": 25.8, "occupied": False})
    d = envelope.apply(proposal(Building_1={"cooling": 0.1}), c)
    assert d.status == "ok" and d.actions["Building_1"]["cooling"] == 0.1


def test_comfort_allows_more_cooling_when_warm(envelope):
    c = ctx(Building_1={"indoor": 25.8})
    d = envelope.apply(proposal(Building_1={"cooling": 0.7}), c)
    assert d.status == "ok"


@pytest.mark.parametrize("text", [None, "", "   ", "not json", '{"reason": "x", "Building_1": {"battery": 0.4',
                                  "[1, 2, 3]", '"just a string"'])
def test_malformed_replies_rejected(text):
    p, why = parse_reply(text, BUILDINGS)
    assert p is None and why


def _valid():
    acts = {"cooling": 0.4, "dhw": None, "battery": 0.1}
    return {"reason": "ok", **{b: dict(acts) for b in BUILDINGS}}


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.pop("Building_3"),
        lambda d: d["Building_1"].pop("battery"),
        lambda d: d.update(Building_9={"cooling": 0.1, "dhw": 0.0, "battery": 0.0}),
        lambda d: d.update(extra=1),
        lambda d: d["Building_2"].update(battery="half"),
        lambda d: d["Building_2"].update(battery=True),
        lambda d: d["Building_1"].update(fan=1.0),
        lambda d: d.update(reason=""),
        lambda d: d.update(reason="x" * 301),
        lambda d: d.update(reason=7),
    ],
)
def test_schema_violations_rejected(mutate):
    d = _valid()
    mutate(d)
    p, why = parse_reply(json.dumps(d), BUILDINGS)
    assert p is None and "schema" in why


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_numbers_rejected(bad):
    text = json.dumps(_valid()).replace("0.1", bad, 1)
    p, why = parse_reply(text, BUILDINGS)
    assert p is None


def test_integers_accepted_as_numbers():
    d = _valid()
    d["Building_1"]["cooling"] = 1
    p, why = parse_reply(json.dumps(d), BUILDINGS)
    assert why is None and p["buildings"]["Building_1"]["cooling"] == 1.0


def test_schema_matches_buildings():
    s = proposal_json_schema(BUILDINGS)
    assert s["required"] == ["reason", *BUILDINGS]
    assert s["additionalProperties"] is False


def test_invalid_reply_falls_back_to_baseline(envelope):
    envelope.apply(proposal(Building_1={"battery": 0.4}), ctx(t=10))
    p, why = parse_reply("garbage", BUILDINGS)
    c = ctx(t=11)
    d = envelope.apply(p, c, why)
    assert d.status == "fallback" and "JSON" in d.fallback
    assert d.resolved(c)["Building_1"] == {"cooling": 0.4, "dhw": 0.0, "battery": 0.0}
    # After a fallback the ramp limit measures from the baseline action again.
    d = envelope.apply(proposal(Building_1={"battery": -0.8}), ctx(t=12, Building_1={"battery_soc": 0.9}))
    assert d.actions["Building_1"]["battery"] == -0.5


def test_every_clamp_has_a_reason(envelope):
    c = ctx(Building_1={"indoor": 25.9, "battery_soc": 0.94})
    d = envelope.apply(proposal(Building_1={"cooling": -1.0, "battery": 3.0, "dhw": -4.0}), c)
    assert d.status == "clamped"
    assert d.clamps and all(cl.reason for cl in d.clamps)
    for v in d.resolved(c)["Building_1"].values():
        assert math.isfinite(v)


def test_config_is_respected():
    env = Envelope(EnvelopeConfig(battery_rate_per_step=0.1))
    d = env.apply(proposal(Building_1={"battery": 0.3}), ctx())
    assert d.actions["Building_1"]["battery"] == 0.1
