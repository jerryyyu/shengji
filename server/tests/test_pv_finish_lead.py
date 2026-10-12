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


def root(cards=8):
    events = json.loads((Path(__file__).parent / 'fixtures/xmtj_round1.json').read_text())
    rnd = rebuild_round(events)
    for event in (e for e in events if e['e'] == 'play'):
        if not rnd.trick.plays and len(rnd.hands[rnd.turn]) == cards:
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


@pytest.fixture(params=['tiny', 'production'])
def decision_package(request):
    if request.param == 'tiny':
        return request.getfixturevalue('package')
    return str(request.getfixturevalue('pinned_production_package')), PACKAGE_SHA


@pytest.mark.parametrize('expired', [False, True])
@pytest.mark.parametrize('candidate', ['finish', 'exact'])
def test_current_recipe_candidate_survives_server_snapshot_and_commit(decision_package, tmp_path, expired, candidate):
    """Current serving flags/W64/bury wrapper and actual API consumer.

    Tiny and hash-pinned production packages; not a strength comparison or
    production-host latency measurement. CI's required package gate cannot skip.
    """
    from shengji.api import server as srv
    from shengji.engine.game import Game

    path, sha = decision_package
    env = tomllib.loads((Path(__file__).parents[2] / 'fly.toml').read_text())['env']
    flag = 'SHENGJI_PV_FINISH_LEAD_ADMISSION' if candidate == 'finish' else 'SHENGJI_PV_EXACT_LEAD_ENDGAME'
    recipe = pv.pv_env_recipe({**env, 'SHENGJI_PV_CKPT': path,
                              'SHENGJI_PV_SHA256': sha,
                              flag: '1'})
    if expired:
        recipe['serving_budget_seconds'] = 1e-9
    entries = pv.pv_registry_entries(**recipe)
    name, = entries

    async def scenario():
        rnd = root(8 if candidate == 'finish' else 2)
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
        attr = 'finish_lead_admission' if candidate == 'finish' else 'exact_lead_endgame'
        assert copied is not policy and getattr(copied, attr)
        assert isinstance(copied, pv.PVSearchBuryBot)
        record = copied.last_decision_record
        assert record['work_complete'] == (not expired)
        if expired:
            assert record['reason'] == 'budget' and copied.sampler.rng.getstate() == before
        else:
            assert record['worlds'] == 64
            if candidate == 'finish':
                assert sorted(hand_before) in [sorted(a) for a in record['admitted']]
                assert 'finish_lead_admission_added' in record
            else:
                assert record['exact_lead_status'] == 'complete'
                assert record['exact_lead_worlds_completed'] == 64
        assert list(prepared.decision.cards) == expected
        assert any(kind == 'model_search' for kind, _ in events)
        assert srv._commit_bot_turn(room, prepared)
        assert room.bot is copied and getattr(room.bot, attr)
        assert len(rnd.hands[seat]) == len(hand_before) - len(accepted)
        assert not srv._commit_bot_turn(room, prepared)  # no duplicate commit

    asyncio.run(scenario())


def test_portable_qualification_preserves_partial_and_refuses_overwrite(tmp_path):
    import runpy
    module = runpy.run_path(str(Path(__file__).parents[1] / 'scripts/qualify_exact_lead.py'))
    main = module['main']
    calls = []
    async def incomplete(checkpoint, dest):
        calls.append(checkpoint)
        dest.write('{"passed":false}\n')
        dest.flush()
        return 1
    main.__globals__['qualify'] = incomplete
    out = tmp_path / 'qualification.jsonl'
    argv = ['--checkpoint', 'not-opened.npz', '--out', str(out)]
    assert main(argv) == 1
    assert json.loads(out.read_text()) == {'passed': False}
    with pytest.raises(FileExistsError):
        main(argv)
    assert len(calls) == 1


def test_exact_flag_identity_and_incompatible_recipes(package):
    path, sha = package
    env = dict(SHENGJI_PV_CKPT=path, SHENGJI_PV_SHA256=sha)
    off = pv.pv_registry_entries(**pv.pv_env_recipe(env))
    explicit_off = pv.pv_registry_entries(**pv.pv_env_recipe({**env, 'SHENGJI_PV_EXACT_LEAD_ENDGAME':'0'}))
    assert list(off) == list(explicit_off)
    assert 'exact_lead_endgame' not in pv.recipe_payload(pv.PVSearchConfig(checkpoint_sha256=sha))
    on = pv.pv_registry_entries(**pv.pv_env_recipe({**env, 'SHENGJI_PV_EXACT_LEAD_ENDGAME':'1'}))
    name, = on
    assert '-ele-' in name and on[name](seed=1).exact_lead_endgame
    with pytest.raises(pv.PVSearchPolicyError):
        pv.pv_env_recipe({**env, 'SHENGJI_PV_EXACT_LEAD_ENDGAME':'yes'})
    for other in ('adaptive_worlds', 'adaptive_worlds_leads', 'oracle_worlds'):
        with pytest.raises(pv.PVSearchPolicyError, match='excludes'):
            pv.recipe_payload(pv.PVSearchConfig(checkpoint_sha256=sha,
                                               exact_lead_endgame=True, **{other: True}))


