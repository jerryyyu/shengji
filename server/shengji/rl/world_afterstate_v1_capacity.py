"""Bounded train-only capacity and P0 packet for Value-Afterstate V1.

The packet reuses the exact immutable V0 population and opens only its train
rows.  It derives the P0 label ceiling, outcome-blind P1 sub-split, and named
negative-control populations, then measures static row reopening and one
complete eight-member epoch at several CPU configurations.  Configuration
selection is throughput-only.  Calibration/report/provider rows remain
unopened and every scientific/gameplay authority remains false.
"""

from __future__ import annotations

import gc
import hashlib
import json
import os
import platform
import stat
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping

import numpy as np
import torch

from .belief_contract import canonical_json_bytes
from .world_afterstate_capacity import _strict_runtime_binding
from .world_afterstate_dataset import (
    reopen_dataset_manifest, validate_dataset_manifest)
from .world_afterstate_population import validate_population_manifest
from .world_afterstate_v1 import (
    BOOTSTRAP_REPLICATES, evaluate_label_ceiling, validate_label_ceiling)
from .world_afterstate_v1_controls import (
    action_association_permutation, identical_successor_control,
    label_permutation, validate_control_evidence)
from .world_afterstate_v1_dataset import (
    build_advantage_manifest, join_advantage_examples,
    validate_advantage_manifest)
from .world_afterstate_v1_schedule import (
    build_subsplit_manifest, validate_subsplit_manifest)
from .world_afterstate_v1_training import AdvantageTrainingConfigV1
from .world_afterstate_v1_training_controller import train_named_cohort


CAPACITY_SCHEMA = "world-afterstate-advantage-capacity-receipt-v1"
CAPACITY_BUILD_SCHEMA = "world-afterstate-advantage-capacity-build-v1"
REVIEW_CLAIM_SCHEMA = "world-afterstate-v1-capacity-review-claim-v1"
REVIEW_PREFIX = "WORLD_AFTERSTATE_V1_TRAIN_CAPACITY_REVIEW "
REVIEW_LEDGER = "HANDOFF_REVIEW.md"
REVIEWER_NAME = "Claude"
REVIEWER_EMAIL = "noreply@anthropic.com"
REVIEWER_SESSION_TRAILER = "Claude-Session: https://claude.ai/code/session_"
CANONICAL_REMOTE_URL = "https://github.com/jerryyyu/shengji.git"
CANONICAL_REMOTE_REF = "refs/heads/main"
CAPACITY_MEMORY_LIMIT_BYTES = 30 * 1024**3
ROW_WORKER_COUNTS = (1, 2, 4, 8, 16)
MEMBER_WORKER_COUNTS = (1, 2, 4, 8)
ROW_REPETITIONS = 2
PAIR_CAP = 64
SHAPE_NAME = "medium"
MAX_CAPACITY_WALL_NANOSECONDS = 2 * 60 * 60 * 10**9
V0_POPULATION_EXTERNAL_SHA256 = (
    "48155bb59aae2e524bbf3b407a07b68b78dc4b052909c68d8e84d6df6964f581")
V0_POPULATION_MANIFEST_SHA256 = (
    "361389bfd87beebd6c10b4c40712638ef7db900ac0b1a6f62e6dfbd11ea55912")
V0_DATASET_EXTERNAL_SHA256 = (
    "ee9c925d98eae681de0a72422f3f15ee11b49a750424cc17029bbdbcca3dc60d")
V0_DATASET_MANIFEST_SHA256 = (
    "5ad464a9f598147544bfdb3055f83b1fbe1b15661b0152eb1b124acf64104474")
V0_FREEZE_EXTERNAL_SHA256 = (
    "735b367e824e1510b7a951e2fd3ef373c8f3688107d622152a1dfc12830b43a0")
V0_FREEZE_SHA256 = (
    "1139e727fd29f5e295135aedc7e08c3a52508a2deb3927f37629158313cfbc12")
V0_CAPACITY_EXTERNAL_SHA256 = (
    "10bdd80f8f2d0342fd290194de1a84ecc8bc92fcb0ca10a06dcf3fe779bedc5b")
REQUIRED_ENVIRONMENT = {
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONHASHSEED": "0",
    "SHENGJI_FAST": "1",
    "SHENGJI_REQUIRE_VOIDS": "1",
}
BASE_ARTIFACT_PATHS = (
    "p0/label-ceiling.json",
    "p1/advantage-manifest.json",
    "p1/subsplit.json",
)
CONTROL_ARTIFACT_PATHS = (
    "p1/controls/action-association-permutation.json",
    "p1/controls/identical-successor.json",
    "p1/controls/label-permutation.json",
)
ARTIFACT_PATHS = BASE_ARTIFACT_PATHS + CONTROL_ARTIFACT_PATHS
SOURCE_PATHS = (
    "VALUE_AFTERSTATE_V1_DESIGN.md",
    "server/pyproject.toml",
    "server/setup.py",
    "server/uv.lock",
    "server/scripts/world_afterstate_v1_capacity.py",
    "server/shengji/rl/belief_contract.py",
    "server/shengji/rl/world_afterstate.py",
    "server/shengji/rl/world_afterstate_capacity.py",
    "server/shengji/rl/world_afterstate_dataset.py",
    "server/shengji/rl/world_afterstate_evaluation.py",
    "server/shengji/rl/world_afterstate_model.py",
    "server/shengji/rl/world_afterstate_population.py",
    "server/shengji/rl/world_afterstate_v1.py",
    "server/shengji/rl/world_afterstate_v1_capacity.py",
    "server/shengji/rl/world_afterstate_v1_checkpoint.py",
    "server/shengji/rl/world_afterstate_v1_controls.py",
    "server/shengji/rl/world_afterstate_v1_dataset.py",
    "server/shengji/rl/world_afterstate_v1_model.py",
    "server/shengji/rl/world_afterstate_v1_schedule.py",
    "server/shengji/rl/world_afterstate_v1_training.py",
    "server/shengji/rl/world_afterstate_v1_training_controller.py",
    "server/shengji/engine/fast.py",
    "server/shengji/engine/legal.py",
    "server/shengji/engine/round.py",
)
AUTHORITY = {
    "v0_train_row_reopening_authorized": True,
    "train_only_p0_diagnostic_authorized": True,
    "train_only_capacity_epoch_authorized": True,
    "calibration_row_opening_authorized": False,
    "report_row_opening_authorized": False,
    "provider_audit_row_opening_authorized": False,
    "scientific_p1_training_authorized": False,
    "p2_execution_authorized": False,
    "gameplay_authorized": False,
    "strength_claim_authorized": False,
    "merge_authorized": False,
    "promotion_authorized": False,
    "deployment_authorized": False,
    "retry_authorized": False,
    "r5_authorized": False,
}


class WorldAfterstateV1CapacityError(ValueError):
    """A V0 binding, train-only boundary, measurement, or receipt drifted."""


@dataclass(frozen=True)
class CapacityBuildV1:
    receipt: dict[str, Any]
    files: tuple[tuple[str, bytes], ...]
    schema: str = CAPACITY_BUILD_SCHEMA


