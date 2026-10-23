"""The month set (0.10.0): the reported phase 2 month plus every month of the tuning dataset kept
locally, each run as its own episode, and the compare report across them.

  phase2      citylearn_challenge_2023_phase_2_local_evaluation, shipped in hyperbolic/data
  tuning-06   June, July and August of citylearn_challenge_2023_phase_2_online_evaluation_1 from
  tuning-07   CityLearn v3.0.2, kept unchanged in scripts/tuning_data. The same three buildings,
  tuning-08   batteries and LSTM models, other weather, loads, solar, carbon and tariff.

A tuning month is written out as its own dataset folder (its rows of every series, the LSTM models,
and a schema that ends at its last hour), so CityLearn runs it exactly as scripts/tune_strategy.py
always has. Every KPI is CityLearn's own, normalized against the no-control run of the same month.
"""

from __future__ import annotations

import csv
import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from . import district as dc

TUNING_DATASET = (Path(__file__).resolve().parents[1] / "scripts" / "tuning_data"
                  / "citylearn_challenge_2023_phase_2_online_evaluation_1")
SERIES = ("Building_1.csv", "Building_2.csv", "Building_3.csv", "carbon_intensity.csv", "pricing.csv", "weather.csv")
PHASE2 = "phase2"

# The KPIs the report shows, in order.
REPORT_KPIS = ("cost_total", "carbon_emissions_total", "electricity_consumption_total", "discomfort_proportion",
               "discomfort_cold_proportion", "discomfort_hot_proportion", "ramping_average", "daily_peak_average",
               "all_time_peak_average", "daily_one_minus_load_factor_average",
               "power_outage_normalized_unserved_energy_total")


@dataclass(frozen=True)
class Month:
    key: str      # phase2, tuning-06, ...
    dataset: str  # recorded in run manifests and folder names
    label: str
    rows: tuple[int, int] | None = None  # the tuning dataset's rows [start, end) for a tuning month


def _tuning_spans() -> list[tuple[str, int, int]]:
    if not (TUNING_DATASET / "Building_1.csv").exists():
        return []
    with (TUNING_DATASET / "Building_1.csv").open(encoding="utf-8") as f:
        months = [row["month"] for row in csv.DictReader(f)]
    spans, start = [], 0
    for i in range(1, len(months) + 1):
        if i == len(months) or months[i] != months[start]:
            spans.append((months[start], start, i))
            start = i
    return spans


def months() -> list[Month]:
    """The phase 2 month, then every tuning month available locally."""
    out = [Month(PHASE2, dc.DATASET, "phase 2")]
    for month, a, b in _tuning_spans():
        key = f"tuning-{int(month):02d}"
        out.append(Month(key, f"{TUNING_DATASET.name}_month_{int(month):02d}", key, (a, b)))
    return out


def month(key: str) -> Month:
    for m in months():
        if m.key == key:
            return m
    raise ValueError(f"unknown month {key!r}; available: {', '.join(m.key for m in months())}")


def month_schema(m: Month, out: Path) -> Path:
    """The schema CityLearn runs for month m. A tuning month is written into out/<key>."""
    if m.rows is None:
        return dc.schema_path()
    a, b = m.rows
    d = Path(out) / m.key
    d.mkdir(parents=True, exist_ok=True)
    for name in SERIES:
        lines = (TUNING_DATASET / name).read_text(encoding="utf-8").splitlines(keepends=True)
        (d / name).write_text("".join([lines[0], *lines[1 + a:1 + b]]), encoding="utf-8")
    for pth in TUNING_DATASET.glob("*.pth"):
        shutil.copy(pth, d / pth.name)
    schema = json.loads((TUNING_DATASET / "schema.json").read_text(encoding="utf-8"))
    (d / "schema.json").write_text(json.dumps({**schema, "simulation_start_time_step": 0,
                                               "simulation_end_time_step": b - a - 1}), encoding="utf-8")
    return d / "schema.json"


def hours(m: Month) -> int:
    """Hourly decisions in month m's episode."""
    return dc.EPISODE_HOURS if m.rows is None else m.rows[1] - m.rows[0] - 1


# -- controllers and the report ----------------------------------------------------

# Offline controllers the report can run: (label, prompt version, rule-based).
CONTROLLERS = {
    "baseline": ("baseline", None, False),
    "rule": ("0.4.0 rule-based", 3, True),
    "v7": ("v7 scripted", 7, True),
    "v8": ("v8 scripted", 8, True),
}


