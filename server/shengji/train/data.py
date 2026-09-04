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
production ``rl.encode.encode_obs`` / ``encode_action`` encode it.

PRIVACY boundary (structural, every row)
----------------------------------------
``privacy_witness`` permutes the hidden cards among the NON-acting seats
(hand sizes kept; the kitty joins the pool when the actor is not the
banker), re-encodes, and demands a byte-identical state and candidate
encoding.  ``build_cache`` runs it on EVERY row it caches
(``witness_every=1``): an encoder that reads a hand the actor cannot see,
on any state, refuses the whole shard (``PrivacyError``) before anything is
cached or trained on.  Sampling (``witness_every > 1``) is refused unless
the caller passes ``allow_sampled_witness=True`` (the CLI's
``--allow-sampled-privacy-witness``); the cache ``meta`` records
``witness_every`` and ``witness_sampled`` and a production build never
reuses a cache whose witness was sparser than it requires.

DEAL identity (global, every source)
------------------------------------
Every cached row carries ``deal_key`` = ``DEAL_KEY_SCHEMA`` digest of the
dealt deck (the 108-card order the state was rebuilt from) -- the same
recipe as ``rl.value_afterstate._deal_key``.  It ignores run ids, policies,
knobs, mirrors and source labels: the self-play generator deals from
``seed0 + cluster``, so two stores with the same ``seed0`` and different
knobs hold the SAME deals under different ``run_id``s, and both mirrors of
a cluster are one deal.  Splits (``split_deals``) and the cluster bootstrap
are keyed by ``deal_key``; ``cluster`` (``<run_id>:<cluster>`` /
the Luna deal ref) is kept as an informational column only.

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
``meta`` JSON (schema, encoder identity, shard hash, counts, witness
settings, decoded ``nbytes``).  Rebuilt when missing or when either key
changes; never a source of truth.  The file is a pure function of (shard
bytes, encoder, witness seed, witness_every): no timing or host detail is
stamped inside, so ``ensure_caches`` may build the missing shards in a pool
of spawned worker processes (``workers`` at a time, one shard per task) and
produce byte-identical files to the in-process build.

