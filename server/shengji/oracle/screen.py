"""Expensive heuristic PROBES of the production search: the same search with
a much deeper leaf evaluation and/or an oracle-ranked ballot, on paired
mirrored deals.  These are NOT ceilings (see INTERPRETATION below).

THE QUESTION.  ``mc-s0-report-lcb`` is a two-stage determinized search: an
N=30 ballot/search nominates one challenger to the heuristic incumbent, then
the fixed pair is re-compared on R=300 fresh shared hidden worlds under a
one-sided paired LCB rule.  Every leaf of both stages is ONE deterministic
heuristic continuation of a fully determinized world.  Before a learned
value head or a learned ballot prior is built, this module asks what a much
more expensive stand-in for each buys inside the unchanged search:

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
    Wide-ballot coverage arm (issue #205 step 2).  The production BALLOT is
    replaced by the best candidates of a CAPPED deterministic prefix of the
    legal set unioned with the production ballot; everything else is
    production.  Per contested decision
    ``enumerate_legal(rnd, seat, cap=WIDE_CAP, must_include=ballot)`` lists
    the enumerator's first ``WIDE_CAP`` legal actions in its fixed order and
    appends every production action that prefix missed.  A legal set larger
    than the cap makes the listing INCOMPLETE: the arm then ranks a prefix,
    not the legal set, and supports no coverage claim beyond that prefix.
    Stage 1 scores every listed action on ``WIDE_SCREEN_WORLDS`` shared
    worlds and keeps the top ``WIDE_KEEP_STAGE1`` (the incumbent always
    survives); stage 2 ranks the survivors with the prior's
    ``PRIOR_WORLDS``-world machinery and keeps ``WIDE_KEEP_TOP`` (incumbent
    at index 0, or the oracle's favourite with ``PRIOR_ANCHOR``).  That
    ballot goes to the production search with ``N_DETERMINIZATIONS``
    UNCHANGED: a wider ballot simply costs more selection worlds, which the
    counters record (``wide_fixed_n``).

    Incompleteness is never silent.  Every capped decision is counted
    (``oracle_wide_capped``), the summary carries a ``wide_coverage`` block
    (decisions, complete, capped, capped_rate, legal_count_total,
    listed_total) plus a ``problems`` entry whenever ``capped_rate > 0``,
    and the arm description names the cap.  ``WIDE_REQUIRE_COMPLETE``
    (``--wide-require-complete``) fails closed instead: the first incomplete
    enumeration refuses its round, the run stops, the refusal is recorded in
    ``summary.problems`` (and ``summary.refused``) and the run exits
    non-zero.

``wide-value``
    ``wide`` stacked with ``value``, as ``both`` stacks ``prior`` with it.

``none`` / ``null``
    Controls: ``none`` plays the production policy on both sides with the
    arm's seeds (the identity witness for a neutral-knob arm); ``null`` plays
    the champion-matched null (same policy, RNG stream shifted by the registry
    offset) so the reviewer sees the noise floor on the same deals.

``knobs``
    Not an oracle: the production class itself with CANDIDATE-GENERATOR
    knobs overridden from the command line (``--knob NAME=VALUE``,
    repeatable), so the ballot switches ``RETAIN_ALL_LEAD_PAIRS``,
    ``V3_LEAD_SINGLES``, ``RISKY_THROWS``, ``TRUMP_BALLOT``,
    ``WIDE_LEAD_BALLOT`` (0/1/true/false) and the ballot caps
    ``LEAD_MAX_CANDIDATES``, ``FOLLOW_MAX_CANDIDATES``, ``MAX_CANDIDATES``,
    ``BURY_MAX_CANDIDATES`` (integers >= 1) can be screened at equal work on
    the same paired mirrored deals.  That whitelist (``KNOB_SPECS``) is the
    whole surface: every other class attribute (search work such as
    ``N_DETERMINIZATIONS`` or ``EXTRA_SELECTION_WORK``, recovery such as
    ``REQUIRE_EXACT_WORK``, sampling such as ``SAMPLE_ATTEMPT_FACTOR``, the
    exact-endgame solver, the report rule and its statistics, margins and
    allocation switches, the heuristic's own knobs) is refused BY NAME, and
    a bad or out-of-bounds value refuses too, all before any round runs.
    ``TRACTOR_LOCK`` is refused by name although it reads like a ballot
    switch: a locked tractor lead returns from ``decide_play`` before
    candidate construction, sampling, selection and the report fold, so
    switching it off turns zero search into a full search on those
    decisions (the amount of search, not the candidate list) while the
    search vector would still read equal.  The search is therefore
    untouched: an accepted knob changes only which actions the unchanged
    search compares, the complete work/report vector of both sides is
    stamped and compared in ``identity.search_vector``, and a wider ballot
    simply costs more selection worlds, which
    ``arm_over_baseline_total_rollouts`` records.  With no override the arm
    is the ``none`` control (its neutral witness).  The override set is
    stamped in ``knobs.overrides``, in the arm description and in
    ``identity.knob_overrides``.

``work``
    Compute control, not an oracle: the production class itself with
    ``N_DETERMINIZATIONS``/``REPORT_FOLD_WORLDS`` set to the absolute
    ``work_select_worlds``/``work_report_worlds`` on the ARM side only; the
    baseline stays registered production.  An oracle arm's gain at K times
    production's rollouts is only evidence for its mechanism if production
    given the same total rollouts does not gain as much; this arm measures
    that.  At the registered values it is the ``none`` identity control.
    Its ``identity.search_vector.equal`` is honestly False whenever the
    arm's N/R differ from the registered values: that difference IS the
    arm, and ``arm_over_baseline_total_rollouts`` records what it cost.

INTERPRETATION (Codex review of PR #203, 2026-09-04).  Neither arm is an
upper bound on what a learned component could buy.  The value arm is a
bounded greedy one-ply rollout-policy modification scored by the same
heuristic continuation: it is not exact and is not guaranteed to rank root
actions at least as well as production.  The prior arm is a finite-world
estimate followed by hard pruning: noise or the prune can discard the best
production-ballot action.  More compute here therefore does not create a
ceiling.  A POSITIVE result says this expensive variant helps (a lower
bound on the headroom); a WEAK or NULL result is NON-CLOSING for the learned
value/prior direction.  Closing that direction needs a real tractable
oracle (exact/minimax continuation on sealed late-game states with a
demonstrated dominance relation) or the learned component itself.  The
``oracle-ceiling-*`` schema identifiers are kept for continuity with the
completed runs; read "ceiling" in them as "probe".

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

ARMS = ("none", "null", "value", "prior", "both", "wide", "wide-value",
        "knobs", "work")
#: Which mixin each oracle arm carries.
VALUE_ARMS = ("value", "both", "wide-value")
PRIOR_ARMS = ("prior", "both")
WIDE_ARMS = ("wide", "wide-value")
ORACLE_ARMS = ("value", "prior", "both", "wide", "wide-value")
#: The production class with its own class knobs overridden; not an oracle.
KNOBS_ARM = "knobs"
#: The knobs arm accepts ONLY these candidate-generator knobs: ballot
#: switches (bool: 0/1/true/false) and ballot caps (int >= 1).  Everything
#: else a production class carries (search work such as N_DETERMINIZATIONS
#: or EXTRA_SELECTION_WORK, recovery such as REQUIRE_EXACT_WORK, sampling
#: such as SAMPLE_ATTEMPT_FACTOR, the exact-endgame solver, the report rule
#: and its statistics, margins, allocation switches, the heuristic's own
#: knobs) is refused BY NAME, so an accepted override can only change which
#: actions the unchanged search compares; identity.search_vector stamps the
#: rest for both sides.  A cap of 0 passes int() but hands the search an
#: empty ballot (mcbot crashes at candidates[0]), hence the bound.
#: TRACTOR_LOCK is NOT here although it reads like a ballot switch: a locked
#: tractor lead returns from decide_play before candidates, sampling,
#: selection and the report fold, so TRACTOR_LOCK=0 changes the amount of
#: search on those decisions, not the candidate list (KNOB_REFUSAL_REASONS).
KNOB_SPECS = {
    "RETAIN_ALL_LEAD_PAIRS": bool,
    "V3_LEAD_SINGLES": bool,
    "RISKY_THROWS": bool,
    "TRUMP_BALLOT": bool,
    "WIDE_LEAD_BALLOT": bool,
    "LEAD_MAX_CANDIDATES": int,
    "FOLLOW_MAX_CANDIDATES": int,
    "MAX_CANDIDATES": int,
    "BURY_MAX_CANDIDATES": int,
}
#: Names refused for a reason beyond "not a candidate-generator knob".
KNOB_REFUSAL_REASONS = {
    "TRACTOR_LOCK": (
        "a locked tractor lead returns from decide_play before candidate "
        "construction, sampling, selection and the report fold, so "
        "TRACTOR_LOCK changes the amount of search on those decisions, not "
        "the candidate list (zero search would become a full search while "
        "identity.search_vector still read equal)"),
}
#: The production class at an absolute N/R on the arm side; not an oracle.
WORK_ARM = "work"
#: The one-sided paired LCB report rule is registered for n >= 30 worlds.
WORK_MIN_REPORT_WORLDS = 30
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


class OracleRoundRefused(OracleScreenError):
    """A round refused its own measurement (a fail-closed knob fired inside a
    decision): the run stops, records the refusal and exits non-zero."""

    def __init__(self, cluster: int, seed: int, mirror: int, reason: str):
        # Positional args only, so the exception pickles across the worker
        # pool unchanged.
        super().__init__(cluster, seed, mirror, reason)
        self.cluster = cluster
        self.seed = seed
        self.mirror = mirror
        self.reason = reason
        #: Filled by ``run_screen`` once the refusal has been written out.
        self.paths: dict[str, str] | None = None

    def __str__(self) -> str:
        return (f"round refused (cluster {self.cluster}, seed {self.seed}, "
                f"mirror {self.mirror}): {self.reason}")

    def as_record(self) -> dict:
        return {"cluster": self.cluster, "seed": self.seed,
                "mirror": self.mirror, "reason": self.reason}


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
    """Replace the production ballot with the best of a capped legal prefix
    unioned with the production ballot.

    ``WIDE_KEEP_TOP`` is the number of ballot entries the production search
    receives; ``0`` disables the arm (neutral knob).  A contested decision
    (the same ones the prior arm treats: not a locked tractor lead, more than
    one production candidate) runs:

    1. ``L = enumerate_legal(rnd, seat, cap=WIDE_CAP, must_include=ballot)``
       where ``ballot`` is the production ballot, whose candidate 0 is the
       incumbent: the enumerator's first ``WIDE_CAP`` legal actions in its
       fixed order plus every production action that prefix missed, so every
       production action is in ``L``; on-ballot actions keep production's
       card order.  ``L`` is the legal set only when ``legal.complete``.  A
       capped listing is counted (``oracle_wide_capped``) and, with
       ``WIDE_REQUIRE_COMPLETE``, refuses the decision (``OracleScreenError``)
       before anything is ranked, which fails the round closed.
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

    The coverage counters (``legal_seen``, ``capped``, ``legal_count``,
    ``uncountable``) describe the decisions that received a wide ballot; a
    decision whose stage sampled zero worlds falls back to production and
    counts only as ``zero_world``.
    """

    WIDE_CAP = 256
    WIDE_SCREEN_WORLDS = 24
    WIDE_KEEP_STAGE1 = 16
    WIDE_KEEP_TOP = 0
    WIDE_REQUIRE_COMPLETE = False
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
        self.oracle_wide_legal_count = 0
        self.oracle_wide_uncountable = 0
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
        if self.WIDE_REQUIRE_COMPLETE and not legal.complete:
            self.oracle_wide_secs += time.perf_counter() - started
            raise OracleScreenError(
                f"wide: {legal.kind} enumeration incomplete at cap "
                f"{int(self.WIDE_CAP)} (legal count "
                f"{'uncountable' if legal.count is None else legal.count}, "
                f"listed {len(legal.actions)}); WIDE_REQUIRE_COMPLETE "
                "refuses to rank a capped prefix")
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
        self.oracle_wide_legal_seen += len(legal.actions)
        self.oracle_wide_capped += int(not legal.complete)
        if legal.count is None:
            self.oracle_wide_uncountable += 1
        else:
            self.oracle_wide_legal_count += int(legal.count)
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
    "oracle_wide_legal_count", "oracle_wide_uncountable",
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
        # Fail closed on a legal set larger than wide_cap; off, the capped
        # prefix is ranked and the incompleteness reported prominently.
        "wide_require_complete": False,
        # A stamp, not a switch: the wide ballot always meets production's N.
        "wide_fixed_n": True,
        # knobs arm: {CLASS_ATTRIBUTE: coerced value}, sorted by name.
        "overrides": {},
    }


# ------------------------------------------------------------------ knobs arm

def _coerce_knob(name: str, kind: type, raw):
    """Coerce ``raw`` (a command-line string or a native value) to the knob's
    kind and check its bounds; refuse anything that does not round-trip."""
    if kind is bool:
        if isinstance(raw, bool):
            return raw
        text = str(raw).strip().lower()
        if text in ("1", "true"):
            return True
        if text in ("0", "false"):
            return False
        raise OracleScreenError(
            f"knob {name}: {raw!r} is not a bool (use 0/1/true/false)")
    assert kind is int, kind
    if isinstance(raw, bool):
        raise OracleScreenError(
            f"knob {name}: expects an int >= 1, got {raw!r}")
    if isinstance(raw, int):
        value = raw
    else:
        try:
            value = int(str(raw).strip())
        except ValueError:
            raise OracleScreenError(
                f"knob {name}: {raw!r} is not an int") from None
    if value < 1:
        raise OracleScreenError(
            f"knob {name}: a ballot cap must be >= 1, got {value} (a cap of "
            "0 hands the search an empty ballot and crashes at candidates[0])")
    return value


def _knob_refusal(base_cls: type, name) -> str:
    accepted = ", ".join(KNOB_SPECS)
    if not isinstance(name, str) or not name.isidentifier():
        return f"knob {name!r}: not an attribute name; accepted: {accepted}"
    reason = KNOB_REFUSAL_REASONS.get(name)
    if reason is not None:
        return f"knob {name}: refused by name: {reason}; accepted: {accepted}"
    if hasattr(base_cls, name):
        return (f"knob {name}: {base_cls.__name__}.{name} is not a "
                "candidate-generator knob and is refused by name (search work, "
                "recovery, sampling, leaf valuation, report/statistical and "
                "exact-endgame controls stay production on both sides); "
                f"accepted: {accepted}")
    return (f"unknown knob {name}: not a class attribute of "
            f"{base_cls.__name__}; accepted: {accepted}")


def parse_knob_overrides(base_cls: type, specs) -> dict:
    """``NAME=VALUE`` strings (or a ``{NAME: value}`` mapping) -> a dict of
    class-attribute overrides, sorted by name.  Only the ``KNOB_SPECS``
    candidate-generator knobs are accepted, each coerced to its kind and
    bound-checked; every other name is refused by name, and a whitelisted
    name that the base class no longer carries with that kind refuses too."""
    if isinstance(specs, dict):
        items = list(specs.items())
    else:
        items = []
        for spec in specs or ():
            if not isinstance(spec, str) or "=" not in spec:
                raise OracleScreenError(f"knob {spec!r}: expected NAME=VALUE")
            name, _, value = spec.partition("=")
            items.append((name.strip(), value))
    out: dict = {}
    for name, raw in items:
        kind = KNOB_SPECS.get(name) if isinstance(name, str) else None
        if kind is None:
            raise OracleScreenError(_knob_refusal(base_cls, name))
        if name in out:
            raise OracleScreenError(f"knob {name}: given more than once")
        try:
            current = inspect.getattr_static(base_cls, name)
        except AttributeError:
            current = None
        if type(current) is not kind:
            raise OracleScreenError(
                f"knob {name}: {base_cls.__name__}.{name} is {current!r}, not "
                f"a {kind.__name__} class knob; KNOB_SPECS has drifted from "
                "the production class")
        out[name] = _coerce_knob(name, kind, raw)
    return dict(sorted(out.items()))


@lru_cache(maxsize=None)
def _knobs_class(base_cls: type, overrides: tuple) -> type:
    """The production class with class attributes overridden; one class per
    override set, so every bot of a screen shares its identity."""
    return type(f"Knobs_{base_cls.__name__}", (base_cls,), dict(overrides))


def make_knobs_bot(base_policy: str, overrides, *, seed: int | None):
    """Construct the knobs arm's bot: production, with ``overrides`` applied
    as class attributes of a subclass (validated and coerced again here, so a
    Python caller gets the same refusals as the command line)."""
    base_cls = base_policy_class(base_policy)
    parsed = parse_knob_overrides(base_cls, overrides or {})
    bot = _knobs_class(base_cls, tuple(parsed.items()))(seed)
    stamp = ",".join(f"{n}={v!r}" for n, v in parsed.items())
    bot.policy_name = f"{base_policy}+knobs" + (f"[{stamp}]" if stamp else "")
    return bot


def class_knob_names(cls: type) -> list[str]:
    """Names of every public UPPER_CASE scalar class attribute of ``cls``
    (bool, int, float, str or None), sorted: the class's whole knob surface,
    the heuristic's switches included."""
    names = []
    for name in dir(cls):
        if name.startswith("_") or not name.isupper():
            continue
        value = inspect.getattr_static(cls, name)
        if callable(value) or hasattr(value, "__get__"):
            continue
        if value is None or isinstance(value, (bool, int, float, str)):
            names.append(name)
    return sorted(names)


