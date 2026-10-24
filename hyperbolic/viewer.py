"""Builds the replay viewer dataset (docs/data/viewer.json) from saved run directories.

Pure function of the run files: no clock, no network, sorted keys, fixed rounding.
Building twice from the same runs gives byte-identical output.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from . import __version__
from . import district as dc
from .runner import load_jsonl

SCHEMA = 2


def _r(v, nd=3):
    return None if v is None else round(float(v), nd)


def load_run(run_dir: Path) -> dict:
    run_dir = Path(run_dir)
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    result_path = run_dir / "result.json"
    result = json.loads(result_path.read_text(encoding="utf-8")) if result_path.exists() else {}
    return {
        "name": run_dir.name,
        "manifest": manifest,
        "result": result,
        "steps": load_jsonl(run_dir / "steps.jsonl"),
        "calls": load_jsonl(run_dir / "calls.jsonl"),
    }


def is_sample(run: dict) -> bool:
    """Only a live model run on CityLearn is a real agent result; scripted, rule-based and
    held-baseline runs are labeled as samples."""
    m = run["manifest"]
    if m["simulator"].get("kind") != "citylearn":
        return True
    return m["mode"] == "agent" and m["supervisor"].get("kind") != "live"


def _running(values: list[float], nd: int = 3) -> list[float]:
    out, total = [], 0.0
    for v in values:
        total += v
        out.append(_r(total, nd))
    return out


def _series(run: dict, n: int, buildings: list[str]) -> dict:
    steps = run["steps"][:n]
    per_b = {}
    for b in buildings:
        per_b[b] = {
            "indoor_c": [_r(s["outcome"][b]["indoor_c"], 2) for s in steps],
            "battery_soc": [_r(s["outcome"][b]["battery_soc"], 3) for s in steps],
            "dhw_soc": [_r(s["outcome"][b]["dhw_soc"], 3) for s in steps],
            "grid_kwh": [_r(s["outcome"][b]["grid_kwh"], 3) for s in steps],
        }
    # math.fsum is exactly rounded, so the result does not depend on the Python version
    # (the built-in sum of floats changed in Python 3.12).
    cost = [math.fsum(s["outcome"][b]["cost_usd"] for b in buildings) for s in steps]
    emis = [math.fsum(s["outcome"][b]["emission_kg"] for b in buildings) for s in steps]
    uncomfortable = [sum(1 for b in buildings if s["outcome"][b]["uncomfortable"]) for s in steps]
    return {
        "buildings": per_b,
        "district_grid_kwh": [_r(math.fsum(s["outcome"][b]["grid_kwh"] for b in buildings), 3) for s in steps],
        "cost_usd": _running(cost, 4),
        "emission_kg": _running(emis, 3),
        "discomfort_h": _running(uncomfortable, 0),
        "kpi": {k: _r(v, 6) for k, v in sorted((run["result"].get("district_kpis") or {}).items())},
        "run": run["name"],
        "steps": len(run["steps"]),
        "complete": bool(run["result"].get("complete")),
    }


def _actions(run: dict, n: int, buildings: list[str]) -> dict:
    steps = run["steps"][:n]
    return {b: {d: [_r((s["actions"] or {}).get(b, {}).get(d), 3) for s in steps] for d in ("cooling", "dhw", "battery")}
            for b in buildings}


def _decision(s: dict) -> dict:
    d = s.get("decision") or {}
    out = {
        "status": d.get("status", "ok"),
        "reason": d.get("reason") or "",
        "fallback": d.get("fallback"),
        "clamps": [{"point": c["point"], "rule": c["rule"], "requested": c["requested"],
                    "applied": c["applied"], "reason": c["reason"]} for c in d.get("clamps") or []],
    }
    # Cooling trims the model ended early, with its reason (0.8.0). Present only when there are
    # some, so the viewer data of older runs is unchanged.
    ends = [{"building": h["building"], "reason": h["reason"]} for h in d.get("holds") or []
            if h.get("action") == "end_early"]
    if ends:
        out["trim_ends"] = ends
    return out


def _decisions(run: dict, n: int) -> list[dict]:
    return [_decision(s) for s in run["steps"][:n]]


def _trim_end_count(manifest: dict, decisions: list[dict]) -> dict:
    """How many cooling trims the model ended early, for runs recorded with the trim hold."""
    if not (manifest.get("envelope") or {}).get("trim_hold"):
        return {}
    return {"trim_ends_early": sum(len(d.get("trim_ends", [])) for d in decisions)}


def _pct(agent: float | None, base: float | None) -> float | None:
    if agent is None or base is None or abs(base) < 1e-12:
        return None
    return round((agent - base) / abs(base) * 100.0, 1)


def headline(base_kpi: dict, agent_kpi: dict) -> dict:
    """Plain verdict from CityLearn's KPIs, stated as bluntly when the agent loses."""
    cost = _pct(agent_kpi.get("cost_total"), base_kpi.get("cost_total"))
    emis = _pct(agent_kpi.get("carbon_emissions_total"), base_kpi.get("carbon_emissions_total"))
    b_d = base_kpi.get("discomfort_proportion") or 0.0
    a_d = agent_kpi.get("discomfort_proportion") or 0.0
    dis_pts = round((a_d - b_d) * 100.0, 1)
    comfort_ok = a_d <= b_d + 0.005
    saves_cost = cost is not None and cost < 0
    saves_emis = emis is not None and emis < 0

    def mag(p):
        return f"{abs(p or 0):.1f}%"

    if comfort_ok and saves_cost and saves_emis:
        tone, text = "win", f"Cost down {mag(cost)} and emissions down {mag(emis)} at equal or better comfort"
    elif comfort_ok and (saves_cost or saves_emis):
        good = f"cost down {mag(cost)}" if saves_cost else f"emissions down {mag(emis)}"
        bad = f"emissions up {mag(emis)}" if saves_cost else f"cost up {mag(cost)}"
        tone, text = "mixed", f"Comfort held, {good}, but {bad}"
    elif comfort_ok:
        if a_d < b_d - 0.005:
            tone = "mixed"
            text = (f"Discomfort down {abs(dis_pts):.1f} points, paid for with cost up {mag(cost)} "
                    f"and emissions up {mag(emis)}")
        else:
            tone, text = "loss", f"The agent lost: cost up {mag(cost)} and emissions up {mag(emis)} with no comfort gain"
    else:
        tone, text = "loss", f"The agent lost on comfort: discomfort up {dis_pts:.1f} points"
        if saves_cost:
            text += f", even though cost fell {mag(cost)}"
    return {"tone": tone, "text": text, "cost_pct": cost, "emissions_pct": emis, "discomfort_points": dis_pts}


