"""The one-command collector: collect, reopen, and verify through scripts/luna."""

from __future__ import annotations

import json
import stat

import pytest

from shengji.rl import privileged_teacher_luna_rpc_collection as attempt_module
from shengji.rl import privileged_teacher_luna_rpc_supervisor as supervisor
from shengji.rl import privileged_teacher_luna_rpc_transport as rpc_transport
from shengji.rl.privileged_teacher_luna_rpc_runtime import RUNTIME_SCHEMA
from test_privileged_teacher_luna_rpc_collection import FakeCodexRun


SECRET = b"pt-luna-cli-test-secret-bytes!!!"
assert len(SECRET) == 32
RUNTIME = {
    "schema": RUNTIME_SCHEMA,
    "boot_identity_sha256": "b" * 64,
    "git_dirty": False,
    "codex_tool_catalog": {"schema": "pt-luna-codex-tool-catalog-v1"},
}


@pytest.fixture
def cli(monkeypatch):
    from scripts import luna as module

    fake = FakeCodexRun()

    def fake_transport(**kwargs):
        # The real transport class, driven by the fake provider instead of a
        # Codex process; every gate between the runner and the journal stays.
        kwargs["run_command"] = fake
        return rpc_transport.CodexExecPlannerTransport(**kwargs)

    monkeypatch.setattr(module, "source_identity", lambda _path: dict(RUNTIME))
    monkeypatch.setattr(attempt_module, "source_identity",
                        lambda _path: dict(RUNTIME))
    monkeypatch.setattr(attempt_module, "CodexExecPlannerTransport",
                        fake_transport)
    module.fake = fake
    return module


def _secret_file(tmp_path):
    path = tmp_path / "seed.secret"
    path.write_bytes(SECRET)
    path.chmod(0o600)
    return path


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


def test_cli_refuses_odd_game_count_and_open_secret_before_any_root(
        tmp_path, cli):
    secret_path = _secret_file(tmp_path)
    root = tmp_path / "run"
    with pytest.raises(supervisor.RPCSupervisorError, match="game count"):
        cli.main(["collect", "--games", "3", "--seed-secret",
                  str(secret_path), "--token-ceiling", "1000",
                  "--out", str(root), "--codex-binary", "/usr/bin/true"])
    assert not root.exists()
    secret_path.chmod(0o644)
    with pytest.raises(ValueError, match="private 32-byte"):
        cli.main(["collect", "--games", "2", "--seed-secret",
                  str(secret_path), "--token-ceiling", "1000",
                  "--out", str(root), "--codex-binary", "/usr/bin/true"])
    assert not root.exists()
    assert cli.fake.calls == 0
