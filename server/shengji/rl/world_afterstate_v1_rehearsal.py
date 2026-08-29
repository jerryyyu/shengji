"""Deterministic non-scientific full-path rehearsal for Value V1.

The rehearsal uses synthetic rows only.  It exists to prove orchestration,
checkpoint, prediction-seal, label-open, negative-control, terminal, immutable
publication, and independent-reopen wiring before any reviewed V0 population
is opened.  It grants no authority for a scientific run.
"""

from __future__ import annotations

import hashlib
from typing import Any, Callable

import numpy as np

from .douzero_micro import HISTORY_EVENT_DIM
from .encode import N_CARDS
from .world_afterstate import (
    PERSPECTIVE_DIM, PUBLIC_DIM, WORLD_RECEIVERS, WorldAfterstateExampleV0,
    WorldAfterstateTensorsV0)
from .world_afterstate_dataset import ReopenedDatasetRowV0
from .world_afterstate_evaluation import EvaluationOutcomeV0
from .world_afterstate_v1 import evaluate_label_ceiling
from .world_afterstate_v1_audit_controller import (
    build_prediction_artifact_bytes, evaluate_sealed_predictions,
    reopen_prediction_artifact_bytes)
from .world_afterstate_v1_controls import (
    action_association_permutation, identical_successor_control,
    label_permutation)
from .world_afterstate_v1_dataset import join_advantage_examples
from .world_afterstate_v1_evaluation import collate_inference_pairs
from .world_afterstate_v1_pipeline import (
    PipelineBuildV1, build_pipeline_build)
from .world_afterstate_v1_result import CONTROL_NAMES, derive_terminal_result
from .world_afterstate_v1_schedule import build_subsplit_manifest
from .world_afterstate_v1_training import AdvantageTrainingConfigV1
from .world_afterstate_v1_training_controller import (
    TRAINING_COHORTS, reopen_cohort_build, train_named_cohort)


TRAIN_STATE_COUNT = 30
AUDIT_STATE_COUNT = 6
FREEZE_SHA256 = "f" * 64
V0_POPULATION_MANIFEST_SHA256 = "a" * 64
AUTHORITY = {
    "scientific_dataset_opening_authorized": False,
    "scientific_training_authorized": False,
    "report_opening_authorized": False,
    "p2_execution_authorized": False,
    "gameplay_authorized": False,
    "strength_claim_authorized": False,
    "merge_authorized": False,
    "promotion_authorized": False,
    "deployment_authorized": False,
    "retry_authorized": False,
    "r5_authorized": False,
}


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def _state_name(*, fold: str, index: int) -> str:
    return f"value-v1-rehearsal-{fold}-{index}"


def _tensors(*, state_index: int, candidate_index: int) \
        -> WorldAfterstateTensorsV0:
    public = np.zeros(PUBLIC_DIM, dtype=np.float32)
    public[0] = candidate_index
    public[1] = state_index / 100.0
    history = np.zeros((1, HISTORY_EVENT_DIM), dtype=np.float32)
    history[0, 0] = state_index / 100.0
    world = np.zeros((WORLD_RECEIVERS, N_CARDS), dtype=np.float32)
    world[0, candidate_index] = 0.5
    world[1, state_index % N_CARDS] = 0.5
    perspective = np.zeros(PERSPECTIVE_DIM, dtype=np.float32)
    perspective[0] = 1.0
    result = WorldAfterstateTensorsV0(
        public=public, history=history, world=world,
        perspective=perspective)
    result.validate()
    return result


def _row(*, fold: str, state_index: int, candidate_index: int,
         replicate: int) -> ReopenedDatasetRowV0:
    state = _state_name(fold=fold, index=state_index)
    successor = _digest(f"{state}-successor-{candidate_index}")
    state_count = (TRAIN_STATE_COUNT if fold == "train"
                   else AUDIT_STATE_COUNT)
    advantage = (state_index + 1 if candidate_index == 1
                 else state_count + state_index + 1)
    category = 80 if candidate_index == 0 else 80 + advantage
    example = WorldAfterstateExampleV0(
        tensors=_tensors(
            state_index=state_index, candidate_index=candidate_index),
        signed_level_category=category, successor_sha256=successor)
    outcome = EvaluationOutcomeV0(
        deal_group_sha256=_digest(f"{state}-deal"),
        state_group_id=_digest(state), source="synthetic-rehearsal",
        fold=fold, root_role="attacker", play_phase="middle",
        position="lead", trump_rank="7", trump_mode="H",
        points_bucket="40-79", candidate_index=candidate_index,
        protected_incumbent=candidate_index == 0,
        successor_sha256=successor, replicate=replicate,
        signed_level_category=category)
    return ReopenedDatasetRowV0(
        example=example, evaluation_outcome=outcome,
        row_sha256=_digest(
            f"{state}-row-{candidate_index}-{replicate}"))


def _training_population():
    rows = []
    bindings = []
    for state_index in range(TRAIN_STATE_COUNT):
        state = _state_name(fold="train", index=state_index)
        bindings.append({
            "deal_group_sha256": _digest(f"{state}-deal"),
            "state_group_id": _digest(state), "fold": "train",
        })
        for candidate in range(3):
            for replicate in (0, 1):
                rows.append(_row(
                    fold="train", state_index=state_index,
                    candidate_index=candidate, replicate=replicate))
    return tuple(join_advantage_examples(rows)), bindings


