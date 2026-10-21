"""End to end through the command line, offline on CityLearn."""

import json

from conftest import needs_citylearn

from hyperbolic.cli import main


@needs_citylearn
def test_baseline_run_compare_replay(tmp_path, capsys):
    runs = tmp_path / "runs"
    assert main(["baseline", "--hours", "8", "--runs-dir", str(runs)]) == 0
    assert main(["run", "--scripted", "--hours", "8", "--runs-dir", str(runs)]) == 0
    out = tmp_path / "viewer.json"
    assert main(["compare", "--runs-dir", str(runs), "--out", str(out)]) == 0
    data = json.loads(out.read_text())
    assert data["scenarios"][0]["hours"] == 8
    agent_dir = next(p for p in runs.iterdir() if "_agent_" in p.name)
    assert main(["replay", str(agent_dir)]) == 0
    assert "deterministic: yes" in capsys.readouterr().out


def test_live_run_without_key_fails_cleanly(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("HYPERBOLIC_ANTHROPIC_KEY", raising=False)
    monkeypatch.delenv("TRIAGE_ANTHROPIC_KEY", raising=False)
    assert main(["run", "--hours", "1", "--runs-dir", str(tmp_path)]) == 2
    assert "HYPERBOLIC_ANTHROPIC_KEY" in capsys.readouterr().err
    assert not any(tmp_path.iterdir())


def test_compare_with_no_runs(tmp_path):
    assert main(["compare", "--runs-dir", str(tmp_path), "--out", str(tmp_path / "v.json")]) == 1


def test_replay_of_committed_baseline(capsys):
    from pathlib import Path

    run = Path(__file__).parents[1] / "results" / "baseline"
    assert main(["replay", str(run)]) == 0
    assert "719/719" in capsys.readouterr().out
