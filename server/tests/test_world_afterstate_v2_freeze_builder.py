"""Focused safety tests for the inert Value V2 freeze builder."""

from __future__ import annotations

import hashlib
import stat
from types import SimpleNamespace
from pathlib import Path

import pytest

from shengji.rl import world_afterstate_v2_freeze_builder as builder
from shengji.rl.world_afterstate_v2_execution import SourceBindingV2
from shengji.rl.belief_contract import canonical_json_bytes
from shengji.rl.world_afterstate_v2_freeze_inputs import (
    build_continuation_policy_v2, build_early_stage_config_v2,
    build_population_adapter_input_v2, build_seed_registry_v2, protocol_bytes,
)


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _patch_minimal(monkeypatch, tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    evidence = tmp_path / "evidence"
    head = "a" * 40
    rows = tuple((label, f"inputs/{label}.json", _digest(label))
                 for label in builder._ARTIFACT_LABELS)
    source = (SourceBindingV2("server/shengji/rl/example.py", 1,
                              _digest("source")),)
    runtime = {
        "boot_identity": "boot-1", "python": "test",
        "environment": {"SHENGJI_FAST": "1", "SHENGJI_REQUIRE_VOIDS": "1"},
        "shengji_native_extension": {"status": "present", "path": "stub",
                                       "sha256": _digest("native")},
    }
    monkeypatch.setattr(builder, "_head", lambda _repo, _head: head)
    monkeypatch.setattr(builder, "_clean_source_tree",
                        lambda _repo, _runtime: None)
    monkeypatch.setattr(builder, "_bindings", lambda _repo, _head: source)
    monkeypatch.setattr(builder, "_validate_inputs",
                        lambda *_args, **_kwargs: (rows, "D256"))
    monkeypatch.setattr(builder, "live_runtime_profile", lambda: runtime)
    return repo, evidence, head, rows


def test_clean_success_roundtrips_and_binds_runtime(monkeypatch, tmp_path):
    repo, evidence, head, rows = _patch_minimal(monkeypatch, tmp_path)
    freeze = builder.build_execution_freeze(
        repo, head, *(tmp_path / f"{label}.json" for label in builder._ARTIFACT_LABELS),
        evidence, 100, 10)
    assert freeze.population_tier == "D256"
    assert freeze.boot_identity == "boot-1"
    assert freeze.artifact_bindings == rows
    assert freeze.canonical_bytes()
    target = tmp_path / "published" / "freeze.json"
    builder.publish_freeze(target, freeze)
    assert target.read_bytes() == freeze.canonical_bytes()
    assert stat.S_IMODE(target.stat().st_mode) == 0o400
    assert target.stat().st_nlink == 1
    assert not target.with_name(".freeze.json.partial").exists()


def test_runtime_boot_mismatch_is_not_accepted(monkeypatch, tmp_path):
    repo, evidence, head, _rows = _patch_minimal(monkeypatch, tmp_path)
    monkeypatch.setattr(builder, "live_runtime_profile",
                        lambda: {
                            "boot_identity": "boot-2", "python": "test",
                            "environment": {"SHENGJI_FAST": "1",
                                            "SHENGJI_REQUIRE_VOIDS": "1"},
                            "shengji_native_extension": {
                                "status": "present", "path": "stub",
                                "sha256": _digest("native")}})
    # The live profile is bound into the new freeze; this test ensures the
    # binding is not silently replaced by a caller-provided boot witness.
    freeze = builder.build_execution_freeze(
        repo, head, *(tmp_path / f"{label}.json" for label in builder._ARTIFACT_LABELS),
        evidence, 100, 10)
    assert freeze.boot_identity == "boot-2"


def test_occupied_output_refuses_without_overwrite(tmp_path):
    target = tmp_path / "freeze.json"
    target.write_bytes(b"existing")
    with pytest.raises(builder.FreezeBuilderError, match="occupied"):
        builder.publish_freeze(target, object())


def test_strict_input_rejects_noncanonical_and_duplicate_keys():
    with pytest.raises(builder.FreezeBuilderError, match="canonical"):
        builder._strict_json(b'{"b":1,"a":2}\n', "input")
    with pytest.raises(builder.FreezeBuilderError, match="duplicate"):
        builder._strict_json(b'{"a":1,"a":1}\n', "input")


def test_source_dirty_and_loadable_shadow_guards(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    (repo / "server" / "shengji").mkdir(parents=True)
    monkeypatch.setattr(
        builder, "_frozen_native_path",
        lambda _repo, _runtime: _repo / "server" / "shengji" / "engine" /
        "_fast.so")
    monkeypatch.setattr(builder, "_git",
                        lambda *_args, **_kwargs: " M server/shengji/x.py")
    with pytest.raises(builder.FreezeBuilderError, match="not clean"):
        builder._clean_source_tree(repo, {
            "shengji_native_extension": {"status": "absent"}})
    monkeypatch.setattr(builder, "_git",
                        lambda *_args, **_kwargs: "!! server/shengji/x.py")
    (repo / "server" / "shengji" / "x.py").write_text("x")
    with pytest.raises(builder.FreezeBuilderError, match="ignored"):
        builder._clean_source_tree(repo, {
            "shengji_native_extension": {"status": "absent"}})


def test_clean_tree_allows_only_hash_bound_in_tree_fast_extension(
        monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    engine = repo / "server" / "shengji" / "engine"
    scripts = repo / "server" / "scripts"
    engine.mkdir(parents=True)
    scripts.mkdir(parents=True)
    native = engine / "_fast.cpython-314-x86_64-linux-gnu.so"
    native.write_bytes(b"bound-native")
    runtime = {"shengji_native_extension": {
        "status": "present", "path": str(native.resolve()),
        "sha256": hashlib.sha256(b"bound-native").hexdigest(),
        "loaded_file_identity": {"status": "verified"}}}
    monkeypatch.setattr(
        builder, "_git", lambda *_args, **_kwargs:
        "!! server/shengji/engine/_fast.cpython-314-x86_64-linux-gnu.so")
    builder._clean_source_tree(repo, runtime)

    shadow = engine / "foreign.so"
    shadow.write_bytes(b"shadow")
    monkeypatch.setattr(
        builder, "_git", lambda *_args, **_kwargs:
        "!! server/shengji/engine/_fast.cpython-314-x86_64-linux-gnu.so\n"
        "!! server/shengji/engine/foreign.so")
    with pytest.raises(builder.FreezeBuilderError, match="ignored loadable"):
        builder._clean_source_tree(repo, runtime)


def test_clean_tree_refuses_changed_fast_extension(monkeypatch, tmp_path):
    repo = tmp_path / "repo"
    engine = repo / "server" / "shengji" / "engine"
    (repo / "server" / "scripts").mkdir(parents=True)
    engine.mkdir(parents=True)
    native = engine / "_fast.cpython-314-x86_64-linux-gnu.so"
    native.write_bytes(b"changed")
    monkeypatch.setattr(builder, "_git", lambda *_args, **_kwargs: "")
    with pytest.raises(builder.FreezeBuilderError, match="runtime path drift"):
        builder._clean_source_tree(repo, {"shengji_native_extension": {
            "status": "present", "path": str(native.resolve()),
            "sha256": hashlib.sha256(b"original").hexdigest()}})


def test_real_input_wiring_returns_tier_and_refuses_policy_drift(
        monkeypatch, tmp_path):
    """Exercise the actual validator instead of stubbing the whole boundary."""
    repo = tmp_path / "repo"
    inputs = repo / "inputs"
    inputs.mkdir(parents=True)
    evidence = tmp_path / "unused-evidence"
    source_git = "a" * 40
    capacity_raw = b"{}\n"
    protocol_raw = protocol_bytes()
    protocol_sha = hashlib.sha256(protocol_raw).hexdigest()
    capacity_sha = hashlib.sha256(capacity_raw).hexdigest()
    source_sha = "b" * 64
    monkeypatch.setattr(
        builder, "capacity_context",
        lambda _raw: (SimpleNamespace(
            source_sha256=source_sha, runtime_sha256="c" * 64),
                      "D256", 4, 8))
    monkeypatch.setattr(builder, "capacity_source_sha256",
                        lambda _repo: source_sha)
    population = build_population_adapter_input_v2(
        source_git=source_git, protocol_sha256=protocol_sha,
        capacity_sha256=capacity_sha, selected_tier="D256", workers=4,
        deadline_seconds=100, heartbeat_seconds=10,
        max_attempts_per_slot=3)
    config = build_early_stage_config_v2(
        source_git=source_git, protocol_sha256=protocol_sha,
        capacity_sha256=capacity_sha, selected_tier="D256", label_workers=8,
        evidence_root=str(evidence), deadline_seconds=100)
    seed = build_seed_registry_v2(
        source_git=source_git, protocol_sha256=protocol_sha,
        capacity_sha256=capacity_sha, selected_tier="D256")
    policy = build_continuation_policy_v2(
        source_git=source_git, protocol_sha256=protocol_sha,
        capacity_sha256=capacity_sha, selected_tier="D256")
    raws = (protocol_raw, capacity_raw, canonical_json_bytes(population),
            canonical_json_bytes(config), canonical_json_bytes(seed),
            canonical_json_bytes(policy))
    paths = []
    for label, raw in zip(builder._ARTIFACT_LABELS, raws, strict=True):
        path = inputs / f"{label}.json"
        path.write_bytes(raw)
        path.chmod(0o400)
        paths.append((label, path))

    bindings, tier = builder._validate_inputs(
        repo, tuple(paths), source_git=source_git,
        evidence_root=evidence, deadline_seconds=100, heartbeat_seconds=10,
        runtime_sha256="c" * 64)
    assert tier == "D256"
    assert tuple(row[0] for row in bindings) == builder._ARTIFACT_LABELS

    population_path = paths[2][1]
    changed_population = dict(population)
    changed_population["heartbeat_seconds"] = 11
    population_path.chmod(0o600)
    population_path.write_bytes(canonical_json_bytes(changed_population))
    population_path.chmod(0o400)
    with pytest.raises(builder.FreezeBuilderError, match="authoritative reopen"):
        builder._validate_inputs(
            repo, tuple(paths), source_git=source_git,
            evidence_root=evidence, deadline_seconds=100,
            heartbeat_seconds=10, runtime_sha256="c" * 64)
    population_path.chmod(0o600)
    population_path.write_bytes(canonical_json_bytes(population))
    population_path.chmod(0o400)

    policy_path = paths[-1][1]
    changed = dict(policy)
    changed["continuation_policy"] = "wrong"
    policy_path.chmod(0o600)
    policy_path.write_bytes(canonical_json_bytes(changed))
    policy_path.chmod(0o400)
    with pytest.raises(builder.FreezeBuilderError, match="authoritative reopen"):
        builder._validate_inputs(
            repo, tuple(paths), source_git=source_git,
            evidence_root=evidence, deadline_seconds=100,
            heartbeat_seconds=10, runtime_sha256="c" * 64)
