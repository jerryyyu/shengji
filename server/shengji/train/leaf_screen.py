"""Value-at-leaf equal-work screen (DEV): CPU-parity calibration, then the
paired mirrored duel of a learned-leaf search against production.

Arms (``leaf_policy.py``): ``learned`` = ``mc-vleaf-<ckpt8>-t<T>``, the
production search whose rollout leaf is the checkpoint's points head after
``T`` tricks; ``prior`` = ``mc-vleaf-prior-t<T>``, the same truncation with
the stratified points prior at the leaf (the no-learning control).  The
baseline is always ``mc-s0-report-lcb`` at its registered N=30 / R=300.

CPU parity (Codex's method, ``README.md``): the arm's decision CPU is
measured with ``TimedPolicy`` on outcome-blind calibration deals at several
selection doses N (R unchanged), the ratio to production's decision CPU is
fitted as a line in N (selection work is proportional to N, the report fold
is fixed) and the N at ratio 1.0 is frozen in ``calibration.json``.  The
choice is a function of CPU only; the calibration never reads an outcome.
A measured ratio outside 0.95-1.05 on the screen itself labels the result
cost-unmatched.  ``equal_work_strength_claim`` is always False here: this is
a development screen, not a confirmation or a promotion.

Both mirrors of one seeded deal are one atomic, resumable shard
(``search_screen._run_pending``); the summary carries the deal-cluster
bootstrap interval on signed level utility, the win rate, role splits, the
CPU ratio, rollout and leaf/NN-call counters, and the minimum detectable
effect for the completed round count and for the planned 1,024 clusters.
"""
from __future__ import annotations

import json
import math
import os
import platform
import statistics
import time
from pathlib import Path
from typing import Sequence

import numpy as np

from ..ai.registry import (VLEAF_BASE_POLICY, make_bot, register_vleaf_arms,
                           vleaf_checkpoint_sha256, vleaf_policy_name)
from ..engine.cards import RANKS
from ..engine.game import Game
from ..engine.round import Round
from ..oracle import screen as duel
from .leaf_policy import load_points_head, load_points_prior
from .search_screen import (TimedPolicy, _publish, _run_pending, bind_output_config,
                            execution_source_identity, reopen_shard)

CONFIG_SCHEMA = "vleaf-screen-config-v1"
CALIBRATION_SCHEMA = "vleaf-calibration-v1"
SUMMARY_SCHEMA = "vleaf-screen-summary-v1"
COMBINED_SCHEMA = "vleaf-screen-combined-v1"
ARMS = ("learned", "prior")
DEFAULT_GRID = (30, 45, 60, 90)
PARITY_BAND = (0.95, 1.05)
BASELINE_SELECT_WORLDS = 30
REPORT_WORLDS = 300
#: fresh seed space, disjoint from every training window (Run A 20260905+8000,
#: Run B 20260906+8000, Run C 30260904+32000, screens 20260904/20260910,
#: Run D 40260904+): the screen's deals ...
DEFAULT_SEED0 = 50_260_904
#: ... and the calibration deals, apart from the screen's 1,024-cluster range.
DEFAULT_CALIBRATION_SEED0 = 50_360_904
DEFAULT_BOOTSTRAP_REPLICATES = 10_000


class ScreenError(RuntimeError):
    pass


# --------------------------------------------------------------- policies

def arm_policy_name(config: dict) -> str:
    if config["arm"] == "learned":
        return vleaf_policy_name(leaf_tricks=config["leaf_tricks"],
                                 checkpoint_id=config["checkpoint_sha256"][:8])
    return vleaf_policy_name(leaf_tricks=config["leaf_tricks"])


def ensure_registered(config: dict) -> str:
    """Register the arm's name in THIS process (workers are spawned)."""
    learned = config["arm"] == "learned"
    register_vleaf_arms(checkpoint=config["checkpoint"] if learned else None,
                        prior=config["prior"] if not learned else None,
                        leaf_tricks=(config["leaf_tricks"],),
                        allow_legacy=bool(config.get("allow_legacy", False)))
    return arm_policy_name(config)


