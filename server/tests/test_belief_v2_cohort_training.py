"""Runnable V2 cohort mechanics, control, and checkpoint-chain tests."""

from __future__ import annotations

import random
from dataclasses import replace

import pytest
import torch

import shengji.rl.belief_v2_cohort_training as STAGE
from shengji.ai.heuristic import HeuristicBot
from shengji.engine.game import Game
from shengji.engine.round import actual_play_after
from shengji.rl.belief_b2_protocol import b2_split_round_seeds
from shengji.rl.belief_contract import PublicTranscriptV1
from shengji.rl.belief_corpus import capture_corpus_pair
from shengji.rl.belief_v2_cohort_training import (
    BeliefV2CohortTrainingError,
    reopen_trained_v2_cohort,
    train_v2_cohort_in_memory,
    validate_trained_v2_cohort,
)
from shengji.rl.belief_v2_freeze import (
    ALL_HUMAN_TRAIN_DECISIONS,
    ALL_SYNTHETIC_TRAIN_DECISIONS,
    MIXED_SYNTHETIC_TRAIN_DECISIONS,
    MIXED_WORK_RULE,
    NO_HUMAN_DECISIONS,
    PRIMARY_WORK_RULE,
    SCALE_SYNTHETIC_TRAIN_DECISIONS,
    SCALE_WORK_RULE,
    V2CohortPlanV1,
)
from shengji.rl.belief_v2_human_corpus import capture_human_corpus_pair
from shengji.rl.belief_v2_schedule import (
    realize_v2_cohorts,
    realize_v2_common_calibration,
    training_row,
)
from shengji.rl.belief_v2_training import (
    build_human_training_example,
    build_synthetic_training_example,
)
from shengji.rl.belief_v2_training_inputs import (
    BeliefV2TrainingInputError,
    V2TrainingInputPopulationV1,
    validate_v2_training_inputs,
)


@pytest.fixture(autouse=True)
def _deterministic_algorithms():
    previous = torch.are_deterministic_algorithms_enabled()
    torch.use_deterministic_algorithms(True)
    try:
        yield
    finally:
        torch.use_deterministic_algorithms(previous)


def _state(seed: int = 31901, plays: int = 9):
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
        previous = rnd.last_trick
        rnd.play(seat, attempted)
        transcript = transcript.with_play(
            seat, attempted, actual_play_after(rnd, seat, previous))
    return rnd, transcript


def _plans():
    return (
        V2CohortPlanV1(
            cohort_id="synthetic-primary", kind="synthetic-primary",
            synthetic_selection_rule=ALL_SYNTHETIC_TRAIN_DECISIONS,
            synthetic_fraction_numerator=1,
            synthetic_fraction_denominator=1,
            human_selection_rule=NO_HUMAN_DECISIONS,
            work_match_rule=PRIMARY_WORK_RULE,
            comparator_cohort_id=None),
        V2CohortPlanV1(
            cohort_id="hard-geometry-label-permutation",
            kind="hard-geometry-label-permutation",
            synthetic_selection_rule=ALL_SYNTHETIC_TRAIN_DECISIONS,
            synthetic_fraction_numerator=1,
            synthetic_fraction_denominator=1,
            human_selection_rule=NO_HUMAN_DECISIONS,
            work_match_rule=PRIMARY_WORK_RULE,
            comparator_cohort_id="synthetic-primary"),
        V2CohortPlanV1(
            cohort_id="human-mixture", kind="human-mixture",
            synthetic_selection_rule=MIXED_SYNTHETIC_TRAIN_DECISIONS,
            synthetic_fraction_numerator=1,
            synthetic_fraction_denominator=1,
            human_selection_rule=ALL_HUMAN_TRAIN_DECISIONS,
            work_match_rule=MIXED_WORK_RULE,
            comparator_cohort_id="synthetic-primary"),
        V2CohortPlanV1(
            cohort_id="synthetic-scale-50", kind="synthetic-scale",
            synthetic_selection_rule=SCALE_SYNTHETIC_TRAIN_DECISIONS,
            synthetic_fraction_numerator=1,
            synthetic_fraction_denominator=2,
            human_selection_rule=NO_HUMAN_DECISIONS,
            work_match_rule=SCALE_WORK_RULE,
            comparator_cohort_id="synthetic-primary"),
    )


def _fixture():
    rnd, transcript = _state()
    seat = rnd.turn
    train_seeds = b2_split_round_seeds("train")[:5]
    synthetic = tuple(build_synthetic_training_example(
        capture_corpus_pair(
            rnd, seat, round_seed=seed, decision_index=9,
            transcript=transcript)) for seed in train_seeds)
    human_pair = capture_human_corpus_pair(
        rnd, seat, group_digest="1" * 64, round_digest="2" * 64,
        decision_index=9, split="train")
    human = (build_human_training_example(
        human_pair.actor_bytes, human_pair.target_bytes),)
    realized = realize_v2_cohorts(
        _plans(),
        synthetic_rows=tuple(training_row(row) for row in synthetic),
        human_rows=tuple(training_row(row) for row in human))
    calibration = tuple(build_synthetic_training_example(
        capture_corpus_pair(
            rnd, seat, round_seed=seed, decision_index=9,
            transcript=transcript))
                        for seed in b2_split_round_seeds("calibration")[:2])
    return synthetic, human, realized, calibration, \
        realize_v2_common_calibration(calibration)


