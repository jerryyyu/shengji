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
    cwv_encoder_identity,
    deal_key,
    expand_history,
    expected_levels,
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


# ------------------------------------------------- search-facing metrics
#
# Jerry's rule: the training validation metric, the held-out model eval and
# what the search consumes are the SAME quantity computed by the SAME code.
# ``search_facing_metrics`` is that code; ``train_cwv`` calls it from the
# per-epoch validation, from the final val/test pass and from ``evaluate``.

CANDIDATE_SET_SCHEMA = "shengji-cwv-candidate-set-v1"
SEARCH_MEANS_SCALE = ("acting-team-signed final attacker points averaged over the search's "
                      "worlds (MCBot mc-s0-report-lcb; sign flipped for a defender)")
RANK_SCALE = ("#214 half-integer signed level (category_signed_level) for the acting seat's "
              "team: the scale the search's leaf consumes (cwv_policy / cwv_puct score "
              "positions by probabilities @ category_signed_level support)")
RANK_REGRET_DEFINITION = (
    "rank_regret = U(E[points])_best - U(E[points])_pick: the level-bracket transform "
    "(level_of_search_mean) of the search's MEAN points per candidate, an MC-ranking proxy "
    "-- NOT E[U] (the mean of per-world levels, which the records do not carry); "
    "rank_regret_points is the untransformed mean-points regret")
#: which search designs consume which head, and on which positions
CONSUMERS = {
    "level_head": {
        "quantity": "expected signed level (probabilities @ category_signed_level support)",
        "consumed_by": ["one-ply (ai.cwv_policy CompleteWorldEvaluator)",
                        "shortlist (train.cwv_shortlist)", "netroll (train.net_rollout)",
                        "PUCT prior / leaf (ai.cwv_puct)"],
        "positions": "every ballot candidate's afterstate (sampled worlds; the metric "
                     "scores the TRUE world), ranked among the decision's candidates",
        "metrics": ["rank_regret (level scale; U(E[points]), an MC-ranking proxy, not E[U])",
                    "rank_regret_points", "rank_top1",
                    "cross_entropy", "value_mae (PT0)", "value_level_mae"],
        "recommended_select_metric": "val_rank_regret",
    },
    "points_head": {
        "quantity": "final attacker points (aux head on the mlp trunk, target points / 100)",
        "consumed_by": ["vleaf leaf (train.leaf_policy CompleteWorldPointsHead)"],
        "positions": "one heuristic trick past a candidate (the leaf's finished afterstate); "
                     "the metric scores the record's own afterstate rows",
        "metrics": ["points_mae", "points_bias (pred - real)", "points_below_banked"],
        "recommended_select_metric": "val_points_mae",
    },
}


def level_of_search_mean(mean: float, root_is_attacker: bool) -> float:
    """The signed level of one search mean (``SEARCH_MEANS_SCALE``): the
    mean's attacker points rounded to the integer bracket
    ``signed_level_category`` maps, from the acting team's perspective."""
    points = float(mean) if root_is_attacker else -float(mean)
    points = int(min(max(round(points), 0), 4_120))
    return category_signed_level(signed_level_category(points, bool(root_is_attacker)))


