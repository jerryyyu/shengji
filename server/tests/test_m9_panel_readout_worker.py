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
        "controls": {},
        "terminal_seal": {"path": str(tmp_path / "SHA256SUMS"), "sha256": "d" * 64},
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


@pytest.mark.parametrize("corrupt", [False, True])
def test_sealed_synthetic_bundle_through_bootstrap_and_real_reader(tmp_path, monkeypatch, corrupt):
    """Only host/runtime admission and the fixture digest are synthetic.

    Packet/control/seal authentication, recipe/path checks, persisted panel
    reading and exclusive publication all execute their actual code paths.
    This does not qualify a Linux runtime or authenticate scientific results.
    """
    from test_m9_panel_artifact_reader import bundle
    from test_m9_panel_recipe import recipe
    from shengji.eval import m9_panel_recipe, observation_runtime
    from shengji.eval import m9_panel_artifact_reader as reader
    from shengji.eval.m9_panel_readout import summarize_m9_panels

    pins, analysis, panel_records = bundle(monkeypatch, tmp_path)
    evidence = tmp_path / "process"
    evidence.mkdir()
    Path(pins["process"]["path"]).rename(evidence / "process.json")
    pins["process"]["path"] = str(evidence / "process.json")
    spec = recipe()
    spec.update(output_dir=str(tmp_path / "collection"), evidence=str(evidence),
                saved_readout=pins["saved_readout"]["path"],
                saved_readout_sha256=pins["saved_readout"]["sha256"])
    monkeypatch.setattr(m9_panel_recipe, "SAVED_READOUT_SHA256", spec["saved_readout_sha256"])

    def write_pin(path, value):
        raw = _canonical(value)
        path.write_bytes(raw)
        return {"path": str(path), "sha256": _sha(raw)}

    helper = _load_actual_helper()
    helper_sha = _sha(Path(helper.__file__).read_bytes())
    old_runtime = write_pin(tmp_path / "collection-runtime.json", {
        "schema": "shengji-m9-runtime-v1", "source_root": "/source/server",
        "source_files": {"scripts/observation_worker.py": helper_sha}})
    packet = {key: None for key in helper._PANEL_PACKET_KEYS}
    packet.update(schema="m9-panel-admission-v1", recipe=spec, runtime=old_runtime,
                  status=pins["owner"]["path"], timeout_seconds=800,
                  process_timeout_seconds=900)
    for name in ("release", "claim", "reservation"):
        packet[name] = str(tmp_path / f"{name}.json")
    packet_pin = write_pin(tmp_path / "packet.json", packet)
    digest = packet_pin["sha256"]
    owner = json.loads(Path(pins["owner"]["path"]).read_bytes())
    owner["packet_sha256"] = digest
    pins["owner"] = write_pin(Path(pins["owner"]["path"]), owner)
    command = list(m9_panel_recipe.build_panel_worker_command(spec, packet_pin["path"], digest))
    controls = {
        "release": write_pin(Path(packet["release"]), {
            "schema": "m9-panel-release-v1", "packet_sha256": digest}),
        "claim": write_pin(Path(packet["claim"]), {
            "schema": "m9-panel-owner-attempt-v1", "packet_sha256": digest,
            "status": "spent_no_retry", "comparison_validated": False,
            "owner_pid": 123, "inner_command": command, "queue_snapshot": {},
            "deadline_monotonic": 12345.0}),
        "reservation": write_pin(Path(packet["reservation"]), {
            "schema": "codex-m9-panel-reservation-v1", "lane": "m9-panel",
            "packet_sha256": digest, "pid": 123, "count": 15, "seeds": [0, 1, 2],
            "status": packet["status"], "output": spec["output_dir"],
            "output_root": spec["output_dir"], "result": spec["output_dir"],
            "evidence": str(evidence), "launcher": command[3], "launcher_sha256": helper_sha}),
        "process_claim": write_pin(evidence / "claim.json", {
            "schema": "m9-process-attempt-v1", "command": command,
            "timeout_seconds": 900, "comparison_validated": False}),
    }
    refs = [*pins.values(), *controls.values(), packet_pin, old_runtime]
    seal = tmp_path / "SHA256SUMS"
    seal.write_bytes("".join(f'{r["sha256"]}  {r["path"]}\n' for r in refs).encode())
    invocation = {
        "schema": "m9-panel-readout-invocation-v1", "files": pins,
        "packet_sha256": digest, "collection_packet": packet_pin,
        "controls": controls, "terminal_seal": {"path": str(seal), "sha256": _sha(seal.read_bytes())},
        "runtime": write_pin(tmp_path / "readout-runtime.json", {}),
        "output_dir": str(tmp_path / "readout"),
    }
    invocation_pin = write_pin(tmp_path / "invocation.json", invocation)
    if corrupt:
        seal.write_bytes(b"changed after pinning\n")
    monkeypatch.setattr(worker, "_runtime_gate", lambda: None)
    monkeypatch.setattr(helper, "_read_runtime", lambda *_: {
        "source_files": {"scripts/observation_worker.py": helper_sha}})
    monkeypatch.setattr(worker, "_load_helper", lambda _: helper)
    monkeypatch.setattr(observation_runtime, "ObservationRuntime",
                        lambda *a, **kw: SimpleNamespace(check=lambda: True))
    monkeypatch.setattr(sys, "path", list(sys.path))
    reads = []
    stable = reader.guards._stable_read
    def track(path, limit):
        reads.append(str(path))
        return stable(path, limit)
    monkeypatch.setattr(reader.guards, "_stable_read", track)
    if corrupt:
        with pytest.raises(ValueError, match="terminal seal SHA mismatch"):
            worker.run(invocation_pin["path"], invocation_pin["sha256"], helper_sha)
        assert reads == []
        assert not (tmp_path / "readout").exists()
        return
    receipt = worker.run(invocation_pin["path"], invocation_pin["sha256"], helper_sha)
    assert len(reads) == len(set(reads)) == 20
    result = json.loads((tmp_path / "readout/result.json").read_bytes())
    assert result["analysis"] == summarize_m9_panels(analysis, panel_records)
    assert receipt["terminal_seal"] == invocation["terminal_seal"]
    assert receipt["result_sha256"] == _sha((tmp_path / "readout/result.json").read_bytes())
    assert json.loads((tmp_path / "readout/receipt.json").read_bytes()) == receipt
    with pytest.raises(FileExistsError):
        worker.run(invocation_pin["path"], invocation_pin["sha256"], helper_sha)
    assert len(reads) == 20  # spent publication cannot trigger a second outcome read


