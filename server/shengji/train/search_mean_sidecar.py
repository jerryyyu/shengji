"""Per-shard sidecar: the search's own value for the PLAYED action (issue #340).

The cwv cache stores only whether a row has search means, not the means, and
rebuilding 96k-corpus caches for one extra column costs hours.  This sidecar is
records-only: one ``<shard_sha256>.npz`` per shard with ``record_sha256`` (S64)
and ``search_mean_played`` (float32, acting-team perspective, the refined mean
``preference.means[played_index]`` which includes the report fold when it ran).
Rows without a usable mean are absent; the trainer falls back to the realised
outcome for them.  Attachment aligns by ``record_sha256`` within the shard, so
row order and skip rules of the cache never matter.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import numpy as np

SIDECAR_SCHEMA = "cwv-search-mean-sidecar-v1"


def shard_sha256(path: str | os.PathLike) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sidecar_path(out_dir: str | os.PathLike, sha: str) -> Path:
    return Path(out_dir) / f"{sha}.npz"


def build_sidecar(shard_path: str | os.PathLike, out_dir: str | os.PathLike) -> dict:
    """Write the sidecar for one shard; idempotent.  Returns counts."""
    sha = shard_sha256(shard_path)
    out = sidecar_path(out_dir, sha)
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    keys, means, n = [], [], 0
    with open(shard_path) as fh:
        for line in fh:
            try:
                record = json.loads(line)
            except Exception:
                continue
            if "action" not in record:
                continue
            n += 1
            rs = record.get("record_sha256")
            pref = record.get("preference") or {}
            values, played = pref.get("means"), pref.get("played_index")
            if not rs or not isinstance(values, list) or played is None \
                    or not 0 <= played < len(values):
                continue
            value = values[played]
            if value is None or not np.isfinite(value):
                continue
            keys.append(rs)
            means.append(float(value))
    tmp = out.with_suffix(".tmp.npz")
    np.savez(tmp, record_sha256=np.asarray(keys, dtype="S64"),
             search_mean_played=np.asarray(means, dtype=np.float32))
    os.replace(tmp, out)
    return {"shard_sha256": sha, "records": n, "with_mean": len(keys)}


def attach_search_means(arrays: dict, shard_sha: str, out_dir: str | os.PathLike) -> None:
    """Add ``search_mean_played`` (float32, NaN where absent) to a block's arrays."""
    path = sidecar_path(out_dir, shard_sha)
    rows = np.asarray(arrays["record_sha256"])
    values = np.full(rows.shape[0], np.nan, dtype=np.float32)
    if path.exists():
        with np.load(path, allow_pickle=False) as npz:
            lookup = dict(zip(npz["record_sha256"].tolist(), npz["search_mean_played"].tolist()))
        for i, key in enumerate(rows.tolist()):
            hit = lookup.get(key)
            if hit is not None:
                values[i] = hit
    arrays["search_mean_played"] = values


def manifest_sha256(out_dir: str | os.PathLike) -> str:
    """Identity of a sidecar directory: the sorted list of (file, size)."""
    digest = hashlib.sha256(SIDECAR_SCHEMA.encode("ascii"))
    for p in sorted(Path(out_dir).glob("*.npz")):
        digest.update(f"{p.name}:{p.stat().st_size}\n".encode("ascii"))
    return digest.hexdigest()