@dataclass
class CandidateSet:
    """The candidate afterstates of the search records of one split, flat:
    record ``r`` owns candidate rows ``offsets[r]:offsets[r + 1]``.  Built
    once (``build_candidate_set``), persisted next to the row cache, and
    scored by one batched forward per epoch."""

    public: np.ndarray            # [n, PUBLIC_DIM] float32
    world: np.ndarray             # [n, WORLD_RECEIVERS, N_CARDS] uint8
    perspective: np.ndarray       # [n] uint8 (1 = the acting seat attacks)
    terminal: np.ndarray          # [n] bool
    terminal_level: np.ndarray    # [n] float64 exact level of a terminal candidate
    means: np.ndarray             # [n] float64 search means (SEARCH_MEANS_SCALE)
    offsets: np.ndarray           # [records + 1] int64
    deal_key: np.ndarray          # [records] str
    role_attacker: np.ndarray     # [records] bool
    source_ref: np.ndarray        # [records] str
    meta: dict
    history_cards: np.ndarray | None = None
    history_meta: np.ndarray | None = None
    history_offsets: np.ndarray | None = None   # [n + 1]

    ARRAYS = ("public", "world", "perspective", "terminal", "terminal_level", "means",
              "offsets", "deal_key", "role_attacker", "source_ref")
    HISTORY_ARRAYS = ("history_cards", "history_meta", "history_offsets")

    @property
    def records(self) -> int:
        return int(self.offsets.size - 1)

    @property
    def candidates(self) -> int:
        return int(self.public.shape[0])

    @property
    def history(self) -> bool:
        return self.history_offsets is not None

    def means_level(self) -> np.ndarray:
        """Every candidate's search mean on the level scale (``RANK_SCALE``)."""
        widths = np.diff(self.offsets)
        attacker = np.repeat(self.role_attacker.astype(bool), widths)
        return np.asarray([level_of_search_mean(m, bool(a))
                           for m, a in zip(self.means.tolist(), attacker.tolist())],
                          dtype=np.float64)

    def batch_entry(self, lo: int, hi: int) -> dict:
        """Rows ``lo:hi`` as a ``candidate_tensors`` entry."""
        entry = {"public": self.public[lo:hi], "world": self.world[lo:hi],
                 "perspective": self.perspective[lo:hi]}
        if self.history:
            assert self.history_offsets is not None
            o = self.history_offsets[lo:hi + 1]
            entry["history_offsets"] = o - o[0]
            entry["history_cards"] = self.history_cards[o[0]:o[-1]]
            entry["history_meta"] = self.history_meta[o[0]:o[-1]]
        return entry

    def save(self, path: str | os.PathLike) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        arrays = {name: getattr(self, name) for name in self.ARRAYS}
        if self.history:
            arrays.update({name: getattr(self, name) for name in self.HISTORY_ARRAYS})
        tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        with open(tmp, "wb") as fh:
            np.savez_compressed(fh, meta=np.asarray(json.dumps(self.meta, sort_keys=True)),
                                **arrays)
        os.replace(tmp, path)

    @classmethod
    def load(cls, path: str | os.PathLike) -> "CandidateSet":
        with np.load(path, allow_pickle=False) as npz:
            meta = json.loads(str(npz["meta"]))
            if meta.get("schema") != CANDIDATE_SET_SCHEMA:
                raise EvalError(f"{path}: candidate set schema {meta.get('schema')!r}")
            arrays = {name: npz[name] for name in cls.ARRAYS}
            if "history_offsets" in npz.files:
                arrays.update({name: npz[name] for name in cls.HISTORY_ARRAYS})
        return cls(meta=meta, **arrays)

    @classmethod
    def empty(cls, meta: Mapping[str, Any], *, history: bool = False) -> "CandidateSet":
        return cls.concatenate([], meta, history=history)

    @classmethod
    def concatenate(cls, entries: Sequence[Mapping[str, Any]], meta: Mapping[str, Any], *,
                    history: bool) -> "CandidateSet":
        """One set from ``score_candidates`` entries (each with ``means``,
        ``deal_key``, ``source_ref``), in the given order."""
        widths = np.asarray([int(e["means"].size) for e in entries], dtype=np.int64)
        offsets = np.zeros(len(entries) + 1, dtype=np.int64)
        offsets[1:] = np.cumsum(widths)

        def cat(name, dtype, shape):
            if entries:
                return np.concatenate([np.asarray(e[name], dtype=dtype) for e in entries])
            return np.zeros((0, *shape), dtype=dtype)

        out = cls(
            public=cat("public", np.float32, (PUBLIC_DIM,)),
            world=cat("world", np.uint8, (WORLD_RECEIVERS, N_CARDS)),
            perspective=cat("perspective", np.uint8, ()),
            terminal=cat("terminal", bool, ()),
            terminal_level=cat("terminal_level", np.float64, ()),
            means=cat("means", np.float64, ()),
            offsets=offsets,
            deal_key=np.asarray([e["deal_key"] for e in entries], dtype=str),
            role_attacker=np.asarray([bool(e["role_attacker"]) for e in entries], dtype=bool),
            source_ref=np.asarray([e["source_ref"] for e in entries], dtype=str),
            meta=dict(meta))
        if history:
            lengths = [np.diff(e["history_offsets"]) for e in entries]
            h_off = np.zeros(int(offsets[-1]) + 1, dtype=np.int64)
            if entries:
                h_off[1:] = np.cumsum(np.concatenate(lengths))
            out.history_offsets = h_off
            out.history_cards = cat("history_cards", np.uint8, (N_CARDS,))
            out.history_meta = cat("history_meta", np.uint8, (HISTORY_META_DIM,))
        return out


