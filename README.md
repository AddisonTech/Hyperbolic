# Hyperbolic

An AI supervisor that runs a simulated district and tries to beat the no-control reference on cost, emissions and comfort.

Hyperbolic runs [CityLearn](https://github.com/citylearn-project/CityLearn), an open source district energy simulator, entirely on one machine. Every simulated hour it reads CityLearn's observations, forecasts and prices for all buildings, asks a language model for one action per device, passes the answer through a deterministic safety envelope, and applies what survives. Both the agent and the reference are scored by CityLearn's own KPI evaluation, so the numbers come from the benchmark, not from this project.

Replay viewer and scorecard: `docs/index.html`, published with GitHub Pages. The baseline shown there is a real CityLearn run. Until a live agent run is committed, the agent side is a clearly labeled sample made with scripted replies.

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
| Observations | Hour, day type, outdoor temperature and solar with 1 to 3 hour forecasts, electricity price with forecasts, carbon intensity, and per building indoor temperature, setpoint, occupants, loads, solar, storage charge, net grid draw, outage flag |
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

## How the safety envelope works

`hyperbolic/envelope.py`. Every reply goes through these steps before CityLearn sees anything:

1. **Schema validation.** One JSON object, strict Pydantic model: a short reason plus `cooling`, `dhw` and `battery` for every building. Each value is a finite number or `null`. Extra or missing fields, strings, booleans, NaN and infinity are rejected.
2. **Action range.** The configured range intersected with CityLearn's own action space.
3. **Rate limit.** At most 0.35 per hour for cooling and 0.5 for the tank and battery, measured from last hour's action or from this hour's baseline action, whichever is closer. Returning to the baseline is never too fast.
4. **State of charge.** No charge or discharge that would take a battery or tank outside 10 to 95 percent.
5. **Comfort.** In occupied hours within 0.5 C of the comfort band edge, cooling may not drop below the baseline when warm or rise above it when cool.

`null` keeps the baseline action for that device. An invalid reply, a timeout, a refusal, a truncated reply or a client error falls back to the baseline action everywhere for that hour. Every clamp and every fallback is logged with the requested value, the applied value and the reason, and both are highlighted in the viewer.

The baseline action under active control is storage idle and the heat pump at the fraction of nominal power that delivers the ideal cooling load. A test checks that running those actions every hour reproduces CityLearn's no-control KPIs (1.000 to six decimals, identical discomfort), so a fallback hour is a no-control hour.

## Model access and budget

- Key from `HYPERBOLIC_ANTHROPIC_KEY`, falling back to `TRIAGE_ANTHROPIC_KEY`. The key lives only in the environment, never in a file, log or run folder (a test checks this).
- Model: `--model haiku` (default, `claude-haiku-5-5`) or `--model sonnet` (`claude-sonnet-5-5`). Structured JSON output, low effort, 2000 max tokens.
- Hard budget per run, `--budget` (default 2.00 USD). Before every call the runner computes that call's worst case (prompt size plus full max tokens). If it could push spending past the budget, model calls stop for the rest of the run and every remaining hour uses the baseline action.
- Episode length: the full 719 hours. Measured over 719 real requests, a request averages about 4,700 characters. That puts a full Haiku run at roughly 0.24 USD, with a hard worst case of 0.83 USD, well under the default budget. The same run on Sonnet is roughly 4.80 USD, so with the default budget it will hit the budget stop partway; raise `--budget` for a full Sonnet run. Each run logs its exact token cost in `result.json`.

## How to run it

Python 3.10, 3.11 or 3.12 (CityLearn 3.0.2 needs numpy below 2, which has no Python 3.13 wheels).

CityLearn is installed with `--no-deps`. Its published pins (scikit-learn 1.2.2, openstudio, torchvision, doe_xstock) are only needed by optional features and would force a source build on Python 3.12. Hyperbolic's own dependencies are the packages CityLearn's simulation core imports.

### Windows (PowerShell, no virtual environment)

```powershell
cd C:\path\to\Hyperbolic
python --version                      # 3.10, 3.11 or 3.12
python -m pip install --no-deps CityLearn==3.0.2
python -m pip install -e ".[dev]"
python -m pytest -q

python -m hyperbolic baseline         # optional: the committed baseline is in results\baseline
python -m hyperbolic run              # Haiku, 2 USD budget, key from TRIAGE_ANTHROPIC_KEY or HYPERBOLIC_ANTHROPIC_KEY
python -m hyperbolic compare          # KPI table, rebuilds docs\data\viewer.json and viewer.js
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
| `hyperbolic run` | Runs the supervisor through the envelope. `--model sonnet`, `--budget 5`, `--hours 24` for a short run, `--scripted` for no API calls. |
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

`python -m pytest -q` runs fully offline. Envelope rules and runner logic run against a small fake district for speed; the backend, the CLI and the no-control equivalence run against real CityLearn on the shipped dataset; replay and the viewer builder run against CityLearn runs recorded in `tests/fixtures`. Covered: every envelope rule, malformed and schema-breaking replies, fallback on invalid, missing and refused replies, the budget stop, key handling, deterministic replay and tamper detection, replay with CityLearn not even importable, and byte-identical viewer data from the same files in one process or two.

CI (GitHub Actions) runs the tests on Python 3.10 and 3.12 with CPU-only torch, a repository rules check, and an author check that fails if any commit in a push or pull request was not authored by AddisonTech.

## Honest limits

- **Simulator only.** CityLearn models buildings with data-driven load profiles and an LSTM for indoor temperature. Beating its reference is evidence worth investigating, not proof of field savings.
- **The sample agent is not a result.** The agent side in the viewer comes from scripted rules until a live run is committed.
- **The reference is a modest bar.** No storage use and an ideal-load heat pump. Any sensible battery and tank schedule should beat it on cost. The interesting questions are emissions, peaks and comfort at the same time.
- **The comfort reference is not perfect.** CityLearn's own no-control run already leaves 17 percent of occupied hours outside the band, mostly too cool.
- **Hourly supervision only.** One decision per hour, three devices per building.
- **The envelope is conservative by design.** It caps ramps and charge levels and protects comfort near the band edges, which also limits how hard any controller can push.
- **Model output varies.** Live runs are not reproducible from scratch. They are reproducible from their recorded files, which is what replay is for.
- **Costs are estimates until the first live run.** The figures above come from measured prompt sizes, not from billed tokens.

## Credits and license

MIT, see `LICENSE`.

CityLearn is developed by the Intelligent Environments Laboratory and contributors and is distributed under the MIT license. The dataset in `hyperbolic/data/citylearn_challenge_2023_phase_2_local_evaluation` is copied unchanged from the CityLearn repository (tag v3.0.2); its license is in `hyperbolic/data/CITYLEARN_LICENSE.txt`. Hyperbolic is not affiliated with the CityLearn project.
