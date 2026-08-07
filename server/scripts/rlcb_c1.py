#!/usr/bin/env python3
"""Fresh formal confirmation of the manually shipped report-LCB policy.

RLCB-C1 is not an S0 continuation.  It never reads the burned 135M S0c
population.  Eight shards cover exactly 2,048 new mirrored deal clusters and
exactly three policies: live ``mc-s0-report-lcb``, current ``mc-strong``, and a
new current-policy null whose RNG shift is proved disjoint from every matched
policy/opponent stream in this block.

There is one strength question: is the paired 95% lower bound for report-LCB
minus current above zero?  The null-current interval is a calibration check,
not a second superiority hurdle.  No command changes production.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Callable, Sequence


SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[1]
REPO = SERVER.parent
LOGS = SERVER / "runs" / "logs"
sys.path.insert(0, str(SERVER))

from shengji.ai.registry import S0_REPORT_WORLDS, make_bot  # noqa: E402
from shengji.evaluation import arm_ballots, paired_by_seed, run_arm  # noqa: E402


SCHEMA = "rlcb-c1-shard-v1"
AGGREGATE_SCHEMA = "rlcb-c1-aggregate-v1"
FREEZE_SCHEMA = "rlcb-c1-freeze-v1"
CLAIM = "fresh_report_lcb_superiority_over_current_mc"
RUN_NAMESPACE = "rlcb-c1-150m-v1"
SHARD_COUNT = 8
CLUSTERS_PER_SHARD = 256
TOTAL_CLUSTERS = SHARD_COUNT * CLUSTERS_PER_SHARD
SEED0 = 150_000_000
SEED_HI = SEED0 + TOTAL_CLUSTERS - 1
OPPONENT = "mc-strong"
NULL_OFFSET = 60_000_011
LABELS = {
    "report_lcb": "mc-s0-report-lcb",
    "current": "mc-strong",
    "current_null": "mc-strong-null-rlcb-c1",
}
SELECTION_RULE = (
    "CONFIRM report-LCB only if all 2,048 fresh mirrored clusters and exact "
    "registered search doses verify, the current-null minus current paired "
    "two-sided 95% interval contains zero, and the single superiority gate "
    "LCB95(report_lcb-current)>0. The null check is calibration, not a second "
    "superiority contrast. No retry, extension, seed substitution, S0c read, "
    "automatic deployment, or production mutation is authorized."
)
CLAIM_BOUNDARY = (
    "Fresh one-round paired formal confirmation of the already-manually-"
    "shipped report-LCB policy only; not adaptive-allocation evidence, an S0c "
    "repair, multi-round progression, or automatic deployment authority."
)
REFUSED_ENV_KEYS = (
    "SHENGJI_WEIGHTED_SPLITS",
    "SHENGJI_UNIFORM_DEAL",
    "SHENGJI_PHYSICAL_FILLS",
    "SHENGJI_ALLOW_BALLOT_MISMATCH",
)
FREEZE_RECEIPT = SCRIPT.with_name("rlcb_c1_freeze.v1.json")

COUNTER_FIELDS = (
    "rollouts", "searches", "search_secs", "void_fallbacks",
    "rejected_worlds", "sample_attempts", "accepted_worlds",
    "failed_worlds", "short_searches", "zero_world", "exact_endgames",
    "exact_endgame_attempts", "exact_endgame_refusals",
    "exact_endgame_budget_exceeded", "exact_endgame_sessions",
    "exact_endgame_nodes", "exact_endgame_cache_hits",
)
INTEGER_COUNTER_FIELDS = tuple(
    field for field in COUNTER_FIELDS if field != "search_secs"
)
FORBIDDEN_COUNTER_FIELDS = (
    "void_fallbacks", "rejected_worlds", "failed_worlds",
    "short_searches", "zero_world", "exact_endgames",
    "exact_endgame_attempts", "exact_endgame_refusals",
    "exact_endgame_budget_exceeded", "exact_endgame_sessions",
    "exact_endgame_nodes", "exact_endgame_cache_hits",
)


class ProtocolRefused(RuntimeError):
    """The requested operation cannot support the frozen RLCB-C1 claim."""


def sha256(path: os.PathLike | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as fh:
        while block := fh.read(1 << 20):
            digest.update(block)
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


def git_is_ancestor(ancestor: str, descendant: str) -> bool:
    return subprocess.run(
        ["git", "merge-base", "--is-ancestor", ancestor, descendant],
        cwd=REPO, capture_output=True, text=True,
    ).returncode == 0


def source_paths() -> dict[str, Path]:
    return {
        "runner": SCRIPT,
        "evaluation": SERVER / "shengji" / "evaluation.py",
        "registry": SERVER / "shengji" / "ai" / "registry.py",
        "mcbot": SERVER / "shengji" / "ai" / "mcbot.py",
        "smart": SERVER / "shengji" / "ai" / "smart.py",
        "memory": SERVER / "shengji" / "ai" / "memory.py",
        "env": SERVER / "shengji" / "ai" / "env.py",
        "ballot": SERVER / "shengji" / "engine" / "ballot.py",
        "round": SERVER / "shengji" / "engine" / "round.py",
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


def policy_contract_sha256s() -> dict[str, str]:
    return {
        name: stable_digest(policy_contract(name))
        for name in sorted(set(LABELS.values()))
    }


def selection_identity() -> dict:
    return {
        "schema": SCHEMA,
        "aggregate_schema": AGGREGATE_SCHEMA,
        "claim": CLAIM,
        "run_namespace": RUN_NAMESPACE,
        "shard_count": SHARD_COUNT,
        "clusters_per_shard": CLUSTERS_PER_SHARD,
        "total_clusters": TOTAL_CLUSTERS,
        "seed0": SEED0,
        "seed_hi": SEED_HI,
        "opponent": OPPONENT,
        "labels": LABELS,
        "null_offset": NULL_OFFSET,
        "selection_rule": SELECTION_RULE,
        "claim_boundary": CLAIM_BOUNDARY,
    }


def selection_digest() -> str:
    return stable_digest(selection_identity())


def _stream_entries(offset: int) -> tuple[dict[int, list[str]], dict[int, list[str]]]:
    """Return null-policy and prohibited stream uses over the whole block.

    Report-LCB and current deliberately share policy streams: that is matched
    common-random-number pairing.  Opponent streams are likewise deliberately
    matched across arms.  Only the null policy's shifted streams must be
    disjoint from all those roles and from one another.
    """
    null: dict[int, list[str]] = {}
    other: dict[int, list[str]] = {}

    def add(target: dict[int, list[str]], key: int, name: str) -> None:
        target.setdefault(key, []).append(name)

    for seed in range(SEED0, SEED_HI + 1):
        add(null, seed + offset, f"null:{seed}:team0")
        add(null, seed + 500_000 + offset, f"null:{seed}:team1")
        add(other, seed, f"matched-policy:{seed}:team0")
        add(other, seed + 500_000, f"matched-policy:{seed}:team1")
        add(other, seed + 1_000_000, f"opponent:{seed}:team0")
        add(other, seed + 1_500_000, f"opponent:{seed}:team1")
    return null, other


def stream_collision_problems(offset: int = NULL_OFFSET) -> list[str]:
    null, other = _stream_entries(offset)
    problems = []
    duplicate_null = {key: names for key, names in null.items()
                      if len(names) != 1}
    if duplicate_null:
        key = min(duplicate_null)
        problems.append(f"null stream self-collision {key}: {duplicate_null[key]}")
    overlap = sorted(set(null) & set(other))
    if overlap:
        key = overlap[0]
        problems.append(
            f"null stream collision {key}: {null[key]} vs {other[key]}")
    return problems


def stream_proof() -> dict:
    null, other = _stream_entries(NULL_OFFSET)
    problems = stream_collision_problems()
    return {
        "schema": "rlcb-c1-stream-proof-v1",
        "null_offset": NULL_OFFSET,
        "seed0": SEED0,
        "seed_hi": SEED_HI,
        "null_streams": sum(len(names) for names in null.values()),
        "distinct_null_streams": len(null),
        "prohibited_stream_keys": len(other),
        "collisions": len(problems),
        "problems": problems,
        "null_stream_digest": stable_digest(sorted(null)),
        "prohibited_stream_digest": stable_digest(sorted(other)),
    }


def load_freeze_receipt() -> dict:
    try:
        value = json.loads(FREEZE_RECEIPT.read_text())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolRefused(f"RLCB-C1 freeze receipt unreadable: {exc}") from exc
    expected = {
        "schema", "selection_identity", "selection_digest",
        "source_sha256s", "policy_contract_sha256s", "stream_proof",
        "python", "fast_binary_sha256", "execution_host", "execution_root",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise ProtocolRefused("RLCB-C1 freeze receipt field set drifted")
    if value.get("schema") != FREEZE_SCHEMA:
        raise ProtocolRefused("RLCB-C1 freeze receipt schema drifted")
    return value


def runtime_identity(fast) -> dict:
    return {
        "host": os.uname().nodename,
        "execution_root": str(SERVER.resolve()),
        "python": platform.python_version(),
        "fast_engine": True,
        "require_voids": True,
        "experimental_sampler_ballot_flags": [],
        "source_sha256s": source_sha256s(),
        "fast_router_sha256": sha256(fast.__file__),
        "fast_binary_sha256": sha256(fast._fast.__file__),
        "freeze_receipt_sha256": sha256(FREEZE_RECEIPT),
        "selection_digest": selection_digest(),
        "policy_contract_sha256s": policy_contract_sha256s(),
    }


def require_environment(*, bind_freeze: bool = True):
    if os.environ.get("SHENGJI_FAST") != "1" \
            or os.environ.get("SHENGJI_REQUIRE_VOIDS") != "1":
        raise ProtocolRefused(
            "set SHENGJI_FAST=1 and SHENGJI_REQUIRE_VOIDS=1 exactly")
    enabled = [name for name in REFUSED_ENV_KEYS if name in os.environ]
    if enabled:
        raise ProtocolRefused(
            f"experimental sampler/ballot flags must be absent: {enabled}")
    from shengji.engine import combos, fast
    if not fast.HAVE_FAST or combos.decompose is not fast.decompose:
        raise ProtocolRefused("compiled engine requested but not active")
    if bind_freeze:
        receipt = load_freeze_receipt()
        checks = {
            "selection_identity": selection_identity(),
            "selection_digest": selection_digest(),
            "source_sha256s": source_sha256s(),
            "policy_contract_sha256s": policy_contract_sha256s(),
            "stream_proof": stream_proof(),
            "python": platform.python_version(),
            "fast_binary_sha256": sha256(fast._fast.__file__),
            "execution_host": os.uname().nodename,
            "execution_root": str(SERVER.resolve()),
        }
        drift = [name for name, value in checks.items()
                 if receipt.get(name) != value]
        if drift:
            raise ProtocolRefused(
                f"runtime differs from immutable freeze: {drift}")
    return fast


def require_clean_pushed_head(expected_git: str | None = None) -> str:
    dirty = git("status", "--porcelain")
    if dirty:
        raise ProtocolRefused(f"RLCB-C1 refuses a dirty tree: {dirty}")
    head = git("rev-parse", "HEAD")
    if expected_git is not None and head != expected_git:
        raise ProtocolRefused(f"runtime git {head}, expected {expected_git}")
    if not git_is_ancestor(head, "origin/main"):
        raise ProtocolRefused(f"RLCB-C1 HEAD {head} is not pushed to origin/main")
    return head


def protocol_problems(*, require_receipt: bool = True) -> list[str]:
    problems = []
    if selection_identity() != {
        "schema": "rlcb-c1-shard-v1",
        "aggregate_schema": "rlcb-c1-aggregate-v1",
        "claim": "fresh_report_lcb_superiority_over_current_mc",
        "run_namespace": "rlcb-c1-150m-v1",
        "shard_count": 8,
        "clusters_per_shard": 256,
        "total_clusters": 2_048,
        "seed0": 150_000_000,
        "seed_hi": 150_002_047,
        "opponent": "mc-strong",
        "labels": {
            "report_lcb": "mc-s0-report-lcb",
            "current": "mc-strong",
            "current_null": "mc-strong-null-rlcb-c1",
        },
        "null_offset": 60_000_011,
        "selection_rule": SELECTION_RULE,
        "claim_boundary": CLAIM_BOUNDARY,
    }:
        problems.append("literal RLCB-C1 selection identity drifted")
    problems += stream_collision_problems()
    try:
        bots = {label: make_bot(name, seed=7)
                for label, name in LABELS.items()}
        contracts = {label: uppercase_contract(bot)
                     for label, bot in bots.items()}
    except Exception as exc:
        problems.append(
            f"policy construction failed: {type(exc).__name__}: {exc}")
        return sorted(set(problems))

    report = contracts["report_lcb"]
    if (report.get("N_DETERMINIZATIONS") != 30
            or report.get("REQUIRE_EXACT_WORK") is not True
            or report.get("REPORT_FOLD_WORLDS") != 300
            or report.get("REPORT_RULE") != "lcb"
            or report.get("REPORT_MIN_GAIN") != 0.0
            or report.get("REPORT_ALPHA") != 0.05
            or report.get("REPORT_T_CRITICAL") != 1.70
            or report.get("MARGIN") != 5.0
            or report.get("ADAPTIVE_ALLOCATION") is not False
            or report.get("EXTRA_SELECTION_WORK") != 0
            or S0_REPORT_WORLDS != 300):
        problems.append("live report-LCB N=30/R=300 fixed policy drifted")
    current = dict(contracts["current"])
    null = dict(contracts["current_null"])
    if null.pop("NULL_SEED_OFFSET", None) != NULL_OFFSET or current != null:
        problems.append("collision-free null differs from current search contract")
    if bots["current_null"].rng.getstate() != \
            make_bot("mc-strong", seed=7 + NULL_OFFSET).rng.getstate():
        problems.append("current-null does not implement the frozen RNG shift")
    if bots["current_null"].rng.getstate() == bots["current"].rng.getstate():
        problems.append("current-null reuses current's RNG stream")
    for label, bot in bots.items():
        if bot.N_DETERMINIZATIONS != 30:
            problems.append(f"{label}: root N is not 30")
        if any(getattr(bot, flag, False) for flag in (
            "MC_BURY", "STRUCTURED_BURY", "EXACT_ENDGAME",
            "ADAPTIVE_ALLOCATION" if label != "report_lcb" else "RANDOM_ALLOCATION",
        )):
            problems.append(f"{label}: unrelated search feature enabled")
    try:
        ballots = arm_ballots(LABELS.values())
        if len(set(ballots.values())) != 1:
            problems.append(f"RLCB-C1 policy ballots differ: {ballots}")
    except Exception as exc:
        problems.append(f"ballot preflight failed: {type(exc).__name__}: {exc}")
    if require_receipt:
        try:
            receipt = load_freeze_receipt()
            if receipt.get("selection_identity") != selection_identity() \
                    or receipt.get("selection_digest") != selection_digest():
                problems.append("freeze receipt selection identity drifted")
            if receipt.get("source_sha256s") != source_sha256s():
                problems.append("freeze receipt transitive source drifted")
            if receipt.get("policy_contract_sha256s") != \
                    policy_contract_sha256s():
                problems.append("freeze receipt policy contract drifted")
            if receipt.get("stream_proof") != stream_proof():
                problems.append("freeze receipt stream proof drifted")
        except ProtocolRefused as exc:
            problems.append(str(exc))
    return sorted(set(problems))


def freeze_payload(fast) -> dict:
    problems = protocol_problems(require_receipt=False)
    if problems:
        raise ProtocolRefused("protocol cannot freeze: " + "; ".join(problems))
    return {
        "schema": FREEZE_SCHEMA,
        "selection_identity": selection_identity(),
        "selection_digest": selection_digest(),
        "source_sha256s": source_sha256s(),
        "policy_contract_sha256s": policy_contract_sha256s(),
        "stream_proof": stream_proof(),
        "python": platform.python_version(),
        "fast_binary_sha256": sha256(fast._fast.__file__),
        "execution_host": os.uname().nodename,
        "execution_root": str(SERVER.resolve()),
    }


def _counter_problems(label: str, side: str, value: object) -> list[str]:
    prefix = f"{label}/{side}"
    if not isinstance(value, dict) or set(value) != set(COUNTER_FIELDS):
        return [f"{prefix}: counter schema drift"]
    counters = value
    problems = []
    for field in INTEGER_COUNTER_FIELDS:
        item = counters[field]
        if isinstance(item, bool) or not isinstance(item, int) or item < 0:
            problems.append(f"{prefix}: malformed {field}")
    seconds = counters["search_secs"]
    if (isinstance(seconds, bool) or not isinstance(seconds, (int, float))
            or not math.isfinite(float(seconds)) or seconds < 0):
        problems.append(f"{prefix}: malformed search_secs")
    if problems:
        return problems
    if counters["sample_attempts"] != (
            counters["accepted_worlds"] + counters["failed_worlds"]):
        problems.append(f"{prefix}: sampler counters do not reconcile")
    for field in FORBIDDEN_COUNTER_FIELDS:
        if counters[field] != 0:
            problems.append(f"{prefix}: nonzero {field}")
    searches = counters["searches"]
    accepted = counters["accepted_worlds"]
    expected = ((30 + S0_REPORT_WORLDS) * searches
                if label == "report_lcb" and side == "arm"
                else 30 * searches)
    if accepted != expected:
        problems.append(
            f"{prefix}: accepted dose {accepted} != registered {expected}")
    if searches and counters["rollouts"] <= 0:
        problems.append(f"{prefix}: searches consumed no rollouts")
    return problems


def record_problems(records: object, *, expected_keys: set[tuple[int, int]]) \
        -> list[str]:
    if not isinstance(records, dict) or set(records) != set(LABELS):
        return ["record labels differ from frozen labels"]
    problems = []
    for label, rows in records.items():
        if not isinstance(rows, list):
            problems.append(f"{label}: rows are not a list")
            continue
        keys = []
        for row in rows:
            if not isinstance(row, dict):
                problems.append(f"{label}: row is not a mapping")
                continue
            required = {
                "run", "label", "policy", "seed", "flip", "won",
                "level_utility", "arm", "opp",
            }
            if not required.issubset(row):
                problems.append(f"{label}: record schema drift")
                continue
            seed, flip = row["seed"], row["flip"]
            keys.append((seed, flip))
            utility, won = row["level_utility"], row["won"]
            if (row["label"] != label or row["policy"] != LABELS[label]
                    or isinstance(seed, bool) or not isinstance(seed, int)
                    or isinstance(flip, bool) or flip not in (0, 1)
                    or isinstance(won, bool) or won not in (0, 1)
                    or isinstance(utility, bool) or not isinstance(utility, int)
                    or utility == 0 or (utility > 0) != bool(won)):
                problems.append(f"{label}: malformed outcome record")
            problems += _counter_problems(label, "arm", row.get("arm"))
            problems += _counter_problems(label, "opp", row.get("opp"))
        if len(keys) != len(set(keys)):
            problems.append(f"{label}: duplicate seed/flip record")
        if set(keys) != expected_keys:
            problems.append(f"{label}: exact seed/flip coverage differs")
    return sorted(set(problems))


def counter_totals(records: dict[str, list]) -> dict:
    return {
        label: {
            side: {
                field: sum(row[side][field] for row in rows)
                for field in COUNTER_FIELDS
            }
            for side in ("arm", "opp")
        }
        for label, rows in records.items()
    }


def accepted_dose(records: dict[str, list]) -> dict:
    totals = counter_totals(records)
    return {
        label: {
            side: {
                "searches": totals[label][side]["searches"],
                "accepted_worlds": totals[label][side]["accepted_worlds"],
                "expected_accepted_worlds": (
                    (30 + S0_REPORT_WORLDS)
                    * totals[label][side]["searches"]
                    if label == "report_lcb" and side == "arm"
                    else 30 * totals[label][side]["searches"]
                ),
                "exact": totals[label][side]["accepted_worlds"] == (
                    (30 + S0_REPORT_WORLDS)
                    * totals[label][side]["searches"]
                    if label == "report_lcb" and side == "arm"
                    else 30 * totals[label][side]["searches"]
                ),
            }
            for side in ("arm", "opp")
        }
        for label in LABELS
    }


def contrast(records: dict[str, list], a: str, b: str) -> dict:
    mean, half, clusters = paired_by_seed(records[a], records[b])
    return {
        "a": a, "b": b, "mean": mean,
        "half_width_95": half, "clusters": clusters,
    }


def gate_criteria(stats: object) -> dict[str, bool]:
    names = {"report_lcb-current", "current_null-current"}
    shaped = (isinstance(stats, dict) and set(stats) == names
              and all(isinstance(value, dict) for value in stats.values()))
    exact = shaped and all(
        value.get("clusters") == TOTAL_CLUSTERS for value in stats.values()
    )
    finite = shaped and all(
        isinstance(value.get("mean"), (int, float))
        and not isinstance(value.get("mean"), bool)
        and math.isfinite(float(value["mean"]))
        and isinstance(value.get("half_width_95"), (int, float))
        and not isinstance(value.get("half_width_95"), bool)
        and math.isfinite(float(value["half_width_95"]))
        and float(value["half_width_95"]) >= 0
        for value in stats.values()
    )
    if not shaped:
        return {
            "exact_registered_clusters": False,
            "finite_paired_statistics": False,
            "current_null_interval_contains_zero": False,
            "single_superiority_lcb_gt_zero": False,
            "all": False,
        }
    null = stats["current_null-current"]
    arm = stats["report_lcb-current"]
    null_sane = exact and finite and (
        abs(float(null["mean"])) <= float(null["half_width_95"])
    )
    superior = exact and finite and (
        float(arm["mean"]) - float(arm["half_width_95"]) > 0
    )
    return {
        "exact_registered_clusters": exact,
        "finite_paired_statistics": finite,
        "current_null_interval_contains_zero": null_sane,
        "single_superiority_lcb_gt_zero": superior,
        "all": exact and finite and null_sane and superior,
    }


def gate_decision(criteria: dict[str, bool]) -> str:
    if not (criteria.get("exact_registered_clusters")
            and criteria.get("finite_paired_statistics")):
        return "REFUSE_INVALID_EVIDENCE"
    if not criteria.get("current_null_interval_contains_zero"):
        return "REFUSE_NULL_CALIBRATION"
    if criteria.get("single_superiority_lcb_gt_zero"):
        return "CONFIRM_REPORT_LCB"
    return "REPORT_LCB_NOT_CONFIRMED"


def run_root() -> Path:
    return LOGS / RUN_NAMESPACE


def record_path(root: Path, index: int) -> Path:
    return root / f"shard{index:02d}.jsonl"


def manifest_path(root: Path, index: int) -> Path:
    return Path(str(record_path(root, index)) + ".manifest.json")


def aggregate_path(root: Path) -> Path:
    return root / "aggregate.json"


def _publish_partial(partial: Path, final: Path) -> None:
    if not partial.is_file():
        raise ProtocolRefused(f"completed partial is missing: {partial}")
    try:
        os.link(partial, final)
    except FileExistsError as exc:
        raise ProtocolRefused(f"refusing to overwrite {final}") from exc
    partial.unlink()


def _write_json_exclusive(path: Path, payload: dict) -> None:
    partial = Path(str(path) + ".partial")
    if path.exists() or partial.exists():
        raise ProtocolRefused(f"refusing to overwrite {path} or {partial}")
    with partial.open("x", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    _publish_partial(partial, path)


def _canonical_root(value: str | Path) -> Path:
    path = Path(value)
    resolved = (path if path.is_absolute() else SERVER / path).resolve()
    if resolved != run_root().resolve():
        raise ProtocolRefused(
            f"run root must be exactly {run_root().resolve()}, got {resolved}")
    return resolved


def run_shard(args) -> None:
    fast = require_environment()
    problems = protocol_problems()
    if problems:
        raise ProtocolRefused("protocol preflight: " + "; ".join(problems))
    head = require_clean_pushed_head(args.expected_git)
    if not 0 <= args.shard_index < SHARD_COUNT:
        raise ProtocolRefused("shard index outside 0..7")
    root = _canonical_root(args.root)
    if not root.is_dir() or root.is_symlink():
        raise ProtocolRefused("supervisor-owned run root is missing or a symlink")
    out = record_path(root, args.shard_index)
    manifest = manifest_path(root, args.shard_index)
    residue = [
        out, Path(str(out) + ".partial"), Path(str(out) + ".FAILED"),
        manifest, Path(str(manifest) + ".partial"),
        Path(str(manifest) + ".FAILED"),
    ]
    if any(path.exists() or path.is_symlink() for path in residue):
        raise ProtocolRefused(f"shard {args.shard_index} namespace is not fresh")
    seed0 = SEED0 + args.shard_index * CLUSTERS_PER_SHARD
    expected_keys = {
        (seed, flip)
        for seed in range(seed0, seed0 + CLUSTERS_PER_SHARD)
        for flip in (0, 1)
    }
    runtime = runtime_identity(fast)
    run_id = f"{RUN_NAMESPACE}:{head}"
    manifest_payload = {
        "schema": SCHEMA,
        "claim": CLAIM,
        "claim_boundary": CLAIM_BOUNDARY,
        "selection_rule": SELECTION_RULE,
        "selection_identity": selection_identity(),
        "selection_digest": selection_digest(),
        "run_id": run_id,
        "git_sha": head,
        "tree_dirty": False,
        "evidence_grade": True,
        "production_promotion": False,
        "automatic_deployment": False,
        "score_blind_progress": True,
        "shard_statistics_persisted": False,
        "runtime": runtime,
        "freeze_receipt_sha256": sha256(FREEZE_RECEIPT),
        "stream_proof": stream_proof(),
        "shard_index": args.shard_index,
        "shard_count": SHARD_COUNT,
        "total_clusters": TOTAL_CLUSTERS,
        "clusters": CLUSTERS_PER_SHARD,
        "seed0": seed0,
        "seed_hi": seed0 + CLUSTERS_PER_SHARD - 1,
        "opponent": OPPONENT,
        "labels": LABELS,
        "policy_contracts": {
            name: policy_contract(name) for name in LABELS.values()
        },
        "ballots": arm_ballots(LABELS.values()),
        "complete": False,
    }
    manifest_partial = Path(str(manifest) + ".partial")
    with manifest_partial.open("x", encoding="utf-8") as fh:
        json.dump(manifest_payload, fh, indent=2, sort_keys=True)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    out_partial = Path(str(out) + ".partial")
    records = {}
    with out_partial.open("x", encoding="utf-8") as fh:
        for label, policy in LABELS.items():
            print(f"START label={label} policy={policy}", flush=True)
            records[label] = run_arm(
                label, policy, OPPONENT, CLUSTERS_PER_SHARD, seed0,
                fh, run_id, progress_scores=False,
            )
            print(
                f"COMPLETE label={label} clusters={CLUSTERS_PER_SHARD}",
                flush=True,
            )
        fh.flush()
        os.fsync(fh.fileno())
    problems = record_problems(records, expected_keys=expected_keys)
    manifest_payload.update({
        "records_sha256": sha256(out_partial),
        "record_counts": {label: len(rows)
                          for label, rows in records.items()},
        "counter_totals": counter_totals(records),
        "accepted_dose": accepted_dose(records),
        "problems": problems,
        "complete": not problems,
    })
    with manifest_partial.open("w", encoding="utf-8") as fh:
        json.dump(manifest_payload, fh, indent=2, sort_keys=True)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    if problems:
        _publish_partial(out_partial, Path(str(out) + ".FAILED"))
        _publish_partial(
            manifest_partial, Path(str(manifest) + ".FAILED"))
        raise ProtocolRefused("shard failed: " + "; ".join(problems))
    _publish_partial(out_partial, out)
    _publish_partial(manifest_partial, manifest)
    print(
        f"SHARD_COMPLETE index={args.shard_index} "
        f"records_sha256={manifest_payload['records_sha256']}",
        flush=True,
    )


def _load_population(root: Path, expected_git: str, runtime: dict) \
        -> tuple[list[dict], dict[str, list]]:
    manifests = []
    records = {label: [] for label in LABELS}
    expected_contracts = {
        name: policy_contract(name) for name in LABELS.values()
    }
    expected_ballots = arm_ballots(LABELS.values())
    for index in range(SHARD_COUNT):
        out = record_path(root, index)
        manifest_file = manifest_path(root, index)
        for path in (out, manifest_file):
            if path.is_symlink() or not path.is_file():
                raise ProtocolRefused(f"missing/non-regular final artifact {path}")
            for suffix in (".partial", ".FAILED"):
                if Path(str(path) + suffix).exists():
                    raise ProtocolRefused(f"residual artifact {path}{suffix}")
        try:
            manifest = json.loads(manifest_file.read_text())
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProtocolRefused(f"unreadable manifest {manifest_file}: {exc}")
        seed0 = SEED0 + index * CLUSTERS_PER_SHARD
        exact = {
            "schema": SCHEMA,
            "claim": CLAIM,
            "claim_boundary": CLAIM_BOUNDARY,
            "selection_rule": SELECTION_RULE,
            "selection_identity": selection_identity(),
            "selection_digest": selection_digest(),
            "run_id": f"{RUN_NAMESPACE}:{expected_git}",
            "git_sha": expected_git,
            "tree_dirty": False,
            "evidence_grade": True,
            "production_promotion": False,
            "automatic_deployment": False,
            "score_blind_progress": True,
            "shard_statistics_persisted": False,
            "runtime": runtime,
            "freeze_receipt_sha256": sha256(FREEZE_RECEIPT),
            "stream_proof": stream_proof(),
            "shard_index": index,
            "shard_count": SHARD_COUNT,
            "total_clusters": TOTAL_CLUSTERS,
            "clusters": CLUSTERS_PER_SHARD,
            "seed0": seed0,
            "seed_hi": seed0 + CLUSTERS_PER_SHARD - 1,
            "opponent": OPPONENT,
            "labels": LABELS,
            "policy_contracts": expected_contracts,
            "ballots": expected_ballots,
            "complete": True,
        }
        drift = [field for field, value in exact.items()
                 if manifest.get(field) != value]
        if drift or manifest.get("problems"):
            raise ProtocolRefused(
                f"manifest {index} contract drift: {drift}; "
                f"problems={manifest.get('problems')}")
        if sha256(out) != manifest.get("records_sha256"):
            raise ProtocolRefused(f"record digest drift in shard {index}")
        try:
            shard_records = {label: [] for label in LABELS}
            for line in out.read_text().splitlines():
                row = json.loads(line)
                label = row.get("label") if isinstance(row, dict) else None
                if label not in shard_records:
                    raise ValueError(f"unknown label {label!r}")
                shard_records[label].append(row)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError,
                ValueError) as exc:
            raise ProtocolRefused(f"unreadable records {out}: {exc}") from exc
        expected_keys = {
            (seed, flip)
            for seed in range(seed0, seed0 + CLUSTERS_PER_SHARD)
            for flip in (0, 1)
        }
        problems = record_problems(shard_records, expected_keys=expected_keys)
        if problems:
            raise ProtocolRefused(
                f"reopened shard {index}: " + "; ".join(problems))
        if manifest.get("record_counts") != {
                label: 2 * CLUSTERS_PER_SHARD for label in LABELS}:
            raise ProtocolRefused(f"record count drift in shard {index}")
        if manifest.get("counter_totals") != counter_totals(shard_records):
            raise ProtocolRefused(f"counter total drift in shard {index}")
        if manifest.get("accepted_dose") != accepted_dose(shard_records):
            raise ProtocolRefused(f"accepted-dose drift in shard {index}")
        manifests.append(manifest)
        for label in LABELS:
            records[label].extend(shard_records[label])
    expected_all = {
        (seed, flip) for seed in range(SEED0, SEED_HI + 1)
        for flip in (0, 1)
    }
    problems = record_problems(records, expected_keys=expected_all)
    if problems:
        raise ProtocolRefused("aggregate population: " + "; ".join(problems))
    return manifests, records


def compute_aggregate(root: Path, expected_git: str, runtime: dict) -> dict:
    manifests, records = _load_population(root, expected_git, runtime)
    stats = {
        "report_lcb-current": contrast(records, "report_lcb", "current"),
        "current_null-current": contrast(records, "current_null", "current"),
    }
    criteria = gate_criteria(stats)
    decision = gate_decision(criteria)
    return {
        "schema": AGGREGATE_SCHEMA,
        "claim": CLAIM,
        "claim_boundary": CLAIM_BOUNDARY,
        "selection_rule": SELECTION_RULE,
        "selection_identity": selection_identity(),
        "selection_digest": selection_digest(),
        "run_namespace": RUN_NAMESPACE,
        "git_sha": expected_git,
        "runtime": runtime,
        "freeze_receipt_sha256": sha256(FREEZE_RECEIPT),
        "stream_proof": stream_proof(),
        "inputs": [
            {
                "shard_index": index,
                "manifest": str(manifest_path(root, index)),
                "manifest_sha256": sha256(manifest_path(root, index)),
                "records": str(record_path(root, index)),
                "records_sha256": sha256(record_path(root, index)),
            }
            for index in range(SHARD_COUNT)
        ],
        "record_counts": {label: len(rows) for label, rows in records.items()},
        "counter_totals": counter_totals(records),
        "accepted_dose": accepted_dose(records),
        "stats": stats,
        "criteria": criteria,
        "decision": decision,
        "formal_confirmation": decision == "CONFIRM_REPORT_LCB",
        "production_promotion": False,
        "automatic_deployment": False,
        "authorizes": (
            "formal report-LCB confirmation claim only"
            if decision == "CONFIRM_REPORT_LCB" else "nothing"
        ),
        "complete": True,
        "shard_manifest_count": len(manifests),
    }


def aggregate(args) -> None:
    fast = require_environment()
    problems = protocol_problems()
    if problems:
        raise ProtocolRefused("protocol preflight: " + "; ".join(problems))
    head = require_clean_pushed_head(args.expected_git)
    root = _canonical_root(args.root)
    payload = compute_aggregate(root, head, runtime_identity(fast))
    _write_json_exclusive(aggregate_path(root), payload)
    print(json.dumps({
        "aggregate": str(aggregate_path(root)),
        "sha256": sha256(aggregate_path(root)),
        "decision": payload["decision"],
        "formal_confirmation": payload["formal_confirmation"],
        "production_promotion": False,
    }, sort_keys=True), flush=True)


def verify(args) -> None:
    fast = require_environment()
    problems = protocol_problems()
    if problems:
        raise ProtocolRefused("protocol preflight: " + "; ".join(problems))
    head = require_clean_pushed_head(args.expected_git)
    root = _canonical_root(args.root)
    path = aggregate_path(root)
    if path.is_symlink() or not path.is_file():
        raise ProtocolRefused("canonical aggregate is missing/non-regular")
    try:
        stored = json.loads(path.read_text())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolRefused(f"aggregate unreadable: {exc}") from exc
    expected = compute_aggregate(root, head, runtime_identity(fast))
    if stored != expected:
        raise ProtocolRefused("aggregate differs from full recomputation")
    print(json.dumps({
        "verified": True,
        "aggregate_sha256": sha256(path),
        "decision": stored["decision"],
        "formal_confirmation": stored["formal_confirmation"],
        "production_promotion": False,
    }, sort_keys=True), flush=True)


@dataclass(frozen=True)
class Job:
    index: int
    argv: tuple[str, ...]
    log_partial: Path
    log_final: Path


def shard_jobs(root: Path, expected_git: str) -> list[Job]:
    jobs = []
    for index in range(SHARD_COUNT):
        partial = root / f"shard{index:02d}.log.partial"
        final = root / f"shard{index:02d}.log"
        jobs.append(Job(index, (
            sys.executable, str(SCRIPT), "shard",
            "--root", str(root),
            "--shard-index", str(index),
            "--expected-git", expected_git,
        ), partial, final))
    return jobs


def _terminate(processes: Sequence[subprocess.Popen]) -> None:
    active = [process for process in processes if process.poll() is None]
    for process in active:
        try:
            process.terminate()
        except ProcessLookupError:
            pass
    for process in active:
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            process.wait(timeout=5)


def supervise(args, *, popen: Callable[..., subprocess.Popen] = subprocess.Popen,
              poll_seconds: float = 1.0,
              heartbeat_seconds: float = 30.0) -> None:
    fast = require_environment()
    problems = protocol_problems()
    if problems:
        raise ProtocolRefused("protocol preflight: " + "; ".join(problems))
    head = require_clean_pushed_head(args.expected_git)
    root = _canonical_root(args.root)
    try:
        root.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise ProtocolRefused(
            f"refusing existing RLCB-C1 attempt {root}") from exc
    progress_partial = root / "supervisor_progress.jsonl.partial"
    progress_final = root / "supervisor_progress.jsonl"
    progress = progress_partial.open("x", encoding="utf-8")

    def event(status: str, **fields) -> None:
        payload = {"time_ns": time.time_ns(), "status": status, **fields}
        progress.write(json.dumps(
            payload, sort_keys=True, separators=(",", ":")) + "\n")
        progress.flush()
        os.fsync(progress.fileno())
        suffix = " ".join(f"{key}={value}" for key, value in fields.items())
        print(f"PROGRESS {status}" + (f" {suffix}" if suffix else ""),
              flush=True)

    jobs = shard_jobs(root, head)
    streams: dict[int, IO[str]] = {}
    processes: dict[int, subprocess.Popen] = {}
    try:
        event(
            "ADMITTED", git=head, namespace=RUN_NAMESPACE,
            shards=SHARD_COUNT, clusters=TOTAL_CLUSTERS,
            freeze_receipt_sha256=sha256(FREEZE_RECEIPT),
        )
        environment = dict(os.environ)
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        for job in jobs:
            streams[job.index] = job.log_partial.open("x", encoding="utf-8")
        for job in jobs:
            processes[job.index] = popen(
                list(job.argv), cwd=SERVER, env=environment,
                stdout=streams[job.index], stderr=subprocess.STDOUT,
            )
        event("SHARDS_RUNNING", workers=len(processes))
        active = set(processes)
        started = time.monotonic()
        last_heartbeat = started
        while active:
            for index in list(active):
                process = processes[index]
                code = process.poll()
                if code is None:
                    continue
                stream = streams.pop(index)
                stream.flush()
                os.fsync(stream.fileno())
                stream.close()
                active.remove(index)
                job = jobs[index]
                if code != 0:
                    event("REFUSED", shard=index, exit_code=code,
                          log=str(job.log_partial))
                    _terminate([processes[item] for item in active])
                    raise ProtocolRefused(
                        f"shard {index} exited {code}; stopped peers")
                _publish_partial(job.log_partial, job.log_final)
                event("SHARD_COMPLETE", shard=index,
                      complete=SHARD_COUNT - len(active), total=SHARD_COUNT)
            now = time.monotonic()
            if active and now - last_heartbeat >= heartbeat_seconds:
                event(
                    "HEARTBEAT", active=len(active),
                    complete=SHARD_COUNT - len(active), total=SHARD_COUNT,
                    elapsed_seconds=round(now - started, 1),
                )
                last_heartbeat = now
            if active:
                time.sleep(poll_seconds)
        # Recheck every frozen dependency after the children exit and before
        # opening any outcomes into a statistic.
        require_environment()
        require_clean_pushed_head(head)
        payload = compute_aggregate(root, head, runtime_identity(fast))
        _write_json_exclusive(aggregate_path(root), payload)
        recomputed = compute_aggregate(root, head, runtime_identity(fast))
        if json.loads(aggregate_path(root).read_text()) != recomputed:
            raise ProtocolRefused("post-publication aggregate verification failed")
        event(
            "COMPLETE", aggregate_sha256=sha256(aggregate_path(root)),
            decision=payload["decision"],
            formal_confirmation=payload["formal_confirmation"],
            production_promotion=False,
        )
        progress.close()
        _publish_partial(progress_partial, progress_final)
        print(json.dumps({
            "aggregate": str(aggregate_path(root)),
            "aggregate_sha256": sha256(aggregate_path(root)),
            "decision": payload["decision"],
            "formal_confirmation": payload["formal_confirmation"],
            "verified": True,
            "production_promotion": False,
        }, sort_keys=True), flush=True)
    except BaseException as exc:
        _terminate(list(processes.values()))
        try:
            event("SUPERVISOR_REFUSED", error=f"{type(exc).__name__}: {exc}",
                  production_promotion=False)
        except Exception:
            pass
        progress.close()
        raise
    finally:
        for stream in streams.values():
            stream.close()


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="command", required=True)
    sub.add_parser("freeze")
    sub.add_parser("preflight")
    for name in ("aggregate", "verify", "supervise"):
        command = sub.add_parser(name)
        command.add_argument("--root", required=True)
        command.add_argument("--expected-git", required=True)
    shard = sub.add_parser("shard")
    shard.add_argument("--root", required=True)
    shard.add_argument("--shard-index", type=int, required=True)
    shard.add_argument("--expected-git", required=True)
    return ap


def _signal_refusal(signum, _frame) -> None:
    raise ProtocolRefused(f"received signal {signum}")


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    os.chdir(SERVER)
    try:
        if args.command == "freeze":
            fast = require_environment(bind_freeze=False)
            require_clean_pushed_head()
            print(json.dumps(freeze_payload(fast), indent=2, sort_keys=True))
        elif args.command == "preflight":
            fast = require_environment()
            problems = protocol_problems()
            if problems:
                raise ProtocolRefused("; ".join(problems))
            head = require_clean_pushed_head()
            print(json.dumps({
                "admitted": True, "git": head,
                "runtime": runtime_identity(fast),
                "stream_proof": stream_proof(),
            }, sort_keys=True))
        elif args.command == "shard":
            run_shard(args)
        elif args.command == "aggregate":
            aggregate(args)
        elif args.command == "verify":
            verify(args)
        else:
            for name in ("SIGINT", "SIGTERM", "SIGHUP"):
                if hasattr(signal, name):
                    signal.signal(getattr(signal, name), _signal_refusal)
            supervise(args)
    except Exception as exc:
        print(f"REFUSING: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
