"""DEV: a per-world readout on the unified model's trunk, for the search's value slot and reply prior.

The unified model (``unified_seq``: the served belief trunk + an information-set outcome head + a root
policy head) runs once per decision on the actor's own information.  The search's value slot and its
reply prior score FULL-INFORMATION states instead: a sampled world after the candidate play and up to
three replies of the same trick.  This module adds the head for those, trained through the trunk:

* per decision (once): the 54 card states are projected to ``dp`` dims, and the row context joined
  with their mean to ``dc``;
* per leaf: nine 54-wide count planes in the actor's frame -- where every card is in the leaf's world
  (actor, the three other seats in play order, kitty) and what each seat has played since the
  decision -- pool the projected card states (a count-weighted sum per plane), and join the raw
  planes, twelve trick scalars and the decision context in a small residual MLP with two outputs:
  the 204-category outcome from the actor's side (the served value's target) and 54 card log-odds
  for the seat to act next (the reply prior; scored over that seat's hand).

Training leaves come from the belief extracts themselves: a row's true world is its hand, the hidden
copies' labels, the public pins and the actor's own burial; the leaf after ``k`` further plays of the
same trick (k = 0..3) subtracts those plays, all read from the round's tokens.  Every row gives one
leaf per remaining play of its trick.  Losses: the unified model's three (belief, Q, root policy,
unchanged weights) + leaf outcome cross-entropy + listwise reply cross-entropy over the next seat's
hand (the reply actually played).

CLI: ``python -m shengji.train.unified_readout {train,export}``.  Status lines (``OUT/status.log``):
``UTR START`` / ``RESUME`` / ``buffer`` / ``EPOCH`` / ``UTR DONE ...`` / ``UTR ABORT ...``.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from . import belief_seq as bs
from . import unified_seq as us
from .belief_eval import _block_slice, known_counts, masked_softmax, mean_ll
from .belief_history import TOKEN_FLOAT

N_CARDS = 54
OUTCOME_CLASSES = 204
LANE = "UTR"
CKPT_SCHEMA = "shengji-unified-readout-ckpt-v1"
#: the readout's architecture (recorded in every checkpoint and package)
READOUT_ARCH = {"dp": 48, "dc": 96, "width": 288, "hidden": 576, "blocks": 3}
N_PLANES = 9                     # 5 locations (actor, rel 1..3, kitty) + 4 played-since-the-decision
N_SCALARS = 12
POOL_SCALE = 0.25
_TAKES_LEAD = TOKEN_FLOAT.index("takes_lead")


class UnifiedReadoutError(ValueError):
    pass


def card_points() -> np.ndarray:
    """``(54,)`` points of each card index."""
    from ..engine.cards import points
    from ..rl.encode import CARD_INDEX
    out = np.zeros(N_CARDS, np.float32)
    for code, i in CARD_INDEX.items():
        out[i] = points(code)
    return out


def leaf_scalars(n_delta, n_trick, points, winner, nxt) -> np.ndarray:
    """``(L, 12)``: plays since the decision / 4, plays in the current trick / 4, the trick is
    complete, its points / 50, its winner so far (one-hot, actor's frame), the seat to act next
    (one-hot; the winner when the trick is complete).  A complete trick is the one just finished."""
    n = len(n_delta)
    out = np.zeros((n, N_SCALARS), np.float32)
    out[:, 0] = np.asarray(n_delta, np.float32) / 4.0
    out[:, 1] = np.asarray(n_trick, np.float32) / 4.0
    out[:, 2] = np.asarray(n_trick) == 4
    out[:, 3] = np.asarray(points, np.float32) / 50.0
    out[np.arange(n), 4 + np.asarray(winner, np.int64)] = 1.0
    out[np.arange(n), 8 + np.asarray(nxt, np.int64)] = 1.0
    return out


def root_locations(b: Mapping[str, np.ndarray]) -> np.ndarray:
    """``(B, 5, 54)`` card counts of each row's TRUE world at its decision, actor's frame: the
    actor's hand, the three other seats (hidden copies + public pins), the kitty (hidden copies, or
    the actor's own burial)."""
    X = b["X"]
    hand = 2.0 * X[:, :N_CARDS]
    hidden = b["Y"] + known_counts(X)
    kitty = hidden[:, :, 3] + np.round(np.asarray(X[:, _block_slice("own_kitty")], np.float32))
    loc = np.stack([hand, hidden[:, :, 0], hidden[:, :, 1], hidden[:, :, 2], kitty], 1).astype(np.float32)
    if np.any(loc != np.round(loc)) or np.any(loc < 0):
        raise UnifiedReadoutError("a world location is not a whole card count")
    return loc


def leaf_batch(b: Mapping[str, np.ndarray]) -> dict[str, np.ndarray]:
    """Every row's leaves (one per remaining play of its trick, the row's own play first):
    ``row`` (L,), ``planes`` (L, 9, 54), ``scalars`` (L, 12), ``k`` (L,), and the reply played at the
    leaf: ``reply`` (L, 54) card counts, ``reply_hand`` (L, 54) the next seat's hand, ``has_reply``."""
    rr, ply, seat = b["rr"], b["ply"], b["seat"]
    ti, tc, tf = b["tok_int"], b["tok_cards"], b["tok_f"]
    B, T = len(rr), ti.shape[1]
    pts = card_points()
    loc = root_locations(b)
    before = np.concatenate([np.zeros_like(tc[:, :1]), np.cumsum(tc, 1)], 1)
    played = before[rr, ply]                             # every card is somewhere: 2 copies each
    if np.any(loc.sum(1) + played != 2):
        raise UnifiedReadoutError("a row's world and the plays before it do not make two decks")
    pos = ti[rr, ply, 1].astype(np.int64)
    trick = ti[rr, ply, 2]
    winner = np.zeros(B, np.int64)
    points = np.zeros(B, np.float32)
    for m in range(3):                                   # the trick's plays before the decision
        on = np.nonzero(pos > m)[0]
        t = ply[on] - pos[on] + m
        rel = (ti[rr[on], t, 0] - seat[on]) % 4
        takes = (tf[rr[on], t, _TAKES_LEAD] > 0) | (m == 0)
        winner[on] = np.where(takes, rel, winner[on])
        points[on] += tc[rr[on], t] @ pts
    delta = np.zeros((B, 4, N_CARDS), np.float32)
    out = {k: [] for k in ("row", "planes", "scalars", "k", "reply", "reply_hand", "has_reply")}
    alive = np.arange(B)
    for k in range(4):
        t = ply[alive] + k
        ok = (pos[alive] + k <= 3) & (t < T)
        alive, t = alive[ok], t[ok]
        ok = (tc[rr[alive], t].sum(-1) > 0) & (ti[rr[alive], t, 2] == trick[alive]) \
            & (ti[rr[alive], t, 1] == pos[alive] + k)
        alive, t = alive[ok], t[ok]
        if not len(alive):
            break
        rel = (ti[rr[alive], t, 0] - seat[alive]) % 4
        cards = tc[rr[alive], t].astype(np.float32)
        loc[alive, rel] -= cards
        delta[alive, rel] += cards
        if np.any(loc[alive, rel] < 0):
            raise UnifiedReadoutError("a play is not in its seat's hand in the row's world")
        takes = (tf[rr[alive], t, _TAKES_LEAD] > 0) | (pos[alive] + k == 0)
        winner[alive] = np.where(takes, rel, winner[alive])
        points[alive] += cards @ pts
        n_trick = pos[alive] + k + 1
        nxt = np.where(n_trick == 4, winner[alive], (rel + 1) % 4)
        t1 = np.minimum(t + 1, T - 1)
        has = (n_trick < 4) & (t + 1 < T) & (ti[rr[alive], t1, 2] == trick[alive]) & (tc[rr[alive], t1].sum(-1) > 0)
        reply = np.where(has[:, None], tc[rr[alive], t1], 0).astype(np.float32)
        hand = loc[alive, nxt]
        if np.any((reply > 0) & (hand < reply)):
            raise UnifiedReadoutError("a reply is not in the next seat's hand in the row's world")
        out["row"].append(alive.copy())
        out["planes"].append(np.concatenate([loc[alive], delta[alive]], 1))
        out["scalars"].append(leaf_scalars(np.full(len(alive), k + 1), n_trick, points[alive], winner[alive], nxt))
        out["k"].append(np.full(len(alive), k, np.int64))
        out["reply"].append(reply)
        out["reply_hand"].append(hand > 0)
        out["has_reply"].append(has)
    return {k: np.concatenate(v) for k, v in out.items()}


def make_batch(part, round_ids, rows, *, perm=None) -> dict[str, np.ndarray]:
    b = us.make_unified_batch(part, round_ids, rows, perm=perm)
    for k, v in leaf_batch(b).items():
        b["leaf_" + k] = v
    return b


# ------------------------------------------------------------------ model

def build(arch: Mapping[str, Any], readout_arch: Mapping[str, Any] = READOUT_ARCH):
    import torch
    from torch import nn
    base = us.build_unified(arch)
    d, xh = int(arch["d"]), int(arch["x_hidden"])
    ra = {k: int(readout_arch[k]) for k in READOUT_ARCH}
    dp, dc, width, hidden = ra["dp"], ra["dc"], ra["width"], ra["hidden"]

    class Readout(nn.Module):
        def __init__(self):
            super().__init__()
            self.card_ln = nn.LayerNorm(d)
            self.card_proj = nn.Linear(d, dp)
            self.ctx = nn.Linear(xh + d, dc)
            self.stem = nn.Linear(N_PLANES * N_CARDS + N_SCALARS + N_PLANES * dp + dc, width)
            self.ln = nn.ModuleList([nn.LayerNorm(width) for _ in range(ra["blocks"])])
            self.up = nn.ModuleList([nn.Linear(width, hidden) for _ in range(ra["blocks"])])
            self.down = nn.ModuleList([nn.Linear(hidden, width) for _ in range(ra["blocks"])])
            self.out_ln = nn.LayerNorm(width)
            self.value = nn.Linear(width, OUTCOME_CLASSES)
            self.reply = nn.Linear(width, N_CARDS)

        def forward(self, q, g, row, planes, scalars):
            n = self.card_ln(q.float())
            S = self.card_proj(n)                                        # B,54,dp
            c = torch.relu(self.ctx(torch.cat([g.float(), n.mean(1)], -1)))   # B,dc
            pooled = torch.bmm(planes, S[row]) * POOL_SCALE              # L,9,dp
            x = torch.cat([planes.flatten(1), scalars, pooled.flatten(1), c[row]], -1)
            h = torch.relu(self.stem(x))
            for ln, up, down in zip(self.ln, self.up, self.down):
                h = h + down(torch.relu(up(ln(h))))
            h = self.out_ln(h)
            return self.value(h), self.reply(h)

    class UnifiedReadout(nn.Module):
        def __init__(self):
            super().__init__()
            self.trunk = base.trunk
            self.q_head = base.q_head
            self.p_head = base.p_head
            self.readout = Readout()
            self.config = {"trunk": dict(base.trunk.config), "heads": dict(us.HEAD_ARCH), "readout": ra}

        def forward(self, b):
            logits, enc, q, g = us.trunk_forward(self.trunk, b)
            frame = b["rr"] * 4 + b["seat"]
            ql = self.q_head(torch.cat([enc[frame, b["ply"]], g], -1).float())
            pl = self.p_head(q.float()).squeeze(-1)
            rv, rp = self.readout(q, g, b["leaf_row"], b["leaf_planes"], b["leaf_scalars"])
            return {"belief": logits, "q": ql, "policy": pl, "leaf_value": rv, "leaf_reply": rp}

    return UnifiedReadout()


def losses(model, tb) -> dict:
    """Sums and counts of the five losses, and the outputs."""
    import torch
    out = model(tb)
    logp = torch.log_softmax(out["belief"].float().masked_fill(~tb["M"], -1e9), -1)
    y = tb["Y"]
    q_ce = torch.nn.functional.cross_entropy(out["q"], tb["q_target"], reduction="none")
    p_ce = us.policy_loss_terms(out["policy"], tb)
    v_ce = torch.nn.functional.cross_entropy(out["leaf_value"], tb["q_target"][tb["leaf_row"]], reduction="none")
    has = tb["leaf_has_reply"]
    rl = torch.log_softmax(out["leaf_reply"].masked_fill(~tb["leaf_reply_hand"], -1e9), -1)
    t = tb["leaf_reply"]
    r_ce = -((t / t.sum(-1, keepdim=True).clamp_min(1.0)) * rl).sum(-1) * has
    return {"belief_sum": -(y * logp).sum(), "belief_n": y.sum(), "q_sum": q_ce.sum(), "p_sum": p_ce.sum(),
            "rows": torch.tensor(float(len(q_ce))), "v_sum": v_ce.sum(), "leaves": torch.tensor(float(len(v_ce))),
            "v0_sum": (v_ce * (tb["leaf_k"] == 0)).sum(), "ve_sum": (v_ce * tb["leaf_scalars"][:, 2]).sum(),
            "ends": tb["leaf_scalars"][:, 2].sum(), "r_sum": r_ce.sum(), "replies": has.float().sum(), "out": out}


SUM_KEYS = ("belief_sum", "belief_n", "q_sum", "p_sum", "rows", "v_sum", "leaves", "v0_sum", "ve_sum", "ends", "r_sum", "replies")


def means(s) -> dict[str, float]:
    s = dict(zip(SUM_KEYS, s))
    return {"belief": s["belief_sum"] / max(s["belief_n"], 1.0), "q": s["q_sum"] / max(s["rows"], 1.0),
            "policy": s["p_sum"] / max(s["rows"], 1.0), "leaf_value": s["v_sum"] / max(s["leaves"], 1.0),
            "leaf_value_k0": s["v0_sum"] / max(s["rows"], 1.0), "leaf_value_end": s["ve_sum"] / max(s["ends"], 1.0), "reply": s["r_sum"] / max(s["replies"], 1.0)}


def evaluate(model, part, *, rounds_per_batch: int = 32) -> dict[str, float]:
    """Calibration-split means of every loss (identity relabeling) and the belief log-loss."""
    import torch
    sums = np.zeros(len(SUM_KEYS))
    n = len(part["X"])
    belief = np.empty((n, N_CARDS, 4), np.float32)
    model.eval()
    with torch.no_grad():
        for rids, rows in bs.round_batches(part, rounds_per_batch, None):
            L = losses(model, us.to_device(make_batch(part, rids, rows), "cpu"))
            sums += np.asarray([float(L[k]) for k in SUM_KEYS])
            belief[rows] = L["out"]["belief"].float().numpy()
    model.train()
    out = {k: round(float(v), 6) for k, v in means(sums).items()}
    out["belief_ll"] = mean_ll(masked_softmax(belief, part["M"]), part["Y"])
    return out


def _status(path: str, msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {msg}"
    print(line, flush=True)
    with open(path, "a") as fh:
        fh.write(line + "\n")


def _run_identity(args) -> dict:
    keys = ("data", "init", "init_sha256", "init_ckpt", "store_map", "epochs", "lr", "head_lr", "readout_lr",
            "head_warmup_buffers", "weight_decay", "belief_weight", "q_weight", "policy_weight", "value_weight",
            "reply_weight", "seed", "buffer_chunks", "rounds_per_batch", "max_train_rows", "calib_rows",
            "exclude_seed_window")
    return json.loads(json.dumps({k: getattr(args, k) for k in keys}, default=str))


def train(args) -> int:
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    status = str(out / "status.log")
    if (out / "status.log").exists() and f" {LANE} DONE" in (out / "status.log").read_text():
        print(f"refusing: {status} already has {LANE} DONE", file=sys.stderr)
        return 2
    try:
        return _train(args, out, status)
    except Exception as exc:
        _status(status, f"{LANE} ABORT {type(exc).__name__}: {str(exc)[:300]}")
        traceback.print_exc()
        return 1


def _train(args, out: Path, status: str) -> int:
    import torch
    torch.set_num_threads(args.threads)
    torch.manual_seed(args.seed)
    verified = bs._Verified()
    index = us.OutcomeIndex(us.parse_store_map(args.store_map))
    entries = us._pick_entries(us.entries_for(args.data, "train", exclude_seed_windows=args.exclude_seed_window),
                               args.max_train_rows, args.seed)
    if not entries:
        raise UnifiedReadoutError("no train chunks")
    init = bs.load_init(args.init)
    if args.init_sha256 and init["sha256"] != args.init_sha256:
        raise UnifiedReadoutError(f"--init sha256 {init['sha256']} != --init-sha256 {args.init_sha256}")
    bs.check_init_identity(init, args.data)
    arch = {k: init["config"][k] for k in bs.DEFAULT_ARCH}
    model = build(arch)
    bs.apply_init(model.trunk, init)
    if args.init_ckpt:
        warm, _ = us.load_checkpoint(args.init_ckpt)
        for a, b_ in zip(model.trunk.state_dict().values(), warm.trunk.state_dict().values()):
            if not torch.equal(a, b_):
                raise UnifiedReadoutError("--init-ckpt's trunk is not --init's trunk")
        model.q_head.load_state_dict(warm.q_head.state_dict())
        model.p_head.load_state_dict(warm.p_head.state_dict())

    stream = us.Stream(entries, index=index, suit_aug=False, verified=verified, threads=args.loader_threads,
                    buffer_chunks=args.buffer_chunks, rounds_per_batch=args.rounds_per_batch, row_frac=1.0)
    calib = us.load_calib(args.data, verified, index, max_rows=args.calib_rows, seed=args.seed,
                          exclude_seed_windows=args.exclude_seed_window)
    groups = [{"params": list(model.trunk.parameters()), "base_lr": args.lr},
              {"params": list(model.q_head.parameters()) + list(model.p_head.parameters()), "base_lr": args.head_lr},
              {"params": list(model.readout.parameters()), "base_lr": args.readout_lr}]
    for g in groups:
        g["lr"] = g["base_lr"]
    opt = torch.optim.AdamW(groups, weight_decay=args.weight_decay)
    n_buffers = math.ceil(len(stream.entries) / args.buffer_chunks)
    total = args.epochs * n_buffers

    def lr_scale(step):
        warm = max(1, int(0.02 * total))
        return (step + 1) / warm if step < warm else 0.5 * (1 + math.cos(math.pi * min(1.0, step / total)))

    def step_on(b, step):
        scale = lr_scale(step)
        for g in opt.param_groups:
            g["lr"] = g["base_lr"] * scale
        if step < args.head_warmup_buffers:
            opt.param_groups[0]["lr"] = 0.0             # the new readout fits a frozen trunk first
            opt.param_groups[1]["lr"] = 0.0
        for k, v in leaf_batch(b).items():
            b["leaf_" + k] = v
        L = losses(model, us.to_device(b, "cpu"))
        m = means([L[k] for k in SUM_KEYS])
        opt.zero_grad()
        (args.belief_weight * m["belief"] + args.q_weight * m["q"] + args.policy_weight * m["policy"]
         + args.value_weight * m["leaf_value"] + args.reply_weight * m["reply"]).backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        opt.step()
        return np.asarray([float(L[k].detach()) for k in SUM_KEYS])

    ck = out / "checkpoint.pt"
    state = {"epoch": 0, "buffer": 0, "history": [], "best": float("inf")}
    if ck.exists():
        saved = torch.load(ck, weights_only=False, map_location="cpu")
        if saved.get("run") != _run_identity(args):
            raise UnifiedReadoutError("resume: the run's settings differ from the checkpoint's")
        model.load_state_dict(saved["model"])
        opt.load_state_dict(saved["opt"])
        state = saved["state"]
        _status(status, f"RESUME epoch {state['epoch']} buffer {state['buffer']}")
    else:
        state["init_calib"] = evaluate(model, calib)
        _status(status, f"{LANE} START params={sum(p.numel() for p in model.parameters())} "
                        f"readout_params={sum(p.numel() for p in model.readout.parameters())} rows={stream.rows} "
                        f"chunks={len(entries)} buffers={n_buffers} init={init['sha256']}")
        (out / "run.json").write_text(json.dumps(_run_identity(args), indent=1))
        _status(status, f"INIT calib {json.dumps(state['init_calib'])}")
        if args.expect_init_belief_ll is not None and abs(state["init_calib"]["belief_ll"] - args.expect_init_belief_ll) > 5e-4:
            raise UnifiedReadoutError(f"init calib belief_ll {state['init_calib']['belief_ll']} != expected")

    def save():
        tmp = out / "checkpoint.pt.tmp"
        torch.save({"model": model.state_dict(), "opt": opt.state_dict(), "state": state, "config": model.config,
                    "run": _run_identity(args)}, tmp)
        os.replace(tmp, ck)

    def save_best(epoch, cm):
        torch.save({"schema": CKPT_SCHEMA, "model": model.state_dict(), "config": model.config, "epoch": epoch,
                    "calib": cm, "init_calib": state.get("init_calib"), "run": _run_identity(args)}, out / "best.pt")

    last_save = time.time()
    while state["epoch"] < args.epochs:
        epoch, t0, sums, cur, steps = state["epoch"], time.time(), np.zeros(len(SUM_KEYS)), state["buffer"], 0
        for gi, b in stream.batches(args.seed, epoch, state["buffer"]):
            if gi != cur:
                state["buffer"] = cur = gi
                if time.time() - last_save > args.save_every:
                    save()
                    last_save = time.time()
                    _status(status, f"epoch {epoch + 1} buffer {gi}/{n_buffers} {json.dumps({k: round(v, 5) for k, v in means(sums).items()})}"
                                    f" ({time.time() - t0:.0f}s)")
                if (out / "STOP").exists():
                    save()
                    _status(status, "STOPPED (STOP file); checkpoint saved")
                    return 3
            sums += step_on(b, epoch * n_buffers + gi)
            steps += 1
            if args.max_steps and steps >= args.max_steps:
                break
        cm = evaluate(model, calib)
        state["history"].append({"epoch": epoch + 1, "train": means(sums), "calib": cm, "seconds": time.time() - t0})
        _status(status, f"EPOCH {epoch + 1} train {json.dumps({k: round(v, 5) for k, v in means(sums).items()})} "
                        f"calib {json.dumps(cm)} steps={steps} ({time.time() - t0:.0f}s)")
        state["epoch"] += 1
        state["buffer"] = 0
        score = cm["belief_ll"] + cm["leaf_value_end"]
        if score < state["best"]:
            state["best"] = score
            save_best(epoch + 1, cm)
        save()
        last_save = time.time()
    _status(status, f"{LANE} DONE best={out / 'best.pt'} sha256={us.sha256_file(out / 'best.pt')}")
    return 0


def load_checkpoint(path: str):
    import torch
    saved = torch.load(path, weights_only=False, map_location="cpu")
    if saved.get("schema") != CKPT_SCHEMA:
        raise UnifiedReadoutError(f"{path}: not a {CKPT_SCHEMA} checkpoint")
    model = build(saved["config"]["trunk"], saved["config"]["readout"])
    model.load_state_dict(saved["model"])
    model.eval()
    return model, saved


def export(args) -> int:
    """Write the NumPy package (``ai.unified_readout_numpy``) of a checkpoint; prints its sha256."""
    from ..ai import unified_readout_numpy as rn
    model, saved = load_checkpoint(args.ckpt)
    sd = {k: v.detach().cpu().float().numpy() for k, v in model.state_dict().items()}
    trunk = {k[len("trunk."):]: v for k, v in sd.items() if k.startswith("trunk.")}
    heads = {k: sd[k] for k in sd if k.startswith(("q_head.", "p_head."))}
    readout = {k[len("readout."):]: sd[k] for k in sd if k.startswith("readout.")}
    meta = {"source_checkpoint_sha256": us.sha256_file(args.ckpt), "epoch": saved.get("epoch"), "calib": saved.get("calib"),
            "note": args.note, "temperature": args.temperature}
    sha = rn.save_package(args.out, saved["config"], trunk, heads, readout, meta)
    print(json.dumps({"package": args.out, "sha256": sha}))
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="unified_readout")
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("train")
    t.add_argument("--data", nargs="+", required=True)
    t.add_argument("--out", required=True)
    t.add_argument("--init", required=True, help="a served-shape belief package whose trunk warms the trunk")
    t.add_argument("--init-sha256", default=None)
    t.add_argument("--init-ckpt", default=None, help="a unified_seq checkpoint with the same trunk: warms the Q and policy heads")
    t.add_argument("--store-map", action="append", default=[])
    t.add_argument("--epochs", type=int, default=1)
    t.add_argument("--lr", type=float, default=1.0e-4)
    t.add_argument("--head-lr", type=float, default=3e-4)
    t.add_argument("--readout-lr", type=float, default=1e-3)
    t.add_argument("--expect-init-belief-ll", type=float, default=None)
    t.add_argument("--head-warmup-buffers", type=int, default=4)
    t.add_argument("--weight-decay", type=float, default=0.01)
    t.add_argument("--belief-weight", type=float, default=1.0)
    t.add_argument("--q-weight", type=float, default=1.0)
    t.add_argument("--policy-weight", type=float, default=0.2)
    t.add_argument("--value-weight", type=float, default=1.0)
    t.add_argument("--reply-weight", type=float, default=0.2)
    t.add_argument("--seed", type=int, default=1)
    t.add_argument("--threads", type=int, default=12)
    t.add_argument("--loader-threads", type=int, default=3)
    t.add_argument("--buffer-chunks", type=int, default=24)
    t.add_argument("--rounds-per-batch", type=int, default=16)
    t.add_argument("--max-train-rows", type=int, default=None)
    t.add_argument("--max-steps", type=int, default=None)
    t.add_argument("--calib-rows", type=int, default=180000)
    t.add_argument("--save-every", type=float, default=600.0)
    t.add_argument("--exclude-seed-window", type=bs.seed_window, action="append", default=[])
    e = sub.add_parser("export")
    e.add_argument("--ckpt", required=True)
    e.add_argument("--out", required=True)
    e.add_argument("--temperature", type=float, required=True, help="the belief output's temperature")
    e.add_argument("--note", default="")
    return ap


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return {"train": train, "export": export}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
