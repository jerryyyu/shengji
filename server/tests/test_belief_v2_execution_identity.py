"""Live source/runtime binding witnesses for the V2 execution freeze."""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from shengji.rl.belief_v2_execution_identity import (
    BeliefV2ExecutionIdentityError,
    V2InstalledDistributionV1,
    V2RuntimeProfileV1,
    build_source_bindings,
    source_manifest_sha256,
    validate_live_execution,
    validate_runtime_profile,
)


def _git(repo, *args):
    return subprocess.run(
        ("git", *args), cwd=repo, check=True,
        capture_output=True, text=True).stdout.strip()


def _repo(tmp_path):
    repo = (tmp_path / "repo").resolve()
    repo.mkdir()
    for name in (
            "BELIEF_V1_SPEC.md", "BELIEF_V1_V2_DESIGN.md",
            "server/pyproject.toml", "server/setup.py", "server/uv.lock",
            "server/shengji/__init__.py",
            "server/scripts/belief_v2_worker.py"):
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{name}\n")
    _git(repo, "init", "-q")
    _git(repo, "add", ".")
    _git(repo, "-c", "user.name=Test", "-c",
         "user.email=test@example.com", "commit", "-qm", "base")
    return repo, _git(repo, "rev-parse", "HEAD")


def _distribution(name):
    return V2InstalledDistributionV1(
        name=name, version="1.0", root="/runtime",
        file_count=10, payload_sha256="a" * 64)


def _runtime():
    return V2RuntimeProfileV1(
        hostname="host", operating_system="system", machine="machine",
        cpu_count=16, memory_bytes=32 * 1024**3,
        boot_identity="b" * 64,
        python_executable="/runtime/python",
        python_executable_sha256="c" * 64,
        python_version="3.14.4", torch=_distribution("torch"),
        torch_config_sha256="d" * 64, numpy=_distribution("numpy"),
        native_path="/runtime/_fast.so", native_sha256="e" * 64,
        required_environment=(
            ("PYTHONDONTWRITEBYTECODE", "1"),
            ("PYTHONHASHSEED", "0"),
            ("SHENGJI_FAST", "1"),
            ("SHENGJI_REQUIRE_VOIDS", "1")))


def test_source_binding_is_complete_exact_and_canonical(tmp_path):
    repo, head = _repo(tmp_path)
    native = tmp_path / "outside.so"
    native.write_bytes(b"native")
    rows = build_source_bindings(
        repo, expected_git=head, native_path=native)
    assert len(rows) == 7
    assert source_manifest_sha256(head, rows) == source_manifest_sha256(
        head, rows)
    assert rows == tuple(sorted(rows, key=lambda row: row.path))


def test_source_binding_refuses_ignored_loadable_shadow(tmp_path):
    repo, head = _repo(tmp_path)
    native = tmp_path / "outside.so"
    native.write_bytes(b"native")
    (repo / ".gitignore").write_text("__pycache__/\n*.pyc\n")
    _git(repo, "add", ".gitignore")
    _git(repo, "-c", "user.name=Test", "-c",
         "user.email=test@example.com", "commit", "-qm", "ignore")
    head = _git(repo, "rev-parse", "HEAD")
    cache = repo / "server/shengji/__pycache__"
    cache.mkdir()
    (cache / "poison.pyc").write_bytes(b"poison")
    with pytest.raises(BeliefV2ExecutionIdentityError,
                       match="bytecode cache"):
        build_source_bindings(
            repo, expected_git=head, native_path=native)


def test_runtime_profile_binds_packages_boot_and_numerical_mode():
    profile = _runtime()
    validate_runtime_profile(profile)
    with pytest.raises(BeliefV2ExecutionIdentityError,
                       match="runtime profile"):
        validate_runtime_profile(replace(profile, boot_identity="bad"))
    with pytest.raises(BeliefV2ExecutionIdentityError,
                       match="distribution"):
        validate_runtime_profile(replace(
            profile, numpy=replace(profile.numpy, file_count=0)))


def test_live_gate_recomputes_both_source_and_runtime(monkeypatch):
    profile = _runtime()
    rows = ()
    monkeypatch.setattr(
        "shengji.rl.belief_v2_execution_identity.validate_source_bindings",
        lambda value: None)
    monkeypatch.setattr(
        "shengji.rl.belief_v2_execution_identity.build_source_bindings",
        lambda *args, **kwargs: rows)
    monkeypatch.setattr(
        "shengji.rl.belief_v2_execution_identity.build_runtime_profile",
        lambda: profile)
    validate_live_execution(
        repo=__import__("pathlib").Path("/repo"), execution_git="f" * 40,
        source_bindings=rows, runtime=profile)
    monkeypatch.setattr(
        "shengji.rl.belief_v2_execution_identity.build_runtime_profile",
        lambda: replace(profile, native_sha256="0" * 64))
    with pytest.raises(BeliefV2ExecutionIdentityError,
                       match="live execution"):
        validate_live_execution(
            repo=__import__("pathlib").Path("/repo"),
            execution_git="f" * 40, source_bindings=rows, runtime=profile)


def test_worker_bootstrap_requires_safe_flags_and_has_closed_command_surface():
    repo = Path(__file__).resolve().parents[2]
    worker = repo / "server" / "scripts" / "belief_v2_worker.py"
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    environment.update({
        "PYTHONDONTWRITEBYTECODE": "1", "PYTHONHASHSEED": "0",
        "SHENGJI_FAST": "1", "SHENGJI_REQUIRE_VOIDS": "1"})
    result = subprocess.run(
        (sys.executable, "-P", "-B", str(worker),
         "--bootstrap-check-only"), cwd=repo, env=environment,
        check=True, capture_output=True, text=True)
    assert result.stdout == "BELIEF_V1_V2_BOOTSTRAP_PASS\n"
    unsafe = subprocess.run(
        (sys.executable, "-B", str(worker), "--bootstrap-check-only"),
        cwd=repo, env=environment, capture_output=True, text=True)
    assert unsafe.returncode != 0
    assert "requires Python -P -B safe flags" in unsafe.stderr
