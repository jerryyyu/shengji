"""Two-trick value leaves at a lead (``two_trick_lead``, token ``tt2``), OFF BY DEFAULT.

``SHENGJI_PV_TT2=1`` changes only what the value head prices at a LEAD decision.
Every accumulator pass of that decision (`PVSearchBot._score_leaves`: the value
pass, the lead confirmation's matrices, the adaptive-worlds rounds) first runs
exactly as served, on the served first-trick leaves, and keeps those sums.  It
then copies each distinct leaf once (`leaf_copy`: fresh hands, trick and history
list; the completed tricks are shared, never mutated), plays the NEXT trick on
the copies with the policy head's argmax at every seat, each seat encoded from
its own view of its copy (`play_next_trick`), and runs the same accumulator on
the copies.  Those sums are the pass's result.

Consumers that need the first trick's horizon never see a copy: the points
tie-break (`PolicyValueBot._trick_points`) and the exact stages build or read
the served leaves through `_scored_leaf` / `_leaf`, which this rule never
replaces, and the copies are distinct objects, so nothing they do reaches a
served leaf or the greedy finish's cache.

A leaf whose round ended in its first trick is priced as it stands (it is its
own copy).  A live leaf must sit exactly one trick past the decision root;
anything else is a contract error, not a fallback.

The per-decision wall cap ``SHENGJI_PV_TT2_MAX_SECONDS`` (default
`TT2_MAX_SECONDS_DEFAULT`, measured from the decision's start, token
``tt2s<ms>`` when it differs from the default) is clamped to
`TT2_BUDGET_FRACTION` of the serving budget when one is set.  When the deadline
passes inside a pass's second-trick work, that pass returns the first-trick sums
it already computed, whole, and every later pass of the decision is priced on
the first trick as well; the record counts each such pass.  The serving budget's
own check still runs everywhere it ran and raises as before.
"""
from __future__ import annotations

import time

import numpy as np

TT2_ENV = "TT2"
TT2_MAX_SECONDS_ENV = "TT2_MAX_SECONDS"
TT2_TOKEN = "tt2"
TT2_MAX_SECONDS_TOKEN = "tt2s"
TT2_MAX_SECONDS_DEFAULT = 5.0
TT2_MAX_SECONDS_RANGE = (0.001, 86400.0)
#: the share of the serving budget the second-trick work may run to, so the
#: decision falls back to its first-trick sums before the serving budget aborts it
TT2_BUDGET_FRACTION = 0.8
#: the rule's recipe identity
TT2_RULE_ID = "lead-value-leaf-plus-next-trick-policy-argmax-every-seat"
#: the record fields, in order (``tt2_seconds`` measures the run)
TT2_RECORD_FIELDS = ("tt2_lead", "tt2_passes", "tt2_fallbacks", "tt2_fallback",
                     "tt2_leaves", "tt2_round_end_leaves", "tt2_policy_rows",
                     "tt2_allowance_seconds", "tt2_seconds")


class TwoTrickDeadline(Exception):
    """The decision passed the rule's deadline inside its second-trick work
    (internal; caught by `score_leaves`)."""


def new_state(rnd_is_lead: bool, deadline: float | None, allowance: float | None) -> dict:
    """A decision's rule state: active only at a lead."""
    return {"active": bool(rnd_is_lead), "lead": bool(rnd_is_lead), "deadline": deadline,
            "allowance": allowance, "expired": False, "passes": 0, "fallbacks": 0,
            "leaves": 0, "round_end": 0, "policy_rows": 0, "seconds": 0.0}


def record(state) -> dict:
    """The decision record's fields for ``state`` (None: a decision the rule
    never saw, such as one that failed before its search began)."""
    if state is None:
        state = new_state(False, None, None)
    return {"tt2_lead": state["lead"], "tt2_passes": state["passes"],
            "tt2_fallbacks": state["fallbacks"], "tt2_fallback": state["fallbacks"] > 0,
            "tt2_leaves": state["leaves"], "tt2_round_end_leaves": state["round_end"],
            "tt2_policy_rows": state["policy_rows"],
            "tt2_allowance_seconds": state["allowance"], "tt2_seconds": state["seconds"]}


def leaf_copy(leaf):
    """A distinct position equal to ``leaf``: the attributes `Round.play`
    mutates in place (the hands, the kitty list, the open trick and the history
    list) are fresh; the completed tricks are the same objects, so a copy's
    history still extends the decision root's by identity (`pv_encode_prefix`)."""
    from ..engine.round import Trick, TrickPlay
    from .pv_tree_search import shallow_round

    clone = shallow_round(leaf)
    clone.hands = [list(hand) for hand in leaf.hands]
    clone.buried = list(leaf.buried)
    if leaf.trick is not None:
        clone.trick = Trick(leader=leaf.trick.leader,
                            plays=[TrickPlay(p.seat, list(p.cards)) for p in leaf.trick.plays])
        clone.trick.running_points = leaf.trick.running_points
        clone.trick.incumbent = leaf.trick.incumbent
    clone.history = list(leaf.history)
    return clone


