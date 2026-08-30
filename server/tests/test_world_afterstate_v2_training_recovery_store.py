import hashlib
from pathlib import Path

import pytest

import shengji.rl.world_afterstate_v2_training_recovery_store as store_module
from shengji.rl.world_afterstate_v2_training_recovery_store import (
    RecoveryStoreBindingV2, WorldAfterstateV2RecoveryStore,
    WorldAfterstateV2RecoveryStoreError)


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _store(tmp_path: Path, members: int = 4) -> WorldAfterstateV2RecoveryStore:
    return WorldAfterstateV2RecoveryStore(
        tmp_path / "recovery",
        RecoveryStoreBindingV2(
            freeze_sha256=_digest("freeze"), admission_sha256=_digest("admission"),
            cohort_name="natural", seed_block=1,
            population_sha256=_digest("population"),
            selection_population_sha256=_digest("selection"),
            config_sha256=_digest("config"), member_count=members))


class _Opened:
    def __init__(self, raw: bytes, member: int, epoch: int = 1):
        self.metadata = {
            "completed_epoch": epoch, "seed_block": 1,
            "member_index": member, "control_name": "natural",
            "freeze_sha256": _digest("freeze"),
            "config_sha256": _digest("config"),
            "population_sha256": _digest("population"),
            "selection_population_sha256": _digest("selection"),
            "common_epoch_sha256": _digest("common"),
        }


def _fake_reopen(raw, *, expected_freeze_sha256,
                 expected_selection_population_sha256):
    # The test seam only needs to model the already-verified recovery boundary.
    text = raw.decode()
    epoch, member = text.split(":")
    return _Opened(raw, int(member), int(epoch))


def test_publish_restart_returns_exact_complete_history(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "reopen_recovery", _fake_reopen)
    target = _store(tmp_path)
    first = tuple(f"1:{member}".encode() for member in range(4))
    second = tuple(f"2:{member}".encode() for member in range(4))
    receipt = target.publish_epoch(1, first)
    assert receipt.completed_epoch_count == 1
    target.publish_epoch(2, second)
    assert target.reopen_history() == (first, second)
    restarted = _store(tmp_path)
    assert restarted.reopen_history() == (first, second)


def test_partial_callback_failure_is_not_manifest_visible(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "reopen_recovery", _fake_reopen)
    target = _store(tmp_path)
    blobs = tuple(f"1:{member}".encode() for member in range(4))

    def fail(_blobs):
        raise RuntimeError("stop before manifest")

    with pytest.raises(WorldAfterstateV2RecoveryStoreError, match="callback"):
        target.publish_epoch(1, blobs, callback=fail)
    assert target.reopen_history() == ()
    assert (target.root / "epochs" / "epoch-1.partial").is_dir()
    target.publish_epoch(1, blobs)
    assert target.reopen_history() == (blobs,)


def test_partial_some_members_are_reused_and_missing_members_added(
        tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "reopen_recovery", _fake_reopen)
    target = _store(tmp_path)
    blobs = tuple(f"1:{member}".encode() for member in range(4))
    partial = target.root / "epochs" / "epoch-1.partial"
    partial.mkdir()
    for member in (0, 2):
        store_module.publish_exclusive_bytes(
            partial / f"member-{member}.bin", blobs[member])
    assert target.reopen_history() == ()
    target.publish_epoch(1, blobs)
    assert target.reopen_history() == (blobs,)


def test_partial_changed_retry_and_malformed_partial_fail(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "reopen_recovery", _fake_reopen)
    target = _store(tmp_path)
    blobs = tuple(f"1:{member}".encode() for member in range(4))

    def fail(_blobs):
        raise RuntimeError("stop before manifest")

    with pytest.raises(WorldAfterstateV2RecoveryStoreError, match="callback"):
        target.publish_epoch(1, blobs, callback=fail)
    changed = tuple(b"1:01" if member == 1 else raw
                    for member, raw in enumerate(blobs))
    with pytest.raises(WorldAfterstateV2RecoveryStoreError, match="mismatch"):
        target.publish_epoch(1, changed)

    malformed = _store(tmp_path / "malformed")
    partial = malformed.root / "epochs" / "epoch-1.partial"
    partial.mkdir()
    (partial / "unexpected.bin").write_bytes(b"malformed")
    with pytest.raises(WorldAfterstateV2RecoveryStoreError, match="extra"):
        malformed.reopen_history()


def test_tamper_and_mixed_member_are_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "reopen_recovery", _fake_reopen)
    target = _store(tmp_path)
    blobs = tuple(f"1:{member}".encode() for member in range(4))
    target.publish_epoch(1, blobs)
    member = target.root / "epochs" / "epoch-1" / "member-2.bin"
    member.chmod(0o600)
    member.write_bytes(b"1:3")
    member.chmod(0o400)
    with pytest.raises(WorldAfterstateV2RecoveryStoreError, match="rehash"):
        target.reopen_history()


def test_noncontiguous_and_single_member_shape(tmp_path, monkeypatch):
    monkeypatch.setattr(store_module, "reopen_recovery", _fake_reopen)
    target = _store(tmp_path, members=1)
    target.publish_epoch(1, b"1:0")
    assert target.reopen_history() == (b"1:0",)
    with pytest.raises(WorldAfterstateV2RecoveryStoreError, match="noncontiguous"):
        target.publish_epoch(3, b"3:0")
