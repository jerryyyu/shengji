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

Units (schema v3, 2026-09-28).  The pv-search producer (#592) writes
``action_values.units = "expected-signed-level-half-integer"``: its mean is
the acting team's EXPECTED SIGNED LEVEL, a bootstrap of the served value head
over the sampled worlds, already on the outcome head's support -- not points,
and not something the ramp applies to.  A v3 sidecar records the units of
every row it keeps (``units_code`` 0 = points, 1 = signed level) and
attachment fills TWO columns: ``search_mean_played`` (points rows) and
``search_level_played`` (signed-level rows), NaN elsewhere.  Only ``play``
decisions are kept, matching the value cache's row filter, so a pv-search
store's bury records (mcbot points scores under no units tag) never enter.
A v2 sidecar (points only) still attaches; the level column is all NaN.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable, Mapping

import numpy as np

SIDECAR_SCHEMA = "cwv-search-mean-sidecar-v3"
#: v2 sidecars (points only, no units column) still attach
LEGACY_SCHEMAS = ("cwv-search-mean-sidecar-v2",)
#: the producer objective whose search mean is an expected-points mean
ELIGIBLE_LEVEL_OBJECTIVE = False
#: ``units_code`` values: the row's mean is expected attacker points (ramp target) or the
#: acting team's expected signed level on the half-integer support (direct target)
UNITS_POINTS = 0
UNITS_SIGNED_LEVEL = 1
UNITS_CODE = {"expected-attacker-points": UNITS_POINTS,
              "expected-signed-level-half-integer": UNITS_SIGNED_LEVEL}


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
    flag = producer_flags(shard_path).get("level_objective")
    if not isinstance(flag, bool):
        raise SidecarError(f"{shard_path}: no policy_flags.level_objective; the sidecar "
                           "mean's units are unknown")
    return bool(flag)


def producer_flags(shard_path: str | os.PathLike) -> dict:
    """``policy_flags`` of the run that wrote ``shard_path``; refuses without a run.json."""
    here = Path(shard_path).resolve().parent
    for directory in (here, *here.parents):
        run = directory / "run.json"
        if run.is_file():
            flags = _policy_flags(json.loads(run.read_text()))
            if flags is None:
                raise SidecarError(f"{run}: no policy_flags; the producer is unknown")
            return dict(flags)
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


def record_units_code(record: Mapping[str, Any], producer_units: str | None = None) -> int:
    """The units of ``record["action_values"].means`` as a ``units_code``: the record's
    tag when it has one (refusing a tag it cannot place); without a tag, POINTS -- but
    ONLY when the producer does not declare otherwise.  ``producer_units`` is the run's
    ``policy_flags.value_units``: a producer that declares signed-level units and writes
    an untagged row is refused, because "no tag means points" is exactly how the level
    means of #649 would be bracketed as points on the value side (#667 finding 5)."""
    values = record.get("action_values")
    units = values.get("units") if isinstance(values, dict) else None
    if units is None:
        if producer_units is not None:
            if producer_units not in UNITS_CODE:
                raise SidecarError(f"unknown producer value units {producer_units!r}")
            if UNITS_CODE[producer_units] != UNITS_POINTS:
                raise SidecarError(f"untagged action_values under a producer that declares "
                                   f"value_units={producer_units!r}; refusing to read it as points")
        return UNITS_POINTS
    if units not in UNITS_CODE:
        raise SidecarError(f"unknown value units {units!r}")
    return UNITS_CODE[units]


def build_sidecar(shard_path: str | os.PathLike, out_dir: str | os.PathLike,
                  level_objective: bool | None = None,
                  units_override: int | None = None) -> dict:
    """Write the sidecar for one shard; idempotent.  Returns counts.

    ``level_objective`` defaults to the producer's flag from ``run.json``, which
    may be absent (null) for a producer whose rows are all units-tagged; a
    POINTS row under a producer whose flag is not ``False`` is refused, because
    its mean's meaning is then unknown.  ``units_override`` (tests) stamps every
    kept row with that code instead of reading the record's tag."""
    producer_units: str | None = None
    try:
        flags = producer_flags(shard_path)
    except SidecarError:
        if level_objective is None:
            raise
        flags = {}                       # an explicit flag and no run.json: tests only
    if level_objective is None:
        flag = flags.get("level_objective")
        level_objective = bool(flag) if isinstance(flag, bool) else None
    if flags.get("value_units") is not None:
        producer_units = str(flags["value_units"])
    sha = shard_sha256(shard_path)
    out = sidecar_path(out_dir, sha)
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    keys, means, codes, n = [], [], [], 0
    with open(shard_path) as fh:
        for line in fh:
            try:
                record = json.loads(line)
            except Exception:
                continue
            if "action" not in record:
                continue
            n += 1
            if record.get("decision_kind", "play") != "play":
                continue                    # the value cache keeps play decisions only
            rs = record.get("record_sha256")
            pref = record.get("preference") or {}
            values, played = pref.get("means"), pref.get("played_index")
            if not rs or not isinstance(values, list) or played is None \
                    or not 0 <= played < len(values):
                continue
            value = values[played]
            if value is None or not np.isfinite(value):
                continue
            code = (record_units_code(record, producer_units) if units_override is None
                    else int(units_override))
            if code == UNITS_POINTS and level_objective is not ELIGIBLE_LEVEL_OBJECTIVE:
                raise SidecarError(
                    f"{shard_path}: a points-units row under producer LEVEL_OBJECTIVE="
                    f"{level_objective}; its search mean is not an expected-points mean"
                    if level_objective is not None else
                    f"{shard_path}: a points-units row under a producer with no "
                    "level_objective flag; the mean's units are unknown")
            keys.append(rs)
            means.append(float(value))
            codes.append(code)
    tmp = out.with_suffix(".tmp.npz")
    np.savez(tmp, schema=np.asarray(SIDECAR_SCHEMA),
             level_objective=np.asarray(level_objective if level_objective is not None else -1,
                                        dtype=np.int8),
             record_sha256=np.asarray(keys, dtype="S64"),
             search_mean_played=np.asarray(means, dtype=np.float32),
             units_code=np.asarray(codes, dtype=np.int8))
    os.replace(tmp, out)
    return {"shard_sha256": sha, "records": n, "with_mean": len(keys),
            "level_objective": level_objective,
            "points_rows": int(sum(1 for c in codes if c == UNITS_POINTS)),
            "level_rows": int(sum(1 for c in codes if c == UNITS_SIGNED_LEVEL))}


def attach_search_means(arrays: dict, shard_sha: str, out_dir: str | os.PathLike) -> bool:
    """Add ``search_mean_played`` (points rows) and ``search_level_played``
    (signed-level rows) -- float32, NaN where absent -- to a block's arrays.
    Returns whether the shard's sidecar file existed: a missing file attaches
    all-NaN columns (the block still trains its other heads), so the CALLER
    must decide whether a missing sidecar is acceptable; ``check_sidecar_coverage``
    refuses a training set with any missing file before the first epoch (#667).

    Refuses a v2 sidecar from a producer whose score is not an expected-points
    mean, or one written before the producer flag existed.  A v3 sidecar
    carries its units per row and has already refused what it could not place."""
    path = sidecar_path(out_dir, shard_sha)
    rows = np.asarray(arrays["record_sha256"])
    means = np.full(rows.shape[0], np.nan, dtype=np.float32)
    levels = np.full(rows.shape[0], np.nan, dtype=np.float32)
    if path.exists():
        with np.load(path, allow_pickle=False) as npz:
            schema = str(npz["schema"]) if "schema" in npz.files else None
            if "level_objective" not in npz.files or schema not in (SIDECAR_SCHEMA, *LEGACY_SCHEMAS):
                raise SidecarError(f"{path}: sidecar predates the producer flag; rebuild it")
            if schema in LEGACY_SCHEMAS:
                if bool(npz["level_objective"]) is not ELIGIBLE_LEVEL_OBJECTIVE:
                    raise SidecarError(f"{path}: producer ran LEVEL_OBJECTIVE="
                                       f"{bool(npz['level_objective'])}; its search mean is a "
                                       "clipped bracket score with no exact inverse, refused")
                codes = np.zeros(npz["record_sha256"].shape[0], dtype=np.int8)
            else:
                codes = np.asarray(npz["units_code"], dtype=np.int8)
                if codes.size and (codes < 0).any() or (codes > UNITS_SIGNED_LEVEL).any():
                    raise SidecarError(f"{path}: unknown units_code in the sidecar")
            lookup = dict(zip(npz["record_sha256"].tolist(),
                              zip(npz["search_mean_played"].tolist(), codes.tolist())))
        for i, key in enumerate(rows.tolist()):
            hit = lookup.get(key)
            if hit is None:
                continue
            value, code = hit
            if code == UNITS_SIGNED_LEVEL:
                levels[i] = value
            else:
                means[i] = value
    arrays["search_mean_played"] = means
    arrays["search_level_played"] = levels
    return path.exists()


def check_sidecar_coverage(out_dir: str | os.PathLike,
                           shards: "Iterable[tuple[str, str]]") -> dict:
    """Refuse a training set whose sidecar directory lacks a file for ANY shard.

    ``shards`` are ``(store identity, shard sha256)`` -- the STORE ROOT (``ShardRef.store``),
    never the shard's own label, so the counts are per store and cannot fragment or
    cross-combine (Codex HOLD on #669).  Returns per-store counts
    ``{label: {"shards": n, "missing": m}}`` for the receipt.  #658 found the
    search-mean head silently training on 24.2M of 55.1M rows because 16 stores
    had no sidecar files and ``attach_search_means`` returned NaN for them; a
    missing file is now a refusal with the store named, never a quiet mask."""
    per: dict[str, dict] = {}
    first_missing: dict[str, str] = {}
    for label, sha in shards:
        entry = per.setdefault(str(label), {"shards": 0, "missing": 0})
        entry["shards"] += 1
        if not sidecar_path(out_dir, sha).exists():
            entry["missing"] += 1
            first_missing.setdefault(str(label), sha)
    bad = {k: v for k, v in per.items() if v["missing"]}
    if bad:
        detail = "; ".join(f"{k}: {v['missing']}/{v['shards']} missing (first {first_missing[k][:12]})"
                           for k, v in sorted(bad.items()))
        raise SidecarError(f"{out_dir}: sidecar coverage incomplete -- {detail}; build the "
                           f"sidecars for these stores or drop them from --data")
    return per


def manifest_sha256(out_dir: str | os.PathLike) -> str:
    """Identity of a sidecar directory: the schema and the sha256 of every
    sidecar file's bytes, so a same-sized label change is a different manifest."""
    digest = hashlib.sha256(SIDECAR_SCHEMA.encode("ascii"))
    for p in sorted(Path(out_dir).glob("*.npz")):
        digest.update(f"{p.name}:{shard_sha256(p)}\n".encode("ascii"))
    return digest.hexdigest()
