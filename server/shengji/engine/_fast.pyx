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
from shengji.engine.legal import IllegalPlay

cdef enum:
    # Levels are 0..15 (12 plain + rank-off/rank-trump/LJ/BJ); <=4 codes can
    # share a level (off-suit trump-rank cards, all rank cards in no-trump).
    MAX_LEVEL = 16
    MAX_PER_LEVEL = 6
    N_CODES = 54
    MAX_CARDS = 128   # plays/hands never exceed 33
    MAX_RUNS = 64     # bounded by MAX_CARDS/2 pair-runs in a shape
    MAX_PAIRS = 64

cdef object KIND_SINGLE = "single"
cdef object KIND_PAIR = "pair"
cdef object KIND_TRACTOR = "tractor"

EFF_ID = {"S": 0, "H": 1, "C": 2, "D": 3, "T": 4}
cdef tuple EFF_NAMES = ("S", "H", "C", "D", "T")
cdef dict _EFF_ID = EFF_ID

# Global code->id and points tables for the ordering-free helpers
# (pair_count, check_in_hand, points); fast.py registers them at import.
cdef dict _CODE2ID = None
cdef int _PTS[N_CODES]


def set_code2id(d):
    global _CODE2ID
    _CODE2ID = d


def set_points(bytes pts):
    cdef const unsigned char *p = <const unsigned char *>PyBytes_AS_STRING(pts)
    cdef Py_ssize_t i
    for i in range(N_CODES):
        _PTS[i] = p[i]

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
    # EVERY pair-capable code per level, sorted by card string. Taking only
    # the first meant C7-C7-D7-D7-H7-H7 offered C7C7+H7H7 and never
    # D7D7+H7H7 — distinct lead actions leaving different residual hands
    # (Codex, 2026-08-04). Mirrors combos._find_tractor_runs_uncached.
    cdef list lev_all = [[] for _ in range(MAX_LEVEL)]
    for j in range(n_order):
        c = order[j]
        if cnt[c] >= 2:
            L = lvl[c]
            if first_at[L] < 0:
                first_at[L] = c
            (<list>lev_all[L]).append(objmap[c])
    for j in range(MAX_LEVEL):
        (<list>lev_all[j]).sort()

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
            # Cartesian product over the window, same order as itertools.product
            windows = [lev_all[start + d] for d in range(k)]
            for combo in _product(windows):
                run = []
                for obj in combo:
                    run.append(obj)
                    run.append(obj)
                out.append(run)
    return out


cdef list _product(list pools):
    """itertools.product over a small list of lists, order-identical."""
    cdef list result = [[]]
    cdef list pool, nxt
    for pool in pools:
        nxt = []
        for prefix in result:
            for item in pool:
                nxt.append(prefix + [item])
        result = nxt
    return result


# ------------------------------------------------------- public entry points

cdef object _decompose_memo(list cards, object ordering, tuple ctx):
    """Shared memoized decompose. The input is CANONICALISED (sorted) first,
    so the key is the multiset and the value is a function of it — matching
    `combos._decompose_uncached`, which sorts at the same point.

    The old caller-order contract existed because the greedy split resolved
    tied-level pairs by input order: `C7 C7 D7 D7 H7 H7` built its tractor from
    C7 and `D7 C7 C7 D7 H7 H7` from D7 (Codex witness, 2026-08-04). Keying on
    caller order preserved that ambiguity faithfully instead of removing it.
    Sorting at entry makes the ambiguity go away, so the multiset key is now
    both correct and a better hit rate. Stored in ``ordering._dcache``, the
    same dict the pure implementation uses."""
    cdef dict cache = <dict>ctx[0]
    cards = sorted(cards)
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


def decompose(list cards, ordering):
    """combos.decompose drop-in: memo probe + kernel (see _decompose_memo)."""
    return _decompose_memo(cards, ordering, _get_ctx(ordering))


