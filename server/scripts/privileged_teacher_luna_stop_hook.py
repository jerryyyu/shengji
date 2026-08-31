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
    GAME_SCHEMA = None
    MODEL = None
    tool_request = None
else:
    _PROJECT_IMPORT_FAILED = False


MAX_STOP_INPUT_BYTES = 1 << 20
CONTINUATION_REASON = (
    "Continue with the PT-Luna mailbox until round_end, then return only the "
    "required terminal JSON."
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
            or type(value.get("last_assistant_message")) is not str
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
    # A blocked Stop causes Codex to continue and marks the next Stop event as
    # hook-active.  Never block that reentrant event again: doing so can create
    # an unbounded assistant-message/Stop-hook loop without advancing the
    # engine.  The outer process/terminal-witness verifier remains the
    # fail-closed authority if the continued model still stops before
    # round_end.
    if stop["stop_hook_active"]:
        return 0
    try:
        observed = tool_request(args.mailbox, {"op": "observe"})
    except Exception:
        return _block()
    # Only this exact, engine-issued response can allow the model to stop.
    if (type(observed) is not dict
            or set(observed) != {"schema", "status", "completion_token"}
            or observed.get("schema") != GAME_SCHEMA
            or observed.get("status") != "round_end"
            or type(observed.get("completion_token")) is not str
            or len(observed["completion_token"]) != 64
            or any(char not in "0123456789abcdef"
                   for char in observed["completion_token"])):
        return _block()
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
