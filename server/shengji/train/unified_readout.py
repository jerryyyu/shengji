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

``train``, ``cache`` and ``polish`` take ``--device {cpu,mps}`` (default ``cpu``, the path every earlier run
took).  Batches are built on the CPU and moved to the device; every checkpoint is written with CPU tensors.
A non-CPU run records its device in its identity, so a resume on another device refuses.  An op the MPS
backend lacks raises; PyTorch's CPU fallback runs only when ``PYTORCH_ENABLE_MPS_FALLBACK=1`` is set by the
caller, and the run's status log says so.
"""
from __future__ import annotations

import argparse
import hashlib
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

def build(arch: Mapping[str, Any], readout_arch: Mapping[str, Any] = READOUT_ARCH, *, outcome_history_width=None):
    import torch
    from torch import nn
    base = us.build_unified(arch, outcome_history_width=outcome_history_width)
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

        def body(self, S, c, planes, scalars):
            """The per-leaf part: each leaf's own ``(54, dp)`` card states and ``(dc,)`` context."""
            pooled = torch.bmm(planes, S) * POOL_SCALE                   # L,9,dp
            x = torch.cat([planes.flatten(1), scalars, pooled.flatten(1), c], -1)
            h = torch.relu(self.stem(x))
            for ln, up, down in zip(self.ln, self.up, self.down):
                h = h + down(torch.relu(up(ln(h))))
            h = self.out_ln(h)
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
            self.config = {"trunk": dict(base.trunk.config), "heads": dict(base.config["heads"]), "readout": ra}

        def forward(self, b):
            logits, enc, q, g = us.trunk_forward(self.trunk, b)
            frame = b["rr"] * 4 + b["seat"]
            ql = self.q_head(torch.cat([enc[frame, b["ply"], :outcome_history_width], g], -1).float())
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
    res = {"belief_sum": -(y * logp).sum(), "belief_n": y.sum(), "q_sum": q_ce.sum(), "p_sum": p_ce.sum(),
           "rows": torch.tensor(float(len(q_ce))), "v_sum": v_ce.sum(), "leaves": torch.tensor(float(len(v_ce))),
           "v0_sum": (v_ce * (tb["leaf_k"] == 0)).sum(), "ve_sum": (v_ce * tb["leaf_scalars"][:, 2]).sum(),
           "ends": tb["leaf_scalars"][:, 2].sum(), "r_sum": r_ce.sum(), "replies": has.float().sum(), "out": out}
    if "row_w" in tb:
        # each row's (and leaf's) loss times its corpus weight; the counts stay unweighted
        w = tb["row_w"].float()
        wl = w[tb["leaf_row"]]
        res.update({"belief_sum_w": -(w[:, 0, None, None] * y * logp).sum(), "q_sum_w": (w[:, 1] * q_ce).sum(),
                    "p_sum_w": (w[:, 2] * p_ce).sum(), "v_sum_w": (wl[:, 3] * v_ce).sum(),
                    "r_sum_w": (wl[:, 4] * r_ce).sum()})
    return res


SUM_KEYS = ("belief_sum", "belief_n", "q_sum", "p_sum", "rows", "v_sum", "leaves", "v0_sum", "ve_sum", "ends", "r_sum", "replies")


def objective(L, args):
    """The training loss: the five head means (corpus-weighted sums over unweighted counts when the
    batch carries ``row_w``), times the head weights."""
    m = means([L[k + "_w"] if k + "_w" in L else L[k] for k in SUM_KEYS])
    return (args.belief_weight * m["belief"] + args.q_weight * m["q"] + args.policy_weight * m["policy"]
            + args.value_weight * m["leaf_value"] + args.reply_weight * m["reply"])


def _backward_batch(model, b, device, args):
    """Accumulate one logical batch's gradient before the caller clips and steps."""
    limit = getattr(args, "microbatch_rounds", None)
    rounds = len(b["banker"])
    totals = dict(belief_n=float(b["Y"].sum(dtype=np.float64)), rows=len(b["rr"]),
                  leaves=len(b["leaf_row"]), replies=int(b["leaf_has_reply"].sum()))
    stats = np.zeros(len(SUM_KEYS))
    round_fields = {"tok_int", "tok_f", "tok_cards", "tok_att", "card_feat", "banker"}
    leaf_rounds = b["rr"][b["leaf_row"]]
    for start in range(0, rounds, limit):
        end = min(rounds, start + limit)
        rows = np.flatnonzero((b["rr"] >= start) & (b["rr"] < end))
        leaves = np.flatnonzero((leaf_rounds >= start) & (leaf_rounds < end))
        micro = {}
        for key, value in b.items():
            if key in round_fields:
                micro[key] = value[start:end]
            elif key.startswith("leaf_"):
                micro[key] = value[leaves]
            else:
                micro[key] = value[rows]
        micro["rr"] -= start
        micro["leaf_row"] = np.searchsorted(rows, micro["leaf_row"])
        loss = losses(model, us.to_device(micro, device))
        objective({**loss, **totals}, args).backward()
        stats += [float(loss[k].detach()) for k in SUM_KEYS]
        del loss
    return stats


#: the heads a corpus weight names, in the column order of ``row_w``
CORPUS_HEADS = ("belief", "q", "policy", "value", "reply")


