"""The one-command collector through scripts/luna: reopen and verify a sealed
run, and the flag-less recovery of a staged or linked seed secret (fixtures
and helpers in test_luna_cli)."""

from __future__ import annotations

import json
import os
import stat

import pytest

from shengji.luna import game as selfplay
from shengji.luna import supervisor as supervisor
from test_luna_cli import (RUNTIME, _census_commits_to, _collect_args,  # noqa: F401
                           _secret_file, cli)


def test_collect_then_reopen_then_verify_through_the_cli(
        tmp_path, capsys, cli):
    secret_path = _secret_file(tmp_path)
    root = tmp_path / "run"
    args = ["collect", "--games", "2", "--seed-secret", str(secret_path),
            "--token-ceiling", "1000000", "--out", str(root),
            "--workers", "2", "--codex-binary", "/usr/bin/true",
            "--per-game-deadline-seconds", "600", "--wall-seconds", "1000",
            "--per-call-wall-reserve-ms", "1000",
            "--per-game-token-cap", "100000",
            "--per-call-token-reserve", "1000"]
    assert cli.main(args) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["route"] == supervisor.COMPLETE_STATE_SOURCE_ACQUISITION
    assert first["completed_games"] == 2
    assert first["failed_games"] == first["pending_games"] == 0
    assert first["resource_totals"]["ledger_spent_tokens"] > 0
    provider_calls = cli.fake.calls
    assert provider_calls > 0
    assert stat.S_IMODE((root / "private").stat().st_mode) == 0o700
    assert stat.S_IMODE((root / "public").stat().st_mode) == 0o755
    terminal = json.loads((root / "public" / "terminal.json").read_text())
    assert terminal["receipt_sha256"] == first["receipt_sha256"]
    assert terminal["runtime_sha256"] == supervisor._sha(RUNTIME)
    assert json.loads((root / "private" / "census.json").read_text())[
        "game_count"] == 2
    assert not supervisor._forbidden(terminal)

    assert cli.main(args) == 0
    assert json.loads(capsys.readouterr().out) == first
    assert cli.fake.calls == provider_calls

    assert cli.main(["verify", str(root), "--seed-secret",
                     str(secret_path)]) == 0
    assert json.loads(capsys.readouterr().out) == first
    assert cli.fake.calls == provider_calls

    with pytest.raises(supervisor.RPCSupervisorError, match="seed drift"):
        other = tmp_path / "other.secret"
        other.write_bytes(b"x" * 32)
        other.chmod(0o600)
        cli.main(["verify", str(root), "--seed-secret", str(other)])


def _covering_secret():
    for _ in range(64):
        secret = os.urandom(32)
        try:
            selfplay.root_census(secret)
        except selfplay.PrivilegedTeacherLunaSelfPlayError:
            continue
        return secret
    raise AssertionError("no covering secret in 64 draws")


def _no_fresh_draw(cli, monkeypatch):
    def no_draw():
        raise AssertionError("drew a fresh secret over a recoverable seal")
    monkeypatch.setattr(cli, "_fresh_secret", no_draw)


def test_flagless_collect_recovers_a_staged_seed_secret(tmp_path, cli, monkeypatch):
    """Death after the stage fsync but before link(2): the staged bytes ARE
    the run's secret and must be promoted, never refused or redrawn."""
    root = tmp_path / "run"
    private = root / "private"
    private.mkdir(mode=0o700, parents=True)
    secret = _covering_secret()
    staged = private / ".seed_secret.partial"
    staged.write_bytes(secret)
    staged.chmod(0o400)
    _no_fresh_draw(cli, monkeypatch)
    assert cli.main(_collect_args(root)) == 0
    sealed = private / "seed_secret"
    assert sealed.is_file() and not staged.exists()
    assert os.stat(sealed).st_nlink == 1
    assert cli._secret(sealed) == secret
    assert _census_commits_to(root, secret)
    assert cli.fake.calls > 0


def test_flagless_collect_recovers_a_linked_seed_secret(tmp_path, cli, monkeypatch):
    """Death after link(2) but before the stage unlink: two names, one inode."""
    root = tmp_path / "run"
    private = root / "private"
    private.mkdir(mode=0o700, parents=True)
    secret = _covering_secret()
    sealed = private / "seed_secret"
    staged = private / ".seed_secret.partial"
    staged.write_bytes(secret)
    staged.chmod(0o400)
    os.link(staged, sealed)
    assert os.stat(sealed).st_nlink == 2
    _no_fresh_draw(cli, monkeypatch)
    assert cli.main(_collect_args(root)) == 0
    assert os.stat(sealed).st_nlink == 1 and not staged.exists()
    assert cli._secret(sealed) == secret
    assert _census_commits_to(root, secret)


def test_flagless_collect_refuses_a_stage_beside_unrelated_artifacts(
        tmp_path, cli, monkeypatch):
    root = tmp_path / "run"
    private = root / "private"
    private.mkdir(mode=0o700, parents=True)
    staged = private / ".seed_secret.partial"
    staged.write_bytes(_covering_secret())
    staged.chmod(0o400)
    (private / "census.json").write_bytes(b"{}")
    _no_fresh_draw(cli, monkeypatch)
    with pytest.raises(ValueError, match="beside other private artifacts"):
        cli.main(_collect_args(root))
    assert sorted(os.listdir(private)) == [".seed_secret.partial", "census.json"]
    assert cli.fake.calls == 0


def test_flagless_collect_refuses_an_incomplete_stage(tmp_path, cli, monkeypatch):
    root = tmp_path / "run"
    private = root / "private"
    private.mkdir(mode=0o700, parents=True)
    staged = private / ".seed_secret.partial"
    staged.write_bytes(b"short")
    staged.chmod(0o400)
    _no_fresh_draw(cli, monkeypatch)
    with pytest.raises(ValueError, match="remove it"):
        cli.main(_collect_args(root))
    assert staged.exists() and cli.fake.calls == 0
