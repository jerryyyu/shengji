"""Oracle value baseline (Suphx-style, RL_PLAN Step 2 item).

V_oracle sees ALL FOUR HANDS (training-time only — we are the simulator)
and predicts the round's final bracket value from any mid-round state.
Used in DMC v2 as the advantage baseline: target = return − V_oracle,
which subtracts deal luck from the learning signal.

This module is self-contained: oracle encoding, data generation
(heuristic self-play, states sampled at each trick start), training, and
a validation report of VARIANCE EXPLAINED — the number that justifies
(or kills) the whole idea.

Usage:
  uv run python -m shengji.rl.oracle gen  rl_data/oracle 20000
  uv run python -m shengji.rl.oracle train rl_data/oracle ckpt_oracle.pt
"""

from __future__ import annotations

import random
import sys
import time

from ..ai.env import play_round
from ..ai.heuristic import HeuristicBot
from ..engine.cards import RANKS, SUITS
from ..engine.game import Game
from ..engine.round import Round
from .bc_generate import round_value
from .encode import N_CARDS, _counts

# hands of all 4 seats (banker-relative) + current-trick plays (3) +
# trump suit/rank + points + cards remaining
ORACLE_DIM = N_CARDS * 7 + 5 + 13 + 1 + 1


def encode_oracle(rnd: Round) -> list[float]:
    """Full-information state, banker-relative, attacker-perspective target."""
    assert rnd.ordering is not None and rnd.banker is not None
    obs: list[float] = []
    for rel in range(4):
        obs += _counts(rnd.hands[(rnd.banker + rel) % 4])
    trick_planes = [[0.0] * N_CARDS for _ in range(3)]
    if rnd.trick is not None:
        for i, tp in enumerate(rnd.trick.plays[:3]):
            trick_planes[i] = _counts(tp.cards)
    for plane in trick_planes:
        obs += plane
    suit_onehot = [0.0] * 5
    if rnd.trump_is_nt:
        suit_onehot[4] = 1.0
    elif rnd.trump_suit in SUITS:
        suit_onehot[SUITS.index(rnd.trump_suit)] = 1.0
    obs += suit_onehot
    rank_onehot = [0.0] * 13
    rank_onehot[RANKS.index(rnd.trump_rank)] = 1.0
    obs += rank_onehot
    obs.append(min(rnd.attacker_points, 200) / 200.0)
    obs.append(sum(len(h) for h in rnd.hands) / 100.0)
    assert len(obs) == ORACLE_DIM
    return obs


class RecordingHeuristic(HeuristicBot):
    """Records the oracle state at the start of every trick."""

    def __init__(self):
        self.states: list[list[float]] = []

    def decide_play(self, rnd, seat):
        if rnd.trick is not None and not rnd.trick.plays:
            self.states.append(encode_oracle(rnd))
        return super().decide_play(rnd, seat)


def gen(out_dir: str, n_rounds: int) -> None:
    import numpy as np
    bot = RecordingHeuristic()
    bots = [bot] * 4
    xs, ys = [], []
    seed = 0
    t0 = time.time()
    done = 0
    while done < n_rounds:
        game = Game(random.Random(seed))
        seed += 1
        while not game.game_over and done < n_rounds:
            bot.states = []
            play_round(game, bots)
            val = round_value(game.round.attacker_points)
            xs.extend(bot.states)
            ys.extend([val] * len(bot.states))
            done += 1
    from pathlib import Path
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    np.savez_compressed(f"{out_dir}/oracle_data.npz",
                        x=np.asarray(xs, dtype=np.float32),
                        y=np.asarray(ys, dtype=np.float32))
    print(f"{len(xs)} states from {done} rounds in {time.time()-t0:.0f}s "
          f"-> {out_dir}/oracle_data.npz")


def train(data_dir: str, ckpt_out: str, epochs: int = 4) -> None:
    import numpy as np
    import torch
    from torch import nn
    z = np.load(f"{data_dir}/oracle_data.npz")
    x, y = z["x"], z["y"]
    n_val = len(x) // 10
    xv, yv = x[:n_val], y[:n_val]
    xt, yt = x[n_val:], y[n_val:]
    dev = "mps" if torch.backends.mps.is_available() else "cpu"
    net = nn.Sequential(nn.Linear(ORACLE_DIM, 512), nn.ReLU(),
                        nn.Linear(512, 256), nn.ReLU(),
                        nn.Linear(256, 1)).to(dev)
    # weight decay + save-best early stopping: the un-regularized version
    # peaked at epoch 0 (47% variance explained) and degraded after
    opt = torch.optim.AdamW(net.parameters(), lr=1e-3, weight_decay=1e-4)
    var_y = float(np.var(yv))
    best_mse = float("inf")
    stale = 0
    for epoch in range(epochs):
        perm = np.random.permutation(len(xt))
        for i in range(0, len(xt), 2048):
            idx = perm[i:i + 2048]
            xb = torch.as_tensor(xt[idx], device=dev)
            yb = torch.as_tensor(yt[idx], device=dev)
            loss = nn.functional.mse_loss(net(xb).squeeze(-1), yb)
            opt.zero_grad()
            loss.backward()
            opt.step()
        with torch.no_grad():
            pv = net(torch.as_tensor(xv, device=dev)).squeeze(-1).cpu().numpy()
        mse = float(np.mean((pv - yv) ** 2))
        marker = ""
        if mse < best_mse:
            best_mse = mse
            stale = 0
            torch.save(net.state_dict(), ckpt_out)
            marker = "  <- saved"
        else:
            stale += 1
        print(f"epoch {epoch}: val MSE {mse:.3f} vs outcome variance "
              f"{var_y:.3f} -> variance explained {1 - mse/var_y:.0%}{marker}",
              flush=True)
        if stale >= 2:
            print("early stop (no val improvement for 2 epochs)")
            break
    print(f"best: variance explained {1 - best_mse/var_y:.0%} -> {ckpt_out}")


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "gen":
        gen(sys.argv[2], int(sys.argv[3]))
    else:
        train(sys.argv[2], sys.argv[3])
