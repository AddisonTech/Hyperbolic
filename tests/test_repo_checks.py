import importlib.util
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
