"""DEV exact-follow reranking keeps the normal ballot atomic."""

import random
import copy
import time
import asyncio
import tomllib
from dataclasses import replace
from pathlib import Path
import numpy as np

import pytest

from shengji.ai.endgame import exhaustive_legal_actions
from shengji.engine.cards import Ordering
from shengji.engine.round import Round, Trick, TrickPlay
from shengji.train.pv_exact_follow import ExactFollowRefusal, rerank_follow
from shengji.train import pv_search_policy as pv
from test_pv_admission_rules import predict, ZeroEvaluator
from test_endgame import _round
from test_encoder_round_compat import pinned_production_package  # noqa: F401
from test_pv_search_serving import _play_state
from shengji.ai.heuristic import HeuristicBot
from shengji.api import server as srv
from shengji.engine.game import Game


class FollowDevBot(pv.PVSearchBuryBot):
    """Use the existing diagnostic factory seam; no serving flag is exposed."""
    def __init__(self, *args, config, **kwargs):
        super().__init__(*args, config=replace(config, exact_follow=True,
                                               exact_follow_max_nodes=10000), **kwargs)


@pytest.mark.parametrize('hand_cap', [3, 4])
def test_pinned_model_follow_snapshot_and_commit(pinned_production_package, tmp_path, hand_cap):
    env = tomllib.loads((Path(__file__).resolve().parents[2] / 'fly.toml').read_text())['env']
    env['SHENGJI_PV_CKPT'] = str(pinned_production_package)
    recipe = pv.pv_env_recipe(env)
    rnd = _play_state()
    heuristic = HeuristicBot()
    while rnd.phase == 'play':
        if rnd.trick.plays and max(map(len, rnd.hands)) <= hand_cap:
            break
        rnd.play(rnd.turn, heuristic.decide_play(rnd, rnd.turn))
    assert rnd.phase == 'play'
    baseline = pv.make_pv_search_bot(**recipe, seed=7)
    expected = baseline.decide_play(copy.deepcopy(rnd), rnd.turn)
    assert baseline.last_decision_record['work_complete']
    bot = pv.make_pv_search_bot(**recipe, seed=7, bot_factory=FollowDevBot)
    bot.policy_name = 'pv-search-exact-follow-dev'

    async def scenario():
        game = Game(random.Random(7))
        game.round = rnd
        room = srv.Room(code='EFDEV', game=game, bot=bot,
            seats=[srv.Seat(str(i), is_bot=True) for i in range(4)], log_dir=tmp_path)
        room.ids = [dict(enumerate(hand)) for hand in rnd.hands]
        room._kitty_given = True
        room.log_event = lambda *args, **kwargs: None
        seat = rnd.turn
        before = list(rnd.hands[seat])
        rng = bot.sampler.rng.getstate()
        prepared = await srv._paced_bot_step(room, seat, minimum_turn_seconds=0)
        assert prepared is not None
        assert rnd.hands[seat] == before and bot.sampler.rng.getstate() == rng
        record = prepared.decision.snapshot.bot_copy.last_decision_record
        assert record['work_complete'] and record['exact_follow_attempted']
        assert list(prepared.decision.cards) == expected
        if hand_cap == 3:
            assert record['exact_follow_worlds'] == 64
            assert len(set(record['exact_follow_scores'])) == 1
            assert not record['exact_follow_applied']
        else:
            assert record['exact_follow_abandoned'] is not None
        assert srv._commit_bot_turn(room, prepared)
        assert len(rnd.hands[seat]) == len(before) - len(expected)

    asyncio.run(scenario())


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
