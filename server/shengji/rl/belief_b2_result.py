"""Single no-authority terminal decision for the BELIEF-V1 B2 experiment.

The terminal evaluator consumes already-recomputed typed artifacts from every
frozen B2 gate.  It authenticates their common model/protocol/cohort identity,
resource limits, exact artifact population, and decision precedence.  It does
not open corpus bytes, train, sample, play, read files, write results, or grant
runtime authority; the later filesystem reopener must reconstruct these inputs
before an independent terminal review accepts the emitted decision.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

from .belief_b2_protocol import (
    B2_ROUND_COUNT,
    CAPTURE_BYTE_CAP,
    CAPTURE_CORE_HOUR_CAP,
    CAPTURE_WALL_SECOND_CAP,
    REFERENCE_BYTE_CAP,
    REFERENCE_CORE_HOUR_CAP,
    REFERENCE_WALL_SECOND_CAP,
    TRAIN_BYTE_CAP,
    TRAIN_DEVICE_HOUR_CAP,
    TRAIN_WALL_SECOND_CAP,
    b2_split_round_seeds,
    protocol_sha256,
)
from .belief_b2_statistics import (
    C1CalibrationResultV1,
    N2PermutedLabelResultV1,
)
from .belief_behavioral_evaluation import (
    POOLED_STRATUM,
    C2BehavioralResultV1,
)
from .belief_cohort import COHORT_SCHEMA, COHORT_SEEDS, ensemble_identity
from .belief_contract import canonical_json_bytes
from .belief_reliability import CountReliabilityReportV1
from .belief_synthetic import C4ExactPosteriorResultV1


MECHANICS_SCHEMA = "belief-v1-b2-mechanics-result-v1"
RESOURCE_SCHEMA = "belief-v1-b2-resource-receipt-v1"
INVENTORY_SCHEMA = "belief-v1-b2-artifact-inventory-v1"
TERMINAL_SCHEMA = "belief-v1-b2-terminal-result-v1"

PASS = "PASS_TO_B3_SAMPLER_IMPLEMENTATION_REVIEW"
NO_LIFT = "SELECT_NONE_NO_CALIBRATION_LIFT"
NO_BEHAVIOR = "SELECT_NONE_BEHAVIORAL_CLAIM_UNSUPPORTED"
REFUSE_MECHANICS = "REFUSE_MECHANICS_OR_LEAKAGE"
REFUSE_INCOMPLETE = "REFUSE_INCOMPLETE_COHORT_OR_ARTIFACT"
TERMINAL_DECISIONS = (
    PASS, NO_LIFT, NO_BEHAVIOR, REFUSE_MECHANICS, REFUSE_INCOMPLETE)
NS_PER_HOUR = 3_600_000_000_000
NS_PER_SECOND = 1_000_000_000


class BeliefB2ResultError(ValueError):
    """A B2 terminal input, identity, resource, or decision drifted."""


def _is_sha256(value: Any) -> bool:
    return (type(value) is str and len(value) == 64
            and all(char in "0123456789abcdef" for char in value))


@dataclass(frozen=True)
class B2MechanicsResultV1:
    prediction_count: int
    conservation_rows_checked: int
    hard_fact_rows_checked: int
    public_twin_cases_checked: int
    rotation_cases_checked: int
    target_isolation_cases_checked: int
    duplicate_decision_count: int
    cross_split_round_count: int
    source_manifest_sha256: str
    conservation_passed: bool
    hard_facts_passed: bool
    public_twins_passed: bool
    rotation_passed: bool
    target_isolation_passed: bool
    schema: str = MECHANICS_SCHEMA

    @property
    def passed(self) -> bool:
        return (self.conservation_passed and self.hard_facts_passed
                and self.public_twins_passed and self.rotation_passed
                and self.target_isolation_passed
                and self.duplicate_decision_count == 0
                and self.cross_split_round_count == 0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "prediction_count": self.prediction_count,
            "checks": {
                "conservation_rows": self.conservation_rows_checked,
                "hard_fact_rows": self.hard_fact_rows_checked,
                "public_twin_cases": self.public_twin_cases_checked,
                "rotation_cases": self.rotation_cases_checked,
                "target_isolation_cases": self.target_isolation_cases_checked,
            },
            "duplicate_decision_count": self.duplicate_decision_count,
            "cross_split_round_count": self.cross_split_round_count,
            "source_manifest_sha256": self.source_manifest_sha256,
            "gates": {
                "conservation": self.conservation_passed,
                "hard_facts": self.hard_facts_passed,
                "public_twins": self.public_twins_passed,
                "rotation": self.rotation_passed,
                "target_isolation": self.target_isolation_passed,
            },
            "passed": self.passed,
            "privileged_targets_consumed": True,
            "runtime_artifact": False,
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


@dataclass(frozen=True)
class B2ResourceReceiptV1:
    source_manifest_sha256: str
    runtime_profile_sha256: str
    capture_cpu_nanoseconds: int
    capture_wall_nanoseconds: int
    capture_artifact_bytes: int
    reference_cpu_nanoseconds: int
    reference_wall_nanoseconds: int
    reference_artifact_bytes: int
    training_device_nanoseconds: int
    training_wall_nanoseconds: int
    training_artifact_bytes: int
    capture_retry_count: int
    reference_retry_count: int
    training_retry_count: int
    test_split_open_count: int
    schema: str = RESOURCE_SCHEMA

    @property
    def within_caps(self) -> bool:
        return (
            self.capture_cpu_nanoseconds
            <= CAPTURE_CORE_HOUR_CAP * NS_PER_HOUR
            and self.capture_wall_nanoseconds
            <= CAPTURE_WALL_SECOND_CAP * NS_PER_SECOND
            and self.capture_artifact_bytes <= CAPTURE_BYTE_CAP
            and self.reference_cpu_nanoseconds
            <= REFERENCE_CORE_HOUR_CAP * NS_PER_HOUR
            and self.reference_wall_nanoseconds
            <= REFERENCE_WALL_SECOND_CAP * NS_PER_SECOND
            and self.reference_artifact_bytes <= REFERENCE_BYTE_CAP
            and self.training_device_nanoseconds
            <= TRAIN_DEVICE_HOUR_CAP * NS_PER_HOUR
            and self.training_wall_nanoseconds
            <= TRAIN_WALL_SECOND_CAP * NS_PER_SECOND
            and self.training_artifact_bytes <= TRAIN_BYTE_CAP
            and self.capture_retry_count == 0
            and self.reference_retry_count == 0
            and self.training_retry_count == 0
            and self.test_split_open_count == 1)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "source_manifest_sha256": self.source_manifest_sha256,
            "runtime_profile_sha256": self.runtime_profile_sha256,
            "capture": {
                "cpu_nanoseconds": self.capture_cpu_nanoseconds,
                "wall_nanoseconds": self.capture_wall_nanoseconds,
                "artifact_bytes": self.capture_artifact_bytes,
                "retry_count": self.capture_retry_count,
            },
            "reference": {
                "cpu_nanoseconds": self.reference_cpu_nanoseconds,
                "wall_nanoseconds": self.reference_wall_nanoseconds,
                "artifact_bytes": self.reference_artifact_bytes,
                "retry_count": self.reference_retry_count,
            },
            "training": {
                "device_nanoseconds": self.training_device_nanoseconds,
                "wall_nanoseconds": self.training_wall_nanoseconds,
                "artifact_bytes": self.training_artifact_bytes,
                "retry_count": self.training_retry_count,
            },
            "test_split_open_count": self.test_split_open_count,
            "within_frozen_caps": self.within_caps,
            "capture_execution_authorized": False,
            "training_authorized": False,
            "gameplay_authorized": False,
            "strength_claim_authorized": False,
            "deployment_authorized": False,
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


@dataclass(frozen=True)
class B2ArtifactInventoryV1:
    source_manifest_sha256: str
    population_sha256: str
    actor_corpus_manifest_sha256: str
    privileged_target_manifest_sha256: str
    split_seed_manifest_sha256: str
    reference_world_manifest_sha256: str
    candidate_training_curve_sha256: str
    control_training_curve_sha256: str
    population_round_count: int
    population_decision_count: int
    test_round_count: int
    candidate_member_model_sha256s: tuple[str, ...]
    candidate_checkpoint_sha256s: tuple[str, ...]
    control_member_model_sha256s: tuple[str, ...]
    control_checkpoint_sha256s: tuple[str, ...]
    candidate_selected_epoch: int
    control_selected_epoch: int
    mechanics_result_sha256: str
    resource_receipt_sha256: str
    c1_result_sha256: str
    c2_result_sha256: str
    c3_result_sha256: str
    n2_result_sha256: str
    c4_result_sha256: str
    schema: str = INVENTORY_SCHEMA

    @property
    def candidate_ensemble_sha256(self) -> str:
        return ensemble_identity(self.candidate_member_model_sha256s)

    @property
    def control_ensemble_sha256(self) -> str:
        return ensemble_identity(self.control_member_model_sha256s)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "protocol_sha256": protocol_sha256(),
            "source_manifest_sha256": self.source_manifest_sha256,
            "population_sha256": self.population_sha256,
            "actor_corpus_manifest_sha256": (
                self.actor_corpus_manifest_sha256),
            "privileged_target_manifest_sha256": (
                self.privileged_target_manifest_sha256),
            "split_seed_manifest_sha256": self.split_seed_manifest_sha256,
            "reference_world_manifest_sha256": (
                self.reference_world_manifest_sha256),
            "training_curve_sha256s": {
                "candidate": self.candidate_training_curve_sha256,
                "hard_geometry_permuted_label": (
                    self.control_training_curve_sha256),
            },
            "population_round_count": self.population_round_count,
            "population_decision_count": self.population_decision_count,
            "test_round_count": self.test_round_count,
            "candidate_cohort": {
                "schema": COHORT_SCHEMA,
                "initialization_seeds": list(COHORT_SEEDS),
                "member_model_sha256s": list(
                    self.candidate_member_model_sha256s),
                "checkpoint_sha256s": list(
                    self.candidate_checkpoint_sha256s),
                "ensemble_sha256": self.candidate_ensemble_sha256,
                "selected_common_epoch": self.candidate_selected_epoch,
            },
            "hard_geometry_permuted_label_cohort": {
                "schema": COHORT_SCHEMA,
                "initialization_seeds": list(COHORT_SEEDS),
                "member_model_sha256s": list(
                    self.control_member_model_sha256s),
                "checkpoint_sha256s": list(
                    self.control_checkpoint_sha256s),
                "ensemble_sha256": self.control_ensemble_sha256,
                "selected_common_epoch": self.control_selected_epoch,
            },
            "results": {
                "mechanics": self.mechanics_result_sha256,
                "resource_receipt": self.resource_receipt_sha256,
                "c1": self.c1_result_sha256,
                "c2_n1": self.c2_result_sha256,
                "c3": self.c3_result_sha256,
                "n2": self.n2_result_sha256,
                "c4": self.c4_result_sha256,
            },
            "contains_round_outcomes": False,
            "runtime_contains_privileged_targets": False,
            "sampler_implementation_authorized": False,
            "gameplay_authorized": False,
            "strength_claim_authorized": False,
            "promotion_authorized": False,
            "deployment_authorized": False,
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


@dataclass(frozen=True)
class B2TerminalEvidenceV1:
    mechanics: B2MechanicsResultV1
    resources: B2ResourceReceiptV1
    inventory: B2ArtifactInventoryV1
    c1: C1CalibrationResultV1
    c2: C2BehavioralResultV1
    c3: CountReliabilityReportV1
    n2: N2PermutedLabelResultV1
    c4: C4ExactPosteriorResultV1
    reference_replicates_stable: bool


@dataclass(frozen=True)
class B2TerminalResultV1:
    decision: str
    evidence_sha256s: tuple[tuple[str, str], ...]
    mechanics_passed: bool
    artifacts_complete: bool
    resources_within_caps: bool
    reference_replicates_stable: bool
    c1_calibration_passed: bool
    c2_behavioral_and_n1_passed: bool
    c3_reliability_report_complete: bool
    n2_permuted_label_passed: bool
    c4_exact_posterior_passed: bool
    u1_true_world_likelihood_passed: bool
    schema: str = TERMINAL_SCHEMA

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "protocol_sha256": protocol_sha256(),
            "decision": self.decision,
            "evidence_sha256s": dict(self.evidence_sha256s),
            "gates": {
                "mechanics": self.mechanics_passed,
                "artifacts_complete": self.artifacts_complete,
                "resources_within_caps": self.resources_within_caps,
                "reference_replicates_stable": (
                    self.reference_replicates_stable),
                "c1_calibration": self.c1_calibration_passed,
                "c2_behavioral_and_n1": (
                    self.c2_behavioral_and_n1_passed),
                "c3_reliability_report_complete": (
                    self.c3_reliability_report_complete),
                "n2_permuted_label": self.n2_permuted_label_passed,
                "c4_exact_posterior": self.c4_exact_posterior_passed,
                "u1_true_world_likelihood": (
                    self.u1_true_world_likelihood_passed),
                "u2_fixed_world_value_quality_deferred_to_b3": True,
            },
            "terminal_reproducibility_review_required": True,
            "b3_sampler_implementation_review_may_be_requested": (
                self.decision == PASS),
            "b3_sampler_implementation_authorized": False,
            "sampler_run_authorized": False,
            "gameplay_authorized": False,
            "strength_claim_authorized": False,
            "promotion_authorized": False,
            "deployment_authorized": False,
        }

    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.to_dict())

    def sha256(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()


def _validate_mechanics(result: B2MechanicsResultV1) -> None:
    values = (
        result.prediction_count, result.conservation_rows_checked,
        result.hard_fact_rows_checked, result.public_twin_cases_checked,
        result.rotation_cases_checked, result.target_isolation_cases_checked,
        result.duplicate_decision_count, result.cross_split_round_count)
    if type(result) is not B2MechanicsResultV1 \
            or result.schema != MECHANICS_SCHEMA \
            or not _is_sha256(result.source_manifest_sha256) \
            or any(type(value) is not int or value < 0 for value in values) \
            or result.prediction_count <= 0 \
            or min(result.conservation_rows_checked,
                   result.hard_fact_rows_checked,
                   result.public_twin_cases_checked,
                   result.rotation_cases_checked,
                   result.target_isolation_cases_checked) <= 0 \
            or any(type(value) is not bool for value in (
                result.conservation_passed, result.hard_facts_passed,
                result.public_twins_passed, result.rotation_passed,
                result.target_isolation_passed)):
        raise BeliefB2ResultError("B2 mechanics result schema/value drift")


def _validate_resources(receipt: B2ResourceReceiptV1) -> None:
    values = (
        receipt.capture_cpu_nanoseconds, receipt.capture_wall_nanoseconds,
        receipt.capture_artifact_bytes,
        receipt.reference_cpu_nanoseconds,
        receipt.reference_wall_nanoseconds,
        receipt.reference_artifact_bytes,
        receipt.training_device_nanoseconds,
        receipt.training_wall_nanoseconds,
        receipt.training_artifact_bytes, receipt.capture_retry_count,
        receipt.reference_retry_count,
        receipt.training_retry_count, receipt.test_split_open_count)
    if type(receipt) is not B2ResourceReceiptV1 \
            or receipt.schema != RESOURCE_SCHEMA \
            or not _is_sha256(receipt.source_manifest_sha256) \
            or not _is_sha256(receipt.runtime_profile_sha256) \
            or any(type(value) is not int or value < 0 for value in values):
        raise BeliefB2ResultError("B2 resource receipt schema/value drift")


def _validate_inventory(inventory: B2ArtifactInventoryV1) -> None:
    digest_fields = (
        inventory.source_manifest_sha256, inventory.population_sha256,
        inventory.actor_corpus_manifest_sha256,
        inventory.privileged_target_manifest_sha256,
        inventory.split_seed_manifest_sha256,
        inventory.reference_world_manifest_sha256,
        inventory.candidate_training_curve_sha256,
        inventory.control_training_curve_sha256,
        inventory.mechanics_result_sha256,
        inventory.resource_receipt_sha256, inventory.c1_result_sha256,
        inventory.c2_result_sha256, inventory.c3_result_sha256,
        inventory.n2_result_sha256, inventory.c4_result_sha256,
        *inventory.candidate_member_model_sha256s,
        *inventory.candidate_checkpoint_sha256s,
        *inventory.control_member_model_sha256s,
        *inventory.control_checkpoint_sha256s)
    populations = (
        inventory.candidate_member_model_sha256s,
        inventory.candidate_checkpoint_sha256s,
        inventory.control_member_model_sha256s,
        inventory.control_checkpoint_sha256s)
    if type(inventory) is not B2ArtifactInventoryV1 \
            or inventory.schema != INVENTORY_SCHEMA \
            or any(type(row) is not tuple or len(row) != len(COHORT_SEEDS)
                   or len(set(row)) != len(row) for row in populations) \
            or any(not _is_sha256(value) for value in digest_fields) \
            or set(inventory.candidate_member_model_sha256s) \
            & set(inventory.control_member_model_sha256s) \
            or type(inventory.population_round_count) is not int \
            or inventory.population_round_count != B2_ROUND_COUNT \
            or type(inventory.population_decision_count) is not int \
            or inventory.population_decision_count < B2_ROUND_COUNT \
            or type(inventory.test_round_count) is not int \
            or inventory.test_round_count != len(b2_split_round_seeds("test")) \
            or type(inventory.candidate_selected_epoch) is not int \
            or not 1 <= inventory.candidate_selected_epoch <= 30 \
            or type(inventory.control_selected_epoch) is not int \
            or not 1 <= inventory.control_selected_epoch <= 30:
        raise BeliefB2ResultError("B2 artifact inventory drift")
    # Force exact cohort identity reconstruction rather than trusting payloads.
    inventory.candidate_ensemble_sha256
    inventory.control_ensemble_sha256


def _artifacts_complete(evidence: B2TerminalEvidenceV1) -> bool:
    inventory = evidence.inventory
    expected = {
        "mechanics": evidence.mechanics.sha256(),
        "resource": evidence.resources.sha256(),
        "c1": evidence.c1.sha256(),
        "c2": evidence.c2.sha256(),
        "c3": evidence.c3.sha256(),
        "n2": evidence.n2.sha256(),
        "c4": evidence.c4.sha256(),
    }
    return (
        inventory.source_manifest_sha256
        == evidence.mechanics.source_manifest_sha256
        == evidence.resources.source_manifest_sha256
        and inventory.mechanics_result_sha256 == expected["mechanics"]
        and inventory.resource_receipt_sha256 == expected["resource"]
        and inventory.c1_result_sha256 == expected["c1"]
        and inventory.c2_result_sha256 == expected["c2"]
        and inventory.c3_result_sha256 == expected["c3"]
        and inventory.n2_result_sha256 == expected["n2"]
        and inventory.c4_result_sha256 == expected["c4"]
        and evidence.c3.split == "test"
        and evidence.c3.model_schema == COHORT_SCHEMA
        and evidence.c3.model_sha256
        == inventory.candidate_ensemble_sha256
        and evidence.c3.decision_count > 0
        and bool(evidence.c3.strata)
        and bool(evidence.c3.linear_expectations))


def evaluate_b2_terminal(
        evidence: B2TerminalEvidenceV1) -> B2TerminalResultV1:
    """Apply the sole frozen B2 decision after typed evidence validation."""
    if type(evidence) is not B2TerminalEvidenceV1 \
            or type(evidence.reference_replicates_stable) is not bool \
            or type(evidence.c1) is not C1CalibrationResultV1 \
            or type(evidence.c2) is not C2BehavioralResultV1 \
            or type(evidence.c3) is not CountReliabilityReportV1 \
            or type(evidence.n2) is not N2PermutedLabelResultV1 \
            or type(evidence.c4) is not C4ExactPosteriorResultV1:
        raise BeliefB2ResultError("B2 terminal evidence type drift")
    _validate_mechanics(evidence.mechanics)
    _validate_resources(evidence.resources)
    _validate_inventory(evidence.inventory)
    complete = _artifacts_complete(evidence)
    c2_pooled = (bool(evidence.c2.strata)
                 and evidence.c2.strata[0].stratum == POOLED_STRATUM
                 and evidence.c2.pooled_behavioral_claim_passed)
    c3_complete = (evidence.c3.split == "test"
                   and evidence.c3.decision_count > 0
                   and bool(evidence.c3.strata)
                   and bool(evidence.c3.linear_expectations))

    if not evidence.mechanics.passed \
            or not evidence.reference_replicates_stable \
            or not evidence.c4.passed:
        decision = REFUSE_MECHANICS
    elif not complete or not evidence.resources.within_caps or not c3_complete:
        decision = REFUSE_INCOMPLETE
    elif not evidence.c1.passed:
        decision = NO_LIFT
    elif not c2_pooled or not evidence.n2.passed:
        decision = NO_BEHAVIOR
    else:
        decision = PASS
    result = B2TerminalResultV1(
        decision=decision,
        evidence_sha256s=(
            ("inventory", evidence.inventory.sha256()),
            ("mechanics", evidence.mechanics.sha256()),
            ("resources", evidence.resources.sha256()),
            ("c1", evidence.c1.sha256()),
            ("c2_n1", evidence.c2.sha256()),
            ("c3", evidence.c3.sha256()),
            ("n2", evidence.n2.sha256()),
            ("c4", evidence.c4.sha256()),
        ),
        mechanics_passed=evidence.mechanics.passed,
        artifacts_complete=complete,
        resources_within_caps=evidence.resources.within_caps,
        reference_replicates_stable=evidence.reference_replicates_stable,
        c1_calibration_passed=evidence.c1.passed,
        c2_behavioral_and_n1_passed=c2_pooled,
        c3_reliability_report_complete=c3_complete,
        n2_permuted_label_passed=evidence.n2.passed,
        c4_exact_posterior_passed=evidence.c4.passed,
        u1_true_world_likelihood_passed=evidence.c1.passed,
    )
    validate_b2_terminal(evidence, result)
    return result


def validate_b2_terminal(
        evidence: B2TerminalEvidenceV1,
        result: B2TerminalResultV1) -> None:
    if type(result) is not B2TerminalResultV1 \
            or result.schema != TERMINAL_SCHEMA \
            or result.decision not in TERMINAL_DECISIONS:
        raise BeliefB2ResultError("B2 terminal result schema drift")
    if type(evidence) is not B2TerminalEvidenceV1 \
            or type(evidence.reference_replicates_stable) is not bool:
        raise BeliefB2ResultError("B2 terminal evidence type drift")
    _validate_mechanics(evidence.mechanics)
    _validate_resources(evidence.resources)
    _validate_inventory(evidence.inventory)
    complete = _artifacts_complete(evidence)
    c2_pooled = (bool(evidence.c2.strata)
                 and evidence.c2.strata[0].stratum == POOLED_STRATUM
                 and evidence.c2.pooled_behavioral_claim_passed)
    c3_complete = (evidence.c3.split == "test"
                   and evidence.c3.decision_count > 0
                   and bool(evidence.c3.strata)
                   and bool(evidence.c3.linear_expectations))
    actual_gates = (
        evidence.mechanics.passed, complete, evidence.resources.within_caps,
        evidence.reference_replicates_stable, evidence.c1.passed, c2_pooled,
        c3_complete, evidence.n2.passed, evidence.c4.passed,
        evidence.c1.passed)
    result_gates = (
        result.mechanics_passed, result.artifacts_complete,
        result.resources_within_caps, result.reference_replicates_stable,
        result.c1_calibration_passed,
        result.c2_behavioral_and_n1_passed,
        result.c3_reliability_report_complete,
        result.n2_permuted_label_passed,
        result.c4_exact_posterior_passed,
        result.u1_true_world_likelihood_passed)
    mechanics_failure = (not evidence.mechanics.passed
                         or not evidence.reference_replicates_stable
                         or not evidence.c4.passed)
    incomplete = (not complete or not evidence.resources.within_caps
                  or not c3_complete)
    decision = (REFUSE_MECHANICS if mechanics_failure else
                REFUSE_INCOMPLETE if incomplete else
                NO_LIFT if not evidence.c1.passed else
                NO_BEHAVIOR if (not c2_pooled or not evidence.n2.passed) else
                PASS)
    evidence_hashes = (
        ("inventory", evidence.inventory.sha256()),
        ("mechanics", evidence.mechanics.sha256()),
        ("resources", evidence.resources.sha256()),
        ("c1", evidence.c1.sha256()),
        ("c2_n1", evidence.c2.sha256()),
        ("c3", evidence.c3.sha256()),
        ("n2", evidence.n2.sha256()),
        ("c4", evidence.c4.sha256()),
    )
    if result_gates != actual_gates \
            or result.decision != decision \
            or result.evidence_sha256s != evidence_hashes \
            or result.u1_true_world_likelihood_passed \
            != result.c1_calibration_passed:
        raise BeliefB2ResultError("B2 terminal result derivation drift")
