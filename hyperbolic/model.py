"""Model access: key lookup, pricing, budget, and the supervisors.

LiveSupervisor     calls the Messages API.
ScriptedSupervisor returns deterministic rule-based replies for offline runs and tests.
HoldSupervisor     always keeps the baseline action (the live page's baseline option).
ReplaySupervisor   serves recorded replies from a run directory, with zero API calls.
RecordedReplySupervisor
                   serves a recorded run's replies hour by hour whatever the request, so the
                   same answers can be sent through other envelope rules (an evaluation, never
                   a recorded run).
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from . import district as dc

KEY_ENV_VARS = ("HYPERBOLIC_ANTHROPIC_KEY", "TRIAGE_ANTHROPIC_KEY")

# USD per million tokens (input, output).
MODELS = {
    "haiku": {"id": "claude-haiku-5-5", "input_per_mtok": 0.10, "output_per_mtok": 0.50},
    "sonnet": {"id": "claude-sonnet-5-5", "input_per_mtok": 2.00, "output_per_mtok": 10.00},
}
DEFAULT_MODEL = "haiku"
DEFAULT_BUDGET_USD = 2.00
DEFAULT_MAX_TOKENS = 2000
DEFAULT_EFFORT = "low"


class KeyMissing(RuntimeError):
    pass


def resolve_api_key(env: dict[str, str] | None = None) -> tuple[str, str]:
    """Return (key, name of the variable it came from). The key is never logged."""
    env = os.environ if env is None else env
    for name in KEY_ENV_VARS:
        value = (env.get(name) or "").strip()
        if value:
            return value, name
    raise KeyMissing(f"set {KEY_ENV_VARS[0]} (or {KEY_ENV_VARS[1]}) in the environment")


def request_sha256(request: dict) -> str:
    blob = json.dumps(request, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(blob.encode()).hexdigest()


def call_cost_usd(model_key: str, input_tokens: int, output_tokens: int) -> float:
    p = MODELS[model_key]
    return (input_tokens * p["input_per_mtok"] + output_tokens * p["output_per_mtok"]) / 1_000_000


def worst_case_cost_usd(model_key: str, request: dict) -> float:
    """Upper bound for one call: about 3 characters per input token, full max_tokens output."""
    chars = len(json.dumps(request, ensure_ascii=False))
    return call_cost_usd(model_key, math.ceil(chars / 3), int(request.get("max_tokens", DEFAULT_MAX_TOKENS)))


@dataclass
class Budget:
    limit_usd: float
    spent_usd: float = 0.0
    stopped: bool = False
    stop_reason: str | None = None

    def allows(self, next_call_worst_case: float) -> bool:
        if self.stopped:
            return False
        if self.spent_usd + next_call_worst_case > self.limit_usd:
            self.stopped = True
            self.stop_reason = (
                f"budget stop: spent ${self.spent_usd:.4f} of ${self.limit_usd:.2f}, "
                f"next call could cost up to ${next_call_worst_case:.4f}"
            )
            return False
        return True

    def charge(self, usd: float) -> None:
        self.spent_usd += usd


@dataclass
class CallResult:
    text: str | None
    input_tokens: int = 0
    output_tokens: int = 0
    stop_reason: str | None = None
    error: str | None = None
    model: str | None = None
    latency_s: float = 0.0
    extra: dict[str, Any] = field(default_factory=dict)


class Supervisor(Protocol):
    kind: str
    model_key: str

    def call(self, step: int, request: dict) -> CallResult: ...


class LiveSupervisor:
    kind = "live"

    def __init__(self, model_key: str = DEFAULT_MODEL, api_key: str | None = None, timeout_s: float = 90.0) -> None:
        import anthropic  # imported here so offline use never needs the SDK configured

        if api_key is None:
            api_key, _ = resolve_api_key()
        self.model_key = model_key
        self._anthropic = anthropic
        self._client = anthropic.Anthropic(api_key=api_key, timeout=timeout_s, max_retries=2)

    def call(self, step: int, request: dict) -> CallResult:
        a = self._anthropic
        t0 = time.monotonic()
        try:
            resp = self._client.messages.create(**request)
        except a.APIStatusError as exc:
            return CallResult(None, error=f"API status {exc.status_code}: {type(exc).__name__}",
                              latency_s=time.monotonic() - t0)
        except a.APIConnectionError as exc:
            return CallResult(None, error=f"API connection error: {type(exc).__name__}",
                              latency_s=time.monotonic() - t0)
        latency = time.monotonic() - t0
        usage = resp.usage
        result = CallResult(
            text=None,
            input_tokens=int(usage.input_tokens or 0) + int(getattr(usage, "cache_read_input_tokens", 0) or 0)
            + int(getattr(usage, "cache_creation_input_tokens", 0) or 0),
            output_tokens=int(usage.output_tokens or 0),
            stop_reason=resp.stop_reason,
            model=resp.model,
            latency_s=latency,
        )
        if resp.stop_reason == "refusal":
            result.error = "model declined the request"
            return result
        if resp.stop_reason == "max_tokens":
            result.error = "reply cut off at max_tokens"
            return result
        result.text = next((b.text for b in resp.content if getattr(b, "type", None) == "text"), None)
        return result


class ReplayMismatch(RuntimeError):
    pass


class ReplaySupervisor:
    """Serves recorded replies. Fails loudly if the request differs from the recording."""

    kind = "replay"

    def __init__(self, calls_path: Path, model_key: str) -> None:
        self.model_key = model_key
        self._by_step: dict[int, dict] = {}
        if calls_path.exists():
            for line in calls_path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    rec = json.loads(line)
                    self._by_step[int(rec["step"])] = rec

    def call(self, step: int, request: dict) -> CallResult:
        rec = self._by_step.get(step)
        if rec is None:
            raise ReplayMismatch(f"step {step}: no recorded call")
        sha = request_sha256(request)
        if sha != rec["request_sha256"]:
            raise ReplayMismatch(f"step {step}: request differs from recording")
        reply = rec["reply"]
        return CallResult(
            text=reply.get("text"),
            input_tokens=reply.get("input_tokens", 0),
            output_tokens=reply.get("output_tokens", 0),
            stop_reason=reply.get("stop_reason"),
            error=reply.get("error"),
            model=reply.get("model"),
        )


class RecordedReplySupervisor:
    """Answers each hour with the reply a recorded run got for that hour, without checking the
    request. Used to send a live run's own actions through different envelope rules
    (scripts/evaluate_hold.py); with the run's own rules it reproduces the run exactly."""

    kind = "recorded"

    def __init__(self, calls_path: Path, model_key: str) -> None:
        self.model_key = model_key
        self._inner = ReplaySupervisor(calls_path, model_key)

    def call(self, step: int, request: dict) -> CallResult:
        rec = self._inner._by_step.get(step)
        if rec is None:
            return CallResult(None, error="no recorded reply for this hour")
        reply = rec["reply"]
        return CallResult(
            text=reply.get("text"),
            input_tokens=reply.get("input_tokens", 0),
            output_tokens=reply.get("output_tokens", 0),
            stop_reason=reply.get("stop_reason"),
            error=reply.get("error"),
            model=reply.get("model"),
        )


