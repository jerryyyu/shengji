"""Bounded DEV paired duel for :class:`PolicyWorldBot`.

This module is deliberately a small experiment harness, not a production
evaluator.  A worker receives only a seed and reconstructs its own Round;
completed (or refused) pairs are written by the parent as JSONL receipts.
Whole-job deadlines belong to an external supervisor.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import hashlib
import inspect
import json
import multiprocessing as mp
import os
from pathlib import Path
import random
import resource
import signal
import statistics
import subprocess
import sys
import time
from typing import Any, Iterable

import numpy as np

from ..ai import registry
from ..ai.heuristic import HeuristicBot
from ..ai.mcbot import MCSmartRoll
from ..engine.game import Game
from ..harvest.rebuild import signed_level_utility
from .policy_world_search import PolicyWorldBot
from .policy_value_search import PolicyValueBot
from .policy_selective_mc import PolicySelectiveMCBot
from .policy_lookahead import PolicyLookaheadBot
from .production_play_control import ProductionPlayControl, SHA256 as PRODUCTION_SHA256
from ..ai.cwv_policy import CompleteWorldEvaluator
from functools import lru_cache


@lru_cache(maxsize=1)
def _value_evaluator(checkpoint, checksum):
    evaluator = CompleteWorldEvaluator(checkpoint, value_head="outcome", threads=1)
    if evaluator.checkpoint_sha256 != checksum:
        raise ValueError("value checkpoint SHA256 mismatch")
    return evaluator


def make_policy(checkpoint, checksum, worlds, seed, mode="policy", candidates=8):
    if mode == "mc-policy-value-rollout":
        from .mc_policy_value_rollout import MCPolicyValueRollout
        continuation = make_policy(checkpoint, checksum, worlds, seed,
                                   "policy-value", candidates)
        return MCPolicyValueRollout(continuation, seed=seed)
    kwargs = dict(worlds=worlds, cap=CAP, seed=seed)
    if mode == "policy":
        return PolicyWorldBot.from_checkpoint(checkpoint, checksum, **kwargs)
    classes = {"policy-value": PolicyValueBot,
               "policy-selective-mc": PolicySelectiveMCBot,
               "policy-lookahead": PolicyLookaheadBot}
    if mode not in classes:
        raise ValueError("unknown policy mode")
    cls = classes[mode]
    return cls.from_checkpoint(
        checkpoint, checksum, evaluator=_value_evaluator(checkpoint, checksum),
        candidates=candidates, **kwargs)


SCHEMA = "policy-world-duel-v1"
DECISION_TIMEOUT_SECONDS = 300
BOOTSTRAP_REPLICATES = 10_000
BOOTSTRAP_SEED = 20260919
CAP = 4000
CONTROL_NAMES = ("mc-lcb", "mc-smart4", "policy-world", "policy-value", "production-play")
VERIFY_KEYS = ("verification_triggers", "verification_worlds",
               "verification_attempts", "verification_rollouts")
EXTRA_POLICY_WORK = ("value_evaluations", "value_batches", "continuation_plies",
                     "continuation_worlds", "continuation_sample_attempts",
                     "continuation_capped_decisions") + VERIFY_KEYS
SHORTLIST_COUNTS = ('decisions', 'forced', 'legal_actions', 'shortlisted_actions',
                    'cheap_worlds', 'cheap_evaluations', 'cheap_batches', 'terminal_afterstates')
SHORTLIST_SAMPLER = ('sample_attempts', 'accepted_worlds', 'failed_worlds',
                    'rejected_worlds', 'impossible_worlds')
SHORTLIST_WORK = SHORTLIST_COUNTS + tuple('cheap_' + k for k in SHORTLIST_SAMPLER) + (
    'prior_decisions', 'prior_worlds', 'prior_pool_evaluations')


def _rss_kib() -> int:
    """Return normalized ru_maxrss in KiB on Linux and macOS."""
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    if sys.platform == "darwin":
        value //= 1024
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _alarm_handler(_signum, _frame):
    raise TimeoutError(f"{DECISION_TIMEOUT_SECONDS}s play decision exceeded")


def _timed_play(bot, rnd, seat):
    """Run exactly one play decision under the cooperative worker alarm."""
    started = time.perf_counter()
    signal.setitimer(signal.ITIMER_REAL, DECISION_TIMEOUT_SECONDS)
    try:
        cards = bot.decide_play(rnd, seat)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
    return cards, time.perf_counter() - started


def make_control(name: str, seed: int, production=None):
    """Construct the named control with its immutable effective dose."""
    if name == "production-play":
        if production is None:
            raise ValueError('production-play requires pinned control checkpoint')
        return production.make(seed)
    if name == "mc-lcb":
        bot = registry.make_bot("mc-s0-report-lcb", seed=seed)
        if (bot.N_DETERMINIZATIONS != 30 or bot.REPORT_FOLD_WORLDS != 300
                or bot.REPORT_RULE != "lcb" or not bot.REQUIRE_EXACT_WORK):
            raise RuntimeError("mc-lcb registry contract drift")
        return bot
    if name == "mc-smart4":
        bot = MCSmartRoll(seed=seed)
        bot.N_DETERMINIZATIONS = 4
        if type(bot) is not MCSmartRoll or bot.N_DETERMINIZATIONS != 4:
            raise RuntimeError("mc-smart4 contract drift")
        return bot
    raise ValueError(f"unknown control {name!r}")


def control_config(name: str, production=None) -> dict[str, Any]:
    """Return effective, recipe-safe control settings (without live objects)."""
    if name == 'production-play':
        if production is None:
            raise ValueError('production-play requires pinned control checkpoint')
        return production.identity()
    if name == "policy-value":
        return {"requested": name, "class": "PolicyValueBot", "cap": CAP,
                "checkpoint": "same as arm", "worlds": "same as arm",
                "candidates": "same as arm", "value_head": "outcome",
                "value_batch_size": 128, "seed_formula": "seed*4+seat",
                "rollout_policy": None}
    if name == "policy-world":
        return {"requested": name, "class": "PolicyWorldBot", "cap": CAP,
                "checkpoint": "same as arm", "worlds": "same as arm",
                "seed_formula": "seed*4+seat", "rollout_policy": None}
    if name == "mc-lcb":
        # The registry's named policy is authoritative; these fields are also
        # checked by make_control for every worker.
        return {
            "requested": name, "registry_policy": "mc-s0-report-lcb",
            "class": "MCS0ReportLCB", "N_DETERMINIZATIONS": 30,
            "REPORT_FOLD_WORLDS": 300, "REPORT_RULE": "lcb",
            "REQUIRE_EXACT_WORK": True, "rollout_policy": "HeuristicBot",
        }
    if name == "mc-smart4":
        return {
            "requested": name, "class": "MCSmartRoll",
            "N_DETERMINIZATIONS": 4, "rollout_policy": "SmartBot",
        }
    raise ValueError(f"unknown control {name!r}")


def _jsonable(value):
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return repr(value)


def full_control_config(name: str, production=None) -> dict[str, Any]:
    """Bind every uppercase gameplay knob in addition to the named dose."""
    config = control_config(name, production)
    if name in ("policy-world", "policy-value"):
        return config
    bot = make_control(name, 0, production)
    config["all_uppercase_attributes"] = {
        key: _jsonable(getattr(bot, key))
        for key in sorted(dir(bot)) if key.isupper() and not key.startswith("_")
    }
    config["rollout_policy"] = type(bot.rollout_policy).__name__
    return config


def _decision_telemetry(bot, side: str) -> dict[str, Any]:
    if side == "policy":
        record = getattr(bot, "last_decision_record", None) or {}
        verification = record.get("verification", {})
        continuation = record.get("continuation_work", {})
        return {
            "verification_triggers": int(verification.get("triggered", False)),
            "verification_worlds": int(verification.get("worlds", 0)),
            "verification_attempts": int(verification.get("sample_attempts", 0)),
            "verification_rollouts": int(verification.get("rollouts", 0)),
            "sample_attempts": int(record.get("sample_attempts", 0)),
            "worlds": int(record.get("worlds", 0)),
            "capped": bool(record.get("legal_complete") is False),
            "value_evaluations": int(record.get("value_evaluations", 0)),
            "value_batches": int(record.get("value_batches", 0)),
            **{"continuation_" + key: int(continuation.get(key, 0))
               for key in ("plies", "worlds", "sample_attempts", "capped_decisions")},
        }
    alloc = getattr(bot, "last_alloc", None) or {}
    record = getattr(bot, "last_decision_record", None) or {}
    fold = getattr(bot, "last_override_stats", None) or {}
    work = record.get("work", {})
    shortlist = getattr(bot, 'last_shortlist', None) or {}
    counts = shortlist.get('counts', {})
    sampler = shortlist.get('cheap_sampler_delta', {})
    prior = shortlist.get('prior_admission', {})
    from .mc_policy_value_rollout import MCPolicyValueRollout
    learned_work = {}
    if isinstance(bot, MCPolicyValueRollout):
        inner = bot.rollout_policy
        learned_work = dict(continuation_plies=inner.decisions,
                            continuation_worlds=inner.worlds,
                            continuation_sample_attempts=inner.sample_attempts,
                            continuation_capped_decisions=inner.legal_caps,
                            value_evaluations=inner.value_evaluations,
                            value_batches=inner.value_batches)
    return {
        **learned_work,
        'shortlist_work': {
            **{k: int(counts.get(k, 0)) for k in SHORTLIST_COUNTS},
            **{'cheap_' + k: int(sampler.get(k, 0)) for k in SHORTLIST_SAMPLER},
            'prior_decisions': int(bool(prior.get('triggered'))),
            'prior_worlds': int(prior.get('worlds', 0)),
            'prior_pool_evaluations': int(prior.get('pool_evaluations', 0))},
        "worlds": int(alloc.get("worlds", 0)),
        "short": bool(alloc.get("short", False)),
        "attempts": int(alloc.get("attempts", 0)),
        "rollouts": int(alloc.get("rollouts", 0)),
        "attempt_cap_hit": bool(alloc.get("attempt_cap_hit", False)),
        "report_worlds": int(fold.get("worlds", 0)),
        "report_rollouts": int(work.get("report_rollouts", 0)),
        "report_incomplete": bool(fold) and not bool(fold.get("complete", False)),
    }


def _empty_side() -> dict[str, Any]:
    return {
        "seconds": [], "sample_attempts": 0, "worlds": 0,
        "capped_decisions": 0, "decisions": 0,
        **{key: 0 for key in EXTRA_POLICY_WORK},
        'shortlist_work': dict.fromkeys(SHORTLIST_WORK, 0),
        "mc_last_alloc": {"decisions": 0, "short": 0,
                          "attempt_cap_hit": 0, "worlds": 0,
                          "attempts": 0, "rollouts": 0,
                          "report_worlds": 0, "report_rollouts": 0,
                          "report_incomplete": 0},
    }


def _record_decision(side_record: dict[str, Any], seconds: float,
                     telemetry: dict[str, Any], side: str) -> None:
    side_record["seconds"].append(float(seconds))
    side_record["decisions"] += 1
    if side == "policy":
        side_record["sample_attempts"] += telemetry["sample_attempts"]
        side_record["worlds"] += telemetry["worlds"]
        side_record["capped_decisions"] += int(telemetry["capped"])
        for key in EXTRA_POLICY_WORK:
            side_record[key] += telemetry.get(key, 0)
    else:
        for key in EXTRA_POLICY_WORK:
            side_record[key] += telemetry.get(key, 0)
        for key in SHORTLIST_WORK:
            side_record['shortlist_work'][key] += telemetry.get('shortlist_work', {}).get(key, 0)
        alloc = side_record["mc_last_alloc"]
        alloc["decisions"] += 1
        alloc["short"] += int(telemetry["short"])
        alloc["attempt_cap_hit"] += int(telemetry["attempt_cap_hit"])
        alloc["worlds"] += telemetry["worlds"]
        alloc["attempts"] += telemetry["attempts"]
        alloc["rollouts"] += telemetry["rollouts"]
        alloc["report_worlds"] += telemetry["report_worlds"]
        alloc["report_rollouts"] += telemetry["report_rollouts"]
        alloc["report_incomplete"] += int(telemetry["report_incomplete"])


def _prepare_round(game: Game, heuristic: HeuristicBot):
    rnd = game.start_round()
    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        cards = heuristic.decide_declare(rnd, seat)
        if cards:
            rnd.declare(seat, cards)
    for seat in range(4):
        cards = heuristic.decide_declare(rnd, seat, final=True)
        if cards:
            rnd.declare(seat, cards)
    rnd.finalize_declare()
    assert rnd.banker is not None
    rnd.bury(rnd.banker, heuristic.decide_bury(rnd, rnd.banker))
    return rnd


def _play_one(seed: int, parity: int, checkpoint: str, checkpoint_sha256: str,
              worlds: int, control_name: str, mode="policy", candidates=8, production=None) -> dict[str, Any]:
    """Play one mirror.  Only this function runs inside a worker."""
    signal.signal(signal.SIGALRM, _alarm_handler)
    side = {"policy": _empty_side(), "control": _empty_side()}
    try:
        game = Game(random.Random(seed))
        heuristic = HeuristicBot()
        rnd = _prepare_round(game, heuristic)
        bots: list[Any] = []
        roles: list[str] = []
        for seat in range(4):
            role = "policy" if seat % 2 == parity else "control"
            role_seed = seed * 4 + seat
            if role == "policy":
                bot = make_policy(checkpoint, checkpoint_sha256, worlds,
                                  role_seed, mode, candidates)
            else:
                bot = (make_policy(checkpoint, checkpoint_sha256, worlds, role_seed,
                                   "policy-value" if control_name == "policy-value" else "policy",
                                   candidates)
                       if control_name in ("policy-world", "policy-value")
                       else make_control(control_name, role_seed, production))
            bots.append(bot)
            roles.append(role)
        while rnd.phase == "play":
            seat = rnd.turn
            assert seat is not None
            role = roles[seat]
            cards, elapsed = _timed_play(bots[seat], rnd, seat)
            telemetry_kind = ("policy" if isinstance(bots[seat], PolicyWorldBot)
                              else "control")
            _record_decision(side[role], elapsed,
                             _decision_telemetry(bots[seat], telemetry_kind), telemetry_kind)
            rnd.play(seat, cards)
        game.finish_round()
        utility = signed_level_utility(
            rnd.attacker_points, banker_seat=rnd.banker,
            perspective_seat=parity)
        return {"utility": float(utility), "attacker_points": rnd.attacker_points,
                "banker": rnd.banker, "sides": side,
                "max_rss_kib": _rss_kib()}
    except TimeoutError as exc:
        return {"sides": side, "max_rss_kib": _rss_kib(), "timeout": True,
                "error": {"type": type(exc).__name__, "message": str(exc)}}
    except Exception as exc:
        return {"sides": side, "max_rss_kib": _rss_kib(), "timeout": False,
                "error": {"type": type(exc).__name__, "message": str(exc)}}


def play_pair(seed: int, checkpoint: str, checkpoint_sha256: str, *,
              worlds: int = 4, control: str = "mc-lcb",
              mode="policy", candidates=8, production=None) -> dict[str, Any]:
    """Play both team-parity mirrors; any exception refuses the whole pair."""
    started = time.monotonic()
    mirrors = []
    sides = {"policy": _empty_side(), "control": _empty_side()}
    try:
        for parity in (0, 1):
            one = _play_one(seed, parity, checkpoint, checkpoint_sha256,
                            worlds, control, mode, candidates, production)
            for role in sides:
                dst, src = sides[role], one["sides"][role]
                dst["seconds"].extend(src["seconds"])
                for key in ("sample_attempts", "worlds", "capped_decisions", "decisions") + EXTRA_POLICY_WORK:
                    dst[key] += src[key]
                for key, value in src["mc_last_alloc"].items():
                    dst["mc_last_alloc"][key] += value
                for key, value in src['shortlist_work'].items():
                    dst['shortlist_work'][key] += value
            if one.get("error"):
                return {
                    "schema": SCHEMA, "seed": int(seed), "mirrors": mirrors,
                    "sides": sides, "max_rss_kib": one.get("max_rss_kib", _rss_kib()),
                    "elapsed_seconds": time.monotonic() - started,
                    "timeout": bool(one.get("timeout")), "error": one["error"],
                }
            mirrors.append(one["utility"])
        return {
            "schema": SCHEMA, "seed": int(seed), "mirrors": mirrors,
            "utility": float(statistics.fmean(mirrors)), "sides": sides,
            "max_rss_kib": _rss_kib(), "elapsed_seconds": time.monotonic() - started,
            "timeout": False, "error": None,
        }
    except TimeoutError as exc:
        return _refused(seed, sides, started, exc, timeout=True)
    except Exception as exc:
        return _refused(seed, sides, started, exc, timeout=False)


def _refused(seed, sides, started, exc, *, timeout: bool) -> dict[str, Any]:
    return {
        "schema": SCHEMA, "seed": int(seed), "mirrors": [],
        "sides": sides, "max_rss_kib": _rss_kib(),
        "elapsed_seconds": time.monotonic() - started, "timeout": timeout,
        "error": {"type": type(exc).__name__, "message": str(exc)},
    }


def _worker_init(checkpoint: str, checkpoint_sha256: str, worlds: int,
                 control: str, mode="policy", candidates=8, production=None) -> None:
    # Verify in every spawned process: a changed path cannot silently alter a
    # worker's model after the parent bound the recipe.
    if _sha256(Path(checkpoint)) != checkpoint_sha256:
        raise ValueError("prior checkpoint SHA256 mismatch in worker")
    try:
        import torch
        torch.set_num_threads(1)
    except ImportError:
        pass
    # Loading once here validates the checkpoint before any pair starts. The
    # PolicyWorldBot factory's checked loader is cached per process.
    make_policy(checkpoint, checkpoint_sha256, worlds, 0, mode, candidates)
    control_config(control, production)
    if production is not None:
        if _sha256(Path(production.checkpoint)) != PRODUCTION_SHA256:
            raise ValueError('production checkpoint SHA256 mismatch in worker')
        production.make(0)


def _worker_pair(args):
    seed, checkpoint, checksum, worlds, control, mode, candidates, production = args
    return play_pair(seed, checkpoint, checksum, worlds=worlds, control=control,
                     mode=mode, candidates=candidates, production=production)


def aggregate_records(records: Iterable[dict[str, Any]],
                      expected_seeds: Iterable[int]) -> dict[str, Any]:
    """Aggregate only a complete, unique, error-free seed set."""
    rows = list(records)
    expected = list(expected_seeds)
    expected_set = set(expected)
    by_seed = {}
    duplicates = []
    for row in rows:
        seed = row.get("seed")
        if seed in by_seed:
            duplicates.append(seed)
        by_seed[seed] = row
    missing = sorted(expected_set - set(by_seed))
    unexpected = sorted(set(by_seed) - expected_set)
    errors = [row for row in rows if row.get("error") or row.get("timeout")]
    if (len(expected_set) != len(expected) or len(rows) != len(expected)
            or missing or unexpected or duplicates or errors):
        raise ValueError({"missing": missing, "unexpected": unexpected,
                          "duplicates": duplicates,
                          "errors": errors})
    values = np.asarray([float(by_seed[s]["utility"]) for s in expected], dtype=float)
    if not np.isfinite(values).all():
        raise ValueError({"nonfinite_utility": True})
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    # Keep peak memory bounded for the largest permitted 4,000-deal run.
    boot_chunks = []
    for start in range(0, BOOTSTRAP_REPLICATES, 256):
        count = min(256, BOOTSTRAP_REPLICATES - start)
        indices = rng.integers(0, len(values), size=(count, len(values)))
        boot_chunks.append(values[indices].mean(axis=1))
    boot = np.concatenate(boot_chunks)

    def row_side(row, role):
        # Keeping aggregation tolerant of a deliberately tiny injected pair
        # makes the fail-closed seed checks independently testable.
        return row.get("sides", {}).get(role, _empty_side())

    def stats(role):
        seconds = np.asarray([x for s in expected
                              for x in row_side(by_seed[s], role).get("seconds", [])])
        if not len(seconds):
            return {"decisions": 0, "mean_seconds": None, "p95_seconds": None,
                    "max_seconds": None, "total_seconds": 0.0}
        return {"decisions": int(len(seconds)),
                "mean_seconds": float(seconds.mean()),
                "p95_seconds": float(np.quantile(seconds, .95)),
                "max_seconds": float(seconds.max()),
                "total_seconds": float(seconds.sum())}

    policy = {"timing": stats("policy")}
    policy["mc_last_alloc"] = {
        key: int(sum(row_side(by_seed[s], "policy").get("mc_last_alloc", {}).get(key, 0)
                     for s in expected))
        for key in _empty_side()["mc_last_alloc"]}
    policy.update({key: int(sum(row_side(by_seed[s], "policy").get(key, 0)
                                for s in expected))
                   for key in ("sample_attempts", "worlds", "capped_decisions", "decisions") + EXTRA_POLICY_WORK})
    mc = {"timing": stats("control")}
    mc['shortlist_work'] = {
        key: int(sum(row_side(by_seed[s], 'control').get('shortlist_work', {}).get(key, 0)
                     for s in expected)) for key in SHORTLIST_WORK}
    # Keep policy sampling separate from the legacy MC work fields. A
    # policy-only control performs zero MC worlds/rollouts, not zero work.
    mc["policy_work"] = {
        key: int(sum(row_side(by_seed[s], "control").get(key, 0) for s in expected))
        for key in ("sample_attempts", "worlds", "capped_decisions") + EXTRA_POLICY_WORK}
    for key in ("decisions", "short", "attempt_cap_hit", "worlds", "attempts", "rollouts",
                "report_worlds", "report_rollouts", "report_incomplete"):
        mc[key] = int(sum(row_side(by_seed[s], "control").get("mc_last_alloc", {})
                          .get(key, 0) for s in expected))
    mc["mc_decisions"] = mc["decisions"]
    mc["decisions"] = int(sum(row_side(by_seed[s], "control").get("decisions", 0)
                              for s in expected))
    return {
        "schema": SCHEMA, "expected": len(expected), "complete": len(rows),
        "mean": float(values.mean()), "mean_utility": float(values.mean()),
        "paired_bootstrap": {
            "replicates": BOOTSTRAP_REPLICATES, "seed": BOOTSTRAP_SEED,
            "ci95": [float(np.quantile(boot, .025)), float(np.quantile(boot, .975))],
        },
        "ci95": [float(np.quantile(boot, .025)), float(np.quantile(boot, .975))],
        "ties": int(np.count_nonzero(values == 0)),
        "policy": policy, "control": mc,
        "max_rss_kib": int(max(by_seed[s].get("max_rss_kib", 0)
                               for s in expected)),
    }


def _git_sha(repo: Path) -> str:
    return subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"],
                                   text=True).strip()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--checkpoint-sha256", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--deals", type=int, default=1)
    parser.add_argument("--seed0", type=int, required=True)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--worlds", type=int, default=4)
    parser.add_argument("--mode", choices=("policy", "policy-value", "policy-lookahead", "policy-selective-mc", "mc-policy-value-rollout"), default="policy")
    parser.add_argument("--candidates", type=int, default=8)
    parser.add_argument("--control", choices=CONTROL_NAMES, default="mc-lcb")
    parser.add_argument('--production-checkpoint',
                        help='pinned NumPy JS-M1 export; required only for production-play')
    return parser


def _validate_args(args) -> None:
    if args.mode == "mc-policy-value-rollout" and args.control != "mc-lcb":
        raise ValueError('MC rollout experiment requires matched mc-lcb control')
    if (args.control == 'production-play') != bool(args.production_checkpoint):
        raise ValueError('production-checkpoint is required exactly for production-play')
    if not (1 <= args.deals <= 4000):
        raise ValueError("deals must be in [1,4000]")
    if not (1 <= args.workers <= 16):
        raise ValueError("workers must be in [1,16]")
    if not (1 <= args.worlds <= 128):
        raise ValueError("worlds must be in [1,128]")
    if not (1 <= args.candidates <= 512):
        raise ValueError("candidates must be in [1,512]")
    if (len(args.checkpoint_sha256) != 64
            or any(c not in "0123456789abcdefABCDEF" for c in args.checkpoint_sha256)):
        raise ValueError("checkpoint-sha256 must be a 64-character hexadecimal digest")


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    _validate_args(args)
    args.checkpoint_sha256 = args.checkpoint_sha256.lower()
    checkpoint = Path(args.checkpoint).resolve()
    if not checkpoint.is_file():
        raise ValueError(f"checkpoint is not a file: {checkpoint}")
    actual = _sha256(checkpoint)
    if actual.lower() != args.checkpoint_sha256.lower():
        raise ValueError("checkpoint SHA256 mismatch")
    production = None
    if args.production_checkpoint:
        production_path = Path(args.production_checkpoint).resolve()
        if _sha256(production_path) != PRODUCTION_SHA256:
            raise ValueError('production checkpoint SHA256 mismatch')
        production = ProductionPlayControl(str(production_path))
    effective_control = full_control_config(args.control, production)
    out = Path(args.out).resolve()
    out.mkdir(parents=True, exist_ok=False)
    repo = Path(__file__).resolve().parents[3]
    policy_path = Path(inspect.getfile(PolicyWorldBot)).resolve()
    recipe = {
        "schema": SCHEMA, "checkpoint": str(checkpoint),
        "checkpoint_sha256": args.checkpoint_sha256.lower(),
        "seed0": args.seed0, "deals": args.deals, "workers": args.workers,
        "worlds": args.worlds, "cap": CAP, "control": args.control,
        "control_effective": effective_control,
        "policy": {"class": {"policy": "PolicyWorldBot", "policy-value": "PolicyValueBot",
                              "policy-selective-mc": "PolicySelectiveMCBot",
                              "policy-lookahead": "PolicyLookaheadBot",
                              "mc-policy-value-rollout": "MCPolicyValueRollout"}[args.mode],
                    "mode": args.mode, "candidates": args.candidates if args.mode != "policy" else None,
                    "value_head": "outcome" if args.mode != "policy" else None,
                    "value_batch_size": 128 if args.mode != "policy" else None,
                    "verification": ({"gap": 0.1, "worlds": 8, "candidates": 2,
                        "rollout_policy": "HeuristicBot", "utility": "root-team half-level",
                        "seed_offset": 1000000007, "exact_endgame": False}
                        if args.mode == "policy-selective-mc" else None),
                    "extra_plies": 4 if args.mode == "policy-lookahead" else 0,
                    "continuation_worlds": 1 if args.mode == "policy-lookahead" else 0,
                    "worlds": args.worlds,
                    "cap": CAP, "seed_formula": "seed*4+seat",
                    "declare_bury": "shared HeuristicBot"},
        "decision_timeout_seconds": DECISION_TIMEOUT_SECONDS,
        "timeout_contract": "cooperative SIGALRM refuses whole pair; external supervisor required for whole-job deadline",
        "source_git_sha": _git_sha(repo),
        "harness_sha256": _sha256(Path(__file__).resolve()),
        "policy_module_sha256": _sha256(policy_path),
        "policy_value_module_sha256": _sha256(Path(inspect.getfile(PolicyValueBot)).resolve()),
        "policy_selective_mc_module_sha256": _sha256(Path(inspect.getfile(PolicySelectiveMCBot)).resolve()),
        "policy_lookahead_module_sha256": _sha256(Path(inspect.getfile(PolicyLookaheadBot)).resolve()),
        "bootstrap": {"replicates": BOOTSTRAP_REPLICATES, "seed": BOOTSTRAP_SEED},
        "runtime": {
            "python": sys.version,
            "numpy": np.__version__,
            "environment": {
                key: os.environ[key] for key in sorted(os.environ)
                if key.startswith("SHENGJI_") or key in {
                    "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                }
            },
        },
    }
    if args.mode == "mc-policy-value-rollout":
        from .mc_policy_value_rollout import MCPolicyValueRollout
        recipe['mc_rollout_module_sha256'] = _sha256(
            Path(inspect.getfile(MCPolicyValueRollout)).resolve())
        recipe['policy']['root_mc'] = effective_control
        recipe['policy']['rollout'] = {
            'class': 'PolicyValueBot', 'worlds': args.worlds,
            'candidates': args.candidates, 'cap': CAP,
            'actor_public_resampling': True, 'terminal_score': 'attacker_points',
            'value_cutoff': False, 'exact_endgame': False,
            'rng': 'independent seed*4+seat stream reset for each outer rollout',
            'value_afterstate': 'heuristic completion of current trick',
        }
    (out / "recipe.json").write_text(json.dumps(recipe, indent=2, sort_keys=True) + "\n")
    expected = list(range(args.seed0, args.seed0 + args.deals))
    records = []
    started = time.monotonic()
    pair_args = [(seed, str(checkpoint), args.checkpoint_sha256, args.worlds, args.control,
                  args.mode, args.candidates, production)
                 for seed in expected]
    ctx = mp.get_context("spawn")
    with ProcessPoolExecutor(max_workers=args.workers, mp_context=ctx,
                             initializer=_worker_init,
                             initargs=(str(checkpoint), args.checkpoint_sha256,
                                       args.worlds, args.control, args.mode, args.candidates, production)) as pool, \
            (out / "pairs.jsonl").open("x") as handle:
        futures = {pool.submit(_worker_pair, item): item[0] for item in pair_args}
        for future in as_completed(futures):
            seed = futures[future]
            try:
                row = future.result()
            except Exception as exc:
                row = _refused(seed, _empty_side_map(), started, exc,
                               timeout=isinstance(exc, TimeoutError))
            records.append(row)
            handle.write(json.dumps(row, sort_keys=True) + "\n")
            handle.flush()
    records.sort(key=lambda row: row.get("seed", -1))
    try:
        summary = aggregate_records(records, expected)
        summary.update({"wall_seconds": time.monotonic() - started,
                        "errors": []})
        exit_code = 0
    except ValueError as exc:
        summary = {"schema": SCHEMA, "expected": len(expected),
                   "complete": len(records),
                   "errors": [row for row in records
                              if row.get("error") or row.get("timeout")],
                   "aggregation_error": str(exc),
                   "wall_seconds": time.monotonic() - started}
        exit_code = 1
    (out / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    return exit_code


def _empty_side_map():
    return {"policy": _empty_side(), "control": _empty_side()}


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, subprocess.SubprocessError) as exc:
        raise SystemExit(f"policy_world_duel refused: {exc}")
