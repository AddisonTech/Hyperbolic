"""Builds the replay viewer dataset (docs/data/viewer.json) from saved run directories.

Pure function of the run files: no clock, no network, sorted keys, fixed rounding.
Building twice from the same runs gives byte-identical output.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import testcase as tc
from .runner import load_jsonl

SCHEMA = 1


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
    return m["simulator"].get("kind") != "boptest" or m["supervisor"].get("kind") == "scripted"


def _running(steps: list[dict], key: str, scale: float) -> list[float | None]:
    out, last = [], 0.0
    for s in steps:
        k = s.get("kpi") or {}
        if k.get(key) is not None:
            last = float(k[key]) * scale
        out.append(_r(last, 3))
    return out


def _series(run: dict, n: int, agent: bool) -> dict:
    steps = run["steps"][:n]
    tz = {z: [_r(tc.k_to_c(s["y"][tc.zone_temp_point(z)]), 2) for s in steps] for z in tc.ZONES}
    heat = {z: [] for z in tc.ZONES}
    cool = {z: [] for z in tc.ZONES}
    tsup_set = []
    for s in steps:
        stock_h, stock_c = tc.stock_zone_setpoints_c(s["time"])
        d = s.get("decision") if agent else None
        for z in tc.ZONES:
            hv = d["heat_c"][z] if d else None
            cv = d["cool_c"][z] if d else None
            heat[z].append(_r(stock_h if hv is None else hv, 2))
            cool[z].append(_r(stock_c if cv is None else cv, 2))
        tsup_set.append(None if not d else _r(d["supply_air_c"], 2))
    power = [_r(sum(float(s["y"].get(p, 0.0) or 0.0) for p in tc.POWER_POINTS) / 1000.0, 2) for s in steps]
    out = {
        "zone_temp_c": tz,
        "heat_set_c": heat,
        "cool_set_c": cool,
        "supply_air_c": [_r(tc.k_to_c(s["y"][tc.SUPPLY_AIR_TEMP_POINT]), 2) for s in steps],
        "supply_air_set_c": tsup_set,
        "power_kw": power,
        "energy_kwh": _running(steps, "ener_tot", tc.FLOOR_AREA_M2),
        "cost_usd": _running(steps, "cost_tot", tc.FLOOR_AREA_M2),
        "discomfort_kh": _running(steps, "tdis_tot", 1.0),
        "kpi": {k: _r(v, 6) for k, v in sorted((run["result"].get("final_kpi") or {}).items())},
        "run": run["name"],
        "steps": len(run["steps"]),
        "complete": bool(run["result"].get("complete")),
    }
    return out


def _decisions(run: dict, n: int) -> list[dict]:
    out = []
    for s in run["steps"][:n]:
        d = s.get("decision") or {}
        clamps = d.get("clamps") or []
        out.append({
            "status": d.get("status", "ok"),
            "reason": d.get("reason") or "",
            "fallback": d.get("fallback"),
            "clamps": [{"point": c["point"], "rule": c["rule"], "requested": c["requested"],
                        "applied": c["applied"], "reason": c["reason"]} for c in clamps],
        })
    return out


def _pct(agent: float | None, base: float | None) -> float | None:
    if agent is None or base is None or abs(base) < 1e-12:
        return None
    return round((agent - base) / abs(base) * 100.0, 1)


def headline(base_kpi: dict, agent_kpi: dict) -> dict:
    """Plain verdict, stated as bluntly when the agent loses as when it wins."""
    cost = _pct(agent_kpi.get("cost_tot"), base_kpi.get("cost_tot"))
    ener = _pct(agent_kpi.get("ener_tot"), base_kpi.get("ener_tot"))
    tdis = _pct(agent_kpi.get("tdis_tot"), base_kpi.get("tdis_tot"))
    b_t, a_t = base_kpi.get("tdis_tot") or 0.0, agent_kpi.get("tdis_tot") or 0.0
    comfort_ok = a_t <= b_t + 0.05
    saves_cost = cost is not None and cost < 0
    saves_energy = ener is not None and ener < 0

    def mag(p):
        return f"{abs(p):.1f}%"

    if comfort_ok and saves_cost and saves_energy:
        tone = "win"
        text = f"Cost down {mag(cost)} and energy down {mag(ener)} at equal or better comfort"
    elif comfort_ok and (saves_cost or saves_energy):
        tone = "mixed"
        good = f"cost down {mag(cost)}" if saves_cost else f"energy down {mag(ener)}"
        bad = f"energy up {mag(ener)}" if saves_cost else f"cost up {mag(cost)}"
        text = f"Comfort held, {good}, but {bad}"
    elif comfort_ok:
        tone = "loss" if (a_t >= b_t - 0.05) else "mixed"
        if tone == "loss":
            text = f"The agent lost: cost up {mag(cost or 0)} and energy up {mag(ener or 0)} with no comfort gain"
        else:
            text = f"Discomfort down {mag(tdis or 0)}, paid for with cost up {mag(cost or 0)} and energy up {mag(ener or 0)}"
    else:
        tone = "loss"
        text = f"The agent lost on comfort: discomfort up {mag(tdis or 0)}"
        if saves_cost:
            text += f", even though cost fell {mag(cost)}"
    return {"tone": tone, "text": text, "cost_pct": cost, "energy_pct": ener, "discomfort_pct": tdis}


def build_scenario(baseline_dir: Path, agent_dir: Path) -> dict:
    base, agent = load_run(baseline_dir), load_run(agent_dir)
    bm, am = base["manifest"], agent["manifest"]
    if bm["mode"] != "baseline" or am["mode"] != "agent":
        raise ValueError("expected a baseline run and an agent run")
    if bm["scenario"] != am["scenario"] or bm["electricity_price"] != am["electricity_price"]:
        raise ValueError("baseline and agent runs are from different scenarios")
    n = min(len(base["steps"]), len(agent["steps"]))
    if n == 0:
        raise ValueError("a run has no steps")
    steps = agent["steps"][:n]
    fc0 = [s["forecast"] for s in steps]
    price_key = tc.PRICE_POINT[am["electricity_price"]]
    decisions = _decisions(agent, n)
    ar = agent["result"]
    sup = am["supervisor"]
    return {
        "id": am["scenario"],
        "name": tc.SCENARIOS[am["scenario"]]["name"],
        "electricity_price": am["electricity_price"],
        "testcase": am["testcase"],
        "sample": is_sample(base) or is_sample(agent),
        "simulator": am["simulator"].get("kind"),
        "hours": n,
        "scenario_hours": am.get("scenario_hours"),
        "start_time_s": steps[0]["time"],
        "time_s": [int(s["time"]) + tc.STEP_SECONDS for s in steps],
        "band_lower_c": [_r(tc.k_to_c(f["LowerSetp[cor]"][1 if len(f["time"]) > 1 else 0]), 1) for f in fc0],
        "band_upper_c": [_r(tc.k_to_c(f["UpperSetp[cor]"][1 if len(f["time"]) > 1 else 0]), 1) for f in fc0],
        "price": [_r(f[price_key][0], 4) for f in fc0],
        "outdoor_c": [_r(tc.k_to_c(s["y"][tc.OUTDOOR_TEMP_POINT]), 1) for s in steps],
        "baseline": _series(base, n, agent=False),
        "agent": {**_series(agent, n, agent=True), "decisions": decisions},
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
        "headline": headline(base["result"].get("final_kpi") or {}, ar.get("final_kpi") or {}),
    }


def build_viewer_data(pairs: list[tuple[Path, Path]]) -> dict:
    scenarios = [build_scenario(b, a) for b, a in pairs]
    order = {k: i for i, k in enumerate(tc.SCENARIOS)}
    scenarios.sort(key=lambda s: order.get(s["id"], 99))
    return {
        "schema": SCHEMA,
        "testcase": tc.TESTCASE,
        "floor_area_m2": tc.FLOOR_AREA_M2,
        "zones": [{"id": z, "name": tc.ZONE_NAMES[z], "area_m2": tc.ZONE_AREA_M2[z]} for z in tc.ZONES],
        "kpis": [{"id": k, "name": v[0], "unit": v[1]} for k, v in tc.KPIS.items()],
        "sample": any(s["sample"] for s in scenarios),
        "scenarios": scenarios,
    }


def dumps(data: dict) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n"


def write_viewer_data(pairs: list[tuple[Path, Path]], out_path: Path) -> dict:
    """Write viewer.json and, next to it, viewer.js (the same data as a script so the
    page also works when opened straight from disk)."""
    data = build_viewer_data(pairs)
    text = dumps(data)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")
    out_path.with_suffix(".js").write_text("window.HYPERBOLIC_VIEWER_DATA = " + text.rstrip("\n") + ";\n",
                                           encoding="utf-8")
    return data


def find_latest_pairs(runs_dir: Path, scenarios: list[str] | None = None,
                      prefer_simulator: str | None = None) -> list[tuple[Path, Path]]:
    """Latest complete baseline and agent run per scenario, matched on simulator kind."""
    found: dict[tuple[str, str, str], tuple[str, Path]] = {}
    if not runs_dir.exists():
        return []
    for d in sorted(p for p in runs_dir.iterdir() if (p / "result.json").exists()):
        m = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
        if scenarios and m["scenario"] not in scenarios:
            continue
        key = (m["scenario"], m["mode"], m["simulator"].get("kind", ""))
        stamp = m.get("started_at", "")
        if key not in found or stamp >= found[key][0]:
            found[key] = (stamp, d)
    pairs = []
    for sc in tc.SCENARIOS:
        for sim in ([prefer_simulator] if prefer_simulator else ["boptest", "mock"]):
            b, a = found.get((sc, "baseline", sim)), found.get((sc, "agent", sim))
            if b and a:
                pairs.append((b[1], a[1]))
                break
    return pairs
