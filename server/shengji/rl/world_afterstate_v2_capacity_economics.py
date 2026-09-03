"""Retained-evidence capacity amendment for Value-Afterstate V2.

This module does not measure capacity or execute scientific work.  It reopens
the exact Census-11 refusal, proves that only the predeclared wall-economics
gates failed, and exposes the unchanged D256 resource layout under the openly
revised seven-hour / fourteen-hour contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Mapping, Sequence

from .belief_contract import canonical_json_bytes
from .world_afterstate_v2_capacity import (
    ARM_GRIDS, AUTHORITY, CAPACITY_HOST_LOGICAL_CPUS, MEMORY_LIMIT_BYTES,
    ZERO_SWAP_BYTES,
)
from .world_afterstate_v2_protocol import (
    COMPLETE_DAG_WALL_SECONDS_MAX, LABEL_CPU_SECONDS_MAX,
    LABEL_WALL_SECONDS_MAX, SCIENTIFIC_SERVICE_SECONDS, TIER_SPECS,
    CapacityTierReceiptV2,
)


AMENDMENT_SCHEMA = "world-afterstate-v2-capacity-economics-amendment-v1"
SELECTED_ARM_SCHEMA = "world-afterstate-v2-capacity-economics-arm-v1"
SOURCE_DIFF_SCHEMA = "world-afterstate-v2-capacity-economics-source-diff-v1"
BASE_SOURCE_GIT = "8ff9c79cd294770b51127ec7a844694784b7d0bc"
BASE_FAILURE_EXTERNAL_SHA256 = (
    "06019851ec4a2aecdc8541d623a02e9d8355c3d68d69c9fe29572a3d0d5be14d")
BASE_FAILURE_RECEIPT_SHA256 = (
    "3a059e3de3c506117bac71611acf20ec3e2fbfdeb3c64e1baadd8d145db5a8b7")
BASE_FAILURE_SOURCE_SHA256 = (
    "53932edb01fabe8f9a3a93d962c34f589e2fe4dcfac1e90a6a6787fb155be6f7")
LEGACY_COMPLETE_DAG_WALL_SECONDS_MAX = 6 * 60 * 60
LEGACY_SCIENTIFIC_SERVICE_SECONDS = 12 * 60 * 60
RETAINED_D256_WALL_SECONDS = 23_065
INHERITED_VIOLATIONS = (
    "complete-dag-wall", "two-for-one-service-wall")
LABEL_STAGES = (
    "label-p0", "label-fit", "label-precision-select", "label-audit")

# The carry-forward head may change only resource economics, typed reopening,
# execution admission, tests, and the reviewed design.  In particular, no
# model, optimizer, label, continuation, population, DAG, worker topology, or
# inference implementation is in this closed set.
ALLOWED_CARRY_FORWARD_PATHS = frozenset({
    "VALUE_AFTERSTATE_V2_ABSOLUTE_LEAF_DESIGN.md",
    "server/scripts/build_world_afterstate_v2_freeze.py",
    "server/scripts/world_afterstate_v2_capacity_economics.py",
    "server/shengji/rl/world_afterstate_v2_capacity_economics.py",
    "server/shengji/rl/world_afterstate_v2_execution.py",
    "server/shengji/rl/world_afterstate_v2_freeze_inputs.py",
    "server/shengji/rl/world_afterstate_v2_late_stage_adapters.py",
    "server/shengji/rl/world_afterstate_v2_protocol.py",
    "server/shengji/rl/world_afterstate_v2_terminal_controller.py",
    "server/shengji/rl/world_afterstate_v2_training_stage_inputs.py",
    "server/tests/fixtures/world_afterstate_v2_capacity_census11_failure.json",
    "server/tests/test_world_afterstate_v2_capacity.py",
    "server/tests/test_world_afterstate_v2_capacity_economics.py",
    "server/tests/test_world_afterstate_v2_freeze_builder.py",
    "server/tests/test_world_afterstate_v2_protocol.py",
})


class CapacityEconomicsError(ValueError):
    """The retained evidence or economics amendment did not authenticate."""


def _sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha(value: object) -> str:
    return _sha_bytes(canonical_json_bytes(value))


def _digest(value: object, label: str, *, length: int = 64) -> str:
    if (type(value) is not str or len(value) != length
            or any(char not in "0123456789abcdef" for char in value)):
        raise CapacityEconomicsError(f"{label} drift")
    return value


def _positive(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise CapacityEconomicsError(f"{label} drift")
    return value


def _canonical_object(raw: bytes, label: str) -> dict[str, Any]:
    if type(raw) is not bytes or not raw:
        raise CapacityEconomicsError(f"{label} bytes drift")
    try:
        value = json.loads(raw.decode("ascii"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise CapacityEconomicsError(f"{label} is not JSON") from exc
    if type(value) is not dict or canonical_json_bytes(value) != raw:
        raise CapacityEconomicsError(f"{label} is not canonical JSON")
    return value


def _longest_path_seconds(
        walls: Mapping[str, int], edges: Sequence[tuple[str, str]]) -> int:
    parents = {name: [] for name in walls}
    for before, after in edges:
        if before not in walls or after not in walls or before == after:
            raise CapacityEconomicsError("retained DAG edge drift")
        parents[after].append(before)
    visiting: set[str] = set()
    memo: dict[str, int] = {}

    def visit(name: str) -> int:
        if name in memo:
            return memo[name]
        if name in visiting:
            raise CapacityEconomicsError("retained DAG cycle drift")
        visiting.add(name)
        result = walls[name] + max(
            (visit(parent) for parent in parents[name]), default=0)
        visiting.remove(name)
        memo[name] = result
        return result

    return max(visit(name) for name in walls)


def _legacy_failure(raw: bytes) -> dict[str, Any]:
    """Strictly reopen the old-cap refusal without applying the new caps."""
    if _sha_bytes(raw) != BASE_FAILURE_EXTERNAL_SHA256:
        raise CapacityEconomicsError("base capacity failure bytes drift")
    value = _canonical_object(raw, "base capacity failure")
    required = {
        "schema", "status", "stage", "reason", "source_sha256",
        "input_sha256", "runtime_sha256", "namespace_sha256",
        "detail_sha256", "elapsed_seconds", "deadline_seconds",
        "detail_message", "assessments", "projection_diagnostic",
        "authority", "failure_receipt_sha256",
    }
    if (set(value) != required
            or value["schema"]
            != "world-afterstate-v2-post-implementation-capacity-failure-v6"
            or value["status"] != "failure" or value["stage"] != "full-dag"
            or value["reason"] != "composed-projection-cap-drift"
            or value["source_sha256"] != BASE_FAILURE_SOURCE_SHA256
            or value["authority"] != AUTHORITY
            or value["deadline_seconds"] != 2 * 60 * 60):
        raise CapacityEconomicsError("base capacity failure identity drift")
    body = {key: item for key, item in value.items()
            if key != "failure_receipt_sha256"}
    if (value["failure_receipt_sha256"] != _sha(body)
            or value["failure_receipt_sha256"]
            != BASE_FAILURE_RECEIPT_SHA256):
        raise CapacityEconomicsError("base capacity failure reconstruction drift")
    assessments = value["assessments"]
    if type(assessments) is not list or len(assessments) != len(ARM_GRIDS):
        raise CapacityEconomicsError("base capacity assessment drift")
    for category, row in zip(ARM_GRIDS, assessments, strict=True):
        if (type(row) is not dict or row.get("category") != category
                or row.get("violates_gate") is not False
                or row.get("selected_variant") not in ARM_GRIDS[category]):
            raise CapacityEconomicsError("base capacity assessment drift")
    diagnostic = value["projection_diagnostic"]
    required_diagnostic = {
        "schema", "stage_walls_seconds", "stage_cpu_seconds",
        "stage_unit_counts", "measured_stage_wall_nanoseconds",
        "measured_stage_cpu_nanoseconds", "composed_wall_seconds",
        "complete_dag_wall_seconds_max", "scientific_service_seconds",
        "peak_memory_bytes", "memory_limit_bytes",
        "composed_artifact_bytes", "free_disk_bytes_before",
        "disk_retain_percent_min", "cohort_workers", "dag_edges",
        "violations",
    }
    if (type(diagnostic) is not dict or set(diagnostic) != required_diagnostic
            or diagnostic["schema"]
            != "world-afterstate-v2-capacity-rejected-projection-v3"
            or diagnostic["complete_dag_wall_seconds_max"]
            != LEGACY_COMPLETE_DAG_WALL_SECONDS_MAX
            or diagnostic["scientific_service_seconds"]
            != LEGACY_SCIENTIFIC_SERVICE_SECONDS
            or diagnostic["composed_wall_seconds"]
            != RETAINED_D256_WALL_SECONDS
            or tuple(diagnostic["violations"]) != INHERITED_VIOLATIONS
            or diagnostic["cohort_workers"] != 2
            or diagnostic["memory_limit_bytes"] != MEMORY_LIMIT_BYTES):
        raise CapacityEconomicsError("base capacity projection identity drift")
    rows = {}
    for key in (
            "stage_walls_seconds", "stage_cpu_seconds",
            "measured_stage_wall_nanoseconds",
            "measured_stage_cpu_nanoseconds"):
        supplied = diagnostic[key]
        if (type(supplied) is not list or not supplied
                or any(type(row) is not list or len(row) != 2
                       or type(row[0]) is not str
                       or isinstance(row[1], bool) or not isinstance(row[1], int)
                       or row[1] < 1 for row in supplied)
                or len({row[0] for row in supplied}) != len(supplied)):
            raise CapacityEconomicsError(f"base capacity {key} drift")
        rows[key] = dict(supplied)
    unit_rows = diagnostic["stage_unit_counts"]
    if (type(unit_rows) is not list or not unit_rows
            or any(type(row) is not list or len(row) != 3
                   or type(row[0]) is not str
                   or any(isinstance(value, bool) or not isinstance(value, int)
                          or value < 1 for value in row[1:])
                   for row in unit_rows)
            or len({row[0] for row in unit_rows}) != len(unit_rows)):
        raise CapacityEconomicsError(
            "base capacity stage_unit_counts drift")
    if set(rows["stage_walls_seconds"]) != set(rows["stage_cpu_seconds"]) \
            or set(rows["stage_walls_seconds"]) \
            != {row[0] for row in unit_rows} \
            or set(rows["stage_walls_seconds"]) \
            != set(rows["measured_stage_wall_nanoseconds"]) \
            or set(rows["stage_walls_seconds"]) \
            != set(rows["measured_stage_cpu_nanoseconds"]):
        raise CapacityEconomicsError("base capacity retained stage grid drift")
    edges = tuple(tuple(row) for row in diagnostic["dag_edges"])
    if (_longest_path_seconds(rows["stage_walls_seconds"], edges)
            != RETAINED_D256_WALL_SECONDS):
        raise CapacityEconomicsError("base capacity retained wall drift")
    _digest(value["runtime_sha256"], "base capacity runtime")
    for key in ("peak_memory_bytes", "composed_artifact_bytes",
                "free_disk_bytes_before"):
        _positive(diagnostic[key], f"base capacity {key}")
    return value


@dataclass(frozen=True)
class SourceDiffV2:
    path: str
    status: str
    base_sha256: str | None
    current_sha256: str
    schema: str = SOURCE_DIFF_SCHEMA

    def validate(self) -> None:
        if (self.schema != SOURCE_DIFF_SCHEMA
                or self.path not in ALLOWED_CARRY_FORWARD_PATHS
                or self.status not in ("A", "M")
                or self.status == "A" and self.base_sha256 is not None
                or self.status == "M" and self.base_sha256 is None):
            raise CapacityEconomicsError("carry-forward source diff drift")
        if self.base_sha256 is not None:
            _digest(self.base_sha256, "carry-forward base source")
        _digest(self.current_sha256, "carry-forward current source")
        if self.base_sha256 == self.current_sha256:
            raise CapacityEconomicsError("carry-forward source diff is unchanged")

    def payload(self) -> dict[str, Any]:
        self.validate()
        return {"schema": self.schema, "path": self.path,
                "status": self.status, "base_sha256": self.base_sha256,
                "current_sha256": self.current_sha256}

    @classmethod
    def reopen(cls, payload: Mapping[str, Any]) -> "SourceDiffV2":
        if type(payload) is not dict or set(payload) != {
                "schema", "path", "status", "base_sha256", "current_sha256"}:
            raise CapacityEconomicsError("carry-forward source diff schema drift")
        result = cls(**payload)
        result.validate()
        return result


@dataclass(frozen=True)
class SelectedArmEvidenceV2:
    stage: str
    variant: int
    evidence_sha256: str = BASE_FAILURE_RECEIPT_SHA256
    schema: str = SELECTED_ARM_SCHEMA

    def validate(self) -> None:
        if (self.schema != SELECTED_ARM_SCHEMA or self.stage not in ARM_GRIDS
                or self.variant not in ARM_GRIDS[self.stage]
                or self.evidence_sha256 != BASE_FAILURE_RECEIPT_SHA256):
            raise CapacityEconomicsError("retained selected arm drift")

    def payload(self) -> dict[str, Any]:
        self.validate()
        return {"schema": self.schema, "stage": self.stage,
                "variant": self.variant,
                "evidence_sha256": self.evidence_sha256}

    @classmethod
    def reopen(cls, payload: Mapping[str, Any]) -> "SelectedArmEvidenceV2":
        if type(payload) is not dict or set(payload) != {
                "schema", "stage", "variant", "evidence_sha256"}:
            raise CapacityEconomicsError("retained selected arm schema drift")
        result = cls(**payload)
        result.validate()
        return result


@dataclass(frozen=True)
class CapacityEconomicsAmendmentV2:
    base_failure_external_sha256: str
    base_failure_receipt_sha256: str
    base_source_git: str
    execution_git: str
    source_sha256: str
    runtime_sha256: str
    source_diff: tuple[SourceDiffV2, ...]
    selected_arms: tuple[SelectedArmEvidenceV2, ...]
    tiers: tuple[CapacityTierReceiptV2, ...]
    retained_stage_walls_seconds: tuple[tuple[str, int], ...]
    retained_stage_cpu_seconds: tuple[tuple[str, int], ...]
    retained_stage_unit_counts: tuple[tuple[str, int, int], ...]
    retained_dag_edges: tuple[tuple[str, str], ...]
    inherited_violations: tuple[str, ...]
    all_core_gate_passed: bool
    authority: Mapping[str, bool] = field(default_factory=lambda: dict(AUTHORITY))
    schema: str = AMENDMENT_SCHEMA

    @property
    def member_workers(self) -> int:
        return self._variant("member-concurrency")

    @property
    def continuation_workers(self) -> int:
        return self._variant("continuation-mechanics")

    @property
    def torch_threads(self) -> int:
        return 1

    @property
    def inference_batch(self) -> int:
        return self._variant("inference-batch")

    @property
    def reconstruction_workers(self) -> int:
        return self._variant("reconstruction")

    def _variant(self, stage: str) -> int:
        values = tuple(row.variant for row in self.selected_arms
                       if row.stage == stage)
        if len(values) != 1:
            raise CapacityEconomicsError("retained selected arm population drift")
        return values[0]

    def validate(self) -> None:
        if (self.schema != AMENDMENT_SCHEMA or self.authority != AUTHORITY
                or self.base_failure_external_sha256
                != BASE_FAILURE_EXTERNAL_SHA256
                or self.base_failure_receipt_sha256
                != BASE_FAILURE_RECEIPT_SHA256
                or self.base_source_git != BASE_SOURCE_GIT
                or self.inherited_violations != INHERITED_VIOLATIONS
                or self.all_core_gate_passed is not True):
            raise CapacityEconomicsError("capacity economics identity drift")
        _digest(self.execution_git, "capacity economics execution Git", length=40)
        _digest(self.source_sha256, "capacity economics source")
        _digest(self.runtime_sha256, "capacity economics runtime")
        expected_paths = tuple(sorted(ALLOWED_CARRY_FORWARD_PATHS))
        if (self.execution_git == self.base_source_git
                or type(self.source_diff) is not tuple
                or tuple(row.path for row in self.source_diff)
                != expected_paths):
            raise CapacityEconomicsError("carry-forward source diff population drift")
        for row in self.source_diff:
            row.validate()
        if (type(self.selected_arms) is not tuple
                or tuple(row.stage for row in self.selected_arms)
                != tuple(ARM_GRIDS)):
            raise CapacityEconomicsError("retained selected arm population drift")
        for row in self.selected_arms:
            row.validate()
        if type(self.tiers) is not tuple or len(self.tiers) != 1:
            raise CapacityEconomicsError("capacity economics tier population drift")
        tier = self.tiers[0]
        tier.validate()
        if (tier.tier != "D256" or tier.exact_source_supply is not True
                or tier.outcomes_opened is not False
                or tier.all_core_gate_passed is not True
                or tier.complete_dag_wall_seconds != RETAINED_D256_WALL_SECONDS
                or tier.service_wall_seconds != SCIENTIFIC_SERVICE_SECONDS
                or not tier.eligible):
            raise CapacityEconomicsError("capacity economics D256 drift")
        for label, rows in (
                ("stage wall", self.retained_stage_walls_seconds),
                ("stage CPU", self.retained_stage_cpu_seconds),
                ("stage units", self.retained_stage_unit_counts)):
            if (type(rows) is not tuple or not rows
                    or any(type(row) is not tuple
                           or len(row) != (3 if label == "stage units" else 2)
                           or type(row[0]) is not str
                           or any(isinstance(value, bool)
                                  or not isinstance(value, int) or value < 1
                                  for value in row[1:])
                           for row in rows)
                    or len({row[0] for row in rows}) != len(rows)):
                raise CapacityEconomicsError(
                    f"capacity economics retained {label} drift")
        wall_map = dict(self.retained_stage_walls_seconds)
        if (set(wall_map) != set(dict(self.retained_stage_cpu_seconds))
                or set(wall_map)
                != {row[0] for row in self.retained_stage_unit_counts}
                or _longest_path_seconds(wall_map, self.retained_dag_edges)
                != RETAINED_D256_WALL_SECONDS
                or sum(wall_map[name] for name in LABEL_STAGES)
                != tier.label_wall_seconds
                or sum(dict(self.retained_stage_cpu_seconds)[name]
                       for name in LABEL_STAGES) != tier.label_cpu_seconds):
            raise CapacityEconomicsError("capacity economics retained DAG drift")

    def choose_tier(self):
        self.validate()
        return TIER_SPECS[0]

    def payload(self) -> dict[str, Any]:
        self.validate()
        body = {
            "schema": self.schema,
            "base_failure_external_sha256": self.base_failure_external_sha256,
            "base_failure_receipt_sha256": self.base_failure_receipt_sha256,
            "base_source_git": self.base_source_git,
            "execution_git": self.execution_git,
            "source_sha256": self.source_sha256,
            "runtime_sha256": self.runtime_sha256,
            "source_diff": [row.payload() for row in self.source_diff],
            "selected_arms": [row.payload() for row in self.selected_arms],
            "tiers": [tier.__dict__ for tier in self.tiers],
            "retained_stage_walls_seconds": [
                list(row) for row in self.retained_stage_walls_seconds],
            "retained_stage_cpu_seconds": [
                list(row) for row in self.retained_stage_cpu_seconds],
            "retained_stage_unit_counts": [
                list(row) for row in self.retained_stage_unit_counts],
            "retained_dag_edges": [list(row) for row in self.retained_dag_edges],
            "legacy_complete_dag_wall_seconds_max":
                LEGACY_COMPLETE_DAG_WALL_SECONDS_MAX,
            "legacy_scientific_service_seconds":
                LEGACY_SCIENTIFIC_SERVICE_SECONDS,
            "amended_complete_dag_wall_seconds_max":
                COMPLETE_DAG_WALL_SECONDS_MAX,
            "amended_scientific_service_seconds":
                SCIENTIFIC_SERVICE_SECONDS,
            "inherited_violations": list(self.inherited_violations),
            "all_core_gate_passed": self.all_core_gate_passed,
            "authority": dict(self.authority),
        }
        return {**body, "capacity_economics_sha256": _sha(body)}


def build_capacity_economics_amendment_v2(
        *, base_failure_raw: bytes, execution_git: str, source_sha256: str,
        source_diff: Sequence[SourceDiffV2]) -> CapacityEconomicsAmendmentV2:
    base = _legacy_failure(base_failure_raw)
    diagnostic = base["projection_diagnostic"]
    walls = tuple(tuple(row) for row in diagnostic["stage_walls_seconds"])
    cpu = tuple(tuple(row) for row in diagnostic["stage_cpu_seconds"])
    units = tuple(tuple(row) for row in diagnostic["stage_unit_counts"])
    edges = tuple(tuple(row) for row in diagnostic["dag_edges"])
    wall_map, cpu_map = dict(walls), dict(cpu)
    selected = tuple(SelectedArmEvidenceV2(
        stage=row["category"], variant=row["selected_variant"])
        for row in base["assessments"])
    tier = CapacityTierReceiptV2(
        tier="D256", host_logical_cpus=CAPACITY_HOST_LOGICAL_CPUS,
        exact_source_supply=True, byte_identical=True, outcomes_opened=False,
        all_core_gate_passed=True,
        label_wall_seconds=sum(wall_map[name] for name in LABEL_STAGES),
        label_cpu_seconds=sum(cpu_map[name] for name in LABEL_STAGES),
        complete_dag_wall_seconds=diagnostic["composed_wall_seconds"],
        service_wall_seconds=SCIENTIFIC_SERVICE_SECONDS,
        peak_memory_bytes=diagnostic["peak_memory_bytes"],
        memory_limit_bytes=diagnostic["memory_limit_bytes"],
        composed_artifact_bytes=diagnostic["composed_artifact_bytes"],
        free_disk_bytes_before=diagnostic["free_disk_bytes_before"])
    if (tier.label_wall_seconds > LABEL_WALL_SECONDS_MAX
            or tier.label_cpu_seconds > LABEL_CPU_SECONDS_MAX):
        raise CapacityEconomicsError("capacity economics inherited label cap drift")
    result = CapacityEconomicsAmendmentV2(
        base_failure_external_sha256=BASE_FAILURE_EXTERNAL_SHA256,
        base_failure_receipt_sha256=BASE_FAILURE_RECEIPT_SHA256,
        base_source_git=BASE_SOURCE_GIT, execution_git=execution_git,
        source_sha256=source_sha256, runtime_sha256=base["runtime_sha256"],
        source_diff=tuple(source_diff), selected_arms=selected, tiers=(tier,),
        retained_stage_walls_seconds=walls,
        retained_stage_cpu_seconds=cpu,
        retained_stage_unit_counts=units, retained_dag_edges=edges,
        inherited_violations=INHERITED_VIOLATIONS,
        all_core_gate_passed=True)
    result.validate()
    return result


def reopen_capacity_economics_amendment_v2(
        payload: Mapping[str, Any]) -> CapacityEconomicsAmendmentV2:
    required = {
        "schema", "base_failure_external_sha256",
        "base_failure_receipt_sha256", "base_source_git", "execution_git",
        "source_sha256", "runtime_sha256", "source_diff", "selected_arms",
        "tiers", "retained_stage_walls_seconds",
        "retained_stage_cpu_seconds", "retained_stage_unit_counts",
        "retained_dag_edges", "legacy_complete_dag_wall_seconds_max",
        "legacy_scientific_service_seconds",
        "amended_complete_dag_wall_seconds_max",
        "amended_scientific_service_seconds", "inherited_violations",
        "all_core_gate_passed", "authority", "capacity_economics_sha256",
    }
    if (type(payload) is not dict or set(payload) != required
            or payload["schema"] != AMENDMENT_SCHEMA
            or payload["legacy_complete_dag_wall_seconds_max"]
            != LEGACY_COMPLETE_DAG_WALL_SECONDS_MAX
            or payload["legacy_scientific_service_seconds"]
            != LEGACY_SCIENTIFIC_SERVICE_SECONDS
            or payload["amended_complete_dag_wall_seconds_max"]
            != COMPLETE_DAG_WALL_SECONDS_MAX
            or payload["amended_scientific_service_seconds"]
            != SCIENTIFIC_SERVICE_SECONDS):
        raise CapacityEconomicsError("capacity economics schema drift")
    body = {key: value for key, value in payload.items()
            if key != "capacity_economics_sha256"}
    if payload["capacity_economics_sha256"] != _sha(body):
        raise CapacityEconomicsError("capacity economics reconstruction drift")
    result = CapacityEconomicsAmendmentV2(
        base_failure_external_sha256=payload[
            "base_failure_external_sha256"],
        base_failure_receipt_sha256=payload[
            "base_failure_receipt_sha256"],
        base_source_git=payload["base_source_git"],
        execution_git=payload["execution_git"],
        source_sha256=payload["source_sha256"],
        runtime_sha256=payload["runtime_sha256"],
        source_diff=tuple(SourceDiffV2.reopen(row)
                          for row in payload["source_diff"]),
        selected_arms=tuple(SelectedArmEvidenceV2.reopen(row)
                            for row in payload["selected_arms"]),
        tiers=tuple(CapacityTierReceiptV2(**row) for row in payload["tiers"]),
        retained_stage_walls_seconds=tuple(
            tuple(row) for row in payload["retained_stage_walls_seconds"]),
        retained_stage_cpu_seconds=tuple(
            tuple(row) for row in payload["retained_stage_cpu_seconds"]),
        retained_stage_unit_counts=tuple(
            tuple(row) for row in payload["retained_stage_unit_counts"]),
        retained_dag_edges=tuple(
            tuple(row) for row in payload["retained_dag_edges"]),
        inherited_violations=tuple(payload["inherited_violations"]),
        all_core_gate_passed=payload["all_core_gate_passed"],
        authority=payload["authority"], schema=payload["schema"])
    result.validate()
    if result.payload() != payload:
        raise CapacityEconomicsError("capacity economics canonical drift")
    return result


def reopen_capacity_economics_amendment_v2_bytes(
        raw: bytes) -> CapacityEconomicsAmendmentV2:
    return reopen_capacity_economics_amendment_v2(
        _canonical_object(raw, "capacity economics amendment"))


def reopen_capacity_evidence_v2_bytes(raw: bytes):
    """Reopen a current capacity amendment or a current measured receipt."""
    payload = _canonical_object(raw, "capacity evidence")
    if payload.get("schema") == AMENDMENT_SCHEMA:
        return reopen_capacity_economics_amendment_v2(payload)
    from .world_afterstate_v2_capacity_runner import reopen_capacity_receipt_v2
    return reopen_capacity_receipt_v2(payload)


def publish_capacity_economics_amendment_v2(
        path: Path | str, receipt: CapacityEconomicsAmendmentV2) -> None:
    target = Path(path)
    if target.exists() or target.is_symlink():
        raise CapacityEconomicsError("capacity economics output already exists")
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.parent / f".{target.name}.partial"
    if partial.exists() or partial.is_symlink():
        raise CapacityEconomicsError("capacity economics partial already exists")
    raw = canonical_json_bytes(receipt.payload())
    with partial.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    partial.chmod(0o400)
    partial.replace(target)
    directory = os.open(target.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


__all__ = [
    "ALLOWED_CARRY_FORWARD_PATHS", "AMENDMENT_SCHEMA", "BASE_SOURCE_GIT",
    "CapacityEconomicsAmendmentV2", "CapacityEconomicsError",
    "SelectedArmEvidenceV2", "SourceDiffV2",
    "build_capacity_economics_amendment_v2",
    "publish_capacity_economics_amendment_v2",
    "reopen_capacity_economics_amendment_v2",
    "reopen_capacity_economics_amendment_v2_bytes",
    "reopen_capacity_evidence_v2_bytes",
]
