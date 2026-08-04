"""Every duel script's ACTUAL factory must reproduce under _seeded().

The unseeded-opponent defect has now appeared twice: once in play_pairing
(fixed 2026-08-03) and once at the call site, where scripts passed
`lambda **k: make_bot("mc")` — a lambda that accepts a seed and drops it, so
_seeded() never reached its fallback and every MC opponent ran on OS entropy
while the logs claimed a seeded protocol (Codex, 2026-08-04).

This tests the factory FORM the scripts use, not a convenient one.
"""
from __future__ import annotations

import pytest

from shengji.ai.registry import make_bot
from shengji.ai.tournament import _seeded

# Exactly the shape used in v11_extend.py / gate_duel.py / vleaf_settle.py.
SCRIPT_FACTORY = staticmethod(lambda name: (lambda **kw: make_bot(name, **kw)))


@pytest.mark.parametrize("name", ["mc", "smart", "heuristic",
                                  "mc-vleaf-v7w-ep02"])
def test_script_factory_reproduces_under_seeded(name):
    make = lambda **kw: make_bot(name, **kw)      # noqa: E731
    a, b = _seeded(make, 4242), _seeded(make, 4242)
    if not hasattr(a, "rng"):
        pytest.skip(f"{name} has no rng to seed")
    assert a.rng.getstate() == b.rng.getstate(), \
        f"{name}: same seed produced different RNG state — opponent is unseeded"


def test_different_seeds_actually_differ():
    make = lambda **kw: make_bot("mc", **kw)      # noqa: E731
    assert _seeded(make, 1).rng.getstate() != _seeded(make, 2).rng.getstate()


def test_make_bot_forwards_seed_kwarg():
    assert make_bot("mc", seed=7).rng.getstate() == make_bot("mc", seed=7).rng.getstate()
