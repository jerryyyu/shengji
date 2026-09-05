"""Net-driven rollouts inside production's MC-LCB search (DEV, tier-i).

Production (``mc-s0-report-lcb``) values every (candidate, sampled world)
pair with ONE deterministic HEURISTIC continuation to round end and uses the
round's final attacker points as the value.  The search is compute-starved
(production +0.07 at 3x worlds, +0.10 at 30x), the one-ply net bot loses
(-0.11) for lack of depth, the value32 probe (+0.12) gained through a better
rollout POLICY, and the net's worst errors are trick mechanics.  So this
arm keeps everything of production -- ballot, world sampler, selection
stage, report fold with 2 x R worlds on the top two candidates, LCB rule,
``_score`` units -- and replaces only the rollout policy for the first ``K``
tricks of every continuation with the complete-world net.

Cost forces the shape.  One net play costs ~100 us (afterstate tensors ~50
us + forward ~30 us) against ~5 us for a heuristic play in the fast engine,
so calling the net per rollout is unaffordable.  :class:`MCNetRolloutSearch`
therefore simulates the rollouts of one candidate across ALL its worlds in
LOCKSTEP: at every ply of the first ``K`` tricks it collects each live
clone's mover and production's ballot for that seat in that world, builds
every (clone, candidate) afterstate, scores them all in ONE
``score_many`` batch from the MOVER's team perspective, and applies the
argmax in each clone.  After ``K`` tricks every clone is finished by the
heuristic exactly as ``MCBot._rollout`` finishes it; the value is the exact
final attacker points and goes through ``_score`` unchanged.

Where the lockstep replaces production's loop:

* ``net_stage="report"`` overrides ``_report_fold_gap`` only.  The worlds
  are drawn by the SAME calls in the SAME order as production (a child
  ``random.Random(seed)``, ``_sample_hands`` until ``n`` accepted worlds or
  the attempt cap, ``_prepare_report_world`` per accepted world), the two
  report candidates are simulated across all worlds, and the paired
  deltas, SE, gap, ``complete`` and attempt counts are computed with
  production's own arithmetic (``_score``, the attacker sign flip,
  ``_paired_se``); the LCB decision itself stays in ``decide_play``.
* ``net_stage="all"`` additionally routes the selection stage through
  ``_decide_adaptive`` (the only selection hook production exposes) with a
  UNIFORM, no-pruning lockstep allocation that draws production's uniform
  worlds (same budget, same attempt cap, same order) and reproduces the
  uniform loop's paired moments; the record's ``alloc.mode`` says so.

``K = 0`` runs the lockstep with no net ply and is byte-identical to
production (tested).  The NO-LEARNING control keeps the lockstep structure
and chooses each play by the stratified prior table (``pt0`` units, as
#229/#234's controls), so a learned-minus-control contrast isolates the
net from the structure.  A checkpoint without the afterstate-encoder
identity or another architecture than ``mlp`` is refused through
``cwv_policy``'s loaders.  Nothing here registers a production default.
"""
from __future__ import annotations

import copy
import os
import random
import time
from functools import lru_cache
from typing import Any, Mapping, Sequence

import numpy as np

from ..ai.cwv_policy import (
    CWVError,
    CompleteWorldEvaluator,
    StratifiedPriorEvaluator,
    afterstate,
    checkpoint_id,
    child_position,
    prior_evaluator_for,
    shared_evaluator,
)
from ..ai.mcbot import MCBot
from ..ai.registry import REGISTRY
from ..engine.combos import decompose
from ..engine.round import Round

NETROLL_BASE_POLICY = "mc-s0-report-lcb"
NET_STAGES = ("report", "all")
NETROLL_RECORD_SCHEMA = "netroll-decision-v1"
NETROLL_CHECKPOINT_ENV = "SHENGJI_NETROLL_CKPT"
NETROLL_TRICKS_ENV = "SHENGJI_NETROLL_TRICKS"
NETROLL_STAGES_ENV = "SHENGJI_NETROLL_STAGES"
NETROLL_RECEIPT_ENV = "SHENGJI_NETROLL_RECEIPT"
DEFAULT_TRICKS = (1, 2, 4)
COUNTERS = ("net_plays", "forced_plays", "heuristic_plays", "net_positions", "batches",
            "forwards", "rollouts", "terminal_clones", "exact_clones",
            "report_rollouts", "report_net_plays", "report_batches", "report_forwards",
            "selection_rollouts", "selection_net_plays", "selection_batches",
            "selection_forwards")


