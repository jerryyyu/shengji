"""Hash-bound V0-to-V1 action-relative pair construction.

The V1 learner may reuse only authenticated V0 train/calibration rows.  This
module joins each non-incumbent outcome to the protected incumbent from the
same state and common-random-number replicate, then binds the two immutable
row hashes and engine-reached successors into a compact manifest.

It performs no filesystem reads, split assignment, training, report opening,
gameplay, strength evaluation, merge, promotion, deployment, retry, or R5
operation.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Sequence

from .belief_contract import canonical_json_bytes
from .world_afterstate_dataset import ReopenedDatasetRowV0
from .world_afterstate_v1 import AdvantagePairV1, build_advantage_pairs
from .world_afterstate_v1_model import AdvantageExampleV1


JOINED_SCHEMA = "world-afterstate-joined-advantage-v1"
MANIFEST_SCHEMA = "world-afterstate-advantage-manifest-v1"
ALLOWED_FOLDS = ("train", "calibration")
AUTHORITY = {
    "dataset_opening_authorized": False,
    "training_authorized": False,
    "report_opening_authorized": False,
    "world_twin_generation_authorized": False,
    "gameplay_authorized": False,
    "strength_claim_authorized": False,
    "merge_authorized": False,
    "promotion_authorized": False,
    "deployment_authorized": False,
    "retry_authorized": False,
    "r5_authorized": False,
}


class WorldAfterstateV1DatasetError(ValueError):
    """A V0 row binding, sibling join, or pair manifest drifted."""


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _digest(value: object, label: str) -> str:
    if type(value) is not str or len(value) != 64 \
            or any(char not in "0123456789abcdef" for char in value):
        raise WorldAfterstateV1DatasetError(f"{label} drift")
    return value


def _validate_reopened(row: ReopenedDatasetRowV0) -> None:
    if type(row) is not ReopenedDatasetRowV0:
        raise WorldAfterstateV1DatasetError("reopened V0 row type drift")
    _digest(row.row_sha256, "reopened V0 row SHA-256")
    row.example.validate()
    row.evaluation_outcome.validate()
    outcome = row.evaluation_outcome
    if outcome.fold not in ALLOWED_FOLDS \
            or row.example.successor_sha256 != outcome.successor_sha256 \
            or row.example.signed_level_category \
            != outcome.signed_level_category:
        raise WorldAfterstateV1DatasetError("reopened V0 row binding drift")


@dataclass(frozen=True)
class JoinedAdvantageV1:
    pair: AdvantagePairV1
    example: AdvantageExampleV1
    incumbent_row_sha256: str
    candidate_row_sha256: str
    schema: str = JOINED_SCHEMA

    def validate(self) -> None:
        if self.schema != JOINED_SCHEMA \
                or type(self.pair) is not AdvantagePairV1 \
                or type(self.example) is not AdvantageExampleV1:
            raise WorldAfterstateV1DatasetError(
                "joined advantage schema drift")
        self.pair.validate()
        self.example.validate()
        _digest(self.incumbent_row_sha256, "incumbent V0 row SHA-256")
        _digest(self.candidate_row_sha256, "candidate V0 row SHA-256")
        if self.incumbent_row_sha256 == self.candidate_row_sha256 \
                or self.example.incumbent.successor_sha256 \
                != self.pair.incumbent_successor_sha256 \
                or self.example.candidate.successor_sha256 \
                != self.pair.candidate_successor_sha256 \
                or self.example.incumbent.signed_level_category \
                != self.pair.incumbent_signed_level_category \
                or self.example.candidate.signed_level_category \
                != self.pair.candidate_signed_level_category \
                or self.example.advantage_levels != self.pair.advantage_levels:
            raise WorldAfterstateV1DatasetError(
                "joined advantage sibling binding drift")

    def key(self) -> tuple[str, int, int]:
        self.validate()
        return self.pair.key()

    def binding(self) -> dict[str, Any]:
        self.validate()
        return {
            "state_group_id": self.pair.state_group_id,
            "fold": self.pair.fold,
            "candidate_index": self.pair.candidate_index,
            "replicate": self.pair.replicate,
            "incumbent_row_sha256": self.incumbent_row_sha256,
            "candidate_row_sha256": self.candidate_row_sha256,
            "incumbent_successor_sha256":
                self.pair.incumbent_successor_sha256,
            "candidate_successor_sha256":
                self.pair.candidate_successor_sha256,
            "advantage_levels": self.pair.advantage_levels,
        }


def join_advantage_examples(
        rows: Sequence[ReopenedDatasetRowV0]) \
        -> tuple[JoinedAdvantageV1, ...]:
    """Join exact sibling rows; never synthesize or repair a missing pair."""
    if type(rows) not in (list, tuple) or not rows:
        raise WorldAfterstateV1DatasetError(
            "V1 reopened row population drift")
    by_key: dict[tuple[str, int, int], ReopenedDatasetRowV0] = {}
    outcomes = []
    for row in rows:
        _validate_reopened(row)
        outcome = row.evaluation_outcome
        key = outcome.key()
        if key in by_key:
            raise WorldAfterstateV1DatasetError("duplicate reopened V0 row")
        by_key[key] = row
        outcomes.append(outcome)
    try:
        pairs = build_advantage_pairs(outcomes)
    except ValueError as exc:
        raise WorldAfterstateV1DatasetError(
            "V1 advantage pair construction refused") from exc
    joined = []
    for pair in pairs:
        incumbent = by_key.get((pair.state_group_id, 0, pair.replicate))
        candidate = by_key.get(pair.key())
        if incumbent is None or candidate is None:
            raise WorldAfterstateV1DatasetError(
                "V1 sibling row population drift")
        value = JoinedAdvantageV1(
            pair=pair,
            example=AdvantageExampleV1(
                incumbent=incumbent.example,
                candidate=candidate.example,
                advantage_levels=pair.advantage_levels),
            incumbent_row_sha256=incumbent.row_sha256,
            candidate_row_sha256=candidate.row_sha256)
        value.validate()
        joined.append(value)
    keys = [value.key() for value in joined]
    if not joined or len(keys) != len(set(keys)):
        raise WorldAfterstateV1DatasetError(
            "V1 joined pair population drift")
    return tuple(sorted(joined, key=lambda value: value.key()))


def build_advantage_manifest(
        joined: Sequence[JoinedAdvantageV1], *,
        v0_dataset_manifest_sha256: str) -> dict[str, Any]:
    """Publish only pair identities and hashes, never private tensors."""
    _digest(v0_dataset_manifest_sha256, "V0 dataset manifest SHA-256")
    if type(joined) not in (list, tuple) or not joined:
        raise WorldAfterstateV1DatasetError(
            "V1 pair manifest population drift")
    rows = []
    previous = None
    state_ids = set()
    fold_counts = {fold: 0 for fold in ALLOWED_FOLDS}
    for value in joined:
        if type(value) is not JoinedAdvantageV1:
            raise WorldAfterstateV1DatasetError(
                "V1 pair manifest row type drift")
        key = value.key()
        if previous is not None and key <= previous:
            raise WorldAfterstateV1DatasetError(
                "V1 pair manifest order drift")
        previous = key
        state_ids.add(value.pair.state_group_id)
        fold_counts[value.pair.fold] += 1
        rows.append(value.binding())
    body = {
        "schema": MANIFEST_SCHEMA,
        "v0_dataset_manifest_sha256": v0_dataset_manifest_sha256,
        "state_count": len(state_ids),
        "pair_count": len(rows),
        "fold_pair_counts": fold_counts,
        "pairs": rows,
        "contains_private_tensors": False,
        "contains_report_or_provider_audit": False,
        "authority": dict(AUTHORITY),
    }
    return {**body, "manifest_sha256": _sha(body)}


def validate_advantage_manifest(value: object) -> None:
    required = {
        "schema", "v0_dataset_manifest_sha256", "state_count",
        "pair_count", "fold_pair_counts", "pairs",
        "contains_private_tensors", "contains_report_or_provider_audit",
        "authority", "manifest_sha256",
    }
    if type(value) is not dict or set(value) != required \
            or value.get("schema") != MANIFEST_SCHEMA \
            or value.get("contains_private_tensors") is not False \
            or value.get("contains_report_or_provider_audit") is not False \
            or value.get("authority") != AUTHORITY:
        raise WorldAfterstateV1DatasetError("V1 pair manifest schema drift")
    _digest(value.get("v0_dataset_manifest_sha256"),
            "V0 dataset manifest SHA-256")
    _digest(value.get("manifest_sha256"), "V1 pair manifest SHA-256")
    rows = value.get("pairs")
    counts = value.get("fold_pair_counts")
    if type(rows) is not list or type(counts) is not dict \
            or set(counts) != set(ALLOWED_FOLDS) \
            or any(isinstance(item, bool) or not isinstance(item, int)
                   or item < 0 for item in counts.values()):
        raise WorldAfterstateV1DatasetError(
            "V1 pair manifest population drift")
    previous = None
    states = set()
    measured = {fold: 0 for fold in ALLOWED_FOLDS}
    required_row = {
        "state_group_id", "fold", "candidate_index", "replicate",
        "incumbent_row_sha256", "candidate_row_sha256",
        "incumbent_successor_sha256", "candidate_successor_sha256",
        "advantage_levels",
    }
    for row in rows:
        if type(row) is not dict or set(row) != required_row \
                or row.get("fold") not in ALLOWED_FOLDS \
                or isinstance(row.get("candidate_index"), bool) \
                or not isinstance(row.get("candidate_index"), int) \
                or row["candidate_index"] < 1 \
                or isinstance(row.get("replicate"), bool) \
                or not isinstance(row.get("replicate"), int) \
                or row["replicate"] not in (0, 1) \
                or isinstance(row.get("advantage_levels"), bool) \
                or not isinstance(row.get("advantage_levels"), int) \
                or not -203 <= row["advantage_levels"] <= 203:
            raise WorldAfterstateV1DatasetError(
                "V1 pair manifest row drift")
        for name in (
                "state_group_id", "incumbent_row_sha256",
                "candidate_row_sha256", "incumbent_successor_sha256",
                "candidate_successor_sha256"):
            _digest(row.get(name), f"V1 pair manifest {name}")
        key = (row["state_group_id"], row["candidate_index"],
               row["replicate"])
        if previous is not None and key <= previous:
            raise WorldAfterstateV1DatasetError(
                "V1 pair manifest order drift")
        previous = key
        states.add(row["state_group_id"])
        measured[row["fold"]] += 1
    body = {key: item for key, item in value.items()
            if key != "manifest_sha256"}
    if value.get("state_count") != len(states) \
            or value.get("pair_count") != len(rows) \
            or counts != measured \
            or value.get("manifest_sha256") != _sha(body):
        raise WorldAfterstateV1DatasetError(
            "V1 pair manifest reconstruction drift")


__all__ = [
    "AUTHORITY", "JoinedAdvantageV1", "WorldAfterstateV1DatasetError",
    "build_advantage_manifest", "join_advantage_examples",
    "validate_advantage_manifest",
]