@pytest.mark.parametrize("bad", [None, "hash", "missing", "extra", "duplicate",
                                    "digest", "relative", "newline", "alias"])
def test_terminal_inventory_binds_all_pins_without_outcome_access(tmp_path, monkeypatch, bad):
    invocation, _ = _invocation(tmp_path)
    invocation["controls"] = {str(i): {"path": str(tmp_path / f"control-{i}"),
                                        "sha256": "b" * 64} for i in range(4)}
    packet = {"runtime": {"path": str(tmp_path / "collection-runtime"), "sha256": "c" * 64}}
    refs = [*invocation["files"].values(), *invocation["controls"].values(),
            invocation["collection_packet"], packet["runtime"]]
    lines = [f'{ref["sha256"]}  {ref["path"]}' for ref in refs]
    if bad == "missing":
        lines.pop()
    elif bad == "extra":
        lines.append(f'{"d" * 64}  {tmp_path / "extra"}')
    elif bad == "duplicate":
        lines[-1] = lines[0]
    elif bad == "digest":
        lines[-1] = "f" * 64 + lines[-1][64:]
    elif bad == "relative":
        lines[-1] = "f" * 64 + "  relative"
    elif bad == "alias":
        packet["runtime"] = invocation["collection_packet"]
    raw = ("\n".join(lines) + ("" if bad == "newline" else "\n")).encode()
    path = tmp_path / "SHA256SUMS"
    path.write_bytes(raw)
    invocation["terminal_seal"] = {"path": str(path), "sha256": _sha(raw)}
    if bad == "hash":
        invocation["terminal_seal"]["sha256"] = "0" * 64
    helper = _load_actual_helper()
    stable_read = helper._stable_read
    reads = []
    def read(p, limit):
        assert p == path, "seal verification must not open outcomes or controls"
        reads.append(p)
        return stable_read(p, limit)
    monkeypatch.setattr(helper, "_stable_read", read)
    if bad is None:
        worker._verify_terminal_seal(helper, invocation, packet)
    else:
        with pytest.raises(ValueError):
            worker._verify_terminal_seal(helper, invocation, packet)
    assert reads == [path]


