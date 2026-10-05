"""Synthetic authenticated panel-worker boundary tests."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import observation_worker as worker


@pytest.mark.parametrize("flag", ["--verify-panel-runtime", "--capture-panel-runtime"])
def test_qualification_cli_never_dispatches_owner_or_collection(monkeypatch, flag):
    calls = []
    def forbidden(*args, **kwargs):
        pytest.fail("qualification must not dispatch")
    monkeypatch.setattr(worker, "run_owner_packet", forbidden)
    monkeypatch.setattr(worker, "run_panel_packet", forbidden)
    monkeypatch.setattr(worker, "run_packet", forbidden)
    monkeypatch.setattr(worker, "qualify_panel_runtime",
                        lambda *a, **kw: calls.append((a, kw)))
    suffix = [flag] + (["/runtime.json"] if "capture" in flag else [])
    worker.main(["--panel", "--packet", "/packet", "--sha256", "a" * 64, *suffix])
    assert calls == [(("/packet", "a" * 64), {
        "destination": "/runtime.json" if "capture" in flag else None})]
    for flags in ([], ["--panel", "--admit"]):
        with pytest.raises(SystemExit) as error:
            worker.main([*flags, "--packet", "/packet", "--sha256", "a" * 64, *suffix])
        assert error.value.code == 2
    assert len(calls) == 1


def test_qualification_authenticates_before_import(monkeypatch):
    def refuse(*args, **kwargs):
        raise ValueError("bad source digest")
    monkeypatch.setattr(worker, "_bootstrap", refuse)
    monkeypatch.setattr(worker, "_import_application", lambda *a, **kw: pytest.fail("import"))
    with pytest.raises(ValueError, match="bad source digest"):
        worker.qualify_panel_runtime("/packet", "a" * 64)


@pytest.fixture
def qualification(monkeypatch, tmp_path):
    server = tmp_path / "source/server"
    server.mkdir(parents=True)
    baseline = dict(source_root=str(server), source_files={"worker.py": "sha"},
                    environment={"SHENGJI_FAST": "1"}, dependency_files={"old-driver": "sha"})
    current = dict(baseline, dependency_files={"actual-worker-dependency": "sha"})
    calls = []
    def capture(source, *, profile):
        calls.append("capture")
        assert source == server and profile == "panel"
        return current
    def admit(manifest, *, profile):
        calls.append("verify")
        assert manifest is baseline and profile == "panel"
        return SimpleNamespace(check=lambda: True)
    adapter = SimpleNamespace(capture=capture, ObservationRuntime=admit)
    monkeypatch.setattr(worker, "_bootstrap", lambda *a, **kw: ({}, server, baseline))
    monkeypatch.setattr(worker, "_import_application",
                        lambda *a, **kw: (None, adapter, None, None, None))
    return server, baseline, current, calls, adapter


def test_qualification_capture_is_exclusive_and_preserves_source(qualification, tmp_path):
    server, baseline, current, calls, _ = qualification
    output = tmp_path / "runtime.json"
    worker.qualify_panel_runtime("/packet", "a" * 64, destination=output)
    assert json.loads(output.read_bytes()) == current
    assert baseline["dependency_files"] == {"old-driver": "sha"}
    with pytest.raises(ValueError, match="exists"):
        worker.qualify_panel_runtime("/packet", "a" * 64, destination=output)
    with pytest.raises(ValueError, match="outside"):
        worker.qualify_panel_runtime("/packet", "a" * 64, destination=server / "new.json")
    assert calls == ["capture"]


@pytest.mark.parametrize("key", ["source_root", "source_files", "environment"])
def test_qualification_rejects_material_drift(qualification, tmp_path, key):
    _, _, current, _, _ = qualification
    current[key] = "changed"
    output = tmp_path / "runtime.json"
    with pytest.raises(ValueError, match="qualified application changed"):
        worker.qualify_panel_runtime("/packet", "a" * 64, destination=output)
    assert not output.exists()


def test_qualification_verify_is_read_only_and_requires_check(qualification, tmp_path):
    _, baseline, _, calls, adapter = qualification
    worker.qualify_panel_runtime("/packet", "a" * 64)
    assert calls == ["verify"]
    adapter.ObservationRuntime = lambda *a, **kw: SimpleNamespace(check=lambda: False)
    with pytest.raises(ValueError, match="verification failed"):
        worker.qualify_panel_runtime("/packet", "a" * 64)
    assert list(tmp_path.iterdir()) == [tmp_path / "source"]


def _write_packet(tmp_path: Path, packet: dict) -> tuple[Path, str]:
    path = tmp_path / "panel.json"
    raw = json.dumps(packet, sort_keys=True, separators=(",", ":")).encode()
    path.write_bytes(raw)
    return path, hashlib.sha256(raw).hexdigest()


def _packet():
    keys = set(worker._PACKET_KEYS) - {"read_complete"}
    packet = {key: None for key in keys}
    packet.update(schema="m9-panel-admission-v1", timeout_seconds=1,
                  process_timeout_seconds=31)
    return packet


def test_panel_packet_schema_isolated_from_original(tmp_path: Path) -> None:
    panel, digest = _write_packet(tmp_path, _packet())
    assert worker._read_packet(str(panel), digest, panel=True)[1]["schema"] == (
        "m9-panel-admission-v1")
    with pytest.raises(ValueError, match="exact M9 packet"):
        worker._read_packet(str(panel), digest)


def test_panel_authentication_precedes_application_import(monkeypatch) -> None:
    calls = []

    def bootstrap(*args, **kwargs):
        calls.append("bootstrap")
        raise ValueError("packet authentication refused")

    monkeypatch.setattr(worker, "_bootstrap", bootstrap)
    monkeypatch.setattr(worker, "_import_application",
                        lambda *args, **kwargs: calls.append("import"))
    with pytest.raises(ValueError, match="authentication refused"):
        worker.run_panel_packet("/packet", "a" * 64)
    assert calls == ["bootstrap"]


def test_cli_panel_and_admit_dispatch(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(worker, "run_panel_packet",
                        lambda *args: calls.append(("child", args)))
    monkeypatch.setattr(worker, "run_owner_packet",
                        lambda *args, **kwargs: calls.append(("owner", args, kwargs)) or
                        {"status": "exited", "returncode": 0})
    worker.main(["--panel", "--packet", "/p", "--sha256", "a" * 64])
    worker.main(["--panel", "--admit", "--packet", "/p", "--sha256", "a" * 64])
    assert calls == [
        ("child", ("/p", "a" * 64)),
        ("owner", ("/p", "a" * 64), {"panel": True}),
    ]


def test_panel_deadline_requires_strict_positive_integer(monkeypatch, tmp_path: Path) -> None:
    packet = _packet()
    packet["recipe"] = {"source_root": str(tmp_path), "python": sys.executable}
    packet["hostname"] = worker.socket.gethostname()
    packet["environment"] = {}
    monkeypatch.setattr(worker, "_bootstrap",
                        lambda *args, **kwargs: (packet, tmp_path / "server", {}))
    recipe = SimpleNamespace(validate_panel_recipe=lambda value: None)
    runtime = SimpleNamespace(ENVIRONMENT={}, ObservationRuntime=object)
    guards = SimpleNamespace()
    monkeypatch.setattr(worker, "_import_application",
                        lambda *args, **kwargs: (recipe, runtime, guards, None, None))
    for invalid in (True, 0, -1, 1.5):
        packet["timeout_seconds"] = invalid
        with pytest.raises(ValueError, match="timeout_seconds"):
            worker.run_panel_packet("/packet", "a" * 64)
