from __future__ import annotations

import copy
import hashlib
from dataclasses import replace

import pytest

from shengji.rl.world_afterstate_v2_label import (
    AUTHORITY, FLOOR_STOP, MECHANICS_STOP, P0_CELLS, STATISTICAL_STOP,
    ContinuationOutcomeV2, WorldAfterstateV2LabelError,
    _candidate_set_sha256, evaluate_precision_label, validate_precision_label,
)
from shengji.rl.world_afterstate_v2_protocol import (
    TIER_SPECS, PopulationSlotV2, StateCandidateV2,
    build_population_slot_ledger, select_p0_population,
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def _population(*, candidate_count: int = 3, incumbent_tie: bool = False,
                split: str = "fit") -> list[ContinuationOutcomeV2]:
    required = _required_slots()
    rows = []
    for deal, state in enumerate(_selected_population()):
        deal_sha = state.deal_sha256
        slot = required[deal_sha]
        assert slot.cell is not None
        phase, position, role = slot.cell
        state_sha = state.state_sha256
        successors = tuple(
            _sha(f"successor-{deal}-{candidate}")
            for candidate in range(candidate_count))
        candidate_set_sha = _candidate_set_sha256(state_sha, successors)
        for replica in range(8):
            for candidate in range(candidate_count):
                # Keep every deal's mean fixed while varying sibling vectors
                # across replicas, so the power arithmetic and correlation
                # gate are both independently exercised.
                multiplier = candidate
                if candidate == 2 and replica >= 4:
                    multiplier = 4
                category = 100 + candidate * multiplier
                if incumbent_tie and candidate == 1:
                    category = 100
                rows.append(ContinuationOutcomeV2(
                    deal_sha256=deal_sha, slot_sha256=slot.slot_sha256,
                    state_sha256=state_sha,
                    candidate_set_sha256=candidate_set_sha,
                    source="natural", split=split, role=role, phase=phase,
                    position=position, trump_rank=slot.trump_rank,
                    trump_mode=slot.trump_mode,
                    points_bucket="40-79", candidate_index=candidate,
                    protected_incumbent=candidate == 0,
                    successor_sha256=successors[candidate],
                    continuation_sha256=_sha(
                        f"continuation-{deal}-{replica}"),
                    replica=replica, signed_level_category=category))
    return rows


def _required_slots() -> dict[str, PopulationSlotV2]:
    return {state.deal_sha256: next(
        slot for slot in build_population_slot_ledger(TIER_SPECS[0])
        if slot.slot_sha256 == state.slot_sha256)
            for state in _selected_population()}


def _natural_population() -> list[StateCandidateV2]:
    slots = [slot for slot in build_population_slot_ledger(TIER_SPECS[0])
             if slot.group == "natural-fit"]
    return [StateCandidateV2(
        deal_sha256=_sha(f"deal-{index}"), slot_sha256=slot.slot_sha256,
        state_sha256=_sha(f"state-{index}"), source="natural", split="fit",
        phase=slot.phase, position=slot.position, role=slot.role,
        trump_rank=slot.trump_rank, trump_mode=slot.trump_mode,
        mechanics_surfaces=(), legal_candidate_count=2)
            for index, slot in enumerate(slots)]


def _selected_population() -> tuple[StateCandidateV2, ...]:
    return select_p0_population(_natural_population(), tier=TIER_SPECS[0])


def _evaluate(rows: list[ContinuationOutcomeV2], **kwargs):
    return evaluate_precision_label(
        rows, required_slots=_required_slots(),
        natural_fit_population=_natural_population(), tier=TIER_SPECS[0],
        **kwargs)


def test_p0_crossfit_uses_complete_candidate_mean_and_closed_authority():
    result = _evaluate(_population(), bootstrap_replicates=100)
    validate_precision_label(result)
    assert result["decision"] == "PASS_P0_PRECISION"
    assert result["deal_count"] == result["state_count"] == 96
    assert result["raw_outcome_count"] == 96 * 3 * 8
    assert result["candidate_pair_count"] == 96 * 2
    assert result["directional_candidate_mean_microlevels"] == {
        "0-to-1": 5_000_000, "1-to-0": 2_333_333}
    assert result["chosen_minus_incumbent_microlevels"] == {
        "0-to-1": 8_000_000, "1-to-0": 4_000_000}
    assert result["cell_counts"] and set(result["cell_counts"].values()) == {8}
    assert "audit" not in result and "calibration" not in result
    assert set(result["r2"]) == {
        "action_agreement_ppm", "return_mean_error_microlevels",
        "intraclass_correlation_ppm"}
    assert result["incumbent_relative_bessel_s_microlevels"] == 0
    assert result["authority"] == AUTHORITY and not any(AUTHORITY.values())


def test_tie_to_incumbent_is_deterministic_and_zero_signal_stops():
    result = _evaluate(
        _population(candidate_count=2, incumbent_tie=True),
        bootstrap_replicates=100)
    assert result["decision"] == STATISTICAL_STOP
    assert result["directional_candidate_mean_microlevels"] == {
        "0-to-1": 0, "1-to-0": 0}


def test_directional_candidate_mean_gate_uses_exact_fraction_sign():
    rows = _population(candidate_count=2)
    rows = [replace(row, signed_level_category=(101
        if row.replica < 4 else 99)) if row.candidate_index == 1 else row
            for row in rows]
    result = _evaluate(rows, bootstrap_replicates=100)
    assert result["directional_candidate_mean_microlevels"]["0-to-1"] < 0
    assert result["decision"] == STATISTICAL_STOP


def test_candidate_singleton_is_refused_before_sign_dose():
    rows = [row for row in _population(candidate_count=2)
            if row.candidate_index == 0]
    with pytest.raises(WorldAfterstateV2LabelError,
                       match="candidate set"):
        _evaluate(rows, bootstrap_replicates=100)


def test_statistical_gates_include_nonzero_sign_and_correlation():
    rows = _population(candidate_count=2)
    # Alternate the advantage in the second half on a small subset, causing
    # the cross-half sign witness and correlation lower-bound path to fail.
    first_half_deals = {_sha(f"deal-{deal}") for deal in range(48)}
    for index, row in enumerate(rows):
        if (row.candidate_index == 1 and row.replica >= 4
                and row.deal_sha256 in first_half_deals):
            rows[index] = replace(row, signed_level_category=98)
    result = _evaluate(rows, bootstrap_replicates=100)
    assert result["decision"] == STATISTICAL_STOP
    assert result["sibling_advantage_correlation_bootstrap_lower_ppm"] <= 0


def test_mechanics_failure_is_separate_and_has_precedence():
    result = _evaluate(
        _population(), bootstrap_replicates=100, mechanics_passed=False)
    assert result["mechanics_passed"] is False
    assert result["statistical_gates_passed"] is True
    assert result["decision"] == MECHANICS_STOP


def test_exact_worthwhile_floor_is_a_separate_route_from_statistical_gates():
    rows = _population()
    for i, row in enumerate(rows):
        if row.candidate_index == 1:
            rows[i] = replace(row, signed_level_category=97)
        elif row.candidate_index == 2:
            rows[i] = replace(row, signed_level_category=(101
                if row.replica < 4 else 99))
    result = _evaluate(rows, bootstrap_replicates=100)
    assert result["statistical_gates_passed"] is True
    assert result["worthwhile_floor_passed"] is False
    assert result["combined_chosen_minus_incumbent_microlevels"] == -500_000
    assert result["decision"] == FLOOR_STOP


def test_icc_one_one_uses_correct_degrees_of_freedom():
    from shengji.rl.world_afterstate_v2_label import _icc
    assert _icc(((0, 1), (2, 3), (4, 5))) == 882_352


@pytest.mark.parametrize("mutation", [
    lambda rows: rows[:-1],
    lambda rows: [replace(row, split="select") for row in rows],
    lambda rows: [replace(rows[0], deal_sha256=rows[24].deal_sha256)
                  ] + rows[1:],
    lambda rows: [replace(rows[-1], candidate_index=3) if i == len(rows) - 1
                  else row for i, row in enumerate(rows)],
    lambda rows: [replace(row, successor_sha256=_sha("foreign"))
                  if row.candidate_index == 1 and row.replica == 7
                  else row for row in rows],
    lambda rows: [replace(row, continuation_sha256=_sha("foreign-crn"))
                  if row.candidate_index == 1 and row.replica == 7
                  else row for row in rows],
    lambda rows: [replace(rows[0], slot_sha256=_sha("foreign-slot"))]
                 + rows[1:],
])
def test_population_contract_refuses_identity_or_split_mutations(mutation):
    with pytest.raises(WorldAfterstateV2LabelError):
        _evaluate(mutation(_population()), bootstrap_replicates=100)


def test_result_schema_is_closed_and_hash_bound():
    result = _evaluate(_population(), bootstrap_replicates=100)
    forged = copy.deepcopy(result)
    forged["statistical_gates_passed"] = False
    with pytest.raises(WorldAfterstateV2LabelError):
        validate_precision_label(forged)
    forged = copy.deepcopy(result)
    forged["worthwhile_floor_passed"] = False
    with pytest.raises(WorldAfterstateV2LabelError):
        validate_precision_label(forged)
    forged = copy.deepcopy(result)
    forged["unexpected"] = True
    with pytest.raises(WorldAfterstateV2LabelError):
        validate_precision_label(forged)


def test_required_slot_population_is_unique_and_exactly_cross_bound():
    rows = _population()
    slots = _required_slots()
    deals = sorted(slots)
    slots[deals[1]] = slots[deals[0]]
    with pytest.raises(WorldAfterstateV2LabelError,
                       match="canonical P0 subset"):
        evaluate_precision_label(
            rows, required_slots=slots,
            natural_fit_population=_natural_population(), tier=TIER_SPECS[0],
            bootstrap_replicates=100)


def test_precision_evaluation_refuses_caller_asserted_96_without_full_population():
    with pytest.raises(WorldAfterstateV2LabelError,
                       match="canonical P0 subset"):
        evaluate_precision_label(
            _population(), required_slots=_required_slots(),
            bootstrap_replicates=100)


def test_exact_gate_fraction_witness_cannot_drift_from_published_projection():
    result = _evaluate(_population(), bootstrap_replicates=100)
    forged = copy.deepcopy(result)
    forged["gate_fractions"]["direction_0_to_1"]["numerator"] += 1
    with pytest.raises(WorldAfterstateV2LabelError,
                       match="fraction|reconstruction"):
        validate_precision_label(forged)