def find_tractor_runs(list cards, ordering, int k):
    """combos.find_tractor_runs drop-in: exact-order memo + defensive copies.

    The enumerated value is multiset-canonical; the cheaper exact-order key is
    retained deliberately for this 815k-call/round hot path."""
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
    tests and benchmarks; the memoized path above is what ships.

    Canonicalises its input exactly as the pure kernel does, so the two agree
    on which tied-level pair joins a tractor."""
    cards = sorted(cards)
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


# ---------------------------------------------- rules: matching / beats / follow

cdef bint _bt(const int *runs, int n_runs, const int *offs, int i,
              int *lev_n, int *lev_codes, int *chosen, int *tops) noexcept:
    """Port of decompose_matching's backtrack: for run i, try window starts
    over currently-available levels ASCENDING; pop the LAST code (list.pop())
    at each window level; first full assignment wins. Undo-based instead of
    dict copies — codes above lev_n are never overwritten, so incrementing
    lev_n restores exactly."""
    if i == n_runs:
        return True
    cdef int k = runs[i]
    cdef int start, d, lv, ok
    for start in range(MAX_LEVEL):
        if lev_n[start] == 0:
            continue
        if start + k > MAX_LEVEL:
            break               # no higher start can fit either
        ok = 1
        for d in range(1, k):
            if lev_n[start + d] == 0:
                ok = 0
                break
        if not ok:
            continue
        for d in range(k):
            lv = start + d
            lev_n[lv] -= 1
            chosen[offs[i] + d] = lev_codes[lv * MAX_PER_LEVEL + lev_n[lv]]
        tops[i] = start + k - 1
        if _bt(runs, n_runs, offs, i + 1, lev_n, lev_codes, chosen, tops):
            return True
        for d in range(k):
            lev_n[start + d] += 1
    return False


cdef int _match_solve(list cards, const unsigned char *lvl, dict code2id,
                      tuple runs_needed, Py_ssize_t n_singles,
                      int *cnt, int *order, int *n_order, list objmap,
                      int *runs, int *n_runs, int *chosen,
                      int *tops) except -1:
    """Setup + search for combos.decompose_matching. Returns 1 solved /
    0 impossible (-> None). Caller provides cnt[N_CODES], order[N_CODES],
    objmap (54-slot list), runs[MAX_RUNS], chosen[MAX_PAIRS], tops[MAX_RUNS].
    Shapes must come from Decomposition.shape() (every run length >= 1)."""
    cdef Py_ssize_t n = len(cards), i, sum_runs = 0
    cdef int nr = <int>len(runs_needed), j, c, k, L
    if nr > MAX_RUNS or n > MAX_CARDS:
        raise ValueError("play too large")
    for j in range(nr):
        k = <int>runs_needed[j]
        if k < 1:
            raise ValueError("shape run lengths must be >= 1")
        runs[j] = k
        sum_runs += k
    n_runs[0] = nr
    if n != 2 * sum_runs + n_singles:
        return 0
    memset(cnt, 0, N_CODES * sizeof(int))
    n_order[0] = 0
    for i in range(n):
        c = <int>code2id[cards[i]]
        if cnt[c] == 0:
            order[n_order[0]] = c
            n_order[0] += 1
            objmap[c] = cards[i]
        cnt[c] += 1
    # by_level in Counter (first-occurrence) order; one slot per CODE with
    # count >= 2 (bug-for-bug with pure: 3+ copies still yield one pair slot).
    cdef int lev_n[MAX_LEVEL]
    cdef int lev_codes[MAX_LEVEL * MAX_PER_LEVEL]
    memset(lev_n, 0, sizeof(lev_n))
    for j in range(n_order[0]):
        c = order[j]
        if cnt[c] >= 2:
            L = lvl[c]
            lev_codes[L * MAX_PER_LEVEL + lev_n[L]] = c
            lev_n[L] += 1
    cdef int offs[MAX_RUNS]
    cdef int pos = 0
    for j in range(nr):
        offs[j] = pos
        pos += runs[j]
    return 1 if _bt(runs, nr, offs, 0, lev_n, lev_codes, chosen, tops) else 0


def decompose_matching(list cards, ordering, shape):
    """combos.decompose_matching drop-in (uncached, like pure): match
    ``cards`` (one effective suit) against a target shape or return None."""
    cdef tuple ctx = _get_ctx(ordering)
    cdef dict code2id = <dict>ctx[4]
    cdef const unsigned char *lvl = \
        <const unsigned char *>PyBytes_AS_STRING(ctx[2])
    runs_needed, n_singles = shape
    cdef int cnt[N_CODES]
    cdef int order[N_CODES]
    cdef int runs[MAX_RUNS]
    cdef int chosen[MAX_PAIRS]
    cdef int tops[MAX_RUNS]
    cdef int used[N_CODES]
    cdef int n_order = 0, n_runs = 0
    cdef list objmap = [None] * N_CODES
    cdef int solved = _match_solve(cards, lvl, code2id, tuple(runs_needed),
                                   n_singles, cnt, order, &n_order, objmap,
                                   runs, &n_runs, chosen, tops)
    if not solved:
        return None
    # Rebuild pure's component order exactly: run comps in solve order,
    # then leftover singles in Counter ((cnt - used).elements()) order,
    # then the stable (-pair_len, -top) sort.
    memset(used, 0, sizeof(used))
    spec = []
    cdef int seq = 0, pos = 0, j, d, k, c, rem
    for j in range(n_runs):
        k = runs[j]
        comp_cards = []
        for d in range(k):
            c = chosen[pos]
            pos += 1
            used[c] += 2
            comp_cards.append(objmap[c])
            comp_cards.append(objmap[c])
        spec.append((k, tops[j], seq, comp_cards))
        seq += 1
    for j in range(n_order):
        c = order[j]
        for d in range(cnt[c] - used[c]):
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


def beats(list challenger, list lead, incumbent_suit, incumbent_top, ordering):
    """legal.beats drop-in. Runs the same matching search as
    decompose_matching but skips building the Decomposition: with the shape's
    runs sorted descending, pure's ``ch_dec.top_level()`` == max top among
    solved runs of maximal length (or max card level when the shape is all
    singles) — value-identical, object-free."""
    cdef tuple ctx = _get_ctx(ordering)
    cdef dict code2id = <dict>ctx[4]
    cdef const unsigned char *efftab = \
        <const unsigned char *>PyBytes_AS_STRING(ctx[3])
    cdef const unsigned char *lvl = \
        <const unsigned char *>PyBytes_AS_STRING(ctx[2])
    cdef Py_ssize_t n = len(challenger), i
    if n == 0:
        return (False, 0)
    cdef int e0 = efftab[<int>code2id[challenger[0]]]
    for i in range(1, n):
        if efftab[<int>code2id[challenger[i]]] != e0:
            return (False, 0)                    # mixed suits: no contest
    lead_dec = _decompose_memo(lead, ordering, ctx)
    # lead_dec.shape() inline: pair-run lengths sorted desc + singles count.
    cdef list runs_list = []
    cdef Py_ssize_t n_singles = 0
    cdef int pl
    for comp in lead_dec.components:
        pl = <int>comp.pair_len
        if pl:
            runs_list.append(pl)
        else:
            n_singles += 1
    runs_list.sort(reverse=True)
    cdef int cnt[N_CODES]
    cdef int order[N_CODES]
    cdef int runs[MAX_RUNS]
    cdef int chosen[MAX_PAIRS]
    cdef int tops[MAX_RUNS]
    cdef int n_order = 0, n_runs = 0
    cdef list objmap = [None] * N_CODES
    cdef int solved = _match_solve(challenger, lvl, code2id, tuple(runs_list),
                                   n_singles, cnt, order, &n_order, objmap,
                                   runs, &n_runs, chosen, tops)
    if not solved:
        return (False, 0)
    cdef int top = -1, j, kmax
    if n_runs > 0:
        kmax = runs[0]                           # runs sorted desc
        for j in range(n_runs):
            if runs[j] == kmax and tops[j] > top:
                top = tops[j]
    else:
        for j in range(n_order):
            if lvl[order[j]] > top:
                top = lvl[order[j]]
    cdef long it = incumbent_top
    hit = _EFF_ID.get(incumbent_suit)
    if hit is not None and e0 == <int>hit:
        return (top > it, top)
    if e0 == 4:                                  # TRUMP over non-trump
        return (True, top)
    return (False, 0)


def pair_count(list cards):
    """combos.pair_count drop-in: sum of k // 2 over card multiplicities."""
    cdef dict code2id = _CODE2ID
    cdef int cnt[N_CODES]
    cdef Py_ssize_t i, n = len(cards)
    cdef int c, total = 0
    if n > MAX_CARDS:
        raise ValueError("play too large")
    memset(cnt, 0, sizeof(cnt))
    for i in range(n):
        c = <int>code2id[cards[i]]
        cnt[c] += 1
        if cnt[c] % 2 == 0:
            total += 1
    return total


