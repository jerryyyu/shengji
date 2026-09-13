"""Seat-scoped observations for the W32 versus LLM benchmark (#355).

Build from an explicit allowlist, never by deleting fields from the private
Luna snapshot. The caller must additionally isolate memory/transport per seat
and construct ballots and rollout tools without privileged information.
"""
from __future__ import annotations

import hashlib

from .canonical import canonical_json_bytes


def _trick(trick):
    if trick is None:
        return None
    return {"leader": trick.leader,
            "plays": [{"seat": p.seat, "cards": list(p.cards)} for p in trick.plays],
            "winner": trick.winner, "points": trick.points}


def observation(rnd, seat: int, *, information: str) -> dict:
    """Return only information available to this seat, or an explicit PT view.

    No true-world digest, seed, deck, or waiting-seat snapshot is exposed. Even
    the PT arm uses seat-scoped memory so information access is the treatment,
    not permission to share a partnership's reasoning context.
    """
    if type(seat) is not int or seat not in range(4):
        raise ValueError("benchmark seat must be 0..3")
    if information not in ("actor-only", "perfect"):
        raise ValueError("unknown benchmark information mode")
    if rnd.phase != "play" or rnd.turn != seat:
        raise ValueError("benchmark observation requires the acting play seat")
    decl = rnd.declaration
    result = {
        "schema": "w32-llm-seat-observation-v1",
        "information": information, "seat": seat,
        "banker": rnd.banker, "trump_rank": rnd.trump_rank,
        "trump_suit": rnd.trump_suit, "trump_is_nt": rnd.trump_is_nt,
        "own_hand": sorted(rnd.hands[seat]),
        "hand_sizes": [len(h) for h in rnd.hands],
        "attacker_points": rnd.attacker_points,
        "declaration": None if decl is None else {
            "seat": decl["seat"], "cards": list(decl["cards"]),
            "strength": decl["strength"]},
        "history": [_trick(t) for t in rnd.history],
        "current_trick": _trick(rnd.trick),
    }
    if seat == rnd.banker:
        result["own_burial"] = sorted(rnd.buried)
    if information == "perfect":
        result["hands_by_seat"] = [sorted(h) for h in rnd.hands]
        result["burial"] = sorted(rnd.buried)
    # Bind only what is exposed. A private-state hash itself can reveal which
    # hidden world the harness holds, even when all card fields are redacted.
    result["observation_sha256"] = hashlib.sha256(canonical_json_bytes(result)).hexdigest()
    return result
