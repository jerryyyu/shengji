"""Oracle ceiling screens: production search vs. the same search with an
oracle leaf value and/or an oracle ballot prior, on paired mirrored deals.

THE QUESTION.  ``mc-s0-report-lcb`` is a two-stage determinized search: an
N=30 ballot/search nominates one challenger to the heuristic incumbent, then
the fixed pair is re-compared on R=300 fresh shared hidden worlds under a
one-sided paired LCB rule.  Every leaf of both stages is ONE deterministic
heuristic continuation of a fully determinized world.  Before a learned
value head or a learned ballot prior is built, this module bounds what each
could buy by replacing it with a much more expensive oracle:

``value``
    Identical worlds and identical ballot.  Each leaf continuation is
    replaced by a DEEPER evaluation of the same determinized world: the
    continuation is played out with greedy one-ply rollout policy improvement
    (every seat, in play order, picks the move whose plain heuristic
    continuation is best for its own team), funded by ``LEAF_MULTIPLIER``
    plain continuation rollouts per leaf instead of production's one; the
    optional S3b exact partnership-minimax solver replaces the tail once
    every hand is within ``EXACT_ENDGAME_MAX_CARDS``.  Sampling, ballot,
    selection rule and report rule are byte-for-byte production code.

``prior``
    Production search work, but the ballot is ranked and pruned per decision
    by a 240-world high-N paired evaluation of the very same candidates (the
    ``highn_build.py`` reference method: shared worlds across candidates,
    plain production continuation).  The incumbent stays candidate 0; the
    remaining ``PRIOR_KEEP_TOP - 1`` slots take the best-ranked other
    candidates in rank order.  Selection worlds scale so that the pruned
    ballot receives production's total selection rollouts (the
    ``MCPriorRace`` equal-work convention); the report fold is unchanged.

``both``
    Both mixins on one bot.

``wide``
    Coverage ceiling (issue #205 step 2).  The production BALLOT is replaced
    by the best candidates of the EXHAUSTIVE legal set, everything else
    production.  Per contested decision the legal set ``L`` is enumerated
    (``shengji.harvest.legal.enumerate_legal``, capped at ``WIDE_CAP`` and
    always containing the production ballot); stage 1 scores every action in
    ``L`` on ``WIDE_SCREEN_WORLDS`` shared worlds and keeps the top
    ``WIDE_KEEP_STAGE1`` (the incumbent always survives); stage 2 ranks the
    survivors with the prior's ``PRIOR_WORLDS``-world machinery and keeps
    ``WIDE_KEEP_TOP`` (incumbent at index 0, or the oracle's favourite with
    ``PRIOR_ANCHOR``).  That ballot goes to the production search with
    ``N_DETERMINIZATIONS`` UNCHANGED: a wider ballot simply costs more
    selection worlds, which the counters record (``wide_fixed_n``).

``wide-value``
    ``wide`` stacked with ``value``, as ``both`` stacks ``prior`` with it.

``none`` / ``null``
    Controls: ``none`` plays the production policy on both sides with the
    arm's seeds (the identity witness for a neutral-knob arm); ``null`` plays
    the champion-matched null (same policy, RNG stream shifted by the registry
    offset) so the reviewer sees the noise floor on the same deals.

Neutral knobs reproduce production decisions exactly: ``LEAF_MULTIPLIER=1``
with the exact solver off routes every leaf through the production
``_rollout``; ``PRIOR_KEEP_TOP=0`` never computes a prior; ``WIDE_KEEP_TOP=0``
never enumerates.  All three are tested.

The arms count their extra work honestly.  ``rollouts`` keeps production's
meaning (leaves scored by the search); ``continuation_rollouts`` is the number
of plain continuations actually played; ``prior_rollouts``/``prior_worlds``
and ``wide_stage1_rollouts``/``wide_stage2_rollouts``/``wide_worlds`` are the
oracles' own sampling, kept apart from the production sampler counters that
the decision record reports; ``total_rollouts`` charges all of it to the arm.

Design/measurement rules follow ``shengji.evaluation``: both mirrors of one
seeded deal are one cluster, the cluster is the uncertainty unit, and the
verdict-free summary carries a clustered bootstrap interval.
"""
from __future__ import annotations

import copy
import hashlib
import inspect
import json
import math
import os
import platform
import random
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from functools import lru_cache
from pathlib import Path

from ..ai.endgame import ExactEndgameBudgetExceeded
from ..ai.env import play_round
from ..ai.mcbot import MCBot, _child_seed
from ..ai.memory import Memory
from ..ai.registry import REGISTRY, make_bot
from ..engine.combos import decompose
from ..engine.game import Game
from ..engine.round import Trick, TrickPlay
from ..evaluation import counters as production_counters
from ..harvest.legal import enumerate_legal

ARMS = ("none", "null", "value", "prior", "both", "wide", "wide-value")
#: Which mixin each oracle arm carries.
VALUE_ARMS = ("value", "both", "wide-value")
PRIOR_ARMS = ("prior", "both")
WIDE_ARMS = ("wide", "wide-value")
ORACLE_ARMS = ("value", "prior", "both", "wide", "wide-value")
DEFAULT_BASE_POLICY = "mc-s0-report-lcb"
#: Same shift the registry uses for every champion-matched null.
NULL_SEED_OFFSET = 999_983
ROUND_SCHEMA = "oracle-ceiling-round-v1"
SUMMARY_SCHEMA = "oracle-ceiling-summary-v1"
RUNTIME_SCHEMA = "oracle-ceiling-runtime-v1"
DEFAULT_BOOTSTRAP_REPLICATES = 10_000
DEFAULT_BOOTSTRAP_SEED = 20_260_904

SERVER = Path(__file__).resolve().parents[2]


class OracleScreenError(RuntimeError):
    """The requested screen cannot support its stated measurement."""


# ------------------------------------------------------------------ value arm