def uniform_suit(list play, ordering):
    """legal.uniform_suit drop-in: the single effective suit, else None."""
    cdef tuple ctx = _get_ctx(ordering)
    cdef dict code2id = <dict>ctx[4]
    cdef const unsigned char *efftab = \
        <const unsigned char *>PyBytes_AS_STRING(ctx[3])
    cdef Py_ssize_t n = len(play), i
    if n == 0:
        return None
    cdef int e0 = efftab[<int>code2id[play[0]]]
    for i in range(1, n):
        if efftab[<int>code2id[play[i]]] != e0:
            return None
    return EFF_NAMES[e0]


cdef int _check_in_hand_c(list hand, list play, int *cntp,
                          int *cnth) except -1:
    """Fills play/hand count arrays; raises IllegalPlay unless ``play`` is a
    nonempty sub-multiset of ``hand`` (legal.check_in_hand semantics)."""
    cdef Py_ssize_t np_ = len(play), nh = len(hand), i
    cdef int c
    if np_ == 0:
        raise IllegalPlay("You don't hold those cards.")
    if np_ > MAX_CARDS or nh > MAX_CARDS:
        raise ValueError("play too large")
    memset(cntp, 0, N_CODES * sizeof(int))
    memset(cnth, 0, N_CODES * sizeof(int))
    for i in range(np_):
        cntp[<int>_CODE2ID[play[i]]] += 1
    for i in range(nh):
        cnth[<int>_CODE2ID[hand[i]]] += 1
    for c in range(N_CODES):
        if cntp[c] > cnth[c]:
            raise IllegalPlay("You don't hold those cards.")
    return 0


