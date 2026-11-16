"""A search-free card play: one model forward per decision, no sampled worlds, no value search.

The model is the unified sequence model (``train.unified_seq``: the belief trunk with its policy head,
run by ``ai.unified_numpy``) plus a candidate head that scores each proposed play from the trunk's
states.  A decision is:

1. featurize the actor's information set exactly as the served belief proposal does
   (``ai.belief_numpy.decision_inputs``) and run the trunk once;
2. propose at most ``CANDIDATES`` plays without any search: the heuristic's play (what a served
   search plays when its budget expires) first, then the legal plays ranked by the policy head
   (the mean of the play's card log-odds, ties in enumeration order).  A lead of two or more cards
   other than the heuristic's is proposed only when the engine accepts it against the whole unseen
   pool held by one opponent, so a proposed throw cannot be refused in any deal;
3. score every proposed play with the candidate head and play the highest logit (ties to the
   earlier proposal).

Every candidate is described from the actor's own hand and the public trick only
(``candidate_token``); the round's hidden hands are never read.  A candidate is encoded as an
accepted play.

Declaring and burying are the wrapped bot's, unchanged: ``SearchFreeBot`` replaces ``decide_play``
only.  Any error in the model path plays the heuristic's play and leaves a
``search-free-fallback-v1`` record.

Off by default.  ``SHENGJI_SEARCH_FREE_CKPT`` + ``SHENGJI_SEARCH_FREE_SHA256`` register one more
policy, ``<SHENGJI_BOT>-sf<sha8>`` (``ai.registry``); no existing name, recipe digest or decision
changes, and without the two variables nothing here is imported by the registry.

A package is one ``.npz``: the unified package's arrays (``w:`` trunk, ``h:`` heads) plus the
candidate head under ``c:``, schema ``shengji-search-free-numpy-v1``.
"""
from __future__ import annotations

import hashlib
import io
import json
import math
import os
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

SCHEMA = "shengji-search-free-numpy-v1"
DECISION_SCHEMA = "search-free-decision-v1"
FALLBACK_SCHEMA = "search-free-fallback-v1"
ENV_CKPT = "SHENGJI_SEARCH_FREE_CKPT"
ENV_SHA256 = "SHENGJI_SEARCH_FREE_SHA256"
TOKEN = "sf"
#: plays scored per decision, the heuristic's included
CANDIDATES = 8
#: legal plays enumerated per decision before the policy head ranks them
CAP = 4000
#: how the policy head ranks a play: the mean of its cards' log-odds
RANK = "mean"
N_CARDS = 54
CAND_LAYERS = 2
CAND_HEADS = 4
PACKAGE_MAX_BYTES = 96 * 1024 * 1024


class SearchFreeError(ValueError):
    pass


def cand_shapes(config: Mapping[str, Any]) -> dict[str, tuple[int, ...]]:
    d, xh = int(config["trunk"]["d"]), int(config["trunk"]["x_hidden"])
    out = {"typ": (4, d), "hand": (d,), "incand": (d,),
           "tok.0.weight": (d, d + 14), "tok.0.bias": (d,), "tok.2.weight": (d, d), "tok.2.bias": (d,),
           "prev.weight": (d, d), "prev.bias": (d,), "ctx.weight": (d, xh), "ctx.bias": (d,),
           "ln.weight": (d,), "ln.bias": (d,),
           "out.0.weight": (d,), "out.0.bias": (d,), "out.1.weight": (256, d), "out.1.bias": (256,),
           "out.3.weight": (2, 256), "out.3.bias": (2,)}
    for i in range(CAND_LAYERS):
        p = f"layers.{i}."
        out.update({p + "self_attn.in_proj_weight": (3 * d, d), p + "self_attn.in_proj_bias": (3 * d,),
                    p + "self_attn.out_proj.weight": (d, d), p + "self_attn.out_proj.bias": (d,),
                    p + "linear1.weight": (2 * d, d), p + "linear1.bias": (2 * d,),
                    p + "linear2.weight": (d, 2 * d), p + "linear2.bias": (d,),
                    p + "norm1.weight": (d,), p + "norm1.bias": (d,),
                    p + "norm2.weight": (d,), p + "norm2.bias": (d,)})
    return out


