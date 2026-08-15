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


class BeliefV2HumanInventoryError(ValueError):
    """The private-log H0 inventory cannot be published safely."""


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


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
    if type(inventory) is not dict or inventory.get("schema") != H0_INVENTORY_SCHEMA:
        raise BeliefV2HumanInventoryError("H0 inventory schema is invalid")
    return canonical_json_bytes(inventory)
