"""Synthetic-only process lifecycle/evidence tests; no model execution."""
import json
import os
from pathlib import Path
import sys
import time

import pytest

from shengji.eval import observation_process as O
from shengji.luna import transport


def invoke(tmp_path, script, *, timeout=5):
    return O.run_observation_process(
        (sys.executable, "-I", "-B", "-c", script), workspace=tmp_path,
        env={"PATH": os.environ.get("PATH", "")},
        watchdog_script=Path(transport.__file__).with_name("watchdog.py").resolve(),
        timeout_seconds=timeout, evidence=tmp_path / "attempt")


@pytest.mark.parametrize("code,status", [(0, "exited"), (7, "failed")])
def test_streams_retained_on_each_exit(tmp_path, code, status):
    receipt = invoke(tmp_path, "import sys; print('OUT',flush=True); "
                     "print('ERR',file=sys.stderr,flush=True); "
                     f"raise SystemExit({code})")
    assert receipt["status"] == status and receipt["returncode"] == code
    assert not receipt["comparison_validated"]
    assert (tmp_path / "attempt/stdout.bin").read_bytes() == b"OUT\n"
    assert (tmp_path / "attempt/stderr.bin").read_bytes() == b"ERR\n"
    assert json.loads((tmp_path / "attempt/process.json").read_text()) == receipt


def test_timeout_kills_child_and_preserves_streams(tmp_path):
    pid_path = tmp_path / "child.pid"
    receipt = invoke(tmp_path,
        "import os,pathlib,time,sys; "
        f"pathlib.Path({str(pid_path)!r}).write_text(str(os.getpid())); "
        "print('BEFORE',flush=True); print('ERROR',file=sys.stderr,flush=True); time.sleep(60)",
        timeout=0.5)
    assert receipt["status"] == "timeout"
    assert receipt["returncode"] != 0
    assert receipt["elapsed_seconds"] < 5
    assert (tmp_path / "attempt/stdout.bin").read_bytes() == b"BEFORE\n"
    assert (tmp_path / "attempt/stderr.bin").read_bytes() == b"ERROR\n"
    pid = int(pid_path.read_text())
    deadline = time.monotonic() + 2
    while True:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        stat = Path(f"/proc/{pid}/stat")
        # Linux may retain a dead orphan as a zombie until init reaps it.
        try:
            if stat.read_text().split(") ", 1)[1].split()[0] == "Z":
                break
        except FileNotFoundError:
            pass
        assert time.monotonic() < deadline, "synthetic child still executing"
        time.sleep(0.01)


def test_attempt_reuse_refuses_before_spawn(tmp_path, monkeypatch):
    invoke(tmp_path, "pass")
    def no_spawn(*args, **kwargs):
        raise AssertionError("reuse spawned a child")
    monkeypatch.setattr(O, "_start_contained_process", no_spawn)
    with pytest.raises(FileExistsError):
        invoke(tmp_path, "pass")


def test_spawn_failure_retains_terminal_evidence(tmp_path, monkeypatch):
    def fail(*args, **kwargs):
        raise OSError("synthetic spawn failure")
    monkeypatch.setattr(O, "_start_contained_process", fail)
    with pytest.raises(OSError, match="synthetic spawn"):
        invoke(tmp_path, "pass")
    receipt = json.loads((tmp_path / "attempt/process.json").read_text())
    assert receipt["status"] == "spawn_failed"
    assert receipt["returncode"] is None
    assert receipt["error_type"] == "OSError"


@pytest.mark.parametrize("timeout", [0, -1, True, float("nan"), float("inf")])
def test_invalid_deadline_does_not_spend_attempt(tmp_path, timeout):
    with pytest.raises(ValueError, match="deadline"):
        invoke(tmp_path, "pass", timeout=timeout)
    assert not (tmp_path / "attempt").exists()


def test_stream_write_failure_never_publishes_receipt(tmp_path, monkeypatch):
    publish = O.publish_exclusive_bytes
    def fail_stderr(path, raw, **kwargs):
        if path.name == "stderr.bin":
            raise OSError("synthetic disk failure")
        return publish(path, raw, **kwargs)
    monkeypatch.setattr(O, "publish_exclusive_bytes", fail_stderr)
    with pytest.raises(OSError, match="disk failure"):
        invoke(tmp_path, "print('saved')")
    assert (tmp_path / "attempt/stdout.bin").read_bytes() == b"saved\n"
    assert not (tmp_path / "attempt/process.json").exists()


def test_interrupt_cleans_up_publishes_and_reraises(tmp_path, monkeypatch):
    calls = []
    class Process:
        pid = 123
        returncode = None
        def communicate(self, **kwargs):
            calls.append("communicate")
            if self.returncode is None:
                raise KeyboardInterrupt()
            return b"partial-out", b"partial-err"
    process = Process()
    class Manager:
        def terminate(self):
            calls.append("terminate")
            process.returncode = -9
        def release(self, pid, fd):
            calls.append("release")
    monkeypatch.setattr(O, "ActiveCallManager", Manager)
    monkeypatch.setattr(O, "_start_contained_process", lambda *a, **k: (process, 17))
    with pytest.raises(KeyboardInterrupt):
        invoke(tmp_path, "pass")
    receipt = json.loads((tmp_path / "attempt/process.json").read_text())
    assert receipt["status"] == "interrupted"
    assert receipt["error_type"] == "KeyboardInterrupt"
    assert (tmp_path / "attempt/stdout.bin").read_bytes() == b"partial-out"
    assert (tmp_path / "attempt/stderr.bin").read_bytes() == b"partial-err"
    assert calls[:3] == ["communicate", "terminate", "communicate"]
    assert calls[-1] == "release"


def test_launch_handoff_interrupt_terminates_manager_without_process_handle(tmp_path, monkeypatch):
    terminated = []
    class Manager:
        def terminate(self):
            terminated.append(True)
    def interrupted_start(*args, **kwargs):
        raise KeyboardInterrupt()
    monkeypatch.setattr(O, "ActiveCallManager", Manager)
    monkeypatch.setattr(O, "_start_contained_process", interrupted_start)
    with pytest.raises(KeyboardInterrupt):
        invoke(tmp_path, "pass")
    assert terminated == [True]
    assert not json.loads((tmp_path / "attempt/process.json").read_text())["comparison_validated"]