RESIDENCY contract (bounded, honest)
------------------------------------
``BlockStore`` decodes blocks on demand into a ``Residency`` (an LRU of
decoded blocks with a byte budget, shared by every store of one run): at
most ``resident_bytes`` of decoded blocks are held at any time (``None``:
everything stays resident; the store then IS the corpus in memory).  Room
is made BEFORE a block is decoded (its size is in the cache meta), and
every array of a block is decoded straight into an anonymous ``mmap``
(``_read_member``: no malloc'd temporary), so evicting a block unmaps its
pages at once instead of leaving them in the allocator's cache -- the
bound holds for the process RSS, not only for the bookkeeping.  A batch
is gathered straight from the resident blocks of the current shuffle
window (``gather``: one batch-sized copy, never a window-sized one), so
the data's memory is ``resident_bytes`` plus one batch plus the per-window
index arrays.  A window holds at most ``window`` blocks and at most
``resident_bytes`` of them; a single block above the budget refuses (raise
the budget or shard the store).  The batch SEQUENCE is a function of the
seed alone: block order and the row order within each window are drawn
from ``rng`` regardless of the budget, so a run with a small budget
reproduces the batches of an unbounded one (it only reloads more).
"""

from __future__ import annotations

import hashlib
import itertools
import json
import math
import mmap
import multiprocessing
import os
import random
import re
import time
import zipfile
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Collection, Iterator, Mapping, Sequence

import numpy as np
from numpy.lib import format as npy_format

from ..engine.cards import make_deck
from ..harvest.common import action_key, sha256_file
from ..harvest.rebuild import RebuildError, state_for_record
from ..harvest.schema import SCHEMA, SchemaError, record_sha256, validate_record
from ..harvest.trajectory import (MANIFEST_SCHEMA as TRAJECTORY_MANIFEST_SCHEMA,
                                  SHARD_SCHEMA, TrajectoryError,
                                  preference_from_record)
from ..rl.encode import (ACT_DIM, CARD_INDEX, ENC_VERSION, ENCODER_IMPLEMENTATION_SHA256,
                         ENCODER_SOURCE_SHA256S, OBS_DIM, OBS_SCHEMA,
                         encode_action, encode_obs)
from ..rl.encoder_identity import encoder_contract

#: v3: + deal_key column, nbytes / witness_every / witness_sampled in meta
CACHE_SCHEMA = "shengji-train-cache-v3"
HARVEST_MANIFEST_SCHEMA = "shengji-harvest-manifest-v1"
LAYOUTS = ("shard-store", "merged", "jsonl")
#: the deal identity recipe; MUST equal ``rl.value_afterstate.DEAL_KEY_SCHEMA``
#: (pinned by ``tests/test_train_v0.py``): sha256 over the schema string and
#: the dealt deck's card codes, each length-prefixed (2 bytes, big endian)
DEAL_KEY_SCHEMA = "shengji-value-deal-key-v1"
DECK_SIZE = len(make_deck())
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
SPLIT_PARTS = ("train", "val", "test")
#: default residency budget: this share of physical memory
DEFAULT_RESIDENT_FRACTION = 0.4


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


def deal_key(deck: Sequence[str]) -> str:
    """The canonical identity of a deal: ``deck:<sha256>`` over the dealt
    108-card order (``DEAL_KEY_SCHEMA``; the recipe of
    ``rl.value_afterstate._deal_key``).  Independent of run id, policy,
    knobs, mirror and source: the same deal keys the same everywhere."""
    if (type(deck) is not list or len(deck) != DECK_SIZE
            or any(type(card) is not str or card not in CARD_INDEX for card in deck)):
        raise TrainDataError("deal key: the deck is not the dealt 108-card order")
    digest = hashlib.sha256(DEAL_KEY_SCHEMA.encode("ascii"))
    for card in deck:
        encoded = card.encode("ascii")
        digest.update(len(encoded).to_bytes(2, "big"))
        digest.update(encoded)
    return f"deck:{digest.hexdigest()}"


def physical_memory_bytes() -> int | None:
    """Installed RAM, or None when the platform does not say."""
    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        page = os.sysconf("SC_PAGE_SIZE")
    except (ValueError, OSError, AttributeError):
        return None
    if pages <= 0 or page <= 0:
        return None
    return int(pages) * int(page)


def default_resident_bytes() -> int:
    """``DEFAULT_RESIDENT_FRACTION`` of physical memory (2 GiB when unknown)."""
    total = physical_memory_bytes()
    if total is None:
        return 2 * 1024 ** 3
    return int(total * DEFAULT_RESIDENT_FRACTION)


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
    """The source's own deal cluster label (informational; splits use
    ``deal_key``): ``<run_id>:<cluster>`` for the self-play generator (both
    mirrors of a deal), else the source_ref with its mirror and event
    fragments removed (Luna: one label per deal)."""
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
                    rng: random.Random, *, trials: int = PRIVACY_TRIALS,
                    base_obs: bytes | None = None,
                    base_cand: Sequence[bytes] | None = None) -> int:
    """Permute the hidden cards among the NON-acting seats (each hand keeps
    its size; the kitty joins the pool unless the actor is the banker) and
    require byte-identical state and candidate encodings.  ``base_obs`` /
    ``base_cand`` are the encodings of the unpermuted state when the caller
    already has them (``encode_record``), else they are computed here.
    Returns the number of permutations checked; raises ``PrivacyError``."""
    if base_obs is None:
        base_obs = np.asarray(encode_obs(rnd, seat), dtype=np.float32).tobytes()
    if base_cand is None:
        base_cand = [np.asarray(encode_action(list(c), rnd), dtype=np.float32).tobytes()
                     for c in (ballot or [])]
    base_act = list(base_cand)
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
    cluster: str                # the source's cluster label (informational)
    deal_key: str               # canonical deal identity (splits, bootstrap)
    sha256: str
    source_ref: str
    search_mean: float | None = None   # aux target, points scale (module docstring)


def encode_record(record: Mapping[str, Any], pref_counts: dict[str, int],
                  *, witness_rng: random.Random | None = None,
                  search_counts: dict[str, int] | None = None) -> Sample:
    """Rebuild, encode and target one record (raises on a bad record).
    With ``witness_rng`` the privacy witness runs on THIS row against the
    encoding that is returned."""
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
    key = deal_key(list(rnd.deck))
    obs = np.asarray(encode_obs(rnd, seat), dtype=np.float32)
    cand = (np.asarray([encode_action(list(c), rnd) for c in ballot], dtype=np.float32)
            if ballot else np.zeros((0, ACT_DIM), dtype=np.float32))
    if witness_rng is not None:
        privacy_witness(rnd, seat, ballot, witness_rng, base_obs=obs.tobytes(),
                        base_cand=[row.tobytes() for row in cand])
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
        seat=seat, kind=kind, cluster=cluster_key(record), deal_key=key,
        sha256=str(record.get("record_sha256") or ""),
        source_ref=str(record["source_ref"]),
        search_mean=search_mean)


# ------------------------------------------------------------------- blocks

class Block:
    """One cached shard, fully decoded (numpy arrays)."""

    ARRAYS = ("obs", "cand_offsets", "cand_feats", "cand_softmax", "has_softmax",
              "played", "utility", "attacker_points", "points_so_far", "ply",
              "role_attacker", "seat", "cluster", "record_sha256", "source_ref",
              "search_mean", "has_search_mean", "deal_key")
    #: per-row scalar arrays (everything but the observation / candidate arrays)
    SCALARS = ARRAYS[4:]

    def __init__(self, arrays: dict[str, np.ndarray], meta: dict, path: str | None = None):
        for name in self.ARRAYS:
            setattr(self, name, arrays[name])
        self.meta = meta
        self.path = path
        self.n = int(self.obs.shape[0])
        self.nbytes = int(sum(int(arrays[name].nbytes) for name in self.ARRAYS))

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
        for name in self.SCALARS:
            arrays[name] = getattr(self, name)[idx]
        return Block(arrays, self.meta, self.path)

    def anonymous(self) -> "Block":
        """The same block with every array copied into an anonymous mmap
        (``_anon_copy``), so that dropping it unmaps its pages at once."""
        return Block({name: _anon_copy(getattr(self, name)) for name in self.ARRAYS},
                     self.meta, self.path)


#: bytes read per ``read`` call while decoding a cache member: small enough
#: that the transient chunks are served from the allocator's recycled small
#: classes (a large freed chunk is parked, not returned, on macOS)
_READ_CHUNK = 64 << 10


def _anon_zeros(shape: tuple[int, ...] | int, dtype) -> np.ndarray:
    """A zero-filled array over an anonymous mmap: its pages come back to
    the OS (``munmap``) when the last array over it dies, instead of being
    parked in the allocator's free-list cache as a freed malloc chunk is."""
    dtype = np.dtype(dtype)
    shape = (int(shape),) if isinstance(shape, (int, np.integer)) else tuple(int(s) for s in shape)
    nbytes = int(np.prod(shape, dtype=np.int64)) * dtype.itemsize if shape else dtype.itemsize
    if nbytes == 0:
        return np.zeros(shape, dtype=dtype)
    return np.frombuffer(mmap.mmap(-1, nbytes), dtype=dtype).reshape(shape)


