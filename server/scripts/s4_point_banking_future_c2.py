#!/usr/bin/env python3
"""C2 runtime profile for the reviewed future S4 experiment.

The C1 runtime already owns the game loop, exact-work accounting, shard
validation, aggregation, and automatic two-look transition.  C2 changes only
the reviewed execution profile: a fresh population and 16 physical shards.
This adapter loads C1 in an isolated module, so importing C2 cannot mutate the
closed C1 protocol in the same interpreter.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve()
BASE_RUNNER = SCRIPT.with_name("s4_point_banking_future.py")
BASE_CONTROLLER = SCRIPT.with_name("s4_point_banking_future_cloud.py")
RUNNER_PATH = Path("server/scripts/s4_point_banking_future_c2.py")
CONTROLLER_PATH = Path("server/scripts/s4_point_banking_future_cloud_c2.py")
FAILED_RUN_ID = "s4-point-banking-future-c2-300b-v1"
RUN_ID = "s4-point-banking-future-c2-300b-recovery-v1"
FAILED_GIT = "6c247b9ec2faa1e3f525adcc7a6803c87afef71a"
FAILED_PACKET_SHA256 = (
    "83cadbfa4ae5afded36570b38d63d4f4a9e1e8d56580884d00ed8d23805cb205")
FAILED_ADMISSION_SHA256 = (
    "554d9fd10bee4c23b34269c2576b42eac9594343f3375e26bd34a9d20fe15daa")
FAILED_RECEIPT_SHA256 = (
    "97e0b7ff21adc31dcf63481b66811a251667a789a5c33d0953206c8227b56f9c")
FAILED_SUPERVISOR_PARTIAL_SHA256 = (
    "a17dfb147c16b4959b6e058f0a2af74392981dac266b08f113628029af288c46")
FAILED_CHILD_LOG_SHA256 = (
    "aaf7cb2f2f629eece3f04b28f1352e15dfcb71677343b27e3a4ff8c7fddd5b71")
FAILED_EXIT_MANIFEST_SHA256 = (
    "3038d7d97fe78ddc2bad2aa334ac9eec5cede3bbe34f73d09424a06bdccd9a53")

import s4_point_banking_future_design as C1_DESIGN  # noqa: E402
import s4_point_banking_future_cloud_c2_design as C2_DESIGN  # noqa: E402


class RuntimeDesign(C2_DESIGN.Design):
    """Expose C1's immutable Look objects without changing reviewed C2 bytes."""

    @property
    def looks(self) -> tuple[C1_DESIGN.Look, ...]:
        return tuple(
            C1_DESIGN.Look(clusters, alpha)
            for clusters, alpha in zip(
                self.look_clusters, self.look_alphas, strict=True)
        )


class _RuntimeDesignModule:
    """Read C2 authority first and inherit unchanged scientific primitives."""

    __file__ = C2_DESIGN.__file__
    Design = RuntimeDesign

    def __getattr__(self, name: str):
        if hasattr(C2_DESIGN, name):
            return getattr(C2_DESIGN, name)
        return getattr(C1_DESIGN, name)


DESIGN = _RuntimeDesignModule()


def _load_base_runtime():
    spec = importlib.util.spec_from_file_location(
        "_s4_point_banking_future_c2_base", BASE_RUNNER)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load the S4 C1 runtime")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_CORE = _load_base_runtime()

# Rebind every import-time-derived protocol field.  Functions in the isolated
# base module resolve these globals at call time; the ordinary C1 module in
# sys.modules is never touched.
_CORE.SCRIPT = SCRIPT
_CORE.DESIGN = DESIGN
_CORE.SCHEMA = "s4-point-banking-future-c2-recovery-shard-v1"
_CORE.AGGREGATE_SCHEMA = (
    "s4-point-banking-future-c2-recovery-aggregate-v1")
_CORE.VALIDATION_SCHEMA = (
    "s4-point-banking-future-c2-recovery-runtime-validation-v1")
_CORE.PACKET_SCHEMA = (
    "s4-point-banking-future-c2-recovery-cloud-packet-v1")
_CORE.PACKET_REVIEW_SCHEMA = (
    "s4-point-banking-future-c2-recovery-cloud-packet-review-v1")
