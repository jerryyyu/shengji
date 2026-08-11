"""Bounded Stage-C proposal focusing for a future report-LCB composition.

The learned model never directly overrides the incumbent here.  It selects at
most one challenger from an already frozen public-information candidate union.
The treatment pair is incumbent versus that challenger. A matched null uses
the exact same model trigger (and therefore the same number of searched arms)
but substitutes one deterministic random non-incumbent candidate. The policy
wrappers feed those pairs to fresh paired report-LCB search.

This module does not register a bot, open evidence, or authorize a strength
run, promotion, or deployment. Merely constructing a wrapper grants no run
authority.
"""
from __future__ import annotations

import copy
import hashlib
import math
import random
import time
from typing import Callable, Mapping, Sequence

from ..ai.memory import Memory
from .encode import encode_action, encode_obs
from .stage_c_model import canonical_json
from .stage_c_npnet import StageCEnsemble


SCHEMA = "teacher-stage-c-focused-proposal-v1"
PLAY_CANDIDATE_CAP = 20
BURY_CANDIDATE_CAP = 33
TELEMETRY_FIELDS = (
    "focus_calls", "scope_checks", "scope_eligible", "scope_ineligible",
    "scope_candidate_rollouts", "model_keeps", "model_triggers",
    "fallbacks", "report_overrides", "report_rejections",
    "report_underfills",
)
SCOPE_WORLDS = 30
SCOPE_ATTEMPT_FACTOR = 10
SCOPE_MARGIN_WINDOW = 2.5


class StageCCompositionError(RuntimeError):
    """A candidate union, surface, model result, or null identity drifted."""


def _require_live_report_lcb(bot) -> None:
    expected = {
        "N_DETERMINIZATIONS": 30,
        "REQUIRE_EXACT_WORK": True,
        "ADAPTIVE_ALLOCATION": False,
        "RANDOM_ALLOCATION": False,
        "EXTRA_SELECTION_WORK": 0,
        "REPORT_FOLD_WORLDS": 300,
        "REPORT_RULE": "lcb",
        "REPORT_MIN_GAIN": 0.0,
        "REPORT_ALPHA": 0.05,
        "MC_BURY": False,
        "MAX_CANDIDATES": 8,
        "LEAD_MAX_CANDIDATES": 14,
        "FOLLOW_MAX_CANDIDATES": 12,
    }
    actual = {name: getattr(bot, name, None) for name in expected}
    if actual != expected:
        raise StageCCompositionError(
            "Stage-C parent differs from exact live report-LCB")


def _validate_candidate_legality(rnd, seat: int,
                                 candidates: Sequence[Sequence[str]],
                                 surface: str) -> None:
    for candidate in candidates:
        clone = copy.deepcopy(rnd)
        try:
            if surface == "play":
                clone.play(seat, list(candidate))
            elif surface == "bury":
                clone.bury(seat, list(candidate))
            else:
                raise StageCCompositionError(
                    "Stage-C candidate legality surface drift")
        except Exception as exc:
            raise StageCCompositionError(
                f"Stage-C {surface} candidate is replay-illegal: {exc}") \
                from exc