class NetRolloutError(RuntimeError):
    """The net-rollout arm cannot honour its contract (fail closed)."""


def _fresh_counts() -> dict[str, int]:
    return {name: 0 for name in COUNTERS}


class MCNetRolloutSearch(REGISTRY[NETROLL_BASE_POLICY]):
    """Production search with the net as the rollout policy for ``K`` tricks."""

    NET_TRICKS = 0
    NET_STAGE = "report"
    NET_TRACE = False      # keep ``last_net_trace`` / final clones (tests)

    def __init__(self, evaluator, *, seed: int | None = None, net_tricks: int = 0,
                 net_stage: str = "report"):
        super().__init__(seed)
        if type(net_tricks) is not int or net_tricks < 0:
            raise NetRolloutError("net_tricks must be a non-negative integer")
        if net_stage not in NET_STAGES:
            raise NetRolloutError(f"net_stage must be one of {NET_STAGES}, got {net_stage!r}")
        if not callable(getattr(evaluator, "score_many", None)):
            raise NetRolloutError("evaluator must provide score_many(positions, seats)")
        self.NET_TRICKS = net_tricks
        self.NET_STAGE = net_stage
        self.evaluator = evaluator
        if net_stage == "all":
            # The selection stage's only hook: a uniform lockstep allocation.
            self.ADAPTIVE_ALLOCATION = True
        self.policy_name = f"{NETROLL_BASE_POLICY}+netroll-k{net_tricks}-{net_stage}"
        # Cumulative, like MCBot's own counters.
        self.netroll_counts = _fresh_counts()
        self.netroll_sim_secs = 0.0       # lockstep simulation wall (net + heuristic)
        self.netroll_net_secs = 0.0       # of which evaluator wall
        self._decision_counts = _fresh_counts()
        self._decision_secs = {"sim": 0.0, "net": 0.0}
        self.last_net_trace: list[dict[str, Any]] | None = None
        self.last_lockstep: dict[str, Any] | None = None

    # ------------------------------------------------------------ describe
    def describe(self) -> dict[str, Any]:
        identity = (self.evaluator.identity() if hasattr(self.evaluator, "identity")
                    else repr(self.evaluator))
        return {"schema": NETROLL_RECORD_SCHEMA, "base_policy": NETROLL_BASE_POLICY,
                "net_tricks": self.NET_TRICKS, "net_stage": self.NET_STAGE,
                "evaluator": identity,
                "checkpoint_sha256": getattr(self.evaluator, "checkpoint_sha256", None)}

    # ------------------------------------------------------------ decision
    def decide_play(self, rnd: Round, seat: int) -> list[str]:
        self._decision_counts = _fresh_counts()
        self._decision_secs = {"sim": 0.0, "net": 0.0}
        self.last_net_trace = [] if self.NET_TRACE else None
        self.last_lockstep = None
        return super().decide_play(rnd, seat)

    def _finish_decision(self, candidates, played_index, reason, started, sampler_before):
        result = super()._finish_decision(candidates, played_index, reason, started,
                                          sampler_before)
        rec = self.last_decision_record
        if rec is not None:
            rec["net_rollout"] = {
                **self.describe(),
                "counts": dict(self._decision_counts),
                "sim_wall_secs": self._decision_secs["sim"],
                "net_wall_secs": self._decision_secs["net"],
                "decision_wall_secs": rec.get("search_secs"),
            }
        return result

    # ---------------------------------------------------------- lockstep
    def _net_horizon(self, rnd: Round) -> int:
        """Resolved tricks at which the net stops driving: K beyond the root."""
        return len(rnd.history) + self.NET_TRICKS

    def _net_ballot(self, clone: Round, seat: int) -> list[list[str]]:
        """Production's decision boundary for a reply seat in a clone: the
        tractor lock on a lead, then the ballot (as ``CWVTwoPlyBot``)."""
        assert clone.trick is not None and clone.ordering is not None
        if self.TRACTOR_LOCK and not clone.trick.plays:
            pick = self.canonical_lead(clone, seat)
            dec = decompose(pick, clone.ordering)
            if len(dec.components) == 1 and dec.components[0].pair_len >= 2:
                return [pick]
        return self._candidates(clone, seat)

    @staticmethod
    def _report_rng(seed: int) -> random.Random:
        """The report fold's child stream, exactly production's."""
        return random.Random(seed)

    @staticmethod
    def _net_perspective(mover: int, root_seat: int) -> int:
        """The seat whose TEAM the mover maximises: the mover's own."""
        del root_seat
        return mover

    def _lockstep_values(self, rnd: Round, seat: int, worlds: Sequence[tuple],
                         candidates: Sequence[Sequence[str]], *, stage: str,
                         sessions: Sequence[Any] | None = None) -> np.ndarray:
        """Final attacker points of every (world, candidate) continuation,
        ``(len(worlds), len(candidates))``: net-driven for ``NET_TRICKS``
        tricks in lockstep, then the heuristic to round end as production."""
        sim0 = time.perf_counter()
        counts = _fresh_counts()          # this call's counts, folded in at the end
        n_w, n_c = len(worlds), len(candidates)
        sessions = list(sessions) if sessions is not None else [None] * n_w
        clones: list[Round] = []
        for hands, buried in worlds:
            for cand in candidates:
                # Clone construction: MCBot._rollout on a prepared world, byte
                # for byte (fresh lists from the canonical hands, sorted kitty).
                clones.append(afterstate(rnd, seat, hands, buried, cand, finish_trick=False))
        values = np.full(n_w * n_c, np.nan, dtype=np.float64)
        done = [False] * len(clones)
        horizon = self._net_horizon(rnd)
        _exact_on = self.EXACT_ENDGAME
        trace = self.last_net_trace
        net_plays_by_clone = [0] * len(clones)
        forward_attr = "forward_calls" if hasattr(self.evaluator, "forward_calls") else None
        net_secs = 0.0

        def settle_exact(index: int) -> bool:
            if not _exact_on:
                return False
            exact = self._exact_endgame_value(clones[index], sessions[index // n_c])
            if exact is None:
                return False
            values[index] = exact
            done[index] = True
            counts["exact_clones"] += 1
            return True

        active = [i for i, c in enumerate(clones)
                  if c.phase == "play" and len(c.history) < horizon]
        while active:
            batch: list[Round] = []
            seats: list[int] = []
            groups: list[tuple[int, int, list[list[str]], int]] = []
            for index in active:
                if settle_exact(index):
                    continue
                clone = clones[index]
                mover = clone.turn
                assert mover is not None
                ballot = self._net_ballot(clone, mover)
                if len(ballot) == 1:
                    if trace is not None:
                        trace.append({"stage": stage, "clone": index, "seat": mover,
                                      "trick": len(clone.history), "candidates": [list(ballot[0])],
                                      "values": None, "chosen": 0})
                    clone.play(mover, list(ballot[0]))
                    counts["forced_plays"] += 1
                    net_plays_by_clone[index] += 1
                    continue
                start = len(batch)
                parent = copy.deepcopy(clone) if trace is not None else None
                for cand in ballot:
                    batch.append(child_position(clone, mover, cand))
                    seats.append(self._net_perspective(mover, seat))
                groups.append((index, mover, ballot, start))
                if trace is not None:
                    trace.append({"stage": stage, "clone": index, "seat": mover,
                                  "trick": len(clone.history), "parent": parent,
                                  "candidates": [list(c) for c in ballot],
                                  "values": None, "chosen": None, "batch": start})
            if batch:
                forwards_before = int(getattr(self.evaluator, forward_attr, 0)) if forward_attr else 0
                net0 = time.perf_counter()
                scored = np.asarray(self.evaluator.score_many(batch, seats), dtype=np.float64)
                net_secs += time.perf_counter() - net0
                if scored.shape != (len(batch),) or not np.all(np.isfinite(scored)):
                    raise NetRolloutError("evaluator returned a misaligned or non-finite batch")
                counts["batches"] += 1
                counts[f"{stage}_batches"] += 1
                counts["net_positions"] += len(batch)
                if forward_attr:
                    delta = int(getattr(self.evaluator, forward_attr, 0)) - forwards_before
                    counts["forwards"] += delta
                    counts[f"{stage}_forwards"] += delta
                for index, mover, ballot, start in groups:
                    block = scored[start:start + len(ballot)]
                    chosen = int(np.argmax(block))          # ties: first candidate
                    clones[index] = batch[start + chosen]
                    counts["net_plays"] += 1
                    counts[f"{stage}_net_plays"] += 1
                    net_plays_by_clone[index] += 1
                    if trace is not None:
                        for entry in reversed(trace):
                            if entry.get("batch") == start and entry["clone"] == index \
                                    and entry["chosen"] is None:
                                entry["values"] = block.tolist()
                                entry["chosen"] = chosen
                                break
            active = [i for i in active if not done[i] and clones[i].phase == "play"
                      and len(clones[i].history) < horizon]

        # After K tricks: MCBot._rollout's continuation, unchanged.
        policy = self.rollout_policy
        heuristic_plays = 0
        for index, clone in enumerate(clones):
            if done[index]:
                continue
            session = sessions[index // n_c]
            while clone.phase == "play":
                exact = (self._exact_endgame_value(clone, session) if _exact_on else None)
                if exact is not None:
                    values[index] = exact
                    counts["exact_clones"] += 1
                    break
                s = clone.turn
                assert s is not None
                clone.play(s, policy.decide_play(clone, s))
                heuristic_plays += 1
            else:
                values[index] = float(clone.attacker_points)
                counts["terminal_clones"] += 1
        counts["heuristic_plays"] += heuristic_plays
        counts["rollouts"] += len(clones)
        counts[f"{stage}_rollouts"] += len(clones)
        if trace is not None:
            self.last_lockstep = {"stage": stage, "worlds": list(worlds),
                                  "candidates": [list(c) for c in candidates],
                                  "finals": clones, "net_phase_plays": net_plays_by_clone}
        if not np.all(np.isfinite(values)):
            raise NetRolloutError("a lockstep continuation produced no value")
        sim = time.perf_counter() - sim0
        self._decision_secs["sim"] += sim
        self._decision_secs["net"] += net_secs
        self.netroll_sim_secs += sim
        self.netroll_net_secs += net_secs
        for name in COUNTERS:
            self._decision_counts[name] += counts[name]
            self.netroll_counts[name] += counts[name]
        return values.reshape(n_w, n_c)

    # -------------------------------------------------------- report fold
    def _report_fold_gap(self, rnd, seat, mem, i_attack, cand_a, cand_b, n,
                         *, seed: int, keep_deltas: bool = False):
        """Production's report fold with lockstep continuations.

        The worlds are drawn by production's own calls in production's own
        order; the two candidates' values are then produced across all of
        them, and the paired arithmetic is production's line for line.
        """
        worlds: list[tuple] = []
        sessions: list[Any] = []
        attempts = 0
        cap = n * self.SAMPLE_ATTEMPT_FACTOR
        original_rng = self.rng
        try:
            self.rng = self._report_rng(seed)
            while len(worlds) < n and attempts < cap:
                attempts += 1
                sampled = self._sample_hands(rnd, seat, mem)
                if sampled is None:
                    continue
                hands, buried = sampled
                sessions.append(self._new_exact_world_session(rnd, buried))
                prepared = self._prepare_report_world(rnd, seat, hands, buried=buried)
                worlds.append((prepared.hands, prepared.buried))
        finally:
            self.rng = original_rng
        used = len(worlds)
        d_sum = d_sq = 0.0
        deltas = []
        if used:
            matrix = self._lockstep_values(rnd, seat, worlds, [list(cand_a), list(cand_b)],
                                           stage="report", sessions=sessions)
            for w in range(used):
                va = self._score(float(matrix[w, 0]))
                vb = self._score(float(matrix[w, 1]))
                if not i_attack:
                    va, vb = -va, -vb
                delta = va - vb
                d_sum += delta
                d_sq += delta * delta
                if keep_deltas:
                    deltas.append(delta)
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

    # ----------------------------------------------------- selection stage
    def _decide_adaptive(self, rnd, seat, candidates, mem, i_attack, *, allocation_rng):
        """``net_stage="all"``: production's UNIFORM selection stage (same
        budget, draws and paired moments) with lockstep continuations.  The
        ``_decide_adaptive`` hook is the only one production exposes for the
        selection stage; no pruning happens here and the allocation RNG is
        never consumed."""
        del allocation_rng
        if self.NET_STAGE != "all":
            raise NetRolloutError("the selection lockstep is only wired for net_stage='all'")
        K = len(candidates)
        budget = self.N_DETERMINIZATIONS * K + self.EXTRA_SELECTION_WORK
        full_target, residual = divmod(budget, K)
        if residual:
            raise NetRolloutError("the selection lockstep does not run residual dummy work")
        target_draws = full_target
        cap = (target_draws * self.SAMPLE_ATTEMPT_FACTOR
               if self.REQUIRE_EXACT_WORK else target_draws)
        worlds: list[tuple] = []
        sessions: list[Any] = []
        attempts = 0
        while len(worlds) < full_target and attempts < cap:
            attempts += 1
            sampled = self._sample_hands(rnd, seat, mem)
            if sampled is None:
                continue
            hands, buried = sampled
            sessions.append(self._new_exact_world_session(rnd, buried))
            worlds.append((self._complete_determinized_hands(rnd, seat, hands, buried=buried),
                           sorted(buried)))
        n_worlds = len(worlds)
        totals = [0.0] * K
        d_sum = [0.0] * K
        d_sq = [0.0] * K
        n_by = [0] * K
        if n_worlds:
            matrix = self._lockstep_values(rnd, seat, worlds, [list(c) for c in candidates],
                                           stage="selection", sessions=sessions)
            for w in range(n_worlds):
                world_vals = []
                for i in range(K):
                    val = self._score(float(matrix[w, i]))
                    val = val if i_attack else -val
                    totals[i] += val
                    world_vals.append(val)
                base = world_vals[0]
                for i, value in enumerate(world_vals):
                    delta = value - base
                    d_sum[i] += delta
                    d_sq[i] += delta * delta
                    n_by[i] += 1
        selection_rollouts = n_worlds * K
        short = n_worlds < full_target
        self.last_alloc = {
            "mode": "uniform-netroll", "attempts": attempts,
            "attempt_cap": cap, "attempt_cap_hit": attempts >= cap and short,
            "worlds": n_worlds, "rollouts": selection_rollouts,
            "decision_rollouts": selection_rollouts,
            "dummy_rollouts": 0, "budget": budget,
            "short": short, "survivors": K,
            "survivor_indices": list(range(K)),
            "n_by_candidate": list(n_by),
        }
        return totals, d_sum, d_sq, n_by, n_worlds, selection_rollouts


# ------------------------------------------------------------- construction

def require_mlp_evaluator(evaluator) -> None:
    """Refuse a learned evaluator whose checkpoint is not the ``mlp`` arch
    (the sequence architectures need the history tensor per position, which
    the lockstep never builds)."""
    if isinstance(evaluator, CompleteWorldEvaluator):
        arch = evaluator.metadata.get("arch")
        if arch != "mlp":
            raise NetRolloutError(f"net rollouts need the mlp architecture, checkpoint is {arch!r}")


def netroll_policy_name(ckpt8: str, net_tricks: int, *, net_stage: str = "report",
                        prior: bool = False) -> str:
    """``mc-netroll-<ckpt8>-k<K>[-all]``; control ``mc-netroll-prior-<ckpt8>-k<K>[-all]``."""
    if net_stage not in NET_STAGES:
        raise NetRolloutError(f"net_stage must be one of {NET_STAGES}")
    if type(net_tricks) is not int or net_tricks < 0:
        raise NetRolloutError("net_tricks must be a non-negative integer")
    kind = "mc-netroll-prior" if prior else "mc-netroll"
    suffix = "-all" if net_stage == "all" else ""
    return f"{kind}-{ckpt8}-k{net_tricks}{suffix}"


def make_netroll_bot(checkpoint: str | os.PathLike, *, net_tricks: int,
                     net_stage: str = "report", prior: bool = False,
                     seed: int | None = None, receipt: str | os.PathLike | None = None,
                     threads: int | None = 1, expected_sha256: str | None = None
                     ) -> MCNetRolloutSearch:
    try:
        if prior:
            evaluator = prior_evaluator_for(checkpoint, receipt=receipt)
        else:
            evaluator = shared_evaluator(checkpoint, threads=threads)
    except CWVError as exc:
        raise NetRolloutError(f"checkpoint refused: {exc}") from exc
    require_mlp_evaluator(evaluator)
    actual = evaluator.checkpoint_sha256
    if expected_sha256 is not None and actual != expected_sha256:
        raise NetRolloutError(f"checkpoint {checkpoint} changed since registration: "
                              f"{actual} != {expected_sha256}")
    bot = MCNetRolloutSearch(evaluator, seed=seed, net_tricks=int(net_tricks),
                             net_stage=net_stage)
    bot.netroll_checkpoint_sha256 = actual
    bot.netroll_ckpt8 = evaluator.ckpt8
    bot.netroll_prior = bool(prior)
    return bot


def netroll_registry_entries(checkpoint: str | os.PathLike, tricks: Sequence[int],
                             stages: Sequence[str] = ("report",), *,
                             receipt: str | os.PathLike | None = None) -> dict[str, Any]:
    """``{name: factory}`` for every (K, stage): the arm and its control."""
    ckpt8 = checkpoint_id(checkpoint)
    entries: dict[str, Any] = {}

    def factory(k: int, stage: str, prior: bool):
        def make(**kw):
            return make_netroll_bot(checkpoint, net_tricks=k, net_stage=stage, prior=prior,
                                    seed=kw.get("seed"), receipt=receipt)
        make.netroll_artifact = (str(checkpoint), ckpt8, k, stage, prior)
        return make

    for stage in stages:
        for k in sorted({int(k) for k in tricks}):
            entries[netroll_policy_name(ckpt8, k, net_stage=stage)] = factory(k, stage, False)
            entries[netroll_policy_name(ckpt8, k, net_stage=stage, prior=True)] = \
                factory(k, stage, True)
    return entries


def register_netroll_policies(checkpoint: str | os.PathLike, tricks: Sequence[int],
                              stages: Sequence[str] = ("report",), *,
                              receipt: str | os.PathLike | None = None) -> list[str]:
    """Register the arms in ``REGISTRY``; a name already bound to another
    artifact is refused.  Returns the registered names."""
    entries = netroll_registry_entries(checkpoint, tricks, stages, receipt=receipt)
    for name, factory in entries.items():
        existing = REGISTRY.get(name)
        bound = getattr(existing, "netroll_artifact", None)
        if existing is not None and bound != factory.netroll_artifact:
            raise NetRolloutError(f"registry name {name!r} is already bound to {bound}")
    REGISTRY.update(entries)
    return sorted(entries)


def env_registry_entries(environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    """``SHENGJI_NETROLL_CKPT`` (+ ``_TRICKS`` default 1,2,4; ``_STAGES``
    default report; ``_RECEIPT``) describe registry entries."""
    env = os.environ if environ is None else environ
    checkpoint = env.get(NETROLL_CHECKPOINT_ENV)
    if not checkpoint:
        return {}
    tricks = [int(p) for p in env.get(NETROLL_TRICKS_ENV, ",".join(map(str, DEFAULT_TRICKS))).split(",") if p]
    stages = [p for p in env.get(NETROLL_STAGES_ENV, "report").split(",") if p]
    return netroll_registry_entries(checkpoint, tricks, stages,
                                    receipt=env.get(NETROLL_RECEIPT_ENV) or None)


def netroll_record(bot) -> dict:
    """Cumulative net-rollout telemetry of one bot (zeros for production)."""
    counts = dict(getattr(bot, "netroll_counts", None) or {})
    evaluator = getattr(bot, "evaluator", None)
    return {
        "schema": NETROLL_RECORD_SCHEMA,
        "net_rollout": bot.describe() if isinstance(bot, MCNetRolloutSearch) else None,
        "counts": counts,
        "sim_secs": float(getattr(bot, "netroll_sim_secs", 0.0)),
        "net_secs": float(getattr(bot, "netroll_net_secs", 0.0)),
        "evaluator_wall_secs": float(getattr(evaluator, "wall_secs", 0.0)),
        "evaluator_cpu_secs": float(getattr(evaluator, "cpu_secs", 0.0)),
    }