@dataclass(frozen=True)
class RuleParams:
    """Knobs of the rule-based policy for prompt version 3 observations. Defaults are the
    values picked on the first week only (scripts/tune_rules.py); the full month is never
    used to choose them."""

    charge_rank: float = 0.15          # grid charging when at most this share of the next 24 h has a lower signal
    charge_max_signal: float = 0.15    # ... and the combined signal now is at most this
    charge_rate: float = 0.3           # battery fraction per hour when charging, spread over the low hours
    discharge_min_signal: float = 0.55 # discharge when the combined signal now is at least this
    discharge_rate: float = 0.8        # most battery fraction per hour when discharging
    shave: float = 0.0                 # also discharge once district load reaches this share of the
                                       # forecast peak; 0 turns peak shaving off
    soc_target: float = 0.95
    soc_reserve: float = 0.1
    solar_soak: bool = True            # store solar the building would otherwise export for nothing
    endgame_hours: int = 12            # no grid charging this close to the end of the month
    max_step: float = 0.5              # largest storage move per hour, the envelope's rate limit
    min_move: float = 0.01             # storage moves smaller than this are skipped


@dataclass(frozen=True)
class StrategyParams:
    """Numbers in the prompt version 4 strategy, which strategy_plan_v4 executes literally and the
    prompt states. Chosen on the tuning dataset (scripts/tune_strategy.py), never on the reported
    month."""

    cold_margin_c: float = 0.5         # an occupied room this far below its setpoint is too cold
    cold_trim: float = 0.1             # ... and its cooling is cut up to this far below the baseline action
    cold_ramp_c: float = 1.0           # the cut grows from 0 to cold_trim over this many degrees
                                       # beyond cold_margin_c; 0 cuts it all at once
    charge_rate: float = 0.15          # battery fraction per hour when charging from the grid
    shave: float = 0.9                 # also discharge once district load reaches this share of the
                                       # forecast peak; 0 turns peak shaving off
    even_discharge: bool = False       # spread the usable charge over the top-price hours left
    soc_target: float = 0.95
    max_step: float = 0.5              # largest storage move per hour, the envelope's rate limit
    min_move: float = 0.01             # storage moves smaller than this are skipped


@dataclass(frozen=True)
class StrategyParamsV5:
    """Numbers in the prompt version 5 strategy: version 4's, plus how it smooths the district
    load. strategy_plan_v5 executes it literally and the prompt states them. Chosen on the tuning
    dataset (scripts/tune_strategy.py), never on the reported month."""

    cold_margin_c: float = 0.5         # an occupied room this far below its setpoint is too cold
    cold_trim: float = 0.1             # ... and its cooling is cut up to this far below the baseline action
    cold_ramp_c: float = 1.0           # the cut grows from 0 to cold_trim over this many degrees beyond
    charge_rate: float = 0.15          # battery fraction per hour when charging from the grid
    shave: float = 0.9                 # also discharge once district load reaches this share of the forecast peak
    soc_target: float = 0.95
    # Smoothing, added in 0.7.0.
    trim_hold_c: float = 0.5           # once trimmed, keep the trim until the room is within this of its setpoint
    trim_step: float = 0.02            # release a trim by at most this per hour (deepening is immediate)
    charge_step: float = 0.15          # raise a grid charge by at most this per hour
    evening_reserve: float = 0.0       # state of charge kept back in the top-price hours for the evening peak
    max_step: float = 0.5              # largest storage move per hour, the envelope's rate limit
    min_move: float = 0.01             # storage moves smaller than this are skipped


@dataclass(frozen=True)
class StrategyParamsV7(StrategyParamsV5):
    """Numbers in the prompt version 7 strategy: version 5's, plus the battery smoothing that was
    searched for it. battery_plan_v7 executes it and the prompt states them. Chosen on the tuning
    dataset (scripts/tune_strategy.py --version 7), never on the reported month: no cap and no
    valley filling kept cost, emissions, discomfort and both peaks at the version 6 strategy's,
    so the shipped battery plan is version 5's."""

    # Added in 0.9.0.
    rise_step: float = 1.0             # soft cap: raise a battery action (more charge, less discharge) by at
                                       # most this per hour; lowering it is free; spare solar is exempt. 1 is
                                       # no cap: every cap tried raised cost and the all-time peak.
    rise_charge: bool = True           # the cap also applies to grid charging, not only to a discharge winding down
    fill_valley: bool = False          # grid charging keeps the district draw no higher than the higher of
                                       # last hour's draw and the next hour's load; it cuts ramping but raises cost
    battery_band: float = 0.1          # the prompt asks a model that differs from strategy_battery to stay this
                                       # close to it


