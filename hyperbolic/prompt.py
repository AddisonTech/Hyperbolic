"""Observation building and the request sent to the model each hour.

Prompt versions are kept side by side so recorded runs replay byte for byte:
  1  v0.2.0. Forecasts were labeled as the next 1, 2 and 3 hours, though CityLearn's are
     6, 12 and 24 hours ahead, and there was no carbon outlook or strategy.
  2  v0.3.0. A 24 hour price and carbon outlook built only from values already observed,
     storage sizes and state of charge, and a plain strategy.
  3  v0.4.0. Adds the district peak (load now, today's and the month's peaks, the
     limiter's target and headroom), a combined price and carbon signal with its
     outlook, hours left in the month, and a strategy in priority order: comfort,
     peak cap, then cost and carbon. Asks for shorter reasons.
  4  v0.6.0. Adds the 0.4.0 rule-based controller's plan for the hour as a reference
     action, a price plan (the 24 hour top and low, whether this is a top-price hour,
     the top-price hours ahead), whether grid charging pays back the battery's losses
     (the envelope's spread check), the battery's real charge floor and usable energy,
     and how far each room is from its setpoint, now that the indoor temperature is the
     one CityLearn simulated. The strategy puts price first and carbon second, holds the
     battery for the top-price hours, and trims cooling in rooms that are too cold.
  5  v0.7.0. Adds what smoothing needs: last hour's measured district draw, the district
     load before storage now and (as yesterday) at the next hour, and each building's
     cooling trim last hour. The strategy holds a trim until the
     room is nearly back at its setpoint and eases it off slowly, starts grid charging
     small and raises it a little each hour, and spreads discharge over the top-price hours.
  6  v0.8.0. The envelope holds a cooling trim in code (EnvelopeConfig.trim_hold), and the
     prompt says so: null keeps a held trim, and the reply's new end_trim field, with a
     reason, is the only way to end one early. The 0.4.0 rule-based reference_action is
     replaced by the version 5 strategy's own battery action per building
     (strategy_battery, with strategy_battery_reason), and each building shows the trim the
     envelope will keep this hour (cooling_trim_held).
  7  v0.9.0. Each building shows what the envelope allows this hour, so a reply can fit it:
     the trim (depth, hold state and why, the least depth it may run, whether end_trim may
     be used), cooling_range and battery_range, and last hour's clamps on that building
     with their reasons (in place of the district-wide last_clamps). null is described as
     exactly the baseline, so a held trim is sent as a number. strategy_battery comes from
     battery_plan_v7, version 5's plan with the shipped numbers, and a model that differs
     from it is asked to stay close. The envelope's rules are the same as for version 6.
  8  v0.10.0. Each building shows the version 8 strategy's whole action for the hour (strategy:
     cooling, dhw and battery, with strategy_reason) in place of strategy_battery, since the
     0.9.0 live month followed strategy_battery but rarely started a cooling trim itself. The
     strategy adds extra cooling in an occupied room that runs warm (the hot-side fix), and
     signal_outlook is dropped. The envelope's rules are the same as for version 6.
  9  v0.11.0. The 0.10.0 live months sent strategy almost everywhere, but sent null where it
     started a trim (state off) and left the batteries idle where it shaved after the top-price
     hours or on a flat-price day, as the version 8 wording allowed ("Before them discharge only to
     shave", "Idle on flat_24h days"); the July and August all-time peaks fell in such hours.
     Version 9 says to send every number, a trim start and a small shave too, and to shave in any
     hour peak.shave_now (new) is true, and its strategy keeps a little charge for that shave. The
     envelope's rules are the same as for version 6.
"""

from __future__ import annotations

import json
import math

from . import district as dc
from .envelope import Decision, Envelope, EnvelopeConfig, StepContext, proposal_json_schema
from .model import (
    DEFAULT_EFFORT,
    DEFAULT_MAX_TOKENS,
    MODELS,
    StrategyParams,
    StrategyParamsV5,
    StrategyParamsV7,
    StrategyParamsV8,
    StrategyParamsV9,
    battery_plan_v5,
    battery_plan_v7,
    rule_plan_v3,
    strategy_plan_v8,
    strategy_plan_v9,
)
from .signals import charge_spread, combined_signal


PROMPT_VERSION = 9
PROMPT_VERSIONS = (1, 2, 3, 4, 5, 6, 7, 8, 9)
# From this version the reply may end a held cooling trim early (envelope trim hold, 0.8.0).
END_TRIM_FROM = 6


def end_trim_field(version: int) -> bool:
    """Whether replies to this prompt version carry end_trim per building."""
    return version >= END_TRIM_FROM


def _r(v, nd=3):
    return None if v is None else round(float(v), nd)


class Lookahead:
    """A 24 hour price and carbon outlook from what the controller has already seen.

    Price: CityLearn's price forecasts are exact, and each hour brings values 6, 12 and 24
    hours ahead, so after one day every one of the next 24 hours is covered by a forecast
    received earlier. Hours not covered yet fall back to the same hour yesterday.
    Carbon: the dataset has no carbon forecast, so the outlook is the same hour yesterday.
    Nothing here reads the dataset directly, so there is no peeking at the future.
    """

    def __init__(self, hours: int = dc.LOOKAHEAD_HOURS) -> None:
        self.hours = hours
        self.price: dict[int, float] = {}
        self.carbon: dict[int, float] = {}

    def update(self, state: dict) -> None:
        t = int(state["time_step"])
        shared = state["shared"]
        horizons = shared.get("forecast_horizons_h") or [0, *dc.FORECAST_HORIZONS_H]
        for h, v in zip(horizons, shared["price_forecast"]):
            self.price[t + int(h)] = float(v)
        self.carbon[t] = float(shared["carbon_intensity"])

    def outlook(self, t: int) -> dict:
        price, carbon, src = [], [], []
        for j in range(1, self.hours + 1):
            if t + j in self.price:
                price.append(self.price[t + j])
                src.append("f")
            elif t + j - 24 in self.price:
                price.append(self.price[t + j - 24])
                src.append("y")
            else:
                price.append(None)
                src.append("-")
            carbon.append(self.carbon.get(t + j - 24))
        return {"price": price, "carbon": carbon, "price_source": "".join(src)}


def _rank(now: float, ahead: list) -> float | None:
    """Share of the coming hours that are cheaper (or cleaner) than now: 0 is the best hour of the day."""
    known = [v for v in ahead if v is not None]
    if not known:
        return None
    return round(sum(1 for v in known if v < now - 1e-9) / len(known), 2)


def _summary(now: float, ahead: list, nd: int) -> dict:
    known = [(i + 1, v) for i, v in enumerate(ahead) if v is not None]
    if not known:
        return {"now": _r(now, nd), "rank_now": None, "min": None, "max": None, "hours_to_min": None,
                "hours_to_max": None}
    lo = min(known, key=lambda x: (x[1], x[0]))
    hi = max(known, key=lambda x: (x[1], -x[0]))
    return {"now": _r(now, nd), "rank_now": _rank(now, ahead), "min": _r(lo[1], nd), "max": _r(hi[1], nd),
            "hours_to_min": lo[0], "hours_to_max": hi[0]}


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


