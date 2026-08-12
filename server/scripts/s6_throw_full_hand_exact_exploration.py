#!/usr/bin/env python3
"""Fresh exact replication of the S6 full-hand boss/near hypothesis.

The first four-card S6 action-set exploration found a post-hoc split worth
checking rather than trusting: full-hand boss/near throws were 3/0/1 while
partial boss/near throws were 1/4/55.  This script freezes that public action-
shape rule *before* looking at a fresh seed range and asks whether the added
action beats the best action already on the live ballot under exact perfect-
information partnership minimax.

The oracle is only a diagnostic label.  The selector itself uses actor-visible
information (the action is a boss/near source and consumes the whole hand),
but this result cannot authorize a whole-game run, policy, promotion, training,
or deployment.  A positive result only motivates a treatment/null DEV screen.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
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
from shengji.engine import combos, fast  # noqa: E402


CAPTURE_SCHEMA = "s6-throw-full-hand-exact-capture-v1"
RESULT_SCHEMA = "s6-throw-full-hand-exact-result-v1"
ROW_SCHEMA = "s6-throw-full-hand-exact-row-v1"
SEED0 = 433_000_000
MAX_DEALS = 200_000
HAND_CARDS = 4
ROLE_QUOTA = 64
ROLES = ("attacker", "defender")
Z_ONE_SIDED_95 = 1.6448536269514722
PROGRESS_EVERY_DEALS = 2_000
PROGRESS_EVERY_ROWS = 8


class FullHandRefused(RuntimeError):
    """The bounded exploration cannot support its stated diagnostic."""


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
        "exploration": SCRIPT,
        "base_exact_shape": BASE.SCRIPT,
        "throw_source": SERVER / "shengji/ai/throw_sourcing.py",
        "mcbot": SERVER / "shengji/ai/mcbot.py",
        "memory": SERVER / "shengji/ai/memory.py",
        "heuristic": SERVER / "shengji/ai/heuristic.py",
        "endgame": SERVER / "shengji/ai/endgame.py",
        "round": SERVER / "shengji/engine/round.py",
        "game": SERVER / "shengji/engine/game.py",
    }
    if fast.HAVE_FAST and fast._fast is not None:
        paths["fast_binary"] = Path(fast._fast.__file__).resolve()
    return {name: sha256(path) for name, path in sorted(paths.items())}


def runtime_snapshot() -> dict[str, object]:
    return {
        "host": platform.node(),
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "python_executable": str(Path(sys.executable).resolve()),
        "fast_active": bool(
            fast.HAVE_FAST and fast._fast is not None
            and combos.decompose is fast.decompose),
        "fast_binary_sha256": (
            sha256(Path(fast._fast.__file__).resolve())
            if fast.HAVE_FAST and fast._fast is not None else None),
    }


def action_key(cards) -> tuple[str, ...]:
    return tuple(sorted(cards))


def qualifying_candidates(rnd, seat: int) -> dict[str, object] | None:
    """Return live and fresh full-hand boss/near actions at a four-card lead."""
    if (rnd.phase != "play" or rnd.trick is None or rnd.trick.plays
            or rnd.turn != seat or max(map(len, rnd.hands)) != HAND_CARDS
            or len(rnd.hands[seat]) != HAND_CARDS):
        return None
    live = BASE.make_bot("mc-s0-report-lcb", seed=0)._candidates(rnd, seat)
    live_keys = {action_key(action) for action in live}
    added = []
    for candidate in BASE.structured_throw_ballot(rnd, seat).candidates:
        if (BASE.candidate_stratum(candidate.sources) != "boss_near"
                or len(candidate.cards) != len(rnd.hands[seat])
                or candidate.cards in live_keys):
            continue
        added.append(candidate.record())
    if not added:
        return None
    return {
        "live_candidates": [list(action) for action in live],
        "added_candidates": added,
    }


def capture_population(*, seed0: int = SEED0, max_deals: int = MAX_DEALS,
                       role_quota: int = ROLE_QUOTA) -> dict:
    """Select a balanced fresh population before computing any outcome."""
    if (isinstance(role_quota, bool) or not isinstance(role_quota, int)
            or role_quota < 1):
        raise ValueError("role_quota must be a positive integer")
    accepted = Counter()
    rows = []
    scanned = 0
    for offset in range(max_deals):
        if all(accepted[role] == role_quota for role in ROLES):
            break
        seed = seed0 + offset
        scanned += 1
        rnd, actors = BASE._start_round(seed)
        selected = None
        while rnd.phase == "play":
            seat = rnd.turn
            if seat is None:
                raise FullHandRefused("play state lost its acting seat")
            source = qualifying_candidates(rnd, seat)
            if source is not None:
                role = "attacker" if rnd.is_attacker(seat) else "defender"
                if accepted[role] < role_quota:
                    selected = {
                        "schema": CAPTURE_SCHEMA,
                        "state_id": f"{seed}:{len(rnd.history)}:{seat}",
                        "deal_seed": seed,
                        "completed_tricks": len(rnd.history),
                        "seat": seat,
                        "role": role,
                        "hand_cards": HAND_CARDS,
                        "live_candidates": source["live_candidates"],
                        "added_candidates": source["added_candidates"],
                        "selector": "full-hand boss/near source absent from live ballot",
                        "score_free_selection": True,
                    }
                    break
            rnd.play(seat, actors[seat].decide_play(rnd, seat))
        if selected is not None:
            rows.append(selected)
            accepted[selected["role"]] += 1
        if scanned % PROGRESS_EVERY_DEALS == 0:
            print(json.dumps({
                "event": "s6-full-hand-capture-progress-v1",
                "deals_scanned": scanned,
                "attacker_states": accepted["attacker"],
                "defender_states": accepted["defender"],
                "role_quota": role_quota,
            }, sort_keys=True), flush=True)
    counts = {role: accepted[role] for role in ROLES}
    return {
        "schema": CAPTURE_SCHEMA,
        "git": git("rev-parse", "HEAD"),
        "source_sha256s": source_sha256s(),
        "runtime": runtime_snapshot(),
        "score_free": True,
        "outcomes_computed": False,
        "seed0": seed0,
        "max_deals": max_deals,
        "deals_scanned": scanned,
        "hand_cards": HAND_CARDS,
        "role_quota": role_quota,
        "role_counts": counts,
        "complete": all(counts[role] == role_quota for role in ROLES),
        "selection": (
            "at most one lead per fresh deal; actor's entire four-card hand "
            "is a new boss/near candidate; roles balanced before scoring"),
        "rows": rows,
        "strength_claim": False,
        "whole_game_execution_authorized": False,
    }


def replay_capture(record: dict):
    rnd, actors = BASE._start_round(int(record["deal_seed"]))
    target = int(record["completed_tricks"])
    while rnd.phase == "play":
        seat = rnd.turn
        if (seat == record["seat"] and len(rnd.history) == target
                and rnd.trick is not None and not rnd.trick.plays):
            source = qualifying_candidates(rnd, seat)
            if source is None:
                raise FullHandRefused("captured full-hand source disappeared")
            if (source["live_candidates"] != record["live_candidates"]
                    or source["added_candidates"]
                    != record["added_candidates"]):
                raise FullHandRefused("captured ballot/source drift")
            return rnd
        rnd.play(seat, actors[seat].decide_play(rnd, seat))
    raise FullHandRefused("captured lead was not replayed")


def score_capture(record: dict) -> dict:
    rnd = replay_capture(record)
    seat = int(record["seat"])
    live = [BASE._score_action(rnd, seat, list(action))
            for action in record["live_candidates"]]
    added = [BASE._score_action(rnd, seat, list(candidate["cards"]))
             for candidate in record["added_candidates"]]
    live_best = BASE._best(live)
    added_best = BASE._best(added)
    return {
        "schema": ROW_SCHEMA,
        "state_id": record["state_id"],
        "deal_seed": record["deal_seed"],
        "role": record["role"],
        "status": "SCORED",
        "live_candidate_count": len(live),
        "new_candidate_count": len(added),
        "live_oracle": live_best,
        "new_source_oracle": added_best,
        "signed_level_utility_delta": (
            added_best["acting_team_level_value"]
            - live_best["acting_team_level_value"]),
        "signed_point_delta": (
            added_best["acting_team_points"]
            - live_best["acting_team_points"]),
        "perfect_information_oracle": True,
        "strength_claim": False,
    }


def descriptive(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"n": 0, "mean": None, "se": None,
                "lcb_one_sided_95": None}
    mean = sum(values) / len(values)
    if len(values) < 2:
        return {"n": len(values), "mean": mean, "se": None,
                "lcb_one_sided_95": None}
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    se = math.sqrt(variance / len(values))
    return {"n": len(values), "mean": mean, "se": se,
            "lcb_one_sided_95": mean - Z_ONE_SIDED_95 * se}


def aggregate(rows: list[dict], *, role_quota: int) -> dict:
    scored = [row for row in rows if row.get("status") == "SCORED"]
    refused = [row for row in rows if row.get("status") == "REFUSED"]
    role_stats = {}
    for role in ROLES:
        values = [row for row in scored if row["role"] == role]
        role_stats[role] = {
            "level_delta": descriptive([
                row["signed_level_utility_delta"] for row in values]),
            "point_delta": descriptive([
                row["signed_point_delta"] for row in values]),
            "wins": sum(row["signed_level_utility_delta"] > 0 for row in values),
            "losses": sum(row["signed_level_utility_delta"] < 0 for row in values),
            "ties": sum(row["signed_level_utility_delta"] == 0 for row in values),
        }
    pooled = descriptive([
        row["signed_level_utility_delta"] for row in scored])
    complete = (not refused and len(scored) == role_quota * len(ROLES)
                and all(role_stats[role]["level_delta"]["n"] == role_quota
                        for role in ROLES))
    positive = bool(
        complete and pooled["lcb_one_sided_95"] is not None
        and pooled["lcb_one_sided_95"] > 0
        and all(role_stats[role]["level_delta"]["mean"] >= 0
                for role in ROLES))
    return {
        "primary": (
            "fresh exact full-hand boss/near best-new action minus exact "
            "best live-ballot action, acting-team level utility"),
        "pooled_level_delta": pooled,
        "roles": role_stats,
        "scored_rows": len(scored),
        "refused_rows": len(refused),
        "coverage_complete": complete,
        "status": (
            "ADVANCE_TO_PUBLIC_GATE_DEV_SCREEN" if positive
            else "NO_EXACT_ACTION_SET_SIGNAL"),
        "public_gate_dev_screen_design_authorized": positive,
        "whole_game_execution_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }


def validate_capture(capture: dict, *, expected_git: str) -> None:
    if (capture.get("schema") != CAPTURE_SCHEMA
            or capture.get("git") != expected_git
            or capture.get("source_sha256s") != source_sha256s()
            or capture.get("runtime") != runtime_snapshot()
            or capture.get("score_free") is not True
            or capture.get("outcomes_computed") is not False
            or capture.get("seed0") != SEED0
            or capture.get("hand_cards") != HAND_CARDS
            or capture.get("role_quota") != ROLE_QUOTA
            or capture.get("complete") is not True
            or len(capture.get("rows", [])) != ROLE_QUOTA * len(ROLES)):
        raise FullHandRefused("capture identity/design/coverage drift")


def build_result(capture: dict, *, expected_git: str) -> dict:
    validate_capture(capture, expected_git=expected_git)
    rows = []
    for index, record in enumerate(capture["rows"], 1):
        try:
            rows.append(score_capture(record))
        except Exception as exc:
            rows.append({
                "schema": ROW_SCHEMA,
                "state_id": record["state_id"],
                "deal_seed": record["deal_seed"],
                "role": record["role"],
                "status": "REFUSED",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "strength_claim": False,
            })
        if index % PROGRESS_EVERY_ROWS == 0 or index == len(capture["rows"]):
            print(json.dumps({
                "event": "s6-full-hand-score-progress-v1",
                "states_complete": index,
                "states_total": len(capture["rows"]),
            }, sort_keys=True), flush=True)
    payload = {
        "schema": RESULT_SCHEMA,
        "git": expected_git,
        "tree_dirty": bool(git("status", "--porcelain", "--untracked-files=all")),
        "source_sha256s": source_sha256s(),
        "capture_sha256": stable_digest(capture),
        "design": {
            "seed0": SEED0,
            "max_deals": MAX_DEALS,
            "hand_cards": HAND_CARDS,
            "role_quota": ROLE_QUOTA,
            "roles": list(ROLES),
            "selector": "full-hand boss/near source absent from live ballot",
            "selection_frozen_before_fresh_outcomes": True,
            "advance_rule": (
                "complete 64/role, pooled one-sided 95% LCB > 0, and no "
                "role has a negative mean"),
            "origin": (
                "post-hoc split in disjoint four-card exact-shape v1; this "
                "fresh population tests that split once"),
        },
        "capture": capture,
        "rows": rows,
        "aggregate": aggregate(rows, role_quota=ROLE_QUOTA),
        "exploration_only": True,
        "reusable_diagnostic": True,
        "training_authorized": False,
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
        raise FullHandRefused(f"refusing to overwrite {path}")
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
        raise FullHandRefused("published artifact failed exact reopen")


def require_clean_exact_git(expected_git: str) -> None:
    if git("rev-parse", "HEAD") != expected_git:
        raise FullHandRefused("Git identity drift")
    if git("status", "--porcelain", "--untracked-files=all"):
        raise FullHandRefused("exploration requires a clean tree")


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    capture = sub.add_parser("capture")
    capture.add_argument("--expected-git", required=True)
    capture.add_argument("--out", required=True)
    score = sub.add_parser("score")
    score.add_argument("--expected-git", required=True)
    score.add_argument("--capture", required=True)
    score.add_argument("--out", required=True)
    args = parser.parse_args()
    require_clean_exact_git(args.expected_git)
    if args.command == "capture":
        payload = capture_population()
        write_exclusive(Path(args.out), payload)
        print(json.dumps({
            "status": "CAPTURE_COMPLETE" if payload["complete"]
            else "CAPTURE_INCOMPLETE",
            "output_sha256": sha256(args.out),
            "role_counts": payload["role_counts"],
            "score_free": True,
        }, sort_keys=True))
        return
    capture_payload = json.loads(Path(args.capture).read_bytes())
    payload = build_result(capture_payload, expected_git=args.expected_git)
    write_exclusive(Path(args.out), payload)
    print(json.dumps({
        "status": payload["aggregate"]["status"],
        "output_sha256": sha256(args.out),
        "internal_sha256": payload["internal_sha256"],
        "aggregate": payload["aggregate"],
        "strength_claim": False,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
