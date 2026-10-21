"""End to end through the command line, offline."""

import json

from hyperbolic.cli import main


def test_mock_baseline_run_compare_replay(tmp_path, capsys):
    runs = tmp_path / "runs"
    common = ["--mock", "--scenario", "typical_heat_day", "--hours", "8", "--runs-dir", str(runs)]
    assert main(["baseline", *common]) == 0
    assert main(["run", *common]) == 0
    out = tmp_path / "viewer.json"
    assert main(["compare", "--mock", "--runs-dir", str(runs), "--out", str(out)]) == 0
    data = json.loads(out.read_text())
    assert data["scenarios"][0]["id"] == "typical_heat_day"
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
