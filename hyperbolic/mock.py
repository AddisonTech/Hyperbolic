"""Offline stand-in for the BOPTEST service.

A small two-node (air and mass) thermal model per zone with a simplified VAV
reheat air handler and the stock schedule from the test case documentation. It is
driven by the test case's own hourly weather, price, occupancy and comfort band data
(hyperbolic/data, extracted from the BOPTEST repository, BSD 3-clause license).

This is not BOPTEST. Its numbers exist so the pipeline, the envelope, the replay
and the viewer can be exercised offline. Never compare mock KPIs with published
BOPTEST results.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from importlib import resources

from . import testcase as tc

CP_AIR = 1005.0
RHO_AIR = 1.2
SUBSTEPS = 30  # 120 s substeps per hourly control step

_DESIGN_FLOW_M3S = {"nor": 0.947948667, "sou": 0.947948667, "eas": 0.9001996, "wes": 0.700155244, "cor": 4.4966688}
_REHEAT_CAP_W = {"nor": 6870.0, "sou": 6870.0, "eas": 6520.0, "wes": 5070.0, "cor": 32600.0}
_FACADE_M = {"nor": 45.4, "sou": 45.4, "eas": 28.8, "wes": 28.8, "cor": 0.0}
_SOLAR_FACTOR = {"nor": 0.12, "sou": 0.55, "eas": 0.32, "wes": 0.32, "cor": 0.0}
_MIN_FLOW_FRAC = 0.3
_MIN_OA_KGS = 0.8590431 * RHO_AIR
_FAN_DESIGN_W = 4700.0
_HEAT_SUPPLY_K = 318.15
_STOCK_HEATING_SUPPLY_C = 35.0
_CORE_COUPLING_W_K = 250.0


@dataclass
class _Zone:
    key: str
    c_air: float
    c_mass: float
    h_am: float
    ua: float
    window_m2: float
    m_design: float
    reheat_cap: float
    t_air: float = 20.0
    t_mass: float = 20.0


def _load_data() -> dict[int, dict[str, float]]:
    rows = {}
    path = resources.files("hyperbolic").joinpath("data/mzosa_hourly_days_0_35.csv")
    with path.open("r", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rows[int(r["time"])] = {k: float(v) for k, v in r.items()}
    return rows


class MockBoptest:
    """Implements the Simulator protocol from hyperbolic.boptest."""

    def __init__(self) -> None:
        self.testid: str | None = None
        self.data = _load_data()
        self.t_end_data = max(self.data)
        self.step = tc.STEP_SECONDS
        self.time = 0.0
        self.end_time = 0.0
        self.price_key = tc.PRICE_POINT["dynamic"]
        self.zones: dict[str, _Zone] = {}
        self._reset_zones()
        self._kpi_on = False
        self._acc = {"tdis": 0.0, "kwh": 0.0, "cost": 0.0, "peak_kw": 0.0}
        self.last_y: dict[str, float] = {}

    # -- Simulator protocol ----------------------------------------------------

    def select(self, testcase: str) -> str:
        if testcase != tc.TESTCASE:
            raise ValueError(f"mock only implements {tc.TESTCASE}")
        self.testid = "mock-0001"
        return self.testid

    def set_step(self, seconds: int) -> None:
        if seconds != tc.STEP_SECONDS:
            raise ValueError("mock supports hourly steps only")
        self.step = seconds

    def set_scenario(self, time_period: str, electricity_price: str) -> dict[str, float]:
        sc = tc.SCENARIOS.get(time_period)
        if sc is None or sc["end_day"] * 86400 > self.t_end_data:
            raise ValueError(f"mock has data for typical_heat_day and peak_heat_day only, not {time_period}")
        if electricity_price != "dynamic":
            raise ValueError("mock has the dynamic price profile only")
        start = sc["start_day"] * 86400.0
        self.end_time = sc["end_day"] * 86400.0
        self._reset_zones()
        self.time = start - tc.WARMUP_DAYS * 86400.0
        self._kpi_on = False
        while self.time < start:
            self._simulate_hour({})
        self._kpi_on = True
        self._acc = {"tdis": 0.0, "kwh": 0.0, "cost": 0.0, "peak_kw": 0.0}
        return dict(self.last_y)

    def advance(self, u: dict[str, float]) -> dict[str, float]:
        if self.time >= self.end_time - 1e-6:
            return {}
        self._simulate_hour(u)
        return dict(self.last_y)

    def forecast(self, points: list[str], horizon: int, interval: int) -> dict[str, list[float]]:
        out: dict[str, list[float]] = {"time": []}
        for p in points:
            out[p] = []
        t = self.time
        while t <= self.time + horizon + 1e-6:
            row = self._row(t)
            out["time"].append(t)
            for p in points:
                out[p].append(self._forecast_value(row, p))
            t += interval
        return out

    def kpi(self) -> dict[str, float | None]:
        a = self._acc
        return {
            "tdis_tot": round(a["tdis"] / len(tc.ZONES), 6),
            "idis_tot": 0.0,
            "ener_tot": round(a["kwh"] / tc.FLOOR_AREA_M2, 6),
            "cost_tot": round(a["cost"] / tc.FLOOR_AREA_M2, 6),
            "emis_tot": round(a["kwh"] * 0.341 / tc.FLOOR_AREA_M2, 6),
            "pele_tot": round(a["peak_kw"] / tc.FLOOR_AREA_M2, 6),
            "pgas_tot": None,
            "pdih_tot": None,
            "time_rat": None,
        }

    def stop(self) -> None:
        self.testid = None

    # -- internals -------------------------------------------------------------

    def _reset_zones(self) -> None:
        self.zones = {}
        for z in tc.ZONES:
            area = tc.ZONE_AREA_M2[z]
            facade = _FACADE_M[z] * 2.74
            window = 0.33 * facade
            ua = window * 2.8 + (facade - window) * 0.45 + 0.25 * area * 2.74 * RHO_AIR * CP_AIR / 3600.0
            self.zones[z] = _Zone(
                key=z,
                c_air=area * 2.74 * RHO_AIR * CP_AIR * 6.0,
                c_mass=area * 160e3,
                h_am=area * 9.0,
                ua=ua,
                window_m2=window,
                m_design=_DESIGN_FLOW_M3S[z] * RHO_AIR,
                reheat_cap=_REHEAT_CAP_W[z],
            )

    def _row(self, t: float) -> dict[str, float]:
        h0 = int(t // 3600) * 3600
        h0 = min(max(h0, 0), self.t_end_data)
        h1 = min(h0 + 3600, self.t_end_data)
        a, b = self.data[h0], self.data[h1]
        w = (t - h0) / 3600.0 if h1 != h0 else 0.0
        out = {}
        for k in a:
            if k.startswith("Occupancy") or k in ("LowerSetp", "UpperSetp", "PriceElectricPowerDynamic"):
                out[k] = a[k]  # piecewise constant like the source data
            else:
                out[k] = a[k] + (b[k] - a[k]) * w
        return out

    def _forecast_value(self, row: dict[str, float], point: str) -> float:
        if point.startswith("LowerSetp["):
            return row["LowerSetp"]
        if point.startswith("UpperSetp["):
            return row["UpperSetp"]
        if point in row:
            return row[point]
        raise KeyError(f"mock has no forecast for {point}")

    @staticmethod
    def _overwrite(u: dict[str, float], name: str) -> float | None:
        if u.get(f"{name}_activate") in (1, 1.0, True):
            return tc.k_to_c(float(u[f"{name}_u"]))
        return None

    def _simulate_hour(self, u: dict[str, float]) -> None:
        t_hour = self.time
        stock_h, stock_c = tc.stock_zone_setpoints_c(t_hour)
        heat = {z: self._overwrite(u, tc.heat_set_input(z)) for z in tc.ZONES}
        cool = {z: self._overwrite(u, tc.cool_set_input(z)) for z in tc.ZONES}
        heat = {z: stock_h if v is None else v for z, v in heat.items()}
        cool = {z: stock_c if v is None else v for z, v in cool.items()}
        sa_over = self._overwrite(u, tc.SUPPLY_AIR_INPUT)
        occupied = tc.is_occupied_hour(t_hour)
        hour = tc.hour_of_day(t_hour)
        dt = self.step / SUBSTEPS
        p_last: dict[str, float] = {}
        t_sup_meas = 0.0
        for _ in range(SUBSTEPS):
            row = self._row(self.time)
            toa = tc.k_to_c(row["TDryBul"])
            price = row[self.price_key]
            lo, hi = tc.k_to_c(row["LowerSetp"]), tc.k_to_c(row["UpperSetp"])
            temps = [zn.t_air for zn in self.zones.values()]
            # Stock operating mode (doc Table 2), simplified.
            if occupied:
                mode = "occupied"
            elif hour == tc.OCCUPIED_START_HOUR - 1 and sum(temps) / len(temps) < tc.STOCK_OCCUPIED_HEAT_C:
                mode = "warmup"
            elif min(t - heat[z] for z, t in zip(self.zones, temps)) < 0:
                mode = "setback"
            elif max(t - cool[z] for z, t in zip(self.zones, temps)) > 0:
                mode = "setup"
            else:
                mode = "off"
            if mode == "warmup":
                zone_heat = {z: max(heat[z], tc.STOCK_OCCUPIED_HEAT_C) for z in self.zones}
            else:
                zone_heat = heat
            if mode == "occupied":
                t_sup = tc.STOCK_SUPPLY_AIR_OCCUPIED_C if sa_over is None else sa_over
            elif mode in ("warmup", "setback"):
                t_sup = _STOCK_HEATING_SUPPLY_C
            else:
                t_sup = tc.STOCK_SUPPLY_AIR_OCCUPIED_C
            fan_on = mode != "off"
            q_reheat = 0.0
            m_tot = 0.0
            mt_sum = 0.0
            q_hvac: dict[str, float] = {}
            for z, zn in self.zones.items():
                occ_gain = row[f"InternalGainsCon[{z}]"]
                solar = row["HGloHor"] * zn.window_m2 * _SOLAR_FACTOR[z] * 0.4
                g_air = occ_gain + 0.3 * solar
                if z != "cor":
                    core_term = _CORE_COUPLING_W_K * (self.zones["cor"].t_air - zn.t_air)
                else:
                    core_term = sum(_CORE_COUPLING_W_K * (o.t_air - zn.t_air) for k, o in self.zones.items() if k != "cor")

                def hold(setp: float, zn=zn, g_air=g_air, toa=toa, core_term=core_term) -> float:
                    return (zn.c_air * (setp - zn.t_air) / dt - g_air - core_term
                            + zn.h_am * (zn.t_air - zn.t_mass) + zn.ua * (zn.t_air - toa))

                if not fan_on:
                    q, m = 0.0, 0.0
                else:
                    m_min = _MIN_FLOW_FRAC * zn.m_design
                    q_free = m_min * CP_AIR * (t_sup - zn.t_air)
                    need_h = hold(zone_heat[z])
                    need_c = hold(cool[z])
                    if q_free < need_h:
                        q = min(need_h, q_free + zn.reheat_cap)
                        q_reheat += q - q_free
                        m = m_min
                    elif q_free > need_c and t_sup < zn.t_air:
                        q = max(need_c, zn.m_design * CP_AIR * (t_sup - zn.t_air))
                        m = min(zn.m_design, max(m_min, q / (CP_AIR * (t_sup - zn.t_air))))
                    else:
                        q, m = q_free, m_min
                    if mode in ("setback", "warmup") and q < 0:
                        q, m = 0.0, 0.0
                q_hvac[z] = q
                m_tot += m
                mt_sum += m * zn.t_air
                zn._g_air, zn._core = g_air, core_term  # type: ignore[attr-defined]
                zn._solar = solar  # type: ignore[attr-defined]
                zn._rad = occ_gain  # type: ignore[attr-defined]
            # Air handler: mixing, economizer, coils.
            q_coil_h = q_coil_c = 0.0
            if m_tot > 0:
                t_ret = mt_sum / m_tot
                f_min = min(1.0, _MIN_OA_KGS / m_tot) if mode in ("occupied",) else 0.0
                t_mix = f_min * toa + (1 - f_min) * t_ret
                if t_mix > t_sup and toa < t_ret and mode in ("occupied", "setup"):
                    f = min(1.0, max(f_min, (t_ret - t_sup) / max(t_ret - toa, 1e-6)))
                    t_mix = f * toa + (1 - f) * t_ret
                if t_mix < t_sup:
                    q_coil_h = m_tot * CP_AIR * (t_sup - t_mix)
                else:
                    q_coil_c = m_tot * CP_AIR * (t_mix - t_sup)
                t_sup_meas = t_sup
            else:
                t_sup_meas = sum(zn.t_air for zn in self.zones.values()) / len(self.zones)
            toa_k = tc.c_to_k(toa)
            cop_hp = min(5.0, max(1.2, 0.3 * _HEAT_SUPPLY_K / max(_HEAT_SUPPLY_K - toa_k, 1.0)))
            cop_ch = max(2.0, 3.8 - 0.04 * (toa - 25.0))
            p_hp = (q_reheat + q_coil_h) / cop_hp
            p_ch = q_coil_c / cop_ch
            frac = m_tot / sum(zn.m_design for zn in self.zones.values())
            p_fan = _FAN_DESIGN_W * (0.1 + 0.9 * frac ** 3) if fan_on and m_tot > 0 else 0.0
            p_pum_h = 180.0 if (q_reheat + q_coil_h) > 1.0 else 0.0
            p_pum_c = 120.0 if q_coil_c > 1.0 else 0.0
            p_total = p_hp + p_ch + p_fan + p_pum_h + p_pum_c
            p_last = {"hp": p_hp, "ch": p_ch, "fan": p_fan, "ph": p_pum_h, "pc": p_pum_c}
            # Integrate zone states.
            for z, zn in self.zones.items():
                q_air = q_hvac[z] + zn._g_air + zn._core  # type: ignore[attr-defined]
                q_mass = zn._rad + 0.7 * zn._solar  # type: ignore[attr-defined]
                d_air = (q_air + zn.h_am * (zn.t_mass - zn.t_air) + zn.ua * (toa - zn.t_air)) / zn.c_air
                d_mass = (q_mass + zn.h_am * (zn.t_air - zn.t_mass)) / zn.c_mass
                zn.t_air += d_air * dt
                zn.t_mass += d_mass * dt
            if self._kpi_on:
                kwh = p_total * dt / 3.6e6
                self._acc["kwh"] += kwh
                self._acc["cost"] += kwh * price
                self._acc["peak_kw"] = max(self._acc["peak_kw"], p_total / 1000.0)
                for zn in self.zones.values():
                    dev = max(0.0, lo - zn.t_air) + max(0.0, zn.t_air - hi)
                    self._acc["tdis"] += dev * dt / 3600.0
            self.time += dt
        self.time = round(self.time, 6)
        row = self._row(self.time)
        y = {"time": self.time}
        for z, zn in self.zones.items():
            occ = row[f"Occupancy[{z}]"]
            y[tc.zone_temp_point(z)] = round(tc.c_to_k(zn.t_air), 4)
            y[tc.zone_co2_point(z)] = round(420.0 + 18.0 * occ / max(tc.ZONE_AREA_M2[z] / 100.0, 1.0), 2)
        y[tc.SUPPLY_AIR_TEMP_POINT] = round(tc.c_to_k(t_sup_meas), 4)
        y[tc.OUTDOOR_TEMP_POINT] = round(row["TDryBul"], 4)
        y["heaPum_reaPHeaPum_y"] = round(p_last.get("hp", 0.0), 3)
        y["chi_reaPChi_y"] = round(p_last.get("ch", 0.0), 3)
        y["hvac_reaAhu_PFanSup_y"] = round(p_last.get("fan", 0.0), 3)
        y["hvac_reaAhu_PPumHea_y"] = round(p_last.get("ph", 0.0), 3)
        y["hvac_reaAhu_PPumCoo_y"] = round(p_last.get("pc", 0.0), 3)
        y["chi_reaPPumDis_y"] = 0.0
        y["heaPum_reaPPumDis_y"] = 0.0
        self.last_y = y
