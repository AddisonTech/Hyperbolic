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
  8. trim hold (0.8.0): a cooling trim, once on, is carried in code. While the room is
     occupied and more than trim_hold_c below its setpoint it stays at least as deep as
     last hour; within trim_hold_c it eases off by at most trim_release_step per hour; it
     ends at once at or above the setpoint, in an unoccupied room, or when the baseline
     has no cooling to trim. The model can end one early only with end_trim and a reason
Then, across the district:
  9. peak limit: storage charging is trimmed so the district's load this hour stays at
     or below the peak target (signals.peak_target_kwh), battery first, then the tank
A null action, or any invalid reply, uses the baseline action for that device.
Every clamp and fallback is returned with a reason so the runner can log it, and every
trim hold action (start, hold, ease, release, end, early end) is recorded with its reason.
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


class DeviceActionsV6(DeviceActions):
    """Prompt version 6 (0.8.0): a building may also end its held cooling trim early, with a reason."""

    end_trim: str | None = Field(default=None, min_length=1, max_length=dc.REASON_MAX_CHARS)


@lru_cache(maxsize=8)
def proposal_model(buildings: tuple[str, ...], end_trim: bool = False) -> type[BaseModel]:
    """The only shape the model is allowed to return: a reason plus one entry per building."""
    fields: dict[str, Any] = {"reason": (str, Field(min_length=1, max_length=dc.REASON_MAX_CHARS))}
    for b in buildings:
        fields[b] = (DeviceActionsV6 if end_trim else DeviceActions, ...)
    return create_model(
        "Proposal", __config__=ConfigDict(extra="forbid", strict=True, allow_inf_nan=False), **fields
    )


def _nullable_number() -> dict:
    return {"anyOf": [{"type": "number"}, {"type": "null"}]}


def proposal_json_schema(buildings: tuple[str, ...], end_trim: bool = False) -> dict:
    """Hand-written JSON schema for structured output. Mirrors proposal_model."""
    dev = {
        "type": "object",
        "properties": {k: _nullable_number() for k in DEVICE_KEYS},
        "required": list(DEVICE_KEYS),
        "additionalProperties": False,
    }
    if end_trim:
        dev["properties"]["end_trim"] = {"anyOf": [{"type": "string"}, {"type": "null"}]}
        dev["required"].append("end_trim")
    props: dict[str, Any] = {"reason": {"type": "string"}}
    for b in buildings:
        props[b] = dev
    return {"type": "object", "properties": props, "required": ["reason", *buildings], "additionalProperties": False}


def parse_reply(text: str | None, buildings: tuple[str, ...], end_trim: bool = False) -> tuple[dict | None, str | None]:
    """Return ({"reason", "buildings": {b: {device: value}}}, None) or (None, why it was rejected).
    With end_trim (prompt version 6) the result also has "end_trim": {b: reason} for every
    building whose reply ends its held cooling trim early."""
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
        p = proposal_model(tuple(buildings), end_trim).model_validate(data)
    except ValidationError as exc:
        first = exc.errors()[0]
        loc = ".".join(str(x) for x in first["loc"])
        return None, f"reply failed schema at {loc or 'root'}: {first['msg']} ({exc.error_count()} error(s))"
    out = {"reason": p.reason,
           "buildings": {b: {d: getattr(getattr(p, b), d) for d in DEVICE_KEYS} for b in buildings}}
    if end_trim:
        out["end_trim"] = {b: getattr(p, b).end_trim for b in buildings if getattr(p, b).end_trim is not None}
    return out, None


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
    # Added in 0.8.0. Carry a cooling trim in code once it is on (Envelope._hold_trim). The
    # numbers are the version 5 strategy's (StrategyParamsV5.trim_hold_c and trim_step); a trim
    # shallower than trim_min_depth counts as off, so rounding never starts one, and a reply that
    # misses the held depth by less than it is taken as rounding, not as a release.
    trim_hold: bool = True
    trim_hold_c: float = 0.5
    trim_release_step: float = 0.02
    trim_min_depth: float = 0.002

    def as_dict(self) -> dict:
        return dict(self.__dict__)

    @classmethod
    def from_manifest(cls, data: dict | None) -> "EnvelopeConfig":
        """Rebuild the config a run used. Fields a run did not record keep the behavior
        they had before they existed, so older runs replay exactly."""
        legacy = {"cooling_max_deviation": None, "overcool_guard_unoccupied": False, "peak_limit": False,
                  "spread_check": False, "trim_hold": False}
        return cls(**{**legacy, **(data or {})})

    @classmethod
    def v040(cls) -> "EnvelopeConfig":
        """The 0.4.0 rule set: everything before the spread check. The rule-based reference
        controller runs with it so its 0.4.0 result reproduces exactly."""
        return cls(spread_check=False, trim_hold=False)

    @classmethod
    def v070(cls) -> "EnvelopeConfig":
        """The 0.7.0 rule set: everything before the trim hold. Runs on prompt versions before 6
        use it, so they behave as they did in 0.7.0."""
        return cls(trim_hold=False)

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


