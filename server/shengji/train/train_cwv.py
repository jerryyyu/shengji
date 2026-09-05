"""``train`` / ``evaluate`` for the complete-world value net (cwv_train_spec).

    train_cwv.py train --data DIR [--data DIR ...] [--eval-luna PATH] --out DIR
        --arch mlp|seq [--device mps|cpu] [--limit-clusters N] [--aux-points]
        [--seed N] [--public-head CKPT] [--epochs 20] [--batch-size 1024] ...
    train_cwv.py evaluate --checkpoint CKPT (--data DIR | --eval-luna PATH) --out DIR
        [--split test|novel|val|train|all] [--public-head CKPT]

What is trained
---------------
``rl.value_model.ValueNetwork`` over #214's afterstate tensors (``cwv_data``:
the record's action applied in the rebuilt COMPLETE round, encoded from the
acting seat; the world tensor sees all four hands and the burial), with the
204-class signed-level cross-entropy of ``rl.value_training``; ``--arch
mlp`` is the batched fast path (public 532 + world 270 + perspective 2 ->
[hidden, hidden // 2] -> 204), ``--arch seq`` #214's Transformer/GRU over
the public history.  ``--aux-points`` adds an auxiliary attacker-points
head on the mlp trunk (its state travels in the checkpoint metadata; the
#214 checkpoint itself is unchanged).  Checkpoints are written by
``rl.value_checkpoint.save_checkpoint`` and load through ``load_checkpoint``
/ ``value_inference.predict_round`` unchanged -- the contract with the
search consumer; the metadata carries ``arch``, the encoder identity,
``sees_hidden_hands``, the persisted deal populations and the baselines.

Splits, roles, populations, receipts
------------------------------------
Exactly ``train_v0``: three ways by deal key (train = fit; val = epoch
selection on the validation cross-entropy, tuning only; test = the
reported held-out metrics), the Luna private rows as an external held-out
set refused on any shared deal, populations persisted and checked, and
``train_v0.check_receipt`` applied to every receipt
(``shengji-cwv-receipt-v1``).

Metrics
-------
Per split: the expected PT0 signed level's MAE/MSE against the record's
utility versus the stratified phase x role x points prior (paired, deal
bootstrap) AND versus the PUBLIC head (``--public-head``, a #213
checkpoint scored at its own decision-state input) on the same rows; the
#214-scale expected level; cross-entropy and ranked probability score;
10-bin reliability tables.  On the TEST split (and any split with search
evidence) the candidate-ranking agreement with the search's per-candidate
means, for the net, the public head (afterstate, cannot see the world) and
the prior.  Plus positions/second of batched inference at batch 1,024 on
CPU (the number the search consumer sizes on).
"""

from __future__ import annotations

import argparse
import copy
import math
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import numpy as np
import torch
from torch import nn

from ..rl.douzero_micro import HISTORY_MAX_EVENTS
from ..rl.value_afterstate import OUTCOME_CLASSES, ValueAfterstateTensors
from ..rl.value_checkpoint import (
    ValueCheckpointError,
    load_checkpoint as load_value_checkpoint,
    save_checkpoint as save_value_checkpoint,
)
from ..rl.value_inference import predict_tensors
from ..rl.value_model import ValueModelConfig, ValueNetwork
from ..rl.value_training import collate_tensors
from .baselines import StratifiedPrior, cluster_bootstrap, reliability_table, value_summary
from .cwv_data import (
    LEVEL_SUPPORT,
    SEES_HIDDEN_HANDS,
    VIEW,
    CwvBlock,
    CwvBlockStore,
    Prepared,
    bridge_record,
    collate,
    cwv_encoder_identity,
    expected_levels,
    median_pt0,
    prepare_stores,
    tensors_of,
)
from .cwv_eval import (
    EvalError,
    SCORERS,
    candidate_pass,
    candidate_tensors,
    load_public_head,
    paired_agreement,
    summarize_agreement,
)
from .data import (
    Residency,
    TrainDataError,
    default_cache_workers,
    default_resident_bytes,
    encoder_identity as public_encoder_identity,
    iter_records,
    split_counts,
    split_deals,
    split_mask,
)
from .train_v0 import (
    EVAL_SPLITS,
    HEADLINE,
    SELECTION_SPLIT,
    SPLIT_ROLES,
    TrainError,
    _resident_budget,
    _write_json,
    check_receipt,
    config_sha256,
    fit_population,
    git_identity,
    labelled,
    peak_memory,
    pick_device,
    population_report,
    population_sets,
    refuse_overlap,
    residency_receipt,
    seed_everything,
    versions,
)

RECEIPT_SCHEMA = "shengji-cwv-receipt-v1"
CHECKPOINT_METADATA_SCHEMA = "shengji-cwv-checkpoint-metadata-v1"
ARCHES = ("mlp", "seq")
SEQ_KINDS = ("transformer", "gru")
SELECTION_CRITERION = ("validation cross-entropy of the 204-class signed-level head "
                       "(never the aux term)")
DEFAULTS = {
    "epochs": 20, "seed": 1, "lr": 3e-4, "weight_decay": 1e-4, "batch_size": 1024,
    "patience": 3, "val_fraction": 0.1, "test_fraction": 0.1, "hidden": 512, "dropout": 0.1,
    "aux_weight": 0.1, "n_boot": 1000, "window": 64, "seq_kind": "transformer",
    "seq_width": 64, "seq_layers": 2, "seq_heads": 4, "seq_feedforward": 128,
    "bench_batch": 1024,
}
REQUIRED_RECEIPT_FIELDS = (
    "schema", "command", "argv", "started", "wall_secs", "device", "versions", "git",
    "encoder", "sees_hidden_hands", "privacy", "view", "config", "config_sha256", "seeds",
    "data", "luna", "counts", "split", "population", "headline", "selection", "baselines",
    "epochs", "best_epoch", "stopped_early", "final", "checkpoints", "public_head",
    "ranking", "residency", "peak_memory", "cache_dir", "cache_workers",
    "inference_benchmark",
)
PRIVACY = {
    "sees_hidden_hands": SEES_HIDDEN_HANDS,
    "world_tensor": "all four seat-relative hands and the burial of the rebuilt complete "
                    "round (rl.value_afterstate.tensors_from_round), by design: the play-time "
                    "consumer feeds sampled worlds",
    "witness": "cwv_data.world_witness: permuting hidden cards among the non-acting seats "
               "must change the world tensor and leave the public tensor byte-identical "
               "(run every witness_every-th cached row; refuses otherwise)",
    "public_head_witness": "untouched: train.data.privacy_witness still guards the public "
                           "pipeline (train_v0) on every row it caches",
}


# ------------------------------------------------------------------- model

def model_config(arch: str, *, hidden: int = DEFAULTS["hidden"],
                 dropout: float = DEFAULTS["dropout"], seq_kind: str = DEFAULTS["seq_kind"],
                 seq_width: int = DEFAULTS["seq_width"], seq_layers: int = DEFAULTS["seq_layers"],
                 seq_heads: int = DEFAULTS["seq_heads"],
                 seq_feedforward: int = DEFAULTS["seq_feedforward"]) -> ValueModelConfig:
    """The #214 model configuration behind ``--arch``: ``mlp`` maps
    ``--hidden H`` onto a ``[H, H // 2]`` trunk (``feedforward_width=H``,
    ``width=H // 2``); ``seq`` is #214's history model."""
    if arch not in ARCHES:
        raise TrainError(f"--arch must be one of {ARCHES}")
    try:
        if arch == "mlp":
            return ValueModelConfig(
                architecture="mlp", width=int(hidden) // 2, history_layers=1,
                attention_heads=1, feedforward_width=int(hidden), dropout=float(dropout),
                max_history=HISTORY_MAX_EVENTS)
        if seq_kind not in SEQ_KINDS:
            raise TrainError(f"--seq-kind must be one of {SEQ_KINDS}")
        return ValueModelConfig(
            architecture=seq_kind, width=int(seq_width), history_layers=int(seq_layers),
            attention_heads=int(seq_heads), feedforward_width=int(seq_feedforward),
            dropout=float(dropout), max_history=HISTORY_MAX_EVENTS)
    except ValueError as exc:
        raise TrainError(f"model configuration: {exc}") from exc


