"""Per-decision belief labels over hidden card copies.

For every play decision of a trajectory store, the acting seat's view becomes one
example:

* **inputs** -- only facts the actor holds at that moment (``belief_features``):
  the v4 observation (v1 public planes + own hand, the v2 trick/points/shape
  columns, the v4 opponent-pair block with the per-seat pair caps), then the
  belief-only blocks that no encoder version carries: the banker's own burial
  (actor-private), the declared cards and declarer, the cards ``Memory`` pins to a
  seat (declared cards plus the failed-throw pins `ai.refusal` derives), the
  attempted-but-unplayed cards of every failed throw on the record, the per-seat
  pair-run caps, the four hand sizes and the trick index.  Nothing reads another
  seat's hand or, for a non-banker, the burial.
* **labels** (``belief_labels``) -- for each of the 54 card codes, how many of its
  HIDDEN copies (``Memory(rnd, seat, own_kitty=True).unseen``) each receiver holds.
  Receivers are seat-relative: next (rel 1), partner (rel 2), previous (rel 3) and
  the kitty.  For the banker the kitty is its own burial, so it is not hidden: the
  kitty column is empty and masked.
* **mask** (``feasible_mask``) -- receivers a copy can be with on public facts:
  a seat with cards left that is not void in the card's effective suit, and the
  kitty only for a non-banker.  The true holder is always feasible (asserted).

The states are rebuilt by replaying each cluster's records IN ORDER from the
setup (``harvest.rebuild.round_from_setup``).  Each decision plays the record's
own ``action`` -- the ATTEMPTED cards -- so a failed throw is refused by the
engine again and posts the same public ``failed_throw`` notice it posted at the
table; the played result is checked against ``engine_play``/``action`` and
against the next record's prefix.  A `ai.refusal.RefusalLedger` observes every
decision state: in an all-bot table every play is a bot decision, so this is the
ledger a release-45 room bot holds (``SHENGJI_PV_REFUSAL_CONSTRAINTS=1``).

The **production-sampler baseline** (``sampler_counts``) draws M worlds per state
through the real path release 45 takes in ``PVSearchBot._worlds``:
``Memory(own_kitty=MCBot.BANKER_KITTY)``, then ``sample_worlds_refusal_aware``
when the ledger holds a refusal and ``cwv_policy.sample_worlds`` otherwise, and
counts where each hidden copy lands.

Layout witness: the gen5 policy-row extracts (``train/policy_prior.py``) carry the
true world at ``X[:, 561:831]`` -- five 54-wide seat-relative planes (rel 0..3 hands,
then the burial) at 0.5 per copy.  ``verify-extract`` replays deals of a store and
checks, row by row, that this block equals the world this module labels from and
that ``X[:, :561]`` equals the v2 public row it rebuilds.  The extract's block is
never an input.

Splits are by ``deal_key`` (mirrors share a deal, so they always share a split);
every deal whose round seed lies in a registered non-trajectory seed window
(screens, calibrations; ``shengji.seeds``) is excluded.

CLI: ``extract`` / ``verify-extract``; see ``build_parser``.  The evaluator is
``train/belief_eval.py``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

import numpy as np

from ..ai.memory import Memory
from ..ai.refusal import (Refusal, RefusalLedger, pin_unplayed_attempt, plays_since)
from ..engine.cards import SUITS, TRUMP
from ..harvest.rebuild import round_from_setup
from ..rl.encode import CARD_INDEX, N_CARDS
from ..rl.encode_versions import OBS_DIM_BY_VERSION, encode_obs
from .data import deal_key

SCHEMA = "shengji-belief-labels-v1"
SPLIT_SALT = "s17-belief-split-v1"
#: seat-relative receivers of a hidden copy
RECEIVERS = ("next", "partner", "prev", "kitty")
N_RECV = len(RECEIVERS)
KITTY = 3
_EFF = tuple(SUITS) + (TRUMP,)
#: phase buckets by 1-based trick number (design note (c) step 1)
PHASES = (("early", 1, 5), ("mid", 6, 15), ("late", 16, 10 ** 9))
#: actor roles
ROLES = ("banker", "banker_partner", "defender")
#: the base observation: encoder v4 (v1 + v2 columns + the opponent-pair block)
BASE_VERSION = 4
BASE_DIM = OBS_DIM_BY_VERSION[BASE_VERSION]           # 635
#: (name, width) of every input block, in order
FEATURE_BLOCKS: tuple[tuple[str, int], ...] = (
    ("obs_v4", BASE_DIM),
    ("own_kitty", N_CARDS),
    ("own_kitty_known", 1),
    ("declarer_rel", 4),
    ("declared_cards", N_CARDS),
    ("pinned_rel1", N_CARDS),
    ("pinned_rel2", N_CARDS),
    ("pinned_rel3", N_CARDS),
    ("throw_unplayed_rel1", N_CARDS),
    ("throw_unplayed_rel2", N_CARDS),
    ("throw_unplayed_rel3", N_CARDS),
    ("refusals_rel", 4),
    ("run_cap", 3 * len(_EFF) * 2),
    ("hand_sizes_rel", 4),
    ("trick_index", 1),
)
FEATURE_DIM = sum(width for _, width in FEATURE_BLOCKS)
#: the gen5 extract's world block: never an input here, only a layout witness
EXTRACT_WORLD = (561, 831)
EXTRACT_PUBLIC = (0, 561)


class BeliefLabelError(ValueError):
    """A record stream, state or label the extractor refuses."""


# ------------------------------------------------------------------ helpers

def _counts(cards: Iterable[str]) -> np.ndarray:
    out = np.zeros(N_CARDS, np.float32)
    for card in cards:
        out[CARD_INDEX[card]] += 1.0
    return out


def phase_of_trick(trick: int) -> str:
    for name, lo, hi in PHASES:
        if lo <= trick <= hi:
            return name
    raise BeliefLabelError(f"trick {trick} has no phase")


def role_of(rnd, seat: int) -> int:
    if rnd.banker == seat:
        return 0
    return 1 if (rnd.banker - seat) % 2 == 0 else 2


def split_fraction(key: str) -> float:
    """A deal's position in [0, 1) for the train/calib/test split (salted, so it is
    independent of every other split in the repo)."""
    return int(hashlib.sha256(f"{SPLIT_SALT}|{key}".encode()).hexdigest(), 16) / 16 ** 64


def split_of(key: str, calib: float, test: float) -> str:
    frac = split_fraction(key)
    if frac >= 1.0 - test:
        return "test"
    if frac >= 1.0 - test - calib:
        return "calib"
    return "train"


def excluded_windows(registry: Mapping[str, Any] | None = None) -> list[tuple[int, int, str]]:
    """Every registered window that is not a trajectory window (screens,
    calibrations, other): ``(lo, hi, name)``, half-open."""
    from .. import seeds
    reg = seeds.load() if registry is None else registry
    out = []
    for entry in reg.get("windows", []):
        if entry.get("purpose") != "trajectory":
            lo, hi = seeds.span_of(entry)
            out.append((int(lo), int(hi), str(entry.get("name"))))
    return out


def seed_excluded(seed: int | None, windows: Sequence[tuple[int, int, str]]) -> bool:
    if seed is None:
        return False
    return any(lo <= int(seed) < hi for lo, hi, _ in windows)


# ------------------------------------------------------------------ replay

@dataclass
class Decision:
    """One live decision state.  ``rnd`` is the replay's own Round and moves on
    when the iterator advances: use it before asking for the next decision."""
    record: Mapping[str, Any]
    rnd: Any
    seat: int
    refusals: tuple[Refusal, ...]
    round_index: int
    decision_index: int


def _played_cards(rnd, history_before: int) -> list[str]:
    """The cards the last accepted play put on the table."""
    if len(rnd.history) > history_before:
        return list(rnd.history[-1].plays[-1].cards)
    return list(rnd.trick.plays[-1].cards)


def _mirror_of(rec: Mapping[str, Any]) -> int:
    """The round (mirror) of a trajectory record: ``source_ref`` is
    ``run:cluster:mirror:seat:ply``."""
    ref = str(rec.get("source_ref") or "")
    parts = ref.split(":")
    if len(parts) < 5:
        raise BeliefLabelError(f"unparseable source_ref {ref!r}")
    if parts[-1] != str(len(rec.get("plays_prefix") or [])):
        raise BeliefLabelError(f"source_ref {ref!r} disagrees with the prefix length")
    return int(parts[-3])


def game_order(records: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """A cluster's play records in table order: by round (mirror), then ply.  A
    shard groups each round's records by seat, not by ply."""
    plays = [r for r in records if r.get("decision_kind") == "play"]
    return sorted(plays, key=lambda r: (_mirror_of(r), len(r.get("plays_prefix") or [])))


