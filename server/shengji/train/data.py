"""Decision-record stores -> encoded, cached training blocks.

Inputs (all ``shengji-decision-record-v1``)
-------------------------------------------
* a **shard store** written by ``harvest.trajectory`` (``<dir>/shards/
  cluster-*.jsonl`` + ``.json`` sidecars + ``manifest.json``); without a
  manifest (a run still in progress) the shards whose sidecar verifies are
  used and the rest are counted as skipped;
* a **merged** store (``<dir>/trajectory.jsonl`` + ``manifest.json`` /
  ``trajectory.manifest.json``, the pre-repair Mini layout);
* a plain **jsonl** file (the Luna private split).

Every shard is hashed; a manifest that states a different hash refuses.

State and encoding (reused, never reinvented)
---------------------------------------------
``harvest.rebuild.state_for_record`` rebuilds the acting state; the
production ``rl.encode.encode_obs`` / ``encode_action`` encode it.  The
PRIVACY witness (``privacy_witness``) permutes the hidden cards among the
NON-acting seats (hand sizes kept; the kitty joins the pool when the actor
is not the banker) and demands a byte-identical encoding; an encoder that
reads another hand refuses loudly (``PrivacyError``) before anything is
cached or trained on.

Targets
-------
VALUE: ``outcome.signed_level_utility`` (signed for the acting seat's
partnership, as stored); ``outcome.attacker_points`` is carried for the
optional auxiliary head.  PRIOR: ``preference.softmax`` and
``preference.final`` (one-hot on the played action) over the record's
``ballot``.  A row without ``preference`` gets it DERIVED from
``allocation`` + ``action_values`` through the generator's own
``preference_from_record`` when those fields exist; a single-candidate
ballot is a point mass; otherwise the softmax target is counted as missing
and the row trains the value head only (``final`` still follows from
``action`` when it is on the ballot).  Nothing is trained on a guessed
distribution.

AUXILIARY SEARCH MEAN (``search_mean`` / ``has_search_mean``): the search's
own estimate for the played action, exactly
``record["action_values"]["means"][played_index(record)]`` -- the index the
``final`` target uses (``preference.played_index``, else
``allocation.played_index``, else the ballot entry matching ``action``).
The generator stamps ``action_values.perspective == "acting-team"``: the
mean over the selection worlds of the rollout score (attacker points from
the attackers' view, negated on banker-team rows), so the sign convention
matches the value target (positive is good for the acting seat's
partnership) while the SCALE is points (about +-[0, 200]).  A row whose
``action_values`` is null (single-candidate ballots, tractor locks, Luna),
whose stated perspective is not ``acting-team``, whose played index is
unknown or whose mean is null/non-finite carries no aux target
(``has_search_mean`` false; counted under ``counts.search_mean`` as
``absent`` / ``unusable``) and trains the aux head on nothing.

Cache
-----
``<out>/cache/<shard sha256>.<encoder sha256[:12]>.npz`` per shard: obs,
ragged per-candidate action features (offsets), targets and ids, plus a
``meta`` JSON (schema, encoder identity, shard hash, counts).  Rebuilt when
missing or when either key changes; never a source of truth.  The file is a
pure function of (shard bytes, encoder, witness seed): no timing or host
detail is stamped inside, so ``ensure_caches`` may build the missing shards
in a pool of spawned worker processes (``workers`` at a time, one shard per
task) and produce byte-identical files to the in-process build.
"""

from __future__ import annotations

import hashlib
import json
import math
import multiprocessing
import os
import random
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Sequence

import numpy as np

from ..harvest.common import action_key, sha256_file
from ..harvest.rebuild import RebuildError, state_for_record
from ..harvest.schema import SCHEMA, SchemaError, record_sha256, validate_record
from ..harvest.trajectory import (MANIFEST_SCHEMA as TRAJECTORY_MANIFEST_SCHEMA,
                                  SHARD_SCHEMA, TrajectoryError,
                                  preference_from_record)
from ..rl.encode import (ACT_DIM, ENC_VERSION, ENCODER_IMPLEMENTATION_SHA256,
                         ENCODER_SOURCE_SHA256S, OBS_DIM, OBS_SCHEMA,
                         encode_action, encode_obs)
from ..rl.encoder_identity import encoder_contract

CACHE_SCHEMA = "shengji-train-cache-v2"      # v2: + search_mean / has_search_mean
HARVEST_MANIFEST_SCHEMA = "shengji-harvest-manifest-v1"
LAYOUTS = ("shard-store", "merged", "jsonl")
#: 25 tricks x 4 seats: a round has 100 plays; ply thirds are the phases
PLAYS_PER_ROUND = 100
PRIVACY_TRIALS = 2
SKIP_REASONS = ("no_outcome", "wrong_schema", "rebuild_failed", "turn_mismatch",
                "schema_invalid")
PREFERENCE_KEYS = ("stored", "derived", "point_mass", "missing", "invalid",
                   "final_from_action", "final_missing")
SEARCH_MEAN_KEYS = ("present", "absent", "unusable")
SEARCH_MEAN_PERSPECTIVE = "acting-team"
#: cache builds run at most this many shards at a time by default
CACHE_WORKERS_CAP = 8


class TrainDataError(RuntimeError):
    """The data cannot be loaded as specified (fail closed)."""


class PrivacyError(TrainDataError):
    """The state encoding depends on a hand the acting seat cannot see."""


# --------------------------------------------------------------- identity

