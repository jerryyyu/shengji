"""Corrected-encoder compatibility gate for frozen ``v11pair``.

The historical 121M v1 block ran after :class:`Memory` changed its banker-
kitty default but before encoder v1 explicitly restored ``own_kitty=False``.
That block therefore answers a different, accidentally drifted observation
question and is never reopened or reinterpreted here.

This v2 protocol asks one narrow question on a disjoint population: does the
unchanged ``ep07`` direct override remain superior to today's compiled N=30
``mc-strong`` when inference uses the restored historical encoder-v1
semantics?  Eight shards cover exactly 2,048 clusters at seeds
142,000,000--142,002,047.  A pass is checkpoint-compatibility evidence only;
it is not retraining, private-kitty encoder evidence, protected-composition
evidence, multi-round progression evidence, or production authorization.

No command in this module launches another experiment or changes production.
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import math
import os
import platform
import subprocess
import sys
import time
from pathlib import Path


SERVER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER))

from shengji.ai.registry import make_bot  # noqa: E402
from shengji.evaluation import (arm_ballots, paired_by_seed,  # noqa: E402
                                run_arm)
from shengji.rl.encode import (ENCODER_IMPLEMENTATION_SHA256,  # noqa: E402
                               ENCODER_SOURCE_SHA256S, ENC_VERSION,
                               OBS_SCHEMA, encode_obs)


SCHEMA = "v11-current-revalidation-v2"
AGGREGATE_SCHEMA = "v11-current-revalidation-aggregate-v2"
CLAIM = "frozen_v11pair_compatibility_under_restored_encoder_v1_only"
SHARD_COUNT = 8
TOTAL_CLUSTERS = 2_048
CLUSTERS_PER_SHARD = 256
SEED0 = 142_000_000
SEED_HI = 142_002_047
OPPONENT = "mc-strong"
LABELS = {
    "arm": "rl-override-v11pair",
    "null": "mc-strong-null",
    "reference": "mc-strong",
}
CHECKPOINT = SERVER / "snapshots_v11pair" / "ep07.npz"
CHECKPOINT_SHA256 = (
    "cd89d6ed7e9d5f798d69ce546107c4dfbef682c5385de39af527026e39e1c003"
)

# Literal corrected boundary.  Reading only the dynamic version integer would
# repeat the bug this protocol exists to repair: dependency semantics changed
# while ENC_VERSION remained one.
EXPECTED_ENCODER_CONTRACT = {
    "schema": "rl-observation-v1-public-no-private-kitty",
    "layout_version": 1,
    "implementation_sha256": (
        "a55cba182152fa51f2d304fb1b9adb02b6e23f4073f7bad37fe2d6ca1ab31afa"
    ),
    "source_sha256s": {
        "encode": (
            "819fe2b2fc3cb9f0dd18cfd1c916b2387e92d97345f6dda212b2f149c7e7408b"
        ),
        "memory": (
            "905873b332fd54471070b25ce24f100b813c9a9f234c1b50254d00895140cf51"
        ),
    },
}
INVALIDATED_V1 = {
    "schema": "v11-current-revalidation-v1",
    "git_sha": "e66b90bc3a50d514472670ea99909add5ea30d19",
    "seed0": 121_000_000,
    "seed_hi": 121_002_047,
    "admissible_parent": False,
    "encoder_source_sha256": (
        "a2022b0754597627ba58c2c4630754ae89b5be0b4daefe7a775b6ade587214cf"
    ),
    "reason": "banker observation used drifted Memory own-kitty default",
}
SELECTION_RULE = (
    "DECLARE the frozen ep07 checkpoint compatible with restored encoder-v1 "
    "direct-override inference only if, over exactly 2,048 fresh seed "
    "clusters, the paired two-sided 95% lower bounds for v11-current and "
    "v11-null are both >0, the mc-strong-null minus current interval contains "
    "zero, and every N=30 search consumes exactly 30 accepted worlds with no "
    "sampler failure, rejection, short search, zero-world decision or void "
    "fallback. This does not validate the drifted v1 artifact, retrain v11, "
    "test a private-kitty encoder, test protected composition or authorize "
    "production. An interval containing zero is not equivalence."
)
SHARD_CLAIM_BOUNDARY = (
    "Frozen ep07 direct-override compatibility under restored public-no-"
    "private-kitty encoder v1 only; not drifted-v1 rehabilitation, retraining, "
    "private-kitty encoding, protected composition, multi-round progression "
    "or production evidence."
)
SAMPLER_FLAGS = (
    "SHENGJI_WEIGHTED_SPLITS",
    "SHENGJI_UNIFORM_DEAL",
    "SHENGJI_PHYSICAL_FILLS",
    "SHENGJI_ALLOW_BALLOT_MISMATCH",
)
COUNTER_FIELDS = (
    "rollouts", "searches", "search_secs", "void_fallbacks",
    "rejected_worlds", "sample_attempts", "accepted_worlds",
    "failed_worlds", "short_searches", "zero_world", "exact_endgames",
    "exact_endgame_attempts", "exact_endgame_refusals",
    "exact_endgame_budget_exceeded", "exact_endgame_sessions",
    "exact_endgame_nodes", "exact_endgame_cache_hits",
)
INTEGER_COUNTER_FIELDS = tuple(
    field for field in COUNTER_FIELDS if field != "search_secs")
FORBIDDEN_COUNTER_FIELDS = (
    "void_fallbacks", "rejected_worlds", "failed_worlds",
    "short_searches", "zero_world", "exact_endgames",
    "exact_endgame_attempts", "exact_endgame_refusals",
    "exact_endgame_budget_exceeded", "exact_endgame_sessions",
    "exact_endgame_nodes", "exact_endgame_cache_hits",
)


class ProtocolRefused(RuntimeError):
    """The requested artifact cannot establish the frozen v2 claim."""


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


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=SERVER.parent, check=True,
        capture_output=True, text=True,
    ).stdout.strip()


def publish_partial_exclusive(partial: os.PathLike | str,
                              final: os.PathLike | str) -> None:
    """Atomically publish completed bytes without replacing a competitor."""
    partial = Path(partial)
    final = Path(final)
    if not partial.is_file():
        raise ProtocolRefused(f"completed partial is missing: {partial}")
    try:
        os.link(partial, final)
    except FileExistsError as exc:
        raise ProtocolRefused(
            f"refusing to overwrite concurrently published {final}") from exc
    partial.unlink()


def write_exclusive_atomic(path: os.PathLike | str, payload: dict) -> None:
    path = Path(path)
    partial = Path(str(path) + ".partial")
    if path.exists() or partial.exists():
        raise ProtocolRefused(f"refusing to overwrite {path} or {partial}")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with partial.open("x") as fh:
            json.dump(payload, fh, indent=2, sort_keys=True)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        publish_partial_exclusive(partial, path)
    except Exception:
        if partial.exists() and not path.exists():
            partial.unlink()
        raise


def encoder_contract() -> dict:
    return {
        "schema": OBS_SCHEMA,
        "layout_version": ENC_VERSION,
        "implementation_sha256": ENCODER_IMPLEMENTATION_SHA256,
        "source_sha256s": dict(ENCODER_SOURCE_SHA256S),
    }


def runtime_identity(fast) -> dict:
    return {
        "host": os.uname().nodename,
        "python": platform.python_version(),
        "fast_engine": True,
        "require_voids": True,
        "experimental_sampler_flags": [],
        "encoder_contract": encoder_contract(),
        "digests": {
            "runner": sha256(__file__),
            "evaluation": sha256(SERVER / "shengji" / "evaluation.py"),
            "registry": sha256(SERVER / "shengji" / "ai" / "registry.py"),
            "mcbot": sha256(SERVER / "shengji" / "ai" / "mcbot.py"),
            "smart": sha256(SERVER / "shengji" / "ai" / "smart.py"),
            "memory": sha256(SERVER / "shengji" / "ai" / "memory.py"),
            "env": sha256(SERVER / "shengji" / "ai" / "env.py"),
            "ballot": sha256(SERVER / "shengji" / "engine" / "ballot.py"),
            "round": sha256(SERVER / "shengji" / "engine" / "round.py"),
            "game": sha256(SERVER / "shengji" / "engine" / "game.py"),
            "torch_policy": sha256(
                SERVER / "shengji" / "rl" / "torch_policy.py"),
            "encoder": sha256(SERVER / "shengji" / "rl" / "encode.py"),
            "npnet": sha256(SERVER / "shengji" / "rl" / "npnet.py"),
            "parity_fixture": sha256(
                SERVER / "tests" / "fixtures" / "npnet_v11pair.npz"),
            "fast_router": sha256(fast.__file__),
            "fast_binary": sha256(fast._fast.__file__),
            "checkpoint": sha256(CHECKPOINT),
        },
    }


def require_runtime() -> tuple[object, dict]:
    if (os.environ.get("SHENGJI_FAST") != "1"
            or os.environ.get("SHENGJI_REQUIRE_VOIDS") != "1"):
        raise ProtocolRefused(
            "set SHENGJI_FAST=1 and SHENGJI_REQUIRE_VOIDS=1")
    enabled = [name for name in SAMPLER_FLAGS if os.environ.get(name)]
    if enabled:
        raise ProtocolRefused(
            f"experimental sampler/ballot flags must be unset: {enabled}")
    from shengji.engine import combos, fast
    if not fast.HAVE_FAST or combos.decompose is not fast.decompose:
        raise ProtocolRefused("compiled engine requested but not active")
    return fast, runtime_identity(fast)


def uppercase_contract(bot) -> dict:
    out = {}
    for name in dir(bot):
        if not name.isupper():
            continue
        value = getattr(bot, name)
        if not isinstance(value, (bool, int, float, str, type(None))):
            raise ProtocolRefused(
                f"non-serializable policy contract {name}={value!r}")
        out[name] = value
    return out


def policy_contract(name: str) -> dict:
    bot = make_bot(name, seed=7)
    return {
        "policy": name,
        "class": type(bot).__name__,
        "uppercase": uppercase_contract(bot),
        "rollout_policy_class": (
            type(bot.rollout_policy).__name__
            if hasattr(bot, "rollout_policy") else None),
        "checkpoint_path": getattr(bot, "checkpoint_path", None),
        "checkpoint_sha256": getattr(bot, "checkpoint_sha256", None),
        "ballot": arm_ballots([name])[name],
    }


def _computed_encoder_implementation(source_sha256s: dict) -> str:
    payload = "|".join(
        f"{name}:{digest}" for name, digest in sorted(source_sha256s.items())
    ).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def protocol_problems() -> list[str]:
    problems = []
    if (SCHEMA != "v11-current-revalidation-v2"
            or CLAIM !=
            "frozen_v11pair_compatibility_under_restored_encoder_v1_only"):
        problems.append("v2 schema/claim boundary drifted")
    if (SHARD_COUNT != 8 or TOTAL_CLUSTERS != 2_048
            or CLUSTERS_PER_SHARD != 256
            or SHARD_COUNT * CLUSTERS_PER_SHARD != TOTAL_CLUSTERS):
        problems.append("registered 8x256 geometry drifted")
    if SEED0 != 142_000_000 or SEED_HI != 142_002_047:
        problems.append("registered fresh 142M seed block drifted")
    old_keys = set(range(INVALIDATED_V1["seed0"],
                         INVALIDATED_V1["seed_hi"] + 1))
    new_keys = set(range(SEED0, SEED_HI + 1))
    if old_keys & new_keys or INVALIDATED_V1["admissible_parent"] is not False:
        problems.append("v2 overlaps or re-admits invalidated v1")
    if LABELS != {
            "arm": "rl-override-v11pair",
            "null": "mc-strong-null",
            "reference": "mc-strong"} or OPPONENT != "mc-strong":
        problems.append("registered policies drifted")

    observed_encoder = encoder_contract()
    if observed_encoder != EXPECTED_ENCODER_CONTRACT:
        problems.append("restored encoder-v1 contract drifted")
    on_disk_sources = {
        "encode": sha256(SERVER / "shengji" / "rl" / "encode.py"),
        "memory": sha256(SERVER / "shengji" / "ai" / "memory.py"),
    }
    if on_disk_sources != EXPECTED_ENCODER_CONTRACT["source_sha256s"]:
        problems.append("encoder dependency source bytes drifted")
    if (_computed_encoder_implementation(on_disk_sources)
            != EXPECTED_ENCODER_CONTRACT["implementation_sha256"]):
        problems.append("encoder implementation digest is inconsistent")

    if not CHECKPOINT.is_file():
        problems.append(f"missing frozen checkpoint {CHECKPOINT}")
    elif sha256(CHECKPOINT) != CHECKPOINT_SHA256:
        problems.append("frozen v11pair checkpoint SHA-256 drifted")
    try:
        contracts = {name: policy_contract(name) for name in LABELS.values()}
        arm_bot = make_bot(LABELS["arm"], seed=7)
        current = make_bot(LABELS["reference"], seed=7)
        null = make_bot(LABELS["null"], seed=7)
        shifted = make_bot(LABELS["reference"], seed=7 + 999_983)
    except Exception as exc:
        problems.append(
            f"policy construction failed: {type(exc).__name__}: {exc}")
        contracts = {}
        arm_bot = current = null = shifted = None

    arm = contracts.get(LABELS["arm"], {})
    if arm.get("class") != "RLOverrideBot":
        problems.append("v11 arm is not the direct RLOverrideBot")
    if arm.get("uppercase", {}).get("MARGIN") != 0.02:
        problems.append("v11 direct threshold is not frozen at 0.02")
    if arm.get("checkpoint_path") != str(CHECKPOINT.resolve()) \
            or arm.get("checkpoint_sha256") != CHECKPOINT_SHA256:
        problems.append("v11 policy did not load the literal checkpoint bytes")

    if current is not None and null is not None and shifted is not None:
        if uppercase_contract(current) != uppercase_contract(null):
            problems.append("mc-strong-null behavioral contract drifted")
        if type(current.rollout_policy) is not type(null.rollout_policy):
            problems.append("mc-strong-null rollout policy drifted")
        if current.rng.getstate() == null.rng.getstate():
            problems.append("mc-strong-null reused current's RNG stream")
        if null.rng.getstate() != shifted.rng.getstate():
            problems.append("mc-strong-null is not the registered RNG shift")
        for name, bot in (("current", current), ("null", null)):
            if bot.N_DETERMINIZATIONS != 30 or bot.MARGIN != 5.0:
                problems.append(f"{name} is not literal N=30 fixed-margin MC")
            if any(getattr(bot, flag, False) for flag in
                   ("MC_BURY", "STRUCTURED_BURY", "EXACT_ENDGAME",
                    "CONFIDENCE_OVERRIDE", "ADAPTIVE_ALLOCATION")):
                problems.append(f"{name} enables an unrelated search feature")
    if arm_bot is not None:
        from shengji.rl import torch_policy
        if torch_policy.encode_obs is not encode_obs:
            problems.append("v11 inference is not using the bound encoder")

    try:
        ballots = arm_ballots(LABELS.values())
        if len(set(ballots.values())) != 1:
            problems.append(
                f"v11/current/null do not share one MC ballot: {ballots}")
    except Exception as exc:
        problems.append(f"ballot preflight failed: {type(exc).__name__}: {exc}")
    return sorted(set(problems))


def _expected_n(label: str, side: str) -> int | None:
    if side == "opp" or label in {"null", "reference"}:
        return 30
    if label == "arm" and side == "arm":
        return None
    raise ProtocolRefused(f"unsupported label/side {label}/{side}")


def _counter_problems(label: str, side: str, counters: object) -> list[str]:
    prefix = f"{label}/{side}"
    if not isinstance(counters, dict) or set(counters) != set(COUNTER_FIELDS):
        return [f"{prefix}: counter fields mismatch"]
    problems = []
    for field in INTEGER_COUNTER_FIELDS:
        value = counters[field]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            problems.append(f"{prefix}: malformed {field}")
    seconds = counters["search_secs"]
    if (isinstance(seconds, bool) or not isinstance(seconds, (int, float))
            or not math.isfinite(float(seconds)) or seconds < 0):
        problems.append(f"{prefix}: malformed search_secs")
    if problems:
        return problems

    expected_n = _expected_n(label, side)
    if expected_n is None:
        nonzero = [field for field in COUNTER_FIELDS if counters[field] != 0]
        if nonzero:
            problems.append(
                f"{prefix}: direct v11 arm unexpectedly searched: {nonzero}")
        return problems

    attempts = counters["sample_attempts"]
    accepted = counters["accepted_worlds"]
    failed = counters["failed_worlds"]
    searches = counters["searches"]
    if attempts != accepted + failed:
        problems.append(f"{prefix}: sampler counters do not reconcile")
    if accepted != expected_n * searches:
        problems.append(
            f"{prefix}: accepted dose {accepted} != {expected_n}*{searches}")
    if attempts != accepted:
        problems.append(f"{prefix}: attempts include a failed sampled world")
    for field in FORBIDDEN_COUNTER_FIELDS:
        if counters[field] != 0:
            problems.append(f"{prefix}: nonzero {field}")
    if searches and counters["rollouts"] <= 0:
        problems.append(f"{prefix}: searches consumed no candidate rollouts")
    return problems


def record_problems(records: object, *, seed0: int,
                    clusters: int) -> list[str]:
    """Validate exact paired coverage and every accepted N=30 dose."""
    if not isinstance(records, dict) or set(records) != set(LABELS):
        return ["record labels differ from frozen labels"]
    expected_keys = {
        (seed, flip) for seed in range(seed0, seed0 + clusters)
        for flip in (0, 1)
    }
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
            seed, flip = row.get("seed"), row.get("flip")
            keys.append((seed, flip))
            won, utility = row.get("won"), row.get("level_utility")
            if (isinstance(seed, bool) or not isinstance(seed, int)
                    or isinstance(flip, bool) or flip not in (0, 1)
                    or isinstance(won, bool) or won not in (0, 1)
                    or isinstance(utility, bool) or not isinstance(utility, int)
                    or utility not in {-3, -2, -1, 1, 2, 3}
                    or (utility > 0) != bool(won)):
                problems.append(f"{label}: malformed outcome record")
            if row.get("label") != label \
                    or row.get("policy") != LABELS[label]:
                problems.append(f"{label}: row policy/label identity drift")
            for side in ("arm", "opp"):
                problems += _counter_problems(label, side, row.get(side))
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


def accepted_dose_summary(records: dict[str, list]) -> dict:
    totals = counter_totals(records)
    cells = {}
    for label in LABELS:
        cells[label] = {}
        for side in ("arm", "opp"):
            expected_n = _expected_n(label, side)
            counters = totals[label][side]
            expected = (0 if expected_n is None
                        else expected_n * counters["searches"])
            cells[label][side] = {
                "policy_kind": "direct_no_search" if expected_n is None else
                               "mc_n30",
                "searches": counters["searches"],
                "accepted_worlds": counters["accepted_worlds"],
                "expected_accepted_worlds": expected,
                "exact": counters["accepted_worlds"] == expected,
            }
    return {
        "schema": "v11-current-accepted-dose-v2",
        "cells": cells,
        "all": all(cell["exact"] for sides in cells.values()
                   for cell in sides.values()),
    }


def _contrast(records: dict[str, list], a: str, b: str) -> dict:
    mean, half, clusters = paired_by_seed(records[a], records[b])
    return {
        "a": a, "b": b, "mean": mean,
        "half_width_95": half, "clusters": clusters,
    }


def all_contrasts(records: dict[str, list]) -> dict:
    return {
        "arm-reference": _contrast(records, "arm", "reference"),
        "arm-null": _contrast(records, "arm", "null"),
        "null-reference": _contrast(records, "null", "reference"),
    }


def gate_criteria(stats: dict, accepted_dose: dict) -> dict[str, bool]:
    arm_ref = stats["arm-reference"]
    arm_null = stats["arm-null"]
    null_ref = stats["null-reference"]
    criteria = {
        "v11_current_lcb_gt_0": (
            arm_ref["mean"] - arm_ref["half_width_95"] > 0),
        "v11_null_lcb_gt_0": (
            arm_null["mean"] - arm_null["half_width_95"] > 0),
        "null_current_interval_contains_0": (
            abs(null_ref["mean"]) <= null_ref["half_width_95"]),
        "exact_accepted_dose": accepted_dose.get("all") is True,
    }
    criteria["all"] = all(criteria.values())
    return criteria


def run_shard(args) -> None:
    _, runtime = require_runtime()
    if not 0 <= args.shard_index < SHARD_COUNT:
        raise ProtocolRefused(f"shard-index must satisfy 0 <= i < {SHARD_COUNT}")
    problems = protocol_problems()
    if problems:
        raise ProtocolRefused(
            "v11 v2 protocol drift:\n  - " + "\n  - ".join(problems))
    head = git("rev-parse", "HEAD")
    dirty = git("status", "--porcelain")
    if dirty and not args.smoke:
        raise ProtocolRefused("full v11 v2 shard refuses a dirty tree")

    clusters = 2 if args.smoke else CLUSTERS_PER_SHARD
    shard_seed0 = SEED0 + args.shard_index * CLUSTERS_PER_SHARD
    run_id = (
        f"{SCHEMA}_shard{args.shard_index:02d}_{head[:10]}" +
        ("_SMOKE" if args.smoke else "")
    )
    out = Path(args.out or f"runs/logs/{run_id}.jsonl")
    manifest_path = Path(str(out) + ".manifest.json")
    records_partial = Path(str(out) + ".partial")
    manifest_partial = Path(str(manifest_path) + ".partial")
    for path in (
            out, records_partial, manifest_path, manifest_partial,
            Path(str(out) + ".FAILED"),
            Path(str(manifest_path) + ".FAILED")):
        if path.exists():
            raise ProtocolRefused(f"refusing to overwrite {path}")
    out.parent.mkdir(parents=True, exist_ok=True)

    manifest = {
        "schema": SCHEMA,
        "claim": CLAIM,
        "claim_boundary": SHARD_CLAIM_BOUNDARY,
        "run_id": run_id,
        "evidence_grade": not args.smoke,
        "production_promotion": False,
        "score_blind_progress": True,
        "shard_statistics_persisted": False,
        "git_sha": head,
        "tree_dirty": bool(dirty),
        "dirty_files": dirty.splitlines() if dirty else [],
        **runtime,
        "invalidated_v1": INVALIDATED_V1,
        "shard_index": args.shard_index,
        "shard_count": SHARD_COUNT,
        "total_clusters": TOTAL_CLUSTERS,
        "clusters": clusters,
        "seed0": shard_seed0,
        "seed_hi": shard_seed0 + clusters - 1,
        "opponent": OPPONENT,
        "labels": LABELS,
        "checkpoint": str(CHECKPOINT.relative_to(SERVER)),
        "checkpoint_sha256": CHECKPOINT_SHA256,
        "selection_rule": SELECTION_RULE,
        "policy_contracts": {
            name: policy_contract(name) for name in LABELS.values()},
        "ballots": arm_ballots(LABELS.values()),
        "started": time.strftime("%Y-%m-%d %H:%M:%S %Z"),
    }
    with manifest_partial.open("x") as fh:
        json.dump(manifest, fh, indent=2, sort_keys=True)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())

    records = {}
    with records_partial.open("x") as fh:
        for label, policy in LABELS.items():
            print(f"\n{label}: {policy} vs {OPPONENT}", flush=True)
            records[label] = run_arm(
                label, policy, OPPONENT, clusters, shard_seed0, fh, run_id,
                progress_scores=False)
        fh.flush()
        os.fsync(fh.fileno())

    problems = record_problems(
        records, seed0=shard_seed0, clusters=clusters)
    manifest.update({
        "records_sha256": sha256(records_partial),
        "record_counts": {label: len(rows)
                          for label, rows in records.items()},
        "counter_totals": counter_totals(records),
        "accepted_dose": accepted_dose_summary(records),
        "completed": time.strftime("%Y-%m-%d %H:%M:%S %Z"),
        "problems": problems,
        "complete": not problems,
    })
    with manifest_partial.open("w") as fh:
        json.dump(manifest, fh, indent=2, sort_keys=True)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    suffix = "" if not problems else ".FAILED"
    publish_partial_exclusive(records_partial, Path(str(out) + suffix))
    publish_partial_exclusive(
        manifest_partial, Path(str(manifest_path) + suffix))
    if problems:
        raise ProtocolRefused(
            "v11 v2 shard failed closed:\n  - " + "\n  - ".join(problems))
    print(f"\nrecords: {out}\nmanifest: {manifest_path}")


def load_population(pattern: str):
    paths = [Path(raw).resolve() for raw in sorted(glob.glob(pattern))]
    if len(paths) != SHARD_COUNT or len(set(paths)) != SHARD_COUNT:
        raise ProtocolRefused(
            f"pattern resolved {len(paths)} unique manifests, expected 8")
    manifests = []
    records: dict[str, list] = {}
    for path in paths:
        try:
            manifest = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise ProtocolRefused(f"manifest unreadable: {path}: {exc}") from exc
        if (not isinstance(manifest, dict)
                or manifest.get("schema") != SCHEMA
                or manifest.get("evidence_grade") is not True):
            raise ProtocolRefused(f"unexpected/non-evidence manifest: {path}")
        record_path = Path(str(path).removesuffix(".manifest.json"))
        if not record_path.is_file():
            raise ProtocolRefused(f"manifest has no records: {path}")
        if sha256(record_path) != manifest.get("records_sha256"):
            raise ProtocolRefused(f"record digest drift for {record_path}")
        manifests.append((path, manifest))
        try:
            for line in record_path.read_text().splitlines():
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError("record is not a mapping")
                row["_source"] = str(record_path)
                records.setdefault(row.get("label"), []).append(row)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            raise ProtocolRefused(
                f"records unreadable: {record_path}: {exc}") from exc
    return manifests, records


def _manifest_runtime(manifest: dict) -> dict:
    return {key: manifest.get(key) for key in (
        "host", "python", "fast_engine", "require_voids",
        "experimental_sampler_flags", "encoder_contract", "digests",
    )}


def validate_population(manifests, records, current_runtime: dict,
                        current_head: str) -> list[str]:
    problems = []
    try:
        expected_contracts = {
            name: policy_contract(name) for name in LABELS.values()}
        expected_ballots = arm_ballots(LABELS.values())
    except Exception as exc:
        problems.append(
            f"current policy preflight failed: {type(exc).__name__}: {exc}")
        expected_contracts = expected_ballots = None
    if len(manifests) != SHARD_COUNT:
        problems.append(f"found {len(manifests)} shards, expected 8")
    indices = [manifest.get("shard_index") for _, manifest in manifests]
    valid_indices = [i for i in indices
                     if isinstance(i, int) and not isinstance(i, bool)]
    if sorted(valid_indices) != list(range(8)):
        problems.append(f"shard indices are {indices}")
    invariant_fields = (
        "schema", "claim", "claim_boundary", "git_sha", "host", "python",
        "fast_engine", "require_voids", "experimental_sampler_flags",
        "encoder_contract", "digests", "invalidated_v1", "labels",
        "ballots", "policy_contracts", "checkpoint_sha256",
        "selection_rule", "shard_count", "total_clusters", "opponent",
        "score_blind_progress", "shard_statistics_persisted",
    )
    for field in invariant_fields:
        values = {stable_digest(manifest.get(field))
                  for _, manifest in manifests}
        if len(values) > 1:
            problems.append(f"shards disagree on {field}")

    run_by_source = {}
    for path, manifest in manifests:
        record_path = str(path).removesuffix(".manifest.json")
        run_by_source[record_path] = manifest.get("run_id")
        if (manifest.get("complete") is not True or manifest.get("problems")
                or manifest.get("tree_dirty")
                or manifest.get("evidence_grade") is not True):
            problems.append(f"incomplete/dirty/non-evidence manifest {path}")
        if manifest.get("git_sha") != current_head:
            problems.append(f"{path}: git SHA differs from verifier")
        if _manifest_runtime(manifest) != current_runtime:
            problems.append(f"{path}: runtime differs from verifier")
        if manifest.get("encoder_contract") != EXPECTED_ENCODER_CONTRACT:
            problems.append(f"{path}: corrected encoder boundary drifted")
        if (manifest.get("schema") != SCHEMA
                or manifest.get("claim") != CLAIM
                or manifest.get("claim_boundary") != SHARD_CLAIM_BOUNDARY
                or manifest.get("invalidated_v1") != INVALIDATED_V1):
            problems.append(f"{path}: claim/v1 invalidation drifted")
        if (manifest.get("labels") != LABELS
                or manifest.get("opponent") != OPPONENT
                or manifest.get("checkpoint_sha256") != CHECKPOINT_SHA256
                or manifest.get("selection_rule") != SELECTION_RULE
                or manifest.get("shard_count") != SHARD_COUNT
                or manifest.get("total_clusters") != TOTAL_CLUSTERS):
            problems.append(f"{path}: frozen protocol identity drifted")
        if expected_contracts is not None \
                and manifest.get("policy_contracts") != expected_contracts:
            problems.append(f"{path}: policy contracts differ from verifier")
        if expected_ballots is not None \
                and manifest.get("ballots") != expected_ballots:
            problems.append(f"{path}: ballots differ from verifier")
        if manifest.get("production_promotion") is not False:
            problems.append(f"{path}: production authorization is forbidden")
        if manifest.get("score_blind_progress") is not True \
                or manifest.get("shard_statistics_persisted") is not False \
                or "stats" in manifest:
            problems.append(f"{path}: shard was not score-blind")
        index = manifest.get("shard_index")
        if isinstance(index, int) and not isinstance(index, bool):
            want = SEED0 + index * CLUSTERS_PER_SHARD
            if (manifest.get("seed0") != want
                    or manifest.get("seed_hi") !=
                    want + CLUSTERS_PER_SHARD - 1):
                problems.append(f"shard {index}: seed block drifted")
        if manifest.get("clusters") != CLUSTERS_PER_SHARD:
            problems.append(f"{path}: cluster count drifted")
        source_rows = [row for rows in records.values() for row in rows
                       if row.get("_source") == record_path]
        manifest_seed0 = manifest.get("seed0")
        if isinstance(manifest_seed0, int) and not isinstance(
                manifest_seed0, bool):
            expected_source_keys = {
                (seed, flip)
                for seed in range(
                    manifest_seed0, manifest_seed0 + CLUSTERS_PER_SHARD)
                for flip in (0, 1)
            }
        else:
            expected_source_keys = set()
            problems.append(f"{path}: malformed shard seed0")
        record_counts = manifest.get("record_counts")
        if not isinstance(record_counts, dict):
            record_counts = {}
            problems.append(f"{path}: record counts are malformed")
        for label in LABELS:
            label_rows = [row for row in source_rows
                          if row.get("label") == label]
            keys = {(row.get("seed"), row.get("flip"))
                    for row in label_rows}
            if keys != expected_source_keys:
                problems.append(f"{path}: {label} shard-local coverage drifted")
            if record_counts.get(label) != len(label_rows):
                problems.append(f"{path}: {label} record count drifted")

    if set(records) != set(LABELS):
        problems.append("population record labels drifted")
    for label, rows in records.items():
        for row in rows:
            if row.get("run") != run_by_source.get(row.get("_source")):
                problems.append(f"{label}: record/run identity drifted")
    problems += record_problems(
        records, seed0=SEED0, clusters=TOTAL_CLUSTERS)
    if not problems:
        expected_dose = accepted_dose_summary(records)
        for path, manifest in manifests:
            record_path = str(path).removesuffix(".manifest.json")
            local = {
                label: [row for row in rows
                        if row.get("_source") == record_path]
                for label, rows in records.items()
            }
            if manifest.get("accepted_dose") != accepted_dose_summary(local):
                problems.append(f"{path}: accepted-dose summary drifted")
            if manifest.get("counter_totals") != counter_totals(local):
                problems.append(f"{path}: counter totals drifted")
        if expected_dose.get("all") is not True:
            problems.append("population did not consume exact accepted dose")
    problems += protocol_problems()
    return sorted(set(problems))


def aggregate(args) -> None:
    _, runtime = require_runtime()
    if git("status", "--porcelain"):
        raise ProtocolRefused("v11 v2 aggregate refuses a dirty verifier tree")
    head = git("rev-parse", "HEAD")
    manifests, records = load_population(args.pattern)
    problems = validate_population(manifests, records, runtime, head)
    if problems:
        raise ProtocolRefused(
            "v11 v2 aggregation refused:\n  - " + "\n  - ".join(problems))
    stats = all_contrasts(records)
    dose = accepted_dose_summary(records)
    criteria = gate_criteria(stats, dose)
    aggregate_dir = Path(args.out).resolve().parent

    def evidence_path(path: os.PathLike | str) -> str:
        return os.path.relpath(Path(path).resolve(), aggregate_dir)

    result = {
        "schema": AGGREGATE_SCHEMA,
        "claim": CLAIM,
        "complete": True,
        "git_sha": head,
        "runtime_identity": runtime,
        "encoder_contract": EXPECTED_ENCODER_CONTRACT,
        "invalidated_v1": INVALIDATED_V1,
        "clusters": TOTAL_CLUSTERS,
        "seed0": SEED0,
        "seed_hi": SEED_HI,
        "labels": LABELS,
        "checkpoint_sha256": CHECKPOINT_SHA256,
        "selection_rule": SELECTION_RULE,
        "input_shards": [
            {
                "manifest_path": evidence_path(path),
                "manifest_sha256": sha256(path),
                "records_path": evidence_path(
                    str(path).removesuffix(".manifest.json")),
                "records_sha256": manifest["records_sha256"],
                "shard_index": manifest["shard_index"],
            }
            for path, manifest in sorted(
                manifests, key=lambda item: item[1]["shard_index"])
        ],
        "record_counts": {
            label: len(rows) for label, rows in records.items()},
        "counter_totals": counter_totals(records),
        "accepted_dose": dose,
        "stats": stats,
        "criteria": criteria,
        "checkpoint_compatible_with_restored_v1": criteria["all"],
        "protected_composition_authorized": False,
        "production_promotion": False,
        "claim_boundary": (
            "A pass establishes only that frozen ep07 direct override remains "
            "compatible under restored historical encoder-v1 semantics on "
            "this population. It does not rehabilitate the drifted 121M "
            "artifact, test private-kitty input, protected composition, "
            "multi-round progression or production deployment."
        ),
    }
    write_exclusive_atomic(args.out, result)
    print(json.dumps(result, indent=2, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("--shard-index", type=int, required=True)
    run.add_argument("--smoke", action="store_true")
    run.add_argument("--out")
    agg = sub.add_parser("aggregate")
    agg.add_argument(
        "--pattern",
        default="runs/logs/v11-current-revalidation-v2_*.manifest.json")
    agg.add_argument("--out", required=True)
    args = parser.parse_args()
    if args.command == "run":
        run_shard(args)
    else:
        aggregate(args)


if __name__ == "__main__":
    try:
        main()
    except ProtocolRefused as exc:
        print(f"REFUSING: {exc}", file=sys.stderr)
        raise SystemExit(3) from exc