def _anon_copy(array: np.ndarray) -> np.ndarray:
    """A C-contiguous copy of ``array`` in an anonymous mmap (``_anon_zeros``)."""
    array = np.ascontiguousarray(array)
    if array.nbytes == 0:
        return array
    out = _anon_zeros(array.shape, array.dtype)
    out[...] = array
    return out


def _read_member_fallback(zf: zipfile.ZipFile, name: str) -> np.ndarray:
    with np.load(zf.filename, allow_pickle=False) as npz:
        return _anon_copy(npz[name])


def _read_member(zf: zipfile.ZipFile, name: str) -> np.ndarray:
    """Decode the ``.npy`` member ``name`` of a cache file straight into an
    anonymous mmap (``readinto`` in ``_READ_CHUNK`` pieces; no malloc'd
    temporary of the array's size).  A member in a layout this reader does
    not handle (Fortran order, a later header version) falls back to
    numpy's own reader, copied into an mmap afterwards."""
    readers = {(1, 0): npy_format.read_array_header_1_0,
               (2, 0): npy_format.read_array_header_2_0}
    with zf.open(name + ".npy") as fp:
        version = npy_format.read_magic(fp)
        if version not in readers:
            return _read_member_fallback(zf, name)
        shape, fortran, dtype = readers[version](fp)
        if fortran or dtype.hasobject:
            return _read_member_fallback(zf, name)
        out = _anon_zeros(shape, dtype)
        nbytes = int(out.nbytes)
        if nbytes == 0:
            return out
        view = memoryview(out.reshape(-1).view(np.uint8))
        got = 0
        while got < nbytes:
            chunk = fp.read(min(_READ_CHUNK, nbytes - got))
            if not chunk:
                raise TrainDataError(f"{zf.filename}: member {name} is truncated")
            view[got:got + len(chunk)] = chunk
            got += len(chunk)
        return out


def cache_path(cache_dir: str | os.PathLike, shard_sha256: str) -> Path:
    return Path(cache_dir) / f"{shard_sha256}.{encoder_cache_key()}.npz"


def _fresh_counts() -> dict:
    return {"records": 0, "encoded": 0,
            "skipped": {k: 0 for k in SKIP_REASONS},
            "preference": {k: 0 for k in PREFERENCE_KEYS},
            "search_mean": {k: 0 for k in SEARCH_MEAN_KEYS},
            "privacy_witness": {"records": 0, "permutations": 0},
            "validated": 0, "legacy_schema": 0}


def check_witness_every(witness_every: int, allow_sampled: bool) -> int:
    """``witness_every`` as an int >= 1; > 1 (a SAMPLED privacy witness)
    refuses unless explicitly allowed."""
    every = int(witness_every)
    if every < 1:
        raise TrainDataError("witness_every must be >= 1")
    if every > 1 and not allow_sampled:
        raise TrainDataError(
            f"privacy witness every {every} rows would leave rows unchecked: the "
            "boundary is enforced on EVERY row in production; pass "
            "--allow-sampled-privacy-witness to sample (the receipt records it)")
    return every


