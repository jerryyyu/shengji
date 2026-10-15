"""DEV exact-follow reranking keeps the normal ballot atomic."""

import random

import pytest

from shengji.ai.endgame import exhaustive_legal_actions
from shengji.engine.cards import Ordering
from shengji.engine.round import Round, Trick, TrickPlay
from shengji.train.pv_exact_follow import ExactFollowRefusal, rerank_follow


def _follow_round():
    rnd = Round("7", banker=0, rng=random.Random(0))
    rnd.phase = "play"
    rnd.ordering = Ordering("H", "7")
    rnd.trump_suit = "H"
    rnd.hands = [["C3"], ["C4", "C5"], ["C6", "C7"], ["C8", "C9"]]
    rnd.buried = []
    rnd.trick = Trick(leader=0, plays=[TrickPlay(0, ["C3"])])
    rnd.turn = 1
    rnd.deck = [c for hand in rnd.hands for c in hand]
    return rnd


def test_actual_follow_rerank_is_complete_and_legal():
    rnd = _follow_round()
    legal = exhaustive_legal_actions(rnd, 1)
    result = rerank_follow(rnd, 1, legal, [( [list(h) for h in rnd.hands], [])],
                           max_nodes=10_000)
    assert 0 <= result.winner < len(legal)
    assert tuple(legal[result.winner]) in {tuple(action) for action in legal}
    assert result.worlds == 1 and result.nodes > 0
    assert rnd.hands[1] == ["C4", "C5"]


def test_follow_refuses_leads_and_node_caps_without_partial_result():
    rnd = _follow_round()
    with pytest.raises(ExactFollowRefusal, match="follow root"):
        lead = Round("7", banker=0, rng=random.Random(0))
        lead.phase, lead.ordering = "play", rnd.ordering
        rerank_follow(lead, 0, [["C3"]], [([ ["C3"]] * 4, [])])
    with pytest.raises(ExactFollowRefusal):
        rerank_follow(rnd, 1, exhaustive_legal_actions(rnd, 1),
                      [([list(h) for h in rnd.hands], [])], max_nodes=1)


def test_budget_callback_cancels_before_exact_result():
    rnd = _follow_round()
    def cancel():
        raise RuntimeError("cancel")
    with pytest.raises(RuntimeError, match="cancel"):
        rerank_follow(rnd, 1, exhaustive_legal_actions(rnd, 1),
                      [([list(h) for h in rnd.hands], [])], check_budget=cancel)
