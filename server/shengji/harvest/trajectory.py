"""Natural-trajectory self-play generator: ``source: "trajectory"`` records.

Ledger basis: 29871a60 (data at scale from engine self-play) and 7a799e1c
(VALUE target = the round's final outcome; PRIOR target = the search's own
evidence over the exhaustive legal set; root exploration so off-ballot
moves can earn mass).  Tier i, engine only: nothing here spends LLM tokens.

What one run does
-----------------
``rounds / 2`` seeded deal clusters (deal seed ``seed0 + cluster``), each
played in both mirrors exactly as ``shengji.evaluation.run_arm`` seats an
arm: the four bots take seeds ``seed``, ``seed + 500_000``,
``seed + 1_000_000`` and ``seed + 1_500_000``; mirror 0 seats them
``[a1, b1, a2, b2]`` and mirror 1 ``[b1, a1, b2, a2]``.  All four seats play
the SAME registry policy (default ``mc-s0-report-lcb``), built through
``registry.make_bot`` (so the seed is forwarded and ``policy_name`` bound)
and then re-classed onto ``TrajectoryMixin`` -- a ``_candidates`` override,
the way ``OraclePriorMixin`` hands ``MCBot`` a modified ballot.  Every
``decide_play`` is followed by a read of ``MCBot.last_decision_record``
(``mc-decision-v2``: ``candidates``, ``n_by_candidate``, ``means``,
``paired_se``, ``eligible_indices``, ``played_index``,
``report_candidate_index``, ``report_fold``, ``work``).

Record mapping (``shengji-decision-record-v1``, ``source: "trajectory"``)
-------------------------------------------------------------------------
* ``round_seed`` and ``deck`` are both public: the deal is the
  reproducibility handle (as for room-log/highn); ``hidden_hands`` is null
  and there is no private split.
* ``ballot`` is the candidate list the search actually ran, exploration-added
  entries included; ``production_ballot`` is present only when exploration
  widened it and holds the plain ``MCBot._candidates`` list.
* ``legal_actions`` is the BOUNDED listing of ``harvest.legal`` (cap 256 by
  default; the ballot and the taken action are always included, and
  ``legal_actions_complete`` / ``legal_actions_count`` say exactly what was
  withheld).  The exhaustive set is re-derivable from the stored state
  (``deck`` + ``setup`` + ``plays_prefix`` -> ``harvest.rebuild`` ->
  ``harvest.legal.enumerate_legal(cap=None)``), so a prior over the FULL
  legal set is trained by re-enumeration, never from the listing.
* ``action`` is the submitted play; ``engine_play`` is stamped when the
  engine recorded different cards (a failed throw) and ``plays_prefix``
  carries the engine's cards.
* ``outcome`` is the FINAL round outcome, filled after the round ends,
  signed for the acting seat's partnership (``harvest.rebuild.outcome_for``:
  attacker points, winner team, level change, signed level utility, kitty
  bonus).
* ``source_ref`` = ``<run_id>:<cluster>:<mirror>:<seat>:<ply>`` (``bury``
  in place of the ply for a bury record); ``policy`` is the registry name;
  ``authority`` is null; ``exploration`` and ``preference`` are documented
  in ``schema.py`` and below.

``allocation`` (kind ``search-work``) is NOT a preference
-----------------------------------------------------------
``allocation.weights`` is the FIXED-DESIGN work split of the search over
the ballot, normalized to sum 1 and aligned with ``ballot``: per candidate
``i``, ``n_by_candidate[i]`` (the selection worlds on which candidate ``i``
was scored) plus the report-fold worlds actually used, credited to BOTH
finalists (candidate 0 and ``report_candidate_index``) whenever the report
fold ran.  ``mc-s0-report-lcb`` gives every candidate the same ``N``
selection worlds and both finalists the same ``R`` report worlds, so these
weights are experiment-design counts: a decisive challenger win and a
decisive challenger loss produce the SAME allocation.  It is recorded so the
work the search spent per candidate is auditable; it is not a visit-count
preference and must not be used as a policy target by itself.  Dummy
residual rollouts (an equal-work control's ``dummy_rollouts``) are excluded.
Decisions the search never saw (a tractor-locked lead, a single-candidate
ballot) and a zero-world fallback carry a point mass on the played action.

``preference``: the preregistered target
-----------------------------------------
A recomputable transform of the search's own evidence into two
distributions over the ballot (each sums to 1, zero outside the ballot):

``softmax``
    ``p_i = exp((m_i - max_j m_j) / tau) / sum_k exp((m_k - max_j m_j) / tau)``
    over the ballot, where ``m`` are per-candidate means and
    ``tau = max(median(finite paired SEs of candidates 1..K-1), 1e-6)``.
``final``
    one-hot on the played action (the search's decision distribution).

Inputs read from ``mc-decision-v2``: ``means`` (selection-stage per-candidate
means, acting-team perspective), ``paired_se`` (SE of the paired difference
``candidate_i - candidate_0`` over the selection worlds; 0 for candidate 0,
which is why candidate 0 is excluded from the median), ``n_by_candidate``,
``played_index``, ``report_candidate_index`` and ``report_fold.{gap, se,
worlds}``.  The report fold does not produce absolute means; it produces the
paired gap ``challenger - candidate_0`` on ``R`` fresh shared worlds.  When
it ran (``worlds > 0``) the challenger ``c`` is REFINED by pooling the two
paired estimates over all shared worlds:

    d_sel   = means[c] - means[0]            (n_sel = n_by_candidate[c] worlds)
    gap     = (n_sel * d_sel + R * report.gap) / (n_sel + R)
    m'[c]   = means[0] + gap                 (candidate 0 anchors the scale)
    se'[c]  = sqrt((n_sel * paired_se[c])^2 + (R * report.se)^2) / (n_sel + R)

and ``refined_indices = [c]``; every other mean/SE is used as recorded.
``d_sel`` is the exact paired mean for the uniform allocation of the default
policy (every candidate scored on the same worlds); for adaptive allocations
it mixes world subsets, which the record documents by carrying the inputs.
Non-finite SEs are excluded from the median; when no finite SE exists
(fewer than two selection worlds and no usable report fold, or a bury
record, which has means but no SEs) ``tau`` is null, meaning infinite
temperature: the softmax is uniform over the ballot.  A decision with no
evidence at all (zero worlds, a tractor-locked lead, a single-candidate
ballot) has ``softmax == final``.  The record stores ``tau`` and the means
and SEs the transform used, so ``softmax`` is recomputable from the record.

Root exploration
----------------
With probability ``explore_rate`` per play decision that reaches a ballot,
up to ``explore_k`` legal actions NOT already on the ballot are appended,
drawn UNIFORMLY over the full exhaustive legal set by reservoir sampling
(Algorithm R) over the enumerator's own iteration
(``harvest.legal.iter_lead_actions`` / ``iter_follow_actions``, the
generators ``enumerate_legal`` consumes) without materializing it, so an
action far beyond the bounded listing has the same chance as the first
one.  ``exploration.pool_count`` is the exact number of non-ballot legal
actions the sample was drawn from; when that set is uncountable or above
``harvest.legal.COUNT_CEILING`` the draw is skipped (``added == []``,
``pool_count == null``) rather than biased.  The draws come from a
dedicated stream, ``random.Random(_child_seed((round_seed, mirror, seat),
"trajectory-explore"))``; the search's own ``self.rng`` is never touched,
so ``--explore-rate 0`` reproduces production decisions exactly (tested).
Added candidates receive selection worlds like any other candidate.  A
tractor-locked lead returns before a ballot exists (as in the oracle prior
arm) and is never widened.

Bury decisions
--------------
``MCBot.decide_bury`` exposes ``last_bury_record`` only when ``MC_BURY`` is
on.  The default policy (``mc-s0-report-lcb``, ``MC_BURY = False``) buries
with SmartBot's rule and exposes no record, so NO bury records are emitted
for it; the omission is visible as ``counts.bury_records == 0``.  A policy
whose bury path does expose a record (the registered ``*-structured-bury``
factories) gets one ``decision_kind: "bury"`` record per round, mapped like
a play record (ballot = the bury candidates, allocation from
``n_by_candidate``, means from ``mean_banker_value``, no SEs).

Shards, resume, determinism
---------------------------
The unit of work is one deal cluster (both mirrors).  As each cluster
finishes -- in any process, in any order -- its records are published as
an IMMUTABLE shard ``shards/cluster-<index:06d>.jsonl`` (records in
``(mirror, seat, ply)`` order, a bury record first within its seat) plus a
sidecar ``shards/cluster-<index:06d>.json`` (run_id, cluster, seed, sha256,
byte size, record count, counts, realized work): both are written to a
temporary name and ``os.replace``d into place, then made read-only.  Memory
holds one cluster at a time.  Progress lines carry counts only.

``run.json`` pins the run identity (``run_id`` = a digest of policy, seed0,
exploration knobs, effective work and cap -- never the wall clock) alongside
the package-source and native-backend identity.  ``--resume`` reopens an out
dir with the SAME run_id:
clusters whose shard and sidecar verify (identity, sha256, byte size,
record count) are kept, missing or invalid ones are regenerated, and a
different run_id or a different generator/engine code identity refuses.
Without ``--resume`` an out dir that already holds a run refuses.  A worker
failure never discards published shards: the remaining clusters are still
drained and published, then the run fails loudly, naming the failed
clusters, and ``--resume`` completes it.  Shard bytes depend only on the
configuration and the cluster, so they are identical across worker counts
and across an interruption + resume.

At the end ``manifest.json`` (deterministic: no timing) lists the shards
in cluster order with their hashes, the aggregated counts and realized
work, the configuration, the registered-vs-effective work and the code
identity; ``runtime.json`` carries the wall clock, worker count, peak RSS
and the reused/generated/failed clusters of this invocation.  A merged
``trajectory.jsonl`` (shards concatenated in cluster order, streamed) is
written ONLY with ``--merge``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import multiprocessing
import os
import platform
import random
import resource
import statistics
import subprocess
import sys
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Callable, Iterator

from ..ai.mcbot import MCBot, _child_seed
from ..ai.registry import make_bot
from ..engine.game import Game
from ..engine.round import actual_play_after
from ..evaluation import counters as production_counters
from .common import action_key, sha256_file, write_jsonl
from .legal import (COUNT_CEILING, DEFAULT_CAP, LegalSet, bury_action_count,
                    count_follow_actions, count_lead_actions, enumerate_legal,
                    iter_follow_actions, iter_lead_actions)
from .rebuild import (actor_role, deck_from_seed, outcome_for,
                      round_from_setup, setup_from_round)
from .schema import SCHEMA, canonical_json, finalize_record

SOURCE = "trajectory"
DEFAULT_POLICY = "mc-s0-report-lcb"
DEFAULT_EXPLORE_RATE = 0.1
DEFAULT_EXPLORE_K = 2
ALLOCATION_KIND = "search-work"
PREFERENCE_KIND = "trajectory-preference-v1"
ACTION_VALUES_KIND = "trajectory-action-values-v1"
MANIFEST_SCHEMA = "shengji-trajectory-manifest-v1"
SHARD_SCHEMA = "shengji-trajectory-shard-v1"
RUN_SCHEMA = "shengji-trajectory-run-v1"
RUNTIME_SCHEMA = "shengji-trajectory-runtime-v1"
ALLOCATION_COUNTER = ("fixed-design work split: selection worlds per candidate "
                      "(n_by_candidate) plus the report-fold worlds used, credited "
                      "to both finalists (candidate 0 and report_candidate_index); "
                      "dummy residual rollouts excluded; NOT a preference")
BURY_ALLOCATION_COUNTER = "bury worlds per candidate (n_by_candidate); NOT a preference"
TAU_FLOOR = 1e-6
EXPLORE_STREAM = "trajectory-explore"
#: seat seeds relative to the deal seed, as ``evaluation.run_arm`` assigns
#: them to ``a1, a2, b1, b2``
SEAT_SEED_OFFSETS = (0, 500_000, 1_000_000, 1_500_000)
#: test-only fault injection: comma-separated cluster indices whose task
#: raises before doing any work (inherited by spawned workers)
FAIL_CLUSTERS_ENV = "SHENGJI_TRAJECTORY_FAIL_CLUSTERS"
COUNT_KEYS = ("rounds", "decisions", "bury_records", "searched", "tractor_locked",
              "single_candidate", "explore_opportunities", "explore_fired",
              "explore_added", "explore_played", "explore_pool_skipped",
              "short_searches", "zero_world", "incomplete_work", "failed_throws",
              "plays", "records")
SERVER = Path(__file__).resolve().parents[2]


class TrajectoryError(RuntimeError):
    """The requested generation cannot be carried out as specified."""


# ------------------------------------------------------------ exploration

def legal_iteration(rnd, seat: int) -> tuple[Iterator[tuple[str, ...]], int | None]:
    """The enumerator's FULL iteration and exact count for the acting seat:
    the same generators ``enumerate_legal`` consumes, with no cap."""
    assert rnd.trick is not None and rnd.ordering is not None
    o = rnd.ordering
    hand = list(rnd.hands[seat])
    if not rnd.trick.plays:
        return iter_lead_actions(hand, o), count_lead_actions(hand, o)
    lead = rnd.trick.plays[0].cards
    return iter_follow_actions(hand, lead, o), count_follow_actions(hand, lead, o)


def sample_off_ballot(rnd, seat: int, k: int, rng: random.Random,
                      exclude) -> tuple[list[list[str]], int | None]:
    """Uniform sample without replacement of up to ``k`` legal actions not
    in ``exclude``: reservoir sampling (Algorithm R) over the full
    enumeration, which is never materialized.

    Returns ``(sample in enumeration order, pool_count)``; ``pool_count`` is
    the exact number of non-excluded legal actions iterated.  When the
    enumeration is uncountable or larger than ``COUNT_CEILING`` nothing is
    drawn (``([], None)``): exploration is skipped there, never biased.
    """
    iteration, count = legal_iteration(rnd, seat)
    if count is None or count > COUNT_CEILING:
        return [], None
    excluded = {action_key(c) for c in exclude}
    reservoir: list[tuple[int, tuple[str, ...]]] = []
    n = 0
    for key in iteration:
        if key in excluded:
            continue
        n += 1
        if k <= 0:
            continue
        if len(reservoir) < k:
            reservoir.append((n, key))
        else:
            j = rng.randrange(n)
            if j < k:
                reservoir[j] = (n, key)
    reservoir.sort()
    return [list(key) for _, key in reservoir], n


# ------------------------------------------------------------------ the bot

class TrajectoryMixin:
    """Root exploration and ballot capture layered on a production MCBot.

    ``_candidates`` is the injection point: ``MCBot.decide_play`` calls it
    exactly once per decision that reaches a ballot and runs the search on
    the list it returns.  The override records the production list, draws
    the exploration sample from the dedicated stream over the full legal
    enumeration, and enumerates the bounded listing for the record with the
    whole ballot force-included.  The search stream ``self.rng`` is never
    read here.
    """

    EXPLORE_RATE = 0.0
    EXPLORE_K = 0
    LEGAL_CAP: int | None = DEFAULT_CAP

    def _trajectory_init(self, explore_rng: random.Random) -> None:
        self.explore_rng = explore_rng
        self.explore_opportunities = 0
        self.explore_fired = 0
        self.explore_added = 0
        self.explore_pool_skipped = 0
        self._trajectory_reset()

    def _trajectory_reset(self) -> None:
        self.last_ballot: list[list[str]] | None = None
        self.last_production_ballot: list[list[str]] | None = None
        self.last_exploration: dict | None = None
        self.last_legal: LegalSet | None = None

    def decide_play(self, rnd, seat):
        self._trajectory_reset()
        return super().decide_play(rnd, seat)

    def _candidates(self, rnd, seat):
        if self.last_ballot is not None:
            raise TrajectoryError(
                "MCBot._candidates was consulted twice in one decision; the "
                "exploration draw would be repeated")
        base = [list(c) for c in super()._candidates(rnd, seat)]
        ballot = [list(c) for c in base]
        exploration = None
        if self.EXPLORE_RATE > 0 and self.EXPLORE_K > 0:
            self.explore_opportunities += 1
            if self.explore_rng.random() < self.EXPLORE_RATE:
                added, pool_count = sample_off_ballot(
                    rnd, seat, self.EXPLORE_K, self.explore_rng, exclude=base)
                ballot.extend(list(a) for a in added)
                exploration = {"rate": float(self.EXPLORE_RATE),
                               "added": [list(a) for a in added],
                               "pool_count": pool_count}
                self.explore_fired += 1
                self.explore_added += len(added)
                if pool_count is None:
                    self.explore_pool_skipped += 1
        legal = enumerate_legal(rnd, seat, cap=self.LEGAL_CAP, must_include=ballot)
        self.last_production_ballot = base
        self.last_ballot = ballot
        self.last_exploration = exploration
        self.last_legal = legal
        return [list(c) for c in ballot]


_TRAJECTORY_CLASSES: dict[type, type] = {}


def trajectory_class(base_cls: type) -> type:
    cls = _TRAJECTORY_CLASSES.get(base_cls)
    if cls is None:
        cls = type(f"Trajectory_{base_cls.__name__}",
                   (TrajectoryMixin, base_cls), {})
        _TRAJECTORY_CLASSES[base_cls] = cls
    return cls


def make_trajectory_bot(config: dict, *, seed: int, explore_rng: random.Random):
    """The registry policy, built by name with its seed forwarded, re-classed
    onto the mixin and given the run's exploration/work knobs."""
    bot = make_bot(config["policy"], seed=seed)
    if not isinstance(bot, MCBot):
        raise TrajectoryError(
            f"policy {config['policy']!r} is not an MCBot search policy: it "
            "has no ballot and no decision record to harvest")
    bot.__class__ = trajectory_class(type(bot))
    bot._trajectory_init(explore_rng)
    bot.EXPLORE_RATE = float(config["explore_rate"])
    bot.EXPLORE_K = int(config["explore_k"])
    bot.LEGAL_CAP = config["cap"]
    work = config["work"]
    if work["select_worlds"] is not None:
        bot.N_DETERMINIZATIONS = int(work["select_worlds"])
    if work["report_worlds"] is not None:
        bot.REPORT_FOLD_WORLDS = int(work["report_worlds"])
    return bot


