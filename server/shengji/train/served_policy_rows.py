"""Policy-head root rows from served-capture trajectory stores.

The served capture records every play decision with the admitted ballot and
the base value pass's per-candidate means (``action_values``; the raw decision
record rides in ``allocation.serving_decision``).  This producer writes them
in the chunked root-row format the joint trainer streams
(``policy_rows.PolicyRowsStream``; ``train_cwv --policy-head --policy-rows DIR
--policy-soft-targets``), so the policy head trains on the served bot's own
decisions:

* ``soft`` rows: the base pass priced at least two admitted candidates with
  finite means and the played action is one of them.  ``vals`` carries the
  means on the points temperature scale (``cwv_data.search_means_points``),
  and the trainer's target is ``softmax(vals / T)`` over the finite slots
  (``policy_prior.soft_ballot_targets``, T = ``--policy-soft-temperature``).
* ``hard_lcc`` rows: a lead on which lead confirmation replaced the base
  winner, read from the recorded ``serving_decision.lead_confirm_status ==
  "applied"`` and never inferred.  The challenger was priced on fresh
  confirmation worlds, not the base pass, so its mean is None by design and a
  softmax over the base means would give the played move zero mass.  The row
  keeps the recorded ballot (base candidates plus the challenger) with every
  ``vals`` slot NaN: the trainer's soft loss then takes its hard fallback,
  cross-entropy on the played slot, with no trainer change.
* every other play record is excluded and counted by reason (``EXCLUSION_REASONS``).
* opt-in lead transforms add an int8 ``lead_type`` array (follow, single, pair,
  tractor, throw); selected throw leads can become ``hard_played`` rows with
  all-NaN values, or hard-LCC throw rows can be dropped.

Held-out deals never enter the output: ``--exclude-seeds LO:HI`` (half-open,
on the record's ``round_seed``, which both mirrors of a deal share) and
``--exclude-deal-keys FILE`` drop a record before anything is encoded.  The
output directory must not exist and must not overlap an input store.  Shard
order is a seeded shuffle of the stores' verified shard lists and chunks are
written with fixed zip timestamps, so the same inputs and arguments give the
same bytes whatever the worker count.

A large build runs as N partitions (``--partition I/N``, each a complete
output directory of its own, on any host holding a copy of the stores), joined
by ``combine`` into one directory the trainer streams.  An interrupted
partition leaves no manifest and is rebuilt with ``--replace-incomplete``;
completed partitions are kept as they are.

    python -m shengji.train.served_policy_rows --data STORE [--data STORE ...]
        --out DIR --encoder-version 2 [--exclude-seeds LO:HI ...]
        [--exclude-deal-keys FILE] [--chunk-rows N] [--max-rows N]
        [--workers N] [--seed S] [--partition I/N] [--replace-incomplete]
        [--lead-types] [--hard-lead-types TYPE]
        [--drop-hard-lcc-lead-types TYPE]
    python -m shengji.train.served_policy_rows combine --out DIR PART [PART ...]
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import os
import random
import re
import sys
import zipfile
from collections import Counter, deque
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

from ..harvest.rebuild import state_for_record
from ..engine import combos
from ..rl.encode import CARD_INDEX, N_CARDS
from .data import ShardRef, deal_key, discover_store, iter_records
from .policy_prior import (CHUNK_SCHEMA, EXPLORE_FLAG_NAMES, NO_SEARCH_VALUES, ballot_tensors,
                           ballot_value_tensor, cards_to_idx, explore_flag_counts, explore_tag_arrays,
                           explore_tags_of, flat_input, input_dim, root_tensors)

SUMMARY_SCHEMA = "shengji-served-policy-rows-summary-v1"
PRODUCER = "shengji.train.served_policy_rows"
TARGET_SOFT, TARGET_HARD_LCC = 0, 1
TARGET_HARD_PLAYED = 3
TARGET_KINDS = {TARGET_SOFT: "soft", TARGET_HARD_LCC: "hard_lcc",
                TARGET_HARD_PLAYED: "hard_played"}
TARGET_KINDS_INV = {name: kind for kind, name in TARGET_KINDS.items()}
LEAD_FOLLOW, LEAD_SINGLE, LEAD_PAIR, LEAD_TRACTOR, LEAD_THROW = range(5)
LEAD_TYPE_NAMES = {
    LEAD_FOLLOW: "follow", LEAD_SINGLE: "single", LEAD_PAIR: "pair",
    LEAD_TRACTOR: "tractor", LEAD_THROW: "throw",
}
_LEAD_TYPE_VALUES = {name: value for value, name in LEAD_TYPE_NAMES.items()}
LCC_APPLIED = "applied"

#: Why a play record is not a row.  ``unsearched:<reason>`` carries the
#: capture's own ``allocation.reason`` for a point-mass record (a serving
#: budget fallback, a tractor-locked lead, a single candidate, ...).
EXCLUSION_REASONS = (
    "excluded_seed", "excluded_deal_key", "fewer_than_two_finite_means",
    "played_not_on_ballot", "played_unpriced_without_lcc", "lcc_record_inconsistent",
    "rebuild_failed", "turn_mismatch",
)
_ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)


class ServedPolicyRowsError(ValueError):
    """An input or argument the producer refuses."""


def _key(cards: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted(cards))


def parse_seed_interval(text: str) -> tuple[int, int]:
    """``"LO:HI"`` is the half-open ``[LO, HI)``; a bare ``"N"`` is ``[N, N + 1)``."""
    try:
        if ":" in text:
            lo_s, hi_s = text.split(":", 1)
            lo, hi = int(lo_s), int(hi_s)
        else:
            lo = int(text)
            hi = lo + 1
    except ValueError as exc:
        raise ServedPolicyRowsError(f"seed interval {text!r}: expected LO:HI or N") from exc
    if not lo < hi:
        raise ServedPolicyRowsError(f"seed interval {text!r}: LO must be below HI")
    return lo, hi


def _in_intervals(seed: int, intervals: Sequence[tuple[int, int]]) -> bool:
    return any(lo <= seed < hi for lo, hi in intervals)


def _played_slot(ballot: Sequence[Sequence[str]], action: Sequence[str]) -> int | None:
    want = _key(action)
    for i, cand in enumerate(ballot):
        if cand and _key(cand) == want:
            return i
    return None


def _normalize_lead_types(values: Sequence[str] | str, option: str) -> tuple[str, ...]:
    if isinstance(values, str):
        values = (values,)
    try:
        raw = list(values)
    except TypeError as exc:
        raise ServedPolicyRowsError(f"{option}: expected lead type names") from exc
    names: set[str] = set()
    for value in raw:
        if not isinstance(value, str):
            raise ServedPolicyRowsError(f"{option}: invalid lead type {value!r}")
        for name in value.split(","):
            if name not in _LEAD_TYPE_VALUES:
                raise ServedPolicyRowsError(
                    f"{option}: invalid lead type {name!r}; expected one of "
                    f"{', '.join(_LEAD_TYPE_VALUES)}")
            names.add(name)
    return tuple(name for name in _LEAD_TYPE_VALUES if name in names)


def _lead_type(root, action: Sequence[str]) -> int:
    """Classify the played action using the rebuilt engine state."""
    if root.trick is not None and root.trick.plays:
        return LEAD_FOLLOW
    decomposition = combos.decompose(list(action), root.ordering)
    if len(decomposition.components) != 1:
        return LEAD_THROW
    component = decomposition.components[0]
    if component.kind == "single":
        return LEAD_SINGLE
    if component.kind == "pair":
        return LEAD_PAIR
    if component.kind == "tractor":
        return LEAD_TRACTOR
    return LEAD_THROW


def _mean_at(record: Mapping[str, Any], slot: int) -> float | None:
    """The base pass's mean recorded for ballot slot ``slot``, None when unpriced."""
    values = record.get("action_values")
    if not isinstance(values, dict):
        return None
    for index, mean in zip(values.get("eligible_indices") or [], values.get("means") or []):
        if index == slot:
            if isinstance(mean, bool) or not isinstance(mean, (int, float)) or not math.isfinite(mean):
                return None
            return float(mean)
    return None