class SearchFreeModel:
    """A validated, read-only model: the unified trunk and policy head, and the candidate head."""

    def __init__(self, config: Mapping[str, Any], trunk_weights: Mapping[str, np.ndarray],
                 head_weights: Mapping[str, np.ndarray], cand_weights: Mapping[str, np.ndarray],
                 metadata: Mapping[str, Any], dtype=np.float32):
        from ..ai.unified_numpy import UnifiedNumpy
        self.unified = UnifiedNumpy(config, trunk_weights, head_weights, metadata, dtype=dtype)
        self.config = self.unified.config
        self.metadata = dict(metadata)
        want = cand_shapes(self.config)
        if set(cand_weights) != set(want):
            raise SearchFreeError(f"candidate head weights differ from the config: "
                                  f"{sorted(set(cand_weights) ^ set(want))[:3]}")
        c = {}
        for k, shape in want.items():
            a = np.asarray(cand_weights[k], dtype)
            if a.shape != shape or not np.isfinite(a).all():
                raise SearchFreeError(f"{k}: shape {a.shape} != {shape} or non-finite")
            a = a.copy()
            a.setflags(write=False)
            c[k] = a
        self.c = c
        self.dtype = np.dtype(dtype)
        self.package_sha256: str | None = None

    def __deepcopy__(self, memo):
        return self

    def trunk_states(self, inp: Mapping[str, Any]) -> dict[str, np.ndarray]:
        """One trunk forward: the encoder states of the plays so far, the 54 card states, the row
        context, the card table and the policy head's 54 card log-odds."""
        from ..ai.belief_numpy import _gelu, _ln
        u = self.unified
        h = u.h
        enc = u.trunk.encode_history(inp)
        q, g = u.card_states(inp, enc)
        x = _ln(q, h["p_head.0.weight"], h["p_head.0.bias"])
        x = _gelu(x @ h["p_head.1.weight"].T + h["p_head.1.bias"])
        card_logits = (x @ h["p_head.3.weight"].T + h["p_head.3.bias"])[:, 0]
        return {"enc": enc, "q": q, "g": g, "ce": u.trunk._card_table(inp), "card_logits": card_logits}

    def _mha(self, prefix: str, x: np.ndarray) -> np.ndarray:
        c = self.c
        K, L, d = x.shape
        dh = d // CAND_HEADS
        qkv = x @ c[prefix + "in_proj_weight"].T + c[prefix + "in_proj_bias"]

        def split(a):
            return a.reshape(K, L, CAND_HEADS, dh).transpose(0, 2, 1, 3)
        qh, kh, vh = split(qkv[..., :d]), split(qkv[..., d:2 * d]), split(qkv[..., 2 * d:])
        s = qh @ kh.transpose(0, 1, 3, 2) / math.sqrt(dh)
        s = s - s.max(-1, keepdims=True)
        e = np.exp(s)
        a = (e / e.sum(-1, keepdims=True)) @ vh
        a = a.transpose(0, 2, 1, 3).reshape(K, L, d)
        return a @ c[prefix + "out_proj.weight"].T + c[prefix + "out_proj.bias"]

    def score(self, inp: Mapping[str, Any], states: Mapping[str, np.ndarray],
              tokens: Sequence[tuple]) -> tuple[np.ndarray, np.ndarray]:
        """``(values, logits)`` of the candidates; ``tokens`` are ``candidate_token`` results."""
        from ..ai.belief_numpy import DIMS, _gelu, _ln
        c, w, f = self.c, self.unified.trunk.w, self.dtype
        K = len(tokens)
        if not K:
            raise SearchFreeError("no candidate")
        T = len(inp["tok_int"])
        if T >= DIMS["max_plays"]:
            raise SearchFreeError("too many plays")
        ti = np.asarray([t[0] for t in tokens], np.int64).reshape(K, 4)
        tf = np.asarray([t[1] for t in tokens], f)
        tc = np.asarray([t[2] for t in tokens], f)
        ta = np.asarray([t[3] for t in tokens], f)
        seat, pos, trick, lead = ti[:, 0], ti[:, 1], ti[:, 2], ti[:, 3]
        role = (seat - int(inp["banker"])) % 4
        eye4, eye5 = np.eye(4, dtype=f), np.eye(5, dtype=f)
        meta = np.concatenate([eye4[pos], eye5[lead], tf, eye4[role]], -1)
        ce = states["ce"]
        emb = (meta @ w["tok_meta.weight"].T + w["tok_meta.bias"] + w["trick_emb.weight"][trick]
               + tc @ ce + (ta @ ce) @ w["att_proj.weight"].T
               + w["pos_emb.weight"][T] + w["rel_emb.weight"][0])
        raw = np.concatenate([tf, eye4[pos]], -1)
        t = _gelu(np.concatenate([emb, raw], -1) @ c["tok.0.weight"].T + c["tok.0.bias"])
        t = t @ c["tok.2.weight"].T + c["tok.2.bias"] + c["typ"][0]
        enc = states["enc"]
        prev = enc[-1] if len(enc) else np.zeros(ce.shape[1], f)
        pv = prev @ c["prev.weight"].T + c["prev.bias"] + c["typ"][1]
        cx = states["g"] @ c["ctx.weight"].T + c["ctx.bias"] + c["typ"][2]
        hand = (np.asarray(inp["X"], f)[:N_CARDS] > 0).astype(f)
        cards = (_ln(states["q"], c["ln.weight"], c["ln.bias"]) + c["typ"][3] + hand[:, None] * c["hand"])[None] \
            + (tc > 0).astype(f)[..., None] * c["incand"]
        x = np.concatenate([t[:, None], np.broadcast_to(pv, (K, 1, pv.shape[-1])),
                            np.broadcast_to(cx, (K, 1, cx.shape[-1])), cards], 1).astype(f, copy=False)
        for i in range(CAND_LAYERS):
            p = f"layers.{i}."
            x = x + self._mha(p + "self_attn.", _ln(x, c[p + "norm1.weight"], c[p + "norm1.bias"]))
            y = _ln(x, c[p + "norm2.weight"], c[p + "norm2.bias"])
            y = _gelu(y @ c[p + "linear1.weight"].T + c[p + "linear1.bias"])
            x = x + y @ c[p + "linear2.weight"].T + c[p + "linear2.bias"]
        o = _ln(x[:, 0], c["out.0.weight"], c["out.0.bias"])
        o = _gelu(o @ c["out.1.weight"].T + c["out.1.bias"]) @ c["out.3.weight"].T + c["out.3.bias"]
        return o[:, 0], o[:, 1]


