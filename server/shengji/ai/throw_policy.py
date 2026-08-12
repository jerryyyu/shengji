"""Experiment-only S6 root-ballot treatment and compute-matched null.

Both arms generate and score the exact same widened ballot.  The treatment may
select a structured shuai-pai proposal; the matched null excludes those added
indices from selection while still paying their candidate-rollout cost.  On an
identical state and RNG stream, the null must therefore make the same move as
the live ``mc-s0-report-lcb`` champion.

This module registers no production policy.  A separately reviewed runner must
construct the arms explicitly and prove null/champion outcome identity before
interpreting a strength contrast.
"""
from __future__ import annotations

from collections import Counter
from functools import lru_cache

from ..engine.combos import decompose
from ..engine.round import Round
from .throw_sourcing import (StructuredThrowBallot, structured_throw_ballot,
                             union_with_live_ballot)


S6_THROW_POLICIES = {
    "base": "mc-s0-report-lcb",
    "treatment": "mc-s0-report-lcb-s6-throw-source",
    "matched_null": "mc-s0-report-lcb-s6-throw-source-null",
}

S6_THROW_COUNTER_FIELDS = (
    "play_calls",
    "lead_calls",
    "eligible_leads",
    "source_candidates",
    "new_candidate_triggers",
    "new_candidates",
    "searched_triggers",
    "tractor_lock_skips",
    "tractor_lock_bypasses",
    "treatment_overrides",
    "matched_noops",
    "attacker_triggers",
    "defender_triggers",
    "base_candidate_count",
    "widened_candidate_count",
    "short_searches",
)


def empty_s6_throw_telemetry(mode: str = "off") -> dict[str, object]:
    """Canonical zero-dose telemetry for the feature-off champion."""
    return {
        "schema": "s6-throw-source-cumulative-telemetry-v1",
        "mode": mode,
        "deterministic_source": True,
        "exact_work_complete": True,
        **{field: 0 for field in S6_THROW_COUNTER_FIELDS},
    }


def _action_key(cards) -> tuple[str, ...]:
    return tuple(sorted(cards))


