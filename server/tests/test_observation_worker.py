"""Synthetic boundary tests for the in-process M9 observation worker."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from scripts import observation_worker as worker


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _manifest(source: Path) -> dict:
    files = {}
    for path in (source / "shengji").rglob("*"):
        if path.is_file() and path.suffix in {".py", ".so"}:
            files[path.relative_to(source).as_posix()] = _sha(path)
    for path in (source / "scripts").rglob("*"):
        if path.is_file() and path.suffix in {".py", ".so"}:
            files[path.relative_to(source).as_posix()] = _sha(path)
    return {"source_root": str(source), "source_files": files}


def _source(tmp_path: Path) -> Path:
    source = tmp_path / "server"
    (source / "shengji").mkdir(parents=True)
    (source / "scripts").mkdir()
    (source / "shengji" / "__init__.py").write_text("# synthetic\n")
    (source / "scripts" / "worker.py").write_text("# synthetic\n")
    (source / "shengji" / "native.so").write_bytes(b"native")
    return source


def test_packet_bootstrap_rejects_duplicate_keys_and_wrong_sha(tmp_path: Path) -> None:
    packet = tmp_path / "packet.json"
    packet.write_bytes(b'{"schema":"m9-admission-v1","schema":"other"}')
    digest = _sha(packet)
    with pytest.raises(ValueError, match="strict finite JSON"):
        worker._read_packet(str(packet), digest)
    with pytest.raises(ValueError, match="packet SHA mismatch"):
        worker._read_packet(str(packet), "0" * 64)


@pytest.mark.parametrize("raw", [b'{"x":1e999}', b'{"x":NaN}', b'{"x":Infinity}'])
def test_nonfinite_json_is_refused(raw):
    from shengji.eval import observation_queue
    with pytest.raises(ValueError):
        worker._parse_object(raw)
    with pytest.raises(ValueError):
        observation_queue._parse_finite_object(raw)


def test_source_map_refuses_bytecode_symlink_and_drift(tmp_path: Path) -> None:
    source = _source(tmp_path)
    manifest = _manifest(source)
    worker._verify_source_files(manifest, source)

    (source / "shengji" / "stale.pyc").write_bytes(b"stale")
    with pytest.raises(ValueError, match="bytecode"):
        worker._verify_source_files(manifest, source)

    (source / "shengji" / "stale.pyc").unlink()
    (source / "scripts" / "link.py").symlink_to(source / "scripts" / "worker.py")
    with pytest.raises(ValueError, match="symlink"):
        worker._verify_source_files(manifest, source)


def test_guard_rejection_happens_before_tactical_or_model_construction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    server = repo / "server"
    server.mkdir(parents=True)
    fixtures = tmp_path / "fixtures.jsonl"
    fixtures.write_bytes(b"synthetic fixture")
    packet_sha = "a" * 64
    recipe_value = {
        "source_root": str(repo),
        "python": sys.executable,
        "fixtures": str(fixtures),
        "fixture_sha256": _sha(fixtures),
    }
    packet = {"recipe": recipe_value}
    calls = []

    class FakeRecipe:
        @staticmethod
        def validate_recipe(value):
            calls.append("recipe")

        @staticmethod
        def build_observation_command(value):
            return (sys.executable, "-I", "-B", "tactical_report.py", "--fixed")

    class FakeRuntime:
        def __init__(self, manifest):
            calls.append("runtime")

        def check(self):
            calls.append("runtime-check")
            return True

    tactical = SimpleNamespace(main=lambda: calls.append("tactical"))
    monkeypatch.setattr(worker, "_repository_root", lambda: repo)
    monkeypatch.setattr(worker, "_read_packet", lambda path, sha: (Path(path), packet))
    monkeypatch.setattr(worker, "_read_runtime", lambda packet, source: {"synthetic": True})
    monkeypatch.setattr(worker, "_import_application",
                        lambda source: (FakeRecipe, SimpleNamespace(ObservationRuntime=FakeRuntime),
                                        object(), tactical))
    monkeypatch.setattr(worker, "_verify_claim_and_controls",
                        lambda packet, sha, guards: (_ for _ in ()).throw(
                            ValueError("release refused")))

    with pytest.raises(ValueError, match="release refused"):
        worker.run_packet("/synthetic/packet.json", packet_sha)
    assert calls == ["recipe", "runtime", "runtime-check"]


def test_success_calls_tactical_once_and_restores_argv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = tmp_path / "repo"
    server = repo / "server"
    server.mkdir(parents=True)
    fixtures = tmp_path / "fixtures.jsonl"
    fixtures.write_bytes(b"synthetic fixture")
    packet_sha = "b" * 64
    packet = {"recipe": {"source_root": str(repo), "python": sys.executable,
                          "fixtures": str(fixtures), "fixture_sha256": _sha(fixtures)}}
    calls = []

    class FakeRecipe:
        @staticmethod
        def validate_recipe(value):
            calls.append("recipe")

        @staticmethod
        def build_observation_command(value):
            return (sys.executable, "-I", "-B", "tactical_report.py", "--fixed")

    class FakeRuntime:
        def __init__(self, manifest):
            calls.append("runtime")

        def check(self):
            return True

    original = ["pytest", "--sentinel"]
    seen = []

    def tactical_main():
        calls.append("tactical")
        seen.append(list(sys.argv))

    monkeypatch.setattr(worker, "_repository_root", lambda: repo)
    monkeypatch.setattr(worker, "_read_packet", lambda path, sha: (Path(path), packet))
    monkeypatch.setattr(worker, "_read_runtime", lambda packet, source: {"synthetic": True})
    monkeypatch.setattr(worker, "_import_application",
                        lambda source: (FakeRecipe, SimpleNamespace(ObservationRuntime=FakeRuntime),
                                        object(), SimpleNamespace(main=tactical_main)))
    monkeypatch.setattr(worker, "_verify_claim_and_controls", lambda *args: {})
    monkeypatch.setattr(worker.sys, "argv", original)

    worker.run_packet("/synthetic/packet.json", packet_sha)

    assert calls == ["recipe", "runtime", "tactical"]
    assert seen == [["tactical_report.py", "--fixed"]]
    assert sys.argv == original


def test_owner_authenticates_before_import_and_delegates_once(tmp_path, monkeypatch):
    calls = []
    packet = {"recipe": {"source_root": str(tmp_path)}}
    monkeypatch.setattr(worker, "_repository_root", lambda: tmp_path)
    monkeypatch.setattr(worker, "_read_packet",
                        lambda *args: (calls.append("packet") or (None, packet)))
    monkeypatch.setattr(worker, "_read_runtime",
                        lambda *args: (calls.append("source-auth") or {}))
    def imported(server):
        assert server == tmp_path / "server"
        calls.append("owner-import")
        def admitted(path, sha):
            calls.append(("admit", path, sha))
            return {"comparison_validated": False}
        return SimpleNamespace(run_packet=admitted)
    monkeypatch.setattr(worker, "_import_owner", imported)
    result = worker.run_owner_packet("/packet", "a" * 64)
    assert calls == ["packet", "source-auth", "owner-import", ("admit", "/packet", "a" * 64)]
    assert result == {"comparison_validated": False}


@pytest.mark.parametrize("stage", ["packet", "source"])
def test_owner_auth_failure_never_imports_admission(tmp_path, monkeypatch, stage):
    def refuse(*args):
        raise ValueError("authentication refused")
    monkeypatch.setattr(worker, "_repository_root", lambda: tmp_path)
    monkeypatch.setattr(worker, "_read_packet", refuse if stage == "packet" else
                        lambda *args: (None, {"recipe": {"source_root": str(tmp_path)}}))
    monkeypatch.setattr(worker, "_read_runtime", refuse)
    monkeypatch.setattr(worker, "_import_owner", lambda *args: pytest.fail("unauthenticated import"))
    with pytest.raises(ValueError, match="authentication refused"):
        worker.run_owner_packet("/packet", "a" * 64)


@pytest.mark.parametrize("admit", [False, True])
def test_cli_owner_mode_is_explicit_without_changing_worker_default(monkeypatch, admit):
    calls = []
    monkeypatch.setattr(worker, "run_owner_packet", lambda *args:
                        (calls.append(("owner", args)) or {"status": "exited", "returncode": 0}))
    monkeypatch.setattr(worker, "run_packet", lambda *args: calls.append(("worker", args)))
    worker.main(["--packet", "/packet", "--sha256", "a" * 64] + (["--admit"] if admit else []))
    assert calls == [("owner" if admit else "worker", ("/packet", "a" * 64))]


@pytest.mark.parametrize("receipt", [
    {"status": "timeout", "returncode": -9}, {"status": "failed", "returncode": 2},
    {"status": "failed", "returncode": 0}, {"status": "exited", "returncode": False}, None,
])
def test_owner_cli_propagates_unsuccessful_receipt(monkeypatch, receipt):
    monkeypatch.setattr(worker, "run_owner_packet", lambda *args: receipt)
    with pytest.raises(SystemExit) as error:
        worker.main(["--admit", "--packet", "/packet", "--sha256", "a" * 64])
    assert error.value.code == 1


def test_isolated_owner_cli_refuses_bad_packet_without_application_import(tmp_path):
    import subprocess

    packet = tmp_path / "packet.json"
    packet.write_bytes(b"{}")
    result = subprocess.run(
        [sys.executable, "-I", "-B", str(Path(worker.__file__).resolve()),
         "--admit", "--packet", str(packet), "--sha256", _sha(packet)],
        capture_output=True, text=True, timeout=10, check=False,
    )
    assert result.returncode != 0
    assert "exact M9 packet required" in result.stderr
    assert "ModuleNotFoundError" not in result.stderr
    assert list(tmp_path.iterdir()) == [packet]
