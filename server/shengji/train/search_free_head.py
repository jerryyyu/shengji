"""Fit a search-free candidate head on a fixed unified trunk and export it for play."""
from __future__ import annotations

import hashlib
import io
from pathlib import Path

import numpy as np

from . import belief_seq as bs
from . import search_free_play as sf
from . import unified_seq as us
from .search_free_candidates import load_public_candidates


def build_head(trunk_config):
    import torch
    from torch import nn

    d, xh = trunk_config["d"], trunk_config["x_hidden"]

    class Head(nn.Module):
        def __init__(self):
            super().__init__()
            self.tok = nn.Sequential(nn.Linear(d + 14, d), nn.GELU(), nn.Linear(d, d))
            self.prev = nn.Linear(d, d)
            self.ctx = nn.Linear(xh, d)
            self.ln = nn.LayerNorm(d)
            self.typ = nn.Parameter(torch.empty(4, d))
            self.hand = nn.Parameter(torch.empty(d))
            self.incand = nn.Parameter(torch.empty(d))
            for weight in (self.typ, self.hand, self.incand):
                nn.init.normal_(weight, std=0.02)
            self.layers = nn.ModuleList(nn.TransformerEncoderLayer(
                d, sf.CAND_HEADS, 2 * d, dropout=0, activation="gelu", batch_first=True,
                norm_first=True) for _ in range(sf.CAND_LAYERS))
            self.out = nn.Sequential(nn.LayerNorm(d), nn.Linear(d, 256), nn.GELU(), nn.Linear(256, 2))

        def forward(self, emb, raw, cards, prev, g, q, hand):
            t = self.tok(torch.cat([emb, raw], -1)) + self.typ[0]
            cs = self.ln(q) + self.typ[3] + hand[..., None] * self.hand + (cards > 0)[..., None] * self.incand
            x = torch.cat([t[:, None], (self.prev(prev) + self.typ[1])[:, None],
                           (self.ctx(g) + self.typ[2])[:, None], cs], 1)
            for layer in self.layers:
                x = layer(x)
            return self.out(x[:, 0]).unbind(-1)

    return Head()


def candidate_name(entry):
    key = hashlib.sha256((str(entry["dir"]) + "|" + entry["sha256"]).encode()).hexdigest()[:20]
    return key + ".npz"


def candidate_batches(entry, directory, verified, *, rounds_per_batch=1):
    """Join whole ballots to pre-play decision rows using the extractor's chunk key."""
    path = Path(directory) / candidate_name(entry)
    source = io.BytesIO(verified.read(str(path), entry["candidate_sha256"])) if "candidate_sha256" in entry else path
    cand, _ = load_public_candidates(source)
    part = bs.load_part(entry, bs.ROW_KEYS, verified, include_source_rows=True)
    row = cand["row"]
    if (row.dtype.kind not in "iu" or int(cand["n_rows"]) != entry["rows"]
            or np.any(row < 0) or np.any(row >= entry["rows"])):
        raise ValueError("candidate shard does not match the extract rows")
    for rounds, rows in bs.round_batches(part, rounds_per_batch, None):
        keep = np.isin(row, part["source_row"][rows])
        if not np.any(keep):
            continue
        decisions, local = np.unique(row[keep], return_inverse=True)
        b = bs.make_batch(part, rounds, np.searchsorted(part["source_row"], decisions))
        c = {k: cand[k][keep] for k in ("tok_int", "tok_f", "tok_cards", "tok_att", "mean", "played", "slot")}
        c["row"] = local
        recorded = b["tok_int"][b["rr"], b["ply"]]
        if (not np.array_equal(c["tok_int"][:, :3], recorded[local, :3])
                or np.any(c["tok_cards"] > (2 * b["X"][local, :54] + 0.01))
                or not np.isfinite(c["mean"]).all()):
            raise ValueError("candidate does not match its decision")
        sizes = np.bincount(local)
        if (np.any(sizes < 2) or c["played"].dtype.kind != "b"
                or not np.all(np.bincount(local, weights=c["played"]) == 1)):
            raise ValueError("expected complete ballots with one selected action")
        groups = np.lexsort((c["slot"], local))
        starts = np.repeat(np.cumsum(sizes) - sizes, sizes)
        if not np.array_equal(c["slot"][groups], np.arange(len(local)) - starts):
            raise ValueError("candidate slots are incomplete")
        selected = c["played"]
        targets = us.policy_target(b)
        if not np.array_equal(c["tok_cards"][selected], targets[local[selected]]):
            raise ValueError("selected candidate differs from the recorded attempt")
        yield b, c


def _frozen_states(model, batch):
    import torch

    m = model.trunk
    if m.training:
        raise ValueError("fixed trunk must be in evaluation mode")
    b = us.to_device(batch, next(m.parameters()).device)
    with torch.no_grad():
        _, enc, q, g = us.trunk_forward(m, b)
        table = m.card_id[None] + m.card_feat(b["card_feat"])
    return b, enc, q, g, table