def stage_c_policy_telemetry(bots: Sequence[object]) -> dict:
    """Aggregate the activation witness required by a whole-game screen."""
    if not isinstance(bots, (list, tuple)) or not bots:
        raise StageCCompositionError("Stage-C telemetry bot population drift")
    totals = {field: 0 for field in TELEMETRY_FIELDS}
    for bot in bots:
        values = {
            "focus_calls": getattr(bot, "stage_c_focus_calls", None),
            "scope_checks": getattr(bot, "stage_c_scope_checks", None),
            "scope_eligible": getattr(
                bot, "stage_c_scope_eligible", None),
            "scope_ineligible": getattr(
                bot, "stage_c_scope_ineligible", None),
            "scope_candidate_rollouts": getattr(
                bot, "stage_c_scope_candidate_rollouts", None),
            "model_keeps": getattr(bot, "stage_c_model_keeps", None),
            "model_triggers": getattr(bot, "stage_c_focus_triggers", None),
            "fallbacks": getattr(bot, "stage_c_focus_fallbacks", None),
            "report_overrides": getattr(
                bot, "stage_c_report_overrides", None),
            "report_rejections": getattr(
                bot, "stage_c_report_rejections", None),
            "report_underfills": getattr(
                bot, "stage_c_report_underfills", None),
        }
        if any(isinstance(value, bool) or not isinstance(value, int)
               or value < 0 for value in values.values()):
            raise StageCCompositionError(
                "Stage-C telemetry counter population drift")
        for field, value in values.items():
            totals[field] += value
    if (totals["scope_checks"] > totals["focus_calls"]
            or totals["scope_eligible"] + totals["scope_ineligible"]
            > totals["scope_checks"]
            or totals["model_triggers"] > totals["scope_eligible"]):
        raise StageCCompositionError("Stage-C scope counters do not nest")
    # A zero-fallback evidence run has a closed decision tree. When a fallback
    # occurred, retain the raw counters so the future gate can reject the run;
    # an exception may have happened after a trigger and therefore overlap it.
    if totals["fallbacks"] == 0 and (
            totals["focus_calls"] != totals["scope_checks"]
            or totals["scope_checks"]
            != totals["scope_eligible"] + totals["scope_ineligible"]
            or totals["scope_eligible"]
            != totals["model_keeps"] + totals["model_triggers"]
            or totals["model_triggers"]
            != totals["report_overrides"]
            + totals["report_rejections"]
            + totals["report_underfills"]):
        raise StageCCompositionError(
            "Stage-C zero-fallback telemetry does not reconcile")
    return {
        "schema": "teacher-stage-c-policy-telemetry-v1",
        **totals,
        "exact_reconciliation": totals["fallbacks"] == 0,
        "strength_claim": False,
    }


def action_key(cards: Sequence[object]) -> tuple[str, ...]:
    if (not isinstance(cards, (list, tuple)) or not cards
            or any(not isinstance(card, str) or not card for card in cards)):
        raise StageCCompositionError("Stage-C composition action geometry drift")
    return tuple(sorted(cards))


def _candidate_union(candidates: Sequence[Sequence[str]], surface: str
                     ) -> list[list[str]]:
    if surface not in {"play", "bury"} or not isinstance(candidates, (list, tuple)):
        raise StageCCompositionError("Stage-C composition surface/union drift")
    cap = PLAY_CANDIDATE_CAP if surface == "play" else BURY_CANDIDATE_CAP
    values = [list(candidate) for candidate in candidates]
    keys = [action_key(value) for value in values]
    if not values or len(values) > cap or len(set(keys)) != len(keys):
        raise StageCCompositionError("Stage-C composition candidate union drift")
    return values


def _matched_random_index(candidates: Sequence[Sequence[str]], *,
                          state_key: str, incumbent_index: int) -> int:
    if not isinstance(state_key, str) or not state_key:
        raise StageCCompositionError("Stage-C composition state key drift")
    if (isinstance(incumbent_index, bool)
            or not isinstance(incumbent_index, int)
            or not 0 <= incumbent_index < len(candidates)):
        raise StageCCompositionError("Stage-C null incumbent drift")
    alternatives = [index for index in range(len(candidates))
                    if index != incumbent_index]
    if not alternatives:
        return incumbent_index
    identity = [list(action_key(candidate)) for candidate in candidates]
    digest = hashlib.sha256(
        ("teacher-stage-c-composition-null-v1|" + state_key + "|"
         + repr(identity)).encode()).digest()
    return alternatives[int.from_bytes(digest[:16], "big")
                        % len(alternatives)]