def iter_decisions(records: Iterable[Mapping[str, Any]], *, ordered: bool = False
                   ) -> Iterator[Decision]:
    """Replay a cluster's records in table order and yield every play decision.

    A record with an empty ``plays_prefix`` starts a round from its setup; every
    other record must continue the live round exactly (same prefix length, the
    previous play equal to the prefix's last entry).  ``ordered=True`` takes the
    records as already in table order (synthetic streams without a source_ref)."""
    rnd = None
    ledger = None
    played_n = 0
    last_play: dict | None = None
    round_index = -1
    decision_index = 0
    stream = ([r for r in records if r.get("decision_kind") == "play"] if ordered
              else game_order(records))
    for rec in stream:
        prefix = rec.get("plays_prefix") or []
        if not prefix:
            rnd = round_from_setup(rec["deck"], rec["setup"])
            ledger = RefusalLedger()
            played_n = 0
            last_play = None
            round_index += 1
        else:
            if rnd is None or len(prefix) != played_n:
                raise BeliefLabelError("records are not one ordered game: prefix length "
                                       f"{len(prefix)} after {played_n} replayed plays")
            tail = prefix[-1]
            if (last_play is None or int(tail["seat"]) != last_play["seat"]
                    or Counter(tail["cards"]) != Counter(last_play["cards"])):
                raise BeliefLabelError("the replayed play differs from the record's prefix")
        seat = int(rec["seat"])
        if rnd.phase != "play" or rnd.turn != seat:
            raise BeliefLabelError("the record's seat is not the replay's turn")
        refusals = tuple(ledger.observe(rnd))
        yield Decision(rec, rnd, seat, refusals, round_index, decision_index)
        decision_index += 1
        before = len(rnd.history)
        rnd.play(seat, list(rec["action"]))      # the ATTEMPTED cards: a failed throw re-posts its notice
        played = _played_cards(rnd, before)
        expected = rec.get("engine_play") or rec["action"]
        if Counter(played) != Counter(expected):
            raise BeliefLabelError("the engine's play differs from the record's engine_play")
        last_play = {"seat": seat, "cards": played}
        played_n += 1


