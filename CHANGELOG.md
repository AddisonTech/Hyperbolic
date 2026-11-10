# Changelog

## 0.15.0 (2026-11-10)

Question: is the value of the v9 strategy in the rules themselves, or in working them out in code? Prompt version 12 ("rules in words") is the version 11 observation, with no suggestion, and the version 11 system prompt plus the version 10 strategy section (the three numbered rules with their `StrategyParamsV9` numbers), worded as an instruction to apply that strategy every hour. Haiku only. The v9 strategy, the envelope and every tuned number are unchanged. Nothing runs on the holdout.

**Runs, all on tuning July (`tuning-07`):** Haiku (`claude-haiku-5-5`) v11 (blind, done in 0.14.0), Haiku v12 (rules in words, new), Haiku v9 (rules worked out in code and shown as `strategy`, new), and v9 scripted.

**How the result is read, pre-registered, written before any code change or live call and not changed after.** Each run's `cost_total` is taken against v9 scripted's on the same month, at CityLearn's six decimals:
- **Haiku v12 within 0.002 of Haiku v9:** the rules in words carry the value, and computing them in code adds nothing measurable for this model.
- **Haiku v12 closer to Haiku v11 than to Haiku v9:** Haiku cannot carry out the rules from words; the value needs the computation.
- **Anything between:** the words carry part of it, and the gap is what the computation adds.
- A result none of the three covers (for example Haiku v12 more than 0.002 below Haiku v9) is reported as covered by no reading, with its numbers.

**Agreement** with `shadow_strategy` per device is reported for Haiku v11 and Haiku v12, the same measure as 0.14.0: the share of building-hours where the model's action is within 0.002 (cooling) or 0.005 (tank and battery) of the v9 strategy's action for the same state, `null` counting as `baseline_action` on either side, an `end_trim` counting as a cooling disagreement, and unusable replies left out and counted separately.

**Order of work, in git:**
- **59606fb (15:54:19 EST):** the readings above.
- **325286d (15:58:44 EST):** the version 12 build and its tests.
- **The smoke test:** started at 15:58:57 EST, 13 seconds after the build commit.
- **Haiku v12 and Haiku v9 months:** both started at 16:00:24 EST, side by side, after checking that the running total plus both budgets ($11.2219 + $0.75 + $0.75 = $12.72) stayed under $15.00.

**Smoke test:** 24 hours of tuning July, Haiku v12, $0.0123. 24 of 24 replies were usable and none fell back (the stop line was more than 2), so the month ran on its planned $0.75.

**Result: the third reading applies.** `cost_total` on tuning July, against v9 scripted (0.919906), at six decimals:
- **Haiku v11 (no rules, 0.14.0):** 0.992758, +0.072852.
- **Haiku v12 (rules in words):** 0.927926, +0.008020.
- **Haiku v9 (rules worked out in code):** 0.919662, -0.000244.

Haiku v12 is 0.008264 from Haiku v9, more than 0.002, so the first reading does not apply. It is 0.064832 from Haiku v11, so it is closer to Haiku v9 and the second does not apply either. **Anything between: the words carry part of it, and the gap is what the computation adds.** On this month the gap is 0.008264 of `cost_total`. Of the 0.073096 between Haiku v11 and Haiku v9, the words closed 0.064832 (89 percent). Measured the same way on other KPIs (not part of the readings), they closed 86 percent of the emissions gap, 72 percent of the all-time peak gap, 66 percent of the daily peak gap and 12 percent of the ramping gap, and more than all of the discomfort gap (Haiku v12 is below both).

The holdout is spent, and tuning July is a month the strategy's numbers were chosen on, which favors the strategy. Everything here is one run per prompt on one month.

**Swap in the 0.13.0 and 0.14.0 tables.** The 0.13.0 tables (README and this changelog) showed the 0.10.0 Haiku v8 live run as a stand-in because no Haiku v9 run existed on tuning July. That row is now the 0.15.0 Haiku v9 run, `Haiku v9 (0.15.0)`, and the README's line comparing Haiku v10 with it now compares against Haiku v9. The 0.14.0 tables had no stand-in row, so `Haiku v9 (0.15.0)` is added to each of them as a new row. No other number in either release changed.

**Agreement with the v9 strategy** (`shadow_strategy`, the same state every hour; 2,229 building-hours per run, no unusable replies in either):

| Device | Haiku v11 (no rules) | Haiku v12 (rules in words) |
|---|---|---|
| cooling (within 0.002) | 64.3% (1,433) | 83.9% (1,871) |
| dhw (within 0.005) | 98.9% (2,204) | 100.0% (2,229) |
| battery (within 0.005) | 59.0% (1,314) | 64.0% (1,426) |
| all three at once | 38.3% (854) | 53.4% (1,191) |

**The ladder, tuning July** (`hyperbolic months`; v9 scripted is not a model result):

| Controller | cost_total | carbon_emissions_total | discomfort_proportion | ramping_average | daily_peak_average | all_time_peak_average |
|---|---|---|---|---|---|---|
| baseline | 1.000000 | 1.000000 | 0.064481 | 1.000000 | 1.000000 | 1.000000 |
| Haiku v11 (no rules) | 0.992758 | 1.014709 | 0.062652 | 1.039499 | 0.975590 | 1.000024 |
| **Haiku v12 (rules in words)** | **0.927926** | **0.976172** | **0.006910** | **1.031187** | **0.916517** | **0.887329** |
| Haiku v9 (rules computed) | 0.919662 | 0.970061 | 0.007295 | 0.968514 | 0.886178 | 0.844480 |
| v9 scripted | 0.919906 | 0.970308 | 0.007295 | 0.968052 | 0.885031 | 0.844480 |

Every KPI against v9 scripted:

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
- **Haiku v12 against the baseline:** ahead on cost (0.9279), emissions (0.9762), grid import (0.9754), discomfort (0.0069 against 0.0645), too cool, too warm (0.0026 against 0.0031), the daily peak (0.9165), the all-time peak (0.8873) and load factor (0.9715). **Behind the baseline on ramping (1.0312).**
- **Haiku v12 against Haiku v11:** ahead on every KPI, level on unserved energy.
- **Haiku v9 against v9 scripted:** ahead on cost (-0.000244), emissions (-0.000247) and grid import (-0.000238); level on discomfort, too cool, too warm, the all-time peak and unserved energy; behind on ramping (+0.000462), the daily peak (+0.001147) and load factor (+0.001456).
- **Clamps:** Haiku v12 was clamped in 83 hours (70 trim hold, 28 state of charge, 7 peak, 1 comfort), against 10 for Haiku v9 and v9 scripted. No reply in any of the three runs fell back.
- **Haiku v12 never used the hot water tank** (100 percent dhw agreement).

