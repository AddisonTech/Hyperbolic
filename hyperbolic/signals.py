"""Signals derived from what the controller has already observed (0.4.0).

combined_signal  price and carbon intensity folded into one 0..1 number per hour
PeakTracker      district load before storage, today's and the month's peaks, and a
                 forecast of today's peak, for the prompt and the envelope's peak limiter

Everything here is built from simulator states as they arrive, so a recorded run
replays to the same values.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import district as dc


def _scale(values: list[float | None]) -> list[float | None]:
    known = [v for v in values if v is not None]
    if not known:
        return [None] * len(values)
    lo, hi = min(known), max(known)
    span = hi - lo
    if span < 1e-12:
        return [None] * len(values)  # flat over the window: says nothing about which hour is better
    return [None if v is None else (v - lo) / span for v in values]


def combined_signal(prices: list[float | None], carbons: list[float | None],
                    weights: dict[str, float] = dc.SIGNAL_WEIGHTS) -> list[float | None]:
    """One value per hour: weights["price"] times the price scaled to 0..1 over the window,
    plus weights["carbon"] times the carbon intensity scaled the same way. 0 is the
    cheapest, cleanest hour in the window and 1 the most expensive, dirtiest. An input that
    is flat over the window (a weekend's single price) carries no information and drops out,
    as does an unknown value: the other input is then used alone. If neither is usable, None."""
    p, c = _scale(prices), _scale(carbons)
    wp, wc = weights["price"], weights["carbon"]
    out: list[float | None] = []
    for a, b in zip(p, c):
        if a is None and b is None:
            out.append(None)
        elif a is None:
            out.append(b)
        elif b is None:
            out.append(a)
        else:
            out.append((wp * a + wc * b) / (wp + wc))
    return out


def peak_target_kwh(fraction: float, today_load_peak: float | None, forecast_peak: float | None) -> float | None:
    """The district load the limiter will not let storage charging push past this hour:
    the higher of today's peak so far (load before storage, this hour included) and
    `fraction` of the forecast of today's peak."""
    if today_load_peak is None:
        return None
    if forecast_peak is None:
        return today_load_peak
    return max(today_load_peak, fraction * forecast_peak)


@dataclass(frozen=True)
class PeakInfo:
    load_now_kwh: float | None        # district load before storage this hour
    today_load_peak_kwh: float | None  # highest district load before storage today, this hour included
    forecast_peak_kwh: float | None   # lowest of the last few days' peaks of load before storage
    today_grid_peak_kwh: float | None  # highest measured district draw today, completed hours only
    month_grid_peak_kwh: float | None  # highest measured district draw so far this run


class PeakTracker:
    def __init__(self, forecast_days: int = dc.PEAK_FORECAST_DAYS) -> None:
        self.forecast_days = forecast_days
        self.load: dict[int, float] = {}  # time step -> district load before storage
        self.grid: dict[int, float] = {}  # time step -> measured district net draw
        self.day_load_peak: dict[int, float] = {}

    def update(self, state: dict) -> None:
        t = int(state["time_step"])
        bs = state["buildings"].values()
        if all(s.get("load_kwh") is not None for s in bs):
            load = sum(float(s["load_kwh"]) for s in bs)
            self.load[t] = load
            d = t // 24
            self.day_load_peak[d] = max(self.day_load_peak.get(d, load), load)
        if t > 0:
            # The net draw observed at the start of hour t is what hour t - 1 drew.
            self.grid[t - 1] = sum(float(s["grid_kwh"]) for s in bs)

    def info(self, t: int) -> PeakInfo:
        d = t // 24
        past = [self.day_load_peak[x] for x in range(d - self.forecast_days, d) if x in self.day_load_peak]
        today_grid = [v for k, v in self.grid.items() if k // 24 == d]
        return PeakInfo(
            load_now_kwh=self.load.get(t),
            today_load_peak_kwh=self.day_load_peak.get(d) if t in self.load else None,
            forecast_peak_kwh=min(past) if past else None,
            today_grid_peak_kwh=max(today_grid) if today_grid else None,
            month_grid_peak_kwh=max(self.grid.values()) if self.grid else None,
        )
