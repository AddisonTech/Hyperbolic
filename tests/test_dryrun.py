"""24 hour dry runs on CityLearn with no API calls: the action path is live end to end."""

import json

from conftest import needs_citylearn

from hyperbolic import district as dc
from hyperbolic.cli import main
from hyperbolic.envelope import Envelope, EnvelopeConfig
from hyperbolic.model import Budget, CallResult, ScriptedSupervisor, observation_from_request
from hyperbolic.runner import (
    AgentController,
    BaselineController,
    NullWriter,
    RunWriter,
    controller_settings,
    load_jsonl,
    replay_run,
    run_session,
)

HOURS = 24
quiet = lambda *_: None  # noqa: E731


def _run(controller, control, hours=HOURS):
    from hyperbolic.sim import CityLearnSimulator

    w = NullWriter()
    res = run_session(CityLearnSimulator(control=control), controller, w, hours=hours, log=quiet)
    return res, w.steps


class ExtraCooling:
    """Asks for the baseline cooling plus a fixed offset in every building, every hour."""

    kind = "fake"
    model_key = "haiku"

    def __init__(self, offset):
        self.offset = offset

    def call(self, step, request):
        obs = observation_from_request(request)
        reply = {"reason": "test"}
        for b, s in obs["buildings"].items():
            base = s["baseline_action"]["cooling"]
            reply[b] = {"cooling": round(min(1.0, max(0.0, base + self.offset)), 3), "dhw": 0.0, "battery": 0.0}
        return CallResult(json.dumps(reply), stop_reason="end_turn")


@needs_citylearn
def test_cooling_actions_change_the_building():
    """Would have caught a dead HVAC path: a cooling offset through the envelope moves temperatures."""
    _, base = _run(BaselineController(), False)
    env = Envelope(EnvelopeConfig(overcool_guard_unoccupied=False))
    _, more = _run(AgentController(ExtraCooling(0.15), env, Budget(1.0)), True)
    _, less = _run(AgentController(ExtraCooling(-0.15), env, Budget(1.0)), True)
    sent = [s for s in more if s["state"]["baseline"]["Building_1"]["cooling"] < 0.8]
    extra = [s["actions"]["Building_1"]["cooling"] - s["state"]["baseline"]["Building_1"]["cooling"] for s in sent]
    assert sent and sum(1 for x in extra if x > 0.1) > len(sent) / 2
    # From 0.6.0 the envelope sees the room CityLearn simulated, so once extra cooling makes it
    # cold the comfort rule holds cooling at the baseline: every hour that did not get the extra
    # cooling has a comfort clamp on it.
    for s, x in zip(sent, extra):
        if x <= 0.1:
            assert "comfort" in {c["rule"] for c in s["decision"]["clamps"] if c["point"] == "Building_1.cooling"}

    def mean_indoor(steps):
        return sum(s["outcome"][b]["indoor_c"] for s in steps for b in s["outcome"]) / (3 * len(steps))

    assert mean_indoor(more) < mean_indoor(base) - 0.2 < mean_indoor(less) - 0.4
    grid = lambda steps: sum(s["outcome"][b]["grid_kwh"] for s in steps for b in s["outcome"])  # noqa: E731
    assert grid(more) > grid(base) > grid(less)


@needs_citylearn
def test_rule_policy_dry_run_and_replay(tmp_path):
    """24 hours with the rule-based policy through the full request, envelope and simulator path."""
    from hyperbolic.sim import CityLearnSimulator

    version, cfg = controller_settings(rule_based=True)
    ctl = AgentController(ScriptedSupervisor(tokens=(3000, 250)), Envelope(cfg), Budget(2.0), prompt_version=version)
    run_dir = tmp_path / "agent"
    res = run_session(CityLearnSimulator(control=True), ctl, RunWriter(run_dir), hours=HOURS, log=quiet,
                      sim_info={"kind": "citylearn", "control": True})
    steps = load_jsonl(run_dir / "steps.jsonl")
    assert res["steps"] == HOURS and res["fallback_steps"] == 0
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["supervisor"]["prompt_version"] == 3
    assert manifest["envelope"]["peak_limit"] is True
    assert manifest["envelope"]["cooling_max_deviation"] == 0.15
    assert manifest["envelope"]["spread_check"] is False  # the frozen 0.4.0 reference
    battery = [s["actions"][b]["battery"] for s in steps for b in s["actions"]]
    assert any(v > 0 for v in battery) and any(v < 0 for v in battery)
    socs = [s["outcome"]["Building_1"]["battery_soc"] for s in steps]
    # Day one has no peak forecast yet, so the limiter allows little grid charging.
    assert max(socs) - min(socs) > 0.05
    assert all(len(s["decision"]["reason"]) <= dc.REASON_TARGET_CHARS for s in steps)
    rep = replay_run(run_dir)
    assert rep.deterministic and rep.api_calls == 0 and rep.identical_steps == HOURS


