"""Small cooperative directory lease for one observation writer.

The lease is a directory containing one owner file.  Acquisition uses the
directory's exclusive creation and then publishes the owner with an exclusive
file create; an occupied lease is always refused unchanged.  The checks are
fail-closed for detected identity drift, but this is cooperative coordination,
not protection against an adversarial process racing filesystem operations.
"""

from __future__ import annotations

import os
from pathlib import Path


def _nonsymlink_ancestry(path: Path) -> bool:
    """Return whether *path* and every existing ancestor are not symlinks."""

    try:
        return all(not part.is_symlink() for part in (path, *path.parents))
    except OSError:
        return False


def file_stamp(path: Path) -> tuple[int, int, int, int, int]:
    """Return identity and metadata for a regular, nonsymlink file."""

    path = Path(path)
    if not _nonsymlink_ancestry(path) or not path.is_file() or path.is_symlink():
        raise ValueError(f"regular nonsymlink file required: {path}")
    try:
        stat = path.stat()
    except OSError as exc:
        raise ValueError(f"cannot stat file: {path}") from exc
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


def _write_exclusive_bytes(path: Path, raw: bytes) -> tuple[int, int, int, int, int]:
    """Create and write one file, leaving any partial publication in place."""

    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
        stat = os.fstat(handle.fileno())
        return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


class Lease:
    """A reusable cooperative exclusive directory lease.

    ``release`` intentionally does not act as a context-manager cleanup hook:
    callers must establish that all lease children have drained first.  Only a
    caller-owned, unchanged directory containing exactly its owner is removed.
    """

    def __init__(self, lock: Path, owner: str):
        if type(owner) is not str or not owner:
            raise ValueError("owner must be a non-empty string")
        self.lock = Path(lock)
        self.owner = owner
        self._lock_stamp: tuple[int, int, int, int, int] | None = None
        self._owner_stamp: tuple[int, int, int, int, int] | None = None
        self._owner_bytes: bytes | None = None

    @property
    def _owner_path(self) -> Path:
        return self.lock / "owner"

    def acquire(self) -> bool:
        """Claim an absent lock, refusing every existing lock unchanged."""

        if self._lock_stamp is not None:
            return False
        if not _nonsymlink_ancestry(self.lock) or self.lock.is_symlink():
            return False
        try:
            self.lock.mkdir(mode=0o700)
        except (FileExistsError, OSError):
            return False

        # Do not remove the directory if owner publication fails.  The partial
        # lock records that this acquisition attempt was interrupted.
        created_dir_identity = self._dir_stamp(self.lock)[:2]
        expected_bytes = self.owner.encode("utf-8")
        published_stamp = _write_exclusive_bytes(self._owner_path, expected_bytes)
        lock_stamp = self._dir_stamp(self.lock)
        if (lock_stamp[:2] != created_dir_identity
                or file_stamp(self._owner_path) != published_stamp
                or self._owner_path.read_bytes() != expected_bytes
                or file_stamp(self._owner_path) != published_stamp
                or list(self.lock.iterdir()) != [self._owner_path]
                or self._dir_stamp(self.lock) != lock_stamp):
            raise ValueError("lease changed during owner publication")
        self._lock_stamp = lock_stamp
        self._owner_stamp = published_stamp
        self._owner_bytes = expected_bytes
        return True

    @staticmethod
    def _dir_stamp(path: Path) -> tuple[int, int, int, int, int]:
        stat = path.stat()
        if path.is_symlink() or not path.is_dir():
            raise ValueError("lease directory is not regular")
        return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns

    def _identity(self) -> bool:
        if self._lock_stamp is None or self._owner_stamp is None or self._owner_bytes is None:
            return False
        if not _nonsymlink_ancestry(self.lock) or self.lock.is_symlink():
            return False
        try:
            return (self._dir_stamp(self.lock) == self._lock_stamp
                    and file_stamp(self._owner_path) == self._owner_stamp
                    and self._owner_path.read_bytes() == self._owner_bytes)
        except (OSError, ValueError):
            return False

    def check(self) -> bool:
        """Return whether the caller's pinned directory and owner are intact."""

        return self._identity()

    def release(self) -> bool:
        """Remove only this unchanged lease when no child remains besides owner."""

        if not self._identity():
            return False
        try:
            entries = list(self.lock.iterdir())
            if entries != [self._owner_path]:
                return False
            if not self._identity():
                return False
            self._owner_path.unlink()
            if not self._nonsymlink_lock():
                return False
            stat = self.lock.stat()
            if ((stat.st_dev, stat.st_ino) != self._lock_stamp[:2]
                    or list(self.lock.iterdir())):
                return False
            self.lock.rmdir()
            self._lock_stamp = self._owner_stamp = None
            self._owner_bytes = None
            return True
        except (OSError, ValueError):
            return False

    def _nonsymlink_lock(self) -> bool:
        return _nonsymlink_ancestry(self.lock) and self.lock.is_dir() and not self.lock.is_symlink()


__all__ = ["Lease", "file_stamp"]
