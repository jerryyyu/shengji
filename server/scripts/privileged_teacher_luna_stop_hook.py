#!/usr/bin/env python3
"""Fail-closed Codex Stop hook for one PT-Luna mailbox.

The hook is intentionally a narrow authority bridge: it reads the Stop event
privately, asks the engine-owned mailbox for one observation, and emits only a
bounded block response or the exact terminal JSON after round_end.  It never
prints an observation, token, model prose, or exception text.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

if not sys.flags.safe_path or not sys.dont_write_bytecode:
    raise RuntimeError("PT-Luna Stop hook requires Python -P -B")

try:
    from shengji.rl.privileged_teacher_luna_selfplay_execution import (  # noqa: E402
        FINAL_RESPONSE_SCHEMA,
        STOP_HOOK_ACTION_FIELD,
        STOP_HOOK_REQUEST_FIELD,
        tool_request,
    )
    from shengji.rl.privileged_teacher_luna_selfplay import (  # noqa: E402
        GAME_SCHEMA,
        MODEL,
    )
except Exception:
    # The command may be launched with a different interpreter than the
    # reviewed venv.  Keep an import failure fail-closed and private: Codex
    # must receive the same bounded continuation decision as any other bad
    # Stop event, never a traceback.
    _PROJECT_IMPORT_FAILED = True
    FINAL_RESPONSE_SCHEMA = None
    STOP_HOOK_ACTION_FIELD = None
    STOP_HOOK_REQUEST_FIELD = None
    GAME_SCHEMA = None
    MODEL = None
    tool_request = None
else:
    _PROJECT_IMPORT_FAILED = False


MAX_STOP_INPUT_BYTES = 1 << 20
CONTINUATION_REASON = (
    "No prose. Call model-visible exec with the prompt JavaScript; inside it "
    "call tools.exec_command for mailbox observe. "
    "Continue to round_end. Never call exec_command as a top-level tool."
)


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True)


def _block(reason: str = CONTINUATION_REASON) -> int:
    # Never include private input, observations, or exception text.  The one
    # exception is the exact terminal correction, emitted only after the
    # engine has independently reached round_end.
    sys.stdout.write(_json({"decision": "block", "reason": reason}))
    sys.stdout.write("\n")
    return 0


def _stop_input(raw: bytes) -> dict[str, object] | None:
    if len(raw) > MAX_STOP_INPUT_BYTES:
        return None
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if type(value) is not dict:
        return None
    # These fields are supplied by Codex's Stop event.  Rejecting malformed
    # metadata keeps an arbitrary stdin payload from becoming an allow signal.
    if (value.get("hook_event_name") != "Stop"
            or value.get("model") != MODEL
            or "last_assistant_message" not in value
            or (value.get("last_assistant_message") is not None
                and type(value.get("last_assistant_message")) is not str)
            or type(value.get("stop_hook_active")) is not bool):
        return None
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mailbox", type=Path, required=True)
    args = parser.parse_args()
    if _PROJECT_IMPORT_FAILED:
        return _block()
    stop = _stop_input(sys.stdin.buffer.read(MAX_STOP_INPUT_BYTES + 1))
    if stop is None:
        return _block()
    try:
        observed = tool_request(args.mailbox, {
            "op": "observe", STOP_HOOK_REQUEST_FIELD: True})
    except Exception:
        # A mailbox failure cannot authorize completion.  Let the process end
        # so the independent outer terminal-witness gate refuses promptly,
        # rather than turning a broken mailbox into an unbounded Stop loop.
        return 0
    # Only this exact, engine-issued response can allow the model to stop.
    action = (observed.get(STOP_HOOK_ACTION_FIELD)
              if type(observed) is dict else None)
    if action == "block":
        return _block()
    if action != "terminal":
        # ``exhausted`` is the normal bounded exit.  Any malformed action also
        # exits into the same fail-closed outer verifier; only the engine's
        # exact terminal witness below can authorize a successful game.
        return 0
    if (set(observed) != {"schema", "status", "completion_token",
                         STOP_HOOK_ACTION_FIELD}
            or observed.get("schema") != GAME_SCHEMA
            or observed.get("status") != "round_end"
            or type(observed.get("completion_token")) is not str
            or len(observed["completion_token"]) != 64
            or any(char not in "0123456789abcdef"
                   for char in observed["completion_token"])):
        return 0
    terminal = _json({"schema": FINAL_RESPONSE_SCHEMA, "status": "complete",
                      "completion_token": observed["completion_token"]})
    if stop["last_assistant_message"] != terminal:
        return _block("Round ended. Return exactly this terminal JSON: "
                      + terminal)
    # Empty stdout is Codex's non-blocking Stop result.  In particular, do
    # not print the terminal game JSON as hook output: it is model output and
    # must remain the exact last_assistant_message that was checked above.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
