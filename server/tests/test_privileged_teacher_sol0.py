"""Adversarial witnesses for the adaptive full-information Sol0 boundary."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import stat
import subprocess
import tempfile

import pytest

from shengji.ai.heuristic import HeuristicBot
from shengji.rl import privileged_teacher_full_ab as full
from shengji.rl import privileged_teacher_sol0 as sol0


_SECRET = b"pt-full-private-seed-material!!!"
assert len(_SECRET) == 32


def _root():
    design = full.FullABDesign(
        seed_commitment_sha256=hashlib.sha256(_SECRET).hexdigest(),
        execution_git="a" * 40,
        native_sha256="b" * 64,
        hostname=full.MINI_HOSTNAME,
    )
    coordinate = design.root_coordinates[0]
    return coordinate, full._build_root(design, _SECRET, *coordinate)


def _session() -> sol0.Sol0GameSession:
    coordinate, root = _root()
    return sol0.Sol0GameSession(
        root, treatment_team=root.banker % 2, seed_secret=_SECRET,
        coordinate=coordinate, role="banker-team")


def _play_request(observation: dict[str, object], index: int = 0) \
        -> dict[str, object]:
    return {
        "op": "play",
        "decision_sha256": observation["decision_sha256"],
        "candidate_index": index,
        "confidence": "low",
    }


def test_observe_exposes_exact_world_but_public_outcome_schema_does_not():
    session = _session()
    observed = session.observe()
    assert observed["hands_by_seat"] == [
        sorted(hand) for hand in session.rnd.hands]
    assert observed["hidden_burial"] == sorted(session.rnd.buried)
    assert len(observed["candidates"]) >= 2
    assert observed["candidates"][0]["is_candidate_zero"] is True

    fields = set(sol0.Sol0Outcome.__dataclass_fields__)
    assert not fields.intersection({
        "hands", "hands_by_seat", "buried", "hidden_burial",
        "model_output", "events", "candidates"})


def test_rollout_deduplicates_exact_candidate_continuation_pairs(monkeypatch):
    session = _session()
    observed = session.observe()
    calls: list[tuple[int, str]] = []

    def evaluate(index: int, continuation: str) -> dict[str, object]:
        calls.append((index, continuation))
        return {
            "candidate_index": index,
            "continuation": continuation,
            "attacker_points": 80,
            "signed_level_utility": 1,
            "exact_endgame_calls": 0,
            "exact_endgame_nodes": 0,
        }

    monkeypatch.setattr(session, "_evaluate", evaluate)
    request = {
        "op": "rollout",
        "decision_sha256": observed["decision_sha256"],
        "candidate_indices": [0, 1],
        "continuations": ["heuristic-all", "smart-all"],
    }
    first = session.rollout(request)
    second = session.rollout(request)
    assert len(calls) == 4
    assert first["new_evaluations"] == 4
    assert second["new_evaluations"] == 0
    assert second["cached_evaluations"] == 4
    with pytest.raises(sol0.PrivilegedTeacherSol0RequestError,
                       match="rollout call budget exceeded"):
        session.rollout(request)


def test_rollout_per_call_cap_can_fail_before_any_evaluation():
    session = _session()
    observed = session.observe()
    assert len(observed["candidates"]) >= 4
    request = {
        "op": "rollout",
        "decision_sha256": observed["decision_sha256"],
        "candidate_indices": [0, 1, 2, 3],
        "continuations": list(sol0.CONTINUATIONS),
    }
    with pytest.raises(sol0.PrivilegedTeacherSol0RequestError,
                       match="rollout per-call budget exceeded"):
        session.rollout(request)
    assert session.failed is None

    malformed = dict(request)
    malformed["candidate_indices"] = [{}]
    with pytest.raises(sol0.PrivilegedTeacherSol0RequestError,
                       match="rollout request shape drift"):
        session.rollout(malformed)
    assert session.failed is None


def test_play_is_bound_to_observation_and_exact_ballot():
    session = _session()
    with pytest.raises(sol0.PrivilegedTeacherSol0Error,
                       match="play requires current observation"):
        session.play({
            "op": "play",
            "decision_sha256": session._decision_sha256,
            "candidate_index": 0,
            "confidence": "low",
        })

    session = _session()
    observed = session.observe()
    with pytest.raises(sol0.PrivilegedTeacherSol0Error,
                       match="play candidate outside ballot"):
        session.play(_play_request(observed, 10_000))


def test_file_mailbox_round_trip_uses_controller_owned_state(tmp_path: Path):
    del tmp_path
    session = _session()
    with tempfile.TemporaryDirectory(dir="/tmp") as raw:
        mailbox_path = Path(raw) / "controller-mailbox"
        with sol0.Sol0ToolServer(mailbox_path, session):
            response = sol0.tool_request(mailbox_path, {"op": "observe"})
            rejected = sol0.tool_request(mailbox_path, {
                "op": "rollout",
                "decision_sha256": response["decision_sha256"],
                "candidate_indices": [0, 1, 2, 3],
                "continuations": list(sol0.CONTINUATIONS),
            })
            after = sol0.tool_request(mailbox_path, {"op": "observe"})
        assert not mailbox_path.exists()
    assert response["status"] == "decision"
    assert rejected == {
        "status": "error", "error": "rollout per-call budget exceeded"}
    assert after["status"] == "decision"
    assert session.failed is None
    assert session._telemetry["rejected_tool_calls"] == 1
    assert response["hands_by_seat"] == [
        sorted(hand) for hand in session.rnd.hands]


def test_successful_external_session_finishes_round_and_seals_private_evidence(
        monkeypatch, tmp_path: Path):
    def verified(bot):
        bot.rollouts = getattr(bot, "rollouts", 0) + 3
        return 3

    monkeypatch.setattr(full, "_verify_decision_work", verified)
    session = _session()
    session._opponents = [HeuristicBot() for _ in range(4)]
    private = tmp_path / "private.json"
    tool_script = Path(__file__)

    def planner(control, *, final_output_path, **_kwargs):
        rolled = False
        completion_token = None
        while not control.complete:
            observed = control.observe()
            if observed["status"] == "round_end":
                break
            if not rolled:
                control.rollout({
                    "op": "rollout",
                    "decision_sha256": observed["decision_sha256"],
                    "candidate_indices": [0],
                    "continuations": ["heuristic-all"],
                })
                rolled = True
            played = control.play(_play_request(observed))
            completion_token = played.get("completion_token") or \
                completion_token
        final_output_path.write_text(json.dumps({
            "schema": sol0.FINAL_RESPONSE_SCHEMA,
            "status": "complete",
            "completion_token": completion_token,
        }))
        return subprocess.CompletedProcess(
            args=("fake-sol",), returncode=0, stdout=b"private reasoning")

    outcome = sol0.run_sol_session(
        session, private_output=private, tool_script=tool_script,
        planner_process=planner)
    evidence = json.loads(private.read_text())
    assert session.complete
    assert outcome.model_exit_code == 0
    assert outcome.telemetry["unique_rollouts"] == 1
    assert outcome.opponent_work["rollouts"] > 0
    assert outcome.opponent_work["verified_rollouts"] == \
        outcome.opponent_work["rollouts"]
    assert evidence["schema"] == sol0.PRIVATE_EVIDENCE_SCHEMA
    assert evidence["process_error"] is None
    assert evidence["transcript"]["status"]["status"] == "round_end"
    assert stat.S_IMODE(private.stat().st_mode) == 0o600
    public = outcome.payload()
    assert set(public) == {
        "schema", "attacker_points", "signed_level_utility",
        "decision_count", "telemetry", "continuation_counts",
        "confidence_counts", "opponent_work", "transcript_sha256",
        "model_output_sha256", "model_exit_code",
        "model_wall_milliseconds"}


def test_failed_external_session_still_consumes_private_attempt(
        tmp_path: Path):
    session = _session()
    private = tmp_path / "private.json"

    def planner(_control, **_kwargs):
        return subprocess.CompletedProcess(
            args=("fake-sol",), returncode=7, stdout=b"failure details")

    with pytest.raises(sol0.PrivilegedTeacherSol0Error,
                       match="did not complete engine round"):
        sol0.run_sol_session(
            session, private_output=private, tool_script=Path(__file__),
            planner_process=planner)
    evidence = json.loads(private.read_text())
    assert evidence["process_returncode"] == 7
    assert evidence["process_error"] == (
        "Sol model process did not complete engine round")
    with pytest.raises(sol0.PrivilegedTeacherSol0Error,
                       match="slot occupied"):
        sol0.run_sol_session(
            session, private_output=private, tool_script=Path(__file__),
            planner_process=planner)


def test_timeout_preserves_partial_model_output(tmp_path: Path):
    session = _session()
    private = tmp_path / "private.json"

    def planner(_control, **_kwargs):
        raise subprocess.TimeoutExpired(
            cmd=("fake-sol",), timeout=1, output=b"partial reasoning")

    with pytest.raises(sol0.PrivilegedTeacherSol0Error,
                       match="exceeded wall deadline"):
        sol0.run_sol_session(
            session, private_output=private, tool_script=Path(__file__),
            planner_process=planner)
    evidence = json.loads(private.read_text())
    assert evidence["process_error"] == (
        "Sol model process exceeded wall deadline")
    assert evidence["model_stdout_base64"] == "cGFydGlhbCByZWFzb25pbmc="
