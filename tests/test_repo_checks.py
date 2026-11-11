import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def commit(login, email="x@example.com", message="Add thing"):
    return {"sha": "a" * 40, "author": {"login": login} if login else None,
            "commit": {"author": {"email": email}, "message": message}}


def test_author_check_accepts_addisontech():
    ca = load("check_authors")
    assert ca.problems(commit("AddisonTech")) == []
    assert ca.problems(commit(None, email="stalor54@yahoo.com")) == []


def test_author_check_rejects_others_and_trailers():
    ca = load("check_authors")
    assert ca.problems(commit("someone-else"))
    assert ca.problems(commit(None, email="bot@example.com"))
    assert ca.problems(commit("AddisonTech", message="Fix\n\nCo-authored-by: X <x@y>"))
    assert ca.problems(commit("AddisonTech", message="Fix\n\nSigned-off-by: X <x@y>"))


def test_repo_rules_pass():
    assert load("check_repo").main() == 0


def test_heading_slugs_match_github():
    cr = load("check_repo")
    assert cr.slug("Version 0.15.0: rules in words") == "version-0150-rules-in-words"
    assert cr.slug("Tuning without peeking at the test month") == "tuning-without-peeking-at-the-test-month"
    assert cr.slug("Version 0.8.0") == "version-080"


def _tree(tmp_path, readme, extra=None):
    (tmp_path / "docs" / "assets").mkdir(parents=True)
    for name in ("ladder.png", "viewer.gif"):
        (tmp_path / "docs" / "assets" / name).write_bytes(b"x")
    (tmp_path / "pyproject.toml").write_text('version = "9.9.9"\n', encoding="utf-8")
    (tmp_path / "README.md").write_text(readme, encoding="utf-8")
    for rel in ("HOLDOUT.md", "CHANGELOG.md", "docs/HISTORY.md", "docs/HOLDOUT_RESULTS.md", "docs/LIMITS.md"):
        (tmp_path / rel).write_text("# T\n", encoding="utf-8")
    (tmp_path / "docs" / "DESIGN.md").write_text("# Design\n\n## Watch it live\n\n```\n## not a heading\n```\n",
                                                 encoding="utf-8")
    for rel, text in (extra or {}).items():
        (tmp_path / rel).write_text(text, encoding="utf-8")
    return tmp_path


GOOD_README = ("# X\n[![v](https://img.shields.io/badge/version-9.9.9-informational.svg)](CHANGELOG.md)\n"
               "![a](docs/assets/ladder.png)\n![b](docs/assets/viewer.gif)\n"
               "[live](docs/DESIGN.md#watch-it-live) [web](https://example.com/#x) [top](#x)\n")


def test_link_and_readme_checks_pass_a_good_tree(tmp_path):
    cr = load("check_repo")
    root = _tree(tmp_path, GOOD_README)
    assert cr.link_errors(root) == []
    assert cr.readme_errors(root) == []


def test_link_check_catches_missing_files_and_headings(tmp_path):
    cr = load("check_repo")
    root = _tree(tmp_path, GOOD_README, {"docs/LIMITS.md": "# L\n[a](HISTORY.md#gone) [b](NOPE.md) [c](#l)\n",
                                         "HOLDOUT.md": "# H\n[d](docs/DESIGN.md#not-a-heading)\n"})
    errors = cr.link_errors(root)
    assert any("HISTORY.md#gone" in e and "no such heading" in e for e in errors)
    assert any("NOPE.md" in e and "no such file" in e for e in errors)
    assert any("not-a-heading" in e for e in errors)  # a heading inside a code fence is not an anchor
    assert len(errors) == 3


def test_readme_check_catches_length_images_and_version(tmp_path):
    cr = load("check_repo")
    long_readme = GOOD_README + "line\n" * 200
    assert any("lines" in e for e in cr.readme_errors(_tree(tmp_path / "a", long_readme)))
    no_gif = GOOD_README.replace("![b](docs/assets/viewer.gif)\n", "")
    assert any("viewer.gif" in e for e in cr.readme_errors(_tree(tmp_path / "b", no_gif)))
    root = _tree(tmp_path / "c", GOOD_README)
    (root / "docs" / "assets" / "ladder.png").unlink()
    assert any("ladder.png: missing" in e for e in cr.readme_errors(root))
    old_badge = GOOD_README.replace("version-9.9.9-", "version-9.9.8-")
    assert any("version badge" in e for e in cr.readme_errors(_tree(tmp_path / "d", old_badge)))


def _run(root, rel, kind="live"):
    folder = root / rel
    folder.mkdir(parents=True)
    supervisor = {"kind": kind} if kind else None
    (folder / "manifest.json").write_text(json.dumps({"mode": "agent", "supervisor": supervisor}), encoding="utf-8")


