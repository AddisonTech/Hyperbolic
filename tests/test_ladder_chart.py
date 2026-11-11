"""The README's ladder chart (0.15.1): its numbers are the recorded tuning July KPIs.

docs/assets/ladder.json holds the numbers docs/assets/ladder.png is drawn from. It is checked against
the 0.14.0 and 0.15.0 tables in docs/HISTORY.md always, and against the recorded runs, which are kept
locally in runs/, when they are on disk. The README's spend figure is checked against the recorded run
costs the same way.
"""

import importlib.util
import json
import re
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LADDER = json.loads((ROOT / "docs/assets/ladder.json").read_text(encoding="utf-8"))
HISTORY = (ROOT / "docs/HISTORY.md").read_text(encoding="utf-8")
README = (ROOT / "README.md").read_text(encoding="utf-8")

# Where each bar's cost_total stands in the published tables (0.15.0 ladder, 0.14.0 blind mode).
TABLE_ROWS = {
    "haiku v11": "| Haiku v11 (no rules) | {} |",
    "sonnet v11": "| **Sonnet v11** | **{}** |",
    "haiku v12": "| **Haiku v12 (rules in words)** | **{}** |",
    "haiku v9": "| Haiku v9 (rules computed) | {} |",
    "v9 scripted": "| v9 scripted | {} |",
}


def load_script():
    spec = importlib.util.spec_from_file_location("make_ladder_chart", ROOT / "scripts/make_ladder_chart.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_ladder_order_title_and_percent():
    mod = load_script()
    assert LADDER["title"] == "Where the savings come from"
    assert LADDER["subtitle"] == "CityLearn 2023, one tuning month, cost_total against the no-control baseline"
    assert [r["key"] for r in LADDER["rows"]] == [r[0] for r in mod.ROWS]
    for r in LADDER["rows"]:
        assert r["saved_percent"] == round((1.0 - r["cost_total"]) * 100.0, 4)


def test_ladder_equals_the_published_tables():
    for r in LADDER["rows"]:
        assert TABLE_ROWS[r["key"]].format(f"{r['cost_total']:.6f}") in HISTORY, r["key"]


def test_readme_finding_uses_the_chart_percents():
    pct = {r["key"]: f"{r['saved_percent']:.1f} percent" for r in LADDER["rows"]}
    finding = README.split("## A small model with the engineering beat a big model without it.")[1].split("\n## ")[0]
    assert "](docs/assets/ladder.png)" in finding
    sentences = finding.split("\n\n")[2]
    for key in ("haiku v11", "sonnet v11", "haiku v12", "haiku v9", "v9 scripted"):
        assert pct[key] in sentences, key
    assert [p for p in re.findall(r"\d+\.\d percent", sentences)] == [
        pct["haiku v11"], pct["sonnet v11"], pct["haiku v12"], pct["haiku v9"], pct["v9 scripted"]]


RUNS = ROOT / "runs"
needs_runs = pytest.mark.skipif(not (RUNS / "v12" / "months_tuning07.json").exists(),
                                reason="the 0.13.0 to 0.15.0 runs are kept locally in runs/")


@needs_runs
def test_ladder_equals_the_recorded_runs():
    assert load_script().collect(RUNS) == LADDER


@needs_runs
def test_readme_spend_equals_the_recorded_run_costs():
    total = Decimal(0)
    count = 0
    for release in ("v10", "v11", "v12", "v9haiku"):  # 0.13.0, 0.14.0, 0.15.0 (two folders)
        for result in (RUNS / release).glob("*/result.json"):
            total += Decimal(str(json.loads(result.read_text(encoding="utf-8"))["cost_usd"]))
            count += 1
    assert count == 9
    assert f"${total.quantize(Decimal('0.0001'))}**, the sum of the nine recorded runs' costs (${total})" in README
