import copy

import numpy as np
import pytest

from test_cwv_truncated_value import Evaluator, play, state
from shengji.harvest.legal import enumerate_legal
from shengji.train.cwv_bounded_puct import PuctConfig, search_worlds


def root():
    rnd = state()
    # Small real-engine late-game fixture, not a true-hidden production input.
    while len(rnd.hands[rnd.turn]) > 3:
        play(rnd)
    rnd._determinized_world = True
    rnd._trusted_rollout = True
    return rnd


def uniform(rnd, seat, actions):
    assert rnd._determinized_world and seat == rnd.turn
    return np.zeros(len(actions))


def test_balanced_batched_legal_and_private():
    rnd = root()
    before = copy.deepcopy(rnd)
    ev = Evaluator()
    out = search_worlds([rnd, copy.deepcopy(rnd), copy.deepcopy(rnd)], rnd.turn,
                        prior_logits=uniform, evaluator=ev,
                        config=PuctConfig(sweeps=5, depth=3, batch_size=2))
    assert out['world_visits'] == [5, 5, 5]
    assert sum(out['visits'].values()) == out['simulations'] == 15
    assert out['counts']['model_rows'] + out['counts']['terminal_rows'] == 15
    assert all(len(states) <= 2 for states, _ in ev.calls)
    assert tuple(out['action']) in enumerate_legal(rnd, rnd.turn, cap=None).keys()
    assert all(seats == [rnd.turn] * len(seats) for _, seats in ev.calls)
    assert rnd.hands == before.hands and rnd.history == before.history
    diagnostic = out['diagnostics']
    assert sum(diagnostic['depth_histogram'].values()) == 15
    assert max(diagnostic['depth_histogram']) <= 3
    assert all(0 < n <= 5 for n in diagnostic['root_visited_actions'])
    assert all(0 < mass <= 1.0000001 for mass in diagnostic['root_visited_prior_mass'])


def test_reject_live_world_and_bad_prior():
    rnd = root()
    rnd._determinized_world = False
    with pytest.raises(ValueError, match='determinized'):
        search_worlds([rnd], rnd.turn, prior_logits=uniform, evaluator=Evaluator())
    rnd._determinized_world = True
    with pytest.raises(ValueError, match='finite policy'):
        search_worlds([rnd], rnd.turn, prior_logits=lambda *a: [float('nan')], evaluator=Evaluator())


def test_gameplay_record_preserves_search_coverage(monkeypatch):
    """Exercise the adapter and real search, not just kernel diagnostics."""
    import json
    from collections import defaultdict
    from types import SimpleNamespace
    from shengji.train import cwv_bounded_puct as module
    rnd = root()
    bot = object.__new__(module.CWVBoundedPuctBot)
    bot.shortlist_config = SimpleNamespace(worlds=2)
    bot.puct_config = PuctConfig(sweeps=5, depth=3, batch_size=2)
    bot.root_warmup_top = 0
    bot.reuse_root_actions = False
    bot.compact_expansions = False
    bot.evaluator = Evaluator()
    bot.prior_config = SimpleNamespace(checkpoint_sha256='test-prior')
    bot.puct_totals = defaultdict(int)
    bot._tree_prior = uniform
    monkeypatch.setattr(module, 'sample_worlds',
                        lambda *args: ([(rnd.hands, rnd.buried)] * 2, 2))
    monkeypatch.setattr(module, 'root_clone', lambda *args: copy.deepcopy(rnd))
    action = bot.decide_play(rnd, rnd.turn)
    record = json.loads(json.dumps(bot.last_decision_record))['bounded_puct']
    d = record['diagnostics']
    assert sum(d['depth_histogram'].values()) == record['simulations'] == 10
    assert max(map(int, d['depth_histogram'])) <= 3
    assert len(d['root_legal_counts']) == len(d['root_visited_actions']) == 2
    assert len(d['root_visited_prior_mass']) == 2
    assert tuple(action) in enumerate_legal(rnd, rnd.turn, cap=None).keys()


