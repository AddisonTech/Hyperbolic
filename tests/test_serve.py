"""Live mode: `hyperbolic serve`, driven over HTTP with fake models (no API key, no network)."""

from __future__ import annotations

import http.client
import json
import shutil
import threading
import time
from pathlib import Path

import pytest
from conftest import needs_citylearn

from hyperbolic.cli import main
from hyperbolic.live import make_server
from hyperbolic.model import ScriptedSupervisor
from hyperbolic.runner import load_jsonl, replay_run
from hyperbolic.viewer import build_scenario, build_viewer_data

ROOT = Path(__file__).parents[1]
SECRET = "sk-test-NEVER-SHOW-THIS-0123456789abcdef"


class FakeModel(ScriptedSupervisor):
    """The rule-based replies, dressed as a paid model: it reports tokens so the cost
    meter and the budget move, and can be slowed down to make pause and stop testable."""

    kind = "fake"

    def __init__(self, model_key="haiku", tokens=(3000, 250), delay=0.0):
        super().__init__(model_key, tokens=tokens)
        self.delay = delay

    def call(self, step, request):
        if self.delay:
            time.sleep(self.delay)
        return super().call(step, request)


class Client:
    def __init__(self, port):
        self.port = port
        self.seen: list[str] = []  # every response body, to check the key never leaks

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=60)
        h = {"Host": f"127.0.0.1:{self.port}"}
        if body is not None:
            h.update({"Content-Type": "application/json", "X-Hyperbolic-Live": "1"})
        h.update(headers or {})
        conn.request(method, path, body=None if body is None else json.dumps(body), headers=h)
        resp = conn.getresponse()
        text = resp.read().decode()
        self.seen.append(text)
        conn.close()
        return resp.status, text

    def get(self, path, **kw):
        code, text = self.request("GET", path, **kw)
        return code, json.loads(text) if text.startswith(("{", "[")) else text

    def post(self, path, body=None, **kw):
        code, text = self.request("POST", path, body={} if body is None else body, **kw)
        return code, json.loads(text)

    def events(self, since=0, until=("done", "failed"), stop_after=None):
        """Read the event stream; return [(kind, data)] up to and including a final event."""
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=120)
        conn.request("GET", f"/api/events?since={since}", headers={"Host": f"127.0.0.1:{self.port}"})
        resp = conn.getresponse()
        out, kind = [], None
        try:
            while True:
                line = resp.fp.readline().decode()
                if not line:
                    break
                self.seen.append(line)
                line = line.rstrip("\n")
                if line.startswith("event: "):
                    kind = line[7:]
                elif line.startswith("data: "):
                    out.append((kind, json.loads(line[6:])))
                    if kind in until or (stop_after and stop_after(out)):
                        break
        finally:
            conn.close()
        return out


@pytest.fixture
def live(tmp_path):
    """Start a server on a free port with a copy of docs/, fake models and a fake environment."""
    servers = []

    def start(env=None, model=None):
        docs = tmp_path / "docs"
        if not docs.exists():
            shutil.copytree(ROOT / "docs", docs)
        factory = None if model is None else (lambda controller: model() if controller in ("haiku", "sonnet")
                                              else ScriptedSupervisor("haiku"))
        kwargs = {} if factory is None else {"supervisor_factory": factory}
        srv = make_server(port=0, runs_dir=tmp_path / "runs", docs=docs, env={} if env is None else env,
                          baseline_dir=ROOT / "results" / "baseline", **kwargs)
        threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True).start()
        servers.append(srv)
        return srv, Client(srv.port)

    yield start
    for srv in servers:
        srv.hub.shutdown(wait=60)
        srv.shutdown()
        srv.server_close()


# -- no CityLearn needed ------------------------------------------------------------


def test_binds_127_0_0_1_only(live):
    with pytest.raises(ValueError):
        make_server(port=0, host="0.0.0.0", docs=ROOT / "docs")
    with pytest.raises(ValueError):
        make_server(port=0, host="192.168.1.10", docs=ROOT / "docs")
    srv, c = live()
    assert srv.server_address[0] == "127.0.0.1"
    assert main(["serve", "--host", "0.0.0.0", "--no-browser"]) == 2


def test_refuses_other_hosts_and_cross_site_posts(live):
    srv, c = live()
    assert c.request("GET", "/api/config", headers={"Host": "evil.example"})[0] == 403
    assert c.request("GET", "/", headers={"Host": f"attacker.example:{srv.port}"})[0] == 403
    code, _ = c.request("POST", "/api/start", body={"hours": 24, "controller": "rule"},
                        headers={"X-Hyperbolic-Live": "0"})
    assert code == 403
    code, _ = c.post("/api/start", {"hours": 24, "controller": "rule"}, headers={"Origin": "http://evil.example"})
    assert code == 403
    assert c.request("GET", "/assets/../../pyproject.toml")[0] == 404
    assert c.request("GET", "/live/../live.py")[0] == 404
    assert srv.hub.run is None  # nothing started


