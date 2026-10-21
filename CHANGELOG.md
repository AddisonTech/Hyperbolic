# Changelog

## 0.4.0 (2026-10-21)

The 0.3.0 live month beat the baseline on cost but not the rule-based controller, raised emissions and set new peaks. In that run the model charged most at hours 19 to 24: those hours tie for the lowest price, but they are high-carbon and sit on the district's own evening load peak. 16 of 30 days got a higher daily peak, and the month's peak rose 7.5 percent.

- Peak limiter in the envelope: battery then tank charging is trimmed so the district's draw stays at or below the peak target, the higher of today's peak so far and the forecast of today's peak (lowest of the last two days' peaks before storage). Every trim is a `peak` clamp with its own reason and replays exactly. Older runs replay without it.
- The simulator reports each building's draw this hour before storage, plus heat pump power and hot water heater efficiency, so the limiter and the agent can size charging.
- Combined signal: 0.5 x price plus 0.5 x carbon intensity, each scaled 0 to 1 over now and the next 24 hours, in `hyperbolic/signals.py`. A flat input drops out instead of capping the signal.
- Prompt version 3 (default): the peak block, the signal and its outlook, each building's draw before storage, hours left in the month, a strategy in priority order (comfort, peak cap, then cost and carbon, with charging spread over several low hours) and a 150 character target for reasons. Versions 1 and 2 are unchanged for replay; `--prompt-version` selects them.
- Rule-based controller for version 3 with the same signal and limiter, retuned on the first week only; the 0.3.0 settings are kept as `RuleParamsV2`.
- `scripts/tune_rules.py` searches the policy and the limiter's settings together, in parallel, and requires both peaks at or below the baseline's on the tuning week.
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
