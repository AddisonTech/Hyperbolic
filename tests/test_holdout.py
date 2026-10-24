"""The sealed holdout (0.11.0, HOLDOUT.md): Buildings 4, 5 and 6 of citylearn_challenge_2023_phase_3_1, kept out
of the month set, scored only with --holdout-final and only on files that match the seal. Nothing here runs a
controller on it; the one CityLearn test is the baseline load check."""

import json
import re
import shutil
from pathlib import Path

import pytest
from conftest import needs_citylearn

from hyperbolic import cli
from hyperbolic import months as mo
from hyperbolic.viewer import write_viewer_data

ROOT = Path(__file__).resolve().parents[1]


def test_the_holdout_is_three_months_of_buildings_4_to_6_and_never_in_the_month_set():
    assert [m.key for m in mo.months()] == ["phase2", "tuning-06", "tuning-07", "tuning-08"]
    hs = mo.holdout_months()
    assert [m.key for m in hs] == ["holdout-06", "holdout-07", "holdout-08"]
    assert [mo.hours(m) for m in hs] == [719, 743, 743]
    assert all(m.holdout and m.buildings == ("Building_4", "Building_5", "Building_6") for m in hs)
    assert hs[1].dataset == "citylearn_challenge_2023_phase_3_1_buildings_4_5_6_month_07"
    assert mo.month("holdout-08") == hs[2] and mo.is_holdout("holdout-06") and mo.is_holdout(hs[0].dataset)
    assert not any(mo.is_holdout(m.key) or mo.is_holdout(m.dataset) for m in mo.months())


def test_a_holdout_month_is_written_with_only_its_own_buildings(tmp_path):
    schema = mo.month_schema(mo.month("holdout-07"), tmp_path)
    data = json.loads(schema.read_text(encoding="utf-8"))
    assert sorted(data["buildings"]) == ["Building_4", "Building_5", "Building_6"]
    assert data["simulation_start_time_step"] == 0 and data["simulation_end_time_step"] == 743
    assert sorted(p.name for p in schema.parent.iterdir()) == [
        "Building_4.csv", "Building_4.pth", "Building_5.csv", "Building_5.pth", "Building_6.csv", "Building_6.pth",
        "carbon_intensity.csv", "pricing.csv", "schema.json", "weather.csv"]
    lines = (schema.parent / "Building_5.csv").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 745


def test_the_seal_matches_the_files_and_holdout_md():
    mo.check_sealed()
    text = (ROOT / "HOLDOUT.md").read_text(encoding="utf-8")
    table = dict(re.findall(r"^\| (\S+\.(?:csv|pth|json)) \| ([0-9a-f]{64}) \|$", text, re.M))
    assert table == mo.HOLDOUT_SHA256


def test_a_changed_or_extra_holdout_file_breaks_the_seal(tmp_path):
    copy = tmp_path / "h"
    shutil.copytree(mo.HOLDOUT_DATASET, copy)
    mo.check_sealed(copy)
    (copy / "notes.txt").write_text("x", encoding="utf-8")
    with pytest.raises(mo.HoldoutSealed, match="notes.txt"):
        mo.check_sealed(copy)
    (copy / "notes.txt").unlink()
    p = copy / "pricing.csv"
    p.write_bytes(p.read_bytes().replace(b"0.", b"1.", 1))
    with pytest.raises(mo.HoldoutSealed, match="pricing.csv"):
        mo.check_sealed(copy)


def test_guard_refuses_the_holdout_unless_final():
    mo.guard(["phase2", "tuning-07", mo.month("tuning-06").dataset])
    with pytest.raises(mo.HoldoutSealed, match="--holdout-final"):
        mo.guard(["phase2", "holdout-06"])
    with pytest.raises(mo.HoldoutSealed):
        mo.guard([mo.month("holdout-08").dataset])
    mo.guard(["holdout-06"], final=True)


def test_run_month_refuses_a_holdout_month_before_simulating(tmp_path):
    with pytest.raises(mo.HoldoutSealed):
        mo.run_month(("baseline", "holdout-06", str(tmp_path)))
    assert not any(tmp_path.iterdir())


