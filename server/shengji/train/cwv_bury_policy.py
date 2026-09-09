"""Bounded DEV-only bury arms layered on the unchanged W32 play policy.

The wrapper is deliberately not registered.  It changes only ``decide_bury``;
all ordinary play/search behaviour comes from :class:`CWVShortlistBot`.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np

from ..ai.cwv_policy import sample_worlds
from ..ai.registry import make_bot
from .cwv_bury import (BuryValueError, bury_candidates, rollout_bury_values,
                       score_bury_candidates)
from .cwv_bury_diagnostic import derived_seed, pick_mc
from .cwv_shortlist import CWVShortlistBot, CWVShortlistConfig


MODEL_WORLDS = 32
SELECTION_WORLDS = 32
SHORTLIST_ALTERNATIVES = 4
_SEED_NAMESPACE = "cwv-bury-policy-v1"
_ARMS = frozenset(("heuristic", "mc", "hybrid"))


@dataclass(frozen=True)
class CWVBuryConfig:
    """Bounded DEV controls for candidate sourcing and bury evaluation."""

    max_candidates: int = 32
    model_worlds: int = MODEL_WORLDS
    selection_worlds: int = SELECTION_WORLDS
    alternatives: int = SHORTLIST_ALTERNATIVES

    def __post_init__(self):
        for name in ("max_candidates", "model_worlds", "selection_worlds",
                     "alternatives"):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        if self.alternatives >= self.max_candidates:
            raise ValueError("alternatives must be less than max_candidates")


class BuryPolicyError(BuryValueError):
    """The bounded DEV bury policy cannot produce a complete decision."""


def _seed(label: str, root_seed: int | None) -> int:
    """Derive a bury-only stream without touching the play bot's RNG."""
    root = 0 if root_seed is None else int(root_seed)
    return derived_seed(f"{_SEED_NAMESPACE}:{label}:{root}", 0)


def _worlds(bot: Any, rnd: Any, seat: int, count: int, label: str):
    worlds, attempts = sample_worlds(bot, rnd, seat, count)
    if len(worlds) != count:
        raise BuryPolicyError(
            f"{label} world sample underfilled: {len(worlds)} of {count}")
    return worlds, attempts


