"""Bounded, score-free D256 population collection.

This module is intentionally an orchestration boundary.  It owns no engine
logic: one injected driver produces one typed source-attempt value, while the
controller binds that value to the frozen slot and attempt identity, publishes
the immutable material shard, and records the attempt in a separate immutable
ledger.  The ledger makes restart conservative: only a recorded, byte-verified
shard can be reused.
"""

from __future__ import annotations

import base64
from contextlib import ExitStack
import hashlib
import json
import threading
import time
from collections import Counter
from concurrent.futures import (
    Future, ProcessPoolExecutor, ThreadPoolExecutor, as_completed,
)
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .belief_artifacts import publish_exclusive_bytes, stable_read_bytes
from .belief_contract import canonical_json_bytes
from .world_afterstate_v2_population_artifacts import (
    PopulationMaterialShardV2, WorldAfterstateV2PopulationArtifactError,
    material_sha256, population_material_bytes, population_material_path,
    publish_population_manifest, publish_population_material,
    reopen_population_manifest, reopen_population_material,
)
from .world_afterstate_v2_protocol import (
    TIER_SPECS, PopulationSlotV2, attempted_deal_identity,
    build_population_slot_ledger,
)
from .world_afterstate_v2_source_driver import (
    PopulationAttemptResultV2, drive_population_attempt_v2,
)
from .world_afterstate_v2_execution import (
    _cgroup_cpu_nanoseconds, _cgroup_v2_directory, _live_telemetry,
    _process_cpu_nanoseconds, verified_process_pool_kwargs,
)


SCHEMA = "world-afterstate-v2-population-controller-receipt-v1"
ATTEMPT_RECORD_SCHEMA = "world-afterstate-v2-population-controller-attempt-v1"
CONFIG_SCHEMA = "world-afterstate-v2-population-controller-config-v2"
STARTED_SCHEMA = "world-afterstate-v2-population-controller-started-v1"
CONTROLLER_DIRNAME = "population-controller"
ATTEMPT_DIRNAME = "attempts"
STARTED_DIRNAME = "started"
CONFIG_NAME = "config.json"
RECEIPT_NAME = "receipt.json"
# Keep this in lockstep with the frozen state/successor capacity arm grid.
# The 32-worker arm is a valid preregistered width; member concurrency is a
# separate dimension and is intentionally not widened here.
WORKER_ARMS = (1, 2, 4, 8, 16, 32)
DEFAULT_DEADLINE_SECONDS = 24 * 60 * 60
DEFAULT_HEARTBEAT_SECONDS = 60
AUTHORITY = {
    "data_collection_authorized": False,
    "audit_opening_authorized": False,
    "training_authorized": False,
    "strength_claim_authorized": False,
    "writer_authorized": False,
}
_REASONS = {
    "actual-trump-mode-mismatch", "no-eligible-state", "engine-error",
    "materialization-error", "requested-trump-mode-unavailable",
}
MAX_DECISIONS = 100


class WorldAfterstateV2PopulationControllerError(ValueError):
    """The bounded population run or its immutable ledger was refused."""


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _digest(value: object, label: str) -> str:
    if type(value) is not str or len(value) != 64 or any(
            char not in "0123456789abcdef" for char in value):
        raise WorldAfterstateV2PopulationControllerError(f"{label} drift")
    return value


