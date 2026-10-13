"""Bounded whole-hand admission hypothesis, not a strength test.

XMTJ's real eight-card late lead is a refused throw: this deliberately tests
that admission is NOT permission to play all eight cards successfully.
"""
import copy
import asyncio
import json
import random
import time
import tomllib
from pathlib import Path

import numpy as np
import pytest

from shengji.rl.replay_log import rebuild_round
from shengji.harvest.legal import resolve_lead
from shengji.train import pv_search_policy as pv
from test_pv_admission_rules import predict, ZeroEvaluator
from test_pv_search_serving import package  # noqa: F401
from test_encoder_round_compat import pinned_production_package, PACKAGE_SHA  # noqa: F401


def root():
    events = json.loads((Path(__file__).parent / 'fixtures/xmtj_round1.json').read_text())
    rnd = rebuild_round(events)
    for event in (e for e in events if e['e'] == 'play'):
        if not rnd.trick.plays and len(rnd.hands[rnd.turn]) == 8:
            return rnd
        rnd.play(event['seat'], event['attempted'])
    raise AssertionError('fixture root missing')


def bot(on, **kw):
    return pv.PVSearchBot(predict, evaluator=ZeroEvaluator(), version=2,
                         config=pv.PVSearchConfig(checkpoint_sha256='f' * 64,
                             worlds=2, candidates=8, cap=4000,
                             finish_lead_admission=on, **kw), checkpoint='/dev/null', seed=7)


def test_admission_adds_only_finish_preserves_ballot_and_never_duplicates():
    rnd = root()
    off, on = bot(False), bot(True)
    anchor = [rnd.hands[rnd.turn][0]]
    actions = off._legal(rnd, rnd.turn, [anchor]).actions
    finish = next(i for i, a in enumerate(actions) if sorted(a) == sorted(rnd.hands[rnd.turn]))
    preferences = -np.arange(len(actions), dtype=float)
    anchor_index = actions.index(anchor)
    a = off._admission(rnd, rnd.turn, actions, preferences, anchor_index, [])
    b = on._admission(rnd, rnd.turn, actions, preferences, anchor_index, [])
    assert finish not in a and b == a + [finish]
    assert on._admission_record()['finish_lead_admission_added']
    preferences[finish] = 1e9
    b = on._admission(rnd, rnd.turn, actions, preferences, anchor_index, [])
    assert len(b) == len(set(b)) == 8 and finish in b
    assert not on._admission_record()['finish_lead_admission_added']
    preferences[finish] = -np.inf  # do not restore a masked exploration action
    assert finish not in on._admission(rnd, rnd.turn, actions, preferences, anchor_index, [])


@pytest.mark.parametrize('world_count', [2, 64])
def test_real_search_consumer_prices_one_extra_and_resolves_refused_finish(monkeypatch, world_count):
    rnd = root()
    accepted, notice = resolve_lead(rnd, rnd.turn, rnd.hands[rnd.turn])
    assert notice and accepted == ['DA']
    records = []
    for on in (False, True):
        policy = bot(on, doomed_throw_reselect=True)
        worlds = [(copy.deepcopy(rnd.hands), list(rnd.buried)) for _ in range(world_count)]
        monkeypatch.setattr(policy, '_worlds', lambda *a: (worlds, world_count))
        monkeypatch.setattr(policy, 'scores',
                            lambda r, s, actions, w: np.tile(-np.arange(len(actions)), (len(w), 1)))
        played = policy.decide_play(copy.deepcopy(rnd), rnd.turn)
        record = policy.last_decision_record
        assert record['work_complete']
        assert sorted(played) != sorted(rnd.hands[rnd.turn])  # not a must-play
        records.append(record)
    assert records[1]['admitted'][:-1] == records[0]['admitted']
    assert sorted(records[1]['admitted'][-1]) == sorted(rnd.hands[rnd.turn])
    assert records[1]['value_evaluations'] == records[0]['value_evaluations'] + world_count
    # Even an artificially maximal score cannot bypass served doomed-throw
    # re-selection: this full-hand action is forced to DA in every world.
    actions = records[1]['admitted']
    values = np.zeros(len(actions))
    values[-1] = 100
    winner = policy._select(rnd, rnd.turn, actions, values, worlds)
    assert winner != len(actions) - 1


