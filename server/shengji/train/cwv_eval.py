"""Evaluation helpers for the complete-world value net.

* ``load_public_head`` -- the #213 value/prior checkpoint (``train_v0``
  schemas v2 and v3) whose decision-state value is the PUBLIC baseline: it
  sees the acting seat's hand and the public state only.
* ``candidate_agreement`` -- the bar that matters for search: for a record
  with per-candidate search means, every candidate is applied in the
  record's TRUE world, the reached states are scored from the acting seat's
  perspective and the ranking is compared with the search's means
  (Spearman over average ranks, top-1 agreement with uniform tie-breaking,
  and the regret in search points of the scorer's top pick).
* ``candidate_pass`` -- one parallel pass over the records of a split: the
  decision-state observation for the public head on every row, and the
  candidate afterstates (public / world / perspective [/ history] tensors,
  exact terminal values) for the rows that carry search means; the parent
  process runs the nets and the prior on what the workers return.
"""

from __future__ import annotations

import math
import multiprocessing
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Sequence

import numpy as np
import torch

from ..harvest.rebuild import RebuildError, state_for_record
from ..rl.douzero_micro import HISTORY_EVENT_DIM
from ..rl.encode import ENCODER_IMPLEMENTATION_SHA256, N_CARDS, OBS_DIM, encode_obs
from ..rl.value_afterstate import (
    PERSPECTIVE_DIM,
    PUBLIC_DIM,
    WORLD_RECEIVERS,
    ValueAfterstateError,
    apply_action,
    category_signed_level,
    signed_level_category,
    tensors_from_round,
)
from .baselines import StratifiedPrior, cluster_bootstrap
from .cwv_data import (
    HISTORY_META_DIM,
    compact_history,
    deal_key,
    expand_history,
    iter_records,
    pt0_level,
    search_means,
)
from .model import ValuePriorNet

PUBLIC_CHECKPOINT_PREFIX = "shengji-train-v0-checkpoint-v"
SCORERS = ("cwv", "public_head", "stratified_prior")


class EvalError(RuntimeError):
    """The evaluation cannot be carried out as specified."""


# ------------------------------------------------------------ public head

def load_public_head(path: str, device: torch.device | str = "cpu") -> tuple[ValuePriorNet, dict]:
    """A #213 checkpoint (v2 without persisted populations, or v3) whose
    encoder is this build's; returns ``(model, info)``."""
    try:
        payload = torch.load(Path(path), map_location="cpu", weights_only=False)
    except Exception as exc:
        raise EvalError(f"{path}: public head checkpoint is unreadable: {exc}") from exc
    schema = payload.get("schema") if isinstance(payload, dict) else None
    if not isinstance(schema, str) or not schema.startswith(PUBLIC_CHECKPOINT_PREFIX):
        raise EvalError(f"{path}: not a {PUBLIC_CHECKPOINT_PREFIX}* checkpoint ({schema!r})")
    enc = payload.get("encoder") or {}
    if enc.get("implementation_sha256") != ENCODER_IMPLEMENTATION_SHA256:
        raise EvalError(f"{path}: public head encoder "
                        f"{str(enc.get('implementation_sha256', ''))[:12]} differs from this "
                        f"build's {ENCODER_IMPLEMENTATION_SHA256[:12]}")
    try:
        model = ValuePriorNet(payload["arch"])
        model.load_state_dict(payload["model_state"])
    except (KeyError, RuntimeError, TypeError, ValueError) as exc:
        raise EvalError(f"{path}: public head model state drift: {exc}") from exc
    model.to(device)
    model.eval()
    config = payload.get("config") or {}
    split = payload.get("split") or {}
    population = payload.get("population")
    info = {
        "path": str(Path(path).resolve()),
        "schema": schema,
        "arch": payload.get("arch"),
        "epoch": payload.get("epoch"),
        "encoder_sha256": enc.get("implementation_sha256"),
        "seed": config.get("seed"),
        "limit_clusters": config.get("limit_clusters"),
        "val_fraction": config.get("val_fraction"),
        "test_fraction": config.get("test_fraction"),
        "split_method": config.get("split_method"),
        "data": config.get("data"),
        "split": {k: v for k, v in split.items() if k != "roles"},
        "has_population": population is not None,
        "population": population,
        "test_metrics": ((payload.get("metrics") or {}).get("test") or {}).get("value"),
    }
    return model, info


