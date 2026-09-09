#!/usr/bin/env python3
"""Import a bounded, train-only CWV decision diagnostic panel.

The importer is deliberately a source reader, not a scorer.  It chooses one
reconstructible play state per dealt deck from an immutable trajectory store;
held-out rows are counted for the census but are never rebuilt.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Mapping

from shengji.harvest import legal, rebuild
from shengji.harvest.common import sha256_file
from shengji.harvest.schema import canonical_json, record_sha256
from shengji.luna.game import _state_snapshot
from shengji.train import data


PANEL_SCHEMA = "cwv-horizon-panel-v1"
SCOPE = "train-only diagnostic; not heldout/strength"
_DEAL_RE = re.compile(r"^deck:[0-9a-f]{64}$")


class PanelError(ValueError):
    """The requested panel cannot be constructed without guessing."""


def _publish_panel(path: Path, value: Mapping[str, Any]) -> None:
    """Use the established publisher without importing optional torch eagerly."""
    try:
        from shengji.train.search_screen import _publish
    except ModuleNotFoundError as exc:
        if exc.name != "torch":
            raise
        # The panel itself is torch-free.  Keep the same atomic replacement
        # contract when this lightweight importer runs without torch.
        raw = json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"
        fd, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp",
                                    dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(raw)
            os.replace(name, path)
        finally:
            if os.path.exists(name):
                os.unlink(name)
    else:
        _publish(path, value)


# Kept as a small seam for callers/tests that replace the established atomic
# publisher; normal execution still resolves ``search_screen._publish`` above.
_publish = _publish_panel


def _digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("ascii")).hexdigest()


def _assignment(value: Mapping[str, Any] | str | Path) -> tuple[dict[str, str], str]:
    """Load the explicit ``deck:<sha> -> train|val|test`` assignment."""
    if isinstance(value, (str, Path)):
        path = Path(value)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise PanelError(f"assignment unreadable: {path}: {exc}") from exc
    else:
        raw = value
    if not isinstance(raw, Mapping):
        raise PanelError("assignment must be a JSON object")
    mapping = raw.get("assignment") if "assignment" in raw else raw
    if not isinstance(mapping, Mapping) or not mapping:
        raise PanelError("assignment must contain a non-empty mapping")
    out: dict[str, str] = {}
    for key, split in mapping.items():
        if not isinstance(key, str) or not _DEAL_RE.fullmatch(key):
            raise PanelError(f"invalid assignment deal key: {key!r}")
        if split not in ("train", "val", "test"):
            raise PanelError(f"invalid assignment split for {key}: {split!r}")
        if key in out:
            raise PanelError(f"duplicate assignment deal key: {key}")
        out[key] = str(split)
    # Hash the semantic mapping, so formatting changes do not change identity.
    return out, _digest({"assignment": dict(sorted(out.items()))})


def _record_deal_key(record: Mapping[str, Any]) -> str:
    deck = record.get("deck")
    if deck is None:
        seed = record.get("round_seed")
        setup = record.get("setup")
        if seed is None or not isinstance(setup, Mapping):
            raise PanelError("record has no dealt deck or reconstructible round_seed")
        try:
            deck = rebuild.deck_from_seed(setup["trump_rank"], setup["banker"], seed)
        except Exception as exc:  # the source is malformed, not a candidate
            raise PanelError(f"cannot derive dealt deck: {exc}") from exc
    try:
        return data.deal_key(list(deck))
    except Exception as exc:
        raise PanelError(f"invalid dealt deck: {exc}") from exc


def _priority(seed: int, deal_key: str, source_ref: str, seat: int,
              prefix_length: int) -> str:
    # Keep the exact identity inputs visible and exclude action, labels,
    # outcomes, model metrics, and the mutable row hash from selection.
    payload = ["cwv-horizon-panel-priority-v1", int(seed), deal_key,
               source_ref, int(seat), int(prefix_length)]
    return hashlib.sha256(canonical_json(payload).encode("ascii")).hexdigest()


def _deal_priority(seed: int, deal_key: str) -> str:
    return hashlib.sha256(canonical_json([
        "cwv-horizon-panel-deal-priority-v1", int(seed), deal_key
    ]).encode("ascii")).hexdigest()


def _read_rows(store: data.Store) -> tuple[list[dict[str, Any]], dict[str, int]]:
    rows: list[dict[str, Any]] = []
    census = {"records": 0, "train_records": 0, "val_records": 0,
              "test_records": 0}
    for shard in store.shards:
        before = sha256_file(shard.path)
        if before != shard.sha256:
            raise PanelError(f"source hash drift: {shard.label}")
        for record in data.iter_records(shard):
            if not isinstance(record, dict):
                raise PanelError(f"{shard.label}: record is not an object")
            record = dict(record)
            record["_panel_shard_label"] = shard.label
            record["_panel_shard_sha256"] = shard.sha256
            rows.append(record)
            census["records"] += 1
        after = sha256_file(shard.path)
        if after != shard.sha256:
            raise PanelError(f"source hash drift while reading: {shard.label}")
    return rows, census


def build_panel(store_path: str | Path, assignment_path: str | Path | Mapping[str, Any],
                out_path: str | Path, *, policy: str, max_deals: int = 64,
                seed: int = 0) -> dict[str, Any]:
    """Build and atomically publish a train-only panel.

    ``policy`` is intentionally required by the API as well as the CLI: a
    caller cannot accidentally use a different registry population.
    """
    if not isinstance(policy, str) or not policy:
        raise PanelError("--policy must be a non-empty exact policy string")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise PanelError("seed must be an integer")
    if isinstance(max_deals, bool) or not isinstance(max_deals, int) or max_deals <= 0:
        raise PanelError("max_deals must be a positive integer")
    target = Path(out_path)
    if target.exists() and target.is_dir():
        target = target / "cwv-horizon-panel.json"
    if target.exists():
        raise PanelError("panel output already exists; preserve the selected population")
    try:
        store = data.discover_store(store_path)
    except Exception as exc:
        raise PanelError(str(exc)) from exc
    assignment, assignment_sha = _assignment(assignment_path)
    rows, census = _read_rows(store)

    groups: dict[str, list[dict[str, Any]]] = {}
    seen_deals: set[str] = set()
    observed_splits: dict[str, set[str]] = {}
    for row in rows:
        key = _record_deal_key(row)
        seen_deals.add(key)
        split = assignment.get(key)
        if split is None:
            raise PanelError(f"assignment missing deal {key}")
        census[f"{split}_records"] += 1
        observed_splits.setdefault(key, set()).add(split)
        if split == "train":
            if row.get("policy") != policy:
                raise PanelError(f"train record policy mismatch: {row.get('policy')!r}")
            groups.setdefault(key, []).append(row)
    missing = seen_deals - set(assignment)
    if missing:
        raise PanelError(f"assignment missing {len(missing)} source deal(s)")
    extra = set(assignment) - seen_deals

    candidates: list[tuple[str, str, dict[str, Any], Any, int]] = []
    eligible = 0
    # Deal ordering is fixed before any state reconstruction.  This makes the
    # bounded prefix independent of row outcomes/metrics and avoids replaying
    # the remainder of a large corpus after the requested population is full.
    ordered_deals = sorted(groups, key=lambda key: (_deal_priority(seed, key), key))
    for deal_key in ordered_deals:
        deal_rows = groups[deal_key]
        ordered = sorted(
            deal_rows,
            key=lambda row: _priority(seed, deal_key, str(row.get("source_ref", "")),
                                       row.get("seat", -1), len(row.get("plays_prefix") or [])),
        )
        for position, row in enumerate(ordered):
            if row.get("decision_kind", "play") != "play":
                continue
            source_ref = row.get("source_ref")
            seat = row.get("seat")
            prefix = row.get("plays_prefix")
            if not isinstance(source_ref, str) or not isinstance(seat, int) \
                    or isinstance(seat, bool) or not isinstance(prefix, list):
                continue
            try:
                rnd = rebuild.state_for_record(row)
                if rnd.phase != "play" or rnd.turn != seat:
                    continue
                # cap=0 computes the exact count without building the legal list.
                legal_set = legal.enumerate_legal(rnd, seat, cap=0)
                if legal_set.count is None or legal_set.count < 6:
                    continue
            except Exception:
                # A malformed train row is not evidence of an eligible state;
                # keep searching this deal's deterministic row order.
                continue
            eligible += 1
            candidates.append((
                _deal_priority(seed, deal_key), deal_key, row, rnd, position))
            break
        if len(candidates) >= max_deals:
            break

    if not candidates:
        raise PanelError("zero eligible train deals")
    candidates.sort(key=lambda item: (item[0], item[1]))
    if len(candidates) < max_deals:
        raise PanelError(f"requested {max_deals} deals but only {len(candidates)} eligible")

    entries: list[dict[str, Any]] = []
    for rank, (_deal_rank, deal_key, row, rnd, position) in enumerate(
            candidates[:max_deals], start=1):
        record_sha = row.get("record_sha256")
        if not isinstance(record_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", record_sha):
            raise PanelError(f"selected record has invalid record_sha256: {row.get('source_ref')}")
        original = {k: v for k, v in row.items() if not k.startswith("_panel_")}
        if record_sha256(original) != record_sha:
            raise PanelError("selected record hash drift")
        prefix_length = len(row["plays_prefix"])
        identity = _priority(seed, deal_key, row["source_ref"], row["seat"], prefix_length)
        entries.append({
            "id": identity,
            "deal_key": deal_key,
            "rank": rank,
            "position": position,
            "ply": row.get("ply"),
            "source_ref": row["source_ref"],
            "record_sha256": record_sha,
            "provenance": {
                "split": "fit", "source_policy": policy,
                "source": row.get("source"),
                "shard": row["_panel_shard_label"],
                "shard_sha256": row["_panel_shard_sha256"],
                "seed": seed,
            },
            "snapshot": _state_snapshot(rnd),
        })

    census.update({"deals_seen": len(seen_deals), "train_deals": sum(
        "train" in splits for splits in observed_splits.values()),
        "eligible_train_deals": eligible, "selected_deals": len(entries),
        "unused_assignment_deals": len(extra),
        "assignment_train_deals": sum(split == "train" for split in assignment.values()),
        "assignment_val_deals": sum(split == "val" for split in assignment.values()),
        "assignment_test_deals": sum(split == "test" for split in assignment.values()),
    })
    panel = {
        "schema": PANEL_SCHEMA,
        "scope": SCOPE,
        "policy": policy,
        "seed": seed,
        "max_deals": max_deals,
        "assignment": dict(sorted(assignment.items())),
        "assignment_sha256": assignment_sha,
        "source": store.describe(),
        "summary": {"requested_deals": max_deals, "selected_deals": len(entries),
                    "complete": True, "train_only": True},
        "census": census,
        "entries": entries,
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    _publish(target, panel)
    return panel


# Descriptive alias for library callers; the CLI and implementation retain
# the short name used by the surrounding harvest scripts.
import_panel = build_panel


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", required=True, type=Path)
    parser.add_argument("--assignment", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--policy", required=True)
    parser.add_argument("--max-deals", "--max", dest="max_deals", type=int, default=64)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv)
    try:
        build_panel(args.store, args.assignment, args.out, policy=args.policy,
                    max_deals=args.max_deals, seed=args.seed)
    except PanelError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
