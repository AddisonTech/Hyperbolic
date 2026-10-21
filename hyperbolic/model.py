"""Model access: key lookup, pricing, budget, and the three supervisors.

LiveSupervisor     calls the Messages API.
ScriptedSupervisor returns deterministic rule-based replies for offline runs and tests.
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


class ScriptedSupervisor:
    """Deterministic stand-in for the model, used for the labeled sample run and tests.

    It reads the observation embedded in the request and answers with a simple
    price-aware rule: charge storage when the price is about to rise or solar is
    spare, discharge when the price is at its local high, and leave cooling at the
    baseline. On listed steps it injects a bad reply so the envelope and
    fallback paths are exercised: out_of_range, too_fast, below_comfort,
    malformed, schema, missing.
    """

    kind = "scripted"

    def __init__(self, model_key: str = DEFAULT_MODEL, faults: dict[int, str] | None = None,
                 tokens: tuple[int, int] = (0, 0)) -> None:
        self.model_key = model_key
        self.faults = dict(faults or {})
        self.tokens = tokens

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
        reply = self._policy(obs)
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

    @staticmethod
    def _policy(obs: dict) -> dict:
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


def observation_from_request(request: dict) -> dict:
    """The user message carries the observation as a JSON block after a marker line."""
    content = request["messages"][-1]["content"]
    text = content if isinstance(content, str) else content[0]["text"]
    marker = "OBSERVATION_JSON\n"
    return json.loads(text[text.index(marker) + len(marker):])
