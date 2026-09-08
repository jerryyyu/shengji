"""DEV consumer composition: exhaustive CWV shortlist plus a points leaf.

This composes the existing full-legal shortlist and S0 MC-LCB search.  The
points leaf only replaces the heuristic continuation after the requested
horizon; nominations, sampled worlds, batching, static successor reuse, and
production reporting remain inherited unchanged.
"""
from __future__ import annotations

from .cwv_shortlist import CWVShortlistBot
from .leaf_policy import MCValueLeafSearch


class LastActorPointsLeaf:
    """Encode the player who just acted; still predict global attacker points."""

    def __init__(self, leaf):
        self.leaf = leaf
        self.kind = getattr(leaf, "kind", "cwv-last-actor")
        self.points_clamp = getattr(leaf, "points_clamp", None)

    def final_attacker_points(self, clone, _mover):
        plays = clone.trick.plays if clone.trick is not None else []
        if not plays and clone.history:
            plays = clone.history[-1].plays
        if not plays:
            raise ValueError("last-actor leaf requires a post-action state")
        return self.leaf.final_attacker_points(clone, plays[-1].seat)


class CWVPointsLeafShortlistBot(MCValueLeafSearch, CWVShortlistBot):
    """Full-legal CWV shortlist consumer with a T1 points continuation."""

    def __init__(self, evaluator, leaf, *, seed=0, config=None,
                 reuse_successors=False, leaf_tricks=1,
                 leaf_view="last_actor"):
        if leaf_view not in ("mover", "last_actor"):
            raise ValueError("leaf_view must be mover or last_actor")
        CWVShortlistBot.__init__(
            self, evaluator, seed=seed, config=config,
            reuse_successors=reuse_successors)
        self.raw_points_leaf = leaf
        if leaf_view == "last_actor":
            leaf = LastActorPointsLeaf(leaf)
        self.leaf_view = leaf_view
        self._configure_leaf(leaf, leaf_tricks, "all")
        self.policy_name = (
            f"mc-s0-report-lcb+cwv-shortlist+points-leaf-t{leaf_tricks}-{leaf_view}")