@pytest.mark.parametrize("bad", [None, "hash", "source", "launcher"])
def test_collection_runtime_binds_historical_launcher(tmp_path, bad):
    manifest = {"schema": "shengji-m9-runtime-v1", "source_root": "/collection/server",
                "source_files": {"scripts/observation_worker.py": "e" * 64}}
    if bad == "source":
        manifest["source_root"] = "/other/server"
    raw = _canonical(manifest)
    path = tmp_path / "collection-runtime.json"
    path.write_bytes(raw)
    packet = {"recipe": {"source_root": "/collection"},
              "runtime": {"path": str(path), "sha256": _sha(raw)}}
    records = {"reservation": {"launcher_sha256": "e" * 64}}
    if bad == "hash":
        packet["runtime"]["sha256"] = "0" * 64
    elif bad == "launcher":
        records["reservation"]["launcher_sha256"] = "f" * 64
    if bad is None:
        worker._read_collection_runtime(_load_actual_helper(), packet, records)
    else:
        with pytest.raises(ValueError):
            worker._read_collection_runtime(_load_actual_helper(), packet, records)


@pytest.mark.parametrize("bad", [None, "release", "owner_command", "pid_bool",
                                    "count_bool", "process_command", "timeout",
                                    "hash", "path"])
def test_historical_controls_bind_packet_without_live_checks(tmp_path, monkeypatch, bad):
    from test_m9_panel_recipe import recipe
    spec = recipe()
    packet = {"recipe": spec, "status": "/outputs/status.json",
              "process_timeout_seconds": 900}
    spec["evidence"] = str(tmp_path / "process")
    (tmp_path / "process").mkdir()
    for name in ("release", "claim", "reservation"):
        packet[name] = str(tmp_path / f"{name}.json")
    invocation = {"packet_sha256": "a" * 64,
                  "collection_packet": {"path": "/packet.json"}, "controls": {}}
    command = [spec["python"], "-I", "-B",
               "/source/server/scripts/observation_worker.py", "--panel", "--packet",
               "/packet.json", "--sha256", "a" * 64]
    records = {
        "release": {"schema": "m9-panel-release-v1", "packet_sha256": "a" * 64},
        "claim": {"schema": "m9-panel-owner-attempt-v1", "packet_sha256": "a" * 64,
                  "status": "spent_no_retry", "comparison_validated": False,
                  "owner_pid": 123, "inner_command": command, "queue_snapshot": {},
                  "deadline_monotonic": 12345.0},
        "reservation": {"schema": "codex-m9-panel-reservation-v1", "lane": "m9-panel",
                        "packet_sha256": "a" * 64, "pid": 123, "count": 15,
                        "seeds": [0, 1, 2], "status": packet["status"],
                        "output": spec["output_dir"], "output_root": spec["output_dir"],
                        "result": spec["output_dir"], "evidence": spec["evidence"],
                        "launcher": command[3]},
        "process_claim": {"schema": "m9-process-attempt-v1", "command": command,
                          "timeout_seconds": 900, "comparison_validated": False},
    }
    if bad == "release":
        records["release"]["packet_sha256"] = "b" * 64
    elif bad == "owner_command":
        records["claim"]["inner_command"] = ["other"]
    elif bad == "pid_bool":
        records["claim"]["owner_pid"] = True
    elif bad == "count_bool":
        records["reservation"]["count"] = True
    elif bad == "process_command":
        records["process_claim"]["command"] = ["other"]
    elif bad == "timeout":
        records["process_claim"]["timeout_seconds"] = 901
    for name, record in records.items():
        path = Path(packet[name]) if name != "process_claim" else tmp_path / "process/claim.json"
        raw = _canonical(record)
        path.write_bytes(raw)
        invocation["controls"][name] = {"path": str(path), "sha256": _sha(raw)}
    helper = _load_actual_helper()
    if bad == "hash":
        invocation["controls"]["process_claim"]["sha256"] = "0" * 64
        monkeypatch.setattr(helper, "_parse_object", lambda *_: pytest.fail(
            "all controls must authenticate before any is parsed"))
    if bad == "path":
        invocation["controls"]["claim"]["path"] = str(tmp_path / "other.json")
    monkeypatch.setattr(os, "kill", lambda *_: pytest.fail("no live PID checks for historical read"))
    if bad is None:
        worker._read_controls(helper, invocation, packet)
    else:
        with pytest.raises(ValueError):
            worker._read_controls(helper, invocation, packet)


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
    monkeypatch.setattr(worker, "_verify_terminal_seal", lambda *_: seen.append("seal"))
    monkeypatch.setattr(worker, "_read_collection_runtime", lambda *_: seen.append("collection-runtime"))
    monkeypatch.setattr(worker, "_read_controls", lambda *_: seen.append("controls"))

    def admit(value, *, profile):
        assert value is manifest
        assert profile == "panel-readout"
        seen.append("admitted")
        return SimpleNamespace(check=check)

    def publish(value, *, invocation_sha256, runtime_check, collection_packet):
        assert seen == ["seal", "controls", "collection-runtime", "admitted", "recipe"]
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


