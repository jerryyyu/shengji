#!/usr/bin/env python3
"""One-shot controller for the reviewed scored-DEV bury/S6 packet.

The controller has two deliberately separate external review gates.  A
Claude-authenticated implementation PASS may freeze one host-specific packet;
an independently authenticated packet PASS may admit one serial 64-state run.
Every state is published as an immutable outcome-bearing record, while the
terminal final contains hashes, identities, work, sampler/dose and timing only.
There is no resume, aggregate, result-opening, strength or deployment command.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import platform
import secrets
import stat
import subprocess
import sys
import time
from collections.abc import Mapping
from pathlib import Path
from types import ModuleType
from typing import Any


SCRIPT = Path(__file__).resolve()
REPO = SCRIPT.parents[2]
SERVER = REPO / "server"
REVIEW_LEDGER = "HANDOFF_REVIEW.md"
CANONICAL_REVIEW_REF = "origin/main"
REVIEWER_NAME = "Claude"
REVIEWER_EMAIL = "noreply@anthropic.com"
REVIEWER_SESSION_TRAILER = "Claude-Session: https://claude.ai/code/session_"

DESIGN_GIT = "d31995d695b8bdfd013517982f6e5341678124c3"
DESIGN_REVIEW_COMMIT = "dbed4ae4ed82718819c325ae9e9d739466f1ce97"
DESIGN_SOURCE_SHA256 = (
    "0a63916f0bb83c46080ad0efdd41ac1e4ef9941f323bc3ad9d0b4e8404a34496"
)
DESIGN_CANONICAL_SHA256 = (
    "a79743a711137493ea77e9c0695022e5527618b925dc78bab500c72560292b92"
)
DESIGN_PATH = SERVER / "scripts/bury_lead_combo_scored_dev_design.py"
SCORER_PATH = SERVER / "scripts/bury_lead_combo_scored_dev.py"

RUN_ID = "bury-lead-combo-scored-dev-64-v1"
RUN_DIR = SERVER / "runs/logs" / RUN_ID
LOCK_DIR = SERVER / "runs/locks"
PACKET_PATH = RUN_DIR / "controller-packet.json"
IMPLEMENTATION_REVIEW_PATH = RUN_DIR / "implementation-review-snapshot.md"
PACKET_REVIEW_PATH = RUN_DIR / "packet-review-snapshot.md"
RECORDS_DIR = RUN_DIR / "sealed-state-records"
FINAL_PATH = RUN_DIR / "supervisor-final.json"
ADMISSION_PATH = LOCK_DIR / f"{RUN_ID}.admission.consumed.json"
SYSTEMD_UNIT = f"{RUN_ID}.service"

PACKET_SCHEMA = "bury-lead-combo-scored-dev-controller-packet-v1"
ADMISSION_SCHEMA = "bury-lead-combo-scored-dev-admission-v1"
FINAL_SCHEMA = "bury-lead-combo-scored-dev-supervisor-final-v1"
STATE_RECEIPT_SCHEMA = "bury-lead-combo-scored-dev-state-receipt-v1"
IMPLEMENTATION_REVIEW_SCHEMA = (
    "bury-lead-combo-scored-dev-controller-review-v1"
)
PACKET_REVIEW_SCHEMA = "bury-lead-combo-scored-dev-packet-review-v1"
IMPLEMENTATION_REVIEW_PREFIX = (
    "BURY_LEAD_COMBO_SCORED_DEV_CONTROLLER_REVIEWER_ATTESTATION_V1 "
)
PACKET_REVIEW_PREFIX = (
    "BURY_LEAD_COMBO_SCORED_DEV_PACKET_REVIEWER_ATTESTATION_V1 "
)

STATE_COUNT = 64
TOTAL_CANDIDATE_ROLLOUTS = 816_480
MAXIMUM_WALL_SECONDS = 3_600
MIN_CPUS = 16
MIN_MEMORY_BYTES = 30 * 1024 ** 3
REQUIRED_ENVIRONMENT = {
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONHASHSEED": "0",
    "SHENGJI_FAST": "1",
    "SHENGJI_REQUIRE_VOIDS": "1",
}
REQUIRED_SCRIPT_PATHS = frozenset({
    "server/scripts/bury_lead_combo_scored_dev_controller.py",
    "server/scripts/bury_lead_combo_scored_dev.py",
    "server/scripts/bury_lead_combo_scored_dev_design.py",
    "server/scripts/bury_lead_combo_exploration.py",
    "server/scripts/bury_lead_combo_population.py",
})
SOURCE_BUILD_PATHS = frozenset({
    "server/setup.py", "server/pyproject.toml", "uv.lock",
})
AUTHORITY_FIELDS = {
    "packet_freeze_authorized": False,
    "execution_authorized": False,
    "scored_record_access_authorized": False,
    "aggregation_authorized": False,
    "report_access_authorized": False,
    "retry_authorized": False,
    "extension_authorized": False,
    "strength_claim": False,
    "training_authorized": False,
    "production_promotion": False,
    "production_deployment": False,
}


class ControllerRefused(RuntimeError):
    """The requested controller action violates the reviewed contract."""


def canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False, allow_nan=False) + "\n").encode()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def digest(value: object) -> str:
    return sha256_bytes(canonical(value))


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


def _integer(value: object, *, minimum: int | None = None) -> bool:
    return (isinstance(value, int) and not isinstance(value, bool)
            and (minimum is None or value >= minimum))


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
        raise ControllerRefused("controller requires exact clean Git")


def stable_bytes(path: Path, *, label: str, root_owned: bool = False,
                 nonwritable: bool = False) -> bytes:
    partial = Path(str(path) + ".partial")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ControllerRefused(f"{label} is missing") from exc
    try:
        before = os.fstat(descriptor)
        path_before = path.lstat()
        chunks = []
        while block := os.read(descriptor, 1 << 20):
            chunks.append(block)
        after = os.fstat(descriptor)
        path_after = path.lstat()
    except OSError as exc:
        raise ControllerRefused(f"{label} changed during read") from exc
    finally:
        os.close(descriptor)
    identity = lambda info: (
        info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_uid,
        info.st_size, info.st_mtime_ns, info.st_ctime_ns,
    )
    if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
            or identity(before) != identity(after)
            or identity(before) != identity(path_before)
            or identity(before) != identity(path_after)
            or os.path.lexists(partial)
            or (root_owned and before.st_uid != 0)
            or (nonwritable and before.st_mode & 0o222)):
        raise ControllerRefused(
            f"{label} is linked, nonregular, partial, writable, unowned, "
            "or unstable")
    raw = b"".join(chunks)
    if len(raw) != before.st_size:
        raise ControllerRefused(f"{label} size drift")
    return raw


def write_bytes_exclusive(path: Path, raw: bytes) -> None:
    partial = Path(str(path) + ".partial")
    if os.path.lexists(path) or os.path.lexists(partial):
        raise ControllerRefused(f"refusing existing output {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with partial.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    os.link(partial, path)
    partial.unlink()
    path.chmod(0o444)
    if path.read_bytes() != raw:
        raise ControllerRefused("published bytes differ from source")


def write_exclusive(path: Path, value: object) -> None:
    write_bytes_exclusive(path, canonical(value))


def _canonical_marker(prefix: str, claim: dict) -> bytes:
    return prefix.encode() + canonical(claim)


def canonical_review_record(*, commit: str, prefix: str, expected: dict,
                            label: str) -> tuple[dict, bytes]:
    if not is_git_sha(commit):
        raise ControllerRefused(f"{label} commit is not a full Git SHA")
    try:
        if subprocess.run(
                ["git", "merge-base", "--is-ancestor", commit,
                 CANONICAL_REVIEW_REF], cwd=REPO,
                capture_output=True).returncode != 0:
            raise ControllerRefused(f"{label} is not on canonical main")
        parents = git("show", "-s", "--format=%P", commit).split()
        if len(parents) != 1:
            raise ControllerRefused(f"{label} must have one parent")
        parent = parents[0]
        identity = tuple(git("show", "-s", f"--format={field}", commit)
                         for field in ("%an", "%ae", "%cn", "%ce"))
        if identity != (REVIEWER_NAME, REVIEWER_EMAIL,
                        REVIEWER_NAME, REVIEWER_EMAIL):
            raise ControllerRefused(f"{label} reviewer identity drift")
        if REVIEWER_SESSION_TRAILER not in git(
                "show", "-s", "--format=%B", commit):
            raise ControllerRefused(f"{label} session provenance missing")
        changed = git("diff-tree", "--no-commit-id", "--name-only", "-r",
                      commit).splitlines()
        if changed != [REVIEW_LEDGER]:
            raise ControllerRefused(f"{label} changed files beyond ledger")
        current = git_bytes("show", f"{commit}:{REVIEW_LEDGER}")
        previous = git_bytes("show", f"{parent}:{REVIEW_LEDGER}")
        tip = git_bytes("show", f"{CANONICAL_REVIEW_REF}:{REVIEW_LEDGER}")
    except subprocess.CalledProcessError as exc:
        raise ControllerRefused(f"cannot authenticate {label}") from exc
    marker = _canonical_marker(prefix, expected)
    current_matches = [line for line in current.splitlines(keepends=True)
                       if line.startswith(prefix.encode())]
    previous_matches = [line for line in previous.splitlines(keepends=True)
                        if line.startswith(prefix.encode())]
    tip_matches = [line for line in tip.splitlines(keepends=True)
                   if line.startswith(prefix.encode())]
    if (not current.startswith(previous) or not tip.startswith(current)
            or current_matches != [marker] or previous_matches
            or tip_matches != [marker]):
        raise ControllerRefused(
            f"{label} marker/append-only ledger provenance drift")
    return ({
        "commit": commit, "parent_commit": parent,
        "ledger_sha256": sha256_bytes(current),
        "marker_sha256": sha256_bytes(marker), "claim": expected,
    }, marker)


def require_design_review() -> None:
    try:
        parents = git("show", "-s", "--format=%P", DESIGN_REVIEW_COMMIT).split()
        identity = tuple(git(
            "show", "-s", f"--format={field}", DESIGN_REVIEW_COMMIT)
            for field in ("%an", "%ae", "%cn", "%ce"))
        changed = git("diff-tree", "--no-commit-id", "--name-only", "-r",
                      DESIGN_REVIEW_COMMIT).splitlines()
        body = git("show", "-s", "--format=%B", DESIGN_REVIEW_COMMIT)
        current = git_bytes("show", f"{DESIGN_REVIEW_COMMIT}:{REVIEW_LEDGER}")
        previous = git_bytes("show", f"{parents[0]}:{REVIEW_LEDGER}")
        tip = git_bytes("show", f"{CANONICAL_REVIEW_REF}:{REVIEW_LEDGER}")
    except (subprocess.CalledProcessError, IndexError) as exc:
        raise ControllerRefused("cannot authenticate design review") from exc
    if (len(parents) != 1
            or identity != (REVIEWER_NAME, REVIEWER_EMAIL,
                            REVIEWER_NAME, REVIEWER_EMAIL)
            or changed != [REVIEW_LEDGER]
            or REVIEWER_SESSION_TRAILER not in body
            or not current.startswith(previous) or not tip.startswith(current)
            or b"scored bury/S6 DEV packet design (PR #91" not in current
            or DESIGN_GIT.encode() not in current
            or DESIGN_CANONICAL_SHA256[:16].encode() not in current):
        raise ControllerRefused("design review provenance drift")


def source_sha256s() -> dict[str, str]:
    names = git("ls-tree", "-r", "--name-only", "HEAD").splitlines()
    selected = {
        name for name in names
        if name.startswith("server/shengji/") or name in SOURCE_BUILD_PATHS
        or name in REQUIRED_SCRIPT_PATHS
    }
    if not REQUIRED_SCRIPT_PATHS <= selected:
        raise ControllerRefused("required scored-DEV source is untracked")
    return {name: sha256_file(REPO / name) for name in sorted(selected)}


def _shadow_paths(native: Path) -> list[str]:
    tracked = set(git("ls-tree", "-r", "--name-only", "HEAD").splitlines())
    allowed = {str(native.resolve())}
    problems = []
    for root in (SERVER / "shengji", SERVER / "scripts"):
        for path in root.rglob("*"):
            if (path.is_file() and path.suffix in {".py", ".pyc", ".so"}
                    and str(path.resolve()) not in allowed
                    and str(path.relative_to(REPO)) not in tracked):
                problems.append(str(path.relative_to(REPO)))
    for child in SERVER.iterdir():
        if (child.is_file() and child.suffix in {".py", ".pyc", ".so"}
                and str(child.relative_to(REPO)) not in tracked):
            problems.append(str(child.relative_to(REPO)))
        if (child.is_dir() and child.name not in {
                "shengji", "scripts", "tests", "runs", "rl_data", ".venv",
                "build", "shengji.egg-info", "__pycache__"}
                and (child / "__init__.py").exists()):
            problems.append(str(child.relative_to(REPO)))
    return sorted(set(problems))


def _memory_bytes() -> int:
    if hasattr(os, "sysconf"):
        try:
            return int(os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES"))
        except (ValueError, OSError):
            pass
    raise ControllerRefused("cannot determine physical memory")


def _python_identity() -> dict:
    resolved = Path(sys.executable).resolve()
    return {
        "executable": sys.executable,
        "resolved": str(resolved),
        "sha256": sha256_file(resolved),
        "version": platform.python_version(),
        "implementation": platform.python_implementation(),
        "machine": platform.machine(),
        "cache_tag": sys.implementation.cache_tag,
    }


def _native_path() -> Path:
    matches = list((SERVER / "shengji/engine").glob("_fast*.so"))
    if len(matches) != 1:
        raise ControllerRefused("exactly one in-tree native extension required")
    return matches[0].resolve()


def _runtime_probe(native: Path) -> dict:
    program = (
        "import json,sys;"
        f"sys.path.insert(0,{str(SERVER)!r});"
        "import shengji.engine.fast as f;"
        "import shengji.engine._fast as n;"
        "from shengji.ai.registry import make_bot;"
        "b=make_bot('mc-s0-report-lcb',seed=1);"
        "print(json.dumps({'have_fast':f.HAVE_FAST,'native':n.__file__,"
        "'bot':type(b).__name__,'exact_endgame':b.EXACT_ENDGAME,"
        "'level_objective':b.LEVEL_OBJECTIVE},sort_keys=True))"
    )
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
           **REQUIRED_ENVIRONMENT}
    completed = subprocess.run(
        [sys.executable, "-I", "-P", "-B", "-c", program],
        check=True, capture_output=True, text=True, env=env)
    value = strict_json(completed.stdout.encode())
    if value != {
            "have_fast": True, "native": str(native),
            "bot": "MCS0ReportLCB", "exact_endgame": False,
            "level_objective": False}:
        raise ControllerRefused("compiled scoring runtime contract drift")
    return value


def runtime_snapshot(expected_git: str, *, systemd_unit: Path,
                     host_profile: Path) -> dict:
    require_clean_exact_git(expected_git)
    if any(os.environ.get(key) != value
           for key, value in REQUIRED_ENVIRONMENT.items()):
        raise ControllerRefused("strict controller environment drift")
    if platform.machine() != "x86_64" or (os.cpu_count() or 0) < MIN_CPUS \
            or _memory_bytes() < MIN_MEMORY_BYTES:
        raise ControllerRefused("controller host capacity/runtime drift")
    sources = source_sha256s()
    native = _native_path()
    shadows = _shadow_paths(native)
    if shadows:
        raise ControllerRefused(f"loadable source shadows present: {shadows}")
    probe = _runtime_probe(native)
    return {
        "git": expected_git,
        "tree_dirty": False,
        "source_sha256s": sources,
        "source_manifest_sha256": digest(sources),
        "native": {"path": str(native), "sha256": sha256_file(native)},
        "python": _python_identity(),
        "host": {
            "hostname": platform.node(), "architecture": platform.machine(),
            "platform": platform.platform(), "cpu_online": os.cpu_count(),
            "memory_bytes": _memory_bytes(),
        },
        "environment": dict(REQUIRED_ENVIRONMENT),
        "probe": probe,
        "systemd_unit": {
            "name": SYSTEMD_UNIT, "path": str(systemd_unit.resolve()),
            "sha256": sha256_bytes(stable_bytes(
                systemd_unit, label="systemd unit", root_owned=True,
                nonwritable=True)),
        },
        "host_profile": {
            "path": str(host_profile.resolve()),
            "sha256": sha256_bytes(stable_bytes(
                host_profile, label="host profile", root_owned=True,
                nonwritable=True)),
        },
        "serial_state_execution": True,
        "maximum_wall_seconds": MAXIMUM_WALL_SECONDS,
    }


def runtime_problems(value: object, *, expected_git: str) -> list[str]:
    if not isinstance(value, Mapping):
        return ["runtime is not an object"]
    expected_fields = {
        "git", "tree_dirty", "source_sha256s", "source_manifest_sha256",
        "native", "python", "host", "environment", "probe",
        "systemd_unit", "host_profile", "serial_state_execution",
        "maximum_wall_seconds",
    }
    problems = []
    if set(value) != expected_fields:
        problems.append("runtime field population drift")
    sources = value.get("source_sha256s")
    if (value.get("git") != expected_git or value.get("tree_dirty") is not False
            or not isinstance(sources, Mapping) or not sources
            or any(not isinstance(path, str) or not is_sha256(sha)
                   for path, sha in sources.items())
            or value.get("source_manifest_sha256") != digest(sources)
            or value.get("environment") != REQUIRED_ENVIRONMENT
            or value.get("serial_state_execution") is not True
            or value.get("maximum_wall_seconds") != MAXIMUM_WALL_SECONDS):
        problems.append("runtime identity/work drift")
    native = value.get("native")
    python = value.get("python")
    host = value.get("host")
    if (not isinstance(native, Mapping) or set(native) != {"path", "sha256"}
            or not isinstance(native.get("path"), str)
            or not is_sha256(native.get("sha256"))):
        problems.append("runtime native identity drift")
    if (not isinstance(python, Mapping)
            or set(python) != {
                "executable", "resolved", "sha256", "version",
                "implementation", "machine", "cache_tag"}
            or python.get("implementation") != "CPython"
            or python.get("machine") != "x86_64"
            or not is_sha256(python.get("sha256"))):
        problems.append("runtime Python identity drift")
    if (not isinstance(host, Mapping)
            or not _integer(host.get("cpu_online"), minimum=MIN_CPUS)
            or not _integer(host.get("memory_bytes"), minimum=MIN_MEMORY_BYTES)
            or host.get("architecture") != "x86_64"):
        problems.append("runtime host identity drift")
    if value.get("probe") != {
            "have_fast": True,
            "native": native.get("path") if isinstance(native, Mapping) else None,
            "bot": "MCS0ReportLCB", "exact_endgame": False,
            "level_objective": False}:
        problems.append("runtime compiled scorer probe drift")
    for label in ("systemd_unit", "host_profile"):
        item = value.get(label)
        fields = {"path", "sha256"} | ({"name"} if label == "systemd_unit" else set())
        if (not isinstance(item, Mapping) or set(item) != fields
                or not isinstance(item.get("path"), str)
                or not is_sha256(item.get("sha256"))
                or (label == "systemd_unit"
                    and item.get("name") != SYSTEMD_UNIT)):
            problems.append(f"runtime {label} drift")
    return sorted(set(problems))


def require_frozen_runtime_inputs(runtime: Mapping[str, object]) -> None:
    if os.geteuid() != 0:
        raise ControllerRefused("freeze/run requires root-owned inputs")
    for relative, expected in runtime["source_sha256s"].items():
        raw = stable_bytes(REPO / relative, label=f"runtime source {relative}",
                           root_owned=True, nonwritable=True)
        if sha256_bytes(raw) != expected:
            raise ControllerRefused(f"runtime source {relative} drift")
    targets = (
        ("native", Path(runtime["native"]["path"]), runtime["native"]["sha256"]),
        ("Python", Path(runtime["python"]["resolved"]), runtime["python"]["sha256"]),
        ("systemd unit", Path(runtime["systemd_unit"]["path"]),
         runtime["systemd_unit"]["sha256"]),
        ("host profile", Path(runtime["host_profile"]["path"]),
         runtime["host_profile"]["sha256"]),
    )
    for label, path, expected in targets:
        raw = stable_bytes(path, label=label, root_owned=True,
                           nonwritable=True)
        if sha256_bytes(raw) != expected:
            raise ControllerRefused(f"runtime {label} drift")


def implementation_review_claim(*, expected_git: str) -> dict:
    sources = source_sha256s()
    return {
        "schema": IMPLEMENTATION_REVIEW_SCHEMA,
        "git": expected_git,
        "controller_sha256": sha256_file(SCRIPT),
        "scorer_sha256": sha256_file(SCORER_PATH),
        "source_manifest_sha256": digest(sources),
        "design_git": DESIGN_GIT,
        "design_source_sha256": DESIGN_SOURCE_SHA256,
        "design_canonical_sha256": DESIGN_CANONICAL_SHA256,
        "design_review_commit": DESIGN_REVIEW_COMMIT,
        "packet_freeze_authorized": True,
        "execution_authorized": False,
        "scored_record_access_authorized": False,
        "aggregation_authorized": False,
        "report_access_authorized": False,
        "retry_authorized": False,
        "extension_authorized": False,
        "strength_claim": False,
        "training_authorized": False,
        "production_promotion": False,
        "production_deployment": False,
    }


def packet_review_claim(*, packet: dict, packet_sha256: str) -> dict:
    return {
        "schema": PACKET_REVIEW_SCHEMA,
        "git": packet["git"],
        "packet_sha256": packet_sha256,
        "packet_internal_sha256": packet["internal_sha256"],
        "runtime_profile_sha256": packet["runtime_profile_sha256"],
        "one_scored_dev_execution_authorized": True,
        "scored_records_remain_sealed": True,
        "scored_record_access_authorized": False,
        "aggregation_authorized": False,
        "report_access_authorized": False,
        "retry_authorized": False,
        "extension_authorized": False,
        "strength_claim": False,
        "training_authorized": False,
        "production_promotion": False,
        "production_deployment": False,
    }


def _review_shape(value: object, expected_claim: dict) -> bool:
    return (isinstance(value, Mapping)
            and set(value) == {
                "commit", "parent_commit", "ledger_sha256",
                "marker_sha256", "claim"}
            and is_git_sha(value.get("commit"))
            and is_git_sha(value.get("parent_commit"))
            and is_sha256(value.get("ledger_sha256"))
            and is_sha256(value.get("marker_sha256"))
            and value.get("claim") == expected_claim)


def packet_payload(*, expected_git: str, runtime: dict,
                   implementation_review: dict) -> dict:
    if runtime_problems(runtime, expected_git=expected_git):
        raise ControllerRefused("cannot freeze invalid runtime")
    value = {
        "schema": PACKET_SCHEMA,
        "run_id": RUN_ID,
        "git": expected_git,
        "design": {
            "git": DESIGN_GIT,
            "source_sha256": DESIGN_SOURCE_SHA256,
            "canonical_sha256": DESIGN_CANONICAL_SHA256,
            "review_commit": DESIGN_REVIEW_COMMIT,
        },
        "scorer_sha256": sha256_file(SCORER_PATH),
        "controller_sha256": sha256_file(SCRIPT),
        "implementation_review": implementation_review,
        "runtime": runtime,
        "runtime_profile_sha256": digest(runtime),
        "population": {
            "id": "s3a-bury-v2-opened-dev-136m-v1",
            "states": STATE_COUNT,
            "selection_rows_sha256": (
                "d7077957d183a1f8c420cde2f0fff11514e8b03dd777c7b3587b75a16d0cdb6f"),
        },
        "work": {
            "selection_worlds_per_state": 30,
            "report_worlds_per_state": 30,
            "modes": ["baseline", "all_boss", "boss_near"],
            "menu_slots": [
                "incumbent_live", "incumbent_widened", "expanded"],
            "total_candidate_rollouts": TOTAL_CANDIDATE_ROLLOUTS,
            "serial_state_execution": True,
            "maximum_wall_seconds": MAXIMUM_WALL_SECONDS,
        },
        "paths": {
            "packet": str(PACKET_PATH.resolve()),
            "implementation_review": str(IMPLEMENTATION_REVIEW_PATH.resolve()),
            "packet_review": str(PACKET_REVIEW_PATH.resolve()),
            "admission": str(ADMISSION_PATH.resolve()),
            "records": str(RECORDS_DIR.resolve()),
            "supervisor_final": str(FINAL_PATH.resolve()),
        },
        "authority": dict(AUTHORITY_FIELDS),
    }
    value["internal_sha256"] = digest(value)
    return value


def packet_problems(value: object, *, expected_git: str) -> list[str]:
    if not isinstance(value, Mapping):
        return ["packet is not an object"]
    expected_fields = {
        "schema", "run_id", "git", "design", "scorer_sha256",
        "controller_sha256", "implementation_review", "runtime",
        "runtime_profile_sha256", "population", "work", "paths",
        "authority", "internal_sha256",
    }
    problems = []
    material = dict(value)
    recorded = material.pop("internal_sha256", None)
    if set(value) != expected_fields:
        problems.append("packet field population drift")
    if (recorded != digest(material) or value.get("schema") != PACKET_SCHEMA
            or value.get("run_id") != RUN_ID or value.get("git") != expected_git
            or value.get("design") != {
                "git": DESIGN_GIT, "source_sha256": DESIGN_SOURCE_SHA256,
                "canonical_sha256": DESIGN_CANONICAL_SHA256,
                "review_commit": DESIGN_REVIEW_COMMIT}
            or value.get("scorer_sha256") != sha256_file(SCORER_PATH)
            or value.get("controller_sha256") != sha256_file(SCRIPT)
            or value.get("runtime_profile_sha256") != digest(
                value.get("runtime"))
            or value.get("population") != {
                "id": "s3a-bury-v2-opened-dev-136m-v1",
                "states": STATE_COUNT,
                "selection_rows_sha256": (
                    "d7077957d183a1f8c420cde2f0fff11514e8b03dd777c7b3587b75a16d0cdb6f")}
            or value.get("work") != {
                "selection_worlds_per_state": 30,
                "report_worlds_per_state": 30,
                "modes": ["baseline", "all_boss", "boss_near"],
                "menu_slots": [
                    "incumbent_live", "incumbent_widened", "expanded"],
                "total_candidate_rollouts": TOTAL_CANDIDATE_ROLLOUTS,
                "serial_state_execution": True,
                "maximum_wall_seconds": MAXIMUM_WALL_SECONDS}
            or value.get("paths") != {
                "packet": str(PACKET_PATH.resolve()),
                "implementation_review": str(IMPLEMENTATION_REVIEW_PATH.resolve()),
                "packet_review": str(PACKET_REVIEW_PATH.resolve()),
                "admission": str(ADMISSION_PATH.resolve()),
                "records": str(RECORDS_DIR.resolve()),
                "supervisor_final": str(FINAL_PATH.resolve())}
            or value.get("authority") != AUTHORITY_FIELDS):
        problems.append("packet identity/work/authority drift")
    problems.extend(runtime_problems(
        value.get("runtime"), expected_git=expected_git))
    expected_claim = implementation_review_claim(expected_git=expected_git)
    if not _review_shape(value.get("implementation_review"), expected_claim):
        problems.append("packet implementation-review provenance drift")
    return sorted(set(problems))


def load_packet(path: Path, expected_sha256: str, *, expected_git: str) -> dict:
    if not is_sha256(expected_sha256):
        raise ControllerRefused("expected packet SHA is invalid")
    raw = stable_bytes(path, label="controller packet", root_owned=True,
                       nonwritable=True)
    if sha256_bytes(raw) != expected_sha256:
        raise ControllerRefused("controller packet file SHA drift")
    value = strict_json(raw)
    problems = packet_problems(value, expected_git=expected_git)
    if problems:
        raise ControllerRefused("; ".join(problems))
    review, marker = canonical_review_record(
        commit=value["implementation_review"]["commit"],
        prefix=IMPLEMENTATION_REVIEW_PREFIX,
        expected=implementation_review_claim(expected_git=expected_git),
        label="scored-DEV controller implementation review")
    if review != value["implementation_review"]:
        raise ControllerRefused("implementation review record drift")
    snapshot = stable_bytes(
        IMPLEMENTATION_REVIEW_PATH, label="implementation review snapshot",
        root_owned=True, nonwritable=True)
    if snapshot != marker or sha256_bytes(snapshot) != review["marker_sha256"]:
        raise ControllerRefused("implementation review snapshot drift")
    return value


def require_fresh_process() -> None:
    forbidden = [name for name in sys.modules
                 if name == "shengji" or name.startswith("shengji.")
                 or name in {
                     "bury_lead_combo_scored_dev",
                     "bury_lead_combo_scored_dev_design",
                     "bury_lead_combo_population",
                     "bury_lead_combo_exploration"}]
    if forbidden:
        raise ControllerRefused(
            f"controller requires a fresh process, preloaded={forbidden[:3]}")


def _load_exact_module(name: str, path: Path, expected_sha: str) -> ModuleType:
    raw = stable_bytes(path, label=f"{name} source", root_owned=True,
                       nonwritable=True)
    if sha256_bytes(raw) != expected_sha or name in sys.modules:
        raise ControllerRefused(f"{name} source/preload drift")
    module = ModuleType(name)
    module.__file__ = str(path.resolve())
    module.__package__ = ""
    sys.modules[name] = module
    try:
        exec(compile(raw, str(path), "exec"), module.__dict__)
    except Exception:
        sys.modules.pop(name, None)
        raise
    if Path(module.__file__).resolve() != path.resolve():
        raise ControllerRefused(f"{name} import origin drift")
    return module


def _load_scorer(packet: Mapping[str, object]) -> tuple[ModuleType, ModuleType]:
    scripts = str((SERVER / "scripts").resolve())
    server = str(SERVER.resolve())
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    if server not in sys.path:
        sys.path.insert(0, server)
    design = _load_exact_module(
        "bury_lead_combo_scored_dev_design", DESIGN_PATH,
        DESIGN_SOURCE_SHA256)
    if sha256_bytes(canonical(design.build_design())) != DESIGN_CANONICAL_SHA256:
        raise ControllerRefused("reviewed design canonical bytes drift")
    scorer = _load_exact_module(
        "bury_lead_combo_scored_dev", SCORER_PATH,
        packet["scorer_sha256"])
    return design, scorer


def _systemd_properties(unit: str) -> dict[str, str]:
    fields = (
        "Id", "InvocationID", "LoadState", "ActiveState", "SubState",
        "Type", "Restart", "KillMode", "UID", "ControlGroup",
        "WorkingDirectory", "NRestarts", "RuntimeMaxUSec",
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


def require_systemd(runtime: Mapping[str, object]) -> str:
    invocation = os.environ.get("INVOCATION_ID", "")
    invocation_path = Path(f"/run/systemd/units/invocation:{invocation}")
    if (os.geteuid() != 0 or not invocation or not invocation_path.exists()):
        raise ControllerRefused("scored-DEV run requires live root systemd")
    properties = _systemd_properties(SYSTEMD_UNIT)
    expected = {
        "Id": SYSTEMD_UNIT, "InvocationID": invocation,
        "LoadState": "loaded", "ActiveState": "active",
        "SubState": "running", "Type": "exec", "Restart": "no",
        "KillMode": "control-group", "WorkingDirectory": str(REPO),
        "NRestarts": "0", "RuntimeMaxUSec": "1h",
    }
    if (any(properties.get(key) != value for key, value in expected.items())
            or properties.get("UID") not in {"0", "[not set]"}
            or not properties.get("ControlGroup", "").startswith(
                "/system.slice/")):
        raise ControllerRefused("scored-DEV systemd identity drift")
    memberships = Path("/proc/self/cgroup").read_text().splitlines()
    if not any(line.endswith(f":{properties['ControlGroup']}")
               for line in memberships):
        raise ControllerRefused("controller process is outside reviewed cgroup")
    if runtime["systemd_unit"]["name"] != SYSTEMD_UNIT:
        raise ControllerRefused("packet systemd unit identity drift")
    return invocation


def _sampler_receipt(value: Mapping[str, object]) -> dict:
    return {
        "worlds": value["worlds"],
        "attempts": value["attempts"],
        "attempt_cap": value["attempt_cap"],
        "pre_rng_sha256": value["pre_rng_sha256"],
        "post_rng_sha256": value["post_rng_sha256"],
        "sampler_before_sha256": value["sampler_before_sha256"],
        "sampler_after_sha256": value["sampler_after_sha256"],
        "sampler_delta": dict(value["sampler_delta"]),
        "world_commitments_sha256": digest(value["world_commitments"]),
    }


def state_receipt(record: dict, *, state_index: int, elapsed_ns: int,
                  raw: bytes, scorer: ModuleType) -> dict:
    seed = record.get("deal_seed")
    problems = scorer.record_problems(record, expected_seed=seed)
    if problems:
        raise ControllerRefused("; ".join(problems))
    selection = record["selection"]
    report = record["report"]
    modes = []
    for mode in ("baseline", "all_boss", "boss_near"):
        arm = report["modes"][mode]
        modes.append({
            "mode": mode,
            "world_commitments_sha256": digest(arm["world_commitments"]),
            "continuation_dose": arm["continuation_dose"],
        })
    value = {
        "schema": STATE_RECEIPT_SCHEMA,
        "state_index": state_index,
        "deal_seed": seed,
        "state_id": record["state_id"],
        "source_state_id": record["source_state_id"],
        "record_file": f"state-{state_index:02d}-of-{STATE_COUNT}.json",
        "record_sha256": sha256_bytes(raw),
        "record_internal_sha256": record["internal_sha256"],
        "record_bytes": len(raw),
        "source_input_sha256": record["source_input_sha256"],
        "source_replay_sha256": record["source_replay_sha256"],
        "ballot_sha256": record["ballot_sha256"],
        "candidate_count": record["candidate_count"],
        "selection": {
            "sampler": _sampler_receipt(selection["sampler"]),
            "selected_slots_sha256": digest(selection["selected_candidates"]),
            "candidate_rollouts": selection["candidate_rollouts"],
        },
        "report": {
            "sampler": _sampler_receipt(report["sampler"]),
            "candidate_rollouts_per_mode":
                report["candidate_rollouts_per_mode"],
            "modes": modes,
        },
        "work": dict(record["work"]),
        "elapsed_ns": elapsed_ns,
    }
    value["internal_sha256"] = digest(value)
    return value


def state_receipt_problems(value: object, *, expected_index: int,
                           expected_seed: int) -> list[str]:
    if not isinstance(value, Mapping):
        return ["state receipt is not an object"]
    expected_fields = {
        "schema", "state_index", "deal_seed", "state_id", "source_state_id",
        "record_file", "record_sha256", "record_internal_sha256",
        "record_bytes", "source_input_sha256", "source_replay_sha256",
        "ballot_sha256", "candidate_count", "selection", "report", "work",
        "elapsed_ns", "internal_sha256",
    }
    problems = []
    material = dict(value)
    recorded = material.pop("internal_sha256", None)
    if set(value) != expected_fields:
        problems.append("state receipt field population drift")
    if (recorded != digest(material)
            or value.get("schema") != STATE_RECEIPT_SCHEMA
            or value.get("state_index") != expected_index
            or value.get("deal_seed") != expected_seed
            or value.get("record_file") != (
                f"state-{expected_index:02d}-of-{STATE_COUNT}.json")
            or not _integer(value.get("record_bytes"), minimum=1)
            or not _integer(value.get("candidate_count"), minimum=1)
            or not _integer(value.get("elapsed_ns"), minimum=1)
            or any(not is_sha256(value.get(field)) for field in (
                "record_sha256", "record_internal_sha256",
                "source_input_sha256", "source_replay_sha256",
                "ballot_sha256"))
            or not isinstance(value.get("state_id"), str)
            or not isinstance(value.get("source_state_id"), str)):
        problems.append("state receipt identity/hash/timing drift")
    selection = value.get("selection")
    report = value.get("report")
    work = value.get("work")
    if (not isinstance(selection, Mapping)
            or set(selection) != {
                "sampler", "selected_slots_sha256", "candidate_rollouts"}
            or not is_sha256(selection.get("selected_slots_sha256"))
            or not _integer(selection.get("candidate_rollouts"), minimum=1)
            or _sampler_receipt_problems(selection.get("sampler"))):
        problems.append("state selection receipt drift")
    if (not isinstance(report, Mapping)
            or set(report) != {
                "sampler", "candidate_rollouts_per_mode", "modes"}
            or report.get("candidate_rollouts_per_mode") != 90
            or _sampler_receipt_problems(report.get("sampler"))
            or not isinstance(report.get("modes"), list)
            or [item.get("mode") for item in report["modes"]
                if isinstance(item, Mapping)] != [
                    "baseline", "all_boss", "boss_near"]):
        problems.append("state report receipt drift")
    else:
        for item in report["modes"]:
            if (not isinstance(item, Mapping)
                    or set(item) != {
                        "mode", "world_commitments_sha256",
                        "continuation_dose"}
                    or not is_sha256(item.get("world_commitments_sha256"))
                    or not isinstance(item.get("continuation_dose"), Mapping)):
                problems.append("state report mode receipt drift")
                break
    expected_work = {
        "selection_candidate_rollouts":
            value.get("candidate_count", 0) * 30,
        "report_candidate_rollouts_per_mode": 90,
        "total_candidate_rollouts":
            value.get("candidate_count", 0) * 30 + 270,
        "exact_complete": True,
    }
    if work != expected_work:
        problems.append("state exact work receipt drift")
    return sorted(set(problems))


def _sampler_receipt_problems(value: object) -> list[str]:
    if not isinstance(value, Mapping):
        return ["sampler receipt is not an object"]
    expected = {
        "worlds", "attempts", "attempt_cap", "pre_rng_sha256",
        "post_rng_sha256", "sampler_before_sha256", "sampler_after_sha256",
        "sampler_delta", "world_commitments_sha256",
    }
    if (set(value) != expected or value.get("worlds") != 30
            or not _integer(value.get("attempts"), minimum=30)
            or not _integer(value.get("attempt_cap"), minimum=30)
            or value["attempts"] > value["attempt_cap"]
            or any(not is_sha256(value.get(field)) for field in (
                "pre_rng_sha256", "post_rng_sha256", "sampler_before_sha256",
                "sampler_after_sha256", "world_commitments_sha256"))
            or not isinstance(value.get("sampler_delta"), Mapping)):
        return ["sampler receipt drift"]
    delta = value["sampler_delta"]
    if (set(delta) != {
            "sample_attempts", "accepted_worlds", "failed_worlds",
            "rejected_worlds", "impossible_worlds"}
            or any(not _integer(item, minimum=0) for item in delta.values())
            or delta["accepted_worlds"] != 30
            or delta["sample_attempts"] != value["attempts"]
            or delta["sample_attempts"] != (
                delta["accepted_worlds"] + delta["failed_worlds"])
            or delta["rejected_worlds"] > delta["failed_worlds"]
            or delta["impossible_worlds"] != 0):
        return ["sampler receipt counters drift"]
    return []


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
        "one_scored_dev_execution_authorized": True,
        "records_remain_sealed": True,
        "resume_authorized": False,
        "retry_or_extension_authorized": False,
        "aggregation_authorized": False,
        "report_access_authorized": False,
        "strength_claim": False,
        "training_authorized": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    value["internal_sha256"] = digest(value)
    return value


def final_payload(*, packet: dict, packet_sha256: str,
                  packet_review: dict, admission_sha256: str,
                  invocation_id: str, state_receipts: list[dict],
                  started_ns: int, finished_ns: int) -> dict:
    total_work = sum(
        item["work"]["total_candidate_rollouts"] for item in state_receipts)
    value = {
        "schema": FINAL_SCHEMA,
        "run_id": RUN_ID,
        "git": packet["git"],
        "packet_sha256": packet_sha256,
        "packet_internal_sha256": packet["internal_sha256"],
        "packet_review_commit": packet_review["commit"],
        "packet_review_marker_sha256": packet_review["marker_sha256"],
        "admission_sha256": admission_sha256,
        "runtime_profile_sha256": packet["runtime_profile_sha256"],
        "systemd_invocation_id": invocation_id,
        "records_directory": str(RECORDS_DIR.resolve()),
        "state_receipts": state_receipts,
        "states_complete": len(state_receipts),
        "total_candidate_rollouts": total_work,
        "started_time_ns": started_ns,
        "finished_time_ns": finished_ns,
        "elapsed_ns": finished_ns - started_ns,
        "status": "COMPLETE_AWAITING_SCORE_FREE_SUPERVISOR_REVIEW",
        "scored_records_opened_after_publication": False,
        "authority": dict(AUTHORITY_FIELDS),
    }
    value["internal_sha256"] = digest(value)
    return value


def final_problems(value: object, *, packet: dict,
                   packet_sha256: str) -> list[str]:
    if not isinstance(value, Mapping):
        return ["supervisor final is not an object"]
    expected_fields = {
        "schema", "run_id", "git", "packet_sha256",
        "packet_internal_sha256", "packet_review_commit",
        "packet_review_marker_sha256", "admission_sha256",
        "runtime_profile_sha256", "systemd_invocation_id",
        "records_directory", "state_receipts", "states_complete",
        "total_candidate_rollouts", "started_time_ns", "finished_time_ns",
        "elapsed_ns", "status", "scored_records_opened_after_publication",
        "authority", "internal_sha256",
    }
    problems = []
    material = dict(value)
    recorded = material.pop("internal_sha256", None)
    if set(value) != expected_fields:
        problems.append("supervisor final field population drift")
    if (recorded != digest(material) or value.get("schema") != FINAL_SCHEMA
            or value.get("run_id") != RUN_ID or value.get("git") != packet["git"]
            or value.get("packet_sha256") != packet_sha256
            or value.get("packet_internal_sha256") != packet["internal_sha256"]
            or value.get("runtime_profile_sha256")
            != packet["runtime_profile_sha256"]
            or value.get("records_directory") != str(RECORDS_DIR.resolve())
            or value.get("states_complete") != STATE_COUNT
            or value.get("total_candidate_rollouts")
            != TOTAL_CANDIDATE_ROLLOUTS
            or value.get("status")
            != "COMPLETE_AWAITING_SCORE_FREE_SUPERVISOR_REVIEW"
            or value.get("scored_records_opened_after_publication") is not False
            or value.get("authority") != AUTHORITY_FIELDS
            or not is_git_sha(value.get("packet_review_commit"))
            or any(not is_sha256(value.get(field)) for field in (
                "packet_review_marker_sha256", "admission_sha256"))
            or not isinstance(value.get("systemd_invocation_id"), str)
            or not value["systemd_invocation_id"]
            or not _integer(value.get("started_time_ns"), minimum=1)
            or not _integer(value.get("finished_time_ns"), minimum=1)
            or not _integer(value.get("elapsed_ns"), minimum=1)
            or value.get("finished_time_ns", 0) - value.get(
                "started_time_ns", 0) != value.get("elapsed_ns", -1)
            or value.get("elapsed_ns", 0) >= MAXIMUM_WALL_SECONDS * 10**9):
        problems.append("supervisor final identity/work/authority drift")
    receipts = value.get("state_receipts")
    seeds = _selection_seeds()
    if (not isinstance(receipts, list) or len(receipts) != STATE_COUNT):
        problems.append("supervisor final state receipt population drift")
    else:
        for index, (receipt, seed) in enumerate(zip(receipts, seeds, strict=True)):
            problems.extend(state_receipt_problems(
                receipt, expected_index=index, expected_seed=seed))
        if (len({item.get("record_sha256") for item in receipts
                 if isinstance(item, Mapping)}) != STATE_COUNT
                or sum(item["work"]["total_candidate_rollouts"]
                       for item in receipts) != TOTAL_CANDIDATE_ROLLOUTS):
            problems.append("supervisor final record/work closure drift")
    return sorted(set(problems))


def _selection_seeds() -> list[int]:
    raw = stable_bytes(DESIGN_PATH, label="reviewed design source")
    # The literal selection rows are reviewed and imported only after the full
    # runtime gate in production.  This lightweight extractor is never used to
    # score or open outcomes; it keeps final validation independent of records.
    if sha256_bytes(raw) != DESIGN_SOURCE_SHA256:
        raise ControllerRefused("reviewed design source drift")
    module_name = "_bury_scored_design_seed_view"
    module = ModuleType(module_name)
    module.__file__ = str(DESIGN_PATH)
    exec(compile(raw, str(DESIGN_PATH), "exec"), module.__dict__)
    return [row["deal_seed"] for row in module._selection_rows()]


def freeze_command(args: argparse.Namespace) -> None:
    require_fresh_process()
    require_clean_exact_git(args.expected_git)
    require_design_review()
    if Path(args.out).resolve() != PACKET_PATH.resolve():
        raise ControllerRefused("packet output path is not canonical")
    claim = implementation_review_claim(expected_git=args.expected_git)
    review, marker = canonical_review_record(
        commit=args.implementation_review_commit,
        prefix=IMPLEMENTATION_REVIEW_PREFIX, expected=claim,
        label="scored-DEV controller implementation review")
    runtime = runtime_snapshot(
        args.expected_git, systemd_unit=Path(args.systemd_unit),
        host_profile=Path(args.host_profile))
    require_frozen_runtime_inputs(runtime)
    raw_design = stable_bytes(
        DESIGN_PATH, label="reviewed design source", root_owned=True,
        nonwritable=True)
    if sha256_bytes(raw_design) != DESIGN_SOURCE_SHA256:
        raise ControllerRefused("reviewed design source drift")
    design = _load_exact_module(
        "bury_lead_combo_scored_dev_design", DESIGN_PATH,
        DESIGN_SOURCE_SHA256)
    if sha256_bytes(canonical(design.build_design())) != DESIGN_CANONICAL_SHA256:
        raise ControllerRefused("reviewed canonical design drift")
    packet = packet_payload(
        expected_git=args.expected_git, runtime=runtime,
        implementation_review=review)
    collisions = [path for path in (PACKET_PATH, IMPLEMENTATION_REVIEW_PATH)
                  if os.path.lexists(path)
                  or os.path.lexists(str(path) + ".partial")]
    if collisions:
        raise ControllerRefused("packet freeze slot already consumed")
    write_bytes_exclusive(IMPLEMENTATION_REVIEW_PATH, marker)
    write_exclusive(PACKET_PATH, packet)
    packet_sha = sha256_file(PACKET_PATH)
    print(json.dumps({
        "status": "FROZEN_AWAITING_PACKET_REVIEW",
        "packet_sha256": packet_sha,
        "packet_internal_sha256": packet["internal_sha256"],
        "packet_review_claim": packet_review_claim(
            packet=packet, packet_sha256=packet_sha),
        "execution_authorized": False,
    }, sort_keys=True))


def verify_packet_command(args: argparse.Namespace) -> None:
    require_fresh_process()
    packet = load_packet(
        Path(args.packet), args.expected_packet_sha256,
        expected_git=args.expected_git)
    print(json.dumps({
        "verified": True,
        "packet_sha256": args.expected_packet_sha256,
        "packet_internal_sha256": packet["internal_sha256"],
        "execution_authorized": False,
    }, sort_keys=True))


def verify_final_command(args: argparse.Namespace) -> None:
    require_fresh_process()
    packet = load_packet(
        Path(args.packet), args.expected_packet_sha256,
        expected_git=args.expected_git)
    raw = stable_bytes(Path(args.final), label="score-free supervisor final",
                       root_owned=True, nonwritable=True)
    value = strict_json(raw)
    problems = final_problems(
        value, packet=packet, packet_sha256=args.expected_packet_sha256)
    if problems:
        raise ControllerRefused("; ".join(problems))
    print(json.dumps({
        "verified": True,
        "supervisor_final_sha256": sha256_bytes(raw),
        "states_complete": value["states_complete"],
        "scored_records_opened": False,
        "aggregation_authorized": False,
    }, sort_keys=True))


def run_command(args: argparse.Namespace) -> None:
    require_fresh_process()
    require_clean_exact_git(args.expected_git)
    canonical_paths = {
        "packet": PACKET_PATH, "admission": ADMISSION_PATH,
        "records": RECORDS_DIR, "final": FINAL_PATH,
    }
    observed_paths = {
        "packet": Path(args.packet), "admission": Path(args.admission),
        "records": Path(args.records), "final": Path(args.final),
    }
    if any(observed_paths[key].resolve() != target.resolve()
           for key, target in canonical_paths.items()):
        raise ControllerRefused("execution path is not canonical")
    packet = load_packet(
        Path(args.packet), args.expected_packet_sha256,
        expected_git=args.expected_git)
    live_runtime = runtime_snapshot(
        args.expected_git,
        systemd_unit=Path(packet["runtime"]["systemd_unit"]["path"]),
        host_profile=Path(packet["runtime"]["host_profile"]["path"]))
    if live_runtime != packet["runtime"]:
        raise ControllerRefused("live runtime differs from frozen packet")
    require_frozen_runtime_inputs(packet["runtime"])
    invocation = require_systemd(packet["runtime"])
    claim = packet_review_claim(
        packet=packet, packet_sha256=args.expected_packet_sha256)
    review, marker = canonical_review_record(
        commit=args.packet_review_commit, prefix=PACKET_REVIEW_PREFIX,
        expected=claim, label="scored-DEV packet review")
    collisions = [path for path in (
        PACKET_REVIEW_PATH, ADMISSION_PATH, RECORDS_DIR, FINAL_PATH)
        if os.path.lexists(path) or os.path.lexists(str(path) + ".partial")]
    if collisions:
        raise ControllerRefused("one-shot execution slot already consumed")
    write_bytes_exclusive(PACKET_REVIEW_PATH, marker)
    admission = admission_payload(
        packet=packet, packet_sha256=args.expected_packet_sha256,
        packet_review=review, invocation_id=invocation)
    write_exclusive(ADMISSION_PATH, admission)
    RECORDS_DIR.mkdir(mode=0o755, parents=False, exist_ok=False)
    design, scorer = _load_scorer(packet)
    seeds = [row["deal_seed"] for row in design._selection_rows()]
    if len(seeds) != STATE_COUNT or len(set(seeds)) != STATE_COUNT:
        raise ControllerRefused("reviewed state population drift")
    started_ns = time.time_ns()
    monotonic_started = time.perf_counter_ns()
    receipts = []
    for index, seed in enumerate(seeds):
        state_started = time.perf_counter_ns()
        record = scorer.score_state(seed)
        elapsed_ns = time.perf_counter_ns() - state_started
        if elapsed_ns <= 0:
            raise ControllerRefused("state elapsed timing is nonpositive")
        raw = scorer.canonical(record) + b"\n"
        receipt = state_receipt(
            record, state_index=index, elapsed_ns=elapsed_ns,
            raw=raw, scorer=scorer)
        problems = state_receipt_problems(
            receipt, expected_index=index, expected_seed=seed)
        if problems:
            raise ControllerRefused("; ".join(problems))
        write_bytes_exclusive(RECORDS_DIR / receipt["record_file"], raw)
        receipts.append(receipt)
    finished_ns = time.time_ns()
    elapsed = time.perf_counter_ns() - monotonic_started
    if elapsed <= 0 or elapsed >= MAXIMUM_WALL_SECONDS * 10**9:
        raise ControllerRefused("run exceeded reviewed wall-time contract")
    require_clean_exact_git(args.expected_git)
    require_frozen_runtime_inputs(packet["runtime"])
    final = final_payload(
        packet=packet, packet_sha256=args.expected_packet_sha256,
        packet_review=review, admission_sha256=sha256_file(ADMISSION_PATH),
        invocation_id=invocation, state_receipts=receipts,
        started_ns=started_ns, finished_ns=finished_ns)
    problems = final_problems(
        final, packet=packet, packet_sha256=args.expected_packet_sha256)
    if problems:
        raise ControllerRefused("; ".join(problems))
    write_exclusive(FINAL_PATH, final)
    print(json.dumps({
        "status": "COMPLETE_AWAITING_SCORE_FREE_SUPERVISOR_REVIEW",
        "supervisor_final_sha256": sha256_file(FINAL_PATH),
        "states_complete": STATE_COUNT,
        "scored_records_opened_after_publication": False,
        "aggregation_authorized": False,
    }, sort_keys=True))


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    commands = value.add_subparsers(dest="command", required=True)
    review = commands.add_parser("implementation-review-claim")
    review.add_argument("--expected-git", required=True)
    freeze = commands.add_parser("freeze-packet")
    freeze.add_argument("--expected-git", required=True)
    freeze.add_argument("--implementation-review-commit", required=True)
    freeze.add_argument("--systemd-unit", required=True)
    freeze.add_argument("--host-profile", required=True)
    freeze.add_argument("--out", required=True)
    verify = commands.add_parser("verify-packet")
    verify.add_argument("--expected-git", required=True)
    verify.add_argument("--packet", required=True)
    verify.add_argument("--expected-packet-sha256", required=True)
    packet_review = commands.add_parser("packet-review-claim")
    packet_review.add_argument("--expected-git", required=True)
    packet_review.add_argument("--packet", required=True)
    packet_review.add_argument("--expected-packet-sha256", required=True)
    run = commands.add_parser("run")
    run.add_argument("--expected-git", required=True)
    run.add_argument("--packet", required=True)
    run.add_argument("--expected-packet-sha256", required=True)
    run.add_argument("--packet-review-commit", required=True)
    run.add_argument("--admission", required=True)
    run.add_argument("--records", required=True)
    run.add_argument("--final", required=True)
    verify_final = commands.add_parser("verify-final")
    verify_final.add_argument("--expected-git", required=True)
    verify_final.add_argument("--packet", required=True)
    verify_final.add_argument("--expected-packet-sha256", required=True)
    verify_final.add_argument("--final", required=True)
    return value


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.command == "implementation-review-claim":
        require_clean_exact_git(args.expected_git)
        print(canonical(implementation_review_claim(
            expected_git=args.expected_git)).decode().rstrip())
    elif args.command == "freeze-packet":
        freeze_command(args)
    elif args.command == "verify-packet":
        verify_packet_command(args)
    elif args.command == "packet-review-claim":
        packet = load_packet(
            Path(args.packet), args.expected_packet_sha256,
            expected_git=args.expected_git)
        print(canonical(packet_review_claim(
            packet=packet,
            packet_sha256=args.expected_packet_sha256)).decode().rstrip())
    elif args.command == "run":
        run_command(args)
    else:
        verify_final_command(args)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ControllerRefused as exc:
        raise SystemExit(f"REFUSED: {exc}") from exc
