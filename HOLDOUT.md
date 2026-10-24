# Holdout

Chosen and sealed on 2026-10-23, at the start of 0.11.0, before any 0.11.0 tuning and before any controller was run on it. Nothing in 0.11.0 or later is tuned on it, and it is scored once, for the final result, with `--holdout-final`.

## The choice

**Buildings 4, 5 and 6 of `citylearn_challenge_2023_phase_3_1`** (CityLearn v3.0.2), June, July and August, each its own episode:

| Key | Dataset name in run manifests | Hours |
|---|---|---|
| `holdout-06` | `citylearn_challenge_2023_phase_3_1_buildings_4_5_6_month_06` | 719 |
| `holdout-07` | `citylearn_challenge_2023_phase_3_1_buildings_4_5_6_month_07` | 743 |
| `holdout-08` | `citylearn_challenge_2023_phase_3_1_buildings_4_5_6_month_08` | 743 |

The files are copied unchanged into `holdout/citylearn_challenge_2023_phase_3_1` (all 16, Buildings 1 to 3 included, so the copy can be checked against upstream file for file). A holdout month is written out with only Buildings 4, 5 and 6 in its schema.

## No fully clean holdout exists

Plainly: CityLearn v3.0.2 ships no dataset that is both new to this project and fully compatible with it. The closest option is the one above, and it is new only in its buildings.

Every dataset CityLearn v3.0.2 lists (`DataSet.get_dataset_names()`; the package fetches them from the CityLearn repository at that tag), checked against the project's three actions (`cooling_device`, `dhw_storage`, `electrical_storage`) and 30 active observations:

| Datasets | Actions | Why not |
|---|---|---|
| `citylearn_challenge_2023_phase_2_local_evaluation` | same | the reported phase 2 month |
| `citylearn_challenge_2023_phase_1` | same | byte for byte the phase 2 month's data |
| `citylearn_challenge_2023_phase_2_online_evaluation_1` | same | the tuning months |
| `..._online_evaluation_2`, `..._online_evaluation_3` | same | the tuning months with another outage seed |
| `citylearn_challenge_2023_phase_3_1`, `_3_2`, `_3_3` | same | Buildings 1 to 3, weather, pricing and carbon are value for value the tuning months (all 2,208 hours, every column); Buildings 4 to 6 are new. The three sets differ only in the outage seed (65647, 42647, 57841) |
| `citylearn_challenge_2020_climate_zone_1` to `4`, `citylearn_challenge_2021` | cooling storage, dhw, battery | no heat pump action, no LSTM building model, other observations |
| `citylearn_challenge_2022_phase_1` to `3`, `_phase_all` and its variants | battery only (some with EVs, deferrable loads) | no cooling or tank action |
| `baeda_3dem` | cooling, cooling storage, dhw | no battery, other observations |
| `ca_alameda_county_neighborhood`, `tx_travis_county_neighborhood`, `vt_chittenden_county_neighborhood` | `cooling_or_heating_device`, dhw, battery | a combined heating and cooling action, 9 of the 30 observations missing and 16 others added, 47 to 100 buildings, a full year |
| `quebec_neighborhood_with_demand_response_set_points`, `..._without_...` | heating only | no cooling, battery or tank action |
| `citylearn_three_phase_*` demos | EVs, battery, deferrable loads | no cooling or tank action |

## Why Buildings 4, 5 and 6 of phase 3 set 1

- **Compatible.** The same three actions and the same 30 observations as the project's month set. Each building is a `citylearn.building.LSTMDynamicsBuilding` with a heat pump for cooling, an electric heater with a hot water tank, a battery and 2.8 kW of PV, and CityLearn's stochastic outage model. The project's code and prompts name no building. A baseline episode of each month loads and runs (checked in 0.11.0; no other controller was run).
- **New to the project.** Their energy simulation data (loads, cooling and hot water demand, occupancy, setpoints, the no-control indoor temperature) and their LSTM models (`Building_4.pth` to `Building_6.pth`) appear in no dataset this project has run, tuned or reported on. Their batteries and heat pumps are their own sizes (Building_4: battery 3.3 kWh at 1.61 kW, heat pump 3.6 kW; Building_5: 4.0 kWh at 3.32 kW, 5.8 kW; Building_6: 3.3 kWh at 1.61 kW, 4.1 kW). Their occupied-hour cooling setpoints run from 21.7 to 27.2 C, a range like the project's buildings'.
- **Not new: the weather, the tariff and the carbon intensity.** They are the tuning months' series, hour for hour, so the strategy settings searched on the tuning months have seen these prices and this weather. The holdout tests the agent and the strategy on buildings they were not shaped on, not on an unseen climate or tariff.
- **Outages.** The stochastic outage model is on for all three buildings (seed 65647, SAIFI 1.436, CAIDI 331.2), so outage hours fall where the project has not seen them. The tuning months have no outages; phase 2 has one, of 15 hours.
- **Set 1, not 2 or 3.** They differ only in the outage seed. Set 1 was picked first, before anything was run on any of them.
- **Three months, each its own episode**, the same split as the tuning months, so a result does not rest on one month.

