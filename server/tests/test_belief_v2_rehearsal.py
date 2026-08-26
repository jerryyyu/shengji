"""Population and authority contract for the full-DAG rehearsal."""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
from dataclasses import replace
import hashlib
import io
import json
import multiprocessing
import os
from pathlib import Path
import subprocess
import time

import pytest

import shengji.rl.belief_v2_calibration_controller as CALIBRATION_STAGE
import shengji.rl.belief_v2_capture as V2_CAPTURE
import shengji.rl.belief_v2_controller as V2_CONTROLLER
import shengji.rl.belief_v2_device_controller as DEVICE_STAGE
import shengji.rl.belief_v2_human_controller as HUMAN_STAGE
import shengji.rl.belief_v2_human_reference_controller as HUMAN_REF_STAGE
import shengji.rl.belief_v2_input_index_controller as INPUT_INDEX_STAGE
import shengji.rl.belief_v2_reference as V2_REFERENCE
import shengji.rl.belief_v2_rehearsal as REHEARSAL
import shengji.rl.belief_v2_result as V2_RESULT
import shengji.rl.belief_v2_schedule as V2_SCHEDULE
import shengji.rl.belief_v2_scoring_controller as SCORING_STAGE
import shengji.rl.belief_v2_streaming_inputs as STREAMING_INPUTS
import shengji.rl.belief_v2_statistics as V2_STATISTICS
import shengji.rl.belief_v2_tensor_cache_controller as CACHE_STAGE
import shengji.rl.belief_v2_parallel_cache as PARALLEL_CACHE
import shengji.rl.belief_v2_parallel_inputs as PARALLEL_INPUTS
import shengji.rl.belief_v2_terminal_controller as TERMINAL_STAGE
import shengji.rl.belief_v2_training_controller as TRAINING_STAGE
import shengji.rl.belief_v2_training_inputs as TRAINING_INPUTS
from shengji.rl.belief_artifacts import publish_exclusive_bytes, stable_read_bytes
from shengji.rl.belief_contract import canonical_json_bytes
from shengji.rl.belief_v2_accelerator import (
    available_training_accelerators,
    build_training_device_profile,
)
from shengji.rl.belief_v2_calibration_controller import (
    reopen_v2_calibration_selection,
    run_v2_calibration_selection,
)
from shengji.rl.belief_v2_controller import (
    BeliefV2ControllerError,
    reopen_capture_lane,
    run_capture_lane,
    run_reference_lane,
)
from shengji.rl.belief_v2_device_controller import (
    reopen_device_qualification,
    run_device_qualification,
)
from shengji.rl.belief_v2_device_qualification import (
    qualification_protocol_sha256,
)
from shengji.rl.belief_v2_human_controller import (
    reopen_human_group_manifest,
    run_human_group_capture,
)
from shengji.rl.belief_v2_human_reference_controller import (
    run_human_reference_group,
)
from shengji.rl.belief_v2_input_index_controller import (
    reopen_training_input_index,
    run_training_input_index,
)
from shengji.rl.belief_v2_execution_identity import (
    build_runtime_profile,
    build_source_bindings,
    configure_numerical_runtime,
    source_manifest_sha256,
)
from shengji.rl.belief_v2_freeze import (
    REVIEW_PREFIX,
    build_pipeline_admission,
    expected_execution_review_claim,
)
from shengji.rl.belief_v2_progress import (
    PROGRESS_PREFIX,
    PROGRESS_SCHEMA,
    V2ProgressReporter,
)
from shengji.rl.belief_v2_tensor_cache_controller import (
    reopen_training_tensor_cache,
    run_training_tensor_cache,
)
from shengji.rl.belief_v2_parallel_cache import (
    build_parallel_tensor_cache,
    parallel_cache_build_topology,
    parallel_cache_worker_count,
)
from shengji.rl.belief_v2_parallel_inputs import (
    parallel_input_worker_count,
)
from shengji.rl.belief_v2_streaming_inputs import V2ArtifactRoundLoader
from shengji.rl.belief_v2_streaming_training import (
    iter_streaming_calibration_batches,
    iter_streaming_training_batches,
)
from shengji.rl.belief_v2_tensor_cache import (
    build_label_overlay,
    build_tensor_cache,
    cached_batch_factory,
)
from shengji.rl.belief_v2_training import label_control_batch_from_natural
from shengji.rl.belief_v2_training_controller import (
    reopen_training_cohort,
    run_training_cohort,
)
from tests.test_belief_v2_controller import _admission, _cpu_only_freeze

from shengji.rl.belief_v2_protocol import (
    V1_B2_SEED_END,
    V1_B2_SEED_START,
    V2_CAPTURE_LANES,
    V2_RANKS,
    v2_round_coordinates,
)
from shengji.rl.belief_v2_rehearsal import (
    BeliefV2RehearsalError,
    REHEARSAL_HUMAN_SPLIT_COUNTS,
    REHEARSAL_RECEIPT_SCHEMA,
    REHEARSAL_ROUND_COUNT,
    REHEARSAL_ROUNDS_PER_RANK,
    REHEARSAL_SPLIT_COUNTS,
    REHEARSAL_SPLIT_COUNTS_PER_RANK,
    REHEARSAL_PROGRESS_STAGES,
    REHEARSAL_TRAIN_BATCH_DECISION_CAP,
    REHEARSAL_STAGE_ORDER,
    rehearsal_lane_coordinates,
    rehearsal_human_source_bytes,
    rehearsal_policy_seeds,
    rehearsal_profile_bytes,
    rehearsal_profile_dict,
    rehearsal_profile_sha256,
    rehearsal_round_coordinates,
    rehearsal_v2_coordinates,
    rehearsal_v2_lane_coordinates,
    rehearsal_v2_policy_seeds,
    rehearsal_v2_round_coordinate,
    validate_rehearsal_coordinates,
    validate_rehearsal_receipt,
)
from shengji.rl.belief_v2_human_inventory import (
    H0_GROUP_SCHEMA,
    build_h0_group_split,
    build_h0_inventory,
    group_split_bytes,
    inventory_bytes,
    validate_h0_group_split,
    validate_h0_inventory,
)
from shengji.rl.belief_v2_terminal_controller import (
    reopen_v2_terminal,
    run_v2_terminal,
)


RUN_FULL_REHEARSAL = (
    os.environ.get("SHENGJI_BELIEF_V2_FULL_DAG_REHEARSAL") == "1")
CACHE_BENCHMARK_ROOT = os.environ.get(
    "SHENGJI_BELIEF_V2_CACHE_BENCHMARK_ROOT")


def _assert_cache_benchmark_receipts(
        expected: dict[str, object], serial: dict[str, object],
        parallel: dict[str, object]) -> None:
    """Bind the portable population and exact same-host cache bytes.

    Torch tensor files are not promised byte-identical across architectures,
    so a Mini-generated manifest cannot be the expected x86 manifest.  The
    archived stage still pins the platform-independent population dimensions;
    the freshly built serial arm is the same-host byte oracle for the parallel
    arm.
    """
    portable_keys = ("batch_count", "decision_count", "artifact_bytes")
    assert {key: serial[key] for key in portable_keys} \
        == {key: expected[key] for key in portable_keys}
    assert parallel == serial


_PRODUCTION_PARALLEL_CACHE_INITIALIZER = PARALLEL_CACHE._initialize_worker
_PRODUCTION_PARALLEL_INPUT_INITIALIZER = PARALLEL_INPUTS._initialize_worker


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ("git", *args), cwd=repo, check=True, capture_output=True,
        text=True).stdout.strip()


def _fixture_h0(tmp_path: Path):
    source_root = tmp_path / "human-sources"
    source_root.mkdir()
    sources = []
    manifest_rows = []
    for index in range(30):
        raw = rehearsal_human_source_bytes(index)
        path = source_root / f"source-{index:02d}.jsonl"
        path.write_bytes(raw)
        sources.append(path)
        manifest_rows.append(
            f"{hashlib.sha256(raw).hexdigest()}  {path.name}\n")
    manifest = tmp_path / "human-source-manifest.txt"
    manifest.write_text("".join(manifest_rows), encoding="ascii")
    inventory = build_h0_inventory(
        source_manifest=manifest, source_paths=sources)
    split = build_h0_group_split(inventory)
    for path in (*sources, manifest):
        path.chmod(0o400)
    return tuple(sources), inventory, split