def encoder_identity() -> dict:
    """Stamped in every cache ``meta`` and every receipt."""
    return {
        "enc_version": ENC_VERSION,
        "obs_schema": OBS_SCHEMA,
        "obs_dim": OBS_DIM,
        "act_dim": ACT_DIM,
        "implementation_sha256": ENCODER_IMPLEMENTATION_SHA256,
        "source_sha256s": dict(ENCODER_SOURCE_SHA256S),
        "transitive": encoder_contract(),
    }


def encoder_cache_key() -> str:
    return ENCODER_IMPLEMENTATION_SHA256[:12]


# ------------------------------------------------------------------ stores

@dataclass(frozen=True)
class ShardRef:
    path: str            # absolute file path
    label: str           # path relative to the store root
    sha256: str
    records: int | None  # as stated by the manifest/sidecar (None: unknown)
    cluster: int | None  # trajectory shard-store cluster index
    store: str           # store root


@dataclass
class Store:
    root: str
    layout: str
    manifests: list[dict] = field(default_factory=list)
    shards: list[ShardRef] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)
    private: bool = False

    def describe(self) -> dict:
        return {
            "root": self.root, "layout": self.layout, "private": self.private,
            "manifests": list(self.manifests),
            "shards": [{"label": s.label, "sha256": s.sha256, "records": s.records,
                        "cluster": s.cluster} for s in self.shards],
            "skipped": list(self.skipped),
        }


def _is_private(path: Path) -> bool:
    return not (path.stat().st_mode & 0o044)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _manifest_entry(path: Path, schema: str | None) -> dict:
    return {"path": str(path), "sha256": sha256_file(path), "schema": schema}


def _stated_sha(manifest: Mapping[str, Any], name: str) -> str | None:
    """The sha256 a harvest manifest states for output ``name`` (top level
    or under one of its sources), else None."""
    outputs = manifest.get("outputs")
    if isinstance(outputs, dict) and isinstance(outputs.get(name), dict):
        return outputs[name].get("sha256")
    for source in (manifest.get("sources") or {}).values():
        outs = source.get("outputs") if isinstance(source, dict) else None
        if isinstance(outs, dict) and isinstance(outs.get(name), dict):
            return outs[name].get("sha256")
    return None


def _stated_records(manifest: Mapping[str, Any], name: str) -> int | None:
    outputs = manifest.get("outputs")
    if isinstance(outputs, dict) and isinstance(outputs.get(name), dict):
        return outputs[name].get("records")
    return None


def discover_store(path: str | os.PathLike, *, limit_clusters: int | None = None
                   ) -> Store:
    """Find the shards of ``path`` and verify their hashes (fail closed)."""
    root = Path(path).resolve()
    if root.is_file():
        return _jsonl_store(root)
    if (root / "shards").is_dir():
        return _shard_store(root, limit_clusters)
    if (root / "trajectory.jsonl").is_file():
        return _merged_store(root)
    raise TrainDataError(f"{root}: no shards/, trajectory.jsonl or .jsonl file")


def _shard_store(root: Path, limit_clusters: int | None) -> Store:
    store = Store(root=str(root), layout="shard-store")
    manifest_path = root / "manifest.json"
    manifest = _read_json(manifest_path) if manifest_path.is_file() else None
    if manifest is not None and manifest.get("schema") == TRAJECTORY_MANIFEST_SCHEMA:
        store.manifests.append(_manifest_entry(manifest_path, manifest["schema"]))
        listed = sorted(manifest["shards"], key=lambda s: int(s["cluster"]))
        if limit_clusters is not None:
            listed = listed[:int(limit_clusters)]
        for shard in listed:
            path = root / shard["path"]
            if not path.is_file():
                raise TrainDataError(f"{path}: listed by the manifest but missing")
            digest = sha256_file(path)
            if digest != shard["sha256"]:
                raise TrainDataError(f"{path}: sha256 drift against the manifest "
                                     f"({digest[:12]} != {shard['sha256'][:12]})")
            store.shards.append(ShardRef(
                path=str(path), label=shard["path"], sha256=digest,
                records=int(shard["records"]), cluster=int(shard["cluster"]),
                store=str(root)))
        return store
    # no manifest yet: a run in progress; keep the shards whose sidecar verifies
    if manifest is not None:
        store.manifests.append(_manifest_entry(manifest_path, manifest.get("schema")))
    paths = sorted((root / "shards").glob("cluster-*.jsonl"))
    for path in paths:
        side = path.with_suffix(".json")
        label = f"shards/{path.name}"
        if not side.is_file():
            store.skipped.append({"label": label, "reason": "no sidecar"})
            continue
        try:
            sidecar = _read_json(side)
        except ValueError:
            store.skipped.append({"label": label, "reason": "sidecar unreadable"})
            continue
        digest = sha256_file(path)
        if sidecar.get("schema") != SHARD_SCHEMA or sidecar.get("sha256") != digest:
            store.skipped.append({"label": label, "reason": "sha256 mismatch"})
            continue
        store.shards.append(ShardRef(
            path=str(path), label=label, sha256=digest,
            records=int(sidecar["records"]), cluster=int(sidecar["cluster"]),
            store=str(root)))
        if limit_clusters is not None and len(store.shards) >= int(limit_clusters):
            break
    if not store.shards:
        raise TrainDataError(f"{root}: no verifiable shard")
    return store


