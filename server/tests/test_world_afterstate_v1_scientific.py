from __future__ import annotations

import copy
from pathlib import Path

import pytest

from shengji.rl.belief_contract import canonical_json_bytes
from shengji.rl.world_afterstate_v1_admission import ADMISSION_AUTHORITY
from shengji.rl.world_afterstate_v1_experiment import build_experiment_freeze
from shengji.rl.world_afterstate_v1_scientific import (
    WorldAfterstateV1ScientificError, consume_stage_attempt,
    initialize_scientific_root, lock_root_for, reopen_scientific_root)

import shengji.rl.world_afterstate_v1_scientific as scientific
from test_world_afterstate_v1_experiment import _inputs


def _fixture(monkeypatch, tmp_path):
    capacity, runtime, sources = _inputs()
    freeze = build_experiment_freeze(
        capacity, source_git="a" * 40,
        source_sha256s=sources, experiment_runtime=runtime)
    admission = {
        "schema": "fixture", "source_git": "a" * 40,
        "freeze_sha256": freeze["freeze_sha256"],
        "review_commit": "b" * 40,
        "canonical_remote_tip_at_admission": "c" * 40,
        "review_marker_sha256": "d" * 64,
        "review_claim_sha256": "e" * 64,
        "authority": dict(ADMISSION_AUTHORITY),
        "admission_sha256": "f" * 64,
    }
    monkeypatch.setattr(
        scientific, "build_admission",
        lambda _freeze, *, repo, review_commit: copy.deepcopy(admission))
    monkeypatch.setattr(
        scientific, "reauthenticate_admission",
        lambda _value, *, freeze, repo: b"fixture-marker\n")
    monkeypatch.setattr(
        scientific, "validate_admission",
        lambda _value, *, freeze, review_marker: None)
    root = tmp_path / "scientific"
    return root, capacity, freeze, admission


def test_scientific_root_seals_exact_capacity_and_reopens(monkeypatch,
                                                          tmp_path):
    root, capacity, freeze, admission = _fixture(monkeypatch, tmp_path)
    manifest = initialize_scientific_root(
        root, freeze_raw=canonical_json_bytes(freeze),
        capacity_build=capacity, repo=Path.cwd().parent.resolve(),
        review_commit="b" * 40)
    reopened_freeze, reopened_capacity, reopened_admission, reopened_manifest \
        = reopen_scientific_root(root, repo=Path.cwd().parent.resolve())
    assert reopened_freeze == freeze
    assert reopened_capacity == capacity
    assert reopened_admission == admission
    assert reopened_manifest == manifest
    assert (root / "outputs").is_dir()
    assert lock_root_for(root).is_dir()


def test_stage_attempt_is_durable_one_shot_and_root_deletion_cannot_retry(
        monkeypatch, tmp_path):
    root, capacity, freeze, admission = _fixture(monkeypatch, tmp_path)
    initialize_scientific_root(
        root, freeze_raw=canonical_json_bytes(freeze),
        capacity_build=capacity, repo=Path.cwd().parent.resolve(),
        review_commit="b" * 40)
    attempt = consume_stage_attempt(
        root, stage="train-natural",
        freeze_sha256=freeze["freeze_sha256"],
        admission_sha256=admission["admission_sha256"],
        inputs={"cohort": "natural"})
    assert attempt["retry_authorized"] is False
    with pytest.raises(WorldAfterstateV1ScientificError,
                       match="already consumed"):
        consume_stage_attempt(
            root, stage="train-natural",
            freeze_sha256=freeze["freeze_sha256"],
            admission_sha256=admission["admission_sha256"],
            inputs={"cohort": "natural"})

    renamed = root.with_name("scientific-removed")
    root.chmod(0o700)
    root.rename(renamed)
    with pytest.raises(WorldAfterstateV1ScientificError,
                       match="namespace occupied"):
        initialize_scientific_root(
            root, freeze_raw=canonical_json_bytes(freeze),
            capacity_build=capacity, repo=Path.cwd().parent.resolve(),
            review_commit="b" * 40)


def test_scientific_root_file_and_stage_population_checks_have_teeth(
        monkeypatch, tmp_path):
    root, capacity, freeze, _admission = _fixture(monkeypatch, tmp_path)
    initialize_scientific_root(
        root, freeze_raw=canonical_json_bytes(freeze),
        capacity_build=capacity, repo=Path.cwd().parent.resolve(),
        review_commit="b" * 40)
    extra = root / "inputs" / "extra.json"
    (root / "inputs").chmod(0o700)
    extra.write_bytes(b"{}\n")
    extra.chmod(0o400)
    with pytest.raises(WorldAfterstateV1ScientificError,
                       match="file population drift"):
        reopen_scientific_root(root, repo=Path.cwd().parent.resolve())
    with pytest.raises(WorldAfterstateV1ScientificError,
                       match="stage attempt request drift"):
        consume_stage_attempt(
            root, stage="open-report",
            freeze_sha256=freeze["freeze_sha256"],
            admission_sha256="f" * 64, inputs={})
