"""Serving-like candidate ranking for the complete-world value net.

``cwv_eval.rank_metrics`` over ``build_candidate_set`` (the trainer's
``rank_regret``) differs from what the served pv-search consumes in three
ways.  It keeps the first eligible search record of each shard in file
order, so at one record per deal it reads almost only trick-0 decisions.  It
scores each candidate's immediate afterstate, while the search scores the
leaf after the heuristic finishes the trick.  Its truth is the record's
search means, which on pv-search records are the producing model's own
sampled-world means.  This module measures the ranking the way serving
consumes it, on the same held-out deals, and leaves that metric unchanged:

* Records: per deal and trick bucket (``TRICK_BUCKETS``: early tricks 0-4,
  mid 5-9, late 10+), the ``per_bucket`` eligible search records with the
  smallest ``sha256(seed|source_ref)``.  Eligible means a play decision with
  an outcome and at least two finite search means that rebuilds to the
  acting seat's turn.  Metrics are reported per bucket and bucket-balanced
  (each bucket weighs one third).
* Scoring: every ballot candidate with a finite search mean is played in
  the record's TRUE world, canonicalised as the serving sampler
  canonicalises its worlds (sorted hands and burial).  The heuristic
  finisher then completes the current trick: ``cwv_policy.afterstate(...,
  finish_trick=True)``, the leaf ``PolicyValueSearch._leaf`` scores.  The
  leaf is encoded with the static encoder; a leaf that ends the round takes
  its exact level, as the serving evaluator does.
* Truth: each leaf is continued to the end of the round on the true world
  by the same heuristic (``MCBot._rollout``'s estimand with the true world
  in place of sampled worlds; no exact-endgame solver), and the outcome is
  read on the signed-level scale.  This truth never involves a value net or
  a world sampler.  The record's own search means are scored beside it as
  ``served_search_regret`` for comparison; on pv-search records they are
  the producing model's own means, so they are never the selection key.

Limits: the truth is the value of a candidate under heuristic play by all
four seats, not under the served policy.  The candidates are the stored
ballot (the searched ones), not every legal action.  The scored world is the
true one, so the metric isolates the leaf and the record choice from the
world sampler; the sampler's own bias is not part of it.
"""

from __future__ import annotations

import hashlib
import json
import math
import multiprocessing
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Sequence

import numpy as np

from ..ai.cwv_policy import afterstate, default_finisher
from ..ai.cwv_static_encoding import tensors_from_round_static
from ..engine.legal import IllegalPlay
from ..harvest.rebuild import RebuildError, state_for_record
from ..rl.encode import N_CARDS
from ..rl.encode_versions import ENC_VERSION
from ..rl.value_afterstate import (
    WORLD_RECEIVERS,
    category_signed_level,
    signed_level_category,
)
from ..rl.value_afterstate_v2 import public_dim
from .cwv_data import cwv_encoder_identity, deal_key, iter_records, search_means, value_units
from .cwv_eval import UNITS_CODE, UNITS_NAME, CandidateSet, EvalError

SERVED_SET_SCHEMA = "shengji-cwv-served-candidate-set-v1"
#: ``(name, first trick, last trick or None)``; tricks are 0-based.  Rounds in
#: the corpus end between tricks 12 and 23, so every bucket is populated in
#: almost every deal.
TRICK_BUCKETS = (("early", 0, 4), ("mid", 5, 9), ("late", 10, None))
BUCKET_NAMES = tuple(name for name, _lo, _hi in TRICK_BUCKETS)
DEFAULT_PER_BUCKET = 1
SERVED_DEFINITION = (
    "served_rank_regret = per record, T_best - mean T over the net's tied argmax, where the net "
    "scores each stored ballot candidate (finite search mean) at its served leaf: the candidate "
    "played in the record's TRUE world and the current trick finished by the heuristic "
    "(cwv_policy.afterstate finish_trick=True, the leaf PolicyValueSearch scores), and T is the "
    "signed level for the acting team of that leaf continued to round end by the same heuristic "
    "on the true world.  Records: per deal and trick bucket (early 0-4, mid 5-9, late 10+), the "
    "per_bucket eligible records with the smallest sha256(seed|source_ref).  The headline is "
    "bucket-balanced (mean of the bucket means).  served_rank_regret_points is the same regret in "
    "the acting team's rollout points.  served_search_regret is the same argmax "
    "scored against the record's recorded search means (RANK_SCALE), reported, never selected.")
