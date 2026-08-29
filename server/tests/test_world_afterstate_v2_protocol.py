from __future__ import annotations

import hashlib

import pytest

from shengji.rl.world_afterstate_v2_protocol import (
    AUTHORITY, P0_CELLS, TIER_SPECS, CapacityTierReceiptV2,
    StateCandidateV2, WorldAfterstateV2ProtocolError, choose_capacity_tier,
    protocol_payload, select_one_state_per_deal, validate_p0_population,
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def _state(index: int, cell: tuple[str, str, str], *,
           state_suffix: str = "a") -> StateCandidateV2:
    return StateCandidateV2(
        deal_sha256=_sha(f"deal-{index}"),
        state_sha256=_sha(f"state-{index}-{state_suffix}"),
        source="natural", split="fit", phase=cell[0], position=cell[1],
        role=cell[2], legal_candidate_count=2)


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


def test_state_selection_is_one_per_deal_and_smallest_hash() -> None:
    cells = {
        _sha("deal-0"): P0_CELLS[0],
        _sha("deal-1"): P0_CELLS[1],
    }
    values = [
        _state(0, P0_CELLS[0], state_suffix="b"),
        _state(0, P0_CELLS[0], state_suffix="a"),
        _state(0, P0_CELLS[1], state_suffix="wrong-cell"),
        _state(1, P0_CELLS[1], state_suffix="a"),
    ]
    selected = select_one_state_per_deal(values, required_cells=cells)
    assert len(selected) == 2
    assert selected[0].state_sha256 == min(
        value.state_sha256 for value in values
        if value.deal_sha256 == selected[0].deal_sha256
        and value.cell == cells[selected[0].deal_sha256])
    assert len({value.deal_sha256 for value in selected}) == 2


def test_state_selection_refuses_missing_cell_and_non_natural_audit() -> None:
    deal = _sha("deal-0")
    with pytest.raises(WorldAfterstateV2ProtocolError,
                       match="no eligible state"):
        select_one_state_per_deal(
            [_state(0, P0_CELLS[1])], required_cells={deal: P0_CELLS[0]})
    value = StateCandidateV2(
        deal_sha256=deal, state_sha256=_sha("bad"), source="diverse",
        split="audit", phase="early", position="lead", role="attacker",
        legal_candidate_count=2)
    with pytest.raises(WorldAfterstateV2ProtocolError,
                       match="must be natural"):
        value.validate()


def test_p0_requires_96_independent_deals_and_eight_per_cell() -> None:
    values = [
        _state(cell_index * 8 + offset, cell)
        for cell_index, cell in enumerate(P0_CELLS)
        for offset in range(8)
    ]
    validate_p0_population(values)
    forged = list(values)
    forged[-1] = _state(95, P0_CELLS[0], state_suffix="moved")
    with pytest.raises(WorldAfterstateV2ProtocolError,
                       match="cell balance"):
        validate_p0_population(forged)


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