def play_next_trick(bot, clones, target, guard=None, prefix=None) -> int:
    """Play every clone in ``clones`` until its history reaches ``target``
    tricks or its round ends: at each turn the acting seat plays the policy
    head's highest-scoring legal action (`pv_tree_search.legal_replies`: a lead
    is one component, ranked by its mean card log-odds; a follow by its summed
    log-odds; a stable sort keeps enumeration order on ties), its row encoded
    from that seat's view of the clone.  ``guard`` is called before every
    clone's listing and every policy batch.  Returns the policy rows scored."""
    from .policy_prior import ENC_VERSION, N_CARDS, flat_input, root_tensors
    from .pv_tree_search import legal_replies

    version = getattr(bot, "version", ENC_VERSION)
    rows_scored = 0
    cache = {}
    active = [c for c in clones if c.phase == "play" and len(c.history) < target]
    while active:
        by_seat = {}
        for clone in active:
            by_seat.setdefault(clone.turn, []).append(clone)
        for seat, group in by_seat.items():
            pending = []
            for clone in group:
                if guard is not None:
                    guard()
                legal, scoring = legal_replies(bot, clone, seat, cache)
                if len(legal) == 1:
                    clone.play(seat, list(legal[0]))
                    continue
                pending.append((clone, legal, scoring))
            if not pending:
                continue
            if prefix is not None:
                from .pv_encode_prefix import reply_rows
                rows = reply_rows([clone for clone, _, _ in pending], seat, version, prefix)
            else:
                rows = [flat_input(root_tensors(clone, seat, version), version)
                        for clone, _, _ in pending]
            for start in range(0, len(rows), bot.batch_size):
                if guard is not None:
                    guard()
                chunk = np.stack(rows[start:start + bot.batch_size]).astype(np.float32)
                logits = np.asarray(bot.predict(chunk), dtype=np.float64)
                if logits.shape != (len(chunk), N_CARDS) or not np.isfinite(logits).all():
                    raise ValueError("policy requires finite rows x 54 log-odds")
                for row, (clone, legal, scoring) in zip(
                        logits, pending[start:start + bot.batch_size]):
                    best = int(np.argsort(-(scoring @ row), kind="stable")[0])
                    clone.play(seat, list(legal[best]))
            rows_scored += len(rows)
        active = [c for c in active if c.phase == "play" and len(c.history) < target]
    return rows_scored


def score_leaves(bot, rnd, seat, actions, worlds, check_budget=None, capture=None):
    """``(sums, batches)`` of one accumulator pass under the rule (module
    docstring).  ``capture`` receives the cells of the sums returned: the
    second trick's when the pass completes, else the first trick's."""
    from .pv_search_policy import PVSearchPolicyError

    state = bot._two_trick
    t0 = time.perf_counter()
    served = []

    def recording(root, actor, hands, buried, action, world_index):
        leaf = bot._scored_leaf(root, actor, hands, buried, action, world_index)
        served.append((world_index, tuple(action), leaf))
        return leaf

    first_sums, first_batches = bot._score_leaves(rnd, seat, actions, worlds, check_budget,
                                                  capture=capture, leaf=recording)
    if state["expired"]:
        state["fallbacks"] += 1
        state["seconds"] += time.perf_counter() - t0
        return first_sums, first_batches
    deadline = state["deadline"]

    def guard():
        if check_budget is not None:
            check_budget()
        if deadline is not None and time.perf_counter() >= deadline:
            raise TwoTrickDeadline

    target = len(rnd.history) + 2
    copies, round_end = {}, 0
    for _, _, leaf in served:
        if id(leaf) in copies:
            continue
        if leaf.phase != "play":
            copies[id(leaf)] = leaf
            round_end += 1
            continue
        if len(leaf.history) != target - 1:
            raise PVSearchPolicyError("tt2: a value leaf is not one trick past the root",
                                      stage="tt2_leaf_horizon")
        copies[id(leaf)] = leaf_copy(leaf)
    replay = iter(served)

    def next_trick_leaf(root, actor, hands, buried, action, world_index):
        expected_world, expected_action, leaf = next(replay)
        if root is not rnd or actor != seat or expected_world != world_index \
                or expected_action != tuple(action):
            raise PVSearchPolicyError("tt2: the second pass left the first pass's order",
                                      stage="tt2_leaf_order")
        return copies[id(leaf)]

    second = None if capture is None else np.full(capture.shape, np.nan, dtype=np.float64)
    try:
        prefix = None
        if bot.encode_prefix_cache:
            from .pv_encode_prefix import HistoryPrefix
            prefix = HistoryPrefix.of(rnd, batched=bot.encode_batch_fast,
                                      native=bot.encode_native)
        rows = play_next_trick(bot, [c for c in copies.values() if c.phase == "play"],
                               target, guard, prefix)
        state["policy_rows"] += rows
        sums, batches = bot._score_leaves(rnd, seat, actions, worlds, guard,
                                          capture=second, leaf=next_trick_leaf)
    except TwoTrickDeadline:
        state["expired"] = True
        state["fallbacks"] += 1
        state["seconds"] += time.perf_counter() - t0
        return first_sums, first_batches
    if next(replay, None) is not None:
        raise PVSearchPolicyError("tt2: the second pass priced fewer leaves than the first",
                                  stage="tt2_leaf_order")
    if capture is not None:
        capture[...] = second
    state["passes"] += 1
    state["leaves"] += len(copies) - round_end
    state["round_end"] += round_end
    state["seconds"] += time.perf_counter() - t0
    return sums, first_batches + batches
