"""Supervise the reviewed, foreground CPU generator and its worker group."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class ProcessResult:
    returncode: int | None
    stop_reason: str | None


@dataclass(frozen=True)
class GroupSample:
    leader_seen: bool
    live: bool
    rss_bytes: int


def _sample_group(group: int) -> GroupSample:
    snapshot = subprocess.check_output(
        ["/bin/ps", "-axo", "pid=,pgid=,stat=,rss="], text=True, timeout=2,
    )
    if not snapshot.endswith("\n"):
        raise RuntimeError("incomplete process-group census")
    seen = set()
    live = False
    rss_kib = 0
    for line in snapshot.splitlines():
        fields = line.split()
        if len(fields) != 4 or any(not value.isascii() or not value.isdigit()
                                   for value in (fields[0], fields[1], fields[3])):
            raise RuntimeError("invalid process-group census")
        pid, pgid, rss = map(int, (fields[0], fields[1], fields[3]))
        if pid < 1 or pid in seen or (pid == group and pgid != group):
            raise RuntimeError("invalid process-group identity")
        seen.add(pid)
        if pgid == group and not fields[2].startswith("Z"):
            live = True
            rss_kib += rss
    return GroupSample(group in seen, live, rss_kib * 1024)


def _live_group(group: int) -> bool:
    return _sample_group(group).live


def _signal_group(group: int, signum: int) -> None:
    try:
        os.killpg(group, signum)
    except ProcessLookupError:
        return
    except PermissionError:
        # Darwin can deny a signal to a group containing only zombies.
        if _live_group(group):
            raise


def _cleanup(child: subprocess.Popen, grace: float) -> None:
    # Keep the child unreaped until all group signals are finished. Its PID
    # remains reserved even when the group leader dies before its workers.
    group = child.pid
    try:
        _signal_group(group, signal.SIGTERM)
        deadline = time.monotonic() + grace
        while time.monotonic() < deadline:
            if not _live_group(group):
                break
            time.sleep(min(0.05, max(0, deadline - time.monotonic())))
    finally:
        try:
            _signal_group(group, signal.SIGKILL)
            deadline = time.monotonic() + 2
            while _live_group(group):
                if time.monotonic() >= deadline:
                    raise RuntimeError("generator processes still live after SIGKILL")
                time.sleep(0.05)
        finally:
            child.wait(timeout=2)


def supervise(command, *, cwd, env, log, guard, wall_seconds, poll_seconds=5,
              term_grace_seconds=2, max_rss_bytes=None) -> ProcessResult:
    """Run fixed argv from the lane controller and stop on its first guard.

    The reviewed generator must keep its descendants in its process group
    and publish ready shards atomically. The caller owns admission and final
    disposition. A stop before process creation returns a null return code.
    The optional RSS limit is sampled across all owned live processes.
    """
    if any(not 0 < n < float("inf")
           for n in (wall_seconds, poll_seconds, term_grace_seconds)):
        raise ValueError("process timings must be positive and finite")
    if max_rss_bytes is not None and (type(max_rss_bytes) is not int or max_rss_bytes <= 0):
        raise ValueError("process RSS limit must be a positive byte count")

    stop_reason = None

    def requested(signum, _frame):
        nonlocal stop_reason
        if stop_reason is None:
            stop_reason = signal.Signals(signum).name

    argv = ["/usr/sbin/taskpolicy", "-b", *command] if sys.platform == "darwin" else [
        "/usr/bin/nice", "-n", "19", *command,
    ]
    cpu_env = dict(env, CUDA_VISIBLE_DEVICES="", HIP_VISIBLE_DEVICES="",
                   OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1",
                   VECLIB_MAXIMUM_THREADS="1", NUMEXPR_NUM_THREADS="1",
                   BLIS_NUM_THREADS="1")
    handlers = {}
    try:
        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            handlers[sig] = signal.signal(sig, requested)
        stop_reason = guard() or stop_reason
        if stop_reason is not None:
            return ProcessResult(None, stop_reason)

        deadline = time.monotonic() + wall_seconds
        child = subprocess.Popen(
            argv, cwd=cwd, env=cpu_env, stdin=subprocess.DEVNULL, stdout=log,
            stderr=subprocess.STDOUT, start_new_session=True,
        )
        try:
            while stop_reason is None:
                if os.waitid(os.P_PID, child.pid, os.WEXITED | os.WNOWAIT | os.WNOHANG):
                    break
                if time.monotonic() >= deadline:
                    stop_reason = "wall-time"
                    break
                stop_reason = guard() or stop_reason
                if stop_reason is None and max_rss_bytes is not None:
                    sample = _sample_group(child.pid)
                    if not sample.leader_seen:
                        raise RuntimeError("owned leader missing from RSS census")
                    if sample.rss_bytes >= max_rss_bytes:
                        stop_reason = "rss-limit"
                if stop_reason is None:
                    time.sleep(max(0, min(poll_seconds, deadline - time.monotonic())))
        finally:
            _cleanup(child, term_grace_seconds)
        return ProcessResult(child.returncode, stop_reason)
    finally:
        for sig, handler in handlers.items():
            signal.signal(sig, handler)
