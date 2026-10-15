"""Score saved CWV checkpoints and numpy packages on the same held-out deals.

    served_rank_regret.py --model LABEL=PATH [--model ...] --data DIR [--data ...]
        --out DIR [--cache-dir DIR] [--deals-file JSON] [--per-bucket 2] [--seed 0]
        [--old-per-shard 1] [--exposure-checkpoint CKPT ...] [--workers 1] [--threads 1]
        [--resident-bytes 2147483648]

For every model, on every deal of the ``--data`` stores (or the
``--deals-file`` subset):

* ``val_ce``: the 204-class cross-entropy over every encoded row of those
  deals (``train_cwv.run_eval``'s rows and arithmetic);
* ``rank_regret``: the trainer's metric (``cwv_eval.rank_metrics``) on the
  candidate set the trainer builds at ``--old-per-shard`` records per deal;
* the served-leaf ranking (``served_rank.served_rank_metrics``) at
  ``--per-bucket`` records per deal and trick bucket, with deal-clustered
  standard errors.

A ``.pt`` path loads through ``train_cwv.load_cwv_checkpoint``; a ``.npz``
path is a numpy serving package (``ai.cwv_numpy``).  Every model must be
held out on the deals: a deal in a model's cumulative FIT exposure refuses
the run.  Its selection deals are allowed and counted, since scoring a run's
own epochs on its validation deals is the point.  A package carries no
exposure lists, so ``--exposure-checkpoint`` must name the checkpoint it was
exported from (matched by sha256).  Writes ``scores.json`` and per-record
arrays ``records.npz`` under ``--out``.  Each model's result is saved as it
finishes (``models/<label>.json`` / ``.npz``) and a rerun of the same command
scores only the models without one, so a stopped run resumes per checkpoint.
"""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Callable, Mapping, Sequence

import numpy as np
import torch

from ..rl.value_checkpoint import file_sha256
from .cwv_data import CwvBlockStore, collate, expected_levels, prepare_stores, tensors_of
from .cwv_eval import (
    CandidateSet,
    EvalError,
    candidate_tensors,
    ensure_candidate_set,
    rank_metrics,
)
from .data import TrainDataError
from .served_rank import (
    BUCKET_NAMES,
    balanced_with_se,
    clustered_se,
    ensure_served_set,
    served_rank_metrics,
    served_rank_rows,
)
from .train_cwv import (
    TrainError,
    exposure_of_checkpoint,
    exposure_sets,
    forward_batch,
    load_cwv_checkpoint,
    rng_guard,
    shard_keys_of,
)


RESCORE_SCHEMA = "shengji-cwv-served-rescore-v1"


