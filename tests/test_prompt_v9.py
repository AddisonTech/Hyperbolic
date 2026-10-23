"""Prompt version 9 (0.11.0): charge kept for the evening shave, peak.shave_now, the wording on small numbers
and shaving after the top price, version 8 still selectable, and the 0.10.0 live months unchanged."""

import json
from dataclasses import asdict
from pathlib import Path

import pytest
from conftest import BUILDINGS, needs_citylearn
from fakes import FakeDistrict
from test_prompt_v8 import _obs

from hyperbolic.envelope import Envelope, EnvelopeConfig, parse_reply
from hyperbolic.model import (
    Budget,
    ScriptedSupervisor,
    StrategyParamsV8,
    StrategyParamsV9,
    strategy_plan_v8,
    strategy_plan_v9,
)
from hyperbolic.prompt import PROMPT_VERSION, build_request, observe, system_prompt_v8, system_prompt_v9
from hyperbolic.runner import AgentController, RunWriter, load_jsonl, replay_run, run_session

LIVE = Path(__file__).parents[1] / "runs" / "live"
LIVE_0100 = {"20261023T160151Z": 719, "20261023T160150Z": 719, "20261023T160200Z": 743, "20261023T160206Z": 743}


def _battery_hour(obs, top=True, load_now=5.0, forecast=10.0, soc=0.3):
    """Every building with a big load, room in its range and soc of charge, in the last top-price hour or not."""
    obs["price_plan"].update({"top_price_now": top, "flat_24h": False, "top_price_hours_ahead": []})
    obs["peak"].update({"district_load_now_kwh": load_now, "forecast_today_kwh": forecast})
    for b in BUILDINGS:
        s = obs["buildings"][b]
        s["load_now_kwh"] = 5.0
        s["battery"].update({"soc": soc, "soc_floor": 0.2, "max_fraction_per_hour": 1.0, "capacity_kwh": 4.0})
        s["battery_range"] = [-0.5, 0.5]
        s["last_action"] = {"cooling": 0.3, "dhw": 0.0, "battery": 0.0}
    return obs


def test_v9_is_the_default_and_only_adds_shave_now_to_the_v8_observation():
    assert PROMPT_VERSION == 9
    st, ctx, look, env, v9 = _obs(version=9)
    v8 = observe(8, st, ctx, None, look, env)
    assert set(v9) == set(v8) and set(v9["peak"]) == set(v8["peak"]) | {"shave_now"}
    assert "shave_now" not in v8["peak"]  # version 8 requests stay byte for byte, so 0.10.0 runs replay
    for b in BUILDINGS:
        assert set(v9["buildings"][b]) == set(v8["buildings"][b])
    plan = strategy_plan_v9(v9)
    assert v9["strategy_reason"] == plan["reason"]
    for b in BUILDINGS:
        assert v9["buildings"][b]["strategy"] == {d: plan[b][d] for d in ("cooling", "dhw", "battery")}


def test_shave_now_is_the_strategys_own_peak_hour_test():
    sp = StrategyParamsV9()
    st, ctx, look, env, v9 = _obs(version=9)
    pk = v9["peak"]
    want = bool(pk["district_load_now_kwh"] is not None and pk["forecast_today_kwh"]
                and pk["district_load_now_kwh"] >= sp.shave * pk["forecast_today_kwh"])
    assert pk["shave_now"] is want


def test_v9_strategy_is_v8_with_charge_kept_through_the_top_price_hours():
    v8, v9 = asdict(StrategyParamsV8()), asdict(StrategyParamsV9())
    assert {k for k in v8 if v8[k] != v9[k]} == {"evening_reserve"} and v9["evening_reserve"] == 0.01
    *_, obs = _obs(version=9)
    top = _battery_hour(json.loads(json.dumps(obs)), top=True, soc=0.3)
    a, b = strategy_plan_v8(top)["Building_1"]["battery"], strategy_plan_v9(top)["Building_1"]["battery"]
    # The usable charge above the floor is 0.099; version 9 keeps 0.01 of it (both truncate to 3 decimals).
    assert a == pytest.approx(-0.099, abs=1.5e-3) and b - a == pytest.approx(0.01, abs=1.5e-3)
    # After the top price, in a peak hour, the charge left goes to the shave (0.243: tuning July's evening peak).
    shave = _battery_hour(json.loads(json.dumps(obs)), top=False, load_now=12.0, forecast=10.0, soc=0.243)
    assert strategy_plan_v9(shave)["Building_1"]["battery"] < 0 and "shave" in strategy_plan_v9(shave)["reason"].lower()


