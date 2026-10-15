"""Offline world weighting: how close do reweighted sampler worlds get to the deal?

DIAGNOSTIC ONLY, never served.  For held-out store decisions this module draws
``W`` worlds through the served sampler path (`belief_labels.sampler_counts`'s
branch: refusal-aware when the round has a refusal on record, else the plain
draw, both through `MCBot._sample_hands` and `_complete_determinized_hands`),
scores every world against the sealed deal with the soft-oracle card agreement
(`pv_soft_oracle.agreement`: hidden copies placed with their true receiver, over
the hidden copies), and stores, per world, everything a weighting needs:

* ``loglik`` -- for every earlier play of another seat in this round, the log
  probability of the ATTEMPTED cards under the package's policy head, at the
  state of that play, with that world's hands substituted (``event_log_probs``).
  Two readings of the head's 54 card log-odds are stored: ``listwise`` (softmax
  over the capped legal set of the factorised action scores, the admission's own
  arithmetic) and ``bernoulli`` (independent per-copy Bernoulli over the cards in
  the player's hand, no enumeration).
* ``counts`` -- the world's copies per (receiver, card), receivers seat-relative
  (next, partner, previous, kitty), so any per-card marginal model -- a kitty
  head, a history belief model -- reweights the same worlds afterwards
  (``marginal_log_weights``) without redrawing them.
* ``kitty_x`` -- the actor's pre-play kitty-inference input
  (`kitty_inference.features`), so a kitty head trained later applies to the
  same states.

The head reads a complete world (the v2 root row carries all four hands and the
kitty).  At an earlier state the substituted world gives the player its own
hand at that point (its current hand in the world plus everything it has played
since) and the same for every other seat; the actor's own hand is the true one.
Serving feeds sampled complete worlds to the same head, so this is the head as
served; a well-fitted head cannot use the other hands to predict a play the
player chose without seeing them, and whatever dependence it does have adds
noise, not the truth, to the weights.

``analyze`` turns the stored terms into weights, ``log w(s) = beta * sum_t
log max(p_t(s), eps_t)`` over the chosen events (all of the round, or the
current and previous trick), plus the hard-filter reading (keep the worlds
whose every play clears a per-relation threshold), and reports weighted card
agreement, effective sample size and the agreement of a 64-world resample, by
trick.  Offline agreement is not playing strength.

CLI: ``collect`` / ``analyze``; see ``build_parser``.
"""
from __future__ import annotations

import argparse
import copy
import dataclasses
import hashlib
import json
import math
import os
import sys
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Mapping, Sequence

import numpy as np

from ..ai.memory import Memory
from ..rl.encode import CARD_INDEX, N_CARDS
from .belief_labels import (BeliefLabelError, Decision, cluster_paths, excluded_windows,
                            iter_decisions, role_of, seed_excluded, split_of)
from .data import deal_key

SCHEMA = "shengji-world-weighting-v1"
#: seat-relative receivers of a world's copies: next, partner, previous, kitty
N_RECV = 4
KITTY = 3
#: the served legal-enumeration cap (`pv_search_policy.DEFAULTS["cap"]`)
SERVED_CAP = 4000
#: the split of `belief_labels` (its defaults), so held-out states are S17's test deals
CALIB, TEST = 0.06, 0.12
LISTWISE, BERNOULLI = "listwise", "bernoulli"
READINGS = (LISTWISE, BERNOULLI)
#: log-probabilities are stored at float16, floored here (far below any floor used);
#: a world in which the play is illegal is stored at ``ILLEGAL``
LOGP_FLOOR = -30.0
ILLEGAL = -60.0


class WorldWeightingError(ValueError):
    pass


# ------------------------------------------------------------------ replay with history

@dataclass
class PlayEvent:
    """One committed play of the round: who, what was attempted, what left the
    hand, and a private copy of the state just before it."""
    seat: int
    attempted: list
    played: list
    snap: Any
    trick: int


@dataclass
class StateView:
    decision: Decision
    events: list            # every earlier play of this round, in table order
    start: Any              # the round at its first play (pre-play facts)
    setup: Mapping[str, Any]


def iter_states(records: Iterable[Mapping[str, Any]], *, ordered: bool = False,
                want: Callable[[Decision], bool] | None = None) -> Iterator[StateView]:
    """`belief_labels.iter_decisions` with each round's earlier plays attached.

    Each yielded decision carries a private copy of its state, so a view stays
    valid after the replay moves on.  ``want`` picks the decisions to yield;
    every play is still snapshotted, since a later chosen decision needs all of
    them."""
    events: list[PlayEvent] = []
    start = None
    current = None
    for d in iter_decisions(records, ordered=ordered):
        if d.round_index != current:
            current = d.round_index
            events = []
            start = copy.deepcopy(d.rnd)
        snap = copy.deepcopy(d.rnd)
        if want is None or want(d):
            yield StateView(dataclasses.replace(d, rnd=snap), list(events), start,
                            d.record["setup"])
        attempted = list(d.record["action"])
        played = list(d.record.get("engine_play") or attempted)
        events.append(PlayEvent(d.seat, attempted, played, snap, len(snap.history) + 1))


