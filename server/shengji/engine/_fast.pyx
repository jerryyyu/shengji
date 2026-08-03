# cython: language_level=3, boundscheck=False, wraparound=False
"""Cython hot-path kernels for combos.py / legal.py (PERF.md #2+#3).

Cards are u8 ids (index into fast.ID2CODE, 54 codes sorted lexicographically)
INTERNALLY only; every public function takes and returns str card codes —
shengji/engine/fast.py owns the tables and passes them in via a per-Ordering
``ctx`` tuple: (dcache, trcache, lvl_bytes, eff_bytes, code2id).

CORRECTNESS CONTRACT: byte-identical ports of combos.decompose /
combos.find_tractor_runs / legal.suit_cards / combos.decompose_matching /
legal.beats (and helpers), including order sensitivity: Counter insertion
order == first occurrence in the input list, pop(0)/pop() consumption,
first-longest-run tie-break, the stable final sort, and defensive copies
of cached tractor runs. Memo semantics follow the CALLER-ORDER contract
(CORRECTNESS.md incident 08-03): keys are ``tuple(cards)`` in the exact
input order — greedy/backtracking splits are order-dependent when distinct
codes share a level, so anagram orders may NOT share a cache entry — and
the cache dicts are the SAME ``ordering._dcache`` / ``ordering._trcache``
dicts the pure implementations use (the invariant suite audits them by
name and key shape). tests/test_fast_parity.py enforces parity on random
hands; the golden-history suite enforces it end-to-end.
"""

from cpython.bytes cimport PyBytes_AS_STRING
from cpython.dict cimport PyDict_GetItem
from cpython.object cimport PyObject
from libc.string cimport memset

from shengji.engine.combos import Component, Decomposition

cdef enum:
    # Levels are 0..15 (12 plain + rank-off/rank-trump/LJ/BJ); <=4 codes can
    # share a level (off-suit trump-rank cards, all rank cards in no-trump).
    MAX_LEVEL = 16
    MAX_PER_LEVEL = 6
    N_CODES = 54
    MAX_CARDS = 128   # plays/hands never exceed 33

cdef object KIND_SINGLE = "single"
cdef object KIND_PAIR = "pair"
cdef object KIND_TRACTOR = "tractor"

EFF_ID = {"S": 0, "H": 1, "C": 2, "D": 3, "T": 4}

# fast.py registers its per-Ordering ctx builder here (avoids a circular
# import); ctx = (dcache, trcache, lvl_bytes, eff_bytes, code2id).
cdef object _ctx_builder = None


def set_ctx_builder(fn):
    global _ctx_builder
    _ctx_builder = fn


cdef inline tuple _get_ctx(object ordering):
    ctx = getattr(ordering, "_fast_ctx", None)
    if ctx is None:
        ctx = _ctx_builder(ordering)
    return <tuple>ctx


def _comp_key(c):
    # (pair_len, top, seq, cards) -> stable sort by (-pair_len, -top)
    return (-c[0], -c[1], c[2])


cdef Py_ssize_t _ids_of(list cards, dict code2id, unsigned char *ids) except -1:
    cdef Py_ssize_t n = len(cards), i
    if n > MAX_CARDS:
        raise ValueError("play too large")
    for i in range(n):
        ids[i] = <unsigned char><int>code2id[cards[i]]
    return n


