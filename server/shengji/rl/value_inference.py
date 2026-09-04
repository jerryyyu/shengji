"""Inference-only adapters for state values and engine-applied root actions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np
import torch

from ..engine.round import Round
from .value_afterstate import (
    OUTCOME_CLASSES,
    ValueAfterstateTensors,
    apply_action,
    terminal_distribution,
    tensors_from_round,
)
from .value_metrics import expected_signed_level
from .value_model import ValueNetwork
from .value_training import collate_tensors


class ValueInferenceError(ValueError):
    """An inference request or model output drifted."""


@dataclass(frozen=True)
class ValuePrediction:
    probability: tuple[float, ...]
    expected_signed_level: float

    def validate(self) -> None:
        values = np.asarray(self.probability, dtype=np.float64)
        if values.shape != (OUTCOME_CLASSES,) \
                or not bool(np.all(np.isfinite(values))) \
                or bool(np.any(values < 0.0)) \
                or not np.isclose(float(values.sum()), 1.0, rtol=0.0, atol=1e-6) \
                or not np.isclose(
                    self.expected_signed_level,
                    expected_signed_level(self.probability), rtol=0.0, atol=1e-7):
            raise ValueInferenceError("prediction distribution drift")


@dataclass(frozen=True)
class ScoredAction:
    submitted_action: tuple[str, ...]
    engine_action: tuple[str, ...]
    prediction: ValuePrediction


def _prediction(probability: np.ndarray) -> ValuePrediction:
    values = tuple(float(value) for value in probability)
    result = ValuePrediction(values, expected_signed_level(values))
    result.validate()
    return result


@torch.inference_mode()
def predict_tensors(model: ValueNetwork,
                    rows: Sequence[ValueAfterstateTensors], *,
                    device: torch.device | str = "cpu") -> tuple[ValuePrediction, ...]:
    if not rows:
        raise ValueInferenceError("inference population is empty")
    model.to(device)
    model.eval()
    batch = collate_tensors(rows).to(device)
    logits = model(batch.public, batch.history, batch.history_mask,
                   batch.world, batch.perspective)
    if logits.shape != (len(rows), OUTCOME_CLASSES) \
            or not bool(torch.all(torch.isfinite(logits))):
        raise ValueInferenceError("model logits drift")
    probabilities = torch.softmax(logits, dim=1).cpu().numpy()
    return tuple(_prediction(row) for row in probabilities)


def predict_round(model: ValueNetwork, rnd: Round, root_seat: int, *,
                  device: torch.device | str = "cpu") -> ValuePrediction:
    """Value a complete leaf; terminal states bypass the model exactly."""
    if type(rnd) is Round and rnd.phase == "round_end":
        return _prediction(terminal_distribution(rnd, root_seat))
    return predict_tensors(
        model, [tensors_from_round(rnd, root_seat)], device=device)[0]


def score_actions(model: ValueNetwork, rnd: Round, root_seat: int,
                  actions: Sequence[Sequence[str]], *,
                  device: torch.device | str = "cpu") -> tuple[ScoredAction, ...]:
    """Apply each candidate through the engine and value the reached state.

    This helper does not choose an action or register a policy.  A future
    search may aggregate these values across belief worlds under its own
    separately reviewed consumer contract.
    """
    if not actions:
        raise ValueInferenceError("action population is empty")
    successors: list[Round] = []
    accepted: list[tuple[str, ...]] = []
    for action in actions:
        successor, engine_action = apply_action(rnd, root_seat, action)
        successors.append(successor)
        accepted.append(engine_action)
    predictions: list[ValuePrediction | None] = [None] * len(actions)
    pending_indices = [
        index for index, successor in enumerate(successors)
        if successor.phase != "round_end"]
    if pending_indices:
        pending = predict_tensors(
            model,
            [tensors_from_round(successors[index], root_seat)
             for index in pending_indices], device=device)
        for index, prediction in zip(pending_indices, pending, strict=True):
            predictions[index] = prediction
    for index, successor in enumerate(successors):
        if successor.phase == "round_end":
            predictions[index] = _prediction(
                terminal_distribution(successor, root_seat))
    if any(prediction is None for prediction in predictions):
        raise ValueInferenceError("action prediction population is incomplete")
    return tuple(ScoredAction(
        tuple(action), accepted[index], prediction)
        for index, (action, prediction) in enumerate(
            zip(actions, predictions, strict=True)))
