#!/usr/bin/env python3
"""Design the Pair V3 scored DEV/CALIB packet, never freeze or run it.

The independently reviewed score-free capacity result opens exactly this
design step.  This module authenticates that review chain and reconstructs a
closed declarative specification for a future controller and packet freezer.
It deliberately has no packet writer, admission writer, gameplay launcher,
evaluator import, aggregate import, or REPORT surface.

The future scored diagnostic remains conditional on the frozen affected-state
population.  It separates policy-selection benefit from candidate-source
headroom.  Neither quantity is live-champion natural dose or whole-game
strength; a separately designed and reviewed champion-trajectory census is
required before any whole-game or value-for-compute claim.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import stat
import subprocess
from pathlib import Path


SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[1]
REPO = SERVER.parent

SCHEMA = "pair-ballot-affected-scored-packet-design-v1"
FUTURE_PACKET_SCHEMA = "pair-ballot-affected-scored-packet-v1"
FUTURE_RUN_ID = "pair-ballot-affected-scored-dev-calib-v1"
CANONICAL_REVIEW_REF = "origin/main"
REVIEW_LEDGER = "HANDOFF_REVIEW.md"
REVIEW_ROTATION_PREFIX = "HANDOFF_REVIEW_ROTATION_V1 "
REVIEW_ROTATION_SCHEMA = "handoff-review-rotation-v1"
REVIEWER_NAME = "Claude"
REVIEWER_EMAIL = "noreply@anthropic.com"
REVIEWER_SESSION_TRAILER = "Claude-Session: https://claude.ai/code/session_"

SOURCE_POPULATION_REVIEW_PREFIX = (
    "PAIR_BALLOT_AFFECTED_SOURCE_POPULATION_V1_REVIEW ")
ARTIFACT_EVALUATOR_REVIEW_PREFIX = (
    "PAIR_BALLOT_AFFECTED_ARTIFACT_EVALUATOR_V1_REVIEW ")
CAPACITY_DESIGN_REVIEW_PREFIX = (
    "PAIR_BALLOT_AFFECTED_CAPACITY_DESIGN_V1_REVIEW ")
CAPACITY_PACKET_REVIEW_PREFIX = (
    "PAIR_BALLOT_AFFECTED_CAPACITY_PREFLIGHT_PACKET_V1_REVIEW ")
CAPACITY_RESULT_REVIEW_PREFIX = (
    "PAIR_BALLOT_AFFECTED_CAPACITY_PREFLIGHT_RESULT_V1_REVIEW ")

SOURCE_POPULATION_REVIEW_COMMIT = (
    "2dc9552956c79ca6a78230699633c24695b2ae51")
SOURCE_POPULATION_REVIEW_PARENT = (
    "1185ecdc6421771110523e0ced835ae7a47cf51c")
ARTIFACT_EVALUATOR_REVIEW_COMMIT = (
    "3cc183d78f1b2d8e2b90d6b26f63c8ef4c0302ce")
ARTIFACT_EVALUATOR_REVIEW_PARENT = (
    "03bbf5868c79ecd5094332c1e3d5e2537ebf3734")
CAPACITY_DESIGN_REVIEW_COMMIT = (
    "d6db827b4d52ddb0860e50e4f5145a5e4cbb9c7c")
CAPACITY_DESIGN_REVIEW_PARENT = (
    "9191cbf8ecf0f363cc9b1e873f2ff2a36d71b51f")
CAPACITY_PACKET_REVIEW_COMMIT = (
    "88866f25f3763f26996be6f45fbcfcdfe3854f30")
CAPACITY_PACKET_REVIEW_PARENT = (
    "023850da1bc8f0737814b3ebb9bfceea928d2c3d")
CAPACITY_RESULT_REVIEW_COMMIT = (
    "16af447129fc980804126c85ef784958559b481a")
CAPACITY_RESULT_REVIEW_PARENT = (
    "30133fabdee310d04c9ae38c7e17b93b209d25d6")
CAPACITY_PROSE_REVIEW_COMMIT = (
    "8843be7aa549185c00ae0bbef6cc4b8ac29dacfe")
CAPACITY_PROSE_REVIEW_PARENT = (
    "fdd141278a0b8f3a7d9b2efb397dffa8f75b8e6d")

CAPTURE_GIT = "746882859529af883bb634e4da10e567720b7ce9"
EVALUATOR_GIT = "22ddfa3728f1d66cac22e98d64725184dd71efd6"
CAPACITY_DESIGN_GIT = "373de8429261d7271b98f4d427760412cea930e2"
CAPACITY_IMPLEMENTATION_GIT = (
    "6461c660e1ff71a905d9010b12c0adfc4e8bc729")
RESULT_REVIEWER_GIT = "f571146f631914eb6899ce435ef466d70d9f9330"

POPULATION_FILE_SHA256 = (
    "6a3f8d9d5317db642b6fae75a042c26a3b1085f6275e48d233b7b851ac2339ae")
POPULATION_ARTIFACT_SHA256 = (
    "6e62bf4bd43558da6233118fea13d49cd6f90ed4d2632b628b56ccd0f470d4d7")
SHARD_MANIFEST_SHA256 = (
    "6e02bb8b0bfb4c7866dd27abb71d0596cfec6085c1f4d04fc154b629b0f6ded3")
IDENTITY_MEMBERSHIP_SHA256 = (
    "57c835c8785db8c84fff78d19e84dcc7ea1b2ee74ea120065fdf7c75bc276e24")
DEFENDER_MEMBERSHIP_SHA256 = (
    "8225e5f88b5b3a7d368d9715f9c3e9c5fc1a14df61486204168583e5511de9a4")
SELECTION_SHA256 = (
    "3c9993bc8432d2fc419cfb75c2f766119de3aa4eacdf87dc3c238e1a484b29ab")
CAPACITY_DESIGN_FILE_SHA256 = (
    "be21b547659e49399dbaf7ea732c4a6a94f953c59c197765112e12d366dbf439")
CAPACITY_DESIGN_INTERNAL_SHA256 = (
    "cd8ada0d53c914adf9862171bcbf8308496129e3b1d66e63fee0a6efe4ac4f9d")
CAPACITY_PACKET_SHA256 = (
    "e054c5e582c1e665da9bc8ab413639f4c015ffe31a85f22c83275b7f4b4de492")
CAPACITY_PACKET_INTERNAL_SHA256 = (
    "25b1888c62ff772c18e065b30a7bfcc2d724c645f5ad054c4e6823dfd56a14b5")
CAPACITY_ADMISSION_SHA256 = (
    "759fc5b7d23ee619fa7a692014148d282909226fcfa7ceb23f0a7a78fda212f7")
CAPACITY_RESULT_SHA256 = (
    "544499d17df03d08aea908c33b27813771cd1edb41a51394682300a7be4ca764")
CAPACITY_RESULT_INTERNAL_SHA256 = (
    "ca36d1af3dda376884b09b1fb5ed4d7142a2f6c64b5af8c0b4153f20123a4fb2")

SOURCE_SHA256S = {
    "pair_ballot_affected_aggregate.py": (
        "a1908a32853ea62e0c775dd1975b7b7ad7316f662dc19b8fe108b25282099ba0"),
    "pair_ballot_affected_capacity_design.py": (
        "caa2d0d9c5580c56828e72c39e3e5ad0cf5be0d3eb7a8a77603e31c73e786317"),
    "pair_ballot_affected_capacity_preflight.py": (
        "cab2caa01f58c02d932365993c856894f811408853c8a2bef9ca42a75721ebaa"),
    "pair_ballot_affected_capacity_result_review.py": (
        "5ca14e1ff66663b93ff3b9f9f35f28e5463689f9638b2126b6cbb5fe25a646a1"),
    "pair_ballot_affected_eval.py": (
        "2d4adfd06d0de7517bb190ebf5d190bd95f848d9ab25fb5eb9a29f27b3cd7488"),
    "pair_ballot_affected_states.py": (
        "e54102482c2f1652186bfa5458f4f229fa01bd8bf74cdcb2d29c7fe133e6f4ce"),
}

SPLITS = ("dev", "calib")
BANDS = ("early", "mid", "late")
LOGICAL_LANES = 16
STATES = 1_024
DEFENDER_ROWS = 1_023
ATTACKER_ROWS = 1
UNIQUE_DEAL_CLUSTERS = 991
DEFENDER_DEAL_CLUSTERS = 990
STATES_BY_SPLIT = {"calib": 512, "dev": 512}
STATES_BY_BAND = {"early": 896, "late": 32, "mid": 96}
STATES_BY_ROLE = {"attacker": 1, "defender": 1_023}
DEFENDER_ROWS_BY_SPLIT = {"calib": 511, "dev": 512}
DEFENDER_ROWS_BY_BAND = {"early": 895, "late": 32, "mid": 96}
BAND_WEIGHTS = {
    "early": 0.9686815593517302,
    "mid": 0.03081197985107315,
    "late": 0.000506460797196671,
}
LANES = (
    {
        "lane_index": 0, "state_count": 51,
        "states_by_split": {"calib": 24, "dev": 27},
        "states_by_band": {"early": 44, "late": 1, "mid": 6},
        "max_candidate_world_rollouts": 149_940,
        "selection_sha256": (
            "e6757756498b8ade7e35d66c55a7974a4ce83073f75e3cb1246fdb39cc0547a8"),
    },
    {
        "lane_index": 1, "state_count": 59,
        "states_by_split": {"calib": 35, "dev": 24},
        "states_by_band": {"early": 51, "late": 1, "mid": 7},
        "max_candidate_world_rollouts": 173_460,
        "selection_sha256": (
            "a191b5e861d6a6a492a15c51878cffa46121bc9d24a268f2cc4ecafdc3148cc9"),
    },
    {
        "lane_index": 2, "state_count": 60,
        "states_by_split": {"calib": 23, "dev": 37},
        "states_by_band": {"early": 53, "late": 4, "mid": 3},
        "max_candidate_world_rollouts": 176_400,
        "selection_sha256": (
            "9c8c8944f112fbe723ff4d92227f8527a419094a61103215a8ad575a0893cb0e"),
    },
    {
        "lane_index": 3, "state_count": 84,
        "states_by_split": {"calib": 39, "dev": 45},
        "states_by_band": {"early": 75, "mid": 9},
        "max_candidate_world_rollouts": 246_960,
        "selection_sha256": (
            "9aa037a427f56e1de8305be92a6d4ef74d567d476d77a0e81b9c04c13164d025"),
    },
    {
        "lane_index": 4, "state_count": 58,
        "states_by_split": {"calib": 35, "dev": 23},
        "states_by_band": {"early": 52, "late": 2, "mid": 4},
        "max_candidate_world_rollouts": 170_520,
        "selection_sha256": (
            "9cbdff9be1368ba92c94b77418808539ef0a6dadfd6072e6a5f68f9d35ac0d05"),
    },
    {
        "lane_index": 5, "state_count": 74,
        "states_by_split": {"calib": 28, "dev": 46},
        "states_by_band": {"early": 67, "late": 4, "mid": 3},
        "max_candidate_world_rollouts": 217_560,
        "selection_sha256": (
            "88437b2f8b972a9f83c6abdf7890aed9547219e1e335a844e7fefb2d7a344873"),
    },
    {
        "lane_index": 6, "state_count": 61,
        "states_by_split": {"calib": 32, "dev": 29},
        "states_by_band": {"early": 50, "late": 3, "mid": 8},
        "max_candidate_world_rollouts": 179_340,
        "selection_sha256": (
            "622e7365db88665eee36707866d8c4c60efa8eb915ae8eb857d4c0e4293bf57b"),
    },
    {
        "lane_index": 7, "state_count": 47,
        "states_by_split": {"calib": 23, "dev": 24},
        "states_by_band": {"early": 36, "late": 3, "mid": 8},
        "max_candidate_world_rollouts": 138_180,
        "selection_sha256": (
            "c256606d12d047c07dffd8dd2170649477eda60b99d27997970b4f5b2112290d"),
    },
    {
        "lane_index": 8, "state_count": 56,
        "states_by_split": {"calib": 28, "dev": 28},
        "states_by_band": {"early": 48, "late": 2, "mid": 6},
        "max_candidate_world_rollouts": 164_640,
        "selection_sha256": (
            "761fd15afe9b37198eabd7c0252e5749f4d8350b93e618bae4841b67b6bdaf97"),
    },
    {
        "lane_index": 9, "state_count": 50,
        "states_by_split": {"calib": 24, "dev": 26},
        "states_by_band": {"early": 44, "late": 4, "mid": 2},
        "max_candidate_world_rollouts": 147_000,
        "selection_sha256": (
            "510f74ca90c1b630b5e98f4ef13c08fad5f0f80bb7dde01a4c6d9549d7cd3a2b"),
    },
    {
        "lane_index": 10, "state_count": 71,
        "states_by_split": {"calib": 36, "dev": 35},
        "states_by_band": {"early": 64, "late": 2, "mid": 5},
        "max_candidate_world_rollouts": 208_740,
        "selection_sha256": (
            "ebfccf9fa0d84a75090474e9e25793343c5d62064fb52638bd7d9f3a7ad6494f"),
    },
    {
        "lane_index": 11, "state_count": 80,
        "states_by_split": {"calib": 41, "dev": 39},
        "states_by_band": {"early": 69, "late": 2, "mid": 9},
        "max_candidate_world_rollouts": 235_200,
        "selection_sha256": (
            "32dec86631f71d60fa08549a3b9bade2a5ce8ddced55859057371ccf42e34558"),
    },
    {
        "lane_index": 12, "state_count": 77,
        "states_by_split": {"calib": 45, "dev": 32},
        "states_by_band": {"early": 69, "late": 2, "mid": 6},
        "max_candidate_world_rollouts": 226_380,
        "selection_sha256": (
            "d9cbfbf46604faed5cbcf8e84b60e61fae392721350c00f4dde2664fa39d08d6"),
    },
    {
        "lane_index": 13, "state_count": 60,
        "states_by_split": {"calib": 30, "dev": 30},
        "states_by_band": {"early": 51, "mid": 9},
        "max_candidate_world_rollouts": 176_400,
        "selection_sha256": (
            "41d2ea14918e3c6072ea012bf45bab7b6b5994cb0a3b210ca59f7a47188695b8"),
    },
    {
        "lane_index": 14, "state_count": 68,
        "states_by_split": {"calib": 31, "dev": 37},
        "states_by_band": {"early": 60, "late": 1, "mid": 7},
        "max_candidate_world_rollouts": 199_920,
        "selection_sha256": (
            "2fa70c0b8a068b05b804eaa93e7c6e08fe2d9b2b291b0e1ab981c55f968de570"),
    },
    {
        "lane_index": 15, "state_count": 68,
        "states_by_split": {"calib": 38, "dev": 30},
        "states_by_band": {"early": 63, "late": 1, "mid": 4},
        "max_candidate_world_rollouts": 199_920,
        "selection_sha256": (
            "e4c6f6eb8f8ee1d21f967eaa8143b2a3734f88b17e2f8de88b32016866c722fa"),
    },
)
LANE_MANIFEST_SHA256 = (
    "75e1ca0fd756083179b3e1943b528063ce53a2ddaab8a44568b498ccf48a6b37")

BALLOT_WIDTH = 14
SELECTION_WORLDS = 30
POLICY_REPORT_WORLDS = 300
EXTERNAL_REPORT_WORLDS = 300
POLICY_WORK_PER_STATE = 1_020
MAX_EXTERNAL_ACTIONS = 3
MAX_EXTERNAL_WORK_PER_STATE = 900
MAX_WORK_PER_STATE = 2_940
MAX_WORK_TOTAL = 3_010_560

CAPTURE_DEALS = 12_000_000
SMARTBOT_SEARCH_ELIGIBLE_OMISSION_EVENTS = 146_112
SMARTBOT_EVENTS_PER_DEAL = 0.012176

MAX_FLEET_HOURS = 64.0
MAX_LANE_WALL_HOURS = 4.0
THROUGHPUT_SAFETY_FACTOR = 2.0
REVIEWED_PROJECTED_FLEET_HOURS = 1.0498934074073278
REVIEWED_PROJECTED_WORST_LANE_HOURS = 0.0877279930623274


class ScoredPacketDesignRefused(RuntimeError):
    """The reviewed chain or the closed declarative design drifted."""


def _canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"))
            + "\n").encode()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _is_hex(value: object, length: int) -> bool:
    return (isinstance(value, str) and len(value) == length
            and all(char in "0123456789abcdef" for char in value))


def _is_nonnegative_int(value: object) -> bool:
    return (isinstance(value, int) and not isinstance(value, bool)
            and value >= 0)


def _strict_object(pairs: list[tuple[str, object]]) -> dict:
    value: dict = {}
    for key, child in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key: {key}")
        value[key] = child
    return value


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number: {value}")


def _strict_json(raw: bytes, *, label: str) -> dict:
    try:
        value = json.loads(
            raw, object_pairs_hook=_strict_object,
            parse_constant=_reject_constant)
    except (UnicodeDecodeError, ValueError) as exc:
        raise ScoredPacketDesignRefused(f"{label} is unreadable") from exc
    if not isinstance(value, dict):
        raise ScoredPacketDesignRefused(f"{label} is not an object")
    return value


def _same_file(left: os.stat_result, right: os.stat_result) -> bool:
    return all(getattr(left, field) == getattr(right, field) for field in (
        "st_dev", "st_ino", "st_mode", "st_nlink", "st_size",
        "st_mtime_ns", "st_ctime_ns",
    ))


def _stable_bytes(path: Path, *, label: str) -> bytes:
    """Read a local design candidate once without symlink or swap windows."""
    partial = Path(str(path) + ".partial")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        before_path = path.lstat()
        if (not stat.S_ISREG(before_path.st_mode)
                or before_path.st_nlink != 1
                or os.path.lexists(partial)):
            raise ScoredPacketDesignRefused(
                f"{label} is linked, nonregular, or partial")
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ScoredPacketDesignRefused(f"{label} is unreadable") from exc
    try:
        before_fd = os.fstat(descriptor)
        chunks = []
        while True:
            chunk = os.read(descriptor, 1 << 20)
            if not chunk:
                break
            chunks.append(chunk)
        after_fd = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    try:
        after_path = path.lstat()
    except OSError as exc:
        raise ScoredPacketDesignRefused(
            f"{label} path changed during read") from exc
    if (not _same_file(before_path, before_fd)
            or not _same_file(before_fd, after_fd)
            or not _same_file(after_fd, after_path)):
        raise ScoredPacketDesignRefused(f"{label} changed during read")
    raw = b"".join(chunks)
    if len(raw) != after_fd.st_size:
        raise ScoredPacketDesignRefused(f"{label} short read")
    return raw


def _git(*args: str) -> str:
    try:
        return subprocess.run(
            ["git", *args], cwd=REPO, check=True, capture_output=True,
            text=True).stdout.strip()
    except subprocess.CalledProcessError as exc:
        raise ScoredPacketDesignRefused("cannot authenticate review Git") \
            from exc


def _git_bytes(*args: str) -> bytes:
    try:
        return subprocess.run(
            ["git", *args], cwd=REPO, check=True,
            capture_output=True).stdout
    except subprocess.CalledProcessError as exc:
        raise ScoredPacketDesignRefused("cannot authenticate review ledger") \
            from exc


def _is_append_only_ledger(before: bytes, after: bytes, *, growth: bool) -> bool:
    """Require exact byte-prefix ancestry at a complete ledger-line boundary."""
    return (before.endswith(b"\n") and after.endswith(b"\n")
            and after.startswith(before)
            and (not growth or len(after) > len(before)))


def _require_review_history(
        reviewed: bytes, canonical: bytes, *, review_commit: str,
        canonical_ref: str) -> None:
    """Accept append-only history or one byte-authenticated ledger rotation.

    The active review mailbox is periodically compacted.  A rotation is not a
    license to discard review provenance: its canonical record must bind the
    exact pre-rotation Git blob to a byte-identical tracked archive, and the
    reviewed ledger must remain an exact prefix of those archived bytes.
    """
    if _is_append_only_ledger(reviewed, canonical, growth=False):
        return
    rotation_lines = [
        line for line in canonical.splitlines(keepends=True)
        if line.startswith(REVIEW_ROTATION_PREFIX.encode())
    ]
    if len(rotation_lines) != 1:
        raise ScoredPacketDesignRefused(
            "canonical review ledger rewrite lacks one rotation record")
    line = rotation_lines[0]
    record = _strict_json(
        line[len(REVIEW_ROTATION_PREFIX):], label="review ledger rotation")
    if set(record) != {
            "archive_path", "archive_sha256", "authority_changed", "schema",
            "source_commit", "source_ledger_bytes", "source_ledger_lines",
            "source_ledger_sha256"}:
        raise ScoredPacketDesignRefused("review ledger rotation schema drift")
    archive_path = record["archive_path"]
    source_commit = record["source_commit"]
    source_sha256 = record["source_ledger_sha256"]
    if (record["schema"] != REVIEW_ROTATION_SCHEMA
            or record["authority_changed"] is not False
            or not _is_hex(source_commit, 40)
            or not _is_hex(source_sha256, 64)
            or record["archive_sha256"] != source_sha256
            or not _is_nonnegative_int(record["source_ledger_bytes"])
            or not _is_nonnegative_int(record["source_ledger_lines"])
            or not isinstance(archive_path, str)
            or not archive_path.startswith("docs_archive/handoff-review-")
            or not archive_path.endswith(".md")
            or ".." in archive_path.split("/")
            or "\\" in archive_path):
        raise ScoredPacketDesignRefused("review ledger rotation identity drift")
    for ancestor, descendant in (
            (review_commit, source_commit), (source_commit, canonical_ref)):
        if subprocess.run(
                ["git", "merge-base", "--is-ancestor", ancestor, descendant],
                cwd=REPO, capture_output=True).returncode != 0:
            raise ScoredPacketDesignRefused(
                "review ledger rotation ancestry drift")
    source = _git_bytes("show", f"{source_commit}:{REVIEW_LEDGER}")
    archive = _git_bytes("show", f"{canonical_ref}:{archive_path}")
    if (source != archive
            or _sha256_bytes(source) != source_sha256
            or len(source) != record["source_ledger_bytes"]
            or source.count(b"\n") != record["source_ledger_lines"]
            or not _is_append_only_ledger(reviewed, source, growth=False)):
        raise ScoredPacketDesignRefused(
            "review ledger rotation archive drift")


def _canonical_review_record(*, commit: str, parent: str, prefix: str,
                             expected: dict,
                             canonical_ref: str = CANONICAL_REVIEW_REF) -> dict:
    """Authenticate one exact reviewer-introduced marker on canonical main."""
    if subprocess.run(
            ["git", "merge-base", "--is-ancestor", commit, canonical_ref],
            cwd=REPO, capture_output=True).returncode != 0:
        raise ScoredPacketDesignRefused(
            f"review {commit[:8]} is not on canonical main")
    if _git("show", "-s", "--format=%P", commit).split() != [parent]:
        raise ScoredPacketDesignRefused(
            f"review {commit[:8]} parent drift")
    identity = tuple(_git("show", "-s", f"--format=%{field}", commit)
                     for field in ("an", "ae", "cn", "ce"))
    if identity != (
            REVIEWER_NAME, REVIEWER_EMAIL, REVIEWER_NAME, REVIEWER_EMAIL):
        raise ScoredPacketDesignRefused(
            f"review {commit[:8]} actor drift")
    if REVIEWER_SESSION_TRAILER not in _git(
            "show", "-s", "--format=%B", commit):
        raise ScoredPacketDesignRefused(
            f"review {commit[:8]} session provenance missing")
    changed = _git(
        "diff-tree", "--no-commit-id", "--name-only", "-r", commit
    ).splitlines()
    if changed != [REVIEW_LEDGER]:
        raise ScoredPacketDesignRefused(
            f"review {commit[:8]} changed files beyond the ledger")
    current = _git_bytes("show", f"{commit}:{REVIEW_LEDGER}")
    previous = _git_bytes("show", f"{parent}:{REVIEW_LEDGER}")
    canonical = _git_bytes("show", f"{canonical_ref}:{REVIEW_LEDGER}")
    if not _is_append_only_ledger(previous, current, growth=True):
        raise ScoredPacketDesignRefused(
            f"review {commit[:8]} ledger ancestry is not append-only")
    _require_review_history(
        current, canonical, review_commit=commit,
        canonical_ref=canonical_ref)
    marker = prefix.encode() + _canonical(expected)
    current_matches = [line for line in current.splitlines(keepends=True)
                       if line.startswith(prefix.encode())]
    previous_matches = [line for line in previous.splitlines(keepends=True)
                        if line.startswith(prefix.encode())]
    canonical_matches = [line for line in canonical.splitlines(keepends=True)
                         if line.startswith(prefix.encode())]
    if (current_matches != [marker] or previous_matches
            or canonical_matches != [marker]):
        raise ScoredPacketDesignRefused(
            f"review {commit[:8]} marker is not exactly once on canonical main")
    return {
        "commit": commit,
        "parent_commit": parent,
        "canonical_ref": canonical_ref,
        "ledger_blob_sha256": _sha256_bytes(current),
        "marker_sha256": _sha256_bytes(marker),
        "claim": expected,
    }


def _authenticate_capacity_prose_context(
        canonical_ref: str = CANONICAL_REVIEW_REF) -> dict:
    """Bind the public numeric summary without treating prose as authority."""
    commit = CAPACITY_PROSE_REVIEW_COMMIT
    parent = CAPACITY_PROSE_REVIEW_PARENT
    if subprocess.run(
            ["git", "merge-base", "--is-ancestor", commit, canonical_ref],
            cwd=REPO, capture_output=True).returncode != 0:
        raise ScoredPacketDesignRefused(
            "capacity prose context is not on canonical main")
    if _git("show", "-s", "--format=%P", commit).split() != [parent]:
        raise ScoredPacketDesignRefused("capacity prose context parent drift")
    identity = tuple(_git("show", "-s", f"--format=%{field}", commit)
                     for field in ("an", "ae", "cn", "ce"))
    if identity != (
            REVIEWER_NAME, REVIEWER_EMAIL, REVIEWER_NAME, REVIEWER_EMAIL):
        raise ScoredPacketDesignRefused("capacity prose context actor drift")
    if REVIEWER_SESSION_TRAILER not in _git(
            "show", "-s", "--format=%B", commit):
        raise ScoredPacketDesignRefused(
            "capacity prose context session provenance missing")
    changed = _git(
        "diff-tree", "--no-commit-id", "--name-only", "-r", commit
    ).splitlines()
    if changed != [REVIEW_LEDGER]:
        raise ScoredPacketDesignRefused(
            "capacity prose context changed files beyond the ledger")
    current = _git_bytes("show", f"{commit}:{REVIEW_LEDGER}")
    previous = _git_bytes("show", f"{parent}:{REVIEW_LEDGER}")
    canonical = _git_bytes("show", f"{canonical_ref}:{REVIEW_LEDGER}")
    if not _is_append_only_ledger(previous, current, growth=True):
        raise ScoredPacketDesignRefused(
            "capacity prose context ledger ancestry is not append-only")
    _require_review_history(
        current, canonical, review_commit=commit,
        canonical_ref=canonical_ref)
    added = _git_bytes(
        "diff", "--unified=0", parent, commit, "--", REVIEW_LEDGER)
    required = (
        b"1.0498934074073278",
        b"0.0877279930623274",
        b"64-hour cap",
        b"4-hour cap",
        b"Prose only",
    )
    if (not all(value in added for value in required)
            or current == previous):
        raise ScoredPacketDesignRefused(
            "capacity prose numeric summary drift")
    return {
        "commit": commit,
        "parent_commit": parent,
        "canonical_ref": canonical_ref,
        "ledger_blob_sha256": _sha256_bytes(current),
        "authority": False,
        "use": "public independently reproduced capacity numbers only",
    }


def _source_population_claim() -> dict:
    return {
        "capture_git": CAPTURE_GIT,
        "deals_scanned": CAPTURE_DEALS,
        "full_shard_validation_verified": True,
        "independent_scratch_reconstruction_verified": True,
        "merged_population_content_open_authorized": False,
        "one_formal_merge_authorized": True,
        "producer_sha256": SOURCE_SHA256S[
            "pair_ballot_affected_states.py"],
        "production_deployment": False,
        "production_promotion": False,
        "rows": 1_536,
        "rows_per_split": 512,
        "schema": "pair-ballot-affected-source-population-review-v1",
        "score_free": True,
        "scored_evaluation_authorized": False,
        "scratch_artifact_sha256": POPULATION_ARTIFACT_SHA256,
        "scratch_population_sha256": POPULATION_FILE_SHA256,
        "shard_count": 16,
        "shard_manifest_sha256": SHARD_MANIFEST_SHA256,
        "strength_claim": False,
        "training_authorized": False,
        "verdict": "PASS",
    }


def _artifact_evaluator_claim() -> dict:
    return {
        "aggregate_reconstruction_verified": True,
        "aggregate_sha256": SOURCE_SHA256S[
            "pair_ballot_affected_aggregate.py"],
        "capacity_packet_design_authorized": True,
        "capture_source_sha256": SOURCE_SHA256S[
            "pair_ballot_affected_states.py"],
        "dev_calib_only": True,
        "equal_width_complete_policy_verified": True,
        "evaluator_sha256": SOURCE_SHA256S[
            "pair_ballot_affected_eval.py"],
        "formal_artifact_sha256": POPULATION_ARTIFACT_SHA256,
        "formal_population_sha256": POPULATION_FILE_SHA256,
        "formal_population_verified": True,
        "fresh_common_report_verified": True,
        "git": EVALUATOR_GIT,
        "population_content_open_authorized": True,
        "production_deployment": False,
        "production_promotion": False,
        "report_refusal_verified": True,
        "report_worlds": EXTERNAL_REPORT_WORLDS,
        "rows": 1_536,
        "schema": "pair-ballot-affected-artifact-evaluator-review-v1",
        "scored_evaluation_authorized": False,
        "strength_claim": False,
        "training_authorized": False,
        "verdict": "PASS",
    }


def _capacity_design_claim() -> dict:
    return {
        "attacker_rows_descriptive_only": True,
        "capacity_preflight_execution_authorized": False,
        "capacity_preflight_implementation_authorized": True,
        "champion_natural_role_dose_required": True,
        "cluster_unit": "deal_seed",
        "combined_dev_calib_primary": True,
        "defender_deal_clusters": DEFENDER_DEAL_CLUSTERS,
        "defender_membership_sha256": DEFENDER_MEMBERSHIP_SHA256,
        "defender_rows": DEFENDER_ROWS,
        "design_file_sha256": CAPACITY_DESIGN_FILE_SHA256,
        "design_internal_sha256": CAPACITY_DESIGN_INTERNAL_SHA256,
        "design_source_sha256": SOURCE_SHA256S[
            "pair_ballot_affected_capacity_design.py"],
        "git": CAPACITY_DESIGN_GIT,
        "identity_membership_sha256": IDENTITY_MEMBERSHIP_SHA256,
        "mde_at_target_power": 0.040889289223836306,
        "parent_git": EVALUATOR_GIT,
        "population_sha256": POPULATION_FILE_SHA256,
        "power_at_worthwhile_effect": 0.9186636345219327,
        "production_deployment": False,
        "production_promotion": False,
        "python_311_312_314_byte_identical": True,
        "report_access_authorized": False,
        "schema": "pair-ballot-affected-capacity-design-review-v1",
        "scored_evaluation_authorized": False,
        "selection_sha256": SELECTION_SHA256,
        "smartbot_trajectory_dose_only": True,
        "states": STATES,
        "strength_claim": False,
        "test_sha256": (
            "bc103baa97a6deffa68c4bbcec82c0697c54a0521c9842d72fd683f45aa904dc"),
        "training_authorized": False,
        "verdict": "PASS",
    }


def _capacity_packet_claim() -> dict:
    return {
        "git": CAPACITY_IMPLEMENTATION_GIT,
        "independent_review": True,
        "one_score_free_preflight_authorized": True,
        "packet_internal_sha256": CAPACITY_PACKET_INTERNAL_SHA256,
        "packet_sha256": CAPACITY_PACKET_SHA256,
        "production_deployment": False,
        "production_promotion": False,
        "report_access_authorized": False,
        "run_id": "pair-ballot-affected-capacity-preflight-v1",
        "schema": "pair-ballot-affected-capacity-preflight-packet-review-v1",
        "scored_evaluation_authorized": False,
        "strength_claim": False,
        "training_authorized": False,
        "verdict": "PASS",
    }


def _capacity_result_claim() -> dict:
    return {
        "admission_sha256": CAPACITY_ADMISSION_SHA256,
        "extension_authorized": False,
        "git": CAPACITY_IMPLEMENTATION_GIT,
        "independent_review": True,
        "packet_internal_sha256": CAPACITY_PACKET_INTERNAL_SHA256,
        "packet_review_commit": CAPACITY_PACKET_REVIEW_COMMIT,
        "packet_sha256": CAPACITY_PACKET_SHA256,
        "production_deployment": False,
        "production_promotion": False,
        "report_access_authorized": False,
        "result_internal_sha256": CAPACITY_RESULT_INTERNAL_SHA256,
        "result_reviewer_script_sha256": SOURCE_SHA256S[
            "pair_ballot_affected_capacity_result_review.py"],
        "result_sha256": CAPACITY_RESULT_SHA256,
        "retry_authorized": False,
        "reviewer_dependency_sha256s": {
            name: digest for name, digest in SOURCE_SHA256S.items()
            if name != "pair_ballot_affected_capacity_result_review.py"
        },
        "run_id": "pair-ballot-affected-capacity-preflight-v1",
        "schema": "pair-ballot-affected-capacity-preflight-result-review-v1",
        "score_free_capacity_pass": True,
        "scored_evaluation_authorized": False,
        "scored_packet_design_authorized": True,
        "scored_packet_freeze_authorized": False,
        "scored_packet_run_authorized": False,
        "strength_claim": False,
        "training_authorized": False,
        "verdict": "PASS",
    }


def _review_specs() -> tuple[tuple[str, str, str, str, dict], ...]:
    return (
        ("source_population", SOURCE_POPULATION_REVIEW_COMMIT,
         SOURCE_POPULATION_REVIEW_PARENT, SOURCE_POPULATION_REVIEW_PREFIX,
         _source_population_claim()),
        ("artifact_evaluator", ARTIFACT_EVALUATOR_REVIEW_COMMIT,
         ARTIFACT_EVALUATOR_REVIEW_PARENT,
         ARTIFACT_EVALUATOR_REVIEW_PREFIX, _artifact_evaluator_claim()),
        ("capacity_design", CAPACITY_DESIGN_REVIEW_COMMIT,
         CAPACITY_DESIGN_REVIEW_PARENT, CAPACITY_DESIGN_REVIEW_PREFIX,
         _capacity_design_claim()),
        ("capacity_packet", CAPACITY_PACKET_REVIEW_COMMIT,
         CAPACITY_PACKET_REVIEW_PARENT, CAPACITY_PACKET_REVIEW_PREFIX,
         _capacity_packet_claim()),
        ("capacity_result", CAPACITY_RESULT_REVIEW_COMMIT,
         CAPACITY_RESULT_REVIEW_PARENT, CAPACITY_RESULT_REVIEW_PREFIX,
         _capacity_result_claim()),
    )


def _authenticate_review_chain() -> dict[str, dict]:
    return {
        name: _canonical_review_record(
            commit=commit, parent=parent, prefix=prefix, expected=claim)
        for name, commit, parent, prefix, claim in _review_specs()
    }


def _reviewed_sources() -> dict[str, str]:
    observed = {
        name: _sha256_bytes(_stable_bytes(
            SCRIPT.parent / name, label=f"reviewed Pair source {name}"))
        for name in sorted(SOURCE_SHA256S)
    }
    if observed != dict(sorted(SOURCE_SHA256S.items())):
        raise ScoredPacketDesignRefused("reviewed Pair source digest drift")
    return observed


def _validate_chain(records: dict[str, dict], sources: dict[str, str]) -> None:
    if set(records) != {
            "source_population", "artifact_evaluator", "capacity_design",
            "capacity_packet", "capacity_result"}:
        raise ScoredPacketDesignRefused("review record population drift")
    source = records["source_population"]["claim"]
    evaluator = records["artifact_evaluator"]["claim"]
    design = records["capacity_design"]["claim"]
    packet = records["capacity_packet"]["claim"]
    result = records["capacity_result"]["claim"]
    result_dependencies = dict(sources)
    result_dependencies.pop(
        "pair_ballot_affected_capacity_result_review.py")
    if not (
            source["scratch_population_sha256"]
            == evaluator["formal_population_sha256"]
            == design["population_sha256"] == POPULATION_FILE_SHA256
            and source["scratch_artifact_sha256"]
            == evaluator["formal_artifact_sha256"]
            == POPULATION_ARTIFACT_SHA256
            and evaluator["evaluator_sha256"]
            == sources["pair_ballot_affected_eval.py"]
            and evaluator["aggregate_sha256"]
            == sources["pair_ballot_affected_aggregate.py"]
            and design["design_source_sha256"]
            == sources["pair_ballot_affected_capacity_design.py"]
            and packet["packet_sha256"]
            == result["packet_sha256"] == CAPACITY_PACKET_SHA256
            and packet["packet_internal_sha256"]
            == result["packet_internal_sha256"]
            == CAPACITY_PACKET_INTERNAL_SHA256
            and result["packet_review_commit"]
            == records["capacity_packet"]["commit"]
            and result["result_reviewer_script_sha256"]
            == sources["pair_ballot_affected_capacity_result_review.py"]
            and result["reviewer_dependency_sha256s"] == result_dependencies
            and result["score_free_capacity_pass"] is True
            and result["scored_packet_design_authorized"] is True):
        raise ScoredPacketDesignRefused("review-chain identity drift")
    closed_fields = (
        "scored_evaluation_authorized", "report_access_authorized",
        "strength_claim", "training_authorized", "production_promotion",
        "production_deployment",
    )
    for claim in (evaluator, design, packet, result):
        for field in closed_fields:
            if field in claim and claim[field] is not False:
                raise ScoredPacketDesignRefused(
                    f"review-chain authority escalation: {field}")
    for field in (
            "scored_packet_freeze_authorized", "scored_packet_run_authorized",
            "retry_authorized", "extension_authorized"):
        if result[field] is not False:
            raise ScoredPacketDesignRefused(
                f"capacity result authority escalation: {field}")


def _validate_fixed_contract() -> None:
    """Type-check constants Python equality could otherwise blur.

    In particular, ``True == 1`` and ``1024.0 == 1024``.  Packet identities,
    indices and counts must retain their exact JSON types, not merely compare
    equal as Python values.
    """
    sha256s = (
        POPULATION_FILE_SHA256, POPULATION_ARTIFACT_SHA256,
        SHARD_MANIFEST_SHA256, IDENTITY_MEMBERSHIP_SHA256,
        DEFENDER_MEMBERSHIP_SHA256, SELECTION_SHA256,
        CAPACITY_DESIGN_FILE_SHA256, CAPACITY_DESIGN_INTERNAL_SHA256,
        CAPACITY_PACKET_SHA256, CAPACITY_PACKET_INTERNAL_SHA256,
        CAPACITY_ADMISSION_SHA256, CAPACITY_RESULT_SHA256,
        CAPACITY_RESULT_INTERNAL_SHA256, LANE_MANIFEST_SHA256,
        *SOURCE_SHA256S.values(),
        *(lane["selection_sha256"] for lane in LANES),
    )
    git_ids = (
        SOURCE_POPULATION_REVIEW_COMMIT, SOURCE_POPULATION_REVIEW_PARENT,
        ARTIFACT_EVALUATOR_REVIEW_COMMIT,
        ARTIFACT_EVALUATOR_REVIEW_PARENT, CAPACITY_DESIGN_REVIEW_COMMIT,
        CAPACITY_DESIGN_REVIEW_PARENT, CAPACITY_PACKET_REVIEW_COMMIT,
        CAPACITY_PACKET_REVIEW_PARENT, CAPACITY_RESULT_REVIEW_COMMIT,
        CAPACITY_RESULT_REVIEW_PARENT, CAPACITY_PROSE_REVIEW_COMMIT,
        CAPACITY_PROSE_REVIEW_PARENT,
        CAPTURE_GIT, EVALUATOR_GIT, CAPACITY_DESIGN_GIT,
        CAPACITY_IMPLEMENTATION_GIT, RESULT_REVIEWER_GIT,
    )
    if (not all(_is_hex(value, 64) for value in sha256s)
            or not all(_is_hex(value, 40) for value in git_ids)):
        raise ScoredPacketDesignRefused("fixed digest or Git identity drift")
    counts = (
        LOGICAL_LANES, STATES, DEFENDER_ROWS, ATTACKER_ROWS,
        UNIQUE_DEAL_CLUSTERS, DEFENDER_DEAL_CLUSTERS, BALLOT_WIDTH,
        SELECTION_WORLDS, POLICY_REPORT_WORLDS, EXTERNAL_REPORT_WORLDS,
        POLICY_WORK_PER_STATE, MAX_EXTERNAL_ACTIONS,
        MAX_EXTERNAL_WORK_PER_STATE, MAX_WORK_PER_STATE, MAX_WORK_TOTAL,
        CAPTURE_DEALS, SMARTBOT_SEARCH_ELIGIBLE_OMISSION_EVENTS,
        *STATES_BY_SPLIT.values(), *STATES_BY_BAND.values(),
        *STATES_BY_ROLE.values(), *DEFENDER_ROWS_BY_SPLIT.values(),
        *DEFENDER_ROWS_BY_BAND.values(),
    )
    lane_fields = {
        "lane_index", "state_count", "states_by_split", "states_by_band",
        "max_candidate_world_rollouts", "selection_sha256",
    }
    if (not all(_is_nonnegative_int(value) for value in counts)
            or not isinstance(LANES, tuple) or len(LANES) != LOGICAL_LANES
            or any(not isinstance(lane, dict) or set(lane) != lane_fields
                   for lane in LANES)
            or any(not _is_nonnegative_int(lane["lane_index"])
                   or not _is_nonnegative_int(lane["state_count"])
                   or not _is_nonnegative_int(
                       lane["max_candidate_world_rollouts"])
                   or not isinstance(lane["states_by_split"], dict)
                   or not isinstance(lane["states_by_band"], dict)
                   or any(not _is_nonnegative_int(value)
                          for value in lane["states_by_split"].values())
                   or any(not _is_nonnegative_int(value)
                          for value in lane["states_by_band"].values())
                   for lane in LANES)):
        raise ScoredPacketDesignRefused("fixed count or lane type drift")
    if (_sha256_bytes(_canonical(list(LANES))) != LANE_MANIFEST_SHA256
            or not SCHEMA or not FUTURE_PACKET_SCHEMA or not FUTURE_RUN_ID):
        raise ScoredPacketDesignRefused("fixed lane manifest identity drift")


def build_design() -> dict:
    """Reconstruct the complete design from public reviewed identities."""
    _validate_fixed_contract()
    sources = _reviewed_sources()
    review_chain = _authenticate_review_chain()
    capacity_prose_context = _authenticate_capacity_prose_context()
    _validate_chain(review_chain, sources)
    lane_split_totals = {
        split: sum(lane["states_by_split"].get(split, 0) for lane in LANES)
        for split in SPLITS
    }
    lane_band_totals = {
        band: sum(lane["states_by_band"].get(band, 0) for lane in LANES)
        for band in BANDS
    }
    if (not math.isclose(math.fsum(BAND_WEIGHTS.values()), 1.0,
                         abs_tol=1e-15)
            or sum(STATES_BY_SPLIT.values()) != STATES
            or sum(STATES_BY_BAND.values()) != STATES
            or sum(STATES_BY_ROLE.values()) != STATES
            or [lane["lane_index"] for lane in LANES]
            != list(range(LOGICAL_LANES))
            or sum(lane["state_count"] for lane in LANES) != STATES
            or lane_split_totals != STATES_BY_SPLIT
            or lane_band_totals != STATES_BY_BAND
            or sum(lane["max_candidate_world_rollouts"] for lane in LANES)
            != MAX_WORK_TOTAL
            or any(lane["max_candidate_world_rollouts"]
                   != lane["state_count"] * MAX_WORK_PER_STATE
                   for lane in LANES)
            or any(sum(lane["states_by_split"].values())
                   != lane["state_count"] for lane in LANES)
            or any(sum(lane["states_by_band"].values())
                   != lane["state_count"] for lane in LANES)
            or REVIEWED_PROJECTED_FLEET_HOURS > MAX_FLEET_HOURS
            or REVIEWED_PROJECTED_WORST_LANE_HOURS
            > MAX_LANE_WALL_HOURS):
        raise ScoredPacketDesignRefused("fixed design arithmetic drift")

    payload = {
        "schema": SCHEMA,
        "review_chain": {
            "records": review_chain,
            "reviewed_sources": sources,
            "result_reviewer_git": RESULT_REVIEWER_GIT,
            "capacity_prose_context": capacity_prose_context,
            "terminal_authority": (
                "authenticated capacity-result marker permits this scored-"
                "packet design only"),
            "all_later_authority_requires_new_marker": True,
        },
        "frozen_inputs": {
            "population": {
                "file_sha256": POPULATION_FILE_SHA256,
                "artifact_sha256": POPULATION_ARTIFACT_SHA256,
                "shard_manifest_sha256": SHARD_MANIFEST_SHA256,
                "capture_git": CAPTURE_GIT,
                "capture_source_sha256": sources[
                    "pair_ballot_affected_states.py"],
                "source_rows": 1_536,
                "source_rows_per_split": 512,
                "source_splits": ["dev", "calib", "report"],
                "report_rows_admitted": 0,
            },
            "capacity_design": {
                "git": CAPACITY_DESIGN_GIT,
                "file_sha256": CAPACITY_DESIGN_FILE_SHA256,
                "internal_sha256": CAPACITY_DESIGN_INTERNAL_SHA256,
                "source_sha256": sources[
                    "pair_ballot_affected_capacity_design.py"],
            },
            "evaluator": {
                "git": EVALUATOR_GIT,
                "source_sha256": sources["pair_ballot_affected_eval.py"],
                "aggregate_source_sha256": sources[
                    "pair_ballot_affected_aggregate.py"],
                "capture_source_sha256": sources[
                    "pair_ballot_affected_states.py"],
            },
            "capacity_evidence": {
                "implementation_git": CAPACITY_IMPLEMENTATION_GIT,
                "packet_sha256": CAPACITY_PACKET_SHA256,
                "packet_internal_sha256": CAPACITY_PACKET_INTERNAL_SHA256,
                "admission_sha256": CAPACITY_ADMISSION_SHA256,
                "result_sha256": CAPACITY_RESULT_SHA256,
                "result_internal_sha256": CAPACITY_RESULT_INTERNAL_SHA256,
                "result_review_commit": CAPACITY_RESULT_REVIEW_COMMIT,
                "score_free_capacity_pass": True,
            },
        },
        "selection": {
            "rule": "all frozen DEV and CALIB rows; no outcome filtering",
            "splits": list(SPLITS),
            "report_permitted": False,
            "states": STATES,
            "states_by_split": copy.deepcopy(STATES_BY_SPLIT),
            "states_by_band": copy.deepcopy(STATES_BY_BAND),
            "states_by_role": copy.deepcopy(STATES_BY_ROLE),
            "unique_deal_clusters": UNIQUE_DEAL_CLUSTERS,
            "identity_membership_sha256": IDENTITY_MEMBERSHIP_SHA256,
            "selection_sha256": SELECTION_SHA256,
            "no_replacement_retry_or_extension": True,
        },
        "schedule": {
            "assignment": "deal_seed modulo 16; DEV then CALIB in each lane",
            "logical_lanes": LOGICAL_LANES,
            "lanes": copy.deepcopy(list(LANES)),
            "lane_manifest_sha256": LANE_MANIFEST_SHA256,
            "lane_manifest_provenance": (
                "exact reviewed capacity design file be21b547...f439"),
            "minimum_states_in_lane": 47,
            "maximum_states_in_lane": 84,
            "scored_shard_outputs": 32,
            "lane_manifest_bound_to_exact_reviewed_capacity_design": True,
            "complete_fixed_population_required": True,
            "outcome_dependent_lane_loss_or_extension": "refuse",
        },
        "scored_work": {
            "ballot_width": BALLOT_WIDTH,
            "current_policy": "mc-s0-report-lcb with pair retention off",
            "retained_policy": "mc-s0-report-lcb with pair retention on",
            "selection_worlds_per_candidate": SELECTION_WORLDS,
            "policy_report_lcb_worlds": POLICY_REPORT_WORLDS,
            "complete_policy_rollouts_per_arm": POLICY_WORK_PER_STATE,
            "policy_arms": 2,
            "external_common_worlds": EXTERNAL_REPORT_WORLDS,
            "external_actions": [
                "current_policy", "retained_policy", "best_inserted_pair"],
            "max_external_actions": MAX_EXTERNAL_ACTIONS,
            "max_external_rollouts_per_state": MAX_EXTERNAL_WORK_PER_STATE,
            "max_candidate_world_rollouts_per_state": MAX_WORK_PER_STATE,
            "max_candidate_world_rollouts_total": MAX_WORK_TOTAL,
            "same_policy_root_seed_for_current_and_retained": True,
            "fresh_common_external_world_draw_for_all_distinct_actions": True,
            "paired_external_action_utilities": True,
            "policy_report_lcb_is_not_source_REPORT_split_access": True,
            "short_or_incomplete_search": "refuse",
        },
        "estimands": {
            "scope": "affected-state source/selector exploration",
            "primary": "defender_retained_policy_minus_current",
            "secondary": "defender_best_inserted_pair_minus_current",
            "primary_population": "combined DEV+CALIB defender rows",
            "primary_row_filter": "role == defender",
            "defender_rows": DEFENDER_ROWS,
            "defender_deal_clusters": DEFENDER_DEAL_CLUSTERS,
            "defender_rows_by_split": copy.deepcopy(DEFENDER_ROWS_BY_SPLIT),
            "defender_rows_by_band": copy.deepcopy(DEFENDER_ROWS_BY_BAND),
            "defender_membership_sha256": DEFENDER_MEMBERSHIP_SHA256,
            "attacker_rows": ATTACKER_ROWS,
            "attacker_use": "descriptive case study only",
            "cluster_unit": "deal_seed",
            "band_weights": copy.deepcopy(BAND_WEIGHTS),
            "band_weight_unit": (
                "SmartBot-trajectory search-reachable omission events"),
            "within_band_sampling_unit": (
                "first affected state per deal and band in frozen population"),
            "combined_dev_calib_primary": True,
            "split_results_are_diagnostics": True,
            "always_publish_both_metrics_and_all_split_band_slices": True,
            "policy_selection_neutral_does_not_imply_source_failure": True,
            "exact_natural_decision_estimand": False,
            "exact_whole_round_estimand": False,
            "confirmatory_claim": False,
            "terminal_selection": False,
        },
        "routing": {
            "statistic": "sign of combined defender diagnostic means",
            "policy_and_source_positive": (
                "require separately reviewed live-champion natural-dose census"
                " before whole-game design"),
            "source_positive_policy_nonpositive": (
                "source promising; selector not exploiting; improve selector"),
            "policy_positive_source_nonpositive": (
                "audit evictions before attributing fixed-width headroom"),
            "both_nonpositive": (
                "stop forced retention; try contextual pair source"),
            "route_is_exploration_only": True,
            "route_cannot_authorize_more_scored_work": True,
            "route_cannot_claim_strength": True,
        },
        "power": {
            "family": "predeclared one-sided normal planning approximation",
            "planning_cluster_sd": 0.50,
            "one_sided_alpha": 0.05,
            "target_power": 0.80,
            "worthwhile_conditional_effect": 0.05,
            "mde_at_target_power": 0.040889289223836306,
            "power_at_worthwhile_effect": 0.9186636345219327,
            "planning_only": True,
            "affected_state_effect_only": True,
            "whole_game_power_claim": False,
        },
        "natural_dose_boundary": {
            "source_trajectory_policy": "smart",
            "capture_deals": CAPTURE_DEALS,
            "search_eligible_omission_events":
                SMARTBOT_SEARCH_ELIGIBLE_OMISSION_EVENTS,
            "events_per_captured_smartbot_deal": SMARTBOT_EVENTS_PER_DEAL,
            "is_live_champion_dose": False,
            "selected_role_mix_is_natural_dose": False,
            "live_champion_role_specific_dose_available": False,
            "translation_to_whole_round_is_approximate": True,
            "future_champion_trajectory_census": {
                "required_before_whole_game_or_value_for_compute_claim": True,
                "exact_policy_identity_required": "mc-s0-report-lcb",
                "all_natural_search_reachable_omission_events_counted": True,
                "counts_required_by_role": ["attacker", "defender"],
                "counts_required_by_band": list(BANDS),
                "fresh_design_and_independent_review_required": True,
                "included_in_this_scored_packet": False,
                "implementation_authorized": False,
                "execution_authorized": False,
            },
        },
        "capacity_and_economics": {
            "exact_runtime_and_result_specific": True,
            "score_free_projection": True,
            "numeric_summary_provenance_commit":
                CAPACITY_PROSE_REVIEW_COMMIT,
            "numeric_summary_is_prose_context_not_execution_authority": True,
            "throughput_safety_factor": THROUGHPUT_SAFETY_FACTOR,
            "projected_fleet_hours": REVIEWED_PROJECTED_FLEET_HOURS,
            "max_fleet_hours": MAX_FLEET_HOURS,
            "fleet_hour_headroom": (
                MAX_FLEET_HOURS - REVIEWED_PROJECTED_FLEET_HOURS),
            "projected_worst_lane_hours":
                REVIEWED_PROJECTED_WORST_LANE_HOURS,
            "reviewed_worst_lane_is_max_of_16_lane_projections": True,
            "average_lane_projection_permitted": False,
            "max_lane_wall_hours": MAX_LANE_WALL_HOURS,
            "worst_lane_headroom_hours": (
                MAX_LANE_WALL_HOURS
                - REVIEWED_PROJECTED_WORST_LANE_HOURS),
            "capacity_is_not_current_constraint": True,
            "projected_fleet_hours_are_not_billed_host_hours": True,
            "currency_or_host_price_claim": False,
            "utility_per_compute_claim": False,
            "whole_game_economics_claim": False,
            "natural_dose_required_before_value_for_compute_claim": True,
            "retry_or_extension_for_economics": False,
        },
        "future_controller_freeze": {
            "status": "specification only; controller not implemented",
            "run_id": FUTURE_RUN_ID,
            "packet_schema": FUTURE_PACKET_SCHEMA,
            "independent_design_source_review_required": True,
            "packet_must_bind_reviewed_design_source_git_and_sha256": True,
            "packet_must_bind_this_design_file_and_internal_sha256": True,
            "packet_must_bind_all_frozen_inputs_and_review_records": True,
            "packet_must_bind_exact_runtime_from_reviewed_capacity_packet":
                True,
            "packet_must_bind_reviewed_per_lane_projection_vector": True,
            "average_lane_projection_permitted": False,
            "packet_must_reconstruct_population_design_and_all_16_lanes": True,
            "dependency_source_bytes_authenticated_before_import": True,
            "preloaded_pair_dependency_names_refuse": True,
            "evidence_reads_require_regular_unlinked_no_partial_single_inode":
                True,
            "evidence_bytes_unchanged_across_reconstruction": True,
            "packet_must_keep_report_split_absent": True,
            "packet_must_keep_scored_outputs_sealed": True,
            "score_free_terminal_final_before_outcome_access": True,
            "independent_packet_review_required": True,
            "fresh_consumed_admission_required": True,
            "packet_cannot_self_authorize": True,
            "packet_write_must_be_exclusive_and_after_review": True,
            "implementation_authorized_now": False,
            "freeze_authorized_now": False,
            "run_authorized_now": False,
        },
        "terminal_sequence": {
            "scored_shards_remain_sealed_until_supervisor_final_review": True,
            "score_free_supervisor_final_review_required": True,
            "aggregation_requires_separate_explicit_marker": True,
            "aggregate_reconstruction_requires_all_32_exact_shards": True,
            "result_review_required_before_opening_diagnostic_values": True,
            "positive_diagnostic_opens_only_fresh_next_design_review": True,
            "no_automatic_retry_extension_or_larger_look": True,
        },
        "authority": {
            "scored_packet_design_only": True,
            "controller_freeze_specification_only": True,
            "population_open_authorized_now": False,
            "capacity_result_open_authorized_now": False,
            "controller_implementation_authorized": False,
            "scored_packet_implementation_authorized": False,
            "scored_packet_freeze_authorized": False,
            "scored_packet_run_authorized": False,
            "scored_evaluation_authorized": False,
            "scored_output_access_authorized": False,
            "aggregation_authorized": False,
            "report_access_authorized": False,
            "champion_dose_census_implementation_authorized": False,
            "champion_dose_census_execution_authorized": False,
            "whole_game_execution_authorized": False,
            "retry_authorized": False,
            "extension_authorized": False,
            "strength_claim": False,
            "training_authorized": False,
            "production_promotion": False,
            "production_deployment": False,
        },
    }
    payload["design_sha256"] = _sha256_bytes(_canonical(payload))
    return payload


def validate_design(payload: object) -> None:
    """Refuse unless every field reconstructs from the reviewed chain."""
    if not isinstance(payload, dict):
        raise ScoredPacketDesignRefused("scored-packet design is not an object")
    body = dict(payload)
    observed = body.pop("design_sha256", None)
    if observed != _sha256_bytes(_canonical(body)):
        raise ScoredPacketDesignRefused("scored-packet design digest drift")
    if _canonical(payload) != _canonical(build_design()):
        raise ScoredPacketDesignRefused(
            "scored-packet design differs from reconstruction")


def verify_design_file(path: Path) -> dict:
    raw = _stable_bytes(path, label="Pair V3 scored-packet design")
    payload = _strict_json(raw, label="Pair V3 scored-packet design")
    if raw != _canonical(payload):
        raise ScoredPacketDesignRefused(
            "Pair V3 scored-packet design is not canonical JSON")
    validate_design(payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("build", "verify"))
    parser.add_argument("--design", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "build":
            if args.design is not None:
                raise ScoredPacketDesignRefused(
                    "build prints to stdout and accepts no design path")
            design = build_design()
            print(_canonical(design).decode(), end="")
        else:
            if args.design is None:
                raise ScoredPacketDesignRefused(
                    "verify requires --design")
            design = verify_design_file(args.design)
            print(json.dumps({
                "schema": design["schema"],
                "design_sha256": design["design_sha256"],
                "states": design["selection"]["states"],
                "logical_lanes": design["schedule"]["logical_lanes"],
                "scored_packet_freeze_authorized": False,
                "scored_packet_run_authorized": False,
            }, sort_keys=True))
    except (OSError, ValueError, ScoredPacketDesignRefused) as exc:
        print(f"REFUSING: {exc}")
        raise SystemExit(3) from exc


if __name__ == "__main__":
    main()
