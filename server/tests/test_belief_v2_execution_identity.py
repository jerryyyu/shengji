"""Live source/runtime binding witnesses for the V2 execution freeze."""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

import scripts.belief_v2_cache_capacity_preflight as CACHE_PREFLIGHT

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
    monkeypatch.setattr(
        "shengji.rl.belief_v2_execution_identity._boot_identity",
        lambda: profile.boot_identity)
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
    # A worker entering after a reboot must re-probe the live boot rather than
    # compare the freeze to itself.  Every worker stage enters through this
    # gate before it can trust an exact-resume journal.
    monkeypatch.setattr(
        "shengji.rl.belief_v2_execution_identity.build_runtime_profile",
        lambda: profile)
    monkeypatch.setattr(
        "shengji.rl.belief_v2_execution_identity._boot_identity",
        lambda: "0" * 64)
    with pytest.raises(BeliefV2ExecutionIdentityError,
                       match="live boot identity drift"):
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


def test_cache_capacity_preflight_bootstraps_under_safe_flags():
    """The reviewed host preflight must at least parse and close its CLI."""
    repo = Path(__file__).resolve().parents[2]
    script = repo / "server" / "scripts" / (
        "belief_v2_cache_capacity_preflight.py")
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    environment.update({
        "PYTHONDONTWRITEBYTECODE": "1", "PYTHONHASHSEED": "0",
        "SHENGJI_FAST": "1", "SHENGJI_REQUIRE_VOIDS": "1"})
    result = subprocess.run(
        (sys.executable, "-P", "-B", str(script), "--help"), cwd=repo,
        env=environment, check=True, capture_output=True, text=True)
    assert "{run,verify}" in result.stdout


def test_cache_capacity_preflight_accepts_exact_clean_git_sha1(monkeypatch):
    """The host source probe binds Git's 40-hex object name, not SHA-256."""
    head = "a" * 40

    class Result:
        def __init__(self, stdout):
            self.stdout = stdout

    def run(command, *args, **kwargs):
        return Result(head + "\n" if command[1:] == (
            "rev-parse", "HEAD") else "")

    monkeypatch.setattr(
        CACHE_PREFLIGHT.subprocess, "run", run)
    CACHE_PREFLIGHT._clean_git_head(head)
    with pytest.raises(
            CACHE_PREFLIGHT.BeliefV2CacheCapacityPreflightError,
            match="source identity drift"):
        CACHE_PREFLIGHT._clean_git_head("b" * 64)


def test_cache_capacity_preflight_schedules_primary_cache_last(monkeypatch):
    primary = SimpleNamespace(cohort_id="synthetic-primary")
    control = SimpleNamespace(
        cohort_id=CACHE_PREFLIGHT.CONTROL_COHORT_ID)
    human = SimpleNamespace(cohort_id="human-mixture")
    scale = SimpleNamespace(cohort_id="synthetic-scale-50")
    calibration = object()
    inputs = SimpleNamespace(
        realizations=(primary, control, human, scale),
        common_calibration=calibration)
    monkeypatch.setattr(
        CACHE_PREFLIGHT, "_realization_binding",
        lambda _freeze, _index, row: f"binding-{row.cohort_id}")
    monkeypatch.setattr(
        CACHE_PREFLIGHT, "_calibration_binding",
        lambda *_args: "binding-calibration")

    specs = CACHE_PREFLIGHT._direct_specs(
        object(), "a" * 64, inputs)
    assert tuple(row[0] for row in specs) == (
        "human-mixture", "synthetic-scale-50",
        CACHE_PREFLIGHT.CALIBRATION_CACHE_ID, "synthetic-primary")
    assert tuple(row[1] for row in specs) == (
        human, scale, calibration, primary)


def test_cache_capacity_preflight_reopens_typed_overlay_manifest(
        tmp_path, monkeypatch):
    """The preserved control overlay has a labels manifest, not a cache one."""
    parent = tmp_path / "cache-stage"
    direct = parent / "cache-synthetic-primary"
    calibration = parent / "cache-common-calibration"
    overlay = parent / CACHE_PREFLIGHT.CONTROL_OVERLAY_DIRECTORY
    direct.mkdir(parents=True)
    calibration.mkdir()
    overlay.mkdir()
    (direct / CACHE_PREFLIGHT.MANIFEST_FILENAME).write_bytes(b"direct")
    (calibration / CACHE_PREFLIGHT.MANIFEST_FILENAME).write_bytes(
        b"calibration")
    (overlay / CACHE_PREFLIGHT.LABEL_MANIFEST_FILENAME).write_bytes(
        b"overlay")
    primary = SimpleNamespace(cohort_id="synthetic-primary")
    control = SimpleNamespace(
        cohort_id=CACHE_PREFLIGHT.CONTROL_COHORT_ID)
    inputs = SimpleNamespace(realizations=(primary, control))
    opened = []

    def stable_read(path):
        opened.append(path)
        return path.read_bytes()

    receipt = {
        "manifest_sha256": "a" * 64,
        "batch_count": 1,
        "decision_count": 1,
        "artifact_bytes": 1,
    }
    monkeypatch.setattr(CACHE_PREFLIGHT, "stable_read_bytes", stable_read)
    monkeypatch.setattr(
        CACHE_PREFLIGHT, "_direct_specs",
        lambda *args, **kwargs: (
            (primary.cohort_id, primary, "train", object()),
            (CACHE_PREFLIGHT.CALIBRATION_CACHE_ID, object(),
             "calibration", object())))
    monkeypatch.setattr(
        CACHE_PREFLIGHT, "_realization_binding",
        lambda *args, **kwargs: object())
    monkeypatch.setattr(
        CACHE_PREFLIGHT, "reopen_tensor_cache",
        lambda *args, **kwargs: receipt)
    monkeypatch.setattr(
        CACHE_PREFLIGHT, "reopen_label_overlay",
        lambda *args, **kwargs: receipt)

    rows = CACHE_PREFLIGHT._reopen_components(
        parent, freeze=object(), index_sha256="b" * 64, inputs=inputs,
        primary=primary, control=control)
    assert len(rows) == 3
    assert overlay / CACHE_PREFLIGHT.LABEL_MANIFEST_FILENAME in opened
    assert overlay / CACHE_PREFLIGHT.MANIFEST_FILENAME not in opened
