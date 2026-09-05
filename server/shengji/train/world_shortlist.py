"""Bounded value-guided world shortlist experiment.

This module deliberately has no registry entry.  It uses the production S0
ballot and report fold, but spends a bounded cheap leaf dose to choose the
small set of candidates that receive the inherited full-rollout refinement.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math
import random
import time

import numpy as np

from ..ai.mcbot import _child_seed
from ..ai.registry import REGISTRY
from ..oracle.screen import OracleValueMixin
from ..rl.encode import encode_obs
from .leaf_policy import PointsHead
from .search_policy import SearchError, terminal_utility


@dataclass(frozen=True)
class WorldShortlistConfig:
    cheap_worlds: int = 128
    refine_worlds: int = 16
    shortlist_size: int = 3
    leaf_tricks: int = 1
    batch_size: int = 128
    value_kind: str = "levels"

    def __post_init__(self):
        for name in ("cheap_worlds", "refine_worlds", "shortlist_size", "batch_size"):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if self.shortlist_size < 2:
            raise ValueError("shortlist_size must be at least 2")
        if type(self.leaf_tricks) is not int or self.leaf_tricks not in (0, 1, 3):
            raise ValueError("leaf_tricks must be 0, 1, or 3")
        if self.value_kind not in {"levels", "points"}:
            raise ValueError("value_kind must be 'levels' or 'points'")


class WorldShortlistBot(REGISTRY["mc-s0-report-lcb"]):
    """Production ballot/report with a cheap value-ranked shortlist."""

    ADAPTIVE_ALLOCATION = True
    N_DETERMINIZATIONS = WorldShortlistConfig().refine_worlds

    def __init__(self, heads, *, seed: int = 0,
                 config: WorldShortlistConfig | None = None):
        super().__init__(seed)
        self.heads = heads
        self.world_shortlist_config = config or WorldShortlistConfig()
        self.config = self.world_shortlist_config
        self.N_DETERMINIZATIONS = self.world_shortlist_config.refine_worlds
        self.policy_name = "mc-s0-report-lcb+world-shortlist"
        if self.world_shortlist_config.value_kind == "points":
            model = getattr(heads, "model", None)
            if model is None:
                raise SearchError("points world shortlist requires a model-backed heads object")
            # Export once.  A headless checkpoint is refused by PointsHead.
            self._points_head = PointsHead.from_model(
                model, metadata=getattr(heads, "metadata", None))
        else:
            self._points_head = None
        self.hybrid_counts = {name: 0 for name in (
            "cheap_worlds", "cheap_evaluations", "model_rows", "model_batches",
            "terminal_leaves", "leaf_plies", "refine_worlds", "refine_full_rollouts",
            "report_full_rollouts")}
        self.hybrid_inference_seconds = 0.0
        self._world_shortlist_pending = None

    def _pick_index(self, candidates, means, indices):
        """Keep production tie handling, with its missing-data fallback fixed."""
        try:
            return super()._pick_index(candidates, means, indices)
        except ValueError:
            # MCBot computes its argmax before checking an underfilled search.
            # With no accepted world every mean is -inf and its point-shy
            # subtraction becomes NaN; candidate zero is the required fallback.
            indices = list(indices)
            if indices and all(means[i] == float("-inf") for i in indices):
                return indices[0]
            raise

    def _cheap_leaf(self, rnd, seat, hands, buried, action, target_tricks,
                    i_attack):
        clone = OracleValueMixin._oracle_world_clone(self, rnd, seat, hands, buried)
        clone.play(seat, list(action))
        self.hybrid_counts["leaf_plies"] += 1
        while clone.phase == "play" and len(clone.history) < target_tricks:
            who = clone.turn
            clone.play(who, self.rollout_policy.decide_play(clone, who))
            self.hybrid_counts["leaf_plies"] += 1
        if clone.phase == "round_end":
            self.hybrid_counts["terminal_leaves"] += 1
            if self.world_shortlist_config.value_kind == "points":
                points = float(clone.attacker_points)
                if not math.isfinite(points):
                    raise SearchError("terminal attacker points are non-finite")
                return None, points if i_attack else -points
            return None, 40.0 * terminal_utility(clone, seat % 2)
        return clone, None

    def _cheap_values(self, rnd, seat, candidates, worlds, i_attack):
        """Evaluate every candidate/world on shared clones, in bounded batches."""
        target = len(rnd.history) + self.world_shortlist_config.leaf_tricks
        scores = [[None] * len(worlds) for _ in candidates]
        pending = []

        def flush():
            nonlocal pending
            if not pending:
                return
            chunk = pending
            pending = []
            leaves = [item[2] for item in chunk]
            before = time.perf_counter()
            if self.world_shortlist_config.value_kind == "levels":
                raw = self.heads.values(leaves)
                arr = np.asarray(raw, dtype=np.float64)
                if arr.ndim != 1 or len(arr) != len(leaves):
                    raise SearchError("cheap level head must cover every leaf")
                values = arr
                # SearchHeads values are signed for the leaf acting team.
                for (ci, wi, leaf), value in zip(chunk, values):
                    if not math.isfinite(float(value)):
                        raise SearchError("cheap level head returned non-finite values")
                    signed = float(value) if leaf.turn % 2 == seat % 2 else -float(value)
                    scores[ci][wi] = 40.0 * signed
            else:
                obs = np.asarray([encode_obs(leaf, leaf.turn) for leaf in leaves],
                                 dtype=np.float64)
                values = np.asarray(self._points_head.forward(obs), dtype=np.float64)
                if values.ndim != 2 or values.shape != (len(leaves), 2):
                    raise SearchError("cheap points head must return [rows, 2]")
                if not np.all(np.isfinite(values)):
                    raise SearchError("cheap points head returned non-finite values")
                sign = 1.0 if i_attack else -1.0
                for (ci, wi, _), value in zip(chunk, values[:, 1]):
                    scores[ci][wi] = sign * float(value) * 100.0
            self.hybrid_inference_seconds += time.perf_counter() - before
            self.hybrid_counts["model_rows"] += len(leaves)
            self.hybrid_counts["model_batches"] += 1

        for wi, (hands, buried) in enumerate(worlds):
            for ci, action in enumerate(candidates):
                leaf, terminal = self._cheap_leaf(
                    rnd, seat, hands, buried, action, target, i_attack)
                if terminal is not None:
                    scores[ci][wi] = terminal
                else:
                    pending.append((ci, wi, leaf))
                if len(pending) >= self.world_shortlist_config.batch_size:
                    flush()
        flush()
        if any(value is None for row in scores for value in row):
            raise SearchError("cheap evaluation did not cover every candidate/world")
        self.hybrid_counts["cheap_evaluations"] += len(candidates) * len(worlds)
        return [[float(value) for value in row] for row in scores]

    def _sample_stage(self, rnd, seat, mem, requested, rng, *, restore=True):
        original_rng = self.rng
        if rng is not None:
            self.rng = random.Random(rng)
        worlds = []
        attempts = 0
        cap = requested * self.SAMPLE_ATTEMPT_FACTOR
        try:
            while len(worlds) < requested and attempts < cap:
                attempts += 1
                sampled = self._sample_hands(rnd, seat, mem)
                if sampled is not None:
                    worlds.append(sampled)
        finally:
            if restore:
                self.rng = original_rng
        return worlds, attempts, cap

    def _decide_adaptive(self, rnd, seat, candidates, mem, i_attack,
                         *, allocation_rng):
        cfg = self.world_shortlist_config
        K = len(candidates)
        state = allocation_rng.getstate()
        refine_seed = _child_seed(state, "world-shortlist-refine")
        self._world_shortlist_pending = {
            "config": asdict(cfg), "cheap_stream": "parent policy RNG",
            "refinement_seed": refine_seed,
        }
        # Cheap sampling is the real policy stream and must advance it so the
        # next decision cannot repeat the same dose. Refinement uses a named
        # child stream and restores this parent stream below.
        cheap_worlds, cheap_attempts, cheap_cap = self._sample_stage(
            rnd, seat, mem, cfg.cheap_worlds, None, restore=False)
        self.hybrid_counts["cheap_worlds"] += len(cheap_worlds)
        pending = self._world_shortlist_pending
        pending.update({
            "cheap_worlds": len(cheap_worlds), "cheap_attempts": cheap_attempts,
            "cheap_attempt_cap": cheap_cap,
        })
        if len(cheap_worlds) != cfg.cheap_worlds:
            self._set_short_alloc(K, cheap_attempts, cheap_cap, len(cheap_worlds),
                                  0, [], cfg.cheap_worlds * K, "cheap")
            pending["shortlist_indices"] = [0]
            pending["cheap_means"] = []
            return [0.0] * K, [0.0] * K, [0.0] * K, [0] * K, len(cheap_worlds), 0

        cheap_scores = self._cheap_values(rnd, seat, candidates, cheap_worlds, i_attack)
        cheap_means = [math.fsum(row) / len(row) for row in cheap_scores]
        # Pick each rank with the production point-shy tie handling. Candidate
        # zero is always retained, even when the model ranks it poorly.
        ranked = [0]
        remaining = list(range(1, K))
        while remaining and len(ranked) < min(cfg.shortlist_size, K):
            pick = self._pick_index(candidates, cheap_means, remaining)
            ranked.append(pick)
            remaining.remove(pick)
        pending.update({"cheap_means": cheap_means, "shortlist_indices": ranked})

        fresh, refine_attempts, refine_cap = self._sample_stage(
            rnd, seat, mem, cfg.refine_worlds, refine_seed)
        self.hybrid_counts["refine_worlds"] += len(fresh)
        pending.update({"refine_worlds": len(fresh), "refine_attempts": refine_attempts,
                        "refine_attempt_cap": refine_cap})
        if len(fresh) != cfg.refine_worlds:
            self._set_short_alloc(K, cheap_attempts + refine_attempts, cheap_cap + refine_cap,
                                  len(cheap_worlds), len(fresh), ranked,
                                  cfg.cheap_worlds * K + cfg.refine_worlds * len(ranked),
                                  "refine", rollouts=len(cheap_worlds) * K)
            self.last_alloc["attempt_cap_hit"] = refine_attempts >= refine_cap
            return ([0.0] * K, [0.0] * K, [0.0] * K, [0] * K,
                    len(cheap_worlds) + len(fresh), len(cheap_worlds) * K)

        totals = [0.0] * K
        d_sum = [0.0] * K
        d_sq = [0.0] * K
        n_by = [0] * K
        for hands, buried in fresh:
            session = self._new_exact_world_session(rnd, buried)
            values = {}
            for i in ranked:
                value = self._score(self._rollout(
                    rnd, seat, hands, buried, candidates[i], exact_session=session))
                value = value if i_attack else -value
                values[i] = value
                totals[i] += value
                n_by[i] += 1
                self.hybrid_counts["refine_full_rollouts"] += 1
            base = values[0]
            for i, value in values.items():
                delta = value - base
                d_sum[i] += delta
                d_sq[i] += delta * delta
        rollouts = len(cheap_worlds) * K + len(fresh) * len(ranked)
        self._set_short_alloc(K, cheap_attempts + refine_attempts,
                              cheap_cap + refine_cap, len(cheap_worlds), len(fresh), ranked,
                              cfg.cheap_worlds * K + cfg.refine_worlds * len(ranked),
                              "complete", rollouts=rollouts)
        return totals, d_sum, d_sq, n_by, len(cheap_worlds) + len(fresh), rollouts

    def _set_short_alloc(self, K, attempts, cap, cheap_used, refine_used,
                         survivors, budget, stage, *, rollouts=0):
        self.last_alloc = {
            "mode": "world_shortlist", "attempts": attempts,
            "attempt_cap": cap, "attempt_cap_hit": attempts >= cap,
            "worlds": cheap_used + refine_used, "cheap_worlds": cheap_used,
            "refine_worlds": refine_used, "rollouts": rollouts,
            "decision_rollouts": rollouts, "dummy_rollouts": 0, "budget": budget,
            "short": stage != "complete", "underfilled_stage": None if stage == "complete" else stage,
            "survivors": len(survivors), "survivor_indices": list(survivors),
            "n_by_candidate": ([refine_used if stage == "complete" and i in survivors else 0
                                 for i in range(K)]),
        }

    def decide_play(self, rnd, seat):
        before = dict(self.hybrid_counts)
        before_inference = self.hybrid_inference_seconds
        self._world_shortlist_pending = None
        action = super().decide_play(rnd, seat)
        rec = self.last_decision_record
        if rec is not None and self._world_shortlist_pending is not None:
            report_delta = int(rec.get("work", {}).get("report_rollouts", 0))
            self.hybrid_counts["report_full_rollouts"] += report_delta
            delta = {key: self.hybrid_counts[key] - before[key]
                     for key in self.hybrid_counts}
            rec["world_shortlist"] = {
                "config": asdict(self.world_shortlist_config),
                "cheap_means": self._world_shortlist_pending.get("cheap_means", []),
                "shortlist_indices": self._world_shortlist_pending.get("shortlist_indices", []),
                "refinement_seed": self._world_shortlist_pending["refinement_seed"],
                "stage_counts_delta": delta,
                "inference_seconds": self.hybrid_inference_seconds - before_inference,
                "cheap_worlds": self._world_shortlist_pending.get("cheap_worlds", 0),
                "refine_worlds": self._world_shortlist_pending.get("refine_worlds", 0),
                "evaluator_declarations": {
                    "cheap": "truncated value leaves for shortlist ranking only",
                    "refinement": "inherited production full heuristic rollouts, points",
                    "report": "inherited independent report-LCB full heuristic rollouts, points",
                    "model_enters": "cheap shortlist ranking only",
                },
            }
        return action