def check_in_hand(list hand, list play):
    """legal.check_in_hand drop-in."""
    cdef int cntp[N_CODES]
    cdef int cnth[N_CODES]
    _check_in_hand_c(hand, play, cntp, cnth)


# ------------------------------------------- phase 2 (partial): policy leaves

cdef inline long _pts_of(object code) except -1:
    """cards.points drop-in core (table hit; pure-logic fallback for any
    code outside the 54-entry table, matching pure's tolerant behavior)."""
    hit = _CODE2ID.get(code)
    if hit is not None:
        return _PTS[<int>hit]
    if code == "LJ" or code == "BJ":
        return 0
    r = code[1:]
    if r == "5":
        return 5
    if r == "10" or r == "K":
        return 10
    return 0


def points(code):
    """cards.points drop-in."""
    return _pts_of(code)


def total_points(codes):
    """cards.total_points drop-in (accepts any iterable, like sum+genexpr)."""
    cdef long tot = 0
    if type(codes) is list:
        for c in <list>codes:
            tot += _pts_of(c)
    else:
        for c in codes:
            tot += _pts_of(c)
    return tot


cdef inline long _low_key(int in_avoid, int trumpish, long pts, int vlen,
                          int lvl, bint avoid_points,
                          bint seek_points) noexcept:
    """HeuristicBot._lowest key tuples packed into one comparable long
    (fields bounded: pts<=10, vlen<=33 fits 8 bits, lvl<=15)."""
    if seek_points:            # (in_avoid, -pts, trumpish, lvl)
        return ((<long>in_avoid << 40) | ((10 - pts) << 32)
                | (<long>trumpish << 24) | lvl)
    if avoid_points:           # (in_avoid, trumpish, pts>0, vlen, lvl)
        return ((<long>in_avoid << 40) | (<long>trumpish << 32)
                | (<long>(1 if pts > 0 else 0) << 24)
                | (<long>vlen << 8) | lvl)
    return ((<long>in_avoid << 40) | (<long>trumpish << 32)  # no-flags key
            | (<long>vlen << 8) | lvl)


