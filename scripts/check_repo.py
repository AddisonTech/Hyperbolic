"""Repository rules that tests cannot see.

  - no em dash characters in any tracked text file
  - nothing that looks like an API key
  - docs/data/viewer.js holds exactly the data in docs/data/viewer.json
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EM_DASH = chr(0x2014)
KEY_PATTERN = re.compile(r"sk-ant-[A-Za-z0-9_-]{16,}")


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
    for e in errors:
        print(e)
    print("repo checks: " + ("FAILED" if errors else "passed"))
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
