"""PL1: the likelihood of every observed opponent play under the S136 model, per candidate world.

Runs in the PL1 worktree (origin/main + the S136 duel branch's search_free_play.py). The S136 package's
trunk + policy head (``UnifiedNumpy.policy_logits``) gives 54 card log-odds for the actor's information
set; the action's logit is the sum of its cards' log-odds and the normaliser is every legal play of the
actor under the hypothesized hand, exactly S113's likelihood form (closed-form leads, full follow listing,
played action forced in, -inf when the played action is illegal under the hypothesized hand). Only the
model that produces the card log-odds changes: S136 instead of the R51 prior FT1.

Inputs for a hypothesized hand are the real ``decision_inputs`` of the true state with the hand-dependent
columns recomputed (``fast_inputs``); ``slow_inputs`` (a root clone through ``decision_inputs``) is the
reference and the tests require exact equality on every pilot state.
"""
from __future__ import annotations

import copy
import math
import os
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

WT = Path("/Users/jerryyu/Projects/shengji-wt/claude-pl1")
PKG = Path("/Users/jerryyu/.claude/jobs/d0498cda/tmp/pl1/models/sf-s136-516617b8.npz")
PKG_SHA = "516617b893689a931977068a1a536735afdb1edff0979f6f2360588291a8d184"
if str(WT / "server") not in sys.path:
    sys.path.insert(0, str(WT / "server"))

from shengji.rl.encode import CARD_INDEX, N_CARDS  # noqa: E402

CODES = [None] * N_CARDS
for _c, _i in CARD_INDEX.items():
    CODES[_i] = _c
OWN = slice(0, 54)
UNSEEN = slice(432, 486)
V2 = slice(531, 560)
V4 = slice(560, 635)
KITTY = slice(635, 689)
KITTY_KNOWN = 689


def counts(cards):
    out = np.zeros(N_CARDS, np.float32)
    for c in cards:
        out[CARD_INDEX[c]] += 1
    return out


def point_states(rec, attempts=None):
    """[(t, seat_t, chosen_t, rnd_t, refusals_t)] for every past play; chosen = the submitted action
    (the attempt for a failed throw); refusals_t = the public refusal ledger before play t."""
    from shengji.ai.refusal import RefusalLedger
    from shengji.harvest.rebuild import round_from_setup
    attempts = attempts or {}
    rnd = round_from_setup(rec["deck"], rec["setup"])
    led = RefusalLedger()
    led.observe(rnd)
    out = []
    for t, play in enumerate(rec["plays_prefix"]):
        seat = int(play["seat"])
        chosen = list(attempts.get(str(t), play["cards"]))
        out.append((t, seat, chosen, copy.deepcopy(rnd), list(led.refusals)))
        before = len(rnd.history)
        rnd.play(seat, chosen)
        got = (rnd.history[before].plays if len(rnd.history) > before else rnd.trick.plays)[-1]
        if got.seat != seat or sorted(got.cards) != sorted(play["cards"]):
            raise ValueError(f"replay drift at play {t}")
        led.observe(rnd)
    if rnd.turn != rec["seat"]:
        raise ValueError("turn mismatch")
    return out, rnd


def slow_inputs(rnd_t, s, refusals, hands, buried):
    from shengji.ai.belief_numpy import decision_inputs
    from shengji.train.cwv_prior_admission import root_clone
    return decision_inputs(root_clone(rnd_t, hands, buried), s, refusals)


