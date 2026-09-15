"""Resumable mirrored screen for the exhaustive complete-world shortlist."""
from __future__ import annotations

import argparse
import copy
from contextlib import contextmanager
from dataclasses import asdict
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import platform

from ..ai.cwv_policy import shared_evaluator
from ..ai.registry import make_bot
from ..oracle import screen as duel
from .cwv_shortlist import CWVShortlistBot, CWVShortlistConfig
from .cwv_double_shortlist import CWVDoubleShortlistBot
from .cwv_throw_aware import CWVThrowComponentsBot, CWVThrowComponentsBuryBot
from .cwv_bury_policy import CWVBuryBot
from .cwv_corrected_rollout import CWVCorrectedRolloutBot, CWVCorrectedRolloutBuryBot
from .cwv_wide_tail import CWVWideTailBot, CWVWideTailConfig
from .cwv_prior_admission import CWVPriorAdmissionBot, CWVPriorAdmissionConfig
from .cwv_truncated_search import CWVTruncatedSearchBot, CWVPriorTruncatedSearchBot
from .leaf_screen import _game_factory_for, parse_trump_ranks
from .search_screen import (
    TimedPolicy, _publish, _run_pending, bind_output_config,
    execution_source_identity,
)
from .screen_deadline import DeadlineSession, RECIPE as DEADLINE_RECIPE, latency_summary, validate_deadline

BASELINE_SELECT_WORLDS = 30
BASELINE_REPORT_WORLDS = 300
RANK = "2"
ARMS = ("learned", "uniform", "production", "identity")


class CWVWideTailBuryBot(CWVBuryBot, CWVWideTailBot):
    """Full-completion hybrid bury layered onto the wide-tail play hook."""


@contextmanager
def screen_output_lock(output: Path):
    """One writer per output; the persistent inode also survives stale PID files.

    Do not unlink this file on exit: another process could already be waiting
    on its inode. Spawned workers return rows to the parent, which is the only
    publisher. An interrupted parent releases its OS lock without deleting pairs.
    """
    output.mkdir(parents=True, exist_ok=True)
    with (output / ".screen.lock").open("a+") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise ValueError(f"screen output is already in use: {output}") from exc
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def rank_for(config: dict, cluster: int) -> str:
    """Return the configured rank for a cluster, preserving legacy rank 2."""
    ranks = config.get("trump_ranks") or (RANK,)
    return ranks[cluster % len(ranks)]


def _cost_order(directory: Path, clusters, seed0: int, trump_ranks=None) -> dict:
    """Read prior completed shard timings for execution-only scheduling."""
    costs = {}
    directory = directory.resolve()
    for cluster in clusters:
        path = directory / f"cluster-{cluster:05}.json"
        if not path.is_file():
            raise ValueError(f"cost-order artifact missing cluster {cluster}: {path}")
        try:
            shard = json.loads(path.read_text())
        except (OSError, ValueError) as exc:
            raise ValueError(f"invalid cost-order artifact for cluster {cluster}") from exc
        expected_seed = seed0 + cluster
        rank = rank_for({"trump_ranks": trump_ranks}, cluster)
        if (shard.get("schema") != "cwv-shortlist-shard-v1"
                or type(shard.get("cluster")) is not int
                or shard.get("cluster") != cluster
                or type(shard.get("seed")) is not int
                or shard.get("seed") != expected_seed
                or shard.get("rank") != rank):
            raise ValueError(f"cost-order artifact drift for cluster {cluster}")
        timings = shard.get("timings")
        if type(timings) is not list or len(timings) != 2:
            raise ValueError(f"cost-order artifact requires two mirrors for cluster {cluster}")
        walls = []
        mirrors = []
        for timing in timings:
            if type(timing) is not dict:
                raise ValueError(f"invalid cost-order timing for cluster {cluster}")
            mirror = timing.get("mirror")
            wall = timing.get("wall_secs")
            if (type(mirror) is not int or mirror not in (0, 1)
                    or mirror in mirrors
                    or type(timing.get("cluster")) is not int
                    or timing.get("cluster") != cluster
                    or type(timing.get("seed")) is not int
                    or timing.get("seed") != expected_seed
                    or type(wall) not in (int, float) or isinstance(wall, bool)
                    or not math.isfinite(wall) or wall < 0):
                raise ValueError(f"invalid cost-order timing for cluster {cluster}")
            mirrors.append(mirror)
            walls.append(wall)
        costs[cluster] = sum(walls)
        if not math.isfinite(costs[cluster]):
            raise ValueError(f"nonfinite cost-order total for cluster {cluster}")
    ordered = sorted(clusters, key=lambda cluster: (-costs[cluster], cluster))
    return {
        "source": str(directory),
        "criterion": "sum prior shard timings wall_secs",
        "clusters": ordered,
        "cluster_wall_secs": {str(cluster): costs[cluster] for cluster in ordered},
    }


