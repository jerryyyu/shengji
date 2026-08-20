#!/usr/bin/env python3
"""Score-free natural-traffic census for the S6 full-hand exact stratum.

The fresh exact diagnostic established action-set value on selected four-card
states.  This census measures how often the same actor-visible rule occurs on
unselected complete heuristic trajectories, including its phase, role, hand
size, and overlap with the live ballot.  It publishes no round outcome,
utility, action choice, or strength claim.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
from collections import Counter
from pathlib import Path


SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[1]
REPO = SERVER.parent
sys.path.insert(0, str(SERVER))
sys.path.insert(0, str(SCRIPT.parent))

import s6_throw_exact_shape_exploration as BASE  # noqa: E402
from shengji.ai.throw_sourcing import BOSS_NEAR_BUNDLE  # noqa: E402
from shengji.engine import combos, fast  # noqa: E402


SCHEMA = "s6-throw-full-hand-prevalence-v1"
SEED0 = 434_000_000
DEALS = 50_000
PROGRESS_EVERY = 2_000
PHASES = ("early", "mid", "late")
ROLES = ("attacker", "defender")


class PrevalenceRefused(RuntimeError):
    """The score-free census cannot support its bounded traffic claim."""


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


def phase_band(completed_tricks: int) -> str:
    if completed_tricks <= 7:
        return "early"
    if completed_tricks <= 16:
        return "mid"
    return "late"


def action_key(cards) -> tuple[str, ...]:
    return tuple(sorted(cards))


def source_sha256s() -> dict[str, str]:
    paths = {
        "census": SCRIPT,
        "base_exact_shape": BASE.SCRIPT,
        "throw_source": SERVER / "shengji/ai/throw_sourcing.py",
        "mcbot": SERVER / "shengji/ai/mcbot.py",
        "memory": SERVER / "shengji/ai/memory.py",
        "heuristic": SERVER / "shengji/ai/heuristic.py",
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


def full_hand_additions(rnd, seat: int, *, live_bot=None) -> list[dict]:
    """Return newly sourced boss/near actions consuming every actor card."""
    if rnd.trick is None or rnd.trick.plays or rnd.turn != seat:
        return []
    if live_bot is None:
        live_bot = BASE.make_bot("mc-s0-report-lcb", seed=0)
    live = live_bot._candidates(rnd, seat)
    live_keys = {action_key(action) for action in live}
    return [
        candidate.record()
        for candidate in BASE.structured_throw_ballot(rnd, seat).candidates
        if (BOSS_NEAR_BUNDLE in candidate.sources
            and len(candidate.cards) == len(rnd.hands[seat])
            and candidate.cards not in live_keys)
    ]


def run_census(*, seed0: int = SEED0, deals: int = DEALS) -> dict:
    if (isinstance(deals, bool) or not isinstance(deals, int) or deals < 1):
        raise ValueError("deals must be a positive integer")
    totals = Counter()
    by_cell = Counter()
    by_hand_cards = Counter()
    triggered_deals = 0
    live_bot = BASE.make_bot("mc-s0-report-lcb", seed=0)
    for offset in range(deals):
        rnd, actors = BASE._start_round(seed0 + offset)
        deal_triggered = False
        while rnd.phase == "play":
            seat = rnd.turn
            if seat is None:
                raise PrevalenceRefused("play state lost its acting seat")
            if rnd.trick is not None and not rnd.trick.plays:
                totals["leads"] += 1
                additions = full_hand_additions(
                    rnd, seat, live_bot=live_bot)
                if additions:
                    role = "attacker" if rnd.is_attacker(seat) else "defender"
                    phase = phase_band(len(rnd.history))
                    totals["triggered_leads"] += 1
                    totals["new_candidates"] += len(additions)
                    by_cell[(role, phase)] += 1
                    by_hand_cards[len(rnd.hands[seat])] += 1
                    deal_triggered = True
            rnd.play(seat, actors[seat].decide_play(rnd, seat))
        triggered_deals += int(deal_triggered)
        if (offset + 1) % PROGRESS_EVERY == 0 or offset + 1 == deals:
            print(json.dumps({
                "event": "s6-full-hand-prevalence-progress-v1",
                "deals_complete": offset + 1,
                "deals_total": deals,
                "triggered_deals": triggered_deals,
                "triggered_leads": totals["triggered_leads"],
            }, sort_keys=True), flush=True)
    cells = {
        f"{role}:{phase}": int(by_cell[(role, phase)])
        for role in ROLES for phase in PHASES
    }
    payload = {
        "schema": SCHEMA,
        "git": git("rev-parse", "HEAD"),
        "tree_dirty": bool(git("status", "--porcelain", "--untracked-files=all")),
        "source_sha256s": source_sha256s(),
        "runtime": runtime_snapshot(),
        "design": {
            "seed0": seed0,
            "deals": deals,
            "trajectory": "deterministic HeuristicBot self-play",
            "selector": (
                "new boss/near source action consumes every card in the "
                "acting hand"),
            "score_free": True,
        },
        "counts": {
            "deals": deals,
            "leads": int(totals["leads"]),
            "triggered_deals": triggered_deals,
            "triggered_leads": int(totals["triggered_leads"]),
            "new_candidates": int(totals["new_candidates"]),
            "cells": cells,
            "by_hand_cards": {
                str(cards): int(count)
                for cards, count in sorted(by_hand_cards.items())
            },
        },
        "rates": {
            "triggered_deals": triggered_deals / deals,
            "triggered_leads": (
                totals["triggered_leads"] / totals["leads"]
                if totals["leads"] else 0.0),
        },
        "score_free": True,
        "outcomes_published": False,
        "exploration_only": True,
        "whole_game_execution_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    payload["internal_sha256"] = stable_digest(payload)
    return payload


def write_exclusive(path: Path, payload: dict) -> None:
    partial = Path(str(path) + ".partial")
    if os.path.lexists(path) or os.path.lexists(partial):
        raise PrevalenceRefused(f"refusing to overwrite {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(payload, sort_keys=True, separators=(",", ":"))
           + "\n").encode()
    with partial.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    os.link(partial, path)
    partial.unlink()
    if json.loads(path.read_bytes()) != payload:
        raise PrevalenceRefused("published census failed exact reopen")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-git", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    if git("rev-parse", "HEAD") != args.expected_git:
        raise SystemExit("REFUSED: Git identity drift")
    if git("status", "--porcelain", "--untracked-files=all"):
        raise SystemExit("REFUSED: census requires a clean tree")
    payload = run_census()
    write_exclusive(Path(args.out), payload)
    print(json.dumps({
        "status": "COMPLETE_SCORE_FREE_CENSUS",
        "output_sha256": sha256(args.out),
        "internal_sha256": payload["internal_sha256"],
        "counts": payload["counts"],
        "rates": payload["rates"],
        "strength_claim": False,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
