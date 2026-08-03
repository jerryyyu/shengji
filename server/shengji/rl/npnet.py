"""Dependency-light inference for the trained nets (production path).

The trained net is four matrix multiplies (~485k params): trunk
531->512->256, then a head 316->256->1. Torch is a ~800MB dependency to
evaluate that, so production loads exported numpy weights instead —
the container stays small and starts fast, and prod never needs a
GPU/MPS runtime.

Export:  uv run python -m shengji.rl.npnet export <ckpt.pt> <out.npz>
Parity is asserted by tests/test_npnet_parity.py against torch.
"""

from __future__ import annotations

import sys

import numpy as np


class NpNet:
    """Numpy mirror of PolicyValueNet (same weights, same arithmetic)."""

    def __init__(self, path: str):
        z = np.load(path)
        self.w = {k: z[k].astype(np.float32) for k in z.files}

    @staticmethod
    def _lin(x, w, b):
        return x @ w.T + b

    def _trunk(self, obs):
        h = np.maximum(self._lin(obs, self.w["t0w"], self.w["t0b"]), 0.0)
        return np.maximum(self._lin(h, self.w["t2w"], self.w["t2b"]), 0.0)

    def _head(self, feat, acts, p):
        fa = np.concatenate(
            [np.repeat(feat[None, :], len(acts), 0), acts], axis=-1)
        h = np.maximum(self._lin(fa, self.w[p + "0w"], self.w[p + "0b"]), 0.0)
        return self._lin(h, self.w[p + "2w"], self.w[p + "2b"]).squeeze(-1)

    def score_candidates(self, obs_vec, action_vecs):
        """Policy logits — the play-time decision (RLBot)."""
        return self._head(self._trunk(np.asarray(obs_vec, np.float32)),
                          np.asarray(action_vecs, np.float32), "p")

    def value_candidates(self, obs_vec, action_vecs):
        """Value head — leaf evaluation for the mc-vleaf hybrid."""
        return self._head(self._trunk(np.asarray(obs_vec, np.float32)),
                          np.asarray(action_vecs, np.float32), "q")


def export(ckpt: str, out: str) -> None:
    import torch
    sd = torch.load(ckpt, map_location="cpu")
    m = {"trunk.0": "t0", "trunk.2": "t2", "q_head.0": "q0", "q_head.2": "q2",
         "p_head.0": "p0", "p_head.2": "p2"}
    w = {}
    for k, v in sd.items():
        base, kind = k.rsplit(".", 1)
        if base in m:
            w[m[base] + ("w" if kind == "weight" else "b")] = v.numpy()
    np.savez_compressed(out, **w)
    print(f"exported {len(w)} arrays -> {out}")


if __name__ == "__main__":
    if sys.argv[1] == "export":
        export(sys.argv[2], sys.argv[3])