class CwvTimedPolicy(TimedPolicy):
    """Attach the shortlist receipt, including forced singleton decisions."""

    def decide_play(self, rnd, seat):
        before = len(self.decisions)
        try:
            return super().decide_play(rnd, seat)
        finally:
            detail = copy.deepcopy(getattr(self.bot, "last_shortlist", None))
            if detail is not None:
                if len(self.decisions) > before:
                    self.decisions[-1]["cwv_shortlist"] = detail
                else:
                    # TimedPolicy records only decisions with the inherited MC
                    # record. A forced singleton still needs a durable trace.
                    self.decisions.append({
                        "seat": seat,
                        "trick": len(rnd.history),
                        "forced": True,
                        "cwv_shortlist": detail,
                    })
            inner = getattr(self.bot, "last_double_shortlist", None)
            if inner is not None and len(self.decisions) > before:
                self.decisions[-1]["cwv_double_shortlist"] = copy.deepcopy(inner)


def _shortlist_config(config: dict) -> CWVShortlistConfig:
    return CWVShortlistConfig(**config["shortlist"])


def _encoding(config: dict) -> str:
    """Reopen legacy configs as reference-encoded screens."""
    return config.get("encoding", "reference")


def _validate_corrected_config(config, correction):
    if (config["arm"] != "learned" or config.get("baseline") not in
            ("flat-shortlist", "levels-shortlist")):
        raise ValueError("corrected rollout requires learned with a shortlist baseline")
    if (config.get("baseline") == "levels-shortlist" and
            correction.get("mode") != "corrected"):
        raise ValueError("levels-shortlist requires corrected rollout mode")
    if any(key in config for key in ("double_shortlist", "value_head",
                                     "report_tie_keeps_incumbent", "throw_components",
                                     "wide_tail")):
        raise ValueError("corrected rollout cannot be combined with inner/value-head/tie options")
    if (correction.get("mode") not in ("corrected", "levels")
            or type(correction.get("correction_worlds")) is not int
            or type(correction.get("residual_worlds")) is not int
            or not 1 <= correction["residual_worlds"] <= correction["correction_worlds"]):
        raise ValueError("require 1 <= residual worlds <= correction worlds")


def _validate_wide_config(config):
    if "wide_tail" not in config:
        return
    arm = config["arm"]
    if (config.get("hybrid_bury")
            and (arm != "learned" or config.get("baseline") != "flat-shortlist"
                 or "double_shortlist" in config)):
        raise ValueError(
            "hybrid-bury requires learned with flat-shortlist baseline and no inner mode")
    if (arm != "learned" or "double_shortlist" in config
            or config.get("report_tie_keeps_incumbent")
            or config.get("value_head") is not None
            or config.get("throw_components")):
        raise ValueError("wide-tail screen requires isolated learned ranking")
    if config.get("hybrid_bury"):
        if config["wide_tail"] != asdict(CWVWideTailConfig()):
            raise ValueError("hybrid-bury requires the default wide-tail recipe")