def arch_of(config: ValueModelConfig) -> str:
    return "mlp" if config.architecture == "mlp" else "seq"


class AuxPointsHead(nn.Module):
    """Auxiliary attacker-points head on the mlp trunk (target: points / 100)."""

    def __init__(self, width: int):
        super().__init__()
        self.linear = nn.Linear(int(width), 1)

    def forward(self, features: torch.Tensor) -> torch.Tensor:
        return self.linear(features).squeeze(1)

    def payload(self) -> dict:
        return {"width": int(self.linear.in_features),
                "weight": [float(v) for v in self.linear.weight.detach().cpu().reshape(-1)],
                "bias": float(self.linear.bias.detach().cpu().item()),
                "target": "outcome attacker_points / 100"}

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "AuxPointsHead":
        head = cls(int(payload["width"]))
        with torch.no_grad():
            head.linear.weight.copy_(torch.tensor(payload["weight"], dtype=torch.float32)
                                     .reshape(1, -1))
            head.linear.bias.copy_(torch.tensor([payload["bias"]], dtype=torch.float32))
        return head


def forward_batch(model: ValueNetwork, t: Mapping[str, torch.Tensor],
                  aux_head: AuxPointsHead | None = None
                  ) -> tuple[torch.Tensor, torch.Tensor | None]:
    """``(logits, aux points / 100 or None)``; the mlp reads its trunk
    directly (the history is a placeholder there), the sequence models run
    #214's full forward."""
    if model.config.architecture == "mlp":
        features = model.features(t["public"], t["world"], t["perspective"])
        logits = model.head(features)
        aux = aux_head(features) if aux_head is not None else None
        return logits, aux
    logits = model(t["public"], t["history"], t["history_mask"], t["world"], t["perspective"])
    return logits, None


# ------------------------------------------------------------- checkpoints

def save_cwv_checkpoint(path: Path, model: ValueNetwork, *, metadata: Mapping[str, Any]) -> str:
    meta = dict(metadata)
    meta["schema"] = CHECKPOINT_METADATA_SCHEMA
    meta["arch"] = arch_of(model.config)
    meta["model_config"] = model.config.payload()
    meta["sees_hidden_hands"] = SEES_HIDDEN_HANDS
    meta["view"] = VIEW
    return save_value_checkpoint(path, model, metadata=meta)


def load_cwv_checkpoint(path: str | os.PathLike, device: torch.device | str = "cpu"
                        ) -> tuple[ValueNetwork, dict, AuxPointsHead | None]:
    """Through #214's ``load_checkpoint``; the metadata must name the
    ``arch`` consistently with the model configuration and declare
    ``sees_hidden_hands``."""
    try:
        model, metadata = load_value_checkpoint(path, map_location=device)
    except ValueCheckpointError as exc:
        raise TrainError(f"{path}: {exc}") from exc
    if metadata.get("schema") != CHECKPOINT_METADATA_SCHEMA:
        raise TrainError(f"{path}: checkpoint metadata schema "
                         f"{metadata.get('schema')!r} != {CHECKPOINT_METADATA_SCHEMA!r}")
    arch = metadata.get("arch")
    if arch not in ARCHES or arch != arch_of(model.config):
        raise TrainError(f"{path}: checkpoint metadata arch {arch!r} does not name the "
                         f"model's architecture ({model.config.architecture!r})")
    if metadata.get("model_config") != model.config.payload():
        raise TrainError(f"{path}: checkpoint metadata model_config drift")
    if metadata.get("sees_hidden_hands") is not True:
        raise TrainError(f"{path}: checkpoint does not declare sees_hidden_hands")
    enc = metadata.get("encoder") or {}
    if enc.get("implementation_sha256") != cwv_encoder_identity()["implementation_sha256"]:
        raise TrainError(f"{path}: checkpoint encoder "
                         f"{str(enc.get('implementation_sha256', ''))[:12]} differs from this "
                         f"build's {cwv_encoder_identity()['implementation_sha256'][:12]}")
    aux = None
    if metadata.get("aux_points_head"):
        aux = AuxPointsHead.from_payload(metadata["aux_points_head"]).to(device)
        aux.eval()
    model.to(device)
    model.eval()
    return model, metadata, aux


# -------------------------------------------------------------- evaluation

def _rps(prob: np.ndarray, target: np.ndarray) -> np.ndarray:
    cumulative = np.cumsum(prob, axis=1)[:, :-1]
    truth = (np.arange(OUTCOME_CLASSES - 1)[None, :] >= target[:, None]).astype(np.float64)
    return np.mean(np.square(cumulative - truth), axis=1)


@torch.no_grad()
def run_eval(model: ValueNetwork, store: CwvBlockStore,
             mask_fn: Callable[[CwvBlock], np.ndarray], device: torch.device, *,
             batch_size: int, aux_head: AuxPointsHead | None = None) -> dict[str, np.ndarray]:
    """Per-row predictions and losses over the selected rows."""
    model.eval()
    keys = ("expected_level", "expected_pt0", "median_pt0", "ce", "rps", "target",
            "target_level", "utility", "ply", "role_attacker", "points_so_far",
            "attacker_points", "deal_key", "source_ref", "aux_pred", "has_search_means")
    out: dict[str, list] = {k: [] for k in keys}
    for block in store.iter_blocks():
        sel = np.flatnonzero(mask_fn(block))
        if not sel.size:
            continue
        for b0 in range(0, sel.size, batch_size):
            idx = sel[b0:b0 + batch_size]
            raw = collate(block, idx)
            t = tensors_of(raw, device)
            logits, aux = forward_batch(model, t, aux_head)
            logp = torch.log_softmax(logits.to(torch.float32), dim=1)
            target = t["target"]
            ce = -logp.gather(1, target.unsqueeze(1)).squeeze(1)
            prob = torch.exp(logp).cpu().numpy().astype(np.float64)
            level, pt0 = expected_levels(prob)
            tgt = raw["target"].astype(np.int64)
            out["expected_level"].append(level)
            out["expected_pt0"].append(pt0)
            out["median_pt0"].append(median_pt0(prob))
            out["ce"].append(ce.cpu().numpy().astype(np.float64))
            out["rps"].append(_rps(prob, tgt))
            out["target"].append(tgt)
            out["target_level"].append(LEVEL_SUPPORT[tgt])
            out["utility"].append(raw["utility"].astype(np.float64))
            out["ply"].append(raw["ply"])
            out["role_attacker"].append(raw["role_attacker"])
            out["points_so_far"].append(raw["points_so_far"])
            out["attacker_points"].append(raw["attacker_points"].astype(np.float64))
            out["deal_key"].append(raw["deal_key"])
            out["source_ref"].append(raw["source_ref"])
            out["aux_pred"].append(np.full(len(idx), np.nan) if aux is None
                                   else aux.cpu().numpy().astype(np.float64) * 100.0)
            out["has_search_means"].append(block.has_search_means[idx])
    if not out["ce"]:
        return {k: np.zeros(0) for k in keys}
    return {k: np.concatenate(v) for k, v in out.items()}


def quick_metrics(ev: Mapping[str, np.ndarray]) -> dict:
    n = int(ev["ce"].size)
    if n == 0:
        return {"n": 0, "loss": None}
    err = ev["expected_pt0"] - ev["utility"]
    err_level = ev["expected_level"] - ev["target_level"]
    has_aux = np.isfinite(ev["aux_pred"])
    return {
        "n": n,
        "loss": float(ev["ce"].mean()),
        "cross_entropy": float(ev["ce"].mean()),
        "rps": float(ev["rps"].mean()),
        "value_mae": float(np.abs(err).mean()),
        "value_mse": float((err ** 2).mean()),
        "value_median_mae": float(np.abs(ev["median_pt0"] - ev["utility"]).mean()),
        "value_level_mae": float(np.abs(err_level).mean()),
        "aux_points_mae": (float(np.abs(ev["aux_pred"][has_aux]
                                        - ev["attacker_points"][has_aux]).mean())
                           if has_aux.any() else None),
    }


