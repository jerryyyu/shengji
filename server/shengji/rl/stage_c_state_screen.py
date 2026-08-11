"""Fresh state-level screen for protected mid/late Stage-C proposals.

This module tests the policy we would actually compose, not the model's raw
argmax.  Treatment, matched-random and the literal live champion each make a
decision from an independently replayed copy of the same public state and the
same policy seed.  Their final actions are then scored on a separate common-
world evaluation fold.  The model never directly plays an action.

The screen is intentionally smaller than a whole-game duel.  A passing result
authorizes only design/review of a fresh whole-game screen; it cannot confirm,
promote or deploy a policy.  Population capture, artifact identity, admission
and execution authority belong to a separately frozen controller.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import statistics
from collections import Counter
from typing import Callable, Mapping, Sequence

SCHEMA = "teacher-stage-c-midlate-protected-state-screen-v1"
SELECTION_SCHEMA = \
    "teacher-stage-c-midlate-protected-selection-v1"
AGGREGATE_SCHEMA = \
    "teacher-stage-c-midlate-protected-state-screen-aggregate-v1"
EVALUATION_FOLD_SCHEMA = \
    "teacher-stage-c-midlate-protected-evaluation-fold-v1"
LABEL_SAMPLER_SCHEMA = "teacher-stage-c-label-sampler-v2"
LABEL_WORK_SCHEMA = "teacher-stage-c-label-work-v2"
TARGET_STATES = 256
TARGET_PER_CELL = 64
MIN_COMPLETED_TRICKS = 5
DECISION_REPORT_WORLDS = 300
EVALUATION_WORLDS = 300
SAMPLE_ATTEMPT_FACTOR = 40
ONE_SIDED_CRITICAL = 1.70
TWO_SIDED_CRITICAL = 1.97
PHASES = ("mid", "late")
ROLES = ("attacker", "defender")
CELL_KEYS = tuple(f"{phase}:{role}" for phase in PHASES for role in ROLES)


class StageCStateScreenError(RuntimeError):
    """A replay, decision, work record, population or contrast drifted."""


class StageCStateIneligible(StageCStateScreenError):
    """A valid candidate state is outside the frozen protected trigger."""


Replay = Callable[[Mapping[str, object]], object]
PolicyFactory = Callable[[int], object]
EvaluationFold = Callable[
    [object, int, Sequence[Sequence[str]], int], Mapping[str, object]]


def _canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"))
            + "\n").encode()


def _seed(state: Mapping[str, object], purpose: str) -> int:
    payload = {
        "schema": "teacher-stage-c-midlate-screen-stream-v1",
        "state_id": state.get("state_id"),
        "deal_seed": state.get("seed"),
        "purpose": purpose,
    }
    return int.from_bytes(hashlib.sha256(_canonical_json(payload)).digest()[:16],
                          "big")


def _self_hash(value: Mapping[str, object], field: str) -> str:
    return hashlib.sha256(_canonical_json({
        key: item for key, item in value.items() if key != field
    })).hexdigest()


def _action_key(cards: Sequence[object]) -> tuple[str, ...]:
    if (not isinstance(cards, (list, tuple)) or not cards
            or any(not isinstance(card, str) or not card for card in cards)):
        raise StageCStateScreenError("screen action geometry drift")
    return tuple(sorted(cards))


def _state_identity(
    state: Mapping[str, object],
) -> tuple[str, int, int, str, str, str]:
    state_id = state.get("state_id")
    seed = state.get("seed")
    seat = state.get("seat")
    phase = state.get("phase")
    role = state.get("role")
    position = state.get("surface")
    trick = state.get("trick")
    expected_phase = ("mid" if isinstance(trick, int) and not isinstance(
        trick, bool) and MIN_COMPLETED_TRICKS <= trick < 12 else "late")
    if (not isinstance(state_id, str) or not state_id
            or isinstance(seed, bool) or not isinstance(seed, int)
            or isinstance(seat, bool) or not isinstance(seat, int)
            or not 0 <= seat < 4
            or phase not in PHASES or role not in ROLES
            or position not in {"lead", "follow"}
            or isinstance(trick, bool) or not isinstance(trick, int)
            or trick < MIN_COMPLETED_TRICKS
            or phase != expected_phase
            or state.get("surface_type") != "play"):
        raise StageCStateScreenError("mid/late screen state identity drift")
    return state_id, seed, seat, str(phase), str(role), str(position)


def _replay(state: Mapping[str, object], replay: Replay):
    rnd = replay(state)
    _, _, seat, _, _, position = _state_identity(state)
    history = getattr(rnd, "history", None)
    trick = getattr(rnd, "trick", None)
    plays = getattr(trick, "plays", None)
    observed_position = (
        "lead" if isinstance(plays, list) and not plays else "follow")
    if (getattr(rnd, "phase", None) != "play"
            or getattr(rnd, "turn", None) != seat
            or not isinstance(history, list)
            or len(history) != state["trick"]
            or not isinstance(plays, list)
            or observed_position != position):
        raise StageCStateScreenError("screen replay boundary drift")
    role = "attacker" if rnd.is_attacker(seat) else "defender"
    if role != state["role"]:
        raise StageCStateScreenError("screen replay role drift")
    return rnd


def _scope_identity(scope: Mapping[str, object]) -> dict:
    return {key: copy.deepcopy(value) for key, value in scope.items()
            if key != "elapsed_seconds"}


def _sampler_is_exact(
    counters: object, accepted: int, *, require_no_failures: bool = False,
) -> bool:
    if not isinstance(counters, Mapping):
        return False
    values = {name: counters.get(name) for name in (
        "sample_attempts", "accepted_worlds", "failed_worlds",
        "rejected_worlds", "impossible_worlds")}
    if any(isinstance(value, bool) or not isinstance(value, int)
           or value < 0 for value in values.values()):
        return False
    return bool(
        values["accepted_worlds"] == accepted
        and values["sample_attempts"]
        == values["accepted_worlds"] + values["failed_worlds"]
        and values["rejected_worlds"] <= values["failed_worlds"]
        and values["impossible_worlds"] <= values["failed_worlds"]
        and values["sample_attempts"]
        <= accepted * SAMPLE_ATTEMPT_FACTOR
        and (not require_no_failures or not any((
            values["failed_worlds"], values["rejected_worlds"],
            values["impossible_worlds"]))))


def _live_decision_identity(record: object) -> object:
    """Remove arm/timing-only fields from one literal champion decision."""
    if record is None:
        return None
    if not isinstance(record, Mapping):
        raise StageCStateScreenError("literal live decision record drift")
    value = copy.deepcopy(dict(record))
    for field in ("policy", "policy_class", "search_secs"):
        value.pop(field, None)
    candidates = value.get("candidates")
    played_index = value.get("played_index")
    if (value.get("schema") != "mc-decision-v2"
            or not isinstance(candidates, list) or not candidates
            or isinstance(played_index, bool)
            or not isinstance(played_index, int)
            or not 0 <= played_index < len(candidates)
            or _action_key(value.get("played", []))
            != _action_key(candidates[played_index])):
        raise StageCStateScreenError("literal live decision identity drift")
    return value


def _validate_focused_record(record: object, *, arm: str,
                             played: Sequence[str]) -> dict:
    if not isinstance(record, dict):
        raise StageCStateScreenError("screen state did not trigger Stage C")
    scope = record.get("scope_diagnostic")
    work = record.get("work")
    report = record.get("report_fold")
    counters = record.get("sampler_counters", {}).get("delta")
    candidate_count = record.get("candidate_count")
    scope_counters = scope.get("sampler_counters") \
        if isinstance(scope, dict) else None
    report_attempts = report.get("attempts") \
        if isinstance(report, dict) else None
    report_rejected = report.get("rejected") \
        if isinstance(report, dict) else None
    shared_candidate_fields = (
        "candidate_keys", "matched_random_index", "incumbent_index",
        "model_selected_index", "treatment_indices", "null_indices",
        "treatment_candidates", "null_candidates",
        "searched_arms_treatment", "searched_arms_null", "selection",
        "head", "epoch", "state_key",
    )
    if (record.get("surface") != "play" or record.get("arm") != arm
            or record.get("fallback_to_live_ballot") is not False
            or record.get("model_triggered") is not True
            or record.get("fresh_paired_report_lcb_required") is not True
            or record.get("model_direct_override_authorized") is not False
            or _action_key(record.get("played", [])) != _action_key(played)
            or not isinstance(candidate_count, int)
            or not 2 <= candidate_count <= 20
            or any(field not in record for field in shared_candidate_fields)
            or not isinstance(record.get("candidate_keys"), list)
            or len(record["candidate_keys"]) != candidate_count
            or not isinstance(scope, dict)
            or scope.get("eligible") is not True
            or scope.get("evaluation_complete") is not True
            or scope.get("worlds") != 30
            or scope.get("attempts") != 30
            or scope.get("candidate_worlds") != 30 * candidate_count
            or not _sampler_is_exact(
                scope_counters, 30, require_no_failures=True)
            or not isinstance(work, dict)
            or work.get("report_budget") != 2 * DECISION_REPORT_WORLDS
            or work.get("report_rollouts") != 2 * DECISION_REPORT_WORLDS
            or work.get("complete") is not True
            or not isinstance(report, dict)
            or report.get("worlds") != DECISION_REPORT_WORLDS
            or report.get("complete") is not True
            or isinstance(report_attempts, bool)
            or not isinstance(report_attempts, int)
            or not DECISION_REPORT_WORLDS <= report_attempts \
                <= DECISION_REPORT_WORLDS * SAMPLE_ATTEMPT_FACTOR
            or report_rejected != report_attempts - DECISION_REPORT_WORLDS
            or not _sampler_is_exact(counters, DECISION_REPORT_WORLDS)
            or counters.get("sample_attempts") != report_attempts
            or counters.get("failed_worlds") != report_rejected):
        raise StageCStateScreenError("protected decision/work contract drift")
    try:
        candidate_keys = [
            _action_key(value) for value in record["candidate_keys"]]
        incumbent_index = int(record["incumbent_index"])
        model_index = int(record["model_selected_index"])
        null_index = int(record["matched_random_index"])
    except (KeyError, TypeError, ValueError) as exc:
        raise StageCStateScreenError(
            "protected candidate identity drift") from exc
    selection = record["selection"]
    treatment_indices = record["treatment_indices"]
    null_indices = record["null_indices"]
    challenger_index = record.get("challenger_candidate_union_index")
    expected_challenger = model_index if arm == "treatment" else null_index
    if (len(set(candidate_keys)) != candidate_count
            or any(list(key) != value for key, value in zip(
                candidate_keys, record["candidate_keys"], strict=True))
            or not 0 <= incumbent_index < candidate_count
            or not 0 <= model_index < candidate_count
            or not 0 <= null_index < candidate_count
            or model_index == incumbent_index
            or null_index == incumbent_index
            or treatment_indices != [incumbent_index, model_index]
            or null_indices != [incumbent_index, null_index]
            or record["searched_arms_treatment"] != 2
            or record["searched_arms_null"] != 2
            or [_action_key(value) for value in record["treatment_candidates"]]
            != [candidate_keys[index] for index in treatment_indices]
            or [_action_key(value) for value in record["null_candidates"]]
            != [candidate_keys[index] for index in null_indices]
            or challenger_index != expected_challenger
            or _action_key(record.get("live_incumbent", []))
            != candidate_keys[incumbent_index]
            or not isinstance(selection, Mapping)
            or selection.get("surface") != "play"
            or selection.get("head") != record["head"]
            or selection.get("epoch") != record["epoch"]
            or selection.get("candidate_count") != candidate_count
            or selection.get("selected_index") != model_index):
        raise StageCStateScreenError("protected candidate identity drift")
    reason = record.get("reason")
    if reason == "stage_c_report_lcb_override":
        expected_play = candidate_keys[expected_challenger]
    elif reason == "stage_c_report_lcb_below_min_gain":
        expected_play = candidate_keys[incumbent_index]
    else:
        raise StageCStateScreenError("protected final reason drift")
    if _action_key(played) != expected_play:
        raise StageCStateScreenError("protected final action drift")
    _live_decision_identity(record.get("live_policy_decision"))
    return copy.deepcopy(record)


def _focused_record(bot, *, arm: str, played: Sequence[str]) -> dict:
    if getattr(bot, "stage_c_min_completed_tricks", None) \
            != MIN_COMPLETED_TRICKS:
        raise StageCStateScreenError("protected phase threshold drift")
    record = getattr(bot, "last_stage_c_focus_record", None)
    if not isinstance(record, dict):
        raise StageCStateIneligible("no protected candidate union")
    if record.get("fallback_to_live_ballot") is True:
        raise StageCStateScreenError("protected decision used a fallback")
    if record.get("model_triggered") is not True:
        reason = record.get("reason")
        if reason not in {
            "outside_champion_uncertainty_scope",
            "model_kept_live_incumbent",
        }:
            raise StageCStateScreenError(
                "protected non-trigger reason drift")
        raise StageCStateIneligible(str(reason))
    return _validate_focused_record(record, arm=arm, played=played)


def _round_value(attacker_points: int) -> float:
    if attacker_points >= 80:
        return min(3, (attacker_points - 80) // 40) + 0.5
    if attacker_points == 0:
        return -3.5
    return -(1 + (79 - attacker_points) // 40) - 0.5


def _logical_fold(
    fold: Mapping[str, object], actions: Sequence[Sequence[str]],
    evaluation_seed: int, *, attacker: bool,
) -> list[list[float]]:
    rows = fold.get("actions")
    sampler = fold.get("sampler")
    work = fold.get("work")
    hashes = sampler.get("world_key_sha256s") \
        if isinstance(sampler, Mapping) else None
    counters = sampler.get("counters") \
        if isinstance(sampler, Mapping) else None
    expected_fold_work = {
        "selection": 0,
        "report": 3 * EVALUATION_WORLDS,
        "audit_selection": 0,
        "audit_report": 0,
    }
    if (fold.get("schema") != EVALUATION_FOLD_SCHEMA
            or fold.get("seed") != evaluation_seed
            or fold.get("worlds") != EVALUATION_WORLDS
            or fold.get("candidate_worlds") != 3 * EVALUATION_WORLDS
            or fold.get("complete") is not True
            or not isinstance(rows, list) or len(rows) != 3
            or not isinstance(sampler, dict)
            or sampler.get("schema") != LABEL_SAMPLER_SCHEMA
            or sampler.get("fold") != "report"
            or sampler.get("seed") != evaluation_seed
            or sampler.get("requested") != EVALUATION_WORLDS
            or sampler.get("accepted") != EVALUATION_WORLDS
            or sampler.get("accepted_draws") != EVALUATION_WORLDS
            or sampler.get("attempts")
            != (counters.get("sample_attempts")
                if isinstance(counters, Mapping) else None)
            or sampler.get("attempt_cap")
            != EVALUATION_WORLDS * SAMPLE_ATTEMPT_FACTOR
            or not isinstance(hashes, list)
            or len(hashes) != EVALUATION_WORLDS
            or any(not isinstance(value, str) or len(value) != 64
                   or any(char not in "0123456789abcdef" for char in value)
                   for value in hashes)
            or sampler.get("world_keys_sha256")
            != hashlib.sha256(_canonical_json(hashes)).hexdigest()
            or sampler.get("unique_worlds") != len(set(hashes))
            or sampler.get("duplicate_draws_retained")
            != EVALUATION_WORLDS - len(set(hashes))
            or sampler.get("prior_fold_overlap_draws_retained") != 0
            or sampler.get("sampling_with_replacement") is not True
            or sampler.get("domain_separated_stream") is not True
            or sampler.get("complete") is not True
            or not _sampler_is_exact(counters, EVALUATION_WORLDS)
            or not isinstance(work, dict)
            or work.get("schema") != LABEL_WORK_SCHEMA
            or work.get("candidate_worlds_attempted") != expected_fold_work
            or work.get("candidate_worlds_completed") != expected_fold_work
            or work.get("total_candidate_worlds_attempted")
            != 3 * EVALUATION_WORLDS
            or work.get("total_candidate_worlds_completed")
            != 3 * EVALUATION_WORLDS
            or work.get("samplers") != {"report": sampler}
            or work.get("sampler_sequence") != ["report"]
            or work.get("accounting_complete") is not True):
        raise StageCStateScreenError("independent evaluation-fold drift")
    result = []
    expected_sources = (
        ["treatment_final"], ["matched_null_final"],
        ["literal_live_final"],
    )
    for index, (row, expected) in enumerate(zip(rows, actions, strict=True)):
        values = row.get("signed_level_utility") \
            if isinstance(row, dict) else None
        raw = row.get("raw_attacker_points") \
            if isinstance(row, dict) else None
        if (not isinstance(row, dict) or row.get("logical_index") != index
                or row.get("candidate_index") != index
                or _action_key(row.get("cards", [])) != _action_key(expected)
                or row.get("sources") != expected_sources[index]
                or not isinstance(raw, list)
                or len(raw) != EVALUATION_WORLDS
                or any(isinstance(value, bool)
                       or not isinstance(value, (int, float))
                       or not math.isfinite(float(value))
                       or float(value) < 0 or not float(value).is_integer()
                       for value in raw)
                or not isinstance(values, list)
                or len(values) != EVALUATION_WORLDS
                or any(isinstance(value, bool)
                       or not isinstance(value, (int, float))
                       or not math.isfinite(float(value)) for value in values)):
            raise StageCStateScreenError(
                "independent evaluation action tensor drift")
        expected_values = [
            _round_value(int(value)) * (1.0 if attacker else -1.0)
            for value in raw
        ]
        mean_value = row.get("mean_signed_level_utility")
        if ([float(value) for value in values] != expected_values
                or isinstance(mean_value, bool)
                or not isinstance(mean_value, (int, float))
                or not math.isfinite(float(mean_value))
                or not math.isclose(
                    float(mean_value),
                    statistics.fmean(expected_values),
                    rel_tol=1e-12, abs_tol=1e-12)):
            raise StageCStateScreenError(
                "independent evaluation utility transform drift")
        result.append(expected_values)
    return result


def _mean_difference(left: Sequence[float], right: Sequence[float]) -> float:
    if len(left) != len(right) or not left:
        raise StageCStateScreenError("paired evaluation geometry drift")
    return statistics.fmean(
        left_value - right_value
        for left_value, right_value in zip(left, right, strict=True))


def select_state(
    state: Mapping[str, object], *, replay: Replay,
    treatment_factory: PolicyFactory, matched_null_factory: PolicyFactory,
    champion_factory: PolicyFactory,
) -> dict:
    """Open only decision folds and freeze one valid protected trigger."""
    state_id, deal_seed, seat, phase, role, position = _state_identity(state)
    policy_seed = _seed(state, "decision")

    treatment_bot = treatment_factory(policy_seed)
    treatment_play = list(treatment_bot.decide_play(
        _replay(state, replay), seat))
    treatment_record = _focused_record(
        treatment_bot, arm="treatment", played=treatment_play)

    null_bot = matched_null_factory(policy_seed)
    null_play = list(null_bot.decide_play(_replay(state, replay), seat))
    null_record = _focused_record(
        null_bot, arm="matched-null", played=null_play)

    champion_bot = champion_factory(policy_seed)
    champion_play = list(champion_bot.decide_play(
        _replay(state, replay), seat))
    champion_record = copy.deepcopy(
        getattr(champion_bot, "last_decision_record", None))

    treatment_live = _action_key(treatment_record["live_incumbent"])
    null_live = _action_key(null_record["live_incumbent"])
    champion_key = _action_key(champion_play)
    shared_fields = (
        "candidate_count", "candidate_source", "candidate_keys", "head",
        "epoch", "state_key", "model_selected_index",
        "matched_random_index", "incumbent_index", "treatment_indices",
        "null_indices", "treatment_candidates", "null_candidates",
        "searched_arms_treatment", "searched_arms_null", "selection",
        "report_seed",
    )
    if (treatment_live != champion_key or null_live != champion_key
            or any(treatment_record.get(field) != null_record.get(field)
                   for field in shared_fields)
            or _scope_identity(treatment_record["scope_diagnostic"])
            != _scope_identity(null_record["scope_diagnostic"])
            or _live_decision_identity(
                treatment_record.get("live_policy_decision"))
            != _live_decision_identity(
                null_record.get("live_policy_decision"))
            or _live_decision_identity(champion_record)
            != _live_decision_identity(
                treatment_record.get("live_policy_decision"))):
        raise StageCStateScreenError(
            "treatment/null/live decision identity drift")
    result = {
        "schema": SELECTION_SCHEMA,
        "state_id": state_id,
        "deal_seed": deal_seed,
        "seat": seat,
        "trick": int(state["trick"]),
        "phase": phase,
        "role": role,
        "position": position,
        "cell": f"{phase}:{role}",
        "min_completed_tricks": MIN_COMPLETED_TRICKS,
        "policy_seed": policy_seed,
        "final_actions": {
            "treatment": list(_action_key(treatment_play)),
            "matched_null": list(_action_key(null_play)),
            "live": list(champion_key),
        },
        "decisions": {
            "treatment": treatment_record,
            "matched_null": null_record,
        },
        "literal_live_decision": champion_record,
        "complete": True,
        "evaluation_opened": False,
        "strength_claim": False,
        "whole_game_launch_authorized": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    result["selection_sha256"] = _self_hash(result, "selection_sha256")
    return result


def _validate_selection(selection: Mapping[str, object]) -> tuple[
        list[str], list[str], list[str]]:
    state_id = selection.get("state_id")
    deal_seed = selection.get("deal_seed")
    seat = selection.get("seat")
    trick = selection.get("trick")
    phase = selection.get("phase")
    role = selection.get("role")
    position = selection.get("position")
    policy_seed = selection.get("policy_seed")
    actions = selection.get("final_actions")
    decisions = selection.get("decisions")
    if (selection.get("schema") != SELECTION_SCHEMA
            or selection.get("selection_sha256")
            != _self_hash(selection, "selection_sha256")
            or selection.get("complete") is not True
            or selection.get("evaluation_opened") is not False
            or selection.get("strength_claim") is not False
            or selection.get("whole_game_launch_authorized") is not False
            or selection.get("production_promotion") is not False
            or selection.get("production_deployment") is not False
            or selection.get("min_completed_tricks") != MIN_COMPLETED_TRICKS
            or not isinstance(state_id, str) or not state_id
            or isinstance(deal_seed, bool) or not isinstance(deal_seed, int)
            or isinstance(seat, bool) or not isinstance(seat, int)
            or not 0 <= seat < 4
            or isinstance(trick, bool) or not isinstance(trick, int)
            or trick < MIN_COMPLETED_TRICKS
            or phase != ("mid" if trick < 12 else "late")
            or phase not in PHASES or role not in ROLES
            or position not in {"lead", "follow"}
            or selection.get("cell") != f"{phase}:{role}"
            or isinstance(policy_seed, bool) or not isinstance(policy_seed, int)
            or not isinstance(actions, Mapping)
            or not isinstance(decisions, Mapping)):
        raise StageCStateScreenError("screen selection identity drift")
    stream_state = {"state_id": state_id, "seed": deal_seed}
    if policy_seed != _seed(stream_state, "decision"):
        raise StageCStateScreenError("screen selection stream identity drift")
    treatment = list(_action_key(actions.get("treatment", [])))
    matched_null = list(_action_key(actions.get("matched_null", [])))
    live = list(_action_key(actions.get("live", [])))
    treatment_record = _validate_focused_record(
        decisions.get("treatment"), arm="treatment", played=treatment)
    null_record = _validate_focused_record(
        decisions.get("matched_null"), arm="matched-null",
        played=matched_null)
    shared_fields = (
        "candidate_count", "candidate_source", "candidate_keys", "head",
        "epoch", "state_key", "model_selected_index",
        "matched_random_index", "incumbent_index", "treatment_indices",
        "null_indices", "treatment_candidates", "null_candidates",
        "searched_arms_treatment", "searched_arms_null", "selection",
        "report_seed",
    )
    literal_live = selection.get("literal_live_decision")
    if (_action_key(treatment_record["live_incumbent"])
            != _action_key(live)
            or _action_key(null_record["live_incumbent"])
            != _action_key(live)
            or any(treatment_record.get(field) != null_record.get(field)
                   for field in shared_fields)
            or _scope_identity(treatment_record["scope_diagnostic"])
            != _scope_identity(null_record["scope_diagnostic"])
            or _live_decision_identity(
                treatment_record.get("live_policy_decision"))
            != _live_decision_identity(
                null_record.get("live_policy_decision"))
            or _live_decision_identity(literal_live)
            != _live_decision_identity(
                treatment_record.get("live_policy_decision"))):
        raise StageCStateScreenError("screen selection decision identity drift")
    return treatment, matched_null, live


def evaluate_selected(
    state: Mapping[str, object], selection: Mapping[str, object], *,
    replay: Replay, evaluation_fold: EvaluationFold,
) -> dict:
    """Open one independent fold only after selection is frozen/reviewed."""
    state_id, deal_seed, seat, phase, role, position = _state_identity(state)
    treatment, matched_null, live = _validate_selection(selection)
    if (selection.get("state_id") != state_id
            or selection.get("deal_seed") != deal_seed
            or selection.get("seat") != seat
            or selection.get("trick") != state["trick"]
            or selection.get("phase") != phase
            or selection.get("role") != role
            or selection.get("position") != position):
        raise StageCStateScreenError("selection/state replay identity drift")
    evaluation_seed = _seed(state, "independent-evaluation")
    if evaluation_seed == selection["policy_seed"]:
        raise StageCStateScreenError("decision/evaluation stream collision")
    fold = evaluation_fold(
        _replay(state, replay), seat,
        [treatment, matched_null, live], evaluation_seed)
    utilities = _logical_fold(
        fold, [treatment, matched_null, live], evaluation_seed,
        attacker=role == "attacker")
    deltas = {
        "treatment_minus_live": _mean_difference(utilities[0], utilities[2]),
        "treatment_minus_matched_null":
            _mean_difference(utilities[0], utilities[1]),
        "matched_null_minus_live": _mean_difference(utilities[1], utilities[2]),
    }
    result = {
        "schema": SCHEMA,
        "selection": copy.deepcopy(selection),
        "evaluation_seed": evaluation_seed,
        "evaluation_fold": copy.deepcopy(fold),
        "deltas": deltas,
        "complete": True,
        "strength_claim": False,
        "whole_game_launch_authorized": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    result["record_sha256"] = _self_hash(result, "record_sha256")
    return result


def run_state(
    state: Mapping[str, object], *, replay: Replay,
    treatment_factory: PolicyFactory, matched_null_factory: PolicyFactory,
    champion_factory: PolicyFactory, evaluation_fold: EvaluationFold,
) -> dict:
    """Convenience path for tests; evidence must freeze selection first."""
    selection = select_state(
        state, replay=replay, treatment_factory=treatment_factory,
        matched_null_factory=matched_null_factory,
        champion_factory=champion_factory)
    return evaluate_selected(
        state, selection, replay=replay, evaluation_fold=evaluation_fold)


def _validate_record(record: Mapping[str, object]) -> dict[str, float]:
    selection = record.get("selection")
    evaluation_seed = record.get("evaluation_seed")
    fold = record.get("evaluation_fold")
    if (record.get("schema") != SCHEMA
            or record.get("record_sha256")
            != _self_hash(record, "record_sha256")
            or record.get("complete") is not True
            or record.get("strength_claim") is not False
            or record.get("whole_game_launch_authorized") is not False
            or record.get("production_promotion") is not False
            or record.get("production_deployment") is not False
            or not isinstance(selection, Mapping)
            or isinstance(evaluation_seed, bool)
            or not isinstance(evaluation_seed, int)
            or not isinstance(fold, Mapping)):
        raise StageCStateScreenError("screen record identity drift")
    treatment, matched_null, live = _validate_selection(selection)
    stream_state = {
        "state_id": selection["state_id"],
        "seed": selection["deal_seed"],
    }
    if (evaluation_seed
            != _seed(stream_state, "independent-evaluation")
            or evaluation_seed == selection["policy_seed"]):
        raise StageCStateScreenError("screen record stream identity drift")
    utilities = _logical_fold(
        fold, [treatment, matched_null, live], evaluation_seed,
        attacker=selection["role"] == "attacker")
    recomputed = {
        "treatment_minus_live": _mean_difference(utilities[0], utilities[2]),
        "treatment_minus_matched_null":
            _mean_difference(utilities[0], utilities[1]),
        "matched_null_minus_live": _mean_difference(utilities[1], utilities[2]),
    }
    if record.get("deltas") != recomputed:
        raise StageCStateScreenError("screen record delta recomputation drift")
    return recomputed


def _summary(values: Sequence[float], *, two_sided: bool = False) -> dict:
    if len(values) != TARGET_STATES or not all(math.isfinite(value)
                                               for value in values):
        raise StageCStateScreenError("screen contrast population drift")
    mean = statistics.fmean(values)
    se = statistics.stdev(values) / math.sqrt(len(values))
    if two_sided:
        return {
            "n": len(values), "mean": mean, "standard_error": se,
            "critical": TWO_SIDED_CRITICAL,
            "lower95": mean - TWO_SIDED_CRITICAL * se,
            "upper95": mean + TWO_SIDED_CRITICAL * se,
            "bound": "paired-state two-sided 95%; t=1.97",
        }
    return {
        "n": len(values), "mean": mean, "standard_error": se,
        "critical": ONE_SIDED_CRITICAL,
        "one_sided_95_lcb": mean - ONE_SIDED_CRITICAL * se,
        "bound": "paired-state one-sided 95%; t=1.70",
    }


def aggregate(
    records: Sequence[Mapping[str, object]], *,
    forbidden_deal_seeds: Sequence[int],
) -> dict:
    """Aggregate 256 fresh one-state-per-deal records into the frozen gate."""
    if not isinstance(records, (list, tuple)) or len(records) != TARGET_STATES:
        raise StageCStateScreenError("screen requires exactly 256 records")
    state_ids = []
    deal_seeds = []
    cells: Counter[str] = Counter()
    positions: Counter[str] = Counter()
    deltas = {name: [] for name in (
        "treatment_minus_live", "treatment_minus_matched_null",
        "matched_null_minus_live")}
    for record in records:
        if not isinstance(record, Mapping):
            raise StageCStateScreenError("screen record identity drift")
        values = _validate_record(record)
        selection = record["selection"]
        state_ids.append(selection.get("state_id"))
        deal_seeds.append(selection.get("deal_seed"))
        cells[str(selection.get("cell"))] += 1
        positions[str(selection.get("position"))] += 1
        for name in deltas:
            deltas[name].append(values[name])
    if (not isinstance(forbidden_deal_seeds, (list, tuple))
            or any(isinstance(seed, bool) or not isinstance(seed, int)
                   for seed in forbidden_deal_seeds)
            or any(not isinstance(state_id, str) or not state_id
                   for state_id in state_ids)):
        raise StageCStateScreenError("screen freshness manifest drift")
    forbidden = set(forbidden_deal_seeds)
    if (len(set(state_ids)) != TARGET_STATES
            or len(set(deal_seeds)) != TARGET_STATES
            or any(isinstance(seed, bool) or not isinstance(seed, int)
                   for seed in deal_seeds)
            or set(deal_seeds) & forbidden
            or dict(cells) != {cell: TARGET_PER_CELL for cell in CELL_KEYS}):
        raise StageCStateScreenError(
            "screen freshness/deal/cell quota drift")

    stats = {
        "treatment_minus_live": _summary(deltas["treatment_minus_live"]),
        "treatment_minus_matched_null":
            _summary(deltas["treatment_minus_matched_null"]),
        "matched_null_minus_live":
            _summary(deltas["matched_null_minus_live"], two_sided=True),
    }
    null = stats["matched_null_minus_live"]
    gates = {
        "treatment_minus_live_lcb_gt_zero":
            stats["treatment_minus_live"]["one_sided_95_lcb"] > 0,
        "treatment_minus_matched_null_lcb_gt_zero":
            stats["treatment_minus_matched_null"][
                "one_sided_95_lcb"] > 0,
        "exact_256_unique_deal_population": True,
        "exact_mid_late_role_quotas": True,
        "zero_forbidden_deal_overlap": True,
    }
    passed = all(gates.values())
    result = {
        "schema": AGGREGATE_SCHEMA,
        "states": TARGET_STATES,
        "cell_counts": {cell: cells[cell] for cell in CELL_KEYS},
        "position_counts": {
            position: positions[position] for position in ("lead", "follow")
        },
        "statistics": stats,
        "diagnostics": {
            # The null/live contrast explains whether extra protected search
            # alone helped or hurt.  It is not a third promotion test: the two
            # primary LCBs already require treatment to beat both the literal
            # champion and the same-work null.
            "matched_null_minus_live_interval_contains_zero":
                null["lower95"] <= 0 <= null["upper95"],
        },
        "gates": gates,
        "decision": (
            "AUTHORIZE_WHOLE_GAME_SCREEN_DESIGN" if passed
            else "SELECT_NONE"),
        "whole_game_screen_design_authorized": passed,
        "whole_game_launch_authorized": False,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    result["aggregate_sha256"] = _self_hash(result, "aggregate_sha256")
    return result
