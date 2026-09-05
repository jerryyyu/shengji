"""``train`` / ``evaluate`` for the complete-world value net (cwv_train_spec).

    train_cwv.py train --data DIR [--data DIR ...] [--eval-luna PATH] --out DIR
        --arch mlp|seq [--device mps|cpu] [--limit-clusters N] [--aux-points]
        [--seed N] [--public-head CKPT] [--epochs 20] [--batch-size 1024]
        [--select-metric val_ce|val_rank_regret|val_points_mae] [--val-rank-records N]
        [--init CKPT [--init-lr-scale F] [--init-exclude-exposed]] ...
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
selection on ``--select-metric``, tuning only; test = the reported
held-out metrics), the Luna private rows as an external held-out
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

Search-facing validation (``cwv_eval.search_facing_metrics``)
-------------------------------------------------------------
Jerry's rule: the training validation metric, the held-out eval and what
the search consumes are the SAME quantity computed by the SAME code.  Every
epoch, the final val/test pass and ``evaluate`` call that one function on
the split's rows plus a ``CandidateSet`` (the first ``--val-rank-records``
search records of the split, every candidate applied in the TRUE world,
encoded once and memoised in the cache dir; scored by one batched forward):
``rank_regret`` / ``rank_top1`` (the level head's per-decision ranking
against the search's means, on the level scale the search consumes),
``points_mae`` / ``points_bias`` / ``points_below_banked`` (the aux points
head, what the vleaf leaf consumes) next to CE / MAE.  ``--select-metric``
picks which one drives early stopping and ``best.pt``: ``val_ce`` (the
default, byte-identical to the historical runs), ``val_rank_regret`` (the
recommendation for the ranking consumers: one-ply / shortlist / netroll /
PUCT) or ``val_points_mae`` (the recommendation for the leaf).  ``--init``
warm-starts trunk and heads from a checkpoint of the same architecture and
feature layout (refused otherwise); the receipt's ``consumer`` block names
which search designs consume which head on which positions.  ``rank_regret``
is the level-bracket transform of the search's MEAN points, U(E[points]),
an MC-ranking proxy -- not E[U].

Labelled harvest holdouts (``--eval-holdout NAME=PATH``, repeatable)
--------------------------------------------------------------------
A file written by ``scripts/label_harvest.py`` (``train.harvest_labels``:
off-distribution harvest positions -- human, Luna, PT1, room-log, highn --
labelled with production's own search) is a search-facing holdout.  The
final test pass of ``train`` and ``evaluate`` call the SAME
``cwv_eval.search_facing_metrics`` on it and report the block under
``search_facing.holdouts.<name>`` (and ``receipt["holdouts"]``): rank
regret / top-1 from the labels' ballot and means (every candidate applied
in the record's true world), CE / value MAE / reliability and the points
head from the record's outcome.  What a source cannot support is SKIPPED
and reported null with the reason (``cwv_eval.HOLDOUT_SUPPORT``): PT1 and
highn rows carry no outcome, so only their ranking is scored; a holdout
sharing a deal with the fit/selection population or the cumulative
exposure is refused, exactly as ``--eval-luna``.

Cumulative exposure (warm start)
--------------------------------
Every checkpoint and receipt persists ``exposure``: the deal keys this run
FIT on (train) and SELECTED on (val), united with every warm-start
ancestor's (``--init`` loads the source's block; a checkpoint without one
exposes its own persisted population).  A warm start recomputes the split
over its own, usually larger, population, so an ancestral fit/selection
deal can land in the new val or test (an ancestral FIT deal in val, an
ancestral fit-or-selected deal in test): ``--init`` REFUSES that, naming
the counts per split, unless ``--init-exclude-exposed`` drops those deals from
the new val/test (never into train; the receipt's ``init.excluded`` and
stdout carry the counts).  ``evaluate --split novel`` and the Luna
evaluation consult the cumulative exposure, so a second warm start cannot
erase it.
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import hashlib
import math
import os
import random
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Callable, Collection, Mapping, Sequence

import numpy as np
import torch
from torch import nn

from ..rl.douzero_micro import HISTORY_MAX_EVENTS
from ..rl.value_afterstate import OUTCOME_CLASSES, ValueAfterstateTensors
from ..rl.value_checkpoint import (
    ValueCheckpointError,
    file_sha256,
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
    CONSUMERS,
    HOLDOUT_SUPPORT,
    EvalError,
    SCORERS,
    CandidateSet,
    candidate_levels,
    candidate_pass,
    candidate_tensors,
    ensure_candidate_set,
    holdout_candidate_set,
    holdout_deal_keys,
    load_labeled_holdout,
    load_public_head,
    materialize_holdout_records,
    paired_agreement,
    search_facing_metrics,
    summarize_agreement,
)
from .data import (
    DEAL_KEY_SCHEMA,
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
EXPOSURE_SCHEMA = "shengji-cwv-exposure-v1"
CHECKPOINT_METADATA_SCHEMA = "shengji-cwv-checkpoint-metadata-v1"
ARCHES = ("mlp", "seq")
SEQ_KINDS = ("transformer", "gru")
SELECTION_CRITERION = ("validation cross-entropy of the 204-class signed-level head "
                       "(never the aux term)")
#: ``--select-metric`` -> the key of the per-epoch validation block it reads
#: (every one is lower-is-better) and its criterion text.
SELECT_METRICS = {
    "val_ce": ("loss", SELECTION_CRITERION),
    "val_rank_regret": ("rank_regret", "validation rank regret of the level head: level of "
                                       "the search's best candidate minus the level of the "
                                       "net's argmax candidate, per decision, averaged "
                                       "(cwv_eval.rank_metrics; the ranking consumers' "
                                       "quantity; levels are U(E[points]), the bracket "
                                       "transform of the search's MEAN points -- an "
                                       "MC-ranking proxy, not E[U])"),
    "val_points_mae": ("points_mae", "validation MAE of the aux points head in attacker "
                                     "points (cwv_eval.points_metrics; the vleaf leaf's "
                                     "quantity)"),
}
DEFAULTS = {
    "epochs": 20, "seed": 1, "lr": 3e-4, "weight_decay": 1e-4, "batch_size": 1024,
    "patience": 3, "val_fraction": 0.1, "test_fraction": 0.1, "hidden": 512, "dropout": 0.1,
    "aux_weight": 0.1, "n_boot": 1000, "window": 64, "seq_kind": "transformer",
    "seq_width": 64, "seq_layers": 2, "seq_heads": 4, "seq_feedforward": 128,
    "bench_batch": 1024, "select_metric": "val_ce", "val_rank_records": 20_000,
    "init_lr_scale": 1.0,
}
REQUIRED_RECEIPT_FIELDS = (
    "schema", "command", "argv", "started", "wall_secs", "device", "versions", "git",
    "encoder", "sees_hidden_hands", "privacy", "view", "config", "config_sha256", "seeds",
    "data", "luna", "counts", "split", "population", "headline", "selection", "baselines",
    "epochs", "best_epoch", "stopped_early", "final", "checkpoints", "public_head",
    "ranking", "residency", "peak_memory", "cache_dir", "cache_workers",
    "inference_benchmark", "consumer", "init", "exposure",
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


# ------------------------------------------------- search-facing validation

def per_shard_cap(n_records: int, n_shards: int) -> int:
    """``--val-rank-records N`` as a per-shard cap: ceil(N / shards)."""
    return int(math.ceil(int(n_records) / max(int(n_shards), 1))) if n_records > 0 else 0


def shard_keys_of(store: CwvBlockStore, keys: set[str]) -> list[tuple[Any, list[str]]]:
    """``(shard, its deal keys among ``keys``)`` for every shard that has one."""
    out = [(shard, [k for k in store.keys_of(i) if k in keys])
           for i, (shard, _path) in enumerate(store.entries)]
    return [(shard, ks) for shard, ks in out if ks]


@contextlib.contextmanager
def rng_guard():
    """Leave every RNG the run seeds exactly as found (the candidate-set
    build runs before the model is initialised)."""
    py_state = random.getstate()
    np_state = np.random.get_state()
    torch_state = torch.get_rng_state()
    mps_state = (torch.mps.get_rng_state() if hasattr(torch, "mps")
                 and torch.backends.mps.is_available() else None)
    try:
        yield
    finally:
        random.setstate(py_state)
        np.random.set_state(np_state)
        torch.set_rng_state(torch_state)
        if mps_state is not None:
            torch.mps.set_rng_state(mps_state)


def candidate_set_for(store: CwvBlockStore, keys: set[str], cache: Path | None, *,
                      n_records: int, history: bool, workers: int, label: str,
                      progress: Callable[[str], None] | None) -> CandidateSet | None:
    """The split's memoised ``CandidateSet`` (None when ``n_records`` is 0)."""
    if n_records <= 0:
        return None
    shard_keys = shard_keys_of(store, keys)
    with rng_guard():
        return ensure_candidate_set(
            shard_keys, cache, per_shard_limit=per_shard_cap(n_records, len(shard_keys)),
            history=history, workers=workers, label=label, progress=progress)


