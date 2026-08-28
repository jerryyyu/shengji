"""Source-neutral model inference and exact round scoring for BELIEF-V1 V2.

V2 trains on the reviewed common public-history surface: final declaration,
engine-accepted plays, and no source-channel availability.  This module makes
that same transformation explicit at evaluation, binds REF-C and every model
to one mechanically equivalent scoring actor, and reduces exact per-decision
proper scores to complete-round units.

It has no filesystem, stage writer, test opener, sampler invocation, model
training, gameplay, or execution authority.
"""

from __future__ import annotations

from concurrent.futures import Executor, ProcessPoolExecutor
from dataclasses import dataclass, replace
import multiprocessing
import os
from threading import BrokenBarrierError
from typing import Any

import torch.multiprocessing as torch_multiprocessing

from .belief_cohort import COHORT_SEEDS, ensemble_ownership
from .belief_artifacts import reopen_checkpoint_bundle
from .belief_checkpoint import reopen_model_checkpoint
from .belief_contract import ActorObservationV1, BeliefTargetsV1
from .belief_evaluation import (
    DecisionProperScoreV1,
    score_target_candidates,
)
from .belief_input import build_history_ownership_input
from .belief_model import (
    HistoryOwnershipModelV1,
    MODEL_SCHEMA,
    inference_logits,
    quantize_raw_count_weights,
)
from .belief_ownership import BeliefOwnershipV1, validate_ownership
from .belief_projection import RawCountWeightV1, project_count_weights
from .belief_refc_capture import (
    ReferenceWorldBatchV1,
    validate_reference_world_batch,
)
from .belief_v2_accelerator import portable_model_state_sha256
from .belief_v2_cohort_training import V2TrainedCohortArtifactsV1
from .belief_v2_common_surface import (
    V2CommonSurfaceTensorsV1,
    common_surface_actor,
    validate_common_surface_tensors,
)
from .belief_v2_human_corpus import UNIVERSAL_POLICY_IDS
from .belief_v2_statistics import V2RoundScoreV1, validate_v2_round_score


PPB = 1_000_000_000
V2_PROJECTION_WORKERS = 16
V2_DECISION_WORKERS = 16


class BeliefV2ScoringError(ValueError):
    """A V2 common actor, model, reference, or round score drifted."""


@dataclass(frozen=True)
class _ProjectionTaskV1:
    actor: ActorObservationV1
    raw_weights: tuple[RawCountWeightV1, ...]
    model_sha256: str
    decision_key: str
    cohort_id: str
    member_index: int


@dataclass(frozen=True)
class _DecisionTaskV1:
    decision: V2ScoringDecisionV1
    cohort_identity: tuple[tuple[str, tuple[str, ...]], ...]


@dataclass(frozen=True)
class _ScoredDecisionV1:
    decision_key: str
    cohort_scores: tuple[
        tuple[str, tuple[DecisionProperScoreV1, ...]], ...]


_DECISION_WORKER_COHORTS: tuple[V2CohortModelsV1, ...] | None = None
_DECISION_WORKER_IDENTITY: tuple[
    tuple[str, tuple[str, ...]], ...] | None = None
_DECISION_WORKER_STARTUP_BARRIER: Any | None = None
DECISION_WORKER_STARTUP_TIMEOUT_SECONDS = 60


def _projection_worker_probe(_: int) -> int:
    return os.getpid()


def projection_pool() -> ProcessPoolExecutor:
    """Create the fixed, source-reviewed target-blind projection pool."""
    if "forkserver" not in multiprocessing.get_all_start_methods():
        raise BeliefV2ScoringError(
            "V2 projection worker start method is unavailable")
    return ProcessPoolExecutor(
        max_workers=V2_PROJECTION_WORKERS,
        mp_context=multiprocessing.get_context("forkserver"))


