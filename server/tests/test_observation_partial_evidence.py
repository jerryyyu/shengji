import hashlib
import copy
import json
from collections import Counter
from pathlib import Path

import pytest

from scripts import tactical_report
from shengji.eval import tactical as T
from shengji.luna.atomic_io import partial_path


FIXTURES = Path(__file__).parent / "tactical" / "public_observations.jsonl"


@pytest.fixture(scope="module")
def cases():
    return T.load_fixtures(FIXTURES)


class FakeBot:
    def __init__(self, cases, *, fail=False):
        self.cases = cases
        self.fail = fail

    def decide_play(self, rnd, seat):
        if self.fail:
            raise RuntimeError("later-arm-failure")
        fx = next(fx for fx in self.cases
                  if fx.trick == len(rnd.history)
                  and fx.position == len(rnd.trick.plays)
                  and fx.seat == seat)
        self.last_decision_record = {
            "work_complete": True,
            "admitted": fx.observed["admitted"],
            "value_means": fx.observed["value_means"],
            "policy_log_odds_admitted": fx.observed["policy_log_odds"],
            "admitted_indices": list(range(len(fx.observed["admitted"]))),
            "selected_index": next(i for i, a in enumerate(fx.observed["admitted"])
                                   if Counter(a) == Counter(fx.observed["action"])),
            "worlds": [["private-world"]],
        }
        return fx.observed["action"]


def _argv(output, *extra):
    return ["tactical_report", "--compare-observations",
            "--ckpt", "/models/smv3out.npz",
            "--sha256", T.OBSERVATION_COMPARISON_SHA256,
            "--fixtures", str(FIXTURES), "--json", str(output), *extra]


def _fake_bots(monkeypatch, cases, *, fail_arm=None):
    constructed = []

    def fake_bot(env, *, seed):
        arm = "treatment" if env.get("SHENGJI_PV_LEAD_ANCHOR") == "1" else "control"
        constructed.append((arm, seed))
        return f"fake-{arm}", FakeBot(cases, fail=arm == fail_arm and seed == 0)

    monkeypatch.setattr(tactical_report.T, "bot_from_environ", fake_bot)
    return constructed


def test_later_arm_failure_preserves_completed_and_failed_partials(cases, tmp_path, monkeypatch):
    output = tmp_path / "comparison.json"
    _fake_bots(monkeypatch, cases, fail_arm="treatment")
    monkeypatch.setattr("sys.argv", _argv(output))

    with pytest.raises(T.TacticalError, match="not observed-only"):
        tactical_report.main()

    assert not output.exists()
    attempt = Path(f"{output}.attempt")
    records = sorted(p for p in attempt.glob("*.json") if p.name != "claim.json")
    assert [p.name for p in records] == ["000-control.json", "001-treatment.json"]
    assert json.loads(records[0].read_text())["status"] == "observed"
    failed = json.loads(records[1].read_text())
    assert failed["status"] == "ERROR"
    assert failed["comparison_complete"] is False
    assert "worlds" not in failed["decision"]


