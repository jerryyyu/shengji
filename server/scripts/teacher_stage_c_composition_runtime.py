#!/usr/bin/env python3
"""Admit and execute one reviewed Stage-C whole-game composition screen.

The runtime consumes a durable one-shot slot before issuing a receipt, runs
eight disjoint shards, and aggregates treatment, matched-null and live-
champion arms only after every shard reopens cleanly.  A positive aggregate
may authorize confirmation-packet review; it never confirms, promotes, or
deploys the policy itself.
"""
from __future__ import annotations

import argparse
import contextlib
import importlib
import json
import math
import os
import re
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import Mapping, Sequence


SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[1]
REPO = SCRIPT.parents[2]
sys.path.insert(0, str(SCRIPT.parent))

_CONTROLLER_MODULE = os.environ.get(
    "SHENGJI_STAGE_C_COMPOSITION_CONTROLLER",
    "teacher_stage_c_composition_controller")
if _CONTROLLER_MODULE not in {
        "teacher_stage_c_composition_controller",
        "teacher_stage_c_expanded_composition_controller",
        "teacher_stage_c_expanded_uncertainty_composition_controller"}:
    raise RuntimeError("unrecognized Stage-C composition controller module")
CTRL = importlib.import_module(_CONTROLLER_MODULE)  # noqa: E402
from shengji.ai.registry import make_bot  # noqa: E402
from shengji.rl import stage_c_candidates as CANDIDATES  # noqa: E402
from shengji.rl import stage_c_composition as COMPOSITION  # noqa: E402
from shengji.rl import stage_c_model as MODEL  # noqa: E402
from shengji.rl import stage_c_npnet as NPNET  # noqa: E402
from shengji.rl import stage_c_screen as SCREEN  # noqa: E402
from shengji.rl.npnet import NpNet as V11NpNet  # noqa: E402


V11_PATH = "server/snapshots_v11pair/ep07.npz"
V11_SHA256 = (
    "cd89d6ed7e9d5f798d69ce546107c4dfbef682c5385de39af527026e39e1c003"
)


ADMISSION_SCHEMA = getattr(
    CTRL, "RUNTIME_ADMISSION_SCHEMA",
    "teacher-stage-c-composition-screen-admission-v1")
CAPACITY_ADMISSION_SCHEMA = getattr(
    CTRL, "RUNTIME_CAPACITY_ADMISSION_SCHEMA",
    "teacher-stage-c-composition-capacity-admission-v1")
SUPERVISOR_ADMISSION_SCHEMA = getattr(
    CTRL, "RUNTIME_SUPERVISOR_ADMISSION_SCHEMA",
    "teacher-stage-c-composition-supervisor-admission-v1")
SUPERVISOR_FINAL_SCHEMA = getattr(
    CTRL, "RUNTIME_SUPERVISOR_FINAL_SCHEMA",
    "teacher-stage-c-composition-supervisor-final-v1")
RECEIPT_SCHEMA = getattr(
    CTRL, "RUNTIME_RECEIPT_SCHEMA",
    "teacher-stage-c-composition-screen-receipt-v1")
SHARD_SCHEMA = getattr(
    CTRL, "RUNTIME_SHARD_SCHEMA",
    "teacher-stage-c-composition-screen-shard-v1")
AGGREGATE_SCHEMA = getattr(
    CTRL, "RUNTIME_AGGREGATE_SCHEMA",
    "teacher-stage-c-composition-screen-result-v1")


class CompositionRuntimeRefused(RuntimeError):
    """The reviewed packet, evidence population, or work contract drifted."""


class CompositionSupervisorInterrupted(BaseException):
    """A handled signal terminally interrupted the one-shot screen owner."""

    def __init__(self, signum: int):
        self.signum = int(signum)
        self.signal_name = signal.Signals(signum).name
        super().__init__(
            f"composition supervisor received {self.signal_name}; "
            "all owned shard children are terminally stopped")


canonical_json = CTRL.canonical_json
sha256_bytes = CTRL.sha256_bytes
sha256_file = CTRL.sha256_file
self_hash = CTRL.self_hash
manifest_hash = CTRL.manifest_hash


