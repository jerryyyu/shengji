"""Outcome-blind state sources for the V0 afterstate experiment.

Reviewed PT-Sol transcripts are used only to supply realistic complete-world
decision states.  Their actions, rollout prose, and terminal results are not
numeric labels.  Each imported observation is rebased to actor seat 0,
mechanically replayed from remaining hands and public history, and paired with
the production ``mc-s0-report-lcb`` ballot recomputed by this source tree.
"""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import numpy as np

from ..ai.registry import make_bot
from ..engine.ballot import mc_ballot
from ..engine.cards import RANKS
from ..engine.round import Round
from ..teacher_v1 import action_key, ballot_problems
from .belief_contract import canonical_json_bytes
from .douzero_micro import encode_public_history
from .encode import encode_obs
from .world_afterstate import (
    SUCCESSOR_SCHEMA, WorldAfterstateError, actor_visible_root_identity,
    build_afterstate_audit_from_snapshot, canonical_successor,
    replay_canonical_successor,
)
from .world_afterstate_capacity import PRODUCTION_BALLOT_POLICY
from .world_afterstate_population import (
    SOURCES, WorldAfterstatePopulationError, build_population_group,
    fold_for_deal_group,
    validate_population_group)


PT_SOL_OBSERVE_KEYS = {
    "acting_seat", "attacker_points", "available_continuations", "banker",
    "budget", "candidate_zero_is_production_prior", "candidates",
    "completed_tricks", "current_trick", "decision_sha256", "hands_by_seat",
    "hidden_burial", "kitty_bonus_so_far", "objective",
    "remaining_points_by_seat", "role", "schema", "status",
    "team_is_attacker", "treatment_team", "trump_is_nt", "trump_rank",
    "trump_suit",
}
PT_SOL_ROUND_END_KEYS = {
    "attacker_points", "completion_token", "schema",
    "signed_level_utility", "status",
}
PRIVATE_SCHEMA = "privileged-teacher-sol0-private-evidence-v1"
TRANSCRIPT_SCHEMA = "privileged-teacher-sol0-private-transcript-v1"
ROUND_SOURCE_SCHEDULE_SCHEMA = "world-afterstate-round-source-schedule-v0"
ROUND_SOURCE_SEARCH_LIMIT = 16_384


class WorldAfterstateSourceError(WorldAfterstateError):
    """A reviewed state source, transcript, or recomputed ballot drifted."""


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _object_sha(value: object) -> str:
    return _sha(canonical_json_bytes(value))


def _derived_seed(*parts: object) -> int:
    return int.from_bytes(hashlib.sha256(canonical_json_bytes({
        "namespace": "world-afterstate-e3-e4-state-source-v0",
        "parts": list(parts),
    })).digest()[:8], "big") & (2**63 - 1)


def _source_seed_start(source: str, purpose: str) -> int:
    if source not in ("production-policy", "mechanics-hard") \
            or purpose not in ("rank-anchor", "mode-anchor"):
        raise WorldAfterstateSourceError("round-source namespace drift")
    raw = hashlib.sha256(
        f"world-afterstate-e3-e4-v0|{source}|{purpose}".encode(
            "ascii")).digest()
    return (int.from_bytes(raw[:8], "big") & (2**63 - 1)) // 65536 * 65536


def _round_spec(source: str, purpose: str, index: int) -> dict[str, Any]:
    if isinstance(index, bool) or not isinstance(index, int) or index < 0:
        raise WorldAfterstateSourceError("round-source index drift")
    seed = _source_seed_start(source, purpose) + index
    rank = RANKS[index % len(RANKS)]
    initial_banker = None if index % 5 == 0 else index % 4
    deal_group = _production_deal_group(
        deal_seed=seed, trump_rank=rank,
        initial_banker=initial_banker, source=source)
    return {
        "source": source, "purpose": purpose, "index": index,
        "deal_seed": seed, "trump_rank": rank,
        "initial_banker": initial_banker,
        "deal_group_sha256": deal_group,
        "fold": fold_for_deal_group(deal_group),
    }