**Attribution** (`scripts/analyze_free_mode.py`, now also for version 12 runs). Each departure from the shadow strategy is sorted into the 0.13.0 classes, put back to the strategy's action and the month resimulated with zero model calls. + means the departures made it worse. The control replay reproduces the run's KPIs exactly, and putting every departure back reproduces v9 scripted exactly ($75.8602 and 1,038.712 kg). The logged `shadow_strategy` matches the strategy worked out again on every recorded observation, all 743 hours. No replay had a fallback hour. (The script's process pool printed a `WinError 6` traceback from an idle worker as it shut down; all 19 replays had already returned, and the report is complete.)

Haiku v12 (tuning July):

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

- **What lost money:** short top-price discharges (+$0.90, +0.0116 cost), trims not started (+$0.46, and +0.0020 discomfort), off-plan discharges (+$0.06), shallower trims (+$0.04), more top-price discharge (+$0.03, with +0.0264 ramping and +3.41 kg) and four classes at $0.01 or less.
- **What made money, and what it cost elsewhere:** deeper trims (-$0.50, and -0.0033 discomfort, but +0.0135 ramping, +0.0030 daily peak and +0.0062 all-time peak), off-plan grid charging (-$0.26, but +6.01 kg), skipped or cut shaves (-$0.09, but +0.0421 daily peak, +0.0281 ramping and +0.0048 all-time peak), less charging (-$0.04), less warm-room cooling (-$0.03, and +0.0010 discomfort), unwanted trims (-$0.03) and `small` (-$0.02).
- **Ramping, the largest loss** (+0.0631 together), comes mostly from skipped shaves (+0.0281), more top-price discharge (+0.0264) and deeper trims (+0.0135); short top-price discharges and trims not started lowered it (-0.0173 and -0.0067).
- **The classes do not add up to the whole.** They sum to +$0.55 while every departure together costs +$0.53: each class is measured with all its other departures in place.
- **In dollars over the month** (CityLearn's hourly cost summed over the buildings): v9 scripted $75.86 and 1,038.7 kg, Haiku v12 $76.39 and 1,044.1 kg.

**Spend: $0.7391 for this release, $11.9487 of the $15.00 cap across 0.13.0 to 0.15.0.** Smoke test $0.0123, Haiku v12 month $0.3739, Haiku v9 month $0.3529. Per call, Haiku v12 averaged 2,364 uncached input tokens, 2,590 cached and 482 output (cache hit rate 52.3 percent); Haiku v9 2,282, 2,476 and 443 (52.0 percent). Every new run replays every hour with 0 API calls (24, 743, 743), and every earlier recorded run on disk (34) still replays.

Changes:

- **Prompt version 12, rules in words** (`--prompt-version 12`; the default stays 9):
  - **Observation:** exactly the version 11 observation, with no suggestion.
  - **System prompt:** the version 11 prompt, every character of it, plus the version 10 strategy section between what the agent sees and the actions. Its three numbered rules are word for word version 10's, with their `StrategyParamsV9` numbers; the heading "Strategy (suggestion already applies it)" becomes "Strategy (apply it every hour, in every building, to choose cooling, dhw and battery)". No free mode paragraph and no `deviation_reason`.
  - **Reply:** the envelope's standard schema with `end_trim`.
  - **Shadow strategy:** logged every hour exactly as in version 11, never sent, and checked on replay.
  - **Scripted:** scripted version 12 sends the shadow strategy and matches scripted v9 action for action.
- **`scripts/analyze_free_mode.py`:** version 12 runs are read like blind-mode runs, against their shadow strategy, with the agreement measure.
- **Unchanged:** the envelope (`envelope.py` byte for byte, pinned by hash), the v9 strategy and every tuned number. Versions 1 to 11 are unchanged; the version 11 system prompt and reply schema are pinned by hash.
- **The published viewer now shows this release's Haiku v9 run on tuning July** (prompt version 9, `cost_total` 0.919662) in place of the 0.10.0 phase 2 live run, against a new no-control baseline on tuning July committed in `results/baseline_tuning07`; the viewer builder now takes the dataset id and name from the run's manifest, and tests pin the published run and the label of a run off phase 2.
- **Tests:**
  - **Version 12:** the schema (the envelope's with `end_trim`, equal to version 11's), the prompt equal to version 11's plus the strategy section, the three rules word for word version 10's with every `StrategyParamsV9` number and following that class when it changes, no request containing "suggestion", `strategy_reason`, a `strategy` field, "shadow" or `deviation_reason`, the observation equal to version 11's, `shadow_strategy` equal to `strategy_plan_v9` every hour and checked on replay, scripted v12 equal to scripted v9 on the fake district and on 24 hours of CityLearn.
  - **Nothing earlier changes:** the envelope hash, the version 11 prompt and schema hashes, no earlier version logging a shadow but version 11, the fixture runs, and every recorded run on disk replaying hour for hour.
  - **The analysis script:** a version 12 run measured exactly as a version 11 run with the same replies, and on CityLearn the control reproducing a version 12 run and every departure put back equal to the strategy.

## 0.14.0 (2026-11-10)

Question: does Sonnet agree with the v9 rules on its own, or did it only defer to them in 0.13.0 because they were handed to it? Prompt version 11 ("blind mode") is the version 10 observation without the suggestion, and a system prompt with no strategy rules or numbers. Same month as 0.13.0, same envelope. The v9 strategy, the envelope and every tuned number are unchanged. Nothing runs on the holdout.

**Acceptance rule, written before any live call or code change and not changed after.** On tuning July (`tuning-07`), Sonnet (`claude-sonnet-5-5`, prompt version 11, blind) passes if its `cost_total` is below v9 scripted's, with `carbon_emissions_total`, `discomfort_proportion` and `discomfort_hot_proportion` each no more than 0.001 worse, and `daily_peak_average` and `all_time_peak_average` each no more than 0.005 worse. Values are CityLearn's, at its six decimals; worse means higher.

**How the result is read, pre-registered, whatever it is:**
- **Passes:** blind Sonnet found savings the rules miss.
- **Fails on cost by 0.002 or less, with agreement at 80 percent or more on every device:** Sonnet independently converged on the rules.
- **Fails by more than 0.002, or agreement under 80 percent on any device:** the rules carry knowledge Sonnet does not find on its own, and its 0.13.0 deference was justified.
- A result none of the three covers (for example cost below v9 scripted with another condition failed) is reported as covered by no reading, with its numbers.

**Agreement** is the share of building-hours where the model's action is within the 0.10.0 tolerances (0.002 for cooling, 0.005 for the tank and battery) of the v9 strategy's action for the same state (`shadow_strategy`, worked out in code every hour and never sent to the model). Measured per device (cooling, dhw, battery) on the model's own reply, `null` counting as `baseline_action` on either side, and an `end_trim` counting as a cooling disagreement (the strategy never ends a trim early). Overall agreement is the share of building-hours where all three devices agree. Building-hours whose reply was unusable (no reply, or one the envelope's parse rejected) are left out of the shares and counted separately.

**Order of work, in git:**
- **f304b45 (14:42:57 EST):** the rule and readings above.
- **e869285 (14:50:14 EST):** the version 11 build and its tests.
- **The smoke test:** started at 14:50:23 EST, 9 seconds after the build commit.
- **The Sonnet pilot:** started at 14:51:32 EST. **The Haiku control:** started at 15:16:50 EST.

**Smoke test:** 24 hours of tuning July, Sonnet v11, $0.1620. That puts a full month at about $5.02 (0.1620 / 24 x 743), under the $7.00 stop line, so the pilot ran on its planned $7.00 budget. The pilot then cost $4.8587.

**Pilot result: fails.** Sonnet v11 on tuning July, against v9 scripted on the same month, at six decimals:
- **cost_total:** 0.945797 against 0.919906, +0.025891. Not below: **fails**.
- **carbon_emissions_total:** +0.042139. More than +0.001: **fails**.
- **discomfort_proportion:** +0.013333. **Fails**.
- **discomfort_hot_proportion:** +0.000457. At most +0.001: passes.
- **daily_peak_average:** +0.074785. More than +0.005: **fails**.
- **all_time_peak_average:** +0.155544. **Fails**.

**Which pre-registered reading applies: the third.** It fails on cost by 0.025891, more than 0.002, and agreement is under 80 percent on two devices (cooling 68.9, battery 54.8). Either alone puts it in the third reading: the rules carry knowledge Sonnet does not find on its own, and its 0.13.0 deference was justified.

The holdout is spent, and tuning July is a month the strategy's numbers were chosen on, which favors the strategy.

**Agreement with the v9 strategy** (`shadow_strategy`, the same state every hour; 2,229 building-hours per run, no unusable replies in either):

| Device | Sonnet v11 | Haiku v11 |
|---|---|---|
| cooling (within 0.002) | 68.9% (1,535) | 64.3% (1,433) |
| dhw (within 0.005) | 97.3% (2,168) | 98.9% (2,204) |
| battery (within 0.005) | 54.8% (1,222) | 59.0% (1,314) |
| all three at once | 37.8% (842) | 38.3% (854) |

Tuning July, every controller (`hyperbolic months`; scripted rows are not model results):

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
- **Sonnet v11 against the baseline:** ahead on cost (0.9458), discomfort (0.0206 against 0.0645), too cool, too warm (0.0020 against 0.0031), the daily peak (0.9598) and load factor (0.9802). **Behind the baseline on emissions (1.0124), grid import (1.0107), ramping (1.0821) and the all-time peak (1.000024, the baseline's peak plus 0.000024).**
- **Haiku v11 against the baseline:** ahead on cost (0.9928), discomfort (0.0627 against 0.0645), too cool, the daily peak (0.9756) and load factor (0.9764); level on too warm. **Behind on emissions (1.0147), grid import (1.0143), ramping (1.0395) and the all-time peak (1.000024).**
- **Haiku v11 against Sonnet v11:** behind on cost, emissions, grid import, discomfort, too cool, too warm and the daily peak; ahead on ramping (1.0395 against 1.0821) and load factor (0.9764 against 0.9802); level on the all-time peak. Haiku v11 is behind Haiku v10 on every KPI except unserved energy.
- **Neither blind run had a fallback hour.** Every reply in both runs parsed; the clamps rose to 38 hours (Sonnet) and 63 (Haiku) against v9 scripted's 10.
- **What blind Sonnet did:** it kept cooling at the baseline in most hours, so it started no trim in 585 building-hours where the strategy trims, and it charged batteries in 258 building-hours where the strategy holds. It skipped or cut 163 building-hours of peak shaving, though the observation still carries `peak.shave_now`.
- **Did Sonnet pre-cool?** 26 building-hours in 25 hours are cooling above the strategy before the day's top-price hours, 0.074 above it on average. Its hourly reasons in those hours mostly say it keeps baseline cooling or cools a warm room; one reason in the whole month mentions pre-cooling. That class lost $0.14 and added 2.03 kg. Haiku did the same in 11 building-hours (+$0.05).

**Attribution** (`scripts/analyze_free_mode.py`, now also for blind mode). Each departure from the shadow strategy is sorted into the 0.13.0 classes, put back to the strategy's action and the month resimulated with zero model calls. + means the departures made it worse. Each control replay reproduces its run's KPIs exactly, and putting every departure back reproduces v9 scripted exactly ($75.8602 and 1,038.712 kg) on both runs. The logged `shadow_strategy` matches the strategy worked out again on every recorded observation, all 743 hours of each run.

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
- **What made money for Sonnet:** off-plan grid charging (-$1.81) and skipped or cut shaves (-$1.22), then extra charging (-$0.19), deeper trims (-$0.16) and three classes under $0.05. **Both large ones cost elsewhere:** the off-plan charging added 10.34 kg (+0.0109 emissions), and the skipped shaves added 0.2043 to the all-time peak, 0.0747 to the daily peak, 0.1014 to ramping and 5.46 kg.
- **What lost money for Sonnet:** trims not started (+$2.18, and +0.0148 discomfort, more than its whole +0.0133), the hot water tank (+$0.46), pre-cooling (+$0.14), off-plan discharges (+$0.07), short top-price discharges (+$0.05), shallower trims (+$0.04) and extra cooling (+$0.02).
- **The classes do not add up to the whole.** Sonnet's classes sum to -$0.48 while every departure together costs +$2.32: each class is measured with all its other departures in place, and the battery classes share the same charge.
- **For Haiku**, trims not started (+$3.59, +0.0538 discomfort) and short top-price discharges (+$1.99) lost the most. Five classes made a little: skipped shaves (-$0.09, with +0.1793 on the all-time peak), deeper trims (-$0.04), less warm-room cooling (-$0.04), more top-price discharge (-$0.02) and unwanted trims (-$0.01).
- **In dollars over the month** (CityLearn's hourly cost summed over the buildings): v9 scripted $75.86 and 1,038.7 kg, Sonnet v11 $78.18 and 1,084.9 kg, Haiku v11 $82.13 and 1,092.2 kg.

**Spend: $5.2905 for this release, $11.2096 of the $15.00 cap overall.** Smoke test $0.1620, Sonnet pilot $4.8587, Haiku control $0.2698 (run because the running total plus $1.50 stayed under $15.00). Per call, Sonnet averaged 2,352 uncached input tokens, 2,144 cached and 162 output; Haiku 2,351, 2,141 and 213. The cache hit rate was 48 percent for both. Every run replays every hour with 0 API calls (24, 743, 743), and every earlier recorded run on disk (31) still replays.

Changes:

- **Prompt version 11, blind mode** (`--prompt-version 11`; the default stays 9):
  - **Observation:** exactly the version 10 observation with `suggestion` and `suggestion_reason` removed. The solar forecast and the building ratings stay, and so does `peak.shave_now`, a true or false the strategy's own shave share (0.9 of the forecast peak) decides; the prompt names it without its threshold.
  - **System prompt:** the version 10 prompt without the free mode paragraph, the `deviation_reason` rules and the strategy section. It says plainly that `null` means `baseline_action`, and prints no strategy rule, threshold or `StrategyParamsV9` number; a test traces every number it prints to the envelope, the forecasts, the reply rules, the district or the dataset.
  - **Reply:** the envelope's standard schema with `end_trim`, no `deviation_reason`.
  - **Shadow strategy:** every hour the v9 strategy's reply for the same observation is worked out in code and logged in the step record as `shadow_strategy`. It is never sent, and replay checks it.
  - **Scripted:** scripted version 11 sends the shadow strategy and matches scripted v9 action for action.
- **`scripts/analyze_free_mode.py`:** blind-mode runs are measured against their shadow strategy, checked against the log, and get the agreement measure; free-mode runs are analyzed as before.
- **Unchanged:** the envelope (`envelope.py` byte for byte, pinned by hash), the v9 strategy and every tuned number. The system prompts and reply schemas of versions 1 to 10 are pinned by hash and unchanged. The published viewer still shows the 0.10.0 phase 2 run, and its data is unchanged.
- **Tests:**
  - **Version 11:** the schema, no request (system prompt, observation or schema) containing "suggestion", "strategy" or `deviation_reason` on any hour, no strategy number in the system prompt and the prompt unchanged when `StrategyParamsV9` changes, the observation equal to version 10's without the suggestion and independent of `StrategyParamsV9` except `peak.shave_now`, `shadow_strategy` equal to `strategy_plan_v9` exactly every hour, scripted v11 equal to scripted v9 on the fake district and on 24 hours of CityLearn, a changed shadow caught on replay.
  - **Nothing earlier changes:** the envelope hash, the version 10 prompt and schema hashes, scripted v10 still equal to v9, the fixture runs and the three 0.13.0 runs replaying.
  - **The analysis script:** the blind reference equal to the shadow, agreement per device (unusable replies left out, `end_trim` counted against cooling), a changed shadow log caught, and on CityLearn the control reproducing a blind run and every departure put back equal to the strategy.

## 0.13.0 (2026-11-10)

Question: given room to deviate from the v9 strategy, can a stronger model find savings the rules miss? Prompt version 10 ("free mode") shows the v9 strategy's action as a suggestion the model may depart from, with a short hypothesis for every departure. The envelope, its rules and every limit, the v9 strategy and every tuned number are unchanged. Nothing runs on the holdout.

**Acceptance rule, written before any live call and not changed after.** On the pilot month (tuning July, `tuning-07`), the free-mode model (`claude-sonnet-5-5`, prompt version 10) passes if its `cost_total` is below v9 scripted's on the same month, with `carbon_emissions_total`, `discomfort_proportion` and `discomfort_hot_proportion` (too warm) each no more than 0.001 worse than v9 scripted, and both peaks (`daily_peak_average` and `all_time_peak_average`) no more than 0.005 worse. Values are CityLearn's, at its six decimals; worse means higher. If the pilot fails the rule, the remaining months are not run.

**Order of work, in git:**
- **24d0b71 (12:13 EST):** the rule above.
- **5c76c18 (12:26:30 EST):** the version 10 build and its tests.
- **The pilot:** started at 12:26:43 EST, 13 seconds after the build commit.
- **The smoke test:** ran at 12:23 EST on the same code, before that commit.

**Budget change before the pilot.** The 24 hour smoke test (Sonnet v10, tuning July, $0.1794) put a full Sonnet month at $5.40 to $5.56, over the planned $5.00. The Sonnet pilot's budget was raised to $6.00. The confirmation after a passing pilot was cut from three months to one (phase 2 only), so the whole task stays under the $15.00 cap. Nothing else in the pilot changed.

**Pilot result: fails.** Sonnet v10 on tuning July, against v9 scripted on the same month, at six decimals:
- **cost_total:** 0.920084 against 0.919906, +0.000178. Not below: **fails**.
- **carbon_emissions_total:** +0.000201. At most +0.001: passes.
- **discomfort_proportion:** +0.000457. Passes.
- **discomfort_hot_proportion:** +0.000000. Passes.
- **daily_peak_average:** +0.000000. At most +0.005: passes.
- **all_time_peak_average:** +0.000000. Passes.

The remaining month (phase 2) was not run. The holdout is spent, and tuning July is a month the strategy's numbers were chosen on, which favors the strategy.

Tuning July, every controller (`hyperbolic months`; scripted rows are not model results; the Haiku v9 row is the 0.15.0 run on this month, which replaced the 0.10.0 Haiku v8 live run that stood in here before a Haiku v9 run existed):

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

- **Sonnet v10 made no reasoned departure in 743 hours.** Its only two departures were copying slips without a `deviation_reason`: in hour 541 the tank at 0.01 in Building_3, and in hour 594 Building_3 cooling 0.2628 against a suggested 0.262. Its reason in both hours said it was sending the suggestions unchanged. Both replies were rejected, and those hours ran the baseline action. In hour 594 that dropped Building_1's trim and put the room 2.17 C below its setpoint, one too-cool hour. Those two hours are its whole gap to v9 scripted.
- **Sonnet v10 beats the baseline on every KPI**, with unserved energy tied at 0. Against v9 scripted it is ahead only on load factor (-0.000214).
- **Haiku v10 had 159 rejected hours:** departures, mostly `null` where the suggestion trims or moves the battery, with no reason. Cost 0.9373 (+0.0174 on v9 scripted), discomfort 0.0170 (+0.0097). **Ramping 1.0239 is over the baseline.** It is ahead of v9 scripted on the daily peak (-0.0062) and load factor (-0.0112), and behind it on the all-time peak (+0.0043).
- **Neither model pre-cooled.** Haiku cooled above the suggestion once, in a rejected hour, with no reason.

**Attribution** (`scripts/analyze_free_mode.py`, new). Each class is put back to the suggestion and the month resimulated with zero model calls. + means the departures made it worse.
- **One difference from 0.11.0:** devices the model left at its suggestion take the replay's own suggestion. So putting every departure back reproduces v9 scripted exactly on both runs, and every control replay reproduces its run exactly.
- **A fix before reporting:** while running attribution on the pilot, the script's first version was found adding a placeholder reason to departures the run had rejected. That turned the run's fallbacks into valid replies in the class replays. It now keeps every recorded rejection, and a test covers it.

Sonnet v10:

| Departures (building-hours, hours, with a reason) | $ | kg CO2 | cost | emissions | discomfort | ramping | daily peak | all-time peak |
|---|---|---|---|---|---|---|---|---|
| `dhw_used`: used the hot water tank (the strategy leaves it at 0) (1, 1, 0) | +0.00 | +0.01 | +0.0000 | +0.0000 | +0.0000 | -0.0002 | +0.0000 | +0.0000 |
| `small`: differed from the suggestion by less than the 0.10.0 class tolerances (1, 1, 0) | +0.02 | +0.24 | +0.0002 | +0.0002 | +0.0005 | +0.0006 | +0.0000 | +0.0000 |
| **Every departure in a rejected hour** | +0.02 | +0.25 | +0.0002 | +0.0002 | +0.0005 | +0.0004 | +0.0000 | +0.0000 |
| **Every departure** | +0.02 | +0.25 | +0.0002 | +0.0002 | +0.0005 | +0.0004 | +0.0000 | +0.0000 |

Haiku v10:

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

- **The missing reasons lost the money:** Haiku's 159 rejected hours account for $1.50 of its $1.46 gap, and Sonnet's two for its whole $0.0171.
- **Nothing made money measurably.** Haiku's reasoned departures together came to +$0.0019.
- **Haiku's hypotheses** (31 building-hours of grid-charging arbitrage, each claiming a cost gain, many adding that the peak was unaffected) did not hold:
  - **Cost:** about even, not a gain.
  - **Emissions:** +1.16 kg.
  - **"Peak unaffected":** the peaks moved. Ramping got worse (+0.0049), and the daily peak (-0.0038) and all-time peak (-0.0308) came out lower, measured with the rejected hours still in place.
  - **Sonnet** stated no hypothesis.

**Spend: $5.9191 of $15.00.** Smoke test $0.1794, Sonnet pilot $5.3566, Haiku pilot $0.3831. Every run replays every hour with 0 API calls (24, 743, 743).

Changes:

- **Prompt version 10, free mode** (`--prompt-version 10`; the default stays 9):
  - **Observation:** the v9 strategy's action as `suggestion` with `suggestion_reason`, plus `solar_forecast` and each building's `cooling_power_kw`, battery `power_kw` and `loss_per_hour`, and tank `heater_efficiency`.
  - **Reply:** a required `deviation_reason` per building. `parse_reply_v10` strips it, hands the rest to the envelope's unchanged `parse_reply`, and rejects a reply that departs from a suggestion by more than 0.0005 without one.
  - **Logging and replay:** each hour's deviations go into the step record (free-mode runs only, so earlier records are unchanged), are checked on replay, and appear in the viewer's and the live page's reason cards.
  - **Scripted:** scripted version 10 sends the suggestion and matches scripted v9 action for action.
- **Pricing:** Sonnet 5.5 cache reads are priced at Anthropic's published $0.10 per million tokens, not $0.20. A test pins every rate.
- **`scripts/analyze_free_mode.py`:** classes, put-back replays, groups by rejected and reasoned departures, and the hypothesis check.
- **HOLDOUT.md** notes that the holdout was scored once.
- **Unchanged:** the envelope (`envelope.py` byte for byte, pinned by hash in a test), the v9 strategy and every tuned number. The system prompts and reply schemas of versions 1 to 9 are pinned by hash and unchanged. The published viewer still shows the 0.10.0 phase 2 run, and its data is unchanged.
- **Tests:**
  - **Version 10:** the schema, the suggestion equal to `strategy_plan_v9`, the fields added, what counts as a departure, a required and well-formed `deviation_reason`, the envelope and earlier versions unchanged, and runs that log, replay and show their deviations.
  - **Fallbacks and replays:** a missing reason falling back, scripted v10 equal to v9 on the fake district and on 24 hours of CityLearn, and the fixture runs replaying.
  - **The analysis script:** control reproducing a run, every departure put back equal to the strategy, the classes and claims, and a rejected hour staying rejected.

## 0.12.0 (2026-11-10)

Goal: publish the one final scoring of the sealed holdout (`HOLDOUT.md`): Buildings 4, 5 and 6 of `citylearn_challenge_2023_phase_3_1`, June, July and August, each its own episode, with prompt version 9 and the 0.11.0 envelope exactly as shipped. Nothing in the strategy, the prompt, the envelope or any tuned number changes in this release, and it makes no model calls.

**Seal check:** passed. All 16 files in `holdout/citylearn_challenge_2023_phase_3_1` match the sha256 hashes in `HOLDOUT.md` (the same table the code checks), with no extra file.

**When the live months ran.** The live months (`claude-haiku-5-5`, prompt version 9, $2.00 budget each) were each run once on 2026-10-23: `holdout-06` run 20261023T212209Z, `holdout-07` 20261023T215850Z, `holdout-08` 20261023T223522Z, between 17:22 and 19:11 EDT. That was after the 0.11.0 commits, and they were scored with `--holdout-final` that evening but not published until this release. The 0.11.0 entry's line that only the baseline had been run on the holdout was true when it was written. No holdout month has been run live a second time. The only code change since is prompt caching, which wraps the same system prompt text as a cached block and is off for these runs; `envelope.py` is unchanged and the shipped envelope equals each run's recorded envelope.

**Replay check:** every live month replays all its hours with 0 API calls (719 of 719, 743 of 743, 743 of 743), every rebuilt request matching the recorded request's sha256, and the replayed district KPIs equal the recorded ones. The baseline (run offline here; no recorded holdout baseline folder existed), the 0.4.0 rule-based controller and v9 scripted, run again with `hyperbolic months --holdout-final`, equal the 2026-10-23 scoring to six decimals.

Every holdout month (`hyperbolic months --holdout-final --run`; scripted rows are not model results):

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

- **Haiku v9 beats the baseline on every KPI in every holdout month**, with unserved energy in outages tied at 0. No KPI comes in over the baseline. Mean of three: cost 0.9231, emissions 0.9544, grid import 0.9564, discomfort 0.0279 against 0.1294, too warm 0.0007 against 0.0158, ramping 0.9696, daily peak 0.9141, all-time peak 0.8902, load factor 0.9671.
- **It beats the 0.4.0 rule-based controller on every KPI in every month**, with unserved energy tied at 0. The rule-based controller comes in over the baseline on ramping in every month (mean 1.0484), on grid import in every month (mean 1.0015), on discomfort and too cool in June (0.1826 against 0.1821, 0.1397 against 0.1392) and on the August all-time peak by 0.000002.
- **It does not beat the v9 scripted strategy overall.** Within 0.0006 of it on every KPI in every month. It trails on cost in all three months (mean 0.923059 against 0.922944), emissions in June and August (mean +0.000147), grid import in all three (mean +0.000148), the all-time peak in June (+0.000561) and July (+0.000307) with August tied (mean +0.000289), the daily peak in June (+0.000036), ramping in August (+0.000299), and by one clamped hour in July (11 against 10). It is ahead on ramping in June and July (mean 0.969573 against 0.969817), the daily peak in July and August (mean 0.914118 against 0.914147) and load factor in all three (mean 0.967139 against 0.967328). Discomfort, too cool, too warm and unserved energy are identical to six decimals.
- **The gap to the strategy is far smaller than in 0.10.0** (Haiku v8 against v8 scripted on the month set: mean cost +0.0035, mean all-time peak +0.0178; Haiku v9 against v9 scripted on the holdout: +0.0001 and +0.0003), on other buildings and another prompt, so not a like-for-like comparison.
- **No outage happened.** The outage model is on in the holdout schema, but no hour of the three episodes has an outage flag: unserved energy is 0 for every controller and thermal resilience is not scored.
- **Model cost:** 2,205 calls, 0 fallbacks, $1.5869 ($0.5187, $0.5351, $0.5331), each under its $2.00 cap and under $6.00 in all. Above the 0.11.0 estimate of $1.30 to $1.36: replies averaged 486 output tokens against 220 estimated (input 4,768 against 4,810).

Changes:

- README: a Holdout results section with the table and these statements, a pointer to it in the introduction, and two Honest limits updated (the holdout's run dates and missing outages; the agent adding nothing measurable over its strategy there).
- The published viewer is unchanged and still shows the 0.10.0 phase 2 live run.
- Version 0.12.0 (`pyproject.toml`, `hyperbolic/__init__.py`, `docs/assets/version.js`). No code, prompt, strategy, envelope or test changes.

## 0.11.0 (2026-10-23)

Goal: close the gap between the 0.10.0 live agent and its strategy on the all-time peak (July 0.8822 against scripted v8 0.8491, August 0.8940 against 0.8570) and the daily peak, bring August ramping (1.0157, the one KPI over the baseline) down, and set up a clean holdout that nothing in this release is tuned on. The envelope does not change. No live model calls are made for this release.

**The holdout** (`HOLDOUT.md`), chosen and sealed before any tuning: Buildings 4, 5 and 6 of `citylearn_challenge_2023_phase_3_1`, June, July and August. No dataset CityLearn v3.0.2 ships is both new and fully compatible; this is the closest, new in its buildings but on the tuning months' weather, tariff and carbon. `hyperbolic months` and `compare` refuse it without `--holdout-final`, and only the baseline was run on it.

**Acceptance rule for prompt version 9, written before any v9 result.** On the mean of the four months of the month set (phase 2, tuning June, July and August), each from `hyperbolic months` at CityLearn's six decimals, a v9 scripted candidate passes when, against v8 scripted:

- `all_time_peak_average` is lower and `ramping_average` is lower;
- `cost_total`, `carbon_emissions_total`, `discomfort_proportion` and `discomfort_hot_proportion` are each no more than 0.001 higher;
- `power_outage_normalized_unserved_energy_total` is not higher at all.

Among passing candidates the one with the lowest mean all-time peak plus mean ramping ships, ties going to the lower mean cost. If no candidate passes, nothing new ships: v8 stays the default strategy and this entry says so. The holdout plays no part.

**Where the 0.10.0 live peaks came from** (`scripts/analyze_peaks.py` on the four live months; every replay runs the month's own replies through the unchanged envelope on the month it was recorded on, and every control replay reproduces the published KPIs exactly). The all-time peak is one hour, the district's highest net draw of the month:

| Month | Haiku's all-time peak | Scripted v8's | What Haiku sent there |
|---|---|---|---|
| phase 2 | step 669 (day 28, 10 pm), 18.96 kWh (Building_1 8.00, Building_2 1.21, Building_3 9.75) | the same hour, 18.96 | the strategy's actions in that hour and the three before |
| June | step 669 (day 28, 10 pm), 15.10 | the same hour, 15.08 | the strategy's actions |
| July | step 739 (day 31, 8 pm), 12.98 (Building_3 10.83) | the same hour, 12.49 | battery 0 in all three buildings where the strategy shaved (-0.033, -0.033, -0.164) |
| August | step 450 (day 19, 7 pm), 13.80 (Building_1 9.29) | the same hour, 13.23 | an all-null reply where the strategy shaved (-0.033, -0.033, -0.219) and held two trims |

Each departure class put back to the strategy on its own (all-time peak, daily peak, ramping):

| Replay | phase 2 | June | July | August |
|---|---|---|---|---|
| Haiku live (control) | 0.9590, 0.9074, 0.9969 | 0.8549, 0.8919, 0.9802 | 0.8822, 0.8943, 0.9744 | 0.8940, 0.8896, 1.0157 |
| Scripted v8 | 0.9588, 0.9095, 0.9983 | 0.8541, 0.8830, 0.9732 | 0.8491, 0.8854, 0.9677 | 0.8570, 0.8861, 1.0100 |
| Skipped shaves put back | 0.9590, 0.9078, 0.9907 | 0.8549, 0.8871, 0.9771 | 0.8637, 0.8882, 0.9701 | 0.8570, 0.8881, 1.0138 |
| Missed trim starts put back | 0.9590, 0.9067, 1.0033 | 0.8549, 0.8858, 0.9812 | 0.8822, 0.8930, 0.9811 | 0.8940, 0.8851, 1.0229 |
| Skipped charges put back | 0.9590, 0.9074, 0.9952 | 0.8549, 0.8887, 0.9651 | 0.8822, 0.8945, 0.9693 | 0.8940, 0.8899, 1.0066 |
| Every departure put back | 0.9591, 0.9080, 0.9988 | 0.8549, 0.8842, 0.9632 | 0.8621, 0.8857, 0.9700 | 0.8569, 0.8849, 1.0156 |

Ranked by KPI points explained (live minus replay), summed over the four months:

| Class (building-hours over four months) | All-time peak | Daily peak | Ramping |
|---|---|---|---|
| `shave_skipped`: skipped or cut a peak-shaving discharge (35) | +0.0555 | +0.0120 | +0.0155 |
| `trim_shallower` (82) | +0.0006 | +0.0003 | -0.0010 |
| `trim_not_started`: no trim in an overcooled room where the strategy trims (416) | 0.0000 | +0.0126 | -0.0212 |
| `charge_skipped`: charged less than the strategy in a charging hour (82) | 0.0000 | +0.0026 | +0.0311 |
| `trim_deeper` (30) | 0.0000 | +0.0018 | -0.0014 |
| `top_discharge_short` (17) | -0.0001 | -0.0030 | -0.0040 |
| every other class | 0.0000 | at most 0.0010 either way | at most 0.0031 either way |

- **The all-time peak gap is skipped shaves.** Putting back 35 building-hours of skipped shaves (17 hours, a mean gap of 0.09 to 0.18 by month) takes August from 0.8940 to the strategy's 0.8570 and July from 0.8822 to 0.8637. 29 of the 35 came after the day's top-price hours and 8 of the 17 hours fell on a flat-price day. In 16 of the 17 the agent's reason says it followed the strategy while calling the batteries idle ("batteries idle-ish per flat price with peak limiter", "battery near idle as SoC low"). The version 8 prompt allowed that reading twice: "Before them discharge only to shave" and "Idle on flat_24h days", with no word that the strategy shaves after the top price and on flat days.
- **The daily peak gap** is the missed trim starts (+0.0126) and the skipped shaves (+0.0120). 415 of the 416 missed trim starts are `null` sent while the trim state was off (median 0.043 above the strategy's trim), the 0.9.0 habit version 8's wording did not end.
- **Ramping:** skipped charges add 0.0311 over the four months; the missed trim starts take 0.0212 off.
- `scripts/analyze_deviations.py` now reads version 8 runs: the strategy is the one the observation shows, replays run on the run's own month, and one class is new, `warm_skipped`.

**August ramping, split** (`scripts/split_ramping.py`, now on any month of the month set; points of `ramping_average` above 1.0, against a scripted v8 August recorded offline):

| Cause | Haiku v8 live (1.0157) | Scripted v8 (1.0100) | Agent minus strategy |
|---|---|---|---|
| Battery charging | +2.24 | +1.44 | +0.80 |
| Battery discharging | -1.13 | -1.58 | +0.45 |
| Trim start, end, depth | -2.95, +3.47, -0.09 | -2.40, +3.91, -0.39 | -0.69 |
| Extra cooling | +0.02 | +0.02 | 0.00 |
| Total | +1.57 | +1.00 | +0.57 |

1.00 of the 1.57 points is the strategy itself, mostly its trim ends (+3.91: the envelope ends a trim at once at the setpoint or when the room empties, and eases it by at most 0.02 an hour). The agent adds 0.57: 1.25 from its battery (uneven charging, skipped shaves) less 0.69 from the trims it did not start.

**The search** (`scripts/tune_strategy.py --version 9`, four months of the month set, scripted, the rule above applied as written). The diagnosis puts every all-time peak in an evening hour just after the top-price discharge, so the grid kept charge back through the top-price hours for that shave (`evening_reserve` 0 to 0.25), with the shave share (0.9, 0.8) and the grid charge rise (`charge_step` 0.15, 0.1, 0.05):

- **First pass, 36 settings: none passed.** The reserve works (0.05: all-time peak 0.8643 against 0.8797, ramping 0.9788 against 0.9873) but costs about 0.003 per 0.05 (0.9117 against 0.9087). A slower charge rise lowers ramping but raises cost and the all-time peak; a lower shave share raises cost.
- **Second pass, added after the first and reported here as such: 8 settings with smaller reserves** (0.01 to 0.04, `charge_step` 0.15 or 0.125). One passed: `evening_reserve` 0.01, everything else at version 8. On the four-month mean: all-time peak 0.876779 against 0.879746, ramping 0.985732 against 0.987321, cost +0.000596, emissions +0.000024, discomfort, too warm and outage energy unchanged to six decimals. It is lower on the all-time peak in every month and on ramping in three of four (July +0.0004). The same numbers come out of `hyperbolic months` with the shipped prompt version 9.
- How it works, at tuning July's peak hour: each battery comes out of the top-price hours with 0.009 more charge (0.243 against 0.234), the shave discharges it (-0.041 against -0.033), and the peak falls from 12.49 to 12.42 kWh.

Changes:

- **Prompt version 9 (default).** The strategy is version 8's with `evening_reserve` 0.01 (`StrategyParamsV9`, `strategy_plan_v9`). The observation adds `peak.shave_now`, the strategy's own test for a peak hour. The system prompt says to send every number exactly ("battery -0.033 is not 0, and cooling under baseline_action is not null, trim state off too"), to shave in any hour `shave_now` is true, after the top price and on flat_24h days too, with whatever charge is left, and to keep 0.01 above the floor in the top-price hours; "Before them discharge only to shave" and "Idle on flat_24h days" are gone. Version 8 stays selectable and its requests are unchanged byte for byte.
- **The holdout and its guard**: `HOLDOUT.md`, `holdout/citylearn_challenge_2023_phase_3_1` (copied unchanged), `hyperbolic months --holdout-final`, `hyperbolic compare --holdout-final`, a seal of file hashes checked before any scoring, `run --month holdout-06` (07, 08) recording without printing KPIs, and `months()` never listing it.
- **Tools.** `scripts/analyze_peaks.py` (peak hours, the model against its strategy there, class replays, the ranking). `scripts/analyze_deviations.py` reads version 8 runs and keeps each replay's hourly grid draw. `scripts/split_ramping.py` resimulates tuning months. `scripts/tune_strategy.py --version 9` with `accepts_v9`.
- `hyperbolic months` runs `v9` scripted too. `hyperbolic serve`'s first cost estimate uses the version 9 request size (4,810 input and 220 output tokens).
- Tests cover the holdout (its months, the schema with only its buildings, the seal and a broken seal, the guard in `months`, `compare`, `run_month` and recorded runs, `run` printing no KPIs, the baseline loading), the peak hours and ranking, version 8 deviation classes and `warm_skipped`, replays on their own month and never the holdout, a CityLearn run that never shaves, the acceptance rule case by case and the pick, the version 9 grid, the version 9 observation, strategy, wording, request size and scripted reply, version 9 runs that replay on the fake district and on 24 hours of CityLearn, and the four 0.10.0 live months replaying hour for hour when they are on disk.

**Estimates on the four months, no holdout** (scripted rows are not model results; the last two rows send the 0.10.0 live replies again with one or every class put back):

| Mean of four months | cost | emissions | discomfort | too warm | ramping | daily peak | all-time peak | load factor | outage |
|---|---|---|---|---|---|---|---|---|---|
| 0.4.0 rule-based | 0.9619 | 1.0002 | 0.1352 | 0.0188 | 1.0955 | 0.9847 | 0.9846 | 0.9851 | 0.1711 |
| v8 scripted | 0.9087 | 0.9582 | 0.0208 | 0.0059 | 0.9873 | 0.8910 | 0.8797 | 0.9549 | 0.1711 |
| **v9 scripted** | **0.9093** | **0.9582** | **0.0208** | **0.0059** | **0.9857** | **0.8898** | **0.8768** | **0.9540** | **0.1711** |
| Haiku v8 live (0.10.0) | 0.9122 | 0.9609 | 0.0241 | 0.0066 | 0.9918 | 0.8958 | 0.8975 | 0.9557 | 0.1711 |
| Haiku v8, skipped shaves put back | 0.9123 | 0.9608 | 0.0241 | 0.0066 | 0.9879 | 0.8928 | 0.8836 | 0.9535 | 0.1711 |
| Haiku v8, every departure put back | 0.9076 | 0.9567 | 0.0198 | 0.0057 | 0.9869 | 0.8907 | 0.8833 | 0.9551 | 0.1711 |

By month, v9 scripted: cost 0.9037, 0.9105, 0.9199, 0.9029; all-time peak 0.9586, 0.8516, 0.8445, 0.8524; ramping 0.9952, 0.9717, 0.9681, 1.0080 (August still above the baseline); clamped hours 22, 32, 10, 3, as v8.

- If Haiku shaves after the top price under the new wording, the July and August all-time peaks should come down to near the strategy's (estimated 0.8637 and 0.8570 from the shaves alone with the version 8 strategy). Only a live run can show whether it does.
- The v9 strategy's own gain is small: 0.003 on the all-time peak and 0.0016 on ramping for 0.0006 of cost. August ramping stays above 1.0 because of the trim ends the envelope fixes; this release does not change the envelope.

**Request size and cost.** Over the same scripted phase 2 month a version 9 request averages 9,716 characters against 9,456 for version 8, 2.8 percent larger: the system prompt is 3,886 characters against 3,645 and the observation 18 longer; the reply schema is unchanged. Scaled from the 0.10.0 live months (4,676 input and 215 output tokens per call), a Haiku month should cost about $0.42 for 719 hours and $0.44 for 743 ($0.44 and $0.46 if replies run 25 percent longer); the hard worst case is $0.96 and $0.99, under the $2.00 cap. All four months should cost about $1.72 to $1.80, and the three holdout months about $1.30 to $1.36.

The envelope is unchanged (`hyperbolic/envelope.py` is byte for byte 0.10.0's and `EnvelopeConfig` is still pinned to 0.8.0 by its test). The four 0.10.0 live months, the 0.9.0 and the 0.8.0 live months replay every hour (719, 719, 743, 743, 719, 719) with 0 API calls. No live model calls were made for this release, and nothing but the baseline has been run on the holdout.

## 0.10.0 (2026-10-23)

Goal: find and close the gap between the 0.9.0 live agent and its own strategy, fix the hot-side comfort miss, and score everything on more than one month. The envelope does not change. The analysis, strategy and estimates below were built before any live call; the live months on all four months of the set follow them.

Where the 0.9.0 live month (`runs/live/...20261023T135430Z`, cost 0.9245, discomfort 0.0940) left the scripted version 7 strategy (0.9016, 0.0430), from `scripts/analyze_deviations.py`: every hour, building and device against what `strategy_plan_v7` sends for the same observation, then the month's own replies replayed through the unchanged envelope with one class at a time put back to the strategy (the control replay reproduces the published KPIs exactly; shares are of the control to strategy gap):

| Class | Building-hours (hours) | Replay: cost, emissions, discomfort, ramping | Share of cost, discomfort gap |
|---|---|---|---|
| No trim in an occupied, overcooled room, trim state off | 584 (418) | 0.8920, 0.9337, 0.0417, 1.0051 | 1.42, 1.03 |
| Deeper trim than the strategy's | 100 (83) | 0.9273, 0.9676, 0.0936, 0.9805 | -0.12, 0.01 |
| Trim where the strategy has none | 19 (18) | 0.9245, 0.9647, 0.0903, 0.9879 | 0.00, 0.07 |
| Shallower trim | 11 (11) | 0.9243, 0.9646, 0.0940, 0.9876 | 0.01, 0.00 |
| Extra cooling 5 (5), trim ended early 3 (3) | 8 | no change to four decimals | 0.00, 0.00 |
| Battery: top-price over-discharge 3 (1), charged off plan 3 (2), skipped charge 1 (1) | 7 | no change to four decimals on cost, emissions, discomfort | 0.00, 0.00 |
| All classes at once | 729 | 0.8977, 0.9393, 0.0435, 0.9977 | 1.17, 0.99 |

- **The missed trim starts are the gap.** All occupied; Building_1 353, Building_3 201, Building_2 30; the room 0.5 to 1 C below its setpoint in 188, 1 to 1.5 C in 147, further in 249; low price 181, mid 166, flat 144, top 93; outdoor 30 C or more in 272; battery state of charge below 0.3 in 274. The agent's reasons ("overcooled but trim off so baseline cooling kept") show it read the version 7 line that `null` is for "only when trim state is off or end" as "send null when the trim is off". Battery and tank: `strategy_battery` was sent in 2,150 of 2,157 building-hours and the tank was never used.
- **The agent's own deeper trims helped cost** (putting them back raises cost to 0.9273) and hurt ramping (0.9805 without them).

The hot-side miss (0.0181 against the baseline's 0.0176) is one building-hour: Building_1 at hour 404 (day 17, 9 pm), 28.77 C against a band top of 28.67 C (baseline 28.54 C); Building_2 and Building_3 match the baseline exactly. Building_1 trimmed cooling for most of day 16's afternoon and evening under a 27.2 C setpoint (at the 0.15 cap from 2 pm to 8 pm, deepened by the agent where the strategy keeps about 0.10), ended the evening at 27.6 C against 25.1 C and stayed about 1 C warmer overnight, and a 15 hour outage on day 17 then carried it over the band. The scripted version 7 strategy has the same miss at the same hour, and its 6 extra warm hours on the tuning months all come between 6 and 11 am in a room trimmed within the day and a half before. A trim brings an overcooled room up to its setpoint, without the baseline's cushion of about 2 C.

Changes:

- **Prompt version 8 (default).** Each building shows `strategy` (`cooling`, `dhw`, `battery` from `strategy_plan_v8`, inside the envelope's ranges) with `strategy_reason`, in place of `strategy_battery` and `strategy_battery_reason`; the agent is told to send it as given. The prompt says a trim starts when an overcooled room's state is off and that a held trim is a number, never `null`; the version 7 line about `null` and the trim state is gone. `signal_outlook` is dropped, and the prompt names no single dataset. Version 7 stays selectable; the 0.9.0 and 0.8.0 live months, the rule-based run and the committed baseline replay 719 of 719 hours.
- **Warm-room cooling** in the strategy (`StrategyParamsV8`): an occupied room with no trim held gets from 0 at 1.5 C above its setpoint to 0.05 above the baseline action at 2.5 C or more, within `cooling_range`, never in an outage. Searched on the tuning months (`scripts/tune_strategy.py --version 8`, 36 settings: margin 0.5, 1 or 1.5 C, boost 0.05, 0.1 or 0.15, at once or ramped over 1 C, and a no-trim night from 18, 20 or 22 h to 5 or 7 h, alone and together). A first rule (too warm at or below the baseline on every tuning month, and cost, emissions, too cool, ramping and both peaks within 0.001 of version 7) qualified none: the cheapest full fix costs about 0.002 of cost. The shipped rule puts comfort first, as the prompt's goals do: too warm at or below the baseline on every tuning month, too cool within 0.001 of version 7, ramping and both peaks at or below the baseline, then the lowest cost plus emissions. 5 qualified. Tuning-set means, shipped against version 7: cost 0.9105 against 0.9086, emissions 0.9627 against 0.9607, too cool 0.0112 against 0.0111, too warm 0.0040 against 0.0201 (baseline 0.0191), ramping 0.9836 against 0.9823. The night rule cleared no warm hour and raised cost by 0.007 to 0.024 (`night_from_hour` stays 0). The outage exception was added after the phase 2 month showed extra cooling in outage hours raising unserved energy (0.6942 against 0.6844); the tuning months have no outages, so it changes nothing there.
- **The month set** (`hyperbolic/months.py`): the phase 2 month and every month of the tuning set kept locally (June 719 hours, July and August 743), each its own episode. `hyperbolic months` runs the baseline, the frozen 0.4.0 rule-based controller and the scripted v7 and v8 strategies on every month in parallel and prints each KPI per month and the mean (`--run` adds a finished run at its month; a mean is shown only over every month). `hyperbolic run --month` and `hyperbolic baseline --month` run any month; the manifest records its dataset, its month and its length, and the run folder is named after it. `scripts/tune_strategy.py` writes its months through the same code.
- **Tools.** `scripts/analyze_deviations.py`: the deviation classes with when they happened, the one-class-at-a-time replays, and estimates with the version 8 strategy filled in (`ReplacingSupervisor`). These are evaluations, never recorded runs.
- `hyperbolic serve`'s first cost estimate uses the version 8 request size (4,560 input and 260 output tokens).
- Tests cover the deviation classes, the attribution replays on a recorded CityLearn run, the version 8 observation, prompt, request size, warm-room cooling and scripted reply, version 8 runs that replay identically, a full version 8 CityLearn month, the version 8 grid and rule, the month set, `run --month`, the compare report, and the 0.9.0 live month replaying 719 of 719 hours when it is on disk.

Every month, offline (scripted columns are not model results):

| KPI | | phase 2 | June | July | August | mean |
|---|---|---|---|---|---|---|
| cost_total | rule 0.4.0 | 0.9611 | 0.9506 | 0.9676 | 0.9682 | 0.9619 |
| | v7 scripted | 0.9016 | 0.9050 | 0.9186 | 0.9021 | 0.9068 |
| | v8 scripted | 0.9031 | 0.9099 | 0.9193 | 0.9023 | 0.9087 |
| carbon_emissions_total | rule 0.4.0 | 0.9947 | 1.0001 | 1.0038 | 1.0024 | 1.0002 |
| | v7 scripted | 0.9429 | 0.9603 | 0.9696 | 0.9521 | 0.9562 |
| | v8 scripted | 0.9447 | 0.9654 | 0.9703 | 0.9524 | 0.9582 |
| discomfort_proportion | baseline, rule | 0.1714 | 0.1128 | 0.0645 | 0.1919 | 0.1352 |
| | v7 scripted | 0.0430 | 0.0610 | 0.0093 | 0.0232 | 0.0341 |
| | v8 scripted | 0.0374 | 0.0174 | 0.0073 | 0.0210 | 0.0208 |
| too warm | baseline, rule | 0.0176 | 0.0526 | 0.0031 | 0.0017 | 0.0188 |
| | v7 scripted | 0.0181 | 0.0545 | 0.0036 | 0.0022 | 0.0196 |
| | v8 scripted | 0.0116 | 0.0104 | 0.0016 | 0.0000 | 0.0059 |
| ramping_average | rule 0.4.0 | 1.1309 | 1.0742 | 1.0922 | 1.0848 | 1.0955 |
| | v7 scripted | 0.9952 | 0.9708 | 0.9666 | 1.0095 | 0.9855 |
| | v8 scripted | 0.9983 | 0.9732 | 0.9677 | 1.0100 | 0.9873 |
| daily_peak_average | rule 0.4.0 | 0.9978 | 0.9934 | 0.9743 | 0.9734 | 0.9847 |
| | v7 scripted | 0.9076 | 0.8806 | 0.8846 | 0.8858 | 0.8897 |
| | v8 scripted | 0.9095 | 0.8830 | 0.8854 | 0.8861 | 0.8910 |
| all_time_peak_average | rule 0.4.0 | 1.0000 | 1.0000 | 1.0000 | 0.9383 | 0.9846 |
| | v7 scripted | 0.9588 | 0.8518 | 0.8491 | 0.8570 | 0.8792 |
| | v8 scripted | 0.9588 | 0.8541 | 0.8491 | 0.8570 | 0.8797 |
| unserved energy in outages | all | 0.6844 | 0 | 0 | 0 | 0.1711 |
| clamped hours | v7, v8 | 22, 22 | 31, 32 | 9, 10 | 3, 3 | 16.2, 16.8 |

- Scripted v8 has fewer too-warm hours than the baseline on every month, where v7 has more on every month, and less discomfort than v7 on every month, for a little cost and emissions. The rule-based and v7 columns reproduce their published numbers exactly.

Estimates for a live v8 month (the 0.9.0 live replies with the version 8 strategy filled in): trims started where the agent skipped them and nothing else changed: cost 0.8920, emissions 0.9337, discomfort 0.0417, too warm 0.0181, ramping 1.0051, 68 clamped hours; every hour's cooling from `strategy` with the agent's own battery: 0.9031, 0.9447, 0.0374, 0.0116, 0.9977, all-time peak 0.9588 (0.9412 live), 22 clamped hours; scripted v8: 0.9031, 0.9447, 0.0374, 0.0116, 0.9983. Only live runs can show whether Haiku sends the strategy's cooling as given, keeps its battery discipline under the new wording, and how the rooms then evolve, and how any live agent does on the tuning months.

Request size and cost: a version 8 request averages 9,456 characters against 10,748 for version 7 over the same scripted month, 12.0 percent smaller (system prompt 3,645 against 4,780 characters, observation 153 shorter, reply schema unchanged). Scaled from the 0.9.0 live month (5,185 input and 245 output tokens per call, $0.4607), a Haiku month should cost about $0.42 ($0.4159 at the same reply length, $0.4379 if replies run 25 percent longer); the hard worst case is $0.95 for 719 hours and $0.98 for 743. Live Haiku months on all four months (2,924 hours) should cost about $1.69 to $1.78 in all, each under its own $2.00 cap.

Live runs (`claude-haiku-5-5`, prompt version 8, $2.00 budget each): phase 2 (run 20261023T160151Z, 719 hours), June (20261023T160150Z, 719), July (20261023T160200Z, 743) and August (20261023T160206Z, 743), scored with `hyperbolic months --run` against the baseline, the 0.4.0 rule-based controller (run 20261022T162847Z on phase 2) and scripted v8 on the same month:

| KPI | | phase 2 | June | July | August | mean |
|---|---|---|---|---|---|---|
| cost_total | baseline | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| | rule 0.4.0 | 0.9611 | 0.9506 | 0.9676 | 0.9682 | 0.9619 |
| | v8 scripted | 0.9031 | 0.9099 | 0.9193 | 0.9023 | 0.9087 |
| | Haiku v8 | 0.9045 | 0.9147 | 0.9228 | 0.9070 | 0.9122 |
| carbon_emissions_total | baseline | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| | rule 0.4.0 | 0.9947 | 1.0001 | 1.0038 | 1.0024 | 1.0002 |
| | v8 scripted | 0.9447 | 0.9654 | 0.9703 | 0.9524 | 0.9582 |
| | Haiku v8 | 0.9453 | 0.9691 | 0.9731 | 0.9559 | 0.9609 |
| electricity_consumption_total | baseline | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| | rule 0.4.0 | 1.0073 | 1.0065 | 1.0060 | 1.0071 | 1.0067 |
| | v8 scripted | 0.9540 | 0.9699 | 0.9717 | 0.9549 | 0.9626 |
| | Haiku v8 | 0.9547 | 0.9733 | 0.9744 | 0.9583 | 0.9652 |
| discomfort_proportion | baseline | 0.1714 | 0.1128 | 0.0645 | 0.1919 | 0.1352 |
| | rule 0.4.0 | 0.1714 | 0.1128 | 0.0645 | 0.1919 | 0.1352 |
| | v8 scripted | 0.0374 | 0.0174 | 0.0073 | 0.0210 | 0.0208 |
| | Haiku v8 | 0.0394 | 0.0207 | 0.0114 | 0.0251 | 0.0241 |
| too cool | baseline | 0.1538 | 0.0602 | 0.0614 | 0.1902 | 0.1164 |
| | rule 0.4.0 | 0.1538 | 0.0602 | 0.0614 | 0.1902 | 0.1164 |
| | v8 scripted | 0.0258 | 0.0069 | 0.0057 | 0.0210 | 0.0149 |
| | Haiku v8 | 0.0266 | 0.0088 | 0.0098 | 0.0251 | 0.0176 |
| too warm | baseline | 0.0176 | 0.0526 | 0.0031 | 0.0017 | 0.0188 |
| | rule 0.4.0 | 0.0176 | 0.0526 | 0.0031 | 0.0017 | 0.0188 |
| | v8 scripted | 0.0116 | 0.0104 | 0.0016 | 0.0000 | 0.0059 |
| | Haiku v8 | 0.0128 | 0.0118 | 0.0016 | 0.0000 | 0.0066 |
| ramping_average | baseline | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| | rule 0.4.0 | 1.1309 | 1.0742 | 1.0922 | 1.0848 | 1.0955 |
| | v8 scripted | 0.9983 | 0.9732 | 0.9677 | 1.0100 | 0.9873 |
| | Haiku v8 | 0.9969 | 0.9802 | 0.9744 | 1.0157 | 0.9918 |
| daily_peak_average | baseline | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| | rule 0.4.0 | 0.9978 | 0.9934 | 0.9743 | 0.9734 | 0.9847 |
| | v8 scripted | 0.9095 | 0.8830 | 0.8854 | 0.8861 | 0.8910 |
| | Haiku v8 | 0.9074 | 0.8919 | 0.8943 | 0.8896 | 0.8958 |
| all_time_peak_average | baseline | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| | rule 0.4.0 | 1.0000 | 1.0000 | 1.0000 | 0.9383 | 0.9846 |
| | v8 scripted | 0.9588 | 0.8541 | 0.8491 | 0.8570 | 0.8797 |
| | Haiku v8 | 0.9590 | 0.8549 | 0.8822 | 0.8940 | 0.8975 |
| daily_one_minus_load_factor_average | baseline | 1.0000 | 1.0000 | 1.0000 | 1.0000 | 1.0000 |
| | rule 0.4.0 | 0.9913 | 0.9834 | 0.9791 | 0.9867 | 0.9851 |
| | v8 scripted | 0.9639 | 0.9490 | 0.9520 | 0.9546 | 0.9549 |
| | Haiku v8 | 0.9616 | 0.9534 | 0.9564 | 0.9514 | 0.9557 |
| unserved energy in outages | baseline | 0.6844 | 0.0000 | 0.0000 | 0.0000 | 0.1711 |
| | rule 0.4.0 | 0.6844 | 0.0000 | 0.0000 | 0.0000 | 0.1711 |
| | v8 scripted | 0.6844 | 0.0000 | 0.0000 | 0.0000 | 0.1711 |
| | Haiku v8 | 0.6844 | 0.0000 | 0.0000 | 0.0000 | 0.1711 |
| clamped hours | baseline | 0 | 0 | 0 | 0 | 0.0 |
| | rule 0.4.0 | 1 | 1 | 0 | 0 | 0.5 |
| | v8 scripted | 22 | 32 | 10 | 3 | 16.8 |
| | Haiku v8 | 33 | 39 | 14 | 17 | 25.8 |
| model cost | Haiku v8 | $0.4182 | $0.4118 | $0.4229 | $0.4288 | $0.4204 |

Thermal resilience is scored only on phase 2, where all four controllers tie at 0.3698.

- **Haiku v8 beats the 0.4.0 rule-based controller on every KPI in every one of the four months**, with unserved energy in outages tied (0.9.0 live trailed it on hot-side discomfort).
- **Too-warm discomfort is now below the baseline in every month**; the v7 strategy was above it in every month.
- **Phase 2 against 0.9.0 live:** cost 0.9045 against 0.9245, discomfort 0.0394 against 0.0940, too warm 0.0128 against 0.0181, ramping 0.9969 against 0.9864, clamped hours 33 against 27.
- **The best live run so far on cost, emissions, grid import, discomfort, too warm and the daily peak** (phase 2). Not on the all-time peak (0.9.0 live: 0.9412), ramping (0.9.0 live: 0.9864) or load factor (0.4.0 live: 0.9559).
- **The agent now follows its strategy closely:** Haiku runs within about 0.004 of the v8 scripted strategy on mean cost (0.9122 against 0.9087; 0.0013 to 0.0048 by month).
- **The one KPI over the baseline is August ramping** (1.0157), where the v8 scripted strategy is also over (1.0100): a strategy limit, not an agent deviation.
- **Phase 2 is no longer a clean holdout**, because the outage exception and the selection rule were set after looking at it; the three tuning months are the cleaner evidence.
- 2,924 calls, 0 fallbacks, $1.6817 in all ($0.4182, $0.4118, $0.4229, $0.4288), and every run replays all its hours identically with 0 API calls.
- The published viewer (`docs/data`) now shows the 0.10.0 phase 2 live run in place of 0.9.0 (cost down 9.6 percent, emissions down 5.5 percent). Phase 2 stays the published month so the viewer stays comparable with earlier releases.

## 0.9.0 (2026-10-23)

Goal: the agent proposes actions that already fit the envelope, so clamps drop sharply and ramping goes under 1.0, without giving back cost, emissions, comfort or peaks against the 0.8.0 live month. The envelope does not change. The estimates below were built from recorded runs and the scripted strategy before any live call; the live month follows them.

Why 312 of 719 hours were clamped in the 0.8.0 live month (390 clamps; `runs/live/...20261022T222703Z`):

- **By rule** (hours, clamps): trim hold 292, 345; comfort 28, 32; battery state of charge 6, 10; cooling deviation 2, 2; peak limiter 1, 1. By building: the hold clamped Building_1 cooling 243 times, Building_3 100 and Building_2 2; comfort 19, 7 and 6.
- **The trim hold's 345 clamps, what the agent asked for against what the hold allowed:**
  - 250 (72 percent) were `null` on a held trim: 175 in the hold zone (room more than 0.5 C below its setpoint), where the hold restored a median 0.068 of depth, and 75 in the ease zone (0.040). The version 6 prompt said `null` keeps a held trim, and it does, but the envelope logs the kept trim as a clamp. In 208 hours these were the only clamps.
  - 52 ended the trim without `end_trim` by sending the baseline: 37 with the room still more than 0.5 C too cold (ended early) and 15 in the ease zone (released at once instead of by 0.02 an hour).
  - 38 eased too fast: 31 in the hold zone, where no easing is allowed (median 0.025 short), and 7 by more than 0.02 in the ease zone (median 0.022 short).
  - 5 asked for a trim where the hold had ended (all Building_1, room at or above its setpoint).
  - None deepened a trim when it should hold: a deeper trim is always allowed.
  - Every one of the 340 held-trim clamps came with the held depth already in the observation (`cooling_trim_held`). The agent saw the number; the prompt told it `null` was enough.
- **The other 45 clamps:** 21 of the 32 comfort clamps were rounding under 0.002 (the agent copied the 3 decimal baseline: 15 a hair above it in a cool room, 6 a hair below it in a warm one); 11 were real (8 extra cooling in a cool room, 3 trims in a warm one). 10 state of charge clamps (charging past 0.95, by 0.0004 to 0.13), 2 deviation clamps and 1 peak limiter trim.
- **What the agent could have avoided by seeing the constraint:** the live month's own replies, fitted into the ranges the version 7 observation shows (`scripts/evaluate_fit.py`), leave 7 clamped hours of 312 (305 avoidable, 98 percent of hours and of clamps), with every KPI equal to four decimals. The 7 left: 6 hours where the held trim is deeper than the baseline cooling, so cooling 0 is the most a reply can give and the hold still logs a clamp (requested 0, applied 0), and the 1 peak limiter trim.

Why ramping stayed above 1.0 (`scripts/split_ramping.py`, points of `ramping_average` above 1.0, 0.4.0 live against 0.8.0 live; the reference's own rises 470.20 and 470.55 kWh):

| Cause | 0.4.0 live (0.9965) | 0.8.0 live (1.0076) | Change |
|---|---|---|---|
| Battery charging | +1.24 | +1.90 | +0.66 |
| Battery discharging | -1.59 | -2.01 | -0.42 |
| Cooling trims (start, end, depth) | 0.00 | +0.86 (-2.03, +2.74, +0.15) | +0.86 |
| Other (tank, extra cooling, rounding, outage hours) | 0.00 | +0.01 | +0.01 |
| **Total** | **-0.35** | **+0.76** | **+1.11** |

- 0.4.0 left comfort at the baseline, so it had no trims. Most of the rise is the trims that bought 0.8.0's comfort, and the rest is net battery: 0.8.0's discharging cut more, but its charging added more. Its largest single battery rise is the top-price discharge stopping at 7 pm (63.3 kWh over the month; 0.4.0 spread its discharge ends over 4 to 7 pm and 11 pm, 33.4 kWh at 7 pm).
- The live agent sent `strategy_battery` in 1,994 of 2,157 building hours. In the other 163 it skipped a charge 70 times, charged when the plan was idle 51 times and skipped a discharge 34 times, mostly peak shaving. Those 163 hours are worth about 1.9 points: the same month with the battery plan followed exactly scores 0.9884 (battery charging +1.42, discharging -3.52).
- An envelope change is not the fix. 0.7.0 measured a ramp rule in the envelope and it made ramping worse, and the evidence here points at the strategy and at following it.

Changes:

- **Prompt version 7 (default).** Each building shows what the envelope allows this hour: `trim` (`depth`, `state` off, hold, ease or end, `why`, `min_depth` while a trim is held, `end_trim_ok`), `cooling_range` and `battery_range` (the values that pass the range, rate, state of charge, deviation, comfort and hold rules without a clamp, 4 decimals rounded inward; `null` when only the exact baseline passes), and `last_clamp`, last hour's clamps on that building with their reasons, in place of the district-wide `last_clamps`. `cooling_trim_held` and `cooling_trim_last_hour` are dropped. The prompt now says `null` is exactly the baseline, to be used only when the trim state is off or end, and that a held trim takes a number inside `cooling_range`. Version 6 stays selectable and recorded version 6 runs replay byte for byte.
- **The ranges are worked out read only from the envelope's own state** (`prompt.cooling_range`, `battery_range`, `trim_view`), in its own rule order, so a value inside them is never clamped. A randomized test holds that against `Envelope.apply`. `hyperbolic/envelope.py` is unchanged.
- **Battery guidance.** `strategy_battery` now comes from `battery_plan_v7` (`StrategyParamsV7`), which can cap how fast a battery action rises (on charging and discharging, or on a discharge winding down only) and fill the valley when grid charging. Searched on the tuning months (`scripts/tune_strategy.py --version 7`, 36 settings): no cap and no valley filling kept cost, emissions, discomfort and both peaks at version 6's battery plan. Every cap raised cost and the all-time peak; a cap of 0.1 left ramping at 0.9965 against 0.9823, and capping only the discharge wind-down raised it to 1.0016, because it spends the charge the evening shave needs. Charging at 0.1 instead of 0.15 cut ramping to 0.9644 but raised cost (0.9103 against 0.9086) and the all-time peak (0.8632 against 0.8526); valley filling cut it to 0.9116 at cost 0.9181. So the shipped plan is version 5's (cap 1, which is no cap), and the prompt's battery point targets the deviations: send `strategy_battery` as given, and when differing stay within 0.1 of it and never skip a peak-shaving discharge. No new envelope limit.
- **Scripted version 7 strategy** (`strategy_plan_v7`, `--scripted --prompt-version 7`): the version 5 cooling trim fitted into `cooling_range` (a held trim is never left to `null`) and the battery plan within `battery_range`.
- **Tools.** `scripts/evaluate_fit.py` sends a recorded version 6 run's replies through its own rules three ways: as recorded (a control that must reproduce its published KPIs), fitted to the version 7 ranges, and fitted with `strategy_battery` followed. These are evaluations, never recorded runs.
- `hyperbolic serve`'s first cost estimate uses the version 7 request size (5,160 input and 450 output tokens).
- Tests cover `EnvelopeConfig` defaults equal to 0.8.0 field by field (and the 0.7.0 and 0.4.0 rule sets), the 0.8.0 live month replaying 719 of 719 hours when it is on disk, the version 7 observation and its dropped fields, every trim state with `min_depth` and `end_trim_ok`, both ranges, any value inside them passing unclamped, a held trim left to `null` being clamped while the top of its range is not, `last_clamp`, the shipped battery plan equal to version 5's and inside `battery_range`, the cap winding a discharge down and leaving spare solar alone, valley filling, the prompt's wording and size, the scripted version 7 reply, fake-district and 24 hour CityLearn version 7 runs that replay identically, a full version 7 CityLearn month, the fitting evaluation and the search grid.

Estimates, no live calls. Scripted columns are not model results.

Phase 2 month (719 hours):

| CityLearn KPI (district) | 0.4.0 rule-based (20261022T162847Z) | 0.8.0 live | v6 scripted | v7 scripted | 0.8.0 live replies fitted to v7 | fitted, battery plan followed |
|---|---|---|---|---|---|---|
| cost_total | 0.9611 | 0.9190 | 0.9017 | 0.9016 | 0.9190 | 0.9182 |
| carbon_emissions_total | 0.9947 | 0.9610 | 0.9430 | 0.9429 | 0.9610 | 0.9603 |
| discomfort_proportion | 0.1714 | 0.0769 | 0.0430 | 0.0430 | 0.0769 | 0.0769 |
| ramping_average | 1.1309 | 1.0076 | 0.9957 | 0.9952 | 1.0076 | 0.9884 |
| daily_peak_average | 0.9978 | 0.9264 | 0.9078 | 0.9076 | 0.9264 | 0.9202 |
| all_time_peak_average | 1.0000 | 0.9593 | 0.9593 | 0.9588 | 0.9593 | 0.9585 |
| daily_one_minus_load_factor_average | 0.9913 | 0.9651 | 0.9640 | 0.9640 | 0.9651 | 0.9584 |
| Clamped hours | 1 | 312 | 139 | 22 | 7 | 7 |

Tuning set (three months, mean): the 0.4.0 rule-based controller cost 0.9621, emissions 1.0021, discomfort 0.1231, ramping 1.0838, daily peak 0.9804, all-time peak 0.9794, load factor 0.9831, 0.3 clamped hours; v6 scripted 0.9086, 0.9607, 0.0310, 0.9821, 0.8836, 0.8530, 0.9522, 112.0; v7 scripted 0.9086, 0.9607, 0.0312, 0.9823, 0.8837, 0.8526, 0.9525, 14.3. The tuning set has no live run.

- **Scripted v7 matches v6 and cuts clamped hours from 139 to 22** on the phase 2 month (112 to 14.3 a month on the tuning set). The 22 left are 21 hours where the held trim is deeper than the baseline cooling and 1 peak trim. Tuning-set discomfort is 0.0312 against 0.0310 because the v6 strategy's trims sat up to 0.002 shallower than the held depth, inside the hold's rounding allowance, and the v7 ranges hold the exact depth.
- **The live replies fitted to the ranges** reproduce the 0.8.0 live KPIs to four decimals with 7 clamped hours.
- **With the battery plan followed as well**, ramping is 0.9884, and cost, emissions, both peaks and load factor improve on 0.8.0 live at the same discomfort. Unserved energy in outages is 0.6861 against 0.6850 (baseline 0.6844).
- **What only a live run can measure:** whether Haiku keeps inside the ranges and sends a number for a held trim, how closely it follows `strategy_battery` under the new wording, and how the rooms and batteries then evolve, since fixed replies cannot react. The fitted columns assume a model that obeys the ranges; the battery column assumes one that sends `strategy_battery` every hour.

Request size and cost: a version 7 request averages 10,748 characters against 10,928 for version 6 over the same scripted month, 1.7 percent smaller: the system prompt 4,780 against 5,221 characters, the observation 231 characters longer, the schema unchanged. Scaled from the 0.8.0 live month (5,245 input and 429 output tokens per call, $0.5315), a Haiku month should cost about $0.53 ($0.5252 at the same reply length, $0.5327 if replies grow 5 percent). The hard worst case (every character a third of a token and a full 2,000 token reply) is $0.98 for all 719 hours, under the $2.00 cap.

Live run (`claude-haiku-5-5`, full month, 719 hours, prompt version 7, run 20261023T135430Z), against the baseline, the 0.4.0 rule-based controller (run 20261022T162847Z) and the 0.8.0 live month:

| CityLearn KPI (district), full month | Baseline | 0.4.0 rule-based | 0.8.0 live | 0.9.0 live |
|---|---|---|---|---|
| cost_total | 1.000 | 0.9611 | 0.9190 | 0.9245 |
| carbon_emissions_total | 1.000 | 0.9947 | 0.9610 | 0.9648 |
| electricity_consumption_total | 1.000 | 1.0073 | 0.9695 | 0.9744 |
| discomfort_proportion (too cool, too warm) | 0.1714 (0.1538, 0.0176) | 0.1714 (0.1538, 0.0176) | 0.0769 (0.0601, 0.0168) | 0.0940 (0.0759, 0.0181) |
| daily_peak_average | 1.000 | 0.9978 | 0.9264 | 0.9182 |
| all_time_peak_average | 1.000 | 1.0000 | 0.9593 | 0.9412 |
| ramping_average | 1.000 | 1.1309 | 1.0076 | 0.9864 |
| daily_one_minus_load_factor_average | 1.000 | 0.9913 | 0.9651 | 0.9566 |
| power_outage_normalized_unserved_energy_total | 0.6844 | 0.6844 | 0.6850 | 0.6844 |
| Clamped hours, fallback hours | | 1, 0 | 312, 0 | 27, 0 |
| Model cost | | none | $0.5315 | $0.4607 |

- **Clamped hours fell from 312 to 27** because version 7 shows the agent its allowed range each hour. 250 of the 0.8.0 clamps were held trims the envelope logged as clamps, not the agent breaking a limit.
- **Ramping is under 1.0 for the first time since 0.4.0** (0.9864; 0.4.0 live: 0.9965).
- **The best live run so far on the daily peak and the all-time peak** (0.9182 against 0.8.0 live's 0.9264, 0.9412 against 0.6.0 live's 0.9483). Load factor (0.9566) is second only to 0.4.0 live (0.9559), which left comfort at the baseline.
- **Gives back a little against 0.8.0 live** on cost (0.9245 against 0.9190), emissions (0.9648 against 0.9610) and comfort (0.0940 against 0.0769).
- **Beats or ties the 0.4.0 rule-based controller on every KPI except hot-side discomfort**, where it trails by 0.0005 (0.0181 against 0.0176). Thermal resilience ties at 0.3698, and unserved energy in outages now ties the baseline (0.6844).
- **Valley filling stays off by default.** It cut tuning-set ramping further (0.9116 against 0.9823) but cost about 0.01 in cost (0.9181 against 0.9086).
- 719 calls, 0 fallbacks, $0.4607 of $2.00, replays 719 of 719 hours deterministically.
- The published viewer (`docs/data`) now shows the 0.9.0 live run in place of 0.8.0.

## 0.8.0 (2026-10-22)

Goal: carry the cooling trim hold in code so the live agent cannot drop it by accident, explain the 0.7.0 ramping rise first, and get live ramping below the baseline without giving back cost, emissions, comfort or the peaks against 0.6.0 live.

Why the 0.7.0 live month ramped more than 0.6.0 live (1.0358 against 1.0174):

- **The KPI's denominator is built inside each run.** CityLearn divides the run's sum of hourly rises in district draw by the same run's draw with storage removed and cooling at the ideal load, not by the baseline run. In hour 399, during an outage in Buildings 1 and 2, the 0.7.0 agent asked for extra cooling; the grid draw was 0 anyway, but CityLearn took the extra cooling off its reference (-0.71 kWh), and the climb back at hour 400 added 0.71 kWh of rises to the denominator only. That is why the hourly series gives 1.0374 against the baseline run and the KPI 1.0358. 0.6.0 matched exactly because its cooling was at the baseline in that outage.
- **Split exactly by cause** (Shapley shares of each hour's rise, adding up to CityLearn's figure; points of ramping above 1.0, 0.6.0 live against 0.7.0 live): trims net +2.52 against +2.74 (ends +6.37 against +5.29, starts -4.84 against -3.30, depth +0.98 against +0.75); battery charging -0.60 against +1.12; battery discharging -0.10 against -0.33; hot water tank 0.00 against +0.18; extra cooling -0.07 against +0.03; the outage-hour effect 0.00 against -0.15. The scripted v5 strategy: trims +1.81, battery charging +1.36, discharging -3.51.
- **The cause is the battery, not the trims.** Battery charging accounts for 1.72 of the 1.84 point rise. 0.7.0 charged 184 kWh against 272 and discharged 156 kWh against 237. 0.6.0's daytime charging stopped, and its daytime discharges started, as the afternoon load climbed, which cancelled rises; 0.7.0 rarely charged in the day and discharged in only 35 of the 80 building hours where the strategy says to cut the daytime peak (0.6.0: 46 of 74, scripted: 51 of 51). The trims are the largest single cause in every run but look much the same in both. The scripted strategy is below the baseline mainly because of its discharging.

Changes:

- **Trim hold in the envelope** (rule `trim_hold`, `EnvelopeConfig.trim_hold`, numbers from `StrategyParamsV5`). Per building: whether a trim is on (cooling more than 0.002 below the baseline action) and how deep. Occupied and more than 0.5 C below the setpoint: at least as deep as last hour. Within 0.5 C: eases off by at most 0.02 per hour. Ends at once at or above the setpoint, when unoccupied, or with no baseline cooling, and none may start there. `null` keeps a held trim, deeper is allowed, and a miss under 0.002 is rounding (the full depth stays held). It runs after the comfort rule and only keeps cooling below the baseline within the deviation limit. The spread check, peak limiter, comfort rule, battery limits, JSON envelope, fallback and budget cap are unchanged. Not a ramp taper.
- **`end_trim` per building** in prompt version 6 replies: `null` or a reason, the only way to end a held trim early. Every hold action (start, hold, ease, release, end, early end) is recorded in the decision's `holds` with its reason; changed values are clamps with rule `trim_hold`. Early ends show in the replay viewer's reason card and the live log, and the viewer data counts them (`trim_ends_early`).
- **Prompt version 6 (default).** Version 5 plus the hold and `end_trim` in the strategy, `cooling_trim_held` per building, and `strategy_battery` with `strategy_battery_reason` (the version 5 strategy's own battery action, `battery_plan_v5`) in place of the 0.4.0 rule-based `reference_action`. `strategy_plan_v5` returns exactly what it did. Requests are 4.8 percent larger than version 5 (10,928 against 10,432 characters).
- **Versioned rules.** Manifests without the new settings rebuild without the hold, and their decisions carry no `holds` key, so every older run replays byte for byte. `EnvelopeConfig.v070()` is the 0.7.0 rule set, used for new runs on prompt versions 1 to 5. The 0.6.0 and 0.7.0 live months and the committed baseline replay 719 of 719 hours.
- **Tools.** `scripts/split_ramping.py` (the exact split), `scripts/evaluate_hold.py` (a recorded run's own replies through its own rules, which must reproduce its KPIs, and through the hold; an evaluation, never a recorded run), `RecordedReplySupervisor`, and `scripts/tune_strategy.py --version 6`. The version 4 and 5 searches now pin the 0.7.0 rules they were made with.
- `hyperbolic serve`'s first cost estimate uses the version 6 request size (5,200 input and 790 output tokens). `compare --against` labels scripted runs by prompt version. The page's How it works strip names the trim hold.
- Tests cover the hold (on, hold, ease, release, every end, early end with a reason, rounding, logging, fallback, rule order, older rules unchanged, byte-for-byte replay with hold actions, changed hold settings detected), the version 6 schema, parsing, observation, prompt and request size, the scripted version 6 reply, recorded replies, the viewer's early ends, 24 hour and full-month version 6 CityLearn runs, and the split and evaluation tools.

Estimates before any live run (tuning months first; nothing tuned on the phase 2 month):

- **Scripted v5 strategy, tuning months**, 0.7.0 against 0.8.0 rules: ramping 0.9816 against 0.9821, daily peak 0.8834 against 0.8836 and load factor 0.9517 against 0.9522 slightly worse; cost 0.9089 against 0.9086, emissions 0.9610 against 0.9607 and all-time peak 0.8532 against 0.8530 slightly better; discomfort equal at 0.0310. The rounding allowance was added here: without it discomfort rose to 0.0312 and the hold clamped 247 to 443 times a month. The strategy's own trims drift shallower by about 0.0015 an hour through rounding, and the hold stops that.
- **Scripted v5 strategy, phase 2 month**: ramping 0.9966 against 0.9957, daily peak 0.9081 against 0.9078, all-time peak 0.9597 against 0.9593 better; emissions, grid import and load factor unchanged to four decimals; cost 0.9015 against 0.9017 and discomfort 0.0424 against 0.0430 slightly worse. Clamped hours 1 against 139.
- **0.7.0 live replies through the 0.8.0 rules** (control reproduces the published 0.7.0 KPIs exactly): cost 0.9320 to 0.9169, emissions 0.9635 to 0.9477, grid import 0.9684 to 0.9527, discomfort 0.0741 to 0.0511, daily peak 0.9393 to 0.9284, all-time peak 0.9592 to 0.9548, ramping 1.0358 to 1.0249, load factor 0.9747 to 0.9787 (worse). Against 0.6.0 live that is better on cost, emissions, discomfort and the daily peak, and worse on the all-time peak and ramping, which stays above the baseline. Trim rule breaks 142 to 4. Clamped hours 66 to 323.
- **The battery change in prompt version 6 is not in any estimate and can only be measured live.**
- A Haiku month should cost about $0.66; the hard worst case is $0.99, under the $2.00 cap.

Live run (`claude-haiku-5-5`, full month, 719 hours, prompt version 6), against the baseline, the 0.4.0 rule-based controller (rerun as run 20261022T162847Z, matching its published numbers) and the earlier live months:

| CityLearn KPI (district), full month | Baseline | 0.4.0 rule-based | 0.6.0 live | 0.7.0 live | 0.8.0 live |
|---|---|---|---|---|---|
| cost_total | 1.000 | 0.9611 | 0.9219 | 0.9320 | 0.9190 |
| carbon_emissions_total | 1.000 | 0.9947 | 0.9665 | 0.9635 | 0.9610 |
| electricity_consumption_total | 1.000 | 1.0073 | 0.9740 | 0.9684 | 0.9695 |
| discomfort_proportion (too cool, too warm) | 0.1714 (0.1538, 0.0176) | 0.1714 (0.1538, 0.0176) | 0.0861 (0.0680, 0.0181) | 0.0741 (0.0560, 0.0181) | 0.0769 (0.0601, 0.0168) |
| daily_peak_average | 1.000 | 0.9978 | 0.9354 | 0.9393 | 0.9264 |
| all_time_peak_average | 1.000 | 1.0000 | 0.9483 | 0.9592 | 0.9593 |
| ramping_average | 1.000 | 1.1309 | 1.0174 | 1.0358 | 1.0076 |
| daily_one_minus_load_factor_average | 1.000 | 0.9913 | 0.9773 | 0.9747 | 0.9651 |
| power_outage_normalized_unserved_energy_total | 0.6844 | 0.6844 | 0.6844 | 0.6877 | 0.6850 |
| Clamped hours, fallback hours | | 1, 0 | 73, 0 | 66, 0 | 312, 0 |
| Model cost | | none | $0.5740 | $0.6329 | $0.5315 |

- **Against the 0.4.0 rule-based controller it wins on every KPI except unserved energy in outages**, where it trails by 0.0006 (0.6850 against 0.6844). Thermal resilience ties at 0.3698.
- **The first live run with both fewer too-cool and fewer too-warm hours than the baseline** (0.0601 against 0.1538, 0.0168 against 0.0176). 0.6.0 and 0.7.0 live added warm hours (0.0181).
- **The best live run so far on cost, emissions and the daily peak.** Not on discomfort (0.7.0 live: 0.0741), grid import (0.7.0 live: 0.9684), the all-time peak (0.6.0 live: 0.9483), or ramping and load factor (0.4.0 live, at baseline comfort: 0.9965 and 0.9559).
- **Missed the 0.8 goal on ramping**: 1.0076, down from 1.0358 and below 0.6.0 live (1.0174) and the 1.0249 estimate, but still above the baseline.
- **Gave back the all-time peak against 0.6.0 live** (0.9593 against 0.9483). Cost, emissions, discomfort and the daily peak improved on 0.6.0 live.
- **312 of 719 hours clamped**, 276 by the trim hold alone and 292 with it (243 clamps on Building_1 cooling, 100 on Building_3, 2 on Building_2); comfort in 28 hours, state of charge in 6, deviation in 2, peak in 1. The hold acted 557 times (109 starts, 243 holds, 97 eases, 21 releases, 80 ends, 7 early ends with a reason). The envelope is steering the agent. 0 fallbacks, 719 calls, $0.5315 of $2.00, replays 719 of 719 hours deterministically.
- The published viewer (`docs/data`) now shows the 0.8.0 live run in place of 0.6.0.

Next for 0.9: cut the clamp rate without losing these gains.

## 0.7.0 (2026-10-22)

Goal: bring ramping below the baseline and the load factor back toward 0.4.0 without giving back cost, emissions, comfort or the peaks, and clean up the public page.

Why the 0.6.0 live month ramped more, from its hourly decisions in `docs/data` (the hourly series reproduce its ramping 1.0174 and load factor 0.9773 exactly):

- **Ramping.** CityLearn's ramping adds up every hour the district draws more than the hour before; a step down costs nothing. Split between the two kinds of action, the cooling trims added 2.45 percent and the battery took 0.71 percent off.
  - The trims flickered. There were 276 trim episodes, with a median length of one hour (160 lasted exactly one hour), and 263 ended while the room was still occupied: the room warmed past the threshold, the trim stopped, the room cooled, and it started again. Every end was a step back up to the baseline. In 75 hours, two or three buildings stepped up together.
  - The battery's own up-steps nearly cancelled. A discharge stopping at 7 pm added 55.8 kWh of up-ramp and a charge starting added 27.0 kWh, while a discharge starting at 4 pm took 83.3 kWh away.
- **Load factor against 0.4.0 live (0.9773 against 0.9559).** The cooling trims account for 0.0158 of the gap: they cut energy across the day, which lowers the daily mean while the daily peak, mostly 8 to 11 pm, stays (on 16 days a trim was running at the peak hour). The battery accounts for 0.0056: it now spends its charge in the 4 to 7 pm price window (137 kWh there against 0.4.0's 86) and has little left for the evening peak that 0.4.0 partly shaved.

Changes:

- **Prompt version 5 (default).**
  - Adds last hour's measured district draw, the district load before storage now and at the next hour (as yesterday), and each building's cooling trim last hour.
  - Adds a smoothing strategy:
    - Hold a trim, once on, until the room is within 0.5 C of its setpoint, then ease it off by at most 0.02 per hour.
    - Start grid charging small and raise it by at most 0.15 per hour.
    - Discharge evenly over the top-price hours.
  - States that ramping counts only steps up. Versions 1 to 4 are unchanged, so recorded runs replay byte for byte.
- **Scripted version 5 strategy** (`strategy_plan_v5`, `StrategyParamsV5`): the version 5 prompt followed literally, run with `--scripted --prompt-version 5`.
- **Tuned on the tuning set only.**
  - `scripts/tune_strategy.py` now defaults to version 5. It searched 18 smoothing settings on the three tuning months under hard constraints: ramping below the baseline, with cost, emissions, discomfort and both peaks no worse than the 0.6.0 tuned strategy on the same months. 8 qualified, and the one with the lowest ramping plus load factor is shipped.
  - On the tuning months the shipped setting scores ramping 0.9816 against 0.9953 for the 0.6.0 strategy, load factor 0.9517 against 0.9529, cost 0.9089 against 0.9113, emissions 0.9610 against 0.9671, discomfort 0.0310 against 0.0344, and both peaks lower. `--version 4` reruns the 0.6.0 search unchanged.
- **No ramp rule in the envelope, on the evidence.** A deterministic rule that limited how fast a battery action or a cooling trim could rise was built and tested, then removed. It made things worse: on the tuning months the same strategy scored ramping 0.9886 with it against 0.9816 without, at higher cost. Sending the 0.6.0 live run's own actions through it raised ramping from 1.0174 to 1.0186. A taper only spreads the same rise over more hours, and CityLearn's ramping sums the rises either way. What lowers it is fewer on and off cycles, which the strategy's hold does. The envelope keeps a read-only record of each building's trim for the prompt; its rules are unchanged.
- **Evening reserve, measured and left off.** Keeping some charge back from the top-price hours for the evening district peak lowers ramping and load factor further: on the tuning months, a reserve of 0.1 gave ramping 0.965 to 0.979 and load factor 0.945 to 0.954. But every reserve tried (0.03, 0.05 and 0.1) raised cost above the 0.6.0 strategy, which the constraints rule out.
- **Public page.**
  - A compact "How it works" strip under the headline: the agent decides, the safety envelope checks, CityLearn simulates, CityLearn scores.
  - A "Run it yourself" section with the local commands, including `hyperbolic serve`, replaces the stale "Replace the sample with a live agent run". The sample banner links to it.
  - It works in both themes and at phone width, with no sideways page scroll; long commands scroll inside their box. The replay and `docs/data` are unchanged.
- `hyperbolic serve`'s cost estimate uses the version 5 request size. `PeakTracker` reports last hour's district draw and the next hour's load as yesterday.
- `hyperbolic serve` reads and discards a refused request's body (up to the 10,000 byte limit) before it sends the 403. On Windows, closing with the body unread reset the connection, so the client saw WinError 10054 or 10053 instead of the 403, and `test_refuses_other_hosts_and_cross_site_posts` failed now and then (1 run in 20 before the fix, 0 in 60 after).
- Tests cover:
  - the v5 strategy's trim hold, slow release, immediate start and release at the setpoint
  - the gentle charge start and the even discharge
  - the v5 observation and prompt
  - the envelope's trim record
  - the tracker fields
  - v5 runs that replay byte for byte and detect a changed observation
  - a full v5 CityLearn month with ramping below the baseline
  - 24 hour v4 and v5 CityLearn runs with replay
  - the new page sections

Results, phase 2 local evaluation month (719 hours). The scripted columns are not model results; the v5 strategy was run once on this month after tuning.

| CityLearn KPI (district) | Baseline | 0.4.0 rule-based | 0.6.0 live, Haiku | 0.6.0 v4 strategy, scripted | 0.7.0 v5 strategy, scripted | 0.7.0 live, Haiku |
|---|---|---|---|---|---|---|
| cost_total | 1.000 | 0.9611 | 0.9219 | 0.9057 | 0.9015 | 0.9320 |
| carbon_emissions_total | 1.000 | 0.9947 | 0.9665 | 0.9506 | 0.9430 | 0.9635 |
| electricity_consumption_total | 1.000 | 1.0073 | 0.9740 | 0.9602 | 0.9523 | 0.9684 |
| discomfort_proportion | 0.1714 | 0.1714 | 0.0861 | 0.0458 | 0.0424 | 0.0741 |
| daily_peak_average | 1.000 | 0.9978 | 0.9354 | 0.9193 | 0.9081 | 0.9393 |
| all_time_peak_average | 1.000 | 1.0000 | 0.9483 | 0.9703 | 0.9597 | 0.9592 |
| ramping_average | 1.000 | 1.1309 | 1.0174 | 1.0151 | 0.9966 | 1.0358 |
| daily_one_minus_load_factor_average | 1.000 | 0.9913 | 0.9773 | 0.9661 | 0.9640 | 0.9747 |

The scripted version 5 strategy brings ramping below the baseline (0.9966) and improves on the version 4 strategy on every KPI in the table. Its load factor (0.9640) does not reach the 0.4.0 live run's 0.9559, and like the version 4 strategy its hot discomfort (0.0181) is a little above the baseline's 0.0176. The baseline, the 0.4.0 rule-based controller and the scripted version 4 strategy reproduce their published numbers exactly, and all four runs replay 719 of 719 hours.

Live 0.7.0 run (`claude-haiku-5-5`, full month, 719 hours, prompt version 5) missed the 0.7 goal. Ramping, the target, went up, not down: 1.0358 against 1.0174 for 0.6.0 live. The scripted version 5 strategy reached 0.9966, so the strategy works when it is followed exactly; the live agent did not hold cooling trims the way the prompt asks.

- **Against 0.6.0 live**, it improved emissions (0.9635 against 0.9665), grid import (0.9684 against 0.9740), discomfort (0.0741 against 0.0861: too cool 0.0560 against 0.0680, too warm unchanged at 0.0181) and load factor (0.9747 against 0.9773). Ramping, cost (0.9320 against 0.9219), the daily peak (0.9393 against 0.9354), the all-time peak (0.9592 against 0.9483) and unserved energy in outages got worse.
- **Outages.** Unserved energy in outages is 0.6877 against the baseline's 0.6844, slightly worse than the baseline: the first run to go past it. Thermal resilience is 0.3698, equal to the baseline.
- **Against the 0.4.0 rule-based controller**, it still wins on cost (0.9320 against 0.9611), emissions (0.9635 against 0.9947), grid import (0.9684 against 1.0073), discomfort (0.0741 against 0.1714), ramping (1.0358 against 1.1309), daily peak (0.9393 against 0.9978), all-time peak (0.9592 against 1.0000) and load factor (0.9747 against 0.9913).
- **Trims, counted the same way as the 0.6.0 diagnosis** (cooling more than 0.002 below the baseline action; episodes that ended within the month). 0.7.0 live had 237 trim episodes against 276 in 0.6.0 live and 167 for the scripted v5 strategy. The median length was 2 hours against 1 and 3, with 108 lasting one hour against 160 and 46. 230 ended while the room was occupied, against 263 and 161. The prompt asks to hold a trim until the room is within 0.5 C of its setpoint, then ease it off by at most 0.02 per hour. 142 of the 237 ends broke that: 73 with the room still more than 0.5 C too cold, and 69 dropped more than 0.02 in one hour. The scripted strategy broke it in 4 of 167, all at the edge of the rule. Trims flickered less than in 0.6.0, so they alone do not explain why ramping rose above 0.6.0 live; that rise is not split further here.
- **Clamps.** 66 clamped hours, 0 fallbacks. By rule: battery state of charge in 51 hours (68 clamps, all charging past 0.95, by a median 0.002), comfort in 12 hours (13 clamps: 10 asked for more cooling than the baseline in a room near the bottom of its band, 3 were rounding under 0.001), cooling more than 0.15 from the baseline in 2 hours (3 clamps), and the peak limiter in 1 hour. No hour had two rules, and the spread check never acted.
- The run cost $0.6329 of the $2.00 budget and replays 719 of 719 hours deterministically.
- **The published viewer stays on the 0.6.0 live run.** It is the better live run on cost, ramping, both peaks and outage energy, and the cost saving the page leads with would drop from 7.8 to 6.8 percent. The 0.7.0 viewer data was built locally and not published; `docs/data` is unchanged.

Next for 0.8, a plan only: carry the trim hold state in code. The envelope or the peak tracker keeps each building's trim on until the room is back within 0.5 C of its setpoint and then eases it off by at most 0.02 per hour. The model can end a trim early only with a stated reason, logged and shown in the viewer. This is not the removed ramp rule, which tapered rises; it keeps a trim on, as the scripted strategy does.


## 0.6.0 (2026-10-22)

Goal: the live agent beats the 0.4.0 rule-based controller on cost and emissions without giving back its daily peak, ramping and load factor wins, at equal or better comfort.

Why the 0.4.0 live month lost on cost (0.9765 against the rule-based 0.9611, a gap of $1.20 of the $82.69 baseline bill), from an hour by hour comparison of the two runs, ranked by dollars:

1. **It reached the 4 to 7 pm price peak with too little charge.** The batteries hold 8.5 kWh above their floor, but the district draws 14.2 kWh in those three hours, so every stored kWh can be sold at the top price. The agent arrived with 4.8 kWh stored on average against the rule-based controller's 6.6 kWh, and delivered 86 kWh into top-price hours against 119 kWh: $1.90 less saved.
2. **It spent charge before the peak.** 23.5 kWh went out between 7 am and 4 pm on top-price days (the rule-based controller: none), saving only the off-peak price ($0.65). Its own reasons cite peak shaving in 12 of those 20 hours and a high combined signal in 12: the 50/50 price and carbon signal ranks high-carbon middays as discharge hours at the off-peak price.
3. **It bought more grid energy:** 14 kWh more off-peak charging on top-price days, $0.46.
4. **It charged at the top price** in 3 building hours (1.9 kWh, $0.11): the only charging of the month that no later price could pay back.
5. Partly offsetting: less cycling on flat-price weekends ($0.46) and some evening discharge ($0.16).

Round trip losses were not a cause (both runs got back about 0.875 of what they charged). CityLearn's district cost is the mean of the three buildings' cost ratios, so a dollar saved in the smallest bill counts most.

Comfort, and a mapping bug: discomfort matched the baseline to four decimals in every live run because the agent never moved cooling (0 of 2,157 building hours off the baseline) and could not see why it should. The indoor temperature in the state was CityLearn's observation, which for an LSTM building is the dataset's no-control value for the coming hour, written before the hour is simulated. The agent and the envelope's comfort rule never saw the room CityLearn simulated: over the baseline month the two differ by a median 1.0 C and up to 6.4 C, and with cooling cut by 0.3 the simulated rooms ran at 28 to 31 C while the state still said 22 to 24 C. The baseline actually overcools: most uncomfortable occupied hours are too cold with the heat pump running. CityLearn scores "too cold" against the heating setpoint; that equals the cooling setpoint in every row of both datasets used here, so that difference has no effect.

Changes:

- **Indoor temperature fix.** The simulator state now reports the temperature CityLearn's LSTM simulated for the hour just finished. A test pins it: the temperature at the start of each hour equals the one simulated for the hour before, and a cooling cut shows up as a warmer room.
- **Spread check in the envelope.** Grid charging of a battery is blocked when no price in the next 24 hours, after the battery's worst round trip efficiency (the minimum of its power efficiency curve, 0.88 or 0.89 here) and its standing loss until then, is worth more than the price now, while a cheaper hour is coming. Spare solar may still be stored. Each block is a clamp with rule `spread` and its reason. Nothing is fitted: the numbers come from each battery's own data. A flat outlook (a weekend) does not block, because the next peak may lie beyond the forecast. Older runs and the rule-based reference replay without it.
- **Prompt version 4 (default).** Adds the 0.4.0 rule-based controller's plan for the hour as `reference_action` with its reason; a price plan (the 24 hour top and low, `top_price_now`, the top-price hours ahead, `flat_24h`); each battery's real charge floor, usable energy, worst round trip efficiency and `grid_charging_ok`, the spread check's verdict; and each room's distance from its setpoint. The strategy now puts price first and carbon second: hold the battery for the top-price hours, discharge there sized to each building's own load, charge about 0.15 of capacity per hour in the cheapest, cleanest hours so the battery is full when they start, discharge early only to keep district load under 0.9 of the forecast peak, leave weekends alone, and trim cooling gradually (up to 0.1 below the baseline) in occupied rooms more than 0.5 C below their setpoint.
- **The rule-based controller is frozen as the 0.4.0 reference.** `hyperbolic run --scripted` and the live page's rule-based option run it on prompt version 3 with the 0.4.0 envelope, so it still scores cost 0.9611 and emissions 0.9947 (a test checks this on the full month). `--scripted --prompt-version 4` runs the version 4 strategy literally (`strategy_plan_v4`), with no model.
- **Tuning on a separate dataset.** `scripts/tune_strategy.py` chooses the strategy's numbers on `citylearn_challenge_2023_phase_2_online_evaluation_1` (CityLearn v3.0.2, copied unchanged into `scripts/tuning_data`): the same three buildings and LSTM models, but June, July and August of a different period with its own weather, loads, carbon and tariff, and no hour in common with the reported month. A setting qualifies when, averaged over the three months, it is as comfortable as the baseline, keeps both peaks, ramping and the load factor at or below the baseline, and beats the 0.4.0 rule-based controller on cost and emissions; 36 of 216 did. The reported month was not used to choose anything.
- `hyperbolic run --prompt-version` defaults to 4 for models and 3 for `--scripted`. `scripts/tune_rules.py` keeps searching the 0.4.0 controller on its own settings.
- `hyperbolic compare --against RUN` (repeatable) prints other finished runs of the same length beside the baseline and the agent, so a live run can be read against the rule-based controller in one table. The viewer data is unchanged.
- Tests: the spread check (blocked at the top price with its reason, allowed when the coming peak pays, not blocked by a flat weekend, blocked when only a cheaper hour is ahead, standing losses, spare solar, discharging untouched, off for older runs and the reference, before the peak limiter), the reference action equal to what the rule-based controller replies, the version 4 observation and prompt, the indoor temperature fix, the frozen rule-based month, a version 4 CityLearn run that replays identically, recorded version 4 runs that replay byte for byte and detect a changed reference policy, and `compare --against`.

Results, phase 2 local evaluation month (719 hours) against the committed baseline. The version 4 strategy column is the scripted stand-in, run once after tuning; it is not a model result.

| CityLearn KPI (district) | Baseline | 0.4.0 rule-based | 0.4.0 live, Haiku | 0.6.0 v4 strategy, scripted | 0.6.0 live, Haiku |
|---|---|---|---|---|---|
| cost_total | 1.000 | 0.9611 | 0.9765 | 0.9057 | 0.9219 |
| carbon_emissions_total | 1.000 | 0.9947 | 0.9974 | 0.9506 | 0.9665 |
| discomfort_proportion | 0.1714 | 0.1714 | 0.1714 | 0.0458 | 0.0861 |
| daily_peak_average | 1.000 | 0.9978 | 0.9525 | 0.9193 | 0.9354 |
| all_time_peak_average | 1.000 | 1.0000 | 1.0000 | 0.9703 | 0.9483 |
| ramping_average | 1.000 | 1.1309 | 0.9965 | 1.0151 | 1.0174 |
| daily_one_minus_load_factor_average | 1.000 | 0.9913 | 0.9559 | 0.9661 | 0.9773 |
| electricity_consumption_total | 1.000 | 1.0073 | 1.0098 | 0.9602 | 0.9740 |

The baseline and the 0.4.0 rule-based controller reproduce their 0.4.0 numbers exactly in this release.

Live 0.6.0 run (`claude-haiku-5-5`, full month, 719 hours, prompt version 4) beats the 0.4.0 rule-based controller on cost (0.9219 against 0.9611), emissions (0.9665 against 0.9947), grid import (0.9740 against 1.0073), discomfort (0.0861 against 0.1714), ramping (1.0174 against 1.1309), daily peak (0.9354 against 0.9978), all-time peak (0.9483 against 1.0000) and load factor (0.9773 against 0.9913). The rule-based numbers were rerun on the same machine and match 0.4.0 exactly. Against the baseline it wins on everything except ramping, 1.7 percent worse (1.0174), and hot discomfort, 0.0181 of occupied hours against 0.0176: trimming cooling in cold rooms halved the cold hours (0.0680 against 0.1538) and added a few warm ones. Thermal resilience (0.3698) and unserved energy in outages (0.6844) tie the baseline.

It trails the scripted version 4 strategy, which follows the same prompt literally (cost 0.9057, emissions 0.9506, discomfort 0.0458), and the 0.4.0 live run still has the better ramping (0.9965) and load factor (0.9559); the 0.6.0 run has the better daily peak (0.9354 against 0.9525).

73 clamped hours, 0 fallbacks. By rule: battery state of charge in 54 hours (73 clamps), cooling more than 0.15 from the baseline in 14 hours (16 clamps), the comfort rule holding cooling at the baseline in 6 hours (6 clamps), and one battery rate limit; 3 hours had two rules. The spread check and the peak limiter never had to act. The run cost $0.5740 of the $2.00 budget and replays 719 of 719 hours deterministically.


## 0.5.0 (2026-10-21)

Local live mode: watch a run unfold in the browser, hour by hour, on the same viewer as the published replay.

- `python -m hyperbolic serve`: a small server on 127.0.0.1 (default port 8765) that serves the viewer with a live panel and opens the browser; `--no-browser`, `--port`, `--runs-dir`, `--docs`. Standard library only: `http.server` and Server-Sent Events.
- Controls: duration (24 hours, 1 week, full month or custom), controller (`claude-haiku-5-5`, `claude-sonnet-5-5`, rule-based, baseline), budget with a cost estimate from recorded runs, and Start, Pause, Resume and Stop. One run at a time; the controls lock while it goes.
- Each finished hour streams to the page: actions, clamps and their reasons, the agent's reason, building states, price, carbon, district draw against the peak target, running KPIs against the baseline over the same hours, and spend. The viewer's tiles, timeline and charts update live, with a scrolling log of reasons.
- Safety: binds 127.0.0.1 only, answers only Host 127.0.0.1 or localhost, and refuses cross-site requests. The key stays in the server process and never reaches the page, logs or run files. The budget cap is enforced on the server as in the CLI. Without a key the Claude options are off and the rule-based and baseline controllers still work.
- Every live run is recorded in `runs/` in the `hyperbolic run` format and replays exactly. A stopped run is saved as partial and scored against a baseline stopped at the same hour.
- When a run finishes the page shows the CityLearn compare table and a Publish button that writes `docs/data` like `hyperbolic compare --pair`, locally only.
- Shared code, not a copy: `run_session` gained an optional per-hour callback, pause and stop control, and a step limit; `viewer.ScenarioStream` builds the replay viewer's data one hour at a time (tests hold it equal to `build_scenario`); the viewer gained a `render(data)` hook. The published GitHub Pages replay is unchanged.
- A "baseline" controller (`HoldSupervisor`) runs the no-control actions through the agent path so it records and publishes like any run. Rule-based and baseline runs are always labeled as samples.


## 0.4.0 (2026-10-21)

The 0.3.0 live month beat the baseline on cost but not the rule-based controller, raised emissions and set new peaks. In that run the model charged most at hours 19 to 24: those hours tie for the lowest price, but they are high-carbon and sit on the district's own evening load peak. 16 of 30 days got a higher daily peak, and the month's peak rose 7.5 percent.

- Peak limiter in the envelope: battery then tank charging is trimmed so the district's draw stays at or below the peak target, the higher of today's peak so far and the forecast of today's peak (lowest of the last two days' peaks before storage). Every trim is a `peak` clamp with its own reason and replays exactly. Older runs replay without it.
- The simulator reports each building's draw this hour before storage, plus heat pump power and hot water heater efficiency, so the limiter and the agent can size charging.
- Combined signal: 0.5 x price plus 0.5 x carbon intensity, each scaled 0 to 1 over now and the next 24 hours, in `hyperbolic/signals.py`. A flat input drops out instead of capping the signal.
- Prompt version 3 (default): the peak block, the signal and its outlook, each building's draw before storage, hours left in the month, a strategy in priority order (comfort, peak cap, then cost and carbon, with charging spread over several low hours) and a 150 character target for reasons. Versions 1 and 2 are unchanged for replay; `--prompt-version` selects them.
- Rule-based controller for version 3 with the same signal and limiter, retuned on the first week only; the 0.3.0 settings are kept as `RuleParamsV2`.
- `scripts/tune_rules.py` searches the policy and the limiter's settings together, in parallel, and requires both peaks at or below the baseline's on the tuning week.
- Viewer footer: the version now comes from `docs/assets/version.js` (refresh with `python -m hyperbolic.viewer --write-version`), which a test keeps equal to the package version; it read a hard-coded 0.2.0 before. Adds a "Built by Addison Smith · GitHub · Sixophor" credit line.
- Tests: the limiter (randomized never-above-target, clamps, battery before tank, legacy runs, a CityLearn run with trims that replays identically), the combined signal, the peak tracker, prompt version 3, the reason length guard, and a full-month rule-based dry run.

Full month against the committed baseline:

| CityLearn KPI (district) | Baseline | 0.3.0 rule-based | 0.3.0 live, Haiku | 0.4.0 rule-based | 0.4.0 live, Haiku |
|---|---|---|---|---|---|
| cost_total | 1.000 | 0.9650 | 0.9728 | 0.9611 | 0.9765 |
| carbon_emissions_total | 1.000 | 1.0029 | 1.0059 | 0.9947 | 0.9974 |
| discomfort_proportion | 0.1714 | 0.1714 | 0.1714 | 0.1714 | 0.1714 |
| daily_peak_average | 1.000 | 1.0020 | 1.0544 | 0.9978 | 0.9525 |
| all_time_peak_average | 1.000 | 1.0000 | 1.0753 | 1.0000 | 1.0000 |
| ramping_average | 1.000 | 1.1776 | 1.1289 | 1.1309 | 0.9965 |
| daily_one_minus_load_factor_average | 1.000 | 0.9930 | 1.0254 | 0.9913 | 0.9559 |
| electricity_consumption_total | 1.000 | 1.0128 | 1.0098 | 1.0073 | 1.0098 |

Live 0.4.0 run, `claude-haiku-5-5`, full month (719 hours): the first live run to beat the baseline on cost, emissions, daily peak, ramping and load factor at equal comfort. It ties the baseline on the all-time peak, thermal resilience and unserved energy, and draws 1.0 percent more electricity (battery losses). It beats the 0.4.0 rule-based controller on daily peak (0.9525 against 0.9978), ramping and load factor; the rule-based controller still wins on cost (0.9611) and emissions (0.9947). 24 clamped hours, all battery state of charge, one of which also had a peak trim; 0 fallbacks; $0.4720 spent; replay reproduces 719 of 719 hours.

Target for 0.5: cost.


## 0.3.1 (2026-10-21)

- Fixed the viewer showing the "Sample agent" banner over a live run. The data was right (`sample` is false for a live run and true for a scripted one), but the banner's `display: flex` overrode the browser's default `[hidden] { display: none }`, so hiding it had no effect. A global `[hidden]` rule now wins.
- Tests: a live run's viewer data is not marked as a sample while a scripted run's is, and the stylesheet keeps the `[hidden]` rule.

## 0.3.0 (2026-10-21)

The first live run in 0.2.0 tied the baseline to the last decimal. The action path was working; the agent held the baseline because the prompt misled it. This release fixes that and gives the agent what it needs to beat the reference.

Root cause:

- CityLearn's forecasts in this dataset are 6, 12 and 24 hours ahead. The 0.2.0 prompt labeled them as the next 1, 2 and 3 hours, so the model saw cheap hours where the evening price spike was coming.
- There was no carbon outlook (the dataset has no carbon forecast), no storage sizes and no strategy, and the prompt's framing rewarded holding the baseline.

Changes:

- Prompt version 2, now the default: a 24 hour price outlook built from the exact price forecasts already received (same hour yesterday where none covers an hour yet), a 24 hour carbon outlook from observed values (same hour yesterday), a now/min/max/rank summary of both, battery and tank capacity, power and state of charge, correct forecast labels, and a plain strategy: charge the battery cheap and clean, discharge into the peak sized to the building's own load, mostly leave the tank alone, and keep cooling at the baseline unless a small pre-cool is clearly safe.
- Prompt version 1 kept unchanged; run manifests record `prompt_version` and replay uses it, so 0.2.0 runs replay byte for byte. `--prompt-version 1` selects it for new runs.
- Envelope: cooling may not move more than 0.15 from the ideal-load baseline, and an unoccupied building near the bottom of its band gets no extra cooling. Older manifests replay with the 0.2.0 rules.
- `ScriptedSupervisor` is now a rule-based controller for prompt version 2, with its settings in `RuleParams`, and runs through the same request, reply, envelope and simulator path as a live model. `--scripted` no longer injects faults; `--inject-faults` does.
- `scripts/tune_rules.py` picks the rule settings on the first week only. There is no other 2023 dataset offline, so the full month is kept for reporting.
- The simulator state now carries the forecast horizons and each building's storage capacity and power.
- Runs of two days or more must cover whole days (for example 167 or 719 hours); other lengths crash CityLearn 3.0.2's outage model, and the CLI now says so up front.
- Tests: the forecast horizon regression, the outlook never using unseen data, both prompt versions, a cooling offset moving indoor temperatures through the envelope, a 24 hour rule-based dry run on CityLearn with replay, and the scripted fault switch.

Results, full month against the committed baseline:

| CityLearn KPI (district) | Baseline | 0.2.0 live, Haiku | 0.3.0 rule-based check |
|---|---|---|---|
| cost_total | 1.000 | 1.0008 | 0.9650 |
| carbon_emissions_total | 1.000 | 1.0045 | 1.0029 |
| discomfort_proportion | 0.1714 | 0.1714 | 0.1714 |
| daily_peak_average | 1.000 | 1.0006 | 1.0020 |
| ramping_average | 1.000 | 1.0288 | 1.1776 |

The rule-based check runs the scripted policy through the full action path with no model calls: 0 clamped and 0 fallback hours, and it replays deterministically.

Live 0.3.0 run, `claude-haiku-5-5`, full month (719 hours):

| CityLearn KPI (district) | Baseline | 0.3.0 rule-based check | 0.3.0 live, Haiku |
|---|---|---|---|
| cost_total | 1.000 | 0.9650 | 0.9728 |
| carbon_emissions_total | 1.000 | 1.0029 | 1.0059 |
| discomfort_proportion | 0.1714 | 0.1714 | 0.1714 |
| electricity_consumption_total | 1.000 | 1.0128 | 1.0098 |
| ramping_average | 1.000 | 1.1776 | 1.1289 |
| daily_peak_average | 1.000 | 1.0020 | 1.0544 |
| all_time_peak_average | 1.000 | 1.0000 | 1.0753 |

17 clamped hours (all battery state of charge), 1 fallback hour (a reason over 300 characters), $0.3934 spent, and replay reproduces 719 of 719 hours.

The live agent beat the baseline on cost but not the rule-based controller: cost 0.9728 against 0.9650, and emissions 1.0059 against 1.0029, both above the baseline's 1.000. Comfort was identical to the baseline. Its night charging also raised peaks: the daily peak rose 5.4 percent and the all-time peak 7.5 percent, where the rule-based controller left both within 0.2 percent of the baseline.

Targets for 0.4: emissions and peaks.

## 0.2.0 (2026-10-21)

Replaces the hosted BOPTEST backend with CityLearn, which runs entirely on one machine.

- CityLearn 3.0.2 backend on the official 2023 challenge local evaluation dataset (3 buildings, 719 hourly decisions), shipped in the package so runs and tests need no download and no server.
- Baseline is CityLearn's no-control reference, the one every CityLearn KPI is normalized against. A real full-episode baseline run is committed in `results/baseline`.
- The supervisor decides every hour for all buildings in one call: heat pump, hot water tank and battery.
- Envelope rewritten for the district: action ranges from CityLearn's action space, per-device ramp limits, state of charge limits, a comfort rule at the band edges, and fallback to the baseline action. A test proves the baseline action reproduces the no-control KPIs.
- KPIs come from CityLearn's own `evaluate()`.
- Viewer reworked into the district: building tiles with comfort, storage and grid draw, price on the timeline, cost, emissions and discomfort counters.
- `python -m hyperbolic` entry point; `compare` pairs a new agent run with the committed baseline.
- Fixed the cross-process viewer determinism test on Windows by passing the parent environment through.
- Removed the BOPTEST client, test case definitions, mock simulator and BOPTEST data file.

## 0.1.0 (2026-10-21)

First release.

- BOPTEST client for the BOPTEST-Service API: select, scenario, step, advance, forecast, KPI, stop, with retries.
- Baseline runner (stock control, no overwrites) and agent runner (hourly supervisory setpoints) for `multizone_office_simple_air`, on the `typical_heat_day` and `peak_heat_day` scenarios with dynamic electricity pricing.
- Safety envelope in plain code: strict schema validation, equipment ranges, per-step rate limits, comfort band clamps, deadband, and fallback to stock control on any invalid or missing reply. Every clamp and fallback is logged with its reason.
- Model access through `HYPERBOLIC_ANTHROPIC_KEY` with `TRIAGE_ANTHROPIC_KEY` as fallback, Haiku by default and Sonnet by flag, and a hard per-run budget (default 2 USD) checked against the worst case before every call.
- Run folders that record every request, reply, simulator response and decision, and `hyperbolic replay` to reproduce a run with zero API or simulator calls.
- `hyperbolic compare` for the KPI comparison and the viewer data.
- Static replay viewer and scorecard in `docs/`, shipped with a labeled sample from a recorded offline mock run.
- Offline test suite and GitHub Actions CI with an author check.
