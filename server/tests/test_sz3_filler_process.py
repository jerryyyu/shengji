import os
import signal
import subprocess
import sys

import pytest

from scripts.lanes import sz3_filler_process as process
from scripts.lanes.sz3_filler_process import ProcessResult, _live_group, supervise


def run_fixture(tmp_path, code, guard=lambda: None, *, wall_seconds=3, **kwargs):
    with (tmp_path / "log").open("w") as log:
        return supervise(
            [sys.executable, "-c", code],
            cwd=tmp_path,
            env={**os.environ, "OPENBLAS_NUM_THREADS": "8", "CUDA_VISIBLE_DEVICES": "0"},
            log=log,
            guard=guard,
            wall_seconds=wall_seconds,
            poll_seconds=0.02,
            term_grace_seconds=0.1,
            **kwargs,
        )


def test_refusal_precedes_spawn(tmp_path):
    result = run_fixture(tmp_path, "raise RuntimeError('spawned')", lambda: "filler-hold")
    assert result == ProcessResult(None, "filler-hold")
    assert (tmp_path / "log").read_bytes() == b""


def test_natural_exit_preserves_exit_code_and_enforces_thread_env(tmp_path):
    result = run_fixture(tmp_path, """
import os
assert os.environ["OPENBLAS_NUM_THREADS"] == "1"
assert os.environ["OMP_NUM_THREADS"] == "1"
assert not os.environ["CUDA_VISIBLE_DEVICES"]
assert os.getpgrp() == os.getpid()
raise SystemExit(7)
""")
    assert result == ProcessResult(7, None)


def test_child_group_is_stopped_after_leader_exits(tmp_path):
    unrelated = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(10)"], start_new_session=True,
    )
    try:
        result = run_fixture(tmp_path, """
import os, subprocess, sys, time
from pathlib import Path
worker = "import signal,time,pathlib; signal.signal(signal.SIGTERM,signal.SIG_IGN); pathlib.Path('worker').touch(); time.sleep(10)"
subprocess.Popen([sys.executable, "-c", worker])
while not Path("worker").exists():
    time.sleep(0.01)
Path("group").write_text(str(os.getpid()))
""")
        assert result == ProcessResult(0, None)
        assert not _live_group(int((tmp_path / "group").read_text()))
        assert unrelated.poll() is None
    finally:
        unrelated.terminate()
        unrelated.wait(timeout=2)


@pytest.mark.parametrize("stop", ["guard", "sigterm", "exception", "deadline"])
def test_interruptions_reap_owned_process_and_restore_handlers(tmp_path, stop):
    group = tmp_path / "group"
    old_handler = signal.getsignal(signal.SIGTERM)

    def guard():
        if not group.is_file() or stop == "deadline":
            return None
        if stop == "sigterm":
            os.kill(os.getpid(), signal.SIGTERM)
        elif stop == "exception":
            raise ValueError("guard failed")
        else:
            return "pace"

    code = """
import os, signal, time
from pathlib import Path
signal.signal(signal.SIGTERM, signal.SIG_IGN)
Path("group.tmp").write_text(str(os.getpid()))
Path("group.tmp").rename("group")
time.sleep(10)
"""
    if stop == "exception":
        with pytest.raises(ValueError, match="guard failed"):
            run_fixture(tmp_path, code, guard)
    else:
        reasons = {"sigterm": "SIGTERM", "guard": "pace", "deadline": "wall-time"}
        result = run_fixture(tmp_path, code, guard, wall_seconds=1 if stop == "deadline" else 3)
        assert result == ProcessResult(-signal.SIGKILL, reasons[stop])
    assert not _live_group(int(group.read_text()))
    assert signal.getsignal(signal.SIGTERM) is old_handler


def test_rss_census_sums_only_owned_live_members(monkeypatch):
    monkeypatch.setattr(process.subprocess, "check_output", lambda *a, **k:
                        "1 1 Ss 100000\n2 2 S 100\n3 2 R 200\n4 2 Z 300\n")
    assert process._sample_group(2) == process.GroupSample(True, True, 300 * 1024)


def test_owned_worker_allocation_trips_rss_guard(tmp_path):
    result = run_fixture(tmp_path, """
import os, subprocess, sys
from pathlib import Path
Path("group").write_text(str(os.getpid()))
code = "import time; memory = bytearray(b'x') * (64 << 20); time.sleep(10)"
subprocess.run([sys.executable, "-c", code], check=True)
""", max_rss_bytes=48 << 20)
    assert result.stop_reason == "rss-limit"
    assert not _live_group(int((tmp_path / "group").read_text()))


def test_missing_rss_census_fails_closed(tmp_path, monkeypatch):
    group = tmp_path / "group"
    actual_sample = process._sample_group

    def sample(pid):
        if group.exists():
            monkeypatch.setattr(process, "_sample_group", actual_sample)
            return process.GroupSample(False, False, 0)
        return actual_sample(pid)

    monkeypatch.setattr(process, "_sample_group", sample)
    with pytest.raises(RuntimeError, match="owned leader missing"):
        run_fixture(tmp_path, """
import os, time
from pathlib import Path
Path("group").write_text(str(os.getpid()))
time.sleep(10)
""", max_rss_bytes=64 << 20)
    assert not _live_group(int(group.read_text()))
