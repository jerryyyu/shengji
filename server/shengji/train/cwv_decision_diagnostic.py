"""Observe unchanged W32; score a bounded action menu on independent worlds.

This is an offline diagnostic, not a registered policy or an optimal oracle.
The reference uses production's heuristic continuation. Its disagreement with
the model can include continuation-policy mismatch, not just prediction error.
"""
from __future__ import annotations

import copy
import hashlib
import json
import time

import numpy as np

from ..ai.cwv_policy import sample_worlds
from ..ai.mcbot import _child_seed
from ..ai.registry import make_bot
from ..luna.game import _round_from_snapshot
from ..rl.value_afterstate import category_signed_level, signed_level_category
from .cwv_shortlist import CWVShortlistBot, CWVShortlistConfig


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


class ObservedW32(CWVShortlistBot):
    """Retain values already computed by the real consumer; change no choice."""

    def _means(self, rnd, seat, actions, worlds):
        means = super()._means(rnd, seat, actions, worlds)
        self.ranked_actions = [list(a) for a in actions]
        self.ranked_means = means.copy()
        self.ranking_worlds_sha256 = digest(worlds)
        return means


def reference_metrics(levels, model_scores, retained, chosen, incumbent):
    """Finite-menu regret plus independently evaluated reference selections.

    The descriptive maximum is optimistic. The two-fold opportunity contrast
    selects on one half of the worlds and evaluates on the other; it may be
    negative and must not be clamped. Neither is gameplay strength.
    """
    levels = np.asarray(levels, dtype=float)
    scores = np.asarray(model_scores, dtype=float)
    if (levels.ndim != 2 or len(levels) < 4 or len(levels) % 2 or levels.shape[1] < 2 or
            scores.shape != (levels.shape[1],) or
            not np.isfinite(levels).all() or not np.isfinite(scores).all()):
        raise ValueError("finite even world/action matrix and aligned model scores required")
    if not retained or chosen not in retained or incumbent not in retained:
        raise ValueError("retained set must include chosen and incumbent")
    if len(set(retained)) != len(retained) or any(
            type(i) is not int or not 0 <= i < levels.shape[1] for i in retained):
        raise ValueError("invalid retained indices")
    means = levels.mean(axis=0)
    best_retained = max(means[i] for i in retained)
    gaps = means - means[incumbent]
    model_gaps = scores - scores[incumbent]
    non_incumbent = np.arange(len(scores)) != incumbent
    folds = []
    for train, evaluate in ((levels[::2], levels[1::2]), (levels[1::2], levels[::2])):
        select_means, eval_means = train.mean(axis=0), evaluate.mean(axis=0)
        best_menu = int(np.argmax(select_means))
        best_keep = max(retained, key=lambda i: (select_means[i], -i))
        folds.append({
            "menu_selected": best_menu, "retained_selected": best_keep,
            "coverage_gap": float(eval_means[best_menu] - eval_means[best_keep]),
            "selection_gap": float(eval_means[best_keep] - eval_means[chosen]),
            "total_gap": float(eval_means[best_menu] - eval_means[chosen]),
        })
    return {
        "reference_means": means.tolist(),
        "final_gain_vs_incumbent": float(means[chosen] - means[incumbent]),
        "descriptive_coverage_regret": float(means.max() - best_retained),
        "descriptive_selection_regret": float(best_retained - means[chosen]),
        "model_action_gap_mae": float(np.abs(model_gaps[non_incumbent] - gaps[non_incumbent]).mean()),
        "zero_action_gap_mae": float(np.abs(gaps[non_incumbent]).mean()),
        "crossfit": {name: float(np.mean([f[name] for f in folds]))
                     for name in ("coverage_gap", "selection_gap", "total_gap")},
        "crossfit_folds": folds,
    }


