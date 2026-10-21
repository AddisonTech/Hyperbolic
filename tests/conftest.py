from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent / "fixtures"))

from hyperbolic.envelope import BuildingState, Envelope, EnvelopeConfig, StepContext  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"
BUILDINGS = ("Building_1", "Building_2", "Building_3")


def bstate(indoor=24.0, setpoint=24.0, occupied=True, battery_soc=0.5, dhw_soc=0.5, cooling_base=0.4,
           battery_bounds=(-0.83, 0.83)) -> BuildingState:
    return BuildingState(indoor_c=indoor, setpoint_c=setpoint, occupied=occupied, battery_soc=battery_soc,
                         dhw_soc=dhw_soc, baseline={"cooling": cooling_base, "dhw": 0.0, "battery": 0.0},
                         bounds={"cooling": (0.0, 1.0), "dhw": (-1.0, 1.0), "battery": battery_bounds})


def ctx(t=10, **overrides) -> StepContext:
    """Overrides are per-building BuildingState kwargs keyed by building name."""
    return StepContext(time_step=t, buildings={b: bstate(**overrides.get(b, {})) for b in BUILDINGS})


def proposal(reason="test", **buildings) -> dict:
    out = {"reason": reason, "buildings": {}}
    for b in BUILDINGS:
        acts = buildings.get(b, {})
        out["buildings"][b] = {d: acts.get(d) for d in ("cooling", "dhw", "battery")}
    return out


def citylearn_available() -> bool:
    try:
        import citylearn  # noqa: F401
        import torch  # noqa: F401
    except Exception:
        return False
    return True


needs_citylearn = pytest.mark.skipif(not citylearn_available(), reason="CityLearn and torch are not installed")


@pytest.fixture
def envelope() -> Envelope:
    return Envelope(EnvelopeConfig())


@pytest.fixture
def fixture_runs() -> tuple[Path, Path]:
    import make_fixtures

    return make_fixtures.BASELINE, make_fixtures.AGENT
