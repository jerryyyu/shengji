from __future__ import annotations

import copy
import json

import numpy as np
import pytest

from shengji.rl.world_afterstate_controls import (
    WorldAfterstateControlError, build_mutation_refusal_evidence,
    complete_world_shuffle,
    geometry_preserving_label_permutation, preaction_replacement_evidence,
    validate_mutation_refusal_evidence, validate_transform_evidence)
from shengji.rl.belief_contract import canonical_json_bytes
from shengji.rl.world_afterstate import build_outcome, reopen_afterstate_audit
from shengji.rl.world_afterstate_dataset import (
    build_dataset_row, reopen_dataset_row_static)
from shengji.rl.world_afterstate_label import continuation_identity

from test_world_afterstate_evaluation import _outcome
from test_world_afterstate_training import _example
from test_world_afterstate_population import _natural_group


def test_geometry_permutation_preserves_identity_and_has_real_dose():
    rows = tuple(_outcome(
        fold="report", deal=100 + index // 2, group=100 + index // 2,
        candidate=index % 2, replicate=0, category=90 + index)
        for index in range(8))
    transformed, evidence = geometry_preserving_label_permutation(rows)
    validate_transform_evidence(evidence)
    assert evidence["changed_count"] == len(rows)
    for original, altered in zip(rows, transformed, strict=True):
        assert original.key() == altered.key()
        assert original.stratum() == altered.stratum()
        assert original.successor_sha256 == altered.successor_sha256
        assert original.signed_level_category != altered.signed_level_category

    identical = tuple(copy.copy(row) for row in rows)
    identical = tuple(row.__class__(
        **{**row.__dict__, "signed_level_category": 100})
        for row in identical)
    unchanged, zero = geometry_preserving_label_permutation(identical)
    validate_transform_evidence(zero)
    assert unchanged == identical
    assert zero["changed_count"] == 0
    assert zero["informative"] is False


def test_complete_world_shuffle_changes_only_world_branch_and_is_bound():
    keys = [f"example-{index}" for index in range(4)]
    examples = [_example(index) for index in range(4)]
    transformed, evidence = complete_world_shuffle(keys, examples)
    validate_transform_evidence(evidence)
    assert evidence["changed_count"] == len(examples)
    for original, altered in zip(examples, transformed, strict=True):
        assert np.array_equal(original.tensors.public, altered.tensors.public)
        assert np.array_equal(original.tensors.history, altered.tensors.history)
        assert np.array_equal(
            original.tensors.perspective, altered.tensors.perspective)
        assert not np.array_equal(original.tensors.world,
                                  altered.tensors.world)
        assert original.signed_level_category == altered.signed_level_category
        assert original.successor_sha256 == altered.successor_sha256

    forged = copy.deepcopy(evidence)
    forged["changed_count"] -= 1
    with pytest.raises(WorldAfterstateControlError,
                       match="reconstruction drift"):
        validate_transform_evidence(forged)


def test_complete_world_shuffle_reports_an_uninformative_identity_transform():
    first = _example(0)
    second = copy.deepcopy(first)
    second = second.__class__(
        tensors=second.tensors, signed_level_category=1,
        successor_sha256=f"{999:064x}")
    _transformed, evidence = complete_world_shuffle(
        ["left", "right"], [first, second])
    validate_transform_evidence(evidence)
    assert evidence["changed_count"] == 0
    assert evidence["informative"] is False


def test_preaction_replacement_binds_changed_inputs_to_same_target():
    successor = [_example(0), _example(1)]
    preaction = copy.deepcopy(successor)
    preaction[0].tensors.public[0] = 1.0
    preaction[1].tensors.world[1, 3] = 0.5
    evidence = preaction_replacement_evidence(
        ["left", "right"], successor, preaction)
    validate_transform_evidence(evidence)
    assert evidence["changed_count"] == 2

    forged = copy.deepcopy(preaction)
    forged[0] = forged[0].__class__(
        tensors=forged[0].tensors,
        signed_level_category=forged[0].signed_level_category + 1,
        successor_sha256=forged[0].successor_sha256)
    with pytest.raises(WorldAfterstateControlError,
                       match="target binding drift"):
        preaction_replacement_evidence(
            ["left", "right"], successor, forged)


def test_named_mutations_are_executed_against_real_sibling_rows(monkeypatch):
    group, audit_raws = _natural_group()
    monkeypatch.setattr(
        "shengji.rl.world_afterstate_dataset.reopen_afterstate_continuation",
        lambda _audit, value: value)
    reopened = []
    for candidate, audit_raw in enumerate(audit_raws):
        audit = json.loads(audit_raw)
        rnd = reopen_afterstate_audit(audit)
        identity = continuation_identity(
            experiment_id="f" * 64,
            state_group_id=group["state_group_id"], fold="train",
            world_occurrence=0, replicate=0)
        continuation = {
            "continuation_identity": identity,
            "outcome": build_outcome(
                audit["successor_sha256"], 120 + candidate * 5,
                rnd.is_attacker(audit["root_seat"])),
        }
        row = build_dataset_row(
            freeze_sha256="f" * 64, group=group,
            candidate_index=candidate, world_occurrence=0, replicate=0,
            audit_raw=audit_raw,
            continuation_raw=canonical_json_bytes(continuation))
        reopened.append(reopen_dataset_row_static(
            row, group=group, allowed_folds=("train",)))
    evidence = build_mutation_refusal_evidence(
        reopened, {group["state_group_id"]: group})
    validate_mutation_refusal_evidence(evidence)
    assert [row["name"] for row in evidence["rows"]] == [
        "ballot", "continuation", "perspective", "transition", "utility"]

    forged = copy.deepcopy(evidence)
    forged["rows"][0]["refusal"] = "not actually witnessed"
    with pytest.raises(WorldAfterstateControlError,
                       match="reconstruction drift"):
        validate_mutation_refusal_evidence(forged)
