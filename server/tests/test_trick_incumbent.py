"""Regression gates for the trusted-rollout incremental trick caches.

``Trick.incumbent`` and ``Trick.running_points`` are maintained by
``Round.play`` ONLY inside the private append-only MC rollout contract
(``rnd._trusted_rollout``).  Live, public, hand-built, deepcopied and
counterfactual rounds must always take the legacy recomputation, so the
public-mutable-state witnesses from the PR #90 review cannot go stale.
"""

from __future__ import annotations

import copy
import random

import pytest

from shengji.ai.registry import make_bot
from shengji.engine.cards import Ordering, points
from shengji.engine.combos import decompose
from shengji.engine.game import Game
from shengji.engine.legal import beats, uniform_suit
from shengji.engine.round import Round, Trick, TrickPlay


def _legacy_current_winner(rnd):
    lead = rnd.trick.plays[0].cards
    suit = uniform_suit(lead, rnd.ordering)
    top = decompose(lead, rnd.ordering).top_level()
    winner = rnd.trick.plays[0].seat
    for tp in rnd.trick.plays[1:]:
        won, t = beats(tp.cards, lead, suit, top, rnd.ordering)
        if won:
            winner, top = tp.seat, t
            suit = rnd.ordering.eff_suit(tp.cards[0])
    return winner, suit, top


def _play_round(seed, trusted):
    game = Game(random.Random(seed))
    actors = [make_bot("smart") for _ in range(4)]
    rnd = game.start_round()
    while rnd.phase == "deal":
        s, _, _ = rnd.deal_next()
        c = actors[s].decide_declare(rnd, s)
        if c:
            rnd.declare(s, c)
    for s in range(4):
        c = actors[s].decide_declare(rnd, s, final=True)
        if c:
            rnd.declare(s, c)
    rnd.finalize_declare()
    rnd.bury(rnd.banker, list(actors[rnd.banker].decide_bury(rnd, rnd.banker)))
    if trusted:
        rnd._trusted_rollout = True
    return rnd, actors


def test_trusted_rollout_cache_matches_legacy_at_every_follow_state():
    checked = 0
    for seed in (1201, 1202, 1203, 1204, 1205):
        rnd, actors = _play_round(seed, trusted=True)
        while rnd.phase == "play":
            s = rnd.turn
            if s is None:
                break
            if rnd.trick is not None and rnd.trick.plays:
                assert rnd.trick.incumbent is not None
                assert rnd.trick.incumbent == _legacy_current_winner(rnd)
                assert rnd.trick.running_points == sum(
                    points(c) for tp in rnd.trick.plays for c in tp.cards)
                checked += 1
            rnd.play(s, actors[s].decide_play(rnd, s))
    assert checked > 100


def test_live_rounds_never_populate_the_cache():
    rnd, actors = _play_round(1201, trusted=False)
    saw_follow = False
    while rnd.phase == "play":
        s = rnd.turn
        if s is None:
            break
        if rnd.trick is not None and rnd.trick.plays:
            assert rnd.trick.incumbent is None
            assert rnd.trick.running_points is None
            saw_follow = True
        rnd.play(s, actors[s].decide_play(rnd, s))
    assert saw_follow


def test_same_length_replacement_after_deepcopy_cannot_go_stale():
    # Codex witness 1/2: a played round is deepcopied and a played card list
    # is replaced at the same length.  Live rounds carry no cache, so both
    # the winner and the points must reflect the mutation.
    rnd, actors = _play_round(1201, trusted=False)
    while rnd.phase == "play":
        s = rnd.turn
        if rnd.trick is not None and len(rnd.trick.plays) == 2:
            break
        rnd.play(s, actors[s].decide_play(rnd, s))
    clone = copy.deepcopy(rnd)
    bot = make_bot("smart")
    before = bot._current_winner(clone)
    # Deterministic teeth: replace the LEAD with same-length cards of a
    # different plain suit drawn from the full deck, which must change the
    # incumbent suit under legacy recomputation.  A stale cache would keep
    # returning ``before``.
    lead = clone.trick.plays[0].cards
    old_suit = clone.ordering.eff_suit(lead[0])
    new_suit = next(x for x in "SHDC"
                    if x != old_suit and x != clone.ordering.trump_suit)
    pool = [c for c in clone.deck
            if clone.ordering.eff_suit(c) == new_suit]
    seen: list[str] = []
    picked: list[str] = []
    for c in pool:
        if seen.count(c) < clone.deck.count(c) and len(picked) < len(lead):
            picked.append(c)
            seen.append(c)
    assert len(picked) == len(lead)
    clone.trick.plays[0].cards[:] = sorted(picked)
    after = bot._current_winner(clone)
    assert after == _legacy_current_winner(clone)
    assert after[1] in (new_suit, "T")
    assert after != before or before[1] == "T"