def full_metrics(ev: Mapping[str, np.ndarray], baselines: Mapping[str, Any], *, n_boot: int,
                 seed: int, public_decision: Mapping[str, float] | None = None,
                 public_note: Mapping[str, Any] | None = None) -> dict:
    """The split's metrics with baselines, deal-bootstrap CIs and reliability."""
    metrics = quick_metrics(ev)
    if metrics["n"] == 0:
        return metrics
    prior = StratifiedPrior.from_dict(baselines["stratified_prior"])
    base = prior.predict(ev["ply"], ev["role_attacker"], ev["points_so_far"])
    metrics["value"] = {
        **value_summary(ev["expected_pt0"], base, ev["utility"], ev["deal_key"],
                        n_boot=n_boot, seed=seed),
        "scale": "PT0 signed level for the acting seat's partnership "
                 "(outcome.signed_level_utility); model = expected PT0 level of the "
                 "204-class distribution",
    }
    metrics["value_median"] = {
        **value_summary(ev["median_pt0"], base, ev["utility"], ev["deal_key"],
                        n_boot=n_boot, seed=seed + 20),
        "scale": "PT0 signed level; model = MEDIAN PT0 level of the 204-class "
                 "distribution (the MAE-optimal point estimate; the expectation above "
                 "is MSE-optimal)",
    }
    err_level = ev["expected_level"] - ev["target_level"]
    metrics["value_level"] = {
        "mae": float(np.abs(err_level).mean()), "mse": float((err_level ** 2).mean()),
        "scale": "#214 half-integer signed level (category_signed_level)",
    }
    metrics["deals"] = int(np.unique(ev["deal_key"]).size)
    metrics["reliability"] = {
        "bins": 10,
        "pt0": reliability_table(ev["expected_pt0"], ev["utility"], bins=10),
        "level": reliability_table(ev["expected_level"], ev["target_level"], bins=10),
    }
    has_aux = np.isfinite(ev["aux_pred"])
    if has_aux.any():
        metrics["aux_points"] = {
            "n": int(has_aux.sum()),
            "mae_points": float(np.abs(ev["aux_pred"][has_aux]
                                       - ev["attacker_points"][has_aux]).mean()),
        }
    if public_decision is not None:
        values = np.asarray([public_decision.get(ref, math.nan) for ref in ev["source_ref"]],
                            dtype=np.float64)
        has = np.isfinite(values)
        block: dict[str, Any] = {
            "n": int(has.sum()), "rows_without_public_value": int((~has).sum()),
            "public_head_input": ("the record's DECISION state (encode_obs at the acting "
                                  "seat's turn: its own training distribution)"),
            **(dict(public_note) if public_note else {}),
        }
        if has.any():
            e_m = ev["expected_pt0"][has] - ev["utility"][has]
            e_md = ev["median_pt0"][has] - ev["utility"][has]
            e_p = values[has] - ev["utility"][has]
            block.update({
                "model": {"mae": float(np.abs(e_m).mean()), "mse": float((e_m ** 2).mean())},
                "model_median": {"mae": float(np.abs(e_md).mean()),
                                 "mse": float((e_md ** 2).mean())},
                "paired_diff_median_minus_public": {
                    "abs_error": cluster_bootstrap(np.abs(e_md) - np.abs(e_p),
                                                   ev["deal_key"][has], n_boot=n_boot,
                                                   seed=seed + 9),
                },
                "public_head": {"mae": float(np.abs(e_p).mean()),
                                "mse": float((e_p ** 2).mean())},
                "paired_diff_model_minus_public": {
                    "abs_error": cluster_bootstrap(np.abs(e_m) - np.abs(e_p),
                                                   ev["deal_key"][has], n_boot=n_boot,
                                                   seed=seed + 7),
                    "sq_error": cluster_bootstrap(e_m ** 2 - e_p ** 2, ev["deal_key"][has],
                                                  n_boot=n_boot, seed=seed + 8),
                },
            })
        metrics["public_head"] = block
    return metrics


def fit_baselines(store: CwvBlockStore, mask_fn: Callable[[CwvBlock], np.ndarray]) -> dict:
    """The stratified prior (phase x role x points so far -> mean PT0
    utility) from the TRAINING rows: ``train.baselines.StratifiedPrior``."""
    prior = StratifiedPrior()
    for block in store.iter_blocks():
        sel = np.flatnonzero(mask_fn(block))
        if sel.size:
            prior.add(block.ply[sel], block.role_attacker[sel], block.points_so_far[sel],
                      block.utility[sel])
    return {"stratified_prior": prior.to_dict(), "fitted_on": "train"}


def cwv_score_fn(model: ValueNetwork, device: torch.device) -> Callable[[dict], np.ndarray]:
    """Expected PT0 level of every candidate afterstate of one search record."""
    @torch.no_grad()
    def score(entry: dict) -> np.ndarray:
        t = candidate_tensors(entry, device)
        logits, _aux = forward_batch(model, t)
        prob = torch.softmax(logits.to(torch.float32), dim=1).cpu().numpy().astype(np.float64)
        _level, pt0 = expected_levels(prob)
        return pt0
    return score


def ranking_block(pass_result: Mapping[str, Any], *, n_boot: int, seed: int) -> dict:
    agreement = pass_result["agreement"]
    clusters = pass_result["clusters"]
    block = {
        "records": int(pass_result["search_records"]),
        "candidates": int(pass_result["candidates"]),
        "candidates_per_record": pass_result["candidates_per_record"],
        "rows_rebuilt": int(pass_result["rows"]),
        "secs": pass_result["secs"],
        "rank_limit": pass_result["rank_limit"],
        "search_means": "action_values.means over eligible_indices (acting-team "
                        "perspective, points); every candidate applied in the record's "
                        "TRUE world and scored from the acting seat's perspective",
        "scorers": {},
    }
    for name in SCORERS:
        if name in agreement:
            block["scorers"][name] = summarize_agreement(agreement[name], clusters,
                                                         n_boot=n_boot, seed=seed)
    if "cwv" in agreement:
        for other in ("public_head", "stratified_prior"):
            if other in agreement:
                block[f"paired_cwv_minus_{other}"] = paired_agreement(
                    agreement["cwv"], agreement[other], clusters, n_boot=n_boot, seed=seed)
    return block


# ---------------------------------------------------------- inference bench

def bench_rows(shard_keys: Sequence[tuple[Any, Sequence[str] | None]], n: int
               ) -> list[ValueAfterstateTensors]:
    """The first ``n`` bridged afterstate rows of the selected deals (real
    histories, as the consumer would feed)."""
    rows: list[ValueAfterstateTensors] = []
    for shard, keys in shard_keys:
        keep = None if keys is None else set(keys)
        for record in iter_records(shard):
            try:
                row = bridge_record(record)
            except TrainDataError:
                continue
            if keep is not None and row.deal_key not in keep:
                continue
            rows.append(row.tensors)
            if len(rows) >= n:
                return rows
    return rows


def bench_inference(model: ValueNetwork, rows: Sequence[ValueAfterstateTensors], *,
                    repeats: int = 5) -> dict:
    """Positions/second on CPU for one batch: the raw forward on a
    pre-collated batch (what a batched search evaluator pays per batch) and
    ``value_inference.predict_tensors`` end to end (collate + validate +
    per-row prediction objects)."""
    if not rows:
        return {"batch": 0}
    cpu = torch.device("cpu")
    bench_model = copy.deepcopy(model).to(cpu)
    bench_model.eval()
    batch = collate_tensors(list(rows))
    with torch.inference_mode():
        bench_model(batch.public, batch.history, batch.history_mask, batch.world,
                    batch.perspective)
        t0 = time.perf_counter()
        for _ in range(repeats):
            bench_model(batch.public, batch.history, batch.history_mask, batch.world,
                        batch.perspective)
        forward = (time.perf_counter() - t0) / repeats
        t0 = time.perf_counter()
        predict_tensors(bench_model, list(rows), device=cpu)
        end_to_end = time.perf_counter() - t0
    n = len(rows)
    return {
        "batch": n, "device": "cpu", "threads": int(torch.get_num_threads()),
        "arch": arch_of(model.config),
        "history_mean_events": float(np.mean([len(r.history) for r in rows])),
        "forward_ms_per_batch": round(forward * 1000.0, 3),
        "forward_positions_per_second": round(n / forward, 1),
        "predict_tensors_ms_per_batch": round(end_to_end * 1000.0, 3),
        "predict_tensors_positions_per_second": round(n / end_to_end, 1),
        "note": ("forward = ValueNetwork on a pre-collated batch (repeats averaged); "
                 "predict_tensors = value_inference end to end, dominated by its per-row "
                 "validation and prediction objects"),
    }


