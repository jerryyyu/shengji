"""Bounded whole-hand admission hypothesis, not a strength test.

XMTJ's real eight-card late lead is a refused throw: this deliberately tests
that admission is NOT permission to play all eight cards successfully.
"""
import copy
import json
import time
from pathlib import Path

import numpy as np
import pytest

from shengji.rl.replay_log import rebuild_round
from shengji.harvest.legal import resolve_lead
from shengji.train import pv_search_policy as pv
from test_pv_admission_rules import predict, ZeroEvaluator
from test_pv_search_serving import package  # noqa: F401


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