_FINISHER_SOURCES = ("ai/heuristic.py", "ai/cwv_policy.py")


def trick_bucket(trick: int) -> str:
    """The ``TRICK_BUCKETS`` name of a 0-based trick index."""
    if isinstance(trick, bool) or not isinstance(trick, (int, np.integer)) or int(trick) < 0:
        raise EvalError(f"trick must be a non-negative integer, got {trick!r}")
    t = int(trick)
    for name, lo, hi in TRICK_BUCKETS:
        if t >= lo and (hi is None or t <= hi):
            return name
    raise EvalError(f"trick {t} falls in no bucket")  # pragma: no cover - buckets cover [0, inf)


def record_rank(seed: int, source_ref: str) -> str:
    """The order in which a deal's eligible records are tried in a bucket."""
    return hashlib.sha256(f"{int(seed)}|{source_ref}".encode("utf-8")).hexdigest()


def served_deals(keys, n: int, seed: int) -> list[str]:
    """The ``n`` deals of ``keys`` with the smallest ``sha256(seed|deal|key)``
    (all of them when ``n`` is at least their number, none when ``n <= 0``)."""
    if int(n) <= 0:
        return []
    ordered = sorted({str(k) for k in keys},
                     key=lambda k: (hashlib.sha256(f"{int(seed)}|deal|{k}".encode("utf-8"))
                                    .hexdigest(), k))
    return ordered[:int(n)]


def level_of_points(points: int, root_is_attacker: bool) -> float:
    """Exact signed level of final attacker ``points`` for the acting team."""
    return float(category_signed_level(signed_level_category(int(points), bool(root_is_attacker))))


def true_world(rnd) -> tuple[list[list[str]], list[str]]:
    """The round's own hands and burial in the serving sampler's canonical
    form (``sample_worlds``: every hand sorted, the burial sorted)."""
    return [sorted(hand) for hand in rnd.hands], sorted(rnd.buried)


def finisher_identity() -> dict:
    """sha256 of the sources whose behaviour the leaf and the rollout read."""
    root = Path(__file__).resolve().parents[1]
    return {name: hashlib.sha256((root / name).read_bytes()).hexdigest()
            for name in _FINISHER_SOURCES}


def score_served_candidates(rnd, seat: int, candidates: Sequence[Sequence[str]], *,
                            version: int = ENC_VERSION, finisher=None) -> dict:
    """Every candidate's served leaf in ``rnd``'s true world, encoded from
    ``seat``, plus its true-world heuristic continuation to round end.
    ``rnd`` is never mutated (each candidate plays on a fresh clone)."""
    policy = default_finisher() if finisher is None else finisher
    k = len(candidates)
    public = np.zeros((k, public_dim(version)), dtype=np.float32)
    world = np.zeros((k, WORLD_RECEIVERS, N_CARDS), dtype=np.uint8)
    perspective = np.zeros(k, dtype=np.uint8)
    terminal = np.zeros(k, dtype=bool)
    terminal_level = np.zeros(k, dtype=np.float64)
    rollout_points = np.zeros(k, dtype=np.int16)
    rollout_level = np.zeros(k, dtype=np.float64)
    root_is_attacker = bool(rnd.is_attacker(seat))
    hands, buried = true_world(rnd)
    for i, candidate in enumerate(candidates):
        leaf = afterstate(rnd, seat, hands, buried, list(candidate), finish_trick=True,
                          policy=policy)
        perspective[i] = 1 if root_is_attacker else 0
        if leaf.phase == "round_end":
            terminal[i] = True
            terminal_level[i] = level_of_points(leaf.attacker_points, root_is_attacker)
        else:
            tensors = tensors_from_round_static(leaf, seat, version=version)
            public[i] = tensors.public
            world[i] = np.rint(tensors.world * 2.0).astype(np.uint8)
        # The leaf is a private clone (afterstate copies hands, burial, trick and
        # history exactly as MCBot._rollout does), so playing it out is safe.
        while leaf.phase == "play":
            s = leaf.turn
            leaf.play(s, policy.decide_play(leaf, s))
        if leaf.phase != "round_end":
            raise EvalError(f"rollout stopped in phase {leaf.phase!r}")
        rollout_points[i] = int(leaf.attacker_points)
        rollout_level[i] = level_of_points(leaf.attacker_points, root_is_attacker)
    return {"public": public, "world": world, "perspective": perspective, "terminal": terminal,
            "terminal_level": terminal_level, "rollout_points": rollout_points,
            "rollout_level": rollout_level, "role_attacker": root_is_attacker}


