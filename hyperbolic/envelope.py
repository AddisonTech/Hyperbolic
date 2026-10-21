"""Safety envelope applied to every supervisory proposal before it reaches the simulator.

For each building and device the checks run in this order:
  1. schema validation (Pydantic, strict, finite numbers only)
  2. action range: the configured limits intersected with CityLearn's action space
  3. rate limit per step, measured from last hour's action or from this hour's
     baseline action, whichever is closer
  4. state of charge limits for the battery and the hot water tank
  5. cooling deviation: at most cooling_max_deviation away from the ideal-load fraction
  6. comfort: in occupied hours near the edge of CityLearn's comfort band the heat
     pump may not cool less (too warm) or more (too cool) than the baseline action,
     and with overcool_guard_unoccupied no extra cooling when already cool at night
A null action, or any invalid reply, uses the baseline action for that device.
Every clamp and fallback is returned with a reason so the runner can log it.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, create_model

from . import district as dc

DEVICE_KEYS = tuple(dc.DEVICES.values())  # cooling, dhw, battery


class DeviceActions(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    cooling: float | None
    dhw: float | None
    battery: float | None


@lru_cache(maxsize=8)
def proposal_model(buildings: tuple[str, ...]) -> type[BaseModel]:
    """The only shape the model is allowed to return: a reason plus one entry per building."""
    fields: dict[str, Any] = {"reason": (str, Field(min_length=1, max_length=300))}
    for b in buildings:
        fields[b] = (DeviceActions, ...)
    return create_model(
        "Proposal", __config__=ConfigDict(extra="forbid", strict=True, allow_inf_nan=False), **fields
    )


def _nullable_number() -> dict:
    return {"anyOf": [{"type": "number"}, {"type": "null"}]}


def proposal_json_schema(buildings: tuple[str, ...]) -> dict:
    """Hand-written JSON schema for structured output. Mirrors proposal_model."""
    dev = {
        "type": "object",
        "properties": {k: _nullable_number() for k in DEVICE_KEYS},
        "required": list(DEVICE_KEYS),
        "additionalProperties": False,
    }
    props: dict[str, Any] = {"reason": {"type": "string"}}
    for b in buildings:
        props[b] = dev
    return {"type": "object", "properties": props, "required": ["reason", *buildings], "additionalProperties": False}


def parse_reply(text: str | None, buildings: tuple[str, ...]) -> tuple[dict | None, str | None]:
    """Return ({"reason", "buildings": {b: {device: value}}}, None) or (None, why it was rejected)."""
    if text is None or not text.strip():
        return None, "empty or missing reply"
    try:
        data = json.loads(text)
    except ValueError as exc:
        return None, f"reply is not valid JSON: {exc.msg}"
    if not isinstance(data, dict):
        return None, "reply is not a JSON object"
    data = _ints_to_floats(data)
    try:
        p = proposal_model(tuple(buildings)).model_validate(data)
    except ValidationError as exc:
        first = exc.errors()[0]
        loc = ".".join(str(x) for x in first["loc"])
        return None, f"reply failed schema at {loc or 'root'}: {first['msg']} ({exc.error_count()} error(s))"
    return {"reason": p.reason, "buildings": {b: getattr(p, b).model_dump() for b in buildings}}, None


def _ints_to_floats(obj: Any) -> Any:
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, int):
        return float(obj)
    if isinstance(obj, dict):
        return {k: _ints_to_floats(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_ints_to_floats(v) for v in obj]
    return obj


@dataclass(frozen=True)
class EnvelopeConfig:
    cooling_min: float = 0.0
    cooling_max: float = 1.0
    storage_min: float = -1.0
    storage_max: float = 1.0
    cooling_rate_per_step: float = 0.35
    dhw_rate_per_step: float = 0.5
    battery_rate_per_step: float = 0.5
    soc_min: float = 0.10
    soc_max: float = 0.95
    comfort_band_k: float = dc.COMFORT_BAND_K
    comfort_margin_k: float = 0.5
    # Added in 0.3.0. Cooling may not leave the ideal-load fraction by more than this
    # (a sustained +0.2 overcools the district by about 8 C). None disables the cap.
    cooling_max_deviation: float | None = 0.15
    # Added in 0.3.0. Also refuse extra cooling when it is already cool in unoccupied
    # hours, so the night cannot be chilled into a cold morning.
    overcool_guard_unoccupied: bool = True

    def as_dict(self) -> dict:
        return dict(self.__dict__)

    @classmethod
    def from_manifest(cls, data: dict | None) -> "EnvelopeConfig":
        """Rebuild the config a run used. Fields a run did not record keep the behavior
        they had before they existed, so older runs replay exactly."""
        legacy = {"cooling_max_deviation": None, "overcool_guard_unoccupied": False}
        return cls(**{**legacy, **(data or {})})

    def rate(self, device: str) -> float:
        return {"cooling": self.cooling_rate_per_step, "dhw": self.dhw_rate_per_step,
                "battery": self.battery_rate_per_step}[device]


@dataclass(frozen=True)
class BuildingState:
    """What the envelope needs to know about one building this hour."""

    indoor_c: float
    setpoint_c: float
    occupied: bool
    battery_soc: float
    dhw_soc: float
    baseline: dict[str, float]  # device -> baseline action this hour
    bounds: dict[str, tuple[float, float]]  # device -> CityLearn action space bounds


@dataclass(frozen=True)
class StepContext:
    time_step: int
    buildings: dict[str, BuildingState]


@dataclass
class Clamp:
    point: str
    rule: str
    requested: float | None
    applied: float | None
    reason: str

    def as_dict(self) -> dict:
        return {"point": self.point, "rule": self.rule, "requested": _r(self.requested),
                "applied": _r(self.applied), "reason": self.reason}


def _r(v: float | None) -> float | None:
    return None if v is None else round(float(v), 4)


@dataclass
class Decision:
    """Actions per building and device; None means the baseline action is used."""

    actions: dict[str, dict[str, float | None]]
    clamps: list[Clamp] = field(default_factory=list)
    fallback: str | None = None
    reason: str = ""

    @property
    def status(self) -> str:
        if self.fallback:
            return "fallback"
        return "clamped" if self.clamps else "ok"

    def resolved(self, ctx: StepContext) -> dict[str, dict[str, float]]:
        """Every action as a number, baseline where the decision left it open."""
        out = {}
        for b, st in ctx.buildings.items():
            acts = self.actions.get(b, {})
            out[b] = {d: round(float(st.baseline[d] if acts.get(d) is None else acts[d]), 4) for d in DEVICE_KEYS}
        return out

    def as_dict(self) -> dict:
        return {
            "status": self.status,
            "reason": self.reason,
            "fallback": self.fallback,
            "actions": {b: {d: _r(v) for d, v in acts.items()} for b, acts in self.actions.items()},
            "clamps": [c.as_dict() for c in self.clamps],
        }


def baseline_decision(buildings, fallback: str | None = None) -> Decision:
    return Decision(actions={b: {d: None for d in DEVICE_KEYS} for b in buildings}, fallback=fallback)


class Envelope:
    def __init__(self, config: EnvelopeConfig | None = None) -> None:
        self.config = config or EnvelopeConfig()
        self.memory: dict[str, float] = {}  # "Building_1.battery" -> last applied action

    def fallback(self, ctx: StepContext, why: str) -> Decision:
        """Use the baseline action everywhere and remember it as the last action."""
        self.memory = {f"{b}.{d}": st.baseline[d] for b, st in ctx.buildings.items() for d in DEVICE_KEYS}
        return baseline_decision(ctx.buildings, fallback=why)

    def apply(self, proposal: dict | None, ctx: StepContext, invalid_reason: str | None = None) -> Decision:
        if proposal is None:
            return self.fallback(ctx, invalid_reason or "no valid reply")
        clamps: list[Clamp] = []
        actions: dict[str, dict[str, float | None]] = {}
        memory: dict[str, float] = {}
        for b, st in ctx.buildings.items():
            req = proposal["buildings"].get(b, {})
            actions[b] = {}
            for d in DEVICE_KEYS:
                v = self._limit(b, d, req.get(d), st, clamps)
                actions[b][d] = v
                memory[f"{b}.{d}"] = st.baseline[d] if v is None else v
        self.memory = memory
        return Decision(actions=actions, clamps=clamps, reason=proposal["reason"])

    def _limit(self, b: str, d: str, requested: float | None, st: BuildingState, clamps: list[Clamp]):
        if requested is None:
            return None
        cfg = self.config
        point = f"{b}.{d}"
        if not math.isfinite(requested):  # Pydantic already rejects these; belt and braces.
            clamps.append(Clamp(point, "range", None, None, "non-finite value replaced by the baseline action"))
            return None
        base = st.baseline[d]
        lo_cfg, hi_cfg = (cfg.cooling_min, cfg.cooling_max) if d == "cooling" else (cfg.storage_min, cfg.storage_max)
        blo, bhi = st.bounds[d]
        lo, hi = max(lo_cfg, blo), min(hi_cfg, bhi)
        v = requested
        if v < lo - 1e-9 or v > hi + 1e-9:
            nv = min(max(v, lo), hi)
            clamps.append(Clamp(point, "range", v, nv, f"outside action range {lo:g} to {hi:g}"))
            v = nv
        # Ramp limit: within `rate` of last hour's action or of this hour's baseline action.
        rate = cfg.rate(d)
        prev = self.memory.get(point, base)
        r_lo, r_hi = min(prev, base) - rate, max(prev, base) + rate
        if v < r_lo - 1e-9 or v > r_hi + 1e-9:
            nv = min(max(v, r_lo), r_hi)
            clamps.append(Clamp(point, "rate", v, nv, f"move of {abs(v - prev):.2f} exceeds {rate:g} per step"))
            v = nv
        if d in ("battery", "dhw"):
            soc = st.battery_soc if d == "battery" else st.dhw_soc
            s_lo = max(lo, min(0.0, cfg.soc_min - soc))
            s_hi = min(hi, max(0.0, cfg.soc_max - soc))
            if v < s_lo - 1e-9:
                clamps.append(Clamp(point, "soc", v, s_lo,
                                    f"discharge would take charge from {soc:.2f} below {cfg.soc_min:g}"))
                v = s_lo
            elif v > s_hi + 1e-9:
                clamps.append(Clamp(point, "soc", v, s_hi,
                                    f"charge would take charge from {soc:.2f} above {cfg.soc_max:g}"))
                v = s_hi
        if d == "cooling" and cfg.cooling_max_deviation is not None and abs(v - base) > cfg.cooling_max_deviation + 1e-9:
            nv = base + math.copysign(cfg.cooling_max_deviation, v - base)
            clamps.append(Clamp(point, "deviation", v, nv,
                                f"more than {cfg.cooling_max_deviation:g} away from the ideal-load cooling {base:.2f}"))
            v = nv
        if d == "cooling" and not st.occupied and cfg.overcool_guard_unoccupied:
            band, margin = cfg.comfort_band_k, cfg.comfort_margin_k
            if st.indoor_c <= st.setpoint_c - band + margin and v > base + 1e-9:
                clamps.append(Clamp(point, "comfort", v, base,
                                    f"indoor {st.indoor_c:.1f} C is already near the bottom of the comfort band, "
                                    "no extra cooling while unoccupied"))
                v = base
        if d == "cooling" and st.occupied:
            band, margin = cfg.comfort_band_k, cfg.comfort_margin_k
            if st.indoor_c >= st.setpoint_c + band - margin and v < base - 1e-9:
                clamps.append(Clamp(point, "comfort", v, base,
                                    f"indoor {st.indoor_c:.1f} C is near the top of the comfort band, "
                                    "cooling held at the baseline"))
                v = base
            elif st.indoor_c <= st.setpoint_c - band + margin and v > base + 1e-9:
                clamps.append(Clamp(point, "comfort", v, base,
                                    f"indoor {st.indoor_c:.1f} C is near the bottom of the comfort band, "
                                    "cooling held at the baseline"))
                v = base
        return round(min(max(v, lo), hi), 4)
