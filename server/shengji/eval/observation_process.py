"""Process evidence for a separately admitted M9 observation attempt.

Not a launcher or admission gate: the caller must qualify/pin its interpreter,
source, watchdog, model, fixtures, environment, host and exclusive ownership,
and verify RELEASE before calling. No retries or scientific result acceptance.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import subprocess
import time

from ..luna.atomic_io import publish_exclusive_bytes
from ..luna.transport import ActiveCallManager, _start_contained_process


def run_observation_process(command: tuple[str, ...], *, workspace: Path,
                            env: dict[str, str], watchdog_script: Path,
                            timeout_seconds: float, evidence: Path) -> dict:
    """Retain terminal streams for one already-authorized local analysis child.

    A fresh evidence directory is spent before spawn, including failed spawns.
    The receipt describes process termination only, never scientific validity
    or host release. An interrupted call publishes evidence then re-raises.
    The caller's reviewed timeout is not an observation/poll timeout.
    """
    if (type(timeout_seconds) not in (int, float)
            or not math.isfinite(timeout_seconds) or timeout_seconds <= 0):
        raise ValueError("finite positive process deadline required")
    if not command or any(not isinstance(arg, str) for arg in command):
        raise ValueError("nonempty explicit command required")
    evidence.mkdir(mode=0o700)  # exclusive; never reuse failed attempts
    publish_exclusive_bytes(evidence / "claim.json", json.dumps({
        "schema": "m9-process-attempt-v1", "command": list(command),
        "timeout_seconds": timeout_seconds, "comparison_validated": False,
    }, sort_keys=True, allow_nan=False).encode(), mode=0o600)
    active = ActiveCallManager()
    process = None
    fd = None
    stdout = stderr = b""
    error: BaseException | None = None
    status = "spawn_failed"
    started = time.monotonic()
    try:
        process, fd = _start_contained_process(
            command, workspace=workspace, env=dict(env), active_calls=active,
            watchdog_script=watchdog_script)
        try:
            stdout, stderr = process.communicate(input=b"", timeout=timeout_seconds)
            status = "exited" if process.returncode == 0 else "failed"
        except subprocess.TimeoutExpired:
            status = "timeout"
            active.terminate()
            stdout, stderr = process.communicate(timeout=5)
    except BaseException as exc:
        error = exc
        # Registration may succeed before the helper returns the process/FD.
        # Its manager can still own a live group when our process is None.
        active.terminate()
        if process is not None:
            status = "interrupted" if isinstance(exc, (KeyboardInterrupt, SystemExit)) else "failed"
            try:
                stdout, stderr = process.communicate(timeout=5)
            except subprocess.TimeoutExpired as drain:
                stdout, stderr = drain.output or b"", drain.stderr or b""
                status = "drain_failed"
    finally:
        # Release is ownership-aware: terminate() has already consumed the FD
        # on cancellation/timeout. Never signal an already-reaped clean group.
        if process is not None and fd is not None:
            if process.returncode is not None and process.returncode < 0:
                active.terminate()
            active.release(process.pid, fd)
    receipt = {
        "schema": "m9-process-result-v1", "status": status,
        "returncode": process.returncode if process is not None else None,
        "elapsed_seconds": time.monotonic() - started,
        "comparison_validated": False,
        "error_type": type(error).__name__ if error is not None else None,
    }
    # Receipt comes last. An I/O error cannot leave a success-looking receipt
    # without its streams; already-published evidence remains untouched.
    publish_exclusive_bytes(evidence / "stdout.bin", stdout, mode=0o600)
    publish_exclusive_bytes(evidence / "stderr.bin", stderr, mode=0o600)
    publish_exclusive_bytes(evidence / "process.json", json.dumps(
        receipt, sort_keys=True, allow_nan=False).encode(), mode=0o600)
    if error is not None:
        raise error
    return receipt
