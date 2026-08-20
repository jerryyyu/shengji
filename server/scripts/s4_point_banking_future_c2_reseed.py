#!/usr/bin/env python3
"""Runtime profile for the fresh 360B S4 C2 replacement population.

The reviewed C2 science, work, and two-look transition remain unchanged.  This
adapter changes only the fully retired 300B population/namespace to the
independently reviewed 360B replacement.  It loads the C1 runtime in isolation
so neither the closed C1 nor retired C2 protocol is mutated by import.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve()
BASE_RUNNER = SCRIPT.with_name("s4_point_banking_future.py")
BASE_CONTROLLER = SCRIPT.with_name("s4_point_banking_future_cloud.py")
RUNNER_PATH = Path("server/scripts/s4_point_banking_future_c2_reseed.py")
CONTROLLER_PATH = Path(
    "server/scripts/s4_point_banking_future_cloud_c2_reseed.py")

import s4_point_banking_future_design as C1_DESIGN  # noqa: E402
import s4_point_banking_future_cloud_c2_reseed_design as DESIGN_SOURCE  # noqa: E402


class RuntimeDesign(DESIGN_SOURCE.Design):
    """Expose C1 Look objects without changing the reviewed design bytes."""

    @property
    def looks(self) -> tuple[C1_DESIGN.Look, ...]:
        return tuple(
            C1_DESIGN.Look(clusters, alpha)
            for clusters, alpha in zip(
                self.look_clusters, self.look_alphas, strict=True)
        )


class _RuntimeDesignModule:
    __file__ = DESIGN_SOURCE.__file__
    Design = RuntimeDesign

    def __getattr__(self, name: str):
        if hasattr(DESIGN_SOURCE, name):
            return getattr(DESIGN_SOURCE, name)
        return getattr(C1_DESIGN, name)


DESIGN = _RuntimeDesignModule()


def _load_base_runtime():
    spec = importlib.util.spec_from_file_location(
        "_s4_point_banking_future_c2_reseed_base", BASE_RUNNER)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load the S4 C1 runtime")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_CORE = _load_base_runtime()

_CORE.SCRIPT = SCRIPT
_CORE.DESIGN = DESIGN
_CORE.SCHEMA = "s4-point-banking-future-c2-reseed-shard-v1"
_CORE.AGGREGATE_SCHEMA = "s4-point-banking-future-c2-reseed-aggregate-v1"
_CORE.VALIDATION_SCHEMA = (
    "s4-point-banking-future-c2-reseed-runtime-validation-v1")
_CORE.PACKET_SCHEMA = (
    "s4-point-banking-future-c2-reseed-cloud-packet-v1")
_CORE.PACKET_REVIEW_SCHEMA = (
    "s4-point-banking-future-c2-reseed-cloud-packet-review-v1")
_CORE.PACKET_REVIEW_MARKER = (
    "S4_POINT_BANKING_FUTURE_C2_RESEED_PACKET_V1_REVIEW ")
_CORE.ADMISSION_SCHEMA = (
    "s4-point-banking-future-c2-reseed-cloud-admission-v1")
_CORE.RECEIPT_SCHEMA = (
    "s4-point-banking-future-c2-reseed-cloud-receipt-v1")
_CORE.DESIGN_REVIEW_GIT = (
    "8c262f77c97c33b68bdda8a37b71236f3a92b246")

_CORE.RUN_ID = DESIGN_SOURCE.RUN_ID
_CORE.NAMESPACE = Path("server/runs/logs") / _CORE.RUN_ID
_CORE.RUNNER_PATH = RUNNER_PATH
_CORE.CONTROLLER_PATH = CONTROLLER_PATH
_CORE.PREFLIGHT_RESULT_PATH = (
    DESIGN_SOURCE.C2.CAPACITY_RESULT.relative_to(_CORE.REPO))
_CORE.PACKET_EXTRA_FIELDS = frozenset({
    "controller_implementation_review",
    "implementation_sources",
    "new_preflight_run",
    "retired_population",
})
_CORE.DESIGN_REVIEW_EXTRA = {"implementation_authorized": True}
_CORE.SEED0 = DESIGN_SOURCE.SCREEN_SEED0
_CORE.LOOK_CLUSTERS = DESIGN_SOURCE.LOOK_CLUSTERS
_CORE.LOOK1_CLUSTERS, _CORE.MAX_CLUSTERS = _CORE.LOOK_CLUSTERS
_CORE.TRANCHE_COUNT = len(_CORE.LOOK_CLUSTERS)
_CORE.SHARD_COUNT = DESIGN_SOURCE.SHARD_COUNT
_CORE.CLUSTERS_PER_SHARD = _CORE.MAX_CLUSTERS // _CORE.SHARD_COUNT
_CORE.TRANCHE_CLUSTERS_PER_SHARD = (
    _CORE.LOOK1_CLUSTERS // _CORE.SHARD_COUNT)
_CORE.NULL_SENTINEL_STRIDE = DESIGN_SOURCE.NULL_SENTINEL_MODULUS
_CORE.NULL_SENTINEL_CLUSTERS = (
    _CORE.MAX_CLUSTERS // _CORE.NULL_SENTINEL_STRIDE)
_CORE.SHARD_NAMES = tuple(
    f"tranche-{tranche}-shard-{index:02d}.json"
    for tranche in range(1, _CORE.TRANCHE_COUNT + 1)
    for index in range(_CORE.SHARD_COUNT)
)
_CORE.MAX_PROJECTED_FLEET_HOURS = (
    DESIGN_SOURCE.MAX_PROJECTED_FLEET_HOURS)
_CORE.MAX_PROJECTED_SHARD_HOURS = (
    DESIGN_SOURCE.MAX_PROJECTED_SHARD_HOURS)
_CORE.CLAIM_BOUNDARY = (
    "One future-only, fresh-360B-population, two-look complete-round "
    "confirmation of frozen S4 versus exact live report-LCB. The complete "
    "300B interval is retired after reviewer gameplay crossed its boundary; "
    "no 300B outcome enters this claim. The reviewed score-free capacity "
    "measurement is reused only to size 16 physical shards. Matched null is "
    "an identity sentinel. No retry of a retired namespace, resize, promotion, "
    "deployment, or discretionary continuation."
)
_CORE.DESIGN_RECORD = json.loads(json.dumps(
    DESIGN_SOURCE.design_record(), sort_keys=True, separators=(",", ":")))
_CORE.SELECTION_RULE = C1_DESIGN.PRIMARY_EFFICACY
_CORE.LOOK1_TRANSITION = _CORE.DESIGN_RECORD["look_1_transition"]
_CORE.FINAL_TRANSITION = _CORE.DESIGN_RECORD["final_transition"]


def retired_population_record() -> dict:
    return {
        "reviewer_incident": DESIGN_SOURCE.incident_record(),
        "population": {
            **DESIGN_SOURCE.retired_population().__dict__,
            "low": DESIGN_SOURCE.retired_population().low,
            "high": DESIGN_SOURCE.retired_population().high,
        },
        "entire_interval_excluded": True,
        "outcomes_used_for_claim": False,
    }


def packet_profile_problems(packet: dict, *, expected_git: str,
                            receipt: dict,
                            current_runtime: dict) -> list[str]:
    expected_sources = {
        "base_runner_sha256": _CORE.sha256(BASE_RUNNER),
        "base_controller_sha256": _CORE.sha256(BASE_CONTROLLER),
    }
    expected_review = {
        "schema": "s4-point-banking-future-c2-reseed-controller-review-v1",
        "git": expected_git,
        "runner_sha256": _CORE.sha256(SCRIPT),
        "controller_sha256": receipt["controller_sha256"],
        **expected_sources,
        "design_git": _CORE.DESIGN_REVIEW_GIT,
        "design_sha256": _CORE.sha256(Path(DESIGN_SOURCE.__file__)),
        "capacity_result_sha256": DESIGN_SOURCE.C2.CAPACITY_RESULT_SHA256,
        "capacity_admission_sha256": (
            DESIGN_SOURCE.C2.CAPACITY_ADMISSION_SHA256),
        "expected_host": current_runtime.get("host"),
        "expected_python": current_runtime.get("python"),
        "expected_fast_binary_sha256": current_runtime.get(
            "fast_binary_sha256"),
        "sixteen_shard_contract_verified": True,
        "reused_score_free_capacity_verified": True,
        "retired_population": retired_population_record(),
        "fresh_namespace": DESIGN_SOURCE.RUN_ID,
        "child_boundary_validation_required": True,
        "runtime_validation_before_first_write": True,
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
        problems.append("C2 reseed implementation source drift")
    if packet.get("controller_implementation_review") != expected_review:
        problems.append("C2 reseed controller implementation review drift")
    if packet.get("new_preflight_run") is not False:
        problems.append("C2 reseed packet authorizes a new preflight")
    if packet.get("retired_population") != retired_population_record():
        problems.append("C2 retired-population boundary drift")
    return problems


_CORE.packet_profile_problems = packet_profile_problems

_base_require_runtime = _CORE.require_runtime


def require_runtime(expected_git: str) -> tuple[dict, dict]:
    parent, runtime = _base_require_runtime(expected_git)
    return parent, {
        **runtime,
        "future_profile": "cloud-c2-reseed-16-shard-v1",
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