_SKIPPABLE = (RebuildError, IllegalPlay, ValueError, KeyError, AssertionError, TypeError)


def _served_task(task: tuple) -> dict:
    """Pool worker: the served records of one shard among the selected deals.
    Returns ``{"entries": [...], "counts": {...}}``; the entries are ordered by
    deal key, bucket and record rank."""
    shard, selected, per_bucket, seed, version = task
    keep = None if selected is None else set(selected)
    pools: dict[tuple[str, str], list[tuple[str, dict]]] = {}
    counts = {"eligible": 0, "rebuild_failed": 0, "turn_mismatch": 0, "play_failed": 0,
              "kept": 0}
    for record in iter_records(shard):
        if record.get("decision_kind") != "play" or record.get("outcome") is None:
            continue
        if search_means(record) is None:
            continue
        deck = record.get("deck")
        trick = record.get("trick")
        if not isinstance(deck, list) or isinstance(trick, bool) or not isinstance(trick, int):
            continue
        key = deal_key(list(deck))
        if keep is not None and key not in keep:
            continue
        counts["eligible"] += 1
        bucket = trick_bucket(trick)
        pools.setdefault((key, bucket), []).append(
            (record_rank(seed, str(record["source_ref"])), record))
    entries: list[dict] = []
    order = {name: i for i, name in enumerate(BUCKET_NAMES)}
    for key, bucket in sorted(pools, key=lambda kb: (kb[0], order[kb[1]])):
        taken = 0
        for _rank, record in sorted(pools[(key, bucket)], key=lambda x: x[0]):
            if taken >= per_bucket:
                break
            seat = int(record["seat"])
            try:
                rnd = state_for_record(record)
            except (RebuildError, ValueError, KeyError, AssertionError, TypeError):
                counts["rebuild_failed"] += 1
                continue
            if rnd.phase != "play" or rnd.turn != seat:
                counts["turn_mismatch"] += 1
                continue
            indices, values = search_means(record)
            try:
                scored = score_served_candidates(
                    rnd, seat, [record["ballot"][i] for i in indices], version=version)
            except _SKIPPABLE:
                counts["play_failed"] += 1
                continue
            scored["means"] = np.asarray(values, dtype=np.float64)
            scored["units_code"] = UNITS_CODE[value_units(record)]
            scored["source_ref"] = str(record["source_ref"])
            scored["deal_key"] = key
            scored["trick"] = int(record["trick"])
            entries.append(scored)
            taken += 1
            counts["kept"] += 1
    return {"entries": entries, "counts": counts}


def _ordered_map(fn: Callable, tasks: Sequence[tuple], *, workers: int) -> Iterator[Any]:
    """``fn`` over ``tasks`` in task order, ``workers`` spawned processes."""
    if workers <= 1 or len(tasks) <= 1:
        for task in tasks:
            yield fn(task)
        return
    ctx = multiprocessing.get_context("spawn")
    with ctx.Pool(processes=min(workers, len(tasks))) as pool:
        yield from pool.imap(fn, tasks, chunksize=4)


