#!/usr/bin/env python3
"""Mini execution profile for the reviewed selective-S6 capacity preflight.

The Air packet is scientifically unchanged but cannot run while Air owns the
long pair-aware screen.  This module loads the reviewed full-hand controller
in isolation, pins Mini's exact runtime, and gives the alternative preflight a
fresh namespace and review marker.  It never borrows the existing Air launch
authority: a Mini packet review must explicitly supersede that packet before
one score-free preflight can execute.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SCRIPT = Path(__file__).resolve()
BASE_CONTROLLER = SCRIPT.with_name(
    "s6_throw_full_hand_preflight_controller.py")


def _load_base_controller():
    spec = importlib.util.spec_from_file_location(
        "_s6_throw_full_hand_preflight_mini_base", BASE_CONTROLLER)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load the selective-S6 base controller")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_CTRL = _load_base_controller()

AIR_PACKET = {
    "git": "a48542d756aaeaf85fa07e44816383a52da88e89",
    "packet_sha256":
        "19f3b2a3d8a50bc10657adfe6d5ef8973dce125d258e8febf48d1fb3adb79dd0",
    "run_id": "s6-throw-full-hand-screen-437b-v2",
    "preflight_run_id": "s6-throw-full-hand-preflight-436b-v2",
    "execution_superseded_by_mini_review": True,
}

_CTRL.SCRIPT = SCRIPT
_CTRL.PACKET_SCHEMA = "s6-throw-full-hand-mini-capacity-packet-v1"
_CTRL.RESULT_SCHEMA = "s6-throw-full-hand-mini-capacity-result-v1"
_CTRL.ADMISSION_SCHEMA = "s6-throw-full-hand-mini-capacity-admission-v1"
_CTRL.FREEZE_ADMISSION_SCHEMA = (
    "s6-throw-full-hand-mini-packet-freeze-admission-v1")
_CTRL.RUN_ID = "s6-throw-full-hand-screen-437b-mini-v1"
_CTRL.PREFLIGHT_RUN_ID = "s6-throw-full-hand-preflight-436b-mini-v1"
_CTRL.PACKET_REVIEW_PREFIX = (
    "S6_FULL_HAND_PREFLIGHT_MINI_PACKET_V1_REVIEW ")
_CTRL.EXPECTED_EXECUTION_HOST = "Jerrys-Mac-mini.local"
_CTRL.EXPECTED_PYTHON_VERSION = "3.14.3"
_CTRL.EXPECTED_PYTHON_EXECUTABLE = (
    "/Users/jerryyu/.local/share/uv/python/"
    "cpython-3.14.3-macos-aarch64-none/bin/python3.14")
_CTRL.EXPECTED_FAST_BINARY_SHA256 = (
    "9c9e77fbdc4c6caceec195465155f37ec6369e409462fd838bc142bf8a0be4c1")
_CTRL.RUN_LOG_DIR = (
    _CTRL.SERVER / "runs/logs" / _CTRL.PREFLIGHT_RUN_ID)
_CTRL.PACKET_PATH = _CTRL.RUN_LOG_DIR / "controller-packet.json"
_CTRL.CLAIM_PATH = _CTRL.RUN_LOG_DIR / "packet-review-request.txt"
_CTRL.FREEZE_ADMISSION_PATH = (
    _CTRL.SERVER / "runs/locks" /
    f"{_CTRL.PREFLIGHT_RUN_ID}.packet-freeze.consumed.json")
_CTRL.ADMISSION_PATH = (
    _CTRL.SERVER / "runs/locks" /
    f"{_CTRL.PREFLIGHT_RUN_ID}.admission.consumed.json")
_CTRL.RESULT_PATH = _CTRL.RUN_LOG_DIR / "capacity.json"

_base_source_paths = _CTRL.source_paths
_base_packet_payload = _CTRL.packet_payload
_base_freeze_admission_payload = _CTRL.freeze_admission_payload
_base_capacity_review_claim = _CTRL.capacity_review_claim


def source_paths() -> dict[str, Path]:
    paths = _base_source_paths()
    paths["controller"] = SCRIPT
    paths["base_full_hand_controller"] = BASE_CONTROLLER
    return paths


def runtime_problems(runtime: object) -> list[str]:
    expected = {
        "host": _CTRL.EXPECTED_EXECUTION_HOST,
        "python": _CTRL.EXPECTED_PYTHON_VERSION,
        "implementation": "CPython",
        "python_executable": _CTRL.EXPECTED_PYTHON_EXECUTABLE,
        "fast_required": True,
        "strict_voids_required": True,
        "fast_env_active": True,
        "strict_voids_active": True,
        "compiled_binding_active": True,
        "fast_binary_sha256": _CTRL.EXPECTED_FAST_BINARY_SHA256,
    }
    return [] if runtime == expected else ["runtime is not exact reviewed Mini"]


def require_mini_runtime() -> dict[str, object]:
    runtime = _CTRL.runtime_snapshot()
    problems = runtime_problems(runtime)
    if problems:
        raise _CTRL.ControllerRefused("; ".join(problems))
    return runtime


def supersession_record() -> dict[str, object]:
    return dict(AIR_PACKET)


def freeze_admission_payload(*, expected_git: str,
                             selector_review_record,
                             nonce: str,
                             created_unix_ns: int) -> dict:
    payload = _base_freeze_admission_payload(
        expected_git=expected_git,
        selector_review_record=selector_review_record,
        nonce=nonce,
        created_unix_ns=created_unix_ns)
    payload.pop("internal_sha256")
    payload["supersedes_air_packet"] = supersession_record()
    payload["internal_sha256"] = _CTRL.stable_digest(payload)
    return payload


def packet_payload(*, expected_git: str,
                   selector_review_record) -> dict:
    payload = _base_packet_payload(
        expected_git=expected_git,
        selector_review_record=selector_review_record)
    payload.pop("internal_sha256")
    payload["execution_profile"] = {
        "profile": "mini-alternative-v1",
        "scientific_design_changed": False,
        "same_preflight_and_screen_seeds": True,
        "same_work_and_capacity_caps": True,
        "air_packet_must_not_execute_after_mini_pass": True,
    }
    payload["supersedes_air_packet"] = supersession_record()
    payload["internal_sha256"] = _CTRL.stable_digest(payload)
    return payload


def packet_review_claim(*, expected_git: str,
                        packet_sha256: str) -> dict:
    return {
        "git": expected_git,
        "independent_review": True,
        "one_score_free_preflight_authorized": True,
        "packet_sha256": packet_sha256,
        "supersedes_air_packet_sha256": AIR_PACKET["packet_sha256"],
        "air_preflight_execution_authorized": False,
        "production_deployment": False,
        "production_promotion": False,
        "run_id": _CTRL.RUN_ID,
        "schema": "s6-throw-full-hand-mini-preflight-packet-review-v1",
        "screen_execution_authorized": False,
        "strength_claim": False,
        "verdict": "PASS",
    }


def capacity_review_claim(*, result: dict, result_sha256: str,
                          packet_sha256: str) -> dict:
    claim = _base_capacity_review_claim(
        result=result, result_sha256=result_sha256,
        packet_sha256=packet_sha256)
    claim["schema"] = "s6-throw-full-hand-mini-capacity-review-v1"
    claim["run_id"] = _CTRL.RUN_ID
    claim["supersedes_air_packet_sha256"] = AIR_PACKET["packet_sha256"]
    return claim


_CTRL.source_paths = source_paths
_CTRL.source_sha256s = lambda: {
    name: _CTRL.sha256(path) for name, path in source_paths().items()}
_CTRL.runtime_problems = runtime_problems
_CTRL.require_air_runtime = require_mini_runtime
_CTRL.freeze_admission_payload = freeze_admission_payload
_CTRL.packet_payload = packet_payload
_CTRL.packet_review_claim = packet_review_claim
_CTRL.capacity_review_claim = capacity_review_claim


def __getattr__(name: str):
    return getattr(_CTRL, name)


def main() -> None:
    _CTRL.main()


if __name__ == "__main__":
    main()
