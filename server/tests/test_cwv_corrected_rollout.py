import random

import numpy as np
import pytest

from shengji.ai.memory import Memory
from shengji.train.cwv_corrected_rollout import CWVCorrectedRolloutBot
from shengji.train.cwv_shortlist import CWVShortlistConfig
from shengji.rl.value_afterstate import category_signed_level, signed_level_category
from tests.test_world_shortlist import play_state, round_signature


class ZeroEvaluator:
    def identity(self):
        return {}

    def score(self, leaves, seat):
        return np.zeros(len(leaves))


def make(mode='corrected', n=4, m=2):
    bot = CWVCorrectedRolloutBot(ZeroEvaluator(), correction_mode=mode,
            correction_worlds=n, residual_worlds=m, seed=17,
            config=CWVShortlistConfig(worlds=1, selection_worlds=2, batch_size=3))
    bot.REPORT_FOLD_WORLDS = 30
    return bot


@pytest.mark.parametrize('advance', [False, True])
def test_real_decision_uses_real_rollouts_and_keeps_report_in_points(monkeypatch, advance):
    rnd = play_state()
    if advance:
        from shengji.ai.heuristic import HeuristicBot
        rnd.play(rnd.turn, HeuristicBot().decide_play(rnd, rnd.turn))
    from shengji.harvest.legal import enumerate_legal
    actions = list(enumerate_legal(rnd, rnd.turn).actions)[:3]
    assert len(actions) > 1
    before = round_signature(rnd)
    bot = make(n=2, m=2)
    monkeypatch.setattr(bot, '_candidates', lambda *a: actions)
    report = bot._report_fold_gap
    observed = []
    def wrapped(*a, **kw):
        rng = bot.rng.getstate()
        value = report(*a, **kw)
        assert bot.rng.getstate() == rng
        observed.append(value)
        return value
    monkeypatch.setattr(bot, '_report_fold_gap', wrapped)
    assert bot.decide_play(rnd, rnd.turn) in actions
    record = bot.last_decision_record
    assert record['paired_se'] is None
    assert record['alloc']['selection_units'] == 'acting-team-signed-level'
    assert record['alloc']['report_units'] == 'attacker-points'
    assert record['work']['selection_rollouts'] == 2 * len(actions)
    assert record['work']['report_rollouts'] == 60
    assert bot.corrected_rollout_counts['model_evaluations'] == 2 * len(actions)
    assert len(observed) == 1 and observed[0]['complete']
    assert observed[0]['seed'] == record['report_seed']
    assert bot.rollouts == 2 * len(actions) + 60
    assert round_signature(rnd) == before
    from shengji.api.debug_play import play_analysis
    rows, info = play_analysis(bot, record['candidates'][0],
                               is_attacker=rnd.is_attacker(rnd.turn), elapsed=0.)
    assert info['selection_score_units'] == 'expected signed levels for acting team'
    assert info['report_gap_units'] == 'acting-team points: challenger minus incumbent'
    assert all(row['attackers_avg'] is None for row in rows)
    assert all(row['paired_se_vs_incumbent'] is None for row in rows)
    assert [row['acting_team_levels'] for row in rows] == [record['means'][row['index']] for row in rows]


