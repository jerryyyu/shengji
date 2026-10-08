"""`shengji.train.optional_stage`: the shared transaction for an optional
serving stage after a finalized base decision, and the reusable contract
(`optional_stage_contract.CONTRACT`) applied to every stage that uses it:
``adaptive_worlds`` (#936) and ``doomed_throw_reselect`` (#946).

A NEW optional stage adds a `StageCase` to ``CASES`` below.
"""
import copy
import time

import pytest

from optional_stage_contract import CONTRACT, Deadline, StageCase
from shengji.ai.heuristic import HeuristicBot
from shengji.train.optional_stage import OptionalStage, OptionalStageTripped
from shengji.train.pv_search_policy import PVSearchBudgetExceeded
from test_policy_world_search import state
from test_pv_adaptive_worlds import (RELEASE42_RULES, NoisyEvaluator, _comparable,
                                     served as aw_served)
from test_pv_doomed_throw_reselect import (DECISIONS, draw, served as dtr_served, tail,
                                           yjqj)


# ------------------------------------------------------- the stages under the contract

def _aw_run(deadline, adaptive=True):
    """One served `_search` (release 42 + ``adaptive_worlds``) on a near-tie,
    under ``deadline``; the budget is set (so the stage is guarded) and far."""
    bot = aw_served(NoisyEvaluator(), budget=1e6, adaptive_worlds=adaptive, **RELEASE42_RULES)
    rnd = state()
    seat = rnd.turn
    anchor = HeuristicBot.decide_play(bot, copy.deepcopy(rnd), seat)
    played = bot._search(copy.deepcopy(rnd), seat, anchor, time.perf_counter(), deadline)
    record = bot.last_decision_record
    if adaptive:
        assert record["adaptive_worlds_triggered"] is True
    return bot, (list(played), _comparable(record))


def _aw_abandon(bot):
    record = bot.last_decision_record
    if not record.get("adaptive_worlds_abandoned"):
        return None
    return record["adaptive_worlds_abandon_reason"], record["adaptive_worlds_abandon_error"]


_DTR = DECISIONS["SJ"]
_DTR_ADMITTED = [_DTR["throw"], ["CA"], ["S4", "S4"]]


def _dtr_run(deadline, reselect=True):
    """The YJQJ SJ lead: the doomed throw first, CA then S4 S4, the points
    rule on (it rebuilds leaves under the stage's guard)."""
    rnd = yjqj(_DTR["plays"])
    worlds = draw(rnd, 0)
    bot = dtr_served(doomed_throw_reselect=reselect, tiebreak_points=True)
    winner, played = tail(bot, rnd, _DTR, worlds, check_budget=deadline,
                          admitted=_DTR_ADMITTED, means=[0.9, 0.5, 0.49], priors=[0.0] * 3)
    return bot, (winner, list(played), bot._tiebreak, bot._lead_tiebreak)


def _dtr_abandon(bot):
    record = bot._doomed_throw_record()
    if "doomed_throw_reselect_abandoned" not in record:
        return None
    assert record["doomed_throw_reselect_abandoned"] == "budget"
    assert record["doomed_throw_reselect_applied"] is False
    return "hard_budget", record["doomed_throw_reselect_abandon_error"]


CASES = [
    StageCase("adaptive_worlds", run=_aw_run,
              base=lambda: _aw_run(Deadline(), adaptive=False)[1],
              abandon=_aw_abandon, abandons_errors=True),
    StageCase("doomed_throw_reselect", run=_dtr_run,
              base=lambda: _dtr_run(Deadline(), reselect=False)[1],
              abandon=_dtr_abandon, abandons_errors=False),
]


@pytest.mark.parametrize("check", CONTRACT, ids=[c.__name__ for c in CONTRACT])
@pytest.mark.parametrize("case", CASES, ids=[c.name for c in CASES])
def test_optional_stage_contract(case, check, monkeypatch):
    check(case, monkeypatch)


# ------------------------------------------------------- the helper itself

class Owner:
    def __init__(self):
        self.a = {"x": [1, 2]}
        self.b = None


class Soft(Exception):
    pass


def _stage(owner, **kw):
    kw.setdefault("budget_errors", PVSearchBudgetExceeded)
    return OptionalStage(owner, ("a", "b"), **kw)


def test_no_deadline_means_no_guard_and_publish_runs_no_check():
    stage = _stage(Owner())
    assert stage.guard is None
    with stage:
        stage.publish()
    assert stage.abandoned is False and stage.reason is None


