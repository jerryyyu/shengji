"""Split-safe paired actor/privileged rows for BELIEF-V1 B1.

The runtime-facing actor row and simulator-only target row are separate
canonical byte strings.  A target row binds the exact actor-file hash, but an
actor row contains no target hash or privileged payload.  This module only
constructs and validates in-memory rows; it has no CLI, file writer, sampler,
model, training loop, or execution authority.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from ..engine.round import Round
from .belief_contract import (ACTOR_OBSERVATION_SCHEMA,
                              BELIEF_TARGETS_SCHEMA,
                              BeliefContractError,
                              PublicTranscriptV1,
                              build_information_partition,
                              canonical_json_bytes)


ACTOR_ROW_SCHEMA = "belief-v1-actor-corpus-row-v1"
TARGET_ROW_SCHEMA = "belief-v1-privileged-target-row-v1"
SPLIT_SCHEMA = "belief-v1-round-seed-sha256-80-10-10-v1"
SPLITS = ("train", "calibration", "test")
MAX_ROUND_SEED = 2**63 - 1
MAX_DECISIONS_PER_ROUND = 128


class BeliefCorpusError(ValueError):
    """A B1 paired row violates split, identity, or leakage boundaries."""


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _is_sha256(value: Any) -> bool:
    return (type(value) is str and len(value) == 64
            and all(char in "0123456789abcdef" for char in value))


def split_for_round_seed(round_seed: int) -> str:
    """Assign an entire deal/round to one immutable data split."""
    if type(round_seed) is not int or not 0 <= round_seed <= MAX_ROUND_SEED:
        raise BeliefCorpusError("round seed is outside the V1 range")
    key = f"{SPLIT_SCHEMA}|{round_seed}".encode("ascii")
    bucket = int.from_bytes(hashlib.sha256(key).digest()[:8], "big") % 100
    if bucket < 80:
        return "train"
    if bucket < 90:
        return "calibration"
    return "test"


def decision_key(round_seed: int, decision_index: int,
                 actor_seat: int) -> str:
    if type(round_seed) is not int or not 0 <= round_seed <= MAX_ROUND_SEED:
        raise BeliefCorpusError("round seed is outside the V1 range")
    if type(decision_index) is not int \
            or not 0 <= decision_index < MAX_DECISIONS_PER_ROUND:
        raise BeliefCorpusError("decision index is outside the V1 range")
    if type(actor_seat) is not int or actor_seat not in range(4):
        raise BeliefCorpusError("actor seat must be an integer in range(4)")
    raw = (f"{ACTOR_ROW_SCHEMA}|{round_seed}|{decision_index}|"
           f"{actor_seat}").encode("ascii")
    return hashlib.sha256(raw).hexdigest()


def _seal(record: dict[str, Any]) -> bytes:
    if "artifact_sha256" in record:
        raise BeliefCorpusError("unsealed record already has an artifact hash")
    sealed = dict(record)
    sealed["artifact_sha256"] = _sha256(canonical_json_bytes(record))
    return canonical_json_bytes(sealed)


def _reject_constant(value: str) -> None:
    raise BeliefCorpusError(f"non-finite JSON constant {value!r}")


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise BeliefCorpusError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _strict_load(raw: bytes, *, label: str) -> dict[str, Any]:
    if type(raw) is not bytes or not raw.endswith(b"\n"):
        raise BeliefCorpusError(f"{label} must be newline-terminated bytes")
    try:
        value = json.loads(raw.decode("ascii"), object_pairs_hook=_pairs,
                           parse_constant=_reject_constant)
    except (UnicodeDecodeError, json.JSONDecodeError, BeliefCorpusError) as exc:
        if isinstance(exc, BeliefCorpusError):
            raise
        raise BeliefCorpusError(f"{label} is not strict JSON") from exc
    if type(value) is not dict:
        raise BeliefCorpusError(f"{label} is not a JSON object")
    try:
        canonical = canonical_json_bytes(value)
    except BeliefContractError as exc:
        raise BeliefCorpusError(f"{label} is not canonical JSON") from exc
    if canonical != raw:
        raise BeliefCorpusError(f"{label} is not canonical JSON")
    return value


def _validate_metadata(record: dict[str, Any], *, schema: str) -> None:
    if record.get("schema") != schema:
        raise BeliefCorpusError("corpus row schema drift")
    if type(record.get("round_seed")) is not int \
            or not 0 <= record["round_seed"] <= MAX_ROUND_SEED:
        raise BeliefCorpusError("round_seed is outside the V1 range")
    if type(record.get("decision_index")) is not int \
            or not 0 <= record["decision_index"] < MAX_DECISIONS_PER_ROUND:
        raise BeliefCorpusError("decision_index is outside the V1 range")
    if type(record.get("actor_seat")) is not int:
        raise BeliefCorpusError("actor_seat must be an integer")
    if record["actor_seat"] not in range(4):
        raise BeliefCorpusError("actor seat must be within range(4)")
    if record.get("split_schema") != SPLIT_SCHEMA:
        raise BeliefCorpusError("split schema drift")
    expected_split = split_for_round_seed(record["round_seed"])
    if record.get("split") != expected_split:
        raise BeliefCorpusError("round seed crossed its frozen split")
    expected_key = decision_key(record["round_seed"],
                                record["decision_index"],
                                record["actor_seat"])
    if record.get("decision_key") != expected_key:
        raise BeliefCorpusError("decision key drift")


def _validate_seal(record: dict[str, Any]) -> None:
    actual = record.get("artifact_sha256")
    if not _is_sha256(actual):
        raise BeliefCorpusError("artifact SHA-256 is invalid")
    unsealed = dict(record)
    del unsealed["artifact_sha256"]
    if _sha256(canonical_json_bytes(unsealed)) != actual:
        raise BeliefCorpusError("artifact self-hash mismatch")


@dataclass(frozen=True)
class CorpusPairV1:
    actor_bytes: bytes
    target_bytes: bytes

    @property
    def actor_file_sha256(self) -> str:
        return _sha256(self.actor_bytes)

    @property
    def target_file_sha256(self) -> str:
        return _sha256(self.target_bytes)


def capture_corpus_pair(rnd: Round, seat: int, *, round_seed: int,
                        decision_index: int,
                        transcript: PublicTranscriptV1) -> CorpusPairV1:
    """Capture one atomic actor/target pair before an ordinary-play action."""
    key = decision_key(round_seed, decision_index, seat)
    split = split_for_round_seed(round_seed)
    try:
        partition = build_information_partition(rnd, seat, transcript)
    except BeliefContractError as exc:
        raise BeliefCorpusError("information partition refused") from exc
    if not partition.actor.declaration_history_complete \
            or not partition.actor.attempted_play_history_complete:
        raise BeliefCorpusError(
            "training corpus requires a complete public transcript")
    actor_payload = partition.actor.to_dict()
    target_payload = partition.targets.to_dict()
    metadata = {
        "round_seed": round_seed,
        "decision_index": decision_index,
        "actor_seat": seat,
        "decision_key": key,
        "split_schema": SPLIT_SCHEMA,
        "split": split,
    }
    actor_bytes = _seal({
        "schema": ACTOR_ROW_SCHEMA,
        **metadata,
        "actor_schema": ACTOR_OBSERVATION_SCHEMA,
        "actor_sha256": partition.actor.sha256(),
        "actor": actor_payload,
        "contains_privileged_targets": False,
    })
    target_bytes = _seal({
        "schema": TARGET_ROW_SCHEMA,
        **metadata,
        "actor_file_sha256": _sha256(actor_bytes),
        "actor_sha256": partition.actor.sha256(),
        "target_schema": BELIEF_TARGETS_SCHEMA,
        "target_sha256": partition.targets.sha256(),
        "partition_sha256": partition.sha256(),
        "target": target_payload,
        "runtime_input": False,
    })
    pair = CorpusPairV1(actor_bytes=actor_bytes, target_bytes=target_bytes)
    validate_corpus_pair(pair.actor_bytes, pair.target_bytes)
    return pair


def validate_corpus_pair(actor_raw: bytes, target_raw: bytes) \
        -> tuple[dict[str, Any], dict[str, Any]]:
    """Reopen both canonical rows and rebind payloads, split, and pairing."""
    actor = _strict_load(actor_raw, label="actor row")
    target = _strict_load(target_raw, label="target row")
    actor_keys = {
        "schema", "round_seed", "decision_index", "actor_seat",
        "decision_key", "split_schema", "split", "actor_schema",
        "actor_sha256", "actor", "contains_privileged_targets",
        "artifact_sha256",
    }
    target_keys = {
        "schema", "round_seed", "decision_index", "actor_seat",
        "decision_key", "split_schema", "split", "actor_file_sha256",
        "actor_sha256", "target_schema", "target_sha256",
        "partition_sha256", "target", "runtime_input", "artifact_sha256",
    }
    if set(actor) != actor_keys or set(target) != target_keys:
        raise BeliefCorpusError("corpus row field population drift")
    _validate_metadata(actor, schema=ACTOR_ROW_SCHEMA)
    _validate_metadata(target, schema=TARGET_ROW_SCHEMA)
    _validate_seal(actor)
    _validate_seal(target)
    metadata_fields = ("round_seed", "decision_index", "actor_seat",
                       "decision_key", "split_schema", "split")
    if any(actor[field] != target[field] for field in metadata_fields):
        raise BeliefCorpusError("actor/target metadata mismatch")
    if target["actor_file_sha256"] != _sha256(actor_raw):
        raise BeliefCorpusError("target does not bind exact actor file")
    if actor["actor_schema"] != ACTOR_OBSERVATION_SCHEMA \
            or target["target_schema"] != BELIEF_TARGETS_SCHEMA:
        raise BeliefCorpusError("payload schema drift")
    if actor["contains_privileged_targets"] is not False \
            or target["runtime_input"] is not False:
        raise BeliefCorpusError("actor/target authority boundary drift")
    if type(actor["actor"]) is not dict or type(target["target"]) is not dict:
        raise BeliefCorpusError("corpus payload must be an object")
    if actor["actor"].get("schema") != actor["actor_schema"] \
            or target["target"].get("schema") != target["target_schema"]:
        raise BeliefCorpusError("payload internal schema drift")
    if actor["actor"].get("declaration_history_complete") is not True \
            or actor["actor"].get(
                "attempted_play_history_complete") is not True:
        raise BeliefCorpusError("actor payload has incomplete public history")
    if target["actor_sha256"] != actor["actor_sha256"]:
        raise BeliefCorpusError("target actor payload binding drift")
    actor_payload_bytes = canonical_json_bytes(actor["actor"])
    target_payload_bytes = canonical_json_bytes(target["target"])
    if _sha256(actor_payload_bytes) != actor["actor_sha256"]:
        raise BeliefCorpusError("actor payload hash mismatch")
    if _sha256(target_payload_bytes) != target["target_sha256"]:
        raise BeliefCorpusError("target payload hash mismatch")
    partition_manifest = {
        "schema": "belief-v1-information-partition-v1",
        "actor_schema": actor["actor_schema"],
        "actor_sha256": actor["actor_sha256"],
        "targets_schema": target["target_schema"],
        "targets_sha256": target["target_sha256"],
        "runtime_consumes_targets": False,
    }
    if _sha256(canonical_json_bytes(partition_manifest)) \
            != target["partition_sha256"]:
        raise BeliefCorpusError("partition hash mismatch")
    return actor, target