cdef Py_ssize_t _lowest_idx(list objs, const unsigned char *ids,
                            const unsigned char *alive, Py_ssize_t n,
                            const unsigned char *efftab,
                            const unsigned char *lvltab, bint void_dump,
                            bint avoid_points, bint seek_points,
                            object avoid) except -1:
    """Index of min(cards, key=HeuristicBot._lowest.key) over alive entries
    (first minimum wins, like min())."""
    cdef int suit_n[5]
    cdef Py_ssize_t i, best_i = -1
    cdef long k, best = 0
    cdef int e, trumpish, vlen, in_avoid
    cdef bint has_avoid = avoid is not None and len(avoid) > 0
    if void_dump:
        memset(suit_n, 0, sizeof(suit_n))
        for i in range(n):
            if alive[i]:
                suit_n[efftab[ids[i]]] += 1
    for i in range(n):
        if not alive[i]:
            continue
        e = efftab[ids[i]]
        trumpish = 1 if e == 4 else 0
        vlen = suit_n[e] if (void_dump and not trumpish) else 0
        in_avoid = 1 if (has_avoid and (objs[i] in avoid)) else 0
        k = _low_key(in_avoid, trumpish, _PTS[ids[i]], vlen,
                     <int>lvltab[ids[i]], avoid_points, seek_points)
        if best_i < 0 or k < best:
            best = k
            best_i = i
    if best_i < 0:
        raise ValueError("min() arg is an empty sequence")
    return best_i


def heuristic_lowest(list cards, ordering, bint void_dump, bint avoid_points,
                     bint seek_points, avoid=None):
    """HeuristicBot._lowest drop-in (void_dump == self.VOID_DUMP)."""
    cdef tuple ctx = _get_ctx(ordering)
    cdef dict code2id = <dict>ctx[4]
    cdef const unsigned char *efftab = \
        <const unsigned char *>PyBytes_AS_STRING(ctx[3])
    cdef const unsigned char *lvltab = \
        <const unsigned char *>PyBytes_AS_STRING(ctx[2])
    cdef unsigned char ids[MAX_CARDS]
    cdef unsigned char alive[MAX_CARDS]
    cdef Py_ssize_t n = _ids_of(cards, code2id, ids), i
    for i in range(n):
        alive[i] = 1
    return cards[_lowest_idx(cards, ids, alive, n, efftab, lvltab,
                             void_dump, avoid_points, seek_points, avoid)]


