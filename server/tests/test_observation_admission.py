"""Synthetic admission-boundary tests; no model, remote, or real launch."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sys

import pytest

from shengji.eval import observation_admission as admission
from shengji.eval.observation_queue import write_exclusive_json


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Build a complete packet while replacing only expensive/host gates."""
    root = tmp_path / "repo"
    server = root / "server"
    (server / "scripts").mkdir(parents=True)
    (server / "scripts" / "observation_worker.py").write_text("# checked worker\n")
    model = tmp_path / "model.bin"
    fixtures = tmp_path / "fixtures.jsonl"
    model.write_bytes(b"synthetic model")
    fixtures.write_bytes(b"synthetic fixtures\n")

    output_dir = tmp_path / "output"
    evidence_dir = tmp_path / "evidence"
    output_dir.mkdir()
    evidence_dir.mkdir()
    output = output_dir / "comparison.json"
    evidence = evidence_dir / "process"

    queue_dir = tmp_path / "queue"
    queue_dir.mkdir()
    reservation = queue_dir / "v49tc.json"
    launcher = tmp_path / "v49tc.launcher"
    status = tmp_path / "v49tc.status"
    launcher.write_text("synthetic v49tc launcher\n")
    status.write_text("2026-10-04T00:00:00Z v49tc LANE DONE\n")
    queue_record = {
        "schema": "claude-reservation-v1", "lane": "v49tc",
        "launcher": str(launcher), "launcher_sha256": _sha(launcher),
        "status": str(status), "seeds": [7], "count": 1,
    }
    reservation.write_bytes(json.dumps(queue_record, sort_keys=True,
                                       separators=(",", ":")).encode())
    queue = {"reservation_dir": str(queue_dir), "reservations": [{
        "path": str(reservation), "sha256": _sha(reservation), "lane": "v49tc",
        "launcher": str(launcher), "launcher_sha256": _sha(launcher),
        "status": str(status), "pid": 999999,
        "terminal_suffix": "v49tc LANE DONE",
    }]}

    runtime_path = tmp_path / "runtime.json"
    runtime_path.write_text(json.dumps({"source_root": str(server)}))
    watchdog = tmp_path / "watchdog.py"
    watchdog.write_text("# synthetic watchdog\n")
    read_complete = tmp_path / "read-complete.json"
    read_complete.write_text("{\"read_complete\":true}\n")
    monkeypatch.setattr(admission, "READ_RECEIPT_SHA", _sha(read_complete))

    release = tmp_path / "RELEASE.json"
    hold = tmp_path / "HOLD"
    host_lock = tmp_path / "host.lock"
    peer_lock = tmp_path / "peer.lock"
    own_reservation = queue_dir / "m9.json"
    terminal_status = tmp_path / "terminal-status.json"
    claim = tmp_path / "claim.json"
    recipe = {
        "python": sys.executable, "source_root": str(root),
        "model": str(model), "fixtures": str(fixtures),
        "output": str(output), "evidence": str(evidence),
        "seeds": [0, 1, 2], "fill_seed": 0, "timeout_seconds": 600,
        "model_sha256": _sha(model), "fixture_sha256": _sha(fixtures),
    }
    packet = {
        "schema": admission.SCHEMA, "recipe": recipe,
        "environment": dict(admission.ENVIRONMENT),
        "source_commit": "a" * 40, "hostname": admission.socket.gethostname(),
        "runtime": {"path": str(runtime_path), "sha256": _sha(runtime_path)},
        "watchdog": {"path": str(watchdog), "sha256": _sha(watchdog)},
        "read_complete": {"path": str(read_complete), "sha256": _sha(read_complete)},
        "queue": queue, "release": str(release), "hold": str(hold),
        "host_lock": str(host_lock), "other_locks": [str(peer_lock)],
        "reservation": str(own_reservation), "status": str(terminal_status),
        "claim": str(claim),
    }
    packet_path = tmp_path / "packet.json"
    packet_raw = json.dumps(packet, sort_keys=True, separators=(",", ":")).encode()
    packet_path.write_bytes(packet_raw)
    packet_sha = hashlib.sha256(packet_raw).hexdigest()
    write_exclusive_json(release, {"schema": "m9-release-v1", "packet_sha256": packet_sha})

    class Runtime:
        def __init__(self, manifest):
            assert manifest == {"source_root": str(server)}

        def check(self):
            return True

    monkeypatch.setattr(admission, "HOST_LOCK", host_lock)
    monkeypatch.setattr(admission, "validate_recipe", lambda recipe: None)
    monkeypatch.setattr(admission, "build_observation_command", lambda recipe: ("synthetic",))
    monkeypatch.setattr(admission, "_source", lambda source, commit: None)
    monkeypatch.setattr(admission, "_quiet_host", lambda: None)
    monkeypatch.setattr(admission, "ObservationRuntime", Runtime)
    monkeypatch.setattr(admission.guards, "capture_queue", lambda spec: {"queue": "snapshot"})
    monkeypatch.setattr(admission.guards, "queue_unchanged", lambda *args, **kwargs: True)
    return packet_path, packet_sha, packet, {
        "root": root, "output": output, "evidence": evidence, "release": release,
        "hold": hold, "host_lock": host_lock, "reservation": own_reservation,
        "status": terminal_status, "claim": claim, "queue": queue,
    }


