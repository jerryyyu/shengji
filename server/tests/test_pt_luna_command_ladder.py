"""Tests use a fake executable but exercise actual bridge files and mailbox I/O."""

from pathlib import Path
import json
import os
import stat
import sys
import time

import pytest

from shengji.rl import pt_luna_command_ladder as ladder


FAKE = '''#!/usr/bin/env python3
import os
import json
from pathlib import Path
import shlex
import subprocess
import sys

HOOK_ONLY = __HOOK_ONLY__
prompt = sys.stdin.read()
tool_argv = shlex.split(prompt.splitlines()[0].split(": ", 1)[1])
tool = Path(tool_argv[3])
mailbox = Path(tool_argv[5])
final_path = Path(sys.argv[sys.argv.index("--output-last-message") + 1])
terminal_json = (b'{"completion_token":"' + b'a' * 64 +
                 b'","schema":"privileged-teacher-luna-selfplay-final-response-v2",'
                 b'"status":"complete"}')
if not HOOK_ONLY:
    child_env = dict(os.environ)
    child_env["PYTHONPATH"] = str(tool.parents[1])
    subprocess.run([sys.executable, "-P", "-B", str(tool),
                    "--mailbox", str(mailbox), "observe"],
                   check=True, env=child_env)
hook_configs = [sys.argv[index + 1] for index, value in
                enumerate(sys.argv[:-1])
                if value == "-c" and sys.argv[index + 1].startswith("hooks.Stop=")]
if hook_configs:
    encoded = hook_configs[0].split("command=", 1)[1].split(",timeout=", 1)[0]
    hook_argv = shlex.split(json.loads(encoded))
    last = json.dumps(terminal_json.decode()).encode()
    child_env = dict(os.environ)
    child_env["PYTHONPATH"] = str(tool.parents[1])
    subprocess.run(hook_argv, input=(
        b'{"hook_event_name":"Stop","model":"gpt-5.6-luna",'
        b'"last_assistant_message":' + last + b',"stop_hook_active":false}'),
                   check=False, env=child_env)
final_path.write_bytes(terminal_json + b"\\n")
'''


def _fake(tmp_path: Path, *, hook_only: bool = False) -> Path:
    executable = tmp_path / "fake-codex"
    source = FAKE.replace("#!/usr/bin/env python3", f"#!{sys.executable}")
    executable.write_text(source.replace("__HOOK_ONLY__", repr(hook_only)))
    executable.chmod(stat.S_IRWXU)
    return executable


def _fake_bad_final(tmp_path: Path) -> Path:
    executable = tmp_path / "fake-bad-final"
    source = FAKE.replace("#!/usr/bin/env python3", f"#!{sys.executable}")
    executable.write_text(source.replace("__HOOK_ONLY__", "False").replace(
        'final_path.write_bytes(terminal_json + b"\\n")',
        'final_path.write_bytes(b"{}\\n")'))
    executable.chmod(stat.S_IRWXU)
    return executable


def _forking_fake(tmp_path: Path) -> tuple[Path, Path]:
    pid_file = tmp_path / "lingering-child.pid"
    executable = _fake(tmp_path)
    source = executable.read_text()
    fork = (f"\npid = os.fork()\n"
            f"if pid == 0:\n"
            f"    Path({str(pid_file)!r}).write_text(str(os.getpid()))\n"
            f"    time.sleep(60)\n"
            f"    os._exit(0)\n")
    source = source.replace("HOOK_ONLY = False", "HOOK_ONLY = False" + fork)
    source = source.replace("import subprocess\n", "import subprocess\nimport time\n")
    executable.write_text(source)
    return executable, pid_file


