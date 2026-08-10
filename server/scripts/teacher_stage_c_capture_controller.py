#!/usr/bin/env python3
"""Freeze the score-free Teacher Stage-C capture controller.

The passed Stage-C design fixes a 2,048-state curriculum but deliberately does
not authorize state capture.  This controller turns that design into one
finite, replayable capture plan.  ``freeze`` and ``verify`` reopen the exact
design, dependency rebind, replacement H0/S3c packets, external PASS markers,
evaluation exclusions, live champion, and executable capture runtime.  They do
not deal a game, capture a state, sample a belief world, compute an outcome,
label an action, train a model, or promote a policy.

After an independent controller review, the separately hashed runtime may
consume one durable admission and scan the exact seed blocks.  A later dataset
freeze must fill every split/stratum/cross-cell quota without extension and
must publish exactly one replayable state per deal.  Labels remain a separate
reviewed stage.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
import sys
from pathlib import Path
from typing import Mapping, Sequence


SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[1]
REPO = SCRIPT.parents[2]
sys.path.insert(0, str(SCRIPT.parent))

import live_champion_parent as LIVE_PARENT  # noqa: E402
import teacher_stage_c_controller_rebind as REBIND  # noqa: E402
import teacher_stage_c_design as DESIGN  # noqa: E402


SCHEMA = "teacher-stage-c-capture-controller-v3"
PACKET_ID = "teacher-v3-hard-tail-stage-c-capture-controller-v3"
RUN_ID = "teacher-v3-hard-tail-stage-c-capture-v3"
REVIEW_SCHEMA = "teacher-stage-c-capture-controller-review-v3"
REVIEW_MARKER = "TEACHER_STAGE_C_CAPTURE_CONTROLLER_V3_REVIEW "
RECEIPT_SCHEMA = "teacher-stage-c-capture-receipt-v3"
ADMISSION_SCHEMA = "teacher-stage-c-capture-admission-v3"
SHARD_SCHEMA = "teacher-stage-c-capture-shard-v3"
DATASET_SCHEMA = "teacher-stage-c-state-set-v3"
GENERATION_WITNESS_SCHEMA = "teacher-stage-c-generation-witness-v3"
VERIFICATION_SCHEMA = "teacher-stage-c-capture-terminal-verification-v3"

BASE_PACKET_SHA256 = REBIND.BASE_PACKET_SHA256
REBIND_PACKET_SHA256 = (
    "b60c4298493794b6de0ffe6907e8b92fb24f4bab6d56cc4c653eb1c67a1b7b18"
)
H0_PACKET_SHA256 = REBIND.H0_PACKET_SHA256
S3C_PACKET_SHA256 = REBIND.S3C_PACKET_SHA256
SHARDS_PER_SPLIT = 8
CAPTURE_SHARDS = SHARDS_PER_SPLIT * 3
ACTOR_POLICY = "smart"
UNCERTAINTY_WORLDS = 30
UNCERTAINTY_ATTEMPT_FACTOR = 10
UNCERTAINTY_RESERVOIR_MULTIPLIER = 4
# Preserve v2's pre-outcome population/RNG estimand.  V3 changes validation
# and evidence namespace only; it must not opportunistically redraw the data
# after an adversarial review found a proof defect.
POPULATION_EXPERIMENT_ID = "teacher-v3-hard-tail-stage-c-capture-v2"
EXPERIMENT_ID = POPULATION_EXPERIMENT_ID
TERMINAL_DISPOSITION_REPLAY_DEALS = 750_000
TERMINAL_DISPOSITION_REPLAY_WORKERS = 8
TERMINAL_DISPOSITION_PROGRESS_EVERY = 250

SAMPLER_FLAGS = (
    "SHENGJI_WEIGHTED_SPLITS",
    "SHENGJI_UNIFORM_DEAL",
    "SHENGJI_PHYSICAL_FILLS",
    "SHENGJI_ALLOW_BALLOT_MISMATCH",
)

# These are the committed evaluation/state assets present on main.  Capture
# seed ranges are disjoint, but reopening their bytes prevents a later asset
# rewrite from making an old "zero overlap" assertion look current.
EVALUATION_ASSET_PATHS = (
    "server/rl_data/corpus_split.v1.json",
    "server/rl_data/corpus_split_late.v1.json",
    "server/rl_data/deep_lead_split.v1.json",
    "server/rl_data/deep_leads.v1.manifest.json",
    "server/rl_data/pilot_states.v1.json",
    "server/rl_data/pilot_states.v2.json",
    "server/rl_data/pilot_states.v3.json",
    "server/rl_data/pilot_dev512.v1.json",
    "server/rl_data/pilot_dev512.v2.json",
    "server/rl_data/pilot_dev512.v3.json",
    "server/rl_data/pilot_dev512.v4.json",
    "server/rl_data/pilot_dev512.v5.json",
    "server/rl_data/pilot_dev512.v6.json",
    "server/rl_data/pilot_calib512.v1.json",
    "server/rl_data/pilot_calib512.v2.json",
    "server/rl_data/pilot_calib512.v3.json",
    "server/rl_data/pilot_calib512.v4.json",
    "server/rl_data/pilot_calib512.v5.json",
    "server/rl_data/pilot_calib512.v6.json",
)

SOURCE_PATHS = (
    ".gitignore",
    "server/scripts/live_champion_parent.py",
    "server/scripts/teacher_stage_c_capture_runtime.py",
    "server/scripts/teacher_stage_c_controller_rebind.py",
    "server/scripts/teacher_stage_c_design.py",
    "server/scripts/teacher_v1_states.py",
    "server/shengji/ai/bury.py",
    "server/shengji/ai/mcbot.py",
    "server/shengji/ai/memory.py",
    "server/shengji/ai/point_banking.py",
    "server/shengji/ai/registry.py",
    "server/shengji/ai/smart.py",
    "server/shengji/engine/ballot.py",
    "server/shengji/engine/game.py",
    "server/shengji/engine/legal.py",
    "server/shengji/engine/round.py",
    "server/shengji/pilot_arms.py",
    "server/shengji/rl/actions.py",
    "server/shengji/rl/encode.py",
    "server/shengji/rl/npnet.py",
    "server/shengji/rl/torch_policy.py",
    "server/shengji/teacher_v1.py",
)

REVIEW_FIELDS = (
    "schema", "git", "controller_script_sha256", "runtime_script_sha256",
    "packet_sha256", "base_stage_c_sha256", "rebind_sha256",
    "h0_controller_sha256", "s3c_controller_sha256", "live_parent_schema",
    "live_parent_policy", "v11_checkpoint_sha256", "schedule_sha256",
    "exclusion_manifest_sha256",
    "states", "design_states", "calib_states", "report_states",
    "play_states", "bury_states", "scan_deals", "capture_shards",
    "population_experiment_id", "terminal_disposition_replay_deals",
    "terminal_disposition_replay_workers",
    "terminal_disposition_progress_every",
    "uncertainty_worlds", "max_uncertainty_candidate_worlds",
    "max_uncertainty_attempts",
    "max_terminal_replay_uncertainty_candidate_worlds",
    "max_terminal_replay_uncertainty_attempts",
    "max_total_uncertainty_candidate_worlds",
    "max_total_uncertainty_attempts",
    "complete_generation_witness", "terminal_recomputes_state_identity",
    "terminal_reconciles_work", "terminal_replays_all_scan_dispositions",
    "worlds_sampled_before_review", "states_captured_before_review",
    "outcomes_computed_before_review", "independent_review",
    "one_capture_execution_authorized", "labels_authorized",
    "training_authorized", "strength_claim", "production_promotion",
    "production_deployment", "verdict",
)


class ControllerRefused(RuntimeError):
    """A Stage-C capture input, plan, or authority boundary drifted."""


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"))
            + "\n").encode()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: str | os.PathLike[str]) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def self_hash(payload: Mapping[str, object], field: str = "packet_sha256") -> str:
    return sha256_bytes(canonical_json({
        key: value for key, value in payload.items() if key != field
    }))


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


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, check=True, capture_output=True, text=True,
    ).stdout.strip()


def marker_claim(path: Path, marker: str) -> dict:
    if not is_regular_unlinked(path):
        raise ControllerRefused("review record is not regular/unlinked")
    try:
        lines = path.read_text().splitlines()
    except OSError as exc:
        raise ControllerRefused("cannot read review record") from exc
    matches = [line[len(marker):] for line in lines if line.startswith(marker)]
    if len(matches) != 1:
        raise ControllerRefused(
            f"review record must contain exactly one {marker.strip()} marker")
    try:
        claim = json.loads(matches[0])
    except ValueError as exc:
        raise ControllerRefused("review marker is not valid JSON") from exc
    if not isinstance(claim, dict):
        raise ControllerRefused("review marker claim is not an object")
    return claim


def admission_slot_logical_path() -> str:
    return f"server/runs/locks/{RUN_ID}.consumed.json"


def require_admission_slot_ignored() -> dict:
    logical = admission_slot_logical_path()
    result = subprocess.run(
        ["git", "check-ignore", "--quiet", logical], cwd=REPO,
        capture_output=True,
    )
    if result.returncode != 0:
        raise ControllerRefused(f"admission slot is not Git-ignored: {logical}")
    return {"logical_path": logical, "gitignored": True}


def require_runtime_mode() -> dict:
    if os.environ.get("SHENGJI_FAST") != "1":
        raise ControllerRefused("set SHENGJI_FAST=1")
    if os.environ.get("SHENGJI_REQUIRE_VOIDS") != "1":
        raise ControllerRefused("set SHENGJI_REQUIRE_VOIDS=1")
    enabled = [name for name in SAMPLER_FLAGS if os.environ.get(name)]
    if enabled:
        raise ControllerRefused(
            f"experimental sampler/ballot flags must be unset: {enabled}")
    sys.path.insert(0, str(SERVER))
    from shengji.engine import combos, fast
    if not fast.HAVE_FAST or combos.decompose is not fast.decompose:
        raise ControllerRefused("compiled engine requested but not active")
    return {
        "environment": {"SHENGJI_FAST": "1", "SHENGJI_REQUIRE_VOIDS": "1"},
        "experimental_sampler_flags": [],
        "fast_engine": True,
        "fast_router_sha256": sha256_file(fast.__file__),
        "compiled_fast_binary_sha256": sha256_file(fast._fast.__file__),
    }


def producer_identity(*, smoke: bool) -> dict:
    git = _git("rev-parse", "HEAD")
    require_admission_slot_ignored()
    dirty = bool(_git("status", "--porcelain", "--untracked-files=all"))
    if dirty and not smoke:
        raise ControllerRefused("real capture-controller freeze refuses dirty tree")
    return {
        "git": git,
        "tree_dirty": dirty,
        "promotable": not smoke,
        "controller_script_sha256": sha256_file(SCRIPT),
    }


def _validate_rebind(
    base_path: Path,
    rebind_path: Path,
    h0_path: Path,
    s3c_path: Path,
    review_record: Path,
) -> tuple[dict, dict, dict, dict]:
    try:
        base, base_claim = REBIND.validate_base(base_path, review_record)
        h0, h0_claim = REBIND.validate_h0(h0_path, review_record)
        s3c, s3c_claim = REBIND.validate_s3c(s3c_path, review_record)
    except REBIND.RebindRefused as exc:
        raise ControllerRefused(str(exc)) from exc
    if (not is_regular_unlinked(rebind_path)
            or sha256_file(rebind_path) != REBIND_PACKET_SHA256):
        raise ControllerRefused("Stage-C rebind external SHA-256 drift")
    rebind = load_json(rebind_path)
    authority = rebind.get("authority", {})
    if (rebind.get("schema") != REBIND.SCHEMA
            or rebind.get("packet_id") != REBIND.PACKET_ID
            or rebind.get("packet_sha256") != REBIND.self_hash(rebind)
            or rebind.get("base_stage_c", {}).get("external_sha256")
            != BASE_PACKET_SHA256
            or rebind.get("base_stage_c", {}).get("curriculum_commitments")
            != REBIND.curriculum_commitments(base)
            or rebind.get("replacement_bindings", {}).get("h0", {}).get(
                "external_sha256") != H0_PACKET_SHA256
            or rebind.get("replacement_bindings", {}).get("h0", {}).get(
                "review_claim") != h0_claim
            or rebind.get("replacement_bindings", {}).get("s3c", {}).get(
                "external_sha256") != S3C_PACKET_SHA256
            or rebind.get("replacement_bindings", {}).get("s3c", {}).get(
                "review_claim") != s3c_claim
            or authority.get("state_capture_authorized") is not False
            or authority.get("labels_authorized") is not False
            or authority.get("training_authorized") is not False):
        raise ControllerRefused("Stage-C rebind identity/authority drift")
    claim = marker_claim(review_record, REBIND.REVIEW_MARKER)
    if claim != REBIND.expected_review_claim(rebind, REBIND_PACKET_SHA256):
        raise ControllerRefused("Stage-C rebind PASS marker drift")
    if base_claim != rebind["base_stage_c"]["review_claim"]:
        raise ControllerRefused("base Stage-C review claim differs from rebind")
    return base, rebind, h0, s3c


def _seed_values(value: object) -> set[int]:
    seeds: set[int] = set()
    if isinstance(value, dict):
        assign = value.get("assign")
        if isinstance(assign, dict):
            for key in assign:
                try:
                    seeds.add(int(key))
                except (TypeError, ValueError):
                    pass
        for key in ("states", "rows"):
            rows = value.get(key)
            if isinstance(rows, list):
                for row in rows:
                    if isinstance(row, dict):
                        for name in ("seed", "deal_seed"):
                            raw = row.get(name)
                            if isinstance(raw, int):
                                seeds.add(raw)
    return seeds


def evaluation_exclusion_manifest(paths: Sequence[Path]) -> dict:
    if len(paths) != len(EVALUATION_ASSET_PATHS):
        raise ControllerRefused("evaluation exclusion asset count drift")
    entries = []
    all_seeds: set[int] = set()
    for logical, path in zip(EVALUATION_ASSET_PATHS, paths, strict=True):
        if not is_regular_unlinked(path):
            raise ControllerRefused(f"evaluation asset is not regular: {logical}")
        try:
            payload = json.loads(path.read_bytes())
        except (OSError, ValueError) as exc:
            raise ControllerRefused(f"cannot parse evaluation asset {logical}") from exc
        seeds = _seed_values(payload)
        all_seeds.update(seeds)
        entries.append({
            "logical_path": logical,
            "sha256": sha256_file(path),
            "seed_identities_found": len(seeds),
        })
    capture_ranges = [
        range(int(item["seed_start"]),
              int(item["seed_start"]) + int(item["scan_deals"]))
        for item in DESIGN._split_geometry().values()
    ]
    overlap = sorted(seed for seed in all_seeds
                     if any(seed in block for block in capture_ranges))
    if overlap:
        raise ControllerRefused(
            f"Stage-C capture range overlaps evaluation deals: {overlap[:8]}")
    payload = {
        "assets": entries,
        "asset_count": len(entries),
        "known_seed_identities": len(all_seeds),
        "known_seed_identities_sha256": sha256_bytes(canonical_json(
            sorted(all_seeds))),
        "capture_seed_overlap": 0,
    }
    payload["manifest_sha256"] = sha256_bytes(canonical_json(payload))
    return payload


def _phase_cells(stratum: str, quota: int) -> list[dict]:
    cells = []
    if stratum in {"ordinary_anchor", "champion_uncertainty",
                   "proposal_disagreement"}:
        values = [(phase, role, surface)
                  for phase in ("early", "mid", "late")
                  for role in ("attacker", "defender")
                  for surface in ("lead", "follow")]
    elif stratum == "exact_late_eligible":
        values = [("late", role, surface)
                  for role in ("attacker", "defender")
                  for surface in ("lead", "follow")]
    elif stratum == "point_banking_opportunity":
        values = [("any", role, "follow")
                  for role in ("attacker", "defender")]
    else:
        raise ControllerRefused(f"unknown play stratum {stratum}")
    if quota % len(values):
        raise ControllerRefused(f"quota {quota} is not equal across {stratum}")
    for phase, role, surface in values:
        cells.append({
            "surface_type": "play", "stratum": stratum,
            "phase": phase, "role": role, "surface": surface,
            "quota": quota // len(values),
        })
    return cells


def quota_cells(base: dict) -> dict[str, list[dict]]:
    result: dict[str, list[dict]] = {}
    for split, definition in base["population_contract"]["splits"].items():
        cells = []
        for stratum, quota in definition["play"].items():
            cells.extend(_phase_cells(stratum, int(quota)))
        for stratum, quota in definition["bury"].items():
            cells.append({
                "surface_type": "bury", "stratum": stratum,
                "phase": "pre-play", "role": "defender",
                "surface": "bury", "quota": int(quota),
            })
        if sum(int(cell["quota"]) for cell in cells) != definition["total"]:
            raise ControllerRefused(f"{split} quota-cell total drift")
        for index, cell in enumerate(cells):
            cell["cell_id"] = (
                f"{split}:{cell['surface_type']}:{cell['stratum']}:"
                f"{cell['phase']}:{cell['role']}:{cell['surface']}"
            )
            cell["index"] = index
            # Only N=30 uncertainty pricing is delayed behind a bounded
            # hash reservoir. Proposal/bury eligibility is score-free and is
            # evaluated on every assigned state before hash-smallest retention.
            cell["pre_candidate_limit"] = (
                int(cell["quota"]) * UNCERTAINTY_RESERVOIR_MULTIPLIER
                if cell["stratum"] == "champion_uncertainty" else
                int(cell["quota"])
            )
            cell["diagnostic_candidate_limit"] = (
                cell["pre_candidate_limit"]
                if cell["stratum"] == "champion_uncertainty" else None)
        result[split] = cells
    return result


def build_schedule(base: dict) -> dict:
    cells = quota_cells(base)
    split_order = ("DESIGN", "CALIB", "REPORT")
    shards = []
    for split_index, split in enumerate(split_order):
        definition = base["population_contract"]["splits"][split]
        seed_start = int(definition["seed_start"])
        scan_deals = int(definition["scan_deals"])
        for local in range(SHARDS_PER_SPLIT):
            shards.append({
                "index": split_index * SHARDS_PER_SPLIT + local,
                "split": split,
                "local_shard": local,
                "shard_count_within_split": SHARDS_PER_SPLIT,
                "seed_start": seed_start,
                "scan_deals": scan_deals,
                "first_seed": seed_start + local,
                "seed_stride": SHARDS_PER_SPLIT,
                "seed_count": len(range(
                    seed_start + local, seed_start + scan_deals,
                    SHARDS_PER_SPLIT)),
            })
    uncertainty_candidates = sum(
        int(cell["diagnostic_candidate_limit"] or 0)
        for split_cells in cells.values() for cell in split_cells)
    # Each of the eight interleaved shards keeps its own top pre-diagnostic
    # reservoir. Keeping ``limit`` on every shard guarantees the global top
    # ``limit`` is not lost before merge; the resulting 8x factor is therefore
    # real maximum work, not an optimistic average.
    max_uncertainty_candidate_worlds = (
        uncertainty_candidates
        * SHARDS_PER_SPLIT
        * int(base["candidate_contract"]["max_unique_play_actions"])
        * UNCERTAINTY_WORLDS
    )
    max_uncertainty_attempts = (
        uncertainty_candidates
        * SHARDS_PER_SPLIT
        * UNCERTAINTY_WORLDS
        * UNCERTAINTY_ATTEMPT_FACTOR
    )
    payload = {
        "algorithm": (
            "scan every frozen seed once; preassign one quota cell by a named "
            "hash stream; for score-free cells retain the hash-smallest "
            "eligible rows per shard then globally; for champion uncertainty "
            "retain a fixed hash-smallest pre-diagnostic reservoir per shard, "
            "run N=30 once, then retain hash-smallest eligible rows globally"
        ),
        "split_order": list(split_order),
        "shards_per_split": SHARDS_PER_SPLIT,
        "shard_count": len(shards),
        "shards": shards,
        "quota_cells": cells,
        "actor_policy": ACTOR_POLICY,
        "one_state_per_deal_across_all_splits": True,
        "cell_assignment_before_deal": True,
        "underfilled_action": "TERMINAL_HOLD_NO_EXTENSION",
        "selection_priority": (
            "sha256(experiment_id|split|cell_id|deal_seed|state_id)"
        ),
        "uncertainty": {
            "selection_only_worlds": UNCERTAINTY_WORLDS,
            "candidate_limit_per_cell_per_shard": (
                f"quota*{UNCERTAINTY_RESERVOIR_MULTIPLIER}"
            ),
            "candidate_admission": "hash-smallest before any belief draw",
            "population_estimand": (
                "N=30 boundary eligibility inside the fixed per-shard "
                "hash-smallest pre-diagnostic reservoirs; not all 250k deals"
            ),
            "eligibility": (
                "raw N=30 best is non-incumbent and paired gap is within "
                "2.5 points of the frozen production margin"
            ),
            "world_stream_disjoint_from_all_label_and_audit_streams": True,
            "max_candidate_worlds": max_uncertainty_candidate_worlds,
            "max_attempts": max_uncertainty_attempts,
        },
        "max_uncertainty_candidate_worlds": max_uncertainty_candidate_worlds,
        "max_uncertainty_attempts": max_uncertainty_attempts,
        "max_terminal_replay_uncertainty_candidate_worlds":
            max_uncertainty_candidate_worlds,
        "max_terminal_replay_uncertainty_attempts": max_uncertainty_attempts,
        "max_total_uncertainty_candidate_worlds":
            2 * max_uncertainty_candidate_worlds,
        "max_total_uncertainty_attempts": 2 * max_uncertainty_attempts,
        "scan_deals": sum(int(base["population_contract"]["splits"][name][
            "scan_deals"]) for name in split_order),
    }
    if len(shards) != CAPTURE_SHARDS:
        raise ControllerRefused("capture shard count drift")
    if payload["scan_deals"] != TERMINAL_DISPOSITION_REPLAY_DEALS:
        raise ControllerRefused("capture/terminal-replay deal population drift")
    payload["schedule_sha256"] = sha256_bytes(canonical_json(payload))
    return payload


def runtime_sources() -> dict:
    values = {}
    for logical in SOURCE_PATHS:
        path = REPO / logical
        if not path.is_file() or path.is_symlink():
            raise ControllerRefused(f"capture runtime source missing: {logical}")
        values[logical] = sha256_file(path)
    values[str(SCRIPT.relative_to(REPO))] = sha256_file(SCRIPT)
    return dict(sorted(values.items()))


def _live_parent(base: dict) -> dict:
    try:
        current = LIVE_PARENT.require_portable_live_champion_parent()
        LIVE_PARENT.require_parent_payload(current)
    except LIVE_PARENT.ProtocolRefused as exc:
        raise ControllerRefused("live champion parent did not reopen") from exc
    expected = base["authority_parent"]["live_parent"]["payload"]
    if current != expected:
        raise ControllerRefused("Stage-C design/live champion parent drift")
    return current


def command_templates(schedule: dict) -> dict:
    runtime = "server/scripts/teacher_stage_c_capture_runtime.py"
    shared = [
        "--expected-git", "{git}",
        "--controller-packet", "{controller_packet}",
        "--expected-controller-packet-sha256", "{controller_packet_sha256}",
    ]
    receipt = [
        "--capture-receipt", "{capture_receipt}",
        "--expected-capture-receipt-sha256", "{capture_receipt_sha256}",
    ]
    shards = []
    for shard in schedule["shards"]:
        shards.append([
            "{python}", runtime, "run-shard", *shared, *receipt,
            "--shard-index", str(shard["index"]), "--out",
            f"server/runs/logs/{RUN_ID}/shard-{shard['index']:02d}.json",
        ])
    shard_paths = [
        f"server/runs/logs/{RUN_ID}/shard-{index:02d}.json"
        for index in range(CAPTURE_SHARDS)
    ]
    return {
        "admit_once": [
            "{python}", runtime, "admit", *shared,
            "--review-record", "{review_record}",
            "--namespace", f"server/runs/logs/{RUN_ID}",
            "--out", f"server/runs/logs/{RUN_ID}/capture-receipt.json",
        ],
        "run_shards": shards,
        "freeze_dataset": [
            "{python}", runtime, "freeze-dataset", *shared, *receipt,
            "--shards", *shard_paths, "--out",
            f"server/runs/logs/{RUN_ID}/state-set.json",
        ],
        "verify_dataset": [
            "{python}", runtime, "verify-dataset", *shared, *receipt,
            "--shards", *shard_paths, "--dataset",
            f"server/runs/logs/{RUN_ID}/state-set.json",
            "--replay-every-selected-state",
            "--disposition-replay-workers",
            str(TERMINAL_DISPOSITION_REPLAY_WORKERS),
            "--disposition-progress-every",
            str(TERMINAL_DISPOSITION_PROGRESS_EVERY),
            "--out",
            f"server/runs/logs/{RUN_ID}/terminal-verification.json",
        ],
    }


def build_packet(
    base_path: Path,
    rebind_path: Path,
    h0_path: Path,
    s3c_path: Path,
    review_record: Path,
    evaluation_assets: Sequence[Path],
    *,
    smoke: bool,
) -> dict:
    base, rebind, h0, s3c = _validate_rebind(
        base_path, rebind_path, h0_path, s3c_path, review_record)
    geometry = base["population_contract"]["splits"]
    schedule = build_schedule(base)
    exclusions = evaluation_exclusion_manifest(evaluation_assets)
    sources = runtime_sources()
    live_parent = _live_parent(base)
    runtime_mode = require_runtime_mode()
    packet = {
        "schema": SCHEMA,
        "packet_id": PACKET_ID,
        "run_id": RUN_ID,
        "producer": producer_identity(smoke=smoke),
        "parents": {
            "base_stage_c": {
                "external_sha256": BASE_PACKET_SHA256,
                "internal_sha256": base["packet_sha256"],
                "curriculum_commitments": REBIND.curriculum_commitments(base),
            },
            "controller_rebind": {
                "external_sha256": REBIND_PACKET_SHA256,
                "internal_sha256": rebind["packet_sha256"],
            },
            "h0_v3": {
                "external_sha256": H0_PACKET_SHA256,
                "internal_sha256": h0["packet_sha256"],
                "execution_remains_separately_admitted": True,
            },
            "s3c_v2": {
                "external_sha256": S3C_PACKET_SHA256,
                "internal_sha256": s3c["packet_sha256"],
                "execution_remains_separately_admitted": True,
            },
            "live_parent": live_parent,
        },
        "runtime_mode": runtime_mode,
        "runtime_sources": sources,
        "inputs": {
            "v11pair": h0["inputs"]["v11pair"],
        },
        "evaluation_exclusions": exclusions,
        "schedule": schedule,
        "capture_contract": {
            "experiment_id": EXPERIMENT_ID,
            "validation_namespace_run_id": RUN_ID,
            "population_experiment_id_preserved_from_held_v2": True,
            "actor_policy": ACTOR_POLICY,
            "actor_is_trajectory_generator_not_labeler": True,
            "target_cell_assigned_before_deal": True,
            "one_state_per_deal_across_all_splits": True,
            "fixed_scan_then_hash_smallest_selection": True,
            "all_accepted_states_must_replay": True,
            "all_actions_must_replay_legal": True,
            "candidate_caps": {
                "play": base["candidate_contract"]["max_unique_play_actions"],
                "bury": base["candidate_contract"]["max_unique_bury_actions"],
            },
            "candidate_sources": base["candidate_contract"],
            "conditional_human_rule": (
                "omitted unless a separately frozen deterministic proposer "
                "is supported by the one H0-v3 DESIGN result; raw human "
                "actions never enter fresh CALIB/REPORT"
            ),
            "conditional_s4_s3c_s5": (
                "secondary tags only after exact prerequisite terminal PASS; "
                "absence never changes primary quotas"
            ),
            "selection_features_never_enter_label_or_audit_worlds": True,
            "raw_human_rows_or_human_c1_traffic_consumed": False,
            "underfill_or_overlap": "TERMINAL_HOLD_NO_EXTENSION",
            "retry_or_extension_authorized": False,
        },
        "result_contract": {
            "shard_schema": SHARD_SCHEMA,
            "dataset_schema": DATASET_SCHEMA,
            "required_shards": CAPTURE_SHARDS,
            "required_states": base["population_contract"]["total_states"],
            "required_split_states": {
                name: definition["total"] for name, definition in geometry.items()
            },
            "required_play_states": sum(
                definition["play_total"] for definition in geometry.values()),
            "required_bury_states": sum(
                definition["bury_total"] for definition in geometry.values()),
            "quota_cells_must_match_schedule_exactly": True,
            "acceptance_and_rejection_counters_required": True,
            "candidate_union_and_source_provenance_required": True,
            "complete_generation_witness_required": True,
            "one_scan_record_per_scheduled_seed": True,
            "one_diagnostic_record_per_pre_reservoir_state": True,
            "terminal_recomputes_cell_state_priority_actor": True,
            "terminal_replays_every_scan_disposition": True,
            "terminal_disposition_replay_deals":
                TERMINAL_DISPOSITION_REPLAY_DEALS,
            "terminal_disposition_replay_workers":
                TERMINAL_DISPOSITION_REPLAY_WORKERS,
            "terminal_disposition_progress_every":
                TERMINAL_DISPOSITION_PROGRESS_EVERY,
            "terminal_verification_schema": VERIFICATION_SCHEMA,
            "dataset_review_requires_terminal_verification": True,
            "nonnegative_reconciled_work_counters": True,
            "dataset_publish_is_exclusive": True,
            "dataset_freeze_authorizes_no_labels": True,
            "durable_one_shot_admission_slot": admission_slot_logical_path(),
            "admission_slot_gitignored": True,
            "admission_slot_published_before_receipt": True,
            "receipt_deletion_cannot_reissue": True,
            "admit_then_runtime_reopen_required": True,
            "unrelated_git_dirt_refused": True,
        },
        "commands": command_templates(schedule),
        "review_contract": {
            "schema": REVIEW_SCHEMA,
            "marker": REVIEW_MARKER.strip(),
            "required_verdict": "PASS",
            "pass_authorizes": (
                "one score-free Stage-C state-capture execution under the "
                "exact schedule and durable admission"
            ),
            "pass_does_not_authorize": [
                "labels", "training", "strength claim", "model selection",
                "whole-game screen", "promotion", "deployment",
            ],
            "required_claim_fields": list(REVIEW_FIELDS),
        },
        "authority": {
            "score_free": True,
            "states_captured": False,
            "worlds_sampled": False,
            "outcomes_computed": False,
            "capture_controller_review_authorized": True,
            "state_capture_authorized": False,
            "labels_authorized": False,
            "training_authorized": False,
            "strength_claim": False,
            "production_promotion": False,
            "production_deployment": False,
        },
    }
    packet["packet_sha256"] = self_hash(packet)
    return packet


def packet_problems(actual: dict, expected: dict) -> list[str]:
    problems = []
    if actual != expected:
        problems.append("capture-controller full recomputation drift")
    authority = actual.get("authority", {})
    if (authority != expected.get("authority")
            or authority.get("score_free") is not True
            or authority.get("states_captured") is not False
            or authority.get("worlds_sampled") is not False
            or authority.get("outcomes_computed") is not False
            or authority.get("state_capture_authorized") is not False
            or authority.get("labels_authorized") is not False
            or authority.get("training_authorized") is not False
            or authority.get("strength_claim") is not False
            or authority.get("production_promotion") is not False
            or authority.get("production_deployment") is not False):
        problems.append("capture-controller authority widened")
    return sorted(set(problems))


def expected_review_claim(packet: dict, external_sha256: str) -> dict:
    if (packet.get("schema") != SCHEMA
            or packet.get("producer", {}).get("promotable") is not True
            or len(external_sha256) != 64):
        raise ControllerRefused("cannot derive capture-controller review claim")
    splits = packet["result_contract"]["required_split_states"]
    sources = packet["runtime_sources"]
    claim = {
        "schema": REVIEW_SCHEMA,
        "git": packet["producer"]["git"],
        "controller_script_sha256": packet["producer"][
            "controller_script_sha256"],
        "runtime_script_sha256": sources[
            "server/scripts/teacher_stage_c_capture_runtime.py"],
        "packet_sha256": external_sha256,
        "base_stage_c_sha256": BASE_PACKET_SHA256,
        "rebind_sha256": REBIND_PACKET_SHA256,
        "h0_controller_sha256": H0_PACKET_SHA256,
        "s3c_controller_sha256": S3C_PACKET_SHA256,
        "live_parent_schema": LIVE_PARENT.SCHEMA,
        "live_parent_policy": LIVE_PARENT.CHAMPION_POLICY,
        "v11_checkpoint_sha256": packet["inputs"]["v11pair"]["sha256"],
        "schedule_sha256": packet["schedule"]["schedule_sha256"],
        "exclusion_manifest_sha256": packet["evaluation_exclusions"][
            "manifest_sha256"],
        "states": packet["result_contract"]["required_states"],
        "design_states": splits["DESIGN"],
        "calib_states": splits["CALIB"],
        "report_states": splits["REPORT"],
        "play_states": packet["result_contract"]["required_play_states"],
        "bury_states": packet["result_contract"]["required_bury_states"],
        "scan_deals": packet["schedule"]["scan_deals"],
        "capture_shards": packet["schedule"]["shard_count"],
        "population_experiment_id": POPULATION_EXPERIMENT_ID,
        "terminal_disposition_replay_deals": packet["result_contract"][
            "terminal_disposition_replay_deals"],
        "terminal_disposition_replay_workers": packet["result_contract"][
            "terminal_disposition_replay_workers"],
        "terminal_disposition_progress_every": packet["result_contract"][
            "terminal_disposition_progress_every"],
        "uncertainty_worlds": UNCERTAINTY_WORLDS,
        "max_uncertainty_candidate_worlds": packet["schedule"][
            "max_uncertainty_candidate_worlds"],
        "max_uncertainty_attempts": packet["schedule"][
            "max_uncertainty_attempts"],
        "max_terminal_replay_uncertainty_candidate_worlds": packet[
            "schedule"]["max_terminal_replay_uncertainty_candidate_worlds"],
        "max_terminal_replay_uncertainty_attempts": packet["schedule"][
            "max_terminal_replay_uncertainty_attempts"],
        "max_total_uncertainty_candidate_worlds": packet["schedule"][
            "max_total_uncertainty_candidate_worlds"],
        "max_total_uncertainty_attempts": packet["schedule"][
            "max_total_uncertainty_attempts"],
        "complete_generation_witness": True,
        "terminal_recomputes_state_identity": True,
        "terminal_reconciles_work": True,
        "terminal_replays_all_scan_dispositions": True,
        "worlds_sampled_before_review": 0,
        "states_captured_before_review": 0,
        "outcomes_computed_before_review": False,
        "independent_review": True,
        "one_capture_execution_authorized": True,
        "labels_authorized": False,
        "training_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
        "verdict": "PASS",
    }
    if tuple(claim) != REVIEW_FIELDS:
        raise ControllerRefused("capture-controller review field order/set drift")
    return claim


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


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--base-stage-c", required=True)
    parser.add_argument("--rebind", required=True)
    parser.add_argument("--h0-controller", required=True)
    parser.add_argument("--s3c-controller", required=True)
    parser.add_argument("--review-record", required=True)
    parser.add_argument("--evaluation-asset", action="append", required=True)
    parser.add_argument("--packet", required=True)
    parser.add_argument("--expected-git")
    parser.add_argument("--smoke", action="store_true")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    freeze = commands.add_parser("freeze")
    _common(freeze)
    verify = commands.add_parser("verify")
    _common(verify)
    verify.add_argument("--expected-packet-sha256")
    return root


def main(argv: list[str] | None = None) -> None:
    args = parser().parse_args(argv)
    if not args.smoke and not args.expected_git:
        raise ControllerRefused("real freeze/verify requires --expected-git")
    if (args.command == "verify" and not args.smoke
            and not args.expected_packet_sha256):
        raise ControllerRefused("real verify requires packet SHA-256")
    if args.expected_git and _git("rev-parse", "HEAD") != args.expected_git:
        raise ControllerRefused("producer Git differs from expected Git")
    expected = build_packet(
        Path(args.base_stage_c), Path(args.rebind), Path(args.h0_controller),
        Path(args.s3c_controller), Path(args.review_record),
        [Path(path) for path in args.evaluation_asset], smoke=args.smoke,
    )
    packet_path = Path(args.packet)
    if args.command == "freeze":
        publish_exclusive(packet_path, expected)
        print(json.dumps({
            "status": "FROZEN_FOR_CAPTURE_CONTROLLER_REVIEW",
            "packet": str(packet_path),
            "sha256": sha256_file(packet_path),
            "states_captured": 0,
            "worlds_sampled": 0,
        }, sort_keys=True))
        return
    if not is_regular_unlinked(packet_path):
        raise ControllerRefused("capture-controller packet is not regular")
    if (args.expected_packet_sha256
            and sha256_file(packet_path) != args.expected_packet_sha256):
        raise ControllerRefused("external capture-controller SHA-256 drift")
    actual = load_json(packet_path)
    problems = packet_problems(actual, expected)
    if problems:
        raise ControllerRefused("; ".join(problems))
    print(json.dumps({
        "status": "VERIFIED_FOR_CAPTURE_CONTROLLER_REVIEW",
        "packet": str(packet_path),
        "sha256": sha256_file(packet_path),
        "states_captured": 0,
        "worlds_sampled": 0,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
