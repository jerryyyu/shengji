"""Model v0: trunk MLP 531 -> 512 -> 256 (GELU, dropout 0.1); value head
256 -> 64 -> 1 (Huber, delta 1); prior head per candidate
concat(trunk embedding, action features 60) -> 128 -> 1 logit, softmax over
the record's ballot only (candidates outside the ballot get exactly zero
probability); loss = value + prior_weight * prior cross-entropy
[+ aux_search_mean * Huber(search head, search mean / 100)].

Auxiliary search-mean head (``arch["aux_search_mean"]``): a second
regression head on the trunk, 256 -> 64 -> 1, predicting the search's own
estimate for the played action (``data.py``: ``action_values.means
[played_index]``, acting-team perspective, points scale) divided by
``SEARCH_MEAN_SCALE`` so that Huber delta 1 covers the +-2 range; the term
is averaged over the rows that carry the target and weighted into the
total.  Predictions are reported back in points.  ``arch["trunk"]`` is
``[hidden, hidden // 2]`` for ``--hidden`` (default 512 -> [512, 256]).
"""

from __future__ import annotations

from typing import NamedTuple

import torch
from torch import nn
from torch.nn import functional as F

from ..rl.encode import ACT_DIM, OBS_DIM

MODEL_SCHEMA = "shengji-train-v0-model-v1"
DEFAULT_HIDDEN = 512
DEFAULT_ARCH = {
    "obs_dim": OBS_DIM,
    "act_dim": ACT_DIM,
    "trunk": [DEFAULT_HIDDEN, DEFAULT_HIDDEN // 2],
    "value_hidden": 64,
    "prior_hidden": 128,
    "dropout": 0.1,
    "aux_points": False,
    "aux_search_mean": False,
}
#: the aux search-mean target is trained as ``points / SEARCH_MEAN_SCALE``
SEARCH_MEAN_SCALE = 100.0


def trunk_for(hidden: int) -> list[int]:
    hidden = int(hidden)
    if hidden < 2:
        raise ValueError("hidden width must be at least 2")
    return [hidden, hidden // 2]


class Outputs(NamedTuple):
    value: torch.Tensor           # [B]
    aux: torch.Tensor | None      # [B] attacker points / 100, or None
    logits: torch.Tensor          # [B, K], -inf outside the ballot
    search: torch.Tensor | None   # [B] search mean / SEARCH_MEAN_SCALE, or None


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
        self.search_head = (nn.Sequential(
            nn.Linear(width, int(arch["value_hidden"])), nn.GELU(),
            nn.Linear(int(arch["value_hidden"]), 1))
            if arch["aux_search_mean"] else None)

    def forward(self, obs: torch.Tensor, cand: torch.Tensor, mask: torch.Tensor) -> Outputs:
        """``Outputs(value [B], aux points [B] | None, masked logits [B, K],
        search mean [B] | None)``; masked logits are ``-inf`` outside the
        ballot."""
        emb = self.trunk(obs)
        head = self.value_head(emb)
        value = head[:, 0]
        aux = head[:, 1] if head.shape[1] > 1 else None
        k = cand.shape[1]
        joined = torch.cat([emb.unsqueeze(1).expand(-1, k, -1), cand], dim=2)
        logits = self.prior_head(joined).squeeze(2)
        logits = logits.masked_fill(~mask, float("-inf"))
        search = self.search_head(emb).squeeze(1) if self.search_head is not None else None
        return Outputs(value, aux, logits, search)


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
                 search_weight: float = 0.0, huber_delta: float = 1.0
                 ) -> dict[str, torch.Tensor]:
    """Loss terms of one batch (means over the rows that carry each target).

    ``search_weight`` > 0 adds ``search_weight * Huber(search head, search
    mean / SEARCH_MEAN_SCALE)`` over the rows with ``has_search_mean`` (the
    model must have the head); ``n_search`` counts those rows."""
    out_model = model(batch["obs"], batch["cand"], batch["mask"])
    value, aux, logits, search = out_model
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
        total = total + aux_weight * a_loss
    if search_weight > 0:
        if search is None:
            raise ValueError("search_weight > 0 needs arch['aux_search_mean']")
        has_s = batch["has_search_mean"]
        n_search = int(has_s.sum().item())
        s_loss = (value_loss(search[has_s], batch["search_mean"][has_s] / SEARCH_MEAN_SCALE,
                             huber_delta).mean() if n_search else value.new_zeros(()))
        out["search"] = s_loss
        out["n_search"] = value.new_tensor(float(n_search))
        total = total + search_weight * s_loss
    out["total"] = total
    return out