def build_scenario(baseline_dir: Path, agent_dir: Path) -> dict:
    base, agent = load_run(baseline_dir), load_run(agent_dir)
    bm, am = base["manifest"], agent["manifest"]
    if bm["mode"] != "baseline" or am["mode"] != "agent":
        raise ValueError("expected a baseline run and an agent run")
    if bm["dataset"] != am["dataset"]:
        raise ValueError("baseline and agent runs use different datasets")
    n = min(len(base["steps"]), len(agent["steps"]))
    if n == 0:
        raise ValueError("a run has no steps")
    buildings = list(am["buildings"])
    steps = agent["steps"][:n]
    first = steps[0]["state"]["time_step"]
    ar = agent["result"]
    sup = am["supervisor"]
    decisions = _decisions(agent, n)
    return {
        "id": am["dataset"],
        "name": dc.DATASET_NAME,
        "hours": n,
        "episode_hours": am.get("episode_hours"),
        "baseline_sample": is_sample(base),
        "agent_sample": is_sample(agent),
        "hour_of_day": [int(s["state"]["shared"]["hour"]) for s in steps],
        "day": [int((s["state"]["time_step"] - first) // 24) + 1 for s in steps],
        "price": [_r(s["state"]["shared"]["price_forecast"][0], 4) for s in steps],
        "carbon": [_r(s["state"]["shared"]["carbon_intensity"], 4) for s in steps],
        "outdoor_c": [_r(s["state"]["shared"]["outdoor_c"], 1) for s in steps],
        "setpoint_c": {b: [_r(s["outcome"][b]["setpoint_c"], 2) for s in steps] for b in buildings},
        "occupied": {b: [1 if s["outcome"][b]["occupants"] > 0 else 0 for s in steps] for b in buildings},
        "baseline": _series(base, n, buildings),
        "agent": {**_series(agent, n, buildings), "decisions": decisions, "actions": _actions(agent, n, buildings)},
        "agent_run": {
            "supervisor": sup.get("kind"),
            "model_key": sup.get("model_key"),
            "model_id": sup.get("model_id"),
            "budget_usd": sup.get("budget_usd"),
            "cost_usd": _r(ar.get("cost_usd", 0.0), 4),
            "calls": ar.get("calls", len(agent["calls"])),
            "clamped_hours": sum(1 for d in decisions if d["status"] == "clamped"),
            "fallback_hours": sum(1 for d in decisions if d["status"] == "fallback"),
            "budget_stopped": bool(ar.get("budget_stopped")),
            # Only runs recorded with prompt caching carry it, so older viewer data is unchanged.
            **({"cache_hit_rate": ar["cache_hit_rate"]} if "cache_hit_rate" in ar else {}),
            "envelope": am.get("envelope"),
            **_trim_end_count(am, decisions),
        },
        "headline": headline(base["result"].get("district_kpis") or {}, ar.get("district_kpis") or {}),
    }


def build_viewer_data(pair: tuple[Path, Path]) -> dict:
    s = build_scenario(*pair)
    return {
        "schema": SCHEMA,
        "dataset": dc.DATASET,
        "comfort_band_k": dc.COMFORT_BAND_K,
        "buildings": [{"id": b, "name": b.replace("_", " ")} for b in s["setpoint_c"]],
        "kpis": [{"id": k, "name": v[0], "unit": v[1]} for k, v in dc.KPIS.items()],
        "sample": s["baseline_sample"] or s["agent_sample"],
        "scenarios": [s],
    }


def dumps(data: dict) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"


def write_viewer_data(pair: tuple[Path, Path], out_path: Path, holdout_final: bool = False) -> dict:
    """Write viewer.json and, next to it, viewer.js (the same data as a script so the
    page also works when opened straight from disk). A pair on the sealed holdout needs
    holdout_final."""
    from .months import guard

    guard([json.loads((Path(d) / "manifest.json").read_text(encoding="utf-8")).get("dataset") for d in pair],
          holdout_final)
    data = build_viewer_data(pair)
    text = dumps(data)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")
    out_path.with_suffix(".js").write_text("window.HYPERBOLIC_VIEWER_DATA = " + text.rstrip("\n") + ";\n",
                                           encoding="utf-8")
    return data


def find_latest_pair(runs_dir: Path, extra_dirs: tuple[Path, ...] = ()) -> tuple[Path, Path] | None:
    """Latest complete baseline run and latest agent run; a live agent run wins over a scripted one.

    extra_dirs are searched too, so the baseline committed under results/ pairs with a
    fresh agent run in runs/.
    """
    candidates = []
    for root in (runs_dir, *extra_dirs):
        if root.exists():
            candidates += [p for p in root.iterdir() if (p / "result.json").exists()]
    best: dict[str, tuple[tuple, Path]] = {}
    for d in sorted(candidates):
        m = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
        if m.get("dataset") != dc.DATASET:
            continue
        live = m["supervisor"].get("kind") == "live"
        key = (live, m.get("started_at", ""))
        if m["mode"] not in best or key >= best[m["mode"]][0]:
            best[m["mode"]] = (key, d)
    if "baseline" in best and "agent" in best:
        return best["baseline"][1], best["agent"][1]
    return None


VERSION_JS = Path("docs/assets/version.js")


def version_js(version: str = __version__) -> str:
    """The viewer footer reads the version from this file, not from a hard-coded string."""
    return ("// The package version shown in the viewer footer. Kept equal to hyperbolic.__version__\n"
            "// by tests/test_viewer.py; refresh it with: python -m hyperbolic.viewer --write-version\n"
            f'window.HYPERBOLIC_VERSION = "{version}";\n')


# -- live mode: the same scenario, one hour at a time ---------------------------------


class RunningKpis:
    """Running estimates of the headline KPIs from hourly outcomes, for the live page.

    The final scores always come from CityLearn's evaluate(); these follow the same
    definitions closely enough to watch a run unfold: district cost, emissions and grid
    import clipped at zero each hour, discomfort as uncomfortable occupied building
    hours, and daily and all-time peaks of district draw.
    """

    def __init__(self) -> None:
        self.side = {k: {"cost": 0.0, "emission": 0.0, "import": 0.0, "occupied": 0, "uncomfortable": 0,
                         "day_peak": {}, "peak": None} for k in ("baseline", "agent")}

    def add(self, side: str, rec: dict, buildings: list[str], day: int) -> None:
        a, out = self.side[side], rec["outcome"]
        a["cost"] += max(0.0, math.fsum(out[b]["cost_usd"] for b in buildings))
        a["emission"] += max(0.0, math.fsum(out[b]["emission_kg"] for b in buildings))
        grid = math.fsum(out[b]["grid_kwh"] for b in buildings)
        a["import"] += max(0.0, grid)
        a["day_peak"][day] = max(a["day_peak"].get(day, grid), grid)
        a["peak"] = grid if a["peak"] is None else max(a["peak"], grid)
        for b in buildings:
            if out[b]["occupants"] > 0:
                a["occupied"] += 1
                a["uncomfortable"] += 1 if out[b]["uncomfortable"] else 0

    def kpis(self) -> tuple[dict, dict]:
        base, agent = self.side["baseline"], self.side["agent"]

        def ratio(x, y):
            return None if abs(y) < 1e-12 else round(x / y, 6)

        def mean(d):
            return math.fsum(d.values()) / len(d) if d else 0.0

        def share(a):
            return round(a["uncomfortable"] / a["occupied"], 6) if a["occupied"] else 0.0

        out = {}
        for name, a in (("baseline", base), ("agent", agent)):
            out[name] = {
                "cost_total": ratio(a["cost"], base["cost"]),
                "carbon_emissions_total": ratio(a["emission"], base["emission"]),
                "electricity_consumption_total": ratio(a["import"], base["import"]),
                "discomfort_proportion": share(a),
                "daily_peak_average": ratio(mean(a["day_peak"]), mean(base["day_peak"])),
                "all_time_peak_average": None if base["peak"] in (None, 0) else ratio(a["peak"], base["peak"]),
            }
        return out["baseline"], out["agent"]


class ScenarioStream:
    """Builds one hour of the viewer's scenario at a time from a baseline record and an
    agent record for the same hour. Concatenating the rows gives the same series as
    build_scenario over the same runs (tests hold it to that)."""

    def __init__(self, buildings: list[str]) -> None:
        self.buildings = list(buildings)
        self.first: int | None = None
        self.totals = {k: {"cost": 0.0, "emission": 0.0, "discomfort": 0} for k in ("baseline", "agent")}
        self.running = RunningKpis()

    def _side(self, side: str, rec: dict) -> dict:
        out, bs = rec["outcome"], self.buildings
        t = self.totals[side]
        t["cost"] += math.fsum(out[b]["cost_usd"] for b in bs)
        t["emission"] += math.fsum(out[b]["emission_kg"] for b in bs)
        t["discomfort"] += sum(1 for b in bs if out[b]["uncomfortable"])
        return {
            "buildings": {b: {"indoor_c": _r(out[b]["indoor_c"], 2), "battery_soc": _r(out[b]["battery_soc"], 3),
                              "dhw_soc": _r(out[b]["dhw_soc"], 3), "grid_kwh": _r(out[b]["grid_kwh"], 3)} for b in bs},
            "district_grid_kwh": _r(math.fsum(out[b]["grid_kwh"] for b in bs), 3),
            "cost_usd": _r(t["cost"], 4),
            "emission_kg": _r(t["emission"], 3),
            "discomfort_h": _r(t["discomfort"], 0),
        }

    def add(self, base_rec: dict, agent_rec: dict) -> dict:
        st, bs = agent_rec["state"], self.buildings
        if self.first is None:
            self.first = st["time_step"]
        day = int((st["time_step"] - self.first) // 24) + 1
        self.running.add("baseline", base_rec, bs, day)
        self.running.add("agent", agent_rec, bs, day)
        base_kpi, agent_kpi = self.running.kpis()
        agent = self._side("agent", agent_rec)
        agent["decision"] = _decision(agent_rec)
        agent["actions"] = {b: {d: _r((agent_rec["actions"] or {}).get(b, {}).get(d), 3)
                                for d in ("cooling", "dhw", "battery")} for b in bs}
        out = agent_rec["outcome"]
        return {
            "i": agent_rec["step"],
            "hour_of_day": int(st["shared"]["hour"]),
            "day": day,
            "price": _r(st["shared"]["price_forecast"][0], 4),
            "carbon": _r(st["shared"]["carbon_intensity"], 4),
            "outdoor_c": _r(st["shared"]["outdoor_c"], 1),
            "setpoint_c": {b: _r(out[b]["setpoint_c"], 2) for b in bs},
            "occupied": {b: 1 if out[b]["occupants"] > 0 else 0 for b in bs},
            "baseline": self._side("baseline", base_rec),
            "agent": agent,
            "kpi": {"baseline": base_kpi, "agent": agent_kpi},
            "headline": headline(base_kpi, agent_kpi),
        }


def viewer_shell(buildings: list[str]) -> dict:
    """The parts of build_viewer_data that do not depend on the run, for the live page."""
    return {
        "schema": SCHEMA,
        "dataset": dc.DATASET,
        "comfort_band_k": dc.COMFORT_BAND_K,
        "buildings": [{"id": b, "name": b.replace("_", " ")} for b in buildings],
        "kpis": [{"id": k, "name": v[0], "unit": v[1]} for k, v in dc.KPIS.items()],
    }


if __name__ == "__main__":
    import sys

    if sys.argv[1:] == ["--write-version"]:
        VERSION_JS.write_text(version_js(), encoding="utf-8")
        print(f"wrote {VERSION_JS} for {__version__}")
    else:
        print("usage: python -m hyperbolic.viewer --write-version", file=sys.stderr)
        raise SystemExit(2)
