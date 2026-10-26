# cython: language_level=3, boundscheck=False, wraparound=False
"""Compiled kernels behind the served search's native latency switch
(`pv_native`).  Each kernel reproduces one Python reference exactly: the same
items in the same order, the same floats; `pv_native` owns every Python-level
check and falls back to the reference whenever a kernel declines.

* `subset_listing`: `harvest.legal.multiset_subsets` (distinct sub-multisets
  in lexicographic order) as card-index rows, capped, optionally filtered by a
  validator (the in-suit follow case) or merged with a fixed base (the short
  and void cases), as `pv_tree_search.CompactReplies` stores a listing.
"""
from libc.stdlib cimport malloc, free, realloc
from libc.string cimport memcpy

import numpy as np


cdef class _Out:
    """A growing int8 card buffer and its int32 offsets."""
    cdef signed char *cards
    cdef int *offsets
    cdef Py_ssize_t ncards, cap_cards, nrows, cap_rows

    def __cinit__(self):
        self.cap_cards = 1024
        self.cap_rows = 256
        self.cards = <signed char *> malloc(self.cap_cards)
        self.offsets = <int *> malloc((self.cap_rows + 1) * sizeof(int))
        if self.cards == NULL or self.offsets == NULL:
            raise MemoryError()
        self.ncards = 0
        self.nrows = 0
        self.offsets[0] = 0

    def __dealloc__(self):
        free(self.cards)
        free(self.offsets)

    cdef int push(self, const signed char *row, int n) except -1:
        cdef void *p
        while self.ncards + n > self.cap_cards:
            self.cap_cards *= 2
            p = realloc(self.cards, self.cap_cards)
            if p == NULL:
                raise MemoryError()
            self.cards = <signed char *> p
        if self.nrows + 1 > self.cap_rows:
            self.cap_rows *= 2
            p = realloc(self.offsets, (self.cap_rows + 1) * sizeof(int))
            if p == NULL:
                raise MemoryError()
            self.offsets = <int *> p
        memcpy(self.cards + self.ncards, row, n)
        self.ncards += n
        self.nrows += 1
        self.offsets[self.nrows] = <int> self.ncards
        return 0

    cdef tuple arrays(self):
        cards = np.empty(self.ncards, dtype=np.int8)
        offsets = np.empty(self.nrows + 1, dtype=np.int32)
        cdef signed char[::1] cv = cards
        cdef int[::1] ov = offsets
        cdef Py_ssize_t i
        for i in range(self.ncards):
            cv[i] = self.cards[i]
        for i in range(self.nrows + 1):
            ov[i] = self.offsets[i]
        return cards, offsets