# ------------------------------------------------------------------ inputs

def actor_memory(rnd, seat: int, refusals: Sequence[Refusal]) -> Memory:
    """The actor's own memory (own burial known) with the failed-throw pins the
    sampler applies (`ai.refusal.pin_unplayed_attempt`)."""
    mem = Memory(rnd, seat, own_kitty=True)
    for refusal in refusals:
        pin_unplayed_attempt(mem, rnd, refusal, seat)
    return mem


def belief_features(rnd, seat: int, refusals: Sequence[Refusal] = (),
                    mem: Memory | None = None) -> np.ndarray:
    """The actor-visible input row (``FEATURE_BLOCKS`` order, ``FEATURE_DIM`` wide)."""
    if mem is None:
        mem = actor_memory(rnd, seat, refusals)
    blocks: list[np.ndarray] = [np.asarray(encode_obs(rnd, seat, version=BASE_VERSION), np.float32)]
    # the banker's own burial: actor-private, zero for everyone else
    if mem.own_kitty_known:
        blocks += [_counts(rnd.buried), np.ones(1, np.float32)]
    else:
        blocks += [np.zeros(N_CARDS, np.float32), np.zeros(1, np.float32)]
    decl = rnd.declaration
    declarer = np.zeros(4, np.float32)
    declared = np.zeros(N_CARDS, np.float32)
    if decl is not None and decl.get("seat") is not None:
        declarer[(int(decl["seat"]) - seat) % 4] = 1.0
        declared = _counts(decl["cards"])
    blocks += [declarer, declared]
    pinned = np.zeros((3, N_CARDS), np.float32)
    for code, (holder, copies) in mem.known.items():
        rel = (holder - seat) % 4
        if rel:
            pinned[rel - 1, CARD_INDEX[code]] += float(copies)
    blocks += list(pinned)
    unplayed = np.zeros((3, N_CARDS), np.float32)
    n_refusals = np.zeros(4, np.float32)
    for refusal in refusals:
        rel = (refusal.seat - seat) % 4
        n_refusals[rel] += 1.0
        if not rel:
            continue
        since = plays_since(rnd, refusal.trick_index)[refusal.seat]
        for code, held in Counter(refusal.attempted).items():
            left = held - since[code]
            if left > 0:
                unplayed[rel - 1, CARD_INDEX[code]] = max(unplayed[rel - 1, CARD_INDEX[code]], left)
    blocks += list(unplayed)
    blocks.append(np.minimum(n_refusals, 4.0) / 4.0)
    run_cap = []
    for rel in (1, 2, 3):
        s = (seat + rel) % 4
        for eff in _EFF:
            cap = mem.run_cap[s].get(eff)
            run_cap += [0.0, 0.0] if cap is None else [1.0, min(cap, 12) / 12.0]
    blocks.append(np.asarray(run_cap, np.float32))
    blocks.append(np.asarray([len(rnd.hands[(seat + rel) % 4]) / 25.0 for rel in range(4)],
                             np.float32))
    blocks.append(np.asarray([(len(rnd.history) + 1) / 25.0], np.float32))
    x = np.concatenate(blocks)
    if x.shape != (FEATURE_DIM,):
        raise BeliefLabelError(f"feature width {x.shape[0]} != {FEATURE_DIM}")
    return x


