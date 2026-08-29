"""Exact data, prediction, terminal, and reconstruction stages for Value V1.

This module keeps the outcome-blind prediction boundary literal.  Training
may reopen only V0 train rows.  Prediction may reopen only the private
calibration audit records, which contain engine states but no continuation
outcomes.  Calibration labels enter only through the later audit function,
after every cohort prediction byte stream has been sealed.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .belief_contract import canonical_json_bytes
from .world_afterstate_dataset import (
    reopen_dataset_manifest, validate_dataset_manifest)
from .world_afterstate_population import (
    reopen_population_audit_fold, validate_population_audit_manifest,
    validate_population_manifest)
from .world_afterstate_v1_audit_controller import (
    build_prediction_artifact_bytes, evaluate_sealed_predictions,
    reopen_prediction_artifact_bytes)
from .world_afterstate_v1_capacity import (
    ARTIFACT_PATHS, CapacityBuildV1, reopen_capacity_build)
from .world_afterstate_v1_controls import (
    action_association_permutation, identical_successor_control,
    label_permutation)
from .world_afterstate_v1_dataset import (
    build_advantage_manifest, join_advantage_examples,
    select_manifest_eligible_advantage_rows)
from .world_afterstate_v1_evaluation import inference_population_sha256
from .world_afterstate_v1_experiment import (
    CALIBRATION_ACTION_GROUP_COUNT, CALIBRATION_AUDIT_COUNT,
    CALIBRATION_GROUP_COUNT,
    CALIBRATION_LABEL_PAIR_COUNT, CALIBRATION_LABEL_ROW_COUNT,
    CALIBRATION_PAIR_COUNT, FREEZE_SCHEMA)
from .world_afterstate_v1_inference import (
    COHORT_INPUT_NAMES, build_calibration_inference_batch,
    validate_calibration_inference_build,
    validate_calibration_inference_manifest)
from .world_afterstate_v1_pipeline import (
    PipelineBuildV1, build_pipeline_build, reopen_pipeline_directory)
from .world_afterstate_v1_result import (
    CONTROL_NAMES, derive_terminal_result)
from .world_afterstate_v1_training import AdvantageTrainingConfigV1
from .world_afterstate_v1_training_controller import (
    CohortTrainingBuildV1, TRAINING_COHORTS, reopen_cohort_build,
    reopen_cohort_directory, train_named_cohort)


PREDICTION_MANIFEST_SCHEMA = (
    "world-afterstate-v1-target-free-prediction-manifest-v1")
PREDICTION_AUTHORITY = {
    "calibration_label_opening_authorized": False,
    "report_row_opening_authorized": False,
    "provider_audit_row_opening_authorized": False,
    "p2_execution_authorized": False,
    "gameplay_authorized": False,
    "strength_claim_authorized": False,
    "merge_authorized": False,
    "promotion_authorized": False,
    "deployment_authorized": False,
    "retry_authorized": False,
    "r5_authorized": False,
}


class WorldAfterstateV1ExecutionError(ValueError):
    """A scientific input, split, prediction, label, or output drifted."""


@dataclass(frozen=True)
class TargetFreePredictionBuildV1:
    manifest: dict[str, Any]
    files: tuple[tuple[str, bytes], ...]


def _sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha(value: object) -> str:
    return _sha_bytes(canonical_json_bytes(value))


def _canonical(raw: bytes, label: str) -> dict[str, Any]:
    if type(raw) is not bytes:
        raise WorldAfterstateV1ExecutionError(f"{label} byte type drift")
    try:
        value = json.loads(raw.decode("ascii"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise WorldAfterstateV1ExecutionError(
            f"{label} is not canonical JSON") from exc
    if type(value) is not dict or canonical_json_bytes(value) != raw:
        raise WorldAfterstateV1ExecutionError(
            f"{label} is not canonical JSON")
    return value


def _sealed_read(path: Path, label: str) -> bytes:
    if not isinstance(path, Path) or path.is_symlink():
        raise WorldAfterstateV1ExecutionError(f"{label} path drift")
    try:
        with path.open("rb") as handle:
            before = os.fstat(handle.fileno())
            raw = handle.read()
            after = os.fstat(handle.fileno())
    except OSError as exc:
        raise WorldAfterstateV1ExecutionError(
            f"{label} cannot be read") from exc
    identity = lambda value: (
        value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns,
        value.st_ctime_ns)
    if identity(before) != identity(after) or before.st_nlink != 1 \
            or stat.S_IMODE(before.st_mode) != 0o400 \
            or before.st_size != len(raw) \
            or not stat.S_ISREG(before.st_mode):
        raise WorldAfterstateV1ExecutionError(
            f"{label} is mutable or changed while read")
    return raw


def _write_once(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(path, 0o400)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _file_rows(files: Mapping[str, bytes]) -> list[dict[str, Any]]:
    return [{
        "relative_path": path, "byte_count": len(raw),
        "sha256": _sha_bytes(raw),
    } for path, raw in sorted(files.items())]


def _capacity_artifacts(build: CapacityBuildV1) -> dict[str, dict[str, Any]]:
    reopened = reopen_capacity_build(build)
    return {
        path: _canonical(raw, f"capacity {path}")
        for path, raw in reopened.files
    }


def _validate_frozen_input(
        path: Path, *, external_sha256: str, internal_sha256: str,
        label: str) -> tuple[bytes, dict[str, Any]]:
    raw = _sealed_read(path, label)
    value = _canonical(raw, label)
    if _sha_bytes(raw) != external_sha256 \
            or value.get("manifest_sha256") != internal_sha256:
        raise WorldAfterstateV1ExecutionError(
            f"{label} binding drift")
    return raw, value


def _row_population_sha(rows: Sequence[tuple[dict[str, Any], Any]]) -> str:
    return _sha([{
        "state_group_id": binding["state_group_id"],
        "candidate_index": binding["candidate_index"],
        "replicate": binding["replicate"],
        "row_sha256": reopened.row_sha256,
    } for binding, reopened in rows])


def reopen_training_values(
        *, freeze: Mapping[str, Any], capacity_build: CapacityBuildV1,
        population_path: Path, dataset_manifest_path: Path, row_root: Path,
        deadline_monotonic_ns: int,
        progress: Callable[[int, int], None] | None = None):
    """Open exactly the V0 train fold and reconstruct the reviewed pairs."""
    if type(freeze) is not dict or freeze.get("schema") != FREEZE_SCHEMA:
        raise WorldAfterstateV1ExecutionError("training freeze drift")
    inputs = freeze["v0_inputs"]
    _population_raw, population = _validate_frozen_input(
        population_path,
        external_sha256=inputs["population_external_sha256"],
        internal_sha256=inputs["population_manifest_sha256"],
        label="scientific V0 population")
    _dataset_raw, dataset = _validate_frozen_input(
        dataset_manifest_path,
        external_sha256=inputs["dataset_external_sha256"],
        internal_sha256=inputs["dataset_manifest_sha256"],
        label="scientific V0 dataset")
    try:
        validate_population_manifest(population)
        validate_dataset_manifest(dataset, population_manifest=population)
        rows = reopen_dataset_manifest(
            dataset, population_manifest=population, row_root=row_root,
            allowed_folds=("train",), reconstruct_continuations=False,
            reconstruction_workers=freeze["learner"]["row_workers"],
            deadline_monotonic_ns=deadline_monotonic_ns,
            progress=progress)
        eligible_rows = select_manifest_eligible_advantage_rows(
            [reopened for _binding, reopened in rows],
            candidate_counts_by_state_group={
                group["state_group_id"]: group["candidate_count"]
                for group in population["groups"]
                if group["fold"] == "train"
            })
        joined = tuple(join_advantage_examples(eligible_rows))
        pair_manifest = build_advantage_manifest(
            joined,
            v0_dataset_manifest_sha256=inputs[
                "dataset_manifest_sha256"])
    except ValueError as exc:
        raise WorldAfterstateV1ExecutionError(
            "scientific train population reconstruction drift") from exc
    expected = freeze["population"]
    artifacts = _capacity_artifacts(capacity_build)
    if len(rows) != expected["train_row_count"] \
            or len(joined) != expected["pair_count"] \
            or _row_population_sha(rows) \
            != expected["train_row_population_sha256"] \
            or canonical_json_bytes(pair_manifest) \
            != canonical_json_bytes(
                artifacts["p1/advantage-manifest.json"]):
        raise WorldAfterstateV1ExecutionError(
            "scientific train population binding drift")
    return joined


def training_values_for_cohort(
        natural: Sequence[Any], *, cohort_name: str,
        capacity_build: CapacityBuildV1):
    """Derive exactly one natural/control population and bind its evidence."""
    if cohort_name not in TRAINING_COHORTS:
        raise WorldAfterstateV1ExecutionError("training cohort name drift")
    if cohort_name == "natural":
        return tuple(natural)
    transforms = {
        "identical-successor": identical_successor_control,
        "action-association-permutation": action_association_permutation,
        "label-permutation": label_permutation,
    }
    try:
        values, evidence = transforms[cohort_name](natural)
    except ValueError as exc:
        raise WorldAfterstateV1ExecutionError(
            "scientific control population drift") from exc
    expected = _capacity_artifacts(capacity_build)[
        f"p1/controls/{cohort_name}.json"]
    if canonical_json_bytes(evidence) != canonical_json_bytes(expected):
        raise WorldAfterstateV1ExecutionError(
            "scientific control evidence binding drift")
    return values


def reopen_scientific_cohort_build(root: Path) -> CohortTrainingBuildV1:
    """Return exact immutable cohort bytes after full checkpoint reopening."""
    try:
        _models, validated_manifest = reopen_cohort_directory(root)
    except ValueError as exc:
        raise WorldAfterstateV1ExecutionError(
            "scientific cohort directory drift") from exc
    manifest_raw = _sealed_read(root / "manifest.json", "cohort manifest")
    manifest = _canonical(manifest_raw, "cohort manifest")
    if manifest != validated_manifest:
        raise WorldAfterstateV1ExecutionError(
            "scientific cohort manifest reconstruction drift")
    checkpoints = tuple(_sealed_read(
        root / "checkpoints" / f"member-{member:02d}.json",
        "cohort checkpoint") for member in range(8))
    build = CohortTrainingBuildV1(
        manifest=manifest, selected_checkpoint_raws=checkpoints)
    try:
        reopen_cohort_build(build)
    except ValueError as exc:
        raise WorldAfterstateV1ExecutionError(
            "scientific cohort build drift") from exc
    return build


def train_scientific_cohort(
        *, freeze: Mapping[str, Any], capacity_build: CapacityBuildV1,
        cohort_name: str, population_path: Path,
        dataset_manifest_path: Path, row_root: Path,
        progress: Callable[[dict[str, Any]], None] | None = None) \
        -> CohortTrainingBuildV1:
    """Reopen train-only rows and run one fixed natural/control cohort."""
    deadline = time.monotonic_ns() \
        + freeze["resources"]["cohort_wall_cap_nanoseconds"]
    natural = reopen_training_values(
        freeze=freeze, capacity_build=capacity_build,
        population_path=population_path,
        dataset_manifest_path=dataset_manifest_path, row_root=row_root,
        deadline_monotonic_ns=deadline)
    values = training_values_for_cohort(
        natural, cohort_name=cohort_name, capacity_build=capacity_build)
    remaining = deadline - time.monotonic_ns()
    if remaining <= 0:
        raise WorldAfterstateV1ExecutionError(
            "scientific cohort deadline expired before training")
    artifacts = _capacity_artifacts(capacity_build)
    config = AdvantageTrainingConfigV1(**{
        key: value for key, value in freeze["learner"]["config"].items()
        if key != "schema"})
    return train_named_cohort(
        cohort_name=cohort_name, values=values,
        subsplit_manifest=artifacts["p1/subsplit.json"],
        freeze_sha256=freeze["freeze_sha256"],
        shape_name=freeze["learner"]["shape_name"],
        initialization_seeds=freeze["learner"]["initialization_seeds"],
        config=config, pair_cap=freeze["learner"]["pair_cap"],
        schedule_seed=freeze["learner"]["schedule_seed"],
        wall_budget_nanoseconds=remaining,
        member_workers=freeze["learner"]["member_workers"],
        progress=progress)


def build_target_free_prediction_build(
        *, freeze: Mapping[str, Any], population_manifest: Mapping[str, Any],
        audit_manifest: Mapping[str, Any],
        audit_materials: Mapping[str, Sequence[bytes]],
        cohort_builds: Mapping[str, CohortTrainingBuildV1]) \
        -> TargetFreePredictionBuildV1:
    """Build every target-free input and seal all four prediction streams."""
    if type(freeze) is not dict or freeze.get("schema") != FREEZE_SCHEMA \
            or type(cohort_builds) is not dict \
            or set(cohort_builds) != set(TRAINING_COHORTS):
        raise WorldAfterstateV1ExecutionError(
            "target-free prediction request drift")
    try:
        batches, inference_manifest = build_calibration_inference_batch(
            population_manifest, audit_manifest, audit_materials)
        validate_calibration_inference_build(
            batches, inference_manifest, population_manifest,
            audit_manifest, audit_materials)
    except ValueError as exc:
        raise WorldAfterstateV1ExecutionError(
            "target-free inference reconstruction drift") from exc
    expected = freeze["population"]
    if inference_manifest["group_count"] \
            != expected["calibration_group_count"] \
            or inference_manifest["audit_count"] \
            != expected["calibration_audit_count"] \
            or inference_manifest["pair_count"] \
            != expected["calibration_pair_count"]:
        raise WorldAfterstateV1ExecutionError(
            "target-free inference population binding drift")
    prediction_raws = {}
    cohort_manifest_shas = {}
    for name in TRAINING_COHORTS:
        try:
            models, cohort_manifest = reopen_cohort_build(
                cohort_builds[name])
            raw = build_prediction_artifact_bytes(
                models=models, batch=batches[COHORT_INPUT_NAMES[name]],
                cohort_manifest=cohort_manifest)
            _natural, _shuffled, artifact = \
                reopen_prediction_artifact_bytes(raw)
        except ValueError as exc:
            raise WorldAfterstateV1ExecutionError(
                f"target-free {name} prediction drift") from exc
        expected_input = inference_manifest[
            "inference_population_sha256s"][COHORT_INPUT_NAMES[name]]
        if cohort_manifest["freeze_sha256"] != freeze["freeze_sha256"] \
                or artifact["input_population_sha256"] != expected_input:
            raise WorldAfterstateV1ExecutionError(
                "target-free cohort/input binding drift")
        prediction_raws[name] = raw
        cohort_manifest_shas[name] = cohort_manifest["manifest_sha256"]
    files = {
        "calibration-input.json": canonical_json_bytes(inference_manifest),
        **{f"predictions/{name}.json": prediction_raws[name]
           for name in TRAINING_COHORTS},
    }
    body = {
        "schema": PREDICTION_MANIFEST_SCHEMA,
        "freeze_sha256": freeze["freeze_sha256"],
        "population_manifest_sha256":
            population_manifest["manifest_sha256"],
        "audit_manifest_sha256": audit_manifest["manifest_sha256"],
        "calibration_inference_manifest_sha256":
            inference_manifest["manifest_sha256"],
        "cohort_manifest_sha256s": cohort_manifest_shas,
        "prediction_artifact_external_sha256s": {
            name: _sha_bytes(prediction_raws[name])
            for name in TRAINING_COHORTS
        },
        "calibration_labels_opened": False,
        "report_rows_opened": False,
        "provider_audit_rows_opened": False,
        "file_count": len(files), "files": _file_rows(files),
        "authority": dict(PREDICTION_AUTHORITY),
    }
    manifest = {**body, "manifest_sha256": _sha(body)}
    return reopen_target_free_prediction_build(
        TargetFreePredictionBuildV1(
            manifest=manifest,
            files=tuple((path, files[path]) for path in sorted(files))))


def validate_prediction_manifest(value: object) -> None:
    required = {
        "schema", "freeze_sha256", "population_manifest_sha256",
        "audit_manifest_sha256",
        "calibration_inference_manifest_sha256",
        "cohort_manifest_sha256s",
        "prediction_artifact_external_sha256s",
        "calibration_labels_opened", "report_rows_opened",
        "provider_audit_rows_opened", "file_count", "files", "authority",
        "manifest_sha256",
    }
    if type(value) is not dict or set(value) != required \
            or value.get("schema") != PREDICTION_MANIFEST_SCHEMA \
            or value.get("calibration_labels_opened") is not False \
            or value.get("report_rows_opened") is not False \
            or value.get("provider_audit_rows_opened") is not False \
            or value.get("authority") != PREDICTION_AUTHORITY:
        raise WorldAfterstateV1ExecutionError(
            "target-free prediction manifest identity drift")
    for key in (
            "freeze_sha256", "population_manifest_sha256",
            "audit_manifest_sha256",
            "calibration_inference_manifest_sha256", "manifest_sha256"):
        item = value.get(key)
        if type(item) is not str or len(item) != 64 \
                or any(char not in "0123456789abcdef" for char in item):
            raise WorldAfterstateV1ExecutionError(
                "target-free prediction manifest digest drift")
    for key in (
            "cohort_manifest_sha256s",
            "prediction_artifact_external_sha256s"):
        mapping = value.get(key)
        if type(mapping) is not dict \
                or set(mapping) != set(TRAINING_COHORTS) \
                or any(type(item) is not str or len(item) != 64
                       or any(char not in "0123456789abcdef"
                              for char in item)
                       for item in mapping.values()):
            raise WorldAfterstateV1ExecutionError(
                "target-free prediction manifest cohort drift")
    rows = value.get("files")
    if type(rows) is not list or value.get("file_count") != 5 \
            or len(rows) != 5:
        raise WorldAfterstateV1ExecutionError(
            "target-free prediction manifest file population drift")
    paths = set()
    previous = None
    for row in rows:
        if type(row) is not dict or set(row) != {
                "relative_path", "byte_count", "sha256"} \
                or type(row.get("relative_path")) is not str \
                or row["relative_path"] in paths \
                or Path(row["relative_path"]).is_absolute() \
                or ".." in Path(row["relative_path"]).parts \
                or previous is not None \
                and row["relative_path"] <= previous \
                or isinstance(row.get("byte_count"), bool) \
                or not isinstance(row.get("byte_count"), int) \
                or row["byte_count"] <= 0 \
                or type(row.get("sha256")) is not str \
                or len(row["sha256"]) != 64 \
                or any(char not in "0123456789abcdef"
                       for char in row["sha256"]):
            raise WorldAfterstateV1ExecutionError(
                "target-free prediction manifest file row drift")
        paths.add(row["relative_path"])
        previous = row["relative_path"]
    expected_paths = {"calibration-input.json"} | {
        f"predictions/{name}.json" for name in TRAINING_COHORTS}
    body = {key: item for key, item in value.items()
            if key != "manifest_sha256"}
    if paths != expected_paths or value["manifest_sha256"] != _sha(body):
        raise WorldAfterstateV1ExecutionError(
            "target-free prediction manifest reconstruction drift")


def reopen_target_free_prediction_build(
        value: TargetFreePredictionBuildV1) -> TargetFreePredictionBuildV1:
    if type(value) is not TargetFreePredictionBuildV1 \
            or type(value.files) is not tuple:
        raise WorldAfterstateV1ExecutionError(
            "target-free prediction build identity drift")
    validate_prediction_manifest(value.manifest)
    files = dict(value.files)
    if len(files) != len(value.files) \
            or _file_rows(files) != value.manifest["files"]:
        raise WorldAfterstateV1ExecutionError(
            "target-free prediction build file binding drift")
    inference = _canonical(
        files["calibration-input.json"], "calibration inference manifest")
    try:
        validate_calibration_inference_manifest(inference)
    except ValueError as exc:
        raise WorldAfterstateV1ExecutionError(
            "calibration inference manifest drift") from exc
    if inference["manifest_sha256"] \
            != value.manifest["calibration_inference_manifest_sha256"]:
        raise WorldAfterstateV1ExecutionError(
            "calibration inference cross-binding drift")
    for name in TRAINING_COHORTS:
        raw = files[f"predictions/{name}.json"]
        try:
            _natural, _shuffled, artifact = \
                reopen_prediction_artifact_bytes(raw)
        except ValueError as exc:
            raise WorldAfterstateV1ExecutionError(
                f"target-free {name} prediction reopen drift") from exc
        expected_input = inference[
            "inference_population_sha256s"][COHORT_INPUT_NAMES[name]]
        if artifact["cohort_name"] != name \
                or artifact["freeze_sha256"] \
                != value.manifest["freeze_sha256"] \
                or artifact["cohort_manifest_sha256"] \
                != value.manifest["cohort_manifest_sha256s"][name] \
                or artifact["input_population_sha256"] != expected_input \
                or _sha_bytes(raw) != value.manifest[
                    "prediction_artifact_external_sha256s"][name]:
            raise WorldAfterstateV1ExecutionError(
                "target-free prediction cross-binding drift")
    return value


def publish_target_free_prediction_build(
        target: Path, build: TargetFreePredictionBuildV1) -> None:
    build = reopen_target_free_prediction_build(build)
    resolved = target.resolve()
    partial = resolved.parent / f".{resolved.name}.partial"
    resolved.parent.mkdir(parents=True, exist_ok=True)
    if resolved.exists() or resolved.is_symlink() \
            or partial.exists() or partial.is_symlink():
        raise WorldAfterstateV1ExecutionError(
            "target-free prediction namespace occupied")
    partial.mkdir(mode=0o700)
    for path, raw in build.files:
        _write_once(partial / path, raw)
    _write_once(partial / "manifest.json",
                canonical_json_bytes(build.manifest))
    for directory in sorted(
            (path for path in partial.rglob("*") if path.is_dir()),
            key=lambda path: len(path.parts), reverse=True):
        os.chmod(directory, 0o500)
        _fsync_directory(directory)
    _fsync_directory(partial)
    os.rename(partial, resolved)
    os.chmod(resolved, 0o500)
    _fsync_directory(resolved)
    _fsync_directory(resolved.parent)


def reopen_target_free_prediction_directory(
        root: Path) -> TargetFreePredictionBuildV1:
    manifest = _canonical(
        _sealed_read(root / "manifest.json", "prediction manifest"),
        "prediction manifest")
    validate_prediction_manifest(manifest)
    files = tuple((row["relative_path"], _sealed_read(
        root / row["relative_path"], "prediction artifact"))
        for row in manifest["files"])
    expected = {root / "manifest.json"} | {
        root / path for path, _raw in files}
    if {path for path in root.rglob("*") if path.is_file()} != expected:
        raise WorldAfterstateV1ExecutionError(
            "target-free prediction directory population drift")
    return reopen_target_free_prediction_build(
        TargetFreePredictionBuildV1(manifest=manifest, files=files))


def reopen_calibration_labels(
        *, freeze: Mapping[str, Any], population_path: Path,
        dataset_manifest_path: Path, row_root: Path,
        deadline_monotonic_ns: int,
        progress: Callable[[int, int], None] | None = None):
    """Open exactly the V0 calibration fold after predictions are sealed."""
    inputs = freeze["v0_inputs"]
    _population_raw, population = _validate_frozen_input(
        population_path,
        external_sha256=inputs["population_external_sha256"],
        internal_sha256=inputs["population_manifest_sha256"],
        label="calibration V0 population")
    _dataset_raw, dataset = _validate_frozen_input(
        dataset_manifest_path,
        external_sha256=inputs["dataset_external_sha256"],
        internal_sha256=inputs["dataset_manifest_sha256"],
        label="calibration V0 dataset")
    try:
        validate_population_manifest(population)
        validate_dataset_manifest(dataset, population_manifest=population)
        rows = reopen_dataset_manifest(
            dataset, population_manifest=population, row_root=row_root,
            allowed_folds=("calibration",),
            reconstruct_continuations=False,
            reconstruction_workers=freeze["learner"]["row_workers"],
            deadline_monotonic_ns=deadline_monotonic_ns,
            progress=progress)
        eligible_rows = select_manifest_eligible_advantage_rows(
            [reopened for _binding, reopened in rows],
            candidate_counts_by_state_group={
                group["state_group_id"]: group["candidate_count"]
                for group in population["groups"]
                if group["fold"] == "calibration"
            })
        joined = tuple(join_advantage_examples(eligible_rows))
    except ValueError as exc:
        raise WorldAfterstateV1ExecutionError(
            "calibration label reconstruction drift") from exc
    states = {value.pair.state_group_id for value in joined}
    expected = freeze["population"]
    if len(rows) != CALIBRATION_LABEL_ROW_COUNT \
            or len(joined) != CALIBRATION_LABEL_PAIR_COUNT \
            or len(states) != CALIBRATION_ACTION_GROUP_COUNT \
            or len(rows) != expected["calibration_label_row_count"] \
            or len(joined) != expected["calibration_label_pair_count"] \
            or len(states) != expected["calibration_action_group_count"]:
        raise WorldAfterstateV1ExecutionError(
            "calibration label population binding drift")
    return joined


def build_scientific_pipeline(
        *, freeze: Mapping[str, Any], capacity_build: CapacityBuildV1,
        cohort_builds: Mapping[str, CohortTrainingBuildV1],
        prediction_build: TargetFreePredictionBuildV1,
        calibration_pairs: Sequence[Any]) -> PipelineBuildV1:
    prediction_build = reopen_target_free_prediction_build(prediction_build)
    prediction_files = dict(prediction_build.files)
    artifacts = _capacity_artifacts(capacity_build)
    audits = {
        name: evaluate_sealed_predictions(
            prediction_files[f"predictions/{name}.json"],
            calibration_pairs)
        for name in TRAINING_COHORTS
    }
    identical, _shuffled, _artifact = reopen_prediction_artifact_bytes(
        prediction_files["predictions/identical-successor.json"])
    terminal = derive_terminal_result(
        artifacts["p0/label-ceiling.json"],
        natural_result=audits["natural"]["natural_result"],
        control_results={
            name: audits[name]["natural_result"] for name in CONTROL_NAMES
        },
        identical_predictions_exact_zero=bool(identical) and all(
            row.advantage_microlevels == 0 for row in identical),
        world_shuffle_delta_result=audits[
            "natural"]["world_shuffle_delta_result"])
    return build_pipeline_build(
        run_kind="reviewed-p1-pilot",
        label_ceiling=artifacts["p0/label-ceiling.json"],
        subsplit_manifest=artifacts["p1/subsplit.json"],
        control_evidence={
            name: artifacts[f"p1/controls/{name}.json"]
            for name in CONTROL_NAMES
        }, cohort_builds=dict(cohort_builds),
        prediction_artifacts={
            name: prediction_files[f"predictions/{name}.json"]
            for name in TRAINING_COHORTS
        }, audit_results=audits, terminal_result=terminal,
        calibration_inference_manifest=_canonical(
            prediction_files["calibration-input.json"],
            "calibration inference manifest"))


def independently_reconstruct_scientific_pipeline(
        *, expected_pipeline_root: Path, freeze: Mapping[str, Any],
        capacity_build: CapacityBuildV1,
        population_manifest: Mapping[str, Any],
        audit_manifest: Mapping[str, Any],
        audit_materials: Mapping[str, Sequence[bytes]],
        cohort_builds: Mapping[str, CohortTrainingBuildV1],
        prediction_build: TargetFreePredictionBuildV1,
        calibration_pairs: Sequence[Any]) -> PipelineBuildV1:
    """Rebuild inputs, predictions, audits and terminal from source bytes."""
    expected = reopen_pipeline_directory(expected_pipeline_root)
    rebuilt_predictions = build_target_free_prediction_build(
        freeze=freeze, population_manifest=population_manifest,
        audit_manifest=audit_manifest, audit_materials=audit_materials,
        cohort_builds=cohort_builds)
    if rebuilt_predictions != prediction_build:
        raise WorldAfterstateV1ExecutionError(
            "independent prediction reconstruction drift")
    rebuilt = build_scientific_pipeline(
        freeze=freeze, capacity_build=capacity_build,
        cohort_builds=cohort_builds,
        prediction_build=rebuilt_predictions,
        calibration_pairs=calibration_pairs)
    if rebuilt != expected:
        raise WorldAfterstateV1ExecutionError(
            "independent pipeline reconstruction drift")
    return rebuilt


__all__ = [
    "PREDICTION_AUTHORITY", "PREDICTION_MANIFEST_SCHEMA",
    "TargetFreePredictionBuildV1", "WorldAfterstateV1ExecutionError",
    "build_scientific_pipeline", "build_target_free_prediction_build",
    "independently_reconstruct_scientific_pipeline",
    "publish_target_free_prediction_build", "reopen_calibration_labels",
    "reopen_target_free_prediction_build",
    "reopen_target_free_prediction_directory", "reopen_training_values",
    "reopen_scientific_cohort_build", "train_scientific_cohort",
    "training_values_for_cohort",
    "validate_prediction_manifest",
]
