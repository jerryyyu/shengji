"""DEV exact-follow reranking keeps the normal ballot atomic."""

import random
import copy
import time
import asyncio
import json
import os
import subprocess
import sys
import tomllib
from dataclasses import replace
from pathlib import Path
import numpy as np

import pytest

from shengji.ai.endgame import exhaustive_legal_actions
from shengji.engine.cards import Ordering
from shengji.engine.round import Round, Trick, TrickPlay
from shengji.train.pv_exact_follow import (ExactFollowRefusal, rerank_follow,
                                           rerank_follow_prefix)
from shengji.train import pv_search_policy as pv
from test_pv_admission_rules import predict, ZeroEvaluator
from test_endgame import _round
from test_encoder_round_compat import pinned_production_package  # noqa: F401
from test_pv_search_serving import _play_state
from test_release46_fly_config import without_combo
from shengji.ai.heuristic import HeuristicBot
from shengji.api import server as srv
from shengji.engine.game import Game


class FollowDevBot(pv.PVSearchBuryBot):
    """Keep the reference-solver diagnostic fixture's small node limit."""
    def __init__(self, *args, config, **kwargs):
        super().__init__(*args, config=replace(config, exact_follow=True,
                                               exact_follow_max_nodes=10000), **kwargs)


@pytest.mark.parametrize('hand_cap', [3, 4])
def test_pinned_model_follow_snapshot_and_commit(pinned_production_package, tmp_path, hand_cap):
    # the release-45 base (production's fly.toml without release 46's twelve combo lines):
    # the baseline bot runs no exact stage and the dev bot sets its own
    env = without_combo(tomllib.loads((Path(__file__).resolve().parents[2] / 'fly.toml')
                                      .read_text())['env'])
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


def follow_env(path, exact_cards=6):
    # the release-45 base with the exact stages set here, so the follow stage is the only
    # rule under test
    env = without_combo(tomllib.loads((Path(__file__).resolve().parents[2] / 'fly.toml')
                                      .read_text())['env'])
    env.update(SHENGJI_PV_CKPT=str(path), SHENGJI_PV_EXACT_LEAD_ENDGAME='1',
               SHENGJI_PV_EXACT_DEEP_CARDS=str(exact_cards), SHENGJI_PV_EXACT_FOLLOW='1',
               SHENGJI_PV_EXACT_FOLLOW_SOLVER='compact-level',
               SHENGJI_PV_EXACT_FOLLOW_MAX_CARDS=str(exact_cards),
               SHENGJI_PV_EXACT_FOLLOW_MAX_NODES='50000000')
    return env