def _merged_store(root: Path) -> Store:
    store = Store(root=str(root), layout="merged")
    path = root / "trajectory.jsonl"
    digest = sha256_file(path)
    records = None
    for name in ("manifest.json", "trajectory.manifest.json"):
        mpath = root / name
        if not mpath.is_file():
            continue
        manifest = _read_json(mpath)
        store.manifests.append(_manifest_entry(mpath, manifest.get("schema")))
        stated = _stated_sha(manifest, "trajectory.jsonl")
        if stated is not None and stated != digest:
            raise TrainDataError(f"{path}: sha256 drift against {name} "
                                 f"({digest[:12]} != {stated[:12]})")
        records = records or _stated_records(manifest, "trajectory.jsonl")
    store.private = _is_private(path)
    store.shards.append(ShardRef(path=str(path), label="trajectory.jsonl",
                                 sha256=digest, records=records, cluster=None,
                                 store=str(root)))
    return store


def _jsonl_store(path: Path) -> Store:
    store = Store(root=str(path.parent), layout="jsonl", private=_is_private(path))
    digest = sha256_file(path)
    records = None
    stem = path.name.split(".")[0]
    for candidate in (path.parent / f"{stem}.manifest.json", path.parent / "manifest.json"):
        if not candidate.is_file():
            continue
        manifest = _read_json(candidate)
        store.manifests.append(_manifest_entry(candidate, manifest.get("schema")))
        stated = _stated_sha(manifest, path.name)
        if stated is not None and stated != digest:
            raise TrainDataError(f"{path}: sha256 drift against {candidate.name} "
                                 f"({digest[:12]} != {stated[:12]})")
        records = records or _stated_records(manifest, path.name)
    store.shards.append(ShardRef(path=str(path), label=path.name, sha256=digest,
                                 records=records, cluster=None,
                                 store=str(path.parent)))
    return store


def iter_records(shard: ShardRef) -> Iterator[dict]:
    with open(shard.path, "rb") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)


# ----------------------------------------------------------------- records

def cluster_key(record: Mapping[str, Any]) -> str:
    """The deal cluster a record belongs to: ``<run_id>:<cluster>`` for the
    self-play generator (both mirrors of a deal), else the source_ref with
    its mirror and event fragments removed (Luna: one key per deal)."""
    ref = str(record["source_ref"])
    if record.get("source") == "trajectory":
        parts = ref.split(":")
        if len(parts) >= 2:
            return f"{parts[0]}:{parts[1]}"
    base = ref.split("#", 1)[0]
    return re.sub(r"-mirror-\d+", "", base)


def played_index(record: Mapping[str, Any]) -> int:
    """Index of the played action on the ballot, -1 when unknown."""
    ballot = record.get("ballot")
    if not ballot:
        return -1
    pref = record.get("preference")
    if isinstance(pref, dict) and isinstance(pref.get("played_index"), int):
        i = pref["played_index"]
        if 0 <= i < len(ballot):
            return i
    alloc = record.get("allocation")
    if isinstance(alloc, dict) and isinstance(alloc.get("played_index"), int):
        i = alloc["played_index"]
        if 0 <= i < len(ballot):
            return i
    key = action_key(record["action"])
    for i, cand in enumerate(ballot):
        if action_key(cand) == key:
            return i
    return -1


def _valid_distribution(values: Any, k: int) -> list[float] | None:
    if not isinstance(values, list) or len(values) != k:
        return None
    out = []
    for v in values:
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            return None
        if v < -1e-9 or v > 1 + 1e-9:
            return None
        out.append(min(1.0, max(0.0, float(v))))
    if abs(sum(out) - 1.0) > 1e-6:
        return None
    return out


def derive_preference(record: Mapping[str, Any]) -> dict | None:
    """``preference`` recomputed from ``allocation`` + ``action_values`` with
    the generator's own transform (pre-repair rows), or None when the
    inputs are not all present."""
    ballot = record.get("ballot")
    alloc = record.get("allocation")
    values = record.get("action_values")
    if not ballot or not isinstance(alloc, dict) or not isinstance(values, dict):
        return None
    k = len(ballot)
    means = values.get("means")
    ses = values.get("paired_se")
    n_by = alloc.get("selection_worlds")
    played = alloc.get("played_index")
    if (not isinstance(means, list) or not isinstance(ses, list)
            or not isinstance(n_by, list) or len(means) != k or len(ses) != k
            or len(n_by) != k or not isinstance(played, int)
            or not 0 <= played < k):
        return None
    report = values.get("report")
    fold = None
    if isinstance(report, dict):
        fold = {"worlds": report.get("worlds") or 0,
                "gap": math.nan if report.get("gap") is None else float(report["gap"]),
                "se": report.get("se")}
    rec = {
        "candidates": [list(c) for c in ballot],
        "means": [-math.inf if m is None else float(m) for m in means],
        "paired_se": [math.inf if s is None else float(s) for s in ses],
        "n_by_candidate": [int(n) for n in n_by],
        "played_index": played,
        "report_candidate_index": alloc.get("report_candidate_index"),
        "report_fold": fold,
    }
    try:
        return preference_from_record(rec)
    except (TrajectoryError, ValueError, TypeError, KeyError):
        return None