_CORE.PACKET_REVIEW_MARKER = (
    "S4_POINT_BANKING_FUTURE_C2_RECOVERY_PACKET_V1_REVIEW ")
_CORE.ADMISSION_SCHEMA = (
    "s4-point-banking-future-c2-recovery-cloud-admission-v1")
_CORE.RECEIPT_SCHEMA = (
    "s4-point-banking-future-c2-recovery-cloud-receipt-v1")
_CORE.DESIGN_REVIEW_GIT = (
    "f0c2a6de07b828535d17350c1c3206942175ad45")

_CORE.RUN_ID = RUN_ID
_CORE.NAMESPACE = Path("server/runs/logs") / _CORE.RUN_ID
_CORE.RUNNER_PATH = RUNNER_PATH
_CORE.CONTROLLER_PATH = CONTROLLER_PATH
_CORE.PREFLIGHT_RESULT_PATH = C2_DESIGN.CAPACITY_RESULT.relative_to(
    _CORE.REPO)
_CORE.PACKET_EXTRA_FIELDS = frozenset({
    "controller_implementation_review",
    "implementation_sources",
    "new_preflight_run",
    "recovery_source",
})
_CORE.DESIGN_REVIEW_EXTRA = {"implementation_authorized": True}
_CORE.SEED0 = C2_DESIGN.SCREEN_SEED0
_CORE.LOOK_CLUSTERS = C2_DESIGN.LOOK_CLUSTERS
_CORE.LOOK1_CLUSTERS, _CORE.MAX_CLUSTERS = _CORE.LOOK_CLUSTERS
_CORE.TRANCHE_COUNT = len(_CORE.LOOK_CLUSTERS)
_CORE.SHARD_COUNT = C2_DESIGN.SHARD_COUNT
_CORE.CLUSTERS_PER_SHARD = _CORE.MAX_CLUSTERS // _CORE.SHARD_COUNT
_CORE.TRANCHE_CLUSTERS_PER_SHARD = (
    _CORE.LOOK1_CLUSTERS // _CORE.SHARD_COUNT)
_CORE.NULL_SENTINEL_STRIDE = C2_DESIGN.NULL_SENTINEL_MODULUS
_CORE.NULL_SENTINEL_CLUSTERS = (
    _CORE.MAX_CLUSTERS // _CORE.NULL_SENTINEL_STRIDE)
_CORE.SHARD_NAMES = tuple(
    f"tranche-{tranche}-shard-{index:02d}.json"
    for tranche in range(1, _CORE.TRANCHE_COUNT + 1)
    for index in range(_CORE.SHARD_COUNT)
)
_CORE.MAX_PROJECTED_FLEET_HOURS = C2_DESIGN.MAX_PROJECTED_FLEET_HOURS
_CORE.MAX_PROJECTED_SHARD_HOURS = C2_DESIGN.MAX_PROJECTED_SHARD_HOURS
_CORE.CLAIM_BOUNDARY = (
    "One recovery launch of the future-only, fresh-population, two-look "
    "complete-round confirmation of frozen S4 versus exact live report-LCB. "
    "The failed predecessor stopped at child receipt validation before "
    "gameplay and published no outcome, so the same frozen population is "
    "statistically untouched. The reviewed C1 score-free capacity measurement "
    "is reused only to size 16 physical shards. Matched null is an identity "
    "sentinel. No retry of the failed namespace, resize, promotion, deployment, "
    "or discretionary continuation."
)
_CORE.DESIGN_RECORD = json.loads(json.dumps(
    C2_DESIGN.design_record(), sort_keys=True, separators=(",", ":")))
_CORE.DESIGN_RECORD["run_id"] = RUN_ID
_CORE.DESIGN_RECORD["recovery_contract"] = {
    "failed_run_id": FAILED_RUN_ID,
    "failure_stage": "child-receipt-validation-before-gameplay",
    "failed_outcomes_published": False,
    "same_frozen_population_reused": True,
    "fresh_namespace_required": True,
}
_CORE.SELECTION_RULE = C1_DESIGN.PRIMARY_EFFICACY
_CORE.LOOK1_TRANSITION = _CORE.DESIGN_RECORD["look_1_transition"]
_CORE.FINAL_TRANSITION = _CORE.DESIGN_RECORD["final_transition"]


def recovery_source_record() -> dict:
    return {
        "schema": "s4-point-banking-future-c2-failed-launch-v1",
        "failed_run_id": FAILED_RUN_ID,
        "failed_git": FAILED_GIT,
        "failed_packet_sha256": FAILED_PACKET_SHA256,
        "failed_admission_sha256": FAILED_ADMISSION_SHA256,
        "failed_receipt_sha256": FAILED_RECEIPT_SHA256,
        "failed_supervisor_partial_sha256": FAILED_SUPERVISOR_PARTIAL_SHA256,
        "failed_child_count": 16,
        "failed_child_returncode": 3,
        "failed_child_log_sha256": FAILED_CHILD_LOG_SHA256,
        "failed_exit_manifest_sha256": FAILED_EXIT_MANIFEST_SHA256,
        "shard_outputs_published": 0,
        "aggregates_published": 0,
        "outcomes_published": False,
        "failure_stage": "child-receipt-validation-before-gameplay",
        "old_namespace_retry_authorized": False,
        "same_frozen_population_statistically_unopened": True,
    }


def packet_profile_problems(packet: dict, *, expected_git: str,
                            receipt: dict,
                            current_runtime: dict) -> list[str]:
    """Reopen C2-only packet fields at the child boundary."""
    expected_sources = {
        "base_runner_sha256": _CORE.sha256(BASE_RUNNER),
        "base_controller_sha256": _CORE.sha256(BASE_CONTROLLER),
    }
    expected_review = {
        "schema": "s4-point-banking-future-c2-recovery-controller-review-v1",
        "git": expected_git,
        "runner_sha256": _CORE.sha256(SCRIPT),
        "controller_sha256": receipt["controller_sha256"],
        **expected_sources,
        "design_git": _CORE.DESIGN_REVIEW_GIT,
        "design_sha256": _CORE.sha256(Path(C2_DESIGN.__file__)),
        "capacity_result_sha256": C2_DESIGN.CAPACITY_RESULT_SHA256,
        "capacity_admission_sha256": C2_DESIGN.CAPACITY_ADMISSION_SHA256,
        "expected_host": current_runtime.get("host"),
        "expected_python": current_runtime.get("python"),
        "expected_fast_binary_sha256": current_runtime.get(
            "fast_binary_sha256"),
        "sixteen_shard_contract_verified": True,
        "reused_score_free_capacity_verified": True,
        "failed_launch": recovery_source_record(),
        "fresh_recovery_namespace": RUN_ID,
        "child_boundary_validation_required": True,
        "new_preflight_authorized": False,
        "packet_freeze_authorized": True,
        "sequential_execution_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
        "verdict": "PASS",
    }
    problems = []
    if packet.get("implementation_sources") != expected_sources:
        problems.append("C2 implementation source drift")
    if packet.get("controller_implementation_review") != expected_review:
        problems.append("C2 controller implementation review drift")
    if packet.get("new_preflight_run") is not False:
        problems.append("C2 packet authorizes a new preflight")
    if packet.get("recovery_source") != recovery_source_record():
        problems.append("C2 failed-launch recovery source drift")
    return problems


_CORE.packet_profile_problems = packet_profile_problems


_base_require_runtime = _CORE.require_runtime


def require_runtime(expected_git: str) -> tuple[dict, dict]:
    """Pin the reused C1 implementation as well as this small C2 adapter."""
    parent, runtime = _base_require_runtime(expected_git)
    return parent, {
        **runtime,
        "future_profile": "cloud-c2-16-shard-v1",
        "future_base_runner_sha256": _CORE.sha256(BASE_RUNNER),
    }


_CORE.require_runtime = require_runtime


def __getattr__(name: str):
    return getattr(_CORE, name)


def main(argv: list[str] | None = None) -> None:
    _CORE.main(argv)


if __name__ == "__main__":
    try:
        main()
    except (_CORE.ProtocolRefused, _CORE.DUEL.ProtocolRefused) as exc:
        print(f"REFUSING: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(3) from exc