@dataclass(frozen=True)
class StrategyParamsV8(StrategyParamsV7):
    """Numbers in the prompt version 8 strategy: version 7's, plus extra cooling in a room that runs
    warm. A trim leaves an overcooled room at its setpoint instead of the baseline's 2 C below it, so
    the next day's heat (or an outage) can carry it over the top of the band. strategy_plan_v8
    executes it and prompt version 8 shows its actions. Chosen on the tuning dataset
    (scripts/tune_strategy.py --version 8), never on the reported month: the cheapest of the 36
    settings tried that keeps every tuning month at or below the baseline's too-warm share."""

    # Added in 0.10.0.
    warm_margin_c: float = 1.5         # an occupied room this far above its setpoint is running warm
    warm_boost: float = 0.05           # ... and its cooling is raised up to this far above the baseline action;
                                       # 0 is no extra cooling
    warm_ramp_c: float = 1.0           # the boost grows from 0 to warm_boost over this many degrees beyond
                                       # warm_margin_c; 0 adds it all at once
    night_from_hour: int = 0           # from this hour of the day (1 to 24) until night_until_hour no trim
    night_until_hour: int = 6          # starts and a held trim is ended; 0 is no night rule. Searched and not
                                       # shipped: it raised cost and cleared no warm hour


@dataclass(frozen=True)
class RuleParamsV2:
    """Knobs of the 0.3.0 rule-based policy for prompt version 2 observations, kept as tuned
    then so the 0.3.0 reference result reproduces."""

    charge_price_rank: float = 0.1     # charge when at most this share of the next 24 h is cheaper
    charge_carbon_rank: float = 0.2    # ... and at most this share is cleaner
    charge_rate: float = 0.6           # battery fraction per hour when charging from the grid; the
                                       # battery is most efficient near 70 to 80 percent of nominal power
    peak_ratio: float = 0.8            # discharge when price is at least this share of the 24 h max
    peak_spread: float = 1.3           # ... and that max is at least this many times the 24 h min
    discharge_rate: float = 0.8        # most battery fraction per hour when discharging
    soc_target: float = 0.95
    soc_reserve: float = 0.1           # kept back for outages
    solar_soak: bool = True            # store solar the building would otherwise export for nothing
    dhw_charge: float = 0.0
    dhw_discharge: float = 0.0
    precool: float = 0.0               # extra cooling fraction in the hours just before a spike
    precool_hours: int = 2
    peak_ease: float = 0.0             # cooling eased by this much during the spike
    max_step: float = 0.5              # largest storage move per hour, the envelope's rate limit
    min_move: float = 0.01             # storage moves smaller than this are skipped


