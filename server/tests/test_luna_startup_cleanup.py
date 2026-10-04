"""Synthetic startup handoff interruptions must not orphan a process group."""
import os
from pathlib import Path
import sys
import threading
import io
import subprocess

import pytest

from shengji.luna import transport as T


@pytest.mark.parametrize("insert_first", [False, True])
def test_registration_interrupt_cleans_fd_and_reaps_wrapper(tmp_path, monkeypatch, insert_first):
    manager = T.ActiveCallManager()
    real_popen = T.subprocess.Popen
    real_register = manager._register_handoff
    captured = {}

    def popen(*args, **kwargs):
        process = real_popen(*args, **kwargs)
        captured["process"] = process
        return process

    def register(pid, fd):
        captured["fd"] = fd
        if insert_first:
            real_register(pid, fd)
        raise KeyboardInterrupt()

    monkeypatch.setattr(T.subprocess, "Popen", popen)
    monkeypatch.setattr(manager, "_register_handoff", register)
    try:
        with pytest.raises(KeyboardInterrupt):
            T._start_contained_process(
                (sys.executable, "-c", "import time; time.sleep(60)"),
                workspace=tmp_path, env=dict(os.environ), active_calls=manager,
                watchdog_script=Path(T.__file__).with_name("watchdog.py").resolve())
        assert captured["process"].poll() is not None
        assert manager._calls == {}
        with pytest.raises(OSError):
            os.fstat(captured["fd"])
    finally:
        process = captured.get("process")
        if process is not None and process.poll() is None:
            os.killpg(process.pid, 9)
            process.communicate(timeout=5)


def test_stopped_manager_refuses_before_spawn(tmp_path, monkeypatch):
    manager = T.ActiveCallManager()
    manager.terminate()
    def refuse(*a, **k):
        raise AssertionError("stopped manager spawned")
    monkeypatch.setattr(T.subprocess, "Popen", refuse)
    with pytest.raises(T.CodexProviderResourceError, match="registration refused"):
        T._start_contained_process(("unused",), workspace=tmp_path, env={},
                                   active_calls=manager)


def test_public_register_still_cleans_refused_resources(monkeypatch):
    manager = T.ActiveCallManager()
    manager.terminate()
    read_fd, write_fd = os.pipe()
    signals = []
    monkeypatch.setattr(T.os, "killpg", lambda pid, sig: signals.append((pid, sig)))
    try:
        with pytest.raises(T.CodexProviderResourceError, match="registration refused"):
            manager.register(12345, write_fd)
        with pytest.raises(OSError):
            os.fstat(write_fd)
        assert signals == [(12345, T.signal.SIGKILL)]
    finally:
        os.close(read_fd)


def test_cancellation_waits_for_interrupted_transfer(tmp_path, monkeypatch):
    manager = T.ActiveCallManager()
    real_register = manager._register_handoff
    attempted = threading.Event()
    finished = threading.Event()
    thread = None
    def cancel():
        attempted.set()
        manager.terminate()
        finished.set()
    def register(pid, fd):
        nonlocal thread
        real_register(pid, fd)
        thread = threading.Thread(target=cancel)
        thread.start()
        assert attempted.wait(2)
        assert not finished.wait(0.05)
        raise KeyboardInterrupt()
    monkeypatch.setattr(manager, "_register_handoff", register)
    try:
        with pytest.raises(KeyboardInterrupt):
            T._start_contained_process(
                (sys.executable, "-c", "import time; time.sleep(60)"),
                workspace=tmp_path, env=dict(os.environ), active_calls=manager,
                watchdog_script=Path(T.__file__).with_name("watchdog.py").resolve())
    finally:
        if thread is not None:
            thread.join(timeout=5)
    assert finished.is_set() and manager._calls == {}


@pytest.mark.parametrize("reap_timeout", [False, True])
def test_signal_permission_error_always_reaps_preserves_interrupt(
        tmp_path, monkeypatch, reap_timeout):
    manager = T.ActiveCallManager()
    events = []
    captured = {}
    original = KeyboardInterrupt("original interrupt")
    class Process:
        pid = 12345
        returncode = None
        stdin, stdout, stderr = io.BytesIO(), io.BytesIO(), io.BytesIO()
        def poll(self):
            return None
        def communicate(self, *, timeout):
            events.append("reap")
            assert timeout == 5
            if reap_timeout:
                raise subprocess.TimeoutExpired("synthetic", timeout)
            self.returncode = -9
            return b"", b""
    process = Process()
    def handoff(pid, fd):
        captured["fd"] = fd
        raise original
    real_close = os.close
    def close(fd):
        if fd == captured.get("fd"):
            events.append("close")
        real_close(fd)
    def signal(pid, sig):
        events.append("signal")
        raise PermissionError("synthetic zombie-only group")
    monkeypatch.setattr(T.subprocess, "Popen", lambda *a, **k: process)
    monkeypatch.setattr(manager, "_register_handoff", handoff)
    monkeypatch.setattr(T.os, "killpg", signal)
    monkeypatch.setattr(T.os, "close", close)
    with pytest.raises(KeyboardInterrupt) as raised:
        T._start_contained_process(("unused",), workspace=tmp_path, env={},
                                   active_calls=manager)
    assert raised.value is original
    assert events == ["signal", "close", "reap"]
    assert "Startup group signal" in original.__notes__[0]
    if reap_timeout:
        assert "reap incomplete" in original.__notes__[1]
        assert all(s.closed for s in (process.stdin, process.stdout, process.stderr))
    with pytest.raises(OSError):
        os.fstat(captured["fd"])


def test_terminate_signals_before_close_and_tolerates_zombie_permission(monkeypatch):
    manager = T.ActiveCallManager()
    read_fd, write_fd = os.pipe()
    manager.register(12345, write_fd)
    events = []
    real_close = os.close
    def signal(pid, sig):
        events.append("signal")
        raise PermissionError("synthetic zombie-only group")
    def close(fd):
        events.append("close")
        real_close(fd)
    monkeypatch.setattr(T.os, "killpg", signal)
    monkeypatch.setattr(T.os, "close", close)
    try:
        manager.terminate()
        assert events == ["signal", "close"]
        assert manager._calls == {}
        with pytest.raises(OSError):
            os.fstat(write_fd)
    finally:
        real_close(read_fd)