def test_live_page_only_when_served(live):
    srv, c = live()
    code, html = c.get("/")
    assert code == 200 and "window.HYPERBOLIC_LIVE" in html and 'src="live/live.js"' in html
    assert c.get("/live/live.js")[0] == 200 and c.get("/assets/app.js")[0] == 200
    published = (ROOT / "docs" / "index.html").read_text(encoding="utf-8")
    assert "live/live.js" not in published and "HYPERBOLIC_LIVE" not in published
    assert not (ROOT / "docs" / "live").exists()


def test_claude_options_disabled_without_a_key(live):
    srv, c = live(env={})
    code, cfg = c.get("/api/config")
    by_id = {x["id"]: x for x in cfg["controllers"]}
    assert not by_id["haiku"]["available"] and not by_id["sonnet"]["available"]
    assert by_id["rule"]["available"] and by_id["baseline"]["available"]
    assert "TRIAGE_ANTHROPIC_KEY" in by_id["haiku"]["note"]
    assert cfg["key"] == {"present": False, "source": None, "variables": ["HYPERBOLIC_ANTHROPIC_KEY", "TRIAGE_ANTHROPIC_KEY"]}
    code, err = c.post("/api/start", {"hours": 24, "controller": "haiku", "budget_usd": 2})
    assert code == 400 and "TRIAGE_ANTHROPIC_KEY" in err["error"]


def test_start_validates_its_input(live):
    srv, c = live(env={})
    for body in ({"hours": 0, "controller": "rule"}, {"hours": 720, "controller": "rule"},
                 {"hours": 168, "controller": "rule"}, {"hours": "24", "controller": "rule"},
                 {"hours": 24, "controller": "nope"}, {"hours": 24, "controller": "rule", "budget_usd": 0},
                 {"hours": 24, "controller": "rule", "budget_usd": 1000}):
        assert c.post("/api/start", body)[0] == 400, body
    assert c.post("/api/pause")[0] == 409 and c.post("/api/stop")[0] == 409 and c.post("/api/publish")[0] == 409


def test_estimate_comes_from_recorded_runs(live):
    srv, c = live()
    est = c.get("/api/config")[1]["estimates"]
    published = json.loads((ROOT / "docs" / "data" / "viewer.json").read_text(encoding="utf-8"))["scenarios"][0]
    expected = published["agent_run"]["cost_usd"] / published["hours"]
    assert est["haiku"]["per_hour"] == pytest.approx(expected) and "recorded" in est["haiku"]["source"]
    assert est["sonnet"]["per_hour"] == pytest.approx(expected * 20)
    assert est["rule"]["per_hour"] == 0 and est["baseline"]["per_hour"] == 0


# -- full runs on CityLearn ------------------------------------------------------------


