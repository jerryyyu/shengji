from __future__ import annotations

import copy
import hashlib

import numpy as np
import pytest

from shengji.rl.world_afterstate import (
    PERSPECTIVE_DIM, PUBLIC_DIM, WORLD_RECEIVERS, WorldAfterstateExampleV0,
    WorldAfterstateTensorsV0)
from shengji.rl.world_afterstate_dataset import ReopenedDatasetRowV0
from shengji.rl.world_afterstate_evaluation import EvaluationOutcomeV0
from shengji.rl.world_afterstate_v1_dataset import (
    AUTHORITY, WorldAfterstateV1DatasetError, build_advantage_manifest,
    join_advantage_examples, select_manifest_eligible_advantage_rows,
    validate_advantage_manifest)
from shengji.rl.douzero_micro import HISTORY_EVENT_DIM
from shengji.rl.encode import N_CARDS


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def _row(state: str, candidate: int, replicate: int, category: int,
         *, fold: str = "train") -> ReopenedDatasetRowV0:
    state_id = _digest(state)
    successor = _digest(f"{state}-{candidate}")
    public = np.zeros(PUBLIC_DIM, dtype=np.float32)
    public[0] = candidate
    history = np.zeros((1, HISTORY_EVENT_DIM), dtype=np.float32)
    world = np.zeros((WORLD_RECEIVERS, N_CARDS), dtype=np.float32)
    world[0, candidate] = 0.5
    perspective = np.asarray([1.0, 0.0], dtype=np.float32)
    example = WorldAfterstateExampleV0(
        tensors=WorldAfterstateTensorsV0(
            public=public, history=history, world=world,
            perspective=perspective),
        signed_level_category=category, successor_sha256=successor)
    outcome = EvaluationOutcomeV0(
        deal_group_sha256=_digest(f"deal-{state}"),
        state_group_id=state_id, source="synthetic", fold=fold,
        root_role="attacker", play_phase="middle", position="lead",
        trump_rank="2", trump_mode="suit", points_bucket="0-39",
        candidate_index=candidate, protected_incumbent=candidate == 0,
        successor_sha256=successor, replicate=replicate,
        signed_level_category=category)
    return ReopenedDatasetRowV0(
        example=example, evaluation_outcome=outcome,
        row_sha256=_digest(f"row-{state}-{candidate}-{replicate}"))


def _population():
    rows = []
    for state in ("a", "b"):
        for candidate in range(3):
            for replicate in range(2):
                rows.append(_row(
                    state, candidate, replicate,
                    100 + candidate + replicate))
    return rows


def test_exact_siblings_join_and_manifest_without_private_tensors():
    joined = join_advantage_examples(_population())
    assert len(joined) == 8
    assert {value.pair.candidate_index for value in joined} == {1, 2}
    assert all(value.example.advantage_levels == value.pair.candidate_index
               for value in joined)
    manifest = build_advantage_manifest(
        joined, v0_dataset_manifest_sha256="a" * 64)
    validate_advantage_manifest(manifest)
    assert manifest["state_count"] == 2
    assert manifest["pair_count"] == 8
    assert manifest["authority"] == AUTHORITY
    assert "example" not in str(manifest)


def test_manifest_eligible_selector_excludes_only_proven_singletons():
    rows = _population() + [
        _row("singleton", 0, replicate, 100 + replicate)
        for replicate in range(2)
    ]
    counts = {
        _digest("a"): 3, _digest("b"): 3,
        _digest("singleton"): 1,
    }
    selected = select_manifest_eligible_advantage_rows(
        rows, candidate_counts_by_state_group=counts)
    assert len(selected) == len(_population())
    assert {row.evaluation_outcome.state_group_id for row in selected} \
        == {_digest("a"), _digest("b")}
    assert len(join_advantage_examples(selected)) == 8

    with pytest.raises(WorldAfterstateV1DatasetError,
                       match="candidate-count population drift"):
        select_manifest_eligible_advantage_rows(
            rows[:-1], candidate_counts_by_state_group=counts)
    forged_counts = dict(counts)
    forged_counts[_digest("a")] = 4
    with pytest.raises(WorldAfterstateV1DatasetError,
                       match="candidate-count population drift"):
        select_manifest_eligible_advantage_rows(
            rows, candidate_counts_by_state_group=forged_counts)


def test_join_refuses_cross_split_and_duplicate_rows():
    rows = _population()
    rows[0] = _row("a", 0, 0, 100, fold="report")
    with pytest.raises(WorldAfterstateV1DatasetError,
                       match="reopened V0 row binding drift"):
        join_advantage_examples(rows)
    rows = _population()
    with pytest.raises(WorldAfterstateV1DatasetError,
                       match="duplicate reopened V0 row"):
        join_advantage_examples(rows + [rows[0]])


def test_join_refuses_missing_replicate_and_cross_candidate_label():
    with pytest.raises(WorldAfterstateV1DatasetError,
                       match="pair construction refused"):
        join_advantage_examples(_population()[:-1])
    rows = _population()
    forged = copy.copy(rows[-1])
    object.__setattr__(forged.example, "signed_level_category", 0)
    with pytest.raises(WorldAfterstateV1DatasetError,
                       match="reopened V0 row binding drift"):
        join_advantage_examples(rows[:-1] + [forged])


def test_joined_binding_and_manifest_reconstruction_have_teeth():
    joined = list(join_advantage_examples(_population()))
    forged_join = copy.copy(joined[0])
    object.__setattr__(forged_join, "candidate_row_sha256",
                       forged_join.incumbent_row_sha256)
    with pytest.raises(WorldAfterstateV1DatasetError,
                       match="sibling binding drift"):
        forged_join.validate()

    manifest = build_advantage_manifest(
        joined, v0_dataset_manifest_sha256="b" * 64)
    forged = copy.deepcopy(manifest)
    forged["pairs"][0]["advantage_levels"] += 1
    with pytest.raises(WorldAfterstateV1DatasetError,
                       match="reconstruction drift"):
        validate_advantage_manifest(forged)


def test_manifest_refuses_order_and_report_claim_drift():
    joined = list(join_advantage_examples(_population()))
    with pytest.raises(WorldAfterstateV1DatasetError,
                       match="order drift"):
        build_advantage_manifest(
            list(reversed(joined)), v0_dataset_manifest_sha256="c" * 64)
    manifest = build_advantage_manifest(
        joined, v0_dataset_manifest_sha256="c" * 64)
    manifest["contains_report_or_provider_audit"] = True
    with pytest.raises(WorldAfterstateV1DatasetError,
                       match="schema drift"):
        validate_advantage_manifest(manifest)
