"""Fast-path routing for the engine hot loop (prototype, PERF.md #2+#3).

The compiled kernels in ``_fast`` (Cython) work on u8 card ids; this module
owns the str<->int boundary so NOTHING outside sees int cards:

- ``ID2CODE``/``CODE2ID``: fixed global id assignment (54 codes, sorted, so
  id order == lexicographic code order).
- a per-Ordering ``ctx`` tuple (caches + level/eff-suit byte tables) built
  lazily and stored on the Ordering instance — same lifetime as the pure
  decompose memo.
- ``decompose`` / ``find_tractor_runs`` / ``suit_cards`` and the RULES
  functions ``decompose_matching`` / ``beats`` / ``validate_follow`` /
  ``pair_count`` / ``uniform_suit`` / ``check_in_hand`` are drop-in
  replacements (str in, str out, identical semantics incl. the memos'
  caller-order keys, defensive run copies, and exact IllegalPlay
  messages). validate_lead stays pure (cold path; runs the ported
  helpers via rebinding). Pure Python remains the reference
  implementation everywhere.
- ``activate()`` swaps the functions in everywhere (module attrs AND
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
    """(dcache, trcache, lvl_bytes, eff_bytes, code2id) per Ordering.

    dcache/trcache are the SAME dicts the pure implementations use
    (``ordering._dcache`` / ``ordering._trcache``), with the same
    caller-order key contract (``tuple(cards)`` / ``(tuple(cards), k)``,
    CORRECTNESS.md 08-03) — so the invariant suite's cache audit and any
    interleaved pure/fast calls see one coherent memo."""
    ctx = getattr(ordering, "_fast_ctx", None)
    if ctx is None:
        dcache = getattr(ordering, "_dcache", None)
        if dcache is None:
            dcache = {}
            ordering._dcache = dcache
        trcache = getattr(ordering, "_trcache", None)
        if trcache is None:
            trcache = {}
            ordering._trcache = trcache
        ctx = (dcache, trcache,
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
    _fast.set_code2id(CODE2ID)
    decompose = _fast.decompose                    # combos.decompose
    find_tractor_runs = _fast.find_tractor_runs    # combos.find_tractor_runs
    suit_cards = _fast.suit_cards                  # legal.suit_cards
    decompose_matching = _fast.decompose_matching  # combos.decompose_matching
    pair_count = _fast.pair_count                  # combos.pair_count
    beats = _fast.beats                            # legal.beats
    uniform_suit = _fast.uniform_suit              # legal.uniform_suit
    check_in_hand = _fast.check_in_hand            # legal.check_in_hand
    validate_follow = _fast.validate_follow        # legal.validate_follow
    decompose_uncached = _fast.decompose_uncached  # combos._decompose_uncached
    find_tractor_runs_uncached = _fast.find_tractor_runs_uncached
else:  # pure-Python fallbacks
    decompose = combos.decompose
    find_tractor_runs = combos.find_tractor_runs
    suit_cards = legal.suit_cards
    decompose_matching = combos.decompose_matching
    pair_count = combos.pair_count
    beats = legal.beats
    uniform_suit = legal.uniform_suit
    check_in_hand = legal.check_in_hand
    validate_follow = legal.validate_follow
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


_ROUTED = (
    # (save-key, pure module, attr) — the compiled drop-ins swap in for these.
    ("decompose", combos, "decompose"),
    ("find_tractor_runs", combos, "find_tractor_runs"),
    ("decompose_matching", combos, "decompose_matching"),
    ("pair_count", combos, "pair_count"),
    ("suit_cards", legal, "suit_cards"),
    ("beats", legal, "beats"),
    ("uniform_suit", legal, "uniform_suit"),
    ("check_in_hand", legal, "check_in_hand"),
    ("validate_follow", legal, "validate_follow"),
)


def activate() -> bool:
    """Route the ported functions (see _ROUTED) through the kernels.

    Returns True when the fast path is (already) active, False when the
    extension isn't built. Idempotent; undo with deactivate().
    """
    if not HAVE_FAST:
        return False
    if _saved:
        return True
    mapping = {}
    for key, mod, attr in _ROUTED:
        _saved[key] = getattr(mod, attr)
        mapping[_saved[key]] = globals()[key]
    _rebind(mapping)
    return True


def deactivate() -> None:
    if _saved:
        _rebind({globals()[key]: _saved.pop(key) for key, _, _ in _ROUTED})
