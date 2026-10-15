# cython: language_level=3, boundscheck=False, wraparound=False, cdivision=True, initializedcheck=False
"""Compiled exact-endgame solver: the reference search on per-world bitmasks.

Same search as ``endgame._ExactSolver`` (child order, alpha-beta windows,
exact/bound transposition tables, node cap), so values, node counts and
cache-hit counts are identical.  ``endgame_compact`` owns backend selection
and the pure-Python fallback; policy code never imports this module.

State
-----
Each seat's cards live in at most ``MAXSLOT`` *slots* (one per physical card
the session has seen in that seat).  Copies of one code in one seat are kept
canonical: a hand holding ``r`` copies holds that code's first ``r`` slots,
and playing a copy removes the highest one.  A hand (or a play) is then a
``uint8`` mask, and mask equality is multiset equality -- exactly the
reference ``_state_key``'s sorted-tuple equality.  The transposition key is
``(hands, turn, leader, #plays | attacker points, plays)`` in two ``uint64``.

Rules
-----
Every fact that depends on the trump context -- effective suit and level per
code, decomposition into components, shape, ``top_level``,
``max_pair_run``, tractor runs, ``decompose_matching`` -- is computed by the
engine's own functions, once per card multiset per ``Ordering`` (so shared by
every world of a decision), and stored as plain integers.  The control flow
of ``legal.validate_follow``, ``legal.validate_lead`` (the throw penalty) and
``Round._resolve_trick`` / ``legal.beats`` is replayed over those integers.
``tests/test_endgame_compact.py`` checks the whole solver against the
reference on real and generated positions under both engines.
"""

from libc.stdint cimport int32_t, uint8_t, uint32_t, uint64_t
from libc.stdlib cimport calloc, free, malloc
from libc.string cimport memset

import threading
import weakref

from shengji.engine import combos as _combos
from shengji.engine.cards import TRUMP, Ordering, make_deck, points as _card_points
from shengji.engine.round import KITTY_MULTIPLIER

cdef enum:
    MAXSLOT = 8
    NMASK = 256
    NCODE = 54
    MAXK = 5            # tractor pair lengths tracked: 2..MAXK-1
    MAXCOMP = 8
    MAXSHAPE = 16
    NONE_EFF = -1
    TRUMP_EFF = 4
    MAXMOVES = 256

cdef enum:
    NEG = -1000000000
    POS = 1000000000
    RAISED = -2147483647   # exception sentinel for cdef int returns

#: largest hand (cards per seat) the slot masks can hold
MAX_HAND = MAXSLOT

#: global code ids: sorted codes, so id order is string order (as fast.ID2CODE)
ID2CODE = sorted(set(make_deck()))
CODE2ID = {c: i for i, c in enumerate(ID2CODE)}
_EFF_ID = {"S": 0, "H": 1, "C": 2, "D": 3, TRUMP: TRUMP_EFF}


class SlotCapacityExceeded(Exception):
    """A seat needs more than ``MAX_HAND`` distinct physical card slots."""


cdef struct MS:
    # facts about one card multiset
    int eff              # uniform effective suit id, or NONE_EFF
    int size
    int pts
    int pair_count
    int max_level        # highest level (uniform sets), NEG if empty
    int max_pair_level   # highest level of a code held twice, NEG if none
    # decomposition (uniform, non-empty sets)
    int n_comp
    int n_pairs
    int top_level
    int max_pair_run
    int single_tractor_k  # pair_len of a lone tractor component, else 0
    int shape_id
    int trac_top[MAXK]   # highest find_tractor_runs top for k pairs, NEG if none
    int comp_pair_len[MAXCOMP]
    int comp_top[MAXCOMP]
    int comp_ncards[MAXCOMP]
    uint8_t comp_codes[MAXCOMP][MAXSLOT]
    int32_t match[MAXSHAPE]   # decompose_matching top + 2; 1 = None; 0 = unknown
    uint64_t lo               # the multiset's 2-bit code counts
    uint64_t hi


cdef struct MSKey:
    uint64_t lo
    uint64_t hi
    int32_t idx          # -1 = empty slot


cdef inline uint64_t _mix(uint64_t a, uint64_t b) noexcept nogil:
    cdef uint64_t h = a * <uint64_t>0x9E3779B97F4A7C15ULL
    h ^= b + <uint64_t>0x632BE59BD9B4E019ULL + (h << 6) + (h >> 2)
    h ^= h >> 31
    h *= <uint64_t>0xBF58476D1CE4E5B9ULL
    h ^= h >> 29
    return h


