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
"""

from __future__ import annotations

import json

from . import district as dc
from .envelope import Decision, Envelope, EnvelopeConfig, StepContext, proposal_json_schema
from .model import DEFAULT_EFFORT, DEFAULT_MAX_TOKENS, MODELS, StrategyParams, rule_plan_v3
from .signals import charge_spread, combined_signal


PROMPT_VERSION = 4
PROMPT_VERSIONS = (1, 2, 3, 4)


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
    raise ValueError(f"unknown prompt version {version}")


def user_message(obs: dict) -> str:
    return (
        "District state this hour. Energy in kWh, temperatures in C, price in $/kWh.\n"
        "OBSERVATION_JSON\n" + json.dumps(obs, separators=(",", ":"), sort_keys=True)
    )


def build_request(obs: dict, cfg: EnvelopeConfig, buildings: tuple[str, ...], model_key: str,
                  max_tokens: int = DEFAULT_MAX_TOKENS, effort: str = DEFAULT_EFFORT,
                  prompt_version: int = 1) -> dict:
    system = {1: system_prompt, 2: system_prompt_v2, 3: system_prompt_v3,
              4: system_prompt_v4}[prompt_version](cfg, buildings)
    return {
        "model": MODELS[model_key]["id"],
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": user_message(obs)}],
        "output_config": {
            "effort": effort,
            "format": {"type": "json_schema", "schema": proposal_json_schema(buildings)},
        },
    }
