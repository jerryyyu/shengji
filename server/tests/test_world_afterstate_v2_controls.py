import copy
import dataclasses

import numpy as np
import pytest
import shengji.rl.world_afterstate_v2_controls as controls_module

from shengji.rl.world_afterstate_v2_controls import (
    AUTHORITY, WorldAfterstateV2ControlError,
    action_association_permutation, complete_world_shuffle,
    collate_control_training_examples, control_training_examples,
    label_permutation, mix_control_populations,
    validate_control_evidence,
)

from test_world_afterstate_v2_training import _rows, _tensor


def _population(*names):
    result = []
    for root_index, name in enumerate(names):
        for row in _rows(name, candidates=2):
            # The fixture's identity tensors are intentionally varied here so
            # complete-world shuffle has a measurable world-channel dose.
            result.append(dataclasses.replace(
                row, tensors=_tensor(root_index * 3 + row.candidate_index),
                signed_level_category=(root_index * 17
                                       + row.candidate_index * 3
                                       + row.replica) % 204))
    return result


def test_association_deranges_bindings_but_keeps_labels_and_metadata():
    natural = _population("a")
    controlled, evidence = action_association_permutation(natural, seed=19)
    assert evidence["authority"] == AUTHORITY
    assert evidence["row_dose_ppm"] == 1_000_000
    assert evidence["changed_row_count"] == len(natural)
    assert [row.target_category for row in controlled] == [
        row.signed_level_category for row in natural]
    assert all(row.natural.candidate_index == row.candidate_index
               and row.natural.protected_incumbent
               == (row.candidate_index == 0)
               for row in controlled)
    assert all(row.successor_sha256 == row.natural.successor_sha256
               for row in controlled)
    assert all(row.donor_successor_sha256 != row.successor_sha256
               for row in controlled)
    validate_control_evidence(evidence, natural=natural, controlled=controlled)


def test_label_permutation_uses_collection_strata_and_whole_replica_families():
    natural = _population("a", "b", "c", "d")
    controlled, evidence = label_permutation(natural, seed=23)
    assert evidence["effective_dose_ppm"] >= 400_000
    assert sorted(row.target_category for row in controlled) == sorted(
        row.signed_level_category for row in natural)
    for row in controlled:
        assert row.tensors is not row.natural.tensors
        assert np.array_equal(row.tensors.public, row.natural.tensors.public)
        assert np.array_equal(row.tensors.history, row.natural.tensors.history)
        assert row.successor_sha256 == row.natural.successor_sha256
    validate_control_evidence(evidence, natural=natural, controlled=controlled)


def test_label_permutation_uses_outcome_blind_collection_geometry_not_predictive_public_buckets(
        monkeypatch):
    natural = []
    roots = {}
    specs = (
        ("natural", "early", "lead", "attacker", "2", "S", "0-39", 2),
        ("natural", "early", "lead", "defender", "3", "H", "40-79", 5),
        ("natural", "early", "lead", "attacker", "4", "D", "80+", 2),
        ("natural", "early", "lead", "defender", "5", "C", "0-39", 5),
        ("pt-luna", "middle", "follow", "attacker", "6", "S", "40-79", 2),
        ("pt-luna", "middle", "follow", "defender", "7", "H", "80+", 5),
        ("pt-luna", "middle", "follow", "attacker", "8", "D", "0-39", 2),
        ("pt-luna", "middle", "follow", "defender", "9", "C", "40-79", 5),
    )
    for index, (source, phase, position, role, trump_rank, trump_mode,
                points_bucket, candidates) in enumerate(specs):
        rows = [dataclasses.replace(
            row, source=source, phase=phase, position=position, role=role,
            trump_rank=trump_rank, trump_mode=trump_mode,
            points_bucket=points_bucket, signed_level_category=10 + index)
                for row in _rows(f"collection-{index}", candidates=candidates)]
        natural.extend(rows)
        roots[rows[0].root_key] = rows[0]

    controlled, evidence = label_permutation(natural, seed=23)
    assert evidence["effective_dose_ppm"] >= 400_000
    assert sorted(row.target_category for row in controlled) == sorted(
        row.signed_level_category for row in natural)
    donor_families = {}
    for row in controlled:
        donor_root, donor_candidate = row.donor_key.rsplit(":", 1)
        donor = roots[donor_root]
        assert (donor.source, donor.phase, donor.position) == (
            row.natural.source, row.natural.phase, row.natural.position)
        donor_families.setdefault(
            (row.root_key, row.candidate_index), set()).add(
                (donor_root, int(donor_candidate)))
    assert all(len(donors) == 1 for donors in donor_families.values())

    monkeypatch.setattr(controls_module, "_label_stratum",
                        controls_module._stratum)
    with pytest.raises(WorldAfterstateV2ControlError, match="minimum dose"):
        label_permutation(natural, seed=23)


