"""Runnable V2 cohort mechanics, control, and checkpoint-chain tests."""

from __future__ import annotations

import random
from dataclasses import replace
from types import SimpleNamespace

import pytest
import torch

import shengji.rl.belief_v2_cohort_training as STAGE
import shengji.rl.belief_v2_epoch_journal as JOURNAL
import shengji.rl.belief_v2_streaming_inputs as STREAM_INPUTS
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
    train_v2_cohort_streaming,
    validate_trained_v2_cohort,
    validate_trained_v2_cohort_rows,
)
from shengji.rl.belief_v2_deadline import (
    BeliefV2DeadlineError,
    V2DeadlineRefusalV1,
)
from shengji.rl.belief_v2_epoch_journal import (
    BeliefV2EpochJournalError,
    V2EpochJournalBindingV1,
    publish_epoch_resume_state,
    reopen_latest_epoch_resume,
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
    collate_v2_label_control_examples,
)
from shengji.rl.belief_v2_training_inputs import (
    BeliefV2TrainingInputError,
    V2TrainingInputPopulationV1,
    validate_v2_training_inputs,
)
from shengji.rl.belief_v2_streaming_training import (
    BeliefV2StreamingTrainingError,
    V2StreamingCalibrationBatchReaderV1,
    V2StreamingSourceV1,
    V2StreamingTrainingBatchReaderV1,
    V2StreamingTrainingIndexV1,
    iter_streaming_calibration_batches,
    iter_streaming_training_batches,
    resident_array_bytes,
)
from shengji.rl.belief_v2_streaming_inputs import (
    BeliefV2StreamingInputError,
    build_streaming_training_inputs,
    reopen_streaming_training_inputs_bytes,
    streaming_training_inputs_bytes,
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


def _streaming_fixture():
    synthetic, human, realized, calibration, schedule = _fixture()
    all_examples = (*synthetic, *human, *calibration)
    by_group = {}
    for example in all_examples:
        by_group.setdefault(example.round_group_key, []).append(example)
    control_dose = sum(collate_v2_label_control_examples(
        tuple(rows))[1] for rows in by_group.values()
                       if rows[0].split == "train"
                       and rows[0].source_kind == "synthetic")
    index = V2StreamingTrainingIndexV1(
        train_rows=tuple(training_row(row) for row in (*synthetic, *human)),
        calibration_rows=tuple(STAGE.calibration_row(row)
                               for row in calibration),
        sources=tuple(V2StreamingSourceV1(
            round_group_key=group, split=rows[0].split,
            source_kind=rows[0].source_kind, source_token=f"source-{index}")
                      for index, (group, rows) in enumerate(
                          sorted(by_group.items()))),
        control_changed_cell_count=control_dose)
    return index, realized, schedule, {
        group: tuple(rows) for group, rows in by_group.items()}


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


def test_completed_epoch_journal_resumes_to_byte_identical_trajectory(
        tmp_path, monkeypatch):
    synthetic, human, realized, calibration, schedule = _fixture()
    value = next(row for row in realized
                 if row.kind == "synthetic-primary")
    by_key = {row.decision_key: row for row in (*synthetic, *human)}
    examples = tuple(by_key[row.decision_key] for row in value.rows)
    monkeypatch.setattr(STAGE, "TRAIN_MAX_EPOCHS", 2)
    binding = V2EpochJournalBindingV1(
        freeze_sha256="a" * 64, admission_sha256="b" * 64,
        cohort_id=value.cohort_id, realization_sha256=value.sha256(),
        common_calibration_sha256=schedule.sha256(),
        selected_device="cpu", torch_num_threads=torch.get_num_threads(),
        journal_byte_cap=1_000_000_000)
    journal = tmp_path / "journal"

    class SimulatedProcessLoss(RuntimeError):
        pass

    def first_checkpoint(state):
        publish_epoch_resume_state(
            journal, binding, state,
            stage_started_monotonic_nanoseconds=100,
            observed_monotonic_nanoseconds=200,
            cumulative_cpu_nanoseconds=80, exact_resume_count=0)
        raise SimulatedProcessLoss

    with pytest.raises(SimulatedProcessLoss):
        train_v2_cohort_in_memory(
            value, examples, schedule, calibration, device="cpu",
            epoch_checkpoint=first_checkpoint)
    with monkeypatch.context() as patch:
        def refuse_tensor_load(_raw):
            raise AssertionError(
                "manifest-only reopen must not deserialize tensor state")

        patch.setattr(JOURNAL, "_load_state_payload", refuse_tensor_load)
        manifest_rows = JOURNAL.reopen_epoch_manifests(journal, binding)
    assert len(manifest_rows) == 1
    assert manifest_rows[0].curves[0].epoch == 1

    state_path = journal / "epoch-0001" / JOURNAL.STATE_FILENAME
    state_raw = state_path.read_bytes()
    state_path.chmod(0o600)
    state_path.write_bytes(state_raw[:-1] + bytes([state_raw[-1] ^ 1]))
    state_path.chmod(0o400)
    with pytest.raises(BeliefV2EpochJournalError,
                       match="manifest chain drift"):
        JOURNAL.reopen_epoch_manifests(journal, binding)
    state_path.chmod(0o600)
    state_path.write_bytes(state_raw)
    state_path.chmod(0o400)

    reopened = reopen_latest_epoch_resume(journal, binding)
    assert reopened is not None
    resume_state, head = reopened
    assert len(resume_state.epochs) == 1
    assert head["exact_resume_count"] == 0

    def resumed_checkpoint(state):
        publish_epoch_resume_state(
            journal, binding, state,
            stage_started_monotonic_nanoseconds=100,
            observed_monotonic_nanoseconds=300,
            cumulative_cpu_nanoseconds=160, exact_resume_count=1)

    resumed = train_v2_cohort_in_memory(
        value, examples, schedule, calibration, device="cpu",
        resume_state=resume_state, epoch_checkpoint=resumed_checkpoint)
    uninterrupted = train_v2_cohort_in_memory(
        value, examples, schedule, calibration, device="cpu")
    assert resumed == uninterrupted
    reopened = reopen_latest_epoch_resume(journal, binding)
    assert reopened is not None
    assert len(reopened[0].epochs) == 2
    assert reopened[1]["exact_resume_count"] == 1

    abandoned = journal / "epoch-0003.partial"
    abandoned.mkdir()
    (abandoned / "never-read").write_bytes(b"partial")
    with pytest.raises(BeliefV2EpochJournalError,
                       match="partial publication"):
        reopen_latest_epoch_resume(journal, binding)
    assert (abandoned / "never-read").read_bytes() == b"partial"


def test_interrupted_epoch_publication_replays_only_exact_next_epoch(
        tmp_path, monkeypatch):
    synthetic, human, realized, calibration, schedule = _fixture()
    value = next(row for row in realized
                 if row.kind == "synthetic-primary")
    by_key = {row.decision_key: row for row in (*synthetic, *human)}
    examples = tuple(by_key[row.decision_key] for row in value.rows)
    monkeypatch.setattr(STAGE, "TRAIN_MAX_EPOCHS", 2)
    binding = V2EpochJournalBindingV1(
        freeze_sha256="a" * 64, admission_sha256="b" * 64,
        cohort_id=value.cohort_id, realization_sha256=value.sha256(),
        common_calibration_sha256=schedule.sha256(),
        selected_device="cpu", torch_num_threads=torch.get_num_threads(),
        journal_byte_cap=1_000_000_000)
    journal = tmp_path / "journal"

    class SimulatedPublicationLoss(RuntimeError):
        pass

    real_publish = JOURNAL.publish_exclusive_bytes
    tripped = False

    def flaky_publish(path, raw):
        nonlocal tripped
        if path.name == JOURNAL.CURVES_FILENAME \
                and path.parent.name == "epoch-0002.partial" \
                and not tripped:
            tripped = True
            fragment = path.with_name(path.name + ".partial")
            fragment.write_bytes(raw[:len(raw) // 2])
            raise SimulatedPublicationLoss
        return real_publish(path, raw)

    monkeypatch.setattr(JOURNAL, "publish_exclusive_bytes", flaky_publish)

    def checkpoint(state):
        publish_epoch_resume_state(
            journal, binding, state,
            stage_started_monotonic_nanoseconds=100,
            observed_monotonic_nanoseconds=200 + len(state.epochs),
            cumulative_cpu_nanoseconds=80 * len(state.epochs),
            exact_resume_count=0)

    with pytest.raises(SimulatedPublicationLoss):
        train_v2_cohort_in_memory(
            value, examples, schedule, calibration, device="cpu",
            epoch_checkpoint=checkpoint)
    assert tripped is True
    assert (journal / "epoch-0002.partial" / "curves.json.partial").is_file()
    reopened = reopen_latest_epoch_resume(journal, binding)
    assert reopened is not None
    resume_state, _ = reopened
    assert len(resume_state.epochs) == 1

    monkeypatch.setattr(JOURNAL, "publish_exclusive_bytes", real_publish)

    def resumed_checkpoint(state):
        publish_epoch_resume_state(
            journal, binding, state,
            stage_started_monotonic_nanoseconds=100,
            observed_monotonic_nanoseconds=300,
            cumulative_cpu_nanoseconds=160, exact_resume_count=1)

    resumed = train_v2_cohort_in_memory(
        value, examples, schedule, calibration, device="cpu",
        resume_state=resume_state, epoch_checkpoint=resumed_checkpoint)
    uninterrupted = train_v2_cohort_in_memory(
        value, examples, schedule, calibration, device="cpu")
    assert resumed == uninterrupted
    assert not (journal / "epoch-0002.partial").exists()
    assert len(reopen_latest_epoch_resume(journal, binding)[0].epochs) == 2


def test_patience_epoch_crash_reopens_and_seals_without_more_training(
        tmp_path, monkeypatch):
    synthetic, human, realized, calibration, schedule = _fixture()
    value = next(row for row in realized
                 if row.kind == "synthetic-primary")
    by_key = {row.decision_key: row for row in (*synthetic, *human)}
    examples = tuple(by_key[row.decision_key] for row in value.rows)
    monkeypatch.setattr(STAGE, "TRAIN_MAX_EPOCHS", 6)
    monkeypatch.setattr(
        STAGE, "evaluate_v2_calibration_cohort_stream_nanonats",
        lambda models, batches, device: (1_000_000,) * len(models))
    binding = V2EpochJournalBindingV1(
        freeze_sha256="a" * 64, admission_sha256="b" * 64,
        cohort_id=value.cohort_id, realization_sha256=value.sha256(),
        common_calibration_sha256=schedule.sha256(),
        selected_device="cpu", torch_num_threads=torch.get_num_threads(),
        journal_byte_cap=1_000_000_000)
    journal = tmp_path / "journal"

    class SimulatedProcessLoss(RuntimeError):
        pass

    def checkpoint_then_crash(state):
        epoch = len(state.epochs)
        publish_epoch_resume_state(
            journal, binding, state,
            stage_started_monotonic_nanoseconds=100,
            observed_monotonic_nanoseconds=200 + epoch,
            cumulative_cpu_nanoseconds=80 * epoch, exact_resume_count=0)
        if epoch == 4:
            raise SimulatedProcessLoss

    with pytest.raises(SimulatedProcessLoss):
        train_v2_cohort_in_memory(
            value, examples, schedule, calibration, device="cpu",
            epoch_checkpoint=checkpoint_then_crash)
    reopened = reopen_latest_epoch_resume(journal, binding)
    assert reopened is not None
    resume_state, manifest = reopened
    assert len(resume_state.epochs) == 4
    assert manifest["selected_common_epoch"] == 1

    def no_more_training_batches():
        raise AssertionError("a patience-complete journal must not train again")

    progress = []
    resumed = STAGE.train_v2_cohort_from_batch_factories(
        value, schedule, device="cpu",
        training_batches=no_more_training_batches,
        calibration_batches=no_more_training_batches,
        control_dose=0, resume_state=resume_state,
        progress=lambda *row: progress.append(row))
    uninterrupted = train_v2_cohort_in_memory(
        value, examples, schedule, calibration, device="cpu")
    assert resumed == uninterrupted
    assert resumed.stopped_for_patience is True
    assert resumed.truncated_by_deadline is False
    assert progress == [
        (4, 6, "training-epochs"),
        (8, 12, "training-batches"),
        (1, 1, "training-worker-complete"),
    ]


def test_deadline_after_completed_epoch_seals_explicit_truncation(
        monkeypatch):
    synthetic, human, realized, calibration, schedule = _fixture()
    value = next(row for row in realized
                 if row.kind == "synthetic-primary")
    by_key = {row.decision_key: row for row in (*synthetic, *human)}
    examples = tuple(by_key[row.decision_key] for row in value.rows)
    monkeypatch.setattr(STAGE, "TRAIN_MAX_EPOCHS", 3)
    checkpoints = []

    def deadline(phase, next_unit_index):
        if phase == "after-unit":
            raise BeliefV2DeadlineError(V2DeadlineRefusalV1(
                freeze_sha256="a" * 64, admission_sha256="b" * 64,
                stage="training", slot=value.cohort_id,
                phase=phase, next_unit_index=next_unit_index,
                started_monotonic_nanoseconds=1,
                observed_monotonic_nanoseconds=10,
                hard_deadline_monotonic_nanoseconds=11,
                wall_cap_nanoseconds=10,
                next_unit_wall_estimate_nanoseconds=6,
                safety_reserve_nanoseconds=3,
                required_remaining_nanoseconds=3,
                observed_remaining_nanoseconds=1))

    result = train_v2_cohort_in_memory(
        value, examples, schedule, calibration, device="cpu",
        deadline_check=deadline,
        epoch_checkpoint=lambda state: checkpoints.append(state))
    assert len(checkpoints) == 1
    assert len(result.epochs) == 1
    assert result.truncated_by_deadline is True
    assert result.stopped_for_patience is False
    assert result.to_dict()["truncated_by_deadline"] is True
    validate_trained_v2_cohort(
        value, examples, schedule, calibration, result)

    with pytest.raises(BeliefV2DeadlineError):
        train_v2_cohort_in_memory(
            value, examples, schedule, calibration, device="cpu",
            deadline_check=lambda phase, index: deadline(
                "after-unit", index))


def test_deadline_wins_if_patience_and_expiry_share_the_same_epoch(
        monkeypatch):
    synthetic, human, realized, calibration, schedule = _fixture()
    value = next(row for row in realized
                 if row.kind == "synthetic-primary")
    by_key = {row.decision_key: row for row in (*synthetic, *human)}
    examples = tuple(by_key[row.decision_key] for row in value.rows)
    monkeypatch.setattr(STAGE, "TRAIN_MAX_EPOCHS", 6)
    monkeypatch.setattr(
        STAGE, "evaluate_v2_calibration_cohort_stream_nanonats",
        lambda models, batches, device: (1_000_000,) * len(models))

    def deadline(phase, next_unit_index):
        if phase == "after-unit" and next_unit_index == 4:
            raise BeliefV2DeadlineError(V2DeadlineRefusalV1(
                freeze_sha256="a" * 64, admission_sha256="b" * 64,
                stage="training", slot=value.cohort_id,
                phase=phase, next_unit_index=next_unit_index,
                started_monotonic_nanoseconds=1,
                observed_monotonic_nanoseconds=10,
                hard_deadline_monotonic_nanoseconds=11,
                wall_cap_nanoseconds=10,
                next_unit_wall_estimate_nanoseconds=6,
                safety_reserve_nanoseconds=3,
                required_remaining_nanoseconds=3,
                observed_remaining_nanoseconds=1))

    result = train_v2_cohort_in_memory(
        value, examples, schedule, calibration, device="cpu",
        deadline_check=deadline)
    assert len(result.epochs) == 4
    assert result.truncated_by_deadline is True
    assert result.stopped_for_patience is False
    validate_trained_v2_cohort(
        value, examples, schedule, calibration, result)


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


def test_streaming_batches_equal_materialized_batches_without_resident_arrays():
    index, realized, schedule, by_group = _streaming_fixture()
    assert resident_array_bytes(index) == 0
    for value in realized:
        source_examples = {
            row.decision_key for row in value.rows}
        materialized = tuple(row for rows in by_group.values() for row in rows
                             if row.decision_key in source_examples)
        expected, _ = STAGE._training_batches(value, materialized)
        actual = tuple(iter_streaming_training_batches(
            index, value,
            load_round=lambda source: by_group[source.round_group_key]))
        assert len(actual) == len(expected)
        for left, right in zip(actual, expected, strict=True):
            assert left.decision_keys == right.decision_keys
            assert left.schema == right.schema
            assert left.control_kind == right.control_kind
            assert torch.equal(left.events, right.events)
            assert torch.equal(left.count_labels, right.count_labels)
            assert torch.equal(left.active_mask, right.active_mask)
    expected_calibration = STAGE._calibration_batches(
        schedule, tuple(row for rows in by_group.values() for row in rows
                        if row.split == "calibration"))
    actual_calibration = tuple(iter_streaming_calibration_batches(
        index, schedule,
        load_round=lambda source: by_group[source.round_group_key]))
    assert len(actual_calibration) == len(expected_calibration)
    assert all(torch.equal(left.events, right.events)
               and torch.equal(left.count_labels, right.count_labels)
               for left, right in zip(
                   actual_calibration, expected_calibration, strict=True))


def test_streaming_batch_readers_are_random_access_and_iterator_identical():
    index, realized, schedule, by_group = _streaming_fixture()
    primary = next(row for row in realized
                   if row.kind == "synthetic-primary")
    load = lambda source: by_group[source.round_group_key]  # noqa: E731
    train_reader = V2StreamingTrainingBatchReaderV1(
        index, primary, load_round=load)
    train_expected = tuple(iter_streaming_training_batches(
        index, primary, load_round=load))
    train_actual = tuple(train_reader.batch(index)[0]
                         for index in reversed(
                             range(train_reader.batch_count)))
    assert all(left.decision_keys == right.decision_keys
               and torch.equal(left.events, right.events)
               and torch.equal(left.count_labels, right.count_labels)
               for left, right in zip(
                   train_actual, reversed(train_expected), strict=True))

    calibration_reader = V2StreamingCalibrationBatchReaderV1(
        index, schedule, load_round=load)
    calibration_expected = tuple(iter_streaming_calibration_batches(
        index, schedule, load_round=load))
    calibration_actual = tuple(calibration_reader.batch(index)
                               for index in reversed(
                                   range(calibration_reader.batch_count)))
    assert all(left.decision_keys == right.decision_keys
               and torch.equal(left.events, right.events)
               and torch.equal(left.count_labels, right.count_labels)
               for left, right in zip(
                   calibration_actual, reversed(calibration_expected),
                   strict=True))
    with pytest.raises(BeliefV2StreamingTrainingError,
                       match="train batch index drift"):
        train_reader.batch(train_reader.batch_count)
    with pytest.raises(BeliefV2StreamingTrainingError,
                       match="calibration batch index drift"):
        calibration_reader.batch(-1)


def test_compact_input_artifact_round_trip_binds_every_row_without_arrays(
        monkeypatch):
    index, _, _, _ = _streaming_fixture()
    freeze = SimpleNamespace(cohorts=_plans(), sha256=lambda: "f" * 64)
    monkeypatch.setattr(
        STREAM_INPUTS, "validate_execution_freeze", lambda value: None)
    value = build_streaming_training_inputs(
        freeze, train_rows=index.train_rows,
        calibration_rows=index.calibration_rows, sources=index.sources,
        control_changed_cell_count=index.control_changed_cell_count,
        human_group_manifest_sha256s=("a" * 64,))
    raw = streaming_training_inputs_bytes(value, freeze)
    reopened = reopen_streaming_training_inputs_bytes(raw, freeze=freeze)
    assert reopened == value
    assert reopened.manifest()["resident_model_array_bytes"] == 0
    assert resident_array_bytes(reopened) == 0
    corrupted = raw.replace(
        index.train_rows[0].decision_key.encode("ascii"), b"0" * 64, 1)
    with pytest.raises(BeliefV2StreamingInputError):
        reopen_streaming_training_inputs_bytes(corrupted, freeze=freeze)


def test_streaming_batch_reopens_only_named_groups_and_binds_compact_rows():
    index, realized, _, by_group = _streaming_fixture()
    primary = next(row for row in realized
                   if row.kind == "synthetic-primary")
    calls = []

    def load(source):
        calls.append(source.round_group_key)
        return by_group[source.round_group_key]

    batches = tuple(iter_streaming_training_batches(
        index, primary, load_round=load))
    expected_groups = {
        row.round_group_key for row in primary.rows}
    assert set(calls) == expected_groups
    assert len(calls) == len(set(calls))
    assert sum(len(batch.decision_keys) for batch in batches) \
        == len(primary.rows)

    victim = index.train_rows[0].decision_key

    def changed_load(source):
        return tuple(replace(
            example, privileged_target_sha256="f" * 64)
                     if example.decision_key == victim else example
                     for example in by_group[source.round_group_key])

    with pytest.raises(BeliefV2StreamingTrainingError,
                       match="example/row binding"):
        tuple(iter_streaming_training_batches(
            index, primary, load_round=changed_load))


@pytest.mark.parametrize("kind", (
    "synthetic-primary", "hard-geometry-label-permutation",
    "human-mixture", "synthetic-scale"))
def test_streaming_training_is_checkpoint_identical_to_materialized(
        monkeypatch, kind):
    index, realized, schedule, by_group = _streaming_fixture()
    value = next(row for row in realized if row.kind == kind)
    source_examples = {
        row.decision_key for row in value.rows}
    examples = tuple(row for rows in by_group.values() for row in rows
                     if row.decision_key in source_examples)
    calibration = tuple(row for rows in by_group.values() for row in rows
                        if row.split == "calibration")
    monkeypatch.setattr(STAGE, "TRAIN_MAX_EPOCHS", 1)
    expected = train_v2_cohort_in_memory(
        value, examples, schedule, calibration, device="cpu")
    actual = train_v2_cohort_streaming(
        value, schedule, index=index,
        load_round=lambda source: by_group[source.round_group_key],
        device="cpu")
    assert actual == expected
    validate_trained_v2_cohort_rows(
        value, schedule,
        control_dose=(index.control_changed_cell_count
                      if kind == "hard-geometry-label-permutation" else 0),
        candidate=actual)