def _declared_mode(spec: Mapping[str, Any]) -> str:
    if type(spec) is not dict:
        raise WorldAfterstateSourceError("round-source spec drift")
    seed = spec["deal_seed"]
    rnd = Round(spec["trump_rank"], spec["initial_banker"],
                random.Random(seed))
    policies = [make_bot(
        PRODUCTION_BALLOT_POLICY, seed=_derived_seed("trajectory", seed, seat))
        for seat in range(4)]
    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        cards = policies[seat].decide_declare(rnd, seat)
        if cards:
            rnd.declare(seat, cards)
    for seat in range(4):
        cards = policies[seat].decide_declare(rnd, seat, final=True)
        if cards:
            rnd.declare(seat, cards)
    rnd.finalize_declare()
    return "NT" if rnd.trump_is_nt else str(rnd.trump_suit)


def build_round_source_schedule(source: str) -> dict[str, Any]:
    """Derive rank/fold and mode/fold anchors before any play outcome."""
    if source not in ("production-policy", "mechanics-hard"):
        raise WorldAfterstateSourceError("round-source schedule drift")
    rank_needed = {(fold, rank) for fold in (
        "train", "calibration", "report", "provider-audit") for rank in RANKS}
    mode_needed = {(fold, mode) for fold in (
        "train", "calibration", "report", "provider-audit")
                   for mode in ("C", "D", "H", "S", "NT")}
    rows = []
    for index in range(ROUND_SOURCE_SEARCH_LIMIT):
        spec = _round_spec(source, "rank-anchor", index)
        key = (spec["fold"], spec["trump_rank"])
        if key in rank_needed:
            rows.append(spec)
            rank_needed.remove(key)
            if not rank_needed:
                break
    if rank_needed:
        raise WorldAfterstateSourceError(
            "round-source rank/fold schedule underfilled")
    for index in range(ROUND_SOURCE_SEARCH_LIMIT):
        spec = _round_spec(source, "mode-anchor", index)
        mode = _declared_mode(spec)
        key = (spec["fold"], mode)
        if key in mode_needed:
            rows.append({**spec, "observed_trump_mode": mode})
            mode_needed.remove(key)
            if not mode_needed:
                break
    if mode_needed:
        raise WorldAfterstateSourceError(
            "round-source mode/fold schedule underfilled")
    rows.sort(key=lambda row: (row["purpose"], row["index"]))
    body = {
        "schema": ROUND_SOURCE_SCHEDULE_SCHEMA,
        "source": source,
        "search_limit": ROUND_SOURCE_SEARCH_LIMIT,
        "rank_seed_start": _source_seed_start(source, "rank-anchor"),
        "mode_seed_start": _source_seed_start(source, "mode-anchor"),
        "round_count": len(rows),
        "rows": rows,
        "outcome_opened": False,
    }
    return {**body, "schedule_sha256": _object_sha(body)}


def validate_round_source_schedule(value: Mapping[str, Any]) -> None:
    if type(value) is not dict or value.get("source") not in (
            "production-policy", "mechanics-hard"):
        raise WorldAfterstateSourceError("round-source schedule schema drift")
    expected = build_round_source_schedule(value["source"])
    if canonical_json_bytes(dict(value)) != canonical_json_bytes(expected):
        raise WorldAfterstateSourceError(
            "round-source schedule reconstruction drift")


@dataclass(frozen=True)
class StateGroupMaterialV0:
    """One public group plus its separately retained private audit bytes."""

    group: dict[str, Any]
    audit_raws: tuple[bytes, ...]

    def validate(self) -> None:
        validate_population_group(self.group)
        candidates = self.group["candidates"]
        if type(self.audit_raws) is not tuple \
                or len(self.audit_raws) != len(candidates) \
                or any(type(raw) is not bytes for raw in self.audit_raws) \
                or [_sha(raw) for raw in self.audit_raws] \
                != [row["audit_sha256"] for row in candidates]:
            raise WorldAfterstateSourceError(
                "state-source audit population drift")