def _candidate_set_task(task: tuple) -> list[dict]:
    """Pool worker: the first ``limit`` search records of one shard among
    the selected deals, every candidate applied in the TRUE world."""
    shard, selected, limit, history = task
    keep = None if selected is None else set(selected)
    entries: list[dict] = []
    for record in iter_records(shard):
        if len(entries) >= limit:
            break
        if record.get("decision_kind") != "play" or record.get("outcome") is None:
            continue
        means = search_means(record)
        if means is None:
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
        indices, values = means
        try:
            scored = score_candidates(rnd, seat, [record["ballot"][i] for i in indices],
                                      history=history)
        except ValueAfterstateError:
            continue
        scored["means"] = np.asarray(values, dtype=np.float64)
        scored["source_ref"] = str(record["source_ref"])
        scored["deal_key"] = key
        entries.append(scored)
    return entries


def _pool_map(fn: Callable, tasks: Sequence[tuple], *, workers: int) -> Iterator[Any]:
    if workers <= 1 or len(tasks) <= 1:
        for task in tasks:
            yield fn(task)
        return
    ctx = multiprocessing.get_context("spawn")
    with ctx.Pool(processes=min(workers, len(tasks))) as pool:
        yield from pool.imap_unordered(fn, tasks)


def candidate_set_digest(shard_keys: Sequence[tuple[Any, Sequence[str] | None]], *,
                         per_shard_limit: int, history: bool) -> str:
    """Identity of a candidate set: encoder, flavour, per-shard cap and the
    (shard, selected deals) list in order."""
    h = hashlib.sha256()
    h.update(json.dumps({
        "schema": CANDIDATE_SET_SCHEMA,
        "encoder": cwv_encoder_identity()["implementation_sha256"],
        "history": bool(history), "per_shard_limit": int(per_shard_limit),
        "shards": [[shard.sha256, None if keys is None else sorted(keys)]
                   for shard, keys in shard_keys],
    }, sort_keys=True).encode("ascii"))
    return h.hexdigest()


def build_candidate_set(shard_keys: Sequence[tuple[Any, Sequence[str] | None]], *,
                        per_shard_limit: int, history: bool, workers: int,
                        label: str = "", progress: Callable[[str], None] | None = None
                        ) -> CandidateSet:
    """Rebuild the first ``per_shard_limit`` search records of every
    ``(shard, deal keys)`` (``None`` = every deal) into one ``CandidateSet``
    (shard order = the input order, so the set is a function of its
    digest)."""
    started = time.perf_counter()
    tasks = [(shard, None if keys is None else list(keys), int(per_shard_limit), bool(history))
             for shard, keys in shard_keys]
    by_shard: dict[str, list[dict]] = {}
    labels = [shard.sha256 for shard, _keys in shard_keys]
    done = 0
    for entries in _pool_map(_candidate_set_task, tasks, workers=workers):
        done += 1
        if entries:
            # the worker returns in completion order; key by shard for a stable order
            key = entries[0]["source_ref"]
            by_shard[key] = entries
        if progress and (done % 500 == 0 or done == len(tasks)):
            progress(f"candidate set{(' ' + label) if label else ''}: {done}/{len(tasks)} "
                     f"shards ({round(time.perf_counter() - started, 1)}s)")
    ordered: list[dict] = []
    for entries in sorted(by_shard.values(), key=lambda es: es[0]["source_ref"]):
        ordered.extend(entries)
    meta = {"schema": CANDIDATE_SET_SCHEMA, "digest": candidate_set_digest(
                shard_keys, per_shard_limit=per_shard_limit, history=history),
            "encoder": cwv_encoder_identity(), "history": bool(history),
            "per_shard_limit": int(per_shard_limit), "shards": len(labels),
            "search_means": SEARCH_MEANS_SCALE, "rank_scale": RANK_SCALE,
            "secs": round(time.perf_counter() - started, 3), "label": label}
    out = CandidateSet.concatenate(ordered, meta, history=history)
    out.meta["records"] = out.records
    out.meta["candidates"] = out.candidates
    return out