cdef class Tables:
    """Rule facts for one trump context, shared by every world on it.

    Rule calls use a PRIVATE ``Ordering`` built from the round's trump suit and
    rank (an ``Ordering`` is a pure function of those two).  The table must
    never reference the round's own ``Ordering``: ``_TABLES`` holds tables
    weakly keyed by it, and a value that owned its key would keep both alive
    for the life of the process.
    """
    cdef object ordering         # private: Ordering(trump_suit, trump_rank)
    cdef object binding
    cdef int level[NCODE]
    cdef int eff[NCODE]
    cdef int pts[NCODE]
    cdef MS** chunks             # stable addresses: records never move
    cdef int n_ms, n_chunks, cap_chunks
    cdef MSKey* keys             # open-addressing (lo, hi) -> record index
    cdef uint64_t key_cap
    cdef dict shapes             # shape tuple -> id
    cdef list shape_list         # id -> shape tuple
    cdef dict match_overflow     # (record, shape id >= MAXSHAPE) -> top
    cdef object lock             # serialises inserts (see ``_insert``)
    cdef object __weakref__      # lets tests watch a table being freed

    def __cinit__(self, ordering):
        cdef int i
        self.chunks = NULL
        self.keys = NULL
        self.binding = (ordering.trump_suit, ordering.trump_rank)
        self.ordering = Ordering(ordering.trump_suit, ordering.trump_rank)
        for i in range(NCODE):
            code = ID2CODE[i]
            self.level[i] = self.ordering.level(code)
            self.eff[i] = _EFF_ID[self.ordering.eff_suit(code)]
            self.pts[i] = _card_points(code)
        self.n_ms = 0
        self.n_chunks = 0
        self.cap_chunks = 64
        self.chunks = <MS**>calloc(self.cap_chunks, sizeof(MS*))
        self.key_cap = 1024
        self.keys = <MSKey*>malloc(self.key_cap * sizeof(MSKey))
        if self.chunks == NULL or self.keys == NULL:
            raise MemoryError()
        for i in range(<int>self.key_cap):
            self.keys[i].idx = -1
        self.shapes = {}
        self.shape_list = []
        self.match_overflow = {}
        self.lock = threading.Lock()

    def __dealloc__(self):
        cdef int i
        if self.chunks != NULL:
            for i in range(self.n_chunks):
                free(self.chunks[i])
            free(self.chunks)
        free(self.keys)

    cdef inline MS* at(self, int i) noexcept:
        return &self.chunks[i >> 8][i & 255]

    @property
    def records(self):
        """Card multisets with computed rule facts (tests: sharing)."""
        return self.n_ms

    cdef int shape_id(self, shape) except -1:
        got = self.shapes.get(shape)
        if got is None:
            got = len(self.shape_list)
            self.shapes[shape] = got
            self.shape_list.append(shape)
        return got

    cdef inline int _probe(self, uint64_t lo, uint64_t hi, uint64_t* slot) noexcept:
        cdef uint64_t mask = self.key_cap - 1
        cdef uint64_t i = _mix(lo, hi) & mask
        while True:
            if self.keys[i].idx < 0:
                slot[0] = i
                return -1
            if self.keys[i].lo == lo and self.keys[i].hi == hi:
                return self.keys[i].idx
            i = (i + 1) & mask

    cdef inline int find(self, uint64_t lo, uint64_t hi) except -2:
        """Record index of the multiset with 2-bit code counts (lo, hi)."""
        cdef uint64_t slot
        cdef int idx = self._probe(lo, hi, &slot)
        if idx >= 0:
            return idx
        return self._insert(lo, hi)

    cdef int _insert(self, uint64_t lo, uint64_t hi) except -2:
        """Build and file one record.  Lock-free readers are safe: the key
        table only changes here, in C, with the GIL held; ``_build`` runs
        engine Python code, so a second thread could get here meanwhile --
        the lock serialises inserts and the probe is redone under it."""
        with self.lock:
            return self._insert_locked(lo, hi)

    cdef int _insert_locked(self, uint64_t lo, uint64_t hi) except -2:
        cdef int c, k, idx
        cdef uint64_t at
        idx = self._probe(lo, hi, &at)
        if idx >= 0:
            return idx
        ids = []
        for c in range(NCODE):
            if c < 32:
                k = (lo >> (2 * c)) & 3
            else:
                k = (hi >> (2 * (c - 32))) & 3
            for _ in range(k):
                ids.append(c)
        idx = self._build(ids)
        self.at(idx).lo = lo
        self.at(idx).hi = hi
        self._probe(lo, hi, &at)   # unchanged under the lock; kept explicit
        self.keys[at].lo = lo
        self.keys[at].hi = hi
        self.keys[at].idx = idx
        if <uint64_t>(self.n_ms * 2) > self.key_cap:
            self._grow_keys()
        return idx

    cdef int _grow_keys(self) except -1:
        cdef MSKey* old = self.keys
        cdef uint64_t old_cap = self.key_cap, i, j, mask
        cdef MSKey* fresh = <MSKey*>malloc(2 * old_cap * sizeof(MSKey))
        if fresh == NULL:
            raise MemoryError()
        for i in range(2 * old_cap):
            fresh[i].idx = -1
        mask = 2 * old_cap - 1
        for i in range(old_cap):
            if old[i].idx >= 0:
                j = _mix(old[i].lo, old[i].hi) & mask
                while fresh[j].idx >= 0:
                    j = (j + 1) & mask
                fresh[j] = old[i]
        self.keys = fresh
        self.key_cap = 2 * old_cap
        free(old)
        return 0

    cdef int _build(self, list ids) except -1:
        """Compute one record with the engine's functions (``ids`` sorted)."""
        cdef MS* m
        cdef int i, j, c, n, k, lv
        cdef MS** grown
        if (self.n_ms >> 8) == self.n_chunks:
            if self.n_chunks == self.cap_chunks:
                grown = <MS**>calloc(2 * self.cap_chunks, sizeof(MS*))
                if grown == NULL:
                    raise MemoryError()
                for i in range(self.n_chunks):
                    grown[i] = self.chunks[i]
                free(self.chunks)
                self.chunks = grown
                self.cap_chunks *= 2
            self.chunks[self.n_chunks] = <MS*>malloc(256 * sizeof(MS))
            if self.chunks[self.n_chunks] == NULL:
                raise MemoryError()
            self.n_chunks += 1
        m = self.at(self.n_ms)
        memset(m, 0, sizeof(MS))
        n = len(ids)
        m.size = n
        m.max_level = NEG
        m.max_pair_level = NEG
        for k in range(MAXK):
            m.trac_top[k] = NEG
        counts = {}
        for c in ids:
            m.pts += self.pts[c]
            counts[c] = counts.get(c, 0) + 1
        for c, k in counts.items():
            m.pair_count += k // 2
        if n == 0:
            m.eff = NONE_EFF
        else:
            m.eff = self.eff[<int>ids[0]]
            for c in ids:
                if self.eff[c] != m.eff:
                    m.eff = NONE_EFF
                    break
        if m.eff != NONE_EFF:
            for c, k in counts.items():
                lv = self.level[c]
                if lv > m.max_level:
                    m.max_level = lv
                if k >= 2 and lv > m.max_pair_level:
                    m.max_pair_level = lv
            ordering = self.ordering
            cards = [ID2CODE[c] for c in ids]
            dec = _combos.decompose(cards, ordering)
            comps = dec.components
            if len(comps) > MAXCOMP:
                raise ValueError("compact exact solver: too many components")
            m.n_comp = len(comps)
            m.n_pairs = dec.n_pairs
            m.top_level = dec.top_level()
            m.max_pair_run = dec.max_pair_run()
            m.single_tractor_k = (comps[0].pair_len
                                  if len(comps) == 1 and comps[0].kind == "tractor"
                                  else 0)
            m.shape_id = self.shape_id(dec.shape())
            for i in range(m.n_comp):
                comp = comps[i]
                m.comp_pair_len[i] = comp.pair_len
                m.comp_top[i] = comp.top
                if len(comp.cards) > MAXSLOT:
                    raise ValueError("compact exact solver: component too large")
                m.comp_ncards[i] = len(comp.cards)
                for j in range(len(comp.cards)):
                    m.comp_codes[i][j] = CODE2ID[comp.cards[j]]
            for k in range(2, MAXK):
                if 2 * k > n:
                    break
                for r in _combos.find_tractor_runs(cards, ordering, k):
                    lv = ordering.level(r[len(r) - 1])
                    if lv > m.trac_top[k]:
                        m.trac_top[k] = lv
        self.n_ms += 1
        return self.n_ms - 1

    cdef int match_top(self, int idx, int shape_id) except RAISED:
        """``decompose_matching(P, shape).top_level()`` for record ``idx``;
        NEG for None."""
        cdef MS* m = self.at(idx)
        cdef int top
        if shape_id < MAXSHAPE and m.match[shape_id] != 0:
            return NEG if m.match[shape_id] == 1 else m.match[shape_id] - 2
        key = (idx, shape_id)
        if shape_id >= MAXSHAPE and key in self.match_overflow:
            return self.match_overflow[key]
        cards = self._codes(m.lo, m.hi)
        dm = _combos.decompose_matching(cards, self.ordering, self.shape_list[shape_id])
        top = NEG if dm is None else dm.top_level()
        m = self.at(idx)
        if shape_id < MAXSHAPE:
            m.match[shape_id] = 1 if top == NEG else top + 2
        else:
            self.match_overflow[key] = top
        return top

    cdef list _codes(self, uint64_t lo, uint64_t hi):
        cdef int c, k
        out = []
        for c in range(NCODE):
            k = <int>((lo >> (2 * c)) & 3) if c < 32 else <int>((hi >> (2 * (c - 32))) & 3)
            for _ in range(k):
                out.append(ID2CODE[c])
        return out


