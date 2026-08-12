#!/usr/bin/env python3
"""Score-free replay of the attacker-only pair-cap gate on frozen roots.

This evaluates one new policy arm on every root in the reviewed 192-state
incremental-dose population.  It publishes actions, dose, and exact work but
never round outcomes or utilities.  The output answers a narrow exploration
question: does declining only defender pair-cap continuations protect the
known v1 reversion while retaining the two new v2 root changes?
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path


SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[1]
REPO = SERVER.parent
sys.path.insert(0, str(SERVER))
sys.path.insert(0, str(SCRIPT.parent))

import pair_cap_rollout_incremental_dose as DOSE  # noqa: E402
import pair_cap_rollout_root_audit as AUDIT  # noqa: E402
from shengji.ai.pair_cap_attacker_rollout import (  # noqa: E402
    make_pair_cap_attacker_bot,
)


SCHEMA = "pair-cap-attacker-gate-root-replay-v1"
EXPECTED_DOSE_SHA256 = (
    "f2e1d28bff52e6dee7d733d78eedb9d6d741c414b4e864b477d60f881d7b0d78"
)
DEFAULT_DOSE = SERVER / "tests/data/pair_cap_rollout_incremental_dose.v1.json"
SCORE_FIELDS = DOSE.SCORE_FIELDS


class ReplayRefused(RuntimeError):
    """The replay cannot support its bounded score-free description."""


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


def _same_action(left: list[str], right: list[str]) -> bool:
    return sorted(left) == sorted(right)


def _assert_score_free(value) -> None:
    if isinstance(value, dict):
        overlap = SCORE_FIELDS.intersection(value)
        if overlap:
            raise ReplayRefused(
                "score-free artifact contains outcome fields: "
                + ", ".join(sorted(overlap)))
        for child in value.values():
            _assert_score_free(child)
    elif isinstance(value, list):
        for child in value:
            _assert_score_free(child)


def _source_sha256s(dose: Path) -> dict[str, str]:
    paths = {
        "replay": SCRIPT,
        "dose_artifact": dose,
        "dose_script": SCRIPT.with_name(
            "pair_cap_rollout_incremental_dose.py"),
        "root_replay": SCRIPT.with_name("pair_cap_rollout_root_audit.py"),
        "attacker_gate": (
            SERVER / "shengji/ai/pair_cap_attacker_rollout.py"),
        "pair_cap": SERVER / "shengji/ai/pair_cap_rollout.py",
        "pair_v1": SERVER / "shengji/ai/pair_aware_rollout.py",
        "mcbot": SERVER / "shengji/ai/mcbot.py",
        "round": SERVER / "shengji/engine/round.py",
    }
    return {name: sha256(path) for name, path in sorted(paths.items())}


def replay_row(row: dict) -> dict:
    rnd = AUDIT.reconstruct_root(row)
    seat = int(row["seat"])
    bot = make_pair_cap_attacker_bot(
        treatment=True, seed=int(row["decision_seed"]))
    action = bot.decide_play(rnd, seat)
    candidates = DOSE._candidates(bot)
    candidate_count = len(candidates) if candidates is not None else 1
    if candidate_count != int(row["root_candidate_count"]):
        raise ReplayRefused(f"{row['state_id']}: root ballot width drift")
    work = DOSE._work(bot)
    if work != row["work"]:
        raise ReplayRefused(f"{row['state_id']}: exact MC work drift")
    if DOSE._public_state_digest(rnd, seat) != row["public_state_sha256"]:
        raise ReplayRefused(f"{row['state_id']}: public replay digest drift")
    pair_cap = bot.rollout_policy.pair_cap_telemetry()
    if pair_cap["defender_triggers"] != 0:
        raise ReplayRefused(
            f"{row['state_id']}: attacker-only gate emitted defender dose")
    return {
        "state_id": row["state_id"],
        "phase_band": row["phase_band"],
        "role": row["role"],
        "seat": seat,
        "public_state_sha256": row["public_state_sha256"],
        "decision_seed": row["decision_seed"],
        "root_candidate_count": candidate_count,
        "v1_action": list(row["v1_action"]),
        "broad_v2_action": list(row["v2_action"]),
        "attacker_gate_action": list(action),
        "matched_null_action": list(row["matched_null_action"]),
        "matches_v1": _same_action(action, row["v1_action"]),
        "matches_broad_v2": _same_action(action, row["v2_action"]),
        "new_vs_v1": not _same_action(action, row["v1_action"]),
        "root_change_vs_null": not _same_action(
            action, row["matched_null_action"]),
        "pair_cap_dose": pair_cap,
        "combined_pair_dose": bot.pair_aware_telemetry(),
        "work": work,
    }


def run_replay(*, dose: Path = DEFAULT_DOSE) -> dict:
    if sha256(dose) != EXPECTED_DOSE_SHA256:
        raise ReplayRefused("incremental-dose input hash drift")
    parent = json.loads(dose.read_bytes())
    rows = parent.get("rows")
    if not isinstance(rows, list) or len(rows) != 192:
        raise ReplayRefused("incremental-dose row population drift")
    if len({row["state_id"] for row in rows}) != len(rows):
        raise ReplayRefused("incremental-dose state identity collision")

    started = time.monotonic()
    replayed = []
    for index, row in enumerate(rows):
        replayed.append(replay_row(row))
        print(json.dumps({
            "event": "pair-cap-attacker-gate-replay-progress-v1",
            "roots_complete": index + 1,
            "roots_total": len(rows),
            "state_id": row["state_id"],
            "new_vs_v1": replayed[-1]["new_vs_v1"],
        }, sort_keys=True), flush=True)

    relation_counts = Counter()
    for row in replayed:
        if row["matches_v1"] and row["matches_broad_v2"]:
            relation_counts["all_equal"] += 1
        elif row["matches_v1"]:
            relation_counts["protects_v1_from_broad_v2"] += 1
        elif row["matches_broad_v2"]:
            relation_counts["retains_broad_v2_change"] += 1
        else:
            relation_counts["new_third_action"] += 1
    changed_parent_rows = [
        row for row in replayed
        if not _same_action(row["v1_action"], row["broad_v2_action"])
    ]
    payload = {
        "schema": SCHEMA,
        "git": git("rev-parse", "HEAD"),
        "tree_dirty": bool(git("status", "--porcelain")),
        "runtime": {
            "hostname": platform.node(),
            "python": platform.python_version(),
            "executable": str(Path(sys.executable).resolve()),
        },
        "source_sha256s": _source_sha256s(dose),
        "design": {
            "population": "all 192 frozen incremental-dose roots",
            "parent_dose_sha256": EXPECTED_DOSE_SHA256,
            "same_root_ballot_decision_seed_and_mc_work": True,
            "new_arm": "v1 plus opponent-pair-cap only on attacker leads",
            "score_free": True,
        },
        "rows": replayed,
        "aggregate": {
            "roots": len(replayed),
            "relation_counts": dict(sorted(relation_counts.items())),
            "root_changes_vs_null": sum(
                row["root_change_vs_null"] for row in replayed),
            "new_root_changes_vs_v1": sum(
                row["new_vs_v1"] for row in replayed),
            "pair_cap_triggered_roots": sum(
                row["pair_cap_dose"]["triggers"] > 0 for row in replayed),
            "pair_cap_triggers": sum(
                row["pair_cap_dose"]["triggers"] for row in replayed),
            "broad_v2_changed_parent_roots": len(changed_parent_rows),
            "changed_parent_root_relations": {
                row["state_id"]: (
                    "v1" if row["matches_v1"] else
                    "broad_v2" if row["matches_broad_v2"] else "third"
                ) for row in changed_parent_rows
            },
            "elapsed_seconds": time.monotonic() - started,
        },
        "score_free": True,
        "outcomes_published": False,
        "exploration_only": True,
        "strength_claim": False,
        "whole_game_execution_authorized": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    _assert_score_free(payload)
    payload["internal_sha256"] = stable_digest(payload)
    return payload


def write_exclusive(path: Path, payload: dict) -> None:
    partial = Path(str(path) + ".partial")
    if os.path.lexists(path) or os.path.lexists(partial):
        raise ReplayRefused("refusing to overwrite attacker-gate replay")
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
    parser.add_argument("--dose", type=Path, default=DEFAULT_DOSE)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    payload = run_replay(dose=args.dose)
    write_exclusive(args.out, payload)
    print(json.dumps({
        "status": "COMPLETE_SCORE_FREE_EXPLORATION",
        "aggregate": payload["aggregate"],
        "output_sha256": sha256(args.out),
        "internal_sha256": payload["internal_sha256"],
    }, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