def _int(value: object, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise WorldAfterstateV2PopulationControllerError(f"{label} drift")
    return value


def _root(value: object, *, create: bool = True) -> Path:
    if not isinstance(value, Path) or value.is_symlink():
        raise WorldAfterstateV2PopulationControllerError("population root drift")
    if create:
        value.mkdir(parents=True, exist_ok=True)
    if not value.is_dir():
        raise WorldAfterstateV2PopulationControllerError("population root drift")
    return value


def _public_attempt(identity: Mapping[str, Any]) -> dict[str, Any]:
    return {key: identity[key] for key in (
        "schema", "population_namespace_sha256", "slot_sha256",
        "attempt_index", "deal_sha256")}


def _attempt_path(root: Path, slot_sha256: str, index: int) -> Path:
    _digest(slot_sha256, "attempt slot SHA-256")
    _int(index, "attempt index")
    return root / CONTROLLER_DIRNAME / ATTEMPT_DIRNAME / (
        f"slot-{slot_sha256}-attempt-{index}.json")


def _strict_json(raw: bytes, label: str) -> dict[str, Any]:
    if type(raw) is not bytes or not raw:
        raise WorldAfterstateV2PopulationControllerError(f"{label} is empty")
    try:
        value = json.loads(raw.decode("ascii"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WorldAfterstateV2PopulationControllerError(
            f"{label} is not strict JSON") from exc
    if type(value) is not dict or canonical_json_bytes(value) != raw:
        raise WorldAfterstateV2PopulationControllerError(
            f"{label} is not canonical JSON")
    return value


def _slot_key(slot: PopulationSlotV2) -> tuple[str, str, str, int]:
    return (slot.tier, slot.split, slot.source, slot.ordinal)


def _validate_d256_slots(slots: Sequence[PopulationSlotV2]) \
        -> tuple[PopulationSlotV2, ...]:
    if type(slots) not in (tuple, list) or len(slots) != 256:
        raise WorldAfterstateV2PopulationControllerError(
            "D256 slot population drift")
    result = tuple(slots)
    if any(type(slot) is not PopulationSlotV2 for slot in result):
        raise WorldAfterstateV2PopulationControllerError("D256 slot type drift")
    expected = build_population_slot_ledger(TIER_SPECS[0])
    if result != expected:
        raise WorldAfterstateV2PopulationControllerError(
            "D256 slot derivation drift")
    if any(slot.tier != "D256" or slot.source not in ("natural", "mechanics")
           for slot in result):
        raise WorldAfterstateV2PopulationControllerError(
            "D256 source policy drift")
    return result


def _validate_material_stratum(material: Any, slot: PopulationSlotV2) -> None:
    """Recheck every frozen slot axis at both publication and reopen."""
    try:
        state = material.state
        if slot.source == "mechanics":
            actual = (state.source, state.split, state.trump_rank,
                      state.trump_mode)
            expected = (slot.source, slot.split, slot.trump_rank,
                        slot.trump_mode)
            if slot.mechanics_surface not in state.mechanics_surfaces:
                raise ValueError("mechanics surface drift")
        else:
            actual = (state.source, state.split, state.phase, state.position,
                      state.role, state.trump_rank, state.trump_mode,
                      state.select_subfold)
            expected = (slot.source, slot.split, slot.phase, slot.position,
                        slot.role, slot.trump_rank, slot.trump_mode,
                        slot.select_subfold)
    except Exception as exc:
        raise WorldAfterstateV2PopulationControllerError(
            "material slot stratum drift") from exc
    if actual != expected:
        raise WorldAfterstateV2PopulationControllerError(
            "material slot stratum drift")


def _ledger_sha256(slots: Sequence[PopulationSlotV2]) -> str:
    return _sha([slot.payload() for slot in slots])


def _config_path(root: Path) -> Path:
    return root / CONTROLLER_DIRNAME / CONFIG_NAME


def _config_payload(*, freeze: str, namespace: str, admission: str,
                    slots: Sequence[PopulationSlotV2], cap: int, workers: int,
                    deadline_seconds: int, deadline_unix_seconds: int,
                    heartbeat_seconds: int) -> dict[str, Any]:
    body = {
        "schema": CONFIG_SCHEMA, "freeze_sha256": freeze,
        "population_namespace_sha256": namespace,
        "admission_sha256": admission, "tier": "D256",
        "slot_count": len(slots), "slot_ledger_sha256": _ledger_sha256(slots),
        "max_attempts_per_slot": cap, "worker_arm": workers,
        "deadline_seconds": deadline_seconds,
        "deadline_unix_seconds": deadline_unix_seconds,
        "heartbeat_seconds": heartbeat_seconds,
        "authority": dict(AUTHORITY),
    }
    return {**body, "config_sha256": _sha(body)}


def _validate_config(value: Mapping[str, Any], *, freeze: str, namespace: str,
                     admission: str, slots: Sequence[PopulationSlotV2], cap: int,
                     workers: int, deadline_seconds: int,
                     heartbeat_seconds: int) -> dict[str, Any]:
    required = {"schema", "freeze_sha256", "population_namespace_sha256",
                "admission_sha256", "tier", "slot_count",
                "slot_ledger_sha256", "max_attempts_per_slot", "worker_arm",
                "deadline_seconds", "deadline_unix_seconds",
                "heartbeat_seconds", "authority", "config_sha256"}
    if type(value) is not dict or set(value) != required \
            or value["schema"] != CONFIG_SCHEMA or value["tier"] != "D256" \
            or value["authority"] != AUTHORITY:
        raise WorldAfterstateV2PopulationControllerError("population config drift")
    if (value["freeze_sha256"], value["population_namespace_sha256"],
            value["admission_sha256"], value["slot_count"],
            value["slot_ledger_sha256"], value["max_attempts_per_slot"],
            value["worker_arm"], value["deadline_seconds"],
            value["heartbeat_seconds"]) != (
                freeze, namespace, admission, len(slots), _ledger_sha256(slots),
                cap, workers, deadline_seconds, heartbeat_seconds):
        raise WorldAfterstateV2PopulationControllerError(
            "population config identity drift")
    _digest(value["config_sha256"], "config SHA-256")
    body = {key: item for key, item in value.items() if key != "config_sha256"}
    if value["config_sha256"] != _sha(body):
        raise WorldAfterstateV2PopulationControllerError("population config hash drift")
    _int(value["slot_count"], "config slot count", minimum=1)
    _int(value["max_attempts_per_slot"], "config maximum attempts", minimum=1)
    if isinstance(value["worker_arm"], bool) or value["worker_arm"] not in WORKER_ARMS:
        raise WorldAfterstateV2PopulationControllerError("config worker arm drift")
    _int(value["deadline_seconds"], "config deadline seconds", minimum=1)
    _int(value["heartbeat_seconds"], "config heartbeat seconds", minimum=1)
    if value["heartbeat_seconds"] > 60:
        raise WorldAfterstateV2PopulationControllerError("config heartbeat cadence drift")
    _int(value["deadline_unix_seconds"], "deadline", minimum=1)
    return dict(value)


def _open_or_publish_config(root: Path, *, freeze: str, namespace: str,
                            admission: str, slots: Sequence[PopulationSlotV2],
                            cap: int, workers: int, deadline_seconds: int,
                            heartbeat_seconds: int) -> dict[str, Any]:
    path = _config_path(root)
    if path.exists() or path.is_symlink():
        try:
            value = _strict_json(stable_read_bytes(path), "population config")
        except Exception as exc:
            raise WorldAfterstateV2PopulationControllerError(
                "population config reopen refused") from exc
        return _validate_config(
            value, freeze=freeze, namespace=namespace, admission=admission,
            slots=slots, cap=cap, workers=workers,
            deadline_seconds=deadline_seconds,
            heartbeat_seconds=heartbeat_seconds)
    controller = root / CONTROLLER_DIRNAME
    if controller.exists() and (controller.is_symlink() or not controller.is_dir()):
        raise WorldAfterstateV2PopulationControllerError("controller path drift")
    if controller.exists() and any(controller.iterdir()):
        raise WorldAfterstateV2PopulationControllerError(
            "controller config missing beside immutable ledger")
    deadline = int(time.time()) + deadline_seconds
    value = _config_payload(
        freeze=freeze, namespace=namespace, admission=admission, slots=slots,
        cap=cap, workers=workers, deadline_seconds=deadline_seconds,
        deadline_unix_seconds=deadline, heartbeat_seconds=heartbeat_seconds)
    controller.mkdir(parents=True, exist_ok=True)
    try:
        publish_exclusive_bytes(path, canonical_json_bytes(value))
    except Exception as exc:
        raise WorldAfterstateV2PopulationControllerError(
            "population config publication refused") from exc
    return value


def _check_deadline(config: Mapping[str, Any]) -> None:
    if time.time() >= config["deadline_unix_seconds"]:
        raise WorldAfterstateV2PopulationControllerError(
            "population deadline expired before new work")


@dataclass(frozen=True)
class PopulationSlotReceiptV2:
    slot_sha256: str
    tier: str
    split: str
    source: str
    ordinal: int
    attempt_count: int
    accepted_attempt: int
    rejection_counts: tuple[tuple[str, int], ...]
    shard: dict[str, Any]

    def payload(self) -> dict[str, Any]:
        return {
            "slot_sha256": self.slot_sha256, "tier": self.tier,
            "split": self.split, "source": self.source,
            "ordinal": self.ordinal, "attempt_count": self.attempt_count,
            "accepted_attempt": self.accepted_attempt,
            "rejection_counts": [[key, value]
                                 for key, value in self.rejection_counts],
            "shard": None if self.shard is None else dict(self.shard),
        }


@dataclass(frozen=True)
class PopulationCollectionReceiptV2:
    freeze_sha256: str
    population_namespace_sha256: str
    admission_sha256: str
    config_sha256: str
    tier: str
    max_attempts_per_slot: int
    slots: tuple[PopulationSlotReceiptV2, ...]
    attempts_total: int
    accepted_slots: int
    manifest_sha256: str
    population_sha256: str
    authority: dict[str, bool]
    schema: str = SCHEMA

    def validate(self) -> None:
        if self.schema != SCHEMA or self.tier != "D256":
            raise WorldAfterstateV2PopulationControllerError(
                "population receipt schema drift")
        for value, label in ((self.freeze_sha256, "freeze SHA-256"),
                             (self.population_namespace_sha256, "namespace SHA-256"),
                             (self.admission_sha256, "admission SHA-256"),
                             (self.config_sha256, "config SHA-256"),
                             (self.manifest_sha256, "manifest SHA-256"),
                             (self.population_sha256, "population SHA-256")):
            _digest(value, label)
        _int(self.max_attempts_per_slot, "maximum attempts", minimum=1)
        if type(self.authority) is not dict or self.authority != AUTHORITY:
            raise WorldAfterstateV2PopulationControllerError(
                "population receipt authority drift")
        if type(self.slots) is not tuple or len(self.slots) != 256:
            raise WorldAfterstateV2PopulationControllerError(
                "population receipt slot population drift")
        if any(type(row) is not PopulationSlotReceiptV2 for row in self.slots):
            raise WorldAfterstateV2PopulationControllerError(
                "population receipt slot type drift")
        expected = build_population_slot_ledger(TIER_SPECS[0])
        for slot, row in zip(expected, self.slots):
            _validate_slot_receipt(row, slot, self.max_attempts_per_slot)
        _int(self.attempts_total, "attempt total")
        _int(self.accepted_slots, "accepted slot count")
        if self.attempts_total != sum(row.attempt_count for row in self.slots) \
                or self.accepted_slots != 256:
            raise WorldAfterstateV2PopulationControllerError(
                "population receipt accounting drift")

    def payload(self) -> dict[str, Any]:
        self.validate()
        return {
            "schema": self.schema, "freeze_sha256": self.freeze_sha256,
            "population_namespace_sha256": self.population_namespace_sha256,
            "admission_sha256": self.admission_sha256, "tier": self.tier,
            "config_sha256": self.config_sha256,
            "max_attempts_per_slot": self.max_attempts_per_slot,
            "slots": [row.payload() for row in self.slots],
            "attempts_total": self.attempts_total,
            "accepted_slots": self.accepted_slots,
            "manifest_sha256": self.manifest_sha256,
            "population_sha256": self.population_sha256,
            "authority": dict(self.authority),
        }

    to_dict = payload


def _validate_slot_receipt(row: PopulationSlotReceiptV2,
                           slot: PopulationSlotV2, cap: int) -> None:
    if row.slot_sha256 != slot.slot_sha256 or row.tier != slot.tier \
            or row.split != slot.split or row.source != slot.source \
            or row.ordinal != slot.ordinal:
        raise WorldAfterstateV2PopulationControllerError(
            "population receipt slot binding drift")
    _digest(row.slot_sha256, "receipt slot SHA-256")
    _int(row.attempt_count, "slot attempt count", minimum=1)
    _int(row.accepted_attempt, "slot accepted attempt")
    if row.attempt_count > cap or row.accepted_attempt >= row.attempt_count:
        raise WorldAfterstateV2PopulationControllerError(
            "population receipt attempt cap drift")
    if type(row.rejection_counts) is not tuple or any(
            type(item) is not tuple or len(item) != 2 or item[0] not in _REASONS
            or _int(item[1], "rejection count") < 1
            for item in row.rejection_counts):
        raise WorldAfterstateV2PopulationControllerError(
            "population receipt rejection counts drift")
    if len({item[0] for item in row.rejection_counts}) != len(row.rejection_counts):
        raise WorldAfterstateV2PopulationControllerError(
            "population receipt rejection duplicate drift")
    if sum(item[1] for item in row.rejection_counts) != row.attempt_count - 1:
        raise WorldAfterstateV2PopulationControllerError(
            "population receipt rejection accounting drift")
    if type(row.shard) is not dict:
        raise WorldAfterstateV2PopulationControllerError(
            "population receipt shard drift")


def reopen_population_receipt_v2(value: Mapping[str, Any]) \
        -> PopulationCollectionReceiptV2:
    if type(value) is not dict:
        raise WorldAfterstateV2PopulationControllerError(
            "population receipt payload type drift")
    expected = {"schema", "freeze_sha256", "population_namespace_sha256",
                "admission_sha256", "config_sha256", "tier", "max_attempts_per_slot", "slots",
                "attempts_total", "accepted_slots", "manifest_sha256",
                "population_sha256", "authority"}
    if set(value) != expected or type(value["slots"]) is not list:
        raise WorldAfterstateV2PopulationControllerError(
            "population receipt field population drift")
    rows = []
    for item in value["slots"]:
        if type(item) is not dict or set(item) != {
                "slot_sha256", "tier", "split", "source", "ordinal",
                "attempt_count", "accepted_attempt", "rejection_counts", "shard"} \
                or type(item["rejection_counts"]) is not list:
            raise WorldAfterstateV2PopulationControllerError(
                "population receipt slot payload drift")
        rows.append(PopulationSlotReceiptV2(
            slot_sha256=item["slot_sha256"], tier=item["tier"],
            split=item["split"], source=item["source"], ordinal=item["ordinal"],
            attempt_count=item["attempt_count"],
            accepted_attempt=item["accepted_attempt"],
            rejection_counts=tuple(tuple(row) for row in item["rejection_counts"]),
            shard=item["shard"]))
    result = PopulationCollectionReceiptV2(
        freeze_sha256=value["freeze_sha256"],
        population_namespace_sha256=value["population_namespace_sha256"],
        admission_sha256=value["admission_sha256"], tier=value["tier"],
        config_sha256=value["config_sha256"],
        max_attempts_per_slot=value["max_attempts_per_slot"], slots=tuple(rows),
        attempts_total=value["attempts_total"], accepted_slots=value["accepted_slots"],
        manifest_sha256=value["manifest_sha256"],
        population_sha256=value["population_sha256"], authority=value["authority"],
        schema=value["schema"])
    result.validate()
    if result.payload() != value:
        raise WorldAfterstateV2PopulationControllerError(
            "population receipt reconstruction drift")
    return result


def _record_payload(*, freeze: str, namespace: str, admission: str,
                    slot: PopulationSlotV2, attempt: Mapping[str, Any],
                    accepted: bool, reason: str | None,
                    decision_count: int, shard: PopulationMaterialShardV2 | None,
                    material_raw: bytes | None = None
                    ) -> dict[str, Any]:
    if accepted != (shard is not None) or (accepted and reason is not None) \
            or (not accepted and reason not in _REASONS) \
            or (accepted != (material_raw is not None)):
        raise WorldAfterstateV2PopulationControllerError(
            "attempt record acceptance drift")
    public = _public_attempt(attempt)
    value = {
        "schema": ATTEMPT_RECORD_SCHEMA, "freeze_sha256": freeze,
        "population_namespace_sha256": namespace,
        "admission_sha256": admission, "slot_sha256": slot.slot_sha256,
        "attempt_index": attempt["attempt_index"],
        "attempted_deal": public, "accepted": accepted,
        "rejection_reason": reason, "decision_count": decision_count,
        "shard": None if shard is None else shard.row(),
        "material_base64": None if material_raw is None else
        base64.b64encode(material_raw).decode("ascii"),
        "state": "ready" if accepted else "rejected",
    }
    return {**value, "record_sha256": _sha(value)}


def _validate_record(value: Mapping[str, Any], *, freeze: str, namespace: str,
                     admission: str, slot: PopulationSlotV2, index: int,
                     cap: int) -> dict[str, Any]:
    expected = {"schema", "freeze_sha256", "population_namespace_sha256",
                "admission_sha256", "slot_sha256", "attempt_index",
                "attempted_deal", "accepted", "rejection_reason",
                "decision_count", "shard", "material_base64", "state",
                "record_sha256"}
    if type(value) is not dict or set(value) != expected \
            or value["schema"] != ATTEMPT_RECORD_SCHEMA:
        raise WorldAfterstateV2PopulationControllerError(
            "attempt record schema drift")
    if (value["freeze_sha256"], value["population_namespace_sha256"],
            value["admission_sha256"], value["slot_sha256"],
            value["attempt_index"]) != (freeze, namespace, admission,
                                          slot.slot_sha256, index):
        raise WorldAfterstateV2PopulationControllerError(
            "attempt record identity drift")
    _digest(freeze, "record freeze SHA-256")
    _digest(namespace, "record namespace SHA-256")
    _digest(admission, "record admission SHA-256")
    _int(index, "record attempt index")
    _digest(value["record_sha256"], "record SHA-256")
    body = {key: item for key, item in value.items() if key != "record_sha256"}
    if _sha(body) != value["record_sha256"]:
        raise WorldAfterstateV2PopulationControllerError(
            "attempt record hash drift")
    attempt = value["attempted_deal"]
    expected_attempt = attempted_deal_identity(namespace, slot, index)
    if type(attempt) is not dict or attempt != _public_attempt(expected_attempt):
        raise WorldAfterstateV2PopulationControllerError(
            "attempt record deal binding drift")
    if type(value["accepted"]) is not bool or type(value["decision_count"]) is not int \
            or isinstance(value["decision_count"], bool) \
            or not 0 <= value["decision_count"] <= MAX_DECISIONS:
        raise WorldAfterstateV2PopulationControllerError(
            "attempt record accounting drift")
    _int(index, "record attempt index")
    if index >= cap:
        raise WorldAfterstateV2PopulationControllerError(
            "attempt record cap drift")
    if value["accepted"]:
        if (value["rejection_reason"] is not None
                or type(value["shard"]) is not dict
                or value["state"] != "ready"
                or type(value["material_base64"]) is not str):
            raise WorldAfterstateV2PopulationControllerError(
                "accepted attempt record drift")
        try:
            raw = base64.b64decode(value["material_base64"], validate=True)
            if not raw:
                raise ValueError("empty material")
        except (ValueError, TypeError) as exc:
            raise WorldAfterstateV2PopulationControllerError(
                "accepted material envelope drift") from exc
    elif (value["shard"] is not None or value["rejection_reason"] not in _REASONS
          or value["material_base64"] is not None
          or value["state"] != "rejected"):
        raise WorldAfterstateV2PopulationControllerError(
            "rejected attempt record drift")
    return dict(value)


def _read_records(root: Path, slots: Sequence[PopulationSlotV2], *, freeze: str,
                  namespace: str, admission: str, cap: int) \
        -> dict[str, list[dict[str, Any]]]:
    directory = root / CONTROLLER_DIRNAME / ATTEMPT_DIRNAME
    controller_dir = root / CONTROLLER_DIRNAME
    if controller_dir.exists() and (controller_dir.is_symlink()
                                    or not controller_dir.is_dir()):
        raise WorldAfterstateV2PopulationControllerError(
            "controller path drift")
    if not directory.exists():
        return {slot.slot_sha256: [] for slot in slots}
    if directory.is_symlink() or not directory.is_dir():
        raise WorldAfterstateV2PopulationControllerError(
            "attempt ledger path drift")
    by_slot = {slot.slot_sha256: [] for slot in slots}
    for path in sorted(directory.iterdir()):
        if path.is_symlink() or not path.is_file() or path.suffix != ".json":
            raise WorldAfterstateV2PopulationControllerError(
                "attempt ledger file population drift")
        try:
            value = _strict_json(stable_read_bytes(path), "attempt record")
        except Exception as exc:
            raise WorldAfterstateV2PopulationControllerError(
                "attempt record reopen refused") from exc
        slot_sha = value.get("slot_sha256")
        if slot_sha not in by_slot:
            raise WorldAfterstateV2PopulationControllerError(
                "attempt record slot drift")
        index = value.get("attempt_index")
        _int(index, "attempt record index")
        slot = next(item for item in slots if item.slot_sha256 == slot_sha)
        checked = _validate_record(value, freeze=freeze, namespace=namespace,
                                   admission=admission, slot=slot, index=index,
                                   cap=cap)
        expected_name = _attempt_path(root, slot_sha, index).name
        if path.name != expected_name:
            raise WorldAfterstateV2PopulationControllerError(
                "attempt record path drift")
        by_slot[slot_sha].append(checked)
    for slot in slots:
        rows = sorted(by_slot[slot.slot_sha256], key=lambda row: row["attempt_index"])
        if [row["attempt_index"] for row in rows] != list(range(len(rows))):
            raise WorldAfterstateV2PopulationControllerError(
                "attempt ledger sequence drift")
        if any(row["accepted"] for row in rows[:-1]) \
                or rows and rows[-1]["accepted"] and len(rows) > cap:
            raise WorldAfterstateV2PopulationControllerError(
                "attempt ledger accepted-slot drift")
        by_slot[slot.slot_sha256] = rows
    started = _read_started(root, slots, freeze=freeze, namespace=namespace,
                            admission=admission)
    recorded = {(slot.slot_sha256, row["attempt_index"])
                for slot in slots for row in by_slot[slot.slot_sha256]}
    if started != recorded:
        raise WorldAfterstateV2PopulationControllerError(
            "attempt start/result ledger mismatch")
    for slot in slots:
        for row in by_slot[slot.slot_sha256]:
            if not row["accepted"]:
                continue
            try:
                raw = base64.b64decode(row["material_base64"], validate=True)
                material = reopen_population_material(raw)
                if material_sha256(material) != row["shard"]["material_sha256"]:
                    raise ValueError("material envelope hash drift")
                _validate_material_stratum(material, slot)
                if (material.slot_sha256, material.deal_sha256) != (
                        slot.slot_sha256,
                        row["attempted_deal"]["deal_sha256"]):
                    raise ValueError("material envelope binding drift")
            except Exception as exc:
                raise WorldAfterstateV2PopulationControllerError(
                    "accepted material envelope reopen refused") from exc
    return by_slot


def _started_path(root: Path, slot_sha256: str, index: int) -> Path:
    return root / CONTROLLER_DIRNAME / STARTED_DIRNAME / (
        f"slot-{slot_sha256}-attempt-{index}.json")


def _started_payload(*, freeze: str, namespace: str, admission: str,
                     slot: PopulationSlotV2, index: int) -> dict[str, Any]:
    attempt = attempted_deal_identity(namespace, slot, index)
    body = {
        "schema": STARTED_SCHEMA, "freeze_sha256": freeze,
        "population_namespace_sha256": namespace,
        "admission_sha256": admission, "slot_sha256": slot.slot_sha256,
        "attempt_index": index,
        "attempted_deal": _public_attempt(attempt),
    }
    return {**body, "started_sha256": _sha(body)}


def _publish_started(root: Path, *, freeze: str, namespace: str,
                     admission: str, slot: PopulationSlotV2, index: int) -> None:
    path = _started_path(root, slot.slot_sha256, index)
    path.parent.mkdir(parents=True, exist_ok=True)
    value = _started_payload(freeze=freeze, namespace=namespace,
                             admission=admission, slot=slot, index=index)
    try:
        publish_exclusive_bytes(path, canonical_json_bytes(value))
    except Exception as exc:
        raise WorldAfterstateV2PopulationControllerError(
            "attempt start publication refused") from exc


def _read_started(root: Path, slots: Sequence[PopulationSlotV2], *, freeze: str,
                  namespace: str, admission: str) -> set[tuple[str, int]]:
    directory = root / CONTROLLER_DIRNAME / STARTED_DIRNAME
    if not directory.exists():
        return set()
    if directory.is_symlink() or not directory.is_dir():
        raise WorldAfterstateV2PopulationControllerError(
            "started ledger path drift")
    by_slot = {slot.slot_sha256: slot for slot in slots}
    found: set[tuple[str, int]] = set()
    for path in sorted(directory.iterdir()):
        if path.is_symlink() or not path.is_file() or path.suffix != ".json":
            raise WorldAfterstateV2PopulationControllerError(
                "started ledger file population drift")
        try:
            value = _strict_json(stable_read_bytes(path), "started attempt")
        except Exception as exc:
            raise WorldAfterstateV2PopulationControllerError(
                "started attempt reopen refused") from exc
        expected = {"schema", "freeze_sha256", "population_namespace_sha256",
                    "admission_sha256", "slot_sha256", "attempt_index",
                    "attempted_deal", "started_sha256"}
        if set(value) != expected or value["schema"] != STARTED_SCHEMA:
            raise WorldAfterstateV2PopulationControllerError(
                "started attempt schema drift")
        slot = by_slot.get(value["slot_sha256"])
        index = value["attempt_index"]
        if slot is None or isinstance(index, bool) or not isinstance(index, int) \
                or index < 0 or path.name != _started_path(root, slot.slot_sha256,
                                                           index).name:
            raise WorldAfterstateV2PopulationControllerError(
                "started attempt identity drift")
        if (value["freeze_sha256"], value["population_namespace_sha256"],
                value["admission_sha256"]) != (freeze, namespace, admission):
            raise WorldAfterstateV2PopulationControllerError(
                "started attempt external identity drift")
        body = {key: item for key, item in value.items()
                if key != "started_sha256"}
        _digest(value["started_sha256"], "started attempt SHA-256")
        if value["started_sha256"] != _sha(body):
            raise WorldAfterstateV2PopulationControllerError(
                "started attempt hash drift")
        if value["attempted_deal"] != _public_attempt(
                attempted_deal_identity(namespace, slot, index)):
            raise WorldAfterstateV2PopulationControllerError(
                "started attempt deal drift")
        found.add((slot.slot_sha256, index))
    return found


def _expected_shard(root: Path, material: Any,
                    slot: PopulationSlotV2, raw: bytes) \
        -> PopulationMaterialShardV2:
    path = population_material_path(root, material.state_sha256)
    digest = hashlib.sha256(raw).hexdigest()
    return PopulationMaterialShardV2(
        relative_path=path.relative_to(root).as_posix(), tier=slot.tier,
        split=slot.split, source=slot.source, ordinal=slot.ordinal,
        deal_sha256=material.deal_sha256, slot_sha256=material.slot_sha256,
        state_sha256=material.state_sha256,
        candidate_set_sha256=material.candidate_set_sha256,
        byte_count=len(raw), sha256=digest, material_sha256=digest)


def _verify_record_shard(root: Path, row: Mapping[str, Any],
                        slot: PopulationSlotV2) -> PopulationMaterialShardV2:
    value = row["shard"]
    if type(value) is not dict:
        raise WorldAfterstateV2PopulationControllerError(
            "accepted shard record drift")
    try:
        shard = PopulationMaterialShardV2(**value)
        path = population_material_path(root, shard.state_sha256)
        if shard.relative_path != path.relative_to(root).as_posix():
            raise ValueError("shard path drift")
        raw = stable_read_bytes(path)
        material = reopen_population_material(raw)
        envelope = base64.b64decode(row["material_base64"], validate=True)
        if raw != envelope:
            raise ValueError("shard envelope bytes drift")
        _validate_material_stratum(material, slot)
        if (material.slot_sha256, material.deal_sha256, material.state_sha256,
                material.source, material.state.split) != (
                    slot.slot_sha256, row["attempted_deal"]["deal_sha256"],
                    shard.state_sha256, slot.source, slot.split):
            raise ValueError("shard semantic binding drift")
        if material_sha256(material) != shard.material_sha256 \
                or material_sha256(material) != shard.sha256 \
                or len(raw) != shard.byte_count:
            raise ValueError("shard bytes drift")
        return shard
    except (OSError, ValueError, TypeError, WorldAfterstateV2PopulationArtifactError) as exc:
        raise WorldAfterstateV2PopulationControllerError(
            "accepted shard reopen refused") from exc


def _publish_or_verify_shard(root: Path, material: Any,
                             shard: PopulationMaterialShardV2,
                             raw: bytes, slot: PopulationSlotV2) -> None:
    path = population_material_path(root, material.state_sha256)
    if path.exists() or path.is_symlink():
        try:
            existing = stable_read_bytes(path)
            if existing != raw:
                raise ValueError("occupied shard bytes drift")
            reopened = reopen_population_material(existing)
            _validate_material_stratum(reopened, slot)
            if material_sha256(reopened) != shard.material_sha256:
                raise ValueError("occupied shard identity drift")
            return
        except Exception as exc:
            raise WorldAfterstateV2PopulationControllerError(
                "occupied shard reopen refused") from exc
    try:
        published = publish_population_material(
            root, material, tier="D256")
    except Exception as exc:
        raise WorldAfterstateV2PopulationControllerError(
            "material shard publication refused") from exc
    if published != shard:
        raise WorldAfterstateV2PopulationControllerError(
            "published shard identity drift")


def _slot_receipt(root: Path, slot: PopulationSlotV2,
                  records: Sequence[Mapping[str, Any]], cap: int) \
        -> PopulationSlotReceiptV2:
    if not records or not records[-1]["accepted"]:
        raise WorldAfterstateV2PopulationControllerError(
            "slot is incomplete")
    counts = Counter(row["rejection_reason"] for row in records
                     if row["rejection_reason"] is not None)
    shard = _verify_record_shard(root, records[-1], slot)
    result = PopulationSlotReceiptV2(
        slot_sha256=slot.slot_sha256, tier=slot.tier, split=slot.split,
        source=slot.source, ordinal=slot.ordinal,
        attempt_count=len(records), accepted_attempt=records[-1]["attempt_index"],
        rejection_counts=tuple(sorted(counts.items())), shard=shard.row())
    _validate_slot_receipt(result, slot, cap)
    return result


@dataclass(frozen=True)
class _SlotRun:
    slot: PopulationSlotV2
    records: tuple[dict[str, Any], ...]


def _run_slot(root: Path, slot: PopulationSlotV2, existing: Sequence[dict[str, Any]],
              *, freeze: str, namespace: str, admission: str, cap: int,
              config: Mapping[str, Any], progress: _Progress,
              driver: Callable[[Mapping[str, Any], PopulationSlotV2],
                               PopulationAttemptResultV2]) -> _SlotRun:
    records = list(existing)
    if records and records[-1]["accepted"]:
        row = records[-1]
        raw = base64.b64decode(row["material_base64"], validate=True)
        material = reopen_population_material(raw)
        shard = PopulationMaterialShardV2(**row["shard"])
        _publish_or_verify_shard(root, material, shard, raw, slot)
        return _SlotRun(slot, tuple(records))
    for index in range(len(records), cap):
        _check_deadline(config)
        attempt = attempted_deal_identity(namespace, slot, index)
        _publish_started(root, freeze=freeze, namespace=namespace,
                         admission=admission, slot=slot, index=index)
        progress.attempt_started(slot, index)
        stop = threading.Event()
        heartbeat = threading.Thread(
            target=progress.heartbeat_loop,
            args=(stop, slot, index, config["heartbeat_seconds"],
                  config["deadline_unix_seconds"]), daemon=True)
        heartbeat.start()
        try:
            result = driver(attempt, slot)
        except Exception as exc:
            stop.set()
            heartbeat.join(timeout=2)
            raise WorldAfterstateV2PopulationControllerError(
                "population attempt failed") from exc
        finally:
            stop.set()
            heartbeat.join(timeout=2)
        try:
            if type(result) is not PopulationAttemptResultV2:
                raise WorldAfterstateV2PopulationControllerError(
                    "attempt driver result type drift")
            result.validate()
            if result.attempted_deal_identity != _public_attempt(attempt) \
                    or result.slot_sha256 != slot.slot_sha256 \
                    or result.deal_sha256 != attempt["deal_sha256"]:
                raise WorldAfterstateV2PopulationControllerError(
                    "attempt result identity drift")
            if result.accepted:
                material = result.material
                if material is None or material.slot_sha256 != slot.slot_sha256 \
                        or material.deal_sha256 != attempt["deal_sha256"] \
                        or material.state.source != slot.source \
                        or material.state.split != slot.split:
                    raise WorldAfterstateV2PopulationControllerError(
                        "accepted material slot binding drift")
                material.validate()
                _validate_material_stratum(material, slot)
                raw = population_material_bytes(material)
                shard = _expected_shard(root, material, slot, raw)
                value = _record_payload(
                    freeze=freeze, namespace=namespace, admission=admission,
                    slot=slot, attempt=attempt, accepted=True,
                    reason=None, decision_count=result.decision_count, shard=shard,
                    material_raw=raw)
            else:
                value = _record_payload(
                    freeze=freeze, namespace=namespace, admission=admission,
                    slot=slot, attempt=attempt, accepted=False,
                    reason=result.rejection_reason,
                    decision_count=result.decision_count, shard=None)
        except WorldAfterstateV2PopulationControllerError:
            raise
        except Exception as exc:
            raise WorldAfterstateV2PopulationControllerError(
                "population attempt failed") from exc
        path = _attempt_path(root, slot.slot_sha256, index)
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            publish_exclusive_bytes(path, canonical_json_bytes(value))
        except Exception as exc:
            raise WorldAfterstateV2PopulationControllerError(
                "attempt record publication refused") from exc
        if value["accepted"]:
            try:
                material = reopen_population_material(
                    base64.b64decode(value["material_base64"], validate=True))
                _publish_or_verify_shard(
                    root, material, PopulationMaterialShardV2(**value["shard"]),
                    base64.b64decode(value["material_base64"], validate=True), slot)
            except WorldAfterstateV2PopulationControllerError:
                raise
            except Exception as exc:
                raise WorldAfterstateV2PopulationControllerError(
                    "material shard publication refused") from exc
        records.append(value)
        if value["accepted"]:
            return _SlotRun(slot, tuple(records))
    raise WorldAfterstateV2PopulationControllerError(
        "attempt budget exhausted without a complete D256 slot")


class _Progress:
    def __init__(self, callback: Callable[[dict[str, Any]], None] | None,
                 total: int, completed: int, attempts: int, workers: int,
                 deadline: int | None = None) -> None:
        self.callback, self.total, self.started = callback, total, time.monotonic()
        self.completed, self.attempts, self.workers = completed, attempts, workers
        self.deadline = deadline
        self._lock = threading.Lock()
        self._process_cpu_baseline = _process_cpu_nanoseconds()
        self._cgroup_directory = _cgroup_v2_directory()
        self._cgroup_cpu_baseline = _cgroup_cpu_nanoseconds(
            self._cgroup_directory)
        self._peak_memory = 0
        self.emit(active_workers=workers)

    def attempt_started(self, slot: PopulationSlotV2, index: int) -> None:
        # ``stage`` is the supervisor's closed DAG stage, while individual
        # population attempts are operational detail within that stage.
        self.emit(active_workers=self.workers, stage="population",
                  substage=f"attempt/slot-{slot.ordinal}-attempt-{index}")

    def heartbeat_loop(self, stop: threading.Event, slot: PopulationSlotV2,
                       index: int, interval: int, deadline: int) -> None:
        while not stop.wait(interval):
            self.emit(active_workers=self.workers, stage="population",
                      substage=f"attempt/slot-{slot.ordinal}-attempt-{index}",
                      deadline=deadline)

    def emit(self, *, active_workers: int, stage: str = "population",
             substage: str = "slot-complete", deadline: int | None = None) -> None:
        if self.callback is None:
            return
        with self._lock:
            elapsed = time.monotonic() - self.started
            rate = self.completed / elapsed if self.completed else 0.0
            eta = ((self.total - self.completed) / rate) if rate else None
            deadline = self.deadline if deadline is None else deadline
            deadline_headroom = None if deadline is None else deadline - time.time()
            cpu_ppm, memory = _live_telemetry(
                int(elapsed * 1_000_000_000),
                process_cpu_baseline=self._process_cpu_baseline,
                cgroup_directory=self._cgroup_directory,
                cgroup_cpu_baseline=self._cgroup_cpu_baseline)
            self._peak_memory = max(self._peak_memory, memory)
            self.callback({
                "schema": "world-afterstate-v2-population-progress-v1",
                "stage": stage, "substage": substage,
                "completed_slots": self.completed, "total_slots": self.total,
                "attempts": self.attempts, "active_workers": active_workers,
                "cpu_utilization": cpu_ppm / 1_000_000,
                "current_memory_bytes": memory,
                "peak_memory_bytes": self._peak_memory,
                "deadline_headroom_seconds": deadline_headroom,
                "immutable_shards": self.completed,
                "elapsed_seconds": elapsed, "eta_seconds": eta,
                "authority": dict(AUTHORITY),
            })


def reopen_population_collection_v2(root: Path, *, freeze_sha256: str,
                                   population_namespace_sha256: str,
                                   admission_sha256: str | None = None,
                                   admission: str | None = None,
                                   max_attempts_per_slot: int | None = None
                                   ) -> PopulationCollectionReceiptV2:
    root = _root(root, create=False)
    admission_sha256 = _resolve_admission(admission_sha256, admission,
                                          freeze_sha256)
    _digest(freeze_sha256, "freeze SHA-256")
    _digest(population_namespace_sha256, "namespace SHA-256")
    _digest(admission_sha256, "admission SHA-256")
    if max_attempts_per_slot is not None:
        _int(max_attempts_per_slot, "maximum attempts", minimum=1)
    controller_dir = root / CONTROLLER_DIRNAME
    if controller_dir.exists() and (controller_dir.is_symlink()
                                    or not controller_dir.is_dir()):
        raise WorldAfterstateV2PopulationControllerError(
            "controller path drift")
    receipt_path = root / CONTROLLER_DIRNAME / RECEIPT_NAME
    try:
        receipt = reopen_population_receipt_v2(
            _strict_json(stable_read_bytes(receipt_path), "population receipt"))
        if (receipt.freeze_sha256, receipt.population_namespace_sha256,
                receipt.admission_sha256) != (
                    freeze_sha256, population_namespace_sha256,
                    admission_sha256) or (
                        max_attempts_per_slot is not None
                        and receipt.max_attempts_per_slot
                        != max_attempts_per_slot):
                raise WorldAfterstateV2PopulationControllerError(
                    "population receipt external identity drift")
        config_raw = stable_read_bytes(_config_path(root))
        config = _strict_json(config_raw, "population config")
        slots = _validate_d256_slots(build_population_slot_ledger(TIER_SPECS[0]))
        config = _validate_config(
            config, freeze=freeze_sha256,
            namespace=population_namespace_sha256, admission=admission_sha256,
            slots=slots, cap=receipt.max_attempts_per_slot,
            workers=config.get("worker_arm"),
            deadline_seconds=config.get("deadline_seconds"),
            heartbeat_seconds=config.get("heartbeat_seconds"))
        if config["config_sha256"] != receipt.config_sha256:
            raise WorldAfterstateV2PopulationControllerError(
                "population receipt config binding drift")
        reopened = reopen_population_manifest(
            root, expected_freeze_sha256=freeze_sha256,
            expected_population_namespace_sha256=population_namespace_sha256,
            expected_tier="D256", expected_split=None, expected_source=None,
            expected_population_sha256=receipt.population_sha256)
        if len(reopened) != 256:
            raise ValueError("population manifest slot population drift")
        cap = receipt.max_attempts_per_slot
        records = _read_records(
            root, slots, freeze=freeze_sha256,
            namespace=population_namespace_sha256, admission=admission_sha256,
            cap=cap)
        reopened_rows = tuple(_slot_receipt(
            root, slot, records[slot.slot_sha256], cap)
                              for slot in slots)
        if reopened_rows != receipt.slots:
            raise WorldAfterstateV2PopulationControllerError(
                "population receipt ledger drift")
        return receipt
    except WorldAfterstateV2PopulationControllerError:
        raise
    except Exception as exc:
        raise WorldAfterstateV2PopulationControllerError(
            "population collection reopen refused") from exc


def _resolve_admission(admission_sha256: str | None, admission: str | None,
                       freeze: str) -> str:
    if admission_sha256 is not None and admission is not None \
            and admission_sha256 != admission:
        raise WorldAfterstateV2PopulationControllerError(
            "admission identity drift")
    return admission_sha256 or admission or freeze


def collect_population_v2(
        root: Path, *, freeze_sha256: str,
        population_namespace_sha256: str, admission_sha256: str | None = None,
        admission: str | None = None, max_attempts_per_slot: int = 1,
        workers: int = 1,
        attempt_driver: Callable[[Mapping[str, Any], PopulationSlotV2],
                                 PopulationAttemptResultV2] | None = None,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
        tier: str = "D256", deadline_seconds: int = DEFAULT_DEADLINE_SECONDS,
        heartbeat_seconds: int = DEFAULT_HEARTBEAT_SECONDS) -> PopulationCollectionReceiptV2:
    """Collect and seal exactly the 256 frozen D256 natural/mechanics slots."""
    if tier != "D256":
        raise WorldAfterstateV2PopulationControllerError(
            "controller only accepts D256")
    if isinstance(workers, bool) or workers not in WORKER_ARMS:
        raise WorldAfterstateV2PopulationControllerError("worker arm drift")
    if attempt_driver is None:
        attempt_driver = drive_population_attempt_v2
    if not callable(attempt_driver):
        raise WorldAfterstateV2PopulationControllerError("attempt driver drift")
    root = _root(root)
    _digest(freeze_sha256, "freeze SHA-256")
    _digest(population_namespace_sha256, "namespace SHA-256")
    admission_sha256 = _resolve_admission(admission_sha256, admission,
                                          freeze_sha256)
    _digest(admission_sha256, "admission SHA-256")
    _int(max_attempts_per_slot, "maximum attempts", minimum=1)
    _int(deadline_seconds, "deadline seconds", minimum=1)
    _int(heartbeat_seconds, "heartbeat seconds", minimum=1)
    if heartbeat_seconds > 60:
        raise WorldAfterstateV2PopulationControllerError("heartbeat cadence drift")
    slots = _validate_d256_slots(build_population_slot_ledger(TIER_SPECS[0]))
    config = _open_or_publish_config(
        root, freeze=freeze_sha256, namespace=population_namespace_sha256,
        admission=admission_sha256, slots=slots,
        cap=max_attempts_per_slot, workers=workers,
        deadline_seconds=deadline_seconds, heartbeat_seconds=heartbeat_seconds)
    receipt_path = root / CONTROLLER_DIRNAME / RECEIPT_NAME
    if receipt_path.exists() or receipt_path.is_symlink():
        return reopen_population_collection_v2(
            root, freeze_sha256=freeze_sha256,
            population_namespace_sha256=population_namespace_sha256,
            admission_sha256=admission_sha256,
            max_attempts_per_slot=max_attempts_per_slot)
    _check_deadline(config)
    records = _read_records(
        root, slots, freeze=freeze_sha256, namespace=population_namespace_sha256,
        admission=admission_sha256, cap=max_attempts_per_slot)
    population_dir = root / "population"
    if population_dir.exists() and (population_dir.is_symlink()
                                    or not population_dir.is_dir()):
        raise WorldAfterstateV2PopulationControllerError(
            "population artifact path drift")
    referenced = set()
    for slot in slots:
        rows = records[slot.slot_sha256]
        if rows and rows[-1]["accepted"]:
            shard = _verify_record_shard(root, rows[-1], slot)
            referenced.add(root / shard.relative_path)
    if population_dir.exists():
        observed = {path for path in population_dir.rglob("*")
                    if path.is_file() or path.is_symlink()}
        if observed != referenced:
            raise WorldAfterstateV2PopulationControllerError(
                "occupied population artifact namespace")
    completed = sum(bool(rows and rows[-1]["accepted"]) for rows in records.values())
    attempts = sum(len(rows) for rows in records.values())
    progress = _Progress(progress_callback, 256, completed, attempts, workers,
                         config["deadline_unix_seconds"])
    runs: dict[str, _SlotRun] = {}
    pending: dict[Future[_SlotRun], PopulationSlotV2] = {}
    try:
        with ExitStack() as stack:
            driver = attempt_driver
            if attempt_driver is drive_population_attempt_v2:
                # Slot orchestration owns mutable progress and immutable file
                # publication in this process.  Only the CPU-bound, pure
                # attempt driver crosses the process boundary; otherwise a
                # wider ThreadPoolExecutor remains serialized by the GIL.
                driver_pool = stack.enter_context(ProcessPoolExecutor(
                    max_workers=workers, **verified_process_pool_kwargs()))

                def process_driver(
                        identity: Mapping[str, Any],
                        slot: PopulationSlotV2) -> PopulationAttemptResultV2:
                    return driver_pool.submit(
                        drive_population_attempt_v2, identity, slot).result()

                driver = process_driver
            pool = stack.enter_context(ThreadPoolExecutor(
                max_workers=workers, thread_name_prefix="d256-population"))
            for slot in slots:
                future = pool.submit(
                    _run_slot, root, slot, records[slot.slot_sha256],
                    freeze=freeze_sha256, namespace=population_namespace_sha256,
                    admission=admission_sha256, cap=max_attempts_per_slot,
                    config=config, progress=progress, driver=driver)
                pending[future] = slot
            for future in as_completed(pending):
                try:
                    run = future.result()
                except Exception:
                    # Do not drain every queued slot after the first failure.
                    # Apart from wasting work, doing so can publish hundreds
                    # of start receipts without matching result receipts and
                    # make the retained prefix impossible to resume.
                    for queued in pending:
                        if queued is not future:
                            queued.cancel()
                    raise
                runs[run.slot.slot_sha256] = run
                records[run.slot.slot_sha256] = list(run.records)
                progress.completed = sum(
                    bool(rows and rows[-1]["accepted"]) for rows in records.values())
                progress.attempts = sum(len(rows) for rows in records.values())
                progress.emit(active_workers=min(
                    workers, sum(not item.done() for item in pending)))
    except WorldAfterstateV2PopulationControllerError:
        raise
    except Exception as exc:
        raise WorldAfterstateV2PopulationControllerError(
            "population collection failed") from exc
    if len(runs) != 256:
        raise WorldAfterstateV2PopulationControllerError(
            "population collection incomplete")
    shards = tuple(_slot_receipt(root, slot, records[slot.slot_sha256],
                                 max_attempts_per_slot).shard
                   for slot in slots)
    shard_values = tuple(PopulationMaterialShardV2(**value) for value in shards)
    try:
        manifest = publish_population_manifest(
            root, shard_values, freeze_sha256=freeze_sha256,
            population_namespace_sha256=population_namespace_sha256,
            tier="D256")
    except Exception as exc:
        raise WorldAfterstateV2PopulationControllerError(
            "population manifest publication refused") from exc
    slot_receipts = tuple(_slot_receipt(
        root, slot, records[slot.slot_sha256], max_attempts_per_slot)
                          for slot in slots)
    receipt = PopulationCollectionReceiptV2(
        freeze_sha256=freeze_sha256,
        population_namespace_sha256=population_namespace_sha256,
        admission_sha256=admission_sha256, tier="D256",
        config_sha256=config["config_sha256"],
        max_attempts_per_slot=max_attempts_per_slot, slots=slot_receipts,
        attempts_total=sum(row.attempt_count for row in slot_receipts),
        accepted_slots=256, manifest_sha256=manifest["manifest_sha256"],
        population_sha256=manifest["population_sha256"], authority=dict(AUTHORITY))
    receipt.validate()
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        publish_exclusive_bytes(receipt_path, canonical_json_bytes(receipt.payload()))
    except Exception as exc:
        raise WorldAfterstateV2PopulationControllerError(
            "population receipt publication refused") from exc
    return receipt


# Descriptive aliases used by callers and integration tests.
run_population_collection_v2 = collect_population_v2
publish_population_v2 = collect_population_v2
collect_d256_population_v2 = collect_population_v2
run_d256_population_v2 = collect_population_v2
reopen_population_v2 = reopen_population_collection_v2
PopulationReceiptV2 = PopulationCollectionReceiptV2
PopulationControllerError = WorldAfterstateV2PopulationControllerError


__all__ = [
    "ATTEMPT_RECORD_SCHEMA", "AUTHORITY", "CONFIG_SCHEMA",
    "CONTROLLER_DIRNAME", "SCHEMA", "STARTED_SCHEMA", "WORKER_ARMS",
    "PopulationCollectionReceiptV2", "PopulationControllerError",
    "PopulationReceiptV2", "PopulationSlotReceiptV2",
    "WorldAfterstateV2PopulationControllerError", "collect_population_v2",
    "run_population_collection_v2", "publish_population_v2",
    "collect_d256_population_v2", "run_d256_population_v2",
    "reopen_population_receipt_v2", "reopen_population_collection_v2",
    "reopen_population_v2",
]