def test_snapshot_is_a_deep_copy_restored_exactly_on_abandon():
    owner = Owner()
    stage = _stage(owner, abandon_on=Exception)
    with stage:
        owner.a["x"].append(3)
        owner.b = "changed"
        raise ValueError("boom")
    assert stage.abandoned and (stage.reason, stage.error) == ("error", "ValueError")
    assert owner.a == {"x": [1, 2]} and owner.b is None


def test_first_latched_expiry_wins_and_a_swallowed_one_still_abandons():
    owner, deadline = Owner(), Deadline(at=1)
    stage = _stage(owner, hard_check=deadline)
    with stage:
        try:
            stage.guard()
        except PVSearchBudgetExceeded:
            pass                       # a nested rule absorbs it
        owner.b = "degraded"
        stage.publish()
    assert stage.abandoned and (stage.reason, stage.error) == \
        ("hard_budget", "PVSearchBudgetExceeded")
    assert owner.b is None and deadline.calls == 1   # publish made no further check


def test_soft_deadline_latches_after_the_hard_check():
    now = [0.0]
    deadline = Deadline()
    stage = _stage(Owner(), hard_check=deadline, soft_deadline=5.0,
                   clock=lambda: now[0], soft_error=Soft)
    with stage:
        stage.guard()
        now[0] = 5.0
        with pytest.raises(Soft):
            stage.guard()
        stage.publish()
    assert deadline.calls == 2 and (stage.reason, stage.error) == ("soft_budget", "Soft")


def test_publish_final_check_and_changed_false():
    stage = _stage(Owner(), hard_check=Deadline(at=1))
    with stage:
        stage.publish(changed=False)   # the base result unchanged: no final check
    assert not stage.abandoned
    stage = _stage(Owner(), hard_check=Deadline(at=1))
    with stage:
        stage.publish()
    assert stage.abandoned and stage.reason == "hard_budget"


def test_final_check_may_differ_from_the_guard():
    final = Deadline(at=1)
    stage = _stage(Owner(), hard_check=None, final_check=final)
    assert stage.guard is None
    with stage:
        stage.publish()
    assert final.calls == 1 and stage.abandoned


def test_leaving_without_publish_is_an_error():
    with pytest.raises(RuntimeError, match="without publish"):
        with _stage(Owner()):
            pass


def test_exceptions_outside_the_policy_propagate_without_restore():
    owner = Owner()
    stage = _stage(owner, abandon_on=PVSearchBudgetExceeded)
    with pytest.raises(ValueError):
        with stage:
            owner.b = "kept"
            raise ValueError
    assert owner.b == "kept" and not stage.abandoned


def test_base_exception_propagates_but_restore_always_runs():
    owner = Owner()
    stage = OptionalStage(owner, ("a", "b"), budget_errors=PVSearchBudgetExceeded,
                          restore_always=("b",))
    with pytest.raises(KeyboardInterrupt):
        with stage:
            owner.a, owner.b = "a-changed", "b-changed"
            raise KeyboardInterrupt
    assert owner.a == "a-changed" and owner.b is None and not stage.abandoned


def test_restore_always_on_success():
    owner = Owner()
    stage = OptionalStage(owner, ("a", "b"), budget_errors=PVSearchBudgetExceeded,
                          restore_always=("b",))
    with stage:
        owner.a, owner.b = "a-new", "b-new"
        stage.publish()
    assert owner.a == "a-new" and owner.b is None


def test_another_stages_trip_is_not_ours():
    outer, inner = _stage(Owner(), abandon_on=PVSearchBudgetExceeded), _stage(Owner())
    with pytest.raises(OptionalStageTripped):
        with outer:
            raise OptionalStageTripped(inner)
    assert not outer.abandoned


@pytest.mark.parametrize("kw", [{"abandon_on": BaseException},
                                {"abandon_on": KeyboardInterrupt},
                                {"soft_deadline": 1.0},
                                {"restore_always": ("c",)}])
def test_bad_configuration_is_refused(kw):
    with pytest.raises((TypeError, ValueError)):
        _stage(Owner(), **kw)


def test_entered_once():
    stage = _stage(Owner())
    with stage:
        stage.publish()
    with pytest.raises(RuntimeError):
        with stage:
            pass


def test_guard_passes_non_budget_errors_through_unlatched():
    def broken():
        raise RuntimeError
    stage = _stage(Owner(), hard_check=broken, abandon_on=PVSearchBudgetExceeded)
    with pytest.raises(RuntimeError):
        with stage:
            stage.guard()
    assert stage.tripped == []
