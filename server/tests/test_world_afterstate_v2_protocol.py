from __future__ import annotations

import hashlib

import pytest

from shengji.rl.world_afterstate_v2_protocol import (
    AUTHORITY, P0_CELLS, SELECT_SUBFOLDS, TIER_SPECS, TRUMP_MODES,
    CapacityTierReceiptV2, PopulationSlotV2, StateCandidateV2,
    WorldAfterstateV2ProtocolError, attempted_deal_identity,
    build_population_slot_ledger, choose_capacity_tier, protocol_payload,
    select_one_state_per_deal, select_p0_population, validate_p0_population,
    validate_population_slot_ledger,
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def _state(index: int, slot: PopulationSlotV2, *,
           state_suffix: str = "a",
           cell: tuple[str, str, str] | None = None,
           mechanics_surfaces: tuple[str, ...] = ()) -> StateCandidateV2:
    selected_cell = slot.cell if cell is None else cell
    assert selected_cell is not None
    return StateCandidateV2(
        deal_sha256=_sha(f"deal-{index}"),
        slot_sha256=slot.slot_sha256,
        state_sha256=_sha(f"state-{index}-{state_suffix}"),
        source=slot.source, split=slot.split, phase=selected_cell[0],
        position=selected_cell[1], role=selected_cell[2],
        trump_rank=slot.trump_rank, trump_mode=slot.trump_mode,
        mechanics_surfaces=mechanics_surfaces, legal_candidate_count=2)


def _receipt(tier: str, **changes: object) -> CapacityTierReceiptV2:
    values: dict[str, object] = {
        "tier": tier, "host_logical_cpus": 16,
        "exact_source_supply": True, "byte_identical": True,
        "outcomes_opened": False, "all_core_gate_passed": True,
        "label_wall_seconds": 10_000, "label_cpu_seconds": 170_000,
        "complete_dag_wall_seconds": 20_000,
        "service_wall_seconds": 43_200,
        "peak_memory_bytes": 25_000, "memory_limit_bytes": 30_000,
        "composed_artifact_bytes": 75_000,
        "free_disk_bytes_before": 100_000,
    }
    values.update(changes)
    return CapacityTierReceiptV2(**values)  # type: ignore[arg-type]


def test_tier_arithmetic_and_protocol_authority_are_exact() -> None:
    assert [(tier.name, tier.fit, tier.total) for tier in TIER_SPECS] == [
        ("D256", 160, 256), ("D512", 384, 512),
        ("D1024", 768, 1024),
    ]
    assert AUTHORITY and not any(AUTHORITY.values())
    payload = protocol_payload()
    assert payload == protocol_payload()
    assert payload["capacity_host_logical_cpus"] == 16
    assert payload["complete_dag_wall_seconds_max"] == 21_600
    assert payload["trump_modes"] == list(TRUMP_MODES)
    assert set(payload["population_slot_ledger_sha256s"]) == {
        tier.name for tier in TIER_SPECS}


def test_preplay_slot_ledgers_have_exact_groups_and_paired_select_census() \
        -> None:
    expected_groups = {
        "D256": {
            "natural-fit": 128, "mechanics-fit": 32,
            "natural-select": 48, "natural-audit": 48,
        },
        "D512": {
            "natural-fit": 256, "diverse-fit-sol": 32,
            "diverse-fit-luna": 16, "diverse-fit-human": 16,
            "mechanics-fit": 64, "natural-select": 64,
            "natural-audit": 64,
        },
        "D1024": {
            "natural-fit": 512, "diverse-fit-sol": 64,
            "diverse-fit-luna": 32, "diverse-fit-human": 32,
            "mechanics-fit": 128, "natural-select": 128,
            "natural-audit": 128,
        },
    }
    for tier in TIER_SPECS:
        slots = build_population_slot_ledger(tier)
        validate_population_slot_ledger(slots, tier=tier)
        assert len(slots) == tier.total
        assert {
            group: sum(slot.group == group for slot in slots)
            for group in expected_groups[tier.name]
        } == expected_groups[tier.name]
        assert {slot.trump_mode for slot in slots} == set(TRUMP_MODES)
        select = [slot for slot in slots if slot.split == "select"]
        left = [slot for slot in select
                if slot.select_subfold == SELECT_SUBFOLDS[0]]
        right = [slot for slot in select
                 if slot.select_subfold == SELECT_SUBFOLDS[1]]
        assert [
            (slot.cell, slot.trump_rank, slot.trump_mode) for slot in left
        ] == [
            (slot.cell, slot.trump_rank, slot.trump_mode) for slot in right
        ]
        assert not ({slot.slot_sha256 for slot in left}
                    & {slot.slot_sha256 for slot in right})


def test_slot_derivation_and_attempt_identity_refuse_cross_binding() -> None:
    tier = TIER_SPECS[0]
    slots = build_population_slot_ledger(tier)
    forged = list(slots)
    forged[0] = PopulationSlotV2(
        **{**slots[0].__dict__, "trump_mode": "NT"})
    with pytest.raises(WorldAfterstateV2ProtocolError,
                       match="slot derivation"):
        validate_population_slot_ledger(forged, tier=tier)
    namespace = _sha("population")
    first = attempted_deal_identity(namespace, slots[0], 0)
    assert first == attempted_deal_identity(namespace, slots[0], 0)
    assert first["deal_sha256"] != attempted_deal_identity(
        namespace, slots[0], 1)["deal_sha256"]
    assert first["deal_sha256"] != attempted_deal_identity(
        namespace, slots[1], 0)["deal_sha256"]


def test_state_selection_is_one_per_deal_and_smallest_hash() -> None:
    slots = build_population_slot_ledger(TIER_SPECS[0])[:2]
    required_slots = {
        _sha("deal-0"): slots[0],
        _sha("deal-1"): slots[1],
    }
    values = [
        _state(0, slots[0], state_suffix="b"),
        _state(0, slots[0], state_suffix="a"),
        _state(0, slots[0], cell=P0_CELLS[1],
               state_suffix="wrong-cell"),
        _state(1, slots[1], state_suffix="a"),
    ]
    selected = select_one_state_per_deal(
        values, required_slots=required_slots)
    assert len(selected) == 2
    assert selected[0].state_sha256 == min(
        value.state_sha256 for value in values
        if value.deal_sha256 == selected[0].deal_sha256
        and value.cell == required_slots[selected[0].deal_sha256].cell)
    assert len({value.deal_sha256 for value in selected}) == 2


def test_state_selection_refuses_missing_cell_and_non_natural_audit() -> None:
    deal = _sha("deal-0")
    slot = build_population_slot_ledger(TIER_SPECS[0])[0]
    with pytest.raises(WorldAfterstateV2ProtocolError,
                       match="no eligible state"):
        select_one_state_per_deal(
            [_state(0, slot, cell=P0_CELLS[1])],
            required_slots={deal: slot})
    value = StateCandidateV2(
        deal_sha256=deal, slot_sha256=slot.slot_sha256,
        state_sha256=_sha("bad"), source="pt-luna",
        split="audit", phase="early", position="lead", role="attacker",
        trump_rank="2", trump_mode="S", mechanics_surfaces=(),
        legal_candidate_count=2)
    with pytest.raises(WorldAfterstateV2ProtocolError,
                       match="must be natural"):
        value.validate()


def test_state_selection_refuses_slot_source_rank_and_subfold_drift() -> None:
    slots = [slot for slot in build_population_slot_ledger(TIER_SPECS[1])
             if slot.group == "diverse-fit-luna"]
    slot = slots[0]
    deal = _sha("deal-0")
    value = _state(0, slot)
    forged = StateCandidateV2(
        **{**value.__dict__, "trump_mode": "NT"
           if slot.trump_mode != "NT" else "S"})
    with pytest.raises(WorldAfterstateV2ProtocolError,
                       match="slot binding"):
        select_one_state_per_deal(
            [forged], required_slots={deal: slot})
    other_slot = slots[1]
    with pytest.raises(WorldAfterstateV2ProtocolError,
                       match="slot binding"):
        select_one_state_per_deal(
            [value], required_slots={deal: other_slot})


def test_p0_requires_96_independent_deals_and_eight_per_cell() -> None:
    natural_slots = [
        slot for slot in build_population_slot_ledger(TIER_SPECS[0])
        if slot.group == "natural-fit"
    ]
    values = [_state(index, slot) for index, slot in enumerate(natural_slots)]
    selected = select_p0_population(values, tier=TIER_SPECS[0])
    validate_p0_population(
        selected, natural_fit_population=values, tier=TIER_SPECS[0])
    forged = list(selected)
    forged[-1] = _state(999, natural_slots[-1], cell=P0_CELLS[0],
                         state_suffix="moved")
    with pytest.raises(WorldAfterstateV2ProtocolError,
                       match="canonical P0 subset"):
        validate_p0_population(forged, natural_fit_population=values,
                               tier=TIER_SPECS[0])


def test_p0_canonical_subset_refuses_balanced_later_deal_alternative() -> None:
    tier = TIER_SPECS[2]
    natural_slots = [
        slot for slot in build_population_slot_ledger(tier)
        if slot.group == "natural-fit"
    ]
    values = [_state(index, slot) for index, slot in enumerate(natural_slots)]
    selected = select_p0_population(values, tier=tier)
    by_cell = {cell: [] for cell in P0_CELLS}
    for state in values:
        by_cell[state.cell].append(state)
    alternative = tuple(
        state for cell in P0_CELLS
        for state in sorted(by_cell[cell], key=lambda item: item.deal_sha256)[8:16])
    assert len(alternative) == 96
    with pytest.raises(WorldAfterstateV2ProtocolError,
                       match="canonical P0 subset mismatch"):
        validate_p0_population(
            alternative, natural_fit_population=values, tier=tier)


def test_capacity_selects_largest_eligible_tier_without_outcomes() -> None:
    receipts = [
        _receipt("D256"), _receipt("D512"),
        _receipt("D1024", exact_source_supply=False),
    ]
    assert choose_capacity_tier(receipts).name == "D512"
    receipts[-1] = _receipt(
        "D1024", label_wall_seconds=20_000,
        label_cpu_seconds=300_000)
    # The 3h/48 CPUh label gate is the D256 entry condition. A larger tier is
    # governed by the complete-DAG six-hour limit.
    assert choose_capacity_tier(receipts).name == "D1024"


@pytest.mark.parametrize(
    ("change", "value"),
    [
        ("all_core_gate_passed", False),
        ("complete_dag_wall_seconds", 21_601),
        ("peak_memory_bytes", 25_501),
        ("composed_artifact_bytes", 75_001),
    ],
)
def test_capacity_boundary_can_make_larger_tier_ineligible(
        change: str, value: object) -> None:
    receipts = [_receipt("D256"), _receipt("D512"),
                _receipt("D1024", **{change: value})]
    assert choose_capacity_tier(receipts).name == "D512"


def test_capacity_refuses_opened_outcomes_and_failed_d256() -> None:
    with pytest.raises(WorldAfterstateV2ProtocolError,
                       match="opened outcomes"):
        choose_capacity_tier([
            _receipt("D256"), _receipt("D512", outcomes_opened=True),
            _receipt("D1024", exact_source_supply=False),
        ])
    with pytest.raises(WorldAfterstateV2ProtocolError,
                       match="D256 capacity minimum"):
        choose_capacity_tier([
            _receipt("D256", label_wall_seconds=10_801),
            _receipt("D512"), _receipt("D1024"),
        ])