@pytest.mark.parametrize('hand_cap,node_cap,cancel_partial,exact_cards', [
    (3, 50_000_000, False, 6), (6, 50_000_000, False, 6),
    (6, 1, False, 6), (3, 50_000_000, True, 6),
    (7, 50_000_000, False, 7),
])
def test_registry_follow_reaches_server_snapshot_and_commit(
        pinned_production_package, tmp_path, monkeypatch, hand_cap, node_cap,
        cancel_partial, exact_cards):
    sessions = []
    if cancel_partial:
        from shengji.train import pv_exact_follow
        from shengji.ai.endgame_compact import CompactWorldSession, default_backend
        clock = [0.0]
        monkeypatch.setattr(pv.time, 'perf_counter', lambda: clock[0])

        class ExpireAfterOneCandidate(CompactWorldSession):
            def __init__(self, *args, check_budget, **kwargs):
                self.completed = 0
                def guard():
                    if self.completed:
                        clock[0] = 4.0  # real 3-second serving deadline, not a solver refusal
                    check_budget()
                super().__init__(*args, check_budget=guard, **kwargs)
                sessions.append(self)

            def solve_level(self, *args, **kwargs):
                result = super().solve_level(*args, **kwargs)
                self.completed += 1
                return result

        monkeypatch.setattr(pv_exact_follow, 'CompactWorldSession', ExpireAfterOneCandidate)
    env = follow_env(pinned_production_package, exact_cards)
    env['SHENGJI_PV_EXACT_FOLLOW_MAX_NODES'] = str(node_cap)
    recipe = pv.pv_env_recipe(env)
    entries = pv.pv_registry_entries(**recipe)
    name, factory = next(iter(entries.items()))
    bot = factory(seed=7)
    assert bot.policy_name == name and bot.config.exact_follow
    assert bot.exact_follow_solver == 'compact-level'
    assert bot.exact_follow_max_cards == bot.exact_deep_cards == exact_cards
    assert f'-ed{exact_cards}' in name and f'-xf{exact_cards}' in name
    assert bot.exact_follow_max_nodes == node_cap
    assert bot.worlds == 64 and bot.candidates == 8 and bot.serving_budget_seconds == 3
    rnd, heuristic = _play_state(), HeuristicBot()
    while not (rnd.trick.plays and max(map(len, rnd.hands)) <= hand_cap):
        rnd.play(rnd.turn, heuristic.decide_play(rnd, rnd.turn))
    baseline_recipe = dict(recipe, exact_follow=False)
    baseline = pv.make_pv_search_bot(**baseline_recipe, seed=7)
    expected = baseline.decide_play(copy.deepcopy(rnd), rnd.turn)
    assert baseline.last_decision_record['work_complete']

    async def scenario():
        game = Game(random.Random(7))
        game.round = rnd
        room = srv.Room(code='EFFACTORY', game=game, bot=bot,
            seats=[srv.Seat(str(i), is_bot=True) for i in range(4)], log_dir=tmp_path)
        room.ids = [dict(enumerate(hand)) for hand in rnd.hands]
        room._kitty_given = True
        room.log_event = lambda *args, **kwargs: None
        seat, hands, rng = rnd.turn, copy.deepcopy(rnd.hands), bot.sampler.rng.getstate()
        prepared = await srv._paced_bot_step(room, seat, minimum_turn_seconds=0)
        assert prepared is not None
        assert rnd.hands == hands and bot.sampler.rng.getstate() == rng
        copied = prepared.decision.snapshot.bot_copy
        assert copied.policy_name == name and copied.exact_follow_solver == 'compact-level'
        record = copied.last_decision_record
        assert record['work_complete'] and record['exact_follow_attempted']
        if cancel_partial or node_cap == 1 or record['exact_follow_abandoned'] is not None:
            if node_cap == 1:
                assert record['exact_follow_abandoned'] == 'error'
                assert record['exact_follow_error'] == 'ExactFollowRefusal'
            elif cancel_partial:
                assert len(sessions) == 1 and sessions[0].completed == 1
                assert sessions[0].nodes > 0
                assert sessions[0].backend == default_backend()
                assert record['exact_follow_abandoned'] == 'hard_budget'
                assert record['exact_follow_error'] == 'PVSearchBudgetExceeded'
                assert 'exact_follow_worlds' not in record
            else:
                # Slower hosts may exhaust the real serving deadline.  That
                # must preserve the baseline, never publish partial means.
                assert hand_cap in (6, 7)
                assert record['exact_follow_abandoned'] in ('soft_budget', 'hard_budget')
            assert not record['exact_follow_applied']
            assert 'exact_follow_scores' not in record
            assert list(prepared.decision.cards) == expected
            for key in ('admitted', 'selected_index', 'value_means', 'played',
                        'value_evaluations', 'value_batches'):
                assert record[key] == baseline.last_decision_record[key]
        else:
            assert record['exact_follow_abandoned'] is None
            assert record['exact_follow_worlds'] == 64
        from shengji.train.search_screen import trace_fields, exact_follow_summary
        persisted = trace_fields(record)
        for key in ('exact_follow_attempted', 'exact_follow_abandoned',
                    'exact_follow_applied', 'exact_follow_worlds', 'exact_follow_scores',
                    'exact_follow_error'):
            if key in record:
                assert persisted[key] == record[key]
        summary = exact_follow_summary([{'decision_traces': [
            {'side': 'arm', 'decisions': [persisted]},
            {'side': 'baseline', 'decisions': [trace_fields(baseline.last_decision_record)]}]}])
        assert summary['valid']
        counts = summary['sides']['arm']
        assert counts['attempted'] == 1 and counts['missing'] == 0
        reason = record['exact_follow_abandoned']
        outcome = ('complete' if reason is None else
                   'refusal' if record.get('exact_follow_error') == 'ExactFollowRefusal'
                   else reason)
        assert counts[outcome] == 1
        assert counts['applied'] == int(record['exact_follow_applied'])
        assert summary['sides']['baseline']['missing'] == 1
        assert summary['sides']['baseline']['attempted'] == 0
        assert srv._commit_bot_turn(room, prepared)
        assert not srv._commit_bot_turn(room, prepared)
        assert len(rnd.hands[seat]) == len(hands[seat]) - len(prepared.decision.cards)

    asyncio.run(scenario())