def test_added_safe_finish_reaches_terminal_leaf_and_can_win_normal_selection(monkeypatch):
    from shengji.engine.round import Trick
    rnd = root()
    # Synthetic late state with an unbeatable six-card club tractor. This is
    # an engine/consumer witness, not a naturally observed production mistake.
    seat = rnd.turn
    rnd.hands[seat] = ['CQ', 'CQ', 'CK', 'CK', 'CA', 'CA']
    others = [['C3', 'C3', 'C4', 'C4', 'C5', 'C5'],
              ['C6', 'C6', 'C7', 'C7', 'C8', 'C8'],
              ['C9', 'C9', 'C10', 'C10', 'CJ', 'CJ']]
    for s, hand in zip([s for s in range(4) if s != seat], others):
        rnd.hands[s] = hand
    rnd.trick = Trick(leader=seat)
    assert resolve_lead(rnd, seat, rnd.hands[seat])[1] is None

    class TerminalEvaluator:
        def score(self, leaves, seat):
            return np.array([float(leaf.phase == 'round_end') for leaf in leaves])

    choices = []
    for on in (False, True):
        policy = bot(on)
        policy.evaluator = TerminalEvaluator()
        worlds = [(copy.deepcopy(rnd.hands), list(rnd.buried)) for _ in range(2)]
        monkeypatch.setattr(policy, '_worlds', lambda *a: (worlds, 2))
        # Intentionally rank large plays last to isolate admission from value.
        monkeypatch.setattr(policy, 'scores', lambda r, s, actions, w:
                            np.tile([-len(a) for a in actions], (len(w), 1)))
        choices.append(policy._search(copy.deepcopy(rnd), seat, ['CQ'], time.perf_counter()))
        assert policy.last_decision_record['work_complete']
    assert len(choices[0]) < 6
    assert sorted(choices[1]) == sorted(rnd.hands[seat])


def test_scope_and_capped_candidate_pool():
    rnd = root()
    policy = bot(True)
    policy.cap = 1
    actions = policy._legal(rnd, rnd.turn, [[rnd.hands[rnd.turn][0]]]).actions
    assert sorted(rnd.hands[rnd.turn]) in [sorted(a) for a in actions]
    following = copy.deepcopy(rnd)
    following.play(following.turn, [following.hands[following.turn][0]])
    assert policy._finish_lead_action(following, following.turn) is None
    # Scope predicates only: no engine or model call on these modified hands.
    for hand in (['DA'], ['DA'] * 9, ['DA', 'C3']):
        changed = copy.deepcopy(rnd)
        changed.hands[changed.turn] = hand
        assert policy._finish_lead_action(changed, changed.turn) is None


def test_env_factory_identity_and_budget_fallback(package):
    path, sha = package
    env = dict(SHENGJI_PV_CKPT=path, SHENGJI_PV_SHA256=sha,
               SHENGJI_PV_FINISH_LEAD_ADMISSION='1', SHENGJI_PV_WORLDS='2',
               SHENGJI_PV_SERVING_BUDGET_SECONDS='0.000000001')
    entries = pv.pv_registry_entries(**pv.pv_env_recipe(env))
    name, = entries
    assert '-fla-' in name
    policy = entries[name](seed=7)
    assert policy.finish_lead_admission
    rnd = root()
    before = policy.sampler.rng.getstate()
    played = policy.decide_play(rnd, rnd.turn)
    assert played and not policy.last_decision_record['work_complete']
    assert policy.last_decision_record['reason'] == 'budget'
    assert policy.sampler.rng.getstate() == before
    false = pv.PVSearchConfig(checkpoint_sha256=sha)
    assert 'finish_lead_admission' not in pv.recipe_payload(false)
    with pytest.raises(pv.PVSearchPolicyError):
        pv.pv_env_recipe({**env, 'SHENGJI_PV_FINISH_LEAD_ADMISSION': 'yes'})


