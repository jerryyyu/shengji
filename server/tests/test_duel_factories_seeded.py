"""make_bot must forward seed= and must not swallow a constructor's TypeError.

A wrapper that accepts a seed and drops it runs an opponent on OS entropy while
the logs claim a seeded protocol; a retry on TypeError would hide a real bug
inside a bot constructor behind that same fallback.
"""
from __future__ import annotations

import pytest

from shengji.ai.registry import make_bot


def test_make_bot_forwards_seed_kwarg():
    assert make_bot("mc", seed=7).rng.getstate() == make_bot("mc", seed=7).rng.getstate()


def test_a_constructor_bug_is_not_swallowed():
    """A real TypeError inside a bot must propagate, not trigger a retry."""
    from shengji.ai.registry import REGISTRY

    def exploding(**kw):
        raise TypeError("bug inside the bot constructor")

    REGISTRY["__exploding__"] = exploding
    try:
        with pytest.raises(TypeError, match="bug inside"):
            make_bot("__exploding__", seed=1)
    finally:
        REGISTRY.pop("__exploding__", None)
