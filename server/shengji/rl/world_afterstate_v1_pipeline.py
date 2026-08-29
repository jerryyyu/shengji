"""Exact top-level artifact binding for the Value V1 P0/P1 pilot.

This module does not train models or open a dataset.  It binds already-built
P0, cohort, prediction, audit, control, and terminal artifacts into one exact
file population and independently reconstructs the terminal decision from
those bytes.  The same path is used by the non-scientific rehearsal and the
eventual reviewed P1 packet.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .belief_contract import canonical_json_bytes
from .world_afterstate_v1 import validate_label_ceiling
from .world_afterstate_v1_audit_controller import (
    reopen_prediction_artifact_bytes, reopen_sealed_audit_result_bytes,
    sealed_audit_result_bytes)
from .world_afterstate_v1_controls import validate_control_evidence
from .world_afterstate_v1_inference import (
    COHORT_INPUT_NAMES, validate_calibration_inference_manifest)
from .world_afterstate_v1_result import (
    CONTROL_NAMES, DECISIONS, derive_terminal_result,
    reopen_terminal_result_bytes, terminal_result_bytes)
from .world_afterstate_v1_schedule import validate_subsplit_manifest
from .world_afterstate_v1_training_controller import (
    CohortTrainingBuildV1, TRAINING_COHORTS, reopen_cohort_build)


PIPELINE_MANIFEST_SCHEMA = "world-afterstate-advantage-pipeline-manifest-v1"
RUN_KINDS = ("non-scientific-rehearsal", "reviewed-p1-pilot")
AUTHORITY = {
    "dataset_opening_authorized": False,
    "training_execution_authorized": False,
    "audit_opening_authorized": False,
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


class WorldAfterstateV1PipelineError(ValueError):
    """A top-level file, component binding, or terminal route drifted."""


@dataclass(frozen=True)
class PipelineBuildV1:
    manifest: dict[str, Any]
    files: tuple[tuple[str, bytes], ...]


def _sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha(value: object) -> str:
    return _sha_bytes(canonical_json_bytes(value))


def _digest(value: object, label: str) -> str:
    if type(value) is not str or len(value) != 64 \
            or any(char not in "0123456789abcdef" for char in value):
        raise WorldAfterstateV1PipelineError(f"{label} drift")
    return value


def _canonical_object(raw: bytes, label: str) -> dict[str, Any]:
    if type(raw) is not bytes:
        raise WorldAfterstateV1PipelineError(f"{label} byte type drift")
    try:
        value = json.loads(raw.decode("ascii"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise WorldAfterstateV1PipelineError(
            f"{label} is not canonical JSON") from exc
    if type(value) is not dict or canonical_json_bytes(value) != raw:
        raise WorldAfterstateV1PipelineError(
            f"{label} is not canonical JSON")
    return value


def _file_rows(files: Mapping[str, bytes]) -> list[dict[str, Any]]:
    rows = []
    for relative_path, raw in sorted(files.items()):
        path = Path(relative_path)
        if type(relative_path) is not str or not relative_path \
                or path.is_absolute() or ".." in path.parts \
                or type(raw) is not bytes:
            raise WorldAfterstateV1PipelineError(
                "pipeline file population drift")
        rows.append({
            "relative_path": relative_path,
            "byte_count": len(raw),
            "sha256": _sha_bytes(raw),
        })
    return rows


def build_pipeline_build(
        *, run_kind: str, label_ceiling: Mapping[str, Any],
        subsplit_manifest: Mapping[str, Any],
        control_evidence: Mapping[str, Mapping[str, Any]],
        cohort_builds: Mapping[str, CohortTrainingBuildV1],
        prediction_artifacts: Mapping[str, bytes],
        audit_results: Mapping[str, Mapping[str, Any]],
        terminal_result: Mapping[str, Any],
        calibration_inference_manifest: Mapping[str, Any] | None = None) \
        -> PipelineBuildV1:
    """Bind a complete P1 result and all bytes needed to reconstruct it."""
    if run_kind not in RUN_KINDS:
        raise WorldAfterstateV1PipelineError("pipeline run kind drift")
    try:
        validate_label_ceiling(label_ceiling)
        validate_subsplit_manifest(subsplit_manifest)
    except ValueError as exc:
        raise WorldAfterstateV1PipelineError(
            "pipeline P0/subsplit component drift") from exc
    if label_ceiling["passed"] is not True:
        raise WorldAfterstateV1PipelineError(
            "complete P1 pipeline requires a passing P0")
    expected_cohorts = set(TRAINING_COHORTS)
    if type(control_evidence) is not dict \
            or set(control_evidence) != set(CONTROL_NAMES) \
            or type(cohort_builds) is not dict \
            or set(cohort_builds) != expected_cohorts \
            or type(prediction_artifacts) is not dict \
            or set(prediction_artifacts) != expected_cohorts \
            or type(audit_results) is not dict \
            or set(audit_results) != expected_cohorts:
        raise WorldAfterstateV1PipelineError(
            "pipeline component population drift")

    for name, evidence in control_evidence.items():
        try:
            validate_control_evidence(evidence)
        except ValueError as exc:
            raise WorldAfterstateV1PipelineError(
                f"pipeline {name} control evidence drift") from exc
        if evidence["name"] != name:
            raise WorldAfterstateV1PipelineError(
                "pipeline control evidence name drift")

    files: dict[str, bytes] = {
        "p0/label-ceiling.json": canonical_json_bytes(label_ceiling),
        "p1/subsplit.json": canonical_json_bytes(subsplit_manifest),
    }
    if run_kind == "reviewed-p1-pilot":
        try:
            validate_calibration_inference_manifest(
                calibration_inference_manifest)
        except ValueError as exc:
            raise WorldAfterstateV1PipelineError(
                "pipeline calibration inference manifest drift") from exc
        files["p1/calibration-input.json"] = canonical_json_bytes(
            calibration_inference_manifest)
    elif calibration_inference_manifest is not None:
        raise WorldAfterstateV1PipelineError(
            "rehearsal carries a scientific calibration input")
    manifests = {}
    freeze_shas = set()
    for name in TRAINING_COHORTS:
        try:
            models, manifest = reopen_cohort_build(cohort_builds[name])
        except ValueError as exc:
            raise WorldAfterstateV1PipelineError(
                f"pipeline {name} cohort drift") from exc
        if len(models) != 8 or manifest["cohort_name"] != name \
                or manifest["subsplit_manifest_sha256"] \
                != subsplit_manifest["manifest_sha256"]:
            raise WorldAfterstateV1PipelineError(
                "pipeline cohort cross-binding drift")
        manifests[name] = manifest
        freeze_shas.add(manifest["freeze_sha256"])
        files[f"p1/cohorts/{name}/manifest.json"] = canonical_json_bytes(
            manifest)
        for member, raw in enumerate(
                cohort_builds[name].selected_checkpoint_raws):
            files[
                f"p1/cohorts/{name}/checkpoints/member-{member:02d}.json"
            ] = raw
    if len(freeze_shas) != 1:
        raise WorldAfterstateV1PipelineError(
            "pipeline cohort freeze binding drift")
    freeze_sha256 = next(iter(freeze_shas))

    opened_predictions = {}
    input_population_shas = {}
    for name in TRAINING_COHORTS:
        raw = prediction_artifacts[name]
        try:
            natural, shuffled, artifact = \
                reopen_prediction_artifact_bytes(raw)
        except ValueError as exc:
            raise WorldAfterstateV1PipelineError(
                f"pipeline {name} prediction drift") from exc
        if artifact["cohort_name"] != name \
                or artifact["freeze_sha256"] != freeze_sha256 \
                or artifact["cohort_manifest_sha256"] \
                != manifests[name]["manifest_sha256"] \
                or artifact["selected_checkpoint_external_sha256s"] \
                != [row["selected_checkpoint_external_sha256"]
                    for row in manifests[name]["members"]] \
                or bool(shuffled) is not (name == "natural"):
            raise WorldAfterstateV1PipelineError(
                "pipeline prediction/cohort binding drift")
        opened_predictions[name] = (natural, shuffled, artifact)
        input_population_shas[name] = artifact["input_population_sha256"]
        files[f"p1/predictions/{name}.json"] = raw
    if run_kind == "reviewed-p1-pilot":
        expected_input_shas = {
            name: calibration_inference_manifest[
                "inference_population_sha256s"][COHORT_INPUT_NAMES[name]]
            for name in TRAINING_COHORTS
        }
        if input_population_shas != expected_input_shas:
            raise WorldAfterstateV1PipelineError(
                "pipeline calibration input/prediction binding drift")

    opened_audits = {}
    audit_population_shas = set()
    for name in TRAINING_COHORTS:
        raw = sealed_audit_result_bytes(audit_results[name])
        try:
            audit = reopen_sealed_audit_result_bytes(raw)
        except ValueError as exc:
            raise WorldAfterstateV1PipelineError(
                f"pipeline {name} audit drift") from exc
        artifact = opened_predictions[name][2]
        if audit["cohort_name"] != name \
                or audit["prediction_artifact_external_sha256"] \
                != _sha_bytes(prediction_artifacts[name]) \
                or audit["prediction_artifact_sha256"] \
                != artifact["artifact_sha256"]:
            raise WorldAfterstateV1PipelineError(
                "pipeline audit/prediction binding drift")
        audit_population_shas.add(audit["audit_population_sha256"])
        opened_audits[name] = audit
        files[f"p1/audits/{name}.json"] = raw
    if len(audit_population_shas) != 1:
        raise WorldAfterstateV1PipelineError(
            "pipeline audit population binding drift")

    identical_rows = opened_predictions["identical-successor"][0]
    identical_exact_zero = bool(identical_rows) and all(
        row.advantage_microlevels == 0 for row in identical_rows)
    rederived_terminal = derive_terminal_result(
        label_ceiling,
        natural_result=opened_audits["natural"]["natural_result"],
        control_results={
            name: opened_audits[name]["natural_result"]
            for name in CONTROL_NAMES
        },
        identical_predictions_exact_zero=identical_exact_zero,
        world_shuffle_delta_result=opened_audits[
            "natural"]["world_shuffle_delta_result"])
    terminal_raw = terminal_result_bytes(terminal_result)
    if rederived_terminal != terminal_result \
            or reopen_terminal_result_bytes(terminal_raw) != terminal_result:
        raise WorldAfterstateV1PipelineError(
            "pipeline terminal reconstruction drift")
    files["p1/terminal.json"] = terminal_raw
    for name, evidence in control_evidence.items():
        files[f"p1/controls/{name}.json"] = canonical_json_bytes(evidence)

    file_rows = _file_rows(files)
    body = {
        "schema": PIPELINE_MANIFEST_SCHEMA,
        "run_kind": run_kind,
        "non_scientific_rehearsal": run_kind == "non-scientific-rehearsal",
        "freeze_sha256": freeze_sha256,
        "label_ceiling_result_sha256": label_ceiling["result_sha256"],
        "subsplit_manifest_sha256": subsplit_manifest["manifest_sha256"],
        "calibration_inference_manifest_sha256": (
            calibration_inference_manifest["manifest_sha256"]
            if calibration_inference_manifest is not None else None),
        "cohort_manifest_sha256s": {
            name: manifests[name]["manifest_sha256"]
            for name in TRAINING_COHORTS
        },
        "prediction_artifact_external_sha256s": {
            name: _sha_bytes(prediction_artifacts[name])
            for name in TRAINING_COHORTS
        },
        "audit_result_sha256s": {
            name: opened_audits[name]["result_sha256"]
            for name in TRAINING_COHORTS
        },
        "audit_population_sha256": next(iter(audit_population_shas)),
        "terminal_result_sha256": terminal_result["result_sha256"],
        "terminal_decision": terminal_result["decision"],
        "prediction_bytes_sealed_before_audit_api": True,
        "audit_labels_opened": True,
        "report_rows_opened": False,
        "file_count": len(file_rows),
        "files": file_rows,
        "authority": dict(AUTHORITY),
    }
    manifest = {**body, "manifest_sha256": _sha(body)}
    validate_pipeline_manifest(manifest)
    return PipelineBuildV1(
        manifest=manifest,
        files=tuple((path, files[path]) for path in sorted(files)))


def validate_pipeline_manifest(value: object) -> None:
    required = {
        "schema", "run_kind", "non_scientific_rehearsal",
        "freeze_sha256", "label_ceiling_result_sha256",
        "subsplit_manifest_sha256",
        "calibration_inference_manifest_sha256",
        "cohort_manifest_sha256s",
        "prediction_artifact_external_sha256s", "audit_result_sha256s",
        "audit_population_sha256", "terminal_result_sha256",
        "terminal_decision", "prediction_bytes_sealed_before_audit_api",
        "audit_labels_opened", "report_rows_opened", "file_count", "files",
        "authority", "manifest_sha256",
    }
    if type(value) is not dict or set(value) != required \
            or value.get("schema") != PIPELINE_MANIFEST_SCHEMA \
            or value.get("run_kind") not in RUN_KINDS \
            or value.get("non_scientific_rehearsal") \
            is not (value.get("run_kind") == "non-scientific-rehearsal") \
            or (value.get("calibration_inference_manifest_sha256") is None) \
            is not (value.get("run_kind") == "non-scientific-rehearsal") \
            or value.get("prediction_bytes_sealed_before_audit_api") is not True \
            or value.get("audit_labels_opened") is not True \
            or value.get("report_rows_opened") is not False \
            or value.get("terminal_decision") not in DECISIONS \
            or value.get("authority") != AUTHORITY:
        raise WorldAfterstateV1PipelineError(
            "pipeline manifest identity drift")
    for name in (
            "freeze_sha256", "label_ceiling_result_sha256",
            "subsplit_manifest_sha256", "audit_population_sha256",
            "terminal_result_sha256", "manifest_sha256"):
        _digest(value.get(name), f"pipeline manifest {name}")
    if value["calibration_inference_manifest_sha256"] is not None:
        _digest(value["calibration_inference_manifest_sha256"],
                "pipeline calibration inference manifest SHA-256")
    for field, names in (
            ("cohort_manifest_sha256s", set(TRAINING_COHORTS)),
            ("prediction_artifact_external_sha256s", set(TRAINING_COHORTS)),
            ("audit_result_sha256s", set(TRAINING_COHORTS))):
        mapping = value.get(field)
        if type(mapping) is not dict or set(mapping) != names:
            raise WorldAfterstateV1PipelineError(
                "pipeline manifest component population drift")
        for digest in mapping.values():
            _digest(digest, f"pipeline manifest {field}")
    rows = value.get("files")
    count = value.get("file_count")
    if type(rows) is not list or isinstance(count, bool) \
            or not isinstance(count, int) or count <= 0 \
            or count != len(rows):
        raise WorldAfterstateV1PipelineError(
            "pipeline manifest file population drift")
    previous = None
    paths = set()
    for row in rows:
        if type(row) is not dict or set(row) != {
                "relative_path", "byte_count", "sha256"} \
                or type(row.get("relative_path")) is not str \
                or not row["relative_path"] \
                or isinstance(row.get("byte_count"), bool) \
                or not isinstance(row.get("byte_count"), int) \
                or row["byte_count"] <= 0:
            raise WorldAfterstateV1PipelineError(
                "pipeline manifest file row drift")
        path = Path(row["relative_path"])
        if path.is_absolute() or ".." in path.parts \
                or row["relative_path"] in paths \
                or previous is not None and row["relative_path"] <= previous:
            raise WorldAfterstateV1PipelineError(
                "pipeline manifest file order drift")
        paths.add(row["relative_path"])
        previous = row["relative_path"]
        _digest(row.get("sha256"), "pipeline manifest file SHA-256")
    body = {key: item for key, item in value.items()
            if key != "manifest_sha256"}
    if value["manifest_sha256"] != _sha(body):
        raise WorldAfterstateV1PipelineError(
            "pipeline manifest reconstruction drift")


def reopen_pipeline_build(value: PipelineBuildV1) -> PipelineBuildV1:
    """Reopen every byte and independently rederive the terminal result."""
    if type(value) is not PipelineBuildV1:
        raise WorldAfterstateV1PipelineError("pipeline build type drift")
    validate_pipeline_manifest(value.manifest)
    if type(value.files) is not tuple \
            or any(type(row) is not tuple or len(row) != 2
                   or type(row[0]) is not str or type(row[1]) is not bytes
                   for row in value.files):
        raise WorldAfterstateV1PipelineError(
            "pipeline build file population drift")
    files = dict(value.files)
    if len(files) != len(value.files) \
            or _file_rows(files) != value.manifest["files"]:
        raise WorldAfterstateV1PipelineError(
            "pipeline build file binding drift")

    p0 = _canonical_object(files["p0/label-ceiling.json"], "pipeline P0")
    subsplit = _canonical_object(files["p1/subsplit.json"],
                                 "pipeline subsplit")
    evidence = {
        name: _canonical_object(
            files[f"p1/controls/{name}.json"],
            f"pipeline {name} control")
        for name in CONTROL_NAMES
    }
    cohorts = {}
    predictions = {}
    audits = {}
    for name in TRAINING_COHORTS:
        manifest = _canonical_object(
            files[f"p1/cohorts/{name}/manifest.json"],
            f"pipeline {name} cohort manifest")
        checkpoints = tuple(
            files[f"p1/cohorts/{name}/checkpoints/member-{member:02d}.json"]
            for member in range(8))
        cohorts[name] = CohortTrainingBuildV1(
            manifest=manifest, selected_checkpoint_raws=checkpoints)
        predictions[name] = files[f"p1/predictions/{name}.json"]
        audits[name] = reopen_sealed_audit_result_bytes(
            files[f"p1/audits/{name}.json"])
    terminal = reopen_terminal_result_bytes(files["p1/terminal.json"])
    calibration_input = None
    if value.manifest["run_kind"] == "reviewed-p1-pilot":
        calibration_input = _canonical_object(
            files["p1/calibration-input.json"],
            "pipeline calibration input")
    rebuilt = build_pipeline_build(
        run_kind=value.manifest["run_kind"], label_ceiling=p0,
        subsplit_manifest=subsplit, control_evidence=evidence,
        cohort_builds=cohorts, prediction_artifacts=predictions,
        audit_results=audits, terminal_result=terminal,
        calibration_inference_manifest=calibration_input)
    if rebuilt.manifest != value.manifest or rebuilt.files != value.files:
        raise WorldAfterstateV1PipelineError(
            "pipeline build reconstruction drift")
    return rebuilt


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


def publish_pipeline_build(target: Path, build: PipelineBuildV1) -> None:
    reopened = reopen_pipeline_build(build)
    if not isinstance(target, Path):
        raise WorldAfterstateV1PipelineError(
            "pipeline publication target drift")
    parent = target.resolve().parent
    resolved = parent / target.name
    partial = parent / f".{target.name}.partial"
    parent.mkdir(parents=True, exist_ok=True)
    if resolved.exists() or resolved.is_symlink() \
            or partial.exists() or partial.is_symlink():
        raise WorldAfterstateV1PipelineError(
            "pipeline publication namespace occupied")
    partial.mkdir(mode=0o700)
    for relative_path, raw in reopened.files:
        _write_once(partial / relative_path, raw)
    _write_once(partial / "manifest.json",
                canonical_json_bytes(reopened.manifest))
    for directory in sorted(
            (path for path in partial.rglob("*") if path.is_dir()),
            key=lambda path: len(path.parts), reverse=True):
        os.chmod(directory, 0o500)
        _fsync_directory(directory)
    _fsync_directory(partial)
    os.rename(partial, resolved)
    os.chmod(resolved, 0o500)
    _fsync_directory(resolved)
    _fsync_directory(parent)


def _sealed_read(path: Path) -> bytes:
    if path.is_symlink():
        raise WorldAfterstateV1PipelineError(
            "pipeline artifact path is a symlink")
    with path.open("rb") as handle:
        before = os.fstat(handle.fileno())
        raw = handle.read()
        after = os.fstat(handle.fileno())
    identity = lambda value: (
        value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns,
        value.st_ctime_ns)
    if identity(before) != identity(after) or before.st_nlink != 1 \
            or stat.S_IMODE(before.st_mode) != 0o400 \
            or before.st_size != len(raw) \
            or not stat.S_ISREG(before.st_mode):
        raise WorldAfterstateV1PipelineError(
            "pipeline artifact is mutable")
    return raw


def reopen_pipeline_directory(root: Path) -> PipelineBuildV1:
    if not isinstance(root, Path) or not root.is_dir() or root.is_symlink():
        raise WorldAfterstateV1PipelineError("pipeline root identity drift")
    manifest = _canonical_object(
        _sealed_read(root / "manifest.json"), "pipeline manifest")
    validate_pipeline_manifest(manifest)
    files = tuple((row["relative_path"], _sealed_read(
        root / row["relative_path"])) for row in manifest["files"])
    expected = {root / "manifest.json"} | {
        root / relative_path for relative_path, _raw in files
    }
    if {path for path in root.rglob("*") if path.is_file()} != expected:
        raise WorldAfterstateV1PipelineError(
            "pipeline directory file population drift")
    return reopen_pipeline_build(PipelineBuildV1(
        manifest=manifest, files=files))


__all__ = [
    "AUTHORITY", "PipelineBuildV1", "RUN_KINDS",
    "WorldAfterstateV1PipelineError", "build_pipeline_build",
    "publish_pipeline_build", "reopen_pipeline_build",
    "reopen_pipeline_directory", "validate_pipeline_manifest",
]