def classify(record: Mapping[str, Any]) -> tuple[str | None, str | None, list[float] | None, str | None]:
    """``(target, reason, means_raw, units)`` of one play record: ``target`` is
    ``"soft"`` or ``"hard_lcc"`` (``reason`` None), or None with the exclusion
    ``reason``.  ``means_raw`` is aligned to the raw ballot on the points
    temperature scale (NaN where unpriced; all NaN for a hard row)."""
    from .cwv_data import search_means_points, value_units
    allocation = record.get("allocation") or {}
    ballot = record.get("ballot") or []
    decision = allocation.get("serving_decision") if isinstance(allocation, dict) else None
    lcc_applied = isinstance(decision, dict) and decision.get("lead_confirm_status") == LCC_APPLIED
    if isinstance(allocation, dict) and allocation.get("searched") is False and not lcc_applied:
        return None, f"unsearched:{allocation.get('reason')}", None, None
    slot = _played_slot(ballot, record.get("action") or [])
    if lcc_applied:
        challenger = decision.get("lead_confirm_to")
        if (decision.get("lead_confirm_applied") is not True or not isinstance(challenger, list)
                or slot is None or _key(challenger) != _key(record["action"])
                or _mean_at(record, slot) is not None or not isinstance(record.get("action_values"), dict)):
            return None, "lcc_record_inconsistent", None, None
        return "hard_lcc", None, [float("nan")] * len(ballot), value_units(record)
    got = search_means_points(record)
    if got is None:
        return None, "fewer_than_two_finite_means", None, None
    if slot is None:
        return None, "played_not_on_ballot", None, None
    indices, means, units = got
    if slot not in indices:
        return None, "played_unpriced_without_lcc", None, None
    means_raw = [float("nan")] * len(ballot)
    for i, m in zip(indices, means):
        means_raw[i] = float(m)
    return "soft", None, means_raw, units


def _record_deal_key(record: Mapping[str, Any]) -> str | None:
    deck = record.get("deck")
    return deal_key(list(deck)) if isinstance(deck, list) else None


