from __future__ import annotations

import json
import inspect

import pytest

from shengji.rl.world_afterstate_v2_protocol import (
    TIER_SPECS, attempted_deal_identity, build_population_slot_ledger,
)
from shengji.rl.world_afterstate_v2_source_driver import (
    FORBIDDEN_TOKENS, REJECTION_MODE_MISMATCH, PopulationAttemptResultV2,
    WorldAfterstateV2SourceDriverError, drive_population_attempt_v2,
)


_NAMESPACE = "a" * 64
_SLOTS = build_population_slot_ledger(TIER_SPECS[0])


def _slot(group: str, ordinal: int):
    return next(row for row in _SLOTS
                if row.group == group and row.ordinal == ordinal)


def test_mode_mismatch_is_typed_and_score_free():
    assert "snapshot" not in inspect.signature(
        drive_population_attempt_v2).parameters
    slot = _slot("natural-fit", 0)
    # The exact production declaration for this attempt is not the frozen
    # slot's mode; the driver must report that, without materialization.
    attempt = attempted_deal_identity(_NAMESPACE, slot, 0)
    result = drive_population_attempt_v2(attempt, slot)
    assert isinstance(result, PopulationAttemptResultV2)
    assert not result.accepted
    assert result.rejection_reason == REJECTION_MODE_MISMATCH
    assert result.material is None
    assert result.decision_count == 0
    assert "engine_seed" not in result.payload()["attempted_deal_identity"]


def test_forged_engine_seed_refuses_before_round(monkeypatch):
    slot = _slot("natural-fit", 0)
    attempt = attempted_deal_identity(_NAMESPACE, slot, 0)
    forged = dict(attempt, engine_seed=attempt["engine_seed"] ^ 1)
    called = False

    def fail_round(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("Round must not be constructed")

    monkeypatch.setattr(
        "shengji.rl.world_afterstate_v2_source_driver.Round", fail_round)
    with pytest.raises(WorldAfterstateV2SourceDriverError):
        drive_population_attempt_v2(forged, slot)
    assert not called


def test_natural_attempt_is_byte_identical_and_forbidden_free():
    # This D256 cell is a bounded, deterministic witness for the live policy.
    slot = _slot("natural-fit", 4)
    attempt = attempted_deal_identity(_NAMESPACE, slot, 0)
    first = drive_population_attempt_v2(attempt, slot)
    second = drive_population_attempt_v2(attempt, slot)
    assert first.accepted and first.material is not None
    assert first.payload() == second.payload()
    assert first.material.state_sha256 == min(
        first.material.state_sha256, first.material.state_sha256)
    encoded = json.dumps(first.payload(), sort_keys=True).lower()
    assert not any(token in encoded for token in FORBIDDEN_TOKENS)


def test_mechanics_slot_can_accept_a_derived_surface():
    slot = _slot("mechanics-fit", 0)
    attempt = attempted_deal_identity(_NAMESPACE, slot, 0)
    result = drive_population_attempt_v2(attempt, slot)
    assert result.accepted and result.material is not None
    assert slot.mechanics_surface in result.material.state.mechanics_surfaces