def focused_pairs(
    ensemble: StageCEnsemble, rnd, seat: int,
    candidates: Sequence[Sequence[str]], *, state_key: str,
    protected_incumbent: Sequence[str] | None = None,
) -> dict:
    """Freeze treatment/null arms with identical model-triggered work geometry."""
    surface = ensemble.surface
    values = _candidate_union(candidates, surface)
    if (not isinstance(seat, int) or not 0 <= seat < 4
            or (surface == "play"
                and (getattr(rnd, "phase", None) != "play"
                     or getattr(rnd, "turn", None) != seat))
            or (surface == "bury"
                and (getattr(rnd, "phase", None) != "bury"
                     or getattr(rnd, "banker", None) != seat))):
        raise StageCCompositionError("Stage-C composition decision surface drift")
    obs = encode_obs(rnd, seat)
    actions = [encode_action(candidate, rnd) for candidate in values]
    selection = ensemble.select(obs, actions)
    model_index = selection.get("selected_index")
    if (isinstance(model_index, bool) or not isinstance(model_index, int)
            or not 0 <= model_index < len(values)
            or selection.get("surface") != surface
            or selection.get("candidate_count") != len(values)):
        raise StageCCompositionError("Stage-C composition model selection drift")
    incumbent_key = action_key(
        values[0] if protected_incumbent is None else protected_incumbent)
    incumbent_matches = [index for index, value in enumerate(values)
                         if action_key(value) == incumbent_key]
    if len(incumbent_matches) != 1:
        raise StageCCompositionError(
            "Stage-C protected incumbent is absent or duplicated")
    incumbent_index = incumbent_matches[0]
    triggered = model_index != incumbent_index
    null_index = incumbent_index
    if triggered:
        null_index = _matched_random_index(
            values, state_key=state_key, incumbent_index=incumbent_index)
    treatment_indices = ([incumbent_index] if not triggered else
                         [incumbent_index, model_index])
    null_indices = ([incumbent_index] if not triggered else
                    [incumbent_index, null_index])
    result = {
        "schema": SCHEMA,
        "surface": surface,
        "head": ensemble.head,
        "epoch": ensemble.epoch,
        "state_key": state_key,
        "candidate_count": len(values),
        "candidate_keys": [list(action_key(value)) for value in values],
        "incumbent_index": incumbent_index,
        "model_selected_index": model_index,
        "model_triggered": triggered,
        "matched_random_index": null_index,
        "treatment_indices": treatment_indices,
        "null_indices": null_indices,
        "treatment_candidates": [values[index] for index in treatment_indices],
        "null_candidates": [values[index] for index in null_indices],
        "searched_arms_treatment": len(treatment_indices),
        "searched_arms_null": len(null_indices),
        "selection": selection,
        "model_direct_override_authorized": False,
        "fresh_paired_report_lcb_required": triggered,
        "strength_claim": False,
        "production_promotion": False,
        "production_deployment": False,
    }
    if (result["treatment_candidates"][0] != values[incumbent_index]
            or result["null_candidates"][0] != values[incumbent_index]
            or result["searched_arms_treatment"]
            != result["searched_arms_null"]):
        raise StageCCompositionError("Stage-C composition matched-arm drift")
    return result


def _state_key(rnd, seat: int, candidates: Sequence[Sequence[str]]) -> str:
    payload = {
        "schema": "teacher-stage-c-composition-state-key-v1",
        "seat": seat,
        "observation": encode_obs(rnd, seat),
        "candidate_keys": [list(action_key(value)) for value in candidates],
    }
    return hashlib.sha256(canonical_json(payload)).hexdigest()


CandidateSource = Callable[[object, object, int, list[list[str]]],
                           tuple[Sequence[Sequence[str]], Mapping[str, object]]]