def _shard_rows(args: tuple) -> tuple[list[tuple], dict]:
    """Rows and counters of one shard, in record order."""
    path, version, intervals, excluded_keys, lead_types, hard_lead_types, drop_hard_lcc_lead_types = args
    rows: list[tuple] = []
    counts: Counter = Counter()
    lcc_status: Counter = Counter()
    excluded_seen: set[str] = set()
    shard = ShardRef(path=path, label="", sha256="", records=None, cluster=None, store="")
    for rec in iter_records(shard):
        counts["records"] += 1
        if rec.get("decision_kind") != "play":
            counts["non_play_records"] += 1
            continue
        counts["play_records"] += 1
        decision = (rec.get("allocation") or {}).get("serving_decision")
        if isinstance(decision, dict) and decision.get("lead_confirm_status") is not None:
            lcc_status[str(decision["lead_confirm_status"])] += 1
        if intervals:
            seed = rec.get("round_seed")
            if isinstance(seed, bool) or not isinstance(seed, int):
                raise ServedPolicyRowsError(
                    f"{path}: a play record has no integer round_seed; seed exclusion cannot be proved")
            if _in_intervals(seed, intervals):
                counts["excluded:excluded_seed"] += 1
                key = _record_deal_key(rec)
                if key is not None:
                    excluded_seen.add(key)
                continue
        key = _record_deal_key(rec)
        if excluded_keys and key is not None and key in excluded_keys:
            counts["excluded:excluded_deal_key"] += 1
            excluded_seen.add(key)
            continue
        target, reason, means_raw, units = classify(rec)
        if target is None:
            counts[f"excluded:{reason}"] += 1
            continue
        try:
            root = state_for_record(rec)
        except Exception:
            counts["excluded:rebuild_failed"] += 1
            continue
        seat = int(rec["seat"])
        if root.phase != "play" or root.turn != seat:
            counts["excluded:turn_mismatch"] += 1
            continue
        root_key = deal_key(list(root.deck))
        if key is not None and key != root_key:
            raise ServedPolicyRowsError(f"{path}: the record's deck and its rebuilt deal disagree")
        if excluded_keys and root_key in excluded_keys:
            counts["excluded:excluded_deal_key"] += 1
            excluded_seen.add(root_key)
            continue
        lead_type = None
        if lead_types:
            lead_type = _lead_type(root, rec["action"])
            lead_name = LEAD_TYPE_NAMES[lead_type]
            if target == "hard_lcc" and lead_name in drop_hard_lcc_lead_types:
                counts["excluded:hard_lcc_lead_type"] += 1
                continue
            if target == "soft" and lead_name in hard_lead_types:
                target = "hard_played"
                means_raw = [float("nan")] * len(raw_ballot)
        x = flat_input(root_tensors(root, seat, version), version).astype(np.float16)
        y = np.zeros(N_CARDS, np.uint8)
        for c in rec["action"]:
            y[CARD_INDEX[c]] = 1
        raw_ballot = rec.get("ballot") or []
        eflag, emargin = explore_tags_of(raw_ballot, means_raw,
                                         (rec.get("exploration") or {}).get("added") or [],
                                         production=rec.get("production_ballot"))
        meta = {"ballot": [cards_to_idx(a) for a in raw_ballot], "taken": cards_to_idx(rec["action"]),
                "deal_key": root_key, "means": means_raw, "units": units or NO_SEARCH_VALUES,
                "target": target, "explore_flag": int(eflag),
                "explore_margin": None if not math.isfinite(emargin) else float(emargin),
                "source_ref": rec.get("source_ref"), "round_seed": rec.get("round_seed")}
        if lead_type is not None:
            meta["lead_type"] = lead_type
        rows.append((x, y, meta))
        counts[f"rows:{target}"] += 1
    return rows, {"counts": dict(counts), "lcc_status": dict(lcc_status),
                  "excluded_deals": sorted(excluded_seen)}


def _ordered(ex, fn, args: Iterable, workers: int):
    """``fn`` over ``args`` in input order, at most ``2 * workers`` tasks in flight."""
    pending: deque = deque()
    it = iter(args)
    try:
        for a in it:
            pending.append(ex.submit(fn, a))
            if len(pending) >= 2 * workers:
                yield pending.popleft().result()
        while pending:
            yield pending.popleft().result()
    finally:
        for f in pending:
            f.cancel()


def save_npz_deterministic(path: Path, arrays: Mapping[str, np.ndarray]) -> str:
    """``np.savez_compressed``'s layout with fixed member timestamps (numpy
    stamps the wall clock), so equal arrays give equal bytes; returns the sha256."""
    from numpy.lib import format as npy_format
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, value in arrays.items():
            buf = io.BytesIO()
            npy_format.write_array(buf, np.asanyarray(value), allow_pickle=False)
            info = zipfile.ZipInfo(name + ".npy", date_time=_ZIP_EPOCH)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, buf.getvalue())
    with open(path, "rb") as fh:
        return hashlib.file_digest(fh, "sha256").hexdigest()


def write_chunk(out_dir: Path, index: int, X, Y, meta) -> dict:
    """One chunk in ``policy_prior``'s layout plus optional lead transforms.

    The stream ignores arrays it does not read, including the opt-in
    ``lead_type`` array.
    """
    ball, mask, tgt = ballot_tensors(meta)
    vals, has_vals = ballot_value_tensor(meta, b_max=int(ball.shape[1]))
    explore_flag, explore_margin = explore_tag_arrays(meta)
    kinds = np.asarray([TARGET_KINDS_INV[m["target"]] for m in meta], np.int8)
    arrays = {
        "X": np.stack(X).astype(np.float16), "Y": np.stack(Y).astype(np.uint8),
        "ball": ball.numpy(), "mask": mask.numpy(), "tgt": tgt.numpy(),
        "deal_key": np.asarray([m["deal_key"] for m in meta]),
        "vals": vals, "has_vals": has_vals,
        "explore_flag": explore_flag, "explore_margin": explore_margin,
        "target_kind": kinds}
    if any("lead_type" in m for m in meta):
        arrays["lead_type"] = np.asarray([m["lead_type"] for m in meta], np.int8)
    path = out_dir / f"chunk-{index:05d}.npz"
    sha = save_npz_deterministic(path, arrays)
    target_kinds = {name: int((kinds == kind).sum())
                    for kind, name in TARGET_KINDS.items()
                    if kind in (TARGET_SOFT, TARGET_HARD_LCC)
                    or int((kinds == kind).sum())}
    return {"file": path.name, "rows": len(X), "deals": len({m["deal_key"] for m in meta}),
            "rows_with_ballot_target": int((tgt >= 0).sum()),
            "rows_with_search_values": int(has_vals.sum()), "sha256": sha,
            "value_units": dict(Counter(m["units"] for m in meta)),
            "explore_flag_counts": explore_flag_counts(explore_flag),
            "target_kinds": target_kinds}


MANIFEST_TMP = "manifest.json.tmp"
_OWN_FILE = re.compile(r"chunk-\d{5}\.npz|summary\.json|manifest\.json\.tmp")
#: a combined output's own entries: symlinks to partition chunks, plus the files above
_OWN_LINK = re.compile(r"p\d{4}-chunk-\d{5}\.npz")