class ScriptedSupervisor:
    """Deterministic stand-in for the model: a rule-based controller that answers through the
    same request, reply, envelope and simulator path as a live model.

    For prompt version 3 observations it charges the battery a little at a time in the
    hours with the lowest combined price and carbon signal, within the district's peak
    headroom, stores spare solar, discharges into high-signal hours sized to each
    building's own load, and can shave the district peak: the 0.4.0 rule-based controller.
    For version 4 it follows that prompt's strategy literally (strategy_plan_v4), which is
    how the strategy's numbers are chosen offline, and likewise for version 5
    (strategy_plan_v5). Version 6 runs the same version 5 strategy, never ends a trim early,
    and leaves holding trims to the envelope. Version 7 (strategy_plan_v7) keeps every action
    inside the ranges the observation shows and uses the version 7 battery plan; version 8
    (strategy_plan_v8) adds extra cooling in a warm room. Version 2
    observations get the 0.3.0 rule and version 1 the simpler 0.2.0 rule.

    Faults are opt-in: on listed steps it injects a bad reply so the envelope and fallback
    paths are exercised: out_of_range, too_fast, below_comfort, malformed, schema, missing.
    """

    kind = "scripted"

    def __init__(self, model_key: str = DEFAULT_MODEL, faults: dict[int, str] | None = None,
                 tokens: tuple[int, int] = (0, 0), params: RuleParams | None = None,
                 params_v2: RuleParamsV2 | None = None, strategy: StrategyParams | None = None,
                 strategy_v5: StrategyParamsV5 | None = None, strategy_v7: StrategyParamsV7 | None = None,
                 strategy_v8: StrategyParamsV8 | None = None) -> None:
        self.model_key = model_key
        self.faults = dict(faults or {})
        self.tokens = tokens
        self.params = params or RuleParams()
        self.params_v2 = params_v2 or RuleParamsV2()
        self.strategy = strategy or StrategyParams()
        self.strategy_v5 = strategy_v5 or StrategyParamsV5()
        self.strategy_v7 = strategy_v7 or StrategyParamsV7()
        self.strategy_v8 = strategy_v8 or StrategyParamsV8()

    @staticmethod
    def default_faults(hours: int) -> dict[int, str]:
        kinds = ["too_fast", "out_of_range", "malformed", "below_comfort", "missing", "schema"]
        faults = {}
        h, i = 31, 0
        while h < hours:
            faults[h] = kinds[i % len(kinds)]
            h += 53
            i += 1
        return faults

    def call(self, step: int, request: dict) -> CallResult:
        obs = observation_from_request(request)
        fault = self.faults.get(step)
        if fault == "missing":
            return CallResult(None, error="timeout: no reply within 90 s (scripted)", model="scripted")
        if fault == "malformed":
            return CallResult('{"reason": "charge batteries", "Building_1": {"battery": 0.4', *self.tokens,
                              stop_reason="end_turn", model="scripted")
        first = next(iter(obs["buildings"].values()), {})
        if "strategy" in first:  # version 8
            reply = strategy_plan_v8(obs, self.strategy_v8)
        elif "cooling_range" in first:  # version 7
            reply = strategy_plan_v7(obs, self.strategy_v7)
        elif "smoothing" in obs:
            reply = strategy_plan_v5(obs, self.strategy_v5)
            if "strategy_battery_reason" in obs:  # version 6: the reply carries end_trim
                for b in obs["buildings"]:
                    reply[b]["end_trim"] = None
        elif "price_plan" in obs:
            reply = strategy_plan_v4(obs, self.strategy)
        elif "signal_outlook" in obs:
            reply = self._policy_v3(obs)
        elif "price_outlook" in obs:
            reply = self._policy(obs)
        else:
            reply = self._policy_v1(obs)
        names = sorted(obs["buildings"])
        if fault == "out_of_range":
            reply[names[0]]["battery"] = 1.8
            reply["reason"] = "Price spike ahead, fill the first battery all at once."
        elif fault == "too_fast":
            for b in names[:2]:
                last = obs["buildings"][b]["last_action"] or {"battery": 0.0}
                reply[b]["battery"] = (last["battery"] or 0.0) - 0.9
            reply["reason"] = "Dump two batteries into the evening peak."
        elif fault == "below_comfort":
            for b in names:
                reply[b]["cooling"] = 0.0
            reply["reason"] = "Switch cooling off for an hour to save on the peak price."
        elif fault == "schema":
            reply[names[-1]]["dhw"] = "half"
        return CallResult(json.dumps(reply), *self.tokens, stop_reason="end_turn", model="scripted")

    def _policy_v3(self, obs: dict) -> dict:
        return rule_plan_v3(obs, self.params)

    def _policy(self, obs: dict) -> dict:
        p = self.params_v2
        po, co = obs["price_outlook"], obs["carbon_outlook"]
        now = po["now"]
        top, bottom = po["max"], po["min"]
        peak_now = top is not None and now >= top * p.peak_ratio and top >= bottom * p.peak_spread
        spike_ahead = (top is not None and top >= now * p.peak_spread and po["hours_to_max"] is not None
                       and po["hours_to_max"] <= p.precool_hours)
        # No grid charging until a day of carbon history exists: charging on dirty power can cost
        # more emissions than the peak discharge saves.
        cheap_now = (po["rank_now"] is not None and po["rank_now"] <= p.charge_price_rank
                     and co["rank_now"] is not None and co["rank_now"] <= p.charge_carbon_rank)
        reply: dict = {}
        notes = set()
        for b, s in sorted(obs["buildings"].items()):
            bat, tank = s["battery"], s["dhw_tank"]
            cap = bat["capacity_kwh"] or 0.0
            fmax = bat["max_fraction_per_hour"] or 0.0
            soc = bat["soc"]
            # Charge levels arrive rounded to 3 decimals; keep that much margin from the limits.
            room = max(0.0, p.soc_target - soc - 0.001)
            spare = max(0.0, soc - p.soc_reserve - 0.001)
            last = s["last_action"] or {}
            # Net draw before storage, from last hour's grid draw less what the battery did.
            load = s["grid_kwh_last_hour"] - (last.get("battery") or 0.0) * cap
            battery = dhw = 0.0
            cooling = None
            if peak_now and cap > 0:
                battery = -min(p.discharge_rate, fmax, max(0.0, load) / cap, spare)
                dhw = -min(p.dhw_discharge, max(0.0, tank["soc"] - p.soc_reserve))
            elif p.solar_soak and load < -0.05 and cap > 0:
                battery = min(fmax, -load / cap, room)
                notes.add("store spare solar")
            elif cheap_now and cap > 0:
                battery = min(p.charge_rate, fmax, room)
                dhw = min(p.dhw_charge, max(0.0, p.soc_target - tank["soc"]))
            # Ramp within the envelope's rate limit instead of being clamped to it. The limit is
            # measured from last hour's action or the baseline (0), whichever is closer.
            lb, ld = last.get("battery") or 0.0, last.get("dhw") or 0.0
            battery = min(max(lb, 0.0) + p.max_step, max(min(lb, 0.0) - p.max_step, battery))
            dhw = min(max(ld, 0.0) + p.max_step, max(min(ld, 0.0) - p.max_step, dhw))
            # Skip moves too small to matter; near a charge limit they only meet rounding.
            battery = 0.0 if abs(battery) < p.min_move else battery
            dhw = 0.0 if abs(dhw) < p.min_move else dhw
            if battery < -0.01:
                notes.add("discharge storage into the price peak")
            elif battery > 0.01 and cheap_now and "store spare solar" not in notes:
                notes.add("charge storage on cheap, clean power")
            low, high = s["comfort_band_c"]
            base = s["baseline_action"]["cooling"]
            if s["occupied"] and base > 0:
                if spike_ahead and p.precool > 0 and s["indoor_c"] > low + 1.0:
                    cooling = round(min(1.0, base + p.precool), 3)
                    notes.add("pre-cool before the price spike")
                elif peak_now and p.peak_ease > 0 and s["indoor_c"] < high - 1.0:
                    cooling = round(max(0.0, base - p.peak_ease), 3)
                    notes.add("ease cooling in the spike")
            # Round toward zero so a move sized to the charge limit never overshoots it.
            reply[b] = {"cooling": cooling, "dhw": math.trunc(dhw * 1000) / 1000,
                        "battery": math.trunc(battery * 1000) / 1000}
        reason = "; ".join(sorted(notes)) if notes else "Nothing stands out, hold storage and meet the cooling load"
        return {"reason": reason[0].upper() + reason[1:], **reply}

    @staticmethod
    def _policy_v1(obs: dict) -> dict:
        """The v0.2.0 rule, kept so fixtures from that version can be regenerated."""
        prices = obs["price_per_kwh_now_and_next_3h"]
        now, ahead = prices[0], max(prices[1:] or prices)
        cheap_now = ahead > now * 1.15
        peak_now = now >= ahead and now > min(prices) * 1.15
        reply: dict = {}
        notes = set()
        for b, s in sorted(obs["buildings"].items()):
            spare_solar = s["solar_kwh"] - s["plug_load_kwh"] - s["cooling_demand_kwh"]
            soc, tank = s["battery_soc"], s["dhw_soc"]
            battery = dhw = 0.0
            if peak_now:
                battery = -min(0.25, max(0.0, soc - 0.15))
                dhw = -min(0.15, max(0.0, tank - 0.15))
            elif cheap_now:
                battery = min(0.25, max(0.0, 0.9 - soc))
                dhw = min(0.15, max(0.0, 0.9 - tank))
            elif spare_solar > 0.2:
                battery = min(0.2, max(0.0, 0.9 - soc))
            if battery < -0.01:
                notes.add("discharge storage into the price peak")
            elif battery > 0.01:
                notes.add("soak up spare solar" if not cheap_now else "charge storage before the price rises")
            reply[b] = {"cooling": None, "dhw": round(dhw, 3), "battery": round(battery, 3)}
        reason = "; ".join(sorted(notes)) if notes else "Price flat, hold storage and meet the cooling load"
        return {"reason": reason[0].upper() + reason[1:], **reply}


