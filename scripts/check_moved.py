"""Check that the 0.15.1 front page rebuild lost no line of the old README.

0.15.1 moved most of README.md into docs/HISTORY.md, docs/HOLDOUT_RESULTS.md, docs/LIMITS.md and
docs/DESIGN.md. This reads README.md as it stood at the old revision (b94aac8, 0.15.0, by default)
and checks that every non-blank line of it is in the new README.md or one of those four files.

Two things are allowed to differ, and nothing else:
  - link targets, because links were repointed at the file a heading moved to: "[text](target)"
    is compared as "[text]()"
  - heading levels, because a section became its own file: leading "#" marks are ignored
One heading was renamed and is listed in RENAMED, which the report prints.

    python scripts/check_moved.py [OLD_REVISION]

It needs the old revision in git, so it runs on a full clone, not on CI's shallow checkout.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OLD_REVISION = "b94aac8"
NEW_FILES = ["README.md", "docs/HISTORY.md", "docs/HOLDOUT_RESULTS.md", "docs/LIMITS.md", "docs/DESIGN.md"]
RENAMED = {"How to run it": "Run it"}
TARGET = re.compile(r"\]\([^)\s]*\)")


def normalize(line: str) -> str:
    line = TARGET.sub("]()", line.strip())
    return re.sub(r"^#{1,6}\s+", "", line)


def lost_lines(old_text: str, new_texts: list[str]) -> list[tuple[int, str]]:
    have = {normalize(line) for text in new_texts for line in text.splitlines()}
    lost = []
    for n, line in enumerate(old_text.splitlines(), 1):
        if not line.strip():
            continue
        key = normalize(line)
        if key in have or RENAMED.get(key) in have:
            continue
        lost.append((n, line))
    return lost


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    rev = argv[0] if argv else OLD_REVISION
    old = subprocess.run(["git", "show", f"{rev}:README.md"], cwd=ROOT, capture_output=True, text=True,
                         encoding="utf-8", check=True).stdout
    news = [(ROOT / f).read_text(encoding="utf-8") for f in NEW_FILES]
    lost = lost_lines(old, news)
    checked = sum(1 for line in old.splitlines() if line.strip())
    for n, line in lost:
        print(f"README.md@{rev}:{n}: not found: {line[:120]}")
    for before, after in RENAMED.items():
        print(f"renamed heading: {before!r} is now {after!r}")
    print(f"lost-line check: {checked} non-blank lines of README.md@{rev}, {len(lost)} not found in "
          + ", ".join(NEW_FILES))
    return 1 if lost else 0


if __name__ == "__main__":
    sys.exit(main())
