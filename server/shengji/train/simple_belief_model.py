"""Small ownership-count belief model and masked categorical objectives."""

from __future__ import annotations

import torch
from torch import nn
from torch.nn import functional as F


_OUTPUT_SHAPE = (4, 54, 3)


class SimpleBeliefMLP(nn.Module):
    """Feed-forward model returning per-seat, per-card count logits."""

    def __init__(self, input_dim: int, width: int = 256,
                 hidden: int = 128) -> None:
        super().__init__()
        if type(input_dim) is not int or input_dim <= 0:
            raise ValueError("input_dim must be a positive integer")
        if type(width) is not int or width <= 0:
            raise ValueError("width must be a positive integer")
        if type(hidden) is not int or hidden <= 0:
            raise ValueError("hidden must be a positive integer")
        self.input_dim = input_dim
        self.width = width
        self.hidden = hidden
        self.net = nn.Sequential(
            nn.Linear(input_dim, width),
            nn.ReLU(),
            nn.Linear(width, hidden),
            nn.ReLU(),
            nn.Linear(hidden, 4 * 54 * 3),
        )

    def forward(self, features: torch.Tensor) -> torch.Tensor:
        if not isinstance(features, torch.Tensor):
            raise ValueError("features must be a tensor")
        if features.ndim != 2 or features.shape[1] != self.input_dim:
            raise ValueError(
                f"features must have shape (batch, {self.input_dim})")
        if features.shape[0] == 0:
            raise ValueError("features batch must not be empty")
        if not features.is_floating_point():
            raise ValueError("features must be floating point")
        if not bool(torch.isfinite(features).all()):
            raise ValueError("features must be finite")
        return self.net(features).reshape(features.shape[0], *_OUTPUT_SHAPE)


def _validate_logits(logits: torch.Tensor) -> None:
    if not isinstance(logits, torch.Tensor):
        raise ValueError("logits must be a tensor")
    if logits.ndim != 4 or tuple(logits.shape[1:]) != _OUTPUT_SHAPE:
        raise ValueError("logits must have shape (batch, 4, 54, 3)")
    if logits.shape[0] == 0:
        raise ValueError("logits batch must not be empty")
    if not logits.is_floating_point():
        raise ValueError("logits must be floating point")
    if not bool(torch.isfinite(logits).all()):
        raise ValueError("logits must be finite")


def _validate_allowed(logits: torch.Tensor, allowed: torch.Tensor) -> None:
    if not isinstance(allowed, torch.Tensor) or allowed.dtype != torch.bool:
        raise ValueError("allowed must be a boolean tensor")
    if allowed.shape != logits.shape:
        raise ValueError("allowed must have the same shape as logits")
    if allowed.device != logits.device:
        raise ValueError("allowed and logits must be on the same device")
    if not bool(allowed.any(dim=-1).all()):
        raise ValueError("each count cell needs at least one allowed class")


def _validate_mask_inputs(logits: torch.Tensor,
                          allowed: torch.Tensor) -> None:
    _validate_logits(logits)
    _validate_allowed(logits, allowed)


def masked_count_probabilities(logits: torch.Tensor,
                               allowed: torch.Tensor) -> torch.Tensor:
    """Convert masked count logits to normalized per-cell probabilities."""
    _validate_mask_inputs(logits, allowed)
    floor = torch.finfo(logits.dtype).min
    masked = logits.masked_fill(~allowed, floor)
    probabilities = F.softmax(masked, dim=-1).masked_fill(~allowed, 0)
    return probabilities / probabilities.sum(dim=-1, keepdim=True)


def masked_count_loss(logits: torch.Tensor, targets: torch.Tensor,
                      allowed: torch.Tensor) -> torch.Tensor:
    """Cross-entropy over uncertain cells, excluding known cells."""
    _validate_mask_inputs(logits, allowed)
    if not isinstance(targets, torch.Tensor) or targets.dtype != torch.int64:
        raise ValueError("targets must be an int64 tensor")
    if targets.shape != logits.shape[:-1]:
        raise ValueError("targets must have shape (batch, 4, 54)")
    if targets.device != logits.device:
        raise ValueError("targets and logits must be on the same device")
    if bool(((targets < 0) | (targets >= 3)).any()):
        raise ValueError("targets contain an out-of-range class")
    target_allowed = allowed.gather(-1, targets.unsqueeze(-1)).squeeze(-1)
    if not bool(target_allowed.all()):
        raise ValueError("targets contain a forbidden class")

    uncertain = allowed.sum(dim=-1) > 1
    if not bool(uncertain.any()):
        # Preserve the graph while producing an exact differentiable zero.
        return logits.sum() * 0.0

    floor = torch.finfo(logits.dtype).min
    masked = logits.masked_fill(~allowed, floor)
    losses = F.cross_entropy(
        masked.reshape(-1, 3), targets.reshape(-1), reduction="none")
    losses = losses.reshape(logits.shape[:-1])
    return losses[uncertain].mean()
