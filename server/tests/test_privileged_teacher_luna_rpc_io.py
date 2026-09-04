"""Crash-boundary witnesses for immutable PT-Luna RPC publication."""

from __future__ import annotations

import os

import pytest

from shengji.rl import privileged_teacher_luna_rpc_io as rpc_io


class ProcessDeath(BaseException):
    pass


def test_complete_staged_write_is_promoted_after_process_death(
        tmp_path, monkeypatch):
    target = tmp_path / "receipt.json"
    raw = b'{"complete":true}\n'
    real_link = rpc_io.os.link
    calls = 0

    def die_once(source, destination, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ProcessDeath()
        return real_link(source, destination, **kwargs)

    monkeypatch.setattr(rpc_io.os, "link", die_once)
    with pytest.raises(ProcessDeath):
        rpc_io.publish_exclusive_bytes(target, raw)
    assert not target.exists()
    assert rpc_io.partial_path(target).read_bytes() == raw

    rpc_io.publish_exclusive_bytes(target, raw)
    assert target.read_bytes() == raw
    assert not rpc_io.partial_path(target).exists()
    assert os.stat(target).st_mode & 0o777 == 0o400


def test_linked_final_and_partial_are_finished_after_process_death(
        tmp_path, monkeypatch):
    target = tmp_path / "receipt.json"
    raw = b'{"complete":true}\n'
    real_fsync = rpc_io._fsync_dir
    died = False

    def die_after_link(path):
        nonlocal died
        if not died and target.exists() and rpc_io.partial_path(target).exists():
            died = True
            raise ProcessDeath()
        return real_fsync(path)

    monkeypatch.setattr(rpc_io, "_fsync_dir", die_after_link)
    with pytest.raises(ProcessDeath):
        rpc_io.publish_exclusive_bytes(target, raw)
    assert target.read_bytes() == raw
    assert rpc_io.partial_path(target).read_bytes() == raw
    assert os.stat(target).st_ino == os.stat(rpc_io.partial_path(target)).st_ino
    assert os.stat(target).st_nlink == 2

    rpc_io.publish_exclusive_bytes(target, raw)
    assert target.read_bytes() == raw
    assert not rpc_io.partial_path(target).exists()
    assert os.stat(target).st_nlink == 1


def test_truncated_partial_refuses_or_repairs_only_when_explicit(
        tmp_path):
    target = tmp_path / "terminal.json"
    staged = rpc_io.partial_path(target)
    staged.write_bytes(b"truncated")
    staged.chmod(0o400)
    with pytest.raises(rpc_io.AtomicPublishError,
                       match="partial bytes drift"):
        rpc_io.publish_exclusive_bytes(target, b"complete\n")
    assert not target.exists()
    rpc_io.publish_exclusive_bytes(
        target, b"complete\n", repair_incomplete_partial=True)
    assert target.read_bytes() == b"complete\n"