def _sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha(value: object) -> str:
    return _sha_bytes(canonical_json_bytes(value))


def _digest(value: object, label: str, *, length: int = 64) -> str:
    if type(value) is not str or len(value) != length \
            or any(char not in "0123456789abcdef" for char in value):
        raise WorldAfterstateV1CapacityError(f"{label} drift")
    return value


def _canonical(raw: bytes, label: str) -> dict[str, Any]:
    if type(raw) is not bytes:
        raise WorldAfterstateV1CapacityError(f"{label} byte type drift")
    try:
        value = json.loads(raw.decode("ascii"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise WorldAfterstateV1CapacityError(
            f"{label} is not canonical JSON") from exc
    if type(value) is not dict or canonical_json_bytes(value) != raw:
        raise WorldAfterstateV1CapacityError(
            f"{label} is not canonical JSON")
    return value


def _git(repo: Path, *arguments: str, binary: bool = False) -> str | bytes:
    try:
        result = subprocess.run(
            ("git", *arguments), cwd=repo, check=True,
            capture_output=True, text=not binary)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise WorldAfterstateV1CapacityError(
            "capacity Git authentication failed") from exc
    return result.stdout if binary else result.stdout.strip()


def _sealed_read(path: Path, label: str) -> bytes:
    if not isinstance(path, Path) or path.is_symlink():
        raise WorldAfterstateV1CapacityError(f"{label} path drift")
    try:
        with path.open("rb") as handle:
            before = os.fstat(handle.fileno())
            raw = handle.read()
            after = os.fstat(handle.fileno())
    except OSError as exc:
        raise WorldAfterstateV1CapacityError(
            f"{label} cannot be read") from exc
    identity = lambda value: (
        value.st_dev, value.st_ino, value.st_size,
        value.st_mtime_ns, value.st_ctime_ns)
    if identity(before) != identity(after) or before.st_nlink != 1 \
            or stat.S_IMODE(before.st_mode) != 0o400 \
            or not stat.S_ISREG(before.st_mode) \
            or before.st_size != len(raw):
        raise WorldAfterstateV1CapacityError(
            f"{label} is mutable or changed while read")
    return raw


def _source_bindings(repo: Path, expected_git: str) -> list[dict[str, Any]]:
    repo = repo.resolve()
    _digest(expected_git, "capacity Git", length=40)
    head = _git(repo, "rev-parse", "HEAD")
    status = _git(repo, "status", "--porcelain", "--untracked-files=all")
    if head != expected_git or status:
        raise WorldAfterstateV1CapacityError(
            "capacity source is not the exact clean Git head")
    rows = []
    for relative in SOURCE_PATHS:
        path = repo / relative
        if path.is_symlink() or not path.is_file():
            raise WorldAfterstateV1CapacityError(
                "capacity source path population drift")
        raw = path.read_bytes()
        committed = _git(
            repo, "show", f"{expected_git}:{relative}", binary=True)
        if raw != committed:
            raise WorldAfterstateV1CapacityError(
                "capacity source differs from committed bytes")
        rows.append({
            "relative_path": relative,
            "byte_count": len(raw),
            "sha256": _sha_bytes(raw),
        })
    return rows


def expected_review_claim(expected_git: str) -> dict[str, Any]:
    _digest(expected_git, "capacity review source Git", length=40)
    return {
        "schema": REVIEW_CLAIM_SCHEMA,
        "source_git": expected_git,
        "v0_population_external_sha256": V0_POPULATION_EXTERNAL_SHA256,
        "v0_dataset_external_sha256": V0_DATASET_EXTERNAL_SHA256,
        "v0_freeze_external_sha256": V0_FREEZE_EXTERNAL_SHA256,
        "row_worker_counts": list(ROW_WORKER_COUNTS),
        "member_worker_counts": list(MEMBER_WORKER_COUNTS),
        "wall_cap_nanoseconds": MAX_CAPACITY_WALL_NANOSECONDS,
        "memory_limit_bytes": CAPACITY_MEMORY_LIMIT_BYTES,
        "authority": dict(AUTHORITY),
    }


def _canonical_remote_tip(repo: Path) -> str:
    try:
        output = subprocess.run(
            ("git", "ls-remote", "--exit-code", CANONICAL_REMOTE_URL,
             CANONICAL_REMOTE_REF), cwd=repo, check=True,
            capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise WorldAfterstateV1CapacityError(
            "capacity review canonical remote lookup failed") from exc
    fields = output.split()
    if len(fields) != 2 or fields[1] != CANONICAL_REMOTE_REF:
        raise WorldAfterstateV1CapacityError(
            "capacity review canonical remote identity drift")
    return _digest(fields[0], "capacity review remote tip", length=40)


def authenticate_review_commit(
        repo: Path, *, expected_git: str, review_commit: str) \
        -> dict[str, str]:
    """Authenticate one append-only external capacity marker on real main."""
    claim = expected_review_claim(expected_git)
    _digest(review_commit, "capacity review commit", length=40)
    remote_tip = _canonical_remote_tip(repo)
    try:
        local_tip = _git(repo, "rev-parse", "origin/main")
        if local_tip != remote_tip:
            raise WorldAfterstateV1CapacityError(
                "capacity review local main differs from real remote")
        if subprocess.run(
                ("git", "merge-base", "--is-ancestor", review_commit,
                 remote_tip), cwd=repo, capture_output=True).returncode != 0:
            raise WorldAfterstateV1CapacityError(
                "capacity review is not on canonical remote main")
        parents = str(_git(
            repo, "show", "-s", "--format=%P", review_commit)).split()
        identity = tuple(str(_git(
            repo, "show", "-s", f"--format={field}", review_commit))
                         for field in ("%an", "%ae", "%cn", "%ce"))
        message = str(_git(
            repo, "show", "-s", "--format=%B", review_commit))
        changed = str(_git(
            repo, "diff-tree", "--no-commit-id", "--name-only", "-r",
            review_commit)).splitlines()
        if len(parents) != 1 or identity != (
                REVIEWER_NAME, REVIEWER_EMAIL,
                REVIEWER_NAME, REVIEWER_EMAIL) \
                or REVIEWER_SESSION_TRAILER not in message \
                or changed != [REVIEW_LEDGER]:
            raise WorldAfterstateV1CapacityError(
                "capacity review provenance drift")
        current = _git(
            repo, "show", f"{review_commit}:{REVIEW_LEDGER}", binary=True)
        previous = _git(
            repo, "show", f"{parents[0]}:{REVIEW_LEDGER}", binary=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise WorldAfterstateV1CapacityError(
            "capacity review Git lookup failed") from exc
    if type(current) is not bytes or type(previous) is not bytes \
            or not current.startswith(previous):
        raise WorldAfterstateV1CapacityError(
            "capacity review ledger is not append-only")
    marker = REVIEW_PREFIX.encode("ascii") + canonical_json_bytes(claim)
    prefix = REVIEW_PREFIX.encode("ascii")
    current_matches = [line for line in current.splitlines(keepends=True)
                       if line.startswith(prefix)]
    previous_matches = [line for line in previous.splitlines(keepends=True)
                        if line.startswith(prefix)]
    if current_matches != [marker] or previous_matches:
        raise WorldAfterstateV1CapacityError(
            "capacity review marker introduction drift")
    return {
        "review_commit": review_commit,
        "canonical_remote_tip_at_admission": remote_tip,
        "review_marker_sha256": _sha_bytes(marker),
        "review_claim_sha256": _sha(claim),
    }


def _runtime() -> dict[str, Any]:
    observed = {key: os.environ.get(key) for key in REQUIRED_ENVIRONMENT}
    if observed != REQUIRED_ENVIRONMENT:
        raise WorldAfterstateV1CapacityError(
            "capacity environment drift")
    if not torch.are_deterministic_algorithms_enabled():
        raise WorldAfterstateV1CapacityError(
            "capacity deterministic algorithms are not enabled")
    strict = dict(_strict_runtime_binding())
    if strict.pop("environment", None) != {
            "SHENGJI_FAST": "1", "SHENGJI_REQUIRE_VOIDS": "1"}:
        raise WorldAfterstateV1CapacityError(
            "capacity strict runtime environment drift")
    return {
        "host": platform.node(),
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "torch": str(torch.__version__),
        "numpy": str(np.__version__),
        "cpu_count": os.cpu_count(),
        "torch_threads_at_entry": torch.get_num_threads(),
        "torch_interop_threads": torch.get_num_interop_threads(),
        "torch_deterministic_algorithms": True,
        **strict,
        "environment": observed,
    }


def _cgroup_snapshot() -> dict[str, Any]:
    try:
        rows = Path("/proc/self/cgroup").read_text().splitlines()
        unified = [row.split(":", 2)[2] for row in rows
                   if row.startswith("0::")]
        if len(unified) != 1:
            raise ValueError
        root = Path("/sys/fs/cgroup") / unified[0].lstrip("/")
        current = int((root / "memory.current").read_text().strip())
        peak = int((root / "memory.peak").read_text().strip())
        cpu = {
            row.split()[0]: int(row.split()[1])
            for row in (root / "cpu.stat").read_text().splitlines()
        }
        usage_ns = cpu["usage_usec"] * 1000
    except (OSError, KeyError, ValueError) as exc:
        raise WorldAfterstateV1CapacityError(
            "capacity requires cgroup-v2 CPU and memory accounting") from exc
    if current < 0 or peak <= 0 or peak < current or usage_ns < 0:
        raise WorldAfterstateV1CapacityError(
            "capacity cgroup-v2 accounting drift")
    return {
        "method": "linux-cgroup-v2",
        "path": str(root),
        "memory_current_bytes": current,
        "memory_peak_bytes": peak,
        "cpu_usage_nanoseconds": usage_ns,
    }


def _phase_resources(before: Mapping[str, Any], after: Mapping[str, Any],
                     wall_nanoseconds: int, cpu_count: int) -> dict[str, int]:
    if before.get("method") != "linux-cgroup-v2" \
            or after.get("method") != before.get("method") \
            or after.get("path") != before.get("path") \
            or isinstance(wall_nanoseconds, bool) \
            or not isinstance(wall_nanoseconds, int) \
            or wall_nanoseconds <= 0 \
            or isinstance(cpu_count, bool) or not isinstance(cpu_count, int) \
            or cpu_count <= 0:
        raise WorldAfterstateV1CapacityError(
            "capacity phase resource request drift")
    cpu = (after["cpu_usage_nanoseconds"]
           - before["cpu_usage_nanoseconds"])
    if cpu < 0 or after["memory_peak_bytes"] < before["memory_peak_bytes"]:
        raise WorldAfterstateV1CapacityError(
            "capacity phase cgroup counters drifted")
    return {
        "wall_nanoseconds": wall_nanoseconds,
        "cpu_nanoseconds": cpu,
        "average_cores_milli": cpu * 1000 // wall_nanoseconds,
        "host_cpu_utilization_ppm": (
            cpu * 1_000_000 // (wall_nanoseconds * cpu_count)),
        "memory_current_bytes_at_finish": after["memory_current_bytes"],
        "memory_peak_bytes_at_finish": after["memory_peak_bytes"],
    }


def _remaining_capacity_wall(started_wall: int) -> int:
    """Return the positive remainder of the one composed packet deadline."""
    remaining = MAX_CAPACITY_WALL_NANOSECONDS - (
        time.monotonic_ns() - started_wall)
    if remaining <= 0:
        raise WorldAfterstateV1CapacityError(
            "capacity wall deadline expired before cohort training")
    return remaining


def _validate_v0_inputs(population_raw: bytes, dataset_raw: bytes,
                        freeze_raw: bytes) \
        -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    if _sha_bytes(population_raw) != V0_POPULATION_EXTERNAL_SHA256 \
            or _sha_bytes(dataset_raw) != V0_DATASET_EXTERNAL_SHA256 \
            or _sha_bytes(freeze_raw) != V0_FREEZE_EXTERNAL_SHA256:
        raise WorldAfterstateV1CapacityError(
            "capacity V0 external input binding drift")
    population = _canonical(population_raw, "capacity V0 population")
    dataset = _canonical(dataset_raw, "capacity V0 dataset manifest")
    freeze = _canonical(freeze_raw, "capacity V0 freeze")
    try:
        validate_population_manifest(population)
        validate_dataset_manifest(dataset, population_manifest=population)
    except ValueError as exc:
        raise WorldAfterstateV1CapacityError(
            "capacity V0 manifest reconstruction drift") from exc
    freeze_body = {key: item for key, item in freeze.items()
                   if key != "freeze_sha256"}
    if population.get("manifest_sha256") \
            != V0_POPULATION_MANIFEST_SHA256 \
            or dataset.get("manifest_sha256") \
            != V0_DATASET_MANIFEST_SHA256 \
            or dataset.get("freeze_sha256") != V0_FREEZE_SHA256 \
            or freeze.get("freeze_sha256") != V0_FREEZE_SHA256 \
            or _sha(freeze_body) != V0_FREEZE_SHA256 \
            or freeze.get("capacity", {}).get("external_sha256") \
            != V0_CAPACITY_EXTERNAL_SHA256 \
            or freeze.get("population_packet", {}).get(
                "population_manifest_external_sha256") \
            != V0_POPULATION_EXTERNAL_SHA256 \
            or freeze.get("population_packet", {}).get(
                "population_manifest_sha256") \
            != V0_POPULATION_MANIFEST_SHA256:
        raise WorldAfterstateV1CapacityError(
            "capacity V0 internal input binding drift")
    return population, dataset, freeze


def _population_sha(rows) -> str:
    return _sha([{
        "state_group_id": binding["state_group_id"],
        "candidate_index": binding["candidate_index"],
        "replicate": binding["replicate"],
        "row_sha256": reopened.row_sha256,
    } for binding, reopened in rows])


def _training_config() -> AdvantageTrainingConfigV1:
    return AdvantageTrainingConfigV1(
        learning_rate_ppb=1_000_000,
        weight_decay_ppb=10_000_000,
        gradient_norm_milli=1_000,
        max_epochs=1,
        early_stop_patience=1,
        minimum_improvement_nanoloss=1)


def _initialization_seeds() -> tuple[int, ...]:
    return tuple(
        int.from_bytes(hashlib.sha256(
            f"world-afterstate-v1-capacity|member|{index}".encode(
                "ascii")).digest()[:8], "big") & (2**63 - 1)
        for index in range(8))


def _schedule_seed() -> int:
    return int.from_bytes(hashlib.sha256(
        b"world-afterstate-v1-capacity|schedule").digest()[:8], "big") \
        & (2**63 - 1)


def _artifact_rows(files: Mapping[str, bytes]) -> list[dict[str, Any]]:
    if type(files) is not dict or tuple(files) not in (
            BASE_ARTIFACT_PATHS, ARTIFACT_PATHS):
        raise WorldAfterstateV1CapacityError(
            "capacity artifact population drift")
    return [{
        "relative_path": path,
        "byte_count": len(files[path]),
        "external_sha256": _sha_bytes(files[path]),
    } for path in files]


def _validate_measurement(row: object, *, kind: str) -> None:
    common = {
        "schedule_index", "wall_nanoseconds", "cpu_nanoseconds",
        "average_cores_milli", "host_cpu_utilization_ppm",
        "memory_current_bytes_at_finish", "memory_peak_bytes_at_finish",
    }
    extra = ({
        "repetition", "workers", "row_count", "rows_per_second_ppm",
        "output_population_sha256",
    } if kind == "row" else {
        "member_workers", "torch_threads", "member_count", "pair_count",
        "member_pairs_per_second_ppm", "output_population_sha256",
    })
    if type(row) is not dict or set(row) != common | extra:
        raise WorldAfterstateV1CapacityError(
            f"capacity {kind} measurement schema drift")
    integer_fields = (common - {"host_cpu_utilization_ppm"}) | (
        {"host_cpu_utilization_ppm"} | extra
        - {"output_population_sha256"})
    if any(isinstance(row.get(key), bool) or not isinstance(row.get(key), int)
           for key in integer_fields):
        raise WorldAfterstateV1CapacityError(
            f"capacity {kind} measurement type drift")
    _digest(row.get("output_population_sha256"),
            f"capacity {kind} population SHA-256")
    positive = ("wall_nanoseconds", "memory_peak_bytes_at_finish",
                "row_count", "rows_per_second_ppm") if kind == "row" \
        else ("wall_nanoseconds", "member_workers", "torch_threads",
              "member_count", "pair_count",
              "member_pairs_per_second_ppm",
              "memory_peak_bytes_at_finish")
    if any(row[key] <= 0 for key in positive) \
            or row["cpu_nanoseconds"] < 0 \
            or row["average_cores_milli"] < 0 \
            or row["host_cpu_utilization_ppm"] < 0 \
            or row["memory_current_bytes_at_finish"] < 0 \
            or row["memory_current_bytes_at_finish"] \
            > row["memory_peak_bytes_at_finish"] \
            or row["average_cores_milli"] \
            != row["cpu_nanoseconds"] * 1000 \
            // row["wall_nanoseconds"] \
            or kind == "row" and row["rows_per_second_ppm"] \
            != row["row_count"] * 10**15 // row["wall_nanoseconds"] \
            or kind == "cohort" \
            and row["member_pairs_per_second_ppm"] \
            != row["pair_count"] * row["member_count"] * 10**15 \
            // row["wall_nanoseconds"]:
        raise WorldAfterstateV1CapacityError(
            f"capacity {kind} measurement value drift")


def validate_capacity_receipt(value: object) -> None:
    required = {
        "schema", "source_git", "source_tree_clean", "runtime",
        "source_bindings", "review", "v0_inputs", "schedule",
        "train_population",
        "row_reopen_measurements", "cohort_measurements", "selection",
        "terminal_route", "aggregate_resources", "artifacts", "authority",
        "receipt_sha256",
    }
    if type(value) is not dict or set(value) != required \
            or value.get("schema") != CAPACITY_SCHEMA \
            or value.get("source_tree_clean") is not True \
            or value.get("authority") != AUTHORITY:
        raise WorldAfterstateV1CapacityError(
            "capacity receipt identity drift")
    _digest(value.get("source_git"), "capacity source Git", length=40)
    _digest(value.get("receipt_sha256"), "capacity receipt SHA-256")
    runtime = value.get("runtime")
    runtime_required = {
        "host", "platform", "machine", "python", "torch", "numpy",
        "cpu_count", "torch_threads_at_entry", "torch_interop_threads",
        "torch_deterministic_algorithms", "environment",
        "python_executable", "python_executable_sha256",
        "fast_router_path", "fast_router_sha256", "native_path",
        "native_sha256", "compiled_engine_active", "safe_path",
        "dont_write_bytecode", "pythonpath_absent",
    }
    if type(runtime) is not dict or set(runtime) != runtime_required \
            or runtime.get("environment") != REQUIRED_ENVIRONMENT \
            or runtime.get("torch_deterministic_algorithms") is not True \
            or any(runtime.get(key) is not True for key in (
                "compiled_engine_active", "safe_path",
                "dont_write_bytecode", "pythonpath_absent")) \
            or any(isinstance(runtime.get(key), bool)
                   or not isinstance(runtime.get(key), int)
                   or runtime[key] <= 0 for key in (
                       "cpu_count", "torch_threads_at_entry",
                       "torch_interop_threads")):
        raise WorldAfterstateV1CapacityError(
            "capacity runtime identity drift")
    for key in ("python_executable_sha256", "fast_router_sha256",
                "native_sha256"):
        _digest(runtime.get(key), f"capacity runtime {key}")
    sources = value.get("source_bindings")
    if type(sources) is not list or len(sources) != len(SOURCE_PATHS) \
            or [row.get("relative_path") for row in sources] \
            != list(SOURCE_PATHS):
        raise WorldAfterstateV1CapacityError(
            "capacity source binding population drift")
    for row in sources:
        if type(row) is not dict or set(row) != {
                "relative_path", "byte_count", "sha256"} \
                or isinstance(row.get("byte_count"), bool) \
                or not isinstance(row.get("byte_count"), int) \
                or row["byte_count"] <= 0:
            raise WorldAfterstateV1CapacityError(
                "capacity source binding row drift")
        _digest(row.get("sha256"), "capacity source binding SHA-256")
    review = value.get("review")
    if type(review) is not dict or set(review) != {
            "review_commit", "canonical_remote_tip_at_admission",
            "review_marker_sha256", "review_claim_sha256"}:
        raise WorldAfterstateV1CapacityError(
            "capacity review receipt drift")
    for key, length in (("review_commit", 40),
                        ("canonical_remote_tip_at_admission", 40),
                        ("review_marker_sha256", 64),
                        ("review_claim_sha256", 64)):
        _digest(review.get(key), f"capacity review {key}", length=length)
    if review["review_claim_sha256"] \
            != _sha(expected_review_claim(value["source_git"])):
        raise WorldAfterstateV1CapacityError(
            "capacity review claim binding drift")
    expected_v0 = {
        "population_external_sha256": V0_POPULATION_EXTERNAL_SHA256,
        "population_manifest_sha256": V0_POPULATION_MANIFEST_SHA256,
        "dataset_external_sha256": V0_DATASET_EXTERNAL_SHA256,
        "dataset_manifest_sha256": V0_DATASET_MANIFEST_SHA256,
        "freeze_external_sha256": V0_FREEZE_EXTERNAL_SHA256,
        "freeze_sha256": V0_FREEZE_SHA256,
        "capacity_external_sha256": V0_CAPACITY_EXTERNAL_SHA256,
    }
    if value.get("v0_inputs") != expected_v0:
        raise WorldAfterstateV1CapacityError(
            "capacity V0 receipt binding drift")
    schedule = value.get("schedule")
    if type(schedule) is not dict or set(schedule) != {
            "row_worker_counts", "row_repetitions",
            "member_worker_counts", "pair_cap", "shape_name",
            "bootstrap_replicates", "capacity_config",
            "initialization_seeds", "schedule_seed",
            "wall_cap_nanoseconds"} \
            or schedule.get("row_worker_counts") \
            != list(ROW_WORKER_COUNTS) \
            or schedule.get("row_repetitions") != ROW_REPETITIONS \
            or schedule.get("member_worker_counts") \
            != list(MEMBER_WORKER_COUNTS) \
            or schedule.get("pair_cap") != PAIR_CAP \
            or schedule.get("shape_name") != SHAPE_NAME \
            or schedule.get("bootstrap_replicates") != BOOTSTRAP_REPLICATES \
            or schedule.get("capacity_config") \
            != _training_config().payload() \
            or schedule.get("initialization_seeds") \
            != list(_initialization_seeds()) \
            or schedule.get("schedule_seed") != _schedule_seed() \
            or schedule.get("wall_cap_nanoseconds") \
            != MAX_CAPACITY_WALL_NANOSECONDS:
        raise WorldAfterstateV1CapacityError(
            "capacity schedule drift")
    population = value.get("train_population")
    if type(population) is not dict or set(population) != {
            "train_row_count", "eligible_state_count", "pair_count",
            "fit_state_count", "select_state_count",
            "train_row_population_sha256", "advantage_manifest_sha256",
            "subsplit_manifest_sha256", "label_ceiling_result_sha256",
            "label_ceiling_passed", "calibration_row_bytes_opened",
            "report_row_bytes_opened", "provider_audit_row_bytes_opened"} \
            or any(population.get(key) is not False for key in (
                "calibration_row_bytes_opened", "report_row_bytes_opened",
                "provider_audit_row_bytes_opened")) \
            or type(population.get("label_ceiling_passed")) is not bool \
            or any(isinstance(population.get(key), bool)
                   or not isinstance(population.get(key), int)
                   or population[key] <= 0 for key in (
                       "train_row_count", "eligible_state_count",
                       "pair_count", "fit_state_count",
                       "select_state_count")):
        raise WorldAfterstateV1CapacityError(
            "capacity train population drift")
    for key in ("train_row_population_sha256",
                "advantage_manifest_sha256", "subsplit_manifest_sha256",
                "label_ceiling_result_sha256"):
        _digest(population.get(key), f"capacity train {key}")
    row_measurements = value.get("row_reopen_measurements")
    expected_rows = ROW_REPETITIONS * len(ROW_WORKER_COUNTS)
    if type(row_measurements) is not list \
            or len(row_measurements) != expected_rows:
        raise WorldAfterstateV1CapacityError(
            "capacity row measurement population drift")
    for row in row_measurements:
        _validate_measurement(row, kind="row")
        if row["host_cpu_utilization_ppm"] \
                != row["cpu_nanoseconds"] * 1_000_000 \
                // (row["wall_nanoseconds"] * runtime["cpu_count"]):
            raise WorldAfterstateV1CapacityError(
                "capacity row CPU utilization reconstruction drift")
    expected_worker_order = []
    for repetition in range(ROW_REPETITIONS):
        order = (ROW_WORKER_COUNTS if repetition % 2 == 0
                 else tuple(reversed(ROW_WORKER_COUNTS)))
        expected_worker_order.extend((repetition, workers)
                                     for workers in order)
    if [(row["repetition"], row["workers"])
            for row in row_measurements] != expected_worker_order \
            or [row["schedule_index"] for row in row_measurements] \
            != list(range(expected_rows)) \
            or any(row["row_count"] != population["train_row_count"]
                   for row in row_measurements) \
            or len({row["output_population_sha256"]
                    for row in row_measurements}) != 1:
        raise WorldAfterstateV1CapacityError(
            "capacity row measurement schedule drift")
    cohorts = value.get("cohort_measurements")
    p0_passed = population["label_ceiling_passed"]
    if type(cohorts) is not list or len(cohorts) != (
            len(MEMBER_WORKER_COUNTS) if p0_passed else 0):
        raise WorldAfterstateV1CapacityError(
            "capacity cohort measurement population drift")
    for row in cohorts:
        _validate_measurement(row, kind="cohort")
        if row["host_cpu_utilization_ppm"] \
                != row["cpu_nanoseconds"] * 1_000_000 \
                // (row["wall_nanoseconds"] * runtime["cpu_count"]):
            raise WorldAfterstateV1CapacityError(
                "capacity cohort CPU utilization reconstruction drift")
    expected_threads = [max(
        1, runtime["cpu_count"] // workers)
        for workers in MEMBER_WORKER_COUNTS]
    if p0_passed and (
            [row["schedule_index"] for row in cohorts]
            != list(range(len(cohorts)))
            or [row["member_workers"] for row in cohorts]
            != list(MEMBER_WORKER_COUNTS)
            or [row["torch_threads"] for row in cohorts]
            != expected_threads
            or any(row["member_count"] != 8 for row in cohorts)
            or any(row["pair_count"] != population["pair_count"]
                   for row in cohorts)):
        raise WorldAfterstateV1CapacityError(
            "capacity cohort measurement schedule drift")
    selection = value.get("selection")
    best_row_workers = max(
        ROW_WORKER_COUNTS,
        key=lambda workers: (
            sum(row["rows_per_second_ppm"] for row in row_measurements
                if row["workers"] == workers), -workers))
    best_cohort = (max(
        cohorts,
        key=lambda row: (row["member_pairs_per_second_ppm"],
                         -row["member_workers"])) if cohorts else None)
    if selection != {
            "row_workers": best_row_workers,
            "member_workers": (
                best_cohort["member_workers"] if best_cohort else None),
            "torch_threads": (
                best_cohort["torch_threads"] if best_cohort else None),
            "selection_uses_outcomes_or_model_quality": False}:
        raise WorldAfterstateV1CapacityError(
            "capacity throughput-only selection drift")
    expected_route = ("PASS_TO_P1_CAPACITY" if p0_passed
                      else "STOP_NO_REPRODUCIBLE_ACTION_LABEL")
    if value.get("terminal_route") != expected_route:
        raise WorldAfterstateV1CapacityError(
            "capacity P0 terminal route drift")
    resources = value.get("aggregate_resources")
    if type(resources) is not dict or set(resources) != {
            "method", "path", "started_memory_current_bytes",
            "started_memory_peak_bytes", "finished_memory_current_bytes",
            "finished_memory_peak_bytes", "started_cpu_usage_nanoseconds",
            "finished_cpu_usage_nanoseconds", "wall_nanoseconds",
            "memory_limit_bytes", "within_wall_and_memory_caps"} \
            or resources.get("method") != "linux-cgroup-v2" \
            or resources.get("memory_limit_bytes") \
            != CAPACITY_MEMORY_LIMIT_BYTES \
            or resources.get("within_wall_and_memory_caps") is not True \
            or any(isinstance(resources.get(key), bool)
                   or not isinstance(resources.get(key), int)
                   or resources[key] < 0 for key in (
                       "started_memory_current_bytes",
                       "started_memory_peak_bytes",
                       "finished_memory_current_bytes",
                       "finished_memory_peak_bytes",
                       "started_cpu_usage_nanoseconds",
                       "finished_cpu_usage_nanoseconds",
                       "wall_nanoseconds", "memory_limit_bytes")) \
            or resources.get("started_memory_peak_bytes", 0) \
            < resources.get("started_memory_current_bytes", 0) \
            or resources.get("finished_memory_peak_bytes", 0) \
            < resources.get("finished_memory_current_bytes", 0) \
            or resources.get("finished_memory_peak_bytes", 0) \
            < resources.get("started_memory_peak_bytes", 0) \
            or resources.get("finished_cpu_usage_nanoseconds", 0) \
            < resources.get("started_cpu_usage_nanoseconds", 0) \
            or resources.get("wall_nanoseconds", 0) <= 0 \
            or resources.get("finished_memory_peak_bytes", 0) \
            > CAPACITY_MEMORY_LIMIT_BYTES \
            or resources.get("wall_nanoseconds", 0) \
            > MAX_CAPACITY_WALL_NANOSECONDS:
        raise WorldAfterstateV1CapacityError(
            "capacity aggregate resource drift")
    artifacts = value.get("artifacts")
    expected_artifacts = (ARTIFACT_PATHS if p0_passed
                          else BASE_ARTIFACT_PATHS)
    if type(artifacts) is not list \
            or [row.get("relative_path") for row in artifacts] \
            != list(expected_artifacts):
        raise WorldAfterstateV1CapacityError(
            "capacity artifact receipt drift")
    for row in artifacts:
        if type(row) is not dict or set(row) != {
                "relative_path", "byte_count", "external_sha256"} \
                or isinstance(row.get("byte_count"), bool) \
                or not isinstance(row.get("byte_count"), int) \
                or row["byte_count"] <= 0:
            raise WorldAfterstateV1CapacityError(
                "capacity artifact row drift")
        _digest(row.get("external_sha256"),
                "capacity artifact external SHA-256")
    body = {key: item for key, item in value.items()
            if key != "receipt_sha256"}
    if value["receipt_sha256"] != _sha(body):
        raise WorldAfterstateV1CapacityError(
            "capacity receipt reconstruction drift")


def _reopen_components(files: Mapping[str, bytes]):
    if tuple(files) not in (BASE_ARTIFACT_PATHS, ARTIFACT_PATHS):
        raise WorldAfterstateV1CapacityError(
            "capacity component population drift")
    artifacts = {path: _canonical(files[path], f"capacity {path}")
                 for path in files}
    try:
        validate_label_ceiling(artifacts["p0/label-ceiling.json"])
        validate_advantage_manifest(
            artifacts["p1/advantage-manifest.json"])
        validate_subsplit_manifest(artifacts["p1/subsplit.json"])
        for path in CONTROL_ARTIFACT_PATHS:
            if path not in artifacts:
                continue
            validate_control_evidence(artifacts[path])
    except ValueError as exc:
        raise WorldAfterstateV1CapacityError(
            "capacity component reconstruction drift") from exc
    return artifacts


def reopen_capacity_build(value: CapacityBuildV1) -> CapacityBuildV1:
    if type(value) is not CapacityBuildV1 \
            or value.schema != CAPACITY_BUILD_SCHEMA \
            or type(value.files) is not tuple \
            or any(type(row) is not tuple or len(row) != 2
                   or type(row[0]) is not str or type(row[1]) is not bytes
                   for row in value.files):
        raise WorldAfterstateV1CapacityError(
            "capacity build identity drift")
    validate_capacity_receipt(value.receipt)
    files = dict(value.files)
    expected_paths = (ARTIFACT_PATHS
                      if value.receipt["train_population"][
                          "label_ceiling_passed"]
                      else BASE_ARTIFACT_PATHS)
    if len(files) != len(value.files) or tuple(files) != expected_paths \
            or _artifact_rows(files) != value.receipt["artifacts"]:
        raise WorldAfterstateV1CapacityError(
            "capacity build file binding drift")
    artifacts = _reopen_components(files)
    p0 = artifacts["p0/label-ceiling.json"]
    manifest = artifacts["p1/advantage-manifest.json"]
    subsplit = artifacts["p1/subsplit.json"]
    population = value.receipt["train_population"]
    if p0["passed"] is not population["label_ceiling_passed"] \
            or p0["result_sha256"] \
            != population["label_ceiling_result_sha256"] \
            or manifest["manifest_sha256"] \
            != population["advantage_manifest_sha256"] \
            or manifest["state_count"] != population["eligible_state_count"] \
            or manifest["pair_count"] != population["pair_count"] \
            or subsplit["manifest_sha256"] \
            != population["subsplit_manifest_sha256"] \
            or subsplit["fit_state_count"] \
            != population["fit_state_count"] \
            or subsplit["select_state_count"] \
            != population["select_state_count"]:
        raise WorldAfterstateV1CapacityError(
            "capacity component cross-binding drift")
    return value


def run_capacity(
        *, repo: Path, expected_git: str, population_path: Path,
        dataset_manifest_path: Path, freeze_path: Path, row_root: Path,
        review_commit: str,
        progress: Callable[[dict[str, Any]], None] | None = None) \
        -> CapacityBuildV1:
    """Run the exact train-only P0 and throughput schedule once."""
    if not isinstance(repo, Path) or not repo.is_absolute() \
            or not isinstance(row_root, Path) or not row_root.is_dir() \
            or row_root.is_symlink():
        raise WorldAfterstateV1CapacityError(
            "capacity path request drift")
    started_wall = time.monotonic_ns()
    source_bindings = _source_bindings(repo, expected_git)
    review = authenticate_review_commit(
        repo, expected_git=expected_git, review_commit=review_commit)
    torch.use_deterministic_algorithms(True)
    runtime = _runtime()
    cpu_count = runtime["cpu_count"]
    if cpu_count < max(ROW_WORKER_COUNTS):
        raise WorldAfterstateV1CapacityError(
            "capacity host has fewer than 16 logical CPUs")
    population_raw = _sealed_read(population_path, "capacity V0 population")
    dataset_raw = _sealed_read(
        dataset_manifest_path, "capacity V0 dataset manifest")
    freeze_raw = _sealed_read(freeze_path, "capacity V0 freeze")
    population_manifest, dataset_manifest, _freeze = _validate_v0_inputs(
        population_raw, dataset_raw, freeze_raw)
    aggregate_start = _cgroup_snapshot()

    def emit(stage: str, completed: int, total: int,
             **extra: Any) -> None:
        if progress is not None:
            progress({
                "stage": stage, "completed": completed, "total": total,
                "percent_basis_points": completed * 10_000 // total,
                **extra,
            })

    row_measurements = []
    expected_population_sha = None
    schedule_index = 0
    for repetition in range(ROW_REPETITIONS):
        workers_for_repetition = (
            ROW_WORKER_COUNTS if repetition % 2 == 0
            else tuple(reversed(ROW_WORKER_COUNTS)))
        for workers in workers_for_repetition:
            before = _cgroup_snapshot()
            phase_started = time.monotonic_ns()
            rows = reopen_dataset_manifest(
                dataset_manifest, population_manifest=population_manifest,
                row_root=row_root, allowed_folds=("train",),
                reconstruct_continuations=False,
                reconstruction_workers=workers,
                deadline_monotonic_ns=(
                    started_wall + MAX_CAPACITY_WALL_NANOSECONDS),
                progress=lambda completed, total, w=workers, r=repetition:
                    emit("row-reopen", completed, total,
                         workers=w, repetition=r))
            elapsed = time.monotonic_ns() - phase_started
            after = _cgroup_snapshot()
            population_sha = _population_sha(rows)
            if expected_population_sha is None:
                expected_population_sha = population_sha
            elif population_sha != expected_population_sha:
                raise WorldAfterstateV1CapacityError(
                    "capacity parallel row output drift")
            resources = _phase_resources(before, after, elapsed, cpu_count)
            count = len(rows)
            row_measurements.append({
                "schedule_index": schedule_index,
                "repetition": repetition, "workers": workers,
                "row_count": count,
                "rows_per_second_ppm": count * 10**15 // elapsed,
                "output_population_sha256": population_sha,
                **resources,
            })
            schedule_index += 1
            del rows
            gc.collect()
            if time.monotonic_ns() - started_wall \
                    > MAX_CAPACITY_WALL_NANOSECONDS:
                raise WorldAfterstateV1CapacityError(
                    "capacity wall deadline expired")
    if expected_population_sha is None:
        raise WorldAfterstateV1CapacityError(
            "capacity produced no row population")
    selected_row_workers = max(
        ROW_WORKER_COUNTS,
        key=lambda workers: (
            sum(row["rows_per_second_ppm"] for row in row_measurements
                if row["workers"] == workers), -workers))
    rows = reopen_dataset_manifest(
        dataset_manifest, population_manifest=population_manifest,
        row_root=row_root, allowed_folds=("train",),
        reconstruct_continuations=False,
        reconstruction_workers=selected_row_workers,
        deadline_monotonic_ns=(
            started_wall + MAX_CAPACITY_WALL_NANOSECONDS),
        progress=lambda completed, total: emit(
            "selected-row-reopen", completed, total,
            workers=selected_row_workers))
    if _population_sha(rows) != expected_population_sha:
        raise WorldAfterstateV1CapacityError(
            "capacity selected row output drift")
    joined = tuple(join_advantage_examples(
        [reopened for _binding, reopened in rows]))
    pair_manifest = build_advantage_manifest(
        joined,
        v0_dataset_manifest_sha256=V0_DATASET_MANIFEST_SHA256)
    p0 = evaluate_label_ceiling(
        tuple(value.pair for value in joined),
        bootstrap_replicates=BOOTSTRAP_REPLICATES)
    state_bindings_by_id = {}
    for value in joined:
        state_bindings_by_id.setdefault(value.pair.state_group_id, {
            "deal_group_sha256": value.pair.deal_group_sha256,
            "state_group_id": value.pair.state_group_id,
            "fold": "train",
        })
    subsplit = build_subsplit_manifest(
        [state_bindings_by_id[key]
         for key in sorted(state_bindings_by_id)],
        v0_population_manifest_sha256=V0_POPULATION_MANIFEST_SHA256)
    files = {
        "p0/label-ceiling.json": canonical_json_bytes(p0),
        "p1/advantage-manifest.json": canonical_json_bytes(pair_manifest),
        "p1/subsplit.json": canonical_json_bytes(subsplit),
    }
    if p0["passed"]:
        identical, identical_evidence = identical_successor_control(joined)
        del identical
        gc.collect()
        association, association_evidence = \
            action_association_permutation(joined)
        del association
        gc.collect()
        permuted, permuted_evidence = label_permutation(joined)
        del permuted
        gc.collect()
        control_evidence = {
            "identical-successor": identical_evidence,
            "action-association-permutation": association_evidence,
            "label-permutation": permuted_evidence,
        }
        for path in CONTROL_ARTIFACT_PATHS:
            name = Path(path).stem
            files[path] = canonical_json_bytes(control_evidence[name])
    capacity_freeze_sha = _sha({
        "schema": "world-afterstate-v1-capacity-training-identity-v1",
        "source_git": expected_git,
        "p0_result_sha256": p0["result_sha256"],
        "subsplit_manifest_sha256": subsplit["manifest_sha256"],
    })
    config = _training_config()
    cohort_measurements = []
    worker_schedule = MEMBER_WORKER_COUNTS if p0["passed"] else ()
    for schedule_index, member_workers in enumerate(worker_schedule):
        torch_threads = max(1, cpu_count // member_workers)
        torch.set_num_threads(torch_threads)
        remaining_wall = _remaining_capacity_wall(started_wall)
        before = _cgroup_snapshot()
        phase_started = time.monotonic_ns()
        cohort = train_named_cohort(
            cohort_name="natural", values=joined,
            subsplit_manifest=subsplit,
            freeze_sha256=capacity_freeze_sha,
            shape_name=SHAPE_NAME,
            initialization_seeds=_initialization_seeds(),
            config=config, pair_cap=PAIR_CAP,
            schedule_seed=_schedule_seed(),
            wall_budget_nanoseconds=remaining_wall,
            member_workers=member_workers,
            progress=lambda value, w=member_workers: emit(
                "cohort-training", value["completed_units"],
                value["total_units"], member_workers=w,
                epoch=value["epoch"]))
        elapsed = time.monotonic_ns() - phase_started
        after = _cgroup_snapshot()
        resources = _phase_resources(before, after, elapsed, cpu_count)
        output_sha = _sha([
            row["selected_model_state_sha256"]
            for row in cohort.manifest["members"]])
        cohort_measurements.append({
            "schedule_index": schedule_index,
            "member_workers": member_workers,
            "torch_threads": torch_threads,
            "member_count": 8, "pair_count": len(joined),
            "member_pairs_per_second_ppm": (
                len(joined) * 8 * 10**15 // elapsed),
            "output_population_sha256": output_sha,
            **resources,
        })
        del cohort
        gc.collect()
        if time.monotonic_ns() - started_wall \
                > MAX_CAPACITY_WALL_NANOSECONDS:
            raise WorldAfterstateV1CapacityError(
                "capacity wall deadline expired")
    best_cohort = (max(
        cohort_measurements,
        key=lambda row: (row["member_pairs_per_second_ppm"],
                         -row["member_workers"]))
                   if cohort_measurements else None)
    aggregate_finish = _cgroup_snapshot()
    total_wall = time.monotonic_ns() - started_wall
    within_caps = (
        total_wall <= MAX_CAPACITY_WALL_NANOSECONDS
        and aggregate_finish["memory_peak_bytes"]
        <= CAPACITY_MEMORY_LIMIT_BYTES)
    if not within_caps:
        raise WorldAfterstateV1CapacityError(
            "capacity exceeded its wall or aggregate memory cap")
    body = {
        "schema": CAPACITY_SCHEMA,
        "source_git": expected_git,
        "source_tree_clean": True,
        "runtime": runtime,
        "source_bindings": source_bindings,
        "review": review,
        "v0_inputs": {
            "population_external_sha256": V0_POPULATION_EXTERNAL_SHA256,
            "population_manifest_sha256": V0_POPULATION_MANIFEST_SHA256,
            "dataset_external_sha256": V0_DATASET_EXTERNAL_SHA256,
            "dataset_manifest_sha256": V0_DATASET_MANIFEST_SHA256,
            "freeze_external_sha256": V0_FREEZE_EXTERNAL_SHA256,
            "freeze_sha256": V0_FREEZE_SHA256,
            "capacity_external_sha256": V0_CAPACITY_EXTERNAL_SHA256,
        },
        "schedule": {
            "row_worker_counts": list(ROW_WORKER_COUNTS),
            "row_repetitions": ROW_REPETITIONS,
            "member_worker_counts": list(MEMBER_WORKER_COUNTS),
            "pair_cap": PAIR_CAP, "shape_name": SHAPE_NAME,
            "bootstrap_replicates": BOOTSTRAP_REPLICATES,
            "capacity_config": config.payload(),
            "initialization_seeds": list(_initialization_seeds()),
            "schedule_seed": _schedule_seed(),
            "wall_cap_nanoseconds": MAX_CAPACITY_WALL_NANOSECONDS,
        },
        "train_population": {
            "train_row_count": len(rows),
            "eligible_state_count": pair_manifest["state_count"],
            "pair_count": pair_manifest["pair_count"],
            "fit_state_count": subsplit["fit_state_count"],
            "select_state_count": subsplit["select_state_count"],
            "train_row_population_sha256": expected_population_sha,
            "advantage_manifest_sha256": pair_manifest["manifest_sha256"],
            "subsplit_manifest_sha256": subsplit["manifest_sha256"],
            "label_ceiling_result_sha256": p0["result_sha256"],
            "label_ceiling_passed": p0["passed"],
            "calibration_row_bytes_opened": False,
            "report_row_bytes_opened": False,
            "provider_audit_row_bytes_opened": False,
        },
        "row_reopen_measurements": row_measurements,
        "cohort_measurements": cohort_measurements,
        "selection": {
            "row_workers": selected_row_workers,
            "member_workers": (
                best_cohort["member_workers"] if best_cohort else None),
            "torch_threads": (
                best_cohort["torch_threads"] if best_cohort else None),
            "selection_uses_outcomes_or_model_quality": False,
        },
        "terminal_route": (
            "PASS_TO_P1_CAPACITY" if p0["passed"]
            else "STOP_NO_REPRODUCIBLE_ACTION_LABEL"),
        "aggregate_resources": {
            "method": aggregate_finish["method"],
            "path": aggregate_finish["path"],
            "started_memory_current_bytes": aggregate_start[
                "memory_current_bytes"],
            "started_memory_peak_bytes": aggregate_start[
                "memory_peak_bytes"],
            "finished_memory_current_bytes": aggregate_finish[
                "memory_current_bytes"],
            "finished_memory_peak_bytes": aggregate_finish[
                "memory_peak_bytes"],
            "started_cpu_usage_nanoseconds": aggregate_start[
                "cpu_usage_nanoseconds"],
            "finished_cpu_usage_nanoseconds": aggregate_finish[
                "cpu_usage_nanoseconds"],
            "wall_nanoseconds": total_wall,
            "memory_limit_bytes": CAPACITY_MEMORY_LIMIT_BYTES,
            "within_wall_and_memory_caps": True,
        },
        "artifacts": _artifact_rows(files),
        "authority": dict(AUTHORITY),
    }
    receipt = {**body, "receipt_sha256": _sha(body)}
    result = CapacityBuildV1(
        receipt=receipt,
        files=tuple((path, files[path]) for path in files))
    return reopen_capacity_build(result)


def _write_once(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(path, 0o400)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def publish_capacity_build(target: Path, build: CapacityBuildV1) -> None:
    reopened = reopen_capacity_build(build)
    if not isinstance(target, Path):
        raise WorldAfterstateV1CapacityError(
            "capacity publication path drift")
    target = target.resolve()
    partial = target.with_name(f".{target.name}.partial")
    if target.exists() or target.is_symlink() \
            or partial.exists() or partial.is_symlink():
        raise WorldAfterstateV1CapacityError(
            "capacity publication namespace occupied")
    partial.mkdir(mode=0o700, parents=True)
    try:
        _write_once(
            partial / "receipt.json",
            canonical_json_bytes(reopened.receipt))
        for relative, raw in reopened.files:
            _write_once(partial / relative, raw)
        for directory in sorted(
                {path.parent for path in partial.rglob("*") if path.is_file()},
                key=lambda value: len(value.parts), reverse=True):
            _fsync_directory(directory)
        _fsync_directory(partial)
        os.rename(partial, target)
        os.chmod(target, 0o500)
        _fsync_directory(target.parent)
    except BaseException:
        raise


def reopen_capacity_directory(root: Path) -> CapacityBuildV1:
    if not isinstance(root, Path) or not root.is_dir() or root.is_symlink():
        raise WorldAfterstateV1CapacityError(
            "capacity directory identity drift")
    receipt = _canonical(
        _sealed_read(root / "receipt.json", "capacity receipt"),
        "capacity receipt")
    validate_capacity_receipt(receipt)
    artifact_paths = tuple(
        row["relative_path"] for row in receipt["artifacts"])
    expected = {"receipt.json", *artifact_paths}
    observed = {path.relative_to(root).as_posix()
                for path in root.rglob("*") if path.is_file()}
    if observed != expected:
        raise WorldAfterstateV1CapacityError(
            "capacity directory file population drift")
    files = tuple((path, _sealed_read(root / path, f"capacity {path}"))
                  for path in artifact_paths)
    return reopen_capacity_build(CapacityBuildV1(
        receipt=receipt, files=files))


__all__ = [
    "ARTIFACT_PATHS", "AUTHORITY", "CAPACITY_SCHEMA",
    "CapacityBuildV1", "WorldAfterstateV1CapacityError",
    "authenticate_review_commit", "expected_review_claim",
    "publish_capacity_build", "reopen_capacity_build",
    "reopen_capacity_directory", "run_capacity",
    "validate_capacity_receipt",
]
