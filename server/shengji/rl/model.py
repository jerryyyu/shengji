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

    class QNetDueling(nn.Module):
        """Q(s,a) = V(s) + A(s,a), A mean-zero across each decision's
        candidates — value-scale learning cannot crush action ranking.
        (Recipe v2 architecture; also used by the distillation trainer.)"""

        def __init__(self, hidden: int = 512):
            super().__init__()
            self.trunk = nn.Sequential(
                nn.Linear(OBS_DIM, hidden), nn.ReLU(),
                nn.Linear(hidden, 256), nn.ReLU(),
            )
            self.v_head = nn.Linear(256, 1)
            self.a_head = nn.Sequential(
                nn.Linear(256 + ACT_DIM, 256), nn.ReLU(),
                nn.Linear(256, 1),
            )

        def q_grouped(self, obs_dec, act_rows, seg, n_dec):
            """obs_dec: (D, OBS_DIM) one row per decision; act_rows:
            (R, ACT_DIM); seg: (R,) decision index per row. Returns
            (Q rows (R,), V (D,), A rows (R,))."""
            feat = self.trunk(obs_dec)
            v = self.v_head(feat).squeeze(-1)
            raw = self.a_head(
                torch.cat([feat[seg], act_rows], dim=-1)).squeeze(-1)
            counts = torch.zeros(n_dec, device=raw.device).index_add_(
                0, seg, torch.ones_like(raw))
            mean = torch.zeros(n_dec, device=raw.device).index_add_(
                0, seg, raw) / counts.clamp(min=1)
            a = raw - mean[seg]
            return v[seg] + a, v, a

        def score_candidates(self, obs_vec, action_vecs):
            with torch.no_grad():
                obs = torch.as_tensor(obs_vec, dtype=torch.float32).unsqueeze(0)
                acts = torch.as_tensor(action_vecs, dtype=torch.float32)
                seg = torch.zeros(len(acts), dtype=torch.long)
                q, _, _ = self.q_grouped(obs, acts, seg, 1)
                return q
