"""The month set (0.10.0): the reported phase 2 month plus every month of the tuning dataset kept
locally, each run as its own episode, and the compare report across them.

  phase2      citylearn_challenge_2023_phase_2_local_evaluation, shipped in hyperbolic/data
  tuning-06   June, July and August of citylearn_challenge_2023_phase_2_online_evaluation_1 from
  tuning-07   CityLearn v3.0.2, kept unchanged in scripts/tuning_data. The same three buildings,
  tuning-08   batteries and LSTM models, other weather, loads, solar, carbon and tariff.

A tuning month is written out as its own dataset folder (its rows of every series, the LSTM models,
and a schema that ends at its last hour), so CityLearn runs it exactly as scripts/tune_strategy.py
always has. Every KPI is CityLearn's own, normalized against the no-control run of the same month.

The holdout (0.11.0, see HOLDOUT.md) is kept apart from the month set: Buildings 4, 5 and 6 of
citylearn_challenge_2023_phase_3_1, June, July and August, each its own episode (holdout-06,
holdout-07, holdout-08). months() never lists it, so nothing that searches or reports the month set
sees it, and scoring it needs final=True (the --holdout-final flag) on files whose hashes still match
the seal.
"""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from . import district as dc

ROOT = Path(__file__).resolve().parents[1]
TUNING_DATASET = ROOT / "scripts" / "tuning_data" / "citylearn_challenge_2023_phase_2_online_evaluation_1"
SERIES = ("Building_1.csv", "Building_2.csv", "Building_3.csv", "carbon_intensity.csv", "pricing.csv", "weather.csv")
SHARED_SERIES = ("carbon_intensity.csv", "pricing.csv", "weather.csv")
PHASE2 = "phase2"

HOLDOUT_DATASET = ROOT / "holdout" / "citylearn_challenge_2023_phase_3_1"
HOLDOUT_BUILDINGS = ("Building_4", "Building_5", "Building_6")
HOLDOUT_FLAG = "--holdout-final"
# The seal: sha256 of every holdout file as copied from CityLearn v3.0.2, text files with LF line
# endings so a Windows checkout hashes the same as Linux.
HOLDOUT_SHA256 = {
    "Building_1.csv": "a7b27f4a3622305e60da0a32a92d468563705f69ebdec2c13d0dc6b2fd705ac1",
    "Building_1.pth": "15e137b9e1930370708346d1298ca1f8b937cdb7c8e47e43f2555e543528d394",
    "Building_2.csv": "2993728aaf8e270abaa90f08a7aec4e66f584f58927ce6d6dfe5d9582929e109",
    "Building_2.pth": "36515f53e995061148697327ee416ed305c756418584f430597616399342a0a3",
    "Building_3.csv": "aca204f9943850e794021450a23ed97407a9fed07fc43c6b14123e6c7667ab0a",
    "Building_3.pth": "42d10bf54ea210d0626d1d55568f0ad7a0b9fb600f5e2802420a3a4d77168794",
    "Building_4.csv": "89d94801d834ce1409ca360b661357176a73834a9f5a90b2345528ba320bd956",
    "Building_4.pth": "4eabbb6c24e2c0482c55768541dce6c1f75e5aedcbaf01ae5c8786177a96d974",
    "Building_5.csv": "9c5a9a91dd4cb22ffa96c0dad75a995f33a6cda95cab1fd3dfafbf5e2e1da672",
    "Building_5.pth": "f0e39abe58629e28d9cbaf8ffdadf41163aa97a0ec5763608d3028c1e47b22ae",
    "Building_6.csv": "ecc75e8eb17a4b9e6d28e90cfc8892a596b18197e9d84bbb492b1c050b93bf71",
    "Building_6.pth": "d349f9cf27c6ebad5a226c81e7729c0050bdb974793acfbd1cfbf1ff600ee2b6",
    "carbon_intensity.csv": "f106216393efe4eee30a5b85823f1fddff2676a09a58a3f63cd28482220516ad",
    "pricing.csv": "f06036bdb7b72d4bf13547da6f8453ab9f7095c5fabcf2b6929f93a79e1d0126",
    "schema.json": "500bdd747f45d8b63295a5ce7ee557ffda930d25210c32c591ef15d23e3306af",
    "weather.csv": "aeb1420f6102c5df2bddc55f211d41cf16e5f572a6fcce3cce8ad37b007875ce",
}


class HoldoutSealed(ValueError):
    """The holdout was asked for without --holdout-final, or its files no longer match the seal."""

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
    rows: tuple[int, int] | None = None  # the source dataset's rows [start, end) for a tuning or holdout month
    source: Path | None = None           # that dataset's folder (the tuning dataset when None)
    buildings: tuple[str, ...] | None = None  # the buildings kept from it (all of them when None)
    holdout: bool = False


def _spans(dataset: Path, building: str = "Building_1") -> list[tuple[str, int, int]]:
    if not (dataset / f"{building}.csv").exists():
        return []
    with (dataset / f"{building}.csv").open(encoding="utf-8") as f:
        months = [row["month"] for row in csv.DictReader(f)]
    spans, start = [], 0
    for i in range(1, len(months) + 1):
        if i == len(months) or months[i] != months[start]:
            spans.append((months[start], start, i))
            start = i
    return spans


