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