RUN_A = "runs/live/x_agent_citylearn_20261023T184434Z"
RUN_B = "runs/v12/x_agent_citylearn_20261110T210024Z"
RUN_C = "runs/v9haiku/x_agent_citylearn_20261110T210024Z"  # same folder name as RUN_B


def test_run_record_check_skips_when_runs_is_not_on_disk(tmp_path):
    cr = load("check_repo")
    (tmp_path / "CHANGELOG.md").write_text("# C\n", encoding="utf-8")
    assert cr.run_record_errors(tmp_path) == []
    (tmp_path / "runs").mkdir()
    (tmp_path / "runs" / "UNPUBLISHED.md").write_text("# U\n", encoding="utf-8")
    assert cr.run_record_errors(tmp_path) == []  # runs/ holding only the list, as in a fresh clone


def test_run_record_check_fails_on_a_run_missing_from_both(tmp_path):
    cr = load("check_repo")
    _run(tmp_path, RUN_A)
    (tmp_path / "CHANGELOG.md").write_text("# C\n", encoding="utf-8")
    errors = cr.run_record_errors(tmp_path)
    assert errors == [f"{RUN_A}: live run not named in CHANGELOG.md or listed in runs/UNPUBLISHED.md"]
    (tmp_path / "runs" / "UNPUBLISHED.md").write_text("| Run | Reason |\n|---|---|\n| `runs/live/other` | x |\n",
                                                      encoding="utf-8")
    assert cr.run_record_errors(tmp_path) == errors


def test_run_record_check_accepts_the_changelog_or_the_list(tmp_path):
    cr = load("check_repo")
    _run(tmp_path, RUN_A)
    _run(tmp_path, RUN_B)
    _run(tmp_path, "runs/rule/x_agent_citylearn_20261022T162847Z", kind="scripted")  # not live: not checked
    _run(tmp_path, "runs/x_baseline_citylearn_20261021T000000Z", kind=None)  # baseline: not checked
    (tmp_path / "CHANGELOG.md").write_text(f"# C\n\n| `{RUN_A}` | 0.11.0 |\n", encoding="utf-8")
    (tmp_path / "runs" / "UNPUBLISHED.md").write_text(
        f"| Run folder | Reason |\n|---|---|\n| `{RUN_B}` | 24-hour smoke test, never reported |\n", encoding="utf-8")
    assert cr.run_record_errors(tmp_path) == []


def test_run_record_check_names_runs_by_path_and_wants_a_reason(tmp_path):
    cr = load("check_repo")
    _run(tmp_path, RUN_B)
    _run(tmp_path, RUN_C)
    (tmp_path / "CHANGELOG.md").write_text(f"# C\n\n`{RUN_B}`\n", encoding="utf-8")
    # The same folder name under another subfolder is a different run.
    assert cr.run_record_errors(tmp_path) == [f"{RUN_C}: live run not named in CHANGELOG.md or listed in runs/UNPUBLISHED.md"]
    (tmp_path / "runs" / "UNPUBLISHED.md").write_text(f"| `{RUN_C}` |  |\n| `{RUN_B}` | reported too |\n",
                                                      encoding="utf-8")
    errors = cr.run_record_errors(tmp_path)
    assert f"{RUN_C}: listed in runs/UNPUBLISHED.md without a reason" in errors
    assert f"{RUN_B}: named in CHANGELOG.md and also listed in runs/UNPUBLISHED.md" in errors
    assert len(errors) == 2
    # A longer path that merely starts with a run's path does not name it.
    (tmp_path / "runs" / "UNPUBLISHED.md").unlink()
    (tmp_path / "CHANGELOG.md").write_text(f"# C\n\n`{RUN_B}_copy` `{RUN_C}`\n", encoding="utf-8")
    assert cr.run_record_errors(tmp_path) == [f"{RUN_B}: live run not named in CHANGELOG.md or listed in runs/UNPUBLISHED.md"]


def test_run_record_check_reports_an_unreadable_manifest(tmp_path):
    cr = load("check_repo")
    folder = tmp_path / RUN_A
    folder.mkdir(parents=True)
    (folder / "manifest.json").write_text("{not json", encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text("# C\n", encoding="utf-8")
    assert any("cannot be read" in e for e in cr.run_record_errors(tmp_path))


def test_lost_line_check():
    cm = load("check_moved")
    old = "# A\n\n## How to run it\n\nSee [here](#x).\n| a | b |\nkept\n"
    new = ["# A\n## Run it\n", "### See [here](OTHER.md#x).\n| a | b |\nkept\n"]
    assert cm.lost_lines(old, new) == []
    assert cm.lost_lines(old + "dropped line\n", new) == [(8, "dropped line")]
    assert cm.lost_lines(old.replace("kept", "kept, changed"), new) == [(7, "kept, changed")]