@torch.no_grad()
def public_values(model: ValuePriorNet, obs: np.ndarray, device: torch.device | str = "cpu",
                  *, batch_size: int = 4096) -> np.ndarray:
    """The public head's value (PT0 signed level for the acting seat's team)
    per observation row (the prior head gets one masked dummy candidate)."""
    obs = np.asarray(obs, dtype=np.float32)
    if obs.ndim != 2 or obs.shape[1] != OBS_DIM:
        raise EvalError("public head observations must be [n, OBS_DIM]")
    model.eval()
    out = []
    act_dim = int(model.arch["act_dim"])
    for b0 in range(0, obs.shape[0], batch_size):
        chunk = torch.from_numpy(np.ascontiguousarray(obs[b0:b0 + batch_size])).to(device)
        cand = torch.zeros((chunk.shape[0], 1, act_dim), dtype=torch.float32, device=device)
        mask = torch.ones((chunk.shape[0], 1), dtype=torch.bool, device=device)
        value = model(chunk, cand, mask).value
        out.append(value.detach().cpu().numpy().astype(np.float64))
    return np.concatenate(out) if out else np.zeros(0, dtype=np.float64)


# -------------------------------------------------------------- agreement

def average_ranks(values: Sequence[float]) -> np.ndarray:
    x = np.asarray(values, dtype=np.float64)
    order = np.argsort(x, kind="stable")
    ranks = np.empty(x.size, dtype=np.float64)
    sorted_x = x[order]
    i = 0
    while i < x.size:
        j = i
        while j + 1 < x.size and sorted_x[j + 1] == sorted_x[i]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2.0 + 1.0
        i = j + 1
    return ranks


def spearman(a: Sequence[float], b: Sequence[float]) -> float | None:
    """Spearman correlation over average ranks; None when either side is
    constant (no ranking information)."""
    ra, rb = average_ranks(a), average_ranks(b)
    if ra.size < 2 or float(ra.std()) == 0.0 or float(rb.std()) == 0.0:
        return None
    return float(np.corrcoef(ra, rb)[0, 1])


def candidate_agreement(scores: Sequence[float], means: Sequence[float]) -> dict:
    """How a scorer's candidate values agree with the search's means.

    ``spearman`` is None when the scorer (or the search) ties every
    candidate; ``top1`` is the probability that the scorer's top pick (a
    uniform draw among its tied maxima) is one of the search's argmax
    candidates; ``regret`` is the search mean of the search's best minus
    the expected search mean of the scorer's top pick (points, >= 0)."""
    s = np.asarray(scores, dtype=np.float64)
    m = np.asarray(means, dtype=np.float64)
    if s.shape != m.shape or s.ndim != 1 or s.size < 2 \
            or not np.all(np.isfinite(s)) or not np.all(np.isfinite(m)):
        raise EvalError("agreement needs >= 2 finite scores aligned with the search means")
    best_search = m == m.max()
    top = np.flatnonzero(s == s.max())
    return {
        "spearman": spearman(s, m),
        "top1": float(best_search[top].mean()),
        "regret": float(m.max() - m[top].mean()),
        "candidates": int(s.size),
    }


def summarize_agreement(rows: Sequence[Mapping[str, Any]], clusters: Sequence[str], *,
                        n_boot: int, seed: int) -> dict:
    """Mean Spearman (over the records where it is defined), top-1 and
    regret with deal-cluster bootstrap CIs."""
    if not rows:
        return {"n": 0}
    clusters = np.asarray(clusters, dtype=str)
    spear = np.asarray([math.nan if r["spearman"] is None else r["spearman"] for r in rows],
                       dtype=np.float64)
    defined = np.isfinite(spear)
    top1 = np.asarray([r["top1"] for r in rows], dtype=np.float64)
    regret = np.asarray([r["regret"] for r in rows], dtype=np.float64)
    return {
        "n": int(len(rows)),
        "spearman": (cluster_bootstrap(spear[defined], clusters[defined], n_boot=n_boot,
                                       seed=seed) if defined.any() else None),
        "spearman_defined": int(defined.sum()),
        "spearman_undefined_scorer_ties": int((~defined).sum()),
        "top1": cluster_bootstrap(top1, clusters, n_boot=n_boot, seed=seed + 1),
        "regret_points": cluster_bootstrap(regret, clusters, n_boot=n_boot, seed=seed + 2),
    }


