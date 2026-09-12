"""Per-shard sidecar: the search's own value for the PLAYED action (issue #340).

The cwv cache stores only whether a row has search means, not the means, and
rebuilding 96k-corpus caches for one extra column costs hours.  This sidecar is
records-only: one ``<shard_sha256>.npz`` per shard with ``record_sha256`` (S64)
and ``search_mean_played`` (float32, acting-team perspective, the refined mean
``preference.means[played_index]`` which includes the report fold when it ran),
plus the PRODUCER'S objective (``level_objective`` from the run's
``run.json`` ``policy_flags``), because the mean's units are the producer's
``mcbot._score``: expected attacker points under ``LEVEL_OBJECTIVE = False``,
a clipped bracket score with no exact inverse under ``True``.  Attachment
refuses a sidecar whose producer is not the one the target is defined for.
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

SIDECAR_SCHEMA = "cwv-search-mean-sidecar-v2"
#: the producer objective whose search mean is an expected-points mean
ELIGIBLE_LEVEL_OBJECTIVE = False


class SidecarError(RuntimeError):
    """A sidecar cannot be built or attached honestly."""


def shard_sha256(path: str | os.PathLike) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sidecar_path(out_dir: str | os.PathLike, sha: str) -> Path:
    return Path(out_dir) / f"{sha}.npz"


def producer_level_objective(shard_path: str | os.PathLike) -> bool:
    """The ``policy_flags.level_objective`` of the run that wrote ``shard_path``
    (``run.json`` in the shard's directory or a parent); refuses if unknown."""
    here = Path(shard_path).resolve().parent
    for directory in (here, *here.parents):
        run = directory / "run.json"
        if run.is_file():
            flags = _policy_flags(json.loads(run.read_text()))
            if flags is None or not isinstance(flags.get("level_objective"), bool):
                raise SidecarError(f"{run}: no policy_flags.level_objective; the sidecar "
                                   "mean's units are unknown")
            return bool(flags["level_objective"])
    raise SidecarError(f"{shard_path}: no run.json above the shard; the producer's "
                       "objective is unknown")


def _policy_flags(payload) -> dict | None:
    """``policy_flags`` wherever the run manifest nests it."""
    if isinstance(payload, dict):
        if isinstance(payload.get("policy_flags"), dict):
            return payload["policy_flags"]
        for value in payload.values():
            found = _policy_flags(value)
            if found is not None:
                return found
    elif isinstance(payload, list):
        for value in payload:
            found = _policy_flags(value)
            if found is not None:
                return found
    return None


def build_sidecar(shard_path: str | os.PathLike, out_dir: str | os.PathLike,
                  level_objective: bool | None = None) -> dict:
    """Write the sidecar for one shard; idempotent.  Returns counts.

    ``level_objective`` defaults to the producer's flag from ``run.json``."""
    if level_objective is None:
        level_objective = producer_level_objective(shard_path)
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
    np.savez(tmp, schema=np.asarray(SIDECAR_SCHEMA),
             level_objective=np.asarray(bool(level_objective)),
             record_sha256=np.asarray(keys, dtype="S64"),
             search_mean_played=np.asarray(means, dtype=np.float32))
    os.replace(tmp, out)
    return {"shard_sha256": sha, "records": n, "with_mean": len(keys),
            "level_objective": bool(level_objective)}


def attach_search_means(arrays: dict, shard_sha: str, out_dir: str | os.PathLike) -> None:
    """Add ``search_mean_played`` (float32, NaN where absent) to a block's arrays.

    Refuses a sidecar from a producer whose score is not an expected-points
    mean, or one written before the producer flag existed."""
    path = sidecar_path(out_dir, shard_sha)
    rows = np.asarray(arrays["record_sha256"])
    values = np.full(rows.shape[0], np.nan, dtype=np.float32)
    if path.exists():
        with np.load(path, allow_pickle=False) as npz:
            if "level_objective" not in npz.files or str(npz["schema"]) != SIDECAR_SCHEMA:
                raise SidecarError(f"{path}: sidecar predates the producer flag; rebuild it")
            if bool(npz["level_objective"]) is not ELIGIBLE_LEVEL_OBJECTIVE:
                raise SidecarError(f"{path}: producer ran LEVEL_OBJECTIVE="
                                   f"{bool(npz['level_objective'])}; its search mean is a "
                                   "clipped bracket score with no exact inverse, refused")
            lookup = dict(zip(npz["record_sha256"].tolist(), npz["search_mean_played"].tolist()))
        for i, key in enumerate(rows.tolist()):
            hit = lookup.get(key)
            if hit is not None:
                values[i] = hit
    arrays["search_mean_played"] = values


def manifest_sha256(out_dir: str | os.PathLike) -> str:
    """Identity of a sidecar directory: the schema and the sha256 of every
    sidecar file's bytes, so a same-sized label change is a different manifest."""
    digest = hashlib.sha256(SIDECAR_SCHEMA.encode("ascii"))
    for p in sorted(Path(out_dir).glob("*.npz")):
        digest.update(f"{p.name}:{shard_sha256(p)}\n".encode("ascii"))
    return digest.hexdigest()