def played_since(events: Sequence[PlayEvent], index: int) -> list[Counter]:
    """Per seat, the cards that left its hand from play ``index`` (inclusive) on."""
    out = [Counter() for _ in range(4)]
    for ev in events[index:]:
        out[ev.seat].update(ev.played)
    return out


def hands_at(event: PlayEvent, since: Sequence[Counter], actor: int,
             world_hands: Sequence[Sequence[str]]) -> list[list[str]]:
    """Every hand at ``event`` in a world: the world's hand now plus what the seat
    has played since; the actor's own hand is the true one."""
    out = []
    for s in range(4):
        if s == actor:
            out.append(list(event.snap.hands[s]))
        else:
            out.append(list(world_hands[s]) + list(since[s].elements()))
    return out


# ------------------------------------------------------------------ worlds

def served_worlds(rnd, seat: int, refusals, n: int, seed: int):
    """``(sampler, mem, worlds, stats)``: ``n`` worlds by the served branch."""
    from ..ai.cwv_policy import sample_worlds
    from ..ai.mcbot import MCBot
    from ..ai.refusal import sample_worlds_refusal_aware
    sampler = MCBot(seed=seed)
    mem = Memory(rnd, seat, own_kitty=getattr(sampler, "BANKER_KITTY", True))
    stats: dict = {}
    if refusals:
        worlds, attempts, stats = sample_worlds_refusal_aware(sampler, rnd, seat, n,
                                                              list(refusals), mem=mem)
    else:
        worlds, attempts = sample_worlds(sampler, rnd, seat, n, mem=mem)
    if len(worlds) != n:
        raise WorldWeightingError(f"sampler short: {len(worlds)}/{n}")
    return sampler, mem, worlds, dict(stats, attempts=int(attempts))


def world_counts(worlds, seat: int, kitty_hidden: bool) -> np.ndarray:
    """``(W, 4, 54)`` uint8: each world's copies per seat-relative receiver."""
    out = np.zeros((len(worlds), N_RECV, N_CARDS), np.uint8)
    for w, (hands, buried) in enumerate(worlds):
        for rel in (1, 2, 3):
            for card in hands[(seat + rel) % 4]:
                out[w, rel - 1, CARD_INDEX[card]] += 1
        if kitty_hidden:
            for card in buried:
                out[w, KITTY, CARD_INDEX[card]] += 1
    return out


def marginal_log_weights(counts: np.ndarray, marginals: np.ndarray, base: np.ndarray | None = None,
                         floor: float = 1e-4) -> np.ndarray:
    """Per-world log importance weights of a per-card marginal model.

    ``counts`` ``(W, 4, 54)`` from ``world_counts``; ``marginals`` ``(54, 4)`` or
    ``(4, 54)``: the model's probability that one hidden copy of a card is with
    each receiver; ``base`` the same for the proposal (default: the worlds' own
    empirical marginal, which is what the sampler proposes).  The weight is the
    product over the world's copies of model / proposal -- the factorised
    reweighting a history belief model or a kitty head plugs into."""
    m = np.asarray(marginals, np.float64)
    if m.shape == (N_CARDS, N_RECV):
        m = m.T
    if m.shape != (N_RECV, N_CARDS):
        raise WorldWeightingError("marginals must be (54, 4) or (4, 54)")
    c = counts.astype(np.float64)
    if base is None:
        tot = c.sum(axis=(0, 1))                                   # copies per card over worlds
        base = np.where(tot > 0, c.sum(axis=0) / np.maximum(tot, 1), 0.0)
    b = np.asarray(base, np.float64)
    if b.shape == (N_CARDS, N_RECV):
        b = b.T
    ratio = np.log(np.maximum(m, floor)) - np.log(np.maximum(b, floor))
    return np.einsum("wrc,rc->w", c, ratio)


# ------------------------------------------------------------------ the likelihood pass

def _lead_log_partition(hand, ordering, logits):
    """Exact mass of all nonempty same-effective-suit submultisets.

    Copies of one code are indistinguishable (no binomial multiplicity).
    Track nonempty mass directly in log space: subtracting the empty term
    from a product loses all precision when every logit is very negative.
    """
    groups = {}
    for card, copies in Counter(hand).items():
        suit = ordering.eff_suit(card)
        nonempty = float(np.logaddexp.reduce(
            np.arange(1, copies + 1, dtype=np.float64) * logits[CARD_INDEX[card]]))
        previous = groups.get(suit, -np.inf)
        groups[suit] = float(np.logaddexp(
            previous + np.logaddexp(0.0, nonempty), nonempty))
    return float(np.logaddexp.reduce(list(groups.values())))


