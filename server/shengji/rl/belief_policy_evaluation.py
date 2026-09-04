"""One-root three-arm R4-to-production policy evaluation.

This module composes already-reviewed actor/model/sampler/rollout mechanics in
memory.  It publishes nothing and grants no run authority.  Every arm shares
one ballot, world stream and rollout tensor; only its fixed aggregation weights
can differ.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from ..ai.mcbot import MCBot, point_shy_pick_index
from ..ai.registry import make_bot
from .belief_capture import CHAMPION_POLICY
from .belief_policy_population import (
    SelectedPolicyRootV1,
    validate_selected_policy_root,
)
from .belief_policy_protocol import (
    REFERENCE_WORLD_COUNT,
    REPORT_WORLD_COUNT,
    SELECTION_WORLD_COUNT,
    policy_fold_seed,
)
from .belief_policy_search import (
    ArmDecisionV1,
    ArmNominationV1,
    finalize_three_arms,
    nominate_three_arms,
)
from .belief_policy_weighting import (
    TemperedWorldWeightsV1,
    adapt_proposal_ownership_to_v2,
    common_tempered_world_weights,
    world_log_ratio_nanonats,
)
from .belief_policy_worlds import (
    ProductionWorldBatchV1,
    production_proposal_ownership,
    sample_production_worlds,
)
from .belief_reference import SampledOwnershipWorldV1
from .belief_v2_common_surface import build_common_surface_tensors
from .belief_v2_freeze import CONTROL_COHORT_ID, PRIMARY_COHORT_ID
from .belief_v2_human_corpus import UNIVERSAL_POLICY_IDS
from .belief_v2_scoring import (
    V2CohortModelsV1,
    predict_v2_cohort_ownership,
    validate_v2_cohort_models,
)


class BeliefPolicyEvaluationError(ValueError):
    """A selected root, model arm, common world or rollout tensor drifted."""


@dataclass(frozen=True)
class PolicyEvaluationWorkV1:
    reference_worlds: int
    selection_worlds: int
    report_worlds: int
    selection_physical_rollouts: int
    report_physical_rollouts: int
    report_logical_rollouts_per_arm: int
    true_world_rollouts: int
    inference_seconds: float
    inference_cpu_seconds: float
    sampling_seconds: float
    sampling_cpu_seconds: float
    rollout_seconds: float
    rollout_cpu_seconds: float
    total_seconds: float
    total_cpu_seconds: float


@dataclass(frozen=True)
class PolicyRootEvaluationV1:
    root: SelectedPolicyRootV1
    reference_batch: ProductionWorldBatchV1
    selection_batch: ProductionWorldBatchV1
    report_batch: ProductionWorldBatchV1
    primary_selection_weights: TemperedWorldWeightsV1
    control_selection_weights: TemperedWorldWeightsV1
    primary_report_weights: TemperedWorldWeightsV1
    control_report_weights: TemperedWorldWeightsV1
    nominations: tuple[
        ArmNominationV1, ArmNominationV1, ArmNominationV1]
    decisions: tuple[ArmDecisionV1, ArmDecisionV1, ArmDecisionV1]
    selection_values: tuple[tuple[float, ...], ...]
    report_values_by_candidate: tuple[tuple[int, tuple[float, ...]], ...]
    true_world_values: tuple[float, ...]
    true_world_oracle_index: int
    true_world_is_privileged: bool
    work: PolicyEvaluationWorkV1


def _world_assignment(
        root: SelectedPolicyRootV1,
        world: SampledOwnershipWorldV1) \
        -> tuple[dict[int, list[str]], list[str]]:
    hands: dict[int, list[str]] = {}
    buried: list[str] | None = None
    for row in world.receivers:
        cards = list(card for card, count in row.cards for _ in range(count))
        if row.receiver == "hidden-kitty":
            buried = cards
            continue
        prefix = "seat-relative-"
        if not row.receiver.startswith(prefix):
            raise BeliefPolicyEvaluationError(
                "policy world receiver identity drift")
        relative = int(row.receiver.removeprefix(prefix))
        hands[(root.actor_seat + relative) % 4] = cards
    expected_hands = {seat for seat in range(4) if seat != root.actor_seat}
    if set(hands) != expected_hands:
        raise BeliefPolicyEvaluationError(
            "policy world absolute hand population drift")
    if buried is None:
        if root.actor.hidden_burial_size:
            raise BeliefPolicyEvaluationError(
                "policy world hidden burial is absent")
        buried = list(root.round_state.buried)
    return hands, buried


def _score_worlds(
        root: SelectedPolicyRootV1,
        worlds: tuple[SampledOwnershipWorldV1, ...],
        candidate_indices: tuple[int, ...]) \
        -> tuple[tuple[float, ...], ...]:
    if type(candidate_indices) is not tuple or not candidate_indices \
            or len(set(candidate_indices)) != len(candidate_indices) \
            or any(type(index) is not int
                   or not 0 <= index < len(root.candidates)
                   for index in candidate_indices):
        raise BeliefPolicyEvaluationError(
            "policy rollout candidate population drift")
    evaluator = make_bot(CHAMPION_POLICY, seed=0)
    if not isinstance(evaluator, MCBot):
        raise BeliefPolicyEvaluationError(
            "policy rollout evaluator identity drift")
    acting_is_attacker = root.round_state.is_attacker(root.actor_seat)
    rows = []
    for world in worlds:
        hands, buried = _world_assignment(root, world)
        exact_session = evaluator._new_exact_world_session(
            root.round_state, buried)
        values = []
        for index in candidate_indices:
            value = evaluator._score(evaluator._rollout(
                root.round_state,
                root.actor_seat,
                hands,
                buried,
                list(root.candidates[index]),
                exact_session=exact_session,
            ))
            values.append(value if acting_is_attacker else -value)
        rows.append(tuple(values))
    return tuple(rows)


def _true_world_values(root: SelectedPolicyRootV1) -> tuple[float, ...]:
    evaluator = make_bot(CHAMPION_POLICY, seed=0)
    if not isinstance(evaluator, MCBot):
        raise BeliefPolicyEvaluationError(
            "true-world evaluator identity drift")
    hands = {
        seat: list(root.round_state.hands[seat])
        for seat in range(4) if seat != root.actor_seat
    }
    buried = list(root.round_state.buried)
    acting_is_attacker = root.round_state.is_attacker(root.actor_seat)
    exact_session = evaluator._new_exact_world_session(
        root.round_state, buried)
    result = []
    for candidate in root.candidates:
        value = evaluator._score(evaluator._rollout(
            root.round_state,
            root.actor_seat,
            hands,
            buried,
            list(candidate),
            exact_session=exact_session,
        ))
        result.append(value if acting_is_attacker else -value)
    return tuple(result)


def evaluate_policy_root(
        root: SelectedPolicyRootV1, *,
        primary: V2CohortModelsV1,
        control: V2CohortModelsV1,
        privileged_truth: bool = True) -> PolicyRootEvaluationV1:
    """Evaluate one root; capacity may use a sampled surrogate truth fold."""
    started = time.perf_counter()
    cpu_started = time.process_time()
    try:
        validate_selected_policy_root(root)
        validate_v2_cohort_models(primary)
        validate_v2_cohort_models(control)
    except ValueError as exc:
        raise BeliefPolicyEvaluationError(
            "policy evaluation input refused") from exc
    if primary.cohort_id != PRIMARY_COHORT_ID \
            or control.cohort_id != CONTROL_COHORT_ID:
        raise BeliefPolicyEvaluationError(
            "policy evaluation cohort identity drift")

    inference_started = time.perf_counter()
    inference_cpu_started = time.process_time()
    common = build_common_surface_tensors(
        root.actor, behavior_policy_ids=UNIVERSAL_POLICY_IDS)
    _, primary_ensemble = predict_v2_cohort_ownership(
        root.actor, common, primary)
    _, control_ensemble = predict_v2_cohort_ownership(
        root.actor, common, control)
    inference_seconds = time.perf_counter() - inference_started
    inference_cpu_seconds = time.process_time() - inference_cpu_started

    sampling_started = time.perf_counter()
    sampling_cpu_started = time.process_time()
    reference_batch = sample_production_worlds(
        root.round_state, root.actor_seat, root.transcript,
        sampler_seed=policy_fold_seed(
            root.coordinate, decision_index=root.decision_index,
            actor_sha256=root.actor.sha256(), fold="proposal-reference"),
        world_count=REFERENCE_WORLD_COUNT,
    )
    selection_batch = sample_production_worlds(
        root.round_state, root.actor_seat, root.transcript,
        sampler_seed=policy_fold_seed(
            root.coordinate, decision_index=root.decision_index,
            actor_sha256=root.actor.sha256(), fold="selection"),
        world_count=SELECTION_WORLD_COUNT,
    )
    report_batch = sample_production_worlds(
        root.round_state, root.actor_seat, root.transcript,
        sampler_seed=policy_fold_seed(
            root.coordinate, decision_index=root.decision_index,
            actor_sha256=root.actor.sha256(), fold="report"),
        world_count=REPORT_WORLD_COUNT,
    )
    if any(batch.actor.canonical_bytes() != root.actor.canonical_bytes()
           for batch in (reference_batch, selection_batch, report_batch)):
        raise BeliefPolicyEvaluationError(
            "policy evaluation fold actor drift")
    proposal = adapt_proposal_ownership_to_v2(
        root.actor,
        production_proposal_ownership(reference_batch),
        behavior_policy_ids=UNIVERSAL_POLICY_IDS,
    )
    primary_selection_scores = world_log_ratio_nanonats(
        root.actor, primary_ensemble, proposal, selection_batch.worlds)
    control_selection_scores = world_log_ratio_nanonats(
        root.actor, control_ensemble, proposal, selection_batch.worlds)
    primary_selection_weights, control_selection_weights = (
        common_tempered_world_weights(
            primary_selection_scores, control_selection_scores))
    primary_report_scores = world_log_ratio_nanonats(
        root.actor, primary_ensemble, proposal, report_batch.worlds)
    control_report_scores = world_log_ratio_nanonats(
        root.actor, control_ensemble, proposal, report_batch.worlds)
    primary_report_weights, control_report_weights = (
        common_tempered_world_weights(
            primary_report_scores, control_report_scores))
    sampling_seconds = time.perf_counter() - sampling_started
    sampling_cpu_seconds = time.process_time() - sampling_cpu_started

    rollout_started = time.perf_counter()
    rollout_cpu_started = time.process_time()
    selection_values = _score_worlds(
        root, selection_batch.worlds,
        tuple(range(len(root.candidates))))
    nominations = nominate_three_arms(
        root.candidates, selection_values,
        primary_weights=primary_selection_weights,
        control_weights=control_selection_weights,
    )
    report_union = tuple(sorted({
        0, *(row.challenger_index for row in nominations)}))
    report_matrix = _score_worlds(
        root, report_batch.worlds, report_union)
    report_values_by_candidate = tuple(
        (candidate_index, tuple(row[column] for row in report_matrix))
        for column, candidate_index in enumerate(report_union))
    decisions = finalize_three_arms(
        root.candidates, nominations, report_values_by_candidate,
        primary_weights=primary_report_weights,
        control_weights=control_report_weights,
    )
    if type(privileged_truth) is not bool:
        raise BeliefPolicyEvaluationError(
            "policy evaluation truth authority drift")
    true_values = (_true_world_values(root) if privileged_truth else
                   _score_worlds(
                       root, (report_batch.worlds[0],),
                       tuple(range(len(root.candidates))))[0])
    oracle = point_shy_pick_index(
        root.candidates, true_values, range(len(root.candidates)),
        epsilon=MCBot.POINT_SHY_EPS)
    rollout_seconds = time.perf_counter() - rollout_started
    rollout_cpu_seconds = time.process_time() - rollout_cpu_started
    work = PolicyEvaluationWorkV1(
        reference_worlds=REFERENCE_WORLD_COUNT,
        selection_worlds=SELECTION_WORLD_COUNT,
        report_worlds=REPORT_WORLD_COUNT,
        selection_physical_rollouts=(
            SELECTION_WORLD_COUNT * len(root.candidates)),
        report_physical_rollouts=REPORT_WORLD_COUNT * len(report_union),
        report_logical_rollouts_per_arm=2 * REPORT_WORLD_COUNT,
        true_world_rollouts=len(root.candidates),
        inference_seconds=inference_seconds,
        inference_cpu_seconds=inference_cpu_seconds,
        sampling_seconds=sampling_seconds,
        sampling_cpu_seconds=sampling_cpu_seconds,
        rollout_seconds=rollout_seconds,
        rollout_cpu_seconds=rollout_cpu_seconds,
        total_seconds=time.perf_counter() - started,
        total_cpu_seconds=time.process_time() - cpu_started,
    )
    return PolicyRootEvaluationV1(
        root=root,
        reference_batch=reference_batch,
        selection_batch=selection_batch,
        report_batch=report_batch,
        primary_selection_weights=primary_selection_weights,
        control_selection_weights=control_selection_weights,
        primary_report_weights=primary_report_weights,
        control_report_weights=control_report_weights,
        nominations=nominations,
        decisions=decisions,
        selection_values=selection_values,
        report_values_by_candidate=report_values_by_candidate,
        true_world_values=true_values,
        true_world_oracle_index=oracle,
        true_world_is_privileged=privileged_truth,
        work=work,
    )
