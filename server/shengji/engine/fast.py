"""Fast-path routing for the engine hot loop (prototype, PERF.md #2+#3).

The compiled kernels in ``_fast`` (Cython) work on u8 card ids; this module
owns the str<->int boundary so NOTHING outside sees int cards:

- ``ID2CODE``/``CODE2ID``: fixed global id assignment (54 codes, sorted, so
  id order == lexicographic code order).
- a per-Ordering ``ctx`` tuple (caches + level/eff-suit byte tables) built
  lazily and stored on the Ordering instance — same lifetime as the pure
  decompose memo.
- ``decompose`` / ``find_tractor_runs`` / ``suit_cards`` are drop-in
  replacements (str in, str out, identical semantics incl. the memo's
  first-caller-order freezing and defensive run copies). RULES stay in
  Python: validate_lead/validate_follow/beats/decompose_matching untouched;
  pure Python remains the reference implementation.
- ``activate()`` swaps the three functions in everywhere (module attrs AND
  ``from x import y`` aliases across loaded shengji modules); modules
  imported after activation bind the patched attributes automatically.
- If the compiled module is missing, everything falls back to pure Python
  and ``activate()`` is a no-op returning False.

Build:  cd server && uv run python setup.py build_ext --inplace
Tests:  SHENGJI_FAST=1 uv run python -m pytest tests/ -q   (fast path active)
"""

from __future__ import annotations

import sys

from . import combos, legal
from .cards import Ordering, make_deck
from .combos import Decomposition

try:
    from . import _fast  # compiled extension; see setup.py
    HAVE_FAST = True
except ImportError:  # not built — pure Python fallback
    _fast = None
    HAVE_FAST = False

ID2CODE: list[str] = sorted(set(make_deck()))  # 54 codes, deterministic ids
CODE2ID: dict[str, int] = {c: i for i, c in enumerate(ID2CODE)}
EFF_ID = {"S": 0, "H": 1, "C": 2, "D": 3, "T": 4}


def _ctx(ordering: Ordering) -> tuple:
    """(dcache, trcache, lvl_bytes, eff_bytes, code2id) per Ordering."""
    ctx = getattr(ordering, "_fast_ctx", None)
    if ctx is None:
        ctx = ({}, {},
               bytes(ordering.level(c) for c in ID2CODE),
               bytes(EFF_ID[ordering.eff_suit(c)] for c in ID2CODE),
               CODE2ID)
        ordering._fast_ctx = ctx
    return ctx


# ---------------------------------------------------------- drop-in functions
# The compiled entry points are the drop-ins themselves (no Python wrapper
# frame on the hot path — 2.9M calls/round made the frame itself a hotspot);
# they fetch/lazy-build the ctx via the builder registered below. Signatures
# and semantics match the pure functions exactly.

if HAVE_FAST:
    _fast.set_ctx_builder(_ctx)
    decompose = _fast.decompose                    # combos.decompose
    find_tractor_runs = _fast.find_tractor_runs    # combos.find_tractor_runs
    suit_cards = _fast.suit_cards                  # legal.suit_cards
    decompose_uncached = _fast.decompose_uncached  # combos._decompose_uncached
    find_tractor_runs_uncached = _fast.find_tractor_runs_uncached
else:  # pure-Python fallbacks
    decompose = combos.decompose
    find_tractor_runs = combos.find_tractor_runs
    suit_cards = legal.suit_cards
    decompose_uncached = combos._decompose_uncached
    find_tractor_runs_uncached = combos._find_tractor_runs_uncached


# ------------------------------------------------------------------ activation

_saved: dict[str, object] = {}


def _rebind(mapping: dict) -> None:
    """Swap function objects in every loaded shengji module — covers both
    module attributes and ``from x import y`` aliases (heuristic/mcbot/...
    bind these names at import time)."""
    skip = (sys.modules.get(__name__), _fast)  # never rewrite our own bindings
    for name, mod in list(sys.modules.items()):
        if not name.startswith("shengji") or mod is None or mod in skip:
            continue
        for attr, val in list(vars(mod).items()):
            try:
                repl = mapping.get(val)
            except TypeError:  # unhashable attr value
                continue
            if repl is not None:
                setattr(mod, attr, repl)


def activate() -> bool:
    """Route decompose / find_tractor_runs / suit_cards through the kernels.

    Returns True when the fast path is (already) active, False when the
    extension isn't built. Idempotent; undo with deactivate().
    """
    if not HAVE_FAST:
        return False
    if _saved:
        return True
    _saved["decompose"] = combos.decompose
    _saved["find_tractor_runs"] = combos.find_tractor_runs
    _saved["suit_cards"] = legal.suit_cards
    _rebind({combos.decompose: decompose,
             combos.find_tractor_runs: find_tractor_runs,
             legal.suit_cards: suit_cards})
    return True


def deactivate() -> None:
    if _saved:
        _rebind({decompose: _saved.pop("decompose"),
                 find_tractor_runs: _saved.pop("find_tractor_runs"),
                 suit_cards: _saved.pop("suit_cards")})
