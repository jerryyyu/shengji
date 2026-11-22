"""Value-pruned, re-rooted two-trick lookahead at a lead (``value_prune_lead``, token ``vp2``), OFF BY DEFAULT.

``SHENGJI_PV_VP2=1`` adds one optional stage to a LEAD decision whose actor holds at least
`VP2_MIN_CARDS` cards, after serving's selection (`PVSearchBot._select`) has chosen the served pick
``b`` from the served value pass.  Nothing before that point changes: the served pass runs exactly
as served and this rule only reads it (`capture_pass`: serving's own accumulator with a capture
matrix and a recording leaf source, both purely additive), so the served pick is the flag-off pick.

1. **Keep set** (`keep_set`): from the served means and the per-world matrix ``v0[w, a]``, keep
   ``b``, the top `KEEP_TOP` by mean, and every candidate whose paired gap to the best,
   ``v0[w, a] - v0[w, best]``, has mean + `KEEP_SE` standard errors >= 0; at most `KEEP_CAP` in
   all, ``b`` first, the rest best mean first.  Rank and paired margin only; never an absolute cut.
   Fewer than two kept: ``b`` is played.
2. **Re-root** (`candidate_values`): each kept candidate's served leaf in each world (the end of the
   decision's own trick, as the served pass priced it) is re-rooted at the next leader ``L``: one
   unified-trunk forward on ``L``'s own information at that leaf (`decision_inputs`), which gives
   both the policy head's card log-odds for ``L`` and the readout frame (`unified_slots.LeafFrame`)
   that prices states of the next trick.  ``L``'s top `LEADS` single-component leads by mean card
   log-odds (`pv_tree_search.single_component_leads`, ties in enumeration order) are each played on
   a copy of the leaf (`pv_two_trick.leaf_copy`) and finished by the served greedy finish
   (`_greedy_finish`) under that frame; the readout prices the end of trick 2 from the root seat's
   team.  ``Q2[w, a]`` is the softmax-of-those-log-odds weighted mean of the `LEADS` values.
3. **Switch** (`choose`): ``d = Q2 - v0`` on the same worlds.  Among the kept candidates the one
   with the best mean ``Q2`` (deep against deep, never against a shallow value) replaces ``b`` only
   when the paired depth evidence alone favours it: `pv_tree_search.depth_override` on ``d`` with
   ``z >= ZMIN``.  Otherwise ``b`` is played.

Each kept candidate is deepened on its own (its leaves, frames, finishes and forwards share nothing
with another candidate's), so a candidate's ``Q2`` column does not depend on which others are kept
(beyond the float rounding a forward's memory layout decides):
the probe switch ``bot.vp2_deepen_all`` (instance attribute; never set by a recipe) deepens every
admitted candidate and keeps the columns in the decision state's ``trace`` for an offline reader,
while the decision itself is still the keep set's.

The rule's wall cap ``SHENGJI_PV_VP2_MAX_SECONDS`` (default `VP2_MAX_SECONDS_DEFAULT`, measured from
the decision's start; token ``vp2s<ms>`` when it differs) is clamped to `VP2_BUDGET_FRACTION` of the
serving budget when one is set.  On expiry the stage stops at its next gate and ``b`` is played
whole; the serving budget's own check runs at every gate and raises as before.  A leaf that is not
at the decision's trick boundary, a missing unified readout or a leaf pass that does not match the
admitted ballot is a contract error (`PVSearchPolicyError`), never a silent fallback.

A served leaf whose first trick ended the round (an eight-card lead into the last trick) has no next
trick: its ``Q2`` is its exact terminal value, equal to the served pass's, and its depth correction 0.
A decision whose served selection fell back to a doomed throw's forced component
(``doomed_throw_reselect_fallback_forced``) plays cards no ballot column prices; the rule skips it
(``vp2_skipped == "forced-component"``) and the served play stands.

The trunk at a re-rooted leaf sees the public refusals of the real round (the root's ledger); a
refusal that happened only inside a sampled world's first trick is not among them.
"""
from __future__ import annotations

