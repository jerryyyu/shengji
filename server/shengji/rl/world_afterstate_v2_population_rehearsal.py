"""Bounded, score-free rehearsal of the complete D256 population.

The rehearsal is an admission witness only.  It calls the reviewed population
controller once, reopens the controller receipt, and publishes one immutable
outer receipt after checking the complete ledger and the resource allowance.
No label, training, audit, terminal, retry, or resume seam is entered here.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import resource
import shutil
import subprocess
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence

from .belief_artifacts import publish_exclusive_bytes, stable_read_bytes
from .belief_contract import canonical_json_bytes
from .world_afterstate_v2_capacity_economics import (
    AMENDMENT_SCHEMA, CapacityEconomicsAmendmentV2,
)
from .world_afterstate_v2_freeze_inputs import (
    capacity_context, population_namespace, protocol_bytes,
    reopen_protocol_bytes,
)
from .world_afterstate_v2_population_controller import (
    CONTROLLER_DIRNAME, RECEIPT_NAME, collect_population_v2,
    reopen_population_collection_v2,
)
from .world_afterstate_v2_protocol import (
    AUTHORITY as PROTOCOL_AUTHORITY, D256_MAX_ATTEMPTS_PER_SLOT,
    TIER_SPECS, build_population_slot_ledger,
)


SCHEMA = "world-afterstate-v2-population-rehearsal-v1"
FREEZE_IDENTITY_SCHEMA = "world-afterstate-v2-population-rehearsal-freeze-v1"
ADMISSION_IDENTITY_SCHEMA = "world-afterstate-v2-population-rehearsal-admission-v1"
POPULATION_WALL_SECONDS_MAX = 2 * 60 * 60
HEARTBEAT_SECONDS = 60
EXPECTED_TIER = "D256"
EXPECTED_SLOT_COUNT = 256
DOWNSTREAM_NAMES = frozenset({
    "label", "labels", "training", "audit", "audit-attempt", "terminal",
    "terminal-controller", "label-controller", "training-controller",
})
AUTHORITY = dict(PROTOCOL_AUTHORITY)


class PopulationRehearsalError(ValueError):
    """The bounded rehearsal or its immutable receipt was refused."""


def _capacity_source_sha256(repo: Path) -> str:
    # Lazy import avoids a cycle: the final freeze builder imports this module
    # to authenticate the rehearsal receipt that it binds.
    from .world_afterstate_v2_freeze_builder import capacity_source_sha256
    return capacity_source_sha256(repo)


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _digest(value: object, label: str, *, length: int = 64) -> str:
    if (type(value) is not str or len(value) != length
            or any(char not in "0123456789abcdef" for char in value)):
        raise PopulationRehearsalError(f"{label} drift")
    return value


def _head(value: object) -> str:
    return _digest(value, "expected source head", length=40)


def _positive(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise PopulationRehearsalError(f"{label} drift")
    return value


def _strict_json(raw: bytes, label: str) -> dict[str, Any]:
    if type(raw) is not bytes or not raw:
        raise PopulationRehearsalError(f"{label} bytes drift")
    try:
        value = json.loads(raw.decode("ascii"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise PopulationRehearsalError(f"{label} is not canonical JSON") from exc
    if type(value) is not dict or canonical_json_bytes(value) != raw:
        raise PopulationRehearsalError(f"{label} is not canonical JSON")
    return value


def _read(path: Path, label: str) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise PopulationRehearsalError(f"{label} path drift")
    try:
        return stable_read_bytes(path)
    except Exception as exc:
        raise PopulationRehearsalError(f"{label} read refused") from exc


def _ensure_head_clean(expected_head: str, *, repo: Path | None = None) -> None:
    expected_head = _head(expected_head)
    repo = Path(repo) if repo is not None else Path(__file__).resolve().parents[3]
    def git(*args: str) -> str:
        result = subprocess.run(("git", "-C", str(repo), *args),
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                check=False)
        if result.returncode:
            raise PopulationRehearsalError("source Git command refused")
        return result.stdout.decode("utf-8")
    if git("rev-parse", "HEAD").strip() != expected_head:
        raise PopulationRehearsalError("source head drift")
    if git("status", "--porcelain=v1", "--untracked-files=all").strip():
        raise PopulationRehearsalError("source tree is dirty")


def _identity(schema: str, *, source_git: str, protocol_sha256: str,
              capacity_sha256: str, namespace: str) -> str:
    body = {
        "schema": schema, "source_git": _head(source_git),
        "protocol_sha256": _digest(protocol_sha256, "protocol SHA-256"),
        "capacity_economics_sha256": _digest(capacity_sha256, "capacity SHA-256"),
        "population_namespace_sha256": _digest(namespace, "population namespace"),
        "tier": EXPECTED_TIER,
    }
    return _sha(body)


def rehearsal_identities(source_git: str, protocol_sha256: str,
                         capacity_sha256: str, namespace: str) -> tuple[str, str]:
    """Derive distinct deterministic freeze and admission identities."""
    freeze = _identity(FREEZE_IDENTITY_SCHEMA, source_git=source_git,
                       protocol_sha256=protocol_sha256,
                       capacity_sha256=capacity_sha256, namespace=namespace)
    admission = _identity(ADMISSION_IDENTITY_SCHEMA, source_git=source_git,
                          protocol_sha256=protocol_sha256,
                          capacity_sha256=capacity_sha256, namespace=namespace)
    if freeze == admission:
        raise PopulationRehearsalError("rehearsal identity collision")
    return freeze, admission


def _path_names(root: Path) -> tuple[str, ...]:
    if not root.exists():
        return ()
    if root.is_symlink() or not root.is_dir():
        raise PopulationRehearsalError("population root path drift")
    found = []
    allowed_top = {"population", CONTROLLER_DIRNAME}
    for child in root.iterdir():
        if child.name not in allowed_top:
            found.append(child.relative_to(root).as_posix())
        elif child.is_symlink() or not child.is_dir():
            raise PopulationRehearsalError("population namespace path drift")
    for path in root.rglob("*"):
        if path.is_dir() and path.name in DOWNSTREAM_NAMES:
            found.append(path.relative_to(root).as_posix())
    return tuple(sorted(found))


def _new_root(root: Path) -> None:
    if root.exists() or root.is_symlink():
        raise PopulationRehearsalError(
            "population rehearsal refuses retry or resume")


def _slot_payload(value: object) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    if hasattr(value, "payload"):
        result = value.payload()
        if isinstance(result, Mapping):
            return result
    if hasattr(value, "__dict__") and isinstance(vars(value), dict):
        return vars(value)
    raise PopulationRehearsalError("population slot receipt drift")


def _collection_payload(value: object) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    if hasattr(value, "payload"):
        result = value.payload()
        if isinstance(result, Mapping):
            return result
    if hasattr(value, "__dict__") and isinstance(vars(value), dict):
        return vars(value)
    raise PopulationRehearsalError("population receipt drift")


def _aggregate(collection: object, *, namespace: str, freeze: str,
               admission: str, workers: int) -> tuple[dict[str, int], dict[str, int],
                                                        int, dict[str, int], str]:
    payload = _collection_payload(collection)
    if (payload.get("tier") != EXPECTED_TIER
            or payload.get("population_namespace_sha256") != namespace
            or payload.get("freeze_sha256") != freeze
            or payload.get("admission_sha256") != admission
            or payload.get("max_attempts_per_slot") != D256_MAX_ATTEMPTS_PER_SLOT
            or payload.get("accepted_slots") != EXPECTED_SLOT_COUNT):
        raise PopulationRehearsalError("population receipt external binding drift")
    rows = payload.get("slots")
    slots = build_population_slot_ledger(TIER_SPECS[0])
    if type(rows) is not list or len(rows) != EXPECTED_SLOT_COUNT:
        raise PopulationRehearsalError("population receipt does not prove 256 slots")
    groups = {"natural-fit": 0, "mechanics-fit": 0,
              "natural-select": 0, "natural-audit": 0}
    pairs = {"natural": set(), "mechanics": set()}
    attempts = 0
    reasons: dict[str, int] = {}
    for slot, raw_row in zip(slots, rows):
        row = _slot_payload(raw_row)
        if (row.get("slot_sha256") != slot.slot_sha256
                or row.get("tier") != slot.tier
                or row.get("split") != slot.split
                or row.get("source") != slot.source
                or row.get("ordinal") != slot.ordinal):
            raise PopulationRehearsalError("population receipt slot binding drift")
        group = f"{slot.source}-{slot.split}"
        if group not in groups:
            raise PopulationRehearsalError("population receipt downstream group drift")
        groups[group] += 1
        if slot.split == "fit":
            pairs[slot.source].add(slot.fit_pair_id)
        count = row.get("attempt_count")
        attempts += _positive(count, "population attempt count")
        rejection_rows = row.get("rejection_counts")
        if type(rejection_rows) is not list:
            raise PopulationRehearsalError("population rejection accounting drift")
        for item in rejection_rows:
            if type(item) is not list or len(item) != 2:
                raise PopulationRehearsalError("population rejection accounting drift")
            reason, amount = item
            amount = _positive(amount, "population rejection count")
            if type(reason) is not str:
                raise PopulationRehearsalError("population rejection reason drift")
            reasons[reason] = reasons.get(reason, 0) + amount
    if groups != {"natural-fit": 128, "mechanics-fit": 32,
                  "natural-select": 48, "natural-audit": 48}:
        raise PopulationRehearsalError("population group census drift")
    if {key: len(value) for key, value in pairs.items()} != {
            "natural": 64, "mechanics": 16}:
        raise PopulationRehearsalError("population fit-pair census drift")
    if payload.get("attempts_total") != attempts:
        raise PopulationRehearsalError("population attempt total drift")
    _positive(workers, "population workers")
    population_sha = _digest(payload.get("population_sha256"), "population SHA-256")
    return groups, {key: len(value) for key, value in pairs.items()}, attempts, dict(sorted(reasons.items())), population_sha


def _rss_bytes() -> int:
    value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    # macOS reports bytes; Linux reports KiB.
    return value if os.uname().sysname == "Darwin" else value * 1024


def _probe(probes: Mapping[str, Callable[..., int]] | None,
           name: str, fallback: Callable[..., int], *args: Any) -> int:
    probe = (probes.get(name) if isinstance(probes, Mapping)
             else getattr(probes, name, None)) if probes else None
    value = (probe or fallback)(*args)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise PopulationRehearsalError(f"{name} probe drift")
    return value


def _clock_value(clock: Any, name: str) -> int:
    probe = clock.get(name) if isinstance(clock, Mapping) else getattr(clock, name, None)
    if not callable(probe):
        raise PopulationRehearsalError("clock probe drift")
    return probe()


@dataclass(frozen=True)
class PopulationRehearsalReceiptV2:
    source_git: str
    population_root: str
    protocol_sha256: str
    capacity_economics_sha256: str
    population_namespace_sha256: str
    freeze_sha256: str
    admission_sha256: str
    population_receipt_sha256: str
    population_sha256: str
    tier: str
    slot_count: int
    max_attempts_per_slot: int
    deadline_seconds: int
    heartbeat_seconds: int
    workers: int
    group_counts: dict[str, int]
    fit_pair_counts: dict[str, int]
    attempts_total: int
    rejection_counts: dict[str, int]
    elapsed_wall_ns: int
    process_cpu_ns: int
    peak_rss_bytes: int
    disk_free_before_bytes: int
    disk_free_after_bytes: int
    downstream_paths: tuple[str, ...]
    authority: dict[str, bool]
    schema: str = SCHEMA
    rehearsal_sha256: str = ""

    def _body(self) -> dict[str, Any]:
        return {"schema": self.schema, "source_git": self.source_git,
                "population_root": self.population_root,
                "protocol_sha256": self.protocol_sha256,
                "capacity_economics_sha256": self.capacity_economics_sha256,
                "population_namespace_sha256": self.population_namespace_sha256,
                "freeze_sha256": self.freeze_sha256,
                "admission_sha256": self.admission_sha256,
                "population_receipt_sha256": self.population_receipt_sha256,
                "population_sha256": self.population_sha256, "tier": self.tier,
                "slot_count": self.slot_count,
                "max_attempts_per_slot": self.max_attempts_per_slot,
                "deadline_seconds": self.deadline_seconds,
                "heartbeat_seconds": self.heartbeat_seconds, "workers": self.workers,
                "group_counts": dict(self.group_counts),
                "fit_pair_counts": dict(self.fit_pair_counts),
                "attempts_total": self.attempts_total,
                "rejection_counts": dict(self.rejection_counts),
                "elapsed_wall_ns": self.elapsed_wall_ns,
                "process_cpu_ns": self.process_cpu_ns,
                "peak_rss_bytes": self.peak_rss_bytes,
                "disk_free_before_bytes": self.disk_free_before_bytes,
                "disk_free_after_bytes": self.disk_free_after_bytes,
                "downstream_paths": list(self.downstream_paths),
                "authority": dict(self.authority)}

    def validate(self) -> None:
        if self.schema != SCHEMA or self.tier != EXPECTED_TIER:
            raise PopulationRehearsalError("rehearsal schema or tier drift")
        _head(self.source_git)
        if (type(self.population_root) is not str
                or not Path(self.population_root).is_absolute()):
            raise PopulationRehearsalError("population root binding drift")
        for value, label in ((self.protocol_sha256, "protocol SHA-256"),
                             (self.capacity_economics_sha256, "capacity SHA-256"),
                             (self.population_namespace_sha256, "population namespace"),
                             (self.freeze_sha256, "freeze SHA-256"),
                             (self.admission_sha256, "admission SHA-256"),
                             (self.population_receipt_sha256, "population receipt SHA-256"),
                             (self.population_sha256, "population SHA-256")):
            _digest(value, label)
        if self.freeze_sha256 == self.admission_sha256:
            raise PopulationRehearsalError("rehearsal identities are not distinct")
        if (self.slot_count != 256 or self.max_attempts_per_slot != 128
                or self.deadline_seconds != POPULATION_WALL_SECONDS_MAX
                or self.heartbeat_seconds < 1 or self.heartbeat_seconds > 60):
            raise PopulationRehearsalError("rehearsal resource contract drift")
        _positive(self.workers, "population workers")
        if self.group_counts != {"natural-fit": 128, "mechanics-fit": 32,
                                 "natural-select": 48, "natural-audit": 48}:
            raise PopulationRehearsalError("rehearsal group census drift")
        if self.fit_pair_counts != {"natural": 64, "mechanics": 16}:
            raise PopulationRehearsalError("rehearsal fit-pair census drift")
        _positive(self.attempts_total, "rehearsal attempts")
        for key, value in self.rejection_counts.items():
            if type(key) is not str:
                raise PopulationRehearsalError("rehearsal rejection reason drift")
            _positive(value, "rehearsal rejection count")
        for value, label in ((self.elapsed_wall_ns, "elapsed wall"),
                             (self.process_cpu_ns, "process CPU"),
                             (self.peak_rss_bytes, "peak RSS"),
                             (self.disk_free_before_bytes, "disk before"),
                             (self.disk_free_after_bytes, "disk after")):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise PopulationRehearsalError(f"{label} metric drift")
        if self.elapsed_wall_ns > self.deadline_seconds * 1_000_000_000:
            raise PopulationRehearsalError("rehearsal wall allowance exceeded")
        if type(self.downstream_paths) is not tuple or self.downstream_paths:
            raise PopulationRehearsalError("downstream namespace is occupied")
        if self.authority != AUTHORITY or any(self.authority.values()):
            raise PopulationRehearsalError("rehearsal authority drift")
        expected = _sha(self._body())
        if self.rehearsal_sha256 != expected:
            raise PopulationRehearsalError("rehearsal receipt self hash drift")

    def payload(self) -> dict[str, Any]:
        self.validate()
        return {**self._body(), "rehearsal_sha256": self.rehearsal_sha256}


def _make_receipt(**kwargs: Any) -> PopulationRehearsalReceiptV2:
    provisional = PopulationRehearsalReceiptV2(**kwargs, rehearsal_sha256="")
    value = PopulationRehearsalReceiptV2(**kwargs,
        rehearsal_sha256=_sha(provisional._body()))
    value.validate()
    return value


def reopen_population_rehearsal(
        value: Mapping[str, Any] | bytes | str | Path,
        *, root: Path | str | None = None,
        receipt: Mapping[str, Any] | bytes | Path | None = None,
        capacity_raw: bytes | None = None,
        expected_head: str | None = None) -> PopulationRehearsalReceiptV2:
    """Reopen an outer receipt and prove its immutable collection binding."""
    # Match the repository's existing ``reopen_...(output, receipt=...)``
    # convention while also allowing a receipt payload/path directly.
    if receipt is not None:
        if root is not None:
            raise PopulationRehearsalError("duplicate rehearsal root")
        root = Path(value) if isinstance(value, (str, Path)) else None
        value = receipt
    if isinstance(value, Path):
        raw = _read(value, "rehearsal receipt")
        payload = _strict_json(raw, "rehearsal receipt")
    elif type(value) is bytes:
        payload = _strict_json(value, "rehearsal receipt")
    elif isinstance(value, Mapping):
        payload = dict(value)
        if canonical_json_bytes(payload) != canonical_json_bytes(dict(payload)):
            raise PopulationRehearsalError("rehearsal receipt mapping drift")
    else:
        raise PopulationRehearsalError("rehearsal receipt input drift")
    required = set(PopulationRehearsalReceiptV2.__dataclass_fields__)
    if set(payload) != required:
        raise PopulationRehearsalError("rehearsal receipt field population drift")
    try:
        result = PopulationRehearsalReceiptV2(
            **{key: (tuple(payload[key]) if key == "downstream_paths" else payload[key])
               for key in required})
        result.validate()
    except PopulationRehearsalError:
        raise
    except Exception as exc:
        raise PopulationRehearsalError("rehearsal receipt reconstruction refused") from exc
    bound_root = Path(result.population_root)
    if root is not None and Path(root).resolve(strict=False) != bound_root:
        raise PopulationRehearsalError("population root binding drift")
    if root is None and expected_head is not None:
        root = bound_root
    if root is not None:
        root = Path(root)
        observed = _path_names(root)
        if observed:
            raise PopulationRehearsalError("downstream namespace is occupied")
        collection_path = root / CONTROLLER_DIRNAME / RECEIPT_NAME
        collection_raw = _read(collection_path, "population collection receipt")
        collection_payload_raw = _strict_json(
            collection_raw, "population collection receipt")
        collection = reopen_population_collection_v2(
            root, freeze_sha256=result.freeze_sha256,
            population_namespace_sha256=result.population_namespace_sha256,
            admission_sha256=result.admission_sha256,
            max_attempts_per_slot=result.max_attempts_per_slot)
        if _collection_payload(collection) != collection_payload_raw:
            raise PopulationRehearsalError("population receipt reopener drift")
        groups, pairs, attempts, reasons, population_sha = _aggregate(
            collection, namespace=result.population_namespace_sha256,
            freeze=result.freeze_sha256, admission=result.admission_sha256,
            workers=result.workers)
        if (_sha_bytes(collection_raw) != result.population_receipt_sha256
                or population_sha != result.population_sha256
                or groups != result.group_counts or pairs != result.fit_pair_counts
                or attempts != result.attempts_total or reasons != result.rejection_counts):
            raise PopulationRehearsalError("population receipt binding drift")
    if expected_head is not None:
        expected_head = _head(expected_head)
        raw_protocol = protocol_bytes()
        reopen_protocol_bytes(raw_protocol)
        capacity_value = capacity_raw
        if capacity_value is None:
            raise PopulationRehearsalError("capacity bytes required for binding proof")
        cap, tier, population_workers, _label = capacity_context(capacity_value)
        cap_schema = cap.get("schema") if isinstance(cap, Mapping) else getattr(cap, "schema", None)
        cap_deadline = (cap.get("population_wall_seconds_max")
                        if isinstance(cap, Mapping)
                        else getattr(cap, "population_wall_seconds_max", None))
        cap_execution_git = (cap.get("execution_git")
                             if isinstance(cap, Mapping)
                             else getattr(cap, "execution_git", None))
        if (tier != EXPECTED_TIER or cap_schema != AMENDMENT_SCHEMA
                or cap_deadline != POPULATION_WALL_SECONDS_MAX
                or cap_execution_git != expected_head
                or result.workers != population_workers):
            raise PopulationRehearsalError("capacity tier binding drift")
        namespace = population_namespace(
            expected_head, _sha_bytes(raw_protocol), _sha_bytes(capacity_value),
            EXPECTED_TIER)
        freeze, admission = rehearsal_identities(
            expected_head, _sha_bytes(raw_protocol), _sha_bytes(capacity_value),
            namespace)
        if (result.source_git, result.protocol_sha256,
                result.capacity_economics_sha256,
                result.population_namespace_sha256, result.freeze_sha256,
                result.admission_sha256) != (
                    expected_head, _sha_bytes(raw_protocol),
                    _sha_bytes(capacity_value), namespace, freeze, admission):
            raise PopulationRehearsalError("rehearsal source binding drift")
    return result


def run_population_rehearsal_v2(
        capacity: Path | str | bytes, root: Path | str, receipt: Path | str,
        *, expected_head: str, progress: Path | str | None = None,
        clock: Any = time, resource_probes: Mapping[str, Callable[..., int]] | None = None,
        clean_repo: Path | str | None = None) -> PopulationRehearsalReceiptV2:
    """Run exactly one fresh full-D256 population rehearsal."""
    expected_head = _head(expected_head)
    root, receipt = Path(root), Path(receipt)
    resolved_root = root.resolve(strict=False)
    resolved_receipt = receipt.resolve(strict=False)
    if (resolved_receipt == resolved_root
            or resolved_root in resolved_receipt.parents):
        raise PopulationRehearsalError(
            "rehearsal receipt must be outside population root")
    if receipt.exists() or receipt.is_symlink():
        raise PopulationRehearsalError("rehearsal receipt already exists")
    repo = (Path(clean_repo) if clean_repo is not None
            else Path(__file__).resolve().parents[3])
    _ensure_head_clean(expected_head, repo=repo)
    _new_root(root)
    root.parent.mkdir(parents=True, exist_ok=True)
    capacity_raw = capacity if type(capacity) is bytes else _read(Path(capacity), "capacity amendment")
    capacity_sha = _sha_bytes(capacity_raw)
    try:
        cap, tier, workers, _label_workers = capacity_context(capacity_raw)
    except Exception as exc:
        raise PopulationRehearsalError("capacity amendment reopen refused") from exc
    cap_schema = (cap.get("schema") if isinstance(cap, Mapping)
                  else getattr(cap, "schema", None))
    cap_deadline = (cap.get("population_wall_seconds_max")
                    if isinstance(cap, Mapping)
                    else getattr(cap, "population_wall_seconds_max", None))
    cap_execution_git = (cap.get("execution_git") if isinstance(cap, Mapping)
                         else getattr(cap, "execution_git", None))
    cap_source_sha = (cap.get("source_sha256") if isinstance(cap, Mapping)
                      else getattr(cap, "source_sha256", None))
    if (cap_schema != AMENDMENT_SCHEMA or tier != EXPECTED_TIER
            or cap_execution_git != expected_head
            or cap_source_sha != _capacity_source_sha256(repo)):
        raise PopulationRehearsalError("current capacity economics amendment required")
    if cap_deadline != POPULATION_WALL_SECONDS_MAX:
        raise PopulationRehearsalError("population deadline amendment binding drift")
    raw_protocol = protocol_bytes()
    try:
        protocol = reopen_protocol_bytes(raw_protocol)
    except Exception as exc:
        raise PopulationRehearsalError("authoritative protocol reopen refused") from exc
    del protocol
    protocol_sha = _sha_bytes(raw_protocol)
    namespace = population_namespace(expected_head, protocol_sha, capacity_sha, EXPECTED_TIER)
    freeze, admission = rehearsal_identities(expected_head, protocol_sha, capacity_sha, namespace)
    if progress is not None:
        progress = Path(progress)
        resolved_progress = progress.resolve(strict=False)
        if (resolved_progress == resolved_root
                or resolved_root in resolved_progress.parents):
            raise PopulationRehearsalError(
                "progress path must be outside population root")
        if progress.exists() or progress.is_symlink():
            raise PopulationRehearsalError("progress path already exists")
        progress.parent.mkdir(parents=True, exist_ok=True)
    def emit(item: dict[str, Any]) -> None:
        if progress is not None:
            with progress.open("ab") as handle:
                handle.write(canonical_json_bytes(item))
                handle.flush()
                os.fsync(handle.fileno())
    wall_start = _clock_value(clock, "monotonic_ns")
    cpu_start = _clock_value(clock, "process_time_ns")
    disk_before = _probe(resource_probes, "disk_free_bytes",
                          lambda path: shutil.disk_usage(path).free, root.parent)
    emit({"event": "start", "tier": EXPECTED_TIER, "workers": workers})
    try:
        collect_population_v2(
            root, freeze_sha256=freeze, population_namespace_sha256=namespace,
            admission_sha256=admission, max_attempts_per_slot=D256_MAX_ATTEMPTS_PER_SLOT,
            workers=workers, tier=EXPECTED_TIER,
            deadline_seconds=POPULATION_WALL_SECONDS_MAX,
            heartbeat_seconds=HEARTBEAT_SECONDS,
            progress_callback=emit)
        collection_path = root / CONTROLLER_DIRNAME / RECEIPT_NAME
        collection_raw = _read(collection_path, "population collection receipt")
        collection_payload_raw = _strict_json(
            collection_raw, "population collection receipt")
        collection = reopen_population_collection_v2(
            root, freeze_sha256=freeze,
            population_namespace_sha256=namespace,
            admission_sha256=admission,
            max_attempts_per_slot=D256_MAX_ATTEMPTS_PER_SLOT)
        if _collection_payload(collection) != collection_payload_raw:
            raise PopulationRehearsalError("population receipt reopener drift")
        groups, pairs, attempts, reasons, population_sha = _aggregate(
            collection, namespace=namespace, freeze=freeze,
            admission=admission, workers=workers)
        downstream = _path_names(root)
        if downstream:
            raise PopulationRehearsalError("downstream namespace is occupied")
        disk_after = _probe(resource_probes, "disk_free_bytes",
                            lambda path: shutil.disk_usage(path).free, root)
        cpu_end = _clock_value(clock, "process_time_ns")
        wall_end = _clock_value(clock, "monotonic_ns")
        elapsed = wall_end - wall_start
        cpu = cpu_end - cpu_start
        if elapsed < 0 or cpu < 0:
            raise PopulationRehearsalError("clock probe moved backwards")
        if elapsed > POPULATION_WALL_SECONDS_MAX * 1_000_000_000:
            raise PopulationRehearsalError("rehearsal wall allowance exceeded")
        collection_payload = _collection_payload(collection)
        result = _make_receipt(
            source_git=expected_head, population_root=str(resolved_root),
            protocol_sha256=protocol_sha,
            capacity_economics_sha256=capacity_sha,
            population_namespace_sha256=namespace, freeze_sha256=freeze,
            admission_sha256=admission,
            population_receipt_sha256=_sha_bytes(collection_raw),
            population_sha256=population_sha, tier=EXPECTED_TIER,
            slot_count=EXPECTED_SLOT_COUNT,
            max_attempts_per_slot=D256_MAX_ATTEMPTS_PER_SLOT,
            deadline_seconds=POPULATION_WALL_SECONDS_MAX,
            heartbeat_seconds=HEARTBEAT_SECONDS, workers=workers,
            group_counts=groups, fit_pair_counts=pairs, attempts_total=attempts,
            rejection_counts=reasons, elapsed_wall_ns=elapsed,
            process_cpu_ns=cpu,
            peak_rss_bytes=_probe(resource_probes, "peak_rss_bytes", _rss_bytes),
            disk_free_before_bytes=disk_before, disk_free_after_bytes=disk_after,
            downstream_paths=tuple(downstream), authority=dict(AUTHORITY))
        if collection_payload.get("population_sha256") != result.population_sha256:
            raise PopulationRehearsalError("population SHA binding drift")
        receipt.parent.mkdir(parents=True, exist_ok=True)
        publish_exclusive_bytes(receipt, canonical_json_bytes(result.payload()))
        return result
    except PopulationRehearsalError:
        raise
    except Exception as exc:
        raise PopulationRehearsalError("population rehearsal failed") from exc


# Descriptive aliases for launch/review callers.
run_full_population_rehearsal_v2 = run_population_rehearsal_v2
run_population_rehearsal = run_population_rehearsal_v2
reopen_full_population_rehearsal_v2 = reopen_population_rehearsal
reopen_population_rehearsal_v2 = reopen_population_rehearsal
PopulationRehearsalReceipt = PopulationRehearsalReceiptV2


__all__ = [
    "ADMISSION_IDENTITY_SCHEMA", "AUTHORITY", "EXPECTED_TIER",
    "FREEZE_IDENTITY_SCHEMA", "HEARTBEAT_SECONDS", "POPULATION_WALL_SECONDS_MAX",
    "PopulationRehearsalError", "PopulationRehearsalReceiptV2",
    "PopulationRehearsalReceipt", "rehearsal_identities",
    "run_population_rehearsal_v2", "run_full_population_rehearsal_v2",
    "run_population_rehearsal",
    "reopen_population_rehearsal", "reopen_population_rehearsal_v2",
    "reopen_full_population_rehearsal_v2",
]
