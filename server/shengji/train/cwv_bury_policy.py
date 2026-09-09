"""Bounded DEV-only bury arms layered on the unchanged W32 play policy.

The wrapper is deliberately not registered.  It changes only ``decide_bury``;
all ordinary play/search behaviour comes from :class:`CWVShortlistBot`.
"""

from __future__ import annotations

import time
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
                 reuse_successors=True):
        if arm not in _ARMS:
            raise BuryPolicyError(f"unknown bury arm {arm!r}")
        if config is None:
            config = CWVShortlistConfig(
                worlds=32, selection_worlds=30, alternatives=4,
                batch_size=128, uniform=False)
        super().__init__(evaluator, seed=seed, config=config,
                         reuse_successors=reuse_successors)
        self.bury_arm = arm
        # Explicitly document the invariant even if a future parent changes a
        # class default: this wrapper must never enter MCBot's bury search.
        if self.MC_BURY:
            raise BuryPolicyError("CWV bury wrapper requires MC_BURY == False")

    def _source_bot(self):
        return make_bot("mc-s0-report-lcb",
                        seed=_seed("candidate-source", self.seed))

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
                    model_bot, rnd, seat, MODEL_WORLDS, "model")
                model_values = score_bury_candidates(
                    rnd, candidates, model_worlds, self.evaluator,
                    first_trick_policy=model_bot.rollout_policy)
                if not np.isfinite(model_values).all():
                    raise BuryPolicyError("model bury values must be finite")
                means = np.mean(model_values, axis=0)
                order = sorted(range(len(candidates)),
                               key=lambda i: (-float(means[i]), i))
                finalists = [i for i in order if i != 0][:SHORTLIST_ALTERNATIVES]
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
                mc_bot, rnd, seat, SELECTION_WORLDS, "MC")
            local_candidates = (candidates if self.bury_arm == "mc"
                                else [candidates[i] for i in shortlist])
            _utility, points = rollout_bury_values(
                rnd, local_candidates, shared_worlds, mc_bot)
            mc_rollouts = len(local_candidates) * len(shared_worlds)
            local_pick = pick_mc(points, mc_bot, range(len(local_candidates)))
            picked = local_pick if self.bury_arm == "mc" else shortlist[local_pick]
            rollout_seconds = time.perf_counter() - rollout_started
            mc_counter_after = self._counter(mc_bot)

        elapsed = time.perf_counter() - started
        self.last_bury_record = {
            "schema": "cwv-bury-policy-v1",
            "arm": self.bury_arm,
            "candidates": [list(candidate) for candidate in candidates],
            "shortlist": list(shortlist),
            "picked_index": int(picked),
            "model_worlds": MODEL_WORLDS if self.bury_arm == "hybrid" else 0,
            "selection_worlds": (SELECTION_WORLDS
                                 if self.bury_arm != "heuristic" else 0),
            "world_counts": {
                "model": MODEL_WORLDS if self.bury_arm == "hybrid" else 0,
                "selection": SELECTION_WORLDS if self.bury_arm != "heuristic" else 0,
                "model_attempts": model_attempts,
                "selection_attempts": mc_attempts,
            },
            "elapsed_seconds": elapsed,
            "model_seconds": model_seconds,
            "rollout_seconds": rollout_seconds,
            "mc_rollouts": mc_rollouts,
            "model_positions": len(candidates) * MODEL_WORLDS if self.bury_arm == "hybrid" else 0,
            "counters": {
                "wrapper": self._counter(self),
                "model_before": model_counter_before,
                "model_after": model_counter_after,
                "mc_before": mc_counter_before,
                "mc_after": mc_counter_after,
            },
        }
        return list(candidates[picked])


def make_cwv_bury_bot(evaluator, W32config: CWVShortlistConfig | None = None,
                      seed=0, arm="heuristic") -> CWVBuryBot:
    """Build one DEV bury arm around the supplied, unchanged W32 config."""
    return CWVBuryBot(evaluator, seed=seed, config=W32config, arm=arm,
                      reuse_successors=True)


__all__ = [
    "BuryPolicyError", "CWVBuryBot", "MODEL_WORLDS", "SELECTION_WORLDS",
    "SHORTLIST_ALTERNATIVES", "make_cwv_bury_bot",
]
