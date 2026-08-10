#!/usr/bin/env python3
"""Execute the reviewed, one-shot Teacher Stage-C state capture.

This runtime captures replayable states and score-free candidate geometry.  It
uses belief worlds only for the explicitly bounded N=30 *selection diagnostic*
inside champion-uncertainty cells.  Those diagnostics choose the state
population and are never labels or model features.  No mode computes the
Stage-C label folds, trains a model, claims strength, promotes, or deploys.
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
import random
import stat
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Iterable, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[1]
REPO = SCRIPT.parents[2]
sys.path.insert(0, str(SERVER))
sys.path.insert(0, str(SCRIPT.parent))

import teacher_stage_c_capture_controller as CTRL  # noqa: E402
from shengji.ai.bury import structured_bury_ballot  # noqa: E402
from shengji.ai.memory import Memory  # noqa: E402
from shengji.ai.point_banking import PointBankingRolloutPolicy  # noqa: E402
from shengji.ai.registry import make_bot  # noqa: E402
from shengji.ai.smart import SmartBot  # noqa: E402
from shengji.engine.game import Game  # noqa: E402
from shengji.pilot_arms import propose as structured_lead_propose  # noqa: E402
from shengji.rl.actions import enumerate_actions  # noqa: E402
from shengji.rl.encode import encode_action, encode_obs  # noqa: E402
from shengji.rl.torch_policy import _load_npnet  # noqa: E402
from shengji.teacher_v1 import phase_for_trick  # noqa: E402


BASE_PATH = Path(
    "server/runs/logs/teacher-v3-hard-tail-stage-c-design-v1/design_packet.json"
)
REBIND_PATH = Path(
    "server/runs/logs/teacher-v3-hard-tail-stage-c-controller-rebind-v1/"
    "rebind_packet.json"
)
H0_PATH = Path(
    "server/runs/logs/human-v8-h0-counterfactual-controller-v3/"
    "controller_packet.json"
)
S3C_PATH = Path(
    "server/runs/logs/s3c-one-card-capacity-controller-v2/controller_packet.json"
)
V11_PATH = Path("server/snapshots_v11pair/ep07.npz")
V11_SHA256 = (
    "cd89d6ed7e9d5f798d69ce546107c4dfbef682c5385de39af527026e39e1c003"
)
UNCERTAINTY_MARGIN_WINDOW = 2.5


class RuntimeRefused(RuntimeError):
    """A reviewed identity, one-shot boundary, or capture invariant failed."""


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, check=True, capture_output=True, text=True,
    ).stdout.strip()


def _load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise RuntimeRefused(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeRefused(f"JSON root is not an object: {path}")
    return value


def _terminal_file(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return False
    return (stat.S_ISREG(info.st_mode) and info.st_nlink == 1
            and not path.is_symlink())


def _self_hash(payload: Mapping[str, object], field: str) -> str:
    return CTRL.sha256_bytes(CTRL.canonical_json({
        key: value for key, value in payload.items() if key != field
    }))


def _expected_slot_path() -> Path:
    return (REPO / CTRL.admission_slot_logical_path()).resolve()


def _logical_inputs() -> tuple[Path, Path, Path, Path, list[Path]]:
    return (
        REPO / BASE_PATH,
        REPO / REBIND_PATH,
        REPO / H0_PATH,
        REPO / S3C_PATH,
        [REPO / logical for logical in CTRL.EVALUATION_ASSET_PATHS],
    )


def _require_clean_tree() -> None:
    if _git("status", "--porcelain", "--untracked-files=all"):
        raise RuntimeRefused("Stage-C capture runtime refuses a dirty tree")


def _validate_parent_files(packet: Mapping[str, object]) -> None:
    base_path, rebind_path, h0_path, s3c_path, _assets = _logical_inputs()
    expected_files = (
        (base_path, CTRL.BASE_PACKET_SHA256, "base Stage-C"),
        (rebind_path, CTRL.REBIND_PACKET_SHA256, "Stage-C rebind"),
        (h0_path, CTRL.H0_PACKET_SHA256, "H0-v3"),
        (s3c_path, CTRL.S3C_PACKET_SHA256, "S3c-v2"),
    )
    for path, expected, label in expected_files:
        if not _terminal_file(path) or CTRL.sha256_file(path) != expected:
            raise RuntimeRefused(f"{label} parent external SHA-256 drift")
    base = _load_json(base_path)
    rebind = _load_json(rebind_path)
    h0 = _load_json(h0_path)
    s3c = _load_json(s3c_path)
    parents = packet.get("parents", {})
    if (base.get("schema") != CTRL.DESIGN.SCHEMA
            or base.get("packet_sha256") != CTRL.REBIND.self_hash(base)
            or parents.get("base_stage_c", {}).get("internal_sha256")
            != base.get("packet_sha256")
            or parents.get("base_stage_c", {}).get("curriculum_commitments")
            != CTRL.REBIND.curriculum_commitments(base)
            or rebind.get("schema") != CTRL.REBIND.SCHEMA
            or rebind.get("packet_sha256") != CTRL.REBIND.self_hash(rebind)
            or parents.get("controller_rebind", {}).get("internal_sha256")
            != rebind.get("packet_sha256")
            or h0.get("schema") != CTRL.REBIND.H0.SCHEMA
            or h0.get("packet_sha256") != CTRL.REBIND.self_hash(h0)
            or parents.get("h0_v3", {}).get("internal_sha256")
            != h0.get("packet_sha256")
            or s3c.get("schema") != CTRL.REBIND.S3C.SCHEMA
            or s3c.get("packet_sha256") != CTRL.REBIND.self_hash(s3c)
            or parents.get("s3c_v2", {}).get("internal_sha256")
            != s3c.get("packet_sha256")):
        raise RuntimeRefused("Stage-C capture parent identity/self-hash drift")
    bindings = rebind.get("replacement_bindings", {})
    if (rebind.get("base_stage_c", {}).get("curriculum_commitments")
            != CTRL.REBIND.curriculum_commitments(base)
            or bindings.get("h0", {}).get("review_claim")
            != CTRL.REBIND.expected_h0_review_claim(h0)
            or bindings.get("s3c", {}).get("review_claim")
            != CTRL.REBIND.expected_s3c_review_claim(s3c)):
        raise RuntimeRefused("Stage-C capture replacement review binding drift")
    v11 = packet.get("inputs", {}).get("v11pair", {})
    if (v11 != h0.get("inputs", {}).get("v11pair")
            or v11.get("sha256") != V11_SHA256):
        raise RuntimeRefused("Stage-C capture V11 parent drift")


def _controller_packet(path: Path, expected_sha256: str) -> dict:
    try:
        runtime_mode = CTRL.require_runtime_mode()
        CTRL.require_admission_slot_ignored()
    except CTRL.ControllerRefused as exc:
        raise RuntimeRefused(str(exc)) from exc
    _require_clean_tree()
    if not _terminal_file(path):
        raise RuntimeRefused("capture-controller packet is not regular/unlinked")
    if CTRL.sha256_file(path) != expected_sha256:
        raise RuntimeRefused("capture-controller external SHA-256 drift")
    packet = _load_json(path)
    authority = packet.get("authority", {})
    if (packet.get("schema") != CTRL.SCHEMA
            or packet.get("packet_id") != CTRL.PACKET_ID
            or packet.get("run_id") != CTRL.RUN_ID
            or packet.get("packet_sha256") != CTRL.self_hash(packet)
            or packet.get("producer", {}).get("git")
            != _git("rev-parse", "HEAD")
            or packet.get("runtime_mode") != runtime_mode
            or CTRL.runtime_sources() != packet.get("runtime_sources")
            or packet.get("schedule", {}).get("schedule_sha256")
            != CTRL.sha256_bytes(CTRL.canonical_json({
                key: value for key, value in packet["schedule"].items()
                if key != "schedule_sha256"
            }))
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
        raise RuntimeRefused("capture-controller identity/authority drift")
    if CTRL.sha256_file(REPO / V11_PATH) != V11_SHA256:
        raise RuntimeRefused("frozen V11pair checkpoint drift")
    _validate_parent_files(packet)
    exclusions = CTRL.evaluation_exclusion_manifest(_logical_inputs()[4])
    if exclusions != packet.get("evaluation_exclusions"):
        raise RuntimeRefused("evaluation exclusion manifest drift")
    try:
        parent = CTRL.LIVE_PARENT.require_portable_live_champion_parent()
    except CTRL.LIVE_PARENT.ProtocolRefused as exc:
        raise RuntimeRefused("live champion parent did not reopen") from exc
    if parent != packet.get("parents", {}).get("live_parent"):
        raise RuntimeRefused("live champion parent drift")
    packet = copy.deepcopy(packet)
    packet["external_sha256"] = expected_sha256
    return packet


def _review_claim(review_record: Path, packet: dict,
                  packet_sha256: str) -> dict:
    try:
        claim = CTRL.marker_claim(review_record, CTRL.REVIEW_MARKER)
    except CTRL.ControllerRefused as exc:
        raise RuntimeRefused(str(exc)) from exc
    expected = CTRL.expected_review_claim(packet, packet_sha256)
    if claim != expected:
        raise RuntimeRefused("capture-controller PASS marker drift")
    return claim


def _receipt(path: Path, expected_sha256: str, packet: dict,
             packet_sha256: str) -> dict:
    expected_path = (REPO / "server/runs/logs" / CTRL.RUN_ID /
                     "capture-receipt.json").resolve()
    if path.resolve() != expected_path or not _terminal_file(path):
        raise RuntimeRefused("capture receipt path/type drift")
    if CTRL.sha256_file(path) != expected_sha256:
        raise RuntimeRefused("capture receipt external SHA-256 drift")
    receipt = _load_json(path)
    fixed = {
        "schema": CTRL.RECEIPT_SCHEMA,
        "run_id": CTRL.RUN_ID,
        "git": packet["producer"]["git"],
        "controller_packet_sha256": packet_sha256,
        "controller_packet_internal_sha256": packet["packet_sha256"],
        "schedule_sha256": packet["schedule"]["schedule_sha256"],
        "admission_slot": str(_expected_slot_path()),
        "one_shot": True,
        "state_capture_authorized": True,
        "labels_authorized": False,
        "training_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    for key, value in fixed.items():
        if receipt.get(key) != value:
            raise RuntimeRefused(f"capture receipt field drift: {key}")
    if receipt.get("review_claim") != CTRL.expected_review_claim(
            packet, packet_sha256):
        raise RuntimeRefused("capture receipt review claim drift")
    if receipt.get("receipt_sha256") != _self_hash(receipt, "receipt_sha256"):
        raise RuntimeRefused("capture receipt self-hash drift")
    slot_path = _expected_slot_path()
    if not _terminal_file(slot_path):
        raise RuntimeRefused("durable capture admission is missing")
    slot = _load_json(slot_path)
    expected_slot = {
        "schema": CTRL.ADMISSION_SCHEMA,
        "run_id": CTRL.RUN_ID,
        "git": packet["producer"]["git"],
        "controller_packet_sha256": packet_sha256,
        "schedule_sha256": packet["schedule"]["schedule_sha256"],
        "receipt_path": str(expected_path),
        "receipt_file_sha256": CTRL.sha256_file(path),
        "consumed_even_if_receipt_publication_fails": True,
    }
    expected_slot["slot_sha256"] = _self_hash(expected_slot, "slot_sha256")
    if slot != expected_slot:
        raise RuntimeRefused("durable capture admission drift")
    return receipt


def admit(*, packet_path: Path, expected_packet_sha256: str,
          review_record: Path, namespace: Path, out: Path) -> dict:
    packet = _controller_packet(packet_path, expected_packet_sha256)
    claim = _review_claim(review_record, packet, expected_packet_sha256)
    expected_namespace = (REPO / "server/runs/logs" / CTRL.RUN_ID).resolve()
    if namespace.resolve() != expected_namespace:
        raise RuntimeRefused("capture namespace differs from reviewed path")
    if out.parent.resolve() != expected_namespace or out.name != "capture-receipt.json":
        raise RuntimeRefused("capture receipt differs from reviewed path")
    slot_path = _expected_slot_path()
    if os.path.lexists(slot_path) or os.path.lexists(Path(str(slot_path) + ".partial")):
        raise RuntimeRefused("one-shot capture admission is already consumed")
    namespace.mkdir(parents=True, exist_ok=True)
    allowed = {packet_path.resolve(), review_record.resolve()}
    for child in namespace.iterdir():
        if child.resolve() not in allowed:
            raise RuntimeRefused(
                f"capture namespace already contains target {child.name}")
    receipt = {
        "schema": CTRL.RECEIPT_SCHEMA,
        "run_id": CTRL.RUN_ID,
        "git": packet["producer"]["git"],
        "controller_packet_sha256": expected_packet_sha256,
        "controller_packet_internal_sha256": packet["packet_sha256"],
        "schedule_sha256": packet["schedule"]["schedule_sha256"],
        "admission_slot": str(slot_path),
        "review_record_sha256": CTRL.sha256_file(review_record),
        "review_claim": claim,
        "one_shot": True,
        "state_capture_authorized": True,
        "labels_authorized": False,
        "training_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    receipt["receipt_sha256"] = _self_hash(receipt, "receipt_sha256")
    slot = {
        "schema": CTRL.ADMISSION_SCHEMA,
        "run_id": CTRL.RUN_ID,
        "git": packet["producer"]["git"],
        "controller_packet_sha256": expected_packet_sha256,
        "schedule_sha256": packet["schedule"]["schedule_sha256"],
        "receipt_path": str(out.resolve()),
        "receipt_file_sha256": CTRL.sha256_bytes(CTRL.canonical_json(receipt)),
        "consumed_even_if_receipt_publication_fails": True,
    }
    slot["slot_sha256"] = _self_hash(slot, "slot_sha256")
    CTRL.publish_exclusive(slot_path, slot)
    CTRL.publish_exclusive(out, receipt)
    return receipt


def _seed(*parts: object) -> int:
    value = "|".join(str(part) for part in parts).encode()
    return int.from_bytes(hashlib.sha256(value).digest()[:16], "big")


def _priority(split: str, cell_id: str, deal_seed: int,
              state_id: str) -> str:
    return hashlib.sha256(
        f"{CTRL.EXPERIMENT_ID}|{split}|{cell_id}|{deal_seed}|{state_id}".encode()
    ).hexdigest()


SCAN_RECORD_FIELDS = (
    "ordinal", "seed", "cell_id", "status", "surface_type", "seat", "ply",
    "state_id", "selection_priority",
)
DIAGNOSTIC_RECORD_FIELDS = (
    "cell_id", "state_id", "selection_priority", "status", "eligible",
    "candidate_count", "candidate_actions", "attempts", "worlds",
    "candidate_worlds", "selection_diagnostic",
)


def _nonnegative_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RuntimeRefused(f"{label} must be a nonnegative integer")
    return value


def _records_sha256(records: Sequence[Mapping[str, object]]) -> str:
    return CTRL.sha256_bytes(CTRL.canonical_json(list(records)))


def _canonical_state_id(*, split: str, seed: int, surface_type: str,
                        seat: int, ply: int) -> str:
    if not 0 <= seat < 4:
        raise RuntimeRefused("Stage-C state seat is outside 0..3")
    if surface_type == "bury":
        if ply != 0:
            raise RuntimeRefused("Stage-C bury state has nonzero ply")
        return f"{split}:{seed}:bury:{seat}"
    if surface_type != "play" or ply < 0:
        raise RuntimeRefused("Stage-C state surface/ply drift")
    return f"{split}:{seed}:{ply}:{seat}"


def _scan_record(ordinal: int, seed: int, cell_id: str, status: str,
                 state: Mapping[str, object] | None) -> dict:
    if state is None:
        identity = {
            "surface_type": None, "seat": None, "ply": None,
            "state_id": None, "selection_priority": None,
        }
    else:
        identity = {
            "surface_type": state["surface_type"],
            "seat": state["seat"],
            "ply": state["ply"],
            "state_id": state["state_id"],
            "selection_priority": state["selection_priority"],
        }
    return {
        "ordinal": ordinal, "seed": seed, "cell_id": cell_id,
        "status": status, **identity,
    }


def _diagnostic_record(*, cell_id: str, state: Mapping[str, object],
                       status: str, eligible: bool,
                       diagnostic: Mapping[str, object] | None) -> dict:
    candidate_actions = [
        list(_action_key(candidate["cards"]))
        for candidate in state.get("candidates", [])
    ]
    candidate_count = len(candidate_actions)
    attempts = worlds = candidate_worlds = 0
    stored_diagnostic = None
    if diagnostic is not None:
        stored_diagnostic = copy.deepcopy(dict(diagnostic))
        attempts = int(diagnostic["attempts"])
        worlds = int(diagnostic["worlds"])
        candidate_worlds = int(diagnostic["candidate_worlds"])
        candidate_count = len(state.get("candidates", []))
    return {
        "cell_id": cell_id,
        "state_id": state["state_id"],
        "selection_priority": state["selection_priority"],
        "status": status,
        "eligible": eligible,
        "candidate_count": candidate_count,
        "candidate_actions": candidate_actions,
        "attempts": attempts,
        "worlds": worlds,
        "candidate_worlds": candidate_worlds,
        "selection_diagnostic": stored_diagnostic,
    }


def _validate_retained_state_identity(
    packet: dict,
    schedule: Mapping[str, object],
    state: Mapping[str, object],
    actor_identity: Mapping[str, object],
) -> None:
    split = str(schedule["split"])
    if not isinstance(state, dict):
        raise RuntimeRefused("Stage-C retained state is not an object")
    seed = _nonnegative_int(state.get("seed"), "Stage-C retained seed")
    if seed not in _shard_seeds(schedule):
        raise RuntimeRefused("Stage-C retained seed is outside its shard")
    cell = _cell_for_seed(packet, split, seed)
    if (state.get("schema") != "teacher-stage-c-replay-state-v1"
            or state.get("experiment_id") != CTRL.EXPERIMENT_ID
            or state.get("capture_packet_id") != CTRL.PACKET_ID
            or state.get("split") != split
            or state.get("cell_id") != cell["cell_id"]
            or state.get("surface_type") != cell["surface_type"]
            or state.get("stratum") != cell["stratum"]
            or state.get("role") != cell["role"]
            or state.get("surface") != cell["surface"]):
        raise RuntimeRefused("Stage-C retained state cell assignment drift")
    if (cell["phase"] != "any" and state.get("phase") != cell["phase"]):
        raise RuntimeRefused("Stage-C retained state phase assignment drift")
    if (cell["phase"] == "any"
            and state.get("phase") not in {"early", "mid", "late"}):
        raise RuntimeRefused("Stage-C retained any-phase state drift")
    seat = _nonnegative_int(state.get("seat"), "Stage-C retained seat")
    ply = _nonnegative_int(state.get("ply"), "Stage-C retained ply")
    plays = state.get("plays")
    if not isinstance(plays, list) or len(plays) != ply:
        raise RuntimeRefused("Stage-C retained play/ply identity drift")
    state_id = _canonical_state_id(
        split=split, seed=seed, surface_type=str(state["surface_type"]),
        seat=seat, ply=ply)
    if state.get("state_id") != state_id:
        raise RuntimeRefused("Stage-C retained canonical state ID drift")
    if state.get("selection_priority") != _priority(
            split, str(cell["cell_id"]), seed, state_id):
        raise RuntimeRefused("Stage-C retained selection priority drift")
    expected_streams = [{
        "seat": actor_seat,
        "seed": _seed(CTRL.EXPERIMENT_ID, split, seed, "actor", actor_seat,
                      CTRL.ACTOR_POLICY),
        "policy": CTRL.ACTOR_POLICY,
    } for actor_seat in range(4)]
    if (state.get("actor_policy") != CTRL.ACTOR_POLICY
            or state.get("actor_identity") != actor_identity
            or state.get("actor_streams") != expected_streams):
        raise RuntimeRefused("Stage-C retained actor identity/stream drift")


def _reconcile_generation_witness(
    packet: dict,
    schedule: Mapping[str, object],
    witness: Mapping[str, object],
    retained_states: Sequence[dict],
) -> tuple[dict, dict, dict]:
    split = str(schedule["split"])
    cells = {cell["cell_id"]: cell
             for cell in packet["schedule"]["quota_cells"][split]}
    if (not isinstance(witness, dict)
            or witness.get("schema") != CTRL.GENERATION_WITNESS_SCHEMA
            or witness.get("complete") is not True
            or witness.get("witness_sha256")
            != _self_hash(witness, "witness_sha256")):
        raise RuntimeRefused("Stage-C complete generation witness drift")
    scan_records = witness.get("scan_records")
    diagnostic_records = witness.get("diagnostic_records")
    if not isinstance(scan_records, list) or not isinstance(
            diagnostic_records, list):
        raise RuntimeRefused("Stage-C generation witness record type drift")
    if (witness.get("scan_records_sha256") != _records_sha256(scan_records)
            or witness.get("diagnostic_records_sha256")
            != _records_sha256(diagnostic_records)):
        raise RuntimeRefused("Stage-C generation witness record digest drift")
    seeds = _shard_seeds(schedule)
    if len(scan_records) != len(seeds):
        raise RuntimeRefused("Stage-C generation witness seed coverage drift")

    scan_by_state: dict[str, dict] = {}
    scan_by_cell: dict[str, list[dict]] = {cell_id: [] for cell_id in cells}
    cell_counts: dict[str, Counter[str]] = {
        cell_id: Counter() for cell_id in cells}
    scan_rejected = 0
    for ordinal, (seed, record) in enumerate(
            zip(seeds, scan_records, strict=True), 1):
        if (not isinstance(record, dict)
                or set(record) != set(SCAN_RECORD_FIELDS)):
            raise RuntimeRefused("Stage-C scan witness field drift")
        expected_cell = _cell_for_seed(packet, split, seed)
        status = record.get("status")
        if (record.get("ordinal") != ordinal or record.get("seed") != seed
                or record.get("cell_id") != expected_cell["cell_id"]
                or not isinstance(status, str) or not status):
            raise RuntimeRefused("Stage-C scan witness schedule/cell drift")
        cell_id = str(expected_cell["cell_id"])
        cell_counts[cell_id]["assigned"] += 1
        state_id = record.get("state_id")
        if state_id is None:
            if any(record.get(name) is not None for name in (
                    "surface_type", "seat", "ply", "selection_priority")):
                raise RuntimeRefused("Stage-C rejected scan identity drift")
            if status == "eligible":
                raise RuntimeRefused("Stage-C rejected scan has eligible status")
            cell_counts[cell_id][f"rejected:{status}"] += 1
            scan_rejected += 1
            continue
        if status != "eligible" or not isinstance(state_id, str):
            raise RuntimeRefused("Stage-C eligible scan status/type drift")
        surface_type = record.get("surface_type")
        if surface_type != expected_cell["surface_type"]:
            raise RuntimeRefused("Stage-C scan surface assignment drift")
        seat = _nonnegative_int(record.get("seat"), "Stage-C scan seat")
        ply = _nonnegative_int(record.get("ply"), "Stage-C scan ply")
        canonical_id = _canonical_state_id(
            split=split, seed=seed, surface_type=str(surface_type),
            seat=seat, ply=ply)
        if state_id != canonical_id:
            raise RuntimeRefused("Stage-C scan canonical state ID drift")
        priority = _priority(split, cell_id, seed, state_id)
        if record.get("selection_priority") != priority:
            raise RuntimeRefused("Stage-C scan selection priority drift")
        if state_id in scan_by_state:
            raise RuntimeRefused("Stage-C scan state identity collision")
        scan_by_state[state_id] = record
        scan_by_cell[cell_id].append(record)
        cell_counts[cell_id]["structurally_eligible"] += 1

    expected_pre: list[dict] = []
    for cell_id in sorted(cells):
        pool = sorted(scan_by_cell[cell_id], key=lambda record: (
            record["selection_priority"], record["state_id"]))
        pool = pool[:int(cells[cell_id]["pre_candidate_limit"])]
        expected_pre.extend(pool)
        cell_counts[cell_id]["retained_pre_diagnostic"] = len(pool)
    expected_pre_keys = [(record["cell_id"], record["state_id"])
                         for record in expected_pre]
    actual_pre_keys = [(record.get("cell_id"), record.get("state_id"))
                       for record in diagnostic_records
                       if isinstance(record, dict)]
    if actual_pre_keys != expected_pre_keys:
        raise RuntimeRefused("Stage-C diagnostic witness population drift")

    diagnostic_by_state: dict[str, dict] = {}
    uncertainty_attempts = uncertainty_worlds = candidate_worlds = 0
    eligible_by_cell: dict[str, list[dict]] = {cell_id: [] for cell_id in cells}
    diagnostic_rejected = 0
    for expected_scan, record in zip(
            expected_pre, diagnostic_records, strict=True):
        if (not isinstance(record, dict)
                or set(record) != set(DIAGNOSTIC_RECORD_FIELDS)):
            raise RuntimeRefused("Stage-C diagnostic witness field drift")
        cell_id = str(expected_scan["cell_id"])
        status = record.get("status")
        if (record.get("cell_id") != cell_id
                or record.get("state_id") != expected_scan["state_id"]
                or record.get("selection_priority")
                != expected_scan["selection_priority"]
                or not isinstance(status, str) or not status
                or record.get("eligible") is not (status == "eligible")):
            raise RuntimeRefused("Stage-C diagnostic witness identity drift")
        candidate_count = _nonnegative_int(
            record.get("candidate_count"), "Stage-C candidate count")
        candidate_actions = record.get("candidate_actions")
        if (not isinstance(candidate_actions, list)
                or len(candidate_actions) != candidate_count
                or any(not isinstance(action, list) or not action
                       or list(_action_key(action)) != action
                       for action in candidate_actions)):
            raise RuntimeRefused("Stage-C diagnostic candidate actions drift")
        candidate_cap = 20 if expected_scan["surface_type"] == "play" else 33
        if candidate_count > candidate_cap or (
                record["eligible"] and candidate_count == 0):
            raise RuntimeRefused("Stage-C diagnostic candidate-count drift")
        attempts = _nonnegative_int(
            record.get("attempts"), "Stage-C uncertainty attempts")
        worlds = _nonnegative_int(
            record.get("worlds"), "Stage-C uncertainty worlds")
        work = _nonnegative_int(
            record.get("candidate_worlds"),
            "Stage-C uncertainty candidate-worlds")
        diagnostic = record.get("selection_diagnostic")
        cell = cells[cell_id]
        if cell["stratum"] == "champion_uncertainty":
            if diagnostic is None:
                if (any((attempts, worlds, work))
                        or status != "uncertainty_single_candidate"
                        or candidate_count != 0):
                    raise RuntimeRefused(
                        "Stage-C absent uncertainty diagnostic semantics drift")
            else:
                if (not isinstance(diagnostic, dict)
                        or diagnostic.get("schema")
                        != "teacher-stage-c-uncertainty-selection-v1"
                        or diagnostic.get("selection_only") is not True
                        or diagnostic.get("may_train_or_label") is not False
                        or diagnostic.get("attempts") != attempts
                        or diagnostic.get("worlds") != worlds
                        or diagnostic.get("candidate_worlds") != work
                        or diagnostic.get("eligible")
                        is not bool(record["eligible"])
                        or work != worlds * candidate_count
                        or not 1 <= candidate_count <= 20
                        or attempts > (CTRL.UNCERTAINTY_WORLDS
                                       * CTRL.UNCERTAINTY_ATTEMPT_FACTOR)
                        or worlds > CTRL.UNCERTAINTY_WORLDS):
                    raise RuntimeRefused(
                        "Stage-C uncertainty diagnostic/work reconciliation "
                        "drift")
                counters = diagnostic.get("sampler_counters")
                required_counters = {
                    "sample_attempts", "accepted_worlds", "failed_worlds",
                    "rejected_worlds", "impossible_worlds",
                }
                if (not isinstance(counters, dict)
                        or set(counters) != required_counters):
                    raise RuntimeRefused(
                        "Stage-C uncertainty sampler-counter schema drift")
                checked_counters = {
                    name: _nonnegative_int(
                        counters.get(name),
                        f"Stage-C uncertainty {name.replace('_', ' ')}")
                    for name in required_counters
                }
                if (checked_counters["sample_attempts"] != attempts
                        or checked_counters["accepted_worlds"] != worlds
                        or checked_counters["sample_attempts"] != (
                            checked_counters["accepted_worlds"]
                            + checked_counters["failed_worlds"])
                        or checked_counters["rejected_worlds"]
                        > checked_counters["failed_worlds"]
                        or checked_counters["impossible_worlds"]
                        > checked_counters["accepted_worlds"]
                        or checked_counters["impossible_worlds"] != 0):
                    raise RuntimeRefused(
                        "Stage-C uncertainty sampler counters do not "
                        "reconcile")
                margin = diagnostic.get("production_margin")
                chooser = make_bot("mc-strong", seed=0)
                if (not isinstance(margin, (int, float))
                        or isinstance(margin, bool)
                        or not math.isfinite(margin)
                        or float(margin) != float(chooser.MARGIN)
                        or diagnostic.get("margin_window")
                        != UNCERTAINTY_MARGIN_WINDOW):
                    raise RuntimeRefused(
                        "Stage-C uncertainty margin semantics drift")
                complete = diagnostic.get("evaluation_complete")
                clean_sampler = not any(checked_counters[name] for name in (
                    "failed_worlds", "rejected_worlds",
                    "impossible_worlds"))
                status_shape = {
                    "eligible": (
                        complete is True and record["eligible"] is True
                        and worlds == CTRL.UNCERTAINTY_WORLDS
                        and clean_sampler),
                    "outside_uncertainty_window": (
                        complete is True and record["eligible"] is False
                        and worlds == CTRL.UNCERTAINTY_WORLDS
                        and clean_sampler),
                    "uncertainty_underfilled": (
                        complete is False and record["eligible"] is False
                        and worlds < CTRL.UNCERTAINTY_WORLDS
                        and attempts == (CTRL.UNCERTAINTY_WORLDS
                                         * CTRL.UNCERTAINTY_ATTEMPT_FACTOR)),
                    "uncertainty_sampler_refusal": (
                        complete is False and record["eligible"] is False
                        and worlds == CTRL.UNCERTAINTY_WORLDS
                        and not clean_sampler),
                }
                if status not in status_shape or not status_shape[status]:
                    raise RuntimeRefused(
                        "Stage-C uncertainty status/work semantics drift")
                if complete is True:
                    means = diagnostic.get("means")
                    best = diagnostic.get("raw_best_index")
                    numeric = (
                        diagnostic.get("paired_gap_vs_candidate0"),
                        diagnostic.get("paired_se_vs_candidate0"),
                    )
                    if (not isinstance(means, list)
                            or len(means) != candidate_count
                            or not all(isinstance(value, (int, float))
                                       and not isinstance(value, bool)
                                       and math.isfinite(value)
                                       for value in means)
                            or isinstance(best, bool)
                            or not isinstance(best, int)
                            or not 0 <= best < candidate_count
                            or not all(isinstance(value, (int, float))
                                       and not isinstance(value, bool)
                                       and math.isfinite(value)
                                       for value in numeric)):
                        raise RuntimeRefused(
                            "Stage-C complete uncertainty statistics drift")
                    gap, se = numeric
                    expected_best = chooser._pick_index(
                        candidate_actions, means, range(candidate_count))
                    expected_gap = means[best] - means[0]
                    expected_eligible = (
                        best != 0
                        and abs(expected_gap - float(margin))
                        <= UNCERTAINTY_MARGIN_WINDOW)
                    if (best != expected_best
                            or not math.isclose(
                            float(gap), expected_gap,
                            rel_tol=1e-12, abs_tol=1e-12)
                            or float(se) < 0
                            or record["eligible"] is not expected_eligible):
                        raise RuntimeRefused(
                            "Stage-C uncertainty selection semantics drift")
                elif any(diagnostic.get(name) is not None for name in (
                        "means", "raw_best_index",
                        "paired_gap_vs_candidate0",
                        "paired_se_vs_candidate0")):
                    raise RuntimeRefused(
                        "Stage-C incomplete uncertainty statistics drift")
            if record["eligible"] and (
                    diagnostic is None or worlds != CTRL.UNCERTAINTY_WORLDS):
                raise RuntimeRefused(
                    "Stage-C eligible uncertainty diagnostic underfilled")
            uncertainty_attempts += attempts
            uncertainty_worlds += worlds
            candidate_worlds += work
        elif (diagnostic is not None or any((attempts, worlds, work))
              or status != "eligible" or record["eligible"] is not True):
            raise RuntimeRefused(
                "Stage-C non-uncertainty diagnostic semantics drift")
        if record["eligible"]:
            cell_counts[cell_id]["candidate_eligible"] += 1
            eligible_by_cell[cell_id].append(record)
        else:
            cell_counts[cell_id][f"rejected:{status}"] += 1
            diagnostic_rejected += 1
        diagnostic_by_state[str(record["state_id"])] = record

    expected_retained_ids = []
    for cell_id in sorted(cells):
        pool = sorted(eligible_by_cell[cell_id], key=lambda record: (
            record["selection_priority"], record["state_id"]))
        pool = pool[:int(cells[cell_id]["quota"])]
        expected_retained_ids.extend(record["state_id"] for record in pool)
        cell_counts[cell_id]["retained_post_diagnostic"] = len(pool)
    actual_retained_ids = [state.get("state_id") for state in retained_states]
    if actual_retained_ids != expected_retained_ids:
        raise RuntimeRefused("Stage-C retained reservoir selection drift")
    for state in retained_states:
        state_id = str(state["state_id"])
        scan = scan_by_state.get(state_id)
        diagnostic = diagnostic_by_state.get(state_id)
        if scan is None or diagnostic is None or diagnostic["eligible"] is not True:
            raise RuntimeRefused("Stage-C retained witness membership drift")
        if (state.get("surface_type") != scan["surface_type"]
                or state.get("seat") != scan["seat"]
                or state.get("ply") != scan["ply"]
                or state.get("selection_priority")
                != scan["selection_priority"]):
            raise RuntimeRefused("Stage-C retained/scan identity drift")
        candidates = state.get("candidates")
        if (not isinstance(candidates, list)
                or len(candidates) != diagnostic["candidate_count"]):
            raise RuntimeRefused("Stage-C retained candidate-count drift")
        if cells[str(state["cell_id"])]["stratum"] == "champion_uncertainty":
            if state.get("selection_diagnostic") != diagnostic[
                    "selection_diagnostic"]:
                raise RuntimeRefused(
                    "Stage-C retained uncertainty witness drift")

    counts = {
        "scanned": len(scan_records),
        "scan_eligible": len(scan_by_state),
        "scan_rejected": scan_rejected,
        "diagnostic_checked": len(diagnostic_records),
        "candidate_eligible": sum(len(rows) for rows in eligible_by_cell.values()),
        "diagnostic_rejected": diagnostic_rejected,
        "retained_post_diagnostic": len(expected_retained_ids),
    }
    reconciled_cells = {
        cell_id: dict(sorted(values.items()))
        for cell_id, values in sorted(cell_counts.items())
    }
    work = {
        "attempts": uncertainty_attempts,
        "worlds": uncertainty_worlds,
        "candidate_worlds": candidate_worlds,
    }
    return counts, reconciled_cells, work


def _action_key(action: Sequence[str]) -> tuple[str, ...]:
    return tuple(sorted(str(card) for card in action))


def _dedupe(actions: Iterable[Sequence[str]]) -> list[list[str]]:
    seen: set[tuple[str, ...]] = set()
    result = []
    for action in actions:
        key = _action_key(action)
        if key not in seen:
            seen.add(key)
            result.append(list(key))
    return result


def _declaration_record(rnd) -> dict | None:
    if rnd.declaration is None:
        return None
    return {
        "seat": rnd.declaration["seat"],
        "cards": list(rnd.declaration["cards"]),
        "strength": rnd.declaration["strength"],
    }


def _cell_for_seed(packet: dict, split: str, seed: int) -> dict:
    cells = packet["schedule"]["quota_cells"][split]
    total = sum(int(cell["quota"]) for cell in cells)
    ticket = _seed(CTRL.EXPERIMENT_ID, split, "quota-cell", seed) % total
    for cell in cells:
        quota = int(cell["quota"])
        if ticket < quota:
            return cell
        ticket -= quota
    raise AssertionError("quota-cell assignment did not terminate")


def _target_trick(split: str, cell: Mapping[str, object], seed: int) -> int:
    if cell["stratum"] == "exact_late_eligible":
        # Throws consume multiple cards per seat, so "one card left" is a
        # state property, not synonymous with trick 24.
        return -1
    phase = cell["phase"]
    ranges = {"early": (0, 5), "mid": (5, 12), "late": (12, 25)}
    if phase == "any":
        return -1
    start, stop = ranges[str(phase)]
    return start + _seed(CTRL.EXPERIMENT_ID, split, "target-trick", seed) % (
        stop - start)


def _actor_identity() -> dict:
    import shengji.ai.heuristic as heuristic
    import shengji.ai.registry as registry
    import shengji.ai.smart as smart
    paths = {
        "heuristic": heuristic.__file__,
        "registry": registry.__file__,
        "smart": smart.__file__,
    }
    payload = {
        "policy": CTRL.ACTOR_POLICY,
        "sources": {name: CTRL.sha256_file(path)
                    for name, path in sorted(paths.items())},
    }
    payload["identity_sha256"] = CTRL.sha256_bytes(CTRL.canonical_json(payload))
    return payload


def _build_play_union(rnd, seat: int, state_id: str, split: str, net) -> tuple[list[dict], dict]:
    production = make_bot("mc-s0-report-lcb", seed=0)
    live = _dedupe(production._candidates(rnd, seat))
    if not live or len(live) > 20:
        raise RuntimeRefused("live Stage-C play ballot cap/emptiness drift")
    # The observation/action encoders treat a hand as a multiset.  Keep the
    # proposal source on that same semantic boundary: ``enumerate_actions``
    # preserves incidental hand-list order, which otherwise changes both the
    # V11 tie break and the seeded random proposal for an identical encoded
    # state.
    exhaustive = sorted(_dedupe(enumerate_actions(
        rnd, seat, exhaustive_follows=True, include_throws=True)),
        key=_action_key)
    live_keys = {_action_key(action) for action in live}
    novel = [action for action in exhaustive if _action_key(action) not in live_keys]
    v11 = None
    if novel:
        values = [float(value) for value in net.value_candidates(
            encode_obs(rnd, seat), [encode_action(action, rnd) for action in novel])]
        if len(values) != len(novel) or not all(math.isfinite(value) for value in values):
            raise RuntimeRefused("V11 proposal returned missing/non-finite values")
        v11 = novel[max(range(len(novel)), key=lambda index: values[index])]
    structured = None
    if not rnd.trick.plays:
        proposed = structured_lead_propose(
            "quota", production, rnd, seat, budget=20,
            seed=_seed(CTRL.EXPERIMENT_ID, split, state_id, "structured-lead"),
            state_key=state_id,
        )
        structured = next((action for action in proposed
                           if _action_key(action) not in live_keys), None)
    else:
        treatment = PointBankingRolloutPolicy(apply_treatment=True)
        # Heuristic follow helpers walk the hand.  Production canonicalises its
        # live ballot in exactly this way; do the same for this extra structured
        # proposal without changing the shared/S4 policy source.
        saved_hand = rnd.hands[seat]
        rnd.hands[seat] = sorted(saved_hand)
        try:
            candidate = treatment._follow(rnd, seat)
        finally:
            rnd.hands[seat] = saved_hand
        if _action_key(candidate) not in live_keys:
            structured = list(candidate)
    random_novel = None
    if novel:
        random_novel = random.Random(_seed(
            CTRL.EXPERIMENT_ID, split, state_id, "matched-random")).choice(novel)
    by_key: dict[tuple[str, ...], dict] = {}
    order: list[tuple[str, ...]] = []

    def add(action: Sequence[str] | None, source: str) -> None:
        if action is None:
            return
        key = _action_key(action)
        if key not in by_key:
            if len(order) >= 20:
                return
            by_key[key] = {"cards": list(key), "sources": []}
            order.append(key)
        if source not in by_key[key]["sources"]:
            by_key[key]["sources"].append(source)

    for action in live:
        add(action, "live_production_ballot")
    add(v11, "v11pair_top_proposal")
    add(structured, "named_structured_lead_or_follow_mechanism")
    add(random_novel, "same_budget_random_diversifier")
    union = [by_key[key] for key in order]
    for candidate in union:
        candidate["sources"].sort()
    if not union or _action_key(union[0]["cards"]) != _action_key(live[0]):
        raise RuntimeRefused("Stage-C candidate zero differs from live ballot")
    source_names = {source for candidate in union
                    for source in candidate["sources"]}
    diagnostics = {
        "live_candidates": len(live),
        "exhaustive_actions": len(exhaustive),
        "novel_actions": len(novel),
        "v11_novel": "v11pair_top_proposal" in source_names,
        "structured_novel": (
            "named_structured_lead_or_follow_mechanism" in source_names),
        "random_novel": "same_budget_random_diversifier" in source_names,
        "candidate_count": len(union),
    }
    return union, diagnostics


def _build_bury_union(rnd, seat: int, state_id: str) -> tuple[list[dict], dict]:
    incumbent = SmartBot().decide_bury(rnd, seat)
    ballot = structured_bury_ballot(
        rnd.hands[seat], rnd.ordering, incumbent, max_candidates=32)
    if (not ballot.candidates or len(ballot.candidates) > 32
            or _action_key(ballot.candidates[0].cards) != _action_key(incumbent)):
        raise RuntimeRefused("Stage-C structured bury ballot drift")
    by_key: dict[tuple[str, ...], dict] = {}
    order: list[tuple[str, ...]] = []

    def add(cards: Sequence[str], sources: Iterable[str]) -> None:
        key = _action_key(cards)
        if key not in by_key:
            if len(order) >= 33:
                return
            by_key[key] = {"cards": list(key), "sources": []}
            order.append(key)
        for source in sources:
            if source not in by_key[key]["sources"]:
                by_key[key]["sources"].append(source)

    for candidate in ballot.candidates:
        add(candidate.cards, ("s3a_structured_point_void_bury", *candidate.sources))
    rng = random.Random(_seed(CTRL.EXPERIMENT_ID, state_id, "random-bury"))
    # Sampling indices from the engine's deal-order list made this deterministic
    # control differ for two equivalent encodings of the same banker hand.
    hand = sorted(rnd.hands[seat])
    for _ in range(64):
        indices = sorted(rng.sample(range(len(hand)), 8))
        candidate = [hand[index] for index in indices]
        if _action_key(candidate) not in by_key:
            add(candidate, ("same_budget_random_structured_bury",))
            break
    union = [by_key[key] for key in order]
    for candidate in union:
        candidate["sources"].sort()
    return union, {
        "candidate_count": len(union),
        "structured_candidates": len(ballot.candidates),
        "structured_generated_unique": ballot.generated_unique,
        "structured_truncated": ballot.truncated,
        "random_novel": any("same_budget_random_structured_bury" in item["sources"]
                            for item in union),
    }


def _point_banking_opportunity(rnd, seat: int) -> dict:
    if not rnd.trick.plays:
        return {"opportunity": False, "telemetry": None}
    probe = PointBankingRolloutPolicy(apply_treatment=False)
    before = probe.point_banking_snapshot()
    probe._follow(rnd, seat)
    telemetry = probe.point_banking_delta(before)
    delta = telemetry["delta"]
    return {"opportunity": int(delta["opportunities"]) == 1,
            "telemetry": telemetry}


def _state_setup(rnd, declarations: list[dict], buried: Sequence[str] | None) -> dict:
    return {
        "deck": list(rnd.deck),
        "initial_banker": None,
        "trump_rank": rnd.trump_rank,
        "banker": rnd.banker,
        "trump_suit": rnd.trump_suit,
        "trump_is_nt": rnd.trump_is_nt,
        "declarations": copy.deepcopy(declarations),
        "final_declaration": _declaration_record(rnd),
        "buried": None if buried is None else list(buried),
    }


def _base_state(*, seed: int, split: str, cell: Mapping[str, object],
                seat: int, surface_type: str, setup: dict,
                actor_streams: list[dict], actor_identity: dict,
                plays: list[dict]) -> dict:
    state_id = (f"{split}:{seed}:bury:{seat}" if surface_type == "bury" else
                f"{split}:{seed}:{len(plays)}:{seat}")
    state = {
        "schema": "teacher-stage-c-replay-state-v1",
        "experiment_id": CTRL.EXPERIMENT_ID,
        "capture_packet_id": CTRL.PACKET_ID,
        "split": split,
        "surface_type": surface_type,
        "stratum": cell["stratum"],
        "cell_id": cell["cell_id"],
        "seed": seed,
        "seat": seat,
        "state_id": state_id,
        "actor_policy": CTRL.ACTOR_POLICY,
        "actor_identity": actor_identity,
        "actor_streams": actor_streams,
        "setup": setup,
        "plays": copy.deepcopy(plays),
    }
    if surface_type == "bury":
        state.update({
            "ply": 0, "trick": None, "phase": "pre-play",
            "surface": "bury", "role": "defender",
        })
    else:
        trick = len(plays) // 4
        # Throws and failed throws do not change that every completed trick has
        # exactly four seat plays; use the live history in the caller to
        # overwrite this defensive approximation.
        state.update({
            "ply": len(plays), "trick": trick,
            "phase": str(cell["phase"]),
            "surface": str(cell["surface"]),
            "role": str(cell["role"]),
        })
    state["selection_priority"] = _priority(
        split, str(cell["cell_id"]), seed, state_id)
    return state


def replay_state(state: Mapping[str, object]):
    if state.get("schema") != "teacher-stage-c-replay-state-v1":
        raise RuntimeRefused("unsupported Stage-C replay-state schema")
    seed = int(state["seed"])
    setup = state["setup"]
    rnd = Game(random.Random(seed)).start_round()
    if list(rnd.deck) != list(setup["deck"]):
        raise RuntimeRefused("Stage-C replay deck drift")
    declarations = list(setup["declarations"])
    event_i = 0
    while rnd.phase == "deal":
        rnd.deal_next()
        while (event_i < len(declarations)
               and declarations[event_i]["stage"] == "deal"
               and declarations[event_i]["deal_pos"] == rnd._deal_pos):
            event = declarations[event_i]
            rnd.declare(int(event["seat"]), list(event["cards"]))
            event_i += 1
    while event_i < len(declarations):
        event = declarations[event_i]
        if event["stage"] != "final" or event["deal_pos"] != rnd._deal_pos:
            raise RuntimeRefused("Stage-C replay declaration order drift")
        rnd.declare(int(event["seat"]), list(event["cards"]))
        event_i += 1
    rnd.finalize_declare()
    actual_decl = _declaration_record(rnd)
    if (rnd.banker != setup["banker"]
            or rnd.trump_rank != setup["trump_rank"]
            or rnd.trump_suit != setup["trump_suit"]
            or rnd.trump_is_nt != setup["trump_is_nt"]
            or actual_decl != setup["final_declaration"]):
        raise RuntimeRefused("Stage-C replay trump/banker boundary drift")
    if state["surface_type"] == "bury":
        if (rnd.phase != "bury" or rnd.turn != state["seat"]
                or setup["buried"] is not None):
            raise RuntimeRefused("Stage-C replay did not land at bury")
        return rnd
    buried = setup.get("buried")
    if not isinstance(buried, list):
        raise RuntimeRefused("Stage-C play replay lacks frozen bury")
    rnd.bury(int(rnd.banker), list(buried))
    for play in state["plays"]:
        if rnd.turn != play["seat"]:
            raise RuntimeRefused("Stage-C replay play order drift")
        rnd.play(int(play["seat"]), list(play["cards"]))
    if (rnd.phase != "play" or rnd.trick is None or rnd.turn != state["seat"]
            or len(state["plays"]) != state["ply"]
            or len(rnd.history) != state["trick"]):
        raise RuntimeRefused("Stage-C replay did not land at play decision")
    surface = "lead" if not rnd.trick.plays else "follow"
    role = "attacker" if rnd.is_attacker(rnd.turn) else "defender"
    if (surface != state["surface"] or role != state["role"]
            or phase_for_trick(len(rnd.history)) != state["phase"]):
        raise RuntimeRefused("Stage-C replay stratum drift")
    return rnd


def _validate_candidates(state: Mapping[str, object], rnd, net) -> None:
    seat = int(state["seat"])
    if state["surface_type"] == "play":
        candidates, diagnostics = _build_play_union(
            rnd, seat, str(state["state_id"]), str(state["split"]), net)
    else:
        candidates, diagnostics = _build_bury_union(
            rnd, seat, str(state["state_id"]))
    if candidates != state.get("candidates"):
        raise RuntimeRefused("Stage-C candidate union replay drift")
    if diagnostics != state.get("candidate_diagnostics"):
        raise RuntimeRefused("Stage-C candidate diagnostic replay drift")
    cap = 20 if state["surface_type"] == "play" else 33
    if not candidates or len(candidates) > cap:
        raise RuntimeRefused("Stage-C candidate cap/emptiness drift")
    for candidate in candidates:
        clone = copy.deepcopy(rnd)
        try:
            if state["surface_type"] == "play":
                clone.play(seat, list(candidate["cards"]))
            else:
                clone.bury(seat, list(candidate["cards"]))
        except Exception as exc:
            raise RuntimeRefused(
                f"Stage-C candidate is replay-illegal: {exc}") from exc
    stratum = state["stratum"]
    if (stratum == "proposal_disagreement"
            and not (diagnostics["v11_novel"]
                     or diagnostics["structured_novel"])):
        raise RuntimeRefused("Stage-C proposal-disagreement tag is unsupported")
    if (stratum == "structured_point_void"
            and (diagnostics["structured_candidates"] <= 1
                 or not diagnostics["random_novel"])):
        raise RuntimeRefused("Stage-C structured-bury tag is unsupported")
    if stratum == "point_banking_opportunity":
        observed = _point_banking_opportunity(rnd, seat)
        if (observed["opportunity"] is not True
                or observed["telemetry"]
                != state.get("point_banking_selection_tag")):
            raise RuntimeRefused("Stage-C point-banking selection tag drift")
    if (stratum == "exact_late_eligible"
            and not all(len(hand) == 1 for hand in rnd.hands)):
        raise RuntimeRefused("Stage-C exact-late state is not one-card")


def hydrate_candidates(state: dict, net) -> tuple[dict | None, str]:
    hydrated = copy.deepcopy(state)
    rnd = replay_state(hydrated)
    seat = int(hydrated["seat"])
    if hydrated["surface_type"] == "play":
        candidates, diagnostics = _build_play_union(
            rnd, seat, hydrated["state_id"], hydrated["split"], net)
    else:
        candidates, diagnostics = _build_bury_union(
            rnd, seat, hydrated["state_id"])
    hydrated["candidates"] = candidates
    hydrated["candidate_diagnostics"] = diagnostics
    stratum = hydrated["stratum"]
    if (stratum == "proposal_disagreement"
            and not (diagnostics["v11_novel"]
                     or diagnostics["structured_novel"])):
        return None, "no_proposal_disagreement"
    if (stratum == "structured_point_void"
            and (diagnostics["structured_candidates"] <= 1
                 or not diagnostics["random_novel"])):
        return None, "no_structured_bury_diversity"
    if stratum == "champion_uncertainty" and len(candidates) < 2:
        return None, "uncertainty_single_candidate"
    _validate_candidates(hydrated, rnd, net)
    return hydrated, "eligible"


def capture_deal(seed: int, split: str, cell: Mapping[str, object],
                 actor_identity: dict) -> tuple[dict | None, str]:
    game = Game(random.Random(seed))
    rnd = game.start_round()
    actors = []
    actor_streams = []
    declarations = []
    for seat in range(4):
        actor_seed = _seed(
            CTRL.EXPERIMENT_ID, split, seed, "actor", seat, CTRL.ACTOR_POLICY)
        actor_streams.append({"seat": seat, "seed": actor_seed,
                              "policy": CTRL.ACTOR_POLICY})
        actors.append(make_bot(CTRL.ACTOR_POLICY, seed=actor_seed))
    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        cards = actors[seat].decide_declare(rnd, seat)
        if cards:
            rnd.declare(seat, cards)
            declarations.append({
                "stage": "deal", "deal_pos": rnd._deal_pos,
                "seat": seat, "cards": list(cards),
            })
    for seat in range(4):
        cards = actors[seat].decide_declare(rnd, seat, final=True)
        if cards:
            rnd.declare(seat, cards)
            declarations.append({
                "stage": "final", "deal_pos": rnd._deal_pos,
                "seat": seat, "cards": list(cards),
            })
    rnd.finalize_declare()
    if rnd.banker is None or rnd.ordering is None or rnd.phase != "bury":
        return None, "declaration_unreachable"
    if cell["surface_type"] == "bury":
        state = _base_state(
            seed=seed, split=split, cell=cell, seat=int(rnd.banker),
            surface_type="bury", setup=_state_setup(rnd, declarations, None),
            actor_streams=actor_streams, actor_identity=actor_identity,
            plays=[],
        )
        replay_state(state)
        return state, "eligible"
    buried = actors[rnd.banker].decide_bury(rnd, rnd.banker)
    setup = _state_setup(rnd, declarations, buried)
    rnd.bury(rnd.banker, buried)
    target_trick = _target_trick(split, cell, seed)
    plays: list[dict] = []
    while rnd.phase == "play":
        seat = rnd.turn
        assert seat is not None and rnd.trick is not None
        surface = "lead" if not rnd.trick.plays else "follow"
        role = "attacker" if rnd.is_attacker(seat) else "defender"
        phase = phase_for_trick(len(rnd.history))
        target = False
        opportunity = None
        if cell["stratum"] == "point_banking_opportunity":
            if surface == "follow" and role == cell["role"]:
                opportunity = _point_banking_opportunity(rnd, seat)
                target = bool(opportunity["opportunity"])
        elif cell["stratum"] == "exact_late_eligible":
            target = (all(len(hand) == 1 for hand in rnd.hands)
                      and phase == cell["phase"]
                      and surface == cell["surface"]
                      and role == cell["role"])
        else:
            target = (len(rnd.history) == target_trick
                      and surface == cell["surface"]
                      and role == cell["role"]
                      and phase == cell["phase"])
        if target:
            state = _base_state(
                seed=seed, split=split, cell=cell, seat=seat,
                surface_type="play", setup=setup,
                actor_streams=actor_streams, actor_identity=actor_identity,
                plays=plays,
            )
            state["trick"] = len(rnd.history)
            state["phase"] = phase
            state["surface"] = surface
            state["role"] = role
            if opportunity is not None:
                state["point_banking_selection_tag"] = opportunity["telemetry"]
            if (cell["stratum"] == "exact_late_eligible"
                    and any(len(hand) != 1 for hand in rnd.hands)):
                return None, "not_one_card_exact_late"
            replay_state(state)
            return state, "eligible"
        cards = actors[seat].decide_play(rnd, seat)
        rnd.play(seat, list(cards))
        plays.append({"seat": seat, "cards": list(cards)})
    return None, "target_unreachable"


def _sampler_snapshot(bot) -> dict[str, int]:
    return {name: int(getattr(bot, name, 0)) for name in (
        "sample_attempts", "accepted_worlds", "failed_worlds",
        "rejected_worlds", "impossible_worlds",
    )}


def _sampler_delta(before: Mapping[str, int], bot) -> dict[str, int]:
    return {name: int(getattr(bot, name, 0)) - int(value)
            for name, value in before.items()}


def uncertainty_diagnostic(state: Mapping[str, object]) -> tuple[dict | None, str]:
    rnd = replay_state(state)
    seat = int(state["seat"])
    actions = [list(candidate["cards"]) for candidate in state["candidates"]]
    bot = make_bot("mc-strong", seed=_seed(
        CTRL.EXPERIMENT_ID, state["split"], state["state_id"],
        "capture-uncertainty"))
    bot.rng = random.Random(_seed(
        CTRL.EXPERIMENT_ID, state["split"], state["state_id"],
        "capture-uncertainty-worlds"))
    mem = Memory(rnd, seat, own_kitty=getattr(bot, "BANKER_KITTY", True))
    before = _sampler_snapshot(bot)
    values = []
    attempts = 0
    cap = CTRL.UNCERTAINTY_WORLDS * CTRL.UNCERTAINTY_ATTEMPT_FACTOR
    while len(values) < CTRL.UNCERTAINTY_WORLDS and attempts < cap:
        attempts += 1
        sampled = bot._sample_hands(rnd, seat, mem)
        if sampled is None:
            continue
        hands, buried = sampled
        sign = 1 if rnd.is_attacker(seat) else -1
        values.append([
            sign * bot._score(bot._rollout(rnd, seat, hands, buried, action))
            for action in actions
        ])
    counters = _sampler_delta(before, bot)
    diagnostic = {
        "schema": "teacher-stage-c-uncertainty-selection-v1",
        "selection_only": True,
        "may_train_or_label": False,
        "evaluation_complete": False,
        "worlds": len(values),
        "attempts": attempts,
        "candidate_worlds": len(values) * len(actions),
        "sampler_counters": counters,
        "means": None,
        "raw_best_index": None,
        "paired_gap_vs_candidate0": None,
        "paired_se_vs_candidate0": None,
        "production_margin": float(bot.MARGIN),
        "margin_window": UNCERTAINTY_MARGIN_WINDOW,
        "eligible": False,
    }
    if len(values) != CTRL.UNCERTAINTY_WORLDS:
        return diagnostic, "uncertainty_underfilled"
    if (counters["accepted_worlds"] != CTRL.UNCERTAINTY_WORLDS
            or counters["failed_worlds"]
            or counters["rejected_worlds"]
            or counters["impossible_worlds"]):
        return diagnostic, "uncertainty_sampler_refusal"
    means = [sum(row[index] for row in values) / len(values)
             for index in range(len(actions))]
    best = bot._pick_index(actions, means, range(len(actions)))
    gap = means[best] - means[0]
    diffs = [row[best] - row[0] for row in values]
    mean = sum(diffs) / len(diffs)
    variance = sum((value - mean) ** 2 for value in diffs) / (len(diffs) - 1)
    se = math.sqrt(variance / len(diffs))
    margin = float(bot.MARGIN)
    diagnostic.update({
        "evaluation_complete": True,
        "means": means,
        "raw_best_index": best,
        "paired_gap_vs_candidate0": gap,
        "paired_se_vs_candidate0": se,
        "production_margin": margin,
        "eligible": best != 0 and abs(gap - margin) <= UNCERTAINTY_MARGIN_WINDOW,
    })
    if not diagnostic["eligible"]:
        return diagnostic, "outside_uncertainty_window"
    return diagnostic, "eligible"


def _reservoir_add(reservoir: list[dict], state: dict, limit: int) -> None:
    reservoir.append(state)
    reservoir.sort(key=lambda item: (item["selection_priority"], item["state_id"]))
    if len(reservoir) > limit:
        reservoir.pop()


def _expected_shard_path(index: int) -> Path:
    return (REPO / "server/runs/logs" / CTRL.RUN_ID /
            f"shard-{index:02d}.json").resolve()


def _expected_dataset_path() -> Path:
    return (REPO / "server/runs/logs" / CTRL.RUN_ID /
            "state-set.json").resolve()


def _expected_verification_path() -> Path:
    return (REPO / "server/runs/logs" / CTRL.RUN_ID /
            "terminal-verification.json").resolve()


def _shard_seeds(schedule: Mapping[str, object]) -> range:
    return range(
        int(schedule["first_seed"]),
        int(schedule["seed_start"]) + int(schedule["scan_deals"]),
        int(schedule["seed_stride"]),
    )


def _generate_shard_evidence(
    packet: dict,
    schedule: Mapping[str, object],
    *,
    shard_index: int,
    actor_identity: Mapping[str, object],
    net,
    progress_every: int,
    progress_status: str,
) -> tuple[dict, list[dict], dict, dict, dict]:
    """Deterministically reconstruct every scan disposition and reservoir.

    The same function owns original generation and terminal replay.  A stored
    rejection is therefore not evidence by itself: terminal verification
    reruns the exact actor/candidate path for every scheduled seed and requires
    byte-identical scan, diagnostic and retained-state witnesses.
    """
    split = str(schedule["split"])
    cells = {cell["cell_id"]: cell
             for cell in packet["schedule"]["quota_cells"][split]}
    reservoirs: dict[str, list[dict]] = {cell_id: [] for cell_id in cells}
    scan_records: list[dict] = []
    seeds = _shard_seeds(schedule)
    for ordinal, seed in enumerate(seeds, 1):
        cell = _cell_for_seed(packet, split, seed)
        cell_id = str(cell["cell_id"])
        state, reason = capture_deal(seed, split, cell, dict(actor_identity))
        if (state is not None and cell["stratum"] in {
                "proposal_disagreement", "structured_point_void"}):
            state, reason = hydrate_candidates(state, net)
        if state is not None:
            _reservoir_add(
                reservoirs[cell_id], state, int(cell["pre_candidate_limit"]))
        scan_records.append(_scan_record(
            ordinal, seed, cell_id, reason, state))
        if progress_every > 0 and (ordinal % progress_every == 0
                                   or ordinal == len(seeds)):
            print(json.dumps({
                "status": progress_status,
                "shard": shard_index,
                "split": split,
                "deals_scanned": ordinal,
                "deals_total": len(seeds),
                "structurally_retained": sum(
                    len(rows) for rows in reservoirs.values()),
            }, sort_keys=True), file=sys.stderr, flush=True)

    diagnostic_records: list[dict] = []
    for cell_id in sorted(cells):
        cell = cells[cell_id]
        eligible: list[dict] = []
        for index, state in enumerate(reservoirs[cell_id], 1):
            diagnostic = None
            if "candidates" in state:
                hydrated, reason = state, "eligible"
                _validate_candidates(hydrated, replay_state(hydrated), net)
            else:
                hydrated, reason = hydrate_candidates(state, net)
            evaluated = hydrated
            if hydrated is not None and cell["stratum"] == "champion_uncertainty":
                diagnostic, reason = uncertainty_diagnostic(hydrated)
                if diagnostic is not None:
                    hydrated["selection_diagnostic"] = diagnostic
                    evaluated = hydrated
                if diagnostic is None or reason != "eligible":
                    hydrated = None
            diagnostic_records.append(_diagnostic_record(
                cell_id=cell_id,
                state=(evaluated if evaluated is not None else state),
                status=reason,
                eligible=hydrated is not None,
                diagnostic=diagnostic,
            ))
            if hydrated is not None:
                eligible.append(hydrated)
            if cell["stratum"] == "champion_uncertainty":
                print(json.dumps({
                    "status": f"{progress_status}_UNCERTAINTY",
                    "shard": shard_index,
                    "cell_id": cell_id,
                    "candidates_checked": index,
                    "candidates_total": len(reservoirs[cell_id]),
                    "eligible": len(eligible),
                }, sort_keys=True), file=sys.stderr, flush=True)
        eligible.sort(key=lambda item: (
            item["selection_priority"], item["state_id"]))
        reservoirs[cell_id] = eligible[:int(cell["quota"])]
    retained = [state for cell_id in sorted(reservoirs)
                for state in reservoirs[cell_id]]
    if len({state["seed"] for state in retained}) != len(retained):
        raise RuntimeRefused("capture shard retained multiple states per deal")
    for state in retained:
        _validate_retained_state_identity(
            packet, schedule, state, actor_identity)
    witness = {
        "schema": CTRL.GENERATION_WITNESS_SCHEMA,
        "complete": True,
        "scan_records": scan_records,
        "scan_records_sha256": _records_sha256(scan_records),
        "diagnostic_records": diagnostic_records,
        "diagnostic_records_sha256": _records_sha256(diagnostic_records),
    }
    witness["witness_sha256"] = _self_hash(witness, "witness_sha256")
    counts, cell_counts, uncertainty_work = _reconcile_generation_witness(
        packet, schedule, witness, retained)
    max_candidate_worlds = sum(
        int(cell["diagnostic_candidate_limit"] or 0)
        * 20 * CTRL.UNCERTAINTY_WORLDS
        for cell in cells.values())
    if uncertainty_work["candidate_worlds"] > max_candidate_worlds:
        raise RuntimeRefused("capture uncertainty shard exceeded work ceiling")
    max_attempts = sum(
        int(cell["diagnostic_candidate_limit"] or 0)
        * CTRL.UNCERTAINTY_WORLDS * CTRL.UNCERTAINTY_ATTEMPT_FACTOR
        for cell in cells.values())
    if uncertainty_work["attempts"] > max_attempts:
        raise RuntimeRefused(
            "capture uncertainty shard exceeded attempt ceiling")
    return witness, retained, counts, cell_counts, uncertainty_work


def run_shard(*, packet_path: Path, expected_packet_sha256: str,
              receipt_path: Path, expected_receipt_sha256: str,
              shard_index: int, out: Path, progress_every: int) -> dict:
    packet = _controller_packet(packet_path, expected_packet_sha256)
    _receipt(receipt_path, expected_receipt_sha256, packet,
             expected_packet_sha256)
    if not 0 <= shard_index < CTRL.CAPTURE_SHARDS:
        raise RuntimeRefused("capture shard index outside reviewed schedule")
    if out.resolve() != _expected_shard_path(shard_index):
        raise RuntimeRefused("capture shard output differs from reviewed path")
    if os.path.lexists(out) or os.path.lexists(Path(str(out) + ".partial")):
        raise RuntimeRefused("refusing existing capture shard/partial")
    schedule = packet["schedule"]["shards"][shard_index]
    split = str(schedule["split"])
    actor_identity = _actor_identity()
    net = _load_npnet(str(REPO / V11_PATH))
    seeds = _shard_seeds(schedule)
    witness, retained, counts, cell_counts, uncertainty_work = (
        _generate_shard_evidence(
            packet, schedule, shard_index=shard_index,
            actor_identity=actor_identity, net=net,
            progress_every=progress_every, progress_status="SCANNING"))
    # Reopen every mutable identity after compute and before publication.
    _controller_packet(packet_path, expected_packet_sha256)
    _receipt(receipt_path, expected_receipt_sha256, packet,
             expected_packet_sha256)
    payload = {
        "schema": CTRL.SHARD_SCHEMA,
        "run_id": CTRL.RUN_ID,
        "git": packet["producer"]["git"],
        "controller_packet_sha256": expected_packet_sha256,
        "capture_receipt_sha256": expected_receipt_sha256,
        "schedule_sha256": packet["schedule"]["schedule_sha256"],
        "shard_index": shard_index,
        "split": split,
        "schedule": schedule,
        "actor_identity": actor_identity,
        "scan": {
            "seed_count": len(seeds),
            "first_seed": seeds.start,
            "seed_stride": seeds.step,
            "stop_exclusive": seeds.stop,
            "ledger_sha256": witness["scan_records_sha256"],
            "generation_witness_sha256": witness["witness_sha256"],
        },
        "counts": counts,
        "cell_counts": cell_counts,
        "uncertainty_work": uncertainty_work,
        "generation_witness": witness,
        "retained_states": retained,
        "retained_state_ids_sha256": CTRL.sha256_bytes(CTRL.canonical_json(
            [state["state_id"] for state in retained])),
        "complete": True,
        "labels_authorized": False,
        "training_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
    }
    payload["shard_sha256"] = _self_hash(payload, "shard_sha256")
    CTRL.publish_exclusive(out, payload)
    return payload


def validate_shard(shard: Mapping[str, object], packet: dict,
                   receipt_sha256: str, index: int) -> None:
    schedule = packet["schedule"]["shards"][index]
    fixed = {
        "schema": CTRL.SHARD_SCHEMA,
        "run_id": CTRL.RUN_ID,
        "git": packet["producer"]["git"],
        "controller_packet_sha256": packet["external_sha256"],
        "capture_receipt_sha256": receipt_sha256,
        "schedule_sha256": packet["schedule"]["schedule_sha256"],
        "shard_index": index,
        "split": schedule["split"],
        "schedule": schedule,
        "complete": True,
        "labels_authorized": False,
        "training_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
    }
    for key, value in fixed.items():
        if shard.get(key) != value:
            raise RuntimeRefused(f"capture shard {index} field drift: {key}")
    if shard.get("shard_sha256") != _self_hash(shard, "shard_sha256"):
        raise RuntimeRefused(f"capture shard {index} self-hash drift")
    scan = shard.get("scan", {})
    seeds = _shard_seeds(schedule)
    if (scan.get("seed_count") != len(seeds)
            or scan.get("first_seed") != seeds.start
            or scan.get("seed_stride") != seeds.step
            or scan.get("stop_exclusive") != seeds.stop):
        raise RuntimeRefused(f"capture shard {index} seed coverage drift")
    states = shard.get("retained_states")
    if not isinstance(states, list):
        raise RuntimeRefused(f"capture shard {index} retained state type")
    if (shard.get("retained_state_ids_sha256")
            != CTRL.sha256_bytes(CTRL.canonical_json(
                [state.get("state_id") for state in states]))):
        raise RuntimeRefused(f"capture shard {index} state identity digest drift")
    actor_identity = _actor_identity()
    if shard.get("actor_identity") != actor_identity:
        raise RuntimeRefused(f"capture shard {index} actor identity drift")
    for state in states:
        _validate_retained_state_identity(
            packet, schedule, state, actor_identity)
    witness = shard.get("generation_witness")
    counts, cell_counts, uncertainty_work = _reconcile_generation_witness(
        packet, schedule, witness, states)
    if (shard.get("counts") != counts
            or shard.get("cell_counts") != cell_counts
            or shard.get("uncertainty_work") != uncertainty_work):
        raise RuntimeRefused(
            f"capture shard {index} generation/work counters drift")
    if (scan.get("ledger_sha256") != witness.get("scan_records_sha256")
            or scan.get("generation_witness_sha256")
            != witness.get("witness_sha256")):
        raise RuntimeRefused(f"capture shard {index} scan ledger drift")
    max_candidate_worlds = sum(
        int(cell["diagnostic_candidate_limit"] or 0)
        * 20 * CTRL.UNCERTAINTY_WORLDS
        for cell in packet["schedule"]["quota_cells"][str(schedule["split"])]
    )
    if uncertainty_work["candidate_worlds"] > max_candidate_worlds:
        raise RuntimeRefused(
            f"capture shard {index} uncertainty work ceiling drift")
    max_attempts = sum(
        int(cell["diagnostic_candidate_limit"] or 0)
        * CTRL.UNCERTAINTY_WORLDS * CTRL.UNCERTAINTY_ATTEMPT_FACTOR
        for cell in packet["schedule"]["quota_cells"][str(schedule["split"])]
    )
    if uncertainty_work["attempts"] > max_attempts:
        raise RuntimeRefused(
            f"capture shard {index} uncertainty attempt ceiling drift")


def replay_shard_dispositions(
    shard: Mapping[str, object],
    packet: dict,
    receipt_sha256: str,
    index: int,
    *,
    progress_every: int,
) -> dict:
    """Replay every scheduled deal and require the full witness byte-for-byte.

    Structural witness validation cannot prove that an omitted state truly was
    ineligible.  This terminal path reconstructs the actor trajectory,
    candidate hydration, uncertainty fold and both reservoirs from the seed
    schedule.  It therefore catches a forged rejection even when every stored
    digest and counter was recomputed around the forgery.
    """
    validate_shard(shard, packet, receipt_sha256, index)
    schedule = packet["schedule"]["shards"][index]
    actor_identity = _actor_identity()
    net = _load_npnet(str(REPO / V11_PATH))
    witness, retained, counts, cell_counts, uncertainty_work = (
        _generate_shard_evidence(
            packet, schedule, shard_index=index,
            actor_identity=actor_identity, net=net,
            progress_every=progress_every,
            progress_status="REPLAYING_DISPOSITIONS"))
    if witness != shard.get("generation_witness"):
        raise RuntimeRefused(
            f"capture shard {index} replay-authenticated disposition drift")
    if retained != shard.get("retained_states"):
        raise RuntimeRefused(
            f"capture shard {index} replay-authenticated reservoir drift")
    if (counts != shard.get("counts")
            or cell_counts != shard.get("cell_counts")
            or uncertainty_work != shard.get("uncertainty_work")):
        raise RuntimeRefused(
            f"capture shard {index} replay-authenticated counters drift")
    return {
        "shard_index": index,
        "deals_replayed": len(_shard_seeds(schedule)),
        "generation_witness_sha256": witness["witness_sha256"],
        "retained_state_ids_sha256": shard["retained_state_ids_sha256"],
        "uncertainty_work": uncertainty_work,
        "byte_identical": True,
    }


def _replay_shard_from_paths(args: tuple[str, str, str, str, int, int]) -> dict:
    """Spawn-safe worker for the terminal full-population replay."""
    (packet_name, packet_sha256, receipt_name, receipt_sha256,
     index, progress_every) = args
    packet_path = Path(packet_name)
    receipt_path = Path(receipt_name)
    packet = _controller_packet(packet_path, packet_sha256)
    _receipt(receipt_path, receipt_sha256, packet, packet_sha256)
    shard_path = _expected_shard_path(index)
    if not _terminal_file(shard_path):
        raise RuntimeRefused(
            f"capture shard {index} is missing before disposition replay")
    before_sha256 = CTRL.sha256_file(shard_path)
    shard = _load_json(shard_path)
    summary = replay_shard_dispositions(
        shard, packet, receipt_sha256, index,
        progress_every=progress_every)
    if CTRL.sha256_file(shard_path) != before_sha256:
        raise RuntimeRefused(
            f"capture shard {index} changed during disposition replay")
    return {**summary, "shard_sha256": before_sha256}


def replay_all_shard_dispositions(
    *,
    packet_path: Path,
    expected_packet_sha256: str,
    receipt_path: Path,
    expected_receipt_sha256: str,
    workers: int,
    progress_every: int,
) -> list[dict]:
    if (isinstance(workers, bool) or not isinstance(workers, int)
            or not 1 <= workers <= CTRL.CAPTURE_SHARDS):
        raise RuntimeRefused("disposition replay worker count outside 1..24")
    if (isinstance(progress_every, bool) or not isinstance(progress_every, int)
            or progress_every <= 0):
        raise RuntimeRefused("disposition replay progress cadence must be positive")
    packet = _controller_packet(packet_path, expected_packet_sha256)
    _receipt(receipt_path, expected_receipt_sha256, packet,
             expected_packet_sha256)
    inputs = [(
        str(packet_path.resolve()), expected_packet_sha256,
        str(receipt_path.resolve()), expected_receipt_sha256,
        index, progress_every,
    ) for index in range(CTRL.CAPTURE_SHARDS)]
    summaries = []
    context = multiprocessing.get_context("spawn")
    with concurrent.futures.ProcessPoolExecutor(
            max_workers=workers, mp_context=context) as pool:
        futures = [pool.submit(_replay_shard_from_paths, value)
                   for value in inputs]
        try:
            for future in concurrent.futures.as_completed(futures):
                summaries.append(future.result())
        except BaseException:
            for future in futures:
                future.cancel()
            raise
    summaries.sort(key=lambda item: item["shard_index"])
    if ([item["shard_index"] for item in summaries]
            != list(range(CTRL.CAPTURE_SHARDS))
            or sum(item["deals_replayed"] for item in summaries)
            != CTRL.TERMINAL_DISPOSITION_REPLAY_DEALS
            or not all(item["byte_identical"] for item in summaries)):
        raise RuntimeRefused("terminal disposition replay population drift")
    replay_candidate_worlds = sum(
        item["uncertainty_work"]["candidate_worlds"] for item in summaries)
    replay_attempts = sum(
        item["uncertainty_work"]["attempts"] for item in summaries)
    if (replay_candidate_worlds > packet["schedule"][
            "max_terminal_replay_uncertainty_candidate_worlds"]
            or replay_attempts > packet["schedule"][
                "max_terminal_replay_uncertainty_attempts"]):
        raise RuntimeRefused(
            "terminal disposition replay uncertainty work exceeded ceiling")
    return summaries


def _audit_rows(states: Sequence[dict], packet: dict) -> list[str]:
    quota = packet["parents"]
    del quota  # Parent presence is already revalidated; use immutable literals below.
    requirements = {
        "play:ordinary_anchor": 48,
        "play:champion_uncertainty": 48,
        "play:proposal_disagreement": 48,
        "play:exact_late_eligible": 48,
        "play:point_banking_opportunity": 32,
        "bury:*": 32,
    }
    selected = []
    for key, count in requirements.items():
        surface, stratum = key.split(":")
        pool = [state for state in states if state["split"] == "REPORT"
                and state["surface_type"] == surface
                and (stratum == "*" or state["stratum"] == stratum)]
        pool.sort(key=lambda state: hashlib.sha256(
            f"{CTRL.EXPERIMENT_ID}|audit|{state['state_id']}".encode()).hexdigest())
        if len(pool) < count:
            raise RuntimeRefused(f"Stage-C REPORT audit quota underfilled: {key}")
        selected.extend(state["state_id"] for state in pool[:count])
    if len(selected) != 256 or len(set(selected)) != 256:
        raise RuntimeRefused("Stage-C REPORT audit population drift")
    return selected


def _dataset_payload(packet: dict, receipt_sha256: str,
                     shards: Sequence[dict]) -> dict:
    retained = [state for shard in shards for state in shard["retained_states"]]
    selected = []
    shortages = []
    counts = Counter()
    for split in packet["schedule"]["split_order"]:
        for cell in packet["schedule"]["quota_cells"][split]:
            pool = [state for state in retained
                    if state["cell_id"] == cell["cell_id"]]
            pool.sort(key=lambda state: (
                state["selection_priority"], state["state_id"]))
            quota = int(cell["quota"])
            if len(pool) < quota:
                shortages.append({
                    "cell_id": cell["cell_id"],
                    "available": len(pool), "required": quota,
                })
                continue
            for rank, state in enumerate(pool[:quota], 1):
                admitted = copy.deepcopy(state)
                admitted["selection_metadata"] = {
                    "rule": (
                        "global_hash_smallest_from_exact_score_free_scan"
                        if state["stratum"] != "champion_uncertainty" else
                        "global_hash_smallest_after_fixed_per_shard_"
                        "pre_diagnostic_reservoir_and_n30_eligibility"
                    ),
                    "eligible_retained_across_shards": len(pool),
                    "quota": quota,
                    "rank": rank,
                    "selection_features_may_train_or_label": False,
                }
                selected.append(admitted)
                counts[f"{split}:{state['surface_type']}:{state['stratum']}"] += 1
    if shortages:
        raise RuntimeRefused(
            "Stage-C capture TERMINAL_HOLD_NO_EXTENSION: "
            + json.dumps(shortages, sort_keys=True))
    selected.sort(key=lambda state: (
        packet["schedule"]["split_order"].index(state["split"]),
        state["cell_id"], state["selection_priority"], state["state_id"]))
    required = packet["result_contract"]
    if (len(selected) != required["required_states"]
            or sum(state["surface_type"] == "play" for state in selected)
            != required["required_play_states"]
            or sum(state["surface_type"] == "bury" for state in selected)
            != required["required_bury_states"]
            or len({state["seed"] for state in selected}) != len(selected)):
        raise RuntimeRefused("Stage-C selected population totals/uniqueness drift")
    split_counts = Counter(state["split"] for state in selected)
    if dict(split_counts) != required["required_split_states"]:
        raise RuntimeRefused("Stage-C selected split totals drift")
    audit = _audit_rows(selected, packet)
    payload = {
        "schema": CTRL.DATASET_SCHEMA,
        "run_id": CTRL.RUN_ID,
        "git": packet["producer"]["git"],
        "controller_packet_sha256": packet["external_sha256"],
        "capture_receipt_sha256": receipt_sha256,
        "schedule_sha256": packet["schedule"]["schedule_sha256"],
        "shard_inputs": [{
            "index": shard["shard_index"],
            "sha256": shard["external_sha256"],
            "ledger_sha256": shard["scan"]["ledger_sha256"],
            "generation_witness_sha256": shard["generation_witness"][
                "witness_sha256"],
            "diagnostic_records_sha256": shard["generation_witness"][
                "diagnostic_records_sha256"],
        } for shard in shards],
        "complete": True,
        "state_count": len(selected),
        "split_counts": dict(sorted(split_counts.items())),
        "surface_counts": {
            "play": sum(state["surface_type"] == "play" for state in selected),
            "bury": sum(state["surface_type"] == "bury" for state in selected),
        },
        "cell_counts": dict(sorted(counts.items())),
        "report_audit_state_ids": audit,
        "report_audit_state_ids_sha256": CTRL.sha256_bytes(
            CTRL.canonical_json(audit)),
        "states": selected,
        "states_sha256": CTRL.sha256_bytes(CTRL.canonical_json(selected)),
        "terminal_disposition_replay_required": True,
        "state_set_review_authorized": False,
        "labels_authorized": False,
        "training_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    payload["dataset_sha256"] = _self_hash(payload, "dataset_sha256")
    return payload


def _load_shards(packet: dict, receipt_sha256: str,
                 shard_paths: Sequence[Path]) -> list[dict]:
    if len(shard_paths) != CTRL.CAPTURE_SHARDS:
        raise RuntimeRefused("Stage-C dataset freeze requires every shard")
    shards = []
    for index, path in enumerate(shard_paths):
        if path.resolve() != _expected_shard_path(index) or not _terminal_file(path):
            raise RuntimeRefused(f"Stage-C shard {index} path/type drift")
        shard = _load_json(path)
        validate_shard(shard, packet, receipt_sha256, index)
        shard = copy.deepcopy(shard)
        shard["external_sha256"] = CTRL.sha256_file(path)
        shards.append(shard)
    if [shard["shard_index"] for shard in shards] != list(range(CTRL.CAPTURE_SHARDS)):
        raise RuntimeRefused("Stage-C shard identity population drift")
    scanned = sum(int(shard["scan"]["seed_count"]) for shard in shards)
    if scanned != packet["schedule"]["scan_deals"]:
        raise RuntimeRefused("Stage-C exact scan-deal total drift")
    candidate_worlds = sum(
        int(shard["uncertainty_work"]["candidate_worlds"])
        for shard in shards)
    if candidate_worlds > packet["schedule"]["max_uncertainty_candidate_worlds"]:
        raise RuntimeRefused("Stage-C capture selection work exceeded ceiling")
    attempts = sum(int(shard["uncertainty_work"]["attempts"])
                   for shard in shards)
    if attempts > packet["schedule"]["max_uncertainty_attempts"]:
        raise RuntimeRefused(
            "Stage-C capture selection attempts exceeded ceiling")
    return shards


def freeze_dataset(*, packet_path: Path, expected_packet_sha256: str,
                   receipt_path: Path, expected_receipt_sha256: str,
                   shard_paths: Sequence[Path], out: Path) -> dict:
    packet = _controller_packet(packet_path, expected_packet_sha256)
    _receipt(receipt_path, expected_receipt_sha256, packet,
             expected_packet_sha256)
    if out.resolve() != _expected_dataset_path():
        raise RuntimeRefused("Stage-C dataset output differs from reviewed path")
    if os.path.lexists(out) or os.path.lexists(Path(str(out) + ".partial")):
        raise RuntimeRefused("refusing existing Stage-C dataset/partial")
    shards = _load_shards(packet, expected_receipt_sha256, shard_paths)
    payload = _dataset_payload(packet, expected_receipt_sha256, shards)
    net = _load_npnet(str(REPO / V11_PATH))
    for index, state in enumerate(payload["states"], 1):
        rnd = replay_state(state)
        _validate_candidates(state, rnd, net)
        print(json.dumps({
            "status": "FREEZE_REPLAY",
            "states_checked": index,
            "states_total": len(payload["states"]),
        }, sort_keys=True), file=sys.stderr, flush=True)
    # Close every source/artifact TOCTOU window before publication.
    packet = _controller_packet(packet_path, expected_packet_sha256)
    _receipt(receipt_path, expected_receipt_sha256, packet,
             expected_packet_sha256)
    shards = _load_shards(packet, expected_receipt_sha256, shard_paths)
    if _dataset_payload(packet, expected_receipt_sha256, shards) != payload:
        raise RuntimeRefused("Stage-C dataset recomputation changed before publish")
    CTRL.publish_exclusive(out, payload)
    return payload


def verify_dataset(*, packet_path: Path, expected_packet_sha256: str,
                   receipt_path: Path, expected_receipt_sha256: str,
                   shard_paths: Sequence[Path], dataset_path: Path,
                   replay_every_selected_state: bool,
                   disposition_replay_workers: int,
                   disposition_progress_every: int,
                   out: Path) -> dict:
    if not replay_every_selected_state:
        raise RuntimeRefused(
            "Stage-C terminal verification requires every selected-state replay")
    if out.resolve() != _expected_verification_path():
        raise RuntimeRefused(
            "Stage-C terminal-verification output differs from reviewed path")
    if os.path.lexists(out) or os.path.lexists(Path(str(out) + ".partial")):
        raise RuntimeRefused(
            "refusing existing Stage-C terminal verification/partial")
    packet = _controller_packet(packet_path, expected_packet_sha256)
    if (disposition_replay_workers != packet["result_contract"][
            "terminal_disposition_replay_workers"]
            or disposition_progress_every != packet["result_contract"][
                "terminal_disposition_progress_every"]):
        raise RuntimeRefused(
            "terminal disposition replay worker/progress contract drift")
    _receipt(receipt_path, expected_receipt_sha256, packet,
             expected_packet_sha256)
    shards = _load_shards(packet, expected_receipt_sha256, shard_paths)
    if dataset_path.resolve() != _expected_dataset_path() or not _terminal_file(
            dataset_path):
        raise RuntimeRefused("Stage-C dataset path/type drift")
    actual = _load_json(dataset_path)
    expected = _dataset_payload(packet, expected_receipt_sha256, shards)
    if actual != expected:
        raise RuntimeRefused("Stage-C dataset full recomputation drift")
    if actual.get("dataset_sha256") != _self_hash(actual, "dataset_sha256"):
        raise RuntimeRefused("Stage-C dataset self-hash drift")
    disposition_replays = replay_all_shard_dispositions(
        packet_path=packet_path,
        expected_packet_sha256=expected_packet_sha256,
        receipt_path=receipt_path,
        expected_receipt_sha256=expected_receipt_sha256,
        workers=disposition_replay_workers,
        progress_every=disposition_progress_every,
    )
    capture_uncertainty = {
        "attempts": sum(item["uncertainty_work"]["attempts"]
                        for item in shards),
        "worlds": sum(item["uncertainty_work"]["worlds"]
                      for item in shards),
        "candidate_worlds": sum(
            item["uncertainty_work"]["candidate_worlds"] for item in shards),
    }
    replay_uncertainty = {
        "attempts": sum(item["uncertainty_work"]["attempts"]
                        for item in disposition_replays),
        "worlds": sum(item["uncertainty_work"]["worlds"]
                      for item in disposition_replays),
        "candidate_worlds": sum(
            item["uncertainty_work"]["candidate_worlds"]
            for item in disposition_replays),
    }
    total_uncertainty = {
        key: capture_uncertainty[key] + replay_uncertainty[key]
        for key in capture_uncertainty
    }
    if (total_uncertainty["candidate_worlds"] > packet["schedule"][
            "max_total_uncertainty_candidate_worlds"]
            or total_uncertainty["attempts"] > packet["schedule"][
                "max_total_uncertainty_attempts"]):
        raise RuntimeRefused("capture plus terminal uncertainty work exceeded cap")
    net = _load_npnet(str(REPO / V11_PATH))
    for index, state in enumerate(actual["states"], 1):
        rnd = replay_state(state)
        _validate_candidates(state, rnd, net)
        if state["stratum"] == "champion_uncertainty":
            diagnostic = state.get("selection_diagnostic", {})
            recomputed, reason = uncertainty_diagnostic(state)
            if (diagnostic.get("eligible") is not True
                    or diagnostic.get("may_train_or_label") is not False
                    or reason != "eligible" or recomputed != diagnostic):
                raise RuntimeRefused("Stage-C uncertainty selection drift")
        print(json.dumps({
            "status": "VERIFYING",
            "states_checked": index,
            "states_total": len(actual["states"]),
        }, sort_keys=True), file=sys.stderr, flush=True)
    _controller_packet(packet_path, expected_packet_sha256)
    _receipt(receipt_path, expected_receipt_sha256, packet,
             expected_packet_sha256)
    for path, shard in zip(shard_paths, shards, strict=True):
        if CTRL.sha256_file(path) != shard["external_sha256"]:
            raise RuntimeRefused("Stage-C shard changed during verification")
    if CTRL.sha256_file(dataset_path) != CTRL.sha256_bytes(
            CTRL.canonical_json(actual)):
        raise RuntimeRefused("Stage-C dataset changed during verification")
    payload = {
        "schema": CTRL.VERIFICATION_SCHEMA,
        "run_id": CTRL.RUN_ID,
        "git": packet["producer"]["git"],
        "controller_packet_sha256": expected_packet_sha256,
        "capture_receipt_sha256": expected_receipt_sha256,
        "schedule_sha256": packet["schedule"]["schedule_sha256"],
        "status": "VERIFIED_STAGE_C_CAPTURE",
        "dataset_sha256": CTRL.sha256_file(dataset_path),
        "states": actual["state_count"],
        "split_counts": actual["split_counts"],
        "surface_counts": actual["surface_counts"],
        "replay_every_selected_state": True,
        "terminal_disposition_replay_deals": sum(
            item["deals_replayed"] for item in disposition_replays),
        "terminal_disposition_replay_workers": disposition_replay_workers,
        "disposition_replays": disposition_replays,
        "capture_uncertainty_work": capture_uncertainty,
        "terminal_replay_uncertainty_work": replay_uncertainty,
        "total_uncertainty_work": total_uncertainty,
        "all_scan_dispositions_replay_authenticated": True,
        "state_set_review_authorized": True,
        "labels_authorized": False,
        "training_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    payload["verification_sha256"] = _self_hash(
        payload, "verification_sha256")
    _controller_packet(packet_path, expected_packet_sha256)
    _receipt(receipt_path, expected_receipt_sha256, packet,
             expected_packet_sha256)
    CTRL.publish_exclusive(out, payload)
    return payload


def _identity_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--expected-git", required=True)
    parser.add_argument("--controller-packet", required=True)
    parser.add_argument("--expected-controller-packet-sha256", required=True)


def _receipt_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--capture-receipt", required=True)
    parser.add_argument("--expected-capture-receipt-sha256", required=True)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    admit_parser = commands.add_parser("admit")
    _identity_args(admit_parser)
    admit_parser.add_argument("--review-record", required=True)
    admit_parser.add_argument("--namespace", required=True)
    admit_parser.add_argument("--out", required=True)

    shard_parser = commands.add_parser("run-shard")
    _identity_args(shard_parser)
    _receipt_args(shard_parser)
    shard_parser.add_argument("--shard-index", type=int, required=True)
    shard_parser.add_argument("--progress-every", type=int, default=250)
    shard_parser.add_argument("--out", required=True)

    freeze_parser = commands.add_parser("freeze-dataset")
    _identity_args(freeze_parser)
    _receipt_args(freeze_parser)
    freeze_parser.add_argument("--shards", nargs="+", required=True)
    freeze_parser.add_argument("--out", required=True)

    verify_parser = commands.add_parser("verify-dataset")
    _identity_args(verify_parser)
    _receipt_args(verify_parser)
    verify_parser.add_argument("--shards", nargs="+", required=True)
    verify_parser.add_argument("--dataset", required=True)
    verify_parser.add_argument("--replay-every-selected-state",
                               action="store_true")
    verify_parser.add_argument("--disposition-replay-workers", type=int,
                               required=True)
    verify_parser.add_argument("--disposition-progress-every", type=int,
                               default=250)
    verify_parser.add_argument("--out", required=True)
    return root


def main(argv: list[str] | None = None) -> None:
    args = parser().parse_args(argv)
    if _git("rev-parse", "HEAD") != args.expected_git:
        raise RuntimeRefused("capture runtime Git differs from expected Git")
    common = {
        "packet_path": Path(args.controller_packet),
        "expected_packet_sha256": args.expected_controller_packet_sha256,
    }
    if args.command == "admit":
        value = admit(
            **common, review_record=Path(args.review_record),
            namespace=Path(args.namespace), out=Path(args.out))
    elif args.command == "run-shard":
        value = run_shard(
            **common, receipt_path=Path(args.capture_receipt),
            expected_receipt_sha256=args.expected_capture_receipt_sha256,
            shard_index=args.shard_index, out=Path(args.out),
            progress_every=args.progress_every)
    elif args.command == "freeze-dataset":
        value = freeze_dataset(
            **common, receipt_path=Path(args.capture_receipt),
            expected_receipt_sha256=args.expected_capture_receipt_sha256,
            shard_paths=[Path(path) for path in args.shards], out=Path(args.out))
    else:
        value = verify_dataset(
            **common, receipt_path=Path(args.capture_receipt),
            expected_receipt_sha256=args.expected_capture_receipt_sha256,
            shard_paths=[Path(path) for path in args.shards],
            dataset_path=Path(args.dataset),
            replay_every_selected_state=args.replay_every_selected_state,
            disposition_replay_workers=args.disposition_replay_workers,
            disposition_progress_every=args.disposition_progress_every,
            out=Path(args.out))
    print(json.dumps(value, sort_keys=True))


if __name__ == "__main__":
    main()