# ------------------------------------------------------------------ labels

def hidden_counts(mem: Memory) -> np.ndarray:
    """Hidden copies per code from the actor's view (own burial known)."""
    out = np.zeros(N_CARDS, np.int64)
    for code, n in mem.unseen.items():
        out[CARD_INDEX[code]] = n
    return out


def belief_labels(rnd, seat: int, mem: Memory | None = None) -> np.ndarray:
    """``(54, 4)`` uint8: hidden copies of each code held by next / partner /
    previous / the kitty.  Reads the TRUE hands; never an input."""
    if mem is None:
        mem = Memory(rnd, seat, own_kitty=True)
    y = np.zeros((N_CARDS, N_RECV), np.int64)
    for rel in (1, 2, 3):
        for card in rnd.hands[(seat + rel) % 4]:
            y[CARD_INDEX[card], rel - 1] += 1
    if not mem.own_kitty_known:
        for card in rnd.buried:
            y[CARD_INDEX[card], KITTY] += 1
    if not np.array_equal(y.sum(axis=1), hidden_counts(mem)):
        raise BeliefLabelError("labels do not account for exactly the hidden copies")
    return y.astype(np.uint8)


def feasible_mask(rnd, seat: int, mem: Memory) -> np.ndarray:
    """``(54, 4)`` bool: receivers a hidden copy can be with on public facts."""
    o = rnd.ordering
    eff = [None] * N_CARDS
    for code, idx in CARD_INDEX.items():
        eff[idx] = o.eff_suit(code)
    m = np.zeros((N_CARDS, N_RECV), bool)
    for rel in (1, 2, 3):
        s = (seat + rel) % 4
        if not rnd.hands[s]:
            continue
        voids = mem.voids[s]
        m[:, rel - 1] = [e not in voids for e in eff]
    m[:, KITTY] = not mem.own_kitty_known
    m &= (hidden_counts(mem) > 0)[:, None]
    return m


def receiver_sizes(rnd, seat: int, mem: Memory) -> np.ndarray:
    """Cards each receiver holds (public: hand sizes; the kitty is 8 unless known)."""
    sizes = [len(rnd.hands[(seat + rel) % 4]) for rel in (1, 2, 3)]
    sizes.append(0 if mem.own_kitty_known else len(rnd.buried))
    return np.asarray(sizes, np.int16)


def world_block(rnd, seat: int) -> np.ndarray:
    """The gen5 extract's world layout (5 x 54 at 0.5 per copy: rel 0..3 hands,
    then the burial), rebuilt from the true deal -- for the layout witness only."""
    w = np.zeros((5, N_CARDS), np.float32)
    for rel in range(4):
        for card in rnd.hands[(seat + rel) % 4]:
            w[rel, CARD_INDEX[card]] += 0.5
    for card in rnd.buried:
        w[4, CARD_INDEX[card]] += 0.5
    return w


