"""Local live mode: `hyperbolic serve`.

A small web server on 127.0.0.1 that serves the replay viewer from docs/ with a live
control panel added, runs one simulation at a time in a background thread, and streams
each finished hour to the page with Server-Sent Events. Standard library only:
http.server for HTTP and plain text/event-stream for the stream, so live mode adds no
dependency.

Runs go through the same run_session, envelope, budget and run folder format as
`hyperbolic run`, so every live run replays with `hyperbolic replay`. The API key stays
in this process: the page only learns whether a key is present.

Safety: the server binds 127.0.0.1 only and answers only requests whose Host header is
127.0.0.1 or localhost on its port (a guard against DNS rebinding). Requests that change
anything must be POSTs with a JSON body, the X-Hyperbolic-Live header and, when the
browser sends one, a same-origin Origin header, so another web page cannot start a run.
"""

from __future__ import annotations

import http.server
import json
import mimetypes
import os
import threading
import webbrowser
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from . import __version__
from . import district as dc
from .envelope import Envelope, EnvelopeConfig
from .model import (
    DEFAULT_BUDGET_USD,
    KEY_ENV_VARS,
    MODELS,
    Budget,
    HoldSupervisor,
    KeyMissing,
    ScriptedSupervisor,
    Supervisor,
    call_cost_usd,
    resolve_api_key,
)
from .runner import (
    AgentController,
    BaselineController,
    RunWriter,
    context_from_state,
    load_jsonl,
    new_run_dir,
    run_session,
)
from .viewer import ScenarioStream, build_viewer_data, viewer_shell, write_viewer_data

DEFAULT_PORT = 8765
LOOPBACK_HOSTS = ("127.0.0.1", "localhost")
MAX_BUDGET_USD = 100.0
LIVE_ASSETS = Path(__file__).parent / "live_assets"
COMMITTED_BASELINE = Path("results/baseline")
HEADER = "X-Hyperbolic-Live"

CONTROLLERS = {
    "haiku": {"label": MODELS["haiku"]["id"], "model": True},
    "sonnet": {"label": MODELS["sonnet"]["id"], "model": True},
    "rule": {"label": "Rule-based controller (no model)", "model": False},
    "baseline": {"label": "Baseline (no-control actions)", "model": False},
}
DURATIONS = [
    {"id": "day", "label": "24 hours", "hours": 24},
    {"id": "week", "label": "1 week (167 hours)", "hours": 167},
    {"id": "month", "label": "Full month (719 hours)", "hours": dc.EPISODE_HOURS},
]
# Typical prompt version 3 request and reply, for a cost estimate before any run is recorded.
TYPICAL_TOKENS = (2500, 250)


def key_status(env: dict[str, str] | None = None) -> dict:
    """Whether a key is configured, and in which variable. Never the key itself."""
    try:
        _, source = resolve_api_key(env)
    except KeyMissing:
        return {"present": False, "source": None, "variables": list(KEY_ENV_VARS)}
    return {"present": True, "source": source, "variables": list(KEY_ENV_VARS)}


def default_supervisor(controller: str) -> Supervisor:
    if controller in ("haiku", "sonnet"):
        from .model import LiveSupervisor

        return LiveSupervisor(controller)
    if controller == "rule":
        return ScriptedSupervisor("haiku")
    if controller == "baseline":
        return HoldSupervisor("haiku")
    raise ValueError(f"unknown controller {controller}")