class CWVBuryBot(CWVShortlistBot):
    """CWVShortlistBot with an explicitly selected DEV bury arm.

    ``MC_BURY`` remains false.  The independent helper bots own all bury
    sampling and rollout counters, so the inherited bot's play RNG and state
    are not consumed by this wrapper.
    """

    def __init__(self, evaluator, *, seed=0, config=None, arm="heuristic",
                 reuse_successors=True, bury_config=None):
        if arm not in _ARMS:
            raise BuryPolicyError(f"unknown bury arm {arm!r}")
        if config is None:
            config = CWVShortlistConfig(
                worlds=32, selection_worlds=30, alternatives=4,
                batch_size=128, uniform=False)
        super().__init__(evaluator, seed=seed, config=config,
                         reuse_successors=reuse_successors)
        self.bury_arm = arm
        self.bury_config = (CWVBuryConfig() if bury_config is None
                            else bury_config)
        if not isinstance(self.bury_config, CWVBuryConfig):
            raise TypeError("bury_config must be a CWVBuryConfig")
        # Explicitly document the invariant even if a future parent changes a
        # class default: this wrapper must never enter MCBot's bury search.
        if self.MC_BURY:
            raise BuryPolicyError("CWV bury wrapper requires MC_BURY == False")

    def _source_bot(self):
        bot = make_bot("mc-s0-report-lcb",
                       seed=_seed("candidate-source", self.seed))
        bot.BURY_MAX_CANDIDATES = self.bury_config.max_candidates
        return bot

    def _bury_candidates(self, rnd, incumbent):
        candidates = [list(candidate)
                      for candidate in bury_candidates(rnd, self._source_bot())]
        if not candidates:
            raise BuryPolicyError("bury candidate generator returned no candidates")
        # The incumbent is the literal action obtained from this wrapper's
        # super call, not a reconstructed/canonicalised equivalent.
        candidates[0] = list(incumbent)
        keys = [tuple(sorted(candidate)) for candidate in candidates]
        if keys[0] in keys[1:]:
            raise BuryPolicyError("bury candidate generator duplicated incumbent")
        if len(set(keys)) != len(keys):
            raise BuryPolicyError("bury candidate generator returned duplicates")
        return candidates

    @staticmethod
    def _counter(bot):
        snapshot = getattr(bot, "_sampler_snapshot", None)
        return None if snapshot is None else dict(snapshot())

    def decide_bury(self, rnd, seat):
        started = time.perf_counter()
        if getattr(rnd, "phase", None) != "bury" or getattr(rnd, "banker", None) != seat:
            raise BuryPolicyError("bury policy requires the banker in bury phase")
        incumbent = list(super().decide_bury(rnd, seat))
        # The control arm is exactly the inherited heuristic action.  Do not
        # even construct a ballot for it: the baseline must carry no bury-arm
        # candidate/sampling cost.
        candidates = ([list(incumbent)] if self.bury_arm == "heuristic"
                      else self._bury_candidates(rnd, incumbent))
        shortlist = [0]
        model_seconds = 0.0
        rollout_seconds = 0.0
        model_attempts = 0
        mc_attempts = 0
        model_counter_before = None
        model_counter_after = None
        mc_counter_before = None
        mc_counter_after = None
        mc_rollouts = 0
        model_means = None
        mc_evidence = None

        if self.bury_arm == "heuristic":
            picked = 0
        else:
            model_bot = None
            model_worlds = []
            if self.bury_arm == "hybrid":
                model_bot = make_bot(
                    "mc-s0-report-lcb", seed=_seed("model", self.seed))
                model_started = time.perf_counter()
                model_counter_before = self._counter(model_bot)
                model_worlds, model_attempts = _worlds(
                    model_bot, rnd, seat, self.bury_config.model_worlds, "model")
                model_values = score_bury_candidates(
                    rnd, candidates, model_worlds, self.evaluator,
                    first_trick_policy=model_bot.rollout_policy)
                if not np.isfinite(model_values).all():
                    raise BuryPolicyError("model bury values must be finite")
                means = np.mean(model_values, axis=0)
                model_means = means.tolist()
                order = sorted(range(len(candidates)),
                               key=lambda i: (-float(means[i]), i))
                finalists = [i for i in order if i != 0][:self.bury_config.alternatives]
                # Keep the original candidate-index order for the MC helper:
                # its tie rule is index based, and local subset columns must
                # preserve that rule after mapping back to global indices.
                shortlist = [0] + sorted(finalists)
                model_seconds = time.perf_counter() - model_started
                model_counter_after = self._counter(model_bot)

            mc_bot = make_bot("mc-s0-report-lcb",
                              seed=_seed("mc", self.seed))
            rollout_started = time.perf_counter()
            mc_counter_before = self._counter(mc_bot)
            shared_worlds, mc_attempts = _worlds(
                mc_bot, rnd, seat, self.bury_config.selection_worlds, "MC")
            local_candidates = (candidates if self.bury_arm == "mc"
                                else [candidates[i] for i in shortlist])
            _utility, points = rollout_bury_values(
                rnd, local_candidates, shared_worlds, mc_bot)
            mc_rollouts = len(local_candidates) * len(shared_worlds)
            local_pick = pick_mc(points, mc_bot, range(len(local_candidates)))
            picked = local_pick if self.bury_arm == "mc" else shortlist[local_pick]
            # Retain precisely the chooser's MC objective, NOT the model's
            # signed-level prediction or scores for unsearched candidates.
            mc_means = np.asarray([
                [-mc_bot._score(float(p)) for p in row] for row in points
            ]).mean(axis=0).tolist()
            mc_evidence = {
                "candidate_indices": (list(range(len(candidates)))
                                      if self.bury_arm == "mc" else list(shortlist)),
                "mean_banker_values": mc_means,
                "worlds_per_candidate": len(shared_worlds),
                "objective": "negative-mcbot-score",
                "level_objective": bool(mc_bot.LEVEL_OBJECTIVE),
                "incumbent_margin": float(mc_bot.MARGIN),
            }
            rollout_seconds = time.perf_counter() - rollout_started
            mc_counter_after = self._counter(mc_bot)

        elapsed = time.perf_counter() - started
        self.last_bury_record = {
            "schema": "cwv-bury-policy-v1",
            "arm": self.bury_arm,
            "bury_config": asdict(self.bury_config),
            "candidates": [list(candidate) for candidate in candidates],
            "shortlist": list(shortlist),
            "picked_index": int(picked),
            "model_means": model_means,
            "mc_evidence": mc_evidence,
            "model_worlds": (self.bury_config.model_worlds
                              if self.bury_arm == "hybrid" else 0),
            "selection_worlds": (self.bury_config.selection_worlds
                                 if self.bury_arm != "heuristic" else 0),
            "world_counts": {
                "model": (self.bury_config.model_worlds
                           if self.bury_arm == "hybrid" else 0),
                "selection": (self.bury_config.selection_worlds
                               if self.bury_arm != "heuristic" else 0),
                "model_attempts": model_attempts,
                "selection_attempts": mc_attempts,
            },
            "elapsed_seconds": elapsed,
            "model_seconds": model_seconds,
            "rollout_seconds": rollout_seconds,
            "mc_rollouts": mc_rollouts,
            "model_positions": (len(candidates) * self.bury_config.model_worlds
                                if self.bury_arm == "hybrid" else 0),
            "counters": {
                "wrapper": self._counter(self),
                "model_before": model_counter_before,
                "model_after": model_counter_after,
                "mc_before": mc_counter_before,
                "mc_after": mc_counter_after,
            },
        }
        return list(candidates[picked])


