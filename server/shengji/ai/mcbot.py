"""Determinized Monte Carlo bot.

For every play decision:
 1. Enumerate a small, diverse set of legal candidate plays.
 2. Sample N "determinizations": full deals of the unseen cards to the other
    players (and hidden kitty), consistent with public information — hand
    sizes, observed voids, and the card count. The banker's own knowledge of
    the buried kitty is used when this bot IS the banker (that's private but
    legitimately its own information).
 3. Roll each (candidate, determinization) to the end of the round with the
    fast heuristic policy for all four seats, scoring attacker points
    (sign-flipped for the banker team).
 4. Play the candidate with the best average score.

Declaration and burying are inherited from SmartBot.
"""

from __future__ import annotations

import os
import time
import subprocess
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path

#: Sample count matrices in proportion to the number of card-assignments they
#: admit, rather than uniformly. Off by default until Codex adopts it.
WEIGHTED_SPLITS = bool(os.environ.get("SHENGJI_WEIGHTED_SPLITS"))
#: Draw uniformly among cap-respecting cards instead of taking the first legal
#: one — the second named posterior bias. Also off by default.
UNIFORM_DEAL = bool(os.environ.get("SHENGJI_UNIFORM_DEAL"))
PHYSICAL_FILLS = bool(os.environ.get("SHENGJI_PHYSICAL_FILLS"))
from math import factorial as _fact

import copy
import hashlib
import random
from collections import Counter

from ..engine.cards import TRUMP
from ..engine.combos import decompose
from ..engine.legal import IllegalPlay, suit_cards, uniform_suit, validate_follow
from ..engine.round import Round, Trick, TrickPlay


class DeterminizationContractError(RuntimeError):
    """A sampled world is incomplete or inconsistent with the round cards."""


@dataclass(frozen=True)
class _CanonicalDeterminization:
    """Validated immutable source for one sampled world.

    Each rollout still receives fresh mutable hand lists because ``Round.play``
    consumes cards in-place.  Keeping the canonical source immutable lets all
    candidates on a paired world share the expensive validation/sorting work
    without sharing mutable hands with one another.
    """

    hands: tuple[tuple[str, ...], ...]
    buried: tuple[str, ...]


STRUCTURED_BURY_TELEMETRY_FIELDS = (
    "opportunities", "triggers", "overrides", "candidate_count_sum",
    "searches", "complete_searches", "short_searches",
    "zero_world_searches", "worlds_requested", "worlds_used",
    "candidate_world_budget", "candidate_rollouts", "sample_attempts",
    "accepted_worlds", "failed_worlds", "rejected_worlds",
    "impossible_worlds",
)


def random_state_from_json(value):
    """Restore the tuple tree that ``json`` turns into lists.

    ``random.Random.getstate()`` is JSON-serialisable, but ``setstate`` refuses
    the decoded list representation.  Keeping the conversion here gives live
    decision logs an executable replay path instead of merely enough bytes for
    a human to reconstruct one.
    """
    if isinstance(value, list):
        return tuple(random_state_from_json(v) for v in value)
    return value


def restore_random_state(rng: random.Random, logged_state) -> None:
    """Set ``rng`` from either the live tuple or its JSON-decoded form."""
    rng.setstate(random_state_from_json(logged_state))


def _child_seed(state, purpose: str) -> int:
    """A named RNG stream derived without advancing the selection stream."""
    raw = hashlib.sha256(f"{purpose}|{state!r}".encode()).digest()
    return int.from_bytes(raw[:16], "big")


@lru_cache(maxsize=1)
def _runtime_identity() -> dict:
    """Git and executable-file identity, computed once per process."""
    path = Path(__file__).resolve()
    code_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    repo = path.parents[3]
    try:
        git_sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo, check=True,
            capture_output=True, text=True).stdout.strip()
        dirty = bool(subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=no"],
            cwd=repo, check=True, capture_output=True,
            text=True).stdout.strip())
    except (OSError, subprocess.SubprocessError):
        git_sha, dirty = None, None
    return {"git_sha": git_sha, "git_dirty": dirty,
            "mcbot_sha256": code_sha}


@lru_cache(maxsize=128)
def _cached_ballot_identity(bot_cls, config: tuple) -> dict:
    """Derive the ballot once per live class/configuration, not per move."""
    from ..engine.ballot import BallotSpec, source_digest

    spec = BallotSpec(
        name="mc_candidates", version=1, source="MCBot._candidates",
        config=config,
        source_digest=source_digest(MCBot._candidates, owner=bot_cls))
    out = asdict(spec)
    out.update({"digest": spec.digest, "display": str(spec)})
    return out


def _ballot_identity(bot) -> dict:
    from ..engine.ballot import MC_BALLOT_ATTRS

    config = tuple(sorted((name, getattr(bot, name, None))
                          for name in MC_BALLOT_ATTRS))
    return dict(_cached_ballot_identity(type(bot), config))
from .heuristic import PLAIN_SUITS, HeuristicBot
from .memory import Memory
from .smart import SmartBot


class _BuryLoose(SmartBot):
    """Bury variant: points in the kitty are nearly free."""
    def _bury_points_mult(self, trump_count: int, has_big_joker: bool) -> float:
        return 1.0


class _BuryStrict(SmartBot):
    """Bury variant: never bury points."""
    def _bury_points_mult(self, trump_count: int, has_big_joker: bool) -> float:
        return 8.0


class _BuryNoVoid(SmartBot):
    """Bury variant: ignore void-creation, keep balanced suits."""
    BURY_VOID = False


