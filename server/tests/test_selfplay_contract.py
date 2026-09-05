"""Falsification tests for the bounded self-play RL entry contract."""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from shengji.rl import selfplay_contract
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
