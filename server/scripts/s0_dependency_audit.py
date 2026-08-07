#!/usr/bin/env python3
"""Predeclared lag-17 dependency repair for the frozen S0c evidence.

The historical null policy shifts its caller seed by 999,983 while the shared
evaluator seeds the opponent at +1,000,000 and +1,500,000.  Therefore the null
arm at deal seed ``s + 17`` reuses both opponent RNG streams from deal seed
``s``.  Ordinary per-seed intervals incorrectly treat those linked clusters as
independent.

This audit is deliberately stricter and was frozen before any S0c result was
opened.  It partitions every residue-mod-17 dependency chain by chain-position
parity.  Within either colour, seeds connected by the only possible lag-17 RNG
collision are separated, leaving two collision-free populations of roughly
4,096 seeds.  A frozen S0c PROMOTE is admissible only when *both* colours
independently clear arm-current and arm-null with paired 95% lower bounds above
zero, and both colour-specific null-current 95% intervals contain zero.

The original packet, aggregate, manifests and raw JSONL are all reopened.  The
result can only narrow the original decision: SELECT NONE remains SELECT NONE;
a provisional PROMOTE becomes final only if this repair passes.  Nothing here
launches a job, changes production, retries a seed, or extends the sample.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import re
import stat
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SERVER = ROOT / "server"
SCRIPTS = SERVER / "scripts"
sys.path.insert(0, str(SCRIPTS))

import s0_closeout as CLOSEOUT  # noqa: E402


SCHEMA = "s0-dependency-audit-v1"
SEAL_SCHEMA = "s0-dependency-input-seal-v1"
ATTEMPT_SCHEMA = "s0-dependency-attempt-v1"
FREEZE_SCHEMA = "s0-dependency-audit-freeze-v1"
FREEZE_PATH = Path(__file__).with_name("s0_dependency_audit_freeze.v1.json")
EVIDENCE_SERVER = Path("/Users/jerryyu/Projects/shengji-s0-mini/server")
AUDIT_SERVER = Path("/Users/jerryyu/Projects/shengji-s0-audit/server")
PYTHON = Path("/opt/homebrew/bin/python3.14")
LOGS = EVIDENCE_SERVER / "runs" / "logs"
PACKET = LOGS / "s0-final-packet.txt"
AGGREGATE = LOGS / "s0c-adaptive-lcb-v1.aggregate.json"
OUTPUT = LOGS / "s0c-dependency-audit-v1.json"
SEAL = LOGS / "s0c-dependency-input-seal-v1.json"
SEAL_ATTEMPT = LOGS / "s0c-dependency-input-seal-v1.attempt.json"
EVALUATE_ATTEMPT = LOGS / "s0c-dependency-evaluate-v1.attempt.json"
PHASE = "s0c-adaptive-lcb"
GIT_SHA = "be1e39cd9281f752d610ff770f6a280098024388"
SHORT_SHA = GIT_SHA[:10]
SEED0 = 135_000_000
CLUSTERS = 8_192
SEED_HI = SEED0 + CLUSTERS - 1
NULL_OFFSET = 999_983
OPPONENT_OFFSETS = (1_000_000, 1_500_000)
TEAMMATE_OFFSET = 500_000
DEPENDENCY_LAG = 1_000_000 - NULL_OFFSET
LABELS = {
    "arm": "mc-s0-adaptive",
    "null": "mc-strong-null",
    "reference": "mc-strong",
}
MAX_CANDIDATES = 14
SHARDS = 8
CLUSTERS_PER_SHARD = CLUSTERS // SHARDS
COUNTER_FIELDS = (
    "rollouts", "searches", "sample_attempts", "accepted_worlds",
    "failed_worlds", "rejected_worlds", "short_searches", "zero_world",
    "void_fallbacks",
)
AUDIT_TOOL_SHA256S = {
    "s0_run.py": "4566b06a264a3153a6f9c2909f40cac4da68d76ef24e1aec2495148c4a128e5f",
    "s0_aggregate.py": "a3e33086019c2a140963d06851591f3cea3ed2b23ffb9e1dd7bc0f6c58d7a255",
    "s0_packet.py": "667dfd41651dda3c40193ad5d9fc66458127099df9c73bc4efe5b8bb60688a72",
}
EXPECTED_RUNTIME = {
    "host": "Jerrys-Mac-mini.local",
    "python": "3.14.6",
    "fast_engine": True,
    "require_voids": True,
    "digests": {
        "evaluation": "4b75a5e643c8a2514c6d14707085f89a33e0c534adc2989229894f2f219a6b16",
        "fast_binary": "9c9e77fbdc4c6caceec195465155f37ec6369e409462fd838bc142bf8a0be4c1",
        "fast_router": "f2506d5c51b8ad37303f04dce59899de0d7c1179633b08ce61f48eb86cec1a3e",
        "mcbot": "3b97b651f9ce7324b22ec50e361ab2de46f4314eb33fe3d12ec7fd069a05b31f",
        "registry": "2a5e15480dc345abbf01c9b17cb3e3be90609a473ab8934a96a825730c1652d4",
        "runner": "c895234e5d5c2799d6421738f6fc6640edece2e968dd699c688eefac9fc5171a",
    },
}
SELECTION_RULE = (
    "The original S0c decision is only provisional. SELECT NONE remains final. "
    "For an original PROMOTE, split each lag-17 dependency chain by "
    "chain-position parity. In each of both collision-free colours require "
    "paired two-sided 95% LCB(arm-reference)>0, LCB(arm-null)>0, and the "
    "two-sided 95% null-reference interval to contain zero. Require exact raw "
    "coverage, exact original-stat reproduction and mechanically verified "
    "cross-seed RNG disjointness within each colour. Only then retain PROMOTE "
    "mc-s0-adaptive; otherwise SELECT NONE. No retry, alternate split, seed "
    "substitution, extension, deployment or report-policy fallback. Before "
    "any outcome parsing, a score-blind one-shot seal hashes the exact packet, "
    "aggregate, eight manifests and eight raw JSONL files. Evaluation is one "
    "shot and may consume only those sealed bytes. Original SELECT NONE emits "
    "a minimal corrected SELECT-NONE artifact without colour analysis."
)


class AuditRefused(RuntimeError):
    """The frozen evidence cannot support the corrected terminal decision."""


def sha256(path: os.PathLike | str) -> str:
    return sha256_bytes(read_regular_bytes(Path(path)))


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def stable_digest(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True,
    ).stdout.strip()


def git_blob(commit: str, path: Path) -> bytes:
    rel = path.resolve().relative_to(ROOT.resolve())
    result = subprocess.run(
        ["git", "show", f"{commit}:{rel}"], cwd=ROOT, capture_output=True,
    )
    if result.returncode:
        raise AuditRefused(f"cannot reopen {rel} at {commit}")
    return result.stdout


def file_commits(path: Path) -> list[str]:
    rel = path.resolve().relative_to(ROOT.resolve())
    output = git("log", "--follow", "--format=%H", "--", str(rel))
    return [line for line in output.splitlines() if line]


def _untracked(path: Path) -> bool:
    rel = path.resolve().relative_to(ROOT.resolve())
    return git("status", "--porcelain", "--", str(rel)).startswith("?? ")


def load_freeze() -> dict:
    try:
        value = json.loads(FREEZE_PATH.read_text())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuditRefused(f"dependency freeze unreadable: {exc}") from exc
    expected = {
        "schema", "script_sha256", "selection_digest", "python",
        "execution_host", "execution_root", "evidence_root", "audit_root",
        "s0_closeout_sha256",
    }
    if not isinstance(value, dict) or set(value) != expected:
        raise AuditRefused("dependency freeze fields drifted")
    if value.get("schema") != FREEZE_SCHEMA:
        raise AuditRefused("dependency freeze schema drifted")
    return value


def freeze_problems() -> list[str]:
    problems = []
    for path in (Path(__file__), FREEZE_PATH):
        commits = file_commits(path)
        if not commits:
            if _untracked(Path(__file__)) and _untracked(FREEZE_PATH):
                continue
            problems.append(f"{path.name}: no Git introduction")
            continue
        if len(commits) != 1:
            problems.append(
                f"{path.name}: changed after pre-outcome introduction")
            continue
        if path.read_bytes() != git_blob(commits[0], path):
            problems.append(f"{path.name}: differs from Git introduction")
    try:
        frozen = load_freeze()
    except AuditRefused as exc:
        problems.append(str(exc))
        return sorted(set(problems))
    if frozen.get("script_sha256") != sha256(__file__):
        problems.append("dependency-audit script digest drifted")
    if frozen.get("selection_digest") != stable_digest(SELECTION_RULE):
        problems.append("dependency-audit selection rule drifted")
    if frozen.get("python") != "3.14.6":
        problems.append("dependency-audit Python receipt drifted")
    if frozen.get("execution_host") != "Jerrys-Mac-mini.local":
        problems.append("dependency-audit execution host receipt drifted")
    if frozen.get("execution_root") != str(SERVER):
        problems.append("dependency-audit execution root receipt drifted")
    if frozen.get("evidence_root") != str(EVIDENCE_SERVER):
        problems.append("dependency-audit evidence root receipt drifted")
    if frozen.get("audit_root") != str(AUDIT_SERVER):
        problems.append("dependency-audit audit root receipt drifted")
    if frozen.get("s0_closeout_sha256") != sha256(CLOSEOUT.__file__):
        problems.append("dependency-audit closeout verifier drifted")
    return sorted(set(problems))


def require_runtime() -> str:
    problems = freeze_problems()
    if problems:
        raise AuditRefused("frozen dependency protocol:\n  - " +
                           "\n  - ".join(problems))
    frozen = load_freeze()
    if os.uname().nodename != frozen["execution_host"]:
        raise AuditRefused("dependency audit is bound to authoritative Mini")
    if str(SERVER.resolve()) != frozen["execution_root"]:
        raise AuditRefused("dependency audit is bound to the canonical checkout")
    if platform.python_version() != frozen["python"]:
        raise AuditRefused("dependency audit Python differs from freeze")
    dirty = git("status", "--porcelain")
    if dirty:
        raise AuditRefused(f"dependency-audit checkout is dirty: {dirty}")
    head = git("rev-parse", "HEAD")
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", head, "origin/main"],
        cwd=ROOT,
    ).returncode == 0
    if not ancestor:
        raise AuditRefused("dependency-audit HEAD is not pushed on origin/main")
    for name, digest in AUDIT_TOOL_SHA256S.items():
        if sha256(AUDIT_SERVER / "scripts" / name) != digest:
            raise AuditRefused(f"frozen S0 audit tool drift: {name}")
    return head


def manifest_path(index: int) -> Path:
    return LOGS / (
        f"s0-protocol-v2_{PHASE}_shard{index:02d}_{SHORT_SHA}.jsonl"
        ".manifest.json"
    )


def record_path(index: int) -> Path:
    return Path(str(manifest_path(index)).removesuffix(".manifest.json"))


def canonical_input_paths() -> tuple[Path, ...]:
    """Return the only bytes this one-shot correction may consume."""
    paths = [PACKET, AGGREGATE]
    for index in range(SHARDS):
        paths.extend((manifest_path(index), record_path(index)))
    return tuple(paths)


def input_key(path: Path) -> str:
    try:
        return str(path.relative_to(EVIDENCE_SERVER))
    except ValueError as exc:
        raise AuditRefused(f"input is outside frozen evidence root: {path}") \
            from exc


def _file_identity(path: Path) -> tuple[int, int, int, int]:
    try:
        value = path.lstat()
    except OSError as exc:
        raise AuditRefused(f"canonical input is unavailable: {path}: {exc}") \
            from exc
    if not stat.S_ISREG(value.st_mode):
        raise AuditRefused(f"canonical input is not a regular file: {path}")
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns)


def snapshot_inputs(paths: tuple[Path, ...] | list[Path]) -> dict[str, dict]:
    """Hash inputs without decoding them, refusing an in-flight mutation."""
    result = {}
    for path in paths:
        value = read_regular_bytes(path)
        key = input_key(path)
        if key in result:
            raise AuditRefused(f"duplicate canonical input key: {key}")
        result[key] = {"sha256": sha256_bytes(value), "size": len(value)}
    return result


def read_regular_bytes(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise AuditRefused(f"regular file is unreadable: {path}: {exc}") \
            from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise AuditRefused(f"canonical input is not regular: {path}")
        chunks = []
        while block := os.read(descriptor, 1 << 20):
            chunks.append(block)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    before_identity = (
        before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    after_identity = (
        after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    if before_identity != after_identity:
        raise AuditRefused(f"regular file changed while reading: {path}")
    pathname_identity = _file_identity(path)
    if pathname_identity[:2] != after_identity[:2]:
        raise AuditRefused(f"pathname changed while reading: {path}")
    value = b"".join(chunks)
    if len(value) != after.st_size:
        raise AuditRefused(f"regular file size changed while reading: {path}")
    return value


def read_sealed_inputs(seal: dict) -> dict[str, bytes]:
    """Read exactly the sealed bytes; never accept a same-shaped mutation."""
    expected = seal.get("inputs")
    paths = canonical_input_paths()
    if not isinstance(expected, dict) or set(expected) != {
            input_key(path) for path in paths}:
        raise AuditRefused("input seal does not name the exact canonical set")
    blobs = {}
    for path in paths:
        value = read_regular_bytes(path)
        key = input_key(path)
        identity = {"sha256": sha256_bytes(value), "size": len(value)}
        if identity != expected[key]:
            raise AuditRefused(f"sealed input digest/size drift: {key}")
        blobs[key] = value
    return blobs


def _load_json_bytes(value: bytes, description: str) -> dict:
    try:
        decoded = json.loads(value)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuditRefused(f"{description} is not valid JSON: {exc}") from exc
    if not isinstance(decoded, dict):
        raise AuditRefused(f"{description} is not a JSON object")
    return decoded


def _fsync_parent(path: Path) -> None:
    descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_attempt(path: Path, payload: dict) -> None:
    """Make a durable, non-retryable attempt receipt at the final path."""
    try:
        with path.open("x") as fh:
            json.dump(payload, fh, indent=2, sort_keys=True)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        _fsync_parent(path)
    except FileExistsError as exc:
        raise AuditRefused(f"one-shot attempt already exists: {path}") from exc


def _assert_absent(paths: tuple[Path, ...]) -> None:
    existing = [str(path) for path in paths
                if path.exists() or path.is_symlink()]
    if existing:
        raise AuditRefused(f"one-shot output/attempt already exists: {existing}")


def seal_inputs(expected_head: str | None = None) -> dict:
    """Seal all terminal inputs without decoding or scoring any outcome."""
    head = require_runtime()
    if expected_head is not None and head != expected_head:
        raise AuditRefused("checkout HEAD changed while waiting to seal")
    _assert_absent((
        SEAL, Path(str(SEAL) + ".partial"), SEAL_ATTEMPT,
        EVALUATE_ATTEMPT, OUTPUT, Path(str(OUTPUT) + ".partial"),
    ))
    paths = canonical_input_paths()
    missing = [input_key(path) for path in paths if not path.exists()]
    if missing:
        raise AuditRefused(f"canonical terminal inputs are missing: {missing}")

    attempt = {
        "schema": ATTEMPT_SCHEMA,
        "action": "seal",
        "git_sha": head,
        "selection_digest": stable_digest(SELECTION_RULE),
        "freeze_sha256": sha256(FREEZE_PATH),
        "canonical_inputs": [input_key(path) for path in paths],
        "started_unix_ns": time.time_ns(),
        "outcomes_parsed": False,
    }
    # This receipt is the first durable audit action. Any later failure leaves
    # it in place and permanently prevents a repaired/retried seal.
    write_attempt(SEAL_ATTEMPT, attempt)
    first = snapshot_inputs(paths)
    second = snapshot_inputs(paths)
    if first != second:
        raise AuditRefused("canonical terminal inputs changed across seal passes")
    payload = {
        "schema": SEAL_SCHEMA,
        "complete": True,
        "git_sha": head,
        "selection_digest": stable_digest(SELECTION_RULE),
        "freeze_sha256": sha256(FREEZE_PATH),
        "seal_attempt_path": str(SEAL_ATTEMPT),
        "seal_attempt_sha256": sha256(SEAL_ATTEMPT),
        "canonical_input_count": len(paths),
        "inputs": first,
        "input_set_sha256": stable_digest(first),
        "sealed_unix_ns": time.time_ns(),
        "outcomes_parsed": False,
    }
    write_exclusive(SEAL, payload)
    return payload


def watch_and_seal(poll_seconds: int = 10) -> dict:
    """Wait using names/counts only, then perform the one score-blind seal."""
    if poll_seconds < 1 or poll_seconds > 60:
        raise AuditRefused("seal watcher poll must be between 1 and 60 seconds")
    head = require_runtime()
    _assert_absent((
        SEAL, Path(str(SEAL) + ".partial"), SEAL_ATTEMPT,
        EVALUATE_ATTEMPT, OUTPUT, Path(str(OUTPUT) + ".partial"),
    ))
    paths = canonical_input_paths()
    while True:
        missing = [input_key(path) for path in paths if not path.exists()]
        if not missing:
            result = seal_inputs(expected_head=head)
            print(f"SEALED {len(paths)} canonical inputs at {SEAL}", flush=True)
            return result
        print(
            f"WAITING score-blind: {len(missing)}/{len(paths)} canonical "
            f"inputs missing: {', '.join(missing)}",
            flush=True,
        )
        time.sleep(poll_seconds)


def load_and_verify_seal(head: str, expected_sha256: str | None = None) -> dict:
    """Verify the one immutable seal before any outcome decoding."""
    if not SEAL.is_file() or not SEAL_ATTEMPT.is_file():
        raise AuditRefused("complete input seal and seal attempt are required")
    if expected_sha256 is not None and sha256(SEAL) != expected_sha256:
        raise AuditRefused("input seal differs from evaluation attempt")
    try:
        seal_bytes = read_regular_bytes(SEAL)
        attempt_bytes = read_regular_bytes(SEAL_ATTEMPT)
        if (expected_sha256 is not None
                and sha256_bytes(seal_bytes) != expected_sha256):
            raise AuditRefused("input seal changed while being decoded")
        seal = json.loads(seal_bytes)
        attempt = json.loads(attempt_bytes)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuditRefused(f"input seal receipt is unreadable: {exc}") from exc
    if not isinstance(seal, dict) or not isinstance(attempt, dict):
        raise AuditRefused("input seal receipt is not a JSON object")
    attempt_keys = {
        "schema", "action", "git_sha", "selection_digest",
        "freeze_sha256", "canonical_inputs", "started_unix_ns",
        "outcomes_parsed",
    }
    seal_keys = {
        "schema", "complete", "git_sha", "selection_digest",
        "freeze_sha256", "seal_attempt_path", "seal_attempt_sha256",
        "canonical_input_count", "inputs", "input_set_sha256",
        "sealed_unix_ns", "outcomes_parsed",
    }
    if set(attempt) != attempt_keys or set(seal) != seal_keys:
        raise AuditRefused("input-seal/attempt fields drifted")
    expected_paths = [input_key(path) for path in canonical_input_paths()]
    if (attempt.get("schema") != ATTEMPT_SCHEMA
            or attempt.get("action") != "seal"
            or attempt.get("git_sha") != head
            or attempt.get("selection_digest") != stable_digest(SELECTION_RULE)
            or attempt.get("freeze_sha256") != sha256(FREEZE_PATH)
            or attempt.get("canonical_inputs") != expected_paths
            or type(attempt.get("started_unix_ns")) is not int
            or attempt["started_unix_ns"] <= 0
            or attempt.get("outcomes_parsed") is not False):
        raise AuditRefused("seal-attempt identity drift")
    if (seal.get("schema") != SEAL_SCHEMA
            or seal.get("complete") is not True
            or seal.get("git_sha") != head
            or seal.get("selection_digest") != stable_digest(SELECTION_RULE)
            or seal.get("freeze_sha256") != sha256(FREEZE_PATH)
            or seal.get("seal_attempt_path") != str(SEAL_ATTEMPT)
            or seal.get("seal_attempt_sha256") != sha256_bytes(attempt_bytes)
            or seal.get("canonical_input_count") != len(expected_paths)
            or type(seal.get("sealed_unix_ns")) is not int
            or seal["sealed_unix_ns"] < attempt["started_unix_ns"]
            or seal.get("outcomes_parsed") is not False
            or seal.get("input_set_sha256") != stable_digest(seal.get("inputs"))):
        raise AuditRefused("input-seal identity drift")
    current = snapshot_inputs(canonical_input_paths())
    if current != seal.get("inputs"):
        raise AuditRefused("canonical terminal inputs differ from score-blind seal")
    return seal


def _packet_hash(text: str, prefix: str) -> str:
    lines = [line for line in text.splitlines() if line.startswith(prefix)]
    if len(lines) != 1:
        raise AuditRefused(f"terminal packet has {len(lines)} {prefix!r} lines")
    match = re.search(r"\bsha256=([0-9a-f]{64})\b", lines[0])
    if not match:
        raise AuditRefused(f"terminal packet {prefix!r} lacks SHA-256")
    return match.group(1)


def verify_original_terminal(blobs: dict[str, bytes]) -> tuple[dict, str, str]:
    result = CLOSEOUT.verify_terminal_packet(
        EVIDENCE_SERVER, PYTHON, PACKET,
        AUDIT_SERVER / "scripts" / "s0_packet.py",
    )
    if result.get("phases") != ["s0a", "s0b-lcb", PHASE]:
        raise AuditRefused(f"terminal phase path drifted: {result.get('phases')}")
    packet_bytes = blobs[input_key(PACKET)]
    if result.get("packet_sha256") != sha256_bytes(packet_bytes):
        raise AuditRefused("terminal verifier consumed a different packet")
    try:
        text = packet_bytes.decode()
    except UnicodeDecodeError as exc:
        raise AuditRefused(f"sealed terminal packet is not UTF-8: {exc}") from exc
    aggregate_sha = _packet_hash(text, f"{PHASE} aggregate:")
    if sha256_bytes(blobs[input_key(AGGREGATE)]) != aggregate_sha:
        raise AuditRefused("terminal S0c aggregate digest mismatch")
    manifest_line = next(
        (line for line in text.splitlines()
         if line.startswith(f"{PHASE} manifests (8/8):")), "")
    for index in range(8):
        path = manifest_path(index)
        bit = (f"{path.relative_to(EVIDENCE_SERVER)} "
               f"sha256={sha256_bytes(blobs[input_key(path)])}")
        if manifest_line.count(bit) != 1:
            raise AuditRefused(
                f"terminal packet does not bind canonical manifest {index}")
    return result, text, aggregate_sha


def load_raw(blobs: dict[str, bytes]) -> \
        tuple[list[dict], dict[str, list[dict]], dict[str, str]]:
    manifests = []
    records = {label: [] for label in LABELS}
    record_sha256s = {}
    for index in range(SHARDS):
        mpath = manifest_path(index)
        rpath = record_path(index)
        try:
            manifest = _load_json_bytes(
                blobs[input_key(mpath)], f"S0c manifest {index}")
            rows = [json.loads(line) for line in
                    blobs[input_key(rpath)].decode().splitlines()]
        except (KeyError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AuditRefused(f"raw S0c shard {index} unreadable: {exc}") from exc
        seed_lo = SEED0 + index * CLUSTERS_PER_SHARD
        seed_hi = seed_lo + CLUSTERS_PER_SHARD - 1
        expected = {
            "schema": "s0-protocol-v2",
            "phase": PHASE,
            "run_id": f"s0-protocol-v2_{PHASE}_shard{index:02d}_{SHORT_SHA}",
            "git_sha": GIT_SHA,
            "host": EXPECTED_RUNTIME["host"],
            "python": EXPECTED_RUNTIME["python"],
            "fast_engine": True,
            "require_voids": True,
            "complete": True,
            "promotable": True,
            "problems": [],
            "tree_dirty": False,
            "dirty_files": [],
            "shard_count": SHARDS,
            "total_clusters": CLUSTERS,
            "clusters": CLUSTERS_PER_SHARD,
            "shard_index": index,
            "seed0": seed_lo,
            "seed_hi": seed_hi,
            "opponent": "mc-strong",
            "labels": LABELS,
            "kind": "confirmation",
            "report_worlds": 300,
        }
        drift = {key: {"actual": manifest.get(key), "expected": value}
                 for key, value in expected.items()
                 if manifest.get(key) != value}
        runtime = {
            "host": manifest.get("host"), "python": manifest.get("python"),
            "fast_engine": manifest.get("fast_engine"),
            "require_voids": manifest.get("require_voids"),
            "digests": manifest.get("digests"),
        }
        if runtime != EXPECTED_RUNTIME:
            drift["runtime"] = {"actual": runtime,
                                "expected": EXPECTED_RUNTIME}
        if drift:
            raise AuditRefused(f"S0c manifest {index} drift: {drift}")
        manifests.append(manifest)
        record_sha256s[input_key(rpath)] = sha256_bytes(blobs[input_key(rpath)])
        run_id = manifest.get("run_id")
        local_records = {label: [] for label in LABELS}
        for row in rows:
            if not isinstance(row, dict) or row.get("label") not in LABELS:
                raise AuditRefused(f"S0c shard {index} record schema drift")
            if (row.get("run") != run_id
                    or row.get("policy") != LABELS[row["label"]]):
                raise AuditRefused(f"S0c shard {index} record identity drift")
            seed = row.get("seed")
            flip = row.get("flip")
            won = row.get("won")
            utility = row.get("level_utility")
            if (type(seed) is not int or not seed_lo <= seed <= seed_hi
                    or type(flip) is not int or flip not in (0, 1)):
                raise AuditRefused(
                    f"S0c shard {index} record seed/flip drift")
            if type(won) is not int or won not in (0, 1):
                raise AuditRefused(f"S0c shard {index} malformed win flag")
            if type(utility) is not int or utility == 0:
                raise AuditRefused(f"S0c shard {index} malformed utility")
            if (utility > 0) != (won == 1):
                raise AuditRefused(
                    f"S0c shard {index} win/utility sign disagreement")
            counter_errors = []
            for side in ("arm", "opp"):
                counter_errors.extend(counter_problems(
                    row["label"], side, row.get(side)))
            if counter_errors:
                raise AuditRefused(
                    f"S0c shard {index} exact work drift: "
                    + "; ".join(sorted(set(counter_errors))))
            local_records[row["label"]].append(row)
            records[row["label"]].append(row)

        expected_local_keys = {
            (seed, flip) for seed in range(seed_lo, seed_hi + 1)
            for flip in (0, 1)
        }
        for label, local_rows in local_records.items():
            keys = [(row["seed"], row["flip"]) for row in local_rows]
            if (len(keys) != 2 * CLUSTERS_PER_SHARD
                    or len(keys) != len(set(keys))
                    or set(keys) != expected_local_keys):
                raise AuditRefused(
                    f"S0c shard {index}/{label}: local coverage drift")
        local_stats = {}
        for label in LABELS:
            value = paired(local_records, label, "reference")
            local_stats[label] = {
                key: item for key, item in value.items() if key not in {"a", "b"}
            }
        if manifest.get("paired_vs_reference") != local_stats:
            raise AuditRefused(
                f"S0c shard {index}: manifest statistics differ from raw")

    expected_keys = {(seed, flip) for seed in range(SEED0, SEED_HI + 1)
                     for flip in (0, 1)}
    for label, rows in records.items():
        keys = [(row.get("seed"), row.get("flip")) for row in rows]
        if len(keys) != 2 * CLUSTERS or len(keys) != len(set(keys)) \
                or set(keys) != expected_keys:
            raise AuditRefused(f"{label}: exact raw seed/flip coverage drift")
    return manifests, records, record_sha256s


def counter_problems(label: str, side: str, counters: object) -> list[str]:
    """Reconstruct exact candidate-rollout arithmetic from aggregate counters."""
    required = set(COUNTER_FIELDS)
    if not isinstance(counters, dict) or not required.issubset(counters):
        return [f"{label}/{side}: counter schema drift"]
    if any(isinstance(counters[name], bool)
           or not isinstance(counters[name], int)
           or counters[name] < 0 for name in required):
        return [f"{label}/{side}: malformed counter"]
    problems = []
    searches = counters["searches"]
    rollouts = counters["rollouts"]
    accepted = counters["accepted_worlds"]
    if counters["sample_attempts"] != (
            accepted + counters["failed_worlds"]):
        problems.append(f"{label}/{side}: sampler counters do not reconcile")
    for name in ("failed_worlds", "rejected_worlds", "short_searches",
                 "zero_world", "void_fallbacks"):
        if counters[name]:
            problems.append(f"{label}/{side}: nonzero {name}")

    report = label == "arm" and side == "arm"
    report_rollouts = 600 * searches if report else 0
    selection_rollouts = rollouts - report_rollouts
    if report:
        if accepted < 330 * searches:
            problems.append(f"{label}/{side}: accepted report dose is short")
        if accepted > 300 * searches + selection_rollouts:
            problems.append(f"{label}/{side}: accepted worlds exceed exact work")
    elif accepted != 30 * searches:
        problems.append(f"{label}/{side}: plain accepted dose differs")
    if selection_rollouts < 60 * searches:
        problems.append(f"{label}/{side}: fewer than two candidates per search")
    if selection_rollouts > 30 * MAX_CANDIDATES * searches:
        problems.append(f"{label}/{side}: candidate ballot exceeds frozen cap")
    if selection_rollouts % 30:
        problems.append(f"{label}/{side}: candidate rollout arithmetic differs")
    return problems


def counter_totals(records: dict[str, list[dict]]) -> dict:
    return {
        label: {
            side: {
                field: sum(int(row[side].get(field, 0)) for row in rows)
                for field in COUNTER_FIELDS
            }
            for side in ("arm", "opp")
        }
        for label, rows in records.items()
    }


def paired(records: dict[str, list[dict]], a: str, b: str,
           seeds: set[int] | None = None) -> dict:
    by = {}
    for row in records[a]:
        if seeds is None or row["seed"] in seeds:
            by.setdefault(row["seed"], [0, 0])[0] += row["level_utility"]
    for row in records[b]:
        if seeds is None or row["seed"] in seeds:
            by.setdefault(row["seed"], [0, 0])[1] += row["level_utility"]
    values = [left - right for left, right in by.values()]
    n = len(values)
    if n < 2:
        raise AuditRefused(f"{a}-{b}: fewer than two paired clusters")
    mean = sum(values) / n
    variance = sum((value - mean) ** 2 for value in values) / (n - 1)
    half = 1.96 * math.sqrt(variance / n)
    return {"a": a, "b": b, "mean": mean,
            "half_width_95": half, "clusters": n}


def all_stats(records: dict[str, list[dict]],
              seeds: set[int] | None = None) -> dict:
    return {
        "arm-reference": paired(records, "arm", "reference", seeds),
        "arm-null": paired(records, "arm", "null", seeds),
        "null-reference": paired(records, "null", "reference", seeds),
    }


def chain_colour(seed: int) -> int:
    return ((seed - SEED0) // DEPENDENCY_LAG) % 2


def effective_rng_streams(label: str, seed: int) -> tuple[int, ...]:
    arm_shift = NULL_OFFSET if label == "null" else 0
    return (
        seed + arm_shift,
        seed + TEAMMATE_OFFSET + arm_shift,
        seed + OPPONENT_OFFSETS[0],
        seed + OPPONENT_OFFSETS[1],
    )


def stream_witness(seeds: set[int]) -> dict:
    owners: dict[int, set[int]] = {}
    for seed in sorted(seeds):
        for label in LABELS:
            for stream in effective_rng_streams(label, seed):
                owners.setdefault(stream, set()).add(seed)
    cross = {stream: sorted(values) for stream, values in owners.items()
             if len(values) > 1}
    return {
        "seeds": len(seeds),
        "unique_rng_streams": len(owners),
        "cross_seed_collision_count": len(cross),
        "cross_seed_collisions": cross,
    }


def criteria(stats: dict) -> dict[str, bool]:
    def lcb(name: str) -> float:
        return (float(stats[name]["mean"])
                - float(stats[name]["half_width_95"]))

    null = stats["null-reference"]
    result = {
        "arm_reference_lcb_gt_0": lcb("arm-reference") > 0,
        "arm_null_lcb_gt_0": lcb("arm-null") > 0,
        "null_reference_interval_contains_0": (
            abs(float(null["mean"])) <= float(null["half_width_95"])),
    }
    result["all"] = all(result.values())
    return result


def corrected_decision(original_promote: bool,
                       colours: dict[str, dict]) -> tuple[bool, str, str]:
    dependency_pass = (
        set(colours) == {"0", "1"}
        and all(value.get("criteria", {}).get("all") is True
                for value in colours.values())
    )
    promotion = bool(original_promote and dependency_pass)
    state = ("S0_COMPLETE_PROMOTE" if promotion
             else "S0_COMPLETE_SELECT_NONE")
    decision = ("PROMOTE mc-s0-adaptive" if promotion
                else "SELECT NONE; production remains mc-strong")
    return dependency_pass, state, decision


def write_exclusive(path: Path, payload: dict) -> None:
    partial = Path(str(path) + ".partial")
    if path.exists() or partial.exists():
        raise AuditRefused(f"refusing duplicate dependency audit: {path}")
    with partial.open("x") as fh:
        json.dump(payload, fh, indent=2, sort_keys=True)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    try:
        os.link(partial, path)
    except FileExistsError as exc:
        raise AuditRefused(f"concurrent dependency audit publication: {path}") \
            from exc
    partial.unlink()
    _fsync_parent(path)


def _result_base(head: str, seal: dict, terminal: dict,
                 aggregate_sha: str) -> dict:
    return {
        "schema": SCHEMA,
        "complete": True,
        "git_sha": head,
        "selection_rule": SELECTION_RULE,
        "selection_digest": stable_digest(SELECTION_RULE),
        "input_seal_path": str(SEAL),
        "input_seal_sha256": sha256(SEAL),
        "input_set_sha256": seal["input_set_sha256"],
        "evaluation_attempt_path": str(EVALUATE_ATTEMPT),
        "evaluation_attempt_sha256": sha256(EVALUATE_ATTEMPT),
        "original_terminal_state": terminal["state"],
        "original_packet_path": str(PACKET),
        "original_packet_sha256": terminal["packet_sha256"],
        "s0c_aggregate_path": str(AGGREGATE),
        "s0c_aggregate_sha256": aggregate_sha,
        "automatic_deployment": False,
        "retry_or_extension_authorized": False,
        "claim_boundary": (
            "Corrected inference for the already-frozen S0c seed block only; "
            "this artifact cannot launch or deploy a policy."
        ),
    }


def run(head: str, seal: dict, blobs: dict[str, bytes], terminal: dict,
        packet_text: str, aggregate_sha: str) -> dict:
    """Analyze sealed bytes after the durable evaluation attempt exists."""
    original_state = terminal["state"]
    base = _result_base(head, seal, terminal, aggregate_sha)
    if original_state == "S0_COMPLETE_SELECT_NONE":
        return {
            **base,
            "raw_reopened": False,
            "original_stats_reproduced": None,
            "colours_analyzed": False,
            "original_promote": False,
            "dependency_repair_pass": None,
            "promotion_admissible": False,
            "final_state": "S0_COMPLETE_SELECT_NONE",
            "final_production_decision": (
                "SELECT NONE; production remains mc-strong"),
        }
    if original_state != "S0_COMPLETE_PROMOTE":
        raise AuditRefused(f"unregistered original terminal state: {original_state}")

    aggregate = _load_json_bytes(
        blobs[input_key(AGGREGATE)], "sealed S0c aggregate")
    expected_aggregate = {
        "schema": "s0-mechanism-aggregate-v1",
        "phase": PHASE,
        "clusters": CLUSTERS,
        "seed0": SEED0,
        "seed_hi": SEED_HI,
        "git_sha": GIT_SHA,
        "record_counts": {label: 2 * CLUSTERS for label in LABELS},
        "runtime_identity": EXPECTED_RUNTIME,
        "hosts": [EXPECTED_RUNTIME["host"]],
        "survivor_label": "arm",
        "survivor_policy": "mc-s0-adaptive",
        "promotion": True,
    }
    drift = {key: {"actual": aggregate.get(key), "expected": value}
             for key, value in expected_aggregate.items()
             if aggregate.get(key) != value}
    if drift:
        raise AuditRefused(f"stored S0c aggregate drift: {drift}")
    _, records, record_sha256s = load_raw(blobs)
    recomputed = all_stats(records)
    if aggregate.get("stats") != recomputed:
        raise AuditRefused("original aggregate stats differ from raw reopening")
    recomputed_counters = counter_totals(records)
    if aggregate.get("counter_totals") != recomputed_counters:
        raise AuditRefused("aggregate counters differ from raw reopening")

    all_seeds = set(range(SEED0, SEED_HI + 1))
    full_witness = stream_witness(all_seeds)
    expected_collision_pairs = {
        (seed, seed + DEPENDENCY_LAG)
        for seed in range(SEED0, SEED_HI - DEPENDENCY_LAG + 1)
    }
    actual_pairs = {
        tuple(values) for values in full_witness["cross_seed_collisions"].values()
    }
    if (DEPENDENCY_LAG != 17 or actual_pairs != expected_collision_pairs
            or full_witness["cross_seed_collision_count"]
            != 2 * (CLUSTERS - DEPENDENCY_LAG)):
        raise AuditRefused("observed RNG dependency graph differs from lag-17 model")

    colours = {}
    for colour in (0, 1):
        seeds = {seed for seed in all_seeds if chain_colour(seed) == colour}
        witness = stream_witness(seeds)
        if witness["cross_seed_collision_count"] != 0:
            raise AuditRefused(f"colour {colour} retains cross-seed RNG collision")
        stats = all_stats(records, seeds)
        colours[str(colour)] = {
            "definition": (
                f"floor((seed-{SEED0})/{DEPENDENCY_LAG}) mod 2 == {colour}"),
            "seed_count": len(seeds),
            "seed_sha256": stable_digest(sorted(seeds)),
            "stream_witness": {
                key: value for key, value in witness.items()
                if key != "cross_seed_collisions"
            },
            "stats": stats,
            "criteria": criteria(stats),
        }

    original_promote = (
        aggregate.get("promotion") is True
        and aggregate.get("survivor_policy") == "mc-s0-adaptive"
        and isinstance(aggregate.get("criteria"), dict)
        and aggregate["criteria"].get("all") is True
        and "Final production decision from registered rule: "
           "PROMOTE mc-s0-adaptive" in packet_text
    )
    dependency_pass, final_state, decision = corrected_decision(
        original_promote, colours)
    promotion_admissible = final_state == "S0_COMPLETE_PROMOTE"
    if not original_promote:
        raise AuditRefused("PROMOTE packet is inconsistent with sealed aggregate")
    return {
        **base,
        "manifest_sha256s": {
            input_key(manifest_path(index)):
            seal["inputs"][input_key(manifest_path(index))]["sha256"]
            for index in range(SHARDS)
        },
        "record_sha256s": record_sha256s,
        "raw_reopened": True,
        "original_stats_reproduced": True,
        "aggregate_counters_reproduced": True,
        "local_coverage_and_stats_reproduced": True,
        "colours_analyzed": True,
        "dependency_lag": DEPENDENCY_LAG,
        "full_population_cross_seed_collision_count":
            full_witness["cross_seed_collision_count"],
        "expected_cross_seed_collision_count":
            2 * (CLUSTERS - DEPENDENCY_LAG),
        "colours": colours,
        "original_promote": original_promote,
        "dependency_repair_pass": dependency_pass,
        "promotion_admissible": promotion_admissible,
        "final_state": final_state,
        "final_production_decision": decision,
    }


def evaluate() -> dict:
    """Consume the score-blind seal exactly once and publish one decision."""
    head = require_runtime()
    _assert_absent((
        EVALUATE_ATTEMPT, OUTPUT, Path(str(OUTPUT) + ".partial"),
    ))
    _file_identity(SEAL)
    _file_identity(SEAL_ATTEMPT)
    seal_sha = sha256(SEAL)
    attempt = {
        "schema": ATTEMPT_SCHEMA,
        "action": "evaluate",
        "git_sha": head,
        "selection_digest": stable_digest(SELECTION_RULE),
        "freeze_sha256": sha256(FREEZE_PATH),
        "input_seal_path": str(SEAL),
        "input_seal_sha256": seal_sha,
        "started_unix_ns": time.time_ns(),
        "outcomes_parsed": False,
    }
    # This is deliberately durable before the packet, aggregate, manifests or
    # records are decoded. A crash/refusal is terminal rather than retryable.
    write_attempt(EVALUATE_ATTEMPT, attempt)
    attempt_sha = sha256(EVALUATE_ATTEMPT)
    seal = load_and_verify_seal(head, expected_sha256=seal_sha)
    blobs = read_sealed_inputs(seal)
    terminal, packet_text, aggregate_sha = verify_original_terminal(blobs)
    result = run(
        head, seal, blobs, terminal, packet_text, aggregate_sha)
    if snapshot_inputs(canonical_input_paths()) != seal["inputs"]:
        raise AuditRefused("sealed inputs changed during evaluation")
    if sha256(SEAL) != seal_sha or sha256(EVALUATE_ATTEMPT) != attempt_sha:
        raise AuditRefused("seal/evaluation attempt changed during evaluation")
    write_exclusive(OUTPUT, result)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="One-shot, predeclared S0c dependency correction")
    sub = parser.add_subparsers(dest="command", required=True)
    watch = sub.add_parser("watch", help="wait by metadata, then seal inputs")
    watch.add_argument("--poll-seconds", type=int, default=10)
    sub.add_parser("seal", help="seal already-complete canonical inputs")
    sub.add_parser("evaluate", help="evaluate the previously sealed inputs")
    args = parser.parse_args()
    if args.command == "watch":
        result = watch_and_seal(args.poll_seconds)
    elif args.command == "seal":
        result = seal_inputs()
    else:
        result = evaluate()
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except (AuditRefused, RuntimeError) as exc:
        print(f"REFUSING: {exc}", file=sys.stderr)
        raise SystemExit(3) from exc
