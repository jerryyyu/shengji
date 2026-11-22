"""Explicit, package-bound whole-action reply ranking for unified search."""
from __future__ import annotations

import hashlib
import io
import re
from pathlib import Path

import numpy as np

from ..engine import combos
from ..engine.legal import beats, uniform_suit
from ..engine.cards import points as card_pts, TRUMP
from ..rl.encode import CARD_INDEX

SCHEMA = "unified-reply-action-v1"
N_AF = 12
PTS = np.zeros(54, np.float32)
for _card, _index in CARD_INDEX.items():
    PTS[_index] = card_pts(_card)


def _trick_context(root, seat):
    o = root.ordering
    plays = root.trick.plays
    lead = list(plays[0].cards)
    lead_suit = uniform_suit(lead, o)
    inc_suit, inc_top = lead_suit, combos.decompose(lead, o).top_level()
    winner = plays[0].seat
    for tp in plays[1:]:
        won, top = beats(list(tp.cards), lead, inc_suit, inc_top, o)
        if won:
            winner, inc_top, inc_suit = tp.seat, top, o.eff_suit(tp.cards[0])
    partner_winning = float((winner - seat) % 4 == 2)
    return lead, lead_suit, inc_suit, inc_top, partner_winning


def action_feats(legal, root, seat):
    """(n_legal, N_AF) engine features of each legal follow."""
    lead, lead_suit, inc_suit, inc_top, partner_winning = _trick_context(root, seat)
    o = root.ordering
    F = np.zeros((len(legal), N_AF), np.float32)
    for i, a in enumerate(legal):
        n = len(a)
        effs = [o.eff_suit(c) for c in a]
        n_lead = sum(e == lead_suit for e in effs)
        n_trump = sum(e == TRUMP for e in effs)
        cnt = {}
        for c in a:
            cnt[c] = cnt.get(c, 0) + 1
        n_pairs = sum(v // 2 for v in cnt.values())
        one_suit = len(set(effs)) == 1
        mpr = combos.decompose(list(a), o).max_pair_run() if one_suit else 0
        won, _ = beats(list(a), lead, inc_suit, inc_top, o)
        pts = float(sum(PTS[CARD_INDEX[c]] for c in a))
        F[i] = (n, n_lead / n, n_trump / n, (n - n_lead - (n_trump if lead_suit != TRUMP else 0)) / n, n_pairs / max(n // 2, 1),
                mpr / max(n // 2, 1), float(one_suit), float(won), pts / 10.0, partner_winning, float(won) * pts / 10.0,
                np.log(len(legal)))
    return F


def _compact_feats(legal, root, counts, n):
    """Compute listing-wide features together; only single-suit actions can win."""
    lead, lead_suit, inc_suit, inc_top, partner = _trick_context(root, root.turn)
    suits = np.empty(54, dtype="U1")
    for card, index in CARD_INDEX.items():
        suits[index] = root.ordering.eff_suit(card)
    suit_counts = np.column_stack([counts[:, suits == suit].sum(1) for suit in ("S", "H", "D", "C", TRUMP)])
    lead_count = counts[:, suits == lead_suit].sum(1)
    trump_count = suit_counts[:, -1]
    one_suit = suit_counts.max(1) == n
    pairs = (counts // 2).sum(1)
    denom = np.maximum(n // 2, 1)
    points = counts @ PTS
    feats = np.zeros((len(legal), N_AF), np.float32)
    feats[:, 0] = n
    feats[:, 1] = lead_count / n
    feats[:, 2] = trump_count / n
    feats[:, 3] = (n - lead_count - (trump_count if lead_suit != TRUMP else 0)) / n
    feats[:, 4] = pairs / denom
    feats[:, 6] = one_suit
    for i in np.flatnonzero(one_suit):
        cards = legal[i]
        feats[i, 5] = combos.decompose(cards, root.ordering).max_pair_run() / denom[i]
        feats[i, 7] = beats(cards, lead, inc_suit, inc_top, root.ordering)[0]
    feats[:, 8] = points / 10
    feats[:, 9] = partner
    feats[:, 10] = feats[:, 7] * feats[:, 8]
    feats[:, 11] = np.log(len(legal))
    return feats


def _stored_precision(a):
    """The residual head consumes float16-rounded features as float32."""
    return np.asarray(a, np.float16).astype(np.float32)


class ReplyActionScorer:
    def __init__(self, weights, base_model_sha, package_sha):
        for sha in (base_model_sha, package_sha):
            if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sha):
                raise ValueError("reply action scorer requires full package hashes")
        dh = np.shape(weights["ln.weight"])[0]
        de = np.shape(weights["e_mu"])[0]
        k = np.shape(weights["A.bias"])[0]
        shapes = {"ln.weight": (dh,), "ln.bias": (dh,), "e_mu": (de,), "e_sd": (de,),
                  "A.weight": (k, dh), "A.bias": (k,), "B.weight": (k, de), "B.bias": (k,),
                  "W1.weight": (k, 3*k), "W1.bias": (k,), "W2.weight": (64, k),
                  "W2.bias": (64,), "w.weight": (1, 64), "w.bias": (1,)}
        if set(weights) != set(shapes) or dh < 1 or de <= 24 or k < 1:
            raise ValueError("invalid reply action weight keys or dimensions")
        self.weights = {}
        for key, shape in shapes.items():
            value = np.array(weights[key], dtype=np.float32, copy=True)
            if value.shape != shape or not np.isfinite(value).all():
                raise ValueError(f"invalid reply action weight: {key}")
            value.setflags(write=False)
            self.weights[key] = value
        if np.any(self.weights["e_sd"] <= 0):
            raise ValueError("reply action scales must be positive")
        self.base_model_sha, self.package_sha256 = base_model_sha, package_sha
        self.hidden_width, self.card_width = dh, de - 24

    def residual(self, h, e):
        w = self.weights
        h, e = np.asarray(h, np.float32), np.asarray(e, np.float32)
        if h.shape != (self.hidden_width,) or e.ndim != 2 or e.shape[1] != len(w["e_mu"]):
            raise ValueError("reply action feature dimensions disagree with package")
        if not np.isfinite(h).all() or not np.isfinite(e).all():
            raise ValueError("reply action features must be finite")
        h = (h - h.mean()) / np.sqrt(h.var() + np.float32(1e-5))
        h = h * w["ln.weight"] + w["ln.bias"]
        u = np.maximum(h @ w["A.weight"].T + w["A.bias"], 0)
        v = np.maximum(((e - w["e_mu"]) / w["e_sd"]) @ w["B.weight"].T + w["B.bias"], 0)
        x = np.concatenate([np.broadcast_to(u, v.shape), v, u * v], axis=1)
        x = np.maximum(x @ w["W1.weight"].T + w["W1.bias"], 0)
        x = np.maximum(x @ w["W2.weight"].T + w["W2.bias"], 0)
        return (x @ w["w.weight"].T + w["w.bias"]).reshape(-1)

    def scores(self, root, legal, row, hidden, card_states, planes):
        from .pv_tree_search import CompactReplies

        # Small listings cost less to walk than to set up suit masks and reductions.
        compact = type(legal) is CompactReplies and not legal.leads and len(legal) >= 16
        if compact:
            counts = legal.multiplicity().astype(np.float32)
        else:
            counts = np.zeros((len(legal), 54), np.float32)
            for i, action in enumerate(legal):
                for card in action:
                    counts[i, CARD_INDEX[card]] += 1
        n = counts.sum(1)
        if not len(legal) or np.any(n == 0):
            raise ValueError("reply action ranking requires nonempty actions")
        row = np.asarray(row, np.float32)
        cardf = np.concatenate([card_states, np.asarray(planes, np.float32).reshape(9, 54).T,
                                row[:, None]], axis=1)
        pool = _stored_precision(counts @ cardf)
        base = (counts.astype(np.float64) * row.astype(np.float64)).sum(1)
        feats = _compact_feats(legal, root, counts, n) if compact else action_feats(legal, root, root.turn)
        e = np.concatenate([pool / n[:, None], _stored_precision(feats),
                            (base / n)[:, None].astype(np.float32),
                            (base - base.max())[:, None].astype(np.float32)], axis=1)
        return base + self.residual(_stored_precision(hidden), e).astype(np.float64)


def save_reply_action(path, weights, *, base_model_sha256):
    """Export a fitted state dict of NumPy arrays, binding its feature producer."""
    scorer = ReplyActionScorer(weights, base_model_sha256, "0" * 64)
    buffer = io.BytesIO()
    np.savez(buffer, schema=SCHEMA, base_model_sha256=base_model_sha256, **scorer.weights)
    data = buffer.getvalue()
    Path(path).write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def load_reply_action(path, *, sha256):
    """Authenticate the exact bytes before loading non-pickled arrays."""
    if not isinstance(sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", sha256):
        raise ValueError("reply action load requires a full sha256")
    data = Path(path).read_bytes()
    if hashlib.sha256(data).hexdigest() != sha256:
        raise ValueError("reply action package hash mismatch")
    with np.load(io.BytesIO(data), allow_pickle=False) as z:
        if str(z["schema"].item()) != SCHEMA:
            raise ValueError("unsupported reply action schema")
        base = str(z["base_model_sha256"].item())
        weights = {key: z[key] for key in z.files if key not in ("schema", "base_model_sha256")}
    return ReplyActionScorer(weights, base, sha256)


def install_reply_action(bot, scorer):
    """Attach only to the unified reply model whose states trained this head."""
    model = getattr(bot, "unified_reply_model", None)
    if model is None or scorer.base_model_sha != model.package_sha256:
        raise ValueError("reply action scorer and unified reply model disagree")
    if getattr(bot, "unified_reply_action", None) is not None:
        raise ValueError("reply action scorer is already installed")
    if model.r["reply.weight"].shape[1] != scorer.hidden_width or \
            model.r["card_proj.weight"].shape[0] != scorer.card_width:
        raise ValueError("reply action scorer dimensions disagree with unified model")
    bot.unified_reply_action = scorer
    bot.policy_name = f"{bot.policy_name}-uaction{scorer.package_sha256[:8]}"
    return bot
