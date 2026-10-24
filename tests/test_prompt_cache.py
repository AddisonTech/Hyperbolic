"""Prompt caching: the system prompt is a byte-identical cached prefix, the hour's state follows it,
and cache reads and writes are priced and recorded."""

import json
import re
from types import SimpleNamespace

import pytest
from fakes import BUILDINGS, FakeDistrict

from hyperbolic.envelope import Envelope
from hyperbolic.model import (
    MODELS,
    Budget,
    CallResult,
    LiveSupervisor,
    ScriptedSupervisor,
    cache_hit_rate,
    call_cost_usd,
    observation_from_request,
    worst_case_cost_usd,
)
from hyperbolic.prompt import PROMPT_VERSION, PROMPT_VERSIONS, system_text
from hyperbolic.runner import AgentController, NullWriter, RunWriter, controller_settings, load_jsonl, replay_run, run_session

quiet = lambda *_: None  # noqa: E731
# Every prompt version a run can use, written out so a new version has to be added here.
CACHED_VERSIONS = (1, 2, 3, 4, 5, 6, 7, 8, 9)


class CapturingSupervisor:
    """A fake client: keeps every request and answers with no actions."""

    kind = "fake"
    model_key = "haiku"

    def __init__(self):
        self.requests = []

    def call(self, step, request):
        self.requests.append(json.loads(json.dumps(request)))
        reply = {"reason": "hold", **{b: {"cooling": None, "dhw": None, "battery": None} for b in BUILDINGS}}
        return CallResult(json.dumps(reply), stop_reason="end_turn")


def _requests(version, hours=2):
    version, cfg = controller_settings(False, version)
    sup = CapturingSupervisor()
    ctl = AgentController(supervisor=sup, envelope=Envelope(cfg), budget=Budget(1.0), prompt_version=version)
    run_session(FakeDistrict(), ctl, NullWriter(), hours=hours, log=quiet)
    return sup.requests


@pytest.mark.parametrize("version", CACHED_VERSIONS)
def test_cache_control_is_on_the_last_block_of_the_system_prompt(version):
    req = _requests(version, hours=1)[0]
    blocks = req["system"]
    assert isinstance(blocks, list) and blocks[-1]["type"] == "text"
    assert blocks[-1]["cache_control"] == {"type": "ephemeral"}  # default 5 minute TTL
    assert all("cache_control" not in b for b in blocks[:-1])
    assert "tools" not in req  # no tools, so the system prompt ends the stable prefix
    assert "cache_control" not in json.dumps(req["messages"])  # nothing after the prefix is marked


@pytest.mark.parametrize("version", CACHED_VERSIONS)
def test_the_hours_state_comes_after_the_prefix(version):
    req = _requests(version, hours=1)[0]
    keys = list(req)
    assert keys.index("system") < keys.index("messages")
    assert [m["role"] for m in req["messages"]] == ["user"]
    obs = observation_from_request(req)  # the hour's state is in the last user message
    text = system_text(req)
    assert "OBSERVATION_JSON" not in text and json.dumps(obs) not in text
    assert not re.search(r"\d{4}-\d{2}-\d{2}|\d{2}:\d{2}:\d{2}", text)  # no dates or clock times
    assert not re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-", text)  # no run ids


@pytest.mark.parametrize("version", CACHED_VERSIONS)
def test_prefix_is_byte_identical_across_consecutive_calls(version):
    first, second = _requests(version, hours=2)
    o1, o2 = observation_from_request(first), observation_from_request(second)
    assert o1["time_step"] != o2["time_step"] and o1 != o2  # different state each hour
    for key in ("model", "system", "output_config"):
        assert json.dumps(first[key]) == json.dumps(second[key])
    assert first["messages"] != second["messages"]


def test_every_prompt_version_is_covered():
    assert CACHED_VERSIONS == PROMPT_VERSIONS


@pytest.mark.parametrize("version", sorted({8, 9, PROMPT_VERSION}))
def test_prompt_is_long_enough_to_cache(version):
    # Claude Haiku 5.5 caches a prefix of 512 tokens or more. Plain English runs about 4 characters
    # a token; 6 is a conservative bound, so this many characters is at least 512 tokens.
    text = system_text(_requests(version, hours=1)[0])
    assert len(text) >= 6 * 512


def test_prices_in_the_table():
    for p in MODELS.values():
        assert p["cache_write_per_mtok"] == pytest.approx(1.25 * p["input_per_mtok"])
        assert p["cache_read_per_mtok"] == pytest.approx(0.1 * p["input_per_mtok"])