The closest alternatives were weaker. All six buildings of phase 3 would mix three buildings the project has tuned on. Online evaluation 2 or 3 is the tuning months again with only the outage seed changed. The neighbourhood datasets would need a different action and observation mapping, which would test the adapter more than the controller.

## The seal

- `hyperbolic months` and `hyperbolic compare` refuse a holdout month or a run recorded on one, for any controller, unless `--holdout-final` is passed. With it, `months` scores the holdout months only, never mixed with the month set.
- The viewer data writer (`compare` and the live page's Publish) refuses a holdout pair without the flag.
- `hyperbolic run --month holdout-06` (and 07, 08) records a run but prints no KPIs. `hyperbolic baseline` runs on the holdout, as the load check needs.
- `hyperbolic.months.months()` never lists the holdout, so `scripts/tune_strategy.py`, `scripts/analyze_deviations.py` and the default `hyperbolic months` cannot reach it.
- Before scoring, the code checks every file in `holdout/citylearn_challenge_2023_phase_3_1` against these sha256 hashes (text files with LF line endings) and refuses if any differs or an extra file appears:

| File | sha256 |
|---|---|
| Building_1.csv | a7b27f4a3622305e60da0a32a92d468563705f69ebdec2c13d0dc6b2fd705ac1 |
| Building_1.pth | 15e137b9e1930370708346d1298ca1f8b937cdb7c8e47e43f2555e543528d394 |
| Building_2.csv | 2993728aaf8e270abaa90f08a7aec4e66f584f58927ce6d6dfe5d9582929e109 |
| Building_2.pth | 36515f53e995061148697327ee416ed305c756418584f430597616399342a0a3 |
| Building_3.csv | aca204f9943850e794021450a23ed97407a9fed07fc43c6b14123e6c7667ab0a |
| Building_3.pth | 42d10bf54ea210d0626d1d55568f0ad7a0b9fb600f5e2802420a3a4d77168794 |
| Building_4.csv | 89d94801d834ce1409ca360b661357176a73834a9f5a90b2345528ba320bd956 |
| Building_4.pth | 4eabbb6c24e2c0482c55768541dce6c1f75e5aedcbaf01ae5c8786177a96d974 |
| Building_5.csv | 9c5a9a91dd4cb22ffa96c0dad75a995f33a6cda95cab1fd3dfafbf5e2e1da672 |
| Building_5.pth | f0e39abe58629e28d9cbaf8ffdadf41163aa97a0ec5763608d3028c1e47b22ae |
| Building_6.csv | ecc75e8eb17a4b9e6d28e90cfc8892a596b18197e9d84bbb492b1c050b93bf71 |
| Building_6.pth | d349f9cf27c6ebad5a226c81e7729c0050bdb974793acfbd1cfbf1ff600ee2b6 |
| carbon_intensity.csv | f106216393efe4eee30a5b85823f1fddff2676a09a58a3f63cd28482220516ad |
| pricing.csv | f06036bdb7b72d4bf13547da6f8453ab9f7095c5fabcf2b6929f93a79e1d0126 |
| schema.json | 500bdd747f45d8b63295a5ce7ee557ffda930d25210c32c591ef15d23e3306af |
| weather.csv | aeb1420f6102c5df2bddc55f211d41cf16e5f572a6fcce3cce8ad37b007875ce |

The seal is a procedure, not cryptography: a recorded run's `result.json` still holds its KPIs. What it guarantees is that the project's own tools never score the holdout by accident, and that the files scored at the end are the files chosen here.

The data is copied unchanged from the CityLearn repository (tag v3.0.2) under the MIT license in `hyperbolic/data/CITYLEARN_LICENSE.txt`.