# ------------------------------------------------------------------ config

def build_config(*, data: Sequence[str], eval_luna: str | None = None, arch: str = "mlp",
                 epochs: int = DEFAULTS["epochs"], seed: int = DEFAULTS["seed"],
                 limit_clusters: int | None = None, lr: float = DEFAULTS["lr"],
                 weight_decay: float = DEFAULTS["weight_decay"],
                 batch_size: int = DEFAULTS["batch_size"], patience: int = DEFAULTS["patience"],
                 val_fraction: float = DEFAULTS["val_fraction"],
                 test_fraction: float = DEFAULTS["test_fraction"],
                 hidden: int = DEFAULTS["hidden"], dropout: float = DEFAULTS["dropout"],
                 aux_points: bool = False, aux_weight: float = DEFAULTS["aux_weight"],
                 n_boot: int = DEFAULTS["n_boot"], window: int = DEFAULTS["window"],
                 seq_kind: str = DEFAULTS["seq_kind"], seq_width: int = DEFAULTS["seq_width"],
                 seq_layers: int = DEFAULTS["seq_layers"], seq_heads: int = DEFAULTS["seq_heads"],
                 seq_feedforward: int = DEFAULTS["seq_feedforward"],
                 public_head: str | None = None, rank_limit: int | None = None) -> dict:
    """Everything that determines the trained model and its metrics."""
    if arch not in ARCHES:
        raise TrainError(f"--arch must be one of {ARCHES}")
    if epochs < 1 or batch_size < 1 or patience < 0:
        raise TrainError("epochs/batch_size >= 1 and patience >= 0 are required")
    for name, frac in (("val_fraction", val_fraction), ("test_fraction", test_fraction)):
        if not (0.0 < float(frac) < 1.0):
            raise TrainError(f"--{name.replace('_', '-')} must be in (0, 1)")
    if float(val_fraction) + float(test_fraction) >= 1.0:
        raise TrainError("--val-fraction + --test-fraction must leave a training split")
    if aux_points and arch != "mlp":
        raise TrainError("--aux-points reads the mlp trunk; the seq architecture exposes none")
    if not (float(aux_weight) >= 0 and math.isfinite(float(aux_weight))):
        raise TrainError("--aux-weight must be a finite weight >= 0")
    config = model_config(arch, hidden=hidden, dropout=dropout, seq_kind=seq_kind,
                          seq_width=seq_width, seq_layers=seq_layers, seq_heads=seq_heads,
                          seq_feedforward=seq_feedforward)
    identity = cwv_encoder_identity()
    return {
        "command": "train", "data": [str(Path(d).resolve()) for d in data],
        "eval_luna": None if eval_luna is None else str(Path(eval_luna).resolve()),
        "arch": arch, "model_config": config.payload(), "epochs": int(epochs),
        "seed": int(seed), "limit_clusters": limit_clusters, "lr": float(lr),
        "weight_decay": float(weight_decay), "batch_size": int(batch_size),
        "patience": int(patience), "val_fraction": float(val_fraction),
        "test_fraction": float(test_fraction), "hidden": int(hidden),
        "dropout": float(dropout), "aux_points": bool(aux_points),
        "aux_weight": float(aux_weight) if aux_points else 0.0, "n_boot": int(n_boot),
        "window": int(window), "optimizer": "AdamW", "loss": "cross-entropy over 204 classes",
        "public_head": None if public_head is None else str(Path(public_head).resolve()),
        "rank_limit": rank_limit,
        "split_method": "three-way by deal_key: rank of sha256(seed|deal_key); "
                        "top test_fraction -> test, next val_fraction -> val, rest train",
        "view": VIEW, "sees_hidden_hands": SEES_HIDDEN_HANDS,
        "encoder_implementation_sha256": identity["implementation_sha256"],
        "public_encoder_implementation_sha256": identity["public_head_encoder_sha256"],
    }


def _public_head_note(info: Mapping[str, Any] | None, *, config: Mapping[str, Any],
                      split: Mapping[str, Any]) -> dict:
    """Whether the public head's fit/selection deals are disjoint from the
    rows it is compared on (a v3 checkpoint persists them; a v2 one is
    assumed to share this run's split when data, seed, fractions, recipe
    and per-part counts all agree)."""
    if info is None:
        return {}
    same_data = list(info.get("data") or []) == list(config["data"])
    same_recipe = (info.get("seed") == config["seed"]
                   and info.get("val_fraction") == config["val_fraction"]
                   and info.get("test_fraction") == config["test_fraction"]
                   and info.get("split_method") == config["split_method"]
                   and info.get("limit_clusters") == config["limit_clusters"])
    theirs = info.get("split") or {}
    deal_counts_match = all(theirs.get(k) == split.get(k)
                            for k in ("train_deals", "val_deals", "test_deals"))
    record_counts_match = all(theirs.get(k) == split.get(k)
                              for k in ("train_records", "val_records", "test_records"))
    return {
        "public_head_checkpoint": info.get("path"),
        "public_head_schema": info.get("schema"),
        "public_head_has_population": bool(info.get("has_population")),
        "same_data_stores": same_data,
        "same_split_recipe": same_recipe,
        "same_split_deal_counts": deal_counts_match,
        "same_split_record_counts": record_counts_match,
        "held_out_for_public_head": (
            "checked against its persisted fit/selection populations (rows in them are "
            "excluded)" if info.get("has_population") else
            ("assumed: no persisted population (v2); the split recipe and deal counts "
             "agree, and split_deals is a function of (seed, deal key) alone"
             if same_recipe and deal_counts_match else
             "NOT established: no persisted population and the split recipe or deal "
             "counts differ")),
    }


def public_comparison(pass_result: Mapping[str, Any], info: Mapping[str, Any] | None
                      ) -> tuple[dict[str, float] | None, dict]:
    """The public head's decision-state values to compare on, restricted to
    the rows whose deal is outside the comparator's persisted fit and
    selection populations (when it has them), plus the check's counts."""
    if info is None:
        return None, {}
    values = dict(pass_result["decision_values"])
    keys = pass_result.get("decision_keys") or {}
    if not info.get("has_population"):
        return values, {"public_head_population_check": None,
                        "rows_compared": len(values)}
    sets = population_sets(info["population"])
    excluded = sets["train"] | sets["val"]
    kept = {ref: value for ref, value in values.items() if keys.get(ref) not in excluded}
    dropped_deals = {keys[ref] for ref in values if ref not in kept and ref in keys}
    return kept, {
        "public_head_population_check": {
            "rows_excluded_in_public_fit_or_selection": len(values) - len(kept),
            "deals_excluded": len(dropped_deals),
            "checked_against": dict(info["population"].get("digest") or {}),
        },
        "rows_compared": len(kept),
    }


# ------------------------------------------------------------------- train