def build_cache(shard: ShardRef, cache_dir: str | os.PathLike, *,
                witness_seed: int = 0, witness_every: int = 1,
                allow_sampled_witness: bool = False,
                validate_every: int = 500,
                progress: Callable[[dict], None] | None = None,
                private: bool = False) -> tuple[Path, dict]:
    """Encode every usable record of ``shard`` into its cache file.

    The privacy witness runs on EVERY encoded record (``witness_every=1``,
    the production setting; ``PRIVACY_TRIALS`` permutations each) and the
    full schema validation on every ``validate_every``-th; a privacy
    failure refuses the whole shard and leaves no file.  ``witness_every >
    1`` needs ``allow_sampled_witness`` and is recorded in the ``meta``.
    The file's bytes depend on nothing but the shard, the encoder,
    ``witness_seed`` and ``witness_every`` (no timing inside:
    ``ensure_caches`` may build it in another process).
    """
    witness_every = check_witness_every(witness_every, allow_sampled_witness)
    counts = _fresh_counts()
    counts["privacy_witness"]["every"] = witness_every
    rng = random.Random(f"{witness_seed}|{shard.sha256}")
    obs_rows: list[np.ndarray] = []
    cand_rows: list[np.ndarray] = []
    soft_rows: list[np.ndarray] = []
    widths: list[int] = []
    scalars: dict[str, list] = {k: [] for k in Block.SCALARS}
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
        scalars["deal_key"].append(sample.deal_key)
        counts["encoded"] += 1
        if progress and counts["encoded"] % 5000 == 0:
            progress({"label": shard.label, "records": counts["records"],
                      "encoded": counts["encoded"],
                      "secs": round(time.perf_counter() - started, 1)})
    n = counts["encoded"]
    if witness_every == 1 and counts["privacy_witness"]["records"] != n:
        raise PrivacyError(f"{shard.label}: {counts['privacy_witness']['records']} of {n} "
                           "encoded rows were witnessed; refusing")
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
        "deal_key": np.asarray(scalars["deal_key"], dtype=str),
    }
    nbytes = int(sum(int(a.nbytes) for a in arrays.values()))
    meta = {
        "schema": CACHE_SCHEMA,
        "encoder": encoder_identity(),
        "shard": {"label": shard.label, "sha256": shard.sha256, "records": shard.records,
                  "cluster": shard.cluster, "store": shard.store},
        "counts": counts,
        "witness_seed": witness_seed,
        "witness_every": witness_every,
        "witness_sampled": witness_every != 1,
        "deal_key_schema": DEAL_KEY_SCHEMA,
        "deals": int(len(set(scalars["deal_key"]))),
        "nbytes": nbytes,
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


def check_meta(meta: Mapping[str, Any], *, path: str | os.PathLike,
               shard_sha256: str | None = None, witness_every: int | None = None) -> dict:
    """Refuse a cache ``meta`` of another schema / encoder / shard, or one
    whose privacy witness was sparser than ``witness_every`` requires."""
    if meta.get("schema") != CACHE_SCHEMA:
        raise TrainDataError(f"{path}: cache schema {meta.get('schema')!r}")
    enc = meta.get("encoder") or {}
    if (enc.get("implementation_sha256") != ENCODER_IMPLEMENTATION_SHA256
            or enc.get("enc_version") != ENC_VERSION):
        raise TrainDataError(f"{path}: cache built by another encoder")
    if shard_sha256 is not None and meta["shard"]["sha256"] != shard_sha256:
        raise TrainDataError(f"{path}: cache derived from another shard")
    if witness_every is not None and int(meta.get("witness_every", 0) or 0) > int(witness_every):
        raise PrivacyError(f"{path}: cache witnessed every {meta.get('witness_every')} rows, "
                           f"this run requires every {witness_every}; refusing to reuse")
    return dict(meta)


def read_meta(path: str | os.PathLike) -> dict:
    """The ``meta`` JSON of a cache file (the arrays are not decoded)."""
    with np.load(path, allow_pickle=False) as npz:
        return json.loads(str(npz["meta"]))


def read_column(path: str | os.PathLike, name: str) -> np.ndarray:
    """One per-row array of a cache file (only that member is decoded,
    into an anonymous mmap)."""
    with zipfile.ZipFile(path) as zf:
        return _read_member(zf, name)


def load_block(path: str | os.PathLike, *, shard_sha256: str | None = None,
               witness_every: int | None = None) -> Block:
    """Load a cache file; refuses a wrong schema / encoder / shard hash and,
    with ``witness_every``, a cache witnessed more sparsely than that.
    Every array lands in its own anonymous mmap (``_read_member``)."""
    meta = check_meta(read_meta(path), path=path, shard_sha256=shard_sha256,
                      witness_every=witness_every)
    with zipfile.ZipFile(path) as zf:
        arrays = {name: _read_member(zf, name) for name in Block.ARRAYS}
    return Block(arrays, meta, str(path))


def ensure_cache(shard: ShardRef, cache_dir: str | os.PathLike, *,
                 witness_seed: int = 0, witness_every: int = 1,
                 allow_sampled_witness: bool = False, private: bool = False,
                 progress: Callable[[dict], None] | None = None) -> tuple[Block, bool]:
    """``(block, rebuilt)``: the cache is regenerated when missing, when its
    keys (shard hash, encoder hash) do not match, or when its privacy
    witness was sparser than ``witness_every``."""
    witness_every = check_witness_every(witness_every, allow_sampled_witness)
    path = cache_path(cache_dir, shard.sha256)
    if _valid_meta(path, shard.sha256, witness_every) is not None:
        return load_block(path, shard_sha256=shard.sha256, witness_every=witness_every), False
    build_cache(shard, cache_dir, witness_seed=witness_seed, witness_every=witness_every,
                allow_sampled_witness=allow_sampled_witness, private=private,
                progress=progress)
    return load_block(path, shard_sha256=shard.sha256, witness_every=witness_every), True


# ---------------------------------------------------------- parallel build

def default_cache_workers() -> int:
    """``min(CACHE_WORKERS_CAP, cpu count)``, at least 1."""
    return max(1, min(CACHE_WORKERS_CAP, os.cpu_count() or 1))


def _valid_meta(path: Path, shard_sha256: str, witness_every: int) -> dict | None:
    """The ``meta`` of the valid cache at ``path`` or None (missing / stale /
    other encoder / other shard / sparser privacy witness)."""
    if not Path(path).is_file():
        return None
    try:
        return check_meta(read_meta(path), path=path, shard_sha256=shard_sha256,
                          witness_every=witness_every)
    except (TrainDataError, OSError, ValueError, KeyError):
        return None


def _build_cache_task(task: tuple) -> dict:
    """Pool worker: build one shard's cache (module-level so ``spawn`` can
    import it); the return value carries counts only."""
    shard, cache_dir, witness_seed, witness_every, allow_sampled, private = task
    started = time.perf_counter()
    _path, counts = build_cache(shard, cache_dir, witness_seed=witness_seed,
                                witness_every=witness_every,
                                allow_sampled_witness=allow_sampled, private=private)
    return {"sha256": shard.sha256, "label": shard.label, "records": counts["records"],
            "encoded": counts["encoded"], "secs": round(time.perf_counter() - started, 3)}


def build_caches(jobs: Sequence[tuple[ShardRef, bool]], cache_dir: str | os.PathLike, *,
                 witness_seed: int = 0, witness_every: int = 1,
                 allow_sampled_witness: bool = False, workers: int | None = None,
                 progress: Callable[[str], None] | None = None) -> list[dict]:
    """Build the caches of ``jobs`` (``(shard, private)`` pairs; a shard
    listed twice is built once).  ``workers`` (default
    ``default_cache_workers()``) shards are encoded at a time in a pool of
    SPAWNED processes; with one worker, or one job, everything runs in this
    process.  Both paths call the same ``build_cache`` on each shard, so the
    files are byte-identical.  Returns one summary per shard built (the pool
    reports in completion order; the parent later loads in store order)."""
    witness_every = check_witness_every(witness_every, allow_sampled_witness)
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
                                        witness_every=witness_every,
                                        allow_sampled_witness=allow_sampled_witness,
                                        private=private, progress=note)
            results.append({"sha256": shard.sha256, "label": shard.label,
                            "records": counts["records"], "encoded": counts["encoded"],
                            "secs": round(time.perf_counter() - started, 3)})
            say(f"cache {shard.label}: built encoded={counts['encoded']} "
                f"secs={results[-1]['secs']}")
        return results
    tasks = [(shard, str(cache_dir), int(witness_seed), int(witness_every),
              bool(allow_sampled_witness), bool(private))
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
                  witness_seed: int = 0, witness_every: int = 1,
                  allow_sampled_witness: bool = False, workers: int | None = None,
                  progress: Callable[[str], None] | None = None
                  ) -> list[tuple[dict, bool]]:
    """``[(meta, rebuilt), ...]`` in the order of ``shards`` (``(shard,
    private)`` pairs): the caches that are missing or whose keys (shard
    hash, encoder hash, privacy witness density) do not match are built
    first, ``workers`` at a time (``build_caches``), then every cache's
    ``meta`` is read (nothing is decoded: residency is the store's job)."""
    witness_every = check_witness_every(witness_every, allow_sampled_witness)
    metas = [_valid_meta(cache_path(cache_dir, s.sha256), s.sha256, witness_every)
             for s, _p in shards]
    pending = [(s, p) for (s, p), m in zip(shards, metas) if m is None]
    if pending:
        build_caches(pending, cache_dir, witness_seed=witness_seed,
                     witness_every=witness_every, allow_sampled_witness=allow_sampled_witness,
                     workers=workers, progress=progress)
    out: list[tuple[dict, bool]] = []
    for (shard, _private), meta in zip(shards, metas):
        if meta is None:
            path = cache_path(cache_dir, shard.sha256)
            meta = check_meta(read_meta(path), path=path, shard_sha256=shard.sha256,
                              witness_every=witness_every)
            out.append((meta, True))
        else:
            out.append((meta, False))
    return out