def champion_uncertainty_diagnostic(
    bot, rnd, seat: int, candidates: Sequence[Sequence[str]], *,
    state_key: str,
) -> dict:
    """Recompute the score-free capture predicate before Stage-C inference.

    The diagnostic is the same public N=30 common-world ``mc-strong`` test
    used to source the frozen champion-uncertainty stratum.  It is deliberately
    separate from both the live champion decision and the later fresh report
    fold.  Its deterministic stream depends only on the public state key; it
    never consumes or changes the live policy RNG.
    """
    values = _candidate_union(candidates, "play")
    if len(values) < 2:
        raise StageCCompositionError(
            "Stage-C uncertainty scope needs at least two candidates")
    if not isinstance(state_key, str) or not state_key:
        raise StageCCompositionError("Stage-C uncertainty state key drift")
    mem = Memory(
        rnd, seat, own_kitty=getattr(bot, "BANKER_KITTY", True))
    before = bot._sampler_snapshot()
    rows: list[list[float]] = []
    attempts = 0
    cap = SCOPE_WORLDS * SCOPE_ATTEMPT_FACTOR
    original_rng = bot.rng
    started = time.perf_counter()
    bot.search_calls += 1
    try:
        seed = int.from_bytes(hashlib.sha256(
            ("teacher-stage-c-live-uncertainty-v1|" + state_key).encode()
        ).digest()[:16], "big")
        bot.rng = random.Random(seed)
        while len(rows) < SCOPE_WORLDS and attempts < cap:
            attempts += 1
            sampled = bot._sample_hands(rnd, seat, mem)
            if sampled is None:
                continue
            hands, buried = sampled
            sign = 1.0 if rnd.is_attacker(seat) else -1.0
            rows.append([
                sign * bot._score(bot._rollout(
                    rnd, seat, hands, buried, candidate))
                for candidate in values
            ])
    finally:
        bot.rng = original_rng
        elapsed = time.perf_counter() - started
        bot.search_secs += elapsed
        bot.rollouts += len(rows) * len(values)
    counters = bot._sampler_delta(before)
    diagnostic = {
        "schema": "teacher-stage-c-live-uncertainty-selection-v1",
        "selection_only": True,
        "stage_c_inference_performed": False,
        "public_information_only": True,
        "worlds": len(rows),
        "attempts": attempts,
        "candidate_worlds": len(rows) * len(values),
        "sampler_counters": counters,
        "means": None,
        "raw_best_index": None,
        "paired_gap_vs_candidate0": None,
        "paired_se_vs_candidate0": None,
        "production_margin": float(bot.MARGIN),
        "margin_window": SCOPE_MARGIN_WINDOW,
        "evaluation_complete": False,
        "eligible": False,
        "elapsed_seconds": elapsed,
    }
    if len(rows) != SCOPE_WORLDS:
        bot.short_search_decisions += 1
        diagnostic["reason"] = "uncertainty_underfilled"
        return diagnostic
    if (counters["accepted_worlds"] != SCOPE_WORLDS
            or counters["failed_worlds"]
            or counters["rejected_worlds"]
            or counters["impossible_worlds"]):
        diagnostic["reason"] = "uncertainty_sampler_refusal"
        return diagnostic
    means = [sum(row[index] for row in rows) / len(rows)
             for index in range(len(values))]
    best = bot._pick_index(values, means, range(len(values)))
    gap = means[best] - means[0]
    diffs = [row[best] - row[0] for row in rows]
    mean = sum(diffs) / len(diffs)
    variance = sum((value - mean) ** 2 for value in diffs) / (
        len(diffs) - 1)
    se = math.sqrt(variance / len(diffs))
    margin = float(bot.MARGIN)
    eligible = best != 0 and abs(gap - margin) <= SCOPE_MARGIN_WINDOW
    diagnostic.update({
        "means": means,
        "raw_best_index": best,
        "paired_gap_vs_candidate0": gap,
        "paired_se_vs_candidate0": se,
        "evaluation_complete": True,
        "eligible": eligible,
        "reason": ("eligible" if eligible else
                   "outside_uncertainty_window"),
    })
    return diagnostic