def train(*, data: Sequence[str], out: str | os.PathLike, eval_luna: str | None = None,
          arch: str = "mlp", device: str | None = None, epochs: int = DEFAULTS["epochs"],
          seed: int = DEFAULTS["seed"], limit_clusters: int | None = None,
          lr: float = DEFAULTS["lr"], weight_decay: float = DEFAULTS["weight_decay"],
          batch_size: int = DEFAULTS["batch_size"], patience: int = DEFAULTS["patience"],
          val_fraction: float = DEFAULTS["val_fraction"],
          test_fraction: float = DEFAULTS["test_fraction"], hidden: int = DEFAULTS["hidden"],
          dropout: float = DEFAULTS["dropout"], aux_points: bool = False,
          aux_weight: float = DEFAULTS["aux_weight"], n_boot: int = DEFAULTS["n_boot"],
          window: int = DEFAULTS["window"], seq_kind: str = DEFAULTS["seq_kind"],
          seq_width: int = DEFAULTS["seq_width"], seq_layers: int = DEFAULTS["seq_layers"],
          seq_heads: int = DEFAULTS["seq_heads"],
          seq_feedforward: int = DEFAULTS["seq_feedforward"], public_head: str | None = None,
          rank_limit: int | None = None, cache_dir: str | None = None,
          cache_workers: int | None = None, eval_workers: int | None = None,
          resident_bytes: int | None = None, bench_batch: int = DEFAULTS["bench_batch"],
          argv: list[str] | None = None,
          log: Callable[[str], None] | None = print) -> dict:
    """Run the training pipeline; returns the receipt (also written)."""
    config = build_config(
        data=data, eval_luna=eval_luna, arch=arch, epochs=epochs, seed=seed,
        limit_clusters=limit_clusters, lr=lr, weight_decay=weight_decay,
        batch_size=batch_size, patience=patience, val_fraction=val_fraction,
        test_fraction=test_fraction, hidden=hidden, dropout=dropout, aux_points=aux_points,
        aux_weight=aux_weight, n_boot=n_boot, window=window, seq_kind=seq_kind,
        seq_width=seq_width, seq_layers=seq_layers, seq_heads=seq_heads,
        seq_feedforward=seq_feedforward, public_head=public_head, rank_limit=rank_limit)
    history = arch == "seq"
    budget = _resident_budget(resident_bytes)
    started = time.perf_counter()
    started_at = time.strftime("%Y-%m-%d %H:%M:%S")
    out_dir = Path(out)
    out_dir.mkdir(parents=True, exist_ok=True)
    cache = Path(cache_dir) if cache_dir else out_dir / "cache"
    workers = default_cache_workers() if cache_workers is None else max(1, int(cache_workers))
    eval_workers = workers if eval_workers is None else max(1, int(eval_workers))
    dev = pick_device(device)
    seeds = seed_everything(seed, dev)
    say = log or (lambda _s: None)
    say(f"train_cwv: arch={arch} device={dev.type} seed={seed} epochs<={epochs} "
        f"batch={batch_size} hidden={hidden} dropout={dropout} aux_points={aux_points} "
        f"history_cache={history} cache_workers={workers} resident_bytes={budget} "
        f"sees_hidden_hands={SEES_HIDDEN_HANDS}")

    residency = Residency(budget)
    prepared = prepare_stores(data, cache, limit_clusters=limit_clusters, history=history,
                              witness_seed=seed, progress=say, cache_workers=workers,
                              residency=residency)
    store = prepared.block_store
    say(f"residency: {len(store)} shard(s) decode to {store.nbytes} bytes; budget {budget} "
        f"({'fits' if store.nbytes <= budget else 'streams through the LRU'})")
    assignment = split_deals(store.keys(), seed=seed, val_fraction=val_fraction,
                             test_fraction=test_fraction)
    masks = {part: (lambda b, p=part: split_mask(b, assignment, p))
             for part in ("train", "val", "test")}
    n_rows = {part: 0 for part in masks}
    for block in store.iter_blocks():
        for part, fn in masks.items():
            n_rows[part] += int(fn(block).sum())
    deals = split_counts(assignment)
    split = {
        "method": config["split_method"], "seed": int(seed),
        "val_fraction": float(val_fraction), "test_fraction": float(test_fraction),
        "train_deals": deals["train"], "val_deals": deals["val"], "test_deals": deals["test"],
        "train_records": n_rows["train"], "val_records": n_rows["val"],
        "test_records": n_rows["test"],
        "roles": {name: SPLIT_ROLES[name]["role"] for name in ("train", "val", "test")},
        "note": ("stores that replay the same deals (e.g. Run A and Run B: 8,000 deals x "
                 "4 rounds, not 16,000 deals) share deal keys, so a deal's rows from every "
                 "store land in one part"),
    }
    if any(n == 0 for n in n_rows.values()):
        raise TrainError(f"split has {n_rows['train']} train / {n_rows['val']} val / "
                         f"{n_rows['test']} test records over {len(assignment)} deals; "
                         "need all three (at least three deals)")
    say(f"split: deals train={deals['train']} val={deals['val']} test={deals['test']} "
        f"records train={n_rows['train']} val={n_rows['val']} test={n_rows['test']}")
    population = fit_population(assignment, stores=prepared.stores)
    baselines = fit_baselines(store, masks["train"])
    say(f"baselines: stratified prior n={baselines['stratified_prior']['n']} "
        f"empty_cells={baselines['stratified_prior']['empty_cells']}")

    luna: tuple[Any, CwvBlockStore] | None = None
    luna_prepared: Prepared | None = None
    luna_population = None
    if eval_luna is not None:
        luna_prepared = prepare_stores([eval_luna], cache, limit_clusters=None, history=history,
                                       witness_seed=seed, progress=say, cache_workers=workers,
                                       residency=residency)
        refuse_overlap(store, luna_prepared.block_store, label=f"--eval-luna {eval_luna}")
        luna_population = population_report(luna_prepared.block_store.keys(), population)
        luna = (luna_prepared.stores[0], luna_prepared.block_store)
        say(f"luna: {luna_prepared.counts['records_total']} rows over "
            f"{luna_prepared.counts['deals_total']} deals, none shared with the data stores")

    public_model = None
    public_info = None
    if public_head is not None:
        try:
            public_model, public_info = load_public_head(public_head, dev)
        except EvalError as exc:
            raise TrainError(str(exc)) from exc
        say(f"public head: {public_info['schema']} epoch={public_info['epoch']} "
            f"population={'persisted' if public_info['has_population'] else 'not persisted'}")

    model_cfg = ValueModelConfig.from_payload(dict(config["model_config"]))
    model = ValueNetwork(model_cfg).to(dev)
    aux_head = AuxPointsHead(model_cfg.width).to(dev) if aux_points else None
    params = list(model.parameters()) + (list(aux_head.parameters()) if aux_head else [])
    optim = torch.optim.AdamW(params, lr=lr, weight_decay=weight_decay)
    rng = np.random.default_rng(seed)
    epoch_rows: list[dict] = []
    best = {"epoch": None, "loss": math.inf}
    since_best = 0
    ckpt_dir = out_dir / "checkpoints"
    ckpt_dir.mkdir(parents=True, exist_ok=True)
    selection = {"split": SELECTION_SPLIT, "criterion": SELECTION_CRITERION,
                 "patience": int(patience)}
    identity = cwv_encoder_identity()
    base_metadata = {
        "encoder": identity, "public_encoder": public_encoder_identity(),
        "config": config, "config_sha256": config_sha256(config), "split": split,
        "population": population, "baselines": baselines, "git": git_identity(),
        "receipt_schema": RECEIPT_SCHEMA,
    }
    n_params = int(sum(p.numel() for p in model.parameters()))
    say(f"model: {model_cfg.architecture} params={n_params}")
    for epoch in range(1, epochs + 1):
        t0 = time.perf_counter()
        model.train()
        if aux_head is not None:
            aux_head.train()
        sums = {"total": 0.0, "ce": 0.0, "aux": 0.0}
        rows = 0
        batches = 0
        for raw in store.iter_batches(masks["train"], batch_size, rng=rng, window=window):
            t = tensors_of(raw, dev)
            logits, aux = forward_batch(model, t, aux_head)
            ce = nn.functional.cross_entropy(logits, t["target"])
            total = ce
            if aux is not None and aux_weight > 0:
                a_loss = nn.functional.huber_loss(aux, t["attacker_points"] / 100.0, delta=1.0)
                total = total + float(aux_weight) * a_loss
                sums["aux"] += float(a_loss.item()) * int(t["target"].shape[0])
            if not bool(torch.isfinite(total)):
                raise TrainError("training loss is non-finite")
            optim.zero_grad(set_to_none=True)
            total.backward()
            optim.step()
            b = int(t["target"].shape[0])
            sums["total"] += float(total.item()) * b
            sums["ce"] += float(ce.item()) * b
            rows += b
            batches += 1
        train_metrics = {"loss": sums["total"] / max(rows, 1),
                         "cross_entropy": sums["ce"] / max(rows, 1), "rows": rows,
                         "batches": batches}
        if aux_head is not None:
            train_metrics["aux_huber"] = sums["aux"] / max(rows, 1)
        val_metrics = quick_metrics(run_eval(model, store, masks["val"], dev,
                                             batch_size=batch_size, aux_head=aux_head))
        secs = round(time.perf_counter() - t0, 3)
        epoch_rows.append({"epoch": epoch, "train": train_metrics, "val": val_metrics,
                           "val_role": SPLIT_ROLES["val"]["role"], "secs": secs})
        metadata = {**base_metadata, "epoch": epoch, "selection": {**selection, "val": val_metrics},
                    "aux_points_head": None if aux_head is None else aux_head.payload()}
        save_cwv_checkpoint(ckpt_dir / f"epoch-{epoch:02d}.pt", model, metadata=metadata)
        improved = val_metrics["loss"] is not None and val_metrics["loss"] < best["loss"]
        if improved:
            best = {"epoch": epoch, "loss": float(val_metrics["loss"])}
            since_best = 0
            shutil.copyfile(ckpt_dir / f"epoch-{epoch:02d}.pt", out_dir / "best.pt")
        else:
            since_best += 1
        say(f"epoch {epoch:02d}/{epochs} train_ce={train_metrics['cross_entropy']:.4f} "
            f"val_ce={val_metrics['loss']:.4f} val_mae_pt0={val_metrics['value_mae']:.4f} "
            f"val_rps={val_metrics['rps']:.4f}"
            + ("" if val_metrics.get("aux_points_mae") is None
               else f" val_aux_points_mae={val_metrics['aux_points_mae']:.2f}")
            + f"{' *' if improved else ''} ({secs}s) [val = tuning]")
        if since_best >= patience and epoch < epochs:
            say(f"early stop: no validation improvement for {patience} epochs "
                f"(best epoch {best['epoch']})")
            break

    model, best_metadata, aux_head = load_cwv_checkpoint(out_dir / "best.pt", dev)
    test_keys = set(population["test"])
    shard_keys_test = [(shard, [k for k in store.keys_of(i) if k in test_keys])
                       for i, (shard, _path) in enumerate(store.entries)]
    shard_keys_test = [(shard, keys) for shard, keys in shard_keys_test if keys]
    say(f"candidate pass (test): {len(shard_keys_test)} shard(s), eval_workers={eval_workers}")
    test_pass = candidate_pass(
        shard_keys_test, score_fn=cwv_score_fn(model, dev), public_head=public_model,
        prior=StratifiedPrior.from_dict(baselines["stratified_prior"]), device=dev,
        workers=eval_workers, rank_limit=rank_limit, history=history, progress=say)
    note = _public_head_note(public_info, config=config, split=split)
    metric_kw = dict(n_boot=n_boot, seed=seed)
    ev_val = run_eval(model, store, masks["val"], dev, batch_size=batch_size, aux_head=aux_head)
    ev_test = run_eval(model, store, masks["test"], dev, batch_size=batch_size,
                       aux_head=aux_head)
    test_public, test_check = public_comparison(test_pass, public_info)
    final = {
        "test": labelled("test", full_metrics(
            ev_test, baselines, public_decision=test_public,
            public_note={**note, **test_check}, **metric_kw)),
        "val": labelled("val", full_metrics(ev_val, baselines, **metric_kw)),
    }
    final["test"]["population"] = population_report(population["test"], population)
    final["val"]["population"] = population_report(population["val"], population)
    ranking = {"test": ranking_block(test_pass, n_boot=n_boot, seed=seed)}
    final["test"]["ranking"] = ranking["test"]
    luna_receipt = None
    if luna is not None:
        luna_store, luna_blocks = luna
        luna_pass = candidate_pass(
            [(shard, None) for shard, _path in luna_blocks.entries],
            score_fn=cwv_score_fn(model, dev), public_head=public_model,
            prior=StratifiedPrior.from_dict(baselines["stratified_prior"]), device=dev,
            workers=eval_workers, rank_limit=rank_limit, history=history, progress=say)
        ev_luna = run_eval(model, luna_blocks, lambda b: np.ones(b.n, dtype=bool), dev,
                           batch_size=batch_size, aux_head=aux_head)
        luna_public, luna_check = public_comparison(luna_pass, public_info)
        final["luna"] = labelled("luna", full_metrics(
            ev_luna, baselines, public_decision=luna_public,
            public_note={**note, **luna_check}, **metric_kw))
        final["luna"]["population"] = luna_population
        ranking["luna"] = ranking_block(luna_pass, n_boot=n_boot, seed=seed)
        final["luna"]["ranking"] = ranking["luna"]
        assert luna_prepared is not None and luna_population is not None
        luna_receipt = {**luna_store.describe(), "counts": luna_prepared.counts,
                        "cache": luna_prepared.cache_files,
                        "shared_deals_with_training": int(luna_population["shared_with_fit"]
                                                          + luna_population["shared_with_selection"]),
                        "shared_with_test": int(luna_population["in_test"]),
                        "population": luna_population,
                        "checked_against": dict(population["digest"])}
    selection = {**selection, "best_epoch": best["epoch"], "best_loss": best["loss"]}
    bench = bench_inference(model, bench_rows(shard_keys_test, int(bench_batch)))
    say(f"inference (cpu, batch {bench.get('batch')}): forward "
        f"{bench.get('forward_positions_per_second')} positions/s, predict_tensors "
        f"{bench.get('predict_tensors_positions_per_second')} positions/s")
    headline = {
        "test_mae_pt0": final["test"]["value"]["model"]["mae"],
        "test_prior_mae_pt0": final["test"]["value"]["stratified_prior"]["mae"],
        "test_public_head_mae_pt0": (final["test"].get("public_head") or {}).get(
            "public_head", {}).get("mae"),
        "test_top1_cwv": ((ranking["test"]["scorers"].get("cwv") or {}).get("top1") or {}).get(
            "mean"),
        "forward_positions_per_second_cpu_1024": bench.get("forward_positions_per_second"),
    }
    save_cwv_checkpoint(out_dir / "best.pt", model, metadata={
        **base_metadata, "epoch": best["epoch"], "selection": selection,
        "aux_points_head": None if aux_head is None else aux_head.payload(),
        "headline": headline, "inference_benchmark": bench})
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
        "encoder": identity,
        "sees_hidden_hands": SEES_HIDDEN_HANDS,
        "privacy": PRIVACY,
        "view": VIEW,
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
        "headline_numbers": headline,
        "selection": selection,
        "baselines": baselines,
        "epochs": epoch_rows,
        "best_epoch": best["epoch"],
        "stopped_early": len(epoch_rows) < epochs,
        "final": final,
        "calibration": None,
        "ranking": ranking,
        "public_head": None if public_info is None else {
            **{k: v for k, v in public_info.items() if k != "population"}, **note},
        "checkpoints": {"best": str(out_dir / "best.pt"),
                        "schema": "shengji-value-checkpoint-v1 (rl.value_checkpoint) + "
                                  f"metadata {CHECKPOINT_METADATA_SCHEMA}",
                        "epochs": [str(ckpt_dir / f"epoch-{r['epoch']:02d}.pt")
                                   for r in epoch_rows]},
        "model": {"architecture": model_cfg.architecture, "parameters": n_params,
                  "config": model_cfg.payload()},
        "residency": residency_receipt(
            residency, decoded_bytes=prepared.counts["decoded_bytes"],
            luna_bytes=0 if luna_prepared is None else luna_prepared.counts["decoded_bytes"]),
        "peak_memory": peak_memory(dev),
        "cache_dir": str(cache),
        "cache_workers": workers,
        "eval_workers": eval_workers,
        "inference_benchmark": bench,
    }
    check_receipt(receipt)
    _write_json(out_dir / "receipt.json", receipt)
    _write_json(out_dir / "metrics.json", {"schema": RECEIPT_SCHEMA + "-metrics",
                                           "epochs": epoch_rows, "final": final,
                                           "ranking": ranking, "headline": HEADLINE,
                                           "headline_numbers": headline,
                                           "selection": selection, "baselines": baselines,
                                           "best_epoch": best["epoch"],
                                           "inference_benchmark": bench})
    _say_final(say, final, wall)
    return receipt