def cost_estimates(runs_dir: Path, docs: Path) -> dict:
    """USD per hour for each model, from the cost of recorded live runs (runs/ and the
    published docs/data). Sonnet without its own runs is scaled from Haiku by price."""
    samples: dict[str, dict[str, float]] = {k: {} for k in MODELS}
    if runs_dir.exists():
        for d in sorted(runs_dir.iterdir()):
            try:
                m = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
                r = json.loads((d / "result.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            sup = m.get("supervisor") or {}
            if sup.get("kind") == "live" and sup.get("model_key") in samples and r.get("calls") and r.get("steps"):
                samples[sup["model_key"]][d.name] = float(r["cost_usd"]) / float(r["steps"])
    try:
        data = json.loads((docs / "data" / "viewer.json").read_text(encoding="utf-8"))
        for sc in data.get("scenarios", []):
            run = sc.get("agent_run") or {}
            if run.get("supervisor") == "live" and run.get("model_key") in samples and sc.get("hours"):
                samples[run["model_key"]][sc["agent"]["run"]] = float(run["cost_usd"]) / float(sc["hours"])
    except (OSError, ValueError, KeyError):
        pass
    out = {}
    for key in MODELS:
        vals = list(samples[key].values())
        if vals:
            out[key] = {"per_hour": sum(vals) / len(vals), "source": f"{len(vals)} recorded {key} run{'' if len(vals) == 1 else 's'}"}
    haiku = out.get("haiku")
    for key in MODELS:
        if key in out:
            continue
        if haiku:
            scale = MODELS[key]["input_per_mtok"] / MODELS["haiku"]["input_per_mtok"]
            out[key] = {"per_hour": haiku["per_hour"] * scale, "source": f"recorded haiku runs at {key} prices"}
        else:
            out[key] = {"per_hour": call_cost_usd(key, *TYPICAL_TOKENS), "source": "typical request size"}
    out["rule"] = {"per_hour": 0.0, "source": "no model calls"}
    out["baseline"] = {"per_hour": 0.0, "source": "no model calls"}
    return out


def _unique(path: Path) -> Path:
    if not path.exists():
        return path
    i = 2
    while path.with_name(f"{path.name}_{i}").exists():
        i += 1
    return path.with_name(f"{path.name}_{i}")


def _check_hours(hours: Any) -> int:
    if isinstance(hours, bool) or not isinstance(hours, int):
        raise ValueError("hours must be a whole number")
    if not 1 <= hours <= dc.EPISODE_HOURS:
        raise ValueError(f"hours must be between 1 and {dc.EPISODE_HOURS}")
    from .sim import CityLearnSimulator

    CityLearnSimulator.check_hours(hours)
    return hours


@dataclass
class Run:
    """One live run: its settings, where it is recorded and how it ended."""

    hours: int
    controller: str
    budget_usd: float
    first_event: int
    state: str = "starting"  # starting, baseline, running, paused, stopping, finished, error
    agent_dir: Path | None = None
    baseline_dir: Path | None = None
    result: dict = field(default_factory=dict)


class LiveHub:
    """Holds the one run that may be going, and the event log the page streams from."""

    def __init__(self, runs_dir: Path, docs: Path,
                 supervisor_factory: Callable[[str], Supervisor] = default_supervisor,
                 env: dict[str, str] | None = None, baseline_dir: Path = COMMITTED_BASELINE) -> None:
        self.runs_dir = Path(runs_dir)
        self.docs = Path(docs)
        self.supervisor_factory = supervisor_factory
        self.env = env  # None means os.environ, read at the moment it is needed
        self.committed_baseline = Path(baseline_dir)
        self.cond = threading.Condition()
        self.events: list[tuple[int, str, dict]] = []
        self.run: Run | None = None
        self.thread: threading.Thread | None = None
        self.paused = False
        self.stop_requested = False
        self.closing = False

    # -- events ------------------------------------------------------------------

    def emit(self, kind: str, data: dict) -> None:
        with self.cond:
            self.events.append((len(self.events), kind, data))
            self.cond.notify_all()

    def wait_events(self, since: int, timeout: float) -> list[tuple[int, str, dict]]:
        with self.cond:
            if since >= len(self.events) and not self.closing:
                self.cond.wait(timeout)
            return self.events[since:]

    # -- RunControl --------------------------------------------------------------

    def checkpoint(self) -> bool:
        with self.cond:
            while self.paused and not self.stop_requested and not self.closing:
                self.cond.wait(0.5)
            return not (self.stop_requested or self.closing)

    # -- controls ----------------------------------------------------------------

    def busy(self) -> bool:
        return self.thread is not None and self.thread.is_alive()

    def config(self) -> dict:
        key = key_status(self.env)
        controllers = []
        for cid, c in CONTROLLERS.items():
            available = key["present"] or not c["model"]
            note = "" if available else (f"Set {KEY_ENV_VARS[1]} (or {KEY_ENV_VARS[0]}) before starting "
                                         "`hyperbolic serve` to use the model.")
            controllers.append({"id": cid, "label": c["label"], "model": c["model"], "available": available,
                                "note": note})
        return {
            "version": __version__,
            "controllers": controllers,
            "key": key,
            "durations": DURATIONS,
            "episode_hours": dc.EPISODE_HOURS,
            "default_budget_usd": DEFAULT_BUDGET_USD,
            "max_budget_usd": MAX_BUDGET_USD,
            "estimates": cost_estimates(self.runs_dir, self.docs),
            "hours_rule": "Runs of two days or more need hours + 1 to be a whole number of days, "
                          "for example 47, 71, 167 or 719.",
        }

    def status(self) -> dict:
        with self.cond:
            r = self.run
            return {
                "state": "idle" if r is None else r.state,
                "busy": self.busy(),
                "paused": self.paused,
                "first_event": None if r is None else r.first_event,
                "events": len(self.events),
                "run": None if r is None else {"hours": r.hours, "controller": r.controller,
                                               "budget_usd": r.budget_usd},
            }

    def start(self, params: dict) -> tuple[int, dict]:
        controller = params.get("controller")
        if controller not in CONTROLLERS:
            return 400, {"error": "unknown controller"}
        try:
            hours = _check_hours(params.get("hours"))
        except ValueError as exc:
            return 400, {"error": str(exc)}
        budget = params.get("budget_usd", DEFAULT_BUDGET_USD)
        if isinstance(budget, bool) or not isinstance(budget, (int, float)) or not 0 < budget <= MAX_BUDGET_USD:
            return 400, {"error": f"budget must be more than 0 and at most {MAX_BUDGET_USD:g} USD"}
        if CONTROLLERS[controller]["model"] and not key_status(self.env)["present"]:
            return 400, {"error": f"No API key: set {KEY_ENV_VARS[1]} to use {CONTROLLERS[controller]['label']}. "
                                  "The rule-based and baseline controllers work without one."}
        with self.cond:
            if self.busy():
                return 409, {"error": "a run is already going; stop it first"}
            self.paused = False
            self.stop_requested = False
            self.run = Run(hours=hours, controller=controller, budget_usd=float(budget), first_event=len(self.events))
            run = self.run
        self.thread = threading.Thread(target=self._execute, args=(run,), name="hyperbolic-live-run", daemon=True)
        self.thread.start()
        return 200, {"ok": True, "first_event": run.first_event}

    def pause(self) -> tuple[int, dict]:
        return self._set_pause(True)

    def resume(self) -> tuple[int, dict]:
        return self._set_pause(False)

    def _set_pause(self, on: bool) -> tuple[int, dict]:
        with self.cond:
            if not self.busy() or self.run is None or self.run.state not in ("running", "paused"):
                return 409, {"error": "no run is going"}
            self.paused = on
            self.run.state = "paused" if on else "running"
            self.cond.notify_all()
        self.emit("status", {"state": self.run.state})
        return 200, {"ok": True}

    def stop(self) -> tuple[int, dict]:
        with self.cond:
            if not self.busy() or self.run is None:
                return 409, {"error": "no run is going"}
            self.stop_requested = True
            self.paused = False
            self.run.state = "stopping"
            self.cond.notify_all()
        self.emit("status", {"state": "stopping"})
        return 200, {"ok": True}

    def finished_pair(self) -> tuple[Path, Path] | None:
        r = self.run
        if r is None or r.state != "finished" or self.busy() or not r.agent_dir or not r.baseline_dir:
            return None
        return r.baseline_dir, r.agent_dir

    def publish(self) -> tuple[int, dict]:
        pair = self.finished_pair()
        if pair is None:
            return 409, {"error": "nothing to publish yet; wait for a run to finish"}
        out = self.docs / "data" / "viewer.json"
        write_viewer_data(pair, out)
        return 200, {"ok": True, "written": [str(out), str(out.with_suffix(".js"))],
                     "pair": [str(pair[0]), str(pair[1])],
                     "note": "Local files only. Nothing was committed or pushed."}

    def shutdown(self, wait: float = 30.0) -> None:
        with self.cond:
            self.closing = True
            self.stop_requested = True
            self.paused = False
            self.cond.notify_all()
        if self.thread is not None:
            self.thread.join(wait)

    # -- the run ---------------------------------------------------------------

    def _baseline(self, run: Run, steps: int | None = None) -> tuple[Path, list[dict]]:
        """Baseline over the same hours. The committed full-month baseline is reused for a
        complete month; anything else is simulated with the same episode length so CityLearn
        draws the same outages, and stopped early to match a stopped agent run."""
        if run.hours == dc.EPISODE_HOURS and steps is None and (self.committed_baseline / "steps.jsonl").exists():
            return self.committed_baseline, load_jsonl(self.committed_baseline / "steps.jsonl")
        from .sim import CityLearnSimulator

        out = _unique(new_run_dir(self.runs_dir, "baseline", "citylearn"))
        run_session(CityLearnSimulator(control=False), BaselineController(), RunWriter(out), run.hours,
                    {"kind": "citylearn", "control": False, "source": "serve"}, log=lambda *_: None,
                    max_steps=steps)
        return out, load_jsonl(out / "steps.jsonl")

    def _execute(self, run: Run) -> None:
        from .sim import CityLearnSimulator

        try:
            run.state = "baseline"
            self.emit("status", {"state": "baseline", "hours": run.hours})
            run.baseline_dir, base_steps = self._baseline(run)
            supervisor = self.supervisor_factory(run.controller)
            ctl = AgentController(supervisor=supervisor, envelope=Envelope(EnvelopeConfig()),
                                  budget=Budget(limit_usd=run.budget_usd))
            run.agent_dir = _unique(new_run_dir(self.runs_dir, "agent", "citylearn"))
            buildings = list(base_steps[0]["outcome"]) if base_steps else []
            stream = ScenarioStream(buildings)
            describe = ctl.describe()
            self.emit("start", {
                "hours": run.hours, "controller": run.controller, "label": CONTROLLERS[run.controller]["label"],
                "budget_usd": run.budget_usd, "supervisor": describe, "shell": viewer_shell(buildings),
                "dataset_name": dc.DATASET_NAME, "agent_run": run.agent_dir.name,
                "baseline_run": run.baseline_dir.name, "sample": run.controller not in ("haiku", "sonnet"),
            })
            run.state = "running"
            self.emit("status", {"state": "running"})

            def on_step(rec: dict) -> None:
                row = stream.add(base_steps[rec["step"]], rec)
                t = int(rec["state"]["time_step"])
                info = ctl.peaks.info(t) if ctl.peaks is not None else None
                target = ctl.envelope.peak_target(context_from_state(rec["state"], info))
                row["peak"] = {"load_kwh": None if info is None or info.load_now_kwh is None else round(info.load_now_kwh, 3),
                               "target_kwh": None if target is None else round(target, 3),
                               "drawn_kwh": row["agent"]["district_grid_kwh"]}
                row["spend"] = {"usd": round(ctl.budget.spent_usd, 6), "budget_usd": run.budget_usd,
                                "calls": ctl.counts["calls"], "clamped": ctl.counts["clamped"],
                                "fallback": ctl.counts["fallback"], "budget_stopped": ctl.budget.stopped,
                                "budget_stop_reason": ctl.budget.stop_reason}
                self.emit("hour", row)

            run.result = run_session(CityLearnSimulator(control=True), ctl, RunWriter(run.agent_dir), run.hours,
                                     {"kind": "citylearn", "control": True, "source": "serve"},
                                     log=lambda *_: None, on_step=on_step, control=self)
            if run.result.get("stopped"):
                self.emit("status", {"state": "stopping", "detail": "scoring the baseline over the same hours"})
                if run.result["steps"] == 0:
                    raise RuntimeError("stopped before the first hour finished; nothing to score")
                run.baseline_dir, _ = self._baseline(run, steps=run.result["steps"])
            base_result = json.loads((run.baseline_dir / "result.json").read_text(encoding="utf-8"))
            rows = []
            for k, (name, unit) in dc.KPIS.items():
                b, a = base_result["district_kpis"].get(k), run.result["district_kpis"].get(k)
                if b is not None or a is not None:
                    rows.append({"id": k, "name": name, "unit": unit, "baseline": b, "agent": a})
            run.state = "finished"
            self.emit("done", {
                "complete": bool(run.result.get("complete")), "stopped": bool(run.result.get("stopped")),
                "stop_reason": run.result.get("stop_reason"), "steps": run.result["steps"], "hours": run.hours,
                "agent_run": str(run.agent_dir), "baseline_run": str(run.baseline_dir), "kpis": rows,
                "cost_usd": run.result["cost_usd"], "calls": run.result["calls"],
                "clamped": run.result["clamped_steps"], "fallback": run.result["fallback_steps"],
                "budget_stopped": run.result["budget_stopped"], "budget_stop_reason": run.result["budget_stop_reason"],
            })
        except Exception as exc:  # report, never crash the server
            run.state = "error"
            self.emit("failed", {"message": self._scrub(f"{type(exc).__name__}: {exc}")})
        finally:
            with self.cond:
                self.paused = False
                self.cond.notify_all()

    def _scrub(self, text: str) -> str:
        """Belt and braces: never let a key value reach the page, even inside an error message."""
        env = os.environ if self.env is None else self.env
        for name in KEY_ENV_VARS:
            value = (env.get(name) or "").strip()
            if value:
                text = text.replace(value, "[key]")
        return text


# -- HTTP ------------------------------------------------------------------------------


class LiveServer(http.server.ThreadingHTTPServer):
    daemon_threads = True
    # On Linux and macOS this only skips the TIME_WAIT of a server that just stopped; it never
    # lets two servers share a port. On Windows the same flag would, so it stays off there.
    allow_reuse_address = os.name != "nt"

    def __init__(self, port: int, hub: LiveHub, quiet: bool = True) -> None:
        super().__init__(("127.0.0.1", port), LiveHandler)
        self.hub = hub
        self.quiet = quiet

    @property
    def port(self) -> int:
        return int(self.server_address[1])

    def allowed_hosts(self) -> set[str]:
        return {f"{h}:{self.port}" for h in LOOPBACK_HOSTS}

    def allowed_origins(self) -> set[str]:
        return {f"http://{h}" for h in self.allowed_hosts()}


class LiveHandler(http.server.BaseHTTPRequestHandler):
    server: LiveServer
    server_version = "Hyperbolic"
    sys_version = ""

    def log_message(self, fmt: str, *args) -> None:
        if not self.server.quiet:
            super().log_message(fmt, *args)

    # -- helpers ---------------------------------------------------------------

    def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, code: int, data: Any) -> None:
        self._send(code, json.dumps(data, separators=(",", ":"), ensure_ascii=True).encode(), "application/json")

    def _host_ok(self) -> bool:
        if (self.headers.get("Host") or "") not in self.server.allowed_hosts():
            self._json(403, {"error": "this server only answers on 127.0.0.1 or localhost"})
            return False
        return True

    def _file(self, root: Path, rel: str) -> None:
        base = root.resolve()
        try:
            path = (base / rel).resolve()
            path.relative_to(base)
        except (ValueError, OSError):
            return self._json(404, {"error": "not found"})
        if not path.is_file():
            return self._json(404, {"error": "not found"})
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        self._send(200, path.read_bytes(), ctype)

    def _index(self) -> None:
        html = (self.server.hub.docs / "index.html").read_text(encoding="utf-8")
        boot = json.dumps({"version": __version__}, separators=(",", ":"))
        html = html.replace("</head>", '  <link rel="stylesheet" href="live/live.css">\n</head>', 1)
        html = html.replace("</body>", f"  <script>window.HYPERBOLIC_LIVE = {boot};</script>\n"
                                       '  <script src="live/live.js"></script>\n</body>', 1)
        self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")

    # -- GET -------------------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802
        if not self._host_ok():
            return
        url = urlparse(self.path)
        path, hub = url.path, self.server.hub
        if path in ("/", "/index.html"):
            return self._index()
        if path == "/api/config":
            return self._json(200, hub.config())
        if path == "/api/state":
            return self._json(200, hub.status())
        if path == "/api/events":
            return self._events(parse_qs(url.query))
        if path == "/api/viewer":
            pair = hub.finished_pair()
            if pair is None:
                return self._json(409, {"error": "no finished run"})
            return self._json(200, build_viewer_data(pair))
        if path.startswith("/live/"):
            return self._file(LIVE_ASSETS, path[len("/live/"):])
        if path.startswith(("/assets/", "/data/")):
            return self._file(hub.docs, path.lstrip("/"))
        return self._json(404, {"error": "not found"})

    do_HEAD = do_GET

    def _events(self, query: dict) -> None:
        hub = self.server.hub
        try:
            since = max(0, int((query.get("since") or ["0"])[0]))
        except ValueError:
            since = 0
        last = self.headers.get("Last-Event-ID")
        if last is not None and last.isdigit():
            since = max(since, int(last) + 1)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        try:
            while not hub.closing:
                batch = hub.wait_events(since, timeout=15.0)
                if not batch:
                    self.wfile.write(b": keep-alive\n\n")
                for eid, kind, data in batch:
                    payload = json.dumps(data, separators=(",", ":"), ensure_ascii=True)
                    self.wfile.write(f"id: {eid}\nevent: {kind}\ndata: {payload}\n\n".encode())
                since += len(batch)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, TimeoutError):
            return

    # -- POST ------------------------------------------------------------------

    def do_POST(self) -> None:  # noqa: N802
        if not self._host_ok():
            return
        origin = self.headers.get("Origin")
        if origin is not None and origin not in self.server.allowed_origins():
            return self._json(403, {"error": "cross-origin requests are refused"})
        if self.headers.get(HEADER) != "1":
            return self._json(403, {"error": f"missing {HEADER} header"})
        if not (self.headers.get("Content-Type") or "").startswith("application/json"):
            return self._json(415, {"error": "send JSON"})
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = -1
        if not 0 <= length <= 10_000:
            return self._json(413, {"error": "request too large"})
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return self._json(400, {"error": "invalid JSON"})
        if not isinstance(body, dict):
            return self._json(400, {"error": "send a JSON object"})
        hub = self.server.hub
        routes = {"/api/start": lambda: hub.start(body), "/api/pause": hub.pause, "/api/resume": hub.resume,
                  "/api/stop": hub.stop, "/api/publish": hub.publish}
        action = routes.get(urlparse(self.path).path)
        if action is None:
            return self._json(404, {"error": "not found"})
        code, data = action()
        self._json(code, data)


