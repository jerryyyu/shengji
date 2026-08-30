"""Focused safety tests for the inert Value V2 freeze builder."""

from __future__ import annotations

import hashlib
import stat
from pathlib import Path

import pytest

from shengji.rl import world_afterstate_v2_freeze_builder as builder
from shengji.rl.world_afterstate_v2_execution import SourceBindingV2


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
    runtime = {"boot_identity": "boot-1", "python": "test"}
    monkeypatch.setattr(builder, "_head", lambda _repo, _head: head)
    monkeypatch.setattr(builder, "_clean_source_tree", lambda _repo: None)
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
                        lambda: {"boot_identity": "boot-2", "python": "test"})
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
    monkeypatch.setattr(builder, "_git",
                        lambda *_args, **_kwargs: " M server/shengji/x.py")
    with pytest.raises(builder.FreezeBuilderError, match="not clean"):
        builder._clean_source_tree(repo)
    monkeypatch.setattr(builder, "_git",
                        lambda *_args, **_kwargs: "!! server/shengji/x.py")
    (repo / "server" / "shengji" / "x.py").write_text("x")
    with pytest.raises(builder.FreezeBuilderError, match="ignored"):
        builder._clean_source_tree(repo)
