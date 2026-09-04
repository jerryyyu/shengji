"""The one-command collector: collect, reopen, and verify through scripts/luna."""

from __future__ import annotations

import json
import os
import stat

import pytest

from shengji.luna import attempt as attempt_module
from shengji.luna import game as selfplay
from shengji.luna import supervisor as supervisor
from shengji.luna import transport as rpc_transport
from shengji.luna.runtime import RUNTIME_SCHEMA
from test_luna_attempt import FakeCodexRun


SECRET = b"pt-luna-cli-test-secret-bytes!!!"
assert len(SECRET) == 32
# Found by search: its 52 fresh roots are unique but none declares NT, the
# shortfall that cost an operator a launch (about 0.3% of random secrets).
NON_COVERING_SECRET = bytes.fromhex(
    "553d0f8e37a47cd7812db9341006b5a48a5a5142700faf364084a7087536b6fe")
assert len(NON_COVERING_SECRET) == 32
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


def _collect_args(root, *extra):
    return ["collect", "--games", "2", "--token-ceiling", "1000000",
            "--out", str(root), "--workers", "2",
            "--codex-binary", "/usr/bin/true",
            "--per-game-deadline-seconds", "600", "--wall-seconds", "1000",
            "--per-call-wall-reserve-ms", "1000",
            "--per-game-token-cap", "100000",
            "--per-call-token-reserve", "1000", *extra]


def _non_covering_secret():
    """A secret the supervisor's own census refuses.

    The pinned secret is tried first; a bounded random search only runs if
    an engine change made it cover, and skips rather than passes vacuously.
    """
    for attempt in range(2000):
        secret = NON_COVERING_SECRET if attempt == 0 else os.urandom(32)
        try:
            selfplay.root_census(secret)
        except selfplay.PrivilegedTeacherLunaSelfPlayError:
            return secret
    pytest.skip("no non-covering seed secret within 2000 draws")


def _census_commits_to(root, secret):
    census = json.loads((root / "private" / "census.json").read_text())
    return census["seed_commitment_sha256"] == supervisor._sha_bytes(secret)


def test_collect_draws_and_seals_a_covering_secret_when_the_flag_is_omitted(
        tmp_path, capsys, cli):
    root = tmp_path / "run"
    seed_path = root / "private" / "seed_secret"
    sealed_at_provider_call = []
    cli.fake.after_call = lambda: sealed_at_provider_call.append(
        seed_path.is_file()
        and stat.S_IMODE(seed_path.stat().st_mode) == 0o400)

    assert cli.main(_collect_args(root)) == 0
    first = json.loads(capsys.readouterr().out)
    assert first["route"] == supervisor.COMPLETE_STATE_SOURCE_ACQUISITION
    assert first["completed_games"] == 2
    assert first["seed_secret_path"] == str(seed_path)
    # Sealed before the first game asked the provider for anything.
    assert sealed_at_provider_call and all(sealed_at_provider_call)
    info = seed_path.lstat()
    assert stat.S_ISREG(info.st_mode)
    assert stat.S_IMODE(info.st_mode) == 0o400
    assert (info.st_nlink, info.st_size) == (1, 32)
    assert not (root / "private" / ".seed_secret.partial").exists()
    assert stat.S_IMODE((root / "private").stat().st_mode) == 0o700
    # The collector's own private-32-byte gate accepts what it sealed, and
    # the supervisor's census of those bytes covers every trump mode.
    secret = cli._secret(seed_path)
    assert len(secret) == 32
    selfplay.validate_root_census(selfplay.root_census(secret))
    assert _census_commits_to(root, secret)

    # A second flag-less collect reopens the sealed run with that secret.
    provider_calls = cli.fake.calls
    assert cli.main(_collect_args(root)) == 0
    assert json.loads(capsys.readouterr().out) == first
    assert cli.fake.calls == provider_calls
    assert cli._secret(seed_path) == secret


def test_collect_refuses_a_supplied_non_covering_secret_before_any_setup(
        tmp_path, cli, monkeypatch):
    secret = _non_covering_secret()
    secret_path = tmp_path / "seed.secret"
    secret_path.write_bytes(secret)
    secret_path.chmod(0o600)
    root = tmp_path / "run"

    def too_late(*_args, **_kwargs):
        raise AssertionError("setup ran before the coverage refusal")

    # Runtime attestation, the schedule (where the supervisor's own refusal
    # used to surface), and the supervisor with its ledger and attempts are
    # all downstream of the refusal; none may run.
    monkeypatch.setattr(cli, "source_identity", too_late)
    monkeypatch.setattr(cli, "schedule_for_games", too_late)
    monkeypatch.setattr(cli, "PTLunaRPCSupervisor", too_late)
    with pytest.raises(ValueError) as refusal:
        cli.main(["collect", "--games", "2", "--seed-secret",
                  str(secret_path), "--token-ceiling", "1000",
                  "--out", str(root), "--codex-binary", "/usr/bin/true"])
    message = str(refusal.value)
    assert f"seed secret {secret_path} does not cover the root census" in message
    assert "trump modes covered" in message and "unique roots" in message
    assert "omit --seed-secret so collect draws a covering secret" in message
    if secret == NON_COVERING_SECRET:
        assert "covered S,H,C,D, missing NT; 52/52 unique roots" in message
    assert not root.exists()
    assert cli.fake.calls == 0