#: round ``Ordering`` -> its Tables, for exactly as long as that Ordering lives
#: (every world of one decision shares the root's Ordering object)
_TABLES = weakref.WeakKeyDictionary()


cdef Tables tables_for(ordering):
    if type(ordering) is not Ordering:
        raise TypeError("compact exact solver needs an engine Ordering")
    got = _TABLES.get(ordering)
    if got is None or (<Tables>got).binding != (ordering.trump_suit, ordering.trump_rank):
        got = Tables(ordering)
        _TABLES[ordering] = got
    return <Tables>got


cdef struct Entry:
    uint64_t k1
    uint64_t k2
    int32_t exact
    int32_t lower
    int32_t upper
    uint8_t flags        # 1 exact stored, 2 bounds stored, 4 slot used
    uint8_t best         # level mode: the played mask that last raised the answer


cdef class FastWorld:
    """One world's exact solver (``endgame_compact.CompactWorldSession``)."""
    cdef Tables T
    cdef public long nodes
    cdef public long cache_hits
    cdef long max_nodes
    cdef bint alpha_beta
    cdef readonly bint level          # level mode (``solve_level``); see below
    cdef public long probes           # level mode: null-window tests run
    cdef int32_t hist[4][NMASK]       # level mode: history scores per (seat, play)
    cdef object check_budget
    cdef long budget_every
    cdef long calls
    cdef int banker_parity
    cdef int kitty_points
    cdef object exc_type          # endgame.ExactEndgameRefusal
    cdef object budget_exc        # endgame.ExactEndgameBudgetExceeded
    # slots
    cdef int n_slots[4]
    cdef int slot_code[4][MAXSLOT]
    cdef uint8_t suitmask[4][5]
    # per-world caches
    cdef int32_t feat[4][NMASK]           # (seat, mask) -> record, -1 unknown
    cdef uint8_t* subs[4][NMASK]          # sorted canonical sub-multisets
    cdef int n_subs[4][NMASK]
    # transposition table
    cdef Entry* tt
    cdef uint64_t tt_cap
    cdef uint64_t tt_used

    def __cinit__(self):
        self.tt = NULL
        memset(self.subs, 0, sizeof(self.subs))

    def __init__(self, ordering, banker, buried, *, max_nodes,
                 check_budget=None, alpha_beta=False, budget_every=256,
                 exc_type, budget_exc_type, level=False):
        cdef int s, m
        self.T = tables_for(ordering)
        self.level = bool(level)
        memset(self.hist, 0, sizeof(self.hist))
        self.nodes = 0
        self.cache_hits = 0
        self.max_nodes = max_nodes
        self.alpha_beta = alpha_beta
        self.check_budget = check_budget
        self.budget_every = budget_every
        self.calls = 0
        self.banker_parity = banker % 2
        self.kitty_points = 0
        for c in buried:
            self.kitty_points += self.T.pts[<int>CODE2ID[c]]
        self.exc_type = exc_type
        self.budget_exc = budget_exc_type
        memset(self.n_slots, 0, sizeof(self.n_slots))
        memset(self.suitmask, 0, sizeof(self.suitmask))
        memset(self.feat, 0xff, sizeof(self.feat))      # -1
        memset(self.n_subs, 0xff, sizeof(self.n_subs))  # -1
        self.tt_cap = 256
        self.tt_used = 0
        self.tt = <Entry*>calloc(self.tt_cap, sizeof(Entry))
        if self.tt == NULL:
            raise MemoryError()

    def __dealloc__(self):
        cdef int s, m
        free(self.tt)
        for s in range(4):
            for m in range(NMASK):
                if self.subs[s][m] != NULL:
                    free(self.subs[s][m])

