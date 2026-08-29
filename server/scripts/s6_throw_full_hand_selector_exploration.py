#!/usr/bin/env python3
"""Can the actor-visible report-LCB gate spend the proven S6 opportunity?

The fresh full-hand exact diagnostic proved that the new boss/near action has
value when a perfect-information oracle chooses it.  That does not imply a
real bot can recognize the good states.  This reusable-DEV diagnostic replays
the same public 128 states, runs the literal champion-anchored S6 gate under
four independent search streams per state, and exact-scores the action it
actually chose against the incumbent it actually displaced.

This is deliberately a fitting/selection diagnostic on an already-opened
population, not fresh strength evidence.  A positive result may justify the
design of a fresh whole-game packet; it cannot authorize that run, training,
promotion, or deployment.
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
from pathlib import Path


SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[1]
REPO = SERVER.parent
sys.path.insert(0, str(SERVER))
sys.path.insert(0, str(SCRIPT.parent))

import s6_throw_full_hand_exact_exploration as EXACT  # noqa: E402
from shengji.ai.throw_full_hand_gate import (  # noqa: E402
    FULL_HAND_BOSS_NEAR_GATE,
    make_s6_full_hand_bot,
)
from shengji.engine import combos, fast  # noqa: E402


SCHEMA = "s6-throw-full-hand-selector-exploration-v1"
ROW_SCHEMA = "s6-throw-full-hand-selector-state-v1"
DECISION_SCHEMA = "s6-throw-full-hand-selector-decision-v1"
CAPTURE = SERVER / "tests/data/s6_throw_full_hand_exact_capture.v1.json"
ORACLE_RESULT = SERVER / "tests/data/s6_throw_full_hand_exact_result.v1.json"
CAPTURE_SHA256 = (
    "99debb547d8ba92456c9d9d8a7e36dd49fdc061b589b063ddcd86e3ab2de5708")
ORACLE_RESULT_SHA256 = (
    "946b029c0922a902ad5974977cef4a8a30ac245430563f57483c25597d65cebe")
MC_REPLICATES = 4
DECISION_SEED0 = 435_000_000
Z_ONE_SIDED_95 = 1.6448536269514722
PROGRESS_EVERY_STATES = 8


class SelectorRefused(RuntimeError):
    """The bounded selector diagnostic cannot support its stated result."""


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


def action_key(cards) -> tuple[str, ...]:
    return tuple(sorted(cards))


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


def source_sha256s() -> dict[str, str]:
    paths = {
        "selector": SCRIPT,
        "gate": SERVER / "shengji/ai/throw_full_hand_gate.py",
        "throw_policy": SERVER / "shengji/ai/throw_policy.py",
        "throw_source": SERVER / "shengji/ai/throw_sourcing.py",
        "mcbot": SERVER / "shengji/ai/mcbot.py",
        "memory": SERVER / "shengji/ai/memory.py",
        "exact_diagnostic": EXACT.SCRIPT,
        "endgame": SERVER / "shengji/ai/endgame.py",
        "round": SERVER / "shengji/engine/round.py",
    }
    if fast.HAVE_FAST and fast._fast is not None:
        paths["fast_binary"] = Path(fast._fast.__file__).resolve()
    return {name: sha256(path) for name, path in sorted(paths.items())}


def load_public_population() -> tuple[list[dict], dict[str, dict]]:
    """Open only the pinned, already-public DEV diagnostic population."""
    if sha256(CAPTURE) != CAPTURE_SHA256:
        raise SelectorRefused("full-hand capture bytes drifted")
    if sha256(ORACLE_RESULT) != ORACLE_RESULT_SHA256:
        raise SelectorRefused("full-hand oracle-result bytes drifted")
    capture = json.loads(CAPTURE.read_bytes())
    result = json.loads(ORACLE_RESULT.read_bytes())
    if (capture.get("schema") != EXACT.CAPTURE_SCHEMA
            or capture.get("score_free") is not True
            or capture.get("complete") is not True
            or len(capture.get("rows", [])) != 128):
        raise SelectorRefused("capture schema/coverage drifted")
    oracle = {row["state_id"]: row for row in result.get("rows", [])}
    if (len(oracle) != len(capture["rows"])
            or any(row.get("status") != "SCORED" for row in oracle.values())
            or {row["state_id"] for row in capture["rows"]} != set(oracle)):
        raise SelectorRefused("oracle rows do not match capture population")
    return capture["rows"], oracle


def _score_summary(scored: dict) -> dict[str, object]:
    return {
        "submitted": list(scored["submitted"]),
        "actual": list(scored["actual"]),
        "throw_failed": bool(scored["throw_failed"]),
        "final_attacker_points": int(scored["final_attacker_points"]),
        "acting_team_points": int(scored["acting_team_points"]),
        "acting_team_level_value": float(scored["acting_team_level_value"]),
        "exact_nodes": int(scored["exact_nodes"]),
        "exact_cache_hits": int(scored["exact_cache_hits"]),
    }


def score_state(record: dict, oracle: dict, *, state_index: int,
                replicates: int = MC_REPLICATES) -> dict:
    if replicates < 1:
        raise ValueError("replicates must be positive")
    if record["state_id"] != oracle["state_id"]:
        raise SelectorRefused("state/oracle identity mismatch")
    if len(record.get("added_candidates", [])) != 1:
        raise SelectorRefused("selector v1 requires exactly one S6 addition")
    rnd = EXACT.replay_capture(record)
    seat = int(record["seat"])
    live_keys = {action_key(cards) for cards in record["live_candidates"]}
    added_key = action_key(record["added_candidates"][0]["cards"])
    exact_cache: dict[tuple[str, ...], dict] = {}

    def exact_score(cards) -> dict:
        key = action_key(cards)
        if key not in exact_cache:
            exact_cache[key] = EXACT.BASE._score_action(rnd, seat, list(cards))
        return exact_cache[key]

    decisions = []
    for replicate in range(replicates):
        decision_seed = DECISION_SEED0 + state_index * MC_REPLICATES + replicate
        bot = make_s6_full_hand_bot(treatment=True, seed=decision_seed)
        selected = list(bot.decide_play(rnd, seat))
        source = bot.last_s6_throw_record
        decision = bot.last_decision_record
        if (source is None or decision is None
                or source.get("search_gate") != FULL_HAND_BOSS_NEAR_GATE
                or source.get("trigger") is not True
                or source.get("searched") is not True
                or source.get("searched_candidate_count") != 1
                or source.get("exact_work_complete") is not True
                or decision.get("work", {}).get("complete") is not True):
            raise SelectorRefused("full-hand gate did not complete exact work")
        incumbent = list(source.get("incumbent_played") or [])
        if action_key(incumbent) not in live_keys:
            raise SelectorRefused("gate incumbent escaped the live ballot")
        selected_key = action_key(selected)
        if selected_key not in {action_key(incumbent), added_key}:
            raise SelectorRefused("gate selection escaped incumbent plus S6 action")
        incumbent_score = exact_score(incumbent)
        selected_score = exact_score(selected)
        report = decision.get("report_fold") or {}
        decisions.append({
            "schema": DECISION_SCHEMA,
            "replicate": replicate,
            "decision_seed": decision_seed,
            "incumbent": _score_summary(incumbent_score),
            "selected": _score_summary(selected_score),
            "override": selected_key != action_key(incumbent),
            "signed_level_utility_delta": (
                selected_score["acting_team_level_value"]
                - incumbent_score["acting_team_level_value"]),
            "signed_point_delta": (
                selected_score["acting_team_points"]
                - incumbent_score["acting_team_points"]),
            "decision_reason": decision.get("reason"),
            "report_worlds": report.get("worlds"),
            "report_gap": report.get("gap"),
            "report_se": report.get("se"),
            "report_statistic": report.get("statistic"),
            "exact_work_complete": True,
        })
    return {
        "schema": ROW_SCHEMA,
        "status": "SCORED",
        "state_id": record["state_id"],
        "deal_seed": record["deal_seed"],
        "role": record["role"],
        "oracle_new_minus_best_live_level_delta": (
            oracle["signed_level_utility_delta"]),
        "oracle_new_minus_best_live_point_delta": oracle["signed_point_delta"],
        "replicates": replicates,
        "decisions": decisions,
        "cluster_mean_level_delta": sum(
            row["signed_level_utility_delta"] for row in decisions) / replicates,
        "cluster_mean_point_delta": sum(
            row["signed_point_delta"] for row in decisions) / replicates,
        "override_count": sum(row["override"] for row in decisions),
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


def aggregate(rows: list[dict], *, expected_states: int,
              replicates: int) -> dict:
    scored = [row for row in rows if row.get("status") == "SCORED"]
    refused = [row for row in rows if row.get("status") == "REFUSED"]
    pooled = descriptive([row["cluster_mean_level_delta"] for row in scored])
    roles = {
        role: descriptive([
            row["cluster_mean_level_delta"] for row in scored
            if row["role"] == role
        ]) for role in EXACT.ROLES
    }
    decisions = [decision for row in scored for decision in row["decisions"]]
    override_decisions = [row for row in decisions if row["override"]]
    by_oracle_label = {}
    for label, predicate in (
            ("positive", lambda value: value > 0),
            ("tie", lambda value: value == 0),
            ("negative", lambda value: value < 0)):
        states = [row for row in scored if predicate(
            row["oracle_new_minus_best_live_level_delta"])]
        by_oracle_label[label] = {
            "states": len(states),
            "decisions": len(states) * replicates,
            "overrides": sum(row["override_count"] for row in states),
        }
    complete = bool(
        not refused and len(scored) == expected_states
        and len(decisions) == expected_states * replicates
        and all(row.get("exact_work_complete") is True for row in decisions))
    advances = bool(
        complete and override_decisions
        and pooled["lcb_one_sided_95"] is not None
        and pooled["lcb_one_sided_95"] > 0
        and all(roles[role]["mean"] is not None
                and roles[role]["mean"] >= 0 for role in EXACT.ROLES))
    return {
        "primary": (
            "mean exact acting-team level delta of actor-visible S6 gate "
            "versus its own literal champion incumbent; state is cluster"),
        "pooled_state_cluster_level_delta": pooled,
        "role_state_cluster_level_delta": roles,
        "scored_states": len(scored),
        "refused_states": len(refused),
        "decisions": len(decisions),
        "overrides": len(override_decisions),
        "override_states": sum(row["override_count"] > 0 for row in scored),
        "beneficial_overrides": sum(
            row["signed_level_utility_delta"] > 0 for row in override_decisions),
        "harmful_overrides": sum(
            row["signed_level_utility_delta"] < 0 for row in override_decisions),
        "neutral_overrides": sum(
            row["signed_level_utility_delta"] == 0 for row in override_decisions),
        "by_oracle_opportunity": by_oracle_label,
        "coverage_complete": complete,
        "status": (
            "ADVANCE_TO_FRESH_WHOLE_GAME_PACKET_DESIGN" if advances
            else "SELECTOR_NOT_READY_FOR_FRESH_WHOLE_GAME"),
        "fresh_whole_game_packet_design_authorized": advances,
        "whole_game_execution_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }


def build_result(*, expected_git: str) -> dict:
    capture_rows, oracle = load_public_population()
    rows = []
    for index, record in enumerate(capture_rows):
        try:
            rows.append(score_state(
                record, oracle[record["state_id"]], state_index=index))
        except Exception as exc:
            rows.append({
                "schema": ROW_SCHEMA,
                "status": "REFUSED",
                "state_id": record["state_id"],
                "deal_seed": record["deal_seed"],
                "role": record["role"],
                "error_type": type(exc).__name__,
                "error": str(exc),
                "strength_claim": False,
            })
        if ((index + 1) % PROGRESS_EVERY_STATES == 0
                or index + 1 == len(capture_rows)):
            print(json.dumps({
                "event": "s6-full-hand-selector-progress-v1",
                "states_complete": index + 1,
                "states_total": len(capture_rows),
                "refused_states": sum(
                    row.get("status") == "REFUSED" for row in rows),
            }, sort_keys=True), flush=True)
    payload = {
        "schema": SCHEMA,
        "git": expected_git,
        "tree_dirty": bool(git("status", "--porcelain", "--untracked-files=all")),
        "source_sha256s": source_sha256s(),
        "runtime": runtime_snapshot(),
        "design": {
            "population": "reusable opened S6 full-hand exact DEV states",
            "capture_sha256": CAPTURE_SHA256,
            "oracle_result_sha256": ORACLE_RESULT_SHA256,
            "states": len(capture_rows),
            "mc_replicates_per_state": MC_REPLICATES,
            "decision_seed0": DECISION_SEED0,
            "selector": (
                "literal report-LCB champion plus one actor-visible full-hand "
                "boss/near candidate"),
            "cluster_unit": "state; four MC streams averaged within state",
            "advance_rule": (
                "complete coverage, at least one override, state-cluster "
                "one-sided 95% LCB > 0, and nonnegative mean in both roles"),
            "exploration_tier": True,
            "fresh_strength_evidence": False,
        },
        "rows": rows,
        "aggregate": aggregate(
            rows, expected_states=len(capture_rows), replicates=MC_REPLICATES),
        "reusable_diagnostic": True,
        "training_authorized": False,
        "whole_game_execution_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    payload["internal_sha256"] = stable_digest(payload)
    return payload


def require_clean_exact_git(expected_git: str) -> None:
    if git("rev-parse", "HEAD") != expected_git:
        raise SelectorRefused("Git identity drift")
    if git("status", "--porcelain", "--untracked-files=all"):
        raise SelectorRefused("selector diagnostic requires a clean tree")


def write_exclusive(path: Path, payload: dict) -> None:
    partial = Path(str(path) + ".partial")
    if os.path.lexists(path) or os.path.lexists(partial):
        raise SelectorRefused(f"refusing to overwrite {path}")
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
        raise SelectorRefused("published selector result failed exact reopen")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-git", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    require_clean_exact_git(args.expected_git)
    payload = build_result(expected_git=args.expected_git)
    write_exclusive(Path(args.out), payload)
    print(json.dumps({
        "status": payload["aggregate"]["status"],
        "output_sha256": sha256(args.out),
        "internal_sha256": payload["internal_sha256"],
        "aggregate": payload["aggregate"],
        "strength_claim": False,
    }, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
