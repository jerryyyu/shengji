#!/usr/bin/env python3
"""Freeze and run one score-free capacity preflight for selective S6.

The already-public selector diagnostic authorizes only packet design.  This
controller consumes an exact independent selector review to freeze a packet;
an additional packet review is then required before its four-cluster Air
preflight may execute.  The preflight discards all outcomes and publishes
only runtime, exact-work, null-equality, and S6 dose counters.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import platform
import secrets
import sys
import time
from pathlib import Path


SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[1]
REPO = SERVER.parent
sys.path.insert(0, str(SERVER))
sys.path.insert(0, str(SCRIPT.parent))

import s6_throw_full_hand_duel as CORE  # noqa: E402
import s6_throw_preflight_controller as BASE  # noqa: E402
from shengji.ai.throw_full_hand_gate import (  # noqa: E402
    FULL_HAND_BOSS_NEAR_GATE,
    make_s6_full_hand_bot,
)
from shengji.ai.throw_policy import S6_THROW_COUNTER_FIELDS  # noqa: E402
from shengji.engine import combos, fast  # noqa: E402
from shengji.engine.ballot import mc_ballot  # noqa: E402


PACKET_SCHEMA = "s6-throw-full-hand-capacity-packet-v2"
RESULT_SCHEMA = "s6-throw-full-hand-capacity-result-v2"
ADMISSION_SCHEMA = "s6-throw-full-hand-capacity-admission-v2"
FREEZE_ADMISSION_SCHEMA = "s6-throw-full-hand-packet-freeze-admission-v2"
RUN_ID = "s6-throw-full-hand-screen-437b-v2"
PREFLIGHT_RUN_ID = "s6-throw-full-hand-preflight-436b-v2"
SELECTOR_GIT = "f3918d26febb434b2ef7391cd72b57c4f461fb4d"
SELECTOR_REVIEW_PREFIX = "S6_FULL_HAND_SELECTOR_V1_REVIEW "
PACKET_REVIEW_PREFIX = "S6_FULL_HAND_PREFLIGHT_PACKET_V2_REVIEW "
EXPECTED_SELECTOR_REVIEW = {
    "actor_visible_gate": True,
    "exact_result_sha256":
        "946b029c0922a902ad5974977cef4a8a30ac245430563f57483c25597d65cebe",
    "git": SELECTOR_GIT,
    "independent_review": True,
    "preflight_packet_design_authorized": True,
    "prevalence_result_sha256":
        "8934c2e39b68afca8a5d8dfc13f4768097c7a61f66627f8f469e1c48b17ea45a",
    "production_deployment": False,
    "production_promotion": False,
    "scored_execution_authorized": False,
    "selector_result_sha256":
        "5473343472c272d3521a04b67bfb7719393ac2adb4263b0f8c1f070be551984c",
    "strength_claim": False,
    "verdict": "PASS",
}
EXPECTED_EXECUTION_HOST = "Jerrys-MacBook-Air.local"
EXPECTED_PYTHON_VERSION = "3.14.6"
EXPECTED_PYTHON_EXECUTABLE = (
    "/Users/jerryyu/.local/share/uv/python/"
    "cpython-3.14.6-macos-aarch64-none/bin/python3.14")
EXPECTED_FAST_BINARY_SHA256 = (
    "9371ab7fc8bbcceb19cc5c4fe799860cf5ad3f51b11b26ab0e375ced36713e32")
PREFLIGHT_SEED0 = 436_000_000_000
PREFLIGHT_CLUSTERS = 4
SCREEN_SEED0 = 437_000_000_000
SCREEN_CLUSTERS = 7_168
SHARD_COUNT = 8
STREAM_STRIDE = 3_000_017
SAFETY_FACTOR = 2.0
SCREEN_FLEET_HOUR_CAP = 512.0
SCREEN_MAX_SHARD_HOUR_CAP = 64.0
HEURISTIC_PREVALENCE_RATE = 1_011 / 50_000
CHAMPION_CENSUS_DEALS = 512
CHAMPION_CENSUS_TRIGGERED_DEALS = 13
CHAMPION_CENSUS_LEADS = 9_382
CHAMPION_CENSUS_TRIGGERED_LEADS = 13
CHAMPION_PREVALENCE_RATE = (
    CHAMPION_CENSUS_TRIGGERED_DEALS / CHAMPION_CENSUS_DEALS)
# Keep sizing conservative: the smaller 2.02% rate has much more source-count
# precision than the bounded 512-round champion census. The champion census is
# an identity/dose transfer check, not permission to inflate a fitting mean.
PREVALENCE_RATE = min(HEURISTIC_PREVALENCE_RATE, CHAMPION_PREVALENCE_RATE)
CHAMPION_CENSUS_PATH = (
    SERVER / "tests/data/s6_throw_full_hand_champion_census.v1.json")
CHAMPION_CENSUS_SHA256 = (
    "65eacf054f1093e884c1c5705bc16ca7ed7372c05423b89703234b91e3d7bf14")
SELECTOR_CONDITIONAL_MEAN = 0.306640625
SELECTOR_CONDITIONAL_SECOND_MOMENT = 0.91259765625
Z_ONE_SIDED_95 = 1.6448536269514722
Z_POWER_80 = 0.8416212335729143
RUN_LOG_DIR = SERVER / "runs/logs" / PREFLIGHT_RUN_ID
PACKET_PATH = RUN_LOG_DIR / "controller-packet.json"
CLAIM_PATH = RUN_LOG_DIR / "packet-review-request.txt"
FREEZE_ADMISSION_PATH = SERVER / "runs/locks" / \
    f"{PREFLIGHT_RUN_ID}.packet-freeze.consumed.json"
ADMISSION_PATH = SERVER / "runs/locks" / \
    f"{PREFLIGHT_RUN_ID}.admission.consumed.json"
RESULT_PATH = RUN_LOG_DIR / "capacity.json"


class ControllerRefused(RuntimeError):
    """The requested operation lacks exact identity or review authority."""


sha256 = BASE.sha256
stable_digest = BASE.stable_digest
write_exclusive = BASE.write_exclusive
require_regular_unlinked = BASE.require_regular_unlinked


def git(*args: str) -> str:
    return BASE.git(*args)


def git_is_ancestor(ancestor: str, descendant: str) -> bool:
    return BASE.git_is_ancestor(ancestor, descendant)


def parse_marker(path: os.PathLike | str, prefix: str,
                 expected: dict, *, label: str) -> dict:
    try:
        return BASE.parse_marker(path, prefix, expected, label=label)
    except BASE.ControllerRefused as exc:
        raise ControllerRefused(str(exc)) from exc


def source_paths() -> dict[str, Path]:
    if not fast.HAVE_FAST or fast._fast is None:
        raise ControllerRefused("compiled fast binary is unavailable")
    return {
        "controller": SCRIPT,
        "champion_census": CHAMPION_CENSUS_PATH,
        "protocol_utility": BASE.SCRIPT,
        "duel_core": CORE.SCRIPT,
        "broad_duel_validator": CORE.BASE.SCRIPT,
        "gate": SERVER / "shengji/ai/throw_full_hand_gate.py",
        "throw_policy": SERVER / "shengji/ai/throw_policy.py",
        "throw_source": SERVER / "shengji/ai/throw_sourcing.py",
        "registry": SERVER / "shengji/ai/registry.py",
        "mcbot": SERVER / "shengji/ai/mcbot.py",
        "memory": SERVER / "shengji/ai/memory.py",
        "evaluation": SERVER / "shengji/evaluation.py",
        "game": SERVER / "shengji/engine/game.py",
        "round": SERVER / "shengji/engine/round.py",
        "fast_binary": Path(fast._fast.__file__).resolve(),
    }


def champion_census_evidence() -> dict[str, object]:
    require_regular_unlinked(
        CHAMPION_CENSUS_PATH, label="S6 champion-trajectory census")
    if sha256(CHAMPION_CENSUS_PATH) != CHAMPION_CENSUS_SHA256:
        raise ControllerRefused("S6 champion census SHA-256 drift")
    try:
        payload = json.loads(CHAMPION_CENSUS_PATH.read_bytes())
    except (OSError, ValueError) as exc:
        raise ControllerRefused("S6 champion census is unreadable") from exc
    counts = payload.get("counts") if isinstance(payload, dict) else None
    rates = payload.get("rates") if isinstance(payload, dict) else None
    expected_cells = {
        "attacker:early": 0, "attacker:late": 6, "attacker:mid": 4,
        "defender:early": 0, "defender:late": 0, "defender:mid": 3,
    }
    if (payload.get("schema") !=
            "s6-throw-full-hand-champion-census-v1"
            or payload.get("git") !=
            "d65dd08750c611dd776ba71cc776834d37fd903e"
            or payload.get("score_free") is not True
            or payload.get("outcomes_published") is not False
            or payload.get("strength_claim") is not False
            or payload.get("whole_game_execution_authorized") is not False
            or not isinstance(counts, dict)
            or counts.get("deals") != CHAMPION_CENSUS_DEALS
            or counts.get("leads") != CHAMPION_CENSUS_LEADS
            or counts.get("triggered_deals") !=
            CHAMPION_CENSUS_TRIGGERED_DEALS
            or counts.get("triggered_leads") !=
            CHAMPION_CENSUS_TRIGGERED_LEADS
            or counts.get("cells") != expected_cells
            or not isinstance(rates, dict)
            or rates.get("triggered_deals") != CHAMPION_PREVALENCE_RATE
            or rates.get("triggered_leads") !=
            CHAMPION_CENSUS_TRIGGERED_LEADS / CHAMPION_CENSUS_LEADS):
        raise ControllerRefused("S6 champion census contract drift")
    return {
        "path": str(CHAMPION_CENSUS_PATH.relative_to(REPO)),
        "sha256": CHAMPION_CENSUS_SHA256,
        "policy": payload["design"]["policy"],
        "deals": counts["deals"],
        "leads": counts["leads"],
        "triggered_deals": counts["triggered_deals"],
        "triggered_leads": counts["triggered_leads"],
        "triggered_deal_rate": rates["triggered_deals"],
        "triggered_lead_rate": rates["triggered_leads"],
        "score_free": True,
        "strength_claim": False,
    }


def source_sha256s() -> dict[str, str]:
    return {name: sha256(path) for name, path in source_paths().items()}


def runtime_snapshot() -> dict[str, object]:
    if not fast.HAVE_FAST or fast._fast is None:
        raise ControllerRefused("compiled fast binary is unavailable")
    return {
        "host": platform.node(),
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "python_executable": str(Path(sys.executable).resolve()),
        "fast_required": True,
        "strict_voids_required": True,
        "fast_env_active": os.environ.get("SHENGJI_FAST") == "1",
        "strict_voids_active":
            os.environ.get("SHENGJI_REQUIRE_VOIDS") == "1",
        "compiled_binding_active": combos.decompose is fast.decompose,
        "fast_binary_sha256": sha256(Path(fast._fast.__file__).resolve()),
    }


def runtime_problems(runtime: object) -> list[str]:
    expected = {
        "host": EXPECTED_EXECUTION_HOST,
        "python": EXPECTED_PYTHON_VERSION,
        "implementation": "CPython",
        "python_executable": EXPECTED_PYTHON_EXECUTABLE,
        "fast_required": True,
        "strict_voids_required": True,
        "fast_env_active": True,
        "strict_voids_active": True,
        "compiled_binding_active": True,
        "fast_binary_sha256": EXPECTED_FAST_BINARY_SHA256,
    }
    return [] if runtime == expected else ["runtime is not exact reviewed Air"]


def require_air_runtime() -> dict[str, object]:
    runtime = runtime_snapshot()
    problems = runtime_problems(runtime)
    if problems:
        raise ControllerRefused("; ".join(problems))
    return runtime


def _uppercase_contract(bot) -> dict[str, bool | int | float | str | None]:
    values = {}
    for name in dir(bot):
        if not name.isupper():
            continue
        value = getattr(bot, name)
        if not isinstance(value, (bool, int, float, str, type(None))):
            raise ControllerRefused(f"non-serializable policy knob {name}")
        values[name] = value
    return values


def policy_contracts() -> dict[str, dict]:
    treatment = make_s6_full_hand_bot(treatment=True, seed=7)
    null = make_s6_full_hand_bot(treatment=False, seed=7)
    champion = CORE.make_arm("champion", 7)
    contracts = [_uppercase_contract(bot)
                 for bot in (treatment, null, champion)]
    if contracts[0] != contracts[1] or contracts[0] != contracts[2]:
        raise ControllerRefused("selective S6 arms changed champion knobs")
    ballots = [mc_ballot(bot).digest for bot in (treatment, null, champion)]
    if len(set(ballots)) != 1:
        raise ControllerRefused("selective S6 root ballot drift")
    return {
        label: {
            "policy": CORE.LABELS[label],
            "class": type(bot).__name__,
            "uppercase": contract,
            "root_ballot_digest": ballot,
            "s6_mode": mode,
        }
        for label, bot, contract, ballot, mode in zip(
            CORE.LABEL_ORDER, (treatment, null, champion), contracts, ballots,
            ("treatment", "matched_null", "off"), strict=True)
    }


def cluster_unit_mapping() -> dict[str, object]:
    """Declare the conservative map from census deals to screen clusters.

    The census observes one complete four-champion round.  The evaluator's
    independent unit is instead one deal seed played twice: treatment owns
    seats 0/2 in flip 0 and seats 1/3 in flip 1.  Thus one cluster exposes the
    treatment to all four seat roles once, matching the census's four-seat
    opportunity count.  Planning deliberately caps any number of S6 decisions
    in a deal at one affected cluster.  This is a fitting approximation, not
    an assertion that the post-trigger trajectories are distributionally
    identical; measured screen telemetry remains authoritative for dose.
    """
    return {
        "census_observation_unit":
            "one complete round with the literal champion in all four seats",
        "screen_independent_unit":
            "one deal seed evaluated in two mirrored complete rounds",
        "screen_primary_cluster_statistic": (
            "sum over both flips of treatment signed level utility minus "
            "the corresponding control sum for the same seed"),
        "flip_treatment_seats": {"0": [0, 2], "1": [1, 3]},
        "treatment_seat_exposures_per_cluster": 4,
        "census_seat_exposures_per_deal": 4,
        "planning_trigger_map": (
            "one census deal with at least one new full-hand S6 source maps "
            "to at most one affected mirrored cluster"),
        "multiple_triggers_capped_at_one_for_planning": True,
        "same_deal_seed_across_flips": True,
        "post_trigger_trajectory_equivalence_assumed": False,
        "actual_preflight_and_screen_telemetry_is_authoritative": True,
        "planning_only_not_strength_evidence": True,
    }


def planning_values() -> dict[str, object]:
    mean = PREVALENCE_RATE * SELECTOR_CONDITIONAL_MEAN
    second = PREVALENCE_RATE * SELECTOR_CONDITIONAL_SECOND_MOMENT
    sd = math.sqrt(second - mean * mean)
    mde = (Z_ONE_SIDED_95 + Z_POWER_80) * sd / math.sqrt(SCREEN_CLUSTERS)
    z = mean * math.sqrt(SCREEN_CLUSTERS) / sd - Z_ONE_SIDED_95
    power = 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))
    return {
        "screen_clusters": SCREEN_CLUSTERS,
        "natural_trigger_rate": PREVALENCE_RATE,
        "heuristic_trajectory_trigger_rate": HEURISTIC_PREVALENCE_RATE,
        "champion_trajectory_trigger_rate": CHAMPION_PREVALENCE_RATE,
        "champion_trajectory_triggered_deals":
            CHAMPION_CENSUS_TRIGGERED_DEALS,
        "champion_trajectory_deals": CHAMPION_CENSUS_DEALS,
        "expected_triggered_clusters": PREVALENCE_RATE * SCREEN_CLUSTERS,
        "expected_triggered_clusters_uses_one_per_deal_cap": True,
        "conditional_selector_mean": SELECTOR_CONDITIONAL_MEAN,
        "mixture_planning_mean": mean,
        "mixture_planning_sd": sd,
        "mde80_one_sided_95": mde,
        "planning_power_at_fitting_mean": power,
    }


def _logical_path(path: Path) -> str:
    try:
        return str(path.relative_to(REPO))
    except ValueError as exc:
        raise ControllerRefused(f"path is outside repository: {path}") from exc


def require_canonical_path(actual: os.PathLike | str, expected: Path, *,
                           label: str) -> None:
    if Path(actual).resolve() != expected.resolve():
        raise ControllerRefused(f"{label} path drift")


def freeze_admission_payload(*, expected_git: str,
                             selector_review_record: os.PathLike | str,
                             nonce: str,
                             created_unix_ns: int) -> dict:
    review = parse_marker(
        selector_review_record, SELECTOR_REVIEW_PREFIX,
        EXPECTED_SELECTOR_REVIEW, label="S6 full-hand selector review")
    if not git_is_ancestor(SELECTOR_GIT, expected_git):
        raise ControllerRefused("reviewed selector is not an ancestor")
    if (not isinstance(nonce, str) or len(nonce) != 32
            or any(char not in "0123456789abcdef" for char in nonce)):
        raise ControllerRefused("packet-freeze nonce is invalid")
    if (isinstance(created_unix_ns, bool)
            or not isinstance(created_unix_ns, int)
            or created_unix_ns <= 0):
        raise ControllerRefused("packet-freeze timestamp is invalid")
    payload = {
        "schema": FREEZE_ADMISSION_SCHEMA,
        "run_id": RUN_ID,
        "preflight_run_id": PREFLIGHT_RUN_ID,
        "git": expected_git,
        "controller_sha256": sha256(SCRIPT),
        "selector_review_sha256": review["sha256"],
        "champion_census_sha256": CHAMPION_CENSUS_SHA256,
        "packet_path": _logical_path(PACKET_PATH),
        "claim_path": _logical_path(CLAIM_PATH),
        "runtime": require_air_runtime(),
        "nonce": nonce,
        "created_unix_ns": created_unix_ns,
        "score_free": True,
        "outcomes_published": False,
        "preflight_execution_authorized": False,
        "screen_execution_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    payload["internal_sha256"] = stable_digest(payload)
    return payload


def freeze_admission_problems(
        payload: object, *, expected_git: str,
        selector_review_record: os.PathLike | str) -> list[str]:
    if not isinstance(payload, dict):
        return ["packet-freeze admission is not an object"]
    internal = payload.get("internal_sha256")
    without = dict(payload)
    without.pop("internal_sha256", None)
    if not isinstance(internal, str) or stable_digest(without) != internal:
        return ["packet-freeze admission internal SHA-256 drift"]
    try:
        expected = freeze_admission_payload(
            expected_git=expected_git,
            selector_review_record=selector_review_record,
            nonce=payload.get("nonce"),
            created_unix_ns=payload.get("created_unix_ns"))
    except Exception as exc:
        return [
            "cannot reconstruct packet-freeze admission: "
            f"{type(exc).__name__}: {exc}"]
    return [] if payload == expected else [
        "packet-freeze admission differs from reconstruction"]


def load_freeze_admission(*, expected_git: str,
                          selector_review_record: os.PathLike | str) -> dict:
    require_regular_unlinked(
        FREEZE_ADMISSION_PATH, label="S6 packet-freeze admission")
    try:
        payload = json.loads(FREEZE_ADMISSION_PATH.read_bytes())
    except (OSError, ValueError) as exc:
        raise ControllerRefused(
            "S6 packet-freeze admission is unreadable") from exc
    problems = freeze_admission_problems(
        payload, expected_git=expected_git,
        selector_review_record=selector_review_record)
    if problems:
        raise ControllerRefused("invalid packet-freeze admission: "
                                + "; ".join(problems))
    return payload


def freeze_admission_evidence(*, expected_git: str,
                              selector_review_record: os.PathLike | str
                              ) -> dict[str, object]:
    payload = load_freeze_admission(
        expected_git=expected_git,
        selector_review_record=selector_review_record)
    return {
        "path": _logical_path(FREEZE_ADMISSION_PATH),
        "sha256": sha256(FREEZE_ADMISSION_PATH),
        "internal_sha256": payload["internal_sha256"],
        "consumed": True,
    }


def packet_payload(*, expected_git: str,
                   selector_review_record: os.PathLike | str) -> dict:
    review = parse_marker(
        selector_review_record, SELECTOR_REVIEW_PREFIX,
        EXPECTED_SELECTOR_REVIEW, label="S6 full-hand selector review")
    if not git_is_ancestor(SELECTOR_GIT, expected_git):
        raise ControllerRefused("reviewed selector is not an ancestor")
    payload = {
        "schema": PACKET_SCHEMA,
        "run_id": RUN_ID,
        "preflight_run_id": PREFLIGHT_RUN_ID,
        "git": expected_git,
        "selector_git": SELECTOR_GIT,
        "selector_review": review,
        "packet_freeze_admission": freeze_admission_evidence(
            expected_git=expected_git,
            selector_review_record=selector_review_record),
        "champion_trajectory_census": champion_census_evidence(),
        "source_sha256s": source_sha256s(),
        "runtime": require_air_runtime(),
        "policy_contracts": policy_contracts(),
        "mechanism": {
            "search_gate": FULL_HAND_BOSS_NEAR_GATE,
            "actor_visible": True,
            "literal_champion_first": True,
            "candidate_zero_is_actual_champion_action": True,
            "matched_null_keeps_champion_action_after_equal_probe": True,
            "post_decision_rng_restored": True,
            "full_structured_ballot_remains_observable": True,
        },
        "preflight": {
            "seed0": PREFLIGHT_SEED0,
            "clusters": PREFLIGHT_CLUSTERS,
            "stream_stride": STREAM_STRIDE,
            "labels": list(CORE.LABEL_ORDER),
            "score_free": True,
            "outcomes_published": False,
            "admission_path": str(ADMISSION_PATH.relative_to(REPO)),
            "result_path": str(RESULT_PATH.relative_to(REPO)),
        },
        "proposed_screen": {
            "seed0": SCREEN_SEED0,
            "clusters": SCREEN_CLUSTERS,
            "shards": SHARD_COUNT,
            "clusters_per_shard": SCREEN_CLUSTERS // SHARD_COUNT,
            "labels": list(CORE.LABEL_ORDER),
            "primary": "paired signed whole-round level utility",
            "secondary": "whole-round game win rate",
            "selection_rule": (
                "one-sided 95% LCB > 0 versus literal champion and matched "
                "null; exact null/champion outcomes; both-role natural dose; "
                "complete work and no integrity failure"),
        },
        "planning": {
            **planning_values(),
            "cluster_unit_mapping": cluster_unit_mapping(),
            "basis": (
                "opened reusable-DEV selector distribution mixed with the "
                "independent score-free 50,000-deal heuristic prevalence; "
                "a 512-round literal-champion transfer census was higher, "
                "so sizing conservatively retains the lower heuristic rate. "
                "The per-deal rate maps to one affected two-flip cluster at "
                "most because treatment spans all four seats once per "
                "cluster; actual dose telemetry, not this approximation, "
                "controls interpretation"),
            "planning_only_not_strength_evidence": True,
        },
        "capacity": {
            "safety_factor": SAFETY_FACTOR,
            "screen_fleet_hour_cap": SCREEN_FLEET_HOUR_CAP,
            "screen_max_shard_hour_cap": SCREEN_MAX_SHARD_HOUR_CAP,
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
                    selector_review_record: os.PathLike | str) -> list[str]:
    try:
        expected = packet_payload(
            expected_git=expected_git,
            selector_review_record=selector_review_record)
    except Exception as exc:
        return [f"cannot reconstruct packet: {type(exc).__name__}: {exc}"]
    return [] if payload == expected else ["packet differs from reconstruction"]


def load_packet(path: os.PathLike | str, expected_sha256: str, *,
                expected_git: str,
                selector_review_record: os.PathLike | str) -> dict:
    source = Path(path)
    require_regular_unlinked(source, label="S6 full-hand capacity packet")
    if sha256(source) != expected_sha256:
        raise ControllerRefused("S6 full-hand packet SHA-256 drift")
    payload = json.loads(source.read_bytes())
    problems = packet_problems(
        payload, expected_git=expected_git,
        selector_review_record=selector_review_record)
    if problems:
        raise ControllerRefused("invalid packet: " + "; ".join(problems))
    return payload


def packet_review_claim(*, expected_git: str, packet_sha256: str) -> dict:
    return {
        "git": expected_git,
        "independent_review": True,
        "one_score_free_preflight_authorized": True,
        "packet_sha256": packet_sha256,
        "production_deployment": False,
        "production_promotion": False,
        "run_id": RUN_ID,
        "schema": "s6-throw-full-hand-preflight-packet-review-v2",
        "screen_execution_authorized": False,
        "strength_claim": False,
        "verdict": "PASS",
    }


def capacity_review_claim(*, result: dict, result_sha256: str,
                          packet_sha256: str) -> dict:
    """Exact bounded claim an independent capacity reviewer may publish."""
    projection = result["projection"]
    passed = result.get("capacity_pass") is True
    return {
        "capacity_pass": passed,
        "capacity_result_internal_sha256": result["internal_sha256"],
        "capacity_result_sha256": result_sha256,
        "elapsed_seconds": result["elapsed_seconds"],
        "git": result["git"],
        "independent_review": True,
        "null_champion_exact_outcomes":
            result["null_champion_exact_outcomes"],
        "one_screen_packet_design_authorized": passed,
        "packet_sha256": packet_sha256,
        "preflight_clusters": PREFLIGHT_CLUSTERS,
        "production_deployment": False,
        "production_promotion": False,
        "run_id": RUN_ID,
        "schema": "s6-throw-full-hand-capacity-review-v2",
        "score_free": True,
        "screen_clusters": SCREEN_CLUSTERS,
        "screen_execution_authorized": False,
        "screen_fleet_hours": projection["screen_fleet_hours"],
        "screen_max_shard_hours": projection["screen_max_shard_hours"],
        "strength_claim": False,
        "verdict": "PASS" if passed else "HOLD",
    }


def _sum_plain(records: list[dict], side: str) -> dict:
    return BASE._sum_plain_counters(records, side)


def _sum_s6(records: list[dict], side: str) -> dict:
    modes = {record[side]["s6_throw"]["mode"] for record in records}
    if len(modes) != 1:
        raise ControllerRefused("S6 telemetry mode drift")
    totals = {field: 0 for field in S6_THROW_COUNTER_FIELDS}
    for record in records:
        for field in totals:
            totals[field] += record[side]["s6_throw"][field]
    return {"mode": next(iter(modes)), **totals}


def measure_preflight(packet: dict, *, clock=time.perf_counter) -> dict:
    started = clock()
    by_label = {label: [] for label in CORE.LABEL_ORDER}
    null_exact = True
    outcome_fields = (
        "banker", "attacker_points", "winner_team", "level_change", "won",
        "level_utility",
    )
    for cluster_index in range(PREFLIGHT_CLUSTERS):
        seed = PREFLIGHT_SEED0 + STREAM_STRIDE * cluster_index
        cluster = {}
        for label in CORE.LABEL_ORDER:
            records = CORE.play_arm_cluster(
                label, seed, run_id=PREFLIGHT_RUN_ID)
            for flip, record in enumerate(records):
                problems = CORE.record_problems(
                    record, expected_label=label, expected_seed=seed,
                    expected_flip=flip, expected_run_id=PREFLIGHT_RUN_ID)
                if problems:
                    raise ControllerRefused(
                        "invalid preflight row: " + "; ".join(problems))
                mode = {"treatment": "treatment",
                        "matched_null": "matched_null",
                        "champion": "off"}[label]
                if (CORE.counter_problems(record["arm"], expected_mode=mode)
                        or CORE.counter_problems(
                            record["opp"], expected_mode="off")):
                    raise ControllerRefused("preflight exact-work failure")
            cluster[label] = records
            by_label[label].extend(records)
        null_exact &= all(
            tuple(left[field] for field in outcome_fields)
            == tuple(right[field] for field in outcome_fields)
            for left, right in zip(
                cluster["matched_null"], cluster["champion"], strict=True))
        print(json.dumps({
            "event": "s6-full-hand-score-free-progress-v2",
            "clusters_complete": cluster_index + 1,
            "clusters_total": PREFLIGHT_CLUSTERS,
        }, sort_keys=True), flush=True)
    elapsed = clock() - started
    if not math.isfinite(elapsed) or elapsed <= 0:
        raise ControllerRefused("preflight elapsed time is invalid")
    counts = {
        label: {
            "records_discarded": len(records),
            "arm": _sum_plain(records, "arm"),
            "opp": _sum_plain(records, "opp"),
            "arm_s6": _sum_s6(records, "arm"),
            "opp_s6": _sum_s6(records, "opp"),
        }
        for label, records in by_label.items()
    }
    measured = PREFLIGHT_CLUSTERS * len(CORE.LABEL_ORDER)
    target = SCREEN_CLUSTERS * len(CORE.LABEL_ORDER)
    fleet_hours = elapsed / measured * target * SAFETY_FACTOR / 3_600.0
    max_shard_hours = fleet_hours / SHARD_COUNT
    treatment = counts["treatment"]["arm_s6"]
    null = counts["matched_null"]["arm_s6"]
    capacity_pass = bool(
        null_exact and treatment["short_searches"] == 0
        and null["short_searches"] == 0
        and null["treatment_overrides"] == 0
        and null["matched_noops"] == null["searched_triggers"]
        and fleet_hours <= SCREEN_FLEET_HOUR_CAP
        and max_shard_hours <= SCREEN_MAX_SHARD_HOUR_CAP)
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
        "null_champion_exact_outcomes": null_exact,
        "projection": {
            "safety_factor": SAFETY_FACTOR,
            "screen_clusters": SCREEN_CLUSTERS,
            "screen_fleet_hours": fleet_hours,
            "screen_max_shard_hours": max_shard_hours,
            "screen_fleet_hour_cap": SCREEN_FLEET_HOUR_CAP,
            "screen_max_shard_hour_cap": SCREEN_MAX_SHARD_HOUR_CAP,
        },
        "capacity_pass": capacity_pass,
        "supports_screen_packet_review": capacity_pass,
        "screen_packet_design_authorized": False,
        "screen_execution_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    result["internal_sha256"] = stable_digest(result)
    problems = BASE.score_free_result_problems(result)
    if problems:
        raise ControllerRefused(
            "preflight attempted score publication: " + "; ".join(problems))
    return result


def require_clean_exact_git(expected_git: str) -> None:
    if git("rev-parse", "HEAD") != expected_git:
        raise ControllerRefused("controller git identity drift")
    if git("status", "--porcelain", "--untracked-files=all"):
        raise ControllerRefused("controller worktree is dirty")


def require_execution_runtime() -> None:
    if (os.environ.get("SHENGJI_FAST") != "1"
            or os.environ.get("SHENGJI_REQUIRE_VOIDS") != "1"
            or not fast.HAVE_FAST or fast._fast is None
            or combos.decompose is not fast.decompose):
        raise ControllerRefused("compiled strict runtime is not active")
    require_air_runtime()


def freeze_command(args) -> None:
    require_canonical_path(
        args.out, PACKET_PATH, label="packet-freeze output")
    require_canonical_path(
        args.claim_out, CLAIM_PATH, label="packet-freeze claim output")
    require_clean_exact_git(args.expected_git)
    for path, label in ((PACKET_PATH, "packet"), (CLAIM_PATH, "claim")):
        if os.path.lexists(path) or os.path.lexists(str(path) + ".partial"):
            raise ControllerRefused(
                f"packet-freeze canonical {label} path is already consumed")
    admission = freeze_admission_payload(
        expected_git=args.expected_git,
        selector_review_record=args.selector_review_record,
        nonce=secrets.token_hex(16),
        created_unix_ns=time.time_ns())
    write_exclusive(FREEZE_ADMISSION_PATH, admission)
    payload = packet_payload(
        expected_git=args.expected_git,
        selector_review_record=args.selector_review_record)
    write_exclusive(PACKET_PATH, payload)
    packet_sha = sha256(PACKET_PATH)
    claim = packet_review_claim(
        expected_git=args.expected_git, packet_sha256=packet_sha)
    write_exclusive(CLAIM_PATH, claim)
    print(json.dumps({"status": "FROZEN_NO_EXECUTION_AUTHORITY",
                      "packet_freeze_admission_sha256":
                          sha256(FREEZE_ADMISSION_PATH),
                      "packet_sha256": packet_sha,
                      "claim": claim}, sort_keys=True))


def verify_command(args) -> None:
    require_canonical_path(
        args.packet, PACKET_PATH, label="packet verification input")
    require_clean_exact_git(args.expected_git)
    payload = load_packet(
        args.packet, args.packet_sha256, expected_git=args.expected_git,
        selector_review_record=args.selector_review_record)
    print(json.dumps({"status": "VERIFIED_NO_EXECUTION_AUTHORITY",
                      "internal_sha256": payload["internal_sha256"]},
                     sort_keys=True))


def preflight_command(args) -> None:
    require_canonical_path(
        args.packet, PACKET_PATH, label="preflight packet input")
    require_clean_exact_git(args.expected_git)
    require_execution_runtime()
    packet = load_packet(
        args.packet, args.packet_sha256, expected_git=args.expected_git,
        selector_review_record=args.selector_review_record)
    expected_review = packet_review_claim(
        expected_git=args.expected_git, packet_sha256=args.packet_sha256)
    review = parse_marker(
        args.packet_review_record, PACKET_REVIEW_PREFIX, expected_review,
        label="S6 full-hand preflight packet review")
    if Path(args.out).resolve() != RESULT_PATH.resolve():
        raise ControllerRefused("preflight output path drift")
    if (os.path.lexists(args.out)
            or os.path.lexists(str(args.out) + ".partial")):
        raise ControllerRefused("preflight result path is already consumed")
    admission = {
        "schema": ADMISSION_SCHEMA,
        "run_id": RUN_ID,
        "git": args.expected_git,
        "packet_sha256": args.packet_sha256,
        "packet_review_sha256": review["sha256"],
        "nonce": secrets.token_hex(16),
        "score_free": True,
        "screen_execution_authorized": False,
    }
    admission["internal_sha256"] = stable_digest(admission)
    write_exclusive(ADMISSION_PATH, admission)
    result = measure_preflight(packet)
    result["admission_internal_sha256"] = admission["internal_sha256"]
    prior = result.pop("internal_sha256")
    if prior == stable_digest(result):
        raise ControllerRefused("admission mutation did not change result hash")
    result["internal_sha256"] = stable_digest(result)
    problems = BASE.score_free_result_problems(result)
    if problems:
        raise ControllerRefused(
            "admission-bound result is not score-free: "
            + "; ".join(problems))
    write_exclusive(args.out, result)
    print(json.dumps({
        "status": "COMPLETE_SCORE_FREE_CAPACITY",
        "capacity_pass": result["capacity_pass"],
        "result_sha256": sha256(args.out),
        "internal_sha256": result["internal_sha256"],
    }, sort_keys=True), flush=True)


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser()
    sub = root.add_subparsers(dest="command", required=True)
    for name in ("freeze", "verify"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--expected-git", required=True)
        cmd.add_argument("--selector-review-record", required=True)
        if name == "freeze":
            cmd.add_argument("--out", required=True)
            cmd.add_argument("--claim-out", required=True)
        else:
            cmd.add_argument("--packet", required=True)
            cmd.add_argument("--packet-sha256", required=True)
    run = sub.add_parser("run-preflight")
    run.add_argument("--expected-git", required=True)
    run.add_argument("--selector-review-record", required=True)
    run.add_argument("--packet", required=True)
    run.add_argument("--packet-sha256", required=True)
    run.add_argument("--packet-review-record", required=True)
    run.add_argument("--out", required=True)
    return root


def main() -> None:
    args = parser().parse_args()
    if args.command == "freeze":
        freeze_command(args)
    elif args.command == "verify":
        verify_command(args)
    else:
        preflight_command(args)


if __name__ == "__main__":
    main()
