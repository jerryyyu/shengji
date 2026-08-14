"""Compact strict artifact framing for BELIEF-V1 capture and REF-C evidence.

Millions of individual world files would make the B2 corpus operationally
fragile.  This module packs already-canonical rows into a simple length-
delimited binary stream, then strictly reconstructs the original typed
artifacts.  The framing is not a serialization shortcut: every JSON part is
canonical-parsed, every nested type is rebuilt, and the original validators
must reproduce the embedded manifests byte for byte.

The optional filesystem helpers use a single stable file descriptor for reads
and an fsynced, same-directory hard-link publication for writes.  They never
replace an existing final or partial artifact.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from pathlib import Path
from typing import Any

from .belief_capture import (
    CapturedRoundArtifactsV1,
    captured_round_artifacts,
    reopen_captured_round_artifacts,
)
from .belief_checkpoint import (
    FrozenModelCheckpointV1,
    validate_model_checkpoint,
)
from .belief_contract import ActorObservationV1, canonical_json_bytes
from .belief_ownership import receiver_sizes
from .belief_refc_capture import (
    ReferenceCapturedRoundV1,
    ReferenceWorldBatchV1,
    validate_reference_captured_round,
    validate_reference_world_batch,
)
from .belief_reference import (
    ReceiverCardsV1,
    SampledOwnershipWorldV1,
    validate_sampled_world,
)
from .belief_trainer import EpochTrainingReceiptV1
from .belief_reopen import actor_observation_from_dict


CAPTURE_MAGIC = b"BELIEF-V1-CAPTURE-BUNDLE-V1\0"
REFERENCE_MAGIC = b"BELIEF-V1-REF-C-ROUND-V1\0"
CHECKPOINT_MAGIC = b"BELIEF-V1-MODEL-CHECKPOINT-V1\0"
WORLD_BLOCK_MAGIC = b"BELIEF-V1-OWNERSHIP-WORLD-BLOCK-V1\0"
MAX_PART_BYTES = 512 * 1024**2
MAX_PART_COUNT = 128 * (2 + 256) + 2
SAMPLER_COUNTERS = (
    "sample_attempts", "accepted_worlds", "failed_worlds",
    "rejected_worlds", "impossible_worlds")


class BeliefArtifactError(ValueError):
    """A compact bundle, stable file, or publication contract drifted."""


def _reject_number(value: str) -> None:
    raise BeliefArtifactError(f"artifact contains invalid number {value}")


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise BeliefArtifactError("artifact JSON has duplicate key")
        result[key] = value
    return result


def _strict_json(raw: bytes, *, label: str) -> dict[str, Any]:
    if type(raw) is not bytes or not raw:
        raise BeliefArtifactError(f"{label} is empty")
    try:
        value = json.loads(
            raw.decode("ascii"), object_pairs_hook=_strict_object,
            parse_float=_reject_number, parse_constant=_reject_number)
    except BeliefArtifactError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BeliefArtifactError(f"{label} is not strict JSON") from exc
    if type(value) is not dict or canonical_json_bytes(value) != raw:
        raise BeliefArtifactError(f"{label} is not canonical JSON")
    return value


def _pack(magic: bytes, parts: tuple[bytes, ...]) -> bytes:
    if type(parts) is not tuple or not parts \
            or len(parts) > MAX_PART_COUNT \
            or any(type(part) is not bytes or not part
                   or len(part) > MAX_PART_BYTES for part in parts):
        raise BeliefArtifactError("artifact part population/size drift")
    output = bytearray(magic)
    output.extend(len(parts).to_bytes(8, "big"))
    for part in parts:
        output.extend(len(part).to_bytes(8, "big"))
        output.extend(part)
    return bytes(output)


def _unpack(raw: bytes, magic: bytes) -> tuple[bytes, ...]:
    if type(raw) is not bytes or not raw.startswith(magic):
        raise BeliefArtifactError("artifact framing magic drift")
    offset = len(magic)
    if len(raw) < offset + 8:
        raise BeliefArtifactError("artifact framing is truncated")
    count = int.from_bytes(raw[offset:offset + 8], "big")
    offset += 8
    if not 1 <= count <= MAX_PART_COUNT:
        raise BeliefArtifactError("artifact part count drift")
    parts = []
    for _ in range(count):
        if len(raw) < offset + 8:
            raise BeliefArtifactError("artifact part length is truncated")
        size = int.from_bytes(raw[offset:offset + 8], "big")
        offset += 8
        if not 1 <= size <= MAX_PART_BYTES or len(raw) < offset + size:
            raise BeliefArtifactError("artifact part size/truncation drift")
        parts.append(raw[offset:offset + size])
        offset += size
    if offset != len(raw):
        raise BeliefArtifactError("artifact has trailing bytes")
    return tuple(parts)


def capture_bundle_bytes(artifacts: CapturedRoundArtifactsV1) -> bytes:
    """Pack one validated, separated capture round."""
    captured = reopen_captured_round_artifacts(artifacts)
    decision_count = len(captured.pairs)
    parts = (artifacts.manifest_bytes, artifacts.transcript_bytes,
             *artifacts.actor_rows, *artifacts.target_rows)
    if len(parts) != 2 + 2 * decision_count:
        raise BeliefArtifactError("capture bundle decision population drift")
    return _pack(CAPTURE_MAGIC, tuple(parts))


def reopen_capture_bundle(raw: bytes) -> CapturedRoundArtifactsV1:
    """Reconstruct and validate every row in one capture bundle."""
    parts = _unpack(raw, CAPTURE_MAGIC)
    if len(parts) < 4 or (len(parts) - 2) % 2:
        raise BeliefArtifactError("capture bundle part population drift")
    decision_count = (len(parts) - 2) // 2
    artifacts = CapturedRoundArtifactsV1(
        manifest_bytes=parts[0], transcript_bytes=parts[1],
        actor_rows=parts[2:2 + decision_count],
        target_rows=parts[2 + decision_count:])
    try:
        captured = reopen_captured_round_artifacts(artifacts)
    except ValueError as exc:
        raise BeliefArtifactError("capture bundle typed reopen refused") \
            from exc
    if len(captured.pairs) != decision_count \
            or capture_bundle_bytes(artifacts) != raw:
        raise BeliefArtifactError("capture bundle reconstruction drift")
    return artifacts


def _world_block_bytes(batch: ReferenceWorldBatchV1) -> bytes:
    """Encode count cells at two bits each; manifests retain world hashes."""
    validate_reference_world_batch(batch)
    cards = tuple(card for card, _ in batch.actor.deductions.unseen)
    receivers = tuple(receiver for receiver, _ in batch.ownership().receiver_sizes)
    cell_count = len(cards) * len(receivers)
    bytes_per_world = (cell_count + 3) // 4
    payload = bytearray()
    for world in batch.worlds:
        by_receiver = {
            row.receiver: dict(row.cards) for row in world.receivers}
        if set(by_receiver) != set(receivers):
            raise BeliefArtifactError("world block receiver population drift")
        encoded = bytearray(bytes_per_world)
        for index, (card, receiver) in enumerate(
                (card, receiver) for card in cards for receiver in receivers):
            count = by_receiver[receiver].get(card, 0)
            if type(count) is not int or count not in (0, 1, 2):
                raise BeliefArtifactError("world block count drift")
            encoded[index // 4] |= count << (6 - 2 * (index % 4))
        payload.extend(encoded)
    return b"".join((
        WORLD_BLOCK_MAGIC,
        len(batch.worlds).to_bytes(4, "big"),
        len(cards).to_bytes(2, "big"),
        len(receivers).to_bytes(1, "big"),
        bytes_per_world.to_bytes(4, "big"),
        bytes(payload),
    ))


def _worlds_from_block(
        raw: bytes, *, actor: ActorObservationV1,
        expected_count: int, expected_stream_sha256: str) \
        -> tuple[SampledOwnershipWorldV1, ...]:
    header = len(WORLD_BLOCK_MAGIC) + 11
    if type(raw) is not bytes or len(raw) < header \
            or not raw.startswith(WORLD_BLOCK_MAGIC):
        raise BeliefArtifactError("world block header drift")
    offset = len(WORLD_BLOCK_MAGIC)
    world_count = int.from_bytes(raw[offset:offset + 4], "big")
    card_count = int.from_bytes(raw[offset + 4:offset + 6], "big")
    receiver_count = raw[offset + 6]
    bytes_per_world = int.from_bytes(raw[offset + 7:offset + 11], "big")
    payload = raw[header:]
    cards = tuple(card for card, _ in actor.deductions.unseen)
    receivers = tuple(receiver for receiver, _ in receiver_sizes(actor))
    cell_count = len(cards) * len(receivers)
    expected_bytes = (cell_count + 3) // 4
    if world_count != expected_count or world_count <= 0 \
            or card_count != len(cards) or receiver_count != len(receivers) \
            or bytes_per_world != expected_bytes \
            or len(payload) != world_count * bytes_per_world:
        raise BeliefArtifactError("world block population/size drift")
    worlds = []
    for world_index in range(world_count):
        encoded = payload[
            world_index * bytes_per_world:
            (world_index + 1) * bytes_per_world]
        if cell_count % 4 and encoded[-1] & (
                (1 << (8 - 2 * (cell_count % 4))) - 1):
            raise BeliefArtifactError("world block padding drift")
        counts = {receiver: {} for receiver in receivers}
        for index, (card, receiver) in enumerate(
                (card, receiver) for card in cards for receiver in receivers):
            count = (encoded[index // 4]
                     >> (6 - 2 * (index % 4))) & 3
            if count == 3:
                raise BeliefArtifactError("world block count code drift")
            if count:
                counts[receiver][card] = count
        world = SampledOwnershipWorldV1(
            actor_observation_sha256=actor.sha256(),
            receivers=tuple(ReceiverCardsV1(
                receiver=receiver,
                cards=tuple(sorted(counts[receiver].items())))
                            for receiver in receivers))
        try:
            validate_sampled_world(actor, world)
        except ValueError as exc:
            raise BeliefArtifactError("world block typed reopen refused") \
                from exc
        worlds.append(world)
    digest = hashlib.sha256()
    for world in worlds:
        canonical = world.canonical_bytes()
        digest.update(len(canonical).to_bytes(8, "big"))
        digest.update(canonical)
    if digest.hexdigest() != expected_stream_sha256:
        raise BeliefArtifactError("world block canonical stream hash drift")
    return tuple(worlds)


def _batch_parts(batch: ReferenceWorldBatchV1) -> tuple[bytes, ...]:
    validate_reference_world_batch(batch)
    return (batch.manifest_bytes(), batch.actor.canonical_bytes(),
            _world_block_bytes(batch))


def _batch_from_parts(parts: tuple[bytes, ...]) -> ReferenceWorldBatchV1:
    if len(parts) != 3:
        raise BeliefArtifactError("REF-C batch parts are incomplete")
    manifest = _strict_json(parts[0], label="REF-C batch manifest")
    actor_payload = _strict_json(parts[1], label="REF-C actor")
    try:
        actor = actor_observation_from_dict(actor_payload)
    except ValueError as exc:
        raise BeliefArtifactError("REF-C actor typed reopen refused") from exc
    expected_keys = {
        "schema", "actor_observation_sha256", "sampler_seed",
        "sampler_source_sha256", "sampler_source_sha256s",
        "behavior_policy_ids", "accepted_world_count", "attempts",
        "attempt_cap", "sampler_counters", "world_stream_sha256",
        "contains_sampled_hidden_worlds", "contains_round_outcome",
        "runtime_input",
    }
    if set(manifest) != expected_keys \
            or manifest["actor_observation_sha256"] != actor.sha256() \
            or type(manifest["behavior_policy_ids"]) is not list \
            or type(manifest["sampler_counters"]) is not dict \
            or set(manifest["sampler_counters"]) != {
                "before", "after", "delta"} \
            or any(type(manifest["sampler_counters"][name]) is not dict
                   for name in ("before", "after", "delta")) \
            or any(set(manifest["sampler_counters"][name])
                   != set(SAMPLER_COUNTERS)
                   for name in ("before", "after", "delta")) \
            or type(manifest["world_stream_sha256"]) is not str \
            or len(manifest["world_stream_sha256"]) != 64 \
            or any(char not in "0123456789abcdef"
                   for char in manifest["world_stream_sha256"]):
        raise BeliefArtifactError("REF-C batch manifest field drift")
    worlds = _worlds_from_block(
        parts[2], actor=actor,
        expected_count=manifest["accepted_world_count"],
        expected_stream_sha256=manifest["world_stream_sha256"])
    batch = ReferenceWorldBatchV1(
        schema=manifest["schema"], actor=actor,
        sampler_seed=manifest["sampler_seed"], attempts=manifest["attempts"],
        attempt_cap=manifest["attempt_cap"],
        sampler_before=tuple((name, manifest["sampler_counters"]
                              ["before"][name])
                             for name in SAMPLER_COUNTERS),
        sampler_after=tuple((name, manifest["sampler_counters"]
                             ["after"][name])
                            for name in SAMPLER_COUNTERS),
        sampler_delta=tuple((name, manifest["sampler_counters"]
                             ["delta"][name])
                            for name in SAMPLER_COUNTERS),
        worlds=worlds,
        sampler_source_sha256=manifest["sampler_source_sha256"],
        behavior_policy_ids=tuple(manifest["behavior_policy_ids"]))
    try:
        validate_reference_world_batch(batch)
    except ValueError as exc:
        raise BeliefArtifactError("REF-C batch typed reopen refused") from exc
    if batch.manifest_bytes() != parts[0] \
            or batch.manifest_dict()["world_stream_sha256"] \
            != manifest["world_stream_sha256"]:
        raise BeliefArtifactError("REF-C batch reconstruction drift")
    return batch


def reference_round_bundle_bytes(result: ReferenceCapturedRoundV1) -> bytes:
    """Pack a validated REF-C round and its exact replayed capture."""
    validate_reference_captured_round(result)
    capture = capture_bundle_bytes(captured_round_artifacts(result.captured))
    parts = [result.manifest_bytes(), capture]
    for batch in result.batches:
        parts.extend(_batch_parts(batch))
    return _pack(REFERENCE_MAGIC, tuple(parts))


def reopen_reference_round_bundle(raw: bytes) -> ReferenceCapturedRoundV1:
    """Reconstruct a complete REF-C round without drawing a new world."""
    parts = _unpack(raw, REFERENCE_MAGIC)
    if len(parts) < 2:
        raise BeliefArtifactError("REF-C round bundle is incomplete")
    manifest = _strict_json(parts[0], label="REF-C round manifest")
    if type(manifest.get("decision_count")) is not int \
            or manifest["decision_count"] <= 0 \
            or type(manifest.get("accepted_world_count")) is not int:
        raise BeliefArtifactError("REF-C round manifest count drift")
    capture_artifacts = reopen_capture_bundle(parts[1])
    captured = reopen_captured_round_artifacts(capture_artifacts)
    batch_count = manifest["decision_count"]
    world_count = manifest["accepted_world_count"] // batch_count
    batch_part_count = 3
    if world_count <= 0 \
            or len(parts) != 2 + batch_count * batch_part_count:
        raise BeliefArtifactError("REF-C round batch framing drift")
    batches = tuple(_batch_from_parts(tuple(parts[
        2 + index * batch_part_count:
        2 + (index + 1) * batch_part_count]))
        for index in range(batch_count))
    result = ReferenceCapturedRoundV1(
        captured=captured, replicate=manifest.get("replicate"),
        batches=batches)
    try:
        validate_reference_captured_round(result)
    except ValueError as exc:
        raise BeliefArtifactError("REF-C round typed reopen refused") from exc
    if result.manifest_bytes() != parts[0] \
            or reference_round_bundle_bytes(result) != raw:
        raise BeliefArtifactError("REF-C round reconstruction drift")
    return result


def _epoch_receipt_from_bytes(raw: bytes) -> EpochTrainingReceiptV1:
    payload = _strict_json(raw, label="training epoch receipt")
    expected = {
        "schema", "epoch", "batch_count", "decision_count",
        "active_label_count", "mean_loss_nanonats", "batch_schema",
        "history_transform", "label_transform", "control_kind",
        "model_state_sha256_before", "model_state_sha256_after",
        "privileged_targets_consumed", "checkpoint_written",
        "runtime_artifact",
    }
    integer_fields = (
        "epoch", "batch_count", "decision_count", "active_label_count",
        "mean_loss_nanonats")
    digest_fields = (
        "model_state_sha256_before", "model_state_sha256_after")
    if set(payload) != expected \
            or any(type(payload[name]) is not int or payload[name] < 0
                   for name in integer_fields) \
            or min(payload[name] for name in integer_fields[:4]) <= 0 \
            or any(type(payload[name]) is not str or not payload[name]
                   for name in ("schema", "batch_schema",
                                "history_transform", "label_transform",
                                "control_kind")) \
            or any(type(payload[name]) is not str
                   or len(payload[name]) != 64
                   or any(char not in "0123456789abcdef"
                          for char in payload[name])
                   for name in digest_fields) \
            or payload["privileged_targets_consumed"] is not True \
            or payload["checkpoint_written"] is not False \
            or payload["runtime_artifact"] is not False:
        raise BeliefArtifactError("training epoch receipt field drift")
    receipt = EpochTrainingReceiptV1(
        epoch=payload["epoch"], batch_count=payload["batch_count"],
        decision_count=payload["decision_count"],
        active_label_count=payload["active_label_count"],
        mean_loss_nanonats=payload["mean_loss_nanonats"],
        batch_schema=payload["batch_schema"],
        history_transform=payload["history_transform"],
        label_transform=payload["label_transform"],
        control_kind=payload["control_kind"],
        model_state_sha256_before=payload["model_state_sha256_before"],
        model_state_sha256_after=payload["model_state_sha256_after"],
        schema=payload["schema"])
    if receipt.canonical_bytes() != raw:
        raise BeliefArtifactError("training epoch receipt rebuild drift")
    return receipt


def reopen_epoch_receipt(raw: bytes) -> EpochTrainingReceiptV1:
    """Public strict reopener for a persisted score-free epoch receipt."""
    return _epoch_receipt_from_bytes(raw)


def checkpoint_bundle_bytes(
        checkpoint: FrozenModelCheckpointV1,
        receipt: EpochTrainingReceiptV1) -> bytes:
    """Pack one non-executable model checkpoint and its exact receipt."""
    try:
        validate_model_checkpoint(checkpoint, final_epoch_receipt=receipt)
    except ValueError as exc:
        raise BeliefArtifactError("model checkpoint validation refused") \
            from exc
    return _pack(CHECKPOINT_MAGIC, (
        receipt.canonical_bytes(), checkpoint.manifest_bytes,
        *checkpoint.parameter_blocks))


def reopen_checkpoint_bundle(
        raw: bytes) -> tuple[FrozenModelCheckpointV1,
                             EpochTrainingReceiptV1]:
    """Rebuild one checkpoint without a pickle or code-loading surface."""
    parts = _unpack(raw, CHECKPOINT_MAGIC)
    if len(parts) < 3:
        raise BeliefArtifactError("model checkpoint bundle is incomplete")
    receipt = _epoch_receipt_from_bytes(parts[0])
    checkpoint = FrozenModelCheckpointV1(
        manifest_bytes=parts[1], parameter_blocks=parts[2:])
    try:
        validate_model_checkpoint(checkpoint, final_epoch_receipt=receipt)
    except ValueError as exc:
        raise BeliefArtifactError("model checkpoint typed reopen refused") \
            from exc
    if checkpoint_bundle_bytes(checkpoint, receipt) != raw:
        raise BeliefArtifactError("model checkpoint reconstruction drift")
    return checkpoint, receipt


def _stat_identity(info: os.stat_result) -> tuple[int, ...]:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_nlink,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def stable_read_bytes(path: Path) -> bytes:
    """Read one regular, unlinked, nonwritable artifact from one descriptor."""
    if not isinstance(path, Path) or path.is_symlink():
        raise BeliefArtifactError("artifact path is not a lexical regular file")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise BeliefArtifactError("artifact open refused") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 \
                or before.st_mode & 0o222:
            raise BeliefArtifactError(
                "artifact must be regular, unlinked, and nonwritable")
        chunks = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    try:
        path_info = path.lstat()
    except OSError as exc:
        raise BeliefArtifactError("artifact path disappeared") from exc
    if _stat_identity(before) != _stat_identity(after) \
            or _stat_identity(after) != _stat_identity(path_info):
        raise BeliefArtifactError("artifact changed during stable read")
    raw = b"".join(chunks)
    if len(raw) != after.st_size:
        raise BeliefArtifactError("artifact byte count drift")
    return raw


def publish_exclusive_bytes(path: Path, raw: bytes) -> str:
    """Fsync and atomically hard-link one immutable final artifact."""
    if not isinstance(path, Path) or type(raw) is not bytes or not raw \
            or path.name in ("", ".", "..") or path.is_symlink():
        raise BeliefArtifactError("artifact publication input drift")
    partial = path.with_name(path.name + ".partial")
    if path.exists() or partial.exists():
        raise BeliefArtifactError("artifact output slot is already occupied")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = -1
    published = False
    try:
        descriptor = os.open(partial, flags, 0o600)
        view = memoryview(raw)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise BeliefArtifactError("artifact write made no progress")
            view = view[written:]
        os.fsync(descriptor)
        os.fchmod(descriptor, 0o400)
        os.close(descriptor)
        descriptor = -1
        os.link(partial, path)
        published = True
        partial.unlink()
        parent = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
        if stable_read_bytes(path) != raw:
            raise BeliefArtifactError("published artifact reopen drift")
        return hashlib.sha256(raw).hexdigest()
    except FileExistsError as exc:
        raise BeliefArtifactError(
            "artifact publication refused concurrent writer") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if not published:
            # Preserve any fully or partially written diagnostic bytes.  A
            # failed slot is one-shot and requires a fresh namespace.
            pass
