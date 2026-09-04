"""Deterministic stratified terminal reduction tests."""

from __future__ import annotations

import shengji.rl.belief_policy_statistics as STATISTICS
from shengji.rl.belief_policy_protocol import (
    POLICY_RANKS,
    SELECTED_ROUNDS_PER_RANK,
)
from shengji.rl.belief_policy_search import (
    ARM_IDS,
    CONTROL_ARM,
    PRIMARY_ARM,
    PRODUCTION_ARM,
)


def _row(rank: str, ordinal: int, *, production: int,
         primary: int, control: int):
    values = {
        PRODUCTION_ARM: production,
        PRIMARY_ARM: primary,
        CONTROL_ARM: control,
    }
    return {
        "coordinate": {
            "trump_rank": rank,
            "rank_ordinal": ordinal,
            "round_seed": POLICY_RANKS.index(rank) * 100 + ordinal,
        },
        "decision_index": ordinal * 10,
        "actor": {
            "actor_is_attacker": ordinal % 2 == 0,
            "current_trick": {"plays": [] if ordinal % 2 == 0 else [{}]},
        },
        "models": {
            "primary": {"member_model_sha256s": [str(i) * 64
                                                   for i in range(1, 9)]},
            "control": {"member_model_sha256s": [str(i) * 64
                                                   for i in range(1, 9)]},
        },
        "true_world": {"arms": [{
            "arm_id": arm_id,
            "true_world_value": values[arm_id],
            "true_world_oracle_agreement": arm_id == PRIMARY_ARM,
            "final_action_flipped_vs_production": arm_id != PRODUCTION_ARM,
        } for arm_id in ARM_IDS]},
        "nominations": [{"challenger_index": index}
                        for index, _ in enumerate(ARM_IDS)],
        "proposal_support": {"true_world_compatible": True},
        "weights": {
            **{
                f"{fold}_{arm}": {
                    "ess_ppb": 60_000_000_000,
                    "max_weight_ppb": 20_000_000,
                    "untempered_ess_ppb": 50_000_000_000,
                    "untempered_max_weight_ppb": 30_000_000,
                    "alpha_ppb": (1_000_000_000
                                  if arm == "primary" else 500_000_000),
                }
                for fold in ("selection", "report")
                for arm in ("primary", "control")
            },
        },
        "work": {
            "total_nanoseconds": 10,
            "total_cpu_nanoseconds": 8,
            "inference_nanoseconds": 1,
            "inference_cpu_nanoseconds": 1,
            "sampling_nanoseconds": 2,
            "sampling_cpu_nanoseconds": 2,
            "rollout_nanoseconds": 7,
            "rollout_cpu_nanoseconds": 5,
        },
        "folds": {
            "proposal_reference": {"attempts": 256,
                                   "accepted_world_count": 256},
            "selection": {"attempts": 30,
                          "accepted_world_count": 30},
            "report": {"attempts": 300,
                       "accepted_world_count": 300},
        },
    }


def _population(*, production: int, primary: int, control: int):
    rows = tuple(_row(
        rank, ordinal, production=production,
        primary=primary, control=control)
        for rank in POLICY_RANKS
        for ordinal in range(SELECTED_ROUNDS_PER_RANK))
    hashes = tuple(f"{index + 1:064x}" for index in range(len(rows)))
    return rows, hashes


def test_complete_population_routes_on_both_paired_lower_bounds(monkeypatch):
    monkeypatch.setattr(STATISTICS, "validate_policy_root_result",
                        lambda _row: None)
    rows, hashes = _population(production=0, primary=3, control=1)
    result = STATISTICS.reduce_policy_root_results(
        rows, shard_sha256s=hashes)
    assert result["route"] == STATISTICS.ROUTE_SIGNAL
    assert result["primary_minus_production"] == {
        "point_nanopoints": 3_000_000_000,
        "bootstrap_lower_nanopoints": 3_000_000_000,
        "bootstrap_upper_nanopoints": 3_000_000_000,
        "bootstrap_replicates": 10_000,
    }
    assert result["primary_minus_control"][
        "bootstrap_lower_nanopoints"] == 2_000_000_000
    assert result["final_action_flip_dose_ppb"][PRIMARY_ARM] \
        == 1_000_000_000
    assert result["r4_test_opened"] is False
    assert result["secondary_strata"]["trump_rank"]["2"][
        "round_count"] == 8
    assert result["legality"] == {
        "validated_legal_world_count": (256 + 30 + 300) * 104,
        "illegal_world_count": 0,
        "all_world_folds_exact_and_validated": True,
    }
    assert result["weighting"]["report"][PRIMARY_ARM][
        "mean_untempered_ess_ppb"] == 50_000_000_000
    assert result["runtime"]["total_root_cpu_nanoseconds"] == 8 * 104


def test_primary_gain_not_separated_from_control_is_not_signal(monkeypatch):
    monkeypatch.setattr(STATISTICS, "validate_policy_root_result",
                        lambda _row: None)
    rows, hashes = _population(production=0, primary=2, control=2)
    result = STATISTICS.reduce_policy_root_results(
        rows, shard_sha256s=hashes)
    assert result["route"] == STATISTICS.ROUTE_CONTROL
    rows, hashes = _population(production=2, primary=1, control=0)
    result = STATISTICS.reduce_policy_root_results(
        rows, shard_sha256s=hashes)
    assert result["route"] == STATISTICS.ROUTE_NONE


def test_positive_signal_cannot_route_through_proposal_support_gap(monkeypatch):
    monkeypatch.setattr(STATISTICS, "validate_policy_root_result",
                        lambda _row: None)
    rows, hashes = _population(production=0, primary=3, control=1)
    rows[0]["proposal_support"]["true_world_compatible"] = False
    result = STATISTICS.reduce_policy_root_results(
        rows, shard_sha256s=hashes)
    assert result["route"] == STATISTICS.ROUTE_SUPPORT
    assert result["proposal_support_miss_count"] == 1