def build_observation_v2(state: dict, ctx: StepContext, last: Decision | None, look: Lookahead) -> dict:
    """Version 2: correct forecast horizons, a 24 hour outlook and storage detail."""
    shared = state["shared"]
    t = int(state["time_step"])
    out = look.outlook(t)
    price_now, carbon_now = float(shared["price_forecast"][0]), float(shared["carbon_intensity"])
    hz = shared.get("forecast_horizons_h") or [0, *dc.FORECAST_HORIZONS_H]
    hour = int(shared["hour"])
    buildings = {}
    for b, s in state["buildings"].items():
        st = ctx.buildings[b]
        cap = float(s.get("battery_capacity_kwh") or 0.0)
        power = float(s.get("battery_power_kw") or 0.0)
        last_act = None if last is None else {
            d: _r(st.baseline[d] if last.actions.get(b, {}).get(d) is None else last.actions[b][d]) for d in st.baseline}
        buildings[b] = {
            "indoor_c": _r(s["indoor_c"], 2),
            "setpoint_c": _r(s["setpoint_c"], 2),
            "comfort_band_c": [_r(s["setpoint_c"] - dc.COMFORT_BAND_K, 2), _r(s["setpoint_c"] + dc.COMFORT_BAND_K, 2)],
            "occupied": st.occupied,
            "occupants": _r(s["occupants"], 1),
            "cooling_demand_kwh": _r(s["cooling_demand_kwh"]),
            "dhw_demand_kwh": _r(s["dhw_demand_kwh"]),
            "plug_load_kwh": _r(s["plug_load_kwh"]),
            "solar_kwh": _r(s["solar_kwh"]),
            "grid_kwh_last_hour": _r(s["grid_kwh"]),
            "battery": {"soc": _r(s["battery_soc"]), "capacity_kwh": _r(cap, 2),
                        "max_fraction_per_hour": _r(min(1.0, power / cap) if cap > 0 else 0.0, 2)},
            "dhw_tank": {"soc": _r(s["dhw_soc"]), "capacity_kwh": _r(s.get("dhw_capacity_kwh"), 2)},
            "power_outage": bool(s.get("power_outage", False)),
            "baseline_action": {d: _r(v) for d, v in st.baseline.items()},
            "last_action": last_act,
        }
    return {
        "time_step": t,
        "hour": hour,
        "day_type": shared["day_type"],
        "outdoor_c": _r(shared["outdoor_c"], 1),
        "outdoor_c_forecast": {f"in_{h}h": _r(v, 1) for h, v in zip(hz[1:], shared["outdoor_c_forecast"])},
        "price_outlook": _summary(price_now, out["price"], 4),
        "carbon_outlook": _summary(carbon_now, out["carbon"], 3),
        "next_24h": {
            "hour": [(hour - 1 + j) % 24 + 1 for j in range(1, look.hours + 1)],
            "price": [_r(v, 4) for v in out["price"]],
            "carbon": [_r(v, 3) for v in out["carbon"]],
            "price_source": out["price_source"],
        },
        "last_status": None if last is None else last.status,
        "last_clamps": [] if last is None else [f"{c.point}: {c.reason}" for c in last.clamps][:6],
        "buildings": buildings,
    }


def system_prompt_v2(cfg: EnvelopeConfig, buildings: tuple[str, ...]) -> str:
    dev = ("" if cfg.cooling_max_deviation is None else
           f"\n- cooling more than {cfg.cooling_max_deviation:g} away from the baseline_action")
    guard = ("\n- extra cooling in an unoccupied building already near the bottom of its band"
             if cfg.overcool_guard_unoccupied else "")
    return f"""You are the hourly supervisory controller for a simulated district of {len(buildings)} \
buildings ({dc.DATASET_NAME}, CityLearn). Each building has a heat pump for space cooling, a hot water \
tank, a battery and rooftop solar. Every hour you choose one action per device for every building.

Goal, graded by CityLearn's own KPIs over the month: lower electricity cost and lower carbon emissions \
than the no-control reference (storage idle, heat pump meeting the ideal load), with no more discomfort. \
Discomfort is any occupied hour with indoor temperature outside setpoint +/- {cfg.comfort_band_k:g} C. \
Holding every action at the baseline only ties the reference; storage is where the savings are.

What you see:
- price_outlook and carbon_outlook: now, the min and max over the next 24 hours, how many hours until \
each, and rank_now (0 means this is the cheapest or cleanest hour of the coming day, 1 the worst).
- next_24h: hour of day, price and carbon for each of the next 24 hours. Price comes from CityLearn's \
exact forecasts (price_source "f") or the same hour yesterday ("y"); carbon is always the same hour \
yesterday, so treat it as a guide. null means not known yet.
- outdoor_c_forecast is 6, 12 and 24 hours ahead and carries forecast error.
- grid_kwh_last_hour is the building's net draw last hour, after solar and storage. Power sent back \
to the grid earns nothing, so discharge only what the building itself will use.

Strategy:
1. Battery. Charge in the cheapest, cleanest hours (low rank_now on both) and with solar the \
building is not using, so it is near full before the daily price peak. Discharge into the peak hours \
(price near the 24 hour max), sized to the building's own load, and keep a little charge for outages. \
Round trip losses are about 10 to 20 percent, so a small price gap is not worth cycling.
2. Hot water tank. Mostly leave it at 0. Its standing losses usually cost more than the price gap \
saves; use it only for a clear, large spike with hot water demand in it.
3. Cooling. Default to null (the baseline_action). Pre-cooling and easing off in a spike tend to push \
occupied hours out of the comfort band. If you do it, keep it small (about +0.05 in the one or two \
occupied hours before a spike) and only when the room is well inside its band.
4. When nothing stands out, hold storage and use null for cooling.

Actions per building, use null to keep the baseline action:
- cooling: heat pump power as a fraction of nominal, {cfg.cooling_min:g} to {cfg.cooling_max:g}. The \
baseline_action is the fraction that meets the ideal cooling load.
- dhw: hot water tank, fraction of capacity to charge (+) or discharge (-) this hour. Baseline 0.
- battery: fraction of battery capacity to charge (+) or discharge (-) this hour. Baseline 0. \
max_fraction_per_hour is the most the battery can move in an hour.

A safety envelope checks every value before it is applied. It will clamp:
- any value outside its range or CityLearn's action space
- any move larger than {cfg.cooling_rate_per_step:g} (cooling), {cfg.dhw_rate_per_step:g} (dhw) or \
{cfg.battery_rate_per_step:g} (battery) per hour, measured from last hour's action or this hour's baseline
- charge that would leave a battery or tank outside {cfg.soc_min:g} to {cfg.soc_max:g} state of charge{dev}
- in occupied hours within {cfg.comfort_margin_k:g} C of a comfort band edge, cooling below the baseline \
when warm or above it when cool{guard}
An invalid reply uses the baseline action everywhere for that hour. Clamps are logged against you.

Reply with one JSON object only, matching the schema. "reason" is one short plain sentence a \
building operator would understand."""


def _hours(values: list, pick, n: int = 4) -> list[int]:
    """Hours ahead (1 to 24) of the n lowest or highest known values, earliest first on ties."""
    known = [(i + 1, v) for i, v in enumerate(values) if v is not None]
    chosen = sorted(known, key=lambda x: (pick(x[1]), x[0]))[:n]
    return sorted(h for h, _ in chosen)


def build_observation_v3(state: dict, ctx: StepContext, last: Decision | None, look: Lookahead,
                         envelope: Envelope | None) -> dict:
    """Version 3: version 2 plus the district peak, the combined signal and the month's end."""
    obs = build_observation_v2(state, ctx, last, look)
    t = int(state["time_step"])
    out = look.outlook(t)
    shared = state["shared"]
    sig = combined_signal([float(shared["price_forecast"][0]), *out["price"]],
                          [float(shared["carbon_intensity"]), *out["carbon"]])
    now, ahead = sig[0], sig[1:]
    obs["signal_outlook"] = {
        "weights": dict(dc.SIGNAL_WEIGHTS),
        "now": _r(now, 2),
        "rank_now": None if now is None else _rank(now, ahead),
        "next_24h": [_r(v, 2) for v in ahead],
        "lowest_hours_ahead": _hours(ahead, lambda v: v),
        "highest_hours_ahead": _hours(ahead, lambda v: -v),
    }
    pk = ctx.peak
    target = None if envelope is None else envelope.peak_target(ctx)
    load_now = None if pk is None else pk.load_now_kwh
    obs["peak"] = {
        "district_load_now_kwh": _r(load_now, 2),
        "target_kwh": _r(target, 2),
        "headroom_kwh": None if target is None or load_now is None else _r(max(0.0, target - load_now), 2),
        "forecast_today_kwh": None if pk is None else _r(pk.forecast_peak_kwh, 2),
        "today_peak_so_far_kwh": None if pk is None else _r(pk.today_grid_peak_kwh, 2),
        "month_peak_so_far_kwh": None if pk is None else _r(pk.month_grid_peak_kwh, 2),
        "limiter_on": bool(envelope is not None and envelope.config.peak_limit),
    }
    # The dataset's own month end; states recorded before 0.6.0 carry none and used EPISODE_HOURS.
    obs["hours_left_in_month"] = max(0, int(shared.get("episode_end_step", dc.EPISODE_HOURS)) - t)
    for b, s in state["buildings"].items():
        obs["buildings"][b]["load_now_kwh"] = _r(s.get("load_kwh"), 3)
    return obs