def ensure_candidate_set(shard_keys: Sequence[tuple[Any, Sequence[str] | None]],
                         cache_dir: str | os.PathLike | None, *, per_shard_limit: int,
                         history: bool, workers: int, label: str = "",
                         progress: Callable[[str], None] | None = None) -> CandidateSet:
    """``build_candidate_set`` memoised in ``cache_dir`` by digest."""
    digest = candidate_set_digest(shard_keys, per_shard_limit=per_shard_limit, history=history)
    path = (None if cache_dir is None
            else Path(cache_dir) / f"candidates-{digest[:24]}{'.cwvh' if history else ''}.npz")
    if path is not None and path.is_file():
        try:
            cached = CandidateSet.load(path)
        except (EvalError, OSError, ValueError, KeyError):
            cached = None
        if cached is not None and cached.meta.get("digest") == digest:
            cached.meta["loaded_from"] = str(path)
            if progress:
                progress(f"candidate set{(' ' + label) if label else ''}: {cached.records} "
                         f"records / {cached.candidates} candidates from {path.name}")
            return cached
    built = build_candidate_set(shard_keys, per_shard_limit=per_shard_limit, history=history,
                                workers=workers, label=label, progress=progress)
    if path is not None:
        built.save(path)
        built.meta["saved_to"] = str(path)
    return built


@torch.no_grad()
def candidate_levels(forward: Callable[[Mapping[str, torch.Tensor]], torch.Tensor],
                     cands: CandidateSet, device: torch.device | str, *,
                     batch_size: int = 4096) -> np.ndarray:
    """The scorer's value per candidate on ``RANK_SCALE``: ``forward(tensors)
    -> logits`` over the 204 classes, expected signed level; terminal rows
    carry their exact level (as the search's evaluator does)."""
    n = cands.candidates
    levels = np.empty(n, dtype=np.float64)
    for lo in range(0, n, batch_size):
        hi = min(n, lo + batch_size)
        t = candidate_tensors(cands.batch_entry(lo, hi), device)
        logits = forward(t)
        prob = torch.softmax(logits.to(torch.float32), dim=1).cpu().numpy().astype(np.float64)
        level, _pt0 = expected_levels(prob)
        levels[lo:hi] = level
    levels = np.where(cands.terminal, cands.terminal_level, levels)
    return levels


def _no_rank() -> dict:
    return {"rank_records": 0, "rank_candidates": 0, "rank_regret": None,
            "rank_regret_points": None, "rank_top1": None, "rank_regret_max": None,
            "rank_scale": RANK_SCALE, "rank_regret_definition": RANK_REGRET_DEFINITION}


