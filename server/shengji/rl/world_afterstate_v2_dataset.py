"""Target-free dataset bridge for Value-Afterstate V2.

The source bundle has already rerun and reopened every continuation.  This
module deliberately performs no continuation call: it statically binds that
seal to its source population, reopens each canonical afterstate audit only
to build model tensors, and emits the existing typed training examples.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .belief_contract import canonical_json_bytes
from .world_afterstate import (
    WorldAfterstateError,
    WorldAfterstateTensorsV0,
    build_afterstate_tensors,
    reopen_afterstate_audit,
)
from .world_afterstate_v2_continuation import (
    ContinuationBundleV2,
)
from .world_afterstate_v2_population import PopulationMaterialV2
from .world_afterstate_v2_protocol import STATE_SOURCES
from .world_afterstate_v2_training import WorldAfterstateV2TrainingExample


SCHEMA = "world-afterstate-v2-dataset-manifest-row-v1"
AUTHORITY = {
    "dataset_opening_authorized": False,
    "audit_opening_authorized": False,
    "training_authorized": False,
    "writer_authorized": False,
    "cli_authorized": False,
}


class WorldAfterstateV2DatasetError(ValueError):
    """A V2 dataset row, tensor, or target-free manifest drifted."""


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha(value: object) -> str:
    return _sha_bytes(canonical_json_bytes(value))


def _digest(value: object, label: str) -> str:
    if type(value) is not str or len(value) != 64 or any(
            char not in "0123456789abcdef" for char in value):
        raise WorldAfterstateV2DatasetError(f"{label} drift")
    return value


def _canonical_audit(raw: bytes) -> dict[str, Any]:
    if type(raw) is not bytes:
        raise WorldAfterstateV2DatasetError("dataset audit bytes drift")
    try:
        value = json.loads(raw.decode("ascii"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise WorldAfterstateV2DatasetError("dataset audit JSON drift") from exc
    if type(value) is not dict or canonical_json_bytes(value) != raw:
        raise WorldAfterstateV2DatasetError("dataset audit canonical bytes drift")
    try:
        reopen_afterstate_audit(value)
    except WorldAfterstateError as exc:
        raise WorldAfterstateV2DatasetError("dataset audit reconstruction drift") from exc
    return value


def _tensor_sha256(tensors: WorldAfterstateTensorsV0) -> str:
    tensors.validate()
    body = {
        "public_shape": list(tensors.public.shape),
        "public_sha256": _sha_bytes(tensors.public.tobytes(order="C")),
        "history_shape": list(tensors.history.shape),
        "history_sha256": _sha_bytes(tensors.history.tobytes(order="C")),
        "world_shape": list(tensors.world.shape),
        "world_sha256": _sha_bytes(tensors.world.tobytes(order="C")),
        "perspective_shape": list(tensors.perspective.shape),
        "perspective_sha256": _sha_bytes(
            tensors.perspective.tobytes(order="C")),
    }
    return _sha(body)


def _static_bind(
        material: PopulationMaterialV2,
        bundle: ContinuationBundleV2) -> tuple[dict[tuple[int, int], Any],
                                                dict[int, dict[str, Any]]]:
    """Validate the immediate source seal without rerunning continuations."""
    if type(material) is not PopulationMaterialV2 \
            or type(bundle) is not ContinuationBundleV2:
        raise WorldAfterstateV2DatasetError("dataset source type drift")
    try:
        material.validate()
        bundle.validate()
    except Exception as exc:
        raise WorldAfterstateV2DatasetError("dataset source seal drift") from exc
    state = material.state
    if state.split != "fit":
        raise WorldAfterstateV2DatasetError("V2 training split refused")
    if (bundle.deal_sha256, bundle.slot_sha256, bundle.state_sha256,
            bundle.candidate_set_sha256) != (
                state.deal_sha256, state.slot_sha256, state.state_sha256,
                material.candidate_set_sha256):
        raise WorldAfterstateV2DatasetError("dataset material/bundle binding drift")
    if len(bundle.candidates) != len(material.candidates) * 8 \
            or len(bundle.labels) != len(bundle.candidates):
        raise WorldAfterstateV2DatasetError("dataset source population drift")
    rows: dict[tuple[int, int], Any] = {}
    for row in bundle.candidates:
        key = (row.candidate_index, row.replica)
        if key in rows:
            raise WorldAfterstateV2DatasetError("dataset duplicate source row")
        rows[key] = row
    audits: dict[int, dict[str, Any]] = {}
    for index, candidate in enumerate(material.candidates):
        audit = _canonical_audit(material.private_audit_raws[index])
        if _sha_bytes(material.private_audit_raws[index]) != candidate.audit_sha256 \
                or audit.get("successor_sha256") != candidate.successor_sha256:
            raise WorldAfterstateV2DatasetError(
                "dataset candidate audit/successor drift")
        audits[index] = audit
        for replica in range(8):
            row = rows.get((index, replica))
            if row is None or row.successor_sha256 != candidate.successor_sha256 \
                    or row.deal_sha256 != state.deal_sha256 \
                    or row.slot_sha256 != state.slot_sha256 \
                    or row.state_sha256 != state.state_sha256 \
                    or row.candidate_set_sha256 != material.candidate_set_sha256 \
                    or row.candidate_index != index \
                    or row.protected_incumbent != (index == 0) \
                    or row.source != state.source \
                    or row.role != state.role \
                    or row.phase != state.phase \
                    or row.position != state.position \
                    or row.split != "fit":
                raise WorldAfterstateV2DatasetError(
                    "dataset candidate/replica binding drift")
    if set(rows) != {(index, replica)
                     for index in range(len(material.candidates))
                     for replica in range(8)}:
        raise WorldAfterstateV2DatasetError(
            "dataset requires every candidate and replica exactly once")
    return rows, audits


def build_training_examples_v2(
        material: PopulationMaterialV2,
        bundle: ContinuationBundleV2) \
        -> tuple[WorldAfterstateV2TrainingExample, ...]:
    """Build complete fit examples from an already-reopened source bundle."""
    rows, audits = _static_bind(material, bundle)
    state = material.state
    tensors: dict[int, WorldAfterstateTensorsV0] = {}
    for index, audit in audits.items():
        try:
            tensors[index] = build_afterstate_tensors(audit)
        except WorldAfterstateError as exc:
            raise WorldAfterstateV2DatasetError(
                "dataset afterstate tensor reconstruction drift") from exc
    result = []
    for index in range(len(material.candidates)):
        for replica in range(8):
            row = rows[(index, replica)]
            result.append(WorldAfterstateV2TrainingExample(
                deal_sha256=row.deal_sha256, slot_sha256=row.slot_sha256,
                state_sha256=row.state_sha256,
                candidate_set_sha256=row.candidate_set_sha256,
                candidate_index=index,
                protected_incumbent=row.protected_incumbent,
                successor_sha256=row.successor_sha256,
                continuation_sha256=row.continuation_sha256,
                replica=replica, source=row.source, split=row.split,
                role=row.role, phase=row.phase, position=row.position,
                tensors=tensors[index],
                signed_level_category=row.signed_level_category))
    result_tuple = tuple(result)
    for value in result_tuple:
        try:
            value.validate()
        except Exception as exc:
            raise WorldAfterstateV2DatasetError(
                "dataset training example validation drift") from exc
    return result_tuple


@dataclass(frozen=True)
class DatasetManifestRowV2:
    """Public per-deal manifest row containing no targets or private payloads."""

    deal_sha256: str
    slot_sha256: str
    state_sha256: str
    candidate_set_sha256: str
    source: str
    split: str
    role: str
    phase: str
    position: str
    candidate_count: int
    replica_count: int
    example_count: int
    successor_sha256s: tuple[str, ...]
    continuation_sha256s: tuple[str, ...]
    audit_sha256s: tuple[str, ...]
    tensor_sha256s: tuple[str, ...]
    row_sha256: str
    schema: str = SCHEMA
    authority: Mapping[str, bool] = field(default_factory=lambda: dict(AUTHORITY))

    def body(self) -> dict[str, Any]:
        return {key: value for key, value in self.to_dict().items()
                if key not in ("row_sha256",)}

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema, "deal_sha256": self.deal_sha256,
            "slot_sha256": self.slot_sha256, "state_sha256": self.state_sha256,
            "candidate_set_sha256": self.candidate_set_sha256,
            "source": self.source, "split": self.split, "role": self.role,
            "phase": self.phase, "position": self.position,
            "candidate_count": self.candidate_count,
            "replica_count": self.replica_count,
            "example_count": self.example_count,
            "successor_sha256s": list(self.successor_sha256s),
            "continuation_sha256s": list(self.continuation_sha256s),
            "audit_sha256s": list(self.audit_sha256s),
            "tensor_sha256s": list(self.tensor_sha256s),
            "authority": dict(self.authority), "row_sha256": self.row_sha256,
        }

    def validate(self) -> None:
        if self.schema != SCHEMA or self.authority != AUTHORITY:
            raise WorldAfterstateV2DatasetError("manifest schema/authority drift")
        for label, value in (("manifest deal SHA-256", self.deal_sha256),
                             ("manifest slot SHA-256", self.slot_sha256),
                             ("manifest state SHA-256", self.state_sha256),
                             ("manifest candidate-set SHA-256",
                              self.candidate_set_sha256),
                             ("manifest row SHA-256", self.row_sha256)):
            _digest(value, label)
        if self.source not in STATE_SOURCES or self.split != "fit" \
                or self.role not in ("attacker", "defender") \
                or self.phase not in ("early", "middle", "late") \
                or self.position not in ("lead", "follow"):
            raise WorldAfterstateV2DatasetError("manifest identity drift")
        if (self.candidate_count < 2 or self.replica_count != 8
                or self.example_count != self.candidate_count * 8
                or len(self.successor_sha256s) != self.candidate_count
                or len(self.audit_sha256s) != self.candidate_count
                or len(self.tensor_sha256s) != self.candidate_count
                or len(self.continuation_sha256s) != 8
                or len(set(self.successor_sha256s)) != self.candidate_count
                or len(set(self.continuation_sha256s)) != 8):
            raise WorldAfterstateV2DatasetError("manifest count drift")
        for values in (self.successor_sha256s, self.continuation_sha256s,
                       self.audit_sha256s, self.tensor_sha256s):
            for value in values:
                _digest(value, "manifest digest")
        expected_set = _sha({
            "schema": "world-afterstate-v2-candidate-set-v1",
            "state_sha256": self.state_sha256,
            "successor_sha256s": list(self.successor_sha256s),
        })
        if self.candidate_set_sha256 != expected_set:
            raise WorldAfterstateV2DatasetError("manifest candidate-set drift")
        if self.row_sha256 != _sha(self.body()):
            raise WorldAfterstateV2DatasetError("manifest reconstruction drift")


def build_dataset_manifest_row_v2(
        material: PopulationMaterialV2,
        bundle: ContinuationBundleV2) -> DatasetManifestRowV2:
    """Return identities/counts/hashes only for one fit deal."""
    rows, audits = _static_bind(material, bundle)
    tensors = {}
    for index, audit in audits.items():
        try:
            tensors[index] = build_afterstate_tensors(audit)
        except WorldAfterstateError as exc:
            raise WorldAfterstateV2DatasetError(
                "manifest tensor reconstruction drift") from exc
    candidate_count = len(material.candidates)
    successors = tuple(material.candidates[index].successor_sha256
                       for index in range(candidate_count))
    audit_hashes = tuple(material.candidates[index].audit_sha256
                         for index in range(candidate_count))
    continuation_hashes = tuple(rows[(0, replica)].continuation_sha256
                                for replica in range(8))
    row_body = {
        "schema": SCHEMA, "deal_sha256": material.state.deal_sha256,
        "slot_sha256": material.state.slot_sha256,
        "state_sha256": material.state.state_sha256,
        "candidate_set_sha256": material.candidate_set_sha256,
        "source": material.state.source, "split": material.state.split,
        "role": material.state.role, "phase": material.state.phase,
        "position": material.state.position,
        "candidate_count": candidate_count, "replica_count": 8,
        "example_count": candidate_count * 8,
        "successor_sha256s": list(successors),
        "continuation_sha256s": list(continuation_hashes),
        "audit_sha256s": list(audit_hashes),
        "tensor_sha256s": [
            _tensor_sha256(tensors[index]) for index in range(candidate_count)],
        "authority": dict(AUTHORITY),
    }
    result = DatasetManifestRowV2(
        deal_sha256=material.state.deal_sha256,
        slot_sha256=material.state.slot_sha256,
        state_sha256=material.state.state_sha256,
        candidate_set_sha256=material.candidate_set_sha256,
        source=material.state.source, split=material.state.split,
        role=material.state.role, phase=material.state.phase,
        position=material.state.position, candidate_count=candidate_count,
        replica_count=8, example_count=candidate_count * 8,
        successor_sha256s=successors, continuation_sha256s=continuation_hashes,
        audit_sha256s=audit_hashes,
        tensor_sha256s=tuple(row_body["tensor_sha256s"]),
        row_sha256=_sha(row_body))
    result.validate()
    return result


def validate_dataset_manifest_row_v2(value: DatasetManifestRowV2) -> None:
    if type(value) is not DatasetManifestRowV2:
        raise WorldAfterstateV2DatasetError("manifest type drift")
    value.validate()


def manifest_row_sha256(value: DatasetManifestRowV2 | Mapping[str, Any]) -> str:
    """Hash the canonical manifest body, excluding its published hash."""
    if isinstance(value, DatasetManifestRowV2):
        return _sha(value.body())
    if type(value) is dict and "row_sha256" in value:
        return _sha({key: item for key, item in value.items()
                     if key != "row_sha256"})
    return _sha(value)


# Descriptive aliases for later shard/controller callers.
build_v2_training_examples = build_training_examples_v2
build_v2_dataset_manifest_row = build_dataset_manifest_row_v2


__all__ = [
    "AUTHORITY", "SCHEMA", "DatasetManifestRowV2",
    "WorldAfterstateV2DatasetError", "build_training_examples_v2",
    "build_v2_training_examples", "build_dataset_manifest_row_v2",
    "build_v2_dataset_manifest_row", "validate_dataset_manifest_row_v2",
    "manifest_row_sha256",
]
