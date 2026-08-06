"""Falsification tests for the bounded self-play RL entry contract."""
from __future__ import annotations

import pytest

from shengji.rl import dmc2
from shengji.rl.selfplay_contract import (CheckpointRef, derive_job_seed,
                                           load_verified, role_sign,
                                           save_immutable_snapshot,
                                           signed_oracle_residual,
                                           signed_oracle_residual_by_sign,
                                           signed_return)


def test_attacker_and_defender_targets_are_exact_antisymmetric():
    for terminal, baseline in ((3.5, 1.25), (-2.5, -0.75), (0.5, 0.5)):
        attacker = signed_oracle_residual(terminal, baseline, True)
        defender = signed_oracle_residual(terminal, baseline, False)
        assert attacker == pytest.approx(terminal - baseline)
        assert defender == pytest.approx(-terminal + baseline)
        assert defender == pytest.approx(-attacker)
        assert signed_oracle_residual_by_sign(
            terminal, baseline, -1) == pytest.approx(defender)
        assert signed_return(terminal, False) == -signed_return(terminal, True)
    assert role_sign(True) == 1 and role_sign(False) == -1


def test_checkpoint_reference_refuses_mutated_actor_bytes(tmp_path):
    path = tmp_path / "actor.pt"
    path.write_bytes(b"generation-a")
    ref = CheckpointRef.capture(path)
    ref.verify()
    path.write_bytes(b"generation-b")
    with pytest.raises(RuntimeError, match="checkpoint digest drift"):
        ref.verify()


def test_verified_load_checks_both_sides_of_the_load(tmp_path):
    path = tmp_path / "actor.pt"
    path.write_bytes(b"generation-a")
    ref = CheckpointRef.capture(path)

    def mutating_loader(raw_path):
        path.write_bytes(b"generation-b")
        return raw_path

    with pytest.raises(RuntimeError, match="checkpoint digest drift"):
        load_verified(ref, mutating_loader)


def test_snapshot_publication_is_atomic_unique_and_digest_bound(tmp_path):
    torch = pytest.importorskip("torch")
    net = torch.nn.Linear(2, 1)
    first = save_immutable_snapshot(net, tmp_path, label="actor", sequence=0)
    first.verify()
    assert not list(tmp_path.glob("*.partial"))
    second = save_immutable_snapshot(net, tmp_path, label="actor", sequence=1)
    second.verify()
    assert first.path != second.path
    with pytest.raises(FileExistsError, match="reused snapshot sequence"):
        save_immutable_snapshot(net, tmp_path, label="actor", sequence=0)


def test_named_job_seed_is_replayable_and_domain_separated():
    common = dict(experiment="s2-micro-v1", root_seed=20260806,
                  sequence=7, actor_sha256="abc")
    a = derive_job_seed(**common, purpose="actor")
    assert a == derive_job_seed(**common, purpose="actor")
    assert a != derive_job_seed(**common, purpose="gate")
    assert a != derive_job_seed(**{**common, "sequence": 8}, purpose="actor")
    assert a != derive_job_seed(**{**common, "actor_sha256": "def"},
                                purpose="actor")


def test_dmc_actor_records_raw_attacker_return_and_explicit_role_sign(
        tmp_path, monkeypatch):
    checkpoint = tmp_path / "actor.pt"
    checkpoint.write_bytes(b"fixed actor")
    ref = CheckpointRef.capture(checkpoint)

    class FakeRound:
        attacker_points = 120

        @staticmethod
        def is_attacker(seat):
            return seat == 0

    class FakeGame:
        def __init__(self, _rng):
            self.round = None

    def fake_play(game, bots):
        actor = next(bot for bot in bots if isinstance(bot, dmc2.V2Actor))
        actor.records = [
            ([1.0] * dmc2.OBS_DIM,
             [[2.0] * dmc2.ACT_DIM, [3.0] * dmc2.ACT_DIM],
             0, [4.0] * dmc2.ORACLE_DIM, 0),
            ([5.0] * dmc2.OBS_DIM,
             [[6.0] * dmc2.ACT_DIM, [7.0] * dmc2.ACT_DIM],
             1, [8.0] * dmc2.ORACLE_DIM, 1),
        ]
        game.round = FakeRound()

    monkeypatch.setattr(dmc2, "load_any_net", lambda _path: object())
    monkeypatch.setattr(dmc2, "Game", FakeGame)
    monkeypatch.setattr(dmc2, "play_round", fake_play)
    result = dmc2.actor_batch((ref, [], 1, 0.1, 99, 7))
    attacker_returns, signs, meta = result[-3:]
    assert attacker_returns.tolist() == [1.5, 1.5]
    assert signs.tolist() == [1, -1]
    assert meta["sequence"] == 7 and meta["actor"] == ref.as_dict()

    def empty_play(game, bots):
        actor = next(bot for bot in bots if isinstance(bot, dmc2.V2Actor))
        actor.records = []
        game.round = FakeRound()

    monkeypatch.setattr(dmc2, "play_round", empty_play)
    empty = dmc2.actor_batch((ref, [], 1, 0.1, 100, 8))
    assert empty[0].shape == (0, dmc2.OBS_DIM)
    assert empty[1].shape == (0, dmc2.ACT_DIM)
    assert empty[4].shape == (0, dmc2.ORACLE_DIM)


def test_dmc_gate_loads_each_immutable_generation_once(tmp_path, monkeypatch):
    paths = []
    for name in ("candidate", "incumbent"):
        path = tmp_path / f"{name}.pt"
        path.write_bytes(name.encode())
        paths.append(CheckpointRef.capture(path))
    loads = []

    def fake_load(ref, _loader):
        ref.verify()
        loads.append(ref.sha256)
        return object()

    class FakeGame:
        def __init__(self, _rng):
            self.result = None

    class FakeResult:
        winner_team = 0

    def fake_play(game, _bots):
        game.result = FakeResult()

    monkeypatch.setattr(dmc2, "load_verified", fake_load)
    monkeypatch.setattr(dmc2, "Game", FakeGame)
    monkeypatch.setattr(dmc2, "play_round", fake_play)
    dmc2.duel((paths[0], paths[1], 3, 123))
    assert loads == [paths[0].sha256, paths[1].sha256]