def _target_free_audit_batch(*, identical: bool):
    state_group_ids = []
    candidate_indexes = []
    incumbent_successor_sha256s = []
    candidate_successor_sha256s = []
    incumbents = []
    candidates = []
    for state_index in range(AUDIT_STATE_COUNT):
        state = _state_name(fold="calibration", index=state_index)
        incumbent = _tensors(state_index=state_index, candidate_index=0)
        for candidate in (1, 2):
            state_group_ids.append(_digest(state))
            candidate_indexes.append(candidate)
            incumbent_successor_sha256s.append(
                _digest(f"{state}-successor-0"))
            candidate_successor_sha256s.append(
                _digest(f"{state}-successor-{candidate}"))
            incumbents.append(incumbent)
            candidates.append(
                incumbent if identical else _tensors(
                    state_index=state_index, candidate_index=candidate))
    return collate_inference_pairs(
        state_group_ids=state_group_ids,
        candidate_indexes=candidate_indexes,
        incumbent_successor_sha256s=incumbent_successor_sha256s,
        candidate_successor_sha256s=candidate_successor_sha256s,
        incumbent_tensors=incumbents, candidate_tensors=candidates)


def _audit_labels():
    rows = []
    for state_index in range(AUDIT_STATE_COUNT):
        for candidate in range(3):
            for replicate in (0, 1):
                rows.append(_row(
                    fold="calibration", state_index=state_index,
                    candidate_index=candidate, replicate=replicate))
    return tuple(join_advantage_examples(rows))


def build_non_scientific_rehearsal(
        *, progress: Callable[[dict[str, Any]], None] | None = None) \
        -> PipelineBuildV1:
    """Run the 30-train/6-audit synthetic path entirely in memory."""
    train, bindings = _training_population()
    label_ceiling = evaluate_label_ceiling(
        tuple(value.pair for value in train), bootstrap_replicates=200)
    if label_ceiling["passed"] is not True:
        raise RuntimeError("synthetic rehearsal P0 did not pass")
    subsplit = build_subsplit_manifest(
        bindings,
        v0_population_manifest_sha256=V0_POPULATION_MANIFEST_SHA256)
    identical, identical_evidence = identical_successor_control(train)
    association, association_evidence = action_association_permutation(train)
    permuted, permuted_evidence = label_permutation(train)
    populations = {
        "natural": train, "identical-successor": identical,
        "action-association-permutation": association,
        "label-permutation": permuted,
    }
    evidence = {
        "identical-successor": identical_evidence,
        "action-association-permutation": association_evidence,
        "label-permutation": permuted_evidence,
    }
    config = AdvantageTrainingConfigV1(
        learning_rate_ppb=1_000_000,
        weight_decay_ppb=10_000_000,
        gradient_norm_milli=1_000,
        max_epochs=1, early_stop_patience=1,
        minimum_improvement_nanoloss=1)
    cohorts = {}
    models = {}
    for cohort_index, name in enumerate(TRAINING_COHORTS):
        build = train_named_cohort(
            cohort_name=name, values=populations[name],
            subsplit_manifest=subsplit, freeze_sha256=FREEZE_SHA256,
            shape_name="small",
            initialization_seeds=tuple(
                1000 + cohort_index * 10 + member for member in range(8)),
            config=config, pair_cap=32, schedule_seed=91,
            wall_budget_nanoseconds=10**12, progress=progress)
        models[name], _manifest = reopen_cohort_build(build)
        cohorts[name] = build

    natural_batch = _target_free_audit_batch(identical=False)
    identical_batch = _target_free_audit_batch(identical=True)
    prediction_raws = {}
    for name in TRAINING_COHORTS:
        prediction_raws[name] = build_prediction_artifact_bytes(
            models=models[name],
            batch=(identical_batch if name == "identical-successor"
                   else natural_batch),
            cohort_manifest=cohorts[name].manifest)
    # The label objects are deliberately not constructed until every
    # target-free prediction byte stream above has been sealed.
    calibration = _audit_labels()
    audits = {
        name: evaluate_sealed_predictions(prediction_raws[name], calibration)
        for name in TRAINING_COHORTS
    }
    identical_predictions, _shuffled, _artifact = \
        reopen_prediction_artifact_bytes(
            prediction_raws["identical-successor"])
    terminal = derive_terminal_result(
        label_ceiling,
        natural_result=audits["natural"]["natural_result"],
        control_results={
            name: audits[name]["natural_result"] for name in CONTROL_NAMES
        },
        identical_predictions_exact_zero=bool(identical_predictions) and all(
            row.advantage_microlevels == 0
            for row in identical_predictions),
        world_shuffle_delta_result=audits[
            "natural"]["world_shuffle_delta_result"])
    return build_pipeline_build(
        run_kind="non-scientific-rehearsal",
        label_ceiling=label_ceiling, subsplit_manifest=subsplit,
        control_evidence=evidence, cohort_builds=cohorts,
        prediction_artifacts=prediction_raws, audit_results=audits,
        terminal_result=terminal)


__all__ = [
    "AUDIT_STATE_COUNT", "AUTHORITY", "TRAIN_STATE_COUNT",
    "build_non_scientific_rehearsal",
]
