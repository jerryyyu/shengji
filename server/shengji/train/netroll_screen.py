"""Net-rollout screen (DEV): coarse cost calibration and the paired mirrored
duel of ``mc-netroll-<ckpt8>-k<K>[-all]`` against production.

Arms (``net_rollout.py``): ``learned`` = production's search with the
complete-world net driving the first ``K`` tricks of every continuation in
lockstep; ``prior`` = the same lockstep with the checkpoint's stratified
prior choosing the play (the no-learning control); ``reference`` =
production at ``x<m>`` its dose (``registry.register_scaled_policies``),
production's own compute curve.  The baseline is always
``mc-s0-report-lcb`` at its registered N=30 / R=300, and every arm keeps
that N/R: the treatment is the rollout policy, never the dose.

Compute is a budget, not a gate (Jerry, 2026-09-05): ``calibrate`` measures
the arm's decision CPU/wall against production per ``K`` on outcome-blind
deals and reports the ratios; ``run`` reports the measured ratios of the
screen itself next to the utility interval.  Nothing refuses on cost.  A
calibration binds the checkpoint, net_stage, the K list, the baseline dose
and the rank cycle; a run that names a calibration must match it.

Both mirrors of one seeded deal are one atomic, resumable shard
(``search_screen._run_pending``); ``equal_work_strength_claim`` is always
False.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Sequence

from ..ai.cwv_policy import file_sha256
from ..ai.registry import REGISTRY, make_bot, scaled_policy_name
from ..engine.cards import RANKS
from ..oracle import screen as duel
from .leaf_screen import (DEFAULT_BOOTSTRAP_REPLICATES, DEFAULT_TRUMP_RANKS, _game_factory_for,
                          _runtime, cycle_rank, minimum_detectable_effect, parse_trump_ranks,
                          per_cluster_utility)
from .net_rollout import (COUNTERS, NET_STAGES, NETROLL_BASE_POLICY, MCNetRolloutSearch,
                          NetRolloutError, checkpoint_id, make_netroll_bot,
                          netroll_policy_name, register_netroll_policies)
from .search_screen import (TimedPolicy, _publish, _run_pending, bind_output_config,
                            execution_source_identity)

CONFIG_SCHEMA = "netroll-screen-config-v1"
CALIBRATION_SCHEMA = "netroll-calibration-v1"
SUMMARY_SCHEMA = "netroll-screen-summary-v1"
COMBINED_SCHEMA = "netroll-screen-combined-v1"
ARMS = ("learned", "prior", "reference")
BASELINE_SELECT_WORLDS = 30
REPORT_WORLDS = 300
REFERENCE_MULTIPLIER = 3
DEFAULT_TRICKS = (1, 2, 4)
#: fresh seed spaces, apart from every training window and the vleaf/cwv
#: screens (50_260_904 + 1024 and 50_360_904 + calibration)
DEFAULT_SEED0 = 50_460_904
DEFAULT_CALIBRATION_SEED0 = 50_560_904
BINDING_FIELDS = ("checkpoint_sha256", "net_stage", "tricks", "baseline_policy",
                  "baseline_select_worlds", "report_worlds", "trump_ranks")


class ScreenError(RuntimeError):
    pass


# ------------------------------------------------------------ identity

def calibration_binding(*, checkpoint_sha256: str, net_stage: str, tricks: Sequence[int],
                        baseline_select_worlds: int, report_worlds: int,
                        trump_ranks: Sequence[str]) -> dict:
    """What a calibration is the cost table FOR."""
    if net_stage not in NET_STAGES:
        raise ScreenError(f"net_stage must be one of {NET_STAGES}")
    return {"checkpoint_sha256": str(checkpoint_sha256), "net_stage": str(net_stage),
            "tricks": sorted({int(k) for k in tricks}), "baseline_policy": NETROLL_BASE_POLICY,
            "baseline_select_worlds": int(baseline_select_worlds),
            "report_worlds": int(report_worlds), "trump_ranks": list(trump_ranks)}


def calibration_identity(binding: dict) -> str:
    raw = json.dumps(binding, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def require_matching_calibration(calibration: dict, *, checkpoint_sha256: str, net_stage: str,
                                 net_tricks: int, baseline_select_worlds: int,
                                 report_worlds: int, trump_ranks: Sequence[str]) -> None:
    """Refuse a calibration made for another matchup: checkpoint, net_stage,
    a K outside its list, the baseline dose or the rank cycle."""
    binding = calibration.get("binding")
    if not isinstance(binding, dict) or any(f not in binding for f in BINDING_FIELDS):
        raise ScreenError("calibration carries no complete binding")
    if calibration.get("identity_sha256") != calibration_identity(binding):
        raise ScreenError("calibration identity does not hash its binding")
    problems = []
    if binding["checkpoint_sha256"] != checkpoint_sha256:
        problems.append(f"checkpoint {binding['checkpoint_sha256'][:8]} != {checkpoint_sha256[:8]}")
    if binding["net_stage"] != net_stage:
        problems.append(f"net_stage {binding['net_stage']!r} != {net_stage!r}")
    if int(net_tricks) not in binding["tricks"]:
        problems.append(f"net_tricks K={net_tricks} not in calibrated {binding['tricks']}")
    if binding["baseline_policy"] != NETROLL_BASE_POLICY:
        problems.append(f"baseline {binding['baseline_policy']!r} != {NETROLL_BASE_POLICY!r}")
    if binding["baseline_select_worlds"] != int(baseline_select_worlds):
        problems.append("baseline selection worlds differ")
    if binding["report_worlds"] != int(report_worlds):
        problems.append(f"report worlds {binding['report_worlds']} != {report_worlds}")
    if list(binding["trump_ranks"]) != list(trump_ranks):
        problems.append(f"trump ranks {binding['trump_ranks']} != {list(trump_ranks)}")
    if problems:
        raise ScreenError("calibration was made for another matchup: " + "; ".join(problems))


def load_calibration(path: str | os.PathLike) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        calibration = json.load(fh)
    if calibration.get("schema") != CALIBRATION_SCHEMA:
        raise ScreenError(f"{path}: not a {CALIBRATION_SCHEMA} calibration")
    if calibration.get("outcomes_read") is not False:
        raise ScreenError(f"{path}: calibration does not attest outcome blindness")
    calibration["file_sha256"] = file_sha256(path)
    return calibration


# ------------------------------------------------------------ policies

def arm_label(arm: str, net_tricks: int | None, multiplier: float = REFERENCE_MULTIPLIER) -> str:
    if arm == "reference":
        return f"reference-x{float(multiplier):g}"
    return f"{arm}-k{int(net_tricks)}"


def arm_policy_name(config: dict) -> str:
    arm = config["arm"]
    if arm == "reference":
        return scaled_policy_name(NETROLL_BASE_POLICY, config["reference_multiplier"])
    return netroll_policy_name(config["checkpoint_sha256"][:8], int(config["net_tricks"]),
                               net_stage=config["net_stage"], prior=(arm == "prior"))


def require_bound_bytes(what: str, actual: str | None, expected: str | None) -> None:
    if not expected or actual != expected:
        raise ScreenError(f"{what} bytes differ from the config's binding: {actual} != {expected}")


def ensure_registered(config: dict) -> str:
    """Register the arm's name in THIS process (workers are spawned) after
    checking the checkpoint file is still the bytes the config bound."""
    require_bound_bytes("checkpoint file", file_sha256(config["checkpoint"]),
                        config.get("checkpoint_sha256"))
    register_netroll_policies(config["checkpoint"], (int(config["net_tricks"]),),
                              (config["net_stage"],))
    return arm_policy_name(config)


def make_side(config: dict, side: str, seed: int):
    if side == "baseline":
        bot = make_bot(NETROLL_BASE_POLICY, seed=seed)
    elif config["arm"] == "reference":
        name = arm_policy_name(config)
        if name not in REGISTRY:
            raise ScreenError(f"reference policy {name!r} is not registered")
        return make_bot(name, seed=seed)        # its dose is the registered multiple
    else:
        bot = make_bot(ensure_registered(config), seed=seed)
        require_bound_bytes("checkpoint", bot.netroll_checkpoint_sha256,
                            config.get("checkpoint_sha256"))
        if bot.netroll_prior != (config["arm"] == "prior") or bot.NET_TRICKS != config["net_tricks"] \
                or bot.NET_STAGE != config["net_stage"]:
            raise ScreenError(f"registered arm {config['arm_policy']!r} does not match the config")
    bot.N_DETERMINIZATIONS = int(config["baseline_select_worlds"])
    bot.REPORT_FOLD_WORLDS = int(config["report_worlds"])
    return bot


class NetrollTimedPolicy(TimedPolicy):
    """``TimedPolicy`` plus every play call and the per-decision net record."""

    def __init__(self, bot):
        super().__init__(bot)
        self.play_calls = 0

    def decide_play(self, rnd, seat):
        self.play_calls += 1
        recorded = len(self.decisions)
        try:
            return super().decide_play(rnd, seat)
        finally:
            if len(self.decisions) > recorded:
                rec = self.bot.last_decision_record or {}
                self.decisions[-1]["net_rollout"] = rec.get("net_rollout")
                self.decisions[-1]["search_secs"] = rec.get("search_secs")


TIMING_FIELDS = ("netroll_sim_secs", "netroll_net_secs")


def work_counters(bots) -> dict:
    """Production counters plus decision CPU/wall and the lockstep's own."""
    out = duel.work_counters(bots)
    for name in ("decision_cpu_seconds", "decision_wall_seconds", *TIMING_FIELDS):
        out[name] = float(sum(getattr(b, name, 0.0) for b in bots))
    out["play_calls"] = int(sum(getattr(b, "play_calls", 0) for b in bots))
    # The lockstep's own counters, prefixed so production's ``rollouts`` (the
    # continuations the search scored, kept by the arm too) stays intact.  The
    # evaluator's cumulative clocks are NOT summed: one shared evaluator serves
    # every bot of a worker process, so they would be counted once per bot.
    for name in COUNTERS:
        out[f"netroll_{name}"] = int(sum(
            (getattr(b, "netroll_counts", None) or {}).get(name, 0) for b in bots))
    return out


