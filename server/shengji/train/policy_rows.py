"""Root-state rows for the joint net's policy head (#425).

A root row is what ``policy_prior.extract`` writes: the flat encoder-v2
tensors of a decision root from the MOVER's seat (``public | world |
perspective``), the played action as a 54-card multi-hot, and the search's
ballot for the listwise term.  These rows are a second dataset next to the
afterstate value cache: the trainer draws one root batch per value batch and
adds the policy losses; a twin drawing the same batches with ``policy_weight
0`` is the matched control.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import torch

from .policy_prior import (INPUT_DIM, MAX_LEGAL, _rank_rows, _report, ballot_tensors, listwise_loss)

SCHEMA = "shengji-policy-rows-v1"


def _file_sha256(path: str | Path) -> str:
    with open(path, "rb") as fh:
        return hashlib.file_digest(fh, "sha256").hexdigest()


def _read_meta(path: str | Path, limit: int | None, keys: tuple[str, ...]):
    out = []
    with open(path) as fh:
        for line in fh:
            if limit is not None and len(out) >= limit:
                break
            m = json.loads(line)
            out.append({k: m.get(k) for k in keys})
    return out


def _deal_keys_of(meta, what: str) -> list[str]:
    keys = [m.get("deal_key") for m in meta]
    if any(not isinstance(k, str) or not k.startswith("deck:") for k in keys):
        raise ValueError(f"{what}: every row needs a full deal_key (re-extract with policy_prior "
                         "at or after #428); root deals are training exposure and must be "
                         "checked against the held-out splits")
    return keys


def _digest(keys) -> str:
    return hashlib.sha256("\n".join(sorted(set(keys))).encode()).hexdigest()


class PolicyRows:
    """The training root rows: ``X`` kept as float16, ballots padded once.
    Rows whose deal is in ``exclude`` (the value run's val/test, the policy
    eval deals, ...) are DROPPED before anything is kept: the policy loss
    updates the shared trunk, so a root deal is a fit exposure (#428)."""

    def __init__(self, prefix: str | Path, *, limit: int | None = None,
                 exclude: set[str] | frozenset[str] = frozenset()):
        prefix = str(prefix)
        d = np.load(prefix + ".npz")
        X, Y = d["X"], d["Y"]
        if X.ndim != 2 or X.shape[1] != INPUT_DIM or Y.shape != (len(X), 54):
            raise ValueError("policy rows: unexpected X/Y layout")
        n = len(X) if not limit else min(int(limit), len(X))
        if n < 1:
            raise ValueError("policy rows: no rows")
        meta = _read_meta(prefix + ".meta.jsonl", n, ("ballot", "taken", "deal", "deal_key"))
        if len(meta) != n:
            raise ValueError("policy rows: metadata shorter than the rows")
        keys = _deal_keys_of(meta, "policy rows")
        keep = np.fromiter((k not in exclude for k in keys), dtype=bool, count=n)
        excluded_deals = {k for k in keys if k in exclude}
        if not keep.any():
            raise ValueError("policy rows: every row is in an excluded deal")
        idx = np.flatnonzero(keep)
        self.X = np.ascontiguousarray(X[:n][idx]).astype(np.float16)
        self.Y = np.ascontiguousarray(Y[:n][idx]).astype(np.uint8)
        meta = [meta[i] for i in idx]
        ball, mask, tgt = ballot_tensors(meta)
        self.ball, self.mask, self.tgt = ball, mask, tgt
        self.n = int(len(idx))
        self.deal_keys = frozenset(m["deal_key"] for m in meta)
        self.deals = len(self.deal_keys)
        self.in_ballot = int((tgt >= 0).sum())
        self.identity = {"schema": SCHEMA, "prefix": str(Path(prefix).resolve()),
                         "npz_sha256": _file_sha256(prefix + ".npz"), "rows_available": int(len(X)),
                         "rows_read": n, "rows_used": self.n, "rows_excluded": int(n - len(idx)),
                         "deals": self.deals, "deals_excluded": len(excluded_deals),
                         "deal_key_schema": "shengji-value-deal-key-v1",
                         "fit_deals_digest": _digest(self.deal_keys),
                         "rows_with_ballot_target": self.in_ballot}

    def batches(self, batch_size: int, rng: np.random.Generator):
        """One pass in a fresh permutation, yielding numpy batches; the caller cycles passes."""
        perm = rng.permutation(self.n)
        for start in range(0, self.n, batch_size):
            idx = perm[start:start + batch_size]
            yield {"x": self.X[idx], "y": self.Y[idx], "ball": self.ball[idx], "mask": self.mask[idx], "tgt": self.tgt[idx]}

    @staticmethod
    def tensors(batch: Mapping[str, Any], device) -> dict[str, torch.Tensor]:
        return _to_device(batch, device)


def _to_device(batch: Mapping[str, Any], device) -> dict[str, torch.Tensor]:
    def t(v, dtype=None):
        v = torch.as_tensor(v) if not isinstance(v, torch.Tensor) else v
        return (v.to(dtype) if dtype is not None else v).to(device)
    return {"x": t(np.asarray(batch["x"], dtype=np.float32)), "y": t(np.asarray(batch["y"], dtype=np.float32)),
            "ball": t(batch["ball"]), "mask": t(batch["mask"], torch.bool), "tgt": t(batch["tgt"], torch.long)}


class PolicyRowsStream:
    """Root rows from a chunked extraction (``policy_prior.extract --chunk-rows``):
    the manifest is read once (deal keys per chunk for the exposure rule), and
    each pass streams the chunks in a fresh order, ``window`` chunks in memory
    at a time with rows shuffled inside the window, so every root decision of
    the corpus can train the head without a memory cap.  Rows on ``exclude``
    deals are dropped per chunk; ``limit`` caps the rows drawn per pass."""

    def __init__(self, directory: str | Path, *, limit: int | None = None,
                 exclude: set[str] | frozenset[str] = frozenset(), window: int = 4):
        from .policy_prior import CHUNK_SCHEMA
        self.dir = Path(directory)
        man = json.load(open(self.dir / "manifest.json"))
        if man.get("schema") != CHUNK_SCHEMA or man.get("input_dim") != INPUT_DIM:
            raise ValueError("policy rows stream: manifest schema drift")
        self.chunks = man["chunks"]
        if not self.chunks:
            raise ValueError("policy rows stream: no chunks")
        self.exclude = frozenset(exclude)
        self.window = max(1, int(window))
        self.limit = None if not limit else int(limit)
        # One verification pass at construction (the first-consumption boundary):
        # every chunk's SHA256 must equal the manifest's, and its arrays must be
        # row-aligned with the recorded count.  A replaced or truncated chunk
        # refuses here; passes never re-hash.
        keys: set[str] = set(); excluded: set[str] = set(); rows_used = 0; in_ballot = 0; verified: list[str] = []
        for c in self.chunks:
            path = self.dir / c["file"]
            if not path.exists():
                raise ValueError(f"policy rows stream: missing {c['file']}")
            actual = _file_sha256(path)
            if actual != c["sha256"]:
                raise ValueError(f"policy rows stream: {c['file']} SHA256 differs from the manifest (tampered or rewritten)")
            d = np.load(path)
            n = int(c["rows"])
            if (d["X"].ndim != 2 or d["X"].shape != (n, INPUT_DIM) or d["Y"].shape != (n, 54)
                    or d["ball"].shape[0] != n or d["mask"].shape[0] != n or d["tgt"].shape != (n,)
                    or d["deal_key"].shape != (n,) or d["ball"].shape[1] != d["mask"].shape[1]):
                raise ValueError(f"policy rows stream: {c['file']} arrays are not row-aligned with the manifest")
            verified.append(actual)
            dk = d["deal_key"].astype(str); keep = np.fromiter((k not in self.exclude for k in dk), dtype=bool, count=len(dk))
            keys.update(dk[keep].tolist()); excluded.update(dk[~keep].tolist())
            rows_used += int(keep.sum()); in_ballot += int((d["tgt"][keep] >= 0).sum())
        if rows_used < 1:
            raise ValueError("policy rows stream: every row is in an excluded deal")
        self.deal_keys = frozenset(keys)
        self.deals = len(self.deal_keys)
        self.n = rows_used
        self.in_ballot = in_ballot
        self.identity = {"schema": SCHEMA, "format": CHUNK_SCHEMA, "prefix": str(self.dir.resolve()),
                         "npz_sha256": _digest(verified), "chunks_verified": len(verified),
                         "rows_available": int(man["rows"]), "rows_read": int(man["rows"]), "rows_used": rows_used,
                         "rows_excluded": int(man["rows"]) - rows_used, "rows_per_pass": min(rows_used, self.limit or rows_used),
                         "deals": self.deals, "deals_excluded": len(excluded), "chunks": len(self.chunks),
                         "window_chunks": self.window, "deal_key_schema": "shengji-value-deal-key-v1",
                         "fit_deals_digest": _digest(self.deal_keys), "rows_with_ballot_target": in_ballot,
                         "split": man.get("split")}

    def _load(self, c: dict) -> dict[str, np.ndarray]:
        d = np.load(self.dir / c["file"])
        dk = d["deal_key"].astype(str)
        keep = np.fromiter((k not in self.exclude for k in dk), dtype=bool, count=len(dk))
        return {k: d[k][keep] for k in ("X", "Y", "ball", "mask", "tgt")}

    def batches(self, batch_size: int, rng: np.random.Generator):
        """One pass: chunks in a fresh order, ``window`` at a time, rows shuffled within the window."""
        order = rng.permutation(len(self.chunks)); drawn = 0
        for start in range(0, len(order), self.window):
            parts = [self._load(self.chunks[i]) for i in order[start:start + self.window]]
            X = np.concatenate([p["X"] for p in parts]); Y = np.concatenate([p["Y"] for p in parts])
            ball = _pad_concat([p["ball"] for p in parts], -1); mask = np.concatenate([_pad2(p["mask"], ball.shape[1], False) for p in parts])
            tgt = np.concatenate([p["tgt"] for p in parts])
            perm = rng.permutation(len(X))
            for b in range(0, len(perm), batch_size):
                if self.limit is not None and drawn >= self.limit:
                    return
                idx = perm[b:b + batch_size]
                if self.limit is not None:
                    idx = idx[:self.limit - drawn]          # the budget is exact, never a partial overshoot
                drawn += len(idx)
                yield {"x": X[idx], "y": Y[idx], "ball": ball[idx], "mask": mask[idx], "tgt": tgt[idx]}

    @staticmethod
    def tensors(batch: Mapping[str, Any], device) -> dict[str, torch.Tensor]:
        return _to_device(batch, device)


def _pad2(a: np.ndarray, width: int, fill) -> np.ndarray:
    if a.shape[1] == width:
        return a
    out = np.full((a.shape[0], width), fill, dtype=a.dtype); out[:, :a.shape[1]] = a; return out


def _pad_concat(arrays, fill) -> np.ndarray:
    """Concatenate (n, B, C) int8 ballot arrays whose B and C differ per chunk."""
    B = max(a.shape[1] for a in arrays); C = max(a.shape[2] for a in arrays)
    out = []
    for a in arrays:
        o = np.full((a.shape[0], B, C), fill, dtype=a.dtype); o[:, :a.shape[1], :a.shape[2]] = a; out.append(o)
    return np.concatenate(out)


def open_policy_rows(path: str | Path, *, limit: int | None = None, exclude=frozenset()):
    """A chunked directory streams; a ``<prefix>.npz`` loads in memory."""
    p = Path(path)
    if p.is_dir() and (p / "manifest.json").exists():
        return PolicyRowsStream(p, limit=limit, exclude=exclude)
    return PolicyRows(p, limit=limit, exclude=exclude)


def policy_losses(model, t: Mapping[str, torch.Tensor], *, listwise_weight: float, detach: bool = False):
    """``(bce, listwise, logits)`` of the policy head on one root batch.  With
    ``detach`` the head reads the trunk features through a stop-gradient: the
    policy loss trains the head only and never moves the shared trunk (#425
    step after J1: the head's recall on frozen value features at zero value cost)."""
    features = model.features_flat(t["x"])
    if detach:
        features = features.detach()
    logits = model.policy_logits(features)
    bce = torch.nn.functional.binary_cross_entropy_with_logits(logits, t["y"])
    lw = listwise_loss(logits, t["ball"], t["mask"], t["tgt"]) if listwise_weight > 0 \
        else logits.sum() * 0.0
    return bce, lw, logits


def policy_log_odds(model, X: np.ndarray, device, batch_size: int = 2048) -> np.ndarray:
    out = []
    model.eval()
    with torch.no_grad():
        for start in range(0, len(X), batch_size):
            x = torch.from_numpy(np.asarray(X[start:start + batch_size], dtype=np.float32)).to(device)
            out.append(model.policy_logits(model.features_flat(x)).float().cpu().numpy())
    return np.concatenate(out) if out else np.zeros((0, 54), np.float32)


class PolicyEval:
    """Held-out root rows (the #419 probe set, with deal keys) read once.
    Rows whose deal is in ``exclude`` (the value run's fit deals) are dropped
    so the reported recall is on deals the trunk never trained on."""

    def __init__(self, prefix: str | Path, *, exclude: set[str] | frozenset[str] = frozenset()):
        prefix = str(prefix)
        d = np.load(prefix + ".npz")
        X = d["X"]
        meta = [json.loads(l) for l in open(prefix + ".meta.jsonl")]
        if len(meta) != len(X):
            raise ValueError("policy eval: metadata/rows mismatch")
        keys = _deal_keys_of(meta, "policy eval")
        keep = [k not in exclude for k in keys]
        if not any(keep):
            raise ValueError("policy eval: every row is in an excluded deal")
        idx = np.flatnonzero(np.asarray(keep, dtype=bool))
        self.X = X[idx]
        self.meta = [meta[i] for i in idx]
        self.deal_keys = frozenset(m["deal_key"] for m in self.meta)
        self.identity = {"prefix": str(Path(prefix).resolve()), "npz_sha256": _file_sha256(prefix + ".npz"),
                         "rows_available": int(len(X)), "rows": int(len(idx)),
                         "rows_excluded": int(len(X) - len(idx)), "deals": len(self.deal_keys),
                         "deals_excluded": len({k for k in keys if k in exclude}),
                         "deal_key_schema": "shengji-value-deal-key-v1", "deals_digest": _digest(self.deal_keys)}

    def run(self, model, device) -> dict[str, Any]:
        """``policy_prior.evaluate``'s report for the joint net's head, plus a
        compact ``top64`` map ``"<stratum> <lo>-<hi>" -> recall`` and deals."""
        lo = policy_log_odds(model, self.X, device)
        report = _report(_rank_rows(lo, self.meta), len(self.meta), None)
        top64, deals = {}, {}
        for stratum, recs in report["strata"].items():
            for r in recs:
                key = f"{stratum} {r['bucket'][0]}-{min(r['bucket'][1], 10 ** 6)}"
                top64[key] = r["taken_recall"]["64"]; deals[key] = r["deals"]
        return {"top64": top64, "deals": deals, "counters": report["counters"],
                "strata": report["strata"], "text": report["text"], "max_legal": MAX_LEGAL}


__all__ = ["PolicyEval", "PolicyRows", "PolicyRowsStream", "SCHEMA", "open_policy_rows", "policy_log_odds", "policy_losses"]