def is_regular_unlinked(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return False
    return (stat.S_ISREG(info.st_mode) and info.st_nlink == 1
            and not path.is_symlink())


def require_publishable(path: Path, label: str) -> None:
    partial = Path(str(path) + ".partial")
    if os.path.lexists(path) or os.path.lexists(partial):
        raise CompositionRuntimeRefused(
            f"refusing existing {label}: {path}")


def load_json(path: Path) -> dict:
    if not is_regular_unlinked(path):
        raise CompositionRuntimeRefused(
            f"input is not regular/unlinked: {path}")
    try:
        value = json.loads(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise CompositionRuntimeRefused(
            f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise CompositionRuntimeRefused(
            f"JSON root is not an object: {path}")
    return value


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, check=True,
        capture_output=True, text=True,
    ).stdout.strip()


def _require_clean_tree() -> None:
    if _git("status", "--porcelain", "--untracked-files=all"):
        raise CompositionRuntimeRefused(
            "composition screen runtime refuses dirty tree")


def publish_exclusive(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = Path(str(path) + ".partial")
    require_publishable(path, "output")
    with partial.open("xb") as handle:
        handle.write(canonical_json(payload))
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.link(partial, path, follow_symlinks=False)
    except FileExistsError as exc:
        raise CompositionRuntimeRefused(
            f"refusing raced output publication: {path}") from exc
    partial.unlink()


def _expected_packet_path() -> Path:
    return (REPO / CTRL.PACKET_PATH).resolve()


def _expected_receipt_path() -> Path:
    return (REPO / CTRL.RECEIPT_PATH).resolve()


def _expected_capacity_result_path() -> Path:
    return (REPO / CTRL.CAPACITY_RESULT_PATH).resolve()


def _expected_shard_path(index: int) -> Path:
    return (REPO / CTRL.SHARD_PATHS[index]).resolve()


def _expected_aggregate_path() -> Path:
    return (REPO / CTRL.RESULT_PATH).resolve()


def _expected_supervisor_final_path() -> Path:
    return (REPO / CTRL.SUPERVISOR_FINAL_PATH).resolve()


def _path_from_ref(ref: Mapping[str, object], label: str) -> Path:
    absolute = ref.get("absolute_path")
    evidence_root = ref.get("evidence_root_absolute_path")
    logical = ref.get("logical_path")
    if absolute is not None:
        if evidence_root is not None or logical is not None:
            raise CompositionRuntimeRefused(f"{label} reference shape drift")
        path = Path(str(absolute)).resolve()
        if str(path) != absolute:
            raise CompositionRuntimeRefused(
                f"{label} absolute path is not canonical")
        return path
    if evidence_root is not None:
        root = Path(str(evidence_root)).resolve()
        logical_path = Path(str(logical))
        if (str(root) != evidence_root or logical_path.is_absolute()
                or ".." in logical_path.parts):
            raise CompositionRuntimeRefused(
                f"{label} evidence reference drift")
        path = (root / logical_path).resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise CompositionRuntimeRefused(
                f"{label} escapes evidence root") from exc
        return path
    if not isinstance(logical, str):
        raise CompositionRuntimeRefused(f"{label} logical path drift")
    return (REPO / logical).resolve()


def _artifact(ref: Mapping[str, object], label: str) -> tuple[Path, dict]:
    path = _path_from_ref(ref, label)
    expected = ref.get("external_sha256")
    if (not is_regular_unlinked(path) or not CTRL.is_sha256(expected)
            or sha256_file(path) != expected):
        raise CompositionRuntimeRefused(f"{label} path/SHA drift")
    return path, load_json(path)


def _review_claim(path: Path, packet: Mapping[str, object],
                  packet_sha256: str) -> dict:
    if not is_regular_unlinked(path):
        raise CompositionRuntimeRefused(
            "composition review record is not regular/unlinked")
    matches = [line[len(CTRL.REVIEW_MARKER):]
               for line in path.read_text().splitlines()
               if line.startswith(CTRL.REVIEW_MARKER)]
    if len(matches) != 1:
        raise CompositionRuntimeRefused(
            "composition review record needs exactly one marker")
    try:
        claim = json.loads(matches[0])
    except ValueError as exc:
        raise CompositionRuntimeRefused(
            "composition review marker is invalid JSON") from exc
    expected = CTRL.expected_review_claim(packet, packet_sha256)
    if claim != expected:
        raise CompositionRuntimeRefused(
            "composition review claim/authority drift")
    return claim


def _capacity_review_claim(
    path: Path, packet: Mapping[str, object], packet_sha256: str,
    capacity_result: Mapping[str, object], capacity_result_sha256: str,
) -> dict:
    if not is_regular_unlinked(path):
        raise CompositionRuntimeRefused(
            "composition capacity review record is not regular/unlinked")
    matches = [line[len(CTRL.CAPACITY_REVIEW_MARKER):]
               for line in path.read_text().splitlines()
               if line.startswith(CTRL.CAPACITY_REVIEW_MARKER)]
    if len(matches) != 1:
        raise CompositionRuntimeRefused(
            "composition capacity review record needs exactly one marker")
    try:
        claim = json.loads(matches[0])
    except ValueError as exc:
        raise CompositionRuntimeRefused(
            "composition capacity review marker is invalid JSON") from exc
    expected = CTRL.expected_capacity_review_claim(
        packet, packet_sha256, capacity_result, capacity_result_sha256)
    if claim != expected:
        raise CompositionRuntimeRefused(
            "composition capacity review claim/authority drift")
    return claim


def _supervisor_review_claim(
    path: Path, packet: Mapping[str, object], packet_sha256: str,
    supervisor_final: Mapping[str, object], supervisor_final_sha256: str,
) -> dict:
    if not is_regular_unlinked(path):
        raise CompositionRuntimeRefused(
            "composition supervisor review record is not regular/unlinked")
    matches = [line[len(CTRL.SUPERVISOR_REVIEW_MARKER):]
               for line in path.read_text().splitlines()
               if line.startswith(CTRL.SUPERVISOR_REVIEW_MARKER)]
    if len(matches) != 1:
        raise CompositionRuntimeRefused(
            "composition supervisor review record needs exactly one marker")
    try:
        claim = json.loads(matches[0])
    except ValueError as exc:
        raise CompositionRuntimeRefused(
            "composition supervisor review marker is invalid JSON") from exc
    expected = CTRL.expected_supervisor_review_claim(
        packet, packet_sha256, supervisor_final, supervisor_final_sha256)
    if claim != expected:
        raise CompositionRuntimeRefused(
            "composition supervisor review claim/authority drift")
    return claim


def _packet(path: Path, expected_sha256: str) -> tuple[dict, object]:
    _require_clean_tree()
    if (path.resolve() != _expected_packet_path()
            or not is_regular_unlinked(path)
            or sha256_file(path) != expected_sha256):
        raise CompositionRuntimeRefused(
            "composition controller packet path/SHA drift")
    packet = load_json(path)
    authority = packet.get("authority", {})
    if (packet.get("schema") != CTRL.SCHEMA
            or packet.get("packet_id") != CTRL.PACKET_ID
            or packet.get("run_id") != CTRL.RUN_ID
            or packet.get("packet_sha256")
            != self_hash(packet, "packet_sha256")
            or packet.get("producer", {}).get("git")
            != _git("rev-parse", "HEAD")
            or packet.get("producer", {}).get("tree_dirty") is not False
            or packet.get("producer", {}).get("sources")
            != CTRL._source_sha256s()
            or packet.get("runtime_contract") != CTRL.runtime_contract()
            or authority != {
                "capacity_preflight_review_authorized": True,
                "capacity_preflight_launch_authorized": False,
                "screen_packet_review_authorized": False,
                "screen_launch_authorized": False,
                "confirmation_launch_authorized": False,
                "v11_inference_authorized": True,
                "strength_claim": False,
                "production_promotion": False,
                "production_deployment": False,
            }
            or packet.get("candidate_contract")
            != CTRL.candidate_contract()
            or packet.get("capacity_contract")
            != CTRL.capacity_contract()
            or packet.get("screen_contract") != CTRL.screen_contract()
            or packet.get("commands") != CTRL._commands()
            or packet.get("result_contract") != CTRL.result_contract()):
        raise CompositionRuntimeRefused(
            "composition controller packet identity/authority drift")

    parents = packet.get("parents", {})
    if set(parents) != {
            "report_packet", "report_review_record",
            "fresh_report_review_record", "state_set_review_record",
            "report_receipt", "report_result", "report_supervisor_final",
            "report_result_review_record", "report_open_admission_slot"}:
        raise CompositionRuntimeRefused(
            "composition parent population drift")
    report_packet_ref = parents.get("report_packet", {})
    report_review_ref = parents.get("report_review_record", {})
    fresh_report_review_ref = parents.get("fresh_report_review_record", {})
    state_set_review_ref = parents.get("state_set_review_record", {})
    report_receipt_ref = parents.get("report_receipt", {})
    report_result_ref = parents.get("report_result", {})
    report_supervisor_ref = parents.get("report_supervisor_final", {})
    report_result_review_ref = parents.get(
        "report_result_review_record", {})
    try:
        report_packet_path, _ = _artifact(
            report_packet_ref, "composition REPORT packet")
        review_paths = []
        for ref, label in (
                (report_review_ref, "composition REPORT review"),
                (fresh_report_review_ref,
                 "composition fresh REPORT review"),
                (state_set_review_ref, "composition state-set review"),
                (report_result_review_ref,
                 "composition REPORT result review")):
            path = _path_from_ref(ref, label)
            if (not is_regular_unlinked(path)
                    or sha256_file(path) != ref.get("external_sha256")):
                raise CompositionRuntimeRefused(f"{label} path/SHA drift")
            review_paths.append(path)
        (report_review_path, fresh_report_review_path,
         state_set_review_path, report_result_review_path) = review_paths
        report_receipt_path, _ = _artifact(
            report_receipt_ref, "composition REPORT receipt")
        report_result_path = _path_from_ref(
            report_result_ref, "composition REPORT result")
        report_supervisor_path = _path_from_ref(
            report_supervisor_ref, "composition REPORT supervisor final")
        if (not is_regular_unlinked(report_result_path)
                or not is_regular_unlinked(report_supervisor_path)):
            raise CompositionRuntimeRefused(
                "composition REPORT terminal artifact unavailable")
        report_packet, report_result = CTRL.validate_report_result(
            report_packet_path=report_packet_path,
            report_packet_sha256=str(
                report_packet_ref["external_sha256"]),
            report_review_record=report_review_path,
            fresh_report_review_record=fresh_report_review_path,
            state_set_review_record=state_set_review_path,
            report_receipt_path=report_receipt_path,
            report_receipt_sha256=str(
                report_receipt_ref["external_sha256"]),
            report_result_path=report_result_path,
            report_result_sha256=str(
                report_result_ref["external_sha256"]),
            report_supervisor_final_path=report_supervisor_path,
            report_supervisor_final_sha256=str(
                report_supervisor_ref["external_sha256"]),
            report_result_review_record=report_result_review_path)
    except CTRL.CompositionControllerRefused as exc:
        raise CompositionRuntimeRefused(str(exc)) from exc
    if (report_result.get("result_sha256")
            != report_result_ref.get("internal_sha256")
            or report_result.get("decision")
            != report_result_ref.get("decision")
            or report_packet.get("selected_capability")
            != packet.get("selected_capability")):
        raise CompositionRuntimeRefused(
            "composition REPORT parent/capability drift")
    expected_open = {
        "logical_path": report_result["report_open_admission_slot"],
        "external_sha256": report_result[
            "report_open_admission_slot_sha256"],
    }
    if parents.get("report_open_admission_slot") != expected_open:
        raise CompositionRuntimeRefused(
            "composition REPORT-open parent drift")

    try:
        live_parent = make_bot("mc-s0-report-lcb", seed=0)
        COMPOSITION._require_live_report_lcb(live_parent)
    except Exception as exc:
        raise CompositionRuntimeRefused(
            f"composition live parent cannot reopen: {exc}") from exc
    exports = packet.get("model_exports")
    if (not isinstance(exports, list)
            or len(exports) != len(MODEL.TRAINING_SEEDS)
            or packet.get("model_exports_sha256") != manifest_hash(exports)
            or [item.get("logical_path") for item in exports]
            != list(CTRL.MODEL_PATHS)):
        raise CompositionRuntimeRefused(
            "composition model export manifest drift")
    members = []
    for item in exports:
        path = (REPO / str(item["logical_path"])).resolve()
        try:
            member = NPNET.StageCNpNet(
                path, expected_sha256=str(item["sha256"]),
                expected_metadata=item["metadata"])
        except NPNET.StageCNumpyError as exc:
            raise CompositionRuntimeRefused(str(exc)) from exc
        members.append(member)
    capability = packet["selected_capability"]
    try:
        ensemble = NPNET.StageCEnsemble(
            members, surface=str(capability["surface"]),
            head=str(capability["head"]), epoch=int(capability["epoch"]))
    except NPNET.StageCNumpyError as exc:
        raise CompositionRuntimeRefused(str(exc)) from exc
    return packet, ensemble


def _validated_capacity_evidence(
    *, packet: Mapping[str, object], packet_sha256: str,
    controller_review_record: Path, capacity_result_path: Path,
    capacity_result_sha256: str, capacity_review_record: Path,
) -> tuple[dict, dict]:
    capacity = _capacity_result(
        capacity_result_path, capacity_result_sha256, packet,
        packet_sha256, controller_review_record)
    claim = _capacity_review_claim(
        capacity_review_record, packet, packet_sha256,
        capacity, capacity_result_sha256)
    return capacity, claim


def _slot_payload(
    packet: Mapping[str, object], packet_sha256: str,
    review_record: Path, capacity_result: Mapping[str, object],
    capacity_result_sha256: str, capacity_review_record: Path,
) -> dict:
    value = {
        "schema": ADMISSION_SCHEMA,
        "run_id": CTRL.RUN_ID,
        "git": packet["producer"]["git"],
        "controller_packet_sha256": packet_sha256,
        "controller_review_record_sha256": sha256_file(review_record),
        "capacity_result_sha256": capacity_result_sha256,
        "capacity_result_internal_sha256": capacity_result["result_sha256"],
        "capacity_review_record_sha256": sha256_file(
            capacity_review_record),
        "screen_max_shard_seconds": capacity_result[
            "screen_max_shard_seconds"],
        "selected_capability": packet["selected_capability"],
        "model_exports_sha256": packet["model_exports_sha256"],
        "python_executable": packet["runtime_contract"][
            "python_executable"],
        "python_executable_sha256": packet["runtime_contract"][
            "python_executable_sha256"],
        "receipt_path": CTRL.RECEIPT_PATH,
        "consumed_before_receipt": True,
        "retry_or_extension_authorized": False,
    }
    value["slot_sha256"] = self_hash(value, "slot_sha256")
    return value


def _require_admission_outputs_available(
        slot_path: Path, out: Path) -> None:
    if (slot_path != (REPO / CTRL.ADMISSION_PATH).resolve()
            or out.resolve() != _expected_receipt_path()):
        raise CompositionRuntimeRefused(
            "composition screen receipt path drift")
    require_publishable(slot_path, "composition screen admission")
    require_publishable(out, "composition screen receipt")


def admit(
    *, packet_path: Path, expected_packet_sha256: str,
    review_record: Path, capacity_result_path: Path,
    expected_capacity_result_sha256: str,
    capacity_review_record: Path, out: Path,
) -> dict:
    slot_path = (REPO / CTRL.ADMISSION_PATH).resolve()
    _require_admission_outputs_available(slot_path, out)
    packet, _ensemble = _packet(packet_path, expected_packet_sha256)
    controller_claim = _review_claim(
        review_record, packet, expected_packet_sha256)
    capacity, capacity_claim = _validated_capacity_evidence(
        packet=packet, packet_sha256=expected_packet_sha256,
        controller_review_record=review_record,
        capacity_result_path=capacity_result_path,
        capacity_result_sha256=expected_capacity_result_sha256,
        capacity_review_record=capacity_review_record)
    slot = _slot_payload(
        packet, expected_packet_sha256, review_record,
        capacity, expected_capacity_result_sha256, capacity_review_record)
    slot_sha256 = sha256_bytes(canonical_json(slot))
    receipt = {
        "schema": RECEIPT_SCHEMA,
        "run_id": CTRL.RUN_ID,
        "git": packet["producer"]["git"],
        "controller_packet_sha256": expected_packet_sha256,
        "controller_packet_internal_sha256": packet["packet_sha256"],
        "controller_review_record_sha256": sha256_file(review_record),
        "controller_review_claim": controller_claim,
        "capacity_result_sha256": expected_capacity_result_sha256,
        "capacity_result_internal_sha256": capacity["result_sha256"],
        "capacity_review_record_sha256": sha256_file(
            capacity_review_record),
        "capacity_review_claim": capacity_claim,
        "screen_max_shard_seconds": capacity[
            "screen_max_shard_seconds"],
        "admission_slot": CTRL.ADMISSION_PATH,
        "admission_slot_sha256": slot_sha256,
        "selected_capability": packet["selected_capability"],
        "model_exports_sha256": packet["model_exports_sha256"],
        "python_executable": packet["runtime_contract"][
            "python_executable"],
        "python_executable_sha256": packet["runtime_contract"][
            "python_executable_sha256"],
        "screen_execution_authorized": True,
        "confirmation_launch_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
        "retry_or_extension_authorized": False,
    }
    receipt["receipt_sha256"] = self_hash(receipt, "receipt_sha256")
    _require_admission_outputs_available(slot_path, out)
    publish_exclusive(slot_path, slot)
    publish_exclusive(out, receipt)
    return receipt


def _receipt(
    path: Path, expected_sha256: str,
    packet: Mapping[str, object], packet_sha256: str,
    review_record: Path, capacity_result_path: Path,
    capacity_result_sha256: str, capacity_review_record: Path,
) -> tuple[dict, dict]:
    if (path.resolve() != _expected_receipt_path()
            or not is_regular_unlinked(path)
            or sha256_file(path) != expected_sha256):
        raise CompositionRuntimeRefused(
            "composition screen receipt path/SHA drift")
    receipt = load_json(path)
    capacity, capacity_claim = _validated_capacity_evidence(
        packet=packet, packet_sha256=packet_sha256,
        controller_review_record=review_record,
        capacity_result_path=capacity_result_path,
        capacity_result_sha256=capacity_result_sha256,
        capacity_review_record=capacity_review_record)
    slot_path = (REPO / CTRL.ADMISSION_PATH).resolve()
    expected_slot = _slot_payload(
        packet, packet_sha256, review_record, capacity,
        capacity_result_sha256, capacity_review_record)
    if (not is_regular_unlinked(slot_path)
            or load_json(slot_path) != expected_slot
            or sha256_file(slot_path) != receipt.get("admission_slot_sha256")
            or receipt.get("schema") != RECEIPT_SCHEMA
            or receipt.get("run_id") != CTRL.RUN_ID
            or receipt.get("git") != packet["producer"]["git"]
            or receipt.get("controller_packet_sha256") != packet_sha256
            or receipt.get("controller_packet_internal_sha256")
            != packet["packet_sha256"]
            or receipt.get("controller_review_record_sha256")
            != sha256_file(review_record)
            or receipt.get("controller_review_claim")
            != _review_claim(review_record, packet, packet_sha256)
            or receipt.get("capacity_result_sha256")
            != capacity_result_sha256
            or receipt.get("capacity_result_internal_sha256")
            != capacity["result_sha256"]
            or receipt.get("capacity_review_record_sha256")
            != sha256_file(capacity_review_record)
            or receipt.get("capacity_review_claim") != capacity_claim
            or receipt.get("screen_max_shard_seconds")
            != capacity["screen_max_shard_seconds"]
            or receipt.get("admission_slot") != CTRL.ADMISSION_PATH
            or receipt.get("selected_capability")
            != packet["selected_capability"]
            or receipt.get("model_exports_sha256")
            != packet["model_exports_sha256"]
            or receipt.get("python_executable")
            != packet["runtime_contract"]["python_executable"]
            or receipt.get("python_executable_sha256")
            != packet["runtime_contract"]["python_executable_sha256"]
            or receipt.get("screen_execution_authorized") is not True
            or receipt.get("confirmation_launch_authorized") is not False
            or receipt.get("strength_claim") is not False
            or receipt.get("production_promotion") is not False
            or receipt.get("production_deployment") is not False
            or receipt.get("retry_or_extension_authorized") is not False
            or receipt.get("receipt_sha256")
            != self_hash(receipt, "receipt_sha256")):
        raise CompositionRuntimeRefused(
            "composition screen receipt/admission drift")
    return receipt, capacity


def _load_v11_proposer(packet: Mapping[str, object]):
    contract = packet.get("candidate_contract")
    if (not isinstance(contract, dict)
            or contract.get("novel_model_proposer") != "v11pair_ep07_value"
            or contract.get("v11_artifact_path") != V11_PATH
            or contract.get("v11_artifact_sha256") != V11_SHA256
            or packet.get("authority", {}).get("v11_inference_authorized")
            is not True):
        raise CompositionRuntimeRefused(
            "composition V11 proposal contract drift")
    path = REPO / V11_PATH
    if not is_regular_unlinked(path) or sha256_file(path) != V11_SHA256:
        raise CompositionRuntimeRefused(
            "composition V11 proposal artifact drift")
    net = V11NpNet(str(path))
    for value in net.w.values():
        value.flags.writeable = False
    return net


def _factories(packet: Mapping[str, object], ensemble):
    surface = str(packet["selected_capability"]["surface"])
    contract = packet["candidate_contract"]
    if surface == "play":
        v11 = _load_v11_proposer(packet)
        source = CANDIDATES.make_play_candidate_source(
            v11, novel_model_source="v11pair")
        make_stage = COMPOSITION.make_play_report_lcb_bot
    elif surface == "bury":
        source = CANDIDATES.make_bury_candidate_source()
        make_stage = COMPOSITION.make_bury_report_lcb_bot
    else:
        raise CompositionRuntimeRefused(
            "composition selected surface drift")

    def treatment(seed: int):
        kwargs = {"arm": "treatment", "seed": seed}
        if surface == "play":
            kwargs["min_completed_tricks"] = contract[
                "model_min_completed_tricks"]
        return make_stage(ensemble, source, **kwargs)

    def matched_null(seed: int):
        kwargs = {"arm": "matched-null", "seed": seed}
        if surface == "play":
            kwargs["min_completed_tricks"] = contract[
                "model_min_completed_tricks"]
        return make_stage(ensemble, source, **kwargs)

    def champion(seed: int):
        return make_bot("mc-s0-report-lcb", seed=seed)

    return treatment, matched_null, champion


def _capacity_slot_payload(
    packet: Mapping[str, object], packet_sha256: str,
    review_record: Path,
) -> dict:
    value = {
        "schema": CAPACITY_ADMISSION_SCHEMA,
        "run_id": CTRL.RUN_ID,
        "git": packet["producer"]["git"],
        "controller_packet_sha256": packet_sha256,
        "controller_review_record_sha256": sha256_file(review_record),
        "capacity_result_path": CTRL.CAPACITY_RESULT_PATH,
        "consumed_before_gameplay": True,
        "retry_or_extension_authorized": False,
    }
    value["slot_sha256"] = self_hash(value, "slot_sha256")
    return value


def _validate_capacity_slot(
    packet: Mapping[str, object], packet_sha256: str,
    review_record: Path, expected_sha256: str,
) -> None:
    path = (REPO / CTRL.CAPACITY_ADMISSION_PATH).resolve()
    expected = _capacity_slot_payload(packet, packet_sha256, review_record)
    if (not is_regular_unlinked(path)
            or sha256_file(path) != expected_sha256
            or load_json(path) != expected):
        raise CompositionRuntimeRefused(
            "composition capacity admission drift")


def _capacity_projection(elapsed_seconds: float) -> dict:
    per_cluster = elapsed_seconds / CTRL.PREFLIGHT_CLUSTERS
    return {
        "throughput_safety_factor": CTRL.THROUGHPUT_SAFETY_FACTOR,
        "screen_fleet_hours": (
            per_cluster * CTRL.SCREEN_CLUSTERS
            * CTRL.THROUGHPUT_SAFETY_FACTOR / 3_600.0),
        "screen_max_shard_hours": (
            per_cluster * CTRL.CLUSTERS_PER_SHARD
            * CTRL.THROUGHPUT_SAFETY_FACTOR / 3_600.0),
        "screen_fleet_hour_cap": CTRL.SCREEN_FLEET_HOUR_CAP,
        "screen_max_shard_hour_cap": CTRL.SCREEN_MAX_SHARD_HOUR_CAP,
    }


def _capacity_summary_problems(value: Mapping[str, object]) -> list[str]:
    telemetry = value.get("stage_c_telemetry")
    work = value.get("work_totals")
    problems = []
    if (not isinstance(telemetry, dict)
            or set(telemetry) != {"treatment", "matched_null"}
            or not isinstance(work, dict)
            or set(work) != set(SCREEN.LABELS)):
        return ["composition capacity work/telemetry population drift"]
    for label in SCREEN.LABELS:
        sides = work.get(label)
        if not isinstance(sides, dict) or set(sides) != {"arm", "opp"}:
            problems.append(f"capacity {label} side population drift")
            continue
        for side in ("arm", "opp"):
            counters = sides[side]
            feature_on = label != "champion" and side == "arm"
            stage = (telemetry.get(label) if feature_on
                     else SCREEN.feature_off_telemetry())
            counter_problems = SCREEN._counter_problems(counters)
            telemetry_problems = SCREEN._telemetry_problems(
                stage, feature_on=feature_on)
            problems.extend(
                f"capacity {label}/{side}: {problem}"
                for problem in (*counter_problems, *telemetry_problems))
            if (not counter_problems and not telemetry_problems
                    and isinstance(counters, dict)
                    and isinstance(stage, dict)):
                problems.extend(
                    f"capacity {label}/{side}: {problem}"
                    for problem in SCREEN._search_work_problems(
                        counters, stage, feature_on=feature_on,
                        surface=str(value.get("surface"))))
    for label in ("treatment", "matched_null"):
        stage = telemetry.get(label)
        if (not isinstance(stage, dict)
                or stage.get("model_triggers", 0) <= 0):
            problems.append(f"capacity {label} did not trigger")
    return problems


def capacity_preflight(
    *, packet_path: Path, expected_packet_sha256: str,
    review_record: Path, out: Path,
) -> dict:
    if out.resolve() != _expected_capacity_result_path():
        raise CompositionRuntimeRefused(
            "composition capacity output path drift")
    require_publishable(out, "composition capacity output")
    packet, ensemble = _packet(packet_path, expected_packet_sha256)
    _review_claim(review_record, packet, expected_packet_sha256)
    slot_path = (REPO / CTRL.CAPACITY_ADMISSION_PATH).resolve()
    slot = _capacity_slot_payload(
        packet, expected_packet_sha256, review_record)
    publish_exclusive(slot_path, slot)
    slot_sha256 = sha256_file(slot_path)
    treatment, matched_null, champion = _factories(packet, ensemble)
    started = time.monotonic()
    deadline = started + CTRL.PREFLIGHT_MAX_SECONDS
    records = {
        "treatment": SCREEN.run_arm_factories(
            "treatment", treatment, champion,
            clusters=CTRL.PREFLIGHT_CLUSTERS,
            seed0=CTRL.PREFLIGHT_SEED0, run_id=CTRL.RUN_ID,
            policy_has_stage_c=True, progress=False,
            deadline_monotonic=deadline),
        "matched_null": SCREEN.run_arm_factories(
            "matched_null", matched_null, champion,
            clusters=CTRL.PREFLIGHT_CLUSTERS,
            seed0=CTRL.PREFLIGHT_SEED0, run_id=CTRL.RUN_ID,
            policy_has_stage_c=True, progress=False,
            deadline_monotonic=deadline),
        "champion": SCREEN.run_arm_factories(
            "champion", champion, champion,
            clusters=CTRL.PREFLIGHT_CLUSTERS,
            seed0=CTRL.PREFLIGHT_SEED0, run_id=CTRL.RUN_ID,
            policy_has_stage_c=False, progress=False,
            deadline_monotonic=deadline),
    }
    elapsed = round(time.monotonic() - started, 6)
    if (not math.isfinite(elapsed) or elapsed <= 0
            or elapsed > CTRL.PREFLIGHT_MAX_SECONDS):
        raise CompositionRuntimeRefused(
            "composition capacity elapsed-time drift")
    surface = str(packet["selected_capability"]["surface"])
    validation = SCREEN.validate_screen_records(
        records, expected_seed0=CTRL.PREFLIGHT_SEED0,
        expected_clusters=CTRL.PREFLIGHT_CLUSTERS,
        expected_surface=surface)
    projection = _capacity_projection(elapsed)
    capacity_pass = (
        validation["stage_c_telemetry"]["treatment"][
            "model_triggers"] > 0
        and validation["stage_c_telemetry"]["matched_null"][
            "model_triggers"] > 0
        and projection["screen_fleet_hours"]
        <= CTRL.SCREEN_FLEET_HOUR_CAP
        and projection["screen_max_shard_hours"]
        <= CTRL.SCREEN_MAX_SHARD_HOUR_CAP)
    payload = {
        "schema": CTRL.CAPACITY_RESULT_SCHEMA,
        "run_id": CTRL.RUN_ID,
        "git": packet["producer"]["git"],
        "controller_packet_sha256": expected_packet_sha256,
        "controller_review_record_sha256": sha256_file(review_record),
        "capacity_admission_slot": CTRL.CAPACITY_ADMISSION_PATH,
        "capacity_admission_slot_sha256": slot_sha256,
        "surface": surface,
        "seed0": CTRL.PREFLIGHT_SEED0,
        "clusters": CTRL.PREFLIGHT_CLUSTERS,
        "record_counts": validation["record_counts"],
        "stage_c_telemetry": validation["stage_c_telemetry"],
        "work_totals": validation["work_totals"],
        "all_records_exact_work": validation["all_records_exact_work"],
        "elapsed_seconds": elapsed,
        "projection": projection,
        "screen_max_shard_seconds": (
            projection["screen_max_shard_hours"] * 3_600.0),
        "capacity_pass": capacity_pass,
        "score_free": True,
        "outcomes_published": False,
        "decision": ("AUTHORIZE_SCREEN_EXECUTION_REVIEW"
                     if capacity_pass else "TERMINAL_CAPACITY_HOLD"),
        "screen_execution_authorized": False,
        "confirmation_launch_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
        "retry_or_extension_authorized": False,
    }
    payload["result_sha256"] = self_hash(payload, "result_sha256")
    final_packet, _ = _packet(packet_path, expected_packet_sha256)
    _review_claim(review_record, final_packet, expected_packet_sha256)
    _validate_capacity_slot(
        final_packet, expected_packet_sha256, review_record, slot_sha256)
    publish_exclusive(out, payload)
    return payload


def _capacity_result(
    path: Path, expected_sha256: str, packet: Mapping[str, object],
    packet_sha256: str, controller_review_record: Path,
) -> dict:
    if (path.resolve() != _expected_capacity_result_path()
            or not is_regular_unlinked(path)
            or sha256_file(path) != expected_sha256):
        raise CompositionRuntimeRefused(
            "composition capacity result path/SHA drift")
    value = load_json(path)
    elapsed = value.get("elapsed_seconds")
    projection = value.get("projection")
    if (isinstance(elapsed, bool) or not isinstance(elapsed, (int, float))
            or not math.isfinite(float(elapsed)) or float(elapsed) <= 0
            or float(elapsed) > CTRL.PREFLIGHT_MAX_SECONDS
            or projection != _capacity_projection(float(elapsed))
            or value.get("schema") != CTRL.CAPACITY_RESULT_SCHEMA
            or value.get("run_id") != CTRL.RUN_ID
            or value.get("git") != packet["producer"]["git"]
            or value.get("controller_packet_sha256") != packet_sha256
            or value.get("controller_review_record_sha256")
            != sha256_file(controller_review_record)
            or value.get("capacity_admission_slot")
            != CTRL.CAPACITY_ADMISSION_PATH
            or not CTRL.is_sha256(value.get(
                "capacity_admission_slot_sha256"))
            or value.get("surface")
            != packet["selected_capability"]["surface"]
            or value.get("seed0") != CTRL.PREFLIGHT_SEED0
            or value.get("clusters") != CTRL.PREFLIGHT_CLUSTERS
            or value.get("record_counts") != {
                label: 2 * CTRL.PREFLIGHT_CLUSTERS
                for label in SCREEN.LABELS}
            or value.get("all_records_exact_work") is not True
            or value.get("screen_max_shard_seconds")
            != projection.get("screen_max_shard_hours", -1) * 3_600.0
            or value.get("capacity_pass") is not True
            or value.get("score_free") is not True
            or value.get("outcomes_published") is not False
            or value.get("decision") != "AUTHORIZE_SCREEN_EXECUTION_REVIEW"
            or value.get("screen_execution_authorized") is not False
            or value.get("confirmation_launch_authorized") is not False
            or value.get("strength_claim") is not False
            or value.get("production_promotion") is not False
            or value.get("production_deployment") is not False
            or value.get("retry_or_extension_authorized") is not False
            or value.get("result_sha256")
            != self_hash(value, "result_sha256")):
        raise CompositionRuntimeRefused(
            "composition capacity result identity/authority drift")
    if _capacity_summary_problems(value):
        raise CompositionRuntimeRefused(
            "composition capacity work summary drift")
    _validate_capacity_slot(
        packet, packet_sha256, controller_review_record,
        str(value["capacity_admission_slot_sha256"]))
    return value


def _supervisor_slot_payload(
    *, packet: Mapping[str, object], packet_sha256: str,
    receipt_sha256: str, controller_review_record: Path,
    capacity_result_sha256: str, capacity_review_record: Path,
) -> dict:
    value = {
        "schema": SUPERVISOR_ADMISSION_SCHEMA,
        "run_id": CTRL.RUN_ID,
        "git": packet["producer"]["git"],
        "controller_packet_sha256": packet_sha256,
        "screen_receipt_sha256": receipt_sha256,
        "controller_review_record_sha256": sha256_file(
            controller_review_record),
        "capacity_result_sha256": capacity_result_sha256,
        "capacity_review_record_sha256": sha256_file(
            capacity_review_record),
        "child_command_templates": packet["commands"][
            "supervisor_child_shards"],
        "python_executable": packet["runtime_contract"][
            "python_executable"],
        "python_executable_sha256": packet["runtime_contract"][
            "python_executable_sha256"],
        "shard_outputs": list(CTRL.SHARD_PATHS),
        "shard_logs": list(CTRL.SHARD_LOG_PATHS),
        "supervisor_final": CTRL.SUPERVISOR_FINAL_PATH,
        "consumed_before_child_launch": True,
        "retry_after_child_failure_authorized": False,
    }
    value["slot_sha256"] = self_hash(value, "slot_sha256")
    return value


def _validate_supervisor_slot(
    *, path: Path, expected_sha256: str,
    packet: Mapping[str, object], packet_sha256: str,
    receipt_sha256: str, controller_review_record: Path,
    capacity_result_sha256: str, capacity_review_record: Path,
) -> dict:
    expected_path = (REPO / CTRL.SUPERVISOR_ADMISSION_PATH).resolve()
    expected = _supervisor_slot_payload(
        packet=packet, packet_sha256=packet_sha256,
        receipt_sha256=receipt_sha256,
        controller_review_record=controller_review_record,
        capacity_result_sha256=capacity_result_sha256,
        capacity_review_record=capacity_review_record)
    if (path.resolve() != expected_path
            or not is_regular_unlinked(path)
            or sha256_file(path) != expected_sha256
            or load_json(path) != expected):
        raise CompositionRuntimeRefused(
            "composition supervisor admission drift")
    return expected


def _child_command(
    *, index: int, packet: Mapping[str, object], packet_sha256: str,
    controller_review_record: Path, receipt_path: Path,
    receipt_sha256: str, capacity_result_path: Path,
    capacity_result_sha256: str, capacity_review_record: Path,
    supervisor_slot_sha256: str,
) -> list[str]:
    return [
        str(packet["runtime_contract"]["python_executable"]),
        getattr(CTRL, "RUNTIME_SCRIPT_PATH",
                "server/scripts/teacher_stage_c_composition_runtime.py"),
        "run-shard",
        "--expected-git", str(packet["producer"]["git"]),
        "--controller-packet", CTRL.PACKET_PATH,
        "--expected-controller-packet-sha256", packet_sha256,
        "--controller-review-record", str(controller_review_record),
        "--screen-receipt", str(receipt_path),
        "--expected-screen-receipt-sha256", receipt_sha256,
        "--capacity-result", str(capacity_result_path),
        "--expected-capacity-result-sha256", capacity_result_sha256,
        "--capacity-review-record", str(capacity_review_record),
        "--supervisor-admission", CTRL.SUPERVISOR_ADMISSION_PATH,
        "--expected-supervisor-admission-sha256", supervisor_slot_sha256,
        "--shard-index", str(index),
        "--out", CTRL.SHARD_PATHS[index],
    ]


def _terminate_children(processes: Sequence[subprocess.Popen]) -> None:
    live = [process for process in processes if process.poll() is None]
    if not live:
        return
    for process in live:
        try:
            process.terminate()
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + 5.0
    while live and time.monotonic() < deadline:
        live = [process for process in live if process.poll() is None]
        if live:
            time.sleep(0.05)
    for process in live:
        try:
            process.kill()
        except ProcessLookupError:
            pass
    for process in processes:
        try:
            process.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            process.wait()


class SupervisorSignalOwner:
    """Own shard children across signals, including the Popen return gap."""

    def __init__(self) -> None:
        self.signals = tuple(
            getattr(signal, name) for name in CTRL.SUPERVISOR_HANDLED_SIGNALS)
        self.previous: dict[int, object] = {}
        self.processes: list[subprocess.Popen] = []
        self.interrupted_by: int | None = None
        self.spawning = False

    def __enter__(self) -> "SupervisorSignalOwner":
        self.previous = {
            signum: signal.getsignal(signum) for signum in self.signals}
        for signum in self.signals:
            signal.signal(signum, self._handle)
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        try:
            if exc_type is not None or self.processes:
                _terminate_children(self.processes)
        finally:
            for signum, previous in self.previous.items():
                signal.signal(signum, previous)
        return False

    def _handle(self, signum: int, _frame: object) -> None:
        if self.interrupted_by is None:
            self.interrupted_by = signum
            for handled in self.signals:
                signal.signal(handled, signal.SIG_IGN)
        if not self.spawning:
            raise CompositionSupervisorInterrupted(self.interrupted_by)

    def register(self, process: subprocess.Popen) -> None:
        if process in self.processes:
            raise CompositionRuntimeRefused(
                "duplicate composition shard signal ownership")
        self.processes.append(process)

    @contextlib.contextmanager
    def deferred_until_registered(self):
        if self.spawning:
            raise CompositionRuntimeRefused(
                "nested composition shard spawn is not authorized")
        self.spawning = True
        try:
            yield
        finally:
            self.spawning = False
            if self.interrupted_by is not None:
                raise CompositionSupervisorInterrupted(self.interrupted_by)


_SHARD_PROGRESS_RE = re.compile(
    r"^\s*(treatment|matched_null|champion): (\d+)/(\d+) rounds$")


def _latest_shard_progress(index: int, path: Path) -> dict | None:
    """Read only a child's outcome-free progress line for the heartbeat."""
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        match = _SHARD_PROGRESS_RE.match(line)
        if match is not None:
            return {
                "shard_index": index,
                "arm": match.group(1),
                "rounds_complete": int(match.group(2)),
                "rounds_total": int(match.group(3)),
            }
    return None


def supervise(
    *, packet_path: Path, expected_packet_sha256: str,
    review_record: Path, receipt_path: Path,
    expected_receipt_sha256: str, capacity_result_path: Path,
    expected_capacity_result_sha256: str,
    capacity_review_record: Path, out: Path,
) -> dict:
    if out.resolve() != _expected_supervisor_final_path():
        raise CompositionRuntimeRefused(
            "composition supervisor final path drift")
    require_publishable(out, "composition supervisor final")
    output_paths = [(REPO / logical).resolve() for logical in CTRL.SHARD_PATHS]
    log_paths = [(REPO / logical).resolve() for logical in CTRL.SHARD_LOG_PATHS]
    for path in (*output_paths, *log_paths):
        require_publishable(path, "composition supervisor child artifact")
    # Refuse all known shard-attempt collisions before consuming the one
    # supervisor admission. A child crash after this point is terminal.
    for logical in CTRL.SHARD_ADMISSION_PATHS:
        require_publishable(
            (REPO / logical).resolve(),
            "composition supervisor shard-attempt admission")
    require_publishable(
        (REPO / CTRL.AGGREGATE_ADMISSION_PATH).resolve(),
        "composition aggregate admission")
    require_publishable(
        _expected_aggregate_path(), "composition aggregate output")
    packet, _ensemble = _packet(packet_path, expected_packet_sha256)
    _, capacity = _receipt(
        receipt_path, expected_receipt_sha256, packet,
        expected_packet_sha256, review_record, capacity_result_path,
        expected_capacity_result_sha256, capacity_review_record)
    slot_path = (REPO / CTRL.SUPERVISOR_ADMISSION_PATH).resolve()
    require_publishable(slot_path, "composition supervisor admission")
    slot = _supervisor_slot_payload(
        packet=packet, packet_sha256=expected_packet_sha256,
        receipt_sha256=expected_receipt_sha256,
        controller_review_record=review_record,
        capacity_result_sha256=expected_capacity_result_sha256,
        capacity_review_record=capacity_review_record)
    publish_exclusive(slot_path, slot)
    slot_sha256 = sha256_file(slot_path)
    commands = [_child_command(
        index=index, packet=packet,
        packet_sha256=expected_packet_sha256,
        controller_review_record=review_record,
        receipt_path=receipt_path,
        receipt_sha256=expected_receipt_sha256,
        capacity_result_path=capacity_result_path,
        capacity_result_sha256=expected_capacity_result_sha256,
        capacity_review_record=capacity_review_record,
        supervisor_slot_sha256=slot_sha256)
        for index in range(CTRL.SHARD_COUNT)]
    handles = []
    processes: list[subprocess.Popen] = []
    started = time.monotonic()
    try:
        with SupervisorSignalOwner() as owner:
            for command, log_path in zip(commands, log_paths, strict=True):
                log_path.parent.mkdir(parents=True, exist_ok=True)
                handle = log_path.open("xb")
                handles.append(handle)
                with owner.deferred_until_registered():
                    process = subprocess.Popen(
                        command, cwd=REPO, stdout=handle,
                        stderr=subprocess.STDOUT)
                    processes.append(process)
                    owner.register(process)
            deadline = (started + float(capacity["screen_max_shard_seconds"])
                        + 120.0)
            next_heartbeat = started
            while True:
                codes = [process.poll() for process in processes]
                if any(code not in {None, 0} for code in codes):
                    raise CompositionRuntimeRefused(
                        f"composition supervisor child failure: {codes}")
                if all(code == 0 for code in codes):
                    break
                now = time.monotonic()
                if now >= deadline:
                    raise CompositionRuntimeRefused(
                        "composition supervisor exceeded reviewed shard timeout")
                if now >= next_heartbeat:
                    complete = sum(code == 0 for code in codes)
                    child_progress = [value for value in (
                        _latest_shard_progress(index, path)
                        for index, path in enumerate(log_paths))
                        if value is not None]
                    print(json.dumps({
                        "event": "stage-c-composition-screen-progress-v1",
                        "shards_complete": complete,
                        "shards_total": CTRL.SHARD_COUNT,
                        "progress": child_progress,
                    }, sort_keys=True), flush=True)
                    next_heartbeat = (
                        now + CTRL.SUPERVISOR_HEARTBEAT_SECONDS)
                time.sleep(0.25)
    except BaseException:
        _terminate_children(processes)
        raise
    finally:
        for handle in handles:
            handle.close()
    elapsed = round(time.monotonic() - started, 6)
    shard_manifest = []
    for index, path in enumerate(output_paths):
        if not is_regular_unlinked(path):
            raise CompositionRuntimeRefused(
                f"composition supervisor shard {index} unavailable")
        shard = load_json(path)
        validate_shard(
            shard, packet=packet, packet_sha256=expected_packet_sha256,
            receipt_sha256=expected_receipt_sha256,
            review_record=review_record, index=index,
            supervisor_slot_sha256=slot_sha256)
        shard_manifest.append({
            "index": index,
            "logical_path": CTRL.SHARD_PATHS[index],
            "external_sha256": sha256_file(path),
            "internal_sha256": shard["shard_sha256"],
            "log_logical_path": CTRL.SHARD_LOG_PATHS[index],
            "log_sha256": sha256_file(log_paths[index]),
            "exit_code": 0,
        })
    payload = {
        "schema": SUPERVISOR_FINAL_SCHEMA,
        "run_id": CTRL.RUN_ID,
        "git": packet["producer"]["git"],
        "controller_packet_sha256": expected_packet_sha256,
        "controller_review_record_sha256": sha256_file(review_record),
        "screen_receipt_sha256": expected_receipt_sha256,
        "capacity_result_sha256": expected_capacity_result_sha256,
        "capacity_review_record_sha256": sha256_file(
            capacity_review_record),
        "supervisor_admission_slot": CTRL.SUPERVISOR_ADMISSION_PATH,
        "supervisor_admission_slot_sha256": slot_sha256,
        "commands": commands,
        "shards": shard_manifest,
        "shard_manifest_sha256": manifest_hash(shard_manifest),
        "elapsed_seconds": elapsed,
        "all_children_exit_zero": True,
        "outcomes_published": False,
        "statistics_published": False,
        "aggregate_execution_authorized": False,
        "confirmation_launch_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
        "retry_or_extension_authorized": False,
    }
    payload["final_sha256"] = self_hash(payload, "final_sha256")
    final_packet, _ = _packet(packet_path, expected_packet_sha256)
    _receipt(
        receipt_path, expected_receipt_sha256, final_packet,
        expected_packet_sha256, review_record, capacity_result_path,
        expected_capacity_result_sha256, capacity_review_record)
    _validate_supervisor_slot(
        path=slot_path, expected_sha256=slot_sha256,
        packet=final_packet, packet_sha256=expected_packet_sha256,
        receipt_sha256=expected_receipt_sha256,
        controller_review_record=review_record,
        capacity_result_sha256=expected_capacity_result_sha256,
        capacity_review_record=capacity_review_record)
    for item, shard_path, log_path in zip(
            shard_manifest, output_paths, log_paths, strict=True):
        if (sha256_file(shard_path) != item["external_sha256"]
                or sha256_file(log_path) != item["log_sha256"]):
            raise CompositionRuntimeRefused(
                "composition supervisor child artifact changed before seal")
    publish_exclusive(out, payload)
    return payload


def _supervisor_final(
    *, path: Path, expected_sha256: str,
    packet: Mapping[str, object], packet_sha256: str,
    receipt_sha256: str, controller_review_record: Path,
    capacity_result: Mapping[str, object], capacity_result_sha256: str,
    capacity_review_record: Path,
) -> dict:
    """Reopen the outcome-free terminal seal without opening shard bytes."""
    if (path.resolve() != _expected_supervisor_final_path()
            or not is_regular_unlinked(path)
            or sha256_file(path) != expected_sha256):
        raise CompositionRuntimeRefused(
            "composition supervisor final path/SHA drift")
    value = load_json(path)
    expected_keys = {
        "schema", "run_id", "git", "controller_packet_sha256",
        "controller_review_record_sha256", "screen_receipt_sha256",
        "capacity_result_sha256", "capacity_review_record_sha256",
        "supervisor_admission_slot",
        "supervisor_admission_slot_sha256", "commands", "shards",
        "shard_manifest_sha256", "elapsed_seconds",
        "all_children_exit_zero", "outcomes_published",
        "statistics_published", "aggregate_execution_authorized",
        "confirmation_launch_authorized", "strength_claim",
        "production_promotion", "production_deployment",
        "retry_or_extension_authorized", "final_sha256",
    }
    elapsed = value.get("elapsed_seconds")
    shards = value.get("shards")
    if (set(value) != expected_keys
            or value.get("schema") != SUPERVISOR_FINAL_SCHEMA
            or value.get("run_id") != CTRL.RUN_ID
            or value.get("git") != packet["producer"]["git"]
            or value.get("controller_packet_sha256") != packet_sha256
            or value.get("controller_review_record_sha256")
            != sha256_file(controller_review_record)
            or value.get("screen_receipt_sha256") != receipt_sha256
            or value.get("capacity_result_sha256")
            != capacity_result_sha256
            or value.get("capacity_review_record_sha256")
            != sha256_file(capacity_review_record)
            or value.get("supervisor_admission_slot")
            != CTRL.SUPERVISOR_ADMISSION_PATH
            or not CTRL.is_sha256(value.get(
                "supervisor_admission_slot_sha256"))
            or isinstance(elapsed, bool)
            or not isinstance(elapsed, (int, float))
            or not math.isfinite(float(elapsed))
            or float(elapsed) <= 0
            or float(elapsed) > (
                float(capacity_result["screen_max_shard_seconds"]) + 120.0)
            or value.get("all_children_exit_zero") is not True
            or value.get("outcomes_published") is not False
            or value.get("statistics_published") is not False
            or value.get("aggregate_execution_authorized") is not False
            or value.get("confirmation_launch_authorized") is not False
            or value.get("strength_claim") is not False
            or value.get("production_promotion") is not False
            or value.get("production_deployment") is not False
            or value.get("retry_or_extension_authorized") is not False
            or value.get("final_sha256")
            != self_hash(value, "final_sha256")
            or not isinstance(shards, list)
            or len(shards) != CTRL.SHARD_COUNT
            or value.get("shard_manifest_sha256")
            != manifest_hash(shards)):
        raise CompositionRuntimeRefused(
            "composition supervisor final identity/authority drift")
    slot_sha256 = str(value["supervisor_admission_slot_sha256"])
    expected_commands = [_child_command(
        index=index, packet=packet, packet_sha256=packet_sha256,
        controller_review_record=controller_review_record,
        receipt_path=_expected_receipt_path(), receipt_sha256=receipt_sha256,
        capacity_result_path=_expected_capacity_result_path(),
        capacity_result_sha256=capacity_result_sha256,
        capacity_review_record=capacity_review_record,
        supervisor_slot_sha256=slot_sha256)
        for index in range(CTRL.SHARD_COUNT)]
    if value.get("commands") != expected_commands:
        raise CompositionRuntimeRefused(
            "composition supervisor child command population drift")
    manifest_keys = {
        "index", "logical_path", "external_sha256", "internal_sha256",
        "log_logical_path", "log_sha256", "exit_code",
    }
    for index, item in enumerate(shards):
        if (not isinstance(item, dict) or set(item) != manifest_keys
                or item.get("index") != index
                or item.get("logical_path") != CTRL.SHARD_PATHS[index]
                or not CTRL.is_sha256(item.get("external_sha256"))
                or not CTRL.is_sha256(item.get("internal_sha256"))
                or item.get("log_logical_path")
                != CTRL.SHARD_LOG_PATHS[index]
                or not CTRL.is_sha256(item.get("log_sha256"))
                or item.get("exit_code") != 0):
            raise CompositionRuntimeRefused(
                f"composition supervisor shard manifest {index} drift")
        # Presence/type is score-free. Shard and log bytes remain unopened
        # until the aggregate admission is durably consumed.
        if (not is_regular_unlinked(_expected_shard_path(index))
                or not is_regular_unlinked(
                    (REPO / CTRL.SHARD_LOG_PATHS[index]).resolve())):
            raise CompositionRuntimeRefused(
                f"composition supervisor sealed artifact {index} unavailable")
    _validate_supervisor_slot(
        path=(REPO / CTRL.SUPERVISOR_ADMISSION_PATH).resolve(),
        expected_sha256=slot_sha256,
        packet=packet, packet_sha256=packet_sha256,
        receipt_sha256=receipt_sha256,
        controller_review_record=controller_review_record,
        capacity_result_sha256=capacity_result_sha256,
        capacity_review_record=capacity_review_record)
    return value


def _shard_seed0(index: int) -> int:
    return CTRL.SCREEN_SEED0 + index * CTRL.CLUSTERS_PER_SHARD


def _attempt_slot_payload(
    *, packet: Mapping[str, object], packet_sha256: str,
    receipt_sha256: str, review_record: Path, kind: str,
    index: int | None = None,
) -> dict:
    if kind not in {"shard", "aggregate"}:
        raise CompositionRuntimeRefused(
            "composition attempt-slot kind drift")
    if ((kind == "shard")
            != (isinstance(index, int) and not isinstance(index, bool)
                and 0 <= index < CTRL.SHARD_COUNT)):
        raise CompositionRuntimeRefused(
            "composition attempt-slot index drift")
    value = {
        "schema": "teacher-stage-c-composition-attempt-admission-v1",
        "run_id": CTRL.RUN_ID,
        "git": packet["producer"]["git"],
        "controller_packet_sha256": packet_sha256,
        "screen_receipt_sha256": receipt_sha256,
        "controller_review_record_sha256": sha256_file(review_record),
        "kind": kind,
        "shard_index": index,
        "consumed_before_outcome_access": True,
        "retry_after_failure_authorized": False,
    }
    value["slot_sha256"] = self_hash(value, "slot_sha256")
    return value


def _consume_attempt_slot(
    *, packet: Mapping[str, object], packet_sha256: str,
    receipt_sha256: str, review_record: Path, kind: str,
    index: int | None = None,
) -> tuple[str, str]:
    logical = (CTRL.SHARD_ADMISSION_PATHS[index]
               if kind == "shard" and index is not None
               else CTRL.AGGREGATE_ADMISSION_PATH)
    path = (REPO / logical).resolve()
    value = _attempt_slot_payload(
        packet=packet, packet_sha256=packet_sha256,
        receipt_sha256=receipt_sha256, review_record=review_record,
        kind=kind, index=index)
    publish_exclusive(path, value)
    return logical, sha256_file(path)


def _validate_attempt_slot(
    *, logical: str, expected_sha256: str,
    packet: Mapping[str, object], packet_sha256: str,
    receipt_sha256: str, review_record: Path, kind: str,
    index: int | None = None,
) -> None:
    expected_logical = (CTRL.SHARD_ADMISSION_PATHS[index]
                        if kind == "shard" and index is not None
                        else CTRL.AGGREGATE_ADMISSION_PATH)
    path = (REPO / logical).resolve()
    expected = _attempt_slot_payload(
        packet=packet, packet_sha256=packet_sha256,
        receipt_sha256=receipt_sha256, review_record=review_record,
        kind=kind, index=index)
    if (logical != expected_logical
            or not is_regular_unlinked(path)
            or sha256_file(path) != expected_sha256
            or load_json(path) != expected):
        raise CompositionRuntimeRefused(
            "composition attempt admission drift")


def run_shard(*, packet_path: Path, expected_packet_sha256: str,
              review_record: Path, receipt_path: Path,
              expected_receipt_sha256: str,
              capacity_result_path: Path,
              expected_capacity_result_sha256: str,
              capacity_review_record: Path,
              supervisor_admission_path: Path,
              expected_supervisor_admission_sha256: str,
              shard_index: int, out: Path) -> dict:
    if (isinstance(shard_index, bool) or not isinstance(shard_index, int)
            or not 0 <= shard_index < CTRL.SHARD_COUNT
            or out.resolve() != _expected_shard_path(shard_index)):
        raise CompositionRuntimeRefused(
            "composition screen shard identity/path drift")
    require_publishable(out, "composition screen shard output")
    packet, ensemble = _packet(packet_path, expected_packet_sha256)
    _, capacity = _receipt(
        receipt_path, expected_receipt_sha256, packet,
        expected_packet_sha256, review_record, capacity_result_path,
        expected_capacity_result_sha256, capacity_review_record)
    _validate_supervisor_slot(
        path=supervisor_admission_path,
        expected_sha256=expected_supervisor_admission_sha256,
        packet=packet, packet_sha256=expected_packet_sha256,
        receipt_sha256=expected_receipt_sha256,
        controller_review_record=review_record,
        capacity_result_sha256=expected_capacity_result_sha256,
        capacity_review_record=capacity_review_record)
    attempt_slot, attempt_slot_sha256 = _consume_attempt_slot(
        packet=packet, packet_sha256=expected_packet_sha256,
        receipt_sha256=expected_receipt_sha256,
        review_record=review_record, kind="shard", index=shard_index)
    treatment, matched_null, champion = _factories(packet, ensemble)
    seed0 = _shard_seed0(shard_index)
    deadline = time.monotonic() + float(
        capacity["screen_max_shard_seconds"])
    records = {
        "treatment": SCREEN.run_arm_factories(
            "treatment", treatment, champion,
            clusters=CTRL.CLUSTERS_PER_SHARD, seed0=seed0,
            run_id=CTRL.RUN_ID, policy_has_stage_c=True,
            deadline_monotonic=deadline),
        "matched_null": SCREEN.run_arm_factories(
            "matched_null", matched_null, champion,
            clusters=CTRL.CLUSTERS_PER_SHARD, seed0=seed0,
            run_id=CTRL.RUN_ID, policy_has_stage_c=True,
            deadline_monotonic=deadline),
        "champion": SCREEN.run_arm_factories(
            "champion", champion, champion,
            clusters=CTRL.CLUSTERS_PER_SHARD, seed0=seed0,
            run_id=CTRL.RUN_ID, policy_has_stage_c=False,
            deadline_monotonic=deadline),
    }
    # This call is a structural/work validator. Its shard-level statistical
    # status is deliberately not published or used for stopping.
    SCREEN.aggregate_screen(
        records, expected_seed0=seed0,
        expected_clusters=CTRL.CLUSTERS_PER_SHARD,
        expected_surface=str(packet["selected_capability"]["surface"]))
    payload = {
        "schema": SHARD_SCHEMA,
        "run_id": CTRL.RUN_ID,
        "git": packet["producer"]["git"],
        "controller_packet_sha256": expected_packet_sha256,
        "screen_receipt_sha256": expected_receipt_sha256,
        "supervisor_admission_slot": CTRL.SUPERVISOR_ADMISSION_PATH,
        "supervisor_admission_slot_sha256":
            expected_supervisor_admission_sha256,
        "attempt_admission_slot": attempt_slot,
        "attempt_admission_slot_sha256": attempt_slot_sha256,
        "shard_index": shard_index,
        "seed0": seed0,
        "clusters": CTRL.CLUSTERS_PER_SHARD,
        "records": records,
        "record_counts": {
            label: len(records[label]) for label in SCREEN.LABELS},
        "complete": True,
        "strength_claim": False,
        "confirmation_launch_authorized": False,
        "production_promotion": False,
        "production_deployment": False,
        "retry_or_extension_authorized": False,
    }
    payload["shard_sha256"] = self_hash(payload, "shard_sha256")
    # Close mutable identities after expensive gameplay and before publish.
    final_packet, _ = _packet(packet_path, expected_packet_sha256)
    _receipt(
        receipt_path, expected_receipt_sha256, final_packet,
        expected_packet_sha256, review_record, capacity_result_path,
        expected_capacity_result_sha256, capacity_review_record)
    _validate_supervisor_slot(
        path=supervisor_admission_path,
        expected_sha256=expected_supervisor_admission_sha256,
        packet=final_packet, packet_sha256=expected_packet_sha256,
        receipt_sha256=expected_receipt_sha256,
        controller_review_record=review_record,
        capacity_result_sha256=expected_capacity_result_sha256,
        capacity_review_record=capacity_review_record)
    _validate_attempt_slot(
        logical=attempt_slot, expected_sha256=attempt_slot_sha256,
        packet=final_packet, packet_sha256=expected_packet_sha256,
        receipt_sha256=expected_receipt_sha256,
        review_record=review_record, kind="shard", index=shard_index)
    publish_exclusive(out, payload)
    return payload


def validate_shard(shard: Mapping[str, object], *, packet: Mapping[str, object],
                   packet_sha256: str, receipt_sha256: str,
                   review_record: Path, index: int,
                   supervisor_slot_sha256: str) -> None:
    records = shard.get("records")
    seed0 = _shard_seed0(index)
    if (shard.get("schema") != SHARD_SCHEMA
            or shard.get("run_id") != CTRL.RUN_ID
            or shard.get("git") != packet["producer"]["git"]
            or shard.get("controller_packet_sha256") != packet_sha256
            or shard.get("screen_receipt_sha256") != receipt_sha256
            or shard.get("supervisor_admission_slot")
            != CTRL.SUPERVISOR_ADMISSION_PATH
            or shard.get("supervisor_admission_slot_sha256")
            != supervisor_slot_sha256
            or not CTRL.is_sha256(supervisor_slot_sha256)
            or shard.get("attempt_admission_slot")
            != CTRL.SHARD_ADMISSION_PATHS[index]
            or not CTRL.is_sha256(shard.get(
                "attempt_admission_slot_sha256"))
            or shard.get("shard_index") != index
            or shard.get("seed0") != seed0
            or shard.get("clusters") != CTRL.CLUSTERS_PER_SHARD
            or not isinstance(records, dict)
            or set(records) != set(SCREEN.LABELS)
            or any(row.get("run") != CTRL.RUN_ID
                   for label in SCREEN.LABELS
                   for row in records.get(label, [])
                   if isinstance(row, dict))
            or shard.get("record_counts") != {
                label: 2 * CTRL.CLUSTERS_PER_SHARD
                for label in SCREEN.LABELS}
            or shard.get("complete") is not True
            or shard.get("strength_claim") is not False
            or shard.get("confirmation_launch_authorized") is not False
            or shard.get("production_promotion") is not False
            or shard.get("production_deployment") is not False
            or shard.get("retry_or_extension_authorized") is not False
            or shard.get("shard_sha256")
            != self_hash(shard, "shard_sha256")):
        raise CompositionRuntimeRefused(
            f"composition screen shard {index} identity drift")
    try:
        SCREEN.aggregate_screen(
            records, expected_seed0=seed0,
            expected_clusters=CTRL.CLUSTERS_PER_SHARD,
            expected_surface=str(packet["selected_capability"]["surface"]))
    except SCREEN.StageCScreenError as exc:
        raise CompositionRuntimeRefused(str(exc)) from exc
    _validate_attempt_slot(
        logical=str(shard["attempt_admission_slot"]),
        expected_sha256=str(shard["attempt_admission_slot_sha256"]),
        packet=packet, packet_sha256=packet_sha256,
        receipt_sha256=receipt_sha256, review_record=review_record,
        kind="shard", index=index)


def aggregate(*, packet_path: Path, expected_packet_sha256: str,
              review_record: Path, receipt_path: Path,
              expected_receipt_sha256: str,
              capacity_result_path: Path,
              expected_capacity_result_sha256: str,
              capacity_review_record: Path,
              supervisor_final_path: Path,
              expected_supervisor_final_sha256: str,
              supervisor_review_record: Path,
              shard_paths: Sequence[Path], out: Path) -> dict:
    if (out.resolve() != _expected_aggregate_path()
            or len(shard_paths) != CTRL.SHARD_COUNT
            or [path.resolve() for path in shard_paths]
            != [_expected_shard_path(index)
                for index in range(CTRL.SHARD_COUNT)]):
        raise CompositionRuntimeRefused(
            "composition aggregate output/shard path drift")
    require_publishable(out, "composition screen aggregate output")
    # File-presence metadata is score-free. Check it before consuming the
    # aggregate's one-shot slot so an obviously incomplete shard population
    # cannot strand the only aggregation attempt; bytes remain sealed until
    # after the slot is durable.
    if any(not is_regular_unlinked(path) for path in shard_paths):
        raise CompositionRuntimeRefused(
            "composition aggregate shard population is incomplete")
    packet, _ensemble = _packet(packet_path, expected_packet_sha256)
    _receipt(
        receipt_path, expected_receipt_sha256, packet,
        expected_packet_sha256, review_record, capacity_result_path,
        expected_capacity_result_sha256, capacity_review_record)
    capacity = _capacity_result(
        capacity_result_path, expected_capacity_result_sha256,
        packet, expected_packet_sha256, review_record)
    supervisor_final = _supervisor_final(
        path=supervisor_final_path,
        expected_sha256=expected_supervisor_final_sha256,
        packet=packet, packet_sha256=expected_packet_sha256,
        receipt_sha256=expected_receipt_sha256,
        controller_review_record=review_record,
        capacity_result=capacity,
        capacity_result_sha256=expected_capacity_result_sha256,
        capacity_review_record=capacity_review_record)
    supervisor_claim = _supervisor_review_claim(
        supervisor_review_record, packet, expected_packet_sha256,
        supervisor_final, expected_supervisor_final_sha256)
    aggregate_slot, aggregate_slot_sha256 = _consume_attempt_slot(
        packet=packet, packet_sha256=expected_packet_sha256,
        receipt_sha256=expected_receipt_sha256,
        review_record=review_record, kind="aggregate")
    merged = {label: [] for label in SCREEN.LABELS}
    shard_manifest = []
    opened_shards = []
    sealed_manifest = supervisor_final["shards"]
    for index, path in enumerate(shard_paths):
        sealed = sealed_manifest[index]
        log_path = (REPO / CTRL.SHARD_LOG_PATHS[index]).resolve()
        if (sha256_file(path) != sealed["external_sha256"]
                or sha256_file(log_path) != sealed["log_sha256"]):
            raise CompositionRuntimeRefused(
                f"composition supervisor seal mismatch for shard {index}")
        shard = load_json(path)
        opened_shards.append(shard)
        validate_shard(
            shard, packet=packet, packet_sha256=expected_packet_sha256,
            receipt_sha256=expected_receipt_sha256,
            review_record=review_record, index=index,
            supervisor_slot_sha256=str(supervisor_final[
                "supervisor_admission_slot_sha256"]))
        if shard["shard_sha256"] != sealed["internal_sha256"]:
            raise CompositionRuntimeRefused(
                f"composition supervisor internal seal mismatch for shard {index}")
        for label in SCREEN.LABELS:
            merged[label].extend(shard["records"][label])
        shard_manifest.append({
            "index": index,
            "logical_path": CTRL.SHARD_PATHS[index],
            "external_sha256": sha256_file(path),
            "internal_sha256": shard["shard_sha256"],
        })
    try:
        result = SCREEN.aggregate_screen(
            merged, expected_seed0=CTRL.SCREEN_SEED0,
            expected_clusters=CTRL.SCREEN_CLUSTERS,
            expected_surface=str(packet["selected_capability"]["surface"]))
    except SCREEN.StageCScreenError as exc:
        raise CompositionRuntimeRefused(str(exc)) from exc
    payload = {
        "schema": AGGREGATE_SCHEMA,
        "run_id": CTRL.RUN_ID,
        "git": packet["producer"]["git"],
        "controller_packet_sha256": expected_packet_sha256,
        "screen_receipt_sha256": expected_receipt_sha256,
        "supervisor_final_sha256": expected_supervisor_final_sha256,
        "supervisor_final_internal_sha256": supervisor_final[
            "final_sha256"],
        "supervisor_review_record_sha256": sha256_file(
            supervisor_review_record),
        "supervisor_review_claim": supervisor_claim,
        "aggregate_admission_slot": aggregate_slot,
        "aggregate_admission_slot_sha256": aggregate_slot_sha256,
        "selected_capability": packet["selected_capability"],
        "model_exports_sha256": packet["model_exports_sha256"],
        "shards": shard_manifest,
        "screen": result,
        "decision": result["status"],
        "confirmation_packet_review_authorized": (
            result["status"] == "AUTHORIZE_CONFIRM_PACKET_REVIEW"),
        "strength_claim": False,
        "confirmation_launch_authorized": False,
        "production_promotion": False,
        "production_deployment": False,
        "retry_or_extension_authorized": False,
    }
    payload["result_sha256"] = self_hash(payload, "result_sha256")
    # Final TOCTOU close after all gameplay records have been opened.
    final_packet, _ = _packet(packet_path, expected_packet_sha256)
    _receipt(
        receipt_path, expected_receipt_sha256, final_packet,
        expected_packet_sha256, review_record, capacity_result_path,
        expected_capacity_result_sha256, capacity_review_record)
    final_capacity = _capacity_result(
        capacity_result_path, expected_capacity_result_sha256,
        final_packet, expected_packet_sha256, review_record)
    final_supervisor = _supervisor_final(
        path=supervisor_final_path,
        expected_sha256=expected_supervisor_final_sha256,
        packet=final_packet, packet_sha256=expected_packet_sha256,
        receipt_sha256=expected_receipt_sha256,
        controller_review_record=review_record,
        capacity_result=final_capacity,
        capacity_result_sha256=expected_capacity_result_sha256,
        capacity_review_record=capacity_review_record)
    _supervisor_review_claim(
        supervisor_review_record, final_packet,
        expected_packet_sha256, final_supervisor,
        expected_supervisor_final_sha256)
    for index, (item, path, shard) in enumerate(zip(
            shard_manifest, shard_paths, opened_shards, strict=True)):
        sealed = final_supervisor["shards"][index]
        log_path = (REPO / CTRL.SHARD_LOG_PATHS[index]).resolve()
        if (sha256_file(path) != item["external_sha256"]
                or item["external_sha256"] != sealed["external_sha256"]
                or shard["shard_sha256"] != sealed["internal_sha256"]
                or sha256_file(log_path) != sealed["log_sha256"]):
            raise CompositionRuntimeRefused(
                "composition sealed shard changed during aggregation")
        _validate_attempt_slot(
            logical=str(shard["attempt_admission_slot"]),
            expected_sha256=str(shard["attempt_admission_slot_sha256"]),
            packet=final_packet, packet_sha256=expected_packet_sha256,
            receipt_sha256=expected_receipt_sha256,
            review_record=review_record, kind="shard", index=index)
    _validate_attempt_slot(
        logical=aggregate_slot, expected_sha256=aggregate_slot_sha256,
        packet=final_packet, packet_sha256=expected_packet_sha256,
        receipt_sha256=expected_receipt_sha256,
        review_record=review_record, kind="aggregate")
    publish_exclusive(out, payload)
    return payload


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    for name in (
            "capacity-preflight", "admit", "supervise", "run-shard",
            "aggregate"):
        child = commands.add_parser(name)
        child.add_argument("--expected-git", required=True)
        child.add_argument("--controller-packet", required=True)
        child.add_argument("--expected-controller-packet-sha256", required=True)
        child.add_argument("--controller-review-record", required=True)
        child.add_argument("--out", required=True)
        if name in {"admit", "supervise", "run-shard", "aggregate"}:
            child.add_argument("--capacity-result", required=True)
            child.add_argument(
                "--expected-capacity-result-sha256", required=True)
            child.add_argument("--capacity-review-record", required=True)
        if name in {"supervise", "run-shard", "aggregate"}:
            child.add_argument("--screen-receipt", required=True)
            child.add_argument(
                "--expected-screen-receipt-sha256", required=True)
        if name == "run-shard":
            child.add_argument("--supervisor-admission", required=True)
            child.add_argument(
                "--expected-supervisor-admission-sha256", required=True)
            child.add_argument("--shard-index", required=True, type=int)
        if name == "aggregate":
            child.add_argument("--supervisor-final", required=True)
            child.add_argument(
                "--expected-supervisor-final-sha256", required=True)
            child.add_argument("--supervisor-review-record", required=True)
            child.add_argument("--shards", nargs="+", required=True)
    return root


def main() -> int:
    args = parser().parse_args()
    if _git("rev-parse", "HEAD") != args.expected_git:
        raise CompositionRuntimeRefused(
            "composition screen expected Git drift")
    common = {
        "packet_path": Path(args.controller_packet).resolve(),
        "expected_packet_sha256": args.expected_controller_packet_sha256,
        "review_record": Path(args.controller_review_record).resolve(),
    }
    if args.command == "capacity-preflight":
        value = capacity_preflight(**common, out=Path(args.out).resolve())
        capacity_common = None
    else:
        capacity_common = {
            "capacity_result_path": Path(args.capacity_result).resolve(),
            "expected_capacity_result_sha256":
                args.expected_capacity_result_sha256,
            "capacity_review_record": Path(
                args.capacity_review_record).resolve(),
        }
    if args.command == "admit":
        value = admit(
            **common, **capacity_common, out=Path(args.out).resolve())
    elif args.command == "supervise":
        value = supervise(
            **common, **capacity_common,
            receipt_path=Path(args.screen_receipt).resolve(),
            expected_receipt_sha256=args.expected_screen_receipt_sha256,
            out=Path(args.out).resolve())
    elif args.command == "run-shard":
        value = run_shard(
            **common, **capacity_common,
            receipt_path=Path(args.screen_receipt).resolve(),
            expected_receipt_sha256=args.expected_screen_receipt_sha256,
            supervisor_admission_path=Path(
                args.supervisor_admission).resolve(),
            expected_supervisor_admission_sha256=
                args.expected_supervisor_admission_sha256,
            shard_index=args.shard_index, out=Path(args.out).resolve())
    elif args.command == "aggregate":
        value = aggregate(
            **common, **capacity_common,
            receipt_path=Path(args.screen_receipt).resolve(),
            expected_receipt_sha256=args.expected_screen_receipt_sha256,
            supervisor_final_path=Path(args.supervisor_final).resolve(),
            expected_supervisor_final_sha256=
                args.expected_supervisor_final_sha256,
            supervisor_review_record=Path(
                args.supervisor_review_record).resolve(),
            shard_paths=[Path(value).resolve() for value in args.shards],
            out=Path(args.out).resolve())
    print(json.dumps({
        "status": value.get("decision", "COMPLETE"),
        "sha256": CTRL.sha256_bytes(canonical_json(value)),
        "strength_claim": False,
        "confirmation_launch_authorized": False,
        "production_promotion": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except CompositionSupervisorInterrupted as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        raise SystemExit(128 + exc.signum) from exc
    except (CompositionRuntimeRefused, SCREEN.StageCScreenError,
            COMPOSITION.StageCCompositionError,
            NPNET.StageCNumpyError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        raise SystemExit(2)