def test_success_uses_checked_worker_argv_owner_claim_and_releases_after_drain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    packet_path, packet_sha, packet, paths = _fixture(tmp_path, monkeypatch)
    seen = {}

    def child(command, **kwargs):
        seen["command"] = command
        seen["claim"] = json.loads(paths["claim"].read_text())
        seen["kwargs"] = kwargs
        return {"status": "exited", "returncode": 0}

    monkeypatch.setattr(admission, "run_observation_process", child)
    result = admission.run_packet(packet_path, packet_sha)

    assert result == {"status": "exited", "returncode": 0}
    assert seen["command"] == (
        packet["recipe"]["python"], "-I", "-B",
        str(paths["root"] / "server/scripts/observation_worker.py"),
        "--packet", str(packet_path), "--sha256", packet_sha,
    )
    assert seen["claim"]["owner_pid"] == os.getpid()
    assert seen["claim"]["status"] == "spent_no_retry"
    assert seen["kwargs"]["workspace"] == paths["root"] / "server"
    assert not paths["host_lock"].exists()
    assert json.loads(paths["status"].read_text())["process_status"] == "exited"


@pytest.mark.parametrize("blocker", ["release", "hold", "output"])
def test_pre_dispatch_blockers_refuse_without_child(tmp_path, monkeypatch, blocker):
    packet_path, packet_sha, _, paths = _fixture(tmp_path, monkeypatch)
    if blocker == "release":
        paths["release"].unlink()
    elif blocker == "hold":
        paths["hold"].write_text("HOLD\n")
    else:
        paths["output"].write_text("occupied\n")
    calls = []
    monkeypatch.setattr(admission, "run_observation_process", lambda *a, **k: calls.append(1))

    with pytest.raises(ValueError):
        admission.run_packet(packet_path, packet_sha)
    assert calls == []
    assert not paths["claim"].exists()
    assert not paths["host_lock"].exists()


def test_queue_drift_refuses_before_dispatch_and_retains_lease(tmp_path, monkeypatch):
    packet_path, packet_sha, _, paths = _fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(admission.guards, "queue_unchanged", lambda *a, **k: False)
    calls = []
    monkeypatch.setattr(admission, "run_observation_process", lambda *a, **k: calls.append(1))

    with pytest.raises(ValueError, match="admission changed"):
        admission.run_packet(packet_path, packet_sha)
    assert calls == []
    assert paths["host_lock"].is_dir()
    assert paths["host_lock"].joinpath("owner").read_text().startswith("m9 ")