def make_side(config: dict, side: str, seed: int):
    continuation = config.get('value_continuation')
    if continuation is not None:
        if (config['arm'] != 'learned' or config.get('baseline') != 'flat-shortlist'
                or any(config.get(k) for k in ('corrected_rollout', 'wide_tail',
                        'double_shortlist', 'throw_components', 'hybrid_bury',
                        'report_tie_keeps_incumbent'))
                or config.get('value_head') not in (None, 'outcome')):
            raise ValueError('value continuation requires isolated outcome-head learned/flat-shortlist')
        if (set(continuation) != {'tricks', 'baseline'}
                or continuation['tricks'] not in ('full', 0, 1, 2)
                or type(continuation['tricks']) is bool
                or continuation['baseline'] not in ('mc', 'full')):
            raise ValueError('invalid value continuation recipe')
    if (config.get("hybrid_bury")
            and (config["arm"] != "learned" or config.get("baseline") not in
                 ("flat-shortlist", "levels-shortlist")
                 or "double_shortlist" in config)):
        raise ValueError("hybrid-bury requires learned with a shortlist baseline and no inner mode")
    _validate_wide_config(config)
    if config.get("baseline") == "levels-shortlist" and not config.get("corrected_rollout"):
        raise ValueError("levels-shortlist requires corrected rollout configuration")
    if config.get("corrected_rollout") is not None:
        _validate_corrected_config(config, config["corrected_rollout"])
    correction = (config.get("corrected_rollout") if side == "arm"
                  or (side == "baseline" and config.get("baseline") == "levels-shortlist")
                  else None)
    arm = config["arm"]
    flat_baseline = side == "baseline" and config.get("baseline") == "flat-shortlist"
    shortlist_baseline = (side == "baseline" and
                          config.get("baseline") in ("flat-shortlist", "levels-shortlist"))
    if (side == "baseline" and not shortlist_baseline) or arm in ("identity", "production"):
        bot = make_bot("mc-s0-report-lcb", seed=seed)
        if side == "arm" and arm == "production":
            multiplier = int(config["production_multiplier"])
            bot.N_DETERMINIZATIONS = BASELINE_SELECT_WORLDS * multiplier
            bot.REPORT_FOLD_WORLDS = BASELINE_REPORT_WORLDS * multiplier
        else:
            bot.N_DETERMINIZATIONS = BASELINE_SELECT_WORLDS
            bot.REPORT_FOLD_WORLDS = BASELINE_REPORT_WORLDS
        return bot

    evaluator = None
    if arm == "learned":
        # #373: the value head rides in config.json and binds the ARM's evaluator
        # only; a flat-shortlist baseline built from the same config keeps the
        # checkpoint's own head (its evaluator is a separate cache entry).
        head = ('outcome' if continuation is not None else
                config.get("value_head") if side == "arm" else None)
        evaluator = shared_evaluator(config["checkpoint"], threads=1,
                                     max_batch=config.get(
                                         "batch_size",
                                         config["shortlist"]["batch_size"]),
                                     encoding=_encoding(config),
                                     **({"value_head": head} if head else {}))
        if evaluator.checkpoint_sha256 != config["checkpoint_sha256"]:
            raise ValueError("checkpoint changed between configuration and worker")
    inner = config.get("double_shortlist") if side == "arm" else None
    kwargs = dict(seed=seed, config=_shortlist_config(config),
                  reuse_successors=config.get("reuse_successors", False))
    if side == "arm" and "prior" in config and (
            arm != "learned" or inner is not None or correction is not None
            or any(config.get(k) for k in ("throw_components", "hybrid_bury", "wide_tail"))):
        raise ValueError("prior admission requires the plain learned shortlist arm")
    if continuation is not None:
        # Same admission on BOTH arms: isolate continuation from prior pruning.
        truncated = side == 'arm' or continuation['baseline'] == 'full'
        if 'prior' in config:
            cls = CWVPriorTruncatedSearchBot if truncated else CWVPriorAdmissionBot
            kwargs['prior'] = CWVPriorAdmissionConfig(**config['prior'])
        else:
            cls = CWVTruncatedSearchBot if truncated else CWVShortlistBot
        if truncated:
            horizon = continuation['tricks'] if side == 'arm' else 'full'
            kwargs['continuation_tricks'] = None if horizon == 'full' else horizon
        bot = cls(evaluator, **kwargs)
    elif side == "arm" and "wide_tail" in config and config.get("hybrid_bury"):
        bot = CWVWideTailBuryBot(evaluator, **kwargs, arm="hybrid")
    elif side == "arm" and "wide_tail" in config:
        bot = CWVWideTailBot(evaluator, **kwargs,
                             wide_tail=CWVWideTailConfig(**config["wide_tail"]))
    elif side == "arm" and "prior" in config:
        # #425 step 4: the learned prior prunes wide decisions on the ARM only;
        # it composes with nothing else in this first test (refused above).
        bot = CWVPriorAdmissionBot(evaluator, **kwargs,
                                   prior=CWVPriorAdmissionConfig(**config["prior"]))
    elif inner is not None:
        if inner.get("guidance") != "selection-fraction-ceil-v2":
            raise ValueError("double-shortlist guidance recipe is not selection-fraction-ceil-v2")
        bot = CWVDoubleShortlistBot(evaluator, **kwargs,
                                   inner_mode=inner["mode"],
                                   inner_worlds=inner["worlds"],
                                   inner_alternatives=4,
                                   inner_batch_size=inner["batch_size"],
                                   inner_reuse_successors=inner.get(
                                       "reuse_successors", False))
    else:
        if correction is None:
            cls = (CWVThrowComponentsBot if side == "arm" and
                   config.get("throw_components") else CWVShortlistBot)
            if config.get("hybrid_bury"):
                cls = (CWVThrowComponentsBuryBot if cls is CWVThrowComponentsBot
                       else CWVBuryBot)
                kwargs["arm"] = "hybrid"
            bot = cls(evaluator, **kwargs)
        else:
            cls = (CWVCorrectedRolloutBuryBot if config.get("hybrid_bury")
                   else CWVCorrectedRolloutBot)
            if config.get("hybrid_bury"):
                kwargs["arm"] = "hybrid"
            bot = cls(evaluator, **kwargs,
                      correction_mode=("levels" if side == "baseline" else correction["mode"]),
                      correction_worlds=correction["correction_worlds"],
                      residual_worlds=correction["residual_worlds"])
    bot.REPORT_FOLD_WORLDS = int(config["report_worlds"])
    # #339 layer 1: bound per window in config.json, applied to the ARM bot only.
    # A flat-shortlist baseline also reaches this point; it must stay at the
    # production default (a class attribute on MCBot, never modified).
    if side == "arm" and config.get("report_tie_keeps_incumbent"):
        bot.REPORT_TIE_KEEPS_INCUMBENT = True
    return bot


