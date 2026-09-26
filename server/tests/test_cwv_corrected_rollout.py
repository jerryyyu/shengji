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


# ------------------------------------------- the opponent is configurable (#625)
def test_the_baseline_bot_is_built_from_the_recorded_identity():
    """The summary reports config['base_policy']; the bot must come from THAT,
    not a second literal that merely happens to match it today."""
    import shengji.train.cwv_shortlist_screen as screen
    import inspect
    src = inspect.getsource(screen)
    assert 'make_bot("mc-s0-report-lcb"' not in src, \
        "the baseline bot is hardcoded again; the recorded identity can now lie"
    assert 'make_bot(base_policy_of(config)' in src


def test_an_unusable_opponent_fails_closed_at_configuration():
    """SmartBot and the heuristic are NOT usable: the oracle arms subclass the
    baseline class. That must be refused before a worker starts, not inside one."""
    import pytest
    from shengji.oracle.screen import base_policy_class, OracleScreenError
    for name in ("smart", "heuristic"):
        with pytest.raises(OracleScreenError, match="not a registered MCBot"):
            base_policy_class(name)


def test_weak_mc_opponents_are_available_for_a_positive_control():
    """The exploitability probe needs a WEAKER opponent to tell 'hard to
    exploit' apart from 'this attack does nothing'."""
    from shengji.oracle.screen import base_policy_class
    for name in ("mc", "mc-lite"):
        assert base_policy_class(name) is not None


def test_the_queue_omits_the_flag_by_default():
    """Default must put the historical argv on the wire, byte for byte."""
    import shengji.train.cwv_screen_queue as q
    import inspect
    src = inspect.getsource(q)
    assert 'if args.baseline_policy else []' in src, "the flag must be opt-in"


# ---------------------------- the weak control must actually BE weak (#645 P2)
def _baseline_bot(policy):
    """Build the baseline side through the REAL path and hand back the bot, so
    these assert instantiated budgets rather than reading the source."""
    import shengji.train.cwv_shortlist_screen as screen
    config = {"base_policy": policy, "arm": "policy", "production_multiplier": 1,
              "arm_policy": None, "baseline": "production"}
    return screen.make_side(config, "baseline", seed=1)


def test_a_weak_opponent_keeps_its_registry_budget():
    """Codex P2: make_side stamped N=30/R=300 over every baseline, which would
    have erased the weakness the positive control exists to create -- a screen
    REPORTING mc-lite while playing a production-strength opponent."""
    from shengji.ai.registry import REGISTRY
    for policy, expected in (("mc-lite", REGISTRY["mc-lite"].N_DETERMINIZATIONS),
                             ("mc", REGISTRY["mc"].N_DETERMINIZATIONS)):
        bot = _baseline_bot(policy)
        assert bot.N_DETERMINIZATIONS == expected, (
            "%s played at N=%s, not its registry N=%s -- the weak control was "
            "silently strengthened" % (policy, bot.N_DETERMINIZATIONS, expected))


def test_mc_lite_is_actually_weaker_than_the_default_baseline():
    """If the two ended up at the same budget the control would be no control."""
    import shengji.train.cwv_shortlist_screen as screen
    from shengji.oracle.screen import DEFAULT_BASE_POLICY
    weak = _baseline_bot("mc-lite").N_DETERMINIZATIONS
    default = _baseline_bot(DEFAULT_BASE_POLICY).N_DETERMINIZATIONS
    assert weak < default, "mc-lite N=%s is not below the default N=%s" % (weak, default)


def test_the_default_baseline_budget_is_unchanged():
    """The historical path must still be stamped with the production budget."""
    import shengji.train.cwv_shortlist_screen as screen
    from shengji.oracle.screen import DEFAULT_BASE_POLICY
    bot = _baseline_bot(DEFAULT_BASE_POLICY)
    assert bot.N_DETERMINIZATIONS == screen.BASELINE_SELECT_WORLDS
    assert bot.REPORT_FOLD_WORLDS == screen.BASELINE_REPORT_WORLDS


def _captured_build_config_kwargs(monkeypatch, policy):
    """Capture what summary_for hands to build_config, at the REAL call site."""
    import shengji.train.cwv_shortlist_screen as screen
    seen = {}

    def spy(**kwargs):
        seen.update(kwargs)
        raise RuntimeError("stop after the config is built")

    monkeypatch.setattr(screen.duel, "build_config", spy)
    config = {"base_policy": policy, "arm": "policy", "arm_policy": None,
              "baseline": "production", "production_multiplier": 1, "seed0": 1}
    try:
        screen.summary_for([], config)
    except RuntimeError:
        pass
    return seen


def test_summary_records_the_budget_the_bot_actually_plays(monkeypatch):
    """The reported P2: summary_for built metadata with the production
    constants while a weak opponent played its own smaller budget, so
    work.effective said N=30/R=300 for a bot running N=5/R=0."""
    seen = _captured_build_config_kwargs(monkeypatch, "mc-lite")
    assert seen, "build_config was never called"
    bot = _baseline_bot("mc-lite")
    assert (seen["select_worlds"], seen["report_worlds"]) == \
        (bot.N_DETERMINIZATIONS, bot.REPORT_FOLD_WORLDS), (
            "summary recorded (%s, %s) for a bot playing (%s, %s)"
            % (seen["select_worlds"], seen["report_worlds"],
               bot.N_DETERMINIZATIONS, bot.REPORT_FOLD_WORLDS))


def test_summary_budget_is_unchanged_for_the_default_opponent(monkeypatch):
    import shengji.train.cwv_shortlist_screen as screen
    from shengji.oracle.screen import DEFAULT_BASE_POLICY
    seen = _captured_build_config_kwargs(monkeypatch, DEFAULT_BASE_POLICY)
    assert (seen["select_worlds"], seen["report_worlds"]) == \
        (screen.BASELINE_SELECT_WORLDS, screen.BASELINE_REPORT_WORLDS)


def test_recorded_budget_matches_the_bot_that_actually_plays():
    """The invariant behind both #645 P2s: metadata and bot must come from the
    same place. Recording N=30/R=300 while mc-lite plays N=5/R=0 is the summary
    lying about the run."""
    import shengji.train.cwv_shortlist_screen as screen
    from shengji.oracle.screen import DEFAULT_BASE_POLICY
    for policy in ("mc-lite", "mc", DEFAULT_BASE_POLICY):
        select, report = screen.effective_baseline_budget(policy)
        bot = _baseline_bot(policy)
        assert (bot.N_DETERMINIZATIONS, bot.REPORT_FOLD_WORLDS) == (select, report), (
            "%s: recorded (%s, %s) but the bot plays (%s, %s)"
            % (policy, select, report, bot.N_DETERMINIZATIONS, bot.REPORT_FOLD_WORLDS))


def test_the_default_constants_and_the_registry_cannot_drift_apart():
    """BASELINE_SELECT_WORLDS/REPORT_WORLDS duplicate the default policy's own
    recipe. They agree today; this fails the moment either moves alone."""
    import shengji.train.cwv_shortlist_screen as screen
    from shengji.oracle.screen import DEFAULT_BASE_POLICY
    effective = screen.effective_baseline_budget(DEFAULT_BASE_POLICY)
    assert effective == (screen.BASELINE_SELECT_WORLDS, screen.BASELINE_REPORT_WORLDS), (
        "the duplicated constants no longer match the default policy's registry recipe")