# ------------------------------------------------------------------ sampler baseline

def sampler_counts(rnd, seat: int, refusals: Sequence[Refusal], n: int, seed: int
                   ) -> tuple[np.ndarray, int, dict]:
    """``(counts (54, 4) uint16, worlds, stats)``: where production's sampler puts
    each hidden copy over ``n`` worlds, through release 45's own branch
    (`PVSearchBot._worlds`: refusal-aware when the ledger holds a refusal)."""
    from ..ai.cwv_policy import sample_worlds
    from ..ai.mcbot import MCBot
    from ..ai.refusal import sample_worlds_refusal_aware
    bot = MCBot(seed=seed)
    mem = Memory(rnd, seat, own_kitty=getattr(bot, "BANKER_KITTY", True))
    stats: dict = {}
    if refusals:
        worlds, attempts, stats = sample_worlds_refusal_aware(bot, rnd, seat, n, list(refusals),
                                                              mem=mem)
    else:
        worlds, attempts = sample_worlds(bot, rnd, seat, n, mem=mem)
    stats = dict(stats, attempts=int(attempts))
    counts = np.zeros((N_CARDS, N_RECV), np.int64)
    kitty_hidden = not mem.own_kitty_known
    for hands, buried in worlds:
        for rel in (1, 2, 3):
            for card in hands[(seat + rel) % 4]:
                counts[CARD_INDEX[card], rel - 1] += 1
        if kitty_hidden:
            for card in buried:
                counts[CARD_INDEX[card], KITTY] += 1
    if worlds and not np.array_equal(counts.sum(axis=1), hidden_counts(mem) * len(worlds)):
        raise BeliefLabelError("sampled worlds do not place exactly the hidden copies")
    return counts.astype(np.uint16), len(worlds), stats


# ------------------------------------------------------------------ extraction

def cluster_paths(store: str | os.PathLike) -> list[Path]:
    shards = Path(store) / "shards"
    paths = sorted(shards.glob("cluster-*.jsonl"))
    if not paths:
        raise BeliefLabelError(f"no cluster shards under {shards}")
    return paths


def _read_records(path: Path) -> list[dict]:
    with open(path) as fh:
        return [json.loads(line) for line in fh if line.strip()]


def extract_cluster(path: Path, *, store_index: int, cluster_index: int, calib: float,
                    test: float, windows: Sequence[tuple[int, int, str]],
                    sampler_worlds: int, sampler_splits: Sequence[str],
                    sampler_stride: int = 1) -> dict | None:
    """All decisions of one cluster as arrays, or None when its deal is excluded."""
    records = _read_records(path)
    plays = [r for r in records if r.get("decision_kind") == "play"]
    if not plays:
        return None
    seeds_ = {r.get("round_seed") for r in plays}
    if any(seed_excluded(s, windows) for s in seeds_):
        return {"excluded": True, "path": str(path)}
    key = deal_key(list(plays[0]["deck"]))
    if any(deal_key(list(r["deck"])) != key for r in plays):
        raise BeliefLabelError(f"{path}: a cluster must be one deal")
    split = split_of(key, calib, test)
    deal_hash = np.uint64(int(hashlib.sha256(key.encode()).hexdigest()[:16], 16))
    xs, ys, ms, sizes, meta, samp, samp_n = [], [], [], [], [], [], []
    stats = Counter()
    for d in iter_decisions(plays):
        rnd, seat = d.rnd, d.seat
        mem = actor_memory(rnd, seat, d.refusals)
        x = belief_features(rnd, seat, d.refusals, mem=mem)
        y = belief_labels(rnd, seat, mem=mem)
        m = feasible_mask(rnd, seat, mem)
        if np.any((y > 0) & ~m):
            raise BeliefLabelError(f"{path}: a true holder is outside the feasible mask")
        trick = len(rnd.history) + 1
        xs.append(x.astype(np.float16))
        ys.append(y)
        ms.append(m)
        sizes.append(receiver_sizes(rnd, seat, mem))
        meta.append((trick, role_of(rnd, seat), len(d.refusals), d.round_index,
                     d.decision_index, int(d.record.get("round_seed") or -1)))
        stats["refusal_states"] += bool(d.refusals)
        if split in sampler_splits and sampler_worlds and d.decision_index % sampler_stride == 0:
            seed = int(hashlib.sha256(f"{key}|{d.decision_index}".encode()).hexdigest()[:8], 16)
            c, n, st = sampler_counts(rnd, seat, d.refusals, sampler_worlds, seed)
            samp.append(c)
            samp_n.append(n)
            stats["sampler_states"] += 1
            stats["refusal_rejections"] += int(st.get("refusal_rejections", 0))
            stats["refusal_fallback_worlds"] += int(st.get("refusal_fallback_worlds", 0))
        else:
            samp.append(np.zeros((N_CARDS, N_RECV), np.uint16))
            samp_n.append(0)
    meta_a = np.asarray(meta, np.int64)
    n = len(xs)
    return {
        "excluded": False, "path": str(path), "split": split, "deal_key": key,
        "X": np.stack(xs), "Y": np.stack(ys), "M": np.stack(ms), "sizes": np.stack(sizes),
        "trick": meta_a[:, 0].astype(np.int16), "role": meta_a[:, 1].astype(np.int8),
        "n_refusals": meta_a[:, 2].astype(np.int16), "round_index": meta_a[:, 3].astype(np.int8),
        "decision": meta_a[:, 4].astype(np.int16), "seed": meta_a[:, 5],
        "deal": np.full(n, deal_hash, np.uint64), "store": np.full(n, store_index, np.int16),
        "cluster": np.full(n, cluster_index, np.int32),
        "S": np.stack(samp), "S_n": np.asarray(samp_n, np.int16),
        "stats": dict(stats),
    }