def _tuning_spans() -> list[tuple[str, int, int]]:
    return _spans(TUNING_DATASET)


def months() -> list[Month]:
    """The phase 2 month, then every tuning month available locally. Never the holdout."""
    out = [Month(PHASE2, dc.DATASET, "phase 2")]
    for month, a, b in _tuning_spans():
        key = f"tuning-{int(month):02d}"
        out.append(Month(key, f"{TUNING_DATASET.name}_month_{int(month):02d}", key, (a, b)))
    return out


def holdout_months() -> list[Month]:
    """The sealed holdout months, kept out of months()."""
    out = []
    for month, a, b in _spans(HOLDOUT_DATASET, HOLDOUT_BUILDINGS[0]):
        key = f"holdout-{int(month):02d}"
        out.append(Month(key, f"{HOLDOUT_DATASET.name}_buildings_4_5_6_month_{int(month):02d}", key, (a, b),
                         HOLDOUT_DATASET, HOLDOUT_BUILDINGS, True))
    return out


def all_months() -> list[Month]:
    return months() + holdout_months()


def month(key: str) -> Month:
    for m in all_months():
        if m.key == key:
            return m
    raise ValueError(f"unknown month {key!r}; available: {', '.join(m.key for m in all_months())}")


def is_holdout(name: str | None) -> bool:
    """Whether a month key or a recorded dataset name is a holdout month."""
    return any(name in (m.key, m.dataset) for m in holdout_months())


def _file_sha256(path: Path) -> str:
    data = path.read_bytes()
    if path.suffix in (".csv", ".json"):
        data = data.replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def check_sealed(folder: Path = HOLDOUT_DATASET) -> None:
    """Raise HoldoutSealed unless every holdout file is present and matches the seal."""
    bad = [name for name, sha in sorted(HOLDOUT_SHA256.items())
           if not (folder / name).exists() or _file_sha256(folder / name) != sha]
    extra = sorted(p.name for p in folder.iterdir() if p.name not in HOLDOUT_SHA256) if folder.exists() else []
    if bad or extra:
        raise HoldoutSealed(f"holdout files do not match the seal in HOLDOUT.md: {', '.join(bad + extra)}")


def guard(names=(), final: bool = False) -> None:
    """Refuse to score a holdout month (key or dataset name) unless final, and only on sealed files."""
    held = sorted({n for n in names if is_holdout(n)})
    if not held:
        return
    if not final:
        raise HoldoutSealed(f"{', '.join(held)} is the sealed holdout; it is scored once, for the final "
                            f"result, with {HOLDOUT_FLAG} (see HOLDOUT.md)")
    check_sealed()


def month_schema(m: Month, out: Path) -> Path:
    """The schema CityLearn runs for month m. A tuning or holdout month is written into out/<key>,
    with only its own buildings."""
    if m.rows is None:
        return dc.schema_path()
    src = m.source or TUNING_DATASET
    a, b = m.rows
    d = Path(out) / m.key
    d.mkdir(parents=True, exist_ok=True)
    series = SERIES if m.buildings is None else (*(f"{x}.csv" for x in m.buildings), *SHARED_SERIES)
    for name in series:
        lines = (src / name).read_text(encoding="utf-8").splitlines(keepends=True)
        (d / name).write_text("".join([lines[0], *lines[1 + a:1 + b]]), encoding="utf-8")
    for pth in src.glob("*.pth"):
        if m.buildings is None or pth.stem in m.buildings:
            shutil.copy(pth, d / pth.name)
    schema = json.loads((src / "schema.json").read_text(encoding="utf-8"))
    if m.buildings is not None:
        schema["buildings"] = {k: v for k, v in schema["buildings"].items() if k in m.buildings}
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


def run_month(job: tuple) -> dict:
    """job: (controller key, month key, scratch folder[, final]). One CityLearn episode, no model calls.
    A holdout month needs final True."""
    import torch

    torch.set_num_threads(1)  # one simulation per process
    from .envelope import Envelope
    from .model import Budget, ScriptedSupervisor
    from .runner import AgentController, BaselineController, NullWriter, controller_settings, run_session
    from .sim import CityLearnSimulator

    kind, key, scratch = job[:3]
    guard([key], final=bool(job[3]) if len(job) > 3 else False)
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


def recorded_run(run_dir: Path, final: bool = False) -> dict:
    """A finished run's KPIs for the report, placed at the month its manifest records. A run on a
    holdout month needs final True."""
    m = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    by_dataset = {x.dataset: x.key for x in all_months()}
    if m.get("dataset") not in by_dataset:
        raise ValueError(f"{run_dir.name}: dataset {m.get('dataset')!r} is not in the month set")
    guard([m["dataset"]], final)
    r = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
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
    keys = [m.key for m in all_months()]
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
    cols = [m.key for m in all_months() if any(m.key in by_month for by_month in rep.values())] + ["mean"]
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
