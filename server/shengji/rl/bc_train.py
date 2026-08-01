"""Phase 2 behavior cloning: imitate SmartBot from bc_generate shards.

Usage:  uv run python -m shengji.rl.bc_train <data_dir> <ckpt_out> [epochs]
Cross-entropy over softmax of candidate scores (chosen action = label).
Uses MPS when available. Requires: uv sync --group rl
"""

from __future__ import annotations

import sys
from pathlib import Path


def main() -> None:
    import numpy as np
    import torch
    from torch import nn
    from .model import QNet, QNetDueling

    data_dir, ckpt_out = sys.argv[1], sys.argv[2]
    epochs = int(sys.argv[3]) if len(sys.argv) > 3 else 3
    arch = sys.argv[4] if len(sys.argv) > 4 else "qnet"
    dev = "mps" if torch.backends.mps.is_available() else "cpu"
    net = (QNetDueling() if arch == "dueling" else QNet()).to(dev)
    print(f"architecture: {type(net).__name__}", flush=True)
    opt = torch.optim.Adam(net.parameters(), lr=1e-3)
    shards = sorted(Path(data_dir).glob("shard_*.npz"))
    assert shards, f"no shards in {data_dir}"
    print(f"{len(shards)} shards, device={dev}")

    for epoch in range(epochs):
        total = correct = 0
        loss_sum = 0.0
        for shard in shards:
            z = np.load(shard)
            obs, acts = z["obs"], z["actions"]
            offsets, chosen = z["offsets"], z["chosen"]
            for i in range(0, len(obs), 512):
                batch = range(i, min(i + 512, len(obs)))
                losses = []
                for j in batch:
                    a = torch.as_tensor(acts[offsets[j]:offsets[j + 1]],
                                        device=dev)
                    o = torch.as_tensor(obs[j], device=dev).expand(len(a), -1)
                    scores = net(o, a)
                    target = torch.as_tensor(int(chosen[j]), device=dev)
                    losses.append(nn.functional.cross_entropy(
                        scores.unsqueeze(0), target.unsqueeze(0)))
                    total += 1
                    correct += int(scores.argmax().item() == int(chosen[j]))
                loss = torch.stack(losses).mean()
                opt.zero_grad()
                loss.backward()
                opt.step()
                loss_sum += loss.item()
        print(f"epoch {epoch}: loss {loss_sum:.1f}, "
              f"imitation acc {correct/total:.1%}", flush=True)
        torch.save(net.state_dict(), ckpt_out)
    print(f"saved {ckpt_out}")


if __name__ == "__main__":
    main()