cdef class _Lister:
    """One listing: the recursion of `multiset_subsets` over ``ncodes``
    distinct codes, emitting each subset (merged with ``base`` when given,
    filtered by ``validate`` when given) until ``cap`` rows are kept."""
    cdef int ncodes, cap, nbase, size
    cdef int *counts
    cdef int *chosen
    cdef signed char *code_index      # card index of each distinct code
    cdef int *code_rank               # global sort rank of each distinct code
    cdef signed char *base_index
    cdef int *base_rank
    cdef signed char *row
    cdef int *row_rank
    cdef _Out out
    cdef object validate              # None or (validate_follow, IllegalPlay, hand, lead, ordering, names)
    cdef bint done

    def __cinit__(self):
        self.counts = NULL
        self.chosen = NULL
        self.code_index = NULL
        self.code_rank = NULL
        self.base_index = NULL
        self.base_rank = NULL
        self.row = NULL
        self.row_rank = NULL

    def __dealloc__(self):
        free(self.counts); free(self.chosen); free(self.code_index); free(self.code_rank)
        free(self.base_index); free(self.base_rank); free(self.row); free(self.row_rank)

    cdef int emit(self) except -1:
        """The current subset (``chosen``) as one row; 1 when the cap is reached."""
        cdef int i, k, n = 0, b, f, total
        cdef signed char *tmp_index
        cdef int *tmp_rank
        # the subset itself, codes in sorted order (``out`` of the reference)
        for i in range(self.ncodes):
            for k in range(self.chosen[i]):
                self.row[self.nbase + n] = self.code_index[i]
                self.row_rank[self.nbase + n] = self.code_rank[i]
                n += 1
        total = self.nbase + n
        if self.nbase:
            # tuple(sorted(base + fill)): both runs are sorted and share no
            # code, so a merge by global rank is the sort
            b = 0
            f = self.nbase
            i = 0
            # merge into the front of a scratch copy
            tmp_index = <signed char *> malloc(total)
            tmp_rank = <int *> malloc(total * sizeof(int))
            if tmp_index == NULL or tmp_rank == NULL:
                free(tmp_index); free(tmp_rank)
                raise MemoryError()
            while b < self.nbase or f < total:
                if f >= total or (b < self.nbase and self.base_rank[b] <= self.row_rank[f]):
                    tmp_index[i] = self.base_index[b]
                    tmp_rank[i] = self.base_rank[b]
                    b += 1
                else:
                    tmp_index[i] = self.row[f]
                    tmp_rank[i] = self.row_rank[f]
                    f += 1
                i += 1
            memcpy(self.row, tmp_index, total)
            free(tmp_index)
            free(tmp_rank)
        if self.validate is not None:
            fn, error, hand, lead, ordering, names = self.validate
            play = [names[self.row[i]] for i in range(total)]
            try:
                fn(play, hand, lead, ordering)
            except error:
                return 0
        self.out.push(self.row, total)
        if self.out.nrows >= self.cap:
            self.done = True
            return 1
        return 0

    cdef int rec(self, int i, int left) except -1:
        cdef int k, top
        if self.done:
            return 1
        if left == 0:
            return self.emit()
        if i == self.ncodes:
            return 0
        top = self.counts[i] if self.counts[i] < left else left
        k = top
        while k >= 0:
            self.chosen[i] = k
            if self.rec(i + 1, left - k):
                self.chosen[i] = 0
                return 1
            self.chosen[i] = 0
            k -= 1
        return 0


def subset_listing(list codes, list counts, int size, int cap, dict card_index, dict rank,
                   list base=None, validate=None):
    """``(cards int8, offsets int32)``: the first ``cap`` rows of
    ``multiset_subsets(cards, size)`` (``codes``: the distinct codes in sorted
    order, ``counts`` their multiplicities), each row the subset's
    `card_index` values -- merged with ``base`` (sorted codes sharing none
    with ``codes``) into the sorted order of ``rank`` when ``base`` is given,
    and kept only when ``validate`` (``(fn, error, hand, lead, ordering,
    names)``: ``fn(play, hand, lead, ordering)`` raising ``error`` for a
    refused play) accepts it."""
    cdef _Lister lister = _Lister()
    cdef int n = len(codes), i, nb = 0 if base is None else len(base)
    if cap <= 0 or size < 0:
        return _Out().arrays()
    lister.ncodes = n
    lister.cap = cap
    lister.size = size
    lister.nbase = nb
    lister.counts = <int *> malloc((n + 1) * sizeof(int))
    lister.chosen = <int *> malloc((n + 1) * sizeof(int))
    lister.code_index = <signed char *> malloc(n + 1)
    lister.code_rank = <int *> malloc((n + 1) * sizeof(int))
    lister.base_index = <signed char *> malloc(nb + 1)
    lister.base_rank = <int *> malloc((nb + 1) * sizeof(int))
    lister.row = <signed char *> malloc(nb + size + 1)
    lister.row_rank = <int *> malloc((nb + size + 1) * sizeof(int))
    if (lister.counts == NULL or lister.chosen == NULL or lister.code_index == NULL
            or lister.code_rank == NULL or lister.base_index == NULL or lister.base_rank == NULL
            or lister.row == NULL or lister.row_rank == NULL):
        raise MemoryError()
    for i in range(n):
        lister.counts[i] = counts[i]
        lister.chosen[i] = 0
        lister.code_index[i] = card_index[codes[i]]
        lister.code_rank[i] = rank[codes[i]]
    for i in range(nb):
        lister.base_index[i] = card_index[base[i]]
        lister.base_rank[i] = rank[base[i]]
        lister.row[i] = lister.base_index[i]
        lister.row_rank[i] = lister.base_rank[i]
    lister.out = _Out()
    lister.validate = validate
    lister.done = False
    lister.rec(0, size)
    return lister.out.arrays()


