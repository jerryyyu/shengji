from __future__ import annotations

import copy
import json

import pytest

from shengji.rl.belief_contract import canonical_json_bytes
from shengji.rl.world_afterstate import (
    build_outcome, reopen_afterstate_audit)
from shengji.rl.world_afterstate_dataset import (
    WorldAfterstateDatasetError, build_dataset_manifest, build_dataset_row,
    reopen_dataset_manifest, reopen_dataset_row, validate_dataset_manifest)
from shengji.rl.world_afterstate_label import continuation_identity
from shengji.rl.world_afterstate_population import build_population_manifest

from test_world_afterstate_population import _manifest_groups, _natural_group


def _row(monkeypatch):
    group, audits = _natural_group()
    audit = json.loads(audits[0])
    identity = continuation_identity(
        experiment_id="f" * 64, state_group_id=group["state_group_id"],
        fold="train", world_occurrence=0, replicate=0)
    rnd = reopen_afterstate_audit(audit)
    continuation = {
        "continuation_identity": identity,
        "outcome": build_outcome(
            audit["successor_sha256"], 120,
            rnd.is_attacker(audit["root_seat"])),
    }
    monkeypatch.setattr(
        "shengji.rl.world_afterstate_dataset.reopen_afterstate_continuation",
        lambda _audit, value: value)
    return group, build_dataset_row(
        freeze_sha256="f" * 64, group=group, candidate_index=0,
        world_occurrence=0, replicate=0, audit_raw=audits[0],
        continuation_raw=canonical_json_bytes(continuation))


def test_private_row_reopens_transition_and_engine_outcome(monkeypatch):
    group, row = _row(monkeypatch)
    reopened = reopen_dataset_row(row, group=group, allowed_folds=("train",))
    assert reopened.example.successor_sha256 \
        == group["candidates"][0]["successor_sha256"]
    assert reopened.evaluation_outcome.fold == "train"

    forged = copy.deepcopy(row)
    forged["signed_level_category"] += 1
    with pytest.raises(WorldAfterstateDatasetError,
                       match="reconstruction drift"):
        reopen_dataset_row(forged, group=group, allowed_folds=("train",))

    source_group, audits = _natural_group()
    identity = continuation_identity(
        experiment_id="f" * 64,
        state_group_id=source_group["state_group_id"], fold="train",
        world_occurrence=1, replicate=0)
    continuation = {"continuation_identity": identity,
                    "outcome": row["continuation"]["outcome"]}
    with pytest.raises(WorldAfterstateDatasetError,
                       match="row identity drift"):
        build_dataset_row(
            freeze_sha256="f" * 64, group=source_group,
            candidate_index=0, world_occurrence=1, replicate=0,
            audit_raw=audits[0],
            continuation_raw=canonical_json_bytes(continuation))


def test_split_refuses_before_private_payload_is_touched(monkeypatch):
    group, row = _row(monkeypatch)
    forged = copy.deepcopy(row)
    forged["audit"] = "not an object"
    with pytest.raises(WorldAfterstateDatasetError,
                       match="before private row opening"):
        reopen_dataset_row(forged, group=group,
                           allowed_folds=("calibration",))


