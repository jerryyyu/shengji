"""Durable controller and score-free capacity census for PT-Luna.

The engine and process-boundary modules deliberately do not own population
admission.  This module is the small orchestration layer that does: it opens a
sealed root census and capacity receipt before an acquisition call, reopens
each attempt immediately, and writes one append-only population report.  A
failed attempt is retained by identity; it is never replaced by a fabricated
trajectory or retried.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import base64
import ctypes
from dataclasses import dataclass
import errno
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import threading
import tempfile
import time
from typing import Callable, Mapping, Sequence

from . import privileged_teacher_luna_selfplay as luna
from . import privileged_teacher_luna_selfplay_execution as execution
from .privileged_teacher_pt0 import canonical_json_bytes


CONTROLLER_SCHEMA = "privileged-teacher-luna-selfplay-controller-v1"
CAPACITY_SCHEMA = "privileged-teacher-luna-selfplay-capacity-v2"
CAPACITY_ARM_SCHEMA = "privileged-teacher-luna-selfplay-capacity-arm-v2"
POPULATION_REPORT_SCHEMA = "privileged-teacher-luna-selfplay-population-report-v1"
POPULATION_ADMISSION_SCHEMA = "privileged-teacher-luna-selfplay-population-admission-v1"
LAUNCH_FREEZE_SCHEMA = "privileged-teacher-luna-selfplay-launch-freeze-v1"
REVIEW_MARKER_SCHEMA = "privileged-teacher-luna-selfplay-source-review-v1"
REVIEW_MARKER_PREFIX = "PT_LUNA_SELFPLAY_SOURCE_REVIEW_V1 "
CANONICAL_REMOTE_URL = "https://github.com/jerryyyu/shengji.git"
CANONICAL_REMOTE_REF = "refs/heads/main"
CAPACITY_ROUTE = "CAPACITY_PASS"
CAPACITY_REFUSE_ROUTE = "REFUSE_RESOURCE_OR_PROVIDER"
CAPACITY_WORKERS = (1, 2, 4, 6, 8)
PHYSICAL_RSS_NUM = 85
SCALING_NUM = 70
HEADROOM_NUM = 25
DEFAULT_WALL_BUDGET_NANOSECONDS = 1 << 62
DEFAULT_TOKEN_BUDGET = 1 << 62
CAPACITY_EXECUTION_SYNTHETIC = "synthetic-injected-capacity"
CAPACITY_EXECUTION_VERIFIED = "verified-runtime-capacity"
CAPACITY_PROVENANCE_SCHEMA = "privileged-teacher-luna-selfplay-capacity-provenance-v1"
CAPACITY_FAILURE_SCHEMA = "privileged-teacher-luna-selfplay-capacity-failure-v3"
_REVIEW_AUTHENTICATION = object()

# Capacity refusals may expose only controller-owned classifications.  Keep
# this list frozen: arbitrary exception text is private process/model output.
_CAPACITY_PROCESS_ERRORS = frozenset({
    "Luna model process exceeded wall deadline",
    "Luna model process did not complete engine round",
    "Luna model process absent",
    "Luna model output too large",
    "Codex JSONL output drift",
    "Codex JSONL output absent",
    "Codex JSONL event drift",
    "Codex completion telemetry drift",
    "Codex token telemetry drift",
    "Luna model final response absent or malformed",
    "Luna terminal mailbox witness absent or malformed",
})
_CAPACITY_PROCESS_ERROR_OTHER = "other"
_CAPACITY_OP_OTHER = "other"
_CAPACITY_CODEX_OPAQUE = "opaque"
_CAPACITY_TRACE_OPERATIONS = frozenset({"observe", "wait", "rollout", "play"})
# The names are the bounded Codex event vocabulary; unknown type strings are
# collapsed so model prose cannot enter the public artifact as an event key.
_CAPACITY_CODEX_EVENT_TYPES = frozenset({
    "thread.started", "thread.completed", "thread.failed",
    "turn.started", "turn.completed", "turn.failed",
    "item.started", "item.updated", "item.completed",
    "response.created", "response.completed", "response.failed",
    "response.output_text.delta", "response.output_item.added",
    "response.output_item.done", "error",
})
# These are metadata values emitted in Codex ``item`` objects.  They are
# deliberately narrower than the full event payload: only these names can
# cross the capacity-refusal boundary, and every future/unknown value is
# collapsed to ``opaque``.
_CAPACITY_CODEX_ITEM_TYPES = frozenset({
    "agent_message", "command_execution", "file_change", "mcp_tool_call",
    "reasoning", "todo_list", "web_search", "error", "user_message",
})
_CAPACITY_CODEX_ITEM_STATUSES = frozenset({
    "completed", "declined", "failed", "in_progress", "interrupted",
    "pending", "started", "updated",
})
_CAPACITY_FAILURE_KEYS = frozenset({
    "schema", "failure_kind", "coordinate", "workers", "worker", "game",
    "reopened_status", "evidence_count", "expected_team_count",
    "evidence_classification", "scientific_admissible",
    "collection_authorized", "opened", "retained", "authority",
})
_CAPACITY_CLASSIFICATION_KEYS = frozenset({
    "team", "execution_kind", "actual_subprocess", "synthetic",
    "process_error_present", "process_returncode", "process_error",
    "codex_event_type_counts", "codex_item_type_counts",
    "codex_item_status_counts", "final_output_present",
    "trace_operation_counts", "stdout_sha256", "output_sha256",
})
_CAPACITY_PROCESS_DIAGNOSTIC_KEYS = frozenset({
    "process_returncode", "process_error", "codex_event_type_counts",
    "codex_item_type_counts", "codex_item_status_counts", "final_output_present",
    "trace_operation_counts", "stdout_sha256", "output_sha256",
})


def _capacity_digest(value: object) -> str | None:
    if (type(value) is str and len(value) == 64
            and all(char in "0123456789abcdef" for char in value)):
        return value
    return None


def _capacity_b64(body: Mapping[str, object], key: str) -> bytes | None:
    value = body.get(key)
    if type(value) is not str:
        return None
    try:
        return base64.b64decode(value, validate=True)
    except (ValueError, TypeError):
        return None


def _capacity_codex_telemetry(
        raw: bytes | None) -> tuple[dict[str, int], dict[str, int], dict[str, int]]:
    """Extract allowlisted Codex metadata without retaining event payloads.

    The parser intentionally treats the JSONL as all-or-nothing.  A malformed
    line, or an event with a malformed type, makes every derived field opaque;
    this avoids presenting a partial and potentially misleading public
    diagnostic.  Item metadata is read only from ``item.type`` and
    ``item.status``; commands, text, ids, and all other payload fields are
    never copied.
    """
    opaque = ({_CAPACITY_CODEX_OPAQUE: 1},
              {_CAPACITY_CODEX_OPAQUE: 1},
              {_CAPACITY_CODEX_OPAQUE: 1})
    if raw is None:
        return opaque
    event_counts: dict[str, int] = {}
    item_type_counts: dict[str, int] = {}
    item_status_counts: dict[str, int] = {}
    lines = raw.splitlines()
    if not lines:
        return opaque
    try:
        for line in lines:
            if not line:
                continue
            event = json.loads(line.decode("utf-8"))
            if type(event) is not dict or type(event.get("type")) is not str:
                return opaque
            event_type = event["type"]
            key = (event_type if event_type in _CAPACITY_CODEX_EVENT_TYPES
                   else _CAPACITY_CODEX_OPAQUE)
            event_counts[key] = event_counts.get(key, 0) + 1

            # Codex item events carry a metadata object under ``item``.  A
            # missing/malformed item on an item event is itself opaque, while
            # non-item events without an item contribute no item count.
            if event_type.startswith("item."):
                item = event.get("item")
                if type(item) is not dict:
                    item_type_counts[_CAPACITY_CODEX_OPAQUE] = (
                        item_type_counts.get(_CAPACITY_CODEX_OPAQUE, 0) + 1)
                    item_status_counts[_CAPACITY_CODEX_OPAQUE] = (
                        item_status_counts.get(_CAPACITY_CODEX_OPAQUE, 0) + 1)
                    continue
                item_type = item.get("type")
                item_type_key = (
                    item_type if (type(item_type) is str
                                  and item_type in _CAPACITY_CODEX_ITEM_TYPES)
                    else _CAPACITY_CODEX_OPAQUE)
                item_type_counts[item_type_key] = (
                    item_type_counts.get(item_type_key, 0) + 1)
                item_status = item.get("status")
                # Current Codex JSONL commonly encodes item status in the
                # event suffix (item.started/item.completed), while some
                # providers also include item.status.  Prefer explicit item
                # metadata and use the allowlisted suffix as a fallback.
                if item_status is None:
                    suffix = event_type.removeprefix("item.")
                    if suffix in _CAPACITY_CODEX_ITEM_STATUSES:
                        item_status = suffix
                item_status_key = (
                    item_status if (type(item_status) is str
                                    and item_status in _CAPACITY_CODEX_ITEM_STATUSES)
                    else _CAPACITY_CODEX_OPAQUE)
                item_status_counts[item_status_key] = (
                    item_status_counts.get(item_status_key, 0) + 1)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return opaque
    if not event_counts:
        return opaque
    return ({key: event_counts[key] for key in sorted(event_counts)},
            {key: item_type_counts[key] for key in sorted(item_type_counts)}
            or {_CAPACITY_CODEX_OPAQUE: 1},
            {key: item_status_counts[key] for key in sorted(item_status_counts)}
            or {_CAPACITY_CODEX_OPAQUE: 1})


def _capacity_codex_events(raw: bytes | None) -> dict[str, int]:
    """Return bounded event names, never event payloads, from private stdout."""
    return _capacity_codex_telemetry(raw)[0]


def _capacity_trace_operations(body: Mapping[str, object]) -> dict[str, int]:
    """Count only the known operation names from the private trace."""
    trace = body.get("trace")
    if type(trace) is not list:
        return {_CAPACITY_OP_OTHER: 1}
    counts: dict[str, int] = {}
    for event in trace:
        operation = None
        if type(event) is dict and isinstance(event.get("request"), Mapping):
            candidate = event["request"].get("op")
            if type(candidate) is str:
                operation = candidate if candidate in _CAPACITY_TRACE_OPERATIONS \
                    else _CAPACITY_OP_OTHER
        else:
            operation = _CAPACITY_OP_OTHER
        if operation is not None:
            counts[operation] = counts.get(operation, 0) + 1
    return {key: counts[key] for key in sorted(counts)}


def _capacity_process_diagnostic(body: Mapping[str, object]) -> dict[str, object]:
    stdout = _capacity_b64(body, "stdout_base64")
    final = _capacity_b64(body, "final_base64")
    event_types, item_types, item_statuses = _capacity_codex_telemetry(stdout)
    returncode = body.get("process_returncode")
    if isinstance(returncode, bool) or not isinstance(returncode, int):
        returncode = None
    process_error = body.get("process_error")
    if (process_error is not None
            and (type(process_error) is not str
                 or process_error not in _CAPACITY_PROCESS_ERRORS)):
        process_error = _CAPACITY_PROCESS_ERROR_OTHER
    output_sha256 = _capacity_digest(body.get("output_sha256"))
    return {
        "process_returncode": returncode,
        "process_error": process_error,
        "codex_event_type_counts": event_types,
        "codex_item_type_counts": item_types,
        "codex_item_status_counts": item_statuses,
        "final_output_present": bool(final),
        "trace_operation_counts": _capacity_trace_operations(body),
        "stdout_sha256": (_sha_bytes(stdout) if stdout is not None else None),
        "output_sha256": output_sha256,
    }


def _validate_capacity_failure_body(body: Mapping[str, object]) -> None:
    """Keep the immutable public refusal artifact closed and type-safe."""
    if type(body) is not dict or set(body) != _CAPACITY_FAILURE_KEYS:
        raise ControllerError("capacity failure schema drift")
    if body["schema"] != CAPACITY_FAILURE_SCHEMA \
            or type(body["failure_kind"]) is not str \
            or not body["failure_kind"]:
        raise ControllerError("capacity failure identity drift")
    coordinate = body["coordinate"]
    if (type(coordinate) is not list or len(coordinate) != 3
            or type(coordinate[0]) is not str
            or type(coordinate[1]) is not int
            or isinstance(coordinate[1], bool)
            or type(coordinate[2]) is not int
            or isinstance(coordinate[2], bool)):
        raise ControllerError("capacity failure coordinate drift")
    for key in ("workers", "worker", "game", "evidence_count",
                "expected_team_count"):
        if isinstance(body[key], bool) or not isinstance(body[key], int) \
                or body[key] < 0 or (key == "workers" and body[key] == 0):
            raise ControllerError("capacity failure count drift")
    if body["worker"] >= body["workers"] or type(body["game"]) is not int:
        raise ControllerError("capacity failure identity drift")
    if body["reopened_status"] is not None \
            and type(body["reopened_status"]) is not str:
        raise ControllerError("capacity failure status drift")
    for key in ("scientific_admissible", "collection_authorized"):
        if type(body[key]) is not bool or body[key]:
            raise ControllerError("capacity failure authority drift")
    for key in ("opened", "retained"):
        value = body[key]
        if (type(value) is not dict
                or set(value) != {"outcomes", "actions", "trajectories",
                                  "model_prose"}
                or any(type(item) is not bool or item for item in value.values())):
            raise ControllerError("capacity failure privacy drift")
    if body["authority"] != luna.AUTHORITY \
            or type(body["authority"]) is not dict \
            or any(type(value) is not bool or value
                   for value in body["authority"].values()):
        raise ControllerError("capacity failure authority drift")
    classifications = body["evidence_classification"]
    if (type(classifications) is not list
            or body["evidence_count"] != len(classifications)
            or body["expected_team_count"] != len(luna.TEAMS)):
        raise ControllerError("capacity failure classification drift")
    for item in classifications:
        if type(item) is not dict or set(item) != _CAPACITY_CLASSIFICATION_KEYS:
            raise ControllerError("capacity failure classification schema drift")
        if (item["team"] is not None
                and (isinstance(item["team"], bool)
                     or not isinstance(item["team"], int))):
            raise ControllerError("capacity failure team drift")
        if item["execution_kind"] not in (
                None, execution.PRODUCTION_EXECUTION_KIND,
                execution.SYNTHETIC_EXECUTION_KIND):
            raise ControllerError("capacity failure execution drift")
        for key in ("actual_subprocess", "synthetic", "process_error_present"):
            if type(item[key]) is not bool:
                raise ControllerError("capacity failure classification type drift")
        diagnostic = {key: item[key]
                      for key in _CAPACITY_PROCESS_DIAGNOSTIC_KEYS}
        returncode = diagnostic["process_returncode"]
        if (returncode is not None
                and (isinstance(returncode, bool) or not isinstance(returncode, int))):
            raise ControllerError("capacity failure returncode drift")
        process_error = diagnostic["process_error"]
        if (process_error is not None
                and (type(process_error) is not str
                     or process_error not in _CAPACITY_PROCESS_ERRORS)
                and process_error != _CAPACITY_PROCESS_ERROR_OTHER):
            raise ControllerError("capacity failure process error drift")
        for counts_key, allowed in (
                ("codex_event_type_counts",
                 _CAPACITY_CODEX_EVENT_TYPES | {_CAPACITY_CODEX_OPAQUE}),
                ("codex_item_type_counts",
                 _CAPACITY_CODEX_ITEM_TYPES | {_CAPACITY_CODEX_OPAQUE}),
                ("codex_item_status_counts",
                 _CAPACITY_CODEX_ITEM_STATUSES | {_CAPACITY_CODEX_OPAQUE}),
                ("trace_operation_counts",
                 _CAPACITY_TRACE_OPERATIONS | {_CAPACITY_OP_OTHER})):
            counts = diagnostic[counts_key]
            if (type(counts) is not dict
                    or any(type(key) is not str or key not in allowed
                           or isinstance(value, bool)
                           or not isinstance(value, int) or value < 0
                           for key, value in counts.items())):
                raise ControllerError("capacity failure count schema drift")
        if type(diagnostic["final_output_present"]) is not bool:
            raise ControllerError("capacity failure final output drift")
        for key in ("stdout_sha256", "output_sha256"):
            if (diagnostic[key] is not None
                    and _capacity_digest(diagnostic[key]) is None):
                raise ControllerError("capacity failure hash drift")

# Complete static local-Python import closure rooted at the collection CLI,
# controller, execution adapter, and game implementation.  Keep this explicit:
# an added local dependency is a reviewed source-boundary change, not something
# a runtime import walk may silently admit after the marker was written.
SOURCE_CLOSURE = (
    "scripts/privileged_teacher_luna_selfplay.py",
    "shengji/__init__.py",
    "shengji/ai/__init__.py",
    "shengji/ai/bury.py",
    "shengji/ai/endgame.py",
    "shengji/ai/heuristic.py",
    "shengji/ai/legacy_b3f8f61/__init__.py",
    "shengji/ai/legacy_b3f8f61/mcbot.py",
    "shengji/ai/legacy_b3f8f61/memory.py",
    "shengji/ai/mcbot.py",
    "shengji/ai/memory.py",
    "shengji/ai/registry.py",
    "shengji/ai/smart.py",
    "shengji/engine/__init__.py",
    "shengji/engine/ballot.py",
    "shengji/engine/cards.py",
    "shengji/engine/combos.py",
    "shengji/engine/fast.py",
    "shengji/engine/legal.py",
    "shengji/engine/round.py",
    "shengji/rl/__init__.py",
    "shengji/rl/actions.py",
    "shengji/rl/encode.py",
    "shengji/rl/model.py",
    "shengji/rl/npnet.py",
    "shengji/rl/privileged_teacher_c0.py",
    "shengji/rl/privileged_teacher_full_ab.py",
    "shengji/rl/privileged_teacher_luna_selfplay.py",
    "shengji/rl/privileged_teacher_luna_selfplay_controller.py",
    "shengji/rl/privileged_teacher_luna_selfplay_execution.py",
    "shengji/rl/privileged_teacher_pt0.py",
    "shengji/rl/privileged_teacher_pt1.py",
    "shengji/rl/privileged_teacher_sol0.py",
    "shengji/rl/provenance.py",
    "shengji/rl/torch_policy.py",
)


class ControllerError(ValueError):
    """A sealed controller input, artifact, or route is invalid."""


class SourceAdmissionError(ControllerError):
    """A structurally valid attempt is not admissible scientific evidence."""


class CapacityEvidenceRefusal(ControllerError):
    """A real capacity game was not admissible as verified evidence."""

    def __init__(self, *, coordinate: tuple[str, int, int], workers: int,
                 worker: int, game: int, reopened_status: str | None,
                 evidence: Sequence[object], failure_kind: str = "evidence"):
        classifications: list[dict[str, object]] = []
        for item in evidence:
            body = getattr(item, "body", {})
            if not isinstance(body, Mapping):
                body = {}
            execution_kind = body.get("execution_kind")
            if execution_kind not in (execution.PRODUCTION_EXECUTION_KIND,
                                      execution.SYNTHETIC_EXECUTION_KIND):
                execution_kind = None
            team = getattr(item, "team", None)
            diagnostic = _capacity_process_diagnostic(body)
            classifications.append({
                "team": team if isinstance(team, int) and not isinstance(team, bool)
                else None,
                "execution_kind": execution_kind,
                "actual_subprocess": body.get("actual_subprocess") is True,
                "synthetic": body.get("synthetic") is True,
                "process_error_present": body.get("process_error") is not None,
                **diagnostic,
            })
        body = {
            "schema": CAPACITY_FAILURE_SCHEMA,
            "failure_kind": failure_kind,
            "coordinate": list(coordinate),
            "workers": workers,
            "worker": worker,
            "game": game,
            "reopened_status": reopened_status,
            "evidence_count": len(evidence),
            "expected_team_count": len(luna.TEAMS),
            "evidence_classification": classifications,
            "scientific_admissible": False,
            "collection_authorized": False,
            "opened": {"outcomes": False, "actions": False,
                        "trajectories": False, "model_prose": False},
            "retained": {"outcomes": False, "actions": False,
                          "trajectories": False, "model_prose": False},
            "authority": {key: False for key in luna.AUTHORITY},
        }
        _validate_capacity_failure_body(body)
        self.body = body
        self.payload = {**body, "diagnostic_sha256": _sha(body)}
        super().__init__("capacity requires verified subprocess evidence")

    def serialized(self) -> dict[str, object]:
        return dict(self.payload)

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.payload)


@dataclass(frozen=True)
class _AuthenticatedSourceReview:
    """Process-local authority transition produced by external review.

    The marker and its claim remain serialized for audit, but this object is
    deliberately not JSON serializable and can only be minted by
    ``authenticate_source_review``.  A receipt/freeze copied from disk thus
    cannot carry scientific admission authority by itself.
    """

    review_commit: str
    review_marker_sha256: str
    review_claim: Mapping[str, object]
    _token: object

    def __post_init__(self) -> None:
        if self._token is not _REVIEW_AUTHENTICATION:
            raise ControllerError("source review authentication token drift")

    def __getitem__(self, key: str) -> object:
        if key == "review_commit":
            return self.review_commit
        if key == "review_marker_sha256":
            return self.review_marker_sha256
        if key == "review_claim":
            return self.review_claim
        raise KeyError(key)


def _require_pure_python_runtime() -> None:
    """PT-Luna V1 deliberately refuses the unbound compiled fast path."""
    fast = sys.modules.get("shengji.engine.fast")
    if os.environ.get("SHENGJI_FAST") == "1" \
            or (fast is not None and bool(getattr(fast, "_saved", {}))):
        raise ControllerError("PT-Luna source review requires pure Python engine")


def _source_manifest() -> dict[str, str]:
    """Return the exact reviewed local source closure and refuse drift."""
    _require_pure_python_runtime()
    root = Path(__file__).resolve().parents[2]
    paths = tuple(root / relative for relative in SOURCE_CLOSURE)
    if len(set(SOURCE_CLOSURE)) != len(SOURCE_CLOSURE) or any(
            not path.is_file() or path.is_symlink() for path in paths):
        raise ControllerError("PT-Luna source closure drift")
    return {relative: _sha_bytes(path.read_bytes())
            for relative, path in zip(SOURCE_CLOSURE, paths, strict=True)}


def _source_sha256() -> str:
    """Hash the complete local source boundary, not mutable Git refs."""
    # The externally reviewed mailbox tool is bound separately in the freeze
    # and review claim because it is an executable artifact, not an import.
    return _sha(_source_manifest())


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _strict_sha(value: object, label: str) -> str:
    if (type(value) is not str or len(value) != 64
            or any(c not in "0123456789abcdef" for c in value)):
        raise ControllerError(f"{label} drift")
    return value


def _positive_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ControllerError(f"{label} drift")
    return value


def _nonnegative_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ControllerError(f"{label} drift")
    return value


def _publish(path: Path, body: Mapping[str, object], *, suffix: str) -> str:
    """Publish one canonical immutable record without replacing an existing one."""
    path = Path(path)
    if path.exists() or path.is_symlink():
        raise ControllerError(f"{suffix} slot occupied")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    raw_body = canonical_json_bytes(dict(body))
    payload = {**dict(body), suffix: _sha(dict(body))}
    raw = canonical_json_bytes(payload)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                 getattr(os, "O_NOFOLLOW", 0), 0o400)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        parent_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
    except BaseException:
        raise
    del raw_body
    return _sha_bytes(raw)


def _read_canonical(path: Path, *, limit: int = 64 << 20) -> dict[str, object]:
    try:
        raw = Path(path).read_bytes()
        payload = json.loads(raw.decode("ascii"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ControllerError("sealed record read refused") from exc
    if type(payload) is not dict or canonical_json_bytes(payload) != raw:
        raise ControllerError("sealed record canonical drift")
    if len(raw) > limit:
        raise ControllerError("sealed record too large")
    return payload


def _rename_noreplace(source: Path, destination: Path) -> None:
    """Atomically install ``source`` without ever replacing ``destination``."""
    library = ctypes.CDLL(None, use_errno=True)
    source_raw = os.fsencode(source)
    destination_raw = os.fsencode(destination)
    try:
        if sys.platform.startswith("linux"):
            operation = library.renameat2
            operation.argtypes = (ctypes.c_int, ctypes.c_char_p,
                                  ctypes.c_int, ctypes.c_char_p,
                                  ctypes.c_uint)
            operation.restype = ctypes.c_int
            result = operation(-100, source_raw, -100, destination_raw, 1)
        elif sys.platform == "darwin":
            operation = library.renamex_np
            operation.argtypes = (ctypes.c_char_p, ctypes.c_char_p,
                                  ctypes.c_uint)
            operation.restype = ctypes.c_int
            result = operation(source_raw, destination_raw, 0x00000004)
        else:
            raise ControllerError(
                "atomic no-replace publication is unavailable")
    except AttributeError as exc:
        raise ControllerError(
            "atomic no-replace publication is unavailable") from exc
    if result == 0:
        return
    error = ctypes.get_errno()
    if error in (errno.EEXIST, errno.ENOTEMPTY):
        raise FileExistsError(error, os.strerror(error), destination)
    raise OSError(error, os.strerror(error), destination)


def publish_capacity_failure(path: Path,
                             refusal: CapacityEvidenceRefusal) -> str:
    """Publish one redacted capacity refusal, accepting only an identical race."""
    if not isinstance(refusal, CapacityEvidenceRefusal):
        raise ControllerError("capacity failure diagnostic type drift")
    path = Path(path)
    raw = refusal.canonical_bytes()
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor: int | None = None
    temporary: Path | None = None

    def existing_matches() -> bool:
        try:
            existing_fd = os.open(path, os.O_RDONLY |
                                  getattr(os, "O_NOFOLLOW", 0))
            try:
                before = os.fstat(existing_fd)
                chunks: list[bytes] = []
                remaining = len(raw) + 1
                while remaining:
                    chunk = os.read(existing_fd, remaining)
                    if not chunk:
                        break
                    chunks.append(chunk)
                    remaining -= len(chunk)
                after = os.fstat(existing_fd)
            finally:
                os.close(existing_fd)
            path_info = path.lstat()
        except OSError as exc:
            raise ControllerError("capacity failure diagnostic slot occupied") from exc
        stable = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or stat.S_IMODE(before.st_mode) != 0o400
                or any(getattr(before, field) != getattr(after, field)
                       for field in stable)
                or before.st_dev != path_info.st_dev
                or before.st_ino != path_info.st_ino
                or b"".join(chunks) != raw):
            raise ControllerError("capacity failure diagnostic slot occupied")
        return True

    try:
        for attempt in range(100):
            temporary = path.parent / (
                f".{path.name}.{os.getpid()}.{threading.get_ident()}."
                f"{time.monotonic_ns()}.{attempt}.tmp")
            try:
                descriptor = os.open(
                    temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                    getattr(os, "O_NOFOLLOW", 0), 0o400)
                break
            except FileExistsError:
                temporary = None
        if descriptor is None or temporary is None:
            raise ControllerError("capacity failure temporary slot unavailable")
        offset = 0
        while offset < len(raw):
            written = os.write(descriptor, raw[offset:])
            if written <= 0:
                raise ControllerError(
                    "capacity failure diagnostic write made no progress")
            offset += written
        os.fsync(descriptor)
        descriptor_stat = os.fstat(descriptor)
        if (not stat.S_ISREG(descriptor_stat.st_mode)
                or descriptor_stat.st_nlink != 1
                or stat.S_IMODE(descriptor_stat.st_mode) != 0o400):
            raise ControllerError("capacity failure temporary identity drift")
        os.close(descriptor)
        descriptor = None
        try:
            _rename_noreplace(temporary, path)
        except FileExistsError:
            existing_matches()
            return _sha_bytes(raw)
        temporary = None
        existing_matches()
        parent_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(parent_fd)
        finally:
            os.close(parent_fd)
        return _sha_bytes(raw)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary is not None:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass


def _record_hash(payload: Mapping[str, object], field: str) -> str:
    if field not in payload:
        raise ControllerError(f"{field} absent")
    digest = payload[field]
    body = {key: value for key, value in payload.items() if key != field}
    if digest != _sha(body):
        raise ControllerError(f"{field} drift")
    return _strict_sha(digest, field)


def _capacity_game_keys(workers: int) -> tuple[tuple[int, int], ...]:
    return tuple((worker, game) for worker in range(workers) for game in range(2))


def _invoke_capacity_runner(game_runner: Callable[..., object], workers: int,
                            worker: int, game: int) -> object:
    """Call the frozen three-argument score-free seam."""
    return game_runner(workers, worker, game)


def _validate_capacity_provenance(value: object,
                                  *, execution_kind: str,
                                  scientific_admissible: bool) -> None:
    if type(value) is not dict or set(value) != {
            "schema", "execution_kind", "scientific_admissible",
            "runtime_sha256", "evidence_sha256", "tool_script_sha256",
            "games"}:
        raise ControllerError("capacity provenance schema drift")
    if value["schema"] != CAPACITY_PROVENANCE_SCHEMA \
            or value["execution_kind"] != execution_kind \
            or value["scientific_admissible"] is not scientific_admissible:
        raise ControllerError("capacity provenance identity drift")
    if execution_kind == CAPACITY_EXECUTION_SYNTHETIC:
        if value["runtime_sha256"] is not None \
                or value["evidence_sha256"] is not None \
                or value["tool_script_sha256"] is not None \
                or value["games"] != []:
            raise ControllerError("synthetic capacity provenance drift")
    else:
        for key in ("runtime_sha256", "evidence_sha256", "tool_script_sha256"):
            _strict_sha(value[key], f"capacity provenance {key}")
        games = value["games"]
        if type(games) is not list or not games:
            raise ControllerError("verified capacity evidence absent")
        game_keys = {"workers", "worker", "game", "runtime_sha256",
                     "evidence_sha256", "tool_script_sha256"}
        for game in games:
            if type(game) is not dict or set(game) != game_keys:
                raise ControllerError("verified capacity evidence schema drift")
            _positive_int(game["workers"], "capacity evidence workers")
            _nonnegative_int(game["worker"], "capacity evidence worker")
            _nonnegative_int(game["game"], "capacity evidence game")
            for key in ("runtime_sha256", "evidence_sha256", "tool_script_sha256"):
                _strict_sha(game[key], f"capacity evidence {key}")
        if value["runtime_sha256"] != _sha(
                [game["runtime_sha256"] for game in games]) \
                or value["evidence_sha256"] != _sha(
                    [game["evidence_sha256"] for game in games]) \
                or any(game["tool_script_sha256"] != value["tool_script_sha256"]
                       for game in games):
            raise ControllerError("verified capacity evidence binding drift")


@dataclass(frozen=True)
class CapacityMetric:
    """Only score-free process/resource telemetry is retained."""

    complete: bool
    verified: bool
    wall_nanoseconds: int
    busy_cpu_nanoseconds: int
    peak_rss_bytes: int
    swap_bytes: int
    process_errors: int
    tool_calls: int
    token_count: int
    token_rate_milli: int
    mechanics_sha256: str

    def __post_init__(self) -> None:
        if type(self.complete) is not bool:
            raise ControllerError("capacity completion drift")
        if type(self.verified) is not bool:
            raise ControllerError("capacity verification drift")
        for name in ("wall_nanoseconds", "busy_cpu_nanoseconds", "peak_rss_bytes",
                     "swap_bytes", "process_errors", "tool_calls",
                     "token_count", "token_rate_milli"):
            _nonnegative_int(getattr(self, name), f"capacity {name}")
        if self.wall_nanoseconds <= 0:
            raise ControllerError("capacity positive metric drift")
        _strict_sha(self.mechanics_sha256, "capacity mechanics SHA")

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> "CapacityMetric":
        expected = {"complete", "verified", "wall_nanoseconds", "busy_cpu_nanoseconds",
                    "peak_rss_bytes", "swap_bytes", "process_errors", "tool_calls",
                    "token_count", "token_rate_milli", "mechanics_sha256"}
        if type(value) is not dict or set(value) != expected:
            raise ControllerError("capacity metric schema drift")
        return cls(**value)

    def payload(self) -> dict[str, object]:
        return {"complete": self.complete, "verified": self.verified,
                "wall_nanoseconds": self.wall_nanoseconds,
                "busy_cpu_nanoseconds": self.busy_cpu_nanoseconds,
                "peak_rss_bytes": self.peak_rss_bytes,
                "swap_bytes": self.swap_bytes,
                "process_errors": self.process_errors,
                "tool_calls": self.tool_calls,
                "token_count": self.token_count,
                "token_rate_milli": self.token_rate_milli,
                "mechanics_sha256": self.mechanics_sha256}


def _p95(values: Sequence[int]) -> int:
    if not values:
        raise ControllerError("capacity p95 empty")
    ordered = sorted(values)
    # Nearest-rank p95 avoids introducing a floating-point measurement.
    index = max(0, (95 * len(ordered) + 99) // 100 - 1)
    return ordered[index]


def _arm_summary(workers: int, metrics: Sequence[CapacityMetric],
                 *, deadline_nanoseconds: int, physical_memory_bytes: int,
                 previous: Mapping[str, object] | None,
                 expected_mechanics_sha256: str | None = None,
                 arm_wall_span_nanoseconds: int | None = None,
                 cumulative_wall_nanoseconds: int | None = None,
                 cumulative_token_count: int | None = None,
                 cumulative_wall_budget_nanoseconds: int | None = None,
                 cumulative_token_budget: int | None = None) -> dict[str, object]:
    if len(metrics) != workers * 2:
        raise ControllerError("capacity arm game count drift")
    walls = [metric.wall_nanoseconds for metric in metrics]
    wall_span = (max(walls) if arm_wall_span_nanoseconds is None
                 else _positive_int(arm_wall_span_nanoseconds, "capacity arm wall"))
    p95_wall = _p95(walls)
    max_rss = max(metric.peak_rss_bytes for metric in metrics)
    # Per-game meters sample disjoint process groups.  Summing their measured
    # peaks is a conservative composed upper bound for a concurrent arm; using
    # max() would silently budget only one game on an 8-game arm.
    aggregate_peak_rss = sum(sorted(
        (metric.peak_rss_bytes for metric in metrics), reverse=True)[:workers])
    swaps = sum(metric.swap_bytes for metric in metrics)
    completed_games = sum(metric.complete for metric in metrics)
    complete = completed_games == workers * 2
    verified_games = sum(metric.verified for metric in metrics)
    verified = verified_games == workers * 2
    process_errors = sum(metric.process_errors for metric in metrics)
    mechanics = {metric.mechanics_sha256 for metric in metrics}
    mechanics_passed = (len(mechanics) == 1
                        and (expected_mechanics_sha256 is None
                             or next(iter(mechanics)) == expected_mechanics_sha256))
    rss_passed = (aggregate_peak_rss * 100
                  <= physical_memory_bytes * PHYSICAL_RSS_NUM)
    deadline_passed = p95_wall * 100 <= deadline_nanoseconds * (100 - HEADROOM_NUM)
    # There are two games per worker.  Token telemetry remains a bounded
    # resource gate, but it is not a provider-capacity assertion.
    aggregate_token_rate = sum(sorted(
        (metric.token_rate_milli for metric in metrics), reverse=True)[:workers])
    observed_parallelism_milli = (sum(metric.wall_nanoseconds for metric in metrics
                                       if metric.complete) * 1000 // wall_span)
    parallelism_passed = (complete and verified and process_errors == 0
                          and observed_parallelism_milli >= 700 * workers)
    scaling_efficiency_milli: int | None = None
    scaling_passed = True
    throughput_num = completed_games * 1_000_000_000
    throughput_den = wall_span
    if previous is not None:
        prev_num = int(previous["completed_games"]) * 1_000_000_000
        prev_den = int(previous["wall_span_nanoseconds"])
        # (new throughput / old throughput) / (workers / old workers) >= .70
        scaling_efficiency_milli = ((throughput_num * prev_den * int(previous["workers"])
                                     * 1000) // (throughput_den * prev_num * workers))
        scaling_passed = scaling_efficiency_milli >= SCALING_NUM * 10
    passed = (complete and verified and mechanics_passed and swaps == 0 and rss_passed
              and deadline_passed and process_errors == 0 and parallelism_passed
              and scaling_passed
              and (cumulative_wall_budget_nanoseconds is None
                   or (cumulative_wall_nanoseconds is not None
                       and cumulative_wall_nanoseconds <= cumulative_wall_budget_nanoseconds))
              and (cumulative_token_budget is None
                   or (cumulative_token_count is not None
                       and cumulative_token_count <= cumulative_token_budget)))
    return {"schema": CAPACITY_ARM_SCHEMA, "workers": workers,
            "completed_games": completed_games, "metrics": [m.payload() for m in metrics],
            "wall_span_nanoseconds": wall_span, "arm_wall_span_nanoseconds": wall_span,
            "cumulative_wall_nanoseconds": cumulative_wall_nanoseconds,
            "cumulative_token_count": cumulative_token_count,
            "aggregate_busy_cpu_nanoseconds": sum(
                metric.busy_cpu_nanoseconds for metric in metrics),
            "aggregate_peak_rss_bytes": aggregate_peak_rss,
            "aggregate_swap_bytes": max(metric.swap_bytes for metric in metrics),
            "aggregate_token_count": sum(metric.token_count for metric in metrics),
            "aggregate_token_rate_milli": aggregate_token_rate,
            "verified_games": verified_games,
            "process_errors": process_errors,
            "observed_parallelism_milli": observed_parallelism_milli,
            "p95_wall_nanoseconds": p95_wall,
            "max_peak_rss_bytes": max_rss, "swap_bytes": swaps,
            "mechanics_sha256": next(iter(mechanics)) if mechanics_passed else None,
            "scaling_efficiency_milli": scaling_efficiency_milli,
            "complete_passed": complete, "verified_passed": verified,
            "process_passed": process_errors == 0,
            "parallelism_passed": parallelism_passed,
            "mechanics_passed": mechanics_passed,
            "rss_passed": rss_passed, "deadline_passed": deadline_passed,
            "scaling_passed": scaling_passed,
            "cumulative_wall_budget_passed": (
                cumulative_wall_budget_nanoseconds is None or
                (cumulative_wall_nanoseconds is not None and
                 cumulative_wall_nanoseconds <= cumulative_wall_budget_nanoseconds)),
            "cumulative_token_budget_passed": (
                cumulative_token_budget is None or
                (cumulative_token_count is not None and
                 cumulative_token_count <= cumulative_token_budget)),
            "passed": passed}


@dataclass(frozen=True)
class CapacityReceipt:
    body: Mapping[str, object]
    receipt_sha256: str

    def __post_init__(self) -> None:
        if type(self.body) is not dict or self.body.get("schema") != CAPACITY_SCHEMA:
            raise ControllerError("capacity receipt schema drift")
        _strict_sha(self.receipt_sha256, "capacity receipt SHA")
        if _sha(self.body) != self.receipt_sha256:
            raise ControllerError("capacity receipt hash drift")
        # Validate the complete typed receipt at construction time.  This is
        # important for the filesystem round trip: changing a synthetic body
        # into a verified one must fail before any launch/admission seam sees
        # it, even when the attacker recomputes the outer receipt hash.
        validate_capacity_receipt(self)

    def serialized(self) -> dict[str, object]:
        return {**dict(self.body), "receipt_sha256": self.receipt_sha256}

    @classmethod
    def reopen(cls, payload: Mapping[str, object]) -> "CapacityReceipt":
        if type(payload) is not dict or "receipt_sha256" not in payload:
            raise ControllerError("capacity receipt digest absent")
        digest = payload["receipt_sha256"]
        body = {key: value for key, value in payload.items() if key != "receipt_sha256"}
        result = cls(body, digest)
        validate_capacity_receipt(result)
        return result


def validate_capacity_receipt(receipt: CapacityReceipt | Mapping[str, object]) -> None:
    if isinstance(receipt, CapacityReceipt):
        body = receipt.body
        digest = receipt.receipt_sha256
    else:
        if type(receipt) is not dict or "receipt_sha256" not in receipt:
            raise ControllerError("capacity receipt digest absent")
        body = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
        digest = receipt["receipt_sha256"]
    if type(body) is not dict or set(body) != {"schema", "deadline_nanoseconds",
            "physical_memory_bytes", "cumulative_wall_budget_nanoseconds",
            "cumulative_token_budget", "arms", "selected_workers", "stop_reason",
            "route", "authority", "execution_kind", "scientific_admissible",
            "provenance"}:
        raise ControllerError("capacity receipt schema drift")
    _positive_int(body["deadline_nanoseconds"], "capacity deadline")
    _positive_int(body["physical_memory_bytes"], "capacity physical memory")
    _positive_int(body["cumulative_wall_budget_nanoseconds"], "capacity wall budget")
    _positive_int(body["cumulative_token_budget"], "capacity token budget")
    if body["authority"] != luna.AUTHORITY or body["schema"] != CAPACITY_SCHEMA:
        raise ControllerError("capacity receipt identity drift")
    if (body["execution_kind"] not in (CAPACITY_EXECUTION_SYNTHETIC,
                                        CAPACITY_EXECUTION_VERIFIED)
            or body["scientific_admissible"] is not False):
        raise ControllerError("capacity execution provenance drift")
    _validate_capacity_provenance(
        body["provenance"], execution_kind=body["execution_kind"],
        scientific_admissible=body["scientific_admissible"])
    arms = body["arms"]
    if type(arms) is not list or not arms or len(arms) > len(CAPACITY_WORKERS):
        raise ControllerError("capacity arm population drift")
    expected = list(CAPACITY_WORKERS[:len(arms)])
    previous = None
    passing: list[int] = []
    saw_failure = False
    for arm, workers in zip(arms, expected):
        arm_keys = {"schema", "workers", "completed_games", "metrics",
                    "wall_span_nanoseconds", "arm_wall_span_nanoseconds",
                    "cumulative_wall_nanoseconds", "cumulative_token_count",
                    "aggregate_busy_cpu_nanoseconds", "aggregate_peak_rss_bytes",
                    "aggregate_swap_bytes", "aggregate_token_count",
                    "aggregate_token_rate_milli", "verified_games", "process_errors",
                    "observed_parallelism_milli", "p95_wall_nanoseconds",
                    "max_peak_rss_bytes", "swap_bytes", "mechanics_sha256",
                    "scaling_efficiency_milli", "complete_passed", "verified_passed",
                    "process_passed", "parallelism_passed", "mechanics_passed",
                    "rss_passed", "deadline_passed", "scaling_passed",
                    "cumulative_wall_budget_passed",
                    "cumulative_token_budget_passed", "passed"}
        if type(arm) is not dict or set(arm) != arm_keys:
            raise ControllerError("capacity arm schema drift")
        if arm["schema"] != CAPACITY_ARM_SCHEMA or arm["workers"] != workers:
            raise ControllerError("capacity arm identity drift")
        metric_values = [CapacityMetric.from_mapping(value) for value in arm["metrics"]]
        expected_summary = _arm_summary(workers, metric_values,
                                        deadline_nanoseconds=body["deadline_nanoseconds"],
                                        physical_memory_bytes=body["physical_memory_bytes"],
                                        previous=previous,
                                        expected_mechanics_sha256=(
                                            None if previous is None
                                            else previous["mechanics_sha256"]),
                                        arm_wall_span_nanoseconds=arm["arm_wall_span_nanoseconds"],
                                        cumulative_wall_nanoseconds=arm["cumulative_wall_nanoseconds"],
                                        cumulative_token_count=arm["cumulative_token_count"],
                                        cumulative_wall_budget_nanoseconds=body["cumulative_wall_budget_nanoseconds"],
                                        cumulative_token_budget=body["cumulative_token_budget"])
        if arm != expected_summary:
            raise ControllerError("capacity arm derivation drift")
        if saw_failure:
            raise ControllerError("capacity arms continued after stop")
        if arm["passed"]:
            passing.append(workers)
        else:
            saw_failure = True
        previous = arm
    if body["execution_kind"] == CAPACITY_EXECUTION_VERIFIED:
        expected_games = [
            (arm["workers"], worker, game)
            for arm in arms
            for worker in range(arm["workers"])
            for game in range(2)
        ]
        observed_games = [
            (game["workers"], game["worker"], game["game"])
            for game in body["provenance"]["games"]
        ]
        if observed_games != expected_games:
            raise ControllerError("verified capacity evidence population drift")
    selected = body["selected_workers"]
    eligible = [workers for workers in passing
                if any(arm["workers"] > workers
                       and arm["parallelism_passed"]
                       and arm["complete_passed"]
                       and arm["verified_passed"]
                       and arm["process_passed"]
                       for arm in arms)]
    expected_selected = (max(
        eligible,
        key=lambda workers: next(
            arm["completed_games"] * 1_000_000_000 / arm["wall_span_nanoseconds"]
            for arm in arms if arm["workers"] == workers))
        if eligible else None)
    if selected != expected_selected:
        raise ControllerError("capacity selected arm drift")
    if body["route"] not in (CAPACITY_ROUTE, CAPACITY_REFUSE_ROUTE):
        raise ControllerError("capacity route drift")
    if type(body["stop_reason"]) is not str:
        raise ControllerError("capacity stop reason drift")
    if (body["stop_reason"] == "cumulative_budget_overrun"
            and body["route"] != CAPACITY_REFUSE_ROUTE):
        raise ControllerError("capacity budget route drift")
    if body["route"] == CAPACITY_ROUTE and selected is None:
        raise ControllerError("capacity pass without arm")
    if body["route"] == CAPACITY_REFUSE_ROUTE and len(arms) == len(CAPACITY_WORKERS) \
            and not passing:
        # A refusal with no passing arm is valid; no additional condition is needed.
        pass
    if digest != _sha(body):
        raise ControllerError("capacity receipt hash drift")


def _run_capacity_core(*, deadline_nanoseconds: int, physical_memory_bytes: int,
                 cumulative_wall_budget_nanoseconds: int = DEFAULT_WALL_BUDGET_NANOSECONDS,
                 cumulative_token_budget: int = DEFAULT_TOKEN_BUDGET,
                 game_runner: Callable[[int, int, int], Mapping[str, object]],
                 synthetic: bool,
                 provenance: Mapping[str, object] | None = None,
                 provenance_factory: Callable[[], Mapping[str, object]] | None = None,
                 progress_sink: Callable[[dict[str, object]], object] | None = None
                 ) -> CapacityReceipt:
    """Run score-free progressive arms concurrently with hard cumulative caps."""
    _positive_int(deadline_nanoseconds, "capacity deadline")
    _positive_int(physical_memory_bytes, "capacity physical memory")
    _positive_int(cumulative_wall_budget_nanoseconds, "capacity wall budget")
    _positive_int(cumulative_token_budget, "capacity token budget")
    if not callable(game_runner):
        raise ControllerError("capacity game runner required")
    if type(synthetic) is not bool:
        raise ControllerError("capacity execution provenance drift")
    if synthetic and provenance_factory is not None:
        raise ControllerError("synthetic capacity provenance factory refused")
    if not synthetic and provenance_factory is None:
        raise ControllerError("verified capacity provenance factory absent")
    if synthetic:
        if provenance is None:
            raise ControllerError("synthetic capacity provenance absent")
        _validate_capacity_provenance(
            dict(provenance), execution_kind=CAPACITY_EXECUTION_SYNTHETIC,
            scientific_admissible=False)
    arms: list[dict[str, object]] = []
    previous: Mapping[str, object] | None = None
    cumulative_wall = 0
    cumulative_tokens = 0
    stop_reason = "all_arms_complete"
    for workers in CAPACITY_WORKERS:
        if previous is not None:
            previous_workers = int(previous["workers"])
            multiplier = (workers + previous_workers - 1) // previous_workers
            estimated_wall = int(previous["arm_wall_span_nanoseconds"]) * multiplier
            estimated_tokens = int(previous["aggregate_token_count"]) * multiplier
            if cumulative_wall + estimated_wall > cumulative_wall_budget_nanoseconds:
                stop_reason = "cumulative_wall_budget_before_arm"
                break
            if cumulative_tokens + estimated_tokens > cumulative_token_budget:
                stop_reason = "cumulative_token_budget_before_arm"
                break
        arm_started = time.monotonic_ns()
        metrics: list[CapacityMetric] = []
        keys = _capacity_game_keys(workers)
        # The executor is deliberately created per arm: exactly two games per
        # worker are reached, and no later arm can start before this arm's
        # resource and mechanics receipt is fully derived.
        def one(item: tuple[int, int]) -> CapacityMetric:
            worker, game = item
            value = _invoke_capacity_runner(game_runner, workers, worker, game)
            return (value if isinstance(value, CapacityMetric)
                    else CapacityMetric.from_mapping(value))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {executor.submit(one, item): item for item in keys}
            for future in futures:
                metric = future.result()
                metrics.append(metric)
                if progress_sink:
                    worker, game = futures[future]
                    try:
                        progress_sink({"schema": CAPACITY_SCHEMA,
                                       "arm_workers": workers, "worker": worker,
                                       "game": game,
                                       "completed_games": len(metrics),
                                       "total_games": workers * 2})
                    except Exception:
                        # Progress is observational; a broken sink must not
                        # erase an otherwise sealed capacity receipt.
                        pass
        arm_finished = time.monotonic_ns()
        arm_wall = max(1, arm_finished - arm_started)
        cumulative_wall += arm_wall
        cumulative_tokens += sum(metric.token_count for metric in metrics)
        summary = _arm_summary(workers, metrics,
                               deadline_nanoseconds=deadline_nanoseconds,
                               physical_memory_bytes=physical_memory_bytes,
                               previous=previous,
                               expected_mechanics_sha256=(
                                   None if previous is None
                                   else previous["mechanics_sha256"]),
                               arm_wall_span_nanoseconds=arm_wall,
                               cumulative_wall_nanoseconds=cumulative_wall,
                               cumulative_token_count=cumulative_tokens,
                               cumulative_wall_budget_nanoseconds=(
                                   cumulative_wall_budget_nanoseconds),
                               cumulative_token_budget=cumulative_token_budget)
        arms.append(summary)
        if summary["passed"]:
            previous = summary
            continue
        stop_reason = ("cumulative_budget_overrun"
                       if not summary["cumulative_wall_budget_passed"]
                       or not summary["cumulative_token_budget_passed"]
                       else "arm_condition_failed")
        break
    passing = [arm["workers"] for arm in arms if arm["passed"]]
    eligible = [workers for workers in passing
                if any(arm["workers"] > workers
                       and arm["parallelism_passed"]
                       and arm["complete_passed"]
                       and arm["verified_passed"]
                       and arm["process_passed"]
                       for arm in arms)]
    selected = (max(eligible, key=lambda workers: next(
        arm["completed_games"] * 1_000_000_000 / arm["wall_span_nanoseconds"]
        for arm in arms if arm["workers"] == workers)) if eligible else None)
    if not synthetic:
        assert provenance_factory is not None
        provenance = provenance_factory()
        _validate_capacity_provenance(
            dict(provenance), execution_kind=CAPACITY_EXECUTION_VERIFIED,
            scientific_admissible=False)
    body = {"schema": CAPACITY_SCHEMA, "deadline_nanoseconds": deadline_nanoseconds,
            "physical_memory_bytes": physical_memory_bytes,
            "cumulative_wall_budget_nanoseconds": cumulative_wall_budget_nanoseconds,
            "cumulative_token_budget": cumulative_token_budget, "arms": arms,
            "selected_workers": selected,
            "stop_reason": stop_reason,
            "route": (CAPACITY_REFUSE_ROUTE
                      if selected is None or stop_reason == "cumulative_budget_overrun"
                      else CAPACITY_ROUTE),
            "authority": dict(luna.AUTHORITY),
            "execution_kind": (CAPACITY_EXECUTION_SYNTHETIC if synthetic
                                else CAPACITY_EXECUTION_VERIFIED),
            "scientific_admissible": False}
    body["provenance"] = dict(provenance)
    receipt = CapacityReceipt(body, _sha(body))
    validate_capacity_receipt(receipt)
    return receipt


def run_capacity(*, deadline_nanoseconds: int, physical_memory_bytes: int,
                 cumulative_wall_budget_nanoseconds: int = DEFAULT_WALL_BUDGET_NANOSECONDS,
                 cumulative_token_budget: int = DEFAULT_TOKEN_BUDGET,
                 game_runner: Callable[[int, int, int], Mapping[str, object]],
                 progress_sink: Callable[[dict[str, object]], object] | None = None
                 ) -> CapacityReceipt:
    """Run the explicitly synthetic, score-free capacity test seam.

    Runtime-verified capacity is intentionally unavailable through this API;
    only ``run_real_capacity`` can mint that candidate from reopened process
    evidence.
    """
    return _run_capacity_core(
        deadline_nanoseconds=deadline_nanoseconds,
        physical_memory_bytes=physical_memory_bytes,
        cumulative_wall_budget_nanoseconds=cumulative_wall_budget_nanoseconds,
        cumulative_token_budget=cumulative_token_budget,
        game_runner=game_runner, synthetic=True,
        provenance={"schema": CAPACITY_PROVENANCE_SCHEMA,
                    "execution_kind": CAPACITY_EXECUTION_SYNTHETIC,
                    "scientific_admissible": False,
                    "runtime_sha256": None, "evidence_sha256": None,
                    "tool_script_sha256": None, "games": []},
        progress_sink=progress_sink)


def run_real_capacity(*, capacity_secret: bytes, tool_script: Path,
                      deadline_nanoseconds: int,
                      physical_memory_bytes: int,
                      config: execution.LunaPlannerConfig | None = None,
                      cumulative_wall_budget_nanoseconds: int = DEFAULT_WALL_BUDGET_NANOSECONDS,
                      cumulative_token_budget: int = DEFAULT_TOKEN_BUDGET,
                      progress_sink: Callable[[dict[str, object]], object] | None = None
                      ) -> CapacityReceipt:
    """Run the real process boundary in a disposable, non-scientific namespace.

    The execution supervisor samples the actual new-session process groups
    while both model processes are live.  The temporary directory is deleted
    after score-free telemetry is extracted; no trajectory, action, outcome,
    or model prose enters the capacity receipt.
    """
    if type(capacity_secret) is not bytes or len(capacity_secret) != 32:
        raise ControllerError("capacity secret identity drift")
    if not Path(tool_script).is_file():
        raise ControllerError("capacity tool script absent")
    planner_config = config or execution.LunaPlannerConfig()
    # Each capacity game has distinct runtime/evidence identities. Keep them
    # keyed by arm coordinate instead of requiring every subprocess to emit
    # the same digest.
    provenance_box: list[tuple[tuple[int, int, int], dict[str, object]]] = []

    def runner(workers: int, worker: int, game_index: int) -> CapacityMetric:
        # Domain-separate every score-free capacity game inside the capacity
        # namespace.  Reusing one root across workers would make the arm look
        # parallel while measuring the same deal repeatedly.
        game_secret = hashlib.sha256(
            capacity_secret + canonical_json_bytes(
                ["capacity-game", workers, worker, game_index])).digest()
        coordinate = ("2", 0, game_index % 2)
        root = luna.build_root(game_secret, coordinate)
        game = luna.LunaSelfPlayGame(root, coordinate=coordinate,
                                     mirror=game_index % 2,
                                     seed_secret=game_secret)
        started = time.monotonic_ns()
        meter = execution.ProcessTreeResourceMeter()
        with tempfile.TemporaryDirectory(prefix="pt-luna-capacity-") as temporary:
            try:
                result = execution.run_luna_game(
                    game, private_root=Path(temporary),
                    tool_script=Path(tool_script), config=planner_config,
                    resource_meter=meter)
            finally:
                telemetry = meter.close()
            try:
                reopened = execution.reopen_attempt(result.attempt_path)
            except Exception as exc:
                raise CapacityEvidenceRefusal(
                    coordinate=coordinate, workers=workers, worker=worker,
                    game=game_index, reopened_status=None, evidence=(),
                    failure_kind="reopen_failure") from exc
            evidence = tuple(reopened.evidence)
            if (len(evidence) != len(luna.TEAMS)
                    or not getattr(reopened, "scientific_admissible", False)
                    or any(item.body.get("execution_kind")
                           != execution.PRODUCTION_EXECUTION_KIND
                           or item.body.get("actual_subprocess") is not True
                           or item.body.get("synthetic") is not False
                           for item in evidence)):
                raise CapacityEvidenceRefusal(
                    coordinate=coordinate, workers=workers, worker=worker,
                    game=game_index,
                    reopened_status=getattr(reopened, "status", None),
                    evidence=evidence)
            provenance = {"schema": CAPACITY_PROVENANCE_SCHEMA,
                          "execution_kind": CAPACITY_EXECUTION_VERIFIED,
                          "scientific_admissible": False,
                          "runtime_sha256": _sha([item.body["runtime"]
                                                   for item in reopened.evidence]),
                          "evidence_sha256": _sha([item.sha256
                                                    for item in reopened.evidence]),
                          "tool_script_sha256": _sha_bytes(
                              Path(tool_script).read_bytes()),
                          "games": []}
            provenance["games"].append({
                "workers": workers, "worker": worker, "game": game_index,
                "runtime_sha256": provenance["runtime_sha256"],
                "evidence_sha256": provenance["evidence_sha256"],
                "tool_script_sha256": provenance["tool_script_sha256"]})
            provenance_box.append(((workers, worker, game_index), provenance))
            finished = time.monotonic_ns()
            elapsed = max(1, finished - started)
            required = {"schema", "busy_cpu_nanoseconds", "peak_rss_bytes",
                        "swap_bytes", "sample_count"}
            if type(telemetry) is not dict or set(telemetry) != required:
                raise ControllerError("resource telemetry schema drift")
            if telemetry["schema"] != execution.RESOURCE_SCHEMA:
                raise ControllerError("resource telemetry identity drift")
            _positive_int(telemetry["sample_count"], "capacity sample count")
            busy_cpu = _positive_int(telemetry["busy_cpu_nanoseconds"],
                                     "capacity busy CPU")
            peak_rss = _positive_int(telemetry["peak_rss_bytes"],
                                     "capacity process RSS")
            swap = _nonnegative_int(telemetry["swap_bytes"], "capacity swap")
            tokens = 0
            tool_calls = 0
            process_errors = 0
            for evidence in reopened.evidence:
                body = evidence.body
                usage = body.get("codex_usage")
                if type(usage) is not dict \
                        or set(usage) != execution.CODEX_USAGE_KEYS:
                    raise ControllerError("capacity token telemetry absent")
                tokens += sum(_nonnegative_int(usage[key], "capacity token count")
                              for key in usage)
                trace = body.get("trace")
                if type(trace) is not list:
                    raise ControllerError("capacity tool telemetry absent")
                tool_calls += len(trace)
                process_errors += int(body.get("process_error") is not None)
            mechanics = _sha({"schema": "pt-luna-capacity-mechanics-v1",
                               "runtime": [item.body.get("runtime")
                                           for item in reopened.evidence],
                               "planner": planner_config.payload()})
            return CapacityMetric(
                complete=reopened.status == "complete",
                verified=(reopened.status == "complete"
                          and all(item.body.get("process_error") is None
                                  for item in reopened.evidence)),
                wall_nanoseconds=elapsed,
                busy_cpu_nanoseconds=busy_cpu,
                peak_rss_bytes=peak_rss, swap_bytes=swap,
                process_errors=process_errors,
                tool_calls=tool_calls, token_count=tokens,
                token_rate_milli=(tokens * 1_000_000_000_000 // elapsed),
                mechanics_sha256=mechanics)

    return _run_capacity_core(
        deadline_nanoseconds=deadline_nanoseconds,
        physical_memory_bytes=physical_memory_bytes,
        cumulative_wall_budget_nanoseconds=cumulative_wall_budget_nanoseconds,
        cumulative_token_budget=cumulative_token_budget,
        game_runner=runner, progress_sink=progress_sink, synthetic=False,
        provenance_factory=lambda: {
            "schema": CAPACITY_PROVENANCE_SCHEMA,
            "execution_kind": CAPACITY_EXECUTION_VERIFIED,
            "scientific_admissible": False,
            "runtime_sha256": _sha([
                item[1]["runtime_sha256"] for item in sorted(provenance_box)]),
            "evidence_sha256": _sha([
                item[1]["evidence_sha256"] for item in sorted(provenance_box)]),
            "tool_script_sha256": _sha_bytes(Path(tool_script).read_bytes()),
            "games": [
                {"workers": item[0][0], "worker": item[0][1], "game": item[0][2],
                 "runtime_sha256": item[1]["runtime_sha256"],
                 "evidence_sha256": item[1]["evidence_sha256"],
                 "tool_script_sha256": item[1]["tool_script_sha256"]}
                for item in sorted(provenance_box)],
        },)


def _completed_from_attempt(attempt: Path) -> luna.CompletedGameArtifacts:
    trajectory_raw = (Path(attempt) / "trajectory.json").read_bytes()
    trajectory = luna.SealedTrajectory.reopen(trajectory_raw)
    receipt_payload = _read_canonical(Path(attempt) / "terminal-receipt.json")
    receipt = luna.TerminalReceipt(**{
        key: tuple(value) if key == "coordinate" else value
        for key, value in receipt_payload.items() if key != "schema"})
    return luna.CompletedGameArtifacts(trajectory, receipt)


def _attempt_manifest_sha(attempt: Path) -> str:
    raw = (Path(attempt) / "manifest.json").read_bytes()
    payload = _read_canonical(Path(attempt) / "manifest.json")
    _record_hash(payload, "manifest_sha256")
    return _sha_bytes(raw)


def _schedule_sha(design: luna.LunaDesign) -> str:
    return _sha([[list(coordinate), mirror]
                 for coordinate, mirror in design.mirror_assignments])


def launch_freeze_payload(*, design: luna.LunaDesign,
                          census: luna.RootCensus,
                          capacity: CapacityReceipt,
                          worker_count: int, output_root: Path,
                          tool_script: Path) -> dict[str, object]:
    """Build the exact externally reviewed, immutable collection admission."""
    if (capacity.body.get("route") != CAPACITY_ROUTE
            or capacity.body.get("execution_kind") != CAPACITY_EXECUTION_VERIFIED
            or capacity.body.get("scientific_admissible") is not False):
        raise ControllerError("launch freeze requires verified capacity candidate")
    luna.validate_game_workers(worker_count)
    if not Path(tool_script).is_file():
        raise ControllerError("launch freeze tool script absent")
    body = {"schema": LAUNCH_FREEZE_SCHEMA,
            "execution_git": design.execution_git,
            "source_sha256": _source_sha256(),
            "design_sha256": _sha(design.payload()),
            "census_sha256": census.census_sha256,
            "capacity_receipt_sha256": capacity.receipt_sha256,
            "schedule_sha256": _schedule_sha(design),
            "worker_count": worker_count,
            "output_root": str(Path(output_root).resolve()),
            "tool_script_sha256": _sha_bytes(Path(tool_script).read_bytes()),
            # This function creates a candidate only.  Authentication and
            # scientific admission can come solely from the external review.
            "authenticated": False,
            "scientific_execution_authorized": False,
            "authority": dict(luna.AUTHORITY)}
    return {**body, "freeze_sha256": _sha(body)}


def validate_launch_freeze(payload: Mapping[str, object], *,
                           design: luna.LunaDesign,
                           census: luna.RootCensus,
                           capacity: CapacityReceipt,
                           output_root: Path, tool_script: Path) -> None:
    if type(payload) is not dict or set(payload) != {
            "schema", "execution_git", "source_sha256", "design_sha256", "census_sha256",
            "capacity_receipt_sha256", "schedule_sha256", "worker_count",
            "output_root", "tool_script_sha256", "authenticated",
            "scientific_execution_authorized", "authority", "freeze_sha256"}:
        raise ControllerError("launch freeze schema drift")
    _record_hash(payload, "freeze_sha256")
    if payload != launch_freeze_payload(
            design=design, census=census, capacity=capacity,
            worker_count=payload["worker_count"], output_root=output_root,
            tool_script=tool_script):
        raise ControllerError("launch freeze binding drift")
    if payload["authenticated"] is not False \
            or payload["scientific_execution_authorized"] is not False:
        raise ControllerError("candidate freeze authority drift")


def _review_claim(*, freeze: Mapping[str, object], design: luna.LunaDesign,
                  census: luna.RootCensus, capacity: CapacityReceipt,
                  output_root: Path, tool_script: Path) -> dict[str, object]:
    return {"schema": REVIEW_MARKER_SCHEMA,
            "execution_git": design.execution_git,
            "source_sha256": _source_sha256(),
            "design_sha256": _sha(design.payload()),
            "census_sha256": census.census_sha256,
            "capacity_receipt_sha256": capacity.receipt_sha256,
            "candidate_freeze_sha256": freeze["freeze_sha256"],
            "worker_count": freeze["worker_count"],
            "output_root": str(Path(output_root).resolve()),
            "tool_script_sha256": _sha_bytes(Path(tool_script).read_bytes()),
            "authority": dict(luna.AUTHORITY)}


def _git(cwd: Path, *args: str) -> str:
    try:
        result = subprocess.run(("git", "-C", str(cwd), *args),
                                check=True, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ControllerError("review provenance unavailable") from exc
    return result.stdout.decode("utf-8")


def authenticate_source_review(*, freeze: Mapping[str, object],
                               design: luna.LunaDesign,
                               census: luna.RootCensus,
                               capacity: CapacityReceipt,
                               output_root: Path, tool_script: Path,
                               review_commit: str,
                               repo_root: Path | None = None) -> _AuthenticatedSourceReview:
    """Authenticate an exact external review marker from fetched GitHub main."""
    validate_launch_freeze(freeze, design=design, census=census,
                           capacity=capacity, output_root=output_root,
                           tool_script=tool_script)
    if (type(review_commit) is not str or len(review_commit) != 40
            or any(char not in "0123456789abcdef" for char in review_commit)):
        raise ControllerError("review commit drift")
    if repo_root is None or not Path(repo_root).is_dir():
        raise ControllerError("source repository required")
    expected = _review_claim(freeze=freeze, design=design, census=census,
                             capacity=capacity, output_root=output_root,
                             tool_script=tool_script)
    remote = CANONICAL_REMOTE_URL
    with tempfile.TemporaryDirectory(prefix="pt-luna-review-") as temporary:
        bare = Path(temporary) / "review.git"
        try:
            subprocess.run(("git", "init", "--bare", str(bare)), check=True,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            subprocess.run(("git", "-C", str(bare), "fetch", "--no-tags",
                            remote, f"{CANONICAL_REMOTE_REF}:refs/remotes/review/main"),
                           check=True, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE)
        except (OSError, subprocess.CalledProcessError) as exc:
            raise ControllerError("canonical review remote unavailable") from exc
        remote_tip = _git(bare, "rev-parse", "refs/remotes/review/main").strip()
        if len(remote_tip) != 40 or any(char not in "0123456789abcdef"
                                        for char in remote_tip):
            raise ControllerError("canonical review tip drift")
        if subprocess.run(("git", "-C", str(bare), "merge-base", "--is-ancestor",
                           review_commit, remote_tip),
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE).returncode != 0:
            raise ControllerError("review commit is not on canonical main")
        parents = _git(bare, "rev-list", "--parents", "-n", "1",
                       review_commit).strip().split()
        if len(parents) != 2:
            raise ControllerError("review commit parent drift")
        try:
            review_bytes = subprocess.check_output(
                ("git", "-C", str(bare), "show", f"{review_commit}:HANDOFF_REVIEW.md"))
            previous_bytes = subprocess.check_output(
                ("git", "-C", str(bare), "show", f"{parents[1]}:HANDOFF_REVIEW.md"))
        except (OSError, subprocess.CalledProcessError) as exc:
            raise ControllerError("review ledger unavailable") from exc
    marker = (REVIEW_MARKER_PREFIX.encode("ascii")
              + canonical_json_bytes(expected))
    previous_lines = previous_bytes.splitlines(keepends=True)
    current_lines = review_bytes.splitlines(keepends=True)
    if (current_lines != [*previous_lines, marker]
            or marker in previous_lines
            or not review_bytes.startswith(previous_bytes)
            or review_bytes[len(previous_bytes):] != marker):
        raise ControllerError("review marker commit drift")
    return _AuthenticatedSourceReview(
        review_commit=review_commit,
        review_marker_sha256=_sha_bytes(marker),
        review_claim=expected,
        _token=_REVIEW_AUTHENTICATION)


def _admission_body(*, design: luna.LunaDesign, census: luna.RootCensus,
                    capacity: CapacityReceipt, worker_count: int,
                    evidence_root: Path, freeze_sha256: str,
                    review: _AuthenticatedSourceReview) -> dict[str, object]:
    return {"schema": POPULATION_ADMISSION_SCHEMA,
            "design": design.payload(), "census_sha256": census.census_sha256,
            "capacity_receipt_sha256": capacity.receipt_sha256,
            "schedule_sha256": _schedule_sha(design), "worker_count": worker_count,
            "output_root": str(Path(evidence_root).resolve()),
            "freeze_sha256": freeze_sha256,
            "review_commit": review["review_commit"],
            "review_marker_sha256": review["review_marker_sha256"],
            "review_claim": review["review_claim"],
            "authority": dict(luna.AUTHORITY)}


def _validate_admission(payload: Mapping[str, object], *, design: luna.LunaDesign,
                        census: luna.RootCensus, capacity: CapacityReceipt,
                        worker_count: int, evidence_root: Path,
                        freeze: Mapping[str, object],
                        review: _AuthenticatedSourceReview) -> None:
    if type(payload) is not dict or set(payload) != {
            "schema", "design", "census_sha256", "capacity_receipt_sha256",
            "schedule_sha256", "worker_count", "output_root", "freeze_sha256",
            "review_commit", "review_marker_sha256", "review_claim", "authority",
            "admission_sha256"}:
        raise ControllerError("population admission schema drift")
    _record_hash(payload, "admission_sha256")
    body = {key: value for key, value in payload.items()
            if key != "admission_sha256"}
    expected = _admission_body(design=design, census=census, capacity=capacity,
                               worker_count=worker_count,
                               evidence_root=evidence_root,
                               freeze_sha256=freeze["freeze_sha256"], review=review)
    if body != expected:
        raise ControllerError("population admission binding drift")
    if (capacity.body.get("execution_kind") != CAPACITY_EXECUTION_VERIFIED
            or capacity.body.get("scientific_admissible") is not False
            or not isinstance(review, _AuthenticatedSourceReview)):
        raise ControllerError("authenticated capacity review required")


def _missing_row(coordinate: tuple[str, int, int], mirror: int,
                 *, error: str = "missing") -> dict[str, object]:
    return {"coordinate": list(coordinate), "mirror": mirror,
            "cluster_key": list(coordinate), "status": "incomplete",
            "attempt_path": "-".join(map(str, coordinate)) + f"-mirror-{mirror}",
            "attempt_manifest_sha256": None, "trajectory_sha256": None,
            "terminal_receipt_sha256": None, "error": error}


def _row_from_attempt(attempt: Path, coordinate: tuple[str, int, int], mirror: int,
                      root_sha256: str, *, require_scientific: bool = True) -> tuple[dict[str, object],
                                                 luna.CompletedGameArtifacts | None]:
    result = execution.reopen_attempt(Path(attempt))
    manifest = _read_canonical(Path(attempt) / "manifest.json")
    if require_scientific and result.status == "complete" \
            and not result.scientific_admissible:
        raise SourceAdmissionError("synthetic execution cannot enter source population")
    if (result.status == "complete" and result.trajectory_sha256 is not None
            and result.terminal_receipt_sha256 is not None):
        artifacts = _completed_from_attempt(attempt)
        if (artifacts.trajectory.body["coordinate"] != list(coordinate)
                or artifacts.trajectory.body["mirror"] != mirror
                or artifacts.trajectory.body["root_sha256"] != root_sha256):
            raise ControllerError("attempt root binding drift")
        return ({"coordinate": list(coordinate), "mirror": mirror,
                 "cluster_key": list(coordinate), "status": "complete",
                 "attempt_path": str(Path(attempt).name),
                 "attempt_manifest_sha256": _attempt_manifest_sha(attempt),
                 "trajectory_sha256": result.trajectory_sha256,
                 "terminal_receipt_sha256": result.terminal_receipt_sha256,
                 "error": None}, artifacts)
    if result.status != "incomplete":
        raise ControllerError("attempt status drift")
    manifest_sha = _attempt_manifest_sha(attempt)
    return ({"coordinate": list(coordinate), "mirror": mirror,
             "cluster_key": list(coordinate), "status": "incomplete",
             "attempt_path": str(Path(attempt).name),
             "attempt_manifest_sha256": manifest_sha,
             "trajectory_sha256": None, "terminal_receipt_sha256": None,
             "error": (manifest.get("error") if isinstance(manifest.get("error"), str)
                        else "incomplete")}, None)


def production_game_runner(*, private_root: Path, tool_script: Path,
                           config: execution.LunaPlannerConfig | None = None):
    def runner(game: luna.LunaSelfPlayGame, attempt_root: Path):
        return execution.run_luna_game(game, private_root=private_root,
                                       tool_script=tool_script, config=config)
    return runner


# Kept as a short compatibility alias for the initial source-review packet.
_production_runner = production_game_runner


def completed_artifact_game_runner(*, private_root: Path, tool_script: Path,
                                   seed_secret: bytes | None = None,
                                   config: execution.LunaPlannerConfig | None = None):
    """Build the ``CompletedGameArtifacts`` callback expected by core.run_population.

    This adapter is intentionally complete-only: an incomplete attempt is a
    terminal source-population result and must be handled by
    :func:`run_source_population`, whose rows preserve its real manifest.
    """
    if seed_secret is not None and (type(seed_secret) is not bytes
                                    or len(seed_secret) != 32):
        raise ControllerError("population seed secret identity drift")
    runner = production_game_runner(private_root=private_root,
                                     tool_script=tool_script, config=config)

    def complete(coordinate: tuple[str, int, int] | luna.LunaSelfPlayGame,
                mirror: int | Path):
        if isinstance(coordinate, luna.LunaSelfPlayGame):
            # Compatibility for the direct game callback used by the first
            # source-review packet; the core adapter below uses the tuple/int
            # contract and derives the game from the committed seed.
            game = coordinate
            attempt_root = Path(mirror)
        else:
            if seed_secret is None:
                raise ControllerError("population seed secret required")
            coord = luna.LunaCoordinate(*coordinate)
            root = luna.build_root(seed_secret, coord, mirror=int(mirror))
            game = luna.LunaSelfPlayGame(root, coordinate=coordinate,
                                         mirror=int(mirror),
                                         seed_secret=seed_secret)
            attempt_root = private_root
        result = runner(game, attempt_root)
        reopened = execution.reopen_attempt(result.attempt_path)
        if reopened.status != "complete":
            raise ControllerError("incomplete execution cannot enter core runner")
        return _completed_from_attempt(result.attempt_path)
    return complete


def run_source_population(*, design: luna.LunaDesign, seed_secret: bytes,
                          census: luna.RootCensus | Mapping[str, object],
                          capacity: CapacityReceipt | Mapping[str, object],
                          evidence_root: Path,
                          game_runner: Callable[[luna.LunaSelfPlayGame, Path], object],
                          worker_count: int | None = None,
                          progress_sink: Callable[[dict[str, object]], object] | None = None,
                          candidate_freeze: Mapping[str, object] | None = None,
                          launch_freeze: Mapping[str, object] | None = None,
                          review_commit: str | None = None,
                          repo_root: Path | None = None,
                          tool_script: Path | None = None
                          ) -> dict[str, object]:
    """Acquire/reopen exactly the sealed 104-game schedule once."""
    try:
        census_obj = (census if isinstance(census, luna.RootCensus)
                      else luna.RootCensus.reopen(census, design=design))
        luna.validate_root_census(census_obj, design=design)
    except Exception as exc:
        raise ControllerError("root census admission refused") from exc
    if hashlib.sha256(seed_secret).hexdigest() != design.seed_commitment_sha256:
        raise ControllerError("seed commitment drift")
    capacity_obj = (capacity if isinstance(capacity, CapacityReceipt)
                    else CapacityReceipt.reopen(capacity))
    validate_capacity_receipt(capacity_obj)
    if (capacity_obj.body["route"] != CAPACITY_ROUTE
            or capacity_obj.body["execution_kind"] != CAPACITY_EXECUTION_VERIFIED
            or capacity_obj.body["scientific_admissible"] is not False):
        raise ControllerError("capacity admission refused")
    selected = capacity_obj.body["selected_workers"]
    if worker_count is None:
        worker_count = int(selected)
    luna.validate_game_workers(worker_count)
    if worker_count != selected:
        raise ControllerError("worker arm differs from capacity")
    if candidate_freeze is not None and launch_freeze is not None \
            and candidate_freeze != launch_freeze:
        raise ControllerError("candidate freeze aliases differ")
    freeze = candidate_freeze if candidate_freeze is not None else launch_freeze
    if freeze is None or review_commit is None or tool_script is None:
        raise ControllerError("authenticated source review admission required")
    review = authenticate_source_review(
        freeze=freeze, design=design, census=census_obj, capacity=capacity_obj,
        output_root=Path(evidence_root), tool_script=Path(tool_script),
        review_commit=review_commit,
        repo_root=repo_root)
    if not callable(game_runner):
        raise ControllerError("population game runner required")
    evidence_root = Path(evidence_root)
    evidence_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    report_path = evidence_root / "population-report.json"
    admission_path = evidence_root / "population-admission.json"
    if report_path.exists() or report_path.is_symlink() \
            or admission_path.exists() or admission_path.is_symlink():
        raise ControllerError("population admission slot occupied")
    _publish(admission_path, _admission_body(
        design=design, census=census_obj, capacity=capacity_obj,
        worker_count=worker_count, evidence_root=evidence_root,
        freeze_sha256=freeze["freeze_sha256"], review=review),
        suffix="admission_sha256")
    attempts_root = evidence_root / "attempts"
    attempts_root.mkdir(mode=0o700, exist_ok=True)
    roots = {tuple(row["coordinate"]): row["root_sha256"]
             for row in census_obj.body["coordinates"]}
    schedule = tuple(design.mirror_assignments)
    rows: list[dict[str, object] | None] = [None] * len(schedule)
    started = time.monotonic()
    lock = threading.Lock()
    completed = 0
    finished_tasks = 0
    active = 0

    def emit() -> None:
        if not progress_sink:
            return
        elapsed = time.monotonic() - started
        done = finished_tasks
        successful = sum(row is not None and row["status"] == "complete"
                         for row in rows)
        sealed = sum(row is not None
                     and row["attempt_manifest_sha256"] is not None
                     for row in rows)
        row = luna.progress(
            completed_games=done, total_games=len(schedule),
            completed_deal_clusters=sum(
                sum(row is not None and row["coordinate"] == list(coord)
                    and row["status"] == "complete" for row in rows) == 2
                for coord in design.deal_clusters),
            total_deal_clusters=len(design.deal_clusters), elapsed_seconds=elapsed,
            eta_seconds=(None if done == 0 else elapsed * (len(schedule) - done) / done),
            successful_games=successful,
            failure_count=done - successful,
            active_game_workers=active, active_model_processes=2 * active,
            recent_games_per_second=(done / elapsed if elapsed else 0.0))
        row["sealed_games"] = sealed
        row["preseal_missing_games"] = done - sealed
        try:
            progress_sink(row)
        except Exception:
            # A telemetry sink is not part of the sealed population.  It must
            # not turn a real attempt into an unreported controller failure.
            pass

    def one(index: int, item: tuple[tuple[str, int, int], int]) -> None:
        nonlocal completed, active, finished_tasks
        coordinate, mirror = item
        coord = luna.LunaCoordinate(*coordinate)
        attempt = attempts_root / ("-".join(map(str, coordinate)) + f"-mirror-{mirror}")
        with lock:
            active += 1
        try:
            if attempt.exists() or attempt.is_symlink():
                if (attempt / "manifest.json").exists():
                    row, artifact = _row_from_attempt(attempt, coordinate, mirror,
                                                      roots[coordinate])
                else:
                    execution.seal_pre_manifest_attempt(
                        attempt=attempt, coordinate=coordinate, mirror=mirror,
                        root_sha256=roots[coordinate])
                    row, artifact = _row_from_attempt(attempt, coordinate, mirror,
                                                      roots[coordinate])
            else:
                root = luna.build_root(seed_secret, coord, mirror=mirror)
                if luna.root_identity(root) != roots[coordinate]:
                    raise ControllerError("census root binding drift")
                game = luna.LunaSelfPlayGame(root, coordinate=coordinate,
                                             mirror=mirror, seed_secret=seed_secret)
                # The execution adapter derives this exact attempt directory
                # from ``attempts_root`` and the immutable game identity.
                result = game_runner(game, attempts_root)
                if not isinstance(result, execution.LunaExecutionResult):
                    raise ControllerError("runner must return execution result")
                if Path(result.attempt_path) != attempt:
                    raise ControllerError("execution attempt path drift")
                row, artifact = _row_from_attempt(result.attempt_path, coordinate,
                                                  mirror, roots[coordinate])
            with lock:
                rows[index] = row
        except Exception as exc:
            if isinstance(exc, SourceAdmissionError):
                raise
            # A model/process exception may still have sealed an attempt.  Reopen
            # that real identity; otherwise publish an explicit missing identity.
            try:
                if (attempt / "manifest.json").is_file():
                    row, _ = _row_from_attempt(attempt, coordinate, mirror,
                                               roots[coordinate])
                else:
                    if attempt.is_dir() and not attempt.is_symlink():
                        execution.seal_pre_manifest_attempt(
                            attempt=attempt, coordinate=coordinate, mirror=mirror,
                            root_sha256=roots[coordinate], error=type(exc).__name__)
                        row, _ = _row_from_attempt(attempt, coordinate, mirror,
                                                   roots[coordinate])
                    else:
                        row = _missing_row(coordinate, mirror,
                                           error=type(exc).__name__)
            except Exception as reopen_exc:
                row = _missing_row(coordinate, mirror,
                                   error=type(reopen_exc).__name__)
            with lock:
                rows[index] = row
        finally:
            with lock:
                active -= 1
                finished_tasks += 1
                if rows[index] is not None and rows[index]["attempt_manifest_sha256"] is not None:
                    completed += 1
                emit()

    with ThreadPoolExecutor(max_workers=worker_count) as pool:
        futures = [pool.submit(one, index, item)
                   for index, item in enumerate(schedule)]
        for future in futures:
            # ``one`` catches acquisition/reopen failures and records them as
            # rows.  Keep the outer controller fail-closed if an unexpected
            # executor error escapes, but still allow the final report to be
            # published for the ordinary worker-error path.
            try:
                future.result()
            except SourceAdmissionError:
                raise
            except Exception:
                continue
    final_rows = [row for row in rows if row is not None]
    successful = sum(row["status"] == "complete" for row in final_rows)
    clusters = sum(sum(row["coordinate"] == list(coord) and row["status"] == "complete"
                        for row in final_rows) == 2 for coord in design.deal_clusters)
    body = {"schema": POPULATION_REPORT_SCHEMA,
            "design": design.payload(), "census_sha256": census_obj.census_sha256,
            "capacity_receipt_sha256": capacity_obj.receipt_sha256,
            "admission_sha256": _record_hash(
                _read_canonical(admission_path), "admission_sha256"),
            "freeze_sha256": freeze["freeze_sha256"],
            "review_commit": review["review_commit"],
            "review_marker_sha256": review["review_marker_sha256"],
            "worker_count": worker_count, "rows": final_rows,
            "completed_games": len(final_rows), "successful_games": successful,
            "total_games": len(schedule), "completed_deal_clusters": clusters,
            "total_deal_clusters": len(design.deal_clusters),
            "terminal_route": (luna.COMPLETE_ROUTE if successful == len(schedule)
                               else luna.INCOMPLETE_ROUTE),
            "authority": dict(luna.AUTHORITY)}
    report = {**body, "report_sha256": _sha(body)}
    _publish(report_path, body, suffix="report_sha256")
    return report


def finalize_source_population(*, design: luna.LunaDesign,
                               census: luna.RootCensus | Mapping[str, object],
                               capacity: CapacityReceipt | Mapping[str, object],
                               evidence_root: Path,
                               candidate_freeze: Mapping[str, object] | None = None,
                               launch_freeze: Mapping[str, object] | None = None,
                               review_commit: str | None = None,
                               repo_root: Path | None = None,
                               tool_script: Path | None = None) -> dict[str, object]:
    """Reconstruct sealed attempts after controller death without model calls."""
    evidence_root = Path(evidence_root)
    report_path = evidence_root / "population-report.json"
    admission_path = evidence_root / "population-admission.json"
    admission = _read_canonical(admission_path)
    census_obj = (census if isinstance(census, luna.RootCensus)
                  else luna.RootCensus.reopen(census, design=design))
    capacity_obj = (capacity if isinstance(capacity, CapacityReceipt)
                    else CapacityReceipt.reopen(capacity))
    validate_capacity_receipt(capacity_obj)
    freeze = candidate_freeze if candidate_freeze is not None else launch_freeze
    if freeze is None or review_commit is None or tool_script is None:
        raise ControllerError("authenticated source review admission required")
    review = authenticate_source_review(
        freeze=freeze, design=design, census=census_obj,
        capacity=capacity_obj, output_root=evidence_root,
        tool_script=Path(tool_script), review_commit=review_commit,
        repo_root=repo_root)
    worker_count = admission.get("worker_count")
    if (isinstance(worker_count, bool) or not isinstance(worker_count, int)
            or worker_count not in luna.CANDIDATE_GAME_WORKERS):
        raise ControllerError("population admission worker drift")
    if worker_count != capacity_obj.body["selected_workers"]:
        raise ControllerError("population admission worker differs from capacity")
    _validate_admission(admission, design=design, census=census_obj,
                        capacity=capacity_obj, worker_count=worker_count,
                        evidence_root=evidence_root, freeze=freeze, review=review)
    if report_path.exists() or report_path.is_symlink():
        return reopen_population_report(report_path, design=design,
                                        capacity=capacity_obj, census=census_obj,
                                        candidate_freeze=freeze,
                                        review_commit=review_commit,
                                        repo_root=repo_root,
                                        tool_script=tool_script)
    attempts_root = evidence_root / "attempts"
    roots = {tuple(row["coordinate"]): row["root_sha256"]
             for row in census_obj.body["coordinates"]}
    rows: list[dict[str, object]] = []
    for coordinate, mirror in design.mirror_assignments:
        attempt = attempts_root / ("-".join(map(str, coordinate))
                                   + f"-mirror-{mirror}")
        if (attempt / "manifest.json").is_file():
            try:
                row, _ = _row_from_attempt(attempt, coordinate, mirror,
                                           roots[coordinate])
            except Exception as exc:
                row = _missing_row(coordinate, mirror, error=type(exc).__name__)
        else:
            if attempt.is_dir() and not attempt.is_symlink():
                try:
                    execution.seal_pre_manifest_attempt(
                        attempt=attempt, coordinate=coordinate, mirror=mirror,
                        root_sha256=roots[coordinate])
                    row, _ = _row_from_attempt(attempt, coordinate, mirror,
                                               roots[coordinate])
                except Exception as exc:
                    raise ControllerError("pre-manifest attempt recovery refused") from exc
            else:
                row = _missing_row(coordinate, mirror)
        rows.append(row)
    successful = sum(row["status"] == "complete" for row in rows)
    clusters = sum(sum(row["coordinate"] == list(coord)
                        and row["status"] == "complete" for row in rows) == 2
                   for coord in design.deal_clusters)
    body = {"schema": POPULATION_REPORT_SCHEMA, "design": design.payload(),
            "census_sha256": census_obj.census_sha256,
            "capacity_receipt_sha256": capacity_obj.receipt_sha256,
            "admission_sha256": admission["admission_sha256"],
            "freeze_sha256": freeze["freeze_sha256"],
            "review_commit": review["review_commit"],
            "review_marker_sha256": review["review_marker_sha256"],
            "worker_count": worker_count, "rows": rows,
            "completed_games": len(rows), "successful_games": successful,
            "total_games": len(rows), "completed_deal_clusters": clusters,
            "total_deal_clusters": len(design.deal_clusters),
            "terminal_route": (luna.COMPLETE_ROUTE if successful == len(rows)
                               else luna.INCOMPLETE_ROUTE),
            "authority": dict(luna.AUTHORITY)}
    report = {**body, "report_sha256": _sha(body)}
    _publish(report_path, body, suffix="report_sha256")
    return report


def reopen_population_report(path: Path, *, design: luna.LunaDesign,
                             capacity: CapacityReceipt | Mapping[str, object],
                             census: luna.RootCensus | Mapping[str, object],
                             candidate_freeze: Mapping[str, object] | None = None,
                             launch_freeze: Mapping[str, object] | None = None,
                             review_commit: str | None = None,
                             repo_root: Path | None = None,
                             tool_script: Path | None = None) -> dict[str, object]:
    payload = _read_canonical(Path(path))
    _record_hash(payload, "report_sha256")
    expected_capacity = (capacity.receipt_sha256 if isinstance(capacity, CapacityReceipt)
                         else CapacityReceipt.reopen(capacity).receipt_sha256)
    capacity_obj = (capacity if isinstance(capacity, CapacityReceipt)
                    else CapacityReceipt.reopen(capacity))
    census_obj = (census if isinstance(census, luna.RootCensus)
                  else luna.RootCensus.reopen(census, design=design))
    freeze = candidate_freeze if candidate_freeze is not None else launch_freeze
    if freeze is None or review_commit is None or tool_script is None:
        raise ControllerError("authenticated source review admission required")
    review = authenticate_source_review(
        freeze=freeze, design=design, census=census_obj,
        capacity=capacity_obj, output_root=Path(path).parent,
        tool_script=Path(tool_script), review_commit=review_commit,
        repo_root=repo_root)
    expected_census = census_obj.census_sha256
    admission_path = Path(path).parent / "population-admission.json"
    admission = _read_canonical(admission_path)
    _record_hash(admission, "admission_sha256")
    admission_worker = admission.get("worker_count")
    if (isinstance(admission_worker, bool)
            or not isinstance(admission_worker, int)):
        raise ControllerError("population admission worker drift")
    if admission_worker != capacity_obj.body["selected_workers"]:
        raise ControllerError("population admission worker differs from capacity")
    _validate_admission(admission, design=design, census=census_obj,
                        capacity=capacity_obj, worker_count=admission_worker,
                        evidence_root=Path(path).parent, freeze=freeze,
                        review=review)
    if (payload.get("schema") != POPULATION_REPORT_SCHEMA
            or payload.get("design") != design.payload()
            or payload.get("capacity_receipt_sha256") != expected_capacity
            or payload.get("freeze_sha256") != freeze["freeze_sha256"]
            or payload.get("review_commit") != review["review_commit"]
            or payload.get("review_marker_sha256") != review["review_marker_sha256"]
            or payload.get("worker_count") != capacity_obj.body["selected_workers"]
            or payload.get("census_sha256") != expected_census
            or payload.get("admission_sha256") != admission["admission_sha256"]
            or payload.get("authority") != luna.AUTHORITY):
        raise ControllerError("population report binding drift")
    rows = payload.get("rows")
    schedule = tuple(design.mirror_assignments)
    if type(rows) is not list or len(rows) != len(schedule):
        raise ControllerError("population report rows drift")
    successes = 0
    clusters: dict[tuple[str, int, int], int] = {}
    for row, (coordinate, mirror) in zip(rows, schedule):
        if type(row) is not dict or set(row) != {"coordinate", "mirror",
                "cluster_key", "status", "attempt_path",
                "attempt_manifest_sha256", "trajectory_sha256",
                "terminal_receipt_sha256", "error"}:
            raise ControllerError("population report row schema drift")
        if (row["coordinate"] != list(coordinate)
                or row["cluster_key"] != list(coordinate)
                or row["mirror"] != mirror
                or not isinstance(row["attempt_path"], str)):
            raise ControllerError("population report row identity drift")
        if row["attempt_manifest_sha256"] is not None:
            _strict_sha(row["attempt_manifest_sha256"], "population manifest SHA")
        if row["status"] == "complete":
            successes += 1
            _strict_sha(row["trajectory_sha256"], "population trajectory SHA")
            _strict_sha(row["terminal_receipt_sha256"], "population receipt SHA")
            if row["error"] is not None:
                raise ControllerError("population complete error drift")
        elif row["status"] == "incomplete":
            if row["trajectory_sha256"] is not None or row["terminal_receipt_sha256"] is not None:
                raise ControllerError("population incomplete artifact drift")
            if row["error"] not in ("incomplete", "missing") \
                    and not isinstance(row["error"], str):
                raise ControllerError("population incomplete error drift")
        else:
            raise ControllerError("population report status drift")
        attempt_path = Path(path).parent / "attempts" / row["attempt_path"]
        if (Path(row["attempt_path"]).name != row["attempt_path"]
                or Path(row["attempt_path"]).is_absolute()
                or row["attempt_path"] != (
                    "-".join(map(str, coordinate)) + f"-mirror-{mirror}")):
            raise ControllerError("population attempt path drift")
        if row["attempt_manifest_sha256"] is None:
            if attempt_path.exists():
                raise ControllerError("population missing attempt drift")
        else:
            if not (attempt_path / "manifest.json").is_file():
                raise ControllerError("population attempt absent")
            try:
                actual, _ = _row_from_attempt(
                    attempt_path, coordinate, mirror,
                    next(row_data["root_sha256"] for row_data in census_obj.body["coordinates"]
                         if row_data["coordinate"] == list(coordinate)))
            except Exception as exc:
                raise ControllerError("population attempt reopen drift") from exc
            for field in ("attempt_manifest_sha256", "trajectory_sha256",
                          "terminal_receipt_sha256", "status"):
                if actual[field] != row[field]:
                    raise ControllerError("population attempt binding drift")
        key = tuple(coordinate)
        clusters[key] = clusters.get(key, 0) + (row["status"] == "complete")
    complete_clusters = sum(value == 2 for value in clusters.values())
    if (payload.get("completed_games") != len(rows)
            or payload.get("successful_games") != successes
            or payload.get("total_games") != len(schedule)
            or payload.get("completed_deal_clusters") != complete_clusters
            or payload.get("total_deal_clusters") != len(design.deal_clusters)
            or payload.get("terminal_route") != (
                luna.COMPLETE_ROUTE if successes == len(rows)
                else luna.INCOMPLETE_ROUTE)):
        raise ControllerError("population report accounting drift")
    return payload


__all__ = ["CAPACITY_SCHEMA", "CAPACITY_FAILURE_SCHEMA", "CAPACITY_WORKERS", "CAPACITY_ROUTE",
           "CAPACITY_REFUSE_ROUTE", "ControllerError", "SourceAdmissionError",
           "CapacityEvidenceRefusal", "CapacityMetric",
           "CapacityReceipt", "POPULATION_ADMISSION_SCHEMA", "run_capacity",
           "run_real_capacity", "validate_capacity_receipt", "LAUNCH_FREEZE_SCHEMA",
           "launch_freeze_payload", "validate_launch_freeze",
           "authenticate_source_review", "CANONICAL_REMOTE_URL",
           "run_source_population", "finalize_source_population",
           "reopen_population_report", "production_game_runner",
           "completed_artifact_game_runner", "CAPACITY_EXECUTION_SYNTHETIC",
           "CAPACITY_EXECUTION_VERIFIED", "publish_capacity_failure"]
