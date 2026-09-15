import copy
import random

import numpy as np
import pytest

from shengji.ai.heuristic import HeuristicBot
from shengji.ai.smart import SmartBot
from shengji.engine.game import Game
from shengji.rl.value_afterstate import OUTCOME_CLASSES, category_signed_level, terminal_distribution
from shengji.train.cwv_truncated_value import continuation_values


def state():
    rnd = Game(random.Random(19)).start_round()
    bot = SmartBot()
    while rnd.phase == 'deal':
        seat, _, _ = rnd.deal_next()
        cards = bot.decide_declare(rnd, seat)
        if cards:
            rnd.declare(seat, cards)
    for seat in range(4):
        cards = bot.decide_declare(rnd, seat, final=True)
        if cards:
            rnd.declare(seat, cards)
    rnd.finalize_declare()
    rnd.bury(rnd.banker, bot.decide_bury(rnd, rnd.banker))
    return rnd


def play(rnd):
    mover = rnd.turn
    rnd.play(mover, HeuristicBot().decide_play(rnd, mover))


class Evaluator:
    def __init__(self):
        self.calls = []

    def score_many(self, states, seats):
        self.calls.append((copy.deepcopy(states), list(seats)))
        return [0.75 if r.is_attacker(s) else -0.75 for r, s in zip(states, seats)]

    def score(self, states, seat):
        return self.score_many(states, [seat] * len(states))


@pytest.mark.parametrize('prior_plays', [0, 1, 2, 3])
@pytest.mark.parametrize('tricks', [0, 1, 2])
def test_horizon_counts_root_trick_not_extra_trick(prior_plays, tricks):
    rnd = state()
    for _ in range(prior_plays):
        play(rnd)
    start = len(rnd.history)
    root_seat = rnd.turn
    play(rnd)
    original = copy.deepcopy(rnd)
    ev = Evaluator()
    out = continuation_values([rnd], [root_seat], [start], evaluator=ev, tricks=tricks)
    leaf = ev.calls[0][0][0]
    assert len(leaf.history) == max(len(rnd.history), start + tricks)
    assert out.heuristic_plies == max(0, tricks * 4 - prior_plays - 1)
    assert ev.calls[0][1] == [root_seat]  # not next mover's perspective
    assert rnd.hands == original.hands and rnd.history == original.history
    assert rnd.trick == original.trick and rnd.attacker_points == original.attacker_points
    assert out.model_rows == out.model_batches == 1


def test_batch_order_and_no_accrued_points_correction():
    rnd = state()
    play(rnd)
    rnd.attacker_points = 75
    ev = Evaluator()
    out = continuation_values([rnd] * 4, list(range(4)), [0] * 4,
                              evaluator=ev, tricks=0, batch_size=3)
    np.testing.assert_array_equal(out.values, [0.75 if rnd.is_attacker(s) else -0.75 for s in range(4)])
    assert [seats for _, seats in ev.calls] == [[0, 1, 2], [3]]
    assert out.model_rows == 4 and out.model_batches == 2


def test_full_continuation_exact_terminal_and_team_signs():
    rnd = state()
    play(rnd)
    independent = copy.deepcopy(rnd)
    while independent.phase == 'play':
        play(independent)
    support = np.asarray([category_signed_level(i) for i in range(OUTCOME_CLASSES)])
    out = continuation_values([rnd] * 4, list(range(4)), [0] * 4, evaluator=None, tricks=None)
    np.testing.assert_array_equal(out.values, [terminal_distribution(independent, s) @ support for s in range(4)])
    assert out.values[0] == out.values[2] == -out.values[1]
    assert out.model_rows == out.model_batches == 0 and out.terminal_rows == 4


def test_terminal_bypasses_model_even_at_zero_horizon():
    rnd = state()
    while rnd.phase == 'play':
        play(rnd)
    out = continuation_values([rnd], [0], [len(rnd.history) - 1], evaluator=None, tricks=0)
    assert out.terminal_rows == 1 and out.heuristic_plies == out.model_rows == 0


@pytest.mark.parametrize('kwargs', [{'tricks': -1}, {'tricks': True}, {'batch_size': 0}])
def test_reject_invalid_configuration(kwargs):
    options = dict(evaluator=None, tricks=0)
    options.update(kwargs)
    with pytest.raises(ValueError):
        continuation_values([], [], [], **options)


def test_reject_nonfinite_model_values():
    rnd = state()
    class Bad:
        def score_many(self, states, seats):
            return [np.nan] * len(states)
    with pytest.raises(ValueError, match='finite'):
        continuation_values([rnd], [0], [0], evaluator=Bad(), tricks=0)