def build_state_group_material(
        snapshot: Mapping[str, Any], *, deal_group_sha256: str,
        source: str, policy_seed: int) -> StateGroupMaterialV0:
    """Materialize an exact production ballot from one complete snapshot."""
    if source not in SOURCES or source == "human-complete-provenance":
        raise WorldAfterstateSourceError("state-source identity drift")
    identity, audit_raws, _digest = production_ballot_from_snapshot(
        snapshot, policy_seed=policy_seed)
    fold = fold_for_deal_group(deal_group_sha256)
    group = build_population_group(
        deal_group_sha256=deal_group_sha256, source=source, fold=fold,
        actor_identity=identity, audit_raws=audit_raws)
    result = StateGroupMaterialV0(group=group, audit_raws=audit_raws)
    result.validate()
    return result


def _production_deal_group(
        *, deal_seed: int, trump_rank: str,
        initial_banker: int | None, source: str) -> str:
    return _object_sha({
        "namespace": "world-afterstate-e3-e4-deal-group-v0",
        "source": source, "deal_seed": deal_seed,
        "trump_rank": trump_rank, "initial_banker": initial_banker,
    })


def capture_production_round_materials(
        *, deal_seed: int, trump_rank: str,
        initial_banker: int | None, source: str = "production-policy",
        max_decisions: int | None = None) -> tuple[StateGroupMaterialV0, ...]:
    """Capture outcome-blind full-round states under the exact live policy.

    ``max_decisions`` exists only for bounded mechanics tests/censuses.  It
    truncates the state inventory before a terminal result and cannot change
    how any retained decision was reached.
    """
    if isinstance(deal_seed, bool) or not isinstance(deal_seed, int) \
            or not 0 <= deal_seed < 2**63 \
            or trump_rank not in (
                "2", "3", "4", "5", "6", "7", "8", "9", "10",
                "J", "Q", "K", "A") \
            or (initial_banker is not None
                and (isinstance(initial_banker, bool)
                     or not isinstance(initial_banker, int)
                     or not 0 <= initial_banker < 4)) \
            or source not in ("production-policy", "mechanics-hard") \
            or (max_decisions is not None
                and (isinstance(max_decisions, bool)
                     or not isinstance(max_decisions, int)
                     or max_decisions <= 0)):
        raise WorldAfterstateSourceError(
            "production state-source request drift")
    rnd = Round(trump_rank, initial_banker, random.Random(deal_seed))
    policies = [make_bot(
        PRODUCTION_BALLOT_POLICY,
        seed=_derived_seed("trajectory", deal_seed, seat))
        for seat in range(4)]
    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        cards = policies[seat].decide_declare(rnd, seat)
        if cards:
            rnd.declare(seat, cards)
    for seat in range(4):
        cards = policies[seat].decide_declare(rnd, seat, final=True)
        if cards:
            rnd.declare(seat, cards)
    rnd.finalize_declare()
    if rnd.banker is None:
        raise WorldAfterstateSourceError(
            "production state source has no banker")
    rnd.bury(rnd.banker, policies[rnd.banker].decide_bury(
        rnd, rnd.banker))
    deal_group = _production_deal_group(
        deal_seed=deal_seed, trump_rank=trump_rank,
        initial_banker=initial_banker, source=source)
    rows = []
    while rnd.phase == "play":
        actor = rnd.turn
        if actor is None:
            raise WorldAfterstateSourceError(
                "production state source has no actor")
        snapshot = canonical_successor(rnd, actor)
        try:
            material = build_state_group_material(
                snapshot, deal_group_sha256=deal_group, source=source,
                policy_seed=_derived_seed(
                    "ballot", actor_seed_identity(snapshot)))
        except WorldAfterstatePopulationError as exc:
            if source != "mechanics-hard" \
                    or str(exc) \
                    != "mechanics-hard state lacks a frozen hard-state reason":
                raise WorldAfterstateSourceError(
                    "production state materialization drift") from exc
        else:
            rows.append(material)
        if max_decisions is not None and len(rows) >= max_decisions:
            break
        action = policies[actor].decide_play(rnd, actor)
        rnd.play(actor, action)
    if not rows:
        raise WorldAfterstateSourceError(
            "production state source contains no decisions")
    return tuple(rows)


