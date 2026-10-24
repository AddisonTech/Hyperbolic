"""The month set and its compare report (0.10.0): the phase 2 month plus every local tuning month, each
its own episode, and runs recorded on any of them."""

import csv
import json

import pytest
from conftest import needs_citylearn
from fakes import FakeDistrict

from hyperbolic import district as dc
from hyperbolic import months as mo
from hyperbolic.cli import build_parser, main
from hyperbolic.envelope import Envelope, EnvelopeConfig
from hyperbolic.model import Budget, ScriptedSupervisor
from hyperbolic.runner import AgentController, RunWriter, new_run_dir, run_session


def test_the_month_set_is_phase_2_and_the_three_tuning_months():
    ms = mo.months()
    assert [m.key for m in ms] == ["phase2", "tuning-06", "tuning-07", "tuning-08"]
    assert ms[0].dataset == dc.DATASET and ms[0].rows is None
    assert [mo.hours(m) for m in ms] == [719, 719, 743, 743]
    assert ms[2].dataset == "citylearn_challenge_2023_phase_2_online_evaluation_1_month_07"
    with pytest.raises(ValueError):
        mo.month("tuning-09")


def test_a_tuning_month_is_written_as_its_own_dataset(tmp_path):
    m = mo.month("tuning-07")
    schema = mo.month_schema(m, tmp_path)
    data = json.loads(schema.read_text(encoding="utf-8"))
    assert data["simulation_start_time_step"] == 0 and data["simulation_end_time_step"] == 743
    with (schema.parent / "Building_1.csv").open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 744 and {r["month"] for r in rows} == {"7"}
    assert sorted(p.name for p in schema.parent.glob("*.pth")) == ["Building_1.pth", "Building_2.pth", "Building_3.pth"]
    assert mo.month_schema(mo.month("phase2"), tmp_path) == dc.schema_path()


def _row(ctl, month, cost, hot=0.01):
    return {"controller": ctl, "month": month, "hours": 719, "clamped": 2,
            "kpis": {k: 1.0 for k in mo.REPORT_KPIS} | {"cost_total": cost, "discomfort_hot_proportion": hot}}


def test_report_means_every_month_and_leaves_a_partial_controller_without_one():
    rows = [_row("a", k, c) for k, c in (("phase2", 0.9), ("tuning-06", 0.8), ("tuning-07", 0.7), ("tuning-08", 0.6))]
    rows.append(_row("live", "phase2", 0.95))
    rep = mo.report(rows)
    assert rep["a"]["mean"]["kpis"]["cost_total"] == pytest.approx(0.75) and rep["a"]["mean"]["months"] == 4
    assert "mean" not in rep["live"]
    text = mo.table(rep)
    assert text.splitlines()[0].split()[-5:] == ["phase2", "tuning-06", "tuning-07", "tuning-08", "mean"]
    assert "  a " in text and "0.7500" in text and "0.9500" in text and chr(0x2014) not in text


def test_report_shows_only_the_months_that_ran():
    rep = mo.report([_row("a", "phase2", 0.9), _row("a", "tuning-07", 0.7)])
    assert mo.table(rep).splitlines()[0].split()[-3:] == ["phase2", "tuning-07", "mean"]


def test_run_session_records_the_month(tmp_path):
    run = new_run_dir(tmp_path, "agent", "fake", "some_month")
    assert run.name.startswith("some_month_agent_fake_")
    ctl = AgentController(ScriptedSupervisor(), Envelope(EnvelopeConfig()), Budget(2.0), prompt_version=8)
    run_session(FakeDistrict(), ctl, RunWriter(run), hours=24, log=lambda *_: None, dataset="some_month")
    m = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    assert m["dataset"] == "some_month" and m["episode_hours"] == dc.EPISODE_HOURS  # the fake has no month length


def test_recorded_run_is_placed_at_its_month_and_marked_partial(tmp_path):
    run = tmp_path / "r"
    run.mkdir()
    (run / "manifest.json").write_text(json.dumps({"dataset": mo.month("tuning-06").dataset, "mode": "agent",
                                                   "supervisor": {"kind": "live", "model_key": "haiku",
                                                                  "prompt_version": 8}}), encoding="utf-8")
    (run / "result.json").write_text(json.dumps({"steps": 24, "complete": False, "clamped_steps": 0,
                                                 "fallback_steps": 0, "cost_usd": 0.01,
                                                 "district_kpis": {"cost_total": 0.97}}), encoding="utf-8")
    got = mo.recorded_run(run)
    assert got["month"] == "tuning-06" and got["controller"] == "haiku v8 (24 h)" and got["kpis"]["cost_total"] == 0.97
    (run / "manifest.json").write_text(json.dumps({"dataset": "elsewhere"}), encoding="utf-8")
    with pytest.raises(ValueError):
        mo.recorded_run(run)


def test_cli_takes_a_month_for_baseline_and_run_and_has_the_months_report():
    p = build_parser()
    assert p.parse_args(["run", "--month", "tuning-08"]).month == "tuning-08"
    assert p.parse_args(["baseline"]).month == "phase2"
    a = p.parse_args(["months", "--controllers", "rule", "v8", "--months", "phase2"])
    assert a.controllers == ["rule", "v8"] and a.months == ["phase2"]
    assert p.parse_args(["months"]).controllers == ["baseline", "rule", "v7", "v8", "v9"]
    with pytest.raises(SystemExit):
        p.parse_args(["run", "--month", "march"])


@needs_citylearn
def test_scripted_run_on_a_tuning_month_records_its_month_and_replays(tmp_path):
    from hyperbolic.runner import replay_run

    assert main(["run", "--scripted", "--prompt-version", "8", "--month", "tuning-07", "--hours", "24",
                 "--runs-dir", str(tmp_path)]) == 0
    (run,) = tmp_path.iterdir()
    m = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    assert m["dataset"] == mo.month("tuning-07").dataset and m["episode_hours"] == 743
    assert m["simulator"]["month"] == "tuning-07" and m["supervisor"]["prompt_version"] == 8
    assert run.name.startswith(mo.month("tuning-07").dataset)
    assert replay_run(run).deterministic


@needs_citylearn
def test_run_month_reproduces_the_rule_based_tuning_month(tmp_path):
    """The frozen 0.4.0 rule-based controller on tuning June, as scripts/tune_strategy.py has always run it."""
    got = mo.run_month(("rule", "tuning-06", str(tmp_path)))
    assert got["hours"] == 719 and got["controller"] == "rule" and got["month"] == "tuning-06"
    assert got["kpis"]["cost_total"] == pytest.approx(0.9506, abs=5e-5)
    assert got["kpis"]["discomfort_proportion"] == pytest.approx(0.1128, abs=5e-5)