# ------------------------------------------------------------------ rounds

def run_cluster(config: dict, cluster: int) -> dict:
    created = []

    def factory(_config, side, seed):
        wrapped = NetrollTimedPolicy(make_side(config, side, seed))
        created.append((side, wrapped))
        return wrapped

    rank = cycle_rank(config, cluster)
    base = duel.build_config(arm="none", select_worlds=config["baseline_select_worlds"],
                             report_worlds=config["report_worlds"])
    seed = config["seed0"] + cluster
    rows = [duel.play_screen_round(base, cluster, seed, mirror, bot_factory=factory,
                                   counter_fn=work_counters,
                                   game_factory=_game_factory_for(rank))
            for mirror in (0, 1)]
    policy = arm_policy_name(config)
    for record, _ in rows:
        if record["trump_rank"] != rank:
            raise ScreenError(f"cluster {cluster} dealt trump rank {record['trump_rank']!r}, "
                              f"expected {rank!r}")
        record["arm"] = config["arm"]
        record["arm_policy"] = policy
        record["net_tricks"] = config.get("net_tricks")
        record["net_stage"] = config.get("net_stage")
    return {"cluster": cluster, "seed": seed, "rank": rank, "arm_policy": policy,
            "records": [r for r, _ in rows], "timings": [t for _, t in rows],
            "decision_traces": [{"mirror": i // 4, "side": side, "decisions": bot.decisions}
                                for i, (side, bot) in enumerate(created)]}


def reopen_shard(path: Path, config: dict, cluster: int) -> dict:
    shard = json.loads(Path(path).read_text())
    rows = shard.get("records", [])
    seed = config["seed0"] + cluster
    rank = cycle_rank(config, cluster)
    if (shard.get("cluster") != cluster or shard.get("seed") != seed
            or shard.get("rank") != rank or len(rows) != 2
            or [r.get("mirror") for r in rows] != [0, 1]
            or any(r.get("cluster") != cluster or r.get("seed") != seed
                   or r.get("trump_rank") != rank or r.get("arm") != config["arm"]
                   or r.get("arm_policy") != config["arm_policy"]
                   or r.get("net_tricks") != config.get("net_tricks")
                   or r.get("net_stage") != config.get("net_stage")
                   for r in rows)):
        raise ValueError("completed shard does not contain its exact mirrored pair")
    return shard


def _resume(output: Path, config: dict) -> tuple[list[dict], list[int]]:
    shards, pending = [], []
    for cluster in range(config["clusters"]):
        path = output / f"cluster-{cluster:05}.json"
        if path.exists():
            shards.append(reopen_shard(path, config, cluster))
        else:
            pending.append(cluster)
    return shards, pending


# ------------------------------------------------------------------ config

def build_config(*, arm: str, net_tricks: int | None, net_stage: str, seed0: int, clusters: int,
                 checkpoint: str | None, baseline_select_worlds: int = BASELINE_SELECT_WORLDS,
                 report_worlds: int = REPORT_WORLDS, trump_ranks: Sequence[str] | None = None,
                 reference_multiplier: float = REFERENCE_MULTIPLIER, calibration: dict | None = None,
                 bootstrap_replicates: int = DEFAULT_BOOTSTRAP_REPLICATES) -> dict:
    if arm not in ARMS:
        raise ScreenError(f"arm must be one of {ARMS}")
    if net_stage not in NET_STAGES:
        raise ScreenError(f"net_stage must be one of {NET_STAGES}")
    if clusters < 1 or baseline_select_worlds < 1:
        raise ScreenError("clusters and selection worlds must be positive")
    if report_worlds < 30:
        raise ScreenError("the LCB report needs at least 30 paired worlds")
    if os.environ.get("SHENGJI_REQUIRE_VOIDS") != "1":
        raise ScreenError("SHENGJI_REQUIRE_VOIDS=1 is required")
    ranks = (parse_trump_ranks(",".join(trump_ranks)) if trump_ranks is not None
             else DEFAULT_TRUMP_RANKS)
    if arm == "reference":
        if float(reference_multiplier) <= 1:
            raise ScreenError("the reference multiplier must exceed 1")
        net_tricks = None
    elif type(net_tricks) is not int or net_tricks < 1:
        raise ScreenError("the learned and prior arms need net_tricks K >= 1")
    config = {
        "schema": CONFIG_SCHEMA, "arm": arm, "net_tricks": net_tricks, "net_stage": net_stage,
        "seed0": int(seed0), "clusters": int(clusters),
        "baseline_select_worlds": int(baseline_select_worlds),
        "report_worlds": int(report_worlds), "base_policy": NETROLL_BASE_POLICY,
        "reference_multiplier": float(reference_multiplier),
        "bootstrap_replicates": int(bootstrap_replicates), "trump_ranks": list(ranks),
    }
    if checkpoint:
        path = str(Path(checkpoint).resolve())
        try:
            probe = make_netroll_bot(path, net_tricks=int(net_tricks or 1), net_stage=net_stage,
                                     prior=(arm == "prior"))
        except NetRolloutError as exc:
            raise ScreenError(str(exc)) from exc
        config.update({"checkpoint": path, "checkpoint_sha256": probe.netroll_checkpoint_sha256,
                       "checkpoint_id": probe.netroll_ckpt8,
                       "evaluator": probe.evaluator.identity()})
    elif arm != "reference":
        raise ScreenError(f"the {arm} arm needs --checkpoint")
    config["arm_policy"] = arm_policy_name(config)
    config["arm_label"] = arm_label(arm, net_tricks, reference_multiplier)
    if calibration is not None:
        if arm == "reference":
            raise ScreenError("the reference arm has no calibration")
        require_matching_calibration(
            calibration, checkpoint_sha256=config["checkpoint_sha256"], net_stage=net_stage,
            net_tricks=int(net_tricks), baseline_select_worlds=baseline_select_worlds,
            report_worlds=report_worlds, trump_ranks=ranks)
        config["calibration"] = {"file_sha256": calibration.get("file_sha256"),
                                 "identity_sha256": calibration["identity_sha256"],
                                 "binding": calibration["binding"],
                                 "cost": next((row for row in calibration.get("table", [])
                                               if row.get("net_tricks") == net_tricks), None)}
    package = Path(__file__).resolve().parents[1]
    config["source_sha256"] = execution_source_identity(package)
    config["runtime"] = _runtime()
    return config


# ------------------------------------------------------------- calibration

COST_FIELDS = ("decision_cpu_seconds", "decision_wall_seconds", "play_calls", "search_calls",
               "rollouts", "netroll_sim_secs", "netroll_net_secs",
               *(f"netroll_{name}" for name in COUNTERS))


def cost_table(shards: Sequence[dict]) -> dict:
    """Outcome-blind cost view of the shards: CPU, wall and work fields only."""
    totals = {side: {name: 0.0 for name in COST_FIELDS} for side in ("arm", "baseline")}
    for shard in shards:
        for record in shard["records"]:
            for side in ("arm", "baseline"):
                work = record["work"][side]
                for name in COST_FIELDS:
                    totals[side][name] += float(work.get(name, 0))

    def per_decision(side, name):
        calls = totals[side]["play_calls"]
        return totals[side][name] / calls if calls else None

    def ratio(name):
        base = totals["baseline"][name]
        return totals["arm"][name] / base if base else None

    arm = totals["arm"]
    return {
        "decision_cpu_ratio": ratio("decision_cpu_seconds"),
        "decision_wall_ratio": ratio("decision_wall_seconds"),
        "rollout_ratio": ratio("rollouts"),
        "per_decision_cpu_seconds": {s: per_decision(s, "decision_cpu_seconds") for s in totals},
        "per_decision_wall_seconds": {s: per_decision(s, "decision_wall_seconds") for s in totals},
        "per_decision_net_plays": per_decision("arm", "netroll_net_plays"),
        "per_decision_net_positions": per_decision("arm", "netroll_net_positions"),
        "per_decision_batches": per_decision("arm", "netroll_batches"),
        "per_net_position_usecs": (1e6 * arm["netroll_net_secs"] / arm["netroll_net_positions"]
                                   if arm["netroll_net_positions"] else None),
        "per_heuristic_play_usecs": (
            1e6 * (arm["netroll_sim_secs"] - arm["netroll_net_secs"]) / arm["netroll_heuristic_plays"]
            if arm["netroll_heuristic_plays"] else None),
        "net_share_of_decision_wall": (arm["netroll_net_secs"] / arm["decision_wall_seconds"]
                                       if arm["decision_wall_seconds"] else None),
        "play_calls": {s: int(totals[s]["play_calls"]) for s in totals},
        "totals": {s: dict(totals[s]) for s in totals},
    }


def calibrate(config: dict, *, output: Path, workers: int, tricks=DEFAULT_TRICKS, log=print,
              executor_factory=None) -> dict:
    """Run the learned arm at every K on the calibration deals (resumable per
    K) and publish the cost table; ratios are REPORTED, never gated."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    if config["arm"] != "learned":
        raise ScreenError("calibration measures the learned arm")
    tricks = tuple(sorted({int(k) for k in tricks}))
    if not tricks or min(tricks) < 1:
        raise ScreenError("tricks must be positive integers")
    started = time.perf_counter()
    table = []
    for k in tricks:
        sub = output / f"k-{k}"
        cfg = dict(config, net_tricks=k)
        cfg["arm_policy"] = arm_policy_name(cfg)
        cfg["arm_label"] = arm_label("learned", k)
        cfg["calibration_tricks"] = list(tricks)
        bind_output_config(sub, cfg)
        shards, pending = _resume(sub, cfg)
        log(f"calibrate: K={k} {cfg['arm_policy']} ({len(shards)}/{cfg['clusters']} pairs done)")
        _run_pending(cfg, pending, shards, output=sub, workers=workers, task_fn=run_cluster,
                     executor_factory=executor_factory)
        table.append({"net_tricks": k, "arm_policy": cfg["arm_policy"],
                      "clusters": len(shards), **cost_table(shards)})
    binding = calibration_binding(
        checkpoint_sha256=config["checkpoint_sha256"], net_stage=config["net_stage"],
        tricks=tricks, baseline_select_worlds=config["baseline_select_worlds"],
        report_worlds=config["report_worlds"], trump_ranks=config["trump_ranks"])
    calibration = {
        "schema": CALIBRATION_SCHEMA,
        "claim": ("coarse cost calibration: decision CPU/wall ratios of the learned arm per K "
                  "against production at the same N/R; reported, not gated; outcomes of the "
                  "calibration deals were never read"),
        "outcomes_read": False,
        "binding": binding, "identity_sha256": calibration_identity(binding),
        "seed0": config["seed0"], "clusters": config["clusters"],
        "seeds": [config["seed0"] + c for c in range(config["clusters"])],
        "table": table,
        "wall_secs": round(time.perf_counter() - started, 3),
        "runtime": _runtime(), "source_sha256": config["source_sha256"],
    }
    _publish(output / "calibration.json", calibration)
    return calibration


# ----------------------------------------------------------------- summary

def summary_for(shards: Sequence[dict], config: dict) -> dict:
    shards = sorted(shards, key=lambda s: s["cluster"])
    records = [r for shard in shards for r in shard["records"]]
    base = duel.build_config(arm="none", select_worlds=config["baseline_select_worlds"],
                             report_worlds=config["report_worlds"])
    out = duel.summarize(records, base, seed0=config["seed0"],
                         replicates=config.get("bootstrap_replicates", DEFAULT_BOOTSTRAP_REPLICATES))
    cost = cost_table(shards)
    per_cluster = per_cluster_utility(records)
    problems = list(out["problems"])
    trump_ranks = list(config.get("trump_ranks") or DEFAULT_TRUMP_RANKS)
    dealt = sorted({str(r["trump_rank"]) for r in records}, key=RANKS.index)
    if any(r not in trump_ranks for r in dealt):
        problems.append(f"rounds dealt trump ranks {dealt} outside the configured cycle {trump_ranks}")
    arm = config["arm"]
    description = {
        "learned": (f"{NETROLL_BASE_POLICY} with the complete-world net as the rollout policy for "
                    f"the first K={config['net_tricks']} trick(s) of every continuation "
                    f"(stage {config['net_stage']}), lockstep-batched; N/R unchanged"),
        "prior": (f"{NETROLL_BASE_POLICY} with the checkpoint's stratified prior choosing the "
                  f"first K={config['net_tricks']} trick(s) (no-learning control, stage "
                  f"{config['net_stage']}); N/R unchanged"),
        "reference": (f"{NETROLL_BASE_POLICY} at x{config['reference_multiplier']:g} its "
                      f"selection and report dose (production's compute curve)"),
    }[arm]
    out.update({
        "schema": SUMMARY_SCHEMA,
        "claim": ("DEV screen on fresh deals; descriptive only: not confirmation, promotion or "
                  "deployment; compute is reported as a budget, not gated"),
        "arm": arm, "arm_label": config["arm_label"], "arm_policy": config["arm_policy"],
        "arm_description": description,
        "net_tricks": config.get("net_tricks"), "net_stage": config.get("net_stage"),
        "trump_ranks": trump_ranks, "trump_ranks_dealt": dealt,
        "config": config,
        "completed_clusters": len(shards), "requested_clusters": config["clusters"],
        "complete": len(shards) == config["clusters"],
        "cost": cost,
        "arm_over_baseline_decision_cpu": cost["decision_cpu_ratio"],
        "arm_over_baseline_decision_wall": cost["decision_wall_ratio"],
        "arm_over_baseline_rollouts": cost["rollout_ratio"],
        "budget_reported_not_gated": True,
        "per_cluster_arm_utility": per_cluster,
        "minimum_detectable_effect": {
            "this_run": minimum_detectable_effect(per_cluster.values()),
            "projected_1024_clusters": minimum_detectable_effect(per_cluster.values(), clusters=1024),
        },
        "equal_work_strength_claim": False,
        "problems": problems,
    })
    return out


def combined_summary(summaries: dict[str, dict], *, seed0: int,
                     replicates: int = DEFAULT_BOOTSTRAP_REPLICATES) -> dict:
    """Every arm on the same deals plus the learned-minus-prior contrast per K."""
    out = {"schema": COMBINED_SCHEMA, "seed0": seed0,
           "claim": "DEV screen; descriptive; equal_work_strength_claim is False for every arm",
           "arms": {}, "learned_minus_prior": {}, "equal_work_strength_claim": False}
    for label, s in summaries.items():
        out["arms"][label] = {
            "arm": s["arm"], "arm_policy": s["arm_policy"], "net_tricks": s.get("net_tricks"),
            "net_stage": s.get("net_stage"), "rounds": s["rounds"], "clusters": s["clusters"],
            "trump_ranks_dealt": s["trump_ranks_dealt"],
            "arm_signed_level_utility_per_round": s["arm_signed_level_utility"]["per_round"],
            "arm_win_rate": s["arm_win_rate"], "role_splits": s["role_splits"],
            "arm_over_baseline_decision_cpu": s["arm_over_baseline_decision_cpu"],
            "arm_over_baseline_decision_wall": s["arm_over_baseline_decision_wall"],
            "cost": {k: v for k, v in s["cost"].items() if k != "totals"},
            "minimum_detectable_effect": s["minimum_detectable_effect"],
            "problems": s["problems"],
        }
    by_k = {}
    for label, s in summaries.items():
        if s["arm"] in ("learned", "prior"):
            by_k.setdefault(s["net_tricks"], {})[s["arm"]] = s
    for k, pair in sorted(by_k.items()):
        if {"learned", "prior"} <= set(pair):
            learned = pair["learned"]["per_cluster_arm_utility"]
            prior = pair["prior"]["per_cluster_arm_utility"]
            common = sorted(set(learned) & set(prior))
            out["learned_minus_prior"][f"k{k}"] = {
                "clusters": len(common),
                "per_round_utility_difference": duel.cluster_bootstrap(
                    [learned[c] - prior[c] for c in common], replicates=replicates,
                    seed=duel.DEFAULT_BOOTSTRAP_SEED + 11 + int(k)),
                "note": ("each arm's utility is against production on the same mirrored deals; "
                         "a paired-by-deal contrast, not a direct learned-vs-prior duel"),
            }
    return out


# ------------------------------------------------------------------ driver

def run_arm(config: dict, *, output: Path, workers: int, log=print, executor_factory=None) -> dict:
    output = Path(output)
    bind_output_config(output, config)
    shards, pending = _resume(output, config)
    log(f"run: {config['arm_label']} {config['arm_policy']} "
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
