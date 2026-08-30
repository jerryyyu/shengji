"""Progressive immutable artifact references for the Value-Afterstate V2 DAG.

The DAG stores references, not producer payloads.  A node is published only
after its predecessors have been reopened and each output has been written as
an independent immutable file.  This deliberately keeps a resume operation
small: a valid node can be reopened without reading any downstream payload.
"""

from __future__ import annotations

import hashlib
import json
import ctypes
import errno
import os
import stat
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .belief_artifacts import stable_read_bytes
from .belief_contract import canonical_json_bytes
from .world_afterstate_v2_terminal_provenance import (
    IndependentReconstructionReceiptV2,
    RECONSTRUCTION_SCHEMA,
    validate_independent_reconstruction_v2,
)


SCHEMA = "world-afterstate-v2-dag-node-manifest-v2"
MANIFEST_SCHEMA = SCHEMA
OUTPUT_SCHEMA = "world-afterstate-v2-dag-output-v2"
NODES_DIRNAME = "nodes"
MANIFEST_NAME = "manifest.json"
RECONSTRUCTION_RECEIPT_PATH = "terminal/independent-reconstruction.json"

# This order is part of the frozen V2 review surface.  All six cohort nodes
# are siblings after nested-curve and can therefore be scheduled independently.
NODE_NAMES = (
    "population", "p0-labels-gates", "optimizer-canary", "nested-curve",
    "block-1-natural", "block-1-action-association-permutation",
    "block-1-label-permutation", "block-1-complete-world-shuffle",
    "block-2-natural", "block-2-complete-world-shuffle",
    "precision-select-power", "audit-attempt", "terminal", "reconstruction",
)
EXPECTED_NODES = NODE_NAMES

_BLOCK_1_CONTROLS = (
    "block-1-action-association-permutation",
    "block-1-label-permutation",
    "block-1-complete-world-shuffle",
)
_COHORTS = (
    "block-1-natural", *_BLOCK_1_CONTROLS, "block-2-natural",
    "block-2-complete-world-shuffle",
)
_SIX_COHORT_FRONTIER = _COHORTS

# A terminal result can be reached before audit opening.  The second terminal
# predecessor alternative is used only after the audit node has been sealed.
NODE_DEPENDENCIES: dict[str, tuple[str, ...] | tuple[tuple[str, ...], ...]] = {
    "population": (),
    "p0-labels-gates": ("population",),
    "optimizer-canary": ("p0-labels-gates",),
    "nested-curve": ("optimizer-canary",),
    "block-1-natural": ("nested-curve",),
    "block-1-action-association-permutation": ("nested-curve",),
    "block-1-label-permutation": ("nested-curve",),
    "block-1-complete-world-shuffle": ("nested-curve",),
    "block-2-natural": ("nested-curve",),
    "block-2-complete-world-shuffle": ("nested-curve",),
    "precision-select-power": _SIX_COHORT_FRONTIER,
    "audit-attempt": ("precision-select-power",),
    "terminal": (("p0-labels-gates",), ("optimizer-canary",),
                  ("nested-curve",), _SIX_COHORT_FRONTIER,
                  ("precision-select-power",), ("audit-attempt",)),
    "reconstruction": ("terminal",),
}
CANONICAL_DEPENDENCIES = NODE_DEPENDENCIES

# No node publication grants execution, audit, training, gameplay, or claims.
AUTHORITY: dict[str, bool] = {
    "data_collection_authorized": False,
    "audit_opening_authorized": False,
    "training_authorized": False,
    "gameplay_authorized": False,
    "strength_claim_authorized": False,
    "writer_authorized": False,
    "terminal_reconstruction_authorized": False,
}


class DagArtifactError(ValueError):
    """A DAG path, manifest, dependency, or immutable output was refused."""


WorldAfterstateV2DagArtifactError = DagArtifactError


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _digest(value: object, label: str) -> str:
    if type(value) is not str or len(value) != 64 \
            or any(char not in "0123456789abcdef" for char in value):
        raise DagArtifactError(f"{label} drift")
    return value