def capture_scheduled_round_materials(
        spec: Mapping[str, Any]) -> tuple[StateGroupMaterialV0, ...]:
    """Capture one exact row from a reconstructed rank/mode schedule."""
    if type(spec) is not dict or spec.get("source") not in (
            "production-policy", "mechanics-hard") \
            or spec.get("purpose") not in ("rank-anchor", "mode-anchor"):
        raise WorldAfterstateSourceError("scheduled round spec drift")
    expected = _round_spec(
        spec["source"], spec["purpose"], spec.get("index"))
    if spec["purpose"] == "mode-anchor":
        expected = {**expected, "observed_trump_mode": _declared_mode(expected)}
    if canonical_json_bytes(expected) != canonical_json_bytes(dict(spec)):
        raise WorldAfterstateSourceError(
            "scheduled round spec reconstruction drift")
    rows = capture_production_round_materials(
        deal_seed=spec["deal_seed"], trump_rank=spec["trump_rank"],
        initial_banker=spec["initial_banker"], source=spec["source"])
    if any(row.group["deal_group_sha256"] != spec["deal_group_sha256"]
           or row.group["fold"] != spec["fold"] for row in rows) \
            or ("observed_trump_mode" in spec
                and any(row.group["trump_mode"]
                        != spec["observed_trump_mode"] for row in rows)):
        raise WorldAfterstateSourceError(
            "scheduled round capture binding drift")
    return rows


def actor_seed_identity(snapshot: Mapping[str, Any]) -> str:
    """Hash only actor-visible pre-ballot bytes for deterministic RNG."""
    if type(snapshot) is not dict:
        raise WorldAfterstateSourceError("state-source snapshot drift")
    rnd = replay_canonical_successor(snapshot)
    public = np.asarray(encode_obs(rnd, 0), dtype="<f4")
    history = np.asarray(encode_public_history(rnd, 0), dtype="<f4")
    return _object_sha({
        "schema": "world-afterstate-actor-seed-identity-v0",
        "root_role": "attacker" if rnd.is_attacker(0) else "defender",
        "public_shape": list(public.shape),
        "public_sha256": hashlib.sha256(
            public.tobytes(order="C")).hexdigest(),
        "history_shape": list(history.shape),
        "history_sha256": hashlib.sha256(
            history.tobytes(order="C")).hexdigest(),
    })


def pt_sol_state_materials(
        raw: bytes, public_record: Mapping[str, Any]) \
        -> tuple[StateGroupMaterialV0, ...]:
    """Turn one reviewed PT-Sol full-round transcript into state materials."""
    root_sha = public_record.get("root_sha256")
    if type(root_sha) is not str or len(root_sha) != 64 \
            or any(char not in "0123456789abcdef" for char in root_sha):
        raise WorldAfterstateSourceError("PT-Sol root binding drift")
    snapshots = reopen_pt_sol_private_evidence(raw, public_record)
    rows = []
    seen: dict[str, StateGroupMaterialV0] = {}
    for snapshot in snapshots:
        material = build_state_group_material(
            snapshot, deal_group_sha256=root_sha,
            source="reviewed-pt-sol0",
            policy_seed=_derived_seed(
                "pt-sol-ballot", actor_seed_identity(snapshot)))
        decision_sha = material.group["decision_sha256"]
        if decision_sha in seen:
            previous = seen[decision_sha]
            if canonical_json_bytes(previous.group) \
                    != canonical_json_bytes(material.group) \
                    or previous.audit_raws != material.audit_raws:
                raise WorldAfterstateSourceError(
                    "PT-Sol repeated decision changed hidden mechanics")
            continue
        seen[decision_sha] = material
        rows.append(material)
    return tuple(rows)