def _rehearsal_freeze(root: Path, inventory, split):
    base = _cpu_only_freeze(root)
    split_counts = {
        name: row["group_count"] for name, row in split["splits"].items()}
    decision_counts = {name: sum(
        group["human_play_decisions"] for group in inventory["groups"]
        if group["group_digest"] in set(split["splits"][name][
            "group_digests"])) for name in split_counts}
    return replace(
        base,
        h0_inventory_sha256=hashlib.sha256(
            inventory_bytes(inventory)).hexdigest(),
        h0_source_manifest_sha256=inventory["source_manifest_sha256"],
        h0_source_digest_population_sha256=inventory[
            "source_digest_population_sha256"],
        human_group_split_sha256=hashlib.sha256(
            group_split_bytes(split, inventory=inventory)).hexdigest(),
        human_group_count=inventory["group_count"],
        human_train_group_count=split_counts["train"],
        human_calibration_group_count=split_counts["calibration"],
        human_test_group_count=split_counts["test"],
        human_complete_round_count=inventory["complete_rounds"],
        human_eligible_decision_count=inventory["human_play_decisions"],
        human_train_eligible_decision_count=decision_counts["train"],
        human_calibration_eligible_decision_count=(
            decision_counts["calibration"]),
        human_test_eligible_decision_count=decision_counts["test"])


def _patch_rehearsal_population(monkeypatch) -> None:
    split_counts = dict(REHEARSAL_SPLIT_COUNTS)
    monkeypatch.setattr(
        V2_CONTROLLER, "v2_lane_coordinates",
        rehearsal_v2_lane_coordinates)
    monkeypatch.setattr(
        V2_CAPTURE, "v2_round_coordinate", rehearsal_v2_round_coordinate)
    monkeypatch.setattr(
        V2_CAPTURE, "v2_policy_seeds", rehearsal_v2_policy_seeds)
    monkeypatch.setattr(
        V2_REFERENCE, "v2_round_coordinate", rehearsal_v2_round_coordinate)
    monkeypatch.setattr(
        V2_REFERENCE, "v2_policy_seeds", rehearsal_v2_policy_seeds)
    monkeypatch.setattr(
        SCORING_STAGE, "v2_policy_seeds", rehearsal_v2_policy_seeds)
    monkeypatch.setattr(
        STREAMING_INPUTS, "v2_lane_coordinates",
        rehearsal_v2_lane_coordinates)
    monkeypatch.setattr(
        PARALLEL_INPUTS, "v2_lane_coordinates",
        rehearsal_v2_lane_coordinates)
    monkeypatch.setattr(
        PARALLEL_INPUTS, "_initialize_worker",
        _rehearsal_parallel_input_initializer)
    monkeypatch.setattr(
        INPUT_INDEX_STAGE, "V2_SPLIT_COUNTS", REHEARSAL_SPLIT_COUNTS)
    monkeypatch.setattr(
        CALIBRATION_STAGE, "v2_round_coordinates",
        rehearsal_v2_coordinates)
    monkeypatch.setattr(
        TERMINAL_STAGE, "v2_round_coordinates", rehearsal_v2_coordinates)
    monkeypatch.setattr(
        TERMINAL_STAGE, "V2_ROUND_COUNT", REHEARSAL_ROUND_COUNT)
    monkeypatch.setattr(
        TERMINAL_STAGE, "V2_SPLIT_COUNTS", REHEARSAL_SPLIT_COUNTS)
    monkeypatch.setattr(
        V2_RESULT, "V2_ROUND_COUNT", REHEARSAL_ROUND_COUNT)
    monkeypatch.setattr(
        V2_RESULT, "V2_SPLIT_COUNTS", REHEARSAL_SPLIT_COUNTS)
    monkeypatch.setattr(
        V2_SCHEDULE, "TRAIN_BATCH_DECISION_CAP",
        REHEARSAL_TRAIN_BATCH_DECISION_CAP)
    monkeypatch.setattr(
        V2_STATISTICS, "RANK_CALIBRATION_MINIMUM_ROUNDS", 1)
    # The rehearsal checks that both independently replayed calibration
    # populations are complete and scoreable.  Their statistical equivalence
    # threshold is a production-power question, not an operational smoke gate.
    real_stability = CALIBRATION_STAGE.v2_reference_replicates_are_stable
    observed = []

    def record_stability(*args, **kwargs):
        observed.append(real_stability(*args, **kwargs))
        return True

    monkeypatch.setattr(
        CALIBRATION_STAGE, "v2_reference_replicates_are_stable",
        record_stability)
    monkeypatch.setattr(
        CALIBRATION_STAGE, "_rehearsal_observed_stability", observed,
        raising=False)
    assert split_counts == {"train": 75, "calibration": 16, "test": 13}


def _restore_parent_worker_population(monkeypatch) -> None:
    """Reinstall direct-import seams after a spawned worker pool exits."""
    monkeypatch.setattr(
        V2_CONTROLLER, "v2_lane_coordinates",
        rehearsal_v2_lane_coordinates)
    monkeypatch.setattr(
        V2_CONTROLLER, "v2_policy_seeds", rehearsal_v2_policy_seeds)
    monkeypatch.setattr(
        V2_CAPTURE, "v2_round_coordinate", rehearsal_v2_round_coordinate)
    monkeypatch.setattr(
        V2_CAPTURE, "v2_policy_seeds", rehearsal_v2_policy_seeds)
    monkeypatch.setattr(
        V2_REFERENCE, "v2_round_coordinate", rehearsal_v2_round_coordinate)
    monkeypatch.setattr(
        V2_REFERENCE, "v2_policy_seeds", rehearsal_v2_policy_seeds)
    monkeypatch.setattr(
        SCORING_STAGE, "v2_policy_seeds", rehearsal_v2_policy_seeds)
    monkeypatch.setattr(
        STREAMING_INPUTS, "v2_lane_coordinates",
        rehearsal_v2_lane_coordinates)
    monkeypatch.setattr(
        V2_SCHEDULE, "TRAIN_BATCH_DECISION_CAP",
        REHEARSAL_TRAIN_BATCH_DECISION_CAP)


def _patch_stage_gates(monkeypatch) -> None:
    for module in (
            V2_CONTROLLER, HUMAN_STAGE, INPUT_INDEX_STAGE, CACHE_STAGE,
            DEVICE_STAGE, HUMAN_REF_STAGE, TRAINING_STAGE,
            CALIBRATION_STAGE, TERMINAL_STAGE):
        monkeypatch.setattr(module, "_stage_gate", lambda **_kwargs: None)


def _reporter(stage: str, worker: str, rows: list[dict]):
    stream = io.StringIO()
    real = V2ProgressReporter(stage=stage, worker=worker, stream=stream)

    def update(*args):
        real.update(*args)
        rows.append(json.loads(
            stream.getvalue().splitlines()[-1].removeprefix(
                PROGRESS_PREFIX)))

    return update


def _group_digest(path: Path) -> str:
    source_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashlib.sha256(
        f"{H0_GROUP_SCHEMA}|{source_sha}".encode("ascii")).hexdigest()


def _artifact_population(root: Path) -> list[dict]:
    return [{
        "path": path.relative_to(root).as_posix(),
        "byte_count": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    } for path in sorted(root.rglob("*")) if path.is_file()]


