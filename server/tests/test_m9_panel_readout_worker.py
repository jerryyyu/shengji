"""Synthetic boundary tests for the authenticated M9 readout bootstrap."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from scripts import m9_panel_readout_worker as worker


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode()


def _invocation(tmp_path: Path) -> tuple[dict, Path]:
    runtime_path = tmp_path / "runtime.json"
    runtime_path.write_bytes(b"{}")
    files = {
        f"input-{index:02d}": {
            "path": str(tmp_path / f"input-{index:02d}.json"),
            "sha256": f"{index + 1:064x}",
        }
        for index in range(20)
    }
    value = {
        "schema": "m9-panel-readout-invocation-v1",
        "files": files,
        "packet_sha256": "a" * 64,
        "collection_packet": {"path": str(tmp_path / "collection-packet.json"),
                              "sha256": "a" * 64},
        "output_dir": str(tmp_path / "output"),
        "runtime": {"path": str(runtime_path), "sha256": _sha(b"{}")},
    }
    path = tmp_path / "invocation.json"
    path.write_bytes(_canonical(value))
    return value, path


def _load_actual_helper():
    path = Path(worker.__file__).with_name("observation_worker.py")
    return worker._load_helper(_sha(path.read_bytes()))


def test_module_load_is_stdlib_only_and_helper_runs_under_non_main_name():
    assert worker._HELPER_NAME != "__main__"
    before = set(sys.modules)
    helper = _load_actual_helper()
    assert helper.__name__ == worker._HELPER_NAME
    assert helper.__file__ == str(Path(worker.__file__).with_name("observation_worker.py"))
    assert not any(name == "shengji" or name.startswith("shengji.")
                   for name in set(sys.modules) - before)


def test_wrong_helper_and_invocation_digest_refuse_before_parsing(tmp_path: Path):
    helper_path = Path(worker.__file__).with_name("observation_worker.py")
    with pytest.raises(ValueError, match="bootstrap helper SHA mismatch"):
        worker._load_helper("0" * 64)

    invocation = tmp_path / "invocation.json"
    invocation.write_bytes(b"not json")
    helper = _load_actual_helper()
    with pytest.raises(ValueError, match="invocation SHA mismatch"):
        worker._read_invocation(helper, str(invocation), _sha(b"different"))
    assert helper_path.is_file()


def test_invocation_requires_canonical_bytes_and_runtime_pin(tmp_path: Path):
    invocation, path = _invocation(tmp_path)
    helper = _load_actual_helper()
    digest = _sha(path.read_bytes())
    assert worker._read_invocation(helper, str(path), digest) == invocation

    path.write_text(json.dumps(invocation, indent=2))
    with pytest.raises(ValueError, match="canonical"):
        worker._read_invocation(helper, str(path), _sha(path.read_bytes()))

    invocation.pop("runtime")
    path.write_bytes(_canonical(invocation))
    with pytest.raises(ValueError, match="exact M9 panel readout invocation"):
        worker._read_invocation(helper, str(path), _sha(path.read_bytes()))


def test_collection_packet_digest_mismatch_refuses_before_parse(tmp_path, monkeypatch):
    packet_path = tmp_path / "collection-packet.json"
    packet_path.write_bytes(b"not the authenticated packet")
    invocation = {"collection_packet": {
        "path": str(packet_path), "sha256": _sha(b"different bytes")}}
    helper = _load_actual_helper()
    monkeypatch.setattr(helper, "_parse_object", lambda raw: pytest.fail(
        "packet parser must not run after digest mismatch"))
    with pytest.raises(ValueError, match="collection packet SHA mismatch"):
        worker._read_collection_packet(helper, invocation)


def test_collection_packet_requires_panel_schema_before_application(monkeypatch,
                                                                      tmp_path):
    packet_path = tmp_path / "collection-packet.json"
    raw = _canonical({"schema": "m9-admission-v1"})
    packet_path.write_bytes(raw)
    helper = _load_actual_helper()
    with pytest.raises(ValueError, match="exact M9 panel collection packet"):
        worker._read_collection_packet(helper, {
            "collection_packet": {"path": str(packet_path), "sha256": _sha(raw)}})


def test_fifo_collection_packet_is_refused_before_stable_read(monkeypatch,
                                                               tmp_path):
    if not hasattr(os, "mkfifo"):
        pytest.skip("FIFO unavailable")
    packet_path = tmp_path / "collection-packet.fifo"
    os.mkfifo(packet_path)
    helper = _load_actual_helper()
    monkeypatch.setattr(helper, "_stable_read", lambda *_: pytest.fail(
        "FIFO must be rejected before stable read"))
    with pytest.raises(ValueError, match="regular nonsymlink"):
        worker._read_collection_packet(helper, {
            "collection_packet": {"path": str(packet_path), "sha256": "a" * 64}})

def test_actual_helper_runtime_source_inventory_rejects_drift(tmp_path: Path):
    server = tmp_path / "server"
    (server / "shengji").mkdir(parents=True)
    (server / "scripts").mkdir()
    source_files = {}
    for relative, content in (("shengji/__init__.py", b"# synthetic\n"),
                              ("scripts/fixture.py", b"# synthetic\n")):
        path = server / relative
        path.write_bytes(content)
        source_files[relative] = _sha(content)
    runtime = {
        "schema": "shengji-m9-runtime-v1",
        "source_root": str(server),
        "source_files": source_files,
    }
    runtime_path = tmp_path / "runtime.json"
    runtime_path.write_bytes(_canonical(runtime))
    helper = _load_actual_helper()
    invocation = {"runtime": {"path": str(runtime_path),
                               "sha256": _sha(runtime_path.read_bytes())}}
    assert helper._read_runtime(invocation, server) == runtime
    (server / "scripts/fixture.py").write_bytes(b"# drift\n")
    with pytest.raises(ValueError, match="runtime source hash mismatch"):
        helper._read_runtime(invocation, server)


def test_fifo_helper_is_refused_without_opening(tmp_path: Path):
    if not hasattr(os, "mkfifo"):
        pytest.skip("FIFO unavailable")
    fifo = tmp_path / "helper.py"
    os.mkfifo(fifo)
    with pytest.raises(ValueError, match="regular nonsymlink"):
        worker._read_helper(fifo, "a" * 64)


def test_fifo_invocation_is_refused_before_stable_read(monkeypatch, tmp_path):
    if not hasattr(os, "mkfifo"):
        pytest.skip("FIFO unavailable")
    fifo = tmp_path / "invocation.json"
    os.mkfifo(fifo)
    helper = _load_actual_helper()
    monkeypatch.setattr(helper, "_stable_read", lambda *_: pytest.fail(
        "FIFO must be rejected before opening"))
    with pytest.raises(ValueError, match="regular nonsymlink"):
        worker._read_invocation(helper, str(fifo), "a" * 64)


def test_fifo_runtime_is_refused_before_runtime_reader(monkeypatch, tmp_path):
    if not hasattr(os, "mkfifo"):
        pytest.skip("FIFO unavailable")
    invocation, path = _invocation(tmp_path)
    fifo = tmp_path / "runtime-fifo.json"
    os.mkfifo(fifo)
    invocation["runtime"]["path"] = str(fifo)
    helper = SimpleNamespace(_read_runtime=lambda *_: pytest.fail(
        "FIFO must be rejected before runtime read"))
    monkeypatch.setattr(worker, "_runtime_gate", lambda: None)
    monkeypatch.setattr(worker, "_load_helper", lambda _: helper)
    monkeypatch.setattr(worker, "_read_invocation", lambda *_: invocation)
    monkeypatch.setattr(worker, "_read_collection_packet", lambda *_: (
        Path(invocation["collection_packet"]["path"]), {}))
    with pytest.raises(ValueError, match="regular nonsymlink"):
        worker.run(str(path), "a" * 64, "b" * 64)


@pytest.mark.parametrize("platform,isolated,no_bytecode,modules,refusal", [
    ("darwin", True, True, {}, "Linux"),
    ("linux", False, True, {}, "isolated"),
    ("linux", True, False, {}, "bytecode"),
    ("linux", True, True, {"scripts": object()}, "already"),
    ("linux", True, True, {"scripts.other": object()}, "already"),
    ("linux", True, True, {"shengji": object()}, "already"),
    ("linux", True, True, {"shengji.eval": object()}, "already"),
    ("linux", True, True, {}, None),
])
def test_runtime_gate_contract(monkeypatch, platform, isolated, no_bytecode,
                               modules, refusal):
    # Substitute only the worker's sys reference; do not disturb pytest's
    # process-global import cache or interpreter flags.
    monkeypatch.setattr(worker, "sys", SimpleNamespace(
        platform=platform, flags=SimpleNamespace(isolated=isolated),
        dont_write_bytecode=no_bytecode, modules=modules))
    if refusal is None:
        worker._runtime_gate()
    else:
        with pytest.raises(ValueError, match=refusal):
            worker._runtime_gate()


def test_runtime_source_failure_prevents_import_and_publication(monkeypatch, tmp_path):
    invocation, _ = _invocation(tmp_path)
    runtime_path = Path(invocation["runtime"]["path"])
    helper = SimpleNamespace(
        _read_runtime=lambda value, source: (_ for _ in ()).throw(
            ValueError("source pins refused")),
    )
    monkeypatch.setattr(worker, "_runtime_gate", lambda: None)
    monkeypatch.setattr(worker, "_load_helper", lambda digest: helper)
    monkeypatch.setattr(worker, "_read_invocation", lambda *args: invocation)
    monkeypatch.setattr(worker, "_read_collection_packet", lambda *_: (
        Path(invocation["collection_packet"]["path"]), {}))
    with pytest.raises(ValueError, match="source pins refused"):
        worker.run(str(tmp_path / "invocation.json"), "a" * 64, "b" * 64)
    assert runtime_path.is_file()
    assert not Path(invocation["output_dir"]).exists()


def test_runtime_manifest_must_bind_authenticated_helper_before_import(
        monkeypatch, tmp_path):
    invocation, _ = _invocation(tmp_path)
    manifest = {"source_files": {"scripts/observation_worker.py": "c" * 64}}
    helper = SimpleNamespace(_read_runtime=lambda value, source: manifest)
    monkeypatch.setattr(worker, "_runtime_gate", lambda: None)
    monkeypatch.setattr(worker, "_load_helper", lambda digest: helper)
    monkeypatch.setattr(worker, "_read_invocation", lambda *args: invocation)
    monkeypatch.setattr(worker, "_read_collection_packet", lambda *_: (
        Path(invocation["collection_packet"]["path"]), {}))
    with pytest.raises(ValueError, match="bind authenticated bootstrap"):
        worker.run(str(tmp_path / "invocation.json"), "a" * 64, "b" * 64)


def test_fresh_process_without_isolation_or_bytecode_flag_refuses(tmp_path: Path):
    result = subprocess.run(
        [sys.executable, str(Path(worker.__file__).resolve()),
         "/missing", "a" * 64, "b" * 64],
        capture_output=True, text=True, check=False, timeout=10,
    )
    assert result.returncode == 1
    assert result.stderr.strip() == "ValueError"
    assert "Traceback" not in result.stderr


def test_admitted_bootstrap_passes_runtime_check_and_invocation(monkeypatch, tmp_path):
    import importlib

    invocation, path = _invocation(tmp_path)
    digest = _sha(path.read_bytes())
    manifest = {"source_files": {"scripts/observation_worker.py": "b" * 64}}
    check = lambda: True
    seen = []

    def admit(value, *, profile):
        assert value is manifest
        assert profile == "panel-readout"
        seen.append("admitted")
        return SimpleNamespace(check=check)

    def publish(value, *, invocation_sha256, runtime_check, collection_packet):
        assert seen == ["admitted", "recipe"]
        assert value is invocation
        assert invocation_sha256 == digest
        assert runtime_check is check
        assert collection_packet["schema"] == "m9-panel-admission-v1"
        return {"synthetic": True}

    from test_m9_panel_recipe import recipe as recipe_fixture
    panel_recipe = recipe_fixture()
    panel_recipe.update(
        output_dir=str(tmp_path / "collection"),
        evidence=str(tmp_path / "evidence"),
        saved_readout=str(tmp_path / "saved-readout.json"),
    )
    packet = {key: None for key in _load_actual_helper()._PANEL_PACKET_KEYS}
    packet.update(schema="m9-panel-admission-v1", recipe=panel_recipe)
    monkeypatch.setattr(worker, "_read_collection_packet", lambda *_: (
        Path(invocation["collection_packet"]["path"]), packet))
    from shengji.eval.m9_panel_recipe import validate_panel_recipe
    def validate_recipe(value):
        validate_panel_recipe(value)
        seen.append("recipe")

    modules = {
        "shengji.eval.observation_runtime": SimpleNamespace(ObservationRuntime=admit),
        "shengji.eval.m9_panel_recipe": SimpleNamespace(
            validate_panel_recipe=validate_recipe),
        "shengji.eval.m9_panel_publication": SimpleNamespace(
            publish_m9_panel_readout_once=publish),
    }
    monkeypatch.setattr(worker, "_runtime_gate", lambda: None)
    monkeypatch.setattr(worker, "_load_helper", lambda _: SimpleNamespace(
        _read_runtime=lambda *_: manifest))
    monkeypatch.setattr(worker, "_read_invocation", lambda *_: invocation)
    monkeypatch.setattr(importlib, "import_module", modules.__getitem__)
    monkeypatch.setattr(sys, "path", list(sys.path))
    assert worker.run(str(path), digest, "b" * 64) == {"synthetic": True}
