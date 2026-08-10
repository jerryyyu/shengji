"""Deterministic Stage-C ranking/outcome training mechanics.

This module consumes already validated, public-observation model examples.  It
never reads label shards, the sealed REPORT split, game outcomes outside those
examples, or a production policy.  A separately reviewed controller must bind
the immutable DESIGN/CALIB dataset, cell schedule, output paths and authority
before any real training execution.

Each play/bury surface is trained independently across the eight frozen seeds
and nested DESIGN state-count curves.  Every cell starts from scratch, uses a
deterministic state order per epoch, and snapshots the frozen epoch grid.  Only
the full-data cells are eligible for the later global CALIB selection rule in
``stage_c_model.select_global_epoch``.
"""
from __future__ import annotations

import copy
import math
import os
from pathlib import Path
from typing import Callable, Mapping, Sequence

from . import stage_c_model as MODEL
from .exact_resume import state_digest


TRAINING_SCHEMA = "teacher-stage-c-training-cell-v1"
SNAPSHOT_SCHEMA = "teacher-stage-c-model-snapshot-v1"
BATCH_SIZE = 64
LEARNING_RATE = 3e-4
WEIGHT_DECAY = 1e-4
HIDDEN = 256
MAX_EPOCH = max(MODEL.EPOCH_GRID)
CPU_THREADS = 1


class StageCTrainingError(RuntimeError):
    """A Stage-C training identity, split, or deterministic boundary drifted."""


def _require_torch():
    if MODEL.torch is None:
        raise StageCTrainingError("Stage-C training requires torch")
    return MODEL.torch


def _self_hash(value: Mapping[str, object], field: str) -> str:
    return MODEL.sha256_bytes(MODEL.canonical_json(
        {key: item for key, item in value.items() if key != field}))


def _finite_vector(value: object, length: int) -> bool:
    return (isinstance(value, list) and len(value) == length
            and all(not isinstance(item, bool)
                    and isinstance(item, (int, float))
                    and math.isfinite(float(item)) for item in value))


def _validate_example(example: Mapping[str, object], *, split: str,
                      surface: str) -> None:
    if (example.get("schema") != MODEL.SCHEMA
            or example.get("split") != split
            or example.get("surface_type") != surface
            or not isinstance(example.get("state_id"), str)
            or not example["state_id"]
            or not _finite_vector(example.get("obs"), MODEL.OBS_DIM)
            or not isinstance(example.get("actions"), list)
            or not example["actions"]
            or any(not _finite_vector(action, MODEL.ACT_DIM)
                   for action in example["actions"])
            or not isinstance(example.get("target"), dict)):
        raise StageCTrainingError("Stage-C training example geometry drift")
    target = example["target"]
    if (target.get("state_id") != example["state_id"]
            or target.get("split") != split
            or target.get("surface_type") != surface
            or target.get("candidate_count") != len(example["actions"])
            or target.get("target_sha256") != _self_hash(
                target, "target_sha256")):
        raise StageCTrainingError("Stage-C training target identity drift")
    if example.get("example_sha256") != _self_hash(
            example, "example_sha256"):
        raise StageCTrainingError("Stage-C training example hash drift")
    count = len(example["actions"])
    distributions = target.get("outcome_distribution")
    ranking_means = target.get("ranking_mean_signed_level_utility")
    outcome_means = target.get("outcome_mean_signed_level_utility")
    preferences = target.get("pairwise_preference")
    weights = target.get("pairwise_weight")
    label = target.get("frozen_label_index")
    expected_recipe = ("ordinary_anchor"
                       if example.get("stratum") == "ordinary_anchor"
                       else "hard_tail")
    expected_worlds = (MODEL.ORDINARY_WORLDS
                       if expected_recipe == "ordinary_anchor"
                       else MODEL.HARD_SELECTION_WORLDS)
    deeper = target.get("deeper_report_pair")
    if (target.get("schema") != "teacher-stage-c-model-target-v1"
            or target.get("stratum") != example.get("stratum")
            or target.get("recipe") != expected_recipe
            or target.get("all_candidate_fold") != (
                "report" if expected_recipe == "ordinary_anchor"
                else "selection")
            or target.get("all_candidate_worlds") != expected_worlds
            or target.get("utility_bins") != list(MODEL.UTILITY_BINS)
            or (expected_recipe == "ordinary_anchor" and deeper is not None)
            or (expected_recipe == "hard_tail"
                and (not isinstance(deeper, dict)
                     or deeper.get("worlds") != MODEL.HARD_REPORT_WORLDS
                     or not isinstance(deeper.get("candidate_indices"), list)
                     or len(deeper["candidate_indices"]) != 2))
            or not isinstance(distributions, list)
            or len(distributions) != count
            or any(not isinstance(value, list) for value in distributions)
            or not _finite_vector(ranking_means, count)
            or not _finite_vector(outcome_means, count)
            or not isinstance(preferences, list) or len(preferences) != count
            or not isinstance(weights, list) or len(weights) != count
            or any(not _finite_vector(value, count) for value in preferences)
            or any(not _finite_vector(value, count) for value in weights)
            or any(not 0 <= float(value) <= 1
                   for row in preferences for value in row)
            or any(float(value) < 0 for row in weights for value in row)
            or isinstance(label, bool) or not isinstance(label, int)
            or not 0 <= label < count):
        raise StageCTrainingError("Stage-C training target geometry drift")
    for distribution in distributions:
        MODEL.distribution_mean(distribution)
    if any(not math.isclose(
            float(outcome_means[index]),
            MODEL.distribution_mean(distributions[index]),
            rel_tol=1e-9, abs_tol=1e-9) for index in range(count)):
        raise StageCTrainingError("Stage-C training outcome mean drift")
    for left in range(count):
        if (not math.isclose(float(preferences[left][left]), 0.5)
                or float(weights[left][left]) != 0.0):
            raise StageCTrainingError("Stage-C training pair diagonal drift")
        for right in range(left + 1, count):
            if (not math.isclose(
                    float(preferences[left][right])
                    + float(preferences[right][left]), 1.0,
                    rel_tol=1e-9, abs_tol=1e-9)
                    or not math.isclose(
                        float(weights[left][right]),
                        float(weights[right][left]),
                        rel_tol=1e-9, abs_tol=1e-9)):
                raise StageCTrainingError("Stage-C training pair symmetry drift")