def system_prompt_v3(cfg: EnvelopeConfig, buildings: tuple[str, ...]) -> str:
    dev = ("" if cfg.cooling_max_deviation is None else
           f"\n- cooling more than {cfg.cooling_max_deviation:g} away from the baseline_action")
    guard = ("\n- extra cooling in an unoccupied building already near the bottom of its band"
             if cfg.overcool_guard_unoccupied else "")
    peak = ("\n- after all of that, battery then tank charging, so district load stays at or below "
            "peak.target_kwh" if cfg.peak_limit else "")
    w = dc.SIGNAL_WEIGHTS
    return f"""You are the hourly supervisory controller for a simulated district of {len(buildings)} \
buildings ({dc.DATASET_NAME}, CityLearn). Each building has a heat pump for space cooling, a hot water \
tank, a battery and rooftop solar. Every hour you choose one action per device for every building.

Goals, in this order, graded by CityLearn's own KPIs over the month against the no-control reference \
(storage idle, heat pump meeting the ideal load):
1. Comfort: no more discomfort than the reference. Discomfort is any occupied hour with indoor \
temperature outside setpoint +/- {cfg.comfort_band_k:g} C.
2. Peaks: the district's daily peak and the month's peak at or below the reference's.
3. Cost and carbon: lower electricity cost and lower emissions than the reference.

What you see:
- peak: district_load_now_kwh is the district's draw this hour before any storage move. target_kwh is \
the most the district may draw this hour; headroom_kwh is how much charging fits under it. \
forecast_today_kwh is the expected peak of the day; today_peak_so_far_kwh and month_peak_so_far_kwh \
are measured draws.
- signal_outlook: one number per hour, {w["price"]:g} x price plus {w["carbon"]:g} x carbon intensity, \
each scaled 0 to 1 over now and the next 24 hours. 0 is the cheapest, cleanest hour in view, 1 the \
worst. rank_now is the share of the next 24 hours that are better than now. lowest_hours_ahead and \
highest_hours_ahead list hours ahead.
- price_outlook, carbon_outlook and next_24h: the raw values. Price comes from exact forecasts; carbon \
is the same hour yesterday, a guide only. Many hours share the lowest price, so use the signal, not \
price alone, to pick charging hours.
- buildings: load_now_kwh is each building's draw this hour before storage; battery and dhw_tank give \
charge, capacity and max_fraction_per_hour. Power sent back to the grid earns nothing.
- hours_left_in_month: charge left in a battery at the end of the month is wasted.

Strategy:
1. Comfort. Use null for cooling (the baseline_action) unless you have a clear reason. Never cool \
less in an occupied building near the top of its band.
2. Peak cap. Never charge more than headroom_kwh allows across the district, and never charge in \
the hours when district load is near forecast_today_kwh. When load nears the forecast peak, \
discharging the battery to cover the building's own load lowers the peak.
3. Cost and carbon. Charge the battery only in hours with a low signal (rank_now near 0), and \
spread it: about 0.1 to 0.25 of capacity per hour over several of the lowest hours, not one burst. \
Discharge into the highest-signal hours, sized to load_now_kwh. Round trip losses are about 10 \
percent, so only cycle when the gap between charge and discharge hours is large. Stop charging from \
the grid when the charge cannot be used before the month ends. Leave the hot water tank at 0.

Actions per building, use null to keep the baseline action:
- cooling: heat pump power as a fraction of nominal, {cfg.cooling_min:g} to {cfg.cooling_max:g}.
- dhw: hot water tank, fraction of capacity to charge (+) or discharge (-) this hour. Baseline 0.
- battery: fraction of battery capacity to charge (+) or discharge (-) this hour. Baseline 0.

A safety envelope checks every value before it is applied. It will clamp:
- any value outside its range or CityLearn's action space
- any move larger than {cfg.cooling_rate_per_step:g} (cooling), {cfg.dhw_rate_per_step:g} (dhw) or \
{cfg.battery_rate_per_step:g} (battery) per hour, measured from last hour's action or this hour's baseline
- charge that would leave a battery or tank outside {cfg.soc_min:g} to {cfg.soc_max:g} state of charge{dev}
- in occupied hours within {cfg.comfort_margin_k:g} C of a comfort band edge, cooling below the baseline \
when warm or above it when cool{guard}{peak}
An invalid reply uses the baseline action everywhere for that hour. Clamps are logged against you.

Reply with one JSON object only, matching the schema. "reason" is one plain sentence of at most \
{dc.REASON_TARGET_CHARS} characters. A reason over {dc.REASON_MAX_CHARS} characters makes the whole \
reply invalid."""


def build_observation_v4(state: dict, ctx: StepContext, last: Decision | None, look: Lookahead,
                         envelope: Envelope | None) -> dict:
    """Version 4: version 3 plus the rule-based reference action, the price plan, the spread
    check's verdict and the battery's real limits."""
    obs = build_observation_v3(state, ctx, last, look, envelope)
    reference = rule_plan_v3(obs)
    t = int(state["time_step"])
    now = float(state["shared"]["price_forecast"][0])
    ahead = [(j, p) for j, p in enumerate(look.outlook(t)["price"], start=1) if p is not None]
    top = max([now] + [p for _, p in ahead])
    low = min([now] + [p for _, p in ahead])
    spread_on = envelope is None or envelope.config.spread_check
    obs["price_plan"] = {
        "now": _r(now, 4),
        "top_24h": _r(top, 4),
        "low_24h": _r(low, 4),
        "flat_24h": top - low < 1e-9,
        "top_price_now": top - low >= 1e-9 and now >= top - 1e-9,
        "top_price_hours_ahead": [j for j, p in ahead if top - low >= 1e-9 and p >= top - 1e-9][:6],
    }
    for b, s in state["buildings"].items():
        st = ctx.buildings[b]
        ob = obs["buildings"][b]
        cap = float(s.get("battery_capacity_kwh") or 0.0)
        floor = float(s.get("battery_soc_floor") or 0.0)
        pays = None
        if spread_on and ctx.prices is not None and st.battery_round_trip_min is not None:
            sp = charge_spread(ctx.prices, st.battery_round_trip_min, st.battery_loss_per_hour or 0.0)
            pays = None if sp is None else not sp.blocked
        ob["indoor_vs_setpoint_c"] = _r(float(s["indoor_c"]) - float(s["setpoint_c"]), 2)
        ob["battery"].update({
            "soc_floor": _r(floor, 2),
            "usable_kwh": _r(max(0.0, float(s["battery_soc"]) - floor) * cap, 2),
            "round_trip_min": _r(st.battery_round_trip_min, 2),
            "grid_charging_ok": pays,
        })
        ob["reference_action"] = reference[b]
    obs["reference_reason"] = reference["reason"]
    return obs


