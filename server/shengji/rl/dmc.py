"""Phase 3: Deep Monte Carlo self-play training.

Actor processes play rounds with the current net (epsilon-greedy over
enumerated legal actions), recording (obs, action_encoding, terminal_return)
for every net-controlled decision. The learner (MPS) regresses
Q(obs, action) -> return from a replay buffer, checkpointing periodically;
actors pick up fresh weights on their next batch.

Round mix per actor batch: 70% pure self-play (4 net seats, all recorded),
30% vs SmartBot opponents (net seats recorded only) so the net keeps
learning to punish/avoid heuristic patterns.

Usage:
  uv run python -m shengji.rl.dmc ckpt_bc.pt ckpt_dmc.pt --minutes 60
Requires: uv sync --group rl
"""

from __future__ import annotations

import argparse
import random
import time
from pathlib import Path

from ..ai.env import play_round
from ..ai.smart import SmartBot
from ..engine.game import Game
from .actions import enumerate_actions
from .bc_generate import round_value
from .encode import ACT_DIM, OBS_DIM, encode_action, encode_obs


# ------------------------------------------------------------------ actors
class EpsGreedyNetBot(SmartBot):
    """Plays with the net; explores with probability eps; records decisions."""

    def __init__(self, net, eps: float, rng: random.Random):
        self.net = net
        self.eps = eps
        self.rng = rng
        self.records: list[tuple[list[float], list[float], int]] = []

    def decide_play(self, rnd, seat):
        actions = enumerate_actions(rnd, seat)
        obs = encode_obs(rnd, seat)
        if len(actions) == 1:
            idx = 0
        elif self.rng.random() < self.eps:
            idx = self.rng.randrange(len(actions))
        else:
            encoded = [encode_action(a, rnd) for a in actions]
            idx = int(self.net.score_candidates(obs, encoded).argmax())
        play = actions[idx]
        self.records.append((obs, encode_action(play, rnd), seat))
        return play


def eval_batch(args):
    """Worker task: quick mirrored eval of a checkpoint vs SmartBot."""
    ckpt_path, n_pairs, seed = args
    import torch
    from .model import QNet
    from .torch_policy import RLBot
    rl = RLBot.__new__(RLBot)
    rl.net = QNet()
    rl.net.load_state_dict(torch.load(ckpt_path, map_location="cpu"))
    rl.net.eval()
    wins = [0, 0]
    for s in range(n_pairs):
        for flip in (0, 1):
            sm = SmartBot()
            pol = [rl, sm, rl, sm] if flip == 0 else [sm, rl, sm, rl]
            game = Game(random.Random(seed + s))
            play_round(game, pol)
            team = 0 if flip == 0 else 1
            wins[0 if game.round is not None and
                 game.result.winner_team == team else 1] += 1
    return wins[0] / (2 * n_pairs)


def actor_batch(args):
    """Runs in a worker process: play rounds, return flat training arrays."""
    ckpt_path, n_rounds, eps, seed = args
    import numpy as np
    import torch
    from .model import QNet
    net = QNet()
    net.load_state_dict(torch.load(ckpt_path, map_location="cpu"))
    net.eval()
    rng = random.Random(seed)
    obs_l, act_l, ret_l = [], [], []
    for r in range(n_rounds):
        bot = EpsGreedyNetBot(net, eps, rng)
        selfplay = rng.random() < 0.7
        if selfplay:
            bots = [bot] * 4
        else:
            sm = SmartBot()
            bots = [bot, sm, bot, sm] if rng.random() < 0.5 else [sm, bot, sm, bot]
        game = Game(random.Random(seed * 100_000 + r))
        play_round(game, bots)
        rnd = game.round
        val = round_value(rnd.attacker_points)
        for obs, act, seat in bot.records:
            obs_l.append(obs)
            act_l.append(act)
            ret_l.append(val if rnd.is_attacker(seat) else -val)
        bot.records = []
    return (np.asarray(obs_l, dtype=np.float32),
            np.asarray(act_l, dtype=np.float32),
            np.asarray(ret_l, dtype=np.float32))