def validate_population(examples: Sequence[Mapping[str, object]], *,
                        split: str, surface: str) -> None:
    if split not in {"DESIGN", "CALIB"}:
        raise StageCTrainingError("Stage-C training cannot consume REPORT")
    if surface not in MODEL.SURFACES or not examples:
        raise StageCTrainingError("Stage-C training population is empty")
    ids = []
    for example in sorted(examples, key=lambda value: str(value["state_id"])):
        _validate_example(example, split=split, surface=surface)
        ids.append(str(example["state_id"]))
    if len(set(ids)) != len(ids):
        raise StageCTrainingError("Stage-C training state identity collision")


def state_balanced_prior(
        examples: Sequence[Mapping[str, object]]) -> list[float]:
    """Empirical DESIGN prior with equal state and candidate weight."""
    if not examples:
        raise StageCTrainingError("Stage-C prior population is empty")
    surface = str(examples[0].get("surface_type"))
    validate_population(examples, split="DESIGN", surface=surface)
    result = [0.0] * len(MODEL.UTILITY_BINS)
    for example in sorted(examples, key=lambda value: str(value["state_id"])):
        distributions = example["target"]["outcome_distribution"]
        candidate_weight = 1.0 / len(distributions)
        for distribution in distributions:
            MODEL.distribution_mean(distribution)
            for index, value in enumerate(distribution):
                result[index] += float(value) * candidate_weight
    result = [value / len(examples) for value in result]
    # Accumulation error is harmless but canonicalize the last bin so every
    # consumer sees a probability vector summing to exactly one in arithmetic.
    result[-1] += 1.0 - sum(result)
    MODEL.distribution_mean(result)
    return result


def deterministic_epoch_order(
        examples: Sequence[Mapping[str, object]], *, seed: int,
        epoch: int) -> list[Mapping[str, object]]:
    if seed not in MODEL.TRAINING_SEEDS or isinstance(epoch, bool) \
            or not isinstance(epoch, int) or epoch <= 0:
        raise StageCTrainingError("Stage-C epoch-order identity drift")
    return sorted(examples, key=lambda example: MODEL.sha256_bytes(
        MODEL.canonical_json([
            "teacher-stage-c-epoch-order-v1", seed, epoch,
            example.get("state_id"),
        ])))


def deterministic_batches(
        examples: Sequence[Mapping[str, object]], *, seed: int,
        epoch: int) -> list[list[Mapping[str, object]]]:
    ordered = deterministic_epoch_order(examples, seed=seed, epoch=epoch)
    return [ordered[start:start + BATCH_SIZE]
            for start in range(0, len(ordered), BATCH_SIZE)]