ARRAY_KEYS = ("X", "Y", "M", "sizes", "trick", "role", "n_refusals", "round_index",
              "decision", "seed", "deal", "store", "cluster", "S", "S_n")


def _extract_task(args: tuple) -> dict:
    (paths, store_indices, cluster_indices, out_dir, chunk_name, calib, test, windows,
     sampler_worlds, sampler_splits, sampler_stride) = args
    t0 = time.time()
    per_split: dict[str, list[dict]] = {"train": [], "calib": [], "test": []}
    stats = Counter()
    excluded = []
    failed = []
    for path, si, ci in zip(paths, store_indices, cluster_indices):
        try:
            got = extract_cluster(Path(path), store_index=si, cluster_index=ci, calib=calib,
                                  test=test, windows=windows, sampler_worlds=sampler_worlds,
                                  sampler_splits=sampler_splits, sampler_stride=sampler_stride)
        except BeliefLabelError as exc:      # counted and reported, never silently dropped
            failed.append({"path": str(path), "error": str(exc)})
            continue
        if got is None:
            continue
        if got["excluded"]:
            excluded.append(got["path"])
            continue
        per_split[got["split"]].append(got)
        stats.update(got["stats"])
        stats[f"deals_{got['split']}"] += 1
    files = {}
    for split, parts in per_split.items():
        if not parts:
            continue
        arrays = {k: np.concatenate([p[k] for p in parts]) for k in ARRAY_KEYS}
        name = f"{split}-{chunk_name}.npz"
        np.savez(Path(out_dir) / name, **arrays)
        files[split] = {"file": name, "rows": int(arrays["X"].shape[0]), "deals": len(parts),
                        "sha256": hashlib.sha256((Path(out_dir) / name).read_bytes()).hexdigest()}
    return {"chunk": chunk_name, "files": files, "stats": dict(stats), "excluded": excluded,
            "failed": failed, "seconds": time.time() - t0}