def save_package(path: str | os.PathLike, config: Mapping[str, Any], trunk_weights: Mapping[str, np.ndarray],
                 head_weights: Mapping[str, np.ndarray], cand_weights: Mapping[str, np.ndarray],
                 metadata: Mapping[str, Any]) -> str:
    from ..ai.belief_numpy import DIMS
    model = SearchFreeModel(config, trunk_weights, head_weights, cand_weights, metadata)
    arrays = {f"w:{k}": np.asarray(v, np.float32) for k, v in trunk_weights.items()}
    arrays.update({f"h:{k}": np.asarray(v, np.float32) for k, v in head_weights.items()})
    arrays.update({f"c:{k}": np.asarray(v, np.float32) for k, v in cand_weights.items()})
    arrays["schema"] = np.asarray(SCHEMA)
    arrays["config"] = np.asarray(json.dumps(model.config, sort_keys=True))
    arrays["metadata"] = np.asarray(json.dumps(dict(metadata, dims=DIMS), sort_keys=True, default=str))
    tmp = Path(str(path) + ".tmp")
    with open(tmp, "wb") as fh:
        np.savez(fh, **arrays)
    os.replace(tmp, path)
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_package(path: str | os.PathLike, sha256: str | None = None, dtype=np.float32) -> SearchFreeModel:
    from ..ai.belief_numpy import DIMS
    p = Path(path)
    if p.stat().st_size > PACKAGE_MAX_BYTES:
        raise SearchFreeError("package too large")
    raw = p.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if sha256 is not None and digest != sha256:
        raise SearchFreeError(f"package sha256 {digest} != expected {sha256}")
    with np.load(io.BytesIO(raw), allow_pickle=False) as z:
        if str(z["schema"]) != SCHEMA:
            raise SearchFreeError(f"schema {z['schema']} != {SCHEMA}")
        config = json.loads(str(z["config"]))
        metadata = json.loads(str(z["metadata"]))
        if metadata.get("dims") != DIMS:
            raise SearchFreeError("package input widths differ from this runtime")
        parts = {tag: {k[2:]: z[k] for k in z.files if k.startswith(tag + ":")} for tag in "whc"}
    model = SearchFreeModel(config, parts["w"], parts["h"], parts["c"], metadata, dtype=dtype)
    model.package_sha256 = digest
    return model


# ------------------------------------------------------------------ candidates

