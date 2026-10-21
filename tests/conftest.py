from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent / "fixtures"))

from hyperbolic.envelope import Envelope, EnvelopeConfig, Proposal, StepContext  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"

# Day 18 of the year, hour of day as given. Occupied 06:00 to 19:00.
DAY = 18 * 86400


def at(hour: int) -> float:
    return DAY + hour * 3600


def ctx(hour: int) -> StepContext:
    occupied = 6 <= hour < 19
    return StepContext(time_s=at(hour), band_lower_c=20.0 if occupied else 12.0,
                       band_upper_c=24.0 if occupied else 30.0)


def proposal(reason: str = "test", supply_air_c=None, **zones) -> Proposal:
    data = {"reason": reason, "supply_air_c": supply_air_c}
    for z in ("nor", "eas", "sou", "wes", "cor"):
        h, c = zones.get(z, (None, None))
        data[z] = {"heat_c": h, "cool_c": c}
    return Proposal.model_validate(data)


@pytest.fixture
def envelope() -> Envelope:
    return Envelope(EnvelopeConfig())


@pytest.fixture
def fixture_runs() -> tuple[Path, Path]:
    import make_fixtures

    return make_fixtures.BASELINE, make_fixtures.AGENT
