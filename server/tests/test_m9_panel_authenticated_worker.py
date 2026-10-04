"""Synthetic authenticated panel-worker boundary tests."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import observation_worker as worker


def _write_packet(tmp_path: Path, packet: dict) -> tuple[Path, str]:
    path = tmp_path / "panel.json"
    raw = json.dumps(packet, sort_keys=True, separators=(",", ":")).encode()
    path.write_bytes(raw)
    return path, hashlib.sha256(raw).hexdigest()


def _packet():
    keys = set(worker._PACKET_KEYS) - {"read_complete"}
    packet = {key: None for key in keys}
    packet.update(schema="m9-panel-admission-v1", timeout_seconds=1)
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