def event_log_probs(predict, version: int, event: PlayEvent, since: Sequence[Counter],
                    actor: int, worlds, cap: int = SERVED_CAP) -> dict:
    """Log-probabilities of ``event``'s attempted cards in every world.

    Returns ``{"listwise": (W,), "bernoulli": (W,), "legal": (W,) int}``."""
    from ..harvest.legal import enumerate_legal, count_lead_actions, is_legal
    from .cwv_prior_admission import root_clone
    from .policy_prior import flat_input, root_tensors
    rows, legal_sets, hand_counts = [], [], []
    target = np.zeros(N_CARDS, np.float64)
    for card in event.attempted:
        target[CARD_INDEX[card]] += 1
    for hands, buried in worlds:
        h = hands_at(event, since, actor, hands)
        clone = root_clone(event.snap, h, buried)
        rows.append(flat_input(root_tensors(clone, event.seat, version), version))
        try:
            acting = (clone.phase == 'play' and clone.turn == event.seat
                      and clone.ordering is not None and clone.trick is not None)
            count = (count_lead_actions(h[event.seat], clone.ordering)
                     if acting and not clone.trick.plays else None)
            if acting and not is_legal(clone, event.seat, event.attempted):
                # The old enumerator rejects this same must_include action,
                # but only after constructing/counting its full legal set.
                # Keep model evaluation and finite-logit validation unchanged.
                legal_sets.append(None)
            elif count and (cap is None or count <= cap):
                # Same complete support as the enumerator, without building
                # its action listing or the actions-by-54 score matrix.
                legal_sets.append((h[event.seat], clone.ordering, count))
            else:
                # Capped support and follow obligations are unchanged.
                legal = enumerate_legal(clone, event.seat, cap=cap, must_include=[event.attempted])
                legal_sets.append(legal.actions)
        except ValueError as exc:
            # the world contradicts the play itself (a follow-suit or pair rule the
            # sampler's constraints do not carry): probability zero
            if "must_include action is illegal" not in str(exc):
                raise
            legal_sets.append(None)
        hc = np.zeros(N_CARDS, np.float64)
        for card in h[event.seat]:
            hc[CARD_INDEX[card]] += 1
        hand_counts.append(hc)
    lo = np.asarray(predict(np.stack(rows).astype(np.float32)), np.float64)
    if lo.shape != (len(worlds), N_CARDS) or not np.isfinite(lo).all():
        raise WorldWeightingError("the head must return finite W x 54 log-odds")
    key = tuple(sorted(event.attempted))
    listwise = np.empty(len(worlds))
    n_legal = np.empty(len(worlds), np.int32)
    for w, actions in enumerate(legal_sets):
        if actions is None:
            listwise[w] = -np.inf
            n_legal[w] = 0
            continue
        if isinstance(actions, tuple):
            hand, ordering, count = actions
            listwise[w] = target @ lo[w] - _lead_log_partition(hand, ordering, lo[w])
            n_legal[w] = count
            continue
        mult = np.zeros((len(actions), N_CARDS))
        at = -1
        for i, action in enumerate(actions):
            for card in action:
                mult[i, CARD_INDEX[card]] += 1
            if at < 0 and tuple(sorted(action)) == key:
                at = i
        if at < 0:
            raise WorldWeightingError("the attempted cards are not in the legal set")
        scores = mult @ lo[w]
        top = scores.max()
        listwise[w] = scores[at] - top - math.log(np.exp(scores - top).sum())
        n_legal[w] = len(actions)
    hc = np.stack(hand_counts)
    log_p = -np.logaddexp(0.0, -lo)                  # log sigmoid
    log_q = -np.logaddexp(0.0, lo)                   # log (1 - sigmoid)
    bernoulli = (target * log_p + (hc - target) * log_q).sum(axis=1)
    bernoulli[n_legal == 0] = -np.inf
    return {LISTWISE: listwise, BERNOULLI: bernoulli, "legal": n_legal}


# ------------------------------------------------------------------ collection

def _state_seed(key: str, round_index: int, decision_index: int) -> int:
    return int(hashlib.sha256(f"{key}|{round_index}|{decision_index}|ww".encode()).hexdigest()[:8], 16)


def _choose(key: str, d: Decision, rate: float) -> bool:
    frac = int(hashlib.sha256(f"{key}|{d.round_index}|{d.decision_index}|pick".encode())
               .hexdigest()[:12], 16) / 16 ** 12
    return frac < rate