def rank_metrics(levels: np.ndarray, cands: CandidateSet) -> dict:
    """Per-decision candidate ranking against the search, averaged over the
    set's records (each with >= 2 candidates and finite search means):

    * ``rank_regret``: level of the search's best mean minus the level of
      the mean of the scorer's argmax candidate (a uniform draw among tied
      maxima), ``RANK_SCALE``, >= 0 -- U(E[points]), the bracket transform
      of the search's MEAN points (``RANK_REGRET_DEFINITION``): an
      MC-ranking proxy, not E[U];
    * ``rank_regret_points``: the same on the search's own scale;
    * ``rank_top1``: probability the scorer's top pick is a search argmax;
    * ``rank_regret_max``: the mean spread (best minus worst mean level) --
      the regret of an inverted ranking."""
    levels = np.asarray(levels, dtype=np.float64)
    if levels.shape != (cands.candidates,):
        raise EvalError("candidate levels are misaligned with the candidate set")
    n = cands.records
    if n == 0:
        return _no_rank()
    if not np.all(np.isfinite(levels)):
        raise EvalError("candidate levels must be finite")
    mean_level = cands.means_level()
    regret = np.empty(n)
    regret_pts = np.empty(n)
    top1 = np.empty(n)
    spread = np.empty(n)
    for r in range(n):
        lo, hi = int(cands.offsets[r]), int(cands.offsets[r + 1])
        s = levels[lo:hi]
        m = cands.means[lo:hi]
        ml = mean_level[lo:hi]
        top = np.flatnonzero(s == s.max())
        regret[r] = ml.max() - ml[top].mean()
        regret_pts[r] = m.max() - m[top].mean()
        top1[r] = float((m == m.max())[top].mean())
        spread[r] = ml.max() - ml.min()
    return {
        "rank_records": int(n), "rank_candidates": int(cands.candidates),
        "rank_regret": float(regret.mean()), "rank_regret_points": float(regret_pts.mean()),
        "rank_top1": float(top1.mean()), "rank_regret_max": float(spread.mean()),
        "rank_scale": RANK_SCALE, "rank_regret_definition": RANK_REGRET_DEFINITION,
    }


def points_metrics(aux_pred: np.ndarray, attacker_points: np.ndarray,
                   points_so_far: np.ndarray) -> dict:
    """The points head on the split's rows: MAE and bias (pred minus real,
    attacker points) and the fraction predicted below the points already
    banked at the decision state (impossible outcomes)."""
    pred = np.asarray(aux_pred, dtype=np.float64)
    has = np.isfinite(pred)
    if not has.any():
        return {"points_n": 0, "points_mae": None, "points_bias": None,
                "points_below_banked": None}
    err = pred[has] - np.asarray(attacker_points, dtype=np.float64)[has]
    banked = np.asarray(points_so_far, dtype=np.float64)[has]
    return {
        "points_n": int(has.sum()),
        "points_mae": float(np.abs(err).mean()),
        "points_bias": float(err.mean()),
        "points_below_banked": float((pred[has] < banked).mean()),
    }


def search_facing_metrics(ev: Mapping[str, np.ndarray], *, levels: np.ndarray | None,
                          cands: CandidateSet | None) -> dict:
    """THE search-facing block (``CONSUMERS``): the level head's per-decision
    ranking (``rank_metrics`` over ``cands`` scored by ``levels``), the
    points head on the rows (``points_metrics``) and the row-level CE / MAE
    of ``train_cwv.run_eval``'s arrays ``ev``.  One function for the
    per-epoch validation, the final val/test pass and ``evaluate``."""
    n = int(ev["ce"].size) if "ce" in ev else 0
    block: dict[str, Any] = {
        "n": n,
        "cross_entropy": float(ev["ce"].mean()) if n else None,
        "value_mae": (float(np.abs(ev["expected_pt0"] - ev["utility"]).mean()) if n else None),
        "value_level_mae": (float(np.abs(ev["expected_level"] - ev["target_level"]).mean())
                            if n else None),
    }
    if cands is not None and levels is not None:
        block.update(rank_metrics(levels, cands))
    else:
        block.update(_no_rank())
    block.update(points_metrics(ev["aux_pred"], ev["attacker_points"], ev["points_so_far"])
                 if n else points_metrics(np.zeros(0), np.zeros(0), np.zeros(0)))
    return block


# ------------------------------------------------- labelled harvest holdouts

HOLDOUT_LABELS_SCHEMA = "shengji-harvest-labels-v1"
HOLDOUT_STRIP_KEYS = ("search_labels", "label_refusal", "deal_key", "state_key")
#: what each search-facing metric of a holdout needs, and why a holdout
#: without it is SKIPPED (reported null), never approximated
HOLDOUT_SUPPORT = {
    "rank_regret": "search_labels with >= 2 finite production means (label_harvest)",
    "calibration": "outcome (attacker_points + signed_level_utility) on the record",
    "points": "outcome.attacker_points on the record (the aux points head)",
}


