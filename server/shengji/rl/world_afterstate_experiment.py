"""Immutable E3/E4 design derived from one score-free capacity receipt.

The builder chooses only resource mechanics: worker count, one existing model
shape, batch size, and a bounded population.  It never reads continuation
outcomes or model scores.  The returned freeze authorizes nothing until a
separate exact-head source+freeze review admits one scientific execution.
"""

from __future__ import annotations

import hashlib
from typing import Any, Mapping

from .belief_contract import canonical_json_bytes
from .world_afterstate_capacity import validate_capacity_receipt
from .world_afterstate_model import CAPACITY_SHAPES
from .world_afterstate_training import WorldAfterstateTrainingConfigV0


FREEZE_SCHEMA = "world-afterstate-e3-e4-freeze-v0"
NAMESPACE = "world-afterstate-e3-e4-v0"
CAPACITY_MEMORY_LIMIT_BYTES = 30 * 1024**3
LABEL_WALL_CAP_SECONDS = 8 * 60 * 60
TRAINING_SOFT_DEADLINE_SECONDS = 8 * 60 * 60
TRAINING_HARD_WALL_CAP_SECONDS = 12 * 60 * 60
REPORT_WALL_CAP_SECONDS = 2 * 60 * 60
INDEPENDENT_VERIFICATION_WALL_CAP_SECONDS = 8 * 60 * 60
TRAINING_DEVICE_HOUR_CAP = 24
STATE_GROUP_COUNT = 520
FOLD_COUNTS = {
    "train": 364,
    "calibration": 52,
    "report": 52,
    "provider-audit": 52,
}
SOURCE_COUNTS = {
    "production-policy": 312,
    "reviewed-pt-sol0": 156,
    "mechanics-hard": 52,
    "human-complete-provenance": 0,
}
SOURCE_FOLD_COUNTS = {
    "train": {
        "production-policy": 219,
        "reviewed-pt-sol0": 109,
        "mechanics-hard": 36,
    },
    "calibration": {
        "production-policy": 31,
        "reviewed-pt-sol0": 16,
        "mechanics-hard": 5,
    },
    "report": {
        "production-policy": 31,
        "reviewed-pt-sol0": 16,
        "mechanics-hard": 5,
    },
    "provider-audit": {
        "production-policy": 31,
        "reviewed-pt-sol0": 15,
        "mechanics-hard": 6,
    },
}
REPETITIONS_BY_FOLD = {
    "train": 2,
    "calibration": 2,
    "report": 4,
    "provider-audit": 8,
}
INITIALIZATION_SEEDS = tuple(
    int.from_bytes(hashlib.sha256(
        f"{NAMESPACE}|member|{index}".encode("ascii")).digest()[:8], "big")
    for index in range(8)
)
AUTHORITY = {
    "population_generation_authorized": False,
    "continuation_dataset_generation_authorized": False,
    "scientific_training_authorized": False,
    "report_opening_authorized": False,
    "gameplay_authorized": False,
    "strength_claim_authorized": False,
    "merge_authorized": False,
    "promotion_authorized": False,
    "deployment_authorized": False,
    "r5_authorized": False,
}
EXPERIMENT_SOURCE_KEYS = (
    "afterstate", "sources", "label", "model", "population",
    "population_packet", "population_builder", "dataset", "controller",
    "training", "training_controller", "checkpoint", "evaluation",
    "controls", "terminal", "terminal_controller", "admission",
    "scientific_controller",
    "experiment", "launcher", "population_launcher",
    "scientific_launcher",
    "engine_round", "engine_legal", "engine_fast", "engine_ballot",
    "ai_mcbot", "ai_registry",
)
EXPERIMENT_RUNTIME_KEYS = {
    "host", "platform", "python", "torch", "device", "cpu_count",
    "torch_threads", "torch_interop_threads", "environment",
    "python_executable", "python_executable_sha256", "fast_router_path",
    "fast_router_sha256", "native_path", "native_sha256",
    "compiled_engine_active", "safe_path", "dont_write_bytecode",
    "pythonpath_absent",
}