@dataclass
class Collected:
    meta: list = field(default_factory=list)
    agreement: list = field(default_factory=list)
    counts: list = field(default_factory=list)
    truth: list = field(default_factory=list)
    kitty_x: list = field(default_factory=list)
    ev_state: list = field(default_factory=list)
    ev_meta: list = field(default_factory=list)
    ev_seconds: list = field(default_factory=list)
    ev_logp: dict = field(default_factory=lambda: {r: [] for r in READINGS})


def collect_state(view: StateView, predict, version: int, *, worlds: int, cap: int,
                  key: str, out: Collected, state_id: int, store_index: int,
                  cluster_index: int, events: bool = True, draw=None) -> dict:
    """Draw, score and store one state's worlds.  ``draw`` replaces the served
    sampler as the world proposal (same signature and return as
    ``served_worlds``); a proposal that is not the sampler supplies its own
    importance weights to ``analyze`` as an extra log-weight array."""
    from . import kitty_inference
    from . import pv_soft_oracle as soft_oracle
    d = view.decision
    rnd, seat = d.rnd, d.seat
    t0 = time.perf_counter()
    sampler, mem, ws, stats = (draw or served_worlds)(
        rnd, seat, d.refusals, worlds, _state_seed(key, d.round_index, d.decision_index))
    layout = soft_oracle.hidden_layout(sampler, rnd, seat, mem, rnd.hands, rnd.buried)
    agree = np.empty(len(ws), np.float32)
    for w, (hands, buried) in enumerate(ws):
        matched, _ = soft_oracle.agreement(layout, hands, buried)
        agree[w] = matched / layout.hidden if layout.hidden else 1.0
    kitty_hidden = bool(layout.kitty_slots)
    counts = world_counts(ws, seat, kitty_hidden)
    truth = world_counts([(rnd.hands, rnd.buried)], seat, kitty_hidden)[0]
    t_sample = time.perf_counter() - t0
    t1 = time.perf_counter()
    n_events = 0
    if events:
        partner = (seat + 2) % 4
        for i, ev in enumerate(view.events):
            if ev.seat == seat:
                continue
            since = played_since(view.events, i)
            te = time.perf_counter()
            got = event_log_probs(predict, version, ev, since, seat, ws, cap=cap)
            out.ev_seconds.append(time.perf_counter() - te)
            for r in READINGS:
                v = np.where(np.isneginf(got[r]), ILLEGAL, np.maximum(got[r], LOGP_FLOOR))
                out.ev_logp[r].append(v.astype(np.float16))
            current = len(rnd.history) + 1
            out.ev_state.append(state_id)
            out.ev_meta.append((current - ev.trick, int(ev.seat == partner),
                                int(not ev.snap.trick.plays),
                                int(Counter(ev.played) != Counter(ev.attempted)),
                                int(np.median(got["legal"])), (ev.seat - seat) % 4))
            n_events += 1
    t_lik = time.perf_counter() - t1
    out.agreement.append(agree)
    out.counts.append(counts)
    out.truth.append(truth)
    out.kitty_x.append(kitty_inference.features(view.start, seat, view.setup))
    out.meta.append((state_id, store_index, cluster_index, d.round_index, d.decision_index,
                     len(rnd.history) + 1, role_of(rnd, seat), len(d.refusals), layout.hidden,
                     n_events, int(kitty_hidden), int(seat), int(rnd.banker)))
    return {"t_sample": t_sample, "t_lik": t_lik, "events": n_events,
            "refusal_rejections": int(stats.get("refusal_rejections", 0))}


META_COLS = ("state", "store", "cluster", "round_index", "decision", "trick", "role",
             "n_refusals", "hidden", "n_events", "kitty_hidden", "seat", "banker")
EV_COLS = ("trick_offset", "partner", "lead", "failed_throw", "legal_median", "rel")


def _save(out_path: Path, c: Collected, timings: list) -> dict:
    arrays = {
        "meta": np.asarray(c.meta, np.int64).reshape(-1, len(META_COLS)),
        "agreement": np.stack(c.agreement) if c.agreement else np.zeros((0, 0), np.float32),
        "counts": np.stack(c.counts) if c.counts else np.zeros((0, 0, N_RECV, N_CARDS), np.uint8),
        "truth": np.stack(c.truth) if c.truth else np.zeros((0, N_RECV, N_CARDS), np.uint8),
        "kitty_x": np.stack(c.kitty_x) if c.kitty_x else np.zeros((0, 0), np.float32),
        "ev_state": np.asarray(c.ev_state, np.int64),
        "ev_meta": np.asarray(c.ev_meta, np.int64).reshape(-1, len(EV_COLS)),
        "ev_seconds": np.asarray(c.ev_seconds, np.float64),
        "timings": np.asarray(timings, np.float64).reshape(-1, 3),
    }
    for r in READINGS:
        arrays[f"ev_{r}"] = (np.stack(c.ev_logp[r]) if c.ev_logp[r]
                             else np.zeros((0, 0), np.float16))
    np.savez_compressed(out_path, **arrays)
    return {"file": out_path.name, "states": len(c.meta), "events": len(c.ev_state),
            "sha256": hashlib.sha256(out_path.read_bytes()).hexdigest()}


