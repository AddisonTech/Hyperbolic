"""Viewer data builder: same replay files in, same bytes out, every time."""

import json
import os
import re
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


def test_viewer_version_follows_the_package():
    """The footer used to hard-code 0.2.0; it now reads assets/version.js, which must match."""
    import re

    import hyperbolic
    from hyperbolic.viewer import version_js

    docs = Path(__file__).parents[1] / "docs"
    js = (docs / "assets" / "version.js").read_text(encoding="utf-8")
    assert js == version_js(hyperbolic.__version__)
    html = (docs / "index.html").read_text(encoding="utf-8")
    assert '<script src="assets/version.js"></script>' in html
    assert html.index("assets/version.js") < html.index("assets/app.js")
    # No release number is written into the page itself.
    assert not re.search(r"Hyperbolic \d+\.\d+\.\d+", html)
    assert "HYPERBOLIC_VERSION" in (docs / "assets" / "app.js").read_text(encoding="utf-8")


def test_viewer_footer_credit():
    html = (Path(__file__).parents[1] / "docs" / "index.html").read_text(encoding="utf-8")
    for href, text in (("https://addisontech.github.io", "Addison Smith"),
                       ("https://github.com/AddisonTech/Hyperbolic", "GitHub"), ("https://sixophor.com", "Sixophor")):
        assert f'<a href="{href}">{text}</a>' in html
    assert "Built by" in html


def test_scenario_stream_rebuilds_the_replay_scenario(fixture_runs):
    """Live mode streams hours one at a time; put together they must equal build_scenario."""
    from hyperbolic.runner import load_jsonl
    from hyperbolic.viewer import ScenarioStream, build_scenario

    base, agent = fixture_runs
    names = json.loads((agent / "manifest.json").read_text())["buildings"]
    stream = ScenarioStream(names)
    rows = [stream.add(b, a) for b, a in zip(load_jsonl(base / "steps.jsonl"), load_jsonl(agent / "steps.jsonl"))]
    sc = build_scenario(base, agent)
    for key in ("hour_of_day", "day", "price", "carbon", "outdoor_c"):
        assert [r[key] for r in rows] == sc[key]
    for b in names:
        assert [r["setpoint_c"][b] for r in rows] == sc["setpoint_c"][b]
        assert [r["occupied"][b] for r in rows] == sc["occupied"][b]
    for side in ("baseline", "agent"):
        for f in ("district_grid_kwh", "cost_usd", "emission_kg", "discomfort_h"):
            assert [r[side][f] for r in rows] == sc[side][f]
        for b in names:
            for f in ("indoor_c", "battery_soc", "dhw_soc", "grid_kwh"):
                assert [r[side]["buildings"][b][f] for r in rows] == sc[side]["buildings"][b][f]
    assert [r["agent"]["decision"] for r in rows] == sc["agent"]["decisions"]
    for b in names:
        for d in ("cooling", "dhw", "battery"):
            assert [r["agent"]["actions"][b][d] for r in rows] == sc["agent"]["actions"][b][d]
    # Running KPI estimates: the baseline scores 1 against itself.
    assert rows[-1]["kpi"]["baseline"]["cost_total"] == 1.0


def test_page_explains_how_it_works_and_how_to_run_it():
    html = (Path(__file__).parents[1] / "docs" / "index.html").read_text(encoding="utf-8")
    assert "Replace the sample with a live agent run" not in html and 'id="howto"' not in html
    steps = re.findall(r'<li class="how-step">.*?<strong>(.*?)</strong>', html)
    assert steps == ["The agent decides", "The safety envelope checks", "CityLearn simulates", "CityLearn scores"]
    run = html[html.index('<section id="run"'):html.index("</section>", html.index('<section id="run"'))]
    for cmd in ("pip install --no-deps CityLearn==3.0.2", 'pip install -e ".[dev]"', "-m hyperbolic serve",
                "-m hyperbolic run --scripted", "-m hyperbolic compare"):
        assert cmd in run, cmd
    assert '<a href="#run">Run it yourself</a>' in html  # the sample banner points at it
    assert chr(0x2014) not in html


def test_viewer_shows_trims_the_model_ended_early(fixture_runs, tmp_path):
    import shutil

    from hyperbolic.viewer import build_scenario

    base, agent = fixture_runs
    run = tmp_path / "agent"
    shutil.copytree(agent, run)
    m = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    m["envelope"]["trim_hold"] = True
    (run / "manifest.json").write_text(json.dumps(m), encoding="utf-8")
    lines = (run / "steps.jsonl").read_text(encoding="utf-8").splitlines()
    rec = json.loads(lines[3])
    rec["decision"]["holds"] = [
        {"building": "Building_2", "action": "end_early", "depth_before": 0.06, "depth_after": 0.0,
         "reason": "Outage ahead, keep the room cool"},
        {"building": "Building_1", "action": "hold", "depth_before": 0.05, "depth_after": 0.05, "reason": "held"}]
    lines[3] = json.dumps(rec)
    (run / "steps.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    s = build_scenario(base, run)
    assert s["agent"]["decisions"][3]["trim_ends"] == [{"building": "Building_2",
                                                       "reason": "Outage ahead, keep the room cool"}]
    assert all("trim_ends" not in d for i, d in enumerate(s["agent"]["decisions"]) if i != 3)
    assert s["agent_run"]["trim_ends_early"] == 1
    assert "trim_ends_early" not in build_scenario(base, agent)["agent_run"]  # older runs: unchanged
    root = Path(__file__).parents[1]
    assert "trim ended early" in (root / "docs" / "assets" / "app.js").read_text(encoding="utf-8")
    assert "trim ended early" in (root / "hyperbolic" / "live_assets" / "live.js").read_text(encoding="utf-8")
