"""Small, score-free Value-Afterstate V2 plumbing rehearsal.

This module is deliberately not a scientific runner.  Its fixture contains
only typed, target-free roots; the reviewed V2 inference and prediction
artifact boundaries are exercised, then the run stops before audit-attempt.
No continuation, outcome, label, or terminal producer is imported here.
"""

from __future__ import annotations

import hashlib
import json
import os
import resource
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Mapping

import torch

from .belief_artifacts import publish_exclusive_bytes, stable_read_bytes
from .belief_contract import canonical_json_bytes
from .world_afterstate import (
    PERSPECTIVE_DIM, PUBLIC_DIM, WORLD_RECEIVERS,
)
from .world_afterstate_v2_inference import (
    ValueInferenceRootV2, prediction_population_manifest_v2,
    predict_roots_v2, reopen_prediction_population_manifest_v2,
)
from .world_afterstate_v2_model import (
    WorldAfterstateV2Batch, new_world_afterstate_v2_model,
)
from .douzero_micro import HISTORY_EVENT_DIM
from .encode import N_CARDS
from .world_afterstate_v2_prediction_artifacts import (
    prediction_population_manifest_path,
    publish_prediction_population_manifest,
    reopen_prediction_population_artifact,
)


REHEARSAL_SCHEMA = "world-afterstate-v2-non-scientific-rehearsal-v1"
RECEIPT_SCHEMA = "world-afterstate-v2-non-scientific-rehearsal-receipt-v1"
POPULATION_SCHEMA = "world-afterstate-v2-score-free-population-v1"
POPULATION_PATH = Path("population") / "score-free-material.json"
TRAIN_STATE_COUNT = 2
MEMBERS = 4
SOURCE_IDENTITY = hashlib.sha256(
    b"world-afterstate-v2-rehearsal-deterministic-score-free-fixture-v1"
).hexdigest()

# This is a receipt-level statement, not execution authority.  Keep every
# downstream authority explicit so a receipt cannot be mistaken for a grant.
AUTHORITY = {
    "scientific_authority": False,
    "scientific_freeze_authorized": False,
    "scientific_dataset_opening_authorized": False,
    "scientific_training_authorized": False,
    "scientific_terminal_interpretation_authorized": False,
    "report_opening_authorized": False,
    "data_collection_authorized": False,
    "capacity_execution_authorized": False,
    "audit_opening_authorized": False,
    "terminal_interpretation_authorized": False,
    "gameplay_authorized": False,
    "strength_claim_authorized": False,
    "merge_authorized": False,
    "deployment_authorized": False,
    "deploy_authorized": False,
    "promotion_authorized": False,
    "retry_authorized": False,
}
STOP_PATHS = (
    "audit-attempt.json", "audit-continuations", "continuation-outcomes",
    "terminal", "terminal.json", "terminal-inputs.json",
)


class RehearsalError(ValueError):
    """The bounded rehearsal or one of its immutable artifacts was refused."""


class RehearsalStage(str, Enum):
    POPULATION = "population"
    PREDICTION = "prediction"
    PUBLISH = "publish"
    REOPEN = "reopen"
    STOP = "stop-before-audit-attempt"


@dataclass(frozen=True)
class ScoreFreePopulationV2:
    """Canonical population row; intentionally has no target-bearing fields."""

    root: ValueInferenceRootV2

    def payload(self) -> dict[str, Any]:
        self.root.validate()
        return {**self.root.target_free_body(), "root_sha256": self.root.root_sha256}


@dataclass(frozen=True)
class RehearsalBuildV2:
    source_identity_sha256: str
    population_bytes: bytes
    population_sha256: str
    roots: tuple[ValueInferenceRootV2, ...]
    prediction_manifest: dict[str, Any]
    model_state_sha256s: tuple[str, ...]


@dataclass(frozen=True)
class RehearsalReceiptV2:
    body: dict[str, Any]
    receipt_sha256: str

    @property
    def payload(self) -> dict[str, Any]:
        return {**self.body, "receipt_sha256": self.receipt_sha256}


