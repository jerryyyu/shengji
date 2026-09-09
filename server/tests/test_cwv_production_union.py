"""Engine-backed tests for the opt-in production-ballot union."""

from __future__ import annotations

import copy

import numpy as np
import pytest

from shengji.ai.mcbot import MCBot
from shengji.harvest.legal import enumerate_legal
from shengji.train.cwv_production_union import CWVProductionUnionBot
from shengji.train.cwv_shortlist import CWVShortlistBot, CWVShortlistConfig
from tests.test_world_shortlist import play_state, round_signature


class Values:
    def __init__(self):
        self.calls = 0

    def score(self, states, seat, **kw):
        self.calls += 1
        # Stable model order: action index is enough to make the top four
        # deterministic while still exercising the real exhaustive pass.
        return np.asarray([float(i) for i, _ in enumerate(states)], dtype=float)


def test_union_keeps_model_order_then_canonical_missing_production():
    rnd = play_state()
    evaluator = Values()
    bot = CWVProductionUnionBot(evaluator, seed=13,
                                config=CWVShortlistConfig(worlds=1, batch_size=19),
                                reuse_successors=True)
    legal = enumerate_legal(rnd, rnd.turn, cap=None)
    selected = bot._candidates(rnd, rnd.turn)
    baseline = CWVShortlistBot(Values(), seed=13,
                               config=CWVShortlistConfig(worlds=1, batch_size=19),
                               reuse_successors=True)
    assert selected[:5] == baseline._candidates(rnd, rnd.turn)
    assert selected[0] == bot.last_shortlist["incumbent"]
    assert selected[1:5] == bot.last_shortlist["shortlist"][1:5]
    # Use the detail's complete production ballot for the exact union witness.
    prod_keys = {tuple(sorted(a)) for a in bot.last_shortlist["production_keys"]}
    assert [tuple(a) for a in selected[5:]] == sorted(
        prod_keys - {tuple(sorted(a)) for a in selected[:5]})
    assert bot.last_shortlist["production_union_added"] == len(selected) - 5
    assert bot.last_shortlist["production_union_added"] > 0
    assert bot.last_shortlist["legal_count"] == len(legal.actions)
    assert evaluator.calls == (len(legal.actions) + 18) // 19
    assert len(bot._union_action_map) == len(legal.actions)
    for offset, action in enumerate(selected):
        key = tuple(sorted(action))
        index, score, _ = bot._union_action_map[key]
        assert index == bot.last_shortlist["shortlist_indices"][offset]
        assert score == bot.last_shortlist["shortlist_means"][offset]


def test_union_metadata_and_rng_match_baseline_and_no_extra_calls():
    rnd = play_state()
    original = round_signature(rnd)
    base_eval, union_eval = Values(), Values()
    base = CWVShortlistBot(base_eval, seed=17,
                           config=CWVShortlistConfig(worlds=1, batch_size=23))
    union = CWVProductionUnionBot(union_eval, seed=17,
                                  config=CWVShortlistConfig(worlds=1, batch_size=23))
    before = union.rng.getstate()
    base._candidates(copy.deepcopy(rnd), rnd.turn)
    union._candidates(rnd, rnd.turn)
    detail = union.last_shortlist
    assert union.rng.getstate() == before
    assert union_eval.calls == base_eval.calls
    if detail["production_union_added"]:
        assert detail["shortlist_indices"][-detail["production_union_added"]:]
    assert detail["production_union"] is True
    assert detail["counts"]["shortlisted_actions"] == len(detail["shortlist"])
    assert detail["counts"]["offballot_kept"] == 4
    assert round_signature(rnd) == original


def test_no_addition_matches_baseline_choice_and_report(monkeypatch):
    # Restrict the production source to its incumbent.  The exhaustive legal
    # population remains untouched and still has more than five actions.
    def incumbent_only(self, rnd, seat):
        return [self.canonical_lead(rnd, seat)]

    monkeypatch.setattr(MCBot, "_candidates", incumbent_only)
    monkeypatch.setattr(
        CWVShortlistBot, "_rollout",
        lambda self, rnd, seat, hands, buried, action, **kw: float(len(action)))
    base_eval, union_eval = Values(), Values()
    base = CWVShortlistBot(base_eval, seed=3,
                           config=CWVShortlistConfig(worlds=1, selection_worlds=2))
    union = CWVProductionUnionBot(union_eval, seed=3,
                                  config=CWVShortlistConfig(worlds=1, selection_worlds=2))
    base.REPORT_FOLD_WORLDS = union.REPORT_FOLD_WORLDS = 30
    left = play_state()
    right = copy.deepcopy(left)
    assert len(enumerate_legal(left, left.turn, cap=None).actions) > 5
    base_play = base.decide_play(left, left.turn)
    union_play = union.decide_play(right, right.turn)
    assert union.last_shortlist["production_union_added"] == 0
    assert union_play == base_play
    assert union_eval.calls == base_eval.calls
    for key in ("candidates", "means", "n_by_candidate", "paired_se",
                "report_fold", "alloc", "work", "played_index", "played",
                "reason", "sampler_counters"):
        assert union.last_decision_record[key] == base.last_decision_record[key]
    assert union.last_decision_record["production_union"] is True
    assert union.last_decision_record["production_union_added"] == 0
    with pytest.raises(ValueError, match="learned shortlist"):
        CWVProductionUnionBot(None, config=CWVShortlistConfig(uniform=True))


def test_alternatives_must_remain_four():
    with pytest.raises(ValueError, match="exactly four"):
        CWVProductionUnionBot(Values(), config=CWVShortlistConfig(alternatives=5))
