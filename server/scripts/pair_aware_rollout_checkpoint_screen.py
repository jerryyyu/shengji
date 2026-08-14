#!/usr/bin/env python3
"""Freeze and run the checkpointed Pair whole-round screen.

This is the first scored execution layer of the reviewed checkpoint-successor
design.  It preserves the powered Pair science from the V3 screen while
changing only execution geometry: 7,168 fresh clusters are split into 224
immutable 32-cluster bundles and at most 16 workers run concurrently.

The supervisor reads only outcome-free receipts.  Outcome files remain sealed
until a separately implemented and independently reviewed aggregate gate.
There is deliberately no resume, aggregate, strength, promotion, or deploy
command in this module.
"""
from __future__ import annotations

import sys

if (__name__ == "__main__"
        and (not sys.dont_write_bytecode
             or not sys.flags.isolated
             or not sys.flags.safe_path)):
    raise SystemExit(
        "REFUSED: checkpoint screen commands require isolated safe-path "
        "no-bytecode Python (-I -P -B)")

import argparse
import hashlib
import json
import math
import os
import secrets
import signal
import stat
import subprocess
import time
import types
from collections import Counter
from pathlib import Path
from typing import Any


SCRIPT = Path(__file__).resolve()
REPO = SCRIPT.parents[2]
SERVER = REPO / "server"
SCRIPTS = SERVER / "scripts"
CAPACITY_MODULE = "pair_aware_rollout_checkpoint_capacity"
CAPACITY_PATH = SCRIPTS / f"{CAPACITY_MODULE}.py"
CAPACITY_SOURCE_SHA256 = (
    "9eec1a8780667f269baabe68e4ed072eecde452abff56945755bf7635f7afa58"
)


def _authenticated_capacity_module():
    raw = CAPACITY_PATH.read_bytes()
    if hashlib.sha256(raw).hexdigest() != CAPACITY_SOURCE_SHA256:
        raise RuntimeError("reviewed Pair capacity source drift")
    preloaded = sys.modules.get(CAPACITY_MODULE)
    if preloaded is not None:
        origin = getattr(preloaded, "__file__", None)
        if (not isinstance(origin, str)
                or Path(origin).resolve() != CAPACITY_PATH.resolve()):
            raise RuntimeError("preloaded Pair capacity origin drift")
        return preloaded, True
    module = types.ModuleType(CAPACITY_MODULE)
    module.__file__ = str(CAPACITY_PATH)
    module.__package__ = ""
    sys.modules[CAPACITY_MODULE] = module
    try:
        exec(compile(raw, str(CAPACITY_PATH), "exec"), module.__dict__)
    except BaseException:
        sys.modules.pop(CAPACITY_MODULE, None)
        raise
    return module, False


CAPACITY, CAPACITY_WAS_PRELOADED = _authenticated_capacity_module()
sys.path.insert(0, str(SERVER))


DESIGN = CAPACITY.DESIGN
CORE = None

SOURCE_GIT = "8a3ef59ff0b19759dc7eecd52fedb9c35e5e2d19"
DESIGN_GIT = "36b3841f28e04a1b3ba066044db0ed8c992e8714"
DESIGN_SOURCE_SHA256 = (
    "259e8dba94af04bb4d26e1146202587c5efcfce7812c3d3b3224ecd1a250bc34"
)
CAPACITY_PACKET_SHA256 = (
    "b2d78d67e0973d3e09a5ca8483e5cb2b7c24f7af0c78fce7782c19cb5f69f92f"
)
CAPACITY_ADMISSION_SHA256 = (
    "e3e51d2b81de7b212328095f84490c2a97b9fbf09dc2a49d2e68c3eb0aad0128"
)
CAPACITY_RESULT_SHA256 = (
    "c120ddbbd6ea2c5b777ed67554cfe5ddf098fdd6dc172507f9fe8dea041f7762"
)
CAPACITY_RECEIPT_SHA256 = (
    "488bf14061d57733db9a1911c6ecc4b9d806f4aa7fb14e1630b8207dae72f005"
)
CAPACITY_RUNTIME_PROFILE_SHA256 = (
    "ff2dc8f1289242bdade0a24c75bce2d61f71ee5c51e505401eae23cf570d7945"
)
CAPACITY_PACKET_REVIEW_COMMIT = (
    "749059553357c11c1095a9f8ca8909f81258c98c"
)
CAPACITY_TERMINAL_REVIEW_COMMIT = (
    "482119b8956fe42f1a932c80a39fd620f388556f"
)
CAPACITY_TERMINAL_REVIEW_PARENT = (
    "f46cad5cc87f99090686eb420981aab44394f7f8"
)
CAPACITY_TERMINAL_APPEND_SHA256 = (
    "577de1c0c5686ed130b741fc17d2496f65a7da623db4e1d9cbbd7766908fc43a"
)

PACKET_SCHEMA = "pair-aware-rollout-checkpoint-screen-packet-v1"
ADMISSION_SCHEMA = "pair-aware-rollout-checkpoint-screen-admission-v1"
OUTCOME_SCHEMA = "pair-aware-rollout-checkpoint-microshard-outcome-v1"
RECEIPT_SCHEMA = "pair-aware-rollout-checkpoint-microshard-receipt-v1"
IMPLEMENTATION_REVIEW_SCHEMA = (
    "pair-aware-rollout-checkpoint-screen-implementation-review-v1"
)
PACKET_REVIEW_SCHEMA = (
    "pair-aware-rollout-checkpoint-screen-packet-review-v1"
)
IMPLEMENTATION_REVIEW_PREFIX = (
    "PAIR_AWARE_ROLLOUT_CHECKPOINT_SCREEN_IMPLEMENTATION_V1_REVIEW "
)
PACKET_REVIEW_PREFIX = (
    "PAIR_AWARE_ROLLOUT_CHECKPOINT_SCREEN_PACKET_V1_REVIEW "
)
CANONICAL_REVIEW_REF = "origin/main"
REVIEW_LEDGER = "HANDOFF_REVIEW.md"
REVIEWER_NAME = "Claude"
REVIEWER_EMAIL = "noreply@anthropic.com"
REVIEWER_SESSION_TRAILER = "Claude-Session: https://claude.ai/code/session_"

RUN_ID = DESIGN.RUN_ID
SCREEN_CLUSTERS = DESIGN.SCREEN_CLUSTERS
MICROSHARD_CLUSTERS = DESIGN.MICROSHARD_CLUSTERS
MICROSHARDS = DESIGN.MICROSHARDS
WORKERS = DESIGN.MIN_WORKERS
SCREEN_SEED0 = DESIGN.SCREEN_SEED0
STREAM_STRIDE = DESIGN.STREAM_STRIDE
PROGRESS_EVERY = 8

RUN_DIR = SERVER / "runs/logs" / RUN_ID
LOCK_DIR = SERVER / "runs/locks"
PACKET_PATH = RUN_DIR / "controller-packet.json"
IMPLEMENTATION_REVIEW_PATH = RUN_DIR / "implementation-review-snapshot.md"
GATE_PATH = LOCK_DIR / f"{RUN_ID}.execution.consumed"
GATE_PARTIAL_PATH = LOCK_DIR / f"{RUN_ID}.execution.partial"
PACKET_REVIEW_PATH = GATE_PATH / "packet-review-snapshot.md"
ADMISSION_PATH = GATE_PATH / "admission.json"
MANIFEST_PATH = RUN_DIR / "score-free-manifest.json"
SYSTEMD_UNIT = f"{RUN_ID}.service"
BUNDLE_PATHS = tuple(
    RUN_DIR / f"microshard-{index:03d}" for index in range(MICROSHARDS)
)
PARTIAL_BUNDLE_PATHS = tuple(
    RUN_DIR / f"microshard-{index:03d}.partial"
    for index in range(MICROSHARDS)
)
LOG_PATHS = tuple(
    RUN_DIR / f"microshard-{index:03d}.log"
    for index in range(MICROSHARDS)
)

CAPACITY_PACKET_PATH = Path(
    "/var/tmp/shengji-pair-screen-checkpoint-capacity-v2/server/runs/logs/"
    "pair-aware-whole-round-concurrent-capacity-v2/controller-packet.json"
)
CAPACITY_ADMISSION_PATH = Path(
    "/var/tmp/shengji-pair-screen-checkpoint-capacity-v2/server/runs/locks/"
    "pair-aware-whole-round-concurrent-capacity-v2.admission.consumed.json"
)
CAPACITY_RESULT_PATH = Path(
    "/var/tmp/shengji-pair-screen-checkpoint-capacity-v2/server/runs/logs/"
    "pair-aware-whole-round-concurrent-capacity-v2/capacity.json"
)
CAPACITY_RECEIPT_PATH = Path(
    "/var/tmp/shengji-pair-screen-checkpoint-capacity-v2/server/runs/logs/"
    "pair-aware-whole-round-concurrent-capacity-v2/execution-receipt.json"
)

ONE_SIDED_ALPHA = 0.05
Z_ONE_SIDED_95 = 1.6448536269514722
FORBIDDEN_RECEIPT_KEYS = frozenset({
    "action", "actions", "attacker_points", "history", "level_utility",
    "outcome", "outcomes", "points", "record", "records", "reward",
    "score", "scores", "utility", "winner", "won",
})


class ScreenRefused(RuntimeError):
    """The reviewed source, packet, runtime, or sealed-output contract drifted."""


def require_fresh_process() -> None:
    if CAPACITY_WAS_PRELOADED:
        raise ScreenRefused(
            "screen command requires a fresh authenticated capacity module")
    if (not sys.dont_write_bytecode
            or not sys.flags.isolated
            or not sys.flags.safe_path):
        raise ScreenRefused(
            "screen command requires isolated safe-path no-bytecode Python "
            "(-I -P -B)")
    CAPACITY.require_fresh_process()


def canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       allow_nan=False) + "\n").encode()


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def is_sha256(value: object) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(character in "0123456789abcdef" for character in value))