def _qualification_fixture(tmp_path, monkeypatch):
    checkout = tmp_path / "checkout"
    server = checkout / "server"
    (server / "scripts").mkdir(parents=True)
    reader = server / "scripts" / "m9_panel_readout_worker.py"
    reader.write_text("# synthetic reader\n")
    baseline_path = tmp_path / "baseline-runtime.json"
    baseline_path.write_bytes(b"baseline")
    bootstrap_sha = "b" * 64
    baseline = {
        "schema": "shengji-m9-runtime-v1",
        "source_root": str(server),
        "source_files": {"scripts/observation_worker.py": bootstrap_sha},
        "environment": {"LANG": "C.UTF-8"},
    }
    helper = _load_actual_helper()
    monkeypatch.setattr(worker, "_runtime_gate", lambda: None)
    monkeypatch.setattr(worker, "_load_helper", lambda _: helper)
    monkeypatch.setattr(worker, "_qualification_paths", lambda _: (reader, server))
    monkeypatch.setattr(helper, "_read_runtime", lambda *_: baseline)
    return server, reader, baseline_path, baseline, bootstrap_sha, helper


def test_capture_runtime_is_model_free_and_uses_only_readout_closure(
        tmp_path, monkeypatch):
    server, _reader, baseline_path, baseline, bootstrap_sha, _helper = \
        _qualification_fixture(tmp_path, monkeypatch)
    output = tmp_path / "qualified" / "runtime.json"
    output.parent.mkdir()
    events = []
    captured = dict(baseline)
    captured["external_runtime"] = {"source_root": str(server), "imports": []}

    class Adapter:
        @staticmethod
        def capture(source, *, profile):
            assert source == server
            assert profile == "panel-readout"
            events.append("capture")
            return captured

    monkeypatch.setattr(worker, "_import_readout_application",
                        lambda source: (events.append("imports") or
                                        (Adapter, object(), object())))
    for name in ("_read_invocation", "_read_collection_packet", "_read_controls",
                 "_verify_terminal_seal", "_read_collection_runtime"):
        monkeypatch.setattr(worker, name, lambda *args, _name=name: pytest.fail(
            f"qualification accessed {_name}"))

    worker.capture_runtime(str(baseline_path), _sha(b"baseline"), bootstrap_sha,
                           str(output))
    assert events == ["imports", "capture"]
    assert json.loads(output.read_bytes()) == captured


def test_capture_runtime_rejects_manifest_mismatch_before_publication(
        tmp_path, monkeypatch):
    _server, _reader, baseline_path, baseline, bootstrap_sha, _helper = \
        _qualification_fixture(tmp_path, monkeypatch)
    output = tmp_path / "qualified.json"
    bad = dict(baseline)
    bad["environment"] = {"LANG": "C"}

    class Adapter:
        @staticmethod
        def capture(source, *, profile):
            return bad

    monkeypatch.setattr(worker, "_import_readout_application",
                        lambda *_: (Adapter, object(), object()))
    with pytest.raises(ValueError, match="environment"):
        worker.capture_runtime(str(baseline_path), _sha(b"baseline"),
                               bootstrap_sha, str(output))
    assert not output.exists()


def test_qualification_bad_manifest_binding_precedes_application_import(
        tmp_path, monkeypatch):
    server, _reader, baseline_path, baseline, bootstrap_sha, helper = \
        _qualification_fixture(tmp_path, monkeypatch)
    imported = []
    monkeypatch.setattr(worker, "_import_readout_application",
                        lambda *_: imported.append(True))
    bad = dict(baseline)
    bad["source_files"] = {"scripts/observation_worker.py": "c" * 64}
    monkeypatch.setattr(helper, "_read_runtime", lambda *_: bad)
    with pytest.raises(ValueError, match="bind authenticated bootstrap"):
        worker.capture_runtime(str(baseline_path), _sha(b"baseline"),
                               bootstrap_sha, str(tmp_path / "out.json"))
    assert imported == []
    assert server.is_dir()


