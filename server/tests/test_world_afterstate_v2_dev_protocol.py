from __future__ import annotations

from dataclasses import replace
import hashlib
from types import SimpleNamespace

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
    ValueV2DevPartialCoverageReceipt,
    ValueV2DevProtocolReceipt,
    WorldAfterstateV2DevProtocolError,
    build_value_v2_dev_partial_protocol,
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


def test_partial_protocol_keeps_fixed_d64_and_refuses_selected_missing_slot(
        monkeypatch):
    population = _population(monkeypatch)
    full = build_value_v2_dev_protocol(population)
    ledger = build_population_slot_ledger(TIER_SPECS[0])
    selected_positions = (*range(0, 32), *range(128, 136),
                          *range(160, 172), *range(208, 220))
    rows = []
    for position, material in zip(selected_positions, full.materials,
                                  strict=True):
        slot = ledger[position]
        digest = hashlib.sha256(
            canonical_json_bytes({"material": position})).hexdigest()
        rows.append({
            "schema": "world-afterstate-v2-population-material-artifact-v1",
            "relative_path":
                f"population/materials/state-{material.state_sha256}.json",
            "tier": "D256", "split": slot.split, "source": slot.source,
            "ordinal": slot.ordinal, "deal_sha256": material.deal_sha256,
            "slot_sha256": slot.slot_sha256,
            "state_sha256": material.state_sha256,
            "candidate_set_sha256": material.candidate_set_sha256,
            "byte_count": 1, "sha256": digest,
            "material_sha256": full.selected_identities[
                len(rows)].material_sha256,
        })
    missing = {**ledger[144].payload(),
               "slot_sha256": ledger[144].slot_sha256}
    coverage = SimpleNamespace(
        freeze_sha256="f" * 64, population_namespace_sha256="b" * 64,
        admission_sha256="a" * 64, config_sha256="c" * 64,
        accepted_slots=255, missing_slots=(missing,),
        selected_identities=tuple(item.payload()
                                  for item in full.selected_identities),
        selected_shard_rows=tuple(rows),
        selected_materials=full.materials, orphan_started=())

    partial = build_value_v2_dev_partial_protocol(coverage)
    assert isinstance(partial, ValueV2DevPartialCoverageReceipt)
    assert partial.materials == full.materials
    assert partial.payload()["coverage_complete"] is False
    assert partial.payload()["missing_slots"] == [missing]

    coverage.missing_slots = (
        {**ledger[0].payload(), "slot_sha256": ledger[0].slot_sha256},)
    with pytest.raises(WorldAfterstateV2DevProtocolError,
                       match="missing slot identity"):
        build_value_v2_dev_partial_protocol(coverage)