def _hash_body(value: Mapping[str, Any], key: str) -> str:
    return _sha(canonical_json_bytes({
        name: item for name, item in value.items() if name != key
    }))


def _seat(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) \
            or not 0 <= value < 4:
        raise WorldAfterstateSourceError(f"{label} drift")
    return value


def _relative(seat: int | None, root: int) -> int | None:
    return None if seat is None else (seat - root) % 4


def _cards(value: object, label: str) -> list[str]:
    from .encode import CARD_INDEX
    if type(value) not in (list, tuple):
        raise WorldAfterstateSourceError(f"{label} drift")
    result = list(value)
    if any(type(card) is not str or card not in CARD_INDEX for card in result):
        raise WorldAfterstateSourceError(f"{label} drift")
    return result


def _relative_trick(value: object, root: int, *, completed: bool) \
        -> dict[str, Any]:
    if type(value) is not dict or set(value) != {
            "leader", "plays", "winner", "points"}:
        raise WorldAfterstateSourceError("PT-Sol trick schema drift")
    plays = value["plays"]
    if type(plays) not in (list, tuple) \
            or (completed and len(plays) != 4) \
            or (not completed and not 0 <= len(plays) < 4):
        raise WorldAfterstateSourceError("PT-Sol trick population drift")
    normalized_plays = []
    for play in plays:
        if type(play) is not dict or set(play) != {"seat", "cards"}:
            raise WorldAfterstateSourceError("PT-Sol play schema drift")
        normalized_plays.append({
            "seat": _relative(_seat(play["seat"], "PT-Sol play seat"), root),
            "cards": sorted(_cards(play["cards"], "PT-Sol play cards")),
        })
    winner = value["winner"]
    if winner is not None:
        winner = _relative(_seat(winner, "PT-Sol trick winner"), root)
    if completed and winner is None:
        raise WorldAfterstateSourceError("PT-Sol completed winner drift")
    if not completed and winner is not None:
        raise WorldAfterstateSourceError("PT-Sol current winner drift")
    points = value["points"]
    if isinstance(points, bool) or not isinstance(points, int) or points < 0 \
            or (not completed and points != 0):
        raise WorldAfterstateSourceError("PT-Sol trick points drift")
    return {
        "leader": _relative(
            _seat(value["leader"], "PT-Sol trick leader"), root),
        "plays": normalized_plays,
        "winner": winner,
        "points": points,
    }


