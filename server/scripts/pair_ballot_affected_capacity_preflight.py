#!/usr/bin/env python3
"""Freeze and run one score-free Pair V3 capacity preflight.

The reviewed capacity design fixes the full 1,024-state DEV/CALIB workload,
but authorizes only implementation of this controller.  Freezing a packet
requires the exact external design marker; executing the six-state sizing
sample requires a second, packet-specific marker.  The preflight computes the
normal evaluator internally, validates it, immediately discards every action
and utility, and publishes only timing, work, sampler and selector-dose counts.

No command in this module can run the full scored exploration or access REPORT.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import copy
import hashlib
import json
import math
import multiprocessing
import os
import platform
import secrets
import stat
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Callable


SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[1]
REPO = SERVER.parent
sys.path.insert(0, str(SCRIPT.parent))

import pair_ballot_affected_aggregate as AGG  # noqa: E402
import pair_ballot_affected_capacity_design as DESIGN  # noqa: E402
import pair_ballot_affected_eval as EVAL  # noqa: E402
import pair_ballot_affected_states as STATES  # noqa: E402
from shengji.engine import combos, fast  # noqa: E402


DESIGN_GIT = "373de8429261d7271b98f4d427760412cea930e2"
DESIGN_REVIEW_GIT = "d6db827b4d52ddb0860e50e4f5145a5e4cbb9c7c"
DESIGN_REVIEW_PARENT_GIT = "9191cbf8ecf0f363cc9b1e873f2ff2a36d71b51f"
CANONICAL_REVIEW_REF = "origin/main"
REVIEW_LEDGER = "HANDOFF_REVIEW.md"
REVIEWER_NAME = "Claude"
REVIEWER_EMAIL = "noreply@anthropic.com"
REVIEWER_SESSION_TRAILER = "Claude-Session: https://claude.ai/code/session_"
DESIGN_REVIEW_PREFIX = "PAIR_BALLOT_AFFECTED_CAPACITY_DESIGN_V1_REVIEW "
PACKET_REVIEW_PREFIX = (
    "PAIR_BALLOT_AFFECTED_CAPACITY_PREFLIGHT_PACKET_V1_REVIEW "
)
PACKET_SCHEMA = "pair-ballot-affected-capacity-preflight-packet-v1"
ADMISSION_SCHEMA = "pair-ballot-affected-capacity-preflight-admission-v1"
RESULT_SCHEMA = "pair-ballot-affected-capacity-preflight-result-v1"
RUN_ID = "pair-ballot-affected-capacity-preflight-v1"
NAMESPACE = SERVER / "runs/logs" / RUN_ID
PACKET_PATH = NAMESPACE / "controller-packet.json"
DESIGN_REVIEW_PATH = NAMESPACE / "design-review-snapshot.md"
PACKET_REVIEW_PATH = NAMESPACE / "packet-review-snapshot.md"
ADMISSION_PATH = SERVER / "runs/locks" / f"{RUN_ID}.admission.consumed.json"
RESULT_PATH = NAMESPACE / "capacity.json"

# One defender row from every split/band cell, then one row in every remaining
# logical lane.  Running all 16 simultaneously measures the saturated host
# shape the scored schedule would actually use.  Six serial states would
# measure neither 16-way contention nor every lane and are not a capacity gate.
PREFLIGHT_CELLS = (
    ("dev", "early"), ("calib", "early"),
    ("dev", "mid"), ("calib", "mid"),
    ("dev", "late"), ("calib", "late"),
)
PREFLIGHT_STATES = DESIGN.SHARD_COUNT
THROUGHPUT_SAFETY_FACTOR = 2.0
MIN_CPUS = 16
MIN_MEMORY_BYTES = 30 * (1 << 30)

FORBIDDEN_RESULT_KEYS = frozenset({
    "action", "actions", "attacker_points", "banker", "cards", "estimands",
    "external_report", "history", "level_change", "level_utility",
    "mean_acting_level_utility", "outcomes", "payoff", "payoffs", "points",
    "raw_attacker_points", "raw_points", "records", "regret", "regrets",
    "reward", "rewards", "score", "scores", "utility", "winner",
    "winner_index", "winner_team", "won",
})


class CapacityPreflightRefused(RuntimeError):
    """The packet, review authority, runtime or score-free boundary drifted."""


def canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"))
            + "\n").encode()


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def sha256_file(path: str | os.PathLike) -> str:
    value = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            value.update(chunk)
    return value.hexdigest()


def is_sha256(value: object) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(char in "0123456789abcdef" for char in value))


def require_regular_unlinked(path: Path, *, label: str) -> None:
    partial = Path(str(path) + ".partial")
    try:
        info = path.lstat()
    except FileNotFoundError as exc:
        raise CapacityPreflightRefused(f"{label} is missing") from exc
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or os.path.lexists(partial)):
        raise CapacityPreflightRefused(
            f"{label} is linked, nonregular, or partial")


def write_exclusive(path: Path, payload: object) -> None:
    partial = Path(str(path) + ".partial")
    if os.path.lexists(path) or os.path.lexists(partial):
        raise CapacityPreflightRefused(f"refusing existing output {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = canonical(payload)
    with partial.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    if json.loads(partial.read_bytes()) != payload:
        raise CapacityPreflightRefused("exclusive partial failed exact reopen")
    os.link(partial, path)
    partial.unlink()
    if path.read_bytes() != raw:
        raise CapacityPreflightRefused("published artifact differs from bytes")


def write_bytes_exclusive(path: Path, raw: bytes) -> None:
    partial = Path(str(path) + ".partial")
    if os.path.lexists(path) or os.path.lexists(partial):
        raise CapacityPreflightRefused(f"refusing existing output {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with partial.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    os.link(partial, path)
    partial.unlink()
    if path.read_bytes() != raw:
        raise CapacityPreflightRefused("published bytes differ from source")


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, check=True, capture_output=True,
        text=True).stdout.strip()


def git_bytes(*args: str) -> bytes:
    return subprocess.run(
        ["git", *args], cwd=REPO, check=True, capture_output=True).stdout


def _canonical_marker(prefix: str, claim: dict) -> bytes:
    return prefix.encode("utf-8") + canonical(claim)


def canonical_review_record(*, commit: str, prefix: str, expected: dict,
                            label: str, expected_parent: str | None = None,
                            canonical_ref: str = CANONICAL_REVIEW_REF
                            ) -> tuple[dict, bytes]:
    """Authenticate a reviewer-introduced marker on canonical main.

    Matching JSON is not authority: request templates contain the same bytes.
    The raw marker must first appear in a canonical-main commit authored and
    committed by the independent reviewer, with the normal session trailer.
    This guards against the PR #74 self-admission failure class.

    Git identity is not a cryptographic signature.  It does, however, make the
    independent actor boundary fail closed against the honest process errors
    this repository's review protocol is designed to catch.  The canonical
    remote-ref check additionally prevents a locally forged, unpushed commit
    from being consumed as authority.
    """
    if (not isinstance(commit, str) or len(commit) != 40
            or any(char not in "0123456789abcdef" for char in commit)):
        raise CapacityPreflightRefused(f"{label} commit is not a full Git SHA")
    try:
        if subprocess.run(
                ["git", "merge-base", "--is-ancestor", commit, canonical_ref],
                cwd=REPO, capture_output=True).returncode != 0:
            raise CapacityPreflightRefused(
                f"{label} commit is not on canonical main")
        parents = git("show", "-s", "--format=%P", commit).split()
        if len(parents) != 1:
            raise CapacityPreflightRefused(
                f"{label} commit must have exactly one parent")
        parent = parents[0]
        if expected_parent is not None and parent != expected_parent:
            raise CapacityPreflightRefused(f"{label} parent commit drift")
        identity = {
            "author_name": git("show", "-s", "--format=%an", commit),
            "author_email": git("show", "-s", "--format=%ae", commit),
            "committer_name": git("show", "-s", "--format=%cn", commit),
            "committer_email": git("show", "-s", "--format=%ce", commit),
        }
        if identity != {
                "author_name": REVIEWER_NAME,
                "author_email": REVIEWER_EMAIL,
                "committer_name": REVIEWER_NAME,
                "committer_email": REVIEWER_EMAIL}:
            raise CapacityPreflightRefused(
                f"{label} was not introduced by the independent reviewer")
        if REVIEWER_SESSION_TRAILER not in git(
                "show", "-s", "--format=%B", commit):
            raise CapacityPreflightRefused(
                f"{label} reviewer session provenance is missing")
        changed = git(
            "diff-tree", "--no-commit-id", "--name-only", "-r", commit
        ).splitlines()
        if changed != [REVIEW_LEDGER]:
            raise CapacityPreflightRefused(
                f"{label} commit changed files beyond the review ledger")
        current = git_bytes("show", f"{commit}:{REVIEW_LEDGER}")
        previous = git_bytes("show", f"{parent}:{REVIEW_LEDGER}")
    except subprocess.CalledProcessError as exc:
        raise CapacityPreflightRefused(
            f"cannot authenticate {label} commit") from exc

    marker = _canonical_marker(prefix, expected)
    current_matches = [line for line in current.splitlines(keepends=True)
                       if line.startswith(prefix.encode("utf-8"))]
    previous_matches = [line for line in previous.splitlines(keepends=True)
                        if line.startswith(prefix.encode("utf-8"))]
    if current_matches != [marker] or previous_matches:
        raise CapacityPreflightRefused(
            f"{label} marker was not introduced exactly once by its review commit")
    return {
        "commit": commit,
        "parent_commit": parent,
        "canonical_ref": canonical_ref,
        "ledger_blob_sha256": sha256_file_from_bytes(current),
        "marker_sha256": sha256_file_from_bytes(marker),
        "claim": expected,
    }, marker


def sha256_file_from_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def require_exact_clean_git(expected_git: str) -> None:
    if (not isinstance(expected_git, str) or len(expected_git) != 40
            or any(char not in "0123456789abcdef" for char in expected_git)
            or git("rev-parse", "HEAD") != expected_git
            or git("status", "--porcelain", "--untracked-files=all")):
        raise CapacityPreflightRefused("execution requires exact clean git")
    if subprocess.run(
            ["git", "merge-base", "--is-ancestor", DESIGN_GIT, expected_git],
            cwd=REPO, capture_output=True).returncode != 0:
        raise CapacityPreflightRefused("reviewed design is not an ancestor")


def expected_design_review_claim() -> dict:
    return {
        "attacker_rows_descriptive_only": True,
        "capacity_preflight_execution_authorized": False,
        "capacity_preflight_implementation_authorized": True,
        "champion_natural_role_dose_required": True,
        "cluster_unit": "deal_seed",
        "combined_dev_calib_primary": True,
        "defender_deal_clusters": DESIGN.DEFENDER_DEAL_CLUSTERS,
        "defender_membership_sha256":
            DESIGN.REVIEWED_DEFENDER_MEMBERSHIP_SHA256,
        "defender_rows": DESIGN.DEFENDER_ROWS,
        "design_file_sha256": (
            "be21b547659e49399dbaf7ea732c4a6a94f953c59c197765112e12d366dbf439"),
        "design_internal_sha256": (
            "cd8ada0d53c914adf9862171bcbf8308496129e3b1d66e63fee0a6efe4ac4f9d"),
        "design_source_sha256": (
            "caa2d0d9c5580c56828e72c39e3e5ad0cf5be0d3eb7a8a77603e31c73e786317"),
        "git": DESIGN_GIT,
        "identity_membership_sha256":
            DESIGN.REVIEWED_IDENTITY_MEMBERSHIP_SHA256,
        "mde_at_target_power": 0.040889289223836306,
        "parent_git": DESIGN.PARENT_REVIEW_GIT,
        "population_sha256": DESIGN.POPULATION_FILE_SHA256,
        "power_at_worthwhile_effect": 0.9186636345219327,
        "production_deployment": False,
        "production_promotion": False,
        "python_311_312_314_byte_identical": True,
        "report_access_authorized": False,
        "schema": "pair-ballot-affected-capacity-design-review-v1",
        "scored_evaluation_authorized": False,
        "selection_sha256": DESIGN.REVIEWED_SELECTION_SHA256,
        "smartbot_trajectory_dose_only": True,
        "states": 1_024,
        "strength_claim": False,
        "test_sha256": (
            "bc103baa97a6deffa68c4bbcec82c0697c54a0521c9842d72fd683f45aa904dc"),
        "training_authorized": False,
        "verdict": "PASS",
    }


def memory_bytes() -> int:
    try:
        pages = int(os.sysconf("SC_PHYS_PAGES"))
        page_size = int(os.sysconf("SC_PAGE_SIZE"))
    except (OSError, ValueError):
        return 0
    return pages * page_size


def runtime_snapshot() -> dict:
    fast_binary = getattr(fast, "_fast", None)
    fast_path = None if fast_binary is None else Path(fast_binary.__file__).resolve()
    return {
        "host": platform.node(),
        "machine": platform.machine().lower(),
        "python": platform.python_version(),
        "python_executable": str(Path(sys.executable).resolve()),
        "cpu_count": int(os.cpu_count() or 0),
        "memory_bytes": memory_bytes(),
        "fast_required": os.environ.get("SHENGJI_FAST") == "1",
        "strict_voids_required":
            os.environ.get("SHENGJI_REQUIRE_VOIDS") == "1",
        "fast_binary_sha256": (
            sha256_file(fast_path) if fast_path is not None else None),
    }


def runtime_problems(runtime: object) -> list[str]:
    if not isinstance(runtime, dict) or set(runtime) != {
            "host", "machine", "python", "python_executable", "cpu_count",
            "memory_bytes", "fast_required", "strict_voids_required",
            "fast_binary_sha256"}:
        return ["runtime field population"]
    problems = []
    if runtime["machine"] not in {"x86_64", "amd64"}:
        problems.append("runtime is not x86-64")
    if runtime["cpu_count"] < MIN_CPUS:
        problems.append("runtime has fewer than 16 CPUs")
    if runtime["memory_bytes"] < MIN_MEMORY_BYTES:
        problems.append("runtime has less than 30 GiB memory")
    if runtime["fast_required"] is not True:
        problems.append("runtime does not require compiled routing")
    if runtime["strict_voids_required"] is not True:
        problems.append("runtime does not require strict voids")
    if not is_sha256(runtime["fast_binary_sha256"]):
        problems.append("runtime fast binary is unauthenticated")
    if (not runtime["host"] or not runtime["python"]
            or not runtime["python_executable"]):
        problems.append("runtime identity is incomplete")
    return sorted(set(problems))


def require_qualified_runtime() -> dict:
    runtime = runtime_snapshot()
    problems = runtime_problems(runtime)
    if not fast.HAVE_FAST or combos.decompose is not fast.decompose:
        problems.append("runtime is not compiled strict routing")
    if problems:
        raise CapacityPreflightRefused("; ".join(problems))
    return runtime


def require_systemd_scope() -> str:
    """Require a cgroup-owned launch so interrupted spawn workers cannot orphan."""
    invocation = os.environ.get("INVOCATION_ID")
    if (not isinstance(invocation, str) or len(invocation) != 32
            or any(char not in "0123456789abcdef" for char in invocation)):
        raise CapacityPreflightRefused(
            "preflight execution requires a systemd-owned cgroup")
    return invocation


def load_population(path: Path) -> dict:
    payload = EVAL.load_population(path)
    if (sha256_file(path) != DESIGN.POPULATION_FILE_SHA256
            or payload.get("artifact_sha256")
            != DESIGN.POPULATION_ARTIFACT_SHA256):
        raise CapacityPreflightRefused("reviewed population identity drift")
    return payload


def preflight_manifest(population: dict) -> list[dict]:
    selected: list[dict] = []
    used_deals: set[int] = set()
    used_lanes: set[int] = set()

    def add(row: dict, *, split: str, band: str) -> None:
        deal_seed = int(row["deal_seed"])
        lane = deal_seed % DESIGN.SHARD_COUNT
        used_deals.add(deal_seed)
        used_lanes.add(lane)
        selected.append({
            "state_id": row["state_id"],
            "state_sha256": row["state_sha256"],
            "deal_seed": deal_seed,
            "split": split,
            "band": band,
            "role": "defender",
            "lane_index": lane,
        })

    for split, band in PREFLIGHT_CELLS:
        candidates = sorted(
            (row for row in population["states"]
             if row.get("split") == split and row.get("band") == band
             and row.get("role") == "defender"
             and row.get("search_eligible") is True),
            key=lambda row: (
                int(row["deal_seed"]), int(row["trick"]), int(row["seat"]),
                str(row["state_id"])))
        row = next(
            (candidate for candidate in candidates
             if int(candidate["deal_seed"]) not in used_deals
             and int(candidate["deal_seed"]) % DESIGN.SHARD_COUNT
             not in used_lanes), None)
        if row is None:
            raise CapacityPreflightRefused(
                f"no distinct defender/lane preflight row for {split}/{band}")
        add(row, split=split, band=band)

    all_candidates = sorted(
        (row for row in population["states"]
         if row.get("split") in DESIGN.SPLITS
         and row.get("band") in DESIGN.BANDS
         and row.get("role") == "defender"
         and row.get("search_eligible") is True),
        key=lambda row: (
            int(row["deal_seed"]), int(row["trick"]), int(row["seat"]),
            str(row["state_id"])))
    for lane in range(DESIGN.SHARD_COUNT):
        if lane in used_lanes:
            continue
        row = next(
            (candidate for candidate in all_candidates
             if int(candidate["deal_seed"]) % DESIGN.SHARD_COUNT == lane
             and int(candidate["deal_seed"]) not in used_deals), None)
        if row is None:
            raise CapacityPreflightRefused(
                f"no distinct defender row for logical lane {lane}")
        add(row, split=row["split"], band=row["band"])

    if (len(selected) != PREFLIGHT_STATES
            or len(used_deals) != PREFLIGHT_STATES
            or used_lanes != set(range(DESIGN.SHARD_COUNT))
            or not set(PREFLIGHT_CELLS).issubset(
                {(row["split"], row["band"]) for row in selected})):
        raise CapacityPreflightRefused("preflight state population drift")
    return selected


def design_ref(design_path: Path, population_path: Path) -> tuple[dict, dict]:
    design = DESIGN.verify_design(population_path, design_path)
    raw_sha = sha256_file(design_path)
    if (raw_sha != expected_design_review_claim()["design_file_sha256"]
            or design["design_sha256"]
            != expected_design_review_claim()["design_internal_sha256"]):
        raise CapacityPreflightRefused("reviewed capacity design identity drift")
    return design, {
        "path": str(design_path),
        "sha256": raw_sha,
        "internal_sha256": design["design_sha256"],
        "reviewed_git": DESIGN_GIT,
    }


def packet_payload(*, expected_git: str, population_path: Path,
                   design_path: Path, runtime: dict | None = None) -> dict:
    design, design_reference = design_ref(design_path, population_path)
    population = load_population(population_path)
    design_review, _marker = canonical_review_record(
        commit=DESIGN_REVIEW_GIT, prefix=DESIGN_REVIEW_PREFIX,
        expected=expected_design_review_claim(),
        expected_parent=DESIGN_REVIEW_PARENT_GIT,
        label="Pair V3 design review")
    observed_runtime = require_qualified_runtime() if runtime is None else runtime
    problems = runtime_problems(observed_runtime)
    if problems:
        raise CapacityPreflightRefused("; ".join(problems))
    manifest = preflight_manifest(population)
    payload = {
        "schema": PACKET_SCHEMA,
        "run_id": RUN_ID,
        "git": expected_git,
        "design": design_reference,
        "design_review": design_review,
        "population": {
            "path": str(population_path),
            "sha256": DESIGN.POPULATION_FILE_SHA256,
            "artifact_sha256": DESIGN.POPULATION_ARTIFACT_SHA256,
            "report_permitted": False,
        },
        "runtime": observed_runtime,
        "preflight": {
            "selection_rule": (
                "first distinct defender deal/lane in each split/band cell, "
                "then first distinct defender deal in every remaining lane"),
            "states": manifest,
            "state_count": PREFLIGHT_STATES,
            "selection_sha256": digest(manifest),
            "saturated_parallel_lanes": DESIGN.SHARD_COUNT,
            "report_worlds": EVAL.REPORT_WORLDS,
            "outcomes_computed_in_memory": True,
            "outcomes_discarded": True,
            "outcomes_published": False,
            "capacity_only_no_effect_estimate": True,
            "systemd_scope_required": True,
        },
        "projection": {
            "target_states": design["selection"]["states"],
            "target_states_by_band": design["selection"]["states_by_band"],
            "logical_lanes": DESIGN.SHARD_COUNT,
            "max_fleet_hours": DESIGN.MAX_FLEET_HOURS,
            "max_lane_wall_hours": DESIGN.MAX_LANE_WALL_HOURS,
            "throughput_safety_factor": THROUGHPUT_SAFETY_FACTOR,
            "normalize_each_timing_to_max_work": True,
        },
        "authority": {
            "one_score_free_preflight_execution_authorized": False,
            "capacity_result_review_authorized": True,
            "scored_packet_design_authorized": False,
            "scored_evaluation_authorized": False,
            "report_access_authorized": False,
            "strength_claim": False,
            "training_authorized": False,
            "production_promotion": False,
            "production_deployment": False,
        },
    }
    payload["internal_sha256"] = digest(payload)
    return payload


def packet_review_claim(*, expected_git: str, packet_sha256: str,
                        packet_internal_sha256: str) -> dict:
    return {
        "git": expected_git,
        "independent_review": True,
        "one_score_free_preflight_authorized": True,
        "packet_internal_sha256": packet_internal_sha256,
        "packet_sha256": packet_sha256,
        "production_deployment": False,
        "production_promotion": False,
        "report_access_authorized": False,
        "run_id": RUN_ID,
        "schema": "pair-ballot-affected-capacity-preflight-packet-review-v1",
        "scored_evaluation_authorized": False,
        "strength_claim": False,
        "training_authorized": False,
        "verdict": "PASS",
    }


def packet_problems(packet: object, *, expected_git: str,
                    population_path: Path, design_path: Path) -> list[str]:
    try:
        if not isinstance(packet, dict):
            return ["packet is not an object"]
        expected = packet_payload(
            expected_git=expected_git, population_path=population_path,
            design_path=design_path,
            runtime=copy.deepcopy(packet.get("runtime")))
    except Exception as exc:
        return [f"cannot reconstruct packet: {type(exc).__name__}: {exc}"]
    return [] if packet == expected else ["packet differs from reconstruction"]


def load_packet(path: Path, expected_sha256: str, *, expected_git: str,
                population_path: Path, design_path: Path) -> dict:
    require_regular_unlinked(path, label="Pair V3 preflight packet")
    if not is_sha256(expected_sha256) or sha256_file(path) != expected_sha256:
        raise CapacityPreflightRefused("preflight packet SHA-256 drift")
    try:
        packet = json.loads(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise CapacityPreflightRefused("preflight packet unreadable") from exc
    problems = packet_problems(
        packet, expected_git=expected_git, population_path=population_path,
        design_path=design_path)
    if problems:
        raise CapacityPreflightRefused("; ".join(problems))
    return packet


def score_free_result_problems(value: object,
                               *, design: dict | None = None) -> list[str]:
    problems: list[str] = []

    def walk(item: object, path: str) -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                if key in FORBIDDEN_RESULT_KEYS:
                    problems.append(f"forbidden outcome field {path}{key}")
                walk(child, f"{path}{key}.")
        elif isinstance(item, list):
            for index, child in enumerate(item):
                walk(child, f"{path}{index}.")

    walk(value, "")
    if (not isinstance(value, dict)
            or value.get("score_free") is not True
            or value.get("outcomes_published") is not False):
        problems.append("score-free identity")
    if not isinstance(value, dict) or value.get("schema") != RESULT_SCHEMA:
        return sorted(set(problems))

    base_fields = {
        "schema", "run_id", "git", "complete", "score_free",
        "outcomes_computed_in_memory", "outcomes_discarded",
        "outcomes_published", "records_discarded",
        "capacity_only_no_effect_estimate", "saturated_parallel_lanes",
        "packet_internal_sha256", "runtime", "timing_rows", "work_totals",
        "sampler_totals", "selector_dose", "projection", "criteria",
        "status", "scored_packet_design_authorized",
        "scored_evaluation_authorized", "report_access_authorized",
        "strength_claim", "training_authorized", "production_promotion",
        "production_deployment", "retry_or_extension_authorized",
    }
    allowed_shapes = {
        frozenset(base_fields),
        frozenset(base_fields | {"internal_sha256"}),
        frozenset(base_fields | {
            "admission_sha256", "packet_sha256", "internal_sha256"}),
    }
    if frozenset(value) not in allowed_shapes:
        problems.append("capacity result top-level field population")
        return sorted(set(problems))
    if (value.get("run_id") != RUN_ID or value.get("complete") is not True
            or value.get("outcomes_computed_in_memory") is not True
            or value.get("outcomes_discarded") is not True
            or value.get("records_discarded") != PREFLIGHT_STATES
            or value.get("capacity_only_no_effect_estimate") is not True
            or value.get("saturated_parallel_lanes") != DESIGN.SHARD_COUNT
            or not isinstance(value.get("git"), str)
            or len(value["git"]) != 40
            or any(char not in "0123456789abcdef" for char in value["git"])
            or not is_sha256(value.get("packet_internal_sha256"))):
        problems.append("capacity result identity")

    runtime = value.get("runtime")
    problems.extend(runtime_problems(runtime))
    timings = value.get("timing_rows")
    timing_fields = {
        "split", "band", "lane_index", "elapsed_seconds",
        "observed_candidate_world_rollouts", "normalized_max_work_seconds",
    }
    if (not isinstance(timings, list) or len(timings) != PREFLIGHT_STATES
            or any(not isinstance(row, dict) or set(row) != timing_fields
                   for row in timings)):
        problems.append("capacity timing row population")
    else:
        cells = Counter((row.get("split"), row.get("band")) for row in timings)
        if (not set(PREFLIGHT_CELLS).issubset(cells)
                or math.fsum(cells.values()) != PREFLIGHT_STATES):
            problems.append("capacity timing cell population")
        for row in timings:
            if (not isinstance(row["lane_index"], int)
                    or isinstance(row["lane_index"], bool)
                    or not 0 <= row["lane_index"] < DESIGN.SHARD_COUNT
                    or not isinstance(row["observed_candidate_world_rollouts"],
                                      int)
                    or isinstance(row["observed_candidate_world_rollouts"],
                                  bool)
                    or not (2 * DESIGN.POLICY_WORK_PER_STATE
                            + EVAL.REPORT_WORLDS)
                    <= row["observed_candidate_world_rollouts"]
                    <= DESIGN.MAX_WORK_PER_STATE
                    or (row["observed_candidate_world_rollouts"]
                        - 2 * DESIGN.POLICY_WORK_PER_STATE)
                    % EVAL.REPORT_WORLDS != 0
                    or not _positive_finite(row["elapsed_seconds"])
                    or not _positive_finite(
                        row["normalized_max_work_seconds"])
                    or not math.isclose(
                        row["normalized_max_work_seconds"],
                        row["elapsed_seconds"] * DESIGN.MAX_WORK_PER_STATE
                        / row["observed_candidate_world_rollouts"],
                        rel_tol=1e-12, abs_tol=1e-12)):
                problems.append("capacity timing row value")

    work = value.get("work_totals")
    if (not isinstance(work, dict) or set(work) != {
            "current_policy_rollouts", "retained_policy_rollouts",
            "external_comparison_rollouts"}
            or work.get("current_policy_rollouts")
            != PREFLIGHT_STATES * DESIGN.POLICY_WORK_PER_STATE
            or work.get("retained_policy_rollouts")
            != PREFLIGHT_STATES * DESIGN.POLICY_WORK_PER_STATE
            or not isinstance(work.get("external_comparison_rollouts"), int)
            or isinstance(work.get("external_comparison_rollouts"), bool)
            or not (PREFLIGHT_STATES * EVAL.REPORT_WORLDS
                    <= work["external_comparison_rollouts"]
                    <= PREFLIGHT_STATES * DESIGN.MAX_EXTERNAL_WORK_PER_STATE)
            or work["external_comparison_rollouts"]
            % EVAL.REPORT_WORLDS != 0):
        problems.append("capacity work totals")

    counters = value.get("sampler_totals")
    if (not isinstance(counters, dict)
            or set(counters) != set(AGG.COUNTER_FIELDS)
            or any(not isinstance(item, int) or isinstance(item, bool)
                   or item < 0 for item in counters.values())
            or counters.get("accepted_worlds")
            != PREFLIGHT_STATES * (
                2 * (DESIGN.SELECTION_WORLDS + DESIGN.POLICY_REPORT_WORLDS)
                + EVAL.REPORT_WORLDS)
            or counters.get("sample_attempts")
            != counters.get("accepted_worlds", 0)
            + counters.get("failed_worlds", 0)
            or counters.get("rejected_worlds", 0)
            > counters.get("failed_worlds", 0)
            or counters.get("impossible_worlds", 0)
            > counters.get("failed_worlds", 0)):
        problems.append("capacity sampler totals")

    dose = value.get("selector_dose")
    if (not isinstance(dose, dict) or set(dose) != {
            "policy_action_changes", "retained_raw_winner_insertions",
            "current_raw_winner_evictions"}
            or any(not isinstance(item, int) or isinstance(item, bool)
                   or not 0 <= item <= PREFLIGHT_STATES
                   for item in dose.values())):
        problems.append("capacity selector dose")

    projection = value.get("projection")
    if (not isinstance(projection, dict) or set(projection) != {
            "fleet_hours", "max_lane_wall_hours", "lane_wall_hours",
            "normalized_seconds_per_state_by_band", "target_states",
            "safety_factor"}):
        problems.append("capacity projection field population")
    else:
        seconds = projection["normalized_seconds_per_state_by_band"]
        lanes = projection["lane_wall_hours"]
        if (not isinstance(seconds, dict) or set(seconds) != set(DESIGN.BANDS)
                or any(not _positive_finite(item) for item in seconds.values())
                or not isinstance(lanes, list)
                or len(lanes) != DESIGN.SHARD_COUNT
                or any(not _positive_finite(item) for item in lanes)
                or not _positive_finite(projection["fleet_hours"])
                or not _positive_finite(projection["max_lane_wall_hours"])
                or not math.isclose(projection["max_lane_wall_hours"],
                                    max(lanes), rel_tol=1e-12, abs_tol=1e-12)
                or projection["target_states"] != 1_024
                or projection["safety_factor"] != THROUGHPUT_SAFETY_FACTOR):
            problems.append("capacity projection value")
        elif isinstance(timings, list) and len(timings) == PREFLIGHT_STATES:
            for band in DESIGN.BANDS:
                observed = [row["normalized_max_work_seconds"]
                            for row in timings if row.get("band") == band]
                if (not observed
                        or not math.isclose(
                            seconds[band], math.fsum(observed) / len(observed),
                            rel_tol=1e-12, abs_tol=1e-12)):
                    problems.append("capacity band projection reconstruction")
            if (not isinstance(design, dict)
                    or not isinstance(design.get("selection"), dict)
                    or not isinstance(design.get("schedule"), dict)
                    or not isinstance(design["schedule"].get("lanes"), list)):
                problems.append("capacity projection design is unavailable")
            else:
                expected_fleet = math.fsum(
                    seconds[band] * count for band, count in
                    design["selection"]["states_by_band"].items()
                ) * THROUGHPUT_SAFETY_FACTOR / 3_600
                expected_lanes = [
                    math.fsum(
                        seconds[band] * count for band, count in
                        lane["states_by_band"].items()
                    ) * THROUGHPUT_SAFETY_FACTOR / 3_600
                    for lane in design["schedule"]["lanes"]]
                if (not math.isclose(
                        projection["fleet_hours"], expected_fleet,
                        rel_tol=1e-12, abs_tol=1e-12)
                        or len(lanes) != len(expected_lanes)
                        or any(not math.isclose(
                            observed, expected, rel_tol=1e-12, abs_tol=1e-12)
                               for observed, expected in zip(
                                   lanes, expected_lanes, strict=True))):
                    problems.append("capacity projection math")

    criteria = value.get("criteria")
    if (not isinstance(criteria, dict) or set(criteria) != {
            "all_capacity_states_complete", "exact_evaluator_work_complete",
            "sampler_nonempty", "fleet_hours_le_cap",
            "max_lane_wall_hours_le_cap", "all"}
            or any(not isinstance(item, bool) for item in criteria.values())):
        problems.append("capacity criteria population")
    elif isinstance(projection, dict) and isinstance(counters, dict):
        expected_criteria = {
            "all_capacity_states_complete": (
                isinstance(timings, list)
                and len(timings) == PREFLIGHT_STATES
                and {row.get("lane_index") for row in timings}
                == set(range(DESIGN.SHARD_COUNT))),
            "exact_evaluator_work_complete": (
                isinstance(work, dict)
                and work.get("current_policy_rollouts")
                == PREFLIGHT_STATES * DESIGN.POLICY_WORK_PER_STATE
                and work.get("retained_policy_rollouts")
                == PREFLIGHT_STATES * DESIGN.POLICY_WORK_PER_STATE),
            "sampler_nonempty": counters.get("accepted_worlds", 0) > 0,
            "fleet_hours_le_cap": (
                _positive_finite(projection.get("fleet_hours"))
                and projection["fleet_hours"] <= DESIGN.MAX_FLEET_HOURS),
            "max_lane_wall_hours_le_cap": (
                _positive_finite(projection.get("max_lane_wall_hours"))
                and projection["max_lane_wall_hours"]
                <= DESIGN.MAX_LANE_WALL_HOURS),
        }
        expected_criteria["all"] = all(expected_criteria.values())
        if criteria != expected_criteria:
            problems.append("capacity criteria reconstruction")
        expected_status = ("AUTHORIZE_CAPACITY_RESULT_REVIEW"
                           if criteria["all"] else "HOLD")
        if value.get("status") != expected_status:
            problems.append("capacity status/criteria mismatch")

    for field in (
            "scored_packet_design_authorized", "scored_evaluation_authorized",
            "report_access_authorized", "strength_claim",
            "training_authorized", "production_promotion",
            "production_deployment", "retry_or_extension_authorized"):
        if value.get(field) is not False:
            problems.append(f"capacity authority escalation: {field}")
    for field in ("admission_sha256", "packet_sha256"):
        if field in value and not is_sha256(value[field]):
            problems.append(f"capacity {field} drift")
    if "internal_sha256" in value:
        body = dict(value)
        observed = body.pop("internal_sha256")
        if not is_sha256(observed) or observed != digest(body):
            problems.append("capacity result internal digest")
    return sorted(set(problems))


def _positive_finite(value: object) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(float(value)) and float(value) > 0)


def _sampler_totals(result: dict) -> dict:
    totals = Counter({name: 0 for name in AGG.COUNTER_FIELDS})
    for policy in ("current", "retained"):
        totals.update(result[policy]["sampler_counters"])
    totals.update(result["external_report"]["sampler"]["counters"])
    return dict(sorted(totals.items()))


def _measure_one_impl(expected: dict, row: dict, runtime: dict,
                      clock: Callable[[], float]) -> dict:
    if require_qualified_runtime() != runtime:
        raise CapacityPreflightRefused("preflight worker runtime drift")
    started = clock()
    result = EVAL.evaluate_state(row, report_worlds=EVAL.REPORT_WORLDS)
    elapsed = clock() - started
    if not math.isfinite(elapsed) or elapsed <= 0:
        raise CapacityPreflightRefused("preflight timing is not positive")
    AGG._validate_result(
        result, split=row["split"], report_worlds=EVAL.REPORT_WORLDS)
    AGG._validate_source_binding(result, row)
    work = result["candidate_world_work"]
    total_work = sum(int(value) for value in work.values())
    if (work["current_policy"] != DESIGN.POLICY_WORK_PER_STATE
            or work["retained_policy"] != DESIGN.POLICY_WORK_PER_STATE
            or work["external_report"] not in {
                EVAL.REPORT_WORLDS * count
                for count in range(1, DESIGN.MAX_EXTERNAL_ACTIONS + 1)}
            or total_work > DESIGN.MAX_WORK_PER_STATE):
        raise CapacityPreflightRefused("preflight exact work drift")
    measured = {
        "band": row["band"],
        "timing": {
            "split": row["split"], "band": row["band"],
            "lane_index": expected["lane_index"],
            "elapsed_seconds": elapsed,
            "observed_candidate_world_rollouts": total_work,
            "normalized_max_work_seconds": (
                elapsed * DESIGN.MAX_WORK_PER_STATE / total_work),
        },
        "work": dict(work),
        "sampler_totals": _sampler_totals(result),
        "selector_dose": {
            "policy_action_changes": int(result["policy_action_changed"]),
            "retained_raw_winner_insertions": int(
                result["retained_raw_winner_is_inserted"]),
            "current_raw_winner_evictions": int(
                result["current_raw_winner_was_evicted"]),
        },
    }
    del result
    return measured


def _measure_one(task: tuple[dict, dict, dict]) -> dict:
    return _measure_one_impl(*task, clock=time.perf_counter)


def measure_preflight(packet: dict, population_path: Path, *,
                      clock: Callable[[], float] = time.perf_counter,
                      parallel: bool = True) -> dict:
    population = load_population(population_path)
    rows = {row["state_id"]: row for row in population["states"]}
    elapsed_by_band: dict[str, list[float]] = defaultdict(list)
    sampler_totals = Counter({name: 0 for name in AGG.COUNTER_FIELDS})
    observed_work = Counter()
    selector_dose = Counter()
    tasks = []
    for expected in packet["preflight"]["states"]:
        row = rows.get(expected["state_id"])
        if row is None or any(row.get(name) != expected[name] for name in (
                "state_id", "state_sha256", "deal_seed", "split", "band",
                "role")):
            raise CapacityPreflightRefused("preflight state identity drift")
        if row["split"] not in EVAL.ALLOWED_SPLITS or row["role"] != "defender":
            raise CapacityPreflightRefused("preflight admitted forbidden row")
        tasks.append((expected, row, packet["runtime"]))

    if parallel:
        context = multiprocessing.get_context("spawn")
        with concurrent.futures.ProcessPoolExecutor(
                max_workers=DESIGN.SHARD_COUNT, mp_context=context) as pool:
            measurements = list(pool.map(_measure_one, tasks))
    else:
        measurements = [
            _measure_one_impl(*task, clock=clock) for task in tasks]
    timings = []
    for measured in measurements:
        elapsed_by_band[measured["band"]].append(
            measured["timing"]["normalized_max_work_seconds"])
        observed_work.update(measured["work"])
        sampler_totals.update(measured["sampler_totals"])
        selector_dose.update(measured["selector_dose"])
        timings.append(measured["timing"])

    if (len(timings) != PREFLIGHT_STATES
            or set(elapsed_by_band) != set(DESIGN.BANDS)
            or any(not values for values in elapsed_by_band.values())
            or {row["lane_index"] for row in timings}
            != set(range(DESIGN.SHARD_COUNT))):
        raise CapacityPreflightRefused("preflight cell completion drift")
    seconds_by_band = {
        band: math.fsum(values) / len(values)
        for band, values in sorted(elapsed_by_band.items())
    }
    design = DESIGN.build_design(population_path)
    target_seconds = math.fsum(
        seconds_by_band[band] * count
        for band, count in design["selection"]["states_by_band"].items())
    fleet_hours = (
        target_seconds * THROUGHPUT_SAFETY_FACTOR / 3_600)
    lane_hours = []
    for lane in design["schedule"]["lanes"]:
        seconds = math.fsum(
            seconds_by_band[band] * count
            for band, count in lane["states_by_band"].items())
        lane_hours.append(seconds * THROUGHPUT_SAFETY_FACTOR / 3_600)
    projection = {
        "fleet_hours": fleet_hours,
        "max_lane_wall_hours": max(lane_hours),
        "lane_wall_hours": lane_hours,
        "normalized_seconds_per_state_by_band": seconds_by_band,
        "target_states": design["selection"]["states"],
        "safety_factor": THROUGHPUT_SAFETY_FACTOR,
    }
    criteria = {
        "all_capacity_states_complete": len(timings) == PREFLIGHT_STATES,
        "exact_evaluator_work_complete": (
            observed_work["current_policy"]
            == PREFLIGHT_STATES * DESIGN.POLICY_WORK_PER_STATE
            and observed_work["retained_policy"]
            == PREFLIGHT_STATES * DESIGN.POLICY_WORK_PER_STATE),
        "sampler_nonempty": sampler_totals["accepted_worlds"] > 0,
        "fleet_hours_le_cap": fleet_hours <= DESIGN.MAX_FLEET_HOURS,
        "max_lane_wall_hours_le_cap": (
            max(lane_hours) <= DESIGN.MAX_LANE_WALL_HOURS),
    }
    criteria["all"] = all(criteria.values())
    payload = {
        "schema": RESULT_SCHEMA,
        "run_id": RUN_ID,
        "git": packet["git"],
        "complete": True,
        "score_free": True,
        "outcomes_computed_in_memory": True,
        "outcomes_discarded": True,
        "outcomes_published": False,
        "records_discarded": PREFLIGHT_STATES,
        "capacity_only_no_effect_estimate": True,
        "saturated_parallel_lanes": DESIGN.SHARD_COUNT,
        "packet_internal_sha256": packet["internal_sha256"],
        "runtime": packet["runtime"],
        "timing_rows": timings,
        "work_totals": {
            "current_policy_rollouts": observed_work["current_policy"],
            "retained_policy_rollouts": observed_work["retained_policy"],
            "external_comparison_rollouts": observed_work["external_report"],
        },
        "sampler_totals": dict(sorted(sampler_totals.items())),
        "selector_dose": dict(sorted(selector_dose.items())),
        "projection": projection,
        "criteria": criteria,
        "status": ("AUTHORIZE_CAPACITY_RESULT_REVIEW"
                   if criteria["all"] else "HOLD"),
        "scored_packet_design_authorized": False,
        "scored_evaluation_authorized": False,
        "report_access_authorized": False,
        "strength_claim": False,
        "training_authorized": False,
        "production_promotion": False,
        "production_deployment": False,
        "retry_or_extension_authorized": False,
    }
    problems = score_free_result_problems(payload, design=design)
    if problems:
        raise CapacityPreflightRefused("; ".join(problems))
    payload["internal_sha256"] = digest(payload)
    return payload


def freeze_command(args: argparse.Namespace) -> None:
    require_exact_clean_git(args.expected_git)
    if Path(args.out).resolve() != PACKET_PATH.resolve():
        raise CapacityPreflightRefused("packet output path is not canonical")
    packet = packet_payload(
        expected_git=args.expected_git,
        population_path=Path(args.population).resolve(),
        design_path=Path(args.design).resolve())
    collisions = [path for path in (PACKET_PATH, DESIGN_REVIEW_PATH)
                  if os.path.lexists(path) or os.path.lexists(str(path) + ".partial")]
    if collisions:
        raise CapacityPreflightRefused("preflight freeze slot already consumed")
    marker = _canonical_marker(
        DESIGN_REVIEW_PREFIX, expected_design_review_claim())
    if sha256_file_from_bytes(marker) != packet["design_review"][
            "marker_sha256"]:
        raise CapacityPreflightRefused("design review marker snapshot drift")
    write_bytes_exclusive(DESIGN_REVIEW_PATH, marker)
    write_exclusive(PACKET_PATH, packet)
    print(json.dumps({
        "packet_sha256": sha256_file(PACKET_PATH),
        "packet_internal_sha256": packet["internal_sha256"],
        "packet_review_claim": packet_review_claim(
            expected_git=args.expected_git,
            packet_sha256=sha256_file(PACKET_PATH),
            packet_internal_sha256=packet["internal_sha256"]),
        "one_score_free_preflight_authorized": False,
    }, sort_keys=True))


def verify_command(args: argparse.Namespace) -> None:
    packet = load_packet(
        Path(args.packet), args.expected_packet_sha256,
        expected_git=args.expected_git,
        population_path=Path(args.population).resolve(),
        design_path=Path(args.design).resolve())
    print(json.dumps({
        "packet_sha256": args.expected_packet_sha256,
        "packet_internal_sha256": packet["internal_sha256"],
        "verified": True,
    }, sort_keys=True))


def run_command(args: argparse.Namespace) -> None:
    require_exact_clean_git(args.expected_git)
    if (Path(args.admission).resolve() != ADMISSION_PATH.resolve()
            or Path(args.out).resolve() != RESULT_PATH.resolve()):
        raise CapacityPreflightRefused("preflight evidence path is not canonical")
    packet = load_packet(
        Path(args.packet), args.expected_packet_sha256,
        expected_git=args.expected_git,
        population_path=Path(args.population).resolve(),
        design_path=Path(args.design).resolve())
    require_regular_unlinked(
        DESIGN_REVIEW_PATH, label="Pair V3 design review snapshot")
    if (sha256_file(DESIGN_REVIEW_PATH)
            != packet["design_review"]["marker_sha256"]
            or DESIGN_REVIEW_PATH.read_bytes() != _canonical_marker(
                DESIGN_REVIEW_PREFIX, expected_design_review_claim())):
        raise CapacityPreflightRefused("design review snapshot drift")
    if require_qualified_runtime() != packet["runtime"]:
        raise CapacityPreflightRefused("execution runtime differs from packet")
    invocation_id = require_systemd_scope()
    claim = packet_review_claim(
        expected_git=args.expected_git,
        packet_sha256=args.expected_packet_sha256,
        packet_internal_sha256=packet["internal_sha256"])
    review, review_marker = canonical_review_record(
        commit=args.packet_review_commit, prefix=PACKET_REVIEW_PREFIX,
        expected=claim, label="Pair V3 preflight packet review")
    collisions = [path for path in (
        ADMISSION_PATH, PACKET_REVIEW_PATH, RESULT_PATH)
        if os.path.lexists(path) or os.path.lexists(str(path) + ".partial")]
    if collisions:
        raise CapacityPreflightRefused("preflight execution slot already consumed")
    write_bytes_exclusive(PACKET_REVIEW_PATH, review_marker)
    admission = {
        "schema": ADMISSION_SCHEMA,
        "run_id": RUN_ID,
        "git": args.expected_git,
        "packet_sha256": args.expected_packet_sha256,
        "packet_review_commit": review["commit"],
        "packet_review_marker_sha256": review["marker_sha256"],
        "nonce": secrets.token_hex(32),
        "created_time_ns": time.time_ns(),
        "systemd_invocation_id": invocation_id,
        "one_score_free_preflight_authorized": True,
        "scored_evaluation_authorized": False,
        "report_access_authorized": False,
        "strength_claim": False,
        "production_deployment": False,
    }
    admission["internal_sha256"] = digest(admission)
    write_exclusive(ADMISSION_PATH, admission)
    result = measure_preflight(
        packet, Path(args.population).resolve(), parallel=True)
    result["admission_sha256"] = sha256_file(ADMISSION_PATH)
    result["packet_sha256"] = args.expected_packet_sha256
    result.pop("internal_sha256", None)
    result["internal_sha256"] = digest(result)
    final_design = DESIGN.build_design(Path(args.population).resolve())
    if score_free_result_problems(result, design=final_design):
        raise CapacityPreflightRefused("final result score-free boundary drift")
    write_exclusive(RESULT_PATH, result)
    print(json.dumps({
        "status": result["status"],
        "result_sha256": sha256_file(RESULT_PATH),
        "result_internal_sha256": result["internal_sha256"],
        "scored_evaluation_authorized": False,
    }, sort_keys=True))


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser()
    commands = root.add_subparsers(dest="command", required=True)
    freeze = commands.add_parser("freeze")
    freeze.add_argument("--expected-git", required=True)
    freeze.add_argument("--population", required=True)
    freeze.add_argument("--design", required=True)
    freeze.add_argument("--out", required=True)
    freeze.set_defaults(func=freeze_command)

    verify = commands.add_parser("verify")
    verify.add_argument("--expected-git", required=True)
    verify.add_argument("--population", required=True)
    verify.add_argument("--design", required=True)
    verify.add_argument("--packet", required=True)
    verify.add_argument("--expected-packet-sha256", required=True)
    verify.set_defaults(func=verify_command)

    run = commands.add_parser("run-preflight")
    run.add_argument("--expected-git", required=True)
    run.add_argument("--population", required=True)
    run.add_argument("--design", required=True)
    run.add_argument("--packet", required=True)
    run.add_argument("--expected-packet-sha256", required=True)
    run.add_argument("--packet-review-commit", required=True)
    run.add_argument("--admission", required=True)
    run.add_argument("--out", required=True)
    run.set_defaults(func=run_command)
    return root


def main() -> None:
    args = parser().parse_args()
    try:
        args.func(args)
    except (CapacityPreflightRefused, DESIGN.CapacityDesignRefused,
            EVAL.EvalRefused, STATES.CaptureRefused,
            subprocess.CalledProcessError, OSError, ValueError) as exc:
        raise SystemExit(f"REFUSED: {exc}") from exc


if __name__ == "__main__":
    main()
