"""One-shot held-out opening and deterministic E4 terminal reconstruction.

The controller publishes ``terminal.partial/attempt.json`` durably before it
opens either held-out fold.  It then scores the natural experiment, executes
the three negative controls, proves root-rotation invariance through a real
cyclic engine-seat relabeling, runs the five named corruptions, and seals one
all-authority-false terminal.  Immediate verification reopens immutable rows
without re-running labels; a separately invoked independent verification can
re-run every engine continuation through ``reconstruct_continuations=True``.
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
from .world_afterstate import (
    WorldAfterstateExampleV0, build_root_rotated_afterstate_tensors)
from .world_afterstate_controls import (
    build_mutation_refusal_evidence, complete_world_shuffle,
    geometry_preserving_label_permutation, preaction_replacement_evidence,
    tensor_sha256)
from .world_afterstate_controller import reopen_scientific_dataset
from .world_afterstate_dataset import ReopenedDatasetRowV0
from .world_afterstate_evaluation import (
    PredictionV0, build_train_prior, evaluate_action_gate,
    evaluate_primary_gate, predict_batch)
from .world_afterstate_population import validate_population_manifest
from .world_afterstate_terminal import (
    build_control_evidence, build_terminal_result,
    validate_control_evidence, validate_terminal_result)
from .world_afterstate_training import (
    COHORT_SIZE, collate_training_examples)
from .world_afterstate_training_controller import reopen_training_build


ATTEMPT_SCHEMA = "world-afterstate-e4-report-attempt-v0"
EVIDENCE_SCHEMA = "world-afterstate-e4-terminal-evidence-v0"
MANIFEST_SCHEMA = "world-afterstate-e4-terminal-manifest-v0"
ATTEMPT_NAME = "attempt.json"
EVIDENCE_NAME = "evidence.json"
TERMINAL_NAME = "terminal.json"
MANIFEST_NAME = "manifest.json"
TERMINAL_CONTROLLER_AUTHORITY = {
    "retry_authorized": False,
    "gameplay_authorized": False,
    "strength_claim_authorized": False,
    "merge_authorized": False,
    "promotion_authorized": False,
    "deployment_authorized": False,
}


class WorldAfterstateTerminalControllerError(ValueError):
    """A held-out attempt, prediction, control, or artifact drifted."""


def _check_deadline(deadline_monotonic_ns: int | None) -> None:
    if deadline_monotonic_ns is not None and (
            isinstance(deadline_monotonic_ns, bool)
            or not isinstance(deadline_monotonic_ns, int)
            or deadline_monotonic_ns <= 0):
        raise WorldAfterstateTerminalControllerError(
            "terminal deadline identity drift")
    if deadline_monotonic_ns is not None \
            and time.monotonic_ns() >= deadline_monotonic_ns:
        raise WorldAfterstateTerminalControllerError(
            "terminal deadline expired")


@dataclass(frozen=True)
class DerivedTerminalV0:
    evidence: dict[str, Any]
    terminal: dict[str, Any]


def _sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha(value: object) -> str:
    return _sha_bytes(canonical_json_bytes(value))


def _digest(value: object, label: str) -> str:
    if type(value) is not str or len(value) != 64 \
            or any(char not in "0123456789abcdef" for char in value):
        raise WorldAfterstateTerminalControllerError(f"{label} drift")
    return value


def _unique_rows(
        rows: Sequence[tuple[Mapping[str, Any], ReopenedDatasetRowV0]], *,
        preaction: bool = False) \
        -> tuple[tuple[str, int, ReopenedDatasetRowV0,
                       WorldAfterstateExampleV0], ...]:
    if type(rows) not in (list, tuple) or not rows:
        raise WorldAfterstateTerminalControllerError(
            "terminal row population drift")
    result = {}
    bindings = {}
    for binding, reopened in rows:
        if type(binding) is not dict \
                or type(reopened) is not ReopenedDatasetRowV0 \
                or type(reopened.evaluation_outcome.state_group_id) is not str:
            raise WorldAfterstateTerminalControllerError(
                "terminal row identity drift")
        outcome = reopened.evaluation_outcome
        example = reopened.preaction_example if preaction else reopened.example
        if type(example) is not WorldAfterstateExampleV0:
            raise WorldAfterstateTerminalControllerError(
                "terminal preaction population drift")
        key = (outcome.state_group_id, outcome.candidate_index)
        value = (tensor_sha256(example.tensors), example.successor_sha256)
        if key in bindings and bindings[key] != value:
            raise WorldAfterstateTerminalControllerError(
                "terminal repeated candidate changed model inputs")
        bindings[key] = value
        result.setdefault(key, (outcome.state_group_id,
                                outcome.candidate_index, reopened, example))
    return tuple(result[key] for key in sorted(result))


def _predict(
        models: Sequence, unique_rows: Sequence[
            tuple[str, int, ReopenedDatasetRowV0,
                  WorldAfterstateExampleV0]], *, split: str,
        batch_size: int) -> tuple[PredictionV0, ...]:
    if type(models) not in (list, tuple) or len(models) != COHORT_SIZE \
            or type(unique_rows) not in (list, tuple) or not unique_rows \
            or isinstance(batch_size, bool) or not isinstance(batch_size, int) \
            or batch_size <= 0:
        raise WorldAfterstateTerminalControllerError(
            "terminal prediction request drift")
    result = []
    for start in range(0, len(unique_rows), batch_size):
        chunk = unique_rows[start:start + batch_size]
        keys = [f"{state}:{candidate}" for state, candidate, _, _ in chunk]
        examples = [example for _, _, _, example in chunk]
        batch = collate_training_examples(keys, examples, split=split)
        state_ids = [state for state, _, _, _ in chunk]
        candidates = [candidate for _, candidate, _, _ in chunk]
        for member, model in enumerate(models):
            result.extend(predict_batch(
                model, batch, member_index=member,
                state_group_ids=state_ids, candidate_indexes=candidates))
    return tuple(result)


def _prediction_binding_sha256(
        predictions: Sequence[PredictionV0], *, state_group_id: str,
        candidate_index: int) -> str:
    rows = []
    for prediction in predictions:
        if prediction.state_group_id == state_group_id \
                and prediction.candidate_index == candidate_index:
            prediction.validate()
            rows.append({
                "member_index": prediction.member_index,
                "model_state_sha256": prediction.model_state_sha256,
                "successor_sha256": prediction.successor_sha256,
                "probabilities_ppb": list(prediction.probabilities_ppb),
            })
    rows.sort(key=lambda row: row["member_index"])
    if [row["member_index"] for row in rows] != list(range(COHORT_SIZE)):
        raise WorldAfterstateTerminalControllerError(
            "rotation prediction population drift")
    return _sha(rows)


def derive_terminal_evidence(
        *, freeze: Mapping[str, Any],
        population_manifest: Mapping[str, Any], models: Sequence,
        train_rows: Sequence[
            tuple[Mapping[str, Any], ReopenedDatasetRowV0]],
        report_rows: Sequence[
            tuple[Mapping[str, Any], ReopenedDatasetRowV0]],
        provider_rows: Sequence[
            tuple[Mapping[str, Any], ReopenedDatasetRowV0]],
        deadline_monotonic_ns: int | None = None,
        progress: Callable[[str, int, int], None] | None = None) \
        -> DerivedTerminalV0:
    validate_population_manifest(population_manifest)
    if type(freeze) is not dict or freeze.get("learner", {}).get(
            "member_count") != COHORT_SIZE:
        raise WorldAfterstateTerminalControllerError(
            "terminal freeze identity drift")
    freeze_sha = _digest(freeze.get("freeze_sha256"),
                         "terminal freeze SHA-256")
    batch_size = freeze["learner"]["batch_size"]
    train_outcomes = tuple(
        row.evaluation_outcome for _, row in train_rows)
    report_outcomes = tuple(
        row.evaluation_outcome for _, row in report_rows)
    provider_outcomes = tuple(
        row.evaluation_outcome for _, row in provider_rows)
    prior = build_train_prior(train_outcomes)
    report_unique = _unique_rows(report_rows)
    provider_unique = _unique_rows(provider_rows)
    if progress is not None:
        progress("natural-predictions", 0, 6)
    _check_deadline(deadline_monotonic_ns)
    report_predictions = _predict(
        models, report_unique, split="report", batch_size=batch_size)
    provider_predictions = _predict(
        models, provider_unique, split="provider-audit",
        batch_size=batch_size)
    primary = evaluate_primary_gate(report_outcomes, report_predictions, prior)
    action = evaluate_action_gate(provider_outcomes, provider_predictions)

    if progress is not None:
        progress("label-permutation", 1, 6)
    _check_deadline(deadline_monotonic_ns)
    permuted_outcomes, permutation_transform = \
        geometry_preserving_label_permutation(report_outcomes)
    permutation_primary = evaluate_primary_gate(
        permuted_outcomes, report_predictions, prior,
        namespace="geometry-preserving-label-permutation")

    if progress is not None:
        progress("preaction-control", 2, 6)
    _check_deadline(deadline_monotonic_ns)
    provider_preaction = _unique_rows(provider_rows, preaction=True)
    preaction_transform = preaction_replacement_evidence(
        [f"{state}:{candidate}" for state, candidate, _, _
         in provider_unique],
        [example for _, _, _, example in provider_unique],
        [example for _, _, _, example in provider_preaction])
    preaction_predictions = _predict(
        models, provider_preaction, split="provider-audit",
        batch_size=batch_size)
    preaction_action = evaluate_action_gate(
        provider_outcomes, preaction_predictions)

    if progress is not None:
        progress("world-shuffle-control", 3, 6)
    _check_deadline(deadline_monotonic_ns)
    report_keys = [f"{state}:{candidate}" for state, candidate, _, _
                   in report_unique]
    shuffled_examples, world_shuffle_transform = complete_world_shuffle(
        report_keys, [example for _, _, _, example in report_unique])
    shuffled_unique = tuple(
        (state, candidate, reopened, example)
        for (state, candidate, reopened, _), example in zip(
            report_unique, shuffled_examples, strict=True))
    shuffled_predictions = _predict(
        models, shuffled_unique, split="report", batch_size=batch_size)
    world_shuffle_primary = evaluate_primary_gate(
        report_outcomes, shuffled_predictions, prior,
        namespace="complete-world-shuffle")

    if progress is not None:
        progress("root-rotation", 4, 6)
    _check_deadline(deadline_monotonic_ns)
    rotated_unique = []
    rotation_pairs = []
    for index, (state, candidate, reopened, example) in enumerate(
            report_unique):
        if type(reopened.row) is not dict:
            raise WorldAfterstateTerminalControllerError(
                "rotation row bytes unavailable")
        rotated = WorldAfterstateExampleV0(
            tensors=build_root_rotated_afterstate_tensors(
                reopened.row["audit"], 1 + index % 3),
            signed_level_category=example.signed_level_category,
            successor_sha256=example.successor_sha256)
        rotated.validate()
        rotated_unique.append((state, candidate, reopened, rotated))
    rotated_predictions = _predict(
        models, tuple(rotated_unique), split="report", batch_size=batch_size)
    for base, rotated in zip(report_unique, rotated_unique, strict=True):
        state, candidate, _, base_example = base
        _, _, _, rotated_example = rotated
        rotation_pairs.append({
            "base_input_sha256": tensor_sha256(base_example.tensors),
            "rotated_input_sha256": tensor_sha256(rotated_example.tensors),
            "base_prediction_sha256": _prediction_binding_sha256(
                report_predictions, state_group_id=state,
                candidate_index=candidate),
            "rotated_prediction_sha256": _prediction_binding_sha256(
                rotated_predictions, state_group_id=state,
                candidate_index=candidate),
        })

    if progress is not None:
        progress("mutation-refusals", 5, 6)
    _check_deadline(deadline_monotonic_ns)
    groups = {group["state_group_id"]: group
              for group in population_manifest["groups"]}
    mutation_evidence = build_mutation_refusal_evidence(
        [row for _, row in report_rows], groups)
    controls = build_control_evidence(
        permutation_primary=permutation_primary,
        permutation_transform=permutation_transform,
        preaction_action=preaction_action,
        preaction_transform=preaction_transform,
        world_shuffle_primary=world_shuffle_primary,
        world_shuffle_transform=world_shuffle_transform,
        rotation_pairs=rotation_pairs,
        mutation_evidence=mutation_evidence)
    terminal = build_terminal_result(
        freeze_sha256=freeze_sha, primary=primary, action=action,
        controls=controls)
    body = {
        "schema": EVIDENCE_SCHEMA,
        "freeze_sha256": freeze_sha,
        "train_prior_sha256": prior.train_population_sha256,
        "primary": primary,
        "action": action,
        "permutation_primary": permutation_primary,
        "permutation_transform": permutation_transform,
        "preaction_action": preaction_action,
        "preaction_transform": preaction_transform,
        "world_shuffle_primary": world_shuffle_primary,
        "world_shuffle_transform": world_shuffle_transform,
        "rotation_pairs": rotation_pairs,
        "mutation_evidence": mutation_evidence,
        "controls": controls,
        "report_decision_consumption_count": 1,
        "authority": dict(TERMINAL_CONTROLLER_AUTHORITY),
    }
    evidence = {**body, "evidence_sha256": _sha(body)}
    validate_terminal_evidence(evidence, terminal=terminal)
    _check_deadline(deadline_monotonic_ns)
    if progress is not None:
        progress("terminal-derived", 6, 6)
    return DerivedTerminalV0(evidence=evidence, terminal=terminal)


def validate_terminal_evidence(
        value: Mapping[str, Any], *, terminal: Mapping[str, Any]) -> None:
    required = {
        "schema", "freeze_sha256", "train_prior_sha256", "primary",
        "action", "permutation_primary", "permutation_transform",
        "preaction_action", "preaction_transform", "world_shuffle_primary",
        "world_shuffle_transform", "rotation_pairs", "mutation_evidence",
        "controls", "report_decision_consumption_count", "authority",
        "evidence_sha256",
    }
    if type(value) is not dict or set(value) != required \
            or value.get("schema") != EVIDENCE_SCHEMA \
            or value.get("authority") != TERMINAL_CONTROLLER_AUTHORITY \
            or value.get("report_decision_consumption_count") != 1:
        raise WorldAfterstateTerminalControllerError(
            "terminal evidence schema drift")
    for key in ("freeze_sha256", "train_prior_sha256", "evidence_sha256"):
        _digest(value.get(key), key)
    expected_controls = build_control_evidence(
        permutation_primary=value["permutation_primary"],
        permutation_transform=value["permutation_transform"],
        preaction_action=value["preaction_action"],
        preaction_transform=value["preaction_transform"],
        world_shuffle_primary=value["world_shuffle_primary"],
        world_shuffle_transform=value["world_shuffle_transform"],
        rotation_pairs=value["rotation_pairs"],
        mutation_evidence=value["mutation_evidence"])
    if canonical_json_bytes(expected_controls) \
            != canonical_json_bytes(value["controls"]):
        raise WorldAfterstateTerminalControllerError(
            "terminal control reconstruction drift")
    expected_terminal = build_terminal_result(
        freeze_sha256=value["freeze_sha256"], primary=value["primary"],
        action=value["action"], controls=value["controls"])
    if canonical_json_bytes(expected_terminal) \
            != canonical_json_bytes(dict(terminal)):
        raise WorldAfterstateTerminalControllerError(
            "terminal result cross-binding drift")
    body = {key: item for key, item in value.items()
            if key != "evidence_sha256"}
    if value["evidence_sha256"] != _sha(body):
        raise WorldAfterstateTerminalControllerError(
            "terminal evidence reconstruction drift")


def _attempt(*, freeze_sha256: str, dataset_manifest_sha256: str,
             training_manifest_sha256: str,
             started_monotonic_ns: int,
             wall_budget_nanoseconds: int) -> dict[str, Any]:
    for label, value in (("freeze", freeze_sha256),
                         ("dataset manifest", dataset_manifest_sha256),
                         ("training manifest", training_manifest_sha256)):
        _digest(value, f"attempt {label} SHA-256")
    if isinstance(started_monotonic_ns, bool) \
            or not isinstance(started_monotonic_ns, int) \
            or started_monotonic_ns < 0 \
            or isinstance(wall_budget_nanoseconds, bool) \
            or not isinstance(wall_budget_nanoseconds, int) \
            or wall_budget_nanoseconds <= 0:
        raise WorldAfterstateTerminalControllerError(
            "terminal attempt deadline drift")
    body = {
        "schema": ATTEMPT_SCHEMA,
        "freeze_sha256": freeze_sha256,
        "dataset_manifest_sha256": dataset_manifest_sha256,
        "training_manifest_sha256": training_manifest_sha256,
        "started_monotonic_ns": started_monotonic_ns,
        "wall_budget_nanoseconds": wall_budget_nanoseconds,
        "deadline_monotonic_ns": (
            started_monotonic_ns + wall_budget_nanoseconds),
        "report_decision_consumption_count": 1,
        "published_before_held_out_open": True,
        "retry_authorized": False,
    }
    return {**body, "attempt_sha256": _sha(body)}


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


def _sealed_read(path: Path) -> bytes:
    if path.is_symlink():
        raise WorldAfterstateTerminalControllerError(
            "terminal artifact path is a symlink")
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
        raise WorldAfterstateTerminalControllerError(
            "terminal artifact is mutable or changed while read")
    return raw


def _canonical(raw: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("ascii"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise WorldAfterstateTerminalControllerError(
            f"{label} is not canonical JSON") from exc
    if type(value) is not dict or canonical_json_bytes(value) != raw:
        raise WorldAfterstateTerminalControllerError(
            f"{label} is not canonical JSON")
    return value


def _manifest(*, attempt_raw: bytes, evidence_raw: bytes,
              terminal_raw: bytes) -> dict[str, Any]:
    body = {
        "schema": MANIFEST_SCHEMA,
        "files": {
            ATTEMPT_NAME: _sha_bytes(attempt_raw),
            EVIDENCE_NAME: _sha_bytes(evidence_raw),
            TERMINAL_NAME: _sha_bytes(terminal_raw),
        },
        "authority": dict(TERMINAL_CONTROLLER_AUTHORITY),
    }
    return {**body, "manifest_sha256": _sha(body)}


def run_open_report(
        target: Path, *, freeze: Mapping[str, Any],
        population_manifest: Mapping[str, Any], dataset_root: Path,
        training_root: Path,
        progress: Callable[[str, int, int], None] | None = None) \
        -> dict[str, Any]:
    """Consume one decision slot, seal a result, and reconstruct it once."""
    if not isinstance(target, Path):
        raise WorldAfterstateTerminalControllerError(
            "terminal target drift")
    freeze_sha = _digest(freeze.get("freeze_sha256"),
                         "terminal freeze SHA-256")
    report_wall_seconds = freeze.get("gates", {}).get(
        "report_wall_cap_seconds")
    if isinstance(report_wall_seconds, bool) \
            or not isinstance(report_wall_seconds, int) \
            or report_wall_seconds <= 0:
        raise WorldAfterstateTerminalControllerError(
            "terminal report wall budget drift")
    started = time.monotonic_ns()
    wall_budget_nanoseconds = report_wall_seconds * 1_000_000_000
    deadline = started + wall_budget_nanoseconds
    train_manifest, train_rows = reopen_scientific_dataset(
        dataset_root, population_manifest=population_manifest,
        allowed_folds=("train",),
        reconstruct_continuations=False)
    training_manifest, models = reopen_training_build(training_root)
    if training_manifest["freeze_sha256"] != freeze_sha \
            or training_manifest["dataset_manifest_sha256"] \
            != train_manifest["manifest_sha256"]:
        raise WorldAfterstateTerminalControllerError(
            "terminal training/dataset binding drift")
    parent = target.resolve().parent
    resolved = parent / target.name
    partial = parent / f".{target.name}.partial"
    parent.mkdir(parents=True, exist_ok=True)
    if resolved.exists() or resolved.is_symlink() \
            or partial.exists() or partial.is_symlink():
        raise WorldAfterstateTerminalControllerError(
            "terminal decision slot occupied")
    partial.mkdir(mode=0o700)
    attempt = _attempt(
        freeze_sha256=freeze_sha,
        dataset_manifest_sha256=train_manifest["manifest_sha256"],
        training_manifest_sha256=training_manifest["manifest_sha256"],
        started_monotonic_ns=started,
        wall_budget_nanoseconds=wall_budget_nanoseconds)
    attempt_raw = canonical_json_bytes(attempt)
    _write_once(partial / ATTEMPT_NAME, attempt_raw)
    # Make the consumed slot itself durable before either held-out fold opens.
    _fsync_directory(partial)
    _fsync_directory(parent)
    try:
        _check_deadline(deadline)
        _report_manifest, report_rows = reopen_scientific_dataset(
            dataset_root, population_manifest=population_manifest,
            allowed_folds=("report",))
        _provider_manifest, provider_rows = reopen_scientific_dataset(
            dataset_root, population_manifest=population_manifest,
            allowed_folds=("provider-audit",))
        derived = derive_terminal_evidence(
            freeze=freeze, population_manifest=population_manifest,
            models=models, train_rows=train_rows, report_rows=report_rows,
            provider_rows=provider_rows,
            deadline_monotonic_ns=deadline, progress=progress)
        _check_deadline(deadline)
        evidence_raw = canonical_json_bytes(derived.evidence)
        terminal_raw = canonical_json_bytes(derived.terminal)
        _write_once(partial / EVIDENCE_NAME, evidence_raw)
        _write_once(partial / TERMINAL_NAME, terminal_raw)
        manifest = _manifest(
            attempt_raw=attempt_raw, evidence_raw=evidence_raw,
            terminal_raw=terminal_raw)
        _write_once(partial / MANIFEST_NAME, canonical_json_bytes(manifest))
        _fsync_directory(partial)
        os.rename(partial, resolved)
        os.chmod(resolved, 0o500)
        _fsync_directory(resolved)
        _fsync_directory(parent)
    except BaseException:
        # A failed attempt is deliberately not deleted or reusable.
        raise
    # Mandatory immediate reconstruction uses immutable stored labels and
    # cannot consume another scientific decision.
    verified = verify_terminal_artifact(
        resolved, freeze=freeze, population_manifest=population_manifest,
        dataset_root=dataset_root, training_root=training_root,
        reconstruct_continuations=False)
    return verified


def verify_terminal_artifact(
        root: Path, *, freeze: Mapping[str, Any],
        population_manifest: Mapping[str, Any], dataset_root: Path,
        training_root: Path, reconstruct_continuations: bool,
        progress: Callable[[str, int, int], None] | None = None) \
        -> dict[str, Any]:
    if not isinstance(root, Path) or not root.is_dir() or root.is_symlink() \
            or type(reconstruct_continuations) is not bool:
        raise WorldAfterstateTerminalControllerError(
            "terminal verification request drift")
    raws = {name: _sealed_read(root / name) for name in (
        ATTEMPT_NAME, EVIDENCE_NAME, TERMINAL_NAME, MANIFEST_NAME)}
    attempt = _canonical(raws[ATTEMPT_NAME], "terminal attempt")
    evidence = _canonical(raws[EVIDENCE_NAME], "terminal evidence")
    terminal = _canonical(raws[TERMINAL_NAME], "terminal result")
    manifest = _canonical(raws[MANIFEST_NAME], "terminal manifest")
    expected_manifest = _manifest(
        attempt_raw=raws[ATTEMPT_NAME], evidence_raw=raws[EVIDENCE_NAME],
        terminal_raw=raws[TERMINAL_NAME])
    if canonical_json_bytes(manifest) != canonical_json_bytes(expected_manifest):
        raise WorldAfterstateTerminalControllerError(
            "terminal manifest reconstruction drift")
    freeze_sha = _digest(freeze.get("freeze_sha256"),
                         "terminal freeze SHA-256")
    wall_key = ("independent_verification_wall_cap_seconds"
                if reconstruct_continuations
                else "report_wall_cap_seconds")
    wall_seconds = freeze.get("gates", {}).get(wall_key)
    workers = (freeze.get("labels", {}).get("workers")
               if reconstruct_continuations else 1)
    if isinstance(wall_seconds, bool) or not isinstance(wall_seconds, int) \
            or wall_seconds <= 0 or isinstance(workers, bool) \
            or not isinstance(workers, int) or not 1 <= workers <= 16:
        raise WorldAfterstateTerminalControllerError(
            "terminal verification budget drift")
    verification_deadline = (
        time.monotonic_ns() + wall_seconds * 1_000_000_000)

    def phase_progress(phase: str):
        if progress is None:
            return None
        return lambda completed, total: progress(phase, completed, total)

    train_manifest, train_rows = reopen_scientific_dataset(
        dataset_root, population_manifest=population_manifest,
        allowed_folds=("train",),
        reconstruct_continuations=reconstruct_continuations,
        reconstruction_workers=workers,
        deadline_monotonic_ns=verification_deadline,
        progress=phase_progress("reconstruct-train"))
    if reconstruct_continuations:
        # Calibration labels selected the common checkpoint and therefore
        # belong to the independent reproduction boundary too.
        reopen_scientific_dataset(
            dataset_root, population_manifest=population_manifest,
            allowed_folds=("calibration",),
            reconstruct_continuations=True,
            reconstruction_workers=workers,
            deadline_monotonic_ns=verification_deadline,
            progress=phase_progress("reconstruct-calibration"))
    training_manifest, models = reopen_training_build(training_root)
    expected_attempt = _attempt(
        freeze_sha256=freeze_sha,
        dataset_manifest_sha256=train_manifest["manifest_sha256"],
        training_manifest_sha256=training_manifest["manifest_sha256"],
        started_monotonic_ns=attempt.get("started_monotonic_ns"),
        wall_budget_nanoseconds=attempt.get("wall_budget_nanoseconds"))
    if attempt.get("wall_budget_nanoseconds") \
            != freeze["gates"]["report_wall_cap_seconds"] * 1_000_000_000:
        raise WorldAfterstateTerminalControllerError(
            "terminal attempt wall budget drift")
    if canonical_json_bytes(attempt) != canonical_json_bytes(expected_attempt):
        raise WorldAfterstateTerminalControllerError(
            "terminal attempt reconstruction drift")
    # When requested, these reopen calls independently rerun every raw engine
    # continuation before any model score is recomputed.
    _report_manifest, report_rows = reopen_scientific_dataset(
        dataset_root, population_manifest=population_manifest,
        allowed_folds=("report",),
        reconstruct_continuations=reconstruct_continuations,
        reconstruction_workers=workers,
        deadline_monotonic_ns=verification_deadline,
        progress=phase_progress("reconstruct-report"))
    _provider_manifest, provider_rows = reopen_scientific_dataset(
        dataset_root, population_manifest=population_manifest,
        allowed_folds=("provider-audit",),
        reconstruct_continuations=reconstruct_continuations,
        reconstruction_workers=workers,
        deadline_monotonic_ns=verification_deadline,
        progress=phase_progress("reconstruct-provider-audit"))
    derived = derive_terminal_evidence(
        freeze=freeze, population_manifest=population_manifest,
        models=models, train_rows=train_rows, report_rows=report_rows,
        provider_rows=provider_rows,
        deadline_monotonic_ns=verification_deadline,
        progress=progress)
    if canonical_json_bytes(derived.evidence) != raws[EVIDENCE_NAME] \
            or canonical_json_bytes(derived.terminal) != raws[TERMINAL_NAME]:
        raise WorldAfterstateTerminalControllerError(
            "terminal derivation reconstruction drift")
    validate_terminal_evidence(evidence, terminal=terminal)
    expected_files = {root / name for name in (
        ATTEMPT_NAME, EVIDENCE_NAME, TERMINAL_NAME, MANIFEST_NAME)}
    if {path for path in root.rglob("*") if path.is_file()} != expected_files:
        raise WorldAfterstateTerminalControllerError(
            "terminal file population drift")
    return {
        "verified": True,
        "terminal_sha256": terminal["terminal_sha256"],
        "decision": terminal["decision"],
        "continuations_reconstructed": reconstruct_continuations,
        "authority": dict(TERMINAL_CONTROLLER_AUTHORITY),
    }


__all__ = [
    "ATTEMPT_SCHEMA", "EVIDENCE_SCHEMA", "MANIFEST_SCHEMA",
    "DerivedTerminalV0", "TERMINAL_CONTROLLER_AUTHORITY",
    "WorldAfterstateTerminalControllerError", "derive_terminal_evidence",
    "run_open_report", "validate_terminal_evidence",
    "verify_terminal_artifact",
]