def _count(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise DagArtifactError(f"{label} drift")
    return value


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DagArtifactError("DAG JSON has duplicate key")
        result[key] = value
    return result


def _reject_number(value: str) -> None:
    raise DagArtifactError(f"DAG JSON contains invalid number {value}")


def _strict_json(raw: bytes, label: str) -> dict[str, Any]:
    if type(raw) is not bytes or not raw:
        raise DagArtifactError(f"{label} is empty")
    try:
        value = json.loads(raw.decode("ascii"), object_pairs_hook=_strict_object,
                           parse_float=_reject_number,
                           parse_constant=_reject_number)
    except DagArtifactError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DagArtifactError(f"{label} is not strict JSON") from exc
    if type(value) is not dict or canonical_json_bytes(value) != raw:
        raise DagArtifactError(f"{label} is not canonical JSON")
    return value


def _valid_node(node: object) -> str:
    if type(node) is not str or node not in NODE_NAMES:
        raise DagArtifactError("DAG node identity drift")
    return node


def _safe_relative(value: object, label: str) -> str:
    if type(value) is not str or not value or value.startswith("/") \
            or "\\" in value:
        raise DagArtifactError(f"{label} path drift")
    path = Path(value)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts) \
            or path.as_posix() != value:
        raise DagArtifactError(f"{label} path drift")
    return value


def _root(root: Path) -> Path:
    if not isinstance(root, Path) or root.is_symlink() or not root.is_dir():
        raise DagArtifactError("DAG artifact root drift")
    return root


def _directory(path: Path, *, create: bool = False) -> Path:
    if path.is_symlink():
        raise DagArtifactError("DAG directory is a symlink")
    if create:
        try:
            path.mkdir(mode=0o700, parents=True, exist_ok=True)
        except OSError as exc:
            raise DagArtifactError("DAG directory creation refused") from exc
    if path.is_symlink() or not path.is_dir():
        raise DagArtifactError("DAG directory drift")
    return path


def _nodes_dir(root: Path, *, create: bool = False) -> Path:
    root = _root(root)
    return _directory(root / NODES_DIRNAME, create=create)


def _node_dir(root: Path, node: str, *, create: bool = False) -> Path:
    node = _valid_node(node)
    return _directory(_nodes_dir(root, create=create) / node, create=create)


def _safe_file(root: Path, relative: str) -> Path:
    relative = _safe_relative(relative, "DAG manifest")
    path = root / Path(relative)
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise DagArtifactError("DAG path escapes root") from exc
    cursor = root
    for part in path.relative_to(root).parts[:-1]:
        cursor = cursor / part
        if cursor.is_symlink() or not cursor.is_dir():
            raise DagArtifactError("DAG manifest parent directory drift")
    return path


def _read(path: Path, label: str) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise DagArtifactError(f"{label} is not a regular file")
    try:
        return stable_read_bytes(path)
    except (OSError, ValueError) as exc:
        raise DagArtifactError(f"{label} stable read refused") from exc


def _rename_noreplace(source: Path, destination: Path) -> None:
    """Atomically install ``source`` without replacing ``destination``."""
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
            raise DagArtifactError("atomic no-replace publication is unavailable")
    except AttributeError as exc:
        raise DagArtifactError(
            "atomic no-replace publication is unavailable") from exc
    if result == 0:
        return
    error = ctypes.get_errno()
    if error in (errno.EEXIST, errno.ENOTEMPTY):
        raise FileExistsError(error, os.strerror(error), destination)
    raise OSError(error, os.strerror(error), destination)


def _publish_idempotent_bytes(path: Path, raw: bytes, label: str) -> str:
    """Publish immutable bytes and accept only a byte-identical race winner."""
    if not isinstance(path, Path) or type(raw) is not bytes or not raw \
            or path.is_symlink() or not path.parent.is_dir() \
            or path.parent.is_symlink():
        raise DagArtifactError(f"{label} publication input drift")

    def existing_matches() -> str:
        existing = _read(path, label)
        if existing != raw:
            raise DagArtifactError(f"{label} divergent immutable replay refused")
        return _sha(raw)

    if path.exists() or path.is_symlink():
        return existing_matches()
    descriptor: int | None = None
    temporary: Path | None = None
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
            raise DagArtifactError(f"{label} temporary slot unavailable")
        offset = 0
        while offset < len(raw):
            written = os.write(descriptor, raw[offset:])
            if written <= 0:
                raise DagArtifactError(f"{label} write made no progress")
            offset += written
        os.fsync(descriptor)
        temporary_stat = os.fstat(descriptor)
        if not stat.S_ISREG(temporary_stat.st_mode) \
                or temporary_stat.st_nlink != 1 \
                or stat.S_IMODE(temporary_stat.st_mode) != 0o400:
            raise DagArtifactError(f"{label} temporary identity drift")
        os.close(descriptor)
        descriptor = None
        try:
            _rename_noreplace(temporary, path)
        except FileExistsError:
            return existing_matches()
        temporary = None
        digest = existing_matches()
        parent = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
        return digest
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary is not None:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass


@dataclass(frozen=True)
class ArtifactRefV2:
    """A root-relative, content-addressed reference to one immutable file."""

    relative_path: str
    schema: str
    sha256: str
    byte_count: int

    def __post_init__(self) -> None:
        _safe_relative(self.relative_path, "artifact")
        if type(self.schema) is not str or not self.schema:
            raise DagArtifactError("artifact schema drift")
        _digest(self.sha256, "artifact SHA-256")
        _count(self.byte_count, "artifact byte count")

    def to_dict(self) -> dict[str, Any]:
        return {"relative_path": self.relative_path, "schema": self.schema,
                "sha256": self.sha256, "byte_count": self.byte_count}

    @property
    def path(self) -> str:
        return self.relative_path

    @property
    def root_relative_path(self) -> str:
        return self.relative_path

    @classmethod
    def from_dict(cls, value: object) -> "ArtifactRefV2":
        required = {"relative_path", "schema", "sha256", "byte_count"}
        if type(value) is not dict or set(value) != required:
            raise DagArtifactError("artifact reference schema drift")
        try:
            return cls(relative_path=value["relative_path"], schema=value["schema"],
                       sha256=value["sha256"], byte_count=value["byte_count"])
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, DagArtifactError):
                raise
            raise DagArtifactError("artifact reference reconstruction drift") from exc


@dataclass(frozen=True)
class DagNodeManifestV2:
    """The immutable identity and exact edge/output set of one DAG node."""

    node: str
    freeze_sha256: str
    admission_sha256: str
    predecessors: tuple[ArtifactRefV2, ...]
    outputs: tuple[ArtifactRefV2, ...]
    authority: Mapping[str, bool]
    manifest_sha256: str
    schema: str = SCHEMA

    def __post_init__(self) -> None:
        _valid_node(self.node)
        _digest(self.freeze_sha256, "DAG freeze SHA-256")
        _digest(self.admission_sha256, "DAG admission SHA-256")
        if self.schema != SCHEMA or type(self.predecessors) is not tuple \
                or type(self.outputs) is not tuple:
            raise DagArtifactError("DAG manifest schema drift")
        if any(type(ref) is not ArtifactRefV2 for ref in
               (*self.predecessors, *self.outputs)):
            raise DagArtifactError("DAG manifest reference type drift")
        if dict(self.authority) != AUTHORITY or any(
                type(value) is not bool or value for value in self.authority.values()):
            raise DagArtifactError("DAG authority is not all false")
        _digest(self.manifest_sha256, "DAG manifest SHA-256")

    def body_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema, "node": self.node,
            "freeze_sha256": self.freeze_sha256,
            "admission_sha256": self.admission_sha256,
            "predecessors": [ref.to_dict() for ref in self.predecessors],
            "outputs": [ref.to_dict() for ref in self.outputs],
            "authority": dict(AUTHORITY),
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.body_dict(), "manifest_sha256": self.manifest_sha256}

    @property
    def predecessor_refs(self) -> tuple[ArtifactRefV2, ...]:
        return self.predecessors

    @property
    def predecessor_manifests(self) -> tuple[ArtifactRefV2, ...]:
        return self.predecessors

    @property
    def output_refs(self) -> tuple[ArtifactRefV2, ...]:
        return self.outputs

    @property
    def self_sha256(self) -> str:
        return self.manifest_sha256

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    manifest_bytes = canonical_bytes

    @classmethod
    def from_bytes(cls, raw: bytes, *, expected_node: str | None = None,
                   freeze_sha256: str | None = None,
                   admission_sha256: str | None = None) -> "DagNodeManifestV2":
        value = _strict_json(raw, "DAG manifest")
        required = {"schema", "node", "freeze_sha256", "admission_sha256",
                    "predecessors", "outputs", "authority", "manifest_sha256"}
        if set(value) != required or value.get("schema") != SCHEMA \
                or value.get("authority") != AUTHORITY:
            raise DagArtifactError("DAG manifest schema drift")
        node = _valid_node(value["node"])
        if expected_node is not None and node != _valid_node(expected_node):
            raise DagArtifactError("DAG manifest node identity drift")
        if freeze_sha256 is not None and value["freeze_sha256"] != freeze_sha256:
            raise DagArtifactError("DAG manifest freeze identity drift")
        if admission_sha256 is not None and value["admission_sha256"] != admission_sha256:
            raise DagArtifactError("DAG manifest admission identity drift")
        if type(value["predecessors"]) is not list or type(value["outputs"]) is not list:
            raise DagArtifactError("DAG manifest reference population drift")
        try:
            predecessors = tuple(ArtifactRefV2.from_dict(item)
                                for item in value["predecessors"])
            outputs = tuple(ArtifactRefV2.from_dict(item)
                            for item in value["outputs"])
            result = cls(node=node, freeze_sha256=value["freeze_sha256"],
                         admission_sha256=value["admission_sha256"],
                         predecessors=predecessors, outputs=outputs,
                         authority=value["authority"],
                         manifest_sha256=value["manifest_sha256"])
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, DagArtifactError):
                raise
            raise DagArtifactError("DAG manifest reconstruction drift") from exc
        body_hash = _sha(canonical_json_bytes(result.body_dict()))
        if result.manifest_sha256 != body_hash or result.canonical_bytes() != raw:
            raise DagArtifactError("DAG manifest self hash drift")
        _validate_refs_shape(result)
        return result


