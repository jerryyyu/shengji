#!/usr/bin/env python3
"""Freeze and execute one score-free pair-aware whole-round preflight.

The reviewed exact endgame and lead-root dose results authorize packet design,
not gameplay.  This controller freezes the complete-round population and
runtime, then requires an independent packet marker before it can play four
mirrored three-arm clusters.  It discards all outcomes and per-round traces,
publishing only exact work, rollout dose, natural first-divergence prevalence,
and cost projections for 2,048 and 8,192 clusters.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import secrets
import stat
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

import pair_aware_rollout_duel as CORE  # noqa: E402
from shengji.ai.heuristic import HeuristicBot  # noqa: E402
from shengji.ai.pair_aware_rollout import (  # noqa: E402
    PAIR_AWARE_COUNTER_FIELDS,
    PairAwareRolloutPolicy,
    make_pair_aware_bot,
)
from shengji.engine import combos, fast  # noqa: E402
from shengji.engine.ballot import mc_ballot  # noqa: E402


PACKET_SCHEMA = "pair-aware-rollout-capacity-packet-v1"
ADMISSION_SCHEMA = "pair-aware-rollout-capacity-admission-v1"
RESULT_SCHEMA = "pair-aware-rollout-capacity-result-v1"
RUN_ID = "pair-aware-whole-round-screen-v1"
PREFLIGHT_RUN_ID = "pair-aware-whole-round-preflight-v1"
SOURCE_GIT = "d4d8ebd116aab4994b5b7af22115fe4e95762ab0"
DOSE_GIT = "1801aa0af5358705eceda8b6d611b079b64cceed"
EXACT_REVIEW_PREFIX = "PAIR_AWARE_ROLLOUT_EXACT_V1_REVIEW "
DOSE_REVIEW_PREFIX = "PAIR_AWARE_ROLLOUT_ROOT_DOSE_V1_REVIEW "
PACKET_REVIEW_PREFIX = "PAIR_AWARE_ROLLOUT_CAPACITY_PACKET_V1_REVIEW "
CAPACITY_REVIEW_PREFIX = "PAIR_AWARE_ROLLOUT_CAPACITY_V1_REVIEW "
EXPECTED_EXECUTION_HOST = "Jerrys-MacBook-Air.local"
EXPECTED_PYTHON_VERSION = "3.14.6"
EXPECTED_PYTHON_IMPLEMENTATION = "CPython"
EXPECTED_PYTHON_EXECUTABLE = (
    "/Users/jerryyu/.local/share/uv/python/"
    "cpython-3.14.6-macos-aarch64-none/bin/python3.14")
EXPECTED_FAST_BINARY_SHA256 = (
    "9371ab7fc8bbcceb19cc5c4fe799860cf5ad3f51b11b26ab0e375ced36713e32")
PREFLIGHT_SEED0 = 444_000_000_000
PREFLIGHT_CLUSTERS = 4
SCREEN_SEED0 = 445_000_000_000
PROJECTION_CLUSTERS = (2_048, 8_192)
SHARD_COUNT = 8
STREAM_STRIDE = 3_000_017
SAFETY_FACTOR = 2.0
BASE_FLEET_HOUR_CAP = 512.0
BASE_MAX_SHARD_HOUR_CAP = 64.0
RUN_LOG_DIR = SERVER / "runs/logs" / PREFLIGHT_RUN_ID
ADMISSION_PATH = SERVER / "runs/locks" / \
    f"{PREFLIGHT_RUN_ID}.admission.consumed.json"
RESULT_PATH = RUN_LOG_DIR / "capacity.json"

EXPECTED_EXACT_REVIEW = {
    "artifact_sha256": (
        "031a365dabff0601ca66299b7b62cb2e38ff4231362b9004f683f26e14112919"),
    "decision": "ADVANCE_TO_REVIEWED_WHOLE_GAME_SCREEN",
    "exact_recomputation_passed": True,
    "git": SOURCE_GIT,
    "independent_review": True,
    "production_deployment": False,
    "production_promotion": False,
    "result_git": "c3faec3f34ff3273de003848ea0e5f0f99be68f8",
    "schema": "pair-aware-rollout-exact-result-review-v1",
    "strength_claim": False,
    "verdict": "PASS",
    "whole_game_execution_authorized": False,
    "whole_game_packet_design_authorized": True,
}
EXPECTED_DOSE_REVIEW = {
    "artifact_sha256": (
        "e530da6a55e53cb29f941a4b539870d15b45bb279d8265f72a6276b80cfbbbb8"),
    "decision": "ADVANCE_TO_SCORE_FREE_WHOLE_GAME_CAPACITY_PACKET_DESIGN",
    "git": DOSE_GIT,
    "independent_review": True,
    "parent_git": SOURCE_GIT,
    "production_deployment": False,
    "production_promotion": False,
    "root_action_changes": 1,
    "schema": "pair-aware-rollout-root-dose-review-v1",
    "score_free_recomputation_passed": True,
    "states": 24,
    "strength_claim": False,
    "verdict": "PASS",
    "whole_game_execution_authorized": False,
    "whole_game_preflight_execution_authorized": False,
    "whole_game_preflight_packet_design_authorized": True,
}
FORBIDDEN_SCORE_KEYS = frozenset({
    "banker", "attacker_points", "winner_team", "level_change", "won",
    "level_utility", "utility", "winner", "points", "records", "outcomes",
    "history", "cards", "action", "actions",
})


class CapacityRefused(RuntimeError):
    """The request lacks exact identity, capacity, or review authority."""


def sha256(path: os.PathLike | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def stable_digest(value) -> str:
    raw = json.dumps(
        value, sort_keys=True, separators=(",", ":"), default=list,
    ).encode()
    return hashlib.sha256(raw).hexdigest()


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, check=True, capture_output=True, text=True,
    ).stdout.strip()


def git_is_ancestor(ancestor: str, descendant: str) -> bool:
    return subprocess.run(
        ["git", "merge-base", "--is-ancestor", ancestor, descendant],
        cwd=REPO, capture_output=True, text=True,
    ).returncode == 0


def write_exclusive(path: os.PathLike | str, payload: dict) -> None:
    final = Path(path)
    partial = Path(str(final) + ".partial")
    if os.path.lexists(final) or os.path.lexists(partial):
        raise CapacityRefused(f"refusing to overwrite {final} or {partial}")
    final.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(payload, sort_keys=True, separators=(",", ":"))
           + "\n").encode()
    with partial.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    if json.loads(partial.read_bytes()) != payload:
        raise CapacityRefused("exclusive partial failed exact reopen")
    os.link(partial, final)
    partial.unlink()
    if final.read_bytes() != raw:
        raise CapacityRefused("published artifact differs from candidate")


def require_regular_unlinked(path: Path, *, label: str) -> None:
    partial = Path(str(path) + ".partial")
    try:
        info = path.lstat()
    except FileNotFoundError as exc:
        raise CapacityRefused(f"{label} is missing") from exc
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or os.path.lexists(partial)):
        raise CapacityRefused(f"{label} is linked, nonregular, or partial")


def source_paths() -> dict[str, Path]:
    if not fast.HAVE_FAST or fast._fast is None:
        raise CapacityRefused("compiled fast binary is unavailable")
    return {
        "controller": SCRIPT,
        "duel_core": SERVER / "scripts/pair_aware_rollout_duel.py",
        "pair_aware": SERVER / "shengji/ai/pair_aware_rollout.py",
        "root_dose": SERVER / "scripts/pair_aware_rollout_root_dose.py",
        "evaluation": SERVER / "shengji/evaluation.py",
        "registry": SERVER / "shengji/ai/registry.py",
        "mcbot": SERVER / "shengji/ai/mcbot.py",
        "memory": SERVER / "shengji/ai/memory.py",
        "env": SERVER / "shengji/ai/env.py",
        "game": SERVER / "shengji/engine/game.py",
        "round": SERVER / "shengji/engine/round.py",
        "fast_binary": Path(fast._fast.__file__).resolve(),
    }


def source_sha256s() -> dict[str, str]:
    return {name: sha256(path) for name, path in source_paths().items()}


def runtime_snapshot() -> dict[str, str | bool]:
    if not fast.HAVE_FAST or fast._fast is None:
        raise CapacityRefused("compiled fast binary is unavailable")
    return {
        "host": platform.node(),
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "python_executable": str(Path(sys.executable).resolve()),
        "fast_required": True,
        "strict_voids_required": True,
        "fast_binary_sha256": sha256(Path(fast._fast.__file__).resolve()),
    }


def runtime_problems(runtime: object) -> list[str]:
    expected = {
        "host": EXPECTED_EXECUTION_HOST,
        "python": EXPECTED_PYTHON_VERSION,
        "implementation": EXPECTED_PYTHON_IMPLEMENTATION,
        "python_executable": EXPECTED_PYTHON_EXECUTABLE,
        "fast_required": True,
        "strict_voids_required": True,
        "fast_binary_sha256": EXPECTED_FAST_BINARY_SHA256,
    }
    return [] if runtime == expected else ["runtime is not exact Air"]


def require_air_runtime() -> dict[str, str | bool]:
    runtime = runtime_snapshot()
    problems = runtime_problems(runtime)
    if problems:
        raise CapacityRefused("; ".join(problems))
    return runtime


def _uppercase_contract(bot) -> dict[str, bool | int | float | str | None]:
    values = {}
    for name in dir(bot):
        if not name.isupper():
            continue
        value = getattr(bot, name)
        if not isinstance(value, (bool, int, float, str, type(None))):
            raise CapacityRefused(f"non-serializable policy knob {name}")
        values[name] = value
    return values


def policy_contracts() -> dict[str, dict]:
    treatment = make_pair_aware_bot(treatment=True, seed=7)
    null = make_pair_aware_bot(treatment=False, seed=7)
    champion = CORE.make_arm("champion", 7)
    if _uppercase_contract(treatment) != _uppercase_contract(null) \
            or _uppercase_contract(treatment) != _uppercase_contract(champion):
        raise CapacityRefused("pair arms do not inherit one champion contract")
    if (type(treatment.rollout_policy) is not PairAwareRolloutPolicy
            or type(null.rollout_policy) is not PairAwareRolloutPolicy
            or type(champion.rollout_policy) is not HeuristicBot):
        raise CapacityRefused("pair rollout seam identity drift")
    digests = {mc_ballot(bot).digest for bot in (treatment, null, champion)}
    if len(digests) != 1:
        raise CapacityRefused("pair root ballot identity drift")
    return {
        "champion": {
            "policy": CORE.LABELS["champion"],
            "class": type(champion).__name__,
            "uppercase": _uppercase_contract(champion),
            "root_ballot_digest": mc_ballot(champion).digest,
            "rollout": type(champion.rollout_policy).__name__,
            "pair_mode": "off",
        },
        "treatment": {
            "policy": CORE.LABELS["treatment"],
            "class": type(treatment).__name__,
            "uppercase": _uppercase_contract(treatment),
            "root_ballot_digest": mc_ballot(treatment).digest,
            "rollout": type(treatment.rollout_policy).__name__,
            "pair_mode": treatment.rollout_policy.mode,
        },
        "matched_null": {
            "policy": CORE.LABELS["matched_null"],
            "class": type(null).__name__,
            "uppercase": _uppercase_contract(null),
            "root_ballot_digest": mc_ballot(null).digest,
            "rollout": type(null.rollout_policy).__name__,
            "pair_mode": null.rollout_policy.mode,
        },
    }


def parse_marker(path: os.PathLike | str, prefix: str,
                 expected: dict, *, label: str) -> dict:
    source = Path(path)
    require_regular_unlinked(source, label=label)
    matches = [line for line in source.read_text(encoding="utf-8").splitlines()
               if line.startswith(prefix)]
    if len(matches) != 1:
        raise CapacityRefused(f"{label} must contain exactly one marker")
    try:
        payload = json.loads(matches[0][len(prefix):])
    except ValueError as exc:
        raise CapacityRefused(f"{label} marker is malformed") from exc
    if payload != expected:
        raise CapacityRefused(f"{label} marker payload drift")
    return {"sha256": sha256(source), "marker": matches[0], "payload": payload}


def packet_payload(*, expected_git: str, exact_review_record: os.PathLike | str,
                   dose_review_record: os.PathLike | str) -> dict:
    exact_review = parse_marker(
        exact_review_record, EXACT_REVIEW_PREFIX, EXPECTED_EXACT_REVIEW,
        label="pair exact review record")
    dose_review = parse_marker(
        dose_review_record, DOSE_REVIEW_PREFIX, EXPECTED_DOSE_REVIEW,
        label="pair root-dose review record")
    if not git_is_ancestor(DOSE_GIT, expected_git):
        raise CapacityRefused("reviewed pair dose source is not an ancestor")
    payload = {
        "schema": PACKET_SCHEMA,
        "run_id": RUN_ID,
        "preflight_run_id": PREFLIGHT_RUN_ID,
        "git": expected_git,
        "source_git": SOURCE_GIT,
        "dose_git": DOSE_GIT,
        "exact_review": exact_review,
        "dose_review": dose_review,
        "source_sha256s": source_sha256s(),
        "runtime": require_air_runtime(),
        "policy_contracts": policy_contracts(),
        "preflight": {
            "seed0": PREFLIGHT_SEED0,
            "clusters": PREFLIGHT_CLUSTERS,
            "labels": list(CORE.LABEL_ORDER),
            "stream_stride": STREAM_STRIDE,
            "score_free": True,
            "outcomes_published": False,
            "natural_dose": (
                "compare treatment and matched-null histories only through "
                "their first divergence on each complete mirrored round"),
            "admission_path": str(ADMISSION_PATH.relative_to(REPO)),
            "result_path": str(RESULT_PATH.relative_to(REPO)),
        },
        "successor_projection": {
            "seed0": SCREEN_SEED0,
            "candidate_clusters": list(PROJECTION_CLUSTERS),
            "shards": SHARD_COUNT,
            "labels": list(CORE.LABEL_ORDER),
            "sizing_rule": (
                "capacity result review must choose or reject a successor "
                "using measured natural root-change traffic and a declared "
                "minimum detectable effect; neither candidate is pre-authorized"),
        },
        "capacity": {
            "safety_factor": SAFETY_FACTOR,
            "base_clusters": PROJECTION_CLUSTERS[0],
            "base_fleet_hour_cap": BASE_FLEET_HOUR_CAP,
            "base_max_shard_hour_cap": BASE_MAX_SHARD_HOUR_CAP,
        },
        "authority": {
            "preflight_execution_authorized": False,
            "screen_packet_design_authorized": False,
            "screen_execution_authorized": False,
            "strength_claim": False,
            "production_promotion": False,
            "production_deployment": False,
        },
    }
    payload["internal_sha256"] = stable_digest(payload)
    return payload


def packet_problems(payload: object, *, expected_git: str,
                    exact_review_record: os.PathLike | str,
                    dose_review_record: os.PathLike | str) -> list[str]:
    try:
        expected = packet_payload(
            expected_git=expected_git,
            exact_review_record=exact_review_record,
            dose_review_record=dose_review_record)
    except Exception as exc:
        return [f"cannot reconstruct packet: {type(exc).__name__}: {exc}"]
    return [] if payload == expected else ["packet differs from reconstruction"]


def load_packet(path: os.PathLike | str, expected_sha256: str, *,
                expected_git: str, exact_review_record: os.PathLike | str,
                dose_review_record: os.PathLike | str) -> dict:
    source = Path(path)
    require_regular_unlinked(source, label="pair capacity packet")
    if sha256(source) != expected_sha256:
        raise CapacityRefused("pair packet SHA-256 drift")
    try:
        payload = json.loads(source.read_bytes())
    except (OSError, ValueError) as exc:
        raise CapacityRefused("pair packet is unreadable") from exc
    problems = packet_problems(
        payload, expected_git=expected_git,
        exact_review_record=exact_review_record,
        dose_review_record=dose_review_record)
    if problems:
        raise CapacityRefused("invalid pair packet: " + "; ".join(problems))
    return payload


def packet_review_claim(*, expected_git: str,
                        packet_sha256: str) -> dict:
    return {
        "git": expected_git,
        "independent_review": True,
        "one_score_free_preflight_authorized": True,
        "packet_sha256": packet_sha256,
        "production_deployment": False,
        "production_promotion": False,
        "run_id": RUN_ID,
        "schema": "pair-aware-rollout-capacity-packet-review-v1",
        "screen_execution_authorized": False,
        "strength_claim": False,
        "verdict": "PASS",
    }


def capacity_review_claim(*, result: dict, result_sha256: str,
                          packet_sha256: str) -> dict:
    passed = result.get("capacity_pass") is True
    return {
        "capacity_pass": passed,
        "capacity_result_internal_sha256": result["internal_sha256"],
        "capacity_result_sha256": result_sha256,
        "elapsed_seconds": result["elapsed_seconds"],
        "git": result["git"],
        "independent_review": True,
        "natural_root_action_changes": result["natural_dose"][
            "root_action_changes"],
        "one_screen_packet_design_authorized": passed,
        "packet_sha256": packet_sha256,
        "preflight_clusters": PREFLIGHT_CLUSTERS,
        "production_deployment": False,
        "production_promotion": False,
        "run_id": RUN_ID,
        "schema": "pair-aware-rollout-capacity-review-v1",
        "score_free": True,
        "screen_execution_authorized": False,
        "strength_claim": False,
        "verdict": "PASS" if passed else "HOLD",
    }


def score_free_result_problems(value: object) -> list[str]:
    problems = []

    def walk(item, path: str) -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                if key in FORBIDDEN_SCORE_KEYS:
                    problems.append(f"forbidden score field {path}{key}")
                walk(child, f"{path}{key}.")
        elif isinstance(item, list):
            for index, child in enumerate(item):
                walk(child, f"{path}{index}.")

    walk(value, "")
    if not isinstance(value, dict) \
            or value.get("score_free") is not True \
            or value.get("outcomes_published") is not False:
        problems.append("score-free identity")
    return sorted(set(problems))


def _sum_plain(records: list[dict], side: str) -> dict:
    names = set(CORE.counters([]))
    totals = {name: 0.0 if name == "search_secs" else 0 for name in names}
    for record in records:
        for name in names:
            totals[name] += record[side][name]
    totals["search_secs"] = round(float(totals["search_secs"]), 4)
    return totals


def _sum_pair(records: list[dict], side: str) -> dict:
    modes = {record[side]["pair_aware"]["mode"] for record in records}
    if len(modes) != 1:
        raise CapacityRefused("pair preflight telemetry mode drift")
    totals = Counter({field: 0 for field in PAIR_AWARE_COUNTER_FIELDS})
    for record in records:
        totals.update({field: record[side]["pair_aware"][field]
                       for field in PAIR_AWARE_COUNTER_FIELDS})
    return {"mode": next(iter(modes)),
            **{field: int(totals[field]) for field in PAIR_AWARE_COUNTER_FIELDS}}


def _natural_dose(by_label: dict[str, list[dict]]) -> dict:
    treatment = by_label["treatment"]
    null = by_label["matched_null"]
    champion = by_label["champion"]
    rows = []
    for tr, nr, cr in zip(treatment, null, champion, strict=True):
        problems = CORE.matched_null_champion_problems(nr, cr)
        if problems:
            raise CapacityRefused("; ".join(problems))
        rows.append(CORE.natural_root_dose(tr, nr))
    changes = [row for row in rows if row["root_action_changed"]]
    by_phase = Counter(row["change_phase"] for row in changes)
    by_role = Counter(row["change_role"] for row in changes)
    return {
        "complete_round_pairs": len(rows),
        "shared_prefix_plays": sum(row["shared_prefix_plays"] for row in rows),
        "root_action_changes": len(changes),
        "rounds_without_root_change": len(rows) - len(changes),
        "change_fraction": len(changes) / len(rows),
        "changes_by_phase": {
            phase: int(by_phase[phase]) for phase in ("early", "mid", "late")
        },
        "changes_by_role": {
            role: int(by_role[role]) for role in ("attacker", "defender")
        },
        "matched_null_champion_exact_histories": True,
    }


def measure_preflight(packet: dict, *, clock=time.perf_counter) -> dict:
    started = clock()
    by_label = {label: [] for label in CORE.LABEL_ORDER}
    for cluster_index in range(PREFLIGHT_CLUSTERS):
        seed = PREFLIGHT_SEED0 + STREAM_STRIDE * cluster_index
        for label in CORE.LABEL_ORDER:
            records = CORE.play_arm_cluster(
                label, seed, run_id=PREFLIGHT_RUN_ID)
            for flip, record in enumerate(records):
                problems = CORE.record_problems(
                    record, expected_label=label, expected_seed=seed,
                    expected_flip=flip, expected_run_id=PREFLIGHT_RUN_ID)
                if problems:
                    raise CapacityRefused(
                        "invalid score-free preflight row: " + "; ".join(problems))
            by_label[label].extend(records)
        print(json.dumps({
            "event": "pair-aware-score-free-progress-v1",
            "clusters_complete": cluster_index + 1,
            "clusters_total": PREFLIGHT_CLUSTERS,
        }, sort_keys=True), flush=True)
    elapsed = clock() - started
    if not math.isfinite(elapsed) or elapsed <= 0:
        raise CapacityRefused("pair preflight elapsed time is invalid")

    counts = {
        label: {
            "records_discarded": len(records),
            "arm": _sum_plain(records, "arm"),
            "opp": _sum_plain(records, "opp"),
            "arm_pair": _sum_pair(records, "arm"),
            "opp_pair": _sum_pair(records, "opp"),
        }
        for label, records in by_label.items()
    }
    exact_work = True
    for records in by_label.values():
        for record in records:
            mode = {"treatment": "treatment", "matched_null": "matched_null",
                    "champion": "off"}[record["label"]]
            if (CORE.counter_problems(record["arm"], expected_mode=mode)
                    or CORE.counter_problems(record["opp"], expected_mode="off")):
                exact_work = False
    dose = _natural_dose(by_label)
    projections = {}
    for clusters in PROJECTION_CLUSTERS:
        fleet_hours = (
            elapsed / PREFLIGHT_CLUSTERS * clusters * SAFETY_FACTOR / 3_600.0)
        projections[str(clusters)] = {
            "clusters": clusters,
            "fleet_hours": fleet_hours,
            "max_shard_hours": fleet_hours / SHARD_COUNT,
        }
    treatment = counts["treatment"]["arm_pair"]
    null = counts["matched_null"]["arm_pair"]
    base_projection = projections[str(PROJECTION_CLUSTERS[0])]
    capacity_pass = (
        exact_work
        and treatment["triggers"] > 0
        and null["triggers"] > 0
        and treatment["changes"] == treatment["triggers"]
        and null["changes"] == 0
        and null["matched_noops"] == null["triggers"]
        and dose["root_action_changes"] > 0
        and dose["matched_null_champion_exact_histories"] is True
        and base_projection["fleet_hours"] <= BASE_FLEET_HOUR_CAP
        and base_projection["max_shard_hours"] <= BASE_MAX_SHARD_HOUR_CAP)
    result = {
        "schema": RESULT_SCHEMA,
        "run_id": RUN_ID,
        "preflight_run_id": PREFLIGHT_RUN_ID,
        "git": packet["git"],
        "packet_internal_sha256": packet["internal_sha256"],
        "score_free": True,
        "outcomes_published": False,
        "records_discarded": sum(
            value["records_discarded"] for value in counts.values()),
        "elapsed_seconds": elapsed,
        "counts": counts,
        "natural_dose": dose,
        "projection": {
            "safety_factor": SAFETY_FACTOR,
            "shards": SHARD_COUNT,
            "candidates": projections,
            "base_fleet_hour_cap": BASE_FLEET_HOUR_CAP,
            "base_max_shard_hour_cap": BASE_MAX_SHARD_HOUR_CAP,
        },
        "exact_work_complete": exact_work,
        "capacity_pass": capacity_pass,
        "supports_screen_packet_review": capacity_pass,
        "screen_packet_design_authorized": False,
        "screen_execution_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    result["internal_sha256"] = stable_digest(result)
    problems = score_free_result_problems(result)
    if problems:
        raise CapacityRefused(
            "pair preflight attempted score publication: " + "; ".join(problems))
    return result


def require_clean_exact_git(expected_git: str) -> None:
    if git("rev-parse", "HEAD") != expected_git:
        raise CapacityRefused("pair controller git identity drift")
    if git("status", "--porcelain", "--untracked-files=all"):
        raise CapacityRefused("pair controller worktree is dirty")


def require_compiled_strict_runtime() -> None:
    if (os.environ.get("SHENGJI_FAST") != "1"
            or os.environ.get("SHENGJI_REQUIRE_VOIDS") != "1"
            or not fast.HAVE_FAST or fast._fast is None
            or combos.decompose is not fast.decompose):
        raise CapacityRefused("pair preflight requires compiled strict mode")


def require_exact_output_path(value: os.PathLike | str, expected: Path,
                              *, label: str) -> None:
    actual = Path(value).resolve(strict=False)
    if actual != expected.resolve(strict=False):
        raise CapacityRefused(
            f"{label} must use singleton path {expected.relative_to(REPO)}")


def freeze_command(args) -> None:
    require_clean_exact_git(args.expected_git)
    payload = packet_payload(
        expected_git=args.expected_git,
        exact_review_record=args.exact_review_record,
        dose_review_record=args.dose_review_record)
    write_exclusive(args.out, payload)
    packet_sha = sha256(args.out)
    print(json.dumps({
        "status": "FROZEN",
        "packet_sha256": packet_sha,
        "packet_internal_sha256": payload["internal_sha256"],
        "packet_review_claim": packet_review_claim(
            expected_git=args.expected_git, packet_sha256=packet_sha),
    }, sort_keys=True))


def verify_command(args) -> None:
    require_clean_exact_git(args.expected_git)
    packet = load_packet(
        args.packet, args.expected_packet_sha256,
        expected_git=args.expected_git,
        exact_review_record=args.exact_review_record,
        dose_review_record=args.dose_review_record)
    print(json.dumps({"status": "VERIFIED",
                      "packet_internal_sha256": packet["internal_sha256"]},
                     sort_keys=True))


def preflight_command(args) -> None:
    require_clean_exact_git(args.expected_git)
    require_exact_output_path(
        args.admission, ADMISSION_PATH, label="pair preflight admission")
    require_exact_output_path(
        args.out, RESULT_PATH, label="pair preflight result")
    require_compiled_strict_runtime()
    packet = load_packet(
        args.packet, args.expected_packet_sha256,
        expected_git=args.expected_git,
        exact_review_record=args.exact_review_record,
        dose_review_record=args.dose_review_record)
    claim = packet_review_claim(
        expected_git=args.expected_git,
        packet_sha256=args.expected_packet_sha256)
    review = parse_marker(
        args.packet_review_record, PACKET_REVIEW_PREFIX, claim,
        label="pair capacity packet review")
    admission = {
        "schema": ADMISSION_SCHEMA,
        "run_id": RUN_ID,
        "git": args.expected_git,
        "packet_sha256": args.expected_packet_sha256,
        "packet_review_sha256": review["sha256"],
        "nonce": secrets.token_hex(32),
        "created_time_ns": time.time_ns(),
        "score_free": True,
        "one_preflight_execution_authorized": True,
        "screen_execution_authorized": False,
        "strength_claim": False,
        "production_deployment": False,
    }
    admission["internal_sha256"] = stable_digest(admission)
    write_exclusive(args.admission, admission)
    result = measure_preflight(packet)
    result["admission_sha256"] = sha256(args.admission)
    result["packet_sha256"] = args.expected_packet_sha256
    result.pop("internal_sha256", None)
    result["internal_sha256"] = stable_digest(result)
    write_exclusive(args.out, result)
    result_sha = sha256(args.out)
    print(json.dumps({
        "status": "CAPACITY_PASS" if result["capacity_pass"] else "HOLD",
        "result_sha256": result_sha,
        "result_internal_sha256": result["internal_sha256"],
        "capacity_review_claim": capacity_review_claim(
            result=result, result_sha256=result_sha,
            packet_sha256=args.expected_packet_sha256),
    }, sort_keys=True))


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser()
    sub = root.add_subparsers(dest="command", required=True)
    for name, fn in (("freeze", freeze_command), ("verify", verify_command)):
        cmd = sub.add_parser(name)
        cmd.add_argument("--expected-git", required=True)
        cmd.add_argument("--exact-review-record", required=True)
        cmd.add_argument("--dose-review-record", required=True)
        if name == "freeze":
            cmd.add_argument("--out", required=True)
        else:
            cmd.add_argument("--packet", required=True)
            cmd.add_argument("--expected-packet-sha256", required=True)
        cmd.set_defaults(func=fn)
    run = sub.add_parser("run-preflight")
    run.add_argument("--expected-git", required=True)
    run.add_argument("--exact-review-record", required=True)
    run.add_argument("--dose-review-record", required=True)
    run.add_argument("--packet", required=True)
    run.add_argument("--expected-packet-sha256", required=True)
    run.add_argument("--packet-review-record", required=True)
    run.add_argument("--admission", required=True)
    run.add_argument("--out", required=True)
    run.set_defaults(func=preflight_command)
    return root


def main() -> None:
    args = parser().parse_args()
    try:
        args.func(args)
    except (CapacityRefused, subprocess.CalledProcessError) as exc:
        raise SystemExit(f"REFUSED: {exc}") from exc


if __name__ == "__main__":
    main()