def _sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha(value: object) -> str:
    return _sha_bytes(canonical_json_bytes(value))


def _digest(value: object, label: str) -> str:
    if type(value) is not str or len(value) != 64 or any(
            char not in "0123456789abcdef" for char in value):
        raise RehearsalError(f"{label} drift")
    return value


def _strict_json(raw: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("ascii"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RehearsalError(f"{label} is not canonical JSON") from exc
    if type(value) is not dict or canonical_json_bytes(value) != raw:
        raise RehearsalError(f"{label} is not canonical JSON")
    return value


def _validate_source_identity(value: object) -> str:
    source = _digest(value, "source identity")
    if source != SOURCE_IDENTITY:
        raise RehearsalError("source identity is not the rehearsal fixture")
    return source


def _fixture_root(index: int, source_identity: str) -> ValueInferenceRootV2:
    """Build a tiny deterministic root without opening any private audit."""
    if not isinstance(index, int) or index < 0 or index >= TRAIN_STATE_COUNT:
        raise RehearsalError("fixture index drift")
    source_identity = _validate_source_identity(source_identity)
    deal = _sha({"source": source_identity, "deal": index})
    slot = _sha({"source": source_identity, "slot": index})
    state = _sha({"source": source_identity, "state": index})
    successors = tuple(_sha({"state": state, "candidate": candidate})
                       for candidate in range(2))
    candidate_set = _sha({
        "schema": "world-afterstate-v2-candidate-set-v1",
        "state_sha256": state,
        "successor_sha256s": list(successors),
    })
    public = torch.zeros((2, PUBLIC_DIM), dtype=torch.float32)
    # The tail is free-form public context; card planes remain exactly zero.
    public[:, -1] = float(index)
    history = torch.zeros((2, 0, HISTORY_EVENT_DIM), dtype=torch.float32)
    world = torch.zeros((2, WORLD_RECEIVERS, N_CARDS), dtype=torch.float32)
    perspective = torch.zeros((2, PERSPECTIVE_DIM), dtype=torch.float32)
    perspective[:, 0] = 1.0
    batch = WorldAfterstateV2Batch(
        public=public, history=history, history_lengths=torch.zeros(
            2, dtype=torch.long), world=world, perspective=perspective)
    batch.validate()
    # The root contract binds a digest for every candidate tensor.  The
    # rehearsal fixture uses exact deterministic one-row shapes here.
    tensor_sha256s = []
    for candidate in range(2):
        tensor_sha256s.append(_sha({
            "public": [[PUBLIC_DIM], _sha_bytes(
                public[candidate].numpy().tobytes())],
            "history": [[0, HISTORY_EVENT_DIM], _sha_bytes(
                history[candidate].numpy().tobytes())],
            "world": [[WORLD_RECEIVERS, N_CARDS], _sha_bytes(
                world[candidate].numpy().tobytes())],
            "perspective": [[PERSPECTIVE_DIM], _sha_bytes(
                perspective[candidate].numpy().tobytes())],
        }))
    root = ValueInferenceRootV2(
        deal_sha256=deal, slot_sha256=slot, state_sha256=state,
        candidate_set_sha256=candidate_set, split="fit", source="natural",
        role="attacker", phase="early", position="lead", trump_rank="2",
        trump_mode="S", select_subfold=None, points_bucket="0-39",
        successor_sha256s=successors, tensor_sha256s=tuple(tensor_sha256s),
        tensors=batch)
    # Hashing uses per-candidate WorldAfterstateTensorsV0 shape conventions;
    # the model API only needs the typed batch.  Validate root identity before
    # handing it to inference so any future contract drift fails closed.
    root.validate()
    return root


def _population(source_identity: str) -> tuple[tuple[ValueInferenceRootV2, ...], bytes]:
    roots = tuple(_fixture_root(index, source_identity)
                  for index in range(TRAIN_STATE_COUNT))
    rows = [ScoreFreePopulationV2(root).payload()
            for root in sorted(roots, key=lambda item: item.root_sha256)]
    body = {
        "schema": POPULATION_SCHEMA,
        "rehearsal_schema": REHEARSAL_SCHEMA,
        "source_identity_sha256": source_identity,
        "split": "fit",
        "score_free": True,
        "scientific": False,
        "rows": rows,
    }
    value = {**body, "population_sha256": _sha(body)}
    return roots, canonical_json_bytes(value)


def _publish_once(path: Path, raw: bytes, label: str) -> str:
    if path.parent.is_symlink() or path.is_symlink() \
            or (path.exists() and not path.is_file()):
        raise RehearsalError(f"{label} path drift")
    if path.exists():
        try:
            existing = stable_read_bytes(path)
        except (OSError, ValueError) as exc:
            raise RehearsalError(f"{label} stable reopen refused") from exc
        if existing != raw:
            raise RehearsalError(f"{label} immutable byte mismatch")
        return _sha_bytes(existing)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        digest = publish_exclusive_bytes(path, raw)
        reread = stable_read_bytes(path)
    except (OSError, ValueError) as exc:
        raise RehearsalError(f"{label} exclusive publication refused") from exc
    if reread != raw or digest != _sha_bytes(raw):
        raise RehearsalError(f"{label} publication/reopen drift")
    return digest


def _emit(progress: Callable[[dict[str, Any]], None] | None, *, stage: RehearsalStage,
          completed: int, total: int, started: int, stage_counts: Mapping[str, int],
          shards: int) -> None:
    if progress is None:
        return
    elapsed = max(0, time.monotonic_ns() - started) / 1e9
    rate = completed / elapsed if completed and elapsed else 0.0
    eta = max(0.0, (total - completed) / rate) if rate else None
    usage = resource.getrusage(resource.RUSAGE_SELF)
    rss = int(usage.ru_maxrss) * (1024 if os.uname().sysname != "Darwin" else 1)
    progress({
        "schema": REHEARSAL_SCHEMA, "stage": stage.value,
        "completed": completed, "total": total,
        "stage_counts": dict(stage_counts), "elapsed_seconds": elapsed,
        "eta_seconds": eta, "workers": 1, "utilization": 1.0,
        "active_workers": 1, "memory_bytes": rss,
        "peak_memory_bytes": rss, "checkpoint_count": 0,
        "shard_count": shards,
    })


def dispatch_stage(stage: RehearsalStage, operation: Callable[[], Any]) -> Any:
    """Dispatch only a declared rehearsal stage through a typed enum."""
    if type(stage) is not RehearsalStage or not callable(operation):
        raise RehearsalError("typed rehearsal stage dispatch drift")
    return operation()


def build_non_scientific_rehearsal_v2(
        *, source_identity: str = SOURCE_IDENTITY,
        progress: Callable[[dict[str, Any]], None] | None = None) -> RehearsalBuildV2:
    """Run the deterministic score-free path entirely in memory."""
    source_identity = _validate_source_identity(source_identity)
    started = time.monotonic_ns()
    counts = {stage.value: 0 for stage in RehearsalStage}
    roots, population_bytes = dispatch_stage(
        RehearsalStage.POPULATION, lambda: _population(source_identity))
    counts[RehearsalStage.POPULATION.value] = len(roots)
    _emit(progress, stage=RehearsalStage.POPULATION, completed=len(roots),
          total=len(roots), started=started, stage_counts=counts, shards=0)
    model_hashes = []
    predictions = []
    for member in range(MEMBERS):
        model = new_world_afterstate_v2_model(9000 + member)
        rows = dispatch_stage(RehearsalStage.PREDICTION, lambda: predict_roots_v2(
            model, roots, seed_block=1, member_index=member,
            control_name="natural"))
        predictions.extend(rows)
        model_hashes.append(rows[0].model_state_sha256)
    counts[RehearsalStage.PREDICTION.value] = len(predictions)
    _emit(progress, stage=RehearsalStage.PREDICTION, completed=len(predictions),
          total=len(roots) * 2 * MEMBERS, started=started, stage_counts=counts,
          shards=0)
    manifest = prediction_population_manifest_v2(
        roots, tuple(predictions), split="fit", control_name="natural", seed_block=1)
    counts[RehearsalStage.PUBLISH.value] = 1
    _emit(progress, stage=RehearsalStage.PUBLISH, completed=1, total=1,
          started=started, stage_counts=counts, shards=1)
    return RehearsalBuildV2(
        source_identity_sha256=source_identity, population_bytes=population_bytes,
        population_sha256=_sha_bytes(population_bytes), roots=roots,
        prediction_manifest=manifest, model_state_sha256s=tuple(model_hashes))


# V1-style discoverable alias.
build_non_scientific_rehearsal = build_non_scientific_rehearsal_v2


def _reopen_population(root: Path, expected_source: str) -> tuple[dict[str, Any], bytes]:
    path = root / POPULATION_PATH
    if path.parent.is_symlink() or path.is_symlink() or not path.is_file():
        raise RehearsalError("score-free population shard missing or symlink")
    try:
        raw = stable_read_bytes(path)
    except (OSError, ValueError) as exc:
        raise RehearsalError("score-free population shard reopen refused") from exc
    value = _strict_json(raw, "score-free population")
    required = {"schema", "rehearsal_schema", "source_identity_sha256", "split",
                "score_free", "scientific", "rows", "population_sha256"}
    if set(value) != required or value["schema"] != POPULATION_SCHEMA \
            or value["rehearsal_schema"] != REHEARSAL_SCHEMA \
            or value["split"] != "fit" or value["score_free"] is not True \
            or value["scientific"] is not False \
            or value["source_identity_sha256"] != expected_source:
        raise RehearsalError("score-free population identity drift")
    body = {key: item for key, item in value.items() if key != "population_sha256"}
    if value["population_sha256"] != _sha(body):
        raise RehearsalError("score-free population hash drift")
    rows = value["rows"]
    if type(rows) is not list or len(rows) != TRAIN_STATE_COUNT:
        raise RehearsalError("score-free population count drift")
    if any(type(row) is not dict or set(row) != {
            "schema", "deal_sha256", "slot_sha256", "state_sha256",
            "candidate_set_sha256", "split", "source", "role", "phase",
            "position", "trump_rank", "trump_mode", "select_subfold",
            "points_bucket", "successor_sha256s", "tensor_sha256s", "root_sha256"
    } for row in rows):
        raise RehearsalError("score-free population row drift")
    if any(row["source"] != "natural" for row in rows):
        raise RehearsalError("mixed population source identity")
    expected_rows, expected_raw = _population(expected_source)
    del expected_rows
    if raw != expected_raw:
        raise RehearsalError("score-free population byte identity drift")
    for row in rows:
        _digest(row["root_sha256"], "population root")
        _digest(row["state_sha256"], "population state")
    return value, raw


def _assert_stop_boundary(root: Path) -> None:
    for relative in STOP_PATHS:
        path = root / relative
        if path.is_symlink() or path.exists():
            raise RehearsalError(f"stop boundary occupied: {relative}")


def reopen_non_scientific_rehearsal(
        output: Path, *, expected_source_identity: str = SOURCE_IDENTITY,
        receipt: Path | None = None
        ) -> RehearsalReceiptV2:
    """Independently reopen the exact population, prediction, and receipt."""
    if not isinstance(output, Path) or output.is_symlink() or not output.is_dir():
        raise RehearsalError("rehearsal artifact root drift")
    source = _validate_source_identity(expected_source_identity)
    population, _raw = _reopen_population(output, source)
    _assert_stop_boundary(output)
    manifest, artifact = reopen_prediction_population_artifact(
        output, control_name="natural", seed_block=1, split="fit")
    rows = reopen_prediction_population_manifest_v2(manifest)
    if len(rows) != TRAIN_STATE_COUNT * 2 * MEMBERS:
        raise RehearsalError("prediction shard count drift")
    if artifact.sha256 != _sha_bytes(
            stable_read_bytes(prediction_population_manifest_path(
                output, "natural", 1, "fit"))):
        raise RehearsalError("prediction artifact hash drift")
    receipt_path = receipt if receipt is not None else output.parent / "receipt.json"
    if receipt_path.is_symlink():
        raise RehearsalError("rehearsal receipt symlink")
    if receipt_path.is_file():
        value = _strict_json(stable_read_bytes(receipt_path), "rehearsal receipt")
        digest = value.pop("receipt_sha256", None)
        expected = {
            "schema": RECEIPT_SCHEMA, "rehearsal_schema": REHEARSAL_SCHEMA,
            "source_identity_sha256": source, "non_scientific": True,
            "score_free": True, "scientific": False,
            "population_sha256": _sha_bytes(_raw),
            "prediction_manifest_sha256": manifest["manifest_sha256"],
            "prediction_artifact_sha256": artifact.sha256,
            "stop_before": "audit-attempt", "audit_paths_absent": list(STOP_PATHS),
            "authority": dict(AUTHORITY),
        }
        if type(digest) is not str or digest != _sha(value) or any(
                value.get(key) != expected_value
                for key, expected_value in expected.items()):
            raise RehearsalError("rehearsal receipt self-binding drift")
        return RehearsalReceiptV2(value, digest)
    # The standalone artifact reopener is useful for library callers that keep
    # the receipt elsewhere; retain a compact, self-bound reconstruction.
    body = {
        "schema": RECEIPT_SCHEMA, "source_identity_sha256": source,
        "non_scientific": True, "score_free": True,
        "population_sha256": _sha_bytes(_raw),
        "prediction_manifest_sha256": manifest["manifest_sha256"],
        "prediction_artifact_sha256": artifact.sha256,
        "stop_before": "audit-attempt", "audit_paths_absent": list(STOP_PATHS),
        "authority": dict(AUTHORITY),
    }
    return RehearsalReceiptV2(body, _sha(body))


def run_non_scientific_rehearsal_v2(
        output: Path, receipt: Path, *, source_identity: str = SOURCE_IDENTITY,
        progress: Callable[[dict[str, Any]], None] | None = None) -> RehearsalReceiptV2:
    """Publish or recover one exact immutable rehearsal artifact set."""
    if not isinstance(output, Path) or not isinstance(receipt, Path):
        raise TypeError("rehearsal paths must be pathlib.Path")
    source_identity = _validate_source_identity(source_identity)
    if output.is_symlink() or receipt.is_symlink():
        raise RehearsalError("rehearsal output symlink")
    if receipt.exists():
        if not receipt.is_file() or not output.is_dir():
            raise RehearsalError("rehearsal receipt/artifact pairing drift")
        reopened = reopen_non_scientific_rehearsal(
            output, expected_source_identity=source_identity, receipt=receipt)
        return reopened
    output.mkdir(mode=0o700, parents=True, exist_ok=True)
    if not output.is_dir() or output.is_symlink():
        raise RehearsalError("rehearsal artifact root drift")
    progress_rows: list[dict[str, Any]] = []

    def observe(value: dict[str, Any]) -> None:
        progress_rows.append(value)
        if progress is not None:
            progress(value)

    # Recovery is intentionally checked before rebuilding the in-memory
    # fixture.  A complete immutable shard set is reopened and reused as-is;
    # no model or population constructor is called on this path.
    population_path = output / POPULATION_PATH
    prediction_path = prediction_population_manifest_path(
        output, "natural", 1, "fit")
    if population_path.is_file() and prediction_path.is_file():
        reopened = reopen_non_scientific_rehearsal(
            output, expected_source_identity=source_identity, receipt=receipt)
        counts = {stage.value: (TRAIN_STATE_COUNT if stage is RehearsalStage.POPULATION
                                else (TRAIN_STATE_COUNT * 2 * MEMBERS
                                      if stage is RehearsalStage.PREDICTION else 1))
                  for stage in RehearsalStage}
        body = {
            "schema": RECEIPT_SCHEMA, "rehearsal_schema": REHEARSAL_SCHEMA,
            "source_identity_sha256": source_identity, "non_scientific": True,
            "score_free": True, "scientific": False,
            "population_sha256": _sha_bytes(stable_read_bytes(population_path)),
            "prediction_manifest_sha256": reopened.body["prediction_manifest_sha256"],
            "prediction_artifact_sha256": reopened.body["prediction_artifact_sha256"],
            "stage_counts": counts, "progress_event_count": 0,
            "workers": 1, "checkpoint_count": 0, "shard_count": 2,
            "stop_before": "audit-attempt",
            "audit_paths_absent": list(STOP_PATHS), "authority": dict(AUTHORITY),
        }
        raw_receipt = canonical_json_bytes({**body, "receipt_sha256": _sha(body)})
        _publish_once(receipt, raw_receipt, "rehearsal receipt")
        return RehearsalReceiptV2(body, _sha(body))
    build = build_non_scientific_rehearsal_v2(
        source_identity=source_identity, progress=observe)
    population_digest = _publish_once(
        output / POPULATION_PATH, build.population_bytes, "population shard")
    if prediction_path.exists() or prediction_path.is_symlink():
        if prediction_path.is_symlink():
            raise RehearsalError("prediction manifest symlink")
        existing, prediction_artifact = reopen_prediction_population_artifact(
            output, control_name="natural", seed_block=1, split="fit")
        if existing != build.prediction_manifest:
            raise RehearsalError("prediction manifest immutable byte mismatch")
    else:
        prediction_artifact = publish_prediction_population_manifest(
            output, build.prediction_manifest,
            control_name="natural", seed_block=1, split="fit")
    prediction_raw = stable_read_bytes(prediction_path)
    if prediction_raw != canonical_json_bytes(build.prediction_manifest):
        raise RehearsalError("prediction manifest publication drift")
    _assert_stop_boundary(output)
    counts = {stage.value: (TRAIN_STATE_COUNT if stage is RehearsalStage.POPULATION
                            else (TRAIN_STATE_COUNT * 2 * MEMBERS
                                  if stage is RehearsalStage.PREDICTION else 1))
              for stage in RehearsalStage}
    _emit(observe, stage=RehearsalStage.REOPEN, completed=1, total=1,
          started=time.monotonic_ns(), stage_counts=counts, shards=2)
    _emit(observe, stage=RehearsalStage.STOP, completed=1, total=1,
          started=time.monotonic_ns(), stage_counts=counts, shards=2)
    body = {
        "schema": RECEIPT_SCHEMA, "rehearsal_schema": REHEARSAL_SCHEMA,
        "source_identity_sha256": source_identity, "non_scientific": True,
        "score_free": True, "scientific": False,
        "population_sha256": population_digest,
        "prediction_manifest_sha256": build.prediction_manifest["manifest_sha256"],
        "prediction_artifact_sha256": prediction_artifact.sha256,
        "stage_counts": counts, "progress_event_count": len(progress_rows),
        "workers": 1, "checkpoint_count": 0, "shard_count": 2,
        "stop_before": "audit-attempt",
        "audit_paths_absent": list(STOP_PATHS), "authority": dict(AUTHORITY),
    }
    raw_receipt = canonical_json_bytes({**body, "receipt_sha256": _sha(body)})
    _publish_once(receipt, raw_receipt, "rehearsal receipt")
    value = _strict_json(raw_receipt, "rehearsal receipt")
    return RehearsalReceiptV2(body, value["receipt_sha256"])


run_non_scientific_rehearsal = run_non_scientific_rehearsal_v2


__all__ = [
    "AUTHORITY", "POPULATION_PATH", "RECEIPT_SCHEMA", "REHEARSAL_SCHEMA",
    "RehearsalBuildV2", "RehearsalError", "RehearsalReceiptV2",
    "RehearsalStage", "ScoreFreePopulationV2", "SOURCE_IDENTITY",
    "STOP_PATHS", "build_non_scientific_rehearsal",
    "build_non_scientific_rehearsal_v2", "reopen_non_scientific_rehearsal",
    "dispatch_stage",
    "run_non_scientific_rehearsal", "run_non_scientific_rehearsal_v2",
]
