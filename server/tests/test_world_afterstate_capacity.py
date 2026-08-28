from __future__ import annotations

import copy
from pathlib import Path

import pytest

from shengji.engine.cards import RANKS
from shengji.rl.world_afterstate_capacity import (
    AUTHORITY,
    WorldAfterstateCapacityError,
    build_capacity_fixtures,
    run_capacity,
    validate_capacity_receipt,
)


def test_capacity_fixtures_cover_every_rank_and_reopen():
    audits = build_capacity_fixtures(13)
    assert len(audits) == 13
    assert {audit["source_state"]["trump_rank"] for audit in audits} \
        == set(RANKS)
    assert all(audit["prestate_sha256"] != audit["successor_sha256"]
               for audit in audits)


def test_tiny_cpu_capacity_receipt_is_outcome_blind(monkeypatch):
    import shengji.rl.world_afterstate_capacity as capacity
    monkeypatch.setattr(capacity, "_git", lambda _repo, *args:
                        "a" * 40 if args == ("rev-parse", "HEAD") else "")
    receipt = run_capacity(
        repo=Path.cwd(), expected_git="a" * 40, fixture_count=13,
        worker_counts=[1], worker_repetitions=1, batch_sizes=[2],
        model_steps=1, device_name="cpu")
    validate_capacity_receipt(receipt)
    assert receipt["authority"] == AUTHORITY
    assert receipt["outcome_blind"] is True
    assert len(receipt["model_measurements"]) == 3


def test_capacity_receipt_authority_and_rank_coverage_are_load_bearing(
        monkeypatch):
    import shengji.rl.world_afterstate_capacity as capacity
    monkeypatch.setattr(capacity, "_git", lambda _repo, *args:
                        "b" * 40 if args == ("rev-parse", "HEAD") else "")
    receipt = run_capacity(
        repo=Path.cwd(), expected_git="b" * 40, fixture_count=13,
        worker_counts=[1], worker_repetitions=1, batch_sizes=[1],
        model_steps=1, device_name="cpu")
    forged = copy.deepcopy(receipt)
    forged["authority"]["training_authorized"] = True
    with pytest.raises(WorldAfterstateCapacityError,
                       match="authority drift"):
        validate_capacity_receipt(forged)
    forged = copy.deepcopy(receipt)
    del forged["fixtures"]["trump_rank_counts"][RANKS[-1]]
    with pytest.raises(WorldAfterstateCapacityError,
                       match="trump-rank coverage drift"):
        validate_capacity_receipt(forged)