def warm_projection_pool(executor: ProcessPoolExecutor) -> None:
    """Start the fixed worker population before outcome-bearing scoring."""
    if not isinstance(executor, ProcessPoolExecutor):
        raise BeliefV2ScoringError("V2 projection worker identity drift")
    try:
        pids = tuple(executor.map(
            _projection_worker_probe, range(V2_PROJECTION_WORKERS),
            chunksize=1))
    except (OSError, RuntimeError) as exc:
        raise BeliefV2ScoringError(
            "V2 projection worker startup refused") from exc
    if len(pids) != V2_PROJECTION_WORKERS \
            or any(type(pid) is not int or pid <= 0 for pid in pids):
        raise BeliefV2ScoringError(
            "V2 projection worker startup population drift")


def _is_sha256(value: Any) -> bool:
    return (type(value) is str and len(value) == 64
            and all(char in "0123456789abcdef" for char in value))


def _round_divide(numerator: int, denominator: int) -> int:
    if type(numerator) is not int or type(denominator) is not int \
            or denominator <= 0:
        raise BeliefV2ScoringError("V2 scoring ratio input drift")
    sign = -1 if numerator < 0 else 1
    return sign * ((2 * abs(numerator) + denominator)
                   // (2 * denominator))


def v2_scoring_actor(actor: ActorObservationV1) -> ActorObservationV1:
    """Return the exact complete-flag adapter used only for V2 mechanics."""
    try:
        common = common_surface_actor(actor)
        result = replace(
            common,
            declaration_history_complete=True,
            attempted_play_history_complete=True,
        )
        build_history_ownership_input(
            result, behavior_policy_ids=UNIVERSAL_POLICY_IDS)
    except ValueError as exc:
        raise BeliefV2ScoringError("V2 scoring actor derivation refused") \
            from exc
    return result


@dataclass(frozen=True)
class V2CohortModelsV1:
    cohort_id: str
    models: tuple[HistoryOwnershipModelV1, ...]
    model_sha256s: tuple[str, ...]


def validate_v2_cohort_models(value: V2CohortModelsV1) -> None:
    if type(value) is not V2CohortModelsV1 \
            or type(value.cohort_id) is not str or not value.cohort_id \
            or type(value.models) is not tuple \
            or len(value.models) != len(COHORT_SEEDS) \
            or any(type(model) is not HistoryOwnershipModelV1
                   for model in value.models) \
            or type(value.model_sha256s) is not tuple \
            or len(value.model_sha256s) != len(COHORT_SEEDS) \
            or len(set(value.model_sha256s)) != len(COHORT_SEEDS) \
            or any(not _is_sha256(digest)
                   for digest in value.model_sha256s):
        raise BeliefV2ScoringError("V2 scoring cohort population drift")
    for model, digest in zip(
            value.models, value.model_sha256s, strict=True):
        if next(model.parameters()).device.type != "cpu" \
                or portable_model_state_sha256(model) != digest:
            raise BeliefV2ScoringError(
                "V2 scoring cohort checkpoint identity drift")


def cohort_models_from_trained(
        trained: V2TrainedCohortArtifactsV1) -> V2CohortModelsV1:
    """Reopen every portable selected checkpoint for target-blind scoring."""
    if type(trained) is not V2TrainedCohortArtifactsV1 \
            or type(trained.checkpoint_bundles) is not tuple \
            or len(trained.checkpoint_bundles) != len(COHORT_SEEDS):
        raise BeliefV2ScoringError(
            "V2 trained scoring cohort population drift")
    models = []
    digests = []
    for raw in trained.checkpoint_bundles:
        try:
            checkpoint, receipt = reopen_checkpoint_bundle(raw)
            model = reopen_model_checkpoint(
                checkpoint, final_epoch_receipt=receipt)
        except ValueError as exc:
            raise BeliefV2ScoringError(
                "V2 scoring checkpoint reopen refused") from exc
        model.eval()
        models.append(model)
        digests.append(portable_model_state_sha256(model))
    result = V2CohortModelsV1(
        cohort_id=trained.cohort_id,
        models=tuple(models), model_sha256s=tuple(digests))
    validate_v2_cohort_models(result)
    return result


@dataclass(frozen=True)
class V2ScoringDecisionV1:
    decision_key: str
    source_actor: ActorObservationV1
    target: BeliefTargetsV1
    common: V2CommonSurfaceTensorsV1
    reference: ReferenceWorldBatchV1


def _validate_decision(value: V2ScoringDecisionV1) -> None:
    if type(value) is not V2ScoringDecisionV1 \
            or not _is_sha256(value.decision_key) \
            or type(value.source_actor) is not ActorObservationV1 \
            or type(value.target) is not BeliefTargetsV1 \
            or type(value.common) is not V2CommonSurfaceTensorsV1 \
            or type(value.reference) is not ReferenceWorldBatchV1:
        raise BeliefV2ScoringError("V2 scoring decision population drift")
    try:
        validate_common_surface_tensors(value.source_actor, value.common)
        validate_reference_world_batch(value.reference)
    except ValueError as exc:
        raise BeliefV2ScoringError(
            "V2 scoring decision input refused") from exc
    expected = v2_scoring_actor(value.source_actor)
    reference_actor = v2_scoring_actor(value.reference.actor)
    if expected.canonical_bytes() != reference_actor.canonical_bytes():
        raise BeliefV2ScoringError(
            "V2 scoring reference public surface drift")


def _cohort_identity(cohorts: tuple[V2CohortModelsV1, ...]) \
        -> tuple[tuple[str, tuple[str, ...]], ...]:
    return tuple((cohort.cohort_id, cohort.model_sha256s)
                 for cohort in cohorts)


def _initialize_decision_worker(
        cohorts: tuple[V2CohortModelsV1, ...], startup_barrier: Any) -> None:
    from .belief_v2_execution_identity import configure_numerical_runtime
    configure_numerical_runtime()
    if type(cohorts) is not tuple or not cohorts:
        raise BeliefV2ScoringError(
            "V2 decision worker cohort population drift")
    for cohort in cohorts:
        validate_v2_cohort_models(cohort)
    global _DECISION_WORKER_COHORTS, _DECISION_WORKER_IDENTITY
    global _DECISION_WORKER_STARTUP_BARRIER
    _DECISION_WORKER_COHORTS = cohorts
    _DECISION_WORKER_IDENTITY = _cohort_identity(cohorts)
    _DECISION_WORKER_STARTUP_BARRIER = startup_barrier


def _decision_worker_probe(
        expected: tuple[tuple[str, tuple[str, ...]], ...]) \
        -> tuple[int, tuple[tuple[str, tuple[str, ...]], ...]]:
    if _DECISION_WORKER_COHORTS is None \
            or _DECISION_WORKER_IDENTITY != expected \
            or _DECISION_WORKER_STARTUP_BARRIER is None:
        raise BeliefV2ScoringError(
            "V2 decision worker cohort identity drift")
    # The first task in every newly initialized worker blocks until the whole
    # frozen worker population has arrived. A fixed sleep is not sufficient:
    # workers that deserialize early can consume every queued probe before the
    # slowest worker becomes ready.
    try:
        _DECISION_WORKER_STARTUP_BARRIER.wait(
            timeout=DECISION_WORKER_STARTUP_TIMEOUT_SECONDS)
    except BrokenBarrierError as exc:
        raise BeliefV2ScoringError(
            "V2 decision worker startup barrier refused") from exc
    return os.getpid(), _DECISION_WORKER_IDENTITY


class V2DecisionScoringPool:
    """Bind every cohort once, then score distinct decisions in parallel."""

    def __init__(self, cohorts: tuple[V2CohortModelsV1, ...]):
        if type(cohorts) is not tuple or not cohorts:
            raise BeliefV2ScoringError(
                "V2 decision pool cohort population drift")
        for cohort in cohorts:
            validate_v2_cohort_models(cohort)
        self.cohort_identity = _cohort_identity(cohorts)
        if "forkserver" not in multiprocessing.get_all_start_methods():
            raise BeliefV2ScoringError(
                "V2 decision worker start method is unavailable")
        strategies = torch_multiprocessing.get_all_sharing_strategies()
        if "file_system" not in strategies:
            raise BeliefV2ScoringError(
                "V2 decision worker tensor transport is unavailable")
        self._previous_sharing_strategy = (
            torch_multiprocessing.get_sharing_strategy())
        try:
            # ``forkserver`` pickles the initializer arguments. PyTorch's
            # default Linux transport consumes one descriptor per tensor
            # storage; the complete 16-member population exceeds the
            # forkserver descriptor-message ceiling before a worker starts.
            # Filename-backed shared storage preserves one parent population
            # across all workers without rebuilding models or weakening exact
            # checkpoint identity.
            torch_multiprocessing.set_sharing_strategy("file_system")
            if torch_multiprocessing.get_sharing_strategy() != "file_system":
                raise BeliefV2ScoringError(
                    "V2 decision worker tensor transport drift")
            context = multiprocessing.get_context("forkserver")
            self._startup_barrier = context.Barrier(V2_DECISION_WORKERS)
            self._executor = ProcessPoolExecutor(
                max_workers=V2_DECISION_WORKERS,
                mp_context=context,
                initializer=_initialize_decision_worker,
                initargs=(cohorts, self._startup_barrier))
        except Exception:
            torch_multiprocessing.set_sharing_strategy(
                self._previous_sharing_strategy)
            raise

    def __enter__(self) -> V2DecisionScoringPool:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def close(self) -> None:
        try:
            self._executor.shutdown(wait=True, cancel_futures=True)
        finally:
            torch_multiprocessing.set_sharing_strategy(
                self._previous_sharing_strategy)

    def warm(self) -> None:
        try:
            observed = tuple(self._executor.map(
                _decision_worker_probe,
                (self.cohort_identity
                 for _ in range(V2_DECISION_WORKERS)),
                chunksize=1))
        except BeliefV2ScoringError:
            raise
        except (OSError, RuntimeError, ValueError) as exc:
            raise BeliefV2ScoringError(
                "V2 decision worker startup refused") from exc
        pids = tuple(pid for pid, _ in observed)
        if len(observed) != V2_DECISION_WORKERS \
                or len(set(pids)) != V2_DECISION_WORKERS \
                or any(type(pid) is not int or pid <= 0
                       or identity != self.cohort_identity
                       for pid, identity in observed):
            raise BeliefV2ScoringError(
                "V2 decision worker startup population drift")

    def score(
            self, decisions: tuple[V2ScoringDecisionV1, ...]) \
            -> tuple[_ScoredDecisionV1, ...]:
        tasks = tuple(_DecisionTaskV1(
            decision=decision, cohort_identity=self.cohort_identity)
            for decision in decisions)
        try:
            rows_list = []
            # ``Executor.map(buffersize=...)`` is Python 3.14-only while the
            # project supports Python 3.11+ and CI runs Python 3.12. Fixed
            # batches retain the same bounded 2x-worker in-flight population
            # without eagerly queueing a complete round.
            batch_size = 2 * V2_DECISION_WORKERS
            for start in range(0, len(tasks), batch_size):
                rows_list.extend(self._executor.map(
                    _score_decision_task,
                    tasks[start:start + batch_size], chunksize=1))
            rows = tuple(rows_list)
        except BeliefV2ScoringError:
            raise
        except Exception as exc:
            raise BeliefV2ScoringError(
                "V2 decision worker execution refused") from exc
        if len(rows) != len(decisions) \
                or any(type(row) is not _ScoredDecisionV1 for row in rows) \
                or tuple(row.decision_key for row in rows) \
                != tuple(decision.decision_key for decision in decisions):
            raise BeliefV2ScoringError(
                "V2 decision worker result order drift")
        return rows


def _adapt_reference(
        actor: ActorObservationV1,
        batch: ReferenceWorldBatchV1) -> BeliefOwnershipV1:
    original = batch.ownership()
    result = replace(
        original,
        actor_observation_sha256=actor.sha256(),
        behavior_policy_ids=UNIVERSAL_POLICY_IDS,
    )
    try:
        validate_ownership(actor, result)
    except ValueError as exc:
        raise BeliefV2ScoringError(
            "V2 scoring reference adaptation refused") from exc
    return result


def _predict_cohort(
        actor: ActorObservationV1,
        common: V2CommonSurfaceTensorsV1,
        cohort: V2CohortModelsV1, *, decision_key: str) \
        -> tuple[tuple[BeliefOwnershipV1, ...], BeliefOwnershipV1]:
    members = []
    for member_index, (model, model_sha) in enumerate(zip(
            cohort.models, cohort.model_sha256s, strict=True)):
        try:
            logits = inference_logits(model, common.tensors)
            raw = quantize_raw_count_weights(common.tensors, logits)
            prediction = project_count_weights(
                actor, behavior_policy_ids=UNIVERSAL_POLICY_IDS,
                model_schema=MODEL_SCHEMA,
                model_sha256=model_sha, raw_weights=raw)
        except ValueError as exc:
            raise BeliefV2ScoringError(
                "V2 scoring member prediction refused: "
                f"decision_key={decision_key}, "
                f"cohort_id={cohort.cohort_id}, "
                f"member_index={member_index}, "
                f"model_sha256={model_sha}") from exc
        members.append(prediction)
    try:
        ensemble = ensemble_ownership(actor, tuple(members))
    except ValueError as exc:
        raise BeliefV2ScoringError(
            "V2 scoring ensemble prediction refused") from exc
    return tuple(members), ensemble


def _project_member_task(task: _ProjectionTaskV1) -> BeliefOwnershipV1:
    """Project one target-blind member in an isolated worker process."""
    if type(task) is not _ProjectionTaskV1:
        raise BeliefV2ScoringError("V2 projection task identity drift")
    try:
        return project_count_weights(
            task.actor, behavior_policy_ids=UNIVERSAL_POLICY_IDS,
            model_schema=MODEL_SCHEMA,
            model_sha256=task.model_sha256,
            raw_weights=task.raw_weights)
    except ValueError as exc:
        raise BeliefV2ScoringError(
            "V2 scoring member prediction refused: "
            f"decision_key={task.decision_key}, "
            f"cohort_id={task.cohort_id}, "
            f"member_index={task.member_index}, "
            f"model_sha256={task.model_sha256}") from exc


def _predict_cohorts(
        actor: ActorObservationV1,
        common: V2CommonSurfaceTensorsV1,
        cohorts: tuple[V2CohortModelsV1, ...], *, decision_key: str,
        projection_executor: Executor | None) -> tuple[
            tuple[tuple[BeliefOwnershipV1, ...], BeliefOwnershipV1], ...]:
    if projection_executor is None:
        return tuple(_predict_cohort(
            actor, common, cohort, decision_key=decision_key)
            for cohort in cohorts)

    tasks = []
    for cohort in cohorts:
        for member_index, (model, model_sha) in enumerate(zip(
                cohort.models, cohort.model_sha256s, strict=True)):
            try:
                logits = inference_logits(model, common.tensors)
                raw = quantize_raw_count_weights(common.tensors, logits)
            except ValueError as exc:
                raise BeliefV2ScoringError(
                    "V2 scoring member prediction refused: "
                    f"decision_key={decision_key}, "
                    f"cohort_id={cohort.cohort_id}, "
                    f"member_index={member_index}, "
                    f"model_sha256={model_sha}") from exc
            tasks.append(_ProjectionTaskV1(
                actor=actor, raw_weights=raw, model_sha256=model_sha,
                decision_key=decision_key, cohort_id=cohort.cohort_id,
                member_index=member_index))
    try:
        projected = tuple(projection_executor.map(
            _project_member_task, tasks, chunksize=1))
    except BeliefV2ScoringError:
        raise
    except (OSError, RuntimeError) as exc:
        raise BeliefV2ScoringError(
            "V2 projection worker execution refused") from exc
    expected = len(cohorts) * len(COHORT_SEEDS)
    if len(projected) != expected:
        raise BeliefV2ScoringError(
            "V2 projection worker population drift")
    results = []
    offset = 0
    for cohort in cohorts:
        members = projected[offset:offset + len(COHORT_SEEDS)]
        offset += len(COHORT_SEEDS)
        try:
            ensemble = ensemble_ownership(actor, members)
        except ValueError as exc:
            raise BeliefV2ScoringError(
                "V2 scoring ensemble prediction refused") from exc
        results.append((members, ensemble))
    return tuple(results)


def _score_decision(
        decision: V2ScoringDecisionV1,
        cohorts: tuple[V2CohortModelsV1, ...], *,
        projection_executor: Executor | None = None) -> _ScoredDecisionV1:
    actor = v2_scoring_actor(decision.source_actor)
    reference = _adapt_reference(actor, decision.reference)
    predictions = _predict_cohorts(
        actor, decision.common, cohorts,
        decision_key=decision.decision_key,
        projection_executor=projection_executor)
    cohort_scores = []
    for cohort, (members, ensemble) in zip(
            cohorts, predictions, strict=True):
        if not reference.probabilities:
            if any(member.probabilities for member in members) \
                    or ensemble.probabilities:
                raise BeliefV2ScoringError(
                    "V2 empty ownership population drift")
            scores = ()
        else:
            scores = score_target_candidates(
                actor, decision.target, reference, (*members, ensemble))
        cohort_scores.append((cohort.cohort_id, scores))
    return _ScoredDecisionV1(
        decision_key=decision.decision_key,
        cohort_scores=tuple(cohort_scores))


def _score_decision_task(task: _DecisionTaskV1) -> _ScoredDecisionV1:
    if type(task) is not _DecisionTaskV1 \
            or _DECISION_WORKER_COHORTS is None \
            or _DECISION_WORKER_IDENTITY != task.cohort_identity:
        raise BeliefV2ScoringError(
            "V2 decision worker task identity drift")
    return _score_decision(task.decision, _DECISION_WORKER_COHORTS)


def _score_ppb(numerator: int, denominator: int) -> int:
    return _round_divide(numerator * PPB, denominator)


def _mean(values: tuple[int, ...]) -> int:
    if not values:
        raise BeliefV2ScoringError("V2 scoring mean population is empty")
    return _round_divide(sum(values), len(values))


def _mean_brier(scores: tuple[DecisionProperScoreV1, ...], *,
                reference: bool) -> int:
    return _mean(tuple(_score_ppb(
        score.reference_brier_numerator if reference
        else score.candidate_brier_numerator,
        score.brier_denominator) for score in scores))


def score_v2_round(
        *, round_key: str, source_kind: str, split: str, trump_rank: str,
        decisions: tuple[V2ScoringDecisionV1, ...],
        cohorts: tuple[V2CohortModelsV1, ...],
        projection_executor: Executor | None = None,
        decision_pool: V2DecisionScoringPool | None = None) \
        -> V2RoundScoreV1:
    """Predict all frozen cohorts and reduce one complete round exactly."""
    if not _is_sha256(round_key) or source_kind not in {"synthetic", "human"} \
            or split not in {"calibration", "test"} \
            or type(trump_rank) is not str \
            or type(decisions) is not tuple or not decisions \
            or type(cohorts) is not tuple or not cohorts \
            or len({cohort.cohort_id for cohort in cohorts}) != len(cohorts) \
            or projection_executor is not None and decision_pool is not None:
        raise BeliefV2ScoringError("V2 scoring round identity drift")
    for decision in decisions:
        _validate_decision(decision)
    if decision_pool is None:
        for cohort in cohorts:
            validate_v2_cohort_models(cohort)
    elif type(decision_pool) is not V2DecisionScoringPool \
            or decision_pool.cohort_identity != _cohort_identity(cohorts):
        raise BeliefV2ScoringError("V2 decision pool identity drift")
    if len({decision.decision_key for decision in decisions}) \
            != len(decisions):
        raise BeliefV2ScoringError("V2 scoring decision duplicate")

    ensemble_scores: dict[str, list[DecisionProperScoreV1]] = {
        cohort.cohort_id: [] for cohort in cohorts}
    member_scores: dict[str, list[list[DecisionProperScoreV1]]] = {
        cohort.cohort_id: [[] for _ in COHORT_SEEDS] for cohort in cohorts}
    scored_decisions = (decision_pool.score(decisions)
                        if decision_pool is not None else tuple(
                            _score_decision(
                                decision, cohorts,
                                projection_executor=projection_executor)
                            for decision in decisions))
    cohort_ids = tuple(cohort.cohort_id for cohort in cohorts)
    for decision, scored in zip(decisions, scored_decisions, strict=True):
        if type(scored) is not _ScoredDecisionV1 \
                or scored.decision_key != decision.decision_key \
                or type(scored.cohort_scores) is not tuple \
                or any(type(row) is not tuple or len(row) != 2
                       for row in scored.cohort_scores) \
                or tuple(row[0] for row in scored.cohort_scores) != cohort_ids \
                or any(type(row[1]) is not tuple
                       or len(row[1]) not in {0, len(COHORT_SEEDS) + 1}
                       or any(type(score) is not DecisionProperScoreV1
                              for score in row[1])
                       for row in scored.cohort_scores):
            raise BeliefV2ScoringError(
                "V2 decision score identity drift")
        for cohort_id, scores in scored.cohort_scores:
            if not scores:
                continue
            for index, score in enumerate(scores[:-1]):
                member_scores[cohort_id][index].append(score)
            ensemble_scores[cohort_id].append(scores[-1])
    if not any(ensemble_scores.values()):
        raise BeliefV2ScoringError(
            "V2 round has no informative ownership decisions")
    first = tuple(ensemble_scores[cohort_ids[0]])
    reference_brier = _mean_brier(first, reference=True)
    reference_log = _mean(tuple(
        score.reference_log_loss_nanonats for score in first))
    cohort_brier = []
    cohort_logs = []
    cohort_members = []
    for cohort_id in cohort_ids:
        scores = tuple(ensemble_scores[cohort_id])
        if tuple((row.actor_observation_sha256,
                  row.privileged_target_sha256,
                  row.reference_ownership_sha256,
                  row.reference_brier_numerator,
                  row.brier_denominator,
                  row.reference_log_loss_nanonats) for row in scores) \
                != tuple((row.actor_observation_sha256,
                           row.privileged_target_sha256,
                           row.reference_ownership_sha256,
                           row.reference_brier_numerator,
                           row.brier_denominator,
                           row.reference_log_loss_nanonats) for row in first):
            raise BeliefV2ScoringError(
                "V2 scoring reference cross-cohort drift")
        cohort_brier.append((cohort_id, _mean_brier(
            scores, reference=False)))
        cohort_logs.append((cohort_id, _mean(tuple(
            score.candidate_log_loss_nanonats for score in scores))))
        cohort_members.append((cohort_id, tuple(_mean_brier(
            tuple(rows), reference=False)
            for rows in member_scores[cohort_id])))
    result = V2RoundScoreV1(
        round_key=round_key, source_kind=source_kind, split=split,
        trump_rank=trump_rank, decision_count=len(decisions),
        reference_brier_ppb=reference_brier,
        reference_log_loss_nanonats=reference_log,
        cohort_brier_ppb=tuple(cohort_brier),
        cohort_log_loss_nanonats=tuple(cohort_logs),
        cohort_member_brier_ppb=tuple(cohort_members))
    try:
        validate_v2_round_score(result, cohort_ids=cohort_ids)
    except ValueError as exc:
        raise BeliefV2ScoringError("V2 round score validation refused") \
            from exc
    return result
