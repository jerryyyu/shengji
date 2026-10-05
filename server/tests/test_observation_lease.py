from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from shengji.eval import observation_lease
from shengji.eval.observation_lease import Lease


def _stable_metadata(info: os.stat_result) -> tuple[int, ...]:
    return (
        info.st_dev,
        info.st_ino,
        info.st_mode,
        info.st_uid,
        info.st_gid,
        info.st_nlink,
        info.st_size,
        info.st_mtime_ns,
        info.st_ctime_ns,
    )


def _stable_snapshot(path: Path) -> tuple[int, ...]:
    return _stable_metadata(path.stat())


def _stable_content_snapshot(path: Path) -> tuple[tuple[int, ...], bytes]:
    return _stable_metadata(path.stat()), path.read_bytes()


@pytest.mark.parametrize(
    "field",
    ["st_dev", "st_ino", "st_mode", "st_uid", "st_gid", "st_nlink",
     "st_size", "st_mtime_ns", "st_ctime_ns"],
)
def test_stable_metadata_ignores_atime_but_detects_stable_drift(field: str) -> None:
    base = SimpleNamespace(
        st_dev=1,
        st_ino=2,
        st_mode=0o600,
        st_uid=3,
        st_gid=4,
        st_nlink=1,
        st_size=7,
        st_atime_ns=8,
        st_mtime_ns=9,
        st_ctime_ns=10,
    )
    atime_drift = SimpleNamespace(**{**vars(base), "st_atime_ns": 11})
    stable_drift = SimpleNamespace(**{
        **vars(base), field: getattr(base, field) + 1,
    })

    assert _stable_metadata(atime_drift) == _stable_metadata(base)
    assert _stable_metadata(stable_drift) != _stable_metadata(base)


def test_normal_acquisition_check_and_release(tmp_path: Path) -> None:
    lock = tmp_path / "observation.lock"
    lease = Lease(lock, "worker-a")

    assert lease.acquire() is True
    assert lease.check() is True
    assert lock.joinpath("owner").read_bytes() == b"worker-a"
    assert lease.release() is True
    assert not lock.exists()
    assert lease.check() is False


def test_repeated_acquisition_is_refused_and_release_allows_reuse(tmp_path: Path) -> None:
    lock = tmp_path / "observation.lock"
    lease = Lease(lock, "worker-a")

    assert lease.acquire() is True
    assert lease.acquire() is False
    assert Lease(lock, "worker-b").acquire() is False
    assert lease.release() is True
    assert lease.acquire() is True
    assert lease.release() is True


def test_existing_foreign_lock_is_refused_unchanged(tmp_path: Path) -> None:
    lock = tmp_path / "observation.lock"
    lock.mkdir()
    owner = lock / "owner"
    owner.write_bytes(b"foreign")
    before = (_stable_snapshot(lock), _stable_content_snapshot(owner))

    assert Lease(lock, "worker-a").acquire() is False

    after = (_stable_snapshot(lock), _stable_content_snapshot(owner))
    assert after == before


def test_symlink_lock_and_ancestor_are_rejected(tmp_path: Path) -> None:
    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    real_lock = real_parent / "observation.lock"
    lock_link = tmp_path / "lock-link"
    lock_link.symlink_to(real_lock, target_is_directory=True)
    assert Lease(lock_link, "worker-a").acquire() is False
    assert not real_lock.exists()

    parent_link = tmp_path / "parent-link"
    parent_link.symlink_to(real_parent, target_is_directory=True)
    ancestor_lock = parent_link / "ancestor.lock"
    assert Lease(ancestor_lock, "worker-a").acquire() is False
    assert not (real_parent / "ancestor.lock").exists()


def test_replaced_lock_fails_closed_and_preserves_replacement(tmp_path: Path) -> None:
    lock = tmp_path / "observation.lock"
    lease = Lease(lock, "worker-a")
    assert lease.acquire() is True

    (lock / "owner").unlink()
    lock.rmdir()
    lock.mkdir()
    (lock / "owner").write_bytes(b"replacement")

    assert lease.check() is False
    assert lease.release() is False
    assert (lock / "owner").read_bytes() == b"replacement"


def test_changed_owner_fails_closed_and_preserves_owner(tmp_path: Path) -> None:
    lock = tmp_path / "observation.lock"
    lease = Lease(lock, "worker-a")
    assert lease.acquire() is True

    owner = lock / "owner"
    owner.write_bytes(b"tampered")

    assert lease.check() is False
    assert lease.release() is False
    assert owner.read_bytes() == b"tampered"
    assert lock.exists()


def test_extra_child_fails_closed_and_preserves_directory(tmp_path: Path) -> None:
    lock = tmp_path / "observation.lock"
    lease = Lease(lock, "worker-a")
    assert lease.acquire() is True
    extra = lock / "child"
    extra.write_bytes(b"still in use")

    assert lease.check() is False
    assert lease.release() is False
    assert extra.read_bytes() == b"still in use"
    assert (lock / "owner").read_bytes() == b"worker-a"


def test_interrupted_owner_publication_preserves_partial_lock(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    lock = tmp_path / "observation.lock"

    def interrupted(path: Path, raw: bytes) -> tuple[int, int, int, int, int]:
        raise OSError("simulated interrupted publication")

    monkeypatch.setattr(observation_lease, "_write_exclusive_bytes", interrupted)
    with pytest.raises(OSError, match="interrupted publication"):
        Lease(lock, "worker-a").acquire()

    assert lock.is_dir()
    assert list(lock.iterdir()) == []
    assert Lease(lock, "worker-b").acquire() is False


def test_lease_has_no_automatic_context_manager_release(tmp_path: Path) -> None:
    lease = Lease(tmp_path / "observation.lock", "worker-a")
    assert not hasattr(lease, "__enter__")
    assert not hasattr(lease, "__exit__")