# ------------------------------------------------------------ static encoding
#
# `encode_static_batch` is `pv_encode_prefix.fused_many_batched` for a batch
# in which every row is kept: it returns None (the caller then runs the
# Python builder on the whole batch) on any row the Python builder would skip,
# refuse or treat specially, and otherwise the same public, world and
# perspective arrays.  Every plane cell is a count of half copies and every
# scalar is the reference's own double expression, cast to float32 once.

DEF NC = 54
DEF NSUIT = 5          # the effective suits, numbered in `_SUIT_ORDER`'s order
DEF V1 = 531           # OBS_DIM


cdef inline int _mod4(long x):
    return <int> (((x % 4) + 4) % 4)


cdef int _traverse_c(object trick, object trickplay_cls, dict card_index,
                     const signed char *suit_of, double *played, long *physical,
                     unsigned int *voids, double *planes, long *events) except -2:
    """`pv_encode_prefix._traverse` on C accumulators: 0 done, -1 where the
    reference returns None.  ``played`` is (4, 54), ``planes`` (3, 54) or NULL."""
    cdef list plays = trick.plays
    cdef Py_ssize_t position, j, n
    cdef int lead_suit = -1, suit, seat, index
    cdef bint off_suit
    cdef object play, cards, card, seat_obj, index_obj
    for position in range(len(plays)):
        play = plays[position]
        if type(play) is not trickplay_cls:
            return -1
        cards = play.cards
        seat_obj = play.seat
        if type(cards) is not list or not cards or type(seat_obj) is not int:
            return -1
        if not 0 <= seat_obj < 4:
            return -1
        seat = seat_obj
        events[0] += 1
        off_suit = False
        n = len(<list> cards)
        for j in range(n):
            card = (<list> cards)[j]
            if type(card) is not str:
                return -1
            index_obj = card_index.get(card)
            if index_obj is None:
                return -1
            index = index_obj
            suit = suit_of[index]
            if lead_suit < 0:
                lead_suit = suit
            if position and suit != lead_suit:
                off_suit = True
            played[seat * NC + index] += 0.5
            physical[index] += 1
            if planes != NULL:
                planes[position * NC + index] += 0.5
        if off_suit:
            voids[seat] |= 1u << lead_suit
    return 0


cdef bint _checked_c(object rnd, object seat, object round_cls, object ordering_cls,
                     object trick_cls, object ranks, dict card_index) except -1:
    """`pv_encode_prefix._checked`, the same tests in the same order."""
    if (type(rnd) is not round_cls or type(seat) is not int or not 0 <= seat < 4
            or rnd.phase != "play" or type(rnd.ordering) is not ordering_cls
            or type(rnd.history) is not list or type(rnd.hands) is not list
            or len(rnd.hands) != 4 or type(rnd.buried) is not list
            or type(rnd.banker) is not int or not 0 <= rnd.banker < 4
            or type(rnd.attacker_points) is not int
            or type(rnd.trump_is_nt) is not bool or rnd.trump_rank not in ranks
            or type(rnd.trick) is not trick_cls or type(rnd.trick.plays) is not list
            or len(rnd.trick.plays) > 3):
        return False
    declaration = rnd.declaration
    if declaration is not None:
        if (type(declaration) is not dict
                or type(declaration.get("seat")) is not int
                or not 0 <= declaration["seat"] < 4
                or type(declaration.get("cards")) is not list
                or not declaration["cards"]):
            return False
        for card in declaration["cards"]:
            if type(card) is not str or card not in card_index:
                return False
    return True