def search_vector(bot, base_cls: type) -> dict:
    """The complete work/report vector of ``bot``'s search: every class knob
    of the registered production class ``base_cls`` except the
    candidate-generator knobs (``KNOB_SPECS``), read from ``bot`` so that
    class-level (knobs arm) and instance-level (oracle arms) overrides both
    show.  Two bots with equal vectors draw, value, recover and judge their
    worlds identically; only the ballot may differ."""
    return {name: getattr(bot, name) for name in class_knob_names(base_cls)
            if name not in KNOB_SPECS}


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
        bot.WIDE_REQUIRE_COMPLETE = bool(k["wide_require_complete"])
        bot.PRIOR_WORLDS = int(k["prior_worlds"])
        bot.PRIOR_ANCHOR = bool(k["prior_anchor"])
    bot.policy_name = f"{base_policy}+oracle-{arm}"
    return bot


def work_arm_values(base_policy: str, select_worlds, report_worlds
                    ) -> tuple[int, int]:
    """Validate the work arm's absolute (N, R) for ``base_policy``."""
    if select_worlds is None or report_worlds is None:
        raise OracleScreenError(
            "the work arm needs both work_select_worlds and work_report_worlds")
    n, r = int(select_worlds), int(report_worlds)
    if n < 1:
        raise OracleScreenError("work_select_worlds must be >= 1")
    if r < WORK_MIN_REPORT_WORLDS:
        raise OracleScreenError(
            f"work_report_worlds must be >= {WORK_MIN_REPORT_WORLDS}: the "
            "LCB report rule is registered for at least that many worlds")
    if base_policy_class(base_policy).REPORT_RULE == "none":
        raise OracleScreenError(
            f"base policy {base_policy!r} has no report fold to scale")
    return n, r