def make_side(config: dict, side: str, seed: int):
    if side == "baseline":
        bot = make_bot(VLEAF_BASE_POLICY, seed=seed)
        bot.N_DETERMINIZATIONS = int(config["baseline_select_worlds"])
    else:
        bot = make_bot(ensure_registered(config), seed=seed)
        bot.N_DETERMINIZATIONS = int(config["arm_select_worlds"])
    bot.REPORT_FOLD_WORLDS = int(config["report_worlds"])
    return bot


class LeafTimedPolicy(TimedPolicy):
    """``TimedPolicy`` plus every play call and per-decision leaf deltas."""

    def __init__(self, bot):
        super().__init__(bot)
        self.play_calls = 0

    def decide_play(self, rnd, seat):
        self.play_calls += 1
        counts = getattr(self.bot, "leaf_counts", None)
        before = dict(counts) if counts else None
        before_secs = float(getattr(self.bot, "leaf_secs", 0.0))
        recorded = len(self.decisions)
        try:
            return super().decide_play(rnd, seat)
        finally:
            if before is not None and len(self.decisions) > recorded:
                self.decisions[-1]["leaf"] = {k: counts[k] - before[k] for k in before}
                self.decisions[-1]["leaf_secs"] = self.bot.leaf_secs - before_secs


LEAF_COUNTERS = ("leaf_calls", "terminal_leaves", "exact_leaves", "predicted_leaves",
                 "leaf_plies")


def work_counters(bots) -> dict:
    """Production counters plus decision CPU/wall and the leaf's own."""
    out = duel.work_counters(bots)
    for name in ("decision_cpu_seconds", "decision_wall_seconds", "leaf_secs"):
        out[name] = float(sum(getattr(b, name, 0.0) for b in bots))
    out["play_calls"] = int(sum(getattr(b, "play_calls", 0) for b in bots))
    for name in LEAF_COUNTERS:
        out[name] = int(sum((getattr(b, "leaf_counts", None) or {}).get(name, 0) for b in bots))
    out["nn_calls"] = int(sum((getattr(b, "leaf_counts", None) or {}).get("predicted_leaves", 0)
                              for b in bots if getattr(getattr(b, "leaf", None), "kind", None) == "learned"))
    out["prior_lookups"] = int(sum((getattr(b, "leaf_counts", None) or {}).get("predicted_leaves", 0)
                                   for b in bots if getattr(getattr(b, "leaf", None), "kind", None) == "prior"))
    # A predicted leaf is not a continuation played to the end; production's
    # `rollouts` keeps its meaning (leaves scored by the search).
    out["continuation_rollouts"] = out["rollouts"] - out["predicted_leaves"]
    out["total_rollouts"] = out["rollouts"]
    return out


# ------------------------------------------------------------------ rounds

def _game_factory_for(rank: str):
    def game_factory(rng):
        game = Game(rng)
        game.level_idx = [RANKS.index(rank), RANKS.index(rank)]

        # Game.start_round uses rank 2 when the banker is not yet known; keep
        # the first-round declaration rule but cycle the trump rank by cluster
        # (search_screen.run_cluster).
        def start():
            game.round = Round(rank, None, game.rng)
            game.round_no += 1
            return game.round
        game.start_round = start
        return game
    return game_factory


