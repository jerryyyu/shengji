"""In-memory, source-neutral cohort training mechanics for BELIEF-V1 V2.

The caller supplies already-reopened train and synthetic-calibration examples
plus their independently derived schedules.  This module trains all eight
fixed members on one reviewed device, applies one common epoch rule, exports
portable CPU checkpoints, and reopens every receipt and checkpoint.  It has no
filesystem, corpus reader, test opener, clock, process launcher, or execution
authority.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Callable

import torch

from .belief_artifacts import (
    checkpoint_bundle_bytes,
    reopen_epoch_receipt,
    reopen_checkpoint_bundle,
)
from .belief_b2_protocol import TRAIN_MAX_EPOCHS
from .belief_checkpoint import (
    build_model_checkpoint,
    reopen_model_checkpoint,
)
from .belief_cohort import COHORT_SEEDS
from .belief_contract import canonical_json_bytes
from .belief_v2_deadline import BeliefV2DeadlineError
from .belief_model import new_from_scratch_model
from .belief_trainer import EpochTrainingReceiptV1, _epoch_input_digests
from .belief_training import (
    CONTROL_TRAINING_BATCH_SCHEMA,
    EXACT_TARGET_LABELS,
    GEOMETRY_PERMUTED_LABELS,
    LABEL_PERMUTATION_CONTROL,
    NATURAL_HISTORY,
    TRAINING_BATCH_SCHEMA,
)
from .belief_training_schedule import select_common_epoch
from .belief_v2_accelerator import (
    canonical_training_device,
    cpu_checkpoint_clone,
    evaluate_v2_calibration_cohort_stream_nanonats,
    move_models_to_device,
    new_v2_optimizer,
    portable_model_state_sha256,
    train_v2_cohort_epoch_stream,
)
from .belief_v2_schedule import (
    V2CalibrationScheduleV1,
    V2CohortRealizationV1,
    calibration_row,
    training_row,
    validate_v2_common_calibration,
)
from .belief_v2_progress import ProgressCallback
from .belief_v2_training import (
    V2TrainingExampleV1,
    collate_v2_label_control_examples,
    collate_v2_training_examples,
)


EPOCH_SCHEMA = "belief-v1-v2-training-epoch-curve-row-v1"
TRAINED_COHORT_SCHEMA = "belief-v1-v2-trained-cohort-artifacts-v1"
CONTROL_KIND = "hard-geometry-label-permutation"


class BeliefV2CohortTrainingError(ValueError):
    """A V2 training input, epoch chain, selection, or checkpoint drifted."""


@dataclass(frozen=True)
class V2CohortResumeStateV1:
    """Exact live state at one completed epoch.

    The durable controller owns serialization.  Keeping this source-neutral
    object here lets the trainer prove that a resumed trajectory is the same
    trajectory: current models bind the last receipts, selected models bind
    the reconstructed common epoch, and optimizer state stays paired with the
    current models.  It carries no execution or test-opening authority.
    """

    models: tuple[Any, ...]
    optimizers: tuple[Any, ...]
    epochs: tuple["V2TrainingEpochCurveRowV1", ...]
    selected_states: tuple[dict[str, torch.Tensor], ...]
    selected_receipts: tuple[EpochTrainingReceiptV1, ...]


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class V2TrainingEpochCurveRowV1:
    epoch: int
    member_training_receipts: tuple[EpochTrainingReceiptV1, ...]
    member_calibration_loss_nanonats: tuple[int, ...]
    cohort_mean_calibration_loss_nanonats: int
    schema: str = EPOCH_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "epoch": self.epoch,
            "member_training_receipts": [
                receipt.to_dict()
                for receipt in self.member_training_receipts],
            "member_calibration_loss_nanonats": list(
                self.member_calibration_loss_nanonats),
            "cohort_mean_calibration_loss_nanonats": (
                self.cohort_mean_calibration_loss_nanonats),
        }


@dataclass(frozen=True)
class V2TrainedCohortArtifactsV1:
    cohort_id: str
    cohort_kind: str
    realization_sha256: str
    common_calibration_sha256: str
    training_device: str
    epochs: tuple[V2TrainingEpochCurveRowV1, ...]
    selected_common_epoch: int
    stop_epoch: int
    stopped_for_patience: bool
    truncated_by_deadline: bool
    label_control_changed_cell_count_per_epoch: int
    checkpoint_bundles: tuple[bytes, ...]
    schema: str = TRAINED_COHORT_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "cohort_id": self.cohort_id,
            "cohort_kind": self.cohort_kind,
            "realization_sha256": self.realization_sha256,
            "common_calibration_sha256": self.common_calibration_sha256,
            "training_device": self.training_device,
            "initialization_seeds": list(COHORT_SEEDS),
            "epochs": [row.to_dict() for row in self.epochs],
            "epoch_count": len(self.epochs),
            "selected_common_epoch": self.selected_common_epoch,
            "stop_epoch": self.stop_epoch,
            "stopped_for_patience": self.stopped_for_patience,
            "truncated_by_deadline": self.truncated_by_deadline,
            "label_control_changed_cell_count_per_epoch": (
                self.label_control_changed_cell_count_per_epoch),
            "checkpoints": [{
                "member_index": index,
                "initialization_seed": COHORT_SEEDS[index],
                "byte_count": len(raw),
                "bundle_sha256": _sha256(raw),
            } for index, raw in enumerate(self.checkpoint_bundles)],
            "common_epoch_calibration_source": "balanced-synthetic-only",
            "human_calibration_consumed_for_common_epoch": False,
            "contains_optimizer_resume_state": False,
            "contains_corpus_rows": False,
            "test_split_opened": False,
            "test_split_open_authorized": False,
            "sampler_implementation_authorized": False,
            "gameplay_strength_screen_authorized": False,
            "strength_claim_authorized": False,
            "deployment_authorized": False,
        }

    def manifest_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())


def _example_map(
        examples: tuple[V2TrainingExampleV1, ...], *, split: str) \
        -> dict[str, V2TrainingExampleV1]:
    if type(examples) is not tuple or not examples \
            or any(type(example) is not V2TrainingExampleV1
                   or example.split != split for example in examples):
        raise BeliefV2CohortTrainingError(
            f"V2 {split} example population drift")
    result = {example.decision_key: example for example in examples}
    if len(result) != len(examples):
        raise BeliefV2CohortTrainingError(
            f"V2 {split} example duplicate")
    return result


def _training_batches(
        realization: V2CohortRealizationV1,
        examples: tuple[V2TrainingExampleV1, ...]) \
        -> tuple[tuple[Any, ...], int]:
    try:
        realization.canonical_bytes()
    except ValueError as exc:
        raise BeliefV2CohortTrainingError(
            "V2 training realization refused") from exc
    by_key = _example_map(examples, split="train")
    if set(by_key) != {row.decision_key for row in realization.rows}:
        raise BeliefV2CohortTrainingError(
            "V2 training example population differs from realization")
    for row in realization.rows:
        try:
            expected = training_row(by_key[row.decision_key])
        except ValueError as exc:
            raise BeliefV2CohortTrainingError(
                "V2 training example binding refused") from exc
        if expected != row:
            raise BeliefV2CohortTrainingError(
                "V2 training example/realization binding drift")
    batches = []
    changed = 0
    for keys in realization.batches:
        selected = tuple(by_key[key] for key in keys)
        if realization.kind == CONTROL_KIND:
            batch, dose = collate_v2_label_control_examples(selected)
            changed += dose
        else:
            batch = collate_v2_training_examples(selected)
        batches.append(batch)
    if realization.kind == CONTROL_KIND and changed <= 0:
        raise BeliefV2CohortTrainingError(
            "V2 label control population has zero dose")
    if realization.kind != CONTROL_KIND and changed != 0:
        raise BeliefV2CohortTrainingError(
            "V2 natural cohort has label-control dose")
    return tuple(batches), changed


def _calibration_batches(
        schedule: V2CalibrationScheduleV1,
        examples: tuple[V2TrainingExampleV1, ...]) -> tuple[Any, ...]:
    try:
        validate_v2_common_calibration(examples, schedule)
    except ValueError as exc:
        raise BeliefV2CohortTrainingError(
            "V2 common calibration schedule refused") from exc
    by_key = _example_map(examples, split="calibration")
    if set(by_key) != {row.decision_key for row in schedule.rows}:
        raise BeliefV2CohortTrainingError(
            "V2 common calibration population drift")
    for row in schedule.rows:
        if calibration_row(by_key[row.decision_key]) != row:
            raise BeliefV2CohortTrainingError(
                "V2 common calibration example binding drift")
    return tuple(collate_v2_training_examples(tuple(by_key[key]
                                                    for key in keys))
                 for keys in schedule.batches)


def _cpu_state(model) -> dict[str, torch.Tensor]:
    return {name: value.detach().to(
        device="cpu", dtype=torch.float32, copy=True).contiguous()
            for name, value in model.state_dict().items()}


def _model_from_state(seed: int, state: dict[str, torch.Tensor]):
    if type(state) is not dict or not state:
        raise BeliefV2CohortTrainingError(
            "V2 resume model state population drift")
    model = new_from_scratch_model(seed)
    try:
        model.load_state_dict(state, strict=True)
    except (RuntimeError, ValueError) as exc:
        raise BeliefV2CohortTrainingError(
            "V2 resume model state refused") from exc
    return model


def _validate_resume_state(
        state: V2CohortResumeStateV1, *, device: str) -> None:
    if type(state) is not V2CohortResumeStateV1 \
            or device != "cpu" \
            or type(state.models) is not tuple \
            or len(state.models) != len(COHORT_SEEDS) \
            or type(state.optimizers) is not tuple \
            or len(state.optimizers) != len(COHORT_SEEDS) \
            or type(state.epochs) is not tuple or not state.epochs \
            or len(state.epochs) > TRAIN_MAX_EPOCHS \
            or type(state.selected_states) is not tuple \
            or len(state.selected_states) != len(COHORT_SEEDS) \
            or type(state.selected_receipts) is not tuple \
            or len(state.selected_receipts) != len(COHORT_SEEDS):
        raise BeliefV2CohortTrainingError(
            "V2 cohort resume state identity drift")
    losses: list[list[int]] = [[] for _ in COHORT_SEEDS]
    for epoch, row in enumerate(state.epochs, 1):
        if type(row) is not V2TrainingEpochCurveRowV1 \
                or row.epoch != epoch \
                or len(row.member_training_receipts) != len(COHORT_SEEDS) \
                or len(row.member_calibration_loss_nanonats) \
                != len(COHORT_SEEDS):
            raise BeliefV2CohortTrainingError(
                "V2 cohort resume curve drift")
        for values, value in zip(
                losses, row.member_calibration_loss_nanonats, strict=True):
            values.append(value)
    decision = select_common_epoch(tuple(tuple(row) for row in losses))
    if decision.stop_epoch != len(state.epochs) \
            or state.selected_receipts != state.epochs[
                decision.selected_epoch - 1].member_training_receipts:
        raise BeliefV2CohortTrainingError(
            "V2 cohort resume selection drift")
    latest = state.epochs[-1].member_training_receipts
    for index, (model, optimizer, receipt, selected_state,
                selected_receipt) in enumerate(zip(
                    state.models, state.optimizers, latest,
                    state.selected_states, state.selected_receipts,
                    strict=True)):
        try:
            current_hash = portable_model_state_sha256(model)
            selected_model = _model_from_state(
                COHORT_SEEDS[index], selected_state)
            selected_hash = portable_model_state_sha256(selected_model)
        except ValueError as exc:
            raise BeliefV2CohortTrainingError(
                "V2 cohort resume model identity refused") from exc
        if current_hash != receipt.model_state_sha256_after \
                or selected_hash != selected_receipt.model_state_sha256_after \
                or not isinstance(optimizer, torch.optim.Optimizer):
            raise BeliefV2CohortTrainingError(
                "V2 cohort resume model/receipt drift")


def train_v2_cohort_in_memory(
        realization: V2CohortRealizationV1,
        training_examples: tuple[V2TrainingExampleV1, ...],
        common_calibration: V2CalibrationScheduleV1,
        calibration_examples: tuple[V2TrainingExampleV1, ...], *,
        device: str,
        deadline_check: Callable[[str, int], None] | None = None,
        resume_state: V2CohortResumeStateV1 | None = None,
        epoch_checkpoint: Callable[[V2CohortResumeStateV1], None]
        | None = None,
        progress: ProgressCallback | None = None
        ) -> V2TrainedCohortArtifactsV1:
    """Train and independently reopen one realized cohort in memory."""
    training_batches, control_dose = _training_batches(
        realization, training_examples)
    calibration_batches = _calibration_batches(
        common_calibration, calibration_examples)
    result = _train_v2_cohort_from_factories(
        realization, common_calibration, device=device,
        training_batches=lambda: iter(training_batches),
        calibration_batches=lambda: iter(calibration_batches),
        control_dose=control_dose, deadline_check=deadline_check,
        resume_state=resume_state, epoch_checkpoint=epoch_checkpoint,
        progress=progress)
    validate_trained_v2_cohort(
        realization, training_examples, common_calibration,
        calibration_examples, result)
    return result


def _train_v2_cohort_from_factories(
        realization: V2CohortRealizationV1,
        common_calibration: V2CalibrationScheduleV1, *, device: str,
        training_batches: Callable[[], Any],
        calibration_batches: Callable[[], Any], control_dose: int,
        deadline_check: Callable[[str, int], None] | None = None,
        resume_state: V2CohortResumeStateV1 | None = None,
        epoch_checkpoint: Callable[[V2CohortResumeStateV1], None]
        | None = None,
        progress: ProgressCallback | None = None
        ) -> V2TrainedCohortArtifactsV1:
    """Train from fresh bounded iterators without retaining their population."""
    if type(control_dose) is not int or control_dose < 0 \
            or (realization.kind == CONTROL_KIND) != (control_dose > 0) \
            or not callable(training_batches) \
            or not callable(calibration_batches):
        raise BeliefV2CohortTrainingError(
            "V2 training batch factory identity drift")
    if epoch_checkpoint is not None and not callable(epoch_checkpoint):
        raise BeliefV2CohortTrainingError(
            "V2 epoch checkpoint callback drift")
    if resume_state is None:
        models = tuple(new_from_scratch_model(seed) for seed in COHORT_SEEDS)
        try:
            move_models_to_device(models, device=device)
            optimizers = tuple(new_v2_optimizer(model) for model in models)
        except ValueError as exc:
            raise BeliefV2CohortTrainingError(
                "V2 training device initialization refused") from exc
        losses: list[list[int]] = [[] for _ in COHORT_SEEDS]
        epoch_rows: list[V2TrainingEpochCurveRowV1] = []
        selected_states = None
        selected_receipts = None
    else:
        _validate_resume_state(resume_state, device=device)
        models = resume_state.models
        optimizers = resume_state.optimizers
        epoch_rows = list(resume_state.epochs)
        losses = [[row.member_calibration_loss_nanonats[index]
                   for row in epoch_rows]
                  for index in range(len(COHORT_SEEDS))]
        selected_states = resume_state.selected_states
        selected_receipts = resume_state.selected_receipts
    decision = None if not epoch_rows else select_common_epoch(tuple(
        tuple(row) for row in losses))
    truncated_by_deadline = False
    train_batch_count = len(realization.batches)
    calibration_batch_count = len(common_calibration.batches)
    batches_per_epoch = train_batch_count + calibration_batch_count
    total_batch_units = TRAIN_MAX_EPOCHS * batches_per_epoch
    if progress is not None:
        progress(len(epoch_rows), TRAIN_MAX_EPOCHS, "training-epochs")
        progress(len(epoch_rows) * batches_per_epoch, total_batch_units,
                 "training-batches")

    def progress_batches(
            batches, *, expected_count: int, offset: int):
        observed = 0
        for batch in batches:
            yield batch
            observed += 1
            if progress is not None:
                progress(offset + observed, total_batch_units,
                         "training-batches")
        if observed != expected_count:
            raise BeliefV2CohortTrainingError(
                "V2 training progress batch population drift")

    final_epoch = (len(epoch_rows) if decision is not None
                   and decision.stopped_for_patience
                   else TRAIN_MAX_EPOCHS)
    for epoch in range(len(epoch_rows) + 1, final_epoch + 1):
        if deadline_check is not None:
            try:
                deadline_check("before-unit", epoch - 1)
            except BeliefV2DeadlineError:
                if not epoch_rows:
                    raise
                truncated_by_deadline = True
                decision = select_common_epoch(tuple(
                    tuple(row) for row in losses))
                break
        try:
            epoch_offset = (epoch - 1) * batches_per_epoch
            receipts = train_v2_cohort_epoch_stream(
                models, optimizers, progress_batches(
                    training_batches(), expected_count=train_batch_count,
                    offset=epoch_offset),
                epoch=epoch, device=device)
            calibration = evaluate_v2_calibration_cohort_stream_nanonats(
                models, progress_batches(
                    calibration_batches(),
                    expected_count=calibration_batch_count,
                    offset=epoch_offset + train_batch_count),
                device=device)
            for row, value in zip(losses, calibration, strict=True):
                row.append(value)
            decision = select_common_epoch(tuple(
                tuple(row) for row in losses))
        except ValueError as exc:
            raise BeliefV2CohortTrainingError(
                "V2 cohort epoch or calibration refused") from exc
        epoch_rows.append(V2TrainingEpochCurveRowV1(
            epoch=epoch, member_training_receipts=receipts,
            member_calibration_loss_nanonats=calibration,
            cohort_mean_calibration_loss_nanonats=(
                sum(calibration) // len(calibration))))
        if decision.selected_epoch == epoch:
            selected_states = tuple(_cpu_state(model) for model in models)
            selected_receipts = receipts
        if selected_states is None or selected_receipts is None:
            raise BeliefV2CohortTrainingError(
                "V2 epoch checkpoint selection state drift")
        if epoch_checkpoint is not None:
            epoch_checkpoint(V2CohortResumeStateV1(
                models=models, optimizers=optimizers,
                epochs=tuple(epoch_rows),
                selected_states=selected_states,
                selected_receipts=selected_receipts))
        if deadline_check is not None:
            try:
                deadline_check("after-unit", epoch)
            except BeliefV2DeadlineError:
                truncated_by_deadline = True
        if progress is not None:
            progress(epoch, TRAIN_MAX_EPOCHS, "training-epochs")
        if truncated_by_deadline:
            break
        if decision.stopped_for_patience:
            break
    if progress is not None and len(epoch_rows) < TRAIN_MAX_EPOCHS:
        # Patience or the deadline completed the worker, not the unexecuted
        # epoch/batch populations.  Keep those curves at their honest
        # fractions and publish a separate one-unit completion phase.
        progress(1, 1, "training-worker-complete")
    if decision is None or selected_states is None \
            or selected_receipts is None \
            or decision.stop_epoch != len(epoch_rows):
        raise BeliefV2CohortTrainingError(
            "V2 common epoch selection state drift")
    bundles = []
    for seed, state, receipt in zip(
            COHORT_SEEDS, selected_states, selected_receipts, strict=True):
        model = new_from_scratch_model(seed)
        model.load_state_dict(state, strict=True)
        if portable_model_state_sha256(model) \
                != receipt.model_state_sha256_after:
            raise BeliefV2CohortTrainingError(
                "V2 selected checkpoint state/receipt drift")
        checkpoint = build_model_checkpoint(
            cpu_checkpoint_clone(model), initialization_seed=seed,
            selected_epoch=decision.selected_epoch,
            final_epoch_receipt=receipt)
        bundles.append(checkpoint_bundle_bytes(checkpoint, receipt))
    # This is the sole normal-path seal boundary.  Check only after the final
    # portable checkpoint bytes exist so a deadline cannot pass in the trainer
    # and then fail a second time in the controller.  Expiry after at least one
    # complete epoch is valid, explicitly truncated evidence; it never opens
    # calibration or test data downstream.
    if deadline_check is not None and not truncated_by_deadline:
        try:
            deadline_check("before-seal", len(epoch_rows))
        except BeliefV2DeadlineError:
            truncated_by_deadline = True
    result = V2TrainedCohortArtifactsV1(
        cohort_id=realization.cohort_id,
        cohort_kind=realization.kind,
        realization_sha256=realization.sha256(),
        common_calibration_sha256=common_calibration.sha256(),
        training_device=device, epochs=tuple(epoch_rows),
        selected_common_epoch=decision.selected_epoch,
        stop_epoch=decision.stop_epoch,
        # If the exact deadline and patience boundary coincide, deadline
        # truncation is the conservative terminal reason.  The common-epoch
        # arithmetic remains reproducible, but the artifact must not also
        # present itself as a patience-converged cohort.
        stopped_for_patience=(
            decision.stopped_for_patience and not truncated_by_deadline),
        truncated_by_deadline=truncated_by_deadline,
        label_control_changed_cell_count_per_epoch=control_dose,
        checkpoint_bundles=tuple(bundles))
    return result


def train_v2_cohort_streaming(
        realization: V2CohortRealizationV1,
        common_calibration: V2CalibrationScheduleV1, *,
        index, load_round, device: str,
        deadline_check: Callable[[str, int], None] | None = None,
        resume_state: V2CohortResumeStateV1 | None = None,
        epoch_checkpoint: Callable[[V2CohortResumeStateV1], None]
        | None = None,
        progress: ProgressCallback | None = None
        ) -> V2TrainedCohortArtifactsV1:
    """Train from one bounded, freshly reopened batch at a time."""
    from .belief_v2_streaming_training import (
        iter_streaming_calibration_batches,
        iter_streaming_training_batches,
        validate_streaming_training_index,
    )
    try:
        validate_streaming_training_index(index)
    except ValueError as exc:
        raise BeliefV2CohortTrainingError(
            "V2 streaming training index refused") from exc
    control_dose = (index.control_changed_cell_count
                    if realization.kind == CONTROL_KIND else 0)
    result = _train_v2_cohort_from_factories(
        realization, common_calibration, device=device,
        training_batches=lambda: iter_streaming_training_batches(
            index, realization, load_round=load_round),
        calibration_batches=lambda: iter_streaming_calibration_batches(
            index, common_calibration, load_round=load_round),
        control_dose=control_dose, deadline_check=deadline_check,
        resume_state=resume_state, epoch_checkpoint=epoch_checkpoint,
        progress=progress)
    validate_trained_v2_cohort_rows(
        realization, common_calibration, control_dose=control_dose,
        candidate=result)
    return result


def train_v2_cohort_from_batch_factories(
        realization: V2CohortRealizationV1,
        common_calibration: V2CalibrationScheduleV1, *, device: str,
        training_batches: Callable[[], Any],
        calibration_batches: Callable[[], Any], control_dose: int,
        deadline_check: Callable[[str, int], None] | None = None,
        resume_state: V2CohortResumeStateV1 | None = None,
        epoch_checkpoint: Callable[[V2CohortResumeStateV1], None]
        | None = None,
        progress: ProgressCallback | None = None
        ) -> V2TrainedCohortArtifactsV1:
    """Train from independently bound reusable batch factories.

    The filesystem/cache controller owns artifact authentication.  This seam
    retains all schedule, control-dose, checkpoint, and selection validation
    while avoiding a second corpus parser inside the trainer.
    """
    result = _train_v2_cohort_from_factories(
        realization, common_calibration, device=device,
        training_batches=training_batches,
        calibration_batches=calibration_batches,
        control_dose=control_dose, deadline_check=deadline_check,
        resume_state=resume_state, epoch_checkpoint=epoch_checkpoint,
        progress=progress)
    validate_trained_v2_cohort_rows(
        realization, common_calibration, control_dose=control_dose,
        candidate=result)
    return result


def validate_trained_v2_cohort(
        realization: V2CohortRealizationV1,
        training_examples: tuple[V2TrainingExampleV1, ...],
        common_calibration: V2CalibrationScheduleV1,
        calibration_examples: tuple[V2TrainingExampleV1, ...],
        candidate: V2TrainedCohortArtifactsV1) -> None:
    """Reopen schedules, every epoch chain, selection, and all checkpoints."""
    batches, control_dose = _training_batches(
        realization, training_examples)
    _calibration_batches(common_calibration, calibration_examples)
    if type(candidate) is not V2TrainedCohortArtifactsV1 \
            or candidate.schema != TRAINED_COHORT_SCHEMA \
            or candidate.cohort_id != realization.cohort_id \
            or candidate.cohort_kind != realization.kind \
            or candidate.realization_sha256 != realization.sha256() \
            or candidate.common_calibration_sha256 \
            != common_calibration.sha256() \
            or type(candidate.training_device) is not str \
            or type(candidate.epochs) is not tuple \
            or not 1 <= len(candidate.epochs) <= TRAIN_MAX_EPOCHS \
            or candidate.stop_epoch != len(candidate.epochs) \
            or type(candidate.truncated_by_deadline) is not bool \
            or (candidate.truncated_by_deadline
                and candidate.stopped_for_patience) \
            or candidate.label_control_changed_cell_count_per_epoch \
            != control_dose \
            or type(candidate.checkpoint_bundles) is not tuple \
            or len(candidate.checkpoint_bundles) != len(COHORT_SEEDS) \
            or any(type(raw) is not bytes or not raw
                   for raw in candidate.checkpoint_bundles):
        raise BeliefV2CohortTrainingError(
            "V2 trained cohort artifact identity drift")
    try:
        canonical_training_device(candidate.training_device)
    except ValueError as exc:
        raise BeliefV2CohortTrainingError(
            "V2 trained cohort device drift") from exc
    member_losses: list[list[int]] = [[] for _ in COHORT_SEEDS]
    receipts_by_epoch = []
    batch_keys = tuple(batch.decision_keys for batch in batches)
    for epoch, row in enumerate(candidate.epochs, 1):
        if type(row) is not V2TrainingEpochCurveRowV1 \
                or row.schema != EPOCH_SCHEMA or row.epoch != epoch \
                or type(row.member_training_receipts) is not tuple \
                or len(row.member_training_receipts) != len(COHORT_SEEDS) \
                or type(row.member_calibration_loss_nanonats) is not tuple \
                or len(row.member_calibration_loss_nanonats) \
                != len(COHORT_SEEDS) \
                or any(type(value) is not int or value < 0
                       for value in row.member_calibration_loss_nanonats) \
                or row.cohort_mean_calibration_loss_nanonats \
                != sum(row.member_calibration_loss_nanonats) \
                // len(COHORT_SEEDS):
            raise BeliefV2CohortTrainingError(
                "V2 training epoch curve drift")
        population_sha, schedule_sha = _epoch_input_digests(
            batch_keys, epoch=epoch)
        for receipt in row.member_training_receipts:
            if type(receipt) is not EpochTrainingReceiptV1 \
                    or receipt.epoch != epoch \
                    or receipt.batch_count != len(batches) \
                    or receipt.decision_count \
                    != sum(len(batch.decision_keys) for batch in batches) \
                    or receipt.active_label_count \
                    != sum(int(batch.active_mask.sum().item())
                           for batch in batches) \
                    or receipt.batch_schema != batches[0].schema \
                    or receipt.history_transform \
                    != batches[0].history_transform \
                    or receipt.label_transform != batches[0].label_transform \
                    or receipt.control_kind != batches[0].control_kind \
                    or receipt.decision_population_sha256 != population_sha \
                    or receipt.batch_schedule_sha256 != schedule_sha:
                raise BeliefV2CohortTrainingError(
                    "V2 training epoch receipt binding drift")
        receipts_by_epoch.append(row.member_training_receipts)
        for values, value in zip(
                member_losses, row.member_calibration_loss_nanonats,
                strict=True):
            values.append(value)
    for member_index, seed in enumerate(COHORT_SEEDS):
        initial = portable_model_state_sha256(new_from_scratch_model(seed))
        if receipts_by_epoch[0][member_index].model_state_sha256_before \
                != initial \
                or any(left[member_index].model_state_sha256_after
                       != right[member_index].model_state_sha256_before
                       for left, right in zip(
                           receipts_by_epoch, receipts_by_epoch[1:])):
            raise BeliefV2CohortTrainingError(
                "V2 training cross-epoch receipt chain drift")
    decision = select_common_epoch(tuple(tuple(row) for row in member_losses))
    expected_patience = (decision.stopped_for_patience
                         and not candidate.truncated_by_deadline)
    if candidate.selected_common_epoch != decision.selected_epoch \
            or candidate.stop_epoch != decision.stop_epoch \
            or candidate.stopped_for_patience is not expected_patience:
        raise BeliefV2CohortTrainingError(
            "V2 common epoch reconstruction drift")
    selected = receipts_by_epoch[decision.selected_epoch - 1]
    checkpoint_hashes = set()
    for index, (raw, expected_receipt) in enumerate(zip(
            candidate.checkpoint_bundles, selected, strict=True)):
        try:
            checkpoint, receipt = reopen_checkpoint_bundle(raw)
            model = reopen_model_checkpoint(
                checkpoint, final_epoch_receipt=receipt)
        except ValueError as exc:
            raise BeliefV2CohortTrainingError(
                "V2 selected checkpoint reopen refused") from exc
        if receipt != expected_receipt \
                or portable_model_state_sha256(model) \
                != expected_receipt.model_state_sha256_after:
            raise BeliefV2CohortTrainingError(
                "V2 selected checkpoint receipt drift")
        checkpoint_hashes.add(_sha256(raw))
    if len(checkpoint_hashes) != len(COHORT_SEEDS):
        raise BeliefV2CohortTrainingError(
            "V2 selected checkpoint population collision")


def validate_trained_v2_cohort_rows(
        realization: V2CohortRealizationV1,
        common_calibration: V2CalibrationScheduleV1, *,
        control_dose: int,
        candidate: V2TrainedCohortArtifactsV1) -> None:
    """Reopen one trained cohort from compact rows without model arrays."""
    try:
        realization.canonical_bytes()
        common_calibration.canonical_bytes()
    except ValueError as exc:
        raise BeliefV2CohortTrainingError(
            "V2 compact training schedule refused") from exc
    is_control = realization.kind == CONTROL_KIND
    if type(control_dose) is not int or control_dose < 0 \
            or is_control != (control_dose > 0):
        raise BeliefV2CohortTrainingError(
            "V2 compact label-control dose drift")
    expected_schema = (CONTROL_TRAINING_BATCH_SCHEMA
                       if is_control else TRAINING_BATCH_SCHEMA)
    expected_label = (GEOMETRY_PERMUTED_LABELS
                      if is_control else EXACT_TARGET_LABELS)
    expected_control = (LABEL_PERMUTATION_CONTROL
                        if is_control else "candidate")
    if type(candidate) is not V2TrainedCohortArtifactsV1 \
            or candidate.schema != TRAINED_COHORT_SCHEMA \
            or candidate.cohort_id != realization.cohort_id \
            or candidate.cohort_kind != realization.kind \
            or candidate.realization_sha256 != realization.sha256() \
            or candidate.common_calibration_sha256 \
            != common_calibration.sha256() \
            or type(candidate.training_device) is not str \
            or type(candidate.epochs) is not tuple \
            or not 1 <= len(candidate.epochs) <= TRAIN_MAX_EPOCHS \
            or candidate.stop_epoch != len(candidate.epochs) \
            or type(candidate.truncated_by_deadline) is not bool \
            or (candidate.truncated_by_deadline
                and candidate.stopped_for_patience) \
            or candidate.label_control_changed_cell_count_per_epoch \
            != control_dose \
            or type(candidate.checkpoint_bundles) is not tuple \
            or len(candidate.checkpoint_bundles) != len(COHORT_SEEDS) \
            or any(type(raw) is not bytes or not raw
                   for raw in candidate.checkpoint_bundles):
        raise BeliefV2CohortTrainingError(
            "V2 trained cohort artifact identity drift")
    try:
        canonical_training_device(candidate.training_device)
    except ValueError as exc:
        raise BeliefV2CohortTrainingError(
            "V2 trained cohort device drift") from exc
    member_losses: list[list[int]] = [[] for _ in COHORT_SEEDS]
    receipts_by_epoch = []
    for epoch, curve in enumerate(candidate.epochs, 1):
        if type(curve) is not V2TrainingEpochCurveRowV1 \
                or curve.schema != EPOCH_SCHEMA or curve.epoch != epoch \
                or type(curve.member_training_receipts) is not tuple \
                or len(curve.member_training_receipts) != len(COHORT_SEEDS) \
                or type(curve.member_calibration_loss_nanonats) is not tuple \
                or len(curve.member_calibration_loss_nanonats) \
                != len(COHORT_SEEDS) \
                or any(type(value) is not int or value < 0
                       for value in curve.member_calibration_loss_nanonats) \
                or curve.cohort_mean_calibration_loss_nanonats \
                != sum(curve.member_calibration_loss_nanonats) \
                // len(COHORT_SEEDS):
            raise BeliefV2CohortTrainingError(
                "V2 training epoch curve drift")
        population_sha, schedule_sha = _epoch_input_digests(
            realization.batches, epoch=epoch)
        for receipt in curve.member_training_receipts:
            if type(receipt) is not EpochTrainingReceiptV1 \
                    or receipt.epoch != epoch \
                    or receipt.batch_count != len(realization.batches) \
                    or receipt.decision_count != len(realization.rows) \
                    or receipt.active_label_count \
                    != realization.active_label_count \
                    or receipt.batch_schema != expected_schema \
                    or receipt.history_transform != NATURAL_HISTORY \
                    or receipt.label_transform != expected_label \
                    or receipt.control_kind != expected_control \
                    or receipt.decision_population_sha256 != population_sha \
                    or receipt.batch_schedule_sha256 != schedule_sha:
                raise BeliefV2CohortTrainingError(
                    "V2 training epoch receipt binding drift")
        receipts_by_epoch.append(curve.member_training_receipts)
        for values, value in zip(
                member_losses, curve.member_calibration_loss_nanonats,
                strict=True):
            values.append(value)
    for member_index, seed in enumerate(COHORT_SEEDS):
        initial = portable_model_state_sha256(new_from_scratch_model(seed))
        if receipts_by_epoch[0][member_index].model_state_sha256_before \
                != initial \
                or any(left[member_index].model_state_sha256_after
                       != right[member_index].model_state_sha256_before
                       for left, right in zip(
                           receipts_by_epoch, receipts_by_epoch[1:])):
            raise BeliefV2CohortTrainingError(
                "V2 training cross-epoch receipt chain drift")
    decision = select_common_epoch(tuple(tuple(row) for row in member_losses))
    expected_patience = (decision.stopped_for_patience
                         and not candidate.truncated_by_deadline)
    if candidate.selected_common_epoch != decision.selected_epoch \
            or candidate.stop_epoch != decision.stop_epoch \
            or candidate.stopped_for_patience is not expected_patience:
        raise BeliefV2CohortTrainingError(
            "V2 common epoch reconstruction drift")
    selected = receipts_by_epoch[decision.selected_epoch - 1]
    checkpoint_hashes = set()
    for raw, expected_receipt in zip(
            candidate.checkpoint_bundles, selected, strict=True):
        try:
            checkpoint, receipt = reopen_checkpoint_bundle(raw)
            model = reopen_model_checkpoint(
                checkpoint, final_epoch_receipt=receipt)
        except ValueError as exc:
            raise BeliefV2CohortTrainingError(
                "V2 selected checkpoint reopen refused") from exc
        if receipt != expected_receipt \
                or portable_model_state_sha256(model) \
                != expected_receipt.model_state_sha256_after:
            raise BeliefV2CohortTrainingError(
                "V2 selected checkpoint receipt drift")
        checkpoint_hashes.add(_sha256(raw))
    if len(checkpoint_hashes) != len(COHORT_SEEDS):
        raise BeliefV2CohortTrainingError(
            "V2 selected checkpoint population collision")


def reopen_trained_v2_cohort(
        manifest_raw: bytes, checkpoint_bundles: tuple[bytes, ...],
        realization: V2CohortRealizationV1,
        training_examples: tuple[V2TrainingExampleV1, ...] | None,
        common_calibration: V2CalibrationScheduleV1,
        calibration_examples: tuple[V2TrainingExampleV1, ...] | None, *,
        compact_control_dose: int | None = None) \
        -> V2TrainedCohortArtifactsV1:
    """Strictly rebuild a persisted cohort manifest and every checkpoint."""
    if type(manifest_raw) is not bytes or not manifest_raw:
        raise BeliefV2CohortTrainingError(
            "V2 trained cohort manifest is empty")
    try:
        payload = json.loads(manifest_raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BeliefV2CohortTrainingError(
            "V2 trained cohort manifest is not JSON") from exc
    expected_keys = {
        "schema", "cohort_id", "cohort_kind", "realization_sha256",
        "common_calibration_sha256", "training_device",
        "initialization_seeds", "epochs", "epoch_count",
        "selected_common_epoch", "stop_epoch", "stopped_for_patience",
        "truncated_by_deadline",
        "label_control_changed_cell_count_per_epoch", "checkpoints",
        "common_epoch_calibration_source",
        "human_calibration_consumed_for_common_epoch",
        "contains_optimizer_resume_state", "contains_corpus_rows",
        "test_split_opened", "test_split_open_authorized",
        "sampler_implementation_authorized",
        "gameplay_strength_screen_authorized", "strength_claim_authorized",
        "deployment_authorized",
    }
    if type(payload) is not dict or set(payload) != expected_keys \
            or canonical_json_bytes(payload) != manifest_raw \
            or payload["schema"] != TRAINED_COHORT_SCHEMA \
            or payload["initialization_seeds"] != list(COHORT_SEEDS) \
            or payload["common_epoch_calibration_source"] \
            != "balanced-synthetic-only" \
            or payload[
                "human_calibration_consumed_for_common_epoch"] is not False \
            or any(payload[key] is not False for key in (
                "contains_optimizer_resume_state", "contains_corpus_rows",
                "test_split_opened", "test_split_open_authorized",
                "sampler_implementation_authorized",
                "gameplay_strength_screen_authorized",
                "strength_claim_authorized", "deployment_authorized")) \
            or type(payload["epochs"]) is not list \
            or type(payload["epoch_count"]) is not int \
            or payload["epoch_count"] != len(payload["epochs"]) \
            or type(payload["checkpoints"]) is not list \
            or len(payload["checkpoints"]) != len(COHORT_SEEDS) \
            or type(checkpoint_bundles) is not tuple \
            or len(checkpoint_bundles) != len(COHORT_SEEDS):
        raise BeliefV2CohortTrainingError(
            "V2 trained cohort manifest identity drift")
    epoch_rows = []
    for epoch, row in enumerate(payload["epochs"], 1):
        if type(row) is not dict or set(row) != {
                "schema", "epoch", "member_training_receipts",
                "member_calibration_loss_nanonats",
                "cohort_mean_calibration_loss_nanonats"} \
                or row["schema"] != EPOCH_SCHEMA or row["epoch"] != epoch \
                or type(row["member_training_receipts"]) is not list \
                or len(row["member_training_receipts"]) \
                != len(COHORT_SEEDS) \
                or type(row[
                    "member_calibration_loss_nanonats"]) is not list \
                or len(row["member_calibration_loss_nanonats"]) \
                != len(COHORT_SEEDS):
            raise BeliefV2CohortTrainingError(
                "V2 persisted epoch row drift")
        try:
            receipts = tuple(reopen_epoch_receipt(
                canonical_json_bytes(receipt))
                for receipt in row["member_training_receipts"])
        except ValueError as exc:
            raise BeliefV2CohortTrainingError(
                "V2 persisted epoch receipt refused") from exc
        epoch_rows.append(V2TrainingEpochCurveRowV1(
            epoch=epoch, member_training_receipts=receipts,
            member_calibration_loss_nanonats=tuple(
                row["member_calibration_loss_nanonats"]),
            cohort_mean_calibration_loss_nanonats=row[
                "cohort_mean_calibration_loss_nanonats"]))
    for index, (row, raw) in enumerate(zip(
            payload["checkpoints"], checkpoint_bundles, strict=True)):
        if type(row) is not dict or set(row) != {
                "member_index", "initialization_seed", "byte_count",
                "bundle_sha256"} \
                or row["member_index"] != index \
                or row["initialization_seed"] != COHORT_SEEDS[index] \
                or type(raw) is not bytes or not raw \
                or row["byte_count"] != len(raw) \
                or row["bundle_sha256"] != _sha256(raw):
            raise BeliefV2CohortTrainingError(
                "V2 persisted checkpoint row drift")
    result = V2TrainedCohortArtifactsV1(
        cohort_id=payload["cohort_id"], cohort_kind=payload["cohort_kind"],
        realization_sha256=payload["realization_sha256"],
        common_calibration_sha256=payload["common_calibration_sha256"],
        training_device=payload["training_device"],
        epochs=tuple(epoch_rows),
        selected_common_epoch=payload["selected_common_epoch"],
        stop_epoch=payload["stop_epoch"],
        stopped_for_patience=payload["stopped_for_patience"],
        truncated_by_deadline=payload["truncated_by_deadline"],
        label_control_changed_cell_count_per_epoch=payload[
            "label_control_changed_cell_count_per_epoch"],
        checkpoint_bundles=checkpoint_bundles)
    if compact_control_dose is None:
        if training_examples is None or calibration_examples is None:
            raise BeliefV2CohortTrainingError(
                "V2 persisted cohort validation population drift")
        validate_trained_v2_cohort(
            realization, training_examples, common_calibration,
            calibration_examples, result)
    else:
        if training_examples is not None or calibration_examples is not None:
            raise BeliefV2CohortTrainingError(
                "V2 persisted cohort mixed validation altitude")
        validate_trained_v2_cohort_rows(
            realization, common_calibration,
            control_dose=compact_control_dose, candidate=result)
    if result.manifest_bytes() != manifest_raw:
        raise BeliefV2CohortTrainingError(
            "V2 trained cohort manifest reconstruction drift")
    return result