def _collect_task(args: tuple) -> dict:
    (paths, store_indices, cluster_indices, out_dir, name, package, sha256, worlds, cap, rate,
     max_states, base_id, events, windows) = args
    from .pv_search_policy import NumpyPriorPredict
    predict = NumpyPriorPredict(package, sha256)
    version = int(predict.version)
    c = Collected()
    timings = []
    failed = []
    state_id = base_id
    t0 = time.time()
    for path, si, ci in zip(paths, store_indices, cluster_indices):
        if len(c.meta) >= max_states:
            break
        with open(path) as fh:
            plays = [r for r in (json.loads(line) for line in fh if line.strip())
                     if r.get("decision_kind") == "play"]
        if not plays or any(seed_excluded(r.get("round_seed"), windows) for r in plays[:1]):
            continue
        key = deal_key(list(plays[0]["deck"]))
        if split_of(key, CALIB, TEST) != "test":
            continue
        try:
            # a deal is always finished once started, so the cap never cuts off its
            # later tricks and the states stay spread over the whole round
            for view in iter_states(plays, want=lambda d: _choose(key, d, rate)):
                t = collect_state(view, predict, version, worlds=worlds, cap=cap, key=key, out=c,
                                  state_id=state_id, store_index=si, cluster_index=ci,
                                  events=events)
                timings.append((t["t_sample"], t["t_lik"], t["events"]))
                state_id += 1
        except (BeliefLabelError, WorldWeightingError, ValueError) as exc:
            failed.append({"path": str(path), "error": str(exc)[:300]})
    res = _save(Path(out_dir) / f"{name}.npz", c, timings) if c.meta else {"file": None, "states": 0}
    return dict(res, failed=failed, seconds=time.time() - t0, chunk=name)


def collect(stores: Sequence[str], out: str, *, package: str, sha256: str, worlds: int,
            cap: int, rate: float, states_per_task: int, tasks_per_store: int, clusters_per_task: int,
            cluster_offset: int, workers: int, events: bool = True, log=print) -> dict:
    out_dir = Path(out)
    out_dir.mkdir(parents=True, exist_ok=True)
    windows = excluded_windows()
    tasks = []
    for si, store in enumerate(stores):
        paths = cluster_paths(store)
        for t in range(tasks_per_store):
            lo = cluster_offset + t * clusters_per_task
            group = [(ci, p) for ci, p in enumerate(paths[lo:lo + clusters_per_task], start=lo)]
            name = f"s{si:02d}-t{t:03d}"
            if (out_dir / f"{name}.npz").exists():
                continue
            tasks.append(([str(p) for _, p in group], [si] * len(group), [ci for ci, _ in group],
                          str(out_dir), name, package, sha256, worlds, cap, rate, states_per_task,
                          (si * 1000 + t) * 100000, events, windows))
    manifest_path = out_dir / "manifest.json"
    manifest = (json.loads(manifest_path.read_text()) if manifest_path.exists() else
                {"schema": SCHEMA, "stores": list(stores), "package": package, "sha256": sha256,
                 "worlds": worlds, "cap": cap, "rate": rate, "split": {"calib": CALIB, "test": TEST},
                 "meta_cols": META_COLS, "ev_cols": EV_COLS, "readings": READINGS,
                 "chunks": []})
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for i, res in enumerate(pool.map(_collect_task, tasks)):
            manifest["chunks"].append(res)
            manifest_path.write_text(json.dumps(manifest, indent=1))
            log(f"[collect] {i + 1}/{len(tasks)} {res['chunk']} states={res['states']} "
                f"failed={len(res['failed'])} {res['seconds']:.0f}s total {time.time() - t0:.0f}s",
                flush=True)
    return manifest


# ------------------------------------------------------------------ analysis