class SeatState:
    """The true state of seat ``s`` before play t, and what a hypothesized hand changes."""

    def __init__(self, rnd_t, s, refusals):
        from shengji.ai.belief_numpy import decision_inputs
        from shengji.engine.cards import SUITS, TRUMP
        self.rnd, self.s, self.refusals = rnd_t, s, refusals
        self.inp = decision_inputs(rnd_t, s, refusals)
        self.X = np.asarray(self.inp["X"], np.float32)
        self.own_true = counts(rnd_t.hands[s])
        self.kitty_known = bool(self.X[KITTY_KNOWN] > 0.5)
        self.bur_true = counts(rnd_t.buried)
        o = rnd_t.ordering
        effs = list(SUITS) + [TRUMP]
        self.eff = np.zeros((N_CARDS, 5), np.float32)
        for i, c in enumerate(CODES):
            self.eff[i, effs.index(o.eff_suit(c))] = 1
        # the mask's public part: feasible_mask before its hidden-count factor, and sizes > 0
        from shengji.train.belief_labels import KITTY as KIT, actor_memory
        mem = actor_memory(rnd_t, s, refusals)
        base = np.zeros((N_CARDS, 4), bool)
        for rel in (1, 2, 3):
            q = (s + rel) % 4
            if rnd_t.hands[q]:
                base[:, rel - 1] = [CODES[i] and o.eff_suit(CODES[i]) not in mem.voids[q] for i in range(N_CARDS)]
        base[:, KIT] = not mem.own_kitty_known
        self.mask_base = base & (np.asarray(self.inp["sizes"]) > 0)[None, :]
        self.n_c_true = np.asarray(self.inp["n_c"], np.int64)

    def batch(self, own, bur):
        """``own`` (W, 54) hand counts, ``bur`` (W, 54) kitty counts -> X (W, F), M (W, 54, 4), ok (W,)."""
        from shengji.train.belief_seq import row_card_planes
        W = len(own)
        X = np.repeat(self.X[None], W, 0)
        d_own = self.own_true[None] - own
        # the obs planes count half a copy (encode._counts); the kitty block counts whole copies
        X[:, OWN] = 0.5 * own
        unseen = 2.0 * self.X[UNSEEN][None] + d_own
        X[:, UNSEEN] = 0.5 * unseen
        # v2 "what the hand is made of": 5 eff-suit counts, unseen trumps, pairs held, hand size
        X[:, 531 + 21:531 + 26] = (own @ self.eff) / 27.0
        X[:, 531 + 26] = (unseen @ self.eff[:, 4]) / 27.0
        X[:, 531 + 27] = (own >= 2).sum(1) / 13.0
        # v4: unseen per eff suit, pairs possible per eff suit
        X[:, 560:565] = (unseen @ self.eff) / 27.0
        X[:, 570:575] = ((unseen >= 2).astype(np.float32) @ self.eff) / 13.0
        n_c = self.n_c_true[None] + d_own.astype(np.int64)
        if self.kitty_known:
            X[:, KITTY] = bur
            n_c = n_c + (self.bur_true[None] - bur).astype(np.int64)
        F = len(self.X) - 4
        X[:, :F] = X[:, :F].astype(np.float16).astype(np.float32)
        ok = (n_c >= 0).all(1)
        M = self.mask_base[None] & (n_c > 0)[:, :, None]
        rc = row_card_planes(X[:, :F])
        return X, M, rc, ok


def fast_inputs_check(st, own, bur, hands_list, bur_list):
    """max |X diff|, M equality, row_card equality against slow_inputs on each world."""
    X, M, rc, ok = st.batch(own, bur)
    worst = 0.0
    eqM = True
    for k, (h, b) in enumerate(zip(hands_list, bur_list)):
        ref = slow_inputs(st.rnd, st.s, st.refusals, h, b)
        xr = np.asarray(ref["X"], np.float32)
        worst = max(worst, float(np.abs(xr - X[k]).max()))
        eqM &= bool(np.array_equal(np.asarray(ref["M"], bool), M[k]))
        eqM &= bool(np.array_equal(np.asarray(ref["row_card"], np.float32), rc[k]))
    return worst, eqM


# ------------------------------------------------------------------ batched model

