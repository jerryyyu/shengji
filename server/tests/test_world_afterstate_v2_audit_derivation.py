from __future__ import annotations

import dataclasses
import hashlib

import pytest

from shengji.rl.world_afterstate_v2_audit_derivation import (
    AUDIT_COHORTS, AuditDerivationInputV2,
    WorldAfterstateV2AuditDerivationError, derive_audit_v2,
)
from shengji.rl.world_afterstate_v2_label import ContinuationOutcomeV2
from shengji.rl.world_afterstate_v2_inference import (
    expected_signed_microlevels,
)
from shengji.rl.world_afterstate_v2_result import (
    PASS_ABSOLUTE_VALUE_AND_ACTION_EDGE_TO_CONSUMER_DESIGN,
    derive_terminal_result,
)
from shengji.rl.world_afterstate_v2_training import (
    WorldAfterstateV2TrainingConfig,
)
from shengji.rl.world_afterstate_v2_training_controller import (
    train_named_cohort,
)
from shengji.rl.world_afterstate_v2_terminal_provenance import COHORT_LABELS
from test_world_afterstate_v2_evaluation import (
    _manifest, _population, _probability,
)
from test_world_afterstate_v2_result import (
    ASSOCIATION_CONTROL, LABEL_CONTROL, WORLD_CONTROL,
    _canary, _dose, _evaluation, _p0, _power,
)
from test_world_afterstate_v2_training import _rows
from test_world_afterstate_v2_training_controller import _selection_population


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def _outcome() -> ContinuationOutcomeV2:
    digest = _sha("outcome")
    return ContinuationOutcomeV2(
        deal_sha256=digest, slot_sha256=_sha("slot"), state_sha256=_sha("state"),
        candidate_set_sha256=_sha("set"), source="natural", split="audit",
        role="attacker", phase="early", position="lead", trump_rank="2",
        trump_mode="S", points_bucket="0-39", candidate_index=0,
        protected_incumbent=True, successor_sha256=_sha("successor"),
        continuation_sha256=_sha("continuation"), replica=0,
        signed_level_category=0)


def _input(**changes) -> AuditDerivationInputV2:
    digest = _sha("placeholder")
    body = dict(
        freeze_sha256=digest, admission_sha256=digest,
        audit_attempt_sha256=digest, continuation_manifest_sha256=digest,
        prediction_manifests=tuple((label, {}) for label in COHORT_LABELS),
        checkpoint_manifest_sha256s=tuple(
            (label, _sha(f"checkpoint:{label}")) for label in COHORT_LABELS),
        cohort_manifests=tuple((label, {}) for label in COHORT_LABELS),
        p0_report={}, optimizer_canary=object(), precision_select_result=object(),
        model_selector_power=object(), audit_outcomes=(_outcome(),), prior=object(),
        control_dose_evidence={"association": {}, "label": {}, "world": {}},
    )
    body.update(changes)
    return AuditDerivationInputV2(**body)


def test_input_requires_one_common_outcome_population():
    # A cohort-specific tuple is structurally different from the one shared
    # audit population and is refused before any evaluation can occur.
    grouped = tuple((label, ()) for label in COHORT_LABELS)
    with pytest.raises(WorldAfterstateV2AuditDerivationError,
                       match="outcome"):
        derive_audit_v2(_input(audit_outcomes=grouped))


@pytest.mark.parametrize("mutation", ("drop", "reorder", "foreign"))
def test_prediction_manifest_population_is_exact_and_bound(mutation):
    rows = list(_input().prediction_manifests)
    if mutation == "drop":
        rows.pop()
    elif mutation == "reorder":
        rows[0], rows[1] = rows[1], rows[0]
    else:
        rows[0] = (rows[0][0], {"foreign": True})
    with pytest.raises(WorldAfterstateV2AuditDerivationError,
                       match="prediction manifest"):
        derive_audit_v2(_input(prediction_manifests=tuple(rows)))