def is_git_sha(value: object) -> bool:
    return (isinstance(value, str) and len(value) == 40
            and all(character in "0123456789abcdef" for character in value))


def _reject_constant(value: str) -> None:
    raise ValueError(f"nonfinite JSON constant {value}")


def _pairs(values: list[tuple[str, object]]) -> dict:
    result: dict[str, object] = {}
    for key, value in values:
        if key in result:
            raise ValueError(f"duplicate JSON key {key}")
        result[key] = value
    return result


def strict_json(raw: bytes) -> Any:
    return json.loads(raw, object_pairs_hook=_pairs,
                      parse_constant=_reject_constant)


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO, check=True,
                          capture_output=True, text=True).stdout.strip()


def git_bytes(*args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=REPO, check=True,
                          capture_output=True).stdout


def require_clean_exact_git(expected_git: str) -> None:
    if (not is_git_sha(expected_git)
            or git("rev-parse", "HEAD") != expected_git
            or git("status", "--porcelain", "--untracked-files=all")):
        raise ScreenRefused("screen execution requires exact clean Git")


def stable_bytes(path: Path, *, label: str, root_owned: bool = False,
                 nonwritable: bool = False) -> bytes:
    partial = Path(str(path) + ".partial")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except (FileNotFoundError, OSError) as exc:
        raise ScreenRefused(f"{label} is missing") from exc
    try:
        before = os.fstat(descriptor)
        path_before = path.lstat()
        chunks = []
        while True:
            chunk = os.read(descriptor, 1 << 20)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(descriptor)
        path_after = path.lstat()
    except (FileNotFoundError, OSError) as exc:
        raise ScreenRefused(f"{label} changed during read") from exc
    finally:
        os.close(descriptor)
    identity = lambda info: (
        info.st_dev, info.st_ino, info.st_mode, info.st_nlink,
        info.st_uid, info.st_size, info.st_mtime_ns,
    )
    if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
            or identity(before) != identity(after)
            or identity(before) != identity(path_before)
            or identity(before) != identity(path_after)
            or os.path.lexists(partial)
            or (root_owned and before.st_uid != 0)
            or (nonwritable and before.st_mode & 0o222)):
        raise ScreenRefused(
            f"{label} is linked, nonregular, partial, writable, unowned, "
            "or unstable")
    raw = b"".join(chunks)
    if len(raw) != before.st_size:
        raise ScreenRefused(f"{label} size changed during read")
    return raw


def strict_object(path: Path, *, label: str, root_owned: bool = False,
                  nonwritable: bool = False) -> tuple[dict, bytes]:
    raw = stable_bytes(path, label=label, root_owned=root_owned,
                       nonwritable=nonwritable)
    value = strict_json(raw)
    if not isinstance(value, dict):
        raise ScreenRefused(f"{label} is not an object")
    return value, raw