import math
import time

import numpy as np

VP2_ENV = "VP2"
VP2_MAX_SECONDS_ENV = "VP2_MAX_SECONDS"
VP2_TOKEN = "vp2"
VP2_MAX_SECONDS_TOKEN = "vp2s"
VP2_MAX_SECONDS_DEFAULT = 5.0
VP2_MAX_SECONDS_RANGE = (0.001, 86400.0)
#: the share of the serving budget the stage may run to, so it stops before the budget aborts it
VP2_BUDGET_FRACTION = 0.8
#: the smallest actor hand the rule acts on (smaller leads belong to the exact lead stage)
VP2_MIN_CARDS = 8
KEEP_TOP = 3
KEEP_SE = 1.0
KEEP_CAP = 4
LEADS = 3
ZMIN = 2.0
VP2_RULE_ID = "lead-keep-top3-pse1-cap4-reroot-policy-top3-softmax-greedy-finish-z2"
#: the digested parameters
VP2_PARAMS = {"min_cards": VP2_MIN_CARDS, "keep_top": KEEP_TOP, "keep_se": KEEP_SE,
              "keep_cap": KEEP_CAP, "leads": LEADS, "zmin": ZMIN,
              "budget_fraction": VP2_BUDGET_FRACTION}
#: the record fields, in order (``vp2_seconds`` measures the run)
VP2_RECORD_FIELDS = ("vp2_eligible", "vp2_applied", "vp2_skipped", "vp2_fallback", "vp2_kept",
                     "vp2_served", "vp2_selected", "vp2_override", "vp2_changed", "vp2_delta",
                     "vp2_se", "vp2_z", "vp2_q2_means", "vp2_d_means", "vp2_reroots",
                     "vp2_value_left", "vp2_reply_left", "vp2_terminal_leaves",
                     "vp2_allowance_seconds", "vp2_seconds")


class Vp2Deadline(Exception):
    """The stage passed its wall cap (internal; caught by `apply`)."""


def new_state(eligible: bool, deadline: float | None, allowance: float | None) -> dict:
    """A decision's rule state.  ``capture`` is pending only on an eligible decision until the
    served pass has run once."""
    return {"eligible": bool(eligible), "capture": bool(eligible), "deadline": deadline,
            "allowance": allowance, "actions": None, "v0": None, "leaves": None,
            "fields": {}, "trace": None}


def record(state) -> dict:
    """The decision record's fields for ``state`` (None: a decision the rule never saw)."""
    fields = dict.fromkeys(VP2_RECORD_FIELDS)
    fields.update(vp2_eligible=False, vp2_applied=False, vp2_override=False, vp2_changed=False)
    if state is not None:
        fields["vp2_eligible"] = state["eligible"]
        fields["vp2_allowance_seconds"] = state["allowance"]
        fields.update(state["fields"])
    return fields


def eligible(rnd, seat) -> bool:
    """A lead whose actor holds at least `VP2_MIN_CARDS` cards (its own hand: public size)."""
    return (rnd.trick is not None and not rnd.trick.plays
            and len(rnd.hands[seat]) >= VP2_MIN_CARDS)