def _dependency_options(node: str) -> tuple[tuple[str, ...], ...]:
    value = NODE_DEPENDENCIES[_valid_node(node)]
    if value and isinstance(value[0], tuple):  # type: ignore[index]
        return value  # type: ignore[return-value]
    return (value,)  # type: ignore[arg-type]


def _validate_refs_shape(manifest: DagNodeManifestV2) -> None:
    if len({ref.relative_path for ref in manifest.predecessors}) != len(manifest.predecessors):
        raise DagArtifactError("DAG duplicate predecessor reference")
    if len({ref.relative_path for ref in manifest.outputs}) != len(manifest.outputs):
        raise DagArtifactError("DAG duplicate output reference")
    if not manifest.outputs:
        raise DagArtifactError("DAG output population is empty")
    expected = {"nodes/%s/manifest.json" % node for node in NODE_NAMES}
    for ref in manifest.predecessors:
        if ref.schema != SCHEMA or ref.relative_path not in expected:
            raise DagArtifactError("DAG predecessor reference drift")
    for ref in manifest.outputs:
        if ref.relative_path in expected or ref.relative_path.endswith(".partial"):
            raise DagArtifactError("DAG output reference drift")


def _manifest_ref(root: Path, node: str, manifest: DagNodeManifestV2 | None = None) -> ArtifactRefV2:
    path = _node_dir(root, node) / MANIFEST_NAME
    raw = manifest.canonical_bytes() if manifest is not None else _read(path, f"DAG {node} manifest")
    return ArtifactRefV2("%s/%s/%s" % (NODES_DIRNAME, node, MANIFEST_NAME),
                         SCHEMA, _sha(raw), len(raw))


def _normalise_predecessors(root: Path, node: str, predecessors: object,
                            *, freeze_sha256: str,
                            admission_sha256: str) -> tuple[ArtifactRefV2, ...]:
    expected = _dependency_options(node)
    if predecessors is None:
        predecessors = ()
    if isinstance(predecessors, Mapping):
        values = tuple(predecessors.get(name) for name in expected[0])
        if any(value is None for value in values):
            raise DagArtifactError("DAG dependency population is incomplete")
        predecessors = values
    if type(predecessors) not in (tuple, list):
        raise DagArtifactError("DAG dependency population drift")
    refs: list[ArtifactRefV2] = []
    for value in predecessors:
        if isinstance(value, DagNodeManifestV2):
            refs.append(_manifest_ref(root, value.node, value))
        elif isinstance(value, ArtifactRefV2):
            refs.append(value)
        else:
            raise DagArtifactError("DAG dependency reference type drift")
    names = tuple(Path(ref.relative_path).parts[-2]
                  for ref in refs if ref.relative_path.startswith("nodes/"))
    if names not in expected:
        raise DagArtifactError("DAG dependencies are not an exact canonical set")
    for ref, dep in zip(refs, names, strict=True):
        if ref.relative_path != f"nodes/{dep}/{MANIFEST_NAME}" or ref.schema != SCHEMA:
            raise DagArtifactError("DAG predecessor path drift")
        raw = _read(_safe_file(root, ref.relative_path), f"DAG predecessor {dep}")
        if len(raw) != ref.byte_count or _sha(raw) != ref.sha256:
            raise DagArtifactError("DAG predecessor bytes drift")
        _reopen_node(root, dep, _seen=set(),
                     freeze_sha256=freeze_sha256,
                     admission_sha256=admission_sha256, expected_raw=raw)
    return tuple(refs)