def rule_plan_v3(obs: dict, p: RuleParams | None = None) -> dict:
    """The 0.4.0 rule-based controller's reply to a prompt version 3 (or later) observation.
    Prompt version 4 shows it to the model as the reference action for the hour."""
    p = p or RuleParams()
    sig, peak = obs["signal_outlook"], obs["peak"]
    now, rank = sig["now"], sig["rank_now"]
    cheap_now = (now is not None and rank is not None and rank <= p.charge_rank and now <= p.charge_max_signal
                 and obs["hours_left_in_month"] > p.endgame_hours)
    high_now = now is not None and now >= p.discharge_min_signal
    load_now, forecast = peak["district_load_now_kwh"], peak["forecast_today_kwh"]
    shave_now = bool(p.shave > 0 and load_now is not None and forecast and load_now >= p.shave * forecast)
    headroom = peak["headroom_kwh"]
    # Grid charging shares the district's headroom in proportion to battery size.
    caps = {b: s["battery"]["capacity_kwh"] or 0.0 for b, s in obs["buildings"].items()}
    total_cap = sum(caps.values()) or 1.0
    reply: dict = {}
    notes = set()
    for b, s in sorted(obs["buildings"].items()):
        bat = s["battery"]
        cap, fmax, soc = caps[b], bat["max_fraction_per_hour"] or 0.0, bat["soc"]
        room = max(0.0, p.soc_target - soc - 0.001)
        spare = max(0.0, soc - p.soc_reserve - 0.001)
        load = s["load_now_kwh"]
        battery = 0.0
        if cap > 0 and load is not None:
            if (high_now or shave_now) and load > 0:
                battery = -min(p.discharge_rate, fmax, load / cap, spare)
                if battery < 0:
                    notes.add("shave the district peak" if shave_now and not high_now
                              else "discharge into a costly, high-carbon hour")
            elif p.solar_soak and load < -0.05:
                battery = min(fmax, -load / cap, room)
                if battery > 0:
                    notes.add("store spare solar")
            elif cheap_now:
                # Headroom arrives rounded to 2 decimals; keep 0.02 kWh clear of the limiter.
                share = None if headroom is None else max(0.0, headroom - 0.02) * caps[b] / total_cap / cap
                battery = min(p.charge_rate, fmax, room, share if share is not None else 1.0)
                if battery > 0:
                    notes.add("charge a little in a cheap, clean hour")
        last = s["last_action"] or {}
        lb = last.get("battery") or 0.0
        battery = min(max(lb, 0.0) + p.max_step, max(min(lb, 0.0) - p.max_step, battery))
        battery = 0.0 if abs(battery) < p.min_move else battery
        reply[b] = {"cooling": None, "dhw": 0.0, "battery": math.trunc(battery * 1000) / 1000}
    reason = "; ".join(sorted(notes)) if notes else "Nothing stands out, hold storage and meet the cooling load"
    return {"reason": (reason[0].upper() + reason[1:])[:dc.REASON_TARGET_CHARS], **reply}


def strategy_plan_v4(obs: dict, p: StrategyParams | None = None) -> dict:
    """The prompt version 4 strategy, step by step, for a prompt version 4 observation: trim
    cooling in occupied rooms that are too cold, discharge in the top-price hours sized to each
    building's load, charge just enough to be full when they start, in the cheapest and then
    cleanest hours before them and only when charging pays, and store spare solar."""
    p = p or StrategyParams()
    pp, peak, nxt = obs["price_plan"], obs["peak"], obs["next_24h"]
    top_now = bool(pp["top_price_now"])
    ahead = pp["top_price_hours_ahead"]
    hours_to_top = min(ahead) if ahead else None
    top_left = 1  # top-price hours left in this window, this one included
    while top_now and top_left in ahead:
        top_left += 1
    # Hours between now and the next top-price hour, as (price, carbon): candidates for charging.
    worst = (float("inf"), float("inf"))
    key = lambda pr, ca: (worst[0] if pr is None else pr, worst[1] if ca is None else ca)  # noqa: E731
    now_key = key(pp["now"], obs["carbon_outlook"]["now"])
    cands = [] if hours_to_top is None else [key(nxt["price"][j - 1], nxt["carbon"][j - 1])
                                            for j in range(1, hours_to_top)]
    load_now, forecast = peak["district_load_now_kwh"], peak["forecast_today_kwh"]
    shave_now = bool(p.shave > 0 and load_now is not None and forecast and load_now >= p.shave * forecast)
    headroom = peak["headroom_kwh"]
    caps = {b: s["battery"]["capacity_kwh"] or 0.0 for b, s in obs["buildings"].items()}
    total_cap = sum(caps.values()) or 1.0
    reply: dict = {}
    notes = set()
    for b, s in sorted(obs["buildings"].items()):
        bat = s["battery"]
        cap, fmax, soc = caps[b], bat["max_fraction_per_hour"] or 0.0, bat["soc"]
        floor = max(bat.get("soc_floor") or 0.0, 0.1)
        room = max(0.0, p.soc_target - soc - 0.001)
        spare = max(0.0, soc - floor - 0.001)
        load = s["load_now_kwh"]
        battery = 0.0
        if cap > 0 and load is not None:
            if (top_now or shave_now) and load > 0:
                share = spare / top_left if top_now and p.even_discharge else spare
                battery = -min(fmax, load / cap, share)
                if battery < 0:
                    notes.add("discharge in a top-price hour" if top_now else "shave the district peak")
            elif load < -0.05:
                battery = min(fmax, -load / cap, room)
                if battery > 0:
                    notes.add("store spare solar")
            elif bat.get("grid_charging_ok") and room > 0 and hours_to_top is not None:
                hours_needed = math.ceil(room / p.charge_rate - 1e-9)
                if sum(1 for c in cands if c < now_key) < hours_needed:
                    share = None if headroom is None else max(0.0, headroom - 0.02) * caps[b] / total_cap / cap
                    battery = min(p.charge_rate, fmax, room, share if share is not None else 1.0)
                    if battery > 0:
                        notes.add("charge in a cheap, clean hour before the top price")
        last = s["last_action"] or {}
        lb = last.get("battery") or 0.0
        battery = min(max(lb, 0.0) + p.max_step, max(min(lb, 0.0) - p.max_step, battery))
        battery = 0.0 if abs(battery) < p.min_move else battery
        cooling = None
        base = s["baseline_action"]["cooling"]
        cold = None if s["indoor_vs_setpoint_c"] is None else -s["indoor_vs_setpoint_c"] - p.cold_margin_c
        if p.cold_trim > 0 and s["occupied"] and base and base > 0 and cold is not None and cold >= 0:
            trim = p.cold_trim if p.cold_ramp_c <= 0 else p.cold_trim * min(1.0, cold / p.cold_ramp_c)
            # The baseline arrives rounded to 3 decimals: keep 0.001 clear of the deviation limit.
            cooling = math.ceil(max(0.0, base - trim + 0.001) * 1000) / 1000
            if cooling < base:
                notes.add("trim cooling in a cold room")
            else:
                cooling = None
        reply[b] = {"cooling": cooling, "dhw": 0.0, "battery": math.trunc(battery * 1000) / 1000}
    reason = "; ".join(sorted(notes)) if notes else "Nothing stands out, hold storage and meet the cooling load"
    return {"reason": (reason[0].upper() + reason[1:])[:dc.REASON_TARGET_CHARS], **reply}


