#!/usr/bin/env python3
"""Project sealed lead-diagnostic game boundaries, never outcome measurements.

The producer seeds its first Game with S and each restart with S*1000+r.
Subsequent rounds in a game consume the existing RNG stream: seed reservations
alone cannot represent their deal exposure. This tool writes no registry entries.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

MAX_BYTES = 256 * 1024 * 1024


def _sealed(path: Path, expected: str) -> list[dict]:
    if len(expected) != 64 or any(c not in "0123456789abcdef" for c in expected):
        raise ValueError("invalid SHA256 pin")
    with path.open("rb") as stream:
        data = stream.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("input exceeds byte limit")
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError("input SHA256 mismatch")
    try:
        rows = [json.loads(line) for line in data.splitlines() if line.strip()]
    except (ValueError, UnicodeError):
        raise ValueError("invalid JSONL") from None
    if not all(isinstance(row, dict) for row in rows):
        raise ValueError("JSONL rows must be objects")
    return rows


def project(rows_path: Path, rows_sha: str, journal_path: Path, journal_sha: str,
            seed: int, rounds: int) -> dict:
    if type(seed) is not int or seed < 0 or type(rounds) is not int or not 1 <= rounds <= 10000:
        raise ValueError("invalid seed or round count")
    journal = _sealed(journal_path, journal_sha)
    if not journal or journal[0].get("kind") != "start" or journal[-1].get("kind") != "terminal":
        raise ValueError("missing journal start or terminal")
    starts = [r for r in journal if r.get("kind") == "start"]
    ends = [r for r in journal if r.get("kind") == "terminal"]
    if len(starts) != 1 or len(ends) != 1:
        raise ValueError("duplicate journal terminal or start")
    if starts[0].get("seed") != seed or ends[0].get("reason") != "max_rounds" or ends[0].get("rounds") != rounds:
        raise ValueError("journal identity or completion mismatch")
    expected = list(range(rounds))
    for kind in ("prepared", "round_complete"):
        seen = [r.get("round") for r in journal if r.get("kind") == kind]
        if any(type(r) is not int for r in seen) or seen != expected:
            raise ValueError("incomplete or unordered round witnesses")
    rows = _sealed(rows_path, rows_sha)
    if type(ends[0].get("positions")) is not int or ends[0]["positions"] != len(rows):
        raise ValueError("position count mismatch")
    games: dict[int, int] = {}
    previous_round = -1
    for row in rows:
        r = row.get("round")
        game = row.get("game")
        if type(row.get("seed")) is not int or row["seed"] != seed or type(r) is not int or not 0 <= r < rounds:
            raise ValueError("row seed or round mismatch")
        if r < previous_round:
            raise ValueError("rows are not ordered")
        previous_round = r
        if not isinstance(game, str) or not game.startswith(f"{seed}:"):
            raise ValueError("row game identity mismatch")
        suffix = game[len(str(seed)) + 1:]
        if not suffix.isascii() or not suffix.isdecimal() or str(int(suffix)) != suffix:
            raise ValueError("invalid game index")
        gid = int(suffix)
        if r in games and games[r] != gid:
            raise ValueError("conflicting game identities within round")
        games[r] = gid
    if sorted(games) != expected:
        raise ValueError("missing round game witness")
    boundaries = []
    continuous = []
    previous_game = -1
    for r in expected:
        gid = games[r]
        if gid == previous_game and r > 0:
            continuous.append(r)
        elif gid == previous_game + 1:
            boundaries.append({"round": r, "game_index": gid,
                               "rng_seed": seed if r == 0 else seed * 1000 + r})
        else:
            raise ValueError("nonconsecutive game identities")
        previous_game = gid
    return {"schema": "s90-seed-boundaries-v1", "seed": seed, "rounds": rounds,
            "rows_sha256": rows_sha, "journal_sha256": journal_sha,
            "game_starts": boundaries, "continuous_game_rounds": continuous,
            "deal_exposure_complete": False,
            "claim": "RNG initialization seeds only; continuous-game deal keys require separate clearance."}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--rows", type=Path, required=True)
    ap.add_argument("--rows-sha256", required=True)
    ap.add_argument("--journal", type=Path, required=True)
    ap.add_argument("--journal-sha256", required=True)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--rounds", type=int, required=True)
    args = ap.parse_args()
    try:
        result = project(args.rows, args.rows_sha256, args.journal, args.journal_sha256,
                         args.seed, args.rounds)
    except (ValueError, OSError):
        ap.exit(2, "REFUSING: invalid, incomplete or mismatched pinned boundary inputs\n")
    print(json.dumps(result, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