def _output_items(outputs: object, output_schemas: Mapping[str, str] | None,
                  node: str) -> list[tuple[str, str, bytes]]:
    if isinstance(outputs, Mapping):
        items = list(outputs.items())
    elif type(outputs) in (list, tuple):
        items = list(outputs)
    else:
        raise DagArtifactError("DAG output population drift")
    result: list[tuple[str, str, bytes]] = []
    seen: set[str] = set()
    for item in items:
        if type(item) not in (tuple, list) or len(item) != 2:
            raise DagArtifactError("DAG output row drift")
        name, value = item
        if type(name) is not str:
            raise DagArtifactError("DAG output path drift")
        schema = (output_schemas or {}).get(name, OUTPUT_SCHEMA)
        if type(value) is tuple and len(value) == 2 and type(value[0]) is str:
            schema, value = value
        if type(schema) is not str or not schema:
            raise DagArtifactError("DAG output schema drift")
        name = _safe_relative(name, "DAG output")
        root_prefix = f"nodes/{node}/"
        if name.startswith("nodes/"):
            if not name.startswith(root_prefix):
                raise DagArtifactError("DAG output path belongs to another node")
            name = name[len(root_prefix):]
            name = _safe_relative(name, "DAG output")
        if name == MANIFEST_NAME or name.endswith(".partial") or name in seen:
            raise DagArtifactError("DAG duplicate output")
        if type(value) is not bytes or not value:
            raise DagArtifactError("DAG output bytes drift")
        seen.add(name)
        result.append((name, schema, value))
    if not result:
        raise DagArtifactError("DAG output population is empty")
    return result


def _output_path(node_dir: Path, name: str) -> Path:
    path = node_dir / Path(name)
    try:
        path.relative_to(node_dir)
    except ValueError as exc:
        raise DagArtifactError("DAG output escapes node") from exc
    cursor = node_dir
    for part in Path(name).parts[:-1]:
        cursor = cursor / part
        _directory(cursor, create=True)
    return path


def _manifest_raw(*, node: str, freeze_sha256: str, admission_sha256: str,
                  predecessors: Sequence[ArtifactRefV2],
                  outputs: Sequence[ArtifactRefV2]) -> bytes:
    body = {
        "schema": SCHEMA, "node": node,
        "freeze_sha256": freeze_sha256, "admission_sha256": admission_sha256,
        "predecessors": [ref.to_dict() for ref in predecessors],
        "outputs": [ref.to_dict() for ref in outputs],
        "authority": dict(AUTHORITY),
    }
    return canonical_json_bytes({**body, "manifest_sha256": _sha(
        canonical_json_bytes(body))})


def _publish_manifest(root: Path, node: str, raw: bytes, *,
                      freeze_sha256: str,
                      admission_sha256: str) -> DagNodeManifestV2:
    """Publish a manifest, accepting an exact immutable publication race."""
    path = _node_dir(root, node, create=True) / MANIFEST_NAME
    if path.exists() or path.is_symlink():
        existing = _read(path, f"DAG {node} manifest")
        if existing != raw:
            raise DagArtifactError("DAG divergent immutable replay refused")
        DagNodeManifestV2.from_bytes(
            existing, expected_node=node, freeze_sha256=freeze_sha256,
            admission_sha256=admission_sha256)
        return reopen_dag_node(root, node, freeze_sha256=freeze_sha256,
                               admission_sha256=admission_sha256)
    _publish_idempotent_bytes(path, raw, f"DAG {node} manifest")
    reread = _read(path, f"DAG {node} manifest")
    if reread != raw:
        raise DagArtifactError("DAG manifest publication drift")
    return DagNodeManifestV2.from_bytes(raw, expected_node=node,
                                         freeze_sha256=freeze_sha256,
                                         admission_sha256=admission_sha256)


def _publish_raw_outputs(root: Path, node: str,
                         rows: Sequence[tuple[str, str, bytes]]) -> tuple[ArtifactRefV2, ...]:
    node_dir = _node_dir(root, node, create=True)
    paths = [_output_path(node_dir, name) for name, _schema, _raw in rows]
    path_set = set(paths)
    pending: list[tuple[Path, bytes, str]] = []
    refs: list[ArtifactRefV2] = []
    for (name, schema, raw), path in zip(rows, paths, strict=True):
        if path.exists() or path.is_symlink():
            reread = _read(path, f"DAG output {node}/{name}")
            if reread != raw:
                raise DagArtifactError("DAG divergent output replay refused")
        else:
            pending.append((path, raw, name))
        refs.append(ArtifactRefV2(f"{NODES_DIRNAME}/{node}/{name}",
                                  schema, _sha(raw), len(raw)))
    # Do not accidentally bless an unrelated file left by a failed attempt.
    for path in node_dir.rglob("*"):
        if path.is_file() and path not in path_set:
            raise DagArtifactError("DAG output population drift")
        if path.is_symlink():
            raise DagArtifactError("DAG output entry is a symlink")
    for path, raw, name in pending:
        _publish_idempotent_bytes(path, raw, f"DAG output {node}/{name}")
        if _read(path, f"DAG output {node}/{name}") != raw:
            raise DagArtifactError("DAG output publication drift")
    return tuple(refs)


