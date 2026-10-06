"""Mini input-process guard; no staging, launch authority or final publication.

The reviewed controller owns host/source/runtime/RELEASE gates. Commands must
write only private working artifacts: promote no bundle until this guard
returns process-exited/0. RSS is a sampled threshold, NOT a hard memory cap.

Only a reviewed non-daemonizing command tree is supported. This is not a
sandbox: an unobserved double-fork/setsid escape cannot be tracked by a PGID
census after reparenting. The input reader spawns no processes. Any transport
in the outer packet must disable SSH ControlMaster/ControlPersist and forbid
daemonization; never use this guard to contain arbitrary/untrusted commands.
"""
import os
import signal
import subprocess
import sys
import time

from scripts.launch_production_llm_panel import _start_contained_process


def group_rss(snapshot, leader, *, finished=False):
    """Validate headerless ps structure/owned leader; sum the owned group.

    A successful ps exit and these checks detect known partial/malformed
    snapshots, not every possible silent omission by the OS/tool.
    """
    if type(snapshot) is not str or not snapshot.endswith('\n'):
        raise ValueError('incomplete process census')
    rows = {}
    for line in snapshot.splitlines():
        fields = line.split()
        if len(fields) != 4 or any(not v.isascii() or not v.isdigit() for v in fields):
            raise ValueError('malformed process census')
        pid, parent, group, rss = map(int, fields)
        if pid < 1 or pid in rows:
            raise ValueError('duplicate/invalid census pid')
        rows[pid] = (parent, group, rss)
    if finished:
        if not rows or any(group == leader for _, group, _ in rows.values()):
            raise ValueError('owned group remains after leader exit')
        return 0
    if leader not in rows or rows[leader][1] != leader:
        raise ValueError('owned group leader missing')
    # A descendant leaving the group invalidates containment. Do not quietly
    # ignore it or widen a kill target to an unrelated group.
    for pid, (parent, group, _) in rows.items():
        seen = {pid}
        while parent in rows and parent not in seen:
            if parent == leader and group != leader:
                raise ValueError('descendant escaped owned process group')
            seen.add(parent)
            parent = rows[parent][0]
    return sum(rss for _, group, rss in rows.values() if group == leader) * 1024


def sample_group_rss(leader, timeout, *, finished=False):
    result = subprocess.run(['/bin/ps', '-axo', 'pid=,ppid=,pgid=,rss='],
        capture_output=True, text=True, check=True, timeout=timeout)
    return group_rss(result.stdout, leader, finished=finished)


def _terminate(child, grace):
    # The parent still owns/reaps this leader; never discover targets by name.
    if child.returncode is not None:
        raise ValueError('leader already reaped; cleanup requires explicit disposition')
    try:
        os.killpg(child.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline:
        time.sleep(min(0.02, max(0, deadline - time.monotonic())))
    # Send KILL even if leader exited: another member may ignore TERM.
    try:
        os.killpg(child.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    except PermissionError:
        # Darwin can report EPERM for a zombie-only group. Keep the leader
        # unreaped (and its PID reserved) while verifying that precise case.
        snapshot = subprocess.run(['/bin/ps', '-axo', 'pgid=,stat='],
            check=True, capture_output=True, text=True, timeout=0.25).stdout
        if not snapshot.endswith('\n'):
            raise ValueError('cleanup census incomplete') from None
        members = []
        for line in snapshot.splitlines():
            fields = line.split()
            if len(fields) != 2 or not fields[0].isascii() or not fields[0].isdigit():
                raise ValueError('cleanup census malformed') from None
            if int(fields[0]) == child.pid:
                members.append(fields[1])
        if not members or any(not state.startswith('Z') for state in members):
            raise ValueError('cleanup signal denied for non-zombie group') from None
    child.wait()


def supervise_s11_input(command, *, cwd, env, log, python=sys.executable,
                        wall_seconds=900, rss_threshold_bytes=512 << 20,
                        sample_seconds=0.25, term_grace_seconds=0.5):
    """Run one private input worker behind the existing parent-death watchdog.

    Input defaults are not authority for model collection. Other callers must
    independently qualify and pin their reviewed packet limits; non-default
    values grant no launch authority. Any census failure terminates the group.
    No raw log/exception content is copied to the operational receipt.
    """
    for value in (wall_seconds, rss_threshold_bytes, sample_seconds, term_grace_seconds):
        if type(value) not in (int, float) or not 0 < value < float('inf'):
            raise ValueError('positive finite guard limits required')
    start = time.monotonic()
    child, watchdog_fd = _start_contained_process(command, cwd=cwd, env=env,
                                                 log=log, python=python)
    peak = samples = 0
    cause = 'controller-interrupted'
    try:
        while True:
            remaining = wall_seconds - (time.monotonic() - start)
            if remaining <= 0:
                cause = 'wall-timeout'
                break
            if child.poll() is not None:
                try:
                    sample_group_rss(child.pid, min(sample_seconds, remaining), finished=True)
                    cause = 'process-exited' if samples else 'census-failed'
                except Exception:
                    cause = 'census-failed'
                break
            sample_start = time.monotonic()
            try:
                rss = sample_group_rss(child.pid, min(sample_seconds, remaining))
            except Exception:
                cause = ('wall-timeout' if time.monotonic() - start >= wall_seconds
                         else 'census-failed')
                break
            samples += 1
            peak = max(peak, rss)
            if rss > rss_threshold_bytes:
                cause = 'rss-threshold'
                break
            now = time.monotonic()
            remaining = wall_seconds - (now - start)
            if remaining > 0:
                try:
                    child.wait(timeout=min(max(0, sample_seconds - (now - sample_start)), remaining))
                except subprocess.TimeoutExpired:
                    pass
    finally:
        try:
            if cause != 'process-exited':
                _terminate(child, term_grace_seconds)
        finally:
            os.close(watchdog_fd)
    return dict(schema='s11-input-guard-v1', pid=child.pid, exit_cause=cause,
                returncode=child.returncode, peak_sampled_rss_bytes=peak,
                sample_count=samples, rss_threshold_bytes=rss_threshold_bytes,
                sample_seconds=sample_seconds, wall_seconds=wall_seconds,
                term_grace_seconds=term_grace_seconds,
                elapsed_seconds=time.monotonic()-start,
                memory_measure='sampled process-group RSS; overshoot between samples possible')