def extract(stores: Sequence[str], out: str, *, cluster_stride: int, cluster_offset: int,
            max_clusters_per_store: int | None, calib: float, test: float,
            sampler_worlds: int, sampler_splits: Sequence[str], sampler_stride: int,
            workers: int, task_clusters: int, log=print) -> dict:
    out_dir = Path(out)
    out_dir.mkdir(parents=True, exist_ok=False)
    windows = excluded_windows()
    tasks = []
    for si, store in enumerate(stores):
        paths = cluster_paths(store)
        chosen = [(ci, p) for ci, p in enumerate(paths) if ci % cluster_stride == cluster_offset]
        if max_clusters_per_store is not None:
            chosen = chosen[:max_clusters_per_store]
        for start in range(0, len(chosen), task_clusters):
            group = chosen[start:start + task_clusters]
            tasks.append(([str(p) for _, p in group], [si] * len(group), [ci for ci, _ in group],
                          str(out_dir), f"s{si:02d}-{start // task_clusters:05d}", calib, test,
                          windows, sampler_worlds, tuple(sampler_splits), sampler_stride))
    manifest: dict[str, Any] = {
        "schema": SCHEMA, "feature_dim": FEATURE_DIM, "feature_blocks": FEATURE_BLOCKS,
        "receivers": RECEIVERS, "phases": PHASES, "roles": ROLES,
        "stores": list(stores), "cluster_stride": cluster_stride, "cluster_offset": cluster_offset,
        "max_clusters_per_store": max_clusters_per_store, "split": {"salt": SPLIT_SALT,
                                                                    "calib": calib, "test": test},
        "excluded_windows": windows, "sampler": {"worlds": sampler_worlds,
                                                  "splits": list(sampler_splits),
                                                  "stride": sampler_stride,
                                                  "path": "PVSearchBot._worlds branch: "
                                                          "sample_worlds_refusal_aware | sample_worlds"},
        "chunks": [], "stats": {}, "excluded_clusters": [], "failed_clusters": [],
    }
    stats = Counter()
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for i, res in enumerate(pool.map(_extract_task, tasks)):
            manifest["chunks"].append(res)
            manifest["excluded_clusters"] += res["excluded"]
            manifest["failed_clusters"] += res["failed"]
            stats.update(res["stats"])
            if (i + 1) % 10 == 0 or i + 1 == len(tasks):
                log(f"[extract] {i + 1}/{len(tasks)} tasks, {time.time() - t0:.0f}s, {dict(stats)}",
                    flush=True)
    manifest["stats"] = dict(stats)
    manifest["seconds"] = time.time() - t0
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=1, default=list))
    return manifest


