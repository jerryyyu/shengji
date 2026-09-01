"""Synthetic two-process checks for the PT-Luna execution boundary."""

from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
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


def _codex_stdout(commands=()) -> bytes:
    events = [{"type": "thread.started", "thread_id": "fake"}]
    for index, (command, response) in enumerate(commands):
        item = {"id": f"command-{index}", "type": "command_execution",
                "command": command}
        events.append({"type": "item.started", "item": {
            **item, "aggregated_output": "", "exit_code": None,
            "status": "in_progress"}})
        events.append({"type": "item.completed", "item": {
            **item, "aggregated_output": json.dumps(
                response, sort_keys=True, separators=(",", ":")),
            "exit_code": 0, "status": "completed"}})
    return ("\n".join(json.dumps(event) for event in events) + "\n"
            + json.dumps({"type": "turn.completed", "usage": {
                "input_tokens": 10, "cached_input_tokens": 2,
                "cache_write_input_tokens": 1, "output_tokens": 3,
                "reasoning_output_tokens": 4}}) + "\n").encode()


def _recorded_request(mailbox: Path, request: dict[str, object], response):
    op = request["op"]
    args = []
    if op == "rollout":
        args = ["--decision", request["decision_sha256"], "--candidates",
                ",".join(str(value) for value in request["candidate_indices"]),
                "--continuations", ",".join(request["continuations"])]
    elif op == "play":
        args = ["--decision", request["decision_sha256"], "--candidate",
                str(request["candidate_index"]), "--confidence",
                request["confidence"]]
    inner = " ".join(shlex.quote(str(value)) for value in (
        execution.sys.executable, "-P", "-B", TOOL, "--mailbox", mailbox, op, *args))
    return shlex.join(("/bin/zsh", "-lc", inner)), response


def _terminal_response_bytes(token: str) -> bytes:
    return execution.canonical_json_bytes({
        "schema": execution.FINAL_RESPONSE_SCHEMA, "status": "complete",
        "completion_token": token,
    }).removesuffix(b"\n")


def _command_stdout(*, mailbox: Path, operation: str,
                    response: dict[str, object], command_mailbox: Path | None = None,
                    shell: str | None = None, command_suffix: str = "") -> bytes:
    target = command_mailbox or mailbox
    argv = tuple(str(value) for value in (
        execution.sys.executable, "-P", "-B", TOOL, "--mailbox", target, operation))
    inner = " ".join(shlex.quote(value) for value in argv) + command_suffix
    command = (shlex.join((shell, "-lc", inner)) if shell is not None
               else inner)
    item = {"id": "command-1", "type": "command_execution",
            "command": command,
            "aggregated_output": json.dumps(
                response, sort_keys=True, separators=(",", ":"))}
    rows = [{"type": "item.started", "item": {
                "id": "command-1", "type": "command_execution",
                "command": command, "aggregated_output": "",
                "exit_code": None, "status": "in_progress"}},
            {"type": "item.completed", "item": item}]
    rows[-1]["item"].update({"exit_code": 0, "status": "completed"})
    return ("\n".join(json.dumps(row, separators=(",", ":"))
                    for row in rows) + "\n").encode()


def test_codex_0150_usage_schema_is_bound_exactly():
    assert execution._codex_jsonl_usage(_codex_stdout()) == {
        "cache_write_input_tokens": 1,
        "cached_input_tokens": 2,
        "input_tokens": 10,
        "output_tokens": 3,
        "reasoning_output_tokens": 4,
    }


def test_live_model_catalog_surface_must_match_code_mode_contract(
        tmp_path, monkeypatch):
    catalog = {"models": [{"slug": execution.MODEL,
                            "tool_mode": execution.CODE_MODE_TOOL_MODE,
                            "shell_type": execution.CODE_MODE_SHELL_TYPE}]}
    raw = json.dumps(catalog).encode()
    monkeypatch.setattr(execution.subprocess, "run", lambda *args, **kwargs:
                        subprocess.CompletedProcess(args[0], 0, raw, b""))
    assert execution.validate_codex_model_surface(
        codex_binary=tmp_path / "codex") == execution._sha_bytes(raw)
    # The prior 0.149 catalog spelling must not be accepted as evidence for
    # the current 0.150.1 execution surface.
    catalog["models"][0]["shell_type"] = "shell_command"
    raw = json.dumps(catalog).encode()
    with pytest.raises(execution.LunaExecutionError,
                       match="^code-mode model catalog drift$"):
        execution.validate_codex_model_surface(
            codex_binary=tmp_path / "codex")