def load(outs: str | os.PathLike | Sequence[str | os.PathLike]) -> dict:
    """Every chunk of one or more collections, concatenated; event rows re-pointed
    to state rows.  State ids are unique within a collection, so each collection
    is offset by its position."""
    if isinstance(outs, (str, os.PathLike)):
        outs = [outs]
    parts = []
    manifests = []
    for n, out in enumerate(outs):
        out_dir = Path(out)
        manifest = json.loads((out_dir / "manifest.json").read_text())
        manifests.append(manifest)
        for chunk in manifest["chunks"]:
            if not chunk.get("file"):
                continue
            path = out_dir / chunk["file"]
            if hashlib.sha256(path.read_bytes()).hexdigest() != chunk["sha256"]:
                raise WorldWeightingError(f"{path}: sha256 mismatch")
            with np.load(path) as z:
                part = {k: z[k] for k in z.files}
            part["meta"] = part["meta"].copy()
            part["meta"][:, 0] += n * 10 ** 12
            part["ev_state"] = part["ev_state"] + n * 10 ** 12
            if "ev_seconds" not in part:
                part["ev_seconds"] = np.full(len(part["ev_state"]), np.nan)
            parts.append(part)
    if not parts:
        raise WorldWeightingError("no states collected")
    widths = {p["agreement"].shape[1] for p in parts if p["agreement"].size}
    if len(widths) != 1:
        raise WorldWeightingError(f"chunks disagree on the world count: {widths}")
    data = {k: np.concatenate([p[k] for p in parts]) for k in parts[0]}
    row_of = {int(s): i for i, s in enumerate(data["meta"][:, 0])}
    data["ev_row"] = np.asarray([row_of[int(s)] for s in data["ev_state"]], np.int64)
    data["manifest"] = manifests
    return data


@dataclass(frozen=True)
class Variant:
    """One weighting: which events, which head reading, how they become weights."""
    name: str
    reading: str = LISTWISE
    beta: float = 1.0
    eps_partner: float = 0.02
    eps_opponent: float = 0.02
    max_offset: int | None = None        # None: the whole round; 1: current + previous trick
    filter: bool = False                 # hard keep/drop at eps (thresholds), not a floor
    min_keep: int = 20
    zero_illegal: bool = False           # a world in which a play is illegal gets weight 0
    legality_only: bool = False          # no likelihood: only the illegal-world zeroing


def variant_log_weights(data: Mapping[str, np.ndarray], v: Variant) -> np.ndarray:
    """``(S, W)`` log weights (unnormalised); zero rows for states without events."""
    S, W = data["agreement"].shape
    logp = data[f"ev_{v.reading}"].astype(np.float64)
    em = data["ev_meta"]
    keep = np.ones(len(em), bool)
    if v.max_offset is not None:
        keep &= em[:, 0] <= v.max_offset
    eps = np.where(em[:, 1] == 1, v.eps_partner, v.eps_opponent)
    rows = data["ev_row"]
    illegal = np.zeros((S, W), bool)
    if v.zero_illegal or v.legality_only:
        for e in np.nonzero(keep)[0]:
            illegal[rows[e]] |= logp[e] <= ILLEGAL / 2
        # a state whose every world is contradicted keeps them all (uniform)
        illegal &= ~illegal.all(axis=1, keepdims=True)
    if v.legality_only:
        return np.where(illegal, -np.inf, 0.0)
    if v.filter:
        ok = np.ones((S, W), bool)
        margin = np.zeros((S, W))
        for e in np.nonzero(keep)[0]:
            ok[rows[e]] &= logp[e] >= math.log(eps[e])
            margin[rows[e]] = np.minimum(margin[rows[e]], logp[e] - math.log(eps[e]))
        out = np.where(ok, 0.0, -np.inf)
        for s in range(S):
            if ok[s].sum() < v.min_keep:
                top = np.argsort(-margin[s], kind="stable")[:v.min_keep]
                out[s] = -np.inf
                out[s, top] = 0.0
        return out
    out = np.zeros((S, W))
    for e in np.nonzero(keep)[0]:
        out[rows[e]] += v.beta * np.maximum(logp[e], math.log(eps[e]))
    return np.where(illegal, -np.inf, out)


def normalise(logw: np.ndarray) -> np.ndarray:
    top = logw.max(axis=1, keepdims=True)
    w = np.exp(logw - top)
    return w / w.sum(axis=1, keepdims=True)


def systematic_resample(w: np.ndarray, k: int, rng: np.random.Generator) -> np.ndarray:
    """``(S, k)`` indices: one systematic resample of ``k`` per row."""
    S, W = w.shape
    cum = np.cumsum(w, axis=1)
    cum[:, -1] = 1.0
    u = (rng.random((S, 1)) + np.arange(k)[None, :]) / k
    return np.stack([np.searchsorted(cum[s], u[s], side="left") for s in range(S)])


TRICK_BUCKETS = ((1, 1), (2, 5), (6, 10), (11, 15), (16, 25))


def _summ(x: np.ndarray) -> dict:
    return {"n": int(len(x)), "mean": float(np.mean(x)) if len(x) else None,
            "se": float(np.std(x, ddof=1) / math.sqrt(len(x))) if len(x) > 1 else None}


