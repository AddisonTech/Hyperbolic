"""Draw the README's ladder chart: cost saved against the no-control baseline on tuning July.

Every number is read from the recorded runs in runs/ (kept on this machine, not in git):

  runs/v12/months_tuning07.json   haiku v11, haiku v12, haiku v9 and v9 scripted (`hyperbolic months`)
  runs/v11/months_tuning07.json   sonnet v11, and v9 scripted again, which must agree

Each live row is also checked against its own run folder's result.json, found in its release folder
(runs/v11, runs/v12, runs/v9haiku) by its manifest (model, prompt version, tuning July, all 743
hours). Nothing is typed in by hand.

Writes docs/assets/ladder.json (the numbers and where each came from) and docs/assets/ladder.png.
tests/test_ladder_chart.py checks ladder.json against the recorded runs when they are on disk, and
against the 0.14.0 and 0.15.0 tables in docs/HISTORY.md always.

Drawing needs matplotlib, a dev tool that is not a package dependency:

    .venv\\Scripts\\python -m pip install matplotlib
    .venv\\Scripts\\python scripts\\make_ladder_chart.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "runs"
OUT_JSON = ROOT / "docs" / "assets" / "ladder.json"
OUT_PNG = ROOT / "docs" / "assets" / "ladder.png"

MONTH = "tuning-07"
DATASET_SUFFIX = "_month_07"
HOURS = 743
TITLE = "Where the savings come from"
SUBTITLE = "CityLearn 2023, one tuning month, cost_total against the no-control baseline"

# (key in the months file, bar label, model key, prompt version, months file under runs/,
#  the release folder under runs/ that holds the run the 0.14.0 and 0.15.0 tables cite)
ROWS = [
    ("haiku v11", "Haiku, no rules (v11)", "haiku", 11, "v12/months_tuning07.json", "v11"),
    ("sonnet v11", "Sonnet, no rules (v11, 0.14.0 blind)", "sonnet", 11, "v11/months_tuning07.json", "v11"),
    ("haiku v12", "Haiku, rules in words (v12)", "haiku", 12, "v12/months_tuning07.json", "v12"),
    ("haiku v9", "Haiku, rules computed in code (v9)", "haiku", 9, "v12/months_tuning07.json", "v9haiku"),
    ("v9 scripted", "v9 scripted (no model)", None, None, "v12/months_tuning07.json", None),
]


def _months_cost(path: Path, key: str) -> float:
    entry = json.loads(path.read_text(encoding="utf-8"))[key]
    month = entry[MONTH]
    if month["hours"] != HOURS:
        raise ValueError(f"{path}: {key} has {month['hours']} hours, not {HOURS}")
    return float(month["kpis"]["cost_total"])


def _run_folder(release: Path, model_key: str, prompt_version: int) -> Path:
    """The one complete tuning July run in this release folder with this model and prompt version."""
    found = []
    for manifest in release.glob("*/manifest.json"):
        m = json.loads(manifest.read_text(encoding="utf-8"))
        sup = m.get("supervisor") or {}
        if (sup.get("kind") == "live" and sup.get("model_key") == model_key
                and sup.get("prompt_version") == prompt_version
                and str(m.get("dataset", "")).endswith(DATASET_SUFFIX)):
            result = json.loads((manifest.parent / "result.json").read_text(encoding="utf-8"))
            if result.get("complete") and result.get("steps") == HOURS:
                found.append(manifest.parent)
    if len(found) != 1:
        raise ValueError(f"expected one complete {model_key} v{prompt_version} tuning July run, found {len(found)}")
    return found[0]


def collect(runs: Path = RUNS) -> dict:
    """The chart's numbers, read from the recorded runs."""
    rows = []
    for key, label, model_key, prompt_version, months_file, release in ROWS:
        cost = _months_cost(runs / months_file, key)
        if model_key is None:
            # v9 scripted is in both months files; they must agree.
            other = _months_cost(runs / "v11/months_tuning07.json", key)
            if other != cost:
                raise ValueError(f"v9 scripted differs between the months files: {cost} and {other}")
            source = "runs/v12/months_tuning07.json and runs/v11/months_tuning07.json"
        else:
            folder = _run_folder(runs / release, model_key, prompt_version)
            recorded = json.loads((folder / "result.json").read_text(encoding="utf-8"))
            run_cost = float(recorded["district_kpis"]["cost_total"])
            if run_cost != cost:
                raise ValueError(f"{key}: months file {cost} but {folder.name}/result.json {run_cost}")
            source = f"runs/{months_file} and runs/{folder.relative_to(runs).as_posix()}/result.json"
        rows.append({
            "key": key,
            "label": label,
            "cost_total": cost,
            "saved_percent": round((1.0 - cost) * 100.0, 4),
            "source": source,
        })
    return {"title": TITLE, "subtitle": SUBTITLE, "kpi": "cost_total", "month": MONTH, "rows": rows}


def draw(data: dict, out: Path = OUT_PNG) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    ink, muted, grid = "#0b0b0b", "#52514e", "#e4e3df"
    model_color, scripted_color = "#2a78d6", "#8d8c86"
    rows = data["rows"]
    n = len(rows)

    dpi = 200
    fig = plt.figure(figsize=(1600 / dpi, 760 / dpi), dpi=dpi, facecolor="white")
    ax = fig.add_axes([0.36, 0.13, 0.58, 0.64], facecolor="white")
    fig.text(0.035, 0.915, data["title"], fontsize=15, fontweight="bold", color=ink, ha="left", va="center")
    fig.text(0.035, 0.85, data["subtitle"], fontsize=9.5, color=muted, ha="left", va="center")

    ys = list(range(n))[::-1]
    top = max(r["saved_percent"] for r in rows)
    for y, r in zip(ys, rows):
        color = scripted_color if r["key"] == "v9 scripted" else model_color
        ax.barh(y, r["saved_percent"], height=0.62, color=color, edgecolor="white", linewidth=2)
        ax.text(r["saved_percent"] + top * 0.012, y, f"{r['saved_percent']:.1f}%", va="center", ha="left",
                fontsize=10, color=ink, fontweight="bold")
    ax.set_yticks(ys)
    ax.set_yticklabels([r["label"] for r in rows], fontsize=10, color=ink)
    ax.set_xlim(0, top * 1.12)
    ax.set_ylim(-0.6, n - 0.4)
    ax.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: f"{v:.0f}%"))
    ax.tick_params(axis="x", colors=muted, labelsize=8.5, length=0)
    ax.tick_params(axis="y", length=0, pad=8)
    ax.grid(axis="x", color=grid, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(grid)
    ax.set_xlabel("cost saved against the no-control baseline (1 minus cost_total)", fontsize=8.5, color=muted)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=dpi, facecolor="white")
    plt.close(fig)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--runs", type=Path, default=RUNS, help="folder holding the recorded runs")
    ap.add_argument("--check", action="store_true", help="only check docs/assets/ladder.json against the runs")
    args = ap.parse_args(argv)
    data = collect(args.runs)
    if args.check:
        same = json.loads(OUT_JSON.read_text(encoding="utf-8")) == data
        print("ladder.json " + ("matches" if same else "DOES NOT match") + " the recorded runs")
        return 0 if same else 1
    OUT_JSON.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    draw(data)
    for r in data["rows"]:
        print(f"{r['label']:<40} cost_total {r['cost_total']:.6f}  saved {r['saved_percent']:.4f}%")
    print(f"wrote {OUT_JSON.relative_to(ROOT)} and {OUT_PNG.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