class WorldAfterstateExperimentError(ValueError):
    """The capacity binding, resource derivation, or freeze drifted."""


def _sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _strict_sha(value: object, label: str, *, length: int = 64) -> str:
    if type(value) is not str or len(value) != length \
            or any(char not in "0123456789abcdef" for char in value):
        raise WorldAfterstateExperimentError(f"{label} drift")
    return value


def reviewed_teacher_binding(raw: bytes, *, model: str) -> dict[str, str]:
    """Bind one already-reviewed complete PT report without consuming rows."""
    if model not in ("gpt-5.6-sol", "gpt-5.6-luna") or type(raw) is not bytes:
        raise WorldAfterstateExperimentError("teacher binding request drift")
    try:
        import json
        value = json.loads(raw.decode("ascii"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise WorldAfterstateExperimentError(
            "teacher report is not canonical JSON") from exc
    if type(value) is not dict or canonical_json_bytes(value) != raw:
        raise WorldAfterstateExperimentError(
            "teacher report is not canonical JSON")
    expected_schema = (
        "privileged-teacher-sol0-open-dev-v1" if model == "gpt-5.6-sol"
        else "privileged-teacher-luna0-open-dev-v1")
    design = value.get("design")
    if value.get("schema") != expected_schema \
            or value.get("status") != "COMPLETE" \
            or value.get("completed_record_count") != 52 \
            or value.get("incomplete_record_count") != 0 \
            or type(design) is not dict or design.get("model") != model \
            or set(value.get("authority", {}).values()) != {False}:
        raise WorldAfterstateExperimentError("teacher report identity drift")
    body = {key: item for key, item in value.items()
            if key != "report_sha256"}
    internal = _strict_sha(
        value.get("report_sha256"), "teacher report SHA-256")
    if _sha_bytes(canonical_json_bytes(body)) != internal:
        raise WorldAfterstateExperimentError(
            "teacher report reconstruction drift")
    execution_git = _strict_sha(
        design.get("execution_git"), "teacher execution Git", length=40)
    return {
        "external_sha256": _sha_bytes(raw),
        "report_sha256": internal,
        "execution_git": execution_git,
    }


def _candidate_upper_bound(capacity: Mapping[str, Any]) -> int:
    try:
        value = capacity["composed_measurement"][
            "candidate_count_distribution"]["maximum"]
    except (KeyError, TypeError) as exc:
        raise WorldAfterstateExperimentError(
            "capacity candidate bound drift") from exc
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise WorldAfterstateExperimentError(
            "capacity candidate bound drift")
    return value


def _label_workers(capacity: Mapping[str, Any]) -> tuple[int, int]:
    """Choose a conservative all-core worker count from measured peak delta."""
    runtime = capacity["runtime"]
    memory = capacity["aggregate_memory"]
    cpu_count = runtime["cpu_count"]
    baseline = memory["start_current_bytes"]
    incremental_peak = max(
        1, memory["finish_peak_bytes"] - baseline)
    memory_workers = max(
        1, (CAPACITY_MEMORY_LIMIT_BYTES - baseline) // incremental_peak)
    workers = min(16, cpu_count, memory_workers)
    if workers <= 0:
        raise WorldAfterstateExperimentError(
            "capacity cannot fit one label worker")
    return workers, incremental_peak


def _model_choice(capacity: Mapping[str, Any]) -> tuple[str, int, int]:
    rows = capacity["model_measurements"]
    by_shape: dict[str, list[Mapping[str, Any]]] = {
        name: [] for name in CAPACITY_SHAPES}
    for row in rows:
        by_shape[row["shape"]].append(row)
    best_small = max(
        by_shape["small"], key=lambda row: row["examples_per_second_ppm"])
    best_medium = max(
        by_shape["medium"], key=lambda row: row["examples_per_second_ppm"])
    # Medium is the fixed V0 preference when it retains at least half of the
    # small model's mechanics throughput.  Otherwise the receipt selects small.
    chosen = best_medium if (
        best_medium["examples_per_second_ppm"] * 2
        >= best_small["examples_per_second_ppm"]
    ) else best_small
    return (str(chosen["shape"]), int(chosen["batch_size"]),
            int(chosen["examples_per_second_ppm"]))


def _training_config() -> WorldAfterstateTrainingConfigV0:
    return WorldAfterstateTrainingConfigV0(
        learning_rate_ppb=1_000_000,
        weight_decay_ppb=10_000_000,
        gradient_norm_milli=1_000,
        max_epochs=40,
        early_stop_patience=5,
        minimum_improvement_nanonats=100_000,
    )


def build_experiment_freeze(
        capacity_raw: bytes, population_packet_raw: bytes, *, source_git: str,
        experiment_source_sha256s: Mapping[str, str],
        experiment_runtime: Mapping[str, Any],
        pt_sol0_external_sha256: str, pt_sol0_report_sha256: str,
        pt_sol0_execution_git: str,
        pt_luna0_external_sha256: str, pt_luna0_report_sha256: str,
        pt_luna0_execution_git: str) -> dict[str, Any]:
    """Build the only E3/E4 freeze shape admitted by this source."""
    try:
        import json
        capacity = json.loads(capacity_raw.decode("ascii"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise WorldAfterstateExperimentError(
            "capacity receipt is not canonical JSON") from exc
    if type(capacity) is not dict \
            or canonical_json_bytes(capacity) != capacity_raw:
        raise WorldAfterstateExperimentError(
            "capacity receipt is not canonical JSON")
    validate_capacity_receipt(capacity)
    try:
        population_packet = json.loads(population_packet_raw.decode("ascii"))
    except (AttributeError, UnicodeDecodeError, ValueError) as exc:
        raise WorldAfterstateExperimentError(
            "population packet is not canonical JSON") from exc
    if type(population_packet) is not dict \
            or canonical_json_bytes(population_packet) \
            != population_packet_raw:
        raise WorldAfterstateExperimentError(
            "population packet is not canonical JSON")
    from .world_afterstate_population_packet import (
        validate_population_packet_identity)
    validate_population_packet_identity(population_packet)
    _strict_sha(source_git, "experiment source Git", length=40)
    if type(experiment_source_sha256s) is not dict \
            or set(experiment_source_sha256s) != set(EXPERIMENT_SOURCE_KEYS):
        raise WorldAfterstateExperimentError(
            "experiment source population drift")
    for key, digest in experiment_source_sha256s.items():
        _strict_sha(digest, f"experiment source {key}")
    capacity_runtime = capacity["runtime"]
    if type(experiment_runtime) is not dict \
            or set(experiment_runtime) != EXPERIMENT_RUNTIME_KEYS \
            or experiment_runtime.get("host") != capacity_runtime["host"] \
            or experiment_runtime.get("platform") \
            != capacity_runtime["platform"] \
            or experiment_runtime.get("python") \
            != capacity_runtime["python"] \
            or experiment_runtime.get("torch") != capacity_runtime["torch"] \
            or experiment_runtime.get("device") \
            != capacity_runtime["device"] \
            or experiment_runtime.get("cpu_count") \
            != capacity_runtime["cpu_count"] \
            or experiment_runtime.get("torch_threads") \
            != capacity_runtime["torch_threads"] \
            or experiment_runtime.get("torch_interop_threads") \
            != capacity_runtime["torch_interop_threads"] \
            or experiment_runtime.get("environment") \
            != capacity_runtime["environment"] \
            or any(experiment_runtime.get(key) != capacity_runtime[key]
                   for key in ("python_executable_sha256",
                               "fast_router_sha256", "native_sha256")) \
            or any(experiment_runtime.get(key) is not True for key in (
                "compiled_engine_active", "safe_path", "dont_write_bytecode",
                "pythonpath_absent")) \
            or any(type(experiment_runtime.get(key)) is not str
                   or not experiment_runtime[key] for key in (
                       "python_executable", "fast_router_path", "native_path")):
        raise WorldAfterstateExperimentError(
            "experiment runtime differs from capacity mechanics")
    for label, value, length in (
        ("PT-Sol external SHA", pt_sol0_external_sha256, 64),
        ("PT-Sol report SHA", pt_sol0_report_sha256, 64),
        ("PT-Sol Git", pt_sol0_execution_git, 40),
        ("PT-Luna external SHA", pt_luna0_external_sha256, 64),
        ("PT-Luna report SHA", pt_luna0_report_sha256, 64),
        ("PT-Luna Git", pt_luna0_execution_git, 40),
    ):
        _strict_sha(value, label, length=length)
    packet_teacher = population_packet["pt_sol0"]
    packet_population = population_packet["population_manifest"]
    if population_packet["source_git"] != source_git \
            or packet_teacher != {
                "external_sha256": pt_sol0_external_sha256,
                "report_sha256": pt_sol0_report_sha256,
                "execution_git": pt_sol0_execution_git,
                "state_source_only": True,
                "numeric_label_authority": False,
            } \
            or packet_population["group_count"] != STATE_GROUP_COUNT \
            or packet_population["fold_counts"] != FOLD_COUNTS \
            or packet_population["source_counts"] != SOURCE_COUNTS \
            or packet_population["source_fold_counts"] \
            != SOURCE_FOLD_COUNTS:
        raise WorldAfterstateExperimentError(
            "population packet differs from frozen design")
    if sum(FOLD_COUNTS.values()) != STATE_GROUP_COUNT \
            or sum(SOURCE_COUNTS.values()) != STATE_GROUP_COUNT \
            or {fold: sum(counts.values())
                for fold, counts in SOURCE_FOLD_COUNTS.items()} \
            != FOLD_COUNTS \
            or {source: sum(counts[source] for counts
                            in SOURCE_FOLD_COUNTS.values())
                for source, count in SOURCE_COUNTS.items() if count} \
            != {source: count for source, count in SOURCE_COUNTS.items()
                if count}:
        raise WorldAfterstateExperimentError(
            "experiment population arithmetic drift")
    candidate_upper = _candidate_upper_bound(capacity)
    label_workers, incremental_peak = _label_workers(capacity)
    complete = capacity["composed_measurement"]["complete_continuation"]
    measured_wall_ns = complete["wall_nanoseconds"]
    conservative_wall_ns = measured_wall_ns * 2
    required_continuations = candidate_upper * sum(
        FOLD_COUNTS[fold] * repetitions
        for fold, repetitions in REPETITIONS_BY_FOLD.items())
    projected_label_wall_ns = (
        required_continuations * conservative_wall_ns + label_workers - 1
    ) // label_workers
    if projected_label_wall_ns > LABEL_WALL_CAP_SECONDS * 10**9:
        raise WorldAfterstateExperimentError(
            "capacity cannot fit the minimum diverse E3/E4 population")
    shape, batch_size, examples_per_second_ppm = _model_choice(capacity)
    config = _training_config()
    body = {
        "schema": FREEZE_SCHEMA,
        "namespace": NAMESPACE,
        "source_git": source_git,
        "source_sha256s": dict(sorted(experiment_source_sha256s.items())),
        "runtime": dict(experiment_runtime),
        "capacity": {
            "external_sha256": _sha_bytes(capacity_raw),
            "source_git": capacity["git"],
            "host": capacity["runtime"]["host"],
            "runtime": capacity["runtime"],
            "source_sha256s": capacity["source_sha256s"],
            "outcome_blind": True,
        },
        "population_packet": {
            "external_sha256": _sha_bytes(population_packet_raw),
            "packet_sha256": population_packet["packet_sha256"],
            "population_manifest_external_sha256":
                packet_population["external_sha256"],
            "population_manifest_sha256":
                packet_population["manifest_sha256"],
            "audit_manifest_external_sha256":
                population_packet["audit_manifest"]["external_sha256"],
            "audit_manifest_sha256":
                population_packet["audit_manifest"]["manifest_sha256"],
            "selection_outcome_blind": True,
            "outcome_opened": False,
        },
        "teacher_state_sources": {
            "pt_sol0": {
                "external_sha256": pt_sol0_external_sha256,
                "report_sha256": pt_sol0_report_sha256,
                "execution_git": pt_sol0_execution_git,
                "role": "reviewed stronger full-game trajectory source",
                "numeric_label_authority": False,
            },
            "pt_luna0": {
                "external_sha256": pt_luna0_external_sha256,
                "report_sha256": pt_luna0_report_sha256,
                "execution_git": pt_luna0_execution_git,
                "role": "descriptive provider candidate only",
                "numeric_label_authority": False,
            },
        },
        "population": {
            "state_group_count": STATE_GROUP_COUNT,
            "fold_counts": dict(FOLD_COUNTS),
            "source_counts": dict(SOURCE_COUNTS),
            "source_fold_counts": {
                fold: dict(counts)
                for fold, counts in SOURCE_FOLD_COUNTS.items()
            },
            "selection": (
                "sha256(actor-visible decision identity before outcomes); "
                "deal-grouped quota fill in canonical seed order"),
            "required_axes": {
                "trump_ranks": 13,
                "trump_suits": ["C", "D", "H", "S", "NT"],
                "root_teams": ["attacker", "defender"],
                "play_phases": ["early", "middle", "late"],
                "positions": ["lead", "follow"],
            },
            "human_target_rows": 0,
            "human_exclusion_reason": (
                "no frozen complete-hidden-state plus transcript provenance"),
            "complete_production_ballot_required": True,
            "protected_incumbent_index": 0,
            "world_occurrences_per_state_group": 1,
            "world_source": (
                "exact complete world from the selected reviewed trajectory; "
                "no REF-C or learned-BELIEF sampling in E3/E4"),
            "continuation_repetitions_with_replacement": True,
        },
        "labels": {
            "owner": "engine terminal attacker_points",
            "continuation_policy": "mc-strong",
            "allocation_provider": "uniform-engine",
            "allocation_provider_gate": (
                "SELECT_UNIFORM_ENGINE_NO_ELIGIBLE_NUMERIC_PT_ALLOCATOR"),
            "allocation_note": (
                "PT-Sol/Luna policy utility does not certify calibrated "
                "numeric allocation; their actions/prose are never labels"),
            "provider_audit_owner": "disjoint-higher-work-engine-fold",
            "repetitions_by_fold": dict(REPETITIONS_BY_FOLD),
            "candidate_upper_bound": candidate_upper,
            "required_continuations_upper_bound": required_continuations,
            "workers": label_workers,
            "measured_one_continuation_wall_nanoseconds": measured_wall_ns,
            "conservative_wall_multiplier": 2,
            "projected_wall_nanoseconds": projected_label_wall_ns,
            "wall_cap_seconds": LABEL_WALL_CAP_SECONDS,
            "deadline_behavior": (
                "incomplete population cannot seal; admission is spent and "
                "the same namespace cannot retry"),
            "per_worker_incremental_peak_proxy_bytes": incremental_peak,
            "common_random_numbers_across_sibling_actions": True,
        },
        "learner": {
            "head": "204-category-V_world_after-only",
            "shape": shape,
            "shape_values": {
                "public_hidden": CAPACITY_SHAPES[shape].public_hidden,
                "history_hidden": CAPACITY_SHAPES[shape].history_hidden,
                "world_hidden": CAPACITY_SHAPES[shape].world_hidden,
                "perspective_hidden":
                    CAPACITY_SHAPES[shape].perspective_hidden,
                "head_hidden": CAPACITY_SHAPES[shape].head_hidden,
            },
            "batch_size": batch_size,
            "capacity_examples_per_second_ppm": examples_per_second_ppm,
            "initialization_seeds": list(INITIALIZATION_SEEDS),
            "member_count": 8,
            "fresh_initialization": True,
            "common_epoch_selection": True,
            "member_drop_allowed": False,
            "config": config.payload(),
            "training_device_hour_cap": TRAINING_DEVICE_HOUR_CAP,
            "soft_deadline_seconds": TRAINING_SOFT_DEADLINE_SECONDS,
            "hard_wall_cap_seconds": TRAINING_HARD_WALL_CAP_SECONDS,
            "deadline_behavior": (
                "finish the current complete eight-member epoch, then seal "
                "the best common epoch with truncated_by_deadline=true; "
                "truncation never counts as convergence and at most one "
                "complete common epoch may use the reviewed grace window"),
        },
        "gates": {
            "primary": (
                "paired report-fold categorical NLL improvement over a "
                "train-only role/surface/trump/points prior; deal-bootstrap "
                "one-sided 95% lower bound strictly positive"),
            "seed_stability": "at least six of eight member means positive",
            "action_usefulness": (
                "lower expected-utility error and simple regret against the "
                "disjoint provider-audit engine fold"),
            "protected_incumbent": "no positive simple-regret regression",
            "bootstrap_replicates": 10_000,
            "report_unit": "deal",
            "search_final_authority": True,
            "belief_required": False,
            "report_wall_cap_seconds": REPORT_WALL_CAP_SECONDS,
            "report_deadline_behavior": (
                "attempt is durable before held-out bytes open; expiry "
                "preserves the consumed attempt and cannot seal a terminal"),
            "independent_verification_wall_cap_seconds":
                INDEPENDENT_VERIFICATION_WALL_CAP_SECONDS,
            "independent_verification_reconstructs_all_continuations": True,
        },
        "negative_controls": {
            "geometry_preserving_label_permutation": "must fail primary",
            "pre_action_state_replacement": "must lose action ranking",
            "complete_world_shuffle": (
                "must lose hidden-world-sensitive strata"),
            "root_rotation": "bytes and predictions invariant",
            "mutations": [
                "transition", "ballot", "continuation", "perspective",
                "utility"],
        },
        "terminal_authority_if_pass": (
            "one later frozen E5a known-world mechanism review only"),
        "authority": dict(AUTHORITY),
    }
    return {**body, "freeze_sha256": _sha_bytes(canonical_json_bytes(body))}


def validate_experiment_freeze(
        value: Mapping[str, Any], capacity_raw: bytes,
        population_packet_raw: bytes) -> None:
    """Rebuild the complete freeze from its bound immutable inputs."""
    if type(value) is not dict or set(value) != {
            "schema", "namespace", "source_git", "source_sha256s", "runtime",
            "capacity",
            "population_packet",
            "teacher_state_sources", "population", "labels", "learner",
            "gates", "negative_controls", "terminal_authority_if_pass",
            "authority", "freeze_sha256"}:
        raise WorldAfterstateExperimentError(
            "experiment freeze schema drift")
    if value.get("authority") != AUTHORITY:
        raise WorldAfterstateExperimentError(
            "experiment freeze authority drift")
    sol = value.get("teacher_state_sources", {}).get("pt_sol0", {})
    luna = value.get("teacher_state_sources", {}).get("pt_luna0", {})
    expected = build_experiment_freeze(
        capacity_raw, population_packet_raw,
        source_git=value.get("source_git"),
        experiment_source_sha256s=value.get("source_sha256s"),
        experiment_runtime=value.get("runtime"),
        pt_sol0_external_sha256=sol.get("external_sha256"),
        pt_sol0_report_sha256=sol.get("report_sha256"),
        pt_sol0_execution_git=sol.get("execution_git"),
        pt_luna0_external_sha256=luna.get("external_sha256"),
        pt_luna0_report_sha256=luna.get("report_sha256"),
        pt_luna0_execution_git=luna.get("execution_git"))
    if canonical_json_bytes(dict(value)) != canonical_json_bytes(expected):
        raise WorldAfterstateExperimentError(
            "experiment freeze reconstruction drift")


__all__ = [
    "AUTHORITY", "EXPERIMENT_RUNTIME_KEYS", "EXPERIMENT_SOURCE_KEYS",
    "FOLD_COUNTS", "FREEZE_SCHEMA",
    "INITIALIZATION_SEEDS",
    "NAMESPACE", "REPETITIONS_BY_FOLD", "SOURCE_COUNTS",
    "SOURCE_FOLD_COUNTS",
    "STATE_GROUP_COUNT", "WorldAfterstateExperimentError",
    "build_experiment_freeze", "reviewed_teacher_binding",
    "validate_experiment_freeze",
]
