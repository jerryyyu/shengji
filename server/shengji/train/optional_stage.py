"""One OPTIONAL serving stage after a FINALIZED base decision.

Every optional pv-search stage that runs after the base decision is complete
(the 4W re-selection of ``adaptive_worlds``, #936; the masked re-selection of
``doomed_throw_reselect``, #946) has the same contract, and both shipped with
the same defect in it, caught only in review: an expiry that a NESTED rule
absorbed (`_select_by_points` catches the deadline and returns its argmax) let
the stage publish a degraded result after the deadline, or an extra-stage
overshoot destroyed the completed base decision.  This module is the one
implementation of that contract:

1. the caller has FINALIZED and cached its base result before entering;
2. on entry the named rule-record attributes of ``owner`` are snapshotted
   (``copy.deepcopy``);
3. inside the stage every deadline check goes through ``stage.guard``: the
   hard check first (``hard_check``; a ``budget_errors`` exception is LATCHED
   before it propagates, so a rule that swallows it cannot hide it), then the
   optional soft deadline (``clock() >= soft_deadline`` latches and raises
   ``soft_error``).  ``guard`` is None when there is neither, so nested rules
   take their unguarded path exactly as before;
4. ``stage.raise_if_tripped()`` turns a latched expiry into an abandon at any
   point the caller chooses (after each nested rule that may absorb one);
5. ``stage.publish()`` is MANDATORY before leaving the block normally: it
   raises a latched expiry, then runs the final hard check (latched as well).
   ``publish(changed=False)`` skips the final hard check when the stage
   publishes the base result unchanged (nothing computed past a deadline
   replaces anything).  Leaving the block without ``publish`` is a programming
   error (RuntimeError);
6. an exception in ``abandon_on`` (or a latched expiry) ABANDONS the stage: the
   snapshot is restored exactly, ``stage.abandoned`` is True, ``stage.reason``
   is ``"soft_budget"`` / ``"hard_budget"`` / ``"error"`` and ``stage.error``
   the exception class name (the FIRST latched expiry wins over whatever was
   raised later), and the exception is suppressed -- the caller returns its
   cached base result.  Any other exception propagates (without the snapshot
   restore), and ``BaseException`` always propagates;
7. ``restore_always`` names are restored from the snapshot on EVERY exit
   (success, abandon, propagation), for records the stage must never leave
   describing its own work (the sampler record of extra draws).

Any NEW optional serving stage must use `OptionalStage`, and must be added to
the contract template in ``tests/optional_stage_contract.py`` (expiry inside a
swallowing inner rule, expiry at the final publish check, an error inside the
stage, KeyboardInterrupt propagation, records restored byte-equal).
"""
from __future__ import annotations

import copy

REASONS = ("soft_budget", "hard_budget", "error")


class OptionalStageTripped(Exception):
    """A latched expiry surfaced by `OptionalStage.raise_if_tripped` (internal;
    always handled by the stage that raised it)."""

    def __init__(self, stage):
        super().__init__("optional stage abandoned on a latched expiry")
        self.stage = stage


class OptionalStage:
    """Context manager for one optional stage (module docstring).

    ``owner``: the object whose ``state_names`` attributes are snapshotted.
    ``hard_check``: the serving deadline, or None.  ``budget_errors``: the
    exception class(es) a hard expiry raises (latched).  ``soft_deadline`` and
    ``clock``: the optional soft deadline (``clock() >= soft_deadline``), raising
    ``soft_error``.  ``final_check``: the hard check `publish` runs (default
    ``hard_check``).  ``abandon_on``: the exception class(es) that abandon the
    stage instead of propagating (each an ``Exception`` subclass).
    """

    def __init__(self, owner, state_names, *, hard_check=None, budget_errors,
                 soft_deadline=None, clock=None, soft_error=None, final_check=None,
                 abandon_on=Exception, restore_always=()):
        abandon = abandon_on if isinstance(abandon_on, tuple) else (abandon_on,)
        if not all(isinstance(c, type) and issubclass(c, Exception) for c in abandon):
            raise TypeError("abandon_on must be Exception subclasses (BaseException propagates)")
        if soft_deadline is not None and (clock is None or soft_error is None):
            raise TypeError("a soft deadline needs a clock and a soft_error")
        unknown = set(restore_always) - set(state_names)
        if unknown:
            raise ValueError(f"restore_always names outside the snapshot: {sorted(unknown)}")
        self.owner = owner
        self.hard_check = hard_check
        self.budget_errors = budget_errors
        self.soft_deadline = soft_deadline
        self.clock = clock
        self.soft_error = soft_error
        self.final_check = hard_check if final_check is None else final_check
        self.abandon_on = abandon
        self.restore_always = tuple(restore_always)
        self.snapshot = {name: copy.deepcopy(getattr(owner, name, None))
                         for name in state_names}
        self.tripped = []          # (reason, error class name), first one wins
        self.abandoned = False
        self.reason = self.error = None
        self._published = False
        self._entered = False
        self.guard = self._guard if (hard_check is not None or soft_deadline is not None) \
            else None

    # -- the latching deadline -------------------------------------------------

    def _latched_hard(self, check):
        try:
            check()
        except self.budget_errors as exc:
            # a nested rule may catch this and publish a degraded result
            self.tripped.append(("hard_budget", type(exc).__name__))
            raise

    def _guard(self):
        if self.hard_check is not None:
            self._latched_hard(self.hard_check)
        if self.soft_deadline is not None and self.clock() >= self.soft_deadline:
            self.tripped.append(("soft_budget", self.soft_error.__name__))
            raise self.soft_error("optional stage soft deadline")

    def raise_if_tripped(self):
        """Abandon now if any expiry was latched (even one a rule absorbed)."""
        if self.tripped:
            raise OptionalStageTripped(self)

    def publish(self, changed=True):
        """The mandatory last step: a latched expiry abandons, then (when the
        stage replaces the base result) the final hard check runs."""
        self.raise_if_tripped()
        if changed and self.final_check is not None:
            self._latched_hard(self.final_check)
        self._published = True

    # -- the transaction -------------------------------------------------------

    def restore(self):
        """Put the snapshot back (the abandon path; a caller may also use it
        when the stage decides to publish the base result's records)."""
        for name, value in self.snapshot.items():
            setattr(self.owner, name, value)

    def __enter__(self):
        if self._entered:
            raise RuntimeError("an OptionalStage is entered once")
        self._entered = True
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if exc_type is None:
                if not self._published:
                    raise RuntimeError("optional stage left without publish()")
                return False
            ours = isinstance(exc, OptionalStageTripped) and exc.stage is self
            if not ours and not issubclass(exc_type, self.abandon_on):
                return False   # propagates (BaseException always)
            if self.tripped:
                self.reason, self.error = self.tripped[0]
            elif isinstance(exc, self.budget_errors):
                self.reason, self.error = "hard_budget", exc_type.__name__
            else:
                self.reason, self.error = "error", exc_type.__name__
            self.restore()
            self.abandoned = True
            return True
        finally:
            for name in self.restore_always:
                setattr(self.owner, name, self.snapshot[name])