def make_play_report_lcb_bot(
    ensemble: StageCEnsemble, candidate_source: CandidateSource, *,
    arm: str, seed: int | None = None,
):
    """Add one protected Stage-C proposal to the literal live policy.

    The live report-LCB decision is made first and remains the incumbent.  A
    separate public N=30 diagnostic over the reviewed capture union determines
    whether the state is in scope *before* Stage-C runs.  In scope, Stage-C may
    nominate one challenger; a fresh paired N=300 LCB can replace the already-
    chosen live action.  Any failure or non-positive report keeps that exact
    action, not merely candidate zero from the heuristic ballot.
    """
    if ensemble.surface != "play" or arm not in {"treatment", "matched-null"}:
        raise StageCCompositionError("Stage-C play wrapper identity drift")
    if not callable(candidate_source):
        raise StageCCompositionError("Stage-C candidate source is not callable")
    # Lazy import avoids making ordinary game/server imports depend on this
    # experimental model path.
    from ..ai.registry import REGISTRY

    base = REGISTRY.get("mc-s0-report-lcb")
    if not isinstance(base, type):
        raise StageCCompositionError("live report-LCB class is unavailable")

    class StageCFocusedReportLCB(base):
        stage_c_arm = arm

        def __init__(self, policy_seed=None):
            super().__init__(policy_seed)
            _require_live_report_lcb(self)
            self.stage_c_focus_calls = 0
            self.stage_c_scope_checks = 0
            self.stage_c_scope_eligible = 0
            self.stage_c_scope_ineligible = 0
            self.stage_c_scope_candidate_rollouts = 0
            self.stage_c_focus_triggers = 0
            self.stage_c_focus_fallbacks = 0
            self.stage_c_model_keeps = 0
            self.stage_c_report_overrides = 0
            self.stage_c_report_rejections = 0
            self.stage_c_report_underfills = 0
            self.last_stage_c_focus_record = None
            self.policy_name = f"stage-c-play-{arm}"

        def _publish_play_record(
            self, record: dict, live_record: dict | None,
            live_play, played,
        ) -> list[str]:
            record["live_incumbent"] = list(live_play)
            record["played"] = list(played)
            record["live_policy_decision"] = copy.deepcopy(live_record)
            self.last_stage_c_focus_record = record
            if live_record is None:
                decision = {
                    "schema": "stage-c-composed-decision-v1",
                    "policy": self.policy_name,
                    "live_policy_decision": None,
                }
            else:
                decision = copy.deepcopy(live_record)
            decision["stage_c_composition"] = {
                key: copy.deepcopy(value) for key, value in record.items()
                if key != "live_policy_decision"
            }
            decision["final_played"] = list(played)
            decision["final_reason"] = record["reason"]
            self.last_decision_record = decision
            return list(played)

        def decide_play(self, rnd, seat):
            self.last_stage_c_focus_record = None
            live_play = list(super().decide_play(rnd, seat))
            live_record = copy.deepcopy(self.last_decision_record)
            focus_started = False
            try:
                # Re-read the deterministic ballot through the exact parent.
                # When the live decision searched, require byte-equivalent
                # candidates rather than silently composing around a new set.
                live = [list(value) for value in super()._candidates(rnd, seat)]
                if (live_record is not None
                        and live_record.get("candidates") is not None
                        and [list(value) for value in
                             live_record["candidates"]] != live):
                    raise StageCCompositionError(
                        "Stage-C live ballot changed after incumbent decision")
                union, source_record = candidate_source(
                    self, rnd, seat, live)
                union = _candidate_union(union, "play")
                if len(union) < 2:
                    return live_play
                focus_started = True
                self.stage_c_focus_calls += 1
                live_keys = [action_key(value) for value in live]
                union_keys = [action_key(value) for value in union]
                if union_keys[:len(live_keys)] != live_keys:
                    raise StageCCompositionError(
                        "Stage-C union did not preserve the complete live ballot")
                if action_key(live_play) not in union_keys:
                    raise StageCCompositionError(
                        "Stage-C live incumbent is absent from candidate union")
                if not isinstance(source_record, Mapping):
                    raise StageCCompositionError(
                        "Stage-C candidate-source record drift")
                _validate_candidate_legality(rnd, seat, union, "play")
                state_key = _state_key(rnd, seat, union)

                # This must precede Stage-C inference.  It deliberately uses
                # the capture candidate-zero baseline even when the live
                # report-LCB policy chose a different incumbent.
                scope = champion_uncertainty_diagnostic(
                    self, rnd, seat, union, state_key=state_key)
                if (scope["evaluation_complete"] is not True
                        or scope["reason"] == "uncertainty_sampler_refusal"):
                    raise StageCCompositionError(
                        f"Stage-C scope refused: {scope['reason']}")
                self.stage_c_scope_checks += 1
                self.stage_c_scope_candidate_rollouts += int(
                    scope["candidate_worlds"])
                base_record = {
                    "schema": SCHEMA,
                    "surface": "play",
                    "arm": arm,
                    "candidate_count": len(union),
                    "candidate_source": dict(source_record),
                    "scope_diagnostic": scope,
                    "fallback_to_live_ballot": False,
                    "model_direct_override_authorized": False,
                    "fresh_paired_report_lcb_required": True,
                    "strength_claim": False,
                    "production_promotion": False,
                    "production_deployment": False,
                }
                if not scope["eligible"]:
                    self.stage_c_scope_ineligible += 1
                    base_record.update({
                        "model_triggered": False,
                        "reason": "outside_champion_uncertainty_scope",
                        "report_fold": None,
                    })
                    return self._publish_play_record(
                        base_record, live_record, live_play, live_play)

                record = focused_pairs(
                    ensemble, rnd, seat, union, state_key=state_key,
                    protected_incumbent=live_play)
                record.update(base_record)
                if not record["model_triggered"]:
                    self.stage_c_scope_eligible += 1
                    self.stage_c_model_keeps += 1
                    record.update({
                        "reason": "model_kept_live_incumbent",
                        "report_fold": None,
                    })
                    return self._publish_play_record(
                        record, live_record, live_play, live_play)

                indices = (record["treatment_indices"]
                           if arm == "treatment" else record["null_indices"])
                if (len(indices) != 2
                        or indices[0] != record["incumbent_index"]
                        or indices[1] == record["incumbent_index"]):
                    raise StageCCompositionError(
                        "Stage-C focused play pair geometry drift")
                challenger_index = indices[1]
                challenger = union[challenger_index]
                pre_rng_state = self.rng.getstate()
                report_seed = _child_seed(
                    pre_rng_state, "stage-c-play-report")
                mem = Memory(
                    rnd, seat,
                    own_kitty=getattr(self, "BANKER_KITTY", True))
                before = self._sampler_snapshot()
                started = time.perf_counter()
                self.search_calls += 1
                report = self._report_fold_gap(
                    rnd, seat, mem, rnd.is_attacker(seat),
                    challenger, live_play, self.REPORT_FOLD_WORLDS,
                    seed=report_seed)
                elapsed = time.perf_counter() - started
                rollouts = 2 * report["worlds"]
                self.rollouts += rollouts
                self.search_secs += elapsed
                critical = statistic = None
                if report["complete"]:
                    critical = self._report_critical(report["worlds"])
                    statistic = report["gap"] - critical * report["se"]
                report_record = {
                    **report,
                    "fold": "fresh_stage_c_report",
                    "rule": self.REPORT_RULE,
                    "critical": critical,
                    "statistic": statistic,
                    "min_gain": self.REPORT_MIN_GAIN,
                    "bound":
                        "paired_student_t_one_sided_95_conservative_df>=29",
                }
                record.update({
                    "report_seed": report_seed,
                    "report_fold": report_record,
                    "challenger_candidate_union_index": challenger_index,
                    "search_secs": elapsed,
                    "work": {
                        "report_budget": 2 * self.REPORT_FOLD_WORLDS,
                        "report_rollouts": rollouts,
                        "complete": report["complete"],
                    },
                    "sampler_counters": {
                        "before": before,
                        "after": self._sampler_snapshot(),
                        "delta": self._sampler_delta(before),
                    },
                })
                self.stage_c_scope_eligible += 1
                self.stage_c_focus_triggers += 1
                if not report["complete"]:
                    self.short_search_decisions += 1
                    self.stage_c_report_underfills += 1
                    record["reason"] = "stage_c_report_underfilled"
                    return self._publish_play_record(
                        record, live_record, live_play, live_play)
                if statistic < self.REPORT_MIN_GAIN:
                    self.stage_c_report_rejections += 1
                    record["reason"] = "stage_c_report_lcb_below_min_gain"
                    return self._publish_play_record(
                        record, live_record, live_play, live_play)
                self.stage_c_report_overrides += 1
                record["reason"] = "stage_c_report_lcb_override"
                return self._publish_play_record(
                    record, live_record, live_play, challenger)
            except Exception as exc:
                if not focus_started:
                    self.stage_c_focus_calls += 1
                self.stage_c_focus_fallbacks += 1
                record = {
                    "schema": SCHEMA,
                    "surface": "play",
                    "arm": arm,
                    "candidate_count": 0,
                    "fallback_to_live_ballot": True,
                    "failure_type": type(exc).__name__,
                    "failure": str(exc),
                    "reason": "stage_c_failure_live_incumbent",
                    "model_direct_override_authorized": False,
                    "fresh_paired_report_lcb_required": True,
                    "strength_claim": False,
                    "production_promotion": False,
                    "production_deployment": False,
                }
                return self._publish_play_record(
                    record, live_record, live_play, live_play)

    StageCFocusedReportLCB.__name__ = (
        "StageCPlayReportLCB" if arm == "treatment"
        else "StageCPlayMatchedNullReportLCB")
    return StageCFocusedReportLCB(seed)


