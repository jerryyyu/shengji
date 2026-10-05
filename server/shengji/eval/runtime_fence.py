"""A small, fail-closed fence for the runtime used by head-free jobs.

The helper deliberately does not import any application or third-party module.
It treats the supplied maps file as an input snapshot; the Linux runner passes
``/proc/self/maps`` while tests may supply a synthetic maps file.
"""

from __future__ import annotations

import hashlib
import os
import platform
import re
import stat
import sys
from pathlib import Path
from typing import Mapping


SCHEMA = "headfree-external-runtime-v1"
_CHUNK_SIZE = 1024 * 1024
_ADDRESS_RE = re.compile(r"^[0-9a-fA-F]+-[0-9a-fA-F]+$")
_PERMS_RE = re.compile(r"^[r-][w-][x-][ps]$")
_DEV_RE = re.compile(r"^[0-9a-fA-F]+:[0-9a-fA-F]+$")
_HEX_RE = re.compile(r"^[0-9a-fA-F]+$")
_DEC_RE = re.compile(r"^[0-9]+$")


def _runtime() -> dict[str, str]:
    return {
        "python_version": platform.python_version(),
        "implementation": platform.python_implementation(),
        "system": platform.system(),
        "machine": platform.machine(),
    }


def _canonical_root(source_root: Path) -> Path:
    try:
        supplied = Path(source_root)
    except (TypeError, ValueError) as exc:
        raise ValueError("source_root must be a path") from exc
    if supplied.is_symlink():
        raise ValueError("source_root must not be a symlink")
    try:
        root = supplied.resolve(strict=True)
        root_stat = root.stat()
    except (OSError, RuntimeError) as exc:
        raise ValueError("source_root must be an existing directory") from exc
    if not stat.S_ISDIR(root_stat.st_mode):
        raise ValueError("source_root must be a directory")
    return root


def _module_names(imports: object) -> list[str]:
    if not isinstance(imports, list) or not imports:
        raise ValueError("imports must be a non-empty list")
    result: list[str] = []
    for name in imports:
        if not isinstance(name, str) or not name:
            raise ValueError("imports must contain non-empty module strings")
        pieces = name.split(".")
        if any(not piece.isidentifier() for piece in pieces):
            raise ValueError(f"invalid module name: {name!r}")
        if name in result:
            raise ValueError("imports must be unique")
        if name not in sys.modules or sys.modules[name] is None:
            raise ValueError(f"module is not already loaded: {name}")
        result.append(name)
    return result


def _module_snapshot(names: list[str]) -> dict[str, object]:
    """Capture already-loaded module identities without importing anything."""
    snapshot: dict[str, object] = {}
    for name in names:
        module = sys.modules.get(name)
        if module is None:
            raise ValueError(f"module is not already loaded: {name}")
        snapshot[name] = module
    return snapshot


def _modules_unchanged(snapshot: Mapping[str, object]) -> bool:
    return all(sys.modules.get(name) is module for name, module in snapshot.items())


def _stat_signature(info: os.stat_result) -> tuple[int, ...]:
    # Do not include atime: merely checking a file must not invalidate it.
    return (
        int(info.st_dev),
        int(info.st_ino),
        int(info.st_mode),
        int(info.st_nlink),
        int(info.st_size),
        int(info.st_mtime_ns),
        int(info.st_ctime_ns),
    )


_MappedFile = tuple[
    str, tuple[str, ...], tuple[int, int], int, tuple[int, ...]
]


def _mapped_file(raw_path: str, major: int, minor: int, inode: int) -> _MappedFile:
    if raw_path.endswith(" (deleted)"):
        raise ValueError("deleted mapped file")
    if not raw_path.startswith("/"):
        raise ValueError("file-backed map path is not absolute")
    try:
        resolved = Path(raw_path).resolve(strict=True)
        info = resolved.stat()
    except (OSError, RuntimeError) as exc:
        raise ValueError(f"mapped file is inaccessible: {raw_path}") from exc
    if not stat.S_ISREG(info.st_mode):
        raise ValueError(f"mapped path is not a regular file: {raw_path}")
    if (os.major(info.st_dev), os.minor(info.st_dev)) != (major, minor):
        raise ValueError(f"mapped file device mismatch: {raw_path}")
    if int(info.st_ino) != inode:
        raise ValueError(f"mapped file inode mismatch: {raw_path}")
    return (str(resolved), (raw_path,), (major, minor), inode, _stat_signature(info))