def paired_agreement(rows_a: Sequence[Mapping[str, Any]], rows_b: Sequence[Mapping[str, Any]],
                     clusters: Sequence[str], *, n_boot: int, seed: int) -> dict:
    """Paired per-record differences (a minus b) of top-1 and regret."""
    if not rows_a:
        return {"n": 0}
    clusters = np.asarray(clusters, dtype=str)
    top = np.asarray([a["top1"] - b["top1"] for a, b in zip(rows_a, rows_b)], dtype=np.float64)
    regret = np.asarray([a["regret"] - b["regret"] for a, b in zip(rows_a, rows_b)],
                        dtype=np.float64)
    return {"top1": cluster_bootstrap(top, clusters, n_boot=n_boot, seed=seed + 3),
            "regret_points": cluster_bootstrap(regret, clusters, n_boot=n_boot, seed=seed + 4)}


# ---------------------------------------------------------- candidate pass

@dataclass
class ShardResult:
    label: str
    source_ref: list[str]
    deal_key: list[str]
    decision_obs: np.ndarray          # [n, OBS_DIM] float32
    search: list[dict]                # one entry per record with search means


def score_candidates(rnd, seat: int, candidates: Sequence[Sequence[str]], *,
                     history: bool = False) -> dict:
    """Apply every candidate in ``rnd`` (the TRUE world) and encode the
    reached states from ``seat``'s perspective; terminal successors carry
    their exact value instead of tensors (the nets never see them)."""
    k = len(candidates)
    public = np.zeros((k, PUBLIC_DIM), dtype=np.float32)
    world = np.zeros((k, WORLD_RECEIVERS, N_CARDS), dtype=np.uint8)
    perspective = np.zeros(k, dtype=np.uint8)
    terminal = np.zeros(k, dtype=bool)
    terminal_level = np.zeros(k, dtype=np.float64)
    successor_points = np.zeros(k, dtype=np.float32)
    successor_ply = np.zeros(k, dtype=np.int32)
    hist_cards: list[np.ndarray] = []
    hist_meta: list[np.ndarray] = []
    lengths = np.zeros(k, dtype=np.int64)
    root_is_attacker = bool(rnd.is_attacker(seat))
    plies = sum(len(t.plays) for t in rnd.history) + (len(rnd.trick.plays) if rnd.trick else 0)
    for i, candidate in enumerate(candidates):
        successor, _accepted = apply_action(rnd, seat, list(candidate))
        successor_points[i] = float(successor.attacker_points)
        successor_ply[i] = plies + 1
        perspective[i] = 1 if root_is_attacker else 0
        if successor.phase == "round_end":
            terminal[i] = True
            terminal_level[i] = category_signed_level(
                signed_level_category(int(successor.attacker_points), root_is_attacker))
            if history:
                hist_cards.append(np.zeros((0, N_CARDS), np.uint8))
                hist_meta.append(np.zeros((0, HISTORY_META_DIM), np.uint8))
            continue
        tensors = tensors_from_round(successor, seat)
        public[i] = tensors.public
        world[i] = np.rint(tensors.world * 2.0).astype(np.uint8)
        if history:
            cards, meta = compact_history(tensors.history)
            hist_cards.append(cards)
            hist_meta.append(meta)
            lengths[i] = cards.shape[0]
    out = {"public": public, "world": world, "perspective": perspective, "terminal": terminal,
           "terminal_level": terminal_level, "successor_points": successor_points,
           "successor_ply": successor_ply, "role_attacker": root_is_attacker}
    if history:
        offsets = np.zeros(k + 1, dtype=np.int64)
        offsets[1:] = np.cumsum(lengths)
        out["history_cards"] = (np.concatenate(hist_cards) if hist_cards
                                else np.zeros((0, N_CARDS), np.uint8))
        out["history_meta"] = (np.concatenate(hist_meta) if hist_meta
                               else np.zeros((0, HISTORY_META_DIM), np.uint8))
        out["history_offsets"] = offsets
    return out