def predict_examples(net, examples: Sequence[Mapping[str, object]]) -> tuple[
        list[list[float]], list[list[list[float]]]]:
    """Return ragged rank logits and outcome probabilities in input order."""
    torch = _require_torch()
    if not examples:
        raise StageCTrainingError("Stage-C prediction population is empty")
    batch = MODEL.collate_examples(examples, device="cpu")
    net.eval()
    with torch.no_grad():
        rank, logits = net.forward_grouped(
            batch["obs"], batch["actions"], batch["segments"])
        probabilities = torch.nn.functional.softmax(logits, dim=-1)
    rank_values = rank.detach().cpu().tolist()
    probability_values = probabilities.detach().cpu().tolist()
    rank_rows = []
    outcome_rows = []
    offset = 0
    for example in examples:
        count = int(example["target"]["candidate_count"])
        rank_rows.append(rank_values[offset:offset + count])
        outcome_rows.append(probability_values[offset:offset + count])
        offset += count
    if offset != len(rank_values) or offset != len(probability_values):
        raise StageCTrainingError("Stage-C ragged prediction offset drift")
    return rank_rows, outcome_rows


def evaluate_model(net, examples: Sequence[Mapping[str, object]], *,
                   prior_distribution: Sequence[float]) -> dict:
    ordered = sorted(examples, key=lambda value: str(value["state_id"]))
    ranks, outcomes = predict_examples(net, ordered)
    return MODEL.evaluate_predictions(
        ordered, ranks, outcomes, prior_distribution=prior_distribution)


def _configure_determinism(seed: int) -> None:
    torch = _require_torch()
    if seed not in MODEL.TRAINING_SEEDS:
        raise StageCTrainingError("Stage-C training seed is not frozen")
    torch.set_num_threads(CPU_THREADS)
    try:
        torch.set_num_interop_threads(CPU_THREADS)
    except RuntimeError:
        # PyTorch permits setting interop threads only before parallel work.
        # A different already-set value is still a refusal.
        if torch.get_num_interop_threads() != CPU_THREADS:
            raise StageCTrainingError(
                "Stage-C torch interop-thread identity drift")
    torch.use_deterministic_algorithms(True)
    torch.manual_seed(seed)


def _state_dict_cpu(net) -> dict:
    return {name: value.detach().cpu().clone()
            for name, value in net.state_dict().items()}


def train_curve(
    design_examples: Sequence[Mapping[str, object]],
    calib_examples: Sequence[Mapping[str, object]],
    *, surface: str, seed: int, curve_fraction: float,
    max_epoch: int = MAX_EPOCH,
    heartbeat: Callable[[Mapping[str, object]], None] | None = None,
) -> dict:
    """Train one frozen surface/seed/curve cell from scratch on CPU."""
    torch = _require_torch()
    if (surface not in MODEL.SURFACES or seed not in MODEL.TRAINING_SEEDS
            or curve_fraction not in MODEL.CURVE_FRACTIONS
            or isinstance(max_epoch, bool) or not isinstance(max_epoch, int)
            or max_epoch not in MODEL.EPOCH_GRID):
        raise StageCTrainingError("Stage-C training cell identity drift")
    validate_population(design_examples, split="DESIGN", surface=surface)
    validate_population(calib_examples, split="CALIB", surface=surface)
    if ({str(value["state_id"]) for value in design_examples}
            & {str(value["state_id"]) for value in calib_examples}):
        raise StageCTrainingError("Stage-C DESIGN/CALIB identity overlap")
    selected_design = list(MODEL.curve_subset(
        design_examples, curve_fraction))
    prior = state_balanced_prior(design_examples)
    _configure_determinism(seed)
    net = MODEL.StageCRankingOutcomeNet(hidden=HIDDEN).to("cpu")
    optimizer = torch.optim.AdamW(
        net.parameters(), lr=LEARNING_RATE, weight_decay=WEIGHT_DECAY,
        foreach=False)
    snapshots = []
    updates = 0
    for epoch in range(1, max_epoch + 1):
        net.train()
        epoch_losses = []
        for examples in deterministic_batches(
                selected_design, seed=seed, epoch=epoch):
            batch = MODEL.collate_examples(examples, device="cpu")
            optimizer.zero_grad(set_to_none=True)
            losses = MODEL.stage_c_loss(net, batch)
            if not all(torch.isfinite(value) for value in losses.values()):
                raise StageCTrainingError("Stage-C training loss is not finite")
            losses["loss"].backward()
            torch.nn.utils.clip_grad_norm_(net.parameters(), max_norm=5.0)
            optimizer.step()
            updates += 1
            epoch_losses.append({
                name: float(value.detach().cpu()) for name, value in losses.items()
            })
        if heartbeat is not None:
            heartbeat({
                "status": "TRAINING",
                "surface": surface,
                "seed": seed,
                "curve_fraction": curve_fraction,
                "epoch": epoch,
                "max_epoch": max_epoch,
                "updates": updates,
            })
        if epoch not in MODEL.EPOCH_GRID:
            continue
        state = _state_dict_cpu(net)
        snapshots.append({
            "epoch": epoch,
            "updates": updates,
            "mean_training_loss": {
                name: sum(row[name] for row in epoch_losses) / len(epoch_losses)
                for name in ("loss", "pairwise_bce", "label_ce", "outcome_ce")
            },
            "calib_metrics": evaluate_model(
                net, calib_examples, prior_distribution=prior),
            "model_state_sha256": state_digest(state),
            "state_dict": state,
        })
    expected_epochs = [epoch for epoch in MODEL.EPOCH_GRID
                       if epoch <= max_epoch]
    if [value["epoch"] for value in snapshots] != expected_epochs:
        raise StageCTrainingError("Stage-C snapshot epoch grid drift")
    result = {
        "schema": TRAINING_SCHEMA,
        "surface": surface,
        "seed": seed,
        "curve_fraction": curve_fraction,
        "design_states": len(selected_design),
        "full_design_states": len(design_examples),
        "calib_states": len(calib_examples),
        "prior_distribution": prior,
        "hyperparameters": {
            "architecture": f"StageCRankingOutcomeNet(hidden={HIDDEN})",
            "batch_size_states": BATCH_SIZE,
            "learning_rate": LEARNING_RATE,
            "weight_decay": WEIGHT_DECAY,
            "gradient_clip_norm": 5.0,
            "max_epoch": max_epoch,
            "cpu_threads": CPU_THREADS,
            "device": "cpu",
            "deterministic_algorithms": True,
        },
        "snapshots": snapshots,
        "report_rows_opened": 0,
        "report_open_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
    }
    return result


