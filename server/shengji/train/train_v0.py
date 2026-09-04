"""``train`` / ``evaluate`` for the v0 value/prior model (train_spec.md).

    train_v0.py train --data DIR [--data DIR ...] [--eval-luna PATH] --out DIR
        [--device mps|cpu] [--epochs 20] [--seed 1] [--prior-target softmax|final]
        [--limit-clusters N] [--prior-weight 1.0] [--hidden 512]
        [--val-fraction 0.1] [--test-fraction 0.1]
        [--aux-search-mean W] [--cache-workers N] [--resident-bytes B]
        [--privacy-witness-every 1 [--allow-sampled-privacy-witness]] ...
    train_v0.py evaluate --checkpoint CKPT (--data DIR | --eval-luna PATH) --out DIR
        [--split test|novel|val|train|all]

Outputs in ``--out``: ``receipt.json`` (git sha, encoder identity, data
manifests + shard hashes, config hash, seeds, split summary, per-epoch
train/validation telemetry, final metrics per split, baseline metrics,
calibration, residency and peak memory), ``metrics.json``,
``checkpoints/epoch-NN.pt``, ``best.pt`` and the derived encoding cache
under ``cache/``.  Progress lines carry counts and losses only.

Splits (three-way, by DEAL)
---------------------------
Every row is bound to its canonical deal key (``data.deal_key``: a digest
of the dealt deck, the same for every store, policy, knob set and mirror
that replayed the deal) and the deals are ranked by ``sha256(seed|key)``:
the top ``test_fraction`` are the TEST split, the next ``val_fraction`` the
VALIDATION split, the rest TRAIN (default 80/10/10).  Roles are fixed:

* train: the model, the stratified prior, the incumbent eps;
* val: epoch selection (``best.pt``: lowest ``value + prior_weight *
  prior CE``) and the affine calibration fit -- TUNING telemetry, reported
  as such (``final.val.held_out == false``), never as held-out evidence;
* test: the reported metrics (``final.test``, the receipt's ``headline``);
  never read by selection or calibration;
* Luna (``--eval-luna``): an external held-out set scored against the
  stratified prior fitted on TRAIN; refused when it shares a deal key with
  any row of the data stores (``final.luna``).

Populations (persisted identities)
----------------------------------
The deal keys of every part (``fit_population``: train = the fit
population, val = the selection population, test) are persisted in every
checkpoint and receipt (``population``, with per-part digests).
``evaluate`` checks whatever it is asked to score against THOSE, never
against the caller's store: a Luna set is refused when it shares a deal
with the fit or selection population (with or without ``--data``); a
``--data`` store's rows are scored by the checkpoint's persisted part
(``--split test|val|train``; a different store is detected and reported
in ``split.population_match``, and a part with no rows in it refuses) or
as ``--split novel`` (the deals the checkpoint never saw; held out).
Every held-out block carries its ``population`` report with an explicit
zero overlap; ``check_receipt`` refuses a receipt whose labels contradict
the roles (a validation block marked held out, a headline that is not
held out, a calibration fitted on a held-out split, a held-out block
whose population was not checked -- ``None`` -- or overlaps, a Luna
overlap that is not an explicit zero, non-disjoint populations).

Privacy, residency, cache
-------------------------
The privacy witness (``data.privacy_witness``) runs on EVERY row of every
shard the run encodes (``--privacy-witness-every 1``); ``N > 1`` is refused
unless ``--allow-sampled-privacy-witness`` is passed, and the receipt
records both (``privacy_witness``).  ``--resident-bytes B`` (default 40% of
physical memory) bounds the decoded blocks held in memory (``data``:
RESIDENCY contract; the receipt's ``residency`` block reports the budget,
the corpus's decoded size and the peak resident bytes, ``peak_memory`` the
process RSS).  ``--cache-workers N`` (default ``min(8, cpu)``) encodes the
missing shard caches N at a time in spawned processes
(``data.ensure_caches``); the files are byte-identical to a one-worker
build.  ``--aux-search-mean W`` (default 0 = off) adds the auxiliary
search-mean head (``model.py`` / ``data.py``) with weight W in the TRAINING
loss; its MAE is reported separately (``final.<split>.aux_search_mean``, in
points) and the primary value / prior metrics and the selection loss are
computed exactly as without it.  ``--hidden N`` sets the trunk to ``[N, N
// 2]``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import resource
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Collection, Mapping, Sequence

import numpy as np
import torch

from ..harvest.schema import canonical_json
from .baselines import (StratifiedPrior, apply_affine, fit_affine, fit_incumbent_eps,
                        prior_summary, reliability_table, value_summary)
from .data import (CACHE_WORKERS_CAP, DEAL_KEY_SCHEMA, PRIVACY_TRIALS, Block, BlockStore,
                   Residency, Store, TrainDataError, cache_path, check_witness_every, collate,
                   default_cache_workers, default_resident_bytes, discover_store,
                   encoder_identity, ensure_caches, first_deals, physical_memory_bytes,
                   split_counts, split_deals, split_mask)
from .model import (DEFAULT_ARCH, DEFAULT_HIDDEN, MODEL_SCHEMA, SEARCH_MEAN_SCALE,
                    ValuePriorNet, batch_losses, prior_cross_entropy, prior_log_probs,
                    trunk_for)

RECEIPT_SCHEMA = "shengji-train-v0-receipt-v3"     # v3: + persisted populations
CHECKPOINT_SCHEMA = "shengji-train-v0-checkpoint-v3"
POPULATION_SCHEMA = "shengji-train-v0-population-v1"
EVAL_SPLITS = ("test", "novel", "val", "train", "all")
PRIOR_TARGETS = ("softmax", "final")
DEFAULTS = {
    "epochs": 20, "seed": 1, "lr": 3e-4, "weight_decay": 1e-4, "batch_size": 1024,
    "patience": 3, "prior_weight": 1.0, "prior_target": "softmax", "val_fraction": 0.1,
    "test_fraction": 0.1, "huber_delta": 1.0, "aux_points": False, "aux_weight": 0.1,
    "aux_search_mean": 0.0, "hidden": DEFAULT_HIDDEN, "n_boot": 1000, "window": 64,
    "limit_clusters": None,
}
REQUIRED_RECEIPT_FIELDS = (
    "schema", "command", "git", "encoder", "data", "config", "config_sha256", "seeds",
    "split", "population", "counts", "epochs", "final", "headline", "selection", "baselines",
    "calibration", "checkpoints", "wall_secs", "peak_memory", "residency",
    "privacy_witness", "device", "versions", "argv", "started",
)
#: the fixed role of every reported split: what it was used for, and
#: whether its numbers are held-out evidence
SPLIT_ROLES = {
    "train": {"held_out": False,
              "role": "fit: the model, the stratified prior and the incumbent eps"},
    "val": {"held_out": False,
            "role": "tuning telemetry: epoch selection and the calibration fit; NOT held out"},
    "test": {"held_out": True,
             "role": "held-out: reported metrics; never read by selection or calibration"},
    "luna": {"held_out": True,
             "role": "held-out: external evaluation set, disjoint from the fit/selection deals"},
    "novel": {"held_out": True,
              "role": "held-out: deals the checkpoint never saw (a foreign store's clean rows)"},
}
HEADLINE = "test"
SELECTION_SPLIT = "val"
SELECTION_CRITERION = "validation loss = value huber + prior_weight * prior CE (never the aux term)"
SERVER = Path(__file__).resolve().parents[2]


class TrainError(RuntimeError):
    """The run cannot be carried out as specified."""


# ------------------------------------------------------------------ device

def pick_device(name: str | None) -> torch.device:
    if name in (None, "", "auto"):
        return torch.device("mps" if torch.backends.mps.is_available() else "cpu")
    if name == "mps" and not torch.backends.mps.is_available():
        raise TrainError("--device mps requested but MPS is not available")
    return torch.device(name)


def seed_everything(seed: int, device: torch.device) -> dict:
    """Fix every RNG the run touches; the receipt stamps the values."""
    import random
    random.seed(seed)
    np.random.seed(seed % (2 ** 32))
    torch.manual_seed(seed)
    if device.type == "mps" and hasattr(torch, "mps"):
        torch.mps.manual_seed(seed)
    if device.type == "cpu":
        torch.use_deterministic_algorithms(True)
    return {"seed": seed, "python_random": seed, "numpy": seed % (2 ** 32),
            "torch": seed, "batch_order": seed, "split": seed, "bootstrap": seed,
            "privacy_witness": seed,
            "deterministic_algorithms": device.type == "cpu"}


# -------------------------------------------------------------------- data

@dataclass
class Prepared:
    stores: list[Store]
    block_store: BlockStore
    counts: dict
    cache_files: list[dict] = field(default_factory=list)
    residency: Residency | None = None


def _merge_counts(total: dict, counts: dict) -> None:
    for key, value in counts.items():
        if isinstance(value, dict):
            total.setdefault(key, {})
            _merge_counts(total[key], value)
        elif isinstance(value, str):
            total.setdefault(key, value)          # first note wins
        else:
            total[key] = total.get(key, 0) + value


def prepare_stores(paths: list[str], cache_dir: Path, *, limit_clusters: int | None,
                   witness_seed: int, progress: Callable[[str], None] | None = None,
                   cache_workers: int | None = None, residency: Residency | None = None,
                   resident_bytes: int | None = None, witness_every: int = 1,
                   allow_sampled_witness: bool = False) -> Prepared:
    """Discover, verify, encode (cache; the missing shards ``cache_workers``
    at a time, default ``data.default_cache_workers()``; the privacy
    witness on every ``witness_every``-th row, 1 = every row) and index
    every store into one ``BlockStore`` over ``residency`` (or a new
    ``Residency(resident_bytes)``).  Nothing is decoded here: ``counts``
    come from the cache metas and the deal-key columns."""
    witness_every = check_witness_every(witness_every, allow_sampled_witness)
    stores = [discover_store(path, limit_clusters=limit_clusters) for path in paths]
    jobs = [(shard, store.private) for store in stores for shard in store.shards]
    if not jobs:
        raise TrainError("no shard to train on")
    built = ensure_caches(jobs, cache_dir, witness_seed=witness_seed,
                          witness_every=witness_every,
                          allow_sampled_witness=allow_sampled_witness,
                          workers=cache_workers, progress=progress)
    entries: list[tuple] = []
    keep: list = []
    counts: dict = {"shards": 0, "cache_rebuilt": 0, "cache_reused": 0}
    cache_files: list[dict] = []
    built_iter = iter(built)
    for store in stores:
        first = len(entries)
        for shard in store.shards:
            meta, rebuilt = next(built_iter)
            counts["shards"] += 1
            counts["cache_rebuilt" if rebuilt else "cache_reused"] += 1
            _merge_counts(counts, {"records": meta["counts"]})
            path = str(cache_path(cache_dir, shard.sha256))
            cache_files.append({"label": shard.label, "shard_sha256": shard.sha256,
                                "cache": path, "records": int(meta["counts"]["encoded"]),
                                "nbytes": int(meta["nbytes"]),
                                "witness_every": int(meta["witness_every"]),
                                "rebuilt": rebuilt})
            entries.append((shard, path))
            keep.append(None)
            if progress:
                pc = meta["counts"]["preference"]
                progress(f"shard {shard.label}: encoded={meta['counts']['encoded']} "
                         f"prior_stored={pc['stored']} prior_derived={pc['derived']} "
                         f"prior_missing={pc['missing']} "
                         f"legacy_schema={meta['counts'].get('legacy_schema', 0)} "
                         f"witness_every={meta['witness_every']} "
                         f"nbytes={meta['nbytes']} {'rebuilt' if rebuilt else 'cached'}")
        if limit_clusters is not None and store.layout != "shard-store":
            # merged/jsonl layouts: keep the first N deals in file order
            kept: dict[str, None] = {}
            for _shard, path in entries[first:]:
                for key in first_deals(path, int(limit_clusters)):
                    if len(kept) < int(limit_clusters):
                        kept.setdefault(key, None)
            for i in range(first, len(entries)):
                keep[i] = set(kept)
    block_store = BlockStore(entries, residency=residency, resident_bytes=resident_bytes,
                             keep=keep, witness_every=witness_every)
    rows = block_store.rows()
    counts["records_total"] = int(sum(rows))
    counts["deals_total"] = len(block_store.keys())
    counts["decoded_bytes"] = int(block_store.nbytes)
    return Prepared(stores=stores, block_store=block_store, counts=counts,
                    cache_files=cache_files, residency=block_store.residency)


def shared_deals(a: BlockStore, b: BlockStore) -> list[str]:
    """Deal keys present in both stores (sorted)."""
    return sorted(set(a.keys()) & set(b.keys()))


def refuse_overlap(training: BlockStore, evaluation: BlockStore, *, label: str) -> int:
    """Refuse an evaluation set that shares a deal with the data stores
    (the evaluation would not be independent); returns 0."""
    shared = shared_deals(training, evaluation)
    if shared:
        raise TrainError(
            f"{label} shares {len(shared)} deal(s) with the data stores (e.g. "
            f"{shared[0]}): the evaluation is not independent of training; refusing")
    return 0


# ----------------------------------------------------------------- tensors

def to_tensors(batch: dict[str, np.ndarray], device: torch.device, prior_target: str
               ) -> dict[str, torch.Tensor]:
    played = batch["played"]
    if prior_target == "final":
        target = np.zeros_like(batch["target"])
        known = played >= 0
        target[np.flatnonzero(known), played[known]] = 1.0
        has = known & batch["mask"].any(axis=1)
    else:
        target = batch["target"]
        has = batch["has_softmax"]
    return {
        "obs": torch.from_numpy(np.ascontiguousarray(batch["obs"])).to(device),
        "cand": torch.from_numpy(np.ascontiguousarray(batch["cand"])).to(device),
        "mask": torch.from_numpy(np.ascontiguousarray(batch["mask"])).to(device),
        "target": torch.from_numpy(np.ascontiguousarray(target)).to(device),
        "has_softmax": torch.from_numpy(np.ascontiguousarray(has)).to(device),
        "utility": torch.from_numpy(np.ascontiguousarray(batch["utility"])).to(device),
        "attacker_points": torch.from_numpy(
            np.ascontiguousarray(batch["attacker_points"])).to(device),
        "search_mean": torch.from_numpy(np.ascontiguousarray(batch["search_mean"])).to(device),
        "has_search_mean": torch.from_numpy(
            np.ascontiguousarray(batch["has_search_mean"])).to(device),
    }


# --------------------------------------------------------------- baselines

def fit_baselines(store: BlockStore, mask_fn: Callable[[Block], np.ndarray]) -> dict:
    """The stratified prior (value, and the same strata over the aux
    search-mean target where present) and the incumbent eps, from the
    TRAINING rows."""
    prior = StratifiedPrior()
    search_prior = StratifiedPrior()
    first_soft: list[np.ndarray] = []
    width_soft: list[np.ndarray] = []
    first_final: list[np.ndarray] = []
    width_final: list[np.ndarray] = []
    for block in store.iter_blocks():
        sel = np.flatnonzero(mask_fn(block))
        if not sel.size:
            continue
        prior.add(block.ply[sel], block.role_attacker[sel], block.points_so_far[sel],
                  block.utility[sel])
        has_s = block.has_search_mean[sel]
        if has_s.any():
            rows = sel[has_s]
            search_prior.add(block.ply[rows], block.role_attacker[rows],
                             block.points_so_far[rows], block.search_mean[rows])
        widths = block.widths[sel]
        wide = widths >= 2
        has = block.has_softmax[sel] & wide
        if has.any():
            starts = block.cand_offsets[sel][has]
            first_soft.append(block.cand_softmax[starts])
            width_soft.append(widths[has])
        played = block.played[sel]
        known = (played >= 0) & wide
        if known.any():
            first_final.append((played[known] == 0).astype(np.float64))
            width_final.append(widths[known])
    cat = lambda parts: np.concatenate(parts) if parts else np.zeros(0)  # noqa: E731
    return {
        "stratified_prior": prior.to_dict(),
        "search_mean_prior": search_prior.to_dict(),
        "incumbent": {
            "softmax": fit_incumbent_eps(cat(first_soft), cat(width_soft)),
            "final": fit_incumbent_eps(cat(first_final), cat(width_final)),
        },
        "fitted_on": "train",
    }


# -------------------------------------------------------------- evaluation

@torch.no_grad()
def run_eval(model: ValuePriorNet, store: BlockStore, mask_fn: Callable[[Block], np.ndarray],
             device: torch.device, *, prior_target: str, prior_weight: float,
             batch_size: int, huber_delta: float) -> dict[str, np.ndarray]:
    """Per-record predictions and losses over the selected rows (one block
    resident at a time; batches gathered from it)."""
    model.eval()
    out: dict[str, list] = {k: [] for k in (
        "pred", "utility", "ply", "role_attacker", "points_so_far", "deal_key", "width",
        "has_softmax", "played", "ce_softmax", "nll_played", "top1", "first_softmax",
        "loss_value", "loss_prior", "has_target", "search_pred", "search_target",
        "has_search")}
    for block in store.iter_blocks():
        sel = np.flatnonzero(mask_fn(block))
        if not sel.size:
            continue
        for b0 in range(0, sel.size, batch_size):
            idx = sel[b0:b0 + batch_size]
            raw = collate(block, idx)
            t = to_tensors(raw, device, prior_target)
            value, _aux, logits, search = model(t["obs"], t["cand"], t["mask"])
            logp = prior_log_probs(logits, t["mask"])
            ce_soft = prior_cross_entropy(logits, t["mask"],
                                          torch.from_numpy(raw["target"]).to(device))
            ce_train = prior_cross_entropy(logits, t["mask"], t["target"])
            played = raw["played"]
            known = played >= 0
            gather = torch.from_numpy(np.where(known, played, 0)).to(device).long()
            nll = -logp.gather(1, gather.unsqueeze(1)).squeeze(1).cpu().numpy()
            nll = np.where(known, nll, np.nan)
            argmax = logits.argmax(dim=1).cpu().numpy()
            widths = raw["widths"]
            first = np.zeros(len(idx), dtype=np.float32)
            if block.cand_softmax.size:
                starts = block.cand_offsets[idx]
                first[widths > 0] = block.cand_softmax[starts[widths > 0]]
            v_loss = torch.nn.functional.huber_loss(value, t["utility"], delta=huber_delta,
                                                    reduction="none")
            out["pred"].append(value.cpu().numpy())
            out["utility"].append(raw["utility"])
            out["ply"].append(block.ply[idx])
            out["role_attacker"].append(block.role_attacker[idx])
            out["points_so_far"].append(block.points_so_far[idx])
            out["deal_key"].append(block.deal_key[idx])
            out["width"].append(widths)
            out["has_softmax"].append(raw["has_softmax"])
            out["played"].append(played)
            out["ce_softmax"].append(ce_soft.cpu().numpy())
            out["nll_played"].append(nll)
            out["top1"].append(argmax == played)
            out["first_softmax"].append(first)
            out["loss_value"].append(v_loss.cpu().numpy())
            out["loss_prior"].append(ce_train.cpu().numpy())
            out["has_target"].append(t["has_softmax"].cpu().numpy())
            # aux search mean back in points; NaN when the model has no head
            out["search_pred"].append(
                np.full(len(idx), np.nan, dtype=np.float32) if search is None
                else search.cpu().numpy() * SEARCH_MEAN_SCALE)
            out["search_target"].append(raw["search_mean"])
            out["has_search"].append(raw["has_search_mean"])
    if not out["pred"]:
        return {k: np.zeros(0) for k in out}
    return {k: np.concatenate(v) for k, v in out.items()}


def _search_rows(ev: dict[str, np.ndarray]) -> np.ndarray:
    """Rows scored by the aux search-mean head: a target and a prediction."""
    return ev["has_search"].astype(bool) & np.isfinite(ev["search_pred"])


def quick_metrics(ev: dict[str, np.ndarray], *, prior_weight: float) -> dict:
    """Cheap per-epoch metrics (no bootstrap).  ``loss`` (the checkpoint
    selection criterion) is value + prior_weight * prior CE, never the aux
    term; ``aux_search_mae`` is in points and None without the head."""
    n = int(ev["pred"].size)
    if n == 0:
        return {"n": 0, "loss": None}
    err = ev["pred"] - ev["utility"]
    has = ev["has_target"].astype(bool)
    wide = ev["width"] >= 2
    known = (ev["played"] >= 0) & wide
    value = float(ev["loss_value"].mean())
    prior = float(ev["loss_prior"][has].mean()) if has.any() else 0.0
    has_s = _search_rows(ev)
    return {
        "n": n,
        "loss": value + prior_weight * prior,
        "value_huber": value,
        "value_mae": float(np.abs(err).mean()),
        "value_mse": float((err ** 2).mean()),
        "prior_ce": prior if has.any() else None,
        "prior_rows": int(has.sum()),
        "nll_played": float(np.nanmean(ev["nll_played"][known])) if known.any() else None,
        "top1_agreement": float(ev["top1"][known].mean()) if known.any() else None,
        "aux_search_mae": (float(np.abs(ev["search_pred"][has_s]
                                        - ev["search_target"][has_s]).mean())
                           if has_s.any() else None),
        "aux_search_rows": int(has_s.sum()),
    }


def full_metrics(ev: dict[str, np.ndarray], baselines: dict, *, prior_target: str,
                 prior_weight: float, n_boot: int, seed: int, calibration: dict | None,
                 calibration_in_sample: bool = False) -> dict:
    """Metrics of one split with baselines, deal-bootstrap CIs and
    calibration; the primary blocks (``value``, ``prior``, ``calibration``)
    do not depend on the aux head, which reports under ``aux_search_mean``
    only when present (points; against the training stratified prior of
    the target).  ``calibration_in_sample`` marks the split the affine fit
    was made on (its ``mae_after`` is in-sample)."""
    metrics = quick_metrics(ev, prior_weight=prior_weight)
    n = metrics["n"]
    if n == 0:
        return metrics
    prior = StratifiedPrior.from_dict(baselines["stratified_prior"])
    base_pred = prior.predict(ev["ply"], ev["role_attacker"], ev["points_so_far"])
    metrics["value"] = value_summary(ev["pred"], base_pred, ev["utility"], ev["deal_key"],
                                     n_boot=n_boot, seed=seed)
    metrics["deals"] = int(np.unique(ev["deal_key"]).size)
    has_s = _search_rows(ev)
    if has_s.any():
        sp = baselines.get("search_mean_prior")
        search_prior = StratifiedPrior.from_dict(sp) if sp else StratifiedPrior()
        s_base = search_prior.predict(ev["ply"][has_s], ev["role_attacker"][has_s],
                                      ev["points_so_far"][has_s])
        metrics["aux_search_mean"] = {
            **value_summary(ev["search_pred"][has_s], s_base, ev["search_target"][has_s],
                            ev["deal_key"][has_s], n_boot=n_boot, seed=seed),
            "units": "points, acting-team perspective (action_values.means[played_index])",
            "rows_without_target": int((~ev["has_search"].astype(bool)).sum()),
        }
    wide = ev["width"] >= 2
    has = ev["has_softmax"].astype(bool) & wide
    known = (ev["played"] >= 0) & wide
    eps = baselines["incumbent"]
    metrics["prior"] = {"training_target": prior_target}
    if has.any():
        metrics["prior"]["softmax"] = prior_summary(
            ev["ce_softmax"][has], ev["nll_played"][has], ev["top1"][has],
            ev["first_softmax"][has], ev["width"][has], ev["played"][has],
            ev["deal_key"][has], incumbent_eps=eps["softmax"]["eps"], n_boot=n_boot, seed=seed)
    else:
        metrics["prior"]["softmax"] = {"n": 0}
    if known.any():
        metrics["prior"]["final"] = prior_summary(
            ev["nll_played"][known], ev["nll_played"][known], ev["top1"][known],
            (ev["played"][known] == 0).astype(np.float64), ev["width"][known],
            ev["played"][known], ev["deal_key"][known],
            incumbent_eps=eps["final"]["eps"], n_boot=n_boot, seed=seed)
    else:
        metrics["prior"]["final"] = {"n": 0}
    metrics["prior"]["rows_single_candidate"] = int((~wide).sum())
    if calibration is not None:
        cal_pred = apply_affine(ev["pred"], calibration)
        metrics["calibration"] = {
            "scale": calibration["scale"], "shift": calibration["shift"],
            "fitted_on": calibration.get("fitted_on"),
            "in_sample": bool(calibration_in_sample),
            "mae_before": float(np.abs(ev["pred"] - ev["utility"]).mean()),
            "mae_after": float(np.abs(cal_pred - ev["utility"]).mean()),
            "mse_before": float(((ev["pred"] - ev["utility"]) ** 2).mean()),
            "mse_after": float(((cal_pred - ev["utility"]) ** 2).mean()),
            "reliability": [
                {**row, "pred_mean_calibrated": float(
                    calibration["scale"] * row["pred_mean"] + calibration["shift"])}
                for row in reliability_table(ev["pred"], ev["utility"], bins=10)],
        }
    return metrics


def labelled(name: str, metrics: dict) -> dict:
    """``metrics`` stamped with the split's fixed role (``SPLIT_ROLES``)."""
    role = SPLIT_ROLES[name]
    return {**metrics, "split": name, "held_out": bool(role["held_out"]), "role": role["role"]}