def prior_targets(record: Mapping[str, Any], counts: dict[str, int]
                  ) -> tuple[list[float] | None, int]:
    """``(softmax over the ballot or None, played index or -1)``; every
    outcome is counted in ``counts`` (``PREFERENCE_KEYS``)."""
    ballot = record.get("ballot")
    if not ballot:
        counts["missing"] += 1
        counts["final_missing"] += 1
        return None, -1
    k = len(ballot)
    played = played_index(record)
    if played < 0:
        counts["final_missing"] += 1
    elif not (isinstance(record.get("preference"), dict)
              or isinstance(record.get("allocation"), dict)):
        counts["final_from_action"] += 1
    pref = record.get("preference")
    softmax = None
    if isinstance(pref, dict):
        softmax = _valid_distribution(pref.get("softmax"), k)
        if softmax is None:
            counts["invalid"] += 1
        else:
            counts["stored"] += 1
    else:
        derived = derive_preference(record)
        if derived is not None:
            softmax = _valid_distribution(derived.get("softmax"), k)
            if softmax is None:
                counts["invalid"] += 1
            else:
                counts["derived"] += 1
        elif k == 1:
            softmax = [1.0]
            counts["point_mass"] += 1
        else:
            counts["missing"] += 1
    return softmax, played


def search_mean_target(record: Mapping[str, Any], played: int, counts: dict[str, int]
                       ) -> float | None:
    """``action_values.means[played]`` in the acting-team perspective (see
    the module docstring), or None; every outcome is counted in ``counts``
    (``SEARCH_MEAN_KEYS``)."""
    values = record.get("action_values")
    means = values.get("means") if isinstance(values, dict) else None
    if not isinstance(means, list):
        counts["absent"] += 1
        return None
    if (values.get("perspective") != SEARCH_MEAN_PERSPECTIVE or played < 0
            or played >= len(means)):
        counts["unusable"] += 1
        return None
    m = means[played]
    if isinstance(m, bool) or not isinstance(m, (int, float)) or not math.isfinite(m):
        counts["unusable"] += 1
        return None
    counts["present"] += 1
    return float(m)


