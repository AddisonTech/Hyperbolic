"""Observation building and the request sent to the model each hour."""

from __future__ import annotations

import json

from . import testcase as tc
from .envelope import Decision, EnvelopeConfig, proposal_json_schema
from .model import DEFAULT_EFFORT, DEFAULT_MAX_TOKENS, MODELS

FORECAST_HOURS = 12


def _r(v, nd=2):
    return None if v is None else round(float(v), nd)


def build_observation(
    y: dict[str, float],
    forecast: dict[str, list[float]],
    last: Decision | None,
    electricity_price: str = tc.DEFAULT_ELECTRICITY_PRICE,
) -> dict:
    """Compact, rounded view of the current state. Rounding keeps requests stable for replay."""
    t = float(y["time"])
    stock_h, stock_c = tc.stock_zone_setpoints_c(t)
    zones = {}
    for z in tc.ZONES:
        zones[z] = {
            "temp_c": _r(tc.k_to_c(y[tc.zone_temp_point(z)])),
            "co2_ppm": _r(y.get(tc.zone_co2_point(z)), 0),
        }
    price_key = tc.PRICE_POINT[electricity_price]
    n = min(FORECAST_HOURS, len(forecast.get("time", [])))
    fc = []
    for i in range(n):
        ft = float(forecast["time"][i])
        fc.append({
            "hours_ahead": i,
            "hour_of_day": tc.hour_of_day(ft),
            "outdoor_c": _r(tc.k_to_c(forecast["TDryBul"][i]), 1),
            "solar_w_m2": _r(forecast["HGloHor"][i], 0),
            "price": _r(forecast[price_key][i], 4),
            "occupants": int(round(sum(forecast[f"Occupancy[{z}]"][i] for z in tc.ZONES))),
            "band_lower_c": _r(tc.k_to_c(forecast["LowerSetp[cor]"][i]), 1),
            "band_upper_c": _r(tc.k_to_c(forecast["UpperSetp[cor]"][i]), 1),
        })
    power_w = sum(float(y.get(p, 0.0) or 0.0) for p in tc.POWER_POINTS)
    band_lo = fc[0]["band_lower_c"] if fc else stock_h
    band_hi = fc[0]["band_upper_c"] if fc else stock_c
    return {
        "time_s": int(t),
        "day_of_year": int(t // 86400),
        "hour": tc.hour_of_day(t),
        "occupied_now": tc.is_occupied_hour(t),
        "outdoor_temp_c": _r(tc.k_to_c(y[tc.OUTDOOR_TEMP_POINT]), 1),
        "supply_air_temp_c": _r(tc.k_to_c(y[tc.SUPPLY_AIR_TEMP_POINT])),
        "hvac_power_kw": _r(power_w / 1000.0),
        "comfort_band_c": {"lower": band_lo, "upper": band_hi},
        "stock_setpoints_c": {"heat": stock_h, "cool": stock_c, "supply_air": tc.STOCK_SUPPLY_AIR_OCCUPIED_C},
        "zones": zones,
        "last_applied": {
            "heat_c": {z: (None if last is None else _r(last.heat_c[z])) for z in tc.ZONES},
            "cool_c": {z: (None if last is None else _r(last.cool_c[z])) for z in tc.ZONES},
            "supply_air_c": None if last is None else _r(last.supply_air_c),
            "status": None if last is None else last.status,
            "clamps": [] if last is None else [f"{c.point}: {c.reason}" for c in last.clamps][:6],
        },
        "forecast": fc,
    }


def system_prompt(cfg: EnvelopeConfig) -> str:
    return f"""You are the hourly supervisory controller for a simulated office floor in Chicago \
(BOPTEST test case {tc.TESTCASE}): five zones (north, east, south, west perimeter and a large core) \
on one VAV air handler with hot water reheat from an air-to-water heat pump and cooling from an \
air-cooled chiller. Local loops (dampers, valves, fan, economizer) are handled by the stock sequence. \
You only choose supervisory setpoints for the next hour.

Goal, graded by BOPTEST KPIs over a two-week test: lower operating cost under a time-of-use \
electricity price and lower energy use, without more thermal discomfort than the stock control. \
Discomfort is counted whenever a zone is outside the comfort band (occupied 06:00 to 19:00).

What you can set, in degC. Use null to leave a point to the stock control:
- per zone heat_c and cool_c (stock: 20/24 occupied, 12/30 unoccupied)
- supply_air_c, the AHU supply air temperature setpoint (stock: 12 when occupied). Raising it in cold \
weather cuts reheat; lowering it pre-cools.

A safety envelope checks every value before it is written. It will clamp:
- zone heating to {cfg.zone_heat_min_c:g} to {cfg.zone_heat_max_c:g}, zone cooling to \
{cfg.zone_cool_min_c:g} to {cfg.zone_cool_max_c:g}, supply air to {cfg.supply_air_min_c:g} to \
{cfg.supply_air_max_c:g} and only during occupied hours
- any move larger than {cfg.zone_rate_k_per_step:g} K per hour for zones and \
{cfg.supply_rate_k_per_step:g} K per hour for supply air, measured from last hour's value or from \
the stock schedule's own step
- heating below the comfort band lower limit or cooling above its upper limit
- cooling less than {cfg.min_deadband_k:g} K above heating
An invalid reply hands every point back to the stock control for that hour. Clamps are logged \
against you, so stay inside the limits.

Reply with one JSON object only, matching the schema. "reason" is one short plain sentence a \
building operator would understand."""


def user_message(obs: dict) -> str:
    return (
        "Current state and forecast. Values in degC, W/m2, $/kWh, kW.\n"
        "OBSERVATION_JSON\n" + json.dumps(obs, separators=(",", ":"), sort_keys=True)
    )


def build_request(obs: dict, cfg: EnvelopeConfig, model_key: str,
                  max_tokens: int = DEFAULT_MAX_TOKENS, effort: str = DEFAULT_EFFORT) -> dict:
    return {
        "model": MODELS[model_key]["id"],
        "max_tokens": max_tokens,
        "system": system_prompt(cfg),
        "messages": [{"role": "user", "content": user_message(obs)}],
        "output_config": {
            "effort": effort,
            "format": {"type": "json_schema", "schema": proposal_json_schema()},
        },
    }
