from __future__ import annotations

import hashlib

import pytest

from shengji.rl.world_afterstate_v2_audit_derivation import (
    AUDIT_COHORTS, AuditDerivationInputV2,
    WorldAfterstateV2AuditDerivationError, derive_audit_v2,
)
from shengji.rl.world_afterstate_v2_label import ContinuationOutcomeV2
from shengji.rl.world_afterstate_v2_terminal_provenance import COHORT_LABELS


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