class OracleValueMixin:
    """Deeper leaf evaluation of the SAME determinized world.

    ``LEAF_MULTIPLIER`` is the number of plain continuation rollouts a leaf
    may consume (production: 1).  Rollouts fund greedy one-ply lookahead at
    successive continuation decisions in play order: the acting seat's
    candidates are its plain heuristic move plus the production ballot for
    that perfect-information state; each is scored by a plain continuation,
    the seat plays the best for its team, and the chosen candidate's
    continuation value is reused when the budget runs out.  When fewer
    rollouts remain than candidates, the first ``remaining`` candidates are
    scored (heuristic move first, then ballot order).  A single-candidate
    decision plays the heuristic move at no cost.  With the exact solver on,
    lookahead stops at the proved boundary because the solver values that
    state exactly.

    The heuristic continuation is deterministic, so a reused value is the
    value the plain continuation would have produced from that state.
    """

    LEAF_MULTIPLIER = 1
    #: A ceiling screen must survive an exact-solver budget overflow: the
    #: overflowing leaf falls back to the heuristic tail and is COUNTED.
    #: (S3b's fail-closed contract propagates instead; this is not S3b.)
    ORACLE_EXACT_FALLBACK = True

    def __init__(self, seed: int | None = None):
        super().__init__(seed)
        self.oracle_leaves = 0
        self.oracle_continuation_rollouts = 0
        self.oracle_lookahead_decisions = 0
        self.oracle_lookahead_candidates = 0
        self.oracle_inline_plies = 0
        self.oracle_exact_budget_fallbacks = 0

    def _rollout(self, rnd, seat, sampled, buried, candidate, *,
                 exact_session=None):
        if self.LEAF_MULTIPLIER <= 1 and not self.EXACT_ENDGAME:
            # Neutral knob: the production leaf, byte for byte.
            return super()._rollout(rnd, seat, sampled, buried, candidate,
                                    exact_session=exact_session)
        clone = self._oracle_world_clone(rnd, seat, sampled, buried)
        clone.play(seat, list(candidate))
        value, spent, improved, evaluated, inline = \
            self._oracle_deep_continuation(clone, exact_session)
        self.oracle_leaves += 1
        self.oracle_continuation_rollouts += spent
        self.oracle_lookahead_decisions += improved
        self.oracle_lookahead_candidates += evaluated
        self.oracle_inline_plies += inline
        return value

    # The clone construction mirrors MCBot._rollout exactly (canonical hands,
    # copied trick, trusted append-only rollout, marked determinized world).
    def _oracle_world_clone(self, rnd, seat, sampled, buried):
        clone = copy.copy(rnd)
        clone.hands = self._complete_determinized_hands(
            rnd, seat, sampled, buried=buried)
        clone.buried = sorted(buried)
        assert rnd.trick is not None
        clone.trick = Trick(
            leader=rnd.trick.leader,
            plays=[TrickPlay(p.seat, list(p.cards)) for p in rnd.trick.plays])
        clone.history = list(rnd.history)
        clone.last_trick = rnd.last_trick
        clone.message = None
        clone._trusted_rollout = True
        clone._determinized_world = True
        return clone

    @staticmethod
    def _oracle_copy(clone):
        """Copy exactly the state ``Round.play`` mutates (trick caches too)."""
        child = copy.copy(clone)
        child.hands = [list(h) for h in clone.hands]
        child.history = list(clone.history)
        trick = clone.trick
        child.trick = None if trick is None else Trick(
            leader=trick.leader,
            plays=[TrickPlay(p.seat, list(p.cards)) for p in trick.plays],
            winner=trick.winner, points=trick.points,
            incumbent=trick.incumbent, running_points=trick.running_points)
        return child

    @classmethod
    def _oracle_child(cls, clone, seat, cards):
        child = cls._oracle_copy(clone)
        child.play(seat, list(cards))
        return child

    def _oracle_exact_value(self, clone, session):
        try:
            return self._exact_endgame_value(clone, session)
        except ExactEndgameBudgetExceeded:
            if not self.ORACLE_EXACT_FALLBACK:
                raise
            self.oracle_exact_budget_fallbacks += 1
            return None

    def _oracle_plain_continuation(self, clone, session) -> float:
        """Production's continuation loop: heuristic play, exact tail if on."""
        policy = self.rollout_policy
        exact_on = self.EXACT_ENDGAME
        while clone.phase == "play":
            if exact_on:
                exact = self._oracle_exact_value(clone, session)
                if exact is not None:
                    return exact
            s = clone.turn
            clone.play(s, policy.decide_play(clone, s))
        return float(clone.attacker_points)

    def _oracle_lookahead_candidates(self, clone, seat) -> list[list[str]]:
        base = list(self.rollout_policy.decide_play(clone, seat))
        out = [base]
        seen = {tuple(sorted(base))}
        # The PRODUCTION generator, bypassing any prior-arm pruning override.
        for cand in MCBot._candidates(self, clone, seat):
            key = tuple(sorted(cand))
            if key not in seen:
                seen.add(key)
                out.append(list(cand))
        return out

    def _oracle_deep_continuation(self, clone, session):
        """Returns (value, continuation rollouts, lookahead decisions,
        candidates scored, inline heuristic plies).

        Accounting: every plain continuation played to the end counts one
        rollout; a leaf whose value came from the inline heuristic line with
        no lookahead counts one (it IS production's rollout); a leaf that ends
        on a reused lookahead value counts nothing more.  Inline plies are
        the single-candidate heuristic moves played on the main line (a
        fraction of one rollout per leaf) and are reported separately.
        """
        budget = int(self.LEAF_MULTIPLIER)
        spent = improved = evaluated = inline = 0
        cached = None
        exact_on = self.EXACT_ENDGAME
        while clone.phase == "play":
            if exact_on and max(len(h) for h in clone.hands) <= \
                    self.EXACT_ENDGAME_MAX_CARDS:
                break
            remaining = budget - spent
            if remaining < 2:
                break
            seat = clone.turn
            cands = self._oracle_lookahead_candidates(clone, seat)
            if len(cands) < 2:
                # Heuristic move: still the plain line, so `cached` stays valid.
                clone.play(seat, cands[0])
                inline += 1
                continue
            take = min(len(cands), remaining)
            children = [self._oracle_child(clone, seat, cand)
                        for cand in cands[:take]]
            vals = [self._oracle_plain_continuation(self._oracle_copy(child),
                                                    session)
                    for child in children]
            spent += take
            improved += 1
            evaluated += take
            choose = max if clone.is_attacker(seat) else min
            pick = vals.index(choose(vals))
            # Adopt the chosen child: its scored continuation is the main
            # line from here, so nothing is replayed.
            clone = children[pick]
            cached = vals[pick]
        if clone.phase != "play":
            if cached is None:
                spent += 1
            return float(clone.attacker_points), spent, improved, evaluated, inline
        if cached is not None:
            return cached, spent, improved, evaluated, inline
        return (self._oracle_plain_continuation(clone, session),
                spent + 1, improved, evaluated, inline)


# ------------------------------------------------------------------ prior arm

