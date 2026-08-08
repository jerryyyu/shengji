#!/usr/bin/env python3
"""Fresh complete-round strength protocol for S3a structured bury.

The 136M state screen established a mechanism, not bot strength.  This file
defines the next bounded question: does enabling only structured bury improve
complete-round signed level utility over the exact live report-LCB champion?

The screen and confirmation use fresh sparse deal-seed populations, mirrored
flips, the exact champion as opponent, and three paired arms:

* structured: ``mc-s0-report-lcb-structured-bury``;
* champion: ``mc-s0-report-lcb``;
* null: the champion-matched RNG-shifted null already in the registry.

Sparse seeds are deliberate.  The historical null shift is 999,983, while
the evaluator's policy/opponent role offsets reach 1,500,000.  Consecutive
deal seeds therefore collide across clusters.  A 2,000,003 stride is larger
than every within-cluster role offset and is proved collision-free over both
registered populations before any play.

``preflight`` is score-free: it retains only time, counters and structured-
bury activation telemetry.  ``run`` publishes one immutable shard.
``aggregate`` independently reopens all eight shards and is the only command
that computes contrasts.  A passing screen authorizes confirmation packet
review only; a passing confirmation still requires explicit deployment
review.  No command changes production.
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
from shengji.ai.mcbot import STRUCTURED_BURY_TELEMETRY_FIELDS  # noqa: E402
from shengji.ai.registry import make_bot  # noqa: E402
from shengji.engine.game import Game  # noqa: E402
from shengji.evaluation import arm_ballots, counters, paired_by_seed  # noqa: E402


SCHEMA = "s3a-bury-duel-shard-v1"
AGGREGATE_SCHEMA = "s3a-bury-duel-aggregate-v1"
PREFLIGHT_SCHEMA = "s3a-bury-duel-preflight-v1"
SHARD_COUNT = 8
STREAM_STRIDE = 2_000_003
NULL_SHIFT = 999_983
STRUCTURED_MAX_CANDIDATES = 32
POLICY_ROLE_OFFSETS = (0, 500_000)
OPPONENT_ROLE_OFFSETS = (1_000_000, 1_500_000)
PREFLIGHT_SEED0 = 18_000_000_000
PREFLIGHT_CLUSTERS = 4
PREFLIGHT_RUN_ID = "s3a-bury-duel-preflight-18b-v1"
THROUGHPUT_SAFETY_FACTOR = 2.0
# The outcome-free S3a throughput probes consumed these deal seeds before this
# protocol existed.  Their outcomes were never published or used for
# selection, but a population advertised as fresh must still exclude them.
CONSUMED_SIZING_DEAL_SEEDS = tuple(range(151_000_000, 151_000_004))
PHASES = {
    "screen": {
        "run_id": "s3a-bury-duel-screen-153m-v1",
        "seed0": 153_000_003,
        "clusters": 2_048,
        "clusters_per_shard": 256,
        "claim": "non_promotable_s3a_complete_round_screen",
    },
    "confirm": {
        "run_id": "s3a-bury-duel-confirm-20b-v1",
        "seed0": 20_000_000_000,
        "clusters": 8_192,
        "clusters_per_shard": 1_024,
        "claim": "independent_s3a_complete_round_confirmation",
    },
}
CHAMPION = "mc-s0-report-lcb"
OPPONENT = CHAMPION
LABELS = {
    "structured": "mc-s0-report-lcb-structured-bury",
    "champion": CHAMPION,
    "null": "mc-s0-report-lcb-null",
}
LABEL_ORDER = tuple(LABELS)
REFUSED_ENV_KEYS = (
    "SHENGJI_WEIGHTED_SPLITS",
    "SHENGJI_UNIFORM_DEAL",
    "SHENGJI_PHYSICAL_FILLS",
    "SHENGJI_ALLOW_BALLOT_MISMATCH",
)
SELECTION_RULE = (
    "Over the complete registered mirrored population, continue only when "
    "LCB95(structured-champion)>0 and LCB95(structured-null)>0; the two-sided "
    "95% interval for null-champion contains zero; structured bury has at "
    "least one trigger and override; every triggered bury consumes exact "
    "registered work; all control structured-bury counters are zero; and no "
    "short, zero-world, void-fallback, or exact-endgame counter is nonzero. "
    "A screen PASS authorizes confirmation packet review only. A confirmation "
    "PASS records strength but never deploys automatically."
)
CLAIM_BOUNDARY = (
    "Fresh one-round paired utility for structured bury against exact live "
    "report-LCB; not a state-screen reinterpretation, multi-round progression, "
    "automatic promotion, or production mutation."
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


class ProtocolRefused(RuntimeError):
    """The requested artifact cannot support the registered claim."""


def sha256(path: os.PathLike | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def stable_digest(value) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), default=list,
    ).encode()).hexdigest()


def is_sha256(value) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(char in "0123456789abcdef" for char in value))


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, check=True,
        capture_output=True, text=True,
    ).stdout.strip()


def write_exclusive(path: os.PathLike | str, payload: dict) -> None:
    path = Path(path)
    partial = Path(str(path) + ".partial")
    if path.exists() or partial.exists():
        raise ProtocolRefused(f"refusing to overwrite {path} or {partial}")
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(payload, sort_keys=True, separators=(",", ":"))
           + "\n").encode()
    try:
        with partial.open("xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        if json.loads(partial.read_bytes()) != payload:
            raise ProtocolRefused("published partial failed exact reopen")
        os.link(partial, path)
        partial.unlink()
        if path.read_bytes() != raw:
            raise ProtocolRefused("published final differs from candidate")
    except BaseException:
        # Preserve a partial as evidence of an interrupted or refused write.
        raise


def source_paths() -> dict[str, Path]:
    return {
        "runner": SCRIPT,
        "live_parent": SERVER / "scripts" / "live_champion_parent.py",
        "evaluation": SERVER / "shengji" / "evaluation.py",
        "registry": SERVER / "shengji" / "ai" / "registry.py",
        "mcbot": SERVER / "shengji" / "ai" / "mcbot.py",
        "bury": SERVER / "shengji" / "ai" / "bury.py",
        "env": SERVER / "shengji" / "ai" / "env.py",
        "game": SERVER / "shengji" / "engine" / "game.py",
    }


def source_sha256s() -> dict[str, str]:
    return {name: sha256(path) for name, path in source_paths().items()}


def uppercase_contract(bot) -> dict:
    contract = {}
    for name in dir(bot):
        if not name.isupper():
            continue
        value = getattr(bot, name)
        if not isinstance(value, (bool, int, float, str, type(None))):
            raise ProtocolRefused(
                f"non-serializable policy contract {name}={value!r}")
        contract[name] = value
    return contract


def policy_contract(name: str) -> dict:
    bot = make_bot(name, seed=7)
    return {
        "policy": name,
        "class": type(bot).__name__,
        "uppercase": uppercase_contract(bot),
        "rollout_policy_class": type(bot.rollout_policy).__name__,
        "ballot": arm_ballots([name])[name],
    }


def phase_identity(phase: str) -> dict:
    if phase not in PHASES:
        raise ProtocolRefused(f"unknown S3a duel phase {phase!r}")
    spec = PHASES[phase]
    return {
        "phase": phase,
        **spec,
        "shard_count": SHARD_COUNT,
        "stream_stride": STREAM_STRIDE,
        "null_shift": NULL_SHIFT,
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


def _stream_uses(phase: str) -> list[tuple[int, int, str]]:
    uses = []
    spec = PHASES[phase]
    for cluster_index in range(spec["clusters"]):
        seed = cluster_seed(phase, cluster_index)
        for role_index, offset in enumerate(POLICY_ROLE_OFFSETS):
            # Structured and champion deliberately share their policy streams.
            uses.append((seed + offset, cluster_index,
                         f"matched-policy-{role_index}"))
            uses.append((seed + NULL_SHIFT + offset, cluster_index,
                         f"null-policy-{role_index}"))
        for role_index, offset in enumerate(OPPONENT_ROLE_OFFSETS):
            # All three arms deliberately share opponent streams.
            uses.append((seed + offset, cluster_index,
                         f"matched-opponent-{role_index}"))
    return uses


def stream_problems(phase: str) -> list[str]:
    by_seed: dict[int, list[tuple[int, str]]] = {}
    for seed, cluster_index, role in _stream_uses(phase):
        by_seed.setdefault(seed, []).append((cluster_index, role))
    problems = []
    for seed, uses in by_seed.items():
        if len(uses) != 1:
            problems.append(f"seed collision {seed}: {uses}")
    return problems


def stream_digest(phase: str) -> str:
    return stable_digest(_stream_uses(phase))


def _preflight_stream_uses() -> list[tuple[int, int, str]]:
    uses = []
    for cluster_index in range(PREFLIGHT_CLUSTERS):
        seed = PREFLIGHT_SEED0 + STREAM_STRIDE * cluster_index
        for role_index, offset in enumerate(POLICY_ROLE_OFFSETS):
            uses.append((seed + offset, cluster_index,
                         f"matched-policy-{role_index}"))
            uses.append((seed + NULL_SHIFT + offset, cluster_index,
                         f"null-policy-{role_index}"))
        for role_index, offset in enumerate(OPPONENT_ROLE_OFFSETS):
            uses.append((seed + offset, cluster_index,
                         f"matched-opponent-{role_index}"))
    return uses


def preflight_stream_problems() -> list[str]:
    uses = _preflight_stream_uses()
    seeds = [seed for seed, _, _ in uses]
    return [] if len(seeds) == len(set(seeds)) else [
        "score-free preflight stream population collides"]


def global_stream_problems() -> list[str]:
    """Refuse reuse with sizing or across all registered duel populations."""
    populations = {
        "consumed-sizing": [
            (seed, index, "consumed-sizing-deal")
            for index, seed in enumerate(CONSUMED_SIZING_DEAL_SEEDS)
        ],
        "preflight": _preflight_stream_uses(),
        **{phase: _stream_uses(phase) for phase in PHASES},
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
        problems.append("S3a duel parent is not exact live report-LCB")
    if SHARD_COUNT != 8 or STREAM_STRIDE != 2_000_003:
        problems.append("registered shard/stream geometry drifted")
    if LABELS != {
            "structured": "mc-s0-report-lcb-structured-bury",
            "champion": "mc-s0-report-lcb",
            "null": "mc-s0-report-lcb-null"}:
        problems.append("registered S3a duel labels drifted")
    if global_stream_problems():
        problems.append("registered global stream population collides")
    try:
        bots = {label: make_bot(name, seed=7)
                for label, name in LABELS.items()}
        contracts = {label: uppercase_contract(bot)
                     for label, bot in bots.items()}
    except Exception as exc:
        problems.append(f"policy construction failed: {type(exc).__name__}: {exc}")
        return sorted(set(problems))
    base = contracts["champion"]
    treatment = dict(contracts["structured"])
    treatment["MC_BURY"] = False
    treatment["STRUCTURED_BURY"] = False
    if treatment != base:
        problems.append("structured arm differs beyond MC/STRUCTURED_BURY")
    if (contracts["structured"].get("MC_BURY") is not True
            or contracts["structured"].get("STRUCTURED_BURY") is not True):
        problems.append("structured arm did not enable exact S3a switches")
    if contracts["structured"].get("BURY_MAX_CANDIDATES") != \
            STRUCTURED_MAX_CANDIDATES:
        problems.append("structured candidate cap drifted")
    if getattr(bots["structured"], "structured_bury_base_policy", None) != CHAMPION:
        problems.append("structured arm names the wrong champion base")
    if contracts["null"] != base:
        problems.append("champion-matched null contract differs from champion")
    if bots["null"].seed != bots["champion"].seed + NULL_SHIFT:
        problems.append("champion-matched null shift drifted")
    if bots["structured"].rng.getstate() != bots["champion"].rng.getstate():
        problems.append("structured arm changed the champion RNG stream")
    for label in ("champion", "null"):
        if any(getattr(bots[label], field, False) for field in
               ("MC_BURY", "STRUCTURED_BURY", "EXACT_ENDGAME")):
            problems.append(f"{label} enables an out-of-scope S3 feature")
    if getattr(bots["structured"], "EXACT_ENDGAME", False):
        problems.append("structured arm enables sampled exact endgame")
    if len({type(bot.rollout_policy) for bot in bots.values()}) != 1:
        problems.append("S3a duel rollout policy classes differ")
    try:
        ballots = arm_ballots(LABELS.values())
        if len(set(ballots.values())) != 1:
            problems.append(f"S3a duel lead/follow ballots differ: {ballots}")
    except Exception as exc:
        problems.append(f"ballot preflight failed: {type(exc).__name__}: {exc}")
    return sorted(set(problems))


def require_runtime(expected_git: str) -> tuple[object, dict, dict]:
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
        raise ProtocolRefused("exact runner git predeclaration")
    if git("status", "--porcelain"):
        raise ProtocolRefused("S3a duel refuses a dirty tree")
    try:
        parent = LIVE_PARENT.require_live_champion_parent()
    except LIVE_PARENT.ProtocolRefused as exc:
        raise ProtocolRefused(f"live champion parent refused: {exc}") from exc
    problems = protocol_problems(parent)
    if problems:
        raise ProtocolRefused("S3a duel protocol drift: " + "; ".join(problems))
    runtime = {
        "git": head,
        "tree_dirty": False,
        "host": os.uname().nodename,
        "python": platform.python_version(),
        "fast_engine": True,
        "require_voids": True,
        "experimental_flags": [],
        "source_sha256s": source_sha256s(),
        "fast_binary_sha256": sha256(fast._fast.__file__),
        "policy_contract_sha256s": {
            name: stable_digest(policy_contract(name))
            for name in sorted(set(LABELS.values()))
        },
        "stream_digests": {
            "preflight": stable_digest(_preflight_stream_uses()),
            **{phase: stream_digest(phase) for phase in PHASES},
        },
    }
    return fast, parent, runtime


def structured_telemetry(bots) -> dict:
    payloads = [bot.structured_bury_telemetry() for bot in bots]
    totals = {name: sum(int(payload[name]) for payload in payloads)
              for name in STRUCTURED_BURY_TELEMETRY_FIELDS}
    return {
        "schema": "structured-bury-cumulative-telemetry-v1",
        **totals,
        "exact_work_complete": all(
            payload["exact_work_complete"] is True for payload in payloads),
    }


def _record(run_id: str, label: str, policy: str, seed: int, flip: int, won: int,
            level_utility: int, arm_bots, opp_bots) -> dict:
    return {
        "run": run_id,
        "label": label,
        "policy": policy,
        "opponent": OPPONENT,
        "seed": seed,
        "flip": flip,
        "won": won,
        "level_utility": level_utility,
        "arm": {
            **counters(arm_bots),
            "structured_bury": structured_telemetry(arm_bots),
        },
        "opp": {
            **counters(opp_bots),
            "structured_bury": structured_telemetry(opp_bots),
        },
    }


def play_arm_cluster(label: str, seed: int, *, run_id: str) -> list[dict]:
    policy = LABELS[label]
    records = []
    for flip in (0, 1):
        a1 = make_bot(policy, seed=seed)
        a2 = make_bot(policy, seed=seed + 500_000)
        b1 = make_bot(OPPONENT, seed=seed + 1_000_000)
        b2 = make_bot(OPPONENT, seed=seed + 1_500_000)
        policies = ([a1, b1, a2, b2] if flip == 0
                    else [b1, a1, b2, a2])
        log = play_round(Game(random.Random(seed)), policies)
        winner_team = 0 if flip == 0 else 1
        won = int(log.winner_team == winner_team)
        utility = (1 if won else -1) * max(1, int(log.level_change))
        records.append(_record(
            run_id, label, policy, seed, flip, won, utility,
            [a1, a2], [b1, b2]))
    return records


def counter_problems(value: object, *, allow_structured: bool) -> list[str]:
    if not isinstance(value, dict):
        return ["counter payload is not an object"]
    problems = []
    telemetry = value.get("structured_bury")
    expected_counter_fields = set(counters([])) | {"structured_bury"}
    if set(value) != expected_counter_fields:
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
    if (not isinstance(telemetry, dict)
            or telemetry.get("schema") !=
            "structured-bury-cumulative-telemetry-v1"
            or set(telemetry) !=
            {"schema", *STRUCTURED_BURY_TELEMETRY_FIELDS,
             "exact_work_complete"}):
        problems.append("structured-bury telemetry schema")
    else:
        for name in STRUCTURED_BURY_TELEMETRY_FIELDS:
            item = telemetry.get(name)
            if isinstance(item, bool) or not isinstance(item, int) or item < 0:
                problems.append(f"structured-bury telemetry {name}")
        if telemetry.get("exact_work_complete") is not True:
            problems.append("structured-bury work is incomplete")
        fields_valid = all(
            isinstance(telemetry.get(name), int)
            and not isinstance(telemetry.get(name), bool)
            and telemetry[name] >= 0
            for name in STRUCTURED_BURY_TELEMETRY_FIELDS)
        if fields_valid:
            if telemetry["triggers"] != telemetry["searches"]:
                problems.append("structured triggers/searches mismatch")
            if telemetry["searches"] != (
                    telemetry["complete_searches"] +
                    telemetry["short_searches"]):
                problems.append("structured search completion mismatch")
            if telemetry["triggers"] > telemetry["opportunities"]:
                problems.append("structured triggers exceed opportunities")
            if not (telemetry["opportunities"] <=
                    telemetry["candidate_count_sum"] <=
                    telemetry["opportunities"] * STRUCTURED_MAX_CANDIDATES):
                problems.append("structured candidate-count accounting")
            if telemetry["overrides"] > telemetry["complete_searches"]:
                problems.append("structured overrides exceed completions")
            if telemetry["zero_world_searches"] > telemetry["short_searches"]:
                problems.append("structured zero-world accounting")
            if telemetry["worlds_used"] > telemetry["worlds_requested"]:
                problems.append("structured worlds exceed request")
            if telemetry["candidate_rollouts"] > \
                    telemetry["candidate_world_budget"]:
                problems.append("structured rollouts exceed budget")
            if telemetry["sample_attempts"] != (
                    telemetry["accepted_worlds"] + telemetry["failed_worlds"]):
                problems.append("structured sampler accounting")
            if telemetry["accepted_worlds"] != telemetry["worlds_used"]:
                problems.append("structured accepted/scored world mismatch")
            if telemetry["rejected_worlds"] > telemetry["failed_worlds"]:
                problems.append("structured rejected/failed mismatch")
            exact = (telemetry["short_searches"] == 0
                     and telemetry["candidate_rollouts"] ==
                     telemetry["candidate_world_budget"])
            if telemetry["exact_work_complete"] is not exact:
                problems.append("structured exact-work flag mismatch")
        if not allow_structured and any(
                telemetry.get(name) != 0
                for name in STRUCTURED_BURY_TELEMETRY_FIELDS):
            problems.append("control structured-bury telemetry is nonzero")
        if allow_structured and (
                telemetry.get("short_searches") != 0
                or telemetry.get("zero_world_searches") != 0):
            problems.append("treatment structured-bury fallback")
    return sorted(set(problems))


def record_problems(record: object, *, phase: str,
                    expected_seed: int, expected_label: str,
                    expected_flip: int,
                    expected_run_id: str | None = None) -> list[str]:
    if not isinstance(record, dict):
        return ["record is not an object"]
    expected_fields = {
        "run", "label", "policy", "opponent", "seed", "flip", "won",
        "level_utility", "arm", "opp",
    }
    problems = []
    if set(record) != expected_fields:
        problems.append("record field population")
    run_id = expected_run_id or PHASES[phase]["run_id"]
    if (record.get("run") != run_id
            or record.get("label") != expected_label
            or record.get("policy") != LABELS[expected_label]
            or record.get("opponent") != OPPONENT
            or record.get("seed") != expected_seed
            or record.get("flip") != expected_flip):
        problems.append("record identity")
    won = record.get("won")
    utility = record.get("level_utility")
    if won not in (0, 1):
        problems.append("record won value")
    if (isinstance(utility, bool) or not isinstance(utility, int)
            or utility == 0 or (utility > 0) != (won == 1)):
        problems.append("record signed level utility")
    problems += [f"arm: {problem}" for problem in counter_problems(
        record.get("arm"), allow_structured=expected_label == "structured")]
    problems += [f"opp: {problem}" for problem in counter_problems(
        record.get("opp"), allow_structured=False)]
    return sorted(set(problems))


def shard_problems(payload: object, *, phase: str,
                   shard_index: int, parent: dict,
                   runtime: dict) -> list[str]:
    if not isinstance(payload, dict):
        return ["shard root is not an object"]
    spec = PHASES[phase]
    expected_identity = phase_identity(phase)
    problems = []
    expected_fields = {
        "schema", "complete", "phase", "phase_identity", "shard_index",
        "run_id", "shard_count", "parent", "runtime", "elapsed_seconds", "records",
        "records_sha256", "production_promotion",
        "retry_or_resume_authorized",
    }
    if set(payload) != expected_fields:
        problems.append("shard field population")
    if (payload.get("schema") != SCHEMA
            or payload.get("complete") is not True
            or payload.get("phase") != phase
            or payload.get("run_id") != spec["run_id"]
            or payload.get("phase_identity") != expected_identity
            or payload.get("shard_index") != shard_index
            or payload.get("shard_count") != SHARD_COUNT
            or payload.get("parent") != parent
            or payload.get("runtime") != runtime
            or payload.get("production_promotion") is not False
            or payload.get("retry_or_resume_authorized") is not False):
        problems.append("shard identity/provenance")
    elapsed = payload.get("elapsed_seconds")
    if (isinstance(elapsed, bool) or not isinstance(elapsed, (int, float))
            or not math.isfinite(elapsed) or elapsed < 0):
        problems.append("shard elapsed time")
    records = payload.get("records")
    expected_records = spec["clusters_per_shard"] * len(LABEL_ORDER) * 2
    if not isinstance(records, list) or len(records) != expected_records:
        problems.append("shard record count")
        return sorted(set(problems))
    cursor = 0
    for local_index in range(spec["clusters_per_shard"]):
        cluster_index = shard_index + SHARD_COUNT * local_index
        seed = cluster_seed(phase, cluster_index)
        for label in LABEL_ORDER:
            for flip in (0, 1):
                problems += [
                    f"record {cursor}: {problem}" for problem in
                    record_problems(
                        records[cursor], phase=phase,
                        expected_seed=seed, expected_label=label,
                        expected_flip=flip)]
                cursor += 1
    if payload.get("records_sha256") != stable_digest(records):
        problems.append("shard record digest")
    return sorted(set(problems))


def run_shard(args) -> None:
    _, parent, runtime = require_runtime(args.expected_git)
    phase = args.phase
    spec = PHASES[phase]
    if not 0 <= args.shard_index < SHARD_COUNT:
        raise ProtocolRefused("invalid shard index")
    records = []
    started = time.perf_counter()
    for local_index in range(spec["clusters_per_shard"]):
        cluster_index = args.shard_index + SHARD_COUNT * local_index
        seed = cluster_seed(phase, cluster_index)
        for label in LABEL_ORDER:
            records.extend(play_arm_cluster(
                label, seed, run_id=spec["run_id"]))
        if args.progress_every and (local_index + 1) % args.progress_every == 0:
            print(json.dumps({
                "event": "s3a-bury-duel-progress-v1",
                "phase": phase,
                "shard_index": args.shard_index,
                "clusters_complete": local_index + 1,
                "clusters_total": spec["clusters_per_shard"],
            }, sort_keys=True), flush=True)
    payload = {
        "schema": SCHEMA,
        "complete": True,
        "phase": phase,
        "run_id": spec["run_id"],
        "phase_identity": phase_identity(phase),
        "shard_index": args.shard_index,
        "shard_count": SHARD_COUNT,
        "parent": parent,
        "runtime": runtime,
        "elapsed_seconds": time.perf_counter() - started,
        "records": records,
        "records_sha256": stable_digest(records),
        "production_promotion": False,
        "retry_or_resume_authorized": False,
    }
    problems = shard_problems(
        payload, phase=phase, shard_index=args.shard_index,
        parent=parent, runtime=runtime)
    if problems:
        raise ProtocolRefused("shard candidate: " + "; ".join(problems))
    write_exclusive(args.out, payload)
    print(json.dumps({
        "schema": SCHEMA,
        "phase": phase,
        "shard_index": args.shard_index,
        "records": len(records),
        "records_sha256": payload["records_sha256"],
    }, sort_keys=True), flush=True)


def _sum_structured(records: list[dict], side: str) -> dict:
    totals = Counter({name: 0 for name in STRUCTURED_BURY_TELEMETRY_FIELDS})
    exact = True
    for record in records:
        payload = record[side]["structured_bury"]
        totals.update({name: payload[name]
                       for name in STRUCTURED_BURY_TELEMETRY_FIELDS})
        exact = exact and payload["exact_work_complete"] is True
    return {**dict(totals), "exact_work_complete": exact}


def contrast(records: dict[str, list[dict]], a: str, b: str) -> dict:
    mean, half, clusters = paired_by_seed(records[a], records[b])
    return {
        "a": a,
        "b": b,
        "mean": mean,
        "half_width_95": half,
        "lcb_95": mean - half,
        "ucb_95": mean + half,
        "clusters": clusters,
        "unit": "mirrored complete-round deal cluster",
    }


def build_aggregate(*, phase: str, shards: list[dict], inputs: list[dict],
                    parent: dict, runtime: dict,
                    screen_parent: dict | None) -> dict:
    records = {label: [] for label in LABEL_ORDER}
    for shard in shards:
        for record in shard["records"]:
            records[record["label"]].append(record)
    stats = {
        "structured-champion": contrast(records, "structured", "champion"),
        "structured-null": contrast(records, "structured", "null"),
        "null-champion": contrast(records, "null", "champion"),
    }
    telemetry = {
        label: {
            "arm": _sum_structured(records[label], "arm"),
            "opp": _sum_structured(records[label], "opp"),
        } for label in LABEL_ORDER
    }
    treatment = telemetry["structured"]["arm"]
    controls_zero = all(
        telemetry[label][side][name] == 0
        for label in LABEL_ORDER for side in ("arm", "opp")
        if not (label == "structured" and side == "arm")
        for name in STRUCTURED_BURY_TELEMETRY_FIELDS)
    null_stat = stats["null-champion"]
    criteria = {
        "structured_champion_lcb_gt_zero": (
            stats["structured-champion"]["lcb_95"] > 0),
        "structured_null_lcb_gt_zero": (
            stats["structured-null"]["lcb_95"] > 0),
        "null_champion_interval_contains_zero": (
            null_stat["lcb_95"] <= 0 <= null_stat["ucb_95"]),
        "structured_triggered": treatment["triggers"] > 0,
        "structured_overrode": treatment["overrides"] > 0,
        "structured_exact_work": (
            treatment["exact_work_complete"] is True
            and treatment["short_searches"] == 0
            and treatment["zero_world_searches"] == 0
            and treatment["candidate_rollouts"] ==
            treatment["candidate_world_budget"]),
        "controls_structured_feature_off": controls_zero,
    }
    criteria["all"] = all(criteria.values())
    status = (
        "AUTHORIZE_CONFIRM_PACKET_REVIEW" if phase == "screen" and criteria["all"]
        else "CONFIRM_S3A_STRENGTH" if phase == "confirm" and criteria["all"]
        else "SELECT_NONE"
    )
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
        "structured_bury_telemetry": telemetry,
        "criteria": criteria,
        "status": status,
        "production_promotion": False,
        "retry_or_extension_authorized": False,
        "explicit_deployment_review_required": True,
    }


def load_shards(args, *, parent: dict, runtime: dict) -> tuple[list[dict], list[dict]]:
    if len(args.input) != SHARD_COUNT or \
            len(args.expected_input_sha256) != SHARD_COUNT:
        raise ProtocolRefused("aggregate requires exactly eight paths and hashes")
    shards, items, problems = [], [], []
    for index, (raw_path, expected) in enumerate(zip(
            args.input, args.expected_input_sha256)):
        path = Path(raw_path)
        if not path.is_file() or not is_sha256(expected):
            problems.append(f"shard {index} path/hash")
            continue
        actual = sha256(path)
        if actual != expected:
            problems.append(f"shard {index} SHA-256")
            continue
        try:
            payload = json.loads(path.read_bytes())
        except (OSError, ValueError) as exc:
            problems.append(f"shard {index} unreadable: {exc}")
            continue
        problems += [f"shard {index}: {problem}" for problem in shard_problems(
            payload, phase=args.phase, shard_index=index,
            parent=parent, runtime=runtime)]
        shards.append(payload)
        items.append({"path": str(path), "sha256": actual, "shard_index": index})
    if len({item["path"] for item in items}) != len(items):
        problems.append("aggregate shard paths are not unique")
    if len({item["sha256"] for item in items}) != len(items):
        problems.append("aggregate shard hashes are not unique")
    if problems:
        raise ProtocolRefused("aggregate inputs: " + "; ".join(sorted(set(problems))))
    return shards, items


def load_screen_parent(path: str | None, expected: str | None, *,
                       parent: dict, runtime: dict) -> dict | None:
    if path is None and expected is None:
        return None
    if path is None or expected is None or not is_sha256(expected):
        raise ProtocolRefused("screen parent requires exact path and SHA-256")
    source = Path(path)
    if not source.is_file() or sha256(source) != expected:
        raise ProtocolRefused("screen parent unavailable or drifted")
    payload = json.loads(source.read_bytes())
    expected_fields = {
        "schema", "complete", "phase", "phase_identity", "parent",
        "runtime", "screen_parent", "inputs", "stats",
        "structured_bury_telemetry", "criteria", "status",
        "production_promotion", "retry_or_extension_authorized",
        "explicit_deployment_review_required",
    }
    expected_criteria = {
        "structured_champion_lcb_gt_zero",
        "structured_null_lcb_gt_zero",
        "null_champion_interval_contains_zero",
        "structured_triggered", "structured_overrode",
        "structured_exact_work", "controls_structured_feature_off", "all",
    }
    if (set(payload) != expected_fields
            or payload.get("schema") != AGGREGATE_SCHEMA
            or payload.get("phase") != "screen"
            or payload.get("complete") is not True
            or payload.get("status") != "AUTHORIZE_CONFIRM_PACKET_REVIEW"
            or payload.get("phase_identity") != phase_identity("screen")
            or payload.get("parent") != parent
            or payload.get("screen_parent") is not None
            or set(payload.get("criteria", {})) != expected_criteria
            or payload.get("criteria", {}).get("all") is not True
            or not all(payload.get("criteria", {}).values())
            or payload.get("production_promotion") is not False
            or payload.get("retry_or_extension_authorized") is not False
            or payload.get("explicit_deployment_review_required") is not True):
        raise ProtocolRefused("screen parent did not authorize confirmation review")
    prior_runtime = payload.get("runtime")
    runtime_fields = (
        "git", "tree_dirty", "python", "fast_engine", "require_voids",
        "experimental_flags", "source_sha256s", "fast_binary_sha256",
        "policy_contract_sha256s", "stream_digests",
    )
    if (not isinstance(prior_runtime, dict)
            or any(prior_runtime.get(name) != runtime.get(name)
                   for name in runtime_fields)):
        raise ProtocolRefused("screen parent runtime/source contract drifted")
    return {"path": str(source), "sha256": expected, "status": payload["status"]}


def aggregate(args) -> None:
    _, parent, runtime = require_runtime(args.expected_git)
    screen_parent = load_screen_parent(
        args.screen_aggregate, args.expected_screen_aggregate_sha256,
        parent=parent, runtime=runtime)
    if args.phase == "screen" and screen_parent is not None:
        raise ProtocolRefused("screen phase cannot consume a screen parent")
    if args.phase == "confirm" and screen_parent is None:
        raise ProtocolRefused("confirmation requires an exact passing screen parent")
    shards, items = load_shards(args, parent=parent, runtime=runtime)
    payload = build_aggregate(
        phase=args.phase, shards=shards, inputs=items,
        parent=parent, runtime=runtime, screen_parent=screen_parent)
    write_exclusive(args.out, payload)
    print(json.dumps({
        "schema": AGGREGATE_SCHEMA,
        "phase": args.phase,
        "status": payload["status"],
        "criteria": payload["criteria"],
        "production_promotion": False,
    }, sort_keys=True), flush=True)


def preflight(args) -> None:
    _, parent, runtime = require_runtime(args.expected_git)
    started = time.perf_counter()
    totals = {label: Counter() for label in LABEL_ORDER}
    telemetry = {label: Counter({name: 0 for name in
                                 STRUCTURED_BURY_TELEMETRY_FIELDS})
                 for label in LABEL_ORDER}
    problems = []
    for cluster_index in range(PREFLIGHT_CLUSTERS):
        seed = PREFLIGHT_SEED0 + STREAM_STRIDE * cluster_index
        for label in LABEL_ORDER:
            records = play_arm_cluster(
                label, seed, run_id=PREFLIGHT_RUN_ID)
            for flip, record in enumerate(records):
                problems += [
                    f"{label}/cluster{cluster_index}/flip{flip}: {problem}"
                    for problem in record_problems(
                        record,
                        phase="screen", expected_seed=seed,
                        expected_label=label, expected_flip=flip,
                        expected_run_id=PREFLIGHT_RUN_ID)]
                # Deliberately retain no won/utility/record digest.
                totals[label].update({
                    name: record["arm"][name]
                    for name in counters([]) if name != "search_secs"})
                telemetry[label].update({
                    name: record["arm"]["structured_bury"][name]
                    for name in STRUCTURED_BURY_TELEMETRY_FIELDS})
    elapsed = time.perf_counter() - started
    seconds_per_cluster = elapsed / PREFLIGHT_CLUSTERS
    projections = {
        phase: {
            "fleet_hours": (seconds_per_cluster * spec["clusters"] *
                            THROUGHPUT_SAFETY_FACTOR / 3_600),
            "max_shard_hours": (
                seconds_per_cluster * spec["clusters_per_shard"] *
                THROUGHPUT_SAFETY_FACTOR / 3_600),
        } for phase, spec in PHASES.items()
    }
    treatment = telemetry["structured"]
    if treatment["triggers"] <= 0:
        problems.append("score-free preflight did not exercise structured bury")
    if (treatment["short_searches"] != 0
            or treatment["zero_world_searches"] != 0
            or treatment["candidate_rollouts"] !=
            treatment["candidate_world_budget"]):
        problems.append("score-free preflight structured work incomplete")
    budgets = {
        "screen_fleet_hours": args.screen_fleet_hours,
        "screen_max_shard_hours": args.screen_max_shard_hours,
        "confirm_fleet_hours": args.confirm_fleet_hours,
        "confirm_max_shard_hours": args.confirm_max_shard_hours,
    }
    for name, value in budgets.items():
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or value <= 0):
            problems.append(f"invalid capacity budget {name}")
    problems = sorted(set(problems))
    payload = {
        "schema": PREFLIGHT_SCHEMA,
        "complete": True,
        "score_free": True,
        "clusters": PREFLIGHT_CLUSTERS,
        "run_id": PREFLIGHT_RUN_ID,
        "seed0": PREFLIGHT_SEED0,
        "stream_stride": STREAM_STRIDE,
        "parent": parent,
        "runtime": runtime,
        "elapsed_seconds": elapsed,
        "seconds_per_cluster": seconds_per_cluster,
        "integer_counters": {label: dict(value)
                             for label, value in totals.items()},
        "structured_bury_telemetry": {label: dict(value)
                                      for label, value in telemetry.items()},
        "projections": projections,
        "throughput_safety_factor": THROUGHPUT_SAFETY_FACTOR,
        "problems": problems,
        "budgets": budgets,
        "capacity_pass": (
            not problems
            and projections["screen"]["fleet_hours"] <= args.screen_fleet_hours
            and projections["screen"]["max_shard_hours"] <=
            args.screen_max_shard_hours
            and projections["confirm"]["fleet_hours"] <=
            args.confirm_fleet_hours
            and projections["confirm"]["max_shard_hours"] <=
            args.confirm_max_shard_hours),
        "strength_launch_authorized": False,
        "production_promotion": False,
    }
    write_exclusive(args.out, payload)
    print(json.dumps({
        "schema": PREFLIGHT_SCHEMA,
        "capacity_pass": payload["capacity_pass"],
        "score_free": True,
        "strength_launch_authorized": False,
    }, sort_keys=True), flush=True)


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="mode", required=True)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--expected-git", required=True)

    pf = sub.add_parser("preflight", parents=[common])
    pf.add_argument("--screen-fleet-hours", type=float, required=True)
    pf.add_argument("--screen-max-shard-hours", type=float, required=True)
    pf.add_argument("--confirm-fleet-hours", type=float, required=True)
    pf.add_argument("--confirm-max-shard-hours", type=float, required=True)
    pf.add_argument("--out", required=True)

    run = sub.add_parser("run", parents=[common])
    run.add_argument("--phase", choices=tuple(PHASES), required=True)
    run.add_argument("--shard-index", type=int, required=True)
    run.add_argument("--progress-every", type=int, default=1)
    run.add_argument("--out", required=True)

    agg = sub.add_parser("aggregate", parents=[common])
    agg.add_argument("--phase", choices=tuple(PHASES), required=True)
    agg.add_argument("--input", action="append", default=[])
    agg.add_argument("--expected-input-sha256", action="append", default=[])
    agg.add_argument("--screen-aggregate")
    agg.add_argument("--expected-screen-aggregate-sha256")
    agg.add_argument("--out", required=True)
    return ap


def main() -> None:
    args = parser().parse_args()
    try:
        if args.mode == "preflight":
            preflight(args)
        elif args.mode == "run":
            run_shard(args)
        else:
            aggregate(args)
    except (ProtocolRefused, OSError, ValueError) as exc:
        print(f"REFUSING: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(3)


if __name__ == "__main__":
    main()
