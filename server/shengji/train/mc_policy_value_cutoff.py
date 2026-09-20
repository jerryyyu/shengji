"""DEV MC-LCB with a bounded actor-public continuation and CWV leaves.

This module is intentionally not registered as a gameplay policy.  The root
search remains the matched ``mc-s0-report-lcb`` search; only the continuation
of each sampled root candidate changes.
"""
from __future__ import annotations

import copy
import math

import numpy as np

from ..ai.heuristic import HeuristicBot
from ..ai.mcbot import Trick, TrickPlay
from ..teacher_v1 import attacker_level_utility
from .mc_policy_value_rollout import MCPolicyValueRollout
from .policy_value_search import PolicyValueBot


class MCPolicyValueCutoff(MCPolicyValueRollout):
    """Matched MC-LCB whose rollout leaf is a fixed-trick CWV value.

    ``_rollout`` always returns an attacker-perspective level.  The inherited
    MC decision loop then applies its existing defender sign flip exactly once
    before comparing candidates.
    """

    POINT_SHY_EPS = 0.0
    MARGIN = 0.0
    LEAD_MARGIN = None

    def __init__(self, continuation: PolicyValueBot, *, evaluator,
                 seed=0, cutoff_tricks=1, learned_continuation=True):
        if type(learned_continuation) is not bool:
            raise ValueError("learned_continuation must be a bool")
        if cutoff_tricks is not None and (
                type(cutoff_tricks) is not int or not 1 <= cutoff_tricks <= 64):
            raise ValueError("cutoff_tricks must be None or an integer in [1,64]")
        if evaluator is None:
            raise ValueError("value evaluator required")
        super().__init__(continuation, seed=seed)
        self.evaluator = evaluator
        self.cutoff_tricks = cutoff_tricks
        self.learned_continuation = learned_continuation
        # Keep PublicPVContinuation as the learned path's public-coordinate
        # actor.  The heuristic control gets its own actor and never enters
        # the continuation model pipeline.
        self._heuristic_continuation = HeuristicBot()
        self.leaf_rollouts = self._empty_leaf_rollouts()

    @staticmethod
    def _empty_leaf_rollouts():
        return {
            "started": 0,
            "completed": 0,
            "predicted": 0,
            "terminal": 0,
            "continuation_plies": 0,
        }

    def decide_play(self, rnd, seat):
        # MCPolicyValueRollout resets the parent phase counters and learned
        # actor telemetry.  Reset the cutoff counters alongside those state
        # machines, once per outer decision rather than once per rollout.
        self.leaf_rollouts = self._empty_leaf_rollouts()
        return super().decide_play(rnd, seat)

    def _score(self, attacker_value):
        """Validate and preserve attacker-signed level units."""
        try:
            value = float(attacker_value)
        except (TypeError, ValueError):
            raise ValueError("rollout value must be finite") from None
        if not math.isfinite(value):
            raise ValueError("rollout value must be finite")
        return value

    def _terminal(self, clone):
        return self._score(attacker_level_utility(clone.attacker_points))

    def _value_leaf(self, clone, root_seat):
        scores = np.asarray(self.evaluator.score([clone], root_seat),
                            dtype=np.float64)
        if scores.shape != (1,) or not np.isfinite(scores).all():
            raise ValueError(
                "value evaluator requires one finite root-team score per leaf")
        # CWV is signed for the root seat's team; MC's outer loop expects the
        # attacker perspective and performs the defender flip itself.
        value = float(scores[0])
        if not clone.is_attacker(root_seat):
            value = -value
        return self._score(value)

    def _rollout(self, rnd, seat, sampled, buried, candidate, *,
                 exact_session=None, _prepared_report=None):
        """Run one compatible determinized rollout to a terminal/CWV leaf."""
        if exact_session is not None:
            raise ValueError("cutoff rollout does not support exact endgame sessions")
        phase = self.phase_rollouts[self.rollout_phase]
        phase["started"] += 1
        self.leaf_rollouts["started"] += 1
        if self.learned_continuation:
            # Match MCPolicyValueRollout's per-rollout public RNG reset.
            self.rollout_policy.begin_rollout()

        clone = copy.copy(rnd)
        # Keep this setup byte-compatible with MCBot._rollout.  In particular,
        # never reuse live or sampled mutable hand lists in the clone.
        if _prepared_report is not None:
            # The cutoff experiment does not prepare report worlds itself.  A
            # caller supplying one must receive the same strict contract as
            # the native rollout rather than a hidden fallback.
            from ..ai.mcbot import _PreparedReportWorld, DeterminizationContractError
            if not isinstance(_prepared_report, _PreparedReportWorld):
                raise DeterminizationContractError(
                    "prepared report world has the wrong type")
            clone.hands = [list(hand) for hand in _prepared_report.hands]
            clone.buried = list(_prepared_report.buried)
        else:
            clone.hands = self._complete_determinized_hands(
                rnd, seat, sampled, buried=buried)
            clone.buried = sorted(buried)
        assert rnd.trick is not None
        clone.trick = Trick(
            leader=rnd.trick.leader,
            plays=[TrickPlay(p.seat, list(p.cards))
                   for p in rnd.trick.plays])
        clone.history = list(rnd.history)
        clone.last_trick = rnd.last_trick
        clone.message = None
        clone._trusted_rollout = True
        clone._determinized_world = True

        clone.play(seat, list(candidate))
        horizon = (None if self.cutoff_tricks is None else
                   len(rnd.history) + self.cutoff_tricks)
        continuation = (self.rollout_policy if self.learned_continuation
                        else self._heuristic_continuation)
        while clone.phase == "play":
            # A terminal result always wins over a model evaluation, including
            # a candidate that completed the final trick at the horizon.
            if horizon is not None and len(clone.history) >= horizon:
                value = self._value_leaf(clone, seat)
                self.leaf_rollouts["completed"] += 1
                self.leaf_rollouts["predicted"] += 1
                phase["completed"] += 1
                return value
            actor = clone.turn
            assert actor is not None
            cards = continuation.decide_play(clone, actor)
            clone.play(actor, list(cards))
            # This is cumulative work, so retain successful continuation plies
            # even if the eventual leaf evaluator refuses the leaf.
            self.leaf_rollouts["continuation_plies"] += 1

        # The loop exits this way only after a terminal play.  The explicit
        # check is kept here so terminal precedence remains obvious if the
        # engine gains another non-play phase later.
        if clone.phase != "round_end":
            raise RuntimeError(f"rollout stopped in unexpected phase {clone.phase!r}")
        value = self._terminal(clone)
        self.leaf_rollouts["completed"] += 1
        self.leaf_rollouts["terminal"] += 1
        phase["completed"] += 1
        return value


__all__ = ["MCPolicyValueCutoff"]
