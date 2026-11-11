# Holdout results


**The one final scoring of the sealed holdout** ([HOLDOUT.md](../HOLDOUT.md)): Buildings 4, 5 and 6 of `citylearn_challenge_2023_phase_3_1`, June (719 hours), July (743) and August (743), each its own episode. No strategy setting or prompt was shaped on these buildings; their weather, tariff and carbon intensity are the tuning months'. Prompt version 9 and the 0.11.0 envelope ran exactly as shipped, with `claude-haiku-5-5` and a $2.00 budget per month. The seal check passed before scoring: all 16 holdout files match the sha256 hashes in HOLDOUT.md and there is no extra file. Everything below comes from `hyperbolic months --holdout-final`.

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

The published viewer shows the 0.15.0 Haiku v9 run on tuning July, not a holdout month (see [Version 0.15.0](HISTORY.md#version-0150-rules-in-words)).