def _apply_rehearsal_process_overrides() -> None:
    """Install the opt-in population inside a fresh worker process."""
    configure_numerical_runtime()
    V2_CONTROLLER.v2_lane_coordinates = rehearsal_v2_lane_coordinates
    V2_CONTROLLER.v2_policy_seeds = rehearsal_v2_policy_seeds
    V2_CAPTURE.v2_round_coordinate = rehearsal_v2_round_coordinate
    V2_CAPTURE.v2_policy_seeds = rehearsal_v2_policy_seeds
    V2_REFERENCE.v2_round_coordinate = rehearsal_v2_round_coordinate
    V2_REFERENCE.v2_policy_seeds = rehearsal_v2_policy_seeds
    SCORING_STAGE.v2_policy_seeds = rehearsal_v2_policy_seeds
    STREAMING_INPUTS.v2_lane_coordinates = rehearsal_v2_lane_coordinates
    V2_SCHEDULE.TRAIN_BATCH_DECISION_CAP = (
        REHEARSAL_TRAIN_BATCH_DECISION_CAP)
    for module in (
            V2_CONTROLLER, HUMAN_STAGE, INPUT_INDEX_STAGE, CACHE_STAGE,
            DEVICE_STAGE, HUMAN_REF_STAGE, TRAINING_STAGE,
            CALIBRATION_STAGE, TERMINAL_STAGE):
        module._stage_gate = lambda **_kwargs: None


def _rehearsal_parallel_cache_initializer(*args) -> None:
    """Install disposable coordinates before the production worker opens."""
    _apply_rehearsal_process_overrides()
    _PRODUCTION_PARALLEL_CACHE_INITIALIZER(*args)


def _rehearsal_parallel_input_initializer(*args) -> None:
    """Install disposable coordinates before the input worker opens."""
    _apply_rehearsal_process_overrides()
    PARALLEL_INPUTS.v2_lane_coordinates = rehearsal_v2_lane_coordinates
    _PRODUCTION_PARALLEL_INPUT_INITIALIZER(*args)


def _capture_process(args):
    _apply_rehearsal_process_overrides()
    root, freeze, admission, lane, review_marker = args
    rows = []
    manifest = run_capture_lane(
        root, freeze, admission, repo=Path("/unused"), lane=lane,
        review_marker=review_marker,
        progress=_reporter("capture", f"lane-{lane:02d}", rows))
    return manifest, rows


def _human_capture_process(args):
    _apply_rehearsal_process_overrides()
    root, freeze, admission, source_path, inventory, group_split, marker = args
    rows = []
    manifest = run_human_group_capture(
        root, freeze, admission, repo=Path("/unused"),
        source_path=source_path, inventory=inventory,
        group_split=group_split, review_marker=marker,
        progress=_reporter("human-capture", source_path.name, rows))
    return manifest, rows


def _reference_process(args):
    _apply_rehearsal_process_overrides()
    (kind, root, freeze, admission, lane, source_path, inventory,
     group_split, replicate, marker) = args
    rows = []
    if kind == "synthetic":
        manifest = run_reference_lane(
            root, freeze, admission, repo=Path("/unused"), lane=lane,
            review_marker=marker,
            progress=_reporter("reference", f"lane-{lane:02d}", rows))
    else:
        manifest = run_human_reference_group(
            root, freeze, admission, repo=Path("/unused"),
            source_path=source_path, inventory=inventory,
            group_split=group_split, replicate=replicate,
            review_marker=marker,
            progress=_reporter("human-reference", replicate, rows))
    return manifest, rows


def _process_map(function, tasks, *, max_workers):
    # Each controller executes in a clean spawned process and explicitly
    # installs the disposable rehearsal population.  This matches the
    # production resource shape without weakening production seed guards.
    with ProcessPoolExecutor(
            max_workers=max_workers,
            mp_context=multiprocessing.get_context("spawn")) as executor:
        return tuple(executor.map(function, tasks))


def test_rehearsal_population_is_balanced_disjoint_and_lane_complete():
    rows = rehearsal_round_coordinates()
    production = {row.round_seed for row in v2_round_coordinates()}

    assert len(rows) == REHEARSAL_ROUND_COUNT == 104
    assert len({row.round_seed for row in rows}) == len(rows)
    assert not production.intersection(row.round_seed for row in rows)
    assert all(not V1_B2_SEED_START <= row.round_seed <= V1_B2_SEED_END
               for row in rows)
    assert {row.trump_rank for row in rows} == set(V2_RANKS)
    assert all(sum(row.trump_rank == rank for row in rows)
               == REHEARSAL_ROUNDS_PER_RANK
               for rank in V2_RANKS)
    assert {split: sum(row.split == split for row in rows)
            for split, _ in REHEARSAL_SPLIT_COUNTS} \
        == dict(REHEARSAL_SPLIT_COUNTS)
    rank_split_counts = [{
        split: sum(row.trump_rank == rank and row.split == split
                   for row in rows)
        for split, _ in REHEARSAL_SPLIT_COUNTS_PER_RANK}
        for rank in V2_RANKS]
    assert rank_split_counts.count(
        dict(REHEARSAL_SPLIT_COUNTS_PER_RANK)) == 10
    assert rank_split_counts.count(
        {"train": 5, "calibration": 2, "test": 1}) == 3
    assert [len(rehearsal_lane_coordinates(lane))
            for lane in range(V2_CAPTURE_LANES)] \
        == [7] * 8 + [6] * 8
    assert all(any(row.split == "calibration"
                   for row in rehearsal_lane_coordinates(lane))
               for lane in range(V2_CAPTURE_LANES))
    assert all(len(set(rehearsal_policy_seeds(row))) == 4
               for row in rows)
    typed = rehearsal_v2_coordinates()
    assert len(typed) == len(rows)
    assert all(rehearsal_v2_round_coordinate(
        row.trump_rank, row.rank_ordinal) == row for row in typed)
    assert tuple(row for lane in range(V2_CAPTURE_LANES)
                 for row in rehearsal_v2_lane_coordinates(lane)) == typed
    assert all(len(set(rehearsal_v2_policy_seeds(row))) == 4
               for row in typed)


def test_rehearsal_profile_is_canonical_and_authorizes_nothing():
    profile = rehearsal_profile_dict()
    assert rehearsal_profile_bytes().endswith(b"\n")
    assert profile["smoke_only"] is True
    assert profile["scientific_evidence"] is False
    assert profile["reference_world_count"] == 256
    assert profile["training_batch_decision_cap"] == 128
    assert profile["human_fixture_population"]["split_counts"] \
        == dict(REHEARSAL_HUMAN_SPLIT_COUNTS)
    assert not any(profile["authority"].values())


def test_rehearsal_receipt_validates_phase_local_eta_not_stage_elapsed():
    rows = [{
        "schema": PROGRESS_SCHEMA,
        "stage": "calibration",
        "worker": "all-cohorts",
        "phase": phase,
        "completed_units": completed,
        "total_units": total,
        "percent_basis_points": completed * 10_000 // total,
        "elapsed_nanoseconds": elapsed,
        "estimated_remaining_nanoseconds": remaining,
        "status": "complete" if completed == total else "running",
        "outcome_blind": True,
        "evidence_artifact": False,
        "strength_claim_authorized": False,
        "deployment_authorized": False,
    } for phase, completed, total, elapsed, remaining in (
        ("reopen-checkpoints", 0, 1, 0, None),
        ("reopen-checkpoints", 1, 1, 100, 0),
        ("score-rounds", 0, 100, 100, None),
        ("score-rounds", 10, 100, 200, 900),
    )]

    def receipt(progress_rows):
        return {
            "row_count": len(progress_rows),
            "worker_count": 1,
            "phase_count": 2,
            "population_sha256": hashlib.sha256(
                canonical_json_bytes(progress_rows)).hexdigest(),
            "rows": progress_rows,
        }

    REHEARSAL._validate_receipt_progress(receipt(rows), eligible=False)
    broken = [dict(row) for row in rows]
    broken[-1]["estimated_remaining_nanoseconds"] = 1_800
    with pytest.raises(BeliefV2RehearsalError,
                       match="progress row drift"):
        REHEARSAL._validate_receipt_progress(
            receipt(broken), eligible=False)