def test_optional_profile_preserves_search_result():
    rnd = root()
    args = dict(prior_logits=uniform, config=PuctConfig(sweeps=8, depth=8))
    plain = search_worlds([rnd], rnd.turn, evaluator=Evaluator(), **args)
    profiled = search_worlds([rnd], rnd.turn, evaluator=Evaluator(), profile=True, **args)
    timings = profiled.pop('timings')
    assert plain == profiled
    assert all(np.isfinite(value) and value >= 0 for value in timings.values())
    assert timings['search_seconds'] > 0
    assert sum(value for key, value in timings.items() if key != 'search_seconds') == pytest.approx(
        timings['search_seconds'])


@pytest.mark.parametrize('sweeps,widening,power', [(1, 1., .5), (8, 2., .5), (16, 1.5, 1.)])
@pytest.mark.parametrize('reuse', [False, True])
@pytest.mark.parametrize('prior_mode', ['uniform', 'varying'])
def test_compact_expansions_exact_with_ties(sweeps, widening, power, reuse, prior_mode):
    rnd = root()
    worlds = [copy.deepcopy(rnd) for _ in range(3)]
    # Uniform priors exercise stable ties at the retained-prefix boundary.
    cfg = PuctConfig(sweeps=sweeps, depth=8, batch_size=2,
                     widening=widening, widening_power=power)
    prior = uniform if prior_mode == 'uniform' else lambda r,s,a: np.arange(len(a)) % 7
    kwargs = dict(prior_logits=prior, config=cfg, reuse_root_actions=reuse)
    reference = search_worlds(worlds, rnd.turn, evaluator=Evaluator(), **kwargs)
    compact = search_worlds(worlds, rnd.turn, evaluator=Evaluator(),
                            compact_expansions=True, **kwargs)
    storage = compact.pop('expansion_storage')
    assert compact == reference
    assert storage['retained_action_entries'] <= storage['exhaustive_action_entries']
    assert storage['retained_action_entries'] <= storage['reachable_width'] * compact['counts']['expanded_nodes']


def test_terminal_bypasses_model():
    rnd = root()
    while sum(map(len, rnd.hands)) > 1:
        play(rnd)
    class NoModel:
        def score_many(self, *args):
            raise AssertionError('terminal must bypass model')
    out = search_worlds([rnd], rnd.turn, prior_logits=uniform, evaluator=NoModel(),
                        config=PuctConfig(sweeps=3))
    assert out['counts']['terminal_rows'] == 3
    assert out['counts']['model_rows'] == 0


@pytest.mark.parametrize('flag', ['reuse_root_actions', 'compact_expansions'])
def test_bot_root_reuse_preserves_decision_and_reports_work(monkeypatch, flag):
    from shengji.train import cwv_bounded_puct as kernel
    from shengji.train import cwv_prior_admission as prior
    from shengji.train.cwv_shortlist import CWVShortlistConfig
    rnd = root()
    monkeypatch.setattr(prior, 'load_prior_checked', lambda *a: ('separate', None, None))
    monkeypatch.setattr(kernel, 'sample_worlds', lambda *a:
        ([(copy.deepcopy(rnd.hands), list(rnd.buried)) for _ in range(3)], 3))
    records, actions = [], []
    for enabled in (False, True):
        bot = kernel.CWVBoundedPuctBot(Evaluator(), seed=19,
            config=CWVShortlistConfig(worlds=3),
            prior=prior.CWVPriorAdmissionConfig(checkpoint='unused', checkpoint_sha256='0' * 64),
            puct_config=PuctConfig(sweeps=8, depth=4, batch_size=3),
            **{flag: enabled})
        monkeypatch.setattr(bot, '_tree_prior', uniform)
        actions.append(bot.decide_play(copy.deepcopy(rnd), rnd.turn))
        record = bot.last_decision_record['bounded_puct'].copy()
        if enabled:
            if flag == 'reuse_root_actions':
                assert record.pop('root_enumeration_reuse') == dict(hits=2, misses=1)
            else:
                storage = record.pop('expansion_storage')
                assert storage['retained_action_entries'] <= storage['exhaustive_action_entries']
        records.append(record)
    assert actions[0] == actions[1]
    assert records[0] == records[1]


