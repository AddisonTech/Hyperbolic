"""Viewer data builder: same replay files in, same bytes out, every time."""

import json
import os
import subprocess
import sys
from pathlib import Path

from conftest import FIXTURES

from hyperbolic.viewer import build_viewer_data, dumps, find_latest_pair, headline, write_viewer_data


def test_builder_is_deterministic(fixture_runs, tmp_path):
    a = dumps(build_viewer_data(fixture_runs))
    b = dumps(build_viewer_data(fixture_runs))
    assert a == b
    write_viewer_data(fixture_runs, tmp_path / "v1.json")
    write_viewer_data(fixture_runs, tmp_path / "v2.json")
    assert (tmp_path / "v1.json").read_bytes() == (tmp_path / "v2.json").read_bytes()
    assert (tmp_path / "v1.js").read_bytes() == (tmp_path / "v2.js").read_bytes()


def test_builder_matches_golden_file(fixture_runs):
    assert dumps(build_viewer_data(fixture_runs)) == (FIXTURES / "viewer_golden.json").read_text(encoding="utf-8")


def test_builder_is_deterministic_across_processes(fixture_runs, tmp_path):
    base, agent = fixture_runs
    outs = []
    for i, seed in enumerate(("0", "12345")):
        out = tmp_path / f"p{i}.json"
        code = ("import sys; from pathlib import Path; from hyperbolic.viewer import write_viewer_data; "
                "write_viewer_data((Path(sys.argv[1]), Path(sys.argv[2])), Path(sys.argv[3]))")
        # Keep the parent environment (user site packages on Windows live under APPDATA)
        # and only override the hash seed and the import path.
        env = dict(os.environ)
        env["PYTHONHASHSEED"] = seed
        env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(Path(__file__).parents[1]), env.get("PYTHONPATH")]))
        subprocess.run([sys.executable, "-c", code, str(base), str(agent), str(out)], check=True, env=env)
        outs.append(out.read_bytes())
    assert outs[0] == outs[1]


def test_viewer_content(fixture_runs):
    data = build_viewer_data(fixture_runs)
    s = data["scenarios"][0]
    assert data["sample"] is True and s["agent_sample"] is True and s["baseline_sample"] is False
    n = s["hours"]
    assert n == 36
    for side in ("baseline", "agent"):
        for b in ("Building_1", "Building_2", "Building_3"):
            for key in ("indoor_c", "battery_soc", "dhw_soc", "grid_kwh"):
                assert len(s[side]["buildings"][b][key]) == n
        assert s[side]["cost_usd"] == sorted(s[side]["cost_usd"]) or min(s[side]["cost_usd"]) < 0
        assert s[side]["discomfort_h"] == sorted(s[side]["discomfort_h"])  # running totals never fall
    assert s["baseline"]["kpi"]["cost_total"] == 1.0  # the no-control reference
    assert len(s["agent"]["decisions"]) == n and len(s["price"]) == n
    statuses = {d["status"] for d in s["agent"]["decisions"]}
    assert {"ok", "clamped", "fallback"} <= statuses
    json.dumps(data, allow_nan=False)


def test_find_latest_pair_prefers_live_agent(tmp_path, fixture_runs):
    import shutil

    base, agent = fixture_runs
    runs = tmp_path / "runs"
    shutil.copytree(base, runs / "b")
    shutil.copytree(agent, runs / "scripted")
    live = runs / "live"
    shutil.copytree(agent, live)
    m = json.loads((live / "manifest.json").read_text())
    m["supervisor"]["kind"] = "live"
    m["started_at"] = "2020-01-01T00:00:00+00:00"  # older, still preferred because it is live
    (live / "manifest.json").write_text(json.dumps(m))
    assert find_latest_pair(runs) == (runs / "b", live)


def _as_live(agent, dest):
    import shutil

    shutil.copytree(agent, dest)
    m = json.loads((dest / "manifest.json").read_text())
    m["supervisor"]["kind"] = "live"
    (dest / "manifest.json").write_text(json.dumps(m))
    return dest


def test_live_run_is_not_labeled_a_sample(tmp_path, fixture_runs):
    base, agent = fixture_runs
    live = build_viewer_data((base, _as_live(agent, tmp_path / "live")))
    assert live["sample"] is False
    assert live["scenarios"][0]["agent_sample"] is False
    assert live["scenarios"][0]["agent_run"]["supervisor"] == "live"
    scripted = build_viewer_data((base, agent))
    assert scripted["sample"] is True
    assert scripted["scenarios"][0]["agent_sample"] is True


def test_hidden_attribute_beats_component_display():
    """The sample banner is display: flex; without this rule setting hidden on it does nothing."""
    import re

    css = (Path(__file__).parents[1] / "docs" / "assets" / "style.css").read_text(encoding="utf-8")
    assert re.search(r"\[hidden\]\s*\{\s*display:\s*none\s*!important;?\s*\}", css)
    html = (Path(__file__).parents[1] / "docs" / "index.html").read_text(encoding="utf-8")
    assert 'id="sample-banner" hidden' in html  # hidden until the data says it is a sample


def test_headline_is_plain_about_losses():
    base = {"cost_total": 1.0, "carbon_emissions_total": 1.0, "discomfort_proportion": 0.17}
    win = headline(base, {"cost_total": 0.9, "carbon_emissions_total": 0.95, "discomfort_proportion": 0.16})
    assert win["tone"] == "win" and "Cost down 10.0%" in win["text"]
    loss = headline(base, {"cost_total": 0.9, "carbon_emissions_total": 0.9, "discomfort_proportion": 0.25})
    assert loss["tone"] == "loss" and loss["text"].startswith("The agent lost on comfort")
    flat = headline(base, {"cost_total": 1.1, "carbon_emissions_total": 1.05, "discomfort_proportion": 0.17})
    assert flat["tone"] == "loss" and flat["text"].startswith("The agent lost")


def test_committed_baseline_pairs_with_a_new_agent_run(tmp_path, fixture_runs):
    import shutil

    from pathlib import Path as P

    _, agent = fixture_runs
    runs = tmp_path / "runs"
    shutil.copytree(agent, runs / "agent")
    results = P(__file__).parents[1] / "results"
    pair = find_latest_pair(runs, (results,))
    assert pair == (results / "baseline", runs / "agent")