def _hold_event(b: str, action: str, depth_before: float, depth_after: float, reason: str) -> dict:
    return {"building": b, "action": action, "depth_before": _r(depth_before), "depth_after": _r(depth_after),
            "reason": reason}


@dataclass
class Decision:
    """Actions per building and device; None means the baseline action is used."""

    actions: dict[str, dict[str, float | None]]
    clamps: list[Clamp] = field(default_factory=list)
    fallback: str | None = None
    reason: str = ""
    holds: list[dict] = field(default_factory=list)  # trim hold actions this hour (0.8.0)

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
        out = {
            "status": self.status,
            "reason": self.reason,
            "fallback": self.fallback,
            "actions": {b: {d: _r(v) for d, v in acts.items()} for b, acts in self.actions.items()},
            "clamps": [c.as_dict() for c in self.clamps],
        }
        if self.holds:  # absent when the hold did nothing, so older runs replay byte for byte
            out["holds"] = [dict(h) for h in self.holds]
        return out


def baseline_decision(buildings, fallback: str | None = None) -> Decision:
    return Decision(actions={b: {d: None for d in DEVICE_KEYS} for b in buildings}, fallback=fallback)


class Envelope:
    def __init__(self, config: EnvelopeConfig | None = None) -> None:
        self.config = config or EnvelopeConfig()
        self.memory: dict[str, float] = {}  # "Building_1.battery" -> last applied action
        self.trims: dict[str, float] = {}  # building -> last hour's cooling minus its baseline (0.7.0, read only)
        self.holds: dict[str, float] = {}  # building -> depth of the cooling trim being held (0.8.0)

    def fallback(self, ctx: StepContext, why: str) -> Decision:
        """Use the baseline action everywhere and remember it as the last action."""
        self.memory = {f"{b}.{d}": st.baseline[d] for b, st in ctx.buildings.items() for d in DEVICE_KEYS}
        self.trims = {}
        self.holds = {}
        return baseline_decision(ctx.buildings, fallback=why)

    def apply(self, proposal: dict | None, ctx: StepContext, invalid_reason: str | None = None) -> Decision:
        if proposal is None:
            return self.fallback(ctx, invalid_reason or "no valid reply")
        clamps: list[Clamp] = []
        actions: dict[str, dict[str, float | None]] = {}
        memory: dict[str, float] = {}
        events: list[dict] = []
        holds: dict[str, float] = {}
        early = proposal.get("end_trim") or {}
        for b, st in ctx.buildings.items():
            req = proposal["buildings"].get(b, {})
            actions[b] = {}
            for d in DEVICE_KEYS:
                v = self._limit(b, d, req.get(d), st, clamps, ctx.prices)
                if d == "cooling" and self.config.trim_hold:
                    v = self._hold_trim(b, v, st, early.get(b), clamps, events, holds)
                actions[b][d] = v
                memory[f"{b}.{d}"] = st.baseline[d] if v is None else v
        if self.config.peak_limit:
            self._limit_peak(actions, ctx, clamps, memory)
        self.memory = memory
        self.trims = {b: 0.0 if actions[b]["cooling"] is None else actions[b]["cooling"] - st.baseline["cooling"]
                      for b, st in ctx.buildings.items()}
        if self.config.trim_hold:
            self.holds = holds
        return Decision(actions=actions, clamps=clamps, reason=proposal["reason"], holds=events)

    def held_trim(self, b: str, st: BuildingState) -> tuple[float, str, str]:
        """What the trim hold requires of building b this hour, before any early end:
        (depth cooling must stay at least this far below the baseline, kind, why). kind is
        "none" (no trim on), "end" (no trim may run now), "hold" or "ease"."""
        cfg = self.config
        prev = self.holds.get(b, 0.0)
        gap = st.indoor_c - st.setpoint_c
        if st.baseline["cooling"] <= cfg.trim_min_depth:
            return 0.0, "end", "the baseline has no cooling to trim"
        if not st.occupied:
            return 0.0, "end", "the room is unoccupied"
        if gap >= 0:
            return 0.0, "end", f"indoor {st.indoor_c:.1f} C is at or above the setpoint {st.setpoint_c:.1f} C"
        if prev <= cfg.trim_min_depth:
            return 0.0, "none", ""
        if gap < -cfg.trim_hold_c:
            return prev, "hold", (f"indoor {st.indoor_c:.1f} C is more than {cfg.trim_hold_c:g} C below the setpoint "
                                  f"{st.setpoint_c:.1f} C, trim held at {prev:.3f}")
        need = round(max(0.0, prev - cfg.trim_release_step), 4)
        return need, "ease", (f"indoor {st.indoor_c:.1f} C is within {cfg.trim_hold_c:g} C of the setpoint "
                              f"{st.setpoint_c:.1f} C, trim eases off from {prev:.3f} by at most "
                              f"{cfg.trim_release_step:g} per hour")

    def _hold_trim(self, b: str, v: float | None, st: BuildingState, early: str | None, clamps: list[Clamp],
                   events: list[dict], holds: dict[str, float]) -> float | None:
        """Carry building b's cooling trim (0.8.0). A trim is cooling more than trim_min_depth
        below the baseline action, and its depth is how far below. This runs after the comfort
        rule and only keeps cooling below the baseline, by no more than the trim already passed
        the deviation limit with, so it never undoes another rule. Every action is recorded in
        events; a changed value is also a clamp with rule trim_hold."""
        cfg = self.config
        point = f"{b}.cooling"
        base = st.baseline["cooling"]
        prev = self.holds.get(b, 0.0)
        on = prev > cfg.trim_min_depth
        applied = base if v is None else v
        need, kind, why = self.held_trim(b, st)
        if kind != "end" and on and early:
            kind, why = "end_early", f"the model ended it early: {early}"
        if kind in ("end", "end_early"):
            trimmed = base - applied > cfg.trim_min_depth
            if trimmed:
                clamps.append(Clamp(point, "trim_hold", applied, round(base, 4),
                                    f"trim ended, {why}, cooling back to the baseline"))
                v = round(base, 4)
            if on or trimmed:
                events.append(_hold_event(b, kind, prev, 0.0, early if kind == "end_early" else why))
            return v
        acted = False
        # A miss smaller than trim_min_depth is rounding (the observation shows the baseline and
        # trims to 3 decimals) and is let through; the held depth below still counts in full.
        if on and base - applied < need - cfg.trim_min_depth:
            lo = max(cfg.cooling_min, st.bounds["cooling"][0])
            nv = round(max(lo, base - need), 4)
            clamps.append(Clamp(point, "trim_hold", applied, nv, why))
            v = applied = nv
            acted = True
        depth = round(max(base - applied, need), 4)
        if depth <= cfg.trim_min_depth:
            if on:
                events.append(_hold_event(b, "release", prev, 0.0, "trim eased off fully"))
            return v
        holds[b] = depth
        if not on:
            events.append(_hold_event(b, "start", 0.0, depth, "trim started"))
        elif acted:
            events.append(_hold_event(b, kind, prev, depth, why))
        return v

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