def _check_out(out: Path, roots: Sequence[Path], *, replace_incomplete: bool = False,
               what: str = "the input store", links: bool = False) -> Path:
    """The canonical output path, refused when it overlaps ``roots`` or already
    exists (unless ``replace_incomplete`` removes an interrupted build).  A
    symlink AT the given path is refused before anything is resolved or
    removed: recovery must never act on a link's target."""
    given = Path(out)
    if given.is_symlink():
        raise ServedPolicyRowsError(f"{given}: is a symlink; the output path must be a real directory")
    out = given.resolve()
    for root in roots:
        root = root.resolve()
        if root == out or root in out.parents or out in root.parents:
            raise ServedPolicyRowsError(f"{out}: overlaps {what} {root}")
    if out.exists() or out.is_symlink():
        if not replace_incomplete:
            raise ServedPolicyRowsError(f"{out}: already exists; a fresh directory only")
        _remove_incomplete(out, links=links)
    return out


def _manifest_state(directory: Path) -> str:
    """``"absent"``, ``"complete"`` (parses as a JSON object with chunks) or
    ``"unreadable"`` for ``directory/manifest.json``."""
    path = directory / "manifest.json"
    if not path.exists() and not path.is_symlink():
        return "absent"
    try:
        man = json.loads(path.read_text())
    except (OSError, UnicodeDecodeError, ValueError):
        return "unreadable"
    return "complete" if isinstance(man, dict) and isinstance(man.get("chunks"), list) else "unreadable"


def _remove_incomplete(out: Path, *, links: bool = False) -> None:
    """Remove an interrupted build: a real directory with no manifest holding
    only this producer's own names (``links``: also a combined output's chunk
    symlinks, which are unlinked, never followed).  A directory with a manifest
    is never rewritten, and one whose manifest cannot be read is refused for
    inspection, not deleted; anything else is refused untouched."""
    if out.is_symlink() or not out.is_dir():
        raise ServedPolicyRowsError(f"{out}: exists and is not a directory this producer wrote")
    state = _manifest_state(out)
    if state == "complete":
        raise ServedPolicyRowsError(f"{out}: is a complete output (it has a manifest); completed output "
                                    "is never rewritten")
    if state == "unreadable":
        raise ServedPolicyRowsError(f"{out}: manifest.json exists but is not a readable manifest; "
                                    "inspect it by hand, it is not removed automatically")
    entries = list(out.iterdir())

    def own(e: Path) -> bool:
        if links and _OWN_LINK.fullmatch(e.name):
            return e.is_symlink()
        return bool(_OWN_FILE.fullmatch(e.name)) and not e.is_symlink() and e.is_file()

    foreign = [e.name for e in entries if not own(e)]
    if foreign:
        raise ServedPolicyRowsError(f"{out}: holds {sorted(foreign)[:3]} that this producer does not "
                                    "write; refusing to remove it")
    for e in entries:
        e.unlink()
    out.rmdir()


