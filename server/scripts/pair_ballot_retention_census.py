#!/usr/bin/env python3
"""Outcome-free natural-dose census for guaranteed lead-pair retention."""

from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing as mp
import os
import platform
import random
import subprocess
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from shengji.ai.registry import make_bot
from shengji.engine.cards import SUITS, TRUMP
from shengji.engine.game import Game
from shengji.engine.legal import suit_cards


SCHEMA = "pair-ballot-retention-natural-dose-census-v1"
BANDS = ("early", "mid", "late")
FIELDS = (
    "lead_states",
    "lead_states_with_pairs",
    "cap_saturated_states",
    "pair_actions",
    "missing_pair_states",
    "missing_pair_actions",
    "retention_repairs",
)


def _band(trick: int) -> str:
    return "early" if trick < 4 else ("mid" if trick < 12 else "late")


def _empty_counts() -> dict[str, dict[str, int]]:
    return {band: {field: 0 for field in FIELDS} for band in BANDS}


def _pair_actions(rnd, seat: int) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for suit in list(SUITS) + [TRUMP]:
        cards = suit_cards(rnd.hands[seat], suit, rnd.ordering)
        pairs.update((code, code) for code, count in Counter(cards).items()
                     if count >= 2)
    return pairs


def _chunk(seed0: int, games: int) -> dict[str, dict[str, int]]:
    counts = _empty_counts()
    current = make_bot("mc", seed=seed0 ^ 0xC0FFEE)
    retained = make_bot("mc", seed=seed0 ^ 0xBAD5EED)
    retained.RETAIN_ALL_LEAD_PAIRS = True

    for seed in range(seed0, seed0 + games):
        game = Game(random.Random(seed))
        bots = [make_bot("smart") for _ in range(4)]
        rnd = game.start_round()
        while rnd.phase == "deal":
            seat, _, _ = rnd.deal_next()
            declaration = bots[seat].decide_declare(rnd, seat)
            if declaration:
                rnd.declare(seat, declaration)
        rnd.finalize_declare()
        rnd.bury(rnd.banker,
                 bots[rnd.banker].decide_bury(rnd, rnd.banker))

        while rnd.phase == "play":
            seat = rnd.turn
            if seat is None:
                break
            if not rnd.trick.plays:
                band = _band(len(rnd.history))
                row = counts[band]
                actions = current._candidates(rnd, seat)
                action_set = {tuple(sorted(action)) for action in actions}
                pairs = _pair_actions(rnd, seat)
                missing = pairs - action_set
                row["lead_states"] += 1
                row["lead_states_with_pairs"] += bool(pairs)
                row["cap_saturated_states"] += (
                    len(actions) == current.LEAD_MAX_CANDIDATES)
                row["pair_actions"] += len(pairs)
                row["missing_pair_states"] += bool(missing)
                row["missing_pair_actions"] += len(missing)
                if missing:
                    proposed = retained._candidates(rnd, seat)
                    proposed_set = {
                        tuple(sorted(action)) for action in proposed}
                    if proposed[0] != actions[0]:
                        raise AssertionError("retention displaced candidate zero")
                    if len(proposed) != len(actions):
                        raise AssertionError("retention changed ballot width")
                    if not pairs <= proposed_set:
                        raise AssertionError("retention failed to retain a pair")
                    row["retention_repairs"] += 1
            rnd.play(seat, bots[seat].decide_play(rnd, seat))
    return counts


def _merge(total, part) -> None:
    for band in BANDS:
        for field in FIELDS:
            total[band][field] += part[band][field]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--games", type=int, required=True)
    parser.add_argument("--workers", type=int, required=True)
    parser.add_argument("--chunks", type=int, default=160)
    parser.add_argument("--seed0", type=int, default=10_000_000)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.games <= 0 or args.workers <= 0 or args.chunks < args.workers:
        raise SystemExit("games/workers must be positive; chunks >= workers")
    if args.games % args.chunks:
        raise SystemExit("games must divide evenly across chunks")
    if args.out.exists():
        raise SystemExit(f"refusing to overwrite {args.out}")

    started = time.perf_counter()
    per_chunk = args.games // args.chunks
    total = _empty_counts()
    futures = []
    with ProcessPoolExecutor(
            max_workers=args.workers,
            mp_context=mp.get_context("fork")) as pool:
        for index in range(args.chunks):
            futures.append(pool.submit(
                _chunk, args.seed0 + index * per_chunk, per_chunk))
        for complete, future in enumerate(as_completed(futures), start=1):
            _merge(total, future.result())
            if complete == 1 or complete % args.workers == 0:
                print(json.dumps({
                    "event": "pair-retention-census-progress-v1",
                    "chunks_complete": complete,
                    "chunks_total": args.chunks,
                    "games_complete": complete * per_chunk,
                    "workers": args.workers,
                    "elapsed_seconds": round(time.perf_counter() - started, 3),
                    "score_free": True,
                }, sort_keys=True), flush=True)

    elapsed = time.perf_counter() - started
    script = Path(__file__).resolve()
    payload = {
        "schema": SCHEMA,
        "git": subprocess.run(
            ["git", "rev-parse", "HEAD"], check=True,
            capture_output=True, text=True).stdout.strip(),
        "script_sha256": _sha256(script),
        "host": platform.node(),
        "python": platform.python_version(),
        "fast_engine": os.environ.get("SHENGJI_FAST") == "1",
        "seed0": args.seed0,
        "games": args.games,
        "workers": args.workers,
        "chunks": args.chunks,
        "elapsed_seconds": elapsed,
        "counts": total,
        "score_free": True,
        "outcomes_published": False,
        "strength_claim": False,
        "production_authority": False,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
        handle.write("\n")
    print(json.dumps({
        "event": "pair-retention-census-complete-v1",
        "games": args.games,
        "elapsed_seconds": round(elapsed, 3),
        "out": str(args.out),
        "score_free": True,
    }, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
