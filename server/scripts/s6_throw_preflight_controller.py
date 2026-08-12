#!/usr/bin/env python3
"""Freeze and execute the score-free S6 whole-round capacity preflight.

Authority is deliberately split:

1. the exact S6 source semantics must have an independent PASS;
2. this controller freezes a deterministic packet;
3. an independent packet review may authorize one four-cluster preflight;
4. only a later capacity-result review may authorize screen-packet design.

The preflight plays real rounds in memory but serializes no score, points,
winner, utility, action, or per-round row.  It publishes only work, sampler,
source-trigger, timing, and capacity totals.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import secrets
import stat
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

import s6_throw_duel as CORE  # noqa: E402
from shengji.ai.throw_policy import (  # noqa: E402
    S6_THROW_COUNTER_FIELDS, make_s6_throw_bot)
from shengji.ai.throw_sourcing import MAX_CANDIDATES, SCHEMA as SOURCE_SCHEMA  # noqa: E402
from shengji.engine import combos, fast  # noqa: E402
from shengji.engine.ballot import mc_ballot  # noqa: E402


PACKET_SCHEMA = "s6-throw-capacity-packet-v2"
ADMISSION_SCHEMA = "s6-throw-capacity-admission-v2"
RESULT_SCHEMA = "s6-throw-capacity-result-v2"
RUN_ID = "s6-throw-screen-310b-v2"
PREFLIGHT_RUN_ID = "s6-throw-preflight-309b-v2"
SOURCE_GIT = "c78a2d8951fbd75d05b2aa718168bc609104fd4a"
SOURCE_REVIEW_PREFIX = "S6_THROW_SOURCE_V2_REVIEW "
PACKET_REVIEW_PREFIX = "S6_THROW_PREFLIGHT_PACKET_V2_REVIEW "
CAPACITY_REVIEW_PREFIX = "S6_THROW_CAPACITY_V2_REVIEW "
EXPECTED_EXECUTION_HOST = "Jerrys-MacBook-Air.local"
EXPECTED_PYTHON_VERSION = "3.14.6"
EXPECTED_PYTHON_IMPLEMENTATION = "CPython"
EXPECTED_PYTHON_EXECUTABLE = (
    "/Users/jerryyu/.local/share/uv/python/"
    "cpython-3.14.6-macos-aarch64-none/bin/python3.14")
EXPECTED_FAST_BINARY_SHA256 = (
    "9c9e77fbdc4c6caceec195465155f37ec6369e409462fd838bc142bf8a0be4c1")
PREFLIGHT_SEED0 = 309_000_000_000
PREFLIGHT_CLUSTERS = 4
SCREEN_SEED0 = 310_000_000_000
SCREEN_CLUSTERS = 2_048
SHARD_COUNT = 8
STREAM_STRIDE = 3_000_017
SAFETY_FACTOR = 2.0
SCREEN_FLEET_HOUR_CAP = 384.0
SCREEN_MAX_SHARD_HOUR_CAP = 48.0
RUN_LOG_DIR = SERVER / "runs/logs" / PREFLIGHT_RUN_ID
ADMISSION_PATH = SERVER / "runs/locks" / \
    f"{PREFLIGHT_RUN_ID}.admission.consumed.json"
RESULT_PATH = RUN_LOG_DIR / "capacity.json"

EXPECTED_SOURCE_REVIEW = {
    "equal_work_screen_design_authorized": True,
    "git": SOURCE_GIT,
    "independent_review": True,
    "merge_authorized": False,
    "production_deployment": False,
    "run_authorized": False,
    "schema": "s6-throw-source-v2-review",
    "strength_claim": False,
    "verdict": "PASS",
}
FORBIDDEN_SCORE_KEYS = frozenset({
    "banker", "attacker_points", "winner_team", "level_change", "won",
    "level_utility", "utility", "winner", "points", "records", "outcomes",
})


class ControllerRefused(RuntimeError):
    """The requested action lacks exact identity, capacity, or authority."""


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
        ["git", *args], cwd=REPO, check=True, capture_output=True, text=True,
    ).stdout.strip()


def git_is_ancestor(ancestor: str, descendant: str) -> bool:
    return subprocess.run(
        ["git", "merge-base", "--is-ancestor", ancestor, descendant],
        cwd=REPO, capture_output=True, text=True,
    ).returncode == 0


def write_exclusive(path: os.PathLike | str, payload: dict) -> None:
    final = Path(path)
    partial = Path(str(final) + ".partial")
    if os.path.lexists(final) or os.path.lexists(partial):
        raise ControllerRefused(f"refusing to overwrite {final} or {partial}")
    final.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(payload, sort_keys=True, separators=(",", ":"))
           + "\n").encode()
    with partial.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    if json.loads(partial.read_bytes()) != payload:
        raise ControllerRefused("exclusive partial failed exact reopen")
    os.link(partial, final)
    partial.unlink()
    if final.read_bytes() != raw:
        raise ControllerRefused("published artifact differs from candidate")


def require_regular_unlinked(path: Path, *, label: str) -> None:
    partial = Path(str(path) + ".partial")
    try:
        info = path.lstat()
    except FileNotFoundError as exc:
        raise ControllerRefused(f"{label} is missing") from exc
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or os.path.lexists(partial)):
        raise ControllerRefused(f"{label} is linked, nonregular, or partial")


def source_paths() -> dict[str, Path]:
    if not fast.HAVE_FAST or fast._fast is None:
        raise ControllerRefused("compiled fast binary is unavailable")
    return {
        "controller": SCRIPT,
        "duel_core": SERVER / "scripts/s6_throw_duel.py",
        "throw_policy": SERVER / "shengji/ai/throw_policy.py",
        "throw_source": SERVER / "shengji/ai/throw_sourcing.py",
        "evaluation": SERVER / "shengji/evaluation.py",
        "registry": SERVER / "shengji/ai/registry.py",
        "mcbot": SERVER / "shengji/ai/mcbot.py",
        "memory": SERVER / "shengji/ai/memory.py",
        "env": SERVER / "shengji/ai/env.py",
        "game": SERVER / "shengji/engine/game.py",
        "round": SERVER / "shengji/engine/round.py",
        "fast_binary": Path(fast._fast.__file__).resolve(),
    }


def source_sha256s() -> dict[str, str]:
    return {name: sha256(path) for name, path in source_paths().items()}


def runtime_snapshot() -> dict[str, str | bool]:
    if not fast.HAVE_FAST or fast._fast is None:
        raise ControllerRefused("compiled fast binary is unavailable")
    fast_binary = Path(fast._fast.__file__).resolve()
    return {
        "host": platform.node(),
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "python_executable": str(Path(sys.executable).resolve()),
        "fast_required": True,
        "strict_voids_required": True,
        "fast_binary_sha256": sha256(fast_binary),
    }


def runtime_problems(runtime: object) -> list[str]:
    if not isinstance(runtime, dict):
        return ["runtime is not an object"]
    expected = {
        "host": EXPECTED_EXECUTION_HOST,
        "python": EXPECTED_PYTHON_VERSION,
        "implementation": EXPECTED_PYTHON_IMPLEMENTATION,
        "python_executable": EXPECTED_PYTHON_EXECUTABLE,
        "fast_required": True,
        "strict_voids_required": True,
        "fast_binary_sha256": EXPECTED_FAST_BINARY_SHA256,
    }
    return [] if runtime == expected else ["runtime is not exact Air"]


def require_air_runtime() -> dict[str, str | bool]:
    runtime = runtime_snapshot()
    problems = runtime_problems(runtime)
    if problems:
        raise ControllerRefused("; ".join(problems))
    return runtime


def _uppercase_contract(bot) -> dict[str, bool | int | float | str | None]:
    values = {}
    for name in dir(bot):
        if not name.isupper():
            continue
        value = getattr(bot, name)
        if not isinstance(value, (bool, int, float, str, type(None))):
            raise ControllerRefused(f"non-serializable policy knob {name}")
        values[name] = value
    return values


def policy_contracts() -> dict[str, dict]:
    treatment = make_s6_throw_bot(treatment=True, seed=7)
    null = make_s6_throw_bot(treatment=False, seed=7)
    champion = CORE.make_arm("champion", 7)
    if _uppercase_contract(treatment) != _uppercase_contract(null) \
            or _uppercase_contract(treatment) != _uppercase_contract(champion):
        raise ControllerRefused("S6 arms do not inherit one champion contract")
    return {
        "champion": {
            "policy": CORE.LABELS["champion"],
            "class": type(champion).__name__,
            "uppercase": _uppercase_contract(champion),
            "root_ballot_digest": mc_ballot(champion).digest,
            "s6_mode": "off",
        },
        "treatment": {
            "policy": CORE.LABELS["treatment"],
            "class": type(treatment).__name__,
            "uppercase": _uppercase_contract(treatment),
            "root_ballot_digest": mc_ballot(treatment).digest,
            "s6_mode": treatment.s6_throw_mode,
        },
        "matched_null": {
            "policy": CORE.LABELS["matched_null"],
            "class": type(null).__name__,
            "uppercase": _uppercase_contract(null),
            "root_ballot_digest": mc_ballot(null).digest,
            "s6_mode": null.s6_throw_mode,
        },
    }


def parse_marker(path: os.PathLike | str, prefix: str,
                 expected: dict, *, label: str) -> dict:
    source = Path(path)
    require_regular_unlinked(source, label=label)
    matches = [line for line in source.read_text(encoding="utf-8").splitlines()
               if line.startswith(prefix)]
    if len(matches) != 1:
        raise ControllerRefused(f"{label} must contain exactly one marker")
    try:
        payload = json.loads(matches[0][len(prefix):])
    except ValueError as exc:
        raise ControllerRefused(f"{label} marker is malformed") from exc
    if payload != expected:
        raise ControllerRefused(f"{label} marker payload drift")
    return {"sha256": sha256(source), "marker": matches[0], "payload": payload}


def packet_payload(*, expected_git: str,
                   source_review_record: os.PathLike | str) -> dict:
    review = parse_marker(
        source_review_record, SOURCE_REVIEW_PREFIX, EXPECTED_SOURCE_REVIEW,
        label="S6 source review record")
    if not git_is_ancestor(SOURCE_GIT, expected_git):
        raise ControllerRefused("S6 source is not an ancestor")
    payload = {
        "schema": PACKET_SCHEMA,
        "run_id": RUN_ID,
        "preflight_run_id": PREFLIGHT_RUN_ID,
        "git": expected_git,
        "source_git": SOURCE_GIT,
        "source_review": review,
        "source_sha256s": source_sha256s(),
        "runtime": require_air_runtime(),
        "source_contract": {
            "schema": SOURCE_SCHEMA,
            "max_added_candidates": MAX_CANDIDATES,
            "append_only": True,
            "candidate_zero_preserved": True,
            "tractor_lock_isolation": "candidate_zero_vs_s6_suffix_only",
            "experiment_seam": (
                "literal_champion_then_equal_probe_with_champion_rng_restore"),
        },
        "policy_contracts": policy_contracts(),
        "preflight": {
            "seed0": PREFLIGHT_SEED0,
            "clusters": PREFLIGHT_CLUSTERS,
            "labels": list(CORE.LABEL_ORDER),
            "score_free": True,
            "outcomes_published": False,
            "admission_path": str(ADMISSION_PATH.relative_to(REPO)),
            "result_path": str(RESULT_PATH.relative_to(REPO)),
        },
        "screen": {
            "seed0": SCREEN_SEED0,
            "clusters": SCREEN_CLUSTERS,
            "shards": SHARD_COUNT,
            "clusters_per_shard": SCREEN_CLUSTERS // SHARD_COUNT,
            "stream_stride": STREAM_STRIDE,
            "labels": list(CORE.LABEL_ORDER),
            "selection_rule": (
                "LCB95(treatment-champion)>0 and "
                "LCB95(treatment-matched_null)>0 with exact null/champion "
                "outcomes, both-role triggers, exact S6 dose and exact work"),
        },
        "capacity": {
            "safety_factor": SAFETY_FACTOR,
            "screen_fleet_hour_cap": SCREEN_FLEET_HOUR_CAP,
            "screen_max_shard_hour_cap": SCREEN_MAX_SHARD_HOUR_CAP,
        },
        "authority": {
            "preflight_execution_authorized": False,
            "screen_packet_design_authorized": False,
            "screen_execution_authorized": False,
            "strength_claim": False,
            "production_promotion": False,
            "production_deployment": False,
        },
    }
    payload["internal_sha256"] = stable_digest(payload)
    return payload


def packet_problems(payload: object, *, expected_git: str,
                    source_review_record: os.PathLike | str) -> list[str]:
    try:
        expected = packet_payload(
            expected_git=expected_git,
            source_review_record=source_review_record)
    except Exception as exc:
        return [f"cannot reconstruct packet: {type(exc).__name__}: {exc}"]
    return [] if payload == expected else ["packet differs from reconstruction"]


def load_packet(path: os.PathLike | str, expected_sha256: str, *,
                expected_git: str,
                source_review_record: os.PathLike | str) -> dict:
    source = Path(path)
    require_regular_unlinked(source, label="S6 capacity packet")
    if sha256(source) != expected_sha256:
        raise ControllerRefused("S6 packet SHA-256 drift")
    try:
        payload = json.loads(source.read_bytes())
    except (OSError, ValueError) as exc:
        raise ControllerRefused("S6 packet is unreadable") from exc
    problems = packet_problems(
        payload, expected_git=expected_git,
        source_review_record=source_review_record)
    if problems:
        raise ControllerRefused("invalid S6 packet: " + "; ".join(problems))
    return payload


def packet_review_claim(*, expected_git: str,
                        packet_sha256: str) -> dict:
    return {
        "git": expected_git,
        "independent_review": True,
        "one_score_free_preflight_authorized": True,
        "packet_sha256": packet_sha256,
        "production_deployment": False,
        "production_promotion": False,
        "run_id": RUN_ID,
        "schema": "s6-throw-preflight-packet-review-v2",
        "screen_execution_authorized": False,
        "strength_claim": False,
        "verdict": "PASS",
    }


def capacity_review_claim(*, result: dict, result_sha256: str,
                          packet_sha256: str) -> dict:
    """Exact marker a reviewer may append after authenticating capacity."""
    projection = result["projection"]
    passed = result.get("capacity_pass") is True
    return {
        "capacity_pass": passed,
        "capacity_result_internal_sha256": result["internal_sha256"],
        "capacity_result_sha256": result_sha256,
        "elapsed_seconds": result["elapsed_seconds"],
        "git": result["git"],
        "independent_review": True,
        "one_screen_packet_design_authorized": passed,
        "packet_sha256": packet_sha256,
        "preflight_clusters": PREFLIGHT_CLUSTERS,
        "production_deployment": False,
        "production_promotion": False,
        "run_id": RUN_ID,
        "schema": "s6-throw-capacity-review-v2",
        "score_free": True,
        "screen_execution_authorized": False,
        "screen_fleet_hours": projection["screen_fleet_hours"],
        "screen_max_shard_hours": projection["screen_max_shard_hours"],
        "strength_claim": False,
        "verdict": "PASS" if passed else "HOLD",
    }


def score_free_result_problems(value: object) -> list[str]:
    problems = []

    def walk(item, path: str) -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                if key in FORBIDDEN_SCORE_KEYS:
                    problems.append(f"forbidden score field {path}{key}")
                walk(child, f"{path}{key}.")
        elif isinstance(item, list):
            for index, child in enumerate(item):
                walk(child, f"{path}{index}.")

    walk(value, "")
    if not isinstance(value, dict) \
            or value.get("score_free") is not True \
            or value.get("outcomes_published") is not False:
        problems.append("score-free identity")
    return sorted(set(problems))


def _sum_plain_counters(records: list[dict], side: str) -> dict:
    names = set(CORE.counters([]))
    totals = {name: 0.0 if name == "search_secs" else 0 for name in names}
    for record in records:
        for name in names:
            totals[name] += record[side][name]
    totals["search_secs"] = round(float(totals["search_secs"]), 4)
    return totals


def _sum_s6(records: list[dict], side: str) -> dict:
    modes = {record[side]["s6_throw"]["mode"] for record in records}
    if len(modes) != 1:
        raise ControllerRefused("S6 preflight telemetry mode drift")
    totals = Counter({field: 0 for field in S6_THROW_COUNTER_FIELDS})
    for record in records:
        totals.update({field: record[side]["s6_throw"][field]
                       for field in S6_THROW_COUNTER_FIELDS})
    return {"mode": next(iter(modes)),
            **{field: int(totals[field]) for field in S6_THROW_COUNTER_FIELDS}}


def measure_preflight(packet: dict, *, clock=time.perf_counter) -> dict:
    """Run real gameplay and return only outcome-free capacity telemetry."""
    started = clock()
    by_label = {label: [] for label in CORE.LABEL_ORDER}
    for cluster_index in range(PREFLIGHT_CLUSTERS):
        seed = PREFLIGHT_SEED0 + STREAM_STRIDE * cluster_index
        for label in CORE.LABEL_ORDER:
            records = CORE.play_arm_cluster(
                label, seed, run_id=PREFLIGHT_RUN_ID)
            for flip, record in enumerate(records):
                problems = CORE.record_problems(
                    record, expected_label=label, expected_seed=seed,
                    expected_flip=flip, expected_run_id=PREFLIGHT_RUN_ID)
                if problems:
                    raise ControllerRefused(
                        f"invalid score-free preflight row: {'; '.join(problems)}")
            by_label[label].extend(records)
        print(json.dumps({
            "event": "s6-throw-score-free-progress-v1",
            "clusters_complete": cluster_index + 1,
            "clusters_total": PREFLIGHT_CLUSTERS,
        }, sort_keys=True), flush=True)
    elapsed = clock() - started
    if not math.isfinite(elapsed) or elapsed <= 0:
        raise ControllerRefused("S6 preflight elapsed time is invalid")

    counts = {
        label: {
            "records_discarded": len(records),
            "arm": _sum_plain_counters(records, "arm"),
            "opp": _sum_plain_counters(records, "opp"),
            "arm_s6": _sum_s6(records, "arm"),
            "opp_s6": _sum_s6(records, "opp"),
        }
        for label, records in by_label.items()
    }
    for records in by_label.values():
        for record in records:
            mode = ({"treatment": "treatment",
                     "matched_null": "matched_null",
                     "champion": "off"}[record["label"]])
            if CORE.counter_problems(record["arm"], expected_mode=mode) \
                    or CORE.counter_problems(record["opp"], expected_mode="off"):
                raise ControllerRefused("S6 preflight exact-work validation failed")

    arm_clusters_measured = PREFLIGHT_CLUSTERS * len(CORE.LABEL_ORDER)
    target_arm_clusters = SCREEN_CLUSTERS * len(CORE.LABEL_ORDER)
    fleet_hours = (elapsed / arm_clusters_measured * target_arm_clusters
                   * SAFETY_FACTOR / 3_600.0)
    max_shard_hours = fleet_hours / SHARD_COUNT
    treatment = counts["treatment"]["arm_s6"]
    null = counts["matched_null"]["arm_s6"]
    capacity_pass = (
        treatment["searched_triggers"] > 0
        and null["searched_triggers"] > 0
        and treatment["short_searches"] == 0
        and null["short_searches"] == 0
        and null["matched_noops"] == null["searched_triggers"]
        and null["treatment_overrides"] == 0
        and fleet_hours <= SCREEN_FLEET_HOUR_CAP
        and max_shard_hours <= SCREEN_MAX_SHARD_HOUR_CAP)
    result = {
        "schema": RESULT_SCHEMA,
        "run_id": RUN_ID,
        "preflight_run_id": PREFLIGHT_RUN_ID,
        "git": packet["git"],
        "packet_internal_sha256": packet["internal_sha256"],
        "score_free": True,
        "outcomes_published": False,
        "records_discarded": sum(
            value["records_discarded"] for value in counts.values()),
        "elapsed_seconds": elapsed,
        "counts": counts,
        "projection": {
            "safety_factor": SAFETY_FACTOR,
            "screen_fleet_hours": fleet_hours,
            "screen_max_shard_hours": max_shard_hours,
            "screen_fleet_hour_cap": SCREEN_FLEET_HOUR_CAP,
            "screen_max_shard_hour_cap": SCREEN_MAX_SHARD_HOUR_CAP,
        },
        "capacity_pass": capacity_pass,
        # The measurement can support a later review; it cannot grant its own
        # successor authority.  A separate capacity-result marker must do so.
        "supports_screen_packet_review": capacity_pass,
        "screen_packet_design_authorized": False,
        "screen_execution_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    result["internal_sha256"] = stable_digest(result)
    problems = score_free_result_problems(result)
    if problems:
        raise ControllerRefused(
            "S6 preflight attempted score publication: " + "; ".join(problems))
    return result


def require_clean_exact_git(expected_git: str) -> None:
    if git("rev-parse", "HEAD") != expected_git:
        raise ControllerRefused("S6 controller git identity drift")
    if git("status", "--porcelain", "--untracked-files=all"):
        raise ControllerRefused("S6 controller worktree is dirty")


def require_compiled_strict_runtime() -> None:
    if (os.environ.get("SHENGJI_FAST") != "1"
            or os.environ.get("SHENGJI_REQUIRE_VOIDS") != "1"
            or not fast.HAVE_FAST
            or fast._fast is None
            or combos.decompose is not fast.decompose):
        raise ControllerRefused("S6 preflight requires compiled strict mode")


def require_exact_output_path(value: os.PathLike | str, expected: Path,
                              *, label: str) -> None:
    actual = Path(value).resolve(strict=False)
    if actual != expected.resolve(strict=False):
        raise ControllerRefused(
            f"{label} must use singleton path {expected.relative_to(REPO)}")


def freeze_command(args) -> None:
    require_clean_exact_git(args.expected_git)
    payload = packet_payload(
        expected_git=args.expected_git,
        source_review_record=args.source_review_record)
    write_exclusive(args.out, payload)
    print(json.dumps({
        "status": "FROZEN",
        "packet_sha256": sha256(args.out),
        "packet_internal_sha256": payload["internal_sha256"],
        "packet_review_claim": packet_review_claim(
            expected_git=args.expected_git, packet_sha256=sha256(args.out)),
    }, sort_keys=True))


def verify_command(args) -> None:
    require_clean_exact_git(args.expected_git)
    packet = load_packet(
        args.packet, args.expected_packet_sha256,
        expected_git=args.expected_git,
        source_review_record=args.source_review_record)
    print(json.dumps({"status": "VERIFIED",
                      "packet_internal_sha256": packet["internal_sha256"]},
                     sort_keys=True))


def preflight_command(args) -> None:
    require_clean_exact_git(args.expected_git)
    # The review authorizes one execution, not one execution per caller-chosen
    # filename.  Bind the consumed slot and result before opening any packet or
    # review bytes so argv variation cannot replay the authority.
    require_exact_output_path(
        args.admission, ADMISSION_PATH, label="S6 preflight admission")
    require_exact_output_path(
        args.out, RESULT_PATH, label="S6 preflight result")
    require_compiled_strict_runtime()
    packet = load_packet(
        args.packet, args.expected_packet_sha256,
        expected_git=args.expected_git,
        source_review_record=args.source_review_record)
    claim = packet_review_claim(
        expected_git=args.expected_git,
        packet_sha256=args.expected_packet_sha256)
    review = parse_marker(
        args.packet_review_record, PACKET_REVIEW_PREFIX, claim,
        label="S6 preflight packet review")
    admission = {
        "schema": ADMISSION_SCHEMA,
        "run_id": RUN_ID,
        "git": args.expected_git,
        "packet_sha256": args.expected_packet_sha256,
        "packet_review_sha256": review["sha256"],
        "nonce": secrets.token_hex(32),
        "created_time_ns": time.time_ns(),
        "score_free": True,
        "one_preflight_execution_authorized": True,
        "screen_execution_authorized": False,
        "strength_claim": False,
        "production_deployment": False,
    }
    admission["internal_sha256"] = stable_digest(admission)
    write_exclusive(args.admission, admission)
    result = measure_preflight(packet)
    result["admission_sha256"] = sha256(args.admission)
    result["packet_sha256"] = args.expected_packet_sha256
    result.pop("internal_sha256", None)
    result["internal_sha256"] = stable_digest(result)
    write_exclusive(args.out, result)
    result_sha = sha256(args.out)
    print(json.dumps({
        "status": "CAPACITY_PASS" if result["capacity_pass"] else "HOLD",
        "result_sha256": result_sha,
        "result_internal_sha256": result["internal_sha256"],
        "capacity_review_claim": capacity_review_claim(
            result=result, result_sha256=result_sha,
            packet_sha256=args.expected_packet_sha256),
    }, sort_keys=True))


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser()
    sub = root.add_subparsers(dest="command", required=True)
    for name, fn in (("freeze", freeze_command), ("verify", verify_command)):
        cmd = sub.add_parser(name)
        cmd.add_argument("--expected-git", required=True)
        cmd.add_argument("--source-review-record", required=True)
        if name == "freeze":
            cmd.add_argument("--out", required=True)
        else:
            cmd.add_argument("--packet", required=True)
            cmd.add_argument("--expected-packet-sha256", required=True)
        cmd.set_defaults(func=fn)
    run = sub.add_parser("run-preflight")
    run.add_argument("--expected-git", required=True)
    run.add_argument("--source-review-record", required=True)
    run.add_argument("--packet", required=True)
    run.add_argument("--expected-packet-sha256", required=True)
    run.add_argument("--packet-review-record", required=True)
    run.add_argument("--admission", required=True)
    run.add_argument("--out", required=True)
    run.set_defaults(func=preflight_command)
    return root


def main() -> None:
    args = parser().parse_args()
    try:
        args.func(args)
    except (ControllerRefused, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"REFUSED: {exc}") from exc


if __name__ == "__main__":
    main()
