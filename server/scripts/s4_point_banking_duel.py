#!/usr/bin/env python3
"""Complete-round S4 point-banking screen and confirmation runner.

The exact-state S4 screen established a narrow mechanism: when a rollout
player is last, already elects to win, can bank points, and retains a higher
winner, the point-card continuation improved the frozen late-game states.  It
did not establish whole-policy strength.  This runner asks that next question
on fresh complete rounds.

Three arms share every mirrored deal and every policy/opponent RNG seed:

``treatment``
    Exact live report-LCB with the frozen point-banking rollout continuation.
``matched_null``
    The same wrapper and trigger analysis, but always the historical cheap
    winner.  It should be behavior-identical to the live champion.
``champion``
    The exact deployed report-LCB parent with the feature absent.

The screen can open confirmation-packet review only.  Confirmation can record
strength, but neither phase promotes or deploys automatically.  A score-free
preflight publishes only work/capacity counters; it never publishes wins or
utility.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import random
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path


SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[1]
REPO = SERVER.parent
sys.path.insert(0, str(SERVER))
sys.path.insert(0, str(SCRIPT.parent))

import live_champion_parent as LIVE_PARENT  # noqa: E402
from shengji.ai.env import play_round  # noqa: E402
from shengji.ai.heuristic import HeuristicBot  # noqa: E402
from shengji.ai.point_banking import (  # noqa: E402
    POINT_BANKING_COUNTER_FIELDS,
    POINT_BANKING_POLICIES,
    empty_point_banking_telemetry,
    make_point_banking_bot,
)
from shengji.ai.registry import make_bot  # noqa: E402
from shengji.engine.ballot import mc_ballot  # noqa: E402
from shengji.engine.game import Game  # noqa: E402
from shengji.evaluation import counters, paired_by_seed  # noqa: E402


SCHEMA = "s4-point-banking-duel-shard-v1"
AGGREGATE_SCHEMA = "s4-point-banking-duel-aggregate-v1"
PREFLIGHT_SCHEMA = "s4-point-banking-duel-preflight-v1"
SHARD_COUNT = 8
STREAM_STRIDE = 3_000_017
POLICY_ROLE_OFFSETS = (0, 500_000)
OPPONENT_ROLE_OFFSETS = (1_000_000, 1_500_000)
PREFLIGHT_SEED0 = 40_000_000_000
PREFLIGHT_CLUSTERS = 4
PREFLIGHT_RUN_ID = "s4-point-banking-duel-preflight-40b-v1"
THROUGHPUT_SAFETY_FACTOR = 2.0
PHASES = {
    "screen": {
        "run_id": "s4-point-banking-duel-screen-50b-v1",
        "seed0": 50_000_000_000,
        "clusters": 2_048,
        "clusters_per_shard": 256,
        "claim": "non_promotable_s4_complete_round_screen",
    },
    "confirm": {
        "run_id": "s4-point-banking-duel-confirm-70b-v1",
        "seed0": 70_000_000_000,
        "clusters": 8_192,
        "clusters_per_shard": 1_024,
        "claim": "independent_s4_complete_round_confirmation",
    },
}
LABELS = {
    "treatment": POINT_BANKING_POLICIES["treatment"],
    "matched_null": POINT_BANKING_POLICIES["matched_null"],
    "champion": POINT_BANKING_POLICIES["base"],
}
LABEL_ORDER = tuple(LABELS)
CHAMPION = POINT_BANKING_POLICIES["base"]
OPPONENT = CHAMPION
REFUSED_ENV_KEYS = (
    "SHENGJI_WEIGHTED_SPLITS",
    "SHENGJI_UNIFORM_DEAL",
    "SHENGJI_PHYSICAL_FILLS",
    "SHENGJI_ALLOW_BALLOT_MISMATCH",
)
FORBIDDEN_COUNTER_FIELDS = (
    "void_fallbacks",
    "short_searches",
    "zero_world",
    "exact_endgames",
    "exact_endgame_attempts",
    "exact_endgame_refusals",
    "exact_endgame_budget_exceeded",
    "exact_endgame_sessions",
    "exact_endgame_nodes",
    "exact_endgame_cache_hits",
)
SELECTION_RULE = (
    "Over the complete registered mirrored population, continue only when "
    "LCB95(treatment-champion)>0 and LCB95(treatment-matched_null)>0; "
    "matched_null and champion have exactly equal outcomes on every seed/flip; "
    "treatment and matched_null both trigger in attacker and defender roles; "
    "treatment changes exactly its triggers, matched_null changes none and "
    "records one matched noop per trigger; all champion/opponent feature "
    "counters are zero; and every arm consumes exact registered MC work. A "
    "screen PASS authorizes confirmation-packet review only."
)
CLAIM_BOUNDARY = (
    "Fresh one-round paired level utility for the frozen S4 rollout-only "
    "continuation against exact live report-LCB under natural trigger traffic; "
    "not a reinterpretation of the 64-state mechanism screen, multi-round "
    "progression, automatic promotion, or production mutation."
)


class ProtocolRefused(RuntimeError):
    """The requested artifact cannot support the registered claim."""


def sha256(path: os.PathLike | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def stable_digest(value) -> str:
    raw = json.dumps(
        value, sort_keys=True, separators=(",", ":"), default=list,
    ).encode()
    return hashlib.sha256(raw).hexdigest()


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, check=True,
        capture_output=True, text=True,
    ).stdout.strip()


def write_exclusive(path: os.PathLike | str, payload: dict) -> None:
    final = Path(path)
    partial = Path(str(final) + ".partial")
    if os.path.lexists(final) or os.path.lexists(partial):
        raise ProtocolRefused(f"refusing to overwrite {final} or {partial}")
    final.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(payload, sort_keys=True, separators=(",", ":"))
           + "\n").encode()
    try:
        with partial.open("xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        if json.loads(partial.read_bytes()) != payload:
            raise ProtocolRefused("partial artifact failed exact reopen")
        os.link(partial, final)
        partial.unlink()
        if final.read_bytes() != raw:
            raise ProtocolRefused("published artifact differs from candidate")
    except BaseException:
        # An interrupted partial is evidence.  Never turn it into a retry.
        raise


def is_sha256(value: object) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(char in "0123456789abcdef" for char in value))


def source_paths() -> dict[str, Path]:
    return {
        "runner": SCRIPT,
        "live_parent": SERVER / "scripts/live_champion_parent.py",
        "point_banking": SERVER / "shengji/ai/point_banking.py",
        "evaluation": SERVER / "shengji/evaluation.py",
        "registry": SERVER / "shengji/ai/registry.py",
        "mcbot": SERVER / "shengji/ai/mcbot.py",
        "heuristic": SERVER / "shengji/ai/heuristic.py",
        "env": SERVER / "shengji/ai/env.py",
        "game": SERVER / "shengji/engine/game.py",
        "round": SERVER / "shengji/engine/round.py",
    }


def source_sha256s() -> dict[str, str]:
    return {name: sha256(path) for name, path in source_paths().items()}


def uppercase_contract(bot) -> dict:
    values = {}
    for name in dir(bot):
        if not name.isupper():
            continue
        value = getattr(bot, name)
        if not isinstance(value, (bool, int, float, str, type(None))):
            raise ProtocolRefused(
                f"non-serializable policy contract {name}={value!r}")
        values[name] = value
    return values


def make_arm(label: str, seed: int):
    if label == "treatment":
        return make_point_banking_bot(treatment=True, seed=seed)
    if label == "matched_null":
        return make_point_banking_bot(treatment=False, seed=seed)
    if label == "champion":
        return make_bot(CHAMPION, seed=seed)
    raise ProtocolRefused(f"unknown S4 arm {label!r}")


def policy_contract(label: str) -> dict:
    bot = make_arm(label, 7)
    return {
        "label": label,
        "policy": LABELS[label],
        "class": type(bot).__name__,
        "uppercase": uppercase_contract(bot),
        "rollout_policy_class": type(bot.rollout_policy).__name__,
        "rollout_mode": getattr(bot.rollout_policy, "mode", "off"),
        "root_ballot_digest": mc_ballot(bot).digest,
    }


def phase_identity(phase: str) -> dict:
    if phase not in PHASES:
        raise ProtocolRefused(f"unknown S4 phase {phase!r}")
    return {
        "phase": phase,
        **PHASES[phase],
        "shard_count": SHARD_COUNT,
        "stream_stride": STREAM_STRIDE,
        "labels": LABELS,
        "opponent": OPPONENT,
        "selection_rule": SELECTION_RULE,
        "claim_boundary": CLAIM_BOUNDARY,
    }


def cluster_seed(phase: str, cluster_index: int) -> int:
    spec = PHASES[phase]
    if not 0 <= cluster_index < spec["clusters"]:
        raise ProtocolRefused("cluster index outside registered population")
    return spec["seed0"] + STREAM_STRIDE * cluster_index


def _stream_uses(seed0: int, clusters: int) -> list[tuple[int, int, str]]:
    uses = []
    for cluster_index in range(clusters):
        seed = seed0 + STREAM_STRIDE * cluster_index
        for role_index, offset in enumerate(POLICY_ROLE_OFFSETS):
            # All three arms deliberately share these CRN streams.
            uses.append((seed + offset, cluster_index,
                         f"shared-policy-{role_index}"))
        for role_index, offset in enumerate(OPPONENT_ROLE_OFFSETS):
            uses.append((seed + offset, cluster_index,
                         f"shared-opponent-{role_index}"))
    return uses


def global_stream_problems() -> list[str]:
    populations = {
        "preflight": _stream_uses(PREFLIGHT_SEED0, PREFLIGHT_CLUSTERS),
        **{phase: _stream_uses(spec["seed0"], spec["clusters"])
           for phase, spec in PHASES.items()},
    }
    by_seed: dict[int, list[tuple[str, int, str]]] = {}
    for population, uses in populations.items():
        for seed, cluster_index, role in uses:
            by_seed.setdefault(seed, []).append(
                (population, cluster_index, role))
    return [
        f"global seed collision {seed}: {uses}"
        for seed, uses in by_seed.items() if len(uses) != 1
    ]


def protocol_problems(parent: dict) -> list[str]:
    problems = []
    if parent.get("champion_policy") != CHAMPION:
        problems.append("S4 parent is not exact live report-LCB")
    if POINT_BANKING_POLICIES != {
            "base": "mc-s0-report-lcb",
            "treatment": "mc-s0-report-lcb-point-banking",
            "matched_null": "mc-s0-report-lcb-point-banking-null"}:
        problems.append("S4 policy labels drifted")
    if SHARD_COUNT != 8 or STREAM_STRIDE != 3_000_017:
        problems.append("S4 shard/stream geometry drifted")
    problems.extend(global_stream_problems())
    try:
        bots = {label: make_arm(label, 7) for label in LABEL_ORDER}
        contracts = {label: uppercase_contract(bot)
                     for label, bot in bots.items()}
        ballots = {label: mc_ballot(bot).digest
                   for label, bot in bots.items()}
    except Exception as exc:
        problems.append(
            f"S4 arm construction failed: {type(exc).__name__}: {exc}")
        return sorted(set(problems))
    if len({stable_digest(value) for value in contracts.values()}) != 1:
        problems.append("S4 arms differ outside rollout policy")
    if len(set(ballots.values())) != 1:
        problems.append("S4 root ballots differ")
    if type(bots["champion"].rollout_policy) is not HeuristicBot:
        problems.append("S4 champion rollout is not historical heuristic")
    if getattr(bots["treatment"].rollout_policy, "mode", None) != "treatment":
        problems.append("S4 treatment rollout mode drifted")
    if getattr(bots["matched_null"].rollout_policy, "mode", None) != \
            "matched_null":
        problems.append("S4 null rollout mode drifted")
    if bots["treatment"].rng.getstate() != bots["matched_null"].rng.getstate() \
            or bots["treatment"].rng.getstate() != bots["champion"].rng.getstate():
        problems.append("S4 root RNG streams differ")
    for label, bot in bots.items():
        if any(getattr(bot, name, False) for name in (
                "MC_BURY", "STRUCTURED_BURY", "EXACT_ENDGAME",
                "ADAPTIVE_ALLOCATION", "RANDOM_ALLOCATION")):
            problems.append(f"{label} enables an out-of-scope feature")
    if getattr(bots["treatment"], "point_banking_base_policy", None) != CHAMPION:
        problems.append("S4 treatment names the wrong parent")
    if getattr(bots["matched_null"], "point_banking_base_policy", None) != CHAMPION:
        problems.append("S4 null names the wrong parent")
    return sorted(set(problems))


def require_runtime(expected_git: str) -> tuple[dict, dict]:
    if os.environ.get("SHENGJI_FAST") != "1" or \
            os.environ.get("SHENGJI_REQUIRE_VOIDS") != "1":
        raise ProtocolRefused("set SHENGJI_FAST=1 and SHENGJI_REQUIRE_VOIDS=1")
    enabled = [name for name in REFUSED_ENV_KEYS if os.environ.get(name)]
    if enabled:
        raise ProtocolRefused(f"experimental flags must be unset: {enabled}")
    from shengji.engine import combos, fast
    if not fast.HAVE_FAST or combos.decompose is not fast.decompose:
        raise ProtocolRefused("compiled engine requested but not active")
    head = git("rev-parse", "HEAD")
    if head != expected_git:
        raise ProtocolRefused("exact S4 runner git predeclaration")
    if git("status", "--porcelain"):
        raise ProtocolRefused("S4 duel refuses a dirty tree")
    try:
        parent = LIVE_PARENT.require_live_champion_parent()
    except LIVE_PARENT.ProtocolRefused as exc:
        raise ProtocolRefused(f"live champion parent refused: {exc}") from exc
    problems = protocol_problems(parent)
    if problems:
        raise ProtocolRefused("S4 protocol drift: " + "; ".join(problems))
    runtime = {
        "git": head,
        "tree_dirty": False,
        "host": platform.node(),
        "python": platform.python_version(),
        "fast_engine": True,
        "require_voids": True,
        "experimental_flags": [],
        "source_sha256s": source_sha256s(),
        "fast_binary_sha256": sha256(fast._fast.__file__),
        "policy_contract_sha256s": {
            label: stable_digest(policy_contract(label))
            for label in LABEL_ORDER
        },
        "stream_digests": {
            "preflight": stable_digest(
                _stream_uses(PREFLIGHT_SEED0, PREFLIGHT_CLUSTERS)),
            **{phase: stable_digest(
                _stream_uses(spec["seed0"], spec["clusters"]))
               for phase, spec in PHASES.items()},
        },
    }
    return parent, runtime


def point_banking_telemetry(bots, *, mode: str) -> dict:
    if mode == "off":
        return empty_point_banking_telemetry(mode="off")
    payloads = [bot.point_banking_telemetry() for bot in bots]
    if any(payload.get("mode") != mode for payload in payloads):
        raise ProtocolRefused("point-banking bot telemetry mode drift")
    return {
        "schema": "point-banking-rollout-telemetry-v1",
        "mode": mode,
        "deterministic": all(
            payload.get("deterministic") is True for payload in payloads),
        "exact_work_complete": all(
            payload.get("exact_work_complete") is True for payload in payloads),
        **{name: sum(int(payload[name]) for payload in payloads)
           for name in POINT_BANKING_COUNTER_FIELDS},
    }


def _record(run_id: str, label: str, seed: int, flip: int, won: int,
            level_utility: int, arm_bots, opp_bots) -> dict:
    mode = {"treatment": "treatment", "matched_null": "matched_null",
            "champion": "off"}[label]
    return {
        "run": run_id,
        "label": label,
        "policy": LABELS[label],
        "opponent": OPPONENT,
        "seed": seed,
        "flip": flip,
        "won": won,
        "level_utility": level_utility,
        "arm": {
            **counters(arm_bots),
            "point_banking": point_banking_telemetry(arm_bots, mode=mode),
        },
        "opp": {
            **counters(opp_bots),
            "point_banking": point_banking_telemetry(opp_bots, mode="off"),
        },
    }


def play_arm_cluster(label: str, seed: int, *, run_id: str) -> list[dict]:
    records = []
    for flip in (0, 1):
        a1 = make_arm(label, seed)
        a2 = make_arm(label, seed + POLICY_ROLE_OFFSETS[1])
        b1 = make_bot(OPPONENT, seed=seed + OPPONENT_ROLE_OFFSETS[0])
        b2 = make_bot(OPPONENT, seed=seed + OPPONENT_ROLE_OFFSETS[1])
        policies = ([a1, b1, a2, b2] if flip == 0
                    else [b1, a1, b2, a2])
        log = play_round(Game(random.Random(seed)), policies)
        policy_team = 0 if flip == 0 else 1
        won = int(log.winner_team == policy_team)
        utility = (1 if won else -1) * max(1, int(log.level_change))
        records.append(_record(
            run_id, label, seed, flip, won, utility,
            [a1, a2], [b1, b2]))
    return records


def telemetry_problems(value: object, *, expected_mode: str) -> list[str]:
    if not isinstance(value, dict):
        return ["point-banking telemetry is not an object"]
    expected_fields = {
        "schema", "mode", "deterministic", "exact_work_complete",
        *POINT_BANKING_COUNTER_FIELDS,
    }
    problems = []
    if set(value) != expected_fields:
        problems.append("point-banking telemetry field population")
    if (value.get("schema") != "point-banking-rollout-telemetry-v1"
            or value.get("mode") != expected_mode
            or value.get("deterministic") is not True
            or value.get("exact_work_complete") is not True):
        problems.append("point-banking telemetry identity")
    valid = all(
        isinstance(value.get(name), int)
        and not isinstance(value.get(name), bool)
        and value[name] >= 0
        for name in POINT_BANKING_COUNTER_FIELDS
    )
    if not valid:
        problems.append("point-banking telemetry counters")
        return sorted(set(problems))
    if value["triggers"] != value["attacker_triggers"] + \
            value["defender_triggers"]:
        problems.append("point-banking role counters do not reconcile")
    if value["triggers"] > value["opportunities"]:
        problems.append("point-banking triggers exceed opportunities")
    if value["single_follow_calls"] > value["follow_calls"]:
        problems.append("point-banking single follows exceed follows")
    if value["legal_winning_actions"] > value["candidate_checks"]:
        problems.append("point-banking winners exceed checks")
    if value["opportunities"] != (
            value["triggers"] + value["decline_not_last"]
            + value["decline_no_higher_reserve"]):
        problems.append("point-banking opportunity paths do not reconcile")
    if value["point_gain"] < 5 * value["triggers"]:
        problems.append("point-banking point gain is impossible")
    if expected_mode == "treatment":
        if value["changes"] != value["triggers"] or value["matched_noops"] != 0:
            problems.append("point-banking treatment dose mismatch")
    elif expected_mode == "matched_null":
        if value["changes"] != 0 or \
                value["matched_noops"] != value["triggers"]:
            problems.append("point-banking null dose mismatch")
    elif any(value[name] != 0 for name in POINT_BANKING_COUNTER_FIELDS):
        problems.append("feature-off point-banking telemetry is nonzero")
    return sorted(set(problems))


def counter_problems(value: object, *, expected_mode: str) -> list[str]:
    if not isinstance(value, dict):
        return ["counter payload is not an object"]
    expected_fields = set(counters([])) | {"point_banking"}
    problems = []
    if set(value) != expected_fields:
        problems.append("counter field population")
    for name in set(counters([])) - {"search_secs"}:
        item = value.get(name)
        if isinstance(item, bool) or not isinstance(item, int) or item < 0:
            problems.append(f"counter {name} is not a non-negative integer")
    seconds = value.get("search_secs")
    if (isinstance(seconds, bool) or not isinstance(seconds, (int, float))
            or not math.isfinite(seconds) or seconds < 0):
        problems.append("counter search_secs is not non-negative finite")
    if (isinstance(value.get("sample_attempts"), int)
            and isinstance(value.get("accepted_worlds"), int)
            and isinstance(value.get("failed_worlds"), int)
            and value["sample_attempts"] !=
            value["accepted_worlds"] + value["failed_worlds"]):
        problems.append("sampler counters do not reconcile")
    if (isinstance(value.get("rejected_worlds"), int)
            and isinstance(value.get("failed_worlds"), int)
            and value["rejected_worlds"] > value["failed_worlds"]):
        problems.append("rejected worlds exceed failed worlds")
    for name in FORBIDDEN_COUNTER_FIELDS:
        if value.get(name) != 0:
            problems.append(f"forbidden counter {name} is nonzero")
    problems.extend(telemetry_problems(
        value.get("point_banking"), expected_mode=expected_mode))
    return sorted(set(problems))


def record_problems(record: object, *, phase: str, expected_seed: int,
                    expected_label: str, expected_flip: int,
                    expected_run_id: str | None = None) -> list[str]:
    if not isinstance(record, dict):
        return ["record is not an object"]
    expected_fields = {
        "run", "label", "policy", "opponent", "seed", "flip", "won",
        "level_utility", "arm", "opp",
    }
    problems = []
    run_id = expected_run_id or PHASES[phase]["run_id"]
    if set(record) != expected_fields:
        problems.append("record field population")
    if (record.get("run") != run_id
            or record.get("label") != expected_label
            or record.get("policy") != LABELS[expected_label]
            or record.get("opponent") != OPPONENT
            or record.get("seed") != expected_seed
            or record.get("flip") != expected_flip):
        problems.append("record identity")
    if record.get("won") not in (0, 1):
        problems.append("record win value")
    utility = record.get("level_utility")
    if (isinstance(utility, bool) or not isinstance(utility, int)
            or utility == 0):
        problems.append("record level utility")
    mode = {"treatment": "treatment", "matched_null": "matched_null",
            "champion": "off"}[expected_label]
    problems.extend(
        f"arm: {problem}" for problem in counter_problems(
            record.get("arm"), expected_mode=mode))
    problems.extend(
        f"opp: {problem}" for problem in counter_problems(
            record.get("opp"), expected_mode="off"))
    return sorted(set(problems))


def shard_problems(payload: object, *, phase: str, shard_index: int,
                   parent: dict, runtime: dict) -> list[str]:
    if not isinstance(payload, dict):
        return ["shard is not an object"]
    expected_fields = {
        "schema", "complete", "phase", "phase_identity", "shard_index",
        "cluster_indexes", "parent", "runtime", "records",
        "production_promotion", "retry_or_extension_authorized",
    }
    problems = []
    if set(payload) != expected_fields:
        problems.append("shard field population")
    expected_indexes = list(range(
        shard_index, PHASES[phase]["clusters"], SHARD_COUNT))
    if (payload.get("schema") != SCHEMA
            or payload.get("complete") is not True
            or payload.get("phase") != phase
            or payload.get("phase_identity") != phase_identity(phase)
            or payload.get("shard_index") != shard_index
            or payload.get("cluster_indexes") != expected_indexes
            or payload.get("parent") != parent
            or payload.get("runtime") != runtime
            or payload.get("production_promotion") is not False
            or payload.get("retry_or_extension_authorized") is not False):
        problems.append("shard identity")
    records = payload.get("records")
    expected_count = len(expected_indexes) * len(LABEL_ORDER) * 2
    if not isinstance(records, list) or len(records) != expected_count:
        problems.append("shard record count")
        return sorted(set(problems))
    cursor = 0
    for cluster_index in expected_indexes:
        seed = cluster_seed(phase, cluster_index)
        for label in LABEL_ORDER:
            for flip in (0, 1):
                problems.extend(
                    f"record {cursor}: {problem}"
                    for problem in record_problems(
                        records[cursor], phase=phase, expected_seed=seed,
                        expected_label=label, expected_flip=flip))
                cursor += 1
    return sorted(set(problems))


def run_shard(args) -> None:
    parent, runtime = require_runtime(args.expected_git)
    phase = args.phase
    indexes = list(range(
        args.shard_index, PHASES[phase]["clusters"], SHARD_COUNT))
    records = []
    for local_index, cluster_index in enumerate(indexes, 1):
        seed = cluster_seed(phase, cluster_index)
        for label in LABEL_ORDER:
            records.extend(play_arm_cluster(
                label, seed, run_id=PHASES[phase]["run_id"]))
        if args.progress_every and local_index % args.progress_every == 0:
            print(json.dumps({
                "event": "s4-point-banking-duel-progress-v1",
                "phase": phase,
                "shard_index": args.shard_index,
                "clusters_complete": local_index,
                "clusters_total": len(indexes),
            }, sort_keys=True), flush=True)
    payload = {
        "schema": SCHEMA,
        "complete": True,
        "phase": phase,
        "phase_identity": phase_identity(phase),
        "shard_index": args.shard_index,
        "cluster_indexes": indexes,
        "parent": parent,
        "runtime": runtime,
        "records": records,
        "production_promotion": False,
        "retry_or_extension_authorized": False,
    }
    problems = shard_problems(
        payload, phase=phase, shard_index=args.shard_index,
        parent=parent, runtime=runtime)
    if problems:
        raise ProtocolRefused("invalid S4 shard: " + "; ".join(problems))
    write_exclusive(args.out, payload)


def _sum_telemetry(records: list[dict], side: str) -> dict:
    totals = Counter({name: 0 for name in POINT_BANKING_COUNTER_FIELDS})
    modes = set()
    for record in records:
        telemetry = record[side]["point_banking"]
        modes.add(telemetry["mode"])
        totals.update({name: telemetry[name]
                       for name in POINT_BANKING_COUNTER_FIELDS})
    if len(modes) != 1:
        raise ProtocolRefused("aggregate point-banking mode drift")
    return {"mode": next(iter(modes)), **dict(totals)}


def contrast(records: dict[str, list[dict]], a: str, b: str) -> dict:
    mean, half, clusters = paired_by_seed(records[a], records[b])
    return {
        "a": a,
        "b": b,
        "mean": mean,
        "half_width95": half,
        "lcb95": mean - half,
        "ucb95": mean + half,
        "clusters": clusters,
    }


def build_aggregate(*, phase: str, shards: list[dict], inputs: list[dict],
                    parent: dict, runtime: dict,
                    screen_parent: dict | None) -> dict:
    records = {label: [] for label in LABEL_ORDER}
    for shard in shards:
        for record in shard["records"]:
            records[record["label"]].append(record)
    expected_records = PHASES[phase]["clusters"] * 2
    if any(len(values) != expected_records for values in records.values()):
        raise ProtocolRefused("aggregate record population drift")
    keys = {
        label: {(row["seed"], row["flip"]) for row in values}
        for label, values in records.items()
    }
    if any(len(value) != expected_records for value in keys.values()) \
            or len({frozenset(value) for value in keys.values()}) != 1:
        raise ProtocolRefused("aggregate CRN population drift")

    stats = {
        "treatment_champion": contrast(records, "treatment", "champion"),
        "treatment_matched_null": contrast(
            records, "treatment", "matched_null"),
        "matched_null_champion": contrast(
            records, "matched_null", "champion"),
    }
    telemetry = {
        label: {
            "arm": _sum_telemetry(values, "arm"),
            "opp": _sum_telemetry(values, "opp"),
        }
        for label, values in records.items()
    }
    treatment = telemetry["treatment"]["arm"]
    matched_null = telemetry["matched_null"]["arm"]
    null_outcomes_equal = all(
        (left["won"], left["level_utility"])
        == (right["won"], right["level_utility"])
        for left, right in zip(
            records["matched_null"], records["champion"], strict=True)
    )
    controls_zero = all(
        value[side][name] == 0
        for label, value in telemetry.items()
        for side in ("arm", "opp")
        for name in POINT_BANKING_COUNTER_FIELDS
        if label == "champion" or side == "opp"
    )
    exact_work = all(
        not counter_problems(
            record[side],
            expected_mode=(
                {"treatment": "treatment", "matched_null": "matched_null",
                 "champion": "off"}[record["label"]]
                if side == "arm" else "off"))
        for values in records.values()
        for record in values
        for side in ("arm", "opp")
    )
    criteria = {
        "treatment_champion_lcb_gt_zero": (
            stats["treatment_champion"]["lcb95"] > 0),
        "treatment_matched_null_lcb_gt_zero": (
            stats["treatment_matched_null"]["lcb95"] > 0),
        "matched_null_champion_exact_outcomes": null_outcomes_equal,
        "treatment_triggered_both_roles": (
            treatment["attacker_triggers"] > 0
            and treatment["defender_triggers"] > 0),
        "matched_null_triggered_both_roles": (
            matched_null["attacker_triggers"] > 0
            and matched_null["defender_triggers"] > 0),
        "treatment_dose_exact": (
            treatment["triggers"] > 0
            and treatment["changes"] == treatment["triggers"]
            and treatment["matched_noops"] == 0),
        "matched_null_dose_exact": (
            matched_null["triggers"] > 0
            and matched_null["changes"] == 0
            and matched_null["matched_noops"] == matched_null["triggers"]),
        "controls_feature_off": controls_zero,
        "all_records_exact_work": exact_work,
    }
    criteria["all"] = all(criteria.values())
    if criteria["all"]:
        status = ("AUTHORIZE_CONFIRM_PACKET_REVIEW" if phase == "screen"
                  else "CONFIRM_S4_POINT_BANKING_STRENGTH")
    else:
        status = "SELECT_NONE"
    return {
        "schema": AGGREGATE_SCHEMA,
        "complete": True,
        "phase": phase,
        "phase_identity": phase_identity(phase),
        "parent": parent,
        "runtime": runtime,
        "screen_parent": screen_parent,
        "inputs": inputs,
        "stats": stats,
        "point_banking_telemetry": telemetry,
        "criteria": criteria,
        "status": status,
        "strength_claim": phase == "confirm" and criteria["all"],
        "production_promotion": False,
        "retry_or_extension_authorized": False,
        "explicit_deployment_review_required": True,
    }


def load_shards(args, *, parent: dict, runtime: dict):
    if len(args.shards) != SHARD_COUNT:
        raise ProtocolRefused(f"expected exactly {SHARD_COUNT} shards")
    shards = []
    inputs = []
    seen = set()
    for expected_index, raw_path in enumerate(args.shards):
        path = Path(raw_path)
        partial = Path(str(path) + ".partial")
        if (not path.is_file() or path.is_symlink() or os.path.lexists(partial)):
            raise ProtocolRefused(f"invalid shard artifact {path}")
        digest = sha256(path)
        if digest in seen:
            raise ProtocolRefused("duplicate shard digest")
        seen.add(digest)
        payload = json.loads(path.read_bytes())
        problems = shard_problems(
            payload, phase=args.phase, shard_index=expected_index,
            parent=parent, runtime=runtime)
        if problems:
            raise ProtocolRefused(
                f"invalid shard {expected_index}: " + "; ".join(problems))
        shards.append(payload)
        inputs.append({
            "path": str(path), "sha256": digest,
            "shard_index": expected_index,
        })
    return shards, inputs


def load_screen_parent(path: str | None, expected_sha256: str | None, *,
                       parent: dict, runtime: dict) -> dict | None:
    if path is None and expected_sha256 is None:
        return None
    if not path or not is_sha256(expected_sha256):
        raise ProtocolRefused("screen parent path and SHA-256 are both required")
    source = Path(path)
    if (not source.is_file() or source.is_symlink()
            or os.path.lexists(Path(str(source) + ".partial"))
            or sha256(source) != expected_sha256):
        raise ProtocolRefused("screen parent unavailable or drifted")
    payload = json.loads(source.read_bytes())
    if (payload.get("schema") != AGGREGATE_SCHEMA
            or payload.get("complete") is not True
            or payload.get("phase") != "screen"
            or payload.get("status") != "AUTHORIZE_CONFIRM_PACKET_REVIEW"
            or payload.get("parent") != parent
            or payload.get("criteria", {}).get("all") is not True
            or payload.get("strength_claim") is not False
            or payload.get("production_promotion") is not False):
        raise ProtocolRefused("screen parent did not authorize confirm review")
    prior_runtime = payload.get("runtime")
    stable_fields = (
        "python", "fast_engine", "require_voids", "experimental_flags",
        "source_sha256s", "fast_binary_sha256", "policy_contract_sha256s",
        "stream_digests",
    )
    if (not isinstance(prior_runtime, dict)
            or any(prior_runtime.get(name) != runtime.get(name)
                   for name in stable_fields)):
        raise ProtocolRefused("screen parent runtime/source contract drifted")
    return {"path": str(source), "sha256": expected_sha256,
            "status": payload["status"]}


def aggregate_command(args) -> None:
    parent, runtime = require_runtime(args.expected_git)
    screen_parent = load_screen_parent(
        args.screen_aggregate, args.expected_screen_aggregate_sha256,
        parent=parent, runtime=runtime)
    if args.phase == "screen" and screen_parent is not None:
        raise ProtocolRefused("screen phase cannot consume a screen parent")
    if args.phase == "confirm" and screen_parent is None:
        raise ProtocolRefused("confirmation requires an exact passing screen")
    shards, inputs = load_shards(args, parent=parent, runtime=runtime)
    payload = build_aggregate(
        phase=args.phase, shards=shards, inputs=inputs,
        parent=parent, runtime=runtime, screen_parent=screen_parent)
    write_exclusive(args.out, payload)
    print(json.dumps({
        "schema": AGGREGATE_SCHEMA,
        "phase": args.phase,
        "status": payload["status"],
        "criteria": payload["criteria"],
        "strength_claim": payload["strength_claim"],
        "production_promotion": False,
    }, sort_keys=True), flush=True)


def _add_record_counters(totals: Counter, record: dict) -> None:
    for side in ("arm", "opp"):
        values = record[side]
        for name in set(counters([])) - {"search_secs"}:
            totals[f"{side}_{name}"] += values[name]
        totals[f"{side}_search_secs_millis"] += round(
            1_000 * values["search_secs"])


def preflight(args) -> None:
    parent, runtime = require_runtime(args.expected_git)
    started = time.perf_counter()
    totals = {label: Counter() for label in LABEL_ORDER}
    telemetry = {label: Counter({name: 0 for name in
                                 POINT_BANKING_COUNTER_FIELDS})
                 for label in LABEL_ORDER}
    mode = {"treatment": "treatment", "matched_null": "matched_null",
            "champion": "off"}
    problems = []
    for cluster_index in range(PREFLIGHT_CLUSTERS):
        seed = PREFLIGHT_SEED0 + STREAM_STRIDE * cluster_index
        for label in LABEL_ORDER:
            records = play_arm_cluster(
                label, seed, run_id=PREFLIGHT_RUN_ID)
            for flip, record in enumerate(records):
                problems.extend(record_problems(
                    record, phase="screen", expected_seed=seed,
                    expected_label=label, expected_flip=flip,
                    expected_run_id=PREFLIGHT_RUN_ID))
                _add_record_counters(totals[label], record)
                telemetry[label].update({
                    name: record["arm"]["point_banking"][name]
                    for name in POINT_BANKING_COUNTER_FIELDS
                })
                # Explicitly discard outcome-bearing rows before publication.
            del records
        print(json.dumps({
            "event": "s4-point-banking-preflight-progress-v1",
            "clusters_complete": cluster_index + 1,
            "clusters_total": PREFLIGHT_CLUSTERS,
        }, sort_keys=True), flush=True)
    elapsed = time.perf_counter() - started
    per_cluster = elapsed / PREFLIGHT_CLUSTERS
    projections = {}
    for phase, spec in PHASES.items():
        fleet_hours = (per_cluster * spec["clusters"]
                       * THROUGHPUT_SAFETY_FACTOR / 3_600)
        projections[phase] = {
            "fleet_hours": fleet_hours,
            "max_shard_hours": fleet_hours / SHARD_COUNT,
        }
    treatment = telemetry["treatment"]
    matched_null = telemetry["matched_null"]
    controls_zero = all(
        telemetry["champion"][name] == 0
        for name in POINT_BANKING_COUNTER_FIELDS)
    criteria = {
        "records_valid": not problems,
        "treatment_triggered": treatment["triggers"] > 0,
        "matched_null_triggered": matched_null["triggers"] > 0,
        "treatment_dose_exact": (
            treatment["changes"] == treatment["triggers"]
            and treatment["matched_noops"] == 0),
        "matched_null_dose_exact": (
            matched_null["changes"] == 0
            and matched_null["matched_noops"] == matched_null["triggers"]),
        "champion_feature_off": controls_zero,
        "screen_fleet_hours_le_100": projections["screen"]["fleet_hours"] <= 100,
        "screen_max_shard_hours_le_15": (
            projections["screen"]["max_shard_hours"] <= 15),
    }
    criteria["all"] = all(criteria.values())
    payload = {
        "schema": PREFLIGHT_SCHEMA,
        "complete": True,
        "score_free": True,
        "outcomes_published": False,
        "outcomes_discarded": True,
        "run_id": PREFLIGHT_RUN_ID,
        "clusters": PREFLIGHT_CLUSTERS,
        "seed0": PREFLIGHT_SEED0,
        "stream_stride": STREAM_STRIDE,
        "parent": parent,
        "runtime": runtime,
        "elapsed_seconds": elapsed,
        "throughput_safety_factor": THROUGHPUT_SAFETY_FACTOR,
        "counter_totals": {label: dict(values)
                           for label, values in totals.items()},
        "point_banking_telemetry": {label: {
            "mode": mode[label], **dict(values)}
            for label, values in telemetry.items()},
        "projections": projections,
        "criteria": criteria,
        "status": ("AUTHORIZE_FULL_GAME_PACKET_REVIEW"
                   if criteria["all"] else "HOLD"),
        "screen_launch_authorized": False,
        "confirmation_launch_authorized": False,
        "strength_claim": False,
        "training_authorized": False,
        "production_promotion": False,
        "retry_or_extension_authorized": False,
    }
    write_exclusive(args.out, payload)
    print(json.dumps({
        "schema": PREFLIGHT_SCHEMA,
        "score_free": True,
        "status": payload["status"],
        "criteria": criteria,
        "projections": projections,
    }, sort_keys=True), flush=True)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser()
    commands = root.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run")
    run.add_argument("--expected-git", required=True)
    run.add_argument("--phase", choices=tuple(PHASES), required=True)
    run.add_argument("--shard-index", type=int, required=True)
    run.add_argument("--progress-every", type=int, default=1)
    run.add_argument("--out", required=True)

    agg = commands.add_parser("aggregate")
    agg.add_argument("--expected-git", required=True)
    agg.add_argument("--phase", choices=tuple(PHASES), required=True)
    agg.add_argument("--shards", nargs="+", required=True)
    agg.add_argument("--screen-aggregate")
    agg.add_argument("--expected-screen-aggregate-sha256")
    agg.add_argument("--out", required=True)

    preflight_parser = commands.add_parser("preflight")
    preflight_parser.add_argument("--expected-git", required=True)
    preflight_parser.add_argument("--out", required=True)
    return root


def main() -> None:
    args = parser().parse_args()
    if args.command == "run":
        if not 0 <= args.shard_index < SHARD_COUNT:
            raise ProtocolRefused("shard index outside registered range")
        if args.progress_every < 0:
            raise ProtocolRefused("progress cadence cannot be negative")
        run_shard(args)
    elif args.command == "aggregate":
        aggregate_command(args)
    else:
        preflight(args)


if __name__ == "__main__":
    main()
