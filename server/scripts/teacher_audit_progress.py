#!/usr/bin/env python3
"""Read only the score-free progress stream of the live Teacher audit.

The label JSON files contain experimental outcomes and must remain unopened
until the one-shot supervisor publishes its terminal gate.  Worker stdout is
safer, but only if every line is proved to be one of the two registered
progress events (or the outcome-free terminal publication receipt).  This
reader enforces that boundary, validates ordering, and reports counts only.

It never writes to the run directory and conveys no stopping, retry, gate,
training, or promotion authority.
"""
from __future__ import annotations

import argparse
import json
import os
import stat
import sys
from pathlib import Path


SCHEMA = "teacher-v3-score-free-progress-summary-v1"
AUDIT_ID = "teacher-v3-report-lcb-audit-v2"
EVENT = "teacher-v1-champion-audit-progress"
SHARD_COUNT = 8
STATES_PER_SHARD = 8
FOLDS = ("champion_selection", "champion_report")
WORLDS_PER_FOLD = 32
PROGRESS_PREFIX = "champion_audit_v2_shard"
PROGRESS_KEYS = {
    "champion-fold": {
        "audit_id", "event", "fold", "kind", "shard_count",
        "shard_index", "state_id", "worlds_complete", "worlds_total",
    },
    "state": {
        "audit_id", "event", "kind", "shard_count", "shard_index",
        "state_id", "states_complete", "states_total",
    },
}
TERMINAL_KEYS = {
    "audit_id", "mode", "out", "shard_index", "records",
    "records_digest",
}


class ProgressRefusal(RuntimeError):
    """The worker logs cannot support a score-free progress statement."""