def test_detached_checkpoint_population_is_checked_before_derivation():
    rows = list(_input().checkpoint_manifest_sha256s)
    rows[0] = (rows[0][0], rows[1][1])
    with pytest.raises(WorldAfterstateV2AuditDerivationError,
                       match="checkpoint"):
        derive_audit_v2(_input(checkpoint_manifest_sha256s=tuple(rows)))


def test_cohort_labels_are_frozen():
    assert tuple(label for label, _, _ in AUDIT_COHORTS) == COHORT_LABELS
    assert tuple(block for _, _, block in AUDIT_COHORTS) == (1, 1, 1, 1, 2, 2)


def test_complete_derivation_reaches_the_strong_terminal_pass():
    """Witness the actual derivation-to-router wiring, not only its helpers."""
    freeze = _sha("freeze")
    natural_values = tuple(_rows("audit-derivation"))
    control_values = tuple(dataclasses.replace(row, cohort="control")
                           for row in natural_values)
    config = WorldAfterstateV2TrainingConfig(
        learning_rate_ppb=10_000_000, weight_decay_ppb=0,
        gradient_norm_milli=1_000, max_epochs=1, sigma_pair_squared=1.0)
    selection = _selection_population()
    cohort_manifests = []
    for label, control_name, block in AUDIT_COHORTS:
        build = train_named_cohort(
            cohort_name=control_name,
            values=(natural_values if control_name == "natural"
                    else control_values),
            natural_values=(None if control_name == "natural"
                            else natural_values),
            freeze_sha256=freeze, config=config,
            selection_population=selection, seed_block=block,
            wall_budget_nanoseconds=10**15, torch_threads=1)
        cohort_manifests.append((label, build.manifest))

    natural_predictions, outcomes, prior, root = _population(
        root="audit-derivation-evaluation")
    prediction_manifests = []
    for label, control_name, block in AUDIT_COHORTS:
        if control_name == "natural":
            predictions = tuple(dataclasses.replace(
                row, seed_block=block,
                model_state_sha256=_sha(
                    f"natural:block-{block}:member-{row.member_index}"),
                consumer_eligible=block == 1)
                for row in natural_predictions)
        else:
            wrong = _probability(0)
            predictions = tuple(dataclasses.replace(
                row, seed_block=block, control_name=control_name,
                model_state_sha256=_sha(
                    f"{control_name}:block-{block}:member-{row.member_index}"),
                probability_ppb=wrong,
                expected_signed_microlevels=expected_signed_microlevels(wrong),
                consumer_eligible=False)
                for row in natural_predictions)
        prediction_manifests.append((
            label, _manifest((root,), predictions,
                             control_name=control_name, seed_block=block)))

    select_population = _sha("precision-select")
    precision = _evaluation(population=select_population, block=1)
    inputs = AuditDerivationInputV2(
        freeze_sha256=freeze, admission_sha256=_sha("admission"),
        audit_attempt_sha256=_sha("attempt"),
        continuation_manifest_sha256=_sha("continuations"),
        prediction_manifests=tuple(prediction_manifests),
        checkpoint_manifest_sha256s=tuple(
            (label, _sha(f"checkpoint:{label}")) for label in COHORT_LABELS),
        cohort_manifests=tuple(cohort_manifests), p0_report=_p0(),
        optimizer_canary=_canary(), precision_select_result=precision,
        model_selector_power=_power(select_population),
        audit_outcomes=outcomes, prior=prior,
        control_dose_evidence={
            "association": _dose(ASSOCIATION_CONTROL),
            "label": _dose(LABEL_CONTROL),
            "world": _dose(WORLD_CONTROL),
        })
    derived = derive_audit_v2(inputs)
    terminal = derive_terminal_result(derived.evidence)
    assert terminal.decision == \
        PASS_ABSOLUTE_VALUE_AND_ACTION_EDGE_TO_CONSUMER_DESIGN
    assert tuple(derived.evidence.control_dose_evidence) == (
        ASSOCIATION_CONTROL, LABEL_CONTROL, WORLD_CONTROL)