class OraclePriorMixin:
    """Rank and prune the production ballot with a per-decision high-N oracle.

    ``PRIOR_KEEP_TOP`` is the number of ballot entries the production search
    receives: the incumbent (candidate 0) plus the ``PRIOR_KEEP_TOP - 1``
    best-ranked other candidates in rank order; ``0`` disables the prior
    (neutral knob).  With ``PRIOR_ANCHOR`` the ranking also chooses the
    incumbent: the ballot becomes the top ``PRIOR_KEEP_TOP`` candidates in
    rank order and the report fold protects the oracle's favourite instead
    of SmartBot's.  ``PRIOR_EQUAL_WORK`` scales the selection worlds so the
    pruned ballot consumes production's ``N x K`` selection rollouts.

    The ranking uses ``PRIOR_WORLDS`` fresh worlds from the production
    sampler on a named child stream (``oracle-prior``), scored with the plain
    production continuation for every candidate on every world, exactly as
    ``scripts/highn_build.py`` built the 240-world reference.  The production
    selection/report streams are untouched: the prior neither advances
    ``self.rng`` nor changes the report seed derived from it.
    """

    PRIOR_WORLDS = 240
    PRIOR_KEEP_TOP = 0
    PRIOR_EQUAL_WORK = True
    PRIOR_ANCHOR = False

    def __init__(self, seed: int | None = None):
        super().__init__(seed)
        self._oracle_pruned = None
        self.last_oracle_prior = None
        self.oracle_prior_decisions = 0
        self.oracle_prior_worlds = 0
        self.oracle_prior_rollouts = 0
        self.oracle_prior_short = 0
        self.oracle_prior_zero_world = 0
        self.oracle_prior_candidates_seen = 0
        self.oracle_prior_candidates_kept = 0
        self.oracle_prior_incumbent_replaced = 0
        self.oracle_prior_sample_attempts = 0
        self.oracle_prior_accepted_worlds = 0
        self.oracle_prior_failed_worlds = 0
        self.oracle_prior_rejected_worlds = 0
        # Wall time of the ranking itself; production's search_secs starts
        # after the prior has run, so this is the only place it is charged.
        self.oracle_prior_secs = 0.0

    def _candidates(self, rnd, seat):
        if self._oracle_pruned is not None:
            return self._oracle_pruned
        return super()._candidates(rnd, seat)

    def decide_play(self, rnd, seat):
        self.last_oracle_prior = None
        if self.PRIOR_KEEP_TOP <= 0:
            return super().decide_play(rnd, seat)
        # Production returns a locked tractor lead before it enumerates a
        # ballot; do not spend an oracle on a decision the search never sees.
        if self.TRACTOR_LOCK and not rnd.trick.plays:
            pick = self.canonical_lead(rnd, seat)
            dec = decompose(pick, rnd.ordering)
            if len(dec.components) == 1 and dec.components[0].pair_len >= 2:
                return super().decide_play(rnd, seat)
        full = MCBot._candidates(self, rnd, seat)
        if len(full) <= 1:
            return super().decide_play(rnd, seat)
        ranking = self._oracle_prior_ranking(rnd, seat, full)
        if ranking is None:
            return super().decide_play(rnd, seat)
        means, order, info = ranking
        keep = min(int(self.PRIOR_KEEP_TOP), len(full))
        if self.PRIOR_ANCHOR:
            kept = order[:keep]
        else:
            kept = [0] + [i for i in order if i != 0][:keep - 1]
        pruned = [list(full[i]) for i in kept]
        base_n = self.N_DETERMINIZATIONS
        scaled = base_n
        if self.PRIOR_EQUAL_WORK:
            scaled = max(base_n, round(base_n * len(full) / len(pruned)))
        info.update({
            "kept_indices": list(kept),
            "incumbent_replaced": bool(kept[0] != 0),
            "base_n_determinizations": base_n,
            "n_determinizations": scaled,
        })
        self.oracle_prior_decisions += 1
        self.oracle_prior_candidates_seen += len(full)
        self.oracle_prior_candidates_kept += len(pruned)
        self.oracle_prior_incumbent_replaced += int(kept[0] != 0)
        self._oracle_pruned = pruned
        self.N_DETERMINIZATIONS = scaled
        try:
            played = super().decide_play(rnd, seat)
        finally:
            self._oracle_pruned = None
            self.N_DETERMINIZATIONS = base_n
        self.last_oracle_prior = info
        if self.last_decision_record is not None:
            self.last_decision_record["oracle_prior"] = info
        return played

    def _oracle_prior_ranking(self, rnd, seat, full):
        n = int(self.PRIOR_WORLDS)
        means, order, info, delta, secs = _shared_world_ranking(
            self, rnd, seat, full, worlds=n, stream="oracle-prior")
        self.oracle_prior_secs += secs
        self.oracle_prior_sample_attempts += delta["sample_attempts"]
        self.oracle_prior_accepted_worlds += delta["accepted_worlds"]
        self.oracle_prior_failed_worlds += delta["failed_worlds"]
        self.oracle_prior_rejected_worlds += delta["rejected_worlds"]
        used = info["worlds"]
        self.oracle_prior_worlds += used
        self.oracle_prior_rollouts += used * len(full)
        if used < n:
            self.oracle_prior_short += 1
        if used == 0:
            self.oracle_prior_zero_world += 1
            return None
        return means, order, info


def _shared_world_ranking(bot, rnd, seat, full, *, worlds: int, stream: str):
    """Rank ``full`` by paired means on ``worlds`` fresh shared worlds.

    The ``highn_build.py`` reference method, shared by the prior arm and both
    stages of the wide arm: every candidate is scored on the SAME worlds,
    drawn from the production sampler on the named child stream, with the
    PLAIN production continuation (``MCBot._rollout`` called directly, so the
    value arm's deeper leaf and the exact solver are bypassed).  ``bot.rng``
    is swapped for the child stream and restored, so the production
    selection/report streams neither advance nor change.

    Returns ``(means, order, info, sampler_delta, secs)``; ``means`` and
    ``order`` are None when no world could be sampled.
    """
    n = int(worlds)
    if n <= 0:
        raise OracleScreenError(f"{stream}: the world count must be positive")
    started = time.perf_counter()
    seed = _child_seed(bot.rng.getstate(), stream)
    mem = Memory(rnd, seat, own_kitty=getattr(bot, "BANKER_KITTY", True))
    i_attack = rnd.is_attacker(seat)
    totals = [0.0] * len(full)
    used = attempts = 0
    cap = n * bot.SAMPLE_ATTEMPT_FACTOR
    before = bot._sampler_snapshot()
    original_rng = bot.rng
    exact_flag = bot.EXACT_ENDGAME
    bot.rng = random.Random(seed)
    bot.EXACT_ENDGAME = False
    try:
        while used < n and attempts < cap:
            attempts += 1
            sampled = bot._sample_hands(rnd, seat, mem)
            if sampled is None:
                continue
            hands, buried = sampled
            for i, cand in enumerate(full):
                v = bot._score(MCBot._rollout(
                    bot, rnd, seat, hands, buried, list(cand)))
                totals[i] += v if i_attack else -v
            used += 1
    finally:
        bot.rng = original_rng
        bot.EXACT_ENDGAME = exact_flag
    secs = time.perf_counter() - started
    delta = bot._sampler_delta(before)
    info = {
        "full_ballot": [list(c) for c in full],
        "means": None,
        "order": None,
        "worlds": used,
        "worlds_requested": n,
        "attempts": attempts,
        "seed": seed,
        "stream": stream,
    }
    if used == 0:
        return None, None, info, delta, secs
    means = [t / used for t in totals]
    order = sorted(range(len(full)), key=lambda i: (-means[i], i))
    info["means"] = list(means)
    info["order"] = list(order)
    return means, order, info, delta, secs


# ------------------------------------------------------------------- wide arm