def _timeout_forking_fake(tmp_path: Path) -> tuple[Path, Path]:
    pid_file = tmp_path / "timeout-child.pid"
    executable = tmp_path / "timeout-fake"
    executable.write_text(
        f"#!{sys.executable}\n"
        "import os\n"
        "from pathlib import Path\n"
        "import time\n"
        "pid = os.fork()\n"
        "if pid == 0:\n"
        f"    Path({str(pid_file)!r}).write_text(str(os.getpid()))\n"
        "    time.sleep(60)\n"
        "    os._exit(0)\n"
        "time.sleep(60)\n")
    executable.chmod(stat.S_IRWXU)
    return executable, pid_file


def test_variants_select_commands_and_bridges_via_real_mailbox(tmp_path: Path):
    report = ladder.run_ladder(executable=_fake(tmp_path),
                               output=tmp_path / "report.json",
                               progress=lambda _: None)
    assert report["passed"] is True
    rows = report["variants"]
    assert [row["variant"] for row in rows] == list(ladder.VARIANTS)
    assert [row["mailbox_operations"] for row in rows] == [1, 1, 2, 2]
    assert len({row["command_sha256"] for row in rows}) == 4
    assert len({row["bridge_sha256"] for row in rows}) == 2
    assert json.loads((tmp_path / "report.json").read_text()) == report


