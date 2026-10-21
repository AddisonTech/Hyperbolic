# Hyperbolic

An AI supervisor that runs a simulated building and tries to beat the stock control sequence on energy, cost, and comfort.

Hyperbolic drives a [BOPTEST](https://github.com/ibpsa/project1-boptest) test case through the hosted BOPTEST service at `api.boptest.net`. Every simulated hour it reads the building's measurements and forecasts, asks a language model for supervisory setpoints, passes the answer through a deterministic safety envelope, and writes what survives to the simulator. The result is graded by BOPTEST's own KPIs against the same test case running its stock control.

Replay viewer and scorecard: `docs/index.html`, published with GitHub Pages. It ships with a clearly labeled sample built from a recorded offline mock run until real runs are added.

**This is a simulator project.** Nothing here connects to a real building, BAS, or customer system.

## Why it is built this way

The same discipline as a production alarm triage agent:

- **Deterministic code does the safety work.** The model never writes to the simulator directly. Plain Python checks every value against hard limits first.
- **The model only makes the supervisory call.** Zone heating and cooling setpoints and the supply air temperature setpoint, once an hour. Dampers, valves, fans and the economizer stay with the stock local loops.
- **Every decision is logged and replayable.** Each run folder holds the full request, the raw reply, the tokens, the cost, every clamp and fallback with its reason, and every simulator response. `hyperbolic replay` re-runs the whole thing with zero API calls and zero simulator calls and checks it reproduces exactly.
- **Results are graded honestly.** Scores are BOPTEST's KPIs on BOPTEST's standard scenarios, so they are comparable to published results. The viewer states a loss as plainly as a win.

## Test case and scenarios

`multizone_office_simple_air`: the middle floor of a Chicago office, five zones (north, east, south, west, core, 1662.66 m2), one VAV air handler with hot water reheat from an air-to-water heat pump and an air-cooled chiller. The stock sequence holds 20/24 C occupied (06:00 to 19:00) and 12/30 C unoccupied with a 12 C supply air setpoint.

| What | Points |
|---|---|
| Overwritten by the supervisor | `hvac_oveZonSup{Nor,Eas,Sou,Wes,Cor}_TZonHeaSet_u`, `..._TZonCooSet_u`, `hvac_oveAhu_TSupSet_u` |
| Left to stock control | AHU `dpSet`, `yFan`, `yCoo`, `yHea`, `yOA`, `yRet`, pumps, zone `yDam`, `yReaHea` |
| Read every hour | zone temperatures and CO2, supply air temperature, outdoor temperature, HVAC electric power |
| Forecast, 12 hours ahead | `TDryBul`, `HGloHor`, `PriceElectricPowerDynamic`, `Occupancy[zone]`, `LowerSetp[zone]`, `UpperSetp[zone]` |
| KPIs | `tdis_tot`, `idis_tot`, `ener_tot`, `cost_tot`, `emis_tot`, `pele_tot`, `pgas_tot`, `pdih_tot`, `time_rat` |

Scenarios: `typical_heat_day` and `peak_heat_day`, each a two-week test after a one-week warmup (336 hourly decisions), with `electricity_price=dynamic`. Any other BOPTEST time period can be selected with `--scenario`.

API used: `POST testcases/{name}/select`, `PUT scenario/{id}`, `PUT step/{id}`, `POST advance/{id}`, `PUT forecast/{id}`, `GET kpi/{id}`, `PUT stop/{id}`, plus `status`, `inputs`, `measurements`, `forecast_points`, `initialize` and `results` in the client.

## How the safety envelope works

`hyperbolic/envelope.py`. Every reply goes through these steps before anything reaches the simulator:

1. **Schema validation.** The reply must be one JSON object matching a strict Pydantic model: a short reason, heat and cool setpoints for each of the five zones, and a supply air setpoint. Each value is a finite number or `null`. Extra fields, missing fields, strings, booleans, NaN and infinity are all rejected.
2. **Equipment range.** Zone heating 12 to 24 C, zone cooling 21 to 30 C, supply air 12 to 18 C, and supply air only during occupied hours.
3. **Rate limit.** A setpoint may move at most 2 K per hour (1.5 K for supply air), measured from where it was last hour or from where the stock schedule's own step would carry it. A preheat ramp that meets the 06:00 occupancy step is not penalized. A jump is.
4. **Comfort band.** Heating may never sit below BOPTEST's comfort band lower limit and cooling never above its upper limit, read from the forecast each hour. The comfort clamp always wins over the rate limit.
5. **Deadband.** Cooling stays at least 1 K above heating.

`null` hands that point back to the stock control. An invalid reply, a timeout, a refusal, a truncated reply or a client error hands *every* point back to stock control for that hour and resets the rate limit memory. Every clamp and every fallback is logged with the requested value, the applied value and the reason, and both show up highlighted in the viewer.

## Model access and budget

- Key from `HYPERBOLIC_ANTHROPIC_KEY`, falling back to `TRIAGE_ANTHROPIC_KEY`. The key lives only in the environment. It is never written to a file, a log or a run folder (a test checks this).
- Model: `--model haiku` (default, `claude-haiku-5-5`) or `--model sonnet` (`claude-sonnet-5-5`). Structured JSON output, low effort, 2000 max tokens.
- Hard budget per scenario run, `--budget` (default 2.00 USD). Before every call the runner computes the worst case for that call (prompt size plus full max tokens). If the call could push spending past the budget, model calls stop for the rest of the run and every remaining hour falls back to stock control.
- Rough cost per 336-hour scenario from the measured prompt size: Haiku about 0.16 USD (worst case 0.40). Sonnet about 3 USD (worst case 8), so with the default budget a Sonnet run will hit the budget stop partway through. Raise `--budget` for Sonnet if you want the full two weeks.

## How to run it

Python 3.10 or newer.

### Windows (PowerShell)

```powershell
git clone https://github.com/AddisonTech/Hyperbolic.git
cd Hyperbolic
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"

# Offline check first: mock simulator, scripted replies, no network, no key
python -m pytest -q
hyperbolic baseline --mock --scenario typical_heat_day --hours 24 --runs-dir runs-mock
hyperbolic run --mock --scenario typical_heat_day --hours 24 --runs-dir runs-mock

# Live: BOPTEST plus the model
$env:HYPERBOLIC_ANTHROPIC_KEY = "your key"
hyperbolic baseline                 # stock control, both scenarios
hyperbolic run                      # agent, both scenarios, Haiku, 2 USD budget per scenario
hyperbolic compare                  # KPI table, rebuilds docs/data/viewer.json and viewer.js
Get-ChildItem runs | Where-Object Name -like "*agent*" | ForEach-Object { hyperbolic replay $_.FullName }
```

### macOS or Linux

```bash
python -m venv .venv && . .venv/bin/activate && pip install -e ".[dev]"
export HYPERBOLIC_ANTHROPIC_KEY="your key"
hyperbolic baseline && hyperbolic run && hyperbolic compare
```

### Commands

| Command | What it does |
|---|---|
| `hyperbolic baseline` | Runs the test case's own control, no overwrites. |
| `hyperbolic run` | Runs the supervisor through the envelope. `--model sonnet`, `--budget 5`, `--scripted` for no API calls. |
| `hyperbolic replay RUN_DIR` | Re-runs a saved run from its files, zero API and simulator calls, and reports whether every decision and overwrite matches. Exit code 1 if not. |
| `hyperbolic compare` | Picks the latest baseline and agent run per scenario (BOPTEST runs win over mock runs), prints the KPI comparison and writes the viewer data. |

Shared options: `--scenario` (repeatable), `--price`, `--hours` for a partial run, `--mock` for the offline simulator, `--url` for a self-hosted BOPTEST, `--runs-dir`.

Each BOPTEST run is two simulated weeks. On the public service expect roughly tens of minutes per scenario, longer when the service is busy. The agent run adds one model call per hour.

## The replay viewer

`docs/` is a static site with no build step: D3 from cdnjs, two Google Fonts, and the data in `docs/data/viewer.js` (the same content as `viewer.json`, as a script so the page also opens straight from disk).

- A headline result per scenario, stated as plainly when the agent loses.
- The floor plan for stock control and for the agent side by side, each zone shaded against its comfort band, with a glow when the envelope clamps a decision or falls back.
- Play, pause, a scrubber with hour and day markers, 1x, 10x and 60x speed, and jumps to the previous or next envelope event.
- Running energy, cost and discomfort counters for both sides, read from BOPTEST's own KPIs at every hour.
- Zone and supply air traces with the comfort band and setpoints, in a rolling window that follows the playhead.
- The agent's one-line reason for every hour, with clamped and fallback hours tagged and each clamp spelled out.
- The BOPTEST KPI scorecard per scenario, the run cost, call count and clamp and fallback counts.

Dark by default with a light toggle, built for phones first, and it respects reduced motion. To publish it, turn on GitHub Pages for the repository: Settings, Pages, Deploy from a branch, `main`, folder `/docs`.

To replace the sample, run the live commands above, then commit `docs/data`. `compare` also accepts explicit pairs: `hyperbolic compare --pair runs/<baseline> runs/<agent>`.

## Tests

`python -m pytest -q` runs fully offline against the mock simulator, a mocked HTTP transport for the BOPTEST client, and recorded replies in `tests/fixtures`. They cover the envelope (out of range, too fast, below comfort, deadband, malformed and schema-breaking replies, NaN), fallback on invalid, missing and refused replies, the budget stop, key handling, deterministic replay and tamper detection, the BOPTEST client against the documented response shapes, the CLI end to end, and a check that the viewer data builder produces byte-identical output from the same replay files every time.

CI (GitHub Actions) runs the tests on Python 3.10 and 3.12, a repository rules check, and an author check that fails if any commit in a push or pull request was not authored by AddisonTech.

## Honest limits

- **Simulator only.** BOPTEST is a high-quality emulator, not a building. Beating its stock control is evidence worth investigating, not proof of field savings.
- **The sample is not a result.** The shipped viewer data comes from `hyperbolic/mock.py`, a small thermal model written for offline testing, with scripted replies standing in for the model. Its numbers mean nothing about BOPTEST or about any model's ability.
- **No live run has been recorded yet.** Version 0.1.0 was built and tested offline. The first live run is the first real result.
- **The stock control is a modest bar.** This test case's stock sequence is a schedule-based ASHRAE 2006 style sequence, not Guideline 36. Winning against it is easier than winning against a well tuned modern sequence.
- **Hourly supervision only.** One decision per hour cannot catch fast events. Lower level control is untouched.
- **The envelope is conservative by design.** It never lets setpoints leave the comfort band, so savings can only come from supply air reset, preheat and precool timing, and setpoint placement inside the band.
- **Model output varies.** Live runs are not reproducible from scratch. They are reproducible from their recorded files, which is what replay is for.
- **The stock schedule used by the rate limit is the documented occupied and unoccupied schedule.** The simulator's warm-up and night setback modes are not modeled in the envelope.

## Data and license

MIT, see `LICENSE`. `hyperbolic/data/mzosa_hourly_days_0_35.csv` is an extract of the BOPTEST test case data used only by the offline mock, redistributed under BOPTEST's license (`hyperbolic/data/BOPTEST_LICENSE.txt`). BOPTEST is developed by IBPSA Project 1.
