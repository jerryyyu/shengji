#!/usr/bin/env python3
"""Score-free census of broad S6 sourcing versus boss/near search spend."""
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

from shengji.ai.heuristic import HeuristicBot  # noqa: E402
from shengji.ai.throw_policy import make_s6_throw_bot  # noqa: E402
from shengji.ai.throw_search_gate import make_s6_boss_near_bot  # noqa: E402
from shengji.ai.throw_sourcing import BOSS_NEAR_BUNDLE  # noqa: E402
from shengji.engine.game import Game  # noqa: E402


SCHEMA = "s6-boss-near-search-prevalence-v1"
SEED0 = 446_000_000
ROUNDS = 512
SCORE_FIELDS = frozenset({
    "attacker_points", "banker", "level_change", "level_utility", "outcome",
    "outcomes", "points", "utility", "win_rate", "winner", "winner_team",
    "won", "wins", "losses",
})


class CensusRefused(RuntimeError):
    """The source/gate census cannot support its score-free description."""


def sha256(path: os.PathLike | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def stable_digest(value) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, check=True,
        capture_output=True, text=True,
    ).stdout.strip()


def phase_band(completed_tricks: int) -> str:
    if completed_tricks <= 7:
        return "early"
    if completed_tricks <= 16:
        return "mid"
    return "late"


def _assert_score_free(value) -> None:
    if isinstance(value, dict):
        overlap = SCORE_FIELDS.intersection(value)
        if overlap:
            raise CensusRefused(
                "score-free census contains outcome fields: "
                + ", ".join(sorted(overlap)))
        for child in value.values():
            _assert_score_free(child)
    elif isinstance(value, list):
        for child in value:
            _assert_score_free(child)


def _start_round(seed: int):
    rnd = Game(random.Random(seed)).start_round()
    actors = [HeuristicBot() for _ in range(4)]
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
        raise CensusRefused("fresh deal has no banker")
    rnd.bury(rnd.banker, actors[rnd.banker].decide_bury(rnd, rnd.banker))
    return rnd, actors


def _source_sha256s() -> dict[str, str]:
    paths = {
        "census": SCRIPT,
        "gate": SERVER / "shengji/ai/throw_search_gate.py",
        "policy": SERVER / "shengji/ai/throw_policy.py",
        "source": SERVER / "shengji/ai/throw_sourcing.py",
        "mcbot": SERVER / "shengji/ai/mcbot.py",
        "memory": SERVER / "shengji/ai/memory.py",
        "round": SERVER / "shengji/engine/round.py",
    }
    return {name: sha256(path) for name, path in sorted(paths.items())}


