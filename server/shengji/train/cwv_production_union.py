"""DEV-only CWV shortlist with production-ballot coverage restored.

The learned shortlist remains the incumbent plus its four model-ranked
alternatives.  This opt-in subclass only appends production candidates that
the learned shortlist omitted; production selection, reporting, and rollout
code stay inherited and untouched.
"""

from __future__ import annotations

from .cwv_shortlist import CWVShortlistBot, CWVShortlistConfig


class CWVProductionUnionBot(CWVShortlistBot):
    """CWV shortlist unioned with missing canonical production actions."""

    PRODUCTION_UNION = True
    MODEL_ALTERNATIVES = 4

    def __init__(self, evaluator, *, seed=0, config=None, reuse_successors=False):
        config = config or CWVShortlistConfig()
        if config.uniform:
            raise ValueError("CWV production union requires the learned shortlist")
        if config.alternatives != self.MODEL_ALTERNATIVES:
            raise ValueError("CWV production union requires exactly four model alternatives")
        self._union_action_map = None
        super().__init__(evaluator, seed=seed, config=config,
                         reuse_successors=reuse_successors)

    def _means(self, rnd, seat, actions, worlds):
        means = super()._means(rnd, seat, actions, worlds)
        # This is only a read-only index of the one model pass.  Unioning
        # production actions must never issue another evaluator call.
        self._union_action_map = {
            tuple(sorted(action)): (index, float(means[index]), list(action))
            for index, action in enumerate(actions)
        }
        return means

    def _candidates(self, rnd, seat):
        self._union_action_map = None
        kept = super()._candidates(rnd, seat)
        detail = self.last_shortlist
        if detail is None:
            return kept

        kept_keys = {tuple(sorted(action)) for action in kept}
        production_keys = {
            tuple(sorted(action)) for action in detail.get("production_keys", ())
        }
        missing = sorted(production_keys - kept_keys)
        additions = []
        for key in missing:
            indexed = self._union_action_map.get(key) if self._union_action_map else None
            if indexed is None:
                raise ValueError("CWV production union action was absent from model index")
            additions.append(indexed)

        if additions:
            kept.extend(item[2] for item in additions)
            detail["shortlist"] = [list(action) for action in kept]
            detail["shortlist_indices"] = list(detail["shortlist_indices"]) + [
                item[0] for item in additions
            ]
            detail["shortlist_means"] = list(detail["shortlist_means"] or []) + [
                item[1] for item in additions
            ]
            detail["counts"]["shortlisted_actions"] += len(additions)
            self.shortlist_counts["shortlisted_actions"] += len(additions)

        # Separate, auditable mechanism metadata.  ``offballot_kept`` is
        # intentionally untouched: every appended action is on production's
        # ballot, while K/model ordering above remains exactly unchanged.
        detail["production_union"] = True
        detail["production_union_added"] = len(additions)
        return kept

    def decide_play(self, rnd, seat):
        played = super().decide_play(rnd, seat)
        detail = self.last_shortlist
        if detail is not None and self.last_decision_record is not None:
            self.last_decision_record["production_union"] = True
            self.last_decision_record["production_union_added"] = detail[
                "production_union_added"]
        return played


__all__ = ["CWVProductionUnionBot"]