def publish_dag_node(root: Path, node: str,
                     outputs: Mapping[str, bytes] | Sequence[tuple[str, bytes]], *,
                     freeze_sha256: str, admission_sha256: str,
                     predecessors: object = (), predecessor_manifests: object = None,
                     predecessor_refs: object = None,
                     output_schemas: Mapping[str, str] | None = None) -> DagNodeManifestV2:
    """Publish one node's raw outputs, with exact immutable resume support."""
    root = _root(root)
    node = _valid_node(node)
    _digest(freeze_sha256, "DAG freeze SHA-256")
    _digest(admission_sha256, "DAG admission SHA-256")
    supplied = predecessor_refs if predecessor_refs is not None else predecessor_manifests
    if supplied is None:
        supplied = predecessors
    refs = _normalise_predecessors(root, node, supplied,
                                   freeze_sha256=freeze_sha256,
                                   admission_sha256=admission_sha256)
    rows = _output_items(outputs, output_schemas, node)
    output_refs = tuple(ArtifactRefV2(
        f"{NODES_DIRNAME}/{node}/{name}", schema, _sha(raw), len(raw))
        for name, schema, raw in rows)
    if node == "reconstruction":
        _validate_reconstruction_outputs(
            root, output_refs, freeze_sha256=freeze_sha256,
            admission_sha256=admission_sha256)
    raw_manifest = _manifest_raw(node=node, freeze_sha256=freeze_sha256,
                                 admission_sha256=admission_sha256,
                                 predecessors=refs, outputs=output_refs)
    manifest_path = _node_dir(root, node, create=True) / MANIFEST_NAME
    if manifest_path.exists() or manifest_path.is_symlink():
        return _publish_manifest(root, node, raw_manifest,
                                 freeze_sha256=freeze_sha256,
                                 admission_sha256=admission_sha256)
    _publish_raw_outputs(root, node, rows)
    return _publish_manifest(root, node, raw_manifest,
                             freeze_sha256=freeze_sha256,
                             admission_sha256=admission_sha256)


def _normalise_output_refs(outputs: object) -> tuple[ArtifactRefV2, ...]:
    if isinstance(outputs, Mapping):
        values = tuple(outputs.values())
    elif type(outputs) in (tuple, list):
        values = tuple(outputs)
    else:
        raise DagArtifactError("DAG output reference population drift")
    if not values or any(type(ref) is not ArtifactRefV2 for ref in values):
        raise DagArtifactError("DAG output reference type drift")
    refs = tuple(values)
    if len({ref.relative_path for ref in refs}) != len(refs):
        raise DagArtifactError("DAG duplicate output reference")
    for ref in refs:
        if ref.relative_path.endswith(".partial") \
                or ref.relative_path in {
                    f"nodes/{node}/manifest.json" for node in NODE_NAMES}:
            raise DagArtifactError("DAG output reference drift")
    return refs


def _validate_existing_output_refs(root: Path,
                                   refs: Sequence[ArtifactRefV2]) -> None:
    for ref in refs:
        raw = _read(_safe_file(root, ref.relative_path),
                    f"DAG external output {ref.relative_path}")
        if len(raw) != ref.byte_count or _sha(raw) != ref.sha256:
            raise DagArtifactError("DAG external output bytes drift")


def _validate_reconstruction_outputs(
        root: Path, refs: Sequence[ArtifactRefV2], *,
        freeze_sha256: str, admission_sha256: str) -> None:
    """Bind reconstruction to the receipt already emitted by terminal.

    The reconstruction node is a receipt-only verifier.  It may not publish a
    model, prediction population, rescored result, or a second copy of an
    existing artifact under a new path.
    """
    if len(refs) != 1 or refs[0].relative_path != RECONSTRUCTION_RECEIPT_PATH \
            or refs[0].schema != RECONSTRUCTION_SCHEMA:
        raise DagArtifactError("DAG reconstruction is not receipt-only")
    raw = _read(_safe_file(root, refs[0].relative_path),
                "DAG reconstruction receipt")
    try:
        value = _strict_json(raw, "DAG reconstruction receipt")
        receipt = IndependentReconstructionReceiptV2(**value)
        validate_independent_reconstruction_v2(receipt)
    except Exception as exc:
        if isinstance(exc, DagArtifactError):
            raise
        raise DagArtifactError("DAG reconstruction receipt refused") from exc
    if not receipt.matched or receipt.canonical_bytes() != raw:
        raise DagArtifactError("DAG reconstruction receipt is not a match")
    terminal = _reopen_node(
        root, "terminal", _seen=set(), freeze_sha256=freeze_sha256,
        admission_sha256=admission_sha256)
    if refs[0] not in terminal.outputs:
        raise DagArtifactError("DAG reconstruction receipt is not terminal-bound")


