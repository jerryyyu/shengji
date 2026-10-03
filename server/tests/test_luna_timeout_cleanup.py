"""Deterministic deadline/cancellation ownership races; no real signals/RPCs."""
import json
import signal
import subprocess

import pytest

from shengji.luna import transport


@pytest.mark.parametrize("first", ["cancel", "deadline"])
def test_deadline_and_cancel_signal_once_and_preserve_evidence(
        tmp_path, monkeypatch, first):
    manager = transport.ActiveCallManager()
    signals, closures = [], []
    fake_pid, fake_fd = 910001, 910002
    real_close = transport.os.close

    class Process:
        pid = fake_pid
        returncode = None
        calls = 0

        def communicate(self, input=None, timeout=None):
            self.calls += 1
            if self.calls == 1:
                if first == "cancel":
                    manager.terminate()
                raise subprocess.TimeoutExpired("synthetic provider", timeout,
                                                output=b"prefix")
            self.returncode = -signal.SIGKILL
            return b"prefix-tail", b"diagnostic"

        def poll(self):
            return self.returncode

    process = Process()

    def start(*args, **kwargs):
        manager.register(fake_pid, fake_fd)
        return process, fake_fd

    def close(fd):
        if fd == fake_fd:
            closures.append(fd)
        else:
            real_close(fd)

    def killpg(pid, sig):
        assert pid == fake_pid
        signals.append((pid, sig))
        if len(signals) > 1:
            raise PermissionError("synthetic reused group refuses second signal")
        process.returncode = -signal.SIGKILL
        if first == "deadline":
            manager.terminate()

    monkeypatch.setattr(transport, "_start_contained_process", start)
    monkeypatch.setattr(transport.os, "close", close)
    monkeypatch.setattr(transport.os, "killpg", killpg)
    with pytest.raises(transport.CodexProviderResourceError, match="deadline"):
        transport._default_run(("synthetic",), b"", tmp_path, 1,
                               _active_call_manager=manager)
    assert signals == [(fake_pid, signal.SIGKILL)]
    assert closures == [fake_fd]
    assert process.calls == 2
    assert not manager._calls
    assert (tmp_path / "stdout.jsonl").read_bytes() == b"prefix-tail"
    assert (tmp_path / "stderr.txt").read_bytes() == b"diagnostic"
    receipt = json.loads((tmp_path / "timeout.json").read_text())
    assert receipt["accepted"] is False
    assert receipt["returncode"] == -signal.SIGKILL