def test_terminal_witness_requires_completed_model_command(tmp_path):
    assert not execution._terminal_command_mailbox_witness(
        _codex_stdout(), mailbox_path=tmp_path / "mailbox", trace=[],
        completion_token_sha256="a" * 64)


def test_substituted_model_command_cannot_attribute_mailbox(tmp_path):
    mailbox = tmp_path / "mailbox"
    raw = _command_stdout(mailbox=mailbox,
                          command_mailbox=tmp_path / "substituted",
                          operation="observe",
                          response={"schema": luna.GAME_SCHEMA,
                                    "status": "waiting"})
    with pytest.raises(execution.LunaExecutionError,
                       match="(shell|command|mailbox) drift"):
        execution._codex_command_mailbox_operations(raw,
                                                     mailbox_path=mailbox)


def test_shell_wrapped_model_command_binds_exact_tool(tmp_path):
    mailbox = tmp_path / "mailbox"
    raw = _command_stdout(
        mailbox=mailbox, operation="observe", shell="/bin/zsh",
        response={"schema": luna.GAME_SCHEMA, "status": "waiting"})
    assert execution._codex_command_mailbox_operations(
        raw, mailbox_path=mailbox, python_path=Path(execution.sys.executable),
        tool_script_path=TOOL, require_shell=True) == ("observe",)


@pytest.mark.parametrize("command_shape", ("/bin/bash", "/bin/sh", None))
def test_production_parser_rejects_non_zsh_or_unwrapped_command(tmp_path,
                                                                 command_shape):
    raw = _command_stdout(mailbox=tmp_path / "mailbox", operation="observe",
                          response={"schema": luna.GAME_SCHEMA,
                                    "status": "waiting"}, shell=command_shape)
    with pytest.raises(execution.LunaExecutionError, match="shell drift"):
        execution._codex_command_mailbox_operations(
            raw, mailbox_path=tmp_path / "mailbox",
            python_path=Path(execution.sys.executable), tool_script_path=TOOL,
            require_shell=True)


def test_command_lifecycle_requires_one_matching_start(tmp_path):
    mailbox = tmp_path / "mailbox"
    raw = _command_stdout(mailbox=mailbox, operation="observe",
                          response={"schema": luna.GAME_SCHEMA,
                                    "status": "waiting"}, shell="/bin/zsh")
    rows = [json.loads(line) for line in raw.splitlines()]
    cases = (rows[1:], rows + [rows[0]],
             [rows[0], {**rows[1], "item": {**rows[1]["item"],
                                               "command": "/bin/zsh -lc pwd"}}],
             [rows[0]])
    for candidate in cases:
        candidate_raw = ("\n".join(json.dumps(row, separators=(",", ":"))
                                   for row in candidate) + "\n").encode()
        with pytest.raises(execution.LunaExecutionError):
            execution._codex_command_mailbox_operations(
                candidate_raw, mailbox_path=mailbox,
                python_path=Path(execution.sys.executable), tool_script_path=TOOL,
                require_shell=True)