def system_prompt_v4(cfg: EnvelopeConfig, buildings: tuple[str, ...]) -> str:
    dev = ("" if cfg.cooling_max_deviation is None else
           f"\n- cooling more than {cfg.cooling_max_deviation:g} away from the baseline_action")
    guard = ("\n- extra cooling in an unoccupied building already near the bottom of its band"
             if cfg.overcool_guard_unoccupied else "")
    peak = ("\n- battery then tank charging, so district load stays at or below peak.target_kwh"
            if cfg.peak_limit else "")
    spread = ("\n- grid charging of a battery when grid_charging_ok is false (spare solar may still be stored)"
              if cfg.spread_check else "")
    sp = StrategyParams()  # the strategy's numbers, chosen on the tuning dataset
    full = sp.cold_margin_c + sp.cold_ramp_c
    return f"""You are the hourly supervisory controller for a simulated district of {len(buildings)} \
buildings ({dc.DATASET_NAME}, CityLearn). Each building has a heat pump for space cooling, a hot water \
tank, a battery and rooftop solar. Every hour you choose one action per device for every building.

Goals, in this order, graded by CityLearn's own KPIs over the month against the no-control reference \
(storage idle, heat pump meeting the ideal load):
1. Comfort: no more discomfort than the reference. Discomfort is any occupied hour with indoor \
temperature outside setpoint +/- {cfg.comfort_band_k:g} C.
2. Peaks: keep the district's daily peak, its hour to hour swings and its daily load factor at or \
better than the reference.
3. Cost first, then carbon: lower electricity cost and lower emissions than the reference. Each \
building's cost counts equally, whatever its size.

What you see:
- reference_action in each building: what the 0.4.0 rule-based controller would do this hour, \
with reference_reason. It is the bar to beat on cost and carbon. Compare your plan with it: where \
you differ, a point of the strategy below should say why.
- price_plan: the price now, the 24 hour top and low, top_price_now (this is one of the most \
expensive hours), top_price_hours_ahead (hours ahead at the top price) and flat_24h (no price \
difference in view, as on weekends).
- battery: soc, soc_floor (the battery cannot go below it), usable_kwh above the floor, capacity, \
max_fraction_per_hour, round_trip_min (the share of a charge that comes back at worst) and \
grid_charging_ok (false when no price in the next 24 hours pays back the losses and a cheaper \
hour is still coming).
- indoor_c is the measured room temperature; indoor_vs_setpoint_c is how far it is from the setpoint.
- peak: district_load_now_kwh before storage, target_kwh, headroom_kwh, forecast_today_kwh.
- signal_outlook and next_24h: price and carbon by hour. Carbon is the same hour yesterday.

Strategy:
1. Comfort and cooling. An occupied room more than {sp.cold_margin_c:g} C below its setpoint is \
overcooled: cut its cooling below baseline_action, gradually, from 0 at {sp.cold_margin_c:g} C below \
the setpoint to {sp.cold_trim:g} at {full:g} C or more below. It saves power and discomfort. Never \
cool less when the room is at or above its setpoint. Otherwise use null.
2. Hold the battery for the top-price hours. Discharge when top_price_now is true, sized to the \
building's load_now_kwh (power sent back to the grid earns nothing). Do not discharge in cheaper \
hours before them, except to keep district load down: once district_load_now_kwh reaches \
{sp.shave:g} x forecast_today_kwh, discharge to cover the building's own load. On flat_24h days \
leave the battery idle.
3. Charge so each battery is near {sp.soc_target:g} when the top-price hours start: only when \
grid_charging_ok is true, in the cheapest hours with the lowest carbon (usually the early \
morning), about {sp.charge_rate:g} of capacity per hour spread over several hours, within \
headroom_kwh. Store spare solar any time.
4. Never charge at the top price. Leave the hot water tank at 0.

Actions per building, use null to keep the baseline action:
- cooling: heat pump power as a fraction of nominal, {cfg.cooling_min:g} to {cfg.cooling_max:g}.
- dhw: hot water tank, fraction of capacity to charge (+) or discharge (-) this hour. Baseline 0.
- battery: fraction of battery capacity to charge (+) or discharge (-) this hour. Baseline 0.

A safety envelope checks every value before it is applied. It will clamp:
- any value outside its range or CityLearn's action space
- any move larger than {cfg.cooling_rate_per_step:g} (cooling), {cfg.dhw_rate_per_step:g} (dhw) or \
{cfg.battery_rate_per_step:g} (battery) per hour, measured from last hour's action or this hour's baseline
- charge that would leave a battery or tank outside {cfg.soc_min:g} to {cfg.soc_max:g} state of charge{dev}
- in occupied hours within {cfg.comfort_margin_k:g} C of a comfort band edge, cooling below the baseline \
when warm or above it when cool{guard}{spread}{peak}
An invalid reply uses the baseline action everywhere for that hour. Clamps are logged against you.

Reply with one JSON object only, matching the schema. "reason" is one plain sentence of at most \
{dc.REASON_TARGET_CHARS} characters. A reason over {dc.REASON_MAX_CHARS} characters makes the whole \
reply invalid."""


def build_observation_v5(state: dict, ctx: StepContext, last: Decision | None, look: Lookahead,
                         envelope: Envelope | None) -> dict:
    """Version 5: version 4 plus what the agent needs to smooth the district load."""
    obs = build_observation_v4(state, ctx, last, look, envelope)
    pk = ctx.peak
    obs["smoothing"] = {
        "district_draw_last_hour_kwh": None if pk is None else _r(pk.last_hour_grid_kwh, 2),
        "district_load_now_kwh": None if pk is None else _r(pk.load_now_kwh, 2),
        "district_load_next_hour_kwh": None if pk is None else _r(pk.next_hour_load_kwh, 2),
    }
    for b in state["buildings"]:
        trim = 0.0 if envelope is None else envelope.trims.get(b, 0.0)
        obs["buildings"][b]["cooling_trim_last_hour"] = _r(min(0.0, trim), 3)
    return obs


def system_prompt_v5(cfg: EnvelopeConfig, buildings: tuple[str, ...]) -> str:
    dev = ("" if cfg.cooling_max_deviation is None else
           f"\n- cooling more than {cfg.cooling_max_deviation:g} away from the baseline_action")
    guard = ("\n- extra cooling in an unoccupied building already near the bottom of its band"
             if cfg.overcool_guard_unoccupied else "")
    peak = ("\n- battery then tank charging, so district load stays at or below peak.target_kwh"
            if cfg.peak_limit else "")
    spread = ("\n- grid charging of a battery when grid_charging_ok is false (spare solar may still be stored)"
              if cfg.spread_check else "")
    sp = StrategyParamsV5()  # the strategy's numbers, chosen on the tuning dataset
    full = sp.cold_margin_c + sp.cold_ramp_c
    reserve = ("" if sp.evening_reserve <= 0 else
               f" Keep {sp.evening_reserve:g} of state of charge back for the evening district peak.")
    return f"""You are the hourly supervisory controller for a simulated district of {len(buildings)} \
buildings ({dc.DATASET_NAME}, CityLearn). Each building has a heat pump for space cooling, a hot water \
tank, a battery and rooftop solar. Every hour you choose one action per device for every building.

Goals, in this order, graded by CityLearn's own KPIs over the month against the no-control reference \
(storage idle, heat pump meeting the ideal load):
1. Comfort: no more discomfort than the reference. Discomfort is any occupied hour with indoor \
temperature outside setpoint +/- {cfg.comfort_band_k:g} C.
2. Peaks and smoothness: keep the district's daily peak, its daily load factor and its ramping at or \
better than the reference. Ramping counts every hour the district draws more than the hour before, \
so a step up costs and a step down does not.
3. Cost first, then carbon: lower electricity cost and lower emissions than the reference. Each \
building's cost counts equally, whatever its size.

What you see:
- reference_action in each building: what the 0.4.0 rule-based controller would do this hour, \
with reference_reason. It is the bar to beat on cost and carbon. Compare your plan with it: where \
you differ, a point of the strategy below should say why.
- price_plan: the price now, the 24 hour top and low, top_price_now (this is one of the most \
expensive hours), top_price_hours_ahead (hours ahead at the top price) and flat_24h (no price \
difference in view, as on weekends).
- battery: soc, soc_floor (the battery cannot go below it), usable_kwh above the floor, capacity, \
max_fraction_per_hour, round_trip_min (the share of a charge that comes back at worst) and \
grid_charging_ok (false when no price in the next 24 hours pays back the losses and a cheaper \
hour is still coming).
- indoor_c is the measured room temperature; indoor_vs_setpoint_c is how far it is from the \
setpoint; cooling_trim_last_hour is how far below baseline_action you ran cooling last hour.
- smoothing: district_draw_last_hour_kwh (measured), district_load_now_kwh (before storage), \
district_load_next_hour_kwh (the next hour's load before storage, as yesterday).
- peak: target_kwh, headroom_kwh, forecast_today_kwh.
- signal_outlook and next_24h: price and carbon by hour. Carbon is the same hour yesterday.

Strategy:
1. Comfort and cooling. An occupied room more than {sp.cold_margin_c:g} C below its setpoint is \
overcooled: cut its cooling below baseline_action, from 0 at {sp.cold_margin_c:g} C below the \
setpoint to {sp.cold_trim:g} at {full:g} C or more below. Once a trim is on, hold it until the room \
is within {sp.trim_hold_c:g} C of its setpoint, then ease it off by at most {sp.trim_step:g} per hour. \
Switching a trim off at once steps the load up. Never cool less when the room is at or above its \
setpoint. Otherwise use null.
2. Hold the battery for the top-price hours. When top_price_now is true, discharge the usable charge \
evenly over the top-price hours left, each hour no more than the building's load_now_kwh (power \
sent back to the grid earns nothing).{reserve} Do not discharge in cheaper hours before them, except \
to keep district load down: once district_load_now_kwh reaches {sp.shave:g} x forecast_today_kwh, \
discharge to cover the building's own load. On flat_24h days leave the battery idle.
3. Charge so each battery is near {sp.soc_target:g} when the top-price hours start: only when \
grid_charging_ok is true, in the cheapest hours with the lowest carbon (usually the early morning), \
up to about {sp.charge_rate:g} of capacity per hour, starting small and rising by at most \
{sp.charge_step:g} per hour, within headroom_kwh. Store spare solar any time.
4. Never charge at the top price. Leave the hot water tank at 0.

Actions per building, use null to keep the baseline action:
- cooling: heat pump power as a fraction of nominal, {cfg.cooling_min:g} to {cfg.cooling_max:g}.
- dhw: hot water tank, fraction of capacity to charge (+) or discharge (-) this hour. Baseline 0.
- battery: fraction of battery capacity to charge (+) or discharge (-) this hour. Baseline 0.

A safety envelope checks every value before it is applied. It will clamp:
- any value outside its range or CityLearn's action space
- any move larger than {cfg.cooling_rate_per_step:g} (cooling), {cfg.dhw_rate_per_step:g} (dhw) or \
{cfg.battery_rate_per_step:g} (battery) per hour, measured from last hour's action or this hour's baseline
- charge that would leave a battery or tank outside {cfg.soc_min:g} to {cfg.soc_max:g} state of charge{dev}
- in occupied hours within {cfg.comfort_margin_k:g} C of a comfort band edge, cooling below the baseline \
when warm or above it when cool{guard}{spread}{peak}
An invalid reply uses the baseline action everywhere for that hour. Clamps are logged against you.

Reply with one JSON object only, matching the schema. "reason" is one plain sentence of at most \
{dc.REASON_TARGET_CHARS} characters. A reason over {dc.REASON_MAX_CHARS} characters makes the whole \
reply invalid."""


