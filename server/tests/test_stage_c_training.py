from __future__ import annotations

import copy

import pytest

from shengji.rl import stage_c_model as MODEL
from shengji.rl import stage_c_training as TRAIN


def _example(index: int, *, split: str = "DESIGN",
             surface: str = "play", stratum: str = "ordinary_anchor") -> dict:
    distributions = []
    ranking_means = []
    for candidate in range(3):
        values = [0.0] * len(MODEL.UTILITY_BINS)
        values[(index + candidate) % len(values)] = 1.0
        distributions.append(values)
        ranking_means.append(MODEL.distribution_mean(values))
    preference = [[0.5] * 3 for _ in range(3)]
    weights = [[0.0] * 3 for _ in range(3)]
    for left in range(3):
        for right in range(left + 1, 3):
            probability = 1.0 if ranking_means[left] > ranking_means[right] else 0.0
            preference[left][right] = probability
            preference[right][left] = 1.0 - probability
            weights[left][right] = weights[right][left] = 1.0
    state_id = f"{split.lower()}:{surface}:{index}"
    target = {
        "schema": MODEL.TARGET_SCHEMA,
        "state_id": state_id,
        "split": split,
        "surface_type": surface,
        "stratum": stratum,
        "recipe": "ordinary_anchor" if stratum == "ordinary_anchor" else "hard_tail",
        "candidate_count": 3,
        "all_candidate_fold": "report" if stratum == "ordinary_anchor" else "selection",
        "all_candidate_worlds": (MODEL.ORDINARY_WORLDS
                                  if stratum == "ordinary_anchor"
                                  else MODEL.HARD_SELECTION_WORLDS),
        "deeper_report_pair": None,
        "frozen_label_index": max(
            range(3), key=lambda value: (ranking_means[value], -value)),
        "pairwise_preference": preference,
        "pairwise_weight": weights,
        "outcome_distribution": distributions,
        "ranking_mean_signed_level_utility": ranking_means,
        "outcome_mean_signed_level_utility": ranking_means,
        "candidate0_relative_advantage": [
            value - ranking_means[0] for value in ranking_means],
        "candidate0_relative_weight": [0.0, 1.0, 1.0],
        "utility_bins": list(MODEL.UTILITY_BINS),
    }
    if stratum != "ordinary_anchor":
        target["deeper_report_pair"] = {
            "candidate_indices": [0, target["frozen_label_index"]],
            "worlds": MODEL.HARD_REPORT_WORLDS,
            "replaced_all_candidate_pair":
                target["frozen_label_index"] != 0,
        }
        challenger = target["frozen_label_index"]
        if challenger != 0:
            target["candidate0_relative_weight"][challenger] = \
                MODEL.HARD_REPORT_WORLDS / MODEL.HARD_SELECTION_WORLDS
    target["target_sha256"] = TRAIN._self_hash(target, "target_sha256")
    example = {
        "schema": MODEL.SCHEMA,
        "state_id": state_id,
        "split": split,
        "surface_type": surface,
        "stratum": stratum,
        "obs": [float((index + offset) % 7) / 7
                for offset in range(MODEL.OBS_DIM)],
        "actions": [[float((candidate + offset) % 5) / 5
                     for offset in range(MODEL.ACT_DIM)]
                    for candidate in range(3)],
        "target": target,
    }
    example["example_sha256"] = TRAIN._self_hash(example, "example_sha256")
    return example


def _population(*, split: str, surface: str, count: int) -> list[dict]:
    return [_example(index, split=split, surface=surface,
                     stratum=("ordinary_anchor" if index % 2 == 0
                              else "proposal_disagreement"))
            for index in range(count)]


def test_training_population_refuses_report_and_hash_drift() -> None:
    with pytest.raises(TRAIN.StageCTrainingError, match="REPORT"):
        TRAIN.validate_population(
            _population(split="REPORT", surface="play", count=2),
            split="REPORT", surface="play")
    values = _population(split="DESIGN", surface="play", count=2)
    values[0]["target"]["frozen_label_index"] = 0
    with pytest.raises(TRAIN.StageCTrainingError, match="target identity"):
        TRAIN.validate_population(values, split="DESIGN", surface="play")


def test_state_balanced_prior_does_not_overweight_large_ballots() -> None:
    examples = _population(split="DESIGN", surface="play", count=2)
    # Replace the second state by a one-candidate ballot. Both states must
    # still contribute one half of the prior.
    examples[1]["actions"] = examples[1]["actions"][:1]
    target = examples[1]["target"]
    for name in ("outcome_distribution", "ranking_mean_signed_level_utility",
                 "outcome_mean_signed_level_utility",
                 "candidate0_relative_advantage",
                 "candidate0_relative_weight"):
        target[name] = target[name][:1]
    target["pairwise_preference"] = [[0.5]]
    target["pairwise_weight"] = [[0.0]]
    target["candidate_count"] = 1
    target["frozen_label_index"] = 0
    target["deeper_report_pair"] = {
        "candidate_indices": [0, 0],
        "worlds": MODEL.HARD_REPORT_WORLDS,
        "replaced_all_candidate_pair": False,
    }
    target["target_sha256"] = TRAIN._self_hash(target, "target_sha256")
    examples[1]["example_sha256"] = TRAIN._self_hash(
        examples[1], "example_sha256")
    prior = TRAIN.state_balanced_prior(examples)
    first_state = [sum(row[index] for row in examples[0]["target"][
        "outcome_distribution"]) / 3 for index in range(8)]
    second_state = examples[1]["target"]["outcome_distribution"][0]
    assert prior == pytest.approx([
        (left + right) / 2 for left, right in zip(first_state, second_state)])