@pytest.mark.parametrize('follow', [False, True])
def test_root_reuse_exact_search_and_world_specific_prior(monkeypatch, follow):
    from shengji.train import cwv_bounded_puct as kernel
    rnd = root()
    while bool(rnd.trick.plays) != follow:
        play(rnd)
    worlds = [copy.deepcopy(rnd) for _ in range(3)]
    # Preserve own hand/public legality but change hidden hands across worlds.
    others = [s for s in range(4) if s != rnd.turn]
    worlds[1].hands[others[0]], worlds[1].hands[others[1]] = (
        worlds[1].hands[others[1]], worlds[1].hands[others[0]])
    worlds[2].hands[rnd.turn].reverse()
    enumeration_calls, prior_calls = [], []
    original = kernel.enumerate_legal
    def counted(*args, **kwargs):
        enumeration_calls.append(1)
        return original(*args, **kwargs)
    def prior(world, seat, actions):
        signature = tuple(tuple(hand) for hand in world.hands)
        prior_calls.append((signature, tuple(actions)))
        offset = sum(ord(c) for card in world.hands[(seat + 1) % 4] for c in card)
        return np.array([(i + offset) % 7 for i in range(len(actions))], dtype=float)
    monkeypatch.setattr(kernel, 'enumerate_legal', counted)
    args = dict(prior_logits=prior, config=PuctConfig(sweeps=8, depth=8))
    reference = search_worlds(worlds, rnd.turn, evaluator=Evaluator(), **args)
    n_reference, calls_reference = len(enumeration_calls), list(prior_calls)
    enumeration_calls.clear()
    prior_calls.clear()
    optimized = search_worlds(worlds, rnd.turn, evaluator=Evaluator(),
                              reuse_root_actions=True, **args)
    assert optimized.pop('root_enumeration_reuse') == dict(hits=2, misses=1)
    assert optimized == reference
    assert prior_calls == calls_reference
    assert len(enumeration_calls) == n_reference - 2


def test_root_reuse_key_separates_legality_inputs():
    from shengji.train.cwv_bounded_puct import _root_legal_key
    rnd = root()
    key = _root_legal_key(rnd)
    for change in ('hand', 'suit', 'rank', 'turn', 'lead'):
        other = copy.deepcopy(rnd)
        if change == 'hand':
            other.hands[other.turn].pop()
        elif change == 'suit':
            other.ordering.trump_suit = 'different'
        elif change == 'rank':
            other.ordering.trump_rank = 'different'
        elif change == 'turn':
            other.turn = (other.turn + 1) % 4
        else:
            play(other)
        assert _root_legal_key(other) != key

def test_common_root_warmup_has_equal_world_evidence_and_explicit_work():
    from shengji.ai.cwv_puct import leaf_copy
    from shengji.train.cwv_truncated_value import continuation_values
    rnd = root()
    actions = enumerate_legal(rnd, rnd.turn, cap=None).actions[:2]
    worlds = [rnd, copy.deepcopy(rnd)]
    others = [s for s in range(4) if s != rnd.turn]
    worlds[1].hands[others[0]], worlds[1].hands[others[1]] = (
        worlds[1].hands[others[1]], worlds[1].hands[others[0]])
    class Fingerprint(Evaluator):
        def score_many(self, states, seats):
            super().score_many(states, seats)
            return [sum((s+1)*sum(ord(c) for card in hand for c in card)
                        for s, hand in enumerate(state.hands)) / 10000
                    for state in states]
    ev = Fingerprint()
    out = search_worlds(worlds, rnd.turn, prior_logits=uniform, evaluator=ev,
        config=PuctConfig(sweeps=3, depth=3, batch_size=1), root_warmup_actions=actions)
    warmup = out['common_root_warmup']
    assert warmup['simulations'] == 2 * len(actions)
    assert warmup['adaptive_simulations'] == 6
    assert out['simulations'] == sum(out['world_visits']) == 6 + 2 * len(actions)
    assert sum(out['visits'].values()) == out['simulations']
    assert sum(out['diagnostics']['depth_histogram'].values()) == out['simulations']
    assert out['counts']['model_rows'] + out['counts']['terminal_rows'] == out['simulations']
    for i, action in enumerate(actions):
        states = []
        for world in worlds:
            child = leaf_copy(world)
            child.play(child.turn, action)
            states.append(child)
        expected = continuation_values(states, [rnd.turn]*2, [len(rnd.history)]*2,
            evaluator=Fingerprint(), tricks=0, batch_size=1).values
        assert warmup['values_by_action_world'][i] == expected.tolist()
        assert warmup['means'][i] == float(expected.mean())
        assert out['visits'][tuple(sorted(action))] >= 2
    assert all(len(states) <= 1 for states, _ in ev.calls)