def test_command_ladder_shapes_and_prompts_are_distinct(tmp_path: Path):
    executable = _fake(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    commands = []
    prompts = []
    for variant in ladder.VARIANTS:
        command, bridge, prompt = ladder._variant_identity(
            variant, executable=executable, workspace=workspace,
            mailbox=tmp_path / f"mailbox-{variant}",
            final_output=tmp_path / f"final-{variant}")
        commands.append(command)
        prompts.append((bridge, prompt))
    assert "--json" not in commands[0]
    assert "--json" in commands[1]
    assert ladder.execution.STOP_HOOK_AUTOMATION_FLAG not in commands[1]
    assert ladder.execution.STOP_HOOK_AUTOMATION_FLAG in commands[2]
    assert ladder.execution.STOP_HOOK_AUTOMATION_FLAG in commands[3]
    assert all(command[command.index("-m") + 1] == ladder.MODEL
               for command in commands)
    assert prompts[0][0] == prompts[2][0] == ladder.SOL0_TOOL
    assert prompts[3][0] == ladder.LUNA_TOOL
    assert str(ladder.SOL0_TOOL) in prompts[0][1]
    assert str(ladder.LUNA_TOOL) in prompts[3][1]


def test_zero_model_mailbox_operations_fails_closed(tmp_path: Path):
    report = ladder.run_ladder(executable=_fake(tmp_path, hook_only=True),
                               output=tmp_path / "zero.json",
                               progress=lambda _: None)
    assert report["passed"] is False
    assert [row["mailbox_operations"] for row in report["variants"]] == [0, 0, 1, 1]
    assert all(row["passed"] is False for row in report["variants"])


def test_final_output_must_match_exact_terminal_json(tmp_path: Path):
    row = ladder.run_variant("A", executable=_fake_bad_final(tmp_path),
                             workspace=tmp_path, mailbox=tmp_path / "mailbox",
                             final_output=tmp_path / "final")
    assert row["mailbox_operations"] == 1
    assert row["error_sha256"] == ladder._sha_text("final output invalid")
    assert row["passed"] is False


def test_successful_leader_cannot_leave_a_lingering_process_group(tmp_path: Path):
    executable, pid_file = _forking_fake(tmp_path)
    row = ladder.run_variant("A", executable=executable, workspace=tmp_path,
                             mailbox=tmp_path / "mailbox",
                             final_output=tmp_path / "final")
    assert row["passed"] is True
    deadline = time.monotonic() + 1.0
    while not pid_file.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert pid_file.exists()
    child_pid = int(pid_file.read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(child_pid, 0)


def test_timeout_also_cleans_the_entire_process_group(tmp_path: Path):
    executable, pid_file = _timeout_forking_fake(tmp_path)
    row = ladder.run_variant("A", executable=executable, workspace=tmp_path,
                             mailbox=tmp_path / "mailbox",
                             final_output=tmp_path / "final",
                             timeout_seconds=1.0)
    assert row["passed"] is False
    deadline = time.monotonic() + 1.0
    while not pid_file.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert pid_file.exists()
    with pytest.raises(ProcessLookupError):
        os.kill(int(pid_file.read_text()), 0)


def test_cleanup_grace_starts_after_a_long_successful_probe(
        monkeypatch, tmp_path: Path):
    executable = tmp_path / "slow-success"
    executable.write_text(
        f"#!{sys.executable}\n"
        "import sys\n"
        "import time\n"
        "sys.stdin.read()\n"
        "time.sleep(2.1)\n")
    executable.chmod(stat.S_IRWXU)
    observed = []
    original = ladder._reap_group

    def witness(pgid, *, deadline):
        observed.append(deadline - time.monotonic())
        return original(pgid, deadline=deadline)

    monkeypatch.setattr(ladder, "_reap_group", witness)
    result = ladder.run_subprocess_probe(
        command=(str(executable), "-C", str(tmp_path)), prompt="probe\n",
        timeout_seconds=3.0)
    assert result.returncode == 0
    assert len(observed) == 1
    assert observed[0] > 0.9


def test_d_argv_is_exact_production_process_command(tmp_path: Path):
    executable = _fake(tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    mailbox = tmp_path / "mailbox"
    final_output = tmp_path / "final"
    actual, _, _ = ladder._variant_identity(
        "D", executable=executable, workspace=workspace, mailbox=mailbox,
        final_output=final_output)
    expected = ladder.execution.process_command(
        codex_binary=executable, workspace=workspace,
        final_output_path=final_output, mailbox_path=mailbox)
    assert actual == expected


def test_bridge_prompt_drift_fails_actual_wiring(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(ladder, "_diagnostic_prompt",
                        lambda **_: "mutated diagnostic prompt")
    row = ladder.run_variant("A", executable=_fake(tmp_path),
                             workspace=tmp_path, mailbox=tmp_path / "mailbox",
                             final_output=tmp_path / "final")
    assert row["passed"] is False


def test_hook_config_drift_fails_actual_wiring(monkeypatch, tmp_path: Path):
    original = ladder.execution._stop_hook_binding

    def drifted(*, mailbox_path):
        binding = dict(original(mailbox_path=mailbox_path))
        binding["config_override"] = "hooks.Stop=mutated"
        return binding

    monkeypatch.setattr(ladder.execution, "_stop_hook_binding", drifted)
    row = ladder.run_variant("C", executable=_fake(tmp_path),
                             workspace=tmp_path, mailbox=tmp_path / "mailbox",
                             final_output=tmp_path / "final")
    assert row["passed"] is False


def test_occupied_mailbox_and_outputs_refuse_retry(tmp_path: Path):
    mailbox = tmp_path / "mailbox"
    mailbox.mkdir()
    with pytest.raises(ladder.DiagnosticError, match="occupied"):
        ladder.run_variant("A", executable=_fake(tmp_path), workspace=tmp_path,
                           mailbox=mailbox, final_output=tmp_path / "final")
    output = tmp_path / "report.json"
    output.write_bytes(b"existing")
    with pytest.raises(ladder.DiagnosticError, match="occupied"):
        ladder.run_ladder(executable=_fake(tmp_path), output=output,
                          progress=lambda _: None)


def test_nonzero_process_exit_is_hashed_without_output_text(tmp_path: Path):
    executable = tmp_path / "failed-codex"
    executable.write_text("#!/bin/sh\nexit 7\n")
    executable.chmod(stat.S_IRWXU)
    row = ladder.run_variant("A", executable=executable, workspace=tmp_path,
                             mailbox=tmp_path / "mailbox",
                             final_output=tmp_path / "final")
    assert row["exit_code"] == 7
    assert row["error_sha256"] == ladder._sha_text("nonzero exit")
    assert row["passed"] is False