@lru_cache(maxsize=1)
def _experiment_bot_class(base_cls):
    """Wrap the exact champion class without editing its registered contract."""

    class S6ThrowExperimentBot(base_cls):
        def __init__(self, seed: int | None = None, *, apply_treatment: bool):
            base_cls.__init__(self, seed=seed)
            self.apply_s6_throw_treatment = bool(apply_treatment)
            self._s6_throw_totals = Counter(
                {field: 0 for field in S6_THROW_COUNTER_FIELDS})
            self._s6_precomputed_base: list[list[str]] | None = None
            self._s6_precomputed_ballot: StructuredThrowBallot | None = None
            self._s6_context: dict[str, object] | None = None
            self._s6_lock_bypass = False
            self.last_s6_throw_record: dict[str, object] | None = None

        @property
        def s6_throw_mode(self) -> str:
            return ("treatment" if self.apply_s6_throw_treatment
                    else "matched_null")

        def _candidates(self, rnd: Round, seat: int) -> list[list[str]]:
            base = self._s6_precomputed_base
            if base is None:
                base = base_cls._candidates(self, rnd, seat)
            else:
                base = [list(candidate) for candidate in base]
            ballot = self._s6_precomputed_ballot
            if ballot is None:
                ballot = structured_throw_ballot(rnd, seat)
            widened = union_with_live_ballot(base, ballot)
            base_keys = {_action_key(candidate) for candidate in base}
            added_indices = tuple(
                index for index, candidate in enumerate(widened)
                if _action_key(candidate) not in base_keys
            )
            if added_indices != tuple(range(len(base), len(widened))):
                raise AssertionError("S6 union is not a literal append-only suffix")
            self._s6_context = {
                "base_candidates": tuple(tuple(candidate) for candidate in base),
                "base_count": len(base),
                "widened_candidates": tuple(
                    tuple(candidate) for candidate in widened),
                "added_indices": added_indices,
                "added_keys": tuple(
                    _action_key(widened[index]) for index in added_indices),
                "ballot": ballot,
                "tractor_lock_bypass": self._s6_lock_bypass,
            }
            return widened

        def _pick_index(self, candidates, means, indices):
            context = self._s6_context
            if context is None:
                return base_cls._pick_index(self, candidates, means, indices)
            base_count = int(context["base_count"])
            added_indices = set(context["added_indices"])
            if context["tractor_lock_bypass"]:
                if self.apply_s6_throw_treatment:
                    allowed = [index for index in indices
                               if index == 0 or index in added_indices]
                    if not allowed:
                        raise AssertionError(
                            "S6 tractor-lock treatment lost every S6 index")
                    return base_cls._pick_index(
                        self, candidates, means, allowed)
                incumbent = [index for index in indices if index == 0]
                if incumbent:
                    return 0
                dummy = [index for index in indices if index in added_indices]
                if dummy:
                    return base_cls._pick_index(
                        self, candidates, means, dummy)
                raise AssertionError(
                    "S6 tractor-lock null lost its dummy report challenger")
            if self.apply_s6_throw_treatment:
                return base_cls._pick_index(self, candidates, means, indices)
            base_indices = [index for index in indices if index < base_count]
            if base_indices:
                return base_cls._pick_index(
                    self, candidates, means, base_indices)
            # If the incumbent ballot had only candidate zero, the champion
            # would return it without search.  The null nevertheless needs a
            # report challenger to spend the treatment's fixed report work.
            # ``decide_play`` restores the champion RNG state and action after
            # this dummy measurement.
            if base_count == 1 and indices:
                return base_cls._pick_index(self, candidates, means, indices)
            raise AssertionError("S6 matched null lost every incumbent index")

        def decide_play(self, rnd: Round, seat: int) -> list[str]:
            self.last_s6_throw_record = None
            self._s6_context = None
            self._s6_precomputed_base = None
            self._s6_precomputed_ballot = None
            self._s6_lock_bypass = False
            pre_rng_state = self.rng.getstate()
            is_lead = bool(rnd.trick is not None and not rnd.trick.plays)

            # Precompute the deterministic source on leads.  Besides avoiding a
            # duplicate source pass, this exposes opportunities hidden behind
            # the champion's intentional tractor-lock early return.
            if is_lead:
                self._s6_precomputed_base = base_cls._candidates(self, rnd, seat)
                self._s6_precomputed_ballot = structured_throw_ballot(rnd, seat)

                widened = union_with_live_ballot(
                    self._s6_precomputed_base, self._s6_precomputed_ballot)
                base_keys = {_action_key(candidate)
                             for candidate in self._s6_precomputed_base}
                has_new_s6 = any(
                    _action_key(candidate) not in base_keys
                    for candidate in widened)
                incumbent_dec = decompose(
                    list(self._s6_precomputed_base[0]), rnd.ordering)
                incumbent_is_locked_tractor = (
                    self.TRACTOR_LOCK
                    and len(incumbent_dec.components) == 1
                    and incumbent_dec.components[0].pair_len >= 2)
                self._s6_lock_bypass = bool(
                    has_new_s6 and incumbent_is_locked_tractor)

            had_instance_lock = "TRACTOR_LOCK" in self.__dict__
            original_instance_lock = self.__dict__.get("TRACTOR_LOCK")
            if self._s6_lock_bypass:
                self.TRACTOR_LOCK = False
            try:
                played = base_cls.decide_play(self, rnd, seat)
            finally:
                self._s6_precomputed_base = None
                self._s6_precomputed_ballot = None
                if self._s6_lock_bypass:
                    if had_instance_lock:
                        self.TRACTOR_LOCK = original_instance_lock
                    else:
                        del self.TRACTOR_LOCK

            ballot = (self._s6_context["ballot"]
                      if self._s6_context is not None
                      else structured_throw_ballot(rnd, seat)
                      if is_lead else None)
            base_candidates = (
                list(self._s6_context["base_candidates"])
                if self._s6_context is not None else [])
            added_indices = (
                tuple(self._s6_context["added_indices"])
                if self._s6_context is not None else ())
            added_keys = (
                set(self._s6_context["added_keys"])
                if self._s6_context is not None else set())

            if is_lead and self._s6_context is None:
                # Tractor lock returned before candidate generation.  Rebuild
                # only the append-only identity from the already computed
                # deterministic inputs; do not run any search or mutate RNG.
                base_candidates = [list(candidate) for candidate in
                                   base_cls._candidates(self, rnd, seat)]
                assert ballot is not None
                widened = union_with_live_ballot(base_candidates, ballot)
                base_keys = {_action_key(candidate)
                             for candidate in base_candidates}
                added_indices = tuple(
                    index for index, candidate in enumerate(widened)
                    if _action_key(candidate) not in base_keys)
                added_keys = {_action_key(widened[index])
                              for index in added_indices}

            trigger = bool(added_indices)
            searched = bool(trigger and self._s6_context is not None)
            locked = bool(trigger and self._s6_context is None)
            lock_bypass = bool(
                searched and self._s6_context["tractor_lock_bypass"])
            played_key = _action_key(played)
            override = bool(searched and played_key in added_keys)

            # A one-candidate incumbent consumed no champion RNG.  The null's
            # dummy widened search is work-only, so restore the untouched
            # stream and literal incumbent action after recording it.
            forced_null_incumbent = False
            if (not self.apply_s6_throw_treatment and searched
                    and (len(base_candidates) == 1 or lock_bypass)):
                self.rng.setstate(pre_rng_state)
                played = list(base_candidates[0])
                played_key = _action_key(played)
                override = False
                forced_null_incumbent = True
                if self.last_decision_record is not None:
                    self.last_decision_record["played_index"] = 0
                    self.last_decision_record["played"] = list(played)
                    self.last_decision_record["reason"] = \
                        "s6_matched_null_single_incumbent"

            if not self.apply_s6_throw_treatment and override:
                raise AssertionError("S6 matched null selected a sourced action")
            if (not self.apply_s6_throw_treatment and searched
                    and played_key not in {_action_key(c)
                                           for c in base_candidates}):
                raise AssertionError("S6 matched null changed incumbent action set")

            short = bool(
                searched and self.last_decision_record is not None
                and not self.last_decision_record.get("work", {}).get(
                    "complete", False))
            record = {
                "schema": "s6-throw-source-decision-v1",
                "mode": self.s6_throw_mode,
                "lead": is_lead,
                "eligible": bool(ballot and ballot.eligible_suits),
                "ballot": ballot.record() if ballot is not None else None,
                "base_candidate_count": len(base_candidates),
                "widened_candidate_count": (
                    len(self._s6_context["widened_candidates"])
                    if self._s6_context is not None else
                    len(base_candidates) + len(added_indices)),
                "added_indices": list(added_indices),
                "trigger": trigger,
                "searched": searched,
                "tractor_lock_skip": locked,
                "tractor_lock_bypass": lock_bypass,
                "treatment_override": override,
                "matched_noop": bool(
                    searched and not self.apply_s6_throw_treatment),
                "forced_null_incumbent": forced_null_incumbent,
                "played": list(played),
                "exact_work_complete": not short,
            }
            self.last_s6_throw_record = record
            if self.last_decision_record is not None:
                self.last_decision_record["s6_throw_sourcing"] = record
            self._record_s6_throw(record, rnd, seat)
            return played

        def _record_s6_throw(self, record: dict[str, object],
                             rnd: Round, seat: int) -> None:
            totals = self._s6_throw_totals
            totals["play_calls"] += 1
            if not record["lead"]:
                return
            totals["lead_calls"] += 1
            ballot = record["ballot"]
            if record["eligible"]:
                totals["eligible_leads"] += 1
            totals["source_candidates"] += len(ballot["candidates"])
            totals["base_candidate_count"] += record["base_candidate_count"]
            totals["widened_candidate_count"] += \
                record["widened_candidate_count"]
            if record["trigger"]:
                totals["new_candidate_triggers"] += 1
                totals["new_candidates"] += len(record["added_indices"])
            if record["searched"]:
                totals["searched_triggers"] += 1
                role = ("attacker_triggers" if rnd.is_attacker(seat)
                        else "defender_triggers")
                totals[role] += 1
            if record["tractor_lock_skip"]:
                totals["tractor_lock_skips"] += 1
            if record["tractor_lock_bypass"]:
                totals["tractor_lock_bypasses"] += 1
            if record["treatment_override"]:
                totals["treatment_overrides"] += 1
            if record["matched_noop"]:
                totals["matched_noops"] += 1
            if not record["exact_work_complete"]:
                totals["short_searches"] += 1
            self.s6_throw_telemetry()

        def s6_throw_telemetry(self) -> dict[str, object]:
            values = {field: int(self._s6_throw_totals[field])
                      for field in S6_THROW_COUNTER_FIELDS}
            if any(value < 0 for value in values.values()):
                raise AssertionError("S6 telemetry has a negative counter")
            if values["eligible_leads"] > values["lead_calls"] \
                    or values["lead_calls"] > values["play_calls"]:
                raise AssertionError("S6 lead accounting does not reconcile")
            if values["new_candidate_triggers"] != (
                    values["searched_triggers"]
                    + values["tractor_lock_skips"]):
                raise AssertionError("S6 trigger paths do not reconcile")
            if values["searched_triggers"] != (
                    values["attacker_triggers"]
                    + values["defender_triggers"]):
                raise AssertionError("S6 role counters do not reconcile")
            if values["tractor_lock_bypasses"] > values["searched_triggers"]:
                raise AssertionError("S6 tractor bypasses exceed searches")
            if values["new_candidates"] < values["new_candidate_triggers"]:
                raise AssertionError("S6 candidate additions do not reconcile")
            if values["source_candidates"] < values["new_candidates"]:
                raise AssertionError("S6 additions exceed sourced candidates")
            if values["base_candidate_count"] > \
                    values["widened_candidate_count"]:
                raise AssertionError("S6 widened ballot shrank the incumbent")
            if values["treatment_overrides"] > values["searched_triggers"]:
                raise AssertionError("S6 overrides exceed searched triggers")
            if self.apply_s6_throw_treatment:
                if values["matched_noops"]:
                    raise AssertionError("S6 treatment recorded null noops")
            else:
                if values["treatment_overrides"]:
                    raise AssertionError("S6 null recorded a treatment override")
                if values["matched_noops"] != values["searched_triggers"]:
                    raise AssertionError("S6 null dose does not reconcile")
            return {
                "schema": "s6-throw-source-cumulative-telemetry-v1",
                "mode": self.s6_throw_mode,
                "deterministic_source": True,
                "exact_work_complete": values["short_searches"] == 0,
                **values,
            }

    S6ThrowExperimentBot.__name__ = "S6ThrowMCS0ReportLCB"
    S6ThrowExperimentBot.__qualname__ = "S6ThrowMCS0ReportLCB"
    return S6ThrowExperimentBot


def make_s6_throw_bot(*, treatment: bool, seed: int | None = None):
    """Construct the exact live champion with only the S6 root source added."""
    from .registry import make_bot

    base_policy = S6_THROW_POLICIES["base"]
    base = make_bot(base_policy, seed=seed)
    if any(getattr(base, field, False) for field in
           ("MC_BURY", "STRUCTURED_BURY", "EXACT_ENDGAME")):
        raise RuntimeError(
            f"S6 base policy {base_policy!r} enables another S3 feature")
    cls = _experiment_bot_class(type(base))
    bot = cls(seed=seed, apply_treatment=treatment)
    bot.policy_name = S6_THROW_POLICIES[
        "treatment" if treatment else "matched_null"]
    bot.s6_throw_base_policy = base_policy
    return bot
