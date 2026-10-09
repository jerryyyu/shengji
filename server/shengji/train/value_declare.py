"""The value-guided trump declaration of the pv-search bot (OFF BY DEFAULT).

``SHENGJI_PV_VALUE_DECLARE=1`` (wiring, budget and record:
`pv_search_policy.PVSearchBot.decide_declare`).  This module is the bounded
world model the rule scores declarations with; nothing here chooses, serves or
registers anything, and nothing here consumes any bot's RNG.

At a declare chance the declaring seat knows its own (partial) hand, the
current declaration (its cards are public and must sit in the declarer's
hand), the trump rank and the banker (or that this is the first round).  It
does NOT know the undealt cards, the other hands or the kitty.  One world:

1. `sample_declare_world`: every card not in the seat's hand and not pinned by
   the current declaration is shuffled (a per-decision `random.Random`) and
   dealt to complete all four 25-card hands, the rest (8) is the kitty, in
   shuffled order (the order matters: an undeclared round flips trump from the
   kitty's first non-joker).  This is the uniform posterior given the seat's
   hand and the public declaration; it ignores what other seats' NOT
   declaring so far says about their hands, and any declaration that was
   overridden earlier (the engine keeps only the current one).
2. `declare_outcome_position`: the candidate declaration is applied with NO
   counter-declaration by anyone afterwards (the simplification: an override
   would need a model of every other seat's declare policy; the heuristic has
   none either).  PASS keeps the current declaration, or, when there is none,
   takes the engine's own no-declaration path (`Round.finalize_declare`: trump
   flipped from the sampled kitty, seat 0 banker in a first round).  The
   world's banker buries with the HEURISTIC bury (`HeuristicBot.decide_bury`),
   and the first trick is played by the heuristic (`default_finisher`),
   because the frozen value encoder rejects a position with no played card --
   exactly the leaf `cwv_bury.score_bury_candidates` scores a bury with
   (``first_trick_policy``, the "after one heuristic-continuation trick" leaf
   of `cwv_bury_diagnostic`).
3. The value head scores that position from the declaring seat's TEAM
   (`evaluator.score(positions, seat)`: expected signed level, the head's own
   units).

The bury is NOT the served hybrid arm (`cwv_bury_policy.CWVBuryMixin`): that
arm samples its own 32 worlds, ranks up to 32 candidates with the value head
and rolls out the finalists -- about a second per bury -- and the declare
evaluation needs one bury per (world, outcome), 64 x up to 5.  The heuristic
bury is the hybrid arm's incumbent (its slot 0) and its budget fallback.

Candidates that lead to the same (banker, trump) are the same outcome in this
model (a single and a pair of the same suit; two joker pairs), so each outcome
is scored once on the SAME worlds (paired).
"""
from __future__ import annotations

import copy
import hashlib
import json
import random
from collections import Counter

from ..ai.cwv_policy import default_finisher
from ..ai.heuristic import HeuristicBot
from ..engine.cards import card_suit, is_joker, make_deck
from ..engine.round import HAND_SIZE, KITTY_SIZE

SCHEMA = "pv-value-declare-v1"
#: the model the recipe digest binds (module docstring)
MODEL = "uniform-unseen|no-counter-declare|heuristic-bury|heuristic-first-trick|value-head-seat-team"
PASS = "PASS"
#: the bury every world's banker makes (stateless)
_HEURISTIC = HeuristicBot()


class ValueDeclareError(RuntimeError):
    """The world model refused a position (never reaches the server: the
    rule's stage abandons to the heuristic)."""


def outcome_key(rnd, seat: int, option) -> tuple:
    """``(banker, trump)`` after the declare window closes with ``option``
    (None = PASS) and no later declaration; trump ``"flip"`` when the kitty
    decides it."""
    if option is None:
        declaration = rnd.declaration
        if declaration is None:
            return (rnd.banker if rnd.banker is not None else 0, "flip")
        declarer, code = declaration["seat"], declaration["cards"][0]
    else:
        declarer, code = seat, option[0]
    trump = "NT" if is_joker(code) else card_suit(code)
    return (rnd.banker if rnd.banker is not None else declarer, trump)


