"""DEV-only bounded wide-tail admission for the exhaustive CWV shortlist.

The first two worlds rank the complete legal population.  Only that bounded
tail, together with every production-ballot anchor, receives the remaining
thirty worlds.  Selection sees only the latter means, so the admission dose
cannot leak into the final shortlist score.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import math

import numpy as np

from .cwv_shortlist import CWVShortlistBot


@dataclass(frozen=True)
class CWVWideTailConfig:
    """The wide-tail-only fields; normal shortlist config stays separate."""

    threshold: int = 10_000
    coarse_worlds: int = 2
    pool: int = 256

    def __post_init__(self):
        for name in ("threshold", "coarse_worlds", "pool"):
            value = getattr(self, name)
            if type(value) is not int or value < 1:
                raise ValueError(f"{name} must be a positive integer")


def _reuse_total(coarse, refine):
    """Combine stage counters without misreporting a refinement-only total."""
    if coarse is None and refine is None:
        return None
    coarse = coarse or {}
    refine = refine or {}
    total = {}
    additive = {
        "root_actions", "leaf_hits", "leaf_completions",
        "tensor_hits", "tensor_completions",
    }
    for key in set(coarse) | set(refine):
        if key in {"schema", "max_entries_per_cache"}:
            total[key] = refine.get(key, coarse.get(key))
        elif key in additive:
            total[key] = int(coarse.get(key, 0)) + int(refine.get(key, 0))
        elif key.startswith("peak_") or key == "peak_entries":
            total[key] = max(int(coarse.get(key, 0)), int(refine.get(key, 0)))
        else:
            # Keep future diagnostic counters truthful: an unknown numeric
            # counter is work from both stages, while non-numeric metadata is
            # carried from the refinement stage.
            left, right = coarse.get(key), refine.get(key)
            if isinstance(left, (int, float)) and isinstance(right, (int, float)):
                total[key] = left + right
            else:
                total[key] = right if right is not None else left
    return total


class CWVWideTailBot(CWVShortlistBot):
    """Learned W32 shortlist with bounded full-legal admission."""

    def __init__(self, evaluator, *, seed=0, config=None, wide_tail=None,
                 reuse_successors=False, capture_full_legal_scores=False):
        # The screen supplies the ordinary shortlist config plus its explicit
        # ``wide_tail`` recipe.  Direct callers may pass the recipe as config.
        from .cwv_shortlist import CWVShortlistConfig

        if wide_tail is None and isinstance(config, CWVWideTailConfig):
            wide_tail, config = config, None
        if wide_tail is None:
            wide_tail = CWVWideTailConfig()
        if not isinstance(wide_tail, CWVWideTailConfig):
            raise TypeError("wide-tail recipe must be CWVWideTailConfig")
        if config is None:
            config = CWVShortlistConfig(worlds=32, selection_worlds=30,
                                        alternatives=4)
        if not isinstance(config, CWVShortlistConfig):
            raise TypeError("shortlist config must be CWVShortlistConfig")
        if config.uniform:
            raise ValueError("wide-tail requires the learned shortlist")
        if config.worlds != 32:
            raise ValueError("wide-tail requires W32")
        if config.alternatives != 4:
            raise ValueError("wide-tail requires four alternatives")
        if wide_tail.pool < config.alternatives + 1:
            raise ValueError("wide-tail pool must retain incumbent plus alternatives")
        if wide_tail.coarse_worlds >= config.worlds:
            raise ValueError("wide-tail requires refinement worlds")
        if capture_full_legal_scores:
            raise ValueError("wide-tail does not support full legal score capture")
        self.wide_tail_config = wide_tail
        self._wide_tail_diagnostics = None
        super().__init__(
            evaluator, seed=seed, config=config,
            reuse_successors=reuse_successors,
            capture_full_legal_scores=False,
        )

    def _admission_means(self, rnd, seat, actions, worlds, production):
        """Rank a wide legal tail, or preserve the ordinary one-stage path."""
        # A fresh diagnostic is important when a bot is reused for decisions;
        # a failed/short or <=threshold decision must not expose stale wide data.
        self._wide_tail_diagnostics = None
        cfg = self.wide_tail_config
        base_cfg = self.shortlist_config
        if len(actions) <= cfg.threshold:
            return self._means(rnd, seat, actions, worlds)
        refine_count = base_cfg.worlds - cfg.coarse_worlds
        if len(worlds) != base_cfg.worlds or len(worlds) < cfg.coarse_worlds + refine_count:
            raise ValueError("wide-tail requires 32 sampled worlds")
        if len(actions) < base_cfg.alternatives + 1:
            raise ValueError("wide-tail legal population is smaller than shortlist")

        keys = [tuple(sorted(action)) for action in actions]
        production_keys = {tuple(sorted(action)) for action in production}
        production_indices = []
        for key in production_keys:
            try:
                production_indices.append(keys.index(key))
            except ValueError as exc:
                raise ValueError("wide-tail production anchor missing from legal population") from exc

        coarse_worlds = worlds[:cfg.coarse_worlds]
        refine_worlds = worlds[cfg.coarse_worlds:cfg.coarse_worlds + refine_count]
        if len(coarse_worlds) != cfg.coarse_worlds or len(refine_worlds) != refine_count:
            raise ValueError("wide-tail world slices are underfilled")

        coarse = np.asarray(self._means(rnd, seat, actions, coarse_worlds), dtype=np.float64)
        coarse_reuse = self.last_successor_reuse
        if coarse.shape != (len(actions),) or not np.isfinite(coarse).all():
            raise ValueError("wide-tail coarse model means must be finite")
        ranked = sorted(range(len(actions)), key=lambda index: (-float(coarse[index]), keys[index]))
        top_indices = ranked[:min(cfg.pool, len(actions))]
        pool_indices = sorted(set(top_indices) | set(production_indices))
        if len(pool_indices) < base_cfg.alternatives + 1:
            raise ValueError("wide-tail pool must retain incumbent plus alternatives")

        refine_actions = [actions[index] for index in pool_indices]
        refine = np.asarray(self._means(rnd, seat, refine_actions, refine_worlds), dtype=np.float64)
        refine_reuse = self.last_successor_reuse
        if refine.shape != (len(pool_indices),) or not np.isfinite(refine).all():
            raise ValueError("wide-tail refinement model means must be finite")

        means = np.full(len(actions), -math.inf, dtype=np.float64)
        means[pool_indices] = refine
        total_reuse = _reuse_total(coarse_reuse, refine_reuse)
        self.last_successor_reuse = total_reuse
        self._wide_tail_diagnostics = {
            "triggered": True,
            "recipe": asdict(cfg),
            "threshold": cfg.threshold,
            "coarse_worlds": len(coarse_worlds),
            "refine_worlds": len(refine_worlds),
            "coarse_action_count": len(actions),
            "pool_action_count": len(pool_indices),
            "coarse_evaluations": len(actions) * len(coarse_worlds),
            "refine_evaluations": len(pool_indices) * len(refine_worlds),
            "pool_indices": pool_indices,
            "ranking_basis": "remaining-world-mean",
            "successor_reuse": {
                "coarse": coarse_reuse,
                "refine": refine_reuse,
                "total": total_reuse,
            },
        }
        return means

    def _candidates(self, rnd, seat):
        self._wide_tail_diagnostics = None
        selected = super()._candidates(rnd, seat)
        detail = self.last_shortlist
        diagnostic = self._wide_tail_diagnostics
        if diagnostic is not None and detail is not None:
            shortlist_means = detail.get("shortlist_means") or []
            if not shortlist_means or not np.isfinite(np.asarray(shortlist_means, dtype=float)).all():
                raise ValueError("wide-tail selected means must be finite")
            detail["wide_tail"] = diagnostic
            detail["ranking_basis"] = "remaining-world-mean"
            detail["full_legal_world_means_complete"] = False
        return selected


__all__ = ["CWVWideTailBot", "CWVWideTailConfig"]