def test_known_non_command_event_is_ignored_but_unknown_shapes_fail_closed(tmp_path):
    mailbox = tmp_path / "mailbox"
    raw = _command_stdout(mailbox=mailbox, operation="observe",
                          response={"schema": luna.GAME_SCHEMA,
                                    "status": "waiting"}, shell="/bin/zsh")
    rows = [json.loads(line) for line in raw.splitlines()]
    rows.insert(0, {"type": "item.updated", "item": {
        "id": "message-1", "type": "agent_message", "text": "opaque"}})
    accepted = ("\n".join(json.dumps(row, separators=(",", ":"))
                for row in rows) + "\n").encode()
    assert execution._codex_command_mailbox_operations(
        accepted, mailbox_path=mailbox,
        python_path=Path(execution.sys.executable), tool_script_path=TOOL,
        require_shell=True) == ("observe",)
    for bad in ({"type": "future.event", "payload": {}},
                {"type": "item.updated", "item": {"type": "future_item"}}):
        candidate = ("\n".join(json.dumps(row, separators=(",", ":"))
                     for row in [bad, *rows]) + "\n").encode()
        with pytest.raises(execution.LunaExecutionError):
            execution._codex_command_mailbox_operations(
                candidate, mailbox_path=mailbox,
                python_path=Path(execution.sys.executable), tool_script_path=TOOL,
                require_shell=True)


@pytest.mark.parametrize("shell", ("/bin/zsh", "/bin/bash", "/bin/sh"))
def test_shell_wrapped_extra_command_is_rejected(tmp_path, shell):
    mailbox = tmp_path / "mailbox"
    raw = _command_stdout(
        mailbox=mailbox, operation="observe", shell=shell,
        command_suffix="; echo extra",
        response={"schema": luna.GAME_SCHEMA, "status": "waiting"})
    with pytest.raises(execution.LunaExecutionError,
                       match="(shell|arguments|command|mailbox) drift"):
        execution._codex_command_mailbox_operations(
            raw, mailbox_path=mailbox, python_path=Path(execution.sys.executable),
            tool_script_path=TOOL, require_shell=True)


def test_hook_only_terminal_response_cannot_satisfy_command_witness(tmp_path):
    token = "a" * 64
    terminal = {"schema": luna.GAME_SCHEMA, "status": "round_end",
                "completion_token": token}
    request = {"op": "observe"}
    hook_event = {"request": request, "response": terminal,
                  "request_sha256": execution._sha(request),
                  "response_sha256": execution._sha(terminal)}
    raw = _command_stdout(mailbox=tmp_path / "mailbox", operation="observe",
                          response={"schema": luna.GAME_SCHEMA,
                                    "status": "waiting"})
    assert not execution._terminal_command_mailbox_witness(
        raw, mailbox_path=tmp_path / "mailbox", trace=[hook_event],
        completion_token_sha256=execution._sha_bytes(token.encode()))


def test_stop_hook_first_observe_cannot_satisfy_model_liveness(tmp_path):
    token = "b" * 64
    terminal = {"schema": luna.GAME_SCHEMA, "status": "round_end",
                "completion_token": token}
    request = {"op": "observe"}
    hook = {"request": {**request, execution.STOP_HOOK_REQUEST_FIELD: True},
            "response": {**terminal, execution.STOP_HOOK_ACTION_FIELD: "terminal"}}
    hook["request_sha256"] = execution._sha(hook["request"])
    hook["response_sha256"] = execution._sha(hook["response"])
    model = {"request": request, "response": terminal,
             "request_sha256": execution._sha(request),
             "response_sha256": execution._sha(terminal)}
    raw = _command_stdout(mailbox=tmp_path / "mailbox", operation="observe",
                          response=terminal, shell="/bin/zsh")
    assert not execution._terminal_command_mailbox_witness(
        raw, mailbox_path=tmp_path / "mailbox", trace=[hook, model],
        completion_token_sha256=execution._sha_bytes(token.encode()),
        require_model_first_observe=True)


def test_run_refuses_hook_first_synthetic_planner(tmp_path):
    def hook_first(session, *, mailbox_path, **kwargs):
        hooked = execution.tool_request(mailbox_path, _hook_observe())
        assert hooked[execution.STOP_HOOK_ACTION_FIELD] == "block"
        return _fake(session, mailbox_path=mailbox_path, **kwargs)

    result = execution.run_luna_game(
        _game(), private_root=tmp_path, tool_script=TOOL,
        planner_process=hook_first)
    assert result.status == "incomplete"
    assert any(item.body["process_error"]
               == "Luna model command mailbox witness absent or malformed"
               for item in result.evidence)