# Slot representation.

    cdef int _slot_mask(self, int seat, int code, int first, int count) except -1:
        """Mask of slots [first, first+count) of ``code`` in ``seat``; grows."""
        cdef int i, seen = 0, mask = 0, need = first + count
        for i in range(self.n_slots[seat]):
            if self.slot_code[seat][i] == code:
                if first <= seen < need:
                    mask |= 1 << i
                seen += 1
        while seen < need:
            # 2-bit code counts in a record key: at most 3 copies per seat
            if self.n_slots[seat] >= MAXSLOT or seen >= 3:
                raise SlotCapacityExceeded(
                    "compact exact session: seat slot capacity exceeded")
            i = self.n_slots[seat]
            self.slot_code[seat][i] = code
            self.suitmask[seat][self.T.eff[code]] |= 1 << i
            self.n_slots[seat] += 1
            if first <= seen < need:
                mask |= 1 << i
            seen += 1
        return mask

    cdef int _import(self, object rnd, uint8_t* hands, uint8_t* plays,
                     int* turn, int* points, int* leader) except -1:
        """Read a root ``Round`` into masks (canonical slots, growing them)."""
        cdef int s, c, i, n, m
        cdef int held[4][NCODE]
        cdef int played[4][NCODE]
        cdef int seats[3]
        memset(held, 0, sizeof(held))
        memset(played, 0, sizeof(played))
        trick = rnd.trick
        n = len(trick.plays)
        if n > 3:
            raise ValueError("a complete trick cannot be a root")
        for i in range(n):
            tp = trick.plays[i]
            s = tp.seat
            if s != (trick.leader + i) % 4:
                raise ValueError("trick plays out of seat order")
            seats[i] = s
            for code in tp.cards:
                played[s][<int>CODE2ID[code]] += 1
        rh = rnd.hands
        for s in range(4):
            for code in rh[s]:
                held[s][<int>CODE2ID[code]] += 1
        for s in range(4):
            hands[s] = 0
            plays[s] = 0
        for s in range(4):
            m = 0
            for c in range(NCODE):
                if held[s][c] or played[s][c]:
                    hands[s] |= self._slot_mask(s, c, 0, held[s][c])
                    if played[s][c]:
                        m |= self._slot_mask(s, c, held[s][c], played[s][c])
            for i in range(n):
                if seats[i] == s:
                    plays[i] = m
        turn[0] = rnd.turn
        points[0] = int(rnd.attacker_points)
        leader[0] = trick.leader
        return n

    cdef tuple _codes_of(self, int seat, int mask):
        cdef int i, j, t, n = 0
        cdef int ids[MAXSLOT]
        for i in range(self.n_slots[seat]):
            if mask >> i & 1:
                ids[n] = self.slot_code[seat][i]
                n += 1
        for i in range(1, n):
            t = ids[i]
            j = i - 1
            while j >= 0 and ids[j] > t:
                ids[j + 1] = ids[j]
                j -= 1
            ids[j + 1] = t
        return tuple([ID2CODE[ids[i]] for i in range(n)])

    cdef inline int _msi(self, int seat, int mask) except -2:
        cdef int32_t i = self.feat[seat][mask]
        cdef int k, c
        cdef uint64_t lo = 0, hi = 0
        if i < 0:
            for k in range(self.n_slots[seat]):
                if mask >> k & 1:
                    c = self.slot_code[seat][k]
                    if c < 32:
                        lo += (<uint64_t>1) << (2 * c)
                    else:
                        hi += (<uint64_t>1) << (2 * (c - 32))
            i = self.T.find(lo, hi)
            self.feat[seat][mask] = i
        return i

    cdef inline MS* _ms(self, int seat, int mask) except NULL:
        return self.T.at(self._msi(seat, mask))

    cdef int _top_slot(self, int seat, int hand, int code) except -1:
        """Slot of the highest present copy of ``code`` in ``hand``."""
        cdef int i
        for i in range(self.n_slots[seat] - 1, -1, -1):
            if (hand >> i & 1) and self.slot_code[seat][i] == code:
                return i
        raise ValueError("compact exact solver: card not in hand")

    cdef int _subs(self, int seat, int hand) except -1:
        """Canonical sub-multisets of ``hand`` in the reference action order
        (by size, then by the sorted code tuple)."""
        cdef int i, j, x, t, take, total, ncodes = 0, n = 0, len_a, len_b, cmp
        cdef int codes[MAXSLOT]
        cdef int cnt[MAXSLOT]
        cdef int slots_of[MAXSLOT][MAXSLOT]
        cdef uint8_t masks[MAXMOVES]
        cdef uint8_t keys[MAXMOVES][MAXSLOT]
        cdef uint8_t sizes[MAXMOVES]
        cdef uint8_t tmpk[MAXSLOT]
        cdef uint8_t tm, ts
        cdef uint8_t* buf
        if self.n_subs[seat][hand] >= 0:
            return self.n_subs[seat][hand]
        # distinct codes ascending, each with its present slots ascending
        for i in range(self.n_slots[seat]):
            if hand >> i & 1:
                x = self.slot_code[seat][i]
                j = 0
                while j < ncodes and codes[j] != x:
                    j += 1
                if j == ncodes:
                    codes[j] = x
                    cnt[j] = 0
                    ncodes += 1
                slots_of[j][cnt[j]] = i
                cnt[j] += 1
        # sort distinct codes ascending (insertion sort, with their slot rows)
        for i in range(1, ncodes):
            j = i
            while j > 0 and codes[j - 1] > codes[j]:
                codes[j - 1], codes[j] = codes[j], codes[j - 1]
                cnt[j - 1], cnt[j] = cnt[j], cnt[j - 1]
                for t in range(MAXSLOT):
                    slots_of[j - 1][t], slots_of[j][t] = slots_of[j][t], slots_of[j - 1][t]
                j -= 1
        total = 1
        for j in range(ncodes):
            total *= cnt[j] + 1
        for x in range(1, total):
            t = x
            tm = 0
            ts = 0
            for j in range(ncodes):
                take = t % (cnt[j] + 1)
                t //= cnt[j] + 1
                for i in range(take):
                    tm |= 1 << slots_of[j][cnt[j] - 1 - i]
                    keys[n][ts] = codes[j]
                    ts += 1
            masks[n] = tm
            sizes[n] = ts
            n += 1
        # insertion sort by (size, code sequence)
        for i in range(1, n):
            tm = masks[i]
            ts = sizes[i]
            for t in range(ts):
                tmpk[t] = keys[i][t]
            j = i - 1
            while j >= 0:
                if sizes[j] != ts:
                    cmp = sizes[j] > ts
                else:
                    cmp = 0
                    for t in range(ts):
                        if keys[j][t] != tmpk[t]:
                            cmp = keys[j][t] > tmpk[t]
                            break
                if not cmp:
                    break
                masks[j + 1] = masks[j]
                sizes[j + 1] = sizes[j]
                for t in range(MAXSLOT):
                    keys[j + 1][t] = keys[j][t]
                j -= 1
            masks[j + 1] = tm
            sizes[j + 1] = ts
            for t in range(ts):
                keys[j + 1][t] = tmpk[t]
        buf = <uint8_t*>malloc(n + 1)
        if buf == NULL:
            raise MemoryError()
        for i in range(n):
            buf[i] = masks[i]
        self.subs[seat][hand] = buf
        self.n_subs[seat][hand] = n
        return n

