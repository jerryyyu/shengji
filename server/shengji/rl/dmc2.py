"""DMC recipe v2 (RL_PLAN Step 2): anchored, oracle-baselined, gated
self-play. Implements the 13-point spec.

Key differences vs v1 (`dmc.py`):
- QNetDueling student warm-started from a distilled/BC checkpoint; a FROZEN
  copy serves as the anchor reference.
- Actors record obs + ALL candidate encodings + chosen idx + oracle obs;
  forced single-candidate decisions are skipped (no action signal).
- Targets: advantage = round_value − V_oracle(full-information state),
  computed at ingestion with the frozen oracle (buffer stores scalars).
- Loss: MSE(Q_chosen, advantage) + w(t)·KL(student‖anchor) over candidate
  sets, with w annealed to zero.
- Gating: the learner's candidate checkpoint must beat the current
  GENERATOR checkpoint ≥55% on mirrored deals before actors adopt it.
- Opponent pool: 80% latest generator / 20% {past promoted ckpts, SmartBot}.
- Epsilon annealed 0.15 → 0.05; replay-ratio cap; spread-collapse alarm;
  periodic eval vs SmartBot; run archived to server/runs/.

Usage:
  uv run python -m shengji.rl.dmc2 ckpt_distill.pt ckpt_oracle.pt out_dir \
      --minutes 480 --workers 8
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
from .oracle import ORACLE_DIM, encode_oracle


def load_any_net(path: str):
    """Load a checkpoint as whichever architecture saved it (QNet /
    QNetDueling / PolicyValueNet) — all expose score_candidates."""
    import torch
    from .model import QNet, QNetDueling, PolicyValueNet
    state = torch.load(path, map_location="cpu")
    if any(k.startswith("p_head") for k in state):
        net = PolicyValueNet()
    elif any(k.startswith("trunk") for k in state):
        net = QNetDueling()
    else:
        net = QNet()
    net.load_state_dict(state)
    net.eval()
    return net


# ------------------------------------------------------------------ actors
class V2Actor(SmartBot):
    """Epsilon-greedy over the net; records full candidate sets + oracle
    state for every multi-candidate decision it controls."""

    def __init__(self, net, eps: float, rng: random.Random):
        self.net = net
        self.eps = eps
        self.rng = rng
        self.records: list[tuple] = []  # (obs, cand_rows, chosen, oracle_obs, seat)

    def decide_play(self, rnd, seat):
        actions = enumerate_actions(rnd, seat)
        if len(actions) == 1:
            return actions[0]
        obs = encode_obs(rnd, seat)
        encoded = [encode_action(a, rnd) for a in actions]
        if self.rng.random() < self.eps:
            idx = self.rng.randrange(len(actions))
        else:
            idx = int(self.net.score_candidates(obs, encoded).argmax())
        self.records.append((obs, encoded, idx, encode_oracle(rnd), seat))
        return actions[idx]


def actor_batch(args):
    """Worker: play rounds vs pool opponents, return decision arrays."""
    (gen_ckpt, pool_ckpts, n_rounds, eps, seed) = args
    import numpy as np
    import torch
    # architectures resolved via load_any_net
    rng = random.Random(seed)

    net = load_any_net(gen_ckpt)
    me = V2Actor(net, eps, rng)
    obs_l, act_rows, offs, chosen_l, orc_l, ret_l, seat_l = \
        [], [], [0], [], [], [], []
    for r in range(n_rounds):
        roll = rng.random()
        if roll < 0.8:
            bots = [me] * 4
        elif pool_ckpts and rng.random() < 0.5:
            opp = V2Actor(load_any_net(rng.choice(pool_ckpts)), 0.0, rng)
            bots = [me, opp, me, opp]
        else:
            sm = SmartBot()
            bots = [me, sm, me, sm]
        if rng.random() < 0.5:
            bots = [bots[1], bots[0], bots[3], bots[2]]
        game = Game(random.Random(seed * 50_000 + r))
        me.records = []
        play_round(game, bots)
        rnd = game.round
        val = round_value(rnd.attacker_points)
        for obs, encoded, idx, orc, seat in me.records:
            obs_l.append(obs)
            act_rows.extend(encoded)
            offs.append(offs[-1] + len(encoded))
            chosen_l.append(idx)
            orc_l.append(orc)
            ret_l.append(val if rnd.is_attacker(seat) else -val)
    return (np.asarray(obs_l, dtype=np.float32),
            np.asarray(act_rows, dtype=np.float32),
            np.asarray(offs, dtype=np.int64),
            np.asarray(chosen_l, dtype=np.int32),
            np.asarray(orc_l, dtype=np.float32),
            np.asarray(ret_l, dtype=np.float32))


def duel(args):
    """Worker: mirrored duel between two checkpoints; returns a's win rate."""
    ckpt_a, ckpt_b, n_pairs, seed = args

    def bot(path):
        return V2Actor(load_any_net(path), 0.0, random.Random(seed))

    wins = [0, 0]
    for s in range(n_pairs):
        for flip in (0, 1):
            a, b = bot(ckpt_a), bot(ckpt_b)
            pol = [a, b, a, b] if flip == 0 else [b, a, b, a]
            game = Game(random.Random(seed + s))
            play_round(game, pol)
            team = 0 if flip == 0 else 1
            wins[0 if game.result.winner_team == team else 1] += 1
    return wins[0] / (2 * n_pairs)