def work_counters(bots):
    out = duel.work_counters(bots)
    for bot in bots:
        for key, value in getattr(bot, "shortlist_counts", {}).items():
            name = "cwv_" + key
            out[name] = out.get(name, 0) + int(value)
        for key, value in getattr(bot, "double_shortlist_counts", {}).items():
            name = "double_" + key
            out[name] = out.get(name, 0) + int(value)
        for key, value in getattr(bot, "corrected_rollout_counts", {}).items():
            name = "correction_" + key
            out[name] = out.get(name, 0) + int(value)
        for key, value in getattr(bot, 'continuation_totals', {}).items():
            name = 'value_continuation_' + key
            out[name] = out.get(name, 0) + int(value)
    for key in ("decision_cpu_seconds", "decision_wall_seconds",
                "shortlist_wall_seconds"):
        out[key] = float(sum(getattr(bot, key, 0.0) for bot in bots))
    # Cheap complete-world evaluations are intentionally separate from the
    # inherited full heuristic continuations; they never inflate rollouts.
    out["cheap_evaluations"] = int(
        out.get("cwv_cheap_evaluations", 0) + out.get("correction_model_evaluations", 0))
    correction_sampled = out.get("correction_sampled_worlds", 0)
    correction_residual = out.get("correction_residual_worlds", 0)
    out["full_rollout_accepted_worlds"] = int(
        out["accepted_worlds"] - out.get("cwv_cheap_worlds", 0)
        - correction_sampled + correction_residual)
    out["continuation_rollouts"] = int(out["rollouts"])
    out["total_rollouts"] = int(out["rollouts"])
    if any(hasattr(bot, 'continuation_totals') for bot in bots):
        model_rows = out.get('value_continuation_model_rows', 0)
        out['candidate_world_evaluations'] = out['rollouts']
        out['rollouts'] -= model_rows
        out['continuation_rollouts'] -= model_rows
        out['total_rollouts'] -= model_rows
        out['cheap_evaluations'] += model_rows
        # A world can contain a mixture of terminal and learned candidate
        # leaves. Retire the ambiguous world-count metric for this recipe;
        # candidate-level terminal_rows and model_rows are exact instead.
        out.pop('full_rollout_accepted_worlds', None)
    if any(hasattr(bot, "timeout_count") for bot in bots):
        out["decision_timeouts"] = sum(bot.timeout_count for bot in bots)
    if any(hasattr(bot, "double_shortlist_counts") for bot in bots):
        out["inner_continuation_rollouts"] = int(out.get("double_inner_full_rollouts", 0))
        out["outer_continuation_rollouts"] = (
            out["total_rollouts"] - out["inner_continuation_rollouts"])
    return out


def _recipe(config):
    ranks = config.get("trump_ranks")
    recipe = {
        "schema": config["schema"], "arm": config["arm"],
        "checkpoint_sha256": config["checkpoint_sha256"],
        "shortlist": config["shortlist"],
        "report_worlds": config["report_worlds"],
        "production_multiplier": config["production_multiplier"],
        "target_wall_multiplier": config["target_wall_multiplier"],
        "rank": RANK if not ranks else ranks[0] if len(ranks) == 1 else None,
    }
    # New receipts bind the requested mode.  A pre-mode config has no such
    # field and must continue to reopen its legacy shards as reference.
    if "encoding" in config:
        recipe["encoding"] = _encoding(config)
    if "reuse_successors" in config:
        recipe["reuse_successors"] = config["reuse_successors"]
    if "trump_ranks" in config:
        recipe["trump_ranks"] = config["trump_ranks"]
    for key in ("double_shortlist", "baseline", "decision_deadline", "throw_components",
                "hybrid_bury", "corrected_rollout", "wide_tail", "prior", "value_continuation"):
        if key in config:
            recipe[key] = config[key]
    return recipe


def _deadline_side(config, side, seed):
    """Top-level spawn factory; the child shares cached evaluators across seats."""
    return CwvTimedPolicy(make_side(config, side, seed))


def run_cluster(config, cluster):
    created = []
    deadline = config.get("decision_deadline")
    if deadline is not None and deadline != DEADLINE_RECIPE:
        raise ValueError("unsupported screen decision deadline recipe")
    session = DeadlineSession(_deadline_side, deadline["seconds"]) if deadline else None

    def factory(_config, side, seed):
        wrapped = (session.register(config, side, seed) if session
                   else CwvTimedPolicy(make_side(config, side, seed)))
        created.append((side, wrapped))
        return wrapped

    rank = rank_for(config, cluster)
    base = duel.build_config(arm="none", select_worlds=BASELINE_SELECT_WORLDS,
                             report_worlds=BASELINE_REPORT_WORLDS)
    seed = config["seed0"] + cluster
    games = []

    def game_factory(rng):
        game = _game_factory_for(rank)(rng)
        games.append(game)
        return game

    try:
        rows = [duel.play_screen_round(
            base, cluster, seed, mirror, bot_factory=factory,
            counter_fn=work_counters, game_factory=game_factory)
                for mirror in (0, 1)]
    finally:
        if session:
            session.close()
    if len(rows) != len(games):
        raise ValueError("ranked screen game factory did not produce one game per mirror")
    for (record, _), game in zip(rows, games, strict=True):
        if record["trump_rank"] != rank:
            raise ValueError(f"cluster {cluster} dealt trump rank {record['trump_rank']!r}, expected {rank!r}")
        record["arm"] = config["arm"]
        if "trump_ranks" in config:
            round_state = getattr(game, "round", None)
            actual_suit = getattr(round_state, "trump_suit", None)
            if actual_suit is None:
                if not getattr(round_state, "trump_is_nt", False):
                    raise ValueError(f"cluster {cluster} has no declared trump suit/NT witness")
                actual_suit = "NT"
            if actual_suit not in ("S", "H", "D", "C", "NT"):
                raise ValueError(f"cluster {cluster} has invalid actual trump suit {actual_suit!r}")
            record["trump_suit"] = actual_suit
    return {
        "schema": "cwv-shortlist-shard-v1", "cluster": cluster,
        "seed": seed, "rank": rank, "recipe": _recipe(config),
        "records": [record for record, _ in rows],
        "timings": [timing for _, timing in rows],
        "decision_traces": [{"mirror": i // 4, "side": side,
                             "decisions": policy.decisions}
                            for i, (side, policy) in enumerate(created)],
    }


