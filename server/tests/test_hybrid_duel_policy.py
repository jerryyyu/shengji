"""Focused tests for the DEV-only multi-trick duel adapter."""

from types import SimpleNamespace
import time

import numpy as np
import pytest

from test_encoder_round_compat import PACKAGE_SHA, pinned_production_package  # noqa: F401
from test_pv_tree_search import hybrid_belief_package  # noqa: F401

from scripts.hybrid_duel_policy import HybridMultiTrickMixin
from scripts.hybrid_duel_policy import attach_hybrid


class _Fake(HybridMultiTrickMixin):
    def __init__(self, *, enabled=True, budget=None, deep=None):
        self.hybrid_multi_trick = enabled
        self.hybrid_decision_started = None
        self._tree_started = None
        self._tree_v0 = np.asarray([[0.20, 0.10], [0.20, 0.10]])
        self.serving_budget_seconds = budget
        self.deep = deep if deep is not None else np.asarray(
            [[0.20, 0.30], [0.20, 0.30]])
        self.calls = []
        self.hands = None

    def _tree_lookahead(self, rnd, seat, actions, worlds, gate, **kwargs):
        self.calls.append((rnd, seat, actions, worlds, kwargs))
        return self.deep, {"tree_completed_tricks_min": 2,
                           "tree_completed_tricks_max": 2}


def _root():
    return SimpleNamespace(hands=[list(range(8)), list(range(8)),
                                  list(range(8)), list(range(8))])


def _select(self, rnd, seat, admitted, means, **kwargs):
    return int(np.argmax(means))


def test_enabled_path_uses_all_worlds_and_actions_and_selects_changed_move(monkeypatch):
    from shengji.train.policy_value_search import PolicyValueBot

    monkeypatch.setattr(PolicyValueBot, "_select", _select)
    bot = _Fake()
    fields = {}
    winner = bot._hybrid_tree_decide(
        _root(), 0, [["A"], ["B"]], np.asarray([0.20, 0.10]),
        [("w0",), ("w1",)], 0, fields, {})
    assert winner == 1
    assert bot.calls[0][2] == [["A"], ["B"]]
    assert bot.calls[0][3] == [("w0",), ("w1",)]
    assert bot.calls[0][4] == {"completed_tricks": 2, "exact_max_cards": 0}
    assert fields["hybrid_attempted"] is True
    assert fields["hybrid_applied"] is True
    assert fields["hybrid_changed"] is True
    assert fields["hybrid_completed_tricks"] == 2
    assert fields["hybrid_worlds"] == 2
    assert fields["hybrid_actions"] == 2


def test_zero_budget_falls_back_without_publishing_partial_result(monkeypatch):
    from shengji.train.policy_value_search import PolicyValueBot

    monkeypatch.setattr(PolicyValueBot, "_select", _select)
    bot = _Fake(budget=1e-9)
    fields = {}
    winner = bot._hybrid_tree_decide(
        _root(), 0, [["A"], ["B"]], np.asarray([0.20, 0.10]),
        [("w0",), ("w1",)], 0, fields, {})
    assert winner == 0
    assert fields["hybrid_applied"] is False
    assert fields["hybrid_fallback"] == "budget"


@pytest.mark.parametrize("deep", [np.asarray([[np.nan, 0.3], [0.2, 0.3]]),
                                   np.asarray([[0.2], [0.3]])])
def test_incomplete_or_nonfinite_lookahead_refuses(monkeypatch, deep):
    from shengji.train.policy_value_search import PolicyValueBot

    monkeypatch.setattr(PolicyValueBot, "_select", _select)
    bot = _Fake(deep=deep)
    fields = {}
    winner = bot._hybrid_tree_decide(
        _root(), 0, [["A"], ["B"]], np.asarray([0.20, 0.10]),
        [("w0",), ("w1",)], 0, fields, {})
    assert winner == 0
    assert fields["hybrid_applied"] is False
    assert fields["hybrid_fallback"] == "invalid"


def test_disabled_path_is_identity_and_does_not_call_lookahead():
    bot = _Fake(enabled=False)
    fields = {}
    winner = bot._hybrid_tree_decide(
        _root(), 0, [["A"], ["B"]], np.asarray([0.20, 0.10]),
        [("w0",), ("w1",)], 0, fields, {})
    assert winner == 0
    assert bot.calls == []
    assert fields["hybrid_fallback"] == "disabled"