def publish_dag_node_from_refs(root: Path, node: str, outputs: object = None, *,
                               freeze_sha256: str, admission_sha256: str,
                               predecessors: object = (),
                               predecessor_manifests: object = None,
                               predecessor_refs: object = None,
                               output_refs: object = None) -> DagNodeManifestV2:
    """Publish only a node manifest for already-sealed root-relative outputs."""
    root = _root(root)
    node = _valid_node(node)
    _digest(freeze_sha256, "DAG freeze SHA-256")
    _digest(admission_sha256, "DAG admission SHA-256")
    supplied = predecessor_refs if predecessor_refs is not None else predecessor_manifests
    if supplied is None:
        supplied = predecessors
    refs = _normalise_predecessors(root, node, supplied,
                                   freeze_sha256=freeze_sha256,
                                   admission_sha256=admission_sha256)
    supplied_outputs = output_refs if output_refs is not None else outputs
    output_refs_value = _normalise_output_refs(supplied_outputs)
    _validate_existing_output_refs(root, output_refs_value)
    if node == "reconstruction":
        _validate_reconstruction_outputs(
            root, output_refs_value, freeze_sha256=freeze_sha256,
            admission_sha256=admission_sha256)
    node_dir = _node_dir(root, node, create=True)
    manifest_path = node_dir / MANIFEST_NAME
    if not manifest_path.exists() and not manifest_path.is_symlink() \
            and any(node_dir.rglob("*")):
        raise DagArtifactError("DAG node has unexpected local output")
    raw_manifest = _manifest_raw(node=node, freeze_sha256=freeze_sha256,
                                 admission_sha256=admission_sha256,
                                 predecessors=refs, outputs=output_refs_value)
    return _publish_manifest(root, node, raw_manifest,
                             freeze_sha256=freeze_sha256,
                             admission_sha256=admission_sha256)


class _MissingNode(DagArtifactError):
    pass


def _reopen_node(root: Path, node: str, *, _seen: set[str],
                 freeze_sha256: str | None, admission_sha256: str | None,
                 expected_raw: bytes | None = None) -> DagNodeManifestV2:
    node = _valid_node(node)
    if node in _seen:
        raise DagArtifactError("DAG dependency cycle")
    _seen.add(node)
    nodes_dir = _nodes_dir(root)
    node_candidate = nodes_dir / node
    if not node_candidate.exists() and not node_candidate.is_symlink():
        raise _MissingNode(f"DAG {node} node is absent")
    node_dir = _node_dir(root, node)
    manifest_path = node_dir / MANIFEST_NAME
    if not manifest_path.exists() and not manifest_path.is_symlink():
        raise DagArtifactError(f"DAG {node} manifest is missing")
    raw = _read(manifest_path, f"DAG {node} manifest")
    if expected_raw is not None and raw != expected_raw:
        raise DagArtifactError(f"DAG {node} manifest changed across dependency boundary")
    manifest = DagNodeManifestV2.from_bytes(raw, expected_node=node,
                                            freeze_sha256=freeze_sha256,
                                            admission_sha256=admission_sha256)
    if freeze_sha256 is None:
        freeze_sha256 = manifest.freeze_sha256
    if admission_sha256 is None:
        admission_sha256 = manifest.admission_sha256
    options = _dependency_options(node)
    names = tuple(Path(ref.relative_path).parts[-2] for ref in manifest.predecessors)
    if names not in options:
        raise DagArtifactError("DAG dependencies are not an exact canonical set")
    _validate_refs_shape(manifest)
    for ref, dep in zip(manifest.predecessors, names, strict=True):
        if ref.relative_path != f"nodes/{dep}/{MANIFEST_NAME}" \
                or ref.schema != SCHEMA:
            raise DagArtifactError("DAG predecessor reference drift")
        dep_path = _safe_file(root, ref.relative_path)
        dep_raw = _read(dep_path, f"DAG predecessor {dep}")
        if len(dep_raw) != ref.byte_count or _sha(dep_raw) != ref.sha256:
            raise DagArtifactError("DAG predecessor bytes drift")
        try:
            _reopen_node(root, dep, _seen=set(_seen),
                         freeze_sha256=freeze_sha256,
                         admission_sha256=admission_sha256, expected_raw=dep_raw)
        except _MissingNode as exc:
            raise DagArtifactError(
                f"DAG {node} dependency {dep} is missing") from exc
    expected_entries = {MANIFEST_NAME}
    expected_dirs: set[str] = set()
    for ref in manifest.outputs:
        local_prefix = f"nodes/{node}/"
        is_local = ref.relative_path.startswith(local_prefix)
        rel = ref.relative_path[len(local_prefix):] if is_local \
            else ref.relative_path
        path = _safe_file(root, ref.relative_path)
        if path.is_symlink() or not path.is_file():
            raise DagArtifactError("DAG output is not a regular file")
        raw_output = _read(path, f"DAG output {node}/{rel}")
        if len(raw_output) != ref.byte_count or _sha(raw_output) != ref.sha256:
            raise DagArtifactError("DAG output bytes drift")
        if is_local:
            expected_entries.add(rel)
            parts = Path(rel).parts
            expected_dirs.update(str(Path(*parts[:i])) for i in range(1, len(parts)))
    if node == "reconstruction":
        _validate_reconstruction_outputs(
            root, manifest.outputs, freeze_sha256=freeze_sha256,
            admission_sha256=admission_sha256)
    actual: set[str] = set()
    for path in node_dir.rglob("*"):
        rel = path.relative_to(node_dir).as_posix()
        if path.is_symlink() or (path.is_dir() and not path.is_symlink()):
            actual.add(rel)
        elif path.is_file():
            actual.add(rel)
        else:
            raise DagArtifactError("DAG node entry drift")
    if actual != expected_entries | expected_dirs:
        raise DagArtifactError("DAG output population drift")
    return manifest