def make_server(port: int = DEFAULT_PORT, host: str = "127.0.0.1", runs_dir: Path = Path("runs"),
                docs: Path = Path("docs"), supervisor_factory: Callable[[str], Supervisor] = default_supervisor,
                env: dict[str, str] | None = None, quiet: bool = True,
                baseline_dir: Path = COMMITTED_BASELINE) -> LiveServer:
    if host not in LOOPBACK_HOSTS:
        raise ValueError(f"live mode only listens on 127.0.0.1 (got {host!r})")
    if not (Path(docs) / "index.html").exists():
        raise FileNotFoundError(f"{docs}/index.html not found; run `hyperbolic serve` from the repository folder")
    hub = LiveHub(runs_dir, docs, supervisor_factory, env, baseline_dir)
    return LiveServer(port, hub, quiet=quiet)


def serve(port: int = DEFAULT_PORT, host: str = "127.0.0.1", runs_dir: Path = Path("runs"),
          docs: Path = Path("docs"), open_browser: bool = True, log=print) -> int:
    server = make_server(port, host, runs_dir, docs, quiet=True)
    url = f"http://127.0.0.1:{server.port}/"
    key = key_status()
    log(f"Hyperbolic live mode at {url} (127.0.0.1 only). Press Ctrl+C to stop.")
    log(f"  model key: {'found in ' + key['source'] if key['present'] else 'not set, Claude options are disabled'}")
    log(f"  runs are recorded in {runs_dir}; Publish writes {docs}/data")
    if open_browser:
        threading.Timer(0.6, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        log("stopping; a run in progress is saved as partial")
    finally:
        server.hub.shutdown()
        server.server_close()
    return 0
