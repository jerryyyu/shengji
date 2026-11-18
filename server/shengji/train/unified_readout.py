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

        def project(self, q, g):
            """The per-decision projections: ``(B, 54, dp)`` card states and ``(B, dc)`` context."""
            n = self.card_ln(q.float())
            return self.card_proj(n), torch.relu(self.ctx(torch.cat([g.float(), n.mean(1)], -1)))

        def features(self, S, c, planes, scalars):
            """The per-leaf ``(L, width)`` features both outputs (and any auxiliary head) read."""
            pooled = torch.bmm(planes, S) * POOL_SCALE                   # L,9,dp
            x = torch.cat([planes.flatten(1), scalars, pooled.flatten(1), c], -1)
            h = torch.relu(self.stem(x))
            for ln, up, down in zip(self.ln, self.up, self.down):
                h = h + down(torch.relu(up(ln(h))))
            return self.out_ln(h)

        def body(self, S, c, planes, scalars):
            """The per-leaf part: each leaf's own ``(54, dp)`` card states and ``(dc,)`` context."""
            h = self.features(S, c, planes, scalars)
            return self.value(h), self.reply(h)

        def forward(self, q, g, row, planes, scalars):
            S, c = self.project(q, g)
            return self.body(S[row], c[row], planes, scalars)

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
    keys = ("data", "init", "init_sha256", "init_ckpt", "init_readout_ckpt", "scratch_arch", "calib_data", "store_map", "epochs", "lr", "head_lr", "readout_lr",
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
    if args.scratch_arch:
        # a trunk of another size, from random weights: no package can warm it
        if args.init or args.init_ckpt or args.init_readout_ckpt:
            raise UnifiedReadoutError("--scratch-arch takes no init")
        arch = dict(bs.DEFAULT_ARCH)
        for item in args.scratch_arch.split(","):
            k, v = item.split("=")
            if k not in arch:
                raise UnifiedReadoutError(f"--scratch-arch: unknown key {k}")
            arch[k] = type(arch[k])(int(v))
        model = build(arch)
        init = {"sha256": "scratch:" + json.dumps(arch, sort_keys=True)}
    elif args.init_readout_ckpt:
        if args.init or args.init_ckpt:
            raise UnifiedReadoutError("--init-readout-ckpt is the whole init")
        model, _ = load_checkpoint(args.init_readout_ckpt)
        model.train()
        init = {"sha256": "readout-ckpt:" + us.sha256_file(args.init_readout_ckpt)}
    else:
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
    calib = us.load_calib(args.calib_data or args.data, verified, index, max_rows=args.calib_rows, seed=args.seed,
                          exclude_seed_windows=args.exclude_seed_window)
    started = time.time()
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
        if step < args.head_warmup_buffers and not args.scratch_arch and not args.init_readout_ckpt:
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
                if (out / "STOP").exists() or (args.max_seconds and time.time() - started > args.max_seconds):
                    save()
                    _status(status, f"STOPPED at epoch {epoch + 1} buffer {gi}/{n_buffers} (STOP file or --max-seconds); checkpoint saved")
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


# ------------------------------------------------------------------ head-only polish on a frozen trunk

BODY_PREFIXES = ("stem.", "ln.", "up.", "down.", "out_ln.", "value.", "reply.")


def cache_arrays(model, part, *, rounds_per_batch: int = 32) -> dict[str, np.ndarray]:
    """One part's rows as the polish reads them: the frozen per-decision projections (float16) and
    every leaf (row index, planes, scalars, outcome target, reply)."""
    import torch
    n = len(part["X"])
    dp, dc = model.config["readout"]["dp"], model.config["readout"]["dc"]
    out = {"S": np.zeros((n, N_CARDS, dp), np.float16), "c": np.zeros((n, dc), np.float16)}
    leaves = {k: [] for k in ("row", "planes", "scalars", "target", "reply", "reply_hand", "has_reply")}
    with torch.no_grad():
        for rids, rows in bs.round_batches(part, rounds_per_batch, None):
            b = make_batch(part, rids, rows)
            tb = us.to_device(b, "cpu")
            _, _, q, g = us.trunk_forward(model.trunk, tb)
            S, c = model.readout.project(q, g)
            out["S"][rows] = S.numpy().astype(np.float16)
            out["c"][rows] = c.numpy().astype(np.float16)
            leaves["row"].append(np.asarray(rows, np.int64)[b["leaf_row"]].astype(np.int32))
            leaves["planes"].append(b["leaf_planes"].astype(np.uint8))
            leaves["scalars"].append(b["leaf_scalars"].astype(np.float32))
            leaves["target"].append(b["q_target"][b["leaf_row"]].astype(np.int16))
            leaves["reply"].append(b["leaf_reply"].astype(np.uint8))
            leaves["reply_hand"].append(b["leaf_reply_hand"])
            leaves["has_reply"].append(b["leaf_has_reply"])
    out.update({"leaf_" + k: np.concatenate(v) for k, v in leaves.items()})
    return out


def cache(args) -> int:
    """Write the polish cache of a checkpoint: ``OUT/calib-0000.npz`` (the trainer's calibration rows) and
    ``OUT/train-NNNN.npz`` (consecutive groups of ``--group-chunks`` train chunks; ``--worker I --workers N``
    takes every N-th group).  A shard that exists is kept."""
    import torch
    torch.set_num_threads(args.threads)
    model, _ = load_checkpoint(args.ckpt)
    verified = bs._Verified()
    index = us.OutcomeIndex(us.parse_store_map(args.store_map))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    def write(name, part):
        tmp = out / (name + ".tmp.npz")
        np.savez(tmp, **cache_arrays(model, part))
        os.replace(tmp, out / (name + ".npz"))
    if args.worker == 0 and not (out / "calib-0000.npz").exists():
        write("calib-0000", us.load_calib(args.data, verified, index, max_rows=args.calib_rows, seed=args.seed,
                                          exclude_seed_windows=args.exclude_seed_window))
    entries = us.entries_for(args.data, "train", exclude_seed_windows=args.exclude_seed_window)
    groups = [entries[i:i + args.group_chunks] for i in range(0, len(entries), args.group_chunks)]
    if args.max_groups:
        groups = groups[:args.max_groups]
    for gi in range(args.worker, len(groups), args.workers):
        name = f"train-{gi:04d}"
        if (out / (name + ".npz")).exists():
            continue
        parts = [us.load_unified_part(e, verified, index) for e in groups[gi]]
        parts = [p for p in parts if len(p["X"])]
        if parts:
            write(name, bs.concat_parts(parts))
        print(f"[cache] {name} of {len(groups)}", flush=True)
    (out / f"DONE.{args.worker}").write_text(json.dumps({"groups": len(groups), "chunks": len(entries)}))
    return 0


def _polish_tensors(z, pick=None):
    import torch
    row = z["leaf_row"] if pick is None else z["leaf_row"][pick]
    get = lambda k: z[k] if pick is None else z[k][pick]
    return (torch.from_numpy(z["S"][row].astype(np.float32)), torch.from_numpy(z["c"][row].astype(np.float32)),
            torch.from_numpy(get("leaf_planes").astype(np.float32)), torch.from_numpy(get("leaf_scalars")),
            torch.from_numpy(get("leaf_target").astype(np.int64)), torch.from_numpy(get("leaf_reply").astype(np.float32)),
            torch.from_numpy(get("leaf_reply_hand")), torch.from_numpy(get("leaf_has_reply")))


def polish_losses(readout, t):
    """Per-leaf outcome CE and reply CE (zero where there is no reply) of cached leaves."""
    out = aux_polish_losses(readout, None, t, None)
    return out["v_ce"], out["r_ce"], out["end"], out["has"]


# Auxiliary heads on the readout's per-leaf features (polish only; default off).
#: ``smv``: a second 204-class outcome head trained on the search's own expected signed level for the
#: PLAYED action (two-point target on the half-integer support) at each row's k = 0 leaf (the played
#: action's afterstate); ``points``: final attacker points / 100 (Huber, delta 1) at every leaf.  Neither
#: is exported: the package keeps the outcome and reply outputs.
AUX_KINDS = ("smv", "points")
AUX_SCHEMA = "shengji-unified-readout-aux-v1"


def build_aux_heads(width: int, kinds: Sequence[str], seed: int = 1):
    import torch
    from torch import nn
    g = torch.random.fork_rng()
    with g:
        torch.manual_seed(seed)
        heads = nn.ModuleDict({k: nn.Linear(int(width), OUTCOME_CLASSES if k == "smv" else 1) for k in kinds})
    return heads


def smv_soft_targets(level, realised):
    """``(probs (L, 204), used (L,))``: the two-point target of each finite ``level`` (the acting side's
    expected signed level) inside the support; ``used`` is False where the level is NaN or off-support."""
    import torch
    from .search_mean_target import soft_targets
    mean = torch.full_like(level, float("nan"))
    return soft_targets(mean, torch.zeros_like(level, dtype=torch.bool), realised, level)


def aux_polish_losses(readout, heads, t, a) -> dict:
    """Per-leaf losses of cached leaves: outcome CE ``v_ce``, reply CE ``r_ce``, and for each auxiliary head
    in ``heads``: ``smv_ce`` (zero off ``smv_mask``: k = 0 leaves with a search value) and ``points_err``
    (Huber) / ``points_abs``.  ``a`` holds the leaves' ``smv`` and ``points`` targets."""
    import torch
    S, c, planes, scalars, target, reply, hand, has = t
    h = readout.features(S, c, planes, scalars)
    v, r = readout.value(h), readout.reply(h)
    v_ce = torch.nn.functional.cross_entropy(v, target, reduction="none")
    rl = torch.log_softmax(r.masked_fill(~hand, -1e9), -1)
    r_ce = -((reply / reply.sum(-1, keepdim=True).clamp_min(1.0)) * rl).sum(-1) * has
    out = {"v_ce": v_ce, "r_ce": r_ce, "end": scalars[:, 2] > 0, "has": has}
    if heads is None:
        return out
    if "smv" in heads:
        k0 = (scalars[:, 0] - 0.25).abs() < 1e-6                      # one play since the decision: the row's own
        probs, used = smv_soft_targets(a["smv"], target)
        mask = k0 & used
        ce = -(probs * torch.log_softmax(heads["smv"](h), -1)).sum(-1)
        out["smv_ce"] = torch.where(mask, ce, torch.zeros_like(ce))
        out["smv_mask"] = mask
    if "points" in heads:
        pred = heads["points"](h).squeeze(-1)
        out["points_err"] = torch.nn.functional.huber_loss(pred, a["points"], delta=1.0, reduction="none")
        out["points_abs"] = (pred - a["points"]).abs()
    return out


def _aux_tensors(aux, z, pick):
    import torch
    if aux is None:
        return None
    row = z["leaf_row"][pick]
    return {k: torch.from_numpy(np.asarray(aux[k][row], np.float32)) for k in AUX_KINDS}


def _aux_for(aux_dir, shard: Path, rows: int):
    """The aux targets of one cache shard (``aux-<name>.npz``), refusing a row-count mismatch."""
    if aux_dir is None:
        return None
    path = Path(aux_dir) / f"aux-{shard.stem}.npz"
    with np.load(path) as z:
        got = {k: z[k] for k in AUX_KINDS}
    if any(len(v) != rows for v in got.values()):
        raise UnifiedReadoutError(f"{path}: aux rows differ from the cache shard's {rows}")
    return got


def polish_eval(readout, z, batch: int = 16384, heads=None, aux=None) -> dict[str, float]:
    import torch
    sums = np.zeros(11)
    readout.eval()
    with torch.no_grad():
        for i in range(0, len(z["leaf_row"]), batch):
            pick = np.arange(i, min(i + batch, len(z["leaf_row"])))
            o = aux_polish_losses(readout, heads, _polish_tensors(z, pick), _aux_tensors(aux, z, pick))
            v, r, end, has = o["v_ce"], o["r_ce"], o["end"], o["has"]
            sums[:6] += [float(v.sum()), len(v), float((v * end).sum()), float(end.sum()), float(r.sum()), float(has.sum())]
            if "smv_ce" in o:
                m = o["smv_mask"]
                sums[6:9] += [float(o["smv_ce"].sum()), float(m.sum()), float((v * m).sum())]
            if "points_abs" in o:
                sums[9:11] += [float(o["points_abs"].sum()), len(v)]
    readout.train()
    out = {"leaf_value": sums[0] / max(sums[1], 1), "leaf_value_end": sums[2] / max(sums[3], 1), "reply": sums[4] / max(sums[5], 1)}
    if heads is not None and "smv" in heads:
        # the smv head's CE on its own soft target, and the outcome head's CE on the same leaves
        out.update(smv_ce=sums[6] / max(sums[7], 1), smv_leaves=int(sums[7]), leaf_value_on_smv_leaves=sums[8] / max(sums[7], 1))
    if heads is not None and "points" in heads:
        out["points_mae"] = sums[9] / max(sums[10], 1)
    return out


def polish(args) -> int:
    """Train the readout's per-leaf body on a cache (the trunk, the other heads and the per-decision
    projections stay the checkpoint's); ``OUT/best.pt`` is the checkpoint with the body of the pass that
    scored the lowest calibration trick-end NLL, or the input checkpoint when no pass beats it.
    ``--smv-weight`` / ``--points-weight`` (default 0) add auxiliary heads on the body's features, trained
    on the targets of ``--aux`` (``aux`` subcommand); selection stays the outcome head's trick-end NLL."""
    import torch
    torch.set_num_threads(args.threads)
    torch.manual_seed(args.seed)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    status = str(out / "status.log")
    model, saved = load_checkpoint(args.ckpt)
    readout = model.readout
    body = [p for n, p in readout.named_parameters() if n.startswith(BODY_PREFIXES)]
    frozen = [n for n, p in readout.named_parameters() if not n.startswith(BODY_PREFIXES)]
    if sorted(frozen) != ["card_ln.bias", "card_ln.weight", "card_proj.bias", "card_proj.weight", "ctx.bias", "ctx.weight"]:
        raise UnifiedReadoutError(f"unexpected frozen readout parameters {frozen}")
    weights = {"smv": getattr(args, "smv_weight", 0.0) or 0.0, "points": getattr(args, "points_weight", 0.0) or 0.0}
    kinds = [k for k in AUX_KINDS if weights[k] > 0]
    aux_dir = getattr(args, "aux", None)
    if kinds and not aux_dir:
        raise UnifiedReadoutError("an auxiliary head needs --aux")
    heads = build_aux_heads(model.config["readout"]["width"], kinds, args.seed) if kinds else None
    cache_dir = Path(args.cache)
    shards = sorted(cache_dir.glob("train-*.npz"))
    done = sorted(cache_dir.glob("DONE.*"))
    if not shards or not done:
        raise UnifiedReadoutError("the cache is incomplete")
    if kinds and (len(list(Path(aux_dir).glob("aux-train-*.npz"))) != len(shards) or not (Path(aux_dir) / "aux-calib-0000.npz").exists()):
        raise UnifiedReadoutError("--aux does not cover every cache shard")
    calib = dict(np.load(cache_dir / "calib-0000.npz"))
    calib_aux = _aux_for(aux_dir, cache_dir / "calib-0000.npz", len(calib["c"])) if kinds else None
    readout.train()
    params = body + (list(heads.parameters()) if heads is not None else [])
    opt = torch.optim.AdamW(params, lr=args.lr, weight_decay=args.weight_decay)
    total = args.epochs * len(shards)
    init = polish_eval(readout, calib, heads=heads, aux=calib_aux)
    best = {"score": init["leaf_value_end"], "epoch": 0, "calib": init}
    _status(status, f"POLISH START shards={len(shards)} epochs={args.epochs} body_params={sum(p.numel() for p in body)} "
                    f"aux={json.dumps({k: weights[k] for k in kinds})} "
                    f"ckpt={us.sha256_file(args.ckpt)} init calib {json.dumps(init)}")
    rng = np.random.default_rng(args.seed)
    step_i, t0 = 0, time.time()
    state = None
    for epoch in range(args.epochs):
        sums = np.zeros(10)
        for si in rng.permutation(len(shards)):
            for g in opt.param_groups:
                g["lr"] = args.lr * 0.5 * (1 + math.cos(math.pi * step_i / total))
            step_i += 1
            z = np.load(shards[si])
            z = {k: z[k] for k in z.files}
            za = _aux_for(aux_dir, shards[si], len(z["c"])) if kinds else None
            order = rng.permutation(len(z["leaf_row"]))
            for i in range(0, len(order), args.batch):
                pick = np.sort(order[i:i + args.batch])
                o = aux_polish_losses(readout, heads, _polish_tensors(z, pick), _aux_tensors(za, z, pick))
                v, r, end, has = o["v_ce"], o["r_ce"], o["end"], o["has"]
                loss = v.mean() + args.reply_weight * r.sum() / has.float().sum().clamp_min(1.0)
                if "smv_ce" in o:
                    loss = loss + weights["smv"] * o["smv_ce"].sum() / o["smv_mask"].float().sum().clamp_min(1.0)
                if "points_err" in o:
                    loss = loss + weights["points"] * o["points_err"].mean()
                opt.zero_grad()
                loss.backward()
                torch.nn.utils.clip_grad_norm_(params, 1.0)
                opt.step()
                sums[:6] += [float(v.sum().detach()), len(v), float((v * end).sum().detach()), float(end.sum()),
                             float(r.sum().detach()), float(has.sum())]
                if "smv_ce" in o:
                    sums[6:8] += [float(o["smv_ce"].sum().detach()), float(o["smv_mask"].sum())]
                if "points_err" in o:
                    sums[8:10] += [float(o["points_abs"].sum().detach()), len(v)]
            if (out / "STOP").exists():
                _status(status, "STOPPED (STOP file)")
                return 3
        cm = polish_eval(readout, calib, heads=heads, aux=calib_aux)
        train = {"leaf_value": sums[0] / max(sums[1], 1), "leaf_value_end": sums[2] / max(sums[3], 1), "reply": sums[4] / max(sums[5], 1)}
        if "smv" in kinds:
            train["smv_ce"] = sums[6] / max(sums[7], 1)
        if "points" in kinds:
            train["points_mae"] = sums[8] / max(sums[9], 1)
        _status(status, f"POLISH EPOCH {epoch + 1} train {json.dumps({k: round(v, 5) for k, v in train.items()})} "
                        f"calib {json.dumps({k: round(v, 5) for k, v in cm.items()})} ({time.time() - t0:.0f}s)")
        if cm["leaf_value_end"] < best["score"]:
            best = {"score": cm["leaf_value_end"], "epoch": epoch + 1, "calib": cm}
            state = {k: v.detach().clone() for k, v in model.state_dict().items()}
            if heads is not None:
                best["aux_heads"] = {k: v.detach().clone() for k, v in heads.state_dict().items()}
    if state is not None:
        model.load_state_dict(state)
    extra = {}
    if heads is not None:
        extra = {"aux_heads": best.get("aux_heads"), "aux": {"schema": AUX_SCHEMA, "kinds": kinds, "weights": {k: weights[k] for k in kinds}}}
    torch.save({"schema": CKPT_SCHEMA, "model": model.state_dict(), "config": model.config, "epoch": saved.get("epoch"),
                "calib": dict(saved.get("calib") or {}, polish=best["calib"], polish_epoch=best["epoch"]),
                "init_calib": saved.get("init_calib"), "run": dict(saved.get("run") or {}, polish=vars(args)), **extra}, out / "best.pt")
    _status(status, f"POLISH DONE best_epoch={best['epoch']} calib {json.dumps(best['calib'])} sha256={us.sha256_file(out / 'best.pt')}")
    return 0


# Auxiliary targets for a polish cache: the search's value of the played action, final points.

def cluster_search_values(path: Path, sha256: str | None = None) -> dict[str, np.ndarray]:
    """One store cluster's play decisions in the extractor's order (``belief_labels.game_order``, the
    ``decision`` index of an extract row): ``seat``, ``round_index``, ``seed`` and ``smv`` (the search's
    refined mean of the played action, ``preference.means[played_index]``, NaN where absent).  Refuses a
    file whose sha256 is not ``sha256``, or a decision whose value units are not signed level."""
    import hashlib
    from .belief_labels import game_order
    raw = Path(path).read_bytes()
    if sha256 is not None and hashlib.sha256(raw).hexdigest() != sha256:
        raise UnifiedReadoutError(f"{path}: sha256 differs from the store manifest")
    plays = [r for r in (json.loads(line) for line in raw.decode().splitlines() if line.strip())
             if r.get("decision_kind") == "play"]
    seat, rnd, seed, smv = [], [], [], []
    ri = -1
    for r in game_order(plays):
        if not (r.get("plays_prefix") or []):
            ri += 1
        units = (r.get("action_values") or {}).get("units") if isinstance(r.get("action_values"), dict) else None
        pref = r.get("preference") or {}
        means, pi = pref.get("means"), pref.get("played_index")
        value = float("nan")
        if isinstance(means, list) and pi is not None and 0 <= int(pi) < len(means) and means[int(pi)] is not None:
            if units != "expected-signed-level-half-integer":
                raise UnifiedReadoutError(f"{path}: a search value in units {units!r}, not signed level")
            value = float(means[int(pi)])
        seat.append(int(r["seat"]))
        rnd.append(ri)
        seed.append(int(r.get("round_seed")))
        smv.append(value)
    return {"seat": np.asarray(seat, np.int64), "round_index": np.asarray(rnd, np.int64),
            "seed": np.asarray(seed, np.int64), "smv": np.asarray(smv, np.float64)}


class SearchValueIndex:
    """``cluster_search_values`` of store clusters, kept as ``MEANS/<store key>-<cluster>.npz`` files."""

    def __init__(self, index, means_dir: str | os.PathLike):
        self.index = index
        self.dir = Path(means_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self._mem: dict = {}

    def get(self, recorded: str, cluster: int, data_dir: str) -> dict[str, np.ndarray]:
        import hashlib
        local = self.index.resolve(recorded, data_dir)
        key = (local, int(cluster))
        if key in self._mem:
            return self._mem[key]
        st = self.index._store(local)
        name = st["names"][int(cluster)]
        path = self.dir / f"{hashlib.sha256(local.encode()).hexdigest()[:16]}-{int(cluster):06d}.npz"
        if path.exists():
            with np.load(path) as z:
                got = {k: z[k] for k in z.files}
            if str(got.pop("shard_sha256")) != st["by_name"][name]["sha256"]:
                raise UnifiedReadoutError(f"{path}: made from another shard")
        else:
            got = cluster_search_values(Path(local) / "shards" / name, st["by_name"][name]["sha256"])
            tmp = path.with_suffix(".tmp.npz")
            np.savez(tmp, shard_sha256=np.asarray(st["by_name"][name]["sha256"]), **got)
            os.replace(tmp, path)
        self._mem = {key: got}                          # one cluster at a time: parts are cluster-ordered
        return got


def part_aux_targets(part, stores: Sequence[str], index, values: SearchValueIndex, data_dir: str) -> dict[str, np.ndarray]:
    """``smv`` (the search's value of the row's own play, acting side, NaN where absent) and ``points``
    (final attacker points / 100) of a loaded part's rows; refuses a row whose seat, round or seed is not
    its store decision's, or whose outcome target is not its round's points."""
    n = len(part["X"])
    smv = np.full(n, np.nan, np.float32)
    points = np.full(n, np.nan, np.float32)
    key = np.stack([part["store"].astype(np.int64), part["cluster"].astype(np.int64)], 1)
    for s, c in (np.unique(key, axis=0) if n else ()):
        sel = np.flatnonzero((key[:, 0] == s) & (key[:, 1] == c))
        sv = values.get(stores[int(s)], int(c), data_dir)
        d = part["decision"][sel].astype(np.int64)
        if np.any(d < 0) or np.any(d >= len(sv["seat"])):
            raise UnifiedReadoutError(f"store {s} cluster {c}: a decision index outside the store's")
        if (np.any(sv["seat"][d] != part["row_seat"][sel]) or np.any(sv["round_index"][d] != part["round_index"][sel])
                or np.any(sv["seed"][d] != part["seed"][sel].astype(np.int64))):
            raise UnifiedReadoutError(f"store {s} cluster {c}: a row's seat, round or seed differs from its store decision")
        smv[sel] = sv["smv"][d]
        rounds = index.rounds(stores[int(s)], int(c), data_dir)
        for r in np.unique(part["round_index"][sel]):
            rows = sel[part["round_index"][sel] == r]
            ap = int(rounds[int(r)]["attacker_points"])
            points[rows] = ap / 100.0
            banker = int(rounds[int(r)]["banker"])
            for att in (True, False):
                m = (part["row_seat"][rows].astype(np.int64) % 2 != banker % 2) == att
                if np.any(part["q_target"][rows[m]] != us.outcome_category(ap, att)):
                    raise UnifiedReadoutError(f"store {s} cluster {c} round {r}: outcome target differs from its points")
    if np.any(~np.isfinite(points)):
        raise UnifiedReadoutError("rows without points")
    return {"smv": smv, "points": points}


def aux(args) -> int:
    """Write ``OUT/aux-<shard>.npz`` (per-row ``smv`` and ``points``) for every shard of the polish cache
    ``--cache`` that ``cache`` wrote with the same ``--data`` / ``--store-map`` / ``--exclude-seed-window`` /
    ``--calib-rows`` / ``--seed`` / ``--group-chunks``; refuses a shard whose rows or outcome targets differ."""
    verified = bs._Verified()
    index = us.OutcomeIndex(us.parse_store_map(args.store_map))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    values = SearchValueIndex(index, out / "means")
    cache_dir = Path(args.cache)

    def write(name, parts):
        got = [part_aux_targets(p, p["_stores"], index, values, p["_data_dir"]) for p in parts]
        a = {k: np.concatenate([g[k] for g in got]) for k in AUX_KINDS}
        with np.load(cache_dir / f"{name}.npz") as z:
            lr, lt, nrow = z["leaf_row"], z["leaf_target"], len(z["c"])
        qt = np.concatenate([p["q_target"] for p in parts])
        if nrow != len(qt) or np.any(qt[lr] != lt):
            raise UnifiedReadoutError(f"{name}: the parts do not reproduce the cache shard's rows")
        meta = {"schema": AUX_SCHEMA, "rows": int(nrow), "smv_rows": int(np.isfinite(a["smv"]).sum())}
        tmp = out / f"aux-{name}.tmp.npz"
        np.savez(tmp, meta=np.asarray(json.dumps(meta)), **a)
        os.replace(tmp, out / f"aux-{name}.npz")

    def loaded(entries):
        parts = []
        for e in entries:
            p = us.load_unified_part(e, verified, index)
            if len(p["X"]):
                p["_stores"], p["_data_dir"] = e["stores"], e["dir"]
                parts.append(p)
        return parts
    if args.worker == 0 and not (out / "aux-calib-0000.npz").exists():
        # load_calib's chunk choice, part by part (its rows are those parts in that order)
        entries = us.entries_for(args.data, "calib", exclude_seed_windows=args.exclude_seed_window)
        if args.calib_rows is not None:
            rng = np.random.default_rng(args.seed)
            picked, n = [], 0
            for i in rng.permutation(len(entries)):
                if n >= args.calib_rows:
                    break
                picked.append(entries[i])
                n += entries[i]["rows"]
            entries = picked
        write("calib-0000", loaded(entries))
    entries = us.entries_for(args.data, "train", exclude_seed_windows=args.exclude_seed_window)
    groups = [entries[i:i + args.group_chunks] for i in range(0, len(entries), args.group_chunks)]
    if args.max_groups:
        groups = groups[:args.max_groups]
    for gi in range(args.worker, len(groups), args.workers):
        name = f"train-{gi:04d}"
        if (out / f"aux-{name}.npz").exists():
            continue
        parts = loaded(groups[gi])
        if parts:
            write(name, parts)
        print(f"[aux] {name} of {len(groups)}", flush=True)
    (out / f"DONE.{args.worker}").write_text(json.dumps({"groups": len(groups), "chunks": len(entries)}))
    return 0


# ------------------------------------------------------------------ the mixture objective on sampled worlds

def mixture_nll(value_logits, target):
    """Per-decision NLL of the outcome under the MIXTURE of its worlds' distributions: ``value_logits`` is
    ``(n, K, 204)`` (one leaf per sampled world), the result ``-log mean_k softmax(logits_k)[target]``.  The
    mixture's expected level is the mean of the worlds' expected levels, which is what the search averages."""
    import torch
    logp = torch.log_softmax(value_logits, -1)
    pick = logp.gather(-1, target[:, None, None].expand(-1, logp.shape[1], 1)).squeeze(-1)      # n,K
    return -(torch.logsumexp(pick, 1) - math.log(logp.shape[1]))


def mix_forward(readout, z, pick):
    """``(n, K, 204)`` leaf outcome logits of the picked decisions of a sampled-world shard, their true-world
    leaf's ``(n, 204)`` logits, and the targets."""
    import torch
    S = torch.from_numpy(z["S"][pick].astype(np.float32))
    c = torch.from_numpy(z["c"][pick].astype(np.float32))
    planes = torch.from_numpy(z["planes"][pick].astype(np.float32))                # n,K,9,54
    scalars = torch.from_numpy(z["scalars"][pick])
    n, K = planes.shape[:2]
    v, _ = readout.body(S.repeat_interleave(K, 0), c.repeat_interleave(K, 0), planes.flatten(0, 1), scalars.flatten(0, 1))
    tv, _ = readout.body(S, c, torch.from_numpy(z["tplanes"][pick].astype(np.float32)), torch.from_numpy(z["tscalars"][pick]))
    return v.view(n, K, -1), tv, torch.from_numpy(z["target"][pick].astype(np.int64))


def mix_eval(readout, shards, batch: int = 64) -> dict[str, float]:
    """Mean mixture NLL and true-world NLL over every decision of ``shards``."""
    import torch
    sums = np.zeros(3)
    readout.eval()
    with torch.no_grad():
        for path in shards:
            z = np.load(path)
            z = {k: z[k] for k in z.files}
            for i in range(0, len(z["target"]), batch):
                v, tv, t = mix_forward(readout, z, np.arange(i, min(i + batch, len(z["target"]))))
                sums += [float(mixture_nll(v, t).sum()), float(torch.nn.functional.cross_entropy(tv, t, reduction="sum")), len(t)]
    readout.train()
    return {"mixture_nll": sums[0] / max(sums[2], 1), "true_nll": sums[1] / max(sums[2], 1), "decisions": int(sums[2])}


def mixpolish(args) -> int:
    """Train the readout's per-leaf body on the mixture objective: every step takes ``--decisions`` decisions
    of a sampled-world shard (mixture NLL over their K worlds) and ``--batch`` true-world leaves of the polish
    cache (outcome CE x ``--true-weight``, reply CE x ``--reply-weight``).  After every pass the calibration
    shards' mixture NLL is scored; ``OUT/best.pt`` carries the body of the pass with the lowest, or the input
    checkpoint's when no pass beats it."""
    import torch
    torch.set_num_threads(args.threads)
    torch.manual_seed(args.seed)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    status = str(out / "status.log")
    model, saved = load_checkpoint(args.ckpt)
    readout = model.readout
    body = [p for n, p in readout.named_parameters() if n.startswith(BODY_PREFIXES)]
    mix = sorted(Path(args.mix).glob("train-*.npz"))
    calib = sorted(Path(args.mix).glob("calib-*.npz"))
    cache = sorted(Path(args.cache).glob("train-*.npz"))
    if not mix or not calib or not cache:
        raise UnifiedReadoutError("mixpolish needs train and calib sampled-world shards and the polish cache")
    readout.train()
    opt = torch.optim.AdamW(body, lr=args.lr, weight_decay=args.weight_decay)
    total = args.epochs * len(mix)
    init = mix_eval(readout, calib)
    best = {"score": init["mixture_nll"], "epoch": 0, "calib": init}
    _status(status, f"MIXPOLISH START mix_shards={len(mix)} calib_shards={len(calib)} cache_shards={len(cache)} epochs={args.epochs} "
                    f"ckpt={us.sha256_file(args.ckpt)} init calib {json.dumps(init)}")
    rng = np.random.default_rng(args.seed)
    step_i, t0, state = 0, time.time(), None
    for epoch in range(args.epochs):
        sums = np.zeros(6)
        for si in rng.permutation(len(mix)):
            for g in opt.param_groups:
                g["lr"] = args.lr * 0.5 * (1 + math.cos(math.pi * step_i / total))
            step_i += 1
            z = np.load(mix[si])
            z = {k: z[k] for k in z.files}
            cz = np.load(cache[rng.integers(len(cache))])
            cz = {k: cz[k] for k in cz.files}
            order = rng.permutation(len(z["target"]))
            for i in range(0, len(order), args.decisions):
                v, tv, t = mix_forward(readout, z, np.sort(order[i:i + args.decisions]))
                m_nll = mixture_nll(v, t)
                v_ce, r_ce, _, has = polish_losses(readout, _polish_tensors(cz, np.sort(rng.choice(len(cz["leaf_row"]), size=min(args.batch, len(cz["leaf_row"])), replace=False))))
                loss = m_nll.mean() + args.true_weight * v_ce.mean() + args.reply_weight * r_ce.sum() / has.float().sum().clamp_min(1.0)
                opt.zero_grad()
                loss.backward()
                torch.nn.utils.clip_grad_norm_(body, 1.0)
                opt.step()
                sums += [float(m_nll.sum().detach()), len(t), float(v_ce.sum().detach()), len(v_ce), float(r_ce.sum().detach()), float(has.sum())]
            if (out / "STOP").exists():
                _status(status, "STOPPED (STOP file)")
                return 3
        cm = mix_eval(readout, calib)
        train = {"mixture_nll": sums[0] / max(sums[1], 1), "true_leaf_ce": sums[2] / max(sums[3], 1), "reply": sums[4] / max(sums[5], 1)}
        _status(status, f"MIXPOLISH EPOCH {epoch + 1} train {json.dumps({k: round(v, 5) for k, v in train.items()})} "
                        f"calib {json.dumps({k: round(v, 5) for k, v in cm.items()})} ({time.time() - t0:.0f}s)")
        if cm["mixture_nll"] < best["score"]:
            best = {"score": cm["mixture_nll"], "epoch": epoch + 1, "calib": cm}
            state = {k: v.detach().clone() for k, v in model.state_dict().items()}
    if state is not None:
        model.load_state_dict(state)
    torch.save({"schema": CKPT_SCHEMA, "model": model.state_dict(), "config": model.config, "epoch": saved.get("epoch"),
                "calib": dict(saved.get("calib") or {}, mixpolish=best["calib"], mixpolish_epoch=best["epoch"], mixpolish_init=init),
                "init_calib": saved.get("init_calib"), "run": dict(saved.get("run") or {}, mixpolish=vars(args))}, out / "best.pt")
    _status(status, f"MIXPOLISH DONE best_epoch={best['epoch']} init {json.dumps(init)} calib {json.dumps(best['calib'])} "
                    f"sha256={us.sha256_file(out / 'best.pt')}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="unified_readout")
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("train")
    t.add_argument("--data", nargs="+", required=True)
    t.add_argument("--out", required=True)
    t.add_argument("--init", default=None, help="a served-shape belief package whose trunk warms the trunk")
    t.add_argument("--init-readout-ckpt", default=None, help="a unified_readout checkpoint: warms the whole model")
    t.add_argument("--scratch-arch", default=None, help="d=..,heads=..,enc_layers=..,xattn_layers=..,x_hidden=..: random init at that size")
    t.add_argument("--calib-data", nargs="+", default=None, help="the dirs whose calib split is scored (default: --data)")
    t.add_argument("--max-seconds", type=float, default=None, help="save and exit 3 at the next buffer after this long (resume continues)")
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
    c = sub.add_parser("cache")
    c.add_argument("--ckpt", required=True)
    c.add_argument("--data", nargs="+", required=True)
    c.add_argument("--out", required=True)
    c.add_argument("--store-map", action="append", default=[])
    c.add_argument("--exclude-seed-window", type=bs.seed_window, action="append", default=[])
    c.add_argument("--calib-rows", type=int, default=180000)
    c.add_argument("--seed", type=int, default=1)
    c.add_argument("--group-chunks", type=int, default=24)
    c.add_argument("--max-groups", type=int, default=None, help="only the first groups (smoke)")
    c.add_argument("--worker", type=int, default=0)
    c.add_argument("--workers", type=int, default=1)
    c.add_argument("--threads", type=int, default=8)
    p = sub.add_parser("polish")
    p.add_argument("--ckpt", required=True)
    p.add_argument("--cache", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--epochs", type=int, default=12)
    p.add_argument("--lr", type=float, default=1e-3)
    p.add_argument("--weight-decay", type=float, default=0.01)
    p.add_argument("--reply-weight", type=float, default=0.2)
    p.add_argument("--batch", type=int, default=4096)
    p.add_argument("--threads", type=int, default=16)
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--aux", default=None, help="the aux targets dir (aux subcommand) the auxiliary heads train on")
    p.add_argument("--smv-weight", type=float, default=0.0, help="the search-value head's weight (0: no head)")
    p.add_argument("--points-weight", type=float, default=0.0, help="the attacker-points head's weight (0: no head)")
    x = sub.add_parser("aux")
    x.add_argument("--cache", required=True)
    x.add_argument("--data", nargs="+", required=True)
    x.add_argument("--out", required=True)
    x.add_argument("--store-map", action="append", default=[])
    x.add_argument("--exclude-seed-window", type=bs.seed_window, action="append", default=[])
    x.add_argument("--calib-rows", type=int, default=180000)
    x.add_argument("--seed", type=int, default=1)
    x.add_argument("--group-chunks", type=int, default=24)
    x.add_argument("--max-groups", type=int, default=None)
    x.add_argument("--worker", type=int, default=0)
    x.add_argument("--workers", type=int, default=1)
    m = sub.add_parser("mixpolish")
    m.add_argument("--ckpt", required=True)
    m.add_argument("--mix", required=True, help="sampled-world shards: train-*.npz and calib-*.npz")
    m.add_argument("--cache", required=True, help="the polish cache (true-world leaves, replies)")
    m.add_argument("--out", required=True)
    m.add_argument("--epochs", type=int, default=4)
    m.add_argument("--lr", type=float, default=3e-4)
    m.add_argument("--weight-decay", type=float, default=0.01)
    m.add_argument("--true-weight", type=float, default=0.25)
    m.add_argument("--reply-weight", type=float, default=0.2)
    m.add_argument("--decisions", type=int, default=256)
    m.add_argument("--batch", type=int, default=4096)
    m.add_argument("--threads", type=int, default=16)
    m.add_argument("--seed", type=int, default=1)
    e = sub.add_parser("export")
    e.add_argument("--ckpt", required=True)
    e.add_argument("--out", required=True)
    e.add_argument("--temperature", type=float, required=True, help="the belief output's temperature")
    e.add_argument("--note", default="")
    return ap


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return {"train": train, "export": export, "cache": cache, "polish": polish, "mixpolish": mixpolish, "aux": aux}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
