"""Closed corpus-manifest boundary for the BELIEF-V1 B2 population.

One compact population row binds the exact separated capture bundle for one
round.  The full manifest requires every frozen B2 seed exactly once in seed
order and recomputes split/lane/decision totals.  Privileged target bytes are
hashed into each bundle but are never embedded in the population manifest.

The module is an in-memory builder/reopener.  It has no filesystem, CLI,
process, policy, model, sampler, outcome, or execution authority.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from .belief_b2_protocol import (B2_CAPTURE_LANES, B2_ROUND_COUNT,
                                 B2_ROUNDS_PER_LANE, B2_SPLIT_COUNTS,
                                 b2_round_seeds, capture_lane,
                                 champion_policy_seeds, protocol_sha256)
from .belief_capture import (CapturedRoundArtifactsV1, BeliefCaptureError,
                             reopen_captured_round_artifacts)
from .belief_contract import canonical_json_bytes


POPULATION_SCHEMA = "belief-v1-b2-open-dev-corpus-population-v1"
POPULATION_ROUND_SCHEMA = "belief-v1-b2-corpus-round-binding-v1"


class BeliefPopulationError(ValueError):
    """The exact B2 corpus population or bundle binding drifted."""


def _is_sha256(value: Any) -> bool:
    return (type(value) is str and len(value) == 64
            and all(char in "0123456789abcdef" for char in value))


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True)
class PopulationRoundV1:
    round_seed: int
    lane: int
    split: str
    policy_seeds: tuple[int, int, int, int]
    decision_count: int
    capture_manifest_sha256: str
    public_transcript_sha256: str
    actor_stream_sha256: str
    privileged_target_stream_sha256: str
    round_bundle_sha256: str
    schema: str = POPULATION_ROUND_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "round_seed": self.round_seed,
            "lane": self.lane,
            "split": self.split,
            "policy_seeds": list(self.policy_seeds),
            "decision_count": self.decision_count,
            "capture_manifest_sha256": self.capture_manifest_sha256,
            "public_transcript_sha256": self.public_transcript_sha256,
            "actor_stream_sha256": self.actor_stream_sha256,
            "privileged_target_stream_sha256": (
                self.privileged_target_stream_sha256),
            "round_bundle_sha256": self.round_bundle_sha256,
        }


@dataclass(frozen=True)
class BeliefPopulationV1:
    rounds: tuple[PopulationRoundV1, ...]
    schema: str = POPULATION_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        split_counts = {split: 0 for split, _ in B2_SPLIT_COUNTS}
        lane_counts = [0] * B2_CAPTURE_LANES
        decisions = 0
        for row in self.rounds:
            split_counts[row.split] += 1
            lane_counts[row.lane] += 1
            decisions += row.decision_count
        return {
            "schema": self.schema,
            "protocol_sha256": protocol_sha256(),
            "round_count": len(self.rounds),
            "split_counts": split_counts,
            "lane_round_counts": lane_counts,
            "decision_count": decisions,
            "rounds": [row.to_dict() for row in self.rounds],
            "contains_round_outcome": False,
            "privileged_targets_are_runtime_inputs": False,
            "capture_execution_authorized": False,
            "reference_generation_authorized": False,
            "training_authorized": False,
            "test_split_open_authorized": False,
            "gameplay_authorized": False,
            "strength_claim_authorized": False,
            "deployment_authorized": False,
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    def sha256(self) -> str:
        return _sha256(self.canonical_bytes())


def _stream_sha256(rows: tuple[bytes, ...]) -> str:
    if type(rows) is not tuple or not rows \
            or any(type(row) is not bytes or not row for row in rows):
        raise BeliefPopulationError("corpus stream population is malformed")
    digest = hashlib.sha256()
    for row in rows:
        digest.update(len(row).to_bytes(8, "big"))
        digest.update(row)
    return digest.hexdigest()


def _round_bundle_sha256(
        round_seed: int, capture_manifest_sha256: str,
        public_transcript_sha256: str, actor_stream_sha256: str,
        privileged_target_stream_sha256: str) -> str:
    return _sha256(canonical_json_bytes({
        "schema": POPULATION_ROUND_SCHEMA,
        "round_seed": round_seed,
        "capture_manifest_sha256": capture_manifest_sha256,
        "public_transcript_sha256": public_transcript_sha256,
        "actor_stream_sha256": actor_stream_sha256,
        "privileged_target_stream_sha256": privileged_target_stream_sha256,
    }))


def population_round_from_artifacts(
        artifacts: CapturedRoundArtifactsV1) -> PopulationRoundV1:
    """Reopen one separated bundle and bind every byte stream."""
    try:
        captured = reopen_captured_round_artifacts(artifacts)
    except BeliefCaptureError as exc:
        raise BeliefPopulationError("population capture bundle refused") from exc
    actor_stream = _stream_sha256(artifacts.actor_rows)
    target_stream = _stream_sha256(artifacts.target_rows)
    capture_manifest = _sha256(artifacts.manifest_bytes)
    public_transcript = _sha256(artifacts.transcript_bytes)
    row = PopulationRoundV1(
        round_seed=captured.round_seed,
        lane=capture_lane(captured.round_seed),
        split=captured.manifest_dict()["split"],
        policy_seeds=captured.policy_seeds,
        decision_count=len(captured.pairs),
        capture_manifest_sha256=capture_manifest,
        public_transcript_sha256=public_transcript,
        actor_stream_sha256=actor_stream,
        privileged_target_stream_sha256=target_stream,
        round_bundle_sha256=_round_bundle_sha256(
            captured.round_seed, capture_manifest, public_transcript,
            actor_stream, target_stream),
    )
    _validate_population_round(row)
    return row


def _validate_population_round(row: PopulationRoundV1) -> None:
    if type(row) is not PopulationRoundV1 \
            or row.schema != POPULATION_ROUND_SCHEMA:
        raise BeliefPopulationError("population round schema drift")
    try:
        expected_lane = capture_lane(row.round_seed)
        expected_policy_seeds = champion_policy_seeds(row.round_seed)
    except ValueError as exc:
        raise BeliefPopulationError("population round seed drift") from exc
    if row.lane != expected_lane \
            or row.policy_seeds != expected_policy_seeds \
            or type(row.decision_count) is not int \
            or not 1 <= row.decision_count <= 128 \
            or any(not _is_sha256(value) for value in (
                row.capture_manifest_sha256,
                row.public_transcript_sha256,
                row.actor_stream_sha256,
                row.privileged_target_stream_sha256,
                row.round_bundle_sha256)):
        raise BeliefPopulationError("population round identity/work drift")
    if row.round_bundle_sha256 != _round_bundle_sha256(
            row.round_seed, row.capture_manifest_sha256,
            row.public_transcript_sha256, row.actor_stream_sha256,
            row.privileged_target_stream_sha256):
        raise BeliefPopulationError("population round bundle hash drift")
    from .belief_corpus import split_for_round_seed
    if row.split != split_for_round_seed(row.round_seed):
        raise BeliefPopulationError("population round split drift")


def build_population(
        artifacts: tuple[CapturedRoundArtifactsV1, ...]) -> BeliefPopulationV1:
    """Build the exact 4,096-round manifest from ordered capture artifacts."""
    if type(artifacts) is not tuple or len(artifacts) != B2_ROUND_COUNT:
        raise BeliefPopulationError("population artifact count drift")
    population = BeliefPopulationV1(rounds=tuple(
        population_round_from_artifacts(bundle) for bundle in artifacts))
    validate_population(population)
    return population


def validate_population(population: BeliefPopulationV1) -> None:
    """Recompute the closed population envelope without privileged bytes."""
    if type(population) is not BeliefPopulationV1 \
            or population.schema != POPULATION_SCHEMA \
            or type(population.rounds) is not tuple \
            or len(population.rounds) != B2_ROUND_COUNT:
        raise BeliefPopulationError("population schema/count drift")
    if tuple(row.round_seed for row in population.rounds) != b2_round_seeds():
        raise BeliefPopulationError("population seed sequence drift")
    for row in population.rounds:
        _validate_population_round(row)
    payload = population.to_dict()
    if payload["split_counts"] != dict(B2_SPLIT_COUNTS) \
            or payload["lane_round_counts"] \
            != [B2_ROUNDS_PER_LANE] * B2_CAPTURE_LANES \
            or type(payload["decision_count"]) is not int \
            or payload["decision_count"] < B2_ROUND_COUNT:
        raise BeliefPopulationError("population aggregate drift")
    expected_keys = {
        "schema", "protocol_sha256", "round_count", "split_counts",
        "lane_round_counts", "decision_count", "rounds",
        "contains_round_outcome", "privileged_targets_are_runtime_inputs",
        "capture_execution_authorized", "reference_generation_authorized",
        "training_authorized", "test_split_open_authorized",
        "gameplay_authorized", "strength_claim_authorized",
        "deployment_authorized",
    }
    if set(payload) != expected_keys \
            or payload["protocol_sha256"] != protocol_sha256() \
            or payload["contains_round_outcome"] is not False \
            or payload["privileged_targets_are_runtime_inputs"] is not False \
            or any(payload[key] is not False for key in expected_keys
                   if key.endswith("_authorized")):
        raise BeliefPopulationError("population authority/envelope drift")


def validate_population_artifacts(
        population: BeliefPopulationV1,
        artifacts: tuple[CapturedRoundArtifactsV1, ...]) -> None:
    """Reopen all separated corpus bytes and compare the entire manifest."""
    validate_population(population)
    if type(artifacts) is not tuple or len(artifacts) != B2_ROUND_COUNT:
        raise BeliefPopulationError("population artifact count drift")
    rebuilt = BeliefPopulationV1(rounds=tuple(
        population_round_from_artifacts(bundle) for bundle in artifacts))
    if rebuilt.canonical_bytes() != population.canonical_bytes():
        raise BeliefPopulationError("population artifact reconstruction drift")