def test_default_process_keeps_stderr_out_of_codex_jsonl(tmp_path):
    launcher = tmp_path / "launcher.py"
    launcher.write_text(
        "import sys\n"
        "sys.stdin.buffer.read()\n"
        f"sys.stdout.buffer.write({_codex_stdout()!r})\n"
        "sys.stderr.buffer.write(b'sandbox diagnostic\\n')\n")
    game = _game()

    completed = execution._default_process(
        game.session(0), workspace=tmp_path,
        mailbox_path=tmp_path / "mailbox", tool_script=TOOL,
        codex_binary=Path(sys.executable), prompt="test",
        final_output_path=tmp_path / "final.json",
        command=(sys.executable, str(launcher)))

    assert completed.returncode == 0
    assert completed.stdout == _codex_stdout()
    assert completed.stderr == b"sandbox diagnostic\n"
    assert execution._codex_jsonl_usage(completed.stdout)["input_tokens"] == 10


def test_planner_prompt_binds_team_relative_utility_objective(tmp_path):
    prompt = execution.planner_prompt(
        mailbox_path=tmp_path / "mailbox", tool_script=TOOL)
    assert "sole objective is to" in prompt
    assert "maximize final signed-level utility" in prompt
    assert "full-information privilege" in prompt
    assert "Candidate zero is always the production prior" in prompt
    assert "defender's utility is the exact opposite" in prompt
    assert "Immediately invoke the local tool's observe command as your first code-mode" in prompt
    assert execution.CODE_MODE_PUBLIC_TOOL_NAME == "exec"
    assert execution.CODE_MODE_PUBLIC_WAIT_NAME == "wait"
    assert execution.CODE_MODE_NESTED_TOOL_NAME == "exec_command"
    assert execution.CODE_MODE_NESTED_WAIT_NAME == "write_stdin"
    assert execution.CODE_MODE_PUBLIC_TOOL_NAME != execution.CODE_MODE_NESTED_TOOL_NAME
    assert "model-visible code-mode tool\n`exec`" in prompt
    assert "model-visible `wait` tool" in prompt
    assert "tools.exec_command" in prompt
    assert "let result = await tools.exec_command" in prompt
    assert "tools.write_stdin" in prompt
    assert (f'// @exec: {{"yield_time_ms": '
            f'{execution.CODE_MODE_OUTER_YIELD_MILLISECONDS}}}' in prompt)
    assert "`exec` tool returns `Script running with cell ID" in prompt
    assert "Do not call `functions.wait`" in prompt
    assert "result.session_id" in prompt
    assert "let combined = result.output ?? \"\"" in prompt
    assert "while (result.session_id)" in prompt
    assert "combined += result.output ?? \"\"" in prompt
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
    assert execution.PLANNER_DEVELOPER_OVERRIDE in command
    assert "first tool call must invoke the model-visible exec tool" \
        in execution.PLANNER_DEVELOPER_INSTRUCTIONS
    assert "nested tools.exec_command" in execution.PLANNER_DEVELOPER_INSTRUCTIONS
    assert "model-visible wait tool" in execution.PLANNER_DEVELOPER_INSTRUCTIONS
    assert "functions.wait is not the public continuation name" \
        in execution.PLANNER_DEVELOPER_INSTRUCTIONS
    assert execution.CODE_MODE_FEATURE_OVERRIDE in command


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


def _hook_observe() -> dict[str, object]:
    return {"op": "observe", execution.STOP_HOOK_REQUEST_FIELD: True}


def test_engine_owned_stop_counter_blocks_twice_then_exhausts(tmp_path):
    game = _game()
    server = execution.LunaToolServer(
        tmp_path / "mailbox", game.session(game.acting_team))

    # Model observes are deliberately unadorned and cannot reset or consume
    # the engine-owned Stop-hook allowance.
    assert execution.STOP_HOOK_ACTION_FIELD not in server._dispatch({"op": "observe"})
    assert server._dispatch(_hook_observe())[execution.STOP_HOOK_ACTION_FIELD] == "block"
    assert execution.STOP_HOOK_ACTION_FIELD not in server._dispatch({"op": "observe"})
    assert server._dispatch(_hook_observe())[execution.STOP_HOOK_ACTION_FIELD] == "block"
    assert server._dispatch(_hook_observe())[execution.STOP_HOOK_ACTION_FIELD] == "exhausted"


