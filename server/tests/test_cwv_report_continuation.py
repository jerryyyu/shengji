"""Focused witnesses for the DEV CWV report-continuation adapter."""
from __future__ import annotations

import copy

import numpy as np
import pytest

from shengji.train.cwv_report_continuation import CWVReportContinuationBot
from shengji.train.cwv_shortlist import CWVShortlistBot, CWVShortlistConfig
from tests.test_world_shortlist import play_state


class RootValues:
    def __init__(self):
        self.score_calls = 0

    def score(self, positions, seat):
        self.score_calls += 1
        return np.asarray([float(r.attacker_points) for r in positions])


class ContinuationValues:
    def __init__(self, rule=None):
        self.calls = 0
        self.seats = []
        self.rule = rule or (lambda position, seat: float(position.attacker_points))

    def score_many(self, positions, seats):
        self.calls += 1
        self.seats.extend(seats)
        return np.asarray([self.rule(position, seat)
                           for position, seat in zip(positions, seats)], dtype=float)


def _configured(bot):
    bot.N_DETERMINIZATIONS = 1
    bot.REPORT_FOLD_WORLDS = 30
    return bot


def test_k0_actual_decision_matches_flat_report_and_rng_moments():
    root = play_state(13)
    flat = _configured(CWVShortlistBot(RootValues(), seed=17,
                                       config=CWVShortlistConfig(selection_worlds=1)))
    adapter = _configured(CWVReportContinuationBot(
        RootValues(), seed=17, guidance="learned", tricks=0,
        config=CWVShortlistConfig(selection_worlds=1)))
    assert adapter.decide_play(copy.deepcopy(root), root.turn) == \
        flat.decide_play(copy.deepcopy(root), root.turn)
    assert adapter.last_decision_record["report_fold"] == flat.last_decision_record[
        "report_fold"]
    assert adapter.last_decision_record["means"] == flat.last_decision_record["means"]
    assert adapter.last_decision_record["rng_state"] == flat.last_decision_record["rng_state"]
    assert adapter.rng.getstate() == flat.rng.getstate()
    assert adapter.last_decision_record["cwv_report_continuation"]["counts"]["net_plays"] == 0


def test_selection_uses_root_score_only_but_report_uses_continuation_score_many():
    root_eval = RootValues()
    continuation = ContinuationValues()
    bot = _configured(CWVReportContinuationBot(
        root_eval, continuation_evaluator=continuation, seed=5,
        config=CWVShortlistConfig(selection_worlds=1)))
    root = play_state(21)
    bot.decide_play(root, root.turn)
    assert root_eval.score_calls > 0
    assert continuation.calls > 0
    rec = bot.last_decision_record["cwv_report_continuation"]
    assert rec["schema"] == "cwv-report-continuation-v1"
    assert rec["counts"]["report_net_plays"] > 0
    assert rec["counts"]["selection_net_plays"] == 0
    assert bot.netroll_counts["report_net_plays"] == rec["counts"]["report_net_plays"]


def test_root_shortlist_is_unchanged_and_inner_ballot_does_not_recurse():
    root = play_state(7)
    cfg = CWVShortlistConfig(selection_worlds=1)
    flat = CWVShortlistBot(RootValues(), seed=9, config=cfg)
    adapter = CWVReportContinuationBot(
        RootValues(), continuation_evaluator=ContinuationValues(), seed=9,
        config=cfg)
    assert adapter._candidates(copy.deepcopy(root), root.turn) == \
        flat._candidates(copy.deepcopy(root), root.turn)

    world = ([list(hand) for hand in root.hands], list(root.buried))
    adapter._candidates = lambda *args: (_ for _ in ()).throw(
        AssertionError("inner ballot recursed into exhaustive CWV root"))
    adapter._lockstep_values(root, root.turn, [world],
                             [adapter._literal_ballot_helper.canonical_lead(root, root.turn)],
                             stage="report")


def test_prior_requires_separate_continuation_and_learned_can_be_isolated():
    with pytest.raises(ValueError, match="prior guidance requires continuation_evaluator"):
        CWVReportContinuationBot(RootValues(), guidance="prior")
    root_eval = RootValues()
    continuation = ContinuationValues()
    bot = CWVReportContinuationBot(root_eval,
                                   continuation_evaluator=continuation,
                                   guidance="prior", tricks=1)
    assert bot.root_evaluator is root_eval
    assert bot.continuation_evaluator is continuation
    assert bot.evaluator is root_eval


@pytest.mark.parametrize("kwargs", [
    {"guidance": "bogus"},
    {"tricks": True},
    {"tricks": -1},
])
def test_invalid_configuration_refuses(kwargs):
    with pytest.raises(ValueError):
        CWVReportContinuationBot(RootValues(), **kwargs)


def test_heuristic_forces_no_net_and_restores_root_after_continuation_error():
    root_eval = RootValues()
    continuation = ContinuationValues()
    continuation.score_many = lambda positions, seats: (_ for _ in ()).throw(
        RuntimeError("continuation failure"))
    bot = CWVReportContinuationBot(root_eval, continuation_evaluator=continuation,
                                   guidance="heuristic", tricks=3)
    assert bot.NET_TRICKS == 0
    root = play_state(3)
    world = ([list(hand) for hand in root.hands], list(root.buried))
    action = bot._literal_ballot_helper.canonical_lead(root, root.turn)
    # K=0 never scores the continuation net, so this also witnesses the
    # heuristic no-net control.  Force a failure only for a learned lockstep.
    bot.NET_TRICKS = 1
    with pytest.raises(RuntimeError, match="continuation failure"):
        bot._lockstep_values(root, root.turn, [world], [action], stage="report")
    assert bot.evaluator is root_eval


def test_mover_perspective_is_not_root_perspective():
    assert CWVReportContinuationBot._net_perspective(3, 0) == 3
