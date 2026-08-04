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

# The factory shape those duel runners used. The runners themselves were
# retired into shengji.evaluation on 2026-08-04; this guard stays because the
# seed-dropping lambda it catches lived in five of them simultaneously, and
# make_bot is still called this way from scripts. See also
# tests/test_evaluation_lib.py::test_run_arm_gives_every_seat_a_distinct_seed.
SCRIPT_FACTORY = staticmethod(lambda name: (lambda **kw: make_bot(name, **kw)))


@pytest.mark.parametrize("name", ["mc", "smart", "heuristic",
                                  "mc-vleaf-v7w-ep02"])
def test_script_factory_reproduces_under_seeded(name, monkeypatch):
    # v7w predates checkpoint ballot provenance, so loading it is a deliberate
    # research-only exception rather than a default pass. Declared per-use and
    # narrowly: a blanket warning is what let three runs score action sets they
    # were never trained on (Codex). This test checks RNG seeding, not strength.
    monkeypatch.setenv("SHENGJI_ALLOW_BALLOT_MISMATCH", "1")
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


@pytest.mark.parametrize("opp", ["mc", "smart"])
def test_full_pairing_reproduces_through_the_script_lambda(opp):
    """End-to-end: the same seeds must give the same SCORE, twice.

    Comparing two fresh RNG states only proves the constructor took a seed.
    It would not catch a factory that seeds correctly and then, say, reseeds
    from entropy on first use (Codex, 2026-08-04).
    """
    from shengji.ai.tournament import play_pairing

    make_a = lambda **kw: make_bot("heuristic", **kw)   # noqa: E731
    make_b = lambda **kw: make_bot(opp, **kw)           # noqa: E731
    first = play_pairing(make_a, make_b, 3, 555_000)
    second = play_pairing(make_a, make_b, 3, 555_000)
    assert first == second, f"same seeds gave {first} then {second}"


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