class OracleWideMixin:
    """Replace the production ballot with the best of the exhaustive legal set.

    ``WIDE_KEEP_TOP`` is the number of ballot entries the production search
    receives; ``0`` disables the arm (neutral knob).  A contested decision
    (the same ones the prior arm treats: not a locked tractor lead, more than
    one production candidate) runs:

    1. ``L = enumerate_legal(rnd, seat, cap=WIDE_CAP, must_include=ballot)``
       where ``ballot`` is the production ballot, whose candidate 0 is the
       incumbent.  Every production action is in ``L`` (a capped listing
       appends them); on-ballot actions keep production's card order.
    2. Stage 1 scores every action in ``L`` on ``WIDE_SCREEN_WORLDS`` shared
       worlds from the ``oracle-wide`` child stream and keeps the incumbent
       plus the ``WIDE_KEEP_STAGE1 - 1`` best others, in rank order.
    3. Stage 2 ranks the survivors on ``PRIOR_WORLDS`` worlds from the
       ``oracle-prior`` child stream (the prior arm's own evaluation, applied
       to the wider list) and keeps ``WIDE_KEEP_TOP``: the incumbent at index
       0 plus the best-ranked others, or with ``PRIOR_ANCHOR`` the top
       ``WIDE_KEEP_TOP`` in rank order.
    4. That ballot goes to ``super().decide_play`` with ``N_DETERMINIZATIONS``
       unchanged (``wide_fixed_n``); the report fold is untouched.

    The incumbent leads every list so ties break in its favour, as in the
    prior arm.  Neither stage advances ``self.rng``, so the report seed the
    production search derives from the pre-decision state is production's.
    """

    WIDE_CAP = 256
    WIDE_SCREEN_WORLDS = 24
    WIDE_KEEP_STAGE1 = 16
    WIDE_KEEP_TOP = 0
    #: Stage 2 reuses the prior's world count and anchor rule.
    PRIOR_WORLDS = 240
    PRIOR_ANCHOR = False

    def __init__(self, seed: int | None = None):
        super().__init__(seed)
        self._oracle_wide_ballot = None
        self.last_oracle_wide = None
        self.oracle_wide_decisions = 0
        self.oracle_wide_legal_seen = 0
        self.oracle_wide_capped = 0
        self.oracle_wide_stage1_rollouts = 0
        self.oracle_wide_stage2_rollouts = 0
        self.oracle_wide_worlds = 0
        self.oracle_wide_candidates_kept = 0
        self.oracle_wide_offballot_kept = 0
        self.oracle_wide_offballot_chosen = 0
        self.oracle_wide_incumbent_replaced = 0
        self.oracle_wide_short = 0
        self.oracle_wide_zero_world = 0
        self.oracle_wide_sample_attempts = 0
        self.oracle_wide_accepted_worlds = 0
        self.oracle_wide_failed_worlds = 0
        self.oracle_wide_rejected_worlds = 0
        # Enumeration plus both stages; production's search_secs starts after.
        self.oracle_wide_secs = 0.0

    def _candidates(self, rnd, seat):
        if self._oracle_wide_ballot is not None:
            return self._oracle_wide_ballot
        return super()._candidates(rnd, seat)

    def decide_play(self, rnd, seat):
        self.last_oracle_wide = None
        if self.WIDE_KEEP_TOP <= 0:
            return super().decide_play(rnd, seat)
        if self.TRACTOR_LOCK and not rnd.trick.plays:
            pick = self.canonical_lead(rnd, seat)
            dec = decompose(pick, rnd.ordering)
            if len(dec.components) == 1 and dec.components[0].pair_len >= 2:
                return super().decide_play(rnd, seat)
        full = MCBot._candidates(self, rnd, seat)
        if len(full) <= 1:
            return super().decide_play(rnd, seat)
        started = time.perf_counter()
        legal = enumerate_legal(rnd, seat, cap=int(self.WIDE_CAP),
                                must_include=full)
        by_key = {tuple(sorted(c)): list(c) for c in full}
        incumbent_key = tuple(sorted(full[0]))
        stage1 = [list(full[0])]
        on_ballot = [True]
        for action in legal.actions:
            key = tuple(sorted(action))
            if key == incumbent_key:
                continue
            prod = by_key.get(key)
            stage1.append(list(action) if prod is None else prod)
            on_ballot.append(prod is not None)
        self.oracle_wide_legal_seen += len(legal.actions)
        self.oracle_wide_capped += int(not legal.complete)
        n1 = int(self.WIDE_SCREEN_WORLDS)
        _, order1, info1, delta1, _ = _shared_world_ranking(
            self, rnd, seat, stage1, worlds=n1, stream="oracle-wide")
        self._oracle_wide_charge(delta1, info1["worlds"], n1, len(stage1),
                                 stage=1)
        if order1 is None:
            self.oracle_wide_zero_world += 1
            self.oracle_wide_secs += time.perf_counter() - started
            return super().decide_play(rnd, seat)
        keep1 = min(int(self.WIDE_KEEP_STAGE1), len(stage1))
        kept1 = [0] + [i for i in order1 if i != 0][:keep1 - 1]
        stage2 = [stage1[i] for i in kept1]
        on_ballot2 = [on_ballot[i] for i in kept1]
        n2 = int(self.PRIOR_WORLDS)
        _, order2, info2, delta2, _ = _shared_world_ranking(
            self, rnd, seat, stage2, worlds=n2, stream="oracle-prior")
        self._oracle_wide_charge(delta2, info2["worlds"], n2, len(stage2),
                                 stage=2)
        if order2 is None:
            self.oracle_wide_zero_world += 1
            self.oracle_wide_secs += time.perf_counter() - started
            return super().decide_play(rnd, seat)
        keep = min(int(self.WIDE_KEEP_TOP), len(stage2))
        if self.PRIOR_ANCHOR:
            kept = order2[:keep]
        else:
            kept = [0] + [i for i in order2 if i != 0][:keep - 1]
        ballot = [list(stage2[i]) for i in kept]
        offballot_kept = sum(not on_ballot2[i] for i in kept)
        self.oracle_wide_secs += time.perf_counter() - started
        info = {
            "production_ballot": [list(c) for c in full],
            "legal_kind": legal.kind,
            "legal_count": legal.count,
            "legal_listed": len(legal.actions),
            "legal_complete": legal.complete,
            "cap": int(self.WIDE_CAP),
            "stage1": info1,
            "stage1_on_ballot": list(on_ballot),
            "stage1_kept": list(kept1),
            "stage2": info2,
            "kept_indices": list(kept),
            "ballot": [list(c) for c in ballot],
            "ballot_on_production": [on_ballot2[i] for i in kept],
            "offballot_kept": offballot_kept,
            "incumbent_replaced": bool(kept[0] != 0),
            "n_determinizations": self.N_DETERMINIZATIONS,
            "wide_fixed_n": True,
        }
        self.oracle_wide_decisions += 1
        self.oracle_wide_candidates_kept += len(ballot)
        self.oracle_wide_offballot_kept += offballot_kept
        self.oracle_wide_incumbent_replaced += int(kept[0] != 0)
        self._oracle_wide_ballot = ballot
        try:
            played = super().decide_play(rnd, seat)
        finally:
            self._oracle_wide_ballot = None
        chosen_off = tuple(sorted(played)) not in by_key
        self.oracle_wide_offballot_chosen += int(chosen_off)
        info["played"] = list(played)
        info["offballot_chosen"] = chosen_off
        self.last_oracle_wide = info
        if self.last_decision_record is not None:
            self.last_decision_record["oracle_wide"] = info
        return played

    def _oracle_wide_charge(self, delta, used, requested, width, *, stage):
        self.oracle_wide_sample_attempts += delta["sample_attempts"]
        self.oracle_wide_accepted_worlds += delta["accepted_worlds"]
        self.oracle_wide_failed_worlds += delta["failed_worlds"]
        self.oracle_wide_rejected_worlds += delta["rejected_worlds"]
        self.oracle_wide_worlds += used
        if stage == 1:
            self.oracle_wide_stage1_rollouts += used * width
        else:
            self.oracle_wide_stage2_rollouts += used * width
        if used < requested:
            self.oracle_wide_short += 1


