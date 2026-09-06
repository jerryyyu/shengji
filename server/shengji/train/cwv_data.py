"""Complete-world value (CWV) data bridge: decision records -> #214 afterstate
tensors (``rl.value_afterstate``), cached per shard, split by deal.

View
----
Every cached row is the AFTERSTATE of its record: the complete round rebuilt
by ``harvest.rebuild.state_for_record`` (every record carries the deck, so
all four hands and the burial are known), the record's engine-accepted
action applied through ``rl.value_afterstate.apply_action``, and the reached
state encoded from the ACTING seat's perspective by ``tensors_from_round`` --
exactly the binding of ``example_from_trajectory_record`` (the build
re-derives every ``reference_every``-th row through that function and
refuses on any difference).  The decision state itself is not encodable for
the first play of a round (#214's tensors require at least one public
history event), and the afterstate is what ``value_inference.score_actions``
feeds the net at play time, so the training distribution is the consumer's.

Target
------
``signed_level_category(outcome.attacker_points, root_is_attacker)``: #214's
204-class signed level, whose support is the half-integer
``teacher_v1.attacker_level_utility`` (an 80-119 takeover is +0.5 for the
attackers, 120-159 is +1.5, a 40-79 defense is +1.5 for the banker team,
...).  The record's ``outcome.signed_level_utility`` is the PT0 integer
convention (a takeover counts one level); ``pt0_level`` maps the 204-class
support onto it exactly (``sign * max(1, floor(|u|))``) and the build refuses
a row whose stored utility disagrees with its category.  The expected PT0
level of a predicted distribution is what the metrics compare with the
stratified prior and the public head, which predict that scale.

Hidden hands
------------
This bridge SEES the hidden hands by design: the world tensor carries all
four seat-relative hands and the burial (``sees_hidden_hands`` is stamped in
every cache meta, checkpoint and receipt).  The play-time consumer only ever
feeds sampled worlds.  ``world_witness`` is the inverse of the public
pipeline's privacy witness: permuting hidden cards among the non-acting
seats must CHANGE the world tensor while leaving the public tensor
byte-identical; the build runs it every ``witness_every``-th row.  The
public head's own witness (``train.data.privacy_witness``) is untouched.

Cache
-----
``<cache>/<shard sha256>.cwv[h]-<encoder sha256[:12]>.npz``: the public
tensor as float32, the world tensor as uint8 card counts (0/1/2 = 0/0.5/1),
the perspective as one byte, the 204-class target, the record's PT0 utility
and outcome points, the decision-state features the stratified prior reads
(ply, role, attacker points so far), identities (deal key, cluster,
source_ref, record and input hashes) and whether the record carries
per-candidate search means.  The ``cwvh`` flavour (``--arch seq``) adds the
public history as compact events (card counts, relative seat, trick
position, card count, points) that rebuild #214's float32 history
byte-for-byte (verified for every event at build time).  The encoder
identity hashes ``value_afterstate.py`` and its executable closure (encode,
douzero_micro, memory, cards, combos, round, rebuild, teacher_v1).  The file
is a pure function of the shard bytes, the encoder and the witness seed, so
the missing shards are built in a pool of spawned workers, byte-identical.

Splits and residency reuse ``train.data``: ``split_deals`` by the canonical
deal key (the recipe of ``value_afterstate._deal_key``) and the LRU
``Residency``; ``CwvBlockStore`` mirrors ``BlockStore``'s contract (windows
bounded by the budget, a batch sequence that is a function of the seed
alone) for these arrays.
"""

from __future__ import annotations

import hashlib
import json
import math
import multiprocessing
import os
import random
import time
import zipfile
from concurrent.futures import ProcessPoolExecutor
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Collection, Iterator, Mapping, Sequence

import numpy as np

from ..engine.cards import make_deck
from ..harvest.common import action_key, sha256_file
from ..harvest.rebuild import RebuildError, state_for_record
from ..harvest.schema import SCHEMA
from ..rl.douzero_micro import HISTORY_EVENT_DIM
from ..rl.encode import N_CARDS
from ..rl.value_afterstate import (
    AFTERSTATE_SCHEMA,
    OUTCOME_CLASSES,
    PERSPECTIVE_DIM,
    PUBLIC_DIM,
    WORLD_RECEIVERS,
    ValueAfterstateError,
    ValueAfterstateTensors,
    apply_action,
    category_signed_level,
    example_from_trajectory_record,
    signed_level_category,
    tensors_from_round,
)
from .data import (
    DEAL_KEY_SCHEMA,
    Residency,
    ShardRef,
    Store,
    TrainDataError,
    _anon_zeros,
    _read_member,
    cluster_key,
    deal_key,
    default_cache_workers,
    discover_store,
    encoder_identity as public_encoder_identity,
    first_deals,
    iter_records,
    scan_deal_keys,
    split_deals,
    split_mask,
    SplitSelector,
)

CACHE_SCHEMA = "shengji-cwv-cache-v1"
IDENTITY_SCHEMA = "shengji-cwv-encoder-identity-v1"
VIEW = ("afterstate: the record's engine-accepted action applied in the rebuilt complete "
        "round, encoded from the acting seat's perspective "
        "(rl.value_afterstate.example_from_trajectory_record)")
SEES_HIDDEN_HANDS = True
SKIP_REASONS = ("wrong_schema", "not_play", "no_outcome", "rebuild_failed", "turn_mismatch",
                "role_drift", "action_drift")
SEARCH_KEYS = ("present", "absent")
#: every N-th encoded row is re-derived through ``example_from_trajectory_record``
REFERENCE_EVERY = 100
#: every N-th encoded row runs ``world_witness``
WITNESS_EVERY = 50
WITNESS_TRIALS = 2
DECK_SIZE = len(make_deck())
HISTORY_META_DIM = 4          # relative seat, trick position, card count, points
_SHENGJI = Path(__file__).resolve().parents[1]
#: the executable closure of ``tensors_from_round`` and the bridge
CWV_SOURCE_PATHS = {
    "value_afterstate": _SHENGJI / "rl" / "value_afterstate.py",
    "encode": _SHENGJI / "rl" / "encode.py",
    "douzero_micro": _SHENGJI / "rl" / "douzero_micro.py",
    "memory": _SHENGJI / "ai" / "memory.py",
    "cards": _SHENGJI / "engine" / "cards.py",
    "combos": _SHENGJI / "engine" / "combos.py",
    "round": _SHENGJI / "engine" / "round.py",
    "rebuild": _SHENGJI / "harvest" / "rebuild.py",
    "teacher_v1": _SHENGJI / "teacher_v1.py",
}


# ---------------------------------------------------------------- identity