class Scorer:
    """One model's 204-class probabilities on batched afterstate tensors."""

    def __init__(self, label: str, path: str, *, exposure_checkpoints: Sequence[str] = ()):
        self.label = label
        self.path = str(Path(path).resolve())
        if self.path.endswith(".npz"):
            from ..ai.cwv_numpy import load_numpy_checkpoint
            self.kind = "package"
            self.model = load_numpy_checkpoint(self.path)
            self.metadata = dict(self.model.metadata)
            self.sha256 = self.model.package_sha256
            source = self.model.source_checkpoint_sha256
            match = [c for c in exposure_checkpoints if file_sha256(c) == source]
            if not match:
                raise TrainError(f"{label}: package {self.path} names source checkpoint "
                                 f"{str(source)[:12]}; pass it as --exposure-checkpoint so its "
                                 "exposure can be checked")
            _model, meta, _aux = load_cwv_checkpoint(match[0], "cpu")
            self.exposure = exposure_of_checkpoint(meta, path=match[0])
            self.exposure_source = str(Path(match[0]).resolve())
            self.enc_version = int(self.model.enc_version)
        else:
            self.kind = "checkpoint"
            self.model, self.metadata, _aux = load_cwv_checkpoint(self.path, "cpu")
            self.sha256 = file_sha256(self.path)
            self.exposure = exposure_of_checkpoint(self.metadata, path=self.path)
            self.exposure_source = self.path
            self.enc_version = int(self.model.config.enc_version)
        self.epoch = self.metadata.get("epoch")

    @torch.no_grad()
    def probabilities(self, t: Mapping[str, torch.Tensor]) -> np.ndarray:
        if self.kind == "checkpoint":
            logits, _aux = forward_batch(self.model, t)
            return torch.softmax(logits.to(torch.float32), dim=1).cpu().numpy().astype(np.float64)
        return np.asarray(self.model.probabilities(
            t["public"].numpy(), t["world"].numpy(), t["perspective"].numpy()), dtype=np.float64)

    @torch.no_grad()
    def row_ce(self, t: Mapping[str, torch.Tensor]) -> np.ndarray:
        """Per-row CE as ``train_cwv.run_eval`` computes it (float32 log-softmax)."""
        target = t["target"]
        if self.kind == "checkpoint":
            logits, _aux = forward_batch(self.model, t)
            logp = torch.log_softmax(logits.to(torch.float32), dim=1)
            return -logp.gather(1, target.unsqueeze(1)).squeeze(1).cpu().numpy().astype(np.float64)
        prob = self.probabilities(t)
        picked = prob[np.arange(prob.shape[0]), target.numpy()]
        return -np.log(np.maximum(picked, 1e-300))


def candidate_levels_of(scorer: Scorer, cands: CandidateSet, *, batch_size: int) -> np.ndarray:
    """``cwv_eval.candidate_levels`` for any ``Scorer``."""
    n = cands.candidates
    levels = np.empty(n, dtype=np.float64)
    for lo in range(0, n, batch_size):
        hi = min(n, lo + batch_size)
        levels[lo:hi] = expected_levels(
            scorer.probabilities(candidate_tensors(cands.batch_entry(lo, hi), "cpu")))[0]
    return np.where(cands.terminal, cands.terminal_level, levels)


def store_ce(scorer: Scorer, store, *, batch_size: int) -> dict:
    """CE over every row of ``store``, with its deal-clustered SE and the
    per-deal sums (``_deal_*``, for paired comparisons)."""
    ces: list[np.ndarray] = []
    deals: list[np.ndarray] = []
    for block in store.iter_blocks():
        idx_all = np.arange(block.n)
        for b0 in range(0, block.n, batch_size):
            raw = collate(block, idx_all[b0:b0 + batch_size])
            ces.append(scorer.row_ce(tensors_of(raw, "cpu")))
            deals.append(np.asarray(raw["deal_key"], dtype=str))
    ce = np.concatenate(ces) if ces else np.zeros(0)
    deal = np.concatenate(deals) if deals else np.zeros(0, dtype=str)
    keys, inverse = np.unique(deal, return_inverse=True)
    return {"rows": int(ce.size), "val_ce": float(ce.mean()) if ce.size else None,
            "val_ce_se": clustered_se(ce, deal) if ce.size else None,
            "_deal_keys": keys, "_deal_ce_sum": np.bincount(inverse, weights=ce),
            "_deal_rows": np.bincount(inverse)}


def _model_done(models_dir: Path, label: str, file_sha: str, run_key: str) -> dict | None:
    """The saved result of ``label`` when it is this run's and this file's."""
    path = models_dir / f"{label}.json"
    if not path.is_file() or not (models_dir / f"{label}.npz").is_file():
        return None
    try:
        saved = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    if saved.get("file_sha256") != file_sha or saved.get("run_key") != run_key:
        return None
    return saved


