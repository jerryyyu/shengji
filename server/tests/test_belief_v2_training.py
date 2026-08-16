"""Mixed synthetic/human V2 example and source-neutral batch tests."""

from __future__ import annotations

import random
from dataclasses import fields, replace

import numpy as np
import pytest

from shengji.ai.heuristic import HeuristicBot
from shengji.engine.game import Game
from shengji.engine.round import actual_play_after
from shengji.rl.belief_b2_protocol import b2_split_round_seeds
from shengji.rl.belief_contract import PublicTranscriptV1
from shengji.rl.belief_corpus import capture_corpus_pair
from shengji.rl.belief_model import new_from_scratch_model
from shengji.rl.belief_trainer import new_b2_optimizer, train_epoch
from shengji.rl.belief_training import (
    CONTROL_TRAINING_BATCH_SCHEMA,
    GEOMETRY_PERMUTED_LABELS,
    LABEL_PERMUTATION_CONTROL,
)
from shengji.rl.belief_v2_common_surface import ARRAY_FIELDS
from shengji.rl.belief_v2_human_corpus import capture_human_corpus_pair
from shengji.rl.belief_v2_schedule import (
    BeliefV2ScheduleError,
    realize_v2_common_calibration,
    validate_v2_common_calibration,
)
from shengji.rl.belief_v2_training import (
    BeliefV2TrainingError,
    build_human_training_example,
    build_synthetic_training_example,
    collate_v2_label_control_examples,
    collate_v2_training_examples,
    validate_human_training_example,
    validate_synthetic_training_example,
)


def _state(seed: int = 12301, plays: int = 9):
    rnd = Game(random.Random(seed)).start_round()
    bot = HeuristicBot()
    transcript = PublicTranscriptV1()
    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        cards = bot.decide_declare(rnd, seat)
        if cards:
            rnd.declare(seat, cards)
            accepted = rnd.declaration
            transcript = transcript.with_declaration(
                accepted["seat"], accepted["cards"], accepted["strength"])
    for seat in range(4):
        cards = bot.decide_declare(rnd, seat, final=True)
        if cards:
            rnd.declare(seat, cards)
            accepted = rnd.declaration
            transcript = transcript.with_declaration(
                accepted["seat"], accepted["cards"], accepted["strength"])
    rnd.finalize_declare()
    rnd.bury(rnd.banker, bot.decide_bury(rnd, rnd.banker))
    for _ in range(plays):
        seat = rnd.turn
        attempted = bot.decide_play(rnd, seat)
        previous_last = rnd.last_trick
        rnd.play(seat, attempted)
        transcript = transcript.with_play(
            seat, attempted, actual_play_after(rnd, seat, previous_last))
    return rnd, transcript


def _paired_examples(split: str = "train"):
    rnd, transcript = _state()
    seat = rnd.turn
    round_seed = b2_split_round_seeds(split)[0]
    synthetic_pair = capture_corpus_pair(
        rnd, seat, round_seed=round_seed,
        decision_index=9, transcript=transcript)
    human_pair = capture_human_corpus_pair(
        rnd, seat, group_digest="1" * 64, round_digest="2" * 64,
        decision_index=9, split=split)
    return (
        synthetic_pair, human_pair,
        build_synthetic_training_example(synthetic_pair),
        build_human_training_example(
            human_pair.actor_bytes, human_pair.target_bytes),
    )


def test_same_public_state_has_identical_human_and_synthetic_model_tensors():
    synthetic_pair, human_pair, synthetic, human = _paired_examples()
    validate_synthetic_training_example(synthetic_pair, synthetic)
    validate_human_training_example(
        human_pair.actor_bytes, human_pair.target_bytes, human)
    assert synthetic.source_kind == "synthetic"
    assert human.source_kind == "human"
    assert synthetic.source_actor_sha256 != human.source_actor_sha256
    assert synthetic.common.source_declaration_history_complete is True
    assert human.common.source_declaration_history_complete is False
    assert synthetic.common.source_attempted_play_history_complete is True
    assert human.common.source_attempted_play_history_complete is False
    assert np.array_equal(synthetic.count_labels, human.count_labels)
    assert np.array_equal(synthetic.active_mask, human.active_mask)
    for name in ARRAY_FIELDS:
        assert np.array_equal(
            getattr(synthetic.common.tensors, name),
            getattr(human.common.tensors, name))


