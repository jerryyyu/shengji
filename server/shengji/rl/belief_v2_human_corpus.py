"""Split-safe human actor/target rows for BELIEF-V1 V2.

The historical source path, player identity, and round number never enter an
actor payload.  Whole-session group and round digests are artifact metadata
only; the model consumes the common public-history tensors derived by
``belief_v2_common_surface``.  Actor and privileged target bytes remain
physically separate and hash-bound.

This module replays source-log bytes supplied by a separately authorized
caller, constructs and validates in-memory rows, and returns a closed manifest.
It has no path opener, file writer, trainer, test opener, sampler, gameplay
path, or execution authority.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from ..engine.round import Round, actual_play_after
from .belief_contract import (
    ACTOR_OBSERVATION_SCHEMA,
    BELIEF_TARGETS_SCHEMA,
    BeliefContractError,
    build_actor_observation,
    build_belief_targets,
    canonical_json_bytes,
)
from .belief_corpus import (
    SPLITS,
    BeliefCorpusError,
    _seal,
    _sha256,
    _strict_load,
    _validate_seal,
)
from .belief_reopen import (
    BeliefReopenError,
    actor_observation_from_dict_allow_incomplete,
    belief_targets_from_dict,
)
from .belief_v2_common_surface import build_common_surface_tensors
from .belief_v2_human_inventory import H0_SPLIT_SCHEMA
from .belief_v2_human_inventory import (
    _events_by_round,
    _group_digest,
    _refuse_evaluation,
)
from .replay_log import EXCLUDE_PLAYERS, rebuild_round


HUMAN_ACTOR_ROW_SCHEMA = "belief-v1-v2-human-actor-row-v1"
HUMAN_TARGET_ROW_SCHEMA = "belief-v1-v2-human-target-row-v1"
HUMAN_PARTITION_SCHEMA = "belief-v1-v2-human-information-partition-v1"
UNIVERSAL_POLICY_IDS = ("universal-public-belief-v2",)
MAX_HUMAN_DECISIONS_PER_ROUND = 128
HUMAN_GROUP_CAPTURE_SCHEMA = "belief-v1-v2-human-group-capture-v1"


class BeliefV2HumanCorpusError(ValueError):
    """A V2 human corpus identity, separation, or physical fact drifted."""


def _is_sha256(value: Any) -> bool:
    return (type(value) is str and len(value) == 64
            and all(char in "0123456789abcdef" for char in value))


def human_decision_key(
        group_digest: str, round_digest: str,
        decision_index: int, actor_seat: int) -> str:
    if not _is_sha256(group_digest) or not _is_sha256(round_digest) \
            or type(decision_index) is not int \
            or not 0 <= decision_index < MAX_HUMAN_DECISIONS_PER_ROUND \
            or type(actor_seat) is not int or actor_seat not in range(4):
        raise BeliefV2HumanCorpusError(
            "human decision identity is invalid")
    return hashlib.sha256(
        (f"{HUMAN_ACTOR_ROW_SCHEMA}|{group_digest}|{round_digest}|"
         f"{decision_index}|{actor_seat}").encode("ascii")
    ).hexdigest()


def _metadata(
        *, group_digest: str, round_digest: str,
        decision_index: int, actor_seat: int, split: str) -> dict[str, Any]:
    key = human_decision_key(
        group_digest, round_digest, decision_index, actor_seat)
    if split not in SPLITS:
        raise BeliefV2HumanCorpusError("human split is invalid")
    return {
        "group_digest": group_digest,
        "round_digest": round_digest,
        "decision_index": decision_index,
        "actor_seat": actor_seat,
        "decision_key": key,
        "split_schema": H0_SPLIT_SCHEMA,
        "split": split,
    }


def _validate_metadata(row: dict[str, Any]) -> None:
    expected = _metadata(
        group_digest=row.get("group_digest"),
        round_digest=row.get("round_digest"),
        decision_index=row.get("decision_index"),
        actor_seat=row.get("actor_seat"),
        split=row.get("split"),
    )
    if row.get("split_schema") != H0_SPLIT_SCHEMA \
            or any(row.get(key) != value for key, value in expected.items()):
        raise BeliefV2HumanCorpusError("human row metadata drift")


@dataclass(frozen=True)
class V2HumanCorpusPairV1:
    actor_bytes: bytes
    target_bytes: bytes

    @property
    def actor_file_sha256(self) -> str:
        return _sha256(self.actor_bytes)

    @property
    def target_file_sha256(self) -> str:
        return _sha256(self.target_bytes)


@dataclass(frozen=True)
class V2HumanGroupCaptureV1:
    source_sha256: str
    group_digest: str
    split: str
    complete_round_count: int
    incomplete_round_count: int
    human_decision_count: int
    pairs: tuple[V2HumanCorpusPairV1, ...]
    schema: str = HUMAN_GROUP_CAPTURE_SCHEMA

    def manifest(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "source_sha256": self.source_sha256,
            "group_digest": self.group_digest,
            "split_schema": H0_SPLIT_SCHEMA,
            "split": self.split,
            "complete_round_count": self.complete_round_count,
            "incomplete_round_count": self.incomplete_round_count,
            "human_decision_count": self.human_decision_count,
            "rows": [
                {
                    "actor_file_sha256": pair.actor_file_sha256,
                    "target_file_sha256": pair.target_file_sha256,
                }
                for pair in self.pairs
            ],
            "actor_target_files_separate": True,
            "raw_player_identity_published": False,
            "source_path_published": False,
            "training_authorized": False,
            "test_open_authorized": False,
            "strength_claim_authorized": False,
        }

    def manifest_bytes(self) -> bytes:
        validate_human_group_capture(self)
        return canonical_json_bytes(self.manifest())


_ACTOR_KEYS = {
    "schema", "group_digest", "round_digest", "decision_index",
    "actor_seat", "decision_key", "split_schema", "split",
    "actor_schema", "actor_sha256", "actor",
    "common_surface_sha256", "contains_privileged_targets",
    "raw_player_identity_model_input", "source_identity_model_input",
    "artifact_sha256",
}

_TARGET_KEYS = {
    "schema", "group_digest", "round_digest", "decision_index",
    "actor_seat", "decision_key", "split_schema", "split",
    "actor_file_sha256", "actor_sha256", "common_surface_sha256",
    "target_schema", "target_sha256", "partition_sha256", "target",
    "runtime_input", "artifact_sha256",
}


def reopen_human_actor_row(actor_raw: bytes):
    """Reopen one target-blind human actor without target bytes."""
    try:
        row = _strict_load(actor_raw, label="V2 human actor row")
        if set(row) != _ACTOR_KEYS:
            raise BeliefV2HumanCorpusError(
                "human actor row field population drift")
        _validate_seal(row)
        _validate_metadata(row)
    except BeliefCorpusError as exc:
        raise BeliefV2HumanCorpusError(
            "human actor row strict reopen refused") from exc
    if row["schema"] != HUMAN_ACTOR_ROW_SCHEMA \
            or row["actor_schema"] != ACTOR_OBSERVATION_SCHEMA \
            or row["contains_privileged_targets"] is not False \
            or row["raw_player_identity_model_input"] is not False \
            or row["source_identity_model_input"] is not False \
            or type(row["actor"]) is not dict \
            or row["actor"].get("schema") != ACTOR_OBSERVATION_SCHEMA \
            or row["actor"].get("declaration_history_complete") is not False \
            or row["actor"].get(
                "attempted_play_history_complete") is not False:
        raise BeliefV2HumanCorpusError(
            "human actor schema/channel/authority drift")
    actor_bytes = canonical_json_bytes(row["actor"])
    if _sha256(actor_bytes) != row["actor_sha256"]:
        raise BeliefV2HumanCorpusError("human actor payload hash drift")
    try:
        actor = actor_observation_from_dict_allow_incomplete(row["actor"])
        common = build_common_surface_tensors(
            actor, behavior_policy_ids=UNIVERSAL_POLICY_IDS)
    except (BeliefReopenError, ValueError) as exc:
        raise BeliefV2HumanCorpusError(
            "human actor typed/common reconstruction refused") from exc
    if actor.sha256() != row["actor_sha256"] \
            or common.sha256() != row["common_surface_sha256"]:
        raise BeliefV2HumanCorpusError(
            "human actor typed/common hash drift")
    metadata = {key: row[key] for key in (
        "group_digest", "round_digest", "decision_index", "actor_seat",
        "decision_key", "split_schema", "split")}
    return actor, common, metadata


def _partition_sha256(
        actor_sha256: str, common_surface_sha256: str,
        target_sha256: str) -> str:
    return _sha256(canonical_json_bytes({
        "schema": HUMAN_PARTITION_SCHEMA,
        "actor_schema": ACTOR_OBSERVATION_SCHEMA,
        "actor_sha256": actor_sha256,
        "common_surface_sha256": common_surface_sha256,
        "target_schema": BELIEF_TARGETS_SCHEMA,
        "target_sha256": target_sha256,
        "runtime_consumes_targets": False,
    }))


def capture_human_corpus_pair(
        rnd: Round, seat: int, *, group_digest: str,
        round_digest: str, decision_index: int,
        split: str) -> V2HumanCorpusPairV1:
    """Capture one human decision with truthful incomplete channel flags."""
    metadata = _metadata(
        group_digest=group_digest, round_digest=round_digest,
        decision_index=decision_index, actor_seat=seat, split=split)
    try:
        actor = build_actor_observation(rnd, seat)
        target = build_belief_targets(rnd, seat)
        common = build_common_surface_tensors(
            actor, behavior_policy_ids=UNIVERSAL_POLICY_IDS)
    except (BeliefContractError, ValueError) as exc:
        raise BeliefV2HumanCorpusError(
            "human information partition refused") from exc
    if actor.declaration_history_complete is not False \
            or actor.attempted_play_history_complete is not False:
        raise BeliefV2HumanCorpusError(
            "human source actor implies complete unavailable history")
    actor_raw = _seal({
        "schema": HUMAN_ACTOR_ROW_SCHEMA,
        **metadata,
        "actor_schema": ACTOR_OBSERVATION_SCHEMA,
        "actor_sha256": actor.sha256(),
        "actor": actor.to_dict(),
        "common_surface_sha256": common.sha256(),
        "contains_privileged_targets": False,
        "raw_player_identity_model_input": False,
        "source_identity_model_input": False,
    })
    target_raw = _seal({
        "schema": HUMAN_TARGET_ROW_SCHEMA,
        **metadata,
        "actor_file_sha256": _sha256(actor_raw),
        "actor_sha256": actor.sha256(),
        "common_surface_sha256": common.sha256(),
        "target_schema": BELIEF_TARGETS_SCHEMA,
        "target_sha256": target.sha256(),
        "partition_sha256": _partition_sha256(
            actor.sha256(), common.sha256(), target.sha256()),
        "target": target.to_dict(),
        "runtime_input": False,
    })
    pair = V2HumanCorpusPairV1(
        actor_bytes=actor_raw, target_bytes=target_raw)
    validate_human_corpus_pair(pair.actor_bytes, pair.target_bytes)
    return pair


def validate_human_corpus_pair(
        actor_raw: bytes, target_raw: bytes):
    """Reopen, type, cross-bind, and physically reconcile one human pair."""
    try:
        actor_row = _strict_load(actor_raw, label="V2 human actor row")
        target_row = _strict_load(target_raw, label="V2 human target row")
        if set(actor_row) != _ACTOR_KEYS or set(target_row) != _TARGET_KEYS:
            raise BeliefV2HumanCorpusError(
                "human row field population drift")
        _validate_seal(actor_row)
        _validate_seal(target_row)
        _validate_metadata(actor_row)
        _validate_metadata(target_row)
    except BeliefCorpusError as exc:
        raise BeliefV2HumanCorpusError(
            "human pair strict reopen refused") from exc
    metadata_fields = (
        "group_digest", "round_digest", "decision_index", "actor_seat",
        "decision_key", "split_schema", "split")
    if actor_row["schema"] != HUMAN_ACTOR_ROW_SCHEMA \
            or target_row["schema"] != HUMAN_TARGET_ROW_SCHEMA \
            or any(actor_row[field] != target_row[field]
                   for field in metadata_fields) \
            or target_row["actor_file_sha256"] != _sha256(actor_raw) \
            or target_row["actor_sha256"] != actor_row["actor_sha256"] \
            or target_row["common_surface_sha256"] \
            != actor_row["common_surface_sha256"] \
            or target_row["target_schema"] != BELIEF_TARGETS_SCHEMA \
            or target_row["runtime_input"] is not False \
            or type(target_row["target"]) is not dict:
        raise BeliefV2HumanCorpusError(
            "human actor/target binding or authority drift")
    target_bytes = canonical_json_bytes(target_row["target"])
    if _sha256(target_bytes) != target_row["target_sha256"]:
        raise BeliefV2HumanCorpusError("human target payload hash drift")
    actor, common, metadata = reopen_human_actor_row(actor_raw)
    try:
        target = belief_targets_from_dict(target_row["target"], actor=actor)
    except BeliefReopenError as exc:
        raise BeliefV2HumanCorpusError(
            "human target physical reconstruction refused") from exc
    if target.sha256() != target_row["target_sha256"] \
            or _partition_sha256(
                actor.sha256(), common.sha256(), target.sha256()) \
            != target_row["partition_sha256"]:
        raise BeliefV2HumanCorpusError(
            "human target/partition hash drift")
    return actor, target, common, metadata


def _round_digest(group_digest: str, ordinal: int) -> str:
    if not _is_sha256(group_digest) or type(ordinal) is not int or ordinal < 0:
        raise BeliefV2HumanCorpusError("human round identity is invalid")
    return hashlib.sha256(
        f"{HUMAN_GROUP_CAPTURE_SCHEMA}|{group_digest}|round-{ordinal}".encode(
            "ascii")
    ).hexdigest()


def capture_human_source_group(
        source_raw: bytes, *, source_sha256: str,
        split: str) -> V2HumanGroupCaptureV1:
    """Replay one hash-bound source-log session into separated V2 rows."""
    if type(source_raw) is not bytes or not source_raw \
            or not _is_sha256(source_sha256) \
            or _sha256(source_raw) != source_sha256 \
            or split not in SPLITS:
        raise BeliefV2HumanCorpusError(
            "human source group identity drift")
    group_digest = _group_digest(source_sha256)
    pairs: list[V2HumanCorpusPairV1] = []
    complete = incomplete = 0
    rounds = _events_by_round(source_raw)
    for ordinal, (_, events) in enumerate(sorted(rounds.items())):
        _refuse_evaluation(events)
        start = next((event for event in events
                      if event.get("e") == "round_start"), None)
        end = next((event for event in events
                    if event.get("e") == "round_end"), None)
        if start is None or end is None:
            incomplete += 1
            continue
        players = start.get("players")
        if type(players) is not list or len(players) != 4:
            raise BeliefV2HumanCorpusError(
                "human source player population drift")
        excluded: set[int] = set()
        for player in players:
            if type(player) is not dict \
                    or type(player.get("seat")) is not int \
                    or player["seat"] not in range(4) \
                    or type(player.get("name")) is not str:
                raise BeliefV2HumanCorpusError(
                    "human source player row drift")
            if player["name"] in EXCLUDE_PLAYERS:
                excluded.add(player["seat"])
        try:
            rnd = rebuild_round(events)
        except Exception as exc:
            raise BeliefV2HumanCorpusError(
                "human source round setup cannot be reconstructed") from exc
        if rnd is None:
            raise BeliefV2HumanCorpusError(
                "complete human source round lacks setup")
        play_index = 0
        round_digest = _round_digest(group_digest, ordinal)
        for event in events:
            if event.get("e") != "play" or rnd.phase != "play":
                continue
            seat = event.get("seat")
            actual = event.get("cards")
            if type(seat) is not int or seat not in range(4) \
                    or type(actual) is not list or not actual \
                    or rnd.turn != seat:
                raise BeliefV2HumanCorpusError(
                    "human source play identity drift")
            if event.get("bot") is False and seat not in excluded:
                pairs.append(capture_human_corpus_pair(
                    rnd, seat, group_digest=group_digest,
                    round_digest=round_digest,
                    decision_index=play_index, split=split))
            attempted = event.get("attempted_cards")
            applied = attempted if type(attempted) is list else actual
            previous_last = rnd.last_trick
            try:
                rnd.play(seat, list(applied))
            except Exception as exc:
                raise BeliefV2HumanCorpusError(
                    "human source play cannot be reconstructed") from exc
            if actual_play_after(rnd, seat, previous_last) != actual:
                raise BeliefV2HumanCorpusError(
                    "human source attempted/actual channel drift")
            play_index += 1
        if rnd.phase != "round_end" \
                or rnd.attacker_points != end.get("attacker_points"):
            raise BeliefV2HumanCorpusError(
                "human source terminal reconstruction drift")
        complete += 1
    result = V2HumanGroupCaptureV1(
        source_sha256=source_sha256,
        group_digest=group_digest,
        split=split,
        complete_round_count=complete,
        incomplete_round_count=incomplete,
        human_decision_count=len(pairs),
        pairs=tuple(pairs),
    )
    validate_human_group_capture(result)
    return result


def validate_human_group_capture(value: V2HumanGroupCaptureV1) -> None:
    if type(value) is not V2HumanGroupCaptureV1 \
            or value.schema != HUMAN_GROUP_CAPTURE_SCHEMA \
            or not _is_sha256(value.source_sha256) \
            or value.group_digest != _group_digest(value.source_sha256) \
            or value.split not in SPLITS \
            or any(type(count) is not int or count < 0 for count in (
                value.complete_round_count,
                value.incomplete_round_count,
                value.human_decision_count)) \
            or type(value.pairs) is not tuple \
            or value.human_decision_count != len(value.pairs):
        raise BeliefV2HumanCorpusError(
            "human group capture identity drift")
    seen: set[str] = set()
    for pair in value.pairs:
        if type(pair) is not V2HumanCorpusPairV1:
            raise BeliefV2HumanCorpusError(
                "human group pair population drift")
        _, _, _, metadata = validate_human_corpus_pair(
            pair.actor_bytes, pair.target_bytes)
        if metadata["group_digest"] != value.group_digest \
                or metadata["split"] != value.split \
                or metadata["decision_key"] in seen:
            raise BeliefV2HumanCorpusError(
                "human group row population drift")
        seen.add(metadata["decision_key"])
    manifest = value.manifest()
    if set(manifest) != {
            "schema", "source_sha256", "group_digest", "split_schema",
            "split", "complete_round_count", "incomplete_round_count",
            "human_decision_count", "rows", "actor_target_files_separate",
            "raw_player_identity_published", "source_path_published",
            "training_authorized", "test_open_authorized",
            "strength_claim_authorized"} \
            or manifest["actor_target_files_separate"] is not True \
            or any(manifest[key] is not False for key in (
                "raw_player_identity_published", "source_path_published",
                "training_authorized", "test_open_authorized",
                "strength_claim_authorized")):
        raise BeliefV2HumanCorpusError(
            "human group manifest authority drift")
