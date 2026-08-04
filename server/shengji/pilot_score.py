"""Scoring for the lead-ballot pilot: per-world returns, oracle, regret.

Three things happen here, in an order that matters:

  1. **Score** an action on a fold, keeping the PER-WORLD return vector rather
     than a mean. Means alone cannot express that two arms were measured on
     the same worlds, and the pilot's whole comparison is paired.
  2. **Freeze an oracle reference** on the ORACLE fold — the argmax over the
     union of every arm's ballot. It is chosen there and never re-chosen.
  3. **Report** each arm's chosen action and the frozen reference on the
     REPORT fold, which neither proposal nor oracle selection has touched.

The separation is the point. An argmax is biased upward by exactly the noise
it selected on, so an oracle chosen and scored on the same worlds would flatter
itself, and an arm scored on the worlds that chose its action would flatter
itself the same way. Regret measured across folds is unbiased for that; regret
measured within one fold is not.

`BALLOT_PLAN` asks for per-world returns or covariance, "means alone are
insufficient". Returns are kept, so covariance is recoverable exactly rather
than approximated.
"""
from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field


@dataclass
class Scored:
    """One action's return on every world of one fold, in fold order.

    Carries the IDENTITY of what it was scored on. Without it `paired_diff`
    could only compare lengths, and two unrelated equal-length vectors paired
    happily into a plausible-looking difference (Codex reproduced this).
    """

    action: tuple
    returns: list = field(default_factory=list)
    state_key: str = ""
    fold: str = ""
    world_keys: tuple = ()

    @property
    def mean(self) -> float:
        if not self.returns:
            raise ValueError(
                f"mean of an empty fold ({self.state_key}/{self.fold}): an "
                f"empty fold silently scored 0.0, which made an empty oracle "
                f"fold select its first action and an empty report fold return "
                f"zero regret.")
        return sum(self.returns) / len(self.returns)

    def paired_diff(self, other: "Scored") -> list:
        """Per-world difference. Requires the SAME worlds, in the same order."""
        if (self.state_key, self.fold) != (other.state_key, other.fold):
            raise ValueError(
                f"cannot pair across {self.state_key}/{self.fold} and "
                f"{other.state_key}/{other.fold}")
        if self.world_keys != other.world_keys:
            raise ValueError(
                "cannot pair: the two scores were taken on different worlds "
                "or in a different order. Equal length is not the same fold.")
        return [a - b for a, b in zip(self.returns, other.returns)]


def score_action(bot, rnd, seat, worlds, action, *, state_key="", fold="",
                 expect=None) -> Scored:
    """Roll `action` out on every world of a fold, keeping each return.

    One rollout per world, from the acting SEAT's perspective, with the sign
    convention the evaluator uses (attacker-positive, flipped for the banker
    team) so a number here means the same thing as a number there.
    """
    if expect is not None and len(worlds) != expect:
        raise ValueError(
            f"{state_key}/{fold}: {len(worlds)} worlds, preregistered {expect}. "
            f"A short fold must fail closed — silently scoring fewer worlds "
            f"changes the estimator without changing the number.")
    if not worlds:
        raise ValueError(f"{state_key}/{fold}: empty fold")
    from .pilot_folds import world_key
    out = Scored(action=tuple(sorted(action)), state_key=state_key, fold=fold,
                 world_keys=tuple(world_key(h, e) for h, e in worlds))
    i_attack = rnd.is_attacker(seat)
    for hands, buried in worlds:
        raw = bot._rollout(rnd, seat, hands, buried, list(action))
        val = bot._score(raw)
        out.returns.append(val if i_attack else -val)
    return out


def oracle_reference(bot, rnd, seat, oracle_worlds, union_actions, *,
                     state_key="", expect=None) -> Scored:
    """The reference action: argmax over the union ballot, on the ORACLE fold.

    Chosen here and FROZEN. Re-choosing it on the report fold would make the
    reference the maximum of the same noise the arms are measured against, and
    every arm's regret would inherit that bias.
    """
    if not union_actions:
        raise ValueError("empty union ballot: nothing to select a reference from")
    best = None
    for a in union_actions:
        s = score_action(bot, rnd, seat, oracle_worlds, a,
                         state_key=state_key, fold="oracle", expect=expect)
        if best is None or s.mean > best.mean:
            best = s
    return best


def report_regret(bot, rnd, seat, report_worlds, chosen, reference_action, *,
                  state_key="", expect=None):
    """Paired regret of `chosen` against the frozen reference, on REPORT worlds.

    Positive regret means the arm's action did worse than the reference. Both
    are re-scored here: the oracle's own fold estimate is a selected maximum
    and must never be reused as the reference's value.
    """
    a = score_action(bot, rnd, seat, report_worlds, chosen,
                     state_key=state_key, fold="report", expect=expect)
    r = score_action(bot, rnd, seat, report_worlds, reference_action,
                     state_key=state_key, fold="report", expect=expect)
    diffs = r.paired_diff(a)              # reference minus arm
    n = len(diffs)
    mean = sum(diffs) / n if n else 0.0
    if n > 1:
        var = sum((d - mean) ** 2 for d in diffs) / (n - 1)
        half = 1.96 * math.sqrt(var / n)
    else:
        half = float("inf")
    # `half` is WITHIN-STATE Monte Carlo uncertainty only. The experiment
    # interval must come from one paired mean per state, clustered by deal —
    # treating states x worlds as independent observations would understate it
    # by roughly sqrt(n_worlds) (Codex).
    return {"regret": mean, "within_state_half": half, "n_worlds": n,
            "arm_mean": a.mean, "reference_mean": r.mean,
            "arm_returns": a.returns, "reference_returns": r.returns}


def union_ballot(ballots: dict) -> list:
    """Every action any arm proposed, deduped, in deterministic order.

    The oracle must choose from the union — a reference drawn from one arm's
    ballot would hand that arm zero regret by construction.
    """
    seen, out = set(), []
    for arm in sorted(ballots):
        for a in ballots[arm]:
            key = tuple(sorted(a))
            if key not in seen:
                seen.add(key)
                out.append(list(key))
    return out