def write_bytes_exclusive(path: Path, raw: bytes, *, mode: int = 0o444) -> None:
    partial = Path(str(path) + ".partial")
    if os.path.lexists(path) or os.path.lexists(partial):
        raise ScreenRefused(f"refusing existing output {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with partial.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    os.link(partial, path)
    partial.unlink()
    path.chmod(mode)
    if stable_bytes(path, label=f"published {path.name}") != raw:
        raise ScreenRefused(f"published bytes differ for {path}")


def write_exclusive(path: Path, value: object) -> None:
    write_bytes_exclusive(path, canonical(value))


def _canonical_marker(prefix: str, claim: dict) -> bytes:
    return prefix.encode() + canonical(claim)


def canonical_review_record(*, commit: str, prefix: str, expected: dict,
                            label: str) -> tuple[dict, bytes]:
    try:
        return CAPACITY.canonical_review_record(
            commit=commit, prefix=prefix, expected=expected, label=label)
    except CAPACITY.CapacityRefused as exc:
        raise ScreenRefused(str(exc)) from exc


def capacity_terminal_review() -> dict:
    commit = CAPACITY_TERMINAL_REVIEW_COMMIT
    try:
        if subprocess.run(
                ["git", "merge-base", "--is-ancestor", commit,
                 CANONICAL_REVIEW_REF], cwd=REPO,
                capture_output=True, check=False).returncode != 0:
            raise ScreenRefused("capacity terminal review is not canonical")
        parent = git("show", "-s", "--format=%P", commit)
        identity = tuple(git("show", "-s", f"--format={field}", commit)
                         for field in ("%an", "%ae", "%cn", "%ce"))
        changed = git("diff-tree", "--no-commit-id", "--name-only", "-r",
                      commit).splitlines()
        current = git_bytes("show", f"{commit}:{REVIEW_LEDGER}")
        previous = git_bytes("show", f"{parent}:{REVIEW_LEDGER}")
        tip = git_bytes("show", f"{CANONICAL_REVIEW_REF}:{REVIEW_LEDGER}")
    except subprocess.CalledProcessError as exc:
        raise ScreenRefused("cannot authenticate capacity terminal review") \
            from exc
    delta = current[len(previous):] if current.startswith(previous) else b""
    required = (
        b"Pair capacity V2 terminal PASS",
        b"47.88 projected wall-hours",
        b"successor screen-packet implementation/freeze only",
        b"no screen execution, outcomes, strength, retry, extension",
    )
    if (parent != CAPACITY_TERMINAL_REVIEW_PARENT
            or identity != (REVIEWER_NAME, REVIEWER_EMAIL,
                            REVIEWER_NAME, REVIEWER_EMAIL)
            or REVIEWER_SESSION_TRAILER not in git(
                "show", "-s", "--format=%B", commit)
            or changed != [REVIEW_LEDGER]
            or not current.startswith(previous)
            or not tip.startswith(current)
            or sha256_bytes(delta) != CAPACITY_TERMINAL_APPEND_SHA256
            or any(token not in delta for token in required)):
        raise ScreenRefused("capacity terminal review provenance drift")
    return {
        "commit": commit,
        "parent_commit": parent,
        "ledger_sha256": sha256_bytes(current),
        "append_sha256": CAPACITY_TERMINAL_APPEND_SHA256,
    }


def _capacity_artifact(path: Path, expected_sha: str,
                       *, label: str) -> tuple[dict, bytes]:
    value, raw = strict_object(path, label=label, root_owned=True,
                               nonwritable=True)
    if sha256_bytes(raw) != expected_sha:
        raise ScreenRefused(f"{label} SHA-256 drift")
    return value, raw


def capacity_packet_problems(value: object) -> list[str]:
    """Validate frozen capacity bytes without rebasing their absolute paths."""
    if not isinstance(value, dict):
        return ["reviewed capacity packet is not an object"]
    unsigned = dict(value)
    observed = unsigned.pop("internal_sha256", None)
    expected_fields = {
        "schema", "run_id", "git", "design_git", "design_source_sha256",
        "implementation_review", "runtime", "runtime_profile_sha256",
        "capacity", "one_capacity_execution_authorized",
        "screen_execution_authorized", "resume_execution_authorized",
        "aggregate_execution_authorized", "strength_claim",
        "production_deployment", "internal_sha256",
    }
    problems = []
    runtime = value.get("runtime")
    if set(value) != expected_fields:
        problems.append("reviewed capacity packet field population drift")
    if (observed != digest(unsigned)
            or value.get("schema") != CAPACITY.PACKET_SCHEMA
            or value.get("run_id") != DESIGN.CAPACITY_RUN_ID
            or value.get("git") != SOURCE_GIT
            or value.get("design_git") != DESIGN_GIT
            or value.get("design_source_sha256") != DESIGN_SOURCE_SHA256
            or value.get("runtime_profile_sha256")
            != CAPACITY_RUNTIME_PROFILE_SHA256
            or value.get("runtime_profile_sha256") != digest(runtime)
            or value.get("capacity") != {
                "seed0": DESIGN.CAPACITY_SEED0,
                "workers": DESIGN.MIN_WORKERS,
                "clusters_per_worker": DESIGN.CAPACITY_CLUSTERS_PER_WORKER,
                "stream_stride": DESIGN.STREAM_STRIDE,
                "all_workers_start_concurrently": True,
                "outcomes_published": False,
            }
            or any(value.get(field) is not False for field in (
                "one_capacity_execution_authorized",
                "screen_execution_authorized", "resume_execution_authorized",
                "aggregate_execution_authorized", "strength_claim",
                "production_deployment"))):
        problems.append("reviewed capacity packet identity/authority drift")
    if (not isinstance(runtime, dict)
            or runtime.get("git") != SOURCE_GIT
            or runtime.get("machine") not in {"x86_64", "amd64"}
            or runtime.get("fast_enabled") is not True
            or runtime.get("fast_environment") is not True
            or runtime.get("fast_routing_active") is not True
            or runtime.get("strict_voids") is not True
            or runtime.get("dont_write_bytecode") is not True
            or runtime.get("python_hash_seed") != "0"
            or runtime.get("process_nice") != 5
            or runtime.get("loadable_shadows") != []
            or not is_sha256(runtime.get("native", {}).get("sha256"))
            or not is_sha256(runtime.get("python", {}).get("sha256"))):
        problems.append("reviewed capacity runtime identity drift")
    implementation = value.get("implementation_review")
    if (not isinstance(implementation, dict)
            or set(implementation) != {
                "commit", "parent_commit", "ledger_sha256",
                "marker_sha256", "claim"}
            or not is_git_sha(implementation.get("commit"))
            or not is_git_sha(implementation.get("parent_commit"))
            or not is_sha256(implementation.get("ledger_sha256"))
            or not is_sha256(implementation.get("marker_sha256"))):
        problems.append("reviewed capacity implementation provenance drift")
    return sorted(set(problems))


def capacity_runtime_compatibility(capacity_runtime: object,
                                   screen_runtime: object) -> dict:
    if not isinstance(capacity_runtime, dict) \
            or not isinstance(screen_runtime, dict):
        raise ScreenRefused("capacity/screen runtime is malformed")
    capacity_sources = capacity_runtime.get("source_sha256s")
    screen_sources = screen_runtime.get("source_sha256s")
    if not isinstance(capacity_sources, dict) \
            or not isinstance(screen_sources, dict):
        raise ScreenRefused("capacity/screen source manifest is malformed")
    missing = sorted(set(capacity_sources) - set(screen_sources))
    drift = sorted(name for name, value in capacity_sources.items()
                   if screen_sources.get(name) != value)
    exact_fields = (
        "hostname", "machine", "cpu_count", "memory_bytes", "python",
        "fast_enabled", "fast_environment", "fast_routing_active",
        "strict_voids", "dont_write_bytecode", "python_hash_seed",
        "process_nice", "boot_id", "loadable_shadows",
    )
    field_drift = [field for field in exact_fields
                   if capacity_runtime.get(field) != screen_runtime.get(field)]
    capacity_native = capacity_runtime.get("native", {})
    screen_native = screen_runtime.get("native", {})
    if (missing or drift or field_drift
            or not isinstance(capacity_native, dict)
            or not isinstance(screen_native, dict)
            or capacity_native.get("sha256") != screen_native.get("sha256")):
        raise ScreenRefused("capacity and screen runtime compatibility drift")
    return {
        "same_host_and_boot": True,
        "same_python": True,
        "same_native_bytes": True,
        "same_compiled_strict_flags_and_nice": True,
        "capacity_source_paths": len(capacity_sources),
        "capacity_sources_exact_subset_of_screen": True,
        "screen_source_paths": len(screen_sources),
    }


def capacity_evidence(*, screen_runtime: dict | None = None) -> dict:
    packet, _ = _capacity_artifact(
        CAPACITY_PACKET_PATH, CAPACITY_PACKET_SHA256,
        label="reviewed capacity packet")
    admission, _ = _capacity_artifact(
        CAPACITY_ADMISSION_PATH, CAPACITY_ADMISSION_SHA256,
        label="reviewed capacity admission")
    result, _ = _capacity_artifact(
        CAPACITY_RESULT_PATH, CAPACITY_RESULT_SHA256,
        label="reviewed capacity result")
    receipt, _ = _capacity_artifact(
        CAPACITY_RECEIPT_PATH, CAPACITY_RECEIPT_SHA256,
        label="reviewed capacity receipt")
    packet_problems = capacity_packet_problems(packet)
    if packet_problems:
        raise ScreenRefused("; ".join(packet_problems))
    claim = CAPACITY.packet_review_claim(
        packet=packet, packet_sha256=CAPACITY_PACKET_SHA256)
    review, _ = CAPACITY.canonical_review_record(
        commit=CAPACITY_PACKET_REVIEW_COMMIT,
        prefix=CAPACITY.PACKET_REVIEW_PREFIX, expected=claim,
        label="reviewed capacity packet review")
    invocation = receipt.get("systemd_invocation_id")
    problems = []
    problems.extend(CAPACITY.admission_problems(
        admission, packet=packet, packet_sha256=CAPACITY_PACKET_SHA256,
        review=review, invocation_id=invocation))
    problems.extend(CAPACITY.capacity_result_problems(result, packet=packet))
    problems.extend(CAPACITY.receipt_problems(
        receipt, packet=packet, packet_sha256=CAPACITY_PACKET_SHA256,
        packet_review=review, admission_sha256=CAPACITY_ADMISSION_SHA256,
        result_sha256=CAPACITY_RESULT_SHA256, result=result,
        invocation_id=invocation))
    if problems:
        raise ScreenRefused("; ".join(sorted(set(problems))))
    projection = DESIGN.capacity_projection(
        result, expected_workers=DESIGN.MIN_WORKERS,
        runtime_profile_sha256=CAPACITY_RUNTIME_PROFILE_SHA256)
    if not 0 < projection["projected_wall_hours"] <= 52.0:
        raise ScreenRefused("reviewed capacity projection drift")
    value = {
        "source_git": SOURCE_GIT,
        "packet_sha256": CAPACITY_PACKET_SHA256,
        "admission_sha256": CAPACITY_ADMISSION_SHA256,
        "result_sha256": CAPACITY_RESULT_SHA256,
        "receipt_sha256": CAPACITY_RECEIPT_SHA256,
        "runtime_profile_sha256": CAPACITY_RUNTIME_PROFILE_SHA256,
        "packet_review_commit": CAPACITY_PACKET_REVIEW_COMMIT,
        "terminal_review": capacity_terminal_review(),
        "projection": projection,
    }
    if screen_runtime is not None:
        value["runtime_compatibility"] = capacity_runtime_compatibility(
            packet["runtime"], screen_runtime)
    return value


def source_sha256s() -> dict[str, str]:
    names = git("ls-tree", "-r", "--name-only", "HEAD").splitlines()
    selected = [name for name in names
                if name.startswith("server/shengji/")
                or name in {"server/setup.py", "server/pyproject.toml",
                            "server/scripts/pair_aware_rollout_duel.py",
                            ("server/scripts/pair_aware_rollout_checkpoint_"
                             "successor_design.py"),
                            ("server/scripts/pair_aware_rollout_checkpoint_"
                             "capacity.py"),
                            ("server/scripts/pair_aware_rollout_checkpoint_"
                             "screen.py")}]
    return {name: sha256_file(REPO / name) for name in sorted(selected)}


def systemd_unit_bytes() -> bytes:
    controller = SCRIPT.resolve()
    packet = PACKET_PATH.resolve()
    admission = ADMISSION_PATH.resolve()
    return (
        "[Unit]\n"
        "Description=Pair checkpointed whole-round screen v1\n"
        "After=network.target\n\n"
        "[Service]\n"
        "Type=exec\n"
        "User=root\n"
        "Nice=5\n"
        f"WorkingDirectory={REPO}\n"
        "Environment=PYTHONDONTWRITEBYTECODE=1\n"
        "Environment=PYTHONHASHSEED=0\n"
        "Environment=SHENGJI_FAST=1\n"
        "Environment=SHENGJI_REQUIRE_VOIDS=1\n"
        "Environment=PYTHONPATH=server:server/scripts\n"
        "ExecStart=/bin/bash -c 'set -euo pipefail; "
        f"packet={packet}; "
        f"expected_git=$$(/usr/bin/git -C {REPO} rev-parse HEAD); "
        "packet_sha=$$(/usr/bin/sha256sum \"$$packet\" | "
        "/usr/bin/cut -d \" \" -f1); "
        f"review_commit=$$(/usr/bin/git -C {REPO} log -1 "
        f"--format=%%H -G \"^{PACKET_REVIEW_PREFIX}\" "
        f"{CANONICAL_REVIEW_REF} -- {REVIEW_LEDGER}); "
        "test -n \"$$review_commit\"; "
        f"exec /usr/bin/python3.14 -I -P -B {controller} run-screen "
        "--expected-git \"$$expected_git\" "
        "--packet \"$$packet\" "
        "--expected-packet-sha256 \"$$packet_sha\" "
        "--packet-review-commit \"$$review_commit\" "
        f"--admission {admission}'\n"
        "Restart=no\n"
        "KillMode=control-group\n"
        "RuntimeMaxSec=52h\n"
        "StandardOutput=journal\n"
        "StandardError=journal\n\n"
        "[Install]\n"
        "WantedBy=multi-user.target\n"
    ).encode()


def runtime_snapshot(expected_git: str) -> dict:
    global CORE
    base = CAPACITY.runtime_snapshot(expected_git)
    CORE = CAPACITY.CORE
    base = dict(base)
    base["source_sha256s"] = source_sha256s()
    base["module_origins"] = dict(base["module_origins"])
    base["module_origins"]["screen_controller"] = str(SCRIPT)
    base["systemd_unit"] = {
        "unit": SYSTEMD_UNIT,
        "sha256": sha256_bytes(systemd_unit_bytes()),
    }
    return base


def runtime_problems(value: object, *, expected_git: str) -> list[str]:
    if not isinstance(value, dict):
        return ["screen runtime is not an object"]
    problems = []
    expected_fields = {
        "git", "hostname", "machine", "platform", "cpu_count",
        "memory_bytes", "python", "native", "systemd_unit", "fast_enabled",
        "fast_environment", "fast_routing_active", "strict_voids",
        "dont_write_bytecode", "python_hash_seed", "process_nice", "boot_id",
        "module_origins", "loadable_shadows", "source_sha256s",
    }
    if set(value) != expected_fields:
        problems.append("screen runtime field population drift")
    if (value.get("git") != expected_git
            or value.get("machine") != "x86_64"
            or not isinstance(value.get("cpu_count"), int)
            or isinstance(value.get("cpu_count"), bool)
            or value["cpu_count"] < WORKERS
            or not isinstance(value.get("memory_bytes"), int)
            or isinstance(value.get("memory_bytes"), bool)
            or value["memory_bytes"] < 30 * 1024 ** 3
            or value.get("fast_enabled") is not True
            or value.get("fast_environment") is not True
            or value.get("fast_routing_active") is not True
            or value.get("strict_voids") is not True
            or value.get("dont_write_bytecode") is not True
            or value.get("python_hash_seed") != "0"
            or value.get("process_nice") != 5
            or value.get("loadable_shadows") != []
            or value.get("source_sha256s") != source_sha256s()
            or value.get("systemd_unit") != {
                "unit": SYSTEMD_UNIT,
                "sha256": sha256_bytes(systemd_unit_bytes()),
            }
            or value.get("module_origins", {}).get("screen_controller")
            != str(SCRIPT)):
        problems.append("screen runtime identity drift")
    for field in ("hostname", "platform", "boot_id"):
        if not isinstance(value.get(field), str) or not value[field]:
            problems.append(f"screen runtime {field} drift")
    python = value.get("python")
    if (not isinstance(python, dict)
            or set(python) != {"executable", "resolved", "version",
                               "sha256", "soabi"}
            or not all(isinstance(python.get(field), str)
                       and python[field] for field in (
                           "executable", "resolved", "version", "soabi"))
            or not Path(python["resolved"]).is_absolute()
            or not is_sha256(python.get("sha256"))):
        problems.append("screen runtime python drift")
    native = value.get("native")
    if (not isinstance(native, dict) or set(native) != {"path", "sha256"}
            or not isinstance(native.get("path"), str)
            or not Path(native["path"]).is_absolute()
            or not is_sha256(native.get("sha256"))):
        problems.append("screen runtime native drift")
    origins = value.get("module_origins")
    if (not isinstance(origins, dict)
            or set(origins) != {"controller", "design", "duel", "fast",
                                "native", "screen_controller"}
            or origins.get("screen_controller") != str(SCRIPT)
            or any(not isinstance(path, str) or not Path(path).is_absolute()
                   for path in origins.values())):
        problems.append("screen runtime module-origin drift")
    sources = value.get("source_sha256s")
    if (not isinstance(sources, dict) or not sources
            or any(not isinstance(name, str) or not is_sha256(value_)
                   for name, value_ in sources.items())):
        problems.append("screen runtime source identity drift")
    return sorted(set(problems))


def require_frozen_runtime_inputs(runtime: dict) -> None:
    if os.geteuid() != 0:
        raise ScreenRefused("screen freeze/run requires root-owned inputs")
    for relative, expected_sha in runtime["source_sha256s"].items():
        raw = stable_bytes(REPO / relative, label=f"runtime source {relative}",
                           root_owned=True, nonwritable=True)
        if sha256_bytes(raw) != expected_sha:
            raise ScreenRefused(f"runtime source {relative} drift")
    for label, path, expected_sha in (
            ("native", Path(runtime["native"]["path"]),
             runtime["native"]["sha256"]),
            ("Python", Path(runtime["python"]["resolved"]),
             runtime["python"]["sha256"])):
        raw = stable_bytes(path, label=f"runtime {label}", root_owned=True,
                           nonwritable=True)
        if sha256_bytes(raw) != expected_sha:
            raise ScreenRefused(f"runtime {label} drift")


def implementation_review_claim(*, expected_git: str) -> dict:
    return {
        "schema": IMPLEMENTATION_REVIEW_SCHEMA,
        "git": expected_git,
        "controller_sha256": sha256_file(SCRIPT),
        "design_git": DESIGN_GIT,
        "design_source_sha256": DESIGN_SOURCE_SHA256,
        "capacity_terminal_review_commit": CAPACITY_TERMINAL_REVIEW_COMMIT,
        "capacity_result_sha256": CAPACITY_RESULT_SHA256,
        "screen_packet_freeze_authorized": True,
        "screen_execution_authorized": False,
        "resume_execution_authorized": False,
        "aggregate_execution_authorized": False,
        "outcome_access_authorized": False,
        "strength_claim": False,
        "production_deployment": False,
    }


def packet_review_claim(*, packet: dict, packet_sha256: str) -> dict:
    return {
        "schema": PACKET_REVIEW_SCHEMA,
        "git": packet["git"],
        "packet_sha256": packet_sha256,
        "packet_internal_sha256": packet["internal_sha256"],
        "runtime_profile_sha256": packet["runtime_profile_sha256"],
        "systemd_unit_sha256": packet["runtime"]["systemd_unit"]["sha256"],
        "microshards": MICROSHARDS,
        "one_screen_execution_authorized": True,
        "resume_execution_authorized": False,
        "aggregate_execution_authorized": False,
        "outcome_access_authorized": False,
        "strength_claim": False,
        "production_deployment": False,
    }


def science_contract() -> dict:
    return {
        "labels": ["treatment", "matched_null", "champion"],
        "clusters": SCREEN_CLUSTERS,
        "seed0": SCREEN_SEED0,
        "stream_stride": STREAM_STRIDE,
        "primary_metric": "mirrored mean signed level utility",
        "primary_contrasts": [
            "treatment_minus_matched_null",
            "treatment_minus_champion",
        ],
        "one_sided_alpha": ONE_SIDED_ALPHA,
        "decision_rule": (
            "PASS_SCREEN iff both primary one-sided 95% lower bounds "
            "are positive, matched-null equals champion exactly, pair "
            "dose covers both roles, and every integrity gate passes"
        ),
    }


def execution_contract() -> dict:
    return {
        "workers": WORKERS,
        "microshards": MICROSHARDS,
        "clusters_per_microshard": MICROSHARD_CLUSTERS,
        "bundle_paths": [str(path.relative_to(REPO))
                         for path in BUNDLE_PATHS],
        "log_paths": [str(path.relative_to(REPO)) for path in LOG_PATHS],
        "manifest_path": str(MANIFEST_PATH.relative_to(REPO)),
        "atomic_bundle_directory": True,
        "supervisor_reads_outcome_files": False,
        "fresh_population": True,
        "automatic_retry": False,
    }


def packet_payload(*, expected_git: str, runtime: dict,
                   implementation_review: dict,
                   capacity: dict) -> dict:
    if runtime_problems(runtime, expected_git=expected_git):
        raise ScreenRefused("cannot freeze invalid screen runtime")
    value = {
        "schema": PACKET_SCHEMA,
        "run_id": RUN_ID,
        "git": expected_git,
        "design_git": DESIGN_GIT,
        "design_source_sha256": DESIGN_SOURCE_SHA256,
        "implementation_review": implementation_review,
        "capacity_evidence": capacity,
        "runtime": runtime,
        "runtime_profile_sha256": digest(runtime),
        "science": science_contract(),
        "execution": execution_contract(),
        "one_screen_execution_authorized": False,
        "resume_execution_authorized": False,
        "aggregate_execution_authorized": False,
        "outcome_access_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
        "retry_or_extension_authorized": False,
    }
    value["internal_sha256"] = digest(value)
    return value


def packet_problems(value: object, *, expected_git: str) -> list[str]:
    if not isinstance(value, dict):
        return ["screen packet is not an object"]
    unsigned = dict(value)
    observed = unsigned.pop("internal_sha256", None)
    problems = []
    expected_fields = {
        "schema", "run_id", "git", "design_git", "design_source_sha256",
        "implementation_review", "capacity_evidence", "runtime",
        "runtime_profile_sha256", "science", "execution",
        "one_screen_execution_authorized", "resume_execution_authorized",
        "aggregate_execution_authorized", "outcome_access_authorized",
        "strength_claim", "production_promotion", "production_deployment",
        "retry_or_extension_authorized", "internal_sha256",
    }
    if set(value) != expected_fields:
        problems.append("screen packet field population drift")
    if (observed != digest(unsigned)
            or value.get("schema") != PACKET_SCHEMA
            or value.get("run_id") != RUN_ID
            or value.get("git") != expected_git
            or value.get("design_git") != DESIGN_GIT
            or value.get("design_source_sha256") != DESIGN_SOURCE_SHA256
            or value.get("runtime_profile_sha256") != digest(value.get("runtime"))
            or any(value.get(field) is not False for field in (
                "one_screen_execution_authorized", "resume_execution_authorized",
                "aggregate_execution_authorized", "outcome_access_authorized",
                "strength_claim", "production_promotion",
                "production_deployment", "retry_or_extension_authorized"))):
        problems.append("screen packet identity/authority drift")
    problems.extend(runtime_problems(value.get("runtime"),
                                     expected_git=expected_git))
    review = value.get("implementation_review")
    if (not isinstance(review, dict)
            or set(review) != {"commit", "parent_commit", "ledger_sha256",
                               "marker_sha256", "claim"}
            or review.get("claim") != implementation_review_claim(
                expected_git=expected_git)
            or not is_git_sha(review.get("commit"))
            or not is_git_sha(review.get("parent_commit"))
            or not is_sha256(review.get("ledger_sha256"))
            or not is_sha256(review.get("marker_sha256"))):
        problems.append("screen implementation-review provenance drift")
    capacity = value.get("capacity_evidence")
    if (not isinstance(capacity, dict)
            or capacity.get("packet_sha256") != CAPACITY_PACKET_SHA256
            or capacity.get("admission_sha256") != CAPACITY_ADMISSION_SHA256
            or capacity.get("result_sha256") != CAPACITY_RESULT_SHA256
            or capacity.get("receipt_sha256") != CAPACITY_RECEIPT_SHA256
            or capacity.get("runtime_profile_sha256")
            != CAPACITY_RUNTIME_PROFILE_SHA256
            or capacity.get("terminal_review", {}).get("commit")
            != CAPACITY_TERMINAL_REVIEW_COMMIT
            or capacity.get("projection", {}).get("projected_wall_hours", 53)
            > 52.0):
        problems.append("screen capacity evidence drift")
    if value.get("science") != science_contract():
        problems.append("screen science contract drift")
    if value.get("execution") != execution_contract():
        problems.append("screen execution geometry drift")
    return sorted(set(problems))


def load_packet(path: Path, expected_sha256: str, *, expected_git: str) -> dict:
    if path.resolve() != PACKET_PATH.resolve():
        raise ScreenRefused("screen packet path is not canonical")
    value, raw = strict_object(path, label="screen packet", root_owned=True,
                               nonwritable=True)
    if sha256_bytes(raw) != expected_sha256:
        raise ScreenRefused("screen packet file SHA drift")
    problems = packet_problems(value, expected_git=expected_git)
    if problems:
        raise ScreenRefused("; ".join(problems))
    review, marker = canonical_review_record(
        commit=value["implementation_review"]["commit"],
        prefix=IMPLEMENTATION_REVIEW_PREFIX,
        expected=implementation_review_claim(expected_git=expected_git),
        label="checkpoint screen implementation review")
    if review != value["implementation_review"]:
        raise ScreenRefused("screen implementation review record drift")
    snapshot = stable_bytes(
        IMPLEMENTATION_REVIEW_PATH, label="implementation review snapshot",
        root_owned=True, nonwritable=True)
    if snapshot != marker or sha256_bytes(snapshot) != review["marker_sha256"]:
        raise ScreenRefused("screen implementation review snapshot drift")
    if value["capacity_evidence"] != capacity_evidence(
            screen_runtime=value["runtime"]):
        raise ScreenRefused("screen capacity evidence reconstruction drift")
    return value


def _core(expected_git: str):
    if CORE is None:
        runtime_snapshot(expected_git)
    if CORE is None:
        raise ScreenRefused("Pair duel runtime was not authenticated")
    return CORE


def _plain_totals(core, records: list[dict], side: str) -> dict:
    names = set(core.counters([]))
    totals = {name: 0.0 if name == "search_secs" else 0 for name in names}
    for record in records:
        for name in names:
            totals[name] += record[side][name]
    return totals


def _pair_totals(core, records: list[dict], side: str) -> dict:
    modes = {record[side]["pair_aware"]["mode"] for record in records}
    if len(modes) != 1:
        raise ScreenRefused("screen telemetry mode drift")
    totals = Counter({field: 0 for field in core.PAIR_AWARE_COUNTER_FIELDS})
    for record in records:
        totals.update({field: record[side]["pair_aware"][field]
                       for field in core.PAIR_AWARE_COUNTER_FIELDS})
    return {"mode": next(iter(modes)), **dict(totals)}


def cluster_row(*, core, cluster_index: int, seed: int,
                by_label: dict[str, list[dict]]) -> dict:
    if list(by_label) != list(core.LABEL_ORDER):
        raise ScreenRefused("screen arm population/order drift")
    for label, records in by_label.items():
        if len(records) != 2:
            raise ScreenRefused("screen mirror population drift")
        for flip, record in enumerate(records):
            problems = core.record_problems(
                record, expected_label=label, expected_seed=seed,
                expected_flip=flip, expected_run_id=RUN_ID)
            if problems:
                raise ScreenRefused("invalid screen record: "
                                    + "; ".join(problems))
    for null, champion in zip(by_label["matched_null"],
                              by_label["champion"], strict=True):
        problems = core.matched_null_champion_problems(null, champion)
        if problems:
            raise ScreenRefused("; ".join(problems))
    dose = [core.natural_root_dose(treatment, null)
            for treatment, null in zip(by_label["treatment"],
                                       by_label["matched_null"], strict=True)]
    return {
        "cluster_index": cluster_index,
        "seed": seed,
        "level_utility": {
            label: [int(row["level_utility"]) for row in by_label[label]]
            for label in core.LABEL_ORDER
        },
        "won": {
            label: [int(row["won"]) for row in by_label[label]]
            for label in core.LABEL_ORDER
        },
        "natural_dose": dose,
    }


def dose_summary(rows: list[dict]) -> dict:
    doses = [dose for row in rows for dose in row["natural_dose"]]
    expected_fields = {
        "shared_prefix_plays", "root_action_changed", "change_play_index",
        "change_phase", "change_role",
    }
    for dose in doses:
        if not isinstance(dose, dict) or set(dose) != expected_fields:
            raise ScreenRefused("screen natural-dose shape drift")
        changed = dose.get("root_action_changed")
        if (not isinstance(dose.get("shared_prefix_plays"), int)
                or isinstance(dose.get("shared_prefix_plays"), bool)
                or not 0 <= dose["shared_prefix_plays"] <= 100
                or not isinstance(changed, bool)):
            raise ScreenRefused("screen natural-dose shape drift")
        if changed:
            if (not isinstance(dose.get("change_play_index"), int)
                    or dose["change_play_index"]
                    != dose["shared_prefix_plays"]
                    or dose.get("change_phase") not in {"early", "mid", "late"}
                    or dose.get("change_role") not in {"attacker", "defender"}):
                raise ScreenRefused("screen changed-dose identity drift")
        elif any(dose.get(field) is not None for field in (
                "change_play_index", "change_phase", "change_role")):
            raise ScreenRefused("screen unchanged-dose identity drift")
    changes = [dose for dose in doses if dose["root_action_changed"]]
    phases = Counter(dose["change_phase"] for dose in changes)
    roles = Counter(dose["change_role"] for dose in changes)
    return {
        "complete_round_pairs": len(doses),
        "root_action_changes": len(changes),
        "rounds_without_root_change": len(doses) - len(changes),
        "shared_prefix_plays": sum(dose["shared_prefix_plays"] for dose in doses),
        "changes_by_phase": {
            phase: int(phases[phase]) for phase in ("early", "mid", "late")
        },
        "changes_by_role": {
            role: int(roles[role]) for role in ("attacker", "defender")
        },
        "matched_null_champion_exact_histories": True,
    }


def run_microshard_payload(*, packet: dict, packet_sha256: str,
                           microshard_index: int,
                           progress_every: int = PROGRESS_EVERY) -> dict:
    if (not isinstance(microshard_index, int)
            or isinstance(microshard_index, bool)
            or not 0 <= microshard_index < MICROSHARDS):
        raise ScreenRefused("screen microshard index drift")
    core = _core(packet["git"])
    started = time.perf_counter()
    rows = []
    all_records = {label: [] for label in core.LABEL_ORDER}
    first = microshard_index * MICROSHARD_CLUSTERS
    for local_index in range(MICROSHARD_CLUSTERS):
        cluster_index = first + local_index
        seed = SCREEN_SEED0 + STREAM_STRIDE * cluster_index
        by_label = {
            label: core.play_arm_cluster(label, seed, run_id=RUN_ID)
            for label in core.LABEL_ORDER
        }
        rows.append(cluster_row(core=core, cluster_index=cluster_index,
                                seed=seed, by_label=by_label))
        for label in core.LABEL_ORDER:
            all_records[label].extend(by_label[label])
        if ((local_index + 1) % progress_every == 0
                or local_index + 1 == MICROSHARD_CLUSTERS):
            print(json.dumps({
                "event": "pair-checkpoint-microshard-progress-v1",
                "microshard_index": microshard_index,
                "clusters_complete": local_index + 1,
                "clusters_total": MICROSHARD_CLUSTERS,
            }, sort_keys=True), flush=True)
    elapsed = time.perf_counter() - started
    counts = {
        label: {
            "records": len(records),
            "arm": _plain_totals(core, records, "arm"),
            "opp": _plain_totals(core, records, "opp"),
            "arm_pair": _pair_totals(core, records, "arm"),
            "opp_pair": _pair_totals(core, records, "opp"),
        }
        for label, records in all_records.items()
    }
    value = {
        "schema": OUTCOME_SCHEMA,
        "run_id": RUN_ID,
        "git": packet["git"],
        "packet_sha256": packet_sha256,
        "packet_internal_sha256": packet["internal_sha256"],
        "runtime_profile_sha256": packet["runtime_profile_sha256"],
        "microshard_index": microshard_index,
        "cluster_index_start": first,
        "clusters": MICROSHARD_CLUSTERS,
        "seed0": SCREEN_SEED0 + STREAM_STRIDE * first,
        "stream_stride": STREAM_STRIDE,
        "elapsed_seconds": elapsed,
        "cluster_rows": rows,
        "counts": counts,
        "natural_dose": dose_summary(rows),
        "exact_work_complete": True,
        "aggregate_execution_authorized": False,
        "outcome_access_authorized": False,
        "strength_claim": False,
        "production_deployment": False,
        "retry_or_extension_authorized": False,
    }
    value["internal_sha256"] = digest(value)
    return value


def _integer_pair(value: object, allowed: range) -> bool:
    return (isinstance(value, list) and len(value) == 2
            and all(isinstance(item, int) and not isinstance(item, bool)
                    and item in allowed for item in value))


def validate_outcome(value: object, *, packet: dict, packet_sha256: str,
                     microshard_index: int, core=None) -> None:
    if not isinstance(value, dict):
        raise ScreenRefused("microshard outcome is not an object")
    if core is None:
        core = _core(packet["git"])
    unsigned = dict(value)
    observed = unsigned.pop("internal_sha256", None)
    first = microshard_index * MICROSHARD_CLUSTERS
    rows = value.get("cluster_rows")
    expected_fields = {
        "schema", "run_id", "git", "packet_sha256",
        "packet_internal_sha256", "runtime_profile_sha256",
        "microshard_index", "cluster_index_start", "clusters", "seed0",
        "stream_stride", "elapsed_seconds", "cluster_rows", "counts",
        "natural_dose", "exact_work_complete",
        "aggregate_execution_authorized", "outcome_access_authorized",
        "strength_claim", "production_deployment",
        "retry_or_extension_authorized", "internal_sha256",
    }
    if (set(value) != expected_fields or observed != digest(unsigned)
            or value.get("schema") != OUTCOME_SCHEMA
            or value.get("run_id") != RUN_ID
            or value.get("git") != packet["git"]
            or value.get("packet_sha256") != packet_sha256
            or value.get("packet_internal_sha256")
            != packet["internal_sha256"]
            or value.get("runtime_profile_sha256")
            != packet["runtime_profile_sha256"]
            or value.get("microshard_index") != microshard_index
            or value.get("cluster_index_start") != first
            or value.get("clusters") != MICROSHARD_CLUSTERS
            or value.get("seed0") != SCREEN_SEED0 + STREAM_STRIDE * first
            or value.get("stream_stride") != STREAM_STRIDE
            or not isinstance(value.get("elapsed_seconds"), (int, float))
            or isinstance(value.get("elapsed_seconds"), bool)
            or not math.isfinite(value["elapsed_seconds"])
            or value["elapsed_seconds"] <= 0
            or not isinstance(rows, list)
            or len(rows) != MICROSHARD_CLUSTERS
            or value.get("exact_work_complete") is not True
            or any(value.get(field) is not False for field in (
                "aggregate_execution_authorized", "outcome_access_authorized",
                "strength_claim", "production_deployment",
                "retry_or_extension_authorized"))):
        raise ScreenRefused(
            f"microshard {microshard_index} outcome identity drift")
    for local_index, row in enumerate(rows):
        cluster_index = first + local_index
        seed = SCREEN_SEED0 + STREAM_STRIDE * cluster_index
        utility = row.get("level_utility", {}) if isinstance(row, dict) else {}
        won = row.get("won", {}) if isinstance(row, dict) else {}
        if (not isinstance(row, dict)
                or set(row) != {"cluster_index", "seed", "level_utility",
                                "won", "natural_dose"}
                or row.get("cluster_index") != cluster_index
                or row.get("seed") != seed
                or list(utility) != list(core.LABEL_ORDER)
                or list(won) != list(core.LABEL_ORDER)
                or not all(_integer_pair(utility[label], range(-101, 102))
                           for label in core.LABEL_ORDER)
                or not all(_integer_pair(won[label], range(2))
                           for label in core.LABEL_ORDER)
                or utility["matched_null"] != utility["champion"]
                or won["matched_null"] != won["champion"]
                or not isinstance(row.get("natural_dose"), list)
                or len(row["natural_dose"]) != 2):
            raise ScreenRefused(
                f"microshard {microshard_index} cluster-row drift")
    if value.get("natural_dose") != dose_summary(rows):
        raise ScreenRefused(f"microshard {microshard_index} dose drift")
    counts = value.get("counts")
    if not isinstance(counts, dict) or list(counts) != list(core.LABEL_ORDER):
        raise ScreenRefused(f"microshard {microshard_index} counts drift")
    plain_fields = set(core.counters([]))
    for label, expected_mode in (
            ("treatment", "treatment"),
            ("matched_null", "matched_null"),
            ("champion", "off")):
        item = counts.get(label)
        if (not isinstance(item, dict)
                or set(item) != {"records", "arm", "opp", "arm_pair",
                                 "opp_pair"}
                or item["records"] != 2 * MICROSHARD_CLUSTERS
                or set(item["arm"]) != plain_fields
                or set(item["opp"]) != plain_fields
                or core.telemetry_problems(
                    item["arm_pair"], expected_mode=expected_mode)
                or core.telemetry_problems(
                    item["opp_pair"], expected_mode="off")):
            raise ScreenRefused(
                f"microshard {microshard_index} {label} work drift")
        for side in ("arm", "opp"):
            counters = item[side]
            for name, counter in counters.items():
                valid = ((name == "search_secs"
                          and isinstance(counter, (int, float))
                          and not isinstance(counter, bool)
                          and math.isfinite(counter) and counter >= 0)
                         or (name != "search_secs"
                             and isinstance(counter, int)
                             and not isinstance(counter, bool)
                             and counter >= 0))
                if not valid:
                    raise ScreenRefused(
                        f"microshard {microshard_index} counter drift")
            if counters["sample_attempts"] != (
                    counters["accepted_worlds"] + counters["failed_worlds"]):
                raise ScreenRefused(
                    f"microshard {microshard_index} sampler drift")
            if counters["accepted_worlds"] != (
                    (core.ROOT_WORLDS + core.REPORT_WORLDS)
                    * counters["searches"]):
                raise ScreenRefused(
                    f"microshard {microshard_index} search-dose drift")


def _forbidden_keys(value: object) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if isinstance(key, str) and key.lower() in FORBIDDEN_RECEIPT_KEYS:
                found.add(key)
            found.update(_forbidden_keys(child))
    elif isinstance(value, list):
        for child in value:
            found.update(_forbidden_keys(child))
    return found


def receipt_payload(*, packet: dict, packet_sha256: str,
                    microshard_index: int, outcome_raw: bytes,
                    elapsed_seconds: float) -> dict:
    first = microshard_index * MICROSHARD_CLUSTERS
    value = {
        "schema": RECEIPT_SCHEMA,
        "run_id": RUN_ID,
        "git": packet["git"],
        "packet_sha256": packet_sha256,
        "packet_internal_sha256": packet["internal_sha256"],
        "campaign_runtime_profile_sha256": packet["runtime_profile_sha256"],
        "microshard_index": microshard_index,
        "cluster_index_start": first,
        "seed0": SCREEN_SEED0 + STREAM_STRIDE * first,
        "clusters": MICROSHARD_CLUSTERS,
        "outcome_filename": "outcome.json",
        "outcome_sha256": sha256_bytes(outcome_raw),
        "outcome_size_bytes": len(outcome_raw),
        "elapsed_seconds": elapsed_seconds,
        "outcomes_opened_by_supervisor": False,
        "statistics_published": False,
        "aggregate_execution_authorized": False,
        "strength_claim": False,
        "production_deployment": False,
        "retry_or_extension_authorized": False,
    }
    value["internal_sha256"] = digest(value)
    return value


def receipt_problems(value: object, *, packet: dict, packet_sha256: str,
                     microshard_index: int) -> list[str]:
    if not isinstance(value, dict):
        return ["microshard receipt is not an object"]
    unsigned = dict(value)
    observed = unsigned.pop("internal_sha256", None)
    first = microshard_index * MICROSHARD_CLUSTERS
    expected_fields = {
        "schema", "run_id", "git", "packet_sha256",
        "packet_internal_sha256", "campaign_runtime_profile_sha256",
        "microshard_index", "cluster_index_start", "seed0", "clusters",
        "outcome_filename", "outcome_sha256", "outcome_size_bytes",
        "elapsed_seconds", "outcomes_opened_by_supervisor",
        "statistics_published", "aggregate_execution_authorized",
        "strength_claim", "production_deployment",
        "retry_or_extension_authorized", "internal_sha256",
    }
    problems = []
    if set(value) != expected_fields:
        problems.append("microshard receipt field population drift")
    if _forbidden_keys(value):
        problems.append("microshard receipt contains outcome-bearing keys")
    if (observed != digest(unsigned)
            or value.get("schema") != RECEIPT_SCHEMA
            or value.get("run_id") != RUN_ID
            or value.get("git") != packet["git"]
            or value.get("packet_sha256") != packet_sha256
            or value.get("packet_internal_sha256")
            != packet["internal_sha256"]
            or value.get("campaign_runtime_profile_sha256")
            != packet["runtime_profile_sha256"]
            or value.get("microshard_index") != microshard_index
            or value.get("cluster_index_start") != first
            or value.get("seed0") != SCREEN_SEED0 + STREAM_STRIDE * first
            or value.get("clusters") != MICROSHARD_CLUSTERS
            or value.get("outcome_filename") != "outcome.json"
            or not is_sha256(value.get("outcome_sha256"))
            or not isinstance(value.get("outcome_size_bytes"), int)
            or isinstance(value.get("outcome_size_bytes"), bool)
            or value["outcome_size_bytes"] <= 0
            or not isinstance(value.get("elapsed_seconds"), (int, float))
            or isinstance(value.get("elapsed_seconds"), bool)
            or not math.isfinite(value["elapsed_seconds"])
            or value["elapsed_seconds"] <= 0
            or any(value.get(field) is not False for field in (
                "outcomes_opened_by_supervisor", "statistics_published",
                "aggregate_execution_authorized", "strength_claim",
                "production_deployment", "retry_or_extension_authorized"))):
        problems.append("microshard receipt identity/authority drift")
    return sorted(set(problems))


def publish_bundle(*, path: Path, partial: Path, outcome: dict,
                   receipt: dict) -> None:
    if os.path.lexists(path) or os.path.lexists(partial):
        raise ScreenRefused(f"microshard bundle slot already consumed: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    os.mkdir(partial, 0o700)
    try:
        for name, value in (("outcome.json", outcome),
                            ("receipt.json", receipt)):
            child = partial / name
            raw = canonical(value)
            with child.open("xb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            child.chmod(0o444)
        descriptor = os.open(partial, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0))
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.rename(partial, path)
        path.chmod(0o555)
        parent_descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(parent_descriptor)
        finally:
            os.close(parent_descriptor)
    except BaseException:
        # Preserve any partial bytes for incident review; never erase or retry.
        raise


def publish_execution_gate(*, marker: bytes, admission: dict) -> None:
    if os.path.lexists(GATE_PATH) or os.path.lexists(GATE_PARTIAL_PATH):
        raise ScreenRefused("screen execution gate slot already consumed")
    GATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    os.mkdir(GATE_PARTIAL_PATH, 0o700)
    for name, raw in (
            ("packet-review-snapshot.md", marker),
            ("admission.json", canonical(admission))):
        child = GATE_PARTIAL_PATH / name
        with child.open("xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        child.chmod(0o444)
    descriptor = os.open(
        GATE_PARTIAL_PATH, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.rename(GATE_PARTIAL_PATH, GATE_PATH)
    GATE_PATH.chmod(0o555)
    parent_descriptor = os.open(GATE_PATH.parent, os.O_RDONLY)
    try:
        os.fsync(parent_descriptor)
    finally:
        os.close(parent_descriptor)


def read_receipt_only(*, packet: dict, packet_sha256: str,
                      microshard_index: int) -> dict:
    bundle = BUNDLE_PATHS[microshard_index]
    try:
        bundle_stat = bundle.lstat()
    except OSError as exc:
        raise ScreenRefused(f"microshard {microshard_index} bundle missing") \
            from exc
    if (not stat.S_ISDIR(bundle_stat.st_mode)
            or bundle_stat.st_uid != 0
            or bundle_stat.st_mode & 0o222):
        raise ScreenRefused(f"microshard {microshard_index} bundle drift")
    try:
        children = sorted(child.name for child in bundle.iterdir())
    except OSError as exc:
        raise ScreenRefused(
            f"microshard {microshard_index} bundle is unreadable") from exc
    if children != ["outcome.json", "receipt.json"]:
        raise ScreenRefused(
            f"microshard {microshard_index} bundle population drift")
    receipt, _ = strict_object(
        bundle / "receipt.json", label=f"microshard {microshard_index} receipt",
        root_owned=True, nonwritable=True)
    problems = receipt_problems(
        receipt, packet=packet, packet_sha256=packet_sha256,
        microshard_index=microshard_index)
    if problems:
        raise ScreenRefused("; ".join(problems))
    outcome_path = bundle / receipt["outcome_filename"]
    try:
        outcome_stat = outcome_path.lstat()
    except OSError as exc:
        raise ScreenRefused(f"microshard {microshard_index} outcome missing") \
            from exc
    if (not stat.S_ISREG(outcome_stat.st_mode)
            or outcome_stat.st_nlink != 1
            or outcome_stat.st_uid != 0
            or outcome_stat.st_mode & 0o222
            or outcome_stat.st_size != receipt["outcome_size_bytes"]):
        raise ScreenRefused(
            f"microshard {microshard_index} sealed outcome metadata drift")
    return receipt


def manifest_payload(*, packet: dict, packet_sha256: str) -> dict:
    rows = []
    for index in range(MICROSHARDS):
        receipt = read_receipt_only(
            packet=packet, packet_sha256=packet_sha256,
            microshard_index=index)
        rows.append({
            "microshard_index": index,
            "cluster_index_start": receipt["cluster_index_start"],
            "seed0": receipt["seed0"],
            "clusters": receipt["clusters"],
            "sha256": receipt["outcome_sha256"],
            "elapsed_seconds": receipt["elapsed_seconds"],
            "worker_runtime_profile_sha256":
                receipt["campaign_runtime_profile_sha256"],
        })
    value = {
        "schema": DESIGN.MANIFEST_SCHEMA,
        "run_id": RUN_ID,
        "packet_sha256": packet_sha256,
        "outcomes_opened": False,
        "statistics_published": False,
        "aggregate_execution_authorized": False,
        "population": {
            "seed0": SCREEN_SEED0,
            "clusters": SCREEN_CLUSTERS,
            "stream_stride": STREAM_STRIDE,
            "max_role_offset": DESIGN.MAX_ROLE_OFFSET,
            "microshard_clusters": MICROSHARD_CLUSTERS,
            "microshards": MICROSHARDS,
        },
        "campaign_runtime_profile_sha256": packet["runtime_profile_sha256"],
        "completed": rows,
    }
    problems = DESIGN.manifest_problems(
        value, packet_sha256=packet_sha256,
        runtime_profile_sha256=packet["runtime_profile_sha256"])
    if problems or len(rows) != MICROSHARDS:
        raise ScreenRefused("; ".join(problems or ["manifest incomplete"]))
    return value


def admission_payload(*, packet: dict, packet_sha256: str,
                      packet_review: dict, invocation_id: str) -> dict:
    value = {
        "schema": ADMISSION_SCHEMA,
        "run_id": RUN_ID,
        "git": packet["git"],
        "packet_sha256": packet_sha256,
        "packet_internal_sha256": packet["internal_sha256"],
        "packet_review_commit": packet_review["commit"],
        "packet_review_marker_sha256": packet_review["marker_sha256"],
        "runtime_profile_sha256": packet["runtime_profile_sha256"],
        "systemd_invocation_id": invocation_id,
        "nonce": secrets.token_hex(32),
        "created_time_ns": time.time_ns(),
        "one_screen_execution_authorized": True,
        "resume_execution_authorized": False,
        "aggregate_execution_authorized": False,
        "outcome_access_authorized": False,
        "strength_claim": False,
        "production_deployment": False,
        "retry_or_extension_authorized": False,
    }
    value["internal_sha256"] = digest(value)
    return value


def admission_problems(value: object, *, packet: dict, packet_sha256: str,
                       packet_review: dict, invocation_id: str) -> list[str]:
    if not isinstance(value, dict):
        return ["screen admission is not an object"]
    unsigned = dict(value)
    observed = unsigned.pop("internal_sha256", None)
    problems = []
    if (observed != digest(unsigned)
            or value.get("schema") != ADMISSION_SCHEMA
            or value.get("run_id") != RUN_ID
            or value.get("git") != packet["git"]
            or value.get("packet_sha256") != packet_sha256
            or value.get("packet_internal_sha256")
            != packet["internal_sha256"]
            or value.get("packet_review_commit") != packet_review["commit"]
            or value.get("packet_review_marker_sha256")
            != packet_review["marker_sha256"]
            or value.get("runtime_profile_sha256")
            != packet["runtime_profile_sha256"]
            or value.get("systemd_invocation_id") != invocation_id
            or not is_sha256(value.get("nonce"))
            or not isinstance(value.get("created_time_ns"), int)
            or isinstance(value.get("created_time_ns"), bool)
            or value["created_time_ns"] <= 0
            or value.get("one_screen_execution_authorized") is not True
            or any(value.get(field) is not False for field in (
                "resume_execution_authorized", "aggregate_execution_authorized",
                "outcome_access_authorized", "strength_claim",
                "production_deployment", "retry_or_extension_authorized"))):
        problems.append("screen admission identity/authority drift")
    return problems


def _systemd_properties(unit: str) -> dict[str, str]:
    fields = (
        "Id", "InvocationID", "LoadState", "ActiveState", "SubState",
        "Type", "Restart", "KillMode", "UID", "ControlGroup",
        "WorkingDirectory", "NRestarts", "FragmentPath", "DropInPaths",
        "NeedDaemonReload", "Environment", "Nice", "RuntimeMaxUSec",
    )
    completed = subprocess.run(
        ["systemctl", "show", unit, "--no-pager",
         *[f"--property={field}" for field in fields]],
        check=True, capture_output=True, text=True)
    result = {}
    for line in completed.stdout.splitlines():
        key, separator, value = line.partition("=")
        if separator and key in fields and key not in result:
            result[key] = value
    return result


def require_systemd(expected_unit_sha256: str) -> str:
    invocation = os.environ.get("INVOCATION_ID", "")
    link = Path("/run/systemd/units") / f"invocation:{SYSTEMD_UNIT}"
    if (not is_sha256(expected_unit_sha256)
            or expected_unit_sha256 != sha256_bytes(systemd_unit_bytes())
            or os.geteuid() != 0
            or len(invocation) != 32
            or any(character not in "0123456789abcdef"
                   for character in invocation)
            or not os.path.lexists(link)
            or not link.is_symlink()
            or os.readlink(link) != invocation):
        raise ScreenRefused("screen run requires a live root systemd unit")
    properties = _systemd_properties(SYSTEMD_UNIT)
    expected = {
        "Id": SYSTEMD_UNIT,
        "InvocationID": invocation,
        "LoadState": "loaded",
        "ActiveState": "active",
        "SubState": "running",
        "Type": "exec",
        "Restart": "no",
        "KillMode": "control-group",
        "WorkingDirectory": str(REPO),
        "NRestarts": "0",
        "FragmentPath": f"/etc/systemd/system/{SYSTEMD_UNIT}",
        "DropInPaths": "",
        "NeedDaemonReload": "no",
        "Environment": (
            "PYTHONDONTWRITEBYTECODE=1 PYTHONHASHSEED=0 SHENGJI_FAST=1 "
            "SHENGJI_REQUIRE_VOIDS=1 PYTHONPATH=server:server/scripts"
        ),
        "Nice": "5",
        "RuntimeMaxUSec": "2d 4h",
    }
    if (any(properties.get(key) != value for key, value in expected.items())
            or properties.get("UID") not in {"0", "[not set]"}
            or not properties.get("ControlGroup", "").startswith(
                "/system.slice/")):
        raise ScreenRefused("screen systemd one-shot identity drift")
    fragment = Path(properties["FragmentPath"])
    raw = stable_bytes(fragment, label="installed screen systemd unit",
                       root_owned=True, nonwritable=True)
    if raw != systemd_unit_bytes() or sha256_bytes(raw) != expected_unit_sha256:
        raise ScreenRefused("installed screen systemd unit bytes drift")
    try:
        memberships = Path("/proc/self/cgroup").read_text().splitlines()
    except OSError as exc:
        raise ScreenRefused("cannot authenticate screen cgroup") from exc
    if not any(line.endswith(f":{properties['ControlGroup']}")
               for line in memberships):
        raise ScreenRefused("screen process is outside reviewed cgroup")
    return invocation


def _child_argv(*, packet_sha256: str, index: int) -> list[str]:
    return [
        sys.executable, "-I", "-P", "-B", str(SCRIPT), "run-microshard",
        "--expected-git", git("rev-parse", "HEAD"),
        "--packet", str(PACKET_PATH),
        "--expected-packet-sha256", packet_sha256,
        "--admission", str(ADMISSION_PATH),
        "--microshard-index", str(index),
        "--out", str(BUNDLE_PATHS[index]),
    ]


def run_microshard_command(args: argparse.Namespace) -> None:
    require_fresh_process()
    require_clean_exact_git(args.expected_git)
    if (args.microshard_index < 0 or args.microshard_index >= MICROSHARDS
            or Path(args.out).resolve()
            != BUNDLE_PATHS[args.microshard_index].resolve()
            or Path(args.admission).resolve() != ADMISSION_PATH.resolve()):
        raise ScreenRefused("microshard execution path/index drift")
    packet = load_packet(Path(args.packet), args.expected_packet_sha256,
                         expected_git=args.expected_git)
    invocation = require_systemd(packet["runtime"]["systemd_unit"]["sha256"])
    if runtime_snapshot(args.expected_git) != packet["runtime"]:
        raise ScreenRefused("microshard runtime differs from packet")
    admission, _ = strict_object(
        ADMISSION_PATH, label="screen admission", root_owned=True,
        nonwritable=True)
    claim = packet_review_claim(
        packet=packet, packet_sha256=args.expected_packet_sha256)
    review, marker = canonical_review_record(
        commit=admission.get("packet_review_commit", ""),
        prefix=PACKET_REVIEW_PREFIX, expected=claim,
        label="checkpoint screen packet review")
    snapshot = stable_bytes(
        PACKET_REVIEW_PATH, label="packet review snapshot",
        root_owned=True, nonwritable=True)
    problems = admission_problems(
        admission, packet=packet,
        packet_sha256=args.expected_packet_sha256,
        packet_review=review, invocation_id=invocation)
    if (problems or snapshot != marker
            or sha256_bytes(snapshot) != review["marker_sha256"]):
        raise ScreenRefused("microshard admission/review drift")
    outcome = run_microshard_payload(
        packet=packet, packet_sha256=args.expected_packet_sha256,
        microshard_index=args.microshard_index)
    validate_outcome(
        outcome, packet=packet, packet_sha256=args.expected_packet_sha256,
        microshard_index=args.microshard_index)
    outcome_raw = canonical(outcome)
    receipt = receipt_payload(
        packet=packet, packet_sha256=args.expected_packet_sha256,
        microshard_index=args.microshard_index, outcome_raw=outcome_raw,
        elapsed_seconds=outcome["elapsed_seconds"])
    problems = receipt_problems(
        receipt, packet=packet, packet_sha256=args.expected_packet_sha256,
        microshard_index=args.microshard_index)
    if problems:
        raise ScreenRefused("; ".join(problems))
    publish_bundle(
        path=BUNDLE_PATHS[args.microshard_index],
        partial=PARTIAL_BUNDLE_PATHS[args.microshard_index],
        outcome=outcome, receipt=receipt)
    print(json.dumps({
        "status": "MICROSHARD_COMPLETE",
        "microshard_index": args.microshard_index,
        "outcome_sha256": receipt["outcome_sha256"],
    }, sort_keys=True))


def supervise(*, packet: dict, packet_sha256: str) -> dict:
    pending = list(range(MICROSHARDS))
    active: dict[int, tuple[subprocess.Popen, object, float]] = {}
    completed = 0
    last_heartbeat = 0.0
    interrupted = {"signal": None}

    def handle_signal(signum, _frame):
        interrupted["signal"] = int(signum)

    old_handlers = {
        signum: signal.signal(signum, handle_signal)
        for signum in (signal.SIGINT, signal.SIGTERM)
    }
    try:
        while pending or active:
            if interrupted["signal"] is not None:
                raise ScreenRefused(
                    f"screen supervisor received signal {interrupted['signal']}")
            while pending and len(active) < WORKERS:
                index = pending.pop(0)
                LOG_PATHS[index].parent.mkdir(parents=True, exist_ok=True)
                handle = LOG_PATHS[index].open("xb")
                process = subprocess.Popen(
                    _child_argv(packet_sha256=packet_sha256, index=index),
                    stdout=handle, stderr=subprocess.STDOUT, cwd=REPO)
                active[index] = (process, handle, time.monotonic())
            for index, (process, handle, child_started) in list(active.items()):
                code = process.poll()
                if code is None:
                    if time.monotonic() - child_started > (
                            packet["capacity_evidence"]["projection"]
                            ["microshard_timeout_seconds"]):
                        raise ScreenRefused(
                            f"microshard {index} exceeded reviewed timeout")
                    continue
                handle.close()
                LOG_PATHS[index].chmod(0o444)
                del active[index]
                if code != 0:
                    raise ScreenRefused(
                        f"microshard {index} exited with status {code}")
                read_receipt_only(
                    packet=packet, packet_sha256=packet_sha256,
                    microshard_index=index)
                completed += 1
            if time.monotonic() - last_heartbeat >= 30.0:
                print(json.dumps({
                    "event": "pair-checkpoint-supervisor-progress-v1",
                    "microshards_complete": completed,
                    "microshards_total": MICROSHARDS,
                    "workers_alive": len(active),
                    "outcomes_opened": False,
                }, sort_keys=True), flush=True)
                last_heartbeat = time.monotonic()
            if pending or active:
                time.sleep(1.0)
        manifest = manifest_payload(packet=packet, packet_sha256=packet_sha256)
        write_exclusive(MANIFEST_PATH, manifest)
        return manifest
    finally:
        for process, _handle, _started in active.values():
            if process.poll() is None:
                process.terminate()
        for process, handle, _started in active.values():
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            if not handle.closed:
                handle.close()
        for signum, handler in old_handlers.items():
            signal.signal(signum, handler)


def freeze_command(args: argparse.Namespace) -> None:
    require_fresh_process()
    require_clean_exact_git(args.expected_git)
    if Path(args.out).resolve() != PACKET_PATH.resolve():
        raise ScreenRefused("screen packet output path is not canonical")
    claim = implementation_review_claim(expected_git=args.expected_git)
    review, marker = canonical_review_record(
        commit=args.implementation_review_commit,
        prefix=IMPLEMENTATION_REVIEW_PREFIX, expected=claim,
        label="checkpoint screen implementation review")
    runtime = runtime_snapshot(args.expected_git)
    require_frozen_runtime_inputs(runtime)
    capacity = capacity_evidence(screen_runtime=runtime)
    packet = packet_payload(
        expected_git=args.expected_git, runtime=runtime,
        implementation_review=review, capacity=capacity)
    collisions = [path for path in (PACKET_PATH, IMPLEMENTATION_REVIEW_PATH)
                  if os.path.lexists(path)
                  or os.path.lexists(str(path) + ".partial")]
    if collisions:
        raise ScreenRefused("screen packet freeze slot already consumed")
    write_bytes_exclusive(IMPLEMENTATION_REVIEW_PATH, marker)
    write_exclusive(PACKET_PATH, packet)
    packet_sha = sha256_file(PACKET_PATH)
    print(json.dumps({
        "status": "FROZEN_AWAITING_PACKET_REVIEW",
        "packet_sha256": packet_sha,
        "packet_internal_sha256": packet["internal_sha256"],
        "packet_review_claim": packet_review_claim(
            packet=packet, packet_sha256=packet_sha),
        "screen_execution_authorized": False,
    }, sort_keys=True))


def implementation_review_claim_command(args: argparse.Namespace) -> None:
    require_fresh_process()
    require_clean_exact_git(args.expected_git)
    claim = implementation_review_claim(expected_git=args.expected_git)
    sys.stdout.buffer.write(_canonical_marker(
        IMPLEMENTATION_REVIEW_PREFIX, claim))


def verify_command(args: argparse.Namespace) -> None:
    require_fresh_process()
    packet = load_packet(Path(args.packet), args.expected_packet_sha256,
                         expected_git=args.expected_git)
    print(json.dumps({
        "verified": True,
        "packet_sha256": args.expected_packet_sha256,
        "packet_internal_sha256": packet["internal_sha256"],
    }, sort_keys=True))


def run_screen_command(args: argparse.Namespace) -> None:
    require_fresh_process()
    require_clean_exact_git(args.expected_git)
    if (Path(args.packet).resolve() != PACKET_PATH.resolve()
            or Path(args.admission).resolve() != ADMISSION_PATH.resolve()):
        raise ScreenRefused("screen execution path is not canonical")
    packet = load_packet(Path(args.packet), args.expected_packet_sha256,
                         expected_git=args.expected_git)
    invocation = require_systemd(packet["runtime"]["systemd_unit"]["sha256"])
    if runtime_snapshot(args.expected_git) != packet["runtime"]:
        raise ScreenRefused("live screen runtime differs from packet")
    require_frozen_runtime_inputs(packet["runtime"])
    claim = packet_review_claim(
        packet=packet, packet_sha256=args.expected_packet_sha256)
    review, marker = canonical_review_record(
        commit=args.packet_review_commit, prefix=PACKET_REVIEW_PREFIX,
        expected=claim, label="checkpoint screen packet review")
    collisions = [path for path in (
        GATE_PATH, GATE_PARTIAL_PATH, MANIFEST_PATH,
        *BUNDLE_PATHS, *PARTIAL_BUNDLE_PATHS, *LOG_PATHS)
        if os.path.lexists(path) or os.path.lexists(str(path) + ".partial")]
    if collisions:
        raise ScreenRefused("screen execution slot already consumed")
    admission = admission_payload(
        packet=packet, packet_sha256=args.expected_packet_sha256,
        packet_review=review, invocation_id=invocation)
    problems = admission_problems(
        admission, packet=packet, packet_sha256=args.expected_packet_sha256,
        packet_review=review, invocation_id=invocation)
    if problems:
        raise ScreenRefused("; ".join(problems))
    publish_execution_gate(marker=marker, admission=admission)
    manifest = supervise(packet=packet,
                         packet_sha256=args.expected_packet_sha256)
    print(json.dumps({
        "status": "SCREEN_COMPLETE_AWAITING_MANIFEST_REVIEW",
        "manifest_sha256": sha256_file(MANIFEST_PATH),
        "microshards_complete": len(manifest["completed"]),
        "outcomes_opened": False,
        "aggregate_execution_authorized": False,
    }, sort_keys=True))


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    unit = commands.add_parser("unit-template")
    unit.set_defaults(func=lambda _args: sys.stdout.buffer.write(
        systemd_unit_bytes()))
    implementation = commands.add_parser("implementation-review-claim")
    implementation.add_argument("--expected-git", required=True)
    implementation.set_defaults(func=implementation_review_claim_command)
    freeze = commands.add_parser("freeze")
    freeze.add_argument("--expected-git", required=True)
    freeze.add_argument("--implementation-review-commit", required=True)
    freeze.add_argument("--out", type=Path, required=True)
    freeze.set_defaults(func=freeze_command)
    verify = commands.add_parser("verify")
    verify.add_argument("--expected-git", required=True)
    verify.add_argument("--packet", type=Path, required=True)
    verify.add_argument("--expected-packet-sha256", required=True)
    verify.set_defaults(func=verify_command)
    run = commands.add_parser("run-screen")
    run.add_argument("--expected-git", required=True)
    run.add_argument("--packet", type=Path, required=True)
    run.add_argument("--expected-packet-sha256", required=True)
    run.add_argument("--packet-review-commit", required=True)
    run.add_argument("--admission", type=Path, required=True)
    run.set_defaults(func=run_screen_command)
    micro = commands.add_parser("run-microshard")
    micro.add_argument("--expected-git", required=True)
    micro.add_argument("--packet", type=Path, required=True)
    micro.add_argument("--expected-packet-sha256", required=True)
    micro.add_argument("--admission", type=Path, required=True)
    micro.add_argument("--microshard-index", type=int, required=True)
    micro.add_argument("--out", type=Path, required=True)
    micro.set_defaults(func=run_microshard_command)
    return root


def main() -> int:
    try:
        require_fresh_process()
        args = parser().parse_args()
        args.func(args)
    except (ScreenRefused, CAPACITY.CapacityRefused,
            OSError, ValueError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"REFUSED: {exc}") from exc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
