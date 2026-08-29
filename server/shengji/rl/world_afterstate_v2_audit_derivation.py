"""Pure construction of the complete Value-Afterstate V2 audit evidence.

This boundary accepts only already-reopened, typed values and sealed manifest
objects.  It performs no opening or execution.  In particular, evaluation
receipts and control comparisons are always derived here; callers cannot
replace them with asserted results.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Any, Mapping

from .belief_contract import canonical_json_bytes
from .world_afterstate_v2_continuation import ContinuationOutcomeV2
from .world_afterstate_v2_diagnostics import (
    ModelSelectorPowerReceiptV2, OptimizerCanaryReceiptV2,
    validate_model_selector_power_v2, validate_optimizer_canary_v2)
from .world_afterstate_v2_evaluation import (
    EvaluationResultV2, evaluate_control_difference, evaluate_v2)
from .world_afterstate_v2_inference import (
    validate_prediction_population_manifest_v2)
from .world_afterstate_v2_metrics import JeffreysPriorV2
from .world_afterstate_v2_result import (
    WorldAfterstateV2TerminalEvidence, derive_terminal_result)
from .world_afterstate_v2_training_controller import validate_cohort_manifest
from .world_afterstate_v2_terminal_provenance import (
    AuditProvenanceV2, COHORT_LABELS, COMPARISON_LABELS, DOSE_LABELS,
    UPSTREAM_RECEIPT_LABELS)
from .world_afterstate_v2_label import validate_precision_label
from .world_afterstate_v2_controls import validate_control_evidence


AUDIT_COHORTS = (
    ("natural:block-1", "natural", 1),
    ("action-association-permutation:block-1",
     "action-association-permutation", 1),
    ("label-permutation:block-1", "label-permutation", 1),
    ("complete-world-shuffle:block-1", "complete-world-shuffle", 1),
    ("natural:block-2", "natural", 2),
    ("complete-world-shuffle:block-2", "complete-world-shuffle", 2),
)
_CONTROL_BY_LABEL = {label: (name, block) for label, name, block in AUDIT_COHORTS}
_COMPARISON_BY_LABEL = {
    "association:b1": ("action-association-permutation", 1),
    "label:b1": ("label-permutation", 1),
    "world:b1": ("complete-world-shuffle", 1),
    "world:b2": ("complete-world-shuffle", 2),
}


class WorldAfterstateV2AuditDerivationError(ValueError):
    """Sealed V2 audit inputs could not be reconstructed exactly."""


def _digest(value: object, label: str) -> str:
    if (type(value) is not str or len(value) != 64
            or any(char not in "0123456789abcdef" for char in value)):
        raise WorldAfterstateV2AuditDerivationError(f"{label} drift")
    return value


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _receipt_hash(value: object, label: str) -> str:
    if isinstance(value, Mapping) and "result_sha256" in value:
        return _digest(value["result_sha256"], f"{label} result SHA-256")
    if hasattr(value, "sha256") and callable(value.sha256):
        return _digest(value.sha256(), f"{label} SHA-256")
    if isinstance(value, Mapping):
        return _sha(value)
    raise WorldAfterstateV2AuditDerivationError(f"{label} receipt type drift")


def _ordered_pairs(value: object, labels: tuple[str, ...], label: str) \
        -> tuple[tuple[str, Any], ...]:
    if type(value) is not tuple or len(value) != len(labels):
        raise WorldAfterstateV2AuditDerivationError(f"{label} population drift")
    rows = []
    for row, expected in zip(value, labels, strict=True):
        if type(row) is not tuple or len(row) != 2 or row[0] != expected:
            raise WorldAfterstateV2AuditDerivationError(f"{label} order drift")
        rows.append(row)
    return tuple(rows)


def _manifest_hash(manifest: Mapping[str, Any], label: str) -> str:
    """Return the SHA-256 of the complete canonical manifest bytes."""
    if type(manifest) is not dict:
        raise WorldAfterstateV2AuditDerivationError(f"{label} type drift")
    try:
        raw = canonical_json_bytes(manifest)
    except Exception as exc:
        raise WorldAfterstateV2AuditDerivationError(
            f"{label} canonical bytes drift") from exc
    return hashlib.sha256(raw).hexdigest()


def _validate_outcomes(value: object) -> tuple[ContinuationOutcomeV2, ...]:
    if type(value) is not tuple or not value:
        raise WorldAfterstateV2AuditDerivationError(
            "audit outcomes population drift")
    for row in value:
        if type(row) is not ContinuationOutcomeV2:
            raise WorldAfterstateV2AuditDerivationError("audit outcome type drift")
        try:
            row.validate()
        except Exception as exc:
            raise WorldAfterstateV2AuditDerivationError(
                "audit outcome refused") from exc
        if row.split != "audit":
            raise WorldAfterstateV2AuditDerivationError("audit outcome split drift")
    return value


@dataclass(frozen=True)
class AuditDerivationInputV2:
    freeze_sha256: str
    admission_sha256: str
    audit_attempt_sha256: str
    continuation_manifest_sha256: str
    prediction_manifests: tuple[tuple[str, Mapping[str, Any]], ...]
    checkpoint_manifest_sha256s: tuple[tuple[str, str], ...]
    cohort_manifests: tuple[tuple[str, Mapping[str, Any]], ...]
    p0_report: Mapping[str, Any]
    optimizer_canary: OptimizerCanaryReceiptV2
    precision_select_result: EvaluationResultV2
    model_selector_power: ModelSelectorPowerReceiptV2
    audit_outcomes: tuple[ContinuationOutcomeV2, ...]
    prior: JeffreysPriorV2
    control_dose_evidence: Mapping[str, Mapping[str, Any]]

    def validate_shape(self) -> None:
        for value, label in (
                (self.freeze_sha256, "external freeze SHA-256"),
                (self.admission_sha256, "admission SHA-256"),
                (self.audit_attempt_sha256, "audit attempt SHA-256"),
                (self.continuation_manifest_sha256,
                 "continuation manifest SHA-256")):
            _digest(value, label)
        _validate_outcomes(self.audit_outcomes)
        checkpoint_rows = _ordered_pairs(
                self.checkpoint_manifest_sha256s, COHORT_LABELS,
                "checkpoint manifest")
        for label, digest in checkpoint_rows:
            _digest(digest, f"checkpoint manifest {label}")
        if len({digest for _, digest in checkpoint_rows}) != len(COHORT_LABELS):
            raise WorldAfterstateV2AuditDerivationError(
                "checkpoint manifest duplicate population")
        _ordered_pairs(self.prediction_manifests, COHORT_LABELS,
                       "prediction manifest")
        for label, manifest in self.prediction_manifests:
            name, block = _CONTROL_BY_LABEL[label]
            if type(manifest) is not dict:
                raise WorldAfterstateV2AuditDerivationError(
                    f"prediction manifest {label} type drift")
            try:
                validate_prediction_population_manifest_v2(manifest)
            except Exception as exc:
                raise WorldAfterstateV2AuditDerivationError(
                    f"prediction manifest {label} refused") from exc
            if (manifest["split"], manifest["control_name"],
                    manifest["seed_block"]) != ("audit", name, block):
                raise WorldAfterstateV2AuditDerivationError(
                    f"prediction manifest {label} binding drift")
        _ordered_pairs(self.cohort_manifests, COHORT_LABELS, "cohort manifest")
        for label, manifest in self.cohort_manifests:
            name, block = _CONTROL_BY_LABEL[label]
            try:
                validate_cohort_manifest(manifest)
            except Exception as exc:
                raise WorldAfterstateV2AuditDerivationError(
                    f"cohort manifest {label} refused") from exc
            if (manifest.get("cohort_name"), manifest.get("seed_block"),
                    manifest.get("freeze_sha256")) != (name, block, self.freeze_sha256):
                raise WorldAfterstateV2AuditDerivationError(
                    f"cohort manifest {label} binding drift")
        if type(self.p0_report) is not dict:
            raise WorldAfterstateV2AuditDerivationError("P0 report type drift")
        try:
            validate_precision_label(self.p0_report)
        except Exception as exc:
            raise WorldAfterstateV2AuditDerivationError("P0 report refused") from exc
        if type(self.optimizer_canary) is not OptimizerCanaryReceiptV2:
            raise WorldAfterstateV2AuditDerivationError("optimizer canary type drift")
        if type(self.precision_select_result) is not EvaluationResultV2:
            raise WorldAfterstateV2AuditDerivationError("precision result type drift")
        if type(self.model_selector_power) is not ModelSelectorPowerReceiptV2:
            raise WorldAfterstateV2AuditDerivationError("power result type drift")
        if type(self.prior) is not JeffreysPriorV2:
            raise WorldAfterstateV2AuditDerivationError("prior type drift")
        try:
            validate_optimizer_canary_v2(self.optimizer_canary)
            self.precision_select_result.validate()
            validate_model_selector_power_v2(self.model_selector_power)
            self.prior.validate()
        except Exception as exc:
            raise WorldAfterstateV2AuditDerivationError(
                "upstream typed receipt refused") from exc
        if (self.precision_select_result.control_name,
                self.precision_select_result.seed_block) != ("natural", 1):
            raise WorldAfterstateV2AuditDerivationError(
                "precision-select identity drift")
        if type(self.control_dose_evidence) is not dict \
                or tuple(self.control_dose_evidence) != DOSE_LABELS:
            raise WorldAfterstateV2AuditDerivationError(
                "control dose population/order drift")
        for name in DOSE_LABELS:
            evidence = self.control_dose_evidence[name]
            if type(evidence) is not dict:
                raise WorldAfterstateV2AuditDerivationError(
                    f"control dose {name} type drift")
            try:
                validate_control_evidence(evidence)
            except Exception as exc:
                raise WorldAfterstateV2AuditDerivationError(
                    f"control dose {name} refused") from exc
            expected_name = {
                "association": "action-association-permutation",
                "label": "label-permutation", "world": "complete-world-shuffle",
            }[name]
            if evidence.get("control_name") != expected_name:
                raise WorldAfterstateV2AuditDerivationError(
                    f"control dose {name} binding drift")


@dataclass(frozen=True)
class AuditDerivationResultV2:
    evidence: WorldAfterstateV2TerminalEvidence
    provenance: AuditProvenanceV2


def _derive(inputs: AuditDerivationInputV2) -> AuditDerivationResultV2:
    if type(inputs) is not AuditDerivationInputV2:
        raise WorldAfterstateV2AuditDerivationError("audit input type drift")
    inputs.validate_shape()
    prediction_rows = tuple(inputs.prediction_manifests)
    outcomes = _validate_outcomes(inputs.audit_outcomes)
    evaluations: dict[str, EvaluationResultV2] = {}
    root_states_expected: set[str] | None = None
    for label, manifest in prediction_rows:
        try:
            root_states = {row["state_sha256"] for row in manifest["root_bindings"]}
            outcome_states = {row.state_sha256 for row in outcomes}
            if root_states != outcome_states:
                raise ValueError("prediction root population mismatch")
            if root_states_expected is None:
                root_states_expected = root_states
            elif root_states != root_states_expected:
                raise ValueError("prediction root population mixing")
            evaluations[label] = evaluate_v2(
                manifest, outcomes, inputs.prior,
                control_name=manifest["control_name"],
                seed_block=manifest["seed_block"])
        except Exception as exc:
            raise WorldAfterstateV2AuditDerivationError(
                f"audit evaluation {label} refused") from exc
    by_label = evaluations
    comparisons = {}
    for label in COMPARISON_LABELS:
        control_name, block = _COMPARISON_BY_LABEL[label]
        natural_label = f"natural:block-{block}"
        try:
            comparisons[(control_name, block)] = evaluate_control_difference(
                by_label[natural_label], by_label[f"{control_name}:block-{block}"])
        except Exception as exc:
            raise WorldAfterstateV2AuditDerivationError(
                f"comparison {label} derivation refused") from exc

    upstream = (
        ("p0", _receipt_hash(inputs.p0_report, "p0")),
        ("optimizer_canary", inputs.optimizer_canary.sha256()),
        ("precision_select", inputs.precision_select_result.sha256()),
        ("model_selector_power", inputs.model_selector_power.sha256()),
    )
    prediction_digests = tuple((label, _manifest_hash(manifest, label))
                               for label, manifest in prediction_rows)
    cohort_digests = tuple((label, _manifest_hash(manifest, label))
                           for label, manifest in inputs.cohort_manifests)
    evaluation_digests = tuple((label, by_label[label].sha256())
                                for label in COHORT_LABELS)
    comparison_digests = tuple(
        (label, comparisons[_COMPARISON_BY_LABEL[label]].sha256())
        for label in COMPARISON_LABELS)
    dose_digests = tuple((label, _sha(inputs.control_dose_evidence[label]))
                         for label in DOSE_LABELS)
    provenance = AuditProvenanceV2(
        freeze_sha256=inputs.freeze_sha256,
        admission_sha256=inputs.admission_sha256,
        audit_attempt_sha256=inputs.audit_attempt_sha256,
        audit_opened_count=1,
        continuation_manifest_sha256=inputs.continuation_manifest_sha256,
        prediction_manifest_sha256s=prediction_digests,
        checkpoint_manifest_sha256s=inputs.checkpoint_manifest_sha256s,
        cohort_manifest_sha256s=cohort_digests,
        evaluation_result_sha256s=evaluation_digests,
        upstream_receipt_sha256s=upstream,
        comparison_sha256s=comparison_digests,
        dose_sha256s=dose_digests)
    try:
        provenance.validate()
        evidence = WorldAfterstateV2TerminalEvidence(
            p0_report=inputs.p0_report,
            optimizer_canary=inputs.optimizer_canary,
            precision_select_result=inputs.precision_select_result,
            model_selector_power=inputs.model_selector_power,
            audit_natural_results={1: by_label["natural:block-1"],
                                   2: by_label["natural:block-2"]},
            audit_control_results={
                name: {block: by_label[f"{name}:block-{block}"]
                       for block in (1, 2)
                       if f"{name}:block-{block}" in by_label}
                for name in ("action-association-permutation", "label-permutation",
                             "complete-world-shuffle")},
            control_comparisons=comparisons,
            control_dose_evidence=inputs.control_dose_evidence,
            audit_provenance=provenance,
            cohort_manifests=tuple(manifest for _, manifest in inputs.cohort_manifests),
            audit_opened_count=1)
        terminal = derive_terminal_result(evidence)
        if terminal.decision == "REFUSE_RESOURCE_INCOMPLETE":
            raise ValueError("complete audit unexpectedly routed to resource refusal")
    except Exception as exc:
        raise WorldAfterstateV2AuditDerivationError(
            "terminal evidence derivation refused") from exc
    return AuditDerivationResultV2(evidence=evidence, provenance=provenance)


def derive_audit_v2(inputs: AuditDerivationInputV2) -> AuditDerivationResultV2:
    return _derive(inputs)


def derive_audit_evidence_v2(
        inputs: AuditDerivationInputV2) -> WorldAfterstateV2TerminalEvidence:
    return _derive(inputs).evidence


def derive_audit_provenance_v2(inputs: AuditDerivationInputV2) -> AuditProvenanceV2:
    return _derive(inputs).provenance


__all__ = [
    "AUDIT_COHORTS", "AuditDerivationInputV2", "AuditDerivationResultV2",
    "WorldAfterstateV2AuditDerivationError", "derive_audit_evidence_v2",
    "derive_audit_provenance_v2", "derive_audit_v2",
]