def load_split(out: str | os.PathLike, split: str, keys: Sequence[str] = ARRAY_KEYS
               ) -> dict[str, np.ndarray]:
    """Concatenate one split of an extract, verifying each chunk's sha256."""
    out_dir = Path(out)
    manifest = json.loads((out_dir / "manifest.json").read_text())
    if manifest.get("schema") != SCHEMA:
        raise BeliefLabelError("not a belief-label extract")
    entries = [c["files"][split] for c in manifest["chunks"] if split in c["files"]]
    total = sum(int(e["rows"]) for e in entries)
    if not total:
        raise BeliefLabelError(f"split {split} is empty")
    out: dict[str, np.ndarray] = {}
    at = 0
    for entry in entries:                    # preallocated: one copy of the split in memory
        path = out_dir / entry["file"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
            raise BeliefLabelError(f"{path}: sha256 mismatch")
        with np.load(path) as z:
            n = int(entry["rows"])
            for k in keys:
                a = z[k]
                if k not in out:
                    out[k] = np.empty((total, *a.shape[1:]), a.dtype)
                out[k][at:at + n] = a
            at += n
    return out


# ------------------------------------------------------------------ layout witness

def verify_extract(store: str, extract_dir: str, *, chunks: int, max_deals: int, log=print) -> dict:
    """Replay deals of ``store`` that the gen5 extract ``extract_dir`` holds and
    compare, row by row, the extract's world block ``X[:, 561:831]`` with
    ``world_block`` and its public block ``X[:, :561]`` with the rebuilt v2 row."""
    from .policy_prior import flat_input, root_tensors
    rows_by_key: dict[str, list[np.ndarray]] = {}
    ext = Path(extract_dir)
    manifest = json.loads((ext / "manifest.json").read_text())
    for chunk in manifest["chunks"][:chunks]:
        with np.load(ext / chunk["file"]) as z:
            X, keys = z["X"], z["deal_key"]
            for i, k in enumerate(keys):
                rows_by_key.setdefault(str(k), []).append(X[i])
    report = Counter()
    worst_public = 0.0
    for path in cluster_paths(store):
        if report["deals"] >= max_deals:
            break
        plays = [r for r in _read_records(path) if r.get("decision_kind") == "play"]
        if not plays:
            continue
        key = deal_key(list(plays[0]["deck"]))
        want = rows_by_key.get(key)
        if want is None:
            report["deals_not_in_extract"] += 1
            continue
        by_record = {}
        for d in iter_decisions(plays):
            by_record[id(d.record)] = (world_block(d.rnd, d.seat).ravel(),
                                       flat_input(root_tensors(d.rnd, d.seat, 2), 2)[:561])
            # the label this module derives must be the same world, restricted to hidden copies
            mem = Memory(d.rnd, d.seat, own_kitty=True)
            y = belief_labels(d.rnd, d.seat, mem)
            w = world_block(d.rnd, d.seat)
            kitty = w[4] * 2 if not mem.own_kitty_known else np.zeros(N_CARDS)
            if not np.array_equal(y.astype(np.float32), np.stack([w[1] * 2, w[2] * 2, w[3] * 2, kitty], 1)):
                report["label_world_mismatch"] += 1
        got = [by_record[id(r)] for r in plays]          # the extract keeps the shard's order
        if len(got) != len(want):
            report["row_count_mismatch"] += 1
            continue
        for (wb, pub), xrow in zip(got, want):
            xw = np.asarray(xrow[EXTRACT_WORLD[0]:EXTRACT_WORLD[1]], np.float32)
            report["rows"] += 1
            if not np.array_equal(xw, wb):
                report["world_mismatch_rows"] += 1
            diff = float(np.max(np.abs(np.asarray(xrow[:561], np.float32) - pub)))
            worst_public = max(worst_public, diff)
            if diff > 1e-2:
                report["public_mismatch_rows"] += 1
        report["deals"] += 1
    out = dict(report, worst_public_abs_diff=worst_public)
    log(json.dumps(out))
    return out


# ------------------------------------------------------------------ CLI

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="belief_labels", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    ex = sub.add_parser("extract", help="replay stores into belief examples")
    ex.add_argument("--store", action="append", required=True)
    ex.add_argument("--out", required=True)
    ex.add_argument("--cluster-stride", type=int, default=1)
    ex.add_argument("--cluster-offset", type=int, default=0)
    ex.add_argument("--max-clusters-per-store", type=int, default=None)
    ex.add_argument("--calib", type=float, default=0.06)
    ex.add_argument("--test", type=float, default=0.12)
    ex.add_argument("--sampler-worlds", type=int, default=256)
    ex.add_argument("--sampler-splits", default="calib,test")
    ex.add_argument("--sampler-stride", type=int, default=1,
                    help="draw sampler worlds on every Nth decision of an eval deal")
    ex.add_argument("--workers", type=int, default=2)
    ex.add_argument("--task-clusters", type=int, default=40)
    vx = sub.add_parser("verify-extract", help="check the gen5 extract layout against replay")
    vx.add_argument("--store", required=True)
    vx.add_argument("--extract", required=True)
    vx.add_argument("--chunks", type=int, default=2)
    vx.add_argument("--max-deals", type=int, default=20)
    return ap


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "extract":
        m = extract(args.store, args.out, cluster_stride=args.cluster_stride,
                    cluster_offset=args.cluster_offset,
                    max_clusters_per_store=args.max_clusters_per_store, calib=args.calib,
                    test=args.test, sampler_worlds=args.sampler_worlds,
                    sampler_splits=[s for s in args.sampler_splits.split(",") if s],
                    sampler_stride=args.sampler_stride, workers=args.workers,
                    task_clusters=args.task_clusters)
        print(json.dumps({"stats": m["stats"], "seconds": m["seconds"],
                          "excluded_clusters": len(m["excluded_clusters"]),
                          "failed_clusters": len(m["failed_clusters"])}))
        return 0
    if args.command == "verify-extract":
        r = verify_extract(args.store, args.extract, chunks=args.chunks, max_deals=args.max_deals)
        bad = (r.get("world_mismatch_rows", 0) or r.get("public_mismatch_rows", 0)
               or r.get("row_count_mismatch", 0) or r.get("label_world_mismatch", 0)
               or not r.get("rows"))
        return 1 if bad else 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
