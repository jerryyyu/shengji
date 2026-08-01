"""Q(obs, action) scoring model (RL_PLAN.md Phases 2-3). Requires torch
(`uv sync --group rl`)."""

from __future__ import annotations

from .encode import ACT_DIM, OBS_DIM

try:
    import torch
    from torch import nn
except ImportError:  # keep the package importable without the rl group
    torch = None
    nn = None


if torch is not None:

    class QNet(nn.Module):
        """MLP over concat(obs, action) -> scalar score (~0.6M params)."""

        def __init__(self, hidden: int = 512):
            super().__init__()
            self.net = nn.Sequential(
                nn.Linear(OBS_DIM + ACT_DIM, hidden), nn.ReLU(),
                nn.Linear(hidden, hidden), nn.ReLU(),
                nn.Linear(hidden, 256), nn.ReLU(),
                nn.Linear(256, 1),
            )

        def forward(self, obs: "torch.Tensor", act: "torch.Tensor"):
            return self.net(torch.cat([obs, act], dim=-1)).squeeze(-1)

        def score_candidates(self, obs_vec, action_vecs):
            """One decision: obs (OBS_DIM,), actions (K, ACT_DIM) -> (K,)."""
            with torch.no_grad():
                obs = torch.as_tensor(obs_vec, dtype=torch.float32)
                acts = torch.as_tensor(action_vecs, dtype=torch.float32)
                return self(obs.expand(len(acts), -1), acts)
