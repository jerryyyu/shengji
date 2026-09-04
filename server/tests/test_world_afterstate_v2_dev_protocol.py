from __future__ import annotations

from dataclasses import replace
import hashlib

import pytest

from shengji.rl.belief_contract import canonical_json_bytes
from shengji.rl.world_afterstate_v2_population import (
    PopulationCandidateV2,
    PopulationMaterialV2,
)
from shengji.rl.world_afterstate_v2_protocol import (
    RANKS,
    build_population_slot_ledger,
    TIER_SPECS,
    StateCandidateV2,
)
from shengji.rl.world_afterstate_v2_dev_protocol import (
    DEV_GROUP_COUNTS,
    DEV_SUBFOLD_COUNTS,
    ValueV2DevProtocolReceipt,
    WorldAfterstateV2DevProtocolError,
    build_value_v2_dev_protocol,
    validate_value_v2_dev_protocol,
)


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _population(monkeypatch: pytest.MonkeyPatch) -> tuple[PopulationMaterialV2, ...]:
    # The protocol under test binds already-validated materials.  Keep this
    # fixture independent of engine replay by replacing that prior boundary;
    # all slot/state axes are still real typed contract values.
    monkeypatch.setattr(PopulationMaterialV2, "validate", lambda self: None)
    ledger = build_population_slot_ledger(TIER_SPECS[0])
    result = []
    for index, slot in enumerate(ledger):
        cell = slot.cell or ("early", "lead", "attacker")
        surfaces = ((slot.mechanics_surface,) if slot.mechanics_surface
                    else ())
        state = StateCandidateV2(
            deal_sha256=_sha(("deal", index)),
            slot_sha256=slot.slot_sha256,
            state_sha256=_sha(("state", index)),
            source=slot.source, split=slot.split,
            phase=cell[0], position=cell[1], role=cell[2],
            trump_rank=slot.trump_rank, trump_mode=slot.trump_mode,
            select_subfold=slot.select_subfold,
            mechanics_surfaces=surfaces, legal_candidate_count=2)
        successors = (_sha(("successor", index, 0)),
                      _sha(("successor", index, 1)))
        candidates = tuple(PopulationCandidateV2(
            candidate_index=offset,
            action_sha256=_sha(("action", index, offset)),
            audit_sha256=_sha(("audit", index, offset)),
            successor_sha256=successor,
            origin="production-ballot", protected_incumbent=offset == 0)
                           for offset, successor in enumerate(successors))
        result.append(PopulationMaterialV2(
            state=state, candidate_set_sha256=_sha(("set", index)),
            candidates=candidates, audit_raws=(b"a", b"b"),
            prestate={"index": index}))
    return tuple(result)


def test_d64_has_frozen_counts_order_and_adjacent_pairs(monkeypatch):
    population = _population(monkeypatch)
    receipt = build_value_v2_dev_protocol(population)
    ledger = build_population_slot_ledger(TIER_SPECS[0])

    assert isinstance(receipt, ValueV2DevProtocolReceipt)
    assert receipt.materials == (population[0:32] + population[128:136]
                                 + population[160:172] + population[208:220])
    assert receipt.per_group_counts == DEV_GROUP_COUNTS
    assert receipt.per_subfold_counts == DEV_SUBFOLD_COUNTS
    assert tuple(item.slot_sha256 for item in receipt.selected_identities) == \
        tuple(slot.slot_sha256 for slot in (ledger[0:32] + ledger[128:136]
                                            + ledger[160:172]
                                            + ledger[208:220]))
    for start, count in ((0, 32), (32, 8)):
        pair_ids = [receipt.selected_identities[index].ordinal // 2
                    for index in range(start, start + count)]
        assert all(pair_ids[index] == pair_ids[index + 1]
                   for index in range(0, count, 2))
    assert [item.select_subfold for item in receipt.selected_identities[40:52]] \
        == ["epoch-select", "precision-select"] * 6
    assert receipt.canonical_sha256 == _sha(receipt.payload())
    assert b"outcome" not in receipt.canonical_bytes()
    assert b"label" not in receipt.canonical_bytes()


def test_d64_is_deterministic_and_rejects_population_drift(monkeypatch):
    population = _population(monkeypatch)
    first = build_value_v2_dev_protocol(population)
    second = build_value_v2_dev_protocol(tuple(population))
    assert first.payload() == second.payload()
    assert first.canonical_sha256 == second.canonical_sha256

    for forged in (population[:-1],
                   population[:1] + population[2:3] + population[1:2]
                   + population[3:]):
        with pytest.raises(WorldAfterstateV2DevProtocolError):
            build_value_v2_dev_protocol(forged)

    foreign = replace(population[0], state=replace(
        population[0].state, slot_sha256=population[1].slot_sha256,
        trump_rank=RANKS[1]))
    forged = (foreign,) + population[1:]
    with pytest.raises(WorldAfterstateV2DevProtocolError):
        build_value_v2_dev_protocol(forged)


def test_selection_mutation_is_refused(monkeypatch):
    population = _population(monkeypatch)
    receipt = build_value_v2_dev_protocol(population)
    forged = replace(receipt, materials=(receipt.materials[1],)
                     + receipt.materials[1:])
    with pytest.raises(WorldAfterstateV2DevProtocolError):
        forged.validate()
    with pytest.raises(WorldAfterstateV2DevProtocolError):
        validate_value_v2_dev_protocol(population, forged)