def capture_pass(bot, rnd, seat, actions, worlds, check_budget=None):
    """``(sums, batches)`` of serving's accumulator on ``actions`` (`PVSearchBot._score_leaves`,
    the same leaves, batches and order), keeping the per-world matrix and every leaf in the
    decision state; once per decision (later passes are the plain accumulator)."""
    state = bot._vp2
    state["capture"] = False
    matrix = np.full((len(worlds), len(actions)), np.nan, dtype=np.float64)
    seen = []

    def recording(root, actor, hands, buried, action, world_index):
        leaf = bot._scored_leaf(root, actor, hands, buried, action, world_index)
        seen.append((world_index, tuple(action), leaf))
        return leaf

    sums, batches = bot._score_leaves(rnd, seat, actions, worlds, check_budget,
                                      capture=matrix, leaf=recording)
    from .pv_search_policy import PVSearchPolicyError
    if len(seen) != len(worlds) * len(actions):
        raise PVSearchPolicyError("vp2: the served pass priced a different number of leaves",
                                  stage="vp2_capture")
    leaves = []
    for w in range(len(worlds)):
        row = []
        for a, action in enumerate(actions):
            world_index, cards, leaf = seen[w * len(actions) + a]
            if world_index != w or cards != tuple(action):
                raise PVSearchPolicyError("vp2: the served pass left world-major order",
                                          stage="vp2_capture")
            row.append(leaf)
        leaves.append(row)
    state.update(actions=actions, v0=matrix, leaves=leaves)
    return sums, batches


def keep_set(v0, means, served: int, top: int = KEEP_TOP, se: float = KEEP_SE,
             cap: int = KEEP_CAP) -> list[int]:
    """Admitted positions kept for depth, ascending (module docstring, step 1)."""
    v0 = np.asarray(v0, dtype=np.float64)
    means = np.asarray(means, dtype=np.float64)
    if v0.ndim != 2 or means.shape != (v0.shape[1],) or not 0 <= served < v0.shape[1]:
        raise ValueError("keep_set needs a (worlds x candidates) matrix, its means and the served pick")
    if not (np.isfinite(v0).all() and np.isfinite(means).all()):
        raise ValueError("keep_set needs finite values")
    n_worlds, n = v0.shape
    order = sorted(range(n), key=lambda i: (-means[i], i))
    best = order[0]
    gap = v0 - v0[:, [best]]
    gap_mean = gap.mean(axis=0)
    if n_worlds >= 2:
        gap_se = gap.std(axis=0, ddof=1) / math.sqrt(n_worlds)
    else:
        gap_se = np.zeros(n)
    near = {i for i in range(n) if gap_mean[i] + se * gap_se[i] >= 0}
    leading = set(order[:top])
    rest = [i for i in order if i != served and (i in leading or i in near)]
    return sorted([int(served)] + [int(i) for i in rest[:max(0, cap - 1)]])


def lead_proposals(model, q, hand, ordering, n: int = LEADS):
    """``(leads, weights)``: the top ``n`` single-component leads of ``hand`` by mean card log-odds
    of the policy head on card states ``q`` (stable: enumeration order on ties) and the softmax of
    those log-odds."""
    from .pv_tree_search import single_component_leads
    from .unified_slots import _preferences, policy_from_states
    leads = single_component_leads(hand, ordering)
    if not leads:
        raise ValueError("a leader with no lead")
    prefs = _preferences(policy_from_states(model, q), leads)
    order = np.argsort(-prefs, kind="stable")[:n]
    top = prefs[order]
    weights = np.exp(top - top.max())
    return [leads[i] for i in order], weights / weights.sum()