def test_v9_system_prompt_says_copy_small_numbers_and_shave_after_the_top_price():
    cfg = EnvelopeConfig()
    text, old = system_prompt_v9(cfg, BUILDINGS), system_prompt_v8(cfg, BUILDINGS)
    sp = StrategyParamsV9()
    for phrase in ("Send it as given, every number exactly", "battery -0.033 is not 0",
                   "cooling under baseline_action is not null, trim state off", "after the top price and on",
                   "flat_24h days too, shave when", "peak.shave_now", f"keeping {sp.evening_reserve:g} above the floor",
                   "daily and monthly peak", "whatever charge is left", "That starts a trim when state is off",
                   "never null"):
        assert phrase in " ".join(text.split()), phrase
    # The version 8 lines that read as "no shaving after the top price or on a flat day" are gone.
    assert "Before them discharge only to shave" in old and "Before them" not in text
    assert "Idle on flat_24h days." in old and "Idle on flat_24h days." not in text
    assert chr(0x2014) not in text and "local evaluation" not in text and "strategy_battery" not in text


def test_v9_request_is_within_3_percent_of_v8_with_the_same_reply_schema():
    st, ctx, look, env, v9 = _obs(version=9)
    v8 = observe(8, st, ctx, None, look, env)
    r8 = build_request(v8, env.config, BUILDINGS, "haiku", prompt_version=8)
    r9 = build_request(v9, env.config, BUILDINGS, "haiku", prompt_version=9)
    assert r9["output_config"] == r8["output_config"]
    assert len(json.dumps(r8)) < len(json.dumps(r9)) < 1.03 * len(json.dumps(r8))


def test_scripted_replies_follow_their_own_versions_strategy():
    st, ctx, look, env, v9 = _obs(version=9)
    req = build_request(v9, env.config, BUILDINGS, "haiku", prompt_version=9)
    p, err = parse_reply(ScriptedSupervisor().call(5, req).text, BUILDINGS, end_trim=True)
    assert err is None
    for b in BUILDINGS:
        assert p["buildings"][b] == v9["buildings"][b]["strategy"]
    v8 = observe(8, st, ctx, None, look, env)
    got = json.loads(ScriptedSupervisor().call(5, build_request(v8, env.config, BUILDINGS, "haiku",
                                                                prompt_version=8)).text)
    assert got == json.loads(json.dumps(strategy_plan_v8(v8)))


def test_v9_run_on_the_fake_district_is_clean_and_replays(tmp_path):
    run = tmp_path / "v9"
    ctl = AgentController(ScriptedSupervisor(), Envelope(EnvelopeConfig()), Budget(2.0), prompt_version=9)
    res = run_session(FakeDistrict(), ctl, RunWriter(run), hours=48, log=lambda *_: None)
    assert res["fallback_steps"] == 0 and res["clamped_steps"] == 0 and ctl.describe()["prompt_version"] == 9
    rep = replay_run(run)
    assert rep.deterministic and rep.identical_steps == 48


@needs_citylearn
def test_v9_dry_run_and_replay(tmp_path):
    """24 hours of the scripted version 9 strategy on CityLearn, through the unchanged rules, and replay."""
    from hyperbolic.runner import controller_settings
    from hyperbolic.sim import CityLearnSimulator

    version, cfg = controller_settings(rule_based=True, prompt_version=9)
    assert cfg == EnvelopeConfig()
    ctl = AgentController(ScriptedSupervisor(), Envelope(cfg), Budget(2.0), prompt_version=version)
    run_dir = tmp_path / "v9"
    res = run_session(CityLearnSimulator(control=True), ctl, RunWriter(run_dir), hours=24, log=lambda *_: None,
                      sim_info={"kind": "citylearn", "control": True})
    assert res["steps"] == 24 and res["fallback_steps"] == 0
    assert '"shave_now":' in load_jsonl(run_dir / "calls.jsonl")[5]["request"]["messages"][0]["content"]
    rep = replay_run(run_dir)
    assert rep.deterministic and rep.api_calls == 0 and rep.identical_steps == 24


@pytest.mark.parametrize("stamp, hours", sorted(LIVE_0100.items()))
def test_the_0_10_0_live_months_still_replay_hour_for_hour(stamp, hours):
    runs = sorted(LIVE.glob(f"*_{stamp}")) if LIVE.exists() else []
    if not runs:
        pytest.skip("the 0.10.0 live runs are kept locally in runs/live")
    m = json.loads((runs[0] / "manifest.json").read_text(encoding="utf-8"))
    assert EnvelopeConfig.from_manifest(m["envelope"]) == EnvelopeConfig() and m["supervisor"]["prompt_version"] == 8
    rep = replay_run(runs[0])
    assert rep.deterministic and rep.identical_steps == hours and rep.api_calls == 0
