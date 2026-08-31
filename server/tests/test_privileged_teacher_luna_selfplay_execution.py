"""Synthetic two-process checks for the PT-Luna execution boundary."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import threading
import time

import pytest

from shengji.rl import privileged_teacher_luna_selfplay as luna
from shengji.rl import privileged_teacher_luna_selfplay_execution as execution


SECRET = b"luna-self-play-secret-material!!"
TOOL = Path(__file__).parents[1] / "scripts" / "privileged_teacher_luna_selfplay_tool.py"


def _codex_stdout() -> bytes:
    return (json.dumps({"type": "thread.started", "thread_id": "fake"}) + "\n"
            + json.dumps({"type": "turn.completed", "usage": {
                "input_tokens": 10, "cached_input_tokens": 2,
                "cache_write_input_tokens": 1, "output_tokens": 3,
                "reasoning_output_tokens": 4}}) + "\n").encode()


def test_codex_0150_usage_schema_is_bound_exactly():
    assert execution._codex_jsonl_usage(_codex_stdout()) == {
        "cache_write_input_tokens": 1,
        "cached_input_tokens": 2,
        "input_tokens": 10,
        "output_tokens": 3,
        "reasoning_output_tokens": 4,
    }


def test_planner_prompt_binds_team_relative_utility_objective(tmp_path):
    prompt = execution.planner_prompt(
        mailbox_path=tmp_path / "mailbox", tool_script=TOOL)
    assert "sole objective is to" in prompt
    assert "maximize final signed-level utility" in prompt
    assert "full-information privilege" in prompt
    assert "Candidate zero is always the production prior" in prompt
    assert "defender's utility is the exact opposite" in prompt
    assert "Immediately invoke the local tool's observe command as your first action" in prompt
    assert "At every decision, call observe first" in prompt
    assert "If it reports waiting, immediately call" in prompt
    assert "A tool error changes no game state" in prompt
    assert "candidate count times continuation count must be at most 16" in prompt
    assert "Use at most two rollout commands per decision" in prompt
    assert "reports round_end" in prompt
    assert "After round_end" in prompt
    assert '"completion_token":"TOKEN"' in prompt
    for consideration in ("multi-trick control", "partnership entries",
                           "point timing", "trump exhaustion",
                           "banker defense", "attacker thresholds"):
        assert consideration in prompt


def test_production_command_binds_reviewed_inline_stop_hook(tmp_path):
    command = execution.process_command(
        codex_binary=Path("/usr/bin/codex"), workspace=tmp_path,
        final_output_path=tmp_path / "final.json",
        mailbox_path=tmp_path / "mailbox")
    assert execution.STOP_HOOK_AUTOMATION_FLAG in command
    assert "-P -B" in command[command.index("-c") + 1]
    hook_override = command[command.index("-c") + 1]
    assert hook_override.startswith("hooks.Stop=[{hooks=[{")
    assert str(execution.STOP_HOOK_SCRIPT) in hook_override
    assert str(tmp_path / "mailbox") in hook_override
    assert ".codex" not in " ".join(command)
    assert execution.STOP_HOOK_SOURCE_SHA256 == execution._sha_bytes(
        execution.STOP_HOOK_SCRIPT.read_bytes())


def test_stop_hook_command_runs_from_outside_repo_with_venv_launcher(tmp_path):
    """The production hook command must retain the venv import context."""
    python = Path(sys.executable)
    config = execution.stop_hook_config(mailbox_path=tmp_path / "mailbox",
                                        python=python)
    command = config["hooks"]["Stop"][0]["hooks"][0]["command"]
    argv = tuple(shlex.split(command))
    assert argv[0] == str(python)
    if python.is_symlink():
        assert argv[0] != str(python.resolve())
    assert argv[1:3] == ("-P", "-B")
    runtime = execution.runtime_identity(codex_binary=python,
                                         tool_script=TOOL)
    assert runtime["python_executable"] == str(python)
    assert runtime["python_sha256"] == execution._sha_bytes(
        python.read_bytes())

    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    environment.pop("SHENGJI_FAST", None)
    process = subprocess.run(
        argv, cwd=tmp_path, input=b"not-json", stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, env=environment, check=False, timeout=10)
    assert process.returncode == 0
    assert process.stderr == b""
    payload = json.loads(process.stdout)
    assert set(payload) == {"decision", "reason"}
    assert payload["decision"] == "block"
    assert type(payload["reason"]) is str
    assert len(payload["reason"]) < 200


def test_stop_hook_validator_rejects_extra_command_argv(tmp_path):
    config = execution.stop_hook_config(mailbox_path=tmp_path / "mailbox",
                                        python=Path(sys.executable))
    hook = config["hooks"]["Stop"][0]["hooks"][0]
    hook["command"] = "prefix " + hook["command"]
    with pytest.raises(execution.LunaExecutionError,
                       match="stop hook config wiring drift"):
        execution._validate_stop_hook_config(
            config, mailbox_path=tmp_path / "mailbox",
            hook_script=execution.STOP_HOOK_SCRIPT,
            python=Path(sys.executable))


def test_production_command_refuses_removed_stop_hook_wiring(tmp_path, monkeypatch):
    monkeypatch.setattr(execution, "stop_hook_config",
                        lambda **_kwargs: {"hooks": {}})
    with pytest.raises(execution.LunaExecutionError,
                       match="stop hook config schema drift"):
        execution.process_command(
            codex_binary=Path("/usr/bin/codex"), workspace=tmp_path,
            final_output_path=tmp_path / "final.json",
            mailbox_path=tmp_path / "mailbox")


def test_reviewed_stop_hook_source_refuses_link_and_changed_bytes(tmp_path):
    changed = tmp_path / "changed.py"
    changed.write_bytes(execution.STOP_HOOK_SCRIPT.read_bytes() + b"\n")
    with pytest.raises(execution.LunaExecutionError,
                       match="stop hook source hash drift"):
        execution._reviewed_stop_hook_source(hook_script=changed)

    linked = tmp_path / "linked.py"
    linked.symlink_to(execution.STOP_HOOK_SCRIPT)
    with pytest.raises(execution.LunaExecutionError,
                       match="stop hook source absent"):
        execution._reviewed_stop_hook_source(hook_script=linked)


@pytest.mark.parametrize("mutation", ("missing", "unknown"))
def test_codex_usage_schema_drift_refuses(mutation):
    usage = {key: 1 for key in execution.CODEX_USAGE_KEYS}
    if mutation == "missing":
        usage.pop("reasoning_output_tokens")
    else:
        usage["future_tokens"] = 1
    raw = (json.dumps({"type": "turn.completed", "usage": usage}) + "\n").encode()
    with pytest.raises(execution.LunaExecutionError,
                       match="token telemetry drift"):
        execution._codex_jsonl_usage(raw)


def _game() -> luna.LunaSelfPlayGame:
    return luna.LunaSelfPlayGame(luna.build_root(SECRET, ("2", 0, 0)),
                                 coordinate=("2", 0, 0))


def _rewrite(path: Path, value: dict[str, object]) -> None:
    path.chmod(0o600)
    path.write_bytes(execution.canonical_json_bytes(value))
    path.chmod(0o400)


def _downgrade_attempt_to_v1(attempt: Path, *, drop_terminal_witness: bool) -> None:
    attempt_path = attempt / "attempt.json"
    attempt_body = json.loads(attempt_path.read_text())
    attempt_body.pop("attempt_sha256")
    attempt_body["schema"] = execution.LEGACY_ATTEMPT_SCHEMA
    attempt_body.pop("private_trace_schema")
    attempt_body.pop("final_response_schema")
    attempt_body["attempt_sha256"] = execution._sha(attempt_body)
    _rewrite(attempt_path, attempt_body)

    manifest_path = attempt / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    witness_dropped = not drop_terminal_witness
    for team in luna.TEAMS:
        path = attempt / f"process-team-{team}.json"
        process = json.loads(path.read_text())
        process["schema"] = execution.LEGACY_PRIVATE_TRACE_SCHEMA
        process.pop("completion_token_sha256")
        retained = []
        for event in process["trace"]:
            terminal = event["response"].get("status") == "round_end"
            removable = (terminal and event["request"].get("op")
                         in ("observe", "wait"))
            if drop_terminal_witness and not witness_dropped and removable:
                witness_dropped = True
                continue
            if terminal:
                event["response"].pop("completion_token")
                event["response_sha256"] = execution._sha(event["response"])
            retained.append(event)
        process["trace"] = retained
        process.pop("evidence_sha256")
        process["evidence_sha256"] = execution._sha(process)
        _rewrite(path, process)
        manifest["evidence"][team]["evidence_sha256"] = process[
            "evidence_sha256"]
    assert witness_dropped
    manifest.pop("manifest_sha256")
    manifest["manifest_sha256"] = execution._sha(manifest)
    _rewrite(manifest_path, manifest)


def _fake(session, *, mailbox_path, final_output_path, **_kwargs):
    terminal = None
    while True:
        observed = execution.tool_request(mailbox_path, {"op": "observe"})
        if observed["status"] in ("round_end", "failed"):
            terminal = observed
            break
        if observed["status"] == "waiting":
            waited = execution.tool_request(mailbox_path, {"op": "wait"})
            if waited["status"] in ("round_end", "failed"):
                terminal = waited
                break
            continue
        played = execution.tool_request(mailbox_path, {
            "op": "play", "decision_sha256": observed["decision_sha256"],
            "candidate_index": 0, "confidence": "low"})
        if played["status"] in ("round_end", "failed"):
            terminal = played
            break
    assert terminal is not None and terminal["status"] == "round_end"
    final_output_path.write_text(json.dumps({
        "schema": execution.FINAL_RESPONSE_SCHEMA, "status": "complete",
        "completion_token": terminal["completion_token"]}))
    return subprocess.CompletedProcess(("fake-luna",), 0, _codex_stdout())


def test_fake_processes_launch_in_engine_turn_order_and_share_engine(tmp_path):
    game = _game()
    initial_team = game.acting_team
    starts: list[int] = []
    plays: list[tuple[int, int]] = []
    eager_nonacting_launches: list[int] = []
    lock = threading.Lock()

    def planner(session, **kwargs):
        with lock:
            starts.append(session.team)
            # This is a can-fail witness: with eager dual launch, the peer is
            # invoked while the engine still belongs to initial_team.
            if not game.complete and session.team != game.acting_team:
                eager_nonacting_launches.append(session.team)
                raise AssertionError("non-acting planner launched eagerly")
        if session.team == initial_team:
            # Keep the engine on its initial turn briefly.  An eager peer
            # launch therefore deterministically trips the witness above.
            time.sleep(0.05)
        terminal = None
        while True:
            observed = execution.tool_request(kwargs["mailbox_path"], {"op": "observe"})
            if observed["status"] in ("round_end", "failed"):
                terminal = observed
                break
            if observed["status"] == "waiting":
                waited = execution.tool_request(
                    kwargs["mailbox_path"], {"op": "wait"})
                if waited["status"] in ("round_end", "failed"):
                    terminal = waited
                    break
                continue
            with lock:
                plays.append((session.team, observed["acting_seat"]))
            played = execution.tool_request(kwargs["mailbox_path"], {
                "op": "play", "decision_sha256": observed["decision_sha256"],
                "candidate_index": 0, "confidence": "low"})
            if played["status"] in ("round_end", "failed"):
                terminal = played
                break
        assert terminal is not None and terminal["status"] == "round_end"
        kwargs["final_output_path"].write_text(json.dumps({
            "schema": execution.FINAL_RESPONSE_SCHEMA, "status": "complete",
            "completion_token": terminal["completion_token"]}))
        return subprocess.CompletedProcess(("fake-luna",), 0, _codex_stdout())

    result = execution.run_luna_game(game, private_root=tmp_path, tool_script=TOOL,
                                     planner_process=planner)
    assert result.status == "complete"
    assert eager_nonacting_launches == []
    assert starts == [initial_team, 1 - initial_team]
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


def test_generic_or_wrong_completion_response_is_diagnostic_only(tmp_path):
    def wrong_final(session, *, mailbox_path, final_output_path, **_kwargs):
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
        token = session._completion_token if session.team else "0" * 64
        final_output_path.write_text(json.dumps({
            "schema": execution.FINAL_RESPONSE_SCHEMA, "status": "complete",
            "completion_token": token}))
        return subprocess.CompletedProcess(("fake-luna",), 0, _codex_stdout())

    result = execution.run_luna_game(
        _game(), private_root=tmp_path, tool_script=TOOL,
        planner_process=wrong_final)
    assert result.status == "complete"
    assert result.scientific_admissible is False
    team0 = json.loads((result.attempt_path / "process-team-0.json").read_text())
    assert team0["process_error"] is None
    assert execution.reopen_attempt(result.attempt_path).status == "complete"


def test_absent_final_after_terminal_trace_is_complete(tmp_path):
    def absent_final(session, *, mailbox_path, **_kwargs):
        terminal = None
        while terminal is None:
            observed = execution.tool_request(mailbox_path, {"op": "observe"})
            if observed["status"] in ("round_end", "failed"):
                terminal = observed
            elif observed["status"] == "waiting":
                waited = execution.tool_request(mailbox_path, {"op": "wait"})
                if waited["status"] in ("round_end", "failed"):
                    terminal = waited
            else:
                execution.tool_request(mailbox_path, {
                    "op": "play", "decision_sha256": observed["decision_sha256"],
                    "candidate_index": 0, "confidence": "low"})
        assert terminal["status"] == "round_end"
        return subprocess.CompletedProcess(("fake-luna",), 0, _codex_stdout())

    result = execution.run_luna_game(
        _game(), private_root=tmp_path, tool_script=TOOL,
        planner_process=absent_final)
    assert result.status == "complete"
    assert all(item.body["process_error"] is None for item in result.evidence)
    assert execution.reopen_attempt(result.attempt_path).status == "complete"


def test_missing_codex_turn_completed_fails_closed(tmp_path):
    def missing_completion(session, **kwargs):
        completed = _fake(session, **kwargs)
        return subprocess.CompletedProcess(completed.args, 0,
                                            b'{"type":"thread.started"}\n')

    result = execution.run_luna_game(
        _game(), private_root=tmp_path, tool_script=TOOL,
        planner_process=missing_completion)
    assert result.status == "incomplete"
    assert any("Codex completion telemetry drift" in (item.body["process_error"] or "")
               for item in result.evidence)


def test_early_generic_final_without_terminal_trace_fails_closed(tmp_path):
    def early(_session, *, final_output_path, **_kwargs):
        final_output_path.write_text("done")
        return subprocess.CompletedProcess(("fake-luna",), 0, _codex_stdout())

    result = execution.run_luna_game(
        _game(), private_root=tmp_path, tool_script=TOOL,
        planner_process=early)
    assert result.status == "incomplete"
    assert any("terminal mailbox witness absent" in (item.body["process_error"] or "")
               for item in result.evidence)


def test_coordinated_rehash_cannot_remove_terminal_mailbox_witness(tmp_path):
    result = execution.run_luna_game(
        _game(), private_root=tmp_path, tool_script=TOOL,
        planner_process=_fake)
    assert result.status == "complete"
    manifest_path = result.attempt_path / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    mutated_team = None
    for team in luna.TEAMS:
        path = result.attempt_path / f"process-team-{team}.json"
        process = json.loads(path.read_text())
        removable = [event for event in process["trace"]
                     if event["response"].get("status") == "round_end"
                     and event["request"].get("op") in ("observe", "wait")]
        if not removable:
            continue
        process["trace"] = [event for event in process["trace"]
                            if event not in removable]
        process.pop("evidence_sha256")
        process["evidence_sha256"] = execution._sha(process)
        _rewrite(path, process)
        manifest["evidence"][team]["evidence_sha256"] = process[
            "evidence_sha256"]
        mutated_team = team
        break
    assert mutated_team is not None
    manifest.pop("manifest_sha256")
    manifest["manifest_sha256"] = execution._sha(manifest)
    _rewrite(manifest_path, manifest)
    with pytest.raises(execution.LunaExecutionError,
                       match="terminal mailbox witness absent"):
        execution.reopen_attempt(result.attempt_path)


def test_legacy_v1_complete_attempt_remains_reopenable(tmp_path):
    result = execution.run_luna_game(
        _game(), private_root=tmp_path, tool_script=TOOL,
        planner_process=_fake)
    _downgrade_attempt_to_v1(result.attempt_path, drop_terminal_witness=True)
    manifest_path = result.attempt_path / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    for team in luna.TEAMS:
        path = result.attempt_path / f"process-team-{team}.json"
        process = json.loads(path.read_text())
        final = json.dumps({
            "schema": execution.LEGACY_FINAL_RESPONSE_SCHEMA,
            "status": "complete"}).encode()
        stdout = base64.b64decode(process["stdout_base64"])
        process["final_base64"] = base64.b64encode(final).decode("ascii")
        process["output_sha256"] = execution._sha_bytes(
            stdout + b"\0" + final)
        process.pop("evidence_sha256")
        process["evidence_sha256"] = execution._sha(process)
        _rewrite(path, process)
        manifest["evidence"][team]["evidence_sha256"] = process[
            "evidence_sha256"]
    manifest.pop("manifest_sha256")
    manifest["manifest_sha256"] = execution._sha(manifest)
    _rewrite(manifest_path, manifest)
    assert execution.reopen_attempt(result.attempt_path).status == "complete"


def test_legacy_v1_incomplete_attempt_remains_reopenable(tmp_path):
    def early(_session, *, final_output_path, **_kwargs):
        final_output_path.write_text("{}")
        return subprocess.CompletedProcess(("fake-luna",), 0, _codex_stdout())

    result = execution.run_luna_game(
        _game(), private_root=tmp_path, tool_script=TOOL,
        planner_process=early)
    assert result.status == "incomplete"
    _downgrade_attempt_to_v1(result.attempt_path,
                             drop_terminal_witness=False)
    assert execution.reopen_attempt(result.attempt_path).status == "incomplete"


def test_current_attempt_cannot_mix_or_downgrade_one_team_to_v1(tmp_path):
    result = execution.run_luna_game(
        _game(), private_root=tmp_path, tool_script=TOOL,
        planner_process=_fake)
    process_path = result.attempt_path / "process-team-0.json"
    process = json.loads(process_path.read_text())
    process["schema"] = execution.LEGACY_PRIVATE_TRACE_SCHEMA
    process.pop("completion_token_sha256")
    for event in process["trace"]:
        if event["response"].get("status") == "round_end":
            event["response"].pop("completion_token")
            event["response_sha256"] = execution._sha(event["response"])
    process.pop("evidence_sha256")
    process["evidence_sha256"] = execution._sha(process)
    _rewrite(process_path, process)
    manifest_path = result.attempt_path / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["evidence"][0]["evidence_sha256"] = process["evidence_sha256"]
    manifest.pop("manifest_sha256")
    manifest["manifest_sha256"] = execution._sha(manifest)
    _rewrite(manifest_path, manifest)
    with pytest.raises(execution.LunaExecutionError,
                       match="trace schema/binding drift"):
        execution.reopen_attempt(result.attempt_path)


def test_process_failure_aborts_game_and_wakes_peer(tmp_path):
    game = _game()

    def failing(session, **kwargs):
        if session.team == 1:
            raise RuntimeError("synthetic process failure")
        return _fake(session, **kwargs)

    result = execution.run_luna_game(game, private_root=tmp_path, tool_script=TOOL,
                                     planner_process=failing)
    assert result.status == "incomplete"
    assert game.failed is not None
    assert len(result.evidence) == 2
    assert any("peer-aborted/cascade" in (item.body["process_error"] or "")
               for item in result.evidence)
    assert execution.reopen_attempt(result.attempt_path).status == "incomplete"
    assert not (result.attempt_path / "terminal-receipt.json").exists()


def _trailing_decision_failure(session, *, mailbox_path, **_kwargs):
    """Observe/search one real decision, then fail before committing it."""
    if session.team == 0:
        observed = execution.tool_request(mailbox_path, {"op": "observe"})
        assert observed["status"] == "decision"
        rollout = execution.tool_request(mailbox_path, {
            "op": "rollout", "decision_sha256": observed["decision_sha256"],
            "candidate_indices": [0], "continuations": ["smart-all"]})
        assert rollout["status"] == "rollout_complete"
        # Real planners may re-observe after a tool request before they commit.
        # The engine state has not moved, so this is the same decision chain.
        observed_again = execution.tool_request(mailbox_path, {"op": "observe"})
        assert observed_again == observed
        raise RuntimeError("synthetic injected planner failure")
    while True:
        observed = execution.tool_request(mailbox_path, {"op": "observe"})
        if observed["status"] == "failed":
            return subprocess.CompletedProcess(("fake-luna",), 1,
                                               _codex_stdout())
        if observed["status"] == "waiting":
            execution.tool_request(mailbox_path, {"op": "wait"})
        else:
            raise AssertionError("peer reached a decision before abort")


def _trailing_failure_attempt(tmp_path):
    return execution.run_luna_game(
        _game(), private_root=tmp_path, tool_script=TOOL,
        planner_process=_trailing_decision_failure)


def test_incomplete_reopen_accepts_one_hash_bound_trailing_decision_chain(tmp_path):
    result = _trailing_failure_attempt(tmp_path)
    assert result.status == "incomplete"
    reopened = execution.reopen_attempt(result.attempt_path)
    assert reopened.status == "incomplete"
    assert len(reopened.evidence) == 2
    assert reopened.trajectory_sha256 == result.trajectory_sha256
    assert reopened.terminal_receipt_sha256 is None
    assert reopened.scientific_admissible is False


def test_trailing_decision_reopen_matches_live_ballot_card_canonicalization(
        tmp_path, monkeypatch):
    original = execution.luna.c0.C0WideHeuristicBot._candidates

    def reversed_cards(self, rnd, seat):
        return [list(reversed(cards)) for cards in original(self, rnd, seat)]

    monkeypatch.setattr(execution.luna.c0.C0WideHeuristicBot, "_candidates",
                        reversed_cards)
    result = _trailing_failure_attempt(tmp_path)
    reopened = execution.reopen_attempt(result.attempt_path)
    assert reopened.status == "incomplete"
    assert len(reopened.evidence) == 2
    assert reopened.scientific_admissible is False


@pytest.mark.parametrize("mutation", ("decision_sha", "candidates",
                                       "conflicting_decision"))
def test_trailing_decision_mutations_refuse(tmp_path, mutation):
    result = _trailing_failure_attempt(tmp_path)
    process_path = result.attempt_path / "process-team-0.json"
    process = json.loads(process_path.read_text())
    decision = next(event for event in process["trace"]
                    if event["response"].get("status") == "decision")
    if mutation == "decision_sha":
        decision["response"]["decision_sha256"] = "0" * 64
        decision["response_sha256"] = execution._sha(decision["response"])
    elif mutation == "candidates":
        decision["response"]["candidates"] = list(
            reversed(decision["response"]["candidates"]))
        decision["response_sha256"] = execution._sha(decision["response"])
    elif mutation == "conflicting_decision":
        conflicting = json.loads(json.dumps(decision))
        conflicting["response"]["current_state"]["turn"] = 1
        conflicting["response_sha256"] = execution._sha(
            conflicting["response"])
        process["trace"].append(conflicting)
    process.pop("evidence_sha256")
    process["evidence_sha256"] = execution._sha(process)
    _rewrite(process_path, process)
    manifest_path = result.attempt_path / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["evidence"][0]["evidence_sha256"] = process[
        "evidence_sha256"]
    manifest.pop("manifest_sha256")
    manifest["manifest_sha256"] = execution._sha(manifest)
    _rewrite(manifest_path, manifest)
    with pytest.raises(execution.LunaExecutionError):
        execution.reopen_attempt(result.attempt_path)


def test_complete_attempt_refuses_coherently_rehashed_uncommitted_decision(
        tmp_path):
    result = execution.run_luna_game(
        _game(), private_root=tmp_path, tool_script=TOOL,
        planner_process=_fake)
    assert result.status == "complete"

    process_path = None
    process = None
    decision_index = None
    for team in luna.TEAMS:
        candidate_path = result.attempt_path / f"process-team-{team}.json"
        candidate = json.loads(candidate_path.read_text())
        for index, event in enumerate(candidate["trace"]):
            if event["response"].get("status") == "decision":
                process_path = candidate_path
                process = candidate
                decision_index = index
                break
        if process is not None:
            break
    assert process_path is not None and process is not None
    assert decision_index is not None

    uncommitted = json.loads(json.dumps(process["trace"][decision_index]))
    uncommitted["response"]["decision_sha256"] = "0" * 64
    uncommitted["response_sha256"] = execution._sha(uncommitted["response"])
    process["trace"].insert(decision_index + 1, uncommitted)
    process.pop("evidence_sha256")
    process["evidence_sha256"] = execution._sha(process)
    _rewrite(process_path, process)

    manifest_path = result.attempt_path / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    team = process["team"]
    manifest["evidence"][team]["evidence_sha256"] = process[
        "evidence_sha256"]
    manifest.pop("manifest_sha256")
    manifest["manifest_sha256"] = execution._sha(manifest)
    _rewrite(manifest_path, manifest)

    with pytest.raises(execution.LunaExecutionError,
                       match="process decision observation drift"):
        execution.reopen_attempt(result.attempt_path)


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

    def planner(session, *, supervisor, final_output_path, mailbox_path,
                **_kwargs):
        child = subprocess.Popen(("sleep", "30"), start_new_session=True)
        children.append(child)
        supervisor.register(session.team, child)
        if session.team == 1:
            raise RuntimeError("peer failed")
        while not supervisor.aborted:
            observed = execution.tool_request(mailbox_path, {"op": "observe"})
            if observed["status"] == "waiting":
                execution.tool_request(mailbox_path, {"op": "wait"})
            elif observed["status"] == "decision":
                execution.tool_request(mailbox_path, {
                    "op": "play", "decision_sha256": observed["decision_sha256"],
                    "candidate_index": 0, "confidence": "low"})
            else:
                break
        final_output_path.write_text(json.dumps({
            "schema": execution.FINAL_RESPONSE_SCHEMA, "status": "complete",
            "completion_token": session._completion_token}))
        return subprocess.CompletedProcess(("fake",), 1, b"")

    import time
    result = execution.run_luna_game(game, private_root=tmp_path, tool_script=TOOL,
                                     planner_process=planner,
                                     config=execution.LunaPlannerConfig(max_game_wall_seconds=2))
    assert result.status == "incomplete"
    assert children and all(child.poll() is not None for child in children)


@pytest.mark.skipif(os.name != "posix", reason="requires POSIX process groups")
def test_real_timeout_cleanup_retains_actual_subprocess_marker(tmp_path):
    ready = tmp_path / "child-ready"
    script = tmp_path / "linger.py"
    script.write_text(
        "import subprocess, sys, time\n"
        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(2.5)'], "
        "start_new_session=True)\n"
        "with open(sys.argv[1], 'wb'): pass\n"
        "sys.stdin.read()\n"
        "time.sleep(30)\n")
    game = _game()
    supervisor = execution.ProcessSupervisor(time.monotonic() + 60)
    ready_seen = threading.Event()

    def abort_after_launch():
        deadline = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        if ready.exists():
            ready_seen.set()
        supervisor.abort("test timeout")

    abort_thread = threading.Thread(target=abort_after_launch)
    abort_thread.start()
    completed = execution._default_process(
        game.session(0), workspace=tmp_path, mailbox_path=tmp_path / "mailbox",
        tool_script=TOOL, codex_binary=Path(sys.executable), prompt="timeout",
        final_output_path=tmp_path / "final.json", supervisor=supervisor,
        command=(sys.executable, str(script), str(ready)))
    abort_thread.join(timeout=6)

    assert ready_seen.is_set()
    assert getattr(completed, "_pt_luna_actual_subprocess", False) is True


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