def reopen_shard(path, config, cluster):
    shard = json.loads(path.read_text())
    rows = shard.get("records", [])
    seed = config["seed0"] + cluster
    rank = rank_for(config, cluster)
    if (shard.get("schema") != "cwv-shortlist-shard-v1"
            or shard.get("cluster") != cluster or shard.get("seed") != seed
            or shard.get("rank") != rank or shard.get("recipe") != _recipe(config)
            or len(rows) != 2 or [r.get("mirror") for r in rows] != [0, 1]
            or any(r.get("cluster") != cluster or r.get("seed") != seed
                   or r.get("trump_rank") != rank
                   or r.get("arm") != config["arm"]
                   or ("trump_ranks" in config
                       and r.get("trump_suit") not in ("S", "H", "D", "C", "NT"))
                   for r in rows)):
        raise ValueError("completed shard does not match its mirrored pair and recipe")
    return shard


def _arm_description(config):
    """Describe the configured arm, including production's actual dose."""
    arm = config["arm"]
    if arm == "learned":
        return "flat exhaustive learned root shortlist"
    if arm == "uniform":
        return "flat exhaustive uniform root shortlist"
    if arm == "production":
        multiplier = int(config["production_multiplier"])
        return (f"production at N={BASELINE_SELECT_WORLDS * multiplier} "
                f"selection worlds, R={BASELINE_REPORT_WORLDS * multiplier} "
                "report worlds")
    if arm == "identity":
        return "production identity control"
    raise ValueError(f"unsupported CWV shortlist arm: {arm!r}")