def make_work_bot(base_policy: str, *, seed: int | None, select_worlds,
                  report_worlds):
    """The compute-control arm: production itself at an absolute N and R."""
    n, r = work_arm_values(base_policy, select_worlds, report_worlds)
    bot = make_bot(base_policy, seed=seed)
    bot.N_DETERMINIZATIONS = n
    bot.REPORT_FOLD_WORLDS = r
    bot.policy_name = f"{base_policy}+work-N{n}-R{r}"
    return bot


def make_side_bot(config: dict, side: str, seed: int):
    """One bot for one seat: ``side`` is ``arm`` or ``baseline``."""
    base = config["base_policy"]
    arm = config["arm"]
    work = config.get("work") or {}
    if side == "baseline" or arm == "none":
        bot = make_bot(base, seed=seed)
    elif arm == "null":
        bot = make_bot(base, seed=seed + NULL_SEED_OFFSET)
        bot.policy_name = f"{base}+null"
    elif arm == KNOBS_ARM:
        bot = make_knobs_bot(base, config["knobs"].get("overrides"), seed=seed)
    elif arm == WORK_ARM:
        if work.get("select_worlds") is not None or \
                work.get("report_worlds") is not None:
            raise OracleScreenError(
                "the work arm cannot be combined with the smoke "
                "select_worlds/report_worlds overrides")
        bot = make_work_bot(base, seed=seed,
                            select_worlds=work.get("work_select_worlds"),
                            report_worlds=work.get("work_report_worlds"))
    else:
        bot = make_oracle_bot(base, arm, seed=seed, knobs=config["knobs"])
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
                 report_worlds: int | None = None,
                 work_select_worlds: int | None = None,
                 work_report_worlds: int | None = None,
                 knob_overrides=None) -> dict:
    """``select_worlds``/``report_worlds`` are the SMOKE overrides (both
    sides); ``work_select_worlds``/``work_report_worlds`` are the work arm's
    absolute N/R (arm side only): ``work.effective`` is the baseline side's
    work, ``work.arm_effective`` the arm side's, and they differ only for the
    work arm, whose baseline is production and therefore not a smoke run.
    ``knob_overrides`` (the knobs arm's ``--knob NAME=VALUE`` list or a
    mapping) is validated against the base class here, so a bad override
    refuses before any round runs; it lands in ``knobs.overrides``."""
    if arm not in ARMS:
        raise OracleScreenError(f"arm must be one of {ARMS}, got {arm!r}")
    base_cls = base_policy_class(base_policy)
    k = dict(knob_defaults())
    k.update(knobs or {})
    overrides = (knob_overrides if knob_overrides is not None
                 else k.get("overrides") or {})
    if arm == KNOBS_ARM:
        k["overrides"] = parse_knob_overrides(base_cls, overrides)
    elif overrides:
        raise OracleScreenError(
            f"knob overrides belong to the {KNOBS_ARM!r} arm, not {arm!r}")
    else:
        k["overrides"] = {}
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
    arm_effective = dict(effective)
    if arm == WORK_ARM:
        if select_worlds is not None or report_worlds is not None:
            raise OracleScreenError(
                "the work arm sets the arm side's N/R itself; the smoke "
                "select_worlds/report_worlds overrides (both sides) cannot "
                "be combined with it")
        n, r = work_arm_values(base_policy, work_select_worlds,
                               work_report_worlds)
        arm_effective["n_determinizations"] = n
        arm_effective["report_fold_worlds"] = r
    elif work_select_worlds is not None or work_report_worlds is not None:
        raise OracleScreenError(
            "work_select_worlds/work_report_worlds apply to the work arm only")
    return {
        "arm": arm,
        "base_policy": base_policy,
        "base_class": base_cls.__name__,
        "knobs": k,
        "work": {
            "select_worlds": select_worlds,
            "report_worlds": report_worlds,
            "work_select_worlds": work_select_worlds,
            "work_report_worlds": work_report_worlds,
            "registered": registered,
            "effective": effective,
            "arm_effective": arm_effective,
            "production": effective == registered,
        },
    }