def test_engine_owned_stop_counter_is_atomic_under_concurrent_dispatch(tmp_path):
    game = _game()
    server = execution.LunaToolServer(
        tmp_path / "mailbox", game.session(game.acting_team))

    with ThreadPoolExecutor(max_workers=20) as pool:
        responses = tuple(pool.map(lambda _index: server._dispatch(_hook_observe()),
                                   range(20)))
    actions = [response[execution.STOP_HOOK_ACTION_FIELD]
               for response in responses]
    assert actions.count("block") == execution.MAX_STOP_HOOK_NONTERMINAL_BLOCKS
    assert actions.count("exhausted") == 18


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
    commands = []
    while True:
        request = {"op": "observe"}
        observed = execution.tool_request(mailbox_path, request)
        commands.append(_recorded_request(mailbox_path, request, observed))
        if observed["status"] in ("round_end", "failed"):
            terminal = observed
            break
        if observed["status"] == "waiting":
            request = {"op": "wait"}
            waited = execution.tool_request(mailbox_path, request)
            commands.append(_recorded_request(mailbox_path, request, waited))
            if waited["status"] in ("round_end", "failed"):
                terminal = waited
                break
            continue
        request = {
            "op": "play", "decision_sha256": observed["decision_sha256"],
            "candidate_index": 0, "confidence": "low"}
        played = execution.tool_request(mailbox_path, request)
        commands.append(_recorded_request(mailbox_path, request, played))
        if played["status"] in ("round_end", "failed"):
            terminal = played
            break
    assert terminal is not None and terminal["status"] == "round_end"
    final_output_path.write_bytes(_terminal_response_bytes(
        terminal["completion_token"]))
    return subprocess.CompletedProcess(("fake-luna",), 0,
                                       _codex_stdout(commands))


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
        commands = []
        while True:
            request = {"op": "observe"}
            observed = execution.tool_request(kwargs["mailbox_path"], request)
            commands.append(_recorded_request(kwargs["mailbox_path"], request,
                                               observed))
            if observed["status"] in ("round_end", "failed"):
                terminal = observed
                break
            if observed["status"] == "waiting":
                request = {"op": "wait"}
                waited = execution.tool_request(
                    kwargs["mailbox_path"], request)
                commands.append(_recorded_request(kwargs["mailbox_path"],
                                                   request, waited))
                if waited["status"] in ("round_end", "failed"):
                    terminal = waited
                    break
                continue
            with lock:
                plays.append((session.team, observed["acting_seat"]))
            request = {
                "op": "play", "decision_sha256": observed["decision_sha256"],
                "candidate_index": 0, "confidence": "low"}
            played = execution.tool_request(kwargs["mailbox_path"], request)
            commands.append(_recorded_request(kwargs["mailbox_path"], request,
                                               played))
            if played["status"] in ("round_end", "failed"):
                terminal = played
                break
        assert terminal is not None and terminal["status"] == "round_end"
        kwargs["final_output_path"].write_bytes(_terminal_response_bytes(
            terminal["completion_token"]))
        return subprocess.CompletedProcess(("fake-luna",), 0,
                                           _codex_stdout(commands))

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


def test_terminal_stop_hook_trace_completes_and_reopens(tmp_path):
    def planner(session, *, mailbox_path, **kwargs):
        completed = _fake(session, mailbox_path=mailbox_path, **kwargs)
        hooked = execution.tool_request(mailbox_path, _hook_observe())
        assert hooked[execution.STOP_HOOK_ACTION_FIELD] == "terminal"
        return completed

    result = execution.run_luna_game(
        _game(), private_root=tmp_path, tool_script=TOOL,
        planner_process=planner)
    assert result.status == "complete"
    assert execution.reopen_attempt(result.attempt_path).status == "complete"


