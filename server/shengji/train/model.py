"""Model v0: trunk MLP 531 -> 512 -> 256 (GELU, dropout 0.1); value head
256 -> 64 -> 1 (Huber, delta 1); prior head per candidate
concat(trunk embedding, action features 60) -> 128 -> 1 logit, softmax over
the record's ballot only (candidates outside the ballot get exactly zero
probability); loss = value + prior_weight * prior cross-entropy.
"""

from __future__ import annotations

import torch
from torch import nn
from torch.nn import functional as F

from ..rl.encode import ACT_DIM, OBS_DIM

MODEL_SCHEMA = "shengji-train-v0-model-v1"
DEFAULT_ARCH = {
    "obs_dim": OBS_DIM,
    "act_dim": ACT_DIM,
    "trunk": [512, 256],
    "value_hidden": 64,
    "prior_hidden": 128,
    "dropout": 0.1,
    "aux_points": False,
}


class ValuePriorNet(nn.Module):
    def __init__(self, arch: dict | None = None):
        super().__init__()
        arch = {**DEFAULT_ARCH, **(arch or {})}
        self.arch = arch
        layers: list[nn.Module] = []
        width = int(arch["obs_dim"])
        for hidden in arch["trunk"]:
            layers += [nn.Linear(width, int(hidden)), nn.GELU(), nn.Dropout(float(arch["dropout"]))]
            width = int(hidden)
        self.trunk = nn.Sequential(*layers)
        self.embed_dim = width
        outputs = 2 if arch["aux_points"] else 1
        self.value_head = nn.Sequential(
            nn.Linear(width, int(arch["value_hidden"])), nn.GELU(),
            nn.Linear(int(arch["value_hidden"]), outputs))
        self.prior_head = nn.Sequential(
            nn.Linear(width + int(arch["act_dim"]), int(arch["prior_hidden"])), nn.GELU(),
            nn.Linear(int(arch["prior_hidden"]), 1))

    def forward(self, obs: torch.Tensor, cand: torch.Tensor, mask: torch.Tensor
                ) -> tuple[torch.Tensor, torch.Tensor | None, torch.Tensor]:
        """``(value [B], aux points [B] | None, masked logits [B, K])``;
        masked logits are ``-inf`` outside the ballot."""
        emb = self.trunk(obs)
        head = self.value_head(emb)
        value = head[:, 0]
        aux = head[:, 1] if head.shape[1] > 1 else None
        k = cand.shape[1]
        joined = torch.cat([emb.unsqueeze(1).expand(-1, k, -1), cand], dim=2)
        logits = self.prior_head(joined).squeeze(2)
        logits = logits.masked_fill(~mask, float("-inf"))
        return value, aux, logits


def prior_log_probs(logits: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
    """Log-probabilities over the ballot; ``-inf`` outside it."""
    logits = logits.masked_fill(~mask, float("-inf"))
    return F.log_softmax(logits, dim=1)


def prior_distribution(logits: torch.Tensor, mask: torch.Tensor) -> torch.Tensor:
    """Probabilities over the ballot; EXACTLY zero outside it."""
    probs = torch.softmax(logits.masked_fill(~mask, float("-inf")), dim=1)
    return torch.where(mask, probs, torch.zeros_like(probs))


def prior_cross_entropy(logits: torch.Tensor, mask: torch.Tensor,
                        target: torch.Tensor) -> torch.Tensor:
    """Soft-label cross-entropy per record, masked to the ballot: the target
    carries no mass outside the ballot and none is scored there."""
    logp = prior_log_probs(logits, mask)
    terms = torch.where(mask, target * logp, torch.zeros_like(logp))
    return -terms.sum(dim=1)


def value_loss(pred: torch.Tensor, target: torch.Tensor, delta: float = 1.0) -> torch.Tensor:
    return F.huber_loss(pred, target, delta=delta, reduction="none")


def batch_losses(model: ValuePriorNet, batch: dict[str, torch.Tensor], *,
                 prior_weight: float, aux_weight: float = 0.0,
                 huber_delta: float = 1.0) -> dict[str, torch.Tensor]:
    """Loss terms of one batch (means over the rows that carry each target)."""
    value, aux, logits = model(batch["obs"], batch["cand"], batch["mask"])
    v_loss = value_loss(value, batch["utility"], huber_delta).mean()
    ce = prior_cross_entropy(logits, batch["mask"], batch["target"])
    has = batch["has_softmax"]
    n_prior = int(has.sum().item())
    p_loss = (ce[has].sum() / n_prior) if n_prior else value.new_zeros(())
    total = v_loss + prior_weight * p_loss
    out = {"total": total, "value": v_loss, "prior": p_loss,
           "n_prior": value.new_tensor(float(n_prior))}
    if aux is not None and aux_weight > 0:
        a_loss = value_loss(aux, batch["attacker_points"] / 100.0, huber_delta).mean()
        out["aux"] = a_loss
        out["total"] = total + aux_weight * a_loss
    return out
