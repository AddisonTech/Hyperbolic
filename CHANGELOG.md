# Changelog

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