def run_census(*, seed0: int = SEED0, rounds: int = ROUNDS) -> dict:
    if isinstance(seed0, bool) or not isinstance(seed0, int) or seed0 < 0:
        raise CensusRefused("seed0 must be a non-negative integer")
    if isinstance(rounds, bool) or not isinstance(rounds, int) \
            or not 1 <= rounds <= 4096:
        raise CensusRefused("rounds must be in [1, 4096]")
    broad = make_s6_throw_bot(treatment=True, seed=0)
    gated = make_s6_boss_near_bot(treatment=True, seed=0)
    rows = []
    totals = Counter()
    by_phase = {phase: Counter() for phase in ("early", "mid", "late")}
    by_role = {role: Counter() for role in ("attacker", "defender")}
    for offset in range(rounds):
        deal_seed = seed0 + offset
        rnd, actors = _start_round(deal_seed)
        while rnd.phase == "play":
            seat = rnd.turn
            if seat is None or rnd.trick is None:
                raise CensusRefused("fresh round lost active play state")
            if not rnd.trick.plays:
                broad_plan = broad._source_plan(rnd, seat)
                gated_plan = gated._source_plan(rnd, seat)
                if broad_plan["ballot"].record() != gated_plan["ballot"].record():
                    raise CensusRefused("search gate changed source coverage")
                broad_keys = set(broad_plan["added_keys"])
                gated_keys = set(gated_plan["added_keys"])
                if not gated_keys.issubset(broad_keys):
                    raise CensusRefused("gated suffix escaped broad additions")
                boss_source = sum(
                    BOSS_NEAR_BUNDLE in candidate.sources
                    for candidate in broad_plan["ballot"].candidates)
                phase = phase_band(len(rnd.history))
                role = "attacker" if rnd.is_attacker(seat) else "defender"
                row = {
                    "state_id": stable_digest({
                        "deal_seed": deal_seed,
                        "completed_tricks": len(rnd.history),
                        "seat": seat,
                    }),
                    "deal_seed": deal_seed,
                    "completed_tricks": len(rnd.history),
                    "seat": seat,
                    "phase": phase,
                    "role": role,
                    "eligible": bool(broad_plan["ballot"].eligible_suits),
                    "source_candidates": len(broad_plan["ballot"].candidates),
                    "boss_near_source_candidates": boss_source,
                    "broad_new_candidates": len(broad_keys),
                    "gated_new_candidates": len(gated_keys),
                    "broad_trigger": bool(broad_keys),
                    "gated_trigger": bool(gated_keys),
                }
                rows.append(row)
                for bucket in (totals, by_phase[phase], by_role[role]):
                    bucket["leads"] += 1
                    bucket["eligible_leads"] += int(row["eligible"])
                    bucket["source_candidates"] += row["source_candidates"]
                    bucket["boss_near_source_candidates"] += boss_source
                    bucket["broad_new_candidates"] += len(broad_keys)
                    bucket["gated_new_candidates"] += len(gated_keys)
                    bucket["broad_triggers"] += int(bool(broad_keys))
                    bucket["gated_triggers"] += int(bool(gated_keys))
            rnd.play(seat, actors[seat].decide_play(rnd, seat))
        if (offset + 1) % 64 == 0:
            print(json.dumps({
                "event": "s6-boss-near-prevalence-progress-v1",
                "rounds_complete": offset + 1,
                "rounds_total": rounds,
                "leads": totals["leads"],
                "broad_triggers": totals["broad_triggers"],
                "gated_triggers": totals["gated_triggers"],
            }, sort_keys=True), flush=True)

    def plain(counter: Counter) -> dict[str, int]:
        return {name: int(counter[name]) for name in (
            "leads", "eligible_leads", "source_candidates",
            "boss_near_source_candidates", "broad_new_candidates",
            "gated_new_candidates", "broad_triggers", "gated_triggers")}

    aggregate = {
        **plain(totals),
        "gated_trigger_fraction_of_broad": (
            totals["gated_triggers"] / totals["broad_triggers"]
            if totals["broad_triggers"] else 0.0),
        "second_search_trigger_reduction": (
            1.0 - totals["gated_triggers"] / totals["broad_triggers"]
            if totals["broad_triggers"] else 0.0),
        "by_phase": {key: plain(value) for key, value in by_phase.items()},
        "by_role": {key: plain(value) for key, value in by_role.items()},
    }
    payload = {
        "schema": SCHEMA,
        "git": git("rev-parse", "HEAD"),
        "tree_dirty": bool(git("status", "--porcelain")),
        "runtime": {
            "hostname": platform.node(),
            "python": platform.python_version(),
            "executable": str(Path(sys.executable).resolve()),
        },
        "source_sha256s": _source_sha256s(),
        "design": {
            "seed0": seed0,
            "rounds": rounds,
            "selection": "all natural leads in consecutive fresh heuristic rounds",
            "source_coverage": "unchanged broad early/mid/late S6 ballot",
            "search_gate": "genuinely new boss/near-boss bundles only",
            "score_free": True,
        },
        "rows": rows,
        "aggregate": aggregate,
        "score_free": True,
        "outcomes_published": False,
        "exploration_only": True,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    _assert_score_free(payload)
    payload["internal_sha256"] = stable_digest(payload)
    return payload


def write_exclusive(path: Path, payload: dict) -> None:
    partial = Path(str(path) + ".partial")
    if os.path.lexists(path) or os.path.lexists(partial):
        raise CensusRefused("refusing to overwrite S6 prevalence artifact")
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(payload, sort_keys=True, separators=(",", ":"))
           + "\n").encode()
    with partial.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    os.link(partial, path)
    partial.unlink()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--seed0", type=int, default=SEED0)
    parser.add_argument("--rounds", type=int, default=ROUNDS)
    args = parser.parse_args()
    payload = run_census(seed0=args.seed0, rounds=args.rounds)
    write_exclusive(Path(args.out), payload)
    print(json.dumps({
        "status": "COMPLETE_SCORE_FREE_EXPLORATION",
        "aggregate": payload["aggregate"],
        "output_sha256": sha256(args.out),
        "internal_sha256": payload["internal_sha256"],
    }, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