@dataclass
class ServedCandidateSet:
    """Served-leaf candidate tensors (``cands``, whose ``means`` are the
    records' search means) plus, per record, its trick and, per candidate,
    the true-world heuristic continuation's points and level."""

    cands: CandidateSet
    trick: np.ndarray             # [records] int16
    rollout_points: np.ndarray    # [candidates] int16
    rollout_level: np.ndarray     # [candidates] float64

    @property
    def meta(self) -> dict:
        return self.cands.meta

    @property
    def records(self) -> int:
        return self.cands.records

    @property
    def candidates(self) -> int:
        return self.cands.candidates

    def buckets(self) -> np.ndarray:
        return np.asarray([trick_bucket(int(t)) for t in self.trick], dtype=object)

    @classmethod
    def concatenate(cls, entries: Sequence[Mapping[str, Any]], meta: Mapping[str, Any]
                    ) -> "ServedCandidateSet":
        cands = CandidateSet.concatenate(entries, meta, history=False)

        def cat(name, dtype):
            if entries:
                return np.concatenate([np.asarray(e[name], dtype=dtype) for e in entries])
            return np.zeros(0, dtype=dtype)

        return cls(cands=cands,
                   trick=np.asarray([int(e["trick"]) for e in entries], dtype=np.int16),
                   rollout_points=cat("rollout_points", np.int16),
                   rollout_level=cat("rollout_level", np.float64))

    def save(self, path: str | os.PathLike) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        arrays = {name: getattr(self.cands, name) for name in CandidateSet.ARRAYS}
        arrays.update(trick=self.trick, rollout_points=self.rollout_points,
                      rollout_level=self.rollout_level)
        tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        with open(tmp, "wb") as fh:
            np.savez_compressed(fh, meta=np.asarray(json.dumps(self.meta, sort_keys=True)),
                                **arrays)
        os.replace(tmp, path)

    @classmethod
    def load(cls, path: str | os.PathLike) -> "ServedCandidateSet":
        with np.load(path, allow_pickle=False) as npz:
            meta = json.loads(str(npz["meta"]))
            if meta.get("schema") != SERVED_SET_SCHEMA:
                raise EvalError(f"{path}: served candidate set schema {meta.get('schema')!r}")
            arrays = {name: npz[name] for name in CandidateSet.ARRAYS}
            extra = {name: npz[name] for name in ("trick", "rollout_points", "rollout_level")}
        return cls(cands=CandidateSet(meta=meta, **arrays), **extra)


def served_set_digest(shard_keys: Sequence[tuple[Any, Sequence[str] | None]], *,
                      per_bucket: int, seed: int, version: int = ENC_VERSION) -> str:
    """Identity of a served set: schema, encoder, buckets, record rule, the
    finisher's sources and the (shard, selected deals) list in order."""
    h = hashlib.sha256()
    h.update(json.dumps({
        "schema": SERVED_SET_SCHEMA,
        "encoder": cwv_encoder_identity(version)["implementation_sha256"],
        "enc_version": int(version), "buckets": [list(b) for b in TRICK_BUCKETS],
        "per_bucket": int(per_bucket), "seed": int(seed), "finisher": finisher_identity(),
        "shards": [[shard.sha256, None if keys is None else sorted(keys)]
                   for shard, keys in shard_keys],
    }, sort_keys=True).encode("ascii"))
    return h.hexdigest()


def build_served_set(shard_keys: Sequence[tuple[Any, Sequence[str] | None]], *,
                     per_bucket: int = DEFAULT_PER_BUCKET, seed: int = 0, workers: int = 1,
                     label: str = "", progress: Callable[[str], None] | None = None,
                     version: int = ENC_VERSION) -> ServedCandidateSet:
    """The served records of every ``(shard, deal keys)`` (``None`` = every
    deal), in input order, so the set is a function of its digest."""
    if int(per_bucket) < 1:
        raise EvalError("per_bucket must be >= 1")
    started = time.perf_counter()
    tasks = [(shard, None if keys is None else list(keys), int(per_bucket), int(seed),
              int(version)) for shard, keys in shard_keys]
    entries: list[dict] = []
    counts: dict[str, int] = {}
    done = 0
    for result in _ordered_map(_served_task, tasks, workers=workers):
        done += 1
        entries.extend(result["entries"])
        for name, value in result["counts"].items():
            counts[name] = counts.get(name, 0) + int(value)
        if progress and (done % 500 == 0 or done == len(tasks)):
            progress(f"served set{(' ' + label) if label else ''}: {done}/{len(tasks)} shards, "
                     f"{len(entries)} records ({round(time.perf_counter() - started, 1)}s)")
    meta = {"schema": SERVED_SET_SCHEMA,
            "digest": served_set_digest(shard_keys, per_bucket=per_bucket, seed=seed,
                                        version=version),
            "encoder": cwv_encoder_identity(version), "enc_version": int(version),
            "per_bucket": int(per_bucket), "seed": int(seed),
            "buckets": [list(b) for b in TRICK_BUCKETS], "finisher": finisher_identity(),
            "shards": len(tasks), "counts": counts, "definition": SERVED_DEFINITION,
            "secs": round(time.perf_counter() - started, 3), "label": label}
    out = ServedCandidateSet.concatenate(entries, meta)
    out.meta["records"] = out.records
    out.meta["candidates"] = out.candidates
    return out


