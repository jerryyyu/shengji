from __future__ import annotations

import copy
import math

import pytest

from shengji.rl import stage_c_model as MODEL


def _action(index: int, utilities: list[float]) -> dict:
    return {
        "logical_index": index,
        "candidate_index": index,
        "signed_level_utility": utilities,
    }


def _state(*, recipe: str = "ordinary_anchor", split: str = "DESIGN",
           surface: str = "play", state_id: str = "s0") -> dict:
    return {
        "state_id": state_id,
        "split": split,
        "surface_type": surface,
        "stratum": recipe,
        "seat": 0,
        "candidates": [
            {"cards": ["C2"], "sources": ["live_production_ballot"]},
            {"cards": ["C3"], "sources": ["v11pair_top_proposal"]},
            {"cards": ["C4"], "sources": ["same_budget_random_diversifier"]},
        ],
    }


def _row(*, recipe: str = "ordinary_anchor", split: str = "DESIGN",
         surface: str = "play", state_id: str = "s0") -> dict:
    base = [
        [-1.5, -0.5, 0.5, 1.5] * 64,
        [0.5, 0.5, 1.5, 1.5] * 64,
        [-1.5, -1.5, -0.5, -0.5] * 64,
    ]
    selection = {
        "candidate_indices": [0, 1, 2],
        "actions": [_action(index, values)
                    for index, values in enumerate(base)],
    }
    report = copy.deepcopy(selection)
    if recipe == "hard_tail":
        selection = {
            "candidate_indices": [0, 1, 2],
            "actions": [_action(index, values[:64])
                        for index, values in enumerate(base)],
        }
        report = {
            "candidate_indices": [0, 1],
            "actions": [
                _action(0, [-0.5] * 300),
                {**_action(1, [1.5] * 300), "logical_index": 1},
            ],
        }
    return {
        "status": "COMPLETE",
        "state_id": state_id,
        "split": split,
        "surface_type": surface,
        "stratum": recipe,
        "candidate_count": 3,
        "recipe": recipe,
        "selection": selection,
        "report": report,
        "label_action": {"index": 1},
    }


def _example(index: int, *, surface: str = "play",
             stratum: str = "ordinary_anchor") -> dict:
    target = MODEL.build_target(
        _state(surface=surface, state_id=f"{surface}:{index}"),
        _row(surface=surface, state_id=f"{surface}:{index}"))
    return {
        "schema": MODEL.SCHEMA,
        "state_id": f"{surface}:{index}",
        "split": "DESIGN",
        "surface_type": surface,
        "stratum": stratum,
        "obs": [0.0] * MODEL.OBS_DIM,
        "actions": [[0.0] * MODEL.ACT_DIM for _ in range(3)],
        "target": target,
    }


def test_utility_bins_and_soft_distribution_are_exact() -> None:
    values = [-3.5, -3.5, 0.5, 3.5]
    distribution = MODEL.utility_distribution(values)
    assert distribution == [0.5, 0.0, 0.0, 0.0, 0.25, 0.0, 0.0, 0.25]
    assert MODEL.distribution_mean(distribution) == pytest.approx(-0.75)
    with pytest.raises(MODEL.StageCModelError, match="outside"):
        MODEL.utility_distribution([0.0])


def test_paired_preference_uses_common_world_wins_and_half_ties() -> None:
    assert MODEL.paired_preference(
        [-1.5, 0.5, 1.5, 1.5],
        [-1.5, -0.5, 1.5, 0.5]) == pytest.approx(0.75)
    with pytest.raises(MODEL.StageCModelError, match="geometry"):
        MODEL.paired_preference([0.5], [0.5, 1.5])


