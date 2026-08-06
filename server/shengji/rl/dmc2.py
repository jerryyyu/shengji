"""Historical anchored/oracle-baselined self-play pipeline.

This is not a faithful Suphx or DouZero implementation and remains blocked from
new evidence runs. Its useful alarms/bookkeeping are retained while the known
correctness defects—defender residual signs, mutable actor paths and promotion
of bytes that never passed the gate—are repaired for reuse by the S2 entry gate.

Key differences vs v1 (`dmc.py`):
- QNetDueling student warm-started from a distilled/BC checkpoint; a FROZEN
  copy serves as the anchor reference.
- Actors record obs + ALL candidate encodings + chosen idx + oracle obs;
  forced single-candidate decisions are skipped (no action signal).
- Targets: acting-team advantage = role_sign * (round_value − V_oracle),
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
      --minutes 20 --workers 2 --allow-legacy-correctness-run

Even with the acknowledgement flag, the manifest declares
``promotion_evidence:false`` and ``resume_supported:false``.  Do not scale this
legacy recipe; build the faithful role-conditioned microbaseline after the
resume gate closes.
"""

from __future__ import annotations

import argparse
import json
import os
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
from .selfplay_contract import (CheckpointRef, DMC2_REWARD_SCHEMA,
                                derive_job_seed, load_verified,
                                save_immutable_snapshot,
                                signed_oracle_residual_by_sign)


from .model import load_any_net


EXPERIMENT = "dmc2-correctness-repair-v1"


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
    (gen_ref, pool_refs, n_rounds, eps, seed, sequence) = args
    import numpy as np
    # architectures resolved via load_any_net
    rng = random.Random(seed)

    net = load_verified(gen_ref, load_any_net)
    me = V2Actor(net, eps, rng)
    opponent_nets = {}

    def opponent_net(ref):
        # Pool actors are immutable, so loading each generation once per batch
        # is both safe and materially cheaper than deserializing every round.
        if ref not in opponent_nets:
            opponent_nets[ref] = load_verified(ref, load_any_net)
        return opponent_nets[ref]

    obs_l, act_rows, offs, chosen_l, orc_l, attacker_ret_l, role_sign_l = \
        [], [], [0], [], [], [], []
    for r in range(n_rounds):
        roll = rng.random()
        if roll < 0.8:
            bots = [me] * 4
        elif pool_refs and rng.random() < 0.5:
            opp = V2Actor(opponent_net(rng.choice(pool_refs)), 0.0, rng)
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
            attacker_ret_l.append(val)
            role_sign_l.append(1 if rnd.is_attacker(seat) else -1)
    return (np.asarray(obs_l, dtype=np.float32).reshape(-1, OBS_DIM),
            np.asarray(act_rows, dtype=np.float32).reshape(-1, ACT_DIM),
            np.asarray(offs, dtype=np.int64),
            np.asarray(chosen_l, dtype=np.int32),
            np.asarray(orc_l, dtype=np.float32).reshape(-1, ORACLE_DIM),
            np.asarray(attacker_ret_l, dtype=np.float32),
            np.asarray(role_sign_l, dtype=np.int8),
            {"sequence": sequence, "seed": seed,
             "actor": gen_ref.as_dict(),
             "opponent_pool": [ref.as_dict() for ref in pool_refs],
             "rounds": n_rounds, "epsilon": eps})


def duel(args):
    """Worker: mirrored duel between two checkpoints; returns a's win rate."""
    ref_a, ref_b, n_pairs, seed = args
    net_a = load_verified(ref_a, load_any_net)
    net_b = load_verified(ref_b, load_any_net)

    wins = [0, 0]
    for s in range(n_pairs):
        for flip in (0, 1):
            # Nets are immutable/eval-only. Reuse their weights while keeping
            # per-game actor records and RNGs isolated.
            a = V2Actor(net_a, 0.0, random.Random(seed))
            b = V2Actor(net_b, 0.0, random.Random(seed))
            pol = [a, b, a, b] if flip == 0 else [b, a, b, a]
            game = Game(random.Random(seed + s))
            play_round(game, pol)
            team = 0 if flip == 0 else 1
            wins[0 if game.result.winner_team == team else 1] += 1
    return wins[0] / (2 * n_pairs)