def test_rehearsal_receipt_refuses_missing_stage_source_and_authority_drift():
    digest = "a" * 64
    profile = {"runtime": "test"}
    progress_rows = [{
        "schema": PROGRESS_SCHEMA,
        "stage": stage,
        "worker": "worker",
        "phase": "complete",
        "completed_units": 1,
        "total_units": 1,
        "percent_basis_points": 10_000,
        "elapsed_nanoseconds": index,
        "estimated_remaining_nanoseconds": 0,
        "status": "complete",
        "outcome_blind": True,
        "evidence_artifact": False,
        "strength_claim_authorized": False,
        "deployment_authorized": False,
    } for index, stage in enumerate(REHEARSAL_PROGRESS_STAGES)]
    receipt = {
        "schema": REHEARSAL_RECEIPT_SCHEMA,
        "smoke_only": True,
        "scientific_evidence": False,
        "profile_sha256": rehearsal_profile_sha256(),
        "freeze_sha256": digest,
        "admission_sha256": digest,
        "source_identity": {
            "execution_git": "b" * 40,
            "checkout_clean": True,
            "source_manifest_sha256": digest,
        },
        "runtime_identity": {
            "profile": profile,
            "profile_sha256": hashlib.sha256(
                canonical_json_bytes(profile)).hexdigest(),
        },
        "device_identity": {
            "training_device": "cpu",
            "qualification_plan_sha256": digest,
            "qualification_result_sha256": digest,
        },
        "synthetic_round_count": REHEARSAL_ROUND_COUNT,
        "human_fixture_source_count": 30,
        "reference_world_count": 256,
        "cohort_epoch_counts": {
            f"cohort-{index}": 1 for index in range(4)},
        "stage_order": list(REHEARSAL_STAGE_ORDER),
        "progress": {
            "row_count": len(progress_rows),
            "worker_count": len(progress_rows),
            "phase_count": len(progress_rows),
            "rows": progress_rows,
            "population_sha256": hashlib.sha256(
                canonical_json_bytes(progress_rows)).hexdigest(),
        },
        "artifact_count": 1,
        "artifact_population_sha256": digest,
        "terminal_manifest_sha256": digest,
        "stability_observations": [],
        "development_resume_used": False,
        "production_freeze_review_eligible": True,
        "retry_count": 0,
        "drop_count": 0,
        "authority": rehearsal_profile_dict()["authority"],
    }
    validate_rehearsal_receipt(receipt)
    with pytest.raises(BeliefV2RehearsalError, match="identity drift"):
        validate_rehearsal_receipt({
            **receipt, "stage_order": receipt["stage_order"][:-1]})
    with pytest.raises(BeliefV2RehearsalError, match="source identity"):
        validate_rehearsal_receipt({
            **receipt,
            "source_identity": {
                **receipt["source_identity"], "checkout_clean": False}})
    with pytest.raises(BeliefV2RehearsalError, match="identity drift"):
        validate_rehearsal_receipt({
            **receipt,
            "authority": {**receipt["authority"], "strength_claim": True}})
    shortened_rows = progress_rows[:-1]
    with pytest.raises(BeliefV2RehearsalError, match="progress coverage"):
        validate_rehearsal_receipt({
            **receipt,
            "progress": {
                **receipt["progress"],
                "row_count": len(shortened_rows),
                "worker_count": len(shortened_rows),
                "phase_count": len(shortened_rows),
                "rows": shortened_rows,
                "population_sha256": hashlib.sha256(
                    canonical_json_bytes(shortened_rows)).hexdigest(),
            },
        })
    drifted_rows = [*progress_rows]
    drifted_rows[0] = {
        **drifted_rows[0], "strength_claim_authorized": True}
    with pytest.raises(BeliefV2RehearsalError, match="progress row"):
        validate_rehearsal_receipt({
            **receipt,
            "progress": {
                **receipt["progress"],
                "rows": drifted_rows,
                "population_sha256": hashlib.sha256(
                    canonical_json_bytes(drifted_rows)).hexdigest(),
            },
        })


def test_rehearsal_human_fixtures_build_real_24_3_3_h0_split(tmp_path):
    sources, inventory, split = _fixture_h0(tmp_path)
    validate_h0_inventory(inventory)
    validate_h0_group_split(split, inventory=inventory)

    assert inventory["group_count"] == 30
    assert inventory["component_count"] == 30
    assert inventory["complete_rounds"] == 30
    assert inventory["human_play_decisions"] == 30
    assert {name: row["group_count"]
            for name, row in split["splits"].items()} \
        == dict(REHEARSAL_HUMAN_SPLIT_COUNTS)
    assert all(path.stat().st_mode & 0o222 == 0 for path in sources)
    assert stable_read_bytes(sources[0]) == rehearsal_human_source_bytes(0)


def test_rehearsal_coordinate_mutations_refuse():
    rows = rehearsal_round_coordinates()
    with pytest.raises(BeliefV2RehearsalError, match="coordinate drift"):
        validate_rehearsal_coordinates(rows[:-1])
    with pytest.raises(BeliefV2RehearsalError, match="coordinate drift"):
        validate_rehearsal_coordinates((
            replace(rows[0], split="test"), *rows[1:]))
    with pytest.raises(BeliefV2RehearsalError, match="population drift"):
        validate_rehearsal_coordinates((
            *rows[:-1], replace(rows[-1], lane=rows[0].lane)))


def test_rehearsal_profile_reaches_the_scoring_reader(monkeypatch):
    _patch_rehearsal_population(monkeypatch)
    coordinate = next(
        row for row in rehearsal_v2_coordinates()
        if row.split == "calibration")
    assert SCORING_STAGE.v2_policy_seeds(coordinate) \
        == rehearsal_v2_policy_seeds(coordinate)


@pytest.mark.skipif(
    CACHE_BENCHMARK_ROOT is None,
    reason="set SHENGJI_BELIEF_V2_CACHE_BENCHMARK_ROOT")
def test_parallel_input_index_reproduces_exact_serial_population(
        monkeypatch):
    """Time the exact compact index scan without writing a stage artifact."""
    configure_numerical_runtime()
    _patch_rehearsal_population(monkeypatch)
    _restore_parent_worker_population(monkeypatch)
    root = Path(CACHE_BENCHMARK_ROOT).resolve()
    base = root.parent
    sources = tuple(sorted((base / "human-sources").glob("*.jsonl")))
    inventory = build_h0_inventory(
        source_manifest=base / "human-source-manifest.txt",
        source_paths=list(sources))
    group_split = build_h0_group_split(inventory)
    freeze = _rehearsal_freeze(root, inventory, group_split)
    admission = _admission(freeze)

    serial_started = time.monotonic_ns()
    serial = STREAMING_INPUTS.reopen_streaming_training_inputs(
        root, freeze=freeze, admission=admission,
        inventory=inventory, group_split=group_split)
    serial_wall = time.monotonic_ns() - serial_started

    worker_count = parallel_input_worker_count(
        freeze.runtime,
        freeze.resource_caps.training_host_memory_bytes)
    assert worker_count >= 2
    parallel_started = time.monotonic_ns()
    parallel = STREAMING_INPUTS.reopen_streaming_training_inputs(
        root, freeze=freeze, admission=admission,
        inventory=inventory, group_split=group_split,
        synthetic_scan=lambda **kwargs: (
            PARALLEL_INPUTS.scan_parallel_synthetic_training_inputs(
                **kwargs, worker_count=worker_count)))
    parallel_wall = time.monotonic_ns() - parallel_started
    serial_raw = STREAMING_INPUTS.streaming_training_inputs_bytes(
        serial, freeze)
    parallel_raw = STREAMING_INPUTS.streaming_training_inputs_bytes(
        parallel, freeze)
    assert parallel_raw == serial_raw
    print("BELIEF_V2_INPUT_INDEX_BENCHMARK " + json.dumps({
        "worker_count": worker_count,
        "index_sha256": hashlib.sha256(parallel_raw).hexdigest(),
        "index_bytes": len(parallel_raw),
        "serial_wall_nanoseconds": serial_wall,
        "parallel_wall_nanoseconds": parallel_wall,
        "wall_speedup_ppm": serial_wall * 1_000_000 // parallel_wall,
    }, sort_keys=True))


@pytest.mark.skipif(
    CACHE_BENCHMARK_ROOT is None,
    reason="set SHENGJI_BELIEF_V2_CACHE_BENCHMARK_ROOT")
