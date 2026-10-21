# Hyperbolic

**A month of building ops in an hour.**

An AI supervisor that runs a simulated district and tries to beat the no-control reference on cost, emissions and comfort.

Hyperbolic runs [CityLearn](https://github.com/citylearn-project/CityLearn), an open source district energy simulator, entirely on one machine. Every simulated hour it reads CityLearn's observations, forecasts and prices for all buildings, asks a language model for one action per device, passes the answer through a deterministic safety envelope, and applies what survives. Both the agent and the reference are scored by CityLearn's own KPI evaluation, so the numbers come from the benchmark, not from this project.

Replay viewer and scorecard: `docs/index.html`, published with GitHub Pages. Both sides shown there are real CityLearn runs: the no-control baseline and the live 0.4.0 Haiku run (see [Results](#results)).

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

**Target for 0.5:** cost. The live agent has to beat the rule-based controller's 0.9611 while keeping emissions below 1.000, the peaks it now holds, and comfort.

## What the agent sees

Prompt version 3 (`hyperbolic/prompt.py`) is the default from 0.4.0. It keeps everything in version 2 and adds the peak block, the combined signal and hours left in the month (see [Version 0.4.0](#version-040)). Version 2, the default in 0.3.0:

- **A 24 hour price outlook from forecasts already received.** Each hour brings exact price forecasts for 6, 12 and 24 hours ahead. Kept and lined up by the hour they refer to, they cover every one of the next 24 hours after the first day. Hours not covered yet fall back to the same hour yesterday. Each value is tagged with its source.
- **A 24 hour carbon outlook** as the same hour yesterday, from observed values only. It is a guide, not a forecast.
- **A summary of both:** now, the 24 hour min and max, hours until each, and where now ranks in the coming day.
- **Storage per building:** state of charge, capacity and how far the battery can move in one hour, for the battery and the hot water tank.
- **A plain strategy:** charge the battery in the cheapest, cleanest hours and with spare solar, discharge into the price peak sized to the building's own load (exports earn nothing), mostly leave the hot water tank alone, keep cooling at the baseline unless a small pre-cool is clearly safe, and hold when nothing stands out.

Nothing reads the dataset ahead of time; the outlook is built only from observations the controller has already received. Prompt versions 1 and 2 are kept unchanged so runs recorded with 0.2.0 and 0.3.0 replay byte for byte, and `--prompt-version 1` or `2` still selects them.

## Tuning without peeking at the test month

The package ships one 2023 dataset (the phase 2 local evaluation month) and the repository has no other offline, so there is no separate 2023 tuning set. The rule-based policy's settings are chosen on the first week only (167 hourly decisions) with `python scripts/tune_rules.py`, and the full month is used only for reporting. In 0.4.0 the grid covers the signal thresholds for charging and discharging, the charge rate, peak shaving, the battery charge limits, when to stop charging before the month ends, and the limiter's target fraction and forecast window. A setting qualifies when, on that week, discomfort is no more than half a point above the baseline and both peaks are at or below the baseline's to four decimals; the qualifying setting with the lowest cost plus emissions wins. (Four decimals because the baseline action under control rounds the heat pump fraction, which by itself moves a peak ratio by about 0.00001.) In 0.3.0 the grid covered charge thresholds and rates, discharge rate, hot water tank use, pre-cooling and peak easing. The prompt's strategy was written from the same first-week evidence: pre-cooling and easing cooling in the spike both raised discomfort there, and cycling the hot water tank raised emissions, so the strategy keeps cooling near the baseline and leans on the battery.

## How the safety envelope works

`hyperbolic/envelope.py`. Every reply goes through these steps before CityLearn sees anything:

1. **Schema validation.** One JSON object, strict Pydantic model: a short reason plus `cooling`, `dhw` and `battery` for every building. Each value is a finite number or `null`. Extra or missing fields, strings, booleans, NaN and infinity are rejected.
2. **Action range.** The configured range intersected with CityLearn's own action space.
3. **Rate limit.** At most 0.35 per hour for cooling and 0.5 for the tank and battery, measured from last hour's action or from this hour's baseline action, whichever is closer. Returning to the baseline is never too fast.
4. **State of charge.** No charge or discharge that would take a battery or tank outside 10 to 95 percent.
5. **Cooling deviation (new in 0.3.0).** Cooling may not move more than 0.15 from the baseline action, the fraction that meets the ideal load. Enough to pre-cool, not enough to switch the heat pump off.
6. **Comfort.** In occupied hours within 0.5 C of the comfort band edge, cooling may not drop below the baseline when warm or rise above it when cool. From 0.3.0, an unoccupied building already near the bottom of its band gets no extra cooling either.
7. **Peak limit (new in 0.4.0).** Across the district, battery charging and then tank charging are trimmed so the district's estimated draw this hour stays at or below the peak target (the higher of today's peak so far and the forecast of today's peak). Discharging and cooling are never touched by it, and discharging earns no credit in the estimate, so it never understates the load.

Older runs replay with the rule set they were recorded with: the run's manifest stores the envelope settings, and settings missing from an old manifest take the values they had before they existed (no deviation cap or unoccupied guard before 0.3.0, no peak limit before 0.4.0).

`null` keeps the baseline action for that device. An invalid reply, a timeout, a refusal, a truncated reply or a client error falls back to the baseline action everywhere for that hour. Every clamp and every fallback is logged with the requested value, the applied value and the reason, and both are highlighted in the viewer.

The baseline action under active control is storage idle and the heat pump at the fraction of nominal power that delivers the ideal cooling load. A test checks that running those actions every hour reproduces CityLearn's no-control KPIs (1.000 to six decimals, identical discomfort), so a fallback hour is a no-control hour.

## Model access and budget

- Key from `HYPERBOLIC_ANTHROPIC_KEY`, falling back to `TRIAGE_ANTHROPIC_KEY`. The key lives only in the environment, never in a file, log or run folder (a test checks this).
- Model: `--model haiku` (default, `claude-haiku-5-5`) or `--model sonnet` (`claude-sonnet-5-5`). Structured JSON output, low effort, 2000 max tokens.
- Hard budget per run, `--budget` (default 2.00 USD). Before every call the runner computes that call's worst case (prompt size plus full max tokens). If it could push spending past the budget, model calls stop for the rest of the run and every remaining hour uses the baseline action.
- Episode length: the full 719 hours. The 0.2.0 live run averaged about 4,700 characters per request and cost 0.23 USD on Haiku. Prompt version 2 adds the 24 hour outlook and the strategy, about 7,400 characters per request, and the 0.3.0 live Haiku month cost 0.39 USD. Prompt version 3 is about 8,600 characters per request; the 0.4.0 live Haiku month cost 0.47 USD, against a hard worst case of about 0.93 USD and the default 2.00 USD budget. Sonnet costs 20 times as much per token: a full Sonnet month should cost roughly 8 to 9 USD, so under a 2.00 USD budget it stops calling the model after about a fifth of the month and the remaining hours use the baseline action. Raise `--budget` (about 10 USD) for a full Sonnet run. Each run logs its exact token cost in `result.json`.

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

.\.venv\Scripts\python -m hyperbolic run --scripted --hours 24   # 24 hour dry run, no API calls
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
| `hyperbolic baseline` | Runs CityLearn's no-control reference. |
| `hyperbolic run` | Runs the supervisor through the envelope. `--model sonnet`, `--budget 5`, `--hours 24` for a short run, `--scripted` for the rule-based policy with no API calls, `--inject-faults` with `--scripted` to exercise clamps and fallback, `--prompt-version 1` or `2` for the 0.2.0 or 0.3.0 prompt. Runs of two days or more need hours + 1 to be a whole number of days (for example 167 or 719), a limit of CityLearn 3.0.2's outage model. |
| `hyperbolic replay RUN_DIR` | Re-runs a saved run from its files with zero model or simulator calls and reports whether every decision and action matches. Exit code 1 if not. |
| `hyperbolic compare` | Pairs the latest baseline (from `runs/` or the committed `results/`) with the latest agent run (a live run wins over a scripted one), prints the KPIs and writes the viewer data. `--pair BASELINE AGENT` to choose. |

`python -m hyperbolic` works the same as `hyperbolic`. A full episode simulates in about 7 seconds; a live run takes as long as 719 model calls.

## The replay viewer

`docs/` is a static site with no build step: D3 from cdnjs, two Google Fonts, and the data in `docs/data/viewer.js` (the same content as `viewer.json`, as a script so the page also opens straight from disk).

- The headline result, stated as plainly when the agent loses.
- The district for the reference and for the agent side by side: each building as a tile with indoor temperature against its comfort band, battery and hot water tank charge, and grid draw, glowing when the envelope clamps or falls back.
- A timeline with the electricity price along the top, envelope events marked, play and pause, 1x, 10x and 60x speed, and jumps between events.
- Running cost, emissions and discomfort counters for both sides.
- Indoor temperature, district grid draw and battery charge in a rolling window that follows the playhead.
- The agent's one-line reason for every hour, with clamped and fallback hours tagged and each clamp spelled out.
- The CityLearn KPI scorecard, run cost, call count and clamp and fallback counts.

Dark by default with a light toggle, built for phones first, and it respects reduced motion. To publish it, turn on GitHub Pages: Settings, Pages, Deploy from a branch, `main`, folder `/docs`.

## Tests

`python -m pytest -q` runs fully offline. Envelope rules and runner logic run against a small fake district for speed; the backend, the CLI and the no-control equivalence run against real CityLearn on the shipped dataset; replay and the viewer builder run against CityLearn runs recorded in `tests/fixtures`. Covered: the peak limiter (never above the target in randomized trials, trims recorded as clamps, battery before tank, off for older runs, and a CityLearn run that replays identically with its trims), the combined signal, the peak tracker, the reason length guard, the forecast horizons (6, 12 and 24 hours, the 0.2.0 mislabel), the 24 hour outlook never using unseen data, all three prompt versions, 24 hour and full-month rule-based dry runs on CityLearn, a cooling offset moving indoor temperatures, every envelope rule, malformed and schema-breaking replies, fallback on invalid, missing and refused replies, the budget stop, key handling, deterministic replay and tamper detection, replay with CityLearn not even importable, and byte-identical viewer data from the same files in one process or two.

CI (GitHub Actions) runs the tests on Python 3.10 and 3.12 with CPU-only torch, a repository rules check, and an author check that fails if any commit in a push or pull request was not authored by AddisonTech.

## Honest limits

- **Simulator only.** CityLearn models buildings with data-driven load profiles and an LSTM for indoor temperature. Beating its reference is evidence worth investigating, not proof of field savings.
- **The rule-based check is not a model result.** It shows the action path can beat the reference and sets the bar for the agent. In 0.3.0 the live agent beat the baseline on cost only and did not beat the rule-based check. In 0.4.0 it beat the rule-based check on daily peak, ramping and load factor but not on cost or emissions.
- **The peak limiter uses this hour's load.** It reads the draw CityLearn is about to simulate for this hour (plug load, solar, hot water demand, cooling), the equivalent of a meter reading in a real building. The forecast of the day's peak is built only from past days. The agent itself sees only the same values the limiter uses, never the rest of the day.
- **One month, tuned on its first week.** There is no second 2023 dataset offline, so settings come from the first week of the same month. The other three weeks are unseen, but they share the same tariff and climate.
- **The reference is a modest bar.** No storage use and an ideal-load heat pump. Any sensible battery and tank schedule should beat it on cost. The interesting questions are emissions, peaks and comfort at the same time.
- **The comfort reference is not perfect.** CityLearn's own no-control run already leaves 17 percent of occupied hours outside the band, mostly too cool.
- **Hourly supervision only.** One decision per hour, three devices per building.
- **The envelope is conservative by design.** It caps ramps and charge levels and protects comfort near the band edges, which also limits how hard any controller can push.
- **Model output varies.** Live runs are not reproducible from scratch. They are reproducible from their recorded files, which is what replay is for.

## Credits and license

MIT, see `LICENSE`.

CityLearn is developed by the Intelligent Environments Laboratory and contributors and is distributed under the MIT license. The dataset in `hyperbolic/data/citylearn_challenge_2023_phase_2_local_evaluation` is copied unchanged from the CityLearn repository (tag v3.0.2); its license is in `hyperbolic/data/CITYLEARN_LICENSE.txt`. Hyperbolic is not affiliated with the CityLearn project.
