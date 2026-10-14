"""The value declaration's WAIT option (OFF BY DEFAULT;
``SHENGJI_PV_VALUE_DECLARE_WAIT=1``, name token ``vdw``; #707 S15).

The value declaration (`value_declare`, release 44's ``vd``) decides at a
declare chance during the deal whether to declare NOW, and what; its PASS is
"never declare" (the window closes with whatever stands).  It never weighs
declaring LATER -- with the rest of the hand seen -- against declaring now.
Humans do: in the #995 evidence (`scripts/declare_pass_evidence.py`) 14 of 25
human pair declarations came in the post-deal grace window, and 39 of 64
humans holding an over-declaring pair stayed silent.

With this rule on, when the value declaration has decided to declare at a
chance DURING the deal (``final=False``), a second pass compares two policies
on the same sampled worlds:

* NOW: declare the chosen option now;
* WAIT: stay silent now.

The worlds are the ordinary pass's own per-decision stream
(`value_declare.decision_rng`, `value_declare.sample_declare_world`: complete
deals consistent with the seat's view), FILTERED by a current-standing
heuristic consistency check: a draw is kept only when no other seat would
declare against the CURRENT standing declaration by the heuristic
(`silence_consistent`).  Without it the opponent model below contradicts the
silence already observed in the most blatant way -- the simulation makes those
seats declare at their very next card, a burst of pre-emptions that biases
against waiting (on 40 seeded deals ~41% of uniform draws failed the filter).
It is a consistency filter, not a likelihood of the observed history: it may
keep worlds inconsistent with earlier standing states (approximation 3).  The first `WORLDS_DEFAULT` kept draws are used, at
most `DRAWS_CAP` draws; none kept abandons the pass.  In each kept world both
branches play out the REST OF THE DEAL in deal order (`continuation_round`, `play_out_deal`): after every card a
seat other than the decider receives, that seat declares by the heuristic
declare policy (`HeuristicBot.decide_declare`, ``final=False``) -- opponents
and partner alike, human or bot.  The decider stays silent in both branches
until the deal ends; then it makes ONE decision (`end_choice`): among its
legal options at that point and PASS (keeping whatever stands -- its own
declaration in NOW unless it was overcalled), merged by outcome
(`value_declare.candidate_outcomes`), it takes the argmax of the value head's
mean over `INNER_WORLDS_DEFAULT` fresh worlds sampled from ITS OWN END-OF-DEAL
VIEW (its 25 cards and the standing declaration).  The chosen outcome is then
scored in the outer world (`value_declare.declare_outcome_position`, the same
leaf as the ordinary pass), and a branch's value is the mean over the outer
worlds.  The bot waits (returns PASS now) only when WAIT's mean beats NOW's by
more than ``value_declare_margin`` -- the same margin rule.

Why the inner sample.  The value head scores COMPLETE worlds; a per-world max
over the end options would pick with the other hands in view, and that
clairvoyance favours WAIT (whose end choice set is wider) -- the unsafe
direction.  Choosing on the decider's own end view and scoring in the outer
world is an unbiased estimate (in this model) of the value of a real
end-of-deal policy, at a smaller sample than the served grace-window decision
(64 worlds).  Equal outcome keys in the two branches score identically (the
encoder reads no declaration cards), so a world where both branches end on the
same (banker, trump) contributes exactly zero to the difference.

Approximations (declared):

1. myopic opponents: every other seat follows the heuristic declare policy,
   which reacts to a standing declaration only through legality (it can only
   overcall); a real opponent may respond to what it sees, and the bots at the
   table run the value declaration, not the heuristic;
2. one future decision point: the decider does not act again during the rest
   of the deal in either branch (the served bot re-evaluates at each of its
   later cards, and can declare earlier than the end), and nobody responds in
   the grace window, before or after the decider's end choice (the ordinary
   pass's own "no counter-declaration" simplification);
3. the silence filter checks each other seat against the CURRENT standing
   declaration only, under the heuristic model.  It is not an exact likelihood
   of any seat's past silence, not even its last one: a stronger declaration
   made since that chance shrinks the seat's legal options, so "cannot declare
   now" does not show "would not have declared then" (a seat holding C7 C7
   that the heuristic would have declared with nothing standing is accepted
   once another seat's D7 D7 stands).  Worlds inconsistent with earlier
   standing states can therefore be kept; a seat's earlier silences, overridden
   declarations, and a human's or a value-declaring bot's reasons to wait are
   not modelled.  Under the ``vdpw`` rule the wait pass still draws uniform
   worlds (`value_declare.sample_declare_world`), not the pass-conditioned
   ones;
4. the world banker buries with the heuristic bury (the ordinary pass's model;
   the ``vdsb`` second pass is not repeated here).

Measured (release 45's package smv3out-491ee4bf, Mac Mini, one thread, bots at
every seat, 200 seeded deals; `scripts/measure_declare_wait.py`): per wait pass
0.135 s mean, p90 0.25 s, max 0.43 s compiled; the pass ran at 324 chances and
chose to wait at 76 (69 of them holding a pair: 69 of 179 pair chances, 7 of
145 others); the standing declaration at the window's close differed from
release 45's in 7 of 200 deals.  Pure-engine figures are in the PR.  These are
the rule's behaviour, not playing strength; strength needs a screen.

Nothing here chooses, serves or registers anything, and nothing here consumes
any bot's RNG; the wiring, budget and record are
`pv_search_policy.PVSearchBot._declare_wait_decision`.
"""
from __future__ import annotations

