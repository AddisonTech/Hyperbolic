# Hyperbolic

**A month of building ops in an hour.**

An AI supervisor that runs a simulated district and tries to beat the no-control reference on cost, emissions and comfort.

Hyperbolic runs [CityLearn](https://github.com/citylearn-project/CityLearn), an open source district energy simulator, entirely on one machine. Every simulated hour it reads CityLearn's observations, forecasts and prices for all buildings, asks a language model for one action per device, passes the answer through a deterministic safety envelope, and applies what survives. Both the agent and the reference are scored by CityLearn's own KPI evaluation, so the numbers come from the benchmark, not from this project.

Replay viewer and scorecard: `docs/index.html`, published with GitHub Pages. Both sides shown there are real CityLearn runs: the no-control baseline and the live 0.9.0 Haiku run (see [Version 0.9.0](#version-090)). It replaces the 0.8.0 live run there; the 0.7.0 live run scored worse and was never published (see [Version 0.7.0](#version-070)).

To watch a run live on your own machine instead, see [Watch it live](#watch-it-live).

**This is a simulator project.** Nothing here connects to a real building, BAS, or customer system.

## Why it is built this way

- **Deterministic code does the safety work.** The model never acts on the simulator directly. Plain Python checks every value against hard limits first.
- **The model only makes the supervisory call.** One action per device per building, once an hour. Everything below that is CityLearn's physics.
- **Every decision is logged and replayable.** Each run folder holds the full request, the raw reply, tokens, cost, every clamp and fallback with its reason, and every simulator state and outcome. `hyperbolic replay` re-runs the whole thing with zero model calls and zero simulator calls and checks it reproduces exactly.
- **Results are graded honestly.** KPIs come from `CityLearnEnv.evaluate()` on an official challenge dataset. The viewer states a loss as plainly as a win.
- **Nothing outside the machine.** Version 0.1.0 targeted the hosted BOPTEST service, which stopped starting tests. CityLearn runs locally and the dataset ships with the repository, so a run needs no server and no download.

## Dataset

`citylearn_challenge_2023_phase_2_local_evaluation`, the public local evaluation set of the CityLearn 2023 challenge, the most recent official challenge. It ships unchanged in `hyperbolic/data`.

| | |
|---|---|
| Buildings | 3, each with a heat pump for cooling, a hot water tank, a battery and rooftop solar |
| Episode | 720 hourly time steps (one summer month), so 719 hourly decisions |
| Indoor temperature | Predicted by CityLearn's LSTM model of each building |
| Comfort | An occupied hour is uncomfortable outside cooling setpoint plus or minus 2 C |
| Actions per building | `cooling_device` 0 to 1 (fraction of heat pump power), `dhw_storage` -1 to 1, `electrical_storage` -1 to 1 |
| Observations | Hour, day type, outdoor temperature and solar with forecasts 6, 12 and 24 hours ahead, electricity price with exact forecasts 6, 12 and 24 hours ahead, carbon intensity (no forecast), and per building indoor temperature, setpoint, occupants, loads, solar, storage charge, net grid draw, outage flag |
| KPIs | `cost_total`, `carbon_emissions_total`, `electricity_consumption_total`, `discomfort_proportion` (hot and cold), `ramping_average`, `daily_peak_average`, `all_time_peak_average`, `daily_one_minus_load_factor_average`, `one_minus_thermal_resilience_proportion`, `power_outage_normalized_unserved_energy_total` |

The ratio KPIs are relative to CityLearn's no-control reference, so the reference itself scores 1.0 on them. Discomfort and resilience are absolute shares.

## Baseline

The baseline is CityLearn's no-control reference, exactly as its `BaselineAgent` runs it: storage idle and the heat pump meeting the ideal load. Every CityLearn KPI is normalized against it. The full-episode run is committed in `results/baseline` and replays with `hyperbolic replay results/baseline`.

| CityLearn KPI (district) | Baseline |
|---|---|
| cost_total, carbon_emissions_total, electricity_consumption_total, ramping, peaks, load factor | 1.000 (the reference) |
| discomfort_proportion | 0.171 (0.018 too warm, 0.154 too cool) |
| one_minus_thermal_resilience_proportion | 0.370 |
| power_outage_normalized_unserved_energy_total | 0.684 |

Summed from CityLearn's hourly series: $82.69 of electricity, 1,166 kg CO2, 348 uncomfortable occupied building hours over the month.

## Results

### Version 0.2.0: the live run tied the baseline

The first live run (`claude-haiku-5-5`, full month, $0.23) scored cost 1.0008, emissions 1.0045 and discomfort 0.1714, matching the reference almost to the last decimal. The HVAC and storage actions were not broken. A scripted run of extreme cooling commands through the same path moves indoor temperatures by several degrees and changes every KPI, and a test now pins that down (`tests/test_dryrun.py`). The agent simply chose to hold the baseline, because of how it was asked:

1. **Mislabeled forecasts.** CityLearn's `*_predicted_1/2/3` values in this dataset are 6, 12 and 24 hours ahead. The prompt called them the next 1, 2 and 3 hours, so at 3 pm, an hour before the price triples, the model was told the next three hours were cheap.
2. **No carbon outlook.** The dataset has no carbon forecast and the prompt gave only the current value, so the model could not tell a clean hour from a dirty one.
3. **No strategy, and a framing that rewarded holding still.** The prompt listed the rules the envelope would clamp, said clamps were held against the model, and never said that idle storage only ties the reference.

### Version 0.3.0

| CityLearn KPI (district), full month | Baseline | 0.2.0 live, Haiku | 0.3.0 rule-based check | 0.3.0 live, Haiku |
|---|---|---|---|---|
| cost_total | 1.000 | 1.0008 | **0.9650** | 0.9728 |
| carbon_emissions_total | 1.000 | 1.0045 | 1.0029 | 1.0059 |
| electricity_consumption_total | 1.000 | 1.0049 | 1.0128 | 1.0098 |
| discomfort_proportion | 0.1714 | 0.1714 | 0.1714 | 0.1714 |
| daily_peak_average | 1.000 | 1.0006 | 1.0020 | 1.0544 |
| all_time_peak_average | 1.000 | 1.0000 | 1.0000 | 1.0753 |
| ramping_average | 1.000 | 1.0288 | 1.1776 | 1.1289 |
| daily_one_minus_load_factor_average | 1.000 | 0.9963 | 0.9930 | 1.0254 |
| one_minus_thermal_resilience_proportion | 0.3698 | 0.3698 | 0.3698 | 0.3698 |
| power_outage_normalized_unserved_energy_total | 0.6844 | 0.6844 | 0.6844 | 0.6844 |
| Clamped hours, fallback hours |  |  | 0, 0 | 17, 1 |
| Model cost |  | $0.23 | none | $0.3934 |

On the first week, where its settings were chosen, the rule-based check scored cost 0.956 and emissions 0.996. Over the whole month the cost saving held (3.5 percent) but emissions came out 0.3 percent worse: battery losses eat the gap between night carbon and evening carbon on many days, and the carbon outlook is only yesterday's values. Emissions and comfort are where a model that reads the outlook has room to beat a fixed rule.

**The live run (`claude-haiku-5-5`, full month, 719 hours).** The live agent beat the baseline on cost but not the rule-based controller: cost 0.9728 against 0.9650, and emissions 1.0059 against 1.0029, both above the baseline's 1.000. Comfort was identical to the baseline. Its night charging also raised peaks: the daily peak rose 5.4 percent and the all-time peak 7.5 percent, where the rule-based controller left both within 0.2 percent of the baseline. All 17 clamped hours were battery state of charge limits, and the one fallback hour was a reply whose reason ran over the 300 character limit. The run cost $0.3934 of the $2.00 budget and replays 719 of 719 hours deterministically.

**Targets for 0.4:** emissions (below 1.000, and below the rule-based controller) and peaks (daily and all-time peaks back to the baseline or lower, so night charging does not stack on top of the existing night load).

The rule-based check is the scripted policy in `hyperbolic/model.py` (`ScriptedSupervisor`), running through exactly the same request, reply, envelope and simulator path a live model uses, with no model calls. It is a floor for the agent to clear, not a result of the model; in 0.3.0 the live agent did not clear it.

### Version 0.4.0

**What went wrong in 0.3.0**, from the committed live run:

- **It charged at the wrong hours.** Many hours share the lowest price, so the price rank read "cheapest hour of the day" almost all night and on flat-price weekend afternoons. The model charged most at hours 19 to 24, where carbon is 0.45 to 0.48 kg/kWh, close to the daily high, rather than at hours 3 to 5 (about 0.40). It then discharged at hours 16 to 18 (about 0.48), so it gained nothing on carbon and lost the round trip losses on top.
- **It stacked charging on the district's own evening peak.** The baseline's daily peak falls at hours 20 to 23 on 14 of 30 days. Charging there raised the daily peak on 16 of 30 days. The all-time peak moved from 19.77 to 21.26 kWh at day 28, hour 22, with all three batteries charging.
- **One fallback** came from a 300+ character reason; reasons averaged 154 characters.

**What changed:**

- **A peak limiter in the envelope.** The simulator now reports each building's draw this hour before any storage move (plug load, solar, hot water demand and cooling at the baseline action; within 0.03 kWh of CityLearn's own figure outside outages). After the per-device rules, the envelope trims battery charging, then tank charging, so the district's draw stays at or below the peak target: the higher of today's peak so far and the forecast of today's peak (the lowest of the last two days' peaks of draw before storage). Each trim is a clamp with rule `peak` and its own reason, so it is logged, shown in the viewer and replayed exactly.
- **Prompt version 3**: the peak (district draw now, target, headroom, forecast, today's and the month's measured peaks), a combined signal per hour (0.5 x price plus 0.5 x carbon intensity, each scaled 0 to 1 over now and the next 24 hours; an input that is flat over the window drops out) with its 24 hour outlook and the best and worst hours ahead, each building's draw before storage, and hours left in the month. The strategy is in priority order: comfort, then the peak cap, then cost and carbon, with charging spread over several low-signal hours. Reasons are asked to stay under 150 characters; the 300 character limit and its fallback are unchanged.
- **The rule-based controller** now uses the same signal and limiter, and was retuned on the first week only.

| CityLearn KPI (district), full month | Baseline | 0.3.0 rule-based | 0.3.0 live, Haiku | 0.4.0 rule-based | 0.4.0 live, Haiku |
|---|---|---|---|---|---|
| cost_total | 1.000 | 0.9650 | 0.9728 | **0.9611** | 0.9765 |
| carbon_emissions_total | 1.000 | 1.0029 | 1.0059 | **0.9947** | 0.9974 |
| discomfort_proportion | 0.1714 | 0.1714 | 0.1714 | 0.1714 | 0.1714 |
| daily_peak_average | 1.000 | 1.0020 | 1.0544 | 0.9978 | **0.9525** |
| all_time_peak_average | 1.000 | 1.0000 | 1.0753 | 1.0000 | 1.0000 |
| ramping_average | 1.000 | 1.1776 | 1.1289 | 1.1309 | **0.9965** |
| daily_one_minus_load_factor_average | 1.000 | 0.9930 | 1.0254 | 0.9913 | **0.9559** |
| electricity_consumption_total | 1.000 | 1.0128 | 1.0098 | **1.0073** | 1.0098 |
| Clamped hours, fallback hours | | 0, 0 | 17, 1 | 1, 0 | 24, 0 |
| Model cost | | none | $0.3934 | none | $0.4720 |

Bold marks the better of the two 0.4.0 columns where they differ.

The 0.4.0 rule-based controller meets every 0.4 goal on the full month: cost below 0.3.0's rule-based 0.9650, emissions below 1.000, daily peak below 1.000, all-time peak at 0.99998, and the same discomfort. Its one clamped hour is a peak trim.

**The live run (`claude-haiku-5-5`, full month, 719 hours)** is the first live run to beat the baseline on cost, emissions, daily peak, ramping and load factor at equal comfort: cost 0.9765, emissions 0.9974, daily peak 0.9525, ramping 0.9965, load factor 0.9559, discomfort 0.1714. It ties the baseline on the all-time peak (0.99998), thermal resilience and unserved energy in outages, and draws 1.0 percent more electricity (1.0098), the battery's round trip losses. It beats the 0.4.0 rule-based controller on daily peak (0.9525 against 0.9978), ramping (0.9965 against 1.1309) and load factor (0.9559 against 0.9913). The rule-based controller still wins on cost (0.9611 against 0.9765) and emissions (0.9947 against 0.9974). All 24 clamped hours were battery state of charge limits; in one of them (day 20, 5 pm) the peak limiter also trimmed charging on all three batteries. No fallbacks: every reason stayed under the limit. The run cost $0.4720 of the $2.00 budget and replays 719 of 719 hours deterministically.

**Target for 0.5:** cost. The live agent has to beat the rule-based controller's 0.9611 while keeping emissions below 1.000, the peaks it now holds, and comfort. (0.5.0 added live mode; the cost work is 0.6.0.)

### Version 0.6.0

**Goal:** the live agent beats the 0.4.0 rule-based controller on cost and emissions without giving back its daily peak, ramping and load factor wins, at equal or better comfort.

**Why the 0.4.0 live month lost on cost.** An hour by hour comparison of the live run (0.9765) with the rule-based run (0.9611) puts the gap at $1.20 of the $82.69 baseline bill. Ranked by dollars:

| Cause (live minus rule-based, phase 2 month) | Dollars | cost_total |
|---|---|---|
| Less energy sold into the 4 to 7 pm top-price hours: 86 kWh against 119 kWh, because the batteries arrived with 4.8 kWh stored against 6.6 kWh | +1.90 | +0.0247 |
| More grid charging on top-price days: 127 kWh against 113 kWh | +0.46 | +0.0057 |
| Charging at the top price, 3 building hours, 1.9 kWh: the only charging no later price could pay back | +0.11 | +0.0014 |
| Discharging between 7 am and 4 pm on top-price days, 23.5 kWh at the off-peak price (the rule-based controller: none) | -0.65 | -0.0086 |
| Discharging after 7 pm | -0.16 | -0.0019 |
| Less cycling on flat-price weekends | -0.46 | -0.0060 |
| **Total** | **+1.20** | **+0.0154** |

The batteries hold 8.5 kWh above their floor and the district draws 14.2 kWh in the three top-price hours, so every stored kWh can be sold at the top price; the winning move is to arrive full and spend it there. The agent charged at 0.10 to 0.15 of capacity per hour for only a few hours and spent charge at midday. Its own reasons for the 20 early discharge hours cite peak shaving in 12 and a high combined signal in 12: the 0.5 x price plus 0.5 x carbon signal ranks high-carbon middays as discharge hours although they sell at the off-peak price. Round trip losses were not a cause: both runs got back about 0.875 of what they charged. CityLearn's district cost is the mean of the three buildings' cost ratios, so a dollar saved in the smallest bill (Building_2, $19.74) counts 1.7 times a dollar saved in the largest.

**Why discomfort never moved, and a mapping bug.** The agent never moved cooling or the hot water tank (0 of 2,157 building hours off the baseline), and it could not see a reason to: the indoor temperature in the state was CityLearn's own observation, which for an LSTM building is the dataset's no-control value for the coming hour, written before CityLearn simulates it. Neither the agent nor the envelope's comfort rule ever saw the room the simulator produced. Over the baseline month the two differ by a median 1.0 C and up to 6.4 C, and with cooling cut by 0.3 the simulated rooms ran at 28 to 31 C while the state still said 22 to 24 C. The baseline actually overcools: 15.4 of its 17.1 percent uncomfortable hours are too cold, with the heat pump running. The state now reports the temperature CityLearn simulated for the hour just finished, and a test pins it. (CityLearn scores "too cold" against the heating setpoint; it equals the cooling setpoint in every row of both datasets used here, so that has no effect.)

**What changed:**

- **Indoor temperature fix** in `hyperbolic/sim.py`, as above.
- **Spread check in the envelope.** Grid charging of a battery is blocked when no price in the next 24 hours, after the battery's worst round trip efficiency and its standing loss until then, is worth more than the price now, while a cheaper hour is coming. That is when charging now is strictly worse than waiting. Spare solar may still be stored. Each block is a clamp with rule `spread` and its reason, for example: "price 0.0587 now, best ahead 0.0587 in 1 h does not cover 12% round trip and standing losses and a cheaper hour comes in 3 h, grid charging blocked". Nothing is fitted: the efficiency is the minimum of each battery's power efficiency curve (0.88 or 0.89 here) and the loss its own coefficient. A flat outlook does not block: on a weekend the next price peak lies beyond the 24 hour forecast, and a charge bought then still pays at Monday's peak.
- **Prompt version 4** (see [What the agent sees](#what-the-agent-sees)): the rule-based controller's plan for the hour as a reference action, a price plan, each battery's real limits and the spread check's verdict, the measured room temperature against its setpoint, and a strategy that puts price first and carbon second.
- **The rule-based controller is frozen** as the 0.4.0 reference (prompt version 3, the 0.4.0 envelope) so the bar does not move: it still scores 0.9611 and 0.9947, and a test checks that on the full month.
- **The strategy's numbers come from a separate dataset** (see [Tuning without peeking at the test month](#tuning-without-peeking-at-the-test-month)).

| CityLearn KPI (district), full month | Baseline | 0.4.0 rule-based | 0.4.0 live, Haiku | 0.6.0 v4 strategy, scripted | 0.6.0 live, Haiku |
|---|---|---|---|---|---|
| cost_total | 1.000 | 0.9611 | 0.9765 | 0.9057 | 0.9219 |
| carbon_emissions_total | 1.000 | 0.9947 | 0.9974 | 0.9506 | 0.9665 |
| discomfort_proportion | 0.1714 | 0.1714 | 0.1714 | 0.0458 | 0.0861 |
| daily_peak_average | 1.000 | 0.9978 | 0.9525 | 0.9193 | 0.9354 |
| all_time_peak_average | 1.000 | 1.0000 | 1.0000 | 0.9703 | 0.9483 |
| ramping_average | 1.000 | 1.1309 | 0.9965 | 1.0151 | 1.0174 |
| daily_one_minus_load_factor_average | 1.000 | 0.9913 | 0.9559 | 0.9661 | 0.9773 |
| electricity_consumption_total | 1.000 | 1.0073 | 1.0098 | 0.9602 | 0.9740 |
| Clamped hours, fallback hours | | 1, 0 | 24, 0 | 1, 0 | 73, 0 |
| Model cost | | none | $0.4720 | none | $0.5740 |

The "v4 strategy, scripted" column is `hyperbolic run --scripted --prompt-version 4`: the version 4 prompt's strategy executed literally by `strategy_plan_v4`, with no model, run once on this month after its numbers were chosen on the tuning set. It is evidence that the strategy the agent is given beats the rule-based controller on cost, emissions, comfort and both peaks, not a model result. It does not reach the live 0.4.0 agent's ramping or load factor, and its ramping sits 1.5 percent above the baseline. On the tuning months it scored ramping 0.9953 and load factor 0.9529.

**The 0.6.0 live run (`claude-haiku-5-5`, full month, 719 hours, prompt version 4)** beats the 0.4.0 rule-based controller on cost (0.9219 against 0.9611), emissions (0.9665 against 0.9947), grid import (0.9740 against 1.0073), discomfort (0.0861 against 0.1714), ramping (1.0174 against 1.1309), daily peak (0.9354 against 0.9978), all-time peak (0.9483 against 1.0000) and load factor (0.9773 against 0.9913). The rule-based numbers were rerun on the same machine and match 0.4.0 exactly. Against the baseline it wins on everything except ramping, 1.7 percent worse (1.0174), and hot discomfort, 0.0181 of occupied hours against 0.0176: trimming cooling in cold rooms halved the cold hours (0.0680 against 0.1538) and added a few warm ones. Thermal resilience (0.3698) and unserved energy in outages (0.6844) tie the baseline.

It trails the scripted version 4 strategy, which follows the same prompt literally (cost 0.9057, emissions 0.9506, discomfort 0.0458), and the 0.4.0 live run still has the better ramping (0.9965) and load factor (0.9559); the 0.6.0 run has the better daily peak (0.9354 against 0.9525).

73 clamped hours, 0 fallbacks. By rule: battery state of charge in 54 hours (73 clamps), cooling more than 0.15 from the baseline in 14 hours (16 clamps), the comfort rule holding cooling at the baseline in 6 hours (6 clamps), and one battery rate limit; 3 hours had two rules. The spread check and the peak limiter never had to act. The run cost $0.5740 of the $2.00 budget and replays 719 of 719 hours deterministically.

### Version 0.7.0

**Goal:** ramping below the baseline and the load factor back toward 0.4.0, without giving back cost, emissions, comfort or the peaks.

**Why the 0.6.0 live month ramped more.** The month's hourly series in `docs/data` reproduce its ramping (1.0174) and load factor (0.9773) exactly, so they can be taken apart hour by hour. CityLearn's ramping adds up every hour the district draws more than the hour before; a step down costs nothing.

| Driver, 0.6.0 live month | Ramping | Load factor, against 0.4.0 live |
|---|---|---|
| Cooling trims switching on and off | +0.0245 | +0.0158 |
| Battery | -0.0071 | +0.0056 |

- **The trims flickered.** There were 276 trim episodes with a median length of one hour, and 263 ended while the room was still occupied: the room warmed past the threshold, the trim stopped, the room cooled, and it started again. Every end was a step back up, in two or three buildings at once in 75 hours.
- **The battery nearly cancelled itself on ramping.** Stopping a discharge at 7 pm added 55.8 kWh of up-ramp and starting a charge 27.0 kWh, while starting the 4 pm discharge took 83.3 kWh away.
- **On load factor, the trims cut energy all day.** That lowers the daily mean while the daily peak, mostly 8 to 11 pm, stays; on 16 days a trim was running at the peak hour.
- **The battery now empties in the 4 to 7 pm price window** (137 kWh there against 0.4.0's 86), leaving little for the evening peak that 0.4.0 partly shaved.

**What changed:**

- **Prompt version 5** (see [What the agent sees](#what-the-agent-sees)) gives the agent last hour's district draw, the load now and at the next hour, and each building's trim last hour. Its strategy now asks the agent to:
  - hold a trim until the room is within 0.5 C of its setpoint, then ease it off by at most 0.02 per hour
  - start charging small and raise it by at most 0.15 per hour
  - spread the discharge evenly over the top-price hours
- **The numbers come from the tuning set**, under hard constraints: ramping below the baseline, with cost, emissions, discomfort and both peaks no worse than the 0.6.0 strategy. 8 of 18 settings qualified.
- **No ramp rule in the envelope.** A deterministic limit on how fast a battery action or a cooling trim may rise was built, tested and removed, because it made results worse:
  - On the tuning months, the same strategy scored ramping 0.9886 with it and 0.9816 without, at higher cost.
  - Sending the 0.6.0 live run's own actions through it raised ramping from 1.0174 to 1.0186.
  - A taper only spreads the same rise over more hours, and the KPI sums the rises either way. Fewer on and off cycles is what lowers it, which is what the strategy's hold does.
- **An evening reserve** (keeping some charge back for the 8 to 11 pm peak) lowers ramping and load factor further. On the tuning months, a reserve of 0.1 gave ramping 0.965 to 0.979 and load factor 0.945 to 0.954. But every reserve tried, down to 0.03, cost more than the 0.6.0 strategy, so it is off.
- **The public page** gains a "How it works" strip and a "Run it yourself" section (see [The replay viewer](#the-replay-viewer)).

| CityLearn KPI (district), full month | Baseline | 0.4.0 rule-based | 0.6.0 live, Haiku | 0.6.0 v4 strategy, scripted | 0.7.0 v5 strategy, scripted | 0.7.0 live, Haiku |
|---|---|---|---|---|---|---|
| cost_total | 1.000 | 0.9611 | 0.9219 | 0.9057 | 0.9015 | 0.9320 |
| carbon_emissions_total | 1.000 | 0.9947 | 0.9665 | 0.9506 | 0.9430 | 0.9635 |
| electricity_consumption_total | 1.000 | 1.0073 | 0.9740 | 0.9602 | 0.9523 | 0.9684 |
| discomfort_proportion | 0.1714 | 0.1714 | 0.0861 | 0.0458 | 0.0424 | 0.0741 |
| daily_peak_average | 1.000 | 0.9978 | 0.9354 | 0.9193 | 0.9081 | 0.9393 |
| all_time_peak_average | 1.000 | 1.0000 | 0.9483 | 0.9703 | 0.9597 | 0.9592 |
| ramping_average | 1.000 | 1.1309 | 1.0174 | 1.0151 | 0.9966 | 1.0358 |
| daily_one_minus_load_factor_average | 1.000 | 0.9913 | 0.9773 | 0.9661 | 0.9640 | 0.9747 |
| Clamped hours, fallback hours | | 1, 0 | 73, 0 | 1, 0 | 1, 0 | 66, 0 |
| Model cost | | none | $0.5740 | none | none | $0.6329 |

The "v5 strategy, scripted" column is `hyperbolic run --scripted --prompt-version 5`: the version 5 prompt followed literally by `strategy_plan_v5`, with no model, run once on this month after tuning. It brings ramping below the baseline (0.9966) and improves on the version 4 strategy on every line. It is not a model result. Its load factor (0.9640) does not reach the 0.4.0 live run's 0.9559, and its hot discomfort (0.0181) is a little above the baseline's 0.0176.

**The 0.7.0 live run (`claude-haiku-5-5`, full month, 719 hours, prompt version 5) missed the 0.7 goal.** Ramping, the target, went up, not down: 1.0358, against 1.0174 for 0.6.0 live. The scripted version 5 strategy reached 0.9966 on the same month, so the strategy works when it is followed exactly. The live agent did not hold cooling trims the way the prompt asks (see below).

Against 0.6.0 live it improved emissions (0.9635 against 0.9665), grid import (0.9684 against 0.9740), discomfort (0.0741 against 0.0861: too cool 0.0560 against 0.0680, too warm unchanged at 0.0181) and load factor (0.9747 against 0.9773). Ramping, cost (0.9320 against 0.9219), the daily peak (0.9393 against 0.9354), the all-time peak (0.9592 against 0.9483) and unserved energy in outages got worse. Unserved energy in outages is 0.6877 against the baseline's 0.6844, slightly worse than the baseline: the first run to go past it. Thermal resilience is 0.3698, equal to the baseline.

It still beats the 0.4.0 rule-based controller on cost (0.9320 against 0.9611), emissions (0.9635 against 0.9947), grid import (0.9684 against 1.0073), discomfort (0.0741 against 0.1714), ramping (1.0358 against 1.1309), daily peak (0.9393 against 0.9978), all-time peak (0.9592 against 1.0000) and load factor (0.9747 against 0.9913).

66 clamped hours, 0 fallbacks. By rule: battery state of charge in 51 hours (68 clamps, all charging that would have gone past 0.95, by a median 0.002), the comfort rule in 12 hours (13 clamps: 10 where the agent asked for more cooling than the baseline in a room near the bottom of its band, and 3 rounding differences under 0.001), cooling more than 0.15 from the baseline in 2 hours (3 clamps), and the peak limiter in 1 hour (1 clamp). No hour had two rules. The spread check never had to act. The run cost $0.6329 of the $2.00 budget and replays 719 of 719 hours deterministically.

**Why ramping did not come down.** Trim episodes counted the same way as the 0.6.0 diagnosis above: an hour counts as trimmed when cooling runs more than 0.002 below the baseline action (smaller gaps are rounding), and an episode counts once it has ended within the month.

| Cooling trim episodes | 0.6.0 live (prompt v4) | 0.7.0 live (prompt v5) | 0.7.0 v5 strategy, scripted |
|---|---|---|---|
| Episodes | 276 | 237 | 167 |
| Median length | 1 h | 2 h | 3 h |
| One hour long | 160 | 108 | 46 |
| Six hours or longer | 9 | 17 | 45 |
| Ended while the room was occupied | 263 | 230 | 161 |
| Ended with the room still more than 0.5 C below its setpoint | 103 | 73 | 0 |
| Ended within 0.5 C, but dropped more than 0.02 in one hour | 74 | 69 | 4 |
| Hours where two or more buildings ended a trim together | 47 | 37 | 12 |

Version 5 asks for a trim to be held until the room is within 0.5 C of its setpoint and then eased off by at most 0.02 per hour. It may end at once only when the room reaches its setpoint, empties, or needs no cooling. The live agent held trims longer than in 0.6.0, but 142 of its 237 trim ends broke that rule: 73 ended with the room still too cold, and 69 dropped in one step. The scripted strategy broke it in 4 of 167, all at the edge of the rule: two rooms at their setpoint to within rounding, and two last steps of 0.022. Each hour is a separate model call, and the trim is one number in the observation (`cooling_trim_last_hour`) that the agent often let go. Trims flickered less than in 0.6.0, so the trims alone do not explain why ramping rose above 0.6.0 live. This release does not split that rise further; 0.8.0 does (see [Version 0.8.0](#version-080)).

**The published viewer stays on the 0.6.0 live run.** The page shows the best live run so far, and 0.7.0 is not it: it is worse than 0.6.0 live on cost, ramping, both peaks and outage energy, and the cost saving the page leads with would drop from 7.8 to 6.8 percent. The 0.7.0 viewer data was built locally and is not published; `docs/data` is unchanged.

**Next for 0.8:** carry the trim's hold state in code instead of relying on the model to remember it. The plan as written for 0.7.0 (built in 0.8.0, see [Version 0.8.0](#version-080)):

- The envelope (or the peak tracker) keeps, per building, whether a trim is on and how deep it is.
- While the room is more than 0.5 C below its setpoint, the trim stays on at least as deep as last hour. Once the room is within 0.5 C, it eases off by at most 0.02 per hour. At or above the setpoint it ends at once, as now.
- The model can end a trim early only with a stated reason, in its own reply field, logged and shown in the viewer, so a dropped trim is a choice and not a lapse.
- Each hold is logged with its own rule and reason and replays exactly; older runs replay without it.
- This is not the ramp rule 0.7.0 removed. That one tapered rises, which only spread them out. This one keeps a trim on, which is what the scripted strategy does.
- Check it first on the tuning set, then aim for ramping below the baseline on the full live month without giving back cost, emissions, comfort or the peaks against 0.6.0 live.

### Version 0.8.0

**Goal:** carry the cooling trim hold in code so the live agent cannot drop it by accident, explain the 0.7.0 ramping rise first, and get live ramping below the baseline without giving back cost, emissions, comfort or the peaks against 0.6.0 live (cost 0.9219, emissions 0.9665, discomfort 0.0861, daily peak 0.9354, all-time peak 0.9483).

**Why the hourly series said 1.0374 when the KPI said 1.0358.** CityLearn's ramping adds up every hour-to-hour rise in the district's net draw, but it does not divide by the baseline run. It divides by a reference built inside the same run: the run's own net draw with storage taken out and cooling put back to the ideal load. In hour 399, during an outage in Buildings 1 and 2, the 0.7.0 agent asked for extra cooling. The grid draw was 0 anyway, but CityLearn still took the extra cooling off its reference, which read -0.71 kWh there, and the climb back to 0 at hour 400 added 0.71 kWh of rises to the denominator only (470.91 kWh against 470.20 for the baseline run). The numerator matches the hourly series to 0.00001 kWh. 0.6.0 matched exactly because its cooling was at the baseline in that outage.

**What made 0.7.0 ramp more than 0.6.0.** Every month below was simulated again from its recorded actions (identical outcomes) and each hour's rise was split among its causes with exact Shapley shares, so the parts add up to CityLearn's own figure (`scripts/split_ramping.py`). Points of `ramping_average` above 1.0:

| Cause | 0.6.0 live | 0.7.0 live | 0.7.0 v5 strategy, scripted |
|---|---|---|---|
| Trims ending | +6.37 | +5.29 | +3.61 |
| Trims starting | -4.84 | -3.30 | -1.84 |
| Trim depth changes | +0.98 | +0.75 | +0.04 |
| **Trims, net** | **+2.52** | **+2.74** | **+1.81** |
| Battery charging | -0.60 | +1.12 | +1.36 |
| Battery discharging | -0.10 | -0.33 | -3.51 |
| **Battery, net** | **-0.70** | **+0.79** | **-2.15** |
| Hot water tank | 0.00 | +0.18 | 0.00 |
| Extra cooling above the baseline | -0.07 | +0.03 | 0.00 |
| Outage hours (the reference effect above) | 0.00 | -0.15 | 0.00 |
| Reference's own rises (the denominator) | 470.20 kWh | 470.91 kWh | 470.20 kWh |
| **ramping_average** | **1.0174** | **1.0358** | **0.9966** |

- **The rise from 0.6.0 to 0.7.0 is the battery, not the trims.** Of the 1.84 points, battery charging accounts for 1.72. The trims net to 0.22. 0.7.0 used the battery about a third less: it charged 184 kWh against 272 and discharged 156 kWh against 237. In 0.6.0, daytime charging stopped as the afternoon load climbed and daytime discharges cut the load as it rose, and both cancelled rises. 0.7.0 rarely charged in the day and discharged in only 35 of the 80 building hours where the strategy says to cut the daytime peak (0.6.0: 46 of 74, the scripted strategy: 51 of 51). It also charged both hot water tanks in hour 441, against the prompt.
- **The trims are still the largest single cause in every run**, and look much the same in 0.6.0 and 0.7.0. Holding them exactly, as the scripted strategy does, still costs 1.81 points.
- **The scripted strategy is below the baseline because of its discharging** (-3.51 points): daytime peak cuts plus discharge spread over the top-price hours. Its trims account for less of the difference.
- In CityLearn's LSTM buildings the heat pump delivers exactly the fraction it is told; there is no thermostat. Room temperature enters only through what the agent or the comfort rule asks for, which is the "extra cooling" line.

So the hold alone was not expected to bring live ramping below the baseline. 0.8.0 builds it as planned and also changes what the agent is shown about the battery.

**Changes:**

- **Trim hold in the envelope** (rule `trim_hold`, `EnvelopeConfig.trim_hold`). Per building the envelope keeps whether a cooling trim is on and how deep it is (cooling more than 0.002 below the baseline action). While the room is occupied and more than 0.5 C below its setpoint, the trim stays at least as deep as last hour. Within 0.5 C it eases off by at most 0.02 per hour. It ends at once at or above the setpoint, when the room is unoccupied, or when the baseline has no cooling to trim, and no trim may start there either. `null` cooling keeps a held trim; a deeper trim is allowed. A reply that misses the held depth by less than 0.002 is taken as rounding (the observation shows the baseline and the trim to 3 decimals) and is not clamped, but the full depth stays held, so nothing drifts. The hold runs after the comfort rule and only keeps cooling below the baseline within the deviation limit the trim already passed, so the spread check, peak limiter, comfort rule, battery limits, JSON envelope, fallback and budget cap are unchanged. A fallback hour uses the baseline everywhere and ends any trim. This is not the ramp rule 0.7.0 removed: that one tapered rises, this one keeps a trim on.
- **Early end only with a reason.** Prompt version 6 replies carry `end_trim` per building: `null`, or a short reason to end that building's held trim now. Every hold action (start, hold, ease, release, end, early end) is recorded in the hour's decision under `holds` with its reason, and every value it changes is a clamp with rule `trim_hold`. Early ends are shown in the replay viewer's reason card and in the live log, and the viewer data counts them (`trim_ends_early`).
- **Prompt version 6 (default).** Version 5, plus: the strategy says the envelope holds trims in code, how a held trim behaves and how to end one early, and each building shows `cooling_trim_held`, the trim the envelope keeps this hour. The 0.4.0 rule-based `reference_action` (a controller that ramped 1.1309) is replaced by the version 5 strategy's own battery action per building, `strategy_battery`, with `strategy_battery_reason`, computed by the same code as the scripted strategy (`battery_plan_v5`).
- **Older runs replay exactly.** Settings a manifest does not have keep their old values, so every run recorded before 0.8.0 replays without the hold, and its decisions carry no `holds` key. `EnvelopeConfig.v070()` is the 0.7.0 rule set. New runs on prompt versions 1 to 5 use it too, so they behave as in 0.7.0; only version 6 runs with the hold. The 0.6.0 and 0.7.0 live months and the committed baseline replay 719 of 719 hours.
- **Evaluation tools.** `scripts/split_ramping.py` splits a run's ramping by cause as above. `scripts/evaluate_hold.py` sends a recorded run's own replies, unchanged, through its own rules (a control that must reproduce its published KPIs exactly) and through the same rules with the hold, on a fresh CityLearn month with no model calls; the result is an evaluation, never a recorded run. `scripts/tune_strategy.py --version 6` makes the same comparison for the scripted strategy on the tuning months; the version 4 and 5 searches run with the 0.7.0 rules they were made with.

**Estimates before any live run.** Checked on the tuning months first, then the phase 2 month. Nothing was tuned on the phase 2 month.

1. **The scripted v5 strategy on the tuning months**, mean of three, 0.7.0 rules against 0.8.0 rules: ramping 0.9816 against 0.9821, daily peak 0.8834 against 0.8836 and load factor 0.9517 against 0.9522 got slightly worse; cost 0.9089 against 0.9086, emissions 0.9610 against 0.9607 and all-time peak 0.8532 against 0.8530 got slightly better; discomfort is equal (0.0310). The first version of the rule, without the rounding allowance, also raised discomfort to 0.0312 and clamped 247 to 443 times a month (87 to 148 with the allowance); the allowance was added on the tuning set, before the phase 2 month was run. The cause of what remains: the strategy rebuilds its trim each hour from a baseline rounded to 3 decimals plus a 0.001 safety margin, so its held trims drift shallower by about 0.0015 an hour. The hold stops that drift, so trims stay a little deeper (lower cost) and step up a little more when they end (slightly more ramping).
2. **The scripted v5 strategy on the phase 2 month**, 0.7.0 rules against 0.8.0 rules (`--scripted --prompt-version 6`): ramping 0.9966 against 0.9957, daily peak 0.9081 against 0.9078 and all-time peak 0.9597 against 0.9593 got better; emissions (0.9430), grid import (0.9523) and load factor (0.9640) are unchanged to four decimals; **cost (0.9015 against 0.9017, exactly 0.901532 against 0.901682) and discomfort (0.0424 against 0.0430, all of it too cool) got slightly worse.** Clamped hours rose from 1 to 139, all of them the hold correcting that drift. The run replays 719 of 719 hours.
3. **The 0.7.0 live month's own replies through the 0.8.0 rules** (`scripts/evaluate_hold.py`). The control, the same replies through the 0.7.0 rules, reproduces the published 0.7.0 KPIs exactly.

| CityLearn KPI (district) | 0.6.0 live | 0.7.0 live (control) | 0.7.0 replies, 0.8.0 rules | Change |
|---|---|---|---|---|
| cost_total | 0.9219 | 0.9320 | 0.9169 | -0.0151 |
| carbon_emissions_total | 0.9665 | 0.9635 | 0.9477 | -0.0158 |
| electricity_consumption_total | 0.9740 | 0.9684 | 0.9527 | -0.0157 |
| discomfort_proportion | 0.0861 | 0.0741 | 0.0511 | -0.0230 |
| daily_peak_average | 0.9354 | 0.9393 | 0.9284 | -0.0108 |
| all_time_peak_average | 0.9483 | 0.9592 | 0.9548 | -0.0044 |
| ramping_average | 1.0174 | 1.0358 | 1.0249 | -0.0109 |
| daily_one_minus_load_factor_average | 0.9773 | 0.9747 | 0.9787 | +0.0039 |

- The hold took ramping down 1.09 points, but **not below the baseline and not below 0.6.0 live**. The trims' net share fell from 2.74 to 1.56 points: trim ends from 5.29 to 3.78, trim starts from -3.30 to -2.12, depth changes from 0.75 to -0.10. The battery's share barely moves (+0.88 against +0.79): its replies are the same, and only the rises it overlaps with changed.
- Against the 0.6.0 live targets the estimate is better on cost, emissions, discomfort (all of the gain is fewer too-cool hours; too warm is unchanged at 0.0181) and the daily peak, and **worse on the all-time peak (0.9548 against 0.9483) and ramping (1.0249 against 1.0174)**. Against 0.7.0 itself, **the load factor got worse (0.9787 against 0.9747)**: the held trims cut energy across the day while the evening peak stays.
- Trims: 174 episodes against 237, median 3 hours against 2, 60 one hour long against 108, and 4 rule breaks against 142, all four trims just over 0.02 deep that one 0.02 step leaves under the 0.002 threshold. The hold acted 668 times: 176 starts, 205 holds, 110 eases, 28 releases, and 149 ends (135 at the setpoint, 11 in an emptied room, 3 with no baseline cooling). Clamped hours rose from 66 to 323; 283 of them carry a `trim_hold` clamp.
- The replies are fixed, so later hours do not react to what the hold changed. **The battery change in prompt version 6 is not in this estimate and can only be measured live.** The scripted strategy follows `strategy_battery` exactly by construction, so no offline run can say how closely a model will. The battery accounts for 2.9 points between the 0.7.0 live month and the scripted strategy.

**Request size and cost.** A version 6 request averages 10,928 characters against 10,432 for version 5 over the same month, 4.8 percent more: the system prompt 5,221 against 4,932 characters, the schema 1,368 against 1,143 (`end_trim` in each building), and the observation 9 characters shorter. Scaled from the 0.7.0 live month (4,946 input and 771 output tokens per call, $0.6329), a Haiku month should cost about $0.66. The hard worst case per call is $0.00137 (every character a third of a token and a full 2,000 token reply), $0.99 for all 719 hours, so the $2.00 budget cap cannot stop a Haiku month; it would allow 1,457 such calls, and spending can never pass $2.00.

**Live results.** The 0.8.0 live run (`claude-haiku-5-5`, full month, 719 hours, prompt version 6, $2.00 budget) against the baseline, the 0.4.0 rule-based controller (rerun as run 20261022T162847Z, matching its published numbers) and the earlier live months:

| CityLearn KPI (district), full month | Baseline | 0.4.0 rule-based | 0.6.0 live, Haiku | 0.7.0 live, Haiku | 0.8.0 live, Haiku |
|---|---|---|---|---|---|
| cost_total | 1.000 | 0.9611 | 0.9219 | 0.9320 | **0.9190** |
| carbon_emissions_total | 1.000 | 0.9947 | 0.9665 | 0.9635 | **0.9610** |
| electricity_consumption_total | 1.000 | 1.0073 | 0.9740 | 0.9684 | **0.9695** |
| discomfort_proportion | 0.1714 | 0.1714 | 0.0861 | 0.0741 | **0.0769** |
| too cool | 0.1538 | 0.1538 | 0.0680 | 0.0560 | **0.0601** |
| too warm | 0.0176 | 0.0176 | 0.0181 | 0.0181 | **0.0168** |
| daily_peak_average | 1.000 | 0.9978 | 0.9354 | 0.9393 | **0.9264** |
| all_time_peak_average | 1.000 | 1.0000 | 0.9483 | 0.9592 | **0.9593** |
| ramping_average | 1.000 | 1.1309 | 1.0174 | 1.0358 | **1.0076** |
| daily_one_minus_load_factor_average | 1.000 | 0.9913 | 0.9773 | 0.9747 | **0.9651** |
| one_minus_thermal_resilience_proportion | 0.3698 | 0.3698 | 0.3698 | 0.3698 | **0.3698** |
| power_outage_normalized_unserved_energy_total | 0.6844 | 0.6844 | 0.6844 | 0.6877 | **0.6850** |
| Clamped hours, fallback hours | | 1, 0 | 73, 0 | 66, 0 | **312, 0** |
| Model cost | | none | $0.5740 | $0.6329 | **$0.5315** |

- **Against the 0.4.0 rule-based controller it wins on every KPI except unserved energy in outages**, where it trails by 0.0006 (0.6850 against 0.6844). Thermal resilience ties at 0.3698.
- **It is the first live run with both fewer too-cool and fewer too-warm hours than the baseline**: too cool 0.0601 against 0.1538, too warm 0.0168 against 0.0176. 0.6.0 and 0.7.0 live cut the cold hours but added warm ones (0.0181).
- **It is the best live run so far on cost, emissions and the daily peak.** It is not the best on discomfort (0.7.0 live: 0.0741), grid import (0.7.0 live: 0.9684), the all-time peak (0.6.0 live: 0.9483), or ramping and load factor, where the 0.4.0 live run, which left comfort at the baseline, still holds 0.9965 and 0.9559.
- **It missed the 0.8 goal on ramping.** Ramping fell from 1.0358 to 1.0076, below 0.6.0 live (1.0174) and below the estimate from the 0.7.0 replies (1.0249), but it is still above the baseline.
- **It gave back the all-time peak against 0.6.0 live** (0.9593 against 0.9483), which the goal said not to do. Cost, emissions, discomfort and the daily peak all improved on 0.6.0 live, as the goal asked.
- **The envelope is steering the agent.** 312 of 719 hours were clamped, 276 of them by the trim hold alone and 292 with it: 243 clamps on Building_1 cooling, 100 on Building_3 cooling and 2 on Building_2 cooling. The other rules: comfort in 28 hours, battery state of charge in 6, the deviation cap in 2 and the peak limiter in 1. The hold acted 557 times: 109 starts, 243 holds, 97 eases, 21 releases, 80 ends, and 7 early ends the agent asked for with a reason. 0 fallbacks.
- The run cost $0.5315 of the $2.00 budget (719 calls) and replays 719 of 719 hours deterministically.

**The published viewer now shows the 0.8.0 live run** in place of 0.6.0: it beats 0.6.0 live on cost (the page's headline saving goes from 7.8 to 8.1 percent), emissions, grid import, discomfort, the daily peak, ramping and load factor, and loses on the all-time peak and outage energy.

**Next for 0.9:** cut the clamp rate without losing the gains. Most clamps are the trim hold correcting replies that let a held trim go, mainly in Buildings 1 and 3, so the target is replies that keep held trims as the envelope would, with the same or better KPIs.

### Version 0.9.0

**Goal:** the agent proposes actions that already fit the envelope, so clamps drop sharply and ramping goes under 1.0, without giving back cost, emissions, comfort or peaks against the 0.8.0 live month. The envelope is identical to 0.8.0. The estimates below were built from recorded runs and the scripted strategy before any live call; the live month follows them.

**Why 312 hours were clamped.** The 0.8.0 live month had 390 clamps in 312 hours: the trim hold 345 (292 hours), comfort 32, battery state of charge 10, the deviation cap 2, the peak limiter 1. What the agent asked for against what the hold allowed:

| Trim hold clamps, 0.8.0 live | Count | Building_1, Building_3, Building_2 |
|---|---|---|
| `null` on a held trim, which the version 6 prompt said keeps it (hold zone 175, ease zone 75) | 250 | 168, 80, 2 |
| Ended the trim by sending the baseline, without `end_trim` (room still more than 0.5 C cold 37, in the ease zone 15) | 52 | 41, 11, 0 |
| Eased too fast (any easing in the hold zone 31, more than 0.02 an hour in the ease zone 7) | 38 | 29, 9, 0 |
| Asked for a trim where the hold had ended (room at or above its setpoint) | 5 | 5, 0, 0 |
| Deepened when it should hold | 0 | a deeper trim is always allowed |

- **Most clamps were bookkeeping.** In 250 cases the agent did what the prompt said (`null` keeps a held trim) and the envelope kept the trim and logged that as a clamp. In 208 hours those were the only clamps. The held depth was in every one of these observations (`cooling_trim_held`).
- 21 of the 32 comfort clamps were rounding under 0.002: the agent copied the 3 decimal baseline and landed a hair on the wrong side of it near a band edge.
- **98 percent were avoidable by seeing the constraint.** The month's own replies fitted into the ranges version 7 shows (`scripts/evaluate_fit.py`) leave 7 clamped hours with every KPI equal to four decimals. Six of the 7 are hours where the held trim is deeper than the baseline cooling: cooling 0 is the most any reply can give, and the hold still logs a clamp. The seventh is a peak limiter trim.

**Why ramping stayed above 1.0.** Points of `ramping_average` above 1.0 (`scripts/split_ramping.py`):

| Cause | 0.4.0 live (0.9965) | 0.8.0 live (1.0076) |
|---|---|---|
| Battery charging | +1.24 | +1.90 |
| Battery discharging | -1.59 | -2.01 |
| Cooling trims (start -2.03, end +2.74, depth +0.15 in 0.8.0) | 0.00 | +0.86 |
| Other (tank, extra cooling, rounding, outage hours) | 0.00 | +0.01 |

0.4.0 left comfort at the baseline, so it had no trims; the trims that bought 0.8.0's comfort are most of the rise, and charging added more than discharging took off. The live agent sent `strategy_battery` in 1,994 of 2,157 building hours. In the other 163 it mostly skipped a charge (70) or a peak-shaving discharge (34), or charged when the plan was idle (51). That is worth about 1.9 points: the same month with the battery plan followed exactly scores 0.9884. An envelope rule would not fix that (0.7.0 measured one: it raised ramping).

**Changes:**

- **Prompt version 7 (default).** Each building shows the envelope's view of this hour: `trim` (depth, state off, hold, ease or end, why, `min_depth` while a trim is held, `end_trim_ok`), `cooling_range` and `battery_range` (what passes without a clamp, rounded inward to 4 decimals), and `last_clamp` with its reason. `null` is now described as exactly the baseline, for use only when no trim is held; a held trim takes a number inside `cooling_range`. The ranges are worked out read only from the envelope's own state in its own rule order, and a randomized test holds that any value inside them passes `Envelope.apply` unclamped.
- **Battery guidance, searched on the tuning months.** `battery_plan_v7` can cap how fast a battery action rises and fill the load valley when grid charging. Of 36 settings none kept cost, emissions, discomfort and both peaks at version 6's battery plan while lowering ramping: every cap raised cost and the all-time peak, and capping only the discharge wind-down raised ramping (1.0016 against 0.9823), because it spends the charge the evening shave needs. So the shipped plan is version 5's, and the prompt targets the deviations instead: send `strategy_battery` as given, and when differing stay within 0.1 of it and never skip a peak-shaving discharge.
- **Version 6 stays selectable** (`--prompt-version 6`), so 0.8.0 runs replay byte for byte; the 0.8.0 live month replays 719 of 719 hours. `EnvelopeConfig` defaults are pinned field by field to 0.8.0 by a test.

**Estimates (no live calls; scripted columns are not model results).** Phase 2 month:

| CityLearn KPI (district) | 0.4.0 rule-based | 0.8.0 live | v6 scripted | v7 scripted | 0.8.0 live replies fitted to v7 | fitted, battery plan followed |
|---|---|---|---|---|---|---|
| cost_total | 0.9611 | 0.9190 | 0.9017 | 0.9016 | 0.9190 | 0.9182 |
| carbon_emissions_total | 0.9947 | 0.9610 | 0.9430 | 0.9429 | 0.9610 | 0.9603 |
| discomfort_proportion | 0.1714 | 0.0769 | 0.0430 | 0.0430 | 0.0769 | 0.0769 |
| ramping_average | 1.1309 | 1.0076 | 0.9957 | 0.9952 | 1.0076 | 0.9884 |
| daily_peak_average | 0.9978 | 0.9264 | 0.9078 | 0.9076 | 0.9264 | 0.9202 |
| all_time_peak_average | 1.0000 | 0.9593 | 0.9593 | 0.9588 | 0.9593 | 0.9585 |
| daily_one_minus_load_factor_average | 0.9913 | 0.9651 | 0.9640 | 0.9640 | 0.9651 | 0.9584 |
| Clamped hours | 1 | 312 | 139 | 22 | 7 | 7 |

On the tuning months (mean of three) the v7 scripted strategy scores cost 0.9086, emissions 0.9607, discomfort 0.0312, ramping 0.9823, daily peak 0.8837, all-time peak 0.8526 and load factor 0.9525 with 14.3 clamped hours a month, against v6's 0.9086, 0.9607, 0.0310, 0.9821, 0.8836, 0.8530, 0.9522 and 112.0. The rule-based controller there: 0.9621, 1.0021, 0.1231, 1.0838, 0.9804, 0.9794, 0.9831.

- If the agent keeps inside the ranges, clamps should fall from 312 hours to about 7 with nothing else changed. If it also sends `strategy_battery` every hour, ramping goes under 1.0 and cost, emissions, both peaks and load factor improve; unserved energy in outages rises slightly (0.6861 against 0.6850).
- **Only a live run can measure** whether Haiku keeps inside the ranges, sends a number for a held trim, and follows `strategy_battery` more closely under the new wording, and how the month then evolves, since fixed replies cannot react.

**Request size and cost.** A version 7 request averages 10,748 characters against 10,928 for version 6, 1.7 percent smaller (the system prompt is 441 characters shorter, the observation 231 longer). Scaled from the 0.8.0 live month, a Haiku month should cost about $0.53; the hard worst case is $0.98, under the $2.00 cap.

**Live results.** The 0.9.0 live run (`claude-haiku-5-5`, full month, 719 hours, prompt version 7, $2.00 budget, run 20261023T135430Z) against the baseline, the 0.4.0 rule-based controller (run 20261022T162847Z) and the 0.8.0 live month:

| CityLearn KPI (district), full month | Baseline | 0.4.0 rule-based | 0.8.0 live, Haiku | 0.9.0 live, Haiku |
|---|---|---|---|---|
| cost_total | 1.000 | 0.9611 | 0.9190 | **0.9245** |
| carbon_emissions_total | 1.000 | 0.9947 | 0.9610 | **0.9648** |
| electricity_consumption_total | 1.000 | 1.0073 | 0.9695 | **0.9744** |
| discomfort_proportion | 0.1714 | 0.1714 | 0.0769 | **0.0940** |
| too cool | 0.1538 | 0.1538 | 0.0601 | **0.0759** |
| too warm | 0.0176 | 0.0176 | 0.0168 | **0.0181** |
| daily_peak_average | 1.000 | 0.9978 | 0.9264 | **0.9182** |
| all_time_peak_average | 1.000 | 1.0000 | 0.9593 | **0.9412** |
| ramping_average | 1.000 | 1.1309 | 1.0076 | **0.9864** |
| daily_one_minus_load_factor_average | 1.000 | 0.9913 | 0.9651 | **0.9566** |
| one_minus_thermal_resilience_proportion | 0.3698 | 0.3698 | 0.3698 | **0.3698** |
| power_outage_normalized_unserved_energy_total | 0.6844 | 0.6844 | 0.6850 | **0.6844** |
| Clamped hours, fallback hours | | 1, 0 | 312, 0 | **27, 0** |
| Model cost | | none | $0.5315 | **$0.4607** |

- **Clamped hours fell from 312 to 27.** Version 7 shows the agent its allowed range each hour, and 250 of the 0.8.0 clamps were held trims the envelope logged as clamps, not the agent breaking a limit.
- **Ramping is under 1.0 for the first time since 0.4.0** (0.9864; 0.4.0 live: 0.9965).
- **It is the best live run so far on the daily peak and the all-time peak** (0.9182 against 0.8.0 live's 0.9264, and 0.9412 against 0.6.0 live's 0.9483). Load factor (0.9566) is second only to 0.4.0 live (0.9559), which left comfort at the baseline.
- **Against 0.8.0 live it gives back a little** cost (0.9245 against 0.9190), emissions (0.9648 against 0.9610) and comfort (0.0940 against 0.0769).
- **Against the 0.4.0 rule-based controller it beats or ties on every KPI except hot-side discomfort**, where it trails by 0.0005 (0.0181 against 0.0176). Unserved energy in outages now ties the baseline (0.6844).
- **Valley filling stays off by default.** On the tuning months it cut ramping further (0.9116 against 0.9823) but cost about 0.01 in cost (0.9181 against 0.9086).
- 0 fallbacks. The run cost $0.4607 of the $2.00 budget (719 calls) and replays 719 of 719 hours deterministically.

**The published viewer now shows the 0.9.0 live run** in place of 0.8.0 (the page's headline: cost down 7.5 percent, emissions down 3.5 percent).

### Version 0.10.0

**Goal:** find and close the gap between the 0.9.0 live agent (cost 0.9245, discomfort 0.0940) and the strategy it is given (scripted v7: 0.9016 and 0.0430), fix the hot-side comfort miss, and score everything on more than one month. The envelope is identical to 0.9.0. No live model calls were made for this release: everything here is measured on recorded runs and offline controllers, and the live months are still to run.

**Where the live agent left its strategy.** `scripts/analyze_deviations.py` compares every hour, building and device of the 0.9.0 live month with what the scripted version 7 strategy sends for the very observation the model saw (within 0.002 for cooling, 0.005 for storage), sorts each departure into one class, and then replays the month's own replies through the unchanged envelope with one class at a time put back to the strategy's action. The control replay reproduces the published KPIs exactly. Shares are of the control to strategy gap; the classes interact, so they need not add up.

| Class (building-hours, hours) | When | Replay: cost, emissions, discomfort, ramping, daily peak | Share of cost gap, discomfort gap |
|---|---|---|---|
| Live month (control) | | 0.9245, 0.9648, 0.0940, 0.9864, 0.9182 | |
| Scripted v7 strategy | | 0.9016, 0.9429, 0.0430, 0.9952, 0.9076 | 1, 1 |
| **No trim in an occupied, overcooled room** where the strategy trims, trim state off (584, 418) | all occupied; Building_1 353, Building_3 201, Building_2 30; room 0.5 to 1 C below setpoint 188, 1 to 1.5 C 147, more 249; low price 181, mid 166, flat 144, top 93; outdoor 30 C or more 272 | 0.8920, 0.9337, 0.0417, 1.0051, 0.9027 | 1.42, 1.03 |
| A deeper trim than the strategy's (100, 83) | Building_1 67, Building_3 33 | 0.9273, 0.9676, 0.0936, 0.9805, 0.9189 | -0.12, 0.01 |
| A trim where the strategy has none (19, 18) | 17 within 0.5 C of the setpoint | 0.9245, 0.9647, 0.0903, 0.9879, 0.9167 | 0.00, 0.07 |
| A shallower trim (11, 11) | Building_1 10 | 0.9243, 0.9646, 0.0940, 0.9876, 0.9182 | 0.01, 0.00 |
| Cooling above the strategy's (5, 5); a held trim ended early (3, 3) | | no change to four decimals | 0.00, 0.00 |
| Battery: over-discharged in a top-price hour (3, 1), charged off plan (3, 2), skipped a charge (1, 1) | | no change to four decimals on cost, emissions, discomfort | 0.00, 0.00 |
| Every class at once | | 0.8977, 0.9393, 0.0435, 0.9977, 0.9005 | 1.17, 0.99 |

- **One class is the whole gap.** The agent sent `strategy_battery` in 2,150 of 2,157 building-hours; the hot water tank was never used. What it did not do is start cooling trims: in 584 building-hours an occupied room was more than 0.5 C below its setpoint with no trim on, and it sent the baseline. Its reasons say why: "buildings 1 and 3 overcooled but trim off so baseline cooling kept". The version 7 prompt says `null` "is exactly baseline_action: use it only when trim state is off or end", and the agent read that as "send null when the trim is off". Putting that class back alone takes cost to 0.8920 and discomfort to 0.0417, past the strategy itself, though ramping rises to 1.0051 (trims add rises).
- **The agent's own deeper trims helped cost.** Putting the 100 deeper trims back to the strategy's depth raises cost to 0.9273 and lowers ramping to 0.9805. The battery classes change nothing measurable.

**The hot-side miss is one building-hour.** CityLearn's too-warm share is the mean of the three buildings' shares: Building_2 (22 of 535 occupied hours) and Building_3 (2 of 600) match the baseline exactly, and Building_1 has 7 of 712 against 6. The extra one is hour 404 (day 17, 9 pm): 28.77 C against a band top of 28.67 C, where the baseline's room was 28.54 C. On day 16 Building_1 trimmed cooling for most of 1 pm to 11 pm (hours 372 to 382) under a 27.2 C setpoint, at the 0.15 deviation cap from 2 pm to 8 pm (the agent deepened it in its second hour where the strategy keeps about 0.10, and the trim hold then held that depth), so the room ended the evening at 27.6 C against the baseline's 25.1 C and stayed about 1 C warmer overnight. A 15 hour outage on day 17 (6 am to 8 pm) then took cooling away from both runs, and the agent's room came out of it 0.23 C warmer and over the top of the band. The scripted version 7 strategy, whose trims stop at 0.10, has the same miss at the same hour. On the tuning months its 6 extra warm hours all come between 6 and 11 am, in a room that ran a trim within the day and a half before, 5 of them in Building_1 under its 27.2 C setpoint. A trim brings an overcooled room up to its setpoint, where the baseline keeps a cushion of about 2 C below it, and a hot morning or an outage then carries it over the band.

**Prompt version 8 (new default).** Each building shows the strategy's whole action for the hour, `strategy` (`cooling`, `dhw`, `battery`, worked out in code inside the envelope's ranges, with `strategy_reason`), in place of `strategy_battery`, and the agent is told to send it as given. The line about `null` and the trim state is gone: the prompt says a trim starts when an overcooled room's state is off and that a held trim is a number, never `null`. The strategy (`strategy_plan_v8`) is version 7's plus extra cooling in a room that runs warm: from 0 at 1.5 C above its setpoint to 0.05 above the baseline action at 2.5 C or more, never while a trim is held and never in an outage. `signal_outlook`, which no version 7 or 8 strategy reads, is dropped. Version 7 stays selectable, and the 0.9.0 and 0.8.0 live months replay 719 of 719 hours.

**The warm-room numbers were chosen on the tuning months** (`scripts/tune_strategy.py --version 8`, 36 settings): extra cooling at 0.5, 1 or 1.5 C above the setpoint, by 0.05, 0.1 or 0.15, at once or ramped over 1 C, and a no-trim night (18, 20 or 22 h until 5 or 7 h), alone and together. Comfort comes first: a setting qualified when its too-warm share was at or below the baseline's on every tuning month, its too-cool share within 0.001 of version 7's, and ramping and both peaks at or below the baseline's; the cheapest qualifying setting won. 5 of 36 qualified. On the tuning months the shipped setting scores cost 0.9105, emissions 0.9627, too cool 0.0112 and too warm 0.0040 against version 7's 0.9086, 0.9607, 0.0111 and 0.0201 (baseline too warm 0.0191). The night rule cleared no warm hour and raised cost by 0.007 to 0.024. A first rule that also held cost, emissions, ramping and both peaks within 0.001 of version 7 qualified none: the cheapest full fix costs about 0.002 of cost. The outage exception was added after the phase 2 month showed extra cooling in outage hours raising unserved energy (0.6942 against 0.6844); the tuning months have no outages, so it changes nothing there.

**Every month (`hyperbolic months`, offline, no model calls).** The phase 2 month and the three tuning months, each its own CityLearn episode:

| CityLearn KPI (district) | | phase 2 | tuning June | tuning July | tuning August | mean |
|---|---|---|---|---|---|---|
| cost_total | 0.4.0 rule-based | 0.9611 | 0.9506 | 0.9676 | 0.9682 | 0.9619 |
| | v7 scripted | 0.9016 | 0.9050 | 0.9186 | 0.9021 | 0.9068 |
| | v8 scripted | 0.9031 | 0.9099 | 0.9193 | 0.9023 | 0.9087 |
| carbon_emissions_total | 0.4.0 rule-based | 0.9947 | 1.0001 | 1.0038 | 1.0024 | 1.0002 |
| | v7 scripted | 0.9429 | 0.9603 | 0.9696 | 0.9521 | 0.9562 |
| | v8 scripted | 0.9447 | 0.9654 | 0.9703 | 0.9524 | 0.9582 |
| discomfort_proportion | baseline and rule-based | 0.1714 | 0.1128 | 0.0645 | 0.1919 | 0.1352 |
| | v7 scripted | 0.0430 | 0.0610 | 0.0093 | 0.0232 | 0.0341 |
| | v8 scripted | **0.0374** | **0.0174** | **0.0073** | **0.0210** | **0.0208** |
| too warm (discomfort_hot_proportion) | baseline and rule-based | 0.0176 | 0.0526 | 0.0031 | 0.0017 | 0.0188 |
| | v7 scripted | 0.0181 | 0.0545 | 0.0036 | 0.0022 | 0.0196 |
| | v8 scripted | **0.0116** | **0.0104** | **0.0016** | **0.0000** | **0.0059** |
| ramping_average | 0.4.0 rule-based | 1.1309 | 1.0742 | 1.0922 | 1.0848 | 1.0955 |
| | v7 scripted | 0.9952 | 0.9708 | 0.9666 | 1.0095 | 0.9855 |
| | v8 scripted | 0.9983 | 0.9732 | 0.9677 | 1.0100 | 0.9873 |
| daily_peak_average | 0.4.0 rule-based | 0.9978 | 0.9934 | 0.9743 | 0.9734 | 0.9847 |
| | v7 scripted | 0.9076 | 0.8806 | 0.8846 | 0.8858 | 0.8897 |
| | v8 scripted | 0.9095 | 0.8830 | 0.8854 | 0.8861 | 0.8910 |
| all_time_peak_average | 0.4.0 rule-based | 1.0000 | 1.0000 | 1.0000 | 0.9383 | 0.9846 |
| | v7 scripted | 0.9588 | 0.8518 | 0.8491 | 0.8570 | 0.8792 |
| | v8 scripted | 0.9588 | 0.8541 | 0.8491 | 0.8570 | 0.8797 |
| power_outage_normalized_unserved_energy_total | all four | 0.6844 | 0 | 0 | 0 | 0.1711 |
| Clamped hours | v7, v8 scripted | 22, 22 | 31, 32 | 9, 10 | 3, 3 | 16.2, 16.8 |

- **The scripted v8 strategy has fewer too-warm hours than the baseline on every month**, where v7 has more on every month, and less discomfort than v7 on every month. It pays for that with a little cost (0.9087 against 0.9068 on the mean) and emissions (0.9582 against 0.9562), and ramping and both peaks move by 0.0031 at most. On the phase 2 month, which played no part in choosing the numbers, too warm is 0.0116 against the baseline's 0.0176.
- The rule-based and v7 columns reproduce their published phase 2 and tuning-set numbers exactly. Ramping in tuning August is above 1.0 for both strategies.
- The scripted columns are not model results.

**Estimates for a live v8 month** (the 0.9.0 live replies, through the same envelope, with the v8 strategy filled in):

| | cost | emissions | discomfort (too cool, too warm) | ramping | daily peak | all-time peak | clamped hours |
|---|---|---|---|---|---|---|---|
| 0.9.0 live (control) | 0.9245 | 0.9648 | 0.0940 (0.0759, 0.0181) | 0.9864 | 0.9182 | 0.9412 | 27 |
| Trims started where the agent skipped them, nothing else changed | 0.8920 | 0.9337 | 0.0417 (0.0236, 0.0181) | 1.0051 | 0.9027 | 0.9412 | 68 |
| Every hour's cooling from `strategy`, the agent's own battery | 0.9031 | 0.9447 | 0.0374 (0.0258, 0.0116) | 0.9977 | 0.9098 | 0.9588 | 22 |
| Scripted v8 | 0.9031 | 0.9447 | 0.0374 (0.0258, 0.0116) | 0.9983 | 0.9095 | 0.9588 | 22 |

- If Haiku sends `strategy.cooling` as it sent `strategy_battery`, a live v8 month should land near the scripted v8 strategy: cost about 0.903, discomfort about 0.037 and too warm below the baseline. If it starts the trims but keeps its own deeper ones, cost could go lower (toward 0.892) with more ramping and the hot-side miss back. Following the strategy's cooling gives back the all-time peak the live agent's own cooling choices had won (0.9588 against 0.9412).
- **Only live runs can show** whether Haiku sends the strategy's cooling numbers as given, whether it keeps its battery discipline with the new wording, how far it goes its own way on trims, and how the rooms then evolve; and on the tuning months, how a live agent compares at all, since none has run there.

**Request size and cost.** A version 8 request averages 9,456 characters against 10,748 for version 7 over the same scripted month, 12.0 percent smaller: the system prompt is 3,645 characters against 4,780, the observation 153 shorter, and the reply schema unchanged. Scaled from the 0.9.0 live month (5,185 input and 245 output tokens per call, $0.4607), a Haiku month should cost about $0.42 ($0.4159 at the same reply length, $0.4379 if replies run 25 percent longer). The hard worst case is $0.95 for 719 hours and $0.98 for 743 hours, under the $2.00 cap. Live Haiku months on all four months of the set (2,924 hours) should cost about $1.69 to $1.78 in all, each month under its own $2.00 cap.

## What the agent sees

Prompt version 8 (`hyperbolic/prompt.py`) is the default from 0.10.0. It keeps everything in version 7 and:

- **Shows the strategy's whole action per building**, `strategy` with `cooling`, `dhw` and `battery` (from `strategy_plan_v8`, inside the envelope's ranges), and `strategy_reason`, in place of `strategy_battery` and `strategy_battery_reason`. The agent is told to send it as given and to say why where it differs.
- **Says a trim starts when an overcooled room's trim state is off**, and that a held trim is a number inside `cooling_range`, never `null`. The version 7 line that `null` is for "only when trim state is off or end" is gone: the 0.9.0 live month read it as "send null when the trim is off".
- **Adds extra cooling in a room that runs warm** to the strategy: from 0 at 1.5 C above its setpoint to 0.05 above the baseline action at 2.5 C or more, never while a trim is held and never in an outage.
- **Drops `signal_outlook`**, which no version 7 or 8 strategy reads, and names no single dataset, so the same prompt serves every month of the month set. Requests are 12.0 percent smaller than version 7's.

Prompt version 7, the default in 0.9.0, keeps everything in version 6 and:

- **Shows what the envelope allows each building this hour.** `trim`: the held trim's `depth`, its `state` (off, hold, ease or end) and why, `min_depth` (the least trim allowed this hour while one is held) and `end_trim_ok`. `cooling_range` and `battery_range`: the values that pass the range, rate, state of charge, deviation, comfort and trim hold rules without a clamp (`null` when only the exact baseline passes). The spread check and the peak limiter are still shown as `grid_charging_ok` and `headroom_kwh`.
- **Shows `last_clamp` per building**, last hour's clamps there with their reasons, in place of the district-wide `last_clamps`. `cooling_trim_held` and `cooling_trim_last_hour` are dropped.
- **Says `null` is exactly the baseline**, for use only when the trim state is off or end; a held trim takes a number inside `cooling_range`. In 0.8.0 `null` on a held trim was kept by the envelope and logged as a clamp.
- **Takes `strategy_battery` from `battery_plan_v7`**, which with the shipped numbers is version 5's plan, kept inside `battery_range`. The agent is told to send it as given, and when it differs to stay within 0.1 of it and never skip a peak-shaving discharge.
- **Is shorter.** The envelope's rules are summed up by the ranges, so the system prompt drops 441 characters.

Prompt version 6, the default in 0.8.0, keeps everything in version 5 and:

- **States the trim hold.** The envelope holds a cooling trim in code (see [How the safety envelope works](#how-the-safety-envelope-works)); `null` cooling keeps a held trim, and a deeper trim is allowed.
- **Adds `end_trim` to the reply**, per building: `null`, or a short reason to end that building's held trim now. It is the only way to end one early, and every early end is logged and shown in the viewer.
- **Adds `cooling_trim_held`** in each building: the trim the envelope keeps this hour, 0 when none.
- **Replaces `reference_action`** (the 0.4.0 rule-based controller's plan) with **`strategy_battery`** in each building and `strategy_battery_reason`: the battery action the version 5 strategy gives this hour, worked out by the same code the scripted strategy runs (`battery_plan_v5`). The agent is told to use it unless it has a clear reason, and to say why when it differs.

Prompt version 5, the default in 0.7.0, keeps everything in version 4 and adds:

- **`smoothing`**: `district_draw_last_hour_kwh` (measured), `district_load_now_kwh` (before storage) and `district_load_next_hour_kwh` (the next hour's load before storage, as yesterday).
- **`cooling_trim_last_hour`** in each building: how far below the baseline action its cooling ran last hour.
- **A smoothing strategy.** The goals now say that ramping counts only steps up. Once a trim is on, hold it until the room is within 0.5 C of its setpoint, then ease it off by at most 0.02 per hour. Start grid charging small and raise it by at most 0.15 per hour. Discharge the usable charge evenly over the top-price hours left. The numbers come from `StrategyParamsV5`, the settings chosen on the tuning set.

Prompt version 4, the default in 0.6.0, keeps everything in version 3 and adds:

- **`reference_action`** in each building, with `reference_reason`: what the 0.4.0 rule-based controller would do this hour (`rule_plan_v3`, the same function its runs use). The agent is told it is the bar to beat and that where its plan differs, a point of the strategy should say why.
- **`price_plan`**: the price now, the 24 hour top and low, `top_price_now`, the top-price hours ahead and `flat_24h`.
- **Battery limits**: `soc_floor` (CityLearn's depth of discharge leaves 0.2 here, above the envelope's 0.1), `usable_kwh` above it, `round_trip_min`, and `grid_charging_ok`, the envelope's spread check verdict for this hour.
- **`indoor_vs_setpoint_c`**, from the room temperature CityLearn actually simulated.
- **A strategy in priority order**: comfort (trim cooling gradually, up to 0.1 below the baseline, in occupied rooms more than 0.5 C below their setpoint; never cool less in a room at or above its setpoint), then hold the battery for the top-price hours and discharge there sized to each building's own load, discharging earlier only once district load reaches 0.9 of the forecast peak, charge about 0.15 of capacity per hour in the cheapest, cleanest hours so the battery is near 0.95 when the top-price hours start and only when `grid_charging_ok`, leave flat-price days alone, never charge at the top price, and leave the hot water tank at 0. The numbers come from `StrategyParams`, the settings chosen on the tuning set, so the prompt and the scripted strategy cannot drift apart.

Prompt version 3, the default in 0.4.0, keeps everything in version 2 and adds the peak block, the combined signal and hours left in the month (see [Version 0.4.0](#version-040)). Version 2, the default in 0.3.0:

- **A 24 hour price outlook from forecasts already received.** Each hour brings exact price forecasts for 6, 12 and 24 hours ahead. Kept and lined up by the hour they refer to, they cover every one of the next 24 hours after the first day. Hours not covered yet fall back to the same hour yesterday. Each value is tagged with its source.
- **A 24 hour carbon outlook** as the same hour yesterday, from observed values only. It is a guide, not a forecast.
- **A summary of both:** now, the 24 hour min and max, hours until each, and where now ranks in the coming day.
- **Storage per building:** state of charge, capacity and how far the battery can move in one hour, for the battery and the hot water tank.
- **A plain strategy:** charge the battery in the cheapest, cleanest hours and with spare solar, discharge into the price peak sized to the building's own load (exports earn nothing), mostly leave the hot water tank alone, keep cooling at the baseline unless a small pre-cool is clearly safe, and hold when nothing stands out.

Nothing reads the dataset ahead of time; the outlook is built only from observations the controller has already received. Prompt versions 1 to 7 are kept unchanged so runs recorded with 0.2.0 to 0.9.0 replay byte for byte, and `--prompt-version 1` to `7` still selects them: 1 to 5 with the 0.7.0 envelope rules, 6 and 7 with the 0.8.0 rules that version 8 also uses.

## Tuning without peeking at the test month

From 0.6.0 there is a separate 2023 tuning set. `scripts/tuning_data` holds `citylearn_challenge_2023_phase_2_online_evaluation_1` from CityLearn v3.0.2, copied unchanged: the same three buildings, batteries and LSTM models as the reported month, but June, July and August of a different period, with its own weather, loads, solar, carbon intensity and tariff, and no hour in common with the reported month. (`citylearn_challenge_2023_phase_1` is byte for byte the reported month's data, so it is no use for tuning; online evaluation sets 2 and 3 differ from set 1 only in the outage seed.)

In 0.10.0, `python scripts/tune_strategy.py --version 8` searched the version 8 strategy's extra cooling in a warm room (`StrategyParamsV8`) and a no-trim night, 36 settings with the 0.8.0 rules, with comfort first: too warm at or below the baseline on every tuning month, too cool within 0.001 of version 7's, ramping and both peaks at or below the baseline's, then the lowest cost plus emissions (see [Version 0.10.0](#version-0100)). The tuning months are now also part of the month set (`hyperbolic.months`, `hyperbolic months`), which the search and the compare report share; the phase 2 month is still only reported, never searched.

In 0.9.0, `python scripts/tune_strategy.py --version 7` searched the version 7 battery plan's smoothing (`StrategyParamsV7`): a soft cap on how fast a battery action may rise (0.05 to 0.25, on charging and discharging or on a discharge winding down only), valley filling when grid charging, and a charge rate of 0.1 or 0.15, 36 settings with the 0.8.0 rules. Every candidate runs the same cooling, so the reference is the candidate with version 6's battery plan, and a setting qualified when ramping was lower with cost, emissions, discomfort and both peaks no worse. None did. Every cap raised cost and the all-time peak (a cap of 0.1: cost 0.9138 against 0.9086, all-time peak 0.8835 against 0.8526, ramping 0.9965 against 0.9823), and capping only the wind-down of a discharge raised ramping (1.0016). Charging at 0.1 cut ramping to 0.9644 and valley filling to as low as 0.9116, but both raised cost and the all-time peak. The shipped numbers are version 5's.

In 0.8.0 nothing was tuned. The trim hold takes its numbers from the version 5 strategy (hold until within 0.5 C, then ease by at most 0.02 per hour), and `python scripts/tune_strategy.py --version 6` runs the shipped version 5 strategy on the tuning months through the 0.7.0 rules and through the 0.8.0 rules, before anything is reported on the phase 2 month. The one choice made there was the hold's rounding allowance (see [Version 0.8.0](#version-080)).

In 0.7.0, `python scripts/tune_strategy.py` (version 5, the default) searched how `strategy_plan_v5` smooths the load: how long a cooling trim is held, how fast it is eased off and how fast a grid charge may rise (`StrategyParamsV5`). A setting qualified when, averaged over the three tuning months, ramping was below the baseline and cost, emissions, discomfort and both peaks were no worse than the 0.6.0 strategy on the same months; the qualifying setting with the lowest ramping plus load factor won. 8 of 18 qualified. On the tuning months the shipped setting scores ramping 0.9816 and load factor 0.9517 against the 0.6.0 strategy's 0.9953 and 0.9529, with cost 0.9089 against 0.9113, emissions 0.9610 against 0.9671 and discomfort 0.0310 against 0.0344.

In 0.6.0, `python scripts/tune_strategy.py --version 4` ran each of its three months as its own episode and searched the version 4 strategy's numbers (`StrategyParams`: when a room counts as too cold and how far its cooling is trimmed, the charge rate, peak shaving, and whether discharge is spread over the top-price hours), executed literally by `strategy_plan_v4`. A setting qualifies when, averaged over the three months, discomfort is at or below the baseline's, the daily and all-time peaks, ramping and the daily load factor are at or below the baseline's to four decimals, and cost and emissions are both below the 0.4.0 rule-based controller's on the same months. 36 of 216 settings qualified; the one with the lowest cost plus emissions is shipped. On the tuning months it scored cost 0.9113 and emissions 0.9671 against the rule-based controller's 0.9621 and 1.0021, discomfort 0.0344 against 0.1231, daily peak 0.8900, ramping 0.9953 and load factor 0.9529. The reported month was used only to report. The envelope's spread check has nothing to tune: it uses each battery's own efficiency curve and standing loss.

Before 0.6.0 the repository had no other 2023 dataset offline, and the rule-based policy's settings were chosen on the first week of the reported month only (167 hourly decisions) with `python scripts/tune_rules.py`. That controller is now the frozen 0.4.0 reference and keeps those settings. In 0.4.0 its grid covered the signal thresholds for charging and discharging, the charge rate, peak shaving, the battery charge limits, when to stop charging before the month ends, and the limiter's target fraction and forecast window; a setting qualified when, on that week, discomfort was no more than half a point above the baseline and both peaks were at or below the baseline's to four decimals. (Four decimals because the baseline action under control rounds the heat pump fraction, which by itself moves a peak ratio by about 0.00001.)

## How the safety envelope works

`hyperbolic/envelope.py`. Every reply goes through these steps before CityLearn sees anything:

1. **Schema validation.** One JSON object, strict Pydantic model: a short reason plus `cooling`, `dhw` and `battery` for every building. Each value is a finite number or `null`. Extra or missing fields, strings, booleans, NaN and infinity are rejected. From prompt version 6 each building may also carry `end_trim`, `null` or a reason of 1 to 300 characters.
2. **Action range.** The configured range intersected with CityLearn's own action space.
3. **Rate limit.** At most 0.35 per hour for cooling and 0.5 for the tank and battery, measured from last hour's action or from this hour's baseline action, whichever is closer. Returning to the baseline is never too fast.
4. **State of charge.** No charge or discharge that would take a battery or tank outside 10 to 95 percent.
5. **Price spread (new in 0.6.0).** No grid charging of a battery when no price in the next 24 hours, after the battery's worst round trip efficiency and its standing loss until then, is worth more than the price now, while a cheaper hour is coming. Spare solar the building would otherwise export may still be stored. A flat outlook does not block, since the next peak may lie beyond the forecast.
6. **Cooling deviation (new in 0.3.0).** Cooling may not move more than 0.15 from the baseline action, the fraction that meets the ideal load. Enough to pre-cool, not enough to switch the heat pump off.
7. **Comfort.** In occupied hours within 0.5 C of the comfort band edge, cooling may not drop below the baseline when warm or rise above it when cool. From 0.3.0, an unoccupied building already near the bottom of its band gets no extra cooling either.
8. **Trim hold (new in 0.8.0).** Per building the envelope keeps whether a cooling trim is on (cooling more than 0.002 below the baseline action) and how deep it is. While the room is occupied and more than 0.5 C below its setpoint, the trim stays at least as deep as last hour; within 0.5 C it eases off by at most 0.02 per hour; it ends at once at or above the setpoint, when the room is unoccupied, or when the baseline has no cooling to trim, and no trim may start there. `null` keeps a held trim, a deeper one is allowed, and a miss of less than 0.002 counts as rounding (the full depth stays held). The model can end a trim early only through `end_trim` with a reason. Every hold action is recorded with its reason in the hour's `holds`, and every value it changes is a clamp with rule `trim_hold`. It runs after the comfort rule and only keeps cooling below the baseline, within the deviation limit the trim already passed. It is not a ramp limit: it does not taper rises, it keeps a trim on.
9. **Peak limit (new in 0.4.0).** Across the district, battery charging and then tank charging are trimmed so the district's estimated draw this hour stays at or below the peak target (the higher of today's peak so far and the forecast of today's peak). Discharging and cooling are never touched by it, and discharging earns no credit in the estimate, so it never understates the load.

0.10.0 changes none of these rules either; a test still pins every `EnvelopeConfig` field to its 0.8.0 value. 0.9.0 changed none of them. Prompt version 7 shows the agent, per building, the cooling and battery values that pass steps 2 to 8 without a clamp, worked out read only from the envelope's own state (`prompt.cooling_range`, `battery_range`, `trim_view`). One thing it makes visible: `null` on a held trim is kept by step 8 and still logged as a `trim_hold` clamp, and where a held trim is deeper than the baseline cooling, cooling 0 is held and logged as a clamp whatever the reply.

Older runs replay with the rule set they were recorded with: the run's manifest stores the envelope settings, and settings missing from an old manifest take the values they had before they existed (no deviation cap or unoccupied guard before 0.3.0, no peak limit before 0.4.0, no spread check before 0.6.0, no trim hold before 0.8.0). The rule-based reference controller runs with the 0.4.0 rules, without the spread check, so its result stays comparable. New runs on prompt versions before 6 run with the 0.7.0 rules (`EnvelopeConfig.v070()`), without the trim hold, because those prompts do not describe it.

From 0.6.0 the comfort rule acts on the room temperature CityLearn simulated for the hour just finished. Before, it saw the dataset's no-control value for the coming hour (see [Version 0.6.0](#version-060)).

`null` keeps the baseline action for that device. An invalid reply, a timeout, a refusal, a truncated reply or a client error falls back to the baseline action everywhere for that hour. Every clamp and every fallback is logged with the requested value, the applied value and the reason, and both are highlighted in the viewer.

The baseline action under active control is storage idle and the heat pump at the fraction of nominal power that delivers the ideal cooling load. A test checks that running those actions every hour reproduces CityLearn's no-control KPIs (1.000 to six decimals, identical discomfort), so a fallback hour is a no-control hour.

## Model access and budget

- Key from `HYPERBOLIC_ANTHROPIC_KEY`, falling back to `TRIAGE_ANTHROPIC_KEY`. The key lives only in the environment, never in a file, log or run folder (a test checks this).
- Model: `--model haiku` (default, `claude-haiku-5-5`) or `--model sonnet` (`claude-sonnet-5-5`). Structured JSON output, low effort, 2000 max tokens.
- Hard budget per run, `--budget` (default 2.00 USD). Before every call the runner computes that call's worst case (prompt size plus full max tokens). If it could push spending past the budget, model calls stop for the rest of the run and every remaining hour uses the baseline action.
- Episode length: the full 719 hours. The 0.2.0 live run averaged about 4,700 characters per request and cost 0.23 USD on Haiku. Prompt version 2 adds the 24 hour outlook and the strategy, about 7,400 characters per request, and the 0.3.0 live Haiku month cost 0.39 USD. Prompt version 3 is about 8,600 characters per request; the 0.4.0 live Haiku month cost 0.47 USD, against a hard worst case of about 0.93 USD. Prompt version 4 adds the reference action, the price plan and the battery limits, about 9,650 characters per request: the 0.6.0 live Haiku month cost 0.57 USD, against a hard worst case of about 0.95 USD. Prompt version 5 adds the smoothing view, about 10,430 characters per request: the 0.7.0 live Haiku month cost 0.63 USD, against a hard worst case of about 0.97 USD and the default 2.00 USD budget. Prompt version 6 adds the trim hold and `end_trim`, about 10,930 characters per request (4.8 percent more): the 0.8.0 live Haiku month cost 0.53 USD (5,245 input and 429 output tokens per call), against a hard worst case of about 0.99 USD. Prompt version 7 shows the envelope's ranges and is 1.7 percent smaller, about 10,750 characters: the 0.9.0 live Haiku month cost 0.46 USD (5,185 input and 245 output tokens per call). Prompt version 8 shows the strategy's whole action and is 12.0 percent smaller again, about 9,460 characters: a Haiku month should cost about 0.42 USD, against a hard worst case of about 0.95 USD (0.98 USD for a 743 hour tuning month). Sonnet costs 20 times as much per token: a full Sonnet month should cost roughly 11 to 13 USD, so under a 2.00 USD budget it stops calling the model after about a sixth of the month and the remaining hours use the baseline action. Raise `--budget` (about 14 USD) for a full Sonnet run. Each run logs its exact token cost in `result.json`.

## How to run it

Python 3.10, 3.11 or 3.12 (CityLearn 3.0.2 needs numpy below 2, which has no Python 3.13 wheels).

CityLearn is installed with `--no-deps`. Its published pins (scikit-learn 1.2.2, openstudio, torchvision, doe_xstock) are only needed by optional features and would force a source build on Python 3.12. Hyperbolic's own dependencies are the packages CityLearn's simulation core imports.

### Windows (PowerShell, with a virtual environment)

```powershell
cd C:\path\to\Hyperbolic
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install --no-deps CityLearn==3.0.2
.\.venv\Scripts\python -m pip install -e ".[dev]"
.\.venv\Scripts\python -m pytest -q

.\.venv\Scripts\python -m hyperbolic run --scripted --hours 24   # 24 hour dry run of the rule-based controller, no API calls
.\.venv\Scripts\python -m hyperbolic run --model haiku --budget 2.00   # key from HYPERBOLIC_ANTHROPIC_KEY or TRIAGE_ANTHROPIC_KEY
.\.venv\Scripts\python -m hyperbolic compare     # KPI table, rebuilds docs\data\viewer.json and viewer.js
```

### macOS or Linux

```bash
python -m pip install --no-deps CityLearn==3.0.2
python -m pip install -e ".[dev]"
export HYPERBOLIC_ANTHROPIC_KEY="your key"
python -m hyperbolic run && python -m hyperbolic compare
```

### Commands

| Command | What it does |
|---|---|
| `hyperbolic baseline` | Runs CityLearn's no-control reference. `--month` as for `run`. |
| `hyperbolic run` | Runs the supervisor through the envelope. `--model sonnet`, `--budget 5`, `--hours 24` for a short run, `--month tuning-06`, `tuning-07` or `tuning-08` for a month of the tuning set instead of the phase 2 month (`phase2`, the default), `--scripted` for the 0.4.0 rule-based controller with no API calls (prompt version 3 and the 0.4.0 envelope), `--scripted --prompt-version 4` or `5` for the version 4 or 5 strategy executed literally, `--scripted --prompt-version 6` for the version 5 strategy with the 0.8.0 trim hold, `--scripted --prompt-version 7` or `8` for the version 7 or 8 strategy kept inside the envelope's ranges, `--inject-faults` with `--scripted` to exercise clamps and fallback, `--prompt-version 1` to `7` for the 0.2.0, 0.3.0, 0.4.0, 0.6.0, 0.7.0, 0.8.0 or 0.9.0 prompt. Runs of two days or more need hours + 1 to be a whole number of days (for example 167 or 719), a limit of CityLearn 3.0.2's outage model. |
| `hyperbolic months` | Runs the baseline, the 0.4.0 rule-based controller and the scripted v7 and v8 strategies on every month of the month set (the phase 2 month and the three tuning months), in parallel with no model calls, and prints each KPI per month and the mean. `--controllers`, `--months`, `--run RUN` (repeatable) to show a finished run at the month it was recorded on, `--out` for JSON. |
| `hyperbolic replay RUN_DIR` | Re-runs a saved run from its files with zero model or simulator calls and reports whether every decision and action matches. Exit code 1 if not. |
| `hyperbolic compare` | Pairs the latest baseline (from `runs/` or the committed `results/`) with the latest agent run (a live run wins over a scripted one), prints the KPIs and writes the viewer data. `--pair BASELINE AGENT` to choose, `--out` to write the viewer data elsewhere, `--against RUN` (repeatable) to print another finished run of the same length beside them, for example the rule-based controller; the viewer data is unchanged. |
| `hyperbolic serve` | Live mode in the browser on 127.0.0.1 (see [Watch it live](#watch-it-live)). `--port 8765`, `--no-browser`. |

`python -m hyperbolic` works the same as `hyperbolic`. A full episode simulates in about 7 seconds; a live run takes as long as 719 model calls.

## Watch it live

```powershell
.\.venv\Scripts\python -m hyperbolic serve
```

That starts a small local server at http://127.0.0.1:8765 and opens it in your browser. Pick a duration (24 hours, 1 week, the full month or a custom hour count), a controller (`claude-haiku-5-5`, `claude-sonnet-5-5`, the rule-based controller or the baseline) and a budget. The page shows an estimated cost from your recorded runs before you press Start. Each hour then lands on the same viewer as it finishes: building tiles, running KPIs against the baseline over the same hours, the agent's reason for every hour in a scrolling log, clamps glowing, district draw against the peak target, and the API spend against the budget. Pause, Resume and Stop work between hours, and one run goes at a time.

- **Local only.** The server binds 127.0.0.1, answers only requests addressed to 127.0.0.1 or localhost, and refuses cross-site requests that would start or stop a run. It is built on Python's standard library (`http.server` and Server-Sent Events), so it adds no dependency.
- **The key stays on the server.** It is read from `TRIAGE_ANTHROPIC_KEY` (or `HYPERBOLIC_ANTHROPIC_KEY`) and never sent to the page, the logs or the run files. Without a key the Claude options are off, and the rule-based and baseline controllers still work.
- **The budget is enforced on the server**, exactly as `hyperbolic run` does: model calls stop at the cap and the remaining hours keep the baseline action.
- **Every live run is recorded** in `runs/` in the same format as `hyperbolic run`, so `hyperbolic replay` reproduces it. A stopped run is saved as partial and scored against a baseline over the same hours.
- **Publish** writes `docs/data` exactly like `hyperbolic compare --pair`, on your disk only. Nothing is committed or pushed.

Options: `--port`, `--runs-dir`, `--docs`, `--no-browser`. Live mode only exists when the page is served by `hyperbolic serve`; the published GitHub Pages replay is unchanged.

## The replay viewer

`docs/` is a static site with no build step: D3 from cdnjs, two Google Fonts, and the data in `docs/data/viewer.js` (the same content as `viewer.json`, as a script so the page also opens straight from disk).

- The headline result, stated as plainly when the agent loses.
- The district for the reference and for the agent side by side: each building as a tile with indoor temperature against its comfort band, battery and hot water tank charge, and grid draw, glowing when the envelope clamps or falls back.
- A timeline with the electricity price along the top, envelope events marked, play and pause, 1x, 10x and 60x speed, and jumps between events.
- Running cost, emissions and discomfort counters for both sides.
- Indoor temperature, district grid draw and battery charge in a rolling window that follows the playhead.
- The agent's one-line reason for every hour, with clamped and fallback hours tagged, each clamp spelled out, and any cooling trim the agent ended early shown with its reason.
- The CityLearn KPI scorecard, run cost, call count and clamp and fallback counts.
- A compact "How it works" strip under the headline (the agent decides, the safety envelope checks, CityLearn simulates, CityLearn scores) and a "Run it yourself" section with the local commands, including `hyperbolic serve`.

Dark by default with a light toggle, built for phones first, and it respects reduced motion. To publish it, turn on GitHub Pages: Settings, Pages, Deploy from a branch, `main`, folder `/docs`.

## Tests

`python -m pytest -q` runs fully offline. Envelope rules and runner logic run against a small fake district for speed; the backend, the CLI and the no-control equivalence run against real CityLearn on the shipped dataset; replay and the viewer builder run against CityLearn runs recorded in `tests/fixtures`. Covered: live mode through the real server with fake models (a full run streamed, recorded and replayed identically, the streamed hours matching the replay viewer's data, pause and resume, stop saving a partial run, the budget cap, the key never appearing in any response or file, the 127.0.0.1 binding and host checks, and the Claude options off without a key), the peak limiter (never above the target in randomized trials, trims recorded as clamps, battery before tank, off for older runs, and a CityLearn run that replays identically with its trims), the combined signal, the peak tracker, the reason length guard, the forecast horizons (6, 12 and 24 hours, the 0.2.0 mislabel), the 24 hour outlook never using unseen data, all eight prompt versions, `EnvelopeConfig` pinned field by field to 0.8.0 and the 0.8.0 and 0.9.0 live months replaying 719 of 719 hours when they are on disk, the deviation classes (every cooling, battery and tank class, the strategy's own reply having none, the tolerance, when each happened), the attribution replays (only the listed points replaced, the control reproducing a recorded CityLearn run exactly, a class put back moving the month toward the strategy, the gap shares), the version 8 observation (the strategy's whole action per building inside the ranges, the dropped fields), the version 8 prompt wording and request size, the warm-room cooling (the ramp, none in an outage, an empty room or with a trim held), the version 8 strategy equal to version 7's without a warm room, the night rule off, the scripted version 8 reply, version 8 runs on the fake district and 24 hours of CityLearn that replay identically, a full version 8 CityLearn month below the baseline's too-warm share, the version 8 search grid and rule, the month set (its months and lengths, a tuning month written as its own dataset, `run --month` recording its month and replaying, the rule-based controller reproducing its tuning month) and the compare report (means only over every month, partial runs marked), the version 7 observation (every trim state with `min_depth` and `end_trim_ok`, both ranges, `last_clamp`, the dropped fields), any value inside the version 7 ranges passing the envelope unclamped in randomized trials, a held trim left to `null` being clamped while the top of its range is not, the version 7 battery plan (version 5's with the shipped numbers, the soft cap winding a discharge down and leaving spare solar alone, valley filling), the version 7 prompt wording and request size, the scripted version 7 reply, version 7 runs on the fake district and 24 hours of CityLearn that replay identically and a full version 7 CityLearn month, the fitting evaluation and the version 7 search grid, the trim hold (on, hold, ease, release, end at the setpoint, in an empty room and with no baseline cooling, early end with a reason, the rounding allowance, logging, fallback, the deviation and comfort rules still first, off for older runs, and runs that replay byte for byte and detect changed hold settings), the version 6 prompt, observation, `end_trim` schema and request size, the scripted version 6 reply following `strategy_battery`, the viewer showing early ends, a 24 hour version 6 CityLearn run that replays identically and a full version 6 CityLearn month, the exact ramping split and the evaluation control reproducing a recorded CityLearn run, the version 4 reference action equal to what the rule-based controller replies, the version 5 smoothing view and strategy (trim hold, slow release, release at the setpoint, gentle charge start, even discharge), a full version 5 CityLearn month with ramping below the baseline, version 5 runs that replay byte for byte and detect a changed observation, the public page's How it works and Run it yourself sections, the spread check (blocked at the top price with its reason, allowed when the coming peak pays, never blocked by a flat weekend, standing losses, spare solar, off for older runs and the rule-based reference), the indoor temperature being the one CityLearn simulated, 24 hour and full-month rule-based dry runs on CityLearn (the full month must still score the 0.4.0 cost, emissions, daily peak, ramping and load factor), a 24 hour version 4 run on CityLearn that replays identically, recorded version 4 runs that replay byte for byte and detect a changed reference policy, a cooling offset moving indoor temperatures, every envelope rule, malformed and schema-breaking replies, fallback on invalid, missing and refused replies, the budget stop, key handling, deterministic replay and tamper detection, replay with CityLearn not even importable, and byte-identical viewer data from the same files in one process or two.

CI (GitHub Actions) runs the tests on Python 3.10 and 3.12 with CPU-only torch, a repository rules check, and an author check that fails if any commit in a push or pull request was not authored by AddisonTech.

## Honest limits

- **Simulator only.** CityLearn models buildings with data-driven load profiles and an LSTM for indoor temperature. Beating its reference is evidence worth investigating, not proof of field savings.
- **The rule-based check is not a model result.** It shows the action path can beat the reference and sets the bar for the agent. In 0.3.0 the live agent beat the baseline on cost only and did not beat the rule-based check. In 0.4.0 it beat the rule-based check on daily peak, ramping and load factor but not on cost or emissions. In 0.6.0 it beat it on every one of those. In 0.8.0 it beat it on every KPI except unserved energy in outages, by 0.0006. In 0.9.0 it beat or tied it on every KPI except hot-side discomfort, by 0.0005. From 0.6.0 the rule-based check is frozen at its 0.4.0 settings so the bar does not move.
- **The scripted version 4 and 5 strategies are not model results either.** They show that the strategy the agent is given beats the rule-based controller when followed literally. A live model reads the same strategy and may follow it more or less closely.
- **The peak limiter uses this hour's load.** It reads the draw CityLearn is about to simulate for this hour (plug load, solar, hot water demand, cooling), the equivalent of a meter reading in a real building. The forecast of the day's peak is built only from past days. The agent itself sees only the same values the limiter uses, never the rest of the day.
- **Ramping is a sum of rises, against CityLearn's own reference.** Smoothing that only spreads a rise over more hours does not lower it, which is why the trims are held rather than tapered. The denominator is built inside each run, so an agent's actions in an outage hour can move it (see [Version 0.8.0](#version-080)). The remaining up-ramp is mostly the baseline's own evening rise and the end of the top-price discharge.
- **The live agent does not carry a plan from hour to hour.** Each hour is a separate call. In 0.7.0 it was asked to hold cooling trims across hours and broke that in 142 of 237 trim ends (the scripted strategy: 4 of 167). From 0.8.0 the envelope holds them in code, and in the 0.8.0 live month it clamped the agent's cooling 345 times in 292 of 719 hours, 250 of them on `null` replies the prompt said would keep the trim. Version 7 shows the allowed range instead. In the 0.9.0 live month the agent sent `strategy_battery` in 2,150 of 2,157 building-hours but started almost none of the trims the strategy calls for, so version 8 shows the cooling as a number too. Its battery use is still the agent's own: in 0.7.0 that, not the trims, is what raised ramping above 0.6.0.
- **The 0.8.0 estimates were not live results.** The 0.7.0 replies sent through the 0.8.0 rules are fixed, so they cannot react to what the hold changed, and they do not include the version 6 prompt. The live month came in lower on ramping than that estimate (1.0076 against 1.0249); this release does not split how much of that is the hold and how much the prompt.
- **The 0.10.0 estimates are not live results.** They fill the version 8 strategy into the 0.9.0 live replies, which were written for the version 7 prompt and cannot react to what changed. The month set's scripted columns are not model results either, and no live run has been made on a tuning month yet.
- **The warm-room cooling rests on CityLearn's LSTM.** It answers a mechanism seen in the simulator: a trimmed room loses the baseline's cushion and a hot morning or an outage carries it over the band. On the tuning months it removed 80 percent of the strategy's too-warm hours for about 0.002 of cost.
- **The 0.9.0 estimates are not live results.** They fit the 0.8.0 live replies into the version 7 ranges and, in one column, swap in `strategy_battery`. They assume a model that obeys the ranges and the battery plan, and fixed replies cannot react to what changed. Whether Haiku does that under the version 7 wording can only be measured live.
- **Tuned on one other dataset.** From 0.6.0 the strategy's numbers come from three summer months of the CityLearn 2023 online evaluation set: other weather, loads, carbon and tariff, but the same three buildings and LSTM models, so it says nothing about other building types. The 0.4.0 rule-based controller still carries settings chosen on the first week of the reported month.
- **The reference is a modest bar.** No storage use and an ideal-load heat pump. Any sensible battery and tank schedule should beat it on cost. The interesting questions are emissions, peaks and comfort at the same time.
- **The comfort reference is not perfect.** CityLearn's own no-control run already leaves 17 percent of occupied hours outside the band, mostly too cool: CityLearn's LSTM runs the rooms colder than the ideal load data assumes. Trimming cooling in those rooms is the largest single gain in 0.6.0, and it rests on that model.
- **Hourly supervision only.** One decision per hour, three devices per building.
- **The envelope is conservative by design.** It caps ramps and charge levels and protects comfort near the band edges, which also limits how hard any controller can push.
- **Model output varies.** Live runs are not reproducible from scratch. They are reproducible from their recorded files, which is what replay is for.

## Credits and license

MIT, see `LICENSE`.

CityLearn is developed by the Intelligent Environments Laboratory and contributors and is distributed under the MIT license. The dataset in `hyperbolic/data/citylearn_challenge_2023_phase_2_local_evaluation` is copied unchanged from the CityLearn repository (tag v3.0.2); its license is in `hyperbolic/data/CITYLEARN_LICENSE.txt`. The tuning dataset in `scripts/tuning_data/citylearn_challenge_2023_phase_2_online_evaluation_1` is copied unchanged from the same repository and tag, under the same license. Hyperbolic is not affiliated with the CityLearn project.