def rescore(models: Sequence[tuple[str, str]], data: Sequence[str], out: str | os.PathLike, *,
            cache_dir: str | os.PathLike | None = None, deals_file: str | None = None,
            per_bucket: int = 2, seed: int = 0, old_per_shard: int = 1, workers: int = 1,
            batch_size: int = 4096, exposure_checkpoints: Sequence[str] = (),
            resident_bytes: int | None = 2 ** 31,
            log: Callable[[str], None] | None = print) -> dict:
    """Score ``models`` (``(label, path)``) on the deals; resumable per model.

    Each model's result is written to ``OUT/models/<label>.json`` / ``.npz``
    as soon as it is scored.  A rerun with the same data, deals and set
    parameters reuses a saved result whose model file has the same sha256,
    and scores only the rest; ``scores.json`` / ``records.npz`` are then
    assembled from every model's files."""
    say = log or (lambda _s: None)
    started = time.perf_counter()
    out = Path(out)
    models_dir = out / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    cache = Path(cache_dir) if cache_dir else out / "cache"
    run_key = hashlib.sha256(json.dumps({
        "schema": RESCORE_SCHEMA, "data": sorted(str(Path(d).resolve()) for d in data),
        "deals_file": None if not deals_file else file_sha256(deals_file),
        "per_bucket": int(per_bucket), "seed": int(seed), "old_per_shard": int(old_per_shard),
    }, sort_keys=True).encode("ascii")).hexdigest()
    done: dict[str, dict] = {}
    pending: list[tuple[str, str]] = []
    for label, path in models:
        saved = _model_done(models_dir, label, file_sha256(path), run_key)
        if saved is None:
            pending.append((label, path))
        else:
            done[label] = saved
    if done:
        say(f"resuming: {sorted(done)} already scored; scoring {[l for l, _ in pending]}")
    # One model is in memory at a time (a checkpoint's metadata carries its whole
    # population); the first pending one is loaded here for the encoder version.
    first = (Scorer(pending[0][0], pending[0][1], exposure_checkpoints=exposure_checkpoints)
             if pending else None)
    versions = ({first.enc_version} if first is not None else set()) \
        | {int(r["enc_version"]) for r in done.values()}
    if len(versions) != 1:
        raise TrainError(f"models encode at different versions {sorted(versions)}")
    version = versions.pop()
    prepared = prepare_stores(list(data), cache, limit_clusters=None, history=False,
                              witness_seed=1, progress=say, cache_workers=workers,
                              version=version, resident_bytes=resident_bytes)
    store = prepared.block_store
    keys = set(store.keys())
    if deals_file:
        wanted = set(json.loads(Path(deals_file).read_text())["deal_keys"])
        missing = wanted - keys
        if missing:
            raise TrainError(f"--deals-file names {len(missing)} deal(s) not in --data")
        keys = wanted
    if deals_file:
        keep = [keys for _ in store.entries]
        store = CwvBlockStore(store.entries, residency=store.residency, keep=keep)
    shard_keys = shard_keys_of(store, keys)
    with rng_guard():
        old = ensure_candidate_set(shard_keys, cache, per_shard_limit=int(old_per_shard),
                                   history=False, workers=workers, label="old", progress=say,
                                   version=version)
        served = ensure_served_set(shard_keys, cache, per_bucket=int(per_bucket), seed=int(seed),
                                   workers=workers, label="served", progress=say,
                                   version=version)
    digests = {"old": old.meta["digest"], "served": served.meta["digest"]}
    for label, saved in done.items():
        if saved.get("set_digests") != digests:
            raise TrainError(f"{label}: its saved result was scored on other candidate sets; "
                             f"remove {models_dir / label}.json to rescore it")
    say(f"old set {old.records} records / {old.candidates} candidates; served set "
        f"{served.records} records / {served.candidates} candidates "
        f"({ {b: int((served.buckets() == b).sum()) for b in BUCKET_NAMES} })")
    for label, path in pending:
        t0 = time.perf_counter()
        s, first = (first, None) if first is not None else (
            Scorer(label, path, exposure_checkpoints=exposure_checkpoints), None)
        if s.enc_version != version:
            raise TrainError(f"{label}: encoder v{s.enc_version}, the others v{version}")
        sets = exposure_sets(s.exposure)
        exposure = {"fit": len(keys & sets["fit"]), "selection": len(keys & sets["selection"])}
        if exposure["fit"]:
            raise TrainError(f"{label}: {exposure['fit']} of the {len(keys)} deals are in its "
                             "fit exposure; not held out")
        del sets
        s.exposure = s.metadata = None
        say(f"{label}: {len(keys)} deals held out (selection overlap {exposure['selection']})")
        ce = store_ce(s, store, batch_size=batch_size)
        arrays = {"ce_deal_key": ce.pop("_deal_keys").astype(str),
                  "ce_deal_rows": ce.pop("_deal_rows"),
                  "ce_deal_sum": ce.pop("_deal_ce_sum")}
        old_levels = candidate_levels_of(s, old, batch_size=batch_size)
        old_block = rank_metrics(old_levels, old)
        old_regret = _old_regret_rows(old_levels, old)
        sv_levels = candidate_levels_of(s, served.cands, batch_size=batch_size)
        sv_block = served_rank_metrics(sv_levels, served)
        rows = served_rank_rows(sv_levels, served)
        buckets = rows["bucket"].astype(str)
        deal = rows["deal_key"]
        bal, bal_se = balanced_with_se(rows["regret"], buckets, deal)
        bal_p, bal_p_se = balanced_with_se(rows["regret_points"], buckets, deal)
        bal_s, bal_s_se = balanced_with_se(rows["search_regret"], buckets, deal)
        result = {
            "path": s.path, "kind": s.kind, "sha256": s.sha256, "epoch": s.epoch,
            "file_sha256": file_sha256(s.path), "run_key": run_key, "set_digests": digests,
            "enc_version": int(s.enc_version),
            "exposure_source": s.exposure_source, "exposure": exposure,
            **ce,
            "rank_regret": old_block["rank_regret"],
            "rank_regret_se": clustered_se(old_regret, old.deal_key.astype(str)),
            "rank_top1": old_block["rank_top1"], "rank_records": old_block["rank_records"],
            "served_rank_regret": bal, "served_rank_regret_se": bal_se,
            "served_rank_regret_points": bal_p, "served_rank_regret_points_se": bal_p_se,
            "served_search_regret": bal_s, "served_search_regret_se": bal_s_se,
            "served": {k: v for k, v in sv_block.items() if k != "served_definition"},
            "secs": round(time.perf_counter() - t0, 1),
        }
        for name in ("regret", "regret_points", "search_regret", "top1"):
            arrays[f"served_{name}"] = rows[name]
        arrays["old_regret"] = old_regret
        # the arrays first, then the json that marks the model as done
        tmp = models_dir / f"{s.label}.{os.getpid()}.tmp.npz"
        np.savez_compressed(tmp, **arrays)
        os.replace(tmp, models_dir / f"{s.label}.npz")
        tmp = models_dir / f"{s.label}.{os.getpid()}.tmp.json"
        tmp.write_text(json.dumps(result, indent=1, sort_keys=True))
        os.replace(tmp, models_dir / f"{s.label}.json")
        done[label] = result
        del s
        gc.collect()
        say(f"{label}: val_ce={result['val_ce']:.4f} rank_regret={result['rank_regret']:.4f} "
            f"served={bal:.4f}+-{bal_se:.4f} points={bal_p:.2f} search={bal_s:.4f} by trick "
            + "/".join(f"{sv_block['served_by_trick'][b]['regret']:.4f}" for b in BUCKET_NAMES
                       if sv_block['served_by_trick'][b]['records'])
            + f" ({result['secs']}s)")
    merged: dict[str, np.ndarray] = {
        "old_deal_key": old.deal_key.astype(str),
        "served_deal_key": served.cands.deal_key.astype(str),
        "served_bucket": served.buckets().astype(str), "served_trick": served.trick,
        "served_units_code": served.cands.units_code}
    for label, _path in models:
        with np.load(models_dir / f"{label}.npz", allow_pickle=False) as npz:
            for shared in ("ce_deal_key", "ce_deal_rows"):
                if shared in merged and not np.array_equal(merged[shared], npz[shared]):
                    raise TrainError(f"{label}: its rows differ from the other models'")
                merged[shared] = npz[shared]
            merged[f"{label}__ce_deal_sum"] = npz["ce_deal_sum"]
            merged[f"{label}__old_regret"] = npz["old_regret"]
            for name in ("regret", "regret_points", "search_regret", "top1"):
                merged[f"{label}__served_{name}"] = npz[f"served_{name}"]
    report = {
        "schema": RESCORE_SCHEMA,
        "deals": len(keys), "data": [str(Path(d).resolve()) for d in data],
        "deals_file": deals_file, "per_bucket": int(per_bucket), "seed": int(seed),
        "old_per_shard": int(old_per_shard), "run_key": run_key,
        "old_set": {k: v for k, v in old.meta.items() if k != "encoder"},
        "served_set": {k: v for k, v in served.meta.items() if k != "encoder"},
        "models": {label: done[label] for label, _path in models},
        "wall_secs": round(time.perf_counter() - started, 1),
    }
    (out / "scores.json").write_text(json.dumps(report, indent=1, sort_keys=True))
    np.savez_compressed(out / "records.npz", **merged)
    return report