ORACLE_COUNTERS = (
    "oracle_leaves", "oracle_continuation_rollouts",
    "oracle_lookahead_decisions", "oracle_lookahead_candidates",
    "oracle_inline_plies", "oracle_exact_budget_fallbacks",
    "oracle_prior_decisions", "oracle_prior_worlds", "oracle_prior_rollouts",
    "oracle_prior_short", "oracle_prior_zero_world",
    "oracle_prior_candidates_seen", "oracle_prior_candidates_kept",
    "oracle_prior_incumbent_replaced", "oracle_prior_sample_attempts",
    "oracle_prior_accepted_worlds", "oracle_prior_failed_worlds",
    "oracle_prior_rejected_worlds",
    "oracle_wide_decisions", "oracle_wide_legal_seen", "oracle_wide_capped",
    "oracle_wide_stage1_rollouts", "oracle_wide_stage2_rollouts",
    "oracle_wide_worlds", "oracle_wide_candidates_kept",
    "oracle_wide_offballot_kept", "oracle_wide_offballot_chosen",
    "oracle_wide_incumbent_replaced", "oracle_wide_short",
    "oracle_wide_zero_world", "oracle_wide_sample_attempts",
    "oracle_wide_accepted_worlds", "oracle_wide_failed_worlds",
    "oracle_wide_rejected_worlds",
)


# --------------------------------------------------------------- construction

@lru_cache(maxsize=None)
def _oracle_class(arm: str, base_cls: type) -> type:
    mixins: tuple[type, ...] = ()
    if arm in VALUE_ARMS:
        mixins += (OracleValueMixin,)
    if arm in PRIOR_ARMS:
        mixins += (OraclePriorMixin,)
    if arm in WIDE_ARMS:
        mixins += (OracleWideMixin,)
    name = f"Oracle_{arm.replace('-', '_')}_{base_cls.__name__}"
    return type(name, mixins + (base_cls,), {})


def base_policy_class(base_policy: str) -> type:
    factory = REGISTRY.get(base_policy)
    if factory is None:
        raise OracleScreenError(f"unknown base policy {base_policy!r}")
    if not (inspect.isclass(factory) and issubclass(factory, MCBot)):
        raise OracleScreenError(
            f"base policy {base_policy!r} is not a registered MCBot class; "
            "the oracle arms subclass the production class itself")
    return factory


def knob_defaults() -> dict:
    return {
        "leaf_multiplier": 8,
        "exact_endgame_cards": 0,
        "exact_endgame_nodes": 250_000,
        "prior_worlds": 240,
        "prior_keep_top": 3,
        "prior_equal_work": True,
        "prior_anchor": False,
        "wide_cap": 256,
        "wide_screen_worlds": 24,
        "wide_keep_stage1": 16,
        "wide_keep_top": 8,
        # A stamp, not a switch: the wide ballot always meets production's N.
        "wide_fixed_n": True,
    }


def make_oracle_bot(base_policy: str, arm: str, *, seed: int | None,
                    knobs: dict | None = None):
    """Construct the arm's bot: the production class with oracle mixins."""
    if arm not in ORACLE_ARMS:
        raise OracleScreenError(f"{arm!r} is not an oracle arm")
    k = dict(knob_defaults())
    k.update(knobs or {})
    base_cls = base_policy_class(base_policy)
    bot = _oracle_class(arm, base_cls)(seed)
    if arm in VALUE_ARMS:
        if int(k["leaf_multiplier"]) < 1:
            raise OracleScreenError("leaf_multiplier must be >= 1")
        bot.LEAF_MULTIPLIER = int(k["leaf_multiplier"])
        cards = int(k["exact_endgame_cards"])
        if cards > 0:
            bot.EXACT_ENDGAME = True
            bot.EXACT_ENDGAME_MAX_CARDS = cards
            bot.EXACT_ENDGAME_MAX_NODES = int(k["exact_endgame_nodes"])
    if arm in PRIOR_ARMS:
        bot.PRIOR_WORLDS = int(k["prior_worlds"])
        bot.PRIOR_KEEP_TOP = int(k["prior_keep_top"])
        bot.PRIOR_EQUAL_WORK = bool(k["prior_equal_work"])
        bot.PRIOR_ANCHOR = bool(k["prior_anchor"])
    if arm in WIDE_ARMS:
        for name in ("wide_cap", "wide_screen_worlds", "wide_keep_stage1"):
            if int(k[name]) < 1:
                raise OracleScreenError(f"{name} must be >= 1")
        if int(k["wide_keep_top"]) < 0:
            raise OracleScreenError("wide_keep_top must be >= 0 (0 = no oracle)")
        if not bool(k["wide_fixed_n"]):
            raise OracleScreenError(
                "the wide arm hands its ballot to production at N unchanged; "
                "wide_fixed_n cannot be switched off")
        bot.WIDE_CAP = int(k["wide_cap"])
        bot.WIDE_SCREEN_WORLDS = int(k["wide_screen_worlds"])
        bot.WIDE_KEEP_STAGE1 = int(k["wide_keep_stage1"])
        bot.WIDE_KEEP_TOP = int(k["wide_keep_top"])
        bot.PRIOR_WORLDS = int(k["prior_worlds"])
        bot.PRIOR_ANCHOR = bool(k["prior_anchor"])
    bot.policy_name = f"{base_policy}+oracle-{arm}"
    return bot


def make_side_bot(config: dict, side: str, seed: int):
    """One bot for one seat: ``side`` is ``arm`` or ``baseline``."""
    base = config["base_policy"]
    arm = config["arm"]
    if side == "baseline" or arm == "none":
        bot = make_bot(base, seed=seed)
    elif arm == "null":
        bot = make_bot(base, seed=seed + NULL_SEED_OFFSET)
        bot.policy_name = f"{base}+null"
    else:
        bot = make_oracle_bot(base, arm, seed=seed, knobs=config["knobs"])
    work = config.get("work") or {}
    if work.get("select_worlds") is not None:
        bot.N_DETERMINIZATIONS = int(work["select_worlds"])
    if work.get("report_worlds") is not None:
        bot.REPORT_FOLD_WORLDS = int(work["report_worlds"])
    return bot


