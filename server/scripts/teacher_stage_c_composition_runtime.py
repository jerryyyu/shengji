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

import teacher_stage_c_composition_controller as CTRL  # noqa: E402
from shengji.ai.registry import make_bot  # noqa: E402
from shengji.rl import stage_c_candidates as CANDIDATES  # noqa: E402
from shengji.rl import stage_c_composition as COMPOSITION  # noqa: E402
from shengji.rl import stage_c_model as MODEL  # noqa: E402
from shengji.rl import stage_c_npnet as NPNET  # noqa: E402
from shengji.rl import stage_c_screen as SCREEN  # noqa: E402
from shengji.rl.torch_policy import _load_npnet  # noqa: E402


ADMISSION_SCHEMA = "teacher-stage-c-composition-screen-admission-v1"
RECEIPT_SCHEMA = "teacher-stage-c-composition-screen-receipt-v1"
SHARD_SCHEMA = "teacher-stage-c-composition-screen-shard-v1"
AGGREGATE_SCHEMA = "teacher-stage-c-composition-screen-result-v1"


class CompositionRuntimeRefused(RuntimeError):
    """The reviewed packet, evidence population, or work contract drifted."""


canonical_json = CTRL.canonical_json
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


def _expected_shard_path(index: int) -> Path:
    return (REPO / CTRL.SHARD_PATHS[index]).resolve()


def _expected_aggregate_path() -> Path:
    return (REPO / CTRL.RESULT_PATH).resolve()


def _artifact(ref: Mapping[str, object], label: str) -> tuple[Path, dict]:
    path = (REPO / str(ref.get("logical_path"))).resolve()
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
                "screen_packet_review_authorized": True,
                "screen_launch_authorized": False,
                "confirmation_launch_authorized": False,
                "strength_claim": False,
                "production_promotion": False,
                "production_deployment": False,
            }
            or packet.get("candidate_contract")
            != CTRL.candidate_contract()
            or packet.get("screen_contract") != CTRL.screen_contract()
            or packet.get("commands") != CTRL._commands()
            or packet.get("result_contract") != CTRL.result_contract()):
        raise CompositionRuntimeRefused(
            "composition controller packet identity/authority drift")

    parents = packet.get("parents", {})
    report_packet_ref = parents.get("report_packet", {})
    report_review_ref = parents.get("report_review_record", {})
    report_receipt_ref = parents.get("report_receipt", {})
    report_result_ref = parents.get("report_result", {})
    try:
        report_packet_path, _ = _artifact(
            report_packet_ref, "composition REPORT packet")
        report_review_path = (REPO / str(
            report_review_ref.get("logical_path"))).resolve()
        if (not is_regular_unlinked(report_review_path)
                or sha256_file(report_review_path)
                != report_review_ref.get("external_sha256")):
            raise CompositionRuntimeRefused(
                "composition REPORT review path/SHA drift")
        report_receipt_path, _ = _artifact(
            report_receipt_ref, "composition REPORT receipt")
        report_result_path, _ = _artifact(
            report_result_ref, "composition REPORT result")
        report_packet, report_result = CTRL.validate_report_result(
            report_packet_path=report_packet_path,
            report_packet_sha256=str(
                report_packet_ref["external_sha256"]),
            report_review_record=report_review_path,
            report_receipt_path=report_receipt_path,
            report_receipt_sha256=str(
                report_receipt_ref["external_sha256"]),
            report_result_path=report_result_path,
            report_result_sha256=str(
                report_result_ref["external_sha256"]))
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

    v11 = parents.get("v11pair", {})
    v11_path = (REPO / str(v11.get("logical_path"))).resolve()
    if (v11 != {
            "logical_path": CTRL.V11_PATH,
            "external_sha256": CTRL.CAPTURE_RUNTIME.V11_SHA256,
            }
            or not is_regular_unlinked(v11_path)
            or sha256_file(v11_path) != v11.get("external_sha256")):
        raise CompositionRuntimeRefused("composition V11 proposal input drift")
    if packet["selected_capability"]["surface"] == "play":
        try:
            _load_npnet(str(v11_path))
        except Exception as exc:
            raise CompositionRuntimeRefused(
                f"composition V11 proposal model cannot load: {exc}") from exc
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


def _slot_payload(packet: Mapping[str, object], packet_sha256: str,
                  review_record: Path) -> dict:
    value = {
        "schema": ADMISSION_SCHEMA,
        "run_id": CTRL.RUN_ID,
        "git": packet["producer"]["git"],
        "controller_packet_sha256": packet_sha256,
        "controller_review_record_sha256": sha256_file(review_record),
        "selected_capability": packet["selected_capability"],
        "model_exports_sha256": packet["model_exports_sha256"],
        "receipt_path": CTRL.RECEIPT_PATH,
        "consumed_before_receipt": True,
        "retry_or_extension_authorized": False,
    }
    value["slot_sha256"] = self_hash(value, "slot_sha256")
    return value


