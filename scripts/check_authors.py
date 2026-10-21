"""Fail if any commit in a push or pull request was not authored by AddisonTech.

Runs in GitHub Actions. Uses the GitHub API so the check is made against the
GitHub account that authored each commit, not only the name in the commit.
Also rejects co-author and sign-off trailers.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.request

ALLOWED_LOGIN = "AddisonTech"
# Used only when GitHub cannot link a commit email to an account.
ALLOWED_EMAILS = {"stalor54@yahoo.com", "223385678+addisontech@users.noreply.github.com"}
TRAILERS = re.compile(r"^\s*(co-authored-by|signed-off-by)\s*:", re.IGNORECASE | re.MULTILINE)
ZERO = "0" * 40


def api(path: str):
    req = urllib.request.Request(
        f"https://api.github.com{path}",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def commits_for_event(repo: str, event_name: str, event: dict) -> list[dict]:
    if event_name == "pull_request":
        number = event["pull_request"]["number"]
        out, page = [], 1
        while True:
            batch = api(f"/repos/{repo}/pulls/{number}/commits?per_page=100&page={page}")
            out += batch
            if len(batch) < 100:
                return out
            page += 1
    before, after = event.get("before", ZERO), event.get("after") or os.environ["GITHUB_SHA"]
    if before and before != ZERO:
        return api(f"/repos/{repo}/compare/{before}...{after}")["commits"]
    return [api(f"/repos/{repo}/commits/{after}")]


def problems(commit: dict) -> list[str]:
    sha = commit["sha"][:10]
    info = commit["commit"]
    login = (commit.get("author") or {}).get("login")
    email = (info["author"].get("email") or "").lower()
    found = []
    if login != ALLOWED_LOGIN and not (login is None and email in ALLOWED_EMAILS):
        found.append(f"{sha}: author is {login or 'unlinked'} <{email}>, expected {ALLOWED_LOGIN}")
    if TRAILERS.search(info.get("message", "")):
        found.append(f"{sha}: commit message has a co-author or sign-off trailer")
    return found


def main() -> int:
    repo = os.environ["GITHUB_REPOSITORY"]
    event_name = os.environ["GITHUB_EVENT_NAME"]
    with open(os.environ["GITHUB_EVENT_PATH"], encoding="utf-8") as f:
        event = json.load(f)
    commits = commits_for_event(repo, event_name, event)
    bad = [p for c in commits for p in problems(c)]
    for c in commits:
        print(f"{c['sha'][:10]} {(c.get('author') or {}).get('login') or 'unlinked'}: "
              f"{c['commit']['message'].splitlines()[0]}")
    if bad:
        print("\nAuthor check failed:")
        print("\n".join(f"  {b}" for b in bad))
        return 1
    print(f"\nAuthor check passed: {len(commits)} commit(s), all by {ALLOWED_LOGIN}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