def parse_corpus_weights(items: Sequence[str]) -> list[tuple[str, list[float]]]:
    """``PREFIX=head:w[,head:w...]`` items: rows of every data dir whose path starts with PREFIX weigh
    their loss on each named head by ``w`` (unnamed heads 1)."""
    spec = []
    for item in items:
        prefix, sep, rest = item.partition("=")
        if not sep or not prefix or not rest:
            raise UnifiedReadoutError(f"--corpus-weight {item!r}: expected PREFIX=head:w[,head:w...]")
        w = dict.fromkeys(CORPUS_HEADS, 1.0)
        for kv in rest.split(","):
            k, sep, v = kv.partition(":")
            if k not in w or not sep:
                raise UnifiedReadoutError(f"--corpus-weight {item!r}: unknown head {k!r} (heads {CORPUS_HEADS})")
            x = float(v)
            if not (math.isfinite(x) and x >= 0):
                raise UnifiedReadoutError(f"--corpus-weight {item!r}: weight {v!r} is not a finite number >= 0")
            w[k] = x
        spec.append((prefix.rstrip("/"), [w[h] for h in CORPUS_HEADS]))
    return spec


def weight_entries(entries, spec):
    """Tag every entry with its corpus weights (all ones where no prefix matches); refuses a dir that
    two prefixes match and a prefix that matches no dir.  No spec leaves the entries untouched."""
    if not spec:
        return entries
    unused = {p for p, _ in spec}
    for e in entries:
        hits = [(p, w) for p, w in spec if str(e["dir"]).rstrip("/").startswith(p)]
        if len(hits) > 1:
            raise UnifiedReadoutError(f"{e['dir']}: matched by more than one --corpus-weight prefix")
        e["corpus_w"] = list(hits[0][1]) if hits else [1.0] * len(CORPUS_HEADS)
        unused -= {p for p, _ in hits}
    if unused:
        raise UnifiedReadoutError(f"--corpus-weight prefixes match no data dir: {sorted(unused)}")
    return entries


def weight_summary(entries) -> dict[str, int]:
    """Rows per distinct weight vector (for the status line)."""
    out: dict[str, int] = {}
    for e in entries:
        k = ",".join(f"{h}:{w:g}" for h, w in zip(CORPUS_HEADS, e.get("corpus_w", [1.0] * len(CORPUS_HEADS))))
        out[k] = out.get(k, 0) + int(e["rows"])
    return out


def means(s) -> dict[str, float]:
    s = dict(zip(SUM_KEYS, s))
    return {"belief": s["belief_sum"] / max(s["belief_n"], 1.0), "q": s["q_sum"] / max(s["rows"], 1.0),
            "policy": s["p_sum"] / max(s["rows"], 1.0), "leaf_value": s["v_sum"] / max(s["leaves"], 1.0),
            "leaf_value_k0": s["v0_sum"] / max(s["rows"], 1.0), "leaf_value_end": s["ve_sum"] / max(s["ends"], 1.0), "reply": s["r_sum"] / max(s["replies"], 1.0)}


def evaluate(model, part, *, rounds_per_batch: int = 32, device="cpu") -> dict[str, float]:
    """Calibration-split means of every loss (identity relabeling) and the belief log-loss."""
    import torch
    sums = np.zeros(len(SUM_KEYS))
    n = len(part["X"])
    belief = np.empty((n, N_CARDS, 4), np.float32)
    model.eval()
    with torch.no_grad():
        for rids, rows in bs.round_batches(part, rounds_per_batch, None):
            L = losses(model, us.to_device(make_batch(part, rids, rows), device))
            sums += np.asarray([float(L[k]) for k in SUM_KEYS])
            belief[rows] = L["out"]["belief"].float().cpu().numpy()
    model.train()
    out = {k: round(float(v), 6) for k, v in means(sums).items()}
    out["belief_ll"] = mean_ll(masked_softmax(belief, part["M"]), part["Y"])
    return out


def _device(name: str, status: str | None = None):
    """The torch device of ``--device``; refuses ``mps`` where the backend is missing."""
    import torch
    if name == "cpu":
        return torch.device("cpu")
    if name != "mps":
        raise UnifiedReadoutError(f"--device {name}: not cpu or mps")
    if not torch.backends.mps.is_available():
        raise UnifiedReadoutError("--device mps: MPS is not available on this host")
    if os.environ.get("PYTORCH_ENABLE_MPS_FALLBACK") == "1":
        msg = "DEVICE mps with PYTORCH_ENABLE_MPS_FALLBACK=1: ops the MPS backend lacks run on the CPU"
        if status:
            _status(status, msg)
        else:
            print(msg, file=sys.stderr, flush=True)
    return torch.device("mps")


