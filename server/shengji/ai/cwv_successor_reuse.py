"""Bounded reuse of complete-world afterstate leaves within one decision.

The cache is deliberately scoped to one root, seat, and sampled world.  It
does not collapse model rows: callers still submit every original action and
world row, while duplicate accepted actions can share the finished leaf and
its separately memoized input tensors.
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Any, Callable, Sequence


class WorldSuccessorCache:
    """Reuse finished successors for one fixed root/world instance."""

    def __init__(self, root, seat: int, hands: Sequence[Sequence[str]],
                 buried: Sequence[str], max_entries: int = 128, *,
                 prepare_leads: bool = True):
        if type(max_entries) is not int or max_entries < 1:
            raise ValueError("max_entries must be a positive integer")
        if type(prepare_leads) is not bool:
            raise ValueError("prepare_leads must be boolean")
        self.root = root
        self.seat = seat
        self.hands = [list(hand) for hand in hands]
        self.buried = list(buried)
        self.max_entries = max_entries
        self._lead_validation = None
        # Preparation is optional; preserve the cache's lazy-root contract
        # when a caller supplies a root without engine decision metadata.
        trick = getattr(root, "trick", None)
        ordering = getattr(root, "ordering", None)
        if (prepare_leads and trick is not None
                and not trick.plays and ordering is not None):
            from ..engine.legal import PreparedLeadValidation
            others = [self.hands[s] for s in range(4) if s != seat]
            self._lead_validation = PreparedLeadValidation(
                self.hands[seat], others, ordering)
        self._leaves: OrderedDict[tuple[str, ...], Any] = OrderedDict()
        self.root_actions = 0
        self.leaf_hits = 0
        self.leaf_completions = 0
        self.peak_entries = 0

    @property
    def counters(self) -> dict[str, int]:
        return {
            "root_actions": self.root_actions,
            "leaf_hits": self.leaf_hits,
            "leaf_completions": self.leaf_completions,
            "peak_entries": self.peak_entries,
        }

    @property
    def entries(self) -> int:
        return len(self._leaves)

    @property
    def lead_validation(self):
        """The root-only prepared context, when this cache enabled it."""
        return self._lead_validation

    def leaf(self, candidate: Sequence[str]):
        """Validate every submitted action, reusing only its finished leaf."""
        # Local imports avoid making cwv_policy import this module recursively.
        from .cwv_policy import afterstate, finish_current_trick
        from ..engine.round import actual_play_after

        self.root_actions += 1
        kwargs = {}
        if self._lead_validation is not None:
            kwargs["_lead_validation"] = self._lead_validation
        clone = afterstate(
            self.root, self.seat, self.hands, self.buried, candidate,
            finish_trick=False, **kwargs)
        accepted = tuple(actual_play_after(
            clone, self.seat, self.root.last_trick))
        cached = self._leaves.get(accepted)
        if cached is not None:
            self.leaf_hits += 1
            self._leaves.move_to_end(accepted)
            return cached

        finish_current_trick(clone)
        self.leaf_completions += 1
        self._leaves[accepted] = clone
        self._leaves.move_to_end(accepted)
        if len(self._leaves) > self.max_entries:
            self._leaves.popitem(last=False)
        self.peak_entries = max(self.peak_entries, len(self._leaves))
        return clone


class TensorInputCache:
    """Bounded tensor reuse keyed by encoder, seat, and exact leaf object."""

    def __init__(self, max_entries: int = 128):
        if type(max_entries) is not int or max_entries < 1:
            raise ValueError("max_entries must be a positive integer")
        self.max_entries = max_entries
        # (encoder id, seat, leaf id) -> (encoder, leaf, tensors). Retaining
        # both objects prevents Python id reuse from colliding with a live key.
        self._entries: OrderedDict[tuple[int, int, int], tuple[Any, Any, Any]] = OrderedDict()
        self.hits = 0
        self.completions = 0
        self.peak_entries = 0

    @property
    def entries(self) -> int:
        return len(self._entries)

    @property
    def counters(self) -> dict[str, int]:
        return {
            "hits": self.hits,
            "completions": self.completions,
            "peak_entries": self.peak_entries,
        }

    def encode(self, leaf, encoder: Callable[[Any, int], Any], seat: int):
        """Encode once for one exact ``(encoder, seat, leaf)`` identity."""
        key = (id(encoder), seat, id(leaf))
        cached = self._entries.get(key)
        if cached is not None and cached[0] is encoder and cached[1] is leaf:
            self.hits += 1
            self._entries.move_to_end(key)
            return cached[2]

        tensors = encoder(leaf, seat)
        # Cached inputs are read-only while the parent scores them; no copy is
        # made, and the cache never mutates the leaf or its source round.
        for name in ("public", "history", "world", "perspective"):
            value = getattr(tensors, name, None)
            if hasattr(value, "setflags"):
                value.setflags(write=False)
        self.completions += 1
        self._entries[key] = (encoder, leaf, tensors)
        self._entries.move_to_end(key)
        if len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)
        self.peak_entries = max(self.peak_entries, len(self._entries))
        return tensors


__all__ = ["TensorInputCache", "WorldSuccessorCache"]
