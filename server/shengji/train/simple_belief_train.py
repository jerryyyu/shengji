"""Deterministic, resumable trainer for the simple belief model."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import tempfile
import time
from typing import Any

import numpy as np
import torch
from torch.nn import functional as F

from .simple_belief_data import SCHEMA
from .simple_belief_features import FEATURE_DIM, FEATURE_SCHEMA
from .simple_belief_model import (
    SimpleBeliefMLP,
    masked_count_loss,
    masked_count_probabilities,
)


MODEL_SHAPE = (4, 54, 3)
CHECKPOINT_SCHEMA = "simple-belief-train-checkpoint-v1"


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _atomic_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.",
                                     suffix=".partial", delete=False) as handle:
        handle.write(data)
        temporary = Path(handle.name)
    temporary.replace(path)


def _atomic_torch(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.",
                                     suffix=".partial", delete=False) as handle:
        torch.save(payload, handle)
        temporary = Path(handle.name)
    temporary.replace(path)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_bytes())
    except (OSError, ValueError, TypeError) as exc:
        raise ValueError(f"invalid JSON file: {path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def _validate_recipe(cache: Path) -> tuple[dict[str, Any], str]:
    recipe_path = cache / "recipe.json"
    try:
        recipe_bytes = recipe_path.read_bytes()
    except OSError as exc:
        raise ValueError("cache recipe is missing") from exc
    recipe = _read_json(recipe_path)
    if recipe.get("schema") != SCHEMA:
        raise ValueError("cache recipe schema mismatch")
    if recipe.get("feature_schema") != FEATURE_SCHEMA:
        raise ValueError("cache feature schema mismatch")
    if (not isinstance(recipe.get("source_digest"), str)
            or not recipe["source_digest"]):
        raise ValueError("cache recipe source digest missing")
    deals = recipe.get("deals")
    if not isinstance(deals, list) or not deals:
        raise ValueError("cache recipe has no deals")
    keys = set()
    for descriptor in deals:
        if not isinstance(descriptor, dict):
            raise ValueError("cache deal descriptor must be an object")
        required = {"deal_key", "split", "path", "identity", "rows"}
        if not required.issubset(descriptor):
            raise ValueError("cache deal descriptor is incomplete")
        key, split, path, identity, rows = (
            descriptor["deal_key"], descriptor["split"], descriptor["path"],
            descriptor["identity"], descriptor["rows"])
        if not isinstance(key, str) or not key or key in keys:
            raise ValueError("cache deal keys must be distinct strings")
        keys.add(key)
        if split not in {"train", "dev", "check"}:
            raise ValueError("cache deal has an invalid split")
        if not isinstance(path, str) or not path or Path(path).is_absolute():
            raise ValueError("cache deal path must be relative")
        if not isinstance(identity, str) or not identity:
            raise ValueError("cache deal identity must be a string")
        if type(rows) is not int or rows < 1:
            raise ValueError("cache deal rows must be positive")
        resolved = (cache / path).resolve()
        if not resolved.is_relative_to(cache.resolve()):
            raise ValueError("cache deal path escapes cache")

    complete = _read_json(cache / "complete.json")
    if complete.get("schema") != SCHEMA:
        raise ValueError("cache completion schema mismatch")
    if (complete.get("completed_deals") != len(deals)
            or complete.get("rows") != sum(d["rows"] for d in deals)):
        raise ValueError("cache completion counts mismatch")
    return recipe, _digest(recipe_bytes)


def _scalar_string(value: np.ndarray, field: str) -> str:
    if value.shape != ():
        raise ValueError(f"cache {field} must be scalar")
    item = value.item()
    if not isinstance(item, str) or not item:
        raise ValueError(f"cache {field} must be a string scalar")
    return item


def _load_file(cache: Path, descriptor: dict[str, Any]) -> tuple[np.ndarray, ...]:
    path = (cache / descriptor["path"]).resolve()
    try:
        with np.load(path, allow_pickle=False) as saved:
            expected = {"x", "allowed", "targets", "identity", "deal_key"}
            if not expected.issubset(saved.files):
                raise ValueError("cache NPZ is missing required arrays")
            identity = _scalar_string(np.asarray(saved["identity"]), "identity")
            deal_key = _scalar_string(np.asarray(saved["deal_key"]), "deal_key")
            if (identity != descriptor["identity"]
                    or deal_key != descriptor["deal_key"]):
                raise ValueError("cache NPZ identity binding differs")
            x = np.asarray(saved["x"])
            allowed = np.asarray(saved["allowed"])
            targets = np.asarray(saved["targets"])
    except FileNotFoundError as exc:
        raise ValueError(f"cache NPZ missing: {path}") from exc
    if (x.dtype != np.dtype("float32")
            or x.shape != (descriptor["rows"], FEATURE_DIM)):
        raise ValueError("cache x dtype or shape differs from recipe")
    if (allowed.dtype != np.dtype("bool")
            or allowed.shape != (descriptor["rows"], *MODEL_SHAPE)):
        raise ValueError("cache allowed dtype or shape differs from recipe")
    if (targets.dtype != np.dtype("int64")
            or targets.shape != (descriptor["rows"], 4, 54)):
        raise ValueError("cache targets dtype or shape differs from recipe")
    if not np.isfinite(x).all() or not allowed.any(axis=-1).all():
        raise ValueError("cache contains invalid features or masks")
    if ((targets < 0) | (targets >= 3)).any():
        raise ValueError("cache targets contain an out-of-range count")
    if not np.take_along_axis(allowed, targets[..., None], axis=-1).all():
        raise ValueError("cache targets contain a forbidden count")
    return x.copy(), allowed.copy(), targets.copy()


def load_split(cache: str | Path, split: str) -> tuple[np.ndarray, ...]:
    """Validate the recipe and load exactly one declared split."""
    if split not in {"train", "dev", "check"}:
        raise ValueError("split must be train, dev, or check")
    root = Path(cache)
    recipe, _ = _validate_recipe(root)
    descriptors = [d for d in recipe["deals"] if d["split"] == split]
    if not descriptors:
        raise ValueError(f"cache has no {split} deals")
    rows = [_load_file(root, descriptor) for descriptor in descriptors]
    return tuple(np.concatenate([row[index] for row in rows], axis=0)
                 for index in range(3))


def _uncertain_count(allowed: torch.Tensor) -> int:
    return int((allowed.sum(dim=-1) > 1).sum().item())


def _probability_metrics(logits: torch.Tensor, targets: torch.Tensor,
                         allowed: torch.Tensor,
                         prior: torch.Tensor | None = None) -> dict[str, float]:
    uncertain = allowed.sum(dim=-1) > 1
    count = int(uncertain.sum().item())
    if not count:
        return {"ce": 0.0, "brier": 0.0}
    if prior is None:
        probs = masked_count_probabilities(logits, allowed)
    else:
        probs = prior.expand_as(logits).masked_fill(~allowed, 0)
        probs = probs / probs.sum(dim=-1, keepdim=True)
    selected = probs[uncertain]
    selected_targets = targets[uncertain]
    logp = selected.gather(-1, selected_targets[:, None]).squeeze(-1)
    ce = -torch.log(logp.clamp_min(torch.finfo(probs.dtype).tiny)).mean()
    one_hot = F.one_hot(selected_targets, num_classes=3).to(probs.dtype)
    brier = ((selected - one_hot).square().sum(dim=-1)).mean()
    return {"ce": float(ce.item()), "brier": float(brier.item())}


def _count_prior(targets: np.ndarray) -> torch.Tensor:
    counts = np.stack([(targets == cls).sum(axis=0) for cls in range(3)], axis=-1)
    probabilities = counts.astype(np.float32) + 1e-6
    probabilities /= probabilities.sum(axis=-1, keepdims=True)
    return torch.from_numpy(probabilities).reshape(1, 4, 54, 3)


def _evaluate(model: SimpleBeliefMLP, data: tuple[np.ndarray, ...],
              prior: torch.Tensor, batch_size: int) -> dict[str, float]:
    x, allowed, targets = data
    model.eval()
    total_cells = 0
    sums = {"ce": 0.0, "brier": 0.0,
            "uniform_ce": 0.0, "uniform_brier": 0.0,
            "prior_ce": 0.0, "prior_brier": 0.0}
    with torch.no_grad():
        for start in range(0, len(x), batch_size):
            stop = min(start + batch_size, len(x))
            tx = torch.from_numpy(x[start:stop])
            ta = torch.from_numpy(allowed[start:stop])
            tt = torch.from_numpy(targets[start:stop])
            logits = model(tx)
            n = _uncertain_count(ta)
            if not n:
                continue
            model_metrics = _probability_metrics(logits, tt, ta)
            uniform = ta.to(logits.dtype)
            uniform /= uniform.sum(dim=-1, keepdim=True)
            uniform_metrics = _probability_metrics(logits, tt, ta, uniform)
            prior_metrics = _probability_metrics(logits, tt, ta, prior)
            for key, value in model_metrics.items():
                sums[key] += value * n
            for key, value in uniform_metrics.items():
                sums[f"uniform_{key}"] += value * n
            for key, value in prior_metrics.items():
                sums[f"prior_{key}"] += value * n
            total_cells += n
    if not total_cells:
        raise ValueError("split contains no uncertain cells")
    return {key: value / total_cells for key, value in sums.items()} | {
        "uncertain_cells": total_cells}


def _load_checkpoint(path: Path, recipe_digest: str) -> dict[str, Any]:
    try:
        payload = torch.load(path, map_location="cpu", weights_only=True)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ValueError(f"invalid checkpoint: {path}") from exc
    if (not isinstance(payload, dict)
            or payload.get("schema") != CHECKPOINT_SCHEMA
            or payload.get("recipe_digest") != recipe_digest):
        raise ValueError("checkpoint schema or recipe binding differs")
    return payload


def score_split(cache: str | Path, checkpoint: str | Path, *,
                split: str = "check", batch_size: int = 256,
                threads: int = 2) -> dict[str, Any]:
    """Explicitly score a checkpoint on one split, including held-out check."""
    if type(batch_size) is not int or batch_size < 1:
        raise ValueError("batch_size must be positive")
    if type(threads) is not int or threads < 1:
        raise ValueError("threads must be positive")
    torch.set_num_threads(threads)
    root = Path(cache)
    recipe, recipe_digest = _validate_recipe(root)
    payload = _load_checkpoint(Path(checkpoint), recipe_digest)
    config = payload.get("config")
    if not isinstance(config, dict):
        raise ValueError("checkpoint configuration missing")
    model = SimpleBeliefMLP(FEATURE_DIM, width=config["width"],
                             hidden=config["hidden"])
    model.load_state_dict(payload["model"], strict=True)
    train = load_split(root, "train")
    evaluation = load_split(root, split)
    prior = _count_prior(train[2])
    metrics = _evaluate(model, evaluation, prior, batch_size)
    return {"split": split, **metrics}


def _config(*, epochs: int, threads: int, batch_size: int, lr: float,
            seed: int, width: int, hidden: int) -> dict[str, Any]:
    return {"epochs": epochs, "threads": threads, "batch_size": batch_size,
            "lr": lr, "seed": seed, "width": width, "hidden": hidden,
            "input_dim": FEATURE_DIM}


def train_simple_belief(cache: str | Path, output: str | Path, *,
                        epochs: int = 20, threads: int = 2,
                        batch_size: int = 256, lr: float = 1e-3,
                        seed: int = 0, width: int = 256,
                        hidden: int = 128, resume: bool = False) -> dict[str, Any]:
    """Train on train/dev only and atomically checkpoint after every epoch."""
    if type(epochs) is not int or epochs < 1:
        raise ValueError("epochs must be positive")
    if type(threads) is not int or threads < 1:
        raise ValueError("threads must be positive")
    if type(batch_size) is not int or batch_size < 1:
        raise ValueError("batch_size must be positive")
    if not math.isfinite(float(lr)) or lr <= 0:
        raise ValueError("lr must be positive and finite")
    if type(seed) is not int or type(width) is not int or type(hidden) is not int:
        raise ValueError("seed, width, and hidden must be integers")
    if width < 1 or hidden < 1:
        raise ValueError("width and hidden must be positive")
    torch.set_num_threads(threads)
    cache = Path(cache)
    output = Path(output)
    recipe, recipe_digest = _validate_recipe(cache)
    if not resume and output.exists() and any(output.iterdir()):
        raise ValueError("output directory is occupied; use --resume")
    # Deliberately load only train and dev in the training path.
    train = load_split(cache, "train")
    dev = load_split(cache, "dev")
    prior = _count_prior(train[2])
    config = _config(epochs=epochs, threads=threads, batch_size=batch_size,
                     lr=lr, seed=seed, width=width, hidden=hidden)
    last_path = output / "last.pt"
    best_path = output / "best.pt"
    curves_path = output / "curves.json"
    torch.manual_seed(seed)
    generator = torch.Generator(device="cpu").manual_seed(seed)
    model = SimpleBeliefMLP(FEATURE_DIM, width=width, hidden=hidden)
    optimizer = torch.optim.AdamW(model.parameters(), lr=lr)
    curves: list[dict[str, Any]] = []
    completed_epochs = 0
    best_epoch = None
    best_dev_ce = float("inf")
    cumulative_wall = 0.0
    epoch_extensions: list[dict[str, int]] = []
    if resume:
        if not last_path.exists():
            raise ValueError("resume requested but last checkpoint is missing")
        payload = _load_checkpoint(last_path, recipe_digest)
        old_config = payload.get("config")
        if not isinstance(old_config, dict):
            raise ValueError("checkpoint configuration missing")
        for key, value in config.items():
            if key != "epochs" and old_config.get(key) != value:
                raise ValueError("resume configuration differs")
        completed_epochs = payload.get("completed_epochs")
        if (type(completed_epochs) is not int or completed_epochs < 0
                or epochs < completed_epochs):
            raise ValueError("resume epoch target is behind completed epochs")
        model.load_state_dict(payload["model"], strict=True)
        optimizer.load_state_dict(payload["optimizer"])
        generator.set_state(payload["generator_state"])
        torch.set_rng_state(payload["torch_rng_state"])
        curves = payload.get("curves", [])
        best_epoch = payload.get("best_epoch")
        best_dev_ce = float(payload.get("best_dev_ce", float("inf")))
        epoch_extensions = list(payload.get("epoch_extensions", []))
        if curves:
            cumulative_wall = float(curves[-1].get("cumulative_wall_seconds", 0.0))
        prior_target = old_config.get("epochs")
        if isinstance(prior_target, int) and epochs > prior_target:
            epoch_extensions.append({"from": prior_target, "to": epochs})
        # Repair a curves file if a prior run stopped after its last checkpoint.
        _atomic_bytes(curves_path, _canonical(curves))
    for epoch in range(completed_epochs + 1, epochs + 1):
        epoch_started = time.monotonic()
        model.train()
        order = torch.randperm(len(train[0]), generator=generator)
        loss_sum = 0.0
        uncertain_sum = 0
        for start in range(0, len(order), batch_size):
            indices = order[start:start + batch_size].numpy()
            tx = torch.from_numpy(train[0][indices])
            ta = torch.from_numpy(train[1][indices])
            tt = torch.from_numpy(train[2][indices])
            optimizer.zero_grad(set_to_none=True)
            loss = masked_count_loss(model(tx), tt, ta)
            loss.backward()
            optimizer.step()
            cells = _uncertain_count(ta)
            loss_sum += float(loss.item()) * cells
            uncertain_sum += cells
        if not uncertain_sum:
            raise ValueError("train split contains no uncertain cells")
        dev_metrics = _evaluate(model, dev, prior, batch_size)
        epoch_wall = time.monotonic() - epoch_started
        cumulative_wall += epoch_wall
        curve = {"epoch": epoch, "loss": loss_sum / uncertain_sum,
                 "dev_ce": dev_metrics["ce"],
                 "dev_brier": dev_metrics["brier"],
                 "dev_uniform_ce": dev_metrics["uniform_ce"],
                 "dev_uniform_brier": dev_metrics["uniform_brier"],
                 "dev_prior_ce": dev_metrics["prior_ce"],
                 "dev_prior_brier": dev_metrics["prior_brier"],
                 "wall_seconds": epoch_wall,
                 "cumulative_wall_seconds": cumulative_wall,
                 "percent": 100.0 * epoch / epochs,
                 "eta_seconds": cumulative_wall / epoch * (epochs - epoch)}
        curves.append(curve)
        completed_epochs = epoch
        if curve["dev_ce"] < best_dev_ce:
            best_dev_ce = curve["dev_ce"]
            best_epoch = epoch
        payload = {
            "schema": CHECKPOINT_SCHEMA, "recipe_digest": recipe_digest,
            "recipe": recipe, "config": config,
            "completed_epochs": completed_epochs,
            "model": copy.deepcopy(model.state_dict()),
            "optimizer": copy.deepcopy(optimizer.state_dict()),
            "generator_state": generator.get_state(),
            "torch_rng_state": torch.get_rng_state(),
            "curves": curves, "best_epoch": best_epoch,
            "best_dev_ce": best_dev_ce,
            "epoch_extensions": epoch_extensions,
        }
        if best_epoch == epoch:
            _atomic_torch(best_path, payload)
        _atomic_torch(last_path, payload)
        _atomic_bytes(curves_path, _canonical(curves))
        print(json.dumps(curve, sort_keys=True), flush=True)
    return {"completed_epochs": completed_epochs, "best_epoch": best_epoch,
            "best_dev_ce": best_dev_ce, "curves": curves,
            "last_checkpoint": str(last_path),
            "best_checkpoint": str(best_path)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--epochs", type=int, default=20)
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--width", type=int, default=256)
    parser.add_argument("--hidden", type=int, default=128)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    result = train_simple_belief(
        args.cache, args.output, epochs=args.epochs, threads=args.threads,
        batch_size=args.batch_size, lr=args.lr, seed=args.seed,
        width=args.width, hidden=args.hidden, resume=args.resume)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
