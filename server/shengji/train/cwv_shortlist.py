"""DEV-only exhaustive legal shortlist, followed by unmodified MC-LCB search.

The model ranks submitted actions, including throws whose accepted component
depends on a sampled world. It never replaces a selection or report rollout.
No live registry entry is installed. Four alternatives plus the incumbent
means min(5, legal_count) actions in BOTH learned and uniform arms.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import random
import time

import numpy as np

from ..ai.cwv_policy import afterstate, sample_worlds
from ..ai.cwv_successor_reuse import TensorInputCache, WorldSuccessorCache
from ..ai.mcbot import _child_seed
from ..ai.registry import REGISTRY
from ..harvest.legal import enumerate_legal


@dataclass(frozen=True)
class CWVShortlistConfig:
    worlds: int = 1
    selection_worlds: int = 30
    alternatives: int = 4
    batch_size: int = 128
    uniform: bool = False

    def __post_init__(self):
        for name in ("worlds", "selection_worlds", "alternatives", "batch_size"):
            if type(getattr(self, name)) is not int or getattr(self, name) < 1:
                raise ValueError(f"{name} must be a positive integer")
        if type(self.uniform) is not bool:
            raise ValueError("uniform must be boolean")


class CWVShortlistBot(REGISTRY["mc-s0-report-lcb"]):
    # The full-legal request includes leads production would tractor-lock.
    # Only this candidate bypass changes; allocation, rollouts, report and
    # final point-shy tie-breaking are inherited from literal production.
    TRACTOR_LOCK = False

    def __init__(self, evaluator, *, seed=0, config=None, reuse_successors=False):
        super().__init__(seed)
        self.shortlist_config = config or CWVShortlistConfig()
        if type(reuse_successors) is not bool:
            raise ValueError("reuse_successors must be boolean")
        if reuse_successors and self.shortlist_config.uniform:
            raise ValueError("successor reuse requires the learned shortlist")
        self.reuse_successors = reuse_successors
        self.last_successor_reuse = None
        if not self.shortlist_config.uniform and evaluator is None:
            raise ValueError("learned shortlist requires a complete-world evaluator")
        self.evaluator = evaluator
        self.N_DETERMINIZATIONS = self.shortlist_config.selection_worlds
        self.last_shortlist = None
        self.shortlist_counts = dict.fromkeys((
            "decisions", "forced", "legal_actions", "shortlisted_actions",
            "offballot_kept", "offballot_played", "cheap_worlds",
            "cheap_evaluations", "cheap_batches", "terminal_afterstates"), 0)
        self.shortlist_wall_seconds = 0.0

    def _means(self, rnd, seat, actions, worlds):
        """Score EVERY action/world, retaining only O(K + batch_size) state."""
        sums = np.zeros(len(actions), dtype=np.float64)
        pending, indices = [], []
        # The tensor cache spans this decision, not one world: the original
        # forward batches can straddle world boundaries. Exact leaf identity
        # keeps those worlds distinct without flushing/changing batch shapes.
        tensor_cache = TensorInputCache() if self.reuse_successors else None
        reuse = {"root_actions": 0, "leaf_hits": 0, "leaf_completions": 0,
                 "peak_entries": 0}

        def flush():
            if not pending:
                return
            scored = (self.evaluator.score(pending, seat) if tensor_cache is None
                      else self.evaluator.score(pending, seat, tensor_cache=tensor_cache))
            values = np.asarray(scored, dtype=np.float64)
            if values.shape != (len(pending),) or not np.isfinite(values).all():
                raise ValueError("CWV shortlist requires one finite root-team value per afterstate")
            np.add.at(sums, indices, values)
            self.shortlist_counts["cheap_evaluations"] += len(pending)
            self.shortlist_counts["cheap_batches"] += 1
            pending.clear()
            indices.clear()

        for hands, buried in worlds:
            successor_cache = (WorldSuccessorCache(rnd, seat, hands, buried)
                               if self.reuse_successors else None)
            for index, action in enumerate(actions):
                # Exactly the #229 convention: engine root action, heuristic
                # finishes this trick, then complete-world value (terminal exact).
                leaf = (afterstate(rnd, seat, hands, buried, action, finish_trick=True)
                        if successor_cache is None else successor_cache.leaf(action))
                self.shortlist_counts["terminal_afterstates"] += int(leaf.phase == "round_end")
                pending.append(leaf)
                indices.append(index)
                if len(pending) == self.shortlist_config.batch_size:
                    flush()
            if successor_cache is not None:
                for key in ("root_actions", "leaf_hits", "leaf_completions"):
                    reuse[key] += successor_cache.counters[key]
                reuse["peak_entries"] = max(reuse["peak_entries"], successor_cache.peak_entries)
        flush()
        self.last_successor_reuse = (None if tensor_cache is None else {
            "schema": "cwv-successor-reuse-v1", "max_entries_per_cache": 128,
            **reuse, "tensor_hits": tensor_cache.hits,
            "tensor_completions": tensor_cache.completions,
            "peak_tensor_entries": tensor_cache.peak_entries})
        return sums / len(worlds)

    def _candidates(self, rnd, seat):
        started = time.perf_counter()
        self.last_successor_reuse = None
        production = super()._candidates(rnd, seat)
        incumbent = tuple(sorted(production[0]))
        legal = enumerate_legal(rnd, seat, cap=None, must_include=production)
        actions = legal.actions
        keys = [tuple(sorted(a)) for a in actions]
        # cap=None exhausts the iterator even if the separate counting helper
        # declines a >2M raw-candidate count. Never use a capped prefix.
        if (not keys or len(set(keys)) != len(keys) or incumbent not in keys
                or (legal.count is not None and legal.count != len(keys))):
            raise ValueError("CWV shortlist exhaustive legal population drift")
        base = keys.index(incumbent)
        alternatives = [i for i in range(len(keys)) if i != base]
        state = self.rng.getstate()
        world_seed = _child_seed(state, "cwv-full-legal-worlds-v1")
        uniform_seed = _child_seed(state, "cwv-full-legal-uniform-v1")
        means = None
        before = dict(self.shortlist_counts)
        sampler_before = self._sampler_snapshot()
        if len(actions) == 1:
            chosen = []
            self.shortlist_counts["forced"] += 1
        elif self.shortlist_config.uniform:
            chosen = random.Random(uniform_seed).sample(
                alternatives, min(len(alternatives), self.shortlist_config.alternatives))
        else:
            parent_rng = self.rng
            try:
                self.rng = random.Random(world_seed)
                worlds, _ = sample_worlds(self, rnd, seat, self.shortlist_config.worlds)
            finally:
                # Cheap ranking cannot consume production selection/report RNG.
                self.rng = parent_rng
            if len(worlds) != self.shortlist_config.worlds:
                raise ValueError("CWV shortlist cheap world population underfilled")
            self.shortlist_counts["cheap_worlds"] += len(worlds)
            means = self._means(rnd, seat, actions, worlds)
            chosen = sorted(alternatives, key=lambda i: (-means[i], keys[i]))[
                :self.shortlist_config.alternatives]
        selected = [base, *chosen]
        production_keys = {tuple(sorted(a)) for a in production}
        kept = [actions[i] for i in selected]
        self.shortlist_counts["decisions"] += 1
        self.shortlist_counts["legal_actions"] += len(actions)
        self.shortlist_counts["shortlisted_actions"] += len(selected)
        self.shortlist_counts["offballot_kept"] += sum(keys[i] not in production_keys for i in selected)
        self.last_shortlist = {
            "config": asdict(self.shortlist_config), "complete": True,
            "legal_count": len(actions), "production_count": len(production),
            "legal_sha256": hashlib.sha256(json.dumps(keys, separators=(",", ":")).encode()).hexdigest(),
            "incumbent": list(incumbent), "shortlist": kept,
            "shortlist_indices": selected,
            "shortlist_means": None if means is None else [float(means[i]) for i in selected],
            "production_keys": sorted(production_keys),
            "world_seed": world_seed, "uniform_seed": uniform_seed,
            "cheap_sampler_delta": self._sampler_delta(sampler_before),
            "counts": {k: self.shortlist_counts[k] - before[k] for k in before},
        }
        if self.reuse_successors:
            self.last_shortlist["successor_reuse"] = self.last_successor_reuse
        elapsed = time.perf_counter() - started
        self.shortlist_wall_seconds += elapsed
        self.last_shortlist["wall_seconds"] = elapsed
        return kept

    def decide_play(self, rnd, seat):
        self.last_shortlist = None
        played = super().decide_play(rnd, seat)
        detail = self.last_shortlist
        if detail is not None:
            offballot = tuple(sorted(played)) not in set(detail["production_keys"])
            self.shortlist_counts["offballot_played"] += int(offballot)
            detail["offballot_played"] = offballot
            if self.last_decision_record is not None:
                self.last_decision_record["cwv_shortlist"] = detail
                # The inherited snapshot intentionally covers the entire
                # decision, including candidate generation. Keep that truthful
                # total AND distinguish production's selection/report samples.
                total = self.last_decision_record["sampler_counters"]["delta"]
                detail["production_sampler_delta"] = {
                    key: value - detail["cheap_sampler_delta"][key]
                    for key, value in total.items()}
        return played
