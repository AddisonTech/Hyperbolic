# Changelog

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