def _publish_manifest(out_dir: Path, manifest: Mapping[str, Any]) -> None:
    """Write ``manifest.json`` atomically: the bytes go to an owned temporary
    name, are fsynced, and replace into place, so a reader sees either no
    manifest or the whole one.  The directory is fsynced where the platform
    allows it."""
    tmp = out_dir / MANIFEST_TMP
    with open(tmp, "x") as fh:
        fh.write(json.dumps(manifest, indent=1) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, out_dir / "manifest.json")
    try:
        fd = os.open(out_dir, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def parse_partition(text: str) -> tuple[int, int]:
    """``"I/N"``: partition ``I`` (0-based) of ``N``."""
    try:
        i_s, n_s = text.split("/", 1)
        index, count = int(i_s), int(n_s)
    except ValueError as exc:
        raise ServedPolicyRowsError(f"partition {text!r}: expected I/N") from exc
    _check_partition((index, count))
    return index, count


def _check_partition(partition: tuple[int, int]) -> tuple[int, int]:
    index, count = partition
    if type(index) is not int or type(count) is not int or count < 1 or not 0 <= index < count:
        raise ServedPolicyRowsError(f"partition {partition!r}: need 0 <= I < N")
    return index, count


def _shard_list_digest(shards: Sequence[ShardRef]) -> str:
    """Host-independent identity of an ordered shard list (labels and content
    hashes, not absolute paths), so partitions built on different hosts from
    copies of the same stores agree."""
    return hashlib.sha256("\n".join(f"{s.label}\t{s.sha256}" for s in shards).encode()).hexdigest()


def _discover_listed(corpus: str | Path):
    """A partition's view of a store: a shard store with a trajectory manifest
    is listed from the manifest's stated hashes WITHOUT reading the shard
    bytes (``_verify_shards`` then hashes only the partition's own shards);
    every other layout is ``discover_store``, which hashes what it lists.
    The listing is the same Store ``discover_store`` returns, so the whole
    build's shard-list identity is unchanged, and since every shard belongs to
    exactly one partition, a combined build has had every shard verified."""
    from .data import (TRAJECTORY_MANIFEST_SCHEMA, Store, TrainDataError, _manifest_entry, discover_store)
    root = Path(corpus).resolve()
    mpath = root / "manifest.json"
    if not ((root / "shards").is_dir() and mpath.is_file()):
        return discover_store(root)
    manifest = json.loads(mpath.read_text(encoding="utf-8"))
    if manifest.get("schema") != TRAJECTORY_MANIFEST_SCHEMA:
        return discover_store(root)
    store = Store(root=str(root), layout="shard-store")
    store.manifests.append(_manifest_entry(mpath, manifest["schema"]))
    for shard in sorted(manifest["shards"], key=lambda s: int(s["cluster"])):
        path = root / shard["path"]
        if not path.is_file():
            raise TrainDataError(f"{path}: listed by the manifest but missing")
        store.shards.append(ShardRef(path=str(path), label=shard["path"], sha256=shard["sha256"],
                                     records=int(shard["records"]), cluster=int(shard["cluster"]),
                                     store=str(root)))
    return store


def _verify_shards(shards: Sequence[ShardRef]) -> None:
    from ..harvest.common import sha256_file
    for sh in shards:
        digest = sha256_file(sh.path)
        if digest != sh.sha256:
            raise ServedPolicyRowsError(f"{sh.path}: sha256 drift against the store manifest "
                                        f"({digest[:12]} != {sh.sha256[:12]})")


def _read_deal_keys(path: str | Path) -> tuple[frozenset[str], str]:
    raw = Path(path).read_bytes()
    keys = [line.strip() for line in raw.decode("ascii").splitlines() if line.strip()]
    bad = [k for k in keys if not k.startswith("deck:")]
    if bad:
        raise ServedPolicyRowsError(f"{path}: not a deal-key list (first bad line {bad[0]!r})")
    return frozenset(keys), hashlib.sha256(raw).hexdigest()


def _digest(keys: Iterable[str]) -> str:
    return hashlib.sha256("\n".join(sorted(set(keys))).encode()).hexdigest()


def produce(out: str | Path, corpora: Sequence[str | Path], *, version: int,
            exclude_seeds: Sequence[tuple[int, int]] = (), exclude_deal_keys: str | Path | None = None,
            chunk_rows: int = 65536, max_rows: int | None = None, workers: int = 1,
            seed: int = 1, partition: tuple[int, int] | None = None,
            replace_incomplete: bool = False, lead_types: bool = False,
            hard_lead_types: Sequence[str] = (),
            drop_hard_lcc_lead_types: Sequence[str] = ()) -> dict:
    """Write the chunked root rows of ``corpora`` to the new directory ``out``
    and return the summary (also written to ``out/summary.json``).

    ``partition=(I, N)`` keeps only every N-th shard of the seeded shuffle,
    starting at I: the N partitions are disjoint, cover every shard, and each
    is a complete output of its own that ``combine`` later joins.  A partition
    may hold no rows (all its records excluded).  ``replace_incomplete``
    removes an interrupted build at ``out`` first (``_remove_incomplete``)."""
    if type(lead_types) is not bool:
        raise ServedPolicyRowsError("lead_types must be a bool")
    hard_lead_types = _normalize_lead_types(hard_lead_types, "hard_lead_types")
    drop_hard_lcc_lead_types = _normalize_lead_types(
        drop_hard_lcc_lead_types, "drop_hard_lcc_lead_types")
    lead_types = bool(lead_types or hard_lead_types or drop_hard_lcc_lead_types)
    transform = ({"lead_types": True,
                  "hard_lead_types": list(hard_lead_types),
                  "drop_hard_lcc_lead_types": list(drop_hard_lcc_lead_types)}
                 if lead_types else None)
    if partition is not None:
        partition = _check_partition(tuple(partition))
        if max_rows is not None:
            raise ServedPolicyRowsError("max_rows applies to one whole build, not to a partition")
    if type(version) is not int:
        raise ServedPolicyRowsError("the encoder version must be given explicitly as an int")
    width = input_dim(version)
    if type(chunk_rows) is not int or chunk_rows < 1:
        raise ServedPolicyRowsError("chunk_rows must be a positive integer")
    if max_rows is not None and (type(max_rows) is not int or max_rows < 1):
        raise ServedPolicyRowsError("max_rows must be a positive integer")
    if type(workers) is not int or workers < 1:
        raise ServedPolicyRowsError("workers must be a positive integer")
    if not corpora:
        raise ServedPolicyRowsError("no input store")
    intervals = [(int(lo), int(hi)) for lo, hi in exclude_seeds]
    for lo, hi in intervals:
        if not lo < hi:
            raise ServedPolicyRowsError(f"seed interval [{lo}, {hi}) is empty")
    excluded_keys: frozenset[str] = frozenset()
    keys_sha = None
    if exclude_deal_keys is not None:
        excluded_keys, keys_sha = _read_deal_keys(exclude_deal_keys)
    scoped = partition is not None
    stores = [_discover_listed(c) if scoped else discover_store(c) for c in corpora]
    shards = [sh for s in stores for sh in s.shards]
    if len({sh.path for sh in shards}) != len(shards):
        raise ServedPolicyRowsError("a shard is listed by two input stores")
    random.Random(seed).shuffle(shards)
    part_info = None
    if partition is not None:
        index, count = partition
        assigned = shards[index::count]
        if not assigned:
            raise ServedPolicyRowsError(f"partition {index}/{count} has no shard ({len(shards)} in all)")
        _verify_shards(assigned)
        part_info = {"index": index, "count": count, "all_shards": len(shards),
                     "all_shards_digest": _shard_list_digest(shards),
                     "shards": len(assigned), "shards_digest": _shard_list_digest(assigned),
                     "shard_bytes_verified": "assigned"}
        shards = assigned
    paths = [sh.path for sh in shards]
    out_dir = _check_out(Path(out), [Path(s.root) for s in stores], replace_incomplete=replace_incomplete)
    from .cwv_data import VALUE_UNITS_SCALE, cwv_encoder_identity
    identity = cwv_encoder_identity(version)
    out_dir.mkdir(parents=True)

    X: list = []; Y: list = []; meta: list = []
    chunks: list[dict] = []
    total = 0
    counts: Counter = Counter()
    lcc_status: Counter = Counter()
    excluded_seen: set[str] = set()
    deals: set[str] = set()
    args = ((p, version, tuple(intervals), excluded_keys, lead_types,
             hard_lead_types, drop_hard_lcc_lead_types) for p in paths)

    def flush(n: int) -> None:
        nonlocal total
        if n > 0:
            chunks.append(write_chunk(out_dir, len(chunks), X[:n], Y[:n], meta[:n]))
            deals.update(m["deal_key"] for m in meta[:n])
            total += n
        del X[:n], Y[:n], meta[:n]

    def consume(results) -> bool:
        """Accumulate shard results in order; True when ``max_rows`` stopped the read."""
        for rows, stats in results:
            counts.update(stats["counts"]); lcc_status.update(stats["lcc_status"])
            excluded_seen.update(stats["excluded_deals"])
            for x, y, m in rows:
                X.append(x); Y.append(y); meta.append(m)
            while len(X) >= chunk_rows and (max_rows is None or total + chunk_rows <= max_rows):
                flush(chunk_rows)
            if max_rows is not None and total + len(X) >= max_rows:
                flush(max_rows - total)
                del X[:], Y[:], meta[:]
                return True
        return False

    if workers == 1:
        stopped = consume(_shard_rows(a) for a in args)
    else:
        with ProcessPoolExecutor(workers) as ex:
            results = _ordered(ex, _shard_rows, args, workers)
            try:
                stopped = consume(results)
            finally:
                results.close()
    if X:
        flush(len(X))
    if not chunks and partition is None:
        raise ServedPolicyRowsError("no rows produced")
    if deals & (excluded_keys | excluded_seen):
        raise ServedPolicyRowsError("an excluded deal key reached the output")
    excluded = {k.split(":", 1)[1]: v for k, v in sorted(counts.items()) if k.startswith("excluded:")}
    for reason in EXCLUSION_REASONS + (("hard_lcc_lead_type",) if transform else ()):
        excluded.setdefault(reason, 0)
    target_rows = {name: sum(c["target_kinds"].get(name, 0) for c in chunks)
                   for name in ("soft", "hard_lcc")}
    if transform:
        target_rows["hard_played"] = sum(c["target_kinds"].get("hard_played", 0)
                                         for c in chunks)
    exclusions = {"seed_intervals_half_open": [[lo, hi] for lo, hi in intervals],
                  "deal_keys_file": None if exclude_deal_keys is None else str(Path(exclude_deal_keys).resolve()),
                  "deal_keys_file_sha256": keys_sha, "deal_keys_listed": len(excluded_keys),
                  "excluded_deals_seen": len(excluded_seen), "excluded_deals_digest": _digest(excluded_seen)}
    summary = {
        "schema": SUMMARY_SCHEMA, "producer": PRODUCER, "out": str(out_dir),
        "enc_version": int(version), "input_dim": width,
        "encoder_implementation_sha256": identity["implementation_sha256"],
        "stores": [{"root": s.root, "layout": s.layout, "shards": len(s.shards),
                    "manifests": [m["sha256"] for m in s.manifests], "skipped": len(s.skipped)}
                   for s in stores],
        "shard_order_seed": int(seed), "chunk_rows": int(chunk_rows), "max_rows": max_rows,
        "stopped_at_max_rows": bool(stopped),
        "records": int(counts["records"]), "play_records": int(counts["play_records"]),
        "non_play_records": int(counts["non_play_records"]),
        "rows": total, "target_rows": target_rows, "deals": len(deals),
        "fit_deals_digest": _digest(deals),
        "excluded": excluded, "excluded_rows": int(sum(excluded.values())),
        "lead_confirm_status": dict(sorted(lcc_status.items())),
        "exclusions": exclusions, "chunks": len(chunks),
        "values_scale": "points",
        "value_units": dict(sum((Counter(c["value_units"]) for c in chunks), Counter())),
    }
    if transform is not None:
        summary["lead_type_transform"] = transform
    if part_info is not None:
        # the excluded deals themselves, so ``combine`` can count their union
        summary["partition"] = dict(part_info, excluded_deals=sorted(excluded_seen))
    manifest = {"schema": CHUNK_SCHEMA, "input_dim": width, "enc_version": int(version),
                "rows": total, "chunks": chunks, "deals": len(deals),
                "split": None, "corpora": [s.root for s in stores],
                "deal_key_schema": "shengji-value-deal-key-v1",
                "value_units": summary["value_units"],
                "value_units_scale": dict(VALUE_UNITS_SCALE), "values_scale": "points",
                "explore_tags": True,
                "explore_flag_names": {str(k): v for k, v in EXPLORE_FLAG_NAMES.items()},
                "explore_flag_counts": {k: sum(c["explore_flag_counts"][k] for c in chunks)
                                        for k in map(str, sorted(EXPLORE_FLAG_NAMES))},
                "target_kind_names": {str(k): v for k, v in TARGET_KINDS.items()
                                      if k != TARGET_HARD_PLAYED or "hard_played" in target_rows},
                "producer": {k: v for k, v in summary.items() if k not in ("schema", "out")}}
    if transform is not None:
        manifest["lead_type_transform"] = transform
        manifest["lead_type_names"] = {str(k): v for k, v in LEAD_TYPE_NAMES.items()}
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=1, sort_keys=True) + "\n")
    # the manifest last: a directory without one is refused by the stream
    _publish_manifest(out_dir, manifest)
    return summary


