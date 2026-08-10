#!/usr/bin/env python3
"""Freeze a fresh, outcome-sealed Stage-C REPORT replacement.

The original Stage-C REPORT rows were inspected while diagnosing V11 proposal
recall.  A later V11-free route therefore cannot reuse them as confirmatory
evidence.  This controller deterministically selects the *next* quota-matched
REPORT tranche from the already captured, externally authenticated v7
reservoirs.  It excludes every state and deal seed in the original 2,048-state
set and publishes only hashes/counts -- never state material, Teacher labels,
model predictions, utilities, or report outcomes.

The frozen packet is itself score-free and grants no execution authority.  An
independent review may authorize one V11-free training-controller packet
freeze that binds this sealed REPORT manifest.  The selected states may be
materialized and labeled only after DESIGN/CALIB has selected one capability
and a separate post-selection REPORT packet has passed review.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import stat
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Mapping, Sequence


SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[1]
REPO = SCRIPT.parents[2]
sys.path.insert(0, str(SCRIPT.parent))

import teacher_stage_c_capture_runtime as CAPTURE  # noqa: E402
import teacher_stage_c_label_controller as LABEL  # noqa: E402


SCHEMA = "teacher-stage-c-fresh-report-selection-controller-v1"
PACKET_ID = "teacher-v3-hard-tail-stage-c-fresh-report-selection-v1"
RUN_ID = "teacher-v3-hard-tail-stage-c-fresh-report-selection-v1"
PACKET_PATH = (
    f"server/runs/logs/{RUN_ID}/controller_packet.json"
)
REVIEW_SCHEMA = "teacher-stage-c-fresh-report-selection-review-v1"
REVIEW_MARKER = "TEACHER_STAGE_C_FRESH_REPORT_SELECTION_V1_REVIEW "

CAPTURE_PACKET_PATH = (
    "server/runs/logs/"
    "teacher-v3-hard-tail-stage-c-capture-controller-v7/controller_packet.json"
)
CAPTURE_STATE_SET_PATH = (
    "server/runs/logs/teacher-v3-hard-tail-stage-c-capture-v7/state-set.json"
)
CAPTURE_VERIFICATION_PATH = (
    "server/runs/logs/teacher-v3-hard-tail-stage-c-capture-v7/"
    "terminal-verification.json"
)
CAPTURE_SHARD_DIRECTORY = (
    "server/runs/logs/teacher-v3-hard-tail-stage-c-capture-v7"
)
REPORT_SHARD_INDICES = tuple(range(16, 24))

CAPTURE_PACKET_SHA256 = LABEL.CAPTURE_CONTROLLER_SHA256
CAPTURE_STATE_SET_SHA256 = (
    "c7a769c4efab582a38a4b77e8a707acde65a3e022d5db9fb27f660809e6e8e1c"
)
CAPTURE_VERIFICATION_SHA256 = (
    "143fb2dbad4623969661aca4582e46936a4a23ca032431a177967429fb434adb"
)
EXPECTED_REPORT_STATES = 512
EXPECTED_REPORT_PLAY = 480
EXPECTED_REPORT_BURY = 32
EXPECTED_EFFECTIVE_SPLITS = {"DESIGN": 1024, "CALIB": 512, "REPORT": 512}

SOURCE_PATHS = (
    "server/scripts/teacher_stage_c_fresh_report_controller.py",
    "server/scripts/teacher_stage_c_capture_controller.py",
    "server/scripts/teacher_stage_c_capture_runtime.py",
    "server/scripts/teacher_stage_c_label_controller.py",
)


class FreshReportRefused(RuntimeError):
    """The replacement REPORT population or authority boundary drifted."""


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"))
            + "\n").encode()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def self_hash(value: Mapping[str, object], field: str) -> str:
    payload = dict(value)
    payload.pop(field, None)
    return sha256_bytes(canonical_json(payload))


def manifest_hash(value: object) -> str:
    return sha256_bytes(canonical_json(value))


def is_regular_unlinked(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return False
    return (stat.S_ISREG(info.st_mode) and info.st_nlink == 1
            and not path.is_symlink())


def load_json(path: Path) -> dict:
    if not is_regular_unlinked(path):
        raise FreshReportRefused(f"JSON parent is not regular/unlinked: {path}")
    try:
        value = json.loads(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise FreshReportRefused(f"cannot read JSON parent {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise FreshReportRefused(f"JSON parent root is not an object: {path}")
    return value


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, check=True,
        capture_output=True, text=True,
    ).stdout.strip()


def source_hashes() -> dict[str, str]:
    values = {}
    for logical in SOURCE_PATHS:
        path = REPO / logical
        if not is_regular_unlinked(path):
            raise FreshReportRefused(f"fresh REPORT source unavailable: {logical}")
        values[logical] = sha256_file(path)
    return dict(sorted(values.items()))


def producer_identity(*, smoke: bool) -> dict:
    dirty = bool(_git("status", "--porcelain", "--untracked-files=all"))
    if dirty and not smoke:
        raise FreshReportRefused("real fresh REPORT freeze refuses dirty tree")
    return {
        "git": _git("rev-parse", "HEAD"),
        "tree_dirty": dirty,
        "promotable": not smoke,
        "controller_script_sha256": sha256_file(SCRIPT),
    }


def _capture_parents(
    *, capture_packet_path: Path, state_set_path: Path,
    verification_path: Path, state_set_review_record: Path,
) -> tuple[dict, dict, dict, dict]:
    try:
        capture_packet = LABEL.validate_capture_controller(capture_packet_path)
        state_set, verification, review = LABEL.validate_state_set(
            state_set_path, CAPTURE_STATE_SET_SHA256,
            verification_path, CAPTURE_VERIFICATION_SHA256,
            state_set_review_record)
    except (LABEL.ControllerRefused, CAPTURE.RuntimeRefused) as exc:
        raise FreshReportRefused(f"capture parent refused: {exc}") from exc
    if capture_packet.get("external_sha256") != CAPTURE_PACKET_SHA256:
        raise FreshReportRefused("capture packet external identity drift")
    return capture_packet, state_set, verification, review


def _report_shards(capture_packet: dict, state_set: dict) -> list[dict]:
    inputs = state_set.get("shard_inputs")
    if not isinstance(inputs, list) or len(inputs) != 24:
        raise FreshReportRefused("capture state-set shard manifest drift")
    result = []
    receipt_sha256 = str(state_set.get("capture_receipt_sha256"))
    for index in REPORT_SHARD_INDICES:
        path = (REPO / CAPTURE_SHARD_DIRECTORY / f"shard-{index:02d}.json")
        expected = inputs[index]
        if (not isinstance(expected, dict)
                or not is_regular_unlinked(path)
                or expected.get("index") != index
                or sha256_file(path) != expected.get("sha256")):
            raise FreshReportRefused(f"REPORT shard {index} external hash drift")
        shard = load_json(path)
        try:
            CAPTURE.validate_shard(
                shard, capture_packet, receipt_sha256, index)
        except CAPTURE.RuntimeRefused as exc:
            raise FreshReportRefused(
                f"REPORT shard {index} semantic drift: {exc}") from exc
        if (shard.get("split") != "REPORT"
                or shard.get("generation_witness", {}).get(
                    "diagnostic_records_sha256")
                != expected.get("diagnostic_records_sha256")
                or shard.get("scan", {}).get("ledger_sha256")
                != expected.get("ledger_sha256")):
            raise FreshReportRefused(f"REPORT shard {index} witness drift")
        material = copy.deepcopy(shard)
        material["external_sha256"] = expected["sha256"]
        result.append(material)
    return result


def _state_digest(states: Sequence[Mapping[str, object]]) -> str:
    return manifest_hash(list(states))


def sealed_selection(
    *, capture_packet: dict, state_set: dict, shards: Sequence[dict],
) -> tuple[dict, list[dict]]:
    original_states = state_set.get("states")
    if not isinstance(original_states, list) or len(original_states) != 2048:
        raise FreshReportRefused("original state population drift")
    original_ids = [str(state.get("state_id")) for state in original_states]
    original_id_set = set(original_ids)
    original_seeds = {int(state["seed"]) for state in original_states}
    if len(original_id_set) != len(original_ids):
        raise FreshReportRefused("original state identity collision")
    original_report = [state for state in original_states
                       if state.get("split") == "REPORT"]
    if len(original_report) != EXPECTED_REPORT_STATES:
        raise FreshReportRefused("original REPORT population drift")

    cells = capture_packet.get("schedule", {}).get(
        "quota_cells", {}).get("REPORT")
    if not isinstance(cells, list):
        raise FreshReportRefused("REPORT quota schedule missing")
    cell_by_id = {str(cell.get("cell_id")): cell for cell in cells}
    if len(cell_by_id) != len(cells):
        raise FreshReportRefused("REPORT quota cell identity collision")
    original_by_cell: dict[str, list[dict]] = defaultdict(list)
    for state in original_report:
        original_by_cell[str(state.get("cell_id"))].append(state)
    pools: dict[str, list[dict]] = defaultdict(list)
    for shard in shards:
        for state in shard.get("retained_states", []):
            if state.get("split") != "REPORT":
                raise FreshReportRefused("non-REPORT row entered replacement pool")
            pools[str(state.get("cell_id"))].append(state)

    selected: list[dict] = []
    cell_manifest = []
    for cell_id in sorted(cell_by_id):
        quota = int(cell_by_id[cell_id]["quota"])
        old = sorted(
            original_by_cell.get(cell_id, []),
            key=lambda state: (state["selection_priority"], state["state_id"]))
        pool = sorted(
            pools.get(cell_id, []),
            key=lambda state: (state["selection_priority"], state["state_id"]))
        if len(old) != quota:
            raise FreshReportRefused(
                f"original REPORT quota drift for {cell_id}")
        if [state["state_id"] for state in pool[:quota]] \
                != [state["state_id"] for state in old]:
            raise FreshReportRefused(
                f"original REPORT was not the first frozen tranche: {cell_id}")
        fresh = [state for state in pool
                 if str(state["state_id"]) not in original_id_set]
        if len(fresh) < quota:
            raise FreshReportRefused(
                f"fresh REPORT supply underfilled for {cell_id}")
        chosen = fresh[:quota]
        selected.extend(copy.deepcopy(chosen))
        cell_manifest.append({
            "cell_id": cell_id,
            "quota": quota,
            "original_selected": len(old),
            "retained_supply": len(pool),
            "fresh_supply_after_exclusion": len(fresh),
            "spare_after_replacement": len(fresh) - quota,
            "selected_state_ids_sha256": manifest_hash(
                [state["state_id"] for state in chosen]),
            "selected_state_material_sha256": _state_digest(chosen),
        })

    selected.sort(key=lambda state: (
        str(state["cell_id"]), state["selection_priority"], state["state_id"]))
    selected_ids = [str(state["state_id"]) for state in selected]
    selected_seeds = [int(state["seed"]) for state in selected]
    if (len(selected) != EXPECTED_REPORT_STATES
            or len(set(selected_ids)) != EXPECTED_REPORT_STATES
            or len(set(selected_seeds)) != EXPECTED_REPORT_STATES
            or original_id_set.intersection(selected_ids)
            or original_seeds.intersection(selected_seeds)):
        raise FreshReportRefused("fresh REPORT overlap/uniqueness drift")
    surface_counts = Counter(str(state["surface_type"]) for state in selected)
    if dict(surface_counts) != {
            "play": EXPECTED_REPORT_PLAY, "bury": EXPECTED_REPORT_BURY}:
        raise FreshReportRefused("fresh REPORT surface totals drift")
    if any(LABEL._forbidden_label_key(state) for state in selected):
        raise FreshReportRefused("label/outcome material entered fresh REPORT")

    design_calib = [state for state in original_states
                    if state.get("split") in {"DESIGN", "CALIB"}]
    if len(design_calib) != 1536:
        raise FreshReportRefused("DESIGN/CALIB parent population drift")
    effective_ids = [str(state["state_id"]) for state in design_calib] \
        + selected_ids
    effective_seeds = [int(state["seed"]) for state in design_calib] \
        + selected_seeds
    if len(set(effective_ids)) != 2048 or len(set(effective_seeds)) != 2048:
        raise FreshReportRefused("effective 2,048-state identity overlap")

    sealed = {
        "schema": "teacher-stage-c-fresh-report-sealed-selection-v1",
        "selection_rule": (
            "within each frozen REPORT quota cell, preserve the original "
            "(selection_priority,state_id) ordering, exclude all original "
            "2,048 state IDs/deal seeds, and seal the first quota rows"
        ),
        "old_report_status": "QUARANTINED_DIAGNOSTIC_NEVER_CONFIRMATORY",
        "original_state_ids_sha256": manifest_hash(original_ids),
        "original_report_state_ids_sha256": manifest_hash(
            [str(state["state_id"]) for state in original_report]),
        "design_calib_state_ids_sha256": manifest_hash(
            [str(state["state_id"]) for state in design_calib]),
        "fresh_report_state_ids_sha256": manifest_hash(selected_ids),
        "fresh_report_state_material_sha256": _state_digest(selected),
        "fresh_report_per_state_hashes_sha256": manifest_hash([
            manifest_hash(state) for state in selected]),
        "effective_state_ids_sha256": manifest_hash(effective_ids),
        "effective_state_count": len(effective_ids),
        "effective_split_counts": dict(EXPECTED_EFFECTIVE_SPLITS),
        "fresh_report_states": len(selected),
        "fresh_report_surface_counts": dict(surface_counts),
        "fresh_report_cell_count": len(cell_manifest),
        "fresh_report_min_spare_per_cell": min(
            row["spare_after_replacement"] for row in cell_manifest),
        "state_id_overlap_with_original": 0,
        "deal_seed_overlap_with_original": 0,
        "cell_manifest": cell_manifest,
        "state_material_published": False,
        "teacher_labels_computed": False,
        "model_predictions_computed": False,
        "report_utility_opened": False,
    }
    sealed["sealed_selection_sha256"] = self_hash(
        sealed, "sealed_selection_sha256")
    return sealed, selected


def _report_shard_parents(shards: Sequence[Mapping[str, object]]) -> list[dict]:
    return [{
        "index": int(shard["shard_index"]),
        "external_sha256": shard["external_sha256"],
        "internal_sha256": shard["shard_sha256"],
        "retained_state_ids_sha256": shard["retained_state_ids_sha256"],
    } for shard in shards]


def selection_contract() -> dict:
    return {
        "split": "REPORT",
        "source": "immutable_v7_report_retained_reservoirs",
        "quota_geometry_identical_to_original_report": True,
        "ordering_identical_to_original_capture": True,
        "exclude_every_original_state_and_deal_seed": True,
        "uses_old_label_or_model_outcome": False,
        "recomputes_v11_or_other_proposer_score": False,
        "publishes_selected_state_material": False,
        "post_result_tuning_or_selector_choice": False,
    }


def commands() -> dict:
    return {
        "verify": [
            "{python}",
            "server/scripts/teacher_stage_c_fresh_report_controller.py",
            "verify",
            "--controller-packet", PACKET_PATH,
            "--expected-controller-packet-sha256", "{packet_sha256}",
            "--state-set-review-record", "{state_set_review_record}",
        ],
    }


def authority() -> dict:
    return {
        "fresh_report_states_materialized": False,
        "teacher_labels_computed": False,
        "training_packet_frozen": False,
        "training_authorized": False,
        "report_open_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }


def build_packet(
    *, smoke: bool, capture_packet_path: Path, state_set_path: Path,
    verification_path: Path, state_set_review_record: Path,
) -> dict:
    capture_packet, state_set, verification, state_review = _capture_parents(
        capture_packet_path=capture_packet_path,
        state_set_path=state_set_path,
        verification_path=verification_path,
        state_set_review_record=state_set_review_record)
    shards = _report_shards(capture_packet, state_set)
    sealed, _selected = sealed_selection(
        capture_packet=capture_packet, state_set=state_set, shards=shards)
    sources = source_hashes()
    packet = {
        "schema": SCHEMA,
        "packet_id": PACKET_ID,
        "run_id": RUN_ID,
        "producer": producer_identity(smoke=smoke),
        "runtime_sources": sources,
        "parents": {
            "capture_controller": {
                "external_sha256": CAPTURE_PACKET_SHA256,
                "internal_sha256": capture_packet["packet_sha256"],
                "git": capture_packet["producer"]["git"],
            },
            "original_state_set": {
                "external_sha256": CAPTURE_STATE_SET_SHA256,
                "internal_sha256": state_set["dataset_sha256"],
                "states_sha256": state_set["states_sha256"],
                "review_claim_sha256": manifest_hash(state_review),
            },
            "capture_verification": {
                "external_sha256": CAPTURE_VERIFICATION_SHA256,
                "internal_sha256": verification["verification_sha256"],
            },
            "report_capture_shards": _report_shard_parents(shards),
        },
        "selection_contract": selection_contract(),
        "sealed_selection": sealed,
        "commands": commands(),
        "authority": authority(),
    }
    packet["packet_sha256"] = self_hash(packet, "packet_sha256")
    return packet


def expected_review_claim(packet: Mapping[str, object], external_sha256: str) \
        -> dict:
    producer = packet.get("producer", {})
    if (producer.get("tree_dirty") is not False
            or producer.get("promotable") is not True):
        raise FreshReportRefused(
            "smoke/dirty fresh REPORT packet cannot receive PASS")
    sealed = packet["sealed_selection"]
    parents = packet["parents"]
    return {
        "schema": REVIEW_SCHEMA,
        "git": packet["producer"]["git"],
        "packet_sha256": external_sha256,
        "packet_internal_sha256": packet["packet_sha256"],
        "controller_script_sha256": packet["runtime_sources"][
            "server/scripts/teacher_stage_c_fresh_report_controller.py"],
        "runtime_sources_sha256": manifest_hash(packet["runtime_sources"]),
        "selection_contract_sha256": manifest_hash(
            packet["selection_contract"]),
        "capture_state_set_sha256": parents[
            "original_state_set"]["external_sha256"],
        "capture_verification_sha256": parents[
            "capture_verification"]["external_sha256"],
        "report_capture_shards": len(parents["report_capture_shards"]),
        "fresh_report_states": sealed["fresh_report_states"],
        "fresh_report_play_states": sealed[
            "fresh_report_surface_counts"]["play"],
        "fresh_report_bury_states": sealed[
            "fresh_report_surface_counts"]["bury"],
        "fresh_report_cell_count": sealed["fresh_report_cell_count"],
        "fresh_report_min_spare_per_cell": sealed[
            "fresh_report_min_spare_per_cell"],
        "fresh_report_state_ids_sha256": sealed[
            "fresh_report_state_ids_sha256"],
        "fresh_report_state_material_sha256": sealed[
            "fresh_report_state_material_sha256"],
        "fresh_report_per_state_hashes_sha256": sealed[
            "fresh_report_per_state_hashes_sha256"],
        "sealed_selection_sha256": sealed["sealed_selection_sha256"],
        "report_capture_shard_manifest_sha256": manifest_hash(
            parents["report_capture_shards"]),
        "effective_state_ids_sha256": sealed[
            "effective_state_ids_sha256"],
        "effective_state_count": sealed["effective_state_count"],
        "state_id_overlap_with_original": 0,
        "deal_seed_overlap_with_original": 0,
        "old_report_quarantined": True,
        "state_material_published": False,
        "teacher_labels_computed": False,
        "model_predictions_computed": False,
        "one_v11_free_training_controller_freeze_authorized": True,
        "training_authorized": False,
        "report_open_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
        "independent_review": True,
        "verdict": "PASS",
    }


def validate_packet(
    *, packet_path: Path, expected_external_sha256: str,
    state_set_review_record: Path,
) -> dict:
    if sha256_file(packet_path) != expected_external_sha256:
        raise FreshReportRefused("fresh REPORT packet external SHA-256 drift")
    packet = load_json(packet_path)
    sources = source_hashes()
    producer = packet.get("producer", {})
    if (packet.get("schema") != SCHEMA
            or packet.get("packet_id") != PACKET_ID
            or packet.get("run_id") != RUN_ID
            or packet.get("packet_sha256") != self_hash(packet, "packet_sha256")
            or producer.get("tree_dirty") is not False
            or producer.get("promotable") is not True
            or not isinstance(producer.get("git"), str)
            or len(producer["git"]) != 40
            or producer.get("controller_script_sha256")
            != sources[SOURCE_PATHS[0]]
            or packet.get("runtime_sources") != sources
            or packet.get("selection_contract") != selection_contract()
            or packet.get("commands") != commands()
            or packet.get("authority") != authority()):
        raise FreshReportRefused("fresh REPORT packet identity/authority drift")
    capture_packet, state_set, verification, review = _capture_parents(
        capture_packet_path=(REPO / CAPTURE_PACKET_PATH).resolve(),
        state_set_path=(REPO / CAPTURE_STATE_SET_PATH).resolve(),
        verification_path=(REPO / CAPTURE_VERIFICATION_PATH).resolve(),
        state_set_review_record=state_set_review_record)
    shards = _report_shards(capture_packet, state_set)
    sealed, _selected = sealed_selection(
        capture_packet=capture_packet, state_set=state_set, shards=shards)
    expected_parents = {
        "capture_controller": {
            "external_sha256": CAPTURE_PACKET_SHA256,
            "internal_sha256": capture_packet["packet_sha256"],
            "git": capture_packet["producer"]["git"],
        },
        "original_state_set": {
            "external_sha256": CAPTURE_STATE_SET_SHA256,
            "internal_sha256": state_set["dataset_sha256"],
            "states_sha256": state_set["states_sha256"],
            "review_claim_sha256": manifest_hash(review),
        },
        "capture_verification": {
            "external_sha256": CAPTURE_VERIFICATION_SHA256,
            "internal_sha256": verification["verification_sha256"],
        },
        "report_capture_shards": _report_shard_parents(shards),
    }
    if (packet.get("sealed_selection") != sealed
            or packet.get("parents") != expected_parents):
        raise FreshReportRefused("fresh REPORT sealed recomputation drift")
    return packet


def publish_exclusive(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = Path(str(path) + ".partial")
    if os.path.lexists(path) or os.path.lexists(partial):
        raise FreshReportRefused(f"refusing existing artifact {path}")
    with partial.open("xb") as handle:
        handle.write(canonical_json(payload))
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.link(partial, path, follow_symlinks=False)
    except FileExistsError as exc:
        raise FreshReportRefused(f"refusing overwrite of {path}") from exc
    partial.unlink()


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    root.add_argument("command", choices=("freeze", "verify"))
    root.add_argument(
        "--capture-controller", type=Path,
        default=REPO / CAPTURE_PACKET_PATH)
    root.add_argument(
        "--state-set", type=Path, default=REPO / CAPTURE_STATE_SET_PATH)
    root.add_argument(
        "--capture-verification", type=Path,
        default=REPO / CAPTURE_VERIFICATION_PATH)
    root.add_argument("--state-set-review-record", type=Path, required=True)
    root.add_argument(
        "--controller-packet", type=Path, default=REPO / PACKET_PATH)
    root.add_argument("--expected-controller-packet-sha256")
    root.add_argument("--smoke", action="store_true")
    return root


def main() -> int:
    args = parser().parse_args()
    if args.command == "freeze":
        packet = build_packet(
            smoke=args.smoke,
            capture_packet_path=args.capture_controller.resolve(),
            state_set_path=args.state_set.resolve(),
            verification_path=args.capture_verification.resolve(),
            state_set_review_record=args.state_set_review_record.resolve())
        publish_exclusive(args.controller_packet.resolve(), packet)
        external = sha256_file(args.controller_packet.resolve())
        claim = None if args.smoke else expected_review_claim(packet, external)
        print(json.dumps({
            "packet": str(args.controller_packet),
            "packet_sha256": external,
            "expected_review_claim": claim,
        }, indent=2, sort_keys=True))
        return 0
    if not args.expected_controller_packet_sha256:
        raise FreshReportRefused("verify requires expected packet SHA-256")
    packet = validate_packet(
        packet_path=args.controller_packet.resolve(),
        expected_external_sha256=args.expected_controller_packet_sha256,
        state_set_review_record=args.state_set_review_record.resolve())
    print(json.dumps({
        "verified": True,
        "packet_sha256": args.expected_controller_packet_sha256,
        "expected_review_claim": expected_review_claim(
            packet, args.expected_controller_packet_sha256),
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FreshReportRefused, LABEL.ControllerRefused,
            CAPTURE.RuntimeRefused) as exc:
        print(f"REFUSING: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(3) from exc