def _say_final(say: Callable[[str], None], final: Mapping[str, Any], wall: float) -> None:
    for name in ("test", "luna"):
        block = final.get(name)
        if not block or "value" not in block:
            continue
        v = block["value"]
        diff = v["paired_diff_model_minus_prior"]["abs_error"]
        line = (f"final {name}: n={v['n']} cwv_mae={v['model']['mae']:.4f} "
                f"prior_mae={v['stratified_prior']['mae']:.4f} diff={diff['mean']:.4f} "
                f"ci95={[round(x, 4) for x in diff['ci95']]}")
        pub = block.get("public_head") or {}
        if pub.get("public_head"):
            pdiff = pub["paired_diff_model_minus_public"]["abs_error"]
            line += (f" | public_head_mae={pub['public_head']['mae']:.4f} "
                     f"diff={pdiff['mean']:.4f} ci95={[round(x, 4) for x in pdiff['ci95']]}")
        rank = block.get("ranking") or {}
        for scorer, summary in (rank.get("scorers") or {}).items():
            top1 = summary.get("top1") or {}
            sp = summary.get("spearman") or {}
            line += (f" | {scorer}: top1={top1.get('mean')} "
                     f"spearman={None if not sp else round(sp['mean'], 4)}")
        say(line)
    say(f"wall={wall}s")