def rank_levels(model: ValueNetwork, cands: CandidateSet, device: torch.device, *,
                batch_size: int) -> np.ndarray:
    """The net's expected signed level per candidate (``cwv_eval.candidate_levels``)."""
    model.eval()
    return candidate_levels(lambda t: forward_batch(model, t)[0], cands, device,
                            batch_size=batch_size)


def search_facing(model: ValueNetwork, ev: Mapping[str, np.ndarray],
                  cands: CandidateSet | None, device: torch.device, *, batch_size: int
                  ) -> dict:
    """``cwv_eval.search_facing_metrics`` on ``ev`` (``run_eval``'s arrays)
    and the candidate set, plus the seconds the candidate forward took."""
    t0 = time.perf_counter()
    levels = (None if cands is None or cands.records == 0
              else rank_levels(model, cands, device, batch_size=batch_size))
    block = search_facing_metrics(ev, levels=levels, cands=cands)
    block["rank_secs"] = round(time.perf_counter() - t0, 3)
    return block


def parse_holdouts(specs: Sequence[str] | None) -> dict[str, str]:
    """``--eval-holdout NAME=PATH`` (repeatable) -> ``{name: path}``; names
    are unique identifiers, paths must exist."""
    out: dict[str, str] = {}
    for spec in specs or ():
        name, sep, path = str(spec).partition("=")
        name = name.strip()
        if not sep or not name or not path.strip():
            raise TrainError(f"--eval-holdout {spec!r}: expected NAME=PATH")
        if not name.replace("-", "_").replace(".", "_").isidentifier():
            raise TrainError(f"--eval-holdout {spec!r}: NAME must be an identifier-like label")
        if name in out:
            raise TrainError(f"--eval-holdout {spec!r}: duplicate holdout name {name!r}")
        resolved = Path(path.strip()).expanduser()
        if not resolved.is_file():
            raise TrainError(f"--eval-holdout {spec!r}: {resolved} is not a file")
        out[name] = str(resolved.resolve())
    return out