class TorchPolicy:
    """S136 trunk card states + policy head, batched over worlds that share one history (torch, CPU)."""

    def __init__(self, threads=1):
        import hashlib
        import torch
        torch.set_num_threads(threads)
        from shengji.train.search_free_play import load_package
        if hashlib.sha256(PKG.read_bytes()).hexdigest() != PKG_SHA:
            raise SystemExit("S136 package sha mismatch")
        self.np_model = load_package(PKG, PKG_SHA)
        self.u = self.np_model.unified
        self.torch = torch
        self.w = {k: torch.from_numpy(np.array(v)) for k, v in self.u.trunk.w.items()}
        self.h = {k: torch.from_numpy(np.array(v)) for k, v in self.u.h.items()}
        self.cfg = self.u.trunk.config
        self.d, self.heads = self.u.trunk.d, self.u.trunk.heads

    def enc(self, inp):
        return self.u.trunk.encode_history(inp)

    def card_logits(self, inp, enc, X, M, rc):
        torch = self.torch
        F = torch.nn.functional
        w, h, d, H = self.w, self.h, self.d, self.heads
        dh = d // H
        W = len(X)
        with torch.no_grad():
            ce = torch.from_numpy(np.asarray(self.u.trunk._card_table(inp), np.float32))
            Xt = torch.from_numpy(X)
            g = F.relu(Xt @ w["x_mlp.0.weight"].T + w["x_mlp.0.bias"])
            g = F.relu(g @ w["x_mlp.2.weight"].T + w["x_mlp.2.bias"])
            rcm = torch.cat([torch.from_numpy(rc), torch.from_numpy(M.astype(np.float32))], -1)
            q = ce[None] + rcm @ w["row_card.weight"].T + w["row_card.bias"] + (g @ w["x_to_q.weight"].T + w["x_to_q.bias"])[:, None]
            mem = torch.cat([w["null_kv"][0], torch.from_numpy(np.asarray(enc, np.float32))], 0)
            S = len(mem)

            def ln(x, a, b):
                return F.layer_norm(x, (x.shape[-1],), w[a] if a in w else h[a], w[b] if b in w else h[b], eps=1e-5)
            for i in range(int(self.cfg["xattn_layers"])):
                kv = mem @ w[f"kv.{i}.weight"].T + w[f"kv.{i}.bias"]
                k = kv[:, :d].reshape(S, H, dh).permute(1, 2, 0)
                v = kv[:, d:].reshape(S, H, dh).transpose(0, 1)
                qi = ln(q, f"ln_q.{i}.weight", f"ln_q.{i}.bias")
                qi = qi @ w[f"xattn.{i}.q.weight"].T + w[f"xattn.{i}.q.bias"]
                qh = qi.reshape(W, N_CARDS, H, dh).transpose(1, 2)
                a = torch.softmax(qh @ k / math.sqrt(dh), -1) @ v
                q = q + a.transpose(1, 2).reshape(W, N_CARDS, d) @ w[f"xattn.{i}.o.weight"].T + w[f"xattn.{i}.o.bias"]
                f = ln(q, f"ff.{i}.0.weight", f"ff.{i}.0.bias")
                f = gelu(f @ w[f"ff.{i}.1.weight"].T + w[f"ff.{i}.1.bias"])
                q = q + f @ w[f"ff.{i}.3.weight"].T + w[f"ff.{i}.3.bias"]
            if self.cfg["card_self_attn"]:
                x = ln(q, "self_ln.weight", "self_ln.bias")
                qkv = x @ w["self_attn.in_proj_weight"].T + w["self_attn.in_proj_bias"]
                sp = lambda t: t.reshape(W, N_CARDS, H, dh).transpose(1, 2)
                a = torch.softmax(sp(qkv[..., :d]) @ sp(qkv[..., d:2 * d]).transpose(-1, -2) / math.sqrt(dh), -1) @ sp(qkv[..., 2 * d:])
                q = q + a.transpose(1, 2).reshape(W, N_CARDS, d) @ w["self_attn.out_proj.weight"].T + w["self_attn.out_proj.bias"]
                f = ln(q, "self_ff.0.weight", "self_ff.0.bias")
                f = gelu(f @ w["self_ff.1.weight"].T + w["self_ff.1.bias"])
                q = q + f @ w["self_ff.3.weight"].T + w["self_ff.3.bias"]
            x = ln(q, "p_head.0.weight", "p_head.0.bias")
            x = gelu(x @ h["p_head.1.weight"].T + h["p_head.1.bias"])
            return (x @ h["p_head.3.weight"].T + h["p_head.3.bias"])[..., 0].numpy().astype(np.float64)


def gelu(x):
    # belief_numpy._gelu's form (tanh or erf) is matched in the test against UnifiedNumpy.policy_logits
    import torch
    return torch.nn.functional.gelu(x, approximate=GELU_APPROX)


GELU_APPROX = "none"


# ------------------------------------------------------------------ likelihood

def _listing_arrays(actions):
    cards = np.fromiter((CARD_INDEX[c] for a in actions for c in a), dtype=np.int64)
    offsets = np.zeros(len(actions) + 1, dtype=np.int64)
    np.cumsum([len(a) for a in actions], out=offsets[1:])
    return cards, offsets


def _lse(xs):
    m = max(xs)
    return m + math.log(sum(math.exp(x - m) for x in xs))


