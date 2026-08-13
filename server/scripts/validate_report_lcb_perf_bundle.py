#!/usr/bin/env python3
"""Independently reopen one immutable report-LCB performance A/B bundle.

The caller must provide the externally preserved design and manifest digests.
The validator trusts neither the bundle's recorded booleans nor its result: it
authenticates the closed file population, reopens every semantic artifact, and
recomputes all statistics and the retain/drop verdict from raw nanoseconds.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import sys
import tarfile
from types import ModuleType
from typing import Any


class BundleRefused(RuntimeError):
    """The bundle is incomplete, mutable, unauthenticated, or inconsistent."""


def _pairs_no_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise BundleRefused(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _nonfinite(token: str) -> None:
    raise BundleRefused(f"non-finite JSON value: {token}")


def load_json(path: Path) -> Any:
    try:
        return json.loads(
            path.read_bytes(), object_pairs_hook=_pairs_no_duplicates,
            parse_constant=_nonfinite)
    except BundleRefused:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BundleRefused(f"invalid JSON {path.name}: {exc}") from exc


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _require_sha(value: str, label: str) -> None:
    if (not isinstance(value, str) or len(value) != 64
            or any(char not in "0123456789abcdef" for char in value)):
        raise BundleRefused(f"{label} is not a lowercase SHA-256")


def _regular_metadata(path: Path) -> dict[str, Any]:
    status = path.stat()
    if (path.is_symlink() or not stat.S_ISREG(status.st_mode)
            or status.st_nlink != 1 or status.st_uid != 0
            or status.st_gid != 0 or status.st_mode & 0o222):
        raise BundleRefused(f"artifact is not immutable root-owned: {path.name}")
    return {
        "path": path.name,
        "sha256": sha256_file(path),
        "bytes": status.st_size,
        "mode": stat.S_IMODE(status.st_mode),
        "uid": status.st_uid,
        "gid": status.st_gid,
        "nlink": status.st_nlink,
    }


def _require_bundle_directory(root: Path) -> None:
    status = root.stat()
    if (root.is_symlink() or not stat.S_ISDIR(status.st_mode)
            or status.st_uid != 0 or status.st_gid != 0
            or status.st_mode & 0o222):
        raise BundleRefused("bundle directory is not immutable root-owned")


def _load_harness(root: Path, design: dict[str, Any]) -> ModuleType:
    path = root / "harness.py"
    if sha256_file(path) != design.get("harness", {}).get("sha256"):
        raise BundleRefused("bundled harness differs from reviewed source")
    module = ModuleType("frozen_perf_harness")
    module.__file__ = str(path)
    try:
        exec(compile(path.read_bytes(), str(path), "exec"), module.__dict__)
    except Exception as exc:
        raise BundleRefused(f"could not load bundled harness: {exc}") from exc
    return module


def _expected_paths(harness: ModuleType) -> set[str]:
    paths = {
        "design.json", "review.json", "harness.py", "validator.py",
        "systemd.unit", "host-profile.json", "base.identity.json",
        "head.identity.json", "base.source.tar", "head.source.tar",
        "base.native.bin", "head.native.bin", "python.bin",
        "execution.json", "result.json",
    }
    for seed in harness.PAIR_SEEDS:
        for label in ("base", "head"):
            stem = f"seed-{seed}.{label}"
            paths.update({
                f"{stem}.raw.json", f"{stem}.normalized.json",
                f"{stem}.stdout.jsonl", f"{stem}.stderr.log",
            })
    return paths


def _validate_source_archive(path: Path, source_map: dict[str, str]) -> None:
    seen: dict[str, str] = {}
    try:
        with tarfile.open(path, "r") as archive:
            for member in archive:
                pure = PurePosixPath(member.name)
                if (not member.isfile() or pure.is_absolute()
                        or ".." in pure.parts or "." in pure.parts
                        or member.name in seen):
                    raise BundleRefused(
                        f"unsafe source archive member: {member.name}")
                source = archive.extractfile(member)
                if source is None:
                    raise BundleRefused(
                        f"unreadable source archive member: {member.name}")
                seen[member.name] = hashlib.sha256(source.read()).hexdigest()
    except (tarfile.TarError, OSError) as exc:
        raise BundleRefused(f"invalid source archive {path.name}: {exc}") from exc
    if seen != source_map:
        raise BundleRefused(f"{path.name} source path/hash closure drift")


def validate_bundle(root: Path, expected_design_sha: str,
                    expected_manifest_sha: str) -> dict[str, Any]:
    root = root.absolute()
    if root.is_symlink():
        raise BundleRefused("bundle path must not be a symlink")
    root = root.resolve()
    _require_sha(expected_design_sha, "external design SHA")
    _require_sha(expected_manifest_sha, "external manifest SHA")
    _require_bundle_directory(root)
    manifest_path = root / "manifest.json"
    _regular_metadata(manifest_path)
    if sha256_file(manifest_path) != expected_manifest_sha:
        raise BundleRefused("external manifest digest drift")
    manifest = load_json(manifest_path)
    if (not isinstance(manifest, dict) or set(manifest) != {
            "schema", "design_sha256", "review_record_sha256",
            "systemd_invocation_id", "artifacts"}):
        raise BundleRefused("manifest field set drift")

    design_path = root / "design.json"
    if sha256_file(design_path) != expected_design_sha \
            or manifest["design_sha256"] != expected_design_sha:
        raise BundleRefused("external design digest drift")
    design = load_json(design_path)
    if not isinstance(design, dict):
        raise BundleRefused("design is not an object")
    harness = _load_harness(root, design)
    try:
        harness.require_design(design)
    except Exception as exc:
        raise BundleRefused(f"design contract refused: {exc}") from exc
    if manifest.get("schema") != harness.BUNDLE_SCHEMA:
        raise BundleRefused("manifest schema drift")

    actual_paths = {path.name for path in root.iterdir()}
    expected_paths = _expected_paths(harness) | {"manifest.json"}
    if actual_paths != expected_paths:
        raise BundleRefused(
            f"bundle path closure drift: missing={sorted(expected_paths-actual_paths)}; "
            f"extra={sorted(actual_paths-expected_paths)}")
    entries = manifest.get("artifacts")
    if (not isinstance(entries, list)
            or any(not isinstance(entry, dict) for entry in entries)
            or len({entry.get("path") for entry in entries}) != len(entries)):
        raise BundleRefused("manifest artifact population drift")
    observed = [_regular_metadata(root / name)
                for name in sorted(_expected_paths(harness))]
    if sorted(entries, key=lambda entry: entry.get("path", "")) != observed:
        raise BundleRefused("manifest artifact metadata/hash closure drift")

    if (sha256_file(root / "validator.py") !=
            design["validator"]["sha256"]
            or sha256_file(Path(__file__).resolve()) !=
            design["validator"]["sha256"]):
        raise BundleRefused("offline validator source identity drift")
    if (sha256_file(root / "systemd.unit") !=
            design["execution"]["systemd_unit"]["sha256"]
            or sha256_file(root / "host-profile.json") !=
            design["execution"]["host_profile"]["sha256"]
            or sha256_file(root / "python.bin") != design["python"]["sha256"]):
        raise BundleRefused("runtime artifact identity drift")

    review = load_json(root / "review.json")
    review_sha = sha256_file(root / "review.json")
    if (not isinstance(review, dict)
            or review_sha != manifest["review_record_sha256"]
            or set(review) != {
                "schema", "design_sha256", "verdict", "reviewer", "summary"}
            or review.get("schema") != harness.REVIEW_SCHEMA
            or review.get("design_sha256") != expected_design_sha
            or review.get("verdict") != "PASS"
            or not isinstance(review.get("reviewer"), str)
            or not review["reviewer"]
            or not isinstance(review.get("summary"), str)):
        raise BundleRefused("review PASS binding drift")
    execution = load_json(root / "execution.json")
    expected_execution_keys = {
        "schema", "design_sha256", "review_record_sha256",
        "review_record_source_path", "systemd_invocation_id", "boot_id",
        "started_unix_ns", "finished_arms_unix_ns", "arms_completed",
        "arm_sequence", "child_environment", "systemd_unit_sha256",
        "host_profile_sha256",
    }
    if (not isinstance(execution, dict)
            or set(execution) != expected_execution_keys
            or execution.get("schema") != harness.EXECUTION_SCHEMA
            or execution.get("design_sha256") != expected_design_sha
            or execution.get("review_record_sha256") != review_sha
            or execution.get("systemd_invocation_id") !=
            manifest["systemd_invocation_id"]
            or execution.get("arms_completed") != 12
            or execution.get("systemd_unit_sha256") !=
            design["execution"]["systemd_unit"]["sha256"]
            or execution.get("host_profile_sha256") !=
            design["execution"]["host_profile"]["sha256"]
            or not isinstance(execution.get("review_record_source_path"), str)
            or not Path(execution["review_record_source_path"]).is_absolute()
            or not isinstance(execution.get("boot_id"), str)
            or not execution["boot_id"]
            or execution.get("child_environment") != {
                **harness.FIXED_CHILD_ENVIRONMENT,
                "INVOCATION_ID": manifest["systemd_invocation_id"],
                "SHENGJI_FAST": "1", "SHENGJI_REQUIRE_VOIDS": "1",
                "PERF_AB_DESIGN_SHA256": expected_design_sha,
                "PERF_EXPERIMENT_ID": harness.EXPERIMENT_ID,
            }
            or not isinstance(execution.get("started_unix_ns"), int)
            or isinstance(execution.get("started_unix_ns"), bool)
            or not isinstance(execution.get("finished_arms_unix_ns"), int)
            or isinstance(execution.get("finished_arms_unix_ns"), bool)
            or execution["finished_arms_unix_ns"] < execution["started_unix_ns"]):
        raise BundleRefused("execution record drift")
    expected_sequence = [
        (seed, label)
        for seed, order in zip(
            harness.PAIR_SEEDS, harness.PAIR_ORDERS, strict=True)
        for label in order.split("_")
    ]
    sequence = execution["arm_sequence"]
    if not isinstance(sequence, list) or len(sequence) != 12:
        raise BundleRefused("execution arm sequence drift")
    previous_finished = None
    for index, (entry, (seed, label)) in enumerate(
            zip(sequence, expected_sequence, strict=True)):
        if (not isinstance(entry, dict) or set(entry) != {
                "sequence_index", "seed", "label", "started_monotonic_ns",
                "finished_monotonic_ns", "returncode"}
                or entry.get("sequence_index") != index
                or entry.get("seed") != seed or entry.get("label") != label
                or entry.get("returncode") != 0
                or not isinstance(entry.get("started_monotonic_ns"), int)
                or isinstance(entry.get("started_monotonic_ns"), bool)
                or not isinstance(entry.get("finished_monotonic_ns"), int)
                or isinstance(entry.get("finished_monotonic_ns"), bool)
                or entry["finished_monotonic_ns"] <
                entry["started_monotonic_ns"]
                or (previous_finished is not None and
                    entry["started_monotonic_ns"] < previous_finished)):
            raise BundleRefused("execution arm sequence drift")
        previous_finished = entry["finished_monotonic_ns"]

    identities: dict[str, Any] = {}
    for label in ("base", "head"):
        identity = load_json(root / f"{label}.identity.json")
        expected = design[label]
        if (not isinstance(identity, dict)
                or identity != {key: expected[key]
                        for key in ("git", "source_sha256s", "native")}):
            raise BundleRefused(f"{label} identity record drift")
        _validate_source_archive(
            root / f"{label}.source.tar", identity["source_sha256s"])
        if sha256_file(root / f"{label}.native.bin") != \
                identity["native"]["sha256"]:
            raise BundleRefused(f"{label} native binary drift")
        identities[label] = identity

    rows = []
    for seed, order in zip(
            harness.PAIR_SEEDS, harness.PAIR_ORDERS, strict=True):
        row: dict[str, Any] = {"seed": seed, "order": order}
        normalized: dict[str, bytes] = {}
        for label in ("base", "head"):
            stem = f"seed-{seed}.{label}"
            raw_path = root / f"{stem}.raw.json"
            normalized_path = root / f"{stem}.normalized.json"
            stdout_path = root / f"{stem}.stdout.jsonl"
            stderr_path = root / f"{stem}.stderr.log"
            if stderr_path.stat().st_size:
                raise BundleRefused(f"{stem} has nonempty stderr")
            lines = stdout_path.read_bytes().splitlines()
            if len(lines) != 1:
                raise BundleRefused(f"{stem} stdout line count drift")
            try:
                summary = harness.load_json_bytes(lines[0])
                raw_bytes = raw_path.read_bytes()
                value = harness.load_json_bytes(raw_bytes)
                validation = harness.validate_arm_semantics(value, design, seed)
                normalized_bytes, removals = harness.normalize_arm(value)
            except Exception as exc:
                raise BundleRefused(f"{stem} semantic refusal: {exc}") from exc
            if (set(summary) != {
                    "elapsed_ns", "semantic_bytes", "semantic_sha256",
                    "history_plays", "searched_decisions",
                    "forced_no_search_decisions", "engine_adjusted_plays",
                    "searched_decisions_by_seat",
                    "forced_no_search_decisions_by_seat",
                    "engine_adjusted_plays_by_seat"}
                    or not isinstance(summary["elapsed_ns"], int)
                    or isinstance(summary["elapsed_ns"], bool)
                    or summary["elapsed_ns"] <= 0
                    or summary["semantic_bytes"] != len(raw_bytes)
                    or summary["semantic_sha256"] !=
                    hashlib.sha256(raw_bytes).hexdigest()
                    or any(summary.get(key) != observed
                           for key, observed in validation.items())
                    or normalized_path.read_bytes() != normalized_bytes):
                raise BundleRefused(f"{stem} summary/semantic drift")
            normalized[label] = normalized_bytes
            row[label] = {
                "elapsed_ns": summary["elapsed_ns"],
                "raw_semantic_sha256": hashlib.sha256(raw_bytes).hexdigest(),
                "raw_semantic_bytes": len(raw_bytes),
                "normalized_semantic_sha256":
                    hashlib.sha256(normalized_bytes).hexdigest(),
                "normalized_semantic_bytes": len(normalized_bytes),
                "normalization_removals": removals,
                "stdout_sha256": sha256_file(stdout_path),
                "stderr_sha256": sha256_file(stderr_path),
                **validation,
            }
        if normalized["base"] != normalized["head"]:
            raise BundleRefused(f"seed {seed} normalized semantics diverged")
        if (row["base"]["normalization_removals"] !=
                row["head"]["normalization_removals"]):
            raise BundleRefused(f"seed {seed} normalization counts diverged")
        row["normalized_semantics_exact"] = True
        rows.append(row)

    expected_result = harness.build_result(
        design, expected_design_sha, review_sha,
        manifest["systemd_invocation_id"], sha256_file(root / "execution.json"),
        identities, rows)
    if load_json(root / "result.json") != expected_result:
        raise BundleRefused("recorded result differs from reopened raw evidence")
    return {
        "status": "VERIFIED",
        "schema": manifest["schema"],
        "design_sha256": expected_design_sha,
        "manifest_sha256": expected_manifest_sha,
        "result_sha256": sha256_file(root / "result.json"),
        "decision": expected_result["decision"],
        "aggregate_wall_reduction_percent":
            expected_result["aggregate"]["wall_reduction_percent"],
        "paired_one_sided_95_lcb_percent":
            expected_result["paired"]["one_sided_95_lcb_percent"],
    }


def main() -> None:
    if len(sys.argv) != 4:
        raise SystemExit(
            "usage: validate_report_lcb_perf_bundle.py "
            "BUNDLE EXPECTED_DESIGN_SHA256 EXPECTED_MANIFEST_SHA256")
    print(json.dumps(
        validate_bundle(Path(sys.argv[1]), sys.argv[2], sys.argv[3]),
        sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except BundleRefused as exc:
        raise SystemExit(f"REFUSED: {exc}") from exc
