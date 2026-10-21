"""Model access: key lookup, pricing, budget, and the supervisors.

LiveSupervisor     calls the Messages API.
ScriptedSupervisor returns deterministic rule-based replies for offline runs and tests.
HoldSupervisor     always keeps the baseline action (the live page's baseline option).
ReplaySupervisor   serves recorded replies from a run directory, with zero API calls.
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
    building's own load, and can shave the district peak. Version 2 observations get the
    0.3.0 rule and version 1 the simpler 0.2.0 rule.

    Faults are opt-in: on listed steps it injects a bad reply so the envelope and fallback
    paths are exercised: out_of_range, too_fast, below_comfort, malformed, schema, missing.
    """

    kind = "scripted"

    def __init__(self, model_key: str = DEFAULT_MODEL, faults: dict[int, str] | None = None,
                 tokens: tuple[int, int] = (0, 0), params: RuleParams | None = None,
                 params_v2: RuleParamsV2 | None = None) -> None:
        self.model_key = model_key
        self.faults = dict(faults or {})
        self.tokens = tokens
        self.params = params or RuleParams()
        self.params_v2 = params_v2 or RuleParamsV2()

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
        if "signal_outlook" in obs:
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
        p = self.params
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