@dataclass
class LabeledHoldout:
    """A labelled harvest file (``harvest_labels``): the rows (deduplicated
    by ``record_sha256``, first occurrence wins), what they support and the
    labeller's identity."""

    path: str
    sha256: str
    rows: list[dict]
    counts: dict
    supports: dict
    identity: dict
    sources: dict
    policies: dict
    private: bool

    def describe(self) -> dict:
        return {"path": self.path, "sha256": self.sha256, "private": self.private,
                "counts": dict(self.counts), "supports": dict(self.supports),
                "identity": dict(self.identity), "sources": dict(self.sources),
                "policies": dict(self.policies), "support_needs": dict(HOLDOUT_SUPPORT)}


def holdout_record(row: Mapping[str, Any]) -> dict:
    """The untouched harvest record inside a labelled row (its
    ``record_sha256`` is valid again once the label keys are gone)."""
    return {k: v for k, v in row.items() if k not in HOLDOUT_STRIP_KEYS}


def holdout_search_means(row: Mapping[str, Any]) -> tuple[list[int], list[float]] | None:
    """``(ballot indices, means)`` of a row's production labels (the
    ``search_labels`` ballot, acting-team perspective, points scale), or
    None without at least two finite means."""
    labels = row.get("search_labels")
    if not isinstance(labels, dict) or not labels.get("searched") or labels.get("forced"):
        return None
    ballot = labels.get("ballot")
    means = labels.get("means")
    eligible = labels.get("eligible_indices")
    if not isinstance(ballot, list) or not isinstance(means, list) \
            or not isinstance(eligible, list) or len(means) != len(ballot):
        return None
    pairs = []
    for index in eligible:
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(ballot):
            continue
        mean = means[index]
        if isinstance(mean, bool) or not isinstance(mean, (int, float)) or not math.isfinite(mean):
            continue
        pairs.append((int(index), float(mean)))
    if len(pairs) < 2:
        return None
    return [i for i, _ in pairs], [m for _, m in pairs]


def _has_outcome(record: Mapping[str, Any]) -> bool:
    outcome = record.get("outcome")
    return (isinstance(outcome, dict) and isinstance(outcome.get("attacker_points"), int)
            and not isinstance(outcome.get("attacker_points"), bool)
            and outcome.get("signed_level_utility") is not None)