def mirror_seat_seeds(seed: int, mirror: int) -> list[int]:
    """Bot seed per seat for one deal ``seed``: mirror 0 seats
    ``[a1, b1, a2, b2]``, mirror 1 ``[b1, a1, b2, a2]``."""
    a1, a2, b1, b2 = (seed + off for off in SEAT_SEED_OFFSETS)
    return [a1, b1, a2, b2] if mirror == 0 else [b1, a1, b2, a2]


def explore_seed(seed: int, mirror: int, seat: int) -> int:
    return _child_seed((seed, mirror, seat), EXPLORE_STREAM)


# ------------------------------------------------------------ configuration

def build_config(*, policy: str = DEFAULT_POLICY, seed0: int,
                 explore_rate: float = DEFAULT_EXPLORE_RATE,
                 explore_k: int = DEFAULT_EXPLORE_K,
                 select_worlds: int | None = None,
                 report_worlds: int | None = None,
                 cap: int | None = DEFAULT_CAP) -> dict:
    if not 0.0 <= float(explore_rate) <= 1.0:
        raise TrajectoryError("explore_rate must be in [0, 1]")
    if int(explore_k) < 0:
        raise TrajectoryError("explore_k must be >= 0")
    if cap is not None and int(cap) < 1:
        raise TrajectoryError("cap must be >= 1 (or None for unbounded)")
    probe = make_bot(policy, seed=0)
    if not isinstance(probe, MCBot):
        raise TrajectoryError(
            f"policy {policy!r} is not an MCBot search policy: it has no "
            "ballot and no decision record to harvest")
    registered = {
        "n_determinizations": int(probe.N_DETERMINIZATIONS),
        "report_fold_worlds": int(probe.REPORT_FOLD_WORLDS),
        "report_rule": str(probe.REPORT_RULE),
    }
    effective = dict(registered)
    if select_worlds is not None:
        if int(select_worlds) < 1:
            raise TrajectoryError("select_worlds must be >= 1")
        effective["n_determinizations"] = int(select_worlds)
    if report_worlds is not None:
        if int(report_worlds) < 0:
            raise TrajectoryError("report_worlds must be >= 0")
        effective["report_fold_worlds"] = int(report_worlds)
    # MCBot refuses these combinations at decision time; refuse before any
    # compute is spent.
    rule, worlds = effective["report_rule"], effective["report_fold_worlds"]
    if rule != "none" and worlds <= 0:
        raise TrajectoryError(f"report rule {rule!r} needs report worlds > 0")
    if rule == "none" and worlds > 0:
        raise TrajectoryError("report worlds without a report rule")
    if rule == "lcb" and worlds < 30:
        raise TrajectoryError("the LCB report rule needs at least 30 report "
                              "worlds (MCBot refuses fewer)")
    config = {
        "policy": policy,
        "policy_class": type(probe).__name__,
        "trajectory_class": trajectory_class(type(probe)).__name__,
        "seed0": int(seed0),
        "explore_rate": float(explore_rate),
        "explore_k": int(explore_k),
        "cap": None if cap is None else int(cap),
        "work": {
            "select_worlds": None if select_worlds is None else int(select_worlds),
            "report_worlds": None if report_worlds is None else int(report_worlds),
            "registered": registered,
            "effective": effective,
            "production": effective == registered,
        },
        "policy_flags": {
            "adaptive_allocation": bool(probe.ADAPTIVE_ALLOCATION),
            "require_exact_work": bool(probe.REQUIRE_EXACT_WORK),
            "extra_selection_work": int(probe.EXTRA_SELECTION_WORK),
            "level_objective": bool(probe.LEVEL_OBJECTIVE),
            "tractor_lock": bool(probe.TRACTOR_LOCK),
            "mc_bury": bool(probe.MC_BURY),
            "exact_endgame": bool(probe.EXACT_ENDGAME),
        },
    }
    config["run_id"] = run_id_for(config)
    return config