def score(data: Mapping[str, np.ndarray], logw: np.ndarray, *, resample: int = 64,
          seed: int = 0) -> dict:
    """Weighted agreement, ESS and resampled agreement, overall and by trick."""
    a = data["agreement"].astype(np.float64)
    w = normalise(logw)
    weighted = (w * a).sum(axis=1)
    uniform = a.mean(axis=1)
    ess = 1.0 / (w ** 2).sum(axis=1)
    idx = systematic_resample(w, resample, np.random.default_rng(seed))
    res = np.take_along_axis(a, idx, axis=1).mean(axis=1)
    gain = weighted - uniform
    trick = data["meta"][:, META_COLS.index("trick")]

    def block(mask):
        return {"states": int(mask.sum()), "uniform": _summ(uniform[mask]),
                "weighted": _summ(weighted[mask]), "gain": _summ(gain[mask]),
                f"resampled{resample}": _summ(res[mask]),
                "ess_median": float(np.median(ess[mask])) if mask.any() else None,
                "ess_p10": float(np.percentile(ess[mask], 10)) if mask.any() else None}

    out = block(np.ones(len(a), bool))
    out["by_trick"] = {f"{lo}-{hi}": block((trick >= lo) & (trick <= hi)) for lo, hi in TRICK_BUCKETS}
    role = data["meta"][:, META_COLS.index("role")]
    out["by_role"] = {name: block(role == i) for i, name in enumerate(("banker", "banker_partner",
                                                                       "defender"))}
    return out


DEFAULT_VARIANTS = (
    Variant("lw_b1_e02", LISTWISE, 1.0, 0.02, 0.02),
    Variant("lw_b05_e02", LISTWISE, 0.5, 0.02, 0.02),
    Variant("lw_b1_split", LISTWISE, 1.0, 0.10, 0.03),
    Variant("lw_b05_split", LISTWISE, 0.5, 0.10, 0.03),
    Variant("lw_b1_e02_recent", LISTWISE, 1.0, 0.02, 0.02, max_offset=1),
    Variant("lw_b05_e02_recent", LISTWISE, 0.5, 0.02, 0.02, max_offset=1),
    Variant("lw_filter_ben", LISTWISE, 1.0, 0.10, 0.03, filter=True),
    Variant("lw_filter_ben_recent", LISTWISE, 1.0, 0.10, 0.03, max_offset=1, filter=True),
    Variant("legal_only", legality_only=True),
    Variant("lw_b1_e02_zi", LISTWISE, 1.0, 0.02, 0.02, zero_illegal=True),
    Variant("lw_b05_e02_zi", LISTWISE, 0.5, 0.02, 0.02, zero_illegal=True),
    Variant("lw_b1_split_zi", LISTWISE, 1.0, 0.10, 0.03, zero_illegal=True),
    Variant("bn_b1_e02", BERNOULLI, 1.0, 0.02, 0.02),
    Variant("bn_b05_e02", BERNOULLI, 0.5, 0.02, 0.02),
)


def analyze(out, *, variants: Sequence[Variant] = DEFAULT_VARIANTS,
            extra: Mapping[str, np.ndarray] | None = None, resample: int = 64) -> dict:
    """Score every variant; ``extra`` adds named ``(S, W)`` log-weight arrays
    (a kitty head, a belief model) alone and on top of each likelihood variant."""
    data = out if isinstance(out, dict) else load(out)
    S, W = data["agreement"].shape
    report: dict[str, Any] = {"states": int(S), "worlds": int(W), "events": int(len(data["ev_state"]))}
    report["uniform"] = score(data, np.zeros((S, W)), resample=resample)
    for v in variants:
        report[v.name] = score(data, variant_log_weights(data, v), resample=resample)
    for name, lw in (extra or {}).items():
        report[name] = score(data, lw, resample=resample)
        for v in variants:
            report[f"{v.name}+{name}"] = score(data, variant_log_weights(data, v) + lw,
                                               resample=resample)
    t = data["timings"]
    ev = t[:, 2]
    report["cost"] = {
        "sample_ms_per_state": float(1000 * t[:, 0].mean()),
        "likelihood_ms_per_state": float(1000 * t[:, 1].mean()),
        "likelihood_ms_per_state_p50": float(1000 * np.median(t[:, 1])),
        "likelihood_ms_per_state_p95": float(1000 * np.percentile(t[:, 1], 95)),
        "events_per_state": float(ev.mean()),
        "ms_per_world_event": float(1000 * t[:, 1].sum() / max(1.0, (ev * W).sum())),
        "worlds": int(W),
    }
    secs = data["ev_seconds"]
    timed = np.isfinite(secs)
    if timed.any():
        em = data["ev_meta"]
        rows = data["ev_row"]
        per_state = np.zeros(S)
        recent = np.zeros(S)
        has = np.zeros(S, bool)
        np.add.at(per_state, rows[timed], secs[timed])
        np.add.at(recent, rows[timed & (em[:, 0] <= 1)], secs[timed & (em[:, 0] <= 1)])
        has[rows[timed]] = True
        report["cost"].update({
            "timed_states": int(has.sum()),
            "recent_ms_per_state_with_events": float(1000 * recent[has].mean()),
            "recent_ms_per_state_with_events_p95": float(1000 * np.percentile(recent[has], 95)),
            "lead_ms_per_event": float(1000 * secs[timed & (em[:, 2] == 1)].mean()),
            "follow_ms_per_event": float(1000 * secs[timed & (em[:, 2] == 0)].mean()),
        })
    return report