# ------------------------------------------------------------- populations

def fit_population(assignment: Mapping[str, str], *, stores: Sequence[Store]) -> dict:
    """The deal identities a run fits, selects and tests on: the sorted
    deal keys of every part (``train`` = the fit population, ``val`` = the
    selection population, ``test``), their digests, and the stores they
    came from.  Persisted in every checkpoint and receipt so that a later
    evaluation can be checked against THESE deals rather than against
    whatever store the caller supplies."""
    parts = {part: sorted(k for k, v in assignment.items() if v == part)
             for part in ("train", "val", "test")}
    digest = {part: hashlib.sha256("\n".join(keys).encode("utf-8")).hexdigest()
              for part, keys in parts.items()}
    return {
        "schema": POPULATION_SCHEMA,
        "deal_key_schema": DEAL_KEY_SCHEMA,
        **parts,
        "counts": {part: len(keys) for part, keys in parts.items()},
        "digest": digest,
        "data": [{"root": s.root, "layout": s.layout,
                  "shards": [{"label": sh.label, "sha256": sh.sha256} for sh in s.shards]}
                 for s in stores],
    }


def population_sets(population: Mapping[str, Any] | None) -> dict[str, set[str]]:
    """``{"train", "val", "test"}`` as sets from a persisted population,
    validated: the schema, and the three parts pairwise disjoint."""
    if not isinstance(population, Mapping) or population.get("schema") != POPULATION_SCHEMA:
        raise TrainError("checkpoint carries no persisted fit/selection/test populations "
                         f"({POPULATION_SCHEMA}); refusing to evaluate an unknown population")
    if population.get("deal_key_schema") != DEAL_KEY_SCHEMA:
        raise TrainError("population deal-key schema differs from this build's")
    sets = {}
    for part in ("train", "val", "test"):
        keys = population.get(part)
        if not isinstance(keys, list) or not all(isinstance(k, str) for k in keys):
            raise TrainError(f"population.{part} is not a list of deal keys")
        sets[part] = set(keys)
    if sets["train"] & sets["val"] or sets["train"] & sets["test"] or sets["val"] & sets["test"]:
        raise TrainError("persisted populations overlap: the checkpoint's split is not a split")
    return sets


