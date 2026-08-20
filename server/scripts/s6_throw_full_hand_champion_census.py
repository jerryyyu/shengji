#!/usr/bin/env python3
"""Score-free prevalence of selective S6 on live-champion trajectories.

The first 50,000-deal census used cheap heuristic trajectories.  This bounded
successor asks whether the same actor-visible gate is reached when all four
seats actually use production ``mc-s0-report-lcb``.  Eight independent shards
publish source/dose counts only; no score, winner, utility, action, hand, or
round outcome is retained.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import random
import subprocess
import sys
from collections import Counter
from pathlib import Path


SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[1]
REPO = SERVER.parent
sys.path.insert(0, str(SERVER))
sys.path.insert(0, str(SCRIPT.parent))

import s6_throw_full_hand_prevalence as PREV  # noqa: E402
from shengji.ai.registry import make_bot  # noqa: E402
from shengji.engine import combos, fast  # noqa: E402
from shengji.engine.game import Game  # noqa: E402


SHARD_SCHEMA = "s6-throw-full-hand-champion-census-shard-v1"
AGGREGATE_SCHEMA = "s6-throw-full-hand-champion-census-v1"
POLICY = "mc-s0-report-lcb"
SEED0 = 438_000_000
SHARDS = 8
DEALS_PER_SHARD = 64
TOTAL_DEALS = SHARDS * DEALS_PER_SHARD
POLICY_SEED_STRIDE = 10_000_019
PROGRESS_EVERY = 8
ROLES = PREV.ROLES
PHASES = PREV.PHASES
FORBIDDEN_FIELDS = frozenset({
    "attacker_points", "winner_team", "level_change", "won", "utility",
    "level_utility", "winner", "points", "hands", "actions", "records",
    "outcomes",
})


class CensusRefused(RuntimeError):
    """The score-free champion census cannot support its bounded claim."""


def sha256(path: os.PathLike | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def stable_digest(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, check=True, capture_output=True, text=True,
    ).stdout.strip()


def source_sha256s() -> dict[str, str]:
    paths = {
        "census": SCRIPT,
        "heuristic_prevalence": PREV.SCRIPT,
        "throw_source": SERVER / "shengji/ai/throw_sourcing.py",
        "registry": SERVER / "shengji/ai/registry.py",
        "mcbot": SERVER / "shengji/ai/mcbot.py",
        "memory": SERVER / "shengji/ai/memory.py",
        "game": SERVER / "shengji/engine/game.py",
        "round": SERVER / "shengji/engine/round.py",
    }
    if fast.HAVE_FAST and fast._fast is not None:
        paths["fast_binary"] = Path(fast._fast.__file__).resolve()
    return {name: sha256(path) for name, path in sorted(paths.items())}


def runtime_snapshot() -> dict[str, object]:
    return {
        "host": platform.node(),
        "python": platform.python_version(),
        "python_executable": str(Path(sys.executable).resolve()),
        "fast_active": bool(
            fast.HAVE_FAST and fast._fast is not None
            and combos.decompose is fast.decompose),
        "fast_binary_sha256": (
            sha256(Path(fast._fast.__file__).resolve())
            if fast.HAVE_FAST and fast._fast is not None else None),
    }


def _start_round(seed: int):
    rnd = Game(random.Random(seed)).start_round()
    actors = [make_bot(POLICY, seed=seed + POLICY_SEED_STRIDE * seat)
              for seat in range(4)]
    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        cards = actors[seat].decide_declare(rnd, seat)
        if cards:
            rnd.declare(seat, cards)
    for seat in range(4):
        cards = actors[seat].decide_declare(rnd, seat, final=True)
        if cards:
            rnd.declare(seat, cards)
    rnd.finalize_declare()
    if rnd.banker is None:
        raise CensusRefused("champion trajectory has no banker")
    rnd.bury(rnd.banker, actors[rnd.banker].decide_bury(rnd, rnd.banker))
    return rnd, actors


def run_deal(seed: int) -> dict[str, object]:
    rnd, actors = _start_round(seed)
    counts = Counter()
    cells = Counter()
    by_hand_cards = Counter()
    while rnd.phase == "play":
        seat = rnd.turn
        if seat is None:
            raise CensusRefused("champion play state lost acting seat")
        if rnd.trick is not None and not rnd.trick.plays:
            counts["leads"] += 1
            additions = PREV.full_hand_additions(
                rnd, seat, live_bot=actors[seat])
            if additions:
                role = "attacker" if rnd.is_attacker(seat) else "defender"
                phase = PREV.phase_band(len(rnd.history))
                counts["triggered_leads"] += 1
                counts["new_candidates"] += len(additions)
                cells[(role, phase)] += 1
                by_hand_cards[len(rnd.hands[seat])] += 1
        rnd.play(seat, actors[seat].decide_play(rnd, seat))
    if rnd.phase != "round_end":
        raise CensusRefused("champion trajectory did not complete")
    return {
        "leads": int(counts["leads"]),
        "triggered_leads": int(counts["triggered_leads"]),
        "new_candidates": int(counts["new_candidates"]),
        "triggered": counts["triggered_leads"] > 0,
        "cells": {f"{role}:{phase}": int(cells[(role, phase)])
                  for role in ROLES for phase in PHASES},
        "by_hand_cards": {str(cards): int(count)
                          for cards, count in sorted(by_hand_cards.items())},
    }


def run_shard(*, shard_index: int) -> dict:
    if shard_index not in range(SHARDS):
        raise ValueError("shard index outside frozen schedule")
    start = SEED0 + shard_index * DEALS_PER_SHARD
    totals = Counter()
    cells = Counter()
    by_hand_cards = Counter()
    for offset in range(DEALS_PER_SHARD):
        row = run_deal(start + offset)
        totals["deals"] += 1
        totals["leads"] += row["leads"]
        totals["triggered_deals"] += int(row["triggered"])
        totals["triggered_leads"] += row["triggered_leads"]
        totals["new_candidates"] += row["new_candidates"]
        cells.update(row["cells"])
        by_hand_cards.update({int(key): value
                              for key, value in row["by_hand_cards"].items()})
        if (offset + 1) % PROGRESS_EVERY == 0:
            print(json.dumps({
                "event": "s6-full-hand-champion-census-progress-v1",
                "shard_index": shard_index,
                "deals_complete": offset + 1,
                "deals_total": DEALS_PER_SHARD,
                "triggered_deals": totals["triggered_deals"],
            }, sort_keys=True), flush=True)
    payload = {
        "schema": SHARD_SCHEMA,
        "git": git("rev-parse", "HEAD"),
        "tree_dirty": bool(git("status", "--porcelain", "--untracked-files=all")),
        "source_sha256s": source_sha256s(),
        "runtime": runtime_snapshot(),
        "design": {
            "policy": POLICY,
            "shard_index": shard_index,
            "seed_start": start,
            "seed_end_exclusive": start + DEALS_PER_SHARD,
            "deals": DEALS_PER_SHARD,
            "score_free": True,
        },
        "counts": {
            "deals": int(totals["deals"]),
            "leads": int(totals["leads"]),
            "triggered_deals": int(totals["triggered_deals"]),
            "triggered_leads": int(totals["triggered_leads"]),
            "new_candidates": int(totals["new_candidates"]),
            "cells": {key: int(cells[key]) for key in sorted(cells)},
            "by_hand_cards": {str(cards): int(count)
                              for cards, count in sorted(by_hand_cards.items())},
        },
        "score_free": True,
        "outcomes_published": False,
        "strength_claim": False,
        "whole_game_execution_authorized": False,
        "production_deployment": False,
    }
    payload["internal_sha256"] = stable_digest(payload)
    return payload


def score_free_problems(value: object) -> list[str]:
    problems = []

    def walk(item, path: str) -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                if key in FORBIDDEN_FIELDS:
                    problems.append(f"forbidden field {path}{key}")
                walk(child, f"{path}{key}.")
        elif isinstance(item, list):
            for index, child in enumerate(item):
                walk(child, f"{path}{index}.")

    walk(value, "")
    if (not isinstance(value, dict) or value.get("score_free") is not True
            or value.get("outcomes_published") is not False):
        problems.append("score-free identity")
    return sorted(set(problems))


def aggregate_payload(shards: list[dict], *, expected_git: str) -> dict:
    if len(shards) != SHARDS:
        raise CensusRefused("champion census shard count drift")
    ordered = sorted(shards, key=lambda row: row["design"]["shard_index"])
    if [row["design"]["shard_index"] for row in ordered] != list(range(SHARDS)):
        raise CensusRefused("champion census shard index population drift")
    expected_source = source_sha256s()
    expected_runtime = runtime_snapshot()
    totals = Counter()
    cells = Counter()
    by_hand_cards = Counter()
    shard_records = []
    for index, row in enumerate(ordered):
        start = SEED0 + index * DEALS_PER_SHARD
        internal = row.get("internal_sha256")
        without = dict(row)
        without.pop("internal_sha256", None)
        if (row.get("schema") != SHARD_SCHEMA or row.get("git") != expected_git
                or row.get("tree_dirty") is not False
                or row.get("source_sha256s") != expected_source
                or row.get("runtime") != expected_runtime
                or row.get("design", {}).get("seed_start") != start
                or row.get("design", {}).get("seed_end_exclusive")
                != start + DEALS_PER_SHARD
                or row.get("counts", {}).get("deals") != DEALS_PER_SHARD
                or stable_digest(without) != internal
                or score_free_problems(row)):
            raise CensusRefused(f"champion census shard {index} drift")
        counts = row["counts"]
        for key in ("deals", "leads", "triggered_deals",
                    "triggered_leads", "new_candidates"):
            totals[key] += counts[key]
        cells.update(counts["cells"])
        by_hand_cards.update({int(key): value
                              for key, value in counts["by_hand_cards"].items()})
        shard_records.append({
            "shard_index": index,
            "internal_sha256": internal,
        })
    payload = {
        "schema": AGGREGATE_SCHEMA,
        "git": expected_git,
        "source_sha256s": expected_source,
        "runtime": expected_runtime,
        "design": {
            "policy": POLICY,
            "seed0": SEED0,
            "shards": SHARDS,
            "deals_per_shard": DEALS_PER_SHARD,
            "deals": TOTAL_DEALS,
            "trajectory": "literal mc-s0-report-lcb at all four seats",
            "score_free": True,
        },
        "shards": shard_records,
        "counts": {
            "deals": int(totals["deals"]),
            "leads": int(totals["leads"]),
            "triggered_deals": int(totals["triggered_deals"]),
            "triggered_leads": int(totals["triggered_leads"]),
            "new_candidates": int(totals["new_candidates"]),
            "cells": {key: int(cells[key]) for key in sorted(cells)},
            "by_hand_cards": {str(cards): int(count)
                              for cards, count in sorted(by_hand_cards.items())},
        },
        "rates": {
            "triggered_deals": totals["triggered_deals"] / totals["deals"],
            "triggered_leads": totals["triggered_leads"] / totals["leads"],
        },
        "score_free": True,
        "outcomes_published": False,
        "exploration_only": True,
        "strength_claim": False,
        "whole_game_execution_authorized": False,
        "production_deployment": False,
    }
    payload["internal_sha256"] = stable_digest(payload)
    if totals["deals"] != TOTAL_DEALS or score_free_problems(payload):
        raise CensusRefused("champion census aggregate contract drift")
    return payload


def write_exclusive(path: Path, payload: dict) -> None:
    PREV.write_exclusive(path, payload)


def require_runtime(expected_git: str) -> None:
    if git("rev-parse", "HEAD") != expected_git:
        raise CensusRefused("champion census git identity drift")
    if git("status", "--porcelain", "--untracked-files=all"):
        raise CensusRefused("champion census requires clean tree")
    runtime = runtime_snapshot()
    if (os.environ.get("SHENGJI_FAST") != "1"
            or os.environ.get("SHENGJI_REQUIRE_VOIDS") != "1"
            or runtime["fast_active"] is not True):
        raise CensusRefused("champion census requires strict compiled runtime")


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run-shard")
    run.add_argument("--expected-git", required=True)
    run.add_argument("--shard-index", type=int, required=True)
    run.add_argument("--out", required=True)
    aggregate = sub.add_parser("aggregate")
    aggregate.add_argument("--expected-git", required=True)
    aggregate.add_argument("--inputs", nargs=SHARDS, required=True)
    aggregate.add_argument("--out", required=True)
    args = parser.parse_args()
    require_runtime(args.expected_git)
    if args.command == "run-shard":
        payload = run_shard(shard_index=args.shard_index)
    else:
        inputs = [Path(path) for path in args.inputs]
        if any(not path.is_file() for path in inputs):
            raise CensusRefused("champion census input missing")
        payload = aggregate_payload(
            [json.loads(path.read_bytes()) for path in inputs],
            expected_git=args.expected_git)
    write_exclusive(Path(args.out), payload)
    print(json.dumps({
        "status": "COMPLETE_SCORE_FREE_CHAMPION_CENSUS",
        "output_sha256": sha256(args.out),
        "internal_sha256": payload["internal_sha256"],
        "counts": payload["counts"],
        "strength_claim": False,
    }, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