def test_exact_failure_preserves_completed_base_and_selection_state(package, monkeypatch):
    from shengji.train import pv_exact_endgame as exact
    path, sha = package
    rnd = root(2)
    off = pv.make_pv_search_bot(path, sha256=sha, worlds=2, candidates=8, seed=17)
    on = pv.make_pv_search_bot(path, sha256=sha, worlds=2, candidates=8, seed=17,
                             exact_lead_endgame=True)
    expected = off.decide_play(copy.deepcopy(rnd), rnd.turn)
    def fail(*args, **kwargs):
        on._tiebreak = {'corrupted': True}
        raise RuntimeError('incomplete exact pass')
    monkeypatch.setattr(exact, 'exact_lead_means', fail)
    actual = on.decide_play(copy.deepcopy(rnd), rnd.turn)
    assert actual == expected and on.sampler.rng.getstate() == off.sampler.rng.getstate()
    assert on.last_decision_record['work_complete']
    assert on.last_decision_record['exact_lead_status'] == 'abandoned'
    assert on.last_decision_record['value_means'] == off.last_decision_record['value_means']
    assert on._tiebreak == off._tiebreak


def test_exact_soft_expiry_keeps_base_without_partial_values(monkeypatch):
    from shengji.train import pv_exact_endgame as exact
    rnd = root(2)
    policy = bot(False, exact_lead_endgame=True)
    clock = [0.0]
    monkeypatch.setattr(pv.time, 'perf_counter', lambda: clock[0])
    base = (np.array([-2.0]), 1, 0, [rnd.hands[rnd.turn][0]], 1)
    policy._tiebreak = {'base': True}
    def expire(rnd, seat, actions, worlds, leaf, check, **kwargs):
        policy._tiebreak = {'partial': True}
        clock[0] = 3.0
        check()
        raise AssertionError('expired exact pass continued')
    monkeypatch.setattr(exact, 'exact_lead_means', expire)
    result = policy._exact_lead_decision(rnd, rnd.turn, [base[3]],
        [(copy.deepcopy(rnd.hands), list(rnd.buried))], 0.0, None, [0.0], base)
    assert result is base
    assert policy._tiebreak == {'base': True}
    assert policy._exact_lead['exact_lead_abandon_reason'] == 'soft_budget'
    assert policy._exact_lead['exact_lead_worlds_completed'] is None
    assert 'exact_lead_selected_level_delta' not in policy._exact_lead


@pytest.mark.parametrize('delta,winner,override,kind', [
    (0.25, 1, False, 'higher'), (0.0, 1, False, 'tie'),
    (-0.25, 1, False, 'lower'), (0.25, 0, False, 'unchanged'),
    (0.25, 1, True, 'post_selection_override'),
])
def test_exact_change_classification_survives_wide_screen_trace(monkeypatch, delta, winner, override, kind):
    from shengji.train import pv_exact_endgame as exact
    from shengji.train.search_screen import TimedPolicy
    rnd = root(2)
    policy = bot(False, exact_lead_endgame=True)
    actions = [['C3'], ['C4']] + [['C5']] * 15
    means = np.array([1.0, 1.0 + delta] + [0.0] * 15)
    # Deliberately unrelated head predictions: delta must use exact means only.
    base = (np.array([100.0] * 17), 1, 0, actions[0], 1)
    monkeypatch.setattr(exact, 'exact_lead_means', lambda *a, **kw:
        (means, dict(worlds_completed=2, nodes=12, cache_hits=1)))
    monkeypatch.setattr(policy, '_select', lambda *a, **kw: winner)
    monkeypatch.setattr(policy, '_swap_doomed_throw', lambda *a, **kw:
        ['D3'] if override else actions[winner])
    result = policy._exact_lead_decision(rnd, rnd.turn, actions, [],
        time.perf_counter(), None, [0.0] * 17, base)
    policy.last_decision_record = {'schema': 'pv-search-decision-v1',
        'played': result[3], 'value_means': result[0].tolist(), **policy._exact_lead}
    monkeypatch.setattr(policy, 'decide_play', lambda *a: result[3])
    consumer = TimedPolicy(policy)
    assert consumer.decide_play(rnd, rnd.turn) == result[3]
    trace, = consumer.decisions
    assert 'value_means' not in trace and trace['value_means__len'] == 17
    assert trace['exact_lead_change_kind'] == kind
    assert trace['exact_lead_selected_level_mean'] == means[winner]
    assert trace['exact_lead_base_level_mean'] == 1.0
    assert trace['exact_lead_selected_level_delta'] == means[winner] - 1.0