def _regular_file(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    return stat.S_ISREG(info.st_mode)


def _log_path(run_root: Path, shard_index: int) -> tuple[Path, bool]:
    stem = f"{PROGRESS_PREFIX}{shard_index:02d}.log"
    final = run_root / stem
    partial = run_root / f"{stem}.partial"
    present = [path for path in (final, partial) if os.path.lexists(path)]
    if len(present) != 1:
        raise ProgressRefusal(
            f"shard {shard_index} requires exactly one final/partial log")
    path = present[0]
    if not _regular_file(path):
        raise ProgressRefusal(f"shard {shard_index} log is not regular")
    return path, path == final


def _exact_int(value: object) -> bool:
    return type(value) is int


def _load_lines(path: Path) -> list[dict]:
    try:
        raw_lines = path.read_text(encoding="utf-8").splitlines()
        values = [json.loads(line) for line in raw_lines]
    except (OSError, UnicodeError, ValueError) as exc:
        raise ProgressRefusal(f"cannot parse score-free log {path}: {exc}") \
            from exc
    if any(not isinstance(value, dict) for value in values):
        raise ProgressRefusal(f"non-object line in score-free log {path}")
    return values


def parse_shard(path: Path, shard_index: int, *, final: bool) -> dict:
    states_complete = 0
    worlds_complete = 0
    current_state: str | None = None
    fold_index = 0
    next_world = 1
    state_ids: list[str] = []
    publication_complete = False

    for line_index, value in enumerate(_load_lines(path), 1):
        kind = value.get("kind")
        if kind in PROGRESS_KEYS:
            if publication_complete:
                raise ProgressRefusal(
                    f"shard {shard_index} progress follows publication")
            if set(value) != PROGRESS_KEYS[kind]:
                raise ProgressRefusal(
                    f"shard {shard_index} line {line_index} progress keys")
            if (value.get("event") != EVENT
                    or value.get("audit_id") != AUDIT_ID
                    or not _exact_int(value.get("shard_index"))
                    or not _exact_int(value.get("shard_count"))
                    or value.get("shard_index") != shard_index
                    or value.get("shard_count") != SHARD_COUNT):
                raise ProgressRefusal(
                    f"shard {shard_index} line {line_index} identity")
            state_id = value.get("state_id")
            if not isinstance(state_id, str) or not state_id:
                raise ProgressRefusal(
                    f"shard {shard_index} line {line_index} state identity")

            if kind == "champion-fold":
                if (not _exact_int(value.get("worlds_complete"))
                        or not _exact_int(value.get("worlds_total"))):
                    raise ProgressRefusal(
                        f"shard {shard_index} line {line_index} fold types")
                if current_state is None:
                    current_state = state_id
                    fold_index = 0
                    next_world = 1
                if (state_id != current_state or fold_index >= len(FOLDS)
                        or value.get("fold") != FOLDS[fold_index]
                        or value.get("worlds_complete") != next_world
                        or value.get("worlds_total") != WORLDS_PER_FOLD):
                    raise ProgressRefusal(
                        f"shard {shard_index} line {line_index} fold order")
                worlds_complete += 1
                next_world += 1
                if next_world > WORLDS_PER_FOLD:
                    fold_index += 1
                    next_world = 1
                continue

            if (not _exact_int(value.get("states_complete"))
                    or not _exact_int(value.get("states_total"))
                    or current_state is None or state_id != current_state
                    or fold_index != len(FOLDS) or next_world != 1
                    or value.get("states_complete") != states_complete + 1
                    or value.get("states_total") != STATES_PER_SHARD):
                raise ProgressRefusal(
                    f"shard {shard_index} line {line_index} state order")
            states_complete += 1
            state_ids.append(state_id)
            current_state = None
            fold_index = 0
            next_world = 1
            continue

        if set(value) != TERMINAL_KEYS:
            raise ProgressRefusal(
                f"shard {shard_index} line {line_index} is not score-free")
        digest = value.get("records_digest")
        if (publication_complete or current_state is not None
                or states_complete != STATES_PER_SHARD
                or value.get("audit_id") != AUDIT_ID
                or value.get("mode") != "label"
                or not _exact_int(value.get("shard_index"))
                or not _exact_int(value.get("records"))
                or value.get("shard_index") != shard_index
                or value.get("records") != STATES_PER_SHARD
                or not isinstance(value.get("out"), str)
                or not isinstance(digest, str) or len(digest) != 64
                or any(char not in "0123456789abcdef" for char in digest)):
            raise ProgressRefusal(
                f"shard {shard_index} line {line_index} publication receipt")
        publication_complete = True

    if states_complete > STATES_PER_SHARD:
        raise ProgressRefusal(f"shard {shard_index} state count overflow")
    observed_states = state_ids + ([current_state] if current_state else [])
    if len(observed_states) != len(set(observed_states)):
        raise ProgressRefusal(f"shard {shard_index} repeats a state identity")
    if final and not publication_complete:
        raise ProgressRefusal(
            f"shard {shard_index} final log lacks publication receipt")
    return {
        "shard_index": shard_index,
        "states_complete": states_complete,
        "states_total": STATES_PER_SHARD,
        "outer_worlds_complete": worlds_complete,
        "outer_worlds_total": (
            STATES_PER_SHARD * len(FOLDS) * WORLDS_PER_FOLD),
        "publication_complete": publication_complete,
        "log_final": final,
        "state_ids": observed_states,
    }


def summarize(run_root: Path) -> dict:
    if not _regular_file(run_root) and not run_root.is_dir():
        raise ProgressRefusal(f"run root is not a directory: {run_root}")
    shards = []
    seen_states: set[str] = set()
    for shard_index in range(SHARD_COUNT):
        path, final = _log_path(run_root, shard_index)
        shard = parse_shard(path, shard_index, final=final)
        state_ids = shard.pop("state_ids")
        overlap = seen_states.intersection(state_ids)
        if overlap:
            raise ProgressRefusal(
                f"state identity appears across shards: {sorted(overlap)}")
        seen_states.update(state_ids)
        shards.append(shard)
    worlds = sum(item["outer_worlds_complete"] for item in shards)
    total_worlds = sum(item["outer_worlds_total"] for item in shards)
    states = sum(item["states_complete"] for item in shards)
    return {
        "schema": SCHEMA,
        "audit_id": AUDIT_ID,
        "score_free": True,
        "read_only": True,
        "run_root": str(run_root),
        "outer_worlds_complete": worlds,
        "outer_worlds_total": total_worlds,
        "outer_worlds_fraction": worlds / total_worlds,
        "states_complete": states,
        "states_total": SHARD_COUNT * STATES_PER_SHARD,
        "published_label_shards": sum(
            item["publication_complete"] for item in shards),
        "shards": shards,
        "stopping_authorized": False,
        "retry_or_resume_authorized": False,
        "outcome_opened": False,
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-root", required=True)
    args = parser.parse_args(argv)
    try:
        payload = summarize(Path(args.run_root))
    except ProgressRefusal as exc:
        print(f"REFUSING: {exc}", file=sys.stderr)
        raise SystemExit(3) from exc
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
