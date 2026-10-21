"""CityLearn backend, fully offline, on the dataset shipped in hyperbolic/data.

control=False runs CityLearn's no-control reference exactly as its BaselineAgent
does: every action is deactivated, so storage stays idle and the heat pump meets
the ideal load from the dataset. This is the reference every CityLearn KPI is
normalized against.

control=True activates the dataset's actions (heat pump, hot water tank, battery)
for the supervisor. The baseline action reported each hour is the closest
equivalent of the no-control reference under active control: storage idle and the
heat pump at the fraction of nominal power that delivers the ideal cooling load.
"""

from __future__ import annotations

import logging
import math
import os
from pathlib import Path

from . import district as dc

DEVICE_OF_ACTION = dict(dc.DEVICES)  # citylearn action name -> device key
ACTION_OF_DEVICE = {v: k for k, v in DEVICE_OF_ACTION.items()}


def _f(x) -> float:
    v = float(x)
    return v if math.isfinite(v) else 0.0


class CityLearnSimulator:
    kind = "citylearn"

    def __init__(self, control: bool = True, schema: Path | None = None) -> None:
        self.control = control
        self.schema = Path(schema) if schema else dc.schema_path()
        self.env = None
        self.t = 0
        self.end_t = 0

    # -- Simulator protocol ------------------------------------------------------

    @staticmethod
    def check_hours(hours: int | None) -> None:
        """CityLearn 3.0.2's outage model fails on a partial last day once a run spans two days."""
        if not hours:
            return
        steps = int(hours) + 1
        if steps >= 48 and steps % 24:
            raise ValueError(f"--hours {hours}: runs of two days or more need hours + 1 to be a whole number "
                             f"of days, for example {steps // 24 * 24 - 1} or {steps // 24 * 24 + 23}")

    def start(self, hours: int | None) -> dict:
        os.environ.setdefault("CITYLEARN_OFFLINE", "1")
        logging.getLogger().setLevel(logging.WARNING)
        from citylearn.citylearn import CityLearnEnv

        kwargs = {"central_agent": True}
        if hours:
            self.check_hours(hours)
            # An episode of N time steps gives N - 1 decisions.
            kwargs["simulation_end_time_step"] = int(hours)
        env = CityLearnEnv(str(self.schema), **kwargs)
        if not self.control:
            # Same as citylearn.agents.base.BaselineAgent: no active actions anywhere.
            for b in env.buildings:
                for a in b.action_metadata:
                    b.action_metadata[a] = False
                b.action_space = b.estimate_action_space()
                b.observation_space = b.estimate_observation_space()
        env.reset()
        self.env = env
        self.t = int(env.time_step)
        self.end_t = int(env.time_steps) - 1
        self.decisions = self.end_t  # hourly decisions in this episode
        self.action_names = [list(names) for names in env.action_names]
        return self.state()

    def step(self, actions: dict | None) -> tuple[dict, dict | None]:
        env = self.env
        t = env.time_step
        if self.control:
            vector = self._vector(actions)
            env.step([vector])
        else:
            env.step([[] for _ in env.action_names])
        outcome = self._outcome(t)
        done = env.terminated or env.time_step >= self.end_t
        return outcome, None if done else self.state()

    def kpis(self) -> list[dict]:
        df = self.env.evaluate()
        rows = []
        for r in df.to_dict(orient="records"):
            value = r.get("value")
            value = None if value is None or (isinstance(value, float) and not math.isfinite(value)) else float(value)
            rows.append({
                "cost_function": str(r["cost_function"]),
                "name": str(r["name"]),
                "level": str(r["level"]),
                "value": None if value is None else round(value, 6),
            })
        rows.sort(key=lambda x: (x["level"], x["name"], x["cost_function"]))
        return rows

    def close(self) -> None:
        self.env = None

    # -- internals ---------------------------------------------------------------

    def _vector(self, actions: dict | None) -> list[float]:
        """CityLearn's central-agent action vector, in its own action order."""
        vec = []
        names = self.env.action_names[0]
        for i, b in enumerate(self.env.buildings):
            acts = (actions or {}).get(b.name, {})
            for a in b.active_actions:
                device = DEVICE_OF_ACTION.get(a)
                vec.append(float(acts.get(device, 0.0)) if device else 0.0)
        assert len(vec) == len(names), "action vector length does not match CityLearn's action names"
        return vec

    def _baseline_cooling(self, b) -> float:
        """Fraction of nominal power that delivers the ideal cooling load this hour."""
        t = self.env.time_step
        ideal = _f(b.energy_simulation.cooling_demand_without_control[t])
        if ideal <= 0.0:
            return 0.0
        temp = _f(b.weather.outdoor_dry_bulb_temperature[t])
        full = _f(b.cooling_device.get_max_output_power(temp, heating=False,
                                                          max_electric_power=b.cooling_device.nominal_power))
        return round(min(1.0, ideal / full), 4) if full > 0 else 1.0

    def _load_before_storage(self, b, o) -> float:
        """This hour's net draw with storage idle and cooling at the baseline action: what
        the building's meter would read before any battery or tank move. Plug load and
        solar come from this hour's observations. Hot water demand comes from the same
        dataset series CityLearn simulates, because its observation lags by one hour."""
        t = self.env.time_step
        dhw = _f(b.energy_simulation.dhw_demand[t]) / max(_f(b.dhw_device.efficiency), 1e-6)
        cooling = self._baseline_cooling(b) * _f(b.cooling_device.nominal_power)
        return round(_f(o["non_shiftable_load"]) + cooling + dhw - _f(o["solar_generation"]), 4)

    def state(self) -> dict:
        """The district as CityLearn's own observations describe it at the start of this hour."""
        env = self.env
        t = env.time_step
        obs = {b.name: b.observations(normalize=False, periodic_normalization=False) for b in env.buildings}
        o0 = obs[env.buildings[0].name]
        shared = {
            "hour": int(o0["hour"]),
            "day_type": int(o0["day_type"]),
            "outdoor_c": _f(o0["outdoor_dry_bulb_temperature"]),
            "outdoor_c_forecast": [_f(o0[f"outdoor_dry_bulb_temperature_predicted_{i}"]) for i in (1, 2, 3)],
            "direct_solar_forecast": [_f(o0["direct_solar_irradiance"])]
            + [_f(o0[f"direct_solar_irradiance_predicted_{i}"]) for i in (1, 2, 3)],
            "price_forecast": [_f(o0["electricity_pricing"])]
            + [_f(o0[f"electricity_pricing_predicted_{i}"]) for i in (1, 2, 3)],
            "carbon_intensity": _f(o0["carbon_intensity"]),
            "forecast_horizons_h": [0, *dc.FORECAST_HORIZONS_H],
        }
        buildings, baseline, bounds = {}, {}, {}
        for b in env.buildings:
            o = obs[b.name]
            buildings[b.name] = {
                "indoor_c": _f(o["indoor_dry_bulb_temperature"]),
                "setpoint_c": _f(o["indoor_dry_bulb_temperature_cooling_set_point"]),
                "occupants": _f(o["occupant_count"]),
                "cooling_demand_kwh": _f(b.energy_simulation.cooling_demand_without_control[t]),
                "dhw_demand_kwh": _f(o["dhw_demand"]),
                "plug_load_kwh": _f(o["non_shiftable_load"]),
                "solar_kwh": _f(o["solar_generation"]),
                "battery_soc": _f(o["electrical_storage_soc"]),
                "dhw_soc": _f(o["dhw_storage_soc"]),
                "grid_kwh": _f(o["net_electricity_consumption"]),
                "power_outage": bool(_f(o.get("power_outage", 0.0))),
                "battery_capacity_kwh": round(_f(b.electrical_storage.capacity), 4),
                "battery_power_kw": round(_f(b.electrical_storage.nominal_power), 4),
                "dhw_capacity_kwh": round(_f(b.dhw_storage.capacity), 4),
                "cooling_power_kw": round(_f(b.cooling_device.nominal_power), 4),
                "dhw_heater_efficiency": round(_f(b.dhw_device.efficiency), 4),
                "load_kwh": self._load_before_storage(b, o),
            }
            baseline[b.name] = {"cooling": self._baseline_cooling(b), "dhw": 0.0, "battery": 0.0}
            bnd = {"cooling": [0.0, 1.0], "dhw": [-1.0, 1.0], "battery": [-1.0, 1.0]}
            if self.control:
                low, high = b.action_space.low, b.action_space.high
                for i, a in enumerate(b.active_actions):
                    if a in DEVICE_OF_ACTION:
                        bnd[DEVICE_OF_ACTION[a]] = [round(_f(low[i]), 4), round(_f(high[i]), 4)]
            bounds[b.name] = bnd
        return {"time_step": int(t), "shared": shared, "buildings": buildings, "baseline": baseline, "bounds": bounds}

    def _outcome(self, t: int) -> dict:
        """What happened in every building during hour t."""
        out = {}
        for b in self.env.buildings:
            es = b.energy_simulation
            indoor = _f(es.indoor_dry_bulb_temperature[t])
            setpoint = _f(es.indoor_dry_bulb_temperature_cooling_set_point[t])
            occupants = _f(es.occupant_count[t])
            out[b.name] = {
                "grid_kwh": round(_f(b.net_electricity_consumption[t]), 5),
                "cost_usd": round(_f(b.net_electricity_consumption_cost[t]), 6),
                "emission_kg": round(_f(b.net_electricity_consumption_emission[t]), 6),
                "indoor_c": round(indoor, 4),
                "setpoint_c": round(setpoint, 4),
                "occupants": round(occupants, 2),
                "battery_soc": round(_f(b.electrical_storage.soc[t]), 5),
                "dhw_soc": round(_f(b.dhw_storage.soc[t]), 5),
                "solar_kwh": round(abs(_f(b.solar_generation[t])), 5),
                "uncomfortable": bool(occupants > 0 and abs(indoor - setpoint) > dc.COMFORT_BAND_K),
            }
        return out
