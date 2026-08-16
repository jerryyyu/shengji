"""Score-free, source-pinned deadline estimates for BELIEF-V1 V2.

The execution freeze needs next-unit estimates before it may create a corpus.
This module derives them from the reviewed 416-round capture preflight and a
rank-diverse, out-of-population 32-round probe.  The probe measures one full
REF-C round per coordinate and two complete passes over 32 one-round training
batches, including fresh example reconstruction and collation for each pass.
It projects each training pass to the exact V2 train-round count;
one-round batches deliberately upper-bound the production packer, which may
combine round groups up to its decision cap.

Only timing and identity receipts leave this module.  Captured rows, sampled
worlds, model states, losses, and hidden labels are discarded.  No production
seed, evidence namespace, calibration/test population, or execution authority
is opened here.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import math
import os
import time
from dataclasses import dataclass
from typing import Any

from ..ai.registry import make_bot
from ..engine.round import Round
from .belief_capture import (
    CHAMPION_POLICY,
    CapturedBeliefRoundV1,
    _capture_with_policies,
)
from .belief_contract import PublicTranscriptV1, canonical_json_bytes
from .belief_corpus import reopen_actor_row
from .belief_cohort import COHORT_SEEDS
from .belief_model import new_from_scratch_model
from .belief_refc_capture import capture_ref_c_worlds
from .belief_reference import REF_C_WORLD_COUNT
from .belief_v2_accelerator import (
    canonical_training_device,
    evaluate_v2_calibration_cohort_stream_nanonats,
    move_models_to_device,
    new_v2_optimizer,
    portable_model_state_sha256,
    train_v2_cohort_epoch_stream,
)
from .belief_v2_device_runner import synchronize_training_device
from .belief_v2_execution_identity import V2RuntimeProfileV1
from .belief_v2_preflight import (
    V2PreflightCoordinate,
    _validate_live_run_environment,
    preflight_coordinates,
    preflight_result_bytes,
)
from .belief_v2_protocol import (
    MAX_SEED,
    V2_CAPTURE_LANES,
    V2_RANKS,
    V2_SPLIT_COUNTS,
)
from .belief_v2_training import (
    build_synthetic_training_example,
    collate_v2_training_examples,
)


DEADLINE_ESTIMATE_SCHEMA = "belief-v1-v2-deadline-estimate-receipt-v2"
DEADLINE_PROBE_SCHEMA = "belief-v1-v2-deadline-probe-v1"
DEADLINE_PROBE_ROUND_COUNT = 32
DEADLINE_TRAINING_REPEAT_COUNT = 2
TRAINING_PROJECTION_MARGIN_NUMERATOR = 5
TRAINING_PROJECTION_MARGIN_DENOMINATOR = 4
MINIMUM_SAFETY_RESERVE_NANOSECONDS = 60_000_000_000
SAFETY_RESERVE_FRACTION_DENOMINATOR = 20


class BeliefV2DeadlineEstimateError(ValueError):
    """A deadline sample, derivation, or authority boundary drifted."""


@dataclass(frozen=True)
class V2DeadlineProbeMeasurement:
    coordinate: V2PreflightCoordinate
    worker_process_id: int
    started_monotonic_nanoseconds: int
    finished_monotonic_nanoseconds: int
    reference_wall_nanoseconds: int
    training_pairs: tuple[Any, ...]
    reference_manifest_population_sha256: str


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _is_sha256(value: Any) -> bool:
    return type(value) is str and len(value) == 64 \
        and all(char in "0123456789abcdef" for char in value)


def _is_git_sha(value: Any) -> bool:
    return type(value) is str and len(value) == 40 \
        and all(char in "0123456789abcdef" for char in value)


def _p95(values: tuple[int, ...]) -> int:
    if type(values) is not tuple or not values \
            or any(type(value) is not int or value <= 0 for value in values):
        raise BeliefV2DeadlineEstimateError(
            "V2 deadline percentile population drift")
    ordered = sorted(values)
    return ordered[math.ceil(95 * len(ordered) / 100) - 1]


def _project_training_epoch(wall_nanoseconds: int) -> int:
    if type(wall_nanoseconds) is not int or wall_nanoseconds <= 0:
        raise BeliefV2DeadlineEstimateError(
            "V2 deadline training projection input drift")
    numerator = (wall_nanoseconds * dict(V2_SPLIT_COUNTS)["train"]
                 * TRAINING_PROJECTION_MARGIN_NUMERATOR)
    denominator = (DEADLINE_PROBE_ROUND_COUNT
                   * TRAINING_PROJECTION_MARGIN_DENOMINATOR)
    return (numerator + denominator - 1) // denominator


def deadline_probe_coordinates() -> tuple[V2PreflightCoordinate, ...]:
    """Select 32 out-of-population coordinates with every rank represented."""
    by_rank = {rank: [] for rank in V2_RANKS}
    for row in preflight_coordinates():
        by_rank[row.trump_rank].append(row)
    ranked_by_rank = {}
    for rank, rows in by_rank.items():
        ranked_by_rank[rank] = sorted(rows, key=lambda row: (
            hashlib.sha256(
                f"{DEADLINE_PROBE_SCHEMA}|coordinate|{row.round_seed}".encode(
                    "ascii")).digest(),
            row.round_seed))
    selected = [row for rank in V2_RANKS
                for row in ranked_by_rank[rank][:2]]
    extra_ranks = sorted(V2_RANKS, key=lambda rank: (
        hashlib.sha256(
            f"{DEADLINE_PROBE_SCHEMA}|extra-rank|{rank}".encode(
                "ascii")).digest(), rank))
    for rank in extra_ranks[:DEADLINE_PROBE_ROUND_COUNT - len(selected)]:
        selected.append(ranked_by_rank[rank][2])
    result = tuple(sorted(selected, key=lambda row: (
        row.rank_index, row.round_seed)))
    if len(result) != DEADLINE_PROBE_ROUND_COUNT \
            or len({row.round_seed for row in result}) != len(result) \
            or {row.trump_rank for row in result} != set(V2_RANKS):
        raise BeliefV2DeadlineEstimateError(
            "V2 deadline probe coordinate population drift")
    return result


def deadline_probe_schedule_bytes() -> bytes:
    return canonical_json_bytes({
        "schema": DEADLINE_PROBE_SCHEMA,
        "coordinates": [{
            "lane": row.lane,
            "policy_seeds": list(row.policy_seeds),
            "rank_index": row.rank_index,
            "replicate": row.replicate,
            "round_seed": row.round_seed,
            "trump_rank": row.trump_rank,
        } for row in deadline_probe_coordinates()],
        "reference_worlds_per_decision": REF_C_WORLD_COUNT,
        "reference_worker_count": V2_CAPTURE_LANES,
        "training_repeat_count": DEADLINE_TRAINING_REPEAT_COUNT,
        "training_member_seeds": list(COHORT_SEEDS),
        "one_round_per_probe_batch": True,
        "fresh_example_reconstruction_per_pass": True,
        "training_projection": {
            "train_round_count": dict(V2_SPLIT_COUNTS)["train"],
            "margin_numerator": TRAINING_PROJECTION_MARGIN_NUMERATOR,
            "margin_denominator": TRAINING_PROJECTION_MARGIN_DENOMINATOR,
        },
        "safety_reserve": {
            "minimum_nanoseconds": MINIMUM_SAFETY_RESERVE_NANOSECONDS,
            "epoch_fraction_denominator": (
                SAFETY_RESERVE_FRACTION_DENOMINATOR),
        },
        "captured_rows_retained": False,
        "production_seed_opened": False,
        "pipeline_execution_authorized": False,
    })


def deadline_probe_schedule_sha256() -> str:
    return _sha256(deadline_probe_schedule_bytes())


def _deadline_sampler_seed(decision_key: str) -> int:
    if not _is_sha256(decision_key):
        raise BeliefV2DeadlineEstimateError(
            "V2 deadline probe decision identity drift")
    return int.from_bytes(hashlib.sha256(
        f"{DEADLINE_PROBE_SCHEMA}|ref-c|{decision_key}".encode(
            "ascii")).digest()[:8], "big") & MAX_SEED


def _measure_coordinate(
        coordinate: V2PreflightCoordinate) -> V2DeadlineProbeMeasurement:
    if coordinate not in deadline_probe_coordinates():
        raise BeliefV2DeadlineEstimateError(
            "V2 deadline probe coordinate is not selected")
    _validate_live_run_environment()
    policies = [make_bot(CHAMPION_POLICY, seed=seed)
                for seed in coordinate.policy_seeds]
    manifests = []

    def observe(rnd: Round, seat: int, transcript: PublicTranscriptV1,
                actor_row: bytes) -> None:
        actor, metadata = reopen_actor_row(actor_row)
        batch = capture_ref_c_worlds(
            rnd, seat, transcript,
            sampler_seed=_deadline_sampler_seed(metadata["decision_key"]))
        if batch.actor.canonical_bytes() != actor.canonical_bytes():
            raise BeliefV2DeadlineEstimateError(
                "V2 deadline REF-C actor reconstruction drift")
        manifests.append(batch.manifest_sha256())

    started_monotonic = time.monotonic_ns()
    captured = _capture_with_policies(
        coordinate.round_seed, CHAMPION_POLICY,
        coordinate.policy_seeds, policies, decision_observer=observe,
        trump_rank=coordinate.trump_rank)
    finished_monotonic = time.monotonic_ns()
    if type(captured) is not CapturedBeliefRoundV1 \
            or len(manifests) != len(captured.pairs) \
            or finished_monotonic <= started_monotonic:
        raise BeliefV2DeadlineEstimateError(
            "V2 deadline probe capture/reference drift")
    manifest_sha = _sha256(canonical_json_bytes({
        "schema": "belief-v1-v2-deadline-reference-manifests-v1",
        "round_seed": coordinate.round_seed,
        "manifests": manifests,
    }))
    return V2DeadlineProbeMeasurement(
        coordinate=coordinate,
        worker_process_id=os.getpid(),
        started_monotonic_nanoseconds=started_monotonic,
        finished_monotonic_nanoseconds=finished_monotonic,
        reference_wall_nanoseconds=(
            finished_monotonic - started_monotonic),
        training_pairs=tuple(captured.pairs),
        reference_manifest_population_sha256=manifest_sha)


def _training_probe(
        training_pairs: tuple[tuple[Any, ...], ...], *,
        device: str, repeat: int) \
        -> tuple[int, str, tuple[str, ...], tuple[int, ...]]:
    if type(repeat) is not int or not 0 <= repeat < DEADLINE_TRAINING_REPEAT_COUNT:
        raise BeliefV2DeadlineEstimateError(
            "V2 deadline training repeat drift")
    models = tuple(new_from_scratch_model(seed) for seed in COHORT_SEEDS)
    move_models_to_device(models, device=device)
    optimizers = tuple(new_v2_optimizer(model) for model in models)

    def batches():
        for pairs in training_pairs:
            examples = tuple(build_synthetic_training_example(pair)
                             for pair in pairs)
            yield collate_v2_training_examples(examples)

    synchronize_training_device(device)
    started = time.perf_counter_ns()
    receipts = train_v2_cohort_epoch_stream(
        models, optimizers, batches(), epoch=1, device=device)
    calibration = evaluate_v2_calibration_cohort_stream_nanonats(
        models, batches(), device=device)
    synchronize_training_device(device)
    finished = time.perf_counter_ns()
    state_sha256s = tuple(portable_model_state_sha256(model)
                         for model in models)
    receipt_sha = _sha256(canonical_json_bytes({
        "schema": "belief-v1-v2-deadline-training-receipts-v1",
        "receipts": [receipt.to_dict() for receipt in receipts],
        "calibration_loss_nanonats": list(calibration),
        "state_sha256s": list(state_sha256s),
    }))
    if finished <= started:
        raise BeliefV2DeadlineEstimateError(
            "V2 deadline training clock drift")
    return finished - started, receipt_sha, state_sha256s, calibration


def derive_deadline_estimate_receipt(
        *, execution_git: str, runtime_profile_sha256: str,
        training_device: str,
        preflight_result: dict[str, Any],
        reference_wall_nanoseconds: tuple[int, ...],
        reference_worker_process_ids: tuple[int, ...],
        reference_started_monotonic_nanoseconds: tuple[int, ...],
        reference_finished_monotonic_nanoseconds: tuple[int, ...],
        reference_manifest_population_sha256s: tuple[str, ...],
        training_probe_wall_nanoseconds: tuple[int, ...],
        training_probe_receipt_sha256s: tuple[str, ...]) -> dict[str, Any]:
    """Build and independently re-open one canonical deadline receipt."""
    try:
        preflight_raw = preflight_result_bytes(preflight_result)
    except ValueError as exc:
        raise BeliefV2DeadlineEstimateError(
            "V2 deadline capture preflight refused") from exc
    capture_samples = tuple(
        row["wall_nanoseconds"]
        for lane in preflight_result["lanes"] for row in lane["rounds"])
    try:
        canonical_device = canonical_training_device(training_device)
    except ValueError as exc:
        raise BeliefV2DeadlineEstimateError(
            "V2 deadline training device drift") from exc
    if not _is_git_sha(execution_git) \
            or preflight_result["runtime"]["git_head"] != execution_git \
            or not _is_sha256(runtime_profile_sha256) \
            or training_device != canonical_device \
            or len(capture_samples) < 32 \
            or len(reference_wall_nanoseconds) != DEADLINE_PROBE_ROUND_COUNT \
            or len(reference_worker_process_ids) \
            != DEADLINE_PROBE_ROUND_COUNT \
            or len(reference_started_monotonic_nanoseconds) \
            != DEADLINE_PROBE_ROUND_COUNT \
            or len(reference_finished_monotonic_nanoseconds) \
            != DEADLINE_PROBE_ROUND_COUNT \
            or len(reference_manifest_population_sha256s) \
            != DEADLINE_PROBE_ROUND_COUNT \
            or any(not _is_sha256(value)
                   for value in reference_manifest_population_sha256s) \
            or len(training_probe_wall_nanoseconds) \
            != DEADLINE_TRAINING_REPEAT_COUNT \
            or len(training_probe_receipt_sha256s) \
            != DEADLINE_TRAINING_REPEAT_COUNT \
            or any(not _is_sha256(value)
                   for value in training_probe_receipt_sha256s):
        raise BeliefV2DeadlineEstimateError(
            "V2 deadline estimate identity population drift")
    intervals_by_worker: dict[int, list[tuple[int, int]]] = {}
    for wall, worker, started, finished in zip(
            reference_wall_nanoseconds,
            reference_worker_process_ids,
            reference_started_monotonic_nanoseconds,
            reference_finished_monotonic_nanoseconds, strict=True):
        if type(worker) is not int or worker <= 0 \
                or type(started) is not int or type(finished) is not int \
                or not 0 < started < finished \
                or wall != finished - started:
            raise BeliefV2DeadlineEstimateError(
                "V2 deadline reference worker interval drift")
        intervals_by_worker.setdefault(worker, []).append((started, finished))
    if len(intervals_by_worker) != V2_CAPTURE_LANES:
        raise BeliefV2DeadlineEstimateError(
            "V2 deadline reference worker population drift")
    first_intervals = [min(rows) for rows in intervals_by_worker.values()]
    reference_overlap = min(finished for _, finished in first_intervals) \
        - max(started for started, _ in first_intervals)
    if reference_overlap <= 0:
        raise BeliefV2DeadlineEstimateError(
            "V2 deadline reference workers lack common overlap")
    capture_p95 = _p95(capture_samples)
    reference_p95 = _p95(reference_wall_nanoseconds)
    train_round_count = dict(V2_SPLIT_COUNTS)["train"]
    projected = tuple(_project_training_epoch(wall)
                      for wall in training_probe_wall_nanoseconds)
    training_p95 = _p95(projected)
    reserve = max(
        MINIMUM_SAFETY_RESERVE_NANOSECONDS,
        (training_p95 + SAFETY_RESERVE_FRACTION_DENOMINATOR - 1)
        // SAFETY_RESERVE_FRACTION_DENOMINATOR)
    result = {
        "schema": DEADLINE_ESTIMATE_SCHEMA,
        "execution_git": execution_git,
        "runtime_profile_sha256": runtime_profile_sha256,
        "training_device": training_device,
        "capture_preflight_result_sha256": _sha256(preflight_raw),
        "capture_sample_count": len(capture_samples),
        "capture_wall_nanoseconds": list(capture_samples),
        "capture_p95_wall_nanoseconds": capture_p95,
        "probe_schedule_sha256": deadline_probe_schedule_sha256(),
        "reference_sample_count": len(reference_wall_nanoseconds),
        "reference_wall_nanoseconds": list(reference_wall_nanoseconds),
        "reference_worker_process_ids": list(reference_worker_process_ids),
        "reference_started_monotonic_nanoseconds": list(
            reference_started_monotonic_nanoseconds),
        "reference_finished_monotonic_nanoseconds": list(
            reference_finished_monotonic_nanoseconds),
        "reference_worker_count": len(intervals_by_worker),
        "reference_common_overlap_nanoseconds": reference_overlap,
        "reference_manifest_population_sha256s": list(
            reference_manifest_population_sha256s),
        "reference_p95_wall_nanoseconds": reference_p95,
        "training_probe_round_count": DEADLINE_PROBE_ROUND_COUNT,
        "training_probe_repeat_count": DEADLINE_TRAINING_REPEAT_COUNT,
        "training_probe_wall_nanoseconds": list(
            training_probe_wall_nanoseconds),
        "training_probe_receipt_sha256s": list(
            training_probe_receipt_sha256s),
        "training_epoch_sample_count": len(projected),
        "training_epoch_wall_estimate_nanoseconds": list(projected),
        "training_epoch_p95_wall_nanoseconds": training_p95,
        "training_epoch_projection": {
            "train_round_count": train_round_count,
            "one_probe_round_per_batch": True,
            "production_may_pack_rounds": True,
            "margin_numerator": TRAINING_PROJECTION_MARGIN_NUMERATOR,
            "margin_denominator": TRAINING_PROJECTION_MARGIN_DENOMINATOR,
        },
        "safety_reserve_nanoseconds": reserve,
        "captured_rows_retained": False,
        "sampled_worlds_retained": False,
        "model_or_loss_artifacts_retained": False,
        "production_seed_opened": False,
        "test_split_opened": False,
        "pipeline_execution_authorized": False,
        "retry_authorized": False,
        "strength_claim_authorized": False,
        "deployment_authorized": False,
    }
    validate_deadline_estimate_receipt(result)
    return result


def validate_deadline_estimate_receipt(receipt: dict[str, Any]) -> None:
    keys = {
        "schema", "execution_git", "runtime_profile_sha256",
        "training_device",
        "capture_preflight_result_sha256", "capture_sample_count",
        "capture_wall_nanoseconds", "capture_p95_wall_nanoseconds",
        "probe_schedule_sha256", "reference_sample_count",
        "reference_wall_nanoseconds",
        "reference_worker_process_ids",
        "reference_started_monotonic_nanoseconds",
        "reference_finished_monotonic_nanoseconds",
        "reference_worker_count", "reference_common_overlap_nanoseconds",
        "reference_manifest_population_sha256s",
        "reference_p95_wall_nanoseconds", "training_probe_round_count",
        "training_probe_repeat_count", "training_probe_wall_nanoseconds",
        "training_probe_receipt_sha256s", "training_epoch_sample_count",
        "training_epoch_wall_estimate_nanoseconds",
        "training_epoch_p95_wall_nanoseconds", "training_epoch_projection",
        "safety_reserve_nanoseconds", "captured_rows_retained",
        "sampled_worlds_retained", "model_or_loss_artifacts_retained",
        "production_seed_opened", "test_split_opened",
        "pipeline_execution_authorized", "retry_authorized",
        "strength_claim_authorized", "deployment_authorized",
    }
    if type(receipt) is not dict:
        raise BeliefV2DeadlineEstimateError(
            "V2 deadline estimate schema/authority drift")
    try:
        canonical_device = canonical_training_device(
            receipt.get("training_device"))
    except (TypeError, ValueError) as exc:
        raise BeliefV2DeadlineEstimateError(
            "V2 deadline estimate training device drift") from exc
    if set(receipt) != keys \
            or receipt.get("schema") != DEADLINE_ESTIMATE_SCHEMA \
            or not _is_git_sha(receipt.get("execution_git")) \
            or receipt.get("training_device") != canonical_device \
            or any(not _is_sha256(receipt.get(key)) for key in (
                "runtime_profile_sha256", "capture_preflight_result_sha256",
                "probe_schedule_sha256")) \
            or receipt["probe_schedule_sha256"] \
            != deadline_probe_schedule_sha256() \
            or any(receipt.get(key) is not False for key in (
                "captured_rows_retained", "sampled_worlds_retained",
                "model_or_loss_artifacts_retained", "production_seed_opened",
                "test_split_opened", "pipeline_execution_authorized",
                "retry_authorized", "strength_claim_authorized",
                "deployment_authorized")):
        raise BeliefV2DeadlineEstimateError(
            "V2 deadline estimate schema/authority drift")
    try:
        capture = tuple(receipt["capture_wall_nanoseconds"])
        reference = tuple(receipt["reference_wall_nanoseconds"])
        workers = tuple(receipt["reference_worker_process_ids"])
        started = tuple(receipt["reference_started_monotonic_nanoseconds"])
        finished = tuple(receipt["reference_finished_monotonic_nanoseconds"])
        training = tuple(receipt["training_probe_wall_nanoseconds"])
        projected = tuple(receipt["training_epoch_wall_estimate_nanoseconds"])
        reference_hashes = tuple(
            receipt["reference_manifest_population_sha256s"])
        training_hashes = tuple(receipt["training_probe_receipt_sha256s"])
    except (KeyError, TypeError) as exc:
        raise BeliefV2DeadlineEstimateError(
            "V2 deadline estimate sample population drift") from exc
    projection = receipt["training_epoch_projection"]
    train_round_count = dict(V2_SPLIT_COUNTS)["train"]
    expected_projected = tuple(_project_training_epoch(wall)
                               for wall in training)
    expected_reserve = max(
        MINIMUM_SAFETY_RESERVE_NANOSECONDS,
        (_p95(expected_projected) + SAFETY_RESERVE_FRACTION_DENOMINATOR - 1)
        // SAFETY_RESERVE_FRACTION_DENOMINATOR)
    intervals_by_worker: dict[int, list[tuple[int, int]]] = {}
    for wall, worker, begin, end in zip(
            reference, workers, started, finished, strict=True):
        if type(worker) is not int or worker <= 0 \
                or type(begin) is not int or type(end) is not int \
                or not 0 < begin < end or wall != end - begin:
            raise BeliefV2DeadlineEstimateError(
                "V2 deadline reference interval reconstruction drift")
        intervals_by_worker.setdefault(worker, []).append((begin, end))
    first_intervals = [min(rows) for rows in intervals_by_worker.values()]
    overlap = (min(end for _, end in first_intervals)
               - max(begin for begin, _ in first_intervals)) \
        if first_intervals else 0
    if len(capture) != receipt["capture_sample_count"] \
            or len(capture) < 32 \
            or _p95(capture) != receipt["capture_p95_wall_nanoseconds"] \
            or len(reference) != DEADLINE_PROBE_ROUND_COUNT \
            or receipt["reference_sample_count"] != len(reference) \
            or _p95(reference) != receipt["reference_p95_wall_nanoseconds"] \
            or len(reference_hashes) != len(reference) \
            or any(not _is_sha256(value) for value in reference_hashes) \
            or len(workers) != len(reference) \
            or len(started) != len(reference) \
            or len(finished) != len(reference) \
            or len(intervals_by_worker) != V2_CAPTURE_LANES \
            or receipt["reference_worker_count"] != V2_CAPTURE_LANES \
            or overlap <= 0 \
            or receipt["reference_common_overlap_nanoseconds"] != overlap \
            or len(training) != DEADLINE_TRAINING_REPEAT_COUNT \
            or receipt["training_probe_round_count"] \
            != DEADLINE_PROBE_ROUND_COUNT \
            or receipt["training_probe_repeat_count"] != len(training) \
            or len(training_hashes) != len(training) \
            or any(not _is_sha256(value) for value in training_hashes) \
            or len(set(training_hashes)) != 1 \
            or projected != expected_projected \
            or receipt["training_epoch_sample_count"] != len(projected) \
            or receipt["training_epoch_p95_wall_nanoseconds"] \
            != _p95(projected) \
            or projection != {
                "train_round_count": train_round_count,
                "one_probe_round_per_batch": True,
                "production_may_pack_rounds": True,
                "margin_numerator": TRAINING_PROJECTION_MARGIN_NUMERATOR,
                "margin_denominator": TRAINING_PROJECTION_MARGIN_DENOMINATOR,
            } \
            or receipt["safety_reserve_nanoseconds"] != expected_reserve:
        raise BeliefV2DeadlineEstimateError(
            "V2 deadline estimate reconstruction drift")


def deadline_estimate_receipt_bytes(receipt: dict[str, Any]) -> bytes:
    validate_deadline_estimate_receipt(receipt)
    return canonical_json_bytes(receipt)


def run_deadline_estimate_preflight(
        *, execution_git: str, runtime: V2RuntimeProfileV1,
        preflight_result: dict[str, Any], training_device: str) \
        -> dict[str, Any]:
    """Run the bounded probe and return only its exact timing receipt."""
    coordinates = deadline_probe_coordinates()
    with concurrent.futures.ProcessPoolExecutor(
            max_workers=V2_CAPTURE_LANES) as executor:
        measurements = tuple(executor.map(_measure_coordinate, coordinates))
    if tuple(row.coordinate for row in measurements) != coordinates:
        raise BeliefV2DeadlineEstimateError(
            "V2 deadline probe worker order drift")
    training_pairs = tuple(row.training_pairs for row in measurements)
    # Warm the exact kernel and allocator before the two retained probes.
    _training_probe(training_pairs, device=training_device, repeat=0)
    retained = tuple(_training_probe(
        training_pairs, device=training_device, repeat=repeat)
        for repeat in range(DEADLINE_TRAINING_REPEAT_COUNT))
    if retained[0][1:] != retained[1][1:]:
        raise BeliefV2DeadlineEstimateError(
            "V2 deadline training semantic repeatability drift")
    runtime_sha = _sha256(canonical_json_bytes(runtime.to_dict()))
    result = derive_deadline_estimate_receipt(
        execution_git=execution_git,
        runtime_profile_sha256=runtime_sha,
        training_device=training_device,
        preflight_result=preflight_result,
        reference_wall_nanoseconds=tuple(
            row.reference_wall_nanoseconds for row in measurements),
        reference_worker_process_ids=tuple(
            row.worker_process_id for row in measurements),
        reference_started_monotonic_nanoseconds=tuple(
            row.started_monotonic_nanoseconds for row in measurements),
        reference_finished_monotonic_nanoseconds=tuple(
            row.finished_monotonic_nanoseconds for row in measurements),
        reference_manifest_population_sha256s=tuple(
            row.reference_manifest_population_sha256 for row in measurements),
        training_probe_wall_nanoseconds=tuple(row[0] for row in retained),
        training_probe_receipt_sha256s=tuple(row[1] for row in retained))
    # Drop the only in-memory privileged and model artifacts before return.
    del measurements, training_pairs, retained
    return result