def candidate_token(rnd, seat: int, cards: Sequence[str]) -> tuple:
    """One candidate play as a history token (``train.belief_history`` columns), from the actor's
    hand and the public trick: ``((seat, position, trick index, lead suit), floats, card counts,
    attempt counts)``.  The play is described as accepted (no refused throw)."""
    from ..engine.cards import SUITS, TRUMP, points
    from ..rl.encode import CARD_INDEX
    from .belief_history import N_TOKEN_FLOAT, _winner_so_far
    o = rnd.ordering
    trick = rnd.trick
    cards = list(cards)
    pos = len(trick.plays)
    lead_eff = o.eff_suit(trick.plays[0].cards[0]) if pos else o.eff_suit(cards[0])
    n_lead = sum(o.eff_suit(c) == lead_eff for c in cards)
    f = np.zeros(N_TOKEN_FLOAT, np.float32)
    f[0] = len(cards) / 8.0
    f[1] = n_lead / len(cards)
    f[2] = all(o.eff_suit(c) == TRUMP for c in cards)
    if pos:
        prev_winner = _winner_so_far(trick, o)
        after = type(trick)(leader=trick.leader,
                            plays=list(trick.plays) + [type(trick.plays[0])(seat, cards)])
        f[3] = n_lead < len(cards)
        f[4] = _winner_so_far(after, o) == seat
        f[5] = (prev_winner - seat) % 4 == 2
        f[6] = (prev_winner - seat) % 2 == 1
    f[7] = sum(points(c) for c in cards) / 25.0
    f[8] = sum(points(c) for tp in trick.plays for c in tp.cards) / 50.0
    counts = np.zeros(N_CARDS, np.float32)
    for code in cards:
        counts[CARD_INDEX[code]] += 1
    eff_order = tuple(SUITS) + (TRUMP,)
    return ((int(seat), pos, len(rnd.history), eff_order.index(lead_eff)), f, counts,
            np.zeros(N_CARDS, np.float32))


def _stands_in_every_deal(rnd, seat: int, cards: Sequence[str], pool: list[str]) -> bool:
    from ..engine.legal import validate_lead
    _, message = validate_lead(list(cards), list(rnd.hands[seat]), [pool, [], []], rnd.ordering)
    return message is None


def propose(rnd, seat: int, anchor: Sequence[str], card_logits: np.ndarray, *,
            candidates: int = CANDIDATES, cap: int | None = CAP, rank: str = RANK) -> dict[str, Any]:
    """The plays to score: ``anchor`` first, then legal plays by the mean of their cards' log-odds
    (ties in enumeration order), ``candidates`` in all.  On a lead, a play of two or more cards
    other than the anchor is kept only when no deal of the unseen cards refuses it."""
    from ..ai.memory import Memory
    from ..harvest.legal import enumerate_legal
    from ..rl.encode import CARD_INDEX
    legal = enumerate_legal(rnd, seat, cap=cap, must_include=[list(anchor)])
    actions = [list(a) for a in legal.actions]
    anchor_key = tuple(sorted(anchor))
    anchor_index = next(i for i, a in enumerate(actions) if tuple(sorted(a)) == anchor_key)
    mult = np.zeros((len(actions), N_CARDS), np.float64)
    for i, action in enumerate(actions):
        for card in action:
            mult[i, CARD_INDEX[card]] += 1
    scores = mult @ np.asarray(card_logits, np.float64)
    if rank == "mean":
        scores = scores / mult.sum(-1)
    elif rank != "sum":
        raise SearchFreeError("rank is 'mean' or 'sum'")
    ranked = sorted(range(len(actions)), key=lambda i: (-scores[i], i))
    lead = not rnd.trick.plays
    pool = None
    chosen, skipped = [anchor_index], 0
    for i in ranked:
        if len(chosen) >= candidates:
            break
        if i == anchor_index:
            continue
        if lead and len(actions[i]) > 1:
            if pool is None:
                pool = list(Memory(rnd, seat, own_kitty=True).unseen.elements())
            if not _stands_in_every_deal(rnd, seat, actions[i], pool):
                skipped += 1
                continue
        chosen.append(i)
    return {"actions": [actions[i] for i in chosen], "legal": len(actions), "legal_count": legal.count,
            "legal_complete": bool(legal.complete), "lead": bool(lead), "unsafe_skipped": skipped}


# ------------------------------------------------------------------ the bot

