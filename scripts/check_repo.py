"""Repository rules that tests cannot see.

  - no em or en dash characters in any tracked text file
  - nothing that looks like an API key
  - docs/data/viewer.js holds exactly the data in docs/data/viewer.json
  - README.md is under 200 lines, shows docs/assets/ladder.png and docs/assets/viewer.gif (both on
    disk), and its version badge is the package version
  - every relative link and image in README.md, HOLDOUT.md, CHANGELOG.md and the four docs files
    (docs/HISTORY.md, docs/HOLDOUT_RESULTS.md, docs/LIMITS.md, docs/DESIGN.md) points at a file that
    exists and, where it names a heading, a heading that exists in that file
  - when runs/ is on disk, every live run folder in it (a manifest whose supervisor kind is "live") is
    either named in CHANGELOG.md by its path under runs/ (runs/live/<folder>; the path, because two
    folders in different subfolders can share a name) or listed in runs/UNPUBLISHED.md in a table row
    with a reason, and not both
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EM_DASH = chr(0x2014)
EN_DASH = chr(0x2013)
KEY_PATTERN = re.compile(r"sk-ant-[A-Za-z0-9_-]{16,}")

README_MAX_LINES = 200
README_IMAGES = ["docs/assets/ladder.png", "docs/assets/viewer.gif"]
LINKED_DOCS = ["README.md", "HOLDOUT.md", "CHANGELOG.md", "docs/HISTORY.md", "docs/HOLDOUT_RESULTS.md",
               "docs/LIMITS.md", "docs/DESIGN.md"]
LINK = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)\)")
FENCE = re.compile(r"^\s*```")


def slug(heading: str) -> str:
    """The anchor GitHub gives a heading: lower case, punctuation dropped, spaces to hyphens."""
    return re.sub(r"[^\w\- ]", "", heading.strip().lower()).replace(" ", "-")


def anchors(path: Path) -> set[str]:
    found, seen, fenced = set(), {}, False
    for line in path.read_text(encoding="utf-8").splitlines():
        if FENCE.match(line):
            fenced = not fenced
            continue
        m = None if fenced else re.match(r"^#{1,6}\s+(.*?)\s*#*\s*$", line)
        if m:
            base = slug(m.group(1))
            n = seen.get(base, 0)
            seen[base] = n + 1
            found.add(base if n == 0 else f"{base}-{n}")
    return found


def links(path: Path) -> list[tuple[int, str]]:
    out, fenced = [], False
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if FENCE.match(line):
            fenced = not fenced
            continue
        if not fenced:
            out.extend((n, m.group(1)) for m in LINK.finditer(line))
    return out


def link_errors(root: Path = ROOT) -> list[str]:
    """Every relative link in the front page and the docs it points to resolves, anchors included."""
    errors = []
    for rel in LINKED_DOCS:
        path = root / rel
        if not path.exists():
            errors.append(f"{rel}: missing")
            continue
        for n, target in links(path):
            if re.match(r"^[a-z][a-z0-9+.-]*:", target, re.I):
                continue  # http, https, mailto
            file_part, _, anchor = target.partition("#")
            dest = (path.parent / file_part).resolve() if file_part else path
            if not dest.exists():
                errors.append(f"{rel}:{n}: link to {target}: no such file")
            elif anchor and (dest.suffix != ".md" or anchor not in anchors(dest)):
                errors.append(f"{rel}:{n}: link to {target}: no such heading")
    return errors


def readme_errors(root: Path = ROOT) -> list[str]:
    errors = []
    text = (root / "README.md").read_text(encoding="utf-8")
    count = len(text.splitlines())
    if count >= README_MAX_LINES:
        errors.append(f"README.md: {count} lines, the limit is under {README_MAX_LINES}")
    targets = {t for _, t in links(root / "README.md")}
    for image in README_IMAGES:
        if not (root / image).is_file():
            errors.append(f"{image}: missing")
        if image not in targets:
            errors.append(f"README.md: does not show {image}")
    version = re.search(r'^version = "([^"]+)"', (root / "pyproject.toml").read_text(encoding="utf-8"), re.M).group(1)
    if f"badge/version-{version}-" not in text:
        errors.append(f"README.md: the version badge does not say {version}")
    return errors


UNPUBLISHED = "runs/UNPUBLISHED.md"


def live_run_folders(root: Path = ROOT) -> tuple[list[str], list[str]]:
    """Paths (runs/...) of every live run folder under runs/, and errors for manifests that cannot be read."""
    runs = root / "runs"
    if not runs.is_dir():
        return [], []
    folders, errors = [], []
    for manifest in sorted(runs.rglob("manifest.json")):
        rel = manifest.parent.relative_to(root).as_posix()
        try:
            m = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            errors.append(f"{rel}/manifest.json: cannot be read ({exc})")
            continue
        if isinstance(m, dict) and (m.get("supervisor") or {}).get("kind") == "live":
            folders.append(rel)
    return folders, errors


def unpublished_rows(root: Path = ROOT) -> dict[str, str]:
    """runs/UNPUBLISHED.md table rows: run path (first cell) to reason (last cell)."""
    path = root / UNPUBLISHED
    rows = {}
    if not path.is_file():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.lstrip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        run = cells[0].strip("`").strip()
        if run.startswith("runs/"):
            rows[run] = cells[-1] if len(cells) > 1 else ""
    return rows


def run_record_errors(root: Path = ROOT) -> list[str]:
    """Every live run on disk is accounted for: named in the CHANGELOG or listed as unpublished, with a reason."""
    folders, errors = live_run_folders(root)
    if not folders:
        return errors
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8") if (root / "CHANGELOG.md").is_file() else ""
    listed = unpublished_rows(root)
    for rel in folders:
        named = re.search(re.escape(rel) + r"(?![\w./-])", changelog) is not None
        if named and rel in listed:
            errors.append(f"{rel}: named in CHANGELOG.md and also listed in {UNPUBLISHED}")
        elif rel in listed and not listed[rel]:
            errors.append(f"{rel}: listed in {UNPUBLISHED} without a reason")
        elif not named and rel not in listed:
            errors.append(f"{rel}: live run not named in CHANGELOG.md or listed in {UNPUBLISHED}")
    return errors


def tracked_files() -> list[Path]:
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return [ROOT / line for line in out.splitlines() if line]


def main() -> int:
    errors = []
    for path in tracked_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, FileNotFoundError):
            continue
        rel = path.relative_to(ROOT)
        for n, line in enumerate(text.splitlines(), 1):
            if EM_DASH in line:
                errors.append(f"{rel}:{n}: em dash")
            if EN_DASH in line:
                errors.append(f"{rel}:{n}: en dash")
            if KEY_PATTERN.search(line):
                errors.append(f"{rel}:{n}: looks like an API key")
    data_json = ROOT / "docs/data/viewer.json"
    data_js = ROOT / "docs/data/viewer.js"
    if data_json.exists() or data_js.exists():
        prefix = "window.HYPERBOLIC_VIEWER_DATA = "
        js = data_js.read_text(encoding="utf-8") if data_js.exists() else ""
        if not js.startswith(prefix) or json.loads(js[len(prefix):].rstrip().rstrip(";")) != json.loads(
                data_json.read_text(encoding="utf-8")):
            errors.append("docs/data/viewer.js does not match docs/data/viewer.json; rerun hyperbolic compare")
    errors += readme_errors()
    errors += link_errors()
    errors += run_record_errors()
    for e in errors:
        print(e)
    print("repo checks: " + ("FAILED" if errors else "passed"))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