def test_common_root_warmup_refuses_duplicates_and_illegal_before_inference():
    rnd = root()
    action = enumerate_legal(rnd, rnd.turn, cap=None).actions[0]
    ev = Evaluator()
    for actions, message in (([action, action], 'distinct'),
                             ([['BJ']*3], 'legal in every world')):
        with pytest.raises(ValueError, match=message):
            search_worlds([rnd], rnd.turn, prior_logits=uniform, evaluator=ev,
                          root_warmup_actions=actions)
    assert not ev.calls


@pytest.mark.parametrize('warmup', ['explicit', 'prior'])
def test_compact_warmup_refused_before_prior_or_value(warmup):
    rnd = root()
    ev = Evaluator()
    def forbidden(*args):
        raise AssertionError('prior must not run')
    options = (dict(root_warmup_top=1) if warmup == 'prior' else
               dict(root_warmup_actions=enumerate_legal(rnd, rnd.turn, cap=None).actions[:1]))
    with pytest.raises(ValueError, match='cannot be combined'):
        search_worlds([rnd], rnd.turn, prior_logits=forbidden, evaluator=ev,
                      compact_expansions=True, **options)
    assert not ev.calls


def test_compact_warmup_bot_refuses_before_loading():
    from shengji.train.cwv_bounded_puct import CWVBoundedPuctBot
    with pytest.raises(ValueError, match='cannot be combined'):
        CWVBoundedPuctBot(Evaluator(), compact_expansions=True, root_warmup_top=1)


def test_root_enumeration_reuse_preserves_warmup_matrix_and_search():
    rnd = root()
    worlds = [rnd, copy.deepcopy(rnd)]
    options = dict(prior_logits=uniform, config=PuctConfig(sweeps=3, depth=3),
                   root_warmup_top=2)
    baseline = search_worlds(worlds, rnd.turn, evaluator=Evaluator(), **options)
    reused = search_worlds(worlds, rnd.turn, evaluator=Evaluator(),
                           reuse_root_actions=True, **options)
    assert reused.pop('root_enumeration_reuse') == dict(hits=1, misses=1)
    assert reused == baseline


def test_common_root_policy_proposals_preserve_low_prior_anchor():
    rnd = root()
    legal = enumerate_legal(rnd, rnd.turn, cap=None).actions
    keys = sorted(tuple(sorted(a)) for a in legal)
    anchor = keys[-1]
    def policy(world, seat, actions):
        return np.array([-10. if tuple(a) == anchor else 0. for a in actions])
    out = search_worlds([rnd, copy.deepcopy(rnd)], rnd.turn,
        prior_logits=policy, evaluator=Evaluator(), config=PuctConfig(sweeps=1),
        root_warmup_actions=[anchor], root_warmup_top=2)
    warmup = out['common_root_warmup']
    assert warmup['anchors'] == [list(anchor)]
    assert warmup['actions'] == [list(anchor), *[list(a) for a in keys[:-1][:2]]]
    assert warmup['policy_additions_actual'] == min(2, len(keys)-1)
    assert out['visits'][anchor] >= 2