# ------------------------------------------------------------------ splits

def split_deals(keys: Sequence[str], *, seed: int, val_fraction: float = 0.1,
                test_fraction: float = 0.1) -> dict[str, str]:
    """Assign every deal key to ``train`` / ``val`` / ``test`` by the rank of
    ``sha256(seed|key)``: the top ``test_fraction`` of deals are the TEST
    split (reported metrics; never touched by selection or calibration),
    the next ``val_fraction`` the VALIDATION split (epoch selection and the
    calibration fit), the rest train.  With three or more deals each
    non-zero fraction gets at least one deal; train always keeps one.  A
    deal is never split."""
    unique = sorted(set(str(k) for k in keys))
    for name, frac in (("val_fraction", val_fraction), ("test_fraction", test_fraction)):
        if not 0.0 <= float(frac) < 1.0:
            raise TrainDataError(f"{name} must be in [0, 1)")
    if float(val_fraction) + float(test_fraction) >= 1.0:
        raise TrainDataError("val_fraction + test_fraction must be < 1")
    ranked = sorted(unique, key=lambda k: hashlib.sha256(
        f"{seed}|{k}".encode("utf-8")).hexdigest())
    n = len(unique)
    n_test = int(round(float(test_fraction) * n))
    n_val = int(round(float(val_fraction) * n))
    if n >= 3:
        if test_fraction > 0:
            n_test = max(1, n_test)
        if val_fraction > 0:
            n_val = max(1, n_val)
    elif n == 2:
        # one deal can be held out: the test split (the headline) first
        n_test = 1 if test_fraction > 0 else 0
        n_val = 0 if n_test else (1 if val_fraction > 0 else 0)
    else:
        n_test = n_val = 0
    n_test = min(n_test, max(0, n - 1))
    n_val = min(n_val, max(0, n - 1 - n_test))
    out = {k: "train" for k in unique}
    for k in ranked[:n_test]:
        out[k] = "test"
    for k in ranked[n_test:n_test + n_val]:
        out[k] = "val"
    return out


