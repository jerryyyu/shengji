# cython: language_level=3, boundscheck=False, wraparound=False
"""Compiled reply children and completed-trick count planes for the greedy finish.

`reply_children` builds, for each candidate in order, exactly what
``child_position_fast(clone, seat, candidate)`` followed by
``finish_current_trick(child)`` builds: a new ``Round`` whose ``__dict__`` is a
copy of the clone's, the same fresh hands, buried cards, trick, history and
flags assigned in the same order, the candidate played and the trick finished
by the heuristic.  Every play is ``child.play`` as the reference calls it
(the engine routing in force) and every heuristic reply is the ``decide``
passed in (the default finisher's ``decide_play``).  The caller owns
every check that makes the plain dict copy and item assignments the
reference's attribute operations.

`project_replies` only builds the card moves and trick metadata
that a same-trick readout consumes. It needs the standard compiled follow
policy and a trusted, nonterminal trick with a one-component lead.
"""
import numpy as np

from cpython.dict cimport PyDict_Copy
from cpython.long cimport PyLong_AsLong, PyLong_AsLongLong
from libc.string cimport memcpy


def reply_children(object clone, object seat, list candidates, object round_cls,
                   object trick_cls, object trickplay_cls, object decide):
    cdef dict base = clone.__dict__
    cdef dict d
    cdef list out = []
    cdef object hands = clone.hands
    cdef list prior
    cdef object trick = clone.trick
    cdef object leader = trick.leader
    cdef object running = trick.running_points
    cdef object incumbent = trick.incumbent
    cdef object buried = clone.buried
    cdef object history = clone.history
    cdef object last = clone.last_trick
    cdef object new = object.__new__
    cdef object child, t, tr, s
    prior = [(p.seat, p.cards) for p in trick.plays]
    for cards in candidates:
        child = new(round_cls)
        d = PyDict_Copy(base)
        d["hands"] = [list(h) for h in hands]
        d["buried"] = list(buried)
        t = trick_cls(leader=leader, plays=[trickplay_cls(ps, list(pc)) for ps, pc in prior])
        t.running_points = running
        t.incumbent = incumbent
        d["trick"] = t
        d["history"] = list(history)
        d["last_trick"] = last
        d["message"] = None
        d["_trusted_rollout"] = True
        d["_determinized_world"] = True
        child.__dict__ = d
        child.play(seat, list(cards))
        while child.phase == "play":
            tr = child.trick
            if tr is None or not tr.plays:
                break
            s = child.turn
            if s is None:
                raise AssertionError
            child.play(s, decide(child, s))
        out.append(child)
    return out


cdef class _ReplyTrick:
    cdef readonly list plays
    cdef readonly tuple incumbent
    cdef readonly long running_points


cdef class _ReplyState:
    cdef readonly _ReplyTrick trick
    cdef readonly list hands
    cdef readonly object ordering

    @property
    def _trusted_rollout(self):
        return True


cdef inline tuple _reply_incumbent(list cards, list lead, tuple incumbent,
                                   object ordering, int seat, object beats):
    won, top = beats(cards, lead, incumbent[1], incumbent[2], ordering)
    if won:
        return (seat, ordering.eff_suit(cards[0]), top)
    return incumbent