@pytest.mark.parametrize('key,value', [('EXACT_FOLLOW', 'yes'),
    ('EXACT_FOLLOW_MAX_CARDS', '9'), ('EXACT_FOLLOW_MAX_CARDS', '2.5'),
    ('EXACT_FOLLOW_MAX_NODES', '0'), ('EXACT_FOLLOW_SOLVER', 'other')])
def test_follow_env_rejects_invalid_parameters(key, value):
    env = follow_env('/unused')
    env['SHENGJI_PV_' + key] = value
    with pytest.raises(pv.PVSearchPolicyError):
        recipe = pv.pv_env_recipe(env)
        pv.pv_registry_entries(**recipe)


@pytest.mark.parametrize('key,value', [('EXACT_FOLLOW_MAX_CARDS', '6'),
    ('EXACT_FOLLOW_MAX_NODES', '100'), ('EXACT_FOLLOW_SOLVER', 'compact-level')])
def test_follow_parameters_require_enabled_rule(key, value):
    env = follow_env('/unused')
    for name in list(env):
        if name.startswith('SHENGJI_PV_EXACT_FOLLOW'):
            del env[name]
    env['SHENGJI_PV_' + key] = value
    with pytest.raises(pv.PVSearchPolicyError):
        pv.pv_env_recipe(env)


def test_follow_solver_contract_matches_lazy_implementation():
    from shengji.train import pv_exact_follow

    assert pv._EXACT_FOLLOW_SOLVERS == pv_exact_follow.SOLVERS


def test_follow_off_recipe_does_not_import_optional_solver(pinned_production_package):
    # the release-45 base: production's fly.toml without release 46's twelve combo lines
    fly_env = without_combo(tomllib.loads(
        (Path(__file__).resolve().parents[2] / 'fly.toml').read_text())['env'])
    source = """
import json
import sys
from shengji.train import pv_search_policy as pv
env = json.loads(sys.argv[1])
env['SHENGJI_PV_CKPT'] = sys.argv[2]
env['SHENGJI_PV_SHA256'] = sys.argv[3]
recipe = pv.pv_env_recipe(env)
assert not recipe.get('exact_follow', False)
name, factory = next(iter(pv.pv_registry_entries(**recipe).items()))
bot = factory(seed=7)
assert bot.policy_name == name
assert 'shengji.train.pv_exact_follow' not in sys.modules
assert 'shengji.ai._endgame_fast' not in sys.modules
"""
    env = dict(os.environ)
    env['PYTHONPATH'] = str(Path(__file__).resolve().parents[1])
    result = subprocess.run(
        [sys.executable, '-P', '-B', '-c', source, json.dumps(fly_env),
         str(pinned_production_package),
         '491ee4bf81abe783d14f1e004d31ceda1ff2679bd2e14b60a5a9fa96b57c2670'],
        cwd=Path(__file__).resolve().parents[1], env=env,
        capture_output=True, text=True)
    assert result.returncode == 0, result.stderr[-2000:]


def test_follow_identity_off_preserved_and_parameters_distinct():
    config = pv.PVSearchConfig(checkpoint_sha256='f' * 64)
    base = pv.pv_policy_name('ffffffff', config)
    assert pv.pv_policy_name('ffffffff', replace(config, exact_follow=False)) == base
    on = replace(config, exact_follow=True)
    variants = [on, replace(on, exact_follow_max_cards=6),
                replace(on, exact_follow_solver='compact-level'),
                replace(on, exact_follow_max_nodes=50_000_000)]
    names = {pv.pv_policy_name('ffffffff', c) for c in variants}
    assert len(names) == len(variants) and base not in names


