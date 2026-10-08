"""The reusable contract every OPTIONAL serving stage must pass
(`shengji.train.optional_stage`).

A new optional stage after a finalized base decision gets a `StageCase` (how
to run one decision through it with a controlled deadline, what the cached
base decision publishes, and how its record reports an abandon) and is added
to the parametrization in ``test_optional_stage_contract.py``; every check in
`CONTRACT` then runs against it:

* `check_inner_swallowed_expiry` -- the deadline expires inside a NESTED rule
  (`_select_rules`, entered inside the stage) that SWALLOWS the expiry and
  returns normally (the #936 / #946 defect class); the deadline is not expired
  for any later check, so only the latch can see it.  The stage must abandon
  (``hard_budget``) and publish exactly the base decision.
* `check_final_publish_expiry` -- the deadline expires at exactly the final
  hard check `OptionalStage.publish` makes; the same scenario with no expiry
  must publish something else (so the check is load-bearing).
* `check_error_inside_stage` -- a RuntimeError inside the stage: abandons
  (``error``) when the stage's policy abandons on errors, else propagates.
* `check_keyboard_interrupt_propagates` -- BaseException is never absorbed;
  the stage's ``restore_always`` records are still put back.
* every abandon restores the snapshotted rule records BYTE-EQUAL (pickle) to
  their state when the stage was entered.
"""
from __future__ import annotations

import inspect
import pickle
from dataclasses import dataclass
from typing import Any, Callable

import pytest

from shengji.train import optional_stage
from shengji.train.policy_value_search import PolicyValueBot
from shengji.train.pv_search_policy import PVSearchBudgetExceeded


class Deadline:
    """A controllable serving deadline: counts its calls; raises the serving
    budget exception at call ``at`` (one-shot) or while ``force`` is set."""

    def __init__(self, at=None):
        self.at, self.calls, self.force = at, 0, False

    def __call__(self):
        self.calls += 1
        if self.force or self.calls == self.at:
            raise PVSearchBudgetExceeded("pv-search serving budget expired")


@dataclass
class StageCase:
    """One optional stage under the contract.

    ``run(deadline)`` builds a FRESH bot, runs one decision whose stage is
    entered, and returns ``(bot, outcome)``; ``base()`` is the outcome the
    cached base decision publishes; ``abandon(bot)`` is ``(reason, error)``
    from the record, or None when the stage did not abandon;
    ``abandons_errors`` is the stage's policy for a non-budget Exception.
    """
    name: str
    run: Callable[[Deadline], tuple]
    base: Callable[[], Any]
    abandon: Callable[[Any], Any]
    abandons_errors: bool


class _Probe:
    """Instruments `OptionalStage` and `_select_rules` for one run."""

    def __init__(self, monkeypatch):
        self.depth, self.entries, self.exits, self.publish_calls = 0, [], [], []
        self.deadline = None
        self.inject = None          # called (with the rule's check) inside the stage
        probe = self
        cls = optional_stage.OptionalStage
        enter, exit_, publish = cls.__enter__, cls.__exit__, cls.publish

        def _state(stage):
            return {n: pickle.dumps(getattr(stage.owner, n, None))
                    for n in stage.snapshot}

        def __enter__(stage):
            probe.depth += 1
            probe.entries.append((stage, _state(stage)))
            return enter(stage)

        def __exit__(stage, *exc):
            try:
                return exit_(stage, *exc)
            finally:
                probe.depth -= 1
                probe.exits.append((stage, _state(stage)))

        def _publish(stage, changed=True):
            probe.publish_calls.append(probe.deadline.calls if probe.deadline else None)
            return publish(stage, changed)

        monkeypatch.setattr(cls, "__enter__", __enter__)
        monkeypatch.setattr(cls, "__exit__", __exit__)
        monkeypatch.setattr(cls, "publish", _publish)
        rules = PolicyValueBot._select_rules
        signature = inspect.signature(rules)

        def _select_rules(bot, *a, **kw):
            if probe.depth and probe.inject is not None:
                inject, probe.inject = probe.inject, None
                check = signature.bind(bot, *a, **kw).arguments.get("check_budget")
                assert check is not None, "the nested rule must receive the stage's guard"
                inject(check)
            return rules(bot, *a, **kw)
        monkeypatch.setattr(PolicyValueBot, "_select_rules", _select_rules)

    def outer(self):
        assert self.entries, "the scenario never entered an optional stage"
        stage, entry = self.entries[0]
        exit_state = next(s for st, s in self.exits if st is stage)
        return stage, entry, exit_state


def _assert_abandoned_to_base(case, probe, bot, outcome, reason, error):
    assert case.abandon(bot) == (reason, error)
    assert outcome == case.base()
    stage, entry, exit_state = probe.outer()
    assert stage.abandoned is True
    assert exit_state == entry, "an abandon must restore the rule records byte-equal"


def check_inner_swallowed_expiry(case, monkeypatch):
    probe = _Probe(monkeypatch)
    deadline = probe.deadline = Deadline()

    def swallow(check):
        deadline.force = True
        try:
            check()
        except PVSearchBudgetExceeded:
            pass                     # the nested rule absorbs it and carries on
        finally:
            deadline.force = False
    probe.inject = swallow
    bot, outcome = case.run(deadline)
    assert probe.inject is None, "the nested rule never ran inside the stage"
    _assert_abandoned_to_base(case, probe, bot, outcome, "hard_budget",
                              PVSearchBudgetExceeded.__name__)


def check_final_publish_expiry(case, monkeypatch):
    probe = _Probe(monkeypatch)
    deadline = probe.deadline = Deadline()
    _, published = case.run(deadline)
    assert published != case.base(), "the scenario must publish a replacement"
    assert probe.publish_calls, "the stage never reached publish()"
    final = probe.publish_calls[0] + 1   # the final hard check is publish's next call
    monkeypatch.undo()
    probe = _Probe(monkeypatch)
    deadline = probe.deadline = Deadline(at=final)
    bot, outcome = case.run(deadline)
    assert deadline.calls == final and probe.publish_calls == [final - 1]
    _assert_abandoned_to_base(case, probe, bot, outcome, "hard_budget",
                              PVSearchBudgetExceeded.__name__)


def check_error_inside_stage(case, monkeypatch):
    probe = _Probe(monkeypatch)
    probe.deadline = Deadline()

    def fail(check):
        raise RuntimeError("an error inside the optional stage")
    probe.inject = fail
    if not case.abandons_errors:
        with pytest.raises(RuntimeError):
            case.run(probe.deadline)
        return
    bot, outcome = case.run(probe.deadline)
    _assert_abandoned_to_base(case, probe, bot, outcome, "error", "RuntimeError")


def check_keyboard_interrupt_propagates(case, monkeypatch):
    probe = _Probe(monkeypatch)
    probe.deadline = Deadline()

    def interrupt(check):
        raise KeyboardInterrupt
    probe.inject = interrupt
    with pytest.raises(KeyboardInterrupt):
        case.run(probe.deadline)
    stage, entry, exit_state = probe.outer()
    assert stage.abandoned is False
    for name in stage.restore_always:
        assert exit_state[name] == entry[name]


CONTRACT = (check_inner_swallowed_expiry, check_final_publish_expiry,
            check_error_inside_stage, check_keyboard_interrupt_propagates)