import copy
import hashlib
import json
import random

from ..ai.heuristic import HeuristicBot
from ..engine.legal import IllegalPlay
from ..engine.round import HAND_SIZE
from . import value_declare as value_declare_model

#: the name token (declare-rule slot, after ``vdsb`` and ``vdpw``)
TOKEN = "vdw"
#: the outer worlds (the first of the ordinary pass's stream; the ordinary pass: 64)
WORLDS_DEFAULT = 32
#: the worlds of the decider's end-of-deal choice, per outer world and branch
INNER_WORLDS_DEFAULT = 8
#: the most draws the outer worlds may take from the stream (`silence_consistent`)
DRAWS_CAP = 8 * WORLDS_DEFAULT
#: the model the recipe digest binds (module docstring)
MODEL = ("silence-consistent-worlds|deal-continuation|heuristic-other-seats|"
         "silent-until-deal-end|end-choice-own-view-value|no-grace-response")
SCHEMA = "pv-value-declare-wait-v1"
#: the policy every other seat declares by (stateless)
_HEURISTIC = HeuristicBot()


def continuation_round(rnd, seat: int, hands, kitty):
    """A copy of ``rnd`` at the same deal position whose undealt cards are the
    sampled world's: each seat holds the dealt prefix of its world hand (the
    world lists every hand in deal order: the decider's own cards and a
    declarer's pinned cards first), the deck deals the rest round-robin as the
    engine does (card ``i`` to seat ``i % 4``).  ``rnd`` is never mutated."""
    sim = copy.copy(rnd)
    dealt = [len(h) for h in rnd.hands]
    sim.hands = [list(hands[s][:dealt[s]]) for s in range(4)]
    if sim.hands[seat] != list(rnd.hands[seat]):
        raise value_declare_model.ValueDeclareError("the world does not extend the seat's hand")
    sim.deck = [hands[i % 4][i // 4] for i in range(4 * HAND_SIZE)] + list(kitty)
    sim.kitty = list(kitty)
    sim.declaration = (None if rnd.declaration is None
                       else {**rnd.declaration, "cards": list(rnd.declaration["cards"])})
    sim.passed = set()
    sim.message = None
    sim.notice = None
    return sim


def play_out_deal(sim, seat: int) -> int:
    """Deal the rest of ``sim`` in place; after each card dealt to a seat
    other than ``seat`` that seat declares by the heuristic (``final=False``).
    Returns how many declarations were made."""
    made = 0
    while sim.phase == "deal":
        receiver, _, _ = sim.deal_next()
        if receiver == seat:
            continue
        choice = _HEURISTIC.decide_declare(sim, receiver, final=False)
        if choice:
            try:
                sim.declare(receiver, choice)
                made += 1
            except IllegalPlay:
                pass
    return made


def silence_consistent(sim, seat: int) -> bool:
    """The current-standing heuristic consistency check on the world ``sim``
    (from `continuation_round`, before any card is dealt): no other seat would
    declare now, against the CURRENT standing declaration, by the heuristic
    opponent model.  Not a likelihood of the seats' past silence: when the
    standing declaration was strengthened after a seat's last chance, that
    seat's options shrank, so a world in which it would have declared then can
    still pass (module docstring, approximation 3)."""
    return all(_HEURISTIC.decide_declare(sim, other, final=False) is None
               for other in range(4) if other != seat)


def inner_rng(seed, rnd, seat: int, world: int) -> random.Random:
    """The stream of outer world ``world``'s end-of-deal choices (both
    branches): a function of the bot seed, the decider's view at the chance
    and the world index, never of any bot's own RNG."""
    declaration = rnd.declaration
    material = json.dumps([SCHEMA, int(seed or 0), int(seat), int(world),
                           sorted(rnd.hands[seat]), sum(len(h) for h in rnd.hands),
                           None if declaration is None else
                           [declaration["seat"], sorted(declaration["cards"])]],
                          separators=(",", ":"))
    return random.Random(int.from_bytes(hashlib.sha256(material.encode()).digest()[:8], "big"))


def end_candidates(sim, seat: int) -> list:
    """``[(key, option)]``: the decider's distinct end-of-deal outcomes, PASS
    (keep what stands) first, then its legal options in engine order."""
    return value_declare_model.candidate_outcomes(sim, seat, sim.declare_options(seat), None)


__all__ = ["TOKEN", "WORLDS_DEFAULT", "INNER_WORLDS_DEFAULT", "DRAWS_CAP", "MODEL", "SCHEMA",
           "continuation_round", "play_out_deal", "silence_consistent", "inner_rng",
           "end_candidates"]