def lead_logsumexp(hand, ordering, lg):
    """S113's closed form: log sum over every legal lead of exp(sum of its cards' log-odds)."""
    from shengji.harvest.legal import _lead_groups
    terms = []
    for _suit, cards in _lead_groups(list(hand), ordering):
        cnt = Counter(cards)
        tot = sum(_lse([k * float(lg[CARD_INDEX[code]]) for k in range(c + 1)]) for code, c in cnt.items())
        terms.append(tot + math.log1p(-math.exp(-tot)) if tot > 1e-12 else -math.inf)
    return _lse(terms)


def s136_loglik(model, prefix, states, seat, cands, *, timing=None, max_batch=512):
    """Per candidate world (hands, buried as code lists), sum over past plays t by seats != seat of
    log softmax_{legal plays}(S136 card-log-odds sums)[played action]; -inf when illegal. Also returns
    the per-play contributions' count."""
    from shengji.harvest import legal as HL
    from shengji.train import pv_native
    from shengji.train.cwv_prior_admission import root_clone
    n = len(cands)
    ll = np.zeros(n, np.float64)
    tm = timing if timing is not None else Counter()
    T = len(states)
    # cards each seat held at t and has played since (the record's actual plays from t on)
    played_after = [[Counter() for _ in range(4)] for _ in range(T + 1)]
    for t in range(T - 1, -1, -1):
        played_after[t] = [Counter(c) for c in played_after[t + 1]]
        played_after[t][int(prefix[t]["seat"])].update(prefix[t]["cards"])
    nplays = 0
    for t, s, chosen, rnd_t, refs in states:
        if s == seat:
            continue
        t0 = time.perf_counter()
        alive = np.flatnonzero(np.isfinite(ll))
        add = played_after[t]
        hands_t = []
        for i in alive:
            hands, buried = cands[i]
            hands_t.append([list(hands[q]) + list(add[q].elements()) for q in range(4)])
        st = SeatState(rnd_t, s, refs)
        own = np.stack([counts(h[s]) for h in hands_t]) if len(hands_t) else np.zeros((0, 54), np.float32)
        bur = np.stack([counts(cands[i][1]) for i in alive]) if len(alive) else np.zeros((0, 54), np.float32)
        played = list(chosen)
        clones = [root_clone(rnd_t, h, cands[i][1]) for h, i in zip(hands_t, alive)]
        legal_ok = np.array([HL.is_legal(c, s, played) for c in clones], bool)
        X, M, rc, ok = st.batch(own, bur)
        good = legal_ok & ok
        ll[alive[~good]] = -math.inf
        t1 = time.perf_counter(); tm["feat"] += t1 - t0
        gi = np.flatnonzero(good)
        if not len(gi):
            continue
        enc = model.enc(st.inp)
        lgs = np.concatenate([model.card_logits(st.inp, enc, X[gi[a:a + max_batch]], M[gi[a:a + max_batch]],
                                                rc[gi[a:a + max_batch]]) for a in range(0, len(gi), max_batch)])
        t2 = time.perf_counter(); tm["forward"] += t2 - t1
        pidx = [CARD_INDEX[c] for c in played]
        lead = rnd_t.trick.plays[0].cards if rnd_t.trick is not None and rnd_t.trick.plays else None
        cache = {}
        for j, k in enumerate(gi):
            hand = clones[k].hands[s]
            lg = lgs[j]
            if lead is None:
                lse = lead_logsumexp(hand, rnd_t.ordering, lg)
            else:
                key = tuple(sorted(hand))
                got = cache.get(key)
                if got is None:
                    listing = pv_native.follow_listing(list(hand), list(lead), rnd_t.ordering, None)
                    if listing is None:
                        got = _listing_arrays(HL.enumerate_legal(clones[k], s, cap=None).actions)
                    else:
                        got = (np.asarray(listing[0], np.int64), np.asarray(listing[1], np.int64))
                    cache[key] = got
                cidx, off = got
                sums = np.add.reduceat(lg[cidx], off[:-1])
                m = sums.max()
                lse = m + math.log(np.exp(sums - m).sum())
            ll[alive[k]] += lg[pidx].sum() - lse
        nplays += 1
        tm["softmax"] += time.perf_counter() - t2
    return ll, nplays


def ess(logw):
    logw = np.asarray(logw, np.float64)
    fin = np.isfinite(logw)
    if not fin.any():
        return 0.0
    w = np.exp(logw[fin] - logw[fin].max())
    return float(w.sum() ** 2 / (w ** 2).sum())