@pytest.mark.parametrize('expired', [False, True])
def test_tiny_recipe_candidate_survives_server_snapshot_and_commit(package, tmp_path, expired):
    _check_recipe_candidate_snapshot_and_commit(package, tmp_path, expired)


@pytest.mark.parametrize('expired', [False, True])
def test_current_recipe_candidate_survives_server_snapshot_and_commit(pinned_production_package, tmp_path, expired):
    # Do not depend on the Torch-exported tiny fixture: the required production
    # package gate deliberately runs without Torch and must execute both cases.
    _check_recipe_candidate_snapshot_and_commit(
        (str(pinned_production_package), PACKAGE_SHA), tmp_path, expired)


def _check_recipe_candidate_snapshot_and_commit(decision_package, tmp_path, expired):
    """Current serving flags/W64/bury wrapper and actual API consumer.

    Tiny and hash-pinned production packages; not a strength comparison or
    production-host latency measurement. CI's required package gate cannot skip.
    """
    from shengji.api import server as srv
    from shengji.engine.game import Game

    path, sha = decision_package
    env = tomllib.loads((Path(__file__).parents[2] / 'fly.toml').read_text())['env']
    recipe = pv.pv_env_recipe({**env, 'SHENGJI_PV_CKPT': path,
                              'SHENGJI_PV_SHA256': sha,
                              'SHENGJI_PV_FINISH_LEAD_ADMISSION': '1'})
    if expired:
        recipe['serving_budget_seconds'] = 1e-9
    entries = pv.pv_registry_entries(**recipe)
    name, = entries

    async def scenario():
        rnd = root()
        policy = entries[name](seed=17)
        direct = entries[name](seed=17)
        expected = direct.decide_play(copy.deepcopy(rnd), rnd.turn)
        accepted, _ = resolve_lead(rnd, rnd.turn, expected)
        game = Game(random.Random(7))
        game.round = rnd
        room = srv.Room(code='FINISH', game=game, bot=policy,
                        seats=[srv.Seat(str(s), is_bot=True) for s in range(4)], log_dir=tmp_path)
        room.ids = [dict(enumerate(hand)) for hand in rnd.hands]
        room._kitty_given = True
        events = []
        room.log_event = lambda kind, **data: events.append((kind, data))
        seat = rnd.turn
        before = policy.sampler.rng.getstate()
        hand_before = list(rnd.hands[seat])
        prepared = await srv._paced_bot_step(room, seat, minimum_turn_seconds=0)
        assert prepared is not None and room.bot is policy
        assert policy.sampler.rng.getstate() == before and rnd.hands[seat] == hand_before
        copied = prepared.decision.snapshot.bot_copy
        assert copied is not policy and copied.finish_lead_admission
        assert isinstance(copied, pv.PVSearchBuryBot)
        record = copied.last_decision_record
        assert record['work_complete'] == (not expired)
        if expired:
            assert record['reason'] == 'budget' and copied.sampler.rng.getstate() == before
        else:
            assert sorted(hand_before) in [sorted(a) for a in record['admitted']]
            assert record['worlds'] == 64
            assert 'finish_lead_admission_added' in record
        assert list(prepared.decision.cards) == expected
        assert any(kind == 'model_search' for kind, _ in events)
        assert srv._commit_bot_turn(room, prepared)
        assert room.bot is copied and room.bot.finish_lead_admission
        assert len(rnd.hands[seat]) == len(hand_before) - len(accepted)
        assert not srv._commit_bot_turn(room, prepared)  # no duplicate commit

    asyncio.run(scenario())