def build_observation_v6(state: dict, ctx: StepContext, last: Decision | None, look: Lookahead,
                         envelope: Envelope | None) -> dict:
    """Version 6: version 5 with the version 5 strategy's battery plan in place of the 0.4.0
    rule-based reference action, and the trim the envelope will hold this hour."""
    obs = build_observation_v5(state, ctx, last, look, envelope)
    del obs["reference_reason"]
    for b in obs["buildings"]:
        del obs["buildings"][b]["reference_action"]
    battery, why = battery_plan_v5(obs)
    obs["strategy_battery_reason"] = why
    for b, st in ctx.buildings.items():
        held = 0.0 if envelope is None or not envelope.config.trim_hold else envelope.held_trim(b, st)[0]
        obs["buildings"][b]["strategy_battery"] = battery[b]
        obs["buildings"][b]["cooling_trim_held"] = _r(-held, 3)
    return obs


def system_prompt_v6(cfg: EnvelopeConfig, buildings: tuple[str, ...]) -> str:
    dev = ("" if cfg.cooling_max_deviation is None else
           f"\n- cooling more than {cfg.cooling_max_deviation:g} away from the baseline_action")
    guard = ("\n- extra cooling in an unoccupied building already near the bottom of its band"
             if cfg.overcool_guard_unoccupied else "")
    peak = ("\n- battery then tank charging, so district load stays at or below peak.target_kwh"
            if cfg.peak_limit else "")
    spread = ("\n- grid charging of a battery when grid_charging_ok is false (spare solar may still be stored)"
              if cfg.spread_check else "")
    hold = "\n- cooling above a held trim, and a trim where the hold has ended" if cfg.trim_hold else ""
    sp = StrategyParamsV5()  # the strategy's numbers, chosen on the tuning dataset
    full = sp.cold_margin_c + sp.cold_ramp_c
    reserve = ("" if sp.evening_reserve <= 0 else
               f" Keep {sp.evening_reserve:g} of state of charge back for the evening district peak.")
    return f"""You are the hourly supervisory controller for a simulated district of {len(buildings)} \
buildings ({dc.DATASET_NAME}, CityLearn). Each building has a heat pump for space cooling, a hot water \
tank, a battery and rooftop solar. Every hour you choose one action per device for every building.

Goals, in this order, graded by CityLearn's own KPIs over the month against the no-control reference \
(storage idle, heat pump meeting the ideal load):
1. Comfort: no more discomfort than the reference. Discomfort is any occupied hour with indoor \
temperature outside setpoint +/- {cfg.comfort_band_k:g} C.
2. Peaks and smoothness: keep the district's daily peak, its daily load factor and its ramping at or \
better than the reference. Ramping counts every hour the district draws more than the hour before, \
so a step up costs and a step down does not.
3. Cost first, then carbon: lower electricity cost and lower emissions than the reference. Each \
building's cost counts equally, whatever its size.

What you see:
- strategy_battery in each building: the battery action points 2 to 4 below give this hour, worked \
out in code, with strategy_battery_reason. Use it unless you have a clear reason; say why you differ.
- price_plan: the price now, the 24 hour top and low, top_price_now (this is one of the most \
expensive hours), top_price_hours_ahead (hours ahead at the top price) and flat_24h (no price \
difference in view, as on weekends).
- battery: soc, soc_floor (the battery cannot go below it), usable_kwh above the floor, capacity, \
max_fraction_per_hour, round_trip_min (the share of a charge that comes back at worst) and \
grid_charging_ok (false when no price in the next 24 hours pays back the losses and a cheaper \
hour is still coming).
- indoor_c is the measured room temperature; indoor_vs_setpoint_c is how far it is from the \
setpoint; cooling_trim_last_hour is how far below baseline_action cooling ran last hour; \
cooling_trim_held is the trim the envelope keeps this hour.
- smoothing: district_draw_last_hour_kwh (measured), district_load_now_kwh (before storage), \
district_load_next_hour_kwh (the next hour's load before storage, as yesterday).
- peak: target_kwh, headroom_kwh, forecast_today_kwh.
- signal_outlook and next_24h: price and carbon by hour. Carbon is the same hour yesterday.

Strategy:
1. Comfort and cooling. An occupied room more than {sp.cold_margin_c:g} C below its setpoint is \
overcooled: cut its cooling below baseline_action, from 0 at {sp.cold_margin_c:g} C below the \
setpoint to {sp.cold_trim:g} at {full:g} C or more below. The envelope holds a trim in code: while \
the room is occupied and more than {cfg.trim_hold_c:g} C below its setpoint it stays at least as deep \
as last hour, within {cfg.trim_hold_c:g} C it eases off by at most {cfg.trim_release_step:g} per hour, \
and it ends at the setpoint, when the room empties or when baseline cooling is 0. null keeps a held \
trim; you may trim deeper. End one early only through end_trim; early ends are logged.
2. Hold the battery for the top-price hours. When top_price_now is true, discharge the usable charge \
evenly over the top-price hours left, each hour no more than the building's load_now_kwh (power \
sent back to the grid earns nothing).{reserve} Do not discharge in cheaper hours before them, except \
to keep district load down: once district_load_now_kwh reaches {sp.shave:g} x forecast_today_kwh, \
discharge to cover the building's own load. On flat_24h days leave the battery idle.
3. Charge so each battery is near {sp.soc_target:g} when the top-price hours start: only when \
grid_charging_ok is true, in the cheapest hours with the lowest carbon (usually the early morning), \
up to about {sp.charge_rate:g} of capacity per hour, starting small and rising by at most \
{sp.charge_step:g} per hour, within headroom_kwh. Store spare solar any time.
4. Never charge at the top price. Leave the hot water tank at 0.

Actions per building, use null to keep the baseline action:
- cooling: heat pump power as a fraction of nominal, {cfg.cooling_min:g} to {cfg.cooling_max:g}.
- dhw: hot water tank, fraction of capacity to charge (+) or discharge (-) this hour. Baseline 0.
- battery: fraction of battery capacity to charge (+) or discharge (-) this hour. Baseline 0.
- end_trim: null, or a short reason to end that building's held cooling trim now.

A safety envelope checks every value before it is applied. It will clamp:
- any value outside its range or CityLearn's action space
- any move larger than {cfg.cooling_rate_per_step:g} (cooling), {cfg.dhw_rate_per_step:g} (dhw) or \
{cfg.battery_rate_per_step:g} (battery) per hour, measured from last hour's action or this hour's baseline
- charge that would leave a battery or tank outside {cfg.soc_min:g} to {cfg.soc_max:g} state of charge{dev}
- in occupied hours within {cfg.comfort_margin_k:g} C of a comfort band edge, cooling below the baseline \
when warm or above it when cool{guard}{hold}{spread}{peak}
An invalid reply uses the baseline action everywhere for that hour. Clamps are logged against you.

Reply with one JSON object only, matching the schema. "reason" is one plain sentence of at most \
{dc.REASON_TARGET_CHARS} characters. A reason over {dc.REASON_MAX_CHARS} characters makes the whole \
reply invalid."""