def holdout_blocks(holdouts: Mapping[str, str], *, model: ValueNetwork,
                   aux_head: "AuxPointsHead | None", dev: torch.device, batch_size: int,
                   history: bool, seed: int, cache: Path, workers: int,
                   residency: "Residency | None", population: Mapping[str, Any],
                   exposure: Mapping[str, Any], n_boot: int,
                   say: Callable[[str], None]) -> dict[str, dict]:
    """``search_facing_metrics`` on every labelled harvest holdout (module
    docstring): the labels' candidate set for the ranking, the record
    rows (through ``prepare_stores`` on the untouched records) for CE /
    MAE / reliability / points when the outcome is present.  Unsupported
    metrics stay null with their reason; a deal overlap with the
    fit/selection population or the cumulative exposure refuses."""
    blocks: dict[str, dict] = {}
    for name, path in holdouts.items():
        t0 = time.perf_counter()
        try:
            hold = load_labeled_holdout(path)
        except (EvalError, ValueError) as exc:
            raise TrainError(f"--eval-holdout {name}={path}: {exc}") from exc
        say(f"holdout {name}: {hold.counts['rows']} rows (labelled {hold.counts['labelled']}, "
            f"searched {hold.counts['searched']}, rank-eligible {hold.counts['rank_eligible']}, "
            f"with outcome {hold.counts['with_outcome']}) sources={hold.sources} "
            f"labeller={hold.identity['policy']} x{hold.identity['scale']} "
            f"N{hold.identity['n_worlds']}/R{hold.identity['report_worlds']}")
        # held out?  The deal identities of EVERY row (rank-only files
        # included) against the fit/selection population and the cumulative
        # exposure, BEFORE any metric is computed (Codex HOLD, PR #243)
        keys = holdout_deal_keys(hold)
        pop = population_report(keys, population)
        pop["exposure"] = exposure_report(keys, exposure)
        shared = pop["shared_with_fit"] + pop["shared_with_selection"]
        if shared:
            raise TrainError(f"--eval-holdout {name} shares {shared} deal(s) with the "
                             "checkpoint's fit/selection population: not held out; refusing")
        if pop["exposure"]["exposed"]:
            raise TrainError(f"--eval-holdout {name} shares {pop['exposure']['exposed']} "
                             "deal(s) with the cumulative fit/selection exposure: not held "
                             "out; refusing")
        say(f"holdout {name}: {pop['deals']} deals, none shared with the fit/selection "
            f"population or the exposure (in_test={pop['in_test']} novel={pop['novel']})")
        cands = None
        levels = None
        if hold.supports["rank_regret"]:
            with rng_guard():
                cands = holdout_candidate_set(hold, history=history, label=name)
            if cands.records:
                levels = rank_levels(model, cands, dev, batch_size=batch_size)
        ev: dict[str, np.ndarray] = {}
        rows_block: dict[str, Any] = {"n": 0, "population": pop, "cache": None}
        if hold.supports["calibration"]:
            materialized = materialize_holdout_records(
                hold, cache / "holdouts" / f"{name}-{hold.sha256[:16]}.jsonl")
            prepared = prepare_stores([str(materialized)], cache, limit_clusters=None,
                                      history=history, witness_seed=int(seed), progress=say,
                                      cache_workers=workers, residency=residency)
            encoded = set(prepared.block_store.keys())
            if encoded - keys:
                raise TrainError(f"--eval-holdout {name}: encoded rows carry "
                                 f"{len(encoded - keys)} deal(s) the exposure check did not see")
            ev = run_eval(model, prepared.block_store, lambda b: np.ones(b.n, dtype=bool), dev,
                          batch_size=batch_size, aux_head=aux_head)
            rows_block = {"n": int(ev["ce"].size), "population": pop,
                          "counts": prepared.counts, "cache": prepared.cache_files,
                          "materialized": str(materialized)}
        block = search_facing_metrics(ev, levels=levels, cands=cands)
        if int(block["n"]):
            block["rps"] = float(ev["rps"].mean())
            block["deals"] = int(np.unique(ev["deal_key"]).size)
            block["reliability"] = {
                "bins": 10,
                "pt0": reliability_table(ev["expected_pt0"], ev["utility"], bins=10),
                "level": reliability_table(ev["expected_level"], ev["target_level"], bins=10),
            }
            err = ev["expected_pt0"] - ev["utility"]
            block["value_mae_ci95"] = cluster_bootstrap(np.abs(err), ev["deal_key"],
                                                        n_boot=n_boot, seed=int(seed) + 11)
        skipped = {}
        if not hold.supports["rank_regret"]:
            skipped["rank_regret"] = f"needs {HOLDOUT_SUPPORT['rank_regret']}"
        if not hold.supports["calibration"]:
            skipped["calibration"] = f"needs {HOLDOUT_SUPPORT['calibration']}"
            skipped["cross_entropy"] = skipped["value_mae"] = skipped["calibration"]
        if not hold.supports["points"]:
            skipped["points"] = f"needs {HOLDOUT_SUPPORT['points']}"
        elif aux_head is None:
            skipped["points"] = "the checkpoint has no points head (--aux-points)"
        block.update({
            "name": name,
            "holdout": hold.describe(),
            "supports": dict(hold.supports),
            "skipped": skipped,
            "population": pop,
            "rows": rows_block,
            "candidate_set": (None if cands is None
                              else {k: v for k, v in cands.meta.items() if k != "encoder"}),
            "held_out": True,
            "role": "labelled harvest holdout: off-distribution positions labelled by "
                    "production search (harvest_labels); never fitted or selected on",
            "secs": round(time.perf_counter() - t0, 3),
        })
        line = f"holdout {name}:"
        if block.get("rank_regret") is not None:
            line += (f" rank_regret={block['rank_regret']:.4f} rank_top1={block['rank_top1']:.3f} "
                     f"(n={block['rank_records']})")
        if block.get("cross_entropy") is not None:
            line += f" ce={block['cross_entropy']:.4f} value_mae={block['value_mae']:.4f} (n={block['n']})"
        if block.get("points_mae") is not None:
            line += f" points_mae={block['points_mae']:.2f} points_bias={block['points_bias']:+.2f}"
        if skipped:
            line += f" skipped={sorted(skipped)}"
        say(line)
        blocks[name] = block
    return blocks