def _parse_maps_text(text: str) -> dict[str, _MappedFile]:
    files: dict[str, _MappedFile] = {}
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line:
            raise ValueError(f"malformed maps line {line_number}")
        fields = line.split(maxsplit=5)
        if len(fields) < 5:
            raise ValueError(f"malformed maps line {line_number}")
        address, perms, offset, dev, inode_text = fields[:5]
        if not _ADDRESS_RE.fullmatch(address):
            raise ValueError(f"malformed address on maps line {line_number}")
        start, end = (int(part, 16) for part in address.split("-"))
        if start >= end or not _PERMS_RE.fullmatch(perms):
            raise ValueError(f"malformed mapping on maps line {line_number}")
        if not _HEX_RE.fullmatch(offset):
            raise ValueError(f"malformed offset on maps line {line_number}")
        if not _DEV_RE.fullmatch(dev):
            raise ValueError(f"malformed device on maps line {line_number}")
        if not _DEC_RE.fullmatch(inode_text):
            raise ValueError(f"malformed inode on maps line {line_number}")
        inode = int(inode_text, 10)
        major_text, minor_text = dev.split(":", 1)
        major, minor = int(major_text, 16), int(minor_text, 16)
        pathname = fields[5] if len(fields) == 6 else None

        # Anonymous and bracketed kernel pseudo-mappings have inode 0 and do
        # not identify a regular file.  Any other inode-0 pathname is suspect.
        if inode == 0 and (pathname is None or pathname.startswith("[")):
            continue
        if pathname is None:
            raise ValueError(f"file-backed map has no path on line {line_number}")
        mapped = _mapped_file(pathname, major, minor, inode)
        previous = files.get(mapped[0])
        if previous is not None:
            if (previous[2], previous[3]) != (mapped[2], mapped[3]):
                raise ValueError(f"conflicting identities for mapped file {mapped[0]}")
            if previous[4] != mapped[4]:
                raise ValueError(f"mapped file changed while parsing: {mapped[0]}")
            if mapped[1][0] not in previous[1]:
                files[mapped[0]] = (
                    previous[0],
                    tuple(sorted((*previous[1], mapped[1][0]))),
                    previous[2],
                    previous[3],
                    previous[4],
                )
        else:
            files[mapped[0]] = mapped
    return dict(sorted(files.items()))


def _maps_snapshot(maps_path: Path) -> dict[str, _MappedFile]:
    try:
        text = maps_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ValueError("maps file is inaccessible or not text") from exc
    return _parse_maps_text(text)


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as stream:
            while True:
                chunk = stream.read(_CHUNK_SIZE)
                if not chunk:
                    break
                digest.update(chunk)
    except OSError as exc:
        raise ValueError(f"cannot hash mapped file: {path}") from exc
    return digest.hexdigest().lower()