@pytest.mark.parametrize('horizon', [0, 1, None])
def test_real_search_decision_reaches_independent_report(horizon):
    from shengji.train.cwv_shortlist import CWVShortlistConfig
    from shengji.train.cwv_truncated_search import CWVTruncatedSearchBot
    rnd = state()
    # Following a single keeps the exhaustive test inexpensive.
    seat = rnd.turn
    rnd.play(seat, [rnd.hands[seat][0]])
    bot = CWVTruncatedSearchBot(Evaluator(), continuation_tricks=horizon,
        config=CWVShortlistConfig(worlds=1, selection_worlds=2, alternatives=2))
    bot.REPORT_FOLD_WORLDS = 30
    action = bot.decide_play(rnd, rnd.turn)
    record = bot.last_decision_record
    assert record['alloc']['mode'] == 'uniform-value-continuation'
    assert record['report_fold']['worlds'] == 30
    assert record['report_fold']['complete']
    trace = record['value_continuation']
    from shengji.train.cwv_shortlist_screen import work_counters
    counts = work_counters([bot])
    assert counts['candidate_world_evaluations'] == trace['terminal_rows'] + trace['model_rows']
    assert counts['total_rollouts'] == trace['terminal_rows']
    assert counts['cheap_evaluations'] == counts['cwv_cheap_evaluations'] + trace['model_rows']
    assert trace['units'] == 'acting-team-final-signed-levels'
    if horizon is None:
        assert trace['terminal_rows'] > 0 and trace['model_rows'] == 0
    else:
        assert trace['model_rows'] > 0
    rnd.play(rnd.turn, action)


@pytest.mark.parametrize('control', ['mc', 'full'])
def test_screen_factory_binds_continuation_and_outcome_head(monkeypatch, control):
    from shengji.train import cwv_shortlist_screen as screen
    from shengji.train.cwv_truncated_search import TruncatedSearchMixin
    from test_cwv_shortlist_screen import cfg
    ev = Evaluator()
    ev.checkpoint_sha256 = 'a' * 64
    calls = []
    def load(*args, **kwargs):
        calls.append(kwargs)
        return ev
    monkeypatch.setattr(screen, 'shared_evaluator', load)
    config = cfg('learned', checkpoint='stub.pt', checkpoint_sha256='a' * 64,
                 baseline='flat-shortlist', value_continuation={'tricks': 1, 'baseline': control})
    arm = screen.make_side(config, 'arm', 1)
    baseline = screen.make_side(config, 'baseline', 1)
    assert isinstance(arm, TruncatedSearchMixin) and arm.continuation_tricks == 1
    assert isinstance(baseline, TruncatedSearchMixin) == (control == 'full')
    if control == 'full':
        assert baseline.continuation_tricks is None
    assert all(c['value_head'] == 'outcome' for c in calls)
    assert screen._recipe(config)['value_continuation'] == config['value_continuation']
    changed = dict(config, value_continuation={'tricks': 2, 'baseline': control})
    assert screen._recipe(config) != screen._recipe(changed)
    with pytest.raises(ValueError, match='isolated'):
        screen.make_side(dict(config, value_head='search-mean'), 'arm', 1)


def test_report_restores_rng_and_preserves_pairing(monkeypatch):
    from shengji.train.cwv_shortlist import CWVShortlistConfig
    from shengji.train.cwv_truncated_search import CWVTruncatedSearchBot
    from shengji.ai.memory import Memory
    rnd = state()
    rnd.play(rnd.turn, [rnd.hands[rnd.turn][0]])
    seat = rnd.turn
    bot = CWVTruncatedSearchBot(Evaluator(), config=CWVShortlistConfig(worlds=1))
    bot.continuation_counts = dict.fromkeys(('model_rows', 'model_batches', 'terminal_rows', 'heuristic_plies'), 0)
    action = HeuristicBot().decide_play(rnd, seat)
    before = bot.rng.getstate()
    # The same candidate must have a zero paired difference on every world.
    report = bot._report_fold_gap(rnd, seat, Memory(rnd, seat), rnd.is_attacker(seat),
                                 action, action, 30, seed=123, keep_deltas=True)
    assert report['complete'] and report['deltas'] == [0.] * 30
    assert report['gap'] == report['se'] == 0
    assert bot.rng.getstate() == before
    monkeypatch.setattr(bot, '_sample_hands', lambda *args: None)
    report = bot._report_fold_gap(rnd, seat, None, rnd.is_attacker(seat),
                                 action, action, 30, seed=123)
    assert not report['complete'] and report['worlds'] == 0
    assert bot.rng.getstate() == before