def test_manifest_requires_every_candidate_and_replicate(
        monkeypatch, tmp_path):
    # A compact synthetic manifest keeps this test focused on row inventory.
    groups = _manifest_groups()
    manifest = build_population_manifest(groups)
    rows = []
    repetitions = {"train": 1, "calibration": 1,
                   "report": 1, "provider-audit": 1}

    def fake_static(row, *, group):
        assert row["state_group_id"] == group["state_group_id"]
        return row["row_sha256"]

    monkeypatch.setattr(
        "shengji.rl.world_afterstate_dataset.validate_dataset_row_static",
        fake_static)
    for group in groups:
        for candidate in range(group["candidate_count"]):
            rows.append({
                "state_group_id": group["state_group_id"],
                "candidate_index": candidate, "replicate": 0,
                "freeze_sha256": "f" * 64,
                "row_sha256": group["group_sha256"],
            })
    result = build_dataset_manifest(
        freeze_sha256="f" * 64, population_manifest=manifest,
        rows=rows, repetitions_by_fold=repetitions)
    validate_dataset_manifest(result, population_manifest=manifest)
    assert result["row_count"] == len(rows)
    assert all(binding["relative_path"].startswith(
        f"rows/{binding['fold']}/") for binding in result["rows"])
    raw_by_path = {}
    input_by_key = {(row["state_group_id"], row["candidate_index"],
                     row["replicate"]): canonical_json_bytes(row)
                    for row in rows}
    for binding in result["rows"]:
        raw_by_path[binding["relative_path"]] = input_by_key[(
            binding["state_group_id"], binding["candidate_index"],
            binding["replicate"])]
    opened = []

    def fake_read(path):
        relative = str(path.relative_to(tmp_path))
        opened.append(relative)
        return raw_by_path[relative]

    monkeypatch.setattr(
        "shengji.rl.world_afterstate_dataset._sealed_row_read", fake_read)
    monkeypatch.setattr(
        "shengji.rl.world_afterstate_dataset.reopen_dataset_row_static",
        lambda row, *, group, allowed_folds: type(
            "Reopened", (), {"row_sha256": row["row_sha256"]})())
    selected = reopen_dataset_manifest(
        result, population_manifest=manifest, row_root=tmp_path,
        allowed_folds=("train",))
    assert len(selected) == result["fold_row_counts"]["train"]
    assert opened and all(path.startswith("rows/train/") for path in opened)

    class ImmediateFuture:
        def __init__(self, value):
            self.value = value

        def result(self):
            return self.value

        def cancel(self):
            return False

    class ImmediateExecutor:
        def __init__(self, *, max_workers):
            assert max_workers == 2

        def submit(self, function, arguments):
            return ImmediateFuture(function(arguments))

        def shutdown(self, *, wait, cancel_futures):
            assert wait is True and cancel_futures is True

    monkeypatch.setattr(
        "shengji.rl.world_afterstate_dataset.ProcessPoolExecutor",
        ImmediateExecutor)
    monkeypatch.setattr(
        "shengji.rl.world_afterstate_dataset.wait",
        lambda pending, **_kwargs: ({next(iter(pending))}, set()))
    monkeypatch.setattr(
        "shengji.rl.world_afterstate_dataset.reopen_dataset_row",
        lambda row, *, group, allowed_folds: type(
            "Reopened", (), {"row_sha256": row["row_sha256"]})())
    monkeypatch.setattr(
        "shengji.rl.world_afterstate_dataset.reopen_dataset_row_static",
        lambda row, *, group, allowed_folds: type(
            "Reopened", (), {"row_sha256": row["row_sha256"]})())
    static_progress = []
    parallel_static = reopen_dataset_manifest(
        result, population_manifest=manifest, row_root=tmp_path,
        allowed_folds=("train",), reconstruct_continuations=False,
        reconstruction_workers=2, deadline_monotonic_ns=10**30,
        progress=lambda completed, total:
            static_progress.append((completed, total)))
    assert len(parallel_static) == len(selected)
    assert static_progress[-1] == (len(selected), len(selected))
    parallel_progress = []
    parallel = reopen_dataset_manifest(
        result, population_manifest=manifest, row_root=tmp_path,
        allowed_folds=("train",), reconstruct_continuations=True,
        reconstruction_workers=2,
        deadline_monotonic_ns=10**30,
        progress=lambda completed, total:
            parallel_progress.append((completed, total)))
    assert len(parallel) == len(selected)
    assert parallel_progress[-1] == (len(selected), len(selected))

    with pytest.raises(WorldAfterstateDatasetError,
                       match="incomplete row population"):
        build_dataset_manifest(
            freeze_sha256="f" * 64, population_manifest=manifest,
            rows=rows[:-1], repetitions_by_fold=repetitions)