# ----------------------------------------------------------------- learner
def main() -> None:
    import multiprocessing as mp
    import numpy as np
    import torch
    from .model import QNet

    ap = argparse.ArgumentParser()
    ap.add_argument("ckpt_in")
    ap.add_argument("ckpt_out")
    ap.add_argument("--minutes", type=float, default=60)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--rounds-per-batch", type=int, default=40)
    ap.add_argument("--eps", type=float, default=0.1)
    ap.add_argument("--buffer", type=int, default=400_000)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--steps-per-cycle", type=int, default=4)
    ap.add_argument("--eval-every", type=float, default=300)  # seconds
    args = ap.parse_args()

    dev = "mps" if torch.backends.mps.is_available() else "cpu"
    net = QNet().to(dev)
    net.load_state_dict(torch.load(args.ckpt_in, map_location=dev))
    opt = torch.optim.Adam(net.parameters(), lr=args.lr)
    torch.save(net.state_dict(), args.ckpt_out)  # actors read this

    buf_obs = np.zeros((args.buffer, OBS_DIM), dtype=np.float32)
    buf_act = np.zeros((args.buffer, ACT_DIM), dtype=np.float32)
    buf_ret = np.zeros(args.buffer, dtype=np.float32)
    buf_n = 0        # filled size
    buf_i = 0        # write cursor (ring)

    ctx = mp.get_context("spawn")
    pool = ctx.Pool(args.workers)
    seed_counter = int(time.time()) % 1_000_000
    pending = []
    for _ in range(args.workers):
        seed_counter += 1
        pending.append(pool.apply_async(
            actor_batch, ((args.ckpt_out, args.rounds_per_batch, args.eps,
                           seed_counter),)))

    t_end = time.time() + args.minutes * 60
    rounds_done = 0
    steps = 0
    loss_ema = None
    next_eval = time.time() + args.eval_every
    eval_pending = None
    while time.time() < t_end:
        if eval_pending is not None and eval_pending.ready():
            print(f"[{time.strftime('%H:%M:%S')}] EVAL vs SmartBot: "
                  f"{eval_pending.get():.0%}  (rounds {rounds_done}, steps {steps})",
                  flush=True)
            eval_pending = None
        if eval_pending is None and time.time() >= next_eval:
            torch.save(net.state_dict(), args.ckpt_out)
            seed_counter += 1
            eval_pending = pool.apply_async(
                eval_batch, ((args.ckpt_out, 15, seed_counter * 7),))
            next_eval = time.time() + args.eval_every
        # harvest finished actors, resubmit with latest weights
        still = []
        for p in pending:
            if p.ready():
                obs, act, ret = p.get()
                for j in range(len(obs)):
                    buf_obs[buf_i] = obs[j]
                    buf_act[buf_i] = act[j]
                    buf_ret[buf_i] = ret[j]
                    buf_i = (buf_i + 1) % args.buffer
                    buf_n = min(buf_n + 1, args.buffer)
                rounds_done += args.rounds_per_batch
                seed_counter += 1
                still.append(pool.apply_async(
                    actor_batch, ((args.ckpt_out, args.rounds_per_batch,
                                   args.eps, seed_counter),)))
            else:
                still.append(p)
        pending = still

        if buf_n < 5000:
            time.sleep(0.5)
            continue
        for _ in range(args.steps_per_cycle):  # train steps per harvest cycle
            idx = np.random.randint(0, buf_n, size=1024)
            o = torch.as_tensor(buf_obs[idx], device=dev)
            a = torch.as_tensor(buf_act[idx], device=dev)
            g = torch.as_tensor(buf_ret[idx], device=dev)
            q = net(o, a)
            loss = torch.nn.functional.mse_loss(q, g)
            opt.zero_grad()
            loss.backward()
            opt.step()
            steps += 1
            loss_ema = loss.item() if loss_ema is None else \
                0.99 * loss_ema + 0.01 * loss.item()
        if steps % 400 < 8:
            torch.save(net.state_dict(), args.ckpt_out)
            print(f"[{time.strftime('%H:%M:%S')}] rounds {rounds_done}, "
                  f"steps {steps}, buffer {buf_n}, loss_ema {loss_ema:.3f}",
                  flush=True)

    torch.save(net.state_dict(), args.ckpt_out)
    stamp = Path(args.ckpt_out).with_suffix(f".{int(time.time())}.pt")
    torch.save(net.state_dict(), stamp)
    pool.terminate()
    print(f"done: {rounds_done} rounds, {steps} steps -> {args.ckpt_out} "
          f"(+ {stamp.name})")


if __name__ == "__main__":
    main()
