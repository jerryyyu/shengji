#!/usr/bin/env python3
"""Freeze the score-free S3c one-card capacity controller.

The reviewed S3c curriculum deliberately starts where every public root has
exactly one legal action.  This controller freezes 64 such roots (16 per
within-trick offset), four information-set determinizations per root, a
256-node cumulative exact-session cap, and one deterministic execution/replay
path.  Freeze and verification replay public states only: they sample no
hidden world, invoke no exact solver, publish no action value, and make no
strength claim.

An independent controller PASS may authorize the separate runtime to execute
this one mechanics/capacity experiment.  It does not authorize two-card work,
training, promotion, or production use.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Mapping


SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[1]
REPO = SERVER.parent
sys.path.insert(0, str(SCRIPT.parent))
sys.path.insert(0, str(SERVER))

import s3c_exact_root_design as DESIGN  # noqa: E402


SCHEMA = "s3c-one-card-capacity-controller-v1"
PACKET_ID = "s3c-one-card-capacity-173m-v1"
RUN_ID = PACKET_ID
RECEIPT_SCHEMA = "s3c-one-card-capacity-execution-receipt-v1"
RESULT_SCHEMA = "s3c-one-card-capacity-result-v1"
FINAL_SCHEMA = "s3c-one-card-capacity-final-v1"
REVIEW_SCHEMA = "s3c-one-card-capacity-controller-review-v1"
REVIEW_MARKER = "S3C_ONE_CARD_CAPACITY_CONTROLLER_V1_REVIEW "

DESIGN_PACKET_LOGICAL_PATH = (
    "server/runs/logs/s3c-exact-root-curriculum-v1/design_packet.json"
)
CENSUS_LOGICAL_PATH = (
    "server/runs/logs/s3c-natural-prefix-census-173m-v1/census.json"
)
DESIGN_PACKET_SHA256 = (
    "df1024280a77c60174a57c3273ba3624e672bec9afde023576fde0404df49eca"
)
DESIGN_PACKET_INTERNAL_SHA256 = (
    "d1d70e37206d8f1be9fc9742c601d7c0f5977feefbd43f208ea8a0ab79c61c74"
)
CENSUS_SHA256 = (
    "236326099dc9763c6a5941bcb2a90670c4e23ac390ea07a0e4ec5063fa50b52a"
)
CENSUS_INTERNAL_SHA256 = (
    "206fada278f96e45bfe1a8fcb1066ca0d8402cfb9e4f79e4c6bce0e2564179ee"
)
DESIGN_PRODUCER_GIT = "0b96faeb4921bd87e71249dd3f7158861a46e124"
DESIGN_ASSET_GIT = "4fb90a1242e467d5f69660ae03e4f164290202a1"
DESIGN_REVIEW_GIT = "084ba7eba59cd0a317a50c4088f194d2376c1e03"
HUMAN_MANIFEST_SHA256 = DESIGN.HUMAN_MANIFEST_SHA256

ROOTS_PER_OFFSET = 16
ROOT_COUNT = 64
WORLDS_PER_ROOT = 4
WORLD_COUNT = ROOT_COUNT * WORLDS_PER_ROOT
MAX_HAND_CARDS = 1
MAX_NODES_PER_WORLD_SESSION = 256
MAX_EXECUTION_NODES = WORLD_COUNT * MAX_NODES_PER_WORLD_SESSION
MAX_TERMINAL_REPLAY_NODES = MAX_EXECUTION_NODES
MAX_TOTAL_PIPELINE_NODES = MAX_EXECUTION_NODES + MAX_TERMINAL_REPLAY_NODES
ROOT_SELECTION_DOMAIN = b"s3c-one-card-root-selection-v1\x00"
WORLD_SEED_DOMAIN = b"s3c-one-card-world-v1\x00"
SAMPLER_FLAGS = (
    "SHENGJI_WEIGHTED_SPLITS",
    "SHENGJI_UNIFORM_DEAL",
    "SHENGJI_PHYSICAL_FILLS",
    "SHENGJI_ALLOW_BALLOT_MISMATCH",
)
SOURCE_PATHS = (
    "server/scripts/s3c_one_card_controller.py",
    "server/scripts/s3c_one_card_runtime.py",
    "server/scripts/s3c_exact_root_design.py",
    "server/shengji/ai/endgame.py",
    "server/shengji/ai/mcbot.py",
    "server/shengji/ai/memory.py",
    "server/shengji/ai/heuristic.py",
    "server/shengji/engine/game.py",
    "server/shengji/engine/round.py",
    "server/shengji/engine/legal.py",
    "server/shengji/engine/combos.py",
    "server/shengji/engine/cards.py",
)

DESIGN_REVIEW_CLAIM = {
    "schema": "s3c-exact-root-curriculum-review-v1",
    "git": DESIGN_ASSET_GIT,
    "producer_git": DESIGN_PRODUCER_GIT,
    "census_sha256": CENSUS_SHA256,
    "packet_sha256": DESIGN_PACKET_SHA256,
    "human_manifest_sha256": HUMAN_MANIFEST_SHA256,
    "census_rows": 768,
    "outcomes_computed": False,
    "independent_review": True,
    "one_card_controller_implementation_authorized": True,
    "solver_or_screen_launch_authorized": False,
    "training_authorized": False,
    "strength_claim": False,
    "production_promotion": False,
    "verdict": "PASS",
}


class ControllerRefused(RuntimeError):
    """The proposed controller differs from the independently passed design."""


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"))
            + "\n").encode()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: str | os.PathLike[str]) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_hex_digest(value: object, length: int = 64) -> bool:
    return (isinstance(value, str) and len(value) == length
            and all(char in "0123456789abcdef" for char in value))


def is_regular_unlinked(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return False
    return (stat.S_ISREG(info.st_mode) and info.st_nlink == 1
            and not path.is_symlink())


def load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise ControllerRefused(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ControllerRefused(f"JSON root is not an object: {path}")
    return value


def load_frozen_json(path: Path) -> dict:
    if not is_regular_unlinked(path):
        raise ControllerRefused(f"artifact is not regular/unlinked: {path}")
    return load_json(path)


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, check=True, capture_output=True, text=True,
    ).stdout.strip()


def require_ancestor(commit: str) -> None:
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", commit, "HEAD"], cwd=REPO,
        capture_output=True,
    )
    if result.returncode:
        raise ControllerRefused(f"required commit is not an ancestor: {commit}")


def producer_identity(*, smoke: bool) -> dict:
    head = git("rev-parse", "HEAD")
    dirty = bool(git("status", "--porcelain"))
    if dirty and not smoke:
        raise ControllerRefused("real controller freeze refuses a dirty tree")
    return {
        "git": head,
        "tree_dirty": dirty,
        "promotable": not smoke,
        "controller_script_sha256": sha256_file(SCRIPT),
    }


def require_compiled_runtime() -> dict:
    if os.environ.get("SHENGJI_FAST") != "1":
        raise ControllerRefused("set SHENGJI_FAST=1")
    if os.environ.get("SHENGJI_REQUIRE_VOIDS") != "1":
        raise ControllerRefused("set SHENGJI_REQUIRE_VOIDS=1")
    enabled = [name for name in SAMPLER_FLAGS if os.environ.get(name)]
    if enabled:
        raise ControllerRefused(
            f"experimental sampler/ballot flags must be unset: {enabled}")
    from shengji.engine import combos, fast
    if not fast.HAVE_FAST or combos.decompose is not fast.decompose:
        raise ControllerRefused("compiled engine requested but not active")
    return {
        "fast_engine": True,
        "require_voids": True,
        "experimental_sampler_flags": [],
        "fast_router_sha256": sha256_file(fast.__file__),
        "compiled_fast_binary_sha256": sha256_file(fast._fast.__file__),
    }


def runtime_sources() -> dict:
    sources = {}
    for logical_path in SOURCE_PATHS:
        path = REPO / logical_path
        if not is_regular_unlinked(path):
            raise ControllerRefused(
                f"runtime source is not regular/unlinked: {logical_path}")
        sources[logical_path] = sha256_file(path)
    return dict(sorted(sources.items()))


def marker_claim(path: Path, marker: str) -> dict:
    if not is_regular_unlinked(path):
        raise ControllerRefused("review record is not regular/unlinked")
    matches = [line[len(marker):] for line in path.read_text().splitlines()
               if line.startswith(marker)]
    if len(matches) != 1:
        raise ControllerRefused(
            f"review record must contain exactly one {marker.strip()} marker")
    try:
        claim = json.loads(matches[0])
    except ValueError as exc:
        raise ControllerRefused("review marker is not valid JSON") from exc
    if not isinstance(claim, dict):
        raise ControllerRefused("review marker is not an object")
    return claim


def require_design_review(path: Path) -> dict:
    claim = marker_claim(path, "S3C_EXACT_ROOT_CURRICULUM_V1_REVIEW ")
    if claim != DESIGN_REVIEW_CLAIM:
        raise ControllerRefused("S3c curriculum review marker drift")
    require_ancestor(DESIGN_REVIEW_GIT)
    return claim


def validate_design_packet(path: Path) -> dict:
    if (not is_regular_unlinked(path)
            or sha256_file(path) != DESIGN_PACKET_SHA256):
        raise ControllerRefused("S3c design packet identity drift")
    packet = load_json(path)
    if (packet.get("schema") != DESIGN.PACKET_SCHEMA
            or packet.get("packet_id") != DESIGN.PACKET_ID
            or packet.get("packet_sha256") != DESIGN_PACKET_INTERNAL_SHA256
            or packet.get("producer", {}).get("git") != DESIGN_PRODUCER_GIT
            or packet.get("parent", {}).get("census_sha256") != CENSUS_SHA256
            or packet.get("parent", {}).get("embedded_census_sha256")
            != CENSUS_INTERNAL_SHA256
            or packet.get("parent", {}).get("human_manifest_sha256")
            != HUMAN_MANIFEST_SHA256):
        raise ControllerRefused("S3c design packet structure/parent drift")
    one = packet.get("curriculum", {}).get("one_card", {})
    if one != {
        "purpose": "mechanics_replay_and_capacity_only",
        "census_roots": 256,
        "reviewed_feasibility_roots": ROOT_COUNT,
        "root_selection": (
            "16 domain-hash-smallest census rows per within-trick "
            "offset, frozen before solver work"),
        "worlds_per_root": WORLDS_PER_ROOT,
        "max_nodes_per_world_session": MAX_NODES_PER_WORLD_SESSION,
        "utility_or_strength_gate": False,
        "required_outputs": [
            "exact replay/state digest",
            "complete legal root-action count",
            "accepted-world and sampler refusal counts",
            "exact nodes/cache hits and overflow counts",
        ],
        "pass_next_authority": "AUTHORIZE_TWO_CARD_MECHANISM_PACKET_REVIEW",
    }:
        raise ControllerRefused("S3c one-card curriculum drift")
    shared = packet.get("shared_execution_contract", {})
    required_true = {
        "complete_legal_root_action_enumeration",
        "same_sampled_worlds_for_all_root_actions",
        "zero_sampler_refusal_and_zero_exact_overflow_required",
        "per_root_nodes_cache_hits_actions_and_worlds_required",
        "partial_root_or_world_dose_cannot_publish_a_metric",
        "complete_round_strength_required_before_policy_use",
    }
    if (any(shared.get(key) is not True for key in required_true)
            or shared.get("production_champion") != "mc-s0-report-lcb"
            or packet.get("authority", {}).get(
                "solver_or_screen_launch_authorized") is not False
            or packet.get("authority", {}).get(
                "one_card_controller_implementation_authorized") is not False
            or packet.get("authority", {}).get("outcomes_computed") is not False
            or packet.get("authority", {}).get("strength_claim") is not False):
        raise ControllerRefused("S3c design authority/execution drift")
    return packet


def validate_census(path: Path) -> dict:
    if not is_regular_unlinked(path) or sha256_file(path) != CENSUS_SHA256:
        raise ControllerRefused("S3c census identity drift")
    try:
        census = DESIGN.validate_census(path, CENSUS_SHA256)
    except DESIGN.S3CDesignError as exc:
        raise ControllerRefused(str(exc)) from exc
    if (census.get("census_sha256") != CENSUS_INTERNAL_SHA256
            or census.get("producer", {}).get("git") != DESIGN_PRODUCER_GIT
            or len(census.get("rows", [])) != 768):
        raise ControllerRefused("S3c census parent/population drift")
    return census


def _domain_hash(domain: bytes, value: object) -> str:
    return sha256_bytes(domain + canonical_json(value))


def select_roots(census: Mapping[str, object]) -> list[dict]:
    rows = census.get("rows")
    if not isinstance(rows, list):
        raise ControllerRefused("S3c census rows missing")
    selected = []
    for offset in DESIGN.OFFSETS:
        eligible = [row for row in rows
                    if row.get("max_hand_cards") == MAX_HAND_CARDS
                    and row.get("within_trick_offset") == offset]
        if len(eligible) != DESIGN.ROWS_PER_OFFSET:
            raise ControllerRefused(
                f"one-card offset {offset} population differs from 64")
        ranked = sorted(
            ((_domain_hash(ROOT_SELECTION_DOMAIN, row["state_id"]), row)
             for row in eligible),
            key=lambda item: (item[0], item[1]["state_id"]),
        )
        for rank, (selection_hash, row) in enumerate(
                ranked[:ROOTS_PER_OFFSET], 1):
            if row.get("legal_action_count") != 1:
                raise ControllerRefused("selected one-card root is not forced")
            selected.append({
                "state_id": row["state_id"],
                "deal_seed": row["deal_seed"],
                "within_trick_offset": offset,
                "actor_seat": row["actor_seat"],
                "actor_role": row["actor_role"],
                "surface": row["surface"],
                "state_sha256": row["state_sha256"],
                "legal_action_count": row["legal_action_count"],
                "legal_action_size_counts": row["legal_action_size_counts"],
                "selection_rank_within_offset": rank,
                "selection_hash": selection_hash,
            })
    if len(selected) != ROOT_COUNT:
        raise ControllerRefused("one-card selected-root count drift")
    state_ids = [root["state_id"] for root in selected]
    deal_seeds = [root["deal_seed"] for root in selected]
    if len(set(state_ids)) != ROOT_COUNT or len(set(deal_seeds)) != ROOT_COUNT:
        raise ControllerRefused("one-card roots are not deal-disjoint")
    return sorted(selected, key=lambda root: root["state_id"])


def world_seed(state_id: str, world_index: int) -> int:
    if not 0 <= world_index < WORLDS_PER_ROOT:
        raise ControllerRefused("world index outside one-card schedule")
    raw = hashlib.sha256(
        WORLD_SEED_DOMAIN + canonical_json([state_id, world_index])
    ).digest()[:8]
    return int.from_bytes(raw, "big")


def build_schedule(census: Mapping[str, object]) -> dict:
    roots = []
    seeds = []
    for root in select_roots(census):
        item = dict(root)
        item["worlds"] = [
            {"index": index, "seed": world_seed(root["state_id"], index)}
            for index in range(WORLDS_PER_ROOT)
        ]
        seeds.extend(world["seed"] for world in item["worlds"])
        roots.append(item)
    if len(seeds) != WORLD_COUNT or len(set(seeds)) != WORLD_COUNT:
        raise ControllerRefused("one-card world schedule is not globally unique")
    schedule = {
        "root_selection": (
            "16 sha256-domain-smallest band-1 rows per within-trick offset; "
            "then canonical state-id order"),
        "root_selection_domain_sha256": sha256_bytes(ROOT_SELECTION_DOMAIN),
        "world_seed_derivation": (
            "first 64 bits of sha256(domain || canonical-json([state_id,index]))"
        ),
        "world_seed_domain_sha256": sha256_bytes(WORLD_SEED_DOMAIN),
        "root_count": ROOT_COUNT,
        "roots_per_offset": ROOTS_PER_OFFSET,
        "worlds_per_root": WORLDS_PER_ROOT,
        "world_count": WORLD_COUNT,
        "max_hand_cards": MAX_HAND_CARDS,
        "max_nodes_per_world_session": MAX_NODES_PER_WORLD_SESSION,
        "max_execution_nodes": MAX_EXECUTION_NODES,
        "max_terminal_replay_nodes": MAX_TERMINAL_REPLAY_NODES,
        "max_total_pipeline_nodes": MAX_TOTAL_PIPELINE_NODES,
        "roots": roots,
    }
    schedule["schedule_sha256"] = sha256_bytes(canonical_json(schedule))
    return schedule


def score_free_preflight(schedule: Mapping[str, object]) -> dict:
    rows = []
    offsets = Counter()
    roles = Counter()
    surfaces = Counter()
    for root in schedule["roots"]:
        replayed = DESIGN.prefix_row(
            int(root["deal_seed"]), MAX_HAND_CARDS,
            int(root["within_trick_offset"]),
        )
        expected = {
            key: root[key] for key in (
                "state_id", "deal_seed", "within_trick_offset", "actor_seat",
                "actor_role", "surface", "state_sha256",
                "legal_action_count", "legal_action_size_counts",
            )
        }
        actual = None if replayed is None else {
            key: replayed[key] for key in expected
        }
        if actual != expected:
            raise ControllerRefused(
                f"score-free selected-root replay drift: {root['state_id']}")
        offsets[str(root["within_trick_offset"])] += 1
        roles[str(root["actor_role"])] += 1
        surfaces[str(root["surface"])] += 1
        rows.append([
            root["state_id"], root["state_sha256"],
            root["legal_action_count"], root["selection_hash"],
        ])
    if offsets != Counter({str(offset): ROOTS_PER_OFFSET
                           for offset in DESIGN.OFFSETS}):
        raise ControllerRefused("score-free offset balance drift")
    return {
        "status": "VERIFIED_SCORE_FREE",
        "roots_replayed": len(rows),
        "by_offset": dict(sorted(offsets.items())),
        "by_role": dict(sorted(roles.items())),
        "by_surface": dict(sorted(surfaces.items())),
        "root_geometry_sha256": sha256_bytes(canonical_json(rows)),
        "worlds_sampled": 0,
        "exact_solver_sessions": 0,
        "exact_solver_nodes": 0,
        "action_values_computed": False,
        "outcomes_computed": False,
    }


def command_templates() -> dict:
    common = [
        "--expected-git", "{git}",
        "--controller-packet", "{controller_packet}",
        "--expected-controller-packet-sha256", "{controller_packet_sha256}",
        "--design-packet", "{design_packet}",
        "--census", "{census}",
        "--design-review-record", "{design_review_record}",
    ]
    runtime = ["{python}", "server/scripts/s3c_one_card_runtime.py"]
    namespace = f"server/runs/logs/{RUN_ID}"
    return {
        "admit_once": [
            *runtime, "admit", *common,
            "--controller-review-record", "{controller_review_record}",
            "--namespace", namespace,
            "--out", f"{namespace}/execution-receipt.json",
        ],
        "run_once": [
            *runtime, "run", *common,
            "--execution-receipt", "{execution_receipt}",
            "--expected-execution-receipt-sha256",
            "{execution_receipt_sha256}",
            "--out", f"{namespace}/capacity-result.json",
            "--progress-every", "1",
        ],
        "terminal_verify": [
            *runtime, "verify-result", *common,
            "--execution-receipt", "{execution_receipt}",
            "--expected-execution-receipt-sha256",
            "{execution_receipt_sha256}",
            "--result", f"{namespace}/capacity-result.json",
            "--out", f"{namespace}/terminal-final.json",
            "--replay-every-complete-root",
        ],
    }


def result_contract(schedule: Mapping[str, object]) -> dict:
    return {
        "single_process_atomic_result": True,
        "durable_one_shot_admission_slot": (
            "server/runs/locks/s3c-one-card-capacity-173m-v1.consumed.json"),
        "admission_slot_published_before_receipt": True,
        "result_schema": RESULT_SCHEMA,
        "terminal_schema": FINAL_SCHEMA,
        "every_selected_root_exactly_once": True,
        "root_is_refusal_unit": True,
        "no_retry_or_replacement": True,
        "complete_root_requires": {
            "public_state_replay_exact": True,
            "legal_root_action_count": 1,
            "scheduled_worlds": WORLDS_PER_ROOT,
            "one_sampler_attempt_per_world": True,
            "one_exact_session_per_accepted_world": True,
            "max_nodes_per_world_session": MAX_NODES_PER_WORLD_SESSION,
            "offset_0_to_2_exact_frontiers_per_world": 1,
            "offset_3_exact_frontiers_per_world": 0,
        },
        "published_capacity_fields": [
            "state/action/world digests", "sampler counters",
            "exact attempts/successes/refusals/overflows/sessions",
            "exact nodes/cache hits/frontiers",
        ],
        "forbidden_result_fields": [
            "sampled_hands", "buried_cards", "attacker_points",
            "action_value", "utility", "estimand", "winner",
        ],
        "exact_solver_terminal_scores_computed_internally_but_never_published":
            True,
        "utility_or_strength_gate": False,
        "completion_gate": {
            "all_roots_complete": (
                "AUTHORIZE_TWO_CARD_MECHANISM_PACKET_REVIEW"),
            "any_root_refused": "REFUSED_INCOMPLETE_NO_NEXT_AUTHORITY",
        },
        "terminal_verifier": {
            "reopen_every_identity": True,
            "replay_every_public_root": True,
            "rerun_every_complete_root_world": True,
            "never_retry_refused_root_worlds": True,
            "compare_capacity_record_exactly": True,
        },
        "schedule_sha256": schedule["schedule_sha256"],
    }


def build_controller_packet(design_path: Path, census_path: Path,
                            review_record: Path, *, smoke: bool) -> dict:
    design = validate_design_packet(design_path)
    census = validate_census(census_path)
    review = require_design_review(review_record)
    schedule = build_schedule(census)
    preflight = score_free_preflight(schedule)
    packet = {
        "schema": SCHEMA,
        "packet_id": PACKET_ID,
        "run_id": RUN_ID,
        "producer": producer_identity(smoke=smoke),
        "design": {
            "logical_path": DESIGN_PACKET_LOGICAL_PATH,
            "external_sha256": DESIGN_PACKET_SHA256,
            "internal_sha256": DESIGN_PACKET_INTERNAL_SHA256,
            "producer_git": DESIGN_PRODUCER_GIT,
            "asset_git": DESIGN_ASSET_GIT,
            "review_git": DESIGN_REVIEW_GIT,
            "review_claim": review,
            "one_card_contract": design["curriculum"]["one_card"],
        },
        "census": {
            "logical_path": CENSUS_LOGICAL_PATH,
            "external_sha256": CENSUS_SHA256,
            "internal_sha256": CENSUS_INTERNAL_SHA256,
            "rows": len(census["rows"]),
            "human_manifest_sha256": HUMAN_MANIFEST_SHA256,
        },
        "runtime": require_compiled_runtime(),
        "runtime_sources": runtime_sources(),
        "schedule": schedule,
        "score_free_preflight": preflight,
        "commands": command_templates(),
        "result_contract": result_contract(schedule),
        "review_contract": {
            "schema": REVIEW_SCHEMA,
            "marker": REVIEW_MARKER.strip(),
            "required_verdict": "PASS",
            "pass_authorizes": "one one-card mechanics/capacity receipt only",
            "hold_authorizes": "no execution",
            "required_claim_fields": [
                "schema", "git", "controller_script_sha256",
                "runtime_script_sha256", "packet_sha256",
                "design_packet_sha256", "census_sha256",
                "design_review_git", "schedule_sha256",
                "root_geometry_sha256", "roots", "worlds",
                "max_execution_nodes", "max_terminal_replay_nodes",
                "score_free_preflight_verified",
                "worlds_sampled_before_review",
                "exact_solver_sessions_before_review",
                "outcomes_computed_before_review", "independent_review",
                "one_card_capacity_execution_authorized",
                "two_card_packet_review_authorized",
                "solver_or_strength_screen_authorized",
                "training_authorized", "strength_claim",
                "production_promotion", "production_deployment", "verdict",
            ],
            "packet_sha256_field": "external SHA-256 of canonical packet file",
        },
        "authority": {
            "score_free": True,
            "worlds_sampled": False,
            "exact_solver_invoked": False,
            "action_values_computed": False,
            "outcomes_computed": False,
            "controller_review_authorized": True,
            "one_card_capacity_execution_authorized": False,
            "two_card_packet_review_authorized": False,
            "solver_or_strength_screen_authorized": False,
            "training_authorized": False,
            "strength_claim": False,
            "production_promotion": False,
            "production_deployment": False,
        },
    }
    packet["packet_sha256"] = sha256_bytes(canonical_json(packet))
    return packet


def packet_problems(actual: dict, expected: dict) -> list[str]:
    problems = []
    if actual != expected:
        problems.append("controller packet full recomputation drift")
    authority = actual.get("authority", {})
    if (authority != expected.get("authority")
            or authority.get("score_free") is not True
            or authority.get("worlds_sampled") is not False
            or authority.get("exact_solver_invoked") is not False
            or authority.get("action_values_computed") is not False
            or authority.get("outcomes_computed") is not False
            or authority.get("one_card_capacity_execution_authorized")
            is not False
            or authority.get("two_card_packet_review_authorized") is not False
            or authority.get("solver_or_strength_screen_authorized") is not False
            or authority.get("training_authorized") is not False
            or authority.get("strength_claim") is not False
            or authority.get("production_promotion") is not False
            or authority.get("production_deployment") is not False):
        problems.append("controller authority widened")
    preflight = actual.get("score_free_preflight", {})
    if (preflight.get("worlds_sampled") != 0
            or preflight.get("exact_solver_sessions") != 0
            or preflight.get("exact_solver_nodes") != 0
            or preflight.get("action_values_computed") is not False
            or preflight.get("outcomes_computed") is not False):
        problems.append("controller preflight is not score-free")
    return sorted(set(problems))


def publish_exclusive(path: Path, payload: Mapping[str, object]) -> None:
    partial = Path(str(path) + ".partial")
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.path.lexists(path) or os.path.lexists(partial):
        raise ControllerRefused(f"refusing to overwrite {path}")
    try:
        with partial.open("xb") as handle:
            handle.write(canonical_json(payload))
            handle.flush()
            os.fsync(handle.fileno())
        os.link(partial, path)
        partial.unlink()
    except BaseException:
        if partial.exists() and not path.exists():
            partial.unlink()
        raise
    if not is_regular_unlinked(path):
        raise ControllerRefused("published artifact is not regular/unlinked")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    for command in ("freeze", "verify"):
        child = commands.add_parser(command)
        child.add_argument("--design-packet", required=True)
        child.add_argument("--census", required=True)
        child.add_argument("--design-review-record", required=True)
        child.add_argument("--controller-packet", required=True)
        child.add_argument("--expected-git")
        child.add_argument("--smoke", action="store_true")
        if command == "verify":
            child.add_argument("--expected-controller-packet-sha256")
    return root


def main(argv: list[str] | None = None) -> None:
    args = parser().parse_args(argv)
    if args.expected_git and git("rev-parse", "HEAD") != args.expected_git:
        raise ControllerRefused("producer Git differs from expected Git")
    expected = build_controller_packet(
        Path(args.design_packet), Path(args.census),
        Path(args.design_review_record), smoke=args.smoke,
    )
    packet_path = Path(args.controller_packet)
    if args.command == "freeze":
        publish_exclusive(packet_path, expected)
        print(json.dumps({
            "status": "FROZEN_FOR_CONTROLLER_REVIEW",
            "packet": str(packet_path),
            "sha256": sha256_file(packet_path),
            "roots_replayed": expected["score_free_preflight"][
                "roots_replayed"],
            "worlds_sampled": 0,
            "exact_solver_sessions": 0,
            "one_card_capacity_execution_authorized": False,
        }, sort_keys=True))
        return
    if not is_regular_unlinked(packet_path):
        raise ControllerRefused("controller packet is not regular/unlinked")
    if (args.expected_controller_packet_sha256
            and sha256_file(packet_path)
            != args.expected_controller_packet_sha256):
        raise ControllerRefused("controller packet SHA-256 drift")
    problems = packet_problems(load_json(packet_path), expected)
    if problems:
        raise ControllerRefused("; ".join(problems))
    print(json.dumps({
        "status": "VERIFIED_FOR_CONTROLLER_REVIEW",
        "packet": str(packet_path),
        "sha256": sha256_file(packet_path),
        "roots_replayed": expected["score_free_preflight"]["roots_replayed"],
        "worlds_sampled": 0,
        "exact_solver_sessions": 0,
        "one_card_capacity_execution_authorized": False,
    }, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except (ControllerRefused, DESIGN.S3CDesignError, OSError, ValueError,
            subprocess.SubprocessError) as exc:
        print(f"REFUSING: {exc}", file=sys.stderr)
        raise SystemExit(3) from exc