# Move enumeration.

    cdef int _moves(self, uint8_t* hands, int turn, int leader, uint8_t* plays,
                    int nplays, uint8_t* out_action, uint8_t* out_played) except -1:
        """``exhaustive_legal_actions`` + what ``Round.play`` records."""
        cdef int hand = hands[turn], n, i, j, o, a, nmoves = 0, beat
        cdef int need, hs, pl, top, forced, fmask, k
        cdef MS* m
        cdef MS* lead
        cdef MS* hsf
        cdef MS* om
        cdef MS* pf
        cdef uint8_t* subs
        if hand == 0:
            raise self.exc_type("acting seat has an empty hand")
        n = self._subs(turn, hand)
        subs = self.subs[turn][hand]
        if nplays == 0:
            for i in range(n):
                a = subs[i]
                m = self._ms(turn, a)
                if m.eff == NONE_EFF:
                    continue
                out_action[nmoves] = a
                out_played[nmoves] = a
                if m.n_comp > 1:
                    # validate_lead: the thrower forfeits the lowest beatable
                    # component, the first one in decomposition order on ties
                    forced = -1
                    for j in range(m.n_comp):
                        pl = m.comp_pair_len[j]
                        top = m.comp_top[j]
                        beat = 0
                        for o in range(4):
                            if o == turn:
                                continue
                            om = self._ms(o, hands[o] & self.suitmask[o][m.eff])
                            if pl == 0:
                                beat = om.max_level > top
                            elif pl == 1:
                                beat = om.max_pair_level > top
                            elif pl < MAXK:
                                beat = om.trac_top[pl] > top
                            else:
                                raise ValueError("tractor longer than tracked")
                            if beat:
                                break
                        if beat and (forced < 0
                                     or pl < m.comp_pair_len[forced]
                                     or (pl == m.comp_pair_len[forced]
                                         and top < m.comp_top[forced])):
                            forced = j
                    if forced >= 0:
                        fmask = 0
                        for j in range(m.comp_ncards[forced]):
                            fmask |= 1 << self._top_slot(turn, hand & ~fmask,
                                                         m.comp_codes[forced][j])
                        out_played[nmoves] = fmask
                nmoves += 1
        else:
            lead = self._ms(leader, plays[0])
            if lead.size > self._ms(turn, hand).size:
                raise self.exc_type("acting hand is shorter than the current lead")
            hs = hand & self.suitmask[turn][lead.eff]
            hsf = self._ms(turn, hs)
            k = lead.single_tractor_k
            if k >= MAXK:
                raise ValueError("tractor longer than tracked")
            for i in range(n):
                a = subs[i]
                pf = self._ms(turn, a)
                if pf.size != lead.size:
                    continue
                if hsf.size >= lead.size:
                    if a & ~hs:
                        continue                      # must follow suit
                    if lead.n_pairs:
                        need = lead.n_pairs
                        if hsf.pair_count < need:
                            need = hsf.pair_count
                        if pf.pair_count < need:
                            continue                  # must play pairs
                    if k and hsf.trac_top[k] != NEG and pf.max_pair_run < k:
                        continue                      # must play a tractor
                elif (a & hs) != hs:
                    continue                          # must play all of the suit
                out_action[nmoves] = a
                out_played[nmoves] = a
                nmoves += 1
        if nmoves == 0:
            raise self.exc_type("active state has no enumerated legal action")
        return nmoves

    cdef int _resolve(self, int leader, uint8_t* plays, int* trick_pts) except -1:
        """``Round._resolve_trick``: the winning seat; sets the trick points."""
        return self._resolve_k(leader, plays, 4, trick_pts)

    cdef int _resolve_k(self, int leader, uint8_t* plays, int k, int* trick_pts) except -1:
        """``_resolve`` over the first ``k`` plays (the current trick winner)."""
        cdef MS* lead = self._ms(leader, plays[0])
        cdef MS* p
        cdef int inc_suit = lead.eff, inc_top = lead.top_level
        cdef int winner = leader, i, seat, top, won
        cdef int pts = lead.pts
        for i in range(1, k):
            seat = (leader + i) % 4
            p = self._ms(seat, plays[i])
            pts += p.pts
            if p.eff == NONE_EFF:
                continue
            if p.size == 1 and lead.size == 1:
                top = p.max_level
            else:
                top = self.T.match_top(self._msi(seat, plays[i]), lead.shape_id)
                if top == NEG:
                    continue
            if p.eff == inc_suit:
                won = top > inc_top
            elif p.eff == TRUMP_EFF:
                won = 1
            else:
                won = 0
            if won:
                winner = seat
                inc_top = top
                inc_suit = p.eff
        trick_pts[0] = pts
        return winner