COMBINED_SCHEMA = "shengji-served-policy-rows-combined-v1"

#: summary fields every partition of one build must agree on (host paths excluded)
_SHARED_FIELDS = ("enc_version", "input_dim", "encoder_implementation_sha256", "shard_order_seed",
                  "chunk_rows", "max_rows", "values_scale")
_SHARED_EXCLUSIONS = ("seed_intervals_half_open", "deal_keys_file_sha256", "deal_keys_listed")
_SHARED_PARTITION = ("count", "all_shards", "all_shards_digest")
_SUMMED = ("records", "play_records", "non_play_records", "rows", "excluded_rows")


def _shared_view(summary: Mapping[str, Any]) -> dict:
    return {"fields": {k: summary.get(k) for k in _SHARED_FIELDS},
            "lead_type_transform": summary.get("lead_type_transform"),
            "exclusions": {k: summary["exclusions"].get(k) for k in _SHARED_EXCLUSIONS},
            "partition": {k: summary["partition"].get(k) for k in _SHARED_PARTITION},
            "stores": [{k: s.get(k) for k in ("layout", "shards", "manifests", "skipped")}
                       for s in summary["stores"]]}


def _read_partition(part: Path) -> tuple[dict, dict]:
    """A complete partition's summary and manifest, every chunk hash-checked."""
    man_path, sum_path = part / "manifest.json", part / "summary.json"
    state = _manifest_state(part)
    if state == "absent":
        raise ServedPolicyRowsError(f"{part}: no manifest.json; an interrupted partition is rebuilt "
                                    "(--replace-incomplete), never combined")
    if state == "unreadable":
        raise ServedPolicyRowsError(f"{part}: manifest.json is not a readable manifest; inspect it by hand")
    if not sum_path.is_file():
        raise ServedPolicyRowsError(f"{part}: no summary.json")
    try:
        summary = json.loads(sum_path.read_text())
    except ValueError as exc:
        raise ServedPolicyRowsError(f"{part}: summary.json is not readable JSON") from exc
    man = json.loads(man_path.read_text())
    if (not isinstance(summary, dict) or summary.get("schema") != SUMMARY_SCHEMA
            or not isinstance(summary.get("partition"), dict)):
        raise ServedPolicyRowsError(f"{part}: not a partition of served_policy_rows (no partition block)")
    if (man.get("schema") != CHUNK_SCHEMA or man.get("rows") != summary["rows"]
            or len(man.get("chunks") or []) != summary["chunks"]
            or sum(int(c["rows"]) for c in man["chunks"]) != summary["rows"]):
        raise ServedPolicyRowsError(f"{part}: manifest and summary disagree")
    for c in man["chunks"]:
        name = c["file"]
        if Path(name).name != name or not re.fullmatch(r"chunk-\d{5}\.npz", name):
            raise ServedPolicyRowsError(f"{part}: unexpected chunk name {name!r}")
        path = part / name
        if path.is_symlink() or not path.is_file():
            raise ServedPolicyRowsError(f"{part}: chunk {name} missing")
        with open(path, "rb") as fh:
            if hashlib.file_digest(fh, "sha256").hexdigest() != c["sha256"]:
                raise ServedPolicyRowsError(f"{part}: chunk {name} SHA256 differs from the manifest")
    return summary, man


