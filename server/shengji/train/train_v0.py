"""``train`` / ``evaluate`` for the v0 value/prior model (train_spec.md).

    train_v0.py train --data DIR [--data DIR ...] [--eval-luna PATH] --out DIR
        [--device mps|cpu] [--epochs 20] [--seed 1] [--prior-target softmax|final]
        [--limit-clusters N] [--prior-weight 1.0] ...
    train_v0.py evaluate --checkpoint CKPT (--data DIR | --eval-luna PATH) --out DIR

Outputs in ``--out``: ``receipt.json`` (git sha, encoder identity, data
manifests + shard hashes, config hash, seeds, split summary, per-epoch
train/val metrics, final metrics, baseline metrics, calibration),
``metrics.json``, ``checkpoints/epoch-NN.pt``, ``best.pt`` and the derived
encoding cache under ``cache/``.  Progress lines carry counts and losses
only.  Splits are by deal cluster (90/10 by cluster hash with the run
seed); Luna is evaluation only, scored against the stratified prior fitted
on the TRAINING data.
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
from typing import Any, Callable

import numpy as np
import torch

from ..harvest.schema import canonical_json
from .baselines import (StratifiedPrior, apply_affine, fit_affine, fit_incumbent_eps,
                        prior_summary, reliability_table, value_summary)
from .data import (Block, BlockStore, Store, TrainDataError, cache_path, collate,
                   discover_store, encoder_identity, ensure_cache, split_clusters,
                   split_mask)
from .model import (DEFAULT_ARCH, MODEL_SCHEMA, ValuePriorNet, batch_losses,
                    prior_cross_entropy, prior_log_probs)

RECEIPT_SCHEMA = "shengji-train-v0-receipt-v1"
CHECKPOINT_SCHEMA = "shengji-train-v0-checkpoint-v1"
PRIOR_TARGETS = ("softmax", "final")
DEFAULTS = {
    "epochs": 20, "seed": 1, "lr": 3e-4, "weight_decay": 1e-4, "batch_size": 1024,
    "patience": 3, "prior_weight": 1.0, "prior_target": "softmax", "val_fraction": 0.1,
    "huber_delta": 1.0, "aux_points": False, "aux_weight": 0.1, "n_boot": 1000,
    "window": 64, "limit_clusters": None,
}
REQUIRED_RECEIPT_FIELDS = (
    "schema", "command", "git", "encoder", "data", "config", "config_sha256", "seeds",
    "split", "counts", "epochs", "final", "baselines", "calibration", "checkpoints",
    "wall_secs", "peak_memory", "device", "versions", "argv", "started",
)
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
                   ) -> Prepared:
    """Discover, verify, encode (cache) and index every store."""
    stores: list[Store] = []
    entries: list[tuple] = []
    blocks: list[Block] = []
    counts: dict = {"shards": 0, "cache_rebuilt": 0, "cache_reused": 0}
    cache_files: list[dict] = []
    for path in paths:
        store = discover_store(path, limit_clusters=limit_clusters)
        stores.append(store)
        for shard in store.shards:
            def note(event, label=shard.label):
                if progress:
                    progress(f"cache {label}: records={event['records']} "
                             f"encoded={event['encoded']} secs={event['secs']}")
            block, rebuilt = ensure_cache(shard, cache_dir, witness_seed=witness_seed,
                                          private=store.private, progress=note)
            counts["shards"] += 1
            counts["cache_rebuilt" if rebuilt else "cache_reused"] += 1
            _merge_counts(counts, {"records": block.meta["counts"]})
            cache_files.append({"label": shard.label, "shard_sha256": shard.sha256,
                                "cache": str(cache_path(cache_dir, shard.sha256)),
                                "records": block.n, "rebuilt": rebuilt})
            entries.append((shard, str(cache_path(cache_dir, shard.sha256))))
            blocks.append(block)
            if progress:
                progress(f"shard {shard.label}: encoded={block.n} "
                         f"prior_stored={block.meta['counts']['preference']['stored']} "
                         f"prior_derived={block.meta['counts']['preference']['derived']} "
                         f"prior_missing={block.meta['counts']['preference']['missing']} "
                         f"legacy_schema={block.meta['counts'].get('legacy_schema', 0)} "
                         f"{'rebuilt' if rebuilt else 'cached'}")
        if limit_clusters is not None and store.layout != "shard-store":
            # merged/jsonl layouts: keep the first N clusters in file order
            keep: list[str] = []
            seen: set[str] = set()
            for block in blocks[-len(store.shards):]:
                for key in block.cluster:
                    if str(key) not in seen:
                        seen.add(str(key))
                        keep.append(str(key))
            keep_set = set(keep[:int(limit_clusters)])
            for i in range(len(blocks) - len(store.shards), len(blocks)):
                sel = np.flatnonzero(np.asarray([str(c) in keep_set for c in blocks[i].cluster]))
                blocks[i] = blocks[i].subset(sel)
    if not entries:
        raise TrainError("no shard to train on")
    block_store = BlockStore(entries)
    block_store.preload(blocks)
    counts["records_total"] = int(sum(b.n for b in blocks))
    counts["clusters_total"] = len(block_store.cluster_keys())
    return Prepared(stores=stores, block_store=block_store, counts=counts,
                    cache_files=cache_files)


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
    }


# --------------------------------------------------------------- baselines

def fit_baselines(store: BlockStore, mask_fn: Callable[[Block], np.ndarray]) -> dict:
    """The stratified prior and the incumbent eps, from the TRAINING rows."""
    prior = StratifiedPrior()
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
        "incumbent": {
            "softmax": fit_incumbent_eps(cat(first_soft), cat(width_soft)),
            "final": fit_incumbent_eps(cat(first_final), cat(width_final)),
        },
    }


# -------------------------------------------------------------- evaluation

@torch.no_grad()
def run_eval(model: ValuePriorNet, store: BlockStore, mask_fn: Callable[[Block], np.ndarray],
             device: torch.device, *, prior_target: str, prior_weight: float,
             batch_size: int, huber_delta: float) -> dict[str, np.ndarray]:
    """Per-record predictions and losses over the selected rows."""
    model.eval()
    out: dict[str, list] = {k: [] for k in (
        "pred", "utility", "ply", "role_attacker", "points_so_far", "cluster", "width",
        "has_softmax", "played", "ce_softmax", "nll_played", "top1", "first_softmax",
        "loss_value", "loss_prior", "has_target")}
    for block in store.iter_blocks():
        sel = np.flatnonzero(mask_fn(block))
        if not sel.size:
            continue
        sub = block.subset(sel)
        for b0 in range(0, sub.n, batch_size):
            idx = np.arange(b0, min(sub.n, b0 + batch_size))
            raw = collate(sub, idx)
            t = to_tensors(raw, device, prior_target)
            value, _aux, logits = model(t["obs"], t["cand"], t["mask"])
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
            if sub.cand_softmax.size:
                starts = sub.cand_offsets[idx]
                first[widths > 0] = sub.cand_softmax[starts[widths > 0]]
            v_loss = torch.nn.functional.huber_loss(value, t["utility"], delta=huber_delta,
                                                    reduction="none")
            out["pred"].append(value.cpu().numpy())
            out["utility"].append(raw["utility"])
            out["ply"].append(sub.ply[idx])
            out["role_attacker"].append(sub.role_attacker[idx])
            out["points_so_far"].append(sub.points_so_far[idx])
            out["cluster"].append(sub.cluster[idx])
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
    if not out["pred"]:
        return {k: np.zeros(0) for k in out}
    return {k: np.concatenate(v) for k, v in out.items()}


def quick_metrics(ev: dict[str, np.ndarray], *, prior_weight: float) -> dict:
    """Cheap per-epoch metrics (no bootstrap)."""
    n = int(ev["pred"].size)
    if n == 0:
        return {"n": 0, "loss": None}
    err = ev["pred"] - ev["utility"]
    has = ev["has_target"].astype(bool)
    wide = ev["width"] >= 2
    known = (ev["played"] >= 0) & wide
    value = float(ev["loss_value"].mean())
    prior = float(ev["loss_prior"][has].mean()) if has.any() else 0.0
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
    }


def full_metrics(ev: dict[str, np.ndarray], baselines: dict, *, prior_target: str,
                 prior_weight: float, n_boot: int, seed: int, calibration: dict | None
                 ) -> dict:
    """Held-out metrics with baselines, bootstrap CIs and calibration."""
    metrics = quick_metrics(ev, prior_weight=prior_weight)
    n = metrics["n"]
    if n == 0:
        return metrics
    prior = StratifiedPrior.from_dict(baselines["stratified_prior"])
    base_pred = prior.predict(ev["ply"], ev["role_attacker"], ev["points_so_far"])
    metrics["value"] = value_summary(ev["pred"], base_pred, ev["utility"], ev["cluster"],
                                     n_boot=n_boot, seed=seed)
    wide = ev["width"] >= 2
    has = ev["has_softmax"].astype(bool) & wide
    known = (ev["played"] >= 0) & wide
    eps = baselines["incumbent"]
    metrics["prior"] = {"training_target": prior_target}
    if has.any():
        metrics["prior"]["softmax"] = prior_summary(
            ev["ce_softmax"][has], ev["nll_played"][has], ev["top1"][has],
            ev["first_softmax"][has], ev["width"][has], ev["played"][has],
            ev["cluster"][has], incumbent_eps=eps["softmax"]["eps"], n_boot=n_boot, seed=seed)
    else:
        metrics["prior"]["softmax"] = {"n": 0}
    if known.any():
        metrics["prior"]["final"] = prior_summary(
            ev["nll_played"][known], ev["nll_played"][known], ev["top1"][known],
            (ev["played"][known] == 0).astype(np.float64), ev["width"][known],
            ev["played"][known], ev["cluster"][known],
            incumbent_eps=eps["final"]["eps"], n_boot=n_boot, seed=seed)
    else:
        metrics["prior"]["final"] = {"n": 0}
    metrics["prior"]["rows_single_candidate"] = int((~wide).sum())
    if calibration is not None:
        cal_pred = apply_affine(ev["pred"], calibration)
        metrics["calibration"] = {
            "scale": calibration["scale"], "shift": calibration["shift"],
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


# ------------------------------------------------------------- checkpoints

def save_checkpoint(path: Path, model: ValuePriorNet, *, config: dict, epoch: int,
                    val: dict, baselines: dict, calibration: dict | None,
                    split: dict, metrics: dict | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": CHECKPOINT_SCHEMA,
        "model_schema": MODEL_SCHEMA,
        "arch": model.arch,
        "model_state": {k: v.detach().cpu() for k, v in model.state_dict().items()},
        "config": config,
        "encoder": encoder_identity(),
        "epoch": epoch,
        "val": val,
        "baselines": baselines,
        "calibration": calibration,
        "split": split,
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


def config_sha256(config: dict) -> str:
    return hashlib.sha256(canonical_json(config).encode("ascii")).hexdigest()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


# ------------------------------------------------------------------- train

def train(*, data: list[str], out: str | os.PathLike, eval_luna: str | None = None,
          device: str | None = None, epochs: int = DEFAULTS["epochs"],
          seed: int = DEFAULTS["seed"], prior_target: str = DEFAULTS["prior_target"],
          limit_clusters: int | None = None, prior_weight: float = DEFAULTS["prior_weight"],
          lr: float = DEFAULTS["lr"], weight_decay: float = DEFAULTS["weight_decay"],
          batch_size: int = DEFAULTS["batch_size"], patience: int = DEFAULTS["patience"],
          val_fraction: float = DEFAULTS["val_fraction"],
          huber_delta: float = DEFAULTS["huber_delta"], aux_points: bool = False,
          aux_weight: float = DEFAULTS["aux_weight"], n_boot: int = DEFAULTS["n_boot"],
          window: int = DEFAULTS["window"], cache_dir: str | None = None,
          argv: list[str] | None = None, log: Callable[[str], None] | None = print) -> dict:
    """Run the training pipeline; returns the receipt (also written)."""
    if prior_target not in PRIOR_TARGETS:
        raise TrainError(f"prior target must be one of {PRIOR_TARGETS}")
    if epochs < 1 or batch_size < 1 or patience < 0:
        raise TrainError("epochs/batch_size >= 1 and patience >= 0 are required")
    started = time.perf_counter()
    started_at = time.strftime("%Y-%m-%d %H:%M:%S")
    out_dir = Path(out)
    out_dir.mkdir(parents=True, exist_ok=True)
    cache = Path(cache_dir) if cache_dir else out_dir / "cache"
    dev = pick_device(device)
    seeds = seed_everything(seed, dev)
    arch = {**DEFAULT_ARCH, "aux_points": bool(aux_points)}
    config = {
        "command": "train", "data": [str(Path(d).resolve()) for d in data],
        "eval_luna": None if eval_luna is None else str(Path(eval_luna).resolve()),
        "epochs": int(epochs), "seed": int(seed), "prior_target": prior_target,
        "limit_clusters": limit_clusters, "prior_weight": float(prior_weight),
        "lr": float(lr), "weight_decay": float(weight_decay), "batch_size": int(batch_size),
        "patience": int(patience), "val_fraction": float(val_fraction),
        "huber_delta": float(huber_delta), "aux_points": bool(aux_points),
        "aux_weight": float(aux_weight) if aux_points else 0.0, "n_boot": int(n_boot),
        "window": int(window), "optimizer": "AdamW", "arch": arch,
        "encoder_implementation_sha256": encoder_identity()["implementation_sha256"],
        "enc_version": encoder_identity()["enc_version"],
    }
    say = log or (lambda _s: None)
    say(f"train: device={dev.type} seed={seed} prior_target={prior_target} "
        f"epochs<={epochs} batch={batch_size}")

    prepared = prepare_stores(data, cache, limit_clusters=limit_clusters,
                              witness_seed=seed, progress=say)
    store = prepared.block_store
    assignment = split_clusters(store.cluster_keys(), seed=seed, val_fraction=val_fraction)
    train_mask = lambda b: split_mask(b, assignment, "train")  # noqa: E731
    val_mask = lambda b: split_mask(b, assignment, "val")  # noqa: E731
    n_train = int(sum(int(train_mask(b).sum()) for b in store.iter_blocks()))
    n_val = int(sum(int(val_mask(b).sum()) for b in store.iter_blocks()))
    split = {
        "method": "by deal cluster: rank of sha256(seed|cluster_key), top val_fraction held out",
        "seed": int(seed), "val_fraction": float(val_fraction),
        "train_clusters": sum(1 for v in assignment.values() if v == "train"),
        "val_clusters": sum(1 for v in assignment.values() if v == "val"),
        "train_records": n_train, "val_records": n_val,
    }
    if n_train == 0 or n_val == 0:
        raise TrainError(f"split has {n_train} train / {n_val} val records; need both")
    say(f"split: clusters train={split['train_clusters']} val={split['val_clusters']} "
        f"records train={n_train} val={n_val}")
    baselines = fit_baselines(store, train_mask)
    say(f"baselines: stratified cells={len(baselines['stratified_prior']['cells'])} "
        f"empty={baselines['stratified_prior']['empty_cells']} "
        f"incumbent_eps softmax={baselines['incumbent']['softmax']['eps']} "
        f"final={baselines['incumbent']['final']['eps']}")

    luna: tuple[Store, BlockStore] | None = None
    luna_prepared = None
    if eval_luna is not None:
        luna_prepared = prepare_stores([eval_luna], cache, limit_clusters=None,
                                       witness_seed=seed, progress=say)
        luna = (luna_prepared.stores[0], luna_prepared.block_store)

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
    for epoch in range(1, epochs + 1):
        t0 = time.perf_counter()
        model.train()
        sums = {"total": 0.0, "value": 0.0, "prior": 0.0, "aux": 0.0}
        rows = 0
        prior_rows = 0
        batches = 0
        for raw in store.iter_batches(train_mask, batch_size, rng=rng, window=window):
            t = to_tensors(raw, dev, prior_target)
            losses = batch_losses(model, t, prior_weight=prior_weight,
                                  aux_weight=aux_weight if aux_points else 0.0,
                                  huber_delta=huber_delta)
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
        val_metrics = quick_metrics(run_eval(model, store, val_mask, dev, **eval_kw),
                                    prior_weight=prior_weight)
        secs = round(time.perf_counter() - t0, 3)
        epoch_rows.append({"epoch": epoch, "train": train_metrics, "val": val_metrics,
                           "secs": secs})
        save_checkpoint(ckpt_dir / f"epoch-{epoch:02d}.pt", model, config=config, epoch=epoch,
                        val=val_metrics, baselines=baselines, calibration=None, split=split)
        improved = val_metrics["loss"] is not None and val_metrics["loss"] < best["loss"]
        if improved:
            best = {"epoch": epoch, "loss": float(val_metrics["loss"])}
            since_best = 0
            shutil.copyfile(ckpt_dir / f"epoch-{epoch:02d}.pt", out_dir / "best.pt")
        else:
            since_best += 1
        say(f"epoch {epoch:02d}/{epochs} train_loss={train_metrics['loss']:.4f} "
            f"val_loss={val_metrics['loss']:.4f} val_value_mae={val_metrics['value_mae']:.4f} "
            f"val_prior_ce={val_metrics['prior_ce'] if val_metrics['prior_ce'] is None else round(val_metrics['prior_ce'], 4)} "
            f"top1={val_metrics['top1_agreement'] if val_metrics['top1_agreement'] is None else round(val_metrics['top1_agreement'], 4)} "
            f"{'*' if improved else ''} ({secs}s)")
        if since_best >= patience and epoch < epochs:
            say(f"early stop: no validation improvement for {patience} epochs "
                f"(best epoch {best['epoch']})")
            break

    # final evaluation with the best checkpoint
    model, _payload = load_checkpoint(out_dir / "best.pt", dev)
    ev_val = run_eval(model, store, val_mask, dev, **eval_kw)
    calibration = fit_affine(ev_val["pred"], ev_val["utility"])
    calibration["fitted_on"] = "validation split"
    final = {"val": full_metrics(ev_val, baselines, prior_target=prior_target,
                                 prior_weight=prior_weight, n_boot=n_boot, seed=seed,
                                 calibration=calibration)}
    luna_receipt = None
    if luna is not None:
        luna_store, luna_blocks = luna
        ev_luna = run_eval(model, luna_blocks, lambda b: np.ones(b.n, dtype=bool), dev,
                           **eval_kw)
        final["luna"] = full_metrics(ev_luna, baselines, prior_target=prior_target,
                                     prior_weight=prior_weight, n_boot=n_boot, seed=seed,
                                     calibration=calibration)
        final["luna"]["prior_target_note"] = (
            "Luna rows carry no search evidence: only the final (played-action) "
            "target is derivable; the softmax block is empty by construction")
        luna_receipt = {**luna_store.describe(), "counts": luna_prepared.counts,
                        "cache": luna_prepared.cache_files}
    save_checkpoint(out_dir / "best.pt", model, config=config, epoch=best["epoch"],
                    val=final["val"], baselines=baselines, calibration=calibration,
                    split=split, metrics=final)
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
        "baselines": baselines,
        "epochs": epoch_rows,
        "best_epoch": best["epoch"],
        "stopped_early": len(epoch_rows) < epochs,
        "final": final,
        "calibration": calibration,
        "checkpoints": {"best": str(out_dir / "best.pt"),
                        "epochs": [str(ckpt_dir / f"epoch-{r['epoch']:02d}.pt")
                                   for r in epoch_rows]},
        "peak_memory": peak_memory(dev),
        "cache_dir": str(cache),
    }
    _write_json(out_dir / "receipt.json", receipt)
    _write_json(out_dir / "metrics.json", {"schema": RECEIPT_SCHEMA + "-metrics",
                                           "epochs": epoch_rows, "final": final,
                                           "baselines": baselines,
                                           "calibration": calibration,
                                           "best_epoch": best["epoch"]})
    v = final["val"]["value"]
    say(f"final: val n={v['n']} model_mae={v['model']['mae']:.4f} "
        f"prior_mae={v['stratified_prior']['mae']:.4f} "
        f"diff={v['paired_diff_model_minus_prior']['abs_error']['mean']:.4f} "
        f"ci95={[round(x, 4) for x in v['paired_diff_model_minus_prior']['abs_error']['ci95']]} "
        f"wall={wall}s")
    return receipt


# ---------------------------------------------------------------- evaluate

def evaluate(*, checkpoint: str, out: str | os.PathLike, data: list[str] | None = None,
             eval_luna: str | None = None, device: str | None = None, split: str = "val",
             limit_clusters: int | None = None, n_boot: int | None = None,
             batch_size: int | None = None, cache_dir: str | None = None,
             argv: list[str] | None = None, log: Callable[[str], None] | None = print) -> dict:
    """Score a checkpoint on a data store's split and/or the Luna set with
    the checkpoint's own baselines and calibration."""
    if not data and not eval_luna:
        raise TrainError("evaluate needs --data DIR and/or --eval-luna PATH")
    if split not in ("train", "val", "all"):
        raise TrainError("--split must be train, val or all")
    started = time.perf_counter()
    started_at = time.strftime("%Y-%m-%d %H:%M:%S")
    out_dir = Path(out)
    out_dir.mkdir(parents=True, exist_ok=True)
    cache = Path(cache_dir) if cache_dir else out_dir / "cache"
    dev = pick_device(device)
    say = log or (lambda _s: None)
    model, payload = load_checkpoint(checkpoint, dev)
    config = payload["config"]
    seeds = seed_everything(int(config["seed"]), dev)
    baselines = payload["baselines"]
    calibration = payload.get("calibration")
    n_boot = int(n_boot if n_boot is not None else config["n_boot"])
    batch_size = int(batch_size if batch_size is not None else config["batch_size"])
    eval_kw = dict(prior_target=config["prior_target"], prior_weight=config["prior_weight"],
                   batch_size=batch_size, huber_delta=config["huber_delta"])
    final: dict = {}
    data_receipt = []
    counts: dict = {}
    split_info = None
    if data:
        prepared = prepare_stores(data, cache, limit_clusters=limit_clusters,
                                  witness_seed=int(config["seed"]), progress=say)
        store = prepared.block_store
        assignment = split_clusters(store.cluster_keys(), seed=int(config["seed"]),
                                    val_fraction=float(config["val_fraction"]))
        if split == "all":
            mask_fn = lambda b: np.ones(b.n, dtype=bool)  # noqa: E731
        else:
            mask_fn = lambda b, part=split: split_mask(b, assignment, part)  # noqa: E731
        ev = run_eval(model, store, mask_fn, dev, **eval_kw)
        final[split] = full_metrics(ev, baselines, n_boot=n_boot, seed=int(config["seed"]),
                                    calibration=calibration, prior_target=config["prior_target"],
                                    prior_weight=config["prior_weight"])
        data_receipt = [{**s.describe(), "cache": prepared.cache_files} for s in prepared.stores]
        counts = prepared.counts
        split_info = {"part": split, "seed": int(config["seed"]),
                      "val_fraction": float(config["val_fraction"]),
                      "records": int(ev["pred"].size)}
    luna_receipt = None
    if eval_luna:
        luna_prepared = prepare_stores([eval_luna], cache, limit_clusters=None,
                                       witness_seed=int(config["seed"]), progress=say)
        ev = run_eval(model, luna_prepared.block_store, lambda b: np.ones(b.n, dtype=bool),
                      dev, **eval_kw)
        final["luna"] = full_metrics(ev, baselines, n_boot=n_boot, seed=int(config["seed"]),
                                     calibration=calibration,
                                     prior_target=config["prior_target"],
                                     prior_weight=config["prior_weight"])
        luna_receipt = {**luna_prepared.stores[0].describe(), "counts": luna_prepared.counts,
                        "cache": luna_prepared.cache_files}
    wall = round(time.perf_counter() - started, 3)
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
        "baselines": baselines,
        "epochs": [],
        "final": final,
        "calibration": calibration,
        "checkpoints": {"evaluated": str(Path(checkpoint).resolve())},
        "peak_memory": peak_memory(dev),
        "cache_dir": str(cache),
    }
    _write_json(out_dir / "receipt.json", receipt)
    _write_json(out_dir / "metrics.json", {"schema": RECEIPT_SCHEMA + "-metrics",
                                           "final": final, "baselines": baselines,
                                           "calibration": calibration})
    for name, m in final.items():
        if "value" in m:
            say(f"evaluate {name}: n={m['value']['n']} model_mae={m['value']['model']['mae']:.4f} "
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
        p.add_argument("--limit-clusters", type=int, default=None,
                       help="use only the first N deal clusters of each data store")
        p.add_argument("--eval-luna", default=None,
                       help="Luna private split (evaluation only)")

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
    t.add_argument("--val-fraction", type=float, default=DEFAULTS["val_fraction"])
    t.add_argument("--huber-delta", type=float, default=DEFAULTS["huber_delta"])
    t.add_argument("--aux-points", action="store_true",
                   help="auxiliary attacker-points head (off by default)")
    t.add_argument("--aux-weight", type=float, default=DEFAULTS["aux_weight"])
    t.add_argument("--n-boot", type=int, default=DEFAULTS["n_boot"])
    t.add_argument("--window", type=int, default=DEFAULTS["window"],
                   help="shards loaded per shuffle window (streaming)")

    e = sub.add_parser("evaluate", help="score a checkpoint")
    common(e)
    e.add_argument("--checkpoint", required=True)
    e.add_argument("--data", action="append", default=None)
    e.add_argument("--split", choices=("train", "val", "all"), default="val")
    e.add_argument("--n-boot", type=int, default=None)
    e.add_argument("--batch-size", type=int, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    os.environ.setdefault("SHENGJI_REQUIRE_VOIDS", "1")
    args = build_parser().parse_args(argv)
    full_argv = sys.argv if argv is None else ["train_v0", *argv]

    def log(line: str) -> None:
        print(line, flush=True)            # progress survives a redirected stdout

    try:
        if args.command == "train":
            train(data=args.data, out=args.out, eval_luna=args.eval_luna, device=args.device,
                  epochs=args.epochs, seed=args.seed, prior_target=args.prior_target,
                  limit_clusters=args.limit_clusters, prior_weight=args.prior_weight,
                  lr=args.lr, weight_decay=args.weight_decay, batch_size=args.batch_size,
                  patience=args.patience, val_fraction=args.val_fraction,
                  huber_delta=args.huber_delta, aux_points=args.aux_points,
                  aux_weight=args.aux_weight, n_boot=args.n_boot, window=args.window,
                  cache_dir=args.cache_dir, argv=full_argv, log=log)
        else:
            evaluate(checkpoint=args.checkpoint, out=args.out, data=args.data,
                     eval_luna=args.eval_luna, device=args.device, split=args.split,
                     limit_clusters=args.limit_clusters, n_boot=args.n_boot,
                     batch_size=args.batch_size, cache_dir=args.cache_dir, argv=full_argv,
                     log=log)
    except (TrainError, TrainDataError) as exc:
        print(f"REFUSING: {exc}", file=sys.stderr)
        return 2
    print(f"receipt -> {Path(args.out) / 'receipt.json'}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