def candidate_values(bot, model, rnd, seat, leaves, refusals, gate, counters, shallow=None) -> np.ndarray:
    """``(W,)``: ``Q2`` of one candidate from its served leaf in each world (module docstring,
    step 2), from the root seat's team.  A leaf whose first trick ended the round has no second
    trick: its ``Q2`` is its exact terminal value through the served evaluator, which must equal
    the served pass's value of that cell (``shallow[w]``, when given), so its depth correction is 0."""
    from ..ai.belief_numpy import decision_inputs
    from .pv_search_policy import PVSearchPolicyError
    from .pv_tree_search import greedy_stats
    from .pv_two_trick import leaf_copy
    from .unified_slots import LeafFrame
    boundary = len(rnd.history) + 1
    target = boundary + 1
    out = np.empty(len(leaves), dtype=np.float64)
    root_frame = bot.unified_frame
    stats = greedy_stats()
    for w, leaf in enumerate(leaves):
        gate()
        if leaf.phase == "round_end" and len(leaf.history) == boundary:
            exact = float(np.asarray(bot.evaluator.score([leaf], seat), dtype=np.float64)[0])
            if not math.isfinite(exact) or (shallow is not None and exact != float(shallow[w])):
                raise PVSearchPolicyError("vp2: a terminal leaf's value is not the served pass's",
                                          stage="vp2_terminal_value")
            out[w] = exact
            counters["terminal"] += 1
            continue
        if leaf.phase != "play" or len(leaf.history) != boundary \
                or (leaf.trick is not None and leaf.trick.plays):
            raise PVSearchPolicyError("vp2: a served leaf is not at the decision's trick boundary",
                                      stage="vp2_leaf_horizon")
        leader = int(leaf.turn)
        inp = decision_inputs(leaf, leader, refusals)
        q, g = model.card_states(inp, model.trunk.encode_history(inp))
        counters["reroots"] += 1
        frame = LeafFrame.at_states(bot, leaf, leader, model, q, g)
        leads, weights = lead_proposals(model, q, leaf.hands[leader], leaf.ordering)
        clones = []
        for lead in leads:
            clone = leaf_copy(leaf)
            clone.play(leader, list(lead))
            clones.append(clone)
        value_other, reply_served = bot.unified_value_other, bot.unified_reply_served
        bot.unified_frame = frame
        try:
            open_ = [c for c in clones if c.phase == "play" and len(c.history) < target]
            if open_:
                bot._greedy_finish(open_, target, gate, stats)
            if any(c.phase == "play" and (len(c.history) != target or (c.trick is not None and c.trick.plays))
                   for c in clones):
                raise PVSearchPolicyError("vp2: a continuation did not end at the next trick boundary",
                                          stage="vp2_continuation")
            gate()
            values = np.asarray(bot.evaluator.score(clones, seat), dtype=np.float64)
        finally:
            bot.unified_frame = root_frame
        counters["value_left"] += bot.unified_value_other - value_other
        counters["reply_left"] += bot.unified_reply_served - reply_served
        if values.shape != (len(clones),) or not np.isfinite(values).all():
            raise PVSearchPolicyError("vp2: the readout returned no finite value per continuation",
                                      stage="vp2_values")
        out[w] = float(weights @ values)
    return out


def choose(q2, v0, kept, served: int, zmin: float = ZMIN):
    """``(winner, test)`` (module docstring, step 3): ``q2`` and ``v0`` are ``(W, len(kept))``
    columns aligned with ``kept``; ``test`` is `depth_override`'s result, or None when the best
    deep mean is the served pick's."""
    from .pv_tree_search import depth_override
    q2 = np.asarray(q2, dtype=np.float64)
    v0 = np.asarray(v0, dtype=np.float64)
    s = kept.index(served)
    means = q2.mean(axis=0)
    j = int(np.argmax(means))
    if means[j] == means[s]:
        j = s
    if j == s:
        return served, None
    test = depth_override(q2 - v0, j, s, zmin)
    return (kept[j] if test["override"] else served), test


def apply(bot, rnd, seat, admitted, means, winner: int, check_budget=None) -> int:
    """The admitted position to play: ``winner`` (the served pick) unless the rule switches it.
    Sets the decision state's record fields (and ``trace`` under ``vp2_deepen_all``)."""
    state = bot._vp2
    fields = state["fields"]
    t0 = time.perf_counter()
    try:
        return _apply(bot, rnd, seat, admitted, means, winner, check_budget, state, fields)
    finally:
        fields["vp2_seconds"] = time.perf_counter() - t0