def combine(out: str | Path, parts: Sequence[str | Path], *, replace_incomplete: bool = False) -> dict:
    """Join the complete partitions ``parts`` (all N of one build, any order)
    into the new directory ``out``: a composed chunk manifest that
    ``PolicyRowsStream`` (``train_cwv --policy-rows out``) streams, whose chunks
    are symlinks to the partitions' verified chunks, and a summary whose counts
    are the partitions' sums (deals and excluded deals as unions).  Returns the
    combined summary (also ``out/summary.json``).  ``replace_incomplete``
    first removes an interrupted combine at ``out`` (no manifest; its chunk
    links are unlinked, the partitions they point at are untouched)."""
    from .cwv_data import VALUE_UNITS_SCALE
    if not parts:
        raise ServedPolicyRowsError("no partition")
    dirs = [Path(p).resolve() for p in parts]
    if len(set(dirs)) != len(dirs):
        raise ServedPolicyRowsError("a partition is listed twice")
    out_dir = _check_out(Path(out), dirs, replace_incomplete=replace_incomplete, what="the partition",
                         links=True)
    read = sorted(((d, *_read_partition(d)) for d in dirs), key=lambda t: t[1]["partition"]["index"])
    first = _shared_view(read[0][1])
    for d, s, _m in read[1:]:
        if _shared_view(s) != first:
            raise ServedPolicyRowsError(f"{d}: built with other inputs or arguments than {read[0][0]}")
    count = first["partition"]["count"]
    indices = [s["partition"]["index"] for _d, s, _m in read]
    if indices != list(range(count)):
        missing = sorted(set(range(count)) - set(indices))
        raise ServedPolicyRowsError(f"partitions {indices} of {count}: need each of 0..{count - 1} once"
                                    + (f" (missing {missing})" if missing else ""))
    if sum(s["partition"]["shards"] for _d, s, _m in read) != first["partition"]["all_shards"]:
        raise ServedPolicyRowsError("the partitions' shard counts do not add up to the build's")

    counts: Counter = Counter()
    excluded: Counter = Counter(); lcc: Counter = Counter(); units: Counter = Counter()
    targets: Counter = Counter(); flags: Counter = Counter()
    deals: set[str] = set(); excluded_deals: set[str] = set()
    chunks: list[tuple[dict, Path]] = []
    for d, s, m in read:
        for k in _SUMMED:
            counts[k] += int(s[k])
        excluded.update(s["excluded"]); lcc.update(s["lead_confirm_status"])
        units.update(s["value_units"]); targets.update(s["target_rows"])
        flags.update({k: int(v) for k, v in m["explore_flag_counts"].items()})
        excluded_deals.update(s["partition"]["excluded_deals"])
        for c in m["chunks"]:
            with np.load(d / c["file"]) as z:
                deals.update(z["deal_key"].astype(str).tolist())
            chunks.append((dict(c, file=f"p{s['partition']['index']:04d}-{c['file']}", source=str(d)),
                           d / c["file"]))
    if not chunks:
        raise ServedPolicyRowsError("no rows in any partition")
    if deals & excluded_deals:
        raise ServedPolicyRowsError("a deal excluded by one partition is a fit row of another")
    head = read[0][1]
    exclusions = {**{k: head["exclusions"][k] for k in _SHARED_EXCLUSIONS},
                  "excluded_deals_seen": len(excluded_deals), "excluded_deals_digest": _digest(excluded_deals)}
    summary = {
        "schema": COMBINED_SCHEMA, "producer": PRODUCER, "out": str(out_dir),
        **{k: head[k] for k in _SHARED_FIELDS}, "stores": head["stores"],
        "partitions": [{"index": s["partition"]["index"], "dir": str(d), "rows": s["rows"],
                        "chunks": s["chunks"], "shards": s["partition"]["shards"],
                        "shards_digest": s["partition"]["shards_digest"],
                        "manifest_sha256": hashlib.sha256((d / "manifest.json").read_bytes()).hexdigest()}
                       for d, s, _m in read],
        "partition_count": count, "all_shards": first["partition"]["all_shards"],
        "all_shards_digest": first["partition"]["all_shards_digest"],
        **{k: int(counts[k]) for k in _SUMMED},
        "target_rows": {name: int(targets[name]) for name in ("soft", "hard_lcc")},
        "deals": len(deals), "fit_deals_digest": _digest(deals),
        "excluded": dict(sorted(excluded.items())),
        "lead_confirm_status": dict(sorted(lcc.items())),
        "exclusions": exclusions, "chunks": len(chunks), "value_units": dict(units),
    }
    if head.get("lead_type_transform") is not None:
        summary["lead_type_transform"] = head["lead_type_transform"]
        summary["target_rows"]["hard_played"] = int(targets["hard_played"])
    if counts["rows"] + counts["excluded_rows"] != counts["play_records"]:
        raise ServedPolicyRowsError("the partitions' rows and exclusions do not add up to their play records")
    manifest = {"schema": CHUNK_SCHEMA, "input_dim": head["input_dim"], "enc_version": head["enc_version"],
                "rows": int(counts["rows"]), "chunks": [c for c, _t in chunks], "deals": len(deals),
                "split": None, "corpora": [s["root"] for s in head["stores"]],
                "composed_from": [{"tag": f"p{s['partition']['index']:04d}", "dir": str(d)} for d, s, _m in read],
                "deal_key_schema": "shengji-value-deal-key-v1", "value_units": dict(units),
                "value_units_scale": dict(VALUE_UNITS_SCALE), "values_scale": "points",
                "explore_tags": True,
                "explore_flag_names": {str(k): v for k, v in EXPLORE_FLAG_NAMES.items()},
                "explore_flag_counts": {k: int(flags[k]) for k in map(str, sorted(EXPLORE_FLAG_NAMES))},
                "target_kind_names": {str(k): v for k, v in TARGET_KINDS.items()
                                      if k != TARGET_HARD_PLAYED
                                      or "hard_played" in summary["target_rows"]},
                "producer": {k: v for k, v in summary.items() if k not in ("schema", "out")}}
    if head.get("lead_type_transform") is not None:
        manifest["lead_type_transform"] = head["lead_type_transform"]
        manifest["lead_type_names"] = {str(k): v for k, v in LEAD_TYPE_NAMES.items()}
    out_dir.mkdir(parents=True)
    for entry, target in chunks:
        (out_dir / entry["file"]).symlink_to(target)
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=1, sort_keys=True) + "\n")
    # the manifest last: a directory without one is refused by the stream
    _publish_manifest(out_dir, manifest)
    return summary


