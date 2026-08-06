"""Falsification tests for the bounded self-play RL entry contract."""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from shengji.rl import selfplay_contract
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


def test_snapshot_final_collision_cannot_overwrite_competitor(
        tmp_path, monkeypatch):
    torch = pytest.importorskip("torch")
    net = torch.nn.Linear(2, 1)
    real_sha256_file = selfplay_contract.sha256_file
    competitor = b"competitor already published these bytes"
    collision = {}

    def publish_competitor_before_link(path):
        digest = real_sha256_file(path)
        if str(path).endswith(".actor_000007.partial"):
            final = tmp_path / f"actor_000007_{digest[:12]}.pt"
            final.write_bytes(competitor)
            collision["final"] = final
        return digest

    monkeypatch.setattr(
        selfplay_contract, "sha256_file", publish_competitor_before_link)
    with pytest.raises(FileExistsError, match="refusing to overwrite"):
        selfplay_contract.save_immutable_snapshot(
            net, tmp_path, label="actor", sequence=7)
    assert collision["final"].read_bytes() == competitor
    assert (tmp_path / ".actor_000007.partial").exists()


def test_two_snapshot_coordinators_have_one_persistent_sequence_owner(tmp_path):
    torch = pytest.importorskip("torch")
    first_net = torch.nn.Linear(2, 1)
    second_net = torch.nn.Linear(2, 1)
    with torch.no_grad():
        first_net.weight.fill_(1)
        second_net.weight.fill_(2)
    barrier = threading.Barrier(2)

    def attempt(net):
        barrier.wait()
        try:
            return save_immutable_snapshot(
                net, tmp_path, label="actor", sequence=11)
        except FileExistsError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(attempt, (first_net, second_net)))
    refs = [value for value in outcomes if isinstance(value, CheckpointRef)]
    errors = [value for value in outcomes if isinstance(value, FileExistsError)]
    assert len(refs) == 1 and len(errors) == 1
    refs[0].verify()
    assert len(list(tmp_path.glob("actor_000011_*.pt"))) == 1
    assert (tmp_path / ".actor_000011.lock").is_file()
    assert not (tmp_path / ".actor_000011.partial").exists()


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


def test_dmc_gate_pass_promotes_exact_evaluated_candidate_not_newer_learner(
        tmp_path, monkeypatch):
    refs = {}
    for name, content in (
        ("incumbent", b"incumbent generation"),
        ("evaluated_candidate", b"bytes that passed the gate"),
        ("newer_learner", b"learner bytes produced while gate was pending"),
    ):
        path = tmp_path / f"{name}.pt"
        path.write_bytes(content)
        refs[name] = CheckpointRef.capture(path)

    def forbid_republication(*_args, **_kwargs):
        pytest.fail("gate resolution must not snapshot the current learner")

    monkeypatch.setattr(dmc2, "save_immutable_snapshot", forbid_republication)
    promoted, pool_addition, event = dmc2.resolve_gate(
        win_rate=0.55,
        candidate_ref=refs["evaluated_candidate"],
        incumbent_ref=refs["incumbent"],
        generator_ref=refs["incumbent"],
        gate_seed=12345,
    )

    assert promoted == refs["evaluated_candidate"]
    assert promoted != refs["newer_learner"]
    assert pool_addition == refs["incumbent"]
    assert event == {
        "event": "promote", "win_rate": 0.55, "seed": 12345,
        "incumbent": refs["incumbent"].as_dict(),
        "actor": refs["evaluated_candidate"].as_dict(),
    }
    promoted.verify()


def test_dmc_gate_hold_keeps_incumbent_and_refuses_generator_drift(tmp_path):
    refs = {}
    for name in ("incumbent", "candidate", "other_generator"):
        path = tmp_path / f"{name}.pt"
        path.write_bytes(name.encode())
        refs[name] = CheckpointRef.capture(path)

    held, pool_addition, event = dmc2.resolve_gate(
        win_rate=0.549,
        candidate_ref=refs["candidate"],
        incumbent_ref=refs["incumbent"],
        generator_ref=refs["incumbent"],
        gate_seed=67890,
    )
    assert held == refs["incumbent"]
    assert pool_addition is None
    assert event == {
        "event": "hold", "win_rate": 0.549, "seed": 67890,
        "incumbent": refs["incumbent"].as_dict(),
        "candidate": refs["candidate"].as_dict(),
    }

    with pytest.raises(RuntimeError, match="generator changed"):
        dmc2.resolve_gate(
            win_rate=0.60,
            candidate_ref=refs["candidate"],
            incumbent_ref=refs["incumbent"],
            generator_ref=refs["other_generator"],
            gate_seed=67891,
        )