def summary_for(shards, config):
    base = duel.build_config(arm="none", select_worlds=BASELINE_SELECT_WORLDS,
                             report_worlds=BASELINE_REPORT_WORLDS)
    result = duel.summarize(
        [record for shard in shards for record in shard["records"]], base,
        seed0=config["seed0"], replicates=1000)
    totals = result.get("work_totals", {})

    def ratio(key):
        denominator = totals.get("baseline", {}).get(key, 0)
        return (totals.get("arm", {}).get(key, 0) / denominator
                if denominator else None)

    wall_ratio = ratio("decision_wall_seconds")
    target = int(config["target_wall_multiplier"])
    result.update({
        "schema": "cwv-shortlist-summary-v1", "config": config,
        "arm": config["arm"],
        "arm_description": _arm_description(config),
        "rank": (RANK if "trump_ranks" not in config
                 else config["trump_ranks"][0] if len(config["trump_ranks"]) == 1 else None),
        "claim": "exploratory DEV paired screen; no equal-work or strength claim",
        "completed_clusters": len(shards),
        "requested_clusters": config["clusters"],
        "complete": len(shards) == config["clusters"],
        "arm_over_baseline_decision_cpu": ratio("decision_cpu_seconds"),
        "arm_over_baseline_decision_wall": wall_ratio,
        "target_wall_multiplier": target,
        "decision_wall_target_status": (
            "over_target" if wall_ratio is not None and wall_ratio > target
            else "within_target" if wall_ratio is not None else "unknown"),
        "equal_work_strength_claim": False,
        "work_caveat": "Decision wall/CPU and cheap evaluations are measured separately; "
                        "a target overrun does not censor or invalidate outcomes.",
    })
    if "double_shortlist" in config or "baseline" in config:
        result["claim"] = "exploratory paired DEV strength estimate; not confirmation or deployment"
        result["arm_description"] = (
            "exhaustive learned root shortlist; bounded per-world perfect-information "
            "inner shortlist continuation, then terminal heuristic values and root MC-LCB"
            if "double_shortlist" in config else "flat exhaustive learned root shortlist")
        result["baseline_description"] = config.get("baseline", "production")
        result["work_caveat"] += (
            " Inner finalist continuations count separately and are included exactly once "
            "in total rollouts. Inner choices see sampled complete worlds, not true hidden hands.")
    if "corrected_rollout" in config:
        mode = config["corrected_rollout"]["mode"]
        result["arm_description"] = (
            "model-corrected shared-world rollout shortlist"
            if mode == "corrected" else "levels-only shared-world rollout shortlist")
        result["baseline_description"] = config.get("baseline", "production")
    if "wide_tail" in config:
        result["arm_description"] = (
            "wide-tail two-stage admission: coarse full legal set, production-anchor "
            "union, disjoint-world refinement; unchanged MC selection/report")
        result["wide_tail"] = config["wide_tail"]
        result["work_caveat"] += (
            " Wide-tail ranking is a policy change, not decision-preserving acceleration. "
            "Only the refinement pool receives remaining-world scores.")
    if config.get("hybrid_bury"):
        result["arm_description"] += "; full-completion hybrid bury on both sides"
    if 'value_continuation' in config:
        result['value_continuation'] = config['value_continuation']
        result['arm_description'] = 'value-truncated selection and independent report; final signed levels'
        result['baseline_description'] = config['value_continuation']['baseline'] + ' continuation; matched admission'
        result['work_caveat'] += (' Legacy rollout counters are candidate-world evaluations, not full playouts. '
                                  'Report uncertainty excludes model error. No strength claim from offline calibration.')
        result["hybrid_bury"] = {
            "arm": "hybrid", "scope": "both sides",
            "serving_budget_seconds": None, "completion": "full",
        }
        result["work_caveat"] += (
            " Both sides use the full-completion CWV hybrid bury policy; this is "
            "not Fly 2s serving-budget parity.")
    if "trump_ranks" in config:
        records = [record for shard in shards for record in shard["records"]]
        by_rank = {rank: 0 for rank in config["trump_ranks"]}
        by_suit = {suit: 0 for suit in ("S", "H", "D", "C", "NT")}
        for record in records:
            rank = record.get("trump_rank")
            suit = record.get("trump_suit")
            if rank not in by_rank:
                raise ValueError(f"record trump rank {rank!r} is outside configured cycle")
            if suit not in by_suit:
                raise ValueError(f"record lacks a valid actual trump suit/NT: {suit!r}")
            by_rank[rank] += 1
            by_suit[suit] += 1
        result["trump_ranks"] = list(config["trump_ranks"])
        result["coverage"] = {"by_rank": by_rank, "by_trump_suit": by_suit}
    if config.get("decision_deadline"):
        result["decision_latency"] = latency_summary(shards)
        complete_accounting = all(row["work_accounting_complete"]
                                  for row in result["decision_latency"].values())
        result["work_accounting_complete"] = complete_accounting
        result["work_caveat"] += (
            " Both policies have a 300s total play deadline with SmartBot fallback."
            " Interrupted search counters/CPU are uncommitted lower bounds, not zero work.")
        if not complete_accounting:
            result["arm_over_baseline_decision_cpu"] = None
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arm", choices=ARMS, required=True)
    parser.add_argument("--checkpoint")
    parser.add_argument("--decision-deadline", type=float, default=300,
                        help="300s total play deadline (default); 0 explicitly selects legacy uncapped policy")
    parser.add_argument("--worlds", type=int, default=1)
    parser.add_argument("--selection-worlds", type=int, default=30)
    parser.add_argument("--alternatives", type=int, default=4)
    parser.add_argument("--report-worlds", type=int, default=300)
    parser.add_argument("--production-multiplier", type=int, choices=(1, 3), default=1)
    parser.add_argument("--target-wall-multiplier", type=int, choices=(1, 3), default=1)
    parser.add_argument("--batch-size", type=int, default=128)
    parser.add_argument("--encoding", choices=("reference", "mlp-static"),
                        default="reference")
    parser.add_argument("--reuse-successors", action="store_true",
                        help="reuse equivalent leaves/inputs without changing action rows or model batches")
    parser.add_argument("--wide-tail", action="store_true",
                        help="DEV: >10000 legal actions use 2-world coarse top256 plus anchors, then 30 disjoint worlds")
    parser.add_argument("--value-head", choices=("outcome", "search-mean"), default=None,
                        help="#373 two-head checkpoints, ARM side only: which head the "
                             "arm's evaluator reads (default: the checkpoint's own value_head)")
    parser.add_argument("--prior-checkpoint", type=Path,
                        help="#425: policy-prior checkpoint (policy_prior.py); ARM side only, "
                             "prunes decisions above --prior-threshold to the union of per-world top lists")
    parser.add_argument("--prior-threshold", type=int, default=10_000)
    parser.add_argument("--prior-top", type=int, default=256)
    parser.add_argument('--value-continuation', choices=('0', '1', '2', 'full'),
                        help='DEV: outcome-value selection and report after k tricks; full is levels control')
    parser.add_argument('--continuation-baseline', choices=('mc', 'full'), default='mc',
                        help='with value-continuation: point-MC or full heuristic signed-level control')
    parser.add_argument("--report-tie-keeps-incumbent", action="store_true",
                        help="#339 layer 1 on the ARM side only: an exact report-fold tie keeps "
                             "the incumbent (MCBot.REPORT_TIE_KEEPS_INCUMBENT); the baseline "
                             "keeps the production default")
    parser.add_argument("--throw-components", action="store_true",
                        help="ARM only: admit direct components of model-shortlisted lead throws")
    parser.add_argument("--corrected-rollout", choices=("corrected", "levels"),
                        help="ARM only: shared-world model-corrected rollout selection")
    parser.add_argument("--correction-worlds", type=int, default=64)
    parser.add_argument("--residual-worlds", type=int, default=16)
    parser.add_argument("--hybrid-bury", action="store_true",
                        help="same default hybrid bury on both learned/flat-shortlist sides")
    parser.add_argument("--inner-mode", choices=("learned", "uniform", "heuristic"),
                        help="DEV: one extra trick of per-world shortlist continuation; learned root only")
    parser.add_argument("--inner-worlds", type=int, default=4,
                        help="guided fraction numerator over --selection-worlds; scaled to each accepted world set")
    parser.add_argument("--inner-batch-size", type=int, default=128)
    parser.add_argument("--inner-reuse-successors", action="store_true",
                        help="reuse exact inner successor leaves and evaluator inputs")
    parser.add_argument("--baseline", choices=("production", "flat-shortlist", "levels-shortlist"),
                        default="production")
    parser.add_argument("--clusters", type=int, default=4)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--seed0", type=int, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--trump-ranks",
                        help="comma-separated distinct trump ranks for the cluster cycle")
    parser.add_argument("--cost-order-from", type=Path,
                        help="order pending clusters by prior shard wall time")
    args = parser.parse_args(argv)
    if args.decision_deadline != 0:
        validate_deadline(args.decision_deadline)
        if args.decision_deadline != 300:
            parser.error("screen recipe supports --decision-deadline 300 or legacy 0 only")
    if (min(args.worlds, args.selection_worlds, args.alternatives,
            args.batch_size, args.clusters, args.workers) < 1
            or args.report_worlds < 30 or args.correction_worlds < 1
            or args.residual_worlds < 1):
        parser.error("positive worlds/alternatives/clusters/workers and >=30 report worlds required")
    if os.environ.get("SHENGJI_REQUIRE_VOIDS") != "1":
        parser.error("SHENGJI_REQUIRE_VOIDS=1 is required")
    if args.arm == "learned" and not args.checkpoint:
        parser.error("learned requires --checkpoint")
    if args.value_continuation is not None and (
            args.arm != 'learned' or args.baseline != 'flat-shortlist'
            or args.value_head not in (None, 'outcome')
            or args.corrected_rollout or args.wide_tail or args.inner_mode
            or args.hybrid_bury or args.throw_components or args.report_tie_keeps_incumbent):
        parser.error('value continuation requires isolated outcome-head learned/flat-shortlist')
    if args.arm != "learned" and args.checkpoint:
        parser.error("--checkpoint is only valid for learned")
    if args.reuse_successors and args.arm != "learned":
        parser.error("--reuse-successors is only valid for learned")
    if args.report_tie_keeps_incumbent and args.arm != "learned":
        parser.error("--report-tie-keeps-incumbent is only valid for learned")
    if args.value_head is not None and args.arm != "learned":
        parser.error("--value-head is only valid for learned")
    if args.wide_tail and (args.arm != "learned" or args.worlds != 32
                           or args.alternatives != 4 or args.inner_mode is not None
                           or args.value_head is not None
                           or args.report_tie_keeps_incumbent):
        parser.error("--wide-tail requires isolated learned W32 ranking with four alternatives")
    if args.throw_components and (args.arm != "learned" or args.inner_mode is not None):
        parser.error("--throw-components requires learned without --inner-mode")
    if args.wide_tail and args.throw_components:
        parser.error("--wide-tail cannot be combined with --throw-components")
    if args.corrected_rollout is not None:
        if args.arm != "learned" or args.baseline not in ("flat-shortlist", "levels-shortlist"):
            parser.error("--corrected-rollout requires learned with a shortlist baseline")
        if args.baseline == "levels-shortlist" and args.corrected_rollout != "corrected":
            parser.error("levels-shortlist requires --corrected-rollout corrected")
        if (args.inner_mode is not None or args.value_head is not None
                or args.report_tie_keeps_incumbent or args.throw_components
                or args.wide_tail):
            parser.error("--corrected-rollout cannot be combined with inner/value-head/tie options")
        if args.residual_worlds > args.correction_worlds:
            parser.error("residual worlds must be <= correction worlds")
    if args.baseline == "levels-shortlist" and args.corrected_rollout != "corrected":
        parser.error("levels-shortlist requires --corrected-rollout corrected")
    if args.hybrid_bury and (args.arm != "learned" or args.baseline not in
                             ("flat-shortlist", "levels-shortlist")
                             or args.inner_mode is not None):
        parser.error("--hybrid-bury requires learned/shortlist without --inner-mode")
    if args.inner_mode is not None:
        if args.arm != "learned" or args.alternatives != 4:
            parser.error("--inner-mode requires a learned root with four alternatives plus incumbent")
        if min(args.inner_worlds, args.inner_batch_size) < 1:
            parser.error("inner worlds and batch size must be positive")
    if args.inner_reuse_successors and args.inner_mode is None:
        parser.error("--inner-reuse-successors requires --inner-mode")
    if args.baseline in ("flat-shortlist", "levels-shortlist") and args.arm != "learned":
        parser.error("shortlist baseline requires the learned checkpoint/root recipe")
    if args.prior_checkpoint is not None:
        if args.arm != "learned" or args.wide_tail or args.throw_components or args.hybrid_bury \
                or args.inner_mode is not None or args.corrected_rollout is not None:
            parser.error("--prior-checkpoint requires the plain learned arm")
        if min(args.prior_threshold, args.prior_top) < 1 or args.prior_top < args.alternatives + 1:
            parser.error("positive prior threshold and prior top > alternatives required")
    trump_ranks = None
    if args.trump_ranks is not None:
        try:
            trump_ranks = parse_trump_ranks(args.trump_ranks)
        except Exception as exc:
            parser.error(str(exc))
    with screen_output_lock(args.out):
        return _run_screen(args, trump_ranks)


