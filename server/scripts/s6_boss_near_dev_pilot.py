#!/usr/bin/env python3
"""Reusable DEV utility pilot for the S6 boss/near search-spend gate.

This is deliberately not a promotion screen.  It plays a fixed fresh DEV
population with the literal live champion, the boss/near treatment, and its
compute-matched null, retaining rows so the descriptive result can be audited.
The full S6 source ballot remains visible; only the second search is gated.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import random
import stat
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path


SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[1]
REPO = SERVER.parent
sys.path.insert(0, str(SERVER))
sys.path.insert(0, str(SCRIPT.parent))

import s6_throw_duel as BASE  # noqa: E402
from shengji.ai.env import play_round  # noqa: E402
from shengji.ai.registry import make_bot  # noqa: E402
from shengji.ai.throw_search_gate import (  # noqa: E402
    BOSS_NEAR_GATE,
    S6_BOSS_NEAR_POLICIES,
    make_s6_boss_near_bot,
)
from shengji.engine import combos, fast  # noqa: E402
from shengji.engine.ballot import mc_ballot  # noqa: E402
from shengji.engine.game import Game  # noqa: E402
from shengji.evaluation import counters  # noqa: E402


SCHEMA = "s6-boss-near-dev-pilot-v1"
RUN_ID = "s6-boss-near-dev-pilot-v1"
SEED0 = 449_000_000_000
DEFAULT_CLUSTERS = 32
MAX_CLUSTERS = 256
DEFAULT_WORKERS = 4
MAX_WORKERS = 8
LABEL_ORDER = tuple(BASE.LABEL_ORDER)
OPPONENT = BASE.OPPONENT
LABELS = {
    "treatment": S6_BOSS_NEAR_POLICIES["treatment"],
    "matched_null": S6_BOSS_NEAR_POLICIES["matched_null"],
    "champion": OPPONENT,
}


class PilotRefused(RuntimeError):
    """The DEV pilot cannot support even its descriptive result."""


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
        ["git", *args], cwd=REPO, check=True, capture_output=True, text=True,
    ).stdout.strip()


def write_exclusive(path: os.PathLike | str, payload: dict) -> None:
    final = Path(path)
    partial = Path(str(final) + ".partial")
    if os.path.lexists(final) or os.path.lexists(partial):
        raise PilotRefused("refusing to overwrite S6 boss/near DEV result")
    final.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(payload, sort_keys=True, separators=(",", ":"))
           + "\n").encode()
    with partial.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    if json.loads(partial.read_bytes()) != payload:
        raise PilotRefused("DEV result failed exact reopen")
    os.link(partial, final)
    partial.unlink()
    if final.read_bytes() != raw:
        raise PilotRefused("published DEV result differs from candidate")


def source_paths() -> dict[str, Path]:
    if not fast.HAVE_FAST or fast._fast is None:
        raise PilotRefused("compiled fast binary is unavailable")
    return {
        "pilot": SCRIPT,
        "duel_core": SERVER / "scripts/s6_throw_duel.py",
        "gate": SERVER / "shengji/ai/throw_search_gate.py",
        "policy": SERVER / "shengji/ai/throw_policy.py",
        "source": SERVER / "shengji/ai/throw_sourcing.py",
        "evaluation": SERVER / "shengji/evaluation.py",
        "registry": SERVER / "shengji/ai/registry.py",
        "mcbot": SERVER / "shengji/ai/mcbot.py",
        "memory": SERVER / "shengji/ai/memory.py",
        "env": SERVER / "shengji/ai/env.py",
        "game": SERVER / "shengji/engine/game.py",
        "round": SERVER / "shengji/engine/round.py",
        "fast_binary": Path(fast._fast.__file__).resolve(),
    }


def make_arm(label: str, seed: int):
    if label == "treatment":
        return make_s6_boss_near_bot(treatment=True, seed=seed)
    if label == "matched_null":
        return make_s6_boss_near_bot(treatment=False, seed=seed)
    if label == "champion":
        return make_bot(OPPONENT, seed=seed)
    raise PilotRefused(f"unknown S6 boss/near arm {label!r}")


def policy_contract() -> dict:
    arms = {label: make_arm(label, 7) for label in LABEL_ORDER}
    digests = {label: mc_ballot(bot).digest for label, bot in arms.items()}
    if len(set(digests.values())) != 1:
        raise PilotRefused("boss/near root ballot changed from champion")
    if (arms["treatment"].s6_throw_search_gate != BOSS_NEAR_GATE
            or arms["matched_null"].s6_throw_search_gate != BOSS_NEAR_GATE
            or arms["treatment"].s6_throw_mode != "treatment"
            or arms["matched_null"].s6_throw_mode != "matched_null"):
        raise PilotRefused("boss/near policy mode drift")
    return {
        "labels": LABELS,
        "root_ballot_digests": digests,
        "full_source_ballot_preserved": True,
        "second_search_gate": BOSS_NEAR_GATE,
        "candidate_zero": "literal live champion action",
    }


def _record(label: str, seed: int, flip: int, log,
            arm_bots: list, opp_bots: list) -> dict:
    policy_team = 0 if flip == 0 else 1
    won = int(log.winner_team == policy_team)
    utility = (1 if won else -1) * max(1, int(log.level_change))
    mode = {"treatment": "treatment", "matched_null": "matched_null",
            "champion": "off"}[label]
    return {
        "run": RUN_ID,
        "label": label,
        "policy": LABELS[label],
        "opponent": OPPONENT,
        "seed": seed,
        "flip": flip,
        "banker": int(log.banker),
        "attacker_points": int(log.attacker_points),
        "winner_team": int(log.winner_team),
        "level_change": int(log.level_change),
        "won": won,
        "level_utility": utility,
        "arm": {
            **counters(arm_bots),
            "s6_throw": BASE.s6_telemetry(arm_bots, mode=mode),
        },
        "opp": {
            **counters(opp_bots),
            "s6_throw": BASE.s6_telemetry(opp_bots, mode="off"),
        },
    }


def play_arm_cluster(label: str, seed: int) -> list[dict]:
    records = []
    for flip in (0, 1):
        a1 = make_arm(label, seed + BASE.POLICY_ROLE_OFFSETS[0])
        a2 = make_arm(label, seed + BASE.POLICY_ROLE_OFFSETS[1])
        b1 = make_bot(OPPONENT, seed=seed + BASE.OPPONENT_ROLE_OFFSETS[0])
        b2 = make_bot(OPPONENT, seed=seed + BASE.OPPONENT_ROLE_OFFSETS[1])
        policies = ([a1, b1, a2, b2] if flip == 0
                    else [b1, a1, b2, a2])
        log = play_round(Game(random.Random(seed)), policies)
        records.append(_record(label, seed, flip, log, [a1, a2], [b1, b2]))
    return records


def _play_cluster(cluster_index: int) -> tuple[int, dict[str, list[dict]]]:
    seed = SEED0 + cluster_index
    return cluster_index, {
        label: play_arm_cluster(label, seed) for label in LABEL_ORDER
    }


def record_problems(record: object, *, expected_label: str,
                    expected_seed: int, expected_flip: int) -> list[str]:
    if not isinstance(record, dict):
        return ["record is not an object"]
    problems = []
    if record.get("policy") != LABELS[expected_label]:
        problems.append("boss/near policy identity")
    normalized = dict(record)
    normalized["policy"] = BASE.LABELS[expected_label]
    problems.extend(BASE.record_problems(
        normalized, expected_label=expected_label,
        expected_seed=expected_seed, expected_flip=expected_flip,
        expected_run_id=RUN_ID))
    return sorted(set(problems))


def _normalized(records: dict[str, list[dict]]) -> dict[str, list[dict]]:
    return {
        label: [{**row, "policy": BASE.LABELS[label]} for row in rows]
        for label, rows in records.items()
    }


def build_payload(records: dict[str, list[dict]], *, expected_git: str,
                  clusters: int, workers: int,
                  elapsed_seconds: float) -> dict:
    if not 0 < clusters <= MAX_CLUSTERS:
        raise PilotRefused("DEV cluster count outside frozen bound")
    if not 0 < workers <= MAX_WORKERS:
        raise PilotRefused("DEV worker count outside frozen bound")
    if not isinstance(elapsed_seconds, (int, float)) \
            or not 0 < elapsed_seconds < 7 * 24 * 3_600:
        raise PilotRefused("DEV elapsed time outside physical bound")
    for label in LABEL_ORDER:
        expected = [(SEED0 + index, flip)
                    for index in range(clusters) for flip in (0, 1)]
        actual = [(row.get("seed"), row.get("flip"))
                  for row in records.get(label, [])]
        if actual != expected:
            raise PilotRefused(f"{label} DEV population/order drift")
        for row, (seed, flip) in zip(records[label], expected, strict=True):
            problems = record_problems(
                row, expected_label=label,
                expected_seed=seed, expected_flip=flip)
            if problems:
                raise PilotRefused(
                    f"invalid {label} row {seed}/{flip}: "
                    + "; ".join(problems))
    base = BASE.build_aggregate(
        _normalized(records), expected_clusters=clusters)
    payload = {
        "schema": SCHEMA,
        "git": expected_git,
        "tree_dirty": False,
        "runtime": {
            "host": platform.node(),
            "python": platform.python_version(),
            "python_executable": str(Path(sys.executable).resolve()),
            "fast_binary_sha256": sha256(source_paths()["fast_binary"]),
            "strict_compiled": True,
        },
        "source_sha256s": {
            name: sha256(path) for name, path in source_paths().items()
        },
        "design": {
            "seed0": SEED0,
            "clusters": clusters,
            "workers": workers,
            "mirrored_flips": [0, 1],
            "labels": list(LABEL_ORDER),
            "opponent": OPPONENT,
            "population": "fresh reusable DEV; never a sealed REPORT set",
            "selection": "fixed consecutive seeds; no outcome-dependent stop",
        },
        "policy_contract": policy_contract(),
        "elapsed_seconds": elapsed_seconds,
        "records": records,
        "descriptive": {
            "stats": base["stats"],
            "telemetry": base["telemetry"],
            "matched_null_champion_exact_outcomes": base["criteria"][
                "matched_null_champion_exact_outcomes"],
            "all_records_exact_work": base["criteria"][
                "all_records_exact_work"],
            "treatment_triggered_both_roles": base["criteria"][
                "treatment_triggered_both_roles"],
            "treatment_overrode": base["criteria"]["treatment_overrode"],
        },
        "status": "COMPLETE_DEV_EXPLORATION",
        "exploration_only": True,
        "confirmatory_claim": False,
        "screen_execution_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    payload["internal_sha256"] = stable_digest(payload)
    return payload


def run(args) -> None:
    if git("rev-parse", "HEAD") != args.expected_git:
        raise PilotRefused("DEV pilot git identity drift")
    if git("status", "--porcelain", "--untracked-files=all"):
        raise PilotRefused("DEV pilot worktree is dirty")
    if not 0 < args.clusters <= MAX_CLUSTERS:
        raise PilotRefused("DEV cluster count outside frozen bound")
    if not 0 < args.workers <= MAX_WORKERS:
        raise PilotRefused("DEV worker count outside frozen bound")
    if (os.environ.get("SHENGJI_FAST") != "1"
            or os.environ.get("SHENGJI_REQUIRE_VOIDS") != "1"
            or not fast.HAVE_FAST or fast._fast is None
            or combos.decompose is not fast.decompose):
        raise PilotRefused("DEV pilot requires strict compiled mode")
    started = time.monotonic()
    records = {label: [] for label in LABEL_ORDER}
    completed = {}
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = [pool.submit(_play_cluster, cluster_index)
                   for cluster_index in range(args.clusters)]
        for future in as_completed(futures):
            cluster_index, cluster = future.result()
            if cluster_index in completed:
                raise PilotRefused("duplicate DEV cluster result")
            completed[cluster_index] = cluster
            print(json.dumps({
                "event": "s6-boss-near-dev-progress-v1",
                "clusters_complete": len(completed),
                "clusters_total": args.clusters,
            }, sort_keys=True), flush=True)
    if set(completed) != set(range(args.clusters)):
        raise PilotRefused("DEV cluster population incomplete")
    for cluster_index in range(args.clusters):
        for label in LABEL_ORDER:
            records[label].extend(completed[cluster_index][label])
    payload = build_payload(
        records, expected_git=args.expected_git, clusters=args.clusters,
        workers=args.workers,
        elapsed_seconds=time.monotonic() - started)
    write_exclusive(args.out, payload)
    print(json.dumps({
        "status": payload["status"],
        "output_sha256": sha256(args.out),
        "internal_sha256": payload["internal_sha256"],
        "clusters": args.clusters,
        "exploration_only": True,
    }, sort_keys=True), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-git", required=True)
    parser.add_argument("--clusters", type=int, default=DEFAULT_CLUSTERS)
    parser.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    try:
        run(args)
    except (PilotRefused, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"REFUSED: {exc}") from exc


if __name__ == "__main__":
    main()