def _old_regret_rows(levels: np.ndarray, cands: CandidateSet) -> np.ndarray:
    """Per-record ``rank_regret`` (``cwv_eval.rank_metrics``' k = 1 term)."""
    ml = cands.means_level()
    out = np.empty(cands.records)
    for r in range(cands.records):
        lo, hi = int(cands.offsets[r]), int(cands.offsets[r + 1])
        s = levels[lo:hi]
        top = np.flatnonzero(s == s.max())
        out[r] = ml[lo:hi].max() - ml[lo:hi][top].mean()
    return out


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="served_rank_regret", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--model", action="append", required=True, metavar="LABEL=PATH")
    p.add_argument("--data", action="append", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--cache-dir", default=None)
    p.add_argument("--deals-file", default=None,
                   help='JSON {"deal_keys": [...]}: score only these deals of --data')
    p.add_argument("--per-bucket", type=int, default=2)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--old-per-shard", type=int, default=1,
                   help="records per deal of the trainer's candidate set (1 = what "
                        "--val-rank-records 20000 gives on a split of more than 20,000 deals)")
    p.add_argument("--exposure-checkpoint", action="append", default=[],
                   help="the checkpoint a --model package was exported from")
    p.add_argument("--workers", type=int, default=1)
    p.add_argument("--threads", type=int, default=1, help="torch CPU threads")
    p.add_argument("--batch-size", type=int, default=4096)
    p.add_argument("--resident-bytes", type=int, default=2 ** 31,
                   help="decoded row blocks kept in memory (LRU; default 2 GiB)")
    return p


def main(argv: list[str] | None = None) -> int:
    os.environ.setdefault("SHENGJI_REQUIRE_VOIDS", "1")
    args = build_parser().parse_args(argv)
    torch.set_num_threads(max(1, int(args.threads)))
    models = []
    for spec in args.model:
        label, sep, path = spec.partition("=")
        if not sep or not label or not path:
            print(f"REFUSING: --model {spec!r}: expected LABEL=PATH", file=sys.stderr)
            return 2
        models.append((label, path))
    try:
        rescore(models, args.data, args.out, cache_dir=args.cache_dir,
                deals_file=args.deals_file, per_bucket=args.per_bucket, seed=args.seed,
                old_per_shard=args.old_per_shard, workers=args.workers,
                batch_size=args.batch_size, exposure_checkpoints=args.exposure_checkpoint,
                resident_bytes=args.resident_bytes,
                log=lambda line: print(line, flush=True))
    except (TrainError, TrainDataError, EvalError) as exc:
        print(f"REFUSING: {exc}", file=sys.stderr)
        return 2
    print(f"scores -> {Path(args.out) / 'scores.json'}", flush=True)
    return 0


__all__ = ["Scorer", "build_parser", "candidate_levels_of", "main", "rescore", "store_ce"]
