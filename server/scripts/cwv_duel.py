"""Budget-ladder calibration and paired duel for the complete-world bots.

Two subcommands, both bound to one checkpoint.  ``--plies 0`` (default) drives
the one-ply bot of #229 (``mc-cwv-<ckpt8>-w<W>``, heuristic trick finish);
``--plies 1`` / ``--plies 2`` drive the TWO-PLY bot (``mc-cwv2-<ckpt8>-w<W>``
/ ``-p2``): the net itself chooses every reply for the rest of the current
trick (1) or one more trick (2), one batched forward per ply step, then one
final root forward.  The calibration binding carries ``plies``, so a ladder
frozen for one bot is refused for the other.

  calibrate  Measure production's wall time per play decision on K outcome-
             blind deals (both mirrors, seeds 70360904+), then the one-ply
             bot's wall per decision at W in {30, 100, 300, 1000} on the SAME
             decision states, fit wall(W) = a + b*W, and freeze a BUDGET
             LADDER: W_1x (matched, 0.95-1.05 of production's wall, verified
             by measurement), W_3x (~3x) and W_10x (~10x), each with its
             predicted wall ratio.  Chosen from wall time only -- no outcome
             is ever read -- and written to calibration.json bound to the
             checkpoint sha, --finish-trick, --lcb, the base policy, the trump
             ranks and the budget set.  Run it ALONE on an idle machine: the
             band is narrower than the timing noise a concurrent job adds.

  run        The strength-vs-compute screen: one learned arm per budget
             (mc-cwv-<ckpt8>-w<W_b>), the NO-LEARNING control mc-cwv-prior-w<W_1x>,
             production's OWN compute curve at the same rungs
             (mc-s0-report-lcb-x3 / -x10: N and R scaled together -- on fresh
             deals production at 29.7x its rollouts scored +0.215 [+0.125,
             +0.309] vs itself at 1x, so that curve is the bar a learned bot
             must beat at each budget) and the production-vs-production
             reference, all on the same mirrored deals with
             scripts/evaluate.py's exact pairing (seeds seed0+c; a1/a2/b1/b2
             at +0/+500k/+1M/+1.5M; flip 1 mirrors the seats), paired per
             seed, clustered by seed.  Refuses a calibration whose identity
             differs from the live checkpoint, flags, ranks or budgets.
             Summary: paired signed level utility per round vs production
             with the deal-cluster bootstrap CI, win rate, role splits,
             realized wall ratio, positions (or rollouts) per decision, the
             minimum detectable effect for the round count, and
             ``equal_work_strength_claim: false`` (a dev screen).

``--tree`` switches both subcommands to the PUCT bot (shengji.ai.cwv_puct):
the budget is S simulations per decision (grid {64, 256, 1024, 4096}), the
arms are mc-cwvpuct-<ckpt8>-s<S_b>, the control mc-cwvpuct-prior-<ckpt8>-s<S_1x>
(uniform prior, stratified-prior leaf), and the calibration binding carries
the search parameters (world pool W, batch K, c_puct, prior mode and prior
checkpoint sha), so a run with other parameters is refused.  Records add
simulations, forward passes and leaf depth (mean and per-decision max).

The canonical strength harness is scripts/evaluate.py; this driver reproduces
its pairing through shengji.evaluation (run_arm's seed layout, paired_by_seed,
clustered_win_rate, counters, arm_ballots) rather than re-deriving them, and
records the same manifest fields plus the calibration binding.  Trump ranks:
``canonical`` (default) is exactly what evaluate.py plays -- a fresh
``Game.start_round()``, i.e. rank 2 with no banker -- ``2`` binds that rank
explicitly (byte-identical deals), and ``cycle`` or a comma list walks
``start_round_at`` over the 13 ranks by cluster.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import multiprocessing as mp
import os
import platform
import random
import statistics
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor

SERVER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, SERVER)

from shengji.ai.env import RoundLog, play_round  # noqa: E402
from shengji.ai.registry import (make_bot, register_cwv_policies,  # noqa: E402
                                 register_cwv_puct_policies,
                                 register_scaled_policies, scaled_policy_name)
from shengji.engine.cards import RANKS  # noqa: E402
from shengji.engine.game import Game  # noqa: E402
from shengji.evaluation import (ProtocolFailure, arm_ballots,  # noqa: E402
                                clustered_win_rate, counters, digest,
                                paired_by_seed, parse_bar)
from shengji.harvest.trajectory import start_round_at  # noqa: E402


CALIBRATION_SCHEMA = "shengji-cwv-calibration-v2"
RUN_SCHEMA = "shengji-cwv-duel-v1"
PRODUCTION = "mc-s0-report-lcb"
DEFAULT_GRID = (30, 100, 300, 1000)
DEFAULT_TREE_GRID = (64, 256, 1024, 4096)
DEFAULT_BUDGETS = ("1x", "3x", "10x")
CALIBRATION_SEED0 = 70_360_904
DUEL_SEED0 = 70_260_904
MATCH_BAND = (0.95, 1.05)
SEAT_OFFSETS = (0, 500_000, 1_000_000, 1_500_000)


class CalibrationMismatch(RuntimeError):
    """A calibration bound to another checkpoint, flags, ranks or budgets."""


# ----------------------------------------------------------------- helpers

def git_identity() -> dict:
    def run(*args):
        try:
            return subprocess.run(["git", *args], cwd=SERVER, check=True,
                                  capture_output=True, text=True).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            return None
    sha = run("rev-parse", "HEAD")
    dirty = run("status", "--porcelain", "--untracked-files=no")
    return {"sha": sha, "short": sha[:8] if sha else None,
            "dirty": bool(dirty) if dirty is not None else None,
            "dirty_files": (dirty.split("\n")[:20] if dirty else [])}


def machine_identity() -> dict:
    try:
        import torch
        torch_version, threads = torch.__version__, torch.get_num_threads()
    except Exception:                                  # pragma: no cover
        torch_version, threads = None, None
    return {"platform": platform.platform(), "machine": platform.machine(),
            "cpu_count": os.cpu_count(), "python": platform.python_version(),
            "torch": torch_version, "torch_threads": threads,
            "fast_engine": bool(os.environ.get("SHENGJI_FAST")),
            "require_voids": bool(os.environ.get("SHENGJI_REQUIRE_VOIDS"))}


def parse_budgets(spec) -> list[float]:
    """``"1x,3x,10x"`` -> ``[1.0, 3.0, 10.0]`` (ascending, distinct)."""
    parts = spec if isinstance(spec, (list, tuple)) else str(spec).split(",")
    out = []
    for part in parts:
        text = str(part).strip().lower().rstrip("x")
        if not text:
            continue
        value = float(text)
        if not math.isfinite(value) or value <= 0:
            raise ValueError(f"budget multiplier must be positive: {part!r}")
        out.append(value)
    if not out or sorted(set(out)) != out:
        raise ValueError("budgets must be ascending and distinct, e.g. 1x,3x,10x")
    return out


def budget_label(multiplier: float) -> str:
    return f"{multiplier:g}x"


def search_binding(*, world_pool: int, batch: int, c_puct: float, prior: str,
                   prior_checkpoint_sha256: str | None) -> dict:
    """The PUCT search parameters a tree calibration is bound to (S is the
    budget and lives in the rungs)."""
    return {"kind": "puct", "world_pool": int(world_pool), "batch": int(batch),
            "c_puct": float(c_puct), "prior": str(prior),
            "prior_checkpoint_sha256": prior_checkpoint_sha256}


def search_from_args(args) -> dict | None:
    """``None`` for the one-ply bot; the search binding under ``--tree``."""
    if not getattr(args, "tree", False):
        return None
    if int(getattr(args, "plies", 0) or 0):
        raise CalibrationMismatch("--tree and --plies 1/2 are different bots; pass one")
    from shengji.ai.cwv_policy import file_sha256
    prior_sha = None
    if args.prior == "head":
        if not args.prior_checkpoint:
            raise CalibrationMismatch("--prior head needs --prior-checkpoint")
        prior_sha = file_sha256(args.prior_checkpoint)
    return search_binding(world_pool=args.world_pool, batch=args.batch,
                          c_puct=args.c_puct, prior=args.prior,
                          prior_checkpoint_sha256=prior_sha)


def register_arms(args, checkpoint: str, budgets, *, receipt=None) -> None:
    """Register the arm and control at every budget (one-ply or tree)."""
    if getattr(args, "tree", False):
        register_cwv_puct_policies(
            checkpoint, budgets, world_pool=args.world_pool, batch=args.batch,
            c_puct=args.c_puct, prior=args.prior,
            prior_checkpoint=args.prior_checkpoint, receipt=receipt)
    else:
        register_cwv_policies(checkpoint, budgets, finish_trick=args.finish_trick,
                              lcb=args.lcb, receipt=receipt,
                              plies=bot_plies(getattr(args, "plies", 0)))


def arm_name(args, ckpt8: str, budget: int) -> str:
    from shengji.ai.cwv_policy import policy_name
    from shengji.ai.cwv_puct import puct_policy_name
    if getattr(args, "tree", False):
        return puct_policy_name(ckpt8, budget)
    return policy_name(ckpt8, budget, lcb=args.lcb, plies=bot_plies(getattr(args, "plies", 0)))


def control_arm_name(args, ckpt8: str, budget: int) -> str:
    from shengji.ai.cwv_policy import control_name
    from shengji.ai.cwv_puct import puct_control_name
    if getattr(args, "tree", False):
        return puct_control_name(ckpt8, budget)
    return control_name(ckpt8, budget, lcb=args.lcb, plies=bot_plies(getattr(args, "plies", 0)))


def rank_plan(spec: str | None):
    """``None``/``canonical`` -> None (evaluate.py's deals); else rank list."""
    if spec is None or str(spec).strip().lower() in ("", "canonical"):
        return None
    text = str(spec).strip()
    if text.lower() == "cycle":
        return list(RANKS)
    ranks = [part.strip().upper() if part.strip().lower() != "10" else "10"
             for part in text.split(",") if part.strip()]
    for rank in ranks:
        if rank not in RANKS:
            raise ValueError(f"unknown trump rank {rank!r}; ranks: {RANKS}")
    return ranks


def rank_spec_label(plan) -> str:
    return "canonical" if plan is None else ",".join(plan)


def rank_for(plan, cluster: int) -> str | None:
    return None if plan is None else plan[cluster % len(plan)]


def play_round_at(game: Game, policies: list, trump_rank: str) -> RoundLog:
    """``env.play_round`` started through ``start_round_at`` (rank/no banker)."""
    rnd = start_round_at(game, trump_rank, None)
    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        cards = policies[seat].decide_declare(rnd, seat)
        if cards:
            rnd.declare(seat, cards)
    for seat in range(4):
        cards = policies[seat].decide_declare(rnd, seat, final=True)
        if cards:
            rnd.declare(seat, cards)
    rnd.finalize_declare()
    assert rnd.banker is not None
    rnd.bury(rnd.banker, policies[rnd.banker].decide_bury(rnd, rnd.banker))
    while rnd.phase == "play":
        seat = rnd.turn
        rnd.play(seat, policies[seat].decide_play(rnd, seat))
    result = game.finish_round()
    return RoundLog(rnd.trump_rank, rnd.banker, result.attacker_points,
                    result.winner_team, result.level_change)


class TimedPolicy:
    """Delegate the bot interface; time every play decision.

    ``keep_states`` snapshots the state BEFORE each searched decision so the
    calibration can time other bots on production's own decision states.
    """

    def __init__(self, inner, *, keep_states: bool = False):
        self.inner = inner
        self.keep_states = keep_states
        self.walls: list[float] = []
        self.states: list[tuple] = []

    def decide_declare(self, rnd, seat, **kw):
        return self.inner.decide_declare(rnd, seat, **kw)

    def decide_bury(self, rnd, seat):
        return self.inner.decide_bury(rnd, seat)

    def decide_play(self, rnd, seat):
        snapshot = copy.deepcopy(rnd) if self.keep_states else None
        started = time.perf_counter()
        cards = self.inner.decide_play(rnd, seat)
        wall = time.perf_counter() - started
        self.walls.append(wall)
        if snapshot is not None and getattr(self.inner, "last_decision_record", None) is not None:
            self.states.append((snapshot, seat, wall))
        return cards


def paired_bots(policy: str, opponent: str, seed: int, flip: int):
    """scripts/evaluate.py's exact seat/seed layout for one mirrored round."""
    a1 = make_bot(policy, seed=seed + SEAT_OFFSETS[0])
    a2 = make_bot(policy, seed=seed + SEAT_OFFSETS[1])
    b1 = make_bot(opponent, seed=seed + SEAT_OFFSETS[2])
    b2 = make_bot(opponent, seed=seed + SEAT_OFFSETS[3])
    pol = [a1, b1, a2, b2] if flip == 0 else [b1, a1, b2, a2]
    return pol, (a1, a2), (b1, b2)


def play_pair(policy: str, opponent: str, seed: int, flip: int, *,
              trump_rank: str | None, keep_states: bool = False):
    """One mirrored round; returns (log, arm bots, opp bots, timers)."""
    pol, arm, opp = paired_bots(policy, opponent, seed, flip)
    timers = [TimedPolicy(bot, keep_states=keep_states and bot in arm) for bot in pol]
    game = Game(random.Random(seed))
    if trump_rank is None:
        log = play_round(game, timers)
    else:
        log = play_round_at(game, timers, trump_rank)
    return log, arm, opp, timers


def _mean(values) -> float:
    values = list(values)
    return float(statistics.fmean(values)) if values else float("nan")


# ------------------------------------------------------------- calibration

def measure_production(base_policy: str, *, deals: int, seed0: int, plan,
                       subset_stride: int) -> dict:
    """Production's wall per decision on outcome-blind deals + state subset.

    The round logs are discarded unread: nothing here depends on who won.
    """
    walls_all: list[float] = []
    contested: list[tuple] = []
    for cluster in range(deals):
        seed = seed0 + cluster
        for flip in (0, 1):
            _log, arm, _opp, timers = play_pair(
                base_policy, base_policy, seed, flip,
                trump_rank=rank_for(plan, cluster), keep_states=True)
            for timer in timers:
                if timer.inner in arm:
                    walls_all.extend(timer.walls)
                    contested.extend(timer.states)
    subset = contested[::max(1, subset_stride)]
    return {
        "policy": base_policy, "deals": deals, "seed0": seed0,
        "decisions": len(walls_all), "mean_wall": _mean(walls_all),
        "contested_decisions": len(contested),
        "contested_mean_wall": _mean(w for _, _, w in contested),
        "subset_size": len(subset), "subset_stride": subset_stride,
        "subset_mean_wall": _mean(w for _, _, w in subset),
        "_subset": subset,
    }


def measure_bot(policy: str, subset, *, seed: int = 11) -> dict:
    """The named bot's wall per decision on production's decision states.

    Works for the one-ply bot (positions evaluated) and for a production
    search policy (rollouts): ``work`` is whichever the bot counts.
    """
    bot = make_bot(policy, seed=seed)
    walls = []
    for snapshot, seat, _ in subset:
        state = copy.deepcopy(snapshot)
        started = time.perf_counter()
        bot.decide_play(state, seat)
        walls.append(time.perf_counter() - started)
    cwv = int(getattr(bot, "cwv_decisions", 0))
    if cwv:
        kind, searched = "positions", cwv
        work = int(getattr(bot, "positions_evaluated", 0))
        active = float(getattr(bot, "batch_wall_secs", 0.0)) \
            + float(getattr(bot, "build_wall_secs", 0.0)) \
            + float(getattr(bot, "prior_wall_secs", 0.0))
    else:
        kind, searched = "rollouts", int(getattr(bot, "search_calls", 0))
        work = int(getattr(bot, "rollouts", 0))
        active = float(getattr(bot, "search_secs", 0.0))
    simulations = int(getattr(bot, "simulations", 0))
    return {
        "policy": policy, "kind": kind,
        "worlds": int(getattr(bot, "CWV_SIMULATIONS", 0) or getattr(bot, "CWV_WORLDS", 0)
                      or getattr(bot, "N_DETERMINIZATIONS", 0)),
        "simulations_per_decision": simulations / max(1, searched),
        "mean_depth": (float(getattr(bot, "depth_sum", 0)) / simulations
                       if simulations else None),
        "max_depth_per_decision": (float(getattr(bot, "depth_max_total", 0)) / searched
                                   if simulations else None),
        "forward_passes_per_decision": (float(getattr(bot, "forward_passes", 0)) / searched
                                        if simulations else None),
        "decisions": len(walls), "searched": searched,
        "mean_wall": _mean(walls), "positions": work,
        "positions_per_decision": work / max(1, searched),
        "positions_per_second": work / active if active > 0 else float("nan"),
        "batch_wall_secs": float(getattr(bot, "batch_wall_secs", 0.0)),
        "build_wall_secs": float(getattr(bot, "build_wall_secs", 0.0)),
        "short_searches": int(getattr(bot, "short_search_decisions", 0)),
        "reply_positions": int(getattr(bot, "reply_positions_evaluated", 0)),
        "forward_passes": int(getattr(bot, "forward_passes", 0)),
        "forwards_per_decision": int(getattr(bot, "forward_passes", 0)) / max(1, searched),
        "plies": int(getattr(bot, "CWV_PLIES", 0) or 0),
    }


def production_ladder_rows(base_policy: str, rungs) -> list[dict]:
    """Production's compute curve at every rung above 1x (registered)."""
    rows = []
    for rung in rungs:
        if rung["multiplier"] == 1.0:
            continue
        name = scaled_policy_name(base_policy, rung["multiplier"])
        register_scaled_policies(base_policy, [rung["multiplier"]])
        probe = make_bot(name, seed=0)
        rows.append({"budget": rung["budget"], "multiplier": rung["multiplier"],
                     "policy": name,
                     "n_determinizations": int(probe.N_DETERMINIZATIONS),
                     "report_fold_worlds": int(probe.REPORT_FOLD_WORLDS)})
    return rows


def fit_line(points) -> dict:
    """Least-squares ``wall = a + b * W`` over ``[(W, wall), ...]``."""
    xs = [float(w) for w, _ in points]
    ys = [float(t) for _, t in points]
    if len(xs) < 2 or len(set(xs)) < 2:
        raise ValueError("a line fit needs two distinct W values")
    mx, my = _mean(xs), _mean(ys)
    sxx = sum((x - mx) ** 2 for x in xs)
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    a = my - b * mx
    ss_res = sum((y - (a + b * x)) ** 2 for x, y in zip(xs, ys))
    ss_tot = sum((y - my) ** 2 for y in ys)
    if b <= 0:
        raise ValueError("wall time must grow with W; the fit has no positive slope")
    return {"a": a, "b": b, "r2": (1.0 - ss_res / ss_tot) if ss_tot > 0 else 1.0,
            "points": [[x, y] for x, y in zip(xs, ys)]}


def worlds_for_wall(fit: dict, target_wall: float) -> int:
    return max(1, int(round((target_wall - fit["a"]) / fit["b"])))


def matched_measurement(measured, production_wall: float):
    """The measured row inside the band closest to 1.0x, if any."""
    inside = [row for row in measured
              if MATCH_BAND[0] <= row["mean_wall"] / production_wall <= MATCH_BAND[1]]
    if not inside:
        return None
    return min(inside, key=lambda row: abs(row["mean_wall"] / production_wall - 1.0))


def local_worlds_for_wall(measured, target_wall: float) -> int:
    """W for a wall target: interpolate between the nearest measured rows
    that bracket it (timing is only locally linear at the 5% scale), else
    the global line fit."""
    below = [r for r in measured if r["mean_wall"] <= target_wall]
    above = [r for r in measured if r["mean_wall"] > target_wall]
    if below and above:
        lo = max(below, key=lambda r: r["mean_wall"])
        hi = min(above, key=lambda r: r["mean_wall"])
        if hi["worlds"] > lo["worlds"] and hi["mean_wall"] > lo["mean_wall"]:
            frac = (target_wall - lo["mean_wall"]) / (hi["mean_wall"] - lo["mean_wall"])
            return max(1, int(round(lo["worlds"] + frac * (hi["worlds"] - lo["worlds"]))))
    return worlds_for_wall(fit_line([(r["worlds"], r["mean_wall"]) for r in measured]),
                           target_wall)


def choose_budget_ladder(production_wall: float, grid, multipliers, *,
                         anchors=None) -> dict:
    """The ladder is a function of WALL TIME only.

    ``grid`` rows carry ``worlds`` and ``mean_wall``; any other field (a
    decoy utility, a win rate) is ignored by construction.  ``anchors``
    (``{multiplier: worlds}``) pins a rung to a MEASURED W -- the verified
    1x -- instead of the fit.  Rungs are strictly increasing in W, forced
    upward when two targets round together.
    """
    fit = fit_line([(row["worlds"], row["mean_wall"]) for row in grid])
    anchors = dict(anchors or {})
    rungs = []
    previous = 0
    for multiplier in sorted(parse_budgets(multipliers)):
        target = multiplier * production_wall
        if multiplier in anchors:
            worlds = max(previous + 1, int(anchors[multiplier]))
        else:
            worlds = max(previous + 1, worlds_for_wall(fit, target))
        predicted = fit["a"] + fit["b"] * worlds
        rungs.append({"budget": budget_label(multiplier), "multiplier": multiplier,
                      "worlds": worlds, "target_wall": target,
                      "predicted_wall": predicted,
                      "predicted_ratio": predicted / production_wall,
                      "anchored": multiplier in anchors})
        previous = worlds
    return {"fit": fit, "ladder": rungs}


def bot_plies(plies) -> int | None:
    """``--plies`` -> the registry's ``plies`` (0 = the one-ply bot = None)."""
    value = int(plies or 0)
    if value not in (0, 1, 2):
        raise ValueError("--plies must be 0 (one-ply bot), 1 or 2 (two-ply bot)")
    return value or None


def calibration_binding(checkpoint_sha256: str, *, finish_trick: bool, lcb: float,
                        base_policy: str, trump_ranks: str, budgets,
                        production_ladder=(), plies: int = 0,
                        search: dict | None = None) -> dict:
    """``plies`` is the two-ply bot's depth (0 = the one-ply bot); ``search``
    is the PUCT binding (``search_binding``) for a tree calibration and
    ``None`` otherwise.  Both are recorded so a ladder frozen for one bot is
    refused for another.  ``worlds`` in a rung is the budget unit of the arm
    (W for the one-ply / two-ply bots, S for the tree)."""
    return {"checkpoint_sha256": checkpoint_sha256,
            "finish_trick": bool(finish_trick), "lcb": float(lcb),
            "plies": int(plies or 0),
            "base_policy": base_policy, "trump_ranks": trump_ranks,
            "search": None if search is None else dict(search),
            "budgets": [{"budget": b["budget"], "multiplier": b["multiplier"],
                         "worlds": b["worlds"]} for b in budgets],
            "production_ladder": [
                {"budget": p["budget"], "multiplier": p["multiplier"],
                 "policy": p["policy"],
                 "n_determinizations": p["n_determinizations"],
                 "report_fold_worlds": p["report_fold_worlds"]}
                for p in production_ladder]}


def calibration_identity(binding: dict) -> str:
    payload = json.dumps(binding, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("ascii")).hexdigest()


def check_calibration(calibration: dict, *, checkpoint_sha256: str,
                      finish_trick: bool, lcb: float, base_policy: str,
                      trump_ranks: str, budgets: list[float],
                      plies: int = 0, search: dict | None = None) -> list[dict]:
    """Refuse a calibration bound to anything but the live configuration.

    ``search`` is the live PUCT binding (S is a budget; W, K, c_puct, prior
    mode and prior checkpoint are compared field by field) or ``None`` for
    the one-ply bot; a tree calibration never serves a one-ply run and vice
    versa.  Returns the requested rungs; each carries ``production`` (the
    scaled production policy at that rung, if the calibration measured one).
    """
    if calibration.get("schema") != CALIBRATION_SCHEMA:
        raise CalibrationMismatch(
            f"calibration schema {calibration.get('schema')!r} != {CALIBRATION_SCHEMA}")
    binding = calibration.get("binding", {})
    if calibration_identity(binding) != calibration.get("identity_sha256"):
        raise CalibrationMismatch("calibration identity does not recompute; tampered")
    wanted = [budget_label(m) for m in budgets]
    rungs = {b["budget"]: b for b in binding.get("budgets", [])}
    missing = [label for label in wanted if label not in rungs]
    problems = []
    if binding.get("checkpoint_sha256") != checkpoint_sha256:
        problems.append(f"checkpoint {str(binding.get('checkpoint_sha256'))[:8]} "
                        f"!= live {checkpoint_sha256[:8]}")
    if bool(binding.get("finish_trick")) != bool(finish_trick):
        problems.append(f"finish_trick {binding.get('finish_trick')} != {finish_trick}")
    if float(binding.get("lcb", 0.0)) != float(lcb):
        problems.append(f"lcb {binding.get('lcb')} != {lcb}")
    if int(binding.get("plies", 0) or 0) != int(plies or 0):
        problems.append(f"plies {binding.get('plies', 0)} != {int(plies or 0)} "
                        "(one-ply and two-ply ladders are not interchangeable)")
    if binding.get("base_policy") != base_policy:
        problems.append(f"base policy {binding.get('base_policy')!r} != {base_policy!r}")
    if binding.get("trump_ranks") != trump_ranks:
        problems.append(f"trump ranks {binding.get('trump_ranks')!r} != {trump_ranks!r}")
    bound_search = binding.get("search")
    if (bound_search is None) != (search is None):
        problems.append(f"search {'puct' if bound_search else 'one-ply'} != live "
                        f"{'puct' if search else 'one-ply'}")
    elif search is not None:
        for key in sorted(set(bound_search) | set(search)):
            if bound_search.get(key) != search.get(key):
                problems.append(f"search.{key} {bound_search.get(key)!r} != {search.get(key)!r}")
    if missing:
        problems.append(f"budgets {missing} are not in the calibration")
    if problems:
        raise CalibrationMismatch("calibration is bound to another run: "
                                  + "; ".join(problems))
    production = {p["budget"]: p for p in binding.get("production_ladder", [])}
    return [{**rungs[label], "production": production.get(label)} for label in wanted]


def calibrate(args) -> dict:
    from shengji.ai.cwv_policy import (afterstate_encoder_identity, file_sha256,
                                       load_cwv_checkpoint)

    plan = rank_plan(args.trump_ranks)
    budgets = parse_budgets(args.budgets)
    plies = bot_plies(args.plies)
    search = search_from_args(args)
    if args.grid is None:
        args.grid = ",".join(str(w) for w in (DEFAULT_TREE_GRID if search else DEFAULT_GRID))
    grid = sorted({int(w) for w in str(args.grid).split(",") if w})
    _model, metadata, sha = load_cwv_checkpoint(args.checkpoint)
    ckpt8 = sha[:8]
    unit = "S" if search else "W"
    started = time.perf_counter()
    bot_label = "puct" if search else ("two-ply" if plies else "one-ply")
    described = bot_label + (f", plies {plies}" if plies else "")
    print(f"calibrate: checkpoint {ckpt8} ({described}) vs {args.base_policy} on "
          f"{args.deals} deals x 2 mirrors (seed0 {args.seed0}, ranks "
          f"{rank_spec_label(plan)}" + (f", search {search}" if search else "") + ")",
          flush=True)
    production = measure_production(
        args.base_policy, deals=args.deals, seed0=args.seed0, plan=plan,
        subset_stride=args.subset_stride)
    subset = production.pop("_subset")
    print(f"  production: {production['decisions']} decisions, mean wall "
          f"{production['mean_wall']:.4f}s (contested {production['contested_mean_wall']:.4f}s, "
          f"subset of {production['subset_size']}: {production['subset_mean_wall']:.4f}s)",
          flush=True)
    target = production["subset_mean_wall"]

    measured: dict[int, dict] = {}

    def measure(worlds: int) -> dict:
        if worlds not in measured:
            register_arms(args, args.checkpoint, [worlds])
            row = measure_bot(arm_name(args, ckpt8, worlds), subset)
            row["ratio"] = row["mean_wall"] / target
            measured[worlds] = row
            depth = ("" if row.get("mean_depth") is None else
                     f", depth mean {row['mean_depth']:.2f} / max {row['max_depth_per_decision']:.1f}")
            print(f"  {unit}={worlds:5d}: mean wall {row['mean_wall']:.4f}s "
                  f"({row['ratio']:.2f}x), {row['positions_per_decision']:.0f} "
                  f"positions/decision, {row['forwards_per_decision']:.1f} "
                  f"forwards/decision, {row['positions_per_second']:.0f} positions/s{depth}",
                  flush=True)
        return measured[worlds]

    for worlds in grid:
        measure(worlds)
    # 1x is VERIFIED by measurement: keep proposing W (local interpolation
    # between the measured rows that bracket production's wall) until a
    # measured row sits inside the band, then anchor the ladder on it.
    verification = []
    for iteration in range(1, args.max_iterations + 1):
        if matched_measurement(measured.values(), target) is not None:
            break
        proposal = local_worlds_for_wall(measured.values(), target)
        if proposal in measured:                     # no progress: step once
            proposal = proposal + (1 if measured[proposal]["ratio"] < 1.0 else -1)
        row = measure(max(1, proposal))
        verification.append({"iteration": iteration, "worlds": row["worlds"],
                             "measured_wall": row["mean_wall"], "ratio": row["ratio"]})
    best_1x = matched_measurement(measured.values(), target)
    matched = best_1x is not None
    if best_1x is None:
        best_1x = min(measured.values(), key=lambda row: abs(row["ratio"] - 1.0))
    chosen = choose_budget_ladder(target, list(measured.values()), budgets,
                                  anchors={1.0: best_1x["worlds"]})
    for rung in chosen["ladder"]:
        row = measured.get(rung["worlds"])
        rung["measured_wall"] = None if row is None else row["mean_wall"]
        rung["measured_ratio"] = None if row is None else row["ratio"]
        rung["positions_per_decision"] = None if row is None else row["positions_per_decision"]
    # Production's own compute curve at the rungs above 1x: N and R scaled
    # together, timed on the same states so the run can report its realized
    # wall ratio next to the learned arm's.
    production_ladder = []
    if args.production_ladder:
        for row in production_ladder_rows(args.base_policy, chosen["ladder"]):
            timing = measure_bot(row["policy"], subset)
            row.update({"measured_wall": timing["mean_wall"],
                        "measured_ratio": timing["mean_wall"] / target,
                        "rollouts_per_decision": timing["positions_per_decision"]})
            production_ladder.append(row)
            print(f"  {row['policy']}: N={row['n_determinizations']} "
                  f"R={row['report_fold_worlds']} mean wall {timing['mean_wall']:.4f}s "
                  f"({row['measured_ratio']:.2f}x)", flush=True)
    binding = calibration_binding(
        sha, finish_trick=args.finish_trick, lcb=args.lcb,
        base_policy=args.base_policy, trump_ranks=rank_spec_label(plan),
        budgets=chosen["ladder"], production_ladder=production_ladder,
        plies=plies or 0, search=search)
    calibration = {
        "schema": CALIBRATION_SCHEMA,
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        "wall_secs": round(time.perf_counter() - started, 1),
        "checkpoint": {"path": os.path.abspath(args.checkpoint), "sha256": sha,
                       "ckpt8": ckpt8, "arch": metadata.get("arch"),
                       "declared_encoder": metadata.get("encoder")},
        "afterstate_encoder": afterstate_encoder_identity()["implementation_sha256"],
        "bot": bot_label, "plies": plies or 0,
        "arm_policy_at_1x": arm_name(args, ckpt8, best_1x["worlds"]),
        "binding": binding,
        "budget_unit": "simulations" if search else "worlds",
        "identity_sha256": calibration_identity(binding),
        "match_band": list(MATCH_BAND),
        "matched_1x": matched,
        "outcome_blind": True,
        "production": production,
        "grid": [measured[w] for w in sorted(measured)],
        "fit": chosen["fit"],
        "ladder": chosen["ladder"],
        "production_ladder": production_ladder,
        "verification": verification,
        "positions_per_second": _mean(row["positions_per_second"]
                                      for row in measured.values()
                                      if math.isfinite(row["positions_per_second"])),
        "machine": machine_identity(),
        "git": git_identity(),
        "cli_sha256_16": digest(os.path.abspath(__file__)),
        "library_sha256_16": digest(file_sha256.__code__.co_filename),
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    with open(args.out, "w") as fh:
        json.dump(calibration, fh, indent=2)
    print("\nladder (from wall time only):")
    for rung in chosen["ladder"]:
        print(f"  {rung['budget']:>4}: {unit}={rung['worlds']:5d} predicted "
              f"{rung['predicted_ratio']:.2f}x" + (
                  f", measured {rung['measured_ratio']:.2f}x"
                  if rung["measured_ratio"] is not None else ""))
    for row in production_ladder:
        print(f"  {row['budget']:>4}: {row['policy']} (N={row['n_determinizations']}, "
              f"R={row['report_fold_worlds']}) measured {row['measured_ratio']:.2f}x")
    print(f"  1x matched within {MATCH_BAND}: {matched}")
    print(f"calibration: {args.out} (identity {calibration['identity_sha256'][:12]})")
    return calibration


# -------------------------------------------------------------------- run

def _record(run_id: str, label: str, policy: str, seed: int, flip: int, log,
            arm, opp, timers) -> dict:
    """evaluate.py's record plus role, timing and evaluator telemetry."""
    won = int(log.winner_team == (0 if flip == 0 else 1))
    arm_team = 0 if flip == 0 else 1
    arm_timers = [t for t in timers if t.inner in arm]
    opp_timers = [t for t in timers if t.inner in opp]
    arm_counters = counters(list(arm))
    opp_counters = counters(list(opp))
    for side, bots in (("arm", arm), ("opp", opp)):
        extra = {
            "positions_evaluated": sum(getattr(b, "positions_evaluated", 0) for b in bots),
            "cwv_decisions": sum(getattr(b, "cwv_decisions", 0) for b in bots),
            "batch_wall_secs": round(sum(getattr(b, "batch_wall_secs", 0.0) for b in bots), 4),
            "build_wall_secs": round(sum(getattr(b, "build_wall_secs", 0.0) for b in bots), 4),
            "reply_positions_evaluated": sum(
                getattr(b, "reply_positions_evaluated", 0) for b in bots),
            "forward_passes": sum(getattr(b, "forward_passes", 0) for b in bots),
            "ply_steps": sum(getattr(b, "ply_steps", 0) for b in bots),
            "simulations": sum(getattr(b, "simulations", 0) for b in bots),
            "sample_wall_secs": round(sum(getattr(b, "sample_wall_secs", 0.0) for b in bots), 4),
            "prior_wall_secs": round(sum(getattr(b, "prior_wall_secs", 0.0) for b in bots), 4),
            "depth_sum": sum(getattr(b, "depth_sum", 0) for b in bots),
            "depth_max_total": sum(getattr(b, "depth_max_total", 0) for b in bots),
        }
        (arm_counters if side == "arm" else opp_counters).update(extra)
    return {
        "run": run_id, "label": label, "policy": policy, "seed": seed,
        "flip": flip, "won": won,
        "level_utility": (1 if won else -1) * max(1, int(log.level_change)),
        "arm": arm_counters, "opp": opp_counters,
        "banker": log.banker, "trump_rank": log.trump_rank,
        "attacker_points": log.attacker_points,
        "arm_role": "defender" if log.banker % 2 == arm_team else "attacker",
        "arm_play_decisions": sum(len(t.walls) for t in arm_timers),
        "arm_play_wall_secs": round(sum(sum(t.walls) for t in arm_timers), 4),
        "opp_play_decisions": sum(len(t.walls) for t in opp_timers),
        "opp_play_wall_secs": round(sum(sum(t.walls) for t in opp_timers), 4),
    }


def pair_key(record: dict) -> tuple:
    return (record["label"], int(record["seed"]), int(record["flip"]))


def read_shard(path: str) -> list[dict]:
    """Every complete record line of a shard file (a torn tail is ignored)."""
    records = []
    if not os.path.exists(path):
        return records
    with open(path) as fh:
        for line in fh:
            if not line.endswith("\n"):
                break                      # unterminated tail: not a record
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                break                      # a torn last line from a crash
    return records


def valid_prefix_length(path: str) -> int:
    """Byte offset just past the last complete JSON line of a shard file."""
    boundary = 0
    with open(path, "rb") as fh:
        for raw in fh:
            if not raw.endswith(b"\n"):
                break                      # unterminated: torn by a crash
            text = raw.strip()
            if text:
                try:
                    json.loads(text)
                except json.JSONDecodeError:
                    break
            boundary += len(raw)
    return boundary


class ShardSink:
    """Append one completed (arm, deal, flip) record per line, durably.

    Each line is written and fsynced as soon as its round finishes, so a
    crash loses at most the round in flight; a rerun with the same run id
    reads the file back and plays only the pairs that are missing.
    """

    def __init__(self, path: str):
        self.path = path
        self.written = 0
        # A torn tail from a crash mid-write would hide every later append
        # from read_shard.  Repair NARROWLY: an intact file is never opened
        # for writing, and a torn tail is cut at the validated byte boundary
        # (os.truncate), so the already-published prefix is never rewritten
        # and cannot be lost by a failure during the repair itself.
        if os.path.exists(path):
            boundary = valid_prefix_length(path)
            if boundary < os.path.getsize(path):
                os.truncate(path, boundary)
                with open(path, "rb") as fh:
                    os.fsync(fh.fileno())

    def __call__(self, record: dict) -> None:
        with open(self.path, "a") as fh:
            fh.write(json.dumps(record) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        self.written += 1


def play_shard(run_id: str, plan, clusters, seed0: int, rank_spec: str | None,
               opponent: str, *, progress: bool = False, sink=None,
               done=frozenset()) -> list[dict]:
    """All plan entries for these clusters, evaluate.py's pairing per entry.

    ``sink(record)`` publishes each completed pair as it completes; pairs
    whose key is in ``done`` are skipped (resume), never replayed.
    """
    ranks = rank_plan(rank_spec)
    records = []
    total = 2 * len(clusters) * len(plan)
    played = 0
    for label, policy in plan:
        for cluster in clusters:
            seed = seed0 + cluster
            for flip in (0, 1):
                if (label, seed, flip) in done:
                    continue
                log, arm, opp, timers = play_pair(
                    policy, opponent, seed, flip, trump_rank=rank_for(ranks, cluster))
                record = _record(run_id, label, policy, seed, flip, log, arm, opp, timers)
                if sink is not None:
                    sink(record)
                records.append(record)
                played += 1
                if progress:
                    print(f"    {label} seed {seed} flip {flip} done "
                          f"({played + len(done)}/{total})", flush=True)
    return records


def shard_path(out: str, run_id: str, index: int) -> str:
    return os.path.join(out, f"{run_id}.shard{index}.jsonl")


def _worker(payload: dict) -> dict:
    """Process entry point: register the arms, then play the shard.

    Returns ``{"records": new records, "retained": records read back from
    this shard's file before playing}``.
    """
    if payload.get("arm_args"):
        register_arms(argparse.Namespace(**payload["arm_args"]), payload["checkpoint"],
                      payload["worlds"], receipt=payload.get("receipt"))
    else:                                   # payloads without arm_args
        register_cwv_policies(payload["checkpoint"], payload["worlds"],
                              finish_trick=payload["finish_trick"], lcb=payload["lcb"],
                              receipt=payload.get("receipt"),
                              plies=bot_plies(payload.get("plies", 0)))
    if payload.get("scaled_multipliers"):
        register_scaled_policies(payload["opponent"], payload["scaled_multipliers"])
    path = shard_path(payload["out"], payload["run_id"], payload["shard"])
    retained = [rec for rec in read_shard(path) if rec.get("run") == payload["run_id"]]
    done = {pair_key(rec) for rec in retained}
    records = play_shard(payload["run_id"], payload["plan"], payload["clusters"],
                         payload["seed0"], payload["rank_spec"], payload["opponent"],
                         progress=payload.get("progress", False),
                         sink=ShardSink(path), done=frozenset(done))
    return {"records": records, "retained": retained}


def preflight_arms(plan, seed: int = 0) -> None:
    """Construct EVERY planned policy before any round is dealt, so a control
    or checkpoint failure surfaces in seconds, not after the expensive arms."""
    for label, policy in plan:
        try:
            make_bot(policy, seed=seed)
        except Exception as exc:
            raise CalibrationMismatch(
                f"arm {label} ({policy}) cannot be constructed: "
                f"{type(exc).__name__}: {exc}") from exc


def shards(clusters: int, workers: int) -> list[list[int]]:
    workers = max(1, min(workers, clusters))
    out = [[] for _ in range(workers)]
    for cluster in range(clusters):
        out[cluster % workers].append(cluster)
    return [chunk for chunk in out if chunk]


def bootstrap_ci(values, *, replicates: int = 2000, seed: int = 0) -> tuple[float, float]:
    """Percentile CI of the mean over resampled deal clusters."""
    values = [float(v) for v in values]
    if len(values) < 2:
        return float("-inf"), float("inf")
    rng = random.Random(seed)
    n = len(values)
    means = sorted(statistics.fmean(rng.choices(values, k=n)) for _ in range(replicates))
    lo = means[max(0, int(0.025 * replicates) - 1)]
    hi = means[min(replicates - 1, int(0.975 * replicates))]
    return lo, hi


def per_seed_differences(a_recs, b_recs) -> dict[int, float]:
    by: dict[int, list[float]] = {}
    for rec in a_recs:
        by.setdefault(rec["seed"], [0.0, 0.0])[0] += rec["level_utility"]
    for rec in b_recs:
        by.setdefault(rec["seed"], [0.0, 0.0])[1] += rec["level_utility"]
    return {seed: x - y for seed, (x, y) in by.items()}


def role_split(a_recs, b_recs) -> dict:
    """Paired per-round differences by the arm's role, clustered by seed."""
    ref = {(r["seed"], r["flip"]): r for r in b_recs}
    out = {}
    for role in ("attacker", "defender"):
        by_seed: dict[int, float] = {}
        rounds = 0
        for rec in a_recs:
            if rec["arm_role"] != role:
                continue
            other = ref.get((rec["seed"], rec["flip"]))
            if other is None:
                continue
            by_seed[rec["seed"]] = by_seed.get(rec["seed"], 0.0) + (
                rec["level_utility"] - other["level_utility"])
            rounds += 1
        diffs = list(by_seed.values())
        lo, hi = bootstrap_ci(diffs)
        out[role] = {"rounds": rounds, "seeds": len(diffs),
                     "paired_utility_per_round": (sum(diffs) / rounds) if rounds else None,
                     "bootstrap_ci_per_seed": [lo, hi]}
    return out


def wall_per_decision(recs, side: str) -> float:
    decisions = sum(r[f"{side}_play_decisions"] for r in recs)
    wall = sum(r[f"{side}_play_wall_secs"] for r in recs)
    return wall / decisions if decisions else float("nan")


def summarize(results: dict, plan, *, budgets_by_label: dict, bar: str,
              control_label: str = "control") -> dict:
    """The strength-vs-compute table and evaluate.py's verdict logic."""
    metric, threshold = parse_bar(bar)
    ref = results["reference"]
    production_wall = wall_per_decision(ref, "arm")
    n_seeds = len({r["seed"] for r in ref})
    table = {}
    for label, policy in plan:
        recs = results[label]
        m, ci, n = paired_by_seed(recs, ref)
        diffs = list(per_seed_differences(recs, ref).values())
        lo, hi = bootstrap_ci(diffs)
        sd = statistics.pstdev(diffs) * math.sqrt(n / (n - 1)) if n > 1 else float("inf")
        win, win_ci = clustered_win_rate(recs)
        searched = sum(r["arm"].get("cwv_decisions", 0) for r in recs)
        positions = sum(r["arm"].get("positions_evaluated", 0) for r in recs)
        forwards = sum(r["arm"].get("forward_passes", 0) for r in recs)
        reply_positions = sum(r["arm"].get("reply_positions_evaluated", 0) for r in recs)
        if searched:
            work_kind = "positions"
        else:                       # a production search arm counts rollouts
            work_kind = "rollouts"
            searched = sum(r["arm"].get("searches", 0) for r in recs)
            positions = sum(r["arm"].get("rollouts", 0) for r in recs)
        wall = wall_per_decision(recs, "arm")
        rounds = len(recs)
        budget = budgets_by_label.get(label) or {}
        simulations = sum(r["arm"].get("simulations", 0) for r in recs)
        depth_sum = sum(r["arm"].get("depth_sum", 0) for r in recs)
        depth_max_total = sum(r["arm"].get("depth_max_total", 0) for r in recs)
        forwards = sum(r["arm"].get("forward_passes", 0) for r in recs)
        wall_parts = {key: sum(r["arm"].get(key, 0.0) for r in recs) for key in (
            "sample_wall_secs", "build_wall_secs", "batch_wall_secs", "prior_wall_secs")}
        entry = {
            "policy": policy, "rounds": rounds, "seeds": n,
            "budget": budget or None,
            "worlds": budget.get("worlds"),
            "paired_utility_per_seed": m, "normal_ci_half": ci,
            "paired_utility_per_round": m / 2.0 if rounds else None,
            "bootstrap_ci_per_seed": [lo, hi],
            "bootstrap_ci_per_round": [lo / 2.0, hi / 2.0],
            "win_rate": win, "win_rate_ci_half": win_ci,
            "roles": role_split(recs, ref),
            "wall_per_decision": wall,
            "realized_wall_ratio": wall / production_wall if production_wall else None,
            "work_kind": work_kind,
            "positions_per_decision": (positions / searched) if searched else None,
            "positions_evaluated": positions,
            "reply_positions_evaluated": reply_positions,
            "forward_passes": forwards,
            "forwards_per_decision": (forwards / searched) if searched and work_kind == "positions" else None,
            "simulations_per_decision": (simulations / searched) if simulations else None,
            "mean_depth": (depth_sum / simulations) if simulations else None,
            "max_depth_per_decision": (depth_max_total / searched) if simulations else None,
            "wall_per_decision_parts": ({key: value / searched for key, value in wall_parts.items()}
                                        if searched else None),
            "short_searches": sum(r["arm"]["short_searches"] for r in recs),
            "minimum_detectable_effect_per_seed": (2.80 * sd / math.sqrt(n)) if n > 1 else None,
            "bar": {"metric": metric, "threshold": threshold,
                    "clears": ((m - ci) > threshold) if metric == "paired_utility"
                    else ((win - win_ci) > threshold)},
        }
        if label != control_label and control_label in results:
            dm, dci, _ = paired_by_seed(recs, results[control_label])
            clo, chi = bootstrap_ci(list(per_seed_differences(recs, results[control_label]).values()))
            entry["minus_control"] = {"paired_utility_per_seed": dm, "normal_ci_half": dci,
                                      "bootstrap_ci_per_seed": [clo, chi],
                                      "distinguishable": abs(dm) - dci > 0}
        table[label] = entry
    problems = []
    all_counts = [side for recs in results.values() for r in recs
                  for side in (r["arm"], r["opp"])]
    unreconciled = sum(abs(c.get("sample_attempts", 0) - c.get("accepted_worlds", 0)
                           - c.get("failed_worlds", 0)) for c in all_counts)
    if unreconciled:
        problems.append(f"sampler accounting is unreconciled by {unreconciled} attempts")
    short = sum(c.get("short_searches", 0) for c in all_counts)
    if short:
        problems.append(f"{short} search decisions failed to consume their dose")
    zero = sum(c.get("zero_world", 0) for c in all_counts)
    if zero:
        problems.append(f"{zero} decisions searched ZERO worlds")
    if not os.environ.get("SHENGJI_REQUIRE_VOIDS"):
        problems.append("SHENGJI_REQUIRE_VOIDS unset: sampled worlds may violate voids")
    return {
        "production_wall_per_decision": production_wall,
        "seeds": n_seeds, "rounds_per_arm": 2 * n_seeds,
        "table": table, "problems": problems,
        "equal_work_strength_claim": False,
        "note": ("dev screen: wall-time budgets, not equal work; the ladder "
                 "reports strength per compute multiple and claims nothing"),
    }


def print_summary(summary: dict, plan) -> None:
    print(f"\n{'label':10} {'S/W/N':>6} {'budget':>10} {'win%':>6} "
          f"{'paired utility/round':>21} {'bootstrap 95% CI':>20} "
          f"{'wall x':>7} {'work/dec':>9} {'fwd/dec':>8} {'MDE/seed':>9} {'depth':>11}")
    for label, _ in plan:
        e = summary["table"][label]
        lo, hi = e["bootstrap_ci_per_round"]
        print(f"{label:10} {str(e['worlds'] or '-'):>6} "
              f"{str((e['budget'] or {}).get('budget', '-')):>10} "
              f"{100 * e['win_rate']:5.1f}% {e['paired_utility_per_round']:+21.3f} "
              f"[{lo:+.3f},{hi:+.3f}]"
              + f" {e['realized_wall_ratio'] or float('nan'):7.2f} "
              f"{(e['positions_per_decision'] or 0):8.0f}{e['work_kind'][0]} "
              f"{(e['forwards_per_decision'] if e['forwards_per_decision'] is not None else float('nan')):8.1f} "
              f"{(e['minimum_detectable_effect_per_seed'] or float('nan')):9.3f}"
              + (f" {e['mean_depth']:5.2f}/{e['max_depth_per_decision']:4.1f}"
                 if e.get("mean_depth") is not None else f" {'-':>11}"))
    print("  work/dec: p = complete-world positions scored (tree: one per "
          "simulation), r = rollouts; depth (tree): mean leaf depth / mean per-decision max")
    for label, _ in plan:
        e = summary["table"][label]
        if "minus_control" in e:
            mc = e["minus_control"]
            print(f"  {label} minus control (paired, same seeds): "
                  f"{mc['paired_utility_per_seed']:+.3f} +/- {mc['normal_ci_half']:.3f}"
                  + ("  <-- excludes 0" if mc["distinguishable"] else "  <-- includes 0"))
    if summary["problems"]:
        print("\nPROTOCOL FAILURES (verdicts forced to NOT CONFIRMED):")
        for problem in summary["problems"]:
            print(f"  - {problem}")
    print(f"\nequal_work_strength_claim: {summary['equal_work_strength_claim']}")


def run(args) -> dict:
    from shengji.ai.cwv_policy import file_sha256, load_cwv_checkpoint

    with open(args.calibration) as fh:
        calibration = json.load(fh)
    budgets = parse_budgets(args.budgets)
    plan_ranks = rank_plan(args.trump_ranks)
    plies = bot_plies(args.plies)
    checkpoint = args.checkpoint or calibration["checkpoint"]["path"]
    _model, _metadata, sha = load_cwv_checkpoint(checkpoint)
    search = search_from_args(args)
    rungs = check_calibration(
        calibration, checkpoint_sha256=sha, finish_trick=args.finish_trick,
        lcb=args.lcb, base_policy=args.opponent, trump_ranks=rank_spec_label(plan_ranks),
        budgets=budgets, plies=plies or 0, search=search)
    if not calibration.get("matched_1x", False) and not args.allow_unmatched:
        raise CalibrationMismatch(
            "calibration did not match production's wall within the band; "
            "re-calibrate or pass --allow-unmatched for a dev screen")
    ckpt8 = sha[:8]
    worlds = [r["worlds"] for r in rungs]
    plan = [(f"arm_{r['budget']}", arm_name(args, ckpt8, r["worlds"]))
            for r in rungs]
    budgets_by_label = {f"arm_{r['budget']}": r for r in rungs}
    scaled_multipliers = []
    if args.production_ladder:
        for r in rungs:
            if r["multiplier"] == 1.0:
                continue
            if r.get("production") is None:
                raise CalibrationMismatch(
                    f"calibration carries no production-scaled arm for {r['budget']}; "
                    "re-calibrate or pass --no-production-ladder")
            scaled_multipliers.append(r["multiplier"])
            plan.append((f"prod_{r['budget']}", r["production"]["policy"]))
            budgets_by_label[f"prod_{r['budget']}"] = {
                "budget": r["budget"] + " (prod)",
                "worlds": r["production"]["n_determinizations"]}
    plan.append(("reference", args.opponent))
    plan.append(("control", control_arm_name(args, ckpt8, rungs[0]["worlds"])))
    budgets_by_label["control"] = {"budget": rungs[0]["budget"] + " (prior)",
                                   "worlds": rungs[0]["worlds"]}
    metric, threshold = parse_bar(args.bar)         # fail before compute
    arm_args = {"tree": bool(search), "finish_trick": args.finish_trick, "lcb": args.lcb,
                "plies": plies or 0,
                "world_pool": getattr(args, "world_pool", None),
                "batch": getattr(args, "batch", None),
                "c_puct": getattr(args, "c_puct", None),
                "prior": getattr(args, "prior", None),
                "prior_checkpoint": getattr(args, "prior_checkpoint", None)}
    register_arms(args, checkpoint, worlds, receipt=args.receipt)
    if scaled_multipliers:
        register_scaled_policies(args.opponent, scaled_multipliers)
    preflight_arms(plan)                            # every arm, before any deal
    git = git_identity()
    os.makedirs(args.out, exist_ok=True)
    configuration = {
        "arms": {label: policy for label, policy in plan},
        "opponent": args.opponent, "clusters": args.clusters, "seed0": args.seed0,
        "workers": args.workers, "declared_bar": args.bar,
        "budgets": [{"budget": r["budget"], "worlds": r["worlds"]} for r in rungs],
        "trump_ranks": rank_spec_label(plan_ranks),
        "finish_trick": args.finish_trick, "lcb": args.lcb, "plies": plies or 0,
        "search": search,
        "calibration_identity": calibration["identity_sha256"],
        "checkpoint_sha256": sha,
    }
    if args.resume:
        run_id = args.resume
        manifest_path = os.path.join(args.out, f"{run_id}.manifest.json")
        with open(manifest_path) as fh:
            manifest = json.load(fh)
        drift = [key for key, value in configuration.items()
                 if manifest.get("configuration", {}).get(key) != value]
        if drift:
            raise CalibrationMismatch(
                f"cannot resume {run_id}: configuration differs in {drift}")
        print(f"resuming {run_id}: completed pairs are read back, only missing "
              "pairs are played", flush=True)
    else:
        run_id = f"cwv_{int(time.time())}_{os.getpid()}_{git['short']}"
    manifest = {
        "schema": RUN_SCHEMA, "run": run_id,
        "arms": {label: policy for label, policy in plan},
        "opponent": args.opponent, "clusters": args.clusters, "seed0": args.seed0,
        "workers": args.workers, "declared_bar": args.bar,
        "budgets": rungs, "trump_ranks": rank_spec_label(plan_ranks),
        "finish_trick": args.finish_trick, "lcb": args.lcb,
        "bot": "puct" if search else ("two-ply" if plies else "one-ply"), "plies": plies or 0,
        "search": search, "budget_unit": "simulations" if search else "worlds",
        "calibration": {"path": os.path.abspath(args.calibration),
                        "identity_sha256": calibration["identity_sha256"],
                        "matched_1x": calibration.get("matched_1x")},
        "checkpoint": {"path": os.path.abspath(checkpoint), "sha256": sha, "ckpt8": ckpt8},
        "git": git["sha"], "tree_dirty": git["dirty"], "dirty_files": git["dirty_files"],
        "cli_sha256_16": digest(os.path.abspath(__file__)),
        "library_sha256_16": digest(os.path.join(SERVER, "shengji", "evaluation.py")),
        "ckpt_digests": {checkpoint: digest(checkpoint)},
        "ballots": arm_ballots([policy for _, policy in plan]),
        "fast_engine": bool(os.environ.get("SHENGJI_FAST")),
        "require_voids": bool(os.environ.get("SHENGJI_REQUIRE_VOIDS")),
        "machine": machine_identity(),
        "started": time.strftime("%Y-%m-%d %H:%M:%S"),
        "equal_work_strength_claim": False,
        "configuration": configuration,
    }
    manifest_path = os.path.join(args.out, f"{run_id}.manifest.json")
    if not args.resume:
        with open(manifest_path, "x") as fh:
            json.dump(manifest, fh, indent=2)
        print(json.dumps(manifest, indent=2), flush=True)
    if git["dirty"]:
        print("\nWARNING: tree is DIRTY -- the git SHA does not describe the code "
              "that ran. Recorded in the manifest.", flush=True)
    t_start = time.time()
    payloads = [{
        "checkpoint": checkpoint, "worlds": worlds, "finish_trick": args.finish_trick,
        "lcb": args.lcb, "plies": plies or 0,
        "receipt": args.receipt, "run_id": run_id, "plan": plan,
        "arm_args": arm_args,
        "clusters": chunk, "seed0": args.seed0,
        "rank_spec": rank_spec_label(plan_ranks) if plan_ranks else None,
        "opponent": args.opponent, "progress": index == 0,
        "scaled_multipliers": scaled_multipliers,
        "out": args.out, "shard": index,
    } for index, chunk in enumerate(shards(args.clusters, args.workers))]
    if len(payloads) == 1:
        outcomes = [_worker(payloads[0])]
    else:
        with ProcessPoolExecutor(max_workers=len(payloads),
                                 mp_context=mp.get_context("spawn")) as pool:
            outcomes = list(pool.map(_worker, payloads))
    retained = [rec for out in outcomes for rec in out["retained"]]
    played = [rec for out in outcomes for rec in out["records"]]
    records = retained + played
    records.sort(key=lambda r: ([label for label, _ in plan].index(r["label"]),
                                r["seed"], r["flip"]))
    expected = 2 * args.clusters * len(plan)
    records_path = os.path.join(args.out, f"{run_id}.jsonl")
    with open(records_path, "w") as fh:            # the merged view of the shards
        for rec in records:
            fh.write(json.dumps(rec) + "\n")
    results = {label: [r for r in records if r["label"] == label] for label, _ in plan}
    summary = summarize(results, plan, budgets_by_label=budgets_by_label, bar=args.bar)
    if git["dirty"]:
        summary["problems"].append("tree was DIRTY: the git SHA does not describe the run")
    if len(records) != expected:
        summary["problems"].append(
            f"incomplete: {len(records)} of {expected} pairs; rerun with --resume {run_id}")
    summary.update({"run": run_id, "wall_minutes": round((time.time() - t_start) / 60, 2),
                    "records": records_path, "manifest": manifest_path,
                    "declared_bar": args.bar, "pairs_expected": expected,
                    "pairs_retained_from_earlier_attempts": len(retained),
                    "pairs_played_this_attempt": len(played),
                    "shards": [shard_path(args.out, run_id, i) for i in range(len(payloads))]})
    summary_path = os.path.join(args.out, f"{run_id}.summary.json")
    with open(summary_path, "w") as fh:
        json.dump(summary, fh, indent=2)
    if retained:
        print(f"\nretained {len(retained)} pairs from earlier attempts of {run_id}; "
              f"played {len(played)} this attempt", flush=True)
    print_summary(summary, plan)
    print(f"\nDECLARED BAR: {metric} > {threshold}")
    for label, _ in plan:
        if label.startswith("arm_") or label.startswith("prod_"):
            e = summary["table"][label]
            verdict = "CONFIRMED" if e["bar"]["clears"] and not summary["problems"] else "NOT CONFIRMED"
            print(f"  {label}: {verdict} (dev screen; equal_work_strength_claim=false)")
    for label, _ in plan:
        if label.startswith("arm_") and f"prod_{label[4:]}" in summary["table"]:
            arm, prod = summary["table"][label], summary["table"][f"prod_{label[4:]}"]
            print(f"  {label} vs production's own curve at {label[4:]}: "
                  f"{arm['paired_utility_per_round']:+.3f} vs "
                  f"{prod['paired_utility_per_round']:+.3f} per round "
                  f"(wall {arm['realized_wall_ratio']:.2f}x vs {prod['realized_wall_ratio']:.2f}x)")
    print(f"wall {summary['wall_minutes']:.1f} min\nrecords: {records_path}\n"
          f"manifest: {manifest_path}\nsummary: {summary_path}")
    return summary


# ------------------------------------------------------------------- main

def add_tree_arguments(parser: argparse.ArgumentParser) -> None:
    """``--tree``: the PUCT bot; its search parameters bind the calibration."""
    from shengji.ai.cwv_puct import (DEFAULT_BATCH, DEFAULT_C_PUCT, DEFAULT_WORLD_POOL,
                                     PRIOR_MODES)
    tree = parser.add_argument_group("tree (PUCT over sampled worlds)")
    tree.add_argument("--tree", action="store_true",
                      help="calibrate/run the PUCT bot; the budget is S simulations")
    tree.add_argument("--world-pool", type=int, default=DEFAULT_WORLD_POOL,
                      help="W complete worlds sampled once per decision")
    tree.add_argument("--batch", type=int, default=DEFAULT_BATCH,
                      help="K simulations per batched leaf evaluation")
    tree.add_argument("--c-puct", type=float, default=DEFAULT_C_PUCT)
    tree.add_argument("--prior", choices=PRIOR_MODES, default="uniform")
    tree.add_argument("--prior-checkpoint", default=None,
                      help="shengji-train-v0 checkpoint whose public prior head prices "
                           "the ballot (--prior head)")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="command", required=True)

    cal = sub.add_parser("calibrate", help="freeze the budget ladder from wall time")
    cal.add_argument("--checkpoint", required=True)
    cal.add_argument("--out", required=True, help="calibration.json to write")
    cal.add_argument("--base-policy", default=PRODUCTION)
    cal.add_argument("--deals", type=int, default=4)
    cal.add_argument("--seed0", type=int, default=CALIBRATION_SEED0)
    cal.add_argument("--grid", default=None,
                     help=f"W grid {DEFAULT_GRID} (one-ply) / S grid {DEFAULT_TREE_GRID} (--tree)")
    cal.add_argument("--budgets", default=",".join(DEFAULT_BUDGETS))
    cal.add_argument("--subset-stride", type=int, default=4,
                     help="time the bot on every k-th production decision state")
    cal.add_argument("--max-iterations", type=int, default=3)
    cal.add_argument("--trump-ranks", default="canonical")
    cal.add_argument("--lcb", type=float, default=0.0)
    cal.add_argument("--plies", type=int, default=0, choices=(0, 1, 2),
                     help="0: the one-ply bot (#229); 1: two-ply, net finishes the "
                          "current trick; 2: two-ply, one more full trick")
    finish = cal.add_mutually_exclusive_group()
    finish.add_argument("--finish-trick", dest="finish_trick", action="store_true", default=True)
    finish.add_argument("--no-finish-trick", dest="finish_trick", action="store_false")
    prod = cal.add_mutually_exclusive_group()
    prod.add_argument("--production-ladder", dest="production_ladder",
                      action="store_true", default=True,
                      help="also time production with N/R scaled at each rung above 1x")
    prod.add_argument("--no-production-ladder", dest="production_ladder", action="store_false")
    add_tree_arguments(cal)
    cal.set_defaults(func=calibrate)

    duel = sub.add_parser("run", help="the strength-vs-compute duel")
    duel.add_argument("--calibration", required=True)
    duel.add_argument("--checkpoint", default=None,
                      help="defaults to the calibration's checkpoint path")
    duel.add_argument("--budgets", default=",".join(DEFAULT_BUDGETS))
    duel.add_argument("--clusters", type=int, default=4)
    duel.add_argument("--seed0", type=int, default=DUEL_SEED0)
    duel.add_argument("--workers", type=int, default=1)
    duel.add_argument("--opponent", default=PRODUCTION)
    duel.add_argument("--bar", default="paired_utility > 0")
    duel.add_argument("--trump-ranks", default="canonical")
    duel.add_argument("--lcb", type=float, default=0.0)
    duel.add_argument("--plies", type=int, default=0, choices=(0, 1, 2),
                      help="must equal the calibration's plies (0 one-ply; 1/2 two-ply)")
    duel.add_argument("--receipt", default=None,
                      help="training receipt JSON with the stratified prior (control)")
    duel.add_argument("--out", default="runs/logs")
    duel.add_argument("--resume", default=None, metavar="RUN_ID",
                      help="reuse this run id: read back completed pairs from its "
                           "shard files and play only the missing ones")
    duel.add_argument("--allow-unmatched", action="store_true")
    finish = duel.add_mutually_exclusive_group()
    finish.add_argument("--finish-trick", dest="finish_trick", action="store_true", default=True)
    finish.add_argument("--no-finish-trick", dest="finish_trick", action="store_false")
    prod = duel.add_mutually_exclusive_group()
    prod.add_argument("--production-ladder", dest="production_ladder",
                      action="store_true", default=True,
                      help="run production with N/R scaled at each rung above 1x")
    prod.add_argument("--no-production-ladder", dest="production_ladder", action="store_false")
    add_tree_arguments(duel)
    duel.set_defaults(func=run)
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        args.func(args)
    except (CalibrationMismatch, ProtocolFailure) as exc:
        print(f"REFUSING: {exc}")
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