def test_reopen_binds_published_final_bytes_to_process_evidence(tmp_path):
    result = execution.run_luna_game(
        _game(), private_root=tmp_path, tool_script=TOOL,
        planner_process=_fake)
    assert result.status == "complete"
    final = result.attempt_path / "workspace-team-0" / "final.json"
    final.write_bytes(b"{}")
    with pytest.raises(execution.LunaExecutionError,
                       match="final response byte binding drift"):
        execution.reopen_attempt(result.attempt_path)


def test_wrong_completion_response_refuses_outer_success_gate(tmp_path):
    def wrong_final(session, *, mailbox_path, final_output_path, **_kwargs):
        commands = []
        while True:
            request = {"op": "observe"}
            observed = execution.tool_request(mailbox_path, request)
            commands.append(_recorded_request(mailbox_path, request, observed))
            if observed["status"] in ("round_end", "failed"):
                break
            if observed["status"] == "waiting":
                request = {"op": "wait"}
                waited = execution.tool_request(mailbox_path, request)
                commands.append(_recorded_request(mailbox_path, request, waited))
                continue
            request = {
                "op": "play", "decision_sha256": observed["decision_sha256"],
                "candidate_index": 0, "confidence": "low"}
            played = execution.tool_request(mailbox_path, request)
            commands.append(_recorded_request(mailbox_path, request, played))
        token = session._completion_token if session.team else "0" * 64
        final_output_path.write_text(json.dumps({
            "schema": execution.FINAL_RESPONSE_SCHEMA, "status": "complete",
            "completion_token": token}))
        return subprocess.CompletedProcess(("fake-luna",), 0,
                                           _codex_stdout(commands))

    result = execution.run_luna_game(
        _game(), private_root=tmp_path, tool_script=TOOL,
        planner_process=wrong_final)
    assert result.status == "incomplete"
    assert result.scientific_admissible is False
    assert any("exact terminal response absent or malformed"
               in (item.body["process_error"] or "")
               for item in result.evidence)
    assert execution.reopen_attempt(result.attempt_path).status == "incomplete"


def test_absent_final_after_terminal_trace_refuses_outer_success_gate(tmp_path):
    def absent_final(session, *, mailbox_path, **_kwargs):
        commands = []
        terminal = None
        while terminal is None:
            request = {"op": "observe"}
            observed = execution.tool_request(mailbox_path, request)
            commands.append(_recorded_request(mailbox_path, request, observed))
            if observed["status"] in ("round_end", "failed"):
                terminal = observed
            elif observed["status"] == "waiting":
                request = {"op": "wait"}
                waited = execution.tool_request(mailbox_path, request)
                commands.append(_recorded_request(mailbox_path, request, waited))
                if waited["status"] in ("round_end", "failed"):
                    terminal = waited
            else:
                request = {
                    "op": "play", "decision_sha256": observed["decision_sha256"],
                    "candidate_index": 0, "confidence": "low"}
                played = execution.tool_request(mailbox_path, request)
                commands.append(_recorded_request(mailbox_path, request, played))
        assert terminal["status"] == "round_end"
        return subprocess.CompletedProcess(("fake-luna",), 0,
                                           _codex_stdout(commands))

    result = execution.run_luna_game(
        _game(), private_root=tmp_path, tool_script=TOOL,
        planner_process=absent_final)
    assert result.status == "incomplete"
    assert any("exact terminal response absent or malformed"
               in (item.body["process_error"] or "")
               for item in result.evidence)
    assert execution.reopen_attempt(result.attempt_path).status == "incomplete"


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