def _snapshot_payload(*, state_dict: Mapping[str, object],
                      contract: Mapping[str, object]) -> dict:
    model_state_sha256 = state_digest(state_dict)
    if contract.get("state_dict_sha256") != model_state_sha256:
        raise StageCTrainingError(
            "Stage-C checkpoint contract/model-state mismatch")
    return {
        "schema": SNAPSHOT_SCHEMA,
        "contract": dict(contract),
        "model_state_sha256": model_state_sha256,
        "state_dict": copy.deepcopy(dict(state_dict)),
    }


def publish_snapshot(path: Path, *, state_dict: Mapping[str, object],
                     contract: Mapping[str, object]) -> dict:
    """Publish and reopen one immutable checkpoint without overwriting."""
    torch = _require_torch()
    path = path.resolve()
    partial = Path(str(path) + ".partial")
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.path.lexists(path) or os.path.lexists(partial):
        raise StageCTrainingError("refusing existing Stage-C snapshot/partial")
    payload = _snapshot_payload(state_dict=state_dict, contract=contract)
    try:
        with partial.open("xb") as handle:
            torch.save(payload, handle)
            handle.flush()
            os.fsync(handle.fileno())
        # Hard-link publication is atomic and fails if another publisher wins
        # the destination race.  Unlike os.replace(), it can never overwrite
        # an evidence file created after the preexistence check.
        try:
            os.link(partial, path, follow_symlinks=False)
        except FileExistsError as exc:
            raise StageCTrainingError(
                "refusing raced Stage-C snapshot publication") from exc
        partial.unlink()
    except BaseException:
        # Preserve a partial as a loud failed publication marker when bytes may
        # have reached disk. A later controller must choose a fresh namespace.
        raise
    reopened = load_snapshot(path, expected_contract=contract)
    return {
        "path": str(path),
        "file_sha256": MODEL.sha256_bytes(path.read_bytes()),
        "model_state_sha256": reopened["model_state_sha256"],
        "contract": dict(contract),
    }


def load_snapshot(path: Path, *, expected_contract: Mapping[str, object]
                  ) -> dict:
    torch = _require_torch()
    path = path.resolve()
    if not path.is_file() or path.is_symlink() or path.stat().st_nlink != 1:
        raise StageCTrainingError("Stage-C snapshot is not regular/unlinked")
    try:
        payload = torch.load(path, map_location="cpu", weights_only=True)
    except Exception as exc:
        raise StageCTrainingError("Stage-C snapshot failed to reopen") from exc
    if (not isinstance(payload, dict)
            or set(payload) != {
                "schema", "contract", "model_state_sha256", "state_dict"}
            or payload.get("schema") != SNAPSHOT_SCHEMA
            or payload.get("contract") != dict(expected_contract)
            or not isinstance(payload.get("state_dict"), dict)
            or payload.get("model_state_sha256")
            != state_digest(payload["state_dict"])
            or payload["contract"].get("state_dict_sha256")
            != payload.get("model_state_sha256")):
        raise StageCTrainingError("Stage-C snapshot identity drift")
    net = MODEL.StageCRankingOutcomeNet(hidden=HIDDEN)
    try:
        net.load_state_dict(payload["state_dict"], strict=True)
    except Exception as exc:
        raise StageCTrainingError("Stage-C snapshot architecture drift") from exc
    if state_digest(net.state_dict()) != payload["model_state_sha256"]:
        raise StageCTrainingError("Stage-C reopened model-state drift")
    return payload
