# Hyperbolic

**A month of building ops in an hour.**

An AI supervisor that runs a simulated district and tries to beat the no-control reference on cost, emissions and comfort.

Hyperbolic runs [CityLearn](https://github.com/citylearn-project/CityLearn), an open source district energy simulator, entirely on one machine. Every simulated hour it reads CityLearn's observations, forecasts and prices for all buildings, asks a language model for one action per device, passes the answer through a deterministic safety envelope, and applies what survives. Both the agent and the reference are scored by CityLearn's own KPI evaluation, so the numbers come from the benchmark, not from this project.

Replay viewer and scorecard: `docs/index.html`, published with GitHub Pages. Both sides shown there are real CityLearn runs: the no-control baseline and the live 0.10.0 Haiku run on the phase 2 month (see [Version 0.10.0](#version-0100)). It replaces the 0.9.0 live run there; the phase 2 month stays the published one so the page stays comparable with earlier releases. The 0.7.0 live run scored worse and was never published (see [Version 0.7.0](#version-070)).

The final result on buildings nothing was tuned on is in [Holdout results](#holdout-results): over three months the live agent beats the baseline and the rule-based controller on every KPI, and stays within 0.0006 of its own scripted strategy, slightly behind it on mean cost, emissions and the all-time peak.

0.13.0 tried a free mode, where the model may depart from the strategy with a stated hypothesis. On the one month tested it found no savings: see [Version 0.13.0](#version-0130-free-mode).

0.14.0 ran blind mode, where the model sees no strategy at all. On the same month Sonnet did not find the rules on its own: it was behind the strategy on every KPI. See [Version 0.14.0](#version-0140-blind-mode).

0.15.0 gave Haiku the strategy's rules in words, with no action worked out for it. On the same month that closed 89 percent of the cost gap between no rules and rules computed in code; the rest, and most of the ramping gain, needed the computation. See [Version 0.15.0](#version-0150-rules-in-words).

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

## Holdout results

**The one final scoring of the sealed holdout** ([HOLDOUT.md](HOLDOUT.md)): Buildings 4, 5 and 6 of `citylearn_challenge_2023_phase_3_1`, June (719 hours), July (743) and August (743), each its own episode. No strategy setting or prompt was shaped on these buildings; their weather, tariff and carbon intensity are the tuning months'. Prompt version 9 and the 0.11.0 envelope ran exactly as shipped, with `claude-haiku-5-5` and a $2.00 budget per month. The seal check passed before scoring: all 16 holdout files match the sha256 hashes in HOLDOUT.md and there is no extra file. Everything below comes from `hyperbolic months --holdout-final`.

**When the live months ran.** Each holdout month was run live once, on 2026-10-23 between 17:22 and 19:11 EDT, a few hours after the 0.11.0 commits. It was scored that evening and is published only now, in 0.12.0. The 0.11.0 notes that say only the baseline had been run on the holdout were true when they were written. No holdout month has been run live a second time, and 0.12.0 makes no model calls. The only code change since those runs is prompt caching, which sends the same system prompt text as a cached block and was off for them. The strategy, the prompt text and the envelope are unchanged. Every live month replays all its hours (719, 743 and 743) with 0 API calls, every rebuilt request matching the recorded request's sha256, and the replayed KPIs equal the recorded ones. The baseline, rule-based and v9 scripted rows below equal the ones scored on 2026-10-23 to six decimals.

| CityLearn KPI (district) | | holdout June | holdout July | holdout August | mean of three |
|---|---|---|---|---|---|
| cost_total | baseline | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
|  | 0.4.0 rule-based | 0.9689 | 0.9728 | 0.9776 | 0.9731 |
|  | v9 scripted | 0.9203 | 0.9215 | 0.9270 | 0.9229 |
|  | **Haiku v9** | **0.9205** | **0.9215** | **0.9271** | **0.9231** |
| carbon_emissions_total | baseline | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
|  | 0.4.0 rule-based | 0.9974 | 0.9986 | 0.9993 | 0.9984 |
|  | v9 scripted | 0.9540 | 0.9551 | 0.9536 | 0.9542 |
|  | **Haiku v9** | **0.9543** | **0.9551** | **0.9538** | **0.9544** |
| electricity_consumption_total | baseline | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
|  | 0.4.0 rule-based | 1.0019 | 1.0003 | 1.0022 | 1.0015 |
|  | v9 scripted | 0.9571 | 0.9562 | 0.9554 | 0.9562 |
|  | **Haiku v9** | **0.9573** | **0.9562** | **0.9556** | **0.9564** |
| discomfort_proportion | baseline | 0.1821 | 0.1024 | 0.1038 | 0.1294 |
|  | 0.4.0 rule-based | 0.1826 | 0.1024 | 0.1038 | 0.1296 |
|  | v9 scripted | 0.0427 | 0.0192 | 0.0219 | 0.0279 |
|  | **Haiku v9** | **0.0427** | **0.0192** | **0.0219** | **0.0279** |
| too cool (discomfort_cold_proportion) | baseline | 0.1392 | 0.1007 | 0.1009 | 0.1136 |
|  | 0.4.0 rule-based | 0.1397 | 0.1007 | 0.1009 | 0.1138 |
|  | v9 scripted | 0.0411 | 0.0192 | 0.0214 | 0.0273 |
|  | **Haiku v9** | **0.0411** | **0.0192** | **0.0214** | **0.0273** |
| too warm (discomfort_hot_proportion) | baseline | 0.0429 | 0.0017 | 0.0028 | 0.0158 |
|  | 0.4.0 rule-based | 0.0429 | 0.0017 | 0.0028 | 0.0158 |
|  | v9 scripted | 0.0015 | 0.0000 | 0.0005 | 0.0007 |
|  | **Haiku v9** | **0.0015** | **0.0000** | **0.0005** | **0.0007** |
| ramping_average | baseline | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
|  | 0.4.0 rule-based | 1.0449 | 1.0476 | 1.0528 | 1.0484 |
|  | v9 scripted | 0.9874 | 0.9562 | 0.9658 | 0.9698 |
|  | **Haiku v9** | **0.9865** | **0.9561** | **0.9661** | **0.9696** |
| daily_peak_average | baseline | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
|  | 0.4.0 rule-based | 0.9832 | 0.9925 | 0.9959 | 0.9905 |
|  | v9 scripted | 0.9136 | 0.9000 | 0.9287 | 0.9141 |
|  | **Haiku v9** | **0.9137** | **0.9000** | **0.9286** | **0.9141** |
| all_time_peak_average | baseline | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
|  | 0.4.0 rule-based | 1.0000 | 0.9799 | 1.0000 | 0.9933 |
|  | v9 scripted | 0.9439 | 0.8387 | 0.8871 | 0.8899 |
|  | **Haiku v9** | **0.9445** | **0.8390** | **0.8871** | **0.8902** |
| daily_one_minus_load_factor_average | baseline | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
|  | 0.4.0 rule-based | 0.9868 | 0.9941 | 0.9972 | 0.9927 |
|  | v9 scripted | 0.9688 | 0.9533 | 0.9799 | 0.9673 |
|  | **Haiku v9** | **0.9686** | **0.9532** | **0.9795** | **0.9671** |
| power_outage_normalized_unserved_energy_total | baseline | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
|  | 0.4.0 rule-based | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
|  | v9 scripted | 0.0000 | 0.0000 | 0.0000 | 0.0000 |
|  | **Haiku v9** | **0.0000** | **0.0000** | **0.0000** | **0.0000** |
| Clamped hours | baseline | 0 | 0 | 0 | 0.0 |
|  | 0.4.0 rule-based | 1 | 0 | 0 | 0.3 |
|  | v9 scripted | 10 | 10 | 3 | 7.7 |
|  | **Haiku v9** | **10** | **11** | **3** | **8.0** |
| Fallback hours | **Haiku v9** | **0** | **0** | **0** | **0.0** |
| Model cost | **Haiku v9** | **$0.5187** | **$0.5351** | **$0.5331** | **$0.5290** |

- **Haiku v9 beats the baseline on every KPI in every holdout month**, with unserved energy in outages tied at 0. No KPI comes in over the baseline. Mean of three: cost 0.9231 (down 7.7 percent), emissions 0.9544 (down 4.6 percent), grid import 0.9564, discomfort 0.0279 against 0.1294, too warm 0.0007 against 0.0158, ramping 0.9696, daily peak 0.9141, all-time peak 0.8902, load factor 0.9671.
- **It beats the 0.4.0 rule-based controller on every KPI in every month**, with unserved energy tied at 0. The rule-based controller is the one that comes in over the baseline: on ramping in every month (mean 1.0484), on grid import in every month (mean 1.0015), on discomfort and too cool in June (0.1826 against 0.1821, 0.1397 against 0.1392) and on the August all-time peak by 0.000002.
- **It does not beat the v9 scripted strategy overall.** It runs within 0.0006 of it on every KPI in every month, and trails it on cost in all three months (mean 0.923059 against 0.922944), on emissions in June and August (mean +0.000147), on grid import in all three months (mean +0.000148), on the all-time peak in June (+0.000561) and July (+0.000307) with August tied (mean +0.000289), on the daily peak in June (+0.000036), on ramping in August (+0.000299), and by one clamped hour in July (11 against 10). It is ahead on ramping in June and July (mean 0.969573 against 0.969817), on the daily peak in July and August (mean 0.914118 against 0.914147) and on load factor in all three months (mean 0.967139 against 0.967328). Discomfort, too cool, too warm and unserved energy are identical to six decimals. On the holdout the live agent's result is its strategy's result.
- **The gap to the strategy is far smaller than in 0.10.0.** Haiku v8 sat 0.0035 above its strategy on mean cost and 0.0178 above it on the mean all-time peak on the month set (0.9122 against 0.9087, 0.8975 against 0.8797); Haiku v9 sits 0.0001 and 0.0003 above v9 scripted on the holdout. These are different buildings and a different prompt, so the two gaps are not a like-for-like comparison.
- **No outage happened.** The stochastic outage model is on in the holdout schema, but no hour of the three episodes has an outage flag, so unserved energy is 0 for every controller and thermal resilience is not scored. The holdout says nothing about how the agent handles an outage.
- **Model cost:** 2,205 calls, 0 fallbacks, $1.5869 in all ($0.5187, $0.5351 and $0.5331), each month under its $2.00 cap. That is above the 0.11.0 estimate of $1.30 to $1.36: replies averaged 486 output tokens against the 220 estimated (input 4,768 against 4,810).

The published viewer still shows the 0.10.0 phase 2 live run.

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

**Goal:** find and close the gap between the 0.9.0 live agent (cost 0.9245, discomfort 0.0940) and the strategy it is given (scripted v7: 0.9016 and 0.0430), fix the hot-side comfort miss, and score everything on more than one month. The envelope is identical to 0.9.0. The analysis, the strategy and the estimates below were built from recorded runs and offline controllers before any live call; the live months on all four months of the set follow them.

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
- **Only live runs can show** whether Haiku sends the strategy's cooling numbers as given, whether it keeps its battery discipline with the new wording, how far it goes its own way on trims, and how the rooms then evolve; and on the tuning months, how a live agent compares at all, since none had run there before this release.

**Request size and cost.** A version 8 request averages 9,456 characters against 10,748 for version 7 over the same scripted month, 12.0 percent smaller: the system prompt is 3,645 characters against 4,780, the observation 153 shorter, and the reply schema unchanged. Scaled from the 0.9.0 live month (5,185 input and 245 output tokens per call, $0.4607), a Haiku month should cost about $0.42 ($0.4159 at the same reply length, $0.4379 if replies run 25 percent longer). The hard worst case is $0.95 for 719 hours and $0.98 for 743 hours, under the $2.00 cap. Live Haiku months on all four months of the set (2,924 hours) should cost about $1.69 to $1.78 in all, each month under its own $2.00 cap.

**Live results.** Four live runs (`claude-haiku-5-5`, prompt version 8, $2.00 budget each): the phase 2 month (run 20261023T160151Z, 719 hours) and tuning June (20261023T160150Z, 719 hours), July (20261023T160200Z, 743 hours) and August (20261023T160206Z, 743 hours), each scored by `hyperbolic months --run` against the baseline, the 0.4.0 rule-based controller (run 20261022T162847Z on the phase 2 month) and the scripted v8 strategy on the same month:

| CityLearn KPI (district) | | phase 2 | tuning June | tuning July | tuning August | mean |
|---|---|---|---|---|---|---|
| cost_total | baseline | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| | 0.4.0 rule-based | 0.9611 | 0.9506 | 0.9676 | 0.9682 | 0.9619 |
| | v8 scripted | 0.9031 | 0.9099 | 0.9193 | 0.9023 | 0.9087 |
| | **Haiku v8** | **0.9045** | **0.9147** | **0.9228** | **0.9070** | **0.9122** |
| carbon_emissions_total | baseline | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| | 0.4.0 rule-based | 0.9947 | 1.0001 | 1.0038 | 1.0024 | 1.0002 |
| | v8 scripted | 0.9447 | 0.9654 | 0.9703 | 0.9524 | 0.9582 |
| | **Haiku v8** | **0.9453** | **0.9691** | **0.9731** | **0.9559** | **0.9609** |
| electricity_consumption_total | baseline | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| | 0.4.0 rule-based | 1.0073 | 1.0065 | 1.0060 | 1.0071 | 1.0067 |
| | v8 scripted | 0.9540 | 0.9699 | 0.9717 | 0.9549 | 0.9626 |
| | **Haiku v8** | **0.9547** | **0.9733** | **0.9744** | **0.9583** | **0.9652** |
| discomfort_proportion | baseline | 0.1714 | 0.1128 | 0.0645 | 0.1919 | 0.1352 |
| | 0.4.0 rule-based | 0.1714 | 0.1128 | 0.0645 | 0.1919 | 0.1352 |
| | v8 scripted | 0.0374 | 0.0174 | 0.0073 | 0.0210 | 0.0208 |
| | **Haiku v8** | **0.0394** | **0.0207** | **0.0114** | **0.0251** | **0.0241** |
| too cool (discomfort_cold_proportion) | baseline | 0.1538 | 0.0602 | 0.0614 | 0.1902 | 0.1164 |
| | 0.4.0 rule-based | 0.1538 | 0.0602 | 0.0614 | 0.1902 | 0.1164 |
| | v8 scripted | 0.0258 | 0.0069 | 0.0057 | 0.0210 | 0.0149 |
| | **Haiku v8** | **0.0266** | **0.0088** | **0.0098** | **0.0251** | **0.0176** |
| too warm (discomfort_hot_proportion) | baseline | 0.0176 | 0.0526 | 0.0031 | 0.0017 | 0.0188 |
| | 0.4.0 rule-based | 0.0176 | 0.0526 | 0.0031 | 0.0017 | 0.0188 |
| | v8 scripted | 0.0116 | 0.0104 | 0.0016 | 0.0000 | 0.0059 |
| | **Haiku v8** | **0.0128** | **0.0118** | **0.0016** | **0.0000** | **0.0066** |
| ramping_average | baseline | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| | 0.4.0 rule-based | 1.1309 | 1.0742 | 1.0922 | 1.0848 | 1.0955 |
| | v8 scripted | 0.9983 | 0.9732 | 0.9677 | 1.0100 | 0.9873 |
| | **Haiku v8** | **0.9969** | **0.9802** | **0.9744** | **1.0157** | **0.9918** |
| daily_peak_average | baseline | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| | 0.4.0 rule-based | 0.9978 | 0.9934 | 0.9743 | 0.9734 | 0.9847 |
| | v8 scripted | 0.9095 | 0.8830 | 0.8854 | 0.8861 | 0.8910 |
| | **Haiku v8** | **0.9074** | **0.8919** | **0.8943** | **0.8896** | **0.8958** |
| all_time_peak_average | baseline | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| | 0.4.0 rule-based | 1.0000 | 1.0000 | 1.0000 | 0.9383 | 0.9846 |
| | v8 scripted | 0.9588 | 0.8541 | 0.8491 | 0.8570 | 0.8797 |
| | **Haiku v8** | **0.9590** | **0.8549** | **0.8822** | **0.8940** | **0.8975** |
| daily_one_minus_load_factor_average | baseline | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| | 0.4.0 rule-based | 0.9913 | 0.9834 | 0.9791 | 0.9867 | 0.9851 |
| | v8 scripted | 0.9639 | 0.9490 | 0.9520 | 0.9546 | 0.9549 |
| | **Haiku v8** | **0.9616** | **0.9534** | **0.9564** | **0.9514** | **0.9557** |
| power_outage_normalized_unserved_energy_total | baseline | 0.6844 | 0.0000 | 0.0000 | 0.0000 | 0.1711 |
| | 0.4.0 rule-based | 0.6844 | 0.0000 | 0.0000 | 0.0000 | 0.1711 |
| | v8 scripted | 0.6844 | 0.0000 | 0.0000 | 0.0000 | 0.1711 |
| | **Haiku v8** | **0.6844** | **0.0000** | **0.0000** | **0.0000** | **0.1711** |
| Clamped hours | baseline | 0 | 0 | 0 | 0 | 0.0 |
| | 0.4.0 rule-based | 1 | 1 | 0 | 0 | 0.5 |
| | v8 scripted | 22 | 32 | 10 | 3 | 16.8 |
| | **Haiku v8** | **33** | **39** | **14** | **17** | **25.8** |
| Model cost | **Haiku v8** | **$0.4182** | **$0.4118** | **$0.4229** | **$0.4288** | **$0.4204** |

Thermal resilience is scored only where there are outages: on the phase 2 month all four controllers tie at 0.3698.

- **Haiku v8 beats the 0.4.0 rule-based controller on every KPI in every one of the four months**, with unserved energy in outages tied. In 0.9.0 the live agent trailed it on hot-side discomfort.
- **Too-warm discomfort is now below the baseline in every month** (0.0128 against 0.0176 on phase 2, 0.0118 against 0.0526 in June, 0.0016 against 0.0031 in July, 0.0000 against 0.0017 in August). The v7 strategy was above the baseline in every month.
- **On the phase 2 month against 0.9.0 live:** cost 0.9045 against 0.9245, discomfort 0.0394 against 0.0940, too warm 0.0128 against 0.0181, ramping 0.9969 against 0.9864, clamped hours 33 against 27. It gives back a little ramping and a few clamped hours for a large gain in cost and comfort.
- **It is the best live run so far on cost, emissions, grid import, discomfort, too warm and the daily peak** (phase 2: 0.9045, 0.9453, 0.9547, 0.0394, 0.0128 and 0.9074, against 0.8.0 live's 0.9190 and 0.9610, 0.7.0 live's 0.9684 and 0.0741, 0.8.0 live's 0.0168 and 0.9.0 live's 0.9182). It is not the best on the all-time peak (0.9.0 live: 0.9412), ramping (0.9.0 live: 0.9864) or load factor (0.4.0 live: 0.9559).
- **The agent now follows its strategy closely.** Haiku runs within about 0.004 of the v8 scripted strategy on mean cost (0.9122 against 0.9087; 0.0013 to 0.0048 by month), where 0.9.0 live sat 0.0229 above the v7 strategy on the phase 2 month.
- **The one KPI over the baseline is August ramping** (1.0157), where the v8 scripted strategy is also over (1.0100). It is a strategy limit, not an agent deviation.
- **Phase 2 is no longer a clean holdout.** The outage exception in the warm-room cooling and the selection rule were set after looking at the phase 2 month, so the three tuning months are the cleaner evidence. They tell the same story: below the rule-based controller on every KPI and within 0.005 of the scripted strategy on cost.
- 0 fallbacks in all four months. The four runs cost $1.6817 in all ($0.4204 a month on average, against the $0.42 estimate), each well under its $2.00 budget, and each replays every hour identically with 0 API calls (719, 719, 743 and 743 of their hours).

**The published viewer now shows the 0.10.0 phase 2 live run** in place of 0.9.0 (the page's headline: cost down 9.6 percent, emissions down 5.5 percent at equal or better comfort). The phase 2 month stays the published one so the page stays comparable with earlier releases.

### Version 0.11.0

**Goal:** close the two gaps the 0.10.0 live months left, the all-time peak (July 0.8822 against scripted v8 0.8491, August 0.8940 against 0.8570, with the daily peak about 0.009 behind too) and August ramping (1.0157, the one KPI over the baseline), and set up a holdout nothing in this release is tuned on. The envelope is identical to 0.10.0. No live model calls were made: everything here is measured on recorded runs and offline controllers, and the published viewer still shows the 0.10.0 phase 2 run.

**A holdout, chosen and sealed first** ([HOLDOUT.md](HOLDOUT.md)). Every result so far is on data the project has looked at: phase 2 shaped the outage exception and the tuning months chose the strategy's numbers. CityLearn v3.0.2 ships no dataset that is both new to the project and fully compatible with it. Every 2023 set reuses the phase 2 or tuning data, and every other dataset has other actions or observations. The closest, chosen before any tuning, is **Buildings 4, 5 and 6 of `citylearn_challenge_2023_phase_3_1`**, June, July and August (`holdout-06`, `holdout-07`, `holdout-08`). It has the same actions and observations, new loads, occupancy, LSTM models, batteries and heat pumps, and stochastic outages. Its weather, tariff and carbon intensity are the tuning months', hour for hour, so it tests new buildings, not a new climate. `hyperbolic months` and `compare` refuse it without `--holdout-final`, the files are checked against a seal of hashes before scoring, and only the baseline has been run on it.

**The acceptance rule was written into the CHANGELOG before any version 9 result:** on the mean of the four months, v9 scripted must have a lower all-time peak and lower ramping than v8 scripted, no more than 0.001 worse cost, emissions, discomfort or too warm, and no worse outage energy; otherwise nothing new ships.

**Where the live peaks came from** (`scripts/analyze_peaks.py`). The all-time peak is a single hour. In phase 2 and June Haiku sent exactly the strategy's actions in it and the hours before. In July (day 31, 8 pm) it sent battery 0 where the strategy shaved, and in August (day 19, 7 pm) an all-null reply. Each departure class put back to the strategy on its own, through the unchanged envelope (control replays reproduce the published KPIs exactly):

| KPI points explained, sum of four months | All-time peak | Daily peak | Ramping |
|---|---|---|---|
| Skipped shaves (35 building-hours) | +0.0555 | +0.0120 | +0.0155 |
| Missed trim starts (416) | 0.0000 | +0.0126 | -0.0212 |
| Skipped charges (82) | 0.0000 | +0.0026 | +0.0311 |
| Every other class | at most 0.0006 | at most 0.0030 either way | at most 0.0040 either way |

- **Skipped shaves are the all-time peak gap.** Putting them back takes August from 0.8940 to the strategy's 0.8570 and July from 0.8822 to 0.8637. 29 of the 35 came after the top-price hours and 8 of the 17 hours fell on flat-price days. The agent's reasons say it followed the strategy while calling the batteries idle; the version 8 prompt said "Before them discharge only to shave" and "Idle on flat_24h days".
- **Missed trim starts** (415 of 416 are `null` with the trim state off) and skipped shaves make the daily peak gap. Skipped charges are most of the agent's ramping.

**August ramping, split exactly** (points above 1.0): scripted v8 +1.00 (battery charging +1.44, discharging -1.58, trims +1.12, of which trim ends +3.91), Haiku +1.57 (battery +1.11, trims +0.43). The strategy is 1.00 of the 1.57; the agent adds 0.57, its battery +1.25 less 0.69 from the trims it did not start. Most of the strategy's own share is trim ends, which the envelope fixes (a trim ends at once at the setpoint and eases by at most 0.02 an hour), so a strategy change cannot remove it.

**The search** (`scripts/tune_strategy.py --version 9`, the four months, the rule as written). Every all-time peak falls in an evening hour just after the top-price discharge, so the grid kept charge back through the top-price hours for that shave (`evening_reserve`), with the shave share and the grid charge rise. **The first pass, 36 settings, passed none**: a reserve of 0.05 cuts the all-time peak to 0.8643 and ramping to 0.9788 but costs 0.003. **A second, finer pass, added after that and reported as such, passed one of 8: `evening_reserve` 0.01.** It ships as the version 9 strategy. At tuning July's peak each battery leaves the top-price hours with 0.009 more charge, the shave discharges it, and the peak falls from 12.49 to 12.42 kWh.

**Estimates, four months, no holdout** (`hyperbolic months`; scripted rows are not model results):

| Mean of four months | cost | emissions | discomfort | too warm | ramping | daily peak | all-time peak | load factor | outage |
|---|---|---|---|---|---|---|---|---|---|
| 0.4.0 rule-based | 0.9619 | 1.0002 | 0.1352 | 0.0188 | 1.0955 | 0.9847 | 0.9846 | 0.9851 | 0.1711 |
| v8 scripted | 0.9087 | 0.9582 | 0.0208 | 0.0059 | 0.9873 | 0.8910 | 0.8797 | 0.9549 | 0.1711 |
| **v9 scripted** | **0.9093** | **0.9582** | **0.0208** | **0.0059** | **0.9857** | **0.8898** | **0.8768** | **0.9540** | **0.1711** |
| Haiku v8 live (0.10.0) | 0.9122 | 0.9609 | 0.0241 | 0.0066 | 0.9918 | 0.8958 | 0.8975 | 0.9557 | 0.1711 |
| Haiku v8, skipped shaves put back | 0.9123 | 0.9608 | 0.0241 | 0.0066 | 0.9879 | 0.8928 | 0.8836 | 0.9535 | 0.1711 |

- **v9 passes the acceptance rule**, narrowly: all-time peak 0.876779 against 0.879746, ramping 0.985732 against 0.987321, cost +0.000596, emissions +0.000024, discomfort, too warm and outage energy unchanged to six decimals. It is lower on the all-time peak in every month and on ramping in three of four (July +0.0004); August ramping is 1.0080, still above the baseline.
- **The bigger lever is the agent.** Putting back only the skipped shaves would take the 0.10.0 live mean all-time peak from 0.8975 to 0.8836. Prompt version 9's wording targets exactly those hours. Only live runs can show whether Haiku now shaves after the top price and starts trims.

**Request size and cost.** A version 9 request averages 9,716 characters against 9,456 for version 8 (2.8 percent larger; system prompt +241, observation +18). A Haiku month should cost about $0.42 (719 hours) to $0.44 (743 hours), with a hard worst case of $0.96 to $0.99 under the $2.00 cap: about $1.72 to $1.80 for the four months and $1.30 to $1.36 for the three holdout months.

### Version 0.13.0: free mode

**Question:** given room to deviate from the v9 strategy, can a stronger model find savings the rules miss? **On the one month tested, no.** Sonnet, given the freedom, did not take it. Haiku took it, and lost money doing so.

**Read this first.** The holdout is spent (scored once in 0.12.0), so this experiment runs on tuning July, a month the strategy's numbers were chosen on. That favors the strategy. The plan was cut to one confirmation month (phase 2) instead of three because of the $15.00 budget: a Sonnet month costs about $5.36. The pilot then failed its acceptance rule, so the confirmation month was not run either. Everything below is one month.

**Prompt version 10, free mode** (selectable with `--prompt-version 10`; version 9 stays the default):
- **The suggestion:** each building shows the v9 strategy's whole action as `suggestion`, exactly what version 9 shows as `strategy`, described as a suggestion, not an instruction.
- **New in the observation:** the direct solar forecast (now, 6, 12 and 24 hours ahead) and each building's heat pump power, battery power, battery standing loss and water heater efficiency. These were already in the simulator state but not shown. The 24 hour price and carbon outlook and the outdoor temperature forecast were already shown in version 9.
- **The freedom:** the agent may depart whenever it expects lower cost or emissions without losing comfort or the peaks, for example by cooling a room ahead of the top-price hours.
- **The hypothesis:** every building whose actions differ from its suggestion by more than 0.0005 (null counting as `baseline_action`), or that sends `end_trim`, must carry `deviation_reason`, a hypothesis under 150 characters. A reply that departs without one is invalid, and that hour runs the baseline action, like any invalid reply.
- **What stays the same:** the envelope, its rules and every limit, the v9 strategy and every tuned number. Versions 1 to 9 are byte for byte unchanged, and every recorded run still replays.

**The acceptance rule**, written into the CHANGELOG and committed before any live call: on tuning July, Sonnet v10 passes if its `cost_total` is below v9 scripted's, with emissions, discomfort and too warm no more than 0.001 worse and both peaks no more than 0.005 worse. **Result: it fails.** Its cost_total is 0.920084 against v9 scripted's 0.919906, 0.000178 higher. The other five conditions hold: emissions +0.000201, discomfort +0.000457, too warm, daily peak and all-time peak equal. Phase 2 was not run.

**Tuning July, every controller** (`hyperbolic months`; scripted rows are not model results; the Haiku v9 row is the 0.15.0 run on this month, which replaced the 0.10.0 Haiku v8 live run that stood in here before a Haiku v9 run existed):

| CityLearn KPI (district) | | tuning July | against v9 scripted |
|---|---|---|---|
| cost_total | baseline | 1.0000 |  |
|  | v9 scripted | 0.9199 |  |
|  | Haiku v9 (0.15.0) | 0.9197 | -0.000244 |
|  | **Haiku v10** | **0.9373** | +0.017389 |
|  | **Sonnet v10** | **0.9201** | +0.000178 |
| carbon_emissions_total | baseline | 1.0000 |  |
|  | v9 scripted | 0.9703 |  |
|  | Haiku v9 (0.15.0) | 0.9701 | -0.000247 |
|  | **Haiku v10** | **0.9772** | +0.006905 |
|  | **Sonnet v10** | **0.9705** | +0.000201 |
| electricity_consumption_total | baseline | 1.0000 |  |
|  | v9 scripted | 0.9717 |  |
|  | Haiku v9 (0.15.0) | 0.9715 | -0.000238 |
|  | **Haiku v10** | **0.9780** | +0.006298 |
|  | **Sonnet v10** | **0.9719** | +0.000202 |
| discomfort_proportion | baseline | 0.0645 |  |
|  | v9 scripted | 0.0073 |  |
|  | Haiku v9 (0.15.0) | 0.0073 | +0.000000 |
|  | **Haiku v10** | **0.0170** | +0.009675 |
|  | **Sonnet v10** | **0.0078** | +0.000457 |
| too cool (discomfort_cold_proportion) | baseline | 0.0614 |  |
|  | v9 scripted | 0.0057 |  |
|  | Haiku v9 (0.15.0) | 0.0057 | +0.000000 |
|  | **Haiku v10** | **0.0154** | +0.009675 |
|  | **Sonnet v10** | **0.0062** | +0.000457 |
| too warm (discomfort_hot_proportion) | baseline | 0.0031 |  |
|  | v9 scripted | 0.0016 |  |
|  | Haiku v9 (0.15.0) | 0.0016 | +0.000000 |
|  | **Haiku v10** | **0.0016** | +0.000000 |
|  | **Sonnet v10** | **0.0016** | +0.000000 |
| ramping_average | baseline | 1.0000 |  |
|  | v9 scripted | 0.9681 |  |
|  | Haiku v9 (0.15.0) | 0.9685 | +0.000462 |
|  | **Haiku v10** | **1.0239** | +0.055813 |
|  | **Sonnet v10** | **0.9685** | +0.000446 |
| daily_peak_average | baseline | 1.0000 |  |
|  | v9 scripted | 0.8850 |  |
|  | Haiku v9 (0.15.0) | 0.8862 | +0.001147 |
|  | **Haiku v10** | **0.8789** | -0.006158 |
|  | **Sonnet v10** | **0.8850** | +0.000000 |
| all_time_peak_average | baseline | 1.0000 |  |
|  | v9 scripted | 0.8445 |  |
|  | Haiku v9 (0.15.0) | 0.8445 | +0.000000 |
|  | **Haiku v10** | **0.8488** | +0.004322 |
|  | **Sonnet v10** | **0.8445** | +0.000000 |
| daily_one_minus_load_factor_average | baseline | 1.0000 |  |
|  | v9 scripted | 0.9518 |  |
|  | Haiku v9 (0.15.0) | 0.9533 | +0.001456 |
|  | **Haiku v10** | **0.9407** | -0.011169 |
|  | **Sonnet v10** | **0.9516** | -0.000214 |
| power_outage_normalized_unserved_energy_total | baseline | 0.0000 |  |
|  | v9 scripted | 0.0000 |  |
|  | Haiku v9 (0.15.0) | 0.0000 | +0.000000 |
|  | **Haiku v10** | **0.0000** | +0.000000 |
|  | **Sonnet v10** | **0.0000** | +0.000000 |
| Clamped hours | baseline | 0 | |
|  | v9 scripted | 10 | |
|  | Haiku v9 (0.15.0) | 10 | |
|  | **Haiku v10** | 8 | |
|  | **Sonnet v10** | 10 | |
| Fallback hours | Haiku v9 (0.15.0) | 0 | |
|  | **Haiku v10** | 159 | |
|  | **Sonnet v10** | 2 | |
| Model cost | Haiku v9 (0.15.0) | $0.3529 | |
|  | **Haiku v10** | $0.3831 | |
|  | **Sonnet v10** | $5.3566 | |

- **Sonnet v10 sent the suggestion in every hour but two, and gave no hypothesis all month.** Its only two departures were copying slips with no `deviation_reason`. In hour 541 it put the battery's 0.01 into Building_3's tank as well. In hour 594 it sent Building_3 cooling 0.2628 against a suggested 0.262. Its reason in both hours said it was sending the suggestions unchanged. The check rejected both replies, so those two hours ran the baseline action. In hour 594 that dropped Building_1's cooling trim, and the room went 2.17 C below its setpoint, one too-cool occupied hour.
- **Sonnet v10 against v9 scripted:** behind on cost (+0.000178), emissions (+0.000201), grid import (+0.000202), discomfort and too cool (+0.000457) and ramping (+0.000446). Equal on too warm, the daily peak, the all-time peak and unserved energy. Ahead on load factor (-0.000214). Every gap comes from the two rejected hours.
- **Sonnet v10 beats the baseline on every KPI**, with unserved energy tied at 0 (no outage on this month).
- **Haiku v10 lost 159 hours to the check.** In 159 of 743 hours its reply departed from the suggestion without a `deviation_reason`. Mostly it sent `null` (the baseline) where the suggestion trims cooling or moves the battery, while its reason said it was following the suggestions. That is the 0.10.0 habit of sending `null` where the strategy acts, and free mode rejects it. Those hours ran the baseline action.
- **Haiku v10 against v9 scripted:** cost 0.9373 against 0.9199 (+0.0174), emissions +0.0069, discomfort 0.0170 against 0.0073, and ramping 1.0239 against 0.9681. **Its ramping is over the baseline (1.0239 against 1.0000), the one KPI over the baseline in this release.** It is ahead of v9 scripted on the daily peak (0.8789 against 0.8850) and load factor (0.9407 against 0.9518), and behind it on the all-time peak (0.8488 against 0.8445).
- **Haiku v10 is behind Haiku v9 (the 0.15.0 run) on the same month** on cost (0.9373 against 0.9197), emissions, grid import, discomfort, too cool, ramping and the all-time peak (0.8488 against 0.8445). It is ahead on the daily peak (0.8789 against 0.8862) and load factor (0.9407 against 0.9533), and level on too warm. (Before 0.15.0 this line compared it with the 0.10.0 Haiku v8 live run.)
- **Neither model pre-cooled.** Sonnet never cooled above the suggestion. Haiku did once, in a rejected hour, with no reason.

**Attribution** (`scripts/analyze_free_mode.py`). Every departure is sorted into the 0.10.0 classes, with extra cooling before the top-price hours split out as `precool`. Departures below the 0.10.0 tolerances (0.002 cooling, 0.005 storage), including `null` against an equal number, go in `small`. Each class is then put back to the suggestion and the month is resimulated with zero model calls, the way 0.11.0 put back skipped shaves. Each class gets the dollars and KPI points its departures were worth: + means the departures made it worse, - means they helped.

One difference from 0.11.0: in every replay, a device the model left at its suggestion takes the suggestion of the replay's own observation, rather than the recorded number. So putting every departure back reproduces v9 scripted exactly; it does, on both runs. Every control replay reproduces its run's KPIs exactly.

Sonnet v10 (tuning July):

| Departures (building-hours, hours, with a reason) | $ | kg CO2 | cost | emissions | discomfort | ramping | daily peak | all-time peak |
|---|---|---|---|---|---|---|---|---|
| `dhw_used`: used the hot water tank (the strategy leaves it at 0) (1, 1, 0) | +0.00 | +0.01 | +0.0000 | +0.0000 | +0.0000 | -0.0002 | +0.0000 | +0.0000 |
| `small`: differed from the suggestion by less than the 0.10.0 class tolerances (1, 1, 0) | +0.02 | +0.24 | +0.0002 | +0.0002 | +0.0005 | +0.0006 | +0.0000 | +0.0000 |
| **Every departure in a rejected hour** | +0.02 | +0.25 | +0.0002 | +0.0002 | +0.0005 | +0.0004 | +0.0000 | +0.0000 |
| **Every departure** | +0.02 | +0.25 | +0.0002 | +0.0002 | +0.0005 | +0.0004 | +0.0000 | +0.0000 |

Haiku v10 (tuning July):

| Departures (building-hours, hours, with a reason) | $ | kg CO2 | cost | emissions | discomfort | ramping | daily peak | all-time peak |
|---|---|---|---|---|---|---|---|---|
| `precool`: cooled above the suggestion before the day's top-price hours (1, 1, 0) | +0.00 | +0.00 | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 |
| `trim_not_started`: no trim in an occupied, overcooled room where the strategy trims (81, 75, 3) | +0.22 | +2.35 | +0.0024 | +0.0019 | +0.0018 | +0.0007 | -0.0010 | +0.0000 |
| `trim_shallower`: a shallower trim than the strategy's (82, 63, 3) | +0.18 | +2.76 | +0.0019 | +0.0022 | +0.0027 | -0.0003 | +0.0001 | -0.0003 |
| `warm_skipped`: less than the strategy's extra cooling in a warm room (4, 4, 0) | -0.00 | -0.02 | -0.0000 | -0.0000 | +0.0000 | -0.0000 | +0.0000 | +0.0000 |
| `top_discharge_short`: discharged less than the strategy in a top-price hour (51, 17, 0) | +0.05 | +0.11 | +0.0006 | +0.0001 | +0.0000 | -0.0020 | -0.0015 | +0.0000 |
| `shave_skipped`: skipped or cut a peak-shaving discharge (11, 6, 0) | -0.08 | -0.04 | -0.0011 | -0.0001 | +0.0000 | +0.0125 | +0.0080 | -0.0014 |
| `charge_skipped`: charged less than the strategy in a charging hour (98, 35, 0) | +0.09 | -0.56 | +0.0010 | -0.0006 | +0.0000 | +0.0070 | +0.0057 | +0.0288 |
| `charge_off_plan`: charged when the strategy holds or only stores solar (31, 14, 31) | -0.01 | +1.04 | -0.0000 | +0.0009 | +0.0000 | +0.0055 | -0.0038 | -0.0308 |
| `discharge_off_plan`: discharged when the strategy does not (7, 7, 0) | +0.02 | +0.20 | +0.0002 | +0.0002 | +0.0000 | -0.0000 | +0.0003 | +0.0000 |
| `small`: differed from the suggestion by less than the 0.10.0 class tolerances (1622, 304, 18) | -0.00 | -0.01 | -0.0000 | -0.0000 | +0.0000 | -0.0000 | +0.0000 | +0.0000 |
| **Every departure in a rejected hour** | +1.50 | +7.91 | +0.0179 | +0.0060 | +0.0097 | +0.0514 | -0.0026 | +0.0045 |
| **Every departure with a reason** | +0.00 | +1.16 | +0.0000 | +0.0010 | +0.0000 | +0.0049 | -0.0038 | -0.0308 |
| **Every departure** | +1.46 | +8.84 | +0.0174 | +0.0069 | +0.0097 | +0.0558 | -0.0062 | +0.0043 |

- **What lost money:** the missing reasons. Putting back every departure in Haiku's 159 rejected hours is worth $1.50 of its $1.46 gap to v9 scripted. The other departures pull slightly the other way. For Sonnet the two rejected hours are the whole $0.0171.
- **By class, for Haiku:** not starting a trim cost $0.22 and a shallower trim $0.18, and together they carry +0.0045 of its +0.0097 discomfort. Skipped charges cost $0.09 and short top-price discharges $0.05. Skipped shaves saved $0.08 but added 0.0125 of ramping. A class's worth here includes the rejected hours it sits in, so the classes do not add up to the whole.
- **What made money:** nothing measurable. The departures that came with a hypothesis made $0.0019 more cost, not less.
- **Did the hypotheses match what happened?** Haiku's hypotheses were nearly all grid-charging arbitrage: 31 building-hours of `charge_off_plan`, every one claiming a cost gain, for example "Charge at 0.030 $/kWh to discharge at 0.066 $/kWh in hours 14-16; round-trip gain, peak headroom ample".
  - **Cost:** the gain did not appear. All its reasoned departures together come to +$0.0019, about even.
  - **Emissions:** they rose by 1.16 kg.
  - **"Peak unaffected":** the peaks did move. Ramping got worse (+0.0049), while the daily peak (-0.0038) and the all-time peak (-0.0308) came out lower. These are measured in a month that still has all 159 rejected hours in it.
  - **Sonnet** stated no hypothesis, so there is nothing to check.

**Spend:** $5.9191 of the $15.00 cap. The 24 hour smoke test was $0.1794, the Sonnet pilot $5.3566 and the Haiku pilot $0.3831.
- **Per call:** Sonnet averaged 2,496 uncached input tokens, 3,144 cached and 190 output; Haiku 2,493 uncached and 469 output. The cache hit rate was 56 percent for both.
- **Pricing correction:** the price table had Sonnet 5.5 cache reads at $0.20 per million tokens. Anthropic's published rate is $0.10, and the table now says so.
- **Replays:** both full runs and the smoke test replay every hour with 0 API calls (743, 743 and 24).

### Version 0.14.0: blind mode

**Question:** does Sonnet agree with the v9 rules on its own, or did it only defer to them in 0.13.0 because they were handed to it? **On the one month tested, it does not find them on its own.** Without the rules it was behind v9 scripted on every KPI, and agreed with the strategy's action in 37.8 percent of building-hours.

**Read this first.** The holdout is spent (scored once in 0.12.0), so this runs on tuning July again, the month 0.13.0 used and a month the strategy's numbers were chosen on. That favors the strategy. Everything below is one month.

**Prompt version 11, blind mode** (selectable with `--prompt-version 11`; version 9 stays the default):
- **The observation:** exactly version 10's without `suggestion` and `suggestion_reason`. The solar forecast and the building ratings stay. So does `peak.shave_now`, a true or false the strategy's own shave share (0.9 of the forecast peak) decides; the prompt names it without its threshold.
- **The system prompt:** version 10's without the free mode paragraph, the `deviation_reason` rules and the strategy. It keeps the goals, what the agent sees, the actions, the envelope and the reply rules, says plainly that `null` means `baseline_action`, and prints no strategy rule, threshold or tuned number.
- **The reply:** the envelope's standard schema with `end_trim`, no `deviation_reason`.
- **The shadow strategy:** every hour the v9 strategy's action for the same observation is worked out in code and logged as `shadow_strategy`, never sent. Agreement and attribution are measured against it, and scripted version 11 sends it, matching scripted v9 action for action.
- **What stays the same:** the envelope, its rules and every limit, the v9 strategy and every tuned number. Versions 1 to 10 are byte for byte unchanged, and every recorded run still replays.

**The acceptance rule and its readings**, written into the CHANGELOG and committed before any live call or code change: on tuning July, Sonnet v11 passes if its `cost_total` is below v9 scripted's, with emissions, discomfort and too warm no more than 0.001 worse and both peaks no more than 0.005 worse. Pre-registered readings: a pass means blind Sonnet found savings the rules miss; a cost miss of 0.002 or less with agreement at 80 percent or more on every device means it converged on the rules by itself; a miss of more than 0.002, or agreement under 80 percent on any device, means the rules carry knowledge Sonnet does not find on its own and its 0.13.0 deference was justified.

**Result: it fails, and the third reading applies.** Its cost_total is 0.945797 against v9 scripted's 0.919906, 0.025891 higher. Emissions (+0.042139), discomfort (+0.013333), the daily peak (+0.074785) and the all-time peak (+0.155544) fail too; only too warm passes (+0.000457). Agreement is under 80 percent on cooling (68.9) and the battery (54.8).

**Agreement with the v9 strategy** (`shadow_strategy`; within 0.002 for cooling and 0.005 for the tank and battery, `null` as `baseline_action`; 2,229 building-hours per run, no unusable replies):

| Device | Sonnet v11 | Haiku v11 |
|---|---|---|
| cooling | 68.9% (1,535) | 64.3% (1,433) |
| dhw | 97.3% (2,168) | 98.9% (2,204) |
| battery | 54.8% (1,222) | 59.0% (1,314) |
| all three at once | 37.8% (842) | 38.3% (854) |

**Tuning July, every controller** (`hyperbolic months`; scripted rows are not model results):

**cost_total**

| Controller | tuning July | against v9 scripted |
|---|---|---|
| baseline | 1.000000 | +0.080094 |
| v9 scripted | 0.919906 |  |
| Sonnet v10 (0.13.0) | 0.920084 | +0.000178 |
| **Sonnet v11** | **0.945797** | +0.025891 |
| Haiku v10 (0.13.0) | 0.937295 | +0.017389 |
| **Haiku v11** | **0.992758** | +0.072852 |
| Haiku v9 (0.15.0) | 0.919662 | -0.000244 |

**carbon_emissions_total**

| Controller | tuning July | against v9 scripted |
|---|---|---|
| baseline | 1.000000 | +0.029692 |
| v9 scripted | 0.970308 |  |
| Sonnet v10 (0.13.0) | 0.970509 | +0.000201 |
| **Sonnet v11** | **1.012447** | +0.042139 |
| Haiku v10 (0.13.0) | 0.977213 | +0.006905 |
| **Haiku v11** | **1.014709** | +0.044401 |
| Haiku v9 (0.15.0) | 0.970061 | -0.000247 |

**electricity_consumption_total**

| Controller | tuning July | against v9 scripted |
|---|---|---|
| baseline | 1.000000 | +0.028296 |
| v9 scripted | 0.971704 |  |
| Sonnet v10 (0.13.0) | 0.971906 | +0.000202 |
| **Sonnet v11** | **1.010680** | +0.038976 |
| Haiku v10 (0.13.0) | 0.978002 | +0.006298 |
| **Haiku v11** | **1.014323** | +0.042619 |
| Haiku v9 (0.15.0) | 0.971466 | -0.000238 |

**discomfort_proportion**

| Controller | tuning July | against v9 scripted |
|---|---|---|
| baseline | 0.064481 | +0.057186 |
| v9 scripted | 0.007295 |  |
| Sonnet v10 (0.13.0) | 0.007752 | +0.000457 |
| **Sonnet v11** | **0.020628** | +0.013333 |
| Haiku v10 (0.13.0) | 0.016970 | +0.009675 |
| **Haiku v11** | **0.062652** | +0.055357 |
| Haiku v9 (0.15.0) | 0.007295 | +0.000000 |

**too cool (discomfort_cold_proportion)**

| Controller | tuning July | against v9 scripted |
|---|---|---|
| baseline | 0.061374 | +0.055669 |
| v9 scripted | 0.005705 |  |
| Sonnet v10 (0.13.0) | 0.006162 | +0.000457 |
| **Sonnet v11** | **0.018581** | +0.012876 |
| Haiku v10 (0.13.0) | 0.015380 | +0.009675 |
| **Haiku v11** | **0.059545** | +0.053840 |
| Haiku v9 (0.15.0) | 0.005705 | +0.000000 |

**too warm (discomfort_hot_proportion)**

| Controller | tuning July | against v9 scripted |
|---|---|---|
| baseline | 0.003107 | +0.001517 |
| v9 scripted | 0.001590 |  |
| Sonnet v10 (0.13.0) | 0.001590 | +0.000000 |
| **Sonnet v11** | **0.002047** | +0.000457 |
| Haiku v10 (0.13.0) | 0.001590 | +0.000000 |
| **Haiku v11** | **0.003107** | +0.001517 |
| Haiku v9 (0.15.0) | 0.001590 | +0.000000 |

**ramping_average**

| Controller | tuning July | against v9 scripted |
|---|---|---|
| baseline | 1.000000 | +0.031948 |
| v9 scripted | 0.968052 |  |
| Sonnet v10 (0.13.0) | 0.968498 | +0.000446 |
| **Sonnet v11** | **1.082070** | +0.114018 |
| Haiku v10 (0.13.0) | 1.023865 | +0.055813 |
| **Haiku v11** | **1.039499** | +0.071447 |
| Haiku v9 (0.15.0) | 0.968514 | +0.000462 |

**daily_peak_average**

| Controller | tuning July | against v9 scripted |
|---|---|---|
| baseline | 1.000000 | +0.114969 |
| v9 scripted | 0.885031 |  |
| Sonnet v10 (0.13.0) | 0.885031 | +0.000000 |
| **Sonnet v11** | **0.959816** | +0.074785 |
| Haiku v10 (0.13.0) | 0.878873 | -0.006158 |
| **Haiku v11** | **0.975590** | +0.090559 |
| Haiku v9 (0.15.0) | 0.886178 | +0.001147 |

**all_time_peak_average**

| Controller | tuning July | against v9 scripted |
|---|---|---|
| baseline | 1.000000 | +0.155520 |
| v9 scripted | 0.844480 |  |
| Sonnet v10 (0.13.0) | 0.844480 | +0.000000 |
| **Sonnet v11** | **1.000024** | +0.155544 |
| Haiku v10 (0.13.0) | 0.848802 | +0.004322 |
| **Haiku v11** | **1.000024** | +0.155544 |
| Haiku v9 (0.15.0) | 0.844480 | +0.000000 |

**daily_one_minus_load_factor_average**

| Controller | tuning July | against v9 scripted |
|---|---|---|
| baseline | 1.000000 | +0.048177 |
| v9 scripted | 0.951823 |  |
| Sonnet v10 (0.13.0) | 0.951609 | -0.000214 |
| **Sonnet v11** | **0.980215** | +0.028392 |
| Haiku v10 (0.13.0) | 0.940654 | -0.011169 |
| **Haiku v11** | **0.976418** | +0.024595 |
| Haiku v9 (0.15.0) | 0.953279 | +0.001456 |

**power_outage_normalized_unserved_energy_total**

| Controller | tuning July | against v9 scripted |
|---|---|---|
| baseline | 0.000000 | +0.000000 |
| v9 scripted | 0.000000 |  |
| Sonnet v10 (0.13.0) | 0.000000 | +0.000000 |
| **Sonnet v11** | **0.000000** | +0.000000 |
| Haiku v10 (0.13.0) | 0.000000 | +0.000000 |
| **Haiku v11** | **0.000000** | +0.000000 |
| Haiku v9 (0.15.0) | 0.000000 | +0.000000 |

**Hours and model cost**

| Controller | clamped hours | fallback hours | model cost |
|---|---|---|---|
| baseline | 0 | 0 | none |
| v9 scripted | 10 | 0 | none |
| Sonnet v10 (0.13.0) | 10 | 2 | $5.3566 |
| **Sonnet v11** | 38 | 0 | $4.8587 |
| Haiku v10 (0.13.0) | 8 | 159 | $0.3831 |
| **Haiku v11** | 63 | 0 | $0.2698 |
| Haiku v9 (0.15.0) | 10 | 0 | $0.3529 |
- **Sonnet v11 is behind v9 scripted on every KPI**, with unserved energy tied at 0 (no outage on this month). It is behind Sonnet v10 on every KPI too.
- **Sonnet v11 against the baseline:** ahead on cost (0.9458), discomfort (0.0206 against 0.0645), too cool, too warm (0.0020 against 0.0031), the daily peak (0.9598) and load factor (0.9802). **Behind the baseline on emissions (1.0124), grid import (1.0107), ramping (1.0821) and the all-time peak (1.000024).** Its all-time peak is the baseline's plus 0.000024, where v9 scripted cuts it to 0.8445.
- **Haiku v11 against the baseline:** ahead on cost (0.9928), discomfort (0.0627 against 0.0645), too cool, the daily peak (0.9756) and load factor (0.9764); level on too warm. **Behind on emissions (1.0147), grid import (1.0143), ramping (1.0395) and the all-time peak (1.000024).**
- **Haiku v11 against Sonnet v11:** behind on cost, emissions, grid import, discomfort, too cool, too warm and the daily peak; ahead on ramping and load factor; level on the all-time peak. Haiku v11 is behind Haiku v10 on every KPI except unserved energy.
- **No fallback hour in either blind run.** Every reply parsed. Clamped hours rose to 38 (Sonnet) and 63 (Haiku) against v9 scripted's 10.
- **What blind Sonnet did differently:** it kept cooling at the baseline in most hours, so it started no trim in 585 building-hours where the strategy trims. It charged batteries in 258 building-hours where the strategy holds, and skipped or cut 163 building-hours of peak shaving, though the observation still carries `peak.shave_now`.
- **Did Sonnet pre-cool?** 26 building-hours in 25 hours are cooling above the strategy before the day's top-price hours, 0.074 above it on average. Its hourly reasons there mostly say it keeps baseline cooling or cools a warm room; one reason in the whole month mentions pre-cooling. That class lost $0.14 and added 2.03 kg. Haiku did the same in 11 building-hours (+$0.05).

**Attribution** (`scripts/analyze_free_mode.py`, now also for blind mode). Each departure from `shadow_strategy` is sorted into the 0.13.0 classes, put back to the strategy's action and the month resimulated with zero model calls: + means the departures made it worse, - means they helped. Each control replay reproduces its run's KPIs exactly, and putting every departure back reproduces v9 scripted exactly ($75.8602, 1,038.712 kg) on both runs. The logged shadow matches the strategy worked out again on all 743 recorded observations of each run.

Sonnet v11 (tuning July):

| Departures from the shadow strategy (building-hours, hours) | $ | kg CO2 | cost | emissions | discomfort | ramping | daily peak | all-time peak |
|---|---|---|---|---|---|---|---|---|
| `precool`: cooled above the strategy before the day's top-price hours (26, 25) | +0.14 | +2.03 | +0.0021 | +0.0023 | +0.0000 | +0.0022 | -0.0001 | +0.0000 |
| `trim_not_started`: no trim in an occupied, overcooled room where the strategy trims (585, 506) | +2.18 | +27.73 | +0.0229 | +0.0225 | +0.0148 | -0.0142 | +0.0109 | +0.0103 |
| `trim_shallower`: a shallower trim than the strategy's (36, 31) | +0.04 | +0.24 | +0.0004 | +0.0002 | +0.0000 | +0.0003 | +0.0000 | +0.0000 |
| `trim_deeper`: a deeper trim than the strategy's (29, 23) | -0.16 | -1.69 | -0.0017 | -0.0013 | -0.0037 | +0.0011 | -0.0030 | +0.0000 |
| `extra_cooling`: cooled above the strategy at any other time (5, 5) | +0.02 | +0.19 | +0.0004 | +0.0003 | +0.0000 | -0.0000 | +0.0000 | +0.0000 |
| `warm_skipped`: less than the strategy's extra cooling in a warm room (18, 18) | -0.02 | -0.27 | -0.0003 | -0.0003 | +0.0010 | +0.0001 | -0.0003 | +0.0000 |
| `top_discharge_short`: discharged less than the strategy in a top-price hour (36, 26) | +0.05 | +0.34 | +0.0007 | +0.0003 | +0.0000 | +0.0020 | -0.0002 | +0.0000 |
| `top_discharge_over`: discharged more than the strategy in a top-price hour (142, 58) | -0.03 | +7.67 | +0.0005 | +0.0090 | +0.0000 | +0.0301 | -0.0047 | +0.0000 |
| `shave_skipped`: skipped or cut a peak-shaving discharge (163, 59) | -1.22 | +5.46 | -0.0156 | +0.0060 | +0.0000 | +0.1014 | +0.0747 | +0.2043 |
| `charge_skipped`: charged less than the strategy in a charging hour (303, 133) | -0.01 | -0.07 | -0.0001 | -0.0000 | +0.0000 | +0.0077 | -0.0043 | +0.0000 |
| `charge_over`: charged more than the strategy in a charging hour (74, 27) | -0.19 | +1.95 | -0.0025 | +0.0020 | +0.0000 | +0.0124 | +0.0015 | +0.0000 |
| `charge_off_plan`: charged when the strategy holds or only stores solar (258, 100) | -1.81 | +10.34 | -0.0231 | +0.0109 | +0.0000 | -0.0046 | -0.0153 | +0.0000 |
| `discharge_off_plan`: discharged when the strategy does not (31, 31) | +0.07 | +1.00 | +0.0007 | +0.0008 | +0.0000 | +0.0034 | +0.0000 | +0.0000 |
| `dhw_used`: used the hot water tank (the strategy leaves it at 0) (61, 21) | +0.46 | +7.24 | +0.0056 | +0.0068 | +0.0000 | +0.0112 | +0.0000 | +0.0000 |
| `small`: differed from the strategy by less than the 0.10.0 class tolerances (3357, 731) | +0.00 | +0.04 | +0.0000 | +0.0000 | +0.0000 | +0.0002 | +0.0000 | +0.0000 |
| **Every departure** | +2.32 | +46.20 | +0.0259 | +0.0421 | +0.0133 | +0.1140 | +0.0748 | +0.1555 |


Haiku v11 (tuning July):

| Departures from the shadow strategy (building-hours, hours) | $ | kg CO2 | cost | emissions | discomfort | ramping | daily peak | all-time peak |
|---|---|---|---|---|---|---|---|---|
| `precool`: cooled above the strategy before the day's top-price hours (11, 9) | +0.05 | +0.79 | +0.0007 | +0.0008 | +0.0000 | +0.0005 | +0.0000 | +0.0000 |
| `trim_not_started`: no trim in an occupied, overcooled room where the strategy trims (740, 582) | +3.59 | +45.92 | +0.0374 | +0.0371 | +0.0538 | -0.0140 | +0.0200 | +0.0014 |
| `trim_shallower`: a shallower trim than the strategy's (5, 5) | +0.01 | +0.18 | +0.0001 | +0.0001 | +0.0000 | +0.0000 | +0.0000 | +0.0000 |
| `trim_deeper`: a deeper trim than the strategy's (3, 2) | -0.04 | -0.30 | -0.0004 | -0.0002 | +0.0000 | +0.0011 | +0.0000 | +0.0000 |
| `trim_unwanted`: a trim where the strategy has none (3, 3) | -0.01 | -0.21 | -0.0001 | -0.0002 | +0.0000 | +0.0004 | +0.0000 | +0.0000 |
| `extra_cooling`: cooled above the strategy at any other time (1, 1) | +0.00 | +0.00 | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 |
| `warm_skipped`: less than the strategy's extra cooling in a warm room (37, 37) | -0.04 | -0.51 | -0.0005 | -0.0005 | +0.0015 | +0.0001 | -0.0004 | +0.0000 |
| `top_discharge_short`: discharged less than the strategy in a top-price hour (171, 61) | +1.99 | +3.17 | +0.0271 | +0.0030 | +0.0000 | -0.0255 | +0.0041 | +0.0000 |
| `top_discharge_over`: discharged more than the strategy in a top-price hour (16, 10) | -0.02 | +0.59 | -0.0002 | +0.0008 | +0.0000 | +0.0059 | -0.0019 | +0.0000 |
| `shave_skipped`: skipped or cut a peak-shaving discharge (167, 58) | -0.09 | +3.65 | -0.0017 | +0.0033 | +0.0000 | +0.0593 | +0.0842 | +0.1793 |
| `charge_skipped`: charged less than the strategy in a charging hour (313, 148) | +0.09 | +0.13 | +0.0013 | +0.0002 | +0.0000 | +0.0082 | -0.0005 | +0.0000 |
| `charge_over`: charged more than the strategy in a charging hour (25, 12) | +0.02 | +0.17 | +0.0002 | +0.0001 | +0.0000 | +0.0020 | +0.0000 | +0.0000 |
| `charge_off_plan`: charged when the strategy holds or only stores solar (182, 76) | +0.22 | +4.71 | +0.0029 | +0.0045 | +0.0000 | +0.0250 | -0.0049 | +0.0000 |
| `discharge_off_plan`: discharged when the strategy does not (41, 31) | +0.17 | +2.76 | +0.0023 | +0.0030 | +0.0000 | +0.0199 | -0.0001 | +0.0000 |
| `dhw_used`: used the hot water tank (the strategy leaves it at 0) (25, 12) | +0.26 | +3.87 | +0.0031 | +0.0035 | +0.0000 | +0.0020 | +0.0000 | +0.0000 |
| `small`: differed from the strategy by less than the 0.10.0 class tolerances (2875, 722) | -0.00 | -0.00 | -0.0000 | -0.0000 | +0.0000 | +0.0001 | +0.0000 | +0.0000 |
| **Every departure** | +6.27 | +53.52 | +0.0729 | +0.0444 | +0.0554 | +0.0714 | +0.0906 | +0.1555 |
- **What made money for Sonnet:** off-plan grid charging (-$1.81) and skipped or cut shaves (-$1.22), then extra charging in charging hours (-$0.19), deeper trims (-$0.16) and three classes under $0.05.
- **Both large gains cost elsewhere.** The off-plan charging added 10.34 kg (+0.0109 emissions). The skipped shaves added 0.2043 to the all-time peak, 0.0747 to the daily peak and 0.1014 to ramping.
- **What lost money for Sonnet:** trims not started (+$2.18, and +0.0148 discomfort, more than its whole +0.0133), the hot water tank (+$0.46), pre-cooling (+$0.14), off-plan discharges (+$0.07), short top-price discharges (+$0.05), shallower trims (+$0.04) and extra cooling (+$0.02).
- **The classes do not add up to the whole.** Sonnet's classes sum to -$0.48 while every departure together costs +$2.32. Each class is measured with all the other departures in place, and the battery classes share the same charge.
- **For Haiku**, trims not started (+$3.59, +0.0538 discomfort) and short top-price discharges (+$1.99) lost the most. Five classes made a little: skipped shaves (-$0.09, with +0.1793 on the all-time peak), deeper trims (-$0.04), less warm-room cooling (-$0.04), more top-price discharge (-$0.02) and unwanted trims (-$0.01).
- **The month in dollars** (CityLearn's hourly cost summed over the buildings): v9 scripted $75.86 and 1,038.7 kg, Sonnet v11 $78.18 and 1,084.9 kg, Haiku v11 $82.13 and 1,092.2 kg.

**Spend:** $5.2905 in this release, $11.2096 of the $15.00 cap across 0.13.0 and 0.14.0. The 24 hour smoke test was $0.1620 (a month estimated at $5.02), the Sonnet pilot $4.8587 and the Haiku control $0.2698.
- **Per call:** Sonnet averaged 2,352 uncached input tokens, 2,144 cached and 162 output; Haiku 2,351, 2,141 and 213. The cache hit rate was 48 percent for both.
- **Replays:** all three runs replay every hour with 0 API calls (24, 743 and 743).

### Version 0.15.0: rules in words

**Question:** is the value of the v9 strategy in the rules themselves, or in working them out in code? **On the one month tested, mostly in the rules, but not all of it.** Given the rules in words, Haiku closed 89 percent of the cost gap between no rules and rules computed in code. The remaining 0.008264 of `cost_total`, and most of the ramping gain, needed the computation.

**Read this first.** The holdout is spent (scored once in 0.12.0), so this runs on tuning July again, a month the strategy's numbers were chosen on. That favors the strategy. Haiku only, one run per prompt, one month.

**Prompt version 12, rules in words** (selectable with `--prompt-version 12`; version 9 stays the default):
- **The observation:** exactly version 11's. No suggestion and no strategy action: the model has to work the actions out itself.
- **The system prompt:** version 11's, every character of it, plus the version 10 strategy section: the three numbered rules word for word with their `StrategyParamsV9` numbers, under a heading that tells the model to apply the strategy every hour. No free mode paragraph and no `deviation_reason`.
- **The reply:** the envelope's standard schema with `end_trim`.
- **The shadow strategy:** logged every hour exactly as in version 11, never sent. Scripted version 12 sends it and matches scripted v9 action for action.
- **What stays the same:** the envelope, its rules and every limit, the v9 strategy and every tuned number. Versions 1 to 11 are unchanged, and every recorded run still replays.

**The three runs compared**, all on tuning July: Haiku v11 (no rules, the 0.14.0 run), Haiku v12 (rules in words, new) and Haiku v9 (the default prompt, rules worked out in code and shown as `strategy`, new), each scored against v9 scripted.

**The readings**, written into the CHANGELOG and committed before any code change or live call, on `cost_total` against v9 scripted: Haiku v12 within 0.002 of Haiku v9 means the rules in words carry the value; Haiku v12 closer to Haiku v11 than to Haiku v9 means Haiku cannot carry out the rules from words; anything between means the words carry part of it, and the gap is what the computation adds.

**Result: the third reading applies.** Haiku v12 is +0.008020 against v9 scripted, Haiku v9 -0.000244 and Haiku v11 +0.072852. Haiku v12 is 0.008264 from Haiku v9 (more than 0.002) and 0.064832 from Haiku v11, so it sits between them, much nearer Haiku v9. **On this month, the words carry most of the cost value, and the computation adds 0.008264.** Measured the same way on other KPIs (not part of the readings), the words closed 86 percent of the emissions gap, 72 percent of the all-time peak gap, 66 percent of the daily peak gap and only 12 percent of the ramping gap. Haiku v12 had less discomfort than both Haiku v9 and v9 scripted.

**The ladder, tuning July** (`hyperbolic months`; v9 scripted is not a model result):

| Controller | cost_total | carbon_emissions_total | discomfort_proportion | ramping_average | daily_peak_average | all_time_peak_average |
|---|---|---|---|---|---|---|
| baseline | 1.000000 | 1.000000 | 0.064481 | 1.000000 | 1.000000 | 1.000000 |
| Haiku v11 (no rules) | 0.992758 | 1.014709 | 0.062652 | 1.039499 | 0.975590 | 1.000024 |
| **Haiku v12 (rules in words)** | **0.927926** | **0.976172** | **0.006910** | **1.031187** | **0.916517** | **0.887329** |
| Haiku v9 (rules computed) | 0.919662 | 0.970061 | 0.007295 | 0.968514 | 0.886178 | 0.844480 |
| v9 scripted | 0.919906 | 0.970308 | 0.007295 | 0.968052 | 0.885031 | 0.844480 |

**Every KPI against v9 scripted:**

| CityLearn KPI (district) | Haiku v11 | Haiku v12 | Haiku v9 |
|---|---|---|---|
| cost_total | +0.072852 | +0.008020 | -0.000244 |
| carbon_emissions_total | +0.044401 | +0.005864 | -0.000247 |
| electricity_consumption_total | +0.042619 | +0.003725 | -0.000238 |
| discomfort_proportion | +0.055357 | -0.000385 | +0.000000 |
| too cool (discomfort_cold_proportion) | +0.053840 | -0.001372 | +0.000000 |
| too warm (discomfort_hot_proportion) | +0.001517 | +0.000987 | +0.000000 |
| ramping_average | +0.071447 | +0.063135 | +0.000462 |
| daily_peak_average | +0.090559 | +0.031486 | +0.001147 |
| all_time_peak_average | +0.155544 | +0.042849 | +0.000000 |
| daily_one_minus_load_factor_average | +0.024595 | +0.019634 | +0.001456 |
| power_outage_normalized_unserved_energy_total | +0.000000 | +0.000000 | +0.000000 |
| clamped hours (v9 scripted 10) | 63 | 83 | 10 |
| fallback hours | 0 | 0 | 0 |
| model cost | $0.2698 | $0.3739 | $0.3529 |

- **Haiku v12 against v9 scripted:** behind on cost (+0.008020), emissions (+0.005864), grid import (+0.003725), too warm (+0.000987), ramping (+0.063135), the daily peak (+0.031486), the all-time peak (+0.042849) and load factor (+0.019634). **Ahead on discomfort (0.006910 against 0.007295) and too cool (-0.001372).** Level on unserved energy (no outage on this month). Against Haiku v9 the wins and losses are the same.
- **Haiku v12 against the baseline:** ahead on cost (0.9279), emissions, grid import, discomfort (0.0069 against 0.0645), too cool, too warm, the daily peak (0.9165), the all-time peak (0.8873) and load factor. **Behind the baseline on ramping (1.0312).**
- **Haiku v12 against Haiku v11:** ahead on every KPI, level on unserved energy.
- **Haiku v9 against v9 scripted:** ahead on cost (-0.000244), emissions (-0.000247) and grid import (-0.000238); level on discomfort, too cool, too warm, the all-time peak and unserved energy; behind on ramping (+0.000462), the daily peak (+0.001147) and load factor (+0.001456). This run now stands in the 0.13.0 and 0.14.0 tables, in place of the 0.10.0 Haiku v8 live run that stood in before a Haiku v9 run existed on this month.
- **Clamps:** Haiku v12 was clamped in 83 hours (70 trim hold, 28 state of charge, 7 peak, 1 comfort), against 10 for Haiku v9 and v9 scripted. No reply in any of the three runs fell back, and the 24 hour smoke test had none either.

**Agreement with the v9 strategy** (`shadow_strategy`; within 0.002 for cooling and 0.005 for the tank and battery, `null` as `baseline_action`; 2,229 building-hours per run, no unusable replies):

| Device | Haiku v11 (no rules) | Haiku v12 (rules in words) |
|---|---|---|
| cooling | 64.3% (1,433) | 83.9% (1,871) |
| dhw | 98.9% (2,204) | 100.0% (2,229) |
| battery | 59.0% (1,314) | 64.0% (1,426) |
| all three at once | 38.3% (854) | 53.4% (1,191) |

**Attribution** (`scripts/analyze_free_mode.py`). Each departure from the shadow strategy is sorted into the 0.13.0 classes, put back to the strategy's action and the month resimulated with zero model calls; + means the departures made it worse. The control replay reproduces the run exactly, and putting every departure back reproduces v9 scripted exactly ($75.8602 and 1,038.712 kg). The logged shadow matches the strategy on all 743 recorded observations.

| Departures from the shadow strategy (building-hours, hours) | $ | kg CO2 | cost | emissions | discomfort | ramping | daily peak | all-time peak |
|---|---|---|---|---|---|---|---|---|
| `precool`: cooled above the strategy before the day's top-price hours (9, 9) | +0.01 | +0.10 | +0.0001 | +0.0001 | +0.0000 | +0.0001 | +0.0001 | +0.0000 |
| `trim_not_started`: no trim in an occupied, overcooled room where the strategy trims (152, 139) | +0.46 | +6.56 | +0.0048 | +0.0053 | +0.0020 | -0.0067 | +0.0006 | +0.0000 |
| `trim_shallower`: a shallower trim than the strategy's (77, 69) | +0.04 | +0.58 | +0.0005 | +0.0005 | +0.0000 | -0.0004 | +0.0000 | +0.0000 |
| `trim_deeper`: a deeper trim than the strategy's (113, 100) | -0.50 | -5.13 | -0.0052 | -0.0041 | -0.0033 | +0.0135 | +0.0030 | +0.0062 |
| `trim_unwanted`: a trim where the strategy has none (5, 5) | -0.03 | -0.38 | -0.0003 | -0.0003 | +0.0000 | +0.0025 | +0.0000 | +0.0000 |
| `trim_ended_early`: ended a held trim early with end_trim (3, 3) | +0.01 | +0.16 | +0.0001 | +0.0001 | +0.0000 | -0.0005 | +0.0000 | +0.0000 |
| `extra_cooling`: cooled above the strategy at any other time (2, 2) | +0.00 | +0.00 | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 |
| `warm_skipped`: less than the strategy's extra cooling in a warm room (26, 26) | -0.03 | -0.45 | -0.0004 | -0.0004 | +0.0010 | -0.0002 | +0.0000 | +0.0000 |
| `top_discharge_short`: discharged less than the strategy in a top-price hour (109, 44) | +0.90 | +0.39 | +0.0116 | +0.0003 | +0.0000 | -0.0173 | +0.0050 | +0.0000 |
| `top_discharge_over`: discharged more than the strategy in a top-price hour (56, 27) | +0.03 | +3.41 | +0.0012 | +0.0040 | +0.0000 | +0.0264 | +0.0009 | +0.0000 |
| `shave_skipped`: skipped or cut a peak-shaving discharge (84, 42) | -0.09 | +0.31 | -0.0014 | +0.0000 | +0.0000 | +0.0281 | +0.0421 | +0.0048 |
| `charge_skipped`: charged less than the strategy in a charging hour (210, 116) | -0.04 | -0.51 | -0.0004 | -0.0004 | +0.0000 | -0.0026 | -0.0030 | +0.0000 |
| `charge_over`: charged more than the strategy in a charging hour (21, 13) | +0.01 | +0.23 | +0.0001 | +0.0002 | +0.0000 | +0.0035 | -0.0004 | +0.0000 |
| `charge_off_plan`: charged when the strategy holds or only stores solar (309, 131) | -0.26 | +6.01 | -0.0033 | +0.0058 | +0.0000 | -0.0013 | -0.0072 | +0.0000 |
| `discharge_off_plan`: discharged when the strategy does not (24, 22) | +0.06 | +0.91 | +0.0007 | +0.0008 | +0.0000 | -0.0009 | +0.0000 | +0.0000 |
| `small`: differed from the strategy by less than the 0.10.0 class tolerances (2124, 523) | -0.02 | -0.17 | -0.0002 | -0.0001 | +0.0000 | -0.0001 | -0.0001 | +0.0000 |
| **Every departure** | +0.53 | +5.37 | +0.0080 | +0.0059 | -0.0004 | +0.0631 | +0.0315 | +0.0428 |

- **What lost money:** short top-price discharges (+$0.90) and trims not started (+$0.46, and +0.0020 discomfort), then off-plan discharges (+$0.06), shallower trims (+$0.04), more top-price discharge (+$0.03) and four classes at $0.01 or less.
- **What made money, and what it cost elsewhere:** deeper trims (-$0.50 and -0.0033 discomfort, but +0.0135 ramping and +0.0062 on the all-time peak), off-plan grid charging (-$0.26, but +6.01 kg) and skipped or cut shaves (-$0.09, but +0.0421 on the daily peak and +0.0281 ramping), then less charging (-$0.04), less warm-room cooling (-$0.03, with +0.0010 discomfort), unwanted trims (-$0.03) and `small` (-$0.02).
- **Ramping** (+0.0631 in all) comes mostly from skipped shaves (+0.0281), more top-price discharge (+0.0264) and deeper trims (+0.0135).
- **The classes do not add up to the whole** (+$0.55 summed, +$0.53 together): each class is measured with all its other departures in place.
- **The month in dollars** (CityLearn's hourly cost summed over the buildings): v9 scripted $75.86 and 1,038.7 kg, Haiku v12 $76.39 and 1,044.1 kg.

**Spend:** $0.7391 in this release, $11.9487 of the $15.00 cap across 0.13.0 to 0.15.0. The 24 hour smoke test was $0.0123, the Haiku v12 month $0.3739 and the Haiku v9 month $0.3529.
- **Per call:** Haiku v12 averaged 2,364 uncached input tokens, 2,590 cached and 482 output; Haiku v9 2,282, 2,476 and 443. The cache hit rate was 52.3 and 52.0 percent.
- **Replays:** all three runs replay every hour with 0 API calls (24, 743 and 743), and every earlier recorded run on disk (34) still replays.

The published viewer still shows the 0.10.0 phase 2 live run.

## What the agent sees

Prompt version 9 (`hyperbolic/prompt.py`) is the default from 0.11.0. Version 10 (0.13.0, free mode), version 11 (0.14.0, blind mode) and version 12 (0.15.0, rules in words) are experiments beside it, described in [Version 0.13.0](#version-0130-free-mode), [Version 0.14.0](#version-0140-blind-mode) and [Version 0.15.0](#version-0150-rules-in-words). Version 9 keeps everything in version 8 and:

- **Says to send every number of `strategy` exactly**: a battery -0.033 is not 0, and cooling under baseline_action is not `null`, with the trim state off too. The 0.10.0 live months left the batteries idle in skipped shaves and sent `null` in 415 of 416 missed trim starts.
- **Shows `peak.shave_now`**, the strategy's own test for a peak hour, and says to shave whenever it is true, after the top price and on flat_24h days too, with whatever charge is left. Version 8's "Before them discharge only to shave" and "Idle on flat_24h days" are gone.
- **Keeps 0.01 of charge above the floor through the top-price hours** (`StrategyParamsV9.evening_reserve`), so the evening shave has something to discharge.

Prompt version 8, the default in 0.10.0, keeps everything in version 7 and:

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

Nothing reads the dataset ahead of time; the outlook is built only from observations the controller has already received. Prompt versions 1 to 8 are kept unchanged so runs recorded with 0.2.0 to 0.10.0 replay byte for byte, and `--prompt-version 1` to `8` still selects them: 1 to 5 with the 0.7.0 envelope rules, 6 to 8 with the 0.8.0 rules that version 9 also uses.

## Tuning without peeking at the test month

From 0.6.0 there is a separate 2023 tuning set. `scripts/tuning_data` holds `citylearn_challenge_2023_phase_2_online_evaluation_1` from CityLearn v3.0.2, copied unchanged: the same three buildings, batteries and LSTM models as the reported month, but June, July and August of a different period, with its own weather, loads, solar, carbon intensity and tariff, and no hour in common with the reported month. (`citylearn_challenge_2023_phase_1` is byte for byte the reported month's data, so it is no use for tuning; online evaluation sets 2 and 3 differ from set 1 only in the outage seed.)

In 0.11.0, `python scripts/tune_strategy.py --version 9` searched charge kept for the evening shave (`StrategyParamsV9.evening_reserve`), the shave share and the grid charge rise on the four months of the month set, the phase 2 month included, under the acceptance rule written into the CHANGELOG first (see [Version 0.11.0](#version-0110)). The first pass of 36 settings passed none and a finer second pass of 8 passed one. The holdout ([HOLDOUT.md](HOLDOUT.md), Buildings 4 to 6 of `citylearn_challenge_2023_phase_3_1`) was sealed before the search and played no part: `months()` never lists it, and scoring it needs `--holdout-final`.

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
- Episode length: the full 719 hours. The 0.2.0 live run averaged about 4,700 characters per request and cost 0.23 USD on Haiku. Prompt version 2 adds the 24 hour outlook and the strategy, about 7,400 characters per request, and the 0.3.0 live Haiku month cost 0.39 USD. Prompt version 3 is about 8,600 characters per request; the 0.4.0 live Haiku month cost 0.47 USD, against a hard worst case of about 0.93 USD. Prompt version 4 adds the reference action, the price plan and the battery limits, about 9,650 characters per request: the 0.6.0 live Haiku month cost 0.57 USD, against a hard worst case of about 0.95 USD. Prompt version 5 adds the smoothing view, about 10,430 characters per request: the 0.7.0 live Haiku month cost 0.63 USD, against a hard worst case of about 0.97 USD and the default 2.00 USD budget. Prompt version 6 adds the trim hold and `end_trim`, about 10,930 characters per request (4.8 percent more): the 0.8.0 live Haiku month cost 0.53 USD (5,245 input and 429 output tokens per call), against a hard worst case of about 0.99 USD. Prompt version 7 shows the envelope's ranges and is 1.7 percent smaller, about 10,750 characters: the 0.9.0 live Haiku month cost 0.46 USD (5,185 input and 245 output tokens per call). Prompt version 8 shows the strategy's whole action and is 12.0 percent smaller again, about 9,460 characters: the 0.10.0 live Haiku months cost 0.41 to 0.43 USD, against a hard worst case of about 0.95 USD (0.98 USD for a 743 hour tuning month). Prompt version 9 adds the shave wording and `shave_now` and is 2.8 percent larger, about 9,720 characters: a Haiku month should cost about 0.42 to 0.44 USD, against a hard worst case of 0.96 to 0.99 USD. Sonnet costs 20 times as much per token: a full Sonnet month should cost roughly 11 to 13 USD, so under a 2.00 USD budget it stops calling the model after about a sixth of the month and the remaining hours use the baseline action. Raise `--budget` (about 14 USD) for a full Sonnet run. Each run logs its exact token cost in `result.json`.

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
| `hyperbolic run` | Runs the supervisor through the envelope. `--model sonnet`, `--budget 5`, `--hours 24` for a short run, `--month tuning-06`, `tuning-07` or `tuning-08` for a month of the tuning set instead of the phase 2 month (`phase2`, the default), `--scripted` for the 0.4.0 rule-based controller with no API calls (prompt version 3 and the 0.4.0 envelope), `--scripted --prompt-version 4` or `5` for the version 4 or 5 strategy executed literally, `--scripted --prompt-version 6` for the version 5 strategy with the 0.8.0 trim hold, `--scripted --prompt-version 7`, `8` or `9` for the version 7, 8 or 9 strategy kept inside the envelope's ranges, `--inject-faults` with `--scripted` to exercise clamps and fallback, `--prompt-version 1` to `8` for the 0.2.0, 0.3.0, 0.4.0, 0.6.0, 0.7.0, 0.8.0, 0.9.0 or 0.10.0 prompt. `--month holdout-06`, `holdout-07` or `holdout-08` records a run on the sealed holdout without printing its KPIs (see [HOLDOUT.md](HOLDOUT.md)). Runs of two days or more need hours + 1 to be a whole number of days (for example 167 or 719), a limit of CityLearn 3.0.2's outage model. |
| `hyperbolic months` | Runs the baseline, the 0.4.0 rule-based controller and the scripted v7, v8 and v9 strategies on every month of the month set (the phase 2 month and the three tuning months), in parallel with no model calls, and prints each KPI per month and the mean. `--controllers`, `--months`, `--run RUN` (repeatable) to show a finished run at the month it was recorded on, `--out` for JSON. `--holdout-final --months holdout-06 holdout-07 holdout-08` is the one final scoring of the sealed holdout, on its own; without the flag a holdout month or run is refused. |
| `hyperbolic replay RUN_DIR` | Re-runs a saved run from its files with zero model or simulator calls and reports whether every decision and action matches. Exit code 1 if not. |
| `hyperbolic compare` | Pairs the latest baseline (from `runs/` or the committed `results/`) with the latest agent run (a live run wins over a scripted one), prints the KPIs and writes the viewer data. `--pair BASELINE AGENT` to choose, `--out` to write the viewer data elsewhere, `--against RUN` (repeatable) to print another finished run of the same length beside them, for example the rule-based controller; the viewer data is unchanged. A pair on the holdout is refused without `--holdout-final`. |
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

`python -m pytest -q` runs fully offline. Envelope rules and runner logic run against a small fake district for speed; the backend, the CLI and the no-control equivalence run against real CityLearn on the shipped dataset; replay and the viewer builder run against CityLearn runs recorded in `tests/fixtures`. Covered: live mode through the real server with fake models (a full run streamed, recorded and replayed identically, the streamed hours matching the replay viewer's data, pause and resume, stop saving a partial run, the budget cap, the key never appearing in any response or file, the 127.0.0.1 binding and host checks, and the Claude options off without a key), the peak limiter (never above the target in randomized trials, trims recorded as clamps, battery before tank, off for older runs, and a CityLearn run that replays identically with its trims), the combined signal, the peak tracker, the reason length guard, the forecast horizons (6, 12 and 24 hours, the 0.2.0 mislabel), the 24 hour outlook never using unseen data, all eight prompt versions, `EnvelopeConfig` pinned field by field to 0.8.0 and the 0.8.0 and 0.9.0 live months replaying 719 of 719 hours when they are on disk, the deviation classes (every cooling, battery and tank class, the strategy's own reply having none, the tolerance, when each happened), the attribution replays (only the listed points replaced, the control reproducing a recorded CityLearn run exactly, a class put back moving the month toward the strategy, the gap shares), the version 8 observation (the strategy's whole action per building inside the ranges, the dropped fields), the version 8 prompt wording and request size, the warm-room cooling (the ramp, none in an outage, an empty room or with a trim held), the version 8 strategy equal to version 7's without a warm room, the night rule off, the scripted version 8 reply, version 8 runs on the fake district and 24 hours of CityLearn that replay identically, a full version 8 CityLearn month below the baseline's too-warm share, the version 8 search grid and rule, the month set (its months and lengths, a tuning month written as its own dataset, `run --month` recording its month and replaying, the rule-based controller reproducing its tuning month) and the compare report (means only over every month, partial runs marked), the version 7 observation (every trim state with `min_depth` and `end_trim_ok`, both ranges, `last_clamp`, the dropped fields), any value inside the version 7 ranges passing the envelope unclamped in randomized trials, a held trim left to `null` being clamped while the top of its range is not, the version 7 battery plan (version 5's with the shipped numbers, the soft cap winding a discharge down and leaving spare solar alone, valley filling), the version 7 prompt wording and request size, the scripted version 7 reply, version 7 runs on the fake district and 24 hours of CityLearn that replay identically and a full version 7 CityLearn month, the fitting evaluation and the version 7 search grid, the trim hold (on, hold, ease, release, end at the setpoint, in an empty room and with no baseline cooling, early end with a reason, the rounding allowance, logging, fallback, the deviation and comfort rules still first, off for older runs, and runs that replay byte for byte and detect changed hold settings), the version 6 prompt, observation, `end_trim` schema and request size, the scripted version 6 reply following `strategy_battery`, the viewer showing early ends, a 24 hour version 6 CityLearn run that replays identically and a full version 6 CityLearn month, the exact ramping split and the evaluation control reproducing a recorded CityLearn run, the version 4 reference action equal to what the rule-based controller replies, the version 5 smoothing view and strategy (trim hold, slow release, release at the setpoint, gentle charge start, even discharge), a full version 5 CityLearn month with ramping below the baseline, version 5 runs that replay byte for byte and detect a changed observation, the public page's How it works and Run it yourself sections, the spread check (blocked at the top price with its reason, allowed when the coming peak pays, never blocked by a flat weekend, standing losses, spare solar, off for older runs and the rule-based reference), the indoor temperature being the one CityLearn simulated, 24 hour and full-month rule-based dry runs on CityLearn (the full month must still score the 0.4.0 cost, emissions, daily peak, ramping and load factor), a 24 hour version 4 run on CityLearn that replays identically, recorded version 4 runs that replay byte for byte and detect a changed reference policy, a cooling offset moving indoor temperatures, every envelope rule, malformed and schema-breaking replies, fallback on invalid, missing and refused replies, the budget stop, key handling, deterministic replay and tamper detection, replay with CityLearn not even importable, and byte-identical viewer data from the same files in one process or two. From 0.11.0 also: the sealed holdout (its three months kept out of the month set, a schema with only Buildings 4 to 6, the seal matching `HOLDOUT.md` and failing on a changed or extra file, `months`, `compare`, `run_month` and recorded runs refusing it without `--holdout-final`, `run` on it printing no KPIs, and the baseline loading on it), the peak diagnosis (peak hours district and per building, the class ranking, version 8 deviation classes and `warm_skipped`, replays on their own month and never the holdout, a CityLearn run that never shaves), the version 9 acceptance rule case by case with its pick and grid, the version 9 observation, strategy, wording, request size and scripted reply, version 9 runs that replay on the fake district and on 24 hours of CityLearn, and the four 0.10.0 live months replaying hour for hour when they are on disk. From 0.13.0 also: prompt version 10 (the schema with a required `deviation_reason`, the suggestion equal to `strategy_plan_v9`, the fields it adds, what counts as a departure, a departure without a reason falling back, the envelope pinned by hash and versions 1 to 9 pinned by hash, deviations logged, replayed and shown, scripted version 10 equal to version 9 on CityLearn), the published Sonnet and Haiku prices, and `scripts/analyze_free_mode.py` (control reproducing a run, every departure put back equal to the strategy, a rejected hour staying rejected). From 0.14.0 also: prompt version 11 (the schema, no request naming "suggestion", "strategy" or `deviation_reason`, every number in the system prompt traced to something other than the strategy and the prompt unchanged when `StrategyParamsV9` changes, the observation equal to version 10's without the suggestion, `shadow_strategy` equal to `strategy_plan_v9` every hour and checked on replay, scripted version 11 equal to version 9 on the fake district and on CityLearn, the version 10 prompt and schema pinned by hash, the 0.13.0 runs replaying) and the blind-mode analysis (agreement per device, a changed shadow log caught, the control and the every-departure replay on CityLearn). From 0.15.0 also: prompt version 12 (the schema, the prompt equal to version 11's plus the strategy section, the three rules word for word version 10's with every `StrategyParamsV9` number, no request carrying a suggestion, a strategy field or the shadow, the observation equal to version 11's, `shadow_strategy` equal to `strategy_plan_v9` every hour and checked on replay, scripted version 12 equal to version 9 on the fake district and on CityLearn, the version 11 prompt and schema pinned by hash, every recorded run on disk replaying) and the analysis of a version 12 run (read as a blind-mode run, the control and the every-departure replay on CityLearn).

CI (GitHub Actions) runs the tests on Python 3.10 and 3.12 with CPU-only torch, a repository rules check, and an author check that fails if any commit in a push or pull request was not authored by AddisonTech.

## Honest limits

- **Simulator only.** CityLearn models buildings with data-driven load profiles and an LSTM for indoor temperature. Beating its reference is evidence worth investigating, not proof of field savings.
- **The rule-based check is not a model result.** It shows the action path can beat the reference and sets the bar for the agent. In 0.3.0 the live agent beat the baseline on cost only and did not beat the rule-based check. In 0.4.0 it beat the rule-based check on daily peak, ramping and load factor but not on cost or emissions. In 0.6.0 it beat it on every one of those. In 0.8.0 it beat it on every KPI except unserved energy in outages, by 0.0006. In 0.9.0 it beat or tied it on every KPI except hot-side discomfort, by 0.0005. In 0.10.0 it beat it on every KPI in every one of the four months of the month set, with unserved energy in outages tied. On the holdout (0.12.0) it beat it on every KPI in every month, with unserved energy tied at 0. From 0.6.0 the rule-based check is frozen at its 0.4.0 settings so the bar does not move.
- **The scripted version 4 and 5 strategies are not model results either.** They show that the strategy the agent is given beats the rule-based controller when followed literally. A live model reads the same strategy and may follow it more or less closely.
- **The peak limiter uses this hour's load.** It reads the draw CityLearn is about to simulate for this hour (plug load, solar, hot water demand, cooling), the equivalent of a meter reading in a real building. The forecast of the day's peak is built only from past days. The agent itself sees only the same values the limiter uses, never the rest of the day.
- **Ramping is a sum of rises, against CityLearn's own reference.** Smoothing that only spreads a rise over more hours does not lower it, which is why the trims are held rather than tapered. The denominator is built inside each run, so an agent's actions in an outage hour can move it (see [Version 0.8.0](#version-080)). The remaining up-ramp is mostly the baseline's own evening rise and the end of the top-price discharge.
- **The live agent does not carry a plan from hour to hour.** Each hour is a separate call. In 0.7.0 it was asked to hold cooling trims across hours and broke that in 142 of 237 trim ends (the scripted strategy: 4 of 167). From 0.8.0 the envelope holds them in code, and in the 0.8.0 live month it clamped the agent's cooling 345 times in 292 of 719 hours, 250 of them on `null` replies the prompt said would keep the trim. Version 7 shows the allowed range instead. In the 0.9.0 live month the agent sent `strategy_battery` in 2,150 of 2,157 building-hours but started almost none of the trims the strategy calls for, so version 8 shows the cooling as a number too. Its battery use is still the agent's own: in 0.7.0 that, not the trims, is what raised ramping above 0.6.0.
- **The 0.8.0 estimates were not live results.** The 0.7.0 replies sent through the 0.8.0 rules are fixed, so they cannot react to what the hold changed, and they do not include the version 6 prompt. The live month came in lower on ramping than that estimate (1.0076 against 1.0249); this release does not split how much of that is the hold and how much the prompt.
- **The 0.10.0 estimates are not live results.** They fill the version 8 strategy into the 0.9.0 live replies, which were written for the version 7 prompt and cannot react to what changed. The month set's scripted columns are not model results either. The live months that followed came in close to the scripted v8 strategy (mean cost 0.9122 against 0.9087).
- **The phase 2 month is no longer a clean holdout.** The warm-room cooling's outage exception and the selection rule were set after looking at it, so from 0.10.0 the three tuning months are the cleaner evidence. In 0.11.0 the version 9 search ran on all four months, so none of them is held out any more.
- **The holdout is the closest available, not a clean one.** Buildings 4 to 6 of phase 3 set 1 are new buildings (loads, occupancy, LSTM models, batteries, heat pumps) on the tuning months' weather, tariff and carbon intensity, so a good result there says the agent and strategy carry to other buildings, not to another climate or price structure. The seal keeps the project's tools from scoring it by accident; a run's `result.json` still holds its KPIs. The live months were run and scored on 2026-10-23 and published in 0.12.0, and no outage happened in any of them, so the holdout does not test outage handling.
- **On the holdout the agent adds nothing measurable over its strategy.** Haiku v9 is within 0.0006 of v9 scripted on every KPI in every month and slightly behind it on mean cost, emissions and the all-time peak. The holdout result is evidence that the strategy carries to new buildings and that the agent follows it, not that the model improves on it.
- **The version 9 strategy's gain is small and came from a second pass.** It lowers the four-month all-time peak by 0.003 and ramping by 0.0016 for 0.0006 of cost, and the passing setting was found in a finer grid added after the first found none. The holdout is where that should be checked.
- **Free mode was tested on one month the strategy was tuned on.** The holdout is spent, so 0.13.0 ran on tuning July, which favors the strategy. The budget cut the confirmation from three months to one, and the pilot's failure meant even that month was not run. Sonnet chose not to depart, and Haiku's departures lost money, mostly through 159 hours its replies were rejected for departing without a reason. That says the rule cost Haiku more than the freedom gained it, on this month, not that no model could find savings.
- **Blind mode was tested on one month the strategy was tuned on.** 0.14.0 ran on tuning July too, which favors the strategy, with one Sonnet run and one Haiku run. It says that on this month, without the rules, Sonnet did not find what they carry; it does not say no prompt or model could. The observation still holds `peak.shave_now`, which the strategy's shave share decides, so the model was not blind to every trace of the strategy.
- **Rules in words was tested on one month the strategy was tuned on, with Haiku only.** 0.15.0 is one Haiku v12 run and one Haiku v9 run on tuning July, which favors the strategy. Its 89 percent is one month's `cost_total`, one run each; run-to-run spread was not measured, and it says nothing about other models.
- **The 0.11.0 estimates are not live results.** v9 scripted is the strategy run literally, and the replays send the 0.10.0 live replies again with classes put back; whether Haiku shaves after the top price and starts trims under the version 9 wording can only be measured live.
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

CityLearn is developed by the Intelligent Environments Laboratory and contributors and is distributed under the MIT license. The dataset in `hyperbolic/data/citylearn_challenge_2023_phase_2_local_evaluation` is copied unchanged from the CityLearn repository (tag v3.0.2); its license is in `hyperbolic/data/CITYLEARN_LICENSE.txt`. The tuning dataset in `scripts/tuning_data/citylearn_challenge_2023_phase_2_online_evaluation_1` and the holdout dataset in `holdout/citylearn_challenge_2023_phase_3_1` are copied unchanged from the same repository and tag, under the same license. Hyperbolic is not affiliated with the CityLearn project.