def eval_vs_smart(args):
    ref, n_pairs, seed = args
    net = load_verified(ref, load_any_net)
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
    ap.add_argument("--seed", type=int, default=20260806)
    ap.add_argument(
        "--allow-legacy-correctness-run", action="store_true",
        help="acknowledge that DMC2 is not a faithful Suphx/DouZero baseline "
             "and its output is not promotion evidence")
    ap.add_argument("--a-scale", type=float, default=1.0,
                    help="rescale the warm start's A-head output (CE-trained "
                         "scale is arbitrary; match it to advantage-target "
                         "scale so regression needn't shrink spread)")
    args = ap.parse_args()
    if not args.allow_legacy_correctness_run:
        ap.error(
            "DMC2 remains a legacy correctness workbench, not strength "
            "evidence; pass --allow-legacy-correctness-run only for a bounded "
            "pipeline test")

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    dev = "mps" if torch.backends.mps.is_available() else "cpu"

    warm_ref = CheckpointRef.capture(args.warm_start)
    oracle_ref = CheckpointRef.capture(args.oracle_ckpt)
    net = load_verified(warm_ref, load_any_net).to(dev)
    net.train()
    anchor = load_verified(warm_ref, load_any_net).to(dev)
    anchor.eval()
    print(f"warm start architecture: {type(net).__name__}", flush=True)
    if args.a_scale != 1.0 and hasattr(net, "a_head"):
        with torch.no_grad():
            for m in (net, anchor):  # both, so the anchor KL target matches
                m.a_head[-1].weight *= args.a_scale
                m.a_head[-1].bias *= args.a_scale
        print(f"A-head rescaled by {args.a_scale}", flush=True)
    from .oracle import oracle_net
    oracle = oracle_net().to(dev)
    oracle_ref.verify()
    oracle.load_state_dict(torch.load(oracle_ref.path, map_location=dev))
    oracle_ref.verify()
    oracle.eval()
    opt = torch.optim.Adam(net.parameters(), lr=args.lr)

    snapshot_dir = out / "actor_snapshots"
    snapshot_sequence = 0

    def publish(label: str) -> CheckpointRef:
        nonlocal snapshot_sequence
        ref = save_immutable_snapshot(
            net, snapshot_dir, label=label, sequence=snapshot_sequence)
        snapshot_sequence += 1
        return ref

    gen_ref = publish("generator_initial")
    pool_refs: list[CheckpointRef] = []
    promotion_ledger = [{"event": "initial", "actor": gen_ref.as_dict()}]
    evaluation_ledger: list[dict] = []

    # ragged replay buffer (python-side, bounded by decisions)
    buf: list[tuple] = []  # (obs, act_rows, chosen, adv_target, actor_sha256)
    buf_pos = 0
    samples_added = samples_trained = 0

    ctx = mp.get_context("spawn")
    pool = ctx.Pool(args.workers + 1)  # +1 slot for eval/gate tasks
    t0 = time.time()
    t_end = t0 + args.minutes * 60
    actor_job_sequence = 0
    actor_ledger: list[dict] = []

    def eps_now():
        frac = min(1.0, (time.time() - t0) / (args.minutes * 60))
        return args.eps0 + (args.eps1 - args.eps0) * frac

    def anchor_w():
        frac = min(1.0, (time.time() - t0) / (args.anchor_anneal_min * 60))
        return args.anchor_w0 * (1.0 - frac)

    def schedule_actor():
        nonlocal actor_job_sequence
        sequence = actor_job_sequence
        actor_job_sequence += 1
        actor = gen_ref
        seed = derive_job_seed(
            experiment=EXPERIMENT, root_seed=args.seed, purpose="actor",
            sequence=sequence, actor_sha256=actor.sha256)
        job = (actor, pool_refs[:], args.rounds_per_batch, eps_now(), seed,
               sequence)
        return pool.apply_async(actor_batch, (job,))

    pending = [schedule_actor() for _ in range(args.workers)]
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
            (obs, act_rows, offs, chosen, orc, attacker_rets,
             role_signs, actor_meta) = p.get()
            actor_ledger.append(actor_meta)
            rounds_done += args.rounds_per_batch
            with torch.no_grad():
                vo = oracle(torch.as_tensor(orc, device=dev)).squeeze(-1)
                # Both the terminal return and attacker-perspective oracle must
                # receive the same role transform.  The previous code signed
                # only the return, corrupting every defender residual.
                adv = signed_oracle_residual_by_sign(
                    torch.as_tensor(attacker_rets, device=dev), vo,
                    torch.as_tensor(role_signs, device=dev))
            adv = adv.cpu().numpy()
            for i in range(len(obs)):
                a, b = offs[i], offs[i + 1]
                item = (obs[i], act_rows[a:b], int(chosen[i]), float(adv[i]),
                        actor_meta["actor"]["sha256"])
                if len(buf) < args.buffer:
                    buf.append(item)
                else:
                    nonlocal_pos = buf_pos % args.buffer
                    buf[nonlocal_pos] = item
                buf_pos += 1
                samples_added += 1
            still.append(schedule_actor())
        pending = still

        # ---- gate / eval bookkeeping
        now = time.time()
        if gate_pending is not None and gate_pending[0].ready():
            gate_job, candidate_ref, incumbent_ref, gate_seed = gate_pending
            wr = gate_job.get()
            gate_pending = None
            if wr >= 0.55:
                if gen_ref != incumbent_ref:
                    raise RuntimeError(
                        "generator changed while its gate was outstanding")
                # Promote the exact bytes that were evaluated.  The old code
                # overwrote generator.pt with the *current* learner after the
                # duel, which could differ from the candidate that passed.
                pool_refs.append(incumbent_ref)
                pool_refs[:] = pool_refs[-5:]
                gen_ref = candidate_ref
                promotion_ledger.append({
                    "event": "promote", "win_rate": wr,
                    "seed": gate_seed,
                    "incumbent": incumbent_ref.as_dict(),
                    "actor": gen_ref.as_dict(),
                })
                print(f"[{time.strftime('%H:%M:%S')}] GATE PASS {wr:.0%} — "
                      f"generator promoted ({len(pool_refs)} in pool)",
                      flush=True)
            else:
                promotion_ledger.append({
                    "event": "hold", "win_rate": wr,
                    "seed": gate_seed,
                    "incumbent": incumbent_ref.as_dict(),
                    "candidate": candidate_ref.as_dict(),
                })
                print(f"[{time.strftime('%H:%M:%S')}] gate held {wr:.0%} "
                      f"(<55%), generator unchanged", flush=True)
        if gate_pending is None and now >= next_gate:
            candidate_ref = publish("gate_candidate")
            incumbent_ref = gen_ref
            gate_seed = derive_job_seed(
                experiment=EXPERIMENT, root_seed=args.seed, purpose="gate",
                sequence=snapshot_sequence,
                actor_sha256=candidate_ref.sha256 + incumbent_ref.sha256)
            gate_job = pool.apply_async(
                duel, ((candidate_ref, incumbent_ref, 20, gate_seed),))
            gate_pending = (gate_job, candidate_ref, incumbent_ref, gate_seed)
            next_gate = now + args.gate_every_min * 60
        if eval_pending is not None and eval_pending[0].ready():
            eval_job, evaluated_ref, eval_seed = eval_pending
            wr = eval_job.get()
            eval_pending = None
            evaluation_ledger.append({
                "seed": eval_seed, "win_rate": wr,
                "actor": evaluated_ref.as_dict(),
                "rounds_done": rounds_done, "steps": steps,
            })
            spread_text = "NA" if spread_ema is None else f"{spread_ema:.2f}"
            msg = (f"[{time.strftime('%H:%M:%S')}] EVAL vs SmartBot {wr:.0%} "
                   f"(rounds {rounds_done}, steps {steps}, "
                   f"spread {spread_text}, anchor_w {anchor_w():.2f}, "
                   f"actor {evaluated_ref.sha256[:12]})")
            evals.append(msg)
            print(msg, flush=True)
        if eval_pending is None and now >= next_eval:
            evaluated_ref = publish("smart_eval")
            eval_seed = derive_job_seed(
                experiment=EXPERIMENT, root_seed=args.seed, purpose="eval",
                sequence=snapshot_sequence,
                actor_sha256=evaluated_ref.sha256)
            eval_job = pool.apply_async(
                eval_vs_smart, ((evaluated_ref, 30, eval_seed),))
            eval_pending = (eval_job, evaluated_ref, eval_seed)
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
                obs_i, acts_i, chosen_i, adv_i, _actor_sha = buf[i]
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

    final_ref = publish("learner_final")
    pool.terminate()
    pool.join()
    manifest = {
        "schema": "dmc2-correctness-run-v1",
        "experiment": EXPERIMENT,
        "promotion_evidence": False,
        "faithful_suphx_or_douzero": False,
        "resume_supported": False,
        "resume_blocker": (
            "learner/optimizer/replay/pending-job state is not checkpointed; "
            "individual actor batches are replayable but the run is not"
        ),
        "reward_schema": DMC2_REWARD_SCHEMA,
        "root_seed": args.seed,
        "warm_start": warm_ref.as_dict(),
        "oracle": oracle_ref.as_dict(),
        "generator": gen_ref.as_dict(),
        "final_learner": final_ref.as_dict(),
        "opponent_pool": [ref.as_dict() for ref in pool_refs],
        "minutes": args.minutes,
        "rounds": rounds_done,
        "steps": steps,
        "samples_added": samples_added,
        "samples_trained": samples_trained,
        "final_spread": spread_ema,
        "actor_batches": sorted(actor_ledger, key=lambda row: row["sequence"]),
        "promotions": promotion_ledger,
        "evaluations": evaluation_ledger,
        "eval_log": evals,
    }
    record = out / f"run_{int(t0)}.json"
    partial = Path(str(record) + ".partial")
    if record.exists() or partial.exists():
        raise FileExistsError(f"refusing to overwrite run record {record}")
    with partial.open("x") as fh:
        json.dump(manifest, fh, sort_keys=True, indent=2)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(partial, record)
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