# Transposition table.

    cdef inline Entry* _lookup(self, uint64_t k1, uint64_t k2) noexcept:
        cdef uint64_t mask = self.tt_cap - 1
        cdef uint64_t i = _mix(k1, k2) & mask
        cdef Entry* e
        while True:
            e = &self.tt[i]
            if e.flags == 0:
                return NULL
            if e.k1 == k1 and e.k2 == k2:
                return e
            i = (i + 1) & mask

    cdef Entry* _slot(self, uint64_t k1, uint64_t k2) except NULL:
        cdef uint64_t mask, i
        cdef Entry* e
        if (self.tt_used + 1) * 2 > self.tt_cap:
            self._grow()
        mask = self.tt_cap - 1
        i = _mix(k1, k2) & mask
        while True:
            e = &self.tt[i]
            if e.flags == 0:
                e.k1 = k1
                e.k2 = k2
                e.flags = 4
                self.tt_used += 1
                return e
            if e.k1 == k1 and e.k2 == k2:
                return e
            i = (i + 1) & mask

    cdef int _grow(self) except -1:
        cdef Entry* old = self.tt
        cdef uint64_t old_cap = self.tt_cap, i, j, mask
        cdef Entry* fresh = <Entry*>calloc(2 * old_cap, sizeof(Entry))
        if fresh == NULL:
            raise MemoryError()
        mask = 2 * old_cap - 1
        for i in range(old_cap):
            if old[i].flags:
                j = _mix(old[i].k1, old[i].k2) & mask
                while fresh[j].flags:
                    j = (j + 1) & mask
                fresh[j] = old[i]
        self.tt = fresh
        self.tt_cap = 2 * old_cap
        free(old)
        return 0

