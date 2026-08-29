from __future__ import annotations

import copy
import hashlib

import pytest

from shengji.rl.world_afterstate_v1_dataset import join_advantage_examples
from shengji.rl.world_afterstate_v1_schedule import (
    AUTHORITY, WorldAfterstateV1ScheduleError, build_subsplit_manifest,
    build_training_batches, deal_subsplit, validate_schedule_receipt,
    validate_subsplit_manifest)

from test_world_afterstate_v1_dataset import _row


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def _fixture():
    rows = []
    bindings = []
    for state_index in range(30):
        state = f"state-{state_index}"
        state_id = _digest(state)
        deal = _digest(f"deal-{state}")
        bindings.append({
            "deal_group_sha256": deal, "state_group_id": state_id,
            "fold": "train",
        })
        for candidate in range(3):
            for replicate in range(2):
                row = _row(
                    state, candidate, replicate,
                    100 + candidate + replicate)
                object.__setattr__(row.evaluation_outcome,
                                   "deal_group_sha256", deal)
                rows.append(row)
    return rows, bindings


def test_subsplit_is_outcome_blind_nonempty_and_deal_indivisible():
    _rows, bindings = _fixture()
    manifest = build_subsplit_manifest(
        bindings, v0_population_manifest_sha256="a" * 64)
    validate_subsplit_manifest(manifest)
    assert manifest["fit_state_count"] + manifest["select_state_count"] == 30
    assert manifest["fit_state_count"] > manifest["select_state_count"] > 0
    assert manifest["outcome_fields_present"] is False
    assert manifest["authority"] == AUTHORITY
    assert all(row["split"] == deal_subsplit(row["deal_group_sha256"])
               for row in manifest["states"])


def test_subsplit_refuses_outcome_fields_and_derived_split_drift():
    _rows, bindings = _fixture()
    forged_binding = dict(bindings[0], signed_level_category=100)
    with pytest.raises(WorldAfterstateV1ScheduleError,
                       match="state binding drift"):
        build_subsplit_manifest(
            [forged_binding, *bindings[1:]],
            v0_population_manifest_sha256="b" * 64)
    manifest = build_subsplit_manifest(
        bindings, v0_population_manifest_sha256="b" * 64)
    forged = copy.deepcopy(manifest)
    forged["states"][0]["split"] = (
        "select" if forged["states"][0]["split"] == "fit" else "fit")
    with pytest.raises(WorldAfterstateV1ScheduleError,
                       match="derivation drift"):
        validate_subsplit_manifest(forged)


def test_schedule_is_repeatable_complete_and_never_splits_a_root():
    rows, bindings = _fixture()
    joined = list(join_advantage_examples(rows))
    manifest = build_subsplit_manifest(
        bindings, v0_population_manifest_sha256="c" * 64)
    first_batches, first_receipt = build_training_batches(
        joined, subsplit_manifest=manifest, split="fit", pair_cap=8,
        schedule_seed=41, epoch=1)
    second_batches, second_receipt = build_training_batches(
        joined, subsplit_manifest=manifest, split="fit", pair_cap=8,
        schedule_seed=41, epoch=1)
    assert first_receipt == second_receipt
    assert [batch.pair_keys for batch in first_batches] \
        == [batch.pair_keys for batch in second_batches]
    assert all(len(batch.pair_keys) <= 8 for batch in first_batches)
    validate_schedule_receipt(first_receipt)
    state_to_batch = {}
    for index, batch in enumerate(first_batches):
        for state in batch.state_group_ids:
            assert state_to_batch.setdefault(state, index) == index


def test_fit_and_select_are_disjoint_and_exhaust_manifest():
    rows, bindings = _fixture()
    joined = list(join_advantage_examples(rows))
    manifest = build_subsplit_manifest(
        bindings, v0_population_manifest_sha256="d" * 64)
    fit, _ = build_training_batches(
        joined, subsplit_manifest=manifest, split="fit", pair_cap=12,
        schedule_seed=43, epoch=1)
    select, _ = build_training_batches(
        joined, subsplit_manifest=manifest, split="select", pair_cap=12,
        schedule_seed=43, epoch=1)
    fit_states = {state for batch in fit for state in batch.state_group_ids}
    select_states = {
        state for batch in select for state in batch.state_group_ids}
    assert fit_states.isdisjoint(select_states)
    assert fit_states | select_states \
        == {row["state_group_id"] for row in manifest["states"]}


def test_schedule_receipt_split_root_witness_has_teeth():
    rows, bindings = _fixture()
    joined = list(join_advantage_examples(rows))
    manifest = build_subsplit_manifest(
        bindings, v0_population_manifest_sha256="e" * 64)
    _batches, receipt = build_training_batches(
        joined, subsplit_manifest=manifest, split="fit", pair_cap=8,
        schedule_seed=47, epoch=1)
    forged = copy.deepcopy(receipt)
    forged["batch_pair_keys"][0][-1], forged["batch_pair_keys"][1][-1] = (
        forged["batch_pair_keys"][1][-1],
        forged["batch_pair_keys"][0][-1])
    with pytest.raises(WorldAfterstateV1ScheduleError,
                       match="split one root"):
        validate_schedule_receipt(forged)
