"""Observation building and the request sent to the model each hour."""

from __future__ import annotations

import json

from . import district as dc
from .envelope import Decision, EnvelopeConfig, StepContext, proposal_json_schema
from .model import DEFAULT_EFFORT, DEFAULT_MAX_TOKENS, MODELS


def _r(v, nd=3):
    return None if v is None else round(float(v), nd)


def build_observation(state: dict, ctx: StepContext, last: Decision | None) -> dict:
    """Compact, rounded view of the district this hour. Rounding keeps requests stable for replay."""
    shared = state["shared"]
    buildings = {}
    for b, s in state["buildings"].items():
        st = ctx.buildings[b]
        buildings[b] = {
            "indoor_c": _r(s["indoor_c"], 2),
            "setpoint_c": _r(s["setpoint_c"], 2),
            "comfort_band_c": [_r(s["setpoint_c"] - dc.COMFORT_BAND_K, 2), _r(s["setpoint_c"] + dc.COMFORT_BAND_K, 2)],
            "occupants": _r(s["occupants"], 1),
            "cooling_demand_kwh": _r(s["cooling_demand_kwh"]),
            "dhw_demand_kwh": _r(s["dhw_demand_kwh"]),
            "plug_load_kwh": _r(s["plug_load_kwh"]),
            "solar_kwh": _r(s["solar_kwh"]),
            "battery_soc": _r(s["battery_soc"]),
            "dhw_soc": _r(s["dhw_soc"]),
            "grid_kwh_last_hour": _r(s["grid_kwh"]),
            "power_outage": bool(s.get("power_outage", False)),
            "baseline_action": {d: _r(v) for d, v in st.baseline.items()},
            "last_action": None if last is None else {
                d: _r(st.baseline[d] if last.actions.get(b, {}).get(d) is None else last.actions[b][d])
                for d in st.baseline},
        }
    return {
        "time_step": state["time_step"],
        "hour": shared["hour"],
        "day_type": shared["day_type"],
        "outdoor_c": _r(shared["outdoor_c"], 1),
        "outdoor_c_next_1_2_3h": [_r(v, 1) for v in shared["outdoor_c_forecast"]],
        "solar_w_m2_direct_now_and_next_3h": [_r(v, 0) for v in shared["direct_solar_forecast"]],
        "price_per_kwh_now_and_next_3h": [_r(v, 4) for v in shared["price_forecast"]],
        "carbon_kg_per_kwh": _r(shared["carbon_intensity"], 4),
        "last_status": None if last is None else last.status,
        "last_clamps": [] if last is None else [f"{c.point}: {c.reason}" for c in last.clamps][:6],
        "buildings": buildings,
    }


def system_prompt(cfg: EnvelopeConfig, buildings: tuple[str, ...]) -> str:
    return f"""You are the hourly supervisory controller for a simulated district of {len(buildings)} \
buildings ({dc.DATASET_NAME}, CityLearn). Each building has a heat pump for space cooling, a hot water \
tank, a battery and rooftop solar. Every hour you choose one action per device for every building.

Goal, graded by CityLearn's own KPIs over the episode: lower electricity cost under the time-varying \
price and lower carbon emissions than the no-control reference (no storage use, heat pump meeting the \
ideal load), without more discomfort. Discomfort is any occupied hour with indoor temperature outside \
setpoint +/- {cfg.comfort_band_k:g} C.

Actions per building, use null to keep the baseline action:
- cooling: heat pump power as a fraction of nominal, {cfg.cooling_min:g} to {cfg.cooling_max:g}. The \
baseline_action is the fraction that meets the ideal cooling load.
- dhw: hot water tank, fraction of capacity to charge (+) or discharge (-) this hour. Baseline 0.
- battery: fraction of battery capacity to charge (+) or discharge (-) this hour. Baseline 0.

A safety envelope checks every value before it is applied. It will clamp:
- any value outside its range or CityLearn's action space
- any move larger than {cfg.cooling_rate_per_step:g} (cooling), {cfg.dhw_rate_per_step:g} (dhw) or \
{cfg.battery_rate_per_step:g} (battery) per hour, measured from last hour's action or this hour's baseline
- charge that would leave a battery or tank outside {cfg.soc_min:g} to {cfg.soc_max:g} state of charge
- in occupied hours within {cfg.comfort_margin_k:g} C of a comfort band edge, cooling below the baseline \
when warm or above it when cool
An invalid reply uses the baseline action everywhere for that hour. Clamps are logged against you.

Reply with one JSON object only, matching the schema. "reason" is one short plain sentence a \
building operator would understand."""


def user_message(obs: dict) -> str:
    return (
        "District state this hour. Energy in kWh, temperatures in C, price in $/kWh.\n"
        "OBSERVATION_JSON\n" + json.dumps(obs, separators=(",", ":"), sort_keys=True)
    )


def build_request(obs: dict, cfg: EnvelopeConfig, buildings: tuple[str, ...], model_key: str,
                  max_tokens: int = DEFAULT_MAX_TOKENS, effort: str = DEFAULT_EFFORT) -> dict:
    return {
        "model": MODELS[model_key]["id"],
        "max_tokens": max_tokens,
        "system": system_prompt(cfg, buildings),
        "messages": [{"role": "user", "content": user_message(obs)}],
        "output_config": {
            "effort": effort,
            "format": {"type": "json_schema", "schema": proposal_json_schema(buildings)},
        },
    }
