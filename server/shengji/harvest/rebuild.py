"""Reconstruct engine state from a decision record.

A record stores the deal (explicit 108-card ``deck`` or a ``round_seed``),
the ``setup`` (trump rank, banker, declarations, bury) and ``plays_prefix``.
``round_from_setup`` follows ``replay_log.rebuild_round`` exactly (deal the
deck round-robin, replay the declarations in order, finalize, bury) so a
record round-trips through the same path the analysis tooling already uses.
"""

from __future__ import annotations

import random
from collections import Counter
from typing import Any, Mapping, Sequence

from ..engine.cards import card_suit, is_joker, make_deck
from ..engine.round import HAND_SIZE, KITTY_SIZE, Round


class RebuildError(ValueError):
    """The record cannot be turned back into a legal engine state."""


# ------------------------------------------------------------------ outcome

def signed_level_utility(attacker_points: int, *, banker_seat: int,
                         perspective_seat: int) -> int:
    """PT0 convention (``privileged_teacher_pt0.signed_level_utility``):
    +gain when the perspective seat's partnership won the round; an 80-point
    attacker takeover counts one level."""
    perspective_is_attacker = perspective_seat % 2 != banker_seat % 2
    if attacker_points >= 80:
        attacker_won = True
        gain = max(1, (attacker_points - 80) // 40)
    else:
        attacker_won = False
        gain = 3 if attacker_points == 0 else (2 if attacker_points < 40 else 1)
    return gain if perspective_is_attacker == attacker_won else -gain


def engine_level_change(attacker_points: int) -> int:
    """``Game.finish_round`` gain: 0 for an 80-119 attacker takeover (the
    attackers only take the deal), unlike the PT0 utility which counts it as
    one level."""
    if attacker_points >= 80:
        return (attacker_points - 80) // 40
    return 3 if attacker_points == 0 else (2 if attacker_points < 40 else 1)


def outcome_for(attacker_points: int, *, banker: int, seat: int,
                kitty_bonus: int | None = None) -> dict[str, Any]:
    """Round result signed for ``seat``'s partnership (see schema.py).

    ``winner_team`` / ``level_change`` follow the engine's ``Game`` (seat
    parity, raw gain); ``signed_level_utility`` follows the PT0 convention.
    """
    banker_team = banker % 2
    winner_team = (1 - banker_team) if attacker_points >= 80 else banker_team
    out: dict[str, Any] = {
        "attacker_points": int(attacker_points),
        "winner_team": winner_team,
        "level_change": engine_level_change(attacker_points),
        "signed_level_utility": signed_level_utility(
            attacker_points, banker_seat=banker, perspective_seat=seat),
    }
    if kitty_bonus is not None:
        out["kitty_bonus"] = int(kitty_bonus)
    return out


# -------------------------------------------------------------------- setup

def setup_from_round(rnd: Round) -> dict[str, Any]:
    """The ``setup`` object for a round at/after bury."""
    return {
        "trump_rank": rnd.trump_rank,
        "banker": rnd.banker,
        "declarations": [],          # filled by the extractor when known
        "declaration": (None if rnd.declaration is None
                        else {"seat": rnd.declaration["seat"],
                              "cards": list(rnd.declaration["cards"]),
                              "strength": rnd.declaration["strength"]}),
        "trump_suit": rnd.trump_suit,
        "trump_is_nt": bool(rnd.trump_is_nt),
        "buried": sorted(rnd.buried) if rnd.buried else None,
    }


def round_from_setup(deck: Sequence[str], setup: Mapping[str, Any], *,
                     stop_before_bury: bool = False,
                     check_trump: bool = True) -> Round:
    """``replay_log.rebuild_round`` semantics from record fields.

    ``check_trump=False`` skips the cross-check against ``setup.trump_suit`` /
    ``trump_is_nt`` for sources that do not store them (the caller derives
    them from the returned round).
    """
    if len(deck) != 108 or sorted(deck) != sorted(make_deck()):
        raise RebuildError("deck must be a permutation of the 108-card deck")
    rnd = Round(setup["trump_rank"], setup["banker"], random.Random(0))
    rnd.deck = list(deck)
    rnd.hands = [[], [], [], []]
    rnd._deal_pos = 0
    rnd.phase = "deal"
    rnd.kitty = list(deck[4 * HAND_SIZE:])
    while rnd.phase == "deal":
        rnd.deal_next()
    for d in setup.get("declarations") or []:
        rnd.declare(d["seat"], list(d["cards"]))
    # seats that passed after the last declaration (PT1 records them; the
    # PT0 public-state hash covers ``passed``, play itself never reads it)
    for seat in setup.get("passed") or []:
        rnd.pass_declare(int(seat))
    rnd.finalize_declare()
    if rnd.banker != setup["banker"]:
        raise RebuildError("banker drift after finalize_declare")
    if check_trump and (rnd.trump_suit != setup["trump_suit"]
                        or bool(rnd.trump_is_nt) != bool(setup["trump_is_nt"])):
        raise RebuildError("trump drift after finalize_declare")
    if stop_before_bury:
        return rnd
    buried = setup.get("buried")
    if not buried:
        raise RebuildError("bury unknown; cannot reach the play phase")
    rnd.bury(rnd.banker, list(buried))
    return rnd


def replay_prefix(rnd: Round, plays_prefix: Sequence[Mapping[str, Any]]) -> Round:
    for play in plays_prefix:
        rnd.play(int(play["seat"]), list(play["cards"]))
    return rnd


def state_for_record(record: Mapping[str, Any], *,
                     deck: Sequence[str] | None = None) -> Round:
    """Rebuild the decision state of ``record`` (deck may be supplied from the
    private split when the public row withholds it)."""
    deck = deck if deck is not None else record.get("deck")
    if deck is None:
        seed = record.get("round_seed")
        if seed is None:
            raise RebuildError("record has neither deck nor round_seed")
        deck = deck_from_seed(record["setup"]["trump_rank"],
                              record["setup"]["banker"], seed)
    if record["decision_kind"] == "bury":
        return round_from_setup(deck, record["setup"], stop_before_bury=True)
    rnd = round_from_setup(deck, record["setup"])
    return replay_prefix(rnd, record["plays_prefix"])


def deck_from_seed(trump_rank: str, banker: int | None, seed: int) -> list[str]:
    """The deal order ``Round(trump_rank, banker, random.Random(seed))`` draws."""
    return list(Round(trump_rank, banker, random.Random(seed)).deck)


# -------------------------------------------------------------- hidden hands

def hands_snapshot(rnd: Round) -> dict[str, Any]:
    return {"hands_by_seat": [sorted(h) for h in rnd.hands],
            "buried": sorted(rnd.buried)}


def synthetic_deck(hands_at_play: Sequence[Sequence[str]], buried: Sequence[str],
                   *, banker: int, declaration: Mapping[str, Any] | None,
                   trump_suit: str | None, trump_is_nt: bool) -> list[str]:
    """A deal order consistent with the hands at the start of play.

    Sources that record hands but not the deal (Luna trajectories) get a
    synthetic order: seat ``s`` receives ``deck[s::4][:25]``; the kitty is
    eight of the banker's 33 (final hand + burial) chosen so the recorded
    declaration stays in the dealt cards and a no-declaration kitty flip
    still yields the recorded trump.  The hands and the play are unaffected
    by which eight went to the kitty; the order is synthetic and the caller
    must label it as such.
    """
    hands = [list(h) for h in hands_at_play]
    if len(hands) != 4 or any(len(h) != HAND_SIZE for h in hands):
        raise RebuildError("synthetic deck needs four 25-card hands")
    if len(buried) != KITTY_SIZE:
        raise RebuildError("synthetic deck needs an 8-card burial")
    pool = sorted(hands[banker]) + sorted(buried)
    declared = Counter(declaration["cards"]) if declaration else Counter()
    if declaration is not None and declaration["seat"] == banker:
        available = Counter(pool)
        for code, n in declared.items():
            if available[code] < n:
                raise RebuildError("declaration cards absent from banker pool")
    reserve = Counter(declared) if (declaration is not None
                                    and declaration["seat"] == banker) else Counter()
    kitty: list[str] = []
    rest: list[str] = []
    if declaration is None:
        if trump_is_nt:
            raise RebuildError("no declaration with NT trump is not "
                               "reconstructible (kitty flip needs a suit)")
        flip = next((c for c in pool if card_suit(c) == trump_suit), None)
        if flip is None:
            raise RebuildError("no banker card can flip the recorded trump")
        kitty.append(flip)
        pool = list(pool)
        pool.remove(flip)
    for code in sorted(buried) + sorted(hands[banker]):
        if code not in pool:
            continue
        pool.remove(code)
        if reserve[code] > 0:
            reserve[code] -= 1
            rest.append(code)
        elif len(kitty) < KITTY_SIZE:
            kitty.append(code)
        else:
            rest.append(code)
    if len(kitty) != KITTY_SIZE:
        raise RebuildError("could not assemble a kitty")
    if declaration is None:
        # a joker-first kitty would flip NT; keep the chosen flip card first
        assert not is_joker(kitty[0])
    dealt = [sorted(h) for h in hands]
    dealt[banker] = sorted(rest)
    if any(len(h) != HAND_SIZE for h in dealt):
        raise RebuildError("dealt hands are not 25 cards each")
    deck: list[str] = [""] * (4 * HAND_SIZE)
    for seat in range(4):
        for i, code in enumerate(dealt[seat]):
            deck[seat + 4 * i] = code
    deck.extend(kitty)
    if sorted(deck) != sorted(make_deck()):
        raise RebuildError("synthetic deck is not a permutation of the deck")
    return deck


def actor_role(rnd: Round, seat: int) -> str:
    assert rnd.banker is not None
    return "attacker-team" if seat % 2 != rnd.banker % 2 else "banker-team"
