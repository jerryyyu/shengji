"""Durable, chain-linked epoch recovery for BELIEF V2/R4 training.

Every completed epoch is published atomically before the deadline guard may
admit another epoch.  A restart is allowed to consume only the highest
contiguous journal epoch; operators cannot select an earlier checkpoint.  The
journal contains optimizer state and therefore is recovery evidence, never a
runtime model or strength result.
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import torch

from .belief_artifacts import (
    publish_exclusive_bytes,
    reopen_epoch_receipt,
    stable_read_bytes,
)
from .belief_cohort import COHORT_SEEDS
from .belief_contract import canonical_json_bytes
from .belief_model import new_from_scratch_model
from .belief_training_schedule import select_common_epoch
from .belief_v2_accelerator import (
    new_v2_optimizer,
    portable_model_state_sha256,
)
from .belief_v2_cohort_training import (
    V2CohortResumeStateV1,
    V2TrainingEpochCurveRowV1,
)


EPOCH_JOURNAL_SCHEMA = "belief-v1-v2-epoch-journal-v1"
EPOCH_CURVES_SCHEMA = "belief-v1-v2-epoch-journal-curves-v1"
STATE_FILENAME = "resume-state.pt"
CURVES_FILENAME = "curves.json"
MANIFEST_FILENAME = "manifest.json"


class BeliefV2EpochJournalError(ValueError):
    """The epoch journal was incomplete, ambiguous, or cross-bound."""


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _is_sha256(value: Any) -> bool:
    return type(value) is str and len(value) == 64 \
        and all(char in "0123456789abcdef" for char in value)


@dataclass(frozen=True)
class V2EpochJournalBindingV1:
    freeze_sha256: str
    admission_sha256: str
    cohort_id: str
    realization_sha256: str
    common_calibration_sha256: str
    selected_device: str
    torch_num_threads: int
    journal_byte_cap: int

    def to_dict(self) -> dict[str, Any]:
        _validate_binding(self)
        return {
            "freeze_sha256": self.freeze_sha256,
            "admission_sha256": self.admission_sha256,
            "cohort_id": self.cohort_id,
            "realization_sha256": self.realization_sha256,
            "common_calibration_sha256": (
                self.common_calibration_sha256),
            "selected_device": self.selected_device,
            "torch_num_threads": self.torch_num_threads,
            "journal_byte_cap": self.journal_byte_cap,
        }


@dataclass(frozen=True)
class V2ReopenedEpochSnapshotV1:
    """One fully reopened epoch, including the model used for rescoring."""

    epoch: int
    manifest: dict[str, Any]
    curves: tuple[V2TrainingEpochCurveRowV1, ...]
    current_model_states: tuple[dict[str, torch.Tensor], ...]
    optimizer_states: tuple[dict[str, Any], ...]
    selected_model_states: tuple[dict[str, torch.Tensor], ...]


def _validate_binding(binding: V2EpochJournalBindingV1) -> None:
    if type(binding) is not V2EpochJournalBindingV1 \
            or any(not _is_sha256(value) for value in (
                binding.freeze_sha256, binding.admission_sha256,
                binding.realization_sha256,
                binding.common_calibration_sha256)) \
            or type(binding.cohort_id) is not str \
            or not binding.cohort_id \
            or binding.selected_device != "cpu" \
            or type(binding.torch_num_threads) is not int \
            or binding.torch_num_threads <= 0 \
            or type(binding.journal_byte_cap) is not int \
            or binding.journal_byte_cap <= 0:
        raise BeliefV2EpochJournalError(
            "V2 epoch journal binding drift")


def _state_to_cpu(value: Any) -> Any:
    if isinstance(value, torch.Tensor):
        return value.detach().to(device="cpu", copy=True).contiguous()
    if isinstance(value, dict):
        return {key: _state_to_cpu(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return tuple(_state_to_cpu(item) for item in value)
    if isinstance(value, list):
        return [_state_to_cpu(item) for item in value]
    return value


def _serialize_state(state: V2CohortResumeStateV1) -> bytes:
    if type(state) is not V2CohortResumeStateV1:
        raise BeliefV2EpochJournalError(
            "V2 epoch journal resume state drift")
    buffer = io.BytesIO()
    torch.save({
        "current_model_states": tuple(
            _state_to_cpu(model.state_dict()) for model in state.models),
        "optimizer_states": tuple(
            _state_to_cpu(optimizer.state_dict())
            for optimizer in state.optimizers),
        "selected_model_states": tuple(
            _state_to_cpu(row) for row in state.selected_states),
    }, buffer)
    return buffer.getvalue()


def _curves_bytes(state: V2CohortResumeStateV1) -> bytes:
    return canonical_json_bytes({
        "schema": EPOCH_CURVES_SCHEMA,
        "epoch_count": len(state.epochs),
        "epochs": [row.to_dict() for row in state.epochs],
    })


def _model_hashes(states: tuple[dict[str, torch.Tensor], ...]) \
        -> tuple[str, ...]:
    if type(states) is not tuple or len(states) != len(COHORT_SEEDS):
        raise BeliefV2EpochJournalError(
            "V2 epoch journal model population drift")
    result = []
    for seed, row in zip(COHORT_SEEDS, states, strict=True):
        model = new_from_scratch_model(seed)
        try:
            model.load_state_dict(row, strict=True)
            result.append(portable_model_state_sha256(model))
        except (RuntimeError, ValueError) as exc:
            raise BeliefV2EpochJournalError(
                "V2 epoch journal model state refused") from exc
    return tuple(result)


def _epoch_name(epoch: int) -> str:
    return f"epoch-{epoch:04d}"


def _manifest(
        binding: V2EpochJournalBindingV1, state: V2CohortResumeStateV1,
        *, state_raw: bytes, curves_raw: bytes,
        previous_manifest_sha256: str | None,
        stage_started_monotonic_nanoseconds: int,
        observed_monotonic_nanoseconds: int,
        cumulative_cpu_nanoseconds: int,
        exact_resume_count: int) -> dict[str, Any]:
    epoch = len(state.epochs)
    current_hashes = tuple(
        portable_model_state_sha256(model) for model in state.models)
    selected_hashes = _model_hashes(state.selected_states)
    decision = select_common_epoch(tuple(tuple(
        curve.member_calibration_loss_nanonats[index]
        for curve in state.epochs) for index in range(len(COHORT_SEEDS))))
    if decision.stop_epoch != epoch \
            or current_hashes != tuple(
                receipt.model_state_sha256_after
                for receipt in state.epochs[-1].member_training_receipts) \
            or selected_hashes != tuple(
                receipt.model_state_sha256_after
                for receipt in state.selected_receipts) \
            or state.selected_receipts != state.epochs[
                decision.selected_epoch - 1].member_training_receipts:
        raise BeliefV2EpochJournalError(
            "V2 epoch journal trajectory binding drift")
    if type(stage_started_monotonic_nanoseconds) is not int \
            or type(observed_monotonic_nanoseconds) is not int \
            or not 0 < stage_started_monotonic_nanoseconds \
            < observed_monotonic_nanoseconds \
            or type(cumulative_cpu_nanoseconds) is not int \
            or cumulative_cpu_nanoseconds < 0 \
            or type(exact_resume_count) is not int \
            or exact_resume_count < 0:
        raise BeliefV2EpochJournalError(
            "V2 epoch journal clock drift")
    return {
        "schema": EPOCH_JOURNAL_SCHEMA,
        "binding": binding.to_dict(),
        "epoch": epoch,
        "previous_manifest_sha256": previous_manifest_sha256,
        "selected_common_epoch": decision.selected_epoch,
        "stage_started_monotonic_nanoseconds": (
            stage_started_monotonic_nanoseconds),
        "observed_monotonic_nanoseconds": observed_monotonic_nanoseconds,
        "cumulative_wall_nanoseconds": (
            observed_monotonic_nanoseconds
            - stage_started_monotonic_nanoseconds),
        "cumulative_cpu_nanoseconds": cumulative_cpu_nanoseconds,
        "exact_resume_count": exact_resume_count,
        "current_model_state_sha256s": list(current_hashes),
        "selected_model_state_sha256s": list(selected_hashes),
        "files": {
            STATE_FILENAME: {
                "byte_count": len(state_raw),
                "sha256": _sha256(state_raw),
            },
            CURVES_FILENAME: {
                "byte_count": len(curves_raw),
                "sha256": _sha256(curves_raw),
            },
        },
        "contains_optimizer_resume_state": True,
        "mandatory_latest_epoch_resume": True,
        "operator_checkpoint_selection_authorized": False,
        "runtime_artifact": False,
        "calibration_open_authorized": False,
        "test_split_open_authorized": False,
        "sampler_implementation_authorized": False,
        "gameplay_strength_screen_authorized": False,
        "strength_claim_authorized": False,
        "deployment_authorized": False,
    }


def _journal_entries(directory: Path) -> tuple[Path, ...]:
    if directory.is_symlink() or not directory.is_dir():
        raise BeliefV2EpochJournalError(
            "V2 epoch journal directory drift")
    finals = []
    partials = []
    for path in directory.iterdir():
        if path.name.startswith("epoch-") and path.name.endswith(".partial"):
            partials.append(path)
        elif path.name.startswith("epoch-"):
            finals.append(path)
        else:
            raise BeliefV2EpochJournalError(
                "V2 epoch journal entry population drift")
    ordered = tuple(sorted(finals, key=lambda path: path.name))
    if tuple(path.name for path in ordered) != tuple(
            _epoch_name(epoch) for epoch in range(1, len(ordered) + 1)):
        raise BeliefV2EpochJournalError(
            "V2 epoch journal chain population drift")
    expected_partial = f"{_epoch_name(len(ordered) + 1)}.partial"
    if len(partials) > 1 \
            or partials and (partials[0].name != expected_partial
                             or partials[0].is_symlink()
                             or not partials[0].is_dir()):
        raise BeliefV2EpochJournalError(
            "V2 epoch journal partial population drift")
    if partials:
        names = {path.name for path in partials[0].iterdir()}
        allowed = {
            STATE_FILENAME, CURVES_FILENAME, MANIFEST_FILENAME,
            f"{STATE_FILENAME}.partial", f"{CURVES_FILENAME}.partial",
            f"{MANIFEST_FILENAME}.partial",
        }
        if not names <= allowed or any(
                name in names and f"{name}.partial" in names
                for name in (STATE_FILENAME, CURVES_FILENAME,
                             MANIFEST_FILENAME)):
            raise BeliefV2EpochJournalError(
                "V2 epoch journal contains an invalid partial publication")
    return ordered


def _read_partial_bytes(path: Path) -> bytes:
    """Read one writable publication fragment without following links."""
    if path.is_symlink():
        raise BeliefV2EpochJournalError(
            "V2 epoch journal publication fragment is a symlink")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise BeliefV2EpochJournalError(
            "V2 epoch journal publication fragment open refused") from exc
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink not in (1, 2):
            raise BeliefV2EpochJournalError(
                "V2 epoch journal publication fragment drift")
        chunks = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    info = path.lstat()
    identity = lambda row: (
        row.st_dev, row.st_ino, row.st_mode, row.st_nlink, row.st_size,
        row.st_mtime_ns, row.st_ctime_ns)
    if identity(before) != identity(after) or identity(after) != identity(info):
        raise BeliefV2EpochJournalError(
            "V2 epoch journal publication fragment changed during read")
    return b"".join(chunks)


def _fsync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _resume_or_publish_bytes(path: Path, raw: bytes) -> None:
    """Complete only an exact prefix left by interrupted atomic publication."""
    fragment = path.with_name(path.name + ".partial")
    if path.exists() or path.is_symlink():
        if fragment.exists() or fragment.is_symlink():
            final_info = path.lstat()
            fragment_info = fragment.lstat()
            if path.is_symlink() or fragment.is_symlink() \
                    or (final_info.st_dev, final_info.st_ino) != (
                        fragment_info.st_dev, fragment_info.st_ino) \
                    or final_info.st_nlink != 2 \
                    or _read_partial_bytes(fragment) != raw:
                raise BeliefV2EpochJournalError(
                    "V2 epoch journal linked publication drift")
            fragment.unlink()
            _fsync_directory(path.parent)
        try:
            existing = stable_read_bytes(path)
        except ValueError as exc:
            raise BeliefV2EpochJournalError(
                "V2 epoch journal completed publication refused") from exc
        if existing != raw:
            raise BeliefV2EpochJournalError(
                "V2 epoch journal resumed publication drift")
        return
    if fragment.exists() or fragment.is_symlink():
        existing = _read_partial_bytes(fragment)
        if len(existing) > len(raw) or raw[:len(existing)] != existing:
            raise BeliefV2EpochJournalError(
                "V2 epoch journal resumed publication prefix drift")
        try:
            os.chmod(fragment, 0o600, follow_symlinks=False)
            descriptor = os.open(
                fragment,
                os.O_WRONLY | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0))
            try:
                view = memoryview(raw)[len(existing):]
                while view:
                    written = os.write(descriptor, view)
                    if written <= 0:
                        raise BeliefV2EpochJournalError(
                            "V2 epoch journal resumed publication stalled")
                    view = view[written:]
                os.fsync(descriptor)
                os.fchmod(descriptor, 0o400)
            finally:
                os.close(descriptor)
            os.link(fragment, path)
            fragment.unlink()
            _fsync_directory(path.parent)
        except OSError as exc:
            raise BeliefV2EpochJournalError(
                "V2 epoch journal publication recovery refused") from exc
        try:
            reopened = stable_read_bytes(path)
        except ValueError as exc:
            raise BeliefV2EpochJournalError(
                "V2 epoch journal recovered publication refused") from exc
        if reopened != raw:
            raise BeliefV2EpochJournalError(
                "V2 epoch journal recovered publication drift")
        return
    try:
        publish_exclusive_bytes(path, raw)
    except ValueError as exc:
        raise BeliefV2EpochJournalError(
            "V2 epoch journal publication refused") from exc


def publish_epoch_resume_state(
        directory: Path, binding: V2EpochJournalBindingV1,
        state: V2CohortResumeStateV1, *,
        stage_started_monotonic_nanoseconds: int,
        observed_monotonic_nanoseconds: int,
        cumulative_cpu_nanoseconds: int,
        exact_resume_count: int) -> dict[str, Any]:
    """Atomically append exactly the next completed epoch."""
    _validate_binding(binding)
    if not isinstance(directory, Path) or directory.is_symlink():
        raise BeliefV2EpochJournalError(
            "V2 epoch journal publish directory drift")
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    entries = _journal_entries(directory)
    epoch = len(state.epochs)
    if epoch != len(entries) + 1:
        raise BeliefV2EpochJournalError(
            "V2 epoch journal append order drift")
    previous = None if not entries else _sha256(stable_read_bytes(
        entries[-1] / MANIFEST_FILENAME))
    state_raw = _serialize_state(state)
    curves_raw = _curves_bytes(state)
    manifest = _manifest(
        binding, state, state_raw=state_raw, curves_raw=curves_raw,
        previous_manifest_sha256=previous,
        stage_started_monotonic_nanoseconds=(
            stage_started_monotonic_nanoseconds),
        observed_monotonic_nanoseconds=observed_monotonic_nanoseconds,
        cumulative_cpu_nanoseconds=cumulative_cpu_nanoseconds,
        exact_resume_count=exact_resume_count)
    manifest_raw = canonical_json_bytes(manifest)
    projected = sum(path.stat().st_size for entry in entries
                    for path in entry.iterdir()) \
        + len(state_raw) + len(curves_raw) + len(manifest_raw)
    if projected > binding.journal_byte_cap:
        raise BeliefV2EpochJournalError(
            "V2 epoch journal byte cap exceeded")
    partial = directory / f"{_epoch_name(epoch)}.partial"
    final = directory / _epoch_name(epoch)
    if final.exists() or final.is_symlink() \
            or partial.is_symlink():
        raise BeliefV2EpochJournalError(
            "V2 epoch journal append slot occupied")
    partial.mkdir(mode=0o700, exist_ok=True)
    _resume_or_publish_bytes(partial / STATE_FILENAME, state_raw)
    _resume_or_publish_bytes(partial / CURVES_FILENAME, curves_raw)
    _resume_or_publish_bytes(partial / MANIFEST_FILENAME, manifest_raw)
    os.rename(partial, final)
    _fsync_directory(directory)
    return manifest


def _reopen_curves(raw: bytes) -> tuple[V2TrainingEpochCurveRowV1, ...]:
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BeliefV2EpochJournalError(
            "V2 epoch journal curves are not JSON") from exc
    if type(payload) is not dict or set(payload) != {
            "schema", "epoch_count", "epochs"} \
            or canonical_json_bytes(payload) != raw \
            or payload["schema"] != EPOCH_CURVES_SCHEMA \
            or type(payload["epochs"]) is not list \
            or payload["epoch_count"] != len(payload["epochs"]):
        raise BeliefV2EpochJournalError(
            "V2 epoch journal curve identity drift")
    result = []
    for epoch, row in enumerate(payload["epochs"], 1):
        if type(row) is not dict or set(row) != {
                "schema", "epoch", "member_training_receipts",
                "member_calibration_loss_nanonats",
                "cohort_mean_calibration_loss_nanonats"} \
                or row["epoch"] != epoch \
                or type(row["member_training_receipts"]) is not list:
            raise BeliefV2EpochJournalError(
                "V2 epoch journal curve row drift")
        try:
            receipts = tuple(reopen_epoch_receipt(
                canonical_json_bytes(receipt))
                for receipt in row["member_training_receipts"])
        except ValueError as exc:
            raise BeliefV2EpochJournalError(
                "V2 epoch journal receipt refused") from exc
        losses = row["member_calibration_loss_nanonats"]
        if len(receipts) != len(COHORT_SEEDS) \
                or type(losses) is not list \
                or len(losses) != len(COHORT_SEEDS) \
                or any(type(value) is not int or value < 0
                       for value in losses) \
                or type(row["cohort_mean_calibration_loss_nanonats"]) \
                is not int \
                or row["cohort_mean_calibration_loss_nanonats"] \
                != sum(losses) // len(COHORT_SEEDS) \
                or any(receipt.epoch != epoch for receipt in receipts):
            raise BeliefV2EpochJournalError(
                "V2 epoch journal curve value drift")
        result.append(V2TrainingEpochCurveRowV1(
            epoch=epoch,
            member_training_receipts=receipts,
            member_calibration_loss_nanonats=tuple(
                row["member_calibration_loss_nanonats"]),
            cohort_mean_calibration_loss_nanonats=row[
                "cohort_mean_calibration_loss_nanonats"],
            schema=row["schema"]))
    return tuple(result)


_MANIFEST_KEYS = {
    "schema", "binding", "epoch", "previous_manifest_sha256",
    "selected_common_epoch", "stage_started_monotonic_nanoseconds",
    "observed_monotonic_nanoseconds", "cumulative_wall_nanoseconds",
    "cumulative_cpu_nanoseconds", "exact_resume_count",
    "current_model_state_sha256s", "selected_model_state_sha256s",
    "files", "contains_optimizer_resume_state",
    "mandatory_latest_epoch_resume",
    "operator_checkpoint_selection_authorized", "runtime_artifact",
    "calibration_open_authorized", "test_split_open_authorized",
    "sampler_implementation_authorized",
    "gameplay_strength_screen_authorized", "strength_claim_authorized",
    "deployment_authorized",
}


def _load_state_payload(raw: bytes) -> tuple[
        tuple[dict[str, torch.Tensor], ...],
        tuple[dict[str, Any], ...],
        tuple[dict[str, torch.Tensor], ...]]:
    try:
        payload = torch.load(
            io.BytesIO(raw), map_location="cpu", weights_only=True)
    except (RuntimeError, ValueError, EOFError) as exc:
        raise BeliefV2EpochJournalError(
            "V2 epoch journal state refused") from exc
    if type(payload) is not dict or set(payload) != {
            "current_model_states", "optimizer_states",
            "selected_model_states"}:
        raise BeliefV2EpochJournalError(
            "V2 epoch journal state population drift")
    current = tuple(payload["current_model_states"])
    optimizers = tuple(payload["optimizer_states"])
    selected = tuple(payload["selected_model_states"])
    if len(current) != len(COHORT_SEEDS) \
            or len(optimizers) != len(COHORT_SEEDS) \
            or len(selected) != len(COHORT_SEEDS) \
            or any(type(row) is not dict for row in (
                *current, *optimizers, *selected)):
        raise BeliefV2EpochJournalError(
            "V2 epoch journal member population drift")
    return current, optimizers, selected


def reopen_epoch_snapshots(
        directory: Path, binding: V2EpochJournalBindingV1) \
        -> tuple[V2ReopenedEpochSnapshotV1, ...]:
    """Reopen and authenticate every durable epoch without mutating it."""
    _validate_binding(binding)
    if not directory.exists():
        return ()
    entries = _journal_entries(directory)
    if not entries:
        return ()
    previous = None
    stage_started = None
    prior_observed = None
    prior_cpu = None
    prior_resume_count = None
    prior_curves = None
    total_bytes = 0
    snapshots = []
    for epoch, entry in enumerate(entries, 1):
        if entry.is_symlink() or not entry.is_dir() \
                or {path.name for path in entry.iterdir()} != {
                    STATE_FILENAME, CURVES_FILENAME, MANIFEST_FILENAME}:
            raise BeliefV2EpochJournalError(
                "V2 epoch journal file population drift")
        manifest_raw = stable_read_bytes(entry / MANIFEST_FILENAME)
        try:
            manifest = json.loads(manifest_raw)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BeliefV2EpochJournalError(
                "V2 epoch journal manifest is not JSON") from exc
        state_raw = stable_read_bytes(entry / STATE_FILENAME)
        curves_raw = stable_read_bytes(entry / CURVES_FILENAME)
        total_bytes += len(manifest_raw) + len(state_raw) + len(curves_raw)
        files = manifest.get("files") if type(manifest) is dict else None
        if type(manifest) is not dict or set(manifest) != _MANIFEST_KEYS \
                or canonical_json_bytes(manifest) != manifest_raw \
                or manifest.get("schema") != EPOCH_JOURNAL_SCHEMA \
                or manifest.get("binding") != binding.to_dict() \
                or manifest.get("epoch") != epoch \
                or manifest.get("previous_manifest_sha256") != previous \
                or type(manifest.get(
                    "stage_started_monotonic_nanoseconds")) is not int \
                or type(manifest.get(
                    "observed_monotonic_nanoseconds")) is not int \
                or type(manifest.get(
                    "cumulative_wall_nanoseconds")) is not int \
                or type(manifest.get(
                    "cumulative_cpu_nanoseconds")) is not int \
                or manifest["cumulative_cpu_nanoseconds"] < 0 \
                or type(manifest.get("exact_resume_count")) is not int \
                or manifest["exact_resume_count"] < 0 \
                or (epoch == 1 and manifest["exact_resume_count"] != 0) \
                or not 0 < manifest[
                    "stage_started_monotonic_nanoseconds"] \
                < manifest["observed_monotonic_nanoseconds"] \
                or manifest["cumulative_wall_nanoseconds"] != (
                    manifest["observed_monotonic_nanoseconds"]
                    - manifest["stage_started_monotonic_nanoseconds"]) \
                or (stage_started is not None and manifest[
                    "stage_started_monotonic_nanoseconds"] != stage_started) \
                or (prior_observed is not None and manifest[
                    "observed_monotonic_nanoseconds"] <= prior_observed) \
                or (prior_cpu is not None and manifest[
                    "cumulative_cpu_nanoseconds"] < prior_cpu) \
                or (prior_resume_count is not None and not (
                    prior_resume_count <= manifest["exact_resume_count"]
                    <= prior_resume_count + 1)) \
                or type(manifest.get("current_model_state_sha256s")) \
                is not list \
                or type(manifest.get("selected_model_state_sha256s")) \
                is not list \
                or any(not _is_sha256(value) for value in (
                    *manifest["current_model_state_sha256s"],
                    *manifest["selected_model_state_sha256s"])) \
                or type(files) is not dict or set(files) != {
                    STATE_FILENAME, CURVES_FILENAME} \
                or any(type(files[name]) is not dict
                       or set(files[name]) != {"byte_count", "sha256"}
                       or files[name]["byte_count"] != len(raw)
                       or files[name]["sha256"] != _sha256(raw)
                       for name, raw in ((STATE_FILENAME, state_raw),
                                         (CURVES_FILENAME, curves_raw))) \
                or manifest.get("contains_optimizer_resume_state") \
                is not True \
                or manifest.get("mandatory_latest_epoch_resume") \
                is not True \
                or any(manifest.get(key) is not False for key in (
                    "operator_checkpoint_selection_authorized",
                    "runtime_artifact", "calibration_open_authorized",
                    "test_split_open_authorized",
                    "sampler_implementation_authorized",
                    "gameplay_strength_screen_authorized",
                    "strength_claim_authorized", "deployment_authorized")):
            raise BeliefV2EpochJournalError(
                "V2 epoch journal manifest chain drift")
        curves = _reopen_curves(curves_raw)
        current_states, optimizer_states, selected_states = (
            _load_state_payload(state_raw))
        if len(curves) != epoch \
                or (prior_curves is not None
                    and curves[:-1] != prior_curves):
            raise BeliefV2EpochJournalError(
                "V2 epoch journal curve chain drift")
        losses = tuple(tuple(
            curve.member_calibration_loss_nanonats[index]
            for curve in curves) for index in range(len(COHORT_SEEDS)))
        decision = select_common_epoch(losses)
        current_hashes = _model_hashes(current_states)
        selected_hashes = _model_hashes(selected_states)
        if decision.stop_epoch != epoch \
                or manifest["selected_common_epoch"] \
                != decision.selected_epoch \
                or manifest["current_model_state_sha256s"] \
                != list(current_hashes) \
                or manifest["selected_model_state_sha256s"] \
                != list(selected_hashes) \
                or current_hashes != tuple(
                    receipt.model_state_sha256_after
                    for receipt in curves[-1].member_training_receipts) \
                or selected_hashes != tuple(
                    receipt.model_state_sha256_after for receipt in curves[
                        decision.selected_epoch - 1].member_training_receipts):
            raise BeliefV2EpochJournalError(
                "V2 epoch journal recovered trajectory drift")
        snapshots.append(V2ReopenedEpochSnapshotV1(
            epoch=epoch, manifest=manifest, curves=curves,
            current_model_states=current_states,
            optimizer_states=optimizer_states,
            selected_model_states=selected_states))
        stage_started = manifest["stage_started_monotonic_nanoseconds"]
        prior_observed = manifest["observed_monotonic_nanoseconds"]
        prior_cpu = manifest["cumulative_cpu_nanoseconds"]
        prior_resume_count = manifest["exact_resume_count"]
        prior_curves = curves
        previous = _sha256(manifest_raw)
    if total_bytes > binding.journal_byte_cap:
        raise BeliefV2EpochJournalError(
            "V2 epoch journal byte cap exceeded")
    return tuple(snapshots)


def reopen_latest_epoch_resume(
        directory: Path, binding: V2EpochJournalBindingV1) \
        -> tuple[V2CohortResumeStateV1, dict[str, Any]] | None:
    """Reopen only the mandatory highest contiguous epoch."""
    snapshots = reopen_epoch_snapshots(directory, binding)
    if not snapshots:
        return None
    latest = snapshots[-1]
    curves = latest.curves
    models = []
    optimizers = []
    for seed, model_state, optimizer_state in zip(
            COHORT_SEEDS, latest.current_model_states,
            latest.optimizer_states, strict=True):
        model = new_from_scratch_model(seed)
        optimizer = new_v2_optimizer(model)
        try:
            model.load_state_dict(model_state, strict=True)
            optimizer.load_state_dict(optimizer_state)
        except (RuntimeError, ValueError) as exc:
            raise BeliefV2EpochJournalError(
                "V2 epoch journal live state refused") from exc
        models.append(model)
        optimizers.append(optimizer)
    losses = tuple(tuple(curve.member_calibration_loss_nanonats[index]
                         for curve in curves)
                   for index in range(len(COHORT_SEEDS)))
    decision = select_common_epoch(losses)
    selected_receipts = curves[
        decision.selected_epoch - 1].member_training_receipts
    result = V2CohortResumeStateV1(
        models=tuple(models), optimizers=tuple(optimizers), epochs=curves,
        selected_states=latest.selected_model_states,
        selected_receipts=selected_receipts)
    if latest.manifest["selected_common_epoch"] != decision.selected_epoch \
            or latest.manifest["current_model_state_sha256s"] \
            != [portable_model_state_sha256(model) for model in models]:
        raise BeliefV2EpochJournalError(
            "V2 epoch journal recovered trajectory drift")
    return result, latest.manifest


def reopen_latest_epoch_resume_state(
        directory: Path, binding: V2EpochJournalBindingV1) \
        -> V2CohortResumeStateV1 | None:
    reopened = reopen_latest_epoch_resume(directory, binding)
    return None if reopened is None else reopened[0]