def phase_of(ply: int | None) -> int:
    """0 early / 1 middle / 2 late by ply thirds; a bury decision is early."""
    if ply is None:
        return 0
    return min(2, max(0, int(ply) * 3 // PLAYS_PER_ROUND))


# ----------------------------------------------------------------- privacy

def privacy_witness(rnd, seat: int, ballot: Sequence[Sequence[str]] | None,
                    rng: random.Random, *, trials: int = PRIVACY_TRIALS) -> int:
    """Permute the hidden cards among the NON-acting seats (each hand keeps
    its size; the kitty joins the pool unless the actor is the banker) and
    require byte-identical state and candidate encodings.  Returns the
    number of permutations checked; raises ``PrivacyError``."""
    base_obs = np.asarray(encode_obs(rnd, seat), dtype=np.float32).tobytes()
    base_act = [np.asarray(encode_action(list(c), rnd), dtype=np.float32).tobytes()
                for c in (ballot or [])]
    others = [s for s in range(4) if s != seat]
    sizes = [len(rnd.hands[s]) for s in others]
    pool = [c for s in others for c in rnd.hands[s]]
    kitty = rnd.banker != seat and bool(rnd.buried)
    if kitty:
        pool.extend(rnd.buried)
    saved_hands = [list(h) for h in rnd.hands]
    saved_buried = list(rnd.buried) if rnd.buried else rnd.buried
    checked = 0
    try:
        for _ in range(trials):
            rng.shuffle(pool)
            i = 0
            for s, n in zip(others, sizes):
                rnd.hands[s] = list(pool[i:i + n])
                i += n
            if kitty:
                rnd.buried = list(pool[i:])
            obs = np.asarray(encode_obs(rnd, seat), dtype=np.float32).tobytes()
            act = [np.asarray(encode_action(list(c), rnd), dtype=np.float32).tobytes()
                   for c in (ballot or [])]
            checked += 1
            if obs != base_obs or act != base_act:
                raise PrivacyError(
                    "encode_obs/encode_action changed when hidden cards were "
                    f"permuted among the non-acting seats (seat {seat}): the "
                    "encoder reads a hand the actor cannot see; refusing to train")
    finally:
        rnd.hands = saved_hands
        rnd.buried = saved_buried
    return checked


# ---------------------------------------------------------------- encoding

@dataclass
class Sample:
    obs: np.ndarray
    cand: np.ndarray            # [K, ACT_DIM]
    softmax: np.ndarray | None  # [K] or None
    played: int
    utility: float
    attacker_points: float
    points_so_far: float
    ply: int                    # -1 for a bury decision
    role_attacker: bool
    seat: int
    kind: str
    cluster: str
    sha256: str
    source_ref: str
    search_mean: float | None = None   # aux target, points scale (module docstring)


def encode_record(record: Mapping[str, Any], pref_counts: dict[str, int],
                  *, witness_rng: random.Random | None = None,
                  search_counts: dict[str, int] | None = None) -> Sample:
    """Rebuild, encode and target one record (raises on a bad record)."""
    if record.get("schema") != SCHEMA:
        raise TrainDataError(f"record schema {record.get('schema')!r} != {SCHEMA!r}")
    outcome = record.get("outcome")
    if not isinstance(outcome, dict) or outcome.get("signed_level_utility") is None:
        raise TrainDataError("record has no outcome")
    seat = int(record["seat"])
    try:
        rnd = state_for_record(record)
    except (RebuildError, ValueError, KeyError, AssertionError) as exc:
        raise TrainDataError(f"rebuild failed: {type(exc).__name__}: {exc}") from exc
    kind = record.get("decision_kind", "play")
    if kind == "play" and rnd.turn != seat:
        raise TrainDataError(f"rebuilt state has turn {rnd.turn}, record seat {seat}")
    ballot = record.get("ballot") or []
    if witness_rng is not None:
        privacy_witness(rnd, seat, ballot, witness_rng)
    obs = np.asarray(encode_obs(rnd, seat), dtype=np.float32)
    cand = (np.asarray([encode_action(list(c), rnd) for c in ballot], dtype=np.float32)
            if ballot else np.zeros((0, ACT_DIM), dtype=np.float32))
    softmax, played = prior_targets(record, pref_counts)
    search_mean = search_mean_target(
        record, played, search_counts if search_counts is not None
        else {k: 0 for k in SEARCH_MEAN_KEYS})
    return Sample(
        obs=obs, cand=cand,
        softmax=None if softmax is None else np.asarray(softmax, dtype=np.float32),
        played=played,
        utility=float(outcome["signed_level_utility"]),
        attacker_points=float(outcome.get("attacker_points") or 0),
        points_so_far=float(rnd.attacker_points),
        ply=-1 if record.get("ply") is None else int(record["ply"]),
        role_attacker=(record["role"] == "attacker-team"),
        seat=seat, kind=kind, cluster=cluster_key(record),
        sha256=str(record.get("record_sha256") or ""),
        source_ref=str(record["source_ref"]),
        search_mean=search_mean)


# ------------------------------------------------------------------- blocks

class Block:
    """One cached shard, fully decoded (numpy arrays)."""

    ARRAYS = ("obs", "cand_offsets", "cand_feats", "cand_softmax", "has_softmax",
              "played", "utility", "attacker_points", "points_so_far", "ply",
              "role_attacker", "seat", "cluster", "record_sha256", "source_ref",
              "search_mean", "has_search_mean")

    def __init__(self, arrays: dict[str, np.ndarray], meta: dict, path: str | None = None):
        for name in self.ARRAYS:
            setattr(self, name, arrays[name])
        self.meta = meta
        self.path = path
        self.n = int(self.obs.shape[0])

    @property
    def widths(self) -> np.ndarray:
        return self.cand_offsets[1:] - self.cand_offsets[:-1]

    def subset(self, idx: np.ndarray) -> "Block":
        """Rows ``idx`` (any order) as a new block; candidates re-packed."""
        idx = np.asarray(idx, dtype=np.int64)
        widths = self.widths[idx]
        starts = self.cand_offsets[idx]
        total = int(widths.sum())
        src = (np.repeat(starts, widths)
               + (np.arange(total) - np.repeat(np.cumsum(widths) - widths, widths)))
        offsets = np.zeros(len(idx) + 1, dtype=np.int64)
        offsets[1:] = np.cumsum(widths)
        arrays = {
            "obs": self.obs[idx], "cand_offsets": offsets,
            "cand_feats": self.cand_feats[src], "cand_softmax": self.cand_softmax[src],
        }
        for name in self.ARRAYS[4:]:
            arrays[name] = getattr(self, name)[idx]
        return Block(arrays, self.meta, self.path)

    @staticmethod
    def concat(blocks: Sequence["Block"]) -> "Block":
        if len(blocks) == 1:
            return blocks[0]
        offsets = [np.zeros(1, dtype=np.int64)]
        base = 0
        for b in blocks:
            offsets.append(b.cand_offsets[1:] + base)
            base += int(b.cand_offsets[-1])
        arrays = {"cand_offsets": np.concatenate(offsets)}
        for name in ("obs", "cand_feats", "cand_softmax") + Block.ARRAYS[4:]:
            arrays[name] = np.concatenate([getattr(b, name) for b in blocks])
        return Block(arrays, {"schema": CACHE_SCHEMA, "concat": len(blocks)})


def cache_path(cache_dir: str | os.PathLike, shard_sha256: str) -> Path:
    return Path(cache_dir) / f"{shard_sha256}.{encoder_cache_key()}.npz"


def _fresh_counts() -> dict:
    return {"records": 0, "encoded": 0,
            "skipped": {k: 0 for k in SKIP_REASONS},
            "preference": {k: 0 for k in PREFERENCE_KEYS},
            "search_mean": {k: 0 for k in SEARCH_MEAN_KEYS},
            "privacy_witness": {"records": 0, "permutations": 0},
            "validated": 0, "legacy_schema": 0}


def build_cache(shard: ShardRef, cache_dir: str | os.PathLike, *,
                witness_seed: int = 0, witness_every: int | None = None,
                validate_every: int = 500,
                progress: Callable[[dict], None] | None = None,
                private: bool = False) -> tuple[Path, dict]:
    """Encode every usable record of ``shard`` into its cache file.

    The privacy witness runs on every ``witness_every``-th record (default:
    about 16 per shard, at least every 1000th) and the full schema
    validation on every ``validate_every``-th; both failures refuse the
    whole shard.  The file's bytes depend on nothing but the shard, the
    encoder and ``witness_seed`` (no timing inside: ``ensure_caches`` may
    build it in another process).
    """
    counts = _fresh_counts()
    expected = shard.records or 0
    if witness_every is None:
        witness_every = max(1, min(1000, expected // 16)) if expected else 250
    rng = random.Random(f"{witness_seed}|{shard.sha256}")
    obs_rows: list[np.ndarray] = []
    cand_rows: list[np.ndarray] = []
    soft_rows: list[np.ndarray] = []
    widths: list[int] = []
    scalars: dict[str, list] = {k: [] for k in Block.ARRAYS[4:]}
    started = time.perf_counter()
    for i, record in enumerate(iter_records(shard)):
        counts["records"] += 1
        if i % validate_every == 0:
            # integrity (the record's own hash) is fail-closed; the CURRENT
            # schema's rules for fields the pipeline never consumes (the
            # pre-repair ``exploration`` shape, {rate, added} without
            # pool_count) are counted and reported, not refused
            if record_sha256(record) != record.get("record_sha256"):
                raise TrainDataError(f"{shard.label} record {i}: record_sha256 drift")
            try:
                validate_record(record)
            except SchemaError as exc:
                counts["legacy_schema"] += 1
                counts.setdefault("legacy_schema_note", str(exc)[:160])
            counts["validated"] += 1
        if record.get("schema") != SCHEMA:
            counts["skipped"]["wrong_schema"] += 1
            continue
        outcome = record.get("outcome")
        if not isinstance(outcome, dict) or outcome.get("signed_level_utility") is None:
            counts["skipped"]["no_outcome"] += 1
            continue
        witness = i % witness_every == 0
        try:
            sample = encode_record(record, counts["preference"],
                                   witness_rng=rng if witness else None,
                                   search_counts=counts["search_mean"])
        except PrivacyError:
            raise
        except TrainDataError as exc:
            reason = ("turn_mismatch" if "turn" in str(exc) else "rebuild_failed")
            counts["skipped"][reason] += 1
            continue
        if witness:
            counts["privacy_witness"]["records"] += 1
            counts["privacy_witness"]["permutations"] += PRIVACY_TRIALS
        k = int(sample.cand.shape[0])
        obs_rows.append(sample.obs)
        cand_rows.append(sample.cand)
        soft_rows.append(sample.softmax if sample.softmax is not None
                         else np.zeros(k, dtype=np.float32))
        widths.append(k)
        scalars["has_softmax"].append(sample.softmax is not None)
        scalars["played"].append(sample.played)
        scalars["utility"].append(sample.utility)
        scalars["attacker_points"].append(sample.attacker_points)
        scalars["points_so_far"].append(sample.points_so_far)
        scalars["ply"].append(sample.ply)
        scalars["role_attacker"].append(sample.role_attacker)
        scalars["seat"].append(sample.seat)
        scalars["cluster"].append(sample.cluster)
        scalars["record_sha256"].append(sample.sha256)
        scalars["source_ref"].append(sample.source_ref)
        scalars["search_mean"].append(0.0 if sample.search_mean is None
                                      else sample.search_mean)
        scalars["has_search_mean"].append(sample.search_mean is not None)
        counts["encoded"] += 1
        if progress and counts["encoded"] % 5000 == 0:
            progress({"label": shard.label, "records": counts["records"],
                      "encoded": counts["encoded"],
                      "secs": round(time.perf_counter() - started, 1)})
    n = counts["encoded"]
    offsets = np.zeros(n + 1, dtype=np.int64)
    offsets[1:] = np.cumsum(np.asarray(widths, dtype=np.int64)) if n else 0
    arrays = {
        "obs": (np.stack(obs_rows) if n else np.zeros((0, OBS_DIM), np.float32)),
        "cand_offsets": offsets,
        "cand_feats": (np.concatenate(cand_rows) if n else np.zeros((0, ACT_DIM), np.float32)),
        "cand_softmax": (np.concatenate(soft_rows) if n else np.zeros(0, np.float32)),
        "has_softmax": np.asarray(scalars["has_softmax"], dtype=bool),
        "played": np.asarray(scalars["played"], dtype=np.int32),
        "utility": np.asarray(scalars["utility"], dtype=np.float32),
        "attacker_points": np.asarray(scalars["attacker_points"], dtype=np.float32),
        "points_so_far": np.asarray(scalars["points_so_far"], dtype=np.float32),
        "ply": np.asarray(scalars["ply"], dtype=np.int32),
        "role_attacker": np.asarray(scalars["role_attacker"], dtype=bool),
        "seat": np.asarray(scalars["seat"], dtype=np.int8),
        "cluster": np.asarray(scalars["cluster"], dtype=str),
        "record_sha256": np.asarray(scalars["record_sha256"], dtype="S64"),
        "source_ref": np.asarray(scalars["source_ref"], dtype=str),
        "search_mean": np.asarray(scalars["search_mean"], dtype=np.float32),
        "has_search_mean": np.asarray(scalars["has_search_mean"], dtype=bool),
    }
    meta = {
        "schema": CACHE_SCHEMA,
        "encoder": encoder_identity(),
        "shard": {"label": shard.label, "sha256": shard.sha256, "records": shard.records,
                  "cluster": shard.cluster, "store": shard.store},
        "counts": counts,
        "witness_seed": witness_seed,
        "witness_every": witness_every,
    }
    path = cache_path(cache_dir, shard.sha256)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")   # unique per builder
    with open(tmp, "wb") as fh:
        if private:
            os.fchmod(fh.fileno(), 0o600)
        np.savez_compressed(fh, meta=np.asarray(json.dumps(meta, sort_keys=True)), **arrays)
    os.chmod(tmp, 0o600 if private else 0o644)
    os.replace(tmp, path)
    return path, counts


def load_block(path: str | os.PathLike, *, shard_sha256: str | None = None) -> Block:
    """Load a cache file; refuses a wrong schema / encoder / shard hash."""
    with np.load(path, allow_pickle=False) as npz:
        meta = json.loads(str(npz["meta"]))
        if meta.get("schema") != CACHE_SCHEMA:
            raise TrainDataError(f"{path}: cache schema {meta.get('schema')!r}")
        enc = meta.get("encoder") or {}
        if (enc.get("implementation_sha256") != ENCODER_IMPLEMENTATION_SHA256
                or enc.get("enc_version") != ENC_VERSION):
            raise TrainDataError(f"{path}: cache built by another encoder")
        if shard_sha256 is not None and meta["shard"]["sha256"] != shard_sha256:
            raise TrainDataError(f"{path}: cache derived from another shard")
        arrays = {name: npz[name] for name in Block.ARRAYS}
    return Block(arrays, meta, str(path))


def ensure_cache(shard: ShardRef, cache_dir: str | os.PathLike, *,
                 witness_seed: int = 0, private: bool = False,
                 progress: Callable[[dict], None] | None = None) -> tuple[Block, bool]:
    """``(block, rebuilt)``: the cache is regenerated when missing or when
    its keys (shard hash, encoder hash) do not match."""
    path = cache_path(cache_dir, shard.sha256)
    if path.is_file():
        try:
            return load_block(path, shard_sha256=shard.sha256), False
        except (TrainDataError, OSError, ValueError, KeyError):
            pass
    build_cache(shard, cache_dir, witness_seed=witness_seed, private=private,
                progress=progress)
    return load_block(path, shard_sha256=shard.sha256), True


# ---------------------------------------------------------- parallel build

def default_cache_workers() -> int:
    """``min(CACHE_WORKERS_CAP, cpu count)``, at least 1."""
    return max(1, min(CACHE_WORKERS_CAP, os.cpu_count() or 1))


def _try_load(path: Path, shard_sha256: str) -> Block | None:
    """The valid cached block at ``path`` or None (missing / stale / other
    encoder / other shard)."""
    if not path.is_file():
        return None
    try:
        return load_block(path, shard_sha256=shard_sha256)
    except (TrainDataError, OSError, ValueError, KeyError):
        return None


def _build_cache_task(task: tuple) -> dict:
    """Pool worker: build one shard's cache (module-level so ``spawn`` can
    import it); the return value carries counts only."""
    shard, cache_dir, witness_seed, private = task
    started = time.perf_counter()
    _path, counts = build_cache(shard, cache_dir, witness_seed=witness_seed,
                                private=private)
    return {"sha256": shard.sha256, "label": shard.label, "records": counts["records"],
            "encoded": counts["encoded"], "secs": round(time.perf_counter() - started, 3)}


def build_caches(jobs: Sequence[tuple[ShardRef, bool]], cache_dir: str | os.PathLike, *,
                 witness_seed: int = 0, workers: int | None = None,
                 progress: Callable[[str], None] | None = None) -> list[dict]:
    """Build the caches of ``jobs`` (``(shard, private)`` pairs; a shard
    listed twice is built once).  ``workers`` (default
    ``default_cache_workers()``) shards are encoded at a time in a pool of
    SPAWNED processes; with one worker, or one job, everything runs in this
    process.  Both paths call the same ``build_cache`` on each shard, so the
    files are byte-identical.  Returns one summary per shard built (the pool
    reports in completion order; the parent later loads in store order)."""
    unique: dict[str, tuple[ShardRef, bool]] = {}
    for shard, private in jobs:
        unique.setdefault(shard.sha256, (shard, private))
    jobs = list(unique.values())
    workers = default_cache_workers() if workers is None else max(1, int(workers))
    say = progress or (lambda _s: None)
    results: list[dict] = []
    if workers == 1 or len(jobs) <= 1:
        for shard, private in jobs:
            started = time.perf_counter()

            def note(event, label=shard.label):
                say(f"cache {label}: records={event['records']} "
                    f"encoded={event['encoded']} secs={event['secs']}")

            _path, counts = build_cache(shard, cache_dir, witness_seed=witness_seed,
                                        private=private, progress=note)
            results.append({"sha256": shard.sha256, "label": shard.label,
                            "records": counts["records"], "encoded": counts["encoded"],
                            "secs": round(time.perf_counter() - started, 3)})
            say(f"cache {shard.label}: built encoded={counts['encoded']} "
                f"secs={results[-1]['secs']}")
        return results
    tasks = [(shard, str(cache_dir), int(witness_seed), bool(private))
             for shard, private in jobs]
    say(f"cache: building {len(tasks)} shard(s) with {min(workers, len(tasks))} workers")
    ctx = multiprocessing.get_context("spawn")
    with ctx.Pool(processes=min(workers, len(tasks))) as pool:
        for result in pool.imap_unordered(_build_cache_task, tasks):
            results.append(result)
            say(f"cache {result['label']}: built encoded={result['encoded']} "
                f"secs={result['secs']} ({len(results)}/{len(tasks)})")
    return results


def ensure_caches(shards: Sequence[tuple[ShardRef, bool]], cache_dir: str | os.PathLike, *,
                  witness_seed: int = 0, workers: int | None = None,
                  progress: Callable[[str], None] | None = None
                  ) -> list[tuple[Block, bool]]:
    """``[(block, rebuilt), ...]`` in the order of ``shards`` (``(shard,
    private)`` pairs): the caches that are missing or whose keys (shard
    hash, encoder hash) do not match are built first, ``workers`` at a time
    (``build_caches``), then every block is loaded."""
    loaded = [_try_load(cache_path(cache_dir, s.sha256), s.sha256) for s, _p in shards]
    pending = [(s, p) for (s, p), b in zip(shards, loaded) if b is None]
    if pending:
        build_caches(pending, cache_dir, witness_seed=witness_seed, workers=workers,
                     progress=progress)
    out: list[tuple[Block, bool]] = []
    for (shard, _private), block in zip(shards, loaded):
        if block is None:
            block = load_block(cache_path(cache_dir, shard.sha256), shard_sha256=shard.sha256)
            out.append((block, True))
        else:
            out.append((block, False))
    return out


# ------------------------------------------------------------------ splits

def split_clusters(keys: Sequence[str], *, seed: int, val_fraction: float = 0.1
                   ) -> dict[str, str]:
    """Assign every deal cluster to ``train`` or ``val`` by the rank of
    ``sha256(seed|key)``: the top ``val_fraction`` of clusters (at least one
    when there are two or more) are held out.  A cluster is never split."""
    unique = sorted(set(str(k) for k in keys))
    if not 0.0 <= val_fraction < 1.0:
        raise TrainDataError("val_fraction must be in [0, 1)")
    ranked = sorted(unique, key=lambda k: hashlib.sha256(
        f"{seed}|{k}".encode("utf-8")).hexdigest())
    n_val = int(round(val_fraction * len(unique)))
    if len(unique) >= 2 and val_fraction > 0:
        n_val = max(1, n_val)
    n_val = min(n_val, len(unique) - 1) if unique else 0
    held = set(ranked[:n_val])
    return {k: ("val" if k in held else "train") for k in unique}


def split_mask(block: Block, assignment: Mapping[str, str], part: str) -> np.ndarray:
    return np.asarray([assignment.get(str(c), "train") == part for c in block.cluster],
                      dtype=bool)


# ------------------------------------------------------------------ batches

def collate(block: Block, idx: np.ndarray) -> dict[str, np.ndarray]:
    """Rows ``idx`` of ``block`` padded to the widest ballot of the batch:
    candidates outside a record's ballot are masked (never scored)."""
    idx = np.asarray(idx, dtype=np.int64)
    b = len(idx)
    widths = block.widths[idx]
    kmax = int(widths.max()) if b and widths.size else 0
    total = int(widths.sum())
    rows = np.repeat(np.arange(b), widths)
    cols = np.arange(total) - np.repeat(np.cumsum(widths) - widths, widths)
    src = np.repeat(block.cand_offsets[idx], widths) + cols
    cand = np.zeros((b, max(kmax, 1), ACT_DIM), dtype=np.float32)
    mask = np.zeros((b, max(kmax, 1)), dtype=bool)
    target = np.zeros((b, max(kmax, 1)), dtype=np.float32)
    if total:
        cand[rows, cols] = block.cand_feats[src]
        mask[rows, cols] = True
        target[rows, cols] = block.cand_softmax[src]
    return {
        "obs": block.obs[idx],
        "cand": cand, "mask": mask, "target": target,
        "has_softmax": block.has_softmax[idx],
        "played": block.played[idx],
        "utility": block.utility[idx],
        "attacker_points": block.attacker_points[idx],
        "search_mean": block.search_mean[idx],
        "has_search_mean": block.has_search_mean[idx],
        "widths": widths,
        "idx": idx,
    }


class BlockStore:
    """The cached blocks of one run, loaded lazily a window at a time so
    a store far larger than memory streams through training."""

    def __init__(self, entries: Sequence[tuple[ShardRef, str]], *,
                 keep_loaded: bool = True):
        self.entries = list(entries)
        self.keep_loaded = keep_loaded
        self._loaded: dict[int, Block] = {}

    def __len__(self) -> int:
        return len(self.entries)

    def block(self, i: int) -> Block:
        if i in self._loaded:
            return self._loaded[i]
        shard, path = self.entries[i]
        block = load_block(path, shard_sha256=shard.sha256)
        if self.keep_loaded:
            self._loaded[i] = block
        return block

    def preload(self, blocks: Sequence[Block]) -> None:
        for i, b in enumerate(blocks):
            self._loaded[i] = b

    def iter_blocks(self) -> Iterator[Block]:
        for i in range(len(self.entries)):
            yield self.block(i)

    def cluster_keys(self) -> list[str]:
        keys: set[str] = set()
        for block in self.iter_blocks():
            keys.update(str(c) for c in np.unique(block.cluster))
        return sorted(keys)

    def iter_batches(self, mask_fn: Callable[[Block], np.ndarray], batch_size: int, *,
                     rng: np.random.Generator | None = None, window: int = 64
                     ) -> Iterator[dict[str, np.ndarray]]:
        """Batches over the rows selected by ``mask_fn`` per block.  With
        ``rng`` the block order and the rows within each window of blocks
        are shuffled (a fixed seed reproduces the exact batch sequence)."""
        order = np.arange(len(self.entries))
        if rng is not None:
            rng.shuffle(order)
        for start in range(0, len(order), max(1, window)):
            blocks = []
            for i in order[start:start + max(1, window)]:
                block = self.block(int(i))
                sel = np.flatnonzero(mask_fn(block))
                if sel.size:
                    blocks.append(block.subset(sel))
            if not blocks:
                continue
            merged = Block.concat(blocks)
            idx = np.arange(merged.n)
            if rng is not None:
                rng.shuffle(idx)
            for b0 in range(0, merged.n, batch_size):
                yield collate(merged, idx[b0:b0 + batch_size])
