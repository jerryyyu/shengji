"""DEV exact-follow reranking keeps the normal ballot atomic."""

import random
import copy
import time
import numpy as np

import pytest

from shengji.ai.endgame import exhaustive_legal_actions
from shengji.engine.cards import Ordering
from shengji.engine.round import Round, Trick, TrickPlay
from shengji.train.pv_exact_follow import ExactFollowRefusal, rerank_follow
from shengji.train import pv_search_policy as pv
from test_pv_admission_rules import predict, ZeroEvaluator
from test_endgame import _round


def disagreement():
    return _round([["C5", "C10"], ["S8", "D3", "HJ"],
                   ["HA", "H4", "CK"], ["D2", "SJ", "SK"]],
                  plays=[(0, ["C5"])], attacker_points=35)


def search_case(deadline=None, on=True, max_nodes=10000):
    """Real enumeration/admission/search/engine, with a deliberately wrong head.

    This isolates the mechanism; it is not a measured production-model mistake.
    """
    rnd = disagreement()
    policy = pv.PVSearchBot(predict, evaluator=ZeroEvaluator(), version=2,
        config=pv.PVSearchConfig(checkpoint_sha256='f' * 64, worlds=2,
            candidates=8, cap=4000, exact_follow=on,
            exact_follow_max_nodes=max_nodes), checkpoint='/dev/null', seed=7)
    worlds = [(copy.deepcopy(rnd.hands), []) for _ in range(2)]
    policy._worlds = lambda *args: (worlds, 2)
    policy.scores = lambda r, s, actions, w: np.zeros((len(w), len(actions)))
    policy._value_means = lambda r, s, actions, w, check: (
        np.asarray([1.0 if a == ['D3'] else 0.0 for a in actions]), 1)
    before = copy.deepcopy(rnd.__dict__, {id(rnd.ordering): rnd.ordering})
    played = policy._search(rnd, 1, ['D3'], time.perf_counter(), deadline)
    assert rnd.__dict__ == before
    record = policy.last_decision_record
    assert record['admitted'][record['admitted_indices'].index(record['selected_index'])] == played
    rnd.play(1, played)
    assert rnd.trick.plays[-1].cards == played
    comparable = {k: v for k, v in record.items()
                  if not k.startswith('exact_follow_') and k != 'seconds'}
    return policy, (played, comparable)


def test_real_search_changes_wrong_ranking_without_changing_ballot():
    off, (base, base_record) = search_case(on=False)
    on, (changed, changed_record) = search_case()
    assert base == ['D3'] and changed == ['HJ']
    assert base_record['admitted'] == changed_record['admitted']
    record = on.last_decision_record
    values = dict(zip(map(tuple, record['admitted']), record['exact_follow_scores']))
    assert values[('HJ',)] > values[('D3',)]
    assert record['exact_follow_worlds'] == 2
    assert record['exact_follow_applied']


def test_incomplete_exact_search_preserves_finalized_baseline():
    _, base = search_case(on=False)
    policy, failed = search_case(max_nodes=1)
    assert failed == base
    assert policy.last_decision_record['exact_follow_abandoned'] == 'error'


def test_recipe_identity_and_own_hand_multiset():
    config = pv.PVSearchConfig(checkpoint_sha256='f' * 64)
    assert 'exact_follow' not in pv.recipe_payload(config)
    config = pv.PVSearchConfig(checkpoint_sha256='f' * 64, exact_follow=True)
    assert pv.recipe_payload(config)['exact_follow'] is True
    rnd = disagreement()
    hands = copy.deepcopy(rnd.hands)
    hands[1].reverse()
    actions = [['D3'], ['HJ']]
    result = rerank_follow(rnd, 1, actions, [(hands, [])])
    assert result.winner == 1
    hands[1][0] = 'C2'
    with pytest.raises(ExactFollowRefusal, match='acting hand'):
        rerank_follow(rnd, 1, actions, [(hands, [])])


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