def part_keys(assignment: Mapping[str, str], part: str) -> np.ndarray:
    return np.asarray(sorted(k for k, v in assignment.items() if v == part), dtype=str)


def split_mask(block: Block, assignment: Mapping[str, str], part: str) -> np.ndarray:
    """Rows of ``block`` whose ``deal_key`` is assigned to ``part``."""
    keys = part_keys(assignment, part)
    if not keys.size:
        return np.zeros(block.n, dtype=bool)
    return np.isin(block.deal_key, keys)


def split_counts(assignment: Mapping[str, str]) -> dict[str, int]:
    return {part: sum(1 for v in assignment.values() if v == part) for part in SPLIT_PARTS}


# ------------------------------------------------------------------ batches

_SCALAR_DTYPES = {"has_softmax": bool, "played": np.int32, "utility": np.float32,
                  "attacker_points": np.float32, "search_mean": np.float32,
                  "has_search_mean": bool}


def gather(blocks: Sequence[Block], which: np.ndarray, rows: np.ndarray
           ) -> dict[str, np.ndarray]:
    """Rows ``rows[j]`` of ``blocks[which[j]]``, in that order, as one batch
    padded to the widest ballot of the batch: candidates outside a record's
    ballot are masked (never scored).  One batch-sized copy (the wide
    arrays over anonymous mmaps, ``_anon_zeros``, so batch churn does not
    accumulate in the allocator); the blocks themselves are not copied."""
    which = np.asarray(which, dtype=np.int64)
    rows = np.asarray(rows, dtype=np.int64)
    b = len(rows)
    widths = np.zeros(b, dtype=np.int64)
    parts = []
    for j in np.unique(which):
        pos = np.flatnonzero(which == j)
        sel = rows[pos]
        widths[pos] = blocks[j].widths[sel]
        parts.append((blocks[j], pos, sel))
    kmax = max(int(widths.max()) if b else 0, 1)
    out: dict[str, np.ndarray] = {
        "obs": _anon_zeros((b, OBS_DIM), np.float32),
        "cand": _anon_zeros((b, kmax, ACT_DIM), np.float32),
        "mask": _anon_zeros((b, kmax), bool),
        "target": _anon_zeros((b, kmax), np.float32),
    }
    for name, dtype in _SCALAR_DTYPES.items():
        out[name] = np.empty(b, dtype=dtype)
    for block, pos, sel in parts:
        out["obs"][pos] = block.obs[sel]
        w = widths[pos]
        total = int(w.sum())
        if total:
            rr = np.repeat(pos, w)
            cols = np.arange(total) - np.repeat(np.cumsum(w) - w, w)
            src = np.repeat(block.cand_offsets[sel], w) + cols
            out["cand"][rr, cols] = block.cand_feats[src]
            out["mask"][rr, cols] = True
            out["target"][rr, cols] = block.cand_softmax[src]
        for name in _SCALAR_DTYPES:
            out[name][pos] = getattr(block, name)[sel]
    out["widths"] = widths
    out["block"] = which
    out["row"] = rows
    return out