def test_qualification_bad_runtime_digest_precedes_application_import(
        tmp_path, monkeypatch):
    server = tmp_path / "checkout" / "server"
    (server / "scripts").mkdir(parents=True)
    reader = server / "scripts" / "m9_panel_readout_worker.py"
    reader.write_text("# synthetic reader\n")
    baseline_path = tmp_path / "baseline-runtime.json"
    baseline_path.write_bytes(b"{}")
    helper = _load_actual_helper()
    monkeypatch.setattr(worker, "_runtime_gate", lambda: None)
    monkeypatch.setattr(worker, "_load_helper", lambda _: helper)
    monkeypatch.setattr(worker, "_qualification_paths", lambda _: (reader, server))
    imported = []
    monkeypatch.setattr(worker, "_import_readout_application",
                        lambda *_: imported.append(True))
    with pytest.raises(ValueError, match="runtime hash mismatch"):
        worker.capture_runtime(str(baseline_path), "0" * 64, "b" * 64,
                               str(tmp_path / "qualified.json"))
    assert imported == []


@pytest.mark.parametrize("kind", ["existing", "symlink", "inside"])
def test_capture_runtime_output_is_exclusive_nonsymlink_and_outside_checkout(
        tmp_path, monkeypatch, kind):
    server, _reader, baseline_path, _baseline, bootstrap_sha, _helper = \
        _qualification_fixture(tmp_path, monkeypatch)
    if kind == "existing":
        output = tmp_path / "existing.json"
        output.write_bytes(b"keep")
    elif kind == "symlink":
        real = tmp_path / "real.json"
        real.write_bytes(b"keep")
        output = tmp_path / "link.json"
        output.symlink_to(real)
    else:
        output = server / "inside.json"
    imported = []
    monkeypatch.setattr(worker, "_import_readout_application",
                        lambda *_: imported.append(True))
    with pytest.raises(ValueError):
        worker.capture_runtime(str(baseline_path), _sha(b"baseline"),
                               bootstrap_sha, str(output))
    assert imported == []


def test_verify_runtime_false_check_refuses_without_collection_access(
        tmp_path, monkeypatch):
    _server, _reader, baseline_path, baseline, bootstrap_sha, _helper = \
        _qualification_fixture(tmp_path, monkeypatch)

    class Runtime:
        def check(self):
            return False

    class Adapter:
        ObservationRuntime = lambda *args, **kwargs: Runtime()

    monkeypatch.setattr(worker, "_import_readout_application",
                        lambda *_: (Adapter, object(), object()))
    for name in ("_read_invocation", "_read_collection_packet", "_read_controls",
                 "_verify_terminal_seal", "_read_collection_runtime"):
        monkeypatch.setattr(worker, name, lambda *args, _name=name: pytest.fail(
            f"qualification accessed {_name}"))
    with pytest.raises(ValueError, match="runtime verification failed"):
        worker.verify_runtime(str(baseline_path), _sha(b"baseline"),
                              bootstrap_sha)


def test_verify_runtime_uses_panel_readout_profile(tmp_path, monkeypatch):
    _server, _reader, baseline_path, _baseline, bootstrap_sha, _helper = \
        _qualification_fixture(tmp_path, monkeypatch)
    profiles = []

    class Runtime:
        def check(self):
            return True

    class Adapter:
        @staticmethod
        def ObservationRuntime(manifest, *, profile):
            profiles.append(profile)
            return Runtime()

    monkeypatch.setattr(worker, "_import_readout_application",
                        lambda *_: (Adapter, object(), object()))
    assert worker.verify_runtime(str(baseline_path), _sha(b"baseline"),
                                 bootstrap_sha)
    assert profiles == ["panel-readout"]


def test_main_preserves_three_positional_real_run(monkeypatch):
    seen = []
    monkeypatch.setattr(worker, "run", lambda *args: seen.append(args))
    assert worker.main(["invocation", "i" * 64, "b" * 64]) == 0
    assert seen == [("invocation", "i" * 64, "b" * 64)]


def test_main_dispatches_strict_runtime_qualification_cli(monkeypatch):
    capture = []
    verify = []
    monkeypatch.setattr(worker, "capture_runtime",
                        lambda *args: capture.append(args))
    monkeypatch.setattr(worker, "verify_runtime",
                        lambda *args: verify.append(args))
    assert worker.main(["--capture-runtime", "base", "a" * 64,
                        "b" * 64, "out"]) == 0
    assert worker.main(["--verify-runtime", "runtime", "c" * 64,
                        "b" * 64]) == 0
    assert capture == [("base", "a" * 64, "b" * 64, "out")]
    assert verify == [("runtime", "c" * 64, "b" * 64)]
    assert worker.main(["--capture-runtime", "base"]) == 1
    assert worker.main(["--verify-runtime", "runtime", "c" * 64]) == 1