def load_labeled_holdout(path: str | os.PathLike) -> LabeledHoldout:
    """Read a labelled harvest file (a merged ``<source>.labels[.private]
    .jsonl`` or one shard) and say what it supports.  Refuses a file whose
    rows are not labelled rows, and one that mixes labeller identities
    (policy / scale / work) -- its metrics would not be one quantity."""
    path = Path(path)
    if not path.is_file():
        raise EvalError(f"{path}: not a file")
    digest = hashlib.sha256()
    rows: list[dict] = []
    seen: set[str] = set()
    counts: dict[str, Any] = {"lines": 0, "rows": 0, "duplicates": 0, "labelled": 0,
                              "searched": 0, "unsearched": {}, "refused": {},
                              "rank_eligible": 0, "with_outcome": 0,
                              "rank_eligible_with_outcome": 0, "played_off_ballot": 0,
                              "forced": 0, "duplicate_state": 0, "failed_throw_prefix": 0,
                              "deals": 0}
    identities: dict[tuple, int] = {}
    code_shas: dict[str, int] = {}
    deals: set[str] = set()
    sources: dict[str, int] = {}
    policies: dict[str, int] = {}
    with open(path, "rb") as fh:
        for raw in fh:
            digest.update(raw)
            line = raw.strip()
            if not line:
                continue
            counts["lines"] += 1
            row = json.loads(line)
            if not isinstance(row, dict) or "search_labels" not in row \
                    or "label_refusal" not in row or not row.get("record_sha256"):
                raise EvalError(f"{path}: line {counts['lines']} is not a labelled harvest row "
                                "(search_labels / label_refusal / record_sha256 missing)")
            sha = str(row["record_sha256"])
            if sha in seen:
                counts["duplicates"] += 1
                continue
            seen.add(sha)
            rows.append(row)
            counts["rows"] += 1
            sources[str(row.get("source"))] = sources.get(str(row.get("source")), 0) + 1
            policies[str(row.get("policy"))] = policies.get(str(row.get("policy")), 0) + 1
            has_outcome = _has_outcome(row)
            counts["with_outcome"] += int(has_outcome)
            if row.get("deal_key"):
                deals.add(str(row["deal_key"]))
            labels = row["search_labels"]
            if labels is None:
                reason = (row.get("label_refusal") or {}).get("reason", "?")
                counts["refused"][reason] = counts["refused"].get(reason, 0) + 1
                counts["duplicate_state"] += int(reason == "duplicate_state")
                continue
            if labels.get("schema") != HOLDOUT_LABELS_SCHEMA:
                raise EvalError(f"{path}: search_labels schema {labels.get('schema')!r} is not "
                                f"{HOLDOUT_LABELS_SCHEMA!r}")
            counts["labelled"] += 1
            ident = (str(labels.get("policy")), int(labels.get("scale", 1)),
                     int(labels.get("n_worlds", 0)), int(labels.get("report_worlds", 0)),
                     str(labels.get("report_rule")),
                     None if labels.get("work_override") is None
                     else tuple(labels["work_override"]))
            identities[ident] = identities.get(ident, 0) + 1
            code = str(labels.get("code_sha"))
            code_shas[code] = code_shas.get(code, 0) + 1
            if labels.get("searched"):
                counts["searched"] += 1
            else:
                reason = str(labels.get("reason"))
                counts["unsearched"][reason] = counts["unsearched"].get(reason, 0) + 1
            if not labels.get("played_in_ballot", True):
                counts["played_off_ballot"] += 1
            counts["forced"] += int(bool(labels.get("forced")))
            counts["failed_throw_prefix"] += int(bool(labels.get("failed_throw_prefix")))
            eligible = holdout_search_means(row) is not None
            counts["rank_eligible"] += int(eligible)
            counts["rank_eligible_with_outcome"] += int(eligible and has_outcome)
    if len(identities) > 1:
        raise EvalError(f"{path}: mixed labeller identities {sorted(identities)}: one holdout "
                        "must be one labeller (policy, scale, work)")
    ident = next(iter(identities)) if identities else None
    identity = {
        "policy": None if ident is None else ident[0],
        "scale": None if ident is None else ident[1],
        "n_worlds": None if ident is None else ident[2],
        "report_worlds": None if ident is None else ident[3],
        "report_rule": None if ident is None else ident[4],
        "work_override": None if ident is None else ident[5],
        "code_shas": dict(sorted(code_shas.items())),
        "labels_schema": HOLDOUT_LABELS_SCHEMA,
    }
    counts["unsearched"] = dict(sorted(counts["unsearched"].items()))
    counts["refused"] = dict(sorted(counts["refused"].items()))
    counts["deals"] = len(deals)
    supports = {
        "rank_regret": counts["rank_eligible"] > 0,
        "calibration": counts["with_outcome"] > 0,
        "points": counts["with_outcome"] > 0,
    }
    return LabeledHoldout(path=str(path.resolve()), sha256=digest.hexdigest(), rows=rows,
                          counts=counts, supports=supports, identity=identity,
                          sources=dict(sorted(sources.items())),
                          policies=dict(sorted(policies.items())),
                          private=not (path.stat().st_mode & 0o044))


def holdout_candidate_entries(rows: Sequence[Mapping[str, Any]], *, history: bool,
                              limit: int | None = None) -> tuple[list[dict], dict]:
    """``score_candidates`` entries for every rank-eligible labelled row
    (the labels' ballot applied in the record's TRUE world, encoded once),
    in file order; no outcome is needed.  Returns ``(entries, counts)``."""
    entries: list[dict] = []
    counts = {"rows": 0, "rank_eligible": 0, "encoded": 0, "rebuild_failed": 0,
              "turn_mismatch": 0, "action_failed": 0}
    for row in rows:
        counts["rows"] += 1
        means = holdout_search_means(row)
        if means is None:
            continue
        counts["rank_eligible"] += 1
        if limit is not None and len(entries) >= int(limit):
            continue
        record = holdout_record(row)
        seat = int(record["seat"])
        try:
            rnd = state_for_record(record)
        except (RebuildError, ValueError, KeyError, AssertionError, TypeError):
            counts["rebuild_failed"] += 1
            continue
        if rnd.phase != "play" or rnd.turn != seat:
            counts["turn_mismatch"] += 1
            continue
        indices, values = means
        ballot = row["search_labels"]["ballot"]
        try:
            scored = score_candidates(rnd, seat, [ballot[i] for i in indices], history=history)
        except ValueAfterstateError:
            counts["action_failed"] += 1
            continue
        scored["means"] = np.asarray(values, dtype=np.float64)
        scored["source_ref"] = str(record["source_ref"])
        scored["deal_key"] = deal_key(list(record["deck"])) if isinstance(record.get("deck"), list) \
            else f"ref:{record['source_ref']}"
        entries.append(scored)
        counts["encoded"] += 1
    return entries, counts


