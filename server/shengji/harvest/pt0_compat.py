"""PT0's actor-visible public-state hash, carried verbatim.

``shengji/rl/privileged_teacher_pt0.py`` left main with the PT keep-set
pruning (#197).  The PT1 evidence groups were hashed with its
``pt0_public_state_sha256`` and the PT1 extractor verifies every replayed
state against that hash, so the function (and only the helpers it needs)
is kept here byte-for-byte from commit 5fc57570's copy of that module.
Do not "improve" it: any change silently breaks the PT1 hash check.
"""

from __future__ import annotations

import hashlib
import json
from typing import Mapping, Sequence

PT0_PUBLIC_STATE_SCHEMA = "privileged-teacher-pt0-actor-visible-state-v1"


class PrivilegedTeacherPT0Error(ValueError):
    """PT0 refusal (name kept so the ported code reads unchanged)."""


def canonical_json_bytes(value: object) -> bytes:
    """Return the closed canonical encoding used by PT0 target hashes."""
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=True) + "\n").encode("ascii")


def _public_trick_payload(trick: object | None) -> object | None:
    """Encode only the actor-visible part of one engine trick."""
    if trick is None:
        return None
    return {
        "leader": trick.leader,
        "plays": [
            {"seat": play.seat, "cards": sorted(play.cards)}
            for play in trick.plays
        ],
        "winner": trick.winner,
        "points": trick.points,
    }


def _public_declaration_payload(declaration: object | None) \
        -> object | None:
    if declaration is None:
        return None
    if not isinstance(declaration, Mapping) or set(declaration) != {
            "seat", "cards", "strength"}:
        raise PrivilegedTeacherPT0Error(
            "PT0 public declaration shape drift")
    cards = declaration.get("cards")
    if isinstance(cards, (str, bytes)) or not isinstance(cards, Sequence):
        raise PrivilegedTeacherPT0Error(
            "PT0 public declaration shape drift")
    return {
        "seat": declaration.get("seat"),
        "cards": sorted(cards),
        "strength": declaration.get("strength"),
    }


def pt0_public_state_sha256(
        rnd: object, *, perspective_seat: int) -> str:
    """Hash the complete actor-visible state shared by compatible worlds.

    The true other hands, undealt deck order, and (for a non-banker) buried
    card identities are deliberately absent.  The actor's own hand and a
    banker's own burial are private-to-actor observations and therefore are
    included.  PT0 derives this value from every supplied ``Round``; callers
    cannot merely assert that separately solved worlds form one information
    set.
    """
    from shengji.engine.round import Round  # pylint: disable=import-outside-toplevel

    if type(rnd) is not Round:
        raise PrivilegedTeacherPT0Error(
            "PT0 public state requires exact Round")
    if (isinstance(perspective_seat, bool)
            or not isinstance(perspective_seat, int)
            or not 0 <= perspective_seat < 4):
        raise PrivilegedTeacherPT0Error(
            "perspective_seat must be an integer seat in [0, 3]")
    if rnd.phase != "play" or rnd.turn != perspective_seat \
            or rnd.banker is None or rnd.ordering is None \
            or rnd.trick is None:
        raise PrivilegedTeacherPT0Error(
            "PT0 public state requires an active actor decision")
    payload = {
        "schema": PT0_PUBLIC_STATE_SCHEMA,
        "perspective_seat": perspective_seat,
        "phase": rnd.phase,
        "turn": rnd.turn,
        "banker": rnd.banker,
        "first_round": rnd.first_round,
        "trump_rank": rnd.trump_rank,
        "trump_suit": rnd.trump_suit,
        "trump_is_nt": rnd.trump_is_nt,
        "declaration": _public_declaration_payload(rnd.declaration),
        "passed": sorted(rnd.passed),
        "hand_sizes": [len(hand) for hand in rnd.hands],
        "actor_hand": sorted(rnd.hands[perspective_seat]),
        "burial": {
            "count": len(rnd.buried),
            "actor_visible_cards": (
                sorted(rnd.buried)
                if perspective_seat == rnd.banker else None),
        },
        "attacker_points": rnd.attacker_points,
        "history": [_public_trick_payload(trick) for trick in rnd.history],
        "current_trick": _public_trick_payload(rnd.trick),
    }
    try:
        return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
    except (TypeError, ValueError) as exc:
        raise PrivilegedTeacherPT0Error(
            "PT0 public state is not canonical") from exc