def _run_screen(args, trump_ranks):
    checkpoint = str(Path(args.checkpoint).resolve()) if args.checkpoint else None
    checkpoint_sha = None
    checkpoint_recipe = None
    if args.arm == "learned":
        evaluator = shared_evaluator(
            checkpoint, threads=1, max_batch=args.batch_size,
            encoding=args.encoding,
            **({"value_head": args.value_head} if args.value_head else {}))
        checkpoint_sha = evaluator.checkpoint_sha256
        checkpoint_recipe = evaluator.identity()
    shortlist = CWVShortlistConfig(
        worlds=args.worlds, selection_worlds=args.selection_worlds,
        alternatives=args.alternatives, batch_size=args.batch_size,
        uniform=args.arm == "uniform")
    config = {
        "schema": "cwv-shortlist-config-v1", "arm": args.arm,
        "checkpoint": checkpoint, "checkpoint_sha256": checkpoint_sha,
        "checkpoint_recipe": checkpoint_recipe,
        "encoding": args.encoding,
        "shortlist": asdict(shortlist), "batch_size": args.batch_size,
        "report_worlds": args.report_worlds,
        "production_multiplier": args.production_multiplier,
        "target_wall_multiplier": args.target_wall_multiplier,
        "seed0": args.seed0, "clusters": args.clusters,
        "source_sha256": execution_source_identity(Path(__file__).resolve().parents[1]),
        "runtime": {"python": platform.python_version(), "platform": platform.platform(),
                    "environment": {k: v for k, v in sorted(os.environ.items())
                                    if k.startswith("SHENGJI_") or k in (
                                        "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS",
                                        "VECLIB_MAXIMUM_THREADS", "MKL_NUM_THREADS")}},
    }
    if args.decision_deadline:
        config["decision_deadline"] = dict(DEADLINE_RECIPE)
    # Leave old/default recipes unchanged; enabled receipts explicitly bind it.
    if args.reuse_successors:
        config["reuse_successors"] = True
    if args.wide_tail:
        config["wide_tail"] = asdict(CWVWideTailConfig())
    if args.prior_checkpoint is not None:
        with Path(args.prior_checkpoint).open("rb") as handle:
            prior_sha = hashlib.file_digest(handle, "sha256").hexdigest()
        config["prior"] = asdict(CWVPriorAdmissionConfig(
            checkpoint=str(Path(args.prior_checkpoint).resolve()), checkpoint_sha256=prior_sha,
            threshold=args.prior_threshold, top=args.prior_top))
    if args.value_continuation is not None:
        config['value_continuation'] = {
            'tricks': ('full' if args.value_continuation == 'full' else int(args.value_continuation)),
            'baseline': args.continuation_baseline,
        }
    if args.report_tie_keeps_incumbent:
        config["report_tie_keeps_incumbent"] = True
    if args.value_head is not None:
        config["value_head"] = args.value_head
    if args.throw_components:
        config["throw_components"] = True
    if args.corrected_rollout is not None:
        config["corrected_rollout"] = {
            "mode": args.corrected_rollout,
            "correction_worlds": args.correction_worlds,
            "residual_worlds": args.residual_worlds,
        }
    if args.hybrid_bury:
        config["hybrid_bury"] = True
    if trump_ranks is not None:
        config["trump_ranks"] = list(trump_ranks)
    if args.inner_mode is not None:
        config["double_shortlist"] = {
            "guidance": "selection-fraction-ceil-v2",
            "mode": args.inner_mode, "worlds": args.inner_worlds,
            "batch_size": args.inner_batch_size,
            "extra_tricks": 1, "alternatives": 4,
            "information": "per-sampled-world perfect information; simulation only",
        }
        if args.inner_reuse_successors:
            config["double_shortlist"]["reuse_successors"] = True
    if args.baseline != "production":
        config["baseline"] = args.baseline
    cost_order = (_cost_order(args.cost_order_from, range(args.clusters), args.seed0,
                              trump_ranks=trump_ranks)
                  if args.cost_order_from is not None else None)
    if cost_order is not None:
        config["execution_order"] = cost_order
    bind_output_config(args.out, config)
    shards, pending = [], []
    for cluster in range(args.clusters):
        path = args.out / f"cluster-{cluster:05}.json"
        if path.exists():
            shards.append(reopen_shard(path, config, cluster))
        else:
            pending.append(cluster)
    if cost_order is not None:
        costs = cost_order["cluster_wall_secs"]
        pending.sort(key=lambda cluster: (-costs[str(cluster)], cluster))
    try:
        _run_pending(config, pending, shards, output=args.out, workers=args.workers,
                     task_fn=run_cluster)
    except Exception as exc:
        if not (args.out / "failure.json").exists():
            _publish(args.out / "failure.json", {
                "type": type(exc).__name__, "message": str(exc),
                "failed_clusters": [],
                "completed_clusters": sorted(s["cluster"] for s in shards),
                "recovery": "rerun the identical command; completed mirrored pairs are retained",
            })
        raise
    finally:
        if shards:
            _publish(args.out / "summary.json",
                     summary_for(sorted(shards, key=lambda s: s["cluster"]), config))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