def population_report(keys: Collection[str], population: Mapping[str, Any]) -> dict:
    """How a set of deal keys relates to a persisted population: counts in
    every part, the deals it never saw (``novel``), the overlap with the
    fit (train) and selection (val) populations, and the digest it was
    checked against.  A held-out label requires both overlaps to be 0."""
    keys = set(str(k) for k in keys)
    sets = population_sets(population)
    novel = keys - sets["train"] - sets["val"] - sets["test"]
    return {
        "deals": len(keys),
        "in_train": len(keys & sets["train"]),
        "in_val": len(keys & sets["val"]),
        "in_test": len(keys & sets["test"]),
        "novel": len(novel),
        "shared_with_fit": len(keys & sets["train"]),
        "shared_with_selection": len(keys & sets["val"]),
        "same_population": keys == (sets["train"] | sets["val"] | sets["test"]),
        "checked_against": dict(population["digest"]),
    }


def _is_zero(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value == 0


def check_receipt(receipt: dict) -> dict:
    """Refuse a receipt whose split labels contradict the fixed roles:
    every reported split must carry its fixed ``held_out`` flag (a
    validation block can never be labelled held out), the headline (when
    the receipt has one; a ``train`` receipt always does) must be a
    reported held-out split, the selection and calibration splits must be
    tuning splits, every held-out block must have been CHECKED against
    the persisted fit/selection populations with zero overlap (an
    unchecked population -- ``None`` -- is refused), the Luna overlap must
    be an explicit zero, and a train receipt must carry disjoint
    populations.  Returns the receipt."""
    final = receipt.get("final") or {}
    headline = receipt.get("headline")
    for name, block in final.items():
        role = SPLIT_ROLES.get(name)
        if role is None:
            if name == "all" and receipt.get("command") == "evaluate" and not block.get("held_out"):
                continue
            raise TrainError(f"receipt: unknown split {name!r} in final")
        if block.get("held_out") is not bool(role["held_out"]):
            raise TrainError(
                f"receipt: final.{name} is labelled held_out={block.get('held_out')!r}; "
                f"the {name} split is {'' if role['held_out'] else 'NOT '}held out "
                f"({role['role']})")
        if block.get("held_out"):
            pop = block.get("population") or {}
            for field in ("shared_with_fit", "shared_with_selection"):
                if not _is_zero(pop.get(field)):
                    raise TrainError(
                        f"receipt: final.{name} is labelled held out but its population "
                        f"was not checked against the checkpoint's fit/selection deals "
                        f"({field}={pop.get(field)!r})")
    if receipt.get("command") == "train" and headline is None:
        raise TrainError("receipt: a train receipt needs a held-out headline split")
    if headline is not None and (headline not in final or not final[headline].get("held_out")):
        raise TrainError(f"receipt: headline {headline!r} is not a reported held-out split")
    selection = receipt.get("selection") or {}
    if receipt.get("command") == "train":
        sel = selection.get("split")
        if sel not in SPLIT_ROLES or SPLIT_ROLES[sel]["held_out"]:
            raise TrainError(f"receipt: selection split {sel!r} must be a tuning split")
        population_sets(receipt.get("population"))
    cal = receipt.get("calibration")
    if cal is not None:
        fitted = cal.get("fitted_on")
        if fitted not in SPLIT_ROLES or SPLIT_ROLES[fitted]["held_out"]:
            raise TrainError(f"receipt: calibration fitted on {fitted!r}, a held-out split")
        for name, block in final.items():
            c = block.get("calibration")
            if c is not None and bool(c.get("in_sample")) != (name == fitted):
                raise TrainError(f"receipt: final.{name}.calibration.in_sample mislabelled")
    luna = receipt.get("luna")
    if "luna" in final and final["luna"].get("held_out"):
        shared = None if luna is None else luna.get("shared_deals_with_training")
        if not _is_zero(shared):
            raise TrainError("receipt: the Luna set's overlap with the fit/selection deals is "
                             f"unknown or non-zero ({shared!r}); it cannot be labelled held out")
    return receipt


# ------------------------------------------------------------- checkpoints

def save_checkpoint(path: Path, model: ValuePriorNet, *, config: dict, epoch: int,
                    selection: dict, baselines: dict, calibration: dict | None,
                    split: dict, population: dict, metrics: dict | None = None) -> None:
    """``population`` (``fit_population``): the deal identities this model
    was fitted, selected and tested on, carried by every checkpoint."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": CHECKPOINT_SCHEMA,
        "model_schema": MODEL_SCHEMA,
        "arch": model.arch,
        "model_state": {k: v.detach().cpu() for k, v in model.state_dict().items()},
        "config": config,
        "encoder": encoder_identity(),
        "epoch": epoch,
        "selection": selection,
        "baselines": baselines,
        "calibration": calibration,
        "split": split,
        "population": population,
        "metrics": metrics,
    }
    tmp = path.with_name(path.name + ".tmp")
    torch.save(payload, tmp)
    os.replace(tmp, path)


def load_checkpoint(path: str | os.PathLike, device: torch.device) -> tuple[ValuePriorNet, dict]:
    payload = torch.load(path, map_location="cpu", weights_only=False)
    if payload.get("schema") != CHECKPOINT_SCHEMA:
        raise TrainError(f"{path}: not a {CHECKPOINT_SCHEMA} checkpoint")
    enc = payload.get("encoder") or {}
    ident = encoder_identity()
    if enc.get("implementation_sha256") != ident["implementation_sha256"]:
        raise TrainError(f"{path}: checkpoint encoder {enc.get('implementation_sha256', '')[:12]} "
                         f"differs from the current encoder {ident['implementation_sha256'][:12]}")
    model = ValuePriorNet(payload["arch"])
    model.load_state_dict(payload["model_state"])
    model.to(device)
    return model, payload


# ---------------------------------------------------------------- identity

def _git(args: list[str]) -> str | None:
    try:
        return subprocess.run(["git", *args], cwd=SERVER.parent, check=True,
                              capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def git_identity() -> dict:
    return {"sha": _git(["rev-parse", "HEAD"]),
            "dirty": bool(_git(["status", "--porcelain", "--untracked-files=no"]))}


def versions() -> dict:
    return {"python": platform.python_version(), "torch": torch.__version__,
            "numpy": np.__version__, "platform": platform.platform(),
            "host": platform.node()}


def peak_memory(device: torch.device) -> dict:
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    out = {"peak_rss_bytes": int(rss) if sys.platform == "darwin" else int(rss) * 1024}
    if device.type == "mps" and hasattr(torch, "mps"):
        try:
            out["mps_driver_allocated_bytes"] = int(torch.mps.driver_allocated_memory())
            out["mps_current_allocated_bytes"] = int(torch.mps.current_allocated_memory())
        except (RuntimeError, AttributeError):
            pass
    return out


def residency_receipt(residency: Residency, *, decoded_bytes: int, luna_bytes: int = 0) -> dict:
    """The residency block of a receipt: the budget, the corpus's decoded
    size (what an all-resident run would hold) and what was resident."""
    total = physical_memory_bytes()
    return {
        **residency.describe(),
        "physical_memory_bytes": total,
        "budget_fraction_of_physical": (None if not total or residency.budget is None
                                        else round(residency.budget / total, 4)),
        "decoded_bytes_data": int(decoded_bytes),
        "decoded_bytes_luna": int(luna_bytes),
        "all_resident_bytes": int(decoded_bytes) + int(luna_bytes),
        "contract": ("at most budget_bytes of decoded blocks resident at any time (LRU); "
                     "batches gathered from the resident window; None = unbounded"),
    }


def config_sha256(config: dict) -> str:
    return hashlib.sha256(canonical_json(config).encode("ascii")).hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _resident_budget(resident_bytes: int | None) -> int:
    budget = default_resident_bytes() if resident_bytes is None else int(resident_bytes)
    if budget <= 0:
        raise TrainError("--resident-bytes must be positive")
    return budget


# ------------------------------------------------------------------- train

def build_config(*, data: list[str], eval_luna: str | None = None,
                 epochs: int = DEFAULTS["epochs"], seed: int = DEFAULTS["seed"],
                 prior_target: str = DEFAULTS["prior_target"],
                 limit_clusters: int | None = None,
                 prior_weight: float = DEFAULTS["prior_weight"], lr: float = DEFAULTS["lr"],
                 weight_decay: float = DEFAULTS["weight_decay"],
                 batch_size: int = DEFAULTS["batch_size"],
                 patience: int = DEFAULTS["patience"],
                 val_fraction: float = DEFAULTS["val_fraction"],
                 test_fraction: float = DEFAULTS["test_fraction"],
                 huber_delta: float = DEFAULTS["huber_delta"], aux_points: bool = False,
                 aux_weight: float = DEFAULTS["aux_weight"],
                 aux_search_mean: float = DEFAULTS["aux_search_mean"],
                 hidden: int = DEFAULTS["hidden"], n_boot: int = DEFAULTS["n_boot"],
                 window: int = DEFAULTS["window"]) -> dict:
    """The run configuration that ``config_sha256`` hashes: everything that
    determines the trained model and its metrics (validated, fail closed);
    execution details (device, cache workers, residency budget, output
    paths, privacy witness density) are not in it."""
    if prior_target not in PRIOR_TARGETS:
        raise TrainError(f"prior target must be one of {PRIOR_TARGETS}")
    if epochs < 1 or batch_size < 1 or patience < 0:
        raise TrainError("epochs/batch_size >= 1 and patience >= 0 are required")
    if not (float(aux_search_mean) >= 0 and math.isfinite(float(aux_search_mean))):
        raise TrainError("--aux-search-mean must be a finite weight >= 0")
    for name, frac in (("val_fraction", val_fraction), ("test_fraction", test_fraction)):
        if not (0.0 < float(frac) < 1.0):
            raise TrainError(f"--{name.replace('_', '-')} must be in (0, 1): the run needs "
                             "a validation split for selection and a test split to report")
    if float(val_fraction) + float(test_fraction) >= 1.0:
        raise TrainError("--val-fraction + --test-fraction must leave a training split")
    try:
        trunk = trunk_for(hidden)
    except (TypeError, ValueError) as exc:
        raise TrainError(f"--hidden: {exc}") from exc
    arch = {**DEFAULT_ARCH, "trunk": trunk, "aux_points": bool(aux_points),
            "aux_search_mean": float(aux_search_mean) > 0}
    return {
        "command": "train", "data": [str(Path(d).resolve()) for d in data],
        "eval_luna": None if eval_luna is None else str(Path(eval_luna).resolve()),
        "epochs": int(epochs), "seed": int(seed), "prior_target": prior_target,
        "limit_clusters": limit_clusters, "prior_weight": float(prior_weight),
        "lr": float(lr), "weight_decay": float(weight_decay), "batch_size": int(batch_size),
        "patience": int(patience), "val_fraction": float(val_fraction),
        "test_fraction": float(test_fraction),
        "huber_delta": float(huber_delta), "aux_points": bool(aux_points),
        "aux_weight": float(aux_weight) if aux_points else 0.0,
        "aux_search_mean": float(aux_search_mean), "hidden": int(hidden),
        "n_boot": int(n_boot), "window": int(window), "optimizer": "AdamW", "arch": arch,
        "split_method": "three-way by deal_key: rank of sha256(seed|deal_key); "
                        "top test_fraction -> test, next val_fraction -> val, rest train",
        "encoder_implementation_sha256": encoder_identity()["implementation_sha256"],
        "enc_version": encoder_identity()["enc_version"],
    }


def train(*, data: list[str], out: str | os.PathLike, eval_luna: str | None = None,
          device: str | None = None, epochs: int = DEFAULTS["epochs"],
          seed: int = DEFAULTS["seed"], prior_target: str = DEFAULTS["prior_target"],
          limit_clusters: int | None = None, prior_weight: float = DEFAULTS["prior_weight"],
          lr: float = DEFAULTS["lr"], weight_decay: float = DEFAULTS["weight_decay"],
          batch_size: int = DEFAULTS["batch_size"], patience: int = DEFAULTS["patience"],
          val_fraction: float = DEFAULTS["val_fraction"],
          test_fraction: float = DEFAULTS["test_fraction"],
          huber_delta: float = DEFAULTS["huber_delta"], aux_points: bool = False,
          aux_weight: float = DEFAULTS["aux_weight"],
          aux_search_mean: float = DEFAULTS["aux_search_mean"],
          hidden: int = DEFAULTS["hidden"], n_boot: int = DEFAULTS["n_boot"],
          window: int = DEFAULTS["window"], cache_dir: str | None = None,
          cache_workers: int | None = None, resident_bytes: int | None = None,
          privacy_witness_every: int = 1, allow_sampled_privacy_witness: bool = False,
          argv: list[str] | None = None,
          log: Callable[[str], None] | None = print) -> dict:
    """Run the training pipeline; returns the receipt (also written)."""
    config = build_config(
        data=data, eval_luna=eval_luna, epochs=epochs, seed=seed, prior_target=prior_target,
        limit_clusters=limit_clusters, prior_weight=prior_weight, lr=lr,
        weight_decay=weight_decay, batch_size=batch_size, patience=patience,
        val_fraction=val_fraction, test_fraction=test_fraction, huber_delta=huber_delta,
        aux_points=aux_points, aux_weight=aux_weight, aux_search_mean=aux_search_mean,
        hidden=hidden, n_boot=n_boot, window=window)
    arch = config["arch"]
    search_weight = float(config["aux_search_mean"])
    try:
        witness_every = check_witness_every(privacy_witness_every, allow_sampled_privacy_witness)
    except TrainDataError as exc:
        raise TrainError(str(exc)) from exc
    budget = _resident_budget(resident_bytes)
    started = time.perf_counter()
    started_at = time.strftime("%Y-%m-%d %H:%M:%S")
    out_dir = Path(out)
    out_dir.mkdir(parents=True, exist_ok=True)
    cache = Path(cache_dir) if cache_dir else out_dir / "cache"
    workers = default_cache_workers() if cache_workers is None else max(1, int(cache_workers))
    dev = pick_device(device)
    seeds = seed_everything(seed, dev)
    say = log or (lambda _s: None)
    say(f"train: device={dev.type} seed={seed} prior_target={prior_target} "
        f"epochs<={epochs} batch={batch_size} hidden={config['hidden']} "
        f"aux_search_mean={search_weight} cache_workers={workers} "
        f"privacy_witness_every={witness_every} resident_bytes={budget}")

    residency = Residency(budget)
    prepared = prepare_stores(data, cache, limit_clusters=limit_clusters,
                              witness_seed=seed, progress=say, cache_workers=workers,
                              residency=residency, witness_every=witness_every,
                              allow_sampled_witness=allow_sampled_privacy_witness)
    store = prepared.block_store
    say(f"residency: {len(store)} shard(s) decode to {store.nbytes} bytes; budget {budget} "
        f"({'fits' if store.nbytes <= budget else 'streams through the LRU'})")
    assignment = split_deals(store.keys(), seed=seed, val_fraction=val_fraction,
                             test_fraction=test_fraction)
    masks = {part: (lambda b, p=part: split_mask(b, assignment, p)) for part in ("train", "val", "test")}
    n_rows = {part: 0 for part in masks}
    for block in store.iter_blocks():
        for part, fn in masks.items():
            n_rows[part] += int(fn(block).sum())
    deals = split_counts(assignment)
    split = {
        "method": config["split_method"],
        "seed": int(seed), "val_fraction": float(val_fraction),
        "test_fraction": float(test_fraction),
        "train_deals": deals["train"], "val_deals": deals["val"], "test_deals": deals["test"],
        "train_records": n_rows["train"], "val_records": n_rows["val"],
        "test_records": n_rows["test"],
        "roles": {name: SPLIT_ROLES[name]["role"] for name in ("train", "val", "test")},
    }
    if any(n == 0 for n in n_rows.values()):
        raise TrainError(f"split has {n_rows['train']} train / {n_rows['val']} val / "
                         f"{n_rows['test']} test records over {len(assignment)} deals; "
                         "need all three (at least three deals)")
    say(f"split: deals train={deals['train']} val={deals['val']} test={deals['test']} "
        f"records train={n_rows['train']} val={n_rows['val']} test={n_rows['test']}")
    population = fit_population(assignment, stores=prepared.stores)
    baselines = fit_baselines(store, masks["train"])
    say(f"baselines: stratified cells={len(baselines['stratified_prior']['cells'])} "
        f"empty={baselines['stratified_prior']['empty_cells']} "
        f"incumbent_eps softmax={baselines['incumbent']['softmax']['eps']} "
        f"final={baselines['incumbent']['final']['eps']}")

    luna: tuple[Store, BlockStore] | None = None
    luna_prepared = None
    if eval_luna is not None:
        luna_prepared = prepare_stores([eval_luna], cache, limit_clusters=None,
                                       witness_seed=seed, progress=say, cache_workers=workers,
                                       residency=residency, witness_every=witness_every,
                                       allow_sampled_witness=allow_sampled_privacy_witness)
        refuse_overlap(store, luna_prepared.block_store, label=f"--eval-luna {eval_luna}")
        luna_population = population_report(luna_prepared.block_store.keys(), population)
        luna = (luna_prepared.stores[0], luna_prepared.block_store)
        say(f"luna: {luna_prepared.counts['records_total']} rows over "
            f"{luna_prepared.counts['deals_total']} deals, none shared with the data stores")

    model = ValuePriorNet(arch).to(dev)
    optim = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=weight_decay)
    rng = np.random.default_rng(seed)
    epoch_rows: list[dict] = []
    best = {"epoch": None, "loss": math.inf}
    since_best = 0
    ckpt_dir = out_dir / "checkpoints"
    ckpt_dir.mkdir(parents=True, exist_ok=True)
    eval_kw = dict(prior_target=prior_target, prior_weight=prior_weight,
                   batch_size=batch_size, huber_delta=huber_delta)
    selection = {"split": SELECTION_SPLIT, "criterion": SELECTION_CRITERION,
                 "patience": int(patience)}
    for epoch in range(1, epochs + 1):
        t0 = time.perf_counter()
        model.train()
        sums = {"total": 0.0, "value": 0.0, "prior": 0.0, "aux": 0.0, "search": 0.0}
        rows = 0
        prior_rows = 0
        search_rows = 0
        batches = 0
        for raw in store.iter_batches(masks["train"], batch_size, rng=rng, window=window):
            t = to_tensors(raw, dev, prior_target)
            losses = batch_losses(model, t, prior_weight=prior_weight,
                                  aux_weight=aux_weight if aux_points else 0.0,
                                  search_weight=search_weight, huber_delta=huber_delta)
            optim.zero_grad(set_to_none=True)
            losses["total"].backward()
            optim.step()
            b = int(t["obs"].shape[0])
            npr = int(losses["n_prior"].item())
            sums["total"] += float(losses["total"].item()) * b
            sums["value"] += float(losses["value"].item()) * b
            sums["prior"] += float(losses["prior"].item()) * npr
            if "aux" in losses:
                sums["aux"] += float(losses["aux"].item()) * b
            if "search" in losses:
                nsr = int(losses["n_search"].item())
                sums["search"] += float(losses["search"].item()) * nsr
                search_rows += nsr
            rows += b
            prior_rows += npr
            batches += 1
        train_metrics = {
            "loss": sums["total"] / max(rows, 1), "value_huber": sums["value"] / max(rows, 1),
            "prior_ce": (sums["prior"] / prior_rows) if prior_rows else None,
            "rows": rows, "prior_rows": prior_rows, "batches": batches,
        }
        if aux_points:
            train_metrics["aux_huber"] = sums["aux"] / max(rows, 1)
        if search_weight > 0:
            train_metrics["aux_search_huber"] = ((sums["search"] / search_rows)
                                                 if search_rows else None)
            train_metrics["aux_search_rows"] = search_rows
        val_metrics = quick_metrics(run_eval(model, store, masks["val"], dev, **eval_kw),
                                    prior_weight=prior_weight)
        secs = round(time.perf_counter() - t0, 3)
        epoch_rows.append({"epoch": epoch, "train": train_metrics, "val": val_metrics,
                           "val_role": SPLIT_ROLES["val"]["role"], "secs": secs})
        save_checkpoint(ckpt_dir / f"epoch-{epoch:02d}.pt", model, config=config, epoch=epoch,
                        selection={**selection, "val": val_metrics}, baselines=baselines,
                        calibration=None, split=split, population=population)
        improved = val_metrics["loss"] is not None and val_metrics["loss"] < best["loss"]
        if improved:
            best = {"epoch": epoch, "loss": float(val_metrics["loss"])}
            since_best = 0
            shutil.copyfile(ckpt_dir / f"epoch-{epoch:02d}.pt", out_dir / "best.pt")
        else:
            since_best += 1
        aux_note = ("" if val_metrics.get("aux_search_mae") is None
                    else f"val_aux_search_mae={val_metrics['aux_search_mae']:.2f} ")
        say(f"epoch {epoch:02d}/{epochs} train_loss={train_metrics['loss']:.4f} "
            f"val_loss={val_metrics['loss']:.4f} val_value_mae={val_metrics['value_mae']:.4f} "
            f"val_prior_ce={val_metrics['prior_ce'] if val_metrics['prior_ce'] is None else round(val_metrics['prior_ce'], 4)} "
            f"top1={val_metrics['top1_agreement'] if val_metrics['top1_agreement'] is None else round(val_metrics['top1_agreement'], 4)} "
            f"{aux_note}{'*' if improved else ''} ({secs}s) [val = tuning]")
        if since_best >= patience and epoch < epochs:
            say(f"early stop: no validation improvement for {patience} epochs "
                f"(best epoch {best['epoch']})")
            break

    # final evaluation with the best checkpoint: calibration fitted on the
    # validation split, the reported numbers from the TEST split
    model, _payload = load_checkpoint(out_dir / "best.pt", dev)
    ev_val = run_eval(model, store, masks["val"], dev, **eval_kw)
    calibration = fit_affine(ev_val["pred"], ev_val["utility"])
    calibration["fitted_on"] = SELECTION_SPLIT
    metric_kw = dict(prior_target=prior_target, prior_weight=prior_weight, n_boot=n_boot,
                     seed=seed, calibration=calibration)
    ev_test = run_eval(model, store, masks["test"], dev, **eval_kw)
    final = {
        "test": labelled("test", full_metrics(ev_test, baselines, **metric_kw)),
        "val": labelled("val", full_metrics(ev_val, baselines, calibration_in_sample=True,
                                            **metric_kw)),
    }
    final["test"]["population"] = population_report(population["test"], population)
    final["val"]["population"] = population_report(population["val"], population)
    luna_receipt = None
    if luna is not None:
        luna_store, luna_blocks = luna
        ev_luna = run_eval(model, luna_blocks, lambda b: np.ones(b.n, dtype=bool), dev,
                           **eval_kw)
        final["luna"] = labelled("luna", full_metrics(ev_luna, baselines, **metric_kw))
        final["luna"]["population"] = luna_population
        final["luna"]["prior_target_note"] = (
            "Luna rows carry no search evidence: only the final (played-action) "
            "target is derivable; the softmax block is empty by construction")
        luna_receipt = {**luna_store.describe(), "counts": luna_prepared.counts,
                        "cache": luna_prepared.cache_files,
                        "shared_deals_with_training": int(luna_population["shared_with_fit"]
                                                          + luna_population["shared_with_selection"]),
                        "shared_with_test": int(luna_population["in_test"]),
                        "population": luna_population,
                        "checked_against": dict(population["digest"])}
    selection = {**selection, "best_epoch": best["epoch"], "best_loss": best["loss"]}
    save_checkpoint(out_dir / "best.pt", model, config=config, epoch=best["epoch"],
                    selection=selection, baselines=baselines, calibration=calibration,
                    split=split, population=population, metrics=final)
    wall = round(time.perf_counter() - started, 3)
    receipt = {
        "schema": RECEIPT_SCHEMA,
        "command": "train",
        "argv": list(argv) if argv is not None else None,
        "started": started_at,
        "wall_secs": wall,
        "device": dev.type,
        "versions": versions(),
        "git": git_identity(),
        "encoder": encoder_identity(),
        "config": config,
        "config_sha256": config_sha256(config),
        "seeds": seeds,
        "data": [{**s.describe(), "cache": [c for c in prepared.cache_files
                                            if any(c["shard_sha256"] == sh.sha256
                                                   for sh in s.shards)]}
                 for s in prepared.stores],
        "luna": luna_receipt,
        "counts": prepared.counts,
        "split": split,
        "population": population,
        "headline": HEADLINE,
        "selection": selection,
        "baselines": baselines,
        "epochs": epoch_rows,
        "best_epoch": best["epoch"],
        "stopped_early": len(epoch_rows) < epochs,
        "final": final,
        "calibration": calibration,
        "checkpoints": {"best": str(out_dir / "best.pt"),
                        "epochs": [str(ckpt_dir / f"epoch-{r['epoch']:02d}.pt")
                                   for r in epoch_rows]},
        "privacy_witness": {"every": witness_every, "sampled": witness_every != 1,
                            "allowed_sampled": bool(allow_sampled_privacy_witness),
                            "trials_per_row": int(PRIVACY_TRIALS)},
        "residency": residency_receipt(
            residency, decoded_bytes=prepared.counts["decoded_bytes"],
            luna_bytes=0 if luna_prepared is None else luna_prepared.counts["decoded_bytes"]),
        "peak_memory": peak_memory(dev),
        "cache_dir": str(cache),
        "cache_workers": workers,
    }
    check_receipt(receipt)
    _write_json(out_dir / "receipt.json", receipt)
    _write_json(out_dir / "metrics.json", {"schema": RECEIPT_SCHEMA + "-metrics",
                                           "epochs": epoch_rows, "final": final,
                                           "headline": HEADLINE, "selection": selection,
                                           "baselines": baselines,
                                           "calibration": calibration,
                                           "best_epoch": best["epoch"]})
    v = final["test"]["value"]
    aux = final["test"].get("aux_search_mean")
    tv = final["val"]["value"]
    say(f"final: TEST n={v['n']} model_mae={v['model']['mae']:.4f} "
        f"prior_mae={v['stratified_prior']['mae']:.4f} "
        f"diff={v['paired_diff_model_minus_prior']['abs_error']['mean']:.4f} "
        f"ci95={[round(x, 4) for x in v['paired_diff_model_minus_prior']['abs_error']['ci95']]} "
        + ("" if aux is None else f"aux_search_mae={aux['model']['mae']:.2f} "
                                  f"(prior {aux['stratified_prior']['mae']:.2f}) ")
        + f"| val (tuning) model_mae={tv['model']['mae']:.4f} | wall={wall}s")
    return receipt


# ---------------------------------------------------------------- evaluate

def evaluate(*, checkpoint: str, out: str | os.PathLike, data: list[str] | None = None,
             eval_luna: str | None = None, device: str | None = None, split: str = "test",
             limit_clusters: int | None = None, n_boot: int | None = None,
             batch_size: int | None = None, cache_dir: str | None = None,
             cache_workers: int | None = None, resident_bytes: int | None = None,
             privacy_witness_every: int = 1, allow_sampled_privacy_witness: bool = False,
             argv: list[str] | None = None,
             log: Callable[[str], None] | None = print) -> dict:
    """Score a checkpoint with its own baselines and calibration against
    populations checked against the deal identities the checkpoint was
    FITTED and SELECTED on (``population`` persisted in the checkpoint;
    a checkpoint without one is refused):

    * ``--data DIR --split test|val|train``: the rows of the store whose
      deals belong to the checkpoint's persisted part (the split is NOT
      re-derived from the store: a different store is detected and
      reported in ``split.population_match``, and a part with no rows in
      the store refuses); only ``test`` is held out;
    * ``--split novel``: the store's rows whose deals the checkpoint never
      saw (a foreign store's clean population; held out);
    * ``--split all``: every row of the store, not held out;
    * ``--eval-luna``: refused when it shares a deal with the fit or
      selection population, whether or not ``--data`` is given; its
      overlap with the test population is reported.

    Every held-out block carries its ``population`` report (zero overlap
    with fit and selection, explicitly); ``check_receipt`` refuses
    anything else."""
    if not data and not eval_luna:
        raise TrainError("evaluate needs --data DIR and/or --eval-luna PATH")
    if split not in EVAL_SPLITS:
        raise TrainError(f"--split must be one of {EVAL_SPLITS}")
    try:
        witness_every = check_witness_every(privacy_witness_every, allow_sampled_privacy_witness)
    except TrainDataError as exc:
        raise TrainError(str(exc)) from exc
    budget = _resident_budget(resident_bytes)
    started = time.perf_counter()
    started_at = time.strftime("%Y-%m-%d %H:%M:%S")
    out_dir = Path(out)
    out_dir.mkdir(parents=True, exist_ok=True)
    cache = Path(cache_dir) if cache_dir else out_dir / "cache"
    workers = default_cache_workers() if cache_workers is None else max(1, int(cache_workers))
    dev = pick_device(device)
    say = log or (lambda _s: None)
    model, payload = load_checkpoint(checkpoint, dev)
    config = payload["config"]
    if "test_fraction" not in config:
        raise TrainError(f"{checkpoint}: trained without a test split; refusing to evaluate")
    population = payload.get("population")
    sets = population_sets(population)          # refuses a checkpoint without populations
    seeds = seed_everything(int(config["seed"]), dev)
    baselines = payload["baselines"]
    calibration = payload.get("calibration")
    n_boot = int(n_boot if n_boot is not None else config["n_boot"])
    batch_size = int(batch_size if batch_size is not None else config["batch_size"])
    eval_kw = dict(prior_target=config["prior_target"], prior_weight=config["prior_weight"],
                   batch_size=batch_size, huber_delta=config["huber_delta"])
    metric_kw = dict(n_boot=n_boot, seed=int(config["seed"]), calibration=calibration,
                     prior_target=config["prior_target"], prior_weight=config["prior_weight"])
    residency = Residency(budget)
    prepare_kw = dict(witness_seed=int(config["seed"]), progress=say, cache_workers=workers,
                      residency=residency, witness_every=witness_every,
                      allow_sampled_witness=allow_sampled_privacy_witness)
    final: dict = {}
    data_receipt = []
    counts: dict = {}
    split_info = None
    decoded = 0
    fitted = (calibration or {}).get("fitted_on")
    if data:
        prepared = prepare_stores(data, cache, limit_clusters=limit_clusters, **prepare_kw)
        store = prepared.block_store
        decoded = prepared.counts["decoded_bytes"]
        data_keys = set(store.keys())
        match = population_report(data_keys, population)
        say(f"population: store deals={match['deals']} in_train={match['in_train']} "
            f"in_val={match['in_val']} in_test={match['in_test']} novel={match['novel']} "
            f"same_as_checkpoint={match['same_population']}")
        parts = {"train": sets["train"], "val": sets["val"], "test": sets["test"],
                 "novel": data_keys - sets["train"] - sets["val"] - sets["test"],
                 "all": data_keys}
        selected = parts[split] & data_keys
        if not selected:
            raise TrainError(
                f"--data {data}: no deal of the checkpoint's {split!r} population is in this "
                f"store ({match}); a foreign store's unseen deals are --split novel")
        selected_arr = np.asarray(sorted(selected), dtype=str)
        mask_fn = lambda b: np.isin(b.deal_key, selected_arr)  # noqa: E731
        ev = run_eval(model, store, mask_fn, dev, **eval_kw)
        metrics = full_metrics(ev, baselines, calibration_in_sample=(split == fitted),
                               **metric_kw)
        if split == "all":
            block = {**metrics, "split": "all", "held_out": False,
                     "role": "every row of the store (whatever part); not held out"}
        else:
            block = labelled(split, metrics)
        block["population"] = population_report(selected, population)
        final[split] = block
        data_receipt = [{**s.describe(), "cache": prepared.cache_files} for s in prepared.stores]
        counts = prepared.counts
        split_info = {"part": split, "records": int(ev["pred"].size), "deals": len(selected),
                      "population_match": match,
                      "checkpoint_population": dict(population["counts"]),
                      "seed": int(config["seed"]),
                      "val_fraction": float(config["val_fraction"]),
                      "test_fraction": float(config["test_fraction"])}
    luna_receipt = None
    luna_bytes = 0
    if eval_luna:
        luna_prepared = prepare_stores([eval_luna], cache, limit_clusters=None, **prepare_kw)
        luna_bytes = luna_prepared.counts["decoded_bytes"]
        luna_population = population_report(luna_prepared.block_store.keys(), population)
        shared = luna_population["shared_with_fit"] + luna_population["shared_with_selection"]
        if shared:
            raise TrainError(
                f"--eval-luna {eval_luna} shares {shared} deal(s) with the checkpoint's "
                f"fit/selection population (train {luna_population['shared_with_fit']}, val "
                f"{luna_population['shared_with_selection']}): not held out; refusing")
        say(f"luna: {luna_prepared.counts['records_total']} rows over "
            f"{luna_population['deals']} deals; shared with fit/selection 0, with the "
            f"checkpoint's test population {luna_population['in_test']}")
        ev = run_eval(model, luna_prepared.block_store, lambda b: np.ones(b.n, dtype=bool),
                      dev, **eval_kw)
        final["luna"] = labelled("luna", full_metrics(ev, baselines, **metric_kw))
        final["luna"]["population"] = luna_population
        luna_receipt = {**luna_prepared.stores[0].describe(), "counts": luna_prepared.counts,
                        "cache": luna_prepared.cache_files,
                        "shared_deals_with_training": int(shared),
                        "shared_with_test": int(luna_population["in_test"]),
                        "population": luna_population,
                        "checked_against": dict(population["digest"])}
    wall = round(time.perf_counter() - started, 3)
    headline = next((name for name in ("test", "novel", "luna")
                     if name in final and final[name].get("held_out")), None)
    receipt = {
        "schema": RECEIPT_SCHEMA,
        "command": "evaluate",
        "argv": list(argv) if argv is not None else None,
        "started": started_at,
        "wall_secs": wall,
        "device": dev.type,
        "versions": versions(),
        "git": git_identity(),
        "encoder": encoder_identity(),
        "checkpoint": {"path": str(Path(checkpoint).resolve()), "epoch": payload.get("epoch"),
                       "config_sha256": config_sha256(config)},
        "config": config,
        "config_sha256": config_sha256(config),
        "seeds": seeds,
        "data": data_receipt,
        "luna": luna_receipt,
        "counts": counts,
        "split": split_info,
        "population": population,
        "headline": headline,
        "selection": payload.get("selection"),
        "baselines": baselines,
        "epochs": [],
        "final": final,
        "calibration": calibration,
        "checkpoints": {"evaluated": str(Path(checkpoint).resolve())},
        "privacy_witness": {"every": witness_every, "sampled": witness_every != 1,
                            "allowed_sampled": bool(allow_sampled_privacy_witness)},
        "residency": residency_receipt(residency, decoded_bytes=decoded, luna_bytes=luna_bytes),
        "peak_memory": peak_memory(dev),
        "cache_dir": str(cache),
        "cache_workers": workers,
    }
    check_receipt(receipt)
    _write_json(out_dir / "receipt.json", receipt)
    _write_json(out_dir / "metrics.json", {"schema": RECEIPT_SCHEMA + "-metrics",
                                           "final": final, "headline": headline,
                                           "baselines": baselines,
                                           "calibration": calibration})
    for name, m in final.items():
        if "value" in m:
            say(f"evaluate {name}{'' if m.get('held_out') else ' (not held out)'}: "
                f"n={m['value']['n']} model_mae={m['value']['model']['mae']:.4f} "
                f"prior_mae={m['value']['stratified_prior']['mae']:.4f}")
    return receipt


# --------------------------------------------------------------------- CLI

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="train_v0", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--out", required=True, help="output directory")
        p.add_argument("--device", default=None, help="mps|cpu (default: mps when available)")
        p.add_argument("--cache-dir", default=None,
                       help="derived encoding cache (default: <out>/cache)")
        p.add_argument("--cache-workers", type=int, default=None,
                       help="shards encoded at a time when building the cache "
                            f"(default: min({CACHE_WORKERS_CAP}, cpu) = "
                            f"{default_cache_workers()})")
        p.add_argument("--resident-bytes", type=int, default=None,
                       help="residency budget: decoded shard blocks held in memory at "
                            "any time, LRU-evicted past it (default: 40%% of physical "
                            f"memory = {default_resident_bytes()})")
        p.add_argument("--privacy-witness-every", type=int, default=1, metavar="N",
                       help="run the privacy witness on every N-th encoded row "
                            "(default 1 = every row; N > 1 needs "
                            "--allow-sampled-privacy-witness)")
        p.add_argument("--allow-sampled-privacy-witness", action="store_true",
                       help="permit --privacy-witness-every N > 1 (recorded in the receipt)")
        p.add_argument("--limit-clusters", type=int, default=None,
                       help="use only the first N deals of each data store")
        p.add_argument("--eval-luna", default=None,
                       help="Luna private split (evaluation only; must share no deal "
                            "with --data)")

    t = sub.add_parser("train", help="train model v0")
    common(t)
    t.add_argument("--data", action="append", required=True,
                   help="shard store / merged store directory (repeatable)")
    t.add_argument("--epochs", type=int, default=DEFAULTS["epochs"])
    t.add_argument("--seed", type=int, default=DEFAULTS["seed"])
    t.add_argument("--prior-target", choices=PRIOR_TARGETS, default=DEFAULTS["prior_target"])
    t.add_argument("--prior-weight", type=float, default=DEFAULTS["prior_weight"])
    t.add_argument("--lr", type=float, default=DEFAULTS["lr"])
    t.add_argument("--weight-decay", type=float, default=DEFAULTS["weight_decay"])
    t.add_argument("--batch-size", type=int, default=DEFAULTS["batch_size"])
    t.add_argument("--patience", type=int, default=DEFAULTS["patience"])
    t.add_argument("--val-fraction", type=float, default=DEFAULTS["val_fraction"],
                   help="share of deals for epoch selection + calibration (tuning)")
    t.add_argument("--test-fraction", type=float, default=DEFAULTS["test_fraction"],
                   help="share of deals held out for the reported metrics")
    t.add_argument("--huber-delta", type=float, default=DEFAULTS["huber_delta"])
    t.add_argument("--aux-points", action="store_true",
                   help="auxiliary attacker-points head (off by default)")
    t.add_argument("--aux-weight", type=float, default=DEFAULTS["aux_weight"])
    t.add_argument("--aux-search-mean", type=float, default=DEFAULTS["aux_search_mean"],
                   metavar="WEIGHT",
                   help="weight of the auxiliary search-mean head "
                        "(action_values.means[played_index]); 0 = off")
    t.add_argument("--hidden", type=int, default=DEFAULTS["hidden"],
                   help="trunk widths [N, N // 2]")
    t.add_argument("--n-boot", type=int, default=DEFAULTS["n_boot"])
    t.add_argument("--window", type=int, default=DEFAULTS["window"],
                   help="shards per shuffle window (also bounded by --resident-bytes)")

    e = sub.add_parser("evaluate", help="score a checkpoint")
    common(e)
    e.add_argument("--checkpoint", required=True)
    e.add_argument("--data", action="append", default=None)
    e.add_argument("--split", choices=EVAL_SPLITS, default="test",
                   help="the checkpoint's persisted part of --data (test is held out), "
                        "novel = deals the checkpoint never saw (held out), all = every row")
    e.add_argument("--n-boot", type=int, default=None)
    e.add_argument("--batch-size", type=int, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    os.environ.setdefault("SHENGJI_REQUIRE_VOIDS", "1")
    args = build_parser().parse_args(argv)
    full_argv = sys.argv if argv is None else ["train_v0", *argv]

    def log(line: str) -> None:
        print(line, flush=True)            # progress survives a redirected stdout

    exec_kw = dict(cache_dir=args.cache_dir, cache_workers=args.cache_workers,
                   resident_bytes=args.resident_bytes,
                   privacy_witness_every=args.privacy_witness_every,
                   allow_sampled_privacy_witness=args.allow_sampled_privacy_witness,
                   argv=full_argv, log=log)
    try:
        if args.command == "train":
            train(data=args.data, out=args.out, eval_luna=args.eval_luna, device=args.device,
                  epochs=args.epochs, seed=args.seed, prior_target=args.prior_target,
                  limit_clusters=args.limit_clusters, prior_weight=args.prior_weight,
                  lr=args.lr, weight_decay=args.weight_decay, batch_size=args.batch_size,
                  patience=args.patience, val_fraction=args.val_fraction,
                  test_fraction=args.test_fraction, huber_delta=args.huber_delta,
                  aux_points=args.aux_points, aux_weight=args.aux_weight,
                  aux_search_mean=args.aux_search_mean, hidden=args.hidden,
                  n_boot=args.n_boot, window=args.window, **exec_kw)
        else:
            evaluate(checkpoint=args.checkpoint, out=args.out, data=args.data,
                     eval_luna=args.eval_luna, device=args.device, split=args.split,
                     limit_clusters=args.limit_clusters, n_boot=args.n_boot,
                     batch_size=args.batch_size, **exec_kw)
    except (TrainError, TrainDataError) as exc:
        print(f"REFUSING: {exc}", file=sys.stderr)
        return 2
    print(f"receipt -> {Path(args.out) / 'receipt.json'}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