def diagnose(entry, evaluator, *, seed=20260909, reference_worlds=1024,
             ranking_worlds=32, selection_worlds=30, report_worlds=300):
    if entry.get("provenance", {}).get("split") != "fit":
        raise ValueError("diagnosis requires an explicitly fit-only root")
    for name, value in (("ranking", ranking_worlds), ("selection", selection_worlds),
                        ("report", report_worlds), ("reference", reference_worlds)):
        if type(value) is not int or value < 1:
            raise ValueError(f"{name} worlds must be a positive integer")
    if reference_worlds < 4 or reference_worlds % 2:
        raise ValueError("reference worlds must be even and >=4")
    start = time.perf_counter()
    rnd = _round_from_snapshot(entry["snapshot"])
    seat = rnd.turn
    root_seed = int(entry["id"][:15], 16) ^ seed
    bot = ObservedW32(evaluator, seed=root_seed, reuse_successors=True,
                      config=CWVShortlistConfig(worlds=ranking_worlds,
                                                selection_worlds=selection_worlds))
    bot.REPORT_FOLD_WORLDS = report_worlds
    pick = bot.decide_play(copy.deepcopy(rnd), seat)
    if not hasattr(bot, "ranked_actions"):
        raise ValueError("root has no model-ranked contested ballot")
    rec, detail = bot.last_decision_record, bot.last_shortlist
    actions, scores = bot.ranked_actions, bot.ranked_means
    keys = [tuple(sorted(a)) for a in actions]
    lookup = {key: i for i, key in enumerate(keys)}
    retained = [lookup[tuple(sorted(a))] for a in detail["shortlist"]]
    # Fixed diagnostic menu: actual W32 five, next ranked alternatives through
    # rank eight, and the production ballot. No reference outcome chooses it.
    ranked = sorted((i for i in range(len(keys)) if i != retained[0]),
                    key=lambda i: (-scores[i], keys[i]))
    menu = sorted(set(retained) | set(ranked[:8]) |
                  {lookup[tuple(a)] for a in detail["production_keys"]})
    menu_lookup = {index: offset for offset, index in enumerate(menu)}
    reference_seed = _child_seed((root_seed,), "w32-decision-independent-reference-v1")
    ref_bot = make_bot("mc-s0-report-lcb", seed=reference_seed)
    worlds, attempts = sample_worlds(ref_bot, rnd, seat, reference_worlds)
    if len(worlds) != reference_worlds:
        raise ValueError("reference world population underfilled")
    points = np.empty((reference_worlds, len(menu)))
    levels = np.empty_like(points)
    attack = bool(rnd.is_attacker(seat))
    for w, (hands, burial) in enumerate(worlds):
        hidden = {s: list(hands[s]) for s in range(4) if s != seat}
        for col, index in enumerate(menu):
            value = ref_bot._rollout(rnd, seat, hidden, burial, actions[index])
            if not np.isfinite(value) or not float(value).is_integer():
                raise ValueError("reference rollout must return integral attacker points")
            points[w, col] = value
            levels[w, col] = category_signed_level(signed_level_category(int(value), attack))
    metrics = reference_metrics(levels, scores[menu],
        [menu_lookup[i] for i in retained], menu_lookup[lookup[tuple(sorted(pick))]],
        menu_lookup[retained[0]])
    return {
        "schema": "cwv-decision-diagnostic-v1", "root_id": entry["id"],
        "deal_key": entry["deal_key"], "root_sha256": digest(entry),
        "source_policy": entry["provenance"].get("source_policy"),
        "model": evaluator.identity(), "seed": root_seed,
        "scope": "FIT finite-menu diagnostic under heuristic continuation; not optimal play or strength",
        "recipe": {"W": ranking_worlds, "K": 4, "N": selection_worlds, "R": report_worlds},
        "legal_count": len(actions), "actions": actions, "model_scores": scores.tolist(),
        "retained_indices": retained, "played": pick, "menu_indices": menu,
        "ranking_worlds_sha256": bot.ranking_worlds_sha256,
        "reference": {"policy": "production heuristic continuation", "seed": reference_seed,
                      "worlds": reference_worlds, "attempts": attempts,
                      "worlds_sha256": digest(worlds), "points": points.tolist(),
                      "levels": levels.tolist()},
        "selection": {k: rec.get(k) for k in ("means", "paired_se", "n_by_candidate",
                      "report_candidate_index", "report_fold", "played_index", "reason", "work")},
        "metrics": metrics, "wall_seconds": time.perf_counter() - start,
    }
