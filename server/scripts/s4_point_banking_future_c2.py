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
RUNNER_PATH = Path("server/scripts/s4_point_banking_future_c2.py")

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
_CORE.SCHEMA = "s4-point-banking-future-c2-shard-v1"
_CORE.AGGREGATE_SCHEMA = "s4-point-banking-future-c2-aggregate-v1"
_CORE.PACKET_SCHEMA = "s4-point-banking-future-c2-cloud-packet-v1"
_CORE.PACKET_REVIEW_SCHEMA = (
    "s4-point-banking-future-c2-cloud-packet-review-v1")
_CORE.PACKET_REVIEW_MARKER = (
    "S4_POINT_BANKING_FUTURE_C2_PACKET_V1_REVIEW ")
_CORE.ADMISSION_SCHEMA = "s4-point-banking-future-c2-cloud-admission-v1"
_CORE.RECEIPT_SCHEMA = "s4-point-banking-future-c2-cloud-receipt-v1"
_CORE.DESIGN_REVIEW_GIT = (
    "f0c2a6de07b828535d17350c1c3206942175ad45")

_CORE.RUN_ID = C2_DESIGN.RUN_ID
_CORE.NAMESPACE = Path("server/runs/logs") / _CORE.RUN_ID
_CORE.RUNNER_PATH = RUNNER_PATH
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
    "One future-only, fresh-population, two-look complete-round confirmation "
    "of frozen S4 versus exact live report-LCB. The reviewed C1 score-free "
    "capacity measurement is reused only to size 16 physical shards; no "
    "historical outcome enters the estimator. Matched null is an identity "
    "sentinel. No retry, resize, promotion, deployment, or discretionary "
    "continuation."
)
_CORE.DESIGN_RECORD = json.loads(json.dumps(
    C2_DESIGN.design_record(), sort_keys=True, separators=(",", ":")))
_CORE.SELECTION_RULE = C1_DESIGN.PRIMARY_EFFICACY
_CORE.LOOK1_TRANSITION = _CORE.DESIGN_RECORD["look_1_transition"]
_CORE.FINAL_TRANSITION = _CORE.DESIGN_RECORD["final_transition"]


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