def test_exact_endgame_is_skipped_to_preserve_d7_baseline():
    bot = _Fake()
    root = SimpleNamespace(hands=[list(range(7))] * 4)
    fields = {}
    winner = bot._hybrid_tree_decide(
        root, 0, [["A"], ["B"]], np.asarray([0.20, 0.10]),
        [("w0",), ("w1",)], 0, fields, {})
    assert winner == 0
    assert bot.calls == []
    assert fields["hybrid_fallback"] == "exact_endgame"


def test_attach_runs_real_decision_and_publishes_hybrid_record():
    from test_policy_world_search import state
    from test_pv_tree_search import bot_of

    bot = bot_of(tree_config=None, worlds=2, seed=11)
    original_config = bot.config
    attach_hybrid(bot)
    assert bot.config is original_config
    assert bot.config.tree is None
    rnd = state()
    action = bot.decide_play(rnd, rnd.turn)
    record = bot.last_decision_record
    assert isinstance(action, list) and action
    assert record["hybrid_attempted"] is True
    assert record["hybrid_worlds"] == 2
    assert record["hybrid_actions"] >= 1
    assert record["hybrid_completed_tricks"] in (0, 2)


def test_attach_off_preserves_real_decision_identity():
    from test_policy_world_search import state
    from test_pv_tree_search import bot_of

    baseline = bot_of(tree_config=None, worlds=2, seed=12)
    hybrid = bot_of(tree_config=None, worlds=2, seed=12)
    attach_hybrid(hybrid, enabled=False)
    left, right = state(), state()
    assert baseline.decide_play(left, left.turn) == hybrid.decide_play(right, right.turn)
    assert hybrid.last_decision_record["hybrid_fallback"] == "disabled"


def test_attach_rejects_existing_tree_bot():
    from test_pv_tree_search import bot_of
    from shengji.train.pv_tree_config import PVTreeConfig

    bot = bot_of(PVTreeConfig(sims=0), worlds=2)
    with pytest.raises(TypeError, match="without an existing tree config"):
        attach_hybrid(bot)


def test_pinned_combo_keeps_exact_endgame_path(pinned_production_package,
                                               hybrid_belief_package, monkeypatch):
    from copy import deepcopy
    from shengji.ai import belief_numpy
    from shengji.train.pv_search_policy import make_pv_search_bot
    from test_xmtj_throw_regressions import position

    # Wiring identity must not depend on cold-start preparation timing.
    monkeypatch.setattr(belief_numpy, 'PREP_SECONDS', 60.0)
    belief_path, belief_sha = hybrid_belief_package
    recipe = dict(sha256=PACKAGE_SHA, worlds=2, candidates=8, seed=13,
                  world_history_legal=True, world_history_draw=True,
                  belief_worlds=True, belief_checkpoint=belief_path,
                  belief_sha256=belief_sha, exact_lead_endgame=True,
                  exact_deep_cards=7, exact_follow=True,
                  exact_follow_max_cards=7, exact_follow_solver='compact-level',
                  exact_follow_max_nodes=50_000_000)
    baseline = make_pv_search_bot(str(pinned_production_package), **recipe)
    candidate = attach_hybrid(make_pv_search_bot(str(pinned_production_package), **recipe))
    assert candidate.config == baseline.config
    rnd = position(52)
    expected = baseline.decide_play(deepcopy(rnd), rnd.turn)
    assert candidate.decide_play(deepcopy(rnd), rnd.turn) == expected
    assert candidate.last_decision_record['hybrid_fallback'] == 'exact_endgame'
    assert baseline.last_decision_record['belief_fallback'] == 0
    assert candidate.last_decision_record['belief_fallback'] == 0
    for key, value in baseline.last_decision_record.items():
        if key.startswith('exact_') and 'seconds' not in key:
            assert candidate.last_decision_record[key] == value


def test_real_budget_expiry_keeps_completed_pv_action_and_record(monkeypatch):
    from copy import deepcopy
    from test_policy_world_search import state
    from test_pv_tree_search import bot_of

    baseline = bot_of(tree_config=None, worlds=2, seed=18, budget=0.25)
    hybrid = bot_of(tree_config=None, worlds=2, seed=18, budget=0.25)
    attach_hybrid(hybrid)
    original = hybrid._tree_lookahead

    def slow(*args, **kwargs):
        time.sleep(0.30)
        return original(*args, **kwargs)

    hybrid._tree_lookahead = slow
    left = state()
    right = deepcopy(left)
    expected = baseline.decide_play(left, left.turn)
    actual = hybrid.decide_play(right, right.turn)
    assert actual == expected
    assert hybrid.last_decision_record["hybrid_fallback"] == "budget"
    assert hybrid.last_decision_record["hybrid_completed_tricks"] == 0
    assert hybrid.last_decision_record["hybrid_applied"] is False