def _history_digest(history) -> str:
    payload = json.dumps([[seat, list(cards)] for seat, cards in history])
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def play_screen_round(config: dict, cluster: int, seed: int, mirror: int, *,
                      bot_factory=None, counter_fn=None, game_factory=None
                      ) -> tuple[dict, dict]:
    """One round: arm vs baseline on deal ``seed``; ``mirror`` swaps teams.

    Seeds follow ``shengji.evaluation.run_arm``: the arm under test takes
    ``seed``/``seed+500_000`` and the opponent ``seed+1_000_000``/
    ``seed+1_500_000``; mirror 0 seats the arm at 0 and 2 (team 0).
    """
    # Narrow dependency injection lets learned heads reuse the exact mirrored
    # game driver and scoring convention without registering a live policy.
    factory = bot_factory or make_side_bot
    count = counter_fn or work_counters
    a1 = factory(config, "arm", seed)
    a2 = factory(config, "arm", seed + 500_000)
    b1 = factory(config, "baseline", seed + 1_000_000)
    b2 = factory(config, "baseline", seed + 1_500_000)
    pol = [a1, b1, a2, b2] if mirror == 0 else [b1, a1, b2, a2]
    arm_team = 0 if mirror == 0 else 1
    started = time.perf_counter()
    try:
        log = play_round((game_factory or Game)(random.Random(seed)), pol, record=True)
    except OracleScreenError as exc:
        raise OracleRoundRefused(cluster, seed, mirror, str(exc)) from exc
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
        "work": {"arm": count([a1, a2]),
                 "baseline": count([b1, b2])},
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
    scheduling, so a run with any worker count reproduces byte for byte; a
    refused round (``OracleRoundRefused``) propagates, and with a pool it is
    the first refusal in that same order.
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
                try:
                    results[key] = future.result()
                except OracleScreenError:
                    # Fail closed: nothing queued behind the refusal starts.
                    pool.shutdown(cancel_futures=True)
                    raise
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
              bootstrap_seed: int = DEFAULT_BOOTSTRAP_SEED,
              refused: dict | None = None) -> dict:
    """``refused`` (``OracleRoundRefused.as_record()``) marks a run that a
    round refused: it heads ``problems`` and is stamped as ``refused``."""
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
    if refused is not None:
        problems.append(
            f"REFUSED (cluster {refused['cluster']}, seed {refused['seed']}, "
            f"mirror {refused['mirror']}): {refused['reason']}; the run "
            "stopped there and recorded no round")
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
    # Coverage of the wide arm's enumeration.  A capped listing is a
    # deterministic legal prefix + the production ballot, not the legal set;
    # that limit is named here and in problems, not buried in a counter.
    coverage = None
    if config["arm"] in WIDE_ARMS:
        capped = wide.get("oracle_wide_capped", 0)
        coverage = {
            "cap": int(config["knobs"]["wide_cap"]),
            "require_complete": bool(config["knobs"]["wide_require_complete"]),
            "decisions": wide_decisions,
            "complete": wide_decisions - capped,
            "capped": capped,
            "capped_rate": capped / wide_decisions if wide_decisions else None,
            # Sum of the exact legal counts: exact when uncountable_decisions
            # is 0, otherwise a lower bound.
            "legal_count_total": wide.get("oracle_wide_legal_count", 0),
            "uncountable_decisions": wide.get("oracle_wide_uncountable", 0),
            "listed_total": wide.get("oracle_wide_legal_seen", 0),
        }
        if capped:
            problems.append(
                f"arm: wide enumeration capped at {coverage['cap']} in "
                f"{capped}/{wide_decisions} contested decisions (capped_rate "
                f"{coverage['capped_rate']:.3f}): those ballots came from a "
                "deterministic legal prefix + the production ballot, NOT "
                "the legal set")
    if not os.environ.get("SHENGJI_REQUIRE_VOIDS"):
        problems.append("SHENGJI_REQUIRE_VOIDS unset: sampled worlds may "
                        "violate observed voids")
    if not config["work"]["production"]:
        problems.append("work override in effect: this is NOT production work")

    if config["arm"] == KNOBS_ARM:
        claim = ("equal-work screen of production candidate-generator knobs, "
                 "NOT a promotion: non-promotable on its own; the arm is the "
                 "production search with the stamped ballot knobs overridden, "
                 "its work/report vector is production's "
                 "(identity.search_vector) and any extra ballot work it buys "
                 "is charged in total_rollouts")
    else:
        claim = ("expensive heuristic probe, NOT a ceiling: non-promotable; "
                 "arms may exceed production compute and are not candidate "
                 "policies; a weak or null result does not close the learned "
                 "value/prior direction")
    return {
        "schema": SUMMARY_SCHEMA,
        "claim": claim,
        "arm": config["arm"],
        "arm_description": arm_description(config),
        "base_policy": config["base_policy"],
        "base_class": config["base_class"],
        "knobs": config["knobs"],
        "work": config["work"],
        "seed0": seed0,
        "rounds": len(records),
        "clusters": len(clusters),
        "refused": refused,
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
        "wide_coverage": coverage,
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
    if arm == KNOBS_ARM:
        overrides = k.get("overrides") or {}
        if not overrides:
            return f"{base} with no knob overrides (identity control)"
        return f"{base} with " + ", ".join(
            f"{name}={value!r}" for name, value in sorted(overrides.items()))
    if arm == WORK_ARM:
        w = config["work"]
        return (f"{base} at N={w['arm_effective']['n_determinizations']} "
                f"selection worlds, R={w['arm_effective']['report_fold_worlds']} "
                f"report worlds vs production "
                f"N={w['registered']['n_determinizations']}, "
                f"R={w['registered']['report_fold_worlds']} (compute control)")
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
            f"oracle wide: capped legal prefix (cap {k['wide_cap']}) + "
            f"production ballot, screened on {k['wide_screen_worlds']} shared "
            f"worlds, top {k['wide_keep_stage1']} ranked on "
            f"{k['prior_worlds']} shared worlds, keep top {k['wide_keep_top']}"
            + (" (anchor replaces incumbent)" if k["prior_anchor"]
               else " (incumbent kept)")
            + ", N unchanged"
            + (", complete enumeration required (a capped prefix refuses)"
               if k["wide_require_complete"] else ""))
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
    arm_bot = None
    if config["arm"] in ORACLE_ARMS:
        arm_bot = make_oracle_bot(config["base_policy"], config["arm"],
                                  seed=0, knobs=config["knobs"])
    elif config["arm"] == KNOBS_ARM:
        arm_bot = make_knobs_bot(config["base_policy"],
                                 config["knobs"].get("overrides"), seed=0)
    elif config["arm"] == WORK_ARM:
        arm_bot = make_side_bot(config, "arm", 0)
    if arm_bot is not None:
        ballots["arm"] = str(mc_ballot(arm_bot))
        ballots["arm_class"] = type(arm_bot).__name__
    # The complete work/report vector of each side at registered work (the
    # two-sided smoke overrides live in work.effective).  For the knobs arm
    # `equal` is the same-altitude equal-work witness; an oracle arm that
    # changes leaf valuation (exact endgame on) honestly shows unequal, and
    # so does the work arm whenever its N/R differ from the registered
    # values (that difference is the arm; work.arm_effective names it).
    vectors = {"baseline": search_vector(base, type(base))}
    vectors["arm"] = (dict(vectors["baseline"]) if arm_bot is None
                      else search_vector(arm_bot, type(base)))
    vectors["equal"] = vectors["arm"] == vectors["baseline"]
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
        # The ballot spec only covers MC_BALLOT_ATTRS; TRACTOR_LOCK and the
        # like would otherwise leave two knob screens looking alike.
        "knob_overrides": dict(sorted(
            (config["knobs"].get("overrides") or {}).items())),
        "search_vector": vectors,
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
               work_select_worlds: int | None = None,
               work_report_worlds: int | None = None,
               replicates: int = DEFAULT_BOOTSTRAP_REPLICATES,
               bootstrap_seed: int = DEFAULT_BOOTSTRAP_SEED,
               script_path: str | None = None, argv: list[str] | None = None,
               progress: bool = False, knob_overrides=None) -> dict:
    config = build_config(arm=arm, base_policy=base_policy, knobs=knobs,
                          select_worlds=select_worlds,
                          report_worlds=report_worlds,
                          work_select_worlds=work_select_worlds,
                          work_report_worlds=work_report_worlds,
                          knob_overrides=knob_overrides)
    ident = identity(config, script_path)
    started = time.perf_counter()

    def report(done, total, rec):
        print(f"  round {done}/{total}: cluster {rec['cluster']} mirror "
              f"{rec['mirror']} arm_utility {rec['arm_utility']:+d} "
              f"({rec['arm_role']})", flush=True)

    refused = None
    try:
        records, timings = run_rounds(config, rounds=rounds, seed0=seed0,
                                      workers=workers,
                                      progress=report if progress else None)
    except OracleRoundRefused as exc:
        # Fail closed, on the record: the refusal becomes the run's summary
        # (no round, problems headed by the refusal) and is then re-raised
        # so the caller exits non-zero.
        refused, records, timings = exc, [], []
    summary = summarize(records, config, seed0=seed0, replicates=replicates,
                        bootstrap_seed=bootstrap_seed,
                        refused=None if refused is None else refused.as_record())
    summary["identity"] = ident
    runtime = runtime_receipt(workers=workers,
                              wall_secs=time.perf_counter() - started,
                              argv=argv or sys.argv, timings=timings)
    paths = write_outputs(out_dir, records=records, timings=timings,
                          summary=summary, runtime=runtime)
    summary["paths"] = paths
    if refused is not None:
        refused.paths = paths
        raise refused
    return summary
