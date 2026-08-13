#!/usr/bin/env python3
"""Concurrent score-free capacity gate for the checkpointed Pair successor.

This is deliberately only the first executable layer of the reviewed
checkpoint-successor design.  It can freeze and run one 16-lane capacity
packet; it cannot freeze or run the scored screen, resume a microshard,
aggregate outcomes, or authorize strength/deployment.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import math
import multiprocessing
import os
import platform
import secrets
import stat
import subprocess
import sys
import sysconfig
import time
import types
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
SERVER = REPO / "server"
REVIEW_LEDGER = "HANDOFF_REVIEW.md"
CANONICAL_REVIEW_REF = "origin/main"
REVIEWER_NAME = "Claude"
REVIEWER_EMAIL = "noreply@anthropic.com"
REVIEWER_SESSION_TRAILER = "Claude-Session: https://claude.ai/code/session_"

DESIGN_GIT = "36b3841f28e04a1b3ba066044db0ed8c992e8714"
DESIGN_SOURCE_SHA256 = (
    "259e8dba94af04bb4d26e1146202587c5efcfce7812c3d3b3224ecd1a250bc34"
)
DUEL_SOURCE_SHA256 = (
    "c034f1cd04f97c6cd0e9877eb3fe186ee59194be27d93bb1b8d01e4e9ff9cc2b"
)
DESIGN_MODULE = "pair_aware_rollout_checkpoint_successor_design"
CORE_MODULE = "pair_aware_rollout_duel"
DESIGN_PATH = SERVER / "scripts/pair_aware_rollout_checkpoint_successor_design.py"
CORE_PATH = SERVER / "scripts/pair_aware_rollout_duel.py"
PRELOADED_SHENGJI_MODULES = tuple(sorted(
    name for name in sys.modules
    if name == "shengji" or name.startswith("shengji.")
))


def _authenticated_design_module():
    raw = DESIGN_PATH.read_bytes()
    if hashlib.sha256(raw).hexdigest() != DESIGN_SOURCE_SHA256:
        raise RuntimeError("reviewed successor design source drift")
    preloaded = sys.modules.get(DESIGN_MODULE)
    if preloaded is not None:
        origin = getattr(preloaded, "__file__", None)
        if not isinstance(origin, str) or Path(origin).resolve() != DESIGN_PATH:
            raise RuntimeError("preloaded successor design origin drift")
        return preloaded, True
    module = types.ModuleType(DESIGN_MODULE)
    module.__file__ = str(DESIGN_PATH)
    module.__package__ = ""
    sys.modules[DESIGN_MODULE] = module
    try:
        exec(compile(raw, str(DESIGN_PATH), "exec"), module.__dict__)
    except BaseException:
        sys.modules.pop(DESIGN_MODULE, None)
        raise
    return module, False


DESIGN, DESIGN_WAS_PRELOADED = _authenticated_design_module()
CORE_WAS_PRELOADED = CORE_MODULE in sys.modules
CORE = None
PACKET_SCHEMA = "pair-aware-rollout-checkpoint-capacity-packet-v2"
ADMISSION_SCHEMA = "pair-aware-rollout-checkpoint-capacity-admission-v2"
RECEIPT_SCHEMA = "pair-aware-rollout-checkpoint-capacity-receipt-v2"
REFUSAL_RECEIPT_SCHEMA = (
    "pair-aware-rollout-checkpoint-capacity-refusal-receipt-v1"
)
IMPLEMENTATION_REVIEW_SCHEMA = (
    "pair-aware-rollout-checkpoint-capacity-implementation-review-v2"
)
PACKET_REVIEW_SCHEMA = (
    "pair-aware-rollout-checkpoint-capacity-packet-review-v2"
)
# The V1 marker was appended by a Jerry-authored/co-authored commit.  That
# records a valid prose review, but it deliberately cannot satisfy this
# controller's independent Claude author+committer gate.  Retire that
# namespace and require a fresh, independently introduced V2 attestation.
RETIRED_IMPLEMENTATION_REVIEW_PREFIX = (
    "PAIR_AWARE_ROLLOUT_CHECKPOINT_CAPACITY_IMPLEMENTATION_V2_REVIEW "
)
IMPLEMENTATION_REVIEW_PREFIX = (
    "PAIR_AWARE_ROLLOUT_CHECKPOINT_CAPACITY_IMPLEMENTATION_V3_REVIEW "
)
PACKET_REVIEW_PREFIX = (
    "PAIR_AWARE_ROLLOUT_CHECKPOINT_CAPACITY_PACKET_V2_REVIEW "
)

RUN_ID = DESIGN.CAPACITY_RUN_ID
RUN_DIR = SERVER / "runs/logs" / RUN_ID
LOCK_DIR = SERVER / "runs/locks"
PACKET_PATH = RUN_DIR / "controller-packet.json"
IMPLEMENTATION_REVIEW_PATH = RUN_DIR / "implementation-review-snapshot.md"
PACKET_REVIEW_PATH = RUN_DIR / "packet-review-snapshot.md"
RESULT_PATH = RUN_DIR / "capacity.json"
RECEIPT_PATH = RUN_DIR / "execution-receipt.json"
REFUSAL_RECEIPT_PATH = RUN_DIR / "capacity-refusal-receipt.json"
ADMISSION_PATH = LOCK_DIR / f"{RUN_ID}.admission.consumed.json"
SYSTEMD_UNIT = f"{RUN_ID}.service"

MIN_MEMORY_BYTES = 30 * 1024 ** 3
CAPACITY_WORKER_TIMEOUT_SECONDS = 4 * 60 * 60
SOURCE_BUILD_PATHS = frozenset({"server/setup.py", "server/pyproject.toml"})
SOURCE_SCRIPT_PATHS = frozenset({
    "server/scripts/pair_aware_rollout_checkpoint_capacity.py",
    "server/scripts/pair_aware_rollout_checkpoint_successor_design.py",
    "server/scripts/pair_aware_rollout_duel.py",
})
FORBIDDEN_KEYS = frozenset({
    "action", "actions", "attacker_points", "history", "level_utility",
    "outcome", "outcomes", "points", "record", "records", "reward",
    "score", "scores", "utility", "winner", "won",
})


class CapacityRefused(RuntimeError):
    """The capacity packet, provenance, runtime, or score-free boundary drifted."""


def canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       allow_nan=False) + "\n").encode()


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: os.PathLike[str] | str) -> str:
    value = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            value.update(chunk)
    return value.hexdigest()


def is_sha256(value: object) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(char in "0123456789abcdef" for char in value))


def is_git_sha(value: object) -> bool:
    return (isinstance(value, str) and len(value) == 40
            and all(char in "0123456789abcdef" for char in value))


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
        raise CapacityRefused("capacity execution requires exact clean Git")


def require_regular_unlinked(path: Path, *, label: str,
                             root_owned: bool = False,
                             nonwritable: bool = False) -> bytes:
    partial = Path(str(path) + ".partial")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except (FileNotFoundError, OSError) as exc:
        raise CapacityRefused(f"{label} is missing") from exc
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
        raise CapacityRefused(f"{label} changed during read") from exc
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
        raise CapacityRefused(
            f"{label} is linked, nonregular, partial, writable, unowned, "
            "or unstable")
    raw = b"".join(chunks)
    if len(raw) != before.st_size:
        raise CapacityRefused(f"{label} size changed during read")
    return raw


def write_bytes_exclusive(path: Path, raw: bytes) -> None:
    partial = Path(str(path) + ".partial")
    if os.path.lexists(path) or os.path.lexists(partial):
        raise CapacityRefused(f"refusing existing output {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with partial.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    os.link(partial, path)
    partial.unlink()
    path.chmod(0o444)
    if path.read_bytes() != raw:
        raise CapacityRefused("published bytes differ from source")


def write_exclusive(path: Path, value: object) -> None:
    write_bytes_exclusive(path, canonical(value))


def _canonical_marker(prefix: str, claim: dict) -> bytes:
    return prefix.encode() + canonical(claim)


def canonical_review_record(*, commit: str, prefix: str, expected: dict,
                            label: str) -> tuple[dict, bytes]:
    if not (isinstance(commit, str) and len(commit) == 40
            and all(char in "0123456789abcdef" for char in commit)):
        raise CapacityRefused(f"{label} commit is not a full Git SHA")
    try:
        if subprocess.run(
                ["git", "merge-base", "--is-ancestor", commit,
                 CANONICAL_REVIEW_REF], cwd=REPO,
                capture_output=True).returncode != 0:
            raise CapacityRefused(f"{label} is not on canonical main")
        parents = git("show", "-s", "--format=%P", commit).split()
        if len(parents) != 1:
            raise CapacityRefused(f"{label} must have one parent")
        parent = parents[0]
        identity = tuple(git("show", "-s", f"--format={field}", commit)
                         for field in ("%an", "%ae", "%cn", "%ce"))
        if identity != (REVIEWER_NAME, REVIEWER_EMAIL,
                        REVIEWER_NAME, REVIEWER_EMAIL):
            raise CapacityRefused(f"{label} reviewer identity drift")
        if REVIEWER_SESSION_TRAILER not in git(
                "show", "-s", "--format=%B", commit):
            raise CapacityRefused(f"{label} session provenance is missing")
        changed = git("diff-tree", "--no-commit-id", "--name-only", "-r",
                      commit).splitlines()
        if changed != [REVIEW_LEDGER]:
            raise CapacityRefused(f"{label} changed files beyond the ledger")
        current = git_bytes("show", f"{commit}:{REVIEW_LEDGER}")
        previous = git_bytes("show", f"{parent}:{REVIEW_LEDGER}")
        canonical_tip = git_bytes(
            "show", f"{CANONICAL_REVIEW_REF}:{REVIEW_LEDGER}")
    except subprocess.CalledProcessError as exc:
        raise CapacityRefused(f"cannot authenticate {label}") from exc
    marker = _canonical_marker(prefix, expected)
    current_matches = [line for line in current.splitlines(keepends=True)
                       if line.startswith(prefix.encode())]
    previous_matches = [line for line in previous.splitlines(keepends=True)
                        if line.startswith(prefix.encode())]
    tip_matches = [line for line in canonical_tip.splitlines(keepends=True)
                   if line.startswith(prefix.encode())]
    if (not current.startswith(previous) or not canonical_tip.startswith(current)
            or current_matches != [marker] or previous_matches
            or tip_matches != [marker]):
        raise CapacityRefused(
            f"{label} marker/append-only ledger provenance drift")
    return ({"commit": commit, "parent_commit": parent,
             "ledger_sha256": sha256_bytes(current),
             "marker_sha256": sha256_bytes(marker), "claim": expected},
            marker)


def source_sha256s() -> dict[str, str]:
    names = git("ls-tree", "-r", "--name-only", "HEAD").splitlines()
    selected = [name for name in names
                if name.startswith("server/shengji/")
                or name in SOURCE_BUILD_PATHS
                or name in SOURCE_SCRIPT_PATHS]
    return {name: sha256_file(REPO / name) for name in sorted(selected)}


def _loaded_origin(module: object, expected: Path, *, label: str) -> str:
    origin = getattr(module, "__file__", None)
    if not isinstance(origin, str) or Path(origin).resolve() != expected.resolve():
        raise CapacityRefused(f"{label} import origin drift")
    return str(expected.resolve())


def _shadow_paths(native: Path) -> list[str]:
    tracked = set(git("ls-tree", "-r", "--name-only", "HEAD").splitlines())
    native = native.resolve()
    shadows = []
    for path in SERVER.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        relative = path.relative_to(REPO).as_posix()
        if relative in tracked or path.resolve() == native:
            continue
        if path.suffix in {".py", ".pyc", ".so", ".pyd"}:
            shadows.append(relative)
    return sorted(shadows)


def require_fresh_process() -> None:
    if (DESIGN_WAS_PRELOADED or CORE_WAS_PRELOADED
            or PRELOADED_SHENGJI_MODULES):
        raise CapacityRefused(
            "capacity command requires fresh, unpreloaded dependencies")


def _load_core(expected_git: str):
    global CORE
    if CORE is not None:
        return CORE
    if not sys.dont_write_bytecode:
        raise CapacityRefused("capacity runtime must disable bytecode writes")
    require_clean_exact_git(expected_git)
    raw = CORE_PATH.read_bytes()
    if sha256_bytes(raw) != DUEL_SOURCE_SHA256:
        raise CapacityRefused("reviewed Pair duel source drift")
    candidates = sorted((SERVER / "shengji/engine").glob("_fast.*.so"))
    if len(candidates) != 1:
        raise CapacityRefused("exactly one compiled native extension is required")
    shadows = _shadow_paths(candidates[0])
    if shadows:
        raise CapacityRefused(
            "runtime contains untracked loadable shadows: " + ",".join(shadows))
    module = types.ModuleType(CORE_MODULE)
    module.__file__ = str(CORE_PATH)
    module.__package__ = ""
    sys.modules[CORE_MODULE] = module
    try:
        exec(compile(raw, str(CORE_PATH), "exec"), module.__dict__)
    except BaseException:
        sys.modules.pop(CORE_MODULE, None)
        raise
    _loaded_origin(module, CORE_PATH, label="Pair duel")
    CORE = module
    return CORE


def _memory_bytes() -> int:
    try:
        return os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
    except (OSError, ValueError):
        return 0


def runtime_snapshot(expected_git: str) -> dict:
    core = _load_core(expected_git)
    from shengji.engine import _fast, fast

    native = Path(_fast.__file__).resolve()
    candidates = sorted((SERVER / "shengji/engine").glob("_fast.*.so"))
    if len(candidates) != 1 or native != candidates[0].resolve():
        raise CapacityRefused("imported native extension identity drift")
    origins = {
        "controller": str(Path(__file__).resolve()),
        "design": _loaded_origin(
            DESIGN, SERVER / "scripts/pair_aware_rollout_checkpoint_successor_design.py",
            label="successor design"),
        "duel": _loaded_origin(
            core, SERVER / "scripts/pair_aware_rollout_duel.py",
            label="Pair duel"),
        "fast": _loaded_origin(
            fast, SERVER / "shengji/engine/fast.py", label="fast router"),
        "native": _loaded_origin(_fast, native, label="native extension"),
    }
    shadows = _shadow_paths(native)
    if shadows:
        raise CapacityRefused(
            "runtime contains untracked loadable shadows: " + ",".join(shadows))
    python = Path(sys.executable)
    resolved_python = python.resolve()
    boot_id = Path("/proc/sys/kernel/random/boot_id")
    value = {
        "git": expected_git,
        "hostname": platform.node(),
        "machine": platform.machine(),
        "platform": platform.platform(),
        "cpu_count": os.cpu_count(),
        "memory_bytes": _memory_bytes(),
        "python": {
            "executable": str(python), "resolved": str(resolved_python),
            "version": platform.python_version(),
            "sha256": sha256_file(resolved_python),
            "soabi": sysconfig.get_config_var("SOABI") or "",
        },
        "native": {"path": str(native), "sha256": sha256_file(native)},
        "fast_enabled": fast.HAVE_FAST is True,
        "fast_environment": os.environ.get("SHENGJI_FAST") == "1",
        "fast_routing_active": bool(getattr(fast, "_saved", {})),
        "strict_voids": os.environ.get("SHENGJI_REQUIRE_VOIDS") == "1",
        "dont_write_bytecode": sys.dont_write_bytecode,
        "python_hash_seed": os.environ.get("PYTHONHASHSEED"),
        "process_nice": os.getpriority(os.PRIO_PROCESS, 0),
        "boot_id": boot_id.read_text().strip() if boot_id.is_file() else "",
        "module_origins": origins,
        "loadable_shadows": [],
        "source_sha256s": source_sha256s(),
    }
    return value


def runtime_problems(value: object, *, expected_git: str) -> list[str]:
    if not isinstance(value, dict):
        return ["runtime is not an object"]
    problems = []
    if set(value) != {"git", "hostname", "machine", "platform", "cpu_count",
                      "memory_bytes", "python", "native", "fast_enabled",
                      "fast_environment", "fast_routing_active",
                      "strict_voids", "dont_write_bytecode",
                      "python_hash_seed", "process_nice", "boot_id", "module_origins",
                      "loadable_shadows", "source_sha256s"}:
        problems.append("runtime field population drift")
    if (value.get("git") != expected_git
            or value.get("machine") not in {"x86_64", "amd64"}
            or not isinstance(value.get("cpu_count"), int)
            or isinstance(value.get("cpu_count"), bool)
            or value["cpu_count"] < DESIGN.MIN_WORKERS
            or not isinstance(value.get("memory_bytes"), int)
            or isinstance(value.get("memory_bytes"), bool)
            or value["memory_bytes"] < MIN_MEMORY_BYTES
            or value.get("fast_enabled") is not True
            or value.get("fast_environment") is not True
            or value.get("fast_routing_active") is not True
            or value.get("strict_voids") is not True
            or value.get("dont_write_bytecode") is not True
            or value.get("python_hash_seed") != "0"
            or value.get("process_nice") != 5
            or not isinstance(value.get("boot_id"), str)
            or not value["boot_id"]
            or value.get("loadable_shadows") != []):
        problems.append("runtime host/compiled/strict identity drift")
    for label in ("python", "native"):
        item = value.get(label)
        if (not isinstance(item, dict)
                or not is_sha256(item.get("sha256"))):
            problems.append(f"runtime {label} identity drift")
    origins = value.get("module_origins")
    if (not isinstance(origins, dict)
            or set(origins) != {"controller", "design", "duel", "fast", "native"}
            or any(not isinstance(path, str) or not Path(path).is_absolute()
                   for path in origins.values())):
        problems.append("runtime module-origin identity drift")
    sources = value.get("source_sha256s")
    if (not isinstance(sources, dict) or not sources
            or any(not isinstance(name, str) or not is_sha256(digest_)
                   for name, digest_ in sources.items())):
        problems.append("runtime source identity drift")
    return sorted(set(problems))


def require_frozen_runtime_inputs(runtime: dict) -> None:
    if os.geteuid() != 0:
        raise CapacityRefused("capacity freeze/run requires root-owned inputs")
    for relative, expected_sha in runtime["source_sha256s"].items():
        raw = require_regular_unlinked(
            REPO / relative, label=f"runtime source {relative}",
            root_owned=True, nonwritable=True)
        if sha256_bytes(raw) != expected_sha:
            raise CapacityRefused(f"runtime source {relative} drift")
    for label, path, expected_sha in (
            ("native", Path(runtime["native"]["path"]),
             runtime["native"]["sha256"]),
            ("Python", Path(runtime["python"]["resolved"]),
             runtime["python"]["sha256"])):
        raw = require_regular_unlinked(
            path, label=f"runtime {label}", root_owned=True,
            nonwritable=True)
        if sha256_bytes(raw) != expected_sha:
            raise CapacityRefused(f"runtime {label} drift")


def implementation_review_claim(*, expected_git: str) -> dict:
    return {
        "schema": IMPLEMENTATION_REVIEW_SCHEMA,
        "git": expected_git,
        "controller_sha256": sha256_file(Path(__file__).resolve()),
        "design_git": DESIGN_GIT,
        "design_source_sha256": DESIGN_SOURCE_SHA256,
        "capacity_packet_freeze_authorized": True,
        "capacity_execution_authorized": False,
        "screen_execution_authorized": False,
        "resume_execution_authorized": False,
        "aggregate_execution_authorized": False,
        "strength_claim": False,
        "production_deployment": False,
    }


def packet_review_claim(*, packet: dict, packet_sha256: str) -> dict:
    return {
        "schema": PACKET_REVIEW_SCHEMA,
        "git": packet["git"], "packet_sha256": packet_sha256,
        "packet_internal_sha256": packet["internal_sha256"],
        "runtime_profile_sha256": packet["runtime_profile_sha256"],
        "one_capacity_execution_authorized": True,
        "screen_execution_authorized": False,
        "resume_execution_authorized": False,
        "aggregate_execution_authorized": False,
        "strength_claim": False,
        "production_deployment": False,
    }


def packet_payload(*, expected_git: str, runtime: dict,
                   implementation_review: dict) -> dict:
    if runtime_problems(runtime, expected_git=expected_git):
        raise CapacityRefused("cannot freeze invalid runtime")
    value = {
        "schema": PACKET_SCHEMA, "run_id": RUN_ID, "git": expected_git,
        "design_git": DESIGN_GIT,
        "design_source_sha256": DESIGN_SOURCE_SHA256,
        "implementation_review": implementation_review,
        "runtime": runtime,
        "runtime_profile_sha256": digest(runtime),
        "capacity": {
            "seed0": DESIGN.CAPACITY_SEED0,
            "workers": DESIGN.MIN_WORKERS,
            "clusters_per_worker": DESIGN.CAPACITY_CLUSTERS_PER_WORKER,
            "stream_stride": DESIGN.STREAM_STRIDE,
            "all_workers_start_concurrently": True,
            "outcomes_published": False,
        },
        "one_capacity_execution_authorized": False,
        "screen_execution_authorized": False,
        "resume_execution_authorized": False,
        "aggregate_execution_authorized": False,
        "strength_claim": False,
        "production_deployment": False,
    }
    value["internal_sha256"] = digest(value)
    return value


def packet_problems(value: object, *, expected_git: str) -> list[str]:
    if not isinstance(value, dict):
        return ["packet is not an object"]
    unsigned = dict(value)
    observed = unsigned.pop("internal_sha256", None)
    problems = []
    expected_fields = {
        "schema", "run_id", "git", "design_git", "design_source_sha256",
        "implementation_review", "runtime", "runtime_profile_sha256",
        "capacity", "one_capacity_execution_authorized",
        "screen_execution_authorized", "resume_execution_authorized",
        "aggregate_execution_authorized", "strength_claim",
        "production_deployment", "internal_sha256",
    }
    if set(value) != expected_fields:
        problems.append("packet field population drift")
    if (observed != digest(unsigned) or value.get("schema") != PACKET_SCHEMA
            or value.get("run_id") != RUN_ID or value.get("git") != expected_git
            or value.get("design_git") != DESIGN_GIT
            or value.get("design_source_sha256") != DESIGN_SOURCE_SHA256
            or value.get("runtime_profile_sha256") != digest(value.get("runtime"))
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
        problems.append("packet identity/authority drift")
    problems.extend(runtime_problems(value.get("runtime"),
                                     expected_git=expected_git))
    review = value.get("implementation_review")
    if (not isinstance(review, dict)
            or set(review) != {"commit", "parent_commit", "ledger_sha256",
                               "marker_sha256", "claim"}
            or not is_git_sha(review.get("commit"))
            or not is_git_sha(review.get("parent_commit"))
            or review.get("claim") != implementation_review_claim(
                expected_git=expected_git)
            or not is_sha256(review.get("marker_sha256"))
            or not is_sha256(review.get("ledger_sha256"))):
        problems.append("packet implementation-review provenance drift")
    return sorted(set(problems))


def load_packet(path: Path, expected_sha256: str, *, expected_git: str) -> dict:
    raw = require_regular_unlinked(path, label="capacity packet",
                                   root_owned=True, nonwritable=True)
    if sha256_bytes(raw) != expected_sha256:
        raise CapacityRefused("capacity packet file SHA drift")
    value = strict_json(raw)
    problems = packet_problems(value, expected_git=expected_git)
    if problems:
        raise CapacityRefused("; ".join(problems))
    review, marker = canonical_review_record(
        commit=value["implementation_review"]["commit"],
        prefix=IMPLEMENTATION_REVIEW_PREFIX,
        expected=implementation_review_claim(expected_git=expected_git),
        label="checkpoint capacity implementation review")
    if review != value["implementation_review"]:
        raise CapacityRefused("packet implementation review record drift")
    snapshot = require_regular_unlinked(
        IMPLEMENTATION_REVIEW_PATH, label="implementation review snapshot",
        root_owned=True, nonwritable=True)
    if snapshot != marker or sha256_bytes(snapshot) != review["marker_sha256"]:
        raise CapacityRefused("implementation review snapshot drift")
    return value


def _validate_cluster(seed: int, *, run_id: str) -> tuple[int, int]:
    if CORE is None:
        raise CapacityRefused("Pair duel was not runtime-authenticated")
    by_label = {label: CORE.play_arm_cluster(label, seed, run_id=run_id)
                for label in CORE.LABEL_ORDER}
    for label, records in by_label.items():
        if len(records) != 2:
            raise CapacityRefused("capacity mirror population drift")
        for flip, record in enumerate(records):
            problems = CORE.record_problems(
                record, expected_label=label, expected_seed=seed,
                expected_flip=flip, expected_run_id=run_id)
            if problems:
                raise CapacityRefused("invalid capacity record: "
                                      + "; ".join(problems))
            if (record["arm"]["searches"] <= 0
                    or record["opp"]["searches"] <= 0):
                raise CapacityRefused("capacity record has no searched work")
    for null, champion in zip(by_label["matched_null"],
                              by_label["champion"], strict=True):
        problems = CORE.matched_null_champion_problems(null, champion)
        if problems:
            raise CapacityRefused("; ".join(problems))
    searches = sum(
        record[side]["searches"] for records in by_label.values()
        for record in records for side in ("arm", "opp"))
    triggers = sum(
        record[side]["pair_aware"]["triggers"]
        for record in by_label["treatment"] for side in ("arm", "opp"))
    # Only score-free work/dose counts remain; records and outcomes die here.
    return searches, triggers


def run_lane(index: int, runtime_profile_sha256: str) -> dict:
    if (not isinstance(index, int) or isinstance(index, bool)
            or not 0 <= index < DESIGN.MIN_WORKERS
            or not is_sha256(runtime_profile_sha256)):
        raise CapacityRefused("capacity lane identity drift")
    started = time.perf_counter()
    first = index * DESIGN.CAPACITY_CLUSTERS_PER_WORKER
    searches = 0
    treatment_triggers = 0
    for offset in range(DESIGN.CAPACITY_CLUSTERS_PER_WORKER):
        seed = DESIGN.CAPACITY_SEED0 + DESIGN.STREAM_STRIDE * (first + offset)
        cluster_searches, cluster_triggers = _validate_cluster(
            seed, run_id=RUN_ID)
        searches += cluster_searches
        treatment_triggers += cluster_triggers
    if searches <= 0 or treatment_triggers <= 0:
        raise CapacityRefused("capacity lane has degenerate work or dose")
    elapsed = time.perf_counter() - started
    if not math.isfinite(elapsed) or elapsed <= 0:
        raise CapacityRefused("capacity lane timing drift")
    return {"index": index,
            "clusters": DESIGN.CAPACITY_CLUSTERS_PER_WORKER,
            "elapsed_seconds": elapsed}


def _lane_process(index: int, expected_git: str,
                  runtime_profile_sha256: str, ready, start, results) -> None:
    try:
        current = runtime_snapshot(expected_git)
        if digest(current) != runtime_profile_sha256:
            raise CapacityRefused("worker runtime differs from packet")
    except BaseException:
        ready.put({"index": index, "ok": False})
        return
    ready.put({"index": index, "ok": True})
    start.wait()
    try:
        value = run_lane(index, runtime_profile_sha256)
    except BaseException:
        results.put({"index": index, "ok": False})
    else:
        results.put({"index": index, "ok": True, "lane": value})


def measure_capacity(packet: dict) -> dict:
    workers = DESIGN.MIN_WORKERS
    context = multiprocessing.get_context("spawn")
    ready = context.Queue()
    start = context.Event()
    results = context.Queue()
    processes = [context.Process(
        target=_lane_process,
        args=(index, packet["git"], packet["runtime_profile_sha256"],
              ready, start, results),
        name=f"pair-capacity-lane-{index:02d}") for index in range(workers)]
    for process in processes:
        process.start()
    try:
        ready_messages = [
            ready.get(timeout=CAPACITY_WORKER_TIMEOUT_SECONDS)
            for _ in range(workers)]
        if (sorted(message.get("index") for message in ready_messages)
                != list(range(workers))
                or any(message.get("ok") is not True
                       for message in ready_messages)):
            raise CapacityRefused("capacity start-barrier population drift")
        start.set()
        messages = [
            results.get(timeout=CAPACITY_WORKER_TIMEOUT_SECONDS)
            for _ in range(workers)]
        if (sorted(message.get("index") for message in messages)
                != list(range(workers))
                or any(message.get("ok") is not True for message in messages)):
            raise CapacityRefused("capacity lane failed")
        lanes = [message["lane"] for message in messages]
    finally:
        for process in processes:
            process.join(timeout=10)
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=10)
            if process.exitcode not in (0, None):
                raise CapacityRefused("capacity lane process exit drift")
    lanes.sort(key=lambda row: row["index"])
    value = {
        "schema": DESIGN.CAPACITY_SCHEMA, "run_id": RUN_ID,
        "seed0": DESIGN.CAPACITY_SEED0, "workers": workers,
        "clusters_per_worker": DESIGN.CAPACITY_CLUSTERS_PER_WORKER,
        "runtime_profile_sha256": packet["runtime_profile_sha256"],
        "score_free": True, "outcomes_published": False,
        "exact_work_complete": True,
        "concurrent_saturation_verified": True, "lanes": lanes,
    }
    problems = DESIGN.concurrent_capacity_problems(
        value, expected_workers=workers,
        runtime_profile_sha256=packet["runtime_profile_sha256"])
    if problems:
        raise CapacityRefused("; ".join(problems))
    return value


def _forbidden_keys(value: object) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if isinstance(key, str) and key.lower() in FORBIDDEN_KEYS:
                found.add(key)
            found.update(_forbidden_keys(child))
    elif isinstance(value, list):
        for child in value:
            found.update(_forbidden_keys(child))
    return found


def capacity_result_problems(value: object, *, packet: dict) -> list[str]:
    problems = DESIGN.concurrent_capacity_problems(
        value, expected_workers=DESIGN.MIN_WORKERS,
        runtime_profile_sha256=packet["runtime_profile_sha256"])
    forbidden = _forbidden_keys(value)
    if forbidden:
        problems.append("capacity result contains outcome-bearing keys")
    if not problems:
        try:
            projection = DESIGN.capacity_projection(
                value, expected_workers=DESIGN.MIN_WORKERS,
                runtime_profile_sha256=packet["runtime_profile_sha256"])
        except DESIGN.DesignRefused as exc:
            problems.append(str(exc))
        else:
            if projection["projected_wall_hours"] > DESIGN.MAX_PLANNED_WALL_HOURS:
                problems.append("capacity projection exceeds planned wall cap")
    return sorted(set(problems))


def admission_problems(value: object, *, packet: dict,
                       packet_sha256: str, review: dict,
                       invocation_id: str) -> list[str]:
    if not isinstance(value, dict):
        return ["capacity admission is not an object"]
    unsigned = dict(value)
    observed = unsigned.pop("internal_sha256", None)
    expected_fields = {
        "schema", "run_id", "git", "packet_sha256",
        "packet_review_commit", "packet_review_marker_sha256",
        "runtime_profile_sha256", "systemd_invocation_id", "nonce",
        "created_time_ns", "one_capacity_execution_authorized",
        "screen_execution_authorized", "resume_execution_authorized",
        "aggregate_execution_authorized", "strength_claim",
        "production_deployment", "retry_or_extension_authorized",
        "internal_sha256",
    }
    problems = []
    if set(value) != expected_fields:
        problems.append("capacity admission field population drift")
    if (observed != digest(unsigned)
            or value.get("schema") != ADMISSION_SCHEMA
            or value.get("run_id") != RUN_ID
            or value.get("git") != packet["git"]
            or value.get("packet_sha256") != packet_sha256
            or value.get("packet_review_commit") != review["commit"]
            or value.get("packet_review_marker_sha256")
            != review["marker_sha256"]
            or value.get("runtime_profile_sha256")
            != packet["runtime_profile_sha256"]
            or value.get("systemd_invocation_id") != invocation_id
            or not is_sha256(value.get("nonce"))
            or not isinstance(value.get("created_time_ns"), int)
            or isinstance(value.get("created_time_ns"), bool)
            or value["created_time_ns"] <= 0
            or value.get("one_capacity_execution_authorized") is not True
            or any(value.get(field) is not False for field in (
                "screen_execution_authorized", "resume_execution_authorized",
                "aggregate_execution_authorized", "strength_claim",
                "production_deployment", "retry_or_extension_authorized"))):
        problems.append("capacity admission identity/authority drift")
    return sorted(set(problems))


def receipt_payload(*, packet: dict, packet_sha256: str,
                    packet_review: dict, admission_sha256: str,
                    result_sha256: str, result: dict,
                    invocation_id: str) -> dict:
    value = {
        "schema": RECEIPT_SCHEMA, "run_id": RUN_ID,
        "git": packet["git"], "packet_sha256": packet_sha256,
        "packet_internal_sha256": packet["internal_sha256"],
        "packet_review_commit": packet_review["commit"],
        "packet_review_marker_sha256": packet_review["marker_sha256"],
        "admission_sha256": admission_sha256,
        "result_sha256": result_sha256,
        "result_internal_sha256": digest(result),
        "runtime_profile_sha256": packet["runtime_profile_sha256"],
        "systemd_invocation_id": invocation_id,
        "capacity_result_review_authorized": True,
        "screen_packet_freeze_authorized": False,
        "screen_execution_authorized": False,
        "resume_execution_authorized": False,
        "aggregate_execution_authorized": False,
        "strength_claim": False, "production_deployment": False,
        "retry_or_extension_authorized": False,
    }
    value["internal_sha256"] = digest(value)
    return value


def receipt_problems(value: object, *, packet: dict, packet_sha256: str,
                     packet_review: dict, admission_sha256: str,
                     result_sha256: str, result: dict,
                     invocation_id: str) -> list[str]:
    if not isinstance(value, dict):
        return ["capacity receipt is not an object"]
    expected = receipt_payload(
        packet=packet, packet_sha256=packet_sha256,
        packet_review=packet_review, admission_sha256=admission_sha256,
        result_sha256=result_sha256, result=result,
        invocation_id=invocation_id)
    return [] if value == expected else ["capacity receipt drift"]


def refusal_receipt_payload(
        *, packet: dict, packet_sha256: str, packet_review: dict,
        admission_sha256: str, measurement: dict, projection: dict,
        invocation_id: str) -> dict:
    value = {
        "schema": REFUSAL_RECEIPT_SCHEMA, "run_id": RUN_ID,
        "git": packet["git"], "packet_sha256": packet_sha256,
        "packet_internal_sha256": packet["internal_sha256"],
        "packet_review_commit": packet_review["commit"],
        "packet_review_marker_sha256": packet_review["marker_sha256"],
        "admission_sha256": admission_sha256,
        "runtime_profile_sha256": packet["runtime_profile_sha256"],
        "systemd_invocation_id": invocation_id,
        "status": "REFUSED_CAPACITY_PROJECTION",
        "reason": "capacity projection exceeds planned wall cap",
        "score_free": True, "outcomes_published": False,
        "measurement": measurement, "projection": projection,
        "max_planned_wall_hours": DESIGN.MAX_PLANNED_WALL_HOURS,
        "capacity_result_published": False,
        "execution_receipt_published": False,
        "capacity_terminal_review_authorized": True,
        "screen_packet_freeze_authorized": False,
        "screen_execution_authorized": False,
        "resume_execution_authorized": False,
        "aggregate_execution_authorized": False,
        "strength_claim": False, "production_deployment": False,
        "retry_or_extension_authorized": False,
    }
    value["internal_sha256"] = digest(value)
    return value


def refusal_receipt_problems(
        value: object, *, packet: dict, packet_sha256: str,
        packet_review: dict, admission_sha256: str,
        measurement: dict, projection: dict,
        invocation_id: str) -> list[str]:
    if not isinstance(value, dict):
        return ["capacity refusal receipt is not an object"]
    if _forbidden_keys(value):
        return ["capacity refusal receipt contains outcome-bearing keys"]
    expected = refusal_receipt_payload(
        packet=packet, packet_sha256=packet_sha256,
        packet_review=packet_review, admission_sha256=admission_sha256,
        measurement=measurement, projection=projection,
        invocation_id=invocation_id)
    return [] if value == expected else ["capacity refusal receipt drift"]


def reopen_exact(path: Path, *, label: str) -> tuple[object, str]:
    raw = require_regular_unlinked(path, label=label,
                                   root_owned=True, nonwritable=True)
    return strict_json(raw), sha256_bytes(raw)


def _systemd_properties(unit: str) -> dict[str, str]:
    fields = (
        "Id", "InvocationID", "LoadState", "ActiveState", "SubState",
        "Type", "Restart", "KillMode", "UID", "ControlGroup",
        "WorkingDirectory", "NRestarts",
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


def _systemd_invocation_exists(
        invocation: str, *, unit: str = SYSTEMD_UNIT,
        units_dir: Path = Path("/run/systemd/units")) -> bool:
    """Return whether systemd binds *unit* to this exact invocation.

    systemd exposes ``invocation:<unit-name> -> <32-hex InvocationID>``.
    Checking the inverse shape would make every real capacity attempt refuse
    before work starts, as the first PR89 performance attempt demonstrated.
    """
    if (len(invocation) != 32
            or any(char not in "0123456789abcdef" for char in invocation)):
        return False
    link = units_dir / f"invocation:{unit}"
    try:
        return (os.path.lexists(link) and link.is_symlink()
                and os.readlink(link) == invocation)
    except OSError:
        return False


def _current_cgroups() -> list[str]:
    return Path("/proc/self/cgroup").read_text().splitlines()


def require_systemd() -> str:
    invocation = os.environ.get("INVOCATION_ID", "")
    if (os.geteuid() != 0 or not invocation
            or not _systemd_invocation_exists(invocation)):
        raise CapacityRefused("capacity run requires a live root systemd unit")
    properties = _systemd_properties(SYSTEMD_UNIT)
    expected = {
        "Id": SYSTEMD_UNIT, "InvocationID": invocation,
        "LoadState": "loaded", "ActiveState": "active",
        "SubState": "running", "Type": "exec", "Restart": "no",
        "KillMode": "control-group",
        "WorkingDirectory": str(REPO), "NRestarts": "0",
    }
    if (any(properties.get(key) != value for key, value in expected.items())
            or properties.get("UID") not in {"0", "[not set]"}
            or not properties.get("ControlGroup", "").startswith("/system.slice/")):
        raise CapacityRefused("capacity systemd one-shot identity drift")
    try:
        memberships = _current_cgroups()
    except OSError as exc:
        raise CapacityRefused("cannot authenticate capacity cgroup") from exc
    control_group = properties["ControlGroup"]
    if not any(line.endswith(f":{control_group}") for line in memberships):
        raise CapacityRefused("capacity process is outside the reviewed cgroup")
    return invocation


def freeze_command(args: argparse.Namespace) -> None:
    require_fresh_process()
    require_clean_exact_git(args.expected_git)
    if Path(args.out).resolve() != PACKET_PATH.resolve():
        raise CapacityRefused("capacity packet output path is not canonical")
    claim = implementation_review_claim(expected_git=args.expected_git)
    review, marker = canonical_review_record(
        commit=args.implementation_review_commit,
        prefix=IMPLEMENTATION_REVIEW_PREFIX, expected=claim,
        label="checkpoint capacity implementation review")
    runtime = runtime_snapshot(args.expected_git)
    require_frozen_runtime_inputs(runtime)
    packet = packet_payload(expected_git=args.expected_git, runtime=runtime,
                            implementation_review=review)
    collisions = [path for path in (PACKET_PATH, IMPLEMENTATION_REVIEW_PATH)
                  if os.path.lexists(path)
                  or os.path.lexists(str(path) + ".partial")]
    if collisions:
        raise CapacityRefused("capacity packet freeze slot already consumed")
    write_bytes_exclusive(IMPLEMENTATION_REVIEW_PATH, marker)
    write_exclusive(PACKET_PATH, packet)
    packet_sha = sha256_file(PACKET_PATH)
    print(json.dumps({
        "status": "FROZEN_AWAITING_PACKET_REVIEW",
        "packet_sha256": packet_sha,
        "packet_internal_sha256": packet["internal_sha256"],
        "packet_review_claim": packet_review_claim(
            packet=packet, packet_sha256=packet_sha),
        "capacity_execution_authorized": False,
    }, sort_keys=True))


def verify_command(args: argparse.Namespace) -> None:
    require_fresh_process()
    packet = load_packet(Path(args.packet), args.expected_packet_sha256,
                         expected_git=args.expected_git)
    print(json.dumps({"verified": True,
                      "packet_sha256": args.expected_packet_sha256,
                      "packet_internal_sha256": packet["internal_sha256"]},
                     sort_keys=True))


def run_command(args: argparse.Namespace) -> None:
    require_fresh_process()
    require_clean_exact_git(args.expected_git)
    invocation = require_systemd()
    if (Path(args.packet).resolve() != PACKET_PATH.resolve()
            or Path(args.admission).resolve() != ADMISSION_PATH.resolve()
            or Path(args.result).resolve() != RESULT_PATH.resolve()
            or Path(args.receipt).resolve() != RECEIPT_PATH.resolve()
            or Path(args.refusal_receipt).resolve()
            != REFUSAL_RECEIPT_PATH.resolve()):
        raise CapacityRefused("capacity execution path is not canonical")
    packet = load_packet(Path(args.packet), args.expected_packet_sha256,
                         expected_git=args.expected_git)
    if runtime_snapshot(args.expected_git) != packet["runtime"]:
        raise CapacityRefused("live runtime differs from frozen packet")
    require_frozen_runtime_inputs(packet["runtime"])
    claim = packet_review_claim(
        packet=packet, packet_sha256=args.expected_packet_sha256)
    review, marker = canonical_review_record(
        commit=args.packet_review_commit, prefix=PACKET_REVIEW_PREFIX,
        expected=claim, label="checkpoint capacity packet review")
    collisions = [path for path in (
        PACKET_REVIEW_PATH, ADMISSION_PATH, RESULT_PATH, RECEIPT_PATH,
        REFUSAL_RECEIPT_PATH)
        if os.path.lexists(path) or os.path.lexists(str(path) + ".partial")]
    if collisions:
        raise CapacityRefused("capacity execution slot already consumed")
    write_bytes_exclusive(PACKET_REVIEW_PATH, marker)
    admission = {
        "schema": ADMISSION_SCHEMA, "run_id": RUN_ID,
        "git": args.expected_git,
        "packet_sha256": args.expected_packet_sha256,
        "packet_review_commit": review["commit"],
        "packet_review_marker_sha256": review["marker_sha256"],
        "runtime_profile_sha256": packet["runtime_profile_sha256"],
        "systemd_invocation_id": invocation,
        "nonce": secrets.token_hex(32), "created_time_ns": time.time_ns(),
        "one_capacity_execution_authorized": True,
        "screen_execution_authorized": False,
        "resume_execution_authorized": False,
        "aggregate_execution_authorized": False,
        "strength_claim": False, "production_deployment": False,
        "retry_or_extension_authorized": False,
    }
    admission["internal_sha256"] = digest(admission)
    problems = admission_problems(
        admission, packet=packet, packet_sha256=args.expected_packet_sha256,
        review=review, invocation_id=invocation)
    if problems:
        raise CapacityRefused("; ".join(problems))
    write_exclusive(ADMISSION_PATH, admission)
    result = measure_capacity(packet)
    measurement_problems = DESIGN.concurrent_capacity_problems(
        result, expected_workers=DESIGN.MIN_WORKERS,
        runtime_profile_sha256=packet["runtime_profile_sha256"])
    if _forbidden_keys(result):
        measurement_problems.append(
            "capacity measurement contains outcome-bearing keys")
    if measurement_problems:
        raise CapacityRefused("; ".join(sorted(set(measurement_problems))))
    projection = DESIGN.capacity_projection_details(
        result, expected_workers=DESIGN.MIN_WORKERS,
        runtime_profile_sha256=packet["runtime_profile_sha256"])
    if projection["projected_wall_hours"] > DESIGN.MAX_PLANNED_WALL_HOURS:
        refusal = refusal_receipt_payload(
            packet=packet, packet_sha256=args.expected_packet_sha256,
            packet_review=review,
            admission_sha256=sha256_file(ADMISSION_PATH),
            measurement=result, projection=projection,
            invocation_id=invocation)
        problems = refusal_receipt_problems(
            refusal, packet=packet,
            packet_sha256=args.expected_packet_sha256,
            packet_review=review,
            admission_sha256=sha256_file(ADMISSION_PATH),
            measurement=result, projection=projection,
            invocation_id=invocation)
        if problems:
            raise CapacityRefused("; ".join(problems))
        write_exclusive(REFUSAL_RECEIPT_PATH, refusal)
        print(json.dumps({
            "status": "REFUSED_CAPACITY_PROJECTION",
            "refusal_receipt_sha256": sha256_file(REFUSAL_RECEIPT_PATH),
            "screen_packet_freeze_authorized": False,
        }, sort_keys=True), flush=True)
        raise CapacityRefused(
            "capacity projection exceeds planned wall cap")
    problems = capacity_result_problems(result, packet=packet)
    if problems:
        raise CapacityRefused("; ".join(problems))
    write_exclusive(RESULT_PATH, result)
    reopened_result, result_sha = reopen_exact(
        RESULT_PATH, label="capacity result")
    if reopened_result != result:
        raise CapacityRefused("capacity result changed after publication")
    receipt = receipt_payload(
        packet=packet, packet_sha256=args.expected_packet_sha256,
        packet_review=review, admission_sha256=sha256_file(ADMISSION_PATH),
        result_sha256=result_sha, result=result, invocation_id=invocation)
    problems = receipt_problems(
        receipt, packet=packet, packet_sha256=args.expected_packet_sha256,
        packet_review=review, admission_sha256=sha256_file(ADMISSION_PATH),
        result_sha256=result_sha, result=result, invocation_id=invocation)
    if problems:
        raise CapacityRefused("; ".join(problems))
    write_exclusive(RECEIPT_PATH, receipt)
    print(json.dumps({
        "status": "CAPACITY_COMPLETE_AWAITING_RESULT_REVIEW",
        "result_sha256": result_sha,
        "receipt_sha256": sha256_file(RECEIPT_PATH),
        "screen_packet_freeze_authorized": False,
    }, sort_keys=True))


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
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
    run = commands.add_parser("run-capacity")
    run.add_argument("--expected-git", required=True)
    run.add_argument("--packet", type=Path, required=True)
    run.add_argument("--expected-packet-sha256", required=True)
    run.add_argument("--packet-review-commit", required=True)
    run.add_argument("--admission", type=Path, required=True)
    run.add_argument("--result", type=Path, required=True)
    run.add_argument("--receipt", type=Path, required=True)
    run.add_argument("--refusal-receipt", type=Path, required=True)
    run.set_defaults(func=run_command)
    return root


def main() -> int:
    try:
        args = parser().parse_args()
        args.func(args)
    except (CapacityRefused, OSError, ValueError,
            subprocess.CalledProcessError) as exc:
        raise SystemExit(f"REFUSED: {exc}") from exc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