def test_common_root_adapter_keeps_mc_candidates(monkeypatch):
    from shengji.train import cwv_prior_admission as prior_module
    from shengji.train.cwv_bounded_puct import CWVBoundedPuctBot
    from shengji.train.cwv_shortlist import CWVShortlistConfig
    from shengji.ai.mcbot import MCBot
    monkeypatch.setattr(prior_module, 'load_prior_checked', lambda *a: ('separate', None, None))
    monkeypatch.setattr(CWVBoundedPuctBot, '_tree_prior', staticmethod(uniform))
    bot = CWVBoundedPuctBot(Evaluator(), seed=37,
        config=CWVShortlistConfig(worlds=2),
        prior=prior_module.CWVPriorAdmissionConfig('unused', 'a'*64),
        puct_config=PuctConfig(sweeps=2), root_warmup_top=2)
    rnd = root()
    anchors = {tuple(sorted(a)) for a in MCBot._candidates(bot, rnd, rnd.turn)}
    bot.decide_play(rnd, rnd.turn)
    record = bot.last_decision_record['bounded_puct']
    warmup = record['common_root_warmup']
    assert {tuple(a) for a in warmup['anchors']} == anchors
    assert anchors <= {tuple(a) for a in warmup['actions']}
    assert record['simulations'] == warmup['simulations'] + 4


@pytest.mark.parametrize('kwargs', [dict(sweeps=0), dict(depth=0), dict(batch_size=0),
                                  dict(widening=0), dict(exploration=float('nan')),
                                  dict(widening_power=0)])
def test_config_refuses_invalid(kwargs):
    with pytest.raises(ValueError):
        PuctConfig(**kwargs)


def test_adapter_does_not_read_live_opponent_hands(monkeypatch):
    from shengji.train import cwv_prior_admission as prior_module
    from shengji.train.cwv_bounded_puct import CWVBoundedPuctBot
    from shengji.train.cwv_shortlist import CWVShortlistConfig
    monkeypatch.setattr(prior_module, 'load_prior_checked', lambda *a: ('separate', None, None))
    monkeypatch.setattr(CWVBoundedPuctBot, '_tree_prior', staticmethod(uniform))
    rnd = state()
    seat = rnd.turn
    changed = copy.deepcopy(rnd)
    others = [s for s in range(4) if s != seat]
    # Deal root, no revealed voids: permutation preserves observer information.
    changed.hands[others[0]], changed.hands[others[1]] = changed.hands[others[1]], changed.hands[others[0]]
    results, evaluators = [], []
    for live in (rnd, changed):
        ev = Evaluator()
        bot = CWVBoundedPuctBot(ev, seed=37,
              config=CWVShortlistConfig(worlds=2, selection_worlds=3, alternatives=2),
              prior=prior_module.CWVPriorAdmissionConfig('unused', 'a' * 64),
              puct_config=PuctConfig(sweeps=2, depth=2))
        action = bot.decide_play(live, seat)
        results.append((action, bot.last_decision_record['bounded_puct']))
        evaluators.append(ev)
    assert results[0] == results[1]
    for (states_a, seats_a), (states_b, seats_b) in zip(evaluators[0].calls, evaluators[1].calls, strict=True):
        assert seats_a == seats_b
        assert [r.hands for r in states_a] == [r.hands for r in states_b]


def test_screen_factory_trace_and_accounting(monkeypatch):
    from test_cwv_shortlist_screen import cfg
    from shengji.train import cwv_shortlist_screen as screen
    from shengji.train import cwv_prior_admission as prior_module
    from shengji.train.cwv_bounded_puct import CWVBoundedPuctBot
    ev = Evaluator()
    ev.checkpoint_sha256 = 'value-sha'
    monkeypatch.setattr(screen, 'shared_evaluator', lambda *a, **k: ev)
    monkeypatch.setattr(prior_module, 'load_prior_checked', lambda *a: ('separate', None, None))
    monkeypatch.setattr(CWVBoundedPuctBot, '_tree_prior', staticmethod(uniform))
    config = cfg('learned', checkpoint='unused', checkpoint_sha256='value-sha',
                 baseline='flat-shortlist', prior=dict(checkpoint='unused', checkpoint_sha256='a'*64),
                 decision_deadline=dict(screen.DEADLINE_RECIPE),
                 bounded_puct=dict(sweeps=2, depth=2))
    bot = screen.make_side(config, 'arm', 19)
    baseline = screen.make_side(config, 'baseline', 19)
    assert isinstance(bot, CWVBoundedPuctBot)
    assert type(baseline) is prior_module.CWVPriorAdmissionBot
    wrapped = screen.CwvTimedPolicy(bot)
    rnd = root()
    wrapped.decide_play(rnd, rnd.turn)
    assert wrapped.decisions[-1]['bounded_puct']['simulations'] == 2
    counters = screen.work_counters([wrapped])
    assert counters['puct_simulations'] == 2
    assert counters['rollouts'] == 0
    assert counters['cheap_evaluations'] == counters['puct_model_rows']
    assert screen._recipe(config)['bounded_puct'] == config['bounded_puct']
    config.pop('decision_deadline')
    with pytest.raises(ValueError, match='300s supervised'):
        screen.make_side(config, 'arm', 19)
    with pytest.raises(ValueError, match='300s supervised'):
        screen.run_cluster(config, 0)
    config['decision_deadline'] = dict(screen.DEADLINE_RECIPE)
    config['reuse_successors'] = True
    with pytest.raises(ValueError, match='successor reuse'):
        screen.make_side(config, 'arm', 19)


