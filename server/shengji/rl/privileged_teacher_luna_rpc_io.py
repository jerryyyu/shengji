"""Crash-safe exclusive publication for PT-Luna RPC artifacts.

Writers first fsync a same-directory hidden partial and then hard-link it into
the immutable final name.  A process death therefore leaves either no final
name or one containing the complete bytes.  A later call with the same bytes
may promote a completed partial without rewriting it.
"""

from __future__ import annotations

import os
from pathlib import Path
import stat


class AtomicPublishError(ValueError):
    """An immutable publication slot or staged write is invalid."""


def partial_path(path: Path) -> Path:
    path = Path(path)
    return path.with_name(f".{path.name}.partial")


def publication_slot_occupied(path: Path) -> bool:
    path = Path(path)
    return path.exists() or path.is_symlink() \
        or partial_path(path).exists() or partial_path(path).is_symlink()


def _fsync_dir(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _stable_read(path: Path, *, mode: int,
                 permitted_nlinks: tuple[int, ...] = (1,)) -> bytes:
    try:
        descriptor = os.open(
            path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            before = os.fstat(descriptor)
            chunks = []
            while True:
                chunk = os.read(descriptor, 1 << 20)
                if not chunk:
                    break
                chunks.append(chunk)
            raw = b"".join(chunks)
            after = os.fstat(descriptor)
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise AtomicPublishError("atomic publication read failed") from exc
    fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    if (not stat.S_ISREG(before.st_mode)
            or before.st_nlink not in permitted_nlinks
            or before.st_uid != os.getuid()
            or stat.S_IMODE(before.st_mode) != mode
            or any(getattr(before, field) != getattr(after, field)
                   for field in fields)):
        raise AtomicPublishError("atomic publication identity drift")
    return raw


def recover_linked_partial(path: Path, *, raw: bytes | None = None,
                           mode: int = 0o400) -> bool:
    """Finish cleanup when final and partial are the same linked inode.

    A death after ``link(2)`` but before the staged-name unlink leaves two
    names for the already-complete immutable file.  This is the sole
    two-link state accepted here; unrelated files, extra links, wrong modes,
    and byte mismatches still refuse.
    """
    path = Path(path)
    staged = partial_path(path)
    if not ((path.exists() or path.is_symlink())
            and (staged.exists() or staged.is_symlink())):
        return False
    try:
        final_info = path.stat(follow_symlinks=False)
        staged_info = staged.stat(follow_symlinks=False)
    except OSError as exc:
        raise AtomicPublishError("atomic linked recovery stat failed") from exc
    identity = ("st_dev", "st_ino")
    if (path.is_symlink() or staged.is_symlink()
            or not stat.S_ISREG(final_info.st_mode)
            or not stat.S_ISREG(staged_info.st_mode)
            or final_info.st_nlink != 2 or staged_info.st_nlink != 2
            or final_info.st_uid != os.getuid()
            or staged_info.st_uid != os.getuid()
            or stat.S_IMODE(final_info.st_mode) != mode
            or stat.S_IMODE(staged_info.st_mode) != mode
            or any(getattr(final_info, field) != getattr(staged_info, field)
                   for field in identity)):
        raise AtomicPublishError("atomic linked recovery identity drift")
    final_raw = _stable_read(path, mode=mode, permitted_nlinks=(2,))
    if _stable_read(staged, mode=mode, permitted_nlinks=(2,)) != final_raw \
            or (raw is not None and final_raw != raw):
        raise AtomicPublishError("atomic linked recovery bytes drift")
    try:
        staged.unlink()
    except OSError as exc:
        raise AtomicPublishError("atomic linked recovery unlink failed") from exc
    _fsync_dir(path.parent)
    if _stable_read(path, mode=mode) != final_raw:
        raise AtomicPublishError("atomic linked recovery final drift")
    return True


def promote_partial(path: Path, raw: bytes, *, mode: int = 0o400) -> None:
    """Promote an already-complete staged file into its final name."""
    path = Path(path)
    staged = partial_path(path)
    if _stable_read(staged, mode=mode) != raw:
        raise AtomicPublishError("atomic partial bytes drift")
    try:
        os.link(staged, path, follow_symlinks=False)
    except FileExistsError:
        if _stable_read(path, mode=mode) != raw:
            raise AtomicPublishError("atomic final bytes drift")
    except OSError as exc:
        raise AtomicPublishError("atomic publication link failed") from exc
    _fsync_dir(path.parent)
    try:
        staged.unlink()
    except FileNotFoundError:
        pass
    _fsync_dir(path.parent)


def publish_exclusive_bytes(
        path: Path, raw: bytes, *, mode: int = 0o400,
        existing_equal_ok: bool = False,
        repair_incomplete_partial: bool = False) -> None:
    """Publish complete bytes without ever exposing a partial final name."""
    path = Path(path)
    if type(raw) is not bytes or mode not in (0o400, 0o444, 0o600):
        raise AtomicPublishError("atomic publication input drift")
    if recover_linked_partial(path, raw=raw, mode=mode):
        return
    if path.exists() or path.is_symlink():
        if existing_equal_ok and _stable_read(path, mode=mode) == raw:
            return
        raise AtomicPublishError("atomic publication slot occupied")
    staged = partial_path(path)
    if staged.exists() or staged.is_symlink():
        try:
            current = _stable_read(staged, mode=mode)
        except AtomicPublishError:
            if not repair_incomplete_partial:
                raise
            if staged.is_symlink():
                raise AtomicPublishError("atomic partial identity drift")
            staged.unlink()
            _fsync_dir(path.parent)
        else:
            if current == raw:
                promote_partial(path, raw, mode=mode)
                return
            if not repair_incomplete_partial:
                raise AtomicPublishError("atomic partial bytes drift")
            staged.unlink()
            _fsync_dir(path.parent)
    try:
        descriptor = os.open(
            staged, os.O_WRONLY | os.O_CREAT | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0), mode)
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise AtomicPublishError("atomic partial write failed") from exc
    promote_partial(path, raw, mode=mode)


__all__ = ["AtomicPublishError", "partial_path", "promote_partial",
           "recover_linked_partial",
           "publication_slot_occupied", "publish_exclusive_bytes"]
