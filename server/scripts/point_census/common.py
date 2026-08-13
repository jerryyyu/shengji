"""Shared, read-only core for the point-management census scripts.

Every script binds its inputs to an explicit ordered manifest (content SHAs,
counts) and emits exactly one canonical JSON document on stdout.  Nothing here
writes files, launches jobs, or carries any review/run authority.
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import platform
import subprocess
import sys
from pathlib import Path

from shengji.ai.heuristic import HeuristicBot
from shengji.ai.memory import Memory
from shengji.engine.cards import TRUMP, points
from shengji.rl.actions import enumerate_actions
from shengji.rl.replay_log import EXCLUDE_PLAYERS, group_rounds, rebuild_round

MANIFEST_SCHEMA = "point-census-input-manifest-v1"
ALLOWED_USE = (
    "behavioural-cloning-control-design", "proposal-source",
    "teacher-disagreement-mining", "counterfactual-pilot-design",
)
_HB = HeuristicBot()


def canonical(value) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"))
            + "\n").encode()


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def emit(value) -> None:
    sys.stdout.buffer.write(canonical(value))


def identity_receipt(manifest: dict) -> dict:
    """Score-free provenance stamp bound into every census output."""
    try:
        git = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True,
            stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        git = "UNKNOWN"
    return {
        "manifest_sha256": sha256_bytes(canonical(manifest)),
        "source_git": git,
        "python": platform.python_version(),
        "platform": platform.platform(),
    }


def build_manifest(logs_dir: str) -> dict:
    rows = []
    for path in sorted(Path(logs_dir).glob("*.jsonl")):
        raw = path.read_bytes()
        rounds = plays = 0
        for line in raw.splitlines():
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            rounds += event.get("e") == "round_start"
            plays += event.get("e") == "play"
        rows.append({"name": path.name, "sha256": sha256_bytes(raw),
                     "bytes": len(raw), "rounds": rounds, "plays": plays})
    if not rows:
        raise SystemExit(f"REFUSED: no .jsonl inputs under {logs_dir}")
    return {
        "schema": MANIFEST_SCHEMA,
        "allowed_use": list(ALLOWED_USE),
        "files": rows,
        "totals": {"files": len(rows),
                   "rounds": sum(r["rounds"] for r in rows),
                   "plays": sum(r["plays"] for r in rows)},
    }


def load_validated_manifest(manifest_path: str, logs_dir: str) -> tuple[dict, list[Path]]:
    """Validate the frozen manifest against on-disk inputs; refuse any drift."""
    manifest = json.loads(Path(manifest_path).read_bytes())
    if manifest.get("schema") != MANIFEST_SCHEMA or not manifest.get("files"):
        raise SystemExit("REFUSED: manifest schema drift")
    ordered = []
    for row in manifest["files"]:
        path = Path(logs_dir) / row["name"]
        try:
            raw = path.read_bytes()
        except OSError:
            raise SystemExit(f"REFUSED: manifest input missing: {row['name']}")
        if sha256_bytes(raw) != row["sha256"] or len(raw) != row["bytes"]:
            raise SystemExit(f"REFUSED: manifest input drift: {row['name']}")
        ordered.append(path)
    return manifest, ordered


def iter_decisions(ordered_paths):
    """Yield (file, round_no, event_index, rnd, seat, human_cards) in
    manifest order at each genuine human play decision."""
    for path in ordered_paths:
        try:
            first = next((json.loads(l) for l in open(path)
                          if json.loads(l).get("e") == "round_start"), None)
        except (OSError, json.JSONDecodeError):
            raise SystemExit(f"REFUSED: unreadable input {path}")
        if not first:
            continue
        excluded = {p["seat"] for p in first["players"]
                    if p["name"] in EXCLUDE_PLAYERS}
        for rno, evs in sorted(group_rounds(str(path)).items()):
            rnd = rebuild_round(evs)
            if rnd is None:
                continue
            plays = [e for e in evs if e["e"] == "play"]
            for index, e in enumerate(plays):
                seat, cards = e["seat"], e["cards"]
                if (rnd.phase == "play" and not e.get("bot")
                        and seat not in excluded):
                    yield path.name, rno, index, rnd, seat, list(cards)
                try:
                    rnd.play(seat, list(cards))
                except Exception:
                    break


def decision_key(manifest_sha: str, file: str, rno: int, index: int) -> int:
    """Stable per-decision seed independent of iteration order."""
    raw = f"{manifest_sha}:{file}:{rno}:{index}".encode()
    return int.from_bytes(hashlib.sha256(raw).digest()[:4], "big")


def trick_context(rnd, seat):
    """(is_lead, winning_play, partner_winning, trick_points, seats_to_act)."""
    t = rnd.trick
    if t is None or not t.plays:
        return True, None, False, 0, []
    win_seat, inc_suit, inc_top = _HB._current_winner(rnd)
    winning = next(p for p in t.plays if p.seat == win_seat)
    tpts = sum(points(c) for tp in t.plays for c in tp.cards)
    order = [(t.leader + k) % 4 for k in range(4)]
    played = {p.seat for p in t.plays}
    to_act = [s for s in order if s not in played and s != seat]
    return False, (winning, inc_suit, inc_top), win_seat % 2 == seat % 2, tpts, to_act


def legal_point_actions(rnd, seat):
    """Legal follow actions carrying points, via the engine ballot."""
    try:
        actions = enumerate_actions(rnd, seat, exhaustive_follows=True)
    except Exception:
        raise SystemExit("REFUSED: legality enumeration failed")
    return [a for a in actions if sum(points(c) for c in a) > 0]


def classify_boss(rnd, seat, winning_play, inc_suit, inc_top, to_act):
    """Public-info incumbent classification.

    literal   — the rollout gate's own predicate (trump or top plain rank).
    inferred  — not literal, but Memory (public info) proves no unseen card
                of the incumbent's shape beats it; `strict` additionally
                requires no ruff risk from the seats still to act.
    open      — neither.  Multi-component incumbents are labeled complex.
    """
    o = rnd.ordering
    literal = inc_suit == TRUMP or inc_top >= len(o.plain_ranks) - 1
    cards = winning_play.cards
    if literal:
        return "literal", True
    mem = Memory(rnd, seat)
    if len(cards) == 1:
        boss = mem.is_boss(cards[0])
    elif len(cards) == 2 and cards[0] == cards[1]:
        boss = mem.pair_is_boss(cards[0])
    else:
        return "complex", False
    if not boss:
        return "open", False
    lead_suit = inc_suit
    strict = not mem.ruff_risk(lead_suit, to_act)
    return ("inferred_strict" if strict else "inferred_loose"), False


def wilson(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 0.0
    p = successes / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / denom
    return round(center - half, 4), round(center + half, 4)