def strategy_plan_v5(obs: dict, p: StrategyParamsV5 | None = None) -> dict:
    """The prompt version 5 strategy, step by step: version 4's, smoothed. A cooling trim, once
    started, is held until the room is nearly back at its setpoint and then released a little each
    hour; a grid charge starts small and rises a little each hour; the top-price discharge can keep
    some charge back for the evening district peak."""
    reply, battery_notes, cooling_notes = _strategy_v5(obs, p)
    notes = battery_notes | cooling_notes
    reason = "; ".join(sorted(notes)) if notes else "Nothing stands out, hold storage and meet the cooling load"
    return {"reason": (reason[0].upper() + reason[1:])[:dc.REASON_TARGET_CHARS], **reply}


def battery_plan_v5(obs: dict, p: StrategyParamsV5 | None = None) -> tuple[dict[str, float], str]:
    """The version 5 strategy's battery action for each building and why: what prompt version 6
    shows the model each hour as strategy_battery, in place of the 0.4.0 rule-based plan."""
    reply, battery_notes, _ = _strategy_v5(obs, p)
    reason = "; ".join(sorted(battery_notes)) if battery_notes else "nothing stands out, hold the batteries"
    return {b: r["battery"] for b, r in reply.items()}, (reason[0].upper() + reason[1:])[:dc.REASON_TARGET_CHARS]


def _strategy_v5(obs: dict, p: StrategyParamsV5 | None = None) -> tuple[dict, set[str], set[str]]:
    """strategy_plan_v5's actions per building, with its battery and cooling notes kept apart."""
    p = p or StrategyParamsV5()
    pp, peak, nxt = obs["price_plan"], obs["peak"], obs["next_24h"]
    top_now = bool(pp["top_price_now"])
    ahead = pp["top_price_hours_ahead"]
    hours_to_top = min(ahead) if ahead else None
    top_left = 1  # top-price hours left in this window, this one included
    while top_now and top_left in ahead:
        top_left += 1
    worst = (float("inf"), float("inf"))
    key = lambda pr, ca: (worst[0] if pr is None else pr, worst[1] if ca is None else ca)  # noqa: E731
    now_key = key(pp["now"], obs["carbon_outlook"]["now"])
    cands = [] if hours_to_top is None else [key(nxt["price"][j - 1], nxt["carbon"][j - 1])
                                            for j in range(1, hours_to_top)]
    load_now, forecast = peak["district_load_now_kwh"], peak["forecast_today_kwh"]
    shave_now = bool(p.shave > 0 and load_now is not None and forecast and load_now >= p.shave * forecast)
    headroom = peak["headroom_kwh"]
    caps = {b: s["battery"]["capacity_kwh"] or 0.0 for b, s in obs["buildings"].items()}
    total_cap = sum(caps.values()) or 1.0
    reply: dict = {}
    notes: set[str] = set()  # battery notes
    cooling_notes: set[str] = set()
    for b, s in sorted(obs["buildings"].items()):
        bat = s["battery"]
        cap, fmax, soc = caps[b], bat["max_fraction_per_hour"] or 0.0, bat["soc"]
        floor = max(bat.get("soc_floor") or 0.0, 0.1)
        room = max(0.0, p.soc_target - soc - 0.001)
        spare = max(0.0, soc - floor - 0.001)
        load = s["load_now_kwh"]
        last = s["last_action"] or {}
        lb = last.get("battery") or 0.0
        battery = 0.0
        if cap > 0 and load is not None:
            if top_now and load > 0:
                battery = -min(fmax, load / cap, max(0.0, spare - p.evening_reserve) / top_left)
                if battery < 0:
                    notes.add("discharge evenly over the top-price hours")
            elif shave_now and load > 0:
                battery = -min(fmax, load / cap, spare)
                if battery < 0:
                    notes.add("shave the district peak")
            elif load < -0.05:
                battery = min(fmax, -load / cap, room)
                if battery > 0:
                    notes.add("store spare solar")
            elif bat.get("grid_charging_ok") and room > 0 and hours_to_top is not None:
                hours_needed = math.ceil(room / p.charge_rate - 1e-9)
                if sum(1 for c in cands if c < now_key) < hours_needed:
                    share = None if headroom is None else max(0.0, headroom - 0.02) * caps[b] / total_cap / cap
                    battery = min(p.charge_rate, fmax, room, share if share is not None else 1.0,
                                  max(lb, 0.0) + p.charge_step)
                    if battery > 0:
                        notes.add("charge gently in a cheap, clean hour before the top price")
        battery = min(max(lb, 0.0) + p.max_step, max(min(lb, 0.0) - p.max_step, battery))
        battery = 0.0 if abs(battery) < p.min_move else battery
        cooling = None
        base = s["baseline_action"]["cooling"]
        prev_trim = min(0.0, s.get("cooling_trim_last_hour") or 0.0)
        gap = s["indoor_vs_setpoint_c"]
        target = 0.0
        if s["occupied"] and base and base > 0 and gap is not None:
            cold = -gap - p.cold_margin_c
            if cold >= 0:
                target = -(p.cold_trim if p.cold_ramp_c <= 0 else p.cold_trim * min(1.0, cold / p.cold_ramp_c))
            if prev_trim < 0 and gap < -p.trim_hold_c:
                target = min(target, prev_trim)  # hold the trim until the room is nearly back
        trim = target if target <= prev_trim else min(target, prev_trim + p.trim_step)
        if base and trim < -0.001 and (gap is None or gap < 0):
            # The baseline arrives rounded to 3 decimals: keep 0.001 clear of the deviation limit.
            cooling = math.ceil(max(0.0, base + max(trim, -p.cold_trim) + 0.001) * 1000) / 1000
            if cooling < base:
                cooling_notes.add("hold a cooling trim in a cold room, easing it off slowly")
            else:
                cooling = None
        reply[b] = {"cooling": cooling, "dhw": 0.0, "battery": math.trunc(battery * 1000) / 1000}
    return reply, notes, cooling_notes


