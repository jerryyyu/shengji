#!/usr/bin/env python3
"""Review and verify the score-free pair-ballot retention census.

The million-round Cloud job was started from a temporary copy of the exact
producer before that source had been committed.  This module makes the content
boundary reviewable without reading the terminal result prematurely.  Once an
independent review authorizes content access, ``verify`` validates the one
existing result; it never launches or retries a census.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import pair_ballot_retention_census as PRODUCER


SCHEMA = "pair-ballot-retention-census-content-review-v1"
REVIEW_MARKER = "PAIR_BALLOT_RETENTION_CENSUS_CONTENT_V1_REVIEW "
SOURCE_GIT = "1d6bd2fc757b60b369a88f384e83f9d313360723"
PRODUCER_SHA256 = (
    "7f4efbd82596ef55f41f768d7825c2b637080c814942ca9625b3fcc7728d9a11"
)
EXPECTED_HOST = "ubuntu-32gb-hel1-1"
EXPECTED_PYTHON = "3.14.4"
EXPECTED_SEED0 = 10_000_000
EXPECTED_GAMES = 1_000_000
EXPECTED_WORKERS = 16
EXPECTED_CHUNKS = 160
TOP_FIELDS = {
    "schema", "git", "script_sha256", "host", "python", "fast_engine",
    "seed0", "games", "workers", "chunks", "elapsed_seconds", "counts",
    "score_free", "outcomes_published", "strength_claim",
    "production_authority",
}


class ReviewRefused(RuntimeError):
    """The producer or claimed score-free result boundary drifted."""


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def producer_path() -> Path:
    return Path(PRODUCER.__file__).resolve()


def producer_problems() -> list[str]:
    path = producer_path()
    problems = []
    if path.is_symlink() or not path.is_file():
        problems.append("census producer missing/non-regular")
    elif sha256(path) != PRODUCER_SHA256:
        problems.append("census producer SHA-256 drifted")
    if PRODUCER.SCHEMA != "pair-ballot-retention-natural-dose-census-v1":
        problems.append("census producer schema drifted")
    if tuple(PRODUCER.BANDS) != ("early", "mid", "late"):
        problems.append("census phase bands drifted")
    if tuple(PRODUCER.FIELDS) != (
            "lead_states", "lead_states_with_pairs",
            "cap_saturated_states", "pair_actions", "missing_pair_states",
            "missing_pair_actions", "retention_repairs"):
        problems.append("census count fields drifted")
    return sorted(set(problems))


def review_claim(*, reviewed_git: str) -> dict:
    problems = producer_problems()
    if problems:
        raise ReviewRefused("; ".join(problems))
    if len(reviewed_git) != 40:
        raise ReviewRefused("reviewed Git must be a full SHA")
    return {
        "schema": SCHEMA,
        "reviewed_git": reviewed_git,
        "source_git": SOURCE_GIT,
        "producer_sha256": PRODUCER_SHA256,
        "expected_games": EXPECTED_GAMES,
        "expected_workers": EXPECTED_WORKERS,
        "expected_chunks": EXPECTED_CHUNKS,
        "content_read_authorized": True,
        "rerun_authorized": False,
        "score_free": True,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
        "verdict": "PASS",
    }


def result_problems(value: object) -> list[str]:
    if not isinstance(value, dict):
        return ["census result is not an object"]
    problems = producer_problems()
    if set(value) != TOP_FIELDS:
        problems.append("census result field set drifted")
    exact = {
        "schema": PRODUCER.SCHEMA,
        "git": SOURCE_GIT,
        "script_sha256": PRODUCER_SHA256,
        "host": EXPECTED_HOST,
        "python": EXPECTED_PYTHON,
        "seed0": EXPECTED_SEED0,
        "games": EXPECTED_GAMES,
        "workers": EXPECTED_WORKERS,
        "chunks": EXPECTED_CHUNKS,
        "score_free": True,
        "outcomes_published": False,
        "strength_claim": False,
        "production_authority": False,
    }
    for key, expected in exact.items():
        if value.get(key) != expected:
            problems.append(f"census result field drifted: {key}")
    if not isinstance(value.get("fast_engine"), bool):
        problems.append("census fast-engine disclosure is not boolean")
    elapsed = value.get("elapsed_seconds")
    if (not isinstance(elapsed, (int, float)) or isinstance(elapsed, bool)
            or not math.isfinite(elapsed) or elapsed <= 0):
        problems.append("census elapsed time is invalid")

    counts = value.get("counts")
    if not isinstance(counts, dict) or set(counts) != set(PRODUCER.BANDS):
        problems.append("census count bands drifted")
        return sorted(set(problems))
    for band in PRODUCER.BANDS:
        row = counts.get(band)
        if not isinstance(row, dict) or set(row) != set(PRODUCER.FIELDS):
            problems.append(f"census count fields drifted: {band}")
            continue
        if any(not isinstance(row[field], int)
               or isinstance(row[field], bool) or row[field] < 0
               for field in PRODUCER.FIELDS):
            problems.append(f"census counts are not nonnegative ints: {band}")
            continue
        if not (row["missing_pair_states"] <=
                row["lead_states_with_pairs"] <= row["lead_states"]):
            problems.append(f"census state counts do not nest: {band}")
        if row["cap_saturated_states"] > row["lead_states"]:
            problems.append(f"census cap count exceeds lead states: {band}")
        if row["missing_pair_actions"] > row["pair_actions"]:
            problems.append(f"census missing actions exceed pairs: {band}")
        if row["missing_pair_actions"] < row["missing_pair_states"]:
            problems.append(f"census missing actions undercount states: {band}")
        if row["retention_repairs"] != row["missing_pair_states"]:
            problems.append(f"census repair count does not close: {band}")
    if isinstance(counts, dict):
        lead_total = sum(
            counts.get(band, {}).get("lead_states", 0)
            for band in PRODUCER.BANDS)
        if not EXPECTED_GAMES <= lead_total <= 25 * EXPECTED_GAMES:
            problems.append("census total lead-state count is implausible")
    return sorted(set(problems))


def load_and_verify(path: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        raise ReviewRefused("census result missing/non-regular")
    try:
        value = json.loads(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise ReviewRefused(f"cannot read census result: {exc}") from exc
    problems = result_problems(value)
    if problems:
        raise ReviewRefused("; ".join(problems))
    return {
        "verified": True,
        "artifact_sha256": sha256(path),
        "schema": value["schema"],
        "source_git": value["git"],
        "games": value["games"],
        "score_free": True,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("review-claim", "verify"))
    parser.add_argument("--reviewed-git")
    parser.add_argument("--result", type=Path)
    args = parser.parse_args()
    if args.command == "review-claim":
        if not args.reviewed_git:
            raise ReviewRefused("review-claim requires --reviewed-git")
        print(REVIEW_MARKER + json.dumps(
            review_claim(reviewed_git=args.reviewed_git),
            sort_keys=True, separators=(",", ":")))
    else:
        if args.result is None:
            raise ReviewRefused("verify requires --result")
        print(json.dumps(load_and_verify(args.result), sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except ReviewRefused as exc:
        print(f"REFUSING: {exc}")
        raise SystemExit(3) from exc