def encode_static_batch(tuple tricks, object ordering, double[:, ::1] prefix_played,
                        long[::1] prefix_physical, unsigned int[::1] prefix_voids,
                        long prefix_events, list positions, list seats, int version,
                        dict card_index, const signed char[::1] suit_of,
                        const unsigned char[::1] is_trump, tuple types, object checked,
                        object trick_state, object suits, object ranks, dict suit_index,
                        int max_events):
    """``(public, world, perspective)`` (float32, ``(m, width)``, ``(m, 5,
    54)``, ``(m, 2)``) of every row, or None.  ``types`` is ``(Round, Trick,
    TrickPlay)``; ``checked`` is `pv_encode_prefix._checked`; ``trick_state``
    is `encode_versions.trick_state` (memoized per distinct trick here, a
    function of the trick's plays and the ordering).  ``suit_of`` and
    ``suit_index`` number the effective suits in `_SUIT_ORDER`'s order;
    ``suits`` and ``ranks`` are `SUITS` and `RANKS`."""
    cdef object round_cls = types[0], trick_cls = types[1], trickplay_cls = types[2]
    cdef Py_ssize_t m = len(positions), row, k, c, depth = len(tricks), w, who
    cdef int seat, rel, index, banker, extra = 0 if version == 1 else (29 if version == 2 else 33)
    cdef int width = V1 + extra + 1
    cdef object rnd, history, hands, cards, card, index_obj, trick, attacker
    cdef long events, ap, total_cards, ut, copies, pairs
    cdef double v
    if version not in (1, 2, 7) or m == 0 or len(seats) != m:
        return None
    public = np.zeros((m, width), dtype=np.float64)
    world = np.zeros((m, 5, NC), dtype=np.float64)
    perspective = np.zeros((m, 2), dtype=np.float32)
    cdef double[:, ::1] pub = public
    cdef double[:, :, ::1] wv = world
    cdef float[:, ::1] pv = perspective
    cdef double played[4 * NC]
    cdef double planes[3 * NC]
    cdef long physical[NC]
    cdef unsigned int voids[4]
    cdef double total
    cdef dict states = {}
    for row in range(m):
        rnd = positions[row]
        seat_obj = seats[row]
        if type(seat_obj) is not int or not _checked_c(rnd, seat_obj, round_cls, types[3],
                                                       trick_cls, ranks, card_index):
            return None
        seat = seat_obj
        if rnd.ordering is not ordering:
            return None
        history = rnd.history
        if len(<list> history) < depth:
            return None
        for k in range(depth):
            if (<list> history)[k] is not tricks[k]:
                return None
        hands = rnd.hands
        for c in range(NC):
            physical[c] = prefix_physical[c]
        # the five world planes: the hands from the acting seat, then the burial
        for rel in range(5):
            cards = (<list> hands)[(seat + rel) % 4] if rel < 4 else rnd.buried
            if type(cards) is not list:
                return None
            for k in range(len(<list> cards)):
                card = (<list> cards)[k]
                if type(card) is not str:
                    return None
                index_obj = card_index.get(card)
                if index_obj is None:
                    return None
                index = index_obj
                wv[row, rel, index] += 0.5
                physical[index] += 1
        for who in range(4):
            for c in range(NC):
                played[who * NC + c] = prefix_played[who, c]
            voids[who] = prefix_voids[who]
        for c in range(3 * NC):
            planes[c] = 0.0
        events = prefix_events
        for k in range(depth, len(<list> history)):
            trick = (<list> history)[k]
            if type(trick) is not trick_cls or type(trick.plays) is not list \
                    or len(<list> trick.plays) != 4:
                return None
            if _traverse_c(trick, trickplay_cls, card_index, &suit_of[0], played, physical,
                           voids, NULL, &events) < 0:
                return None
        if _traverse_c(rnd.trick, trickplay_cls, card_index, &suit_of[0], played, physical,
                       voids, planes, &events) < 0:
            return None
        if not 1 <= events <= max_events:
            return None
        for c in range(NC):
            if physical[c] != 2:
                return None
        # v1: own, the four played planes from the acting seat, the trick planes, unseen
        for c in range(NC):
            pub[row, c] = wv[row, 0, c]
        for rel in range(4):
            who = (seat + rel) % 4
            for c in range(NC):
                pub[row, NC * (1 + rel) + c] = played[who * NC + c]
        for k in range(3):
            for c in range(NC):
                pub[row, NC * (5 + k) + c] = planes[k * NC + c]
        for c in range(NC):
            total = played[c] + played[NC + c]
            total = total + played[2 * NC + c]
            total = total + played[3 * NC + c]
            v = 1.0 - total - wv[row, 0, c]
            pub[row, 8 * NC + c] = v if v > 0.0 else 0.0
        # the tail: trump suit, trump rank, banker seat, score, cards left, side, voids
        w = 9 * NC
        if rnd.trump_is_nt:
            pub[row, w + 4] = 1.0
        else:
            trump_suit = rnd.trump_suit
            # the reference refuses a row whose suit ``in SUITS`` cannot test
            if type(trump_suit) is not str:
                return None
            if trump_suit in suits:
                pub[row, w + <int> suits.index(trump_suit)] = 1.0
        pub[row, w + 5 + <int> ranks.index(rnd.trump_rank)] = 1.0
        banker = rnd.banker
        pub[row, w + 18 + _mod4(banker - seat)] = 1.0
        attacker = rnd.is_attacker(seat)
        ap = rnd.attacker_points
        pub[row, w + 22] = (ap if ap < 200 else 200) / 200.0
        total_cards = 0
        for k in range(4):
            total_cards += len(<list> (<list> hands)[k])
        pub[row, w + 23] = total_cards / 100.0
        pub[row, w + 24] = 1.0 if attacker else 0.0
        for rel in range(4):
            who = (seat + rel) % 4
            for k in range(NSUIT):
                if voids[who] & (1u << k):
                    pub[row, w + 25 + rel * NSUIT + k] = 1.0
        if attacker:
            pv[row, 0] = 1.0
        else:
            pv[row, 1] = 1.0
        if version == 1:
            continue
        # v2: the trick in progress, the score band, the hand; v7: the next actor
        w = V1
        trick = rnd.trick
        key = tuple([(p.seat, tuple(p.cards)) for p in trick.plays])
        state = states.get(key)
        if state is None:
            state = states[key] = trick_state(rnd, seat)
        winner, lead_suit, trick_pts = state
        if winner is not None:
            pub[row, w + _mod4(winner - seat)] = 1.0
            if winner != seat and _mod4(winner - seat) % 2 == 0:
                pub[row, w + 4] = 1.0
        pub[row, w + 5] = (trick_pts if trick_pts < 80 else 80) / 80.0
        if lead_suit is not None:
            pub[row, w + 6 + <int> suit_index[lead_suit]] = 1.0
        k = len(<list> trick.plays)
        pub[row, w + 11 + (k if k < 3 else 3)] = 1.0
        if k:
            pub[row, w + 15] = len(<list> (<list> trick.plays)[0].cards) / 6.0
        ap = ap if ap < 200 else 200
        v = (ap - 80) / 80.0
        pub[row, w + 16] = -1.0 if v < -1.0 else (1.0 if v > 1.0 else v)
        pub[row, w + 17 + (0 if ap < 40 else 1 if ap < 80 else 2 if ap < 120 else 3)] = 1.0
        # the hand columns, from the acting seat's world plane
        ut = 0
        pairs = 0
        copies = 0
        for c in range(NC):
            index = <int> (wv[row, 0, c] * 2)
            copies += index
            if wv[row, 0, c] == 1.0:
                pairs += 1
            if index:
                pub[row, w + 21 + suit_of[c]] += index
            if is_trump[c]:
                # the unseen plane as float32, doubled, as the reference counts it
                ut += <long> ((<float> pub[row, 8 * NC + c]) * 2)
        for k in range(NSUIT):
            pub[row, w + 21 + k] = pub[row, w + 21 + k] / 27.0
        pub[row, w + 26] = ut / 27.0
        pub[row, w + 27] = pairs / 13.0
        pub[row, w + 28] = copies / 27.0
        if version == 7:
            turn = rnd.turn
            if (rnd.phase == "play" and isinstance(turn, int) and not isinstance(turn, bool)
                    and 0 <= turn < 4):
                pub[row, w + 29 + _mod4(turn - seat)] = 1.0
    return public.astype(np.float32), world.astype(np.float32), perspective