class SearchFreeBot:
    """``base`` with its card play replaced by the search-free decision; every other attribute
    (declaring, burying, public observation, records) is ``base``'s."""

    def __init__(self, base, model: SearchFreeModel, *, candidates: int = CANDIDATES, cap: int | None = None):
        from ..ai.heuristic import HeuristicBot
        from ..ai.refusal import RefusalLedger
        if type(candidates) is not int or not 1 <= candidates <= 64:
            raise SearchFreeError("candidates must be an integer in [1, 64]")
        if not model.package_sha256:
            raise SearchFreeError("the model has no package sha256 (load it with load_package)")
        self.base = base
        self.model = model
        self.candidates = candidates
        self.cap = cap if cap is not None else getattr(base, "cap", CAP)
        self._heuristic = base if isinstance(base, HeuristicBot) else HeuristicBot()
        self._ledger = RefusalLedger()
        self.policy_name = f"{getattr(base, 'policy_name', type(base).__name__)}-{TOKEN}{model.package_sha256[:8]}"
        self.last_decision_record = None
        self.search_free_decisions = 0
        self.search_free_fallbacks = 0

    def __getattr__(self, name):
        if name == "base" or name.startswith("__"):
            raise AttributeError(name)
        return getattr(self.base, name)

    def observe_public(self, rnd) -> None:
        self._ledger.observe(rnd)
        observe = getattr(self.base, "observe_public", None)
        if observe is not None:
            observe(rnd)

    def decide_declare(self, rnd, seat, final=False):
        return self.base.decide_declare(rnd, seat, final=final)

    def decide_bury(self, rnd, seat):
        return self.base.decide_bury(rnd, seat)

    def decide_play(self, rnd, seat):
        from ..ai.belief_numpy import decision_inputs
        from ..ai.heuristic import HeuristicBot
        started = time.perf_counter()
        self.last_decision_record = None
        anchor = list(HeuristicBot.decide_play(self._heuristic, rnd, seat))
        try:
            refusals = self._ledger.observe(rnd)
            inp = decision_inputs(rnd, seat, refusals)
            states = self.model.trunk_states(inp)
            prop = propose(rnd, seat, anchor, states["card_logits"], candidates=self.candidates, cap=self.cap)
            actions = prop.pop("actions")
            if len(actions) == 1:
                pick, values, logits = 0, None, None
            else:
                values, logits = self.model.score(inp, states, [candidate_token(rnd, seat, a) for a in actions])
                if not (np.isfinite(values).all() and np.isfinite(logits).all()):
                    raise SearchFreeError("non-finite candidate scores")
                pick = int(np.argmax(logits))
            played = list(actions[pick])
        except Exception as exc:
            self.search_free_fallbacks += 1
            self.last_decision_record = {
                "schema": FALLBACK_SCHEMA, "policy": self.policy_name, "action": list(anchor),
                "played": list(anchor), "reason": "search-free-error", "error_class": type(exc).__name__,
                "error_message": str(exc)[:200], "elapsed_seconds": time.perf_counter() - started,
                "work_complete": False}
            return list(anchor)
        self.search_free_decisions += 1
        self.last_decision_record = {
            "schema": DECISION_SCHEMA, "policy": self.policy_name, "played": played,
            "candidates": len(actions), "selected": pick, "anchor_selected": pick == 0,
            "logits": None if logits is None else [round(float(v), 5) for v in logits],
            "values": None if values is None else [round(float(v), 5) for v in values],
            "refusals": len(refusals), "seconds": time.perf_counter() - started, **prop}
        return played


def registry_entries(registry: Mapping[str, Any], environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    """``{<SHENGJI_BOT>-sf<sha8>: factory}`` when both package variables are set, else empty.  The
    factory builds the named served bot through ``registry`` and wraps it."""
    env = os.environ if environ is None else environ
    path, sha = env.get(ENV_CKPT), env.get(ENV_SHA256)
    if not path and not sha:
        return {}
    if not path or not sha or len(sha) != 64:
        raise SearchFreeError(f"{ENV_CKPT} and {ENV_SHA256} (64 hex) are set together")
    base_name = env.get("SHENGJI_BOT", "smart")
    if base_name not in registry:
        raise SearchFreeError(f"SHENGJI_BOT {base_name!r} is not a registered policy")
    base_factory = registry[base_name]
    name = f"{base_name}-{TOKEN}{sha[:8]}"
    cache: list[SearchFreeModel] = []

    def make(**kw):
        import inspect
        if not cache:
            cache.append(load_package(path, sha256=sha))
        try:
            params = inspect.signature(base_factory).parameters
        except (TypeError, ValueError):
            params = {}
        takes = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()) or "seed" in params
        base = base_factory(**kw) if takes else base_factory()
        if getattr(base, "policy_name", None) is None:
            try:
                base.policy_name = base_name
            except AttributeError:
                pass
        bot = SearchFreeBot(base, cache[0])
        bot.policy_name = name
        return bot
    return {name: make}