def battery_plan_v7(obs: dict, p: StrategyParamsV7 | None = None) -> tuple[dict[str, float], str]:
    """The prompt version 7 battery plan: version 5's, with the smoothing searched for 0.9.0. With
    rise_step below 1 a battery action rises (more charge, or less discharge) by at most that per
    hour, so a discharge winds down over several hours while charge and load allow; with
    fill_valley, grid charging only fills the district draw up to the higher of last hour's draw
    and the next hour's load. With the shipped numbers (no cap, no valley filling) it gives
    exactly battery_plan_v5's actions, which is left as it was so version 6 runs replay."""
    p = p or StrategyParamsV7()
    pp, peak, nxt, sm = obs["price_plan"], obs["peak"], obs["next_24h"], obs["smoothing"]
    top_now = bool(pp["top_price_now"])
    ahead = pp["top_price_hours_ahead"]
    hours_to_top = min(ahead) if ahead else None
    top_left = 1  # top-price hours left in this window, this one included
    while top_now and top_left in ahead:
        top_left += 1
    worst = (float("inf"), float("inf"))
    key = lambda pr, ca: (worst[0] if pr is None else pr, worst[1] if ca is None else ca)  # noqa: E731
    now_key = key(pp["now"], obs["carbon_outlook"]["now"])
    cands = [] if hours_to_top is None else [key(nxt["price"][j - 1], nxt["carbon"][j - 1])
                                            for j in range(1, hours_to_top)]
    load_now, forecast = peak["district_load_now_kwh"], peak["forecast_today_kwh"]
    shave_now = bool(p.shave > 0 and load_now is not None and forecast and load_now >= p.shave * forecast)
    headroom = peak["headroom_kwh"]
    fill = None
    level = [v for v in (sm["district_draw_last_hour_kwh"], sm["district_load_next_hour_kwh"]) if v is not None]
    if p.fill_valley and level and sm["district_load_now_kwh"] is not None:
        fill = max(0.0, max(level) - sm["district_load_now_kwh"])
    caps = {b: s["battery"]["capacity_kwh"] or 0.0 for b, s in obs["buildings"].items()}
    total_cap = sum(caps.values()) or 1.0
    reply: dict[str, float] = {}
    notes: set[str] = set()
    for b, s in sorted(obs["buildings"].items()):
        bat = s["battery"]
        cap, fmax, soc = caps[b], bat["max_fraction_per_hour"] or 0.0, bat["soc"]
        floor = max(bat.get("soc_floor") or 0.0, 0.1)
        room = max(0.0, p.soc_target - soc - 0.001)
        spare = max(0.0, soc - floor - 0.001)
        load = s["load_now_kwh"]
        last = s["last_action"] or {}
        lb = last.get("battery") or 0.0
        battery, solar, note = 0.0, False, None
        if cap > 0 and load is not None:
            if top_now and load > 0:
                battery = -min(fmax, load / cap, max(0.0, spare - p.evening_reserve) / top_left)
                note = "discharge evenly over the top-price hours"
            elif shave_now and load > 0:
                battery = -min(fmax, load / cap, spare)
                note = "shave the district peak"
            elif load < -0.05:
                battery, solar = min(fmax, -load / cap, room), True
                note = "store spare solar"
            elif bat.get("grid_charging_ok") and room > 0 and hours_to_top is not None:
                hours_needed = math.ceil(room / p.charge_rate - 1e-9)
                if sum(1 for c in cands if c < now_key) < hours_needed:
                    share = None if headroom is None else max(0.0, headroom - 0.02) * caps[b] / total_cap / cap
                    filled = 1.0 if fill is None else fill * caps[b] / total_cap / cap
                    battery = min(p.charge_rate, fmax, room, share if share is not None else 1.0, filled,
                                  max(lb, 0.0) + p.charge_step)
                    note = "charge gently in a cheap, clean hour before the top price"
            ceiling = round(lb + p.rise_step, 6)
            if not solar and battery > ceiling and (p.rise_charge or lb < 0):
                # No step up: keep discharging, or charge less, as far as the battery and the load allow.
                most = -min(fmax, max(0.0, load) / cap, spare)
                battery = ceiling if ceiling >= 0 else min(battery, max(ceiling, most))
                if battery < 0 and not top_now and not shave_now:
                    note = "wind a discharge down slowly"
        if note and battery != 0 and (battery > 0) == (solar or note.startswith("charge")):
            notes.add(note)
        battery = min(max(lb, 0.0) + p.max_step, max(min(lb, 0.0) - p.max_step, battery))
        battery = 0.0 if abs(battery) < p.min_move else battery
        reply[b] = math.trunc(battery * 1000) / 1000
    reason = "; ".join(sorted(notes)) if notes else "nothing stands out, hold the batteries"
    return reply, (reason[0].upper() + reason[1:])[:dc.REASON_TARGET_CHARS]