def test_exact_formula_wired_to_challenger_and_report_independent(monkeypatch):
    import shengji.train.cwv_corrected_rollout as module
    rnd = play_state()
    actions = [[c] for c in dict.fromkeys(rnd.hands[rnd.turn])][:3]
    bot = make()
    monkeypatch.setattr(bot, '_candidates', lambda *a: actions)
    # The sampled world tag never comes from true opponent cards.
    # Fill opponent maps while keeping simple world tags for this arithmetic test.
    draws = iter([({s: [] for s in range(4) if s != rnd.turn}, [i]) for i in range(4)])
    monkeypatch.setattr(bot, '_sample_hands', lambda *a: next(draws))
    v = np.array([[0., 4., -1.], [2., -3., 1.], [1., 2., 3.], [0., 1., -2.]])
    monkeypatch.setattr(module, 'afterstate',
                        lambda r, s, h, b, a, **kw: (b[0], actions.index(a)))
    bot.evaluator.score = lambda leaves, seat: np.array([v[x] for x in leaves])
    points = [0, 80, 120]
    calls = []
    def rollout(r, s, h, b, a, **kw):
        calls.append((b[0], actions.index(a)))
        return points[actions.index(a)]
    monkeypatch.setattr(bot, '_rollout', rollout)
    report_calls = []
    def report(r, s, mem, attack, challenger, incumbent, n, *, seed, **kw):
        report_calls.append((challenger, incumbent, seed))
        return dict(gap=-1., se=0., worlds=n, attempts=n, complete=True, seed=seed)
    monkeypatch.setattr(bot, '_report_fold_gap', report)
    assert bot.decide_play(rnd, rnd.turn) == actions[0]  # report can veto correction
    record = bot.last_decision_record
    ids = record['alloc']['residual_indices']
    r = np.array([category_signed_level(signed_level_category(p, rnd.is_attacker(rnd.turn)))
                  for p in points])
    expected = v.mean(0) + r - v[ids].mean(0)
    np.testing.assert_allclose(record['means'], expected)
    assert calls == [(wi, ci) for wi in ids for ci in range(3)]
    expected_challenger = bot._pick_index(actions, expected, [1, 2])
    assert report_calls[0][0] == actions[expected_challenger]
    assert report_calls[0][2] == record['report_seed']
    assert record['alloc']['model_evaluations'] == 12
    assert record['work']['total_rollouts'] == 66


def test_levels_control_same_worlds_and_subset_without_model_evaluation(monkeypatch):
    rnd = play_state()
    actions = [[c] for c in dict.fromkeys(rnd.hands[rnd.turn])][:2]
    outputs = []
    for mode in ('levels', 'corrected'):
        bot = make(mode)
        monkeypatch.setattr(bot, '_rollout', lambda *a, **kw: 120)
        value = bot._selection_override(rnd, rnd.turn, actions, Memory(rnd, rnd.turn),
                rnd.is_attacker(rnd.turn), allocation_rng=random.Random(42))
        outputs.append((value, bot.last_alloc['residual_indices'], bot.rng.getstate()))
        assert bot.corrected_rollout_counts['model_evaluations'] == (8 if mode == 'corrected' else 0)
    assert outputs[0] == outputs[1]  # constant zero model cancels exactly


def test_underfill_cannot_report_or_fabricate_rollouts(monkeypatch):
    rnd = play_state()
    actions = [[c] for c in dict.fromkeys(rnd.hands[rnd.turn])][:2]
    bot = make()
    monkeypatch.setattr(bot, '_candidates', lambda *a: actions)
    monkeypatch.setattr(bot, '_sample_hands', lambda *a: None)
    monkeypatch.setattr(bot, '_report_fold_gap', lambda *a, **kw: pytest.fail('report on underfill'))
    assert bot.decide_play(rnd, rnd.turn) == actions[0]
    assert bot.rollouts == 0
    assert bot.last_decision_record['alloc']['short'] is True
    assert bot.corrected_rollout_counts['underfilled'] == 1


@pytest.mark.parametrize('kwargs', [{'residual_worlds': 0}, {'correction_worlds': True},
                                  {'correction_mode': 'bad'}, {'residual_worlds': 65}])
def test_bad_recipe_refuses(kwargs):
    with pytest.raises(ValueError):
        CWVCorrectedRolloutBot(ZeroEvaluator(), **kwargs)


def test_nonfinite_model_refuses(monkeypatch):
    rnd = play_state()
    bot = make(n=2, m=1)
    bot.evaluator.score = lambda leaves, seat: [float('nan')] * len(leaves)
    with pytest.raises(ValueError, match='finite acting-team'):
        bot._selection_override(rnd, rnd.turn, [[rnd.hands[rnd.turn][0]]],
                Memory(rnd, rnd.turn), rnd.is_attacker(rnd.turn), allocation_rng=random.Random(1))


def test_full_admission_to_report_path_without_method_stubs():
    rnd = play_state()
    bot = make(n=2, m=1)
    before = round_signature(rnd)
    played = bot.decide_play(rnd, rnd.turn)
    record = bot.last_decision_record
    assert played in record['candidates']
    assert record['cwv_shortlist']['shortlist_indices']
    assert record['alloc']['rollouts'] == len(record['candidates'])
    assert record['work']['report_rollouts'] == 60
    assert bot.shortlist_counts['cheap_evaluations'] > 0
    assert bot.corrected_rollout_counts['model_evaluations'] == 2 * len(record['candidates'])
    assert round_signature(rnd) == before