def test_parallel_cache_benchmark_reproduces_exact_primary(
        tmp_path, monkeypatch):
    """Time only the real primary cache path against sealed rehearsal bytes."""
    configure_numerical_runtime()
    _patch_rehearsal_population(monkeypatch)
    _restore_parent_worker_population(monkeypatch)
    _patch_stage_gates(monkeypatch)
    root = Path(CACHE_BENCHMARK_ROOT).resolve()
    base = root.parent
    sources = tuple(sorted((base / "human-sources").glob("*.jsonl")))
    inventory = build_h0_inventory(
        source_manifest=base / "human-source-manifest.txt",
        source_paths=list(sources))
    group_split = build_h0_group_split(inventory)
    freeze = _rehearsal_freeze(root, inventory, group_split)
    admission = _admission(freeze)
    index_manifest, inputs = reopen_training_input_index(
        root / "training-input-index" / "result",
        freeze=freeze, admission=admission)
    primary = next(row for row in inputs.realizations
                   if row.cohort_id == "synthetic-primary")
    binding = CACHE_STAGE._realization_binding(
        freeze, index_manifest["index_sha256"], primary)
    worker_count = min(
        int(os.environ.get("SHENGJI_BELIEF_V2_CACHE_BENCHMARK_WORKERS",
                           str(parallel_cache_worker_count(
                               freeze.runtime,
                               freeze.resource_caps
                               .training_host_memory_bytes)))),
        parallel_cache_worker_count(
            freeze.runtime,
            freeze.resource_caps.training_host_memory_bytes))
    assert worker_count >= 2
    monkeypatch.setattr(
        PARALLEL_CACHE, "_initialize_worker",
        _rehearsal_parallel_cache_initializer)

    loader = V2ArtifactRoundLoader(
        root, freeze=freeze, admission=admission, index=inputs.index)
    serial_started = time.monotonic_ns()
    serial_receipt = build_tensor_cache(
        tmp_path / "serial-cache",
        batches=lambda: iter_streaming_training_batches(
            inputs.index, primary, load_round=loader),
        binding=binding)
    serial_wall = time.monotonic_ns() - serial_started

    parallel_started = time.monotonic_ns()
    parallel_receipt = build_parallel_tensor_cache(
        tmp_path / "cache", root=root, freeze=freeze, admission=admission,
        index=inputs.index, schedule=primary, mode="train",
        binding=binding, worker_count=worker_count)
    parallel_wall = time.monotonic_ns() - parallel_started
    stage = json.loads((
        root / "training-tensor-cache" / "result" / "manifest.json"
    ).read_bytes())
    expected = next(row for row in stage["cohort_caches"]
                    if row["cohort_id"] == primary.cohort_id)
    expected_receipt = {key: expected[key] for key in (
        "manifest_sha256", "batch_count", "decision_count",
        "artifact_bytes")}
    _assert_cache_benchmark_receipts(
        expected_receipt, serial_receipt, parallel_receipt)
    assert {path.name: path.read_bytes()
            for path in (tmp_path / "serial-cache").iterdir()} \
        == {path.name: path.read_bytes()
            for path in (tmp_path / "cache").iterdir()}
    print("BELIEF_V2_CACHE_BENCHMARK " + json.dumps({
        "worker_count": worker_count,
        "batch_count": parallel_receipt["batch_count"],
        "artifact_bytes": parallel_receipt["artifact_bytes"],
        "serial_wall_nanoseconds": serial_wall,
        "parallel_wall_nanoseconds": parallel_wall,
        "wall_speedup_ppm": (
            serial_wall * 1_000_000 // parallel_wall),
        "manifest_sha256": parallel_receipt["manifest_sha256"],
    }, sort_keys=True))


@pytest.mark.skipif(
    CACHE_BENCHMARK_ROOT is None,
    reason="set SHENGJI_BELIEF_V2_CACHE_BENCHMARK_ROOT")
def test_parallel_cache_group_benchmark_reproduces_exact_stage_population(
        tmp_path, monkeypatch):
    """Measure the full cache population with the production worker topology."""
    configure_numerical_runtime()
    _patch_rehearsal_population(monkeypatch)
    _restore_parent_worker_population(monkeypatch)
    _patch_stage_gates(monkeypatch)
    root = Path(CACHE_BENCHMARK_ROOT).resolve()
    base = root.parent
    sources = tuple(sorted((base / "human-sources").glob("*.jsonl")))
    inventory = build_h0_inventory(
        source_manifest=base / "human-source-manifest.txt",
        source_paths=list(sources))
    group_split = build_h0_group_split(inventory)
    freeze = _rehearsal_freeze(root, inventory, group_split)
    admission = _admission(freeze)
    index_manifest, inputs = reopen_training_input_index(
        root / "training-input-index" / "result",
        freeze=freeze, admission=admission)
    monkeypatch.setattr(
        PARALLEL_CACHE, "_initialize_worker",
        _rehearsal_parallel_cache_initializer)
    index_sha = index_manifest["index_sha256"]
    primary = next(row for row in inputs.realizations
                   if row.cohort_id == "synthetic-primary")
    control = next(row for row in inputs.realizations
                   if row.cohort_id == "hard-geometry-label-permutation")
    primary_binding = CACHE_STAGE._realization_binding(
        freeze, index_sha, primary)
    direct_specs = tuple(
        (row.cohort_id, row, "train", CACHE_STAGE._realization_binding(
            freeze, index_sha, row))
        for row in inputs.realizations
        if row.cohort_id != control.cohort_id) + ((
            CACHE_STAGE.CALIBRATION_CACHE_ID,
            inputs.common_calibration, "calibration",
            CACHE_STAGE._calibration_binding(
                freeze, index_sha, inputs.common_calibration)),)
    loader = V2ArtifactRoundLoader(
        root, freeze=freeze, admission=admission, index=inputs.index)

    def serial_build(parent: Path, spec):
        cache_id, schedule, mode, binding = spec
        directory = parent / cache_id
        if mode == "train":
            receipt = build_tensor_cache(
                directory,
                batches=lambda row=schedule: (
                    iter_streaming_training_batches(
                        inputs.index, row, load_round=loader)),
                binding=binding)
        else:
            receipt = build_tensor_cache(
                directory,
                batches=lambda: iter_streaming_calibration_batches(
                    inputs.index, inputs.common_calibration,
                    load_round=loader),
                binding=binding)
        return cache_id, receipt

    serial_parent = tmp_path / "serial"
    serial_parent.mkdir()
    serial_started = time.monotonic_ns()
    serial_receipts = dict(
        serial_build(serial_parent, spec) for spec in direct_specs)
    serial_overlay = build_label_overlay(
        serial_parent / "control-overlay",
        batches=lambda: iter_streaming_training_batches(
            inputs.index, control, load_round=loader),
        actor_directory=serial_parent / primary.cohort_id,
        actor_manifest_sha256=serial_receipts[
            primary.cohort_id]["manifest_sha256"],
        binding=primary_binding, overlay_id=control.sha256())
    serial_wall = time.monotonic_ns() - serial_started

    parallel_parent = tmp_path / "parallel"
    parallel_parent.mkdir()
    build_concurrency, workers_per_build = parallel_cache_build_topology(
        freeze.runtime, freeze.resource_caps.training_host_memory_bytes,
        len(direct_specs))

    def parallel_build(spec):
        cache_id, schedule, mode, binding = spec
        return cache_id, build_parallel_tensor_cache(
            parallel_parent / cache_id, root=root, freeze=freeze,
            admission=admission, index=inputs.index, schedule=schedule,
            mode=mode, binding=binding, worker_count=workers_per_build)

    parallel_started = time.monotonic_ns()
    with ThreadPoolExecutor(max_workers=build_concurrency) as executor:
        parallel_receipts = dict(executor.map(
            parallel_build, direct_specs))

    def cached_control_batches():
        primary_factory = cached_batch_factory(
            parallel_parent / primary.cohort_id,
            expected_manifest_sha256=parallel_receipts[
                primary.cohort_id]["manifest_sha256"],
            binding=primary_binding)
        for natural in primary_factory():
            transformed, _ = label_control_batch_from_natural(natural)
            yield transformed

    parallel_overlay = build_label_overlay(
        parallel_parent / "control-overlay",
        batches=cached_control_batches,
        actor_directory=parallel_parent / primary.cohort_id,
        actor_manifest_sha256=parallel_receipts[
            primary.cohort_id]["manifest_sha256"],
        binding=primary_binding, overlay_id=control.sha256())
    parallel_wall = time.monotonic_ns() - parallel_started

    assert parallel_receipts == serial_receipts
    assert parallel_overlay == serial_overlay
    for cache_id, *_ in direct_specs:
        assert {path.name: path.read_bytes()
                for path in (parallel_parent / cache_id).iterdir()} \
            == {path.name: path.read_bytes()
                for path in (serial_parent / cache_id).iterdir()}
    assert {path.name: path.read_bytes()
            for path in (parallel_parent / "control-overlay").iterdir()} \
        == {path.name: path.read_bytes()
            for path in (serial_parent / "control-overlay").iterdir()}
    stage = json.loads((
        root / "training-tensor-cache" / "result" / "manifest.json"
    ).read_bytes())
    expected = {row["cohort_id"]: row
                for row in stage["cohort_caches"]}
    for cache_id, receipt in serial_receipts.items():
        source = (stage["common_calibration_cache"]
                  if cache_id == CACHE_STAGE.CALIBRATION_CACHE_ID
                  else expected[cache_id])
        _assert_cache_benchmark_receipts(source, receipt, receipt)
    _assert_cache_benchmark_receipts(
        expected[control.cohort_id], serial_overlay, parallel_overlay)
    print("BELIEF_V2_CACHE_GROUP_BENCHMARK " + json.dumps({
        "aggregate_worker_budget": parallel_cache_worker_count(
            freeze.runtime,
            freeze.resource_caps.training_host_memory_bytes),
        "concurrent_builds": build_concurrency,
        "workers_per_build": workers_per_build,
        "direct_cache_count": len(direct_specs),
        "serial_wall_nanoseconds": serial_wall,
        "parallel_wall_nanoseconds": parallel_wall,
        "wall_speedup_ppm": serial_wall * 1_000_000 // parallel_wall,
        "direct_artifact_bytes": sum(
            row["artifact_bytes"] for row in parallel_receipts.values()),
        "overlay_artifact_bytes": parallel_overlay["artifact_bytes"],
    }, sort_keys=True))


def test_cache_benchmark_receipt_binding_is_cross_platform_but_exact():
    expected = {
        "manifest_sha256": "a" * 64,
        "batch_count": 71,
        "decision_count": 5536,
        "artifact_bytes": 71579039,
    }
    serial = dict(expected, manifest_sha256="b" * 64)
    parallel = dict(serial)
    _assert_cache_benchmark_receipts(expected, serial, parallel)

    with pytest.raises(AssertionError):
        _assert_cache_benchmark_receipts(
            expected, serial, dict(parallel, manifest_sha256="c" * 64))
    with pytest.raises(AssertionError):
        _assert_cache_benchmark_receipts(
            expected, dict(serial, decision_count=5535), parallel)


def test_genuine_admission_traverses_every_unpatched_stage_gate(
        tmp_path, monkeypatch):
    """Exercise the production gate at every stage import altitude."""
    monkeypatch.delenv("PYTHONPATH", raising=False)
    for key, value in (
            ("PYTHONDONTWRITEBYTECODE", "1"),
            ("PYTHONHASHSEED", "0"),
            ("SHENGJI_FAST", "1"),
            ("SHENGJI_REQUIRE_VOIDS", "1")):
        monkeypatch.setenv(key, value)
    configure_numerical_runtime()

    repo = (tmp_path / "execution-repo").resolve()
    remote = (tmp_path / "canonical.git").resolve()
    root = (tmp_path / "evidence").resolve()
    root.mkdir()
    for relative in (
            "BELIEF_V1_SPEC.md", "BELIEF_V1_V2_DESIGN.md",
            "server/pyproject.toml", "server/setup.py", "server/uv.lock",
            "server/scripts/belief_v2_worker.py",
            "server/shengji/__init__.py"):
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"fixture: {relative}\n", encoding="utf-8")
    (repo / "HANDOFF_REVIEW.md").write_text("ledger\n", encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "add", ".")
    _git(repo, "-c", "user.name=Execution", "-c",
         "user.email=execution@example.com", "commit", "-qm", "execution")
    execution_git = _git(repo, "rev-parse", "HEAD")
    bindings = build_source_bindings(repo, expected_git=execution_git)
    runtime = build_runtime_profile()
    training_device = next(iter(available_training_accelerators()), "cpu")
    freeze = replace(
        _cpu_only_freeze(root), execution_git=execution_git,
        source_manifest_sha256=source_manifest_sha256(
            execution_git, bindings),
        source_bindings=bindings, runtime=runtime,
        source_review_commit=execution_git,
        training_candidate_device=training_device,
        training_device_profile=build_training_device_profile(
            training_device),
        device_qualification_protocol_sha256=(
            qualification_protocol_sha256(training_device)))

    marker = REVIEW_PREFIX.encode("ascii") + canonical_json_bytes(
        expected_execution_review_claim(freeze))
    with (repo / "HANDOFF_REVIEW.md").open("ab") as handle:
        handle.write(marker)
    _git(repo, "add", "HANDOFF_REVIEW.md")
    _git(repo, "-c", "user.name=Claude", "-c",
         "user.email=noreply@anthropic.com", "commit", "-qm",
         "PASS\n\nClaude-Session: https://claude.ai/code/session_test")
    review_commit = _git(repo, "rev-parse", "HEAD")
    subprocess.run(("git", "init", "--bare", "-q", str(remote)),
                   check=True)
    _git(repo, "branch", "-M", "main")
    _git(repo, "remote", "add", "origin", str(remote))
    _git(repo, "push", "-qu", "origin", "main")
    _git(repo, "checkout", "-q", "--detach", execution_git)
    monkeypatch.setattr(
        "shengji.rl.belief_v2_freeze.CANONICAL_REMOTE_URL", str(remote))
    admission, built_marker = build_pipeline_admission(
        freeze, repo=repo, review_commit=review_commit)
    assert built_marker == marker

    stage_gates = (
        ("synthetic-capture", V2_CONTROLLER._stage_gate),
        ("human-capture", HUMAN_STAGE._stage_gate),
        ("training-input-index", INPUT_INDEX_STAGE._stage_gate),
        ("training-tensor-cache", CACHE_STAGE._stage_gate),
        ("device-qualification", DEVICE_STAGE._stage_gate),
        ("synthetic-reference", V2_CONTROLLER._stage_gate),
        ("human-reference", HUMAN_REF_STAGE._stage_gate),
        ("training", TRAINING_STAGE._stage_gate),
        ("calibration", CALIBRATION_STAGE._stage_gate),
        ("terminal", TERMINAL_STAGE._stage_gate),
    )
    assert len(stage_gates) == 10
    assert all(gate is V2_CONTROLLER._stage_gate
               for _, gate in stage_gates)
    stage_gates[0][1](
        root=root, repo=repo, freeze=freeze, admission=admission,
        review_marker=marker)

    # Reproduce the seventh R4 failure class between stage transitions: an
    # unrelated append-only commit advances canonical main after admission.
    # Later gates must authenticate the recorded historical tip, not compare
    # the frozen checkout with the moving remote head.
    writer = (tmp_path / "canonical-writer").resolve()
    subprocess.run(("git", "clone", "-q", str(remote), str(writer)),
                   check=True)
    (writer / "later.txt").write_text("main advanced\n", encoding="utf-8")
    _git(writer, "add", "later.txt")
    _git(writer, "-c", "user.name=Later", "-c",
         "user.email=later@example.com", "commit", "-qm", "later")
    _git(writer, "push", "-q", "origin", "main")
    assert _git(writer, "rev-parse", "HEAD") \
        != admission.canonical_remote_tip
    for _, gate in stage_gates[1:]:
        gate(root=root, repo=repo, freeze=freeze, admission=admission,
             review_marker=marker)

    forged = replace(admission, canonical_remote_tip=execution_git)
    for _, gate in stage_gates:
        with pytest.raises(BeliefV2ControllerError,
                           match="stage admission refused"):
            gate(root=root, repo=repo, freeze=freeze, admission=forged,
                 review_marker=marker)