# ------------------------------------------------------------------ other models' weights

def iter_collected_states(stores: Sequence[str], meta: np.ndarray) -> Iterator[tuple[int, StateView]]:
    """Replay the stores and yield ``(state id, view)`` for every collected state,
    so another model (a history belief model) computes its inputs at exactly
    these states.  ``stores`` in the collection's order (its manifest)."""
    cols = {c: META_COLS.index(c) for c in ("state", "store", "cluster", "round_index", "decision")}
    wanted: dict[tuple[int, int], dict[tuple[int, int], int]] = {}
    for row in meta:
        wanted.setdefault((int(row[cols["store"]]), int(row[cols["cluster"]])), {})[
            (int(row[cols["round_index"]]), int(row[cols["decision"]]))] = int(row[cols["state"]])
    paths = {si: cluster_paths(store) for si, store in enumerate(stores)}
    for (si, ci), picks in sorted(wanted.items()):
        with open(paths[si][ci]) as fh:
            plays = [r for r in (json.loads(line) for line in fh if line.strip())
                     if r.get("decision_kind") == "play"]
        for view in iter_states(plays, want=lambda d: (d.round_index, d.decision_index) in picks):
            d = view.decision
            yield picks[(d.round_index, d.decision_index)], view


def marginals_log_weights(path: str, data: Mapping[str, np.ndarray]) -> np.ndarray:
    """``(S, W)`` log weights from a per-state marginal file: ``state`` (ids as in
    the collection's ``meta``) and ``P`` ``(n, 54, 4)`` per-copy receiver
    probabilities (next, partner, previous, kitty).  States the file lacks get
    zero (uniform)."""
    with np.load(path) as z:
        ids, P = z["state"], z["P"]
    row_of = {int(s): i for i, s in enumerate(data["meta"][:, 0])}
    S, W = data["agreement"].shape
    out = np.zeros((S, W))
    for sid, p in zip(ids, P):
        i = row_of.get(int(sid))
        if i is not None:
            out[i] = marginal_log_weights(data["counts"][i], p)
    return out


# ------------------------------------------------------------------ CLI

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="world_weighting", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    c = sub.add_parser("collect", help="draw, score and store worlds on held-out states")
    c.add_argument("--store", action="append", required=True)
    c.add_argument("--out", required=True)
    c.add_argument("--package", required=True)
    c.add_argument("--sha256", required=True)
    c.add_argument("--worlds", type=int, default=512)
    c.add_argument("--cap", type=int, default=SERVED_CAP)
    c.add_argument("--rate", type=float, default=0.03, help="fraction of a test deal's decisions taken")
    c.add_argument("--states-per-task", type=int, default=40)
    c.add_argument("--tasks-per-store", type=int, default=3)
    c.add_argument("--clusters-per-task", type=int, default=400)
    c.add_argument("--cluster-offset", type=int, default=0)
    c.add_argument("--workers", type=int, default=4)
    c.add_argument("--no-events", action="store_true", help="worlds and agreement only")
    a = sub.add_parser("analyze", help="score the weighting variants")
    a.add_argument("--out", action="append", required=True)
    a.add_argument("--kitty-head", default=None, help="a kitty_inference checkpoint to add as weights")
    a.add_argument("--marginals", default=None,
                   help="per-state (54, 4) receiver marginals (npz: state, P) to add as weights")
    a.add_argument("--report", default=None)
    return ap


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "collect":
        m = collect(args.store, args.out, package=args.package, sha256=args.sha256,
                    worlds=args.worlds, cap=args.cap, rate=args.rate,
                    states_per_task=args.states_per_task, tasks_per_store=args.tasks_per_store,
                    clusters_per_task=args.clusters_per_task, cluster_offset=args.cluster_offset,
                    workers=args.workers, events=not args.no_events)
        print(json.dumps({"chunks": len(m["chunks"]),
                          "states": sum(c.get("states", 0) for c in m["chunks"])}))
        return 0
    if args.command == "analyze":
        extra = None
        data = load(args.out)
        if args.kitty_head:
            from . import kitty_inference
            extra = {"kitty": kitty_inference.world_log_weights(args.kitty_head, data)}
        if args.marginals:
            extra = dict(extra or {}, marginals=marginals_log_weights(args.marginals, data))
        rep = analyze(data, extra=extra)
        text = json.dumps(rep, indent=1)
        if args.report:
            Path(args.report).write_text(text)
        print(text)
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