def ensure_served_set(shard_keys: Sequence[tuple[Any, Sequence[str] | None]],
                      cache_dir: str | os.PathLike | None, *,
                      per_bucket: int = DEFAULT_PER_BUCKET, seed: int = 0, workers: int = 1,
                      label: str = "", progress: Callable[[str], None] | None = None,
                      version: int = ENC_VERSION) -> ServedCandidateSet:
    """``build_served_set`` memoised in ``cache_dir`` by digest."""
    digest = served_set_digest(shard_keys, per_bucket=per_bucket, seed=seed, version=version)
    path = None if cache_dir is None else Path(cache_dir) / f"served-{digest[:24]}.npz"
    if path is not None and path.is_file():
        try:
            cached = ServedCandidateSet.load(path)
        except (EvalError, OSError, ValueError, KeyError):
            cached = None
        if cached is not None and cached.meta.get("digest") == digest:
            cached.meta["loaded_from"] = str(path)
            if progress:
                progress(f"served set{(' ' + label) if label else ''}: {cached.records} records / "
                         f"{cached.candidates} candidates from {path.name}")
            return cached
    built = build_served_set(shard_keys, per_bucket=per_bucket, seed=seed, workers=workers,
                             label=label, progress=progress, version=version)
    if path is not None:
        built.save(path)
        built.meta["saved_to"] = str(path)
    return built


# ----------------------------------------------------------------- metrics

def served_rank_rows(levels: np.ndarray, sset: ServedCandidateSet) -> dict[str, np.ndarray]:
    """Per-record arrays of the served ranking: ``regret`` / ``top1`` against
    the rollout truth (and ``regret_points`` in the acting team's rollout
    points, a finer scale), ``search_regret`` / ``search_top1`` against the
    recorded search means, the rollout ``spread`` (best minus worst level),
    plus ``bucket``, ``units_code`` and ``deal_key``."""
    levels = np.asarray(levels, dtype=np.float64)
    cands = sset.cands
    if levels.shape != (cands.candidates,):
        raise EvalError("candidate levels are misaligned with the served set")
    if not np.all(np.isfinite(levels)):
        raise EvalError("candidate levels must be finite")
    n = cands.records
    mean_level = cands.means_level() if n else np.zeros(0)
    out = {name: np.empty(n) for name in ("regret", "top1", "regret_points", "search_regret",
                                          "search_top1", "spread")}
    widths = np.diff(cands.offsets)
    sign = np.where(np.repeat(cands.role_attacker.astype(bool), widths), 1.0, -1.0)
    team_points = sign * sset.rollout_points.astype(np.float64)
    for r in range(n):
        lo, hi = int(cands.offsets[r]), int(cands.offsets[r + 1])
        s = levels[lo:hi]
        top = np.flatnonzero(s == s.max())
        t = sset.rollout_level[lo:hi]
        out["regret"][r] = t.max() - t[top].mean()
        out["top1"][r] = float((t == t.max())[top].mean())
        out["spread"][r] = t.max() - t.min()
        p = team_points[lo:hi]
        out["regret_points"][r] = p.max() - p[top].mean()
        ml = mean_level[lo:hi]
        m = cands.means[lo:hi]
        out["search_regret"][r] = ml.max() - ml[top].mean()
        out["search_top1"][r] = float((m == m.max())[top].mean())
    out["bucket"] = sset.buckets()
    out["units_code"] = cands.units_code.astype(int)
    out["deal_key"] = cands.deal_key.astype(str)
    return out


def _block(rows: Mapping[str, np.ndarray], mask: np.ndarray) -> dict:
    n = int(mask.sum())
    if not n:
        return {"records": 0, "regret": None, "top1": None, "regret_points": None,
                "search_regret": None,
                "search_top1": None, "informative": None}
    return {"records": n,
            "regret": float(rows["regret"][mask].mean()),
            "top1": float(rows["top1"][mask].mean()),
            "regret_points": float(rows["regret_points"][mask].mean()),
            "search_regret": float(rows["search_regret"][mask].mean()),
            "search_top1": float(rows["search_top1"][mask].mean()),
            "informative": float((rows["spread"][mask] > 0).mean())}


