"""DEV-only shortlist continuations with one privileged extra trick.

The root candidate population, world streams, and MC-LCB decision boundary are
owned by :class:`CWVShortlistBot`.  This arm only changes the value returned by
the inherited production selection/report hooks for a bounded prefix of their
sampled worlds.  The inner choices are made on complete sampled worlds and are
therefore simulation machinery, never a policy that can be exposed to a live
actor.
"""
from __future__ import annotations

import copy
import hashlib
import random
from typing import Any

import numpy as np

from ..ai.cwv_policy import afterstate
from ..ai.cwv_successor_reuse import WorldSuccessorCache
from ..ai.heuristic import HeuristicBot
from .cwv_shortlist import CWVShortlistBot
from .net_rollout import MCNetRolloutSearch
from ..harvest.legal import enumerate_legal


class DoubleShortlistError(ValueError):
    """The bounded continuation cannot honour its simulation contract."""


class CWVDoubleShortlistBot(CWVShortlistBot):
    """Full-legal root shortlist plus one inner, five-action shortlist.

    The first bounded fraction of worlds in each independent production
    selection/report call are guided.  The configured ``inner_worlds`` is the
    numerator and the production selection-world count is the denominator;
    every other world is the inherited heuristic rollout.
    """

    NET_STAGE = "all"
    ADAPTIVE_ALLOCATION = True
    DOUBLE_RECORD_SCHEMA = "cwv-double-shortlist-v2"
    GUIDANCE_MODE = "selection-fraction-ceil-v2"

    # Reuse the existing uniform-selection and paired-report adapters. They
    # draw production worlds/moments and invoke this class's lockstep hook.
    _report_fold_gap = MCNetRolloutSearch._report_fold_gap
    _decide_adaptive = MCNetRolloutSearch._decide_adaptive
    _report_rng = staticmethod(MCNetRolloutSearch._report_rng)

    def __init__(self, evaluator, *, seed=0, config=None,
                 reuse_successors=False, inner_mode="learned",
                 inner_worlds=4, inner_alternatives=4,
                 inner_batch_size=128):
        super().__init__(evaluator, seed=seed, config=config,
                         reuse_successors=reuse_successors)
        if inner_mode not in {"learned", "uniform", "heuristic"}:
            raise DoubleShortlistError(
                "inner_mode must be one of 'learned', 'uniform', 'heuristic'")
        for name, value in (("inner_worlds", inner_worlds),
                            ("inner_alternatives", inner_alternatives),
                            ("inner_batch_size", inner_batch_size)):
            if type(value) is not int or value < (0 if name == "inner_alternatives" else 1):
                raise DoubleShortlistError(f"{name} must be a positive integer"
                                            if name != "inner_alternatives"
                                            else "inner_alternatives must be non-negative")
        if self.EXACT_ENDGAME:
            raise DoubleShortlistError(
                "CWVDoubleShortlistBot does not support EXACT_ENDGAME yet")
        if inner_mode == "learned" and not callable(getattr(evaluator, "score_many", None)):
            raise DoubleShortlistError(
                "learned inner shortlist requires evaluator.score_many(positions, seats)")
        self.inner_mode = inner_mode
        self.inner_worlds = inner_worlds
        self.inner_alternatives = inner_alternatives
        self.inner_batch_size = inner_batch_size
        self.last_double_shortlist: dict[str, Any] | None = None
        self._double_stage_records: list[dict[str, Any]] = []
        self.double_shortlist_counts = {
            "calls": 0, "guided_worlds": 0, "inner_actions": 0,
            "inner_finalist_actions": 0, "inner_net_rows": 0,
            "inner_batches": 0, "inner_cross_parent_batches": 0,
            "inner_full_rollouts": 0,
        }

    def _guidance_counts(self, actual_worlds: int) -> tuple[int, int, int]:
        """Return ``(numerator, denominator, target guided worlds)``.

        ``inner_worlds`` is deliberately the numerator of a fraction whose
        denominator is the configured production selection-world count.  The
        same fraction therefore applies to independent selection and report
        batches, including short batches and a saturated numerator.
        """
        denominator = int(self.N_DETERMINIZATIONS)
        if denominator < 1:
            raise DoubleShortlistError(
                "N_DETERMINIZATIONS must be positive for double-shortlist guidance")
        numerator = min(self.inner_worlds, denominator)
        if self.inner_mode == "heuristic" or actual_worlds <= 0:
            return numerator, denominator, 0
        target = min(actual_worlds,
                     (actual_worlds * numerator + denominator - 1) // denominator)
        return numerator, denominator, target

    # -------------------------------------------------------------- records
    def _aggregate_record(self) -> dict[str, Any] | None:
        if not self._double_stage_records:
            return None
        rows = self._double_stage_records
        return {
            "schema": self.DOUBLE_RECORD_SCHEMA,
            "guidance": self.GUIDANCE_MODE,
            "mode": self.inner_mode,
            "inner_selection_worlds": self.inner_worlds,
            "guidance_numerator": rows[0]["guidance_numerator"],
            "guidance_denominator": rows[0]["guidance_denominator"],
            "target_inner_worlds": sum(r["target_inner_worlds"] for r in rows),
            "inner_alternatives": self.inner_alternatives,
            "inner_batch_size": self.inner_batch_size,
            "actual_inner_worlds": sum(r["actual_inner_worlds"] for r in rows),
            "inner_actions": sum(r["inner_actions"] for r in rows),
            "inner_finalist_actions": sum(r["inner_finalist_actions"] for r in rows),
            "inner_net_rows": sum(r["inner_net_rows"] for r in rows),
            "inner_batches": sum(r["inner_batches"] for r in rows),
            "inner_cross_parent_batches": sum(
                r["inner_cross_parent_batches"] for r in rows),
            "inner_full_rollouts": sum(r["inner_full_rollouts"] for r in rows),
            "one_extra_trick_horizon": rows[0]["one_extra_trick_horizon"],
            "stages": [copy.deepcopy(r) for r in rows],
        }

    def decide_play(self, rnd, seat):
        self._double_stage_records = []
        self.last_double_shortlist = None
        played = super().decide_play(rnd, seat)
        detail = self._aggregate_record()
        if detail is not None:
            self.last_double_shortlist = detail
            if self.last_decision_record is not None:
                self.last_decision_record["cwv_double_shortlist"] = detail
                # Keep production's fixed budget fields intact while exposing
                # the extra, real finalist work separately.
                self.last_decision_record["work"]["inner_rollouts"] = detail[
                    "inner_full_rollouts"]
                self.last_decision_record["work"]["total_rollouts_including_inner"] = (
                    self.last_decision_record["work"]["total_rollouts"]
                    + detail["inner_full_rollouts"])
        return played

    # ------------------------------------------------------------- utilities
    @staticmethod
    def _state_identity(state, branch: tuple[int, int, int]) -> str:
        """Stable, local-only identity for uniform inner alternatives."""
        trick = None if state.trick is None else {
            "leader": state.trick.leader,
            "plays": [(p.seat, tuple(sorted(p.cards))) for p in state.trick.plays],
        }
        history = [[(p.seat, tuple(sorted(p.cards))) for p in t.plays]
                   for t in state.history]
        payload = (tuple(tuple(sorted(h)) for h in state.hands),
                   tuple(sorted(state.buried)), tuple(history), trick,
                   state.turn, state.attacker_points, branch)
        return hashlib.sha256(repr(payload).encode()).hexdigest()

    @staticmethod
    def _copy_state(state):
        # Round has several mutable caches used by the trusted rollout path;
        # deepcopy keeps a finalist leaf completely independent of its parent.
        return copy.deepcopy(state)

    def _finish_heuristic(self, state) -> float:
        while state.phase == "play":
            mover = state.turn
            assert mover is not None
            state.play(mover, list(self.rollout_policy.decide_play(state, mover)))
        return float(state.attacker_points)

    def _root_leaf(self, rnd, seat, hands, buried, candidate, cache=None):
        if cache is not None:
            # WorldSuccessorCache's value is shared by equivalent accepted
            # actions.  Never let a subsequent inner choice mutate that leaf.
            return self._copy_state(cache.leaf(candidate))
        return afterstate(rnd, seat, hands, buried, candidate,
                          finish_trick=True, policy=self.rollout_policy)

    def _uniform_finalists(self, state, mover, legal, branch):
        incumbent = tuple(sorted(self.rollout_policy.decide_play(state, mover)))
        keys = [tuple(sorted(action)) for action in legal.actions]
        if incumbent not in keys:
            raise DoubleShortlistError("heuristic incumbent missing from inner legal set")
        alternatives = [key for key in keys if key != incumbent]
        seed = int(self._state_identity(state, branch), 16)
        chosen = random.Random(seed).sample(
            alternatives, min(len(alternatives), self.inner_alternatives))
        return [incumbent, *chosen]

    def _rank_inner_many(self, parents, stats):
        """Rank all current movers, sharing one bounded evaluator queue.

        Parent legal sets are enumerated one at a time.  Only the current
        batch and each parent's incumbent/top alternatives are retained, so a
        wide world/candidate product never becomes a position tensor.
        """
        batch_positions: list[Any] = []
        batch_owners: list[int] = []
        batch_actions: list[tuple[str, ...]] = []
        records = []

        def consider(owner, action, value, leaf):
            record = records[owner]
            keep = record["keep"]
            keep[action] = (float(value), leaf)
            incumbent = record["incumbent"]
            ordered = sorted(keep, key=lambda key: (-keep[key][0], key))
            allowed = [incumbent] + [key for key in ordered
                                      if key != incumbent][:self.inner_alternatives]
            allowed = set(allowed)
            for key in list(keep):
                if key not in allowed:
                    del keep[key]

        def flush():
            if not batch_positions:
                return
            owners = list(batch_owners)
            values = np.asarray(self.evaluator.score_many(
                batch_positions,
                [records[owner]["mover"] for owner in owners]), dtype=np.float64)
            if values.shape != (len(batch_positions),) or not np.isfinite(values).all():
                raise DoubleShortlistError(
                    "inner evaluator returned a misaligned or non-finite batch")
            stats["inner_net_rows"] += len(batch_positions)
            stats["inner_batches"] += 1
            stats.setdefault("inner_cross_parent_batches", 0)
            if len(set(owners)) > 1:
                stats["inner_cross_parent_batches"] += 1
            for action, owner, position, value in zip(
                    batch_actions, owners, batch_positions, values):
                consider(owner, action, float(value), position)
            batch_positions.clear()
            batch_owners.clear()
            batch_actions.clear()

        # Stream one parent's legal actions at a time.  A partial tail is
        # intentionally allowed to share the next parent's rows.  ``legal``
        # is local to this loop, so completed parents do not retain their full
        # action lists while later parents are enumerated.
        for owner, parent in enumerate(parents):
            state, mover, branch = parent["state"], parent["mover"], parent["branch"]
            incumbent = tuple(sorted(self.rollout_policy.decide_play(state, mover)))
            legal = parent.get("legal") or enumerate_legal(
                state, mover, cap=None, must_include=[incumbent])
            actions = [tuple(sorted(action)) for action in legal.actions]
            if not actions or incumbent not in actions:
                raise DoubleShortlistError(
                    "inner exhaustive legal population lost incumbent")
            stats["inner_actions"] += len(actions)
            record = {"incumbent": incumbent,
                      "keep": {incumbent: (float("-inf"), None)},
                      "state": state, "mover": mover, "branch": branch}
            records.append(record)
            if self.inner_mode == "heuristic":
                del actions, legal
                continue
            if self.inner_mode == "uniform":
                record["finalists"] = self._uniform_finalists(
                    state, mover, legal, branch)
                record["leaves"] = {}
                del actions, legal
                continue
            for action in actions:
                leaf = afterstate(record["state"], record["mover"],
                                  record["state"].hands,
                                  record["state"].buried, action,
                                  finish_trick=True, policy=self.rollout_policy)
                batch_positions.append(leaf)
                batch_owners.append(owner)
                batch_actions.append(action)
                if len(batch_positions) >= self.inner_batch_size:
                    flush()
            del actions, legal
        flush()
        if self.inner_mode == "heuristic":
            return [([r["incumbent"]], {}) for r in records]
        if self.inner_mode == "uniform":
            return [(r["finalists"], r["leaves"]) for r in records]
        result = []
        for record in records:
            keep = record["keep"]
            incumbent = record["incumbent"]
            if keep[incumbent][1] is None:
                raise DoubleShortlistError("inner incumbent was not scored")
            ordered = sorted(keep, key=lambda key: (-keep[key][0], key))
            finalists = [incumbent] + [key for key in ordered if key != incumbent]
            leaves = {key: keep[key][1] for key in finalists}
            result.append((finalists, leaves))
        return result

    def _rank_inner(self, state, mover, branch, stats, legal=None):
        """Single-parent compatibility wrapper used by focused witnesses."""
        parent = {"state": state, "mover": mover, "branch": branch}
        if legal is not None:
            parent["legal"] = legal
        return self._rank_inner_many([parent], stats)[0]

    def _guided_many(self, branches, stats):
        active = [branch for branch in branches
                  if branch["state"].phase == "play" and
                  len(branch["state"].history) < branch["horizon"]]
        while active:
            ranked = (self._rank_inner(active[0]["state"], active[0]["mover"],
                                       active[0]["branch"], stats)
                      if len(active) == 1 else self._rank_inner_many(active, stats))
            for parent, (finalists, ranked_leaves) in zip(active, ranked if len(active) > 1 else [ranked]):
                state, mover = parent["state"], parent["mover"]
                stats["inner_finalist_actions"] += len(finalists)
                leaves = ranked_leaves
                if self.inner_mode != "learned":
                    leaves = {action: afterstate(
                        state, mover, state.hands, state.buried, action,
                        finish_trick=True, policy=self.rollout_policy)
                              for action in finalists}
                best_action, best_value = finalists[0], None
                for action in finalists:
                    value = self._score(self._finish_heuristic(
                        self._copy_state(leaves[action])))
                    if not state.is_attacker(mover):
                        value = -value
                    if best_value is None or value > best_value:
                        best_action, best_value = action, value
                    stats["inner_full_rollouts"] += 1
                parent["state"] = afterstate(
                    state, mover, state.hands, state.buried, best_action,
                    finish_trick=False)
                parent["mover"] = parent["state"].turn
            active = [branch for branch in active
                      if branch["state"].phase == "play" and
                      len(branch["state"].history) < branch["horizon"]]
        return [self._finish_heuristic(branch["state"]) for branch in branches]

    def _guided_root_value(self, root_leaf, branch, stats):
        if root_leaf.phase == "round_end":
            return float(root_leaf.attacker_points)
        branch_state = self._copy_state(root_leaf)
        return self._guided_many([{"state": branch_state,
                                   "mover": branch_state.turn,
                                   "branch": branch,
                                   "horizon": len(root_leaf.history) + 1}], stats)[0]

    def _lockstep_values(self, rnd, seat, worlds, candidates, *, stage,
                         sessions=None):
        del sessions
        if self.EXACT_ENDGAME:
            raise DoubleShortlistError(
                "CWVDoubleShortlistBot does not support EXACT_ENDGAME yet")
        n_worlds, n_candidates = len(worlds), len(candidates)
        numerator, denominator, target_inner = self._guidance_counts(n_worlds)
        stats = {"stage": stage, "worlds": n_worlds,
                 "guidance_numerator": numerator,
                 "guidance_denominator": denominator,
                 "target_inner_worlds": target_inner,
                 "actual_inner_worlds": target_inner,
                 "inner_actions": 0, "inner_finalist_actions": 0,
                 "inner_net_rows": 0, "inner_batches": 0,
                 "inner_cross_parent_batches": 0,
                 "inner_full_rollouts": 0,
                 "one_extra_trick_horizon": len(rnd.history) + 2}
        values = np.empty((n_worlds, n_candidates), dtype=np.float64)
        guided_limit = stats["actual_inner_worlds"]
        guided = []
        for wi, (hands, buried) in enumerate(worlds):
            cache = (WorldSuccessorCache(rnd, seat, hands, buried)
                     if type(self.rollout_policy) is HeuristicBot else None)
            for ci, candidate in enumerate(candidates):
                leaf = self._root_leaf(rnd, seat, hands, buried, candidate, cache)
                if wi < guided_limit and self.inner_mode != "heuristic":
                    guided.append({"state": leaf,
                                   "mover": leaf.turn,
                                   "branch": (wi, ci, len(rnd.history)),
                                   "horizon": len(leaf.history) + 1,
                                   "wi": wi, "ci": ci})
                else:
                    values[wi, ci] = self._finish_heuristic(leaf)
        if guided:
            guided_values = self._guided_many(guided, stats)
            for branch, value in zip(guided, guided_values):
                values[branch["wi"], branch["ci"]] = value
        if not np.isfinite(values).all():
            raise DoubleShortlistError("double-shortlist continuation produced no value")
        self.double_shortlist_counts["calls"] += 1
        for key in ("actual_inner_worlds", "inner_actions", "inner_finalist_actions",
                    "inner_net_rows", "inner_batches", "inner_cross_parent_batches",
                    "inner_full_rollouts"):
            field = "guided_worlds" if key == "actual_inner_worlds" else key
            self.double_shortlist_counts[field] += stats[key]
        self.rollouts += stats["inner_full_rollouts"]
        self._double_stage_records.append(stats)
        self.last_double_shortlist = self._aggregate_record()
        return values


__all__ = ["CWVDoubleShortlistBot", "DoubleShortlistError"]