class Selector:
    """Epoch selection on one lower-is-better validation metric
    (``SELECT_METRICS``): ``observe`` returns ``(improved, stop)``."""

    def __init__(self, metric: str, *, patience: int):
        if metric not in SELECT_METRICS:
            raise TrainError(f"--select-metric must be one of {tuple(SELECT_METRICS)}")
        self.metric = metric
        self.key, self.criterion = SELECT_METRICS[metric]
        self.patience = int(patience)
        self.best_epoch: int | None = None
        self.best_value = math.inf
        self.since_best = 0

    def value_of(self, val_metrics: Mapping[str, Any]) -> float:
        value = val_metrics.get(self.key)
        if value is None or not math.isfinite(float(value)):
            raise TrainError(f"--select-metric {self.metric}: the validation block has no "
                             f"finite {self.key!r} (no search records / no points head?)")
        return float(value)

    def observe(self, epoch: int, val_metrics: Mapping[str, Any]) -> tuple[bool, bool]:
        value = self.value_of(val_metrics)
        improved = value < self.best_value
        if improved:
            self.best_epoch, self.best_value, self.since_best = int(epoch), value, 0
        else:
            self.since_best += 1
        return improved, self.since_best >= self.patience

    def payload(self) -> dict:
        return {"metric": self.metric, "key": self.key, "criterion": self.criterion,
                "patience": self.patience, "best_epoch": self.best_epoch,
                "best_value": None if self.best_epoch is None else self.best_value}


def consumer_block(select_metric: str, aux_points: bool) -> dict:
    """Which search designs consume which head on which positions, and
    the metric this run selected on (``cwv_eval.CONSUMERS``)."""
    heads = {"level_head": copy.deepcopy(CONSUMERS["level_head"])}
    if aux_points:
        heads["points_head"] = copy.deepcopy(CONSUMERS["points_head"])
    return {"select_metric": select_metric, "heads": heads,
            "rule": "the training validation metric, the held-out eval and what the search "
                    "consumes are the SAME quantity computed by the SAME code "
                    "(cwv_eval.search_facing_metrics)"}


# --------------------------------------------------------------- exposure

def exposure_block(fit: Collection[str], selection: Collection[str], *,
                   ancestors: Sequence[Mapping[str, Any]] = (), note: str | None = None) -> dict:
    """The cumulative exposure of a checkpoint: every deal it (or a
    warm-start ancestor) was FIT on and every deal it (or an ancestor) was
    SELECTED on; persisted in the checkpoint payload and the receipt."""
    fit_keys = sorted(set(str(k) for k in fit))
    sel_keys = sorted(set(str(k) for k in selection))
    return {
        "schema": EXPOSURE_SCHEMA, "deal_key_schema": DEAL_KEY_SCHEMA,
        "fit": fit_keys, "selection": sel_keys,
        "counts": {"fit": len(fit_keys), "selection": len(sel_keys),
                   "exposed": len(set(fit_keys) | set(sel_keys))},
        "digest": {"fit": hashlib.sha256("\n".join(fit_keys).encode()).hexdigest(),
                   "selection": hashlib.sha256("\n".join(sel_keys).encode()).hexdigest()},
        "ancestors": [dict(a) for a in ancestors],
        "note": note or ("cumulative: this run's fit (train) and selection (val) deals united "
                         "with every warm-start ancestor's"),
    }


def exposure_sets(exposure: Mapping[str, Any] | None) -> dict[str, set[str]]:
    """``{"fit", "selection"}`` as sets from a persisted exposure, validated."""
    if not isinstance(exposure, Mapping) or exposure.get("schema") != EXPOSURE_SCHEMA:
        raise TrainError(f"checkpoint carries no {EXPOSURE_SCHEMA} exposure block")
    if exposure.get("deal_key_schema") != DEAL_KEY_SCHEMA:
        raise TrainError("exposure deal-key schema differs from this build's")
    out = {}
    for part in ("fit", "selection"):
        keys = exposure.get(part)
        if not isinstance(keys, list) or not all(isinstance(k, str) for k in keys):
            raise TrainError(f"exposure.{part} is not a list of deal keys")
        out[part] = set(keys)
    return out


def exposure_of_checkpoint(metadata: Mapping[str, Any], *, path: str) -> dict:
    """The source's cumulative exposure: its persisted block, or -- for a
    checkpoint that predates the block -- its own persisted population's
    fit (train) and selection (val) deals."""
    if isinstance(metadata.get("exposure"), Mapping):
        exposure_sets(metadata["exposure"])
        return dict(metadata["exposure"])
    sets = population_sets(metadata.get("population"))
    return exposure_block(sets["train"], sets["val"], note=(
        f"derived from the persisted population of {path} (the checkpoint predates the "
        "exposure block; its own warm-start ancestors, if any, are unknown)"))


def exposure_conflict(exposure: Mapping[str, Any], assignment: Mapping[str, str]
                      ) -> dict[str, list[str]]:
    """The ancestral deals a new split would not hold out (sorted keys per
    part): ancestral FIT deals assigned to ``val``, ancestral fit-OR-
    selected deals assigned to ``test``.  (A deal an ancestor only selected
    on may stay in val: still tuning-only, never fit; so a warm start on
    the identical split is compatible.)"""
    sets = exposure_sets(exposure)
    return {"val": sorted(k for k, v in assignment.items() if v == "val" and k in sets["fit"]),
            "test": sorted(k for k, v in assignment.items()
                           if v == "test" and k in (sets["fit"] | sets["selection"]))}


def exposure_report(keys: Collection[str], exposure: Mapping[str, Any]) -> dict:
    """How a set of deal keys relates to a cumulative exposure."""
    keys = set(str(k) for k in keys)
    sets = exposure_sets(exposure)
    return {"deals": len(keys), "in_fit": len(keys & sets["fit"]),
            "in_selection": len(keys & sets["selection"]),
            "exposed": len(keys & (sets["fit"] | sets["selection"])),
            "checked_against": dict(exposure["digest"])}


# ------------------------------------------------------------- warm start