def _candidate_task(task: tuple) -> ShardResult:
    """Pool worker: rebuild the selected records of one shard."""
    shard, selected, want_search, per_shard_limit, history = task
    keep = None if selected is None else set(selected)
    refs: list[str] = []
    keys: list[str] = []
    obs: list[np.ndarray] = []
    search: list[dict] = []
    for record in iter_records(shard):
        if record.get("decision_kind") != "play" or record.get("outcome") is None:
            continue
        deck = record.get("deck")
        if not isinstance(deck, list):
            continue
        key = deal_key(list(deck))
        if keep is not None and key not in keep:
            continue
        seat = int(record["seat"])
        try:
            rnd = state_for_record(record)
        except (RebuildError, ValueError, KeyError, AssertionError, TypeError):
            continue
        if rnd.phase != "play" or rnd.turn != seat:
            continue
        refs.append(str(record["source_ref"]))
        keys.append(key)
        obs.append(np.asarray(encode_obs(rnd, seat), dtype=np.float32))
        means = search_means(record)
        if not want_search or means is None or len(search) >= per_shard_limit:
            continue
        indices, values = means
        try:
            scored = score_candidates(rnd, seat, [record["ballot"][i] for i in indices],
                                      history=history)
        except ValueAfterstateError:
            continue
        scored["means"] = np.asarray(values, dtype=np.float64)
        scored["source_ref"] = str(record["source_ref"])
        scored["deal_key"] = key
        search.append(scored)
    decision = np.stack(obs) if obs else np.zeros((0, OBS_DIM), np.float32)
    return ShardResult(label=shard.label, source_ref=refs, deal_key=keys,
                       decision_obs=decision, search=search)


def iter_shard_results(tasks: Sequence[tuple], *, workers: int) -> Iterator[ShardResult]:
    """``ShardResult`` per task (completion order), ``workers`` processes."""
    if workers <= 1 or len(tasks) <= 1:
        for task in tasks:
            yield _candidate_task(task)
        return
    ctx = multiprocessing.get_context("spawn")
    with ctx.Pool(processes=min(workers, len(tasks))) as pool:
        yield from pool.imap_unordered(_candidate_task, tasks)