def forced_follow(list hand, list lead, ordering, bint void_dump,
                  bint prefer_points, avoid=None):
    """HeuristicBot._forced_follow drop-in: construct a legal minimal
    follow. Same decision order as pure — tractor obligation from the
    memoized find_tractor_runs (runs[0]), pair obligation over remaining
    pool pairs stable-sorted by (in avoid, level), then lowest-card fill
    with per-iteration recomputed void-dump suit lengths."""
    cdef tuple ctx = _get_ctx(ordering)
    cdef dict code2id = <dict>ctx[4]
    cdef const unsigned char *efftab = \
        <const unsigned char *>PyBytes_AS_STRING(ctx[3])
    cdef const unsigned char *lvltab = \
        <const unsigned char *>PyBytes_AS_STRING(ctx[2])
    cdef Py_ssize_t n = len(lead), nh = len(hand), i, j, bi
    cdef unsigned char lids[MAX_CARDS]
    cdef unsigned char hids[MAX_CARDS]
    _ids_of(lead, code2id, lids)
    _ids_of(hand, code2id, hids)
    cdef int e0 = efftab[lids[0]]
    for i in range(1, n):
        if efftab[lids[i]] != e0:
            raise AssertionError       # pure: assert uniform_suit(lead)
    # Split hand into led-suit / off-suit, preserving hand order.
    cdef list sobj = []
    cdef list oobj = []
    cdef unsigned char sid[MAX_CARDS]
    cdef unsigned char oid_[MAX_CARDS]
    cdef unsigned char alive[MAX_CARDS]
    cdef Py_ssize_t ns = 0, no = 0
    for i in range(nh):
        if efftab[hids[i]] == e0:
            sid[ns] = hids[i]
            sobj.append(hand[i])
            ns += 1
        else:
            oid_[no] = hids[i]
            oobj.append(hand[i])
            no += 1
    cdef list picked = []
    cdef list fobj
    cdef unsigned char *fid
    cdef Py_ssize_t nf
    cdef int cnt[N_CODES]
    cdef int pc[N_CODES]
    cdef int pcode[N_CODES]
    cdef long pkey[N_CODES]
    cdef int npc = 0, need, k, c, cid, taken, in_av
    cdef long kk
    cdef bint has_avoid = avoid is not None and len(avoid) > 0
    if ns >= n:
        for i in range(ns):
            alive[i] = 1
        lead_dec = _decompose_memo(lead, ordering, ctx)
        comps = lead_dec.components
        # tractor obligation
        if len(comps) == 1 and comps[0].kind == KIND_TRACTOR:
            k = <int>comps[0].pair_len
            runs = find_tractor_runs(sobj, ordering, k)
            if runs:
                run = <list>(runs[0])
                for c_obj in run:
                    picked.append(c_obj)
                    cid = <int>code2id[c_obj]
                    for j in range(ns):        # pool.remove(c): first alive
                        if alive[j] and sid[j] == cid:
                            alive[j] = 0
                            break
        # pair obligation: need = min(lead pairs, pair_count(h_suit)) - taken
        memset(cnt, 0, sizeof(cnt))
        need = 0
        for i in range(ns):
            cnt[sid[i]] += 1
        for c in range(N_CODES):
            need += cnt[c] // 2                # pair_count(h_suit)
        if <int>lead_dec.n_pairs < need:
            need = <int>lead_dec.n_pairs
        need -= <int>len(picked) // 2          # pair_count(picked): all pairs
        if need > 0:
            # distinct pool codes with count >= 2, Counter (first-alive-
            # occurrence) order, stable insertion sort by (in avoid, level)
            memset(pc, 0, sizeof(pc))
            for i in range(ns):
                if alive[i]:
                    pc[sid[i]] += 1
            npc = 0
            for i in range(ns):
                if alive[i] and pc[sid[i]] >= 2:
                    pc[sid[i]] = -pc[sid[i]]   # mark emitted
                    in_av = 1 if (has_avoid and (sobj[i] in avoid)) else 0
                    kk = (<long>in_av << 8) | <int>lvltab[sid[i]]
                    j = npc
                    while j > 0 and pkey[j - 1] > kk:
                        pkey[j] = pkey[j - 1]
                        pcode[j] = pcode[j - 1]
                        j -= 1
                    pkey[j] = kk
                    pcode[j] = sid[i]
                    npc += 1
            if need > npc:
                need = npc
            for j in range(need):
                cid = pcode[j]
                taken = 0
                for i in range(ns):            # remove + collect both copies
                    if alive[i] and sid[i] == cid:
                        alive[i] = 0
                        if taken == 0:
                            picked.append(sobj[i])
                            picked.append(sobj[i])
                        taken += 1
                        if taken == 2:
                            break
        fobj = sobj
        fid = sid
        nf = ns
    else:
        picked = list(sobj)
        fobj = oobj
        fid = oid_
        nf = no
        for i in range(nf):
            alive[i] = 1
    while <Py_ssize_t>len(picked) < n:
        bi = _lowest_idx(fobj, fid, alive, nf, efftab, lvltab, void_dump,
                         not prefer_points, prefer_points, avoid)
        picked.append(fobj[bi])
        alive[bi] = 0
    return picked[:n]