def test_exact_corrects_captured_joker_lead_through_api(pinned_production_package, tmp_path, monkeypatch):
    """#700 captured root 94121012:0 / round7 / trick11 / seat3.

    Ordinary W64 sampler, restored refusal history and actual server commit.
    Fresh diagnostic seed, NOT original RNG replay. Disable wall-clock deadlines
    for deterministic correctness CI; real local budget witnesses live on #700.
    """
    from shengji.api import server as srv
    from shengji.engine.game import Game
    from shengji.train.lead_root_capture import restore_with_ledger
    from types import SimpleNamespace

    # Replace this module's clock reference, not global time used by asyncio.
    monkeypatch.setattr(pv, 'time', SimpleNamespace(perf_counter=lambda: 0.0))
    packet = json.loads((Path(__file__).parent / 'fixtures/r44_joker_lead.json').read_text())
    # Pin the captured release, not tomorrow's fly.toml.
    env = dict(SHENGJI_PV_WORLDS='64', SHENGJI_PV_CANDIDATES='8',
        SHENGJI_PV_CAP='4000', SHENGJI_PV_BATCH_SIZE='128',
        SHENGJI_PV_ADMISSION_DIVERSITY='1', SHENGJI_PV_REFUSAL_CONSTRAINTS='1',
        SHENGJI_PV_TIEBREAK_POINTS='1', SHENGJI_PV_LEAD_ANCHOR='1',
        SHENGJI_PV_DOOMED_THROW_RESELECT='1', SHENGJI_PV_VALUE_DECLARE='1',
        SHENGJI_PV_SERVING_BUDGET_SECONDS='3', SHENGJI_PV_BURY_ARM='hybrid',
        SHENGJI_PV_BURY_SERVING_BUDGET_SECONDS='2')

    async def scenario():
        records = []
        for enabled in (False, True):
            rnd, ledger = restore_with_ledger(packet)
            assert len(ledger.refusals) == 1 and rnd.turn == 3
            recipe = pv.pv_env_recipe({**env, 'SHENGJI_PV_CKPT': str(pinned_production_package),
                'SHENGJI_PV_SHA256': PACKAGE_SHA, 'SHENGJI_PV_EXACT_LEAD_ENDGAME': str(int(enabled))})
            entries = pv.pv_registry_entries(**recipe)
            name, = entries
            if not enabled:
                assert name == ('pv-search-491ee4bf-w64-k8-div-rc-tb-la-dtr-vd-'
                                'radd86676-bury-hybrid-6c1fb26b80e6')
            policy = entries[name](seed=941210121)
            policy._refusals = ledger
            game = Game(random.Random(7))
            game.round = rnd
            room = srv.Room(code='JOKER', game=game, bot=policy,
                seats=[srv.Seat(str(s), is_bot=True) for s in range(4)], log_dir=tmp_path)
            room.ids = [dict(enumerate(hand)) for hand in rnd.hands]
            room._kitty_given = True
            room.log_event = lambda *a, **kw: None
            before = copy.deepcopy(rnd.hands)
            prepared = await srv._paced_bot_step(room, 3, minimum_turn_seconds=0)
            assert prepared is not None and rnd.hands == before
            expected = ['BJ'] if enabled else ['BJ', 'S5', 'S8', 'SQ']
            assert list(prepared.decision.cards) == expected
            copied = prepared.decision.snapshot.bot_copy
            record = copied.last_decision_record
            assert record['work_complete'] and record['worlds'] == 64
            if enabled:
                assert record['exact_lead_status'] == 'complete'
                assert record['exact_lead_worlds_completed'] == 64
                assert record['value_means'][record['admitted'].index(['BJ'])] == 2.296875
                assert record['exact_lead_changed'] is True
                assert record['exact_lead_change_kind'] == 'higher'
                assert record['exact_lead_selected_level_delta'] == 0.328125
                assert record['admitted'][record['exact_lead_base_selected_index']] == ['BJ', 'S5', 'S8', 'SQ']
            assert srv._commit_bot_turn(room, prepared)
            assert room.bot is copied and not srv._commit_bot_turn(room, prepared)
            records.append((record, copied.sampler.rng.getstate()))
        assert records[0][0]['admitted'] == records[1][0]['admitted']
        assert records[0][0]['value_means'] == records[1][0]['exact_lead_base_value_means']
        assert records[0][1] == records[1][1]

    asyncio.run(scenario())