def candidate_pass(shard_keys: Sequence[tuple[Any, Sequence[str] | None]], *,
                   score_fn: Callable[[dict], np.ndarray] | None,
                   public_head: ValuePriorNet | None, prior: StratifiedPrior | None,
                   device: torch.device | str, workers: int, rank_limit: int | None,
                   history: bool, want_search: bool = True,
                   progress: Callable[[str], None] | None = None) -> dict:
    """Run the workers over ``shard_keys`` (``(shard, selected deal keys or
    None)``) and score what they return.

    ``score_fn(candidates) -> expected PT0 level per candidate`` is the CWV
    net (None skips it); the public head scores the afterstate's public
    slice; the prior reads the afterstate's ply, role and points.  Returns
    the public head's decision-state value per ``source_ref`` and the
    ranking agreement rows per scorer (with the record's deal key)."""
    tasks = []
    per_shard = None
    if rank_limit is not None:
        per_shard = max(1, math.ceil(int(rank_limit) / max(1, len(shard_keys))))
    for shard, keys in shard_keys:
        tasks.append((shard, None if keys is None else list(keys), bool(want_search),
                      per_shard if per_shard is not None else 1 << 30, bool(history)))
    started = time.perf_counter()
    decision_values: dict[str, float] = {}
    decision_keys: dict[str, str] = {}
    agreement: dict[str, list[dict]] = {name: [] for name in SCORERS}
    clusters: list[str] = []
    n_rows = 0
    n_candidates = 0
    widths: list[int] = []
    done = 0
    for result in iter_shard_results(tasks, workers=workers):
        done += 1
        n_rows += len(result.source_ref)
        for ref, key in zip(result.source_ref, result.deal_key):
            decision_keys[ref] = key
        if public_head is not None and result.decision_obs.shape[0]:
            values = public_values(public_head, result.decision_obs, device)
            for ref, value in zip(result.source_ref, values.tolist()):
                decision_values[ref] = float(value)
        for entry in result.search:
            k = int(entry["means"].size)
            n_candidates += k
            widths.append(k)
            clusters.append(entry["deal_key"])
            terminal = entry["terminal"]
            if score_fn is not None:
                scores = np.asarray(score_fn(entry), dtype=np.float64)
                scores = np.where(terminal, np.asarray([pt0_level(v) if t else 0.0
                                                        for v, t in zip(entry["terminal_level"],
                                                                        terminal)]), scores)
                agreement["cwv"].append(candidate_agreement(scores, entry["means"]))
            if public_head is not None:
                values = public_values(public_head, entry["public"][:, :OBS_DIM], device)
                values = np.where(terminal, np.asarray([pt0_level(v) if t else 0.0
                                                        for v, t in zip(entry["terminal_level"],
                                                                        terminal)]), values)
                agreement["public_head"].append(candidate_agreement(values, entry["means"]))
            if prior is not None:
                role = np.full(k, bool(entry["role_attacker"]))
                values = prior.predict(entry["successor_ply"], role, entry["successor_points"])
                values = np.where(terminal, np.asarray([pt0_level(v) if t else 0.0
                                                        for v, t in zip(entry["terminal_level"],
                                                                        terminal)]), values)
                agreement["stratified_prior"].append(candidate_agreement(values, entry["means"]))
        if progress and (done % 200 == 0 or done == len(tasks)):
            progress(f"candidate pass: {done}/{len(tasks)} shards, rows={n_rows} "
                     f"search_records={len(clusters)} candidates={n_candidates} "
                     f"({round(time.perf_counter() - started, 1)}s)")
    return {
        "rows": n_rows,
        "search_records": len(clusters),
        "candidates": n_candidates,
        "candidates_per_record": (float(np.mean(widths)) if widths else None),
        "decision_values": decision_values,
        "decision_keys": decision_keys,
        "agreement": {name: rows for name, rows in agreement.items() if rows},
        "clusters": clusters,
        "secs": round(time.perf_counter() - started, 3),
        "rank_limit": rank_limit,
        "per_shard_limit": per_shard,
    }


def candidate_tensors(entry: Mapping[str, np.ndarray], device: torch.device | str) -> dict:
    """The #214 batch tensors of one search record's candidate afterstates
    (terminal rows carry zeros; the caller substitutes their exact value)."""
    k = int(entry["public"].shape[0])
    perspective = np.zeros((k, PERSPECTIVE_DIM), dtype=np.float32)
    attacker = entry["perspective"].astype(bool)
    perspective[attacker, 0] = 1.0
    perspective[~attacker, 1] = 1.0
    if "history_offsets" in entry:
        offsets = entry["history_offsets"]
        lengths = offsets[1:] - offsets[:-1]
        length = max(int(lengths.max()) if k else 1, 1)
        history = np.zeros((k, length, HISTORY_EVENT_DIM), dtype=np.float32)
        mask = np.zeros((k, length), dtype=bool)
        events = expand_history(entry["history_cards"], entry["history_meta"])
        for i in range(k):
            n = int(lengths[i])
            history[i, :n] = events[offsets[i]:offsets[i] + n]
            mask[i, :n] = True
        mask[lengths == 0, 0] = True          # terminal rows: one padding event
    else:
        history = np.zeros((k, 1, HISTORY_EVENT_DIM), dtype=np.float32)
        mask = np.ones((k, 1), dtype=bool)
    return {
        "public": torch.from_numpy(np.ascontiguousarray(entry["public"])).to(device),
        "world": torch.from_numpy(np.ascontiguousarray(entry["world"])).to(device)
        .to(torch.float32) * 0.5,
        "perspective": torch.from_numpy(perspective).to(device),
        "history": torch.from_numpy(history).to(device),
        "history_mask": torch.from_numpy(mask).to(device),
    }


__all__ = [
    "EvalError", "SCORERS", "ShardResult", "candidate_agreement", "candidate_pass",
    "candidate_tensors", "iter_shard_results", "load_public_head", "paired_agreement",
    "public_values", "score_candidates", "spearman", "summarize_agreement",
]