def strategy_plan_v7(obs: dict, p: StrategyParamsV7 | None = None) -> dict:
    """The prompt version 7 strategy for a version 7 observation, as a model that keeps inside the
    envelope would answer: battery_plan_v7 (strategy_battery with the default numbers) within
    battery_range, the version 5 cooling trim fitted into cooling_range (a held trim is never
    left to null), the tank at 0 and no early ends."""
    p = p or StrategyParamsV7()
    battery, battery_reason = battery_plan_v7(obs, p)
    reply: dict = {}
    notes: set[str] = set()
    for b, s in sorted(obs["buildings"].items()):
        trim, rng = s["trim"], s["cooling_range"]
        base = s["baseline_action"]["cooling"]
        held = trim["state"] in ("hold", "ease")
        prev_trim = -trim["depth"]
        gap = s["indoor_vs_setpoint_c"]
        target = 0.0
        if s["occupied"] and base and base > 0 and gap is not None:
            cold = -gap - p.cold_margin_c
            if cold >= 0:
                target = -(p.cold_trim if p.cold_ramp_c <= 0 else p.cold_trim * min(1.0, cold / p.cold_ramp_c))
            if prev_trim < 0 and gap < -p.trim_hold_c:
                target = min(target, prev_trim)
        step = target if target <= prev_trim else min(target, prev_trim + p.trim_step)
        cooling = None
        if base and step < -0.001 and (gap is None or gap < 0):
            cooling = math.ceil(max(0.0, base + max(step, -p.cold_trim) + 0.001) * 1000) / 1000
        if rng is None:
            cooling = None
        elif cooling is not None or held:
            cooling = min(max(rng[0], rng[1] if cooling is None else cooling), rng[1])
            if not held and cooling >= base:
                cooling = None
        if cooling is not None:
            notes.add("hold a cooling trim in a cold room, easing it off slowly")
        lo, hi = s["battery_range"]
        reply[b] = {"cooling": cooling, "dhw": 0.0, "battery": min(max(battery[b], lo), hi), "end_trim": None}
    reason = "; ".join([battery_reason[0].lower() + battery_reason[1:], *sorted(notes)])
    return {"reason": (reason[0].upper() + reason[1:])[:dc.REASON_TARGET_CHARS], **reply}


WARM_NOTE = "cool a warm room a little more"
NIGHT_NOTE = "no cooling trim at night"
NIGHT_END_TRIM = "night: the room cools back to its cushion for tomorrow"


def night_now(hour: int, p: StrategyParamsV8) -> bool:
    """Whether hour of the day (1 to 24) falls in the strategy's no-trim night."""
    if p.night_from_hour <= 0:
        return False
    if p.night_from_hour <= p.night_until_hour:
        return p.night_from_hour <= hour < p.night_until_hour
    return hour >= p.night_from_hour or hour < p.night_until_hour


def strategy_plan_v8(obs: dict, p: StrategyParamsV8 | None = None) -> dict:
    """The prompt version 8 strategy: version 7's, with no trim at night (none starts, a held one is
    ended with end_trim) and an occupied room more than warm_margin_c above its setpoint, with no
    trim held, cooled up to warm_boost above baseline_action within cooling_range. Prompt version 8
    shows each building's result as strategy."""
    p = p or StrategyParamsV8()
    reply = strategy_plan_v7(obs, p)
    warm = night = False
    if night_now(int(obs["hour"]), p):
        for b, s in sorted(obs["buildings"].items()):
            base = s["baseline_action"]["cooling"]
            if s["trim"]["end_trim_ok"]:
                reply[b]["cooling"], reply[b]["end_trim"] = None, NIGHT_END_TRIM
                night = True
            elif s["trim"]["state"] not in ("hold", "ease") and reply[b]["cooling"] is not None and base is not None \
                    and reply[b]["cooling"] < base:
                reply[b]["cooling"] = None
                night = True
    for b, s in sorted(obs["buildings"].items()):
        gap, rng = s["indoor_vs_setpoint_c"], s["cooling_range"]
        base = s["baseline_action"]["cooling"]
        # In an outage the grid cannot serve extra cooling, and CityLearn counts it as unserved energy.
        if (p.warm_boost <= 0 or not s["occupied"] or s["power_outage"] or gap is None or rng is None or base is None
                or s["trim"]["state"] in ("hold", "ease") or gap < p.warm_margin_c):
            continue
        boost = p.warm_boost if p.warm_ramp_c <= 0 else p.warm_boost * min(1.0, (gap - p.warm_margin_c) / p.warm_ramp_c)
        # The baseline arrives rounded to 3 decimals: keep 0.001 clear of the deviation limit.
        cooling = min(max(math.floor((base + boost - 0.001) * 1000) / 1000, rng[0]), rng[1])
        if cooling > base + 0.001:
            reply[b]["cooling"] = cooling
            warm = True
    notes = [*([NIGHT_NOTE] if night else []), *([WARM_NOTE] if warm else [])]
    if notes:
        reply["reason"] = "; ".join([reply["reason"], *notes])[:dc.REASON_TARGET_CHARS]
    return reply


class HoldSupervisor:
    """Answers every hour with null actions, so the envelope applies the baseline action
    everywhere: the no-control reference run through the agent path. Used by the live
    page's "baseline" option so that run is recorded, replayed and published like any other."""

    kind = "hold"

    def __init__(self, model_key: str = DEFAULT_MODEL) -> None:
        self.model_key = model_key

    def call(self, step: int, request: dict) -> CallResult:
        obs = observation_from_request(request)
        reply = {"reason": "Hold the no-control actions."}
        reply.update({b: {"cooling": None, "dhw": None, "battery": None} for b in sorted(obs["buildings"])})
        return CallResult(json.dumps(reply), stop_reason="end_turn", model="hold")


def observation_from_request(request: dict) -> dict:
    """The user message carries the observation as a JSON block after a marker line."""
    content = request["messages"][-1]["content"]
    text = content if isinstance(content, str) else content[0]["text"]
    marker = "OBSERVATION_JSON\n"
    return json.loads(text[text.index(marker) + len(marker):])