def admit(*, packet_path: Path, expected_packet_sha256: str,
          review_record: Path, out: Path) -> dict:
    packet, _ensemble = _packet(packet_path, expected_packet_sha256)
    claim = _review_claim(review_record, packet, expected_packet_sha256)
    if out.resolve() != _expected_receipt_path():
        raise CompositionRuntimeRefused(
            "composition screen receipt path drift")
    require_publishable(out, "composition screen receipt")
    slot_path = (REPO / CTRL.ADMISSION_PATH).resolve()
    slot = _slot_payload(packet, expected_packet_sha256, review_record)
    publish_exclusive(slot_path, slot)
    receipt = {
        "schema": RECEIPT_SCHEMA,
        "run_id": CTRL.RUN_ID,
        "git": packet["producer"]["git"],
        "controller_packet_sha256": expected_packet_sha256,
        "controller_packet_internal_sha256": packet["packet_sha256"],
        "controller_review_record_sha256": sha256_file(review_record),
        "controller_review_claim": claim,
        "admission_slot": CTRL.ADMISSION_PATH,
        "admission_slot_sha256": sha256_file(slot_path),
        "selected_capability": packet["selected_capability"],
        "model_exports_sha256": packet["model_exports_sha256"],
        "screen_execution_authorized": True,
        "confirmation_launch_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
        "retry_or_extension_authorized": False,
    }
    receipt["receipt_sha256"] = self_hash(receipt, "receipt_sha256")
    publish_exclusive(out, receipt)
    return receipt


def _receipt(path: Path, expected_sha256: str,
             packet: Mapping[str, object], packet_sha256: str,
             review_record: Path) -> dict:
    if (path.resolve() != _expected_receipt_path()
            or not is_regular_unlinked(path)
            or sha256_file(path) != expected_sha256):
        raise CompositionRuntimeRefused(
            "composition screen receipt path/SHA drift")
    receipt = load_json(path)
    slot_path = (REPO / CTRL.ADMISSION_PATH).resolve()
    expected_slot = _slot_payload(packet, packet_sha256, review_record)
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
            or receipt.get("admission_slot") != CTRL.ADMISSION_PATH
            or receipt.get("selected_capability")
            != packet["selected_capability"]
            or receipt.get("model_exports_sha256")
            != packet["model_exports_sha256"]
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
    return receipt


