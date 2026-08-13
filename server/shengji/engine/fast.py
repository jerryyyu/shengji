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
  replacements (str in, str out, identical semantics incl. memo keys,
  defensive run copies, and exact IllegalPlay
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

from . import cards as _cards
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
    key contracts (a sorted multiset for decompose; exact caller order for the
    hotter tractor lookup) — so the invariant suite's cache audit and any
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
    _fast.set_points(bytes(_cards.points(c) for c in ID2CODE))
    decompose = _fast.decompose                    # combos.decompose
    find_tractor_runs = _fast.find_tractor_runs    # combos.find_tractor_runs
    suit_cards = _fast.suit_cards                  # legal.suit_cards
    decompose_matching = _fast.decompose_matching  # combos.decompose_matching
    pair_count = _fast.pair_count                  # combos.pair_count
    beats = _fast.beats                            # legal.beats
    uniform_suit = _fast.uniform_suit              # legal.uniform_suit
    check_in_hand = _fast.check_in_hand            # legal.check_in_hand
    validate_follow = _fast.validate_follow        # legal.validate_follow
    points = _fast.points                          # cards.points
    total_points = _fast.total_points              # cards.total_points
    heuristic_lowest = _fast.heuristic_lowest      # HeuristicBot._lowest core
    forced_follow = _fast.forced_follow            # HeuristicBot._forced_follow
    cheapest_winning = _fast.cheapest_winning      # HeuristicBot contest core
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
    points = _cards.points
    total_points = _cards.total_points
    heuristic_lowest = None
    forced_follow = None
    cheapest_winning = None
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
    ("points", _cards, "points"),
    ("total_points", _cards, "total_points"),
)


# Method drop-ins for HeuristicBot (phase 2 partial): thin wrappers that
# forward the per-instance VOID_DUMP flag into the kernels. Patched onto
# the CLASS by activate() (SmartBot/MCBot inherit; no subclass overrides
# these two — asserted at activation).
def _lowest_fast(self, cards, o, avoid_points=False, seek_points=False,
                 avoid=None):
    return _fast.heuristic_lowest(cards, o, self.VOID_DUMP, avoid_points,
                                  seek_points, avoid)


def _forced_follow_fast(self, hand, lead, o, prefer_points, avoid=None):
    return _fast.forced_follow(hand, lead, o, self.VOID_DUMP, prefer_points,
                               avoid)


def _lead_fast(self, rnd, seat):
    return _fast.heuristic_lead(self, rnd, seat)


def _cheapest_winning_fast(self, hand, lead, inc_suit, inc_top, o):
    # Engine-produced comparison tops are -1..15.  Keep the native call on
    # that exact domain; the method remains public/testable, so malformed or
    # arbitrarily large Python values must retain the pure implementation's
    # result/exception rather than being narrowed to C ``long``.
    if type(inc_top) is not int or not -1 <= inc_top <= 15:
        return _saved["HeuristicBot._cheapest_winning"](
            self, hand, lead, inc_suit, inc_top, o)
    return _fast.cheapest_winning(self, hand, lead, inc_suit, inc_top, o)


_METHOD_ROUTED = (
    # (save-key, class attr on HeuristicBot, wrapper,
    #  require-no-subclass-override).  A subclass's own `_lead` wins normal
    # Python dispatch and is therefore safe to preserve; the other wrappers
    # are shared policy primitives whose semantics must remain uniform.
    ("HeuristicBot._lowest", "_lowest", _lowest_fast, True),
    ("HeuristicBot._forced_follow", "_forced_follow", _forced_follow_fast,
     True),
    ("HeuristicBot._lead", "_lead", _lead_fast, False),
    ("HeuristicBot._cheapest_winning", "_cheapest_winning",
     _cheapest_winning_fast, True),
)


def activate() -> bool:
    """Route the ported functions (_ROUTED) and HeuristicBot methods
    (_METHOD_ROUTED) through the kernels.

    Returns True when the fast path is (already) active, False when the
    extension isn't built. Idempotent; undo with deactivate().
    """
    if not HAVE_FAST:
        return False
    if _saved:
        return True
    from ..ai.heuristic import HeuristicBot  # deferred: ai imports engine
    mapping = {}
    for key, mod, attr in _ROUTED:
        _saved[key] = getattr(mod, attr)
        mapping[_saved[key]] = globals()[key]
    _rebind(mapping)
    for key, attr, wrapper, require_unoverridden in _METHOD_ROUTED:
        # The strict wrappers are shared policy primitives; refuse a subclass
        # override instead of silently changing its meaning.  `_lead` is a
        # normal dispatch leaf: subclass overrides continue to win through
        # Python's method resolution and are intentionally allowed.
        if require_unoverridden:
            assert all(attr not in vars(k)
                       for k in _subclasses(HeuristicBot)), \
                f"a HeuristicBot subclass overrides {attr}; fast path unsafe"
        _saved[key] = getattr(HeuristicBot, attr)
        setattr(HeuristicBot, attr, wrapper)
    return True


def _subclasses(cls) -> list[type]:
    out = []
    stack = list(cls.__subclasses__())
    while stack:
        k = stack.pop()
        out.append(k)
        stack.extend(k.__subclasses__())
    return out


def deactivate() -> None:
    if not _saved:
        return
    from ..ai.heuristic import HeuristicBot
    for key, attr, _, _ in _METHOD_ROUTED:
        setattr(HeuristicBot, attr, _saved.pop(key))
    _rebind({globals()[key]: _saved.pop(key) for key, _, _ in _ROUTED})