# --------------------------------------------------------------- world draw
#
# `belief_draw` is the copy loop of `train.belief_seq.sample_worlds`: the same
# Hall test over the 16 receiver subsets, the same weights, the same
# ``rng.random(W)`` call per copy (the generator is the caller's, called at
# the same point), the same normalisations and right-open bins, the same
# refusals.  Every float is the reference's own double expression evaluated in
# the reference's order (``w / peak``; a running sum; ``cdf / cdf[last]``).

def belief_draw(const double[:, ::1] P, const unsigned char[:, ::1] M,
                const long[::1] copies, const long[::1] types, long[::1] tc,
                const long[::1] sizes, int W, object rng, object error):
    """``(W, 54, 4)`` int16 copy counts, as `sample_worlds` returns them
    (``copies``, ``types`` and ``tc`` are its prologue's arrays)."""
    cdef Py_ssize_t n = copies.shape[0], k, w, r, q, S, t
    out = np.zeros((W, 54, 4), dtype=np.int16)
    cap_arr = np.empty((W, 4), dtype=np.int64)
    cdef short[:, :, ::1] ov = out
    cdef long[:, ::1] cap = cap_arr
    cdef long need[16]
    cdef long s_cap
    cdef int c
    cdef bint okw[4]
    cdef bint any_ok, fits
    cdef double wt[4]
    cdef double cdf[4]
    cdef double peak, u
    cdef long k_r
    cdef const double[::1] uv
    if P.shape[0] != 54 or P.shape[1] != 4 or M.shape[0] != 54 or M.shape[1] != 4 \
            or sizes.shape[0] != 4 or tc.shape[0] != 16 or types.shape[0] != n:
        raise ValueError("belief_draw: shape drift")
    for w in range(W):
        for r in range(4):
            cap[w, r] = sizes[r]
    oks = np.zeros((W, 4), dtype=np.uint8)
    cdef unsigned char[:, ::1] okv = oks
    picks = np.zeros(W, dtype=np.int64)
    cdef long[::1] pv = picks
    for k in range(n):
        c = <int> copies[k]
        t = types[k]
        tc[t] -= 1
        # need[S] = copies still to place whose feasible set lies inside S
        for S in range(16):
            need[S] = 0
            for q in range(16):
                if (q & ~S) == 0:
                    need[S] += tc[q]
        any_ok = True
        for w in range(W):
            fits = False
            for r in range(4):
                okw[r] = False
                if M[c, r] and cap[w, r] > 0:
                    okw[r] = True
                    for S in range(16):
                        s_cap = 0
                        for q in range(4):
                            if S & (1 << q):
                                s_cap += cap[w, q] - (1 if q == r else 0)
                        if s_cap < need[S]:
                            okw[r] = False
                            break
                okv[w, r] = okw[r]
                if okw[r]:
                    fits = True
            if not fits:
                any_ok = False
        if not any_ok:
            raise error("no completable receiver (infeasible state)")
        uv = rng.random(W)
        for w in range(W):
            for r in range(4):
                wt[r] = P[c, r] if okv[w, r] else 0.0
            peak = wt[0]
            for r in range(1, 4):
                if wt[r] > peak:
                    peak = wt[r]
            if peak > 0:
                for r in range(4):
                    wt[r] = wt[r] / peak
            else:
                for r in range(4):
                    wt[r] = 1.0 if okv[w, r] else 0.0
            cdf[0] = wt[0]
            for r in range(1, 4):
                cdf[r] = cdf[r - 1] + wt[r]
            for r in range(4):
                cdf[r] = cdf[r] / cdf[3]
            u = uv[w]
            k_r = 0
            for r in range(4):
                if cdf[r] <= u:
                    k_r += 1
            pv[w] = k_r
        for w in range(W):
            if pv[w] >= 4 or not okv[w, pv[w]]:
                raise error("categorical draw selected an infeasible receiver")
        for w in range(W):
            ov[w, c, pv[w]] += 1
            cap[w, pv[w]] -= 1
    return out