def _factories(packet: Mapping[str, object], ensemble):
    surface = str(packet["selected_capability"]["surface"])
    if surface == "play":
        v11 = _load_npnet(str(REPO / CTRL.V11_PATH))
        source = CANDIDATES.make_play_candidate_source(v11)
        make_stage = COMPOSITION.make_play_report_lcb_bot
    elif surface == "bury":
        source = CANDIDATES.make_bury_candidate_source()
        make_stage = COMPOSITION.make_bury_report_lcb_bot
    else:
        raise CompositionRuntimeRefused(
            "composition selected surface drift")

    def treatment(seed: int):
        return make_stage(
            ensemble, source, arm="treatment", seed=seed)

    def matched_null(seed: int):
        return make_stage(
            ensemble, source, arm="matched-null", seed=seed)

    def champion(seed: int):
        return make_bot("mc-s0-report-lcb", seed=seed)

    return treatment, matched_null, champion


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
              expected_receipt_sha256: str, shard_index: int,
              out: Path) -> dict:
    if (isinstance(shard_index, bool) or not isinstance(shard_index, int)
            or not 0 <= shard_index < CTRL.SHARD_COUNT
            or out.resolve() != _expected_shard_path(shard_index)):
        raise CompositionRuntimeRefused(
            "composition screen shard identity/path drift")
    require_publishable(out, "composition screen shard output")
    packet, ensemble = _packet(packet_path, expected_packet_sha256)
    _receipt(receipt_path, expected_receipt_sha256, packet,
             expected_packet_sha256, review_record)
    attempt_slot, attempt_slot_sha256 = _consume_attempt_slot(
        packet=packet, packet_sha256=expected_packet_sha256,
        receipt_sha256=expected_receipt_sha256,
        review_record=review_record, kind="shard", index=shard_index)
    treatment, matched_null, champion = _factories(packet, ensemble)
    seed0 = _shard_seed0(shard_index)
    records = {
        "treatment": SCREEN.run_arm_factories(
            "treatment", treatment, champion,
            clusters=CTRL.CLUSTERS_PER_SHARD, seed0=seed0,
            run_id=CTRL.RUN_ID, policy_has_stage_c=True),
        "matched_null": SCREEN.run_arm_factories(
            "matched_null", matched_null, champion,
            clusters=CTRL.CLUSTERS_PER_SHARD, seed0=seed0,
            run_id=CTRL.RUN_ID, policy_has_stage_c=True),
        "champion": SCREEN.run_arm_factories(
            "champion", champion, champion,
            clusters=CTRL.CLUSTERS_PER_SHARD, seed0=seed0,
            run_id=CTRL.RUN_ID, policy_has_stage_c=False),
    }
    # This call is a structural/work validator. Its shard-level statistical
    # status is deliberately not published or used for stopping.
    SCREEN.aggregate_screen(
        records, expected_seed0=seed0,
        expected_clusters=CTRL.CLUSTERS_PER_SHARD)
    payload = {
        "schema": SHARD_SCHEMA,
        "run_id": CTRL.RUN_ID,
        "git": packet["producer"]["git"],
        "controller_packet_sha256": expected_packet_sha256,
        "screen_receipt_sha256": expected_receipt_sha256,
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
    _receipt(receipt_path, expected_receipt_sha256, final_packet,
             expected_packet_sha256, review_record)
    _validate_attempt_slot(
        logical=attempt_slot, expected_sha256=attempt_slot_sha256,
        packet=final_packet, packet_sha256=expected_packet_sha256,
        receipt_sha256=expected_receipt_sha256,
        review_record=review_record, kind="shard", index=shard_index)
    publish_exclusive(out, payload)
    return payload


def validate_shard(shard: Mapping[str, object], *, packet: Mapping[str, object],
                   packet_sha256: str, receipt_sha256: str,
                   review_record: Path, index: int) -> None:
    records = shard.get("records")
    seed0 = _shard_seed0(index)
    if (shard.get("schema") != SHARD_SCHEMA
            or shard.get("run_id") != CTRL.RUN_ID
            or shard.get("git") != packet["producer"]["git"]
            or shard.get("controller_packet_sha256") != packet_sha256
            or shard.get("screen_receipt_sha256") != receipt_sha256
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
            expected_clusters=CTRL.CLUSTERS_PER_SHARD)
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
    _receipt(receipt_path, expected_receipt_sha256, packet,
             expected_packet_sha256, review_record)
    aggregate_slot, aggregate_slot_sha256 = _consume_attempt_slot(
        packet=packet, packet_sha256=expected_packet_sha256,
        receipt_sha256=expected_receipt_sha256,
        review_record=review_record, kind="aggregate")
    merged = {label: [] for label in SCREEN.LABELS}
    shard_manifest = []
    opened_shards = []
    for index, path in enumerate(shard_paths):
        shard = load_json(path)
        opened_shards.append(shard)
        validate_shard(
            shard, packet=packet, packet_sha256=expected_packet_sha256,
            receipt_sha256=expected_receipt_sha256,
            review_record=review_record, index=index)
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
            expected_clusters=CTRL.SCREEN_CLUSTERS)
    except SCREEN.StageCScreenError as exc:
        raise CompositionRuntimeRefused(str(exc)) from exc
    payload = {
        "schema": AGGREGATE_SCHEMA,
        "run_id": CTRL.RUN_ID,
        "git": packet["producer"]["git"],
        "controller_packet_sha256": expected_packet_sha256,
        "screen_receipt_sha256": expected_receipt_sha256,
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
    _receipt(receipt_path, expected_receipt_sha256, final_packet,
             expected_packet_sha256, review_record)
    for index, (item, path, shard) in enumerate(zip(
            shard_manifest, shard_paths, opened_shards, strict=True)):
        if sha256_file(path) != item["external_sha256"]:
            raise CompositionRuntimeRefused(
                "composition screen shard changed during aggregation")
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
    for name in ("admit", "run-shard", "aggregate"):
        child = commands.add_parser(name)
        child.add_argument("--expected-git", required=True)
        child.add_argument("--controller-packet", required=True)
        child.add_argument("--expected-controller-packet-sha256", required=True)
        child.add_argument("--controller-review-record", required=True)
        child.add_argument("--out", required=True)
        if name != "admit":
            child.add_argument("--screen-receipt", required=True)
            child.add_argument(
                "--expected-screen-receipt-sha256", required=True)
        if name == "run-shard":
            child.add_argument("--shard-index", required=True, type=int)
        if name == "aggregate":
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
    if args.command == "admit":
        value = admit(**common, out=Path(args.out).resolve())
    elif args.command == "run-shard":
        value = run_shard(
            **common, receipt_path=Path(args.screen_receipt).resolve(),
            expected_receipt_sha256=args.expected_screen_receipt_sha256,
            shard_index=args.shard_index, out=Path(args.out).resolve())
    else:
        value = aggregate(
            **common, receipt_path=Path(args.screen_receipt).resolve(),
            expected_receipt_sha256=args.expected_screen_receipt_sha256,
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
    except (CompositionRuntimeRefused, SCREEN.StageCScreenError,
            COMPOSITION.StageCCompositionError,
            NPNET.StageCNumpyError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        raise SystemExit(2)