def _score_candidates(m, head, states, candidates):
    import torch
    from torch.nn.functional import one_hot

    b, enc, q, g, card_table = states
    c = us.to_device(candidates, enc.device)
    with torch.no_grad():
        row = c["row"].long()
        rr, ply = b["rr"][row], b["ply"][row]
        seat, pos, trick, lead = c["tok_int"].long().unbind(-1)
        tf, cards = c["tok_f"].float(), c["tok_cards"].float()
        role = (seat - b["banker"][rr]) % 4
        raw = torch.cat((tf, one_hot(pos, 4)), -1)
        meta = torch.cat((one_hot(pos, 4), one_hot(lead, 5), tf, one_hot(role, 4)), -1)
        table = card_table[rr]
        emb = (m.tok_meta(meta) + m.trick_emb(trick) + torch.bmm(cards[:, None], table)[:, 0]
               + m.pos_emb.weight[ply] + m.rel_emb.weight[0])
        prev = enc[rr * 4 + seat, (ply - 1).clamp_min(0)] * (ply > 0)[:, None]
    return head(emb, raw, cards, prev, g[row], q[row], b["X"][row, :54] > 0)


def score_batch(model, head, batch, candidates):
    """Score corrected tokens in caller order from the fixed trunk's pre-play states."""
    return _score_candidates(model.trunk, head, _frozen_states(model, batch), candidates)


def candidate_loss(values, logits, candidates, *, decision_count=None, candidate_count=None):
    """Decision-balanced soft search and chosen-action losses plus candidate value regression."""
    import torch
    from torch.nn import functional as F

    row = torch.as_tensor(candidates["row"], device=logits.device).long()
    mean = torch.as_tensor(candidates["mean"], device=logits.device, dtype=logits.dtype)
    played = torch.as_tensor(candidates["played"], device=logits.device)
    groups, row = torch.unique(row, return_inverse=True)
    n = groups.numel()
    decisions = n if decision_count is None else decision_count
    count = len(mean) if candidate_count is None else candidate_count

    def log_probs(x):
        mx = x.new_full((n,), -torch.inf).scatter_reduce_(0, row, x.detach(), "amax")
        centered = x - mx[row]
        total = x.new_zeros(n).scatter_add_(0, row, centered.exp())
        return centered - total.log()[row]

    logp = log_probs(logits)
    soft_ce = -(log_probs(mean / 0.05).exp() * logp).sum() / decisions
    chosen_ce = -logp[played].sum() / decisions
    return soft_ce + 0.5 * chosen_ce + F.smooth_l1_loss(values, mean, reduction="sum") / count


def _whole_ballots(candidates, target):
    """Pack complete decisions; an individual ballot above the target runs by itself."""
    rows = candidates["row"]
    if len(rows) <= target:
        yield candidates
        return
    order = np.argsort(rows, kind="stable")
    start = stop = 0
    for size in np.bincount(rows):
        if stop > start and stop + size - start > target:
            yield {k: v[order[start:stop]] for k, v in candidates.items()}
            start = stop
        stop += size
    yield {k: v[order[start:stop]] for k, v in candidates.items()}


def fit_shard(model, head, optimizer, entry, directory, verified, *, rounds_per_batch=1, candidate_target=128):
    """Update the candidate head on whole ballots from one prepared training chunk."""
    if candidate_target < 1:
        raise ValueError("candidate_target must be positive")
    decisions = 0
    for batch, candidates in candidate_batches(entry, directory, verified, rounds_per_batch=rounds_per_batch):
        optimizer.zero_grad(set_to_none=True)
        states = _frozen_states(model, batch)
        for group in _whole_ballots(candidates, candidate_target):
            values, logits = _score_candidates(model.trunk, head, states, group)
            loss = candidate_loss(values, logits, group, decision_count=len(batch["X"]),
                                  candidate_count=len(candidates["row"]))
            if not loss.isfinite().item():
                raise ValueError("non-finite candidate loss")
            loss.backward()
        optimizer.step()
        decisions += len(batch["X"])
    return decisions


def export(path, model, head, metadata, *, shared_unified=None):
    """Export a standalone scorer or a head bound to the matching loaded serving package."""
    def arrays(module):
        return {k: v.detach().cpu().float().numpy() for k, v in module.state_dict().items()}

    weights = {f"{name}.{k}": v for name in ("q_head", "p_head")
               for k, v in arrays(getattr(model, name)).items()}
    trunk = arrays(model.trunk)
    cand = arrays(head)
    if shared_unified is None:
        return sf.save_package(path, model.config, trunk, weights, cand, metadata)

    digest = shared_unified.package_sha256
    if (not digest or len(digest) != 64 or shared_unified.dtype != np.float32
            or any(shared_unified.config[k] != model.config[k] for k in ("trunk", "heads"))):
        raise ValueError("expected a matching, hashed float32 unified serving package")
    for fitted, served in ((trunk, shared_unified.trunk.w), (weights, shared_unified.h)):
        if fitted.keys() != served.keys() or any(not np.array_equal(v, served[k]) for k, v in fitted.items()):
            raise ValueError("candidate training and serving weights differ")
    return sf.save_shared_head(path, shared_unified, cand, metadata)
