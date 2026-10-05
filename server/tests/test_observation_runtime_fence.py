"""Synthetic tests for the fail-closed mapped-runtime fence."""

import copy
import os
from pathlib import Path
import sys
from types import ModuleType

import pytest

from shengji.eval.runtime_fence import RuntimeFence, capture


def _maps_line(path: Path, *, inode: int | None = None, dev: tuple[int, int] | None = None,
               start: int = 0x400000) -> str:
    info = path.stat()
    if inode is None:
        inode = int(info.st_ino)
    if dev is None:
        dev = (os.major(info.st_dev), os.minor(info.st_dev))
    return (
        f"{start:08x}-{start + 0x1000:08x} r--p 00000000 "
        f"{dev[0]:02x}:{dev[1]:02x} {inode} {path}\n"
    )


def _fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source_root = tmp_path / "source"
    source_root.mkdir()
    mapped = tmp_path / "external" / "libsynthetic.so"
    mapped.parent.mkdir()
    mapped.write_bytes(b"synthetic-native\n")
    maps = tmp_path / "maps"
    maps.write_text(_maps_line(mapped), encoding="utf-8")
    module_name = "runtime_fence_synthetic_module"
    module = ModuleType(module_name)
    monkeypatch.setitem(sys.modules, module_name, module)
    manifest = capture(source_root, [module_name], maps_path=maps)
    return source_root, mapped, maps, module_name, manifest


def test_capture_and_verify_accept_unchanged_synthetic_fence(tmp_path, monkeypatch):
    source_root, mapped, maps, module_name, manifest = _fixture(tmp_path, monkeypatch)

    assert manifest["files"] == {
        str(mapped.resolve()): manifest["files"][str(mapped.resolve())]
    }
    fence = RuntimeFence(manifest, source_root, maps_path=maps)
    assert fence.check() is True
    assert fence.last_failure is None
    assert manifest["imports"] == [module_name]


@pytest.mark.parametrize("field", ["runtime", "imports", "source_root"])
def test_manifest_runtime_import_source_mismatch_is_rejected(
    tmp_path, monkeypatch, field,
):
    source_root, _, maps, module_name, manifest = _fixture(tmp_path, monkeypatch)
    bad = copy.deepcopy(manifest)
    if field == "runtime":
        bad["runtime"]["machine"] = "synthetic-mismatch"
    elif field == "imports":
        bad["imports"] = ["runtime_fence_module_not_loaded"]
    else:
        alternate = tmp_path / "alternate-source"
        alternate.mkdir()
        bad["source_root"] = str(alternate.resolve())
    with pytest.raises(ValueError):
        RuntimeFence(bad, source_root, maps_path=maps)


@pytest.mark.parametrize("mutation", ["bytes", "stat"])
def test_mapped_file_bytes_or_stat_drift_is_rejected(
    tmp_path, monkeypatch, mutation,
):
    source_root, mapped, maps, module_name, manifest = _fixture(tmp_path, monkeypatch)
    if mutation == "bytes":
        mapped.write_bytes(b"different-native\n")
        with pytest.raises(ValueError, match="mapped file"):
            RuntimeFence(manifest, source_root, maps_path=maps)
        return
    fence = RuntimeFence(manifest, source_root, maps_path=maps)
    info = mapped.stat()
    os.utime(mapped, ns=(info.st_atime_ns, info.st_mtime_ns + 1_000_000))
    assert fence.check() is False
    assert fence.last_failure == {"stage": "mapped_files", "added": [],
                                  "removed": [], "changed": [str(mapped)]}


@pytest.mark.parametrize("mutation", ["new", "deleted"])
def test_new_or_deleted_map_fails_check(tmp_path, monkeypatch, mutation):
    source_root, mapped, maps, module_name, manifest = _fixture(tmp_path, monkeypatch)
    fence = RuntimeFence(manifest, source_root, maps_path=maps)
    if mutation == "new":
        added = tmp_path / "external" / "another.so"
        added.write_bytes(b"another-native\n")
        maps.write_text(
            _maps_line(mapped) + _maps_line(added, start=0x401000), encoding="utf-8"
        )
    else:
        maps.write_text("", encoding="utf-8")
    assert fence.check() is False
    assert fence.last_failure == {
        "stage": "mapped_files", "added": [str(added)] if mutation == "new" else [],
        "removed": [str(mapped)] if mutation == "deleted" else [],
    }
    maps.write_text(_maps_line(mapped), encoding="utf-8")
    assert fence.check()
    assert fence.last_failure is None


@pytest.mark.parametrize("kind", ["path", "inode"])
def test_path_or_inode_mismatch_fails_closed(tmp_path, monkeypatch, kind):
    source_root, mapped, maps, module_name, manifest = _fixture(tmp_path, monkeypatch)
    if kind == "path":
        replacement = tmp_path / "external" / "replacement.so"
        replacement.write_bytes(b"replacement-native\n")
        maps.write_text(_maps_line(replacement), encoding="utf-8")
        with pytest.raises(ValueError, match="mapped-file set"):
            RuntimeFence(manifest, source_root, maps_path=maps)
    else:
        info = mapped.stat()
        maps.write_text(_maps_line(mapped, inode=int(info.st_ino) + 1), encoding="utf-8")
        with pytest.raises(ValueError, match="inode mismatch"):
            capture(source_root, [module_name], maps_path=maps)


def test_replaced_module_object_fails_check(tmp_path, monkeypatch):
    source_root, _, maps, module_name, manifest = _fixture(tmp_path, monkeypatch)
    fence = RuntimeFence(manifest, source_root, maps_path=maps)
    monkeypatch.setitem(sys.modules, module_name, ModuleType(module_name))
    assert fence.check() is False
    assert fence.last_failure == {"stage": "module_identity", "changed": [module_name]}