def _inward(lo: float, hi: float) -> list[float] | None:
    """[lo, hi] rounded inward to 4 decimals, the precision the envelope applies; None when no
    4 decimal value fits (only the exact baseline does)."""
    a, b = math.ceil(lo * 1e4 - 1e-6) / 1e4, math.floor(hi * 1e4 + 1e-6) / 1e4
    return None if a > b else [a, b]


def cooling_range(envelope: Envelope, b: str, st) -> list[float] | None:
    """The cooling values the envelope lets through for building b this hour without a clamp,
    worked out read only from its own state, in its own order: range, rate, deviation, the
    unoccupied overcool guard, comfort, then the trim hold. None means only the exact
    baseline_action passes (null). A held trim keeps cooling at least need below the baseline,
    exactly what the hold would apply; where that reaches below the action range the hold
    applies the bottom of the range and still logs a clamp, which no reply can avoid."""
    cfg = envelope.config
    base = st.baseline["cooling"]
    blo, bhi = st.bounds["cooling"]
    lo, hi = max(cfg.cooling_min, blo), min(cfg.cooling_max, bhi)
    floor = lo
    prev = envelope.memory.get(f"{b}.cooling", base)
    lo, hi = max(lo, min(prev, base) - cfg.cooling_rate_per_step), min(hi, max(prev, base) + cfg.cooling_rate_per_step)
    if cfg.cooling_max_deviation is not None:
        lo, hi = max(lo, base - cfg.cooling_max_deviation), min(hi, base + cfg.cooling_max_deviation)
    band, margin = cfg.comfort_band_k, cfg.comfort_margin_k
    if not st.occupied and cfg.overcool_guard_unoccupied and st.indoor_c <= st.setpoint_c - band + margin:
        hi = min(hi, base)
    if st.occupied:
        if st.indoor_c >= st.setpoint_c + band - margin:
            lo = max(lo, base)
        elif st.indoor_c <= st.setpoint_c - band + margin:
            hi = min(hi, base)
    if cfg.trim_hold:
        need, kind, _ = envelope.held_trim(b, st)
        if kind == "end":
            lo = max(lo, base)
        elif envelope.holds.get(b, 0.0) > cfg.trim_min_depth:
            # Where the hold reaches below the action range it holds cooling at the bottom of it.
            hi = max(min(hi, base - need), max(floor, base - need))
            lo = min(lo, hi)
            got = _inward(lo, hi)
            return got if got is not None else [math.ceil(lo * 1e4 - 1e-6) / 1e4] * 2
    return _inward(lo, hi)


def battery_range(envelope: Envelope, b: str, st) -> list[float]:
    """The battery values the envelope lets through for building b without a range, rate or
    state of charge clamp. The spread check and the peak limiter are shown separately
    (grid_charging_ok, peak.headroom_kwh)."""
    cfg = envelope.config
    blo, bhi = st.bounds["battery"]
    lo, hi = max(cfg.storage_min, blo), min(cfg.storage_max, bhi)
    prev = envelope.memory.get(f"{b}.battery", 0.0)
    lo, hi = max(lo, min(prev, 0.0) - cfg.battery_rate_per_step), min(hi, max(prev, 0.0) + cfg.battery_rate_per_step)
    lo, hi = max(lo, min(0.0, cfg.soc_min - st.battery_soc)), min(hi, max(0.0, cfg.soc_max - st.battery_soc))
    return _inward(lo, hi) or [0.0, 0.0]


_TRIM_WHY = {"the baseline has no cooling to trim": "no baseline cooling", "the room is unoccupied": "unoccupied"}


def trim_view(envelope: Envelope, b: str, st) -> dict:
    """Building b's cooling trim as the envelope will treat it this hour. state: off (no trim on),
    hold (more than trim_hold_c below the setpoint: keep at least depth), ease (within
    trim_hold_c: ease off by at most trim_release_step), end (no trim may run now)."""
    cfg = envelope.config
    depth = envelope.holds.get(b, 0.0) if cfg.trim_hold else 0.0
    on = depth > cfg.trim_min_depth
    need, kind, why = envelope.held_trim(b, st) if cfg.trim_hold else (0.0, "none", "")
    out: dict = {"depth": _r(depth, 3) if on else 0.0, "state": "off" if kind == "none" else kind,
                 "end_trim_ok": bool(on and kind in ("hold", "ease"))}
    if kind == "hold":
        out["why"] = f"{st.setpoint_c - st.indoor_c:.1f} C below setpoint"
    elif kind == "ease":
        out["why"] = f"within {cfg.trim_hold_c:g} C of setpoint"
    elif kind == "end":
        out["why"] = _TRIM_WHY.get(why, "at or above setpoint")
    if kind in ("hold", "ease") and on:
        out["min_depth"] = _r(need, 3)
    return out


def build_observation_v7(state: dict, ctx: StepContext, last: Decision | None, look: Lookahead,
                         envelope: Envelope | None) -> dict:
    """Version 7: version 6 with what the envelope allows each building this hour (the trim,
    cooling_range, battery_range, last hour's clamps there) and the version 7 battery plan."""
    envelope = envelope or Envelope(EnvelopeConfig())
    obs = build_observation_v5(state, ctx, last, look, envelope)
    del obs["reference_reason"], obs["last_clamps"]
    for b in obs["buildings"]:
        del obs["buildings"][b]["reference_action"], obs["buildings"][b]["cooling_trim_last_hour"]
    battery, why = battery_plan_v7(obs)
    obs["strategy_battery_reason"] = why
    for b, st in ctx.buildings.items():
        ob = obs["buildings"][b]
        ob["trim"] = trim_view(envelope, b, st)
        ob["cooling_range"] = cooling_range(envelope, b, st)
        ob["battery_range"] = br = battery_range(envelope, b, st)
        ob["strategy_battery"] = min(max(battery[b], br[0]), br[1])
        clamps = [] if last is None else [c for c in last.clamps if c.point.startswith(f"{b}.")]
        if clamps:
            ob["last_clamp"] = "; ".join(f"{c.point.split('.')[1]} {c.rule} {_r(c.requested, 4)} to "
                                         f"{_r(c.applied, 4)}: {c.reason}" for c in clamps)
    return obs