def normalize_pt_sol_observation(response: Mapping[str, Any]) \
        -> dict[str, Any]:
    """Convert one reviewed full-game PT observation to a complete snapshot."""
    if type(response) is not dict or set(response) != PT_SOL_OBSERVE_KEYS \
            or response.get("schema") \
            != "privileged-teacher-sol0-tool-response-v1" \
            or response.get("status") != "decision" \
            or response.get("candidate_zero_is_production_prior") is not True:
        raise WorldAfterstateSourceError("PT-Sol observation identity drift")
    root = _seat(response["acting_seat"], "PT-Sol acting seat")
    banker = _seat(response["banker"], "PT-Sol banker")
    hands = response["hands_by_seat"]
    if type(hands) not in (list, tuple) or len(hands) != 4:
        raise WorldAfterstateSourceError("PT-Sol hand population drift")
    absolute_hands = [_cards(hand, "PT-Sol hand") for hand in hands]
    relative_hands = [
        sorted(absolute_hands[(root + relative) % 4])
        for relative in range(4)
    ]
    completed = response["completed_tricks"]
    if type(completed) not in (list, tuple):
        raise WorldAfterstateSourceError(
            "PT-Sol completed-trick population drift")
    current = response["current_trick"]
    if current is None:
        raise WorldAfterstateSourceError("PT-Sol decision lacks current trick")
    team_is_attacker = response["team_is_attacker"]
    if type(team_is_attacker) is not bool:
        raise WorldAfterstateSourceError("PT-Sol team role drift")
    attacker_points = response["attacker_points"]
    kitty_bonus = response["kitty_bonus_so_far"]
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 0
           for value in (attacker_points, kitty_bonus)):
        raise WorldAfterstateSourceError("PT-Sol score drift")
    trump_is_nt = response["trump_is_nt"]
    trump_suit = response["trump_suit"]
    if type(trump_is_nt) is not bool \
            or trump_suit not in ("C", "D", "H", "S", None) \
            or trump_is_nt is not (trump_suit is None):
        raise WorldAfterstateSourceError("PT-Sol trump-mode drift")
    snapshot = {
        "schema": SUCCESSOR_SCHEMA,
        "root_role": "attacker" if team_is_attacker else "defender",
        "public": {
            "phase": "play",
            "terminal": False,
            "turn": 0,
            "banker": _relative(banker, root),
            # PT-Full starts from a named prior banker and does not retain
            # declaration/message bytes. Neither field is a V0 tensor.
            "first_round": False,
            "trump_rank": response["trump_rank"],
            "trump_suit": trump_suit,
            "trump_is_nt": trump_is_nt,
            "declaration": None,
            "attacker_points": attacker_points,
            "kitty_bonus": kitty_bonus,
            "last_trick_winner": None,
            "completed_tricks": [
                _relative_trick(trick, root, completed=True)
                for trick in completed
            ],
            "current_trick": _relative_trick(
                current, root, completed=False),
            "message": None,
            "hand_sizes": [len(hand) for hand in relative_hands],
        },
        "complete_world": {
            "hands": relative_hands,
            "buried": sorted(_cards(
                response["hidden_burial"], "PT-Sol hidden burial")),
        },
    }
    try:
        rnd = replay_canonical_successor(snapshot)
    except WorldAfterstateError as exc:
        raise WorldAfterstateSourceError(
            "PT-Sol observation mechanics drift") from exc
    if rnd.turn != 0 or rnd.is_attacker(0) is not team_is_attacker:
        raise WorldAfterstateSourceError("PT-Sol root-role binding drift")
    return snapshot


def production_ballot_from_snapshot(
        snapshot: Mapping[str, Any], *, policy_seed: int) \
        -> tuple[dict[str, Any], tuple[bytes, ...], str]:
    """Recompute and materialize the exact production ballot at a snapshot."""
    identity, candidates, digest = production_ballot_identity_from_snapshot(
        snapshot, policy_seed=policy_seed)
    raws = tuple(canonical_json_bytes(
        build_afterstate_audit_from_snapshot(snapshot, action))
        for action in candidates)
    return identity, raws, digest


def production_ballot_identity_from_snapshot(
        snapshot: Mapping[str, Any], *, policy_seed: int) \
        -> tuple[dict[str, Any], tuple[tuple[str, ...], ...], str]:
    """Recompute a ballot without materializing candidate afterstate rows."""
    if isinstance(policy_seed, bool) or not isinstance(policy_seed, int) \
            or not 0 <= policy_seed < 2**63:
        raise WorldAfterstateSourceError("production ballot seed drift")
    rnd = replay_canonical_successor(snapshot)
    if rnd.phase != "play" or rnd.turn != 0:
        raise WorldAfterstateSourceError(
            "production ballot requires an actor-root decision")
    policy = make_bot(PRODUCTION_BALLOT_POLICY, seed=policy_seed)
    candidates = [list(action_key(action))
                  for action in policy._candidates(rnd, 0)]
    problems = ballot_problems(rnd, 0, candidates)
    if problems:
        raise WorldAfterstateSourceError(
            "production ballot refused: " + "; ".join(problems))
    identity = actor_visible_root_identity(rnd, 0, candidates)
    return (identity, tuple(tuple(action) for action in candidates),
            mc_ballot(policy).digest)


