"""Safety envelope applied to every supervisory proposal before it reaches the simulator.

Order of checks for each setpoint:
  1. schema validation (Pydantic, strict, finite numbers only)
  2. equipment range clamp
  3. rate limit per step, measured from the previous setpoint or from where
     the stock schedule's own step would carry it
  4. comfort clamp to the BOPTEST comfort band (always wins over the rate limit)
  5. heating/cooling deadband
A null setpoint, or any invalid reply, releases that point to the stock control.
Every clamp and fallback is returned with a reason so the runner can log it.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from . import testcase as tc


class ZoneSetpoints(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    heat_c: float | None
    cool_c: float | None


class Proposal(BaseModel):
    """The only thing the model is allowed to return."""

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    reason: str = Field(min_length=1, max_length=300)
    nor: ZoneSetpoints
    eas: ZoneSetpoints
    sou: ZoneSetpoints
    wes: ZoneSetpoints
    cor: ZoneSetpoints
    supply_air_c: float | None


def _nullable_number() -> dict:
    return {"anyOf": [{"type": "number"}, {"type": "null"}]}


def proposal_json_schema() -> dict:
    """Hand-written JSON schema for structured output. Mirrors Proposal."""
    zone = {
        "type": "object",
        "properties": {"heat_c": _nullable_number(), "cool_c": _nullable_number()},
        "required": ["heat_c", "cool_c"],
        "additionalProperties": False,
    }
    props: dict[str, Any] = {"reason": {"type": "string"}}
    for z in tc.ZONES:
        props[z] = zone
    props["supply_air_c"] = _nullable_number()
    return {
        "type": "object",
        "properties": props,
        "required": ["reason", *tc.ZONES, "supply_air_c"],
        "additionalProperties": False,
    }


def parse_reply(text: str | None) -> tuple[Proposal | None, str | None]:
    """Return (proposal, None) or (None, why it was rejected)."""
    if text is None or not text.strip():
        return None, "empty or missing reply"
    try:
        data = json.loads(text)
    except ValueError as exc:
        return None, f"reply is not valid JSON: {exc.msg}"
    if not isinstance(data, dict):
        return None, "reply is not a JSON object"
    # JSON has no integer/float split for setpoints; accept ints as floats.
    data = _ints_to_floats(data)
    try:
        return Proposal.model_validate(data), None
    except ValidationError as exc:
        first = exc.errors()[0]
        loc = ".".join(str(p) for p in first["loc"])
        return None, f"reply failed schema at {loc or 'root'}: {first['msg']} ({exc.error_count()} error(s))"


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
    zone_heat_min_c: float = 12.0
    zone_heat_max_c: float = 24.0
    zone_cool_min_c: float = 21.0
    zone_cool_max_c: float = 30.0
    min_deadband_k: float = 1.0
    supply_air_min_c: float = 12.0
    supply_air_max_c: float = 18.0
    zone_rate_k_per_step: float = 2.0
    supply_rate_k_per_step: float = 1.5
    comfort_slack_k: float = 0.0
    supply_air_occupied_only: bool = True

    def as_dict(self) -> dict:
        return dict(self.__dict__)


@dataclass
class Clamp:
    point: str
    rule: str
    requested: float | None
    applied: float | None
    reason: str

    def as_dict(self) -> dict:
        return {
            "point": self.point,
            "rule": self.rule,
            "requested": _r(self.requested),
            "applied": _r(self.applied),
            "reason": self.reason,
        }


@dataclass
class Decision:
    """Setpoints in degC that will be written; None means left to stock control."""

    heat_c: dict[str, float | None]
    cool_c: dict[str, float | None]
    supply_air_c: float | None
    clamps: list[Clamp] = field(default_factory=list)
    fallback: str | None = None
    reason: str = ""

    @property
    def status(self) -> str:
        if self.fallback:
            return "fallback"
        return "clamped" if self.clamps else "ok"

    def to_boptest_u(self, time_s: float) -> dict[str, float]:
        """Overwrite dict for POST advance. Released points are sent with activate 0."""
        stock_h, stock_c = tc.stock_zone_setpoints_c(time_s)
        u: dict[str, float] = {}
        for z in tc.ZONES:
            for name, val, stock in (
                (tc.heat_set_input(z), self.heat_c[z], stock_h),
                (tc.cool_set_input(z), self.cool_c[z], stock_c),
            ):
                u[f"{name}_u"] = round(tc.c_to_k(stock if val is None else val), 3)
                u[f"{name}_activate"] = 0 if val is None else 1
        sa = self.supply_air_c
        u[f"{tc.SUPPLY_AIR_INPUT}_u"] = round(tc.c_to_k(tc.STOCK_SUPPLY_AIR_OCCUPIED_C if sa is None else sa), 3)
        u[f"{tc.SUPPLY_AIR_INPUT}_activate"] = 0 if sa is None else 1
        return u

    def as_dict(self) -> dict:
        return {
            "status": self.status,
            "reason": self.reason,
            "fallback": self.fallback,
            "heat_c": {z: _r(v) for z, v in self.heat_c.items()},
            "cool_c": {z: _r(v) for z, v in self.cool_c.items()},
            "supply_air_c": _r(self.supply_air_c),
            "clamps": [c.as_dict() for c in self.clamps],
        }


def _r(v: float | None) -> float | None:
    return None if v is None else round(float(v), 3)


def baseline_decision(fallback: str | None = None, reason: str = "") -> Decision:
    return Decision(
        heat_c={z: None for z in tc.ZONES},
        cool_c={z: None for z in tc.ZONES},
        supply_air_c=None,
        fallback=fallback,
        reason=reason,
    )


@dataclass
class PointMemory:
    """What a setpoint did in the previous step. effective is None when it was
    released, in which case the stock schedule value is used as the reference."""

    effective: float | None = None
    offset: float = 0.0


@dataclass
class EnvelopeState:
    points: dict[str, PointMemory] = field(default_factory=dict)

    def get(self, point: str) -> PointMemory:
        return self.points.get(point, PointMemory())


@dataclass(frozen=True)
class StepContext:
    time_s: float
    band_lower_c: float
    band_upper_c: float


class Envelope:
    def __init__(self, config: EnvelopeConfig | None = None) -> None:
        self.config = config or EnvelopeConfig()
        self.state = EnvelopeState()

    def fallback(self, why: str) -> Decision:
        """Hand every point back to the stock control and reset rate-limit memory."""
        self.state = EnvelopeState()
        return baseline_decision(fallback=why, reason="")

    def apply(self, proposal: Proposal | None, ctx: StepContext, invalid_reason: str | None = None) -> Decision:
        if proposal is None:
            return self.fallback(invalid_reason or "no valid reply")
        cfg = self.config
        clamps: list[Clamp] = []
        stock_h, stock_c = tc.stock_zone_setpoints_c(ctx.time_s)
        prev_h, prev_c = tc.stock_zone_setpoints_c(ctx.time_s - tc.STEP_SECONDS)
        comfort_lo = ctx.band_lower_c - cfg.comfort_slack_k
        comfort_hi = ctx.band_upper_c + cfg.comfort_slack_k
        heat: dict[str, float | None] = {}
        cool: dict[str, float | None] = {}
        new_state = EnvelopeState()

        for z in tc.ZONES:
            req: ZoneSetpoints = getattr(proposal, z)
            hp, cp = f"{z}.heat_c", f"{z}.cool_c"
            h = self._limit(hp, req.heat_c, stock_h, prev_h, cfg.zone_heat_min_c, cfg.zone_heat_max_c,
                            cfg.zone_rate_k_per_step, comfort_lo, None, clamps)
            c = self._limit(cp, req.cool_c, stock_c, prev_c, cfg.zone_cool_min_c, cfg.zone_cool_max_c,
                            cfg.zone_rate_k_per_step, None, comfort_hi, clamps)
            h, c = self._deadband(z, h, c, stock_h, stock_c, comfort_lo, comfort_hi, clamps)
            heat[z], cool[z] = h, c
            new_state.points[hp] = self._memory(h, stock_h)
            new_state.points[cp] = self._memory(c, stock_c)

        sa_req = proposal.supply_air_c
        stock_sa = tc.STOCK_SUPPLY_AIR_OCCUPIED_C
        if sa_req is not None and cfg.supply_air_occupied_only and not tc.is_occupied_hour(ctx.time_s):
            clamps.append(Clamp("supply_air_c", "schedule", sa_req, None,
                                "supply air setpoint is left to stock control outside occupied hours"))
            sa = None
        else:
            sa = self._limit("supply_air_c", sa_req, stock_sa, stock_sa, cfg.supply_air_min_c,
                             cfg.supply_air_max_c, cfg.supply_rate_k_per_step, None, None, clamps)
        new_state.points["supply_air_c"] = self._memory(sa, stock_sa)
        self.state = new_state
        return Decision(heat_c=heat, cool_c=cool, supply_air_c=sa, clamps=clamps, reason=proposal.reason)

    @staticmethod
    def _memory(value: float | None, stock: float) -> PointMemory:
        if value is None:
            return PointMemory()
        return PointMemory(effective=value, offset=value - stock)

    def _limit(self, point, requested, stock, stock_prev, lo, hi, rate, comfort_min, comfort_max, clamps):
        if requested is None:
            return None
        if not math.isfinite(requested):  # Pydantic already rejects these; belt and braces.
            clamps.append(Clamp(point, "range", None, None, "non-finite value released to stock control"))
            return None
        v = requested
        if v < lo or v > hi:
            nv = min(max(v, lo), hi)
            clamps.append(Clamp(point, "range", v, nv, f"outside equipment range {lo:g} to {hi:g} C"))
            v = nv
        # A setpoint may move at most `rate` per step from where it was last step,
        # or from where the stock schedule's own step would have carried it, or
        # land anywhere between those two references.
        mem = self.state.get(point)
        prev_eff = stock_prev if mem.effective is None else mem.effective
        shifted = stock + mem.offset
        lo_ok, hi_ok = min(prev_eff, shifted) - rate, max(prev_eff, shifted) + rate
        if not lo_ok - 1e-9 <= v <= hi_ok + 1e-9:
            nv = min(max(v, lo_ok), hi_ok)
            clamps.append(Clamp(point, "rate", v, nv,
                                f"move of {abs(v - prev_eff):.2f} K exceeds {rate:g} K per step"))
            v = nv
        if comfort_min is not None and v < comfort_min:
            clamps.append(Clamp(point, "comfort", v, comfort_min, f"below comfort band lower limit {comfort_min:g} C"))
            v = comfort_min
        if comfort_max is not None and v > comfort_max:
            clamps.append(Clamp(point, "comfort", v, comfort_max, f"above comfort band upper limit {comfort_max:g} C"))
            v = comfort_max
        return round(v, 3)

    def _deadband(self, z, h, c, stock_h, stock_c, comfort_lo, comfort_hi, clamps):
        db = self.config.min_deadband_k
        eff_h = stock_h if h is None else h
        eff_c = stock_c if c is None else c
        if eff_c - eff_h >= db - 1e-9:
            return h, c
        # Prefer moving the cooling setpoint up, within comfort and range.
        target_c = min(eff_h + db, comfort_hi, self.config.zone_cool_max_c)
        if target_c - eff_h >= db - 1e-9:
            clamps.append(Clamp(f"{z}.cool_c", "deadband", eff_c, target_c,
                                f"cooling setpoint raised to keep {db:g} K above heating"))
            return h, round(target_c, 3)
        target_h = max(eff_c - db, comfort_lo, self.config.zone_heat_min_c)
        clamps.append(Clamp(f"{z}.heat_c", "deadband", eff_h, target_h,
                            f"heating setpoint lowered to keep {db:g} K below cooling"))
        if c is None:
            c = eff_c
        return round(target_h, 3), c
