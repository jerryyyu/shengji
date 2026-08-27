"""PT-Cla0: Claude as the adaptive full-information planner.

This is a controlled planner swap of PT-Sol0.  The engine session, mailbox
protocol, planner prompt, candidate ballots, rollout budgets, completion
token, private-evidence sealing and public report machinery are all reused
byte-for-byte from ``privileged_teacher_sol0``; the only substitution is the
external planner process, injected through the existing ``PlannerProcess``
seam that ``run_dev`` already threads to ``run_sol_session``.

Planner identity rides in ``Sol0Design``'s generic planner-binary fields:
``codex_binary_sha256`` carries the Claude CLI binary hash and
``codex_version`` carries ``claude --version`` plus the pinned model tag, so
a Cla0 report is schema-identical to a Sol0 report and differs exactly in
planner identity and outcomes.  Unlike Codex's ``--ignore-user-config``, the
Claude CLI offers no complete user-config bypass; the binary hash, version
string and pinned model are the identity that the frozen design binds.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from shutil import which

from .privileged_teacher_sol0 import (
    MAX_SESSION_WALL_SECONDS,
    PrivilegedTeacherSol0Error,
)

CLAUDE_MODEL = "claude-fable-5"
# One run pins exactly one model; each model produces a distinct frozen
# design SHA because the model tag is part of the bound identity string.
ALLOWED_CLAUDE_MODELS = (
    "claude-fable-5",
    "claude-opus-5",
    "claude-sonnet-5",
)

# Every tool except the engine mailbox command is denied.  The Bash allowlist
# prefix must equal the exact tool invocation the planner prompt advertises.
DENIED_TOOLS = (
    "Agent", "Edit", "NotebookEdit", "Task", "TodoWrite",
    "WebFetch", "WebSearch", "Write",
)
MAX_PLANNER_TURNS = 600


def require_claude_model(model: str) -> str:
    if model not in ALLOWED_CLAUDE_MODELS:
        raise PrivilegedTeacherSol0Error("Claude model identity drift")
    return model


def resolve_claude_binary(claude_binary: Path | None = None) -> Path:
    if claude_binary is None:
        found = which("claude")
        if found is None:
            raise PrivilegedTeacherSol0Error("Claude binary absent")
        claude_binary = Path(found)
    claude_binary = claude_binary.resolve()
    if not claude_binary.is_file():
        raise PrivilegedTeacherSol0Error("Claude binary absent")
    return claude_binary


def claude_version(claude_binary: Path,
                   model: str = CLAUDE_MODEL) -> str:
    """Return the planner identity string bound into the frozen design."""
    require_claude_model(model)
    version = subprocess.run(
        (str(claude_binary), "--version"), check=True, capture_output=True,
        text=True).stdout.strip()
    if not version or len(version) > 96:
        raise PrivilegedTeacherSol0Error("Claude version drift")
    return f"{version} [{model}]"


def claude_planner_command(
        *, claude_binary: Path, tool_command: str,
        model: str = CLAUDE_MODEL) -> tuple[str, ...]:
    """Exact headless invocation; pure so the shape is witnessable."""
    require_claude_model(model)
    return (
        str(claude_binary), "-p",
        "--model", model,
        "--output-format", "json",
        "--allowedTools", f"Bash({tool_command}:*)",
        "--disallowedTools", ",".join(DENIED_TOOLS),
        "--max-turns", str(MAX_PLANNER_TURNS),
    )


def extract_final_response(stdout: bytes) -> bytes | None:
    """Pull the planner's final message out of the ``json`` output envelope.

    The prompt requires the final message to be exactly the final-response
    JSON object.  A single surrounding markdown fence is stripped because it
    is an envelope artifact, not a game-semantics difference; anything else
    is returned verbatim for the session's own strict parser to judge.
    """
    try:
        envelope = json.loads(stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if type(envelope) is not dict:
        return None
    result = envelope.get("result")
    if type(result) is not str:
        return None
    text = result.strip()
    if text.startswith("```") and text.endswith("```"):
        text = text[3:-3].strip()
        if text.startswith("json"):
            text = text[4:].strip()
    return text.encode("utf-8")


def make_claude_planner_process(model: str = CLAUDE_MODEL):
    """Return a ``PlannerProcess`` pinned to exactly one Claude model.

    ``codex_binary`` is the generic planner-binary slot threaded by
    ``run_sol_session``; for Cla0 it holds the resolved Claude CLI path.
    """
    require_claude_model(model)

    def planner_process(
            session: object, *, workspace: Path, mailbox_path: Path,
            tool_script: Path, codex_binary: Path, prompt: str,
            final_output_path: Path) -> subprocess.CompletedProcess[bytes]:
        del session
        tool_command = (
            f"{Path(sys.executable)} -P -B {tool_script} "
            f"--mailbox {mailbox_path}")
        command = claude_planner_command(
            claude_binary=codex_binary, tool_command=tool_command,
            model=model)
        env = dict(os.environ)
        env.pop("PYTHONPATH", None)
        completed = subprocess.run(
            command, input=prompt.encode("utf-8"), stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, cwd=workspace, env=env,
            timeout=MAX_SESSION_WALL_SECONDS, check=False)
        final = extract_final_response(bytes(completed.stdout or b""))
        if final is not None:
            final_output_path.write_bytes(final)
        return completed

    return planner_process


claude_planner_process = make_claude_planner_process()