def test_cost_of_a_call_with_cache_reads_writes_and_plain_input():
    got = call_cost_usd("haiku", 1_000, 300, cache_read_tokens=5_000, cache_write_tokens=2_000)
    want = (1_000 * 0.10 + 2_000 * 0.125 + 5_000 * 0.01 + 300 * 0.50) / 1_000_000
    assert got == pytest.approx(want)
    assert call_cost_usd("sonnet", 1_000, 300, 5_000, 2_000) == pytest.approx(
        (1_000 * 2.00 + 2_000 * 2.50 + 5_000 * 0.20 + 300 * 10.00) / 1_000_000)
    assert call_cost_usd("haiku", 1_000, 300) == pytest.approx((1_000 * 0.10 + 300 * 0.50) / 1_000_000)
    assert cache_hit_rate(1_000, 5_000, 2_000) == pytest.approx(5_000 / 8_000)
    assert cache_hit_rate(0, 0, 0) is None


def test_worst_case_prices_the_cached_prefix_as_a_write():
    req = _requests(PROMPT_VERSION, hours=1)[0]
    plain = {**req, "system": system_text(req)}
    assert worst_case_cost_usd("haiku", req) > worst_case_cost_usd("haiku", plain)


def _response(text, inp, read, write, out=200):
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        usage=SimpleNamespace(input_tokens=inp, output_tokens=out, cache_read_input_tokens=read,
                              cache_creation_input_tokens=write),
        stop_reason="end_turn",
        model="claude-haiku-5-5",
    )


def test_live_run_records_and_prices_cache_tokens(tmp_path, monkeypatch):
    monkeypatch.setenv("HYPERBOLIC_ANTHROPIC_KEY", "sk-test")
    sup = LiveSupervisor("haiku")
    reply = json.dumps({"reason": "hold", **{b: {"cooling": None, "dhw": None, "battery": None} for b in BUILDINGS}})
    # The first hour writes the prefix, the next two read it.
    seq = [_response(reply, 900, 0, 1_200), _response(reply, 950, 1_200, 0), _response(reply, 980, 1_200, 0)]
    sent = []

    def create(**kwargs):
        sent.append(kwargs)
        return seq[len(sent) - 1]

    monkeypatch.setattr(sup._client.messages, "create", create)
    version, cfg = controller_settings(False)
    ctl = AgentController(supervisor=sup, envelope=Envelope(cfg), budget=Budget(1.0), prompt_version=version)
    res = run_session(FakeDistrict(), ctl, RunWriter(tmp_path / "a"), hours=3, log=quiet)

    assert sent[0]["system"][-1]["cache_control"] == {"type": "ephemeral"}
    want = (call_cost_usd("haiku", 900, 200, 0, 1_200) + call_cost_usd("haiku", 950, 200, 1_200, 0)
            + call_cost_usd("haiku", 980, 200, 1_200, 0))
    assert res["cost_usd"] == pytest.approx(want, abs=1e-6)
    assert ctl.budget.spent_usd == pytest.approx(want)  # the cost cap charges the priced cost
    assert res["tokens"] == {"input": 2_830, "cache_read": 2_400, "cache_write": 1_200, "output": 600}
    assert res["cache_hit_rate"] == pytest.approx(2_400 / (2_830 + 2_400 + 1_200), abs=1e-4)

    calls = load_jsonl(tmp_path / "a" / "calls.jsonl")
    assert [(c["reply"]["input_tokens"], c["reply"]["cache_read_input_tokens"],
             c["reply"]["cache_creation_input_tokens"]) for c in calls] == [(900, 0, 1_200), (950, 1_200, 0),
                                                                           (980, 1_200, 0)]
    assert json.loads((tmp_path / "a" / "manifest.json").read_text(encoding="utf-8"))["supervisor"]["prompt_cache"]

    rep = replay_run(tmp_path / "a")  # replays with zero calls, cache counts and all
    assert rep.deterministic and rep.api_calls == 0
    assert rep.cost_usd == pytest.approx(want, abs=1e-6)
    assert rep.cache_hit_rate == pytest.approx(2_400 / 6_430)


def test_runs_recorded_before_caching_still_replay(tmp_path):
    ctl = AgentController(supervisor=ScriptedSupervisor(), envelope=Envelope(controller_settings(True)[1]),
                          budget=Budget(1.0), prompt_version=controller_settings(True)[0], prompt_cache=False)
    run_session(FakeDistrict(), ctl, RunWriter(tmp_path / "old"), hours=3, log=quiet)
    m_path = tmp_path / "old" / "manifest.json"
    m = json.loads(m_path.read_text(encoding="utf-8"))
    del m["supervisor"]["prompt_cache"]  # as a manifest written before caching existed
    m_path.write_text(json.dumps(m), encoding="utf-8")
    calls = load_jsonl(tmp_path / "old" / "calls.jsonl")
    assert isinstance(calls[0]["request"]["system"], str)
    assert replay_run(tmp_path / "old").deterministic
