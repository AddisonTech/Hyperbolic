"""Safety envelope applied to every supervisory proposal before it reaches the simulator.

For each building and device the checks run in this order:
  1. schema validation (Pydantic, strict, finite numbers only)
  2. action range: the configured limits intersected with CityLearn's action space
  3. rate limit per step, measured from last hour's action or from this hour's
     baseline action, whichever is closer
  4. state of charge limits for the battery and the hot water tank
  5. price spread (0.6.0): no grid charging of a battery when no price in the next
     24 hours, after the battery's worst round trip efficiency and its standing losses
     until then, is worth more than the price now and a cheaper hour is coming; spare
     solar may still be stored
  6. cooling deviation: at most cooling_max_deviation away from the ideal-load fraction
  7. comfort: in occupied hours near the edge of CityLearn's comfort band the heat
     pump may not cool less (too warm) or more (too cool) than the baseline action,
     and with overcool_guard_unoccupied no extra cooling when already cool at night
Then, across the district:
  8. peak limit: storage charging is trimmed so the district's load this hour stays at
     or below the peak target (signals.peak_target_kwh), battery first, then the tank
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
from .signals import PeakInfo, PriceOutlook, charge_spread, peak_target_kwh

DEVICE_KEYS = tuple(dc.DEVICES.values())  # cooling, dhw, battery


class DeviceActions(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    cooling: float | None
    dhw: float | None
    battery: float | None


@lru_cache(maxsize=8)
def proposal_model(buildings: tuple[str, ...]) -> type[BaseModel]:
    """The only shape the model is allowed to return: a reason plus one entry per building."""
    fields: dict[str, Any] = {"reason": (str, Field(min_length=1, max_length=dc.REASON_MAX_CHARS))}
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
    # Added in 0.4.0. Trim storage charging so district load never passes the peak target:
    # the higher of today's peak so far and peak_target_fraction of the forecast peak.
    peak_limit: bool = True
    peak_target_fraction: float = 1.0  # picked on the tuning week by scripts/tune_rules.py
    peak_forecast_days: int = dc.PEAK_FORECAST_DAYS
    # Added in 0.6.0. Block grid charging of a battery when the price outlook cannot pay back
    # its round trip and standing losses and a cheaper hour is coming (signals.charge_spread).
    # Physical, not fitted: the efficiency and loss come from the battery itself.
    spread_check: bool = True

    def as_dict(self) -> dict:
        return dict(self.__dict__)

    @classmethod
    def from_manifest(cls, data: dict | None) -> "EnvelopeConfig":
        """Rebuild the config a run used. Fields a run did not record keep the behavior
        they had before they existed, so older runs replay exactly."""
        legacy = {"cooling_max_deviation": None, "overcool_guard_unoccupied": False, "peak_limit": False,
                  "spread_check": False}
        return cls(**{**legacy, **(data or {})})

    @classmethod
    def v040(cls) -> "EnvelopeConfig":
        """The 0.4.0 rule set: everything before the spread check. The rule-based reference
        controller runs with it so its 0.4.0 result reproduces exactly."""
        return cls(spread_check=False)

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
    # Added in 0.4.0 for the peak limiter; absent from runs recorded before it.
    load_kwh: float | None = None  # net draw this hour with storage idle and baseline cooling
    cooling_power_kw: float | None = None
    battery_capacity_kwh: float | None = None
    dhw_capacity_kwh: float | None = None
    dhw_heater_efficiency: float | None = None
    # Added in 0.6.0 for the spread check.
    battery_round_trip_min: float | None = None
    battery_loss_per_hour: float | None = None


@dataclass(frozen=True)
class StepContext:
    time_step: int
    buildings: dict[str, BuildingState]
    peak: PeakInfo | None = None
    prices: PriceOutlook | None = None  # added in 0.6.0


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
        self.trims: dict[str, float] = {}  # building -> last hour's cooling minus its baseline (0.7.0, read only)

    def fallback(self, ctx: StepContext, why: str) -> Decision:
        """Use the baseline action everywhere and remember it as the last action."""
        self.memory = {f"{b}.{d}": st.baseline[d] for b, st in ctx.buildings.items() for d in DEVICE_KEYS}
        self.trims = {}
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
                v = self._limit(b, d, req.get(d), st, clamps, ctx.prices)
                actions[b][d] = v
                memory[f"{b}.{d}"] = st.baseline[d] if v is None else v
        if self.config.peak_limit:
            self._limit_peak(actions, ctx, clamps, memory)
        self.memory = memory
        self.trims = {b: 0.0 if actions[b]["cooling"] is None else actions[b]["cooling"] - st.baseline["cooling"]
                      for b, st in ctx.buildings.items()}
        return Decision(actions=actions, clamps=clamps, reason=proposal["reason"])

    def peak_target(self, ctx: StepContext) -> float | None:
        if ctx.peak is None:
            return None
        return peak_target_kwh(self.config.peak_target_fraction, ctx.peak.today_load_peak_kwh,
                               ctx.peak.forecast_peak_kwh)

    def district_load(self, actions: dict, ctx: StepContext) -> float | None:
        """Estimated district draw this hour with these actions. Discharging earns no credit,
        so the estimate never understates the load."""
        total = 0.0
        for b, st in ctx.buildings.items():
            if st.load_kwh is None or st.cooling_power_kw is None:
                return None
            acts = actions.get(b, {})
            total += st.load_kwh + self._extra_kwh(b, "cooling", acts.get("cooling"), st)
            total += self._extra_kwh(b, "battery", acts.get("battery"), st)
            total += self._extra_kwh(b, "dhw", acts.get("dhw"), st)
        return total

    @staticmethod
    def _extra_kwh(b: str, d: str, v: float | None, st: BuildingState) -> float:
        if v is None:
            return 0.0
        if d == "cooling":
            return (v - st.baseline["cooling"]) * (st.cooling_power_kw or 0.0)
        if v <= 0:
            return 0.0
        if d == "battery":
            return v * (st.battery_capacity_kwh or 0.0)
        return v * (st.dhw_capacity_kwh or 0.0) / max(st.dhw_heater_efficiency or 1.0, 1e-6)

    def _limit_peak(self, actions: dict, ctx: StepContext, clamps: list[Clamp], memory: dict) -> None:
        target = self.peak_target(ctx)
        total = self.district_load(actions, ctx)
        if target is None or total is None or total <= target + 1e-9:
            return
        for d in ("battery", "dhw"):
            excess = total - target
            charging = {b: self._extra_kwh(b, d, actions[b].get(d), st) for b, st in ctx.buildings.items()}
            energy = sum(charging.values())
            if energy <= 0:
                continue
            keep = max(0.0, (energy - excess) / energy)
            for b, e in charging.items():
                if e <= 0:
                    continue
                old = actions[b][d]
                new = math.floor(old * keep * 1e4) / 1e4  # round down so the target holds
                clamps.append(Clamp(f"{b}.{d}", "peak", old, new,
                                    f"district load {total:.2f} kWh would pass the peak target {target:.2f} kWh, "
                                    "charging trimmed"))
                actions[b][d] = new
                memory[f"{b}.{d}"] = new
            total = self.district_load(actions, ctx)
            if total <= target + 1e-9:
                return

    @staticmethod
    def _limit_spread(point: str, v: float, st: BuildingState, prices: PriceOutlook | None,
                      clamps: list[Clamp]) -> float:
        """Grid charging must be able to pay for itself: blocked when no price ahead, after the
        battery's round trip and standing losses, is worth more than the price now while a
        cheaper hour is coming. Spare solar, which would be exported for nothing, may always
        be stored."""
        if prices is None or st.battery_round_trip_min is None or not st.battery_capacity_kwh:
            return v
        spread = charge_spread(prices, st.battery_round_trip_min, st.battery_loss_per_hour or 0.0)
        if spread is None or not spread.blocked:
            return v
        solar = max(0.0, -(st.load_kwh or 0.0)) / st.battery_capacity_kwh
        nv = min(v, math.floor(solar * 1e4) / 1e4)
        if nv >= v - 1e-9:
            return v
        why = (f"price {prices.now:.4f} now, best ahead {spread.best_price:.4f} in {spread.best_hours_ahead} h "
               f"does not cover {(1.0 - spread.keep) * 100.0:.0f}% round trip and standing losses and a cheaper "
               f"hour comes in {spread.cheaper_hours_ahead} h, grid charging blocked")
        clamps.append(Clamp(point, "spread", v, nv, why + (", spare solar still stored" if nv > 0 else "")))
        return nv

    def _limit(self, b: str, d: str, requested: float | None, st: BuildingState, clamps: list[Clamp],
               prices: PriceOutlook | None = None):
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
        if d == "battery" and cfg.spread_check and v > 1e-9:
            v = self._limit_spread(point, v, st, prices, clamps)
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