# ---------------------------------------------------------------- evaluate

def evaluate(*, checkpoint: str, out: str | os.PathLike, data: Sequence[str] | None = None,
             eval_luna: str | None = None, device: str | None = None, split: str = "test",
             limit_clusters: int | None = None, n_boot: int | None = None,
             batch_size: int | None = None, public_head: str | None = None,
             rank_limit: int | None = None, cache_dir: str | None = None,
             cache_workers: int | None = None, eval_workers: int | None = None,
             resident_bytes: int | None = None, bench_batch: int = DEFAULTS["bench_batch"],
             argv: list[str] | None = None,
             log: Callable[[str], None] | None = print) -> dict:
    """Score a checkpoint against populations checked against the deal
    identities it was fitted and selected on (``train_v0.evaluate``'s
    rules)."""
    if not data and not eval_luna:
        raise TrainError("evaluate needs --data DIR and/or --eval-luna PATH")
    if split not in EVAL_SPLITS:
        raise TrainError(f"--split must be one of {EVAL_SPLITS}")
    budget = _resident_budget(resident_bytes)
    started = time.perf_counter()
    started_at = time.strftime("%Y-%m-%d %H:%M:%S")
    out_dir = Path(out)
    out_dir.mkdir(parents=True, exist_ok=True)
    cache = Path(cache_dir) if cache_dir else out_dir / "cache"
    workers = default_cache_workers() if cache_workers is None else max(1, int(cache_workers))
    eval_workers = workers if eval_workers is None else max(1, int(eval_workers))
    dev = pick_device(device)
    say = log or (lambda _s: None)
    model, metadata, aux_head = load_cwv_checkpoint(checkpoint, dev)
    config = metadata["config"]
    history = metadata["arch"] == "seq"
    population = metadata.get("population")
    sets = population_sets(population)
    seeds = seed_everything(int(config["seed"]), dev)
    baselines = metadata["baselines"]
    n_boot = int(n_boot if n_boot is not None else config["n_boot"])
    batch_size = int(batch_size if batch_size is not None else config["batch_size"])
    residency = Residency(budget)
    prepare_kw = dict(history=history, witness_seed=int(config["seed"]), progress=say,
                      cache_workers=workers, residency=residency)
    public_model = None
    public_info = None
    if public_head is not None:
        try:
            public_model, public_info = load_public_head(public_head, dev)
        except EvalError as exc:
            raise TrainError(str(exc)) from exc
    note = _public_head_note(public_info, config=config, split=metadata.get("split") or {})
    prior = StratifiedPrior.from_dict(baselines["stratified_prior"])
    final: dict = {}
    ranking: dict = {}
    data_receipt: list = []
    counts: dict = {}
    split_info = None
    decoded = 0
    bench_source: list = []
    if data:
        prepared = prepare_stores(list(data), cache, limit_clusters=limit_clusters,
                                  **prepare_kw)
        store = prepared.block_store
        decoded = prepared.counts["decoded_bytes"]
        data_keys = set(store.keys())
        match = population_report(data_keys, population)
        say(f"population: store deals={match['deals']} in_train={match['in_train']} "
            f"in_val={match['in_val']} in_test={match['in_test']} novel={match['novel']}")
        parts = {"train": sets["train"], "val": sets["val"], "test": sets["test"],
                 "novel": data_keys - sets["train"] - sets["val"] - sets["test"],
                 "all": data_keys}
        selected = parts[split] & data_keys
        if not selected:
            raise TrainError(f"--data {list(data)}: no deal of the checkpoint's {split!r} "
                             f"population is in this store ({match})")
        selected_arr = np.asarray(sorted(selected), dtype=str)
        mask_fn = lambda b: np.isin(b.deal_key, selected_arr)  # noqa: E731
        shard_keys = [(shard, [k for k in store.keys_of(i) if k in selected])
                      for i, (shard, _path) in enumerate(store.entries)]
        shard_keys = [(shard, keys) for shard, keys in shard_keys if keys]
        bench_source = shard_keys
        pass_result = candidate_pass(
            shard_keys, score_fn=cwv_score_fn(model, dev), public_head=public_model,
            prior=prior, device=dev, workers=eval_workers, rank_limit=rank_limit,
            history=history, progress=say)
        ev = run_eval(model, store, mask_fn, dev, batch_size=batch_size, aux_head=aux_head)
        data_public, data_check = public_comparison(pass_result, public_info)
        metrics = full_metrics(ev, baselines, n_boot=n_boot, seed=int(config["seed"]),
                               public_decision=data_public,
                               public_note={**note, **data_check})
        if split == "all":
            block = {**metrics, "split": "all", "held_out": False,
                     "role": "every row of the store (whatever part); not held out"}
        else:
            block = labelled(split, metrics)
        block["population"] = population_report(selected, population)
        ranking[split] = ranking_block(pass_result, n_boot=n_boot, seed=int(config["seed"]))
        block["ranking"] = ranking[split]
        final[split] = block
        data_receipt = [{**s.describe(), "cache": prepared.cache_files} for s in prepared.stores]
        counts = prepared.counts
        split_info = {"part": split, "records": int(ev["ce"].size), "deals": len(selected),
                      "population_match": match,
                      "checkpoint_population": dict(population["counts"]),
                      "seed": int(config["seed"])}
    luna_receipt = None
    luna_bytes = 0
    if eval_luna:
        luna_prepared = prepare_stores([eval_luna], cache, limit_clusters=None, **prepare_kw)
        luna_bytes = luna_prepared.counts["decoded_bytes"]
        luna_population = population_report(luna_prepared.block_store.keys(), population)
        shared = luna_population["shared_with_fit"] + luna_population["shared_with_selection"]
        if shared:
            raise TrainError(f"--eval-luna {eval_luna} shares {shared} deal(s) with the "
                             "checkpoint's fit/selection population: not held out; refusing")
        luna_blocks = luna_prepared.block_store
        luna_pass = candidate_pass(
            [(shard, None) for shard, _path in luna_blocks.entries],
            score_fn=cwv_score_fn(model, dev), public_head=public_model, prior=prior,
            device=dev, workers=eval_workers, rank_limit=rank_limit, history=history,
            progress=say)
        ev = run_eval(model, luna_blocks, lambda b: np.ones(b.n, dtype=bool), dev,
                      batch_size=batch_size, aux_head=aux_head)
        luna_public, luna_check = public_comparison(luna_pass, public_info)
        final["luna"] = labelled("luna", full_metrics(
            ev, baselines, n_boot=n_boot, seed=int(config["seed"]),
            public_decision=luna_public, public_note={**note, **luna_check}))
        final["luna"]["population"] = luna_population
        ranking["luna"] = ranking_block(luna_pass, n_boot=n_boot, seed=int(config["seed"]))
        final["luna"]["ranking"] = ranking["luna"]
        if not bench_source:
            bench_source = [(shard, None) for shard, _path in luna_blocks.entries]
        luna_receipt = {**luna_prepared.stores[0].describe(), "counts": luna_prepared.counts,
                        "cache": luna_prepared.cache_files,
                        "shared_deals_with_training": int(shared),
                        "shared_with_test": int(luna_population["in_test"]),
                        "population": luna_population,
                        "checked_against": dict(population["digest"])}
    bench = bench_inference(model, bench_rows(bench_source, int(bench_batch)))
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
        "encoder": cwv_encoder_identity(),
        "sees_hidden_hands": SEES_HIDDEN_HANDS,
        "privacy": PRIVACY,
        "view": VIEW,
        "checkpoint": {"path": str(Path(checkpoint).resolve()), "epoch": metadata.get("epoch"),
                       "arch": metadata.get("arch"),
                       "config_sha256": metadata.get("config_sha256")},
        "config": config,
        "config_sha256": config_sha256(config),
        "seeds": seeds,
        "data": data_receipt,
        "luna": luna_receipt,
        "counts": counts,
        "split": split_info,
        "population": population,
        "headline": headline,
        "selection": metadata.get("selection"),
        "baselines": baselines,
        "epochs": [],
        "best_epoch": metadata.get("epoch"),
        "stopped_early": None,
        "final": final,
        "calibration": None,
        "ranking": ranking,
        "public_head": None if public_info is None else {
            **{k: v for k, v in public_info.items() if k != "population"}, **note},
        "checkpoints": {"evaluated": str(Path(checkpoint).resolve())},
        "model": {"architecture": model.config.architecture, "config": model.config.payload()},
        "residency": residency_receipt(residency, decoded_bytes=decoded, luna_bytes=luna_bytes),
        "peak_memory": peak_memory(dev),
        "cache_dir": str(cache),
        "cache_workers": workers,
        "eval_workers": eval_workers,
        "inference_benchmark": bench,
    }
    check_receipt(receipt)
    _write_json(out_dir / "receipt.json", receipt)
    _write_json(out_dir / "metrics.json", {"schema": RECEIPT_SCHEMA + "-metrics",
                                           "final": final, "ranking": ranking,
                                           "headline": headline, "baselines": baselines,
                                           "inference_benchmark": bench})
    _say_final(say, final, wall)
    return receipt


