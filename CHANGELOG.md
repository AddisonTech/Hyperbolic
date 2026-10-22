# Changelog

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