def cwv_encoder_identity() -> dict:
    """Stamped in every cache ``meta``, checkpoint and receipt; the cache
    key is its ``implementation_sha256`` (rehashed on every call)."""
    sources = {name: sha256_file(path) for name, path in CWV_SOURCE_PATHS.items()}
    payload = "|".join([IDENTITY_SCHEMA, AFTERSTATE_SCHEMA]
                       + [f"{name}:{digest}" for name, digest in sorted(sources.items())])
    return {
        "identity_schema": IDENTITY_SCHEMA,
        "afterstate_schema": AFTERSTATE_SCHEMA,
        "public_dim": PUBLIC_DIM,
        "world_shape": [WORLD_RECEIVERS, N_CARDS],
        "perspective_dim": PERSPECTIVE_DIM,
        "history_event_dim": HISTORY_EVENT_DIM,
        "outcome_classes": OUTCOME_CLASSES,
        "implementation_sha256": hashlib.sha256(payload.encode("ascii")).hexdigest(),
        "source_sha256s": sources,
        "public_head_encoder_sha256": public_encoder_identity()["implementation_sha256"],
    }


def encoder_cache_key() -> str:
    return cwv_encoder_identity()["implementation_sha256"][:12]


def cache_path(cache_dir: str | os.PathLike, shard_sha256: str, *, history: bool = False) -> Path:
    flavour = "cwvh" if history else "cwv"
    return Path(cache_dir) / f"{shard_sha256}.{flavour}-{encoder_cache_key()}.npz"


# ------------------------------------------------------------------ levels

def pt0_level(signed_level: float) -> float:
    """The PT0 integer utility (``harvest.rebuild.signed_level_utility``) of
    a #214 signed level: ``sign * max(1, floor(|u|))`` -- a +0.5 takeover is
    one level, +1.5 (120-159) is one level, +2.5 two, -1.5 (a 40-79
    defense) is minus one, -3.5 (zero points) minus three."""
    value = float(signed_level)
    if not math.isfinite(value) or value == 0.0:
        raise TrainDataError("PT0 level needs a finite, non-zero signed level")
    return math.copysign(max(1.0, math.floor(abs(value))), value)


LEVEL_SUPPORT = np.asarray([category_signed_level(c) for c in range(OUTCOME_CLASSES)],
                           dtype=np.float64)
PT0_SUPPORT = np.asarray([pt0_level(u) for u in LEVEL_SUPPORT], dtype=np.float64)


def target_category(attacker_points: int, root_is_attacker: bool) -> int:
    """#214's target for one outcome (``signed_level_category``)."""
    return signed_level_category(int(attacker_points), bool(root_is_attacker))


