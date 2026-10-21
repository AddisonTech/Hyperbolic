"""A tiny deterministic district with the same state shape as CityLearnSimulator.

Used only by tests that exercise runner logic (fallback, budget, key handling)
where the physics does not matter and speed does.
"""

from __future__ import annotations

import math

BUILDINGS = ("Building_1", "Building_2", "Building_3")


class FakeDistrict:
    kind = "fake"

    def __init__(self) -> None:
        self.t = 0
        self.end = 0
        self.soc = {b: 0.5 for b in BUILDINGS}
        self.dhw = {b: 0.5 for b in BUILDINGS}
        self.indoor = {b: 24.0 for b in BUILDINGS}
        self.sent: list[dict | None] = []

    def start(self, hours: int | None) -> dict:
        self.t = 0
        self.end = (hours or 48) - 1
        return self.state()

    def state(self) -> dict:
        h = self.t % 24
        price = 0.05 if h < 16 else 0.25 if h < 21 else 0.05
        occupied = 8 <= h < 20
        return {
            "time_step": self.t,
            "shared": {
                "hour": h + 1, "day_type": 1 + (self.t // 24) % 7,
                "outdoor_c": 25 + 5 * math.sin(h / 24 * 2 * math.pi),
                "outdoor_c_forecast": [26.0, 27.0, 28.0],
                "direct_solar_forecast": [300.0, 320.0, 340.0, 360.0],
                "price_forecast": [price, price, 0.25 if 14 <= h < 20 else price, 0.25],
                "carbon_intensity": 0.4,
            },
            "buildings": {b: {
                "indoor_c": self.indoor[b], "setpoint_c": 24.0, "occupants": 3.0 if occupied else 0.0,
                "cooling_demand_kwh": 1.0, "dhw_demand_kwh": 0.1, "plug_load_kwh": 0.4, "solar_kwh": 0.8,
                "battery_soc": self.soc[b], "dhw_soc": self.dhw[b], "grid_kwh": 0.5, "power_outage": False,
                "battery_capacity_kwh": 4.0, "battery_power_kw": 3.32, "dhw_capacity_kwh": 2.0,
            } for b in BUILDINGS},
            "baseline": {b: {"cooling": 0.3, "dhw": 0.0, "battery": 0.0} for b in BUILDINGS},
            "bounds": {b: {"cooling": [0.0, 1.0], "dhw": [-1.0, 1.0], "battery": [-0.83, 0.83]} for b in BUILDINGS},
        }

    def step(self, actions: dict | None) -> tuple[dict, dict | None]:
        self.sent.append(actions)
        out = {}
        for b in BUILDINGS:
            a = (actions or {}).get(b, {"cooling": 0.3, "dhw": 0.0, "battery": 0.0})
            self.soc[b] = min(1.0, max(0.0, self.soc[b] + a["battery"] * 0.9))
            self.dhw[b] = min(1.0, max(0.0, self.dhw[b] + a["dhw"] * 0.9))
            self.indoor[b] = round(self.indoor[b] + (0.3 - a["cooling"]) * 2.0, 4)
            out[b] = {"grid_kwh": 1.0 + a["battery"], "cost_usd": 0.05, "emission_kg": 0.4,
                      "indoor_c": self.indoor[b], "setpoint_c": 24.0, "occupants": 3.0, "battery_soc": self.soc[b],
                      "dhw_soc": self.dhw[b], "solar_kwh": 0.8, "uncomfortable": abs(self.indoor[b] - 24) > 2}
        self.t += 1
        return out, None if self.t > self.end else self.state()

    def kpis(self) -> list[dict]:
        return [{"cost_function": "cost_total", "level": "district", "name": "District", "value": 1.0}]

    def close(self) -> None:
        pass
