#!/usr/bin/env python3
"""Review and execute the 16-shard C2 profile of future S4.

This is a thin, fail-closed profile over the reviewed C1 controller.  It
reuses the exact score-free C1 capacity artifact, validates C2's adjusted
16-shard envelope, and explicitly refuses a preflight retry.  A controller
review can authorize only a packet freeze; packet admission and scored
execution remain separate external gates.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

import s4_point_banking_future_c2 as CORE
import s4_point_banking_future_cloud_c2_design as DESIGN


SCRIPT = Path(__file__).resolve()
BASE_CONTROLLER = SCRIPT.with_name("s4_point_banking_future_cloud.py")
RUNNER = Path("server/scripts/s4_point_banking_future_c2.py")
CONTROLLER = Path("server/scripts/s4_point_banking_future_cloud_c2.py")
CAPACITY_ADMISSION = DESIGN.CAPACITY_RESULT.with_name(
    "s4_point_banking_future_cloud_preflight_admission.v1.json")


def _load_base_controller():
    previous = sys.modules.get("s4_point_banking_future")
    sys.modules["s4_point_banking_future"] = CORE
    try:
        spec = importlib.util.spec_from_file_location(
            "_s4_point_banking_future_cloud_c2_base", BASE_CONTROLLER)
        if spec is None or spec.loader is None:
            raise RuntimeError("cannot load the S4 C1 Cloud controller")
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        if previous is None:
            sys.modules.pop("s4_point_banking_future", None)
        else:
            sys.modules["s4_point_banking_future"] = previous


_CTRL = _load_base_controller()

_CTRL.CORE = CORE
_CTRL.SCHEMA = "s4-point-banking-future-c2-cloud-controller-v1"
_CTRL.EXIT_SCHEMA = "s4-point-banking-future-c2-cloud-exit-v1"
_CTRL.FINAL_SCHEMA = "s4-point-banking-future-c2-cloud-final-v1"
_CTRL.PREAUTH_SCHEMA = (
    "s4-point-banking-future-c2-tranche2-preauthorization-v1")
_CTRL.RELEASE_SCHEMA = "s4-point-banking-future-c2-tranche2-release-v1"
_CTRL.CONTROLLER_REVIEW_MARKER = (
    "S4_POINT_BANKING_FUTURE_C2_CONTROLLER_V1_REVIEW ")
_CTRL.RUN_ID = CORE.RUN_ID
_CTRL.NAMESPACE = CORE.NAMESPACE
_CTRL.RUNNER = RUNNER
_CTRL.CONTROLLER = CONTROLLER
_CTRL.SHARD_COUNT = CORE.SHARD_COUNT
_CTRL.TRANCHE_COUNT = CORE.TRANCHE_COUNT
_CTRL.SHARD_NAMES = CORE.SHARD_NAMES
_CTRL.AGGREGATE_NAMES = CORE.AGGREGATE_NAMES
_CTRL.PREFLIGHT_PATH = DESIGN.CAPACITY_RESULT.relative_to(_CTRL.ROOT)
_CTRL.DESIGN_REVIEW_GIT = CORE.DESIGN_REVIEW_GIT

DESIGN_REVIEW_MARKER = "S4_POINT_BANKING_FUTURE_C2_DESIGN_V1_REVIEW "
CONTROLLER_REVIEW_MARKER = _CTRL.CONTROLLER_REVIEW_MARKER


def design_review_claim() -> dict:
    return {
        "capacity_result_sha256": DESIGN.CAPACITY_RESULT_SHA256,
        "design_sha256": _CTRL.sha256_file(Path(DESIGN.__file__)),
        "git": CORE.DESIGN_REVIEW_GIT,
        "implementation_authorized": True,
        "look_clusters": list(DESIGN.LOOK_CLUSTERS),
        "preflight_retry_authorized": False,
        "production_deployment": False,
        "production_promotion": False,
        "schema": DESIGN.SCHEMA,
        "scored_execution_authorized": False,
        "shard_count": DESIGN.SHARD_COUNT,
        "strength_claim": False,
        "verdict": "PASS_TO_IMPLEMENT",
    }


def _one_marker(raw: bytes, marker: str, *, label: str) -> dict:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _CTRL.SupervisorRefused(f"{label} is not UTF-8") from exc
    matches = [line[len(marker):] for line in text.splitlines()
               if line.startswith(marker)]
    if len(matches) != 1:
        raise _CTRL.SupervisorRefused(
            f"{label} must contain exactly one raw marker")
    try:
        value = json.loads(matches[0])
    except json.JSONDecodeError as exc:
        raise _CTRL.SupervisorRefused(f"{label} marker is invalid") from exc
    if not isinstance(value, dict):
        raise _CTRL.SupervisorRefused(f"{label} marker is not an object")
    return value


def design_review_evidence(path: Path) -> dict:
    ref = _CTRL._artifact_ref(path, None, "S4 C2 design review")
    if _one_marker(
            path.read_bytes(), DESIGN_REVIEW_MARKER,
            label="S4 C2 design review") != design_review_claim():
        raise _CTRL.SupervisorRefused("S4 C2 design review authority drift")
    return {
        **ref,
        "git": CORE.DESIGN_REVIEW_GIT,
        "verdict": "PASS_TO_IMPLEMENT",
        "implementation_authorized": True,
    }


def controller_review_claim(config) -> dict:
    return {
        "schema": "s4-point-banking-future-c2-controller-review-v1",
        "git": config.expected_git,
        "runner_sha256": config.expected_runner_sha256,
        "controller_sha256": config.expected_controller_sha256,
        "base_runner_sha256": _CTRL.sha256_file(CORE.BASE_RUNNER),
        "base_controller_sha256": _CTRL.sha256_file(BASE_CONTROLLER),
        "design_git": CORE.DESIGN_REVIEW_GIT,
        "design_sha256": _CTRL.sha256_file(Path(DESIGN.__file__)),
        "capacity_result_sha256": DESIGN.CAPACITY_RESULT_SHA256,
        "capacity_admission_sha256": DESIGN.CAPACITY_ADMISSION_SHA256,
        "expected_host": _CTRL.EXPECTED_HOST,
        "expected_python": _CTRL.EXPECTED_PYTHON,
        "expected_fast_binary_sha256": _CTRL.EXPECTED_FAST_SHA256,
        "sixteen_shard_contract_verified": True,
        "reused_score_free_capacity_verified": True,
        "new_preflight_authorized": False,
        "packet_freeze_authorized": True,
        "sequential_execution_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
        "verdict": "PASS",
    }


def controller_review_evidence(raw: bytes, config) -> dict:
    claim = _one_marker(
        raw, CONTROLLER_REVIEW_MARKER, label="S4 C2 controller review")
    if claim != controller_review_claim(config):
        raise _CTRL.SupervisorRefused(
            "S4 C2 controller review grants wrong authority")
    return claim


def capacity_evidence() -> dict:
    problems = DESIGN.design_problems()
    if problems:
        raise _CTRL.SupervisorRefused(
            "S4 C2 capacity evidence drift: " + "; ".join(problems))
    source = DESIGN.capacity_result()
    projection = DESIGN.adjusted_projection(value=source)
    criteria = {
        "source_integrity_pass": DESIGN.capacity_problems(source) == [],
        "source_score_free": (
            source.get("score_free") is True
            and source.get("outcomes_published") is False),
        "sixteen_shards_equal_cloud_cores": (
            DESIGN.SHARD_COUNT == DESIGN.CLOUD_CORES == 16),
        "fleet_hours_le_c2_cap": (
            projection["fleet_hours"] <= DESIGN.MAX_PROJECTED_FLEET_HOURS),
        "max_shard_hours_le_c2_cap": (
            projection["max_shard_hours"] <=
            DESIGN.MAX_PROJECTED_SHARD_HOURS),
    }
    criteria["all"] = all(criteria.values())
    if not criteria["all"]:
        raise _CTRL.SupervisorRefused("S4 C2 adjusted capacity does not pass")
    ref = _CTRL._artifact_ref(
        DESIGN.CAPACITY_RESULT, DESIGN.CAPACITY_RESULT_SHA256,
        "reviewed S4 C1 capacity result")
    admission_ref = _CTRL._artifact_ref(
        CAPACITY_ADMISSION, DESIGN.CAPACITY_ADMISSION_SHA256,
        "reviewed S4 C1 capacity admission")
    return {
        **ref,
        "schema": "s4-point-banking-future-c2-reused-capacity-v1",
        "score_free": True,
        "outcomes_published": False,
        "source_status": "HOLD",
        "source_admission": admission_ref,
        "source_projection": source["projection"],
        "projection": projection,
        "old_shard_count": C1_SHARD_COUNT,
        "new_shard_count": DESIGN.SHARD_COUNT,
        "criteria": criteria,
        "status": "AUTHORIZE_SEQUENTIAL_PACKET_REVIEW",
        "new_preflight_run": False,
        "preflight_retry_authorized": False,
    }


C1_SHARD_COUNT = DESIGN.C1.SHARD_COUNT
_base_packet_contract = _CTRL.packet_contract
_base_identity_context = _CTRL._identity_context


def _identity_context(config, paths):
    parent, runtime = _base_identity_context(config, paths)
    if runtime.get("future_base_runner_sha256") != _CTRL.sha256_file(
            CORE.BASE_RUNNER):
        raise _CTRL.SupervisorRefused("S4 C2 base runner identity drift")
    return parent, runtime


def packet_contract(config, paths, *, parent: dict, runtime: dict,
                    preflight: dict, design_review: dict,
                    controller_review: dict | None = None) -> dict:
    if controller_review != controller_review_claim(config):
        raise _CTRL.SupervisorRefused(
            "S4 C2 controller review did not authorize packet freeze")
    packet = _base_packet_contract(
        config, paths, parent=parent, runtime=runtime,
        preflight=preflight, design_review=design_review)
    packet["controller_implementation_review"] = controller_review
    packet["implementation_sources"] = {
        "base_runner_sha256": _CTRL.sha256_file(CORE.BASE_RUNNER),
        "base_controller_sha256": _CTRL.sha256_file(BASE_CONTROLLER),
    }
    packet["new_preflight_run"] = False
    return packet


def _expected_packet(config, paths):
    parent, runtime = _identity_context(config, paths)
    raw = paths.design_review_copy.read_bytes()
    design_review = design_review_evidence(paths.design_review_copy)
    controller_review = controller_review_evidence(raw, config)
    packet = packet_contract(
        config, paths, parent=parent, runtime=runtime,
        preflight=capacity_evidence(), design_review=design_review,
        controller_review=controller_review)
    return packet, parent, runtime


def freeze_packet(config, review_record: Path,
                  expected_review_sha256: str) -> dict:
    paths = _CTRL.paths_for()
    if paths.namespace.exists():
        raise _CTRL.SupervisorRefused("S4 C2 namespace already exists")
    if (_CTRL.sha256_file(review_record) != expected_review_sha256
            or not _CTRL.is_regular_unlinked(review_record)):
        raise _CTRL.SupervisorRefused("S4 C2 review source identity drift")
    raw = review_record.read_bytes()
    design_review_evidence(review_record)
    controller_review_evidence(raw, config)
    _CTRL._write_bytes_exclusive(paths.design_review_copy, raw)
    packet, _, _ = _expected_packet(config, paths)
    _CTRL._write_json_exclusive(paths.packet, packet)
    return {
        "path": _CTRL.rel(paths.packet),
        "sha256": _CTRL.sha256_file(paths.packet),
        "packet_review_authorized": True,
        "sequential_launch_authorized": False,
        "new_preflight_run": False,
    }


def run_score_free_preflight(*_args, **_kwargs):
    raise _CTRL.SupervisorRefused(
        "S4 C2 design forbids a preflight retry; reuse reviewed capacity")


# Install the small profile-specific seams into the isolated controller.  All
# execution, supervision, transition, and terminal verification logic remains
# the reviewed C1 implementation.
_CTRL.controller_review_claim = controller_review_claim
_CTRL.design_review_evidence = design_review_evidence
_CTRL._identity_context = _identity_context
_CTRL.packet_contract = packet_contract
_CTRL._expected_packet = _expected_packet
_CTRL.freeze_packet = freeze_packet
_CTRL.run_score_free_preflight = run_score_free_preflight


def __getattr__(name: str):
    return getattr(_CTRL, name)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command", choices=("controller-review-claim", "freeze",
                            "verify-packet", "admit", "launch", "verify"))
    parser.add_argument("--expected-git", required=True)
    parser.add_argument("--expected-runner-sha256", required=True)
    parser.add_argument("--expected-controller-sha256", required=True)
    parser.add_argument("--heartbeat-seconds", type=float, default=30.0)
    parser.add_argument("--review-record")
    parser.add_argument("--expected-review-sha256")
    parser.add_argument("--expected-packet-sha256")
    args = parser.parse_args(argv)
    if not 1.0 <= args.heartbeat_seconds <= 60.0:
        raise _CTRL.SupervisorRefused(
            "heartbeat must be between 1 and 60 seconds")
    config = _CTRL.Config(
        expected_git=args.expected_git,
        expected_runner_sha256=args.expected_runner_sha256,
        expected_controller_sha256=args.expected_controller_sha256,
        heartbeat_seconds=args.heartbeat_seconds)
    if args.command == "controller-review-claim":
        print(CONTROLLER_REVIEW_MARKER + json.dumps(
            controller_review_claim(config), sort_keys=True,
            separators=(",", ":")))
    elif args.command == "freeze":
        if not all((args.review_record, args.expected_review_sha256)):
            raise _CTRL.SupervisorRefused(
                "freeze requires the combined review record and SHA-256")
        print(json.dumps(freeze_packet(
            config, Path(args.review_record), args.expected_review_sha256),
            sort_keys=True))
    elif args.command == "verify-packet":
        packet = _CTRL.verify_packet(config)
        print(json.dumps({
            "verified": True,
            "packet_sha256": _CTRL.sha256_file(_CTRL.paths_for().packet),
            "sequential_launch_authorized":
                packet["sequential_launch_authorized"],
        }, sort_keys=True))
    elif args.command == "admit":
        if not all((args.review_record, args.expected_review_sha256,
                    args.expected_packet_sha256)):
            raise _CTRL.SupervisorRefused(
                "admit requires review path and both hashes")
        print(json.dumps(_CTRL.admit_packet(
            config, Path(args.review_record), args.expected_review_sha256,
            args.expected_packet_sha256), sort_keys=True))
    elif args.command == "launch":
        _CTRL.launch(config)
    else:
        _CTRL.verify(config)


if __name__ == "__main__":
    try:
        main()
    except (_CTRL.SupervisorRefused, CORE.ProtocolRefused,
            CORE.DUEL.ProtocolRefused) as exc:
        print(f"REFUSING: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(3) from exc