def reopen_dag_node(root: Path, node: str, *, freeze_sha256: str,
                    admission_sha256: str) -> DagNodeManifestV2:
    """Reopen one node, recursively checking its exact dependency closure."""
    root = _root(root)
    _digest(freeze_sha256, "DAG freeze SHA-256")
    _digest(admission_sha256, "DAG admission SHA-256")
    return _reopen_node(root, node, _seen=set(), freeze_sha256=freeze_sha256,
                        admission_sha256=admission_sha256)


def reopen_dag(root: Path, *, freeze_sha256: str, admission_sha256: str) -> dict[str, DagNodeManifestV2]:
    """Return the valid dependency-closed portion of the progressive DAG.

    Truly absent future nodes are intentionally omitted.  A malformed or
    tampered present node raises; it can never masquerade as incompleteness.
    An early terminal node does not require audit or reconstruction.
    """
    root = _root(root)
    try:
        _nodes_dir(root)
    except DagArtifactError:
        if not (root / NODES_DIRNAME).exists():
            return {}
        raise
    nodes_dir = root / NODES_DIRNAME
    for entry in nodes_dir.iterdir():
        if entry.name not in NODE_NAMES or entry.is_symlink() or not entry.is_dir():
            raise DagArtifactError("DAG node population drift")
    result: dict[str, DagNodeManifestV2] = {}
    for node in NODE_NAMES:
        try:
            result[node] = reopen_dag_node(root, node, freeze_sha256=freeze_sha256,
                                           admission_sha256=admission_sha256)
        except _MissingNode:
            continue
    return result


def reopen_dag_aggregate(root: Path, *, freeze_sha256: str,
                         admission_sha256: str) -> dict[str, DagNodeManifestV2]:
    return reopen_dag(root, freeze_sha256=freeze_sha256,
                      admission_sha256=admission_sha256)


# Short descriptive aliases used by callers treating the directory as the API.
publish_node = publish_dag_node
publish_node_v2 = publish_dag_node
publish_node_manifest_v2 = publish_dag_node
publish_node_from_refs = publish_dag_node_from_refs
publish_dag_node_manifest_from_refs = publish_dag_node_from_refs
reopen_node = reopen_dag_node
reopen_node_manifest_v2 = reopen_dag_node
reopen_dependency_closed_dag = reopen_dag
aggregate_reopen = reopen_dag
final_aggregate_reopen_v2 = reopen_dag


__all__ = [
    "AUTHORITY", "EXPECTED_NODES", "MANIFEST_NAME", "MANIFEST_SCHEMA",
    "CANONICAL_DEPENDENCIES", "NODE_DEPENDENCIES", "NODE_NAMES", "NODES_DIRNAME", "OUTPUT_SCHEMA",
    "SCHEMA", "ArtifactRefV2", "DagArtifactError", "DagNodeManifestV2",
    "WorldAfterstateV2DagArtifactError", "publish_dag_node", "publish_node",
    "publish_dag_node_from_refs", "publish_node_from_refs",
    "publish_dag_node_manifest_from_refs",
    "reopen_dag", "reopen_dag_aggregate", "reopen_dag_node", "reopen_node",
    "reopen_dependency_closed_dag", "aggregate_reopen", "final_aggregate_reopen_v2",
    "publish_node_v2", "publish_node_manifest_v2", "reopen_node_manifest_v2",
]