# --------------------------------------------------------------------- CLI

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="train_cwv", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--out", required=True, help="output directory")
        p.add_argument("--device", default=None, help="mps|cpu (default: mps when available)")
        p.add_argument("--cache-dir", default=None,
                       help="derived encoding cache (default: <out>/cache)")
        p.add_argument("--cache-workers", type=int, default=None,
                       help=f"shards encoded at a time (default {default_cache_workers()})")
        p.add_argument("--eval-workers", type=int, default=None,
                       help="worker processes of the candidate pass (default: --cache-workers)")
        p.add_argument("--resident-bytes", type=int, default=None,
                       help="residency budget for decoded shard blocks "
                            f"(default 40%% of physical memory = {default_resident_bytes()})")
        p.add_argument("--limit-clusters", type=int, default=None,
                       help="use only the first N deals of each data store")
        p.add_argument("--eval-luna", default=None,
                       help="Luna private split (evaluation only; must share no deal "
                            "with --data)")
        p.add_argument("--public-head", default=None,
                       help="a train_v0 checkpoint (v2/v3) scored on the same rows")
        p.add_argument("--rank-limit", type=int, default=None,
                       help="cap the records of the candidate-ranking pass (per shard: "
                            "ceil(N / shards))")
        p.add_argument("--bench-batch", type=int, default=DEFAULTS["bench_batch"],
                       help="positions per batch of the CPU inference benchmark")

    t = sub.add_parser("train", help="train the complete-world value net")
    common(t)
    t.add_argument("--data", action="append", required=True,
                   help="shard store / merged store directory (repeatable)")
    t.add_argument("--arch", choices=ARCHES, default="mlp")
    t.add_argument("--epochs", type=int, default=DEFAULTS["epochs"])
    t.add_argument("--seed", type=int, default=DEFAULTS["seed"])
    t.add_argument("--lr", type=float, default=DEFAULTS["lr"])
    t.add_argument("--weight-decay", type=float, default=DEFAULTS["weight_decay"])
    t.add_argument("--batch-size", type=int, default=DEFAULTS["batch_size"])
    t.add_argument("--patience", type=int, default=DEFAULTS["patience"])
    t.add_argument("--val-fraction", type=float, default=DEFAULTS["val_fraction"])
    t.add_argument("--test-fraction", type=float, default=DEFAULTS["test_fraction"])
    t.add_argument("--hidden", type=int, default=DEFAULTS["hidden"],
                   help="mlp trunk widths [N, N // 2]")
    t.add_argument("--dropout", type=float, default=DEFAULTS["dropout"])
    t.add_argument("--aux-points", action="store_true",
                   help="auxiliary attacker-points head on the mlp trunk")
    t.add_argument("--aux-weight", type=float, default=DEFAULTS["aux_weight"])
    t.add_argument("--n-boot", type=int, default=DEFAULTS["n_boot"])
    t.add_argument("--window", type=int, default=DEFAULTS["window"],
                   help="shards per shuffle window (also bounded by --resident-bytes)")
    t.add_argument("--seq-kind", choices=SEQ_KINDS, default=DEFAULTS["seq_kind"])
    t.add_argument("--seq-width", type=int, default=DEFAULTS["seq_width"])
    t.add_argument("--seq-layers", type=int, default=DEFAULTS["seq_layers"])
    t.add_argument("--seq-heads", type=int, default=DEFAULTS["seq_heads"])
    t.add_argument("--seq-feedforward", type=int, default=DEFAULTS["seq_feedforward"])

    e = sub.add_parser("evaluate", help="score a checkpoint")
    common(e)
    e.add_argument("--checkpoint", required=True)
    e.add_argument("--data", action="append", default=None)
    e.add_argument("--split", choices=EVAL_SPLITS, default="test")
    e.add_argument("--n-boot", type=int, default=None)
    e.add_argument("--batch-size", type=int, default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    os.environ.setdefault("SHENGJI_REQUIRE_VOIDS", "1")
    args = build_parser().parse_args(argv)
    full_argv = sys.argv if argv is None else ["train_cwv", *argv]

    def log(line: str) -> None:
        print(line, flush=True)

    exec_kw = dict(cache_dir=args.cache_dir, cache_workers=args.cache_workers,
                   eval_workers=args.eval_workers, resident_bytes=args.resident_bytes,
                   public_head=args.public_head, rank_limit=args.rank_limit,
                   bench_batch=args.bench_batch, argv=full_argv, log=log)
    try:
        if args.command == "train":
            train(data=args.data, out=args.out, eval_luna=args.eval_luna, arch=args.arch,
                  device=args.device, epochs=args.epochs, seed=args.seed,
                  limit_clusters=args.limit_clusters, lr=args.lr,
                  weight_decay=args.weight_decay, batch_size=args.batch_size,
                  patience=args.patience, val_fraction=args.val_fraction,
                  test_fraction=args.test_fraction, hidden=args.hidden, dropout=args.dropout,
                  aux_points=args.aux_points, aux_weight=args.aux_weight, n_boot=args.n_boot,
                  window=args.window, seq_kind=args.seq_kind, seq_width=args.seq_width,
                  seq_layers=args.seq_layers, seq_heads=args.seq_heads,
                  seq_feedforward=args.seq_feedforward, **exec_kw)
        else:
            evaluate(checkpoint=args.checkpoint, out=args.out, data=args.data,
                     eval_luna=args.eval_luna, device=args.device, split=args.split,
                     limit_clusters=args.limit_clusters, n_boot=args.n_boot,
                     batch_size=args.batch_size, **exec_kw)
    except (TrainError, TrainDataError, EvalError) as exc:
        print(f"REFUSING: {exc}", file=sys.stderr)
        return 2
    print(f"receipt -> {Path(args.out) / 'receipt.json'}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