cdef object _decompose_core(list cards, const unsigned char *ids,
                            Py_ssize_t n, const unsigned char *lvl):
    """Port of combos._decompose_uncached. Returns a Decomposition holding
    the input's own str objects (first occurrence per code, like Counter)."""
    cdef int cnt[N_CODES]
    cdef int order[N_CODES]        # distinct ids, first-occurrence order
    cdef int lev_codes[MAX_LEVEL][MAX_PER_LEVEL]
    cdef int lev_n[MAX_LEVEL]
    cdef int n_order = 0, pairs_left = 0
    cdef int j, c, L, best_start, best_len, seq
    cdef Py_ssize_t i
    cdef list objmap = [None] * N_CODES  # id -> first str object seen

    memset(cnt, 0, sizeof(cnt))
    memset(lev_n, 0, sizeof(lev_n))
    for i in range(n):
        c = ids[i]
        if cnt[c] == 0:
            order[n_order] = c
            n_order += 1
            objmap[c] = cards[i]
        cnt[c] += 1
    # Counter.items() order == first occurrence: fill per-level pair lists
    # in that order (matters when trump-rank pairs share a level).
    for j in range(n_order):
        c = order[j]
        if cnt[c] >= 2:
            L = lvl[c]
            lev_codes[L][lev_n[L]] = c
            lev_n[L] += 1
            pairs_left += 1

    spec = []
    seq = 0
    # Greedy: repeatedly take the longest run of consecutive non-empty
    # levels (first-longest on ties), consuming one pair per level.
    while pairs_left > 0:
        best_start = -1
        best_len = 0
        j = 0
        while j < MAX_LEVEL:
            if lev_n[j] > 0:
                L = j
                while L + 1 < MAX_LEVEL and lev_n[L + 1] > 0:
                    L += 1
                if L - j + 1 > best_len:
                    best_len = L - j + 1
                    best_start = j
                j = L + 1
            else:
                j += 1
        comp_cards = []
        for L in range(best_start, best_start + best_len):
            c = lev_codes[L][0]          # pop(0) semantics
            for j in range(1, lev_n[L]):
                lev_codes[L][j - 1] = lev_codes[L][j]
            lev_n[L] -= 1
            pairs_left -= 1
            comp_cards.append(objmap[c])
            comp_cards.append(objmap[c])
        spec.append((best_len, best_start + best_len - 1, seq, comp_cards))
        seq += 1

    for j in range(n_order):
        c = order[j]
        if cnt[c] == 1:
            spec.append((0, <int>lvl[c], seq, [objmap[c]]))
            seq += 1
    spec.sort(key=_comp_key)
    comps = []
    cdef int p, t
    for p, t, _, comp_cards in spec:
        comps.append(Component(
            KIND_TRACTOR if p >= 2 else (KIND_PAIR if p == 1 else KIND_SINGLE),
            comp_cards, t, p))
    return Decomposition(comps)


cdef list _tractor_runs_core(list cards, const unsigned char *ids,
                             Py_ssize_t n, const unsigned char *lvl, int k):
    """Port of combos._find_tractor_runs_uncached (lowest start first)."""
    cdef int cnt[N_CODES]
    cdef int order[N_CODES]        # distinct ids, first-occurrence order
    cdef int first_at[MAX_LEVEL]   # by_level[lv][0]: first pair-code at level
    cdef int j, c, L, start, d, ok, n_order = 0
    cdef Py_ssize_t i
    cdef list objmap = [None] * N_CODES

    memset(cnt, 0, sizeof(cnt))
    for j in range(MAX_LEVEL):
        first_at[j] = -1
    for i in range(n):
        c = ids[i]
        if cnt[c] == 0:
            order[n_order] = c
            n_order += 1
            objmap[c] = cards[i]
        cnt[c] += 1
    # by_level[lv][0] == first code with count>=2 in Counter (first-
    # occurrence) order — NOT the first to reach count 2 in scan order.
    for j in range(n_order):
        c = order[j]
        if cnt[c] >= 2:
            L = lvl[c]
            if first_at[L] < 0:
                first_at[L] = c

    out = []
    if k <= 0 or k > MAX_LEVEL:
        return out
    for start in range(MAX_LEVEL - k + 1):
        if first_at[start] < 0:
            continue
        ok = 1
        for d in range(1, k):
            if first_at[start + d] < 0:
                ok = 0
                break
        if ok:
            run = []
            for d in range(k):
                obj = objmap[first_at[start + d]]
                run.append(obj)
                run.append(obj)
            out.append(run)
    return out