def validate_follow(list play, list hand, list lead, ordering):
    """legal.validate_follow drop-in — identical rule order, identical
    IllegalPlay messages, same memoized decompose calls on lead/play."""
    cdef tuple ctx = _get_ctx(ordering)
    cdef dict code2id = <dict>ctx[4]
    cdef const unsigned char *efftab = \
        <const unsigned char *>PyBytes_AS_STRING(ctx[3])
    cdef const unsigned char *lvl = \
        <const unsigned char *>PyBytes_AS_STRING(ctx[2])
    cdef int cntp[N_CODES]
    cdef int cnth[N_CODES]
    _check_in_hand_c(hand, play, cntp, cnth)
    cdef Py_ssize_t np_ = len(play), nl = len(lead), i
    if np_ != nl:
        raise IllegalPlay(f"Must play exactly {nl} card(s).")
    cdef int e0 = efftab[<int>code2id[lead[0]]]
    for i in range(1, nl):
        if efftab[<int>code2id[lead[i]]] != e0:
            raise AssertionError            # pure: assert uniform_suit(lead)
    # Led-suit portions of hand and play, from the count arrays.
    cdef int h_suit_n = 0, p_suit_n = 0, c
    cdef int cnths[N_CODES]
    memset(cnths, 0, sizeof(cnths))
    for c in range(N_CODES):
        if efftab[c] == e0:
            cnths[c] = cnth[c]
            h_suit_n += cnth[c]
            p_suit_n += cntp[c]
    cdef int need_pairs, have_pairs, play_pairs, k, start, d, ok
    cdef int pair_at[MAX_LEVEL]
    if h_suit_n >= nl:
        if p_suit_n != np_:
            raise IllegalPlay("You must follow suit.")
        lead_dec = _decompose_memo(lead, ordering, ctx)
        have_pairs = 0
        for c in range(N_CODES):
            have_pairs += cnths[c] // 2
        need_pairs = <int>lead_dec.n_pairs
        if have_pairs < need_pairs:
            need_pairs = have_pairs
        play_pairs = 0
        for c in range(N_CODES):
            play_pairs += cntp[c] // 2
        if play_pairs < need_pairs:
            raise IllegalPlay("You must play pairs from the led suit.")
        # Tractor obligation for a pure tractor lead.
        comps = lead_dec.components
        if len(comps) == 1 and comps[0].kind == KIND_TRACTOR:
            k = <int>comps[0].pair_len
            # has_tractor(h_suit, k): any k consecutive levels each holding
            # a pair among the hand's led-suit cards.
            memset(pair_at, 0, sizeof(pair_at))
            for c in range(N_CODES):
                if cnths[c] >= 2:
                    pair_at[lvl[c]] = 1
            for start in range(MAX_LEVEL - k + 1):
                ok = 1
                for d in range(k):
                    if not pair_at[start + d]:
                        ok = 0
                        break
                if ok:
                    if _decompose_memo(play, ordering,
                                       ctx).max_pair_run() < k:
                        raise IllegalPlay(
                            f"You must follow with a tractor of {k} pairs.")
                    break
    else:
        # Void-ish: every led-suit card in hand must appear in the play.
        for c in range(N_CODES):
            if cnths[c] > cntp[c]:
                raise IllegalPlay("You must play all your cards of the led suit.")