def _on_cpu(obj):
    """``obj`` (a state dict, optimizer state or nested container) with every tensor moved to the CPU."""
    import torch
    if isinstance(obj, torch.Tensor):
        return obj.detach().cpu()
    if isinstance(obj, dict):
        return {k: _on_cpu(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return type(obj)(_on_cpu(v) for v in obj)
    return obj


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
    if getattr(args, "microbatch_rounds", None) is not None:
        keys += ("microbatch_rounds",)
    if getattr(args, "corpus_weight", None):
        keys += ("corpus_weight",)
    run = {k: getattr(args, k) for k in keys}
    if getattr(args, "device", "cpu") != "cpu":
        run["device"] = args.device          # absent means cpu: a CPU run keeps the identity it always had
    if getattr(args, "report_buffer", None) is not None:
        run["report_buffer"] = args.report_buffer
    return json.loads(json.dumps(run, default=str))


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
    if getattr(args, "microbatch_rounds", None) is not None and args.microbatch_rounds < 1:
        raise UnifiedReadoutError("--microbatch-rounds must be positive")
    calib_rounds = min(getattr(args, "microbatch_rounds", None) or 32, 32)
    report_buffer = getattr(args, "report_buffer", None)
    pause_at_report = getattr(args, "pause_at_report", False)
    expect_resume_buffer = getattr(args, "expect_resume_buffer", None)
    capture_capacity = getattr(args, "capacity_stats", False)
    ck = out / "checkpoint.pt"
    if expect_resume_buffer is not None and (expect_resume_buffer < 0 or not ck.is_file()):
        raise UnifiedReadoutError("--expect-resume-buffer requires a nonnegative cursor and an existing checkpoint")
    if pause_at_report and report_buffer is None:
        raise UnifiedReadoutError("--pause-at-report requires --report-buffer")
    import torch
    torch.set_num_threads(args.threads)
    torch.manual_seed(args.seed)
    device = _device(args.device, status)
    verified = bs._Verified()
    index = us.OutcomeIndex(us.parse_store_map(args.store_map))
    entries = us._pick_entries(us.entries_for(args.data, "train", exclude_seed_windows=args.exclude_seed_window),
                               args.max_train_rows, args.seed)
    if not entries:
        raise UnifiedReadoutError("no train chunks")
    weight_entries(entries, parse_corpus_weights(args.corpus_weight))
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
    if device.type != "cpu":
        model.to(device)

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
    if report_buffer is not None and not 0 < report_buffer < n_buffers:
        raise UnifiedReadoutError("--report-buffer must be an interior buffer boundary")
    if expect_resume_buffer is not None and expect_resume_buffer >= n_buffers:
        raise UnifiedReadoutError("--expect-resume-buffer must be within the selected epoch")
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
        if getattr(args, "microbatch_rounds", None) is None:
            loss = losses(model, us.to_device(b, device))
            opt.zero_grad()
            objective(loss, args).backward()
        else:
            opt.zero_grad()
            stats = _backward_batch(model, b, device, args)
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        opt.step()
        if getattr(args, "microbatch_rounds", None) is None:
            return np.asarray([float(loss[k].detach()) for k in SUM_KEYS])
        return stats

    state = {"epoch": 0, "buffer": 0, "history": [], "best": float("inf")}
    recovery_digest = getattr(args, "recover_checkpoint_sha256", None)
    if ck.exists() or expect_resume_buffer is not None or recovery_digest is not None:
        with ck.open("rb") as checkpoint_file:
            if recovery_digest is not None:
                if hashlib.file_digest(checkpoint_file, "sha256").hexdigest() != recovery_digest:
                    raise UnifiedReadoutError("resume: checkpoint SHA256 mismatch")
                checkpoint_file.seek(0)
            saved = torch.load(checkpoint_file, weights_only=False, map_location="cpu")
        was = (saved.get("run") or {}).get("device", "cpu")
        if was != args.device:
            raise UnifiedReadoutError(f"resume: the checkpoint was trained with --device {was}, not --device {args.device}")
        if saved.get("run") != _run_identity(args):
            raise UnifiedReadoutError("resume: the run's settings differ from the checkpoint's")
        state = saved["state"]
        if recovery_digest is not None and (state["epoch"] != 0 or not 0 < state["buffer"] < n_buffers):
            raise UnifiedReadoutError("resume: recovery requires an interior first-epoch checkpoint")
        if expect_resume_buffer is not None and (state["epoch"] != 0 or state["buffer"] != expect_resume_buffer):
            raise UnifiedReadoutError(f"resume: expected epoch 0 buffer {expect_resume_buffer}, "
                                      f"found epoch {state['epoch']} buffer {state['buffer']}")
        model.load_state_dict(saved["model"])
        opt.load_state_dict(saved["opt"])
        _status(status, f"RESUME epoch {state['epoch']} buffer {state['buffer']}"
                        + ("" if device.type == "cpu" else f" device={args.device}"))
    else:
        state["init_calib"] = evaluate(model, calib, rounds_per_batch=calib_rounds, device=device)
        _status(status, f"{LANE} START params={sum(p.numel() for p in model.parameters())} "
                        f"readout_params={sum(p.numel() for p in model.readout.parameters())} rows={stream.rows} "
                        f"chunks={len(entries)} buffers={n_buffers} init={init['sha256']}"
                        + (f" corpus_weights={json.dumps(weight_summary(entries))}" if args.corpus_weight else "")
                        + ("" if device.type == "cpu" else f" device={args.device}"))
        (out / "run.json").write_text(json.dumps(_run_identity(args), indent=1))
        _status(status, f"INIT calib {json.dumps(state['init_calib'])}")
        if args.expect_init_belief_ll is not None and abs(state["init_calib"]["belief_ll"] - args.expect_init_belief_ll) > 5e-4:
            raise UnifiedReadoutError(f"init calib belief_ll {state['init_calib']['belief_ll']} != expected")

    def weights():
        return model.state_dict() if device.type == "cpu" else _on_cpu(model.state_dict())

    def save():
        tmp = out / "checkpoint.pt.tmp"
        torch.save({"model": weights(), "opt": opt.state_dict() if device.type == "cpu" else _on_cpu(opt.state_dict()),
                    "state": state, "config": model.config, "run": _run_identity(args)}, tmp)
        os.replace(tmp, ck)

    def save_best(epoch, cm):
        torch.save({"schema": CKPT_SCHEMA, "model": weights(), "config": model.config, "epoch": epoch,
                    "calib": cm, "init_calib": state.get("init_calib"), "run": _run_identity(args)}, out / "best.pt")

    def write_report(epoch, buffer, sums, *, steps=None):
        totals = dict(zip(SUM_KEYS, sums))
        report = {"epoch": epoch + 1, "completed_buffers": buffer, "rows": int(totals["rows"]),
                  "leaves": int(totals["leaves"]), "train": means(sums)}
        if steps is not None:
            report["steps"] = steps
        path = out / f"epoch-{epoch + 1}-buffer-{buffer}.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(report, allow_nan=False) + "\n")
        os.replace(tmp, path)

    def stopped():
        _status(status, f"STOPPED at epoch {state['epoch'] + 1} buffer {state['buffer']}/{n_buffers} "
                        "(STOP file or --max-seconds); checkpoint saved")
        return 3

    def capacity_sample(epoch, rows, steps, train_start, tensor_bytes, driver_bytes):
        train_seconds = time.monotonic() - train_start
        sample = dict(epoch=epoch + 1, rows=rows, steps=steps, train_seconds=train_seconds,
                      rows_per_second=rows / train_seconds, max_batch_rounds=max_batch_rounds)
        if device.type == "mps":
            sample.update(post_step_max_tensor_bytes=tensor_bytes, post_step_max_driver_bytes=driver_bytes)
        return sample

    def pause(capacity=None):
        if capacity is not None:
            write_report(0, report_buffer, state["epoch_sums"], steps=capacity["steps"])
        elif not capture_capacity or not (out / f"epoch-1-buffer-{report_buffer}.json").is_file():
            write_report(0, report_buffer, state["epoch_sums"])
        if (out / "STOP").exists():
            return stopped()
        if capacity is not None:
            _status(status, f"CAPACITY {json.dumps(capacity, allow_nan=False)}")
        _status(status, f"{LANE} PAUSED at epoch 1 buffer {report_buffer}/{n_buffers} "
                        "(report boundary); checkpoint saved")
        return 7

    if pause_at_report:
        if state["epoch"] or state["buffer"] > report_buffer:
            raise UnifiedReadoutError("resume: the checkpoint is past the requested report boundary")
        if state["buffer"] == report_buffer:
            return pause()

    last_save = time.time()
    while state["epoch"] < args.epochs:
        epoch, t0, sums, cur, steps = state["epoch"], time.time(), np.zeros(len(SUM_KEYS)), state["buffer"], 0
        if cur:
            if "epoch_sums" in state:
                sums[:] = state["epoch_sums"]
            elif report_buffer is not None:
                raise UnifiedReadoutError("resume: checkpoint lacks the sums for the requested buffer report")
            else:
                state["train_start_buffer"] = cur
                _status(status, f"epoch {epoch + 1} train metrics start at buffer {cur}: checkpoint lacks earlier sums")
        if capture_capacity:
            train_start = time.monotonic()
            trained_rows = tensor_bytes = driver_bytes = max_batch_rounds = 0
        for gi, b in stream.batches(args.seed, epoch, state["buffer"]):
            if gi != cur:
                if pause_at_report and gi > report_buffer:
                    raise UnifiedReadoutError("the stream skipped the requested report boundary")
                state["buffer"] = cur = gi
                state["epoch_sums"] = sums.tolist()
                if gi == report_buffer:
                    if pause_at_report:
                        capacity = (
                            capacity_sample(epoch, trained_rows, steps, train_start, tensor_bytes, driver_bytes)
                            if capture_capacity and steps else None
                        )
                        save()
                        return pause(capacity)
                    write_report(epoch, gi, sums)
                if time.time() - last_save > args.save_every:
                    save()
                    last_save = time.time()
                    _status(status, f"epoch {epoch + 1} buffer {gi}/{n_buffers} {json.dumps({k: round(v, 5) for k, v in means(sums).items()})}"
                                    f" ({time.time() - t0:.0f}s)")
                if (out / "STOP").exists() or (args.max_seconds and time.time() - started > args.max_seconds):
                    save()
                    return stopped()
            batch_sums = step_on(b, epoch * n_buffers + gi)
            sums += batch_sums
            if capture_capacity:
                max_batch_rounds = max(max_batch_rounds, len(b["tok_int"]))
                trained_rows += int(batch_sums[SUM_KEYS.index("rows")])
                if device.type == "mps":
                    tensor_bytes = max(tensor_bytes, torch.mps.current_allocated_memory())
                    driver_bytes = max(driver_bytes, torch.mps.driver_allocated_memory())
            steps += 1
            if args.max_steps and steps >= args.max_steps:
                break
        if pause_at_report:
            raise UnifiedReadoutError("training ended before the requested report boundary")
        if capture_capacity:
            capacity = capacity_sample(epoch, trained_rows, steps, train_start, tensor_bytes, driver_bytes)
            _status(status, f"CAPACITY {json.dumps(capacity, allow_nan=False)}")
        cm = evaluate(model, calib, rounds_per_batch=calib_rounds, device=device)
        state["history"].append({"epoch": epoch + 1, "train": means(sums), "calib": cm, "seconds": time.time() - t0})
        coverage = ""
        if "train_start_buffer" in state:
            start_buffer = state.pop("train_start_buffer")
            state["history"][-1]["train_start_buffer"] = start_buffer
            coverage = f" train_start_buffer={start_buffer}"
        state.pop("epoch_sums", None)
        _status(status, f"EPOCH {epoch + 1} train {json.dumps({k: round(v, 5) for k, v in means(sums).items()})} "
                        f"calib {json.dumps(cm)} steps={steps} ({time.time() - t0:.0f}s){coverage}")
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
    model = build(saved["config"]["trunk"], saved["config"]["readout"],
                  outcome_history_width=saved["config"].get("heads", {}).get("outcome_history_width"))
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


CACHE_DEFAULT_ENCODE_ROUNDS = 32


def cache_arrays(model, part, *, rounds_per_batch: int = CACHE_DEFAULT_ENCODE_ROUNDS,
                 device="cpu") -> dict[str, np.ndarray]:
    """One part's rows as the polish reads them: the frozen per-decision projections (float16) and
    every leaf (row index, planes, scalars, outcome target, reply)."""
    import torch
    n = len(part["X"])
    dp, dc = model.config["readout"]["dp"], model.config["readout"]["dc"]
    out = {"S": np.zeros((n, N_CARDS, dp), np.float16), "c": np.zeros((n, dc), np.float16)}
    leaves = {k: [] for k in ("row", "planes", "scalars", "target", "reply", "reply_hand", "has_reply")}
    leaf_offsets = []
    if "row_w" in part:
        leaves["w"] = []                                 # (L, 2): the value and reply corpus weights
    with torch.no_grad():
        for rids, rows in bs.round_batches(part, rounds_per_batch, None):
            b = make_batch(part, rids, rows)
            tb = us.to_device(b, device)
            _, _, q, g = us.trunk_forward(model.trunk, tb)
            S, c = model.readout.project(q, g)
            out["S"][rows] = S.cpu().numpy().astype(np.float16)
            out["c"][rows] = c.cpu().numpy().astype(np.float16)
            leaves["row"].append(np.asarray(rows, np.int64)[b["leaf_row"]].astype(np.int32))
            leaves["planes"].append(b["leaf_planes"].astype(np.uint8))
            leaves["scalars"].append(b["leaf_scalars"].astype(np.float32))
            leaves["target"].append(b["q_target"][b["leaf_row"]].astype(np.int16))
            leaves["reply"].append(b["leaf_reply"].astype(np.uint8))
            leaves["reply_hand"].append(b["leaf_reply_hand"])
            leaves["has_reply"].append(b["leaf_has_reply"])
            if rounds_per_batch != CACHE_DEFAULT_ENCODE_ROUNDS:
                leaf_offsets.append(b["leaf_k"])
            if "w" in leaves:
                leaves["w"].append(b["row_w"][b["leaf_row"]][:, [CORPUS_HEADS.index("value"), CORPUS_HEADS.index("reply")]]
                                   .astype(np.float32))
    order = None
    if leaf_offsets:
        # Preserve the logical batch's leaf order so encode sizing keeps polish minibatches fixed.
        leaf_rows = np.concatenate(leaves["row"])
        round_ids = part["row_round"]
        logical_batch = np.searchsorted(np.unique(round_ids), round_ids[leaf_rows]) // CACHE_DEFAULT_ENCODE_ROUNDS
        order = np.lexsort((leaf_rows, np.concatenate(leaf_offsets), logical_batch))
    for key, pieces in leaves.items():
        values = np.concatenate(pieces)
        out[f"leaf_{key}"] = values if order is None else values[order]
    return out


CACHE_DEVICE = "cache_device.json"


def _cache_has_output(out: Path) -> bool:
    return any(out.glob("calib-*.npz")) or any(out.glob("train-*.npz")) or any(out.glob("DONE.*"))


def _cache_marker(out: Path, name: str, payload: dict) -> dict:
    """Atomically bind a cache producer setting before any worker writes shards."""
    marker = out / name
    if not marker.exists():
        tmp = out / f"{name}.{os.getpid()}.tmp"
        tmp.write_text(json.dumps(payload))
        try:
            os.link(tmp, marker)
        except FileExistsError:
            pass
        except OSError:
            try:
                fd = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
                with os.fdopen(fd, "w") as fh:
                    fh.write(json.dumps(payload))
            except FileExistsError:
                pass
        finally:
            tmp.unlink()
    for _ in range(50):                              # the fallback writer may have opened the file without writing yet
        text = marker.read_text()
        if text:
            break
        time.sleep(0.1)
    return json.loads(text)


def bind_cache_device(out: Path, device: str) -> None:
    """A cache without a device record uses the legacy CPU producer."""
    marker = out / CACHE_DEVICE
    if device != "cpu" and not marker.exists() and _cache_has_output(out) and not marker.exists():
        raise UnifiedReadoutError(f"cache {out}: its shards carry no device and so are CPU output; "
                                  f"--device {device} would mix producers")
    was = _cache_marker(out, CACHE_DEVICE, {"device": device}).get("device")
    if was != device:
        raise UnifiedReadoutError(f"cache {out}: its shards were made with --device {was}, not --device {device}")


CACHE_ENCODE = "cache_encode.json"


def bind_cache_encode_rounds(out: Path, rounds: int, *, sample=None) -> None:
    """Bind the encoder and optional sampled shard layout before any worker writes."""
    marker = out / CACHE_ENCODE
    if not marker.exists() and _cache_has_output(out) and not marker.exists():
        if rounds != CACHE_DEFAULT_ENCODE_ROUNDS:
            raise UnifiedReadoutError(f"cache {out}: existing shards have the default encode batch size")
        if sample is not None:
            raise UnifiedReadoutError(f"cache {out}: existing shards have no sampled selection binding")
        for receipt in out.glob("DONE.*"):
            try:
                record = json.loads(receipt.read_text())
            except (OSError, ValueError):
                continue
            if isinstance(record, dict) and "sample" in record:
                raise UnifiedReadoutError(f"cache {out}: existing shards come from an unbound sampled cache")
    expected = {"rounds_per_batch": rounds}
    if sample is not None:
        expected["sample"] = sample
    record = _cache_marker(out, CACHE_ENCODE, expected)
    if record.get("rounds_per_batch") != rounds:
        raise UnifiedReadoutError(f"cache {out}: shards use --encode-rounds-per-batch "
                                  f"{record.get('rounds_per_batch')}, not {rounds}")
    if record.get("sample") != sample:
        raise UnifiedReadoutError(f"cache {out}: sampled selection or worker layout differs")


def sample_entries(entries, cap, seed):
    """Visit chunks in seeded random order, keep those that fit, and return them in input order."""
    if cap is None or sum(int(e["rows"]) for e in entries) <= cap:
        return entries
    keep, total = np.zeros(len(entries), bool), 0
    for i in np.random.default_rng([int(seed), 0x5A3C]).permutation(len(entries)):
        rows = int(entries[i]["rows"])
        if total + rows <= cap:
            keep[i], total = True, total + rows
    return [entry for entry, kept in zip(entries, keep) if kept]


def _cache_sample_binding(args, receipt, entries):
    manifests = [
        (path, us.sha256_file(Path(path) / "manifest.json"), us.sha256_file(Path(path) / "hist/manifest.json"))
        for path in args.data
    ]
    selected = hashlib.sha256()
    for entry in entries:
        selected.update(bytes.fromhex(entry["sha256"]))
        selected.update(bytes.fromhex(entry["hist_sha256"]))
    inputs = dict(manifests=manifests, selection_sha256=selected.hexdigest(), store_map=args.store_map,
                  calib_rows=args.calib_rows, exclude_seed_windows=args.exclude_seed_window,
                  corpus_weight=args.corpus_weight, checkpoint_sha256=us.sha256_file(args.ckpt))
    inputs_sha256 = hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()
    return dict(receipt=receipt, inputs_sha256=inputs_sha256, workers=args.workers,
                group_chunks=args.group_chunks, max_groups=args.max_groups)


def cache(args) -> int:
    """Write the polish cache of a checkpoint: ``OUT/calib-0000.npz`` (the trainer's calibration rows) and
    ``OUT/train-NNNN.npz`` (consecutive groups of ``--group-chunks`` train chunks; ``--worker I --workers N``
    takes every N-th group). Existing shards are reused when the cache producer's device, encode batch
    size, and optional sampled selection match this run."""
    import torch
    if args.encode_rounds_per_batch <= 0:
        raise UnifiedReadoutError("--encode-rounds-per-batch must be positive")
    cap = getattr(args, "sample_train_rows", None)
    if cap is not None and cap <= 0:
        raise UnifiedReadoutError("--sample-train-rows must be positive")

    def train_entries():
        return weight_entries(us.entries_for(args.data, "train", exclude_seed_windows=args.exclude_seed_window),
                              parse_corpus_weights(args.corpus_weight))

    receipt = binding = entries = None
    if cap is not None:
        available = train_entries()
        entries = sample_entries(available, cap, args.seed)
        if not entries:
            raise UnifiedReadoutError("--sample-train-rows fits no training chunks")
        receipt = dict(cap_rows=cap, seed=args.seed, chunks=len(entries),
                       rows=sum(int(e["rows"]) for e in entries), of_chunks=len(available),
                       of_rows=sum(int(e["rows"]) for e in available))
        binding = _cache_sample_binding(args, receipt, entries)
    torch.set_num_threads(args.threads)
    device = _device(args.device)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    bind_cache_device(out, args.device)
    bind_cache_encode_rounds(out, args.encode_rounds_per_batch, sample=binding)
    model, _ = load_checkpoint(args.ckpt)
    if device.type != "cpu":
        model.to(device)
    verified = bs._Verified()
    index = us.OutcomeIndex(us.parse_store_map(args.store_map))

    def write(name, part):
        tmp = out / (name + ".tmp.npz")
        np.savez(tmp, **cache_arrays(model, part, rounds_per_batch=args.encode_rounds_per_batch, device=device))
        os.replace(tmp, out / (name + ".npz"))
    if args.worker == 0 and not (out / "calib-0000.npz").exists():
        write("calib-0000", us.load_calib(args.data, verified, index, max_rows=args.calib_rows, seed=args.seed,
                                          exclude_seed_windows=args.exclude_seed_window))
    if entries is None:
        entries = train_entries()
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
    done = {"groups": len(groups), "chunks": len(entries)}
    if receipt is not None:
        done["sample"] = receipt
    if args.corpus_weight:
        done["corpus_weight"] = list(args.corpus_weight)
    (out / f"DONE.{args.worker}").write_text(json.dumps(done))
    return 0


def _polish_tensors(z, pick=None, device="cpu"):
    import torch
    row = z["leaf_row"] if pick is None else z["leaf_row"][pick]
    get = lambda k: z[k] if pick is None else z[k][pick]
    t = (torch.from_numpy(z["S"][row].astype(np.float32)), torch.from_numpy(z["c"][row].astype(np.float32)),
         torch.from_numpy(get("leaf_planes").astype(np.float32)), torch.from_numpy(get("leaf_scalars")),
         torch.from_numpy(get("leaf_target").astype(np.int64)), torch.from_numpy(get("leaf_reply").astype(np.float32)),
         torch.from_numpy(get("leaf_reply_hand")), torch.from_numpy(get("leaf_has_reply")))
    return t if torch.device(device).type == "cpu" else tuple(x.to(device) for x in t)


def polish_losses(readout, t):
    """Per-leaf outcome CE and reply CE (zero where there is no reply) of cached leaves."""
    import torch
    S, c, planes, scalars, target, reply, hand, has = t
    v, r = readout.body(S, c, planes, scalars)
    v_ce = torch.nn.functional.cross_entropy(v, target, reduction="none")
    rl = torch.log_softmax(r.masked_fill(~hand, -1e9), -1)
    r_ce = -((reply / reply.sum(-1, keepdim=True).clamp_min(1.0)) * rl).sum(-1) * has
    return v_ce, r_ce, scalars[:, 2] > 0, has


def polish_objective(v, r, has, reply_weight, leaf_w=None):
    """Mean outcome CE + reply_weight x reply CE per leaf with a reply; ``leaf_w`` (L, 2) weighs each
    leaf's two losses by its corpus (the counts stay unweighted)."""
    import torch
    if leaf_w is not None:
        lw = torch.from_numpy(np.asarray(leaf_w, np.float32))
        if v.device.type != "cpu":
            lw = lw.to(v.device)
        v, r = v * lw[:, 0], r * lw[:, 1]
    return v.mean() + reply_weight * r.sum() / has.float().sum().clamp_min(1.0)


def polish_eval(readout, z, batch: int = 16384, device="cpu") -> dict[str, float]:
    import torch
    sums = np.zeros(6)
    readout.eval()
    with torch.no_grad():
        for i in range(0, len(z["leaf_row"]), batch):
            v, r, end, has = polish_losses(readout, _polish_tensors(z, np.arange(i, min(i + batch, len(z["leaf_row"]))), device))
            sums += [float(v.sum()), len(v), float((v * end).sum()), float(end.sum()), float(r.sum()), float(has.sum())]
    readout.train()
    return {"leaf_value": sums[0] / max(sums[1], 1), "leaf_value_end": sums[2] / max(sums[3], 1), "reply": sums[4] / max(sums[5], 1)}


def polish(args) -> int:
    """Train the readout's per-leaf body on a cache (the trunk, the other heads and the per-decision
    projections stay the checkpoint's); ``OUT/best.pt`` is the checkpoint with the body of the pass that
    scored the lowest calibration trick-end NLL, or the input checkpoint when no pass beats it."""
    import torch
    torch.set_num_threads(args.threads)
    torch.manual_seed(args.seed)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    status = str(out / "status.log")
    device = _device(args.device, status)
    model, saved = load_checkpoint(args.ckpt)
    if device.type != "cpu":
        model.to(device)
    readout = model.readout
    body = [p for n, p in readout.named_parameters() if n.startswith(BODY_PREFIXES)]
    frozen = [n for n, p in readout.named_parameters() if not n.startswith(BODY_PREFIXES)]
    if sorted(frozen) != ["card_ln.bias", "card_ln.weight", "card_proj.bias", "card_proj.weight", "ctx.bias", "ctx.weight"]:
        raise UnifiedReadoutError(f"unexpected frozen readout parameters {frozen}")
    cache_dir = Path(args.cache)
    shards = sorted(cache_dir.glob("train-*.npz"))
    done = sorted(cache_dir.glob("DONE.*"))
    if not shards or not done:
        raise UnifiedReadoutError("the cache is incomplete")
    weighted = {"leaf_w" in np.load(f).files for f in shards}
    if len(weighted) != 1:
        raise UnifiedReadoutError("the cache mixes shards with and without corpus weights")
    weighted = weighted.pop()
    calib = dict(np.load(cache_dir / "calib-0000.npz"))
    readout.train()
    opt = torch.optim.AdamW(body, lr=args.lr, weight_decay=args.weight_decay)
    total = args.epochs * len(shards)
    init = polish_eval(readout, calib, device=device)
    best = {"score": init["leaf_value_end"], "epoch": 0, "calib": init}
    _status(status, f"POLISH START shards={len(shards)} epochs={args.epochs} body_params={sum(p.numel() for p in body)} "
                    f"ckpt={us.sha256_file(args.ckpt)} corpus_weighted={weighted} init calib {json.dumps(init)}"
                    + ("" if device.type == "cpu" else f" device={args.device}"))
    rng = np.random.default_rng(args.seed)
    step_i, t0 = 0, time.time()
    state = None
    for epoch in range(args.epochs):
        sums = np.zeros(6)
        for si in rng.permutation(len(shards)):
            for g in opt.param_groups:
                g["lr"] = args.lr * 0.5 * (1 + math.cos(math.pi * step_i / total))
            step_i += 1
            z = np.load(shards[si])
            z = {k: z[k] for k in z.files}
            order = rng.permutation(len(z["leaf_row"]))
            for i in range(0, len(order), args.batch):
                pick = np.sort(order[i:i + args.batch])
                v, r, end, has = polish_losses(readout, _polish_tensors(z, pick, device))
                loss = polish_objective(v, r, has, args.reply_weight, z["leaf_w"][pick] if weighted else None)
                opt.zero_grad()
                loss.backward()
                torch.nn.utils.clip_grad_norm_(body, 1.0)
                opt.step()
                sums += [float(v.sum().detach()), len(v), float((v * end).sum().detach()), float(end.sum()),
                         float(r.sum().detach()), float(has.sum())]
            if (out / "STOP").exists():
                _status(status, "STOPPED (STOP file)")
                return 3
        cm = polish_eval(readout, calib, device=device)
        train = {"leaf_value": sums[0] / max(sums[1], 1), "leaf_value_end": sums[2] / max(sums[3], 1), "reply": sums[4] / max(sums[5], 1)}
        _status(status, f"POLISH EPOCH {epoch + 1} train {json.dumps({k: round(v, 5) for k, v in train.items()})} "
                        f"calib {json.dumps({k: round(v, 5) for k, v in cm.items()})} ({time.time() - t0:.0f}s)")
        if cm["leaf_value_end"] < best["score"]:
            best = {"score": cm["leaf_value_end"], "epoch": epoch + 1, "calib": cm}
            state = {k: v.detach().clone() for k, v in model.state_dict().items()}
    if state is not None:
        model.load_state_dict(state)
    polish_args = {k: v for k, v in vars(args).items() if not (k == "device" and v == "cpu")}
    torch.save({"schema": CKPT_SCHEMA, "model": model.state_dict() if device.type == "cpu" else _on_cpu(model.state_dict()),
                "config": model.config, "epoch": saved.get("epoch"),
                "calib": dict(saved.get("calib") or {}, polish=best["calib"], polish_epoch=best["epoch"]),
                "init_calib": saved.get("init_calib"), "run": dict(saved.get("run") or {}, polish=polish_args)}, out / "best.pt")
    _status(status, f"POLISH DONE best_epoch={best['epoch']} calib {json.dumps(best['calib'])} sha256={us.sha256_file(out / 'best.pt')}")
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
    t.add_argument("--microbatch-rounds", type=int, help="maximum rounds per backward pass within a logical batch")
    t.add_argument("--rounds-per-batch", type=int, default=16)
    t.add_argument("--max-train-rows", type=int, default=None)
    t.add_argument("--capacity-stats", action="store_true",
                   help="report throughput and post-step MPS allocations for each completed training leg")
    t.add_argument("--max-steps", type=int, default=None)
    t.add_argument("--calib-rows", type=int, default=180000)
    t.add_argument("--report-buffer", type=int, help="write cumulative epoch losses at this interior buffer boundary")
    t.add_argument("--pause-at-report", action="store_true",
                   help="checkpoint and exit 7 at the first epoch's report boundary; omit to continue")
    t.add_argument("--expect-resume-buffer", type=int,
                   help="require a matching first-epoch checkpoint at this buffer before training")
    t.add_argument("--recover-checkpoint-sha256", help="require these exact checkpoint bytes at an interior first-epoch buffer")
    t.add_argument("--save-every", type=float, default=600.0)
    t.add_argument("--exclude-seed-window", type=bs.seed_window, action="append", default=[])
    t.add_argument("--corpus-weight", action="append", default=[],
                   help="PREFIX=head:w[,head:w...]: loss weights of the rows of data dirs under PREFIX "
                        f"(heads {','.join(CORPUS_HEADS)}; default 1)")
    t.add_argument("--device", choices=("cpu", "mps"), default="cpu", help="where the model runs; batches are built on the CPU")
    c = sub.add_parser("cache")
    c.add_argument("--ckpt", required=True)
    c.add_argument("--data", nargs="+", required=True)
    c.add_argument("--out", required=True)
    c.add_argument("--store-map", action="append", default=[])
    c.add_argument("--exclude-seed-window", type=bs.seed_window, action="append", default=[])
    c.add_argument("--calib-rows", type=int, default=180000)
    c.add_argument("--seed", type=int, default=1)
    c.add_argument("--group-chunks", type=int, default=24)
    c.add_argument("--encode-rounds-per-batch", type=int, default=CACHE_DEFAULT_ENCODE_ROUNDS,
                   help="maximum rounds per trunk forward for cache training and calibration shards")
    c.add_argument("--max-groups", type=int, default=None, help="only the first groups (smoke)")
    c.add_argument("--sample-train-rows", type=int,
                   help="cache a seeded sample of whole train chunks within this manifest row cap")
    c.add_argument("--worker", type=int, default=0)
    c.add_argument("--workers", type=int, default=1)
    c.add_argument("--threads", type=int, default=8)
    c.add_argument("--corpus-weight", action="append", default=[],
                   help="as train's: stores each leaf's value and reply weights in the cache (the polish uses them)")
    c.add_argument("--device", choices=("cpu", "mps"), default="cpu")
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
    p.add_argument("--device", choices=("cpu", "mps"), default="cpu")
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
    return {"train": train, "export": export, "cache": cache, "polish": polish, "mixpolish": mixpolish}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