def test_collect_redraws_until_the_census_validator_accepts(
        tmp_path, capsys, cli, monkeypatch):
    rejected = 3
    draws = [bytes([n]) * 32 for n in range(1, rejected + 1)] + [SECRET]
    handed = []

    def scripted_draw():
        handed.append(draws[len(handed)])
        return handed[-1]

    verdicts = []
    real_validate = selfplay.validate_root_census

    def gate(census, *, design=None):
        # The supervisor's validator, refusing the first ``rejected`` censuses.
        verdicts.append(census)
        if len(verdicts) <= rejected:
            raise selfplay.PrivilegedTeacherLunaSelfPlayError(
                "root census coverage drift")
        return real_validate(census, design=design)

    monkeypatch.setattr(cli, "_fresh_secret", scripted_draw)
    monkeypatch.setattr(selfplay, "validate_root_census", gate)
    root = tmp_path / "run"
    assert cli.main(_collect_args(root)) == 0
    assert json.loads(capsys.readouterr().out)["completed_games"] == 2
    assert handed == draws
    assert cli._secret(root / "private" / "seed_secret") == draws[rejected]
    assert _census_commits_to(root, draws[rejected])


def test_collect_refuses_when_no_draw_covers_within_the_bound(
        tmp_path, cli, monkeypatch):
    bound = 4
    monkeypatch.setattr(cli, "SEED_DRAW_ATTEMPTS", bound)
    drawn = []
    real_draw = cli._fresh_secret

    def counting_draw():
        if len(drawn) >= 2 * bound:
            raise AssertionError("redraw loop ignores its bound")
        drawn.append(real_draw())
        return drawn[-1]

    verdicts = []

    def never(census, *, design=None):
        verdicts.append(census)
        raise selfplay.PrivilegedTeacherLunaSelfPlayError(
            "root census coverage drift")

    monkeypatch.setattr(cli, "_fresh_secret", counting_draw)
    monkeypatch.setattr(selfplay, "validate_root_census", never)
    root = tmp_path / "run"
    with pytest.raises(ValueError, match=rf"no covering seed secret in {bound} "
                       r"draws") as refusal:
        cli.main(_collect_args(root))
    assert "trump modes covered" in str(refusal.value)
    assert len(drawn) == bound == len(verdicts)
    assert len(set(drawn)) == bound
    assert not root.exists()
    assert cli.fake.calls == 0


def test_collect_never_draws_into_a_root_that_already_holds_a_run(
        tmp_path, cli, monkeypatch):
    root = tmp_path / "run"
    private = root / "private"
    private.mkdir(mode=0o700, parents=True)
    (private / "census.json").write_bytes(b"{}")

    def no_draw():
        raise AssertionError("drew a secret into a used root")

    monkeypatch.setattr(cli, "_fresh_secret", no_draw)
    with pytest.raises(ValueError, match="supply --seed-secret"):
        cli.main(_collect_args(root))
    assert sorted(os.listdir(private)) == ["census.json"]
    assert cli.fake.calls == 0


def test_verify_reads_the_sealed_seed_secret_when_the_flag_is_omitted(
        tmp_path, capsys, cli):
    root = tmp_path / "run"
    seed_path = root / "private" / "seed_secret"
    assert cli.main(_collect_args(root)) == 0
    first = json.loads(capsys.readouterr().out)
    provider_calls = cli.fake.calls

    assert cli.main(["verify", str(root)]) == 0
    assert json.loads(capsys.readouterr().out) == first
    assert cli.fake.calls == provider_calls

    # The bytes come from that file: another private secret there is seed
    # drift, and without the file the flag is required again.
    seed_path.unlink()
    seed_path.write_bytes(SECRET)
    seed_path.chmod(0o600)
    with pytest.raises(supervisor.RPCSupervisorError, match="seed drift"):
        cli.main(["verify", str(root)])
    seed_path.unlink()
    with pytest.raises(ValueError, match="--seed-secret"):
        cli.main(["verify", str(root)])
    assert cli.fake.calls == provider_calls