def test_world_shuffle_only_changes_world_and_pairs_different_deals():
    natural = _population("a", "b", "c", "d")
    controlled, evidence = complete_world_shuffle(natural, seed=29)
    assert evidence["row_dose_ppm"] >= 900_000
    for row in controlled:
        source = row.natural
        assert np.array_equal(row.tensors.public, source.tensors.public)
        assert np.array_equal(row.tensors.history, source.tensors.history)
        assert np.array_equal(row.tensors.perspective, source.tensors.perspective)
        assert row.target_category == source.signed_level_category
    assert any(not np.array_equal(row.tensors.world, row.natural.tensors.world)
               for row in controlled)
    validate_control_evidence(evidence, natural=natural, controlled=controlled)


def test_controls_refuse_incomplete_singleton_zero_dose_and_bad_receipts():
    natural = _population("a", "b", "c", "d")
    with pytest.raises(WorldAfterstateV2ControlError, match="incomplete"):
        action_association_permutation(natural[:-1])
    with pytest.raises(WorldAfterstateV2ControlError, match="compatible deal"):
        complete_world_shuffle(_population("only"))
    zero = [dataclasses.replace(row, signed_level_category=100)
            for row in natural]
    with pytest.raises(WorldAfterstateV2ControlError, match="minimum dose"):
        label_permutation(zero)
    _rows_control, receipt = action_association_permutation(natural)
    forged = copy.deepcopy(receipt)
    forged["seed"] += 1
    with pytest.raises(WorldAfterstateV2ControlError):
        validate_control_evidence(forged)
    forged = copy.deepcopy(receipt)
    forged["changed_row_count"] -= 1
    with pytest.raises(WorldAfterstateV2ControlError):
        validate_control_evidence(forged)


def test_controls_refuse_stratum_crossing_protected_leaks_and_mixed_controls():
    natural = _population("a", "b", "c", "d")
    bad = list(natural)
    bad[-1] = dataclasses.replace(bad[-1], trump_mode="H")
    with pytest.raises(WorldAfterstateV2ControlError,
                       match="root mechanics|root identity"):
        action_association_permutation(bad)
    association, _ = action_association_permutation(natural)
    labels, _ = label_permutation(natural)
    with pytest.raises(WorldAfterstateV2ControlError, match="multiple controls"):
        mix_control_populations(association, labels)
    with pytest.raises(WorldAfterstateV2ControlError, match="source row"):
        action_association_permutation([
            dataclasses.replace(natural[0], split="audit")])


def test_each_control_rebinds_to_a_distinct_valid_training_population():
    natural = _population("a", "b", "c", "d")
    for transform in (action_association_permutation, label_permutation,
                      complete_world_shuffle):
        controlled, _ = transform(natural)
        batch = collate_control_training_examples(controlled)
        assert batch.cohort == "control"
        assert batch.size == len(natural)


def test_real_controls_reuse_the_exact_natural_root_schedule():
    from shengji.rl.world_afterstate_v2_schedule import (
        reuse_schedule_for_control, training_epoch_batches,
        validate_control_schedule_match,
    )

    natural = _population("a", "b", "c", "d")
    natural_schedule, _ = training_epoch_batches(natural, epoch=1)
    for transform in (action_association_permutation, label_permutation,
                      complete_world_shuffle):
        controlled, receipt = transform(natural)
        transformed = control_training_examples(controlled)
        control_schedule, _ = reuse_schedule_for_control(
            natural_schedule, transformed, control_name=receipt["control_name"])
        validate_control_schedule_match(natural_schedule, control_schedule)


def test_control_source_mechanics_and_protected_binding_refuse_when_mutated():
    natural = _population("a", "b", "c", "d")
    bad_crn = list(natural)
    bad_crn[-1] = dataclasses.replace(
        bad_crn[-1], continuation_sha256="0" * 64)
    with pytest.raises(WorldAfterstateV2ControlError, match="root mechanics"):
        action_association_permutation(bad_crn)

    controlled, receipt = action_association_permutation(natural)
    forged = list(controlled)
    forged[0] = dataclasses.replace(
        forged[0], natural=dataclasses.replace(
            forged[0].natural, role="defender"))
    with pytest.raises(WorldAfterstateV2ControlError):
        validate_control_evidence(receipt, natural=natural, controlled=forged)
