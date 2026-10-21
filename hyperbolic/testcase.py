"""Facts about the BOPTEST test case Hyperbolic supervises.

Everything here comes from the multizone_office_simple_air documentation in
the BOPTEST repository (testcases/multizone_office_simple_air/doc/index.html).
"""

from __future__ import annotations

TESTCASE = "multizone_office_simple_air"
FLOOR_AREA_M2 = 1662.66
STEP_SECONDS = 3600

# Zone keys as BOPTEST spells them in point names, and display names.
ZONES = ("nor", "eas", "sou", "wes", "cor")
ZONE_NAMES = {"nor": "North", "eas": "East", "sou": "South", "wes": "West", "cor": "Core"}
ZONE_AREA_M2 = {"nor": 207.58, "sou": 207.58, "eas": 131.416, "wes": 131.416, "cor": 984.672}

# Occupied period of the stock schedule, hours of day [start, end).
OCCUPIED_START_HOUR = 6
OCCUPIED_END_HOUR = 19

# Stock supervisory setpoints in degC (doc Table 2).
STOCK_OCCUPIED_HEAT_C = 20.0
STOCK_OCCUPIED_COOL_C = 24.0
STOCK_UNOCCUPIED_HEAT_C = 12.0
STOCK_UNOCCUPIED_COOL_C = 30.0
STOCK_SUPPLY_AIR_OCCUPIED_C = 12.0

# Scenario time periods (doc "Scenario Information").
SCENARIOS = {
    "typical_heat_day": {"name": "Typical heat day", "start_day": 11, "end_day": 25},
    "peak_heat_day": {"name": "Peak heat day", "start_day": 19, "end_day": 33},
    "typical_cool_day": {"name": "Typical cool day", "start_day": 137, "end_day": 151},
    "peak_cool_day": {"name": "Peak cool day", "start_day": 192, "end_day": 206},
    "mix_day": {"name": "Mix day", "start_day": 77, "end_day": 91},
}
DEFAULT_SCENARIOS = ("typical_heat_day", "peak_heat_day")
DEFAULT_ELECTRICITY_PRICE = "dynamic"
WARMUP_DAYS = 7

# BOPTEST core KPIs with units (kpis/kpi_calculator.py get_core_kpis).
KPIS = {
    "tdis_tot": ("Thermal discomfort", "K h/zone"),
    "idis_tot": ("Air quality discomfort", "ppm h/zone"),
    "ener_tot": ("Energy use", "kWh/m2"),
    "cost_tot": ("Operating cost", "$/m2"),
    "emis_tot": ("Emissions", "kgCO2/m2"),
    "pele_tot": ("Peak electric demand", "kW/m2"),
    "pgas_tot": ("Peak gas demand", "kW/m2"),
    "pdih_tot": ("Peak district heating", "kW/m2"),
    "time_rat": ("Computation time ratio", "s/s"),
}


def zone_cap(zone: str) -> str:
    return zone.capitalize()


def heat_set_input(zone: str) -> str:
    return f"hvac_oveZonSup{zone_cap(zone)}_TZonHeaSet"


def cool_set_input(zone: str) -> str:
    return f"hvac_oveZonSup{zone_cap(zone)}_TZonCooSet"


SUPPLY_AIR_INPUT = "hvac_oveAhu_TSupSet"


def supervisory_inputs() -> list[str]:
    """Overwritable inputs the supervisor is allowed to touch, without suffix."""
    names = []
    for z in ZONES:
        names.append(heat_set_input(z))
        names.append(cool_set_input(z))
    names.append(SUPPLY_AIR_INPUT)
    return names


def zone_temp_point(zone: str) -> str:
    return f"hvac_reaZon{zone_cap(zone)}_TZon_y"


def zone_co2_point(zone: str) -> str:
    return f"hvac_reaZon{zone_cap(zone)}_CO2Zon_y"


SUPPLY_AIR_TEMP_POINT = "hvac_reaAhu_TSup_y"
OUTDOOR_TEMP_POINT = "weaSta_reaWeaTDryBul_y"
POWER_POINTS = (
    "chi_reaPChi_y",
    "chi_reaPPumDis_y",
    "heaPum_reaPHeaPum_y",
    "heaPum_reaPPumDis_y",
    "hvac_reaAhu_PFanSup_y",
    "hvac_reaAhu_PPumCoo_y",
    "hvac_reaAhu_PPumHea_y",
)

PRICE_POINT = {
    "constant": "PriceElectricPowerConstant",
    "dynamic": "PriceElectricPowerDynamic",
    "highly_dynamic": "PriceElectricPowerHighlyDynamic",
}


def forecast_points(electricity_price: str = DEFAULT_ELECTRICITY_PRICE) -> list[str]:
    points = ["TDryBul", "HGloHor", PRICE_POINT[electricity_price]]
    for z in ZONES:
        points += [f"LowerSetp[{z}]", f"UpperSetp[{z}]", f"Occupancy[{z}]"]
    return points


def k_to_c(k: float) -> float:
    return k - 273.15


def c_to_k(c: float) -> float:
    return c + 273.15


def hour_of_day(time_s: float) -> int:
    return int((time_s % 86400) // 3600)


def is_occupied_hour(time_s: float) -> bool:
    h = hour_of_day(time_s)
    return OCCUPIED_START_HOUR <= h < OCCUPIED_END_HOUR


def stock_zone_setpoints_c(time_s: float) -> tuple[float, float]:
    """Stock (heat, cool) zone setpoints for the step starting at time_s.

    This is the occupied/unoccupied schedule only. The stock sequence also has
    warm-up and night setback modes that run inside the simulator; they are not
    reproduced here.
    """
    if is_occupied_hour(time_s):
        return STOCK_OCCUPIED_HEAT_C, STOCK_OCCUPIED_COOL_C
    return STOCK_UNOCCUPIED_HEAT_C, STOCK_UNOCCUPIED_COOL_C