# ------------------------------------------------------- public entry points

def decompose(list cards, ordering):
    """combos.decompose drop-in: memo probe + kernel.

    Memo semantics match the pure version exactly (caller-order contract,
    CORRECTNESS.md 08-03): key is ``tuple(cards)`` in the caller's exact
    order, value computed on that order, stored in ``ordering._dcache`` —
    the same dict the pure implementation uses.
    """
    cdef tuple ctx = _get_ctx(ordering)
    cdef dict cache = <dict>ctx[0]
    key = tuple(cards)
    cdef PyObject *hit = PyDict_GetItem(cache, key)
    if hit != NULL:
        return <object>hit
    cdef dict code2id = <dict>ctx[4]
    cdef const unsigned char *lvl = \
        <const unsigned char *>PyBytes_AS_STRING(ctx[2])
    cdef unsigned char ids[MAX_CARDS]
    cdef Py_ssize_t n = _ids_of(cards, code2id, ids)
    result = _decompose_core(cards, ids, n, lvl)
    cache[key] = result
    return result


def find_tractor_runs(list cards, ordering, int k):
    """combos.find_tractor_runs drop-in: caller-order memo + defensive
    copies, stored in ``ordering._trcache`` keyed ``(tuple(cards), k)``."""
    cdef tuple ctx = _get_ctx(ordering)
    cdef dict cache = <dict>ctx[1]
    key = (tuple(cards), k)
    cdef PyObject *hitp = PyDict_GetItem(cache, key)
    cdef list hit
    cdef dict code2id
    cdef const unsigned char *lvl
    cdef unsigned char ids[MAX_CARDS]
    cdef Py_ssize_t n
    if hitp != NULL:
        hit = <list><object>hitp
    else:
        code2id = <dict>ctx[4]
        lvl = <const unsigned char *>PyBytes_AS_STRING(ctx[2])
        n = _ids_of(cards, code2id, ids)
        hit = _tractor_runs_core(cards, ids, n, lvl, k)
        cache[key] = hit
    # Same rule as combos: callers may mutate runs (throw penalties), so
    # never hand out the cached lists themselves.
    return [list(r) for r in hit]


def suit_cards(list hand, eff, ordering):
    """legal.suit_cards drop-in: keep cards whose effective suit matches.
    Filters the original str objects — no reverse conversion needed."""
    cdef tuple ctx = _get_ctx(ordering)
    cdef int target = <int>EFF_ID[eff]
    cdef dict code2id = <dict>ctx[4]
    cdef const unsigned char *efftab = \
        <const unsigned char *>PyBytes_AS_STRING(ctx[3])
    out = []
    for c in hand:
        if efftab[<int>code2id[c]] == target:
            out.append(c)
    return out


def decompose_uncached(list cards, ordering):
    """Uncached kernel (combos._decompose_uncached drop-in) — for parity
    tests and benchmarks; the memoized path above is what ships."""
    cdef tuple ctx = _get_ctx(ordering)
    cdef dict code2id = <dict>ctx[4]
    cdef const unsigned char *lvl = \
        <const unsigned char *>PyBytes_AS_STRING(ctx[2])
    cdef unsigned char ids[MAX_CARDS]
    cdef Py_ssize_t n = _ids_of(cards, code2id, ids)
    return _decompose_core(cards, ids, n, lvl)


def find_tractor_runs_uncached(list cards, ordering, int k):
    """Uncached kernel (combos._find_tractor_runs_uncached drop-in)."""
    cdef tuple ctx = _get_ctx(ordering)
    cdef dict code2id = <dict>ctx[4]
    cdef const unsigned char *lvl = \
        <const unsigned char *>PyBytes_AS_STRING(ctx[2])
    cdef unsigned char ids[MAX_CARDS]
    cdef Py_ssize_t n = _ids_of(cards, code2id, ids)
    return _tractor_runs_core(cards, ids, n, lvl, k)