# Search.

    cdef int _child(self, uint8_t* hands, int turn, int points, int leader,
                    uint8_t* plays, int nplays, int played,
                    int alpha, int beta) except? RAISED:
        """``Round.play(turn, played)`` then ``value`` of the child."""
        cdef uint8_t ch[4]
        cdef uint8_t cp[4]
        cdef int winner, tpts
        ch[0] = hands[0]; ch[1] = hands[1]; ch[2] = hands[2]; ch[3] = hands[3]
        cp[0] = plays[0]; cp[1] = plays[1]; cp[2] = plays[2]; cp[3] = 0
        ch[turn] = hands[turn] & ~played
        cp[nplays] = played
        if nplays < 3:
            return self.value(ch, (turn + 1) % 4, points, leader, cp, nplays + 1,
                              alpha, beta)
        winner = self._resolve(leader, cp, &tpts)
        if winner % 2 != self.banker_parity:
            points += tpts
        if (ch[0] | ch[1] | ch[2] | ch[3]) == 0:
            if winner % 2 != self.banker_parity:
                points += (self.kitty_points * KITTY_MULTIPLIER
                           * self._ms(leader, cp[0]).size)
            return self.value(ch, -1, points, -1, cp, 0, alpha, beta)
        return self.value(ch, winner, points, winner, cp, 0, alpha, beta)

    cdef int value(self, uint8_t* hands, int turn, int points, int leader,
                   uint8_t* plays, int nplays, int alpha, int beta) except? RAISED:
        cdef uint64_t k1, k2
        cdef Entry* e
        cdef int lower = NEG, upper = POS, original_alpha = alpha
        cdef int original_beta = beta, answer, v, i, n
        cdef bint maximize
        cdef uint8_t actions[MAXMOVES]
        cdef uint8_t played[MAXMOVES]
        if self.check_budget is not None:
            if self.calls % self.budget_every == 0:
                self.check_budget()
            self.calls += 1
        if turn < 0:
            return points
        k1 = (<uint64_t>hands[0] | (<uint64_t>hands[1] << 8)
              | (<uint64_t>hands[2] << 16) | (<uint64_t>hands[3] << 24)
              | (<uint64_t>turn << 32) | (<uint64_t>leader << 34)
              | (<uint64_t>nplays << 36))
        k2 = <uint64_t>(<uint32_t>points)
        if nplays > 0:
            k2 |= <uint64_t>plays[0] << 32
        if nplays > 1:
            k2 |= <uint64_t>plays[1] << 40
        if nplays > 2:
            k2 |= <uint64_t>plays[2] << 48
        e = self._lookup(k1, k2)
        if e != NULL:
            if e.flags & 1:
                self.cache_hits += 1
                return e.exact
            if e.flags & 2:
                lower = e.lower
                upper = e.upper
        if lower >= beta or upper <= alpha:
            self.cache_hits += 1
            return lower if lower >= beta else upper
        if self.nodes >= self.max_nodes:
            raise self.budget_exc(
                f"exact endgame exceeded max_nodes={self.max_nodes}",
                nodes=self.nodes, cache_hits=self.cache_hits)
        self.nodes += 1

        n = self._moves(hands, turn, leader, plays, nplays, actions, played)
        maximize = (turn % 2) != self.banker_parity
        answer = NEG if maximize else POS
        for i in range(n):
            v = self._child(hands, turn, points, leader, plays, nplays, played[i],
                            alpha, beta)
            if maximize:
                if v > answer:
                    answer = v
            elif v < answer:
                answer = v
            if self.alpha_beta:
                if maximize:
                    if answer > alpha:
                        alpha = answer
                elif answer < beta:
                    beta = answer
                if alpha >= beta:
                    break
        # fail-high/low results are bounds, never exact values
        e = self._slot(k1, k2)
        if original_alpha < answer < original_beta:
            e.exact = answer
            e.flags |= 1
        elif answer <= original_alpha:
            e.lower = lower
            e.upper = upper if upper < answer else answer
            e.flags |= 2
        else:
            e.lower = lower if lower > answer else answer
            e.upper = upper
            e.flags |= 2
        return answer

    def solve(self, rnd):
        """``endgame._solve_root`` for a root ``Round`` -> (value, action)."""
        if self.level:
            raise ValueError("a level-mode session answers solve_level only")
        cdef uint8_t hands[4]
        cdef uint8_t plays[4]
        cdef uint8_t actions[MAXMOVES]
        cdef uint8_t played[MAXMOVES]
        cdef int turn, points, leader, nplays, n, i, best, v
        cdef bint attacker
        nplays = self._import(rnd, hands, plays, &turn, &points, &leader)
        n = self._moves(hands, turn, leader, plays, nplays, actions, played)
        attacker = (turn % 2) != self.banker_parity
        values = []
        for i in range(n):
            values.append(self._child(hands, turn, points, leader, plays, nplays,
                                      played[i], NEG, POS))
        best = max(values) if attacker else min(values)
        i = values.index(best)
        return best, self._codes_of(turn, actions[i])

    # Level mode.
    #
    # ``solve_level`` answers a coarser question than ``solve``: which interval
    # between consecutive ``cuts`` (attacker-point thresholds) holds the root's
    # minimax value.  The S18 objective is a step function of attacker points
    # (`rl.value_afterstate.signed_level_category`), so the interval is all it
    # uses.  Three changes make that cheaper, none of which can change the
    # interval:
    #
    # * the table stores values relative to the points already scored, so a
    #   position reached with different scores shares one entry (every payoff
    #   is additive, so value(state, points) = points + value(state, 0));
    # * null-window tests ``value >= cut`` in a binary search over the cuts,
    #   with a fail-soft bound from the points still in play (hands, current
    #   trick, the largest possible kitty bonus);
    # * move ordering: the table's best move, then (last seat of a trick) the
    #   tricks our side wins, most points first, then history scores.
    #
    # Node counts therefore differ from ``solve``; values do not, up to the
    # interval (``tests/test_endgame_compact.py`` checks this against the
    # reference minimax).

    cdef int _rem_max(self, uint8_t* hands, int leader, uint8_t* plays,
                      int nplays) except? RAISED:
        """An upper bound on the attacker points still to be scored."""
        cdef int s, i, pts = 0, size, most = 0
        for s in range(4):
            if hands[s]:
                pts += self._ms(s, hands[s]).pts
                size = self._ms(s, hands[s]).size
                if size > most:
                    most = size
        for i in range(nplays):
            pts += self._ms((leader + i) % 4, plays[i]).pts
        return pts + self.kitty_points * KITTY_MULTIPLIER * most

    cdef int _lorder(self, uint8_t* hands, int turn, int leader, uint8_t* plays,
                     int nplays, uint8_t* played, int n, int hint) except -1:
        cdef int32_t score[MAXMOVES]
        cdef uint8_t cp[4]
        cdef int i, j, tpts, winner
        cdef int32_t sc
        cdef uint8_t m
        for i in range(n):
            if hint and played[i] == hint:
                score[i] = 1 << 30
                continue
            sc = self.hist[turn][played[i]]
            if nplays == 3:
                cp[0] = plays[0]; cp[1] = plays[1]; cp[2] = plays[2]; cp[3] = played[i]
                winner = self._resolve(leader, cp, &tpts)
                if (winner % 2) == (turn % 2):
                    sc = (1 << 28) + (tpts << 16) + (sc >> 8)
                else:
                    sc = (1 << 26) - (tpts << 16) + (sc >> 8)
            elif nplays:
                cp[0] = plays[0]; cp[1] = plays[1]; cp[2] = plays[2]; cp[3] = 0
                cp[nplays] = played[i]
                winner = self._resolve_k(leader, cp, nplays + 1, &tpts)
                if (winner % 2) == (turn % 2):
                    sc = (1 << 28) + (self._ms(turn, played[i]).pts << 16) + (sc >> 8)
                else:
                    sc = (1 << 26) - (self._ms(turn, played[i]).pts << 16) + (sc >> 8)
            else:
                sc = (self._ms(turn, played[i]).top_level << 20) + (sc >> 8)
            score[i] = sc
        for i in range(1, n):
            m = played[i]
            sc = score[i]
            j = i - 1
            while j >= 0 and score[j] < sc:
                played[j + 1] = played[j]
                score[j + 1] = score[j]
                j -= 1
            played[j + 1] = m
            score[j + 1] = sc
        return 0

    cdef int _lchild(self, uint8_t* hands, int turn, int leader, uint8_t* plays,
                     int nplays, int played, int alpha, int beta) except? RAISED:
        """Attacker points from playing ``played`` on, relative to now."""
        cdef uint8_t ch[4]
        cdef uint8_t cp[4]
        cdef int winner, tpts, gain = 0
        ch[0] = hands[0]; ch[1] = hands[1]; ch[2] = hands[2]; ch[3] = hands[3]
        cp[0] = plays[0]; cp[1] = plays[1]; cp[2] = plays[2]; cp[3] = 0
        ch[turn] = hands[turn] & ~played
        cp[nplays] = played
        if nplays < 3:
            return self.lval(ch, (turn + 1) % 4, leader, cp, nplays + 1, alpha, beta)
        winner = self._resolve(leader, cp, &tpts)
        if winner % 2 != self.banker_parity:
            gain = tpts
        if (ch[0] | ch[1] | ch[2] | ch[3]) == 0:
            if winner % 2 != self.banker_parity:
                gain += (self.kitty_points * KITTY_MULTIPLIER
                         * self._ms(leader, cp[0]).size)
            return gain
        return gain + self.lval(ch, winner, winner, cp, 0, alpha - gain, beta - gain)

    cdef int lval(self, uint8_t* hands, int turn, int leader, uint8_t* plays,
                  int nplays, int alpha, int beta) except? RAISED:
        """Fail-soft alpha-beta on attacker points still to come."""
        cdef uint64_t k1, k2
        cdef Entry* e
        cdef int lower = 0, upper, original_alpha = alpha
        cdef int original_beta = beta, answer, v, i, n, rem, left
        cdef int hint = 0
        cdef uint8_t best = 0
        cdef bint maximize
        cdef uint8_t actions[MAXMOVES]
        cdef uint8_t played[MAXMOVES]
        if self.check_budget is not None:
            if self.calls % self.budget_every == 0:
                self.check_budget()
            self.calls += 1
        if beta <= 0:
            return 0
        rem = self._rem_max(hands, leader, plays, nplays)
        if rem <= alpha:
            return rem
        upper = rem
        k1 = (<uint64_t>hands[0] | (<uint64_t>hands[1] << 8)
              | (<uint64_t>hands[2] << 16) | (<uint64_t>hands[3] << 24)
              | (<uint64_t>turn << 32) | (<uint64_t>leader << 34)
              | (<uint64_t>nplays << 36))
        k2 = 0
        if nplays > 0:
            k2 |= <uint64_t>plays[0] << 32
        if nplays > 1:
            k2 |= <uint64_t>plays[1] << 40
        if nplays > 2:
            k2 |= <uint64_t>plays[2] << 48
        e = self._lookup(k1, k2)
        if e != NULL:
            hint = e.best
            if e.flags & 1:
                self.cache_hits += 1
                return e.exact
            if e.flags & 2:
                if e.lower > lower:
                    lower = e.lower
                if e.upper < upper:
                    upper = e.upper
        if lower >= beta or upper <= alpha:
            self.cache_hits += 1
            return lower if lower >= beta else upper
        if self.nodes >= self.max_nodes:
            raise self.budget_exc(
                f"exact endgame exceeded max_nodes={self.max_nodes}",
                nodes=self.nodes, cache_hits=self.cache_hits)
        self.nodes += 1
        if alpha < lower:
            alpha = lower
        if beta > upper:
            beta = upper

        n = self._moves(hands, turn, leader, plays, nplays, actions, played)
        if n > 1:
            self._lorder(hands, turn, leader, plays, nplays, played, n, hint)
        maximize = (turn % 2) != self.banker_parity
        answer = NEG if maximize else POS
        for i in range(n):
            v = self._lchild(hands, turn, leader, plays, nplays, played[i], alpha, beta)
            if maximize:
                if v > answer:
                    answer = v
                    best = played[i]
                if answer > alpha:
                    alpha = answer
            else:
                if v < answer:
                    answer = v
                    best = played[i]
                if answer < beta:
                    beta = answer
            if alpha >= beta:
                left = (self._ms(turn, hands[turn]).size if hands[turn] else 0) + 1
                if self.hist[turn][played[i]] < (1 << 30):
                    self.hist[turn][played[i]] += left * left
                break
        e = self._slot(k1, k2)
        e.best = best
        if original_alpha < answer < original_beta:
            e.exact = answer
            e.flags |= 1
        elif answer <= original_alpha:
            e.lower = lower
            e.upper = upper if upper < answer else answer
            e.flags |= 2
        else:
            e.lower = lower if lower > answer else answer
            e.upper = upper
            e.flags |= 2
        return answer

    def solve_level(self, rnd, cuts):
        """The root's minimax attacker points, exact up to ``cuts``: returns
        the root's points plus nothing, or the highest cut reached (module
        level-mode notes).  ``cuts``: ascending attacker-point thresholds."""
        cdef uint8_t hands[4]
        cdef uint8_t plays[4]
        cdef int turn, points, leader, nplays, rem, lo, hi, mid, c, v
        if not self.level:
            raise ValueError("solve_level needs a level-mode session")
        nplays = self._import(rnd, hands, plays, &turn, &points, &leader)
        if (hands[0] | hands[1] | hands[2] | hands[3]) == 0 and nplays == 0:
            return points
        rem = self._rem_max(hands, leader, plays, nplays)
        rel = [c - points for c in cuts if points < c <= points + rem]
        lo = 0
        hi = len(rel)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            c = rel[mid - 1]
            v = self.lval(hands, turn, leader, plays, nplays, c - 1, c)
            self.probes += 1
            if v >= c:
                lo = mid
            else:
                hi = mid - 1
        return points + (rel[lo - 1] if lo else 0)

    def solve_points(self, rnd):
        """The root's exact minimax attacker points, by the level-mode search
        with a full window (same table and ordering as ``solve_level``)."""
        cdef uint8_t hands[4]
        cdef uint8_t plays[4]
        cdef int turn, points, leader, nplays, rem
        if not self.level:
            raise ValueError("solve_points needs a level-mode session")
        nplays = self._import(rnd, hands, plays, &turn, &points, &leader)
        if (hands[0] | hands[1] | hands[2] | hands[3]) == 0 and nplays == 0:
            return points
        rem = self._rem_max(hands, leader, plays, nplays)
        return points + self.lval(hands, turn, leader, plays, nplays, -1, rem + 1)