def test_follow_prefix_recipe_is_opt_in_and_bounded():
    base = pv.PVSearchConfig(checkpoint_sha256='f' * 64)
    assert 'exact_follow_prefix_min_worlds' not in pv.recipe_payload(base)
    enabled = replace(base, exact_follow=True, exact_follow_max_cards=8,
                      worlds=4, exact_follow_prefix_min_worlds=2)
    assert pv.recipe_payload(enabled)['exact_follow_prefix_min_worlds'] == 2
    assert '-xfp2' in pv.pv_policy_name('ffffffff', enabled)
    for invalid in (
            replace(base, exact_follow_prefix_min_worlds=1),
            replace(base, exact_follow=True, exact_follow_prefix_min_worlds=1),
            replace(base, exact_follow=True, exact_follow_max_cards=8, worlds=1,
                    exact_follow_prefix_min_worlds=2)):
        with pytest.raises(pv.PVSearchPolicyError):
            pv.recipe_payload(invalid)


def test_pinned_model_singleton_follow_does_not_solve(pinned_production_package, monkeypatch):
    from shengji.train import pv_exact_follow
    env = follow_env(pinned_production_package)
    recipe = pv.pv_env_recipe(env)
    rnd, heuristic = _play_state(), HeuristicBot()
    while not (rnd.trick.plays and max(map(len, rnd.hands)) <= 3):
        rnd.play(rnd.turn, heuristic.decide_play(rnd, rnd.turn))
    rnd.play(rnd.turn, heuristic.decide_play(rnd, rnd.turn))
    def forbidden(*args, **kwargs):
        pytest.fail('a singleton ballot cannot benefit from exact reranking')
    monkeypatch.setattr(pv_exact_follow, 'rerank_follow', forbidden)
    bot = pv.make_pv_search_bot(**recipe, seed=7)
    assert bot.decide_play(copy.deepcopy(rnd), rnd.turn) == ['D5']
    assert bot.last_decision_record['work_complete']
    assert not bot.last_decision_record.get('exact_follow_attempted', False)
    assert bot.last_decision_record['admitted'] == [['D5']]


def test_registry_ineligible_follow_does_not_enter_exact_stage(
        pinned_production_package, monkeypatch):
    from shengji.train import pv_exact_follow
    recipe = pv.pv_env_recipe(follow_env(pinned_production_package))
    _, factory = next(iter(pv.pv_registry_entries(**recipe).items()))
    bot = factory(seed=7)
    rnd, heuristic = _play_state(), HeuristicBot()
    while not (rnd.trick.plays and max(map(len, rnd.hands)) <= 7):
        rnd.play(rnd.turn, heuristic.decide_play(rnd, rnd.turn))
    assert max(map(len, rnd.hands)) > bot.exact_follow_max_cards
    baseline = pv.make_pv_search_bot(**dict(recipe, exact_follow=False), seed=7)
    expected = baseline.decide_play(copy.deepcopy(rnd), rnd.turn)

    def forbidden(*args, **kwargs):
        pytest.fail('ineligible follow must not enter the exact solver')

    monkeypatch.setattr(pv_exact_follow, 'rerank_follow', forbidden)
    assert bot.decide_play(copy.deepcopy(rnd), rnd.turn) == expected
    record = bot.last_decision_record
    assert record['work_complete'] and len(record['admitted']) > 1
    assert not any(k.startswith('exact_follow_') for k in record)
    for key in ('admitted', 'selected_index', 'value_means', 'played',
                'value_evaluations', 'value_batches'):
        assert record[key] == baseline.last_decision_record[key]


def disagreement():
    return _round([["C5", "C10"], ["S8", "D3", "HJ"],
                   ["HA", "H4", "CK"], ["D2", "SJ", "SK"]],
                  plays=[(0, ["C5"])], attacker_points=35)


