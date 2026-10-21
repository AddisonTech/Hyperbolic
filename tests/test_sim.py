"""The CityLearn backend, offline, on the shipped dataset."""

import pytest
from conftest import needs_citylearn

from hyperbolic import district as dc

pytestmark = needs_citylearn


@pytest.fixture(scope="module")
def short_runs():
    from hyperbolic.sim import CityLearnSimulator

    out = {}
    for name, control in (("reference", False), ("baseline_actions", True)):
        sim = CityLearnSimulator(control=control)
        state = sim.start(24)
        states, outcomes = [state], []
        while state is not None:
            acts = None if not control else {b: dict(v) for b, v in state["baseline"].items()}
            outcome, state = sim.step(acts)
            outcomes.append(outcome)
            if state is not None:
                states.append(state)
        out[name] = {"states": states, "outcomes": outcomes, "kpis": sim.kpis()}
    return out


def test_dataset_is_shipped_and_offline():
    assert dc.schema_path().exists()
    for b in ("Building_1", "Building_2", "Building_3"):
        assert (dc.dataset_dir() / f"{b}.csv").exists() and (dc.dataset_dir() / f"{b}.pth").exists()


def test_state_shape(short_runs):
    s = short_runs["baseline_actions"]["states"][0]
    assert set(s["buildings"]) == {"Building_1", "Building_2", "Building_3"}
    assert len(s["shared"]["price_forecast"]) == 4 and len(s["shared"]["outdoor_c_forecast"]) == 3
    for b, st in s["buildings"].items():
        assert 0.0 <= st["battery_soc"] <= 1.0
        assert st["solar_kwh"] >= 0.0
        assert s["bounds"][b] == {"cooling": [0.0, 1.0], "dhw": [-1.0, 1.0], "battery": [-1.0, 1.0]}
        assert s["baseline"][b]["dhw"] == 0.0 and s["baseline"][b]["battery"] == 0.0
        assert 0.0 <= s["baseline"][b]["cooling"] <= 1.0


def test_episode_length(short_runs):
    assert len(short_runs["reference"]["outcomes"]) == 24


def test_baseline_actions_reproduce_the_no_control_reference(short_runs):
    """The fallback action is the reference: same KPIs as CityLearn's no-control run."""
    ref = {k["cost_function"]: k["value"] for k in short_runs["reference"]["kpis"] if k["level"] == "district"}
    act = {k["cost_function"]: k["value"] for k in short_runs["baseline_actions"]["kpis"] if k["level"] == "district"}
    assert ref["cost_total"] == pytest.approx(1.0)
    for key in ("cost_total", "carbon_emissions_total", "electricity_consumption_total", "discomfort_proportion"):
        assert act[key] == pytest.approx(ref[key], abs=1e-4), key


def test_kpis_come_from_citylearn_evaluate(short_runs):
    kpis = short_runs["reference"]["kpis"]
    names = {k["cost_function"] for k in kpis if k["level"] == "district"}
    assert {"cost_total", "carbon_emissions_total", "discomfort_proportion"} <= names
    assert {k["level"] for k in kpis} == {"district", "building"}


def test_actions_are_applied_in_citylearn_order():
    from hyperbolic.sim import CityLearnSimulator

    sim = CityLearnSimulator(control=True)
    state = sim.start(4)
    acts = {b: {"cooling": v["cooling"], "dhw": 0.0, "battery": 0.0} for b, v in state["baseline"].items()}
    acts["Building_2"]["battery"] = 0.5
    sim.step(acts)
    socs = {b.name: float(b.electrical_storage.soc[0]) for b in sim.env.buildings}
    assert socs["Building_2"] > socs["Building_1"]
    assert sim._vector(acts)[3:6] == [0.0, 0.5, acts["Building_2"]["cooling"]]
