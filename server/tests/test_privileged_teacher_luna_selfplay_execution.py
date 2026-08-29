"""Synthetic two-process checks for the PT-Luna execution boundary."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import threading

import pytest

from shengji.rl import privileged_teacher_luna_selfplay as luna
from shengji.rl import privileged_teacher_luna_selfplay_execution as execution


SECRET = b"luna-self-play-secret-material!!"
TOOL = Path(__file__).parents[1] / "scripts" / "privileged_teacher_luna_selfplay_tool.py"


def _codex_stdout() -> bytes:
    return (json.dumps({"type": "thread.started", "thread_id": "fake"}) + "\n"
            + json.dumps({"type": "turn.completed", "usage": {
                "input_tokens": 10, "cached_input_tokens": 2,
                "output_tokens": 3}}) + "\n").encode()


def _game() -> luna.LunaSelfPlayGame:
    return luna.LunaSelfPlayGame(luna.build_root(SECRET, ("2", 0, 0)),
                                 coordinate=("2", 0, 0))


def _rewrite(path: Path, value: dict[str, object]) -> None:
    path.chmod(0o600)
    path.write_bytes(execution.canonical_json_bytes(value))
    path.chmod(0o400)


def _fake(session, *, mailbox_path, final_output_path, **_kwargs):
    while True:
        observed = execution.tool_request(mailbox_path, {"op": "observe"})
        if observed["status"] in ("round_end", "failed"):
            break
        if observed["status"] == "waiting":
            execution.tool_request(mailbox_path, {"op": "wait"})
            continue
        execution.tool_request(mailbox_path, {
            "op": "play", "decision_sha256": observed["decision_sha256"],
            "candidate_index": 0, "confidence": "low"})
    final_output_path.write_text(json.dumps({
        "schema": execution.FINAL_RESPONSE_SCHEMA, "status": "complete"}))
    return subprocess.CompletedProcess(("fake-luna",), 0, _codex_stdout())


def test_fake_processes_launch_concurrently_and_share_alternating_engine(tmp_path):
    game = _game()
    starts: list[int] = []
    plays: list[tuple[int, int]] = []
    lock = threading.Lock()

    def planner(session, **kwargs):
        with lock:
            starts.append(session.team)
        while True:
            observed = execution.tool_request(kwargs["mailbox_path"], {"op": "observe"})
            if observed["status"] in ("round_end", "failed"):
                break
            if observed["status"] == "waiting":
                execution.tool_request(kwargs["mailbox_path"], {"op": "wait"})
                continue
            with lock:
                plays.append((session.team, observed["acting_seat"]))
            execution.tool_request(kwargs["mailbox_path"], {
                "op": "play", "decision_sha256": observed["decision_sha256"],
                "candidate_index": 0, "confidence": "low"})
        kwargs["final_output_path"].write_text(json.dumps({
            "schema": execution.FINAL_RESPONSE_SCHEMA, "status": "complete"}))
        return subprocess.CompletedProcess(("fake-luna",), 0, _codex_stdout())

    result = execution.run_luna_game(game, private_root=tmp_path, tool_script=TOOL,
                                     planner_process=planner)
    assert result.status == "complete"
    assert set(starts) == {0, 1}
    assert {team for team, _ in plays} == {0, 1}
    assert all(seat % 2 == team for team, seat in plays)
    trajectory = json.loads((result.attempt_path / "trajectory.json").read_text())
    contested = [event for event in trajectory["events"]
                 if len(event["legal_ballot"]) > 1]
    assert [(event["team"], event["seat"]) for event in contested] == plays
    assert execution.reopen_attempt(result.attempt_path).status == "complete"


def test_forced_actions_are_engine_only_and_artifacts_reopen(tmp_path):
    game = _game()
    result = execution.run_luna_game(game, private_root=tmp_path, tool_script=TOOL,
                                     planner_process=_fake)
    assert result.status == "complete"
    assert result.trajectory_sha256
    body = json.loads((result.attempt_path / "trajectory.json").read_text())
    assert body["events"]
    assert any(len(event["legal_ballot"]) == 1 for event in body["events"])
    reopened = execution.reopen_attempt(result.attempt_path)
    assert reopened.trajectory_sha256 == result.trajectory_sha256
    assert reopened.scientific_admissible is False
    for evidence in reopened.evidence:
        assert evidence.body["execution_kind"] == execution.SYNTHETIC_EXECUTION_KIND
        assert evidence.body["synthetic"] is True
        assert evidence.body["actual_subprocess"] is False


def test_process_failure_aborts_game_and_wakes_peer(tmp_path):
    game = _game()
    barrier = threading.Barrier(2)

    def failing(session, **kwargs):
        barrier.wait()
        if session.team == 1:
            raise RuntimeError("synthetic process failure")
        return _fake(session, **kwargs)

    result = execution.run_luna_game(game, private_root=tmp_path, tool_script=TOOL,
                                     planner_process=failing)
    assert result.status == "incomplete"
    assert game.failed is not None
    assert len(result.evidence) == 2
    assert execution.reopen_attempt(result.attempt_path).status == "incomplete"
    assert not (result.attempt_path / "terminal-receipt.json").exists()


def test_tool_schema_rejects_wait_arguments(tmp_path):
    game = _game()
    mailbox = tmp_path / "mailbox"
    with execution.LunaToolServer(mailbox, game.session(game.acting_team)):
        response = execution.tool_request(mailbox, {"op": "wait", "timeout": 1})
    assert response["status"] == "error"
    assert game.failed is not None


def test_sandbox_command_binds_peer_denial_or_pins_fallback(tmp_path, monkeypatch):
    own = tmp_path / "own"
    peer = tmp_path / "peer"
    own.mkdir()
    peer.mkdir()
    profile = execution.sandbox_profile(workspace=own, peer_workspace=peer,
                                         peer_outputs=(tmp_path / "peer.trace",))
    assert str(peer) in profile
    monkeypatch.setattr(execution.sys, "platform", "darwin")
    monkeypatch.setattr(execution.shutil, "which",
                        lambda name: "/usr/bin/sandbox-exec" if name == "sandbox-exec" else None)
    command = execution.process_command(
        codex_binary=Path("/usr/bin/codex"), workspace=own,
        final_output_path=own / "final.json", peer_workspace=peer,
        sandbox_profile_path=own / "sandbox.sb")
    assert command[:3] == ("/usr/bin/sandbox-exec", "-f", str(own / "sandbox.sb"))
    if sys.platform == "darwin" and Path("/usr/bin/sandbox-exec").is_file():
        # The production path uses this same profile under the outer sandbox.
        assert "(deny file-read*" in profile


def test_supervisor_kills_fake_process_groups_on_peer_failure(tmp_path):
    game = _game()
    children: list[subprocess.Popen[bytes]] = []
    barrier = threading.Barrier(2)

    def planner(session, *, supervisor, final_output_path, **_kwargs):
        child = subprocess.Popen(("sleep", "30"), start_new_session=True)
        children.append(child)
        supervisor.register(session.team, child)
        barrier.wait()
        if session.team == 1:
            raise RuntimeError("peer failed")
        while not supervisor.aborted:
            time.sleep(0.01)
        final_output_path.write_text(json.dumps({
            "schema": execution.FINAL_RESPONSE_SCHEMA, "status": "complete"}))
        return subprocess.CompletedProcess(("fake",), 1, b"")

    import time
    result = execution.run_luna_game(game, private_root=tmp_path, tool_script=TOOL,
                                     planner_process=planner,
                                     config=execution.LunaPlannerConfig(max_game_wall_seconds=2))
    assert result.status == "incomplete"
    assert children and all(child.poll() is not None for child in children)


def test_reopen_refuses_coordinated_trace_rehash_outside_tool_contract(tmp_path):
    result = execution.run_luna_game(
        _game(), private_root=tmp_path, tool_script=TOOL,
        planner_process=_fake)
    evidence_path = result.attempt_path / "process-team-0.json"
    evidence = json.loads(evidence_path.read_text())
    event = next(row for row in evidence["trace"]
                 if row["request"]["op"] == "observe")
    event["request"]["smuggled"] = True
    event["request_sha256"] = execution._sha(event["request"])
    evidence_body = dict(evidence)
    evidence_body.pop("evidence_sha256")
    evidence["evidence_sha256"] = execution._sha(evidence_body)
    _rewrite(evidence_path, evidence)
    manifest_path = result.attempt_path / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    for row in manifest["evidence"]:
        if row["team"] == 0:
            row["evidence_sha256"] = evidence["evidence_sha256"]
    manifest_body = dict(manifest)
    manifest_body.pop("manifest_sha256")
    manifest["manifest_sha256"] = execution._sha(manifest_body)
    _rewrite(manifest_path, manifest)
    with pytest.raises(execution.LunaExecutionError,
                       match="observe/wait request"):
        execution.reopen_attempt(result.attempt_path)


def test_reopen_refuses_unbound_planner_workspace_file(tmp_path):
    result = execution.run_luna_game(
        _game(), private_root=tmp_path, tool_script=TOOL,
        planner_process=_fake)
    extra = result.attempt_path / "workspace-team-0" / "notes.txt"
    extra.write_text("not bound\n")
    with pytest.raises(execution.LunaExecutionError,
                       match="workspace file population"):
        execution.reopen_attempt(result.attempt_path)


def test_process_tree_meter_counts_only_registered_group():
    rows = (b"100 100 1024 00:01.50\n"
            b"101 100 2048 00:00.50\n"
            b"999 999 9999 00:09.00\n")
    meter = execution.ProcessTreeResourceMeter(
        sample_interval_seconds=1.0, ps_runner=lambda: rows,
        swap_reader=lambda: 0)
    meter.register(100)
    meter._sample()
    meter.unregister(100)
    receipt = meter.close()
    assert receipt["schema"] == execution.RESOURCE_SCHEMA
    assert receipt["busy_cpu_nanoseconds"] == 2_000_000_000
    assert receipt["peak_rss_bytes"] == 3 * 1024 * 1024
    assert receipt["swap_bytes"] == 0
    assert receipt["sample_count"] >= 3


def test_process_tree_meter_fails_closed_when_sampler_breaks():
    def broken():
        raise OSError("ps unavailable")
    meter = execution.ProcessTreeResourceMeter(
        sample_interval_seconds=1.0, ps_runner=broken,
        swap_reader=lambda: 0)
    meter.register(100)
    meter._sample()
    with pytest.raises(execution.LunaExecutionError, match="ps unavailable"):
        meter.close()