def work_counters(bots) -> dict:
    """Production counters (minus wall time) plus the oracle's own."""
    out = production_counters(bots)
    out.pop("search_secs", None)
    for name in ORACLE_COUNTERS:
        out[name] = sum(int(getattr(b, name, 0)) for b in bots)
    # Plain continuations actually played: production leaves that went through
    # the deep path are replaced by the rollouts they spent.
    out["continuation_rollouts"] = (out["rollouts"] - out["oracle_leaves"]
                                    + out["oracle_continuation_rollouts"])
    # Everything the side actually played: production-stage continuations
    # (deepened or not) plus the oracle prior's ranking rollouts and the wide
    # arm's two screening stages.
    out["total_rollouts"] = (out["continuation_rollouts"]
                             + out["oracle_prior_rollouts"]
                             + out["oracle_wide_stage1_rollouts"]
                             + out["oracle_wide_stage2_rollouts"])
    # The production sampler counters include the oracles' own draws; these
    # are the production stages' share alone.
    out["search_sample_attempts"] = (out["sample_attempts"]
                                     - out["oracle_prior_sample_attempts"]
                                     - out["oracle_wide_sample_attempts"])
    out["search_worlds"] = (out["accepted_worlds"]
                            - out["oracle_prior_accepted_worlds"]
                            - out["oracle_wide_accepted_worlds"])
    return out


# ------------------------------------------------------------------- rounds

def build_config(*, arm: str, base_policy: str = DEFAULT_BASE_POLICY,
                 knobs: dict | None = None, select_worlds: int | None = None,
                 report_worlds: int | None = None) -> dict:
    if arm not in ARMS:
        raise OracleScreenError(f"arm must be one of {ARMS}, got {arm!r}")
    base_cls = base_policy_class(base_policy)
    k = dict(knob_defaults())
    k.update(knobs or {})
    registered = {
        "n_determinizations": int(base_cls.N_DETERMINIZATIONS),
        "report_fold_worlds": int(base_cls.REPORT_FOLD_WORLDS),
        "report_rule": str(base_cls.REPORT_RULE),
    }
    effective = dict(registered)
    if select_worlds is not None:
        if select_worlds < 1:
            raise OracleScreenError("select_worlds must be >= 1")
        effective["n_determinizations"] = int(select_worlds)
    if report_worlds is not None:
        if report_worlds < 0:
            raise OracleScreenError("report_worlds must be >= 0")
        effective["report_fold_worlds"] = int(report_worlds)
    return {
        "arm": arm,
        "base_policy": base_policy,
        "base_class": base_cls.__name__,
        "knobs": k,
        "work": {
            "select_worlds": select_worlds,
            "report_worlds": report_worlds,
            "registered": registered,
            "effective": effective,
            "production": effective == registered,
        },
    }


def _history_digest(history) -> str:
    payload = json.dumps([[seat, list(cards)] for seat, cards in history])
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def play_screen_round(config: dict, cluster: int, seed: int, mirror: int
                      ) -> tuple[dict, dict]:
    """One round: arm vs baseline on deal ``seed``; ``mirror`` swaps teams.

    Seeds follow ``shengji.evaluation.run_arm``: the arm under test takes
    ``seed``/``seed+500_000`` and the opponent ``seed+1_000_000``/
    ``seed+1_500_000``; mirror 0 seats the arm at 0 and 2 (team 0).
    """
    a1 = make_side_bot(config, "arm", seed)
    a2 = make_side_bot(config, "arm", seed + 500_000)
    b1 = make_side_bot(config, "baseline", seed + 1_000_000)
    b2 = make_side_bot(config, "baseline", seed + 1_500_000)
    pol = [a1, b1, a2, b2] if mirror == 0 else [b1, a1, b2, a2]
    arm_team = 0 if mirror == 0 else 1
    started = time.perf_counter()
    log = play_round(Game(random.Random(seed)), pol, record=True)
    wall = time.perf_counter() - started
    arm_won = int(log.winner_team == arm_team)
    level = max(1, int(log.level_change))
    arm_utility = level if arm_won else -level
    banker_team = log.banker % 2
    record = {
        "schema": ROUND_SCHEMA,
        "cluster": cluster,
        "seed": seed,
        "mirror": mirror,
        "arm": config["arm"],
        "arm_team": arm_team,
        "arm_seats": [0, 2] if mirror == 0 else [1, 3],
        "banker": log.banker,
        "trump_rank": log.trump_rank,
        "arm_role": "banker" if banker_team == arm_team else "attacker",
        "attacker_points": int(log.attacker_points),
        "winner_team": int(log.winner_team),
        "level_change": int(log.level_change),
        "arm_won": arm_won,
        "arm_utility": arm_utility,
        "baseline_utility": -arm_utility,
        "plays": len(log.history),
        "history_sha256_16": _history_digest(log.history),
        "work": {"arm": work_counters([a1, a2]),
                 "baseline": work_counters([b1, b2])},
    }
    timing = {
        "cluster": cluster, "seed": seed, "mirror": mirror,
        "wall_secs": round(wall, 4),
        "arm_search_secs": round(a1.search_secs + a2.search_secs, 4),
        "arm_prior_secs": round(
            sum(getattr(b, "oracle_prior_secs", 0.0) for b in (a1, a2)), 4),
        "arm_wide_secs": round(
            sum(getattr(b, "oracle_wide_secs", 0.0) for b in (a1, a2)), 4),
        "baseline_search_secs": round(b1.search_secs + b2.search_secs, 4),
    }
    return record, timing


def _round_task(args):
    config, cluster, seed, mirror = args
    return play_screen_round(config, cluster, seed, mirror)