def run_month(job: tuple[str, str, str]) -> dict:
    """job: (controller key, month key, scratch folder). One CityLearn episode, no model calls."""
    import torch

    torch.set_num_threads(1)  # one simulation per process
    from .envelope import Envelope
    from .model import Budget, ScriptedSupervisor
    from .runner import AgentController, BaselineController, NullWriter, controller_settings, run_session
    from .sim import CityLearnSimulator

    kind, key, scratch = job
    m = month(key)
    schema = month_schema(m, Path(scratch))
    if kind == "baseline":
        controller, control = BaselineController(), False
    else:
        version, cfg = controller_settings(True, CONTROLLERS[kind][1])
        controller, control = AgentController(ScriptedSupervisor(), Envelope(cfg), Budget(2.0),
                                              prompt_version=version), True
    res = run_session(CityLearnSimulator(control=control, schema=schema), controller, NullWriter(),
                      sim_info={"kind": "citylearn", "control": control}, log=lambda *_: None, dataset=m.dataset)
    k = res["district_kpis"]
    return {"controller": kind, "month": key, "hours": res["steps"], "kpis": {x: k.get(x) for x in REPORT_KPIS},
            "clamped": res["clamped_steps"], "fallback": res["fallback_steps"]}


def recorded_run(run_dir: Path) -> dict:
    """A finished run's KPIs for the report, placed at the month its manifest records."""
    m = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    r = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
    by_dataset = {x.dataset: x.key for x in months()}
    if m.get("dataset") not in by_dataset:
        raise ValueError(f"{run_dir.name}: dataset {m.get('dataset')!r} is not in the month set")
    sup = m.get("supervisor") or {}
    if sup.get("kind") == "live":
        label = f"{sup.get('model_key')} v{sup.get('prompt_version')}"
    else:
        label = f"{sup.get('kind', m.get('mode'))} v{sup.get('prompt_version', '-')}"
    if not r.get("complete"):
        label += f" ({r.get('steps')} h)"
    k = r.get("district_kpis") or {}
    return {"controller": label, "month": by_dataset[m["dataset"]], "hours": r.get("steps"),
            "kpis": {x: k.get(x) for x in REPORT_KPIS}, "clamped": r.get("clamped_steps"),
            "fallback": r.get("fallback_steps"), "cost_usd": r.get("cost_usd"), "complete": r.get("complete")}


def report(rows: list[dict]) -> dict:
    """Per controller: each month's KPIs and, when it ran every month in the report, their mean."""
    keys = [m.key for m in months()]
    out: dict = {}
    for r in rows:
        out.setdefault(r["controller"], {})[r["month"]] = r
    ran = {k for by_month in out.values() for k in by_month}
    for ctl, by_month in out.items():
        if not ran <= set(by_month):
            continue
        got = [by_month[k] for k in keys if k in by_month]
        mean = {x: (sum(g["kpis"][x] for g in got) / len(got)
                    if all(g["kpis"][x] is not None for g in got) else None) for x in REPORT_KPIS}
        by_month["mean"] = {"controller": ctl, "month": "mean", "hours": sum(g["hours"] or 0 for g in got),
                            "kpis": mean, "clamped": sum(g["clamped"] or 0 for g in got) / len(got),
                            "months": len(got)}
    return out


def table(rep: dict) -> str:
    """One block per KPI: a row per controller, a column per month and the mean."""
    cols = [m.key for m in months() if any(m.key in by_month for by_month in rep.values())] + ["mean"]
    width = max([len(c) for c in rep] + [10]) + 2
    lines = [f"{'CityLearn KPI (district)':<{width}}" + "".join(f"{c:>11}" for c in cols)]
    for x in (*REPORT_KPIS, "clamped"):
        lines.append(x)
        for ctl, by_month in rep.items():
            cells = []
            for c in cols:
                r = by_month.get(c)
                v = None if r is None else (r["clamped"] if x == "clamped" else r["kpis"][x])
                cells.append(f"{'':>11}" if v is None else f"{v:>11.1f}" if x == "clamped" else f"{v:>11.4f}")
            lines.append(f"  {ctl:<{width - 2}}" + "".join(cells))
    return "\n".join(lines)
