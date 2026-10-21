"""Builds the replay viewer dataset (docs/data/viewer.json) from saved run directories.

Pure function of the run files: no clock, no network, sorted keys, fixed rounding.
Building twice from the same runs gives byte-identical output.
"""

from __future__ import annotations

import json
from pathlib import Path

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
    m = run["manifest"]
    return m["simulator"].get("kind") != "citylearn" or m["supervisor"].get("kind") == "scripted"


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
    cost = [sum(s["outcome"][b]["cost_usd"] for b in buildings) for s in steps]
    emis = [sum(s["outcome"][b]["emission_kg"] for b in buildings) for s in steps]
    uncomfortable = [sum(1 for b in buildings if s["outcome"][b]["uncomfortable"]) for s in steps]
    return {
        "buildings": per_b,
        "district_grid_kwh": [_r(sum(s["outcome"][b]["grid_kwh"] for b in buildings), 3) for s in steps],
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


def _decisions(run: dict, n: int) -> list[dict]:
    out = []
    for s in run["steps"][:n]:
        d = s.get("decision") or {}
        out.append({
            "status": d.get("status", "ok"),
            "reason": d.get("reason") or "",
            "fallback": d.get("fallback"),
            "clamps": [{"point": c["point"], "rule": c["rule"], "requested": c["requested"],
                        "applied": c["applied"], "reason": c["reason"]} for c in d.get("clamps") or []],
        })
    return out


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
            "envelope": am.get("envelope"),
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


def write_viewer_data(pair: tuple[Path, Path], out_path: Path) -> dict:
    """Write viewer.json and, next to it, viewer.js (the same data as a script so the
    page also works when opened straight from disk)."""
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