def _no_served() -> dict:
    out = {"served_rank_records": 0, "served_rank_candidates": 0, "served_rank_regret": None,
           "served_rank_top1": None, "served_rank_regret_points": None,
           "served_search_regret": None, "served_search_top1": None,
           "served_rank_regret_records_mean": None,
           "served_by_trick": {b: {"records": 0} for b in BUCKET_NAMES},
           "served_by_units": {}, "served_definition": SERVED_DEFINITION}
    for b in BUCKET_NAMES:
        out[f"served_rank_regret_{b}"] = None
    return out


def served_rank_metrics(levels: np.ndarray, sset: ServedCandidateSet | None) -> dict:
    """The served ranking block (``SERVED_DEFINITION``): bucket-balanced
    headline keys ``served_rank_regret`` / ``served_rank_top1`` (rollout
    truth, signed level), ``served_rank_regret_points`` (rollout truth in the
    acting team's points: one rollout is one outcome, and the level brackets
    leave most records without a spread, so points resolve more) and
    ``served_search_regret`` / ``served_search_top1`` (recorded search
    means), per bucket under ``served_by_trick`` and flat as
    ``served_rank_regret_<bucket>``, and per units family under
    ``served_by_units``."""
    if sset is None or sset.records == 0:
        return _no_served()
    rows = served_rank_rows(levels, sset)
    by_trick = {b: _block(rows, rows["bucket"] == b) for b in BUCKET_NAMES}
    present = [b for b in BUCKET_NAMES if by_trick[b]["records"]]

    def balanced(key):
        return float(np.mean([by_trick[b][key] for b in present]))

    out = {
        "served_rank_records": int(sset.records),
        "served_rank_candidates": int(sset.candidates),
        "served_rank_regret": balanced("regret"),
        "served_rank_top1": balanced("top1"),
        "served_rank_regret_points": balanced("regret_points"),
        "served_search_regret": balanced("search_regret"),
        "served_search_top1": balanced("search_top1"),
        "served_rank_regret_records_mean": float(rows["regret"].mean()),
        "served_by_trick": by_trick,
        "served_by_units": {UNITS_NAME[c]: _block(rows, rows["units_code"] == c)
                            for c in sorted(set(rows["units_code"].tolist()))},
        "served_buckets_present": present,
        "served_definition": SERVED_DEFINITION,
    }
    for b in BUCKET_NAMES:
        out[f"served_rank_regret_{b}"] = by_trick[b]["regret"]
    return out


def clustered_se(values: np.ndarray, clusters: np.ndarray) -> float:
    """Standard error of ``values.mean()`` with records clustered by deal."""
    values = np.asarray(values, dtype=np.float64)
    if values.size < 2:
        return math.nan
    centred = values - values.mean()
    _keys, inverse = np.unique(np.asarray(clusters, dtype=str), return_inverse=True)
    sums = np.bincount(inverse, weights=centred)
    return float(math.sqrt(float((sums ** 2).sum())) / values.size)


def balanced_with_se(values: np.ndarray, buckets: np.ndarray, clusters: np.ndarray
                     ) -> tuple[float, float]:
    """The bucket-balanced mean of ``values`` and its deal-clustered SE."""
    values = np.asarray(values, dtype=np.float64)
    present = [b for b in BUCKET_NAMES if (buckets == b).any()]
    if not present:
        return math.nan, math.nan
    influence = np.zeros_like(values)
    mean = 0.0
    for b in present:
        mask = buckets == b
        mu = float(values[mask].mean())
        mean += mu / len(present)
        influence[mask] = (values[mask] - mu) / (len(present) * int(mask.sum()))
    _keys, inverse = np.unique(np.asarray(clusters, dtype=str), return_inverse=True)
    sums = np.bincount(inverse, weights=influence)
    return mean, float(math.sqrt(float((sums ** 2).sum())))


__all__ = [
    "BUCKET_NAMES", "DEFAULT_PER_BUCKET", "SERVED_DEFINITION", "SERVED_SET_SCHEMA",
    "ServedCandidateSet", "TRICK_BUCKETS", "balanced_with_se", "build_served_set",
    "clustered_se", "ensure_served_set", "finisher_identity", "level_of_points",
    "record_rank", "score_served_candidates", "served_deals", "served_rank_metrics",
    "served_rank_rows", "served_set_digest", "trick_bucket", "true_world",
]