def _under(root: Path, path: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _read_manifest(manifest: Mapping[str, object]) -> tuple[Path, dict[str, str], list[str], dict[str, str]]:
    if not isinstance(manifest, dict):
        raise ValueError("manifest must be a dictionary")
    if set(manifest) != {"schema", "source_root", "runtime", "imports", "files"}:
        raise ValueError("manifest has an unexpected schema")
    if manifest["schema"] != SCHEMA or not isinstance(manifest["source_root"], str):
        raise ValueError("invalid manifest schema or source_root")
    root = _canonical_root(Path(manifest["source_root"]))
    if str(root) != manifest["source_root"]:
        raise ValueError("source_root is not canonical")
    runtime = manifest["runtime"]
    if not isinstance(runtime, dict) or set(runtime) != {
        "python_version", "implementation", "system", "machine"
    } or any(not isinstance(value, str) for value in runtime.values()):
        raise ValueError("invalid runtime metadata")
    imports = _module_names(manifest["imports"])
    files = manifest["files"]
    if not isinstance(files, dict):
        raise ValueError("files must be a mapping")
    checked: dict[str, str] = {}
    for raw_path, digest in files.items():
        if not isinstance(raw_path, str) or not isinstance(digest, str):
            raise ValueError("files must map strings to SHA256 strings")
        try:
            path = Path(raw_path)
            resolved = path.resolve(strict=True)
            info = resolved.stat()
        except (OSError, RuntimeError, ValueError) as exc:
            raise ValueError(f"invalid declared file: {raw_path}") from exc
        if not path.is_absolute() or str(resolved) != raw_path or not stat.S_ISREG(info.st_mode):
            raise ValueError(f"declared file is not canonical regular file: {raw_path}")
        if _under(root, resolved):
            raise ValueError("source files cannot be declared external")
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise ValueError(f"invalid SHA256 digest for {raw_path}")
        checked[raw_path] = digest
    return root, dict(runtime), imports, checked


def capture(
    source_root: Path,
    imports: list[str],
    *,
    maps_path: Path = Path("/proc/self/maps"),
) -> dict[str, object]:
    """Capture a canonical manifest from already-loaded runtime state."""
    root = _canonical_root(source_root)
    checked_imports = _module_names(imports)
    runtime = _runtime()
    module_snapshot = _module_snapshot(checked_imports)
    maps = _maps_snapshot(Path(maps_path))
    external = {path: item for path, item in maps.items() if not _under(root, Path(path))}

    hashes: dict[str, str] = {}
    for path, item in external.items():
        before = Path(path).stat()
        if _stat_signature(before) != item[4]:
            raise ValueError(f"mapped file changed while capturing: {path}")
        digest = _hash_file(Path(path))
        after = Path(path).stat()
        if _stat_signature(after) != _stat_signature(before):
            raise ValueError(f"mapped file changed while hashing: {path}")
        hashes[path] = digest

    after_maps = _maps_snapshot(Path(maps_path))
    if maps != after_maps:
        raise ValueError("mapped files changed while capturing")
    if _runtime() != runtime or not _modules_unchanged(module_snapshot):
        raise ValueError("runtime changed while capturing")
    return {
        "schema": SCHEMA,
        "source_root": str(root),
        "runtime": runtime,
        "imports": checked_imports,
        "files": dict(sorted(hashes.items())),
    }


class RuntimeFence:
    """Validate a manifest once and cheaply check its runtime fence later."""

    def __init__(
        self,
        manifest: dict,
        source_root: Path,
        *,
        maps_path: Path = Path("/proc/self/maps"),
    ) -> None:
        root, runtime, imports, declared = _read_manifest(manifest)
        supplied_root = _canonical_root(source_root)
        if supplied_root != root:
            raise ValueError("source_root does not match manifest")
        if runtime != _runtime():
            raise ValueError("runtime metadata does not match current runtime")
        module_snapshot = _module_snapshot(imports)
        maps = _maps_snapshot(Path(maps_path))
        external = {path: item for path, item in maps.items() if not _under(root, Path(path))}
        if set(external) != set(declared):
            raise ValueError("manifest external mapped-file set does not match")
        for path in sorted(declared):
            before = Path(path).stat()
            if _stat_signature(before) != external[path][4]:
                raise ValueError(f"mapped file changed while verifying: {path}")
            if _hash_file(Path(path)) != declared[path]:
                raise ValueError(f"hash mismatch for mapped file: {path}")
        after_maps = _maps_snapshot(Path(maps_path))
        if maps != after_maps:
            raise ValueError("mapped files changed while verifying")
        if _runtime() != runtime or not _modules_unchanged(module_snapshot):
            raise ValueError("runtime changed while verifying")
        self._source_root = root
        self._runtime = runtime
        self._imports = tuple(imports)
        self._maps_path = Path(maps_path)
        self._maps = maps
        self._declared_files = frozenset(declared)
        self._module_objects = module_snapshot

    def check(self) -> bool:
        """Return whether the current process still satisfies the fence."""
        self.last_failure = None
        stage = "runtime_identity"
        try:
            if _runtime() != self._runtime:
                self.last_failure = {"stage": stage}
                return False
            changed_modules = [
                name for name in self._imports if
                name not in sys.modules
                or sys.modules[name] is None
                or sys.modules[name] is not self._module_objects[name]
            ]
            if changed_modules:
                self.last_failure = {"stage": "module_identity", "changed": changed_modules}
                return False
            stage = "source_root"
            if self._source_root.is_symlink() or not self._source_root.is_dir():
                self.last_failure = {"stage": stage}
                return False
            stage = "mapped_files"
            current = _maps_snapshot(self._maps_path)
            current_external = {
                path: item
                for path, item in current.items()
                if not _under(self._source_root, Path(path))
            }
            if set(current_external) != self._declared_files:
                self.last_failure = {
                    "stage": stage,
                    "added": sorted(set(current_external) - self._declared_files),
                    "removed": sorted(self._declared_files - set(current_external)),
                }
                return False
            if current != self._maps:
                self.last_failure = {
                    "stage": stage,
                    "added": sorted(current.keys() - self._maps.keys()),
                    "removed": sorted(self._maps.keys() - current.keys()),
                    "changed": sorted(k for k in current.keys() & self._maps.keys()
                                      if current[k] != self._maps[k]),
                }
                return False
            return True
        except (OSError, RuntimeError, ValueError) as exc:
            self.last_failure = {"stage": stage, "error_type": type(exc).__name__,
                                 "error": str(exc)}
            return False


__all__ = ["RuntimeFence", "capture"]
