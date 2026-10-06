"""Focused tests for the optional pinned watchdog-script adapter."""

from __future__ import annotations

import os
from pathlib import Path
import sys
import time

import pytest

from shengji.luna import transport


class _CapturedProcess:
    pid = 8123


def test_default_watchdog_wrapper_uses_source_adjacent_isolated_script(tmp_path, monkeypatch):
    captured: dict[str, object] = {}

    def capture(argv, **kwargs):
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        return _CapturedProcess()

    monkeypatch.setattr(transport.subprocess, "Popen", capture)
    manager = transport.ActiveCallManager()
    process, watchdog_fd = transport._start_contained_process(
        ("provider", "--flag"), workspace=tmp_path, env={},
        active_calls=manager)
    try:
        assert process.pid == 8123
        assert captured["argv"] == (
            sys.executable, "-I", "-B",
            str(Path(transport.__file__).absolute().with_name("watchdog.py")),
            str(captured["kwargs"]["pass_fds"][0]), "provider", "--flag")
    finally:
        manager.release(process.pid, watchdog_fd)


def test_explicit_watchdog_wrapper_uses_isolated_script(tmp_path, monkeypatch):
    script = tmp_path / "watchdog.py"
    script.write_text("# synthetic watchdog\n")
    captured: dict[str, object] = {}

    def capture(argv, **kwargs):
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        return _CapturedProcess()

    monkeypatch.setattr(transport.subprocess, "Popen", capture)
    manager = transport.ActiveCallManager()
    process, watchdog_fd = transport._start_contained_process(
        ("provider", "--flag"), workspace=tmp_path, env={},
        active_calls=manager, watchdog_script=script)
    try:
        assert captured["argv"] == (
            sys.executable, "-I", "-B", str(script),
            str(captured["kwargs"]["pass_fds"][0]), "provider", "--flag")
    finally:
        manager.release(process.pid, watchdog_fd)


@pytest.mark.parametrize("path_kind", ("relative", "missing", "symlink"))
def test_invalid_watchdog_script_is_rejected_before_pipe(tmp_path, monkeypatch,
                                                         path_kind):
    target = tmp_path / "target.py"
    target.write_text("# target\n")
    if path_kind == "relative":
        script = Path("watchdog.py")
    elif path_kind == "missing":
        script = tmp_path / "missing.py"
    else:
        script = tmp_path / "watchdog-link.py"
        script.symlink_to(target)

    def pipe_must_not_be_called():
        raise AssertionError("pipe created before watchdog validation")

    monkeypatch.setattr(transport.os, "pipe", pipe_must_not_be_called)
    with pytest.raises(ValueError, match="absolute regular nonsymlink"):
        transport._start_contained_process(
            ("provider",), workspace=tmp_path, env={},
            active_calls=transport.ActiveCallManager(), watchdog_script=script)


def test_explicit_watchdog_runs_child_and_manager_cleanup(tmp_path):
    watchdog = Path(transport.__file__).with_name("watchdog.py").resolve()
    manager = transport.ActiveCallManager()
    process, watchdog_fd = transport._start_contained_process(
        (sys.executable, "-c",
         "import sys; sys.stdout.write('OUT'); sys.stderr.write('ERR'); "
         "raise SystemExit(7)"),
        workspace=tmp_path, env=dict(os.environ), active_calls=manager,
        watchdog_script=watchdog)
    try:
        stdout, stderr = process.communicate(input=b"prompt", timeout=5)
        assert (process.returncode, stdout, stderr) == (7, b"OUT", b"ERR")
    finally:
        manager.release(process.pid, watchdog_fd)
        if process.poll() is None:
            os.killpg(process.pid, 9)
            process.wait(timeout=5)
    with manager._lock:
        assert manager._calls == {}
    with pytest.raises(OSError):
        os.fstat(watchdog_fd)


def test_explicit_watchdog_kills_child_when_controller_fd_closes(tmp_path):
    watchdog = Path(transport.__file__).with_name("watchdog.py").resolve()
    pid_path = tmp_path / "provider.pid"
    command = (
        sys.executable, "-c",
        "import os,pathlib,sys,time; "
        "pathlib.Path(sys.argv[1]).write_text(str(os.getpid())); "
        "time.sleep(60)", str(pid_path))
    manager = transport.ActiveCallManager()
    process, watchdog_fd = transport._start_contained_process(
        command, workspace=tmp_path, env=dict(os.environ),
        active_calls=manager, watchdog_script=watchdog)
    provider_pid = None
    try:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and not pid_path.exists():
            time.sleep(0.01)
        assert pid_path.exists()
        provider_pid = int(pid_path.read_text())
        os.close(watchdog_fd)
        watchdog_fd = -1
        process.wait(timeout=5)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                os.kill(provider_pid, 0)
            except ProcessLookupError:
                break
            time.sleep(0.01)
        with pytest.raises(ProcessLookupError):
            os.kill(provider_pid, 0)
    finally:
        if watchdog_fd >= 0:
            manager.release(process.pid, watchdog_fd)
        if process.poll() is None:
            os.killpg(process.pid, 9)
            process.wait(timeout=5)
        if provider_pid is not None:
            try:
                os.kill(provider_pid, 9)
            except ProcessLookupError:
                pass