def holdout_candidate_set(holdout: LabeledHoldout, *, history: bool, limit: int | None = None,
                          label: str = "") -> CandidateSet:
    """The holdout's ``CandidateSet`` (``rank_metrics`` input): the same
    arrays, scale and metric definitions as the self-play candidate sets,
    with the production labels as the search means."""
    started = time.perf_counter()
    entries, counts = holdout_candidate_entries(holdout.rows, history=history, limit=limit)
    digest = hashlib.sha256(json.dumps({
        "schema": CANDIDATE_SET_SCHEMA, "holdout": holdout.sha256,
        "encoder": cwv_encoder_identity()["implementation_sha256"],
        "history": bool(history), "limit": limit}, sort_keys=True).encode("ascii")).hexdigest()
    meta = {"schema": CANDIDATE_SET_SCHEMA, "digest": digest,
            "encoder": cwv_encoder_identity(), "history": bool(history),
            "per_shard_limit": None if limit is None else int(limit), "shards": 1,
            "search_means": SEARCH_MEANS_SCALE + " -- here: production labels "
                                                 "(harvest_labels, search_labels.means)",
            "rank_scale": RANK_SCALE, "label": label, "holdout": holdout.path,
            "holdout_sha256": holdout.sha256, "counts": counts,
            "secs": round(time.perf_counter() - started, 3)}
    out = CandidateSet.concatenate(entries, meta, history=history)
    out.meta["records"] = out.records
    out.meta["candidates"] = out.candidates
    return out


def materialize_holdout_records(holdout: LabeledHoldout, out_path: str | os.PathLike) -> Path:
    """Write the holdout's untouched harvest records (label keys stripped,
    every ``record_sha256`` valid) as one canonical JSONL so the row-level
    pipeline (``cwv_data.prepare_stores`` -> ``bridge_record``) reads them
    unchanged; 0600 when the holdout is private.  Returns the path."""
    from ..harvest.schema import encode_line
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_name(f"{out_path.name}.{os.getpid()}.tmp")
    mode = 0o600 if holdout.private else 0o644
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    with os.fdopen(fd, "wb") as fh:
        os.fchmod(fh.fileno(), mode)
        for row in holdout.rows:
            fh.write(encode_line(holdout_record(row)).encode("ascii"))
    os.replace(tmp, out_path)
    return out_path


__all__ = [
    "CANDIDATE_SET_SCHEMA", "CONSUMERS", "CandidateSet", "EvalError", "RANK_REGRET_DEFINITION",
    "RANK_SCALE",
    "HOLDOUT_LABELS_SCHEMA", "HOLDOUT_SUPPORT", "LabeledHoldout",
    "SCORERS", "SEARCH_MEANS_SCALE", "ShardResult", "build_candidate_set",
    "candidate_agreement", "candidate_levels", "candidate_pass", "candidate_set_digest",
    "candidate_tensors", "ensure_candidate_set", "holdout_candidate_entries",
    "holdout_candidate_set", "holdout_record", "holdout_search_means", "iter_shard_results",
    "load_labeled_holdout", "materialize_holdout_records",
    "level_of_search_mean", "load_public_head", "paired_agreement", "points_metrics",
    "public_values", "rank_metrics", "score_candidates", "search_facing_metrics",
    "spearman", "summarize_agreement",
]