def collate(block: Block, idx: np.ndarray) -> dict[str, np.ndarray]:
    """Rows ``idx`` of ``block`` as one padded batch (``gather``)."""
    idx = np.asarray(idx, dtype=np.int64)
    out = gather([block], np.zeros(len(idx), dtype=np.int64), idx)
    out["idx"] = idx
    return out


_STORE_IDS = itertools.count()


class Residency:
    """The decoded blocks of one run, LRU-bounded: at most ``budget`` bytes
    (``None``: unbounded) stay resident; loading past the budget evicts the
    least recently used blocks that are not pinned (the current window).
    Shared by every ``BlockStore`` of a run so the bound is global."""

    def __init__(self, budget: int | None = None):
        if budget is not None and int(budget) <= 0:
            raise TrainDataError("resident_bytes must be positive (or None: unbounded)")
        self.budget = None if budget is None else int(budget)
        self._blocks: "OrderedDict[tuple[int, int], Block]" = OrderedDict()
        self.bytes = 0
        self.peak_bytes = 0
        self.loads = 0
        self.evictions = 0

    def __len__(self) -> int:
        return len(self._blocks)

    def get(self, key: tuple[int, int]) -> Block | None:
        block = self._blocks.get(key)
        if block is not None:
            self._blocks.move_to_end(key)
        return block

    def make_room(self, nbytes: int, *, label: str = "",
                  pinned: Collection[tuple[int, int]] = ()) -> None:
        """Evict least-recently-used, unpinned blocks until ``nbytes`` more
        fit the budget (called BEFORE a block is decoded, with its size from
        the cache meta, so the decode itself never overshoots the budget)."""
        if self.budget is None:
            return
        if nbytes > self.budget:
            raise TrainDataError(
                f"{label}: decodes to {nbytes} bytes, above the residency budget of "
                f"{self.budget}; raise --resident-bytes or shard the store")
        for old in list(self._blocks):
            if self.bytes + nbytes <= self.budget:
                break
            if old in pinned:
                continue
            self.evict(old)
        if self.bytes + nbytes > self.budget:
            raise TrainDataError(
                f"{label}: the pinned window does not fit the residency budget of "
                f"{self.budget} bytes; lower --window or raise --resident-bytes")

    def admit(self, key: tuple[int, int], block: Block, *, label: str = "",
              pinned: Collection[tuple[int, int]] = ()) -> None:
        self.make_room(block.nbytes, label=label or str(key), pinned=pinned)
        self._blocks[key] = block
        self.bytes += block.nbytes
        self.peak_bytes = max(self.peak_bytes, self.bytes)
        self.loads += 1

    def evict(self, key: tuple[int, int]) -> None:
        block = self._blocks.pop(key, None)
        if block is not None:
            self.bytes -= block.nbytes
            self.evictions += 1

    def clear(self) -> None:
        for key in list(self._blocks):
            self.evict(key)

    def describe(self) -> dict:
        return {"budget_bytes": self.budget, "resident_bytes": self.bytes,
                "peak_resident_bytes": self.peak_bytes, "blocks": len(self._blocks),
                "loads": self.loads, "evictions": self.evictions}