def eval_vs_smart(args):
    ckpt, n_pairs, seed = args
    net = load_any_net(ckpt)
    wins = [0, 0]
    for s in range(n_pairs):
        for flip in (0, 1):
            a = V2Actor(net, 0.0, random.Random(seed))
            sm = SmartBot()
            pol = [a, sm, a, sm] if flip == 0 else [sm, a, sm, a]
            game = Game(random.Random(seed + s))
            play_round(game, pol)
            team = 0 if flip == 0 else 1
            wins[0 if game.result.winner_team == team else 1] += 1
    return wins[0] / (2 * n_pairs)


# ----------------------------------------------------------------- learner
def main() -> None:
    import multiprocessing as mp
    import numpy as np
    import torch
    # architectures resolved via load_any_net
    from .oracle import ORACLE_DIM as _od  # noqa: F401
    from torch import nn

    ap = argparse.ArgumentParser()
    ap.add_argument("warm_start")
    ap.add_argument("oracle_ckpt")
    ap.add_argument("out_dir")
    ap.add_argument("--minutes", type=float, default=480)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--rounds-per-batch", type=int, default=40)
    ap.add_argument("--buffer", type=int, default=150_000)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--anchor-w0", type=float, default=1.0)
    ap.add_argument("--anchor-anneal-min", type=float, default=240)
    ap.add_argument("--eps0", type=float, default=0.15)
    ap.add_argument("--eps1", type=float, default=0.05)
    ap.add_argument("--replay-ratio", type=float, default=4.0)
    ap.add_argument("--gate-every-min", type=float, default=20)
    ap.add_argument("--eval-every-min", type=float, default=5)
    ap.add_argument("--a-scale", type=float, default=1.0,
                    help="rescale the warm start's A-head output (CE-trained "
                         "scale is arbitrary; match it to advantage-target "
                         "scale so regression needn't shrink spread)")
    args = ap.parse_args()

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    dev = "mps" if torch.backends.mps.is_available() else "cpu"

    net = load_any_net(args.warm_start).to(dev)
    net.train()
    anchor = load_any_net(args.warm_start).to(dev)
    anchor.eval()
    print(f"warm start architecture: {type(net).__name__}", flush=True)
    if args.a_scale != 1.0 and hasattr(net, "a_head"):
        with torch.no_grad():
            for m in (net, anchor):  # both, so the anchor KL target matches
                m.a_head[-1].weight *= args.a_scale
                m.a_head[-1].bias *= args.a_scale
        print(f"A-head rescaled by {args.a_scale}", flush=True)
    oracle = nn.Sequential(nn.Linear(ORACLE_DIM, 512), nn.ReLU(),
                           nn.Linear(512, 256), nn.ReLU(),
                           nn.Linear(256, 1)).to(dev)
    oracle.load_state_dict(torch.load(args.oracle_ckpt, map_location=dev))
    oracle.eval()
    opt = torch.optim.Adam(net.parameters(), lr=args.lr)

    gen_ckpt = str(out / "generator.pt")
    cand_ckpt = str(out / "candidate.pt")
    torch.save(net.state_dict(), gen_ckpt)
    torch.save(net.state_dict(), cand_ckpt)
    pool_ckpts: list[str] = []

    # ragged replay buffer (python-side, bounded by decisions)
    buf: list[tuple] = []  # (obs, act_rows, chosen, adv_target)
    buf_pos = 0
    samples_added = samples_trained = 0

    ctx = mp.get_context("spawn")
    pool = ctx.Pool(args.workers + 1)  # +1 slot for eval/gate tasks
    t0 = time.time()
    t_end = t0 + args.minutes * 60
    seed_counter = int(t0) % 1_000_000

    def eps_now():
        frac = min(1.0, (time.time() - t0) / (args.minutes * 60))
        return args.eps0 + (args.eps1 - args.eps0) * frac

    def anchor_w():
        frac = min(1.0, (time.time() - t0) / (args.anchor_anneal_min * 60))
        return args.anchor_w0 * (1.0 - frac)

    pending = []
    for _ in range(args.workers):
        seed_counter += 1
        pending.append(pool.apply_async(actor_batch, (
            (gen_ckpt, pool_ckpts[:], args.rounds_per_batch, eps_now(),
             seed_counter),)))
    eval_pending = gate_pending = None
    next_eval = t0 + args.eval_every_min * 60
    next_gate = t0 + args.gate_every_min * 60
    steps = 0
    rounds_done = 0
    loss_ema = spread_ema = None
    spread0 = None
    evals: list[str] = []

    while time.time() < t_end:
        # ---- harvest actors
        still = []
        for p in pending:
            if not p.ready():
                still.append(p)
                continue
            obs, act_rows, offs, chosen, orc, rets = p.get()
            rounds_done += args.rounds_per_batch
            with torch.no_grad():
                vo = oracle(torch.as_tensor(orc, device=dev)).squeeze(-1)
                adv = torch.as_tensor(rets, device=dev) - vo
            adv = adv.cpu().numpy()
            for i in range(len(obs)):
                a, b = offs[i], offs[i + 1]
                item = (obs[i], act_rows[a:b], int(chosen[i]), float(adv[i]))
                if len(buf) < args.buffer:
                    buf.append(item)
                else:
                    nonlocal_pos = buf_pos % args.buffer
                    buf[nonlocal_pos] = item
                buf_pos += 1
                samples_added += 1
            seed_counter += 1
            still.append(pool.apply_async(actor_batch, (
                (gen_ckpt, pool_ckpts[:], args.rounds_per_batch, eps_now(),
                 seed_counter),)))
        pending = still

        # ---- gate / eval bookkeeping
        now = time.time()
        if gate_pending is not None and gate_pending.ready():
            wr = gate_pending.get()
            gate_pending = None
            if wr >= 0.55:
                torch.save(net.state_dict(), gen_ckpt)
                stamp = str(out / f"promoted_{int(now)}.pt")
                torch.save(net.state_dict(), stamp)
                pool_ckpts.append(stamp)
                pool_ckpts[:] = pool_ckpts[-5:]
                print(f"[{time.strftime('%H:%M:%S')}] GATE PASS {wr:.0%} — "
                      f"generator promoted ({len(pool_ckpts)} in pool)",
                      flush=True)
            else:
                print(f"[{time.strftime('%H:%M:%S')}] gate held {wr:.0%} "
                      f"(<55%), generator unchanged", flush=True)
        if gate_pending is None and now >= next_gate:
            torch.save(net.state_dict(), cand_ckpt)
            seed_counter += 1
            gate_pending = pool.apply_async(
                duel, ((cand_ckpt, gen_ckpt, 20, seed_counter * 13),))
            next_gate = now + args.gate_every_min * 60
        if eval_pending is not None and eval_pending.ready():
            wr = eval_pending.get()
            eval_pending = None
            msg = (f"[{time.strftime('%H:%M:%S')}] EVAL vs SmartBot {wr:.0%} "
                   f"(rounds {rounds_done}, steps {steps}, "
                   f"spread {spread_ema:.2f}, anchor_w {anchor_w():.2f})")
            evals.append(msg)
            print(msg, flush=True)
        if eval_pending is None and now >= next_eval:
            torch.save(net.state_dict(), cand_ckpt)
            seed_counter += 1
            eval_pending = pool.apply_async(
                eval_vs_smart, ((cand_ckpt, 30, seed_counter * 7),))
            next_eval = now + args.eval_every_min * 60

        # ---- train (replay-ratio capped)
        if len(buf) < 5000 or samples_trained >= samples_added * args.replay_ratio:
            time.sleep(0.3)
            continue
        for _ in range(4):
            idx = np.random.randint(0, len(buf), size=512)
            obs_b, rows_b, seg_b, ch_b, tg_b = [], [], [], [], []
            base = 0
            for di, i in enumerate(idx):
                obs_i, acts_i, chosen_i, adv_i = buf[i]
                obs_b.append(obs_i)
                rows_b.append(acts_i)
                seg_b.append(np.full(len(acts_i), di))
                ch_b.append(base + chosen_i)
                tg_b.append(adv_i)
                base += len(acts_i)
            o = torch.as_tensor(np.asarray(obs_b), device=dev)
            ar = torch.as_tensor(np.concatenate(rows_b), device=dev)
            seg = torch.as_tensor(np.concatenate(seg_b), dtype=torch.long,
                                  device=dev)
            chr_ = torch.as_tensor(np.asarray(ch_b), dtype=torch.long,
                                   device=dev)
            tg = torch.as_tensor(np.asarray(tg_b, dtype=np.float32), device=dev)
            q, _, _ = net.q_grouped(o, ar, seg, len(idx))
            loss_val = torch.nn.functional.mse_loss(q[chr_], tg)
            w = anchor_w()
            if w > 0:
                with torch.no_grad():
                    qa, _, _ = anchor.q_grouped(o, ar, seg, len(idx))
                loss_anchor = _seg_kl(qa, q, seg, len(idx), dev)
                loss = loss_val + w * loss_anchor
            else:
                loss = loss_val
            opt.zero_grad()
            loss.backward()
            opt.step()
            steps += 1
            samples_trained += 512
            loss_ema = loss_val.item() if loss_ema is None else \
                0.99 * loss_ema + 0.01 * loss_val.item()
            with torch.no_grad():
                qmax = torch.full((len(idx),), -1e9, device=dev)
                qmax = qmax.scatter_reduce(0, seg, q, reduce="amax")
                qmin = torch.full((len(idx),), 1e9, device=dev)
                qmin = qmin.scatter_reduce(0, seg, q, reduce="amin")
                sp = (qmax - qmin).mean().item()
                spread_ema = sp if spread_ema is None else \
                    0.99 * spread_ema + 0.01 * sp
                # arm the alarm only after a warmup: early scale adaptation
                # to the target range is benign (ranking-preserving)
                if spread0 is None and steps > 600:
                    spread0 = spread_ema
        if spread0 and spread_ema < spread0 / 5:
            print(f"!! SPREAD COLLAPSE ALARM: {spread_ema:.3f} vs initial "
                  f"{spread0:.3f} — halting", flush=True)
            break
        if steps % 2000 < 4:
            print(f"[{time.strftime('%H:%M:%S')}] rounds {rounds_done} "
                  f"steps {steps} buf {len(buf)} loss {loss_ema:.3f} "
                  f"spread {spread_ema:.2f} eps {eps_now():.2f}", flush=True)

    torch.save(net.state_dict(), cand_ckpt)
    pool.terminate()
    record = out / f"run_{int(t0)}.md"
    record.write_text(
        f"# DMC v2 run {time.strftime('%Y-%m-%d %H:%M', time.localtime(t0))}\n\n"
        f"warm_start={args.warm_start} oracle={args.oracle_ckpt} "
        f"minutes={args.minutes} lr={args.lr} anchor_w0={args.anchor_w0} "
        f"buffer={args.buffer} replay_ratio={args.replay_ratio}\n\n"
        f"rounds={rounds_done} steps={steps} final_spread={spread_ema}\n\n"
        + "\n".join(evals) + "\n")
    print(f"done: {rounds_done} rounds, {steps} steps; record: {record}")


def _seg_kl(q_ref, q_stu, seg, n, dev):
    """KL(ref softmax || student softmax) over each candidate segment."""
    import torch

    def seg_logsoftmax(q):
        qmax = torch.full((n,), -1e9, device=dev)
        qmax = qmax.scatter_reduce(0, seg, q, reduce="amax")
        ex = torch.exp(q - qmax[seg])
        denom = torch.zeros(n, device=dev).index_add_(0, seg, ex)
        return (q - qmax[seg]) - torch.log(denom[seg] + 1e-9)

    lp_ref = seg_logsoftmax(q_ref)
    lp_stu = seg_logsoftmax(q_stu)
    p_ref = torch.exp(lp_ref)
    per_row = p_ref * (lp_ref - lp_stu)
    tot = torch.zeros(n, device=dev).index_add_(0, seg, per_row)
    return tot.mean()


if __name__ == "__main__":
    main()