def run_rounds(config: dict, *, rounds: int, seed0: int, workers: int = 1,
               progress=None) -> tuple[list[dict], list[dict]]:
    """Play ``rounds`` rounds (``rounds/2`` clusters x both mirrors).

    Output order is fixed by (cluster, mirror) regardless of worker
    scheduling, so a run with any worker count reproduces byte for byte.
    """
    if rounds < 2 or rounds % 2:
        raise OracleScreenError(
            "rounds must be an even number >= 2: every deal cluster plays "
            "both mirrors")
    if workers < 1:
        raise OracleScreenError("workers must be >= 1")
    tasks = [(config, c, seed0 + c, mirror)
             for c in range(rounds // 2) for mirror in (0, 1)]
    results: dict[tuple[int, int], tuple[dict, dict]] = {}
    done = 0
    if workers == 1:
        for task in tasks:
            results[(task[1], task[3])] = _round_task(task)
            done += 1
            if progress:
                progress(done, len(tasks), results[(task[1], task[3])][0])
    else:
        import multiprocessing
        ctx = multiprocessing.get_context("spawn")
        with ProcessPoolExecutor(max_workers=min(workers, len(tasks)),
                                 mp_context=ctx) as pool:
            futures = {pool.submit(_round_task, task): (task[1], task[3])
                       for task in tasks}
            for future, key in futures.items():
                results[key] = future.result()
                done += 1
                if progress:
                    progress(done, len(tasks), results[key][0])
    ordered = [results[(c, m)] for c in range(rounds // 2) for m in (0, 1)]
    return [r for r, _ in ordered], [t for _, t in ordered]


# ---------------------------------------------------------------- statistics

def cluster_bootstrap(cluster_values: list[float], *, replicates: int,
                      seed: int) -> dict:
    """Percentile bootstrap of a mean over clusters resampled with replacement."""
    n = len(cluster_values)
    if n == 0:
        return {"mean": None, "ci95": [None, None], "clusters": 0,
                "replicates": replicates, "seed": seed}
    mean = sum(cluster_values) / n
    if n < 2:
        return {"mean": mean, "ci95": [None, None], "clusters": n,
                "replicates": replicates, "seed": seed}
    import numpy as np
    values = np.asarray(cluster_values, dtype=float)
    rng = np.random.default_rng(seed)
    means = np.empty(replicates, dtype=float)
    chunk = 2000
    for start in range(0, replicates, chunk):
        stop = min(replicates, start + chunk)
        idx = rng.integers(0, n, size=(stop - start, n))
        means[start:stop] = values[idx].mean(axis=1)
    lo, hi = np.percentile(means, [2.5, 97.5])
    return {"mean": mean, "ci95": [float(lo), float(hi)], "clusters": n,
            "replicates": replicates, "seed": seed}


def _mean(values):
    return sum(values) / len(values) if values else None


def summarize(records: list[dict], config: dict, *, seed0: int,
              replicates: int = DEFAULT_BOOTSTRAP_REPLICATES,
              bootstrap_seed: int = DEFAULT_BOOTSTRAP_SEED) -> dict:
    by_cluster: dict[int, list[dict]] = {}
    for r in records:
        by_cluster.setdefault(r["cluster"], []).append(r)
    clusters = sorted(by_cluster)
    per_round_mean = [_mean([r["arm_utility"] for r in by_cluster[c]])
                      for c in clusters]
    per_cluster_sum = [sum(r["arm_utility"] for r in by_cluster[c])
                       for c in clusters]
    per_cluster_win = [_mean([r["arm_won"] for r in by_cluster[c]])
                       for c in clusters]

    def split(role):
        rows = [r for r in records if r["arm_role"] == role]
        return {
            "rounds": len(rows),
            "mean_arm_utility": _mean([r["arm_utility"] for r in rows]),
            "arm_win_rate": _mean([r["arm_won"] for r in rows]),
            "mean_attacker_points": _mean(
                [r["attacker_points"] for r in rows]),
        }

    totals = {side: {} for side in ("arm", "baseline")}
    for side in totals:
        keys = set()
        for r in records:
            keys.update(r["work"][side])
        for key in sorted(keys):
            totals[side][key] = sum(r["work"][side].get(key, 0)
                                    for r in records)
    def ratio_of(key):
        if not totals["baseline"].get(key):
            return None
        return totals["arm"][key] / totals["baseline"][key]

    ratio = ratio_of("continuation_rollouts")
    total_ratio = ratio_of("total_rollouts")

    problems = []
    for side in ("arm", "baseline"):
        t = totals[side]
        if t.get("short_searches"):
            problems.append(f"{side}: {t['short_searches']} search decisions "
                            "failed to consume their registered dose")
        if t.get("zero_world"):
            problems.append(f"{side}: {t['zero_world']} decisions searched "
                            "zero worlds")
        unreconciled = abs(t.get("sample_attempts", 0)
                           - t.get("accepted_worlds", 0)
                           - t.get("failed_worlds", 0))
        if unreconciled:
            problems.append(f"{side}: sampler accounting unreconciled by "
                            f"{unreconciled}")
        if t.get("exact_endgame_refusals") or t.get("oracle_exact_budget_fallbacks"):
            problems.append(
                f"{side}: exact solver refusals={t.get('exact_endgame_refusals', 0)} "
                f"budget_fallbacks={t.get('oracle_exact_budget_fallbacks', 0)}")
        if t.get("oracle_prior_short") or t.get("oracle_prior_zero_world"):
            problems.append(
                f"{side}: oracle prior short={t.get('oracle_prior_short', 0)} "
                f"zero_world={t.get('oracle_prior_zero_world', 0)}")
        if t.get("oracle_wide_short") or t.get("oracle_wide_zero_world"):
            problems.append(
                f"{side}: oracle wide short={t.get('oracle_wide_short', 0)} "
                f"zero_world={t.get('oracle_wide_zero_world', 0)}")
    # Coverage diagnostics of the wide arm: how much of the kept ballot, and
    # how many final actions, came from outside the production ballot.
    wide = totals["arm"]
    kept = wide.get("oracle_wide_candidates_kept", 0)
    wide_decisions = wide.get("oracle_wide_decisions", 0)
    offballot_kept_rate = (wide["oracle_wide_offballot_kept"] / kept
                           if kept else None)
    offballot_chosen_rate = (wide["oracle_wide_offballot_chosen"]
                             / wide_decisions if wide_decisions else None)
    if not os.environ.get("SHENGJI_REQUIRE_VOIDS"):
        problems.append("SHENGJI_REQUIRE_VOIDS unset: sampled worlds may "
                        "violate observed voids")
    if not config["work"]["production"]:
        problems.append("work override in effect: this is NOT production work")

    return {
        "schema": SUMMARY_SCHEMA,
        "claim": ("ceiling screen: non-promotable; arms may exceed production "
                  "compute and are not candidate policies"),
        "arm": config["arm"],
        "arm_description": arm_description(config),
        "base_policy": config["base_policy"],
        "base_class": config["base_class"],
        "knobs": config["knobs"],
        "work": config["work"],
        "seed0": seed0,
        "rounds": len(records),
        "clusters": len(clusters),
        "metric": ("arm signed level utility per round; positive means the "
                   "arm's team gained levels against the baseline's team on "
                   "the same mirrored deal; cluster = one deal (both mirrors)"),
        "arm_signed_level_utility": {
            "per_round": cluster_bootstrap(
                per_round_mean, replicates=replicates, seed=bootstrap_seed),
            "per_cluster_sum": cluster_bootstrap(
                per_cluster_sum, replicates=replicates,
                seed=bootstrap_seed + 1),
            "positive_clusters": sum(v > 0 for v in per_cluster_sum),
            "zero_clusters": sum(v == 0 for v in per_cluster_sum),
            "negative_clusters": sum(v < 0 for v in per_cluster_sum),
        },
        "arm_win_rate": cluster_bootstrap(
            per_cluster_win, replicates=replicates, seed=bootstrap_seed + 2),
        "role_splits": {"arm_banker_team": split("banker"),
                        "arm_attacker_team": split("attacker")},
        "work_totals": totals,
        "arm_over_baseline_continuation_rollouts": ratio,
        "arm_over_baseline_total_rollouts": total_ratio,
        "oracle_wide_offballot_kept_rate": offballot_kept_rate,
        "oracle_wide_offballot_chosen_rate": offballot_chosen_rate,
        "problems": problems,
    }


def arm_description(config: dict) -> str:
    arm = config["arm"]
    k = config["knobs"]
    base = config["base_policy"]
    if arm == "none":
        return f"{base} on both sides (identity control)"
    if arm == "null":
        return (f"{base} vs its champion-matched null "
                f"(seed offset {NULL_SEED_OFFSET})")
    parts = []
    if arm in VALUE_ARMS:
        parts.append(
            f"oracle value: {k['leaf_multiplier']} continuation rollouts per "
            "leaf spent on greedy one-ply rollout improvement"
            + (f", exact endgame at <= {k['exact_endgame_cards']} cards "
               f"({k['exact_endgame_nodes']} nodes)"
               if int(k["exact_endgame_cards"]) > 0 else ", no exact endgame"))
    if arm in PRIOR_ARMS:
        parts.append(
            f"oracle prior: ballot ranked on {k['prior_worlds']} shared "
            f"worlds, keep top {k['prior_keep_top']}"
            + (" (anchor replaces incumbent)" if k["prior_anchor"]
               else " (incumbent kept)")
            + (", selection worlds scaled to equal work"
               if k["prior_equal_work"] else ", N unchanged"))
    if arm in WIDE_ARMS:
        parts.append(
            f"oracle wide: exhaustive legal set (cap {k['wide_cap']}) "
            f"screened on {k['wide_screen_worlds']} shared worlds, top "
            f"{k['wide_keep_stage1']} ranked on {k['prior_worlds']} shared "
            f"worlds, keep top {k['wide_keep_top']}"
            + (" (anchor replaces incumbent)" if k["prior_anchor"]
               else " (incumbent kept)")
            + ", N unchanged")
    return f"{base} + " + "; ".join(parts)


# ------------------------------------------------------------------ identity

def _digest(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _git(args, cwd) -> str | None:
    try:
        return subprocess.run(["git", *args], cwd=cwd, check=True,
                              capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def fast_engine_active() -> bool:
    from ..engine import combos, fast
    return bool(fast.HAVE_FAST and combos.decompose is fast.decompose)


def identity(config: dict, script_path: str | None = None) -> dict:
    from ..engine.ballot import mc_ballot
    repo = SERVER.parent
    base = make_bot(config["base_policy"], seed=0)
    ballots = {"baseline": str(mc_ballot(base))}
    if config["arm"] in ORACLE_ARMS:
        arm_bot = make_oracle_bot(config["base_policy"], config["arm"],
                                  seed=0, knobs=config["knobs"])
        ballots["arm"] = str(mc_ballot(arm_bot))
        ballots["arm_class"] = type(arm_bot).__name__
    return {
        "git_sha": _git(["rev-parse", "HEAD"], repo),
        "git_dirty": bool(_git(["status", "--porcelain",
                                "--untracked-files=no"], repo)),
        "screen_module_sha256_16": _digest(Path(__file__)),
        "script_sha256_16": _digest(Path(script_path)) if script_path else None,
        "mcbot_sha256_16": _digest(SERVER / "shengji" / "ai" / "mcbot.py"),
        "registry_sha256_16": _digest(SERVER / "shengji" / "ai" / "registry.py"),
        "evaluation_sha256_16": _digest(SERVER / "shengji" / "evaluation.py"),
        "fast_engine": fast_engine_active(),
        "require_voids": bool(os.environ.get("SHENGJI_REQUIRE_VOIDS")),
        "ballots": ballots,
    }


def runtime_receipt(*, workers: int, wall_secs: float, argv: list[str],
                    timings: list[dict]) -> dict:
    walls = [t["wall_secs"] for t in timings]
    return {
        "schema": RUNTIME_SCHEMA,
        "argv": list(argv),
        "host": platform.node(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "logical_cpus": os.cpu_count(),
        "workers": workers,
        "fast_engine": fast_engine_active(),
        "wall_secs": round(wall_secs, 3),
        "rounds": len(timings),
        "round_wall_secs_mean": round(_mean(walls), 3) if walls else None,
        "round_wall_secs_max": round(max(walls), 3) if walls else None,
        "arm_search_secs": round(sum(t["arm_search_secs"] for t in timings), 3),
        "arm_prior_secs": round(sum(t["arm_prior_secs"] for t in timings), 3),
        "arm_wide_secs": round(sum(t["arm_wide_secs"] for t in timings), 3),
        "baseline_search_secs": round(
            sum(t["baseline_search_secs"] for t in timings), 3),
        "started": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


# ------------------------------------------------------------------- driver

def write_outputs(out_dir: str | os.PathLike, *, records, timings, summary,
                  runtime) -> dict[str, str]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = {
        "rounds": out / "rounds.jsonl",
        "summary": out / "summary.json",
        "timing": out / "timing.jsonl",
        "runtime": out / "runtime.json",
    }
    for path in paths.values():
        if path.exists():
            raise OracleScreenError(
                f"{path} exists; a screen never mixes into an earlier run")
    with paths["rounds"].open("x", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, sort_keys=True) + "\n")
    with paths["timing"].open("x", encoding="utf-8") as fh:
        for row in timings:
            fh.write(json.dumps(row, sort_keys=True) + "\n")
    with paths["summary"].open("x", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2, sort_keys=True)
        fh.write("\n")
    with paths["runtime"].open("x", encoding="utf-8") as fh:
        json.dump(runtime, fh, indent=2, sort_keys=True)
        fh.write("\n")
    return {k: str(v) for k, v in paths.items()}


def run_screen(*, arm: str, rounds: int, seed0: int, out_dir, workers: int = 1,
               base_policy: str = DEFAULT_BASE_POLICY, knobs: dict | None = None,
               select_worlds: int | None = None, report_worlds: int | None = None,
               replicates: int = DEFAULT_BOOTSTRAP_REPLICATES,
               bootstrap_seed: int = DEFAULT_BOOTSTRAP_SEED,
               script_path: str | None = None, argv: list[str] | None = None,
               progress: bool = False) -> dict:
    config = build_config(arm=arm, base_policy=base_policy, knobs=knobs,
                          select_worlds=select_worlds,
                          report_worlds=report_worlds)
    ident = identity(config, script_path)
    started = time.perf_counter()

    def report(done, total, rec):
        print(f"  round {done}/{total}: cluster {rec['cluster']} mirror "
              f"{rec['mirror']} arm_utility {rec['arm_utility']:+d} "
              f"({rec['arm_role']})", flush=True)

    records, timings = run_rounds(config, rounds=rounds, seed0=seed0,
                                  workers=workers,
                                  progress=report if progress else None)
    summary = summarize(records, config, seed0=seed0, replicates=replicates,
                        bootstrap_seed=bootstrap_seed)
    summary["identity"] = ident
    runtime = runtime_receipt(workers=workers,
                              wall_secs=time.perf_counter() - started,
                              argv=argv or sys.argv, timings=timings)
    paths = write_outputs(out_dir, records=records, timings=timings,
                          summary=summary, runtime=runtime)
    summary["paths"] = paths
    return summary
