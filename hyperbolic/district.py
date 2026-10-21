"""Facts about the CityLearn dataset Hyperbolic supervises.

Dataset: citylearn_challenge_2023_phase_2_local_evaluation, the public local
evaluation set of the CityLearn 2023 challenge, shipped unchanged in
hyperbolic/data. Three buildings, one month of hourly steps, an LSTM model of
indoor temperature, a heat pump for cooling, a domestic hot water tank, a
battery and rooftop PV per building.
"""

from __future__ import annotations

from importlib import resources
from pathlib import Path

DATASET = "citylearn_challenge_2023_phase_2_local_evaluation"
DATASET_NAME = "CityLearn 2023 challenge, local evaluation"
EPISODE_HOURS = 719  # hourly decisions in the 720 time step episode
STEP_SECONDS = 3600

# CityLearn's forecast observations (`*_predicted_1/2/3`) in this dataset are the values
# 6, 12 and 24 hours ahead, not the next three hours. Price forecasts are exact;
# weather forecasts carry error. The dataset has no carbon forecast.
FORECAST_HORIZONS_H = (6, 12, 24)
LOOKAHEAD_HOURS = 24
# Rules and prompts are tuned on the first week only (168 time steps, 167 decisions);
# the full month is for reporting.
TUNING_HOURS = 167

# Combined hourly signal (0.4.0): price and carbon intensity, each scaled to 0..1 over
# now plus the 24 hour outlook, then weighted. Equal weights because the goal counts
# cost and emissions the same. 0 is the cheapest, cleanest hour in view; 1 the worst.
SIGNAL_WEIGHTS = {"price": 0.5, "carbon": 0.5}

# Peak limiter (0.4.0): the forecast of today's district peak is the lowest of the last
# PEAK_FORECAST_DAYS days' peaks of district load before storage.
PEAK_FORECAST_DAYS = 2

# A reply's reason is rejected above REASON_MAX_CHARS; the prompt asks for at most
# REASON_TARGET_CHARS so a long sentence never costs a fallback.
REASON_MAX_CHARS = 300
REASON_TARGET_CHARS = 150

# CityLearn action names and the short keys the supervisor uses.
DEVICES = {
    "cooling_device": "cooling",
    "dhw_storage": "dhw",
    "electrical_storage": "battery",
}
DEVICE_LABELS = {
    "cooling": "heat pump cooling, fraction of nominal power",
    "dhw": "hot water tank, fraction of capacity to charge (+) or discharge (-)",
    "battery": "battery, fraction of capacity to charge (+) or discharge (-)",
}

# CityLearn counts an occupied hour as uncomfortable outside setpoint +/- this band
# (citylearn.data.EnergySimulation.DEFUALT_COMFORT_BAND).
COMFORT_BAND_K = 2.0

# CityLearn KPIs reported by CityLearnEnv.evaluate(). Every one is lower-is-better.
# Ratios are relative to CityLearn's no-control reference (no storage, heat pump at
# ideal load), so the reference run itself scores 1.0 on them.
KPIS = {
    "cost_total": ("Electricity cost", "ratio to no control"),
    "carbon_emissions_total": ("Carbon emissions", "ratio to no control"),
    "electricity_consumption_total": ("Grid import", "ratio to no control"),
    "discomfort_proportion": ("Discomfort", "share of occupied hours"),
    "discomfort_hot_proportion": ("Too warm", "share of occupied hours"),
    "discomfort_cold_proportion": ("Too cool", "share of occupied hours"),
    "ramping_average": ("Ramping", "ratio to no control"),
    "daily_peak_average": ("Daily peak", "ratio to no control"),
    "all_time_peak_average": ("All-time peak", "ratio to no control"),
    "daily_one_minus_load_factor_average": ("1 - daily load factor", "ratio to no control"),
    "one_minus_thermal_resilience_proportion": ("1 - thermal resilience", "share of outage hours"),
    "power_outage_normalized_unserved_energy_total": ("Unserved energy in outages", "share"),
}
HEADLINE_KPIS = ("cost_total", "carbon_emissions_total", "discomfort_proportion")


def dataset_dir() -> Path:
    return Path(str(resources.files("hyperbolic").joinpath("data", DATASET)))


def schema_path() -> Path:
    return dataset_dir() / "schema.json"
