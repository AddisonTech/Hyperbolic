# Unpublished live runs

Live run folders kept in `runs/` that no CHANGELOG entry reports. `scripts/check_repo.py` fails when a live run folder on disk is neither named in CHANGELOG.md by its path under `runs/` nor listed here with a reason. Added in 0.15.2; see the 0.15.2 entry in CHANGELOG.md.

Every run below is on the phase 2 local evaluation month with `claude-haiku-5-5`, completed its hours, and replays every hour with 0 API calls. Together they cost $0.111544. No folder name of theirs appears in any revision of README.md, CHANGELOG.md, HOLDOUT.md, `docs/` or `results/`, and every number there that equals one of their KPIs or costs at six decimals comes from another run or the baseline. Each started under the same tool version as the full month that followed it.

| Run folder | Tool version | Prompt version | Started (UTC) | Hours | Cost | Reason |
|---|---|---|---|---|---|---|
| `runs/citylearn_challenge_2023_phase_2_local_evaluation_agent_citylearn_20261021T164149Z` | 0.2.0 | none | 2026-10-21 16:41 | 6 | $0.0019 | 6-hour run started 2 minutes 28 seconds before the 0.2.0 full month (`runs/citylearn_challenge_2023_phase_2_local_evaluation_agent_citylearn_20261021T164417Z`). No entry reports it. |
| `runs/citylearn_challenge_2023_phase_2_local_evaluation_agent_citylearn_20261021T184216Z` | 0.3.0 | 2 | 2026-10-21 18:42 | 24 | $0.0118 | 24-hour run started 14 minutes 13 seconds before the 0.3.0 full month. No entry reports it. |
| `runs/citylearn_challenge_2023_phase_2_local_evaluation_agent_citylearn_20261021T204718Z` | 0.4.0 | 3 | 2026-10-21 20:47 | 24 | $0.0146 | 24-hour run started 2 minutes 36 seconds before the 0.4.0 full month. No entry reports it. |
| `runs/smoke/citylearn_challenge_2023_phase_2_local_evaluation_agent_citylearn_20261022T152220Z` | 0.6.0 | 4 | 2026-10-22 15:22 | 24 | $0.0177 | 24-hour smoke run started 9 minutes 52 seconds before the 0.6.0 full month. No entry reports it. |
| `runs/smoke/citylearn_challenge_2023_phase_2_local_evaluation_agent_citylearn_20261022T175206Z` | 0.7.0 | 5 | 2026-10-22 17:52 | 24 | $0.0202 | 24-hour smoke run started 5 minutes 31 seconds before the 0.7.0 full month. No entry reports it. |
| `runs/smoke/citylearn_challenge_2023_phase_2_local_evaluation_agent_citylearn_20261022T202117Z` | 0.8.0 | 6 | 2026-10-22 20:21 | 24 | $0.0174 | 24-hour smoke run started 2 hours 5 minutes 47 seconds before the 0.8.0 full month. No entry reports it. |
| `runs/smoke/citylearn_challenge_2023_phase_2_local_evaluation_agent_citylearn_20261023T135313Z` | 0.9.0 | 7 | 2026-10-23 13:53 | 24 | $0.0146 | 24-hour smoke run started 1 minute 17 seconds before the 0.9.0 full month. No entry reports it. |
| `runs/smoke/citylearn_challenge_2023_phase_2_local_evaluation_agent_citylearn_20261023T155552Z` | 0.10.0 | 8 | 2026-10-23 15:55 | 24 | $0.0133 | 24-hour smoke run started 6 minutes 0 seconds before the 0.10.0 phase 2 month. No entry reports it. |