def _one_epoch(monkeypatch, kind: str):
    synthetic, human, realized, calibration, schedule = _fixture()
    monkeypatch.setattr(STAGE, "TRAIN_MAX_EPOCHS", 1)
    value = next(row for row in realized if row.kind == kind)
    by_key = {row.decision_key: row for row in (*synthetic, *human)}
    examples = tuple(by_key[row.decision_key] for row in value.rows)
    result = train_v2_cohort_in_memory(
        value, examples, schedule, calibration, device="cpu")
    return value, examples, schedule, calibration, result


def test_primary_trains_one_common_epoch_and_reopens_every_checkpoint(
        monkeypatch):
    value, examples, schedule, calibration, result = _one_epoch(
        monkeypatch, "synthetic-primary")
    validate_trained_v2_cohort(
        value, examples, schedule, calibration, result)
    assert result.selected_common_epoch == 1
    assert result.stop_epoch == 1
    assert result.label_control_changed_cell_count_per_epoch == 0
    assert len(result.checkpoint_bundles) == 8
    payload = result.to_dict()
    assert payload["common_epoch_calibration_source"] \
        == "balanced-synthetic-only"
    assert payload["human_calibration_consumed_for_common_epoch"] is False
    assert payload["test_split_opened"] is False
    assert payload["deployment_authorized"] is False
    assert reopen_trained_v2_cohort(
        result.manifest_bytes(), result.checkpoint_bundles,
        value, examples, schedule, calibration) == result


def test_label_control_has_real_dose_and_exact_control_receipts(monkeypatch):
    _, _, _, _, result = _one_epoch(
        monkeypatch, "hard-geometry-label-permutation")
    assert result.label_control_changed_cell_count_per_epoch > 0
    assert all(receipt.control_kind == "hard-geometry-label-permutation"
               for receipt in result.epochs[0].member_training_receipts)


def test_human_mixture_uses_same_work_and_synthetic_common_epoch(monkeypatch):
    value, examples, schedule, calibration, result = _one_epoch(
        monkeypatch, "human-mixture")
    assert value.human_decision_count == 1
    assert value.synthetic_decision_count == 4
    assert len(examples) == 5
    assert result.epochs[0].member_training_receipts[0].decision_count == 5
    assert result.common_calibration_sha256 == schedule.sha256()
    validate_trained_v2_cohort(
        value, examples, schedule, calibration, result)


def test_epoch_chain_checkpoint_and_selection_rewrites_refuse(monkeypatch):
    value, examples, schedule, calibration, result = _one_epoch(
        monkeypatch, "synthetic-primary")
    row = result.epochs[0]
    changed_receipt = replace(
        row.member_training_receipts[0],
        model_state_sha256_before="f" * 64)
    changed = replace(result, epochs=(replace(
        row, member_training_receipts=(
            changed_receipt, *row.member_training_receipts[1:])),))
    with pytest.raises(BeliefV2CohortTrainingError, match="chain"):
        validate_trained_v2_cohort(
            value, examples, schedule, calibration, changed)

    raw = bytearray(result.checkpoint_bundles[0])
    raw[-1] ^= 1
    changed = replace(result, checkpoint_bundles=(
        bytes(raw), *result.checkpoint_bundles[1:]))
    with pytest.raises(BeliefV2CohortTrainingError, match="checkpoint"):
        validate_trained_v2_cohort(
            value, examples, schedule, calibration, changed)

    changed = replace(result, selected_common_epoch=2)
    with pytest.raises(BeliefV2CohortTrainingError, match="common epoch"):
        validate_trained_v2_cohort(
            value, examples, schedule, calibration, changed)

    with pytest.raises(BeliefV2CohortTrainingError, match="device"):
        validate_trained_v2_cohort(
            value, examples, schedule, calibration,
            replace(result, training_device="cuda"))


def test_closed_training_input_population_reconstructs_every_schedule():
    synthetic, human, realized, calibration, schedule = _fixture()
    value = V2TrainingInputPopulationV1(
        synthetic_train_examples=synthetic,
        synthetic_calibration_examples=calibration,
        human_train_examples=human,
        cohort_plans=_plans(), realizations=realized,
        common_calibration=schedule,
        human_group_manifest_sha256s=("a" * 64,))
    validate_v2_training_inputs(value)
    payload = value.manifest()
    assert payload["synthetic_test_targets_opened"] is False
    assert payload["human_test_targets_opened"] is False
    assert payload["source_identity_model_input"] is False
    assert value.canonical_bytes().endswith(b"\n")
    with pytest.raises(BeliefV2TrainingInputError,
                       match="artifact reconstruction"):
        validate_v2_training_inputs(replace(
            value, realizations=tuple(reversed(value.realizations))))
