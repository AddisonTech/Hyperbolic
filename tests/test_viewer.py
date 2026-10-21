"""Viewer data builder: same replay files in, same bytes out, every time."""

import json
import subprocess
import sys
from pathlib import Path

from conftest import FIXTURES

from hyperbolic.viewer import build_viewer_data, dumps, headline, write_viewer_data


def test_builder_is_deterministic(fixture_runs, tmp_path):
    pair = [fixture_runs]
    a = dumps(build_viewer_data(pair))
    b = dumps(build_viewer_data(pair))
    assert a == b
    write_viewer_data(pair, tmp_path / "v1.json")
    write_viewer_data(pair, tmp_path / "v2.json")
    assert (tmp_path / "v1.json").read_bytes() == (tmp_path / "v2.json").read_bytes()


def test_builder_matches_golden_file(fixture_runs):
    assert dumps(build_viewer_data([fixture_runs])) == (FIXTURES / "viewer_golden.json").read_text(encoding="utf-8")


def test_builder_is_deterministic_across_processes(fixture_runs, tmp_path):
    base, agent = fixture_runs
    outs = []
    for i, seed in enumerate(("0", "12345")):
        out = tmp_path / f"p{i}.json"
        code = ("import sys; from pathlib import Path; from hyperbolic.viewer import write_viewer_data; "
                "write_viewer_data([(Path(sys.argv[1]), Path(sys.argv[2]))], Path(sys.argv[3]))")
        subprocess.run([sys.executable, "-c", code, str(base), str(agent), str(out)], check=True,
                       env={"PYTHONHASHSEED": seed, "PATH": "", "PYTHONPATH": str(Path(__file__).parents[1])})
        outs.append(out.read_bytes())
    assert outs[0] == outs[1]


def test_viewer_content(fixture_runs):
    data = build_viewer_data([fixture_runs])
    s = data["scenarios"][0]
    assert data["sample"] is True and s["sample"] is True
    n = s["hours"]
    assert n == 30
    for side in ("baseline", "agent"):
        for z in ("nor", "eas", "sou", "wes", "cor"):
            assert len(s[side]["zone_temp_c"][z]) == n
        assert len(s[side]["energy_kwh"]) == n
        assert s[side]["energy_kwh"] == sorted(s[side]["energy_kwh"])  # running totals never fall
    assert len(s["agent"]["decisions"]) == n
    statuses = {d["status"] for d in s["agent"]["decisions"]}
    assert {"ok", "clamped", "fallback"} <= statuses
    assert s["agent_run"]["clamped_hours"] + s["agent_run"]["fallback_hours"] > 0
    assert s["headline"]["tone"] in ("win", "mixed", "loss")
    json.dumps(data, allow_nan=False)


def test_headline_is_plain_about_losses():
    base = {"cost_tot": 1.0, "ener_tot": 1.0, "tdis_tot": 10.0}
    win = headline(base, {"cost_tot": 0.9, "ener_tot": 0.95, "tdis_tot": 9.0})
    assert win["tone"] == "win" and "Cost down 10.0%" in win["text"]
    loss = headline(base, {"cost_tot": 0.9, "ener_tot": 0.9, "tdis_tot": 14.0})
    assert loss["tone"] == "loss" and loss["text"].startswith("The agent lost on comfort")
    flat = headline(base, {"cost_tot": 1.1, "ener_tot": 1.05, "tdis_tot": 10.0})
    assert flat["tone"] == "loss" and flat["text"].startswith("The agent lost")