def _fake_run(path: Path, dataset: str, mode: str = "agent") -> Path:
    path.mkdir()
    (path / "manifest.json").write_text(json.dumps({"dataset": dataset, "mode": mode,
                                                    "supervisor": {"kind": "live", "model_key": "haiku",
                                                                   "prompt_version": 9}}), encoding="utf-8")
    (path / "result.json").write_text(json.dumps({"steps": 719, "complete": True, "clamped_steps": 0,
                                                  "fallback_steps": 0, "cost_usd": 0.4,
                                                  "district_kpis": {"cost_total": 0.9}}), encoding="utf-8")
    return path


def test_recorded_run_on_the_holdout_needs_final(tmp_path):
    run = _fake_run(tmp_path / "r", mo.month("holdout-07").dataset)
    with pytest.raises(mo.HoldoutSealed):
        mo.recorded_run(run)
    assert mo.recorded_run(run, final=True)["month"] == "holdout-07"


def test_months_cli_refuses_the_holdout_without_the_flag_and_mixed_with_the_month_set(tmp_path, capsys):
    assert cli.main(["months", "--months", "holdout-06", "--controllers", "baseline"]) == 2
    assert "sealed holdout" in capsys.readouterr().err
    assert cli.main(["months", "--holdout-final", "--controllers", "baseline"]) == 2
    assert cli.main(["months", "--holdout-final", "--months", "holdout-06", "phase2"]) == 2
    run = _fake_run(tmp_path / "r", mo.month("holdout-06").dataset)
    assert cli.main(["months", "--months", "phase2", "--controllers", "baseline", "--run", str(run)]) == 2
    p = cli.build_parser()
    assert p.parse_args(["months", "--holdout-final", "--months", "holdout-07"]).holdout_final
    assert p.parse_args(["compare", "--holdout-final"]).holdout_final
    assert not p.parse_args(["months"]).holdout_final


def test_compare_refuses_a_holdout_pair_and_writes_nothing(tmp_path, capsys):
    ds = mo.month("holdout-06").dataset
    base, agent = _fake_run(tmp_path / "b", ds, "baseline"), _fake_run(tmp_path / "a", ds)
    out = tmp_path / "data" / "viewer.json"
    with pytest.raises(mo.HoldoutSealed):
        write_viewer_data((base, agent), out)
    assert cli.main(["compare", "--pair", str(base), str(agent), "--out", str(out)]) == 2
    assert "sealed holdout" in capsys.readouterr().err and not out.exists()


def test_run_on_the_holdout_records_but_prints_no_kpis(tmp_path, monkeypatch, capsys):
    class Sim:
        def check_hours(self, hours):
            pass

    res = {"steps": 719, "complete": True, "calls": 719, "fallback_steps": 0, "clamped_steps": 3, "cost_usd": 0.41,
           "budget_stopped": False, "district_kpis": {"cost_total": 0.9123, "carbon_emissions_total": 0.95,
                                                      "discomfort_proportion": 0.05}}
    monkeypatch.setattr(cli, "_sim", lambda control, schema=None: Sim())
    monkeypatch.setattr(cli, "run_session", lambda *a, **k: res)
    assert cli.main(["run", "--scripted", "--month", "holdout-06", "--runs-dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "KPIs are not shown" in out and "0.9123" not in out and "cost_total" not in out


@needs_citylearn
def test_the_baseline_loads_and_runs_on_the_holdout(tmp_path):
    """The load check HOLDOUT.md describes: the no-control reference on holdout June, Buildings 4 to 6 only."""
    assert cli.main(["baseline", "--month", "holdout-06", "--hours", "24", "--runs-dir", str(tmp_path)]) == 0
    (run,) = tmp_path.iterdir()
    m = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    assert m["dataset"] == mo.month("holdout-06").dataset and tuple(m["buildings"]) == mo.HOLDOUT_BUILDINGS
    assert m["episode_hours"] == 719