def run_cluster(config: dict, cluster: int) -> dict:
    """Both mirrors of one deal: one atomic, independently replayable shard."""
    created = []

    def factory(_config, side, seed):
        wrapped = LeafTimedPolicy(make_side(config, side, seed))
        created.append((side, wrapped))
        return wrapped

    rank = RANKS[cluster % len(RANKS)]
    base = duel.build_config(arm="none", select_worlds=config["baseline_select_worlds"],
                             report_worlds=config["report_worlds"])
    seed = config["seed0"] + cluster
    rows = [duel.play_screen_round(base, cluster, seed, mirror, bot_factory=factory,
                                   counter_fn=work_counters,
                                   game_factory=_game_factory_for(rank))
            for mirror in (0, 1)]
    policy = arm_policy_name(config)
    for record, _ in rows:
        record["arm"] = config["arm"]
        record["arm_policy"] = policy
        record["arm_select_worlds"] = int(config["arm_select_worlds"])
    return {"cluster": cluster, "seed": seed, "rank": rank,
            "arm_policy": policy,
            "records": [r for r, _ in rows], "timings": [t for _, t in rows],
            "decision_traces": [{"mirror": i // 4, "side": side, "decisions": bot.decisions}
                                for i, (side, bot) in enumerate(created)]}


# ------------------------------------------------------------- calibration

CPU_FIELDS = ("decision_cpu_seconds", "decision_wall_seconds", "play_calls", "search_calls",
              "rollouts", "predicted_leaves", "leaf_secs")


def cpu_rows(shards: Sequence[dict]) -> list[dict]:
    """Outcome-blind view of the shards: work and CPU fields only."""
    rows = []
    for shard in shards:
        for record in shard["records"]:
            for side in ("arm", "baseline"):
                work = record["work"][side]
                rows.append({"cluster": record["cluster"], "mirror": record["mirror"],
                             "side": side,
                             **{name: work.get(name, 0) for name in CPU_FIELDS}})
    return rows


def cpu_ratio(rows: Sequence[dict]) -> dict:
    totals = {side: {name: 0.0 for name in CPU_FIELDS} for side in ("arm", "baseline")}
    for row in rows:
        for name in CPU_FIELDS:
            totals[row["side"]][name] += float(row[name])
    base_cpu = totals["baseline"]["decision_cpu_seconds"]
    arm_cpu = totals["arm"]["decision_cpu_seconds"]

    def per_decision(side):
        calls = totals[side]["play_calls"]
        return totals[side]["decision_cpu_seconds"] / calls if calls else None

    arm_pd, base_pd = per_decision("arm"), per_decision("baseline")
    return {
        "decision_cpu_ratio": arm_cpu / base_cpu if base_cpu else None,
        "decision_cpu_seconds": {"arm": arm_cpu, "baseline": base_cpu},
        "per_decision_cpu_ratio": (arm_pd / base_pd) if arm_pd is not None and base_pd else None,
        "per_decision_cpu_seconds": {"arm": arm_pd, "baseline": base_pd},
        "play_calls": {s: int(totals[s]["play_calls"]) for s in totals},
        "rollouts": {s: int(totals[s]["rollouts"]) for s in totals},
        "predicted_leaves": {s: int(totals[s]["predicted_leaves"]) for s in totals},
        "leaf_secs": {s: totals[s]["leaf_secs"] for s in totals},
    }


def choose_n(points: Sequence[tuple[int, float]], *, band=PARITY_BAND) -> dict:
    """The selection dose N whose decision-CPU ratio to production is 1.0.

    The arm's decision CPU is affine in N (selection work grows with N, the
    R-world report fold is fixed), so the grid's ratios are fitted with a
    least-squares line and solved at ratio 1; a solution outside the grid is
    an extrapolation and says so.  Inputs are (N, ratio) pairs only.
    """
    pts = [(int(n), float(r)) for n, r in points]
    if not pts or any(not math.isfinite(r) or r <= 0 for _, r in pts):
        raise ScreenError("calibration needs finite positive CPU ratios")
    ns = np.asarray([n for n, _ in pts], dtype=float)
    rs = np.asarray([r for _, r in pts], dtype=float)
    nearest = min(pts, key=lambda p: (abs(p[1] - 1.0), p[0]))
    out = {"grid": [{"n": n, "ratio": r} for n, r in pts], "band": list(band),
           "nearest_grid_n": nearest[0], "nearest_grid_ratio": nearest[1]}
    if len(pts) >= 2 and float(np.ptp(ns)) > 0:
        slope, intercept = np.polyfit(ns, rs, 1)
        fitted = intercept + slope * ns
        out["fit"] = {"intercept": float(intercept), "slope_per_world": float(slope),
                      "max_abs_residual": float(np.abs(fitted - rs).max()),
                      "method": "least-squares line ratio(N) = intercept + slope * N"}
        if slope > 0:
            n_star = (1.0 - intercept) / slope
            chosen = max(1, int(round(n_star)))
            out.update({"n_at_unit_ratio": float(n_star), "chosen_n": chosen,
                        "predicted_ratio": float(intercept + slope * chosen),
                        "within_grid": bool(ns.min() <= chosen <= ns.max()),
                        "method": "line fit through the grid, solved at ratio 1.0"})
        else:
            out.update({"chosen_n": nearest[0], "predicted_ratio": nearest[1],
                        "within_grid": True,
                        "method": "ratio did not increase with N: nearest grid point"})
    else:
        out.update({"chosen_n": nearest[0], "predicted_ratio": nearest[1], "within_grid": True,
                    "method": "single grid point"})
    out["within_band"] = bool(band[0] <= out["predicted_ratio"] <= band[1])
    return out


def calibration_choice(shards_by_n: dict[int, Sequence[dict]], *, band=PARITY_BAND) -> dict:
    """From completed per-N shards to the frozen N: CPU fields only."""
    table = []
    for n in sorted(shards_by_n):
        ratio = cpu_ratio(cpu_rows(shards_by_n[n]))
        table.append({"n": int(n), "clusters": len(shards_by_n[n]), **ratio})
    choice = choose_n([(row["n"], row["decision_cpu_ratio"]) for row in table], band=band)
    return {"table": table, "choice": choice}


def calibrate(config: dict, *, output: Path, workers: int, grid=DEFAULT_GRID,
              band=PARITY_BAND, log=print, executor_factory=None) -> dict:
    """Run every grid N on the calibration deals (resumable per N) and
    freeze the CPU-parity N in ``output/calibration.json``."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    if len(set(grid)) != len(grid) or any(type(n) is not int or n < 1 for n in grid):
        raise ScreenError("grid must be distinct positive integers")
    shards_by_n: dict[int, list[dict]] = {}
    started = time.perf_counter()
    for n in grid:
        sub = output / f"n-{n:03d}"
        cfg = dict(config, arm_select_worlds=int(n), calibration_grid=list(grid))
        bind_output_config(sub, cfg)
        shards, pending = _resume(sub, cfg)
        log(f"calibrate: N={n} ({len(shards)}/{cfg['clusters']} pairs done)")
        _run_pending(cfg, pending, shards, output=sub, workers=workers, task_fn=run_cluster,
                     executor_factory=executor_factory)
        shards_by_n[n] = sorted(shards, key=lambda s: s["cluster"])
    result = calibration_choice(shards_by_n, band=band)
    choice = result["choice"]
    calibration = {
        "schema": CALIBRATION_SCHEMA,
        "claim": ("CPU-parity calibration: the arm's selection dose N chosen on measured "
                  "decision CPU only; outcomes of the calibration deals were never read"),
        "outcomes_read": False,
        "arm": config["arm"], "arm_policy": arm_policy_name(config),
        "leaf_tricks": config["leaf_tricks"],
        "checkpoint_sha256": config.get("checkpoint_sha256"),
        "prior_sha256": config.get("prior_sha256"),
        "baseline_policy": VLEAF_BASE_POLICY,
        "baseline_select_worlds": config["baseline_select_worlds"],
        "report_worlds": config["report_worlds"],
        "seed0": config["seed0"], "clusters": config["clusters"],
        "seeds": [config["seed0"] + c for c in range(config["clusters"])],
        "grid": result["table"],
        "choice": choice,
        "chosen_arm_select_worlds": choice["chosen_n"],
        "predicted_decision_cpu_ratio": choice["predicted_ratio"],
        "within_band": choice["within_band"],
        "within_grid": choice["within_grid"],
        "wall_secs": round(time.perf_counter() - started, 3),
        "runtime": _runtime(),
        "source_sha256": config["source_sha256"],
    }
    _publish(output / "calibration.json", calibration)
    return calibration


def load_calibration(path: str | os.PathLike) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        calibration = json.load(fh)
    if calibration.get("schema") != CALIBRATION_SCHEMA:
        raise ScreenError(f"{path}: not a {CALIBRATION_SCHEMA} calibration")
    if calibration.get("outcomes_read") is not False:
        raise ScreenError(f"{path}: calibration does not attest outcome blindness")
    n = calibration.get("chosen_arm_select_worlds")
    if type(n) is not int or n < 1:
        raise ScreenError(f"{path}: no positive chosen_arm_select_worlds")
    calibration["file_sha256"] = vleaf_checkpoint_sha256(path)
    return calibration


# ------------------------------------------------------------------ config

def _runtime() -> dict:
    return {"python": platform.python_version(), "platform": platform.platform(),
            "fast_engine": duel.fast_engine_active(),
            "environment": {k: v for k, v in sorted(os.environ.items())
                            if k.startswith("SHENGJI_") or k in
                            {"OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS"}}}


def build_config(*, arm: str, leaf_tricks: int, seed0: int, clusters: int,
                 arm_select_worlds: int, checkpoint: str | None = None,
                 allow_legacy: bool = False, prior: str | None = None,
                 baseline_select_worlds: int = BASELINE_SELECT_WORLDS,
                 report_worlds: int = REPORT_WORLDS, calibration: dict | None = None,
                 bootstrap_replicates: int = DEFAULT_BOOTSTRAP_REPLICATES) -> dict:
    if arm not in ARMS:
        raise ScreenError(f"arm must be one of {ARMS}")
    if clusters < 1 or arm_select_worlds < 1 or baseline_select_worlds < 1:
        raise ScreenError("clusters and selection worlds must be positive")
    if report_worlds < 30:
        raise ScreenError("the LCB report needs at least 30 paired worlds")
    if os.environ.get("SHENGJI_REQUIRE_VOIDS") != "1":
        raise ScreenError("SHENGJI_REQUIRE_VOIDS=1 is required")
    config = {
        "schema": CONFIG_SCHEMA, "arm": arm, "leaf_tricks": int(leaf_tricks),
        "seed0": int(seed0), "clusters": int(clusters),
        "arm_select_worlds": int(arm_select_worlds),
        "baseline_select_worlds": int(baseline_select_worlds),
        "report_worlds": int(report_worlds),
        "base_policy": VLEAF_BASE_POLICY,
        "bootstrap_replicates": int(bootstrap_replicates),
    }
    if arm == "learned":
        if not checkpoint:
            raise ScreenError("the learned arm needs --checkpoint")
        path = str(Path(checkpoint).resolve())
        head = load_points_head(path, bool(allow_legacy))   # refuses a headless checkpoint
        meta = {k: v for k, v in head.metadata.items() if k != "population"}
        population = head.metadata.get("population")
        if isinstance(population, dict):
            meta["population_digest"] = population.get("digest")
        config.update({"checkpoint": path, "checkpoint_sha256": head.metadata["checkpoint_sha256"],
                       "allow_legacy": bool(allow_legacy), "model_metadata": meta})
    else:
        if not prior:
            raise ScreenError("the prior arm needs --prior")
        path = str(Path(prior).resolve())
        table = load_points_prior(path)
        config.update({"prior": path, "prior_sha256": table.provenance["file_sha256"],
                       "prior_provenance": table.provenance, "prior_n": table.n})
    config["arm_policy"] = arm_policy_name(config)
    if calibration is not None:
        config["calibration"] = {k: calibration.get(k) for k in (
            "file_sha256", "chosen_arm_select_worlds", "predicted_decision_cpu_ratio",
            "within_band", "within_grid", "seed0", "clusters", "checkpoint_sha256")}
    package = Path(__file__).resolve().parents[1]
    config["source_sha256"] = execution_source_identity(package)
    config["runtime"] = _runtime()
    return config


def _resume(output: Path, config: dict) -> tuple[list[dict], list[int]]:
    shards, pending = [], []
    for cluster in range(config["clusters"]):
        path = output / f"cluster-{cluster:05}.json"
        if path.exists():
            shards.append(reopen_shard(path, config, cluster))
        else:
            pending.append(cluster)
    return shards, pending


# ----------------------------------------------------------------- summary

def minimum_detectable_effect(per_cluster: Sequence[float], *, clusters: int | None = None,
                              alpha: float = 0.05, power: float = 0.8) -> dict:
    """Paired-mean MDE on per-cluster signed level utility:
    ``(z_{1-alpha/2} + z_power) * sd / sqrt(clusters)``."""
    values = np.asarray(list(per_cluster), dtype=float)
    n = int(clusters if clusters is not None else values.size)
    if values.size < 2 or n < 1:
        return {"clusters": n, "cluster_sd": None, "mde_levels_per_round": None,
                "alpha_two_sided": alpha, "power": power}
    sd = float(values.std(ddof=1))
    z = statistics.NormalDist().inv_cdf(1 - alpha / 2) + statistics.NormalDist().inv_cdf(power)
    return {"clusters": n, "cluster_sd": sd, "mde_levels_per_round": z * sd / math.sqrt(n),
            "alpha_two_sided": alpha, "power": power,
            "basis": "paired mean of per-cluster arm utility (both mirrors averaged); "
                     "sd from this run's clusters"}


def per_cluster_utility(records: Sequence[dict]) -> dict[int, float]:
    by_cluster: dict[int, list[float]] = {}
    for r in records:
        by_cluster.setdefault(int(r["cluster"]), []).append(float(r["arm_utility"]))
    return {c: sum(v) / len(v) for c, v in sorted(by_cluster.items())}


def summary_for(shards: Sequence[dict], config: dict) -> dict:
    shards = sorted(shards, key=lambda s: s["cluster"])
    records = [r for shard in shards for r in shard["records"]]
    base = duel.build_config(arm="none", select_worlds=config["baseline_select_worlds"],
                             report_worlds=config["report_worlds"])
    out = duel.summarize(records, base, seed0=config["seed0"],
                         replicates=config.get("bootstrap_replicates", DEFAULT_BOOTSTRAP_REPLICATES))
    totals = out["work_totals"]

    def ratio(name):
        denominator = totals["baseline"].get(name, 0)
        return totals["arm"].get(name, 0) / denominator if denominator else None

    cpu = ratio("decision_cpu_seconds")
    cost_matched = cpu is not None and PARITY_BAND[0] <= cpu <= PARITY_BAND[1]
    per_cluster = per_cluster_utility(records)
    problems = list(out["problems"])
    if cpu is None:
        problems.append("no baseline decision CPU measured")
    elif not cost_matched:
        problems.append(f"measured decision-CPU ratio {cpu:.4f} outside the parity band "
                        f"{PARITY_BAND}: a cost-unmatched result, not an equal-work claim")
    leaf_kind = "points head" if config["arm"] == "learned" else "stratified points prior"
    out.update({
        "schema": SUMMARY_SCHEMA,
        "claim": ("DEV equal-work screen on fresh deals; descriptive only: not confirmation, "
                  "promotion or deployment"),
        "arm": config["arm"], "arm_policy": config["arm_policy"],
        "arm_description": (f"{VLEAF_BASE_POLICY} with its rollout leaf replaced after "
                            f"{config['leaf_tricks']} trick(s) by the {leaf_kind} "
                            f"(final attacker points); selection N={config['arm_select_worlds']} "
                            f"from CPU calibration, report R={config['report_worlds']} unchanged; "
                            f"baseline N={config['baseline_select_worlds']}/R={config['report_worlds']}"),
        "leaf_tricks": config["leaf_tricks"],
        "config": config,
        "completed_clusters": len(shards), "requested_clusters": config["clusters"],
        "complete": len(shards) == config["clusters"],
        "arm_over_baseline_decision_cpu": cpu,
        "arm_over_baseline_decision_wall": ratio("decision_wall_seconds"),
        "arm_over_baseline_rollouts": ratio("rollouts"),
        "cpu_parity_band": list(PARITY_BAND),
        "cost_matched": cost_matched,
        "leaf_counters": {side: {name: totals[side].get(name, 0) for name in (
            *LEAF_COUNTERS, "nn_calls", "prior_lookups", "rollouts", "continuation_rollouts",
            "play_calls", "searches", "short_searches", "zero_world", "decision_cpu_seconds",
            "leaf_secs")}
            for side in ("arm", "baseline")},
        "per_cluster_arm_utility": per_cluster,
        "minimum_detectable_effect": {
            "this_run": minimum_detectable_effect(per_cluster.values()),
            "projected_1024_clusters": minimum_detectable_effect(per_cluster.values(), clusters=1024),
        },
        "equal_work_strength_claim": False,
        "work_caveat": ("N was chosen on calibration deals' decision CPU, never on outcomes. "
                        "The measured CPU ratio of THIS run is the cost fact; outside the band "
                        "the result is cost-unmatched. A learned-minus-prior contrast on the same "
                        "deals isolates the leaf estimator from truncation and dose."),
        "problems": problems,
    })
    return out


def combined_summary(summaries: dict[str, dict], *, seed0: int,
                     replicates: int = DEFAULT_BOOTSTRAP_REPLICATES) -> dict:
    """Both arms on the same deals: the learned-minus-prior paired contrast."""
    out = {"schema": COMBINED_SCHEMA, "seed0": seed0,
           "claim": "DEV screen; descriptive; equal_work_strength_claim is False for every arm",
           "arms": {}, "equal_work_strength_claim": False}
    for arm, s in summaries.items():
        out["arms"][arm] = {
            "arm_policy": s["arm_policy"], "rounds": s["rounds"], "clusters": s["clusters"],
            "arm_signed_level_utility_per_round": s["arm_signed_level_utility"]["per_round"],
            "arm_win_rate": s["arm_win_rate"], "role_splits": s["role_splits"],
            "arm_over_baseline_decision_cpu": s["arm_over_baseline_decision_cpu"],
            "cost_matched": s["cost_matched"],
            "leaf_counters": s["leaf_counters"]["arm"],
            "minimum_detectable_effect": s["minimum_detectable_effect"],
            "problems": s["problems"],
        }
    if {"learned", "prior"} <= set(summaries):
        learned = summaries["learned"]["per_cluster_arm_utility"]
        prior = summaries["prior"]["per_cluster_arm_utility"]
        common = sorted(set(learned) & set(prior))
        diffs = [learned[c] - prior[c] for c in common]
        out["learned_minus_prior"] = {
            "clusters": len(common),
            "per_round_utility_difference": duel.cluster_bootstrap(
                diffs, replicates=replicates, seed=duel.DEFAULT_BOOTSTRAP_SEED + 7),
            "note": ("each arm's utility is against production on the same mirrored deals; "
                     "this is a paired-by-deal contrast, not a direct learned-vs-prior duel"),
        }
    return out


# ------------------------------------------------------------------ driver

def run_arm(config: dict, *, output: Path, workers: int, log=print,
            executor_factory=None) -> dict:
    output = Path(output)
    bind_output_config(output, config)
    shards, pending = _resume(output, config)
    log(f"run: {config['arm_policy']} N={config['arm_select_worlds']} "
        f"({len(shards)}/{config['clusters']} pairs done)")
    summary = None
    try:
        _run_pending(config, pending, shards, output=output, workers=workers, task_fn=run_cluster,
                     executor_factory=executor_factory)
    finally:
        if shards:
            summary = summary_for(shards, config)
            _publish(output / "summary.json", summary)
    if summary is None:
        raise ScreenError("no completed pair to summarize")
    return summary