def test_terminal_hook_trace_cannot_replace_model_command_witness(tmp_path):
    def missing_terminal_command(session, **kwargs):
        completed = _fake(session, **kwargs)
        rows = [json.loads(line) for line in completed.stdout.splitlines()]
        completed_indices = [
            index for index, row in enumerate(rows)
            if row.get("type") == "item.completed"
            and row.get("item", {}).get("type") == "command_execution"
        ]
        assert completed_indices
        completed_index = completed_indices[-1]
        command_id = rows[completed_index]["item"]["id"]
        rows = [row for row in rows if not (
            row.get("type") in ("item.started", "item.completed")
            and row.get("item", {}).get("type") == "command_execution"
            and row.get("item", {}).get("id") == command_id)]
        stdout = ("\n".join(json.dumps(row) for row in rows) + "\n").encode()
        return subprocess.CompletedProcess(completed.args, 0, stdout)

    result = execution.run_luna_game(
        _game(), private_root=tmp_path, tool_script=TOOL,
        planner_process=missing_terminal_command)
    assert result.status == "incomplete"
    errors = [item.body["process_error"] for item in result.evidence
              if item.body["process_error"] is not None]
    assert "Luna model command mailbox witness absent or malformed" in errors


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


def test_coordinated_rehash_hook_first_trace_cannot_satisfy_model_witness(
        tmp_path):
    result = execution.run_luna_game(
        _game(), private_root=tmp_path, tool_script=TOOL,
        planner_process=_fake)
    assert result.status == "complete"
    manifest_path = result.attempt_path / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    for team in luna.TEAMS:
        process_path = result.attempt_path / f"process-team-{team}.json"
        process = json.loads(process_path.read_text())
        assert process["schema"] == execution.PRIVATE_TRACE_SCHEMA
        first = process["trace"][0]
        assert first["request"] == {"op": "observe"}
        hook_request = {
            **first["request"], execution.STOP_HOOK_REQUEST_FIELD: True}
        hook_response = {
            **first["response"], execution.STOP_HOOK_ACTION_FIELD: "block"}
        hook = {
            "request": hook_request,
            "response": hook_response,
            "request_sha256": execution._sha(hook_request),
            "response_sha256": execution._sha(hook_response),
        }
        process["trace"] = [hook, *process["trace"]]
        process.pop("evidence_sha256")
        process["evidence_sha256"] = execution._sha(process)
        _rewrite(process_path, process)
        manifest["evidence"][team]["evidence_sha256"] = process[
            "evidence_sha256"]
    manifest.pop("manifest_sha256")
    manifest["manifest_sha256"] = execution._sha(manifest)
    _rewrite(manifest_path, manifest)
    with pytest.raises(execution.LunaExecutionError,
                       match="process terminal command mailbox witness absent"):
        execution.reopen_attempt(result.attempt_path)


def test_coordinated_rehash_cannot_remove_tool_liveness_instruction(tmp_path):
    result = execution.run_luna_game(
        _game(), private_root=tmp_path, tool_script=TOOL,
        planner_process=_fake)
    assert result.status == "complete"
    process_path = result.attempt_path / "process-team-0.json"
    process = json.loads(process_path.read_text())
    process["command"].remove(execution.PLANNER_DEVELOPER_OVERRIDE)
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
    with pytest.raises(execution.LunaExecutionError,
                       match="process command identity drift"):
        execution.reopen_attempt(result.attempt_path)


def test_pre_repair_v2_artifact_remains_reopenable_without_liveness_override(
        tmp_path):
    result = execution.run_luna_game(
        _game(), private_root=tmp_path, tool_script=TOOL,
        planner_process=_fake)
    assert result.status == "complete"
    attempt_path = result.attempt_path / "attempt.json"
    attempt = json.loads(attempt_path.read_text())
    attempt.pop("attempt_sha256")
    attempt["schema"] = execution.INTERMEDIATE_ATTEMPT_SCHEMA
    attempt["private_trace_schema"] = \
        execution.INTERMEDIATE_PRIVATE_TRACE_SCHEMA
    attempt["attempt_sha256"] = execution._sha(attempt)
    _rewrite(attempt_path, attempt)
    manifest_path = result.attempt_path / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    for team in luna.TEAMS:
        process_path = result.attempt_path / f"process-team-{team}.json"
        process = json.loads(process_path.read_text())
        process["schema"] = execution.INTERMEDIATE_PRIVATE_TRACE_SCHEMA
        process["command"].remove(execution.PLANNER_DEVELOPER_OVERRIDE)
        process.pop("evidence_sha256")
        process["evidence_sha256"] = execution._sha(process)
        _rewrite(process_path, process)
        manifest["evidence"][team]["evidence_sha256"] = process[
            "evidence_sha256"]
    manifest.pop("manifest_sha256")
    manifest["manifest_sha256"] = execution._sha(manifest)
    _rewrite(manifest_path, manifest)
    assert execution.reopen_attempt(result.attempt_path).status == "complete"