def test_mixed_batch_contains_no_source_identity_and_trains_unchanged_model():
    _, _, synthetic, human = _paired_examples()
    batch = collate_v2_training_examples((synthetic, human))
    assert set(field.name for field in fields(batch)).isdisjoint({
        "source_kind", "source_identity", "source_channel_availability"})
    assert batch.events.shape[0] == 2
    assert np.array_equal(batch.events[0].numpy(), batch.events[1].numpy())
    assert np.array_equal(
        batch.count_labels[0].numpy(), batch.count_labels[1].numpy())
    model = new_from_scratch_model(495023836)
    receipt = train_epoch(
        model, new_b2_optimizer(model), (batch,), epoch=1)
    assert receipt.decision_count == 2
    assert receipt.active_label_count == int(batch.active_mask.sum())


def test_source_provenance_rewrite_is_caught_before_collation():
    synthetic_pair, human_pair, synthetic, human = _paired_examples()
    with pytest.raises(BeliefV2TrainingError, match="derivation drift"):
        validate_synthetic_training_example(
            synthetic_pair, replace(synthetic, source_kind="human"))
    with pytest.raises(BeliefV2TrainingError, match="derivation drift"):
        validate_human_training_example(
            human_pair.actor_bytes, human_pair.target_bytes,
            replace(human, source_kind="synthetic"))


def test_v2_label_control_preserves_public_tensors_and_hard_geometry():
    _, _, synthetic, human = _paired_examples()
    natural = collate_v2_training_examples((synthetic, human))
    control, changed_cells = collate_v2_label_control_examples(
        (synthetic, human))
    assert changed_cells > 0
    assert control.schema == CONTROL_TRAINING_BATCH_SCHEMA
    assert control.label_transform == GEOMETRY_PERMUTED_LABELS
    assert control.control_kind == LABEL_PERMUTATION_CONTROL
    assert np.array_equal(control.events.numpy(), natural.events.numpy())
    assert np.array_equal(
        control.active_mask.numpy(), natural.active_mask.numpy())
    assert np.array_equal(
        control.count_labels.numpy().sum(axis=2),
        natural.count_labels.numpy().sum(axis=2))
    assert np.array_equal(
        control.count_labels.numpy().sum(axis=1),
        natural.count_labels.numpy().sum(axis=1))
    model = new_from_scratch_model(495023836)
    receipt = train_epoch(
        model, new_b2_optimizer(model), (control,), epoch=1)
    assert receipt.control_kind == LABEL_PERMUTATION_CONTROL


def test_common_tensor_and_label_mutations_refuse_at_wiring_altitude():
    synthetic_pair, human_pair, synthetic, human = _paired_examples()
    changed_events = synthetic.common.tensors.events.copy()
    changed_events[0, 0] = 1.0 - changed_events[0, 0]
    changed_common = replace(
        synthetic.common,
        tensors=replace(synthetic.common.tensors, events=changed_events))
    with pytest.raises(BeliefV2TrainingError, match="common tensor"):
        validate_synthetic_training_example(
            synthetic_pair, replace(synthetic, common=changed_common))

    labels = human.count_labels.copy()
    index = tuple(int(value) for value in np.argwhere(human.active_mask)[0])
    labels[index] = (int(labels[index]) + 1) % 3
    with pytest.raises(BeliefV2TrainingError, match="derivation drift"):
        validate_human_training_example(
            human_pair.actor_bytes, human_pair.target_bytes,
            replace(human, count_labels=labels))


def test_mixed_batch_refuses_cross_split_duplicate_and_unbound_example():
    _, _, synthetic, human = _paired_examples()
    _, _, _, calibration_human = _paired_examples("calibration")
    with pytest.raises(BeliefV2TrainingError, match="split/policy"):
        collate_v2_training_examples((synthetic, calibration_human))
    with pytest.raises(BeliefV2TrainingError, match="duplicate"):
        collate_v2_training_examples((synthetic, synthetic))
    with pytest.raises(BeliefV2TrainingError, match="binding drift"):
        collate_v2_training_examples((
            synthetic,
            replace(human, source_identity_model_input=True),
        ))


def test_common_epoch_schedule_is_synthetic_only_and_rederived():
    _, _, calibration_synthetic, calibration_human = _paired_examples(
        "calibration")
    result = realize_v2_common_calibration((calibration_synthetic,))
    validate_v2_common_calibration((calibration_synthetic,), result)
    assert result.to_dict()["selection_role"] == "common-epoch-only"
    assert result.to_dict()["human_calibration_consumed"] is False
    assert result.batches == ((calibration_synthetic.decision_key,),)
    with pytest.raises(BeliefV2ScheduleError):
        realize_v2_common_calibration((calibration_human,))
    with pytest.raises(BeliefV2ScheduleError, match="reconstruction"):
        validate_v2_common_calibration(
            (calibration_synthetic,),
            replace(result, batch_schedule_sha256="f" * 64))