def test_changed_ordering_on_a_played_trick_recomputes():
    rnd, actors = _play_round(1202, trusted=False)
    while rnd.phase == "play":
        s = rnd.turn
        if rnd.trick is not None and len(rnd.trick.plays) == 2:
            break
        rnd.play(s, actors[s].decide_play(rnd, s))
    bot = make_bot("smart")
    suits = ["S", "H", "D", "C", None]
    other = next(x for x in suits if x != rnd.ordering.trump_suit)
    rnd.ordering = Ordering(other, rnd.trump_rank)
    assert bot._current_winner(rnd) == _legacy_current_winner(rnd)


def test_resolution_points_follow_a_mutated_live_trick():
    rnd, actors = _play_round(1203, trusted=False)
    while rnd.phase == "play":
        s = rnd.turn
        if rnd.trick is not None and len(rnd.trick.plays) == 3:
            break
        rnd.play(s, actors[s].decide_play(rnd, s))
    # mutate an already-played card list on the live round, then resolve
    plays = rnd.trick.plays
    non_point = [c for c in plays[1].cards if points(c) == 0]
    tens = [c for c in rnd.deck if c[1:] == "10"]
    if non_point and tens:
        plays[1].cards[plays[1].cards.index(non_point[0])] = tens[0]
    expected = sum(points(c) for tp in plays for c in tp.cards)
    s = rnd.turn
    played = make_bot("smart").decide_play(rnd, s)
    expected += sum(points(c) for c in played)
    rnd.play(s, played)
    assert rnd.last_trick.points == expected


def test_partial_trick_rollout_clone_starts_none_and_stays_consistent():
    # Mirrors MCBot._rollout: a mid-trick clone rebuilds Trick by hand, so
    # its cache starts None even under the trusted flag, and must stay None
    # (correct fallback) for the remainder of that trick.
    rnd, actors = _play_round(1204, trusted=False)
    while rnd.phase == "play":
        s = rnd.turn
        if rnd.trick is not None and len(rnd.trick.plays) == 2:
            break
        rnd.play(s, actors[s].decide_play(rnd, s))
    clone = copy.copy(rnd)
    clone.hands = [list(h) for h in rnd.hands]
    clone.trick = Trick(leader=rnd.trick.leader,
                        plays=[TrickPlay(p.seat, list(p.cards))
                               for p in rnd.trick.plays])
    clone.history = list(rnd.history)
    clone._trusted_rollout = True
    assert clone.trick.incumbent is None
    bot = make_bot("smart")
    assert bot._current_winner(clone) == _legacy_current_winner(clone)
    s = clone.turn
    clone.play(s, bot.decide_play(clone, s))
    if clone.trick is not None and clone.trick.plays:
        assert clone.trick.incumbent is None  # mid-trick clone: stays legacy
        assert bot._current_winner(clone) == _legacy_current_winner(clone)


def test_exact_endgame_disabled_never_calls_the_solver():
    bot = make_bot("mc", seed=0)
    assert bot.EXACT_ENDGAME is False

    def boom(*a, **k):
        raise AssertionError("solver consulted while disabled")

    bot._exact_endgame_value = boom
    rnd, actors = _play_round(1205, trusted=False)
    while rnd.phase == "play":
        s = rnd.turn
        if s == rnd.banker:
            rnd.play(s, bot.decide_play(rnd, s))
            break
        rnd.play(s, actors[s].decide_play(rnd, s))
    assert bot.rollouts > 0