def test_pre_code_mode_v3_artifact_remains_reopenable(tmp_path):
    result = execution.run_luna_game(
        _game(), private_root=tmp_path, tool_script=TOOL,
        planner_process=_fake)
    assert result.status == "complete"
    attempt_path = result.attempt_path / "attempt.json"
    attempt = json.loads(attempt_path.read_text())
    attempt.pop("attempt_sha256")
    attempt["schema"] = execution.PRE_CODE_MODE_ATTEMPT_SCHEMA
    attempt["private_trace_schema"] = \
        execution.PRE_CODE_MODE_PRIVATE_TRACE_SCHEMA
    for key in ("expected_tool_mode", "expected_shell_type",
                "expected_tool_name"):
        attempt["runtime"].pop(key)
    attempt["attempt_sha256"] = execution._sha(attempt)
    _rewrite(attempt_path, attempt)
    manifest_path = result.attempt_path / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["runtime"] = attempt["runtime"]
    for team in luna.TEAMS:
        process_path = result.attempt_path / f"process-team-{team}.json"
        process = json.loads(process_path.read_text())
        assert process["schema"] == execution.PRIVATE_TRACE_SCHEMA
        process["schema"] = execution.PRE_CODE_MODE_PRIVATE_TRACE_SCHEMA
        for key in ("expected_tool_mode", "expected_shell_type",
                    "expected_tool_name"):
            process["runtime"].pop(key)
        process["command"].remove(execution.CODE_MODE_FEATURE_OVERRIDE)
        process.pop("evidence_sha256")
        process["evidence_sha256"] = execution._sha(process)
        _rewrite(process_path, process)
        manifest["evidence"][team]["evidence_sha256"] = process[
            "evidence_sha256"]
    manifest.pop("manifest_sha256")
    manifest["manifest_sha256"] = execution._sha(manifest)
    _rewrite(manifest_path, manifest)
    assert execution.reopen_attempt(result.attempt_path).status == "complete"


@pytest.mark.parametrize("identity_key,mutated_value", (
    ("expected_tool_mode", "shell"),
    ("expected_shell_type", "direct"),
    ("expected_tool_name", "shell"),
))
def test_coordinated_rehash_rejects_code_mode_runtime_mutation(
        tmp_path, identity_key, mutated_value):
    result = execution.run_luna_game(
        _game(), private_root=tmp_path, tool_script=TOOL,
        planner_process=_fake)
    assert result.status == "complete"
    attempt_path = result.attempt_path / "attempt.json"
    attempt = json.loads(attempt_path.read_text())
    attempt.pop("attempt_sha256")
    attempt["runtime"][identity_key] = mutated_value
    attempt["attempt_sha256"] = execution._sha(attempt)
    _rewrite(attempt_path, attempt)
    manifest_path = result.attempt_path / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["runtime"] = attempt["runtime"]
    for team in luna.TEAMS:
        process_path = result.attempt_path / f"process-team-{team}.json"
        process = json.loads(process_path.read_text())
        process["runtime"][identity_key] = mutated_value
        process.pop("evidence_sha256")
        process["evidence_sha256"] = execution._sha(process)
        _rewrite(process_path, process)
        manifest["evidence"][team]["evidence_sha256"] = process[
            "evidence_sha256"]
    manifest.pop("manifest_sha256")
    manifest["manifest_sha256"] = execution._sha(manifest)
    _rewrite(manifest_path, manifest)
    with pytest.raises(execution.LunaExecutionError,
                       match="^code-mode runtime identity drift$"):
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