def system_prompt_v7(cfg: EnvelopeConfig, buildings: tuple[str, ...]) -> str:
    peak = ", battery then tank charging above peak.target_kwh" if cfg.peak_limit else ""
    spread = ", grid charging when grid_charging_ok is false (spare solar may still be stored)" if cfg.spread_check else ""
    sp = StrategyParamsV7()  # the strategy's numbers, chosen on the tuning dataset
    full = sp.cold_margin_c + sp.cold_ramp_c
    fill = (" Grid charging fills the district draw only up to the higher of district_draw_last_hour_kwh and "
            "district_load_next_hour_kwh." if sp.fill_valley else "")
    cap = ("" if sp.rise_step >= sp.max_step else
           f" Raise a battery action (more charge or less discharge) by at most {sp.rise_step:g} per hour; "
           "lowering it is free.")
    reserve = ("" if sp.evening_reserve <= 0 else
               f" Keep {sp.evening_reserve:g} of state of charge back for the evening district peak.")
    return f"""You are the hourly supervisory controller for a simulated district of {len(buildings)} \
buildings ({dc.DATASET_NAME}, CityLearn). Each building has a heat pump for space cooling, a hot water \
tank, a battery and rooftop solar. Every hour you choose one action per device for every building.

Goals, in this order, graded by CityLearn's own KPIs over the month against the no-control reference \
(storage idle, heat pump meeting the ideal load):
1. Comfort: no more discomfort than the reference. Discomfort is any occupied hour with indoor \
temperature outside setpoint +/- {cfg.comfort_band_k:g} C.
2. Peaks and smoothness: keep the district's daily peak, its daily load factor and its ramping at or \
better than the reference. Ramping counts every hour the district draws more than the hour before, \
so a step up costs and a step down does not.
3. Cost first, then carbon: lower electricity cost and lower emissions than the reference. Each \
building's cost counts equally, whatever its size.

What you see:
- cooling_range and battery_range in each building: the values the safety envelope lets through this \
hour. Stay inside them and nothing is clamped. cooling_range null: only the baseline passes, use null.
- trim: the cooling trim the envelope carries. depth is how far below baseline_action it runs. state \
off: none on. hold: the room is more than {cfg.trim_hold_c:g} C below its setpoint, keep at least depth. \
ease: within {cfg.trim_hold_c:g} C, ease off by at most {cfg.trim_release_step:g} per hour. end: no trim may \
run now. min_depth is the least trim allowed this hour; end_trim_ok says whether end_trim may be used.
- last_clamp: what the envelope changed in that building last hour, and why.
- strategy_battery: the battery action points 2 to 4 below give this hour, worked out in code, with \
strategy_battery_reason. Use it unless you have a clear reason; say why you differ.
- price_plan: the price now, the 24 hour top and low, top_price_now, top_price_hours_ahead, flat_24h.
- battery: soc, soc_floor, usable_kwh, capacity, max_fraction_per_hour, round_trip_min, and \
grid_charging_ok (false when no price ahead pays back the losses and a cheaper hour is coming).
- indoor_vs_setpoint_c; smoothing: district_draw_last_hour_kwh (measured), district_load_now_kwh and \
district_load_next_hour_kwh (before storage, the next hour as yesterday); peak: target_kwh, \
headroom_kwh, forecast_today_kwh; signal_outlook and next_24h by hour.

Strategy:
1. Cooling. An occupied room more than {sp.cold_margin_c:g} C below its setpoint is overcooled: cut its \
cooling below baseline_action, from 0 at {sp.cold_margin_c:g} C below to {sp.cold_trim:g} at {full:g} C or \
more below. null is exactly baseline_action: use it only when trim state is off or end. When state is \
hold or ease, send a cooling number inside cooling_range (deeper is fine). End a held trim early only \
with end_trim and null cooling, when end_trim_ok.
2. Hold the battery for the top-price hours. When top_price_now is true, discharge the usable charge \
evenly over the top-price hours left, each hour no more than the building's load_now_kwh (power \
sent back to the grid earns nothing).{reserve} Do not discharge in cheaper hours before them, except \
to keep district load down: once district_load_now_kwh reaches {sp.shave:g} x forecast_today_kwh, \
discharge to cover the building's own load. On flat_24h days leave the battery idle.
3. Charge so each battery is near {sp.soc_target:g} when the top-price hours start: only when \
grid_charging_ok is true, in the cheapest hours with the lowest carbon, up to about {sp.charge_rate:g} \
of capacity per hour, within headroom_kwh. Store spare solar any time.{fill}
4. No step changes. strategy_battery already spreads charging over several cheap hours and the \
discharge over the top-price hours; send it as given. If you differ, stay within {sp.battery_band:g} of \
it and never skip a peak-shaving discharge.{cap} Never charge at the top price. Leave the hot water \
tank at 0.

Actions per building, use null to keep the baseline action:
- cooling: heat pump power as a fraction of nominal, {cfg.cooling_min:g} to {cfg.cooling_max:g}.
- dhw: hot water tank, fraction of capacity to charge (+) or discharge (-) this hour. Baseline 0.
- battery: fraction of battery capacity to charge (+) or discharge (-) this hour. Baseline 0.
- end_trim: null, or a short reason to end that building's held cooling trim now.

The ranges already apply the envelope's range, rate, state of charge ({cfg.soc_min:g} to \
{cfg.soc_max:g}), deviation, comfort and trim hold rules. It also clamps the tank by the same rate \
({cfg.dhw_rate_per_step:g}) and charge limits{spread}{peak}. An invalid reply uses the baseline action \
everywhere for that hour. Clamps are logged against you.

Reply with one JSON object only, matching the schema. "reason" is one plain sentence of at most \
{dc.REASON_TARGET_CHARS} characters. A reason over {dc.REASON_MAX_CHARS} characters makes the whole \
reply invalid."""


def build_observation_v8(state: dict, ctx: StepContext, last: Decision | None, look: Lookahead,
                         envelope: Envelope | None, strategy=strategy_plan_v8) -> dict:
    """Version 8: version 7 with the version 8 strategy's whole action per building (strategy, with
    strategy_reason) in place of strategy_battery, and without signal_outlook, which no version 7 or
    8 strategy reads."""
    obs = build_observation_v7(state, ctx, last, look, envelope)
    del obs["strategy_battery_reason"], obs["signal_outlook"]
    plan = strategy(obs)
    obs["strategy_reason"] = plan["reason"]
    for b, ob in obs["buildings"].items():
        del ob["strategy_battery"]
        ob["strategy"] = {d: plan[b][d] for d in ("cooling", "dhw", "battery")}
    return obs


def system_prompt_v8(cfg: EnvelopeConfig, buildings: tuple[str, ...]) -> str:
    peak = ", battery then tank charging above peak.target_kwh" if cfg.peak_limit else ""
    spread = ", grid charging when grid_charging_ok is false (spare solar may still be stored)" if cfg.spread_check else ""
    sp = StrategyParamsV8()  # the strategy's numbers, chosen on the tuning dataset
    full = sp.cold_margin_c + sp.cold_ramp_c
    return f"""You are the hourly supervisory controller for a simulated district of {len(buildings)} \
buildings (CityLearn 2023 challenge data). Each building has a heat pump for space cooling, a hot water \
tank, a battery and rooftop solar. Every hour you choose one action per device for every building.

Goals, in this order, graded by CityLearn's own KPIs over the month against the no-control reference \
(storage idle, heat pump meeting the ideal load):
1. Comfort: no more discomfort, too cool or too warm, than the reference. Discomfort is any occupied \
hour with indoor temperature outside setpoint +/- {cfg.comfort_band_k:g} C.
2. Peaks and smoothness: the district's daily peak, daily load factor and ramping at or better than \
the reference. Ramping counts every hour the district draws more than the hour before.
3. Cost first, then carbon. Each building's cost counts equally, whatever its size.

What you see:
- strategy in each building: the action the strategy below gives this hour for cooling, dhw and \
battery, worked out in code inside the envelope's ranges, with strategy_reason. Send it as given. \
Where you differ, say why in the reason.
- cooling_range and battery_range: the values the safety envelope lets through this hour without a \
clamp. cooling_range null: only the baseline passes.
- trim: the cooling trim the envelope carries: depth below baseline_action, state (off, hold, ease, \
end), min_depth, end_trim_ok. last_clamp: what the envelope changed there last hour, and why.
- price_plan, battery, indoor_vs_setpoint_c, smoothing, peak and next_24h: what the strategy reads.

Strategy (strategy already applies it):
1. Cooling. An occupied room more than {sp.cold_margin_c:g} C below its setpoint is overcooled: cooling \
goes below baseline_action, from 0 at {sp.cold_margin_c:g} C below to {sp.cold_trim:g} at {full:g} C or more \
below. That starts a trim when state is off; while it is held, cooling is a number inside cooling_range, \
never null. A trim leaves the room at its setpoint, without the reference's cushion, so an occupied room \
running warm with no trim held gets more cooling than baseline_action: from 0 at {sp.warm_margin_c:g} C \
above its setpoint to {sp.warm_boost:g} at {sp.warm_margin_c + sp.warm_ramp_c:g} C or more above. \
Otherwise cooling is null, exactly baseline_action.
2. Battery. Discharge the usable charge evenly over the top-price hours left, each hour no more than \
load_now_kwh. Before them discharge only to shave the district peak, once district_load_now_kwh \
reaches {sp.shave:g} x forecast_today_kwh. Charge from the grid only when grid_charging_ok, in the \
cheapest, cleanest hours, up to {sp.charge_rate:g} of capacity per hour within headroom_kwh, to be \
near {sp.soc_target:g} when the top price starts. Store spare solar any time. Idle on flat_24h days.
3. Leave the hot water tank at 0.

Actions per building, null keeps baseline_action:
- cooling: heat pump power as a fraction of nominal, {cfg.cooling_min:g} to {cfg.cooling_max:g}.
- dhw: hot water tank, fraction of capacity to charge (+) or discharge (-) this hour. Baseline 0.
- battery: fraction of battery capacity to charge (+) or discharge (-) this hour. Baseline 0.
- end_trim: null, or a short reason to end a held trim now (only when end_trim_ok, with null cooling).

The ranges already apply the envelope's range, rate, state of charge ({cfg.soc_min:g} to \
{cfg.soc_max:g}), deviation, comfort and trim hold rules. It also clamps the tank by the same rate \
({cfg.dhw_rate_per_step:g}) and charge limits{spread}{peak}. An invalid reply uses the baseline action \
everywhere for that hour. Clamps are logged against you.

Reply with one JSON object only, matching the schema. "reason" is one plain sentence of at most \
{dc.REASON_TARGET_CHARS} characters. A reason over {dc.REASON_MAX_CHARS} characters makes the whole \
reply invalid."""


