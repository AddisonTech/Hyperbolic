"""24 hour dry runs on CityLearn with no API calls: the action path is live end to end."""

import json

from conftest import needs_citylearn

from hyperbolic.cli import main
from hyperbolic.envelope import Envelope, EnvelopeConfig
from hyperbolic.model import Budget, CallResult, ScriptedSupervisor, observation_from_request
from hyperbolic.runner import AgentController, BaselineController, NullWriter, RunWriter, load_jsonl, replay_run, run_session

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
    sent = [s["actions"]["Building_1"]["cooling"] - s["state"]["baseline"]["Building_1"]["cooling"]
            for s in more if s["state"]["baseline"]["Building_1"]["cooling"] < 0.8]
    assert sent and min(sent) > 0.1

    def mean_indoor(steps):
        return sum(s["outcome"][b]["indoor_c"] for s in steps for b in s["outcome"]) / (3 * len(steps))

    assert mean_indoor(more) < mean_indoor(base) - 0.2 < mean_indoor(less) - 0.4
    grid = lambda steps: sum(s["outcome"][b]["grid_kwh"] for s in steps for b in s["outcome"])  # noqa: E731
    assert grid(more) > grid(base) > grid(less)


@needs_citylearn
def test_rule_policy_dry_run_and_replay(tmp_path):
    """24 hours with the rule-based policy through the full request, envelope and simulator path."""
    from hyperbolic.sim import CityLearnSimulator

    ctl = AgentController(ScriptedSupervisor(tokens=(3000, 250)), Envelope(EnvelopeConfig()), Budget(2.0))
    run_dir = tmp_path / "agent"
    res = run_session(CityLearnSimulator(control=True), ctl, RunWriter(run_dir), hours=HOURS, log=quiet,
                      sim_info={"kind": "citylearn", "control": True})
    steps = load_jsonl(run_dir / "steps.jsonl")
    assert res["steps"] == HOURS and res["fallback_steps"] == 0
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["supervisor"]["prompt_version"] == 2
    assert manifest["envelope"]["cooling_max_deviation"] == 0.15
    battery = [s["actions"][b]["battery"] for s in steps for b in s["actions"]]
    assert any(v > 0 for v in battery) and any(v < 0 for v in battery)
    socs = [s["outcome"]["Building_1"]["battery_soc"] for s in steps]
    assert max(socs) - min(socs) > 0.2
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
    # The first injected fault is a too-fast battery move at hour 31.
    assert "rate" not in {c["rule"] for c in clean_steps[31]["decision"]["clamps"]}
    assert "rate" in {c["rule"] for c in faulty_steps[31]["decision"]["clamps"]}


def test_cli_rejects_hours_citylearn_cannot_run(tmp_path, capsys):
    assert main(["run", "--scripted", "--hours", "168", "--runs-dir", str(tmp_path)]) == 2
    assert "167" in capsys.readouterr().err
    assert main(["run", "--inject-faults", "--hours", "24", "--runs-dir", str(tmp_path)]) == 2
    assert not any(tmp_path.iterdir())