@needs_citylearn
def test_rule_policy_full_month_dry_run():
    """The whole month through prompt version 3, the envelope with the peak limiter, and replay."""
    from hyperbolic.sim import CityLearnSimulator

    hours = dc.EPISODE_HOURS
    version, cfg = controller_settings(rule_based=True)
    ctl = AgentController(ScriptedSupervisor(), Envelope(cfg), Budget(2.0), prompt_version=version)
    w = NullWriter()
    res = run_session(CityLearnSimulator(control=True), ctl, w, hours=hours, log=quiet)
    assert res["steps"] == hours and res["complete"] and res["fallback_steps"] == 0
    k = res["district_kpis"]
    # The limiter's job: no new daily or all-time peaks (to the 1e-5 the baseline action itself moves them).
    assert k["daily_peak_average"] <= 1.0 + 5e-5 and k["all_time_peak_average"] <= 1.0 + 5e-5
    assert max(len(s["decision"]["reason"]) for s in w.steps) <= dc.REASON_TARGET_CHARS
    # The rule-based reference is frozen at 0.4.0: the same cost, emissions and peaks as published.
    for key, published in (("cost_total", 0.9611), ("carbon_emissions_total", 0.9947),
                           ("daily_peak_average", 0.9978), ("ramping_average", 1.1309),
                           ("daily_one_minus_load_factor_average", 0.9913)):
        assert round(k[key], 4) == published, key
    assert res["clamped_steps"] == 1


@needs_citylearn
def test_indoor_temperature_is_the_one_citylearn_simulated():
    """Regression for the 0.4.0 mapping bug: the state showed CityLearn's indoor temperature
    observation, the dataset's no-control value for the coming hour, so the model and the
    comfort rule never saw what the heat pump actually did."""
    import pandas as pd

    env = Envelope(EnvelopeConfig(overcool_guard_unoccupied=False, cooling_max_deviation=None))
    _, less = _run(AgentController(ExtraCooling(-0.3), env, Budget(1.0)), True, hours=47)
    for b in ("Building_1", "Building_2", "Building_3"):
        dataset = pd.read_csv(dc.dataset_dir() / f"{b}.csv")["indoor_dry_bulb_temperature"]
        now = [s["state"]["buildings"][b]["indoor_c"] for s in less[1:]]
        before = [s["outcome"][b]["indoor_c"] for s in less[:-1]]
        # The temperature at the start of an hour is the one simulated for the hour before it.
        assert all(abs(x - y) < 1e-3 for x, y in zip(now, before))
        # With cooling cut by 0.3 the rooms run warmer than the no-control data says.
        warmer = [x - dataset[s["state"]["time_step"]] for x, s in zip(now, less[1:])]
        assert sum(warmer[24:]) / len(warmer[24:]) > 1.0


@needs_citylearn
def test_v4_strategy_dry_run_and_replay(tmp_path):
    """24 hours of the prompt version 4 strategy through the spread check and replay."""
    from hyperbolic.sim import CityLearnSimulator

    version, cfg = controller_settings(rule_based=False)
    ctl = AgentController(ScriptedSupervisor(), Envelope(cfg), Budget(2.0), prompt_version=version)
    run_dir = tmp_path / "v4"
    res = run_session(CityLearnSimulator(control=True), ctl, RunWriter(run_dir), hours=HOURS, log=quiet,
                      sim_info={"kind": "citylearn", "control": True})
    assert res["steps"] == HOURS and res["fallback_steps"] == 0
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["supervisor"]["prompt_version"] == 4 and manifest["envelope"]["spread_check"] is True
    calls = load_jsonl(run_dir / "calls.jsonl")
    obs = observation_from_request(calls[5]["request"])
    assert {"reference_action", "indoor_vs_setpoint_c"} <= set(obs["buildings"]["Building_1"])
    assert "reference_action" in calls[5]["request"]["system"]
    rep = replay_run(run_dir)
    assert rep.deterministic and rep.api_calls == 0 and rep.identical_steps == HOURS


@needs_citylearn
def test_cli_scripted_run_has_no_faults_unless_asked(tmp_path, capsys):
    runs = tmp_path / "runs"
    assert main(["run", "--scripted", "--hours", "40", "--runs-dir", str(runs)]) == 0
    assert main(["run", "--scripted", "--inject-faults", "--hours", "40", "--runs-dir", str(runs / "f")]) == 0
    clean = next(p for p in runs.iterdir() if "_agent_" in p.name)
    faulty = next(p for p in (runs / "f").iterdir())
    clean_steps = load_jsonl(clean / "steps.jsonl")
    faulty_steps = load_jsonl(faulty / "steps.jsonl")
    assert json.loads((clean / "result.json").read_text())["fallback_steps"] == 0
    # --scripted is the frozen 0.4.0 rule-based controller unless a prompt version is asked for.
    manifest = json.loads((clean / "manifest.json").read_text())
    assert manifest["supervisor"]["prompt_version"] == 3 and manifest["envelope"]["spread_check"] is False
    # The first injected fault is a too-fast battery move at hour 31.
    assert "rate" not in {c["rule"] for c in clean_steps[31]["decision"]["clamps"]}
    assert "rate" in {c["rule"] for c in faulty_steps[31]["decision"]["clamps"]}


def test_cli_rejects_hours_citylearn_cannot_run(tmp_path, capsys):
    assert main(["run", "--scripted", "--hours", "168", "--runs-dir", str(tmp_path)]) == 2
    assert "167" in capsys.readouterr().err
    assert main(["run", "--inject-faults", "--hours", "24", "--runs-dir", str(tmp_path)]) == 2
    assert not any(tmp_path.iterdir())
