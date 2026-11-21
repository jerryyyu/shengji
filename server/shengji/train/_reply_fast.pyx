# cython: language_level=3, boundscheck=False, wraparound=False
"""The greedy finish's reply children of one clone, compiled
(`pv_tree_search.reply_children_fast`).

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

`project_singleton_replies` only builds the card moves and trick metadata
that a same-trick readout consumes. It needs the standard compiled follow
policy and a trusted, nonterminal singleton trick.
"""
from cpython.dict cimport PyDict_Copy


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


def project_singleton_replies(clone, int seat, list candidates, int frame_seat,
                              parent, tuple plane_maps, dict points, tuple actual,
                              long prior_points, decide, beats, trickplay_cls):
    cdef _ReplyState state = _ReplyState()
    cdef _ReplyTrick trick = _ReplyTrick()
    cdef object source = clone.trick
    cdef list prior = source.plays
    cdef list lead
    cdef tuple cached = source.incumbent
    cdef long cached_points = source.running_points
    cdef int pos, turn, relative, n_prior = len(prior)
    cdef long pts, total
    cdef tuple incumbent, updated
    cdef list out = [], slots
    cdef object candidate, cards, card
    if not 1 <= n_prior <= 2 or not 0 <= seat < 4 or not 0 <= frame_seat < 4:
        return None
    lead = prior[0].cards
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
            if type(cards) is not list or len(cards) != 1:
                return None
            card = cards[0]
            if pos == n_prior and (type(card) is not str or card not in state.hands[turn]):
                return None
            relative = (turn - frame_seat + 4) % 4
            slots.append(plane_maps[relative][card])
            pts = points[card]
            total += pts
            updated = _reply_incumbent(cards, lead, incumbent, state.ordering, turn, beats)
            if pos < 3:
                # The heuristic observes the transition caches, including if
                # they differ from the winner and points computed for the readout.
                if trick.incumbent == incumbent:
                    trick.incumbent = updated
                else:
                    trick.incumbent = _reply_incumbent(cards, lead, trick.incumbent,
                                                       state.ordering, turn, beats)
                trick.running_points += pts
                trick.plays.append(trickplay_cls(turn, cards))
                turn = (turn + 1) % 4
                cards = decide(state, turn)
            incumbent = updated
        out.append((parent, slots, total, (incumbent[0] - frame_seat) % 4))
    return out