def test_complete_path_publishes_atomic_final_after_24_partials(cases, tmp_path, monkeypatch):
    output = tmp_path / "comparison.json"
    _fake_bots(monkeypatch, cases)
    monkeypatch.setattr("sys.argv", _argv(output))

    tactical_report.main()

    report = json.loads(output.read_text())
    assert report["comparison_complete"] is True
    assert len(report["results"]) == 12
    assert not partial_path(output).exists()
    attempt = Path(f"{output}.attempt")
    records = sorted(p for p in attempt.glob("*.json") if p.name != "claim.json")
    assert len(records) == 24
    assert all(p.name.split("-", 1)[0].isdigit() for p in records)
    assert all(json.loads(p.read_text())["comparison_complete"] is False for p in records)
    claim = json.loads((attempt / "claim.json").read_text())
    expected = hashlib.sha256(json.dumps(
        [fx.to_json() for fx in cases], sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    assert claim["normalized_fixture_sha256"] == expected
    assert claim["seeds"] == [0, 1, 2] and claim["fill_seed"] == 0


def test_rerun_refuses_before_bot_construction(cases, tmp_path, monkeypatch):
    output = tmp_path / "comparison.json"
    constructed = _fake_bots(monkeypatch, cases)
    monkeypatch.setattr("sys.argv", _argv(output))
    tactical_report.main()
    before = len(constructed)

    with pytest.raises(SystemExit, match="already exists"):
        tactical_report.main()
    assert len(constructed) == before


def test_coverage_failure_keeps_observations_without_success(cases, tmp_path, monkeypatch):
    output = tmp_path / "comparison.json"
    _fake_bots(monkeypatch, cases)
    from shengji.train import ballot_opportunity

    def fail_coverage(*args, **kwargs):
        raise RuntimeError("coverage-failure")

    monkeypatch.setattr(ballot_opportunity, "summarize_opportunities", fail_coverage)
    monkeypatch.setattr("sys.argv", _argv(output))

    with pytest.raises(RuntimeError, match="coverage-failure"):
        tactical_report.main()
    assert not output.exists()
    assert len([p for p in Path(f"{output}.attempt").glob("*.json")
                if p.name != "claim.json"]) == 24


@pytest.mark.parametrize("occupied", ["final", "partial", "attempt", "attempt-symlink"])
def test_existing_output_or_attempt_refuses_before_construction(cases, tmp_path, monkeypatch, occupied):
    output = tmp_path / "comparison.json"
    if occupied == "final":
        output.write_text("existing")
    elif occupied == "partial":
        partial_path(output).write_text("existing")
    elif occupied == "attempt":
        Path(f"{output}.attempt").mkdir()
    else:
        Path(f"{output}.attempt").symlink_to(tmp_path / "missing-target")
    constructed = _fake_bots(monkeypatch, cases)
    monkeypatch.setattr("sys.argv", _argv(output))

    with pytest.raises(SystemExit, match="already exists"):
        tactical_report.main()
    assert constructed == []


def test_partial_write_failure_propagates_before_next_bot(cases, tmp_path, monkeypatch):
    output = tmp_path / "comparison.json"
    constructed = _fake_bots(monkeypatch, cases)
    real_publish = tactical_report._publish_json

    def fail_partial(path, value):
        if Path(path).name != "claim.json":
            raise RuntimeError("partial-write-failure")
        real_publish(path, value)

    monkeypatch.setattr(tactical_report, "_publish_json", fail_partial)
    monkeypatch.setattr("sys.argv", _argv(output))

    with pytest.raises(RuntimeError, match="partial-write-failure"):
        tactical_report.main()
    # Two probe constructions, then only the first control decision; the
    # treatment bot is never constructed after the callback write fails.
    assert constructed == [("control", 0), ("treatment", 0), ("control", 0)]
    assert not output.exists()


@pytest.mark.parametrize("field,value", [
    ("admitted_indices", None), ("admitted_indices", [1, 1]),
    ("admitted_indices", [True, 5]), ("admitted_indices", [-1, 5]),
    ("admitted_indices", [2]), ("selected_index", 99),
    ("selected_index", True), ("selected_index", 5),
    ("value_means", None), ("value_means", [0.1]),
    ("value_means", [float("nan"), 0.1]),
    ("policy_log_odds_admitted", [float("inf"), 0.1]),
    ("policy_log_odds_admitted", [True, 0.1]),
    ("admitted", []), ("admitted", [["S6"], [None]]),
])
def test_malformed_score_join_refuses(cases, field, value):
    record = {"work_complete": True, "admitted": [["S6"], ["H6"]],
              "admitted_indices": [2, 5], "selected_index": 2,
              "value_means": [0.1, 0.2], "policy_log_odds_admitted": [0.3, 0.4]}
    result = T.Result(cases[0], ["S6"], None, "synthetic", record=record)
    T._validate_observation_telemetry(result)
    record[field] = copy.deepcopy(value)
    with pytest.raises(T.TacticalError, match="telemetry"):
        T._validate_observation_telemetry(result)


def test_missing_score_join_preserves_partial_but_never_completes(cases, tmp_path, monkeypatch):
    output = tmp_path / "comparison.json"
    constructed = _fake_bots(monkeypatch, cases)
    decide = FakeBot.decide_play

    def incomplete(self, rnd, seat):
        action = decide(self, rnd, seat)
        self.last_decision_record.pop("admitted_indices")
        return action

    monkeypatch.setattr(FakeBot, "decide_play", incomplete)
    monkeypatch.setattr("sys.argv", _argv(output))
    with pytest.raises(T.TacticalError, match="telemetry"):
        tactical_report.main()
    assert constructed == [("control", 0), ("treatment", 0), ("control", 0)]
    assert not output.exists()
    attempt = Path(f"{output}.attempt")
    assert sorted(p.name for p in attempt.glob("*.json")) == ["000-control.json", "claim.json"]
    assert json.loads((attempt / "000-control.json").read_text())["comparison_complete"] is False
