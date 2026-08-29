import copy
import hashlib

import pytest

from shengji.rl.world_afterstate_evaluation import EvaluationOutcomeV0
from shengji.rl.world_afterstate_v1 import (
    AUTHORITY, AdvantagePairV1, WorldAfterstateV1Error,
    build_advantage_pairs, evaluate_label_ceiling, validate_label_ceiling)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def _outcome(
        *, state: int, candidate: int, replicate: int, category: int,
        fold: str = "train") -> EvaluationOutcomeV0:
    return EvaluationOutcomeV0(
        deal_group_sha256=_digest(f"deal-{state}"),
        state_group_id=_digest(f"state-{state}"),
        source="production-policy", fold=fold,
        root_role="attacker", play_phase="middle", position="lead",
        trump_rank="7", trump_mode="H", points_bucket="40-79",
        candidate_index=candidate, protected_incumbent=candidate == 0,
        successor_sha256=_digest(f"successor-{state}-{candidate}"),
        replicate=replicate, signed_level_category=category)


def _population(*, contradictory: bool = False):
    rows = []
    for state in range(24):
        fold = "train" if state < 20 else "calibration"
        for replicate in (0, 1):
            rows.append(_outcome(
                state=state, candidate=0, replicate=replicate,
                category=100, fold=fold))
            category = 102
            if contradictory and replicate == 1:
                category = 98
            rows.append(_outcome(
                state=state, candidate=1, replicate=replicate,
                category=category, fold=fold))
    return rows


def test_pairs_are_exact_candidate_minus_incumbent_and_order_stable():
    outcomes = _population()
    forward = build_advantage_pairs(outcomes)
    reverse = build_advantage_pairs(list(reversed(outcomes)))
    assert forward == reverse
    assert len(forward) == 48
    assert {pair.advantage_levels for pair in forward} == {2}
    assert {pair.fold for pair in forward} == {"train", "calibration"}
    assert all(pair.candidate_index == 1 for pair in forward)


def test_label_ceiling_passes_only_for_reproducible_action_signal():
    result = evaluate_label_ceiling(
        build_advantage_pairs(_population()), bootstrap_replicates=200)
    validate_label_ceiling(result)
    assert result["passed"] is True
    assert result["crossfit_direction_mean_microlevels"] == {
        "0-to-1": 2_000_000, "1-to-0": 2_000_000}
    assert result["combined_crossfit_microlevels"] == {
        "mean": 2_000_000,
        "bootstrap_lower": 2_000_000,
        "bootstrap_upper": 2_000_000,
    }
    assert result["selection_dose_ppm"] == 1_000_000
    assert result["replicate_advantage_correlation_ppm"] == 0
    assert result["replicate_sign_agreement_ppm"] == 1_000_000
    assert set(result["authority"].values()) == {False}
    assert result["authority"] == AUTHORITY


def test_contradictory_replicates_stop_before_training():
    result = evaluate_label_ceiling(
        build_advantage_pairs(_population(contradictory=True)),
        bootstrap_replicates=200)
    validate_label_ceiling(result)
    assert result["passed"] is False
    assert result["crossfit_direction_mean_microlevels"] == {
        "0-to-1": -2_000_000, "1-to-0": 0}
    assert result["combined_crossfit_microlevels"]["bootstrap_upper"] < 0
    # Both repetitions are constant across states, so Pearson correlation is
    # undefined and the contract reports zero; the sign witness still proves
    # complete disagreement.
    assert result["replicate_advantage_correlation_ppm"] == 0
    assert result["replicate_sign_agreement_ppm"] == 0


def test_pair_builder_refuses_missing_replicate_before_derivation():
    outcomes = _population()
    outcomes.pop()
    with pytest.raises(
            WorldAfterstateV1Error,
            match="advantage sibling replicate population drift"):
        build_advantage_pairs(outcomes)


def test_pair_builder_refuses_cross_candidate_state_binding():
    outcomes = _population()
    donor = outcomes[-1]
    outcomes[-1] = EvaluationOutcomeV0(
        **{**donor.__dict__, "source": "reviewed-pt-sol0"})
    with pytest.raises(
            WorldAfterstateV1Error,
            match="advantage cross-candidate binding drift"):
        build_advantage_pairs(outcomes)


def test_pair_label_mutation_is_refused_exactly():
    pair = build_advantage_pairs(_population())[0]
    bad = AdvantagePairV1(**{**pair.__dict__, "advantage_levels": 3})
    with pytest.raises(
            WorldAfterstateV1Error, match="advantage pair label drift"):
        bad.validate()


def test_label_ceiling_refuses_dropped_candidate_row():
    pairs = list(build_advantage_pairs(_population()))
    pairs.pop()
    with pytest.raises(
            WorldAfterstateV1Error,
            match="label-ceiling replicate population drift"):
        evaluate_label_ceiling(pairs, bootstrap_replicates=200)


def test_label_ceiling_refuses_cross_replicate_successor_drift():
    pairs = list(build_advantage_pairs(_population()))
    donor = pairs[1]
    pairs[1] = AdvantagePairV1(**{
        **donor.__dict__,
        "candidate_successor_sha256": _digest("foreign-successor"),
    })
    with pytest.raises(
            WorldAfterstateV1Error,
            match="label-ceiling candidate successor binding drift"):
        evaluate_label_ceiling(pairs, bootstrap_replicates=200)


def test_result_gate_and_hash_mutations_are_refused():
    result = evaluate_label_ceiling(
        build_advantage_pairs(_population()), bootstrap_replicates=200)
    gate = copy.deepcopy(result)
    gate["passed"] = False
    with pytest.raises(WorldAfterstateV1Error, match="label-ceiling gate drift"):
        validate_label_ceiling(gate)
    digest = copy.deepcopy(result)
    digest["result_sha256"] = "0" * 64
    with pytest.raises(
            WorldAfterstateV1Error,
            match="label-ceiling result reconstruction drift"):
        validate_label_ceiling(digest)
    census = copy.deepcopy(result)
    census["state_census"]["source"][0][1] -= 1
    with pytest.raises(
            WorldAfterstateV1Error, match="label-ceiling census drift"):
        validate_label_ceiling(census)