def _apply(bot, rnd, seat, admitted, means, winner, check_budget, state, fields):
    from .pv_search_policy import PVSearchPolicyError
    fields.update(vp2_served=int(winner), vp2_selected=int(winner))
    doomed = getattr(bot, "_doomed_throw", None) if getattr(bot, "doomed_throw_reselect", False) else None
    if doomed is not None and doomed.get("doomed_throw_reselect_fallback_forced"):
        # every admitted candidate was a doomed throw: the served play is the selected throw's
        # forced component, not ``admitted[winner]``, so no ballot column prices what is played
        fields["vp2_skipped"] = "forced-component"
        return winner
    if len(admitted) < 2:
        fields["vp2_skipped"] = "single"
        return winner
    if state["actions"] is not admitted or state["v0"] is None:
        raise PVSearchPolicyError("vp2: the served pass of the admitted ballot was not captured",
                                  stage="vp2_capture")
    v0 = state["v0"]
    if v0.shape[1] != len(admitted) or not np.isfinite(v0).all():
        raise PVSearchPolicyError("vp2: the captured value matrix is incomplete", stage="vp2_capture")
    model = getattr(bot, "unified_value_model", None)
    if model is None or getattr(bot, "unified_reply_model", None) is not model \
            or getattr(bot, "unified_prior_model", None) is not model:
        raise PVSearchPolicyError("vp2 needs the unified value, reply and prior slots of one package",
                                  stage="vp2_unified")
    kept = keep_set(v0, means, int(winner))
    fields["vp2_kept"] = kept
    if len(kept) < 2:
        fields["vp2_skipped"] = "single"
        return winner
    deadline = state["deadline"]

    def gate():
        if check_budget is not None:
            check_budget()
        if deadline is not None and time.perf_counter() >= deadline:
            raise Vp2Deadline

    refusals = bot._refusals.observe(rnd) if getattr(bot, "refusal_constraints", False) else ()
    deepen = list(range(len(admitted))) if getattr(bot, "vp2_deepen_all", False) else kept
    counters = {"reroots": 0, "value_left": 0, "reply_left": 0, "terminal": 0}
    columns, cpu, wall = {}, {}, {}
    try:
        for a in deepen:
            c0, w0 = time.thread_time(), time.perf_counter()
            columns[a] = candidate_values(bot, model, rnd, seat, [row[a] for row in state["leaves"]],
                                          refusals, gate, counters, shallow=v0[:, a])
            cpu[a], wall[a] = time.thread_time() - c0, time.perf_counter() - w0
        gate()
    except Vp2Deadline:
        fields.update(vp2_fallback="deadline", vp2_reroots=counters["reroots"],
                      vp2_value_left=counters["value_left"], vp2_reply_left=counters["reply_left"])
        return winner
    q2 = np.stack([columns[a] for a in kept], axis=1)
    v0k = v0[:, kept]
    chosen, test = choose(q2, v0k, kept, int(winner))
    fields.update(vp2_applied=True, vp2_selected=int(chosen), vp2_changed=int(chosen) != int(winner),
                  vp2_override=test is not None and bool(test["override"]),
                  vp2_q2_means=[float(v) for v in q2.mean(axis=0)],
                  vp2_d_means=[float(v) for v in (q2 - v0k).mean(axis=0)],
                  vp2_reroots=counters["reroots"], vp2_value_left=counters["value_left"],
                  vp2_reply_left=counters["reply_left"], vp2_terminal_leaves=counters["terminal"])
    if test is not None:
        fields.update(vp2_delta=float(test["delta"]),
                      vp2_se=float(test["se"]) if math.isfinite(test["se"]) else None,
                      vp2_z=float(test["z"]) if math.isfinite(test["z"]) else None)
    if getattr(bot, "vp2_deepen_all", False):
        state["trace"] = {"v0": v0.copy(), "means": np.asarray(means, dtype=np.float64).copy(),
                          "served": int(winner), "kept": list(kept),
                          "q2": np.stack([columns[a] for a in deepen], axis=1),
                          "cpu": [cpu[a] for a in deepen], "wall": [wall[a] for a in deepen]}
    return int(chosen)