def candidate_outcomes(rnd, seat: int, options, heuristic) -> list:
    """``[(key, representative)]``, one per distinct outcome: the heuristic's
    choice first (its own cards represent its outcome), then the options in
    engine order (an outcome the heuristic did not choose is represented by its
    STRONGEST option -- the hardest to override, though overrides are not
    modelled), then PASS (None) unless an option already reaches its outcome."""
    groups: dict = {}
    groups[outcome_key(rnd, seat, heuristic)] = heuristic
    for option in options:
        key = outcome_key(rnd, seat, option)
        held = groups.get(key)
        if key not in groups:
            groups[key] = list(option)
        elif held is not heuristic and held is not None and \
                rnd._declaration_strength(option) > rnd._declaration_strength(held):
            groups[key] = list(option)
    groups.setdefault(outcome_key(rnd, seat, None), None)
    return list(groups.items())


def decision_rng(seed, rnd, seat: int) -> random.Random:
    """A fresh per-decision stream: a function of the bot seed and what the
    seat sees (its hand, the cards dealt, the current declaration), never of
    call history, and never any bot's own RNG."""
    declaration = rnd.declaration
    material = json.dumps([SCHEMA, int(seed or 0), int(seat), sorted(rnd.hands[seat]),
                           sum(len(h) for h in rnd.hands),
                           None if declaration is None else
                           [declaration["seat"], sorted(declaration["cards"])]],
                          separators=(",", ":"))
    return random.Random(int.from_bytes(hashlib.sha256(material.encode()).digest()[:8], "big"))


def sample_declare_world(rnd, seat: int, rng: random.Random):
    """``(hands, kitty)``: one complete deal consistent with the seat's view
    (module docstring, step 1)."""
    pool = Counter(make_deck())
    pool.subtract(rnd.hands[seat])
    pinned = [[] for _ in range(4)]
    declaration = rnd.declaration
    if declaration is not None and declaration["seat"] != seat:
        pinned[declaration["seat"]] = list(declaration["cards"])
        pool.subtract(declaration["cards"])
    if any(count < 0 for count in pool.values()):
        raise ValueDeclareError("the seat's view holds more copies of a card than the deck")
    unseen = sorted(pool.elements())
    rng.shuffle(unseen)
    hands, used = [], 0
    for s in range(4):
        base = list(rnd.hands[s]) if s == seat else pinned[s]
        need = HAND_SIZE - len(base)
        if need < 0:
            raise ValueDeclareError("a hand exceeds the hand size")
        hands.append(base + unseen[used:used + need])
        used += need
    kitty = unseen[used:]
    if len(kitty) != KITTY_SIZE:
        raise ValueDeclareError(f"sampled kitty has {len(kitty)} cards")
    return hands, kitty


def declare_outcome_position(rnd, seat: int, hands, kitty, option, policy=None):
    """The engine position the value head scores for ``option`` in one world
    (module docstring, step 2): declare window closed, buried, first trick
    played.  ``rnd`` is never mutated."""
    policy = default_finisher() if policy is None else policy
    world = copy.copy(rnd)
    world.hands = [list(h) for h in hands]
    world.kitty = list(kitty)
    # a deck consistent with this world (the real deck is hidden information)
    world.deck = [hands[i % 4][i // 4] for i in range(4 * HAND_SIZE)] + list(kitty)
    world._deal_pos = 4 * HAND_SIZE
    world.phase = "declare"
    if option is None:
        current = rnd.declaration
        world.declaration = None if current is None else {**current, "cards": list(current["cards"])}
    else:
        world.declaration = {"seat": seat, "cards": list(option),
                             "strength": rnd._declaration_strength(list(option))}
    world.passed = set()
    world.ordering = None
    world.trump_suit = None
    world.trump_is_nt = False
    world.buried = []
    world.trick = None
    world.last_trick = None
    world.history = []
    world.attacker_points = 0
    world.kitty_bonus = 0
    world.last_trick_winner = None
    world.message = None
    world.notice = None
    world.turn = None
    world.finalize_declare()
    banker = world.banker
    world.bury(banker, _HEURISTIC.decide_bury(world, banker))
    for _ in range(4):
        actor = world.turn
        world.play(actor, policy.decide_play(world, actor))
    world._determinized_world = True
    return world


__all__ = ["SCHEMA", "MODEL", "PASS", "ValueDeclareError", "outcome_key", "candidate_outcomes",
           "decision_rng", "sample_declare_world", "declare_outcome_position"]