def expected_levels(probability: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """``(expected #214 signed level, expected PT0 level)`` per row (the
    expectation is the MSE-optimal point estimate)."""
    prob = np.asarray(probability, dtype=np.float64)
    return prob @ LEVEL_SUPPORT, prob @ PT0_SUPPORT


def median_pt0(probability: np.ndarray) -> np.ndarray:
    """The distribution's median PT0 level per row (the MAE-optimal point
    estimate): the support is ordered, so it is the PT0 level of the first
    category whose cumulative mass reaches one half."""
    prob = np.asarray(probability, dtype=np.float64)
    cumulative = np.cumsum(prob, axis=1)
    index = np.argmax(cumulative >= 0.5, axis=1)
    return PT0_SUPPORT[index]


# ------------------------------------------------------------------ bridge

@dataclass
class Row:
    tensors: ValueAfterstateTensors
    target: int
    deal_key: str
    input_sha256: str
    utility: float                 # the record's PT0 signed_level_utility
    attacker_points: float         # the outcome
    points_so_far: float           # attacker points at the DECISION state
    ply: int
    role_attacker: bool
    seat: int
    cluster: str
    source_ref: str
    record_sha256: str
    search_indices: list[int]      # ballot indices with a finite search mean
    search_means: list[float]
    successor: Any = None          # the afterstate Round (not stored)


def search_means(record: Mapping[str, Any]) -> tuple[list[int], list[float]] | None:
    """``(ballot indices, means)`` of the record's per-candidate search means
    (``action_values.means`` aligned with ``eligible_indices``, acting-team
    perspective, points scale), or None without at least two finite ones."""
    values = record.get("action_values")
    ballot = record.get("ballot")
    if not isinstance(values, dict) or values.get("perspective") != "acting-team" \
            or not isinstance(ballot, list) or not ballot:
        return None
    means = values.get("means")
    eligible = values.get("eligible_indices")
    if not isinstance(means, list) or not isinstance(eligible, list) \
            or len(means) != len(eligible):
        return None
    pairs = []
    for index, mean in zip(eligible, means):
        if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(ballot):
            continue
        if isinstance(mean, bool) or not isinstance(mean, (int, float)) or not math.isfinite(mean):
            continue
        pairs.append((int(index), float(mean)))
    if len(pairs) < 2:
        return None
    return [i for i, _ in pairs], [m for _, m in pairs]


def bridge_record(record: Mapping[str, Any]) -> Row:
    """Rebuild, apply the record's action and encode the afterstate (module
    docstring: View / Target).  Raises ``TrainDataError`` whose message
    starts with the skip reason."""
    if record.get("schema") != SCHEMA:
        raise TrainDataError(f"wrong_schema: {record.get('schema')!r}")
    if record.get("decision_kind") != "play":
        raise TrainDataError(f"not_play: {record.get('decision_kind')!r}")
    outcome = record.get("outcome")
    if not isinstance(outcome, dict) or isinstance(outcome.get("attacker_points"), bool) \
            or not isinstance(outcome.get("attacker_points"), int) \
            or outcome.get("signed_level_utility") is None:
        raise TrainDataError("no_outcome")
    seat = int(record["seat"])
    try:
        root = state_for_record(record)
    except (RebuildError, ValueError, KeyError, AssertionError, TypeError) as exc:
        raise TrainDataError(f"rebuild_failed: {type(exc).__name__}: {exc}") from exc
    if root.phase != "play" or root.turn != seat:
        raise TrainDataError(f"turn_mismatch: rebuilt turn {root.turn}, record seat {seat}")
    root_is_attacker = bool(root.is_attacker(seat))
    if record.get("role") != ("attacker-team" if root_is_attacker else "banker-team"):
        raise TrainDataError("role_drift: the record's role disagrees with the engine")
    try:
        successor, accepted = apply_action(root, seat, record["action"])
    except ValueAfterstateError as exc:
        raise TrainDataError(f"action_drift: {exc}") from exc
    recorded = record.get("engine_play", record["action"])
    if action_key(accepted) != action_key(recorded) or (
            action_key(accepted) != action_key(record["action"]) and "engine_play" not in record):
        raise TrainDataError("action_drift: the engine-accepted action differs from the record")
    tensors = tensors_from_round(successor, seat)
    target = signed_level_category(int(outcome["attacker_points"]), root_is_attacker)
    utility = float(outcome["signed_level_utility"])
    mapped = pt0_level(category_signed_level(target))
    if mapped != utility:
        raise TrainDataError(f"utility_mismatch: category {target} maps to PT0 {mapped} but "
                             f"the record stores {utility}")
    means = search_means(record)
    return Row(
        tensors=tensors, target=target, deal_key=deal_key(list(root.deck)),
        input_sha256=tensors.sha256(), utility=utility,
        attacker_points=float(outcome["attacker_points"]),
        points_so_far=float(root.attacker_points), ply=int(record["ply"]),
        role_attacker=root_is_attacker, seat=seat, cluster=cluster_key(record),
        source_ref=str(record["source_ref"]),
        record_sha256=str(record.get("record_sha256") or ""),
        search_indices=[] if means is None else means[0],
        search_means=[] if means is None else means[1],
        successor=successor)


def reference_check(record: Mapping[str, Any], row: Row) -> None:
    """Refuse a bridged row that differs from #214's own binding."""
    try:
        example = example_from_trajectory_record(record)
    except ValueAfterstateError as exc:
        raise TrainDataError(f"reference: example_from_trajectory_record refused the "
                             f"record: {exc}") from exc
    if example.input_sha256 != row.input_sha256 or example.target_category != row.target \
            or example.deal_key != row.deal_key:
        raise TrainDataError("reference: the bridged row differs from "
                             "example_from_trajectory_record")


def world_conservation(tensors: ValueAfterstateTensors, rnd) -> bool:
    """The world tensor plus the cards played so far account for the deck."""
    played = sum(len(play.cards) for trick in rnd.history for play in trick.plays)
    if rnd.trick is not None:
        played += sum(len(play.cards) for play in rnd.trick.plays)
    return int(round(float(tensors.world.sum()) * 2)) + played == DECK_SIZE


def world_witness(rnd, seat: int, rng: random.Random, *, trials: int = WITNESS_TRIALS,
                  encoder: Callable[[Any, int], ValueAfterstateTensors] = tensors_from_round
                  ) -> dict:
    """Permute the hidden cards among the NON-acting seats (hand sizes kept;
    the burial joins the pool unless the actor is the banker) and count the
    trials whose world tensor CHANGED (it must) and whose public tensor
    changed (it must not); a shuffle that leaves every hidden hand's
    multiset as it was is ``inconclusive``.  ``rnd`` is restored."""
    base = encoder(rnd, seat)
    others = [s for s in range(4) if s != seat]
    sizes = [len(rnd.hands[s]) for s in others]
    pool = [c for s in others for c in rnd.hands[s]]
    kitty = rnd.banker != seat and bool(rnd.buried)
    if kitty:
        pool.extend(rnd.buried)
    saved_hands = [list(h) for h in rnd.hands]
    saved_buried = list(rnd.buried) if rnd.buried else rnd.buried
    result = {"trials": 0, "world_changed": 0, "public_changed": 0, "inconclusive": 0}
    try:
        for _ in range(trials):
            rng.shuffle(pool)
            moved = False
            i = 0
            for s, n in zip(others, sizes):
                new = pool[i:i + n]
                i += n
                moved = moved or Counter(new) != Counter(saved_hands[s])
                rnd.hands[s] = list(new)
            if kitty:
                new = pool[i:]
                moved = moved or Counter(new) != Counter(saved_buried)
                rnd.buried = list(new)
            permuted = encoder(rnd, seat)
            result["trials"] += 1
            if not moved:
                result["inconclusive"] += 1
                continue
            if not np.array_equal(permuted.world, base.world):
                result["world_changed"] += 1
            if not np.array_equal(permuted.public, base.public):
                result["public_changed"] += 1
    finally:
        rnd.hands = saved_hands
        rnd.buried = saved_buried
    return result


def check_witness(result: Mapping[str, int], *, label: str = "") -> None:
    conclusive = int(result["trials"]) - int(result["inconclusive"])
    if int(result["world_changed"]) < conclusive:
        raise TrainDataError(
            f"{label}: permuting hidden cards among the non-acting seats left the world "
            "tensor unchanged; the encoding does not carry the hidden hands")
    if int(result["public_changed"]):
        raise TrainDataError(
            f"{label}: permuting hidden cards changed the PUBLIC tensor; the public head's "
            "privacy boundary is violated")


# ----------------------------------------------------------------- history

def compact_history(history: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """#214's float32 history events as ``(card counts uint8 [m, 54], meta
    uint8 [m, 4])`` -- relative seat, trick position, card count, points --
    verified to rebuild the input byte-for-byte."""
    events = np.asarray(history, dtype=np.float32)
    m = int(events.shape[0])
    cards = np.rint(events[:, :N_CARDS] * 2.0).astype(np.uint8)
    meta = np.zeros((m, HISTORY_META_DIM), dtype=np.uint8)
    offset = N_CARDS
    meta[:, 0] = events[:, offset:offset + 4].argmax(axis=1)
    meta[:, 1] = events[:, offset + 4:offset + 8].argmax(axis=1)
    counts = np.rint(events[:, offset + 8] * 25.0)
    points = np.rint(events[:, offset + 9] * 40.0)
    if m and (counts.max() > 255 or points.max() > 255):
        raise TrainDataError("history event exceeds the compact encoding's byte range")
    meta[:, 2] = counts.astype(np.uint8)
    meta[:, 3] = points.astype(np.uint8)
    rebuilt = expand_history(cards, meta)
    if rebuilt.shape != events.shape or rebuilt.tobytes() != events.tobytes():
        raise TrainDataError("compact history does not rebuild the encoder's events exactly")
    return cards, meta


def expand_history(cards: np.ndarray, meta: np.ndarray) -> np.ndarray:
    """The inverse of ``compact_history``: float32 events ``[m, 64]``."""
    cards = np.asarray(cards, dtype=np.uint8)
    meta = np.asarray(meta, dtype=np.uint8)
    m = int(cards.shape[0])
    out = np.zeros((m, HISTORY_EVENT_DIM), dtype=np.float32)
    if not m:
        return out
    out[:, :N_CARDS] = cards.astype(np.float32) * np.float32(0.5)
    rows = np.arange(m)
    out[rows, N_CARDS + meta[:, 0].astype(np.int64)] = 1.0
    out[rows, N_CARDS + 4 + meta[:, 1].astype(np.int64)] = 1.0
    out[:, N_CARDS + 8] = (meta[:, 2].astype(np.float64) / 25.0).astype(np.float32)
    out[:, N_CARDS + 9] = (meta[:, 3].astype(np.float64) / 40.0).astype(np.float32)
    return out


# ------------------------------------------------------------------- blocks

class CwvBlock:
    """One cached shard, fully decoded (numpy arrays)."""

    ARRAYS = ("public", "world", "perspective", "target", "utility", "attacker_points",
              "points_so_far", "ply", "role_attacker", "seat", "deal_key", "cluster",
              "source_ref", "record_sha256", "input_sha256", "has_search_means", "n_search")
    HISTORY_ARRAYS = ("history_cards", "history_meta", "history_offsets")
    #: per-row arrays (the history members are ragged)
    ROW_ARRAYS = ARRAYS

    def __init__(self, arrays: Mapping[str, np.ndarray], meta: dict, path: str | None = None):
        self.history = "history_offsets" in arrays
        names = self.ARRAYS + (self.HISTORY_ARRAYS if self.history else ())
        for name in names:
            setattr(self, name, arrays[name])
        self.meta = meta
        self.path = path
        self.n = int(self.public.shape[0])
        self.nbytes = int(sum(int(arrays[name].nbytes) for name in names))

    def arrays(self) -> dict[str, np.ndarray]:
        names = self.ARRAYS + (self.HISTORY_ARRAYS if self.history else ())
        return {name: getattr(self, name) for name in names}

    @property
    def history_lengths(self) -> np.ndarray:
        if not self.history:
            return np.ones(self.n, dtype=np.int64)
        return self.history_offsets[1:] - self.history_offsets[:-1]

    def subset(self, idx: np.ndarray) -> "CwvBlock":
        idx = np.asarray(idx, dtype=np.int64)
        arrays = {name: getattr(self, name)[idx] for name in self.ROW_ARRAYS}
        if self.history:
            lengths = self.history_lengths[idx]
            starts = self.history_offsets[idx]
            total = int(lengths.sum())
            src = (np.repeat(starts, lengths)
                   + (np.arange(total) - np.repeat(np.cumsum(lengths) - lengths, lengths)))
            offsets = np.zeros(len(idx) + 1, dtype=np.int64)
            offsets[1:] = np.cumsum(lengths)
            arrays["history_cards"] = self.history_cards[src]
            arrays["history_meta"] = self.history_meta[src]
            arrays["history_offsets"] = offsets
        return CwvBlock(arrays, self.meta, self.path)


def _fresh_counts() -> dict:
    return {"records": 0, "encoded": 0, "skipped": {k: 0 for k in SKIP_REASONS},
            "search_means": {k: 0 for k in SEARCH_KEYS},
            "reference_checked": 0,
            "world_witness": {"records": 0, "trials": 0, "world_changed": 0,
                              "public_changed": 0, "inconclusive": 0}}


def build_cache(shard: ShardRef, cache_dir: str | os.PathLike, *, history: bool = False,
                private: bool = False, reference_every: int = REFERENCE_EVERY,
                witness_every: int = WITNESS_EVERY, witness_seed: int = 0,
                progress: Callable[[dict], None] | None = None) -> tuple[Path, dict]:
    """Encode every usable play record of ``shard`` into its cache file.

    Every ``reference_every``-th encoded row is re-derived through
    ``example_from_trajectory_record`` and every ``witness_every``-th runs
    ``world_witness``; either disagreement refuses the whole shard and
    leaves no file.  The bytes depend on nothing but the shard, the
    encoder, the flavour and the witness seed.
    """
    reference_every = max(1, int(reference_every))
    witness_every = max(1, int(witness_every))
    counts = _fresh_counts()
    rng = random.Random(f"{witness_seed}|{shard.sha256}")
    public_rows: list[np.ndarray] = []
    world_rows: list[np.ndarray] = []
    hist_cards: list[np.ndarray] = []
    hist_meta: list[np.ndarray] = []
    hist_lengths: list[int] = []
    scalars: dict[str, list] = {k: [] for k in CwvBlock.ARRAYS if k not in ("public", "world")}
    started = time.perf_counter()
    for record in iter_records(shard):
        counts["records"] += 1
        try:
            row = bridge_record(record)
        except TrainDataError as exc:
            reason = str(exc).split(":", 1)[0]
            if reason not in SKIP_REASONS:
                raise
            counts["skipped"][reason] += 1
            continue
        index = counts["encoded"]
        if index % reference_every == 0:
            reference_check(record, row)
            counts["reference_checked"] += 1
        if index % witness_every == 0:
            result = world_witness(row.successor, row.seat, rng)
            check_witness(result, label=f"{shard.label} record {counts['records'] - 1}")
            counts["world_witness"]["records"] += 1
            for key in ("trials", "world_changed", "public_changed", "inconclusive"):
                counts["world_witness"][key] += int(result[key])
        if not world_conservation(row.tensors, row.successor):
            raise TrainDataError(f"{shard.label}: the world tensor and the played cards do "
                                 f"not account for the {DECK_SIZE}-card deck")
        world = np.rint(row.tensors.world * 2.0).astype(np.uint8)
        public_rows.append(row.tensors.public)
        world_rows.append(world)
        if history:
            cards, meta = compact_history(row.tensors.history)
            hist_cards.append(cards)
            hist_meta.append(meta)
            hist_lengths.append(int(cards.shape[0]))
        scalars["perspective"].append(1 if row.tensors.perspective[0] == 1.0 else 0)
        scalars["target"].append(row.target)
        scalars["utility"].append(row.utility)
        scalars["attacker_points"].append(row.attacker_points)
        scalars["points_so_far"].append(row.points_so_far)
        scalars["ply"].append(row.ply)
        scalars["role_attacker"].append(row.role_attacker)
        scalars["seat"].append(row.seat)
        scalars["deal_key"].append(row.deal_key)
        scalars["cluster"].append(row.cluster)
        scalars["source_ref"].append(row.source_ref)
        scalars["record_sha256"].append(row.record_sha256)
        scalars["input_sha256"].append(row.input_sha256)
        scalars["has_search_means"].append(bool(row.search_means))
        scalars["n_search"].append(len(row.search_means))
        counts["search_means"]["present" if row.search_means else "absent"] += 1
        counts["encoded"] += 1
        if progress and counts["encoded"] % 5000 == 0:
            progress({"label": shard.label, "records": counts["records"],
                      "encoded": counts["encoded"],
                      "secs": round(time.perf_counter() - started, 1)})
    n = counts["encoded"]
    arrays = {
        "public": (np.stack(public_rows) if n else np.zeros((0, PUBLIC_DIM), np.float32)),
        "world": (np.stack(world_rows) if n
                  else np.zeros((0, WORLD_RECEIVERS, N_CARDS), np.uint8)),
        "perspective": np.asarray(scalars["perspective"], dtype=np.uint8),
        "target": np.asarray(scalars["target"], dtype=np.int16),
        "utility": np.asarray(scalars["utility"], dtype=np.float32),
        "attacker_points": np.asarray(scalars["attacker_points"], dtype=np.float32),
        "points_so_far": np.asarray(scalars["points_so_far"], dtype=np.float32),
        "ply": np.asarray(scalars["ply"], dtype=np.int16),
        "role_attacker": np.asarray(scalars["role_attacker"], dtype=bool),
        "seat": np.asarray(scalars["seat"], dtype=np.int8),
        "deal_key": np.asarray(scalars["deal_key"], dtype=str),
        "cluster": np.asarray(scalars["cluster"], dtype=str),
        "source_ref": np.asarray(scalars["source_ref"], dtype=str),
        "record_sha256": np.asarray(scalars["record_sha256"], dtype="S64"),
        "input_sha256": np.asarray(scalars["input_sha256"], dtype="S64"),
        "has_search_means": np.asarray(scalars["has_search_means"], dtype=bool),
        "n_search": np.asarray(scalars["n_search"], dtype=np.int16),
    }
    if history:
        offsets = np.zeros(n + 1, dtype=np.int64)
        if n:
            offsets[1:] = np.cumsum(np.asarray(hist_lengths, dtype=np.int64))
        arrays["history_cards"] = (np.concatenate(hist_cards) if n
                                   else np.zeros((0, N_CARDS), np.uint8))
        arrays["history_meta"] = (np.concatenate(hist_meta) if n
                                  else np.zeros((0, HISTORY_META_DIM), np.uint8))
        arrays["history_offsets"] = offsets
    nbytes = int(sum(int(a.nbytes) for a in arrays.values()))
    meta = {
        "schema": CACHE_SCHEMA,
        "encoder": cwv_encoder_identity(),
        "shard": {"label": shard.label, "sha256": shard.sha256, "records": shard.records,
                  "cluster": shard.cluster, "store": shard.store},
        "counts": counts,
        "history": bool(history),
        "witness_seed": int(witness_seed),
        "witness_every": witness_every,
        "reference_every": reference_every,
        "deal_key_schema": DEAL_KEY_SCHEMA,
        "deals": int(len(set(scalars["deal_key"]))),
        "nbytes": nbytes,
        "sees_hidden_hands": SEES_HIDDEN_HANDS,
        "view": VIEW,
    }
    path = cache_path(cache_dir, shard.sha256, history=history)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    with open(tmp, "wb") as fh:
        if private:
            os.fchmod(fh.fileno(), 0o600)
        np.savez_compressed(fh, meta=np.asarray(json.dumps(meta, sort_keys=True)), **arrays)
    os.chmod(tmp, 0o600 if private else 0o644)
    os.replace(tmp, path)
    return path, counts


def read_meta(path: str | os.PathLike) -> dict:
    with np.load(path, allow_pickle=False) as npz:
        return json.loads(str(npz["meta"]))


def check_meta(meta: Mapping[str, Any], *, path: str | os.PathLike,
               shard_sha256: str | None = None, history: bool | None = None) -> dict:
    """Refuse a cache of another schema / encoder / shard / flavour."""
    if meta.get("schema") != CACHE_SCHEMA:
        raise TrainDataError(f"{path}: cache schema {meta.get('schema')!r}")
    enc = meta.get("encoder") or {}
    if enc.get("implementation_sha256") != cwv_encoder_identity()["implementation_sha256"]:
        raise TrainDataError(f"{path}: cache built by another encoder")
    if shard_sha256 is not None and meta["shard"]["sha256"] != shard_sha256:
        raise TrainDataError(f"{path}: cache derived from another shard")
    if history is not None and bool(meta.get("history")) != bool(history):
        raise TrainDataError(f"{path}: cache flavour (history={meta.get('history')}) differs")
    if meta.get("sees_hidden_hands") is not True:
        raise TrainDataError(f"{path}: cache does not declare sees_hidden_hands")
    return dict(meta)


def load_block(path: str | os.PathLike, *, shard_sha256: str | None = None,
               history: bool | None = None) -> CwvBlock:
    meta = check_meta(read_meta(path), path=path, shard_sha256=shard_sha256, history=history)
    names = CwvBlock.ARRAYS + (CwvBlock.HISTORY_ARRAYS if meta.get("history") else ())
    with zipfile.ZipFile(path) as zf:
        arrays = {name: _read_member(zf, name) for name in names}
    return CwvBlock(arrays, meta, str(path))


def decode_arrays(task: tuple[str, str | None, bool | None]
                  ) -> tuple[dict[str, np.ndarray], dict]:
    """Decode one cached shard to ``(arrays, meta)`` in a worker process.

    The hash and flavour check runs HERE, in the child, so a parallel decode
    is as fail-closed as ``load_block``; the parent only wraps the result.
    Module level and argument-picklable so a process pool can call it.
    """
    path, shard_sha256, history = task
    meta = check_meta(read_meta(path), path=path, shard_sha256=shard_sha256,
                      history=history)
    names = CwvBlock.ARRAYS + (CwvBlock.HISTORY_ARRAYS if meta.get("history") else ())
    with zipfile.ZipFile(path) as zf:
        arrays = {name: _read_member(zf, name) for name in names}
    return arrays, meta


def _valid_meta(path: Path, shard_sha256: str, history: bool) -> dict | None:
    if not Path(path).is_file():
        return None
    try:
        return check_meta(read_meta(path), path=path, shard_sha256=shard_sha256,
                          history=history)
    except (TrainDataError, OSError, ValueError, KeyError):
        return None


def _build_cache_task(task: tuple) -> dict:
    shard, cache_dir, history, private, witness_seed = task
    started = time.perf_counter()
    _path, counts = build_cache(shard, cache_dir, history=history, private=private,
                                witness_seed=witness_seed)
    return {"sha256": shard.sha256, "label": shard.label, "records": counts["records"],
            "encoded": counts["encoded"], "secs": round(time.perf_counter() - started, 3)}


def build_caches(jobs: Sequence[tuple[ShardRef, bool]], cache_dir: str | os.PathLike, *,
                 history: bool = False, witness_seed: int = 0, workers: int | None = None,
                 progress: Callable[[str], None] | None = None) -> list[dict]:
    """Build the caches of ``jobs`` (``(shard, private)`` pairs), ``workers``
    at a time in spawned processes (one shard per task); byte-identical to
    the in-process build."""
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
            _path, counts = build_cache(shard, cache_dir, history=history, private=private,
                                        witness_seed=witness_seed)
            results.append({"sha256": shard.sha256, "label": shard.label,
                            "records": counts["records"], "encoded": counts["encoded"],
                            "secs": round(time.perf_counter() - started, 3)})
            say(f"cwv cache {shard.label}: built encoded={counts['encoded']} "
                f"secs={results[-1]['secs']}")
        return results
    tasks = [(shard, str(cache_dir), bool(history), bool(private), int(witness_seed))
             for shard, private in jobs]
    say(f"cwv cache: building {len(tasks)} shard(s) with {min(workers, len(tasks))} workers")
    ctx = multiprocessing.get_context("spawn")
    with ctx.Pool(processes=min(workers, len(tasks))) as pool:
        for result in pool.imap_unordered(_build_cache_task, tasks):
            results.append(result)
            if len(results) % 100 == 0 or len(results) == len(tasks):
                say(f"cwv cache: {len(results)}/{len(tasks)} shards built "
                    f"(last {result['label']} encoded={result['encoded']} "
                    f"secs={result['secs']})")
    return results


def ensure_caches(shards: Sequence[tuple[ShardRef, bool]], cache_dir: str | os.PathLike, *,
                  history: bool = False, witness_seed: int = 0, workers: int | None = None,
                  progress: Callable[[str], None] | None = None) -> list[tuple[dict, bool]]:
    """``[(meta, rebuilt), ...]`` in the order of ``shards``."""
    metas = [_valid_meta(cache_path(cache_dir, s.sha256, history=history), s.sha256, history)
             for s, _p in shards]
    pending = [(s, p) for (s, p), m in zip(shards, metas) if m is None]
    if pending:
        build_caches(pending, cache_dir, history=history, witness_seed=witness_seed,
                     workers=workers, progress=progress)
    out: list[tuple[dict, bool]] = []
    for (shard, _private), meta in zip(shards, metas):
        if meta is None:
            path = cache_path(cache_dir, shard.sha256, history=history)
            meta = check_meta(read_meta(path), path=path, shard_sha256=shard.sha256,
                              history=history)
            out.append((meta, True))
        else:
            out.append((meta, False))
    return out


# ------------------------------------------------------------------- store

class CwvBlockStore:
    """The cached blocks of one run over a shared ``Residency`` (the
    RESIDENCY contract of ``train.data``); ``keep`` filters an entry to a
    set of deal keys (a filtered entry is decoded and then subset).
    Construction scans each entry's ``deal_key`` column only."""

    def __init__(self, entries: Sequence[tuple[ShardRef, str]], *,
                 residency: Residency | None = None, resident_bytes: int | None = None,
                 keep: Sequence[Collection[str] | None] | None = None,
                 history: bool = False):
        self.entries = [(shard, str(path)) for shard, path in entries]
        self.residency = residency if residency is not None else Residency(resident_bytes)
        keep_list = list(keep) if keep is not None else [None] * len(self.entries)
        if len(keep_list) != len(self.entries):
            raise TrainDataError("keep must have one entry per shard")
        self.keep = [None if k is None else frozenset(str(x) for x in k) for k in keep_list]
        self.history = bool(history)
        self.id = ("cwv", id(self))
        self.metas = [check_meta(read_meta(path), path=path, shard_sha256=shard.sha256,
                                 history=self.history)
                      for shard, path in self.entries]
        self._keys: list[np.ndarray] = []
        self.keep_idx: list[np.ndarray | None] = []
        self._rows: list[int] = []
        self.sizes: list[int] = []
        for (_shard, path), meta, kept in zip(self.entries, self.metas, self.keep):
            keys, keep_idx, rows = scan_deal_keys(path, keep=kept)
            self._keys.append(keys)
            self.keep_idx.append(keep_idx)
            self._rows.append(int(rows))
            self.sizes.append(int(meta.get("nbytes") or 0))

    def __len__(self) -> int:
        return len(self.entries)

    @property
    def nbytes(self) -> int:
        return int(sum(self.sizes))

    def _key(self, i: int) -> tuple:
        return (self.id, i)

    #: shards dispatched to a decode pool since construction; a parallel
    #: run that never submits is a serial run, so tests assert on this.
    decode_submitted = 0

    def decode_task(self, i: int) -> tuple[str, str | None, bool | None]:
        """The picklable argument ``decode_arrays`` needs for shard ``i``."""
        shard, path = self.entries[i]
        return (str(path), shard.sha256, self.history)

    def is_resident(self, i: int) -> bool:
        return self.residency.get(self._key(i)) is not None

    def block(self, i: int, *, pinned: Collection[int] = (),
              decoded: tuple[dict, dict] | None = None) -> CwvBlock:
        key = self._key(i)
        block = self.residency.get(key)
        if block is not None:
            return block
        shard, path = self.entries[i]
        pins = {self._key(j) for j in pinned}
        self.residency.make_room(self.sizes[i], label=shard.label, pinned=pins)
        if decoded is None:
            block = load_block(path, shard_sha256=shard.sha256, history=self.history)
        else:
            arrays, meta = decoded
            block = CwvBlock(arrays, meta, str(path))
        if self.keep_idx[i] is not None:
            block = block.subset(self.keep_idx[i])
        self.residency.admit(key, block, label=shard.label, pinned=pins)
        return block

    def rows(self) -> list[int]:
        return list(self._rows)

    def keys(self) -> list[str]:
        keys: set[str] = set()
        for part in self._keys:
            keys.update(part.tolist())
        return sorted(keys)

    def keys_of(self, i: int) -> list[str]:
        return self._keys[i].tolist()

    def iter_blocks(self, *, skip: Callable[[list[str]], bool] | None = None
                    ) -> Iterator[CwvBlock]:
        """Every block, or only those ``skip`` does not reject.

        ``skip`` is asked about a shard's recorded deal keys (``keys_of``),
        which are known without decoding it. A split is assigned by deal and
        a shard holds one deal, so an evaluation over one part can decline
        roughly nine shards in ten before paying to decode them.
        """
        for i in range(len(self.entries)):
            if skip is not None and skip(self.keys_of(i)):
                continue
            yield self.block(i)

    def windows(self, order: Sequence[int], window: int) -> list[list[int]]:
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
                    f"residency budget of {budget}; raise --resident-bytes")
            if cur and (len(cur) >= max(1, int(window))
                        or (budget is not None and cur_bytes + size > budget)):
                groups.append(cur)
                cur, cur_bytes = [], 0
            cur.append(i)
            cur_bytes += size
        if cur:
            groups.append(cur)
        return groups

    def iter_batches(self, mask_fn: Callable[[CwvBlock], np.ndarray], batch_size: int, *,
                     rng: np.random.Generator | None = None, window: int = 64,
                     decode_workers: int = 0
                     ) -> Iterator[dict[str, np.ndarray]]:
        """Batches over the rows ``mask_fn`` selects, gathered from the
        resident blocks of each window; the batch sequence is a function of
        ``rng`` alone."""
        order = np.arange(len(self.entries))
        if rng is not None:
            rng.shuffle(order)
        batch_size = max(1, int(batch_size))
        groups = self.windows(order, window)
        pool = (ProcessPoolExecutor(max_workers=int(decode_workers))
                if int(decode_workers) > 0 and len(groups) > 1 else None)
        # Decode the window's shards concurrently and wait for them. Lookahead
        # was tried first and bought nothing: it can only hide decode behind the
        # consumer, and the consumer is far cheaper than the decode. The batch
        # sequence stays a function of rng alone either way, and the in-flight
        # payload is bounded by the window at ~0.4 MB a shard.
        def submit(group):
            """Dispatch the window's non-resident shards, after making room.

            The serial path makes room BEFORE it decodes, so live decoded
            bytes never exceed the residency budget. A pool receives its
            payloads before anything is admitted, so room must be made for
            the WHOLE dispatched set up front or the budget is exceeded by
            the amount in flight (Codex, review of #279).

            The staging bound is therefore explicit: the non-resident bytes
            of one window. When those do not fit the budget at all there is
            nothing to reserve against, so the window decodes serially
            rather than silently shrinking the window, which would change
            the batch order.
            """
            if pool is None:
                return {}
            todo = [i for i in group if not self.is_resident(i)]
            if not todo:
                return {}
            need = sum(int(self.sizes[i]) for i in todo)
            budget = self.residency.budget
            if budget is not None and need > budget:
                return {}
            self.residency.make_room(need, label="parallel decode staging",
                                     pinned={self._key(i) for i in group})
            self.decode_submitted += len(todo)
            return {i: pool.submit(decode_arrays, self.decode_task(i)) for i in todo}
        try:
            for group in groups:
                pending = submit(group)
                blocks = [self.block(i, pinned=group,
                                     decoded=(pending.pop(i).result() if i in pending else None))
                          for i in group]
                which_parts: list[np.ndarray] = []
                row_parts: list[np.ndarray] = []
                for j, block in enumerate(blocks):
                    sel = np.flatnonzero(mask_fn(block))
                    which_parts.append(np.full(sel.size, j, dtype=np.int64))
                    row_parts.append(sel.astype(np.int64))
                which = np.concatenate(which_parts) if which_parts else np.zeros(0, np.int64)
                rows = np.concatenate(row_parts) if row_parts else np.zeros(0, np.int64)
                if rows.size:
                    idx = np.arange(rows.size)
                    if rng is not None:
                        rng.shuffle(idx)
                    for b0 in range(0, rows.size, batch_size):
                        sl = idx[b0:b0 + batch_size]
                        yield gather(blocks, which[sl], rows[sl])
                del blocks, which, rows
        finally:
            if pool is not None:
                pool.shutdown(cancel_futures=True)


_SCALAR_DTYPES = {"perspective": np.uint8, "target": np.int64, "utility": np.float32,
                  "attacker_points": np.float32, "points_so_far": np.float32,
                  "ply": np.int32, "role_attacker": bool, "seat": np.int8}
_STRING_COLUMNS = ("deal_key", "source_ref", "input_sha256")


def gather(blocks: Sequence[CwvBlock], which: np.ndarray, rows: np.ndarray
           ) -> dict[str, np.ndarray]:
    """Rows ``rows[j]`` of ``blocks[which[j]]`` as one batch (the wide arrays
    over anonymous mmaps); with history blocks the events come padded as
    float32 ``history`` ``[b, L, 64]`` plus a boolean ``history_mask``."""
    which = np.asarray(which, dtype=np.int64)
    rows = np.asarray(rows, dtype=np.int64)
    b = len(rows)
    out: dict[str, np.ndarray] = {
        "public": _anon_zeros((b, PUBLIC_DIM), np.float32),
        "world": _anon_zeros((b, WORLD_RECEIVERS, N_CARDS), np.uint8),
    }
    for name, dtype in _SCALAR_DTYPES.items():
        out[name] = np.empty(b, dtype=dtype)
    strings: dict[str, list] = {name: [None] * b for name in _STRING_COLUMNS}
    history = bool(blocks) and all(block.history for block in blocks)
    parts = []
    lengths = np.ones(b, dtype=np.int64)
    for j in np.unique(which):
        pos = np.flatnonzero(which == j)
        sel = rows[pos]
        block = blocks[j]
        out["public"][pos] = block.public[sel]
        out["world"][pos] = block.world[sel]
        for name in _SCALAR_DTYPES:
            out[name][pos] = getattr(block, name)[sel]
        for name in _STRING_COLUMNS:
            column = getattr(block, name)[sel]
            for p, value in zip(pos.tolist(), column.tolist()):
                strings[name][p] = value
        if history:
            lengths[pos] = block.history_lengths[sel]
        parts.append((block, pos, sel))
    for name in _STRING_COLUMNS:
        out[name] = np.asarray(strings[name], dtype=str)
    if history:
        length = max(int(lengths.max()) if b else 1, 1)
        events = _anon_zeros((b, length, HISTORY_EVENT_DIM), np.float32)
        mask = np.zeros((b, length), dtype=bool)
        for block, pos, sel in parts:
            w = lengths[pos]
            total = int(w.sum())
            if not total:
                continue
            rr = np.repeat(pos, w)
            cols = np.arange(total) - np.repeat(np.cumsum(w) - w, w)
            src = np.repeat(block.history_offsets[sel], w) + cols
            events[rr, cols] = expand_history(block.history_cards[src], block.history_meta[src])
            mask[rr, cols] = True
        out["history"] = events
        out["history_mask"] = mask
    out["lengths"] = lengths
    out["block"] = which
    out["row"] = rows
    return out


def collate(block: CwvBlock, idx: np.ndarray) -> dict[str, np.ndarray]:
    idx = np.asarray(idx, dtype=np.int64)
    return gather([block], np.zeros(len(idx), dtype=np.int64), idx)


def tensors_of(batch: Mapping[str, np.ndarray], device) -> dict:
    """The #214 batch tensors of a gathered batch: ``public`` float32,
    ``world`` float32 (counts / 2), ``perspective`` one-hot, ``history`` /
    ``history_mask`` (a single all-zero event per row when the batch carries
    none: the mlp ignores it, the batch contract still holds), plus the
    targets."""
    import torch

    b = int(batch["public"].shape[0])
    perspective = np.zeros((b, PERSPECTIVE_DIM), dtype=np.float32)
    attacker = batch["perspective"].astype(bool)
    perspective[attacker, 0] = 1.0
    perspective[~attacker, 1] = 1.0
    if "history" in batch:
        history = np.ascontiguousarray(batch["history"])
        mask = np.ascontiguousarray(batch["history_mask"])
    else:
        history = np.zeros((b, 1, HISTORY_EVENT_DIM), dtype=np.float32)
        mask = np.ones((b, 1), dtype=bool)
    return {
        "public": torch.from_numpy(np.ascontiguousarray(batch["public"])).to(device),
        "world": (torch.from_numpy(np.ascontiguousarray(batch["world"])).to(device)
                  .to(torch.float32) * 0.5),
        "perspective": torch.from_numpy(perspective).to(device),
        "history": torch.from_numpy(history).to(device),
        "history_mask": torch.from_numpy(mask).to(device),
        "target": torch.from_numpy(np.ascontiguousarray(batch["target"])).to(device),
        "attacker_points": torch.from_numpy(
            np.ascontiguousarray(batch["attacker_points"])).to(device),
    }


def tensors_rows(batch: Mapping[str, np.ndarray]) -> list[ValueAfterstateTensors]:
    """The rows of a gathered HISTORY batch as #214 tensor objects (validated)."""
    if "history" not in batch:
        raise TrainDataError("tensor rows need a history batch (the cwvh cache flavour)")
    rows = []
    for i in range(int(batch["public"].shape[0])):
        n = int(batch["lengths"][i])
        attacker = bool(batch["perspective"][i])
        tensors = ValueAfterstateTensors(
            public=np.asarray(batch["public"][i], dtype=np.float32),
            history=np.asarray(batch["history"][i, :n], dtype=np.float32),
            world=np.asarray(batch["world"][i], dtype=np.float32) * np.float32(0.5),
            perspective=np.asarray([float(attacker), float(not attacker)], dtype=np.float32))
        tensors.validate()
        rows.append(tensors)
    return rows


# ------------------------------------------------------------------ splits

def assert_split_by_deal(blocks: Sequence[CwvBlock],
                         assignment_fn: Callable[[CwvBlock], np.ndarray]) -> dict[str, int]:
    """Refuse a row assignment that puts one deal in two parts; returns the
    number of deals per part.  ``assignment_fn`` maps a block to one part
    label per row (``train`` / ``val`` / ``test``)."""
    seen: dict[str, str] = {}
    for block in blocks:
        parts = np.asarray(assignment_fn(block), dtype=str)
        if parts.shape != (block.n,):
            raise TrainDataError("assignment must label every row of the block")
        for key, part in zip(block.deal_key.tolist(), parts.tolist()):
            previous = seen.setdefault(key, part)
            if previous != part:
                raise TrainDataError(f"deal {key[:20]}... is split across {previous} and "
                                     f"{part}: a deal must never be split")
    counts = Counter(seen.values())
    return {part: int(counts.get(part, 0)) for part in ("train", "val", "test")}


def deal_assignment(assignment: Mapping[str, str]) -> Callable[[CwvBlock], np.ndarray]:
    """Per-row part labels from a deal-key assignment (``split_deals``)."""
    def label(block: CwvBlock) -> np.ndarray:
        return np.asarray([assignment[key] for key in block.deal_key.tolist()], dtype=str)
    return label


# ---------------------------------------------------------------- prepare

@dataclass
class Prepared:
    stores: list[Store]
    block_store: CwvBlockStore
    counts: dict
    cache_files: list[dict] = field(default_factory=list)


def _merge_counts(total: dict, counts: Mapping) -> None:
    for key, value in counts.items():
        if isinstance(value, Mapping):
            total.setdefault(key, {})
            _merge_counts(total[key], value)
        elif isinstance(value, str):
            total.setdefault(key, value)
        else:
            total[key] = total.get(key, 0) + value


def prepare_stores(paths: Sequence[str], cache_dir: Path, *, limit_clusters: int | None,
                   history: bool, witness_seed: int,
                   progress: Callable[[str], None] | None = None,
                   cache_workers: int | None = None, residency: Residency | None = None,
                   resident_bytes: int | None = None) -> Prepared:
    """Discover, verify, encode (the missing shard caches ``cache_workers``
    at a time) and index every store into one ``CwvBlockStore``."""
    stores = [discover_store(path, limit_clusters=limit_clusters) for path in paths]
    jobs = [(shard, store.private) for store in stores for shard in store.shards]
    if not jobs:
        raise TrainDataError("no shard to train on")
    built = ensure_caches(jobs, cache_dir, history=history, witness_seed=witness_seed,
                          workers=cache_workers, progress=progress)
    entries: list[tuple[ShardRef, str]] = []
    keep: list = []
    counts: dict = {"shards": 0, "cache_rebuilt": 0, "cache_reused": 0}
    cache_files: list[dict] = []
    built_iter = iter(built)
    for store in stores:
        first = len(entries)
        for shard in store.shards:
            meta, rebuilt = next(built_iter)
            counts["shards"] += 1
            counts["cache_rebuilt" if rebuilt else "cache_reused"] += 1
            _merge_counts(counts, {"records": meta["counts"]})
            path = str(cache_path(cache_dir, shard.sha256, history=history))
            cache_files.append({"label": shard.label, "shard_sha256": shard.sha256,
                                "cache": path, "records": int(meta["counts"]["encoded"]),
                                "nbytes": int(meta["nbytes"]), "history": bool(history),
                                "rebuilt": rebuilt})
            entries.append((shard, path))
            keep.append(None)
        if limit_clusters is not None and store.layout != "shard-store":
            kept: dict[str, None] = {}
            for _shard, path in entries[first:]:
                for key in first_deals(path, int(limit_clusters)):
                    if len(kept) < int(limit_clusters):
                        kept.setdefault(key, None)
            for i in range(first, len(entries)):
                keep[i] = set(kept)
    block_store = CwvBlockStore(entries, residency=residency, resident_bytes=resident_bytes,
                                keep=keep, history=history)
    rows = block_store.rows()
    counts["records_total"] = int(sum(rows))
    counts["deals_total"] = len(block_store.keys())
    counts["decoded_bytes"] = int(block_store.nbytes)
    return Prepared(stores=stores, block_store=block_store, counts=counts,
                    cache_files=cache_files)


__all__ = [
    "CACHE_SCHEMA", "VIEW", "SEES_HIDDEN_HANDS", "CwvBlock", "CwvBlockStore", "Prepared",
    "Row", "assert_split_by_deal", "bridge_record", "build_cache", "cache_path",
    "check_witness", "collate", "compact_history", "cwv_encoder_identity", "deal_assignment",
    "ensure_caches", "expand_history", "expected_levels", "gather", "load_block",
    "prepare_stores", "pt0_level", "read_meta", "reference_check", "search_means",
    "split_deals", "split_mask", "SplitSelector", "target_category", "tensors_of", "tensors_rows",
    "world_conservation", "world_witness", "LEVEL_SUPPORT", "PT0_SUPPORT",
]