def run_id_for(config: dict) -> str:
    """A digest of what generates the records, so a rerun at the same seed
    and knobs reproduces ``source_ref`` byte for byte."""
    payload = {
        "policy": config["policy"],
        "seed0": config["seed0"],
        "explore_rate": config["explore_rate"],
        "explore_k": config["explore_k"],
        "cap": config["cap"],
        "work": config["work"]["effective"],
    }
    digest = hashlib.sha256(canonical_json(payload).encode("ascii")).hexdigest()
    return f"traj-s{config['seed0']}-{digest[:12]}"


# ------------------------------------------------------------- record maps

def _finite(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _one_hot(k: int, index: int) -> list[float]:
    return [1.0 if i == index else 0.0 for i in range(k)]


def preference_from_evidence(means, paired_se, played_index: int,
                             refined_indices=()) -> dict:
    """The preregistered ``preference`` transform (module docstring).

    ``means`` / ``paired_se`` are per-candidate floats aligned with the
    ballot, already refined where the report fold applies; non-finite
    values are allowed and handled as documented.
    """
    means = [float(m) for m in means]
    ses = [float(s) for s in paired_se]
    k = len(means)
    final = _one_hot(k, int(played_index))
    finite_means = all(math.isfinite(m) for m in means)
    finite_ses = [s for s in ses[1:] if math.isfinite(s)]
    tau: float | None
    if finite_means and finite_ses:
        tau = max(float(statistics.median(finite_ses)), TAU_FLOOR)
        top = max(means)
        weights = [math.exp((m - top) / tau) for m in means]
        total = sum(weights)
        softmax = [w / total for w in weights]
    elif finite_means:
        tau = None                      # no finite SE: infinite temperature
        softmax = [1.0 / k] * k
    else:
        tau = None                      # no evidence: the decision itself
        softmax = list(final)
    return {
        "kind": PREFERENCE_KIND,
        "softmax": softmax,
        "final": final,
        "tau": tau,
        "means": [_finite(m) for m in means],
        "paired_se": [_finite(s) for s in ses],
        "refined_indices": [int(i) for i in refined_indices],
        "played_index": int(played_index),
    }


def preference_from_record(rec: dict) -> dict:
    """``preference`` for a searched play decision from its ``mc-decision-v2``
    record: selection-stage means and paired SEs, with the report-fold gap
    pooled into the challenger's mean and SE (module docstring)."""
    k = len(rec["candidates"])
    means = [float(m) for m in rec["means"]]
    ses = [float(s) for s in rec["paired_se"]]
    if len(means) != k or len(ses) != k:
        raise TrajectoryError("means/paired_se are not aligned with the ballot")
    refined: list[int] = []
    fold = rec.get("report_fold")
    challenger = rec.get("report_candidate_index")
    if (isinstance(fold, dict) and int(fold.get("worlds") or 0) > 0
            and challenger is not None and 0 < int(challenger) < k):
        c = int(challenger)
        n_sel = int(rec["n_by_candidate"][c])
        r = int(fold["worlds"])
        gap = float(fold["gap"])
        d_sel = means[c] - means[0]
        if math.isfinite(d_sel) and math.isfinite(gap) and n_sel + r > 0:
            means[c] = means[0] + (n_sel * d_sel + r * gap) / (n_sel + r)
            se_rep = float(fold["se"]) if fold.get("se") is not None else math.inf
            se_sel = ses[c]
            ses[c] = (math.sqrt((n_sel * se_sel) ** 2 + (r * se_rep) ** 2) / (n_sel + r)
                      if math.isfinite(se_sel) and math.isfinite(se_rep) else math.inf)
            refined = [c]
    return preference_from_evidence(means, ses, int(rec["played_index"]), refined)


def allocation_from_record(rec: dict, ballot: list[list[str]]) -> dict:
    """``allocation`` (kind ``search-work``) for a searched decision: the
    fixed-design work split, NOT a preference (module docstring)."""
    k = len(ballot)
    if [list(c) for c in rec["candidates"]] != ballot:
        raise TrajectoryError("decision record candidates differ from the "
                              "ballot handed to the search")
    n_by = [int(n) for n in rec["n_by_candidate"]]
    if len(n_by) != k:
        raise TrajectoryError("n_by_candidate is not aligned with the ballot")
    report_worlds = [0] * k
    fold = rec.get("report_fold")
    challenger = rec.get("report_candidate_index")
    if isinstance(fold, dict) and int(fold.get("worlds") or 0) > 0:
        if challenger is None or not 0 <= int(challenger) < k:
            raise TrajectoryError("report fold without a challenger index")
        for i in {0, int(challenger)}:
            report_worlds[i] += int(fold["worlds"])
    worlds = [a + b for a, b in zip(n_by, report_worlds)]
    total = sum(worlds)
    played = int(rec["played_index"])
    if total > 0:
        weights = [w / total for w in worlds]
    else:
        weights = _one_hot(k, played)
    return {
        "kind": ALLOCATION_KIND,
        "weights": weights,
        "counter": ALLOCATION_COUNTER,
        "selection_worlds": n_by,
        "report_worlds": report_worlds,
        "total_worlds": total,
        "played_index": played,
        "raw_winner_index": rec.get("raw_winner_index"),
        "report_candidate_index": challenger,
        "reason": rec.get("reason"),
        "searched": True,
        "work": {key: _finite(v) for key, v in rec["work"].items()},
    }


def point_mass_allocation(reason: str) -> dict:
    return {
        "kind": ALLOCATION_KIND,
        "weights": [1.0],
        "counter": ALLOCATION_COUNTER,
        "selection_worlds": [0],
        "report_worlds": [0],
        "total_worlds": 0,
        "played_index": 0,
        "raw_winner_index": None,
        "report_candidate_index": None,
        "reason": reason,
        "searched": False,
        "work": None,
    }


def point_mass_preference() -> dict:
    return {
        "kind": PREFERENCE_KIND,
        "softmax": [1.0],
        "final": [1.0],
        "tau": None,
        "means": None,
        "paired_se": None,
        "refined_indices": [],
        "played_index": 0,
    }


def action_values_from_record(rec: dict) -> dict:
    fold = rec.get("report_fold")
    report = None
    if isinstance(fold, dict):
        report = {key: _finite(fold.get(key)) for key in (
            "gap", "se", "worlds", "attempts", "rejected", "complete", "rule",
            "critical", "statistic", "min_gain", "bound")}
    return {
        "kind": ACTION_VALUES_KIND,
        "perspective": "acting-team",
        "means": [_finite(m) for m in rec["means"]],
        "paired_se": [_finite(s) for s in rec["paired_se"]],
        "eligible_indices": [int(i) for i in rec["eligible_indices"]],
        "raw_winner_index": rec.get("raw_winner_index"),
        "report": report,
    }


def _play_fields(base: dict, run_id: str, cluster: int, mirror: int, rnd,
                 seat: int, prefix: list[dict], action: list[str], bot,
                 cap: int | None, stats: Counter) -> dict:
    rec = bot.last_decision_record
    ballot = bot.last_ballot
    legal = bot.last_legal
    production_ballot = None
    exploration = bot.last_exploration
    if ballot is None:
        # a tractor-locked lead: returned before any ballot was enumerated
        stats["tractor_locked"] += 1
        ballot = [list(action)]
        legal = enumerate_legal(rnd, seat, cap=cap, must_include=[action])
        allocation = point_mass_allocation("tractor_lock")
        preference = point_mass_preference()
        action_values = None
    elif rec is None:
        if len(ballot) != 1 or action_key(ballot[0]) != action_key(action):
            raise TrajectoryError("no decision record for a contested ballot")
        stats["single_candidate"] += 1
        allocation = point_mass_allocation("single_candidate")
        preference = point_mass_preference()
        action_values = None
    else:
        stats["searched"] += 1
        allocation = allocation_from_record(rec, ballot)
        preference = preference_from_record(rec)
        action_values = action_values_from_record(rec)
        if action_key(rec["played"]) != action_key(action):
            raise TrajectoryError("decision record played a different action")
        if rec["work"].get("complete") is False:
            stats["incomplete_work"] += 1
    if exploration is not None:
        stats["explore_fired"] += 1
        stats["explore_added"] += len(exploration["added"])
        if exploration["pool_count"] is None:
            stats["explore_pool_skipped"] += 1
        production_ballot = bot.last_production_ballot
        added_keys = {action_key(a) for a in exploration["added"]}
        if action_key(action) in added_keys:
            stats["explore_played"] += 1
    return {
        **base,
        "source_ref": f"{run_id}:{cluster}:{mirror}:{seat}:{len(prefix)}",
        "decision_kind": "play",
        "plays_prefix": [dict(p) for p in prefix],
        "seat": seat,
        "ply": len(prefix),
        "trick": len(prefix) // 4,
        "role": actor_role(rnd, seat),
        "legal_actions": [list(a) for a in legal.actions],
        "legal_actions_complete": legal.complete,
        "legal_actions_count": legal.count,
        "ballot": [list(c) for c in ballot],
        "production_ballot": production_ballot,
        "allocation": allocation,
        "preference": preference,
        "action_values": action_values,
        "action": list(action),
        "exploration": exploration,
    }


def _bury_fields(base: dict, run_id: str, cluster: int, mirror: int,
                 banker: int, hand_before: list[str], bury_cards: list[str],
                 raw: dict) -> dict:
    cands = [list(c["cards"]) for c in raw["candidates"]]
    n_by = [int(n) for n in raw["n_by_candidate"]]
    k = len(cands)
    if len(n_by) != k or not 0 <= int(raw["played_index"]) < k:
        raise TrajectoryError("bury record is not aligned with its candidates")
    played = int(raw["played_index"])
    if action_key(cands[played]) != action_key(bury_cards):
        raise TrajectoryError("bury record played a different burial")
    total = sum(n_by)
    weights = [n / total for n in n_by] if total > 0 else _one_hot(k, played)
    means = [c.get("mean_banker_value") for c in raw["candidates"]]
    means_f = ([-math.inf] * k if any(m is None for m in means)
               else [float(m) for m in means])      # None = no world scored it
    work = raw.get("work")
    return {
        **base,
        "source_ref": f"{run_id}:{cluster}:{mirror}:{banker}:bury",
        "decision_kind": "bury",
        "plays_prefix": [],
        "seat": banker, "ply": None, "trick": None,
        "role": "banker-team",
        "legal_actions": None, "legal_actions_complete": False,
        "legal_actions_count": bury_action_count(hand_before),
        "ballot": cands,
        "allocation": {
            "kind": ALLOCATION_KIND,
            "weights": weights,
            "counter": BURY_ALLOCATION_COUNTER,
            "selection_worlds": n_by,
            "report_worlds": [0] * k,
            "total_worlds": total,
            "played_index": played,
            "raw_winner_index": raw.get("raw_winner_index"),
            "report_candidate_index": None,
            "reason": raw.get("reason"),
            "searched": int(raw.get("candidate_count", k)) > 1,
            "work": ({key: _finite(v) for key, v in work.items()}
                     if isinstance(work, dict) else None),
        },
        "preference": preference_from_evidence(means_f, [math.inf] * k, played),
        "action_values": {
            "kind": ACTION_VALUES_KIND,
            "perspective": "acting-team",
            "means": [_finite(m) for m in means],
            "paired_se": None,
            "eligible_indices": None,
            "raw_winner_index": raw.get("raw_winner_index"),
            "report": None,
        },
        "action": list(bury_cards),
        "exploration": None,
    }


# ------------------------------------------------------------------- rounds

def play_trajectory_round(config: dict, cluster: int, seed: int, mirror: int
                          ) -> tuple[list[dict], dict]:
    """One self-play round on deal ``seed``; returns (records, stats).

    Drives the round exactly as ``shengji.ai.env.play_round`` does (deal with
    declarations, the final declare pass, finalize, bury, play), so that at
    ``explore_rate == 0`` the four bots make production's decisions.
    """
    run_id = config["run_id"]
    started = time.perf_counter()
    bots = [make_trajectory_bot(config, seed=s,
                                explore_rng=random.Random(explore_seed(seed, mirror, seat)))
            for seat, s in enumerate(mirror_seat_seeds(seed, mirror))]
    game = Game(random.Random(seed))
    rnd = game.start_round()
    deck = list(rnd.deck)
    if deck != deck_from_seed(rnd.trump_rank, rnd.banker, seed):
        raise TrajectoryError("the deal is not reproducible from round_seed")
    declarations: list[dict] = []
    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        cards = bots[seat].decide_declare(rnd, seat)
        if cards:
            rnd.declare(seat, cards)
            declarations.append({"seat": seat, "cards": list(cards)})
    for seat in range(4):  # the grace window, as play_round
        cards = bots[seat].decide_declare(rnd, seat, final=True)
        if cards:
            rnd.declare(seat, cards)
            declarations.append({"seat": seat, "cards": list(cards)})
    rnd.finalize_declare()
    banker = rnd.banker
    assert banker is not None
    hand_before_bury = sorted(rnd.hands[banker])
    bury_cards = list(bots[banker].decide_bury(rnd, banker))
    bury_raw = getattr(bots[banker], "last_bury_record", None)
    rnd.bury(banker, bury_cards)
    setup = setup_from_round(rnd)
    setup["declarations"] = declarations
    twin = round_from_setup(deck, setup)
    if ([sorted(h) for h in twin.hands] != [sorted(h) for h in rnd.hands]
            or twin.turn != rnd.turn or twin.trump_suit != rnd.trump_suit
            or bool(twin.trump_is_nt) != bool(rnd.trump_is_nt)):
        raise TrajectoryError("setup does not round-trip through rebuild")
    base = {
        "source": SOURCE,
        "policy": config["policy"],
        "round_seed": seed,
        "deck": deck,
        "setup": setup,
        "authority": None,
        "hidden_hands": None,
    }
    stats: Counter = Counter()
    pending: list[dict] = []
    if bury_raw is not None:
        pending.append(_bury_fields(base, run_id, cluster, mirror, banker,
                                    hand_before_bury, bury_cards, bury_raw))
        stats["bury_records"] += 1
    prefix: list[dict] = []
    while rnd.phase == "play":
        seat = rnd.turn
        assert seat is not None
        bot = bots[seat]
        action = list(bot.decide_play(rnd, seat))
        fields = _play_fields(base, run_id, cluster, mirror, rnd, seat, prefix,
                              action, bot, config["cap"], stats)
        prev_last = rnd.last_trick
        rnd.play(seat, action)
        played = actual_play_after(rnd, seat, prev_last)
        if action_key(played) != action_key(action):
            fields["engine_play"] = list(played)
            stats["failed_throws"] += 1
        pending.append(fields)
        prefix.append({"seat": seat, "cards": list(played)})
        stats["decisions"] += 1
    result = game.finish_round()
    records: list[dict] = []
    for fields in pending:
        outcome = outcome_for(result.attacker_points, banker=banker,
                              seat=fields["seat"], kitty_bonus=result.kitty_points)
        if (outcome["winner_team"] != result.winner_team
                or outcome["level_change"] != result.level_change):
            raise TrajectoryError("outcome differs from the engine's result")
        fields["outcome"] = outcome
        records.append(finalize_record(fields))
    stats["rounds"] = 1
    stats["plays"] = len(prefix)
    stats["records"] = len(records)
    for bot in bots:
        stats["explore_opportunities"] += bot.explore_opportunities
        stats["short_searches"] += bot.short_search_decisions
        stats["zero_world"] += bot.zero_world_decisions
        stats["search_calls"] += bot.search_calls
        stats["rollouts"] += bot.rollouts
    work = production_counters(bots)
    timing = {
        "wall_secs": round(time.perf_counter() - started, 4),
        "search_secs": round(float(work.pop("search_secs", 0.0)), 4),
    }
    return records, {"counts": dict(stats), "work": work, "timing": timing,
                     "cluster": cluster, "mirror": mirror, "seed": seed,
                     "attacker_points": int(result.attacker_points)}


def _record_order(record: dict) -> tuple[int, int]:
    return (int(record["seat"]), -1 if record["ply"] is None else int(record["ply"]))


def _fault_injection(cluster: int) -> None:
    raw = os.environ.get(FAIL_CLUSTERS_ENV, "")
    if raw and str(cluster) in {p.strip() for p in raw.split(",") if p.strip()}:
        raise TrajectoryError(f"injected failure for cluster {cluster} "
                              f"({FAIL_CLUSTERS_ENV})")


def play_trajectory_cluster(config: dict, cluster: int, seed: int
                            ) -> tuple[list[dict], list[dict]]:
    """Both mirrors of one deal cluster: records in ``(mirror, seat, ply)``
    order (a bury record first within its seat) and per-round stats."""
    _fault_injection(cluster)
    records: list[dict] = []
    stats: list[dict] = []
    for mirror in (0, 1):
        recs, st = play_trajectory_round(config, cluster, seed, mirror)
        records.extend(sorted(recs, key=_record_order))
        stats.append(st)
    return records, stats


def _cluster_task(args):
    config, cluster, seed = args
    return play_trajectory_cluster(config, cluster, seed)


# ------------------------------------------------------------------- shards

def shard_paths(out_dir: Path, cluster: int) -> tuple[Path, Path]:
    name = f"cluster-{cluster:06d}"
    return out_dir / "shards" / f"{name}.jsonl", out_dir / "shards" / f"{name}.json"


def _atomic_write_text(path: Path, text: str, mode: int = 0o644) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def publish_shard(out_dir: Path, config: dict, cluster: int, seed: int,
                  records: list[dict], stats: list[dict]) -> dict:
    """Write the cluster's shard + sidecar atomically (temp name, then
    ``os.replace``), read-only once published.  Returns the sidecar."""
    jsonl, side = shard_paths(out_dir, cluster)
    jsonl.parent.mkdir(parents=True, exist_ok=True)
    tmp = jsonl.with_name(jsonl.name + ".tmp")
    n, digest = write_jsonl(tmp, records)
    os.chmod(tmp, 0o444)
    os.replace(tmp, jsonl)
    counts: Counter = Counter()
    work: Counter = Counter()
    for st in stats:
        counts.update(st["counts"])
        work.update(st["work"])
    sidecar = {
        "schema": SHARD_SCHEMA,
        "record_schema": SCHEMA,
        "source": SOURCE,
        "run_id": config["run_id"],
        "cluster": int(cluster),
        "seed": int(seed),
        "path": f"shards/{jsonl.name}",
        "records": n,
        "sha256": digest,
        "bytes": jsonl.stat().st_size,
        "counts": {k: int(counts[k]) for k in sorted(counts)},
        "work": {k: int(work[k]) for k in sorted(work)},
        "rounds": [{"mirror": st["mirror"], "seed": st["seed"],
                    "decisions": st["counts"].get("decisions", 0),
                    "attacker_points": st["attacker_points"]} for st in stats],
    }
    _atomic_write_text(side, json.dumps(sidecar, indent=1, sort_keys=True) + "\n",
                       mode=0o444)
    return sidecar


def verify_shard(out_dir: Path, config: dict, cluster: int, seed: int
                 ) -> tuple[dict | None, str]:
    """The sidecar when the published shard verifies (identity, sha256, byte
    size, record count), else ``(None, reason)``."""
    jsonl, side = shard_paths(out_dir, cluster)
    if not jsonl.is_file() or not side.is_file():
        return None, "missing"
    try:
        sidecar = json.loads(side.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, "sidecar unreadable"
    if (not isinstance(sidecar, dict) or sidecar.get("schema") != SHARD_SCHEMA
            or sidecar.get("run_id") != config["run_id"]
            or sidecar.get("cluster") != cluster or sidecar.get("seed") != seed
            or sidecar.get("path") != f"shards/{jsonl.name}"):
        return None, "sidecar identity"
    if jsonl.stat().st_size != sidecar.get("bytes"):
        return None, "byte size"
    if sha256_file(jsonl) != sidecar.get("sha256"):
        return None, "sha256"
    with jsonl.open("rb") as fh:
        n = sum(1 for _ in fh)
    if n != sidecar.get("records"):
        return None, "record count"
    return sidecar, "ok"


def run_clusters(config: dict, *, rounds: int, seed0: int, out_dir: Path,
                 workers: int = 1, resume: bool = False,
                 progress: Callable[[dict], None] | None = None
                 ) -> tuple[dict[int, dict], list[tuple[int, str]], dict]:
    """Play the clusters that need playing and publish each shard as soon as
    it finishes.  Returns (sidecars by cluster, failures, receipt)."""
    if rounds < 2 or rounds % 2:
        raise TrajectoryError("rounds must be an even number >= 2: every "
                              "deal cluster plays both mirrors")
    if workers < 1:
        raise TrajectoryError("workers must be >= 1")
    clusters = list(range(rounds // 2))
    sidecars: dict[int, dict] = {}
    failures: list[tuple[int, str]] = []
    reused: list[int] = []
    timing: dict[int, dict] = {}
    done = 0
    total_decisions = 0

    def note(cluster: int, sidecar: dict, was_reused: bool) -> None:
        nonlocal done, total_decisions
        done += 1
        decisions = int(sidecar["counts"].get("decisions", 0))
        total_decisions += decisions
        if progress:
            progress({"cluster": cluster, "done": done, "total": len(clusters),
                      "decisions": decisions, "total_decisions": total_decisions,
                      "reused": was_reused})

    todo: list[int] = []
    for c in clusters:
        if resume:
            sidecar, _why = verify_shard(out_dir, config, c, seed0 + c)
            if sidecar is not None:
                sidecars[c] = sidecar
                reused.append(c)
                note(c, sidecar, True)
                continue
        todo.append(c)

    def publish(cluster: int, result, started: float) -> None:
        records, stats = result
        sidecars[cluster] = publish_shard(out_dir, config, cluster,
                                          seed0 + cluster, records, stats)
        timing[cluster] = {
            "wall_secs": round(time.perf_counter() - started, 4),
            "round_wall_secs": [st["timing"]["wall_secs"] for st in stats],
            "search_secs": round(sum(st["timing"]["search_secs"] for st in stats), 4),
        }
        note(cluster, sidecars[cluster], False)

    if workers == 1:
        for c in todo:
            started = time.perf_counter()
            try:
                result = _cluster_task((config, c, seed0 + c))
            except Exception as exc:  # noqa: BLE001 - reported, then re-raised as one
                failures.append((c, f"{type(exc).__name__}: {exc}"))
                continue
            publish(c, result, started)
    elif todo:
        ctx = multiprocessing.get_context("spawn")
        started_all = time.perf_counter()
        with ProcessPoolExecutor(max_workers=min(workers, len(todo)),
                                 mp_context=ctx) as pool:
            futures = {pool.submit(_cluster_task, (config, c, seed0 + c)): c
                       for c in todo}
            for future in as_completed(futures):
                c = futures[future]
                try:
                    result = future.result()
                except Exception as exc:  # noqa: BLE001 - drained, then re-raised
                    failures.append((c, f"{type(exc).__name__}: {exc}"))
                    continue
                publish(c, result, started_all)
    failures.sort()
    receipt = {
        "requested": len(clusters),
        "reused": reused,
        "generated": sorted(c for c in todo if c in sidecars),
        "failed": [[c, why] for c, why in failures],
        "timing": {str(c): timing[c] for c in sorted(timing)},
    }
    return sidecars, failures, receipt


def merge_shards(out_dir: Path, sidecars: dict[int, dict]) -> dict:
    """Stream the shards in cluster order into ``trajectory.jsonl``."""
    path = out_dir / "trajectory.jsonl"
    tmp = path.with_name(path.name + ".tmp")
    digest = hashlib.sha256()
    n = size = 0
    with tmp.open("wb") as dst:
        for c in sorted(sidecars):
            with (out_dir / sidecars[c]["path"]).open("rb") as src:
                for line in src:
                    dst.write(line)
                    digest.update(line)
                    n += 1
                    size += len(line)
    os.chmod(tmp, 0o644)
    os.replace(tmp, path)
    return {"path": path.name, "sha256": digest.hexdigest(), "bytes": size,
            "records": n}


# ----------------------------------------------------------------- identity

def _git(args, cwd) -> str | None:
    try:
        return subprocess.run(["git", *args], cwd=cwd, check=True,
                              capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def _digest(path: Path) -> str | None:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _source_tree_digest(root: Path) -> str:
    """Content-bind every Python source that can participate in generation.

    Resume must not mix shards produced before and after a change in a
    transitive engine, policy, rebuild, schema, or serialization dependency.
    Relative-path and byte-length framing makes the digest unambiguous while
    allowing documentation-only commits at a different Git SHA.
    """
    digest = hashlib.sha256()
    paths = sorted(root.rglob("*.py"),
                   key=lambda path: path.relative_to(root).as_posix())
    for path in paths:
        relative = path.relative_to(root).as_posix().encode("utf-8")
        payload = path.read_bytes()
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


CODE_IDENTITY_KEYS = ("source_tree_sha256", "fast_module_sha256_16", "ballot",
                      "fast_engine", "require_voids")


def identity(config: dict) -> dict:
    from ..engine.ballot import mc_ballot
    from ..engine import combos, fast
    repo = SERVER.parent
    probe = make_trajectory_bot(config, seed=0, explore_rng=random.Random(0))
    fast_path = getattr(getattr(fast, "_fast", None), "__file__", None)
    return {
        "git_sha": _git(["rev-parse", "HEAD"], repo),
        "git_dirty": bool(_git(["status", "--porcelain", "--untracked-files=no"],
                               repo)),
        "source_tree_sha256": _source_tree_digest(SERVER / "shengji"),
        "fast_module_sha256_16": (_digest(Path(fast_path)) if fast_path else None),
        "trajectory_module_sha256_16": _digest(Path(__file__)),
        "mcbot_sha256_16": _digest(SERVER / "shengji" / "ai" / "mcbot.py"),
        "registry_sha256_16": _digest(SERVER / "shengji" / "ai" / "registry.py"),
        "legal_sha256_16": _digest(SERVER / "shengji" / "harvest" / "legal.py"),
        "fast_engine": bool(fast.HAVE_FAST and combos.decompose is fast.decompose),
        "require_voids": bool(os.environ.get("SHENGJI_REQUIRE_VOIDS")),
        "ballot": str(mc_ballot(probe)),
        "python": sys.version.split()[0],
    }


# ------------------------------------------------------------------- driver

def build_run_manifest(config: dict, ident: dict, *, rounds: int,
                       sidecars: dict[int, dict], merged: dict | None,
                       out_dir: Path) -> dict:
    counts: Counter = Counter()
    work: Counter = Counter()
    shards = []
    for c in sorted(sidecars):
        side = sidecars[c]
        counts.update(side["counts"])
        work.update(side["work"])
        _jsonl, side_path = shard_paths(out_dir, c)
        shards.append({
            "cluster": c, "seed": side["seed"], "path": side["path"],
            "sha256": side["sha256"], "bytes": side["bytes"],
            "records": side["records"],
            "sidecar": f"shards/{side_path.name}",
            "sidecar_sha256": sha256_file(side_path),
        })
    for key in COUNT_KEYS:
        counts.setdefault(key, 0)
    return {
        "schema": MANIFEST_SCHEMA,
        "record_schema": SCHEMA,
        "source": SOURCE,
        "run_id": config["run_id"],
        "config": config,
        "seed0": config["seed0"],
        "rounds": int(rounds),
        "clusters": len(shards),
        "shards": shards,
        "counts": {k: int(counts[k]) for k in sorted(counts)},
        "work_realized": {k: int(work[k]) for k in sorted(work)},
        "merged": merged,
        "identity": ident,
        "seeds": {"deal": "seed0 + cluster; Game(random.Random(seed))",
                  "seats": "seed + (0, 500000, 1000000, 1500000) as a1, a2, "
                           "b1, b2; mirror 0 seats [a1, b1, a2, b2], mirror 1 "
                           "[b1, a1, b2, a2]",
                  "explore": f"random.Random(_child_seed((seed, mirror, seat), "
                             f"{EXPLORE_STREAM!r}))"},
        "notes": [
            "allocation (kind search-work) = the fixed-design work split "
            "(selection worlds per candidate + report-fold worlds credited to "
            "both finalists), NOT a preference; do not use as a policy target",
            "preference.softmax_i = exp((m_i - max m) / tau) normalized, tau = "
            "max(median(finite paired SEs of candidates 1..K-1), 1e-6), with the "
            "report-fold gap pooled into the challenger by world count; "
            "preference.final = one-hot on the played action",
            "exploration draws are uniform over the FULL legal enumeration "
            "(reservoir sampling); legal_actions is the bounded listing, the "
            "exhaustive set is re-derivable from deck + setup + plays_prefix",
            "shard records ordered by (mirror, seat, ply); a bury record "
            "precedes its seat's plays; shards listed in cluster order",
            "bury records only when the policy's bury path exposes "
            "last_bury_record (MC_BURY); the default policy emits none",
        ],
    }


def _rss_bytes(value: int) -> int:
    return int(value) if sys.platform == "darwin" else int(value) * 1024


def runtime_receipt(*, argv, workers: int, resume: bool, merge: bool,
                    wall_secs: float, receipt: dict) -> dict:
    return {
        "schema": RUNTIME_SCHEMA,
        "argv": list(argv) if argv is not None else None,
        "host": platform.node(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "logical_cpus": os.cpu_count(),
        "workers": int(workers),
        "resume": bool(resume),
        "merge": bool(merge),
        "wall_secs": round(wall_secs, 3),
        "clusters": {k: receipt[k] for k in ("requested", "reused", "generated", "failed")},
        "per_cluster": receipt["timing"],
        "peak_rss_bytes": {
            "self": _rss_bytes(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss),
            "children_max": _rss_bytes(
                resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss),
        },
        "require_voids": bool(os.environ.get("SHENGJI_REQUIRE_VOIDS")),
        "started": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


def _open_run(out_dir: Path, config: dict, ident: dict, *, resume: bool) -> bool:
    """Pin or check the run identity in ``out_dir/run.json``.  Returns True
    when an existing run is being resumed."""
    run_path = out_dir / "run.json"
    if run_path.exists():
        existing = json.loads(run_path.read_text(encoding="utf-8"))
        if not resume:
            raise TrajectoryError(
                f"{out_dir} already holds run {existing.get('run_id')}; pass "
                "--resume to continue it or choose a fresh directory")
        if existing.get("run_id") != config["run_id"]:
            raise TrajectoryError(
                f"resume refused: {out_dir} holds run {existing.get('run_id')} "
                f"but the requested policy/seed/knobs/work give {config['run_id']}")
        old = existing.get("identity") or {}
        drift = [k for k in CODE_IDENTITY_KEYS if old.get(k) != ident.get(k)]
        if drift:
            raise TrajectoryError(
                "resume refused: the generator/engine code identity differs "
                f"from the run's ({', '.join(drift)}); shards would not be "
                "byte-comparable")
        return True
    if (out_dir / "shards").exists():
        raise TrajectoryError(f"{out_dir}/shards exists without run.json; "
                              "choose a fresh directory")
    out_dir.mkdir(parents=True, exist_ok=True)
    _atomic_write_text(run_path, json.dumps(
        {"schema": RUN_SCHEMA, "run_id": config["run_id"], "config": config,
         "identity": ident}, indent=2, sort_keys=True) + "\n")
    return False


def generate(*, rounds: int, seed0: int, out_dir: str | os.PathLike,
             workers: int = 1, policy: str = DEFAULT_POLICY,
             explore_rate: float = DEFAULT_EXPLORE_RATE,
             explore_k: int = DEFAULT_EXPLORE_K,
             select_worlds: int | None = None, report_worlds: int | None = None,
             cap: int | None = DEFAULT_CAP, merge: bool = False,
             resume: bool = False,
             progress: Callable[[dict], None] | None = None,
             argv: list[str] | None = None) -> dict:
    """Generate the shard store in ``out_dir`` (+ ``trajectory.jsonl`` with
    ``merge``); returns the manifest.  Raises ``TrajectoryError`` when any
    cluster failed (published shards are kept for ``--resume``)."""
    os.environ.setdefault("SHENGJI_REQUIRE_VOIDS", "1")
    if rounds < 2 or rounds % 2:
        raise TrajectoryError("rounds must be an even number >= 2: every "
                              "deal cluster plays both mirrors")
    if workers < 1:
        raise TrajectoryError("workers must be >= 1")
    config = build_config(policy=policy, seed0=seed0, explore_rate=explore_rate,
                          explore_k=explore_k, select_worlds=select_worlds,
                          report_worlds=report_worlds, cap=cap)
    out = Path(out_dir)
    ident = identity(config)
    resumed = _open_run(out, config, ident, resume=resume)
    started = time.perf_counter()
    sidecars, failures, receipt = run_clusters(
        config, rounds=rounds, seed0=seed0, out_dir=out, workers=workers,
        resume=resumed, progress=progress)
    runtime = runtime_receipt(argv=argv, workers=workers, resume=resumed,
                              merge=merge, wall_secs=time.perf_counter() - started,
                              receipt=receipt)
    _atomic_write_text(out / "runtime.json",
                       json.dumps(runtime, indent=2, sort_keys=True) + "\n")
    if failures:
        raise TrajectoryError(
            f"{len(failures)} of {rounds // 2} cluster(s) failed: "
            + "; ".join(f"cluster {c}: {why}" for c, why in failures)
            + f". {len(sidecars)} shard(s) are published and verified in "
            f"{out / 'shards'}; rerun with --resume to complete the run")
    merged = merge_shards(out, sidecars) if merge else None
    manifest = build_run_manifest(config, ident, rounds=rounds, sidecars=sidecars,
                                  merged=merged, out_dir=out)
    _atomic_write_text(out / "manifest.json",
                       json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="trajectory", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rounds", type=int, required=True,
                        help="total rounds (even): rounds/2 clusters x 2 mirrors")
    parser.add_argument("--seed", type=int, required=True,
                        help="seed0; cluster c deals from seed0 + c")
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--out", required=True, type=Path,
                        help="output directory (shard store)")
    parser.add_argument("--policy", default=DEFAULT_POLICY,
                        help=f"registry policy for all four seats (default {DEFAULT_POLICY})")
    parser.add_argument("--explore-rate", type=float, default=DEFAULT_EXPLORE_RATE,
                        help="per-decision probability of widening the ballot "
                             f"(default {DEFAULT_EXPLORE_RATE}; 0 = production)")
    parser.add_argument("--explore-k", type=int, default=DEFAULT_EXPLORE_K,
                        help=f"legal actions added per exploring decision (default {DEFAULT_EXPLORE_K})")
    parser.add_argument("--select-worlds", type=int, default=None,
                        help="override N selection worlds (reduced work; stamped as effective)")
    parser.add_argument("--report-worlds", type=int, default=None,
                        help="override R report worlds (reduced work; LCB needs >= 30)")
    parser.add_argument("--cap", type=int, default=DEFAULT_CAP,
                        help=f"max legal actions listed per record (default {DEFAULT_CAP}; 0 = unbounded)")
    parser.add_argument("--merge", action="store_true",
                        help="also write trajectory.jsonl (shards concatenated in cluster order)")
    parser.add_argument("--resume", action="store_true",
                        help="continue a run in --out with the same run_id: verified "
                             "shards are kept, missing/invalid ones regenerated")
    return parser


def main(argv: list[str] | None = None) -> int:
    os.environ.setdefault("SHENGJI_REQUIRE_VOIDS", "1")
    args = build_parser().parse_args(argv)
    cap = None if args.cap == 0 else args.cap

    def progress(event: dict) -> None:
        state = "reused" if event["reused"] else "done"
        print(f"  cluster {event['cluster']} {state} ({event['done']}/{event['total']}): "
              f"decisions={event['decisions']} total={event['total_decisions']}",
              flush=True)

    try:
        manifest = generate(
            rounds=args.rounds, seed0=args.seed, out_dir=args.out,
            workers=args.workers, policy=args.policy,
            explore_rate=args.explore_rate, explore_k=args.explore_k,
            select_worlds=args.select_worlds, report_worlds=args.report_worlds,
            cap=cap, merge=args.merge, resume=args.resume, progress=progress,
            argv=sys.argv if argv is None else ["trajectory", *argv])
    except TrajectoryError as exc:
        print(f"REFUSING: {exc}", file=sys.stderr)
        return 2
    counts = manifest["counts"]
    runtime = json.loads((Path(args.out) / "runtime.json").read_text(encoding="utf-8"))
    wall = runtime["wall_secs"]
    rss = runtime["peak_rss_bytes"]
    print(f"{SOURCE}: run_id={manifest['run_id']} clusters={manifest['clusters']} "
          f"rounds={counts['rounds']} decisions={counts['decisions']} "
          f"bury_records={counts['bury_records']} searched={counts['searched']} "
          f"explored={counts['explore_fired']} added={counts['explore_added']} "
          f"short={counts['short_searches']} wall={wall}s "
          f"decisions/s={round(counts['decisions'] / wall, 3) if wall else None} "
          f"peak_rss_mb=self:{rss['self'] / 1e6:.1f},children:{rss['children_max'] / 1e6:.1f}",
          flush=True)
    for shard in manifest["shards"]:
        print(f"  {shard['path']}: records={shard['records']} sha256={shard['sha256']}",
              flush=True)
    if manifest["merged"]:
        m = manifest["merged"]
        print(f"  {m['path']}: records={m['records']} sha256={m['sha256']} bytes={m['bytes']}",
              flush=True)
    print(f"manifest -> {Path(args.out) / 'manifest.json'}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
