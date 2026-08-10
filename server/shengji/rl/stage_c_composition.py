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
    "focus_calls", "model_keeps", "model_triggers", "fallbacks",
    "report_overrides", "report_rejections", "report_underfills",
)


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
    if totals["model_triggers"] > totals["focus_calls"]:
        raise StageCCompositionError("Stage-C triggers exceed focus calls")
    # A zero-fallback evidence run has a closed decision tree. When a fallback
    # occurred, retain the raw counters so the future gate can reject the run;
    # an exception may have happened after a trigger and therefore overlap it.
    if totals["fallbacks"] == 0 and (
            totals["focus_calls"]
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
                          state_key: str) -> int:
    if not isinstance(state_key, str) or not state_key:
        raise StageCCompositionError("Stage-C composition state key drift")
    if len(candidates) <= 1:
        return 0
    identity = [list(action_key(candidate)) for candidate in candidates]
    digest = hashlib.sha256(
        ("teacher-stage-c-composition-null-v1|" + state_key + "|"
         + repr(identity)).encode()).digest()
    return 1 + int.from_bytes(digest[:16], "big") % (len(candidates) - 1)


def focused_pairs(
    ensemble: StageCEnsemble, rnd, seat: int,
    candidates: Sequence[Sequence[str]], *, state_key: str,
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
    triggered = model_index != 0
    null_index = (_matched_random_index(values, state_key=state_key)
                  if triggered else 0)
    treatment_indices = [0] if not triggered else [0, model_index]
    null_indices = [0] if not triggered else [0, null_index]
    result = {
        "schema": SCHEMA,
        "surface": surface,
        "head": ensemble.head,
        "epoch": ensemble.epoch,
        "state_key": state_key,
        "candidate_count": len(values),
        "candidate_keys": [list(action_key(value)) for value in values],
        "incumbent_index": 0,
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
    if (result["treatment_candidates"][0] != values[0]
            or result["null_candidates"][0] != values[0]
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


def make_play_report_lcb_bot(
    ensemble: StageCEnsemble, candidate_source: CandidateSource, *,
    arm: str, seed: int | None = None,
):
    """Wrap the exact live report-LCB bot with one focused play challenger.

    The source must construct the separately reviewed Stage-C candidate union.
    Any source/model/geometry failure falls back to the *entire* unchanged live
    ballot and is recorded; a whole-game evidence gate must require zero such
    fallbacks and nonzero model triggers. The learned action still must clear
    the base policy's fresh paired N=300 report LCB before it can be played.
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
            self.stage_c_focus_triggers = 0
            self.stage_c_focus_fallbacks = 0
            self.stage_c_model_keeps = 0
            self.stage_c_report_overrides = 0
            self.stage_c_report_rejections = 0
            self.stage_c_report_underfills = 0
            self.last_stage_c_focus_record = None
            self.policy_name = f"stage-c-play-{arm}"

        def _candidates(self, rnd, seat):
            live = [list(value) for value in super()._candidates(rnd, seat)]
            self.stage_c_focus_calls += 1
            try:
                union, source_record = candidate_source(self, rnd, seat, live)
                union = _candidate_union(union, "play")
                if action_key(union[0]) != action_key(live[0]):
                    raise StageCCompositionError(
                        "Stage-C union candidate zero differs from live")
                _validate_candidate_legality(rnd, seat, union, "play")
                state_key = _state_key(rnd, seat, union)
                record = focused_pairs(
                    ensemble, rnd, seat, union, state_key=state_key)
                if not isinstance(source_record, Mapping):
                    raise StageCCompositionError(
                        "Stage-C candidate-source record drift")
                record["candidate_source"] = dict(source_record)
                record["arm"] = arm
                record["fallback_to_live_ballot"] = False
                selected = (record["treatment_candidates"]
                            if arm == "treatment" else
                            record["null_candidates"])
                if record["model_triggered"]:
                    self.stage_c_focus_triggers += 1
                else:
                    self.stage_c_model_keeps += 1
                self.last_stage_c_focus_record = record
                return [list(value) for value in selected]
            except Exception as exc:
                self.stage_c_focus_fallbacks += 1
                self.last_stage_c_focus_record = {
                    "schema": SCHEMA,
                    "surface": "play",
                    "arm": arm,
                    "candidate_count": len(live),
                    "fallback_to_live_ballot": True,
                    "failure_type": type(exc).__name__,
                    "failure": str(exc),
                    "model_direct_override_authorized": False,
                    "fresh_paired_report_lcb_required": True,
                    "strength_claim": False,
                    "production_promotion": False,
                    "production_deployment": False,
                }
                return live

        def decide_play(self, rnd, seat):
            self.last_stage_c_focus_record = None
            played = super().decide_play(rnd, seat)
            if self.last_stage_c_focus_record is not None:
                self.last_stage_c_focus_record["played"] = list(played)
                decision = self.last_decision_record
                self.last_stage_c_focus_record["report_lcb_decision"] = (
                    None if decision is None else {
                        "reason": decision.get("reason"),
                        "played_index": decision.get("played_index"),
                        "report_fold": decision.get("report_fold"),
                        "work": decision.get("work"),
                    })
                record = self.last_stage_c_focus_record
                if (not record.get("fallback_to_live_ballot")
                        and record.get("model_triggered")):
                    reason = (None if decision is None
                              else decision.get("reason"))
                    if reason == "report_lcb_override":
                        self.stage_c_report_overrides += 1
                    elif reason == "report_lcb_below_min_gain":
                        self.stage_c_report_rejections += 1
                    else:
                        self.stage_c_report_underfills += 1
            return played

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