@needs_citylearn
def test_full_live_run_streams_records_replays_and_publishes(live, tmp_path):
    srv, c = live(env={"TRIAGE_ANTHROPIC_KEY": SECRET}, model=FakeModel)
    cfg = c.get("/api/config")[1]
    assert cfg["key"]["present"] and all(x["available"] for x in cfg["controllers"])
    code, started = c.post("/api/start", {"hours": 24, "controller": "haiku", "budget_usd": 2})
    assert code == 200
    assert c.post("/api/start", {"hours": 24, "controller": "rule"})[0] == 409  # one run at a time
    events = c.events(started["first_event"])
    kinds = [k for k, _ in events]
    assert kinds[0] == "status" and "start" in kinds and kinds[-1] == "done" and kinds.count("hour") == 24
    hours = [d for k, d in events if k == "hour"]
    first = hours[0]
    for key in ("hour_of_day", "price", "carbon", "baseline", "agent", "kpi", "headline", "peak", "spend"):
        assert key in first
    assert set(first["agent"]["decision"]) == {"status", "reason", "fallback", "clamps"}
    assert first["peak"]["drawn_kwh"] is not None and "target_kwh" in first["peak"]
    spend = [h["spend"]["usd"] for h in hours]
    assert spend == sorted(spend) and spend[-1] > 0 and hours[-1]["spend"]["calls"] == 24
    done = events[-1][1]
    assert done["complete"] and not done["stopped"] and done["steps"] == 24
    assert {r["id"] for r in done["kpis"]} >= {"cost_total", "carbon_emissions_total", "discomfort_proportion"}

    # Recorded in the same format as `hyperbolic run`, and replays exactly.
    agent_dir, base_dir = Path(done["agent_run"]), Path(done["baseline_run"])
    manifest = json.loads((agent_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["mode"] == "agent" and manifest["simulator"]["source"] == "serve"
    rep = replay_run(agent_dir)
    assert rep.deterministic and rep.identical_steps == 24 and rep.api_calls == 0

    # The streamed hours rebuild exactly the scenario the replay viewer builds from the files.
    scen = build_scenario(base_dir, agent_dir)
    assert [h["price"] for h in hours] == scen["price"]
    assert [h["agent"]["district_grid_kwh"] for h in hours] == scen["agent"]["district_grid_kwh"]
    assert [h["agent"]["cost_usd"] for h in hours] == scen["agent"]["cost_usd"]
    assert [h["baseline"]["emission_kg"] for h in hours] == scen["baseline"]["emission_kg"]
    assert [h["agent"]["decision"] for h in hours] == scen["agent"]["decisions"]
    b = scen["setpoint_c"]
    assert {k: [h["setpoint_c"][k] for h in hours] for k in b} == b

    code, full = c.get("/api/viewer")
    assert code == 200 and full == json.loads(json.dumps(build_viewer_data((base_dir, agent_dir))))
    code, pub = c.post("/api/publish")
    assert code == 200 and "Nothing was committed or pushed" in pub["note"]
    written = json.loads((tmp_path / "docs" / "data" / "viewer.json").read_text(encoding="utf-8"))
    assert written["scenarios"][0]["agent"]["run"] == agent_dir.name

    # The key never reaches a response, the stream or a file.
    c.get("/api/state")
    assert not any(SECRET in text for text in c.seen)
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert SECRET.encode() not in path.read_bytes(), path


@needs_citylearn
def test_pause_resume_and_stop_save_a_partial_run(live):
    srv, c = live(env={"TRIAGE_ANTHROPIC_KEY": SECRET}, model=lambda: FakeModel(delay=0.08))
    code, started = c.post("/api/start", {"hours": 47, "controller": "haiku", "budget_usd": 2})
    assert code == 200
    c.events(started["first_event"], stop_after=lambda ev: sum(k == "hour" for k, _ in ev) >= 4)
    assert c.post("/api/pause")[0] == 200
    time.sleep(0.4)
    paused_at = c.get("/api/state")[1]["events"]
    time.sleep(0.8)
    state = c.get("/api/state")[1]
    assert state["state"] == "paused" and state["events"] == paused_at  # nothing moves while paused
    assert c.post("/api/start", {"hours": 24, "controller": "rule"})[0] == 409  # still locked
    assert c.post("/api/resume")[0] == 200
    c.events(paused_at, stop_after=lambda ev: sum(k == "hour" for k, _ in ev) >= 3)
    assert c.post("/api/stop")[0] == 200
    events = c.events(started["first_event"])
    done = events[-1][1]
    assert events[-1][0] == "done" and done["stopped"] and not done["complete"]
    steps = done["steps"]
    assert 7 <= steps < 47 and sum(k == "hour" for k, _ in events) == steps
    agent_dir, base_dir = Path(done["agent_run"]), Path(done["baseline_run"])
    result = json.loads((agent_dir / "result.json").read_text(encoding="utf-8"))
    assert result["stopped"] and not result["complete"] and "stopped by the user" in result["stop_reason"]
    assert len(load_jsonl(base_dir / "steps.jsonl")) == steps  # baseline scored over the same hours
    rep = replay_run(agent_dir)
    assert rep.deterministic and rep.identical_steps == steps
    assert c.get("/api/viewer")[0] == 200 and c.post("/api/publish")[0] == 200


@needs_citylearn
def test_budget_cap_stops_model_calls(live):
    # Realistic token counts for a version 3 request and a full-length reply: about $0.00125 a
    # call on haiku, so a $0.01 budget covers a handful of hours. The server checks each call's
    # worst case (prompt size plus full max tokens) before making it, as the CLI does.
    srv, c = live(env={"TRIAGE_ANTHROPIC_KEY": SECRET}, model=lambda: FakeModel(tokens=(2_500, 2_000)))
    code, started = c.post("/api/start", {"hours": 24, "controller": "haiku", "budget_usd": 0.01})
    events = c.events(started["first_event"])
    done = events[-1][1]
    assert done["budget_stopped"] and 0 < done["calls"] < 24 and done["cost_usd"] <= 0.01
    hours = [d for k, d in events if k == "hour"]
    stopped = [h for h in hours if h["spend"]["budget_stopped"]]
    assert stopped and all("budget stop" in h["agent"]["decision"]["fallback"] for h in stopped)
    assert hours[-1]["spend"]["calls"] == done["calls"]


@needs_citylearn
def test_rule_and_baseline_run_without_a_key(live):
    srv, c = live(env={})
    for controller in ("rule", "baseline"):
        code, started = c.post("/api/start", {"hours": 24, "controller": controller, "budget_usd": 1})
        assert code == 200, started
        events = c.events(started["first_event"])
        start = next(d for k, d in events if k == "start")
        assert start["sample"] is True  # never presented as a model result
        assert events[-1][0] == "done" and events[-1][1]["cost_usd"] == 0
    cost = next(r for r in events[-1][1]["kpis"] if r["id"] == "cost_total")
    assert cost["agent"] == pytest.approx(1.0, abs=1e-4)  # holding the baseline scores like the baseline