@pytest.mark.skipif(
    not RUN_FULL_REHEARSAL,
    reason="set SHENGJI_BELIEF_V2_FULL_DAG_REHEARSAL=1")
def test_full_dag_rehearsal_traverses_every_stage_and_reopens(
        tmp_path, monkeypatch):
    """Run the computational DAG on disposable data with real stage wiring.

    The population/stability overrides are explicit test-harness inputs and
    are recorded in the receipt.  Production defaults and scientific gates are
    unchanged outside this opt-in process.
    """
    monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    configure_numerical_runtime()
    _patch_rehearsal_population(monkeypatch)
    _patch_stage_gates(monkeypatch)
    monkeypatch.setattr(
        PARALLEL_CACHE, "_initialize_worker",
        _rehearsal_parallel_cache_initializer)
    resume_value = os.environ.get("SHENGJI_BELIEF_V2_REHEARSAL_RESUME_ROOT")
    fresh_root_value = os.environ.get("SHENGJI_BELIEF_V2_REHEARSAL_ROOT")
    if resume_value is not None and fresh_root_value is not None:
        raise AssertionError("rehearsal root and resume root are exclusive")
    resumed = resume_value is not None
    if resumed:
        root = Path(resume_value).resolve()
        base = root.parent
        sources = tuple(sorted((base / "human-sources").glob("*.jsonl")))
        inventory = build_h0_inventory(
            source_manifest=base / "human-source-manifest.txt",
            source_paths=list(sources))
        group_split = build_h0_group_split(inventory)
        for failed_partial in (
                root / "training-input-index" / "result.partial",
                root / "device-qualification" / "result.partial"):
            if failed_partial.is_dir() and not any(failed_partial.iterdir()):
                failed_partial.rmdir()
    else:
        root = (Path(fresh_root_value).resolve()
                if fresh_root_value is not None
                else (tmp_path / "evidence").resolve())
        base = root.parent
        base.mkdir(mode=0o700, exist_ok=True)
        sources, inventory, group_split = _fixture_h0(base)
        root.mkdir()
    freeze = _rehearsal_freeze(root, inventory, group_split)
    admission = _admission(freeze)
    review_marker = b"rehearsal-review-marker\n"
    progress_rows: list[dict] = []

    capture_dirs = tuple(
        root / "capture" / f"lane-{lane:02d}"
        for lane in range(V2_CAPTURE_LANES))
    if resumed and all(path.is_dir() for path in capture_dirs):
        _restore_parent_worker_population(monkeypatch)
        capture_manifests = tuple(reopen_capture_lane(
            path, freeze=freeze, admission=admission, lane=lane)
            for lane, path in enumerate(capture_dirs))
    else:
        capture_results = _process_map(
            _capture_process,
            ((root, freeze, admission, lane, review_marker)
             for lane in range(V2_CAPTURE_LANES)),
            max_workers=V2_CAPTURE_LANES)
        capture_manifests = tuple(row[0] for row in capture_results)
        progress_rows.extend(progress for row in capture_results
                             for progress in row[1])
    assert sum(row["round_count"] for row in capture_manifests) == 104

    human_dirs = tuple(
        root / "human-capture" / f"group-{_group_digest(path)}"
        for path in sources)
    if resumed and all(path.is_dir() for path in human_dirs):
        human_manifests = tuple(reopen_human_group_manifest(
            path, freeze=freeze, admission=admission)
            for path in human_dirs)
    else:
        human_results = _process_map(
            _human_capture_process,
            ((root, freeze, admission, path, inventory, group_split,
              review_marker) for path in sources),
            max_workers=V2_CAPTURE_LANES)
        human_manifests = tuple(row[0] for row in human_results)
        progress_rows.extend(progress for row in human_results
                             for progress in row[1])
    assert sum(row["human_decision_count"]
               for row in human_manifests) == 30

    _restore_parent_worker_population(monkeypatch)
    index_directory = root / "training-input-index" / "result"
    if resumed and index_directory.is_dir():
        index_manifest, inputs = reopen_training_input_index(
            index_directory, freeze=freeze, admission=admission)
    else:
        index_manifest = run_training_input_index(
            root, freeze, admission, repo=Path("/unused"),
            review_marker=review_marker, inventory=inventory,
            group_split=group_split,
            progress=_reporter(
                "training-input-index", "all-sources", progress_rows))
        reopened_index_manifest, inputs = reopen_training_input_index(
            index_directory, freeze=freeze, admission=admission)
        assert reopened_index_manifest == index_manifest
    assert len(inputs.realizations) == 4

    cache_directory = root / "training-tensor-cache" / "result"
    if resumed and cache_directory.is_dir():
        (cache_manifest, factories, calibration_factory, control_dose,
         cache_sha) = reopen_training_tensor_cache(
            cache_directory, freeze=freeze, admission=admission)
    else:
        cache_manifest = run_training_tensor_cache(
            root, freeze, admission, repo=Path("/unused"),
            review_marker=review_marker,
            progress=_reporter(
                "training-tensor-cache", "all-cohorts", progress_rows))
        (reopened_cache, factories, calibration_factory, control_dose,
         cache_sha) = reopen_training_tensor_cache(
            cache_directory, freeze=freeze, admission=admission)
        assert reopened_cache == cache_manifest
    assert tuple(factories) == tuple(
        row.cohort_id for row in inputs.realizations)

    primary = next(row for row in inputs.realizations
                   if row.cohort_id == "synthetic-primary")
    qualification_directory = root / "device-qualification" / "result"
    if resumed and qualification_directory.is_dir():
        (qualification_manifest, qualification_plan, qualification) = (
            reopen_device_qualification(
                qualification_directory, freeze=freeze,
                admission=admission, primary=primary))
    else:
        qualification_manifest = run_device_qualification(
            root, freeze, admission, repo=Path("/unused"),
            review_marker=review_marker, primary=primary,
            primary_examples=None,
            batch_factory=factories[primary.cohort_id],
            progress=_reporter(
                "device-qualification", "candidate-device", progress_rows))
        (reopened_qualification_manifest, qualification_plan,
         qualification) = reopen_device_qualification(
            qualification_directory, freeze=freeze,
            admission=admission, primary=primary)
        assert reopened_qualification_manifest == qualification_manifest

    reference_tasks = []
    for lane in range(V2_CAPTURE_LANES):
        reference_tasks.append((
            "synthetic", root, freeze, admission, lane, None, inventory,
            group_split, None, review_marker))
    by_split = {
        split: set(row["group_digests"])
        for split, row in group_split["splits"].items()}
    for path in sources:
        digest = _group_digest(path)
        split = next(name for name, values in by_split.items()
                     if digest in values)
        replicates = (
            ("calibration-replicate-0", "calibration-replicate-1")
            if split == "calibration"
            else ("test-primary",) if split == "test" else ())
        for replicate in replicates:
            reference_tasks.append((
                "human", root, freeze, admission, None, path, inventory,
                group_split, replicate, review_marker))

    reference_directories = tuple(
        root / "reference" / f"lane-{row[4]:02d}"
        if row[0] == "synthetic" else
        root / "human-reference" / f"group-{_group_digest(row[5])}" / row[8]
        for row in reference_tasks)
    if resumed and all(path.is_dir() for path in reference_directories):
        # Every publisher already performed a typed post-publish reopen, and
        # calibration/terminal will reopen the selected artifacts again.  A
        # development-only resume needs only the complete slot population;
        # the official zero-resume rehearsal still executes the publishers.
        reference_manifests = tuple(
            {"resumed_directory": str(path)}
            for path in reference_directories)
    else:
        reference_results = _process_map(
            _reference_process, reference_tasks, max_workers=V2_CAPTURE_LANES)
        reference_manifests = tuple(row[0] for row in reference_results)
        progress_rows.extend(progress for row in reference_results
                             for progress in row[1])
    assert len(reference_manifests) == 25

    def train(realization):
        return run_training_cohort(
            root, freeze, admission, repo=Path("/unused"),
            review_marker=review_marker, primary=primary,
            realization=realization, training_examples=None,
            calibration=inputs.common_calibration,
            calibration_examples=None,
            training_batch_factory=factories[realization.cohort_id],
            calibration_batch_factory=calibration_factory,
            cache_manifest_sha256=cache_sha,
            cache_control_dose=(
                control_dose if realization.kind
                == "hard-geometry-label-permutation" else 0),
            qualification_plan=qualification_plan,
            qualification_result=qualification,
            progress=_reporter(
                "training", realization.cohort_id, progress_rows))

    training_directories = tuple(
        root / "training" / row.cohort_id for row in inputs.realizations)
    reused_training = resumed and all(
        path.is_dir() for path in training_directories)
    if reused_training:
        training_manifests = None
    else:
        with ThreadPoolExecutor(max_workers=4) as executor:
            training_manifests = tuple(
                executor.map(train, inputs.realizations))
    def reopen_trained(item):
        index, realization = item
        reopened_manifest, artifacts = reopen_training_cohort(
            root / "training" / realization.cohort_id, freeze=freeze,
            admission=admission, primary=primary,
            realization=realization, training_examples=None,
            calibration=inputs.common_calibration,
            calibration_examples=None,
            qualification_plan=qualification_plan,
            qualification_result=qualification,
            calibration_batch_factory=calibration_factory,
            cache_manifest_sha256=cache_sha,
            compact_control_dose=(
                control_dose if realization.kind
                == "hard-geometry-label-permutation" else 0))
        if training_manifests is not None:
            assert reopened_manifest == training_manifests[index]
        assert len(artifacts.epochs) >= 1
        return artifacts

    if reused_training:
        cohort_epoch_counts = {
            realization.cohort_id: len(tuple(
                (root / "training" / realization.cohort_id
                 / "epoch-journal").glob("epoch-[0-9][0-9][0-9][0-9]")))
            for realization in inputs.realizations}
        assert min(cohort_epoch_counts.values()) >= 1
    else:
        # Re-scoring the four independently sealed checkpoint chains is pure
        # read-only verification.  Keep the same four-way topology as training
        # so the dress rehearsal does not add a needless single-core tail.
        with ThreadPoolExecutor(max_workers=4) as executor:
            trained = list(executor.map(
                reopen_trained, enumerate(inputs.realizations)))
        cohort_epoch_counts = {
            row.cohort_id: len(row.epochs) for row in trained}

    calibration_directory = root / "calibration" / "selection"
    if resumed and calibration_directory.is_dir():
        calibration_manifest = reopen_v2_calibration_selection(
            calibration_directory, freeze=freeze, admission=admission,
            inventory=inventory, group_split=group_split)
    else:
        calibration_manifest = run_v2_calibration_selection(
            root, freeze, admission, repo=Path("/unused"),
            review_marker=review_marker, inventory=inventory,
            group_split=group_split,
            progress=_reporter("calibration", "all-cohorts", progress_rows))
        assert reopen_v2_calibration_selection(
            calibration_directory, freeze=freeze,
            admission=admission, inventory=inventory,
            group_split=group_split) == calibration_manifest

    terminal_directory = root / "terminal"
    if resumed and terminal_directory.is_dir():
        terminal_manifest = reopen_v2_terminal(
            terminal_directory, freeze=freeze, admission=admission,
            inventory=inventory, group_split=group_split,
            progress=_reporter(
                "terminal-verification", "reopen", progress_rows))
    else:
        terminal_manifest = run_v2_terminal(
            root, freeze, admission, repo=Path("/unused"),
            review_marker=review_marker, inventory=inventory,
            group_split=group_split,
            progress=_reporter("terminal", "test-opening", progress_rows))
        assert reopen_v2_terminal(
            terminal_directory, freeze=freeze, admission=admission,
            inventory=inventory, group_split=group_split,
            progress=_reporter(
                "terminal-verification", "reopen", progress_rows)) \
            == terminal_manifest

    by_phase: dict[tuple[str, str, str], list[dict]] = {}
    for row in progress_rows:
        by_phase.setdefault(
            (row["stage"], row["worker"], row["phase"]), []).append(row)
    if not resumed:
        assert by_phase
    assert all([row["completed_units"] for row in values]
               == sorted(row["completed_units"] for row in values)
               and len({row["total_units"] for row in values}) == 1
               for values in by_phase.values())
    by_worker: dict[tuple[str, str], list[dict]] = {}
    for row in progress_rows:
        by_worker.setdefault((row["stage"], row["worker"]), []).append(row)
    assert all(any(row["completed_units"] > 0 for row in values)
               and values[-1]["completed_units"]
               == values[-1]["total_units"]
               for values in by_worker.values())

    artifacts = _artifact_population(root)
    repo = Path(__file__).resolve().parents[2]
    execution_git = subprocess.run(
        ("git", "rev-parse", "HEAD"), cwd=repo, check=True,
        capture_output=True, text=True).stdout.strip()
    checkout_clean = not subprocess.run(
        ("git", "status", "--porcelain", "--untracked-files=all"),
        cwd=repo, check=True, capture_output=True,
        text=True).stdout.strip()
    source_sha = None
    if checkout_clean:
        source_sha = source_manifest_sha256(
            execution_git, build_source_bindings(
                repo, expected_git=execution_git))
    runtime = build_runtime_profile()
    runtime_dict = runtime.to_dict()
    progress_population_sha256 = hashlib.sha256(
        canonical_json_bytes(progress_rows)).hexdigest()
    receipt = {
        "schema": REHEARSAL_RECEIPT_SCHEMA,
        "smoke_only": True,
        "scientific_evidence": False,
        "profile_sha256": rehearsal_profile_sha256(),
        "freeze_sha256": freeze.sha256(),
        "admission_sha256": admission.sha256(),
        "source_identity": {
            "execution_git": execution_git,
            "checkout_clean": checkout_clean,
            "source_manifest_sha256": source_sha,
        },
        "runtime_identity": {
            "profile": runtime_dict,
            "profile_sha256": hashlib.sha256(
                canonical_json_bytes(runtime_dict)).hexdigest(),
        },
        "device_identity": {
            "training_device": qualification.selected_device,
            "qualification_plan_sha256": qualification_plan.sha256(),
            "qualification_result_sha256": hashlib.sha256(
                qualification.canonical_bytes(
                    qualification_plan)).hexdigest(),
        },
        "synthetic_round_count": 104,
        "human_fixture_source_count": 30,
        "reference_world_count": 256,
        "cohort_epoch_counts": cohort_epoch_counts,
        "stage_order": list(REHEARSAL_STAGE_ORDER),
        "progress": {
            "row_count": len(progress_rows),
            "worker_count": len(by_worker),
            "phase_count": len(by_phase),
            "rows": progress_rows,
            "population_sha256": progress_population_sha256,
        },
        "artifact_count": len(artifacts),
        "artifact_population_sha256": hashlib.sha256(
            canonical_json_bytes(artifacts)).hexdigest(),
        "terminal_manifest_sha256": hashlib.sha256(
            canonical_json_bytes(terminal_manifest)).hexdigest(),
        "stability_observations": list(
            CALIBRATION_STAGE._rehearsal_observed_stability),
        "development_resume_used": resumed,
        "production_freeze_review_eligible": (
            not resumed and checkout_clean),
        "retry_count": 0,
        "drop_count": 0,
        "authority": rehearsal_profile_dict()["authority"],
    }
    validate_rehearsal_receipt(receipt)
    assert receipt["cohort_epoch_counts"]
    assert min(receipt["cohort_epoch_counts"].values()) >= 1
    assert not any(receipt["authority"].values())
    output = os.environ.get("SHENGJI_BELIEF_V2_REHEARSAL_RECEIPT")
    if output:
        output_path = Path(output).resolve()
        assert output_path.is_absolute() and not output_path.exists()
        publish_exclusive_bytes(output_path, canonical_json_bytes(receipt))