def project_replies(clone, int seat, list candidates, int frame_seat,
                    parent, tuple plane_maps, dict points, tuple actual,
                    long prior_points, decide, beats, trickplay_cls, bint memo_heuristic=False):
    cdef _ReplyState state = _ReplyState()
    cdef _ReplyTrick trick = _ReplyTrick()
    cdef object source = clone.trick
    cdef list prior = source.plays
    cdef list lead
    cdef tuple cached = source.incumbent
    cdef long cached_points = source.running_points
    cdef int pos, turn, relative, width, n_prior = len(prior)
    cdef long pts, total
    cdef tuple incumbent, updated
    cdef list out = [], slots, hand, played
    cdef dict lookup, decisions = {} if memo_heuristic and len(candidates) > 1 else None
    cdef tuple key
    cdef object candidate, cards, card
    if not 1 <= n_prior <= 2 or not 0 <= seat < 4 or not 0 <= frame_seat < 4:
        return None
    lead = prior[0].cards
    width = len(lead)
    if not width:
        return None
    state.trick = trick
    # Each remaining player acts once. The compiled follow and its validator
    # read only that player's hand, so those hands can be shared with the parent.
    state.hands = clone.hands
    state.ordering = clone.ordering
    for candidate in candidates:
        trick.plays = prior.copy()
        trick.incumbent = cached
        trick.running_points = cached_points
        incumbent = actual
        total = prior_points
        slots = []
        cards = candidate
        turn = seat
        for pos in range(n_prior, 4):
            if type(cards) is not list or len(cards) != width:
                return None
            played = <list>cards
            relative = (turn - frame_seat + 4) % 4
            lookup = plane_maps[relative]
            if width == 1:
                card = played[0]
                if pos == n_prior and (type(card) is not str or card not in state.hands[turn]):
                    return None
                slots.append(lookup[card])
                pts = points[card]
            else:
                if pos == n_prior:
                    hand = state.hands[turn]
                    for card in played:
                        if type(card) is not str or played.count(card) > hand.count(card):
                            return None
                pts = 0
                for card in played:
                    slots.append(lookup[card])
                    pts += points[card]
            total += pts
            updated = _reply_incumbent(played, lead, incumbent, state.ordering, turn, beats)
            if pos < 3:
                # The heuristic observes the transition caches, including if
                # they differ from the winner and points computed for the readout.
                if trick.incumbent == incumbent:
                    trick.incumbent = updated
                else:
                    trick.incumbent = _reply_incumbent(played, lead, trick.incumbent,
                                                       state.ordering, turn, beats)
                trick.running_points += pts
                if trick.running_points > 200:
                    return None
                trick.plays.append(trickplay_cls(turn, played))
                turn = (turn + 1) % 4
                if decisions is None:
                    cards = decide(state, turn)
                else:
                    # The stock policy reads the fixed lead and hand, the cache
                    # fields, and whether this is the last seat. Within this
                    # parent, the seat also identifies the ply.
                    key = (turn, trick.incumbent, trick.running_points)
                    cards = decisions.get(key)
                    if cards is None:
                        cards = decide(state, turn)
                        decisions[key] = cards
            incumbent = updated
        out.append((parent, slots, total, (incumbent[0] - frame_seat) % 4))
    return out

DEF N_CARDS = 54
DEF HAND_WIDTH = 4 * N_CARDS
DEF PLAY_OFFSET = 5 * N_CARDS
DEF COUNT_WIDTH = 9 * N_CARDS


def pack_reply_rows(items, n_delta):
    """Copy each parent row and move the listed hand slots into played planes."""
    cdef tuple rows = tuple(items)
    cdef Py_ssize_t n = len(rows), i
    cdef long delta = PyLong_AsLong(n_delta)
    cdef long slot, won
    cdef object source, slots, points, winner, card
    cdef object held = None
    cdef const unsigned char[::1] parent
    if n == 0 or not 1 <= delta <= 4:
        raise ValueError("invalid completed-trick batch")
    counts = np.empty((n, COUNT_WIDTH), dtype=np.uint8)
    meta = np.empty((n, 5), dtype=np.int64)
    cdef unsigned char[:, ::1] cv = counts
    cdef long long[:, ::1] mv = meta
    for i, (source, slots, points, winner) in enumerate(rows):
        # Consecutive replies from one parent reuse its buffer view.
        if i == 0 or source is not held:
            parent = source
            if parent is None or parent.shape[0] != COUNT_WIDTH:
                raise ValueError("invalid reply parent width")
            held = source
        memcpy(&cv[i, 0], &parent[0], COUNT_WIDTH)
        for card in slots:
            slot = PyLong_AsLong(card)
            if not 0 <= slot < HAND_WIDTH:
                raise ValueError("reply hand slot out of range")
            if cv[i, slot] == 0 or cv[i, slot + PLAY_OFFSET] == 255:
                raise ValueError("invalid reply count delta")
            cv[i, slot] -= 1
            cv[i, slot + PLAY_OFFSET] += 1
        won = PyLong_AsLong(winner)
        if not 0 <= won < 4:
            raise ValueError("reply winner out of range")
        mv[i, 0] = delta
        mv[i, 1] = 4
        mv[i, 2] = PyLong_AsLongLong(points)
        mv[i, 3] = won
        mv[i, 4] = won
    return counts, meta
