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


def test_reject_live_world_and_bad_prior():
    rnd = root()
    rnd._determinized_world = False
    with pytest.raises(ValueError, match='determinized'):
        search_worlds([rnd], rnd.turn, prior_logits=uniform, evaluator=Evaluator())
    rnd._determinized_world = True
    with pytest.raises(ValueError, match='finite policy'):
        search_worlds([rnd], rnd.turn, prior_logits=lambda *a: [float('nan')], evaluator=Evaluator())


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