def build_observation_v9(state: dict, ctx: StepContext, last: Decision | None, look: Lookahead,
                         envelope: Envelope | None) -> dict:
    """Version 9: version 8 with the version 9 strategy (charge kept for the evening shave) and
    peak.shave_now, the strategy's own test for a peak-shaving hour, at any time of day."""
    obs = build_observation_v8(state, ctx, last, look, envelope, strategy=strategy_plan_v9)
    pk, sp = obs["peak"], StrategyParamsV9()
    now, forecast = pk["district_load_now_kwh"], pk["forecast_today_kwh"]
    pk["shave_now"] = bool(sp.shave > 0 and now is not None and forecast and now >= sp.shave * forecast)
    return obs


def system_prompt_v9(cfg: EnvelopeConfig, buildings: tuple[str, ...]) -> str:
    peak = ", battery then tank charging above peak.target_kwh" if cfg.peak_limit else ""
    spread = ", grid charging when grid_charging_ok is false (spare solar may still be stored)" if cfg.spread_check else ""
    sp = StrategyParamsV9()  # the strategy's numbers, chosen on the month set
    full = sp.cold_margin_c + sp.cold_ramp_c
    return f"""You are the hourly supervisory controller for a simulated district of {len(buildings)} \
buildings (CityLearn 2023 challenge data). Each building has a heat pump for space cooling, a hot water \
tank, a battery and rooftop solar. Every hour you choose one action per device for every building.

Goals, in this order, graded by CityLearn's own KPIs over the month against the no-control reference \
(storage idle, heat pump meeting the ideal load):
1. Comfort: no more discomfort, too cool or too warm, than the reference. Discomfort is any occupied \
hour with indoor temperature outside setpoint +/- {cfg.comfort_band_k:g} C.
2. Peaks and smoothness: the district's daily and monthly peak, daily load factor and ramping at or \
better than the reference. Ramping counts every hour the district draws more than the hour before.
3. Cost first, then carbon. Each building's cost counts equally, whatever its size.

What you see:
- strategy in each building: the action the strategy below gives this hour for cooling, dhw and \
battery, worked out in code inside the envelope's ranges, with strategy_reason. Send it as given, every \
number exactly: battery -0.033 is not 0, and cooling under baseline_action is not null, trim state off \
too. Where you differ, say why.
- cooling_range and battery_range: the values the safety envelope lets through this hour without a \
clamp. cooling_range null: only the baseline passes.
- trim: the cooling trim the envelope carries: depth below baseline_action, state (off, hold, ease, \
end), min_depth, end_trim_ok. last_clamp: what the envelope changed there last hour, and why.
- price_plan, battery, indoor_vs_setpoint_c, smoothing, peak and next_24h: what the strategy reads.

Strategy (strategy already applies it):
1. Cooling. An occupied room more than {sp.cold_margin_c:g} C below its setpoint is overcooled: cooling \
goes below baseline_action, from 0 at {sp.cold_margin_c:g} C below to {sp.cold_trim:g} at {full:g} C or more \
below. That starts a trim when state is off; while it is held, cooling is a number inside cooling_range, \
never null. A trim leaves the room at its setpoint, without the reference's cushion, so an occupied room \
running warm with no trim held gets more cooling than baseline_action: from 0 at {sp.warm_margin_c:g} C \
above its setpoint to {sp.warm_boost:g} at {sp.warm_margin_c + sp.warm_ramp_c:g} C or more above. \
Otherwise cooling is null, exactly baseline_action.
2. Battery. Discharge the usable charge evenly over the top-price hours left, keeping {sp.evening_reserve:g} \
above the floor, each hour no more than load_now_kwh. In any other hour, after the top price and on \
flat_24h days too, shave when peak.shave_now (district_load_now_kwh at least {sp.shave:g} x \
forecast_today_kwh): cover the building's own load with whatever charge is left. Charge from the grid only when grid_charging_ok, in the \
cheapest, cleanest hours, up to {sp.charge_rate:g} of capacity per hour within headroom_kwh, to be near \
{sp.soc_target:g} when the top price starts. Store spare solar any time. Else idle on flat_24h days.
3. Leave the hot water tank at 0.

Actions per building, null keeps baseline_action:
- cooling: heat pump power as a fraction of nominal, {cfg.cooling_min:g} to {cfg.cooling_max:g}.
- dhw: hot water tank, fraction of capacity to charge (+) or discharge (-) this hour. Baseline 0.
- battery: fraction of battery capacity to charge (+) or discharge (-) this hour. Baseline 0.
- end_trim: null, or a short reason to end a held trim now (only when end_trim_ok, with null cooling).

The ranges already apply the envelope's range, rate, state of charge ({cfg.soc_min:g} to \
{cfg.soc_max:g}), deviation, comfort and trim hold rules. It also clamps the tank by the same rate \
({cfg.dhw_rate_per_step:g}) and charge limits{spread}{peak}. An invalid reply uses the baseline action \
everywhere for that hour. Clamps are logged against you.

Reply with one JSON object only, matching the schema. "reason" is one plain sentence of at most \
{dc.REASON_TARGET_CHARS} characters. A reason over {dc.REASON_MAX_CHARS} characters makes the whole \
reply invalid."""


def observe(version: int, state: dict, ctx: StepContext, last: Decision | None, look: Lookahead,
            envelope: Envelope | None = None) -> dict:
    if version == 1:
        return build_observation(state, ctx, last)
    if version == 2:
        return build_observation_v2(state, ctx, last, look)
    if version == 3:
        return build_observation_v3(state, ctx, last, look, envelope)
    if version == 4:
        return build_observation_v4(state, ctx, last, look, envelope)
    if version == 5:
        return build_observation_v5(state, ctx, last, look, envelope)
    if version == 6:
        return build_observation_v6(state, ctx, last, look, envelope)
    if version == 7:
        return build_observation_v7(state, ctx, last, look, envelope)
    if version == 8:
        return build_observation_v8(state, ctx, last, look, envelope)
    if version == 9:
        return build_observation_v9(state, ctx, last, look, envelope)
    raise ValueError(f"unknown prompt version {version}")


def user_message(obs: dict) -> str:
    return (
        "District state this hour. Energy in kWh, temperatures in C, price in $/kWh.\n"
        "OBSERVATION_JSON\n" + json.dumps(obs, separators=(",", ":"), sort_keys=True)
    )


def system_text(request: dict) -> str:
    """The system prompt's text, whether it was sent as a plain string or as cached blocks."""
    system = request["system"]
    return system if isinstance(system, str) else "".join(b["text"] for b in system)


def build_request(obs: dict, cfg: EnvelopeConfig, buildings: tuple[str, ...], model_key: str,
                  max_tokens: int = DEFAULT_MAX_TOKENS, effort: str = DEFAULT_EFFORT,
                  prompt_version: int = 1, prompt_cache: bool = False) -> dict:
    """prompt_cache marks the system prompt as the cached prefix. It depends only on the envelope
    config and the building names, so it is the same bytes every hour of a run; everything that
    changes by the hour is in the user message after it. Off by default so runs recorded before
    prompt caching rebuild the request they sent."""
    system = {1: system_prompt, 2: system_prompt_v2, 3: system_prompt_v3,
              4: system_prompt_v4, 5: system_prompt_v5, 6: system_prompt_v6,
              7: system_prompt_v7, 8: system_prompt_v8, 9: system_prompt_v9}[prompt_version](cfg, buildings)
    if prompt_cache:
        # Default 5 minute TTL: hourly calls run back to back, seconds apart.
        system = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
    return {
        "model": MODELS[model_key]["id"],
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user_message(obs)}],
        "output_config": {
            "effort": effort,
            "format": {"type": "json_schema",
                       "schema": proposal_json_schema(buildings, end_trim_field(prompt_version))},
        },
    }