def test_ordinary_target_uses_all_candidate_report_fold() -> None:
    target = MODEL.build_target(_state(), _row())
    assert target["all_candidate_fold"] == "report"
    assert target["all_candidate_worlds"] == 256
    assert target["deeper_report_pair"] is None
    assert target["pairwise_preference"][1][0] == pytest.approx(0.875)
    assert target["ranking_mean_signed_level_utility"] == pytest.approx(
        [0.0, 1.0, -1.0])
    assert target["outcome_mean_signed_level_utility"] == pytest.approx(
        [0.0, 1.0, -1.0])
    assert target["frozen_label_index"] == 1
    assert target["target_sha256"] == MODEL.sha256_bytes(
        MODEL.canonical_json({key: value for key, value in target.items()
                              if key != "target_sha256"}))


def test_hard_tail_target_replaces_only_deeper_zero_winner_evidence() -> None:
    state = _state(recipe="hard_tail")
    row = _row(recipe="hard_tail")
    target = MODEL.build_target(state, row)
    assert target["all_candidate_fold"] == "selection"
    assert target["deeper_report_pair"] == {
        "candidate_indices": [0, 1],
        "worlds": 300,
        "replaced_all_candidate_pair": True,
    }
    assert target["pairwise_preference"][1][0] == 1.0
    assert target["pairwise_weight"][1][0] == pytest.approx(300 / 64)
    # Candidate 2 still comes from the all-candidate selection fold.
    assert target["ranking_mean_signed_level_utility"] == pytest.approx(
        [0.0, 1.0, -1.0])
    assert target["outcome_mean_signed_level_utility"][0] == pytest.approx(
        -0.5)
    assert target["outcome_mean_signed_level_utility"][1] == pytest.approx(1.5)
    assert target["outcome_mean_signed_level_utility"][2] == pytest.approx(-1.0)


def test_hard_tail_duplicate_candidate_zero_remains_identifiable() -> None:
    state = _state(recipe="hard_tail")
    row = _row(recipe="hard_tail")
    row["report"]["candidate_indices"] = [0, 0]
    row["report"]["actions"][1]["candidate_index"] = 0
    row["label_action"]["index"] = 0
    target = MODEL.build_target(state, row)
    assert target["deeper_report_pair"]["replaced_all_candidate_pair"] is False
    assert target["pairwise_weight"][0][0] == 0.0


def test_target_rejects_continuous_or_reordered_teacher_data() -> None:
    row = _row()
    row["report"]["actions"][0]["signed_level_utility"][0] = 0.0
    with pytest.raises(MODEL.StageCModelError, match="outside"):
        MODEL.build_target(_state(), row)
    row = _row()
    row["report"]["candidate_indices"] = [1, 0, 2]
    with pytest.raises(MODEL.StageCModelError, match="order"):
        MODEL.build_target(_state(), row)


def test_target_rejects_state_recipe_or_stratum_drift() -> None:
    row = _row()
    row["recipe"] = "hard_tail"
    with pytest.raises(MODEL.StageCModelError, match="state/recipe"):
        MODEL.build_target(_state(), row)


def test_target_rejects_world_budget_and_hard_label_drift() -> None:
    row = _row()
    row["report"]["actions"][0]["signed_level_utility"].pop()
    row["report"]["actions"][1]["signed_level_utility"].pop()
    row["report"]["actions"][2]["signed_level_utility"].pop()
    with pytest.raises(MODEL.StageCModelError, match="budget"):
        MODEL.build_target(_state(), row)
    row = _row(recipe="hard_tail")
    row["label_action"]["index"] = 2
    with pytest.raises(MODEL.StageCModelError, match="label/report"):
        MODEL.build_target(_state(recipe="hard_tail"), row)
    row = _row()
    row["stratum"] = "proposal_disagreement"
    with pytest.raises(MODEL.StageCModelError, match="identity"):
        MODEL.build_target(_state(), row)