class BlockStore:
    """The cached blocks of one run (``entries``: ``(shard, cache path)``),
    decoded on demand into a ``Residency`` (module docstring: RESIDENCY
    contract).  ``keep``: per entry, the deal keys to keep (None: all; the
    filter is applied once, when the block is decoded).  ``witness_every``:
    a cache witnessed more sparsely refuses to load."""

    def __init__(self, entries: Sequence[tuple[ShardRef, str]], *,
                 residency: Residency | None = None, resident_bytes: int | None = None,
                 keep: Sequence[Collection[str] | None] | None = None,
                 witness_every: int = 1):
        self.entries = [(shard, str(path)) for shard, path in entries]
        self.residency = residency if residency is not None else Residency(resident_bytes)
        self.keep = ([None if k is None else np.asarray(sorted(set(k)), dtype=str)
                      for k in keep] if keep is not None else [None] * len(self.entries))
        if len(self.keep) != len(self.entries):
            raise TrainDataError("keep must have one entry per shard")
        self.witness_every = int(witness_every)
        self.id = next(_STORE_IDS)
        self.metas = [check_meta(read_meta(path), path=path, shard_sha256=shard.sha256,
                                 witness_every=self.witness_every)
                      for shard, path in self.entries]
        #: decoded bytes per block as built (an upper bound under ``keep``)
        self.sizes = [int(m.get("nbytes") or 0) for m in self.metas]

    def __len__(self) -> int:
        return len(self.entries)

    @property
    def nbytes(self) -> int:
        """Decoded bytes of the whole store (the all-resident size)."""
        return int(sum(self.sizes))

    def _key(self, i: int) -> tuple[int, int]:
        return (self.id, i)

    def block(self, i: int, *, pinned: Collection[int] = ()) -> Block:
        """Block ``i``, decoded (and filtered) on first use and resident
        until evicted; ``pinned`` blocks of this store are never evicted to
        make room for it.  Room is made BEFORE the decode (the size comes
        from the cache meta), so the budget is never overshot by a decode;
        under ``keep`` the unfiltered block is transiently held as well."""
        key = self._key(i)
        block = self.residency.get(key)
        if block is not None:
            return block
        shard, path = self.entries[i]
        pins = {self._key(j) for j in pinned}
        self.residency.make_room(self.sizes[i], label=shard.label, pinned=pins)
        block = load_block(path, shard_sha256=shard.sha256, witness_every=self.witness_every)
        if self.keep[i] is not None:
            block = block.subset(np.flatnonzero(np.isin(block.deal_key, self.keep[i]))).anonymous()
        self.residency.admit(key, block, label=shard.label, pinned=pins)
        return block

    def column(self, i: int, name: str) -> np.ndarray:
        """One per-row array of block ``i`` (after ``keep``), decoded from
        the file when the block is not resident (only that member)."""
        block = self.residency.get(self._key(i))
        if block is not None:
            return getattr(block, name)
        path = self.entries[i][1]
        col = read_column(path, name)
        if self.keep[i] is not None:
            keys = col if name == "deal_key" else read_column(path, "deal_key")
            col = col[np.isin(keys, self.keep[i])]
        return col

    def rows(self) -> list[int]:
        """Rows per block (after ``keep``)."""
        return [int(self.column(i, "deal_key").shape[0]) for i in range(len(self.entries))]

    def iter_blocks(self) -> Iterator[Block]:
        for i in range(len(self.entries)):
            yield self.block(i)

    def keys(self) -> list[str]:
        """Sorted unique deal keys of the store (nothing stays resident for it)."""
        keys: set[str] = set()
        for i in range(len(self.entries)):
            keys.update(str(k) for k in np.unique(self.column(i, "deal_key")))
        return sorted(keys)

    def windows(self, order: Sequence[int], window: int) -> list[list[int]]:
        """Consecutive groups of ``order``: at most ``window`` blocks and at
        most the residency budget of decoded bytes each."""
        budget = self.residency.budget
        groups: list[list[int]] = []
        cur: list[int] = []
        cur_bytes = 0
        for i in order:
            i = int(i)
            size = self.sizes[i]
            if budget is not None and size > budget:
                raise TrainDataError(
                    f"{self.entries[i][0].label}: decodes to {size} bytes, above the "
                    f"residency budget of {budget}; raise --resident-bytes or shard the store")
            if cur and (len(cur) >= max(1, int(window))
                        or (budget is not None and cur_bytes + size > budget)):
                groups.append(cur)
                cur, cur_bytes = [], 0
            cur.append(i)
            cur_bytes += size
        if cur:
            groups.append(cur)
        return groups

    def iter_batches(self, mask_fn: Callable[[Block], np.ndarray], batch_size: int, *,
                     rng: np.random.Generator | None = None, window: int = 64
                     ) -> Iterator[dict[str, np.ndarray]]:
        """Batches over the rows selected by ``mask_fn`` per block, gathered
        straight from the resident blocks of each window (``gather``).  With
        ``rng`` the block order and the rows within each window are shuffled;
        a fixed seed reproduces the exact batch sequence whatever the
        residency budget.  ``idx`` in a batch is the row's position in the
        window's concatenation; ``block`` (the store's block index) and
        ``row`` locate it."""
        order = np.arange(len(self.entries))
        if rng is not None:
            rng.shuffle(order)
        batch_size = max(1, int(batch_size))
        for group in self.windows(order, window):
            group_ids = np.asarray(group, dtype=np.int64)
            # decode the window (the previous window's references were
            # dropped below, so an evicted block is unmapped before the
            # next one is decoded: the transient never exceeds the budget)
            blocks = [self.block(i, pinned=group) for i in group]
            which_parts: list[np.ndarray] = []
            row_parts: list[np.ndarray] = []
            for j, block in enumerate(blocks):
                sel = np.flatnonzero(mask_fn(block))
                which_parts.append(np.full(sel.size, j, dtype=np.int64))
                row_parts.append(sel.astype(np.int64))
            del block, sel
            which = np.concatenate(which_parts) if which_parts else np.zeros(0, np.int64)
            rows = np.concatenate(row_parts) if row_parts else np.zeros(0, np.int64)
            del which_parts, row_parts
            if rows.size:
                idx = np.arange(rows.size)
                if rng is not None:
                    rng.shuffle(idx)
                for b0 in range(0, rows.size, batch_size):
                    sl = idx[b0:b0 + batch_size]
                    batch = gather(blocks, which[sl], rows[sl])
                    batch["block"] = group_ids[which[sl]]
                    batch["idx"] = sl
                    yield batch
                del batch, sl, idx
            del blocks, which, rows
