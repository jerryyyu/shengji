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


class PolicyRows:
    """The training root rows: ``X`` kept as float16, ballots padded once."""

    def __init__(self, prefix: str | Path, *, limit: int | None = None):
        prefix = str(prefix)
        d = np.load(prefix + ".npz")
        X, Y = d["X"], d["Y"]
        if X.ndim != 2 or X.shape[1] != INPUT_DIM or Y.shape != (len(X), 54):
            raise ValueError("policy rows: unexpected X/Y layout")
        n = len(X) if not limit else min(int(limit), len(X))
        if n < 1:
            raise ValueError("policy rows: no rows")
        self.X = np.ascontiguousarray(X[:n]).astype(np.float16)
        self.Y = np.ascontiguousarray(Y[:n]).astype(np.uint8)
        meta = _read_meta(prefix + ".meta.jsonl", n, ("ballot", "taken", "deal"))
        if len(meta) != n:
            raise ValueError("policy rows: metadata shorter than the rows")
        ball, mask, tgt = ballot_tensors(meta)
        self.ball, self.mask, self.tgt = ball, mask, tgt
        self.n = n
        self.deals = len({m["deal"] for m in meta if m.get("deal")})
        self.in_ballot = int((tgt >= 0).sum())
        self.identity = {"schema": SCHEMA, "prefix": str(Path(prefix).resolve()),
                         "npz_sha256": _file_sha256(prefix + ".npz"), "rows_available": int(len(X)),
                         "rows_used": n, "deals": self.deals, "rows_with_ballot_target": self.in_ballot}

    def batches(self, batch_size: int, rng: np.random.Generator):
        """One pass in a fresh permutation; the caller cycles passes."""
        perm = rng.permutation(self.n)
        for start in range(0, self.n, batch_size):
            yield perm[start:start + batch_size]

    def tensors(self, idx: np.ndarray, device) -> dict[str, torch.Tensor]:
        idx = np.asarray(idx)
        return {"x": torch.from_numpy(self.X[idx].astype(np.float32)).to(device),
                "y": torch.from_numpy(self.Y[idx].astype(np.float32)).to(device),
                "ball": self.ball[idx].to(device), "mask": self.mask[idx].to(device),
                "tgt": self.tgt[idx].to(device)}


def policy_losses(model, t: Mapping[str, torch.Tensor], *, listwise_weight: float):
    """``(bce, listwise, logits)`` of the policy head on one root batch."""
    logits = model.policy_logits(model.features_flat(t["x"]))
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
    """Held-out root rows (the #419 probe set, with deal ids) read once."""

    def __init__(self, prefix: str | Path):
        prefix = str(prefix)
        d = np.load(prefix + ".npz")
        self.X = d["X"]
        self.meta = [json.loads(l) for l in open(prefix + ".meta.jsonl")]
        if len(self.meta) != len(self.X):
            raise ValueError("policy eval: metadata/rows mismatch")
        self.identity = {"prefix": str(Path(prefix).resolve()), "npz_sha256": _file_sha256(prefix + ".npz"),
                         "rows": int(len(self.X)), "deals": len({m.get("deal") for m in self.meta if m.get("deal")})}

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


__all__ = ["PolicyEval", "PolicyRows", "SCHEMA", "policy_log_odds", "policy_losses"]
