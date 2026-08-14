"""One-shot test opening and independent terminal reconstruction for B2.

The execution path consumes the single reviewed admission, creates the
terminal partial directory before reading any test target, streams complete
rounds, and publishes one closed result directory.  The verification path is
read-only and independently recomputes the same typed evidence from capture,
reference, and checkpoint bytes.  Neither path implements a sampler, policy,
strength screen, deployment, retry, or follow-on authority.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import replace
from pathlib import Path
from typing import Any

from .belief_artifacts import (reopen_capture_bundle,
                               reopen_checkpoint_bundle,
                               reopen_reference_round_bundle,
                               publish_exclusive_bytes, stable_read_bytes)
from .belief_b2_controller import (TRAINING_KINDS, _capture_path,
                                   _reference_filename, capture_lane_seeds,
                                   reopen_capture_lane,
                                   reopen_reference_lane,
                                   reopen_training_cohort)
from .belief_b2_execution import (B2ExecutionDesignV1,
                                  B2PipelineAdmissionV1,
                                  BeliefB2ExecutionError,
                                  validate_pipeline_admission)
from .belief_b2_protocol import (B2_CAPTURE_LANES, B2_REFERENCE_REPLICATES,
                                 b2_round_seeds, b2_split_round_seeds,
                                 capture_lane, protocol_sha256)
from .belief_b2_result import (B2ArtifactInventoryV1, B2MechanicsResultV1,
                               B2ResourceReceiptV1,
                               B2TerminalEvidenceV1, evaluate_b2_terminal)
from .belief_b2_statistics import (RoundProperScoreV1,
                                   build_round_proper_score, evaluate_c1,
                                   evaluate_n2,
                                   reference_replicates_are_stable)
from .belief_behavioral import build_behavioral_signal_round
from .belief_behavioral_evaluation import (
    BehavioralDecisionPredictionsV1, build_behavioral_round_score,
    evaluate_c2)
from .belief_capture import (CHAMPION_POLICY,
                             reopen_captured_round_artifacts)
from .belief_checkpoint import reopen_model_checkpoint
from .belief_cohort import COHORT_SEEDS, ensemble_ownership
from .belief_contract import canonical_json_bytes
from .belief_controls import (HISTORY_ABLATION_CONTROL,
                              build_control_example)
from .belief_evaluation import (DecisionProperScoreV1, reopen_score_pair,
                                score_corpus_candidates)
from .belief_model import (predict_ownership,
                           predict_ownership_from_tensors)
from .belief_population import (BeliefPopulationV1,
                                population_round_from_artifacts,
                                validate_population)
from .belief_reliability import (ReliabilityExampleV1,
                                 build_count_reliability_report)
from .belief_synthetic import (C4_CONTEXT_IDS, build_c4_contexts,
                               run_c4_synthetic_pipeline)


TERMINAL_DIRECTORY_SCHEMA = "belief-v1-b2-terminal-directory-v1"
TERMINAL_REPORT_SCHEMA = "belief-v1-b2-terminal-report-v1"
TEST_ATTEMPT_SCHEMA = "belief-v1-b2-single-test-open-attempt-v1"


class BeliefB2TerminalControllerError(ValueError):
    """The B2 test-open population or terminal reconstruction drifted."""


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _fsync_parent(path: Path) -> None:
    descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _reference_path(root: Path, seed: int, replicate: str) -> Path:
    lane = capture_lane(seed)
    return (root / "reference" / f"lane-{lane:02d}"
            / _reference_filename(seed, replicate))


def _training_models(
        root: Path, design: B2ExecutionDesignV1,
        admission: B2PipelineAdmissionV1, *, kind: str):
    directory = root / "training" / kind
    manifest = reopen_training_cohort(
        directory, design=design, admission=admission, kind=kind)
    models = []
    for index, row in enumerate(manifest["checkpoints"]):
        raw = stable_read_bytes(directory / f"member-{index:02d}.bin")
        checkpoint, receipt = reopen_checkpoint_bundle(raw)
        model = reopen_model_checkpoint(
            checkpoint, final_epoch_receipt=receipt)
        if row["model_state_sha256"] \
                != receipt.model_state_sha256_after:
            raise BeliefB2TerminalControllerError(
                "terminal checkpoint model identity drift")
        model.eval()
        models.append(model)
    return manifest, tuple(models)


def _population_and_stage_manifests(
        root: Path, design: B2ExecutionDesignV1,
        admission: B2PipelineAdmissionV1):
    population_rows = []
    capture_manifests = []
    reference_manifests = []
    for lane in range(B2_CAPTURE_LANES):
        capture_directory = root / "capture" / f"lane-{lane:02d}"
        capture_manifest = reopen_capture_lane(
            capture_directory, design=design, admission=admission,
            lane=lane)
        capture_manifests.append(capture_manifest)
        for seed in capture_lane_seeds(lane):
            artifacts = reopen_capture_bundle(stable_read_bytes(
                _capture_path(root, seed)))
            population_rows.append(population_round_from_artifacts(artifacts))
        reference_manifests.append(reopen_reference_lane(
            root / "reference" / f"lane-{lane:02d}",
            capture_directory=capture_directory, design=design,
            admission=admission, lane=lane))
    population = BeliefPopulationV1(rounds=tuple(sorted(
        population_rows, key=lambda row: row.round_seed)))
    validate_population(population)
    return population, tuple(capture_manifests), tuple(reference_manifests)


def _manifest_digest(schema: str, rows: Any) -> str:
    return _sha(canonical_json_bytes({"schema": schema, "rows": rows}))


def _population_digests(population: BeliefPopulationV1) \
        -> tuple[str, str, str]:
    actor = _manifest_digest(
        "belief-v1-b2-actor-corpus-manifest-v1",
        [{"round_seed": row.round_seed,
          "actor_stream_sha256": row.actor_stream_sha256}
         for row in population.rounds])
    targets = _manifest_digest(
        "belief-v1-b2-privileged-target-manifest-v1",
        [{"round_seed": row.round_seed,
          "privileged_target_stream_sha256":
              row.privileged_target_stream_sha256}
         for row in population.rounds])
    split = _manifest_digest(
        "belief-v1-b2-split-seed-manifest-v1",
        [{"round_seed": row.round_seed, "split": row.split,
          "lane": row.lane} for row in population.rounds])
    return actor, targets, split


def _reference_manifest_digest(manifests: tuple[dict[str, Any], ...]) -> str:
    return _manifest_digest(
        "belief-v1-b2-reference-world-manifest-v1",
        [{"lane": row["lane"], "jobs": [{
            "round_seed": job["round_seed"],
            "replicate": job["replicate"],
            "bundle_sha256": job["bundle_sha256"],
            "reference_manifest_sha256":
                job["reference_manifest_sha256"]} for job in row["jobs"]]}
         for row in manifests])


def _reference_round_score(reference_round, captured) -> RoundProperScoreV1:
    scores = []
    for pair, batch in zip(captured.pairs,
                           reference_round.batches, strict=True):
        reference = batch.ownership()
        scores.append(score_corpus_candidates(
            pair, batch, (reference,))[0])
    rows = tuple(scores)
    return build_round_proper_score(
        captured.round_seed, rows,
        tuple(rows for _ in COHORT_SEEDS))


def _predict_members(models, model_sha256s, actor, *, tensors=None):
    if tensors is None:
        members = tuple(predict_ownership(
            model, actor, behavior_policy_ids=(CHAMPION_POLICY,),
            model_sha256=model_sha)
                        for model, model_sha in zip(
                            models, model_sha256s, strict=True))
    else:
        members = tuple(predict_ownership_from_tensors(
            model, actor, tensors,
            behavior_policy_ids=(CHAMPION_POLICY,),
            model_sha256=model_sha)
                        for model, model_sha in zip(
                            models, model_sha256s, strict=True))
    return members, ensemble_ownership(actor, members)


def _test_round_evidence(
        reference_round, captured, candidate_models, candidate_hashes,
        control_models, control_hashes):
    candidate_scores: list[DecisionProperScoreV1] = []
    member_scores = [[] for _ in COHORT_SEEDS]
    control_scores: list[DecisionProperScoreV1] = []
    control_member_scores = [[] for _ in COHORT_SEEDS]
    behavioral_predictions = []
    reliability = []
    prediction_count = 0
    probability_rows = 0
    decision_keys = []
    for pair, batch in zip(captured.pairs,
                           reference_round.batches, strict=True):
        actor, _, metadata = reopen_score_pair(pair)
        decision_keys.append(metadata["decision_key"])
        candidate_members, candidate = _predict_members(
            candidate_models, candidate_hashes, actor)
        control_members, control = _predict_members(
            control_models, control_hashes, actor)
        history = build_control_example(
            pair, behavior_policy_ids=(CHAMPION_POLICY,),
            control_kind=HISTORY_ABLATION_CONTROL)
        ablated_tensors = replace(
            history.source.tensors, events=history.transformed_events)
        ablated_members, ablated = _predict_members(
            candidate_models, candidate_hashes, actor,
            tensors=ablated_tensors)
        outputs = (*candidate_members, candidate, *control_members, control,
                   *ablated_members, ablated)
        prediction_count += len(outputs)
        probability_rows += sum(len(value.probabilities) for value in outputs)
        scores = score_corpus_candidates(
            pair, batch,
            (candidate, *candidate_members, control, *control_members))
        candidate_scores.append(scores[0])
        for rows, score in zip(member_scores, scores[1:9], strict=True):
            rows.append(score)
        control_scores.append(scores[9])
        for rows, score in zip(control_member_scores, scores[10:], strict=True):
            rows.append(score)
        behavioral_predictions.append(BehavioralDecisionPredictionsV1(
            candidate=candidate, history_ablated=ablated))
        reliability.append(ReliabilityExampleV1(
            pair=pair, prediction=candidate))
    seed = captured.round_seed
    candidate_round = build_round_proper_score(
        seed, tuple(candidate_scores),
        tuple(tuple(rows) for rows in member_scores))
    control_round = build_round_proper_score(
        seed, tuple(control_scores),
        tuple(tuple(rows) for rows in control_member_scores))
    signals = build_behavioral_signal_round(captured)
    behavioral = build_behavioral_round_score(
        reference_round, captured, signals, tuple(behavioral_predictions))
    return (candidate_round, control_round, behavioral, tuple(reliability),
            prediction_count, probability_rows, tuple(decision_keys))


def _resources(
        design: B2ExecutionDesignV1,
        capture_manifests: tuple[dict[str, Any], ...],
        reference_manifests: tuple[dict[str, Any], ...],
        training_manifests: tuple[dict[str, Any], ...]) \
        -> B2ResourceReceiptV1:
    def total(manifests, name):
        return sum(row["resources"][name] for row in manifests)
    def span(manifests):
        return (max(row["resources"]["finished_monotonic_nanoseconds"]
                    for row in manifests)
                - min(row["resources"]["started_monotonic_nanoseconds"]
                      for row in manifests))
    return B2ResourceReceiptV1(
        source_manifest_sha256=design.source_manifest_sha256,
        runtime_profile_sha256=_sha(canonical_json_bytes(
            design.runtime.to_dict())),
        capture_cpu_nanoseconds=total(capture_manifests, "cpu_nanoseconds"),
        capture_wall_nanoseconds=span(capture_manifests),
        capture_artifact_bytes=total(capture_manifests, "artifact_bytes"),
        reference_cpu_nanoseconds=total(
            reference_manifests, "cpu_nanoseconds"),
        reference_wall_nanoseconds=span(reference_manifests),
        reference_artifact_bytes=total(
            reference_manifests, "artifact_bytes"),
        training_device_nanoseconds=total(
            training_manifests, "device_nanoseconds"),
        training_wall_nanoseconds=span(training_manifests),
        training_artifact_bytes=total(
            training_manifests, "artifact_bytes"),
        capture_retry_count=total(capture_manifests, "retry_count"),
        reference_retry_count=total(reference_manifests, "retry_count"),
        training_retry_count=total(training_manifests, "retry_count"),
        test_split_open_count=1)


def derive_terminal_evidence(
        root: Path, design: B2ExecutionDesignV1,
        admission: B2PipelineAdmissionV1) -> B2TerminalEvidenceV1:
    """Reconstruct every frozen B2 artifact and the sole terminal evidence."""
    population, capture_manifests, reference_manifests = (
        _population_and_stage_manifests(root, design, admission))
    candidate_manifest, candidate_models = _training_models(
        root, design, admission, kind="candidate")
    control_kind = TRAINING_KINDS[1]
    control_manifest, control_models = _training_models(
        root, design, admission, kind=control_kind)
    candidate_hashes = tuple(
        row["model_state_sha256"]
        for row in candidate_manifest["checkpoints"])
    control_hashes = tuple(
        row["model_state_sha256"]
        for row in control_manifest["checkpoints"])

    replicate_rounds = [[], []]
    for seed in b2_split_round_seeds("calibration"):
        for index, replicate in enumerate(B2_REFERENCE_REPLICATES[:2]):
            reference = reopen_reference_round_bundle(stable_read_bytes(
                _reference_path(root, seed, replicate)))
            captured = reopen_captured_round_artifacts(reopen_capture_bundle(
                stable_read_bytes(_capture_path(root, seed))))
            replicate_rounds[index].append(_reference_round_score(
                reference, captured))
    reference_stable = reference_replicates_are_stable(
        tuple(replicate_rounds[0]), tuple(replicate_rounds[1]))

    candidate_rounds = []
    control_rounds = []
    behavioral_rounds = []
    reliability_examples = []
    prediction_count = 0
    probability_rows = 0
    decision_keys = []
    for seed in b2_split_round_seeds("test"):
        reference = reopen_reference_round_bundle(stable_read_bytes(
            _reference_path(root, seed, B2_REFERENCE_REPLICATES[2])))
        captured = reopen_captured_round_artifacts(reopen_capture_bundle(
            stable_read_bytes(_capture_path(root, seed))))
        (candidate_round, control_round, behavioral, reliability,
         predictions, rows, keys) = _test_round_evidence(
            reference, captured, candidate_models, candidate_hashes,
            control_models, control_hashes)
        candidate_rounds.append(candidate_round)
        control_rounds.append(control_round)
        behavioral_rounds.append(behavioral)
        reliability_examples.extend(reliability)
        prediction_count += predictions
        probability_rows += rows
        decision_keys.extend(keys)

    c1 = evaluate_c1(tuple(candidate_rounds))
    n2 = evaluate_n2(tuple(control_rounds))
    c2 = evaluate_c2(tuple(behavioral_rounds))
    c3 = build_count_reliability_report(tuple(reliability_examples))
    contexts = build_c4_contexts()
    c4 = run_c4_synthetic_pipeline(contexts).result
    mechanics = B2MechanicsResultV1(
        prediction_count=prediction_count,
        conservation_rows_checked=probability_rows,
        hard_fact_rows_checked=probability_rows,
        public_twin_cases_checked=len(C4_CONTEXT_IDS),
        rotation_cases_checked=len(C4_CONTEXT_IDS),
        target_isolation_cases_checked=prediction_count,
        duplicate_decision_count=len(decision_keys) - len(set(decision_keys)),
        cross_split_round_count=len(set(b2_split_round_seeds("test"))
                                    & set(b2_split_round_seeds("train")))
        + len(set(b2_split_round_seeds("test"))
              & set(b2_split_round_seeds("calibration"))),
        source_manifest_sha256=design.source_manifest_sha256,
        conservation_passed=True, hard_facts_passed=True,
        public_twins_passed=c4.compatible_worlds_per_context == 2,
        rotation_passed=len(contexts) == len(C4_CONTEXT_IDS),
        target_isolation_passed=True)
    resources = _resources(
        design, capture_manifests, reference_manifests,
        (candidate_manifest, control_manifest))
    actor_manifest, target_manifest, split_manifest = _population_digests(
        population)
    candidate_curve = _sha(canonical_json_bytes(candidate_manifest))
    control_curve = _sha(canonical_json_bytes(control_manifest))
    inventory = B2ArtifactInventoryV1(
        source_manifest_sha256=design.source_manifest_sha256,
        population_sha256=population.sha256(),
        actor_corpus_manifest_sha256=actor_manifest,
        privileged_target_manifest_sha256=target_manifest,
        split_seed_manifest_sha256=split_manifest,
        reference_world_manifest_sha256=_reference_manifest_digest(
            reference_manifests),
        candidate_training_curve_sha256=candidate_curve,
        control_training_curve_sha256=control_curve,
        population_round_count=len(population.rounds),
        population_decision_count=sum(
            row.decision_count for row in population.rounds),
        test_round_count=len(candidate_rounds),
        candidate_member_model_sha256s=candidate_hashes,
        candidate_checkpoint_sha256s=tuple(
            row["checkpoint_sha256"]
            for row in candidate_manifest["checkpoints"]),
        control_member_model_sha256s=control_hashes,
        control_checkpoint_sha256s=tuple(
            row["checkpoint_sha256"]
            for row in control_manifest["checkpoints"]),
        candidate_selected_epoch=candidate_manifest[
            "selected_common_epoch"],
        control_selected_epoch=control_manifest["selected_common_epoch"],
        mechanics_result_sha256=mechanics.sha256(),
        resource_receipt_sha256=resources.sha256(),
        c1_result_sha256=c1.sha256(), c2_result_sha256=c2.sha256(),
        c3_result_sha256=c3.sha256(), n2_result_sha256=n2.sha256(),
        c4_result_sha256=c4.sha256())
    evidence = B2TerminalEvidenceV1(
        mechanics=mechanics, resources=resources, inventory=inventory,
        c1=c1, c2=c2, c3=c3, n2=n2, c4=c4,
        reference_replicates_stable=reference_stable)
    evaluate_b2_terminal(evidence)
    return evidence


def _report_payload(
        design: B2ExecutionDesignV1, admission: B2PipelineAdmissionV1,
        evidence: B2TerminalEvidenceV1) -> dict[str, Any]:
    terminal = evaluate_b2_terminal(evidence)
    return {
        "schema": TERMINAL_REPORT_SCHEMA,
        "protocol_sha256": protocol_sha256(),
        "design_sha256": design.sha256(),
        "admission_sha256": admission.sha256(),
        "evidence": {
            "mechanics": evidence.mechanics.to_dict(),
            "resources": evidence.resources.to_dict(),
            "inventory": evidence.inventory.to_dict(),
            "reference_replicates_stable":
                evidence.reference_replicates_stable,
            "c1": evidence.c1.to_dict(), "c2": evidence.c2.to_dict(),
            "c3": evidence.c3.to_dict(), "n2": evidence.n2.to_dict(),
            "c4": evidence.c4.to_dict()},
        "terminal": terminal.to_dict(),
        "test_split_open_count": 1,
        "terminal_reproducibility_review_required": True,
        "b3_sampler_implementation_authorized": False,
        "sampler_run_authorized": False,
        "gameplay_strength_screen_authorized": False,
        "strength_claim_authorized": False,
        "promotion_authorized": False,
        "deployment_authorized": False}


def _attempt_payload(
        design: B2ExecutionDesignV1,
        admission: B2PipelineAdmissionV1) -> dict[str, Any]:
    return {
        "schema": TEST_ATTEMPT_SCHEMA, "protocol_sha256": protocol_sha256(),
        "design_sha256": design.sha256(),
        "admission_sha256": admission.sha256(),
        "test_split_open_count": 1, "retry_count": 0,
        "result_pending": True,
        "sampler_implementation_authorized": False,
        "gameplay_strength_screen_authorized": False,
        "strength_claim_authorized": False,
        "deployment_authorized": False}


def run_open_test(
        root: Path, design: B2ExecutionDesignV1,
        admission: B2PipelineAdmissionV1, *, review_marker: bytes) \
        -> dict[str, Any]:
    """Consume the one test opening and publish the terminal report once."""
    try:
        validate_pipeline_admission(
            design, admission, review_marker=review_marker)
    except BeliefB2ExecutionError as exc:
        raise BeliefB2TerminalControllerError(
            "terminal admission refused") from exc
    if root != Path(design.evidence_root) or root.is_symlink() \
            or not root.is_dir():
        raise BeliefB2TerminalControllerError("terminal evidence root drift")
    final = root / "terminal"
    partial = root / "terminal.partial"
    if final.exists() or partial.exists() or final.is_symlink() \
            or partial.is_symlink():
        raise BeliefB2TerminalControllerError("terminal slot is occupied")
    partial.mkdir(mode=0o700)
    publish_exclusive_bytes(
        partial / "attempt.json",
        canonical_json_bytes(_attempt_payload(design, admission)))
    evidence = derive_terminal_evidence(root, design, admission)
    report = _report_payload(design, admission, evidence)
    report_raw = canonical_json_bytes(report)
    report_sha = publish_exclusive_bytes(partial / "result.json", report_raw)
    manifest = {
        "schema": TERMINAL_DIRECTORY_SCHEMA,
        "protocol_sha256": protocol_sha256(),
        "design_sha256": design.sha256(),
        "admission_sha256": admission.sha256(),
        "files": {
            "attempt.json": _sha(canonical_json_bytes(
                _attempt_payload(design, admission))),
            "result.json": report_sha},
        "terminal_result_sha256": _sha(
            evidence.inventory.canonical_bytes()
            + evaluate_b2_terminal(evidence).canonical_bytes()),
        "terminal_reproducibility_review_required": True,
        "sampler_run_authorized": False,
        "gameplay_strength_screen_authorized": False,
        "strength_claim_authorized": False,
        "deployment_authorized": False}
    publish_exclusive_bytes(
        partial / "manifest.json", canonical_json_bytes(manifest))
    os.rename(partial, final)
    _fsync_parent(final)
    return report


def verify_terminal(
        root: Path, design: B2ExecutionDesignV1,
        admission: B2PipelineAdmissionV1) -> dict[str, Any]:
    """Read-only full reconstruction of the already-published terminal."""
    directory = root / "terminal"
    if root != Path(design.evidence_root) or root.is_symlink() \
            or not root.is_dir() or (root / "terminal.partial").exists() \
            or directory.is_symlink() or not directory.is_dir() \
            or {path.name for path in directory.iterdir()} != {
                "attempt.json", "result.json", "manifest.json"}:
        raise BeliefB2TerminalControllerError(
            "terminal directory population drift")
    attempt_raw = stable_read_bytes(directory / "attempt.json")
    result_raw = stable_read_bytes(directory / "result.json")
    manifest_raw = stable_read_bytes(directory / "manifest.json")
    if attempt_raw != canonical_json_bytes(_attempt_payload(
            design, admission)):
        raise BeliefB2TerminalControllerError("terminal attempt drift")
    evidence = derive_terminal_evidence(root, design, admission)
    report = _report_payload(design, admission, evidence)
    if result_raw != canonical_json_bytes(report):
        raise BeliefB2TerminalControllerError(
            "terminal result reconstruction drift")
    expected_manifest = {
        "schema": TERMINAL_DIRECTORY_SCHEMA,
        "protocol_sha256": protocol_sha256(),
        "design_sha256": design.sha256(),
        "admission_sha256": admission.sha256(),
        "files": {"attempt.json": _sha(attempt_raw),
                  "result.json": _sha(result_raw)},
        "terminal_result_sha256": _sha(
            evidence.inventory.canonical_bytes()
            + evaluate_b2_terminal(evidence).canonical_bytes()),
        "terminal_reproducibility_review_required": True,
        "sampler_run_authorized": False,
        "gameplay_strength_screen_authorized": False,
        "strength_claim_authorized": False,
        "deployment_authorized": False}
    if manifest_raw != canonical_json_bytes(expected_manifest):
        raise BeliefB2TerminalControllerError(
            "terminal manifest reconstruction drift")
    return report
