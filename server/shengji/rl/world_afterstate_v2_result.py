"""Pure, stage-aware terminal routing for Value-Afterstate V2.

This module is deliberately a boundary, rather than a controller.  It only
reopens already sealed receipts and computes the first matching route from the
V2 design.  In particular, the booleans published by reports are never used
as gates when the underlying metric is available.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .belief_contract import canonical_json_bytes
from .world_afterstate_v2_diagnostics import (
    ModelSelectorPowerReceiptV2, OptimizerCanaryReceiptV2,
    validate_model_selector_power_v2, validate_optimizer_canary_v2,
)
from .world_afterstate_v2_evaluation import (
    ControlComparisonV2, EvaluationResultV2, evaluate_control_difference,
    validate_control_comparison, validate_evaluation_result,
)
from .world_afterstate_v2_label import validate_precision_label
from .world_afterstate_v2_controls import validate_control_evidence
from .world_afterstate_v2_training_controller import validate_cohort_manifest


SCHEMA = "world-afterstate-v2-terminal-result-v1"
DECISIONS = (
    "REFUSE_MECHANICS_OR_CONTROL", "REFUSE_RESOURCE_INCOMPLETE",
    "REFUSE_TRAINING_RECIPE", "STOP_NO_REPRODUCIBLE_VALUE_LABEL",
    "STOP_BELOW_WORTHWHILE_VALUE_FLOOR", "STOP_UNDERPOWERED",
    "SELECT_NONE_PREAUDIT_LEARNING", "SELECT_NONE_NO_ABSOLUTE_VALUE",
    "SELECT_NONE_NO_ACTION_SENSITIVITY", "SELECT_NONE_NO_WORLD_SIGNAL",
    "PASS_ABSOLUTE_VALUE_LEARNING_ONLY",
    "PASS_ABSOLUTE_VALUE_AND_ACTION_EDGE_TO_CONSUMER_DESIGN",
)
STAGES = ("p0", "training", "precision-select", "audit")
CONTROL_NAMES = (
    "action-association-permutation", "label-permutation",
    "complete-world-shuffle",
)
ASSOCIATION_CONTROL = "action-association-permutation"
LABEL_CONTROL = "label-permutation"
WORLD_CONTROL = "complete-world-shuffle"
REQUIRED_CONTROL_BLOCKS = {
    ASSOCIATION_CONTROL: (1,),
    LABEL_CONTROL: (1,),
    WORLD_CONTROL: (1, 2),
}
MICROLEVELS = 1_000_000
WORTHWHILE_MICROLEVELS = 100_000
MINIMUM_DOSE_PPM = 50_000

# Named constants make the frozen precedence usable without copying strings.
REFUSE_MECHANICS_OR_CONTROL = "REFUSE_MECHANICS_OR_CONTROL"
REFUSE_RESOURCE_INCOMPLETE = "REFUSE_RESOURCE_INCOMPLETE"
REFUSE_TRAINING_RECIPE = "REFUSE_TRAINING_RECIPE"
STOP_NO_REPRODUCIBLE_VALUE_LABEL = "STOP_NO_REPRODUCIBLE_VALUE_LABEL"
STOP_BELOW_WORTHWHILE_VALUE_FLOOR = "STOP_BELOW_WORTHWHILE_VALUE_FLOOR"
STOP_UNDERPOWERED = "STOP_UNDERPOWERED"
SELECT_NONE_PREAUDIT_LEARNING = "SELECT_NONE_PREAUDIT_LEARNING"
SELECT_NONE_NO_ABSOLUTE_VALUE = "SELECT_NONE_NO_ABSOLUTE_VALUE"
SELECT_NONE_NO_ACTION_SENSITIVITY = "SELECT_NONE_NO_ACTION_SENSITIVITY"
SELECT_NONE_NO_WORLD_SIGNAL = "SELECT_NONE_NO_WORLD_SIGNAL"
PASS_ABSOLUTE_VALUE_LEARNING_ONLY = "PASS_ABSOLUTE_VALUE_LEARNING_ONLY"
PASS_ABSOLUTE_VALUE_AND_ACTION_EDGE_TO_CONSUMER_DESIGN = (
    "PASS_ABSOLUTE_VALUE_AND_ACTION_EDGE_TO_CONSUMER_DESIGN")

# This is intentionally a separate copy: a terminal result cannot acquire
# authority merely because another V2 module grows a new authority key.
AUTHORITY = {
    "optimizer_authorized": False,
    "training_authorized": False,
    "data_opening_authorized": False,
    "label_opening_authorized": False,
    "audit_opening_authorized": False,
    "terminal_route_authorized": False,
    "consumer_authorized": False,
    "puct_authorized": False,
    "rollout_authorized": False,
    "belief_authorized": False,
    "gameplay_authorized": False,
    "strength_claim_authorized": False,
    "merge_authorized": False,
    "promotion_authorized": False,
    "deployment_authorized": False,
    "retry_authorized": False,
}


class WorldAfterstateV2ResultError(ValueError):
    """Terminal evidence or its canonical route was malformed."""


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _digest(value: object, label: str) -> str:
    if type(value) is not str or len(value) != 64 \
            or any(char not in "0123456789abcdef" for char in value):
        raise WorldAfterstateV2ResultError(f"{label} drift")
    return value


def _bool(value: object, label: str) -> bool:
    if type(value) is not bool:
        raise WorldAfterstateV2ResultError(f"{label} drift")
    return value


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise WorldAfterstateV2ResultError(f"{label} drift")
    return value


def _p0_gates(report: Mapping[str, Any]) -> tuple[bool, bool, bool, bool, bool]:
    """Reconstruct P0 mechanics/statistical/floor gates from exact fields."""
    try:
        validate_precision_label(report)
        exact = report["gate_fractions"]
        # validate_precision_label has already checked canonical Fractions and
        # their integer projections.  The fractions are intentionally read,
        # rather than the report's asserted ``*_passed`` fields.
        def positive(name: str) -> bool:
            row = exact[name]
            return row["numerator"] > 0

        statistical = (
            positive("direction_0_to_1")
            and positive("direction_1_to_0")
            and exact["combined_bootstrap_lower"]["numerator"] > 0
            and report["sibling_same_nonzero_sign_ppm"] >= 50_000
            and report["sibling_advantage_correlation_bootstrap_lower_ppm"] > 0
        )
        # Avoid a float comparison in the floor check.
        floor = (exact["chosen_minus_incumbent_mean"]["numerator"] * MICROLEVELS
                 >= WORTHWHILE_MICROLEVELS
                 * exact["chosen_minus_incumbent_mean"]["denominator"])
        return (
            report["mechanics_passed"], statistical,
            positive("direction_0_to_1") and positive("direction_1_to_0")
            and exact["combined_bootstrap_lower"]["numerator"] > 0
            and report["sibling_same_nonzero_sign_ppm"] >= 50_000
            and report["sibling_advantage_correlation_bootstrap_lower_ppm"] > 0,
            floor, report["decision"] == "PASS_P0_PRECISION")
    except Exception as exc:
        if isinstance(exc, WorldAfterstateV2ResultError):
            raise
        raise WorldAfterstateV2ResultError("P0 report refused") from exc


def _receipt_sha(value: object) -> str:
    if isinstance(value, Mapping):
        if "result_sha256" in value:
            return _digest(value["result_sha256"], "receipt result SHA-256")
        return _sha(value)
    if hasattr(value, "sha256") and callable(value.sha256):
        return _digest(value.sha256(), "receipt SHA-256")
    raise WorldAfterstateV2ResultError("receipt type drift")


def _validate_eval(value: object, label: str) -> EvaluationResultV2:
    if type(value) is not EvaluationResultV2:
        raise WorldAfterstateV2ResultError(f"{label} type drift")
    try:
        validate_evaluation_result(value)
    except Exception as exc:
        raise WorldAfterstateV2ResultError(f"{label} refused") from exc
    return value


def _as_blocks(value: object, label: str) -> dict[int, EvaluationResultV2]:
    if isinstance(value, Mapping):
        pairs = value.items()
    elif isinstance(value, (tuple, list)):
        pairs = ((item.seed_block, item) for item in value)
    else:
        raise WorldAfterstateV2ResultError(f"{label} population drift")
    result: dict[int, EvaluationResultV2] = {}
    for key, item in pairs:
        if isinstance(key, bool) or key not in (1, 2):
            raise WorldAfterstateV2ResultError(f"{label} block drift")
        parsed = _validate_eval(item, label)
        if parsed.seed_block != key or parsed.control_name != "natural":
            raise WorldAfterstateV2ResultError(f"{label} binding drift")
        if key in result:
            raise WorldAfterstateV2ResultError(f"{label} duplicate block")
        result[key] = parsed
    return result


def _control_blocks(value: object, name: str) -> dict[int, EvaluationResultV2]:
    if isinstance(value, Mapping):
        # Accept either {1: result, 2: result} or {name: {1: result, 2: result}}.
        if name in value:
            value = value[name]
        result = {}
        for key, item in value.items():
            if isinstance(key, bool) or key not in (1, 2):
                raise WorldAfterstateV2ResultError(f"{name} block drift")
            parsed = _validate_eval(item, f"{name} evaluation")
            if parsed.seed_block != key or parsed.control_name != name:
                raise WorldAfterstateV2ResultError(f"{name} binding drift")
            result[key] = parsed
        return result
    if isinstance(value, (tuple, list)):
        result = {}
        for item in value:
            parsed = _validate_eval(item, f"{name} evaluation")
            if parsed.control_name != name or parsed.seed_block in result:
                raise WorldAfterstateV2ResultError(f"{name} binding drift")
            result[parsed.seed_block] = parsed
        return result
    raise WorldAfterstateV2ResultError(f"{name} evaluation population drift")


def _comparison_blocks(value: object) -> dict[tuple[str, int], ControlComparisonV2]:
    if isinstance(value, Mapping):
        values = value.values()
    elif isinstance(value, (tuple, list)):
        values = value
    else:
        raise WorldAfterstateV2ResultError("control comparison population drift")
    result: dict[tuple[str, int], ControlComparisonV2] = {}
    for item in values:
        if type(item) is not ControlComparisonV2:
            raise WorldAfterstateV2ResultError("control comparison type drift")
        try:
            validate_control_comparison(item)
        except Exception as exc:
            raise WorldAfterstateV2ResultError("control comparison refused") from exc
        key = (item.control_name, item.seed_block)
        if key in result:
            raise WorldAfterstateV2ResultError("duplicate control comparison")
        result[key] = item
    return result


def _control_dose(doses: Mapping[str, Any], needed: Sequence[str]) -> dict[str, str]:
    result = {}
    for name in needed:
        evidence = doses.get(name)
        if not isinstance(evidence, Mapping):
            raise WorldAfterstateV2ResultError("control-dose evidence incomplete")
        try:
            validate_control_evidence(evidence)
        except Exception as exc:
            raise WorldAfterstateV2ResultError("control-dose evidence refused") from exc
        if evidence.get("control_name") != name \
                or evidence.get("dose_ppm", 0) < MINIMUM_DOSE_PPM:
            raise WorldAfterstateV2ResultError("control-dose evidence below minimum")
        result[name] = _receipt_sha(evidence)
    return result


@dataclass(frozen=True)
class WorldAfterstateV2TerminalEvidence:
    """Typed collection of sealed evidence at the furthest reached stage."""

    p0_report: Mapping[str, Any] | None = None
    optimizer_canary: OptimizerCanaryReceiptV2 | None = None
    precision_select_result: EvaluationResultV2 | None = None
    model_selector_power: ModelSelectorPowerReceiptV2 | None = None
    audit_natural_results: Mapping[int, EvaluationResultV2] | Sequence[EvaluationResultV2] | None = None
    audit_control_results: Mapping[str, Any] | None = None
    control_comparisons: Mapping[Any, ControlComparisonV2] | Sequence[ControlComparisonV2] | None = None
    control_dose_evidence: Mapping[str, Mapping[str, Any]] | None = None
    # A manifest is optional because the training controller publishes a dict;
    # when supplied, truncation is rederived from its source fields.
    cohort_manifests: Sequence[Mapping[str, Any]] = ()
    cohort_truncated: bool = False
    resource_incomplete: bool = False
    resource_stage: str | None = None
    resource_cap_exceeded: bool = False
    mechanics_failure: bool = False
    mechanics_stage: str | None = None
    audit_opened_count: int = 0
    schema: str = "world-afterstate-v2-terminal-evidence-v1"

    def validate_shape(self) -> None:
        if self.schema != "world-afterstate-v2-terminal-evidence-v1":
            raise WorldAfterstateV2ResultError("terminal evidence schema drift")
        _bool(self.resource_incomplete, "resource incomplete")
        _bool(self.resource_cap_exceeded, "resource cap")
        _bool(self.mechanics_failure, "mechanics failure")
        _bool(self.cohort_truncated, "cohort truncation")
        if isinstance(self.audit_opened_count, bool) \
                or not isinstance(self.audit_opened_count, int) \
                or self.audit_opened_count < 0:
            raise WorldAfterstateV2ResultError("audit opened count drift")
        if self.resource_stage is not None and self.resource_stage not in STAGES:
            raise WorldAfterstateV2ResultError("resource stage drift")
        if self.mechanics_stage is not None and self.mechanics_stage not in STAGES:
            raise WorldAfterstateV2ResultError("mechanics stage drift")
        if self.mechanics_failure != (self.mechanics_stage is not None):
            raise WorldAfterstateV2ResultError("mechanics failure/stage drift")
        for manifest in self.cohort_manifests:
            try:
                validate_cohort_manifest(manifest)
            except Exception as exc:
                raise WorldAfterstateV2ResultError(
                    "cohort manifest refused") from exc
        if self.resource_stage is not None and not (
                self.resource_incomplete or self.resource_cap_exceeded
                or self.cohort_truncated or any(
                    manifest.get("truncated_by_deadline") is True
                    or manifest.get("audit_eligible") is False
                    or manifest.get("resource_cap_exceeded") is True
                    for manifest in self.cohort_manifests)):
            raise WorldAfterstateV2ResultError(
                "resource failure/stage drift")


@dataclass(frozen=True)
class WorldAfterstateV2TerminalResult:
    stage_reached: str
    audit_opened_count: int
    input_receipt_hashes: tuple[tuple[str, str], ...]
    decision: str
    authority: Mapping[str, bool] = field(default_factory=lambda: dict(AUTHORITY))
    schema: str = SCHEMA
    result_sha256: str = ""

    def payload(self) -> dict[str, Any]:
        return {
            "schema": self.schema, "stage_reached": self.stage_reached,
            "audit_opened_count": self.audit_opened_count,
            "input_receipt_hashes": [list(item) for item in self.input_receipt_hashes],
            "decision": self.decision, "authority": dict(self.authority),
        }

    def sha256(self) -> str:
        return _sha(self.payload())

    def validate(self) -> None:
        _validate_result_shape(self)


def _resource_incomplete(evidence: WorldAfterstateV2TerminalEvidence) -> bool:
    if (evidence.resource_incomplete or evidence.resource_cap_exceeded
            or evidence.cohort_truncated):
        return True
    for manifest in evidence.cohort_manifests:
        if not isinstance(manifest, Mapping):
            raise WorldAfterstateV2ResultError("cohort manifest type drift")
        if manifest.get("truncated_by_deadline") is True \
                or manifest.get("audit_eligible") is False \
                or manifest.get("resource_cap_exceeded") is True:
            return True
    return False


def _resource_stage(evidence: WorldAfterstateV2TerminalEvidence) -> str | None:
    """Locate a resource failure at the earliest stage it can affect."""
    if not _resource_incomplete(evidence):
        return None
    if evidence.resource_stage is not None:
        return evidence.resource_stage
    if evidence.p0_report is None:
        return "p0"
    if evidence.cohort_truncated or any(
            manifest.get("truncated_by_deadline") is True
            or manifest.get("audit_eligible") is False
            or manifest.get("resource_cap_exceeded") is True
            for manifest in evidence.cohort_manifests):
        return "training"
    if evidence.optimizer_canary is None:
        return "training"
    if evidence.precision_select_result is None \
            or evidence.model_selector_power is None:
        return "precision-select"
    return "audit"


def _audit_evidence_present(evidence: WorldAfterstateV2TerminalEvidence) -> bool:
    return evidence.audit_opened_count != 0 or any(value is not None for value in (
        evidence.audit_natural_results, evidence.audit_control_results,
        evidence.control_comparisons, evidence.control_dose_evidence))


def _reject_after_stop(evidence: WorldAfterstateV2TerminalEvidence, stage: str) -> None:
    """A valid early stop may not coexist with artifacts from later stages."""
    if stage == "p0":
        forbidden = bool(evidence.cohort_manifests) or any(
            value is not None for value in (
                evidence.optimizer_canary, evidence.precision_select_result,
                evidence.model_selector_power)) or _audit_evidence_present(evidence)
    elif stage == "training":
        forbidden = any(value is not None for value in (
            evidence.precision_select_result,
            evidence.model_selector_power)) or _audit_evidence_present(evidence)
    elif stage == "precision-select":
        forbidden = _audit_evidence_present(evidence)
    else:
        forbidden = False
    if forbidden:
        raise WorldAfterstateV2ResultError(
            f"downstream evidence after {stage} stop")


def _input_hashes(e: WorldAfterstateV2TerminalEvidence) -> tuple[tuple[str, str], ...]:
    rows: list[tuple[str, str]] = [("terminal_stage_assertions", _sha({
        "resource_incomplete": e.resource_incomplete,
        "resource_cap_exceeded": e.resource_cap_exceeded,
        "resource_stage": e.resource_stage,
        "cohort_truncated": e.cohort_truncated,
        "mechanics_failure": e.mechanics_failure,
        "mechanics_stage": e.mechanics_stage,
        "audit_opened_count": e.audit_opened_count,
    }))]
    if e.p0_report is not None:
        rows.append(("p0", _receipt_sha(e.p0_report)))
    if e.optimizer_canary is not None:
        rows.append(("optimizer_canary", _receipt_sha(e.optimizer_canary)))
    if e.precision_select_result is not None:
        rows.append(("precision_select", _receipt_sha(e.precision_select_result)))
    if e.model_selector_power is not None:
        rows.append(("model_selector_power", _receipt_sha(e.model_selector_power)))
    for key, value in sorted(_as_blocks(e.audit_natural_results, "audit natural").items()) \
            if e.audit_natural_results is not None else ():
        rows.append((f"audit_natural_{key}", _receipt_sha(value)))
    if e.control_comparisons is not None:
        for (name, block), value in sorted(_comparison_blocks(e.control_comparisons).items()):
            rows.append((f"control_comparison_{name}_{block}", _receipt_sha(value)))
    if e.audit_control_results is not None:
        for name in sorted(e.audit_control_results):
            blocks = _control_blocks(e.audit_control_results[name], name)
            for block, value in sorted(blocks.items()):
                rows.append((f"audit_control_{name}_{block}", _receipt_sha(value)))
    if e.control_dose_evidence is not None:
        for name, value in sorted(e.control_dose_evidence.items()):
            rows.append((f"control_dose_{name}", _receipt_sha(value)))
    for index, manifest in enumerate(e.cohort_manifests):
        rows.append((f"cohort_manifest_{index}", _sha(manifest)))
    return tuple(rows)


def _validate_p0_and_route(e: WorldAfterstateV2TerminalEvidence) -> tuple[str | None, str]:
    if e.p0_report is None:
        return "p0", "REFUSE_RESOURCE_INCOMPLETE"
    mechanics, statistical, _, floor, _ = _p0_gates(e.p0_report)
    if (e.mechanics_failure and e.mechanics_stage == "p0") or not mechanics:
        return "p0", "REFUSE_MECHANICS_OR_CONTROL"
    if not statistical:
        return "p0", "STOP_NO_REPRODUCIBLE_VALUE_LABEL"
    if not floor:
        return "p0", "STOP_BELOW_WORTHWHILE_VALUE_FLOOR"
    return None, ""


def derive_terminal_result(evidence: WorldAfterstateV2TerminalEvidence) -> WorldAfterstateV2TerminalResult:
    """Derive the frozen first-match terminal route without side effects."""
    if type(evidence) is not WorldAfterstateV2TerminalEvidence:
        raise WorldAfterstateV2ResultError("terminal evidence type drift")
    evidence.validate_shape()
    resource_stage = _resource_stage(evidence)
    # Resource/deadline failure is first-match at the stage where it occurred.
    # A later-stage marker is intentionally irrelevant when an earlier stop is
    # already valid (downstream artifacts are then correctly absent).
    if resource_stage == "p0":
        _reject_after_stop(evidence, "p0")
        result = WorldAfterstateV2TerminalResult(
            stage_reached="p0", audit_opened_count=0,
            input_receipt_hashes=_input_hashes(evidence),
            decision="REFUSE_RESOURCE_INCOMPLETE")
        return _seal(result)
    stage, decision = _validate_p0_and_route(evidence)
    p0_passed = stage is None
    if not p0_passed:
        _reject_after_stop(evidence, "p0")
        result = WorldAfterstateV2TerminalResult(
            stage_reached=stage or "p0", audit_opened_count=0,
            input_receipt_hashes=_input_hashes(evidence), decision=decision)
        return _seal(result)

    if resource_stage == "training":
        _reject_after_stop(evidence, "training")
        return _seal(WorldAfterstateV2TerminalResult(
            "training", 0, _input_hashes(evidence),
            "REFUSE_RESOURCE_INCOMPLETE"))
    if evidence.optimizer_canary is None:
        _reject_after_stop(evidence, "training")
        return _seal(WorldAfterstateV2TerminalResult(
            "training", 0, _input_hashes(evidence), "REFUSE_RESOURCE_INCOMPLETE"))
    if type(evidence.optimizer_canary) is not OptimizerCanaryReceiptV2:
        raise WorldAfterstateV2ResultError("optimizer canary type drift")
    try:
        validate_optimizer_canary_v2(evidence.optimizer_canary)
    except Exception as exc:
        raise WorldAfterstateV2ResultError("optimizer canary refused") from exc
    if evidence.optimizer_canary.source_p0_population_sha256 \
            != evidence.p0_report["population_sha256"]:
        raise WorldAfterstateV2ResultError("optimizer canary/P0 binding drift")
    if evidence.mechanics_failure and evidence.mechanics_stage == "training":
        _reject_after_stop(evidence, "training")
        return _seal(WorldAfterstateV2TerminalResult(
            "training", 0, _input_hashes(evidence),
            "REFUSE_MECHANICS_OR_CONTROL"))
    if not evidence.optimizer_canary.passed:
        _reject_after_stop(evidence, "training")
        return _seal(WorldAfterstateV2TerminalResult(
            "training", 0, _input_hashes(evidence), "REFUSE_TRAINING_RECIPE"))

    if resource_stage == "precision-select":
        _reject_after_stop(evidence, "precision-select")
        return _seal(WorldAfterstateV2TerminalResult(
            "precision-select", 0, _input_hashes(evidence),
            "REFUSE_RESOURCE_INCOMPLETE"))
    if evidence.precision_select_result is None:
        _reject_after_stop(evidence, "precision-select")
        return _seal(WorldAfterstateV2TerminalResult(
            "precision-select", 0, _input_hashes(evidence),
            "REFUSE_RESOURCE_INCOMPLETE"))
    if evidence.mechanics_failure and evidence.mechanics_stage == "precision-select":
        _reject_after_stop(evidence, "precision-select")
        return _seal(WorldAfterstateV2TerminalResult(
            "precision-select", 0, _input_hashes(evidence),
            "REFUSE_MECHANICS_OR_CONTROL"))
    precision = _validate_eval(evidence.precision_select_result, "precision-select")
    if precision.control_name != "natural" or precision.seed_block != 1:
        raise WorldAfterstateV2ResultError("precision-select binding drift")
    # Preadmission is deliberately narrower than audit learning gates: it
    # requires RPS, paired-error, and member-RPS evidence, as specified in
    # Section 9, but does not turn absolute-error gate 2 into an extra stop.
    if not (precision.rps_improvement.lower_5th > 0
            and precision.paired_error_improvement.lower_5th > 0
            and precision.positive_rps_member_count >= 3):
        _reject_after_stop(evidence, "precision-select")
        return _seal(WorldAfterstateV2TerminalResult(
            "precision-select", 0, _input_hashes(evidence),
            "SELECT_NONE_PREAUDIT_LEARNING"))
    if evidence.model_selector_power is None:
        _reject_after_stop(evidence, "precision-select")
        return _seal(WorldAfterstateV2TerminalResult(
            "precision-select", 0, _input_hashes(evidence),
            "REFUSE_RESOURCE_INCOMPLETE"))
    if type(evidence.model_selector_power) is not ModelSelectorPowerReceiptV2:
        raise WorldAfterstateV2ResultError("model-selector power type drift")
    try:
        validate_model_selector_power_v2(evidence.model_selector_power)
    except Exception as exc:
        raise WorldAfterstateV2ResultError("model-selector power refused") from exc
    if evidence.model_selector_power.precision_select_population_sha256 \
            != precision.population_sha256:
        raise WorldAfterstateV2ResultError("power/precision-select binding drift")
    if evidence.model_selector_power.stop_underpowered:
        _reject_after_stop(evidence, "precision-select")
        return _seal(WorldAfterstateV2TerminalResult(
            "precision-select", 0, _input_hashes(evidence), "STOP_UNDERPOWERED"))

    if resource_stage == "audit":
        return _seal(WorldAfterstateV2TerminalResult(
            "audit", evidence.audit_opened_count, _input_hashes(evidence),
            "REFUSE_RESOURCE_INCOMPLETE"))
    if evidence.mechanics_failure and evidence.mechanics_stage == "audit":
        return _seal(WorldAfterstateV2TerminalResult(
            evidence.resource_stage or "audit", evidence.audit_opened_count,
            _input_hashes(evidence), "REFUSE_MECHANICS_OR_CONTROL"))
    if evidence.audit_opened_count > 1 \
            or evidence.audit_opened_count == 0 and any(
                value is not None for value in (
                    evidence.audit_natural_results,
                    evidence.audit_control_results,
                    evidence.control_comparisons,
                    evidence.control_dose_evidence)):
        return _seal(WorldAfterstateV2TerminalResult(
            "audit", evidence.audit_opened_count, _input_hashes(evidence),
            "REFUSE_MECHANICS_OR_CONTROL"))
    if evidence.audit_opened_count == 0:
        return _seal(WorldAfterstateV2TerminalResult(
            "audit", evidence.audit_opened_count, _input_hashes(evidence),
            "REFUSE_RESOURCE_INCOMPLETE"))
    if evidence.audit_natural_results is None \
            or evidence.audit_control_results is None \
            or evidence.control_comparisons is None \
            or evidence.control_dose_evidence is None:
        return _seal(WorldAfterstateV2TerminalResult(
            "audit", evidence.audit_opened_count, _input_hashes(evidence),
            "REFUSE_RESOURCE_INCOMPLETE"))

    natural = _as_blocks(evidence.audit_natural_results, "audit natural")
    if set(natural) != {1, 2}:
        return _seal(WorldAfterstateV2TerminalResult(
            "audit", evidence.audit_opened_count, _input_hashes(evidence),
            "REFUSE_RESOURCE_INCOMPLETE"))
    if natural[1].population_sha256 != natural[2].population_sha256:
        return _seal(WorldAfterstateV2TerminalResult(
            "audit", evidence.audit_opened_count, _input_hashes(evidence),
            "REFUSE_MECHANICS_OR_CONTROL"))
    try:
        comparisons = _comparison_blocks(evidence.control_comparisons)
    except WorldAfterstateV2ResultError:
        return _seal(WorldAfterstateV2TerminalResult(
            "audit", evidence.audit_opened_count, _input_hashes(evidence),
            "REFUSE_MECHANICS_OR_CONTROL"))
    if any(name not in evidence.control_dose_evidence for name in CONTROL_NAMES):
        return _seal(WorldAfterstateV2TerminalResult(
            "audit", evidence.audit_opened_count, _input_hashes(evidence),
            "REFUSE_RESOURCE_INCOMPLETE"))
    try:
        _control_dose(evidence.control_dose_evidence, CONTROL_NAMES)
    except WorldAfterstateV2ResultError:
        return _seal(WorldAfterstateV2TerminalResult(
            "audit", evidence.audit_opened_count, _input_hashes(evidence),
            "REFUSE_MECHANICS_OR_CONTROL"))

    controls: dict[str, dict[int, EvaluationResultV2]] = {}
    try:
        for name in CONTROL_NAMES:
            controls[name] = _control_blocks(evidence.audit_control_results.get(name), name)
    except Exception:
        return _seal(WorldAfterstateV2TerminalResult(
            "audit", evidence.audit_opened_count, _input_hashes(evidence),
            "REFUSE_RESOURCE_INCOMPLETE"))
    if any(tuple(sorted(controls[name])) != REQUIRED_CONTROL_BLOCKS[name]
           for name in CONTROL_NAMES) \
            or set(comparisons) != {
                (name, block) for name in CONTROL_NAMES
                for block in REQUIRED_CONTROL_BLOCKS[name]}:
        return _seal(WorldAfterstateV2TerminalResult(
            "audit", evidence.audit_opened_count, _input_hashes(evidence),
            "REFUSE_RESOURCE_INCOMPLETE"))
    if any(controls[name][block].population_sha256 != natural[block].population_sha256
           for name in CONTROL_NAMES for block in REQUIRED_CONTROL_BLOCKS[name]) \
            or any(comparisons[(name, block)].rps_improvement.population_sha256
                   != natural[block].population_sha256
                   for name in CONTROL_NAMES
                   for block in REQUIRED_CONTROL_BLOCKS[name]):
        return _seal(WorldAfterstateV2TerminalResult(
            "audit", evidence.audit_opened_count, _input_hashes(evidence),
            "REFUSE_MECHANICS_OR_CONTROL"))
    try:
        for name in CONTROL_NAMES:
            for block in REQUIRED_CONTROL_BLOCKS[name]:
                if comparisons[(name, block)] != evaluate_control_difference(
                        natural[block], controls[name][block]):
                    raise WorldAfterstateV2ResultError(
                        "control comparison reconstruction drift")
    except Exception:
        return _seal(WorldAfterstateV2TerminalResult(
            "audit", evidence.audit_opened_count, _input_hashes(evidence),
            "REFUSE_MECHANICS_OR_CONTROL"))

    # Required demanded-failure controls are evaluated from the control
    # cohorts' gates, never from a caller's ``passed`` assertion.
    demanded_failure = all(
        not all(controls[name][block].learning_gates_1_to_4)
        for name in (ASSOCIATION_CONTROL, LABEL_CONTROL)
        for block in REQUIRED_CONTROL_BLOCKS[name])
    if not demanded_failure:
        return _seal(WorldAfterstateV2TerminalResult(
            "audit", evidence.audit_opened_count, _input_hashes(evidence),
            "REFUSE_MECHANICS_OR_CONTROL"))

    # Route 9 intentionally excludes paired-advantage gate 3.  If gates
    # 1/2/4 pass but gate 3 fails, route 10 is the more specific diagnosis.
    absolute_learning = (
        natural[1].rps_improvement.lower_5th > 0
        and natural[1].absolute_error_improvement.lower_5th > 0
        and natural[1].positive_rps_member_count >= 3)
    if not absolute_learning:
        return _seal(WorldAfterstateV2TerminalResult(
            "audit", evidence.audit_opened_count, _input_hashes(evidence),
            "SELECT_NONE_NO_ABSOLUTE_VALUE"))
    if natural[1].paired_error_improvement.lower_5th <= 0:
        return _seal(WorldAfterstateV2TerminalResult(
            "audit", evidence.audit_opened_count, _input_hashes(evidence),
            "SELECT_NONE_NO_ACTION_SENSITIVITY"))
    world_ok = all(
        comparisons[(WORLD_CONTROL, block)].rps_improvement.lower_5th > 0
        and comparisons[(WORLD_CONTROL, block)].paired_error_improvement.lower_5th > 0
        and comparisons[(WORLD_CONTROL, block)].positive_rps_member_count >= 3
        and comparisons[(WORLD_CONTROL, block)].positive_paired_member_count >= 3
        for block in (1, 2))
    if not world_ok:
        return _seal(WorldAfterstateV2TerminalResult(
            "audit", evidence.audit_opened_count, _input_hashes(evidence),
            "SELECT_NONE_NO_WORLD_SIGNAL"))
    # Block 1 is the primary ensemble/action claim.  Block 2 is confirmatory
    # replication and contributes to world-signal gate 5 only.  The frozen
    # terminal order evaluates world signal before action usefulness.
    primary = natural[1]
    if not (primary.selected_action_utility.lower_5th >= WORTHWHILE_MICROLEVELS
            and primary.positive_action_utility_member_count >= 3
            and primary.nonincumbent_dose_ppm >= MINIMUM_DOSE_PPM
            and comparisons[(WORLD_CONTROL, 1)].action_utility.lower_5th > 0):
        return _seal(WorldAfterstateV2TerminalResult(
            "audit", evidence.audit_opened_count, _input_hashes(evidence),
            "PASS_ABSOLUTE_VALUE_LEARNING_ONLY"))
    return _seal(WorldAfterstateV2TerminalResult(
        "audit", evidence.audit_opened_count, _input_hashes(evidence),
        "PASS_ABSOLUTE_VALUE_AND_ACTION_EDGE_TO_CONSUMER_DESIGN"))


def _seal(result: WorldAfterstateV2TerminalResult) -> WorldAfterstateV2TerminalResult:
    body = result.payload()
    return WorldAfterstateV2TerminalResult(
        stage_reached=result.stage_reached,
        audit_opened_count=result.audit_opened_count,
        input_receipt_hashes=result.input_receipt_hashes,
        decision=result.decision, authority=dict(AUTHORITY), schema=SCHEMA,
        result_sha256=_sha(body))


def _validate_result_shape(result: object) -> None:
    if type(result) is not WorldAfterstateV2TerminalResult \
            or result.schema != SCHEMA \
            or result.stage_reached not in STAGES \
            or result.decision not in DECISIONS \
            or result.authority != AUTHORITY \
            or isinstance(result.audit_opened_count, bool) \
            or not isinstance(result.audit_opened_count, int) \
            or result.audit_opened_count < 0 \
            or type(result.input_receipt_hashes) is not tuple \
            or any(type(item) is not tuple or len(item) != 2
                   or type(item[0]) is not str for item in result.input_receipt_hashes):
        raise WorldAfterstateV2ResultError("terminal result schema drift")
    for key, value in result.input_receipt_hashes:
        if not key:
            raise WorldAfterstateV2ResultError("terminal input label drift")
        _digest(value, "terminal input receipt")
    _digest(result.result_sha256, "terminal result SHA-256")


def validate_terminal_result(
        evidence: WorldAfterstateV2TerminalEvidence,
        result: WorldAfterstateV2TerminalResult) -> None:
    """Re-derive and compare a result; coordinated rehashing is rejected."""
    _validate_result_shape(result)
    expected = derive_terminal_result(evidence)
    if result != expected or result.sha256() != result.result_sha256:
        raise WorldAfterstateV2ResultError("terminal result reconstruction drift")


# Friendly aliases used by callers which refer to the route as a router.
TerminalEvidenceV2 = WorldAfterstateV2TerminalEvidence
TerminalResultV2 = WorldAfterstateV2TerminalResult
derive_v2_terminal_result = derive_terminal_result
validate_v2_terminal_result = validate_terminal_result


__all__ = [
    "AUTHORITY", "CONTROL_NAMES", "DECISIONS", "SCHEMA", "STAGES",
    "REFUSE_MECHANICS_OR_CONTROL", "REFUSE_RESOURCE_INCOMPLETE",
    "REFUSE_TRAINING_RECIPE", "STOP_NO_REPRODUCIBLE_VALUE_LABEL",
    "STOP_BELOW_WORTHWHILE_VALUE_FLOOR", "STOP_UNDERPOWERED",
    "SELECT_NONE_PREAUDIT_LEARNING", "SELECT_NONE_NO_ABSOLUTE_VALUE",
    "SELECT_NONE_NO_ACTION_SENSITIVITY", "SELECT_NONE_NO_WORLD_SIGNAL",
    "PASS_ABSOLUTE_VALUE_LEARNING_ONLY",
    "PASS_ABSOLUTE_VALUE_AND_ACTION_EDGE_TO_CONSUMER_DESIGN",
    "TerminalEvidenceV2", "TerminalResultV2",
    "WorldAfterstateV2ResultError", "WorldAfterstateV2TerminalEvidence",
    "WorldAfterstateV2TerminalResult", "derive_terminal_result",
    "derive_v2_terminal_result", "validate_terminal_result",
    "validate_v2_terminal_result",
]