def _bury_report_fold_gap(bot, rnd, seat: int, mem, cand_a, cand_b,
                          n: int, *, seed: int) -> dict:
    """Evaluate two buries on fresh paired worlds from the banker's view."""
    if (isinstance(n, bool) or not isinstance(n, int) or n <= 0
            or isinstance(seed, bool) or not isinstance(seed, int)):
        raise StageCCompositionError("Stage-C bury report work drift")
    d_sum = d_sq = 0.0
    used = attempts = 0
    cap = n * bot.SAMPLE_ATTEMPT_FACTOR
    original_rng = bot.rng
    try:
        bot.rng = random.Random(seed)
        while used < n and attempts < cap:
            attempts += 1
            sampled = bot._sample_hands(rnd, seat, mem)
            if sampled is None:
                continue
            hands, _buried = sampled
            # _rollout_from_bury returns attacker points. Higher is worse for
            # the banker, so negate the live bot's level-aware score before
            # taking challenger-minus-incumbent.
            value_a = -bot._score(bot._rollout_from_bury(
                rnd, seat, hands, list(cand_a)))
            value_b = -bot._score(bot._rollout_from_bury(
                rnd, seat, hands, list(cand_b)))
            delta = value_a - value_b
            d_sum += delta
            d_sq += delta * delta
            used += 1
    finally:
        bot.rng = original_rng
    mean = d_sum / used if used else 0.0
    return {
        "gap": mean,
        "se": bot._paired_se(d_sum, d_sq, used),
        "worlds": used,
        "attempts": attempts,
        "rejected": attempts - used,
        "complete": used == n,
        "seed": seed,
    }