def apply_init(model: ValueNetwork, aux_head: AuxPointsHead | None, init: str,
               config: Mapping[str, Any], device: torch.device, *,
               loaded: tuple[ValueNetwork, dict, AuxPointsHead | None] | None = None) -> dict:
    """Load ``init``'s trunk + heads into ``model`` (and the aux head when
    both sides have one); refused unless the architecture, the model
    configuration (hidden widths) and the feature layout (encoder identity,
    ``load_cwv_checkpoint``'s check) all match.  The exposure check
    (``exposure_conflict``) runs on the split, before this."""
    source, metadata, source_aux = (load_cwv_checkpoint(init, device) if loaded is None
                                    else loaded)
    if metadata.get("arch") != config["arch"]:
        raise TrainError(f"--init {init}: arch {metadata.get('arch')!r} != --arch "
                         f"{config['arch']!r}")
    if metadata.get("model_config") != config["model_config"]:
        raise TrainError(f"--init {init}: model configuration differs (theirs "
                         f"{metadata.get('model_config')}, ours {config['model_config']}); "
                         "--hidden / --dropout / seq knobs must match")
    theirs = source.state_dict()
    ours = model.state_dict()
    if set(theirs) != set(ours) or any(theirs[k].shape != ours[k].shape for k in ours):
        raise TrainError(f"--init {init}: parameter layout differs from this model")
    model.load_state_dict(theirs)
    aux_loaded = False
    if aux_head is not None and source_aux is not None:
        if source_aux.linear.in_features != aux_head.linear.in_features:
            raise TrainError(f"--init {init}: aux points head width differs")
        aux_head.load_state_dict(source_aux.state_dict())
        aux_loaded = True
    model.to(device)
    if aux_head is not None:
        aux_head.to(device)
    return {
        "path": str(Path(init).resolve()), "sha256": file_sha256(init),
        "epoch": metadata.get("epoch"), "config_sha256": metadata.get("config_sha256"),
        "git": metadata.get("git"), "aux_points_head_loaded": aux_loaded,
        "aux_points_head_in_init": source_aux is not None,
        "selection": {k: (metadata.get("selection") or {}).get(k)
                      for k in ("metric", "best_epoch", "best_loss", "best_value")},
        "exposure": {k: v for k, v in exposure_of_checkpoint(metadata, path=init).items()
                     if k in ("counts", "digest", "ancestors", "note")},
    }


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
                 public_head: str | None = None, rank_limit: int | None = None,
                 select_metric: str = DEFAULTS["select_metric"],
                 val_rank_records: int = DEFAULTS["val_rank_records"],
                 init: str | None = None,
                 init_lr_scale: float = DEFAULTS["init_lr_scale"],
                 init_exclude_exposed: bool = False) -> dict:
    """Everything that determines the trained model and its metrics."""
    if arch not in ARCHES:
        raise TrainError(f"--arch must be one of {ARCHES}")
    if select_metric not in SELECT_METRICS:
        raise TrainError(f"--select-metric must be one of {tuple(SELECT_METRICS)}")
    if select_metric == "val_points_mae" and not aux_points:
        raise TrainError("--select-metric val_points_mae needs --aux-points")
    if int(val_rank_records) < 0:
        raise TrainError("--val-rank-records must be >= 0 (0 disables the rank pass)")
    if select_metric == "val_rank_regret" and int(val_rank_records) == 0:
        raise TrainError("--select-metric val_rank_regret needs --val-rank-records > 0")
    if not (math.isfinite(float(init_lr_scale)) and float(init_lr_scale) > 0):
        raise TrainError("--init-lr-scale must be a finite scale > 0")
    if init_exclude_exposed and init is None:
        raise TrainError("--init-exclude-exposed needs --init")
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
        "select_metric": select_metric, "val_rank_records": int(val_rank_records),
        "init": None if init is None else str(Path(init).resolve()),
        "init_lr_scale": float(init_lr_scale) if init is not None else 1.0,
        "init_exclude_exposed": bool(init_exclude_exposed),
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
          select_metric: str = DEFAULTS["select_metric"],
          val_rank_records: int = DEFAULTS["val_rank_records"], init: str | None = None,
          init_lr_scale: float = DEFAULTS["init_lr_scale"], init_exclude_exposed: bool = False,
          eval_holdout: Sequence[str] | None = None,
          argv: list[str] | None = None,
          log: Callable[[str], None] | None = print) -> dict:
    """Run the training pipeline; returns the receipt (also written)."""
    holdouts = parse_holdouts(eval_holdout)
    config = build_config(
        data=data, eval_luna=eval_luna, arch=arch, epochs=epochs, seed=seed,
        limit_clusters=limit_clusters, lr=lr, weight_decay=weight_decay,
        batch_size=batch_size, patience=patience, val_fraction=val_fraction,
        test_fraction=test_fraction, hidden=hidden, dropout=dropout, aux_points=aux_points,
        aux_weight=aux_weight, n_boot=n_boot, window=window, seq_kind=seq_kind,
        seq_width=seq_width, seq_layers=seq_layers, seq_heads=seq_heads,
        seq_feedforward=seq_feedforward, public_head=public_head, rank_limit=rank_limit,
        select_metric=select_metric, val_rank_records=val_rank_records, init=init,
        init_lr_scale=init_lr_scale, init_exclude_exposed=init_exclude_exposed)
    config["eval_holdouts"] = dict(holdouts)
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
        f"sees_hidden_hands={SEES_HIDDEN_HANDS} select_metric={select_metric} "
        f"val_rank_records={val_rank_records} init={config['init']}")

    residency = Residency(budget)
    prepared = prepare_stores(data, cache, limit_clusters=limit_clusters, history=history,
                              witness_seed=seed, progress=say, cache_workers=workers,
                              residency=residency)
    store = prepared.block_store
    say(f"residency: {len(store)} shard(s) decode to {store.nbytes} bytes; budget {budget} "
        f"({'fits' if store.nbytes <= budget else 'streams through the LRU'})")
    assignment = split_deals(store.keys(), seed=seed, val_fraction=val_fraction,
                             test_fraction=test_fraction)
    init_loaded = None
    source_exposure = None
    init_excluded = None
    if init is not None:
        init_loaded = load_cwv_checkpoint(init, dev)
        source_exposure = exposure_of_checkpoint(init_loaded[1], path=init)
        conflict = exposure_conflict(source_exposure, assignment)
        n_conflict = {part: len(keys) for part, keys in conflict.items()}
        if any(n_conflict.values()) and not init_exclude_exposed:
            raise TrainError(
                f"--init {init}: {n_conflict['val']} deal(s) the source (or an ancestor) was "
                f"fit on land in this run's val and {n_conflict['test']} fit-or-selected "
                f"deal(s) in its test (exposure fit={source_exposure['counts']['fit']} "
                f"selection={source_exposure['counts']['selection']}); the new val/test "
                "would not be held out from the warm start. Pass --init-exclude-exposed to "
                "drop those deals from val/test (never into train), or change the data/seed")
        for part, keys in conflict.items():
            for key in keys:
                del assignment[key]          # dropped: in no part of this run
        init_excluded = {**n_conflict, "note": "ancestral fit/selection deals removed from "
                                               "this run's val/test by --init-exclude-exposed "
                                               "(never added to train)"}
        say(f"init exposure: source fit={source_exposure['counts']['fit']} "
            f"selection={source_exposure['counts']['selection']} deals; excluded from this "
            f"run's val={n_conflict['val']} test={n_conflict['test']} "
            f"(--init-exclude-exposed={init_exclude_exposed})")
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
    if source_exposure is None:
        exposure = exposure_block(population["train"], population["val"])
    else:
        src = exposure_sets(source_exposure)
        exposure = exposure_block(
            src["fit"] | set(population["train"]), src["selection"] | set(population["val"]),
            ancestors=[*source_exposure.get("ancestors", []),
                       {"path": str(Path(init).resolve()), "sha256": file_sha256(init),
                        "epoch": init_loaded[1].get("epoch"),
                        "counts": dict(source_exposure["counts"]),
                        "digest": dict(source_exposure["digest"])}])
        assert not set(population["val"]) & src["fit"]
        assert not set(population["test"]) & (src["fit"] | src["selection"])
    say(f"exposure: fit={exposure['counts']['fit']} selection={exposure['counts']['selection']} "
        f"deals (ancestors {len(exposure['ancestors'])})")
    baselines = fit_baselines(store, masks["train"])
    say(f"baselines: stratified prior n={baselines['stratified_prior']['n']} "
        f"empty_cells={baselines['stratified_prior']['empty_cells']}")
    val_cands = candidate_set_for(store, set(population["val"]), cache,
                                  n_records=int(val_rank_records), history=history,
                                  workers=eval_workers, label="val", progress=say)
    if val_cands is not None:
        say(f"candidate set (val): {val_cands.records} records / {val_cands.candidates} "
            f"candidates (per-shard cap {val_cands.meta['per_shard_limit']}, "
            f"{val_cands.meta.get('secs', 0)}s)")
    if select_metric == "val_rank_regret" and (val_cands is None or val_cands.records == 0):
        raise TrainError("--select-metric val_rank_regret: the validation split has no "
                         "search record (no action_values means)")

    luna: tuple[Any, CwvBlockStore] | None = None
    luna_prepared: Prepared | None = None
    luna_population = None
    if eval_luna is not None:
        luna_prepared = prepare_stores([eval_luna], cache, limit_clusters=None, history=history,
                                       witness_seed=seed, progress=say, cache_workers=workers,
                                       residency=residency)
        refuse_overlap(store, luna_prepared.block_store, label=f"--eval-luna {eval_luna}")
        luna_population = population_report(luna_prepared.block_store.keys(), population)
        luna_exposure = exposure_report(luna_prepared.block_store.keys(), exposure)
        if luna_exposure["exposed"]:
            raise TrainError(f"--eval-luna {eval_luna} shares {luna_exposure['exposed']} "
                             "deal(s) with the cumulative fit/selection exposure (a warm-start "
                             "ancestor saw them): not held out; refusing")
        luna_population["exposure"] = luna_exposure
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
    init_info = None
    if init is not None:
        init_info = apply_init(model, aux_head, init, config, dev, loaded=init_loaded)
        init_info["excluded"] = init_excluded
        init_info["exclude_exposed"] = bool(init_exclude_exposed)
        say(f"init: {init_info['path']} sha={init_info['sha256'][:12]} "
            f"epoch={init_info['epoch']} aux_head_loaded={init_info['aux_points_head_loaded']} "
            f"lr={lr} x {init_lr_scale}")
    lr_effective = float(lr) * (float(init_lr_scale) if init is not None else 1.0)
    params = list(model.parameters()) + (list(aux_head.parameters()) if aux_head else [])
    optim = torch.optim.AdamW(params, lr=lr_effective, weight_decay=weight_decay)
    rng = np.random.default_rng(seed)
    epoch_rows: list[dict] = []
    best = {"epoch": None, "loss": math.inf}
    selector = Selector(select_metric, patience=patience)
    ckpt_dir = out_dir / "checkpoints"
    ckpt_dir.mkdir(parents=True, exist_ok=True)
    selection = {"split": SELECTION_SPLIT, "criterion": selector.criterion,
                 "metric": select_metric, "metric_key": selector.key, "patience": int(patience),
                 "val_rank_records": int(val_rank_records), "lr_effective": lr_effective}
    consumer = consumer_block(select_metric, aux_points)

    def validate() -> dict:
        ev = run_eval(model, store, masks["val"], dev, batch_size=batch_size, aux_head=aux_head)
        metrics = quick_metrics(ev)
        metrics.update(search_facing(model, ev, val_cands, dev, batch_size=batch_size))
        return metrics

    def epoch_line(tag: str, metrics: Mapping[str, Any], extra: str) -> str:
        # the selected metric first, then the rest (each once)
        shown = {"val_ce": f"val_ce={metrics['loss']:.4f}",
                 "val_mae_pt0": f"val_mae_pt0={metrics['value_mae']:.4f}",
                 "val_rps": f"val_rps={metrics['rps']:.4f}"}
        if metrics.get("rank_regret") is not None:
            shown["val_rank_regret"] = f"val_rank_regret={metrics['rank_regret']:.4f}"
            shown["val_rank_top1"] = f"val_rank_top1={metrics['rank_top1']:.3f}"
        if metrics.get("points_mae") is not None:
            shown["val_points_mae"] = f"val_points_mae={metrics['points_mae']:.2f}"
            shown["val_points_bias"] = f"val_points_bias={metrics['points_bias']:+.2f}"
            shown["val_points_below_banked"] = (
                f"val_points_below_banked={metrics['points_below_banked']:.3f}")
        first = shown.pop(select_metric, f"{select_metric}=n/a")
        return f"{tag} {first} " + " ".join(shown.values()) + extra

    if init_info is not None:
        init_val = validate()
        selection["init_val"] = init_val
        init_info["val"] = init_val
        say(epoch_line("epoch 00 (init, no step)", init_val, " [val = tuning]"))
    identity = cwv_encoder_identity()
    base_metadata = {
        "encoder": identity, "public_encoder": public_encoder_identity(),
        "config": config, "config_sha256": config_sha256(config), "split": split,
        "population": population, "exposure": exposure, "baselines": baselines,
        "git": git_identity(), "receipt_schema": RECEIPT_SCHEMA,
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
        train_secs = round(time.perf_counter() - t0, 3)
        val_metrics = validate()
        secs = round(time.perf_counter() - t0, 3)
        epoch_rows.append({"epoch": epoch, "train": train_metrics, "val": val_metrics,
                           "val_role": SPLIT_ROLES["val"]["role"], "secs": secs,
                           "train_secs": train_secs, "rank_secs": val_metrics["rank_secs"]})
        metadata = {**base_metadata, "epoch": epoch, "selection": {**selection, "val": val_metrics},
                    "aux_points_head": None if aux_head is None else aux_head.payload()}
        save_cwv_checkpoint(ckpt_dir / f"epoch-{epoch:02d}.pt", model, metadata=metadata)
        improved, stop = selector.observe(epoch, val_metrics)
        if improved:
            best = {"epoch": epoch, "loss": float(val_metrics["loss"]),
                    "value": selector.best_value}
            shutil.copyfile(ckpt_dir / f"epoch-{epoch:02d}.pt", out_dir / "best.pt")
        say(epoch_line(f"epoch {epoch:02d}/{epochs}", val_metrics,
                       f" train_ce={train_metrics['cross_entropy']:.4f}"
                       f"{' *' if improved else ''} ({secs}s, rank {val_metrics['rank_secs']}s)"
                       " [val = tuning]"))
        if stop and epoch < epochs:
            say(f"early stop: no {select_metric} improvement for {patience} epochs "
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
    final["test"]["population"]["exposure"] = exposure_report(population["test"], exposure)
    final["val"]["population"]["exposure"] = exposure_report(population["val"], exposure)
    ranking = {"test": ranking_block(test_pass, n_boot=n_boot, seed=seed)}
    final["test"]["ranking"] = ranking["test"]
    test_cands = candidate_set_for(store, test_keys, cache, n_records=int(val_rank_records),
                                   history=history, workers=eval_workers, label="test",
                                   progress=say)
    final["val"]["search_facing"] = search_facing(model, ev_val, val_cands, dev,
                                                  batch_size=batch_size)
    final["test"]["search_facing"] = search_facing(model, ev_test, test_cands, dev,
                                                   batch_size=batch_size)
    for name, cands in (("val", val_cands), ("test", test_cands)):
        final[name]["search_facing"]["candidate_set"] = (
            None if cands is None else {k: v for k, v in cands.meta.items() if k != "encoder"})
    holdout_report = holdout_blocks(
        holdouts, model=model, aux_head=aux_head, dev=dev, batch_size=batch_size,
        history=history, seed=seed, cache=cache, workers=workers, residency=residency,
        population=population, exposure=exposure, n_boot=n_boot, say=say)
    final["test"]["search_facing"]["holdouts"] = holdout_report
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
    selection = {**selection, "best_epoch": best["epoch"], "best_loss": best["loss"],
                 "best_value": best.get("value")}
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
        "test_rank_regret": final["test"]["search_facing"].get("rank_regret"),
        "test_rank_top1": final["test"]["search_facing"].get("rank_top1"),
        "test_points_mae": final["test"]["search_facing"].get("points_mae"),
        "test_points_bias": final["test"]["search_facing"].get("points_bias"),
        "val_rank_regret": final["val"]["search_facing"].get("rank_regret"),
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
        "exposure": exposure,
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
        "consumer": consumer,
        "init": init_info,
        "holdouts": holdout_report,
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
                                           "consumer": consumer, "init": init_info,
                                           "holdouts": holdout_report,
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
        sf = block.get("search_facing") or {}
        if sf.get("rank_regret") is not None:
            line += (f" | search-facing: rank_regret={sf['rank_regret']:.4f} "
                     f"rank_top1={sf['rank_top1']:.3f} (n={sf['rank_records']})")
        if sf.get("points_mae") is not None:
            line += (f" points_mae={sf['points_mae']:.2f} points_bias={sf['points_bias']:+.2f} "
                     f"below_banked={sf['points_below_banked']:.3f}")
        say(line)
        for hname, hb in (sf.get("holdouts") or {}).items():
            hline = f"final {name} holdout {hname}:"
            if hb.get("rank_regret") is not None:
                hline += f" rank_regret={hb['rank_regret']:.4f} rank_top1={hb['rank_top1']:.3f}"
            if hb.get("cross_entropy") is not None:
                hline += f" ce={hb['cross_entropy']:.4f} value_mae={hb['value_mae']:.4f}"
            if hb.get("points_mae") is not None:
                hline += f" points_mae={hb['points_mae']:.2f}"
            if hb.get("skipped"):
                hline += f" skipped={sorted(hb['skipped'])}"
            say(hline)
    say(f"wall={wall}s")


# ---------------------------------------------------------------- evaluate

def evaluate(*, checkpoint: str, out: str | os.PathLike, data: Sequence[str] | None = None,
             eval_luna: str | None = None, device: str | None = None, split: str = "test",
             limit_clusters: int | None = None, n_boot: int | None = None,
             batch_size: int | None = None, public_head: str | None = None,
             rank_limit: int | None = None, cache_dir: str | None = None,
             cache_workers: int | None = None, eval_workers: int | None = None,
             resident_bytes: int | None = None, bench_batch: int = DEFAULTS["bench_batch"],
             eval_holdout: Sequence[str] | None = None,
             argv: list[str] | None = None,
             log: Callable[[str], None] | None = print) -> dict:
    """Score a checkpoint against populations checked against the deal
    identities it was fitted and selected on (``train_v0.evaluate``'s
    rules)."""
    holdouts = parse_holdouts(eval_holdout)
    if not data and not eval_luna and not holdouts:
        raise TrainError("evaluate needs --data DIR, --eval-luna PATH and/or "
                         "--eval-holdout NAME=PATH")
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
    exposure = exposure_of_checkpoint(metadata, path=str(checkpoint))
    exposed = exposure_sets(exposure)
    exposed_all = exposed["fit"] | exposed["selection"]
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
        match["exposure"] = exposure_report(data_keys, exposure)
        say(f"population: store deals={match['deals']} in_train={match['in_train']} "
            f"in_val={match['in_val']} in_test={match['in_test']} novel={match['novel']} "
            f"(exposed to a warm-start ancestor: {match['exposure']['exposed']})")
        parts = {"train": sets["train"], "val": sets["val"], "test": sets["test"],
                 "novel": data_keys - sets["train"] - sets["val"] - sets["test"] - exposed_all,
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
        cands = candidate_set_for(store, selected, cache,
                                  n_records=int(config.get("val_rank_records",
                                                           DEFAULTS["val_rank_records"])),
                                  history=history, workers=eval_workers, label=split,
                                  progress=say)
        metrics["search_facing"] = search_facing(model, ev, cands, dev, batch_size=batch_size)
        metrics["search_facing"]["candidate_set"] = (
            None if cands is None else {k: v for k, v in cands.meta.items() if k != "encoder"})
        if split == "all":
            block = {**metrics, "split": "all", "held_out": False,
                     "role": "every row of the store (whatever part); not held out"}
        else:
            block = labelled(split, metrics)
        block["population"] = population_report(selected, population)
        block["population"]["exposure"] = exposure_report(selected, exposure)
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
        luna_population["exposure"] = exposure_report(luna_prepared.block_store.keys(), exposure)
        shared = luna_population["shared_with_fit"] + luna_population["shared_with_selection"]
        if shared:
            raise TrainError(f"--eval-luna {eval_luna} shares {shared} deal(s) with the "
                             "checkpoint's fit/selection population: not held out; refusing")
        if luna_population["exposure"]["exposed"]:
            raise TrainError(f"--eval-luna {eval_luna} shares "
                             f"{luna_population['exposure']['exposed']} deal(s) with the "
                             "cumulative fit/selection exposure (a warm-start ancestor saw "
                             "them): not held out; refusing")
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
    holdout_report = holdout_blocks(
        holdouts, model=model, aux_head=aux_head, dev=dev, batch_size=batch_size,
        history=history, seed=int(config["seed"]), cache=cache, workers=workers,
        residency=residency, population=population, exposure=exposure, n_boot=n_boot, say=say)
    if data:
        final[split]["search_facing"]["holdouts"] = holdout_report
    bench = (bench_inference(model, bench_rows(bench_source, int(bench_batch)))
             if bench_source else None)
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
        "exposure": exposure,
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
        "consumer": consumer_block(str(config.get("select_metric", DEFAULTS["select_metric"])),
                                   bool(aux_head is not None)),
        "init": (metadata.get("config") or {}).get("init"),
        "holdouts": holdout_report,
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
                                           "holdouts": holdout_report,
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
        p.add_argument("--eval-holdout", action="append", default=None, metavar="NAME=PATH",
                       help="labelled harvest file (scripts/label_harvest.py) scored as a "
                            "search-facing holdout under search_facing.holdouts.NAME "
                            "(repeatable)")

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
    t.add_argument("--select-metric", choices=tuple(SELECT_METRICS),
                   default=DEFAULTS["select_metric"],
                   help="early stopping + best.pt on this validation metric (default val_ce; "
                        "val_rank_regret is the recommendation for the ranking consumers, "
                        "val_points_mae for the vleaf leaf)")
    t.add_argument("--val-rank-records", type=int, default=DEFAULTS["val_rank_records"],
                   help="search records of the val (and test) split in the candidate set "
                        "(per shard: ceil(N / shards)); 0 disables the rank pass")
    t.add_argument("--init", default=None,
                   help="warm start: a train_cwv checkpoint of the same arch / hidden / "
                        "feature layout whose trunk and heads are loaded")
    t.add_argument("--init-lr-scale", type=float, default=DEFAULTS["init_lr_scale"],
                   help="multiply --lr by this with --init")
    t.add_argument("--init-exclude-exposed", action="store_true",
                   help="with --init: drop the source's (and its ancestors') fit/selection "
                        "deals from this run's val/test instead of refusing (never into train)")

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
                   bench_batch=args.bench_batch, eval_holdout=args.eval_holdout,
                   argv=full_argv, log=log)
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
                  seq_feedforward=args.seq_feedforward, select_metric=args.select_metric,
                  val_rank_records=args.val_rank_records, init=args.init,
                  init_lr_scale=args.init_lr_scale,
                  init_exclude_exposed=args.init_exclude_exposed, **exec_kw)
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
