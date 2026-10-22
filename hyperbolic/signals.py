"""Signals derived from what the controller has already observed (0.4.0).

combined_signal  price and carbon intensity folded into one 0..1 number per hour
PeakTracker      district load before storage, today's and the month's peaks, and a
                 forecast of today's peak, for the prompt and the envelope's peak limiter
charge_spread    whether grid charging a battery now can pay back its losses (0.6.0)

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
class PriceOutlook:
    """The price now and over the next hours, from forecasts already received (prompt.Lookahead)."""

    now: float
    ahead: tuple[float | None, ...]  # hours 1, 2, ... ahead; None where nothing is known yet


@dataclass(frozen=True)
class ChargeSpread:
    pays: bool                     # some hour ahead is worth more than now after losses
    best_price: float              # the price of the hour worth most after losses
    best_hours_ahead: int
    keep: float                    # share of a kWh bought now that is left to use at that hour
    cheaper_hours_ahead: int | None  # the first hour ahead with a lower price than now, if any

    @property
    def blocked(self) -> bool:
        """Charging now is dominated: nothing in view pays it back, and a cheaper hour is coming.
        A flat outlook (a weekend) does not block, because the next price peak may lie beyond it."""
        return not self.pays and self.cheaper_hours_ahead is not None


def charge_spread(prices: PriceOutlook, round_trip: float, loss_per_hour: float) -> ChargeSpread | None:
    """A kWh bought now and used j hours later keeps round_trip x (1 - loss_per_hour)^j of itself.
    Charging pays when that share times some known price ahead is more than the price now. The
    efficiency is the battery's worst, so a charge that passes pays at any power. None when no
    price ahead is known."""
    best, cheaper = None, None
    for j, p in enumerate(prices.ahead, start=1):
        if p is None:
            continue
        keep = round_trip * (1.0 - loss_per_hour) ** j
        if best is None or p * keep > best[0] + 1e-12:
            best = (p * keep, p, j, keep)
        if cheaper is None and p < prices.now - 1e-9:
            cheaper = j
    if best is None:
        return None
    return ChargeSpread(pays=best[0] > prices.now + 1e-9, best_price=best[1], best_hours_ahead=best[2], keep=best[3],
                        cheaper_hours_ahead=cheaper)


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