def test_curve_subsets_are_nested_deterministic_and_stratum_preserving() -> None:
    examples = []
    for surface in MODEL.SURFACES:
        for stratum in ("ordinary_anchor", "proposal_disagreement"):
            examples.extend(_example(
                index + (100 if stratum != "ordinary_anchor" else 0),
                surface=surface, stratum=stratum) for index in range(8))
    quarter = MODEL.curve_subset(examples, 0.25)
    half = MODEL.curve_subset(examples, 0.5)
    full = MODEL.curve_subset(examples, 1.0)
    qids = {value["state_id"] for value in quarter}
    hids = {value["state_id"] for value in half}
    assert qids <= hids <= {value["state_id"] for value in full}
    assert len(quarter) == 8
    assert len(half) == 16
    assert MODEL.curve_subset(examples, 0.5) == half


@pytest.mark.skipif(MODEL.torch is None, reason="torch is optional")
def test_grouped_model_loss_is_finite_and_backpropagates() -> None:
    examples = [_example(0), _example(1)]
    batch = MODEL.collate_examples(examples)
    net = MODEL.StageCRankingOutcomeNet(hidden=32)
    losses = MODEL.stage_c_loss(net, batch)
    assert set(losses) == {"loss", "pairwise_bce", "label_ce", "outcome_ce"}
    assert all(MODEL.torch.isfinite(value) for value in losses.values())
    losses["loss"].backward()
    assert any(parameter.grad is not None for parameter in net.parameters())


def test_prediction_metrics_reward_better_ranking_and_calibration() -> None:
    example = _example(0)
    actual = example["target"]["outcome_distribution"]
    # A model softmax is strictly positive even when the empirical target has
    # empty bins.  Smooth the exact target by an immaterial epsilon to emulate
    # a perfectly calibrated finite-logit prediction.
    predicted = [[(probability + 1e-6) / (1.0 + 8e-6)
                  for probability in distribution]
                 for distribution in actual]
    metrics = MODEL.evaluate_predictions(
        [example], [[0.0, 2.0, -1.0]], [predicted],
        prior_distribution=[1 / 8] * 8)
    assert metrics["mean_teacher_regret"] == 0.0
    assert metrics["ranking_improvement_vs_candidate0"] > 0
    assert metrics["frozen_label_top1_agreement"] == 1.0
    assert metrics["outcome_nll_improvement_vs_prior"] > 0


def _selection_records(*, passing: bool) -> list[dict]:
    records = []
    for epoch in MODEL.EPOCH_GRID:
        for surface in MODEL.SURFACES:
            for seed in MODEL.TRAINING_SEEDS:
                good = passing and epoch == 8
                records.append({
                    "epoch": epoch, "surface": surface, "seed": seed,
                    "split": "CALIB", "curve_fraction": 1.0,
                    "metrics": {
                        "ranking_improvement_vs_candidate0": 0.2 if good else -0.1,
                        "outcome_nll_improvement_vs_prior": 0.1 if good else -0.1,
                        "mean_teacher_regret": 0.1 if good else 0.3,
                        "outcome_nll": 1.0 if good else 2.0,
                    },
                })
    return records


def test_calib_selects_one_epoch_for_all_eight_seeds_not_one_checkpoint() -> None:
    selected = MODEL.select_global_epoch(_selection_records(passing=True))
    assert selected["decision"] == \
        "FREEZE_EIGHT_SEED_ENSEMBLE_FOR_REPORT_REVIEW"
    assert selected["selected_epoch"] == 8
    assert selected["single_seed_selection"] is False
    assert selected["report_open_authorized"] is False

    rejected = MODEL.select_global_epoch(_selection_records(passing=False))
    assert rejected["decision"] == "SELECT_NONE"
    assert rejected["selected_epoch"] is None


def test_checkpoint_contract_keeps_play_and_bury_weights_separate() -> None:
    value = MODEL.checkpoint_contract(
        surface="bury", seed=41, epoch=8, curve_fraction=1.0,
        state_dict_sha256="a" * 64)
    assert value["play_and_bury_share_weights"] is False
    assert value["utility_bins"] == list(MODEL.UTILITY_BINS)
