#!/usr/bin/env python3
"""Read-only reviewer for the Pair V3 score-free capacity result.

This module has no writer, launcher, admission, gameplay, or REPORT surface.
It authenticates the frozen packet and its independent review, verifies the
consumed admission, and delegates the capacity arithmetic and score-free
boundary to the controller's pure validator.  A successful review authorizes
only design of a future scored packet; it does not authorize freezing or
running that packet.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
import types
from pathlib import Path


class CapacityResultReviewRefused(RuntimeError):
    """The score-free capacity evidence or its authority chain drifted."""


_HASHLIB_SHA256 = hashlib.sha256


def _sha256_file(path: Path) -> str:
    """Hash a file without trusting any reviewed Pair dependency."""
    digest = _HASHLIB_SHA256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_bytes(value: bytes) -> str:
    """Hash bytes without trusting any reviewed Pair dependency."""
    return _HASHLIB_SHA256(value).hexdigest()


def _is_sha256(value: object) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(char in "0123456789abcdef" for char in value))


def _digest(value: object) -> str:
    encoded = (json.dumps(
        value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    return _sha256_bytes(encoded)


DEPENDENCY_IMPORT_NAMES = (
    "pair_ballot_affected_aggregate",
    "pair_ballot_affected_capacity_design",
    "pair_ballot_affected_capacity_preflight",
    "pair_ballot_affected_eval",
    "pair_ballot_affected_states",
)
EXPECTED_DEPENDENCY_SHA256S = {
    "pair_ballot_affected_aggregate.py": (
        "a1908a32853ea62e0c775dd1975b7b7ad7316f662dc19b8fe108b25282099ba0"),
    "pair_ballot_affected_capacity_design.py": (
        "caa2d0d9c5580c56828e72c39e3e5ad0cf5be0d3eb7a8a77603e31c73e786317"),
    "pair_ballot_affected_capacity_preflight.py": (
        "cab2caa01f58c02d932365993c856894f811408853c8a2bef9ca42a75721ebaa"),
    "pair_ballot_affected_eval.py": (
        "2d4adfd06d0de7517bb190ebf5d190bd95f848d9ab25fb5eb9a29f27b3cd7488"),
    "pair_ballot_affected_states.py": (
        "e54102482c2f1652186bfa5458f4f229fa01bd8bf74cdcb2d29c7fe133e6f4ce"),
}
PRELOADED_DEPENDENCIES = tuple(
    name for name in DEPENDENCY_IMPORT_NAMES if name in sys.modules)


def _preimport_dependency_sources() -> dict[str, tuple[Path, bytes]]:
    """Read and authenticate every dependency before any can execute."""
    if not sys.dont_write_bytecode:
        raise CapacityResultReviewRefused(
            "review requires PYTHONDONTWRITEBYTECODE=1")
    if PRELOADED_DEPENDENCIES:
        raise CapacityResultReviewRefused(
            "review dependency was preloaded before the reviewer: "
            + ",".join(PRELOADED_DEPENDENCIES))
    expected_names = {f"{name}.py" for name in DEPENDENCY_IMPORT_NAMES}
    if (set(EXPECTED_DEPENDENCY_SHA256S) != expected_names
            or not all(_is_sha256(value)
                       for value in EXPECTED_DEPENDENCY_SHA256S.values())):
        raise CapacityResultReviewRefused("review dependency population drift")
    scripts = Path(__file__).resolve().parent
    verified_sources: dict[str, tuple[Path, bytes]] = {}
    for import_name in DEPENDENCY_IMPORT_NAMES:
        name = f"{import_name}.py"
        expected_path = scripts / name
        try:
            resolved_path = expected_path.resolve(strict=True)
            source = resolved_path.read_bytes()
        except OSError as exc:
            raise CapacityResultReviewRefused(
                f"review dependency source is unreadable before import: {name}") \
                from exc
        if (resolved_path != expected_path
                or _sha256_bytes(source)
                != EXPECTED_DEPENDENCY_SHA256S[name]):
            raise CapacityResultReviewRefused(
                f"review dependency source drift before import: {name}")
        verified_sources[name] = (resolved_path, source)
    return verified_sources


PREIMPORT_DEPENDENCY_SOURCES = _preimport_dependency_sources()


def _load_verified_dependency(import_name: str) -> types.ModuleType:
    """Execute only the exact source bytes authenticated above."""
    name = f"{import_name}.py"
    path, source = PREIMPORT_DEPENDENCY_SOURCES[name]
    module = types.ModuleType(import_name)
    module.__file__ = str(path)
    module.__package__ = ""
    module.__cached__ = None
    sys.modules[import_name] = module
    try:
        exec(compile(source, str(path), "exec", dont_inherit=True),
             module.__dict__)
    except BaseException:
        if sys.modules.get(import_name) is module:
            del sys.modules[import_name]
        raise
    return module


# Topological order: later Pair modules import only earlier Pair modules.
STATES = _load_verified_dependency("pair_ballot_affected_states")
EVAL = _load_verified_dependency("pair_ballot_affected_eval")
AGG = _load_verified_dependency("pair_ballot_affected_aggregate")
DESIGN = _load_verified_dependency("pair_ballot_affected_capacity_design")
CAPACITY = _load_verified_dependency("pair_ballot_affected_capacity_preflight")


EXPECTED_GIT = "6461c660e1ff71a905d9010b12c0adfc4e8bc729"
EXPECTED_PACKET_SHA256 = (
    "e054c5e582c1e665da9bc8ab413639f4c015ffe31a85f22c83275b7f4b4de492")
EXPECTED_PACKET_INTERNAL_SHA256 = (
    "25b1888c62ff772c18e065b30a7bfcc2d724c645f5ad054c4e6823dfd56a14b5")
PACKET_REVIEW_GIT = "88866f25f3763f26996be6f45fbcfcdfe3854f30"
PACKET_REVIEW_PARENT_GIT = "023850da1bc8f0737814b3ebb9bfceea928d2c3d"
RESULT_REVIEW_PREFIX = (
    "PAIR_BALLOT_AFFECTED_CAPACITY_PREFLIGHT_RESULT_V1_REVIEW ")
RESULT_REVIEW_SCHEMA = (
    "pair-ballot-affected-capacity-preflight-result-review-v1")
DEPENDENCY_MODULES = {
    "pair_ballot_affected_aggregate.py": AGG,
    "pair_ballot_affected_capacity_design.py": DESIGN,
    "pair_ballot_affected_capacity_preflight.py": CAPACITY,
    "pair_ballot_affected_eval.py": EVAL,
    "pair_ballot_affected_states.py": STATES,
}


def _is_hex(value: object, length: int) -> bool:
    return (isinstance(value, str) and len(value) == length
            and all(char in "0123456789abcdef" for char in value))


def _strict_object(pairs: list[tuple[str, object]]) -> dict:
    value: dict = {}
    for key, child in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key: {key}")
        value[key] = child
    return value


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number: {value}")


def _require_dependency_sources() -> None:
    if PRELOADED_DEPENDENCIES:
        raise CapacityResultReviewRefused(
            "review dependency was preloaded before the reviewer: "
            + ",".join(PRELOADED_DEPENDENCIES))
    scripts = Path(__file__).resolve().parent
    if (set(DEPENDENCY_MODULES) != set(EXPECTED_DEPENDENCY_SHA256S)
            or set(PREIMPORT_DEPENDENCY_SOURCES)
            != set(EXPECTED_DEPENDENCY_SHA256S)):
        raise CapacityResultReviewRefused("review dependency population drift")
    for name, module in DEPENDENCY_MODULES.items():
        expected_path = scripts / name
        try:
            resolved_path = expected_path.resolve(strict=True)
            module_path = Path(
                str(getattr(module, "__file__", ""))).resolve(strict=True)
            observed_sha256 = _sha256_file(resolved_path)
        except OSError as exc:
            raise CapacityResultReviewRefused(
                f"review dependency identity drift: {name}") from exc
        if (resolved_path != expected_path
                or PREIMPORT_DEPENDENCY_SOURCES[name][0] != expected_path
                or _sha256_bytes(PREIMPORT_DEPENDENCY_SOURCES[name][1])
                != EXPECTED_DEPENDENCY_SHA256S[name]
                or module_path != expected_path
                or sys.modules.get(module.__name__) is not module
                or observed_sha256 != EXPECTED_DEPENDENCY_SHA256S[name]):
            raise CapacityResultReviewRefused(
                f"review dependency identity drift: {name}")


_require_dependency_sources()


def _load_exact_json(path: Path, expected_sha256: str, *, label: str) -> dict:
    if not _is_sha256(expected_sha256):
        raise CapacityResultReviewRefused(f"{label} expected SHA-256 drift")
    partial = Path(str(path) + ".partial")
    try:
        info = path.lstat()
    except FileNotFoundError as exc:
        raise CapacityResultReviewRefused(f"{label} is missing") from exc
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or os.path.lexists(partial)):
        raise CapacityResultReviewRefused(
            f"{label} is linked, nonregular, or partial")
    if _sha256_file(path) != expected_sha256:
        raise CapacityResultReviewRefused(f"{label} file SHA-256 drift")
    try:
        value = json.loads(
            path.read_bytes(), object_pairs_hook=_strict_object,
            parse_constant=_reject_constant)
    except (OSError, ValueError) as exc:
        raise CapacityResultReviewRefused(f"{label} is unreadable") from exc
    if not isinstance(value, dict):
        raise CapacityResultReviewRefused(f"{label} is not an object")
    return value


def _packet_review(packet: dict, review_snapshot_path: Path) -> tuple[dict, bytes]:
    claim = CAPACITY.packet_review_claim(
        expected_git=EXPECTED_GIT,
        packet_sha256=EXPECTED_PACKET_SHA256,
        packet_internal_sha256=EXPECTED_PACKET_INTERNAL_SHA256)
    try:
        review, marker = CAPACITY.canonical_review_record(
            commit=PACKET_REVIEW_GIT,
            prefix=CAPACITY.PACKET_REVIEW_PREFIX,
            expected=claim,
            expected_parent=PACKET_REVIEW_PARENT_GIT,
            label="Pair V3 preflight packet review")
        CAPACITY.require_regular_unlinked(
            review_snapshot_path, label="Pair V3 packet review snapshot")
    except CAPACITY.CapacityPreflightRefused as exc:
        raise CapacityResultReviewRefused(str(exc)) from exc
    if (review_snapshot_path.read_bytes() != marker
            or _sha256_file(review_snapshot_path)
            != review["marker_sha256"]):
        raise CapacityResultReviewRefused(
            "Pair V3 packet review snapshot drift")
    if (packet.get("git") != EXPECTED_GIT
            or packet.get("internal_sha256")
            != EXPECTED_PACKET_INTERNAL_SHA256):
        raise CapacityResultReviewRefused("Pair V3 packet identity drift")
    return review, marker


def _admission_problems(admission: object, *, packet: dict,
                        review: dict) -> list[str]:
    if not isinstance(admission, dict):
        return ["admission is not an object"]
    expected_fields = {
        "schema", "run_id", "git", "packet_sha256",
        "packet_review_commit", "packet_review_marker_sha256", "nonce",
        "created_time_ns", "systemd_invocation_id",
        "one_score_free_preflight_authorized",
        "scored_evaluation_authorized", "report_access_authorized",
        "strength_claim", "production_deployment", "internal_sha256",
    }
    problems: list[str] = []
    if set(admission) != expected_fields:
        problems.append("admission field population")
        return problems
    if (admission["schema"] != CAPACITY.ADMISSION_SCHEMA
            or admission["run_id"] != CAPACITY.RUN_ID
            or admission["git"] != EXPECTED_GIT
            or admission["packet_sha256"] != EXPECTED_PACKET_SHA256
            or admission["packet_review_commit"] != PACKET_REVIEW_GIT
            or admission["packet_review_marker_sha256"]
            != review["marker_sha256"]
            or not _is_hex(admission["nonce"], 64)
            or not isinstance(admission["created_time_ns"], int)
            or isinstance(admission["created_time_ns"], bool)
            or admission["created_time_ns"] <= 0
            or not _is_hex(admission["systemd_invocation_id"], 32)):
        problems.append("admission identity")
    if admission["one_score_free_preflight_authorized"] is not True:
        problems.append("admission did not authorize the one score-free run")
    for field in (
            "scored_evaluation_authorized", "report_access_authorized",
            "strength_claim", "production_deployment"):
        if admission[field] is not False:
            problems.append(f"admission authority escalation: {field}")
    body = dict(admission)
    observed = body.pop("internal_sha256")
    if (not _is_sha256(observed)
            or observed != _digest(body)):
        problems.append("admission internal digest")
    if packet.get("internal_sha256") != EXPECTED_PACKET_INTERNAL_SHA256:
        problems.append("admission packet binding")
    return sorted(set(problems))


def result_review_claim(*, admission_sha256: str, result_sha256: str,
                        result_internal_sha256: str) -> dict:
    """Return the sole deterministic authority emitted by this reviewer."""
    return {
        "admission_sha256": admission_sha256,
        "git": EXPECTED_GIT,
        "independent_review": True,
        "packet_internal_sha256": EXPECTED_PACKET_INTERNAL_SHA256,
        "packet_review_commit": PACKET_REVIEW_GIT,
        "packet_sha256": EXPECTED_PACKET_SHA256,
        "production_deployment": False,
        "production_promotion": False,
        "report_access_authorized": False,
        "reviewer_dependency_sha256s": EXPECTED_DEPENDENCY_SHA256S,
        "result_reviewer_script_sha256": _sha256_file(Path(__file__)),
        "result_internal_sha256": result_internal_sha256,
        "result_sha256": result_sha256,
        "run_id": CAPACITY.RUN_ID,
        "schema": RESULT_REVIEW_SCHEMA,
        "scored_evaluation_authorized": False,
        "scored_packet_design_authorized": True,
        "scored_packet_freeze_authorized": False,
        "scored_packet_run_authorized": False,
        "score_free_capacity_pass": True,
        "strength_claim": False,
        "training_authorized": False,
        "retry_authorized": False,
        "extension_authorized": False,
        "verdict": "PASS",
    }


def verify(*, population_path: Path, design_path: Path, packet_path: Path,
           packet_review_snapshot_path: Path, admission_path: Path,
           expected_admission_sha256: str, result_path: Path,
           expected_result_sha256: str) -> dict:
    """Verify immutable evidence and return a design-only review claim."""
    _require_dependency_sources()
    try:
        packet = CAPACITY.load_packet(
            packet_path, EXPECTED_PACKET_SHA256,
            expected_git=EXPECTED_GIT,
            population_path=population_path,
            design_path=design_path)
    except CAPACITY.CapacityPreflightRefused as exc:
        raise CapacityResultReviewRefused(str(exc)) from exc
    review, _marker = _packet_review(packet, packet_review_snapshot_path)

    admission = _load_exact_json(
        admission_path, expected_admission_sha256,
        label="Pair V3 consumed admission")
    problems = _admission_problems(admission, packet=packet, review=review)
    if problems:
        raise CapacityResultReviewRefused("; ".join(problems))

    result = _load_exact_json(
        result_path, expected_result_sha256,
        label="Pair V3 score-free capacity result")
    result_body = dict(result)
    result_internal_sha256 = result_body.pop("internal_sha256", None)
    if (not _is_sha256(result_internal_sha256)
            or result_internal_sha256 != _digest(result_body)):
        raise CapacityResultReviewRefused(
            "capacity result internal digest")
    try:
        design = DESIGN.verify_design(population_path, design_path)
    except Exception as exc:
        raise CapacityResultReviewRefused(
            f"cannot reconstruct reviewed design: {type(exc).__name__}: {exc}") \
            from exc
    problems = CAPACITY.score_free_result_problems(result, design=design)
    if result.get("git") != EXPECTED_GIT:
        problems.append("result Git binding")
    if result.get("packet_sha256") != EXPECTED_PACKET_SHA256:
        problems.append("result packet file binding")
    if (result.get("packet_internal_sha256")
            != EXPECTED_PACKET_INTERNAL_SHA256):
        problems.append("result packet internal binding")
    if result.get("admission_sha256") != expected_admission_sha256:
        problems.append("result admission binding")
    if result.get("runtime") != packet.get("runtime"):
        problems.append("result runtime differs from frozen packet")
    criteria = result.get("criteria")
    if (not isinstance(criteria, dict) or criteria.get("all") is not True
            or result.get("status") != "AUTHORIZE_CAPACITY_RESULT_REVIEW"):
        problems.append("capacity result did not pass every criterion")
    if problems:
        raise CapacityResultReviewRefused("; ".join(sorted(set(problems))))
    return result_review_claim(
        admission_sha256=expected_admission_sha256,
        result_sha256=expected_result_sha256,
        result_internal_sha256=result["internal_sha256"])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--population", type=Path, required=True)
    parser.add_argument("--design", type=Path, required=True)
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--packet-review-snapshot", type=Path, required=True)
    parser.add_argument("--admission", type=Path, required=True)
    parser.add_argument("--expected-admission-sha256", required=True)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--expected-result-sha256", required=True)
    args = parser.parse_args()
    claim = verify(
        population_path=args.population.resolve(),
        design_path=args.design.resolve(), packet_path=args.packet.resolve(),
        packet_review_snapshot_path=args.packet_review_snapshot.resolve(),
        admission_path=args.admission.resolve(),
        expected_admission_sha256=args.expected_admission_sha256,
        result_path=args.result.resolve(),
        expected_result_sha256=args.expected_result_sha256)
    print(RESULT_REVIEW_PREFIX + json.dumps(
        claim, sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