def _child_seed(state, purpose: str) -> int:
    raw = hashlib.sha256(f"{purpose}|{state!r}".encode()).digest()
    return int.from_bytes(raw[:16], "big")


def make_bury_report_lcb_bot(
    ensemble: StageCEnsemble, candidate_source: CandidateSource, *,
    arm: str, seed: int | None = None,
):
    """Protect one model-selected bury with a fresh paired report-LCB fold.

    The model is only a proposer.  On every trigger, treatment and matched
    null each price exactly incumbent plus one challenger on the same N=300
    work geometry. A challenger can be played only when its fresh banker's-
    perspective lower confidence bound is positive. Any source/model failure,
    report underfill, or negative bound keeps the literal live incumbent.
    """
    if ensemble.surface != "bury" or arm not in {"treatment", "matched-null"}:
        raise StageCCompositionError("Stage-C bury wrapper identity drift")
    if not callable(candidate_source):
        raise StageCCompositionError("Stage-C candidate source is not callable")
    from ..ai.registry import REGISTRY

    base = REGISTRY.get("mc-s0-report-lcb")
    if not isinstance(base, type):
        raise StageCCompositionError("live report-LCB class is unavailable")

    class StageCFocusedBuryReportLCB(base):
        stage_c_arm = arm

        def __init__(self, policy_seed=None):
            super().__init__(policy_seed)
            _require_live_report_lcb(self)
            self.stage_c_focus_calls = 0
            self.stage_c_scope_checks = 0
            self.stage_c_scope_eligible = 0
            self.stage_c_scope_ineligible = 0
            self.stage_c_scope_candidate_rollouts = 0
            self.stage_c_focus_triggers = 0
            self.stage_c_focus_fallbacks = 0
            self.stage_c_model_keeps = 0
            self.stage_c_report_overrides = 0
            self.stage_c_report_rejections = 0
            self.stage_c_report_underfills = 0
            self.last_stage_c_focus_record = None
            self.policy_name = f"stage-c-bury-{arm}"

        def _publish_bury_record(self, record: dict, played) -> list[str]:
            record["played"] = list(played)
            self.last_stage_c_focus_record = record
            self.last_bury_record = record
            return list(played)

        def decide_bury(self, rnd, seat):
            self.last_stage_c_focus_record = None
            self.last_override_stats = None
            self.last_n_worlds = 0
            incumbent = list(super().decide_bury(rnd, seat))
            self.stage_c_focus_calls += 1
            try:
                union, source_record = candidate_source(
                    self, rnd, seat, [incumbent])
                union = _candidate_union(union, "bury")
                if action_key(union[0]) != action_key(incumbent):
                    raise StageCCompositionError(
                        "Stage-C bury candidate zero differs from live")
                _validate_candidate_legality(rnd, seat, union, "bury")
                if not isinstance(source_record, Mapping):
                    raise StageCCompositionError(
                        "Stage-C candidate-source record drift")
                state_key = _state_key(rnd, seat, union)
                record = focused_pairs(
                    ensemble, rnd, seat, union, state_key=state_key)
                self.stage_c_scope_checks += 1
                self.stage_c_scope_eligible += 1
                record["candidate_source"] = dict(source_record)
                record["arm"] = arm
                record["fallback_to_live_ballot"] = False
                record["report_worlds_requested"] = self.REPORT_FOLD_WORLDS
                record["report_rule"] = self.REPORT_RULE
                if not record["model_triggered"]:
                    self.stage_c_model_keeps += 1
                    record["reason"] = "model_kept_incumbent"
                    record["played_candidate_union_index"] = 0
                    record["report_fold"] = None
                    record["work"] = {
                        "report_budget": 0, "report_rollouts": 0,
                        "complete": True,
                    }
                    return self._publish_bury_record(record, incumbent)

                self.stage_c_focus_triggers += 1
                indices = (record["treatment_indices"]
                           if arm == "treatment" else record["null_indices"])
                if len(indices) != 2 or indices[0] != 0 or indices[1] == 0:
                    raise StageCCompositionError(
                        "Stage-C bury focused arm geometry drift")
                challenger_index = indices[1]
                challenger = union[challenger_index]
                before = self._sampler_snapshot()
                pre_rng_state = self.rng.getstate()
                report_seed = _child_seed(
                    pre_rng_state, "stage-c-bury-report")
                started = time.perf_counter()
                self.search_calls += 1
                self.bury_search_calls += 1
                mem = Memory(
                    rnd, seat,
                    own_kitty=getattr(self, "BANKER_KITTY", True),
                )
                report = _bury_report_fold_gap(
                    self, rnd, seat, mem, challenger, incumbent,
                    self.REPORT_FOLD_WORLDS, seed=report_seed)
                self.last_n_worlds = report["worlds"]
                elapsed = time.perf_counter() - started
                rollouts = 2 * report["worlds"]
                self.rollouts += rollouts
                self.bury_rollouts += rollouts
                self.search_secs += elapsed
                self.bury_search_secs += elapsed
                critical = statistic = None
                if report["complete"]:
                    critical = (0.0 if self.REPORT_RULE == "mean"
                                else self._report_critical(report["worlds"]))
                    statistic = report["gap"] - critical * report["se"]
                report_record = {
                    **report,
                    "fold": "report",
                    "rule": self.REPORT_RULE,
                    "critical": critical,
                    "statistic": statistic,
                    "min_gain": self.REPORT_MIN_GAIN,
                    "bound": (
                        "paired_mean" if self.REPORT_RULE == "mean" else
                        "paired_student_t_one_sided_95_conservative_df>=29"),
                }
                self.last_override_stats = report_record
                record["rng_state"] = pre_rng_state
                record["report_seed"] = report_seed
                record["report_fold"] = report_record
                record["challenger_candidate_union_index"] = challenger_index
                record["search_secs"] = elapsed
                record["work"] = {
                    "report_budget": 2 * self.REPORT_FOLD_WORLDS,
                    "report_rollouts": rollouts,
                    "complete": report["complete"],
                }
                record["sampler_counters"] = {
                    "before": before,
                    "after": self._sampler_snapshot(),
                    "delta": self._sampler_delta(before),
                }
                if not report["complete"]:
                    self.short_search_decisions += 1
                    self.stage_c_report_underfills += 1
                    record["reason"] = "report_underfilled"
                    record["played_candidate_union_index"] = 0
                    return self._publish_bury_record(record, incumbent)
                if statistic < self.REPORT_MIN_GAIN:
                    self.stage_c_report_rejections += 1
                    record["reason"] = f"report_{self.REPORT_RULE}_below_min_gain"
                    record["played_candidate_union_index"] = 0
                    return self._publish_bury_record(record, incumbent)
                record["reason"] = f"report_{self.REPORT_RULE}_override"
                self.stage_c_report_overrides += 1
                record["played_candidate_union_index"] = challenger_index
                return self._publish_bury_record(record, challenger)
            except Exception as exc:
                self.stage_c_focus_fallbacks += 1
                record = {
                    "schema": SCHEMA,
                    "surface": "bury",
                    "arm": arm,
                    "candidate_count": 1,
                    "fallback_to_live_ballot": True,
                    "failure_type": type(exc).__name__,
                    "failure": str(exc),
                    "reason": "stage_c_failure_live_incumbent",
                    "played_candidate_union_index": 0,
                    "model_direct_override_authorized": False,
                    "fresh_paired_report_lcb_required": True,
                    "strength_claim": False,
                    "production_promotion": False,
                    "production_deployment": False,
                }
                return self._publish_bury_record(record, incumbent)

    StageCFocusedBuryReportLCB.__name__ = (
        "StageCBuryReportLCB" if arm == "treatment"
        else "StageCBuryMatchedNullReportLCB")
    return StageCFocusedBuryReportLCB(seed)
