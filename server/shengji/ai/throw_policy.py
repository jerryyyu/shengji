"""Experiment-only S6 champion-anchored treatment and compute-matched null.

Both arms first execute the literal live ``mc-s0-report-lcb`` decision.  When
the source contributes a genuinely new shuai-pai action, both then run the
same second report-LCB probe: exact champion action as candidate zero versus
only the new S6 suffix.  Both restore the champion's post-decision RNG state;
the treatment may use the probe's action while the null always keeps the
champion action.  Thus the null is behaviourally and RNG-identical to the
champion while paying the same extra S6 work as treatment.

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
            self._s6_secondary_candidates: list[list[str]] | None = None
            self.last_s6_throw_record: dict[str, object] | None = None

        @property
        def s6_throw_mode(self) -> str:
            return ("treatment" if self.apply_s6_throw_treatment
                    else "matched_null")

        def _source_plan(self, rnd: Round, seat: int) -> dict[str, object]:
            """Freeze the live ballot and its literal S6-only suffix."""
            base = [list(candidate)
                    for candidate in base_cls._candidates(self, rnd, seat)]
            ballot = structured_throw_ballot(rnd, seat)
            widened = union_with_live_ballot(base, ballot)
            base_keys = {_action_key(candidate) for candidate in base}
            added_indices = tuple(
                index for index, candidate in enumerate(widened)
                if _action_key(candidate) not in base_keys
            )
            if added_indices != tuple(range(len(base), len(widened))):
                raise AssertionError("S6 union is not a literal append-only suffix")
            return {
                "base_candidates": tuple(tuple(candidate) for candidate in base),
                "base_count": len(base),
                "widened_candidates": tuple(
                    tuple(candidate) for candidate in widened),
                "added_indices": added_indices,
                "added_keys": tuple(
                    _action_key(widened[index]) for index in added_indices),
                "ballot": ballot,
            }

        def _candidates(self, rnd: Round, seat: int) -> list[list[str]]:
            # The first pass is the literal live champion.  Only the second,
            # work-matched probe substitutes candidate zero = the action that
            # champion actually chose and appends the genuinely new S6 moves.
            # This prevents extra candidates from perturbing the champion's
            # adaptive allocation before an S6 comparison even begins.
            if self._s6_secondary_candidates is not None:
                return [list(candidate)
                        for candidate in self._s6_secondary_candidates]
            return base_cls._candidates(self, rnd, seat)

        def _pick_index(self, candidates, means, indices):
            return base_cls._pick_index(self, candidates, means, indices)

        def decide_play(self, rnd: Round, seat: int) -> list[str]:
            self.last_s6_throw_record = None
            self._s6_secondary_candidates = None
            is_lead = bool(rnd.trick is not None and not rnd.trick.plays)
            if not is_lead:
                played = base_cls.decide_play(self, rnd, seat)
                record = {
                    "schema": "s6-throw-source-decision-v2",
                    "mode": self.s6_throw_mode,
                    "lead": False, "eligible": False, "ballot": None,
                    "base_candidate_count": 0,
                    "widened_candidate_count": 0,
                    "secondary_candidate_count": 0,
                    "added_indices": [], "trigger": False,
                    "searched": False, "tractor_lock_skip": False,
                    "tractor_lock_bypass": False,
                    "treatment_override": False,
                    "matched_noop": False,
                    "forced_null_incumbent": False,
                    "played": list(played), "exact_work_complete": True,
                }
                self.last_s6_throw_record = record
                if self.last_decision_record is not None:
                    self.last_decision_record["s6_throw_sourcing"] = record
                self._record_s6_throw(record, rnd, seat)
                return played

            plan = self._source_plan(rnd, seat)
            base_candidates = [list(candidate)
                               for candidate in plan["base_candidates"]]
            ballot = plan["ballot"]
            added_indices = tuple(plan["added_indices"])
            additions = [list(plan["widened_candidates"][index])
                         for index in added_indices]
            added_keys = set(plan["added_keys"])

            # Pass one is literally the live champion, including its adaptive
            # selection, report fold, tractor lock, action and RNG transition.
            champion_play = base_cls.decide_play(self, rnd, seat)
            champion_record = self.last_decision_record
            champion_post_rng = self.rng.getstate()
            base_keys = {_action_key(candidate) for candidate in base_candidates}
            if _action_key(champion_play) not in base_keys:
                raise AssertionError("S6 champion action escaped its frozen ballot")
            if (champion_record is not None
                    and champion_record.get("candidates") != base_candidates):
                raise AssertionError("S6 champion ballot changed between passes")
            trigger = bool(additions)
            if not trigger:
                record = {
                    "schema": "s6-throw-source-decision-v2",
                    "mode": self.s6_throw_mode, "lead": True,
                    "eligible": bool(ballot.eligible_suits),
                    "ballot": ballot.record(),
                    "base_candidate_count": len(base_candidates),
                    "widened_candidate_count": len(base_candidates),
                    "secondary_candidate_count": 0,
                    "added_indices": [], "trigger": False,
                    "searched": False, "tractor_lock_skip": False,
                    "tractor_lock_bypass": False,
                    "treatment_override": False,
                    "matched_noop": False,
                    "forced_null_incumbent": False,
                    "played": list(champion_play),
                    "exact_work_complete": True,
                }
                self.last_s6_throw_record = record
                if champion_record is not None:
                    champion_record["s6_throw_sourcing"] = record
                self._record_s6_throw(record, rnd, seat)
                return champion_play

            incumbent_dec = decompose(list(champion_play), rnd.ordering)
            lock_bypass = bool(
                self.TRACTOR_LOCK and champion_record is None
                and len(incumbent_dec.components) == 1
                and incumbent_dec.components[0].pair_len >= 2)

            # Pass two is a work-identical probe in both arms: exact champion
            # action as candidate zero versus only the genuinely new S6 suffix.
            # Restore the champion's post-decision RNG afterwards in both arms,
            # so the experiment changes an action—not the future random stream.
            self._s6_secondary_candidates = [list(champion_play), *additions]
            had_instance_lock = "TRACTOR_LOCK" in self.__dict__
            original_instance_lock = self.__dict__.get("TRACTOR_LOCK")
            self.TRACTOR_LOCK = False
            try:
                probe_play = base_cls.decide_play(self, rnd, seat)
                probe_record = self.last_decision_record
            finally:
                self._s6_secondary_candidates = None
                if had_instance_lock:
                    self.TRACTOR_LOCK = original_instance_lock
                else:
                    del self.TRACTOR_LOCK
                self.rng.setstate(champion_post_rng)
            if probe_record is None:
                raise AssertionError("S6 multi-candidate probe produced no record")

            probe_override = _action_key(probe_play) in added_keys
            if (_action_key(probe_play) != _action_key(champion_play)
                    and not probe_override):
                raise AssertionError("S6 probe escaped champion-plus-suffix ballot")
            played = (list(probe_play) if self.apply_s6_throw_treatment
                      else list(champion_play))
            override = bool(self.apply_s6_throw_treatment and probe_override)
            primary_complete = bool(
                champion_record is None
                or champion_record.get("work", {}).get("complete", False))
            probe_complete = bool(
                probe_record.get("work", {}).get("complete", False))
            short = not (primary_complete and probe_complete)

            probe_record["s6_incumbent_decision"] = champion_record
            probe_record["s6_probe_played"] = list(probe_play)
            probe_record["s6_probe_reason"] = probe_record.get("reason")
            if not self.apply_s6_throw_treatment:
                probe_record["played_index"] = 0
                probe_record["played"] = list(champion_play)
                probe_record["reason"] = "s6_matched_null_after_equal_probe"
            self.last_decision_record = probe_record
            record = {
                "schema": "s6-throw-source-decision-v2",
                "mode": self.s6_throw_mode,
                "lead": True,
                "eligible": bool(ballot.eligible_suits),
                "ballot": ballot.record(),
                "base_candidate_count": len(base_candidates),
                "widened_candidate_count": len(plan["widened_candidates"]),
                "secondary_candidate_count": 1 + len(additions),
                "added_indices": list(added_indices),
                "trigger": True,
                "searched": True,
                "tractor_lock_skip": False,
                "tractor_lock_bypass": lock_bypass,
                "treatment_override": override,
                "matched_noop": not self.apply_s6_throw_treatment,
                "forced_null_incumbent": not self.apply_s6_throw_treatment,
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