def test_post_lease_error_retains_lease(tmp_path, monkeypatch):
    packet_path, packet_sha, _, paths = _fixture(tmp_path, monkeypatch)
    quiet_calls = []

    def quiet():
        quiet_calls.append(1)
        if len(quiet_calls) == 2:
            raise ValueError("post-lease check")

    monkeypatch.setattr(admission, "_quiet_host", quiet)
    monkeypatch.setattr(admission, "run_observation_process",
                        lambda *a, **k: pytest.fail("dispatch after post-lease error"))

    with pytest.raises(ValueError, match="post-lease check"):
        admission.run_packet(packet_path, packet_sha)
    assert paths["host_lock"].is_dir()


def test_child_exception_retains_lease(tmp_path, monkeypatch):
    packet_path, packet_sha, _, paths = _fixture(tmp_path, monkeypatch)

    def child(*args, **kwargs):
        raise RuntimeError("synthetic child failure")

    monkeypatch.setattr(admission, "run_observation_process", child)
    with pytest.raises(RuntimeError, match="synthetic child failure"):
        admission.run_packet(packet_path, packet_sha)
    assert paths["host_lock"].is_dir()
    assert not paths["status"].exists()


def test_timeout_receipt_after_drain_releases_lease(tmp_path, monkeypatch):
    packet_path, packet_sha, _, paths = _fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(admission, "run_observation_process",
                        lambda *a, **k: {"status": "timeout", "returncode": -15})

    receipt = admission.run_packet(packet_path, packet_sha)
    assert receipt == {"status": "timeout", "returncode": -15}
    assert not paths["host_lock"].exists()
    assert json.loads(paths["status"].read_text())["process_status"] == "timeout"


def test_spent_claim_prevents_second_attempt(tmp_path, monkeypatch):
    packet_path, packet_sha, _, paths = _fixture(tmp_path, monkeypatch)
    calls = []
    monkeypatch.setattr(admission, "run_observation_process",
                        lambda *a, **k: (calls.append(1) or
                                         {"status": "exited", "returncode": 0}))

    admission.run_packet(packet_path, packet_sha)
    with pytest.raises(ValueError, match="fresh artifact"):
        admission.run_packet(packet_path, packet_sha)
    assert calls == [1]


@pytest.mark.parametrize(
    "argv,parent,allowed",
    [
        (("/usr/bin/python3", "/usr/bin/networkd-dispatcher",
          "--run-startup-triggers"), 1, True),
        (("/usr/bin/python3", "/usr/share/unattended-upgrades/"
          "unattended-upgrade-shutdown", "--wait-for-signal"), 1, True),
        (("/usr/bin/python3", "/usr/bin/networkd-dispatcher",
          "--run-startup-triggers"), 2, False),
        (("/usr/bin/python3", "/usr/bin/networkd-dispatcher",
          "--run-startup-triggers", "--arm"), 1, False),
    ],
)
def test_quiet_host_exempts_only_exact_init_owned_services(monkeypatch, argv, parent, allowed):
    current = os.getpid()

    class ProcPath:
        def __init__(self, raw):
            self.raw = str(raw)

        @property
        def name(self):
            return self.raw.rsplit("/", 1)[-1]

        def __truediv__(self, child):
            return ProcPath(f"{self.raw}/{child}")

        def iterdir(self):
            assert self.raw == "/proc"
            return [ProcPath("/proc/1"), ProcPath(f"/proc/{current}"),
                    ProcPath("/proc/2001")]

        def read_text(self):
            if self.raw == f"/proc/{current}/stat":
                return f"{current} (test) S 1 0 0 0 0"
            if self.raw == "/proc/1/stat":
                return "1 (init) S 0 0 0 0 0"
            if self.raw == "/proc/2001/stat":
                return f"2001 (service) S {parent} 0 0 0 0"
            raise AssertionError(self.raw)

        def read_bytes(self):
            assert self.raw == "/proc/2001/cmdline"
            return b"\0".join(part.encode() for part in argv) + b"\0"

        def exists(self):
            return True

    monkeypatch.setattr(admission, "Path", ProcPath)
    monkeypatch.setattr(admission.sys, "platform", "linux")
    if allowed:
        admission._quiet_host()
    else:
        with pytest.raises(ValueError, match="live peer"):
            admission._quiet_host()