def build_combine_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="served_policy_rows combine",
                                description="join all N complete partitions of one build")
    p.add_argument("--out", required=True, help="the new combined directory (must not exist)")
    p.add_argument("parts", nargs="+", help="the partition output directories")
    p.add_argument("--replace-incomplete", action="store_true",
                   help="first remove an interrupted combine at --out (no manifest; links only)")
    return p


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="served_policy_rows", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data", action="append", required=True, help="a served-capture trajectory store; repeatable")
    p.add_argument("--out", required=True, help="the new output directory (must not exist)")
    p.add_argument("--encoder-version", type=int, required=True,
                   help="encoder the root rows are built at; must equal the trained checkpoint's")
    p.add_argument("--exclude-seeds", action="append", default=[], metavar="LO:HI",
                   help="drop records whose round_seed is in [LO, HI); repeatable")
    p.add_argument("--exclude-deal-keys", default=None, metavar="FILE",
                   help="drop records on these deals (one deck:<sha256> per line)")
    p.add_argument("--chunk-rows", type=int, default=65536)
    p.add_argument("--max-rows", type=int, default=None)
    p.add_argument("--workers", type=int, default=1)
    p.add_argument("--seed", type=int, default=1, help="shard-order shuffle seed")
    p.add_argument("--partition", default=None, metavar="I/N",
                   help="build only partition I (0-based) of N over the shuffled shards; join all N "
                        "with the combine subcommand")
    p.add_argument("--replace-incomplete", action="store_true",
                   help="first remove an interrupted build at --out (no manifest, only this producer's "
                        "files); a complete output is refused")
    p.add_argument("--lead-types", action="store_true",
                   help="write the engine-classified lead_type array")
    p.add_argument("--hard-lead-types", action="append", default=[], metavar="TYPE",
                   help="make matching soft rows hard_played (repeatable; enables lead types)")
    p.add_argument("--drop-hard-lcc-lead-types", action="append", default=[], metavar="TYPE",
                   help="drop matching hard_lcc rows with counted exclusions (repeatable)")
    return p


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        if argv[:1] == ["combine"]:
            c = build_combine_parser().parse_args(argv[1:])
            summary = combine(c.out, c.parts, replace_incomplete=c.replace_incomplete)
            print(json.dumps({k: v for k, v in summary.items() if k != "partitions"}, sort_keys=True))
            return 0
        a = build_parser().parse_args(argv)
        summary = produce(a.out, a.data, version=a.encoder_version,
                          exclude_seeds=[parse_seed_interval(s) for s in a.exclude_seeds],
                          exclude_deal_keys=a.exclude_deal_keys, chunk_rows=a.chunk_rows,
                          max_rows=a.max_rows, workers=a.workers, seed=a.seed,
                          partition=None if a.partition is None else parse_partition(a.partition),
                          replace_incomplete=a.replace_incomplete, lead_types=a.lead_types,
                          hard_lead_types=a.hard_lead_types,
                          drop_hard_lcc_lead_types=a.drop_hard_lcc_lead_types)
    except ServedPolicyRowsError as exc:
        print(f"served_policy_rows: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
