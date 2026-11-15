#!/usr/bin/env python3
"""Fixtures that hold the offline page's bot requests to the game server's rounds.

For the solo games of ``server_sessions.jsonl.gz`` (same seeds, same human
driver; ``server/scripts/gen_offline_server_fixtures.py``), with SmartBot as the
room bot, records the request the offline page must send for every room-bot
decision (``bridge_harness``) and writes, per game, the digest of each request
in order.  The vitest suite (``web/src/offline/server/bridge.test.ts``) plays
the same games on the TypeScript server with a stand-in for the native bot and
compares the requests it sends, digest by digest: the TypeScript action log,
deck, banker and trump rank must be exactly what the Python round holds.

Usage::

    server/.venv/bin/python web/ios/pybot/gen_bridge_fixtures.py --games 40 \\
        --out web/src/offline/fixtures
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bridge_harness  # noqa: E402
import gen_offline_server_fixtures as sessions  # noqa: E402  (on sys.path via bridge_harness)
from gen_offline_engine_fixtures import _gzip_bytes  # noqa: E402
from shengji.ai.registry import make_bot  # noqa: E402

FORMAT = 1
FIXTURE = "bridge_requests.jsonl.gz"


def canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def digest(obj) -> str:
    return hashlib.sha256(canonical(obj).encode("ascii")).hexdigest()[:8]


def game_record(seed: int, rounds: int, config: dict, stats: Counter) -> dict:
    records, _ = bridge_harness.record_session(seed, rounds, config, lambda: make_bot("smart"))
    for r in records:
        stats[r["request"]["kind"]] += 1
    stats["games"] += 1
    return {"seed": seed, "rounds": rounds, "config": config, "requests": len(records),
            "digests": "".join(digest(r["request"]) for r in records)}


def fixture_text(games: int, rounds: int, base_seed: int, stats: Counter | None = None) -> str:
    stats = Counter() if stats is None else stats
    lines = [canonical(game_record(sessions.game_seed(base_seed, g), rounds,
                                   sessions.game_config(g), stats)) for g in range(games)]
    header = {"format": FORMAT, "games": games, "rounds": rounds, "seed": base_seed,
              "human": sessions.HUMAN_NAME, "stats": dict(sorted(stats.items()))}
    return "\n".join([canonical(header)] + lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--games", type=int, default=40)
    ap.add_argument("--rounds", type=int, default=2)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    stats: Counter = Counter()
    text = fixture_text(args.games, args.rounds, args.seed, stats)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / FIXTURE).write_bytes(_gzip_bytes(text))
    print(json.dumps(dict(sorted(stats.items()))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