def test_epoch_order_is_deterministic_and_seed_specific() -> None:
    values = _population(split="DESIGN", surface="play", count=12)
    first = [row["state_id"] for row in TRAIN.deterministic_epoch_order(
        values, seed=41, epoch=1)]
    assert first == [row["state_id"] for row in TRAIN.deterministic_epoch_order(
        list(reversed(values)), seed=41, epoch=1)]
    assert first != [row["state_id"] for row in TRAIN.deterministic_epoch_order(
        values, seed=73, epoch=1)]


@pytest.mark.skipif(MODEL.torch is None, reason="torch is optional")
@pytest.mark.parametrize("loss_recipe", MODEL.LOSS_RECIPES)
def test_training_cell_is_reproducible_and_keeps_report_closed(
        loss_recipe: str) -> None:
    design = _population(split="DESIGN", surface="play", count=12)
    calib = _population(split="CALIB", surface="play", count=6)
    first = TRAIN.train_curve(
        design, calib, surface="play", seed=41,
        curve_fraction=1.0, loss_recipe=loss_recipe, max_epoch=2)
    second = TRAIN.train_curve(
        list(reversed(design)), list(reversed(calib)),
        surface="play", seed=41, curve_fraction=1.0,
        loss_recipe=loss_recipe, max_epoch=2)
    assert [row["model_state_sha256"] for row in first["snapshots"]] == [
        row["model_state_sha256"] for row in second["snapshots"]]
    assert [row["calib_metrics"] for row in first["snapshots"]] == [
        row["calib_metrics"] for row in second["snapshots"]]
    assert first["report_rows_opened"] == 0
    assert first["report_open_authorized"] is False
    assert first["loss_recipe"] == loss_recipe


@pytest.mark.skipif(MODEL.torch is None, reason="torch is optional")
def test_snapshot_publication_round_trips_and_refuses_overwrite(tmp_path) -> None:
    design = _population(split="DESIGN", surface="bury", count=6)
    calib = _population(split="CALIB", surface="bury", count=4)
    result = TRAIN.train_curve(
        design, calib, surface="bury", seed=41,
        curve_fraction=0.5, max_epoch=1)
    snapshot = result["snapshots"][0]
    contract = MODEL.checkpoint_contract(
        surface="bury", seed=41, epoch=1, curve_fraction=0.5,
        state_dict_sha256=snapshot["model_state_sha256"])
    path = tmp_path / "model.pt"
    published = TRAIN.publish_snapshot(
        path, state_dict=snapshot["state_dict"], contract=contract)
    assert published["model_state_sha256"] == snapshot["model_state_sha256"]
    assert TRAIN.load_snapshot(path, expected_contract=contract)[
        "model_state_sha256"] == snapshot["model_state_sha256"]
    with pytest.raises(TRAIN.StageCTrainingError, match="existing"):
        TRAIN.publish_snapshot(
            path, state_dict=snapshot["state_dict"], contract=contract)


@pytest.mark.skipif(MODEL.torch is None, reason="torch is optional")
def test_snapshot_publication_cross_binds_contract_to_model_state(
        tmp_path) -> None:
    net = MODEL.StageCRankingOutcomeNet()
    state = net.state_dict()
    actual_sha256 = TRAIN.state_digest(state)
    false_contract = MODEL.checkpoint_contract(
        surface="play", seed=41, epoch=1, curve_fraction=1.0,
        state_dict_sha256="0" * 64)
    assert false_contract["state_dict_sha256"] != actual_sha256
    with pytest.raises(TRAIN.StageCTrainingError, match="contract/model-state"):
        TRAIN.publish_snapshot(
            tmp_path / "false-contract.pt", state_dict=state,
            contract=false_contract)
    assert not (tmp_path / "false-contract.pt").exists()

    forged_path = tmp_path / "forged.pt"
    MODEL.torch.save({
        "schema": TRAIN.SNAPSHOT_SCHEMA,
        "contract": false_contract,
        "model_state_sha256": actual_sha256,
        "state_dict": state,
    }, forged_path)
    with pytest.raises(TRAIN.StageCTrainingError, match="identity drift"):
        TRAIN.load_snapshot(
            forged_path, expected_contract=false_contract)


@pytest.mark.skipif(MODEL.torch is None, reason="torch is optional")
def test_snapshot_publication_cannot_overwrite_raced_destination(
        tmp_path, monkeypatch) -> None:
    net = MODEL.StageCRankingOutcomeNet()
    state = net.state_dict()
    contract = MODEL.checkpoint_contract(
        surface="play", seed=41, epoch=1, curve_fraction=1.0,
        state_dict_sha256=TRAIN.state_digest(state))
    path = tmp_path / "raced.pt"
    real_link = TRAIN.os.link

    def _raced_link(source, destination, *, follow_symlinks):
        path.write_bytes(b"other publisher")
        return real_link(
            source, destination, follow_symlinks=follow_symlinks)

    monkeypatch.setattr(TRAIN.os, "link", _raced_link)
    with pytest.raises(TRAIN.StageCTrainingError, match="raced"):
        TRAIN.publish_snapshot(path, state_dict=state, contract=contract)
    assert path.read_bytes() == b"other publisher"
    assert (tmp_path / "raced.pt.partial").is_file()


def test_calib_population_cannot_be_used_as_design() -> None:
    calib = _population(split="CALIB", surface="play", count=2)
    with pytest.raises(TRAIN.StageCTrainingError, match="geometry"):
        TRAIN.state_balanced_prior(calib)
