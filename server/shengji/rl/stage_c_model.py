"""Stage-C ranking and calibrated-outcome model primitives.

Stage C is deliberately not another scalar-Q leaf.  Each independently
trained surface model exposes two outputs for every candidate in one public
information state:

* a within-ballot ranking logit, trained from paired common-world preferences;
* an eight-bin distribution over acting-team signed level utility.

Play and bury use separate checkpoints.  Eight fixed seeds are evaluated as a
cohort; CALIB chooses one epoch globally and never cherry-picks a seed.  This
module contains model/target/loss/metric mechanics only.  It does not open the
sealed REPORT fold, authorize training, compose a policy, or launch strength
compute.
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Mapping, Sequence

from .encode import ACT_DIM, OBS_DIM, encode_action, encode_obs


SCHEMA = "teacher-stage-c-model-example-v1"
MODEL_SCHEMA = "teacher-stage-c-ranking-outcome-model-v1"
SELECTION_SCHEMA = "teacher-stage-c-model-selection-v1"
SURFACES = ("play", "bury")
UTILITY_BINS = (-3.5, -2.5, -1.5, -0.5, 0.5, 1.5, 2.5, 3.5)
TRAINING_SEEDS = (41, 73, 101, 137, 173, 211, 251, 293)
CURVE_FRACTIONS = (0.25, 0.5, 1.0)
EPOCH_GRID = (1, 2, 4, 8, 16, 32)
PAIRWISE_WEIGHT = 1.0
LABEL_CE_WEIGHT = 0.25
OUTCOME_CE_WEIGHT = 1.0
ORDINARY_WORLDS = 256
HARD_SELECTION_WORLDS = 64
HARD_REPORT_WORLDS = 300


class StageCModelError(RuntimeError):
    """A Stage-C target, model surface, or selection contract drifted."""


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"))
            + "\n").encode()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def utility_bin(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise StageCModelError("Stage-C utility is not numeric")
    number = float(value)
    if not math.isfinite(number):
        raise StageCModelError("Stage-C utility is not finite")
    try:
        return UTILITY_BINS.index(number)
    except ValueError as exc:
        raise StageCModelError(
            f"Stage-C utility {number} is outside the frozen level bins") from exc


def utility_distribution(values: Sequence[object]) -> list[float]:
    if not values:
        raise StageCModelError("Stage-C utility sample is empty")
    counts = [0] * len(UTILITY_BINS)
    for value in values:
        counts[utility_bin(value)] += 1
    total = len(values)
    return [count / total for count in counts]


def distribution_mean(distribution: Sequence[object]) -> float:
    if (len(distribution) != len(UTILITY_BINS)
            or any(isinstance(value, bool)
                   or not isinstance(value, (int, float))
                   or not math.isfinite(float(value))
                   or float(value) < 0 for value in distribution)
            or not math.isclose(sum(float(value) for value in distribution),
                                1.0, rel_tol=1e-9, abs_tol=1e-9)):
        raise StageCModelError("Stage-C outcome distribution is invalid")
    return sum(value * float(probability)
               for value, probability in zip(
                   UTILITY_BINS, distribution, strict=True))


def paired_preference(left: Sequence[object], right: Sequence[object]) -> float:
    """Probability left beats right, with a tie worth one half."""
    if not left or len(left) != len(right):
        raise StageCModelError("Stage-C paired preference geometry drift")
    total = 0.0
    for left_value, right_value in zip(left, right, strict=True):
        left_bin = utility_bin(left_value)
        right_bin = utility_bin(right_value)
        total += 1.0 if left_bin > right_bin else (
            0.5 if left_bin == right_bin else 0.0)
    return total / len(left)


def _fold_actions(fold: Mapping[str, object], *,
                  candidate_count: int, require_all: bool) -> list[dict]:
    indices = fold.get("candidate_indices")
    actions = fold.get("actions")
    if (not isinstance(indices, list) or not isinstance(actions, list)
            or len(indices) != len(actions)
            or not indices):
        raise StageCModelError("Stage-C model fold action geometry drift")
    if require_all and indices != list(range(candidate_count)):
        raise StageCModelError("Stage-C all-candidate fold order drift")
    result = []
    for logical, (candidate_index, action) in enumerate(
            zip(indices, actions, strict=True)):
        if (isinstance(candidate_index, bool)
                or not isinstance(candidate_index, int)
                or not 0 <= candidate_index < candidate_count
                or not isinstance(action, dict)
                or action.get("logical_index") != logical
                or action.get("candidate_index") != candidate_index
                or not isinstance(action.get("signed_level_utility"), list)
                or not action["signed_level_utility"]):
            raise StageCModelError("Stage-C model fold action identity drift")
        # Validate all values now; later code can use them without accepting a
        # self-consistent but out-of-contract continuous target.
        for value in action["signed_level_utility"]:
            utility_bin(value)
        result.append(action)
    return result


def build_target(state: Mapping[str, object], row: Mapping[str, object]) -> dict:
    """Build one ranking/distribution target from a validated label row.

    Ordinary anchors use their 256-world all-candidate report fold.  Hard-tail
    states use the 64-world all-candidate selection fold, then replace the
    candidate-zero versus frozen-winner pair and both available distributions
    with their deeper 300-world report evidence.  REPORT rows may be passed to
    this pure function only by the separately authorized one-shot evaluator;
    the training controller is responsible for excluding them.
    """
    candidates = state.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise StageCModelError("Stage-C model state has no candidates")
    count = len(candidates)
    if (row.get("status") != "COMPLETE"
            or row.get("state_id") != state.get("state_id")
            or row.get("split") != state.get("split")
            or row.get("surface_type") != state.get("surface_type")
            or row.get("stratum") != state.get("stratum")
            or row.get("candidate_count") != count):
        raise StageCModelError("Stage-C model state/row identity drift")
    surface = state.get("surface_type")
    if surface not in SURFACES:
        raise StageCModelError("Stage-C model surface drift")
    recipe = row.get("recipe")
    if recipe not in {"ordinary_anchor", "hard_tail"}:
        raise StageCModelError("Stage-C model recipe drift")
    expected_recipe = ("ordinary_anchor"
                       if state.get("stratum") == "ordinary_anchor"
                       else "hard_tail")
    if recipe != expected_recipe:
        raise StageCModelError("Stage-C model state/recipe drift")
    base_name = "report" if recipe == "ordinary_anchor" else "selection"
    base_fold = row.get(base_name)
    if not isinstance(base_fold, dict):
        raise StageCModelError("Stage-C all-candidate target fold missing")
    base_actions = _fold_actions(
        base_fold, candidate_count=count, require_all=True)
    utilities = [list(action["signed_level_utility"])
                 for action in base_actions]
    sample_worlds = [len(values) for values in utilities]
    if len(set(sample_worlds)) != 1:
        raise StageCModelError("Stage-C target common-world count drift")
    expected_base_worlds = (ORDINARY_WORLDS if recipe == "ordinary_anchor"
                            else HARD_SELECTION_WORLDS)
    if sample_worlds[0] != expected_base_worlds:
        raise StageCModelError("Stage-C target world budget drift")
    ranking_distributions = [utility_distribution(values)
                             for values in utilities]
    # All-candidate ranking metrics must stay on one common-world fold.  A
    # hard-tail report contains only candidate zero and the frozen selection
    # winner, so replacing those two means and comparing them with selection-
    # fold means for the other candidates would create an incoherent ranking
    # target.  The outcome head may still use the deeper per-action evidence.
    ranking_means = [distribution_mean(value)
                     for value in ranking_distributions]
    distributions = [list(value) for value in ranking_distributions]
    preference = [[0.5] * count for _ in range(count)]
    pair_weights = [[0.0] * count for _ in range(count)]
    for left in range(count):
        for right in range(left + 1, count):
            probability = paired_preference(utilities[left], utilities[right])
            preference[left][right] = probability
            preference[right][left] = 1.0 - probability
            pair_weights[left][right] = pair_weights[right][left] = 1.0

    deeper_pair = None
    deeper_indices = None
    if recipe == "hard_tail":
        report = row.get("report")
        if not isinstance(report, dict):
            raise StageCModelError("Stage-C hard-tail report fold missing")
        report_actions = _fold_actions(
            report, candidate_count=count, require_all=False)
        if len(report_actions) != 2:
            raise StageCModelError("Stage-C hard-tail report must have two slots")
        left_index = int(report_actions[0]["candidate_index"])
        right_index = int(report_actions[1]["candidate_index"])
        if left_index != 0:
            raise StageCModelError("Stage-C hard-tail report lost candidate zero")
        left_values = list(report_actions[0]["signed_level_utility"])
        right_values = list(report_actions[1]["signed_level_utility"])
        if len(left_values) != len(right_values) or not left_values:
            raise StageCModelError("Stage-C hard-tail report worlds drift")
        if len(left_values) != HARD_REPORT_WORLDS:
            raise StageCModelError("Stage-C hard-tail report budget drift")
        distributions[left_index] = utility_distribution(left_values)
        distributions[right_index] = utility_distribution(right_values)
        if left_index != right_index:
            probability = paired_preference(left_values, right_values)
            preference[left_index][right_index] = probability
            preference[right_index][left_index] = 1.0 - probability
            weight = len(left_values) / sample_worlds[0]
            pair_weights[left_index][right_index] = weight
            pair_weights[right_index][left_index] = weight
        deeper_pair = {
            "candidate_indices": [left_index, right_index],
            "worlds": len(left_values),
            "replaced_all_candidate_pair": left_index != right_index,
        }
        deeper_indices = {left_index, right_index}

    label = row.get("label_action", {}).get("index")
    if (isinstance(label, bool) or not isinstance(label, int)
            or not 0 <= label < count):
        raise StageCModelError("Stage-C frozen label index drift")
    if deeper_indices is not None and label not in deeper_indices:
        raise StageCModelError("Stage-C hard-tail label/report identity drift")
    target = {
        "schema": "teacher-stage-c-model-target-v1",
        "state_id": state["state_id"],
        "split": state["split"],
        "surface_type": surface,
        "stratum": state["stratum"],
        "recipe": recipe,
        "candidate_count": count,
        "all_candidate_fold": base_name,
        "all_candidate_worlds": sample_worlds[0],
        "deeper_report_pair": deeper_pair,
        "frozen_label_index": label,
        "pairwise_preference": preference,
        "pairwise_weight": pair_weights,
        "outcome_distribution": distributions,
        "ranking_mean_signed_level_utility": ranking_means,
        "outcome_mean_signed_level_utility": [
            distribution_mean(value) for value in distributions],
        "utility_bins": list(UTILITY_BINS),
    }
    target["target_sha256"] = sha256_bytes(canonical_json(target))
    return target


def materialize_example(state: Mapping[str, object], row: Mapping[str, object],
                        rnd) -> dict:
    """Attach frozen public observation/action encodings to a model target."""
    target = build_target(state, row)
    seat = state.get("seat")
    if isinstance(seat, bool) or not isinstance(seat, int) or not 0 <= seat < 4:
        raise StageCModelError("Stage-C model seat drift")
    candidates = state["candidates"]
    obs = encode_obs(rnd, seat)
    actions = [encode_action(list(candidate["cards"]), rnd)
               for candidate in candidates]
    if len(obs) != OBS_DIM or any(len(action) != ACT_DIM for action in actions):
        raise StageCModelError("Stage-C model encoder shape drift")
    example = {
        "schema": SCHEMA,
        "state_id": state["state_id"],
        "split": state["split"],
        "surface_type": state["surface_type"],
        "stratum": state["stratum"],
        "obs": obs,
        "actions": actions,
        "target": target,
    }
    example["example_sha256"] = sha256_bytes(canonical_json(example))
    return example


def curve_subset(examples: Sequence[Mapping[str, object]],
                 fraction: float) -> list[Mapping[str, object]]:
    """Deterministic nested, stratum-preserving DESIGN learning curves."""
    if fraction not in CURVE_FRACTIONS:
        raise StageCModelError("Stage-C curve fraction is not frozen")
    if any(example.get("split") != "DESIGN" for example in examples):
        raise StageCModelError("Stage-C learning curve received non-DESIGN row")
    groups: dict[tuple[str, str], list[Mapping[str, object]]] = defaultdict(list)
    for example in examples:
        surface = str(example.get("surface_type"))
        stratum = str(example.get("stratum"))
        if surface not in SURFACES:
            raise StageCModelError("Stage-C curve surface drift")
        groups[(surface, stratum)].append(example)
    selected = []
    for key, values in sorted(groups.items()):
        ordered = sorted(values, key=lambda example: sha256_bytes(
            canonical_json(["stage-c-curve-v1", key, example["state_id"]])))
        count = len(ordered) if fraction == 1.0 else max(
            1, math.ceil(len(ordered) * fraction))
        selected.extend(ordered[:count])
    return sorted(selected, key=lambda example: str(example["state_id"]))


try:
    import torch
    from torch import nn
except ImportError:  # keep core game imports usable without the RL group
    torch = None
    nn = None


if torch is not None:

    class StageCRankingOutcomeNet(nn.Module):
        """Small per-surface network with separate rank/distribution heads."""

        def __init__(self, hidden: int = 256):
            super().__init__()
            self.obs_trunk = nn.Sequential(
                nn.Linear(OBS_DIM, hidden), nn.ReLU(),
                nn.Linear(hidden, 128), nn.ReLU(),
            )
            self.action_trunk = nn.Sequential(
                nn.Linear(ACT_DIM, 64), nn.ReLU(),
            )
            self.joint = nn.Sequential(
                nn.Linear(192, 128), nn.ReLU(),
            )
            self.rank_head = nn.Linear(128, 1)
            self.outcome_head = nn.Linear(128, len(UTILITY_BINS))

        def forward_grouped(self, obs_dec, action_rows, segment):
            obs_features = self.obs_trunk(obs_dec)
            action_features = self.action_trunk(action_rows)
            joint = self.joint(torch.cat(
                [obs_features[segment], action_features], dim=-1))
            return (self.rank_head(joint).squeeze(-1),
                    self.outcome_head(joint))

        def score_candidates(self, obs, actions):
            with torch.no_grad():
                obs_tensor = torch.as_tensor(
                    obs, dtype=torch.float32).unsqueeze(0)
                action_tensor = torch.as_tensor(actions, dtype=torch.float32)
                segment = torch.zeros(
                    len(actions), dtype=torch.long,
                    device=action_tensor.device)
                return self.forward_grouped(
                    obs_tensor, action_tensor, segment)


def collate_examples(examples: Sequence[Mapping[str, object]], *, device=None):
    if torch is None:
        raise StageCModelError("Stage-C model training requires torch")
    if not examples:
        raise StageCModelError("Stage-C model batch is empty")
    obs_rows = []
    action_rows = []
    segments = []
    label_rows = []
    bracket_targets = []
    pair_left = []
    pair_right = []
    pair_targets = []
    pair_weights = []
    pair_segments = []
    offset = 0
    for decision, example in enumerate(examples):
        actions = example.get("actions")
        target = example.get("target", {})
        count = target.get("candidate_count")
        if (not isinstance(actions, list) or isinstance(count, bool)
                or not isinstance(count, int) or len(actions) != count
                or count <= 0):
            raise StageCModelError("Stage-C batch candidate geometry drift")
        obs_rows.append(example["obs"])
        action_rows.extend(actions)
        segments.extend([decision] * count)
        label_rows.append(offset + int(target["frozen_label_index"]))
        bracket_targets.extend(target["outcome_distribution"])
        preferences = target["pairwise_preference"]
        weights = target["pairwise_weight"]
        for left in range(count):
            for right in range(left + 1, count):
                pair_left.append(offset + left)
                pair_right.append(offset + right)
                pair_targets.append(float(preferences[left][right]))
                pair_weights.append(float(weights[left][right]))
                pair_segments.append(decision)
        offset += count
    return {
        "obs": torch.as_tensor(obs_rows, dtype=torch.float32, device=device),
        "actions": torch.as_tensor(
            action_rows, dtype=torch.float32, device=device),
        "segments": torch.as_tensor(
            segments, dtype=torch.long, device=device),
        "label_rows": torch.as_tensor(
            label_rows, dtype=torch.long, device=device),
        "bracket_targets": torch.as_tensor(
            bracket_targets, dtype=torch.float32, device=device),
        "pair_left": torch.as_tensor(
            pair_left, dtype=torch.long, device=device),
        "pair_right": torch.as_tensor(
            pair_right, dtype=torch.long, device=device),
        "pair_targets": torch.as_tensor(
            pair_targets, dtype=torch.float32, device=device),
        "pair_weights": torch.as_tensor(
            pair_weights, dtype=torch.float32, device=device),
        "pair_segments": torch.as_tensor(
            pair_segments, dtype=torch.long, device=device),
        "decisions": len(examples),
    }


def _segment_mean(values, segments, count: int, weights=None):
    if weights is None:
        weights = torch.ones_like(values)
    total = torch.zeros(count, dtype=values.dtype, device=values.device)
    denom = torch.zeros(count, dtype=values.dtype, device=values.device)
    total.index_add_(0, segments, values * weights)
    denom.index_add_(0, segments, weights)
    return total / denom.clamp(min=1e-12)


def _segment_log_softmax(values, segments, count: int):
    maxima = torch.full(
        (count,), -torch.inf, dtype=values.dtype, device=values.device)
    maxima.scatter_reduce_(0, segments, values, reduce="amax", include_self=True)
    shifted = values - maxima[segments]
    denominators = torch.zeros(
        count, dtype=values.dtype, device=values.device)
    denominators.index_add_(0, segments, torch.exp(shifted))
    return shifted - torch.log(denominators[segments].clamp(min=1e-12))


def stage_c_loss(net, batch: Mapping[str, object]) -> dict:
    """State-balanced pairwise ranking, label and distribution losses."""
    if torch is None:
        raise StageCModelError("Stage-C model training requires torch")
    decisions = int(batch["decisions"])
    rank, outcome_logits = net.forward_grouped(
        batch["obs"], batch["actions"], batch["segments"])
    pair_logits = rank[batch["pair_left"]] - rank[batch["pair_right"]]
    pair_rows = torch.nn.functional.binary_cross_entropy_with_logits(
        pair_logits, batch["pair_targets"], reduction="none")
    pairwise = _segment_mean(
        pair_rows, batch["pair_segments"], decisions,
        weights=batch["pair_weights"]).mean()
    log_rank = _segment_log_softmax(rank, batch["segments"], decisions)
    label_ce = -log_rank[batch["label_rows"]].mean()
    log_outcome = torch.nn.functional.log_softmax(outcome_logits, dim=-1)
    outcome_rows = -(batch["bracket_targets"] * log_outcome).sum(dim=-1)
    outcome_ce = _segment_mean(
        outcome_rows, batch["segments"], decisions).mean()
    total = (PAIRWISE_WEIGHT * pairwise
             + LABEL_CE_WEIGHT * label_ce
             + OUTCOME_CE_WEIGHT * outcome_ce)
    return {
        "loss": total,
        "pairwise_bce": pairwise,
        "label_ce": label_ce,
        "outcome_ce": outcome_ce,
    }


def evaluate_predictions(examples: Sequence[Mapping[str, object]],
                         rank_rows: Sequence[Sequence[float]],
                         outcome_rows: Sequence[Sequence[Sequence[float]]],
                         *, prior_distribution: Sequence[float] | None = None
                         ) -> dict:
    """Compute state-balanced ranking and calibration diagnostics."""
    if (not examples or len(examples) != len(rank_rows)
            or len(examples) != len(outcome_rows)):
        raise StageCModelError("Stage-C evaluation population drift")
    if prior_distribution is not None:
        distribution_mean(prior_distribution)
    regrets = []
    baseline_regrets = []
    agreements = []
    top3 = []
    nll = []
    brier = []
    utility_mae = []
    prior_nll = []
    for example, ranks, predictions in zip(
            examples, rank_rows, outcome_rows, strict=True):
        target = example["target"]
        means = target["ranking_mean_signed_level_utility"]
        distributions = target["outcome_distribution"]
        count = target["candidate_count"]
        if (len(ranks) != count or len(predictions) != count
                or any(isinstance(value, bool)
                       or not isinstance(value, (int, float))
                       or not math.isfinite(float(value)) for value in ranks)):
            raise StageCModelError("Stage-C prediction candidate drift")
        selected = max(range(count), key=lambda index: (ranks[index], -index))
        teacher_best = max(means)
        regrets.append(teacher_best - means[selected])
        baseline_regrets.append(teacher_best - means[0])
        label = int(target["frozen_label_index"])
        agreements.append(float(selected == label))
        ordered = sorted(range(count), key=lambda index: (-ranks[index], index))
        top3.append(float(label in ordered[:3]))
        state_nll = []
        state_brier = []
        state_mae = []
        state_prior = []
        for predicted, actual in zip(predictions, distributions, strict=True):
            if (len(predicted) != len(UTILITY_BINS)
                    or any(isinstance(value, bool)
                           or not isinstance(value, (int, float))
                           or float(value) <= 0
                           or not math.isfinite(float(value))
                           for value in predicted)
                    or not math.isclose(sum(float(value) for value in predicted),
                                        1.0, rel_tol=1e-6, abs_tol=1e-6)):
                raise StageCModelError("Stage-C predicted distribution drift")
            state_nll.append(-sum(float(target_p) * math.log(float(model_p))
                                  for target_p, model_p in zip(
                                      actual, predicted, strict=True)))
            state_brier.append(sum((float(model_p) - float(target_p)) ** 2
                                   for model_p, target_p in zip(
                                       predicted, actual, strict=True)))
            # ``predicted`` comes from float32 softmax and is already checked
            # above at the frozen 1e-6 model-output tolerance.  Reusing the
            # 1e-9 empirical-target validator here would reject ordinary
            # softmax roundoff even though the prediction contract passed.
            predicted_mean = sum(
                utility * float(probability)
                for utility, probability in zip(
                    UTILITY_BINS, predicted, strict=True))
            state_mae.append(abs(predicted_mean
                                 - distribution_mean(actual)))
            if prior_distribution is not None:
                state_prior.append(-sum(
                    float(target_p) * math.log(max(float(prior_p), 1e-12))
                    for target_p, prior_p in zip(
                        actual, prior_distribution, strict=True)))
        nll.append(sum(state_nll) / len(state_nll))
        brier.append(sum(state_brier) / len(state_brier))
        utility_mae.append(sum(state_mae) / len(state_mae))
        if state_prior:
            prior_nll.append(sum(state_prior) / len(state_prior))

    def mean(values):
        return sum(values) / len(values) if values else None

    result = {
        "states": len(examples),
        "mean_teacher_regret": mean(regrets),
        "candidate0_mean_teacher_regret": mean(baseline_regrets),
        "ranking_improvement_vs_candidate0": (
            mean(baseline_regrets) - mean(regrets)),
        "frozen_label_top1_agreement": mean(agreements),
        "frozen_label_top3_coverage": mean(top3),
        "outcome_nll": mean(nll),
        "outcome_brier": mean(brier),
        "expected_utility_mae": mean(utility_mae),
        "prior_outcome_nll": mean(prior_nll),
        "outcome_nll_improvement_vs_prior": (
            mean(prior_nll) - mean(nll) if prior_nll else None),
    }
    return result


def select_global_epoch(records: Sequence[Mapping[str, object]]) -> dict:
    """Choose one CALIB epoch for the complete eight-seed surface ensemble."""
    by_epoch: dict[int, list[Mapping[str, object]]] = defaultdict(list)
    for record in records:
        epoch = record.get("epoch")
        if (isinstance(epoch, bool) or not isinstance(epoch, int)
                or epoch not in EPOCH_GRID
                or record.get("seed") not in TRAINING_SEEDS
                or record.get("surface") not in SURFACES
                or record.get("split") != "CALIB"
                or record.get("curve_fraction") != 1.0):
            raise StageCModelError("Stage-C CALIB record identity drift")
        metrics = record.get("metrics")
        required_metrics = {
            "ranking_improvement_vs_candidate0", "outcome_nll_improvement_vs_prior",
            "mean_teacher_regret", "outcome_nll",
        }
        if (not isinstance(metrics, dict)
                or any(name not in metrics
                       or isinstance(metrics[name], bool)
                       or not isinstance(metrics[name], (int, float))
                       or not math.isfinite(float(metrics[name]))
                       for name in required_metrics)):
            raise StageCModelError("Stage-C CALIB metric drift")
        by_epoch[epoch].append(record)
    candidates = []
    expected_cells = {(surface, seed) for surface in SURFACES
                      for seed in TRAINING_SEEDS}
    for epoch in EPOCH_GRID:
        values = by_epoch.get(epoch, [])
        cells = {(value["surface"], value["seed"]) for value in values}
        if cells != expected_cells or len(values) != len(expected_cells):
            raise StageCModelError("Stage-C CALIB epoch population drift")
        surface_summary = {}
        eligible = True
        for surface in SURFACES:
            metrics = [value["metrics"] for value in values
                       if value["surface"] == surface]
            ranking = sorted(float(value[
                "ranking_improvement_vs_candidate0"]) for value in metrics)
            calibration = sorted(float(value[
                "outcome_nll_improvement_vs_prior"]) for value in metrics)
            ranking_positive = sum(value > 0 for value in ranking)
            calibration_positive = sum(value > 0 for value in calibration)
            median_ranking = (ranking[3] + ranking[4]) / 2
            median_calibration = (calibration[3] + calibration[4]) / 2
            surface_summary[surface] = {
                "ranking_positive_seeds": ranking_positive,
                "calibration_positive_seeds": calibration_positive,
                "median_ranking_improvement": median_ranking,
                "median_outcome_nll_improvement": median_calibration,
                "mean_teacher_regret": sum(float(value[
                    "mean_teacher_regret"]) for value in metrics) / len(metrics),
                "mean_outcome_nll": sum(float(value["outcome_nll"])
                                         for value in metrics) / len(metrics),
            }
            eligible &= (ranking_positive >= 6 and calibration_positive >= 6
                         and median_ranking > 0 and median_calibration > 0)
        candidates.append({
            "epoch": epoch,
            "eligible": eligible,
            "surfaces": surface_summary,
            "worst_surface_median_ranking_improvement": min(
                value["median_ranking_improvement"]
                for value in surface_summary.values()),
            "mean_outcome_nll": sum(value["mean_outcome_nll"]
                                    for value in surface_summary.values()) / 2,
        })
    passing = [value for value in candidates if value["eligible"]]
    selected = max(
        passing,
        key=lambda value: (
            value["worst_surface_median_ranking_improvement"],
            -value["mean_outcome_nll"], -value["epoch"]),
    ) if passing else None
    result = {
        "schema": SELECTION_SCHEMA,
        "seeds": list(TRAINING_SEEDS),
        "surfaces": list(SURFACES),
        "epoch_grid": list(EPOCH_GRID),
        "criterion": (
            "both surfaces: >=6/8 seeds improve ranking and outcome NLL; "
            "positive medians; maximize worst-surface median ranking gain, "
            "then minimize mean NLL, then earliest epoch"
        ),
        "candidates": candidates,
        "decision": ("FREEZE_EIGHT_SEED_ENSEMBLE_FOR_REPORT_REVIEW"
                     if selected is not None else "SELECT_NONE"),
        "selected_epoch": selected["epoch"] if selected else None,
        "single_seed_selection": False,
        "report_open_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
    }
    result["selection_sha256"] = sha256_bytes(canonical_json(result))
    return result


def checkpoint_contract(*, surface: str, seed: int, epoch: int,
                        curve_fraction: float, state_dict_sha256: str) -> dict:
    if (surface not in SURFACES or seed not in TRAINING_SEEDS
            or epoch not in EPOCH_GRID or curve_fraction not in CURVE_FRACTIONS
            or len(state_dict_sha256) != 64
            or any(character not in "0123456789abcdef"
                   for character in state_dict_sha256)):
        raise StageCModelError("Stage-C checkpoint identity drift")
    return {
        "schema": MODEL_SCHEMA,
        "surface": surface,
        "seed": seed,
        "epoch": epoch,
        "curve_fraction": curve_fraction,
        "architecture": "StageCRankingOutcomeNet(hidden=256)",
        "utility_bins": list(UTILITY_BINS),
        "loss_weights": {
            "pairwise_bce": PAIRWISE_WEIGHT,
            "frozen_label_ce": LABEL_CE_WEIGHT,
            "outcome_distribution_ce": OUTCOME_CE_WEIGHT,
        },
        "state_dict_sha256": state_dict_sha256,
        "play_and_bury_share_weights": False,
    }
