"""Score-free, identity-free H0 inventory for BELIEF-V1 V2 human data.

The inventory validates an exact source snapshot and reconstructs complete
rounds only far enough to report whether hidden ownership labels and the
engine-public action channel are recoverable.  It emits no names, file names,
actions, hands, kitty cards, or model rows.  Running it opens private logs and
therefore still requires the consolidated V2 source/design PASS; importing
this module does not open anything or authorize training.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

from ..api.human_eval import SCHEMA as HUMAN_EVALUATION_SCHEMA
from ..engine.cards import RANKS
from ..engine.round import actual_play_after
from .belief_contract import canonical_json_bytes
from .replay_log import EXCLUDE_PLAYERS, rebuild_round


H0_INVENTORY_SCHEMA = "belief-v1-v2-human-h0-inventory-v1"
H0_GROUP_SCHEMA = "belief-v1-v2-human-source-group-v1"
H0_SPLIT_SCHEMA = "belief-v1-v2-human-group-split-v1"
H0_SPLIT_NAMESPACE = "belief-v1-v2-human-group-split-80-10-10-v1"


class BeliefV2HumanInventoryError(ValueError):
    """The private-log H0 inventory cannot be published safely."""


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _is_sha256(value: Any) -> bool:
    return (type(value) is str and len(value) == 64
            and all(char in "0123456789abcdef" for char in value))


def _strict_source_manifest(raw: bytes) -> dict[str, str]:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BeliefV2HumanInventoryError(
            "H0 source manifest is not UTF-8") from exc
    members: dict[str, str] = {}
    for line_number, line in enumerate(text.splitlines(), 1):
        fields = line.split(maxsplit=1)
        if len(fields) != 2 or len(fields[0]) != 64 \
                or any(char not in "0123456789abcdef" for char in fields[0]):
            raise BeliefV2HumanInventoryError(
                f"H0 source manifest line {line_number} is malformed")
        name = Path(fields[1].lstrip("* ")).name
        if not name or name in members:
            raise BeliefV2HumanInventoryError(
                "H0 source manifest member population is invalid")
        members[name] = fields[0]
    if not members:
        raise BeliefV2HumanInventoryError("H0 source manifest is empty")
    return members


def _events_by_round(raw: bytes) -> dict[int, list[dict[str, Any]]]:
    rounds: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for line_number, line in enumerate(raw.splitlines(), 1):
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise BeliefV2HumanInventoryError(
                f"H0 source event line {line_number} is malformed") from exc
        if type(event) is not dict or type(event.get("round")) is not int:
            raise BeliefV2HumanInventoryError(
                f"H0 source event line {line_number} identity is malformed")
        rounds[event["round"]].append(event)
    return dict(rounds)


def _refuse_evaluation(events: Iterable[dict[str, Any]]) -> None:
    for event in events:
        experiment = event.get("experiment")
        tagged = event.get("training_excluded") is True
        if isinstance(experiment, dict):
            tagged = tagged or experiment.get("training_excluded") is True
            tagged = tagged or experiment.get("schema") \
                == HUMAN_EVALUATION_SCHEMA
        if tagged:
            raise BeliefV2HumanInventoryError(
                "evaluation-only round cannot enter H0 inventory")


def _group_digest(source_sha256: str) -> str:
    return _sha256(
        f"{H0_GROUP_SCHEMA}|{source_sha256}".encode("ascii"))


def _inventory_round(events: list[dict[str, Any]],
                     excluded_seats: set[int]) -> dict[str, Any] | None:
    _refuse_evaluation(events)
    start = next((event for event in events
                  if event.get("e") == "round_start"), None)
    end = next((event for event in events
                if event.get("e") == "round_end"), None)
    if start is None or end is None:
        return None
    trump_rank = start.get("trump_rank")
    deck = start.get("deck")
    if trump_rank not in RANKS or type(deck) is not list or len(deck) != 108:
        raise BeliefV2HumanInventoryError(
            "H0 complete round setup is malformed")
    try:
        rnd = rebuild_round(events)
    except Exception as exc:
        raise BeliefV2HumanInventoryError(
            "H0 complete round setup cannot be reconstructed") from exc
    if rnd is None:
        raise BeliefV2HumanInventoryError(
            "H0 complete round is missing setup events")

    human_decisions = 0
    attempted_counts: Counter[str] = Counter()
    for event in events:
        if event.get("e") != "play" or rnd.phase != "play":
            continue
        seat = event.get("seat")
        actual = event.get("cards")
        if type(seat) is not int or not 0 <= seat < 4 \
                or type(actual) is not list or rnd.turn != seat:
            raise BeliefV2HumanInventoryError(
                "H0 play event is malformed or off-turn")
        attempted = event.get("attempted_cards")
        attempted_complete = type(attempted) is list
        applied = attempted if attempted_complete else actual
        previous_last = rnd.last_trick
        try:
            rnd.play(seat, list(applied))
        except Exception as exc:
            raise BeliefV2HumanInventoryError(
                "H0 play event cannot be reconstructed") from exc
        if actual_play_after(rnd, seat, previous_last) != actual:
            raise BeliefV2HumanInventoryError(
                "H0 attempted/actual play channel disagrees with engine")
        if event.get("bot") is False and seat not in excluded_seats:
            human_decisions += 1
            attempted_counts[
                "complete" if attempted_complete else "absent"] += 1
    if rnd.phase != "round_end" \
            or rnd.attacker_points != end.get("attacker_points"):
        raise BeliefV2HumanInventoryError(
            "H0 round terminal reconstruction drift")
    return {
        "trump_rank": trump_rank,
        "human_play_decisions": human_decisions,
        "attempted_channel_counts": dict(sorted(attempted_counts.items())),
    }


def build_h0_inventory(*, source_manifest: Path,
                       source_paths: Iterable[Path]) -> dict[str, Any]:
    """Validate an exact source snapshot and return aggregate-only H0 facts."""
    manifest_path = Path(source_manifest).resolve()
    manifest_raw = manifest_path.read_bytes()
    members = _strict_source_manifest(manifest_raw)
    source_by_name: dict[str, Path] = {}
    for source_path in source_paths:
        path = Path(source_path).resolve()
        if path.name in source_by_name:
            raise BeliefV2HumanInventoryError(
                "H0 source basename population is duplicated")
        source_by_name[path.name] = path
    if set(source_by_name) != set(members):
        raise BeliefV2HumanInventoryError(
            "H0 source population differs from manifest")

    totals: Counter[str] = Counter()
    rank_counts: Counter[str] = Counter()
    attempted_counts: Counter[str] = Counter()
    group_rows: list[dict[str, Any]] = []
    source_digests: list[str] = []
    for name in sorted(members):
        raw = source_by_name[name].read_bytes()
        source_sha = _sha256(raw)
        if source_sha != members[name]:
            raise BeliefV2HumanInventoryError(
                "H0 source bytes differ from manifest")
        source_digests.append(source_sha)
        group_totals: Counter[str] = Counter()
        group_ranks: Counter[str] = Counter()
        group_attempted: Counter[str] = Counter()
        rounds = _events_by_round(raw)
        totals["rounds_seen"] += len(rounds)
        for events in rounds.values():
            start = next((event for event in events
                          if event.get("e") == "round_start"), None)
            excluded: set[int] = set()
            if start is not None:
                players = start.get("players")
                if type(players) is not list or len(players) != 4:
                    raise BeliefV2HumanInventoryError(
                        "H0 player population is malformed")
                for player in players:
                    if type(player) is not dict \
                            or type(player.get("seat")) is not int \
                            or type(player.get("name")) is not str:
                        raise BeliefV2HumanInventoryError(
                            "H0 player row is malformed")
                    if player["name"] in EXCLUDE_PLAYERS:
                        excluded.add(player["seat"])
            row = _inventory_round(events, excluded)
            if row is None:
                totals["incomplete_rounds"] += 1
                group_totals["incomplete_rounds"] += 1
                continue
            totals["complete_rounds"] += 1
            group_totals["complete_rounds"] += 1
            totals["human_play_decisions"] += row["human_play_decisions"]
            group_totals["human_play_decisions"] += row[
                "human_play_decisions"]
            rank_counts[row["trump_rank"]] += 1
            group_ranks[row["trump_rank"]] += 1
            attempted_counts.update(row["attempted_channel_counts"])
            group_attempted.update(row["attempted_channel_counts"])
        group_rows.append({
            "group_digest": _group_digest(source_sha),
            "source_bytes": len(raw),
            "complete_rounds": group_totals["complete_rounds"],
            "incomplete_rounds": group_totals["incomplete_rounds"],
            "human_play_decisions": group_totals["human_play_decisions"],
            "trump_rank_counts": dict(sorted(group_ranks.items())),
            "attempted_channel_counts": dict(sorted(group_attempted.items())),
        })
    population_sha = _sha256(canonical_json_bytes({
        "schema": "belief-v1-v2-human-source-digest-population-v1",
        "sha256s": sorted(source_digests),
    }))
    return {
        "schema": H0_INVENTORY_SCHEMA,
        "source_manifest_sha256": _sha256(manifest_raw),
        "source_file_count": len(source_digests),
        "source_digest_population_sha256": population_sha,
        "group_count": len(group_rows),
        "groups": sorted(group_rows, key=lambda row: row["group_digest"]),
        "rounds_seen": totals["rounds_seen"],
        "complete_rounds": totals["complete_rounds"],
        "incomplete_rounds": totals["incomplete_rounds"],
        "human_play_decisions": totals["human_play_decisions"],
        "trump_rank_counts": dict(sorted(rank_counts.items())),
        "attempted_channel_counts": dict(sorted(attempted_counts.items())),
        "hidden_ownership_labels_reconstructable_for_complete_rounds": True,
        "group_split_unit": "source-log-session-digest",
        "raw_player_identity_published": False,
        "model_rows_published": False,
        "training_authorized": False,
        "test_open_authorized": False,
        "strength_claim_authorized": False,
    }


def inventory_bytes(inventory: dict[str, Any]) -> bytes:
    verify_h0_inventory(inventory)
    return canonical_json_bytes(inventory)


def _counter(value: Any, *, allowed: set[str] | None = None) \
        -> Counter[str]:
    if type(value) is not dict \
            or any(type(key) is not str or not key
                   or type(count) is not int or count < 0
                   for key, count in value.items()) \
            or (allowed is not None and not set(value).issubset(allowed)):
        raise BeliefV2HumanInventoryError("H0 inventory counter drift")
    return Counter(value)


def verify_h0_inventory(inventory: dict[str, Any]) -> None:
    """Reopen an aggregate H0 receipt with a closed schema and no authority."""
    expected_keys = {
        "schema", "source_manifest_sha256", "source_file_count",
        "source_digest_population_sha256", "group_count", "groups",
        "rounds_seen", "complete_rounds", "incomplete_rounds",
        "human_play_decisions", "trump_rank_counts",
        "attempted_channel_counts",
        "hidden_ownership_labels_reconstructable_for_complete_rounds",
        "group_split_unit", "raw_player_identity_published",
        "model_rows_published", "training_authorized",
        "test_open_authorized", "strength_claim_authorized"}
    if type(inventory) is not dict or set(inventory) != expected_keys \
            or inventory["schema"] != H0_INVENTORY_SCHEMA \
            or any(type(inventory[key]) is not int or inventory[key] < 0
                   for key in (
                       "source_file_count", "group_count", "rounds_seen",
                       "complete_rounds", "incomplete_rounds",
                       "human_play_decisions")) \
            or inventory["source_file_count"] <= 0 \
            or inventory["group_count"] != inventory["source_file_count"] \
            or inventory["rounds_seen"] != inventory["complete_rounds"] \
            + inventory["incomplete_rounds"] \
            or type(inventory["groups"]) is not list \
            or len(inventory["groups"]) != inventory["group_count"] \
            or not _is_sha256(inventory["source_manifest_sha256"]) \
            or not _is_sha256(
                inventory["source_digest_population_sha256"]) \
            or inventory[
                "hidden_ownership_labels_reconstructable_for_complete_rounds"] \
            is not True \
            or inventory["group_split_unit"] \
            != "source-log-session-digest" \
            or any(inventory[key] is not False for key in (
                "raw_player_identity_published", "model_rows_published",
                "training_authorized", "test_open_authorized",
                "strength_claim_authorized")):
        raise BeliefV2HumanInventoryError("H0 inventory identity drift")
    rank_totals = _counter(
        inventory["trump_rank_counts"], allowed=set(RANKS))
    attempted_totals = _counter(
        inventory["attempted_channel_counts"],
        allowed={"complete", "absent"})
    if sum(rank_totals.values()) != inventory["complete_rounds"] \
            or sum(attempted_totals.values()) \
            != inventory["human_play_decisions"]:
        raise BeliefV2HumanInventoryError("H0 inventory total drift")
    group_digests = []
    complete = incomplete = decisions = source_bytes = 0
    group_ranks: Counter[str] = Counter()
    group_attempted: Counter[str] = Counter()
    for row in inventory["groups"]:
        if type(row) is not dict or set(row) != {
                "group_digest", "source_bytes", "complete_rounds",
                "incomplete_rounds", "human_play_decisions",
                "trump_rank_counts", "attempted_channel_counts"} \
                or type(row["group_digest"]) is not str \
                or len(row["group_digest"]) != 64 \
                or any(char not in "0123456789abcdef"
                       for char in row["group_digest"]) \
                or any(type(row[key]) is not int or row[key] < 0
                       for key in (
                           "source_bytes", "complete_rounds",
                           "incomplete_rounds", "human_play_decisions")) \
                or row["source_bytes"] <= 0:
            raise BeliefV2HumanInventoryError("H0 inventory group row drift")
        ranks = _counter(row["trump_rank_counts"], allowed=set(RANKS))
        attempted = _counter(
            row["attempted_channel_counts"],
            allowed={"complete", "absent"})
        if sum(ranks.values()) != row["complete_rounds"] \
                or sum(attempted.values()) != row["human_play_decisions"]:
            raise BeliefV2HumanInventoryError(
                "H0 inventory group accounting drift")
        group_digests.append(row["group_digest"])
        source_bytes += row["source_bytes"]
        complete += row["complete_rounds"]
        incomplete += row["incomplete_rounds"]
        decisions += row["human_play_decisions"]
        group_ranks.update(ranks)
        group_attempted.update(attempted)
    if group_digests != sorted(group_digests) \
            or len(group_digests) != len(set(group_digests)) \
            or source_bytes <= 0 \
            or complete != inventory["complete_rounds"] \
            or incomplete != inventory["incomplete_rounds"] \
            or decisions != inventory["human_play_decisions"] \
            or group_ranks != rank_totals \
            or group_attempted != attempted_totals:
        raise BeliefV2HumanInventoryError("H0 inventory group closure drift")


def validate_h0_inventory(inventory: dict[str, Any]) -> None:
    """Backward-compatible name for the exact H0 receipt verifier."""
    verify_h0_inventory(inventory)


def _split_key(group_digest: str) -> bytes:
    return hashlib.sha256(
        f"{H0_SPLIT_NAMESPACE}|{group_digest}".encode("ascii")).digest()


def _split_summary(groups: list[dict[str, Any]]) -> dict[str, Any]:
    ranks: Counter[str] = Counter()
    attempted: Counter[str] = Counter()
    for group in groups:
        ranks.update(group["trump_rank_counts"])
        attempted.update(group["attempted_channel_counts"])
    return {
        "group_count": len(groups),
        "group_digests": sorted(group["group_digest"] for group in groups),
        "complete_rounds": sum(group["complete_rounds"] for group in groups),
        "incomplete_rounds": sum(
            group["incomplete_rounds"] for group in groups),
        "human_play_decisions": sum(
            group["human_play_decisions"] for group in groups),
        "trump_rank_counts": dict(sorted(ranks.items())),
        "attempted_channel_counts": dict(sorted(attempted.items())),
    }


def _derive_h0_group_split(inventory: dict[str, Any]) -> dict[str, Any]:
    validate_h0_inventory(inventory)
    if inventory["group_count"] < 10:
        raise BeliefV2HumanInventoryError(
            "H0 group population is too small for 80/10/10 split")
    ordered = sorted(
        inventory["groups"],
        key=lambda row: (_split_key(row["group_digest"]),
                         row["group_digest"]))
    train_count = len(ordered) * 8 // 10
    calibration_count = len(ordered) // 10
    test_count = len(ordered) - train_count - calibration_count
    if min(train_count, calibration_count, test_count) <= 0:
        raise BeliefV2HumanInventoryError("H0 group split is empty")
    splits = {
        "train": _split_summary(ordered[:train_count]),
        "calibration": _split_summary(
            ordered[train_count:train_count + calibration_count]),
        "test": _split_summary(ordered[-test_count:]),
    }
    population = {
        split: row["group_digests"] for split, row in splits.items()}
    return {
        "schema": H0_SPLIT_SCHEMA,
        "namespace": H0_SPLIT_NAMESPACE,
        "inventory_sha256": _sha256(inventory_bytes(inventory)),
        "source_digest_population_sha256": (
            inventory["source_digest_population_sha256"]),
        "selection_inputs": ["group_digest"],
        "selection_uses_round_or_decision_counts": False,
        "selection_uses_labels_or_outcomes": False,
        "group_population_sha256": _sha256(canonical_json_bytes({
            "schema": "belief-v1-v2-human-group-split-population-v1",
            "splits": population,
        })),
        "splits": splits,
        "raw_player_identity_published": False,
        "model_rows_published": False,
        "training_authorized": False,
        "test_open_authorized": False,
        "strength_claim_authorized": False,
    }


def build_h0_group_split(inventory: dict[str, Any]) -> dict[str, Any]:
    result = _derive_h0_group_split(inventory)
    validate_h0_group_split(result, inventory=inventory)
    return result


def validate_h0_group_split(
        result: dict[str, Any], *, inventory: dict[str, Any]) -> None:
    expected = _derive_h0_group_split(inventory)
    if type(result) is not dict \
            or canonical_json_bytes(result) != canonical_json_bytes(expected):
        raise BeliefV2HumanInventoryError("H0 group split reconstruction drift")


def group_split_bytes(
        result: dict[str, Any], *, inventory: dict[str, Any]) -> bytes:
    validate_h0_group_split(result, inventory=inventory)
    return canonical_json_bytes(result)