def search_case(deadline=None, on=True, max_nodes=10000, preferred='D3'):
    """Real enumeration/admission/search/engine, with a controlled value head.

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
        np.asarray([1.0 if a == [preferred] else 0.0 for a in actions]), 1)
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


@pytest.mark.parametrize('preferred', ['D3', 'HJ'])
def test_exact_follow_publication_checks_deadline_even_if_action_unchanged(monkeypatch, preferred):
    from shengji.train import pv_exact_follow
    _, baseline = search_case(on=False, preferred=preferred)
    original = pv_exact_follow.rerank_follow
    expired = False
    results = []

    def finish_then_expire(*args, **kwargs):
        nonlocal expired
        result = original(*args, **kwargs)
        results.append((result.winner, kwargs['baseline_index']))
        expired = True
        return result

    def check():
        if expired:
            raise pv.PVSearchBudgetExceeded('expired before exact publication')

    monkeypatch.setattr(pv_exact_follow, 'rerank_follow', finish_then_expire)
    bot, actual = search_case(deadline=check, preferred=preferred)
    assert len(results) == 1
    assert (results[0][0] == results[0][1]) == (preferred == 'HJ')
    assert actual == baseline
    record = bot.last_decision_record
    assert record['exact_follow_abandoned'] == 'hard_budget'
    assert record['exact_follow_error'] == 'PVSearchBudgetExceeded'
    assert not record['exact_follow_applied']
    assert 'exact_follow_scores' not in record
    assert 'exact_follow_worlds' not in record


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


def test_compact_follow_grouping_preserves_candidate_scores(monkeypatch):
    from shengji.ai.endgame_compact import HAVE_FAST, CompactWorldSession
    from shengji.train import pv_exact_follow
    if not HAVE_FAST:
        pytest.skip("compiled exact backend is not built")
    rnd = _follow_round()
    rnd.hands[1] = ["C8", "C9"]
    rnd.hands[2] = ["C6", "C7"]
    rnd.hands[3] = ["D8", "D9"]
    rnd.deck = [c for hand in rnd.hands for c in hand]
    legal = exhaustive_legal_actions(rnd, 1)
    worlds = [([list(hand) for hand in rnd.hands], [])]
    real = CompactWorldSession
    probe = real(rnd, backend="compiled", level=True, max_nodes=10_000)
    assert len({probe.play_key(rnd, action) for action in legal}) < len(legal)
    clones = []
    real_root_clone = pv_exact_follow.root_clone
    grouped_solves = []

    def tracked_root_clone(*args, **kwargs):
        clones.append(True)
        return real_root_clone(*args, **kwargs)

    class GroupedSession(real):
        def solve_level(self, *args, **kwargs):
            grouped_solves.append(True)
            return super().solve_level(*args, **kwargs)

    monkeypatch.setattr(pv_exact_follow, "root_clone", tracked_root_clone)
    monkeypatch.setattr(
        pv_exact_follow, "CompactWorldSession",
        lambda *args, **kwargs: GroupedSession(*args, backend="compiled", **kwargs))
    grouped = rerank_follow(rnd, 1, legal, worlds, max_nodes=10_000,
                            solver="compact-level")
    assert len(clones) == len(legal) + 1
    assert len(grouped_solves) == 1

    ungrouped_solves = []

    class UngroupedSession(real):
        def play_key(self, rnd, cards):
            return None

        def solve_level(self, *args, **kwargs):
            ungrouped_solves.append(True)
            return super().solve_level(*args, **kwargs)

    monkeypatch.setattr(
        pv_exact_follow, "CompactWorldSession",
        lambda *args, **kwargs: UngroupedSession(*args, backend="compiled", **kwargs))
    ungrouped = rerank_follow(rnd, 1, legal, worlds, max_nodes=10_000,
                              solver="compact-level")
    assert grouped.winner == ungrouped.winner
    assert grouped.scores == ungrouped.scores
    assert len(ungrouped_solves) == 2


def test_group_reuse_does_not_bypass_engine_validation(monkeypatch):
    from shengji.ai.endgame_compact import CompactWorldSession
    from shengji.engine.legal import IllegalPlay
    from shengji.train import pv_exact_follow

    class SameKeySession(CompactWorldSession):
        def play_key(self, rnd, cards):
            return 1

    monkeypatch.setattr(pv_exact_follow, 'CompactWorldSession', SameKeySession)
    rnd = _follow_round()
    hands = copy.deepcopy(rnd.hands)
    with pytest.raises(IllegalPlay):
        rerank_follow(rnd, 1, [['C4'], ['SA']], [(hands, [])],
                      max_nodes=10_000, solver='compact-level')
    assert rnd.hands == hands


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


def _prefix_fixture():
    rnd = _follow_round()
    rnd.hands = [[f"C{i}" for i in range(3, 11)],
                 [f"D{i}" for i in range(3, 11)],
                 [f"S{i}" for i in range(3, 11)],
                 [f"H{i}" for i in range(3, 11)]]
    rnd.deck = [card for hand in rnd.hands for card in hand]
    return rnd


def test_prefix_registry_preserves_explicit_opt_in(pinned_production_package):
    recipe = pv.pv_env_recipe(follow_env(pinned_production_package, 8))
    default_entries = pv.pv_registry_entries(**recipe)
    default_bot = next(iter(default_entries.values()))(seed=7)
    assert default_bot.exact_follow_prefix_min_worlds == 0
    entries = pv.pv_registry_entries(**recipe, exact_follow_prefix_min_worlds=1)
    name, factory = next(iter(entries.items()))
    assert name not in default_entries
    assert '-xfp1' in name
    bot = factory(seed=7)
    assert bot.exact_follow_prefix_min_worlds == 1
    assert copy.deepcopy(bot).exact_follow_prefix_min_worlds == 1
    with pytest.raises(pv.PVSearchPolicyError):
        pv.pv_registry_entries(**recipe, exact_follow_prefix_min_worlds=True)


@pytest.mark.parametrize('hard_expiry', [False, True])
def test_prefix_server_snapshot_commit(pinned_production_package, tmp_path,
                                       monkeypatch, hard_expiry):
    from shengji.train import pv_exact_follow
    from shengji.train.search_screen import trace_fields, exact_follow_summary

    recipe = pv.pv_env_recipe(follow_env(pinned_production_package, 8))
    entries = pv.pv_registry_entries(**recipe, exact_follow_prefix_min_worlds=1)
    name, factory = next(iter(entries.items()))
    bot = factory(seed=7)
    rnd, heuristic = _play_state(), HeuristicBot()
    while not (rnd.trick.plays and max(map(len, rnd.hands)) == 8):
        assert rnd.phase == 'play'
        action = (heuristic.decide_play(rnd, rnd.turn) if rnd.trick.plays
                  else [rnd.hands[rnd.turn][0]])
        rnd.play(rnd.turn, action)
    clock, calls = [0.0], [0]
    monkeypatch.setattr(pv.time, 'perf_counter', lambda: clock[0])

    def scores(*args):
        args[6]()
        calls[0] += 1
        clock[0] = 4.0 if hard_expiry else 2.5
        return [0.0] * len(args[2]), 1

    monkeypatch.setattr(pv_exact_follow, '_world_scores', scores)

    async def scenario():
        game = Game(random.Random(7))
        game.round = rnd
        room = srv.Room(code='PREFIX', game=game, bot=bot,
                        seats=[srv.Seat(str(i), is_bot=True) for i in range(4)],
                        log_dir=tmp_path)
        room.ids = [dict(enumerate(hand)) for hand in rnd.hands]
        room._kitty_given = True
        room.log_event = lambda *args, **kwargs: None
        seat, hands = rnd.turn, copy.deepcopy(rnd.hands)
        rng = bot.sampler.rng.getstate()
        prepared = await srv._paced_bot_step(room, seat, minimum_turn_seconds=0)
        assert prepared is not None
        assert rnd.hands == hands and bot.sampler.rng.getstate() == rng
        copied = prepared.decision.snapshot.bot_copy
        assert copied.policy_name == name and copied.exact_follow_prefix_min_worlds == 1
        record = copied.last_decision_record
        assert record['exact_follow_prefix'] is True
        assert calls[0] == 1
        summary = exact_follow_summary([{'decision_traces': [
            {'side': 'arm', 'decisions': [trace_fields(record)]}]}])
        assert summary['valid']
        if hard_expiry:
            assert record['exact_follow_abandoned'] == 'hard_budget'
            assert not record['exact_follow_applied']
            assert 'exact_follow_scores' not in record
            assert summary['sides']['arm']['hard_budget'] == 1
        else:
            assert record['exact_follow_completed_worlds'] == 1
            assert summary['sides']['arm']['prefix_complete'] == 1
        assert srv._commit_bot_turn(room, prepared)
        assert not srv._commit_bot_turn(room, prepared)
        assert len(rnd.hands[seat]) == len(hands[seat]) - len(prepared.decision.cards)

    asyncio.run(scenario())


def test_prefix_real_eight_card_solver_matches_full_world_and_stops(monkeypatch):
    from shengji.train import pv_exact_follow as module
    hands = [[suit + rank for rank in ('3', '4', '5', '6') for _ in range(2)]
             for suit in ('C', 'D', 'S', 'H')]
    lead = hands[0]
    hands[0] = []
    rnd = _round(hands, plays=[(0, lead)])
    admitted = [list(hands[1])]
    worlds = [(copy.deepcopy(hands), [])] * 2
    config = dict(max_hand_cards=8, max_nodes=10_000, solver='compact-level',
                  baseline_index=0)
    expected = rerank_follow(rnd, 1, admitted, worlds[:1], **config)
    original = module._world_scores
    clock = [0.0]
    completed = [0]
    hard_checks = [0]
    def hard_check():
        hard_checks[0] += 1
    def real_world(*args):
        result = original(*args)
        completed[0] += 1
        clock[0] = 1.0
        return result
    monkeypatch.setattr(module, '_world_scores', real_world)
    result = rerank_follow_prefix(rnd, 1, admitted, worlds, min_worlds=1,
                                  soft_deadline=0.5, clock=lambda: clock[0],
                                  check_budget=hard_check, **config)
    assert result == expected
    assert result.winner == 0
    assert completed == [1] and hard_checks[0] > 3
    assert rnd.hands == hands and rnd.turn == 1


def test_prefix_soft_stop_discards_in_world_totals(monkeypatch):
    from shengji.train import pv_exact_follow

    rnd = _prefix_fixture()
    worlds = [(rnd.hands, []) for _ in range(2)]
    calls = 0
    clock_values = iter((0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0))

    def fake_world_scores(*args):
        nonlocal calls
        calls += 1
        guard = args[6]
        if calls == 1:
            # Internal solver guards may be numerous; soft expiry remains
            # active for all of them, not just the candidate boundaries.
            for _ in range(5):
                guard()
            return [1.0, 3.0], 7
        # A later internal boundary soft-stops this world.  No row from this
        # in-flight world may reach the accumulated prefix.
        guard()
        guard()
        return [100.0, 300.0], 700

    monkeypatch.setattr(pv_exact_follow, '_world_scores', fake_world_scores)
    result = rerank_follow_prefix(
        rnd, 1, [['D3'], ['D4']], worlds, min_worlds=1,
        soft_deadline=0.5, clock=lambda: next(clock_values))
    assert result.worlds == 1
    assert result.scores == (1.0, 3.0)
    assert result.nodes == 7


def test_prefix_soft_shortfall_is_distinct_refusal(monkeypatch):
    from shengji.train import pv_exact_follow

    rnd = _prefix_fixture()
    worlds = [(rnd.hands, [])]

    def stop(*args):
        args[6]()
        pytest.fail('soft stop should have raised before a world completed')

    monkeypatch.setattr(pv_exact_follow, '_world_scores', stop)
    from shengji.train.pv_exact_follow import ExactFollowPrefixShortfall
    with pytest.raises(ExactFollowPrefixShortfall, match='completed 0 worlds'):
        rerank_follow_prefix(
            rnd, 1, [['D3'], ['D4']], worlds, min_worlds=1,
            soft_deadline=0.0, clock=lambda: 1.0)


def test_prefix_hard_expiry_after_minimum_never_publishes(monkeypatch):
    from shengji.train import pv_exact_follow

    rnd = _prefix_fixture()
    worlds = [(rnd.hands, []) for _ in range(2)]
    checks = 0

    def hard_check():
        nonlocal checks
        checks += 1
        if checks > 1:
            raise pv.PVSearchBudgetExceeded('hard expiry')

    def fake_world_scores(*args):
        args[6]()
        return [1.0, 3.0], 7

    monkeypatch.setattr(pv_exact_follow, '_world_scores', fake_world_scores)
    with pytest.raises(pv.PVSearchBudgetExceeded, match='hard expiry'):
        rerank_follow_prefix(
            rnd, 1, [['D3'], ['D4']], worlds, min_worlds=1,
            check_budget=hard_check)


def test_prefix_solver_refusal_after_minimum_is_not_a_soft_stop(monkeypatch):
    from shengji.train import pv_exact_follow
    rnd = _prefix_fixture()
    calls = [0]
    def solve(*args):
        calls[0] += 1
        if calls[0] == 2:
            raise ExactFollowRefusal('node limit')
        return [0.0, 1.0], 2
    monkeypatch.setattr(pv_exact_follow, '_world_scores', solve)
    with pytest.raises(ExactFollowRefusal, match='node limit'):
        rerank_follow_prefix(rnd, 1, [['D3'], ['D4']], [(rnd.hands, [])] * 2,
                             min_worlds=1)


@pytest.mark.parametrize('mode', ['full', 'soft', 'short', 'hard', 'seven'])
def test_prefix_bot_consumer_routes_only_eight_card_root(monkeypatch, mode):
    from shengji.train import pv_exact_follow

    rnd = _prefix_fixture()
    if mode == 'seven':
        rnd.hands = [hand[:7] for hand in rnd.hands]
    worlds = [(rnd.hands, []) for _ in range(2)]
    config = pv.PVSearchConfig(
        checkpoint_sha256='f' * 64, worlds=2, candidates=2,
        exact_follow=True, exact_follow_max_cards=8,
        exact_follow_prefix_min_worlds=2 if mode == 'short' else 1,
        serving_budget_seconds=3)
    bot = pv.PVSearchBot(
        predict, evaluator=ZeroEvaluator(), version=2, config=config,
        checkpoint='/dev/null', seed=7)
    bot._worlds = lambda *args: (worlds, len(worlds))
    bot.scores = lambda *args: np.zeros((2, len(args[2])))
    bot._value_means = lambda *args: (np.zeros(len(args[2])), 1)
    bot._admission = lambda _r, _s, _a, _p, anchor_index, _w, _c: [
        anchor_index, next(i for i in range(len(_a)) if i != anchor_index)]

    clock = [0.0]
    calls = [0]
    monkeypatch.setattr(pv.time, 'perf_counter', lambda: clock[0])

    def fake_world_scores(*args):
        calls[0] += 1
        if calls[0] == 2 and mode in ('soft', 'short', 'hard'):
            clock[0] = 4.0 if mode == 'hard' else 2.5
        if args[6] is not None:
            args[6]()
        return [0.0, 1.0], 2

    monkeypatch.setattr(pv_exact_follow, '_world_scores', fake_world_scores)
    def hard_check():
        if clock[0] >= 3:
            raise pv.PVSearchBudgetExceeded('hard serving deadline')
    played = bot._search(rnd, 1, ['D3'], time.perf_counter(), check_budget=hard_check)
    record = bot.last_decision_record
    from shengji.train.search_screen import trace_fields, exact_follow_summary
    summary = exact_follow_summary([{'decision_traces': [
        {'side': 'arm', 'decisions': [trace_fields(record)]}]}])
    assert summary['valid']
    if mode in ('short', 'hard'):
        assert played == ['D3']
        assert not record['exact_follow_applied']
        assert 'exact_follow_scores' not in record
        assert 'exact_follow_completed_worlds' not in record
        assert record['exact_follow_abandoned'] == ('hard_budget' if mode == 'hard' else 'error')
        assert record['exact_follow_error'] == ('PVSearchBudgetExceeded' if mode == 'hard'
                                                else 'ExactFollowPrefixShortfall')
        assert summary['sides']['arm']['hard_budget' if mode == 'hard' else 'soft_budget'] == 1
        assert summary['sides']['arm']['refusal'] == 0
        assert summary['sides']['arm']['prefix_complete'] == 0
        return
    assert played == record['admitted'][1]
    if mode == 'seven':
        assert 'exact_follow_prefix' not in record
        assert record['exact_follow_worlds'] == 2
        assert summary['sides']['arm']['complete'] == 1
        return
    assert record['exact_follow_prefix'] is True
    assert record['exact_follow_prefix_min_worlds'] == 1
    assert record['exact_follow_requested_worlds'] == 2
    assert record['exact_follow_completed_worlds'] == (1 if mode == 'soft' else 2)
    assert summary['sides']['arm']['prefix_complete'] == 1
    assert summary['sides']['arm']['complete'] == 0
