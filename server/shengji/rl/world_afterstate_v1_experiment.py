"""Immutable reviewed-pilot freeze derived from one Value V1 capacity build.

The builder consumes no dataset row and observes no model-quality statistic.
It converts the already-sealed train-only P0/capacity packet into exact P1
training mechanics.  The returned freeze authorizes nothing until a later
external source+freeze review admits one execution.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Mapping

from .belief_contract import canonical_json_bytes
from .world_afterstate_v1_admission import (
    validate_capacity_operator_reentry,
    validate_capacity_operator_reentry_v2)
from .world_afterstate_v1_capacity import (
    CAPACITY_MEMORY_LIMIT_BYTES, CapacityBuildV1, reopen_capacity_build)
from .world_afterstate_v1_training import AdvantageTrainingConfigV1
from .world_afterstate_v1_training_controller import TRAINING_COHORTS


FREEZE_SCHEMA = "world-afterstate-advantage-p1-freeze-v1"
NAMESPACE = "world-afterstate-advantage-p1-v1"
TRAINING_WALL_CAP_NANOSECONDS = 8 * 60 * 60 * 10**9
COHORT_WALL_CAP_NANOSECONDS = 2 * 60 * 60 * 10**9
AUDIT_WALL_CAP_NANOSECONDS = 2 * 60 * 60 * 10**9
RECONSTRUCTION_WALL_CAP_NANOSECONDS = 2 * 60 * 60 * 10**9
CAPACITY_WALL_MULTIPLIER = 2
V0_AUDIT_MANIFEST_EXTERNAL_SHA256 = (
    "67fba564ab19941c19051a350a931f116d8154b9ce5757af9fe638c8d0a53c75")
V0_AUDIT_MANIFEST_SHA256 = (
    "daf451dab7a0736d43f8374e9eede9e504084609214526dc25f22a7ba5e314ce")
CALIBRATION_GROUP_COUNT = 52
CALIBRATION_ACTION_GROUP_COUNT = 49
CALIBRATION_AUDIT_COUNT = 312
CALIBRATION_PAIR_COUNT = 260
CALIBRATION_LABEL_ROW_COUNT = 624
CALIBRATION_LABEL_PAIR_COUNT = 520
SOURCE_PATHS = {
    "design": "VALUE_AFTERSTATE_V1_DESIGN.md",
    "pyproject": "server/pyproject.toml",
    "setup": "server/setup.py",
    "uv_lock": "server/uv.lock",
    "belief_contract": "server/shengji/rl/belief_contract.py",
    "afterstate": "server/shengji/rl/world_afterstate.py",
    "v0_model": "server/shengji/rl/world_afterstate_model.py",
    "v0_dataset": "server/shengji/rl/world_afterstate_dataset.py",
    "population": "server/shengji/rl/world_afterstate_population.py",
    "v1_core": "server/shengji/rl/world_afterstate_v1.py",
    "v1_dataset": "server/shengji/rl/world_afterstate_v1_dataset.py",
    "v1_controls": "server/shengji/rl/world_afterstate_v1_controls.py",
    "v1_model": "server/shengji/rl/world_afterstate_v1_model.py",
    "v1_schedule": "server/shengji/rl/world_afterstate_v1_schedule.py",
    "v1_training": "server/shengji/rl/world_afterstate_v1_training.py",
    "v1_training_controller":
        "server/shengji/rl/world_afterstate_v1_training_controller.py",
    "v1_checkpoint": "server/shengji/rl/world_afterstate_v1_checkpoint.py",
    "v1_evaluation": "server/shengji/rl/world_afterstate_v1_evaluation.py",
    "v1_inference": "server/shengji/rl/world_afterstate_v1_inference.py",
    "v1_audit_controller":
        "server/shengji/rl/world_afterstate_v1_audit_controller.py",
    "v1_result": "server/shengji/rl/world_afterstate_v1_result.py",
    "v1_pipeline": "server/shengji/rl/world_afterstate_v1_pipeline.py",
    "v1_capacity": "server/shengji/rl/world_afterstate_v1_capacity.py",
    "v1_experiment": "server/shengji/rl/world_afterstate_v1_experiment.py",
    "v1_admission": "server/shengji/rl/world_afterstate_v1_admission.py",
    "v1_scientific": "server/shengji/rl/world_afterstate_v1_scientific.py",
    "v1_execution": "server/shengji/rl/world_afterstate_v1_execution.py",
    "experiment_script": "server/scripts/world_afterstate_v1_experiment.py",
    "run_script": "server/scripts/world_afterstate_v1_run.py",
    "engine_cards": "server/shengji/engine/cards.py",
    "engine_round": "server/shengji/engine/round.py",
    "engine_legal": "server/shengji/engine/legal.py",
    "engine_fast": "server/shengji/engine/fast.py",
    "engine_ballot": "server/shengji/engine/ballot.py",
    "engine_combos": "server/shengji/engine/combos.py",
}
SOURCE_KEYS = tuple(SOURCE_PATHS)
RUNTIME_MATCH_KEYS = (
    "host", "platform", "machine", "python", "torch", "numpy",
    "cpu_count", "torch_interop_threads", "environment",
    "python_executable_sha256", "fast_router_sha256", "native_sha256",
    "compiled_engine_active", "safe_path", "dont_write_bytecode",
    "pythonpath_absent",
)
AUTHORITY = {
    "v0_train_row_reopening_authorized": False,
    "v0_calibration_row_opening_authorized": False,
    "scientific_p1_training_authorized": False,
    "p1_audit_opening_authorized": False,
    "report_row_opening_authorized": False,
    "provider_audit_row_opening_authorized": False,
    "p2_execution_authorized": False,
    "gameplay_authorized": False,
    "strength_claim_authorized": False,
    "merge_authorized": False,
    "promotion_authorized": False,
    "deployment_authorized": False,
    "retry_authorized": False,
    "r5_authorized": False,
}
CAPACITY_FAILED_ATTEMPTS = (
    {
        "ordinal": 1,
        "source_git": "aa0595cce9b626941c9cc4fd64062b4e06d10cf1",
        "service": "value-afterstate-v1-capacity-aa0595c-r1.service",
        "invocation_id": "40a4c998a71e4b74befb46feddd2dd52",
        "failure_class": "doubled-dataset-row-root",
        "train_population_opened": False,
        "progress_records_emitted": 0,
        "output_published": False,
        "heldout_rows_opened": False,
        "canonical_evidence_commit":
            "32cc41391a4c40c406161b14f6d91385123ba08c",
    },
    {
        "ordinal": 2,
        "source_git": "aa0595cce9b626941c9cc4fd64062b4e06d10cf1",
        "service": "value-afterstate-v1-capacity-aa0595c-r2.service",
        "invocation_id": "638870aef3b44e84a2297b9a1cf1bbf7",
        "failure_class": "stale-canonical-remote-ref",
        "train_population_opened": False,
        "progress_records_emitted": 0,
        "output_published": False,
        "heldout_rows_opened": False,
        "canonical_evidence_commit":
            "11786ebb81d4d6995f9b6ed1d21be93fccd70a0b",
    },
    {
        "ordinal": 3,
        "source_git": "aa0595cce9b626941c9cc4fd64062b4e06d10cf1",
        "service": "value-afterstate-v1-capacity-aa0595c-r3.service",
        "invocation_id": "bf7e9e3ddc64472eab796d93dfce347c",
        "failure_class": "singleton-candidate-eligibility-projection",
        "train_population_opened": True,
        "progress_records_emitted": 0,
        "output_published": False,
        "heldout_rows_opened": False,
        "canonical_evidence_commit":
            "89f278d27a51b8249f87cec7d1392350cc566bbe",
    },
    {
        "ordinal": 4,
        "source_git": "34409006ed9ecafdddd41e060936c2e3a8421aee",
        "service": "value-afterstate-v1-capacity-3440900-r1.service",
        "invocation_id": "e04d13f84d41486eb8f6e6acbb8250bc",
        "failure_class": "same-prefix-review-marker-introduction",
        "train_population_opened": False,
        "progress_records_emitted": 0,
        "output_published": False,
        "heldout_rows_opened": False,
        "canonical_evidence_commit":
            "6692243c04c868e773220dc743ada117110950bf",
    },
)
SCIENTIFIC_FAILED_ATTEMPTS = (
    {
        "ordinal": 1,
        "source_git": "3534fe095875826f8fa6296cb6004c28f0b7359e",
        "service":
            "value-afterstate-v1-p1-scientific-3534fe0-r1.service",
        "invocation_id": "9bd5215a32ed4481a6229b7bd508be12",
        "scientific_root": "/opt/value-afterstate-v1-p1-scientific-r1",
        "failure_class":
            "scientific-training-missed-eligibility-projection",
        "failure_stage": "natural-cohort-train-population-reopen",
        "admission_spent": True,
        "train_population_opened": True,
        "cohort_output_published": False,
        "predictions_published": False,
        "calibration_attempt_published": False,
        "calibration_labels_opened": False,
        "reconstruction_attempt_published": False,
        "report_rows_opened": False,
        "provider_audit_rows_opened": False,
    },
)


class WorldAfterstateV1ExperimentError(ValueError):
    """A capacity, runtime, resource derivation, or freeze drifted."""


def _sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha(value: object) -> str:
    return _sha_bytes(canonical_json_bytes(value))


def _digest(value: object, label: str, *, length: int = 64) -> str:
    if type(value) is not str or len(value) != length \
            or any(char not in "0123456789abcdef" for char in value):
        raise WorldAfterstateV1ExperimentError(f"{label} drift")
    return value


def _training_config() -> AdvantageTrainingConfigV1:
    return AdvantageTrainingConfigV1(
        learning_rate_ppb=1_000_000,
        weight_decay_ppb=10_000_000,
        gradient_norm_milli=1_000,
        max_epochs=30,
        early_stop_patience=4,
        minimum_improvement_nanoloss=100_000,
    )


def _initialization_seeds() -> tuple[int, ...]:
    return tuple(
        int.from_bytes(hashlib.sha256(
            f"{NAMESPACE}|member|{member}".encode("ascii")
        ).digest()[:8], "big") & (2**63 - 1)
        for member in range(8)
    )


def _schedule_seed() -> int:
    return int.from_bytes(hashlib.sha256(
        f"{NAMESPACE}|schedule".encode("ascii")
    ).digest()[:8], "big") & (2**63 - 1)


def _capacity_directory_binding(build: CapacityBuildV1) -> dict[str, Any]:
    receipt_raw = canonical_json_bytes(build.receipt)
    return {
        "receipt_external_sha256": _sha_bytes(receipt_raw),
        "receipt_sha256": build.receipt["receipt_sha256"],
        "source_git": build.receipt["source_git"],
        "review": build.receipt["review"],
        "terminal_route": build.receipt["terminal_route"],
        "artifacts": [dict(row) for row in build.receipt["artifacts"]],
    }


def build_experiment_freeze(
        capacity_build: CapacityBuildV1, *, source_git: str,
        source_sha256s: Mapping[str, str],
        experiment_runtime: Mapping[str, Any],
        scientific_root: str,
        capacity_operator_reentry: Mapping[str, Any],
        capacity_operator_reentry_v2: Mapping[str, Any]) -> dict[str, Any]:
    """Derive one outcome-blind P1 freeze from exact capacity mechanics."""
    try:
        capacity_build = reopen_capacity_build(capacity_build)
    except ValueError as exc:
        raise WorldAfterstateV1ExperimentError(
            "experiment capacity build drift") from exc
    try:
        validate_capacity_operator_reentry(capacity_operator_reentry)
        validate_capacity_operator_reentry_v2(capacity_operator_reentry_v2)
    except ValueError as exc:
        raise WorldAfterstateV1ExperimentError(
            "experiment capacity operator reentry drift") from exc
    receipt = capacity_build.receipt
    if receipt["terminal_route"] != "PASS_TO_P1_CAPACITY" \
            or receipt["train_population"]["label_ceiling_passed"] is not True \
            or len(capacity_build.files) != 6:
        raise WorldAfterstateV1ExperimentError(
            "experiment requires a passing P0 capacity packet")
    _digest(source_git, "experiment source Git", length=40)
    if type(scientific_root) is not str or not scientific_root \
            or not Path(scientific_root).is_absolute() \
            or str(Path(scientific_root).resolve(strict=False)) \
            != scientific_root:
        raise WorldAfterstateV1ExperimentError(
            "experiment scientific root drift")
    if type(source_sha256s) is not dict \
            or set(source_sha256s) != set(SOURCE_KEYS):
        raise WorldAfterstateV1ExperimentError(
            "experiment source population drift")
    for key, value in source_sha256s.items():
        _digest(value, f"experiment source {key}")
    capacity_runtime = receipt["runtime"]
    if type(experiment_runtime) is not dict \
            or set(experiment_runtime) != set(capacity_runtime) \
            or any(experiment_runtime.get(key) != capacity_runtime.get(key)
                   for key in RUNTIME_MATCH_KEYS) \
            or experiment_runtime.get("torch_threads_at_entry") \
            != receipt["selection"]["torch_threads"] \
            or any(type(experiment_runtime.get(key)) is not str
                   or not experiment_runtime[key] for key in (
                       "python_executable", "fast_router_path", "native_path")):
        raise WorldAfterstateV1ExperimentError(
            "experiment runtime differs from capacity host")

    selection = receipt["selection"]
    matching = [row for row in receipt["cohort_measurements"]
                if row["member_workers"] == selection["member_workers"]
                and row["torch_threads"] == selection["torch_threads"]]
    if len(matching) != 1:
        raise WorldAfterstateV1ExperimentError(
            "experiment selected capacity measurement drift")
    measured_epoch_wall = matching[0]["wall_nanoseconds"]
    config = _training_config()
    projected_cohort_wall = (
        measured_epoch_wall * config.max_epochs * CAPACITY_WALL_MULTIPLIER)
    projected_total_wall = projected_cohort_wall * len(TRAINING_COHORTS)
    if projected_cohort_wall > COHORT_WALL_CAP_NANOSECONDS \
            or projected_total_wall > TRAINING_WALL_CAP_NANOSECONDS:
        raise WorldAfterstateV1ExperimentError(
            "capacity cannot fit the fixed P1 training schedule")

    train = receipt["train_population"]
    body = {
        "schema": FREEZE_SCHEMA,
        "namespace": NAMESPACE,
        "scientific_root": scientific_root,
        "source_git": source_git,
        "source_sha256s": dict(sorted(source_sha256s.items())),
        "runtime": dict(experiment_runtime),
        "capacity_operator_reentry": dict(capacity_operator_reentry),
        "capacity_operator_reentry_v2": dict(capacity_operator_reentry_v2),
        "capacity_attempt_lineage": {
            "failed_attempt_count": len(CAPACITY_FAILED_ATTEMPTS),
            "failed_attempts": [dict(row)
                                for row in CAPACITY_FAILED_ATTEMPTS],
            "successful_attempt_count": 1,
            "successful_source_git": receipt["source_git"],
            "successful_receipt_external_sha256":
                _sha_bytes(canonical_json_bytes(receipt)),
            "successful_receipt_sha256": receipt["receipt_sha256"],
            "successful_terminal_route": receipt["terminal_route"],
        },
        "scientific_attempt_lineage": {
            "failed_attempt_count": len(SCIENTIFIC_FAILED_ATTEMPTS),
            "failed_attempts": [dict(row)
                                for row in SCIENTIFIC_FAILED_ATTEMPTS],
            "next_attempt_ordinal": len(SCIENTIFIC_FAILED_ATTEMPTS) + 1,
            "fresh_exact_head_freeze_review_required": True,
            "prior_admission_retry_authorized": False,
        },
        "capacity": _capacity_directory_binding(capacity_build),
        "v0_inputs": {
            **dict(receipt["v0_inputs"]),
            "audit_manifest_external_sha256":
                V0_AUDIT_MANIFEST_EXTERNAL_SHA256,
            "audit_manifest_sha256": V0_AUDIT_MANIFEST_SHA256,
        },
        "population": {
            "train_row_count": train["train_row_count"],
            "eligible_state_count": train["eligible_state_count"],
            "pair_count": train["pair_count"],
            "fit_state_count": train["fit_state_count"],
            "select_state_count": train["select_state_count"],
            "train_row_population_sha256":
                train["train_row_population_sha256"],
            "advantage_manifest_sha256":
                train["advantage_manifest_sha256"],
            "subsplit_manifest_sha256":
                train["subsplit_manifest_sha256"],
            "label_ceiling_result_sha256":
                train["label_ceiling_result_sha256"],
            "calibration_fold": "original-v0-calibration-only",
            "calibration_group_count": CALIBRATION_GROUP_COUNT,
            "calibration_action_group_count":
                CALIBRATION_ACTION_GROUP_COUNT,
            "calibration_audit_count": CALIBRATION_AUDIT_COUNT,
            "calibration_pair_count": CALIBRATION_PAIR_COUNT,
            "calibration_label_row_count": CALIBRATION_LABEL_ROW_COUNT,
            "calibration_label_pair_count": CALIBRATION_LABEL_PAIR_COUNT,
            "report_rows_opened": False,
            "provider_audit_rows_opened": False,
        },
        "learner": {
            "head": "shared-bounded-successor-scalar-difference",
            "shape_name": receipt["schedule"]["shape_name"],
            "pair_cap": receipt["schedule"]["pair_cap"],
            "row_workers": selection["row_workers"],
            "member_workers": selection["member_workers"],
            "torch_threads": selection["torch_threads"],
            "cohorts": list(TRAINING_COHORTS),
            "initialization_seeds": list(_initialization_seeds()),
            "schedule_seed": _schedule_seed(),
            "config": config.payload(),
            "fresh_initialization": True,
            "common_epoch_selection": True,
            "member_drop_allowed": False,
            "warm_start_allowed": False,
        },
        "resources": {
            "capacity_epoch_wall_nanoseconds": measured_epoch_wall,
            "capacity_wall_multiplier": CAPACITY_WALL_MULTIPLIER,
            "projected_cohort_wall_nanoseconds": projected_cohort_wall,
            "projected_total_training_wall_nanoseconds": projected_total_wall,
            "cohort_wall_cap_nanoseconds": COHORT_WALL_CAP_NANOSECONDS,
            "training_wall_cap_nanoseconds": TRAINING_WALL_CAP_NANOSECONDS,
            "audit_wall_cap_nanoseconds": AUDIT_WALL_CAP_NANOSECONDS,
            "reconstruction_wall_cap_nanoseconds":
                RECONSTRUCTION_WALL_CAP_NANOSECONDS,
            "memory_limit_bytes": CAPACITY_MEMORY_LIMIT_BYTES,
            "deadline_behavior": (
                "each cohort seals its best complete common epoch; deadline "
                "truncation is explicit and never masquerades as convergence"),
        },
        "gates": {
            "advantage_error":
                "deal-bootstrap lower bound over zero baseline positive",
            "action_utility":
                "deal-bootstrap lower bound over incumbent positive",
            "seed_stability": "at least six of eight positive member means",
            "selection_dose_ppm_minimum": 50_000,
            "negative_controls_must_fail": list(TRAINING_COHORTS[1:]),
            "world_shuffle_requires_two_positive_lower_bounds": True,
            "search_final_authority": True,
            "belief_required": False,
        },
        "stage_order": [
            "reopen-train-only-capacity-pairs",
            "train-and-seal-four-cohorts",
            "reopen-outcome-blind-calibration-audits",
            "seal-all-target-free-predictions",
            "durably-record-calibration-opening-attempt",
            "open-calibration-labels-once",
            "derive-and-seal-terminal",
            "immediate-independent-reconstruction",
        ],
        "terminal_authority_if_pass":
            "one later public-action-value or P2 packet review only",
        "authority": dict(AUTHORITY),
    }
    return {**body, "freeze_sha256": _sha(body)}


def validate_experiment_freeze(
        value: Mapping[str, Any], capacity_build: CapacityBuildV1) -> None:
    """Rebuild the full freeze from its only immutable variable input."""
    if type(value) is not dict or set(value) != {
            "schema", "namespace", "scientific_root", "source_git",
            "source_sha256s",
            "runtime", "capacity_operator_reentry",
            "capacity_operator_reentry_v2", "capacity_attempt_lineage",
            "scientific_attempt_lineage", "capacity", "v0_inputs",
            "population", "learner", "resources", "gates", "stage_order",
            "terminal_authority_if_pass", "authority", "freeze_sha256"} \
            or value.get("schema") != FREEZE_SCHEMA \
            or value.get("namespace") != NAMESPACE \
            or value.get("authority") != AUTHORITY:
        raise WorldAfterstateV1ExperimentError(
            "experiment freeze identity drift")
    expected = build_experiment_freeze(
        capacity_build, source_git=value.get("source_git"),
        source_sha256s=value.get("source_sha256s"),
        experiment_runtime=value.get("runtime"),
        scientific_root=value.get("scientific_root"),
        capacity_operator_reentry=value.get("capacity_operator_reentry"),
        capacity_operator_reentry_v2=value.get(
            "capacity_operator_reentry_v2"))
    if canonical_json_bytes(dict(value)) != canonical_json_bytes(expected):
        raise WorldAfterstateV1ExperimentError(
            "experiment freeze reconstruction drift")


__all__ = [
    "AUTHORITY", "CAPACITY_FAILED_ATTEMPTS",
    "CALIBRATION_ACTION_GROUP_COUNT", "CALIBRATION_AUDIT_COUNT",
    "CALIBRATION_GROUP_COUNT",
    "CALIBRATION_LABEL_PAIR_COUNT", "CALIBRATION_LABEL_ROW_COUNT",
    "CALIBRATION_PAIR_COUNT", "FREEZE_SCHEMA", "NAMESPACE", "SOURCE_KEYS",
    "SCIENTIFIC_FAILED_ATTEMPTS", "SOURCE_PATHS",
    "V0_AUDIT_MANIFEST_EXTERNAL_SHA256", "V0_AUDIT_MANIFEST_SHA256",
    "WorldAfterstateV1ExperimentError", "build_experiment_freeze",
    "validate_experiment_freeze",
]