class MCBot(SmartBot):
    N_DETERMINIZATIONS = 10
    MAX_CANDIDATES = 8
    WIDE_LEAD_BALLOT = True  # leads: roll out every pair/tractor/near-boss
    #                          throw in every suit incl. trump (JVRA gap:
    #                          sourcing, not judgment). ADOPTED: 62% vs
    #                          narrow-ballot mc (75-45, n=120), +7% latency.
    LEAD_MAX_CANDIDATES = 14
    # Ballot V3 lead layer: offer one single per distinct effective level
    # instead of only the top and lowest-non-point card per suit.
    V3_LEAD_SINGLES = False
    V3_LEAD_RANDOM = False      # control: same slots, arbitrary singles
    WIDE_FOLLOW_BALLOT = True  # ADOPTED 60% (72-48, n=120). Follows: bounded exhaustive distinct-code
    #                             multisets on top of the constructed set
    #                             (audit: 21% of human follow singles were
    #                             off-ballot — discard selection). Cap below.
    FOLLOW_MAX_CANDIDATES = 12
    SAMPLE_RETRIES = 15
    DECLARER_PIN = True   # sampled worlds place the declarer's SHOWN cards
    #                       in the declarer's hand (public info; RTLT: a
    #                       declared rank pair was sampled split, making a
    #                       beatable K-pair lead look boss)
    CONFIDENCE_OVERRIDE = False   # S0: require a paired LCB, not a point gap
    ADAPTIVE_ALLOCATION = False   # S0: fixed budget, spent on contenders
    RANDOM_ALLOCATION = False     # S0 attribution: prune identities at random
    SAMPLE_ATTEMPT_FACTOR = 40    # cap draws per decision; None-loops hung
    REQUIRE_EXACT_WORK = False    # experimental arms retry/refuse a short dose
    EXTRA_SELECTION_WORK = 0      # equal-work control; candidate rollouts
    REPORT_FOLD_WORLDS = 0        # >0: score a challenger on DISJOINT worlds
    REPORT_RULE = "none"          # one of: none, mean, lcb
    REPORT_MIN_GAIN = 0.0         # distinct from incumbent point MARGIN=5
    REPORT_ALPHA = 0.05
    # Conservative one-sided Student-t critical for every supported report
    # fold (n >= 30; t_29,0.95 = 1.699). This is a frozen decision heuristic,
    # not the full-game promotion interval.
    REPORT_T_CRITICAL = 1.70
    CONFIDENCE_Z = 1.64           # one-sided 95%
    MARGIN = 5.0  # points/round a candidate must beat SmartBot's pick by;
    #               keeps the heuristic prior unless the search is confident.
    #               0 = pure argmax.
    LEVEL_OBJECTIVE = False  # score rollouts by level-change brackets (the
    #                          real payoff: 79 vs 80 points is a cliff), not
    #                          raw points. Scaled so MARGIN keeps meaning.
    MC_BURY = False          # search the banker's bury over sampled worlds
    N_BURY_WORLDS = 8
    STRUCTURED_BURY = False  # S3a: bounded point/void/trump candidate source
    BURY_MAX_CANDIDATES = 32
    BURY_MAX_ROLLOUTS = 256  # hard candidate-world cap; once per round
    BURY_REQUIRE_EXACT_WORK = True
    EXACT_ENDGAME = False    # S3b: solve determinized continuation exactly
    EXACT_ENDGAME_MAX_CARDS = 4
    EXACT_ENDGAME_MAX_NODES = 250_000
    RISKY_THROWS = False     # put near-boss throws (A+QQ) on the ballot and
    #                          let determinization price them (user idea)
    TRUMP_BALLOT = False     # trump pair / top-trump lead candidates (钓主):
    #                          hand-rules for draining measured -4% three
    #                          times, but the ballot lets worlds price it
    #                          per-position (user idea)
    TRACTOR_LOCK = True      # heuristic tractor leads are final (measured
    #                          56% vs override-allowed, and fixes perceived
    #                          "why didn't it lead the tractor" moments)
    POINT_SHY_EPS = 2.0      # among candidates within this of the best,
    #                          risk the fewest points (10-10 pair leads lose
    #                          20 immediately when beaten; expectation-equal
    #                          but worse downside)
    LEAD_MARGIN = None       # optional higher margin for LEADS only: rollout
    #                          opponents are too passive to punish slow play,
    #                          biasing lead values toward low cards (None =
    #                          use MARGIN)

    def __init__(self, seed: int | None = None):
        self.rng = random.Random(seed)
        self.seed = seed
        self.rollout_policy = HeuristicBot()
        # CUMULATIVE work counters (not per-decision): comparing gates at equal
        # call RATE is not comparing compute, because search cost scales with
        # candidates and worlds and a candidate-count gate deliberately selects
        # expensive states (Codex, 2026-08-04).
        self.search_calls = 0
        self.rollouts = 0
        self.search_secs = 0.0
        # Worlds buildable only by ignoring observed voids. Counted, never
        # refused: refusing them killed the search outright in constrained
        # late-round states where no void-respecting world exists.
        self.impossible_worlds = 0
        self.rejected_worlds = 0
        self.sample_attempts = 0
        self.accepted_worlds = 0
        self.failed_worlds = 0
        self.short_search_decisions = 0
        self.last_override_stats = None
        self.last_alloc = None
        self.last_decision_record = None
        self.last_bury_record = None
        self.bury_search_calls = 0
        self.bury_rollouts = 0
        self.bury_search_secs = 0.0
        self.bury_short_searches = 0
        # S3a is feature-off in production, but a future strength gate must be
        # able to prove that its treatment actually fired and consumed the
        # registered common-world work.  Keep this telemetry private to MCBot so
        # adding it cannot change the shared evaluator record schema used by
        # already-frozen S0/S3b evidence.
        self._structured_bury_totals = {
            name: 0 for name in STRUCTURED_BURY_TELEMETRY_FIELDS}
        self.exact_endgame_calls = 0
        self.exact_endgame_attempts = 0
        self.exact_endgame_refusals = 0
        self.exact_endgame_budget_exceeded = 0
        self.exact_endgame_sessions = 0
        self.exact_endgame_nodes = 0
        self.exact_endgame_cache_hits = 0
        self.reject_cause = Counter()
        # Decisions that fell back to candidate 0 with NO world sampled.
        self.zero_world_decisions = 0

    # ------------------------------------------------------------------- play
    def decide_play(self, rnd: Round, seat: int) -> list[str]:
        assert rnd.trick is not None and rnd.ordering is not None
        self.last_eval = None  # (candidates, per-candidate values) for distillation
        self.last_n_worlds = 0  # worlds that actually sampled — 0 means NO search
        # Literal decision boundary: every early return below must expose NO
        # evidence from the preceding move.  Putting this after candidate
        # generation left tractor-lock and one-candidate plays with stale logs.
        self.last_decision_record = None
        self.last_override_stats = None
        self.last_alloc = None
        sampler_before = self._sampler_snapshot()
        if self.TRACTOR_LOCK and not rnd.trick.plays:
            pick = self.canonical_lead(rnd, seat)
            dec = decompose(pick, rnd.ordering)
            if len(dec.components) == 1 and dec.components[0].pair_len >= 2:
                return pick
        candidates = self._candidates(rnd, seat)
        if len(candidates) <= 1:
            return candidates[0]
        if self.REPORT_RULE not in {"none", "mean", "lcb"}:
            raise ValueError(f"unknown REPORT_RULE {self.REPORT_RULE!r}")
        if self.REPORT_RULE != "none" and self.REPORT_FOLD_WORLDS <= 0:
            raise ValueError("REPORT_RULE requires REPORT_FOLD_WORLDS > 0")
        if self.REPORT_FOLD_WORLDS and self.REPORT_RULE == "none":
            raise ValueError("REPORT_FOLD_WORLDS requires REPORT_RULE")
        if self.REPORT_RULE == "lcb" and self.REPORT_FOLD_WORLDS < 30:
            raise ValueError("S0 report LCB requires at least 30 paired worlds")
        self.search_calls += 1
        # Full pre-decision RNG state: a digest identifies a stream position
        # but cannot restore it, so the logged draw was not replayable even in
        # principle. This works whether or not construction used a seed.
        pre_rng_state = self.rng.getstate()
        report_seed = _child_seed(pre_rng_state, "s0-report")
        allocation_seed = _child_seed(pre_rng_state, "s0-allocation")
        _t0 = time.perf_counter()
        mem = Memory(rnd, seat, own_kitty=getattr(self, 'BANKER_KITTY', True))
        i_attack = rnd.is_attacker(seat)
        totals = [0.0] * len(candidates)
        # Paired running moments of (candidate_i - candidate_0) on the SAME
        # world. The fixed-margin override compares point estimates only, so a
        # noisy draw can clear it: in the sanitised incident `DJ` beat candidate 0 by
        # 5.8-6.3 against a 5.0 margin in 2 of 500 N=30 replicas, while the
        # correct card won the other 479. Pairing on shared worlds removes the
        # world-to-world variance that dominates the raw spread.
        d_sum = [0.0] * len(candidates)
        d_sq = [0.0] * len(candidates)
        n_worlds = 0
        n_by = [0] * len(candidates)
        if self.ADAPTIVE_ALLOCATION:
            totals, d_sum, d_sq, n_by, n_worlds, _rk = self._decide_adaptive(
                rnd, seat, candidates, mem, i_attack,
                allocation_rng=random.Random(allocation_seed))
        else:
            # Uniform arms have an exact candidate-world budget.  The
            # equal-total-work control may add 2R candidate evaluations; whole
            # common worlds affect estimates and an unavoidable <K residual is
            # executed but deliberately excluded as `dummy_rollouts`.
            K = len(candidates)
            budget = self.N_DETERMINIZATIONS * K + self.EXTRA_SELECTION_WORK
            full_target, residual = divmod(budget, K)
            target_draws = full_target + int(bool(residual))
            attempts = 0
            cap = (target_draws * self.SAMPLE_ATTEMPT_FACTOR
                   if self.REQUIRE_EXACT_WORK else target_draws)
            while n_worlds < full_target and attempts < cap:
                attempts += 1
                sampled = self._sample_hands(rnd, seat, mem)
                if sampled is None:
                    continue
                n_worlds += 1
                hands, buried = sampled
                exact_session = self._new_exact_world_session(rnd, buried)
                world = self._prepare_play_world(
                    rnd, seat, hands, buried=buried)
                world_vals = []
                for i, cand in enumerate(candidates):
                    val = self._score(
                        self._rollout(
                            rnd, seat, world, buried, cand,
                            exact_session=exact_session))
                    val = val if i_attack else -val
                    totals[i] += val
                    world_vals.append(val)
                base = world_vals[0]
                for i, value in enumerate(world_vals):
                    delta = value - base
                    d_sum[i] += delta
                    d_sq[i] += delta * delta
                    n_by[i] += 1

            dummy_rollouts = 0
            # Consume the exact residual without letting a subset receive a
            # noisier/differently-selected mean. This is real matched compute,
            # explicitly recorded as unused by the decision rule.
            while (n_worlds == full_target and dummy_rollouts < residual
                   and attempts < cap):
                attempts += 1
                sampled = self._sample_hands(rnd, seat, mem)
                if sampled is None:
                    continue
                hands, buried = sampled
                exact_session = self._new_exact_world_session(rnd, buried)
                world = self._prepare_play_world(
                    rnd, seat, hands, buried=buried)
                for cand in candidates[:residual]:
                    self._score(self._rollout(
                        rnd, seat, world, buried, cand,
                        exact_session=exact_session))
                    dummy_rollouts += 1

            selection_rollouts = n_worlds * K + dummy_rollouts
            short = n_worlds < full_target or dummy_rollouts < residual
            self.last_alloc = {
                "mode": "uniform", "attempts": attempts,
                "attempt_cap": cap, "attempt_cap_hit": attempts >= cap and short,
                "worlds": n_worlds, "rollouts": selection_rollouts,
                "decision_rollouts": n_worlds * K,
                "dummy_rollouts": dummy_rollouts, "budget": budget,
                "short": short, "survivors": K,
                "survivor_indices": list(range(K)),
                "n_by_candidate": list(n_by),
            }
        self.last_n_worlds = n_worlds
        selection_rollouts = int(self.last_alloc["rollouts"])
        self.rollouts += selection_rollouts
        # acting-team perspective values, exposed for search distillation
        # Adaptive selection names its explicit survivor set; uniform selection
        # includes every candidate that received a scoring world. A pruned
        # candidate can therefore never re-enter on its frozen noisy mean.
        eligible = ([i for i in self.last_alloc.get("survivor_indices", [])
                     if n_by[i] > 0] if self.ADAPTIVE_ALLOCATION else
                    [i for i, n in enumerate(n_by) if n > 0]) or [0]
        means = [totals[i] / n_by[i] if n_by[i] else float("-inf")
                 for i in range(len(candidates))]
        self.last_eval = (candidates, means)
        best = self._pick_index(candidates, means, eligible)
        alternatives = [i for i in eligible if i != 0]
        challenger = (self._pick_index(candidates, means, alternatives)
                      if alternatives else None)
        # candidates[0] is SmartBot's own choice: prefer it unless the search
        # clears the confidence margin (rollouts are noisiest early on).
        margin = self.MARGIN
        if self.LEAD_MARGIN is not None and not rnd.trick.plays:
            margin = self.LEAD_MARGIN
        # S0 item 3: persist enough to REPLAY this exact decision. The live
        # logs retained neither the RNG position nor the candidate values, so
        # the reported incident draw could not be reproduced — the diagnosis had to
        # be inferred from replicas. Recorded for every contested decision, not
        # only overrides, because "why did it NOT override" is the same
        # question.
        self.last_decision_record = {
            "schema": "mc-decision-v2",
            "policy": getattr(self, "policy_name", type(self).__name__),
            "policy_class": type(self).__name__,
            "code": _runtime_identity(),
            "ballot": _ballot_identity(self),
            "n_determinizations": self.N_DETERMINIZATIONS,
            "confidence_override": self.CONFIDENCE_OVERRIDE,
            "adaptive_allocation": self.ADAPTIVE_ALLOCATION,
            "random_allocation": self.RANDOM_ALLOCATION,
            "margin": margin,
            "z": self.CONFIDENCE_Z,
            "report_rule": self.REPORT_RULE,
            "report_min_gain": self.REPORT_MIN_GAIN,
            "report_worlds_requested": self.REPORT_FOLD_WORLDS,
            "report_alpha": self.REPORT_ALPHA,
            "seed": self.seed,
            "rng_state": pre_rng_state,
            "report_seed": report_seed,
            "allocation_seed": allocation_seed,
            "eligible_indices": list(eligible),
            "candidates": [list(c) for c in candidates],
            "means": list(means),
            "n_by_candidate": list(n_by),
            "paired_se": [self._paired_se(d_sum[i], d_sq[i], n_by[i])
                          for i in range(len(candidates))],
            "raw_winner_index": best,
            "report_candidate_index": challenger,
            "worlds": n_worlds,
            "alloc": self.last_alloc,
            "work": {
                "selection_budget": int(self.last_alloc["budget"]),
                "selection_rollouts": selection_rollouts,
                "report_budget": 2 * self.REPORT_FOLD_WORLDS,
                "report_rollouts": 0,
                "total_budget": (int(self.last_alloc["budget"])
                                 + 2 * self.REPORT_FOLD_WORLDS),
                "total_rollouts": selection_rollouts,
            },
        }
        if self.last_alloc.get("short") or n_worlds == 0:
            if n_worlds == 0:
                self.zero_world_decisions += 1
            self.short_search_decisions += 1
            return self._finish_decision(
                candidates, 0, "selection_underfilled", _t0, sampler_before)

        if self.REPORT_FOLD_WORLDS:
            if challenger is None:
                # Defensive: adaptive keeps one challenger, and every uniform
                # contested ballot has one. Refuse instead of fabricating work.
                self.short_search_decisions += 1
                return self._finish_decision(
                    candidates, 0, "no_report_challenger", _t0, sampler_before)
            report = self._report_fold_gap(
                rnd, seat, mem, i_attack, candidates[challenger], candidates[0],
                self.REPORT_FOLD_WORLDS, seed=report_seed)
            report_rollouts = 2 * report["worlds"]
            self.rollouts += report_rollouts
            self.last_decision_record["work"]["report_rollouts"] = report_rollouts
            self.last_decision_record["work"]["total_rollouts"] += report_rollouts
            critical = statistic = None
            if report["complete"]:
                critical = (0.0 if self.REPORT_RULE == "mean"
                            else self._report_critical(report["worlds"]))
                statistic = report["gap"] - critical * report["se"]
            self.last_override_stats = {
                **report, "fold": "report", "rule": self.REPORT_RULE,
                "critical": critical, "statistic": statistic,
                "min_gain": self.REPORT_MIN_GAIN,
                "bound": ("paired_mean" if self.REPORT_RULE == "mean" else
                          "paired_student_t_one_sided_95_conservative_df>=29"),
            }
            self.last_decision_record["report_fold"] = self.last_override_stats
            if not report["complete"]:
                self.short_search_decisions += 1
                return self._finish_decision(
                    candidates, 0, "report_underfilled", _t0, sampler_before)
            if statistic < self.REPORT_MIN_GAIN:
                return self._finish_decision(
                    candidates, 0, f"report_{self.REPORT_RULE}_below_min_gain",
                    _t0, sampler_before)
            return self._finish_decision(
                candidates, challenger, f"report_{self.REPORT_RULE}_override",
                _t0, sampler_before)

        if best != 0:
            # PAIRED gap, from the same worlds the SE is computed on.
            # `means[best] - means[0]` mixes subsets: under adaptive allocation
            # a pruned-then-revived candidate covers fewer worlds than the
            # never-pruned candidate 0, so that difference is biased while its
            # SE uses only the overlap — comparing two different quantities
            # (Codex). `d_sum[best]/n_by[best]` is the mean of per-world
            # differences on worlds where BOTH were evaluated.
            gap = (d_sum[best] / n_by[best]) if n_by[best] else 0.0
            if self.CONFIDENCE_OVERRIDE:
                # Require the paired LOWER CONFIDENCE BOUND to clear the
                # margin, not the point estimate. This is what the fixed
                # margin could not do: distinguish "genuinely better" from
                # "ahead on a lucky draw".
                se = self._paired_se(d_sum[best], d_sq[best], n_by[best])
                self.last_override_stats = {
                    "gap": gap, "se": se, "n_worlds": n_worlds,
                    "lcb": gap - self.CONFIDENCE_Z * se, "margin": margin,
                    "candidate": list(candidates[best]),
                    "candidate0": list(candidates[0]),
                }
                if gap - self.CONFIDENCE_Z * se < margin:
                    return self._finish_decision(
                        candidates, 0, "lcb_below_margin", _t0, sampler_before)
            elif gap < margin:
                return self._finish_decision(
                    candidates, 0, "below_fixed_margin", _t0, sampler_before)
        return self._finish_decision(
            candidates, best, "search_override" if best != 0 else
            "candidate0_best", _t0, sampler_before)

    def _pick_index(self, candidates, means, indices):
        """Argmax with the production point-shy tie-break, over `indices`."""
        from ..engine.cards import points as _pts

        indices = list(indices)
        if not indices:
            raise ValueError("cannot choose from an empty candidate set")
        best = max(indices, key=lambda i: means[i])
        close = [i for i in indices
                 if means[best] - means[i] <= self.POINT_SHY_EPS]
        return min(close, key=lambda i: (sum(_pts(c) for c in candidates[i]),
                                         -means[i]))

    def _finish_decision(self, candidates, played_index, reason, started,
                         sampler_before):
        """Finalize observability and timing exactly once for every search."""
        elapsed = time.perf_counter() - started
        self.search_secs += elapsed
        self._finalise_record(candidates, played_index, reason)
        rec = self.last_decision_record
        if rec is not None:
            rec["search_secs"] = elapsed
            rec["sampler_counters"] = {
                "before": sampler_before,
                "after": self._sampler_snapshot(),
                "delta": self._sampler_delta(sampler_before),
            }
            work = rec["work"]
            work["complete"] = work["total_rollouts"] == work["total_budget"]
        return candidates[played_index]

    def _finalise_record(self, candidates, played_index, reason):
        """Stamp the ACTUAL played move on the record, after all fallbacks.

        `raw_winner_index` is the search's argmax; the move finally returned can
        differ because of the margin/confidence fallback. Logging only the
        former let the record name an alternative the bot never played (Codex).
        """
        rec = self.last_decision_record
        if rec is None:
            return
        rec["played_index"] = played_index
        rec["played"] = list(candidates[played_index])
        rec["reason"] = reason

    def _sampler_snapshot(self) -> dict[str, int]:
        return {name: int(getattr(self, name, 0)) for name in (
            "sample_attempts", "accepted_worlds", "failed_worlds",
            "rejected_worlds", "impossible_worlds")}

    def _sampler_delta(self, before) -> dict[str, int]:
        after = self._sampler_snapshot()
        return {name: after[name] - before[name] for name in after}

    def structured_bury_telemetry(self) -> dict[str, int | str | bool]:
        """Return fail-closed cumulative S3a dose and exact-work telemetry.

        This is deliberately separate from :func:`evaluation.counters`: frozen
        evidence protocols require that shared counter object to retain its
        exact schema.  A future S3a duel can explicitly opt into this record.
        """
        totals = dict(self._structured_bury_totals)
        problems = []
        if set(totals) != set(STRUCTURED_BURY_TELEMETRY_FIELDS):
            problems.append("field population")
        elif any(isinstance(value, bool) or not isinstance(value, int)
                 or value < 0 for value in totals.values()):
            problems.append("non-negative integer fields")
        else:
            if totals["triggers"] != totals["searches"]:
                problems.append("triggers != searches")
            if totals["searches"] != (totals["complete_searches"] +
                                      totals["short_searches"]):
                problems.append("search completion accounting")
            if totals["triggers"] > totals["opportunities"]:
                problems.append("triggers exceed opportunities")
            if not (totals["opportunities"] <=
                    totals["candidate_count_sum"] <=
                    totals["opportunities"] * self.BURY_MAX_CANDIDATES):
                problems.append("candidate-count accounting")
            if totals["overrides"] > totals["complete_searches"]:
                problems.append("overrides exceed complete searches")
            if totals["zero_world_searches"] > totals["short_searches"]:
                problems.append("zero-world searches exceed short searches")
            if totals["worlds_used"] > totals["worlds_requested"]:
                problems.append("used worlds exceed requested worlds")
            if totals["candidate_rollouts"] > \
                    totals["candidate_world_budget"]:
                problems.append("candidate rollouts exceed requested work")
            if totals["sample_attempts"] != (totals["accepted_worlds"] +
                                              totals["failed_worlds"]):
                problems.append("sampler attempts do not reconcile")
            if totals["accepted_worlds"] != totals["worlds_used"]:
                problems.append("accepted worlds != scored worlds")
            if totals["rejected_worlds"] > totals["failed_worlds"]:
                problems.append("rejected worlds exceed failed worlds")
            if (totals["short_searches"] == 0 and
                    totals["candidate_rollouts"] !=
                    totals["candidate_world_budget"]):
                problems.append("complete treatment underfilled exact work")
        if problems:
            raise AssertionError(
                "structured bury telemetry failed closed: " +
                "; ".join(problems))
        return {
            "schema": "structured-bury-cumulative-telemetry-v1",
            **totals,
            "exact_work_complete": (
                totals["short_searches"] == 0 and
                totals["candidate_rollouts"] ==
                totals["candidate_world_budget"]),
        }

    def _record_structured_bury_telemetry(self, record: dict) -> None:
        """Validate and add one completed structured-bury opportunity."""
        if record.get("schema") != "structured-bury-search-v1":
            raise AssertionError("structured bury telemetry received wrong schema")
        candidate_count = record.get("candidate_count")
        played_index = record.get("played_index")
        work = record.get("work", {})
        sampler = record.get("sampler_counters", {}).get("delta", {})
        required_work = {
            "worlds_requested", "worlds_used", "candidate_rollouts", "complete"}
        if (isinstance(candidate_count, bool) or
                not isinstance(candidate_count, int) or
                not 1 <= candidate_count <= self.BURY_MAX_CANDIDATES or
                isinstance(played_index, bool) or
                not isinstance(played_index, int) or
                not 0 <= played_index < candidate_count or
                not required_work.issubset(work) or
                set(sampler) != {"sample_attempts", "accepted_worlds",
                                 "failed_worlds", "rejected_worlds",
                                 "impossible_worlds"}):
            raise AssertionError("structured bury telemetry record shape")
        numeric_work = (
            work["worlds_requested"], work["worlds_used"],
            work["candidate_rollouts"],
        )
        if any(isinstance(value, bool) or not isinstance(value, int) or value < 0
               for value in (*numeric_work, *sampler.values())):
            raise AssertionError("structured bury telemetry non-integer work")
        requested, used, rollouts = numeric_work
        complete = work["complete"]
        triggered = candidate_count > 1
        expected_budget = requested * candidate_count
        if (complete is not (used == requested) or used > requested or
                rollouts != used * candidate_count or
                sampler["sample_attempts"] !=
                sampler["accepted_worlds"] + sampler["failed_worlds"] or
                sampler["accepted_worlds"] != used or
                sampler["rejected_worlds"] > sampler["failed_worlds"] or
                (not triggered and (requested or used or rollouts or
                                    sampler["sample_attempts"])) or
                (triggered and requested <= 0)):
            raise AssertionError("structured bury telemetry work does not reconcile")
        short = triggered and not complete
        if short != (record.get("reason") == "bury_search_underfilled"):
            raise AssertionError("structured bury telemetry fallback reason drift")

        delta = {
            "opportunities": 1,
            "triggers": int(triggered),
            "overrides": int(played_index != 0),
            "candidate_count_sum": candidate_count,
            "searches": int(triggered),
            "complete_searches": int(triggered and complete),
            "short_searches": int(short),
            "zero_world_searches": int(short and used == 0),
            "worlds_requested": requested,
            "worlds_used": used,
            "candidate_world_budget": expected_budget,
            "candidate_rollouts": rollouts,
            **sampler,
        }
        for name in STRUCTURED_BURY_TELEMETRY_FIELDS:
            self._structured_bury_totals[name] += delta[name]
        record["cumulative_telemetry"] = self.structured_bury_telemetry()

    def _report_critical(self, n: int) -> float:
        if self.REPORT_ALPHA != 0.05:
            raise ValueError("S0 v1 registers only one-sided alpha=0.05")
        if n < 30:
            return float("inf")
        return self.REPORT_T_CRITICAL

    def _report_fold_gap(self, rnd, seat, mem, i_attack, cand_a, cand_b, n,
                         *, seed: int, keep_deltas: bool = False):
        """Paired gap and SE for A vs B on FRESH worlds, on the same draws.

        Selecting the empirical winner among K candidates and then bounding it
        on the SAME worlds is not 95% coverage for the selected maximum — the
        winner's curse (Codex). Evaluating the chosen pair on a DISJOINT report
        fold makes the bound valid without inventing a simultaneous family: the
        report worlds took no part in selection. Both candidates see identical
        worlds, so the pairing is exact rather than an overlap approximation.
        """
        d_sum = d_sq = 0.0
        deltas = []
        used = 0
        attempts = 0
        cap = n * self.SAMPLE_ATTEMPT_FACTOR
        original_rng = self.rng
        try:
            self.rng = random.Random(seed)
            while used < n and attempts < cap:
                attempts += 1
                sampled = self._sample_hands(rnd, seat, mem)
                if sampled is None:
                    continue
                hands, buried = sampled
                exact_session = self._new_exact_world_session(rnd, buried)
                world = self._prepare_play_world(
                    rnd, seat, hands, buried=buried)
                va = self._score(self._rollout(rnd, seat, world, buried,
                                               list(cand_a),
                                               exact_session=exact_session))
                vb = self._score(self._rollout(rnd, seat, world, buried,
                                               list(cand_b),
                                               exact_session=exact_session))
                if not i_attack:
                    va, vb = -va, -vb
                delta = va - vb
                d_sum += delta
                d_sq += delta * delta
                if keep_deltas:
                    deltas.append(delta)
                used += 1
        finally:
            self.rng = original_rng
        mean = d_sum / used if used else 0.0
        out = {
            "gap": mean,
            "se": self._paired_se(d_sum, d_sq, used),
            "worlds": used,
            "attempts": attempts,
            "rejected": attempts - used,
            "complete": used == n,
            "seed": seed,
        }
        if keep_deltas:
            out["deltas"] = deltas
        return out

    def _decide_adaptive(self, rnd, seat, candidates, mem, i_attack,
                         *, allocation_rng):
        """Fixed-budget adaptive allocation (S0 item 2).

        Uniform search spends `N x K` candidate-worlds evenly, so every
        candidate — including obvious losers — gets the same precision, and the
        contenders that actually decide the move stay noisy. That noise is what
        the fixed margin mistook for evidence in the sanitised incident.

        Same total work, spent differently: evaluate everyone on a common
        prefix, drop candidates whose UPPER bound is already below the leader's
        LOWER bound, then buy more shared worlds for whoever is left. Candidate
        0 is never pruned — it is the pairing baseline and the incumbent.

        Returns (totals, d_sum, d_sq, n_by_cand, worlds_used, rollouts).
        """
        K = len(candidates)
        budget = self.N_DETERMINIZATIONS * K        # identical to uniform cost
        totals = [0.0] * K
        d_sum = [0.0] * K
        d_sq = [0.0] * K
        n_by = [0] * K
        # Direct paired moments for candidate i - candidate j on worlds where
        # both were alive. Pruning no longer manufactures a leader bound by
        # adding two candidate-vs-zero SEs and ignoring their covariance.
        pair_sum = [[0.0] * K for _ in range(K)]
        pair_sq = [[0.0] * K for _ in range(K)]
        pair_n = [[0] * K for _ in range(K)]
        alive = list(range(K))
        rollouts = 0
        worlds = 0
        seed_batch = max(4, self.N_DETERMINIZATIONS // 4)
        prune_log = []

        attempts = 0
        max_attempts = budget * self.SAMPLE_ATTEMPT_FACTOR
        while rollouts + len(alive) <= budget:
            if attempts >= max_attempts:
                # A repeatedly-failing sampler advances neither `rollouts` nor
                # the loop, so this spun forever rather than failing (Codex).
                break
            attempts += 1
            sampled = self._sample_hands(rnd, seat, mem)
            if sampled is None:
                continue
            hands, buried = sampled
            exact_session = self._new_exact_world_session(rnd, buried)
            world = self._prepare_play_world(
                rnd, seat, hands, buried=buried)
            worlds += 1
            vals = {}
            for i in alive:
                v = self._score(self._rollout(rnd, seat, world, buried,
                                              candidates[i],
                                              exact_session=exact_session))
                v = v if i_attack else -v
                vals[i] = v
                totals[i] += v
                n_by[i] += 1
            rollouts += len(alive)
            base = vals.get(0)
            if base is not None:
                for i, v in vals.items():
                    d = v - base
                    d_sum[i] += d
                    d_sq[i] += d * d
            for i, vi in vals.items():
                for j, vj in vals.items():
                    delta = vi - vj
                    pair_sum[i][j] += delta
                    pair_sq[i][j] += delta * delta
                    pair_n[i][j] += 1
            # prune only after a stable prefix, and never candidate 0
            if worlds >= seed_batch and len(alive) > 2:
                means = {i: totals[i] / n_by[i] for i in alive}
                # Preserve one nonzero challenger even when candidate 0 leads,
                # so the fixed report fold always has a nominated pair.
                lead = max((i for i in alive if i != 0), key=means.get)
                keep = []
                for i in alive:
                    if i in (0, lead):
                        keep.append(i)
                        continue
                    overlap = pair_n[i][lead]
                    direct_gap = (pair_sum[i][lead] / overlap
                                  if overlap else float("-inf"))
                    direct_se = self._paired_se(
                        pair_sum[i][lead], pair_sq[i][lead], overlap)
                    if direct_gap + self.CONFIDENCE_Z * direct_se < 0:
                        continue        # upper bound below the leader's lower
                    keep.append(i)
                deterministic_keep = list(keep)
                if self.RANDOM_ALLOCATION:
                    # Same survivor COUNT and exact total work, random survivor
                    # identities. A named child RNG keeps sampling worlds on the
                    # same stream rather than advancing it to shuffle arms.
                    take = max(1, len(keep) - 1)
                    pool = [i for i in alive if i != 0]
                    keep = [0] + allocation_rng.sample(pool, min(take, len(pool)))
                    keep.sort()
                if set(keep) != set(alive):
                    prune_log.append({
                        "world": worlds, "leader": lead,
                        "deterministic_survivors": deterministic_keep,
                        "survivors": list(keep),
                    })
                alive = keep

        # The old loop stranded `budget - rollouts` whenever fewer than one
        # survivor batch remained. Execute that <len(alive) residual as explicit
        # dummy work, excluded from all estimates, so every successful decision
        # consumes exactly N*K candidate rollouts.
        dummy_rollouts = 0
        residual = budget - rollouts
        while residual and attempts < max_attempts:
            attempts += 1
            sampled = self._sample_hands(rnd, seat, mem)
            if sampled is None:
                continue
            hands, buried = sampled
            exact_session = self._new_exact_world_session(rnd, buried)
            world = self._prepare_play_world(
                rnd, seat, hands, buried=buried)
            for i in alive[:residual]:
                self._score(self._rollout(rnd, seat, world, buried,
                                          candidates[i],
                                          exact_session=exact_session))
                dummy_rollouts += 1
            rollouts += dummy_rollouts
            residual = 0

        short = rollouts != budget
        self.last_alloc = {
            "mode": "random_adaptive" if self.RANDOM_ALLOCATION else
                    "deterministic_adaptive",
            "attempts": attempts, "attempt_cap": max_attempts,
            "attempt_cap_hit": attempts >= max_attempts and short,
            "worlds": worlds, "rollouts": rollouts,
            "decision_rollouts": rollouts - dummy_rollouts,
            "dummy_rollouts": dummy_rollouts,
            "budget": budget, "short": short,
            "survivors": len(alive), "survivor_indices": list(alive),
            "n_by_candidate": list(n_by), "prunes": prune_log,
        }
        return totals, d_sum, d_sq, n_by, worlds, rollouts

    @staticmethod
    def _paired_se(d_sum: float, d_sq: float, n: int) -> float:
        """SE of the paired mean difference. Zero variance -> zero SE."""
        if n < 2:
            return float("inf")
        mean = d_sum / n
        var = max(0.0, d_sq / n - mean * mean) * n / (n - 1)
        return (var / n) ** 0.5

    def _score(self, attacker_pts: float) -> float:
        """Rollout value from the attackers' perspective.

        With LEVEL_OBJECTIVE, points map to the scoring brackets that decide
        the round (0 / <40 / <80 / 80+ / 120+ / ...) plus a half-bracket for
        seizing or keeping the deal, scaled x40 so MARGIN stays comparable;
        a small points term breaks ties within a bracket."""
        p = attacker_pts
        if not self.LEVEL_OBJECTIVE:
            return float(p)
        if p >= 80:
            bracket, deal = min(3, int(p - 80) // 40), 0.5
        elif p == 0:
            bracket, deal = -3, -0.5
        else:
            bracket, deal = -(1 + int(79 - p) // 40), -0.5
        return 40.0 * (bracket + deal) + 0.2 * p

    # ------------------------------------------------------------------- bury
    def decide_bury(self, rnd: Round, seat: int) -> list[str]:
        self.last_bury_record = None
        base = super().decide_bury(rnd, seat)
        if not self.MC_BURY:
            return base
        ballot_record = None
        if self.STRUCTURED_BURY:
            # Candidate zero is the literal action of the named base policy on
            # this exact engine state.  Canonicalising the hand here silently
            # changed SmartBot's bury on permutation-sensitive states, so the
            # old feature-on path bundled a second treatment that the S3a screen
            # never evaluated.
            ballot = self._structured_bury_ballot(rnd, seat, base)
            cands = [list(candidate.cards) for candidate in ballot.candidates]
            ballot_record = ballot.record()
            if len(cands) > self.BURY_MAX_CANDIDATES:
                raise AssertionError("structured bury source exceeded candidate cap")
        else:
            cands = [base]
            for variant in (_BuryLoose(), _BuryStrict(), _BuryNoVoid()):
                c = variant.decide_bury(rnd, seat)
                if not any(sorted(c) == sorted(x) for x in cands):
                    cands.append(c)
        if len(cands) == 1:
            if self.STRUCTURED_BURY:
                sampler = self._sampler_snapshot()
                self.last_bury_record = {
                    "schema": "structured-bury-search-v1",
                    "policy": getattr(self, "policy_name", type(self).__name__),
                    "mode": "structured",
                    "ballot": ballot_record,
                    "candidate_count": 1,
                    "incumbent_index": 0,
                    "candidates": [{
                        **ballot_record["candidates"][0],
                        "index": 0,
                        "mean_banker_value": None,
                        "worlds": 0,
                    }],
                    "raw_winner_index": 0,
                    "played_index": 0,
                    "played": list(cands[0]),
                    "reason": "only_incumbent",
                    "common_worlds": True,
                    "n_by_candidate": [0],
                    "margin": self.MARGIN,
                    "gap_vs_incumbent": None,
                    "search_secs": 0.0,
                    "work": {"cap": self.BURY_MAX_ROLLOUTS,
                             "worlds_requested": 0, "worlds_used": 0,
                             "attempts": 0, "attempt_cap": 0,
                             "candidate_rollouts": 0, "complete": True},
                    "sampler_counters": {
                        "before": sampler, "after": sampler,
                        "delta": {name: 0 for name in sampler},
                    },
                }
                self._record_structured_bury_telemetry(self.last_bury_record)
            return base

        if self.STRUCTURED_BURY:
            if self.N_BURY_WORLDS <= 0:
                raise ValueError("N_BURY_WORLDS must be positive")
            if self.BURY_MAX_ROLLOUTS < len(cands):
                raise ValueError(
                    "BURY_MAX_ROLLOUTS must fund at least one common world "
                    "for every structured candidate")
            worlds_requested = min(
                self.N_BURY_WORLDS,
                self.BURY_MAX_ROLLOUTS // len(cands),
            )
            attempt_cap = (worlds_requested * self.SAMPLE_ATTEMPT_FACTOR
                           if self.BURY_REQUIRE_EXACT_WORK else
                           worlds_requested)
        else:
            worlds_requested = self.N_BURY_WORLDS
            attempt_cap = worlds_requested

        self.search_calls += 1
        self.bury_search_calls += 1
        started = time.perf_counter()
        pre_rng_state = self.rng.getstate()
        sampler_before = self._sampler_snapshot()
        mem = Memory(rnd, seat, own_kitty=getattr(self, 'BANKER_KITTY', True))
        totals = [0.0] * len(cands)
        n_worlds = 0
        attempts = 0
        while n_worlds < worlds_requested and attempts < attempt_cap:
            attempts += 1
            sampled = self._sample_hands(rnd, seat, mem)
            if sampled is None:
                continue
            n_worlds += 1
            hands, _ = sampled
            world = self._prepare_bury_world(
                rnd, seat, hands, buried=[])
            for i, cand in enumerate(cands):
                # banker's perspective: minimize the attackers' value
                totals[i] -= self._score(
                    self._rollout_from_bury(rnd, seat, world, cand))
        rollouts = n_worlds * len(cands)
        if self.STRUCTURED_BURY and rollouts > self.BURY_MAX_ROLLOUTS:
            raise AssertionError("structured bury scorer exceeded work cap")
        elapsed = time.perf_counter() - started
        self.rollouts += rollouts
        self.bury_rollouts += rollouts
        self.search_secs += elapsed
        self.bury_search_secs += elapsed
        complete = n_worlds == worlds_requested
        means = ([value / n_worlds for value in totals]
                 if n_worlds else [None] * len(cands))
        raw_best = (max(range(len(cands)), key=lambda i: totals[i])
                    if n_worlds else 0)
        played_index = raw_best
        reason = "bury_search_best"
        gap = (means[raw_best] - means[0]) if n_worlds else None
        if not complete:
            self.short_search_decisions += 1
            self.bury_short_searches += 1
            if n_worlds == 0:
                self.zero_world_decisions += 1
            played_index = 0
            reason = "bury_search_underfilled"
        elif raw_best != 0 and gap < self.MARGIN:
            played_index = 0
            reason = "bury_below_fixed_margin"
        elif raw_best == 0:
            reason = "bury_incumbent_best"

        candidates_record = []
        source_candidates = (ballot_record["candidates"]
                             if ballot_record is not None else
                             [{"cards": list(candidate),
                               "sources": ["legacy"]}
                              for candidate in cands])
        for i, candidate in enumerate(source_candidates):
            candidates_record.append({
                **candidate,
                "index": i,
                "mean_banker_value": means[i],
                "worlds": n_worlds,
            })
        self.last_bury_record = {
            "schema": ("structured-bury-search-v1" if self.STRUCTURED_BURY
                       else "legacy-bury-search-v1"),
            "policy": getattr(self, "policy_name", type(self).__name__),
            "mode": "structured" if self.STRUCTURED_BURY else "legacy",
            "rng_state": pre_rng_state,
            "candidate_count": len(cands),
            "incumbent_index": 0,
            "candidates": candidates_record,
            "ballot": ballot_record,
            "common_worlds": True,
            "n_by_candidate": [n_worlds] * len(cands),
            "raw_winner_index": raw_best,
            "played_index": played_index,
            "played": list(cands[played_index]),
            "reason": reason,
            "margin": self.MARGIN,
            "gap_vs_incumbent": gap,
            "search_secs": elapsed,
            "work": {
                "cap": (self.BURY_MAX_ROLLOUTS if self.STRUCTURED_BURY else
                        self.N_BURY_WORLDS * len(cands)),
                "worlds_requested": worlds_requested,
                "worlds_used": n_worlds,
                "attempts": attempts,
                "attempt_cap": attempt_cap,
                "candidate_rollouts": rollouts,
                "complete": complete,
            },
            "sampler_counters": {
                "before": sampler_before,
                "after": self._sampler_snapshot(),
                "delta": self._sampler_delta(sampler_before),
            },
        }
        if self.STRUCTURED_BURY:
            self._record_structured_bury_telemetry(self.last_bury_record)
        return cands[played_index]

    def _canonical_bury(self, rnd: Round, seat: int) -> list[str]:
        saved = rnd.hands[seat]
        rnd.hands[seat] = sorted(saved)
        try:
            return sorted(super().decide_bury(rnd, seat))
        finally:
            rnd.hands[seat] = saved

    def _structured_bury_ballot(self, rnd: Round, seat: int, incumbent):
        """Pure source boundary: own hand + public ordering, no hidden hands."""
        from .bury import structured_bury_ballot

        assert rnd.ordering is not None
        if rnd.phase != "bury" or seat != rnd.banker:
            raise ValueError("structured bury may run only for the banker in bury phase")
        return structured_bury_ballot(
            rnd.hands[seat], rnd.ordering, incumbent,
            max_candidates=self.BURY_MAX_CANDIDATES,
        )

    def _rollout_from_bury(self, rnd: Round, seat: int,
                           sampled: dict[int, list[str]] |
                           _CanonicalDeterminization,
                           bury_cards: list[str]) -> float:
        clone: Round = copy.copy(rnd)
        # A determinization is a CARD MULTISET per seat.  The sampler's list
        # order is incidental, but HeuristicBot walks hands in list order.  A
        # rollout therefore used to assign different values to the same world
        # after nothing more than a hand permutation, and one changed value
        # was enough to flip MC's argmax.  Canonicalise at the rollout-policy
        # boundary so every continuation sees one representation of a world.
        clone.hands = self._fresh_determinized_hands(
            rnd, seat, sampled, buried=[])
        clone.buried = []
        clone.trick = None
        clone.last_trick = None
        clone.history = []
        clone.message = None
        clone.bury(seat, list(bury_cards))
        clone._determinized_world = True
        policy = self.rollout_policy
        while clone.phase == "play":
            # A bury candidate changes the terminal kitty context, so it may
            # not share an exact cache with another bury candidate.
            exact = self._exact_endgame_value(clone)
            if exact is not None:
                return exact
            s = clone.turn
            assert s is not None
            clone.play(s, policy.decide_play(clone, s))
        return float(clone.attacker_points)

    def _complete_determinized_hands(self, rnd: Round, seat: int,
                                     sampled: dict[int, list[str]], *,
                                     buried: list[str]) -> list[list[str]]:
        """Validate a sampled world without ever falling back to live hands."""
        expected = {other for other in range(4) if other != seat}
        if set(sampled) != expected:
            raise DeterminizationContractError(
                f"sampled hand keys {sorted(sampled)} != opponents "
                f"{sorted(expected)}")
        for other in expected:
            if len(sampled[other]) != len(rnd.hands[other]):
                raise DeterminizationContractError(
                    f"sampled seat {other} has {len(sampled[other])} cards, "
                    f"expected {len(rnd.hands[other])}")
        hands = [sorted(rnd.hands[seat]) if current == seat
                 else sorted(sampled[current]) for current in range(4)]
        played = []
        for trick in rnd.history:
            for play in trick.plays:
                played.extend(play.cards)
        if rnd.trick is not None:
            for play in rnd.trick.plays:
                played.extend(play.cards)
        observed = Counter(played)
        observed.update(buried)
        for hand in hands:
            observed.update(hand)
        deck = Counter(rnd.deck)
        if observed != deck:
            missing = deck - observed
            extra = observed - deck
            raise DeterminizationContractError(
                "sampled world violates card conservation: "
                f"missing={dict(sorted(missing.items()))}, "
                f"extra={dict(sorted(extra.items()))}")
        return hands

    def _prepare_determinized_world(
            self, rnd: Round, seat: int, sampled: dict[int, list[str]], *,
            buried: list[str]) -> _CanonicalDeterminization:
        """Validate and canonicalise one accepted sampled world exactly once."""
        hands = self._complete_determinized_hands(
            rnd, seat, sampled, buried=buried)
        return _CanonicalDeterminization(
            hands=tuple(tuple(hand) for hand in hands),
            buried=tuple(sorted(buried)),
        )

    def _prepare_play_world(
            self, rnd: Round, seat: int, sampled: dict[int, list[str]], *,
            buried: list[str]) -> (dict[int, list[str]] |
                                    _CanonicalDeterminization):
        """Prepare worlds only for the canonical MCBot rollout boundary.

        Experimental subclasses and focused tests may replace ``_rollout``
        with a boundary that consumes the sampler mapping directly.  The old
        search loop passed that mapping through, so preserve that contract.
        """
        if getattr(self._rollout, "__func__", None) is not MCBot._rollout:
            return sampled
        return self._prepare_determinized_world(
            rnd, seat, sampled, buried=buried)

    def _prepare_bury_world(
            self, rnd: Round, seat: int, sampled: dict[int, list[str]], *,
            buried: list[str]) -> (dict[int, list[str]] |
                                    _CanonicalDeterminization):
        """Bury analogue of :meth:`_prepare_play_world`."""
        if getattr(self._rollout_from_bury, "__func__", None) is not \
                MCBot._rollout_from_bury:
            return sampled
        return self._prepare_determinized_world(
            rnd, seat, sampled, buried=buried)

    def _fresh_determinized_hands(
            self, rnd: Round, seat: int,
            sampled: dict[int, list[str]] | _CanonicalDeterminization, *,
            buried: list[str]) -> list[list[str]]:
        """Return non-aliased mutable hands for one rollout candidate.

        Direct/private callers that still supply the sampler mapping retain the
        original validate-on-every-call contract.  Search loops pass a prepared
        immutable world after validating it once.  This helper only copies its
        hands: ordinary-play ``_rollout`` reads the kitty context from the
        prepared world's immutable ``buried`` field, while a bury rollout
        deliberately begins before any cards have been buried.
        """
        if not isinstance(sampled, _CanonicalDeterminization):
            return self._complete_determinized_hands(
                rnd, seat, sampled, buried=buried)
        return [list(hand) for hand in sampled.hands]

    def _new_exact_world_session(self, rnd: Round, buried: list[str]):
        """Create one cache for one accepted ordinary-play determinization."""
        if not self.EXACT_ENDGAME:
            return None
        from .endgame import ExactWorldSession

        context = copy.copy(rnd)
        context.buried = sorted(buried)
        session = ExactWorldSession(
            context,
            max_hand_cards=self.EXACT_ENDGAME_MAX_CARDS,
            max_nodes=self.EXACT_ENDGAME_MAX_NODES,
        )
        self.exact_endgame_sessions += 1
        return session

    def _exact_endgame_value(self, clone: Round, session=None) -> float | None:
        """Solve one determinized continuation inside the proved S3b bound.

        This is called only on rollout clones whose four hands are known.  It
        must never be called on the live room state: doing so would let a bot
        inspect hidden hands.  A budget refusal propagates and invalidates an
        experimental run instead of silently mixing exact and heuristic work.
        """
        if not self.EXACT_ENDGAME or clone.phase != "play":
            return None
        if not getattr(clone, "_determinized_world", False):
            from .endgame import ExactEndgameRefusal
            raise ExactEndgameRefusal(
                "exact MC continuation requires a marked determinized world")
        if max((len(hand) for hand in clone.hands), default=0) > \
                self.EXACT_ENDGAME_MAX_CARDS:
            return None
        from .endgame import (ExactEndgameBudgetExceeded,
                              ExactEndgameRefusal, ExactWorldSession)

        if session is None:
            session = ExactWorldSession(
                clone,
                max_hand_cards=self.EXACT_ENDGAME_MAX_CARDS,
                max_nodes=self.EXACT_ENDGAME_MAX_NODES,
            )
            self.exact_endgame_sessions += 1
        self.exact_endgame_attempts += 1
        try:
            result = session.solve(clone)
        except ExactEndgameBudgetExceeded as exc:
            self.exact_endgame_refusals += 1
            self.exact_endgame_budget_exceeded += 1
            self.exact_endgame_nodes += exc.nodes
            self.exact_endgame_cache_hits += exc.cache_hits
            raise
        except ExactEndgameRefusal:
            self.exact_endgame_refusals += 1
            raise
        self.exact_endgame_calls += 1
        self.exact_endgame_nodes += result.nodes
        self.exact_endgame_cache_hits += result.cache_hits
        return float(result.attacker_points)

    # ------------------------------------------------------------- candidates
    def canonical_lead(self, rnd: Round, seat: int) -> list[str]:
        """SmartBot's lead pick, through the canonical hand order.

        THE shared boundary. `_lead` walks the hand, so its pick depended on
        list order; the TRACTOR_LOCK path in `decide_play` called it raw and
        therefore returned different leads for the same state. That is a
        PRODUCTION actor-distribution defect, not just a pilot one — a capture
        self-played through it inherits the wrong distribution (Codex).
        """
        saved = rnd.hands[seat]
        rnd.hands[seat] = sorted(saved)
        try:
            return sorted(self._lead(rnd, seat))
        finally:
            rnd.hands[seat] = saved

    def _candidates(self, rnd: Round, seat: int) -> list[list[str]]:
        """The ballot. CANONICALISED in the seat's hand order.

        Generation walks the hand and the caps truncate whatever was produced
        first, so the emitted ACTION SET depended on incidental list order —
        `D2` was offered under one ordering and `H2` under another, in roughly
        one lead state in six (found while building the pilot, 2026-08-05).
        Same class as the `decompose` order-dependence, one level up, and it
        put ballot noise into every measurement that used this ballot.

        The hand is sorted for the duration of generation and restored after,
        so every helper below — `_lead`, `_follow`, the throw builders — sees
        one canonical order without each needing to sort defensively.
        """
        o = rnd.ordering
        assert o is not None and rnd.trick is not None
        _saved_hand = rnd.hands[seat]
        rnd.hands[seat] = sorted(_saved_hand)
        try:
            return self._candidates_canonical(rnd, seat, o)
        finally:
            rnd.hands[seat] = _saved_hand

    def _candidates_canonical(self, rnd: Round, seat: int, o) -> list[list[str]]:
        hand = rnd.hands[seat]
        cands: list[list[str]] = []

        def add(play: list[str] | None) -> None:
            if not play:
                return
            key = tuple(sorted(play))
            if key in {tuple(sorted(c)) for c in cands}:
                return
            if rnd.trick.plays:
                try:
                    validate_follow(play, hand, rnd.trick.plays[0].cards, o)
                except IllegalPlay:
                    return
            cands.append(play)

        if not rnd.trick.plays:
            add(self._lead(rnd, seat))  # SmartBot's pick (throws included)
            if self.RISKY_THROWS or self.WIDE_LEAD_BALLOT:
                mem_ = Memory(rnd, seat, own_kitty=getattr(self, 'BANKER_KITTY', True))
                for t in self.near_boss_throws(rnd, seat, mem_):
                    add(t)  # sampled worlds price the beat risk + penalty
            if self.WIDE_LEAD_BALLOT:
                # JVRA 2026-08-02: ballot lacked trump pairs (♣A♣A/♣8♣8) —
                # sourcing gap, not judgment. Show rollouts EVERY pair,
                # tractor, and near-boss throw in every suit incl. trump;
                # the margin rule still shields the heuristic from noise.
                from ..engine.combos import find_tractor_runs
                for s in list(PLAIN_SUITS) + [TRUMP]:
                    cards = suit_cards(hand, s, o)
                    for length in range(6, 1, -1):
                        for run in find_tractor_runs(cards, o, length):
                            add(run)
                    for code, k in sorted(Counter(cards).items(),
                                          key=lambda e: -o.level(e[0])):
                        if k >= 2:
                            add([code, code])
                    if cards:
                        add([max(cards, key=o.level)])
            for s in PLAIN_SUITS:
                cards = suit_cards(hand, s, o)
                if not cards:
                    continue
                comps = decompose(cards, o).components
                paired = [c for c in comps if c.pair_len]
                if paired:
                    # list(): .cards aliases the decompose cache
                    add(list(max(paired, key=lambda c: (c.pair_len, c.top)).cards))
                # top single (the ace lead) must always be on the ballot
                add([max(cards, key=o.level)])
                add([self._lowest(cards, o, avoid_points=True)])
            trumps = suit_cards(hand, TRUMP, o)
            if trumps:
                add([self._lowest(trumps, o, avoid_points=True)])
                if self.TRUMP_BALLOT:
                    comps = decompose(trumps, o).components
                    paired = [c for c in comps if c.pair_len]
                    if paired:
                        add(list(max(paired, key=lambda c: (c.pair_len, c.top)).cards))
                    add([max(trumps, key=o.level)])  # boss/top trump drain
        else:
            add(self._follow(rnd, seat))  # SmartBot's pick
            lead = rnd.trick.plays[0].cards
            add(self._forced_follow(hand, lead, o, prefer_points=False))
            add(self._forced_follow(hand, lead, o, prefer_points=True))
            win_seat, inc_suit, inc_top = self._current_winner(rnd)
            add(self._cheapest_winning(hand, lead, inc_suit, inc_top, o))
            if self.WIDE_FOLLOW_BALLOT:
                # Every distinct-code follow (in-suit part maximal, as the
                # rules force), validated by add(); constructed seeds above
                # keep the known-good shapes ahead of the cap.
                from itertools import combinations
                suit = uniform_suit(lead, o)
                h_suit = suit_cards(hand, suit, o)
                n_suit = min(len(lead), len(h_suit))
                if n_suit == len(lead):
                    pool = {tuple(sorted(c))
                            for c in combinations(sorted(h_suit), n_suit)}
                else:
                    off = list(hand)
                    for c in h_suit:
                        off.remove(c)
                    base = tuple(sorted(h_suit))
                    pool = {base + tuple(sorted(c))
                            for c in combinations(sorted(off),
                                                  len(lead) - n_suit)}
                for cand in sorted(pool):
                    if len(cands) >= self.FOLLOW_MAX_CANDIDATES:
                        break
                    add(list(cand))
        if self.V3_LEAD_SINGLES and not rnd.trick.plays:
            # BALLOT V3, lead layer (Codex audit 2026-08-04). The deployed
            # ballot misses 15.5% of human LEADS — 55 of them middle-rank
            # singles — because per suit it only ever offers the top card and
            # the lowest non-point card. Everything in between is unreachable,
            # so no amount of search or learning can find it: race4 only
            # REMOVES from this list, and highn_build values only what is on
            # it.
            #
            # Offer one representative per DISTINCT effective level, which is
            # what "strategically distinct" means here — two cards of the same
            # level are interchangeable for the trick. The cap is unchanged, so
            # rollout cost is comparable; what changes is WHAT fills it.
            for suit in list(PLAIN_SUITS) + [TRUMP]:
                cards = suit_cards(hand, suit, o)
                # Equivalence must include what the play LEAVES BEHIND, not
                # just its immediate strength. Under trump rank 7, S7 and C7
                # tie in level, but from S7-S7-C7 leading S7 breaks the pair
                # while leading C7 keeps it — so "one representative per
                # effective level" silently dropped a materially different
                # action (Codex P0, reproduced 2026-08-04).
                seen_keys = set()
                order = sorted(cards, key=lambda x: -o.level(x))
                if self.V3_LEAD_RANDOM:
                    # CONTROL: fill the same slots with arbitrary legal
                    # singles, so "better sourcing helps" can be told apart
                    # from "a fuller ballot helps". Its RNG is SEPARATE from
                    # self.rng: sharing the stream would couple which actions
                    # are proposed to how worlds are sampled (Codex).
                    if not hasattr(self, "_proposal_rng"):
                        import random as _r
                        self._proposal_rng = _r.Random(
                            (self.rng.random() * 1e9).__int__() ^ 0xC0FFEE)
                    order = list(cards)
                    self._proposal_rng.shuffle(order)
                for c in order:
                    rest = list(cards)
                    rest.remove(c)
                    key = (o.level(c), decompose(rest, o).shape() if rest else ())
                    if key in seen_keys:
                        continue
                    seen_keys.add(key)
                    if len(cands) >= self.LEAD_MAX_CANDIDATES:
                        break
                    add([c])
        if (self.WIDE_LEAD_BALLOT or self.V3_LEAD_SINGLES) and not rnd.trick.plays:
            return cands[:self.LEAD_MAX_CANDIDATES]
        if self.WIDE_FOLLOW_BALLOT and rnd.trick.plays:
            return cands[:self.FOLLOW_MAX_CANDIDATES]
        return cands[:self.MAX_CANDIDATES]

    # ------------------------------------------------------------- sampling
    def _sample_hands(self, rnd: Round, seat: int, mem: Memory):
        """Deal unseen cards to the other three seats (+ hidden kitty when we
        aren't the banker), respecting hand sizes and observed voids.
        Returns (hands, buried) or None if sampling failed."""
        self.sample_attempts += 1
        o = rnd.ordering
        assert o is not None
        pool = list(mem.unseen.elements())
        if seat == rnd.banker:
            # Subtract our own burial only if Memory did not already exclude
            # it (own_kitty). Subtracting twice removes cards opponents
            # genuinely hold and no world can then be built.
            if not getattr(mem, "own_kitty_known", False):
                pool = list((Counter(pool) - Counter(rnd.buried)).elements())
            buried = list(rnd.buried)
            kitty_slots = 0
        else:
            buried = []
            kitty_slots = len(rnd.buried)

        others = [s for s in range(4) if s != seat]
        sizes = {s: len(rnd.hands[s]) for s in others}
        # Conservation invariant: the unseen pool must fill exactly the other
        # hands plus the hidden kitty. A silent mismatch here means every
        # world fails and search degrades to candidate 0 without a word.
        assert len(pool) == sum(sizes.values()) + kitty_slots, (
            f"unseen pool {len(pool)} != hands {sum(sizes.values())} + "
            f"kitty {kitty_slots} (seat {seat}, banker {rnd.banker})")
        # Pin the declarer's PUBLIC shown cards before anything else, so the
        # assignment below only has to place genuinely unknown cards (RTLT
        # incident: scattering a declared trump-rank pair across hands made
        # KK-pair leads look boss in most worlds).
        pinned: Counter[str] = Counter()
        pre: dict[int, list[str]] = {s: [] for s in others}
        if self.DECLARER_PIN:
            for code, (dseat, ncopies) in mem.known.items():
                if dseat in pre:
                    take = min(ncopies, sizes[dseat] - len(pre[dseat]))
                    for _ in range(take):
                        pre[dseat].append(code)
                        pinned[code] += 1
        free = list((Counter(pool) - pinned).elements())
        caps = {s: sizes[s] - len(pre[s]) for s in others}

        for attempt in range(self.SAMPLE_RETRIES):
            respect_voids = attempt < self.SAMPLE_RETRIES - 1
            got = self._assign(free, caps, kitty_slots, o, mem, pre,
                               respect_voids=respect_voids)
            if got is None:
                continue
            hands, kitty = got
            for s in others:
                hands[s] = pre[s] + hands[s]
            if not respect_voids:
                # This world was only buildable by IGNORING observed voids,
                # i.e. it is impossible given the play history.
                #
                # SHENGJI_REQUIRE_VOIDS makes this a hard constraint. A
                # constraint-correct world ALWAYS exists (the real deal is
                # one), so a failure under this flag is a defect in the
                # construction — not proof of impossibility, which is what I
                # wrongly concluded on 2026-08-04 (Codex).
                if os.environ.get("SHENGJI_REQUIRE_VOIDS"):
                    self.rejected_worlds += 1
                    self.failed_worlds += 1
                    return None
                self.impossible_worlds += 1
            self.accepted_worlds += 1
            return hands, (buried or kitty)
        self.failed_worlds += 1
        return None

    def _assign(self, cards, caps, kitty_slots, o, mem, pre, respect_voids=True):
        """Deal `cards` to seats + kitty without ever dead-ending.

        The previous version walked a shuffled pool and gave each card to a
        random seat that still had room. That is a greedy first-fit, and it
        FAILS on states where a feasible world plainly exists: place two
        off-suit cards early and the only seat that can legally take the next
        suit is already full. Those failures were not theoretical — 14 of them
        landed in the determinization confirmation blocks, each one forcing
        `PROTOCOL FAILURES` and invalidating the run they appeared in.

        The fix is to decide COUNTS before cards. There are at most five
        effective suits and four receivers, so the count matrix is tiny and can
        be searched exactly with randomized backtracking and forward checking:
        if any legal assignment exists, this finds one. Cards are only then
        distributed inside each suit, where pair caps apply.
        """
        by_suit: dict[str, list[str]] = {}
        for c in cards:
            by_suit.setdefault(o.eff_suit(c), []).append(c)

        seats = list(caps)
        recv = seats + ["kitty"]
        cap = dict(caps)
        cap["kitty"] = kitty_slots
        allowed = {
            u: [r for r in recv
                if r == "kitty" or not (respect_voids and u in mem.voids[r])]
            for u in by_suit
        }
        # Most-constrained suit first: fewest receivers, then most cards.
        order = sorted(by_suit,
                       key=lambda u: (len(allowed[u]), -len(by_suit[u]), u))
        counts: dict[str, dict] = {}
        rem = dict(cap)

        def place(i: int) -> bool:
            if i == len(order):
                return True
            u = order[i]
            need = len(by_suit[u])
            opts = [r for r in allowed[u] if rem[r] > 0]
            # Forward check: everything still unplaced must still fit.
            def feasible() -> bool:
                for j in range(i + 1, len(order)):
                    v = order[j]
                    if sum(rem[r] for r in allowed[v]) < len(by_suit[v]):
                        return False
                return True

            # PAIR-CAP FORWARD CHECK. The search previously forward-checked
            # VOIDS only, so it proposed count matrices no fill could satisfy
            # and the failure surfaced later as an exhausted card deal. A
            # receiver given `n` cards drawn from `d` distinct codes is FORCED
            # to hold at least `n - d` pairs, so `n - d > cap` is impossible
            # however the cards are shuffled. Example that produced a rejected
            # world at original:81002046:4 — 6 clubs over 4 codes (C10 and CQ
            # doubled), seat 2 void, kitty full, and pair_cap 0 everywhere: any
            # split handing one seat 5 clubs is dead on arrival, but `place`
            # could not see it and `_deal_suit` burned its retries discovering
            # it. This is a necessary condition and costs O(receivers).
            ncodes = len(set(by_suit[u]))
            caps_u = {r: (mem.max_pairs(r, u) if isinstance(r, int) else None)
                      for r in allowed[u]}

            def pair_feasible(split) -> bool:
                for r, n in split.items():
                    cap_r = caps_u.get(r)
                    if cap_r is not None and n - ncodes > cap_r:
                        return False
                return True

            for split in self._splits(need, opts, rem,
                                      cards=by_suit[u] if WEIGHTED_SPLITS else None):
                if not pair_feasible(split):
                    continue
                for r, n in split.items():
                    rem[r] -= n
                if feasible() and place(i + 1):
                    counts[u] = split
                    return True
                for r, n in split.items():
                    rem[r] += n
            return False

        if not place(0):
            self.reject_cause["no_void_assignment"] += 1
            return None

        # Counts are feasible for VOIDS; whether they are feasible for PAIR
        # CAPS depends on which specific cards land where, so a failure here is
        # a reason to redraw the cards, not to abandon the world.
        for _ in range(8):
            hands: dict[int, list[str]] = {s: [] for s in seats}
            kitty: list[str] = []
            ok = True
            for u, split in counts.items():
                # Work from an explicit REMAINING list and remove what is
                # taken. The previous version indexed into a shared list while
                # also writing slices back into it, and a swap left the taken
                # region stale — which dealt a third copy of a two-copy card.
                remaining = list(by_suit[u])
                self.rng.shuffle(remaining)
                for r, n in split.items():
                    # Seed the pair count with cards ALREADY pinned to this
                    # seat in this suit. The declarer pin runs before dealing,
                    # so a seat holding one declared copy could be handed the
                    # second and form a pair the history proves it cannot have
                    # — the two fixes never met. Found by certification against
                    # a rules-derived validator, not by the self-consistent
                    # tests, which is the whole reason Codex asked for it.
                    already = Counter(
                        c for c in pre.get(r, ()) if o.eff_suit(c) == u) \
                        if isinstance(r, int) else Counter()
                    chunk = self._deal_suit(remaining, n, r, u, mem, already)
                    if chunk is None:
                        ok = False
                        break
                    if r == "kitty":
                        kitty += chunk
                    else:
                        hands[r] += chunk
                if not ok:
                    break
            if ok:
                return hands, kitty
        self.reject_cause["pair_cap"] += 1
        return None

    @staticmethod
    def _fills(cards, split) -> int:
        """How many distinct card-assignments realise this count matrix.

        Two splits of six cards into 2/2/2 versus 6/0/0 are NOT equally likely
        worlds: the first admits far more completions. Sampling count matrices
        uniformly therefore under-weights balanced hands, which is the larger
        of the two named posterior biases. This counts the completions exactly
        by DP over CODES, so equal codes are not treated as distinguishable.
        """
        recv = [r for r in split]
        caps = tuple(split[r] for r in recv)
        codes = sorted(Counter(cards).items())
        from functools import lru_cache

        @lru_cache(maxsize=None)
        def rec(i, rem_caps):
            if i == len(codes):
                return 1 if not any(rem_caps) else 0
            _, m = codes[i]
            total = 0
            # distribute m identical copies over the receivers
            def dist(j, left, acc):
                nonlocal total
                if j == len(rem_caps):
                    if left == 0:
                        # PHYSICAL_FILLS: a multiset assignment giving receiver
                        # j exactly acc[j] copies of this code is realised by
                        # m!/prod(acc[j]!) distinct PHYSICAL deals, because the
                        # deck holds separate copies. Counting each multiset
                        # once targets a flat-over-multisets prior; the stated
                        # target is flat over DEALS. `AABB` split 2/2 is 3
                        # multisets but 6 deals (1/4/1), so the uncorrected
                        # count under-weights balanced hands even here, in the
                        # very function written to stop under-weighting them.
                        coef = 1
                        if PHYSICAL_FILLS:
                            coef = _fact(m)
                            for k in acc:
                                coef //= _fact(k)
                        total += coef * rec(i + 1, tuple(a - b for a, b in
                                                         zip(rem_caps, acc)))
                    return
                for k in range(min(left, rem_caps[j]) + 1):
                    dist(j + 1, left - k, acc + (k,))
            dist(0, m, ())
            return total

        return rec(0, caps)

    def _splits(self, need, opts, rem, cards=None):
        """EVERY distribution of `need` cards over `opts`, in random order.

        Drawing a bounded number of random splits made this a search that could
        fail while a legal assignment existed — 5 rejected worlds in 18k
        searches, small but the same class of defect as the greedy it replaced.
        Enumerating lazily costs nothing in the common case, because the first
        split that survives forward checking is almost always accepted; the
        completeness only does work in the constrained states where the old
        code gave up.
        """
        if not opts:
            if need == 0:
                yield {}
            return
        order = list(opts)
        self.rng.shuffle(order)

        def rec(i, left, acc):
            if i == len(order):
                if left == 0:
                    yield dict(acc)
                return
            r = order[i]
            room = min(rem[r], left)
            # Remaining capacity after this receiver, so impossible tails are
            # never explored.
            tail = sum(rem[x] for x in order[i + 1:])
            lo = max(0, left - tail)
            choices = list(range(lo, room + 1))
            self.rng.shuffle(choices)
            for n in choices:
                acc[r] = n
                yield from rec(i + 1, left - n, acc)
            acc.pop(r, None)

        if cards is None:
            yield from rec(0, need, {})
            return
        # WEIGHTED: enumerate every feasible split, weight each by the number
        # of card-assignments it admits, and sample proportionally. Yields in
        # weighted-random order so the caller's first accepted split is drawn
        # from the right distribution.
        all_splits = list(rec(0, need, {}))
        if not all_splits:
            return
        weights = [max(self._fills(cards, sp), 0) for sp in all_splits]
        if sum(weights) <= 0:
            yield from all_splits
            return
        pool = list(zip(all_splits, weights))
        while pool:
            tot = sum(w for _, w in pool)
            if tot <= 0:
                for sp, _ in pool:
                    yield sp
                return
            pick = self.rng.random() * tot
            acc = 0.0
            for idx, (sp, w) in enumerate(pool):
                acc += w
                if acc >= pick:
                    yield sp
                    pool.pop(idx)
                    break
            else:
                yield pool.pop()[0]

    def _deal_suit(self, remaining, n, r, suit, mem, already=None):
        """Remove and return `n` cards of one suit for one receiver.

        Honours `pair_cap`: the provable ceiling on how many pairs a seat can
        still hold in a suit — zero after failing to follow a PAIR lead, one
        after failing a tractor. Dealing them a pair anyway builds a world the
        play history has already ruled out. Nothing consumed this before;
        Codex raised it four times.

        Cards are REMOVED from `remaining`, so conservation is structural
        rather than something the index arithmetic has to get right.

        NOT named `_take`: HeuristicBot already defines one, and shadowing it
        from a subclass broke follow generation everywhere.
        """
        if n <= 0:
            return []
        is_seat = isinstance(r, int) and r != "kitty"
        cap = mem.max_pairs(r, suit) if is_seat else None
        run_cap = mem.max_run(r, suit) if is_seat else None
        if cap is None and run_cap is None:
            out = remaining[:n]
            del remaining[:n]
            return out
        # `held` starts from what is already pinned to this seat, so the cap
        # applies to the FULL hand rather than only to this deal.
        # Prefer distinct codes, so a capped seat is not handed a pair when an
        # alternative exists. Ties keep the shuffled order, so this stays a
        # random draw among the choices that respect the bound.
        out: list[str] = []
        held: Counter[str] = Counter(already or {})
        from ..engine.combos import decompose as _dec
        o = getattr(mem, "o", None)
        for _ in range(n):
            pick = None
            # UNIFORM among cap-respecting cards, rather than first-legal.
            # First-legal prefers distinct codes beyond what the caps require —
            # the second named posterior bias. Flagged so its contribution is
            # measurable separately from the split weighting.
            if UNIFORM_DEAL:
                elig = []
                for i, c in enumerate(remaining):
                    t = held + Counter([c])
                    if cap is not None and sum(v // 2 for v in t.values()) > cap:
                        continue
                    if run_cap is not None and o is not None and \
                            _dec(list(t.elements()), o).max_pair_run() > run_cap:
                        continue
                    elig.append(i)
                if not elig:
                    return None
                c = remaining.pop(self.rng.choice(elig))
                out.append(c)
                held[c] += 1
                continue
            for i, c in enumerate(remaining):
                trial = held + Counter([c])
                if cap is not None:
                    if sum(v // 2 for v in trial.values()) > cap:
                        continue
                if run_cap is not None and o is not None:
                    # A pair CAP is not a run cap: two non-consecutive pairs
                    # form no tractor, and a seat that failed a k-tractor
                    # obligation may still legally hold k-1 runs.
                    if _dec(list(trial.elements()), o).max_pair_run() > run_cap:
                        continue
                pick = i
                break
            if pick is None:
                return None
            c = remaining.pop(pick)
            out.append(c)
            held[c] += 1
        return out

    # -------------------------------------------------------------- rollout
    def _rollout(self, rnd: Round, seat: int,
                 sampled: dict[int, list[str]] | _CanonicalDeterminization,
                 buried: list[str], candidate: list[str], *,
                 exact_session=None) -> float:
        clone: Round = copy.copy(rnd)
        # Sampled hands represent multisets, not sequences.  HeuristicBot's
        # continuation policy is intentionally simple and walks a list, so it
        # must receive a canonical representation or `_rollout` is a function
        # of sampler insertion order rather than of the game state.
        if isinstance(sampled, _CanonicalDeterminization):
            clone.hands = [list(hand) for hand in sampled.hands]
            # A prepared world owns its validated kitty context.  Reading the
            # immutable binding is both safer and cheaper than sorting or
            # comparing the same burial once per candidate.
            clone.buried = list(sampled.buried)
        else:
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
        clone._trusted_rollout = True  # skip follow re-validation (audit)
        clone._determinized_world = True
        clone.play(seat, list(candidate))
        policy = self.rollout_policy
        while clone.phase == "play":
            exact = self._exact_endgame_value(clone, exact_session)
            if exact is not None:
                return exact
            s = clone.turn
            assert s is not None
            clone.play(s, policy.decide_play(clone, s))
        return float(clone.attacker_points)


class MCSmartRoll(MCBot):
    """MCBot with SmartBot (memory-aware) rollouts — ~5x slower/decision."""

    def __init__(self, seed: int | None = None):
        super().__init__(seed)
        self.rollout_policy = SmartBot()