def trajectory_bury_record(raw: dict) -> dict:
    """Map new DEV evidence to the existing MC-bury data-writer contract.

    The training ballot is only the MC-scored subset (or the single heuristic
    action). The full proposal pool and its model rankings remain separate
    metadata. Old screen records without MC evidence cannot be relabeled from
    the final pick: they remain valid gameplay evidence, not value targets.
    """
    if raw.get("schema") != "cwv-bury-policy-v1" or "mc_evidence" not in raw:
        raise BuryPolicyError("bury trajectory requires retained MC evidence; old screen records are not value labels")
    pool = raw["candidates"]
    picked = raw["picked_index"]
    evidence = raw["mc_evidence"]
    if raw["arm"] == "heuristic":
        if evidence is not None or picked != 0 or len(pool) != 1:
            raise BuryPolicyError("heuristic bury evidence is inconsistent")
        indices, means, n = [0], [None], 0
        winner = None
    else:
        if not isinstance(evidence, dict):
            raise BuryPolicyError("searched bury is missing MC evidence")
        indices = evidence["candidate_indices"]
        means = evidence["mean_banker_values"]
        n = evidence["worlds_per_candidate"]
        if (not indices or indices[0] != 0
                or any(type(i) is not int or not 0 <= i < len(pool) for i in indices)
                or len(set(indices)) != len(indices) or picked not in indices
                or len(means) != len(indices) or not np.isfinite(means).all()
                or type(n) is not int or n < 1
                or n != raw["selection_worlds"]
                or len(indices) * n != raw["mc_rollouts"]
                or evidence["objective"] != "negative-mcbot-score"):
            raise BuryPolicyError("bury MC evidence is not aligned with its scored candidates")
        winner = max(range(len(means)), key=lambda i: (means[i], -indices[i]))
    return {
        "candidates": [{"cards": list(pool[i]), "mean_banker_value": mean}
                       for i, mean in zip(indices, means)],
        "n_by_candidate": [n] * len(indices),
        "played_index": indices.index(picked),
        "raw_winner_index": winner,
        "reason": "heuristic" if evidence is None else "MC-with-incumbent-margin",
        "candidate_count": len(indices),
        "bury_search": {
            "schema": "cwv-bury-search-evidence-v1",
            "arm": raw["arm"], "config": raw["bury_config"],
            "candidate_pool": pool, "ballot_pool_indices": indices,
            "model_means": raw["model_means"],
            "model_worlds": raw["model_worlds"],
            "mc_objective": None if evidence is None else evidence["objective"],
            "level_objective": None if evidence is None else evidence["level_objective"],
            "incumbent_margin": None if evidence is None else evidence["incumbent_margin"],
            "model_values_are_mc_targets": False,
        },
    }


def make_cwv_bury_bot(evaluator, W32config: CWVShortlistConfig | None = None,
                      seed=0, arm="heuristic", bury_config=None) -> CWVBuryBot:
    """Build one DEV bury arm around the supplied, unchanged W32 config."""
    return CWVBuryBot(evaluator, seed=seed, config=W32config, arm=arm,
                      reuse_successors=True, bury_config=bury_config)


__all__ = [
    "BuryPolicyError", "CWVBuryConfig", "CWVBuryBot", "MODEL_WORLDS",
    "SELECTION_WORLDS", "SHORTLIST_ALTERNATIVES", "make_cwv_bury_bot",
]