def reopen_pt_sol_private_evidence(
        raw: bytes, public_record: Mapping[str, Any]) \
        -> tuple[dict[str, Any], ...]:
    """Authenticate one private transcript against its reviewed public row."""
    if type(raw) is not bytes or type(public_record) is not dict:
        raise WorldAfterstateSourceError("PT-Sol evidence request drift")
    try:
        value = json.loads(raw.decode("ascii"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise WorldAfterstateSourceError(
            "PT-Sol private evidence is not canonical JSON") from exc
    if type(value) is not dict or canonical_json_bytes(value) != raw \
            or value.get("schema") != PRIVATE_SCHEMA \
            or _sha(raw) != public_record.get("private_evidence_sha256") \
            or value.get("evidence_sha256") != _hash_body(
                value, "evidence_sha256") \
            or value.get("process_returncode") != 0 \
            or value.get("process_error") is not None:
        raise WorldAfterstateSourceError("PT-Sol private evidence drift")
    transcript = value.get("transcript")
    if type(transcript) is not dict \
            or transcript.get("schema") != TRANSCRIPT_SCHEMA \
            or transcript.get("transcript_sha256") != _hash_body(
                transcript, "transcript_sha256") \
            or transcript.get("role") != public_record.get("role") \
            or transcript.get("treatment_team") \
            != public_record.get("treatment_team"):
        raise WorldAfterstateSourceError("PT-Sol private transcript drift")
    coordinate = transcript.get("coordinate")
    expected_coordinate = [
        public_record.get("trump_rank"), public_record.get("banker"),
        public_record.get("replicate"),
    ]
    status = transcript.get("status")
    sol = public_record.get("sol0")
    events = transcript.get("events")
    if coordinate != expected_coordinate or type(status) is not dict \
            or status.get("status") != "round_end" or type(sol) is not dict \
            or status.get("attacker_points") != sol.get("attacker_points") \
            or status.get("signed_level_utility") \
            != sol.get("signed_level_utility") \
            or type(events) is not list \
            or [event.get("index") for event in events] \
            != list(range(len(events))):
        raise WorldAfterstateSourceError("PT-Sol transcript binding drift")
    observations = []
    for event in events:
        if type(event) is not dict or set(event) != {
                "index", "operation", "request", "response"}:
            raise WorldAfterstateSourceError("PT-Sol event schema drift")
        if event["operation"] == "observe":
            response = event["response"]
            if type(response) is not dict:
                raise WorldAfterstateSourceError(
                    "PT-Sol observe response drift")
            if response.get("status") == "decision":
                observations.append(normalize_pt_sol_observation(response))
            elif response.get("status") == "round_end":
                if set(response) != PT_SOL_ROUND_END_KEYS \
                        or response.get("schema") \
                        != "privileged-teacher-sol0-tool-response-v1" \
                        or response.get("attacker_points") \
                        != status.get("attacker_points") \
                        or response.get("signed_level_utility") \
                        != status.get("signed_level_utility"):
                    raise WorldAfterstateSourceError(
                        "PT-Sol terminal observation drift")
            else:
                raise WorldAfterstateSourceError(
                    "PT-Sol observe status drift")
    if not observations:
        raise WorldAfterstateSourceError(
            "PT-Sol transcript contains no decision observations")
    return tuple(observations)


__all__ = [
    "StateGroupMaterialV0", "WorldAfterstateSourceError",
    "actor_seed_identity", "build_round_source_schedule",
    "build_state_group_material", "capture_production_round_materials",
    "capture_scheduled_round_materials", "normalize_pt_sol_observation",
    "pt_sol_state_materials",
    "production_ballot_from_snapshot",
    "production_ballot_identity_from_snapshot",
    "reopen_pt_sol_private_evidence", "validate_round_source_schedule",
]