def test_puct_summary_reports_configured_worlds(monkeypatch):
    from test_cwv_shortlist_screen import cfg, identity_summary
    from shengji.train import cwv_shortlist_screen as s
    monkeypatch.setattr(s.duel, 'summarize', identity_summary)
    result = s.summary_for([], cfg('learned', bounded_puct=dict(sweeps=2)))
    assert 'W1 admission' in result['baseline_description']


@pytest.mark.parametrize('extra', [['--decision-deadline', '0'], ['--reuse-successors']])
def test_cli_refuses_unsupported_puct_recipe(monkeypatch, tmp_path, extra):
    from shengji.train import cwv_shortlist_screen as s
    monkeypatch.setenv('SHENGJI_REQUIRE_VOIDS', '1')
    with pytest.raises(SystemExit) as exc:
        s.main(['--arm', 'learned', '--checkpoint', 'unused', '--prior-checkpoint', 'unused',
                '--baseline', 'flat-shortlist', '--puct-sweeps', '2', '--seed0', '19',
                '--out', str(tmp_path / 'absent'), *extra])
    assert exc.value.code == 2
    assert not (tmp_path / 'absent' / 'config.json').exists()


def test_parent_checks_outcome_head_before_publishing(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from shengji.train import cwv_shortlist_screen as s
    def refuse(*a, **kw):
        assert kw['value_head'] == 'outcome'
        raise ValueError('unsupported export')
    monkeypatch.setattr(s, 'shared_evaluator', refuse)
    with pytest.raises(ValueError, match='unsupported export'):
        s._run_screen(SimpleNamespace(checkpoint=str(tmp_path / 'bad.npz'), arm='learned',
            puct_sweeps=2, value_head=None, batch_size=128, encoding='mlp-static'), None)
    assert not (tmp_path / 'config.json').exists()


@pytest.mark.parametrize('mover,expected_sign', [(1, -1), (2, 1)])
def test_opponent_minimizes_partner_maximizes_root_value(monkeypatch, mover, expected_sign):
    from types import SimpleNamespace
    from shengji.train import cwv_bounded_puct as p
    class Tiny:
        phase = 'play'
        turn = 0
        history = []
        _determinized_world = True
        stage = 0
        value = 0.
        def play(self, seat, cards):
            assert seat == self.turn
            if self.stage == 0:
                self.stage, self.turn = 1, mover
            else:
                self.stage, self.phase = 2, 'round_end'
                self.value = 1. if cards == ['plus'] else -1.
    monkeypatch.setattr(p, 'leaf_copy', copy.deepcopy)
    monkeypatch.setattr(p, 'enumerate_legal', lambda s, *a, **k: SimpleNamespace(
        complete=True, actions=[['root']] if s.stage == 0 else [['plus'], ['minus']]))
    monkeypatch.setattr(p, 'continuation_values', lambda leaves, *a, **k: SimpleNamespace(
        values=np.array([s.value for s in leaves]), model_rows=0, model_batches=0,
        terminal_rows=len(leaves)))
    result = p.search_worlds([Tiny()], 0, prior_logits=lambda s, t, a: np.zeros(len(a)),
                            evaluator=None, config=PuctConfig(sweeps=40, depth=3))
    assert expected_sign * result['totals'][('root',)] / 40 > .7
