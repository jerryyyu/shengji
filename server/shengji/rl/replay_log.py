"""Shared helpers for reconstructing game state from JSONL logs.

Single home for the rebuild-a-Round-from-a-log block that analysis
tooling (replay, xray, harvest/room_log, ballot_gap,
human_shards) previously each carried a copy of.
"""

from __future__ import annotations

import glob as _glob
import json
import random
from collections import defaultdict

from ..engine.round import Round

SYM = {"S": "♠", "H": "♥", "D": "♦", "C": "♣"}
EXCLUDE_PLAYERS = {"Smoke", "DeployTest", "X"}  # test scripts, not humans


def pretty(code: str) -> str:
    if code in ("BJ", "LJ"):
        return code + "o"
    return SYM.get(code[0], code[0]) + code[1:]


def pretty_cards(cards) -> str:
    return " ".join(pretty(c) for c in cards)


def group_rounds(path: str) -> dict[int, list[dict]]:
    """Round number -> event list, in file order."""
    by_round: dict[int, list[dict]] = defaultdict(list)
    for line in open(path):
        e = json.loads(line)
        by_round[e["round"]].append(e)
    return by_round


def rebuild_round(evs: list[dict]) -> Round | None:
    """Reconstruct a Round to the start of play from one round's events.
    Returns None if the log lacks setup events (partial round)."""
    rs = next((e for e in evs if e["e"] == "round_start"), None)
    tr = next((e for e in evs if e["e"] == "trump"), None)
    bury = next((e for e in evs if e["e"] == "bury"), None)
    if not rs or not tr or not bury:
        return None
    rnd = Round(rs["trump_rank"], rs["banker"], random.Random(0))
    rnd.deck = rs["deck"]
    rnd.hands = [[], [], [], []]
    rnd._deal_pos = 0
    rnd.phase = "deal"
    rnd.kitty = rs["deck"][100:]
    while rnd.phase == "deal":
        rnd.deal_next()
    for e in evs:
        if e["e"] == "declare":
            rnd.declare(e["seat"], e["cards"])
    rnd.finalize_declare()
    rnd.bury(tr["banker"], bury["cards"])
    return rnd


def iter_human_decisions(paths):
    """Yield (rnd, seat, human_cards) at each genuine human play decision
    across the given log paths/globs. Known test-script seats excluded."""
    expanded: list[str] = []
    for p in paths if isinstance(paths, (list, tuple)) else [paths]:
        expanded.extend(_glob.glob(p) if any(ch in p for ch in "*?[") else [p])
    for path in expanded:
        excluded_seats: set = set()
        try:
            first = next((e for e in map(json.loads, open(path))
                          if e.get("e") == "round_start"), None)
        except (OSError, json.JSONDecodeError):
            continue
        if first:
            excluded_seats = {p["seat"] for p in first["players"]
                              if p["name"] in EXCLUDE_PLAYERS}
        for rno, evs in sorted(group_rounds(path).items()):
            try:
                rnd = rebuild_round(evs)
                if rnd is None:
                    continue
                for e in evs:
                    if e["e"] != "play" or rnd.phase != "play":
                        continue
                    if (e.get("bot") is False and rnd.turn == e["seat"]
                            and e["seat"] not in excluded_seats):
                        yield rnd, e["seat"], e["cards"]
                    rnd.play(e["seat"], e["cards"])
            except Exception:
                continue  # partial/corrupt round
