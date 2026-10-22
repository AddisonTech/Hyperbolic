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


@needs_citylearn
def test_compare_against_the_rule_based_controller(tmp_path, capsys):
    runs = tmp_path / "runs"
    assert main(["baseline", "--hours", "8", "--runs-dir", str(runs)]) == 0
    assert main(["run", "--scripted", "--prompt-version", "4", "--hours", "8", "--runs-dir", str(runs)]) == 0
    assert main(["run", "--scripted", "--hours", "8", "--runs-dir", str(tmp_path / "rule")]) == 0
    base = next(p for p in runs.iterdir() if "_baseline_" in p.name)
    agent = next(p for p in runs.iterdir() if "_agent_" in p.name)
    rule = next((tmp_path / "rule").iterdir())
    out = tmp_path / "viewer.json"
    capsys.readouterr()
    assert main(["compare", "--pair", str(base), str(agent), "--against", str(rule), "--out", str(out)]) == 0
    text = capsys.readouterr().out
    header = next(line for line in text.splitlines() if "CityLearn KPI" in line)
    assert header.split()[-3:] == ["baseline", "agent", "rule-based"]
    cost = next(line for line in text.splitlines() if line.strip().startswith("cost_total"))
    assert all(float(v) > 0 for v in cost.split()[-3:])  # baseline, agent and rule-based values
    # The viewer data still holds only the baseline and the agent.
    assert json.loads(out.read_text())["scenarios"][0]["agent"]["run"] == agent.name
    # A run of another length is refused.
    assert main(["run", "--scripted", "--hours", "4", "--runs-dir", str(tmp_path / "short")]) == 0
    short = next((tmp_path / "short").iterdir())
    assert main(["compare", "--pair", str(base), str(agent), "--against", str(short), "--out", str(out)]) == 1
