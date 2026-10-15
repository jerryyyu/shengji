"""Bounded, allowlisted view of one isolated play evaluation, not replay data.

Two decision records reach the overlay: the CWV shortlist bot's
(``last_eval`` + ``cwv_shortlist`` / ``report_fold``) and the pv-search bot's
(``pv-search-decision-v1``: the admitted candidates with their value means and
policy log-odds, plus one block per optional rule that ran, holding only that
rule's listed fields).  The
served bot writes the second; a record of neither shape is a forced play or a
bot without search.
"""
from __future__ import annotations

import math

MAX_CANDIDATES = 32
PV_SCHEMA = "pv-search-decision-v1"
PV_FALLBACK_SCHEMA = "pv-search-fallback-v1"
#: the optional rules of a pv-search record: for each rule, the exact fields the
#: overlay may show.  Only a name on this list reaches the browser, and only as
#: a bounded scalar or a short scalar list (``_scalar``); an unlisted field --
#: a sampled world, a hand, an RNG state, an exception text -- is dropped even
#: when its shape would fit.  The exact-lead / exact-follow names cover the
#: endgame stages so their decisions show once those rules are served.
PV_STAGES = {
    "tiebreak": (
        "tiebreak_applied", "tiebreak_abandoned", "tiebreak_near_set", "tiebreak_points"),
    "lead_tiebreak": (
        "lead_tiebreak_leading", "lead_tiebreak_applied", "lead_tiebreak_superseded",
        "lead_tiebreak_near_count", "lead_tiebreak_from_index", "lead_tiebreak_to_index",
        "lead_tiebreak_from", "lead_tiebreak_to", "lead_tiebreak_value_gap"),
    "lead_anchor": (
        "lead_anchor_applied", "lead_anchor_from", "lead_anchor_to", "lead_anchor_source"),
    "doomed_throw_swap": (
        "doomed_throw_swap_applied", "doomed_throw_swap_abandoned", "doomed_throw_swap_from",
        "doomed_throw_swap_to", "doomed_throw_swap_worlds", "doomed_throw_swap_refused_worlds",
        "doomed_throw_swap_forced_variants"),
    "doomed_throw_reselect": (
        "doomed_throw_reselect_applied", "doomed_throw_reselect_abandoned",
        "doomed_throw_reselect_from", "doomed_throw_reselect_to",
        "doomed_throw_reselect_doomed_candidates", "doomed_throw_reselect_forced_excluded",
        "doomed_throw_reselect_fallback_forced"),
    "adaptive_worlds": (
        "adaptive_worlds_triggered", "adaptive_worlds_changed", "adaptive_worlds_played_changed",
        "adaptive_worlds_abandoned", "adaptive_worlds_skipped_budget",
        "adaptive_worlds_sampler_advanced", "adaptive_worlds_total", "adaptive_worlds_margin",
        "adaptive_worlds_se", "adaptive_worlds_base_seconds"),
    "exact_lead": (
        "exact_lead_status", "exact_lead_changed", "exact_lead_change_kind",
        "exact_lead_worlds_completed", "exact_lead_nodes", "exact_lead_cache_hits",
        "exact_lead_seconds", "exact_lead_means", "exact_lead_selected_level_mean",
        "exact_lead_selected_level_delta", "exact_lead_base_level_mean",
        "exact_lead_base_selected_index", "exact_lead_base_played", "exact_lead_base_value_means",
        "exact_lead_abandon_reason", "exact_lead_first_trick", "exact_lead_policy_plays",
        "exact_lead_policy_forced", "exact_lead_policy_fallbacks", "exact_lead_policy_batches",
        "exact_lead_policy_views", "exact_lead_policy_view_worlds",
        "exact_lead_tie_baseline_kept", "exact_lead_tie_baseline_exact_index",
        "exact_deep_cards"),
    "exact_follow": (
        "exact_follow_attempted", "exact_follow_applied", "exact_follow_abandoned",
        "exact_follow_worlds", "exact_follow_nodes", "exact_follow_scores"),
    "refusal": (
        "refusal_observations", "refusal_rejections", "refusal_fallback_worlds",
        "refusal_pinned_codes"),
    "small_joker": (
        "small_joker_guard_active", "small_joker_guard_anchor_replaced",
        "small_joker_guard_anchor_to", "small_joker_guard_big_jokers_out",
        "small_joker_guard_other_trumps"),
    "wide_lead": ("wide_lead_admission_applied", "wide_lead_admission_k"),
}
#: the sampler's per-decision counter deltas (`PVSearchBot.decide_play`)
PV_SAMPLING_DELTAS = ("impossible_worlds_delta", "rejected_worlds_delta")
#: the record flags that say a rule changed or extended this decision
PV_APPLIED_FLAGS = (
    "tiebreak_applied", "lead_tiebreak_applied", "lead_anchor_applied",
    "doomed_throw_swap_applied", "doomed_throw_reselect_applied",
    "adaptive_worlds_triggered", "exact_lead_changed", "exact_follow_applied",
    "wide_lead_admission_applied", "adaptive_k_applied",
)
MAX_TEXT = 100
MAX_LIST = 64
_OMIT = object()


def _number(value):
    return value if isinstance(value, (int, float)) and math.isfinite(value) else None


def _fields(source, names):
    return {k: _number(source[k]) for k in names if k in source}


def _scalar(value):
    """A browser-safe copy of one record value, or ``_OMIT`` for any shape that
    could carry a world, a hand or an unbounded listing."""
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return _number(value)
    if isinstance(value, str):
        return value[:MAX_TEXT]
    if isinstance(value, (list, tuple)) and len(value) <= MAX_LIST \
            and all(v is None or isinstance(v, (bool, int, float, str)) for v in value):
        return [_scalar(v) for v in value]
    return _OMIT


def _listed(rec, names):
    """The named record fields that are present and browser-safe."""
    block = {}
    for key in names:
        if key in rec:
            safe = _scalar(rec[key])
            if safe is not _OMIT:
                block[key] = safe
    return block


def _model_identity(bot):
    evaluator = getattr(bot, "evaluator", None)
    if evaluator is None:
        return None
    identity = evaluator.identity()
    model = {k: identity.get(k) for k in (
        "backend", "checkpoint_sha256", "source_checkpoint_sha256", "encoding",
        "effective_encoding", "max_batch", "device")}
    model["encoder_version"] = _number(getattr(evaluator, "enc_version", None))
    return model


def _pv_play_analysis(bot, pick, rec, *, elapsed):
    admitted = [list(c) for c in rec.get("admitted") or []]
    means = rec.get("value_means") or []
    odds = rec.get("policy_log_odds_admitted") or []
    indices = list(rec.get("admitted_indices") or [])
    selected = rec.get("selected_index")
    selected_pos = indices.index(selected) if selected in indices else None
    chosen_key = tuple(sorted(pick))
    anchor_replaced = rec.get("lead_anchor_applied") is True
    worlds = _number(rec.get("worlds"))
    rows = []
    for i, cards in enumerate(admitted[:MAX_CANDIDATES]):
        key = tuple(sorted(cards))
        level = _number(means[i]) if i < len(means) else None
        rows.append({
            "index": i, "play": cards,
            # the value head's units; the same number under both names so the
            # shortlist-era column and the pv column read it
            "acting_team_levels": level, "model_score": level,
            "policy_log_odds": _number(odds[i]) if i < len(odds) else None,
            "attackers_avg": None, "se": None, "paired_se_vs_incumbent": None,
            "selection_worlds": worlds,
            "old_ballot": None,
            "anchor": i == 0,
            "heuristic_pick": i == 0 and not anchor_replaced,
            "model_nominated": i != 0,
            "report_finalist": False,
            "selected": i == selected_pos,
            "bot_plays": key == chosen_key,
        })
    if chosen_key not in {tuple(sorted(c)) for c in admitted}:
        # a doomed-throw rule played the selected candidate's forced component
        rows.append({
            "index": None, "play": list(pick),
            "acting_team_levels": None, "model_score": None, "policy_log_odds": None,
            "attackers_avg": None, "se": None, "paired_se_vs_incumbent": None,
            "selection_worlds": worlds, "old_ballot": None,
            "anchor": False, "heuristic_pick": False, "model_nominated": False,
            "report_finalist": False, "selected": False, "bot_plays": True,
            "forced_component": True,
        })
    stages = {}
    for name, fields in PV_STAGES.items():
        block = _listed(rec, fields)
        if block:
            stages[name] = block
    sampling = _fields(rec, ("worlds", "sample_attempts") + PV_SAMPLING_DELTAS)
    admission = {
        **_fields(rec, ("legal_count", "actions", "k_used")),
        "legal_complete": rec.get("legal_complete"),
        "admitted": len(admitted),
        "adaptive_k_applied": rec.get("adaptive_k_applied"),
        "diversity_skipped": len(rec.get("diversity_skipped") or []),
        "forced_single_added": len(rec.get("forced_single_added") or []),
        "finish_lead_admission_added": rec.get("finish_lead_admission_added"),
    }
    # a rule that is off leaves no field; the view does not invent one
    admission = {k: v for k, v in admission.items() if v is not None}
    return rows, {
        "source": "isolated_current_state_replay", "historical_decision": False,
        "schema": PV_SCHEMA,
        "policy": str(getattr(bot, "policy_name", type(bot).__name__))[:160],
        "reason": "pv_search",
        "applied_rules": [name for name in PV_APPLIED_FLAGS if rec.get(name) is True],
        "anchor_selected": rec.get("anchor_selected"),
        "selected_index": selected_pos,
        "work_complete": rec.get("work_complete"),
        "model": _model_identity(bot),
        "model_score_units": "expected signed levels for acting team",
        "selection_score_units": "expected signed levels for acting team",
        "report": None,
        "recipe": {"worlds": worlds, "alternatives": len(admitted),
                   "cap": _number(rec.get("cap")),
                   "serving_budget_seconds": _number(getattr(bot, "serving_budget_seconds", None)),
                   "encoder_version": _number(rec.get("encoder_version"))},
        "sampling": sampling,
        "admission": admission,
        "stages": stages,
        "work": {**_fields(rec, ("value_evaluations", "value_batches")), "worlds": worlds},
        "search_seconds": _number(rec.get("seconds")),
        "evaluation_seconds": elapsed,
        "candidate_count": len(admitted), "candidates_truncated": len(admitted) > MAX_CANDIDATES,
    }


def _pv_fallback_analysis(bot, pick, rec, *, elapsed):
    rows = [{
        "index": 0, "play": list(pick),
        "acting_team_levels": None, "model_score": None, "policy_log_odds": None,
        "attackers_avg": None, "se": None, "paired_se_vs_incumbent": None,
        "selection_worlds": None, "old_ballot": None,
        "anchor": True, "heuristic_pick": True, "model_nominated": False,
        "report_finalist": False, "selected": True, "bot_plays": True,
    }]
    return rows, {
        "source": "isolated_current_state_replay", "historical_decision": False,
        "schema": PV_FALLBACK_SCHEMA,
        "policy": str(getattr(bot, "policy_name", type(bot).__name__))[:160],
        "reason": str(rec.get("reason", "fallback"))[:MAX_TEXT],
        "applied_rules": [],
        "anchor_selected": True, "selected_index": 0,
        "work_complete": rec.get("work_complete"),
        "fallback": {"error_class": str(rec.get("error_class") or "")[:MAX_TEXT],
                     "error_stage": str(rec.get("error_stage") or "")[:MAX_TEXT],
                     "budget_seconds": _number(rec.get("budget_seconds"))},
        "model": _model_identity(bot),
        "model_score_units": "expected signed levels for acting team",
        "selection_score_units": "expected signed levels for acting team",
        "report": None,
        "recipe": {"serving_budget_seconds": _number(rec.get("budget_seconds"))},
        "sampling": {}, "admission": {}, "stages": {}, "work": {},
        "search_seconds": _number(rec.get("elapsed_seconds")),
        "evaluation_seconds": elapsed,
        "candidate_count": 1, "candidates_truncated": False,
    }


def play_analysis(bot, pick, *, is_attacker, elapsed):
    rec = getattr(bot, "last_decision_record", None) or {}
    schema = rec.get("schema")
    if schema == PV_SCHEMA:
        return _pv_play_analysis(bot, pick, rec, elapsed=elapsed)
    if schema == PV_FALLBACK_SCHEMA:
        return _pv_fallback_analysis(bot, pick, rec, elapsed=elapsed)
    shortlist = rec.get("cwv_shortlist") or {}
    evaluation = getattr(bot, "last_eval", None)
    candidates, means = evaluation if evaluation is not None else ([pick], [None])
    chosen_key = tuple(sorted(pick))
    # Keep the incumbent and actual finalists even if a future policy has a
    # large ballot. Never serialize the exhaustive legal set or sampled worlds.
    priorities = [0, rec.get("report_candidate_index"), rec.get("played_index")]
    priorities += [i for i, c in enumerate(candidates) if tuple(sorted(c)) == chosen_key]
    indices = []
    for i in priorities + list(range(min(len(candidates), MAX_CANDIDATES))):
        if isinstance(i, int) and 0 <= i < len(candidates) and i not in indices:
            indices.append(i)
        if len(indices) == MAX_CANDIDATES:
            break
    model_scores = dict(zip(
        (tuple(sorted(c)) for c in shortlist.get("shortlist", [])),
        shortlist.get("shortlist_means") or []))
    old_ballot = {tuple(sorted(c)) for c in shortlist.get("production_keys", [])}
    selection_levels = (rec.get("alloc", {}).get("selection_units")
                        == "acting-team-signed-level")
    def at(name, i):
        values = rec.get(name) or []
        return _number(values[i]) if i < len(values) else None
    rows = []
    for i in indices:
        key = tuple(sorted(candidates[i]))
        mean = _number(means[i]) if i < len(means) else None
        rows.append({
            "index": i, "play": list(candidates[i]),
            "attackers_avg": None if mean is None or selection_levels else mean * (1 if is_attacker else -1),
            "se": None,  # Individual-mean uncertainty is not retained.
            "paired_se_vs_incumbent": at("paired_se", i),
            "selection_worlds": at("n_by_candidate", i),
            "model_score": _number(model_scores.get(key)),
            "old_ballot": key in old_ballot if shortlist else None,
            "model_nominated": i != 0 and key in model_scores and not shortlist.get("config", {}).get("uniform", False),
            "heuristic_pick": i == 0 and evaluation is not None,
            "report_finalist": bool(rec.get("report_fold")) and i in (0, rec.get("report_candidate_index")),
            "bot_plays": key == chosen_key,
        })
        if selection_levels:
            rows[-1]["acting_team_levels"] = mean
    report = rec.get("report_fold")
    safe_report = None
    if report:
        safe_report = _fields(report, ("gap", "se", "worlds", "critical", "statistic", "min_gain"))
        safe_report.update(rule=str(report.get("rule", ""))[:64],
                           complete=bool(report.get("complete")))
    return rows, {
        "source": "isolated_current_state_replay", "historical_decision": False,
        "policy": str(getattr(bot, "policy_name", type(bot).__name__))[:160],
        "reason": str(rec.get("reason", "forced_or_no_search"))[:100],
        "model": _model_identity(bot),
        "model_score_units": "expected signed levels for acting team",
        "selection_score_units": ("expected signed levels for acting team" if selection_levels
                                  else "expected final attacker points"),
        "report_gap_units": "acting-team points: challenger minus incumbent",
        "report": safe_report,
        "recipe": {**_fields(shortlist.get("config", {}), ("worlds", "alternatives", "selection_worlds", "batch_size", "uniform")),
                   **_fields(rec, ("report_worlds_requested", "report_min_gain")),
                   "report_rule": str(rec.get("report_rule", "none"))[:64]},
        "shortlist": {**_fields(shortlist, ("legal_count", "production_count", "wall_seconds")),
                      "retained_count": len(shortlist.get("shortlist", [])),
                      "offballot_played": bool(shortlist.get("offballot_played")),
                      "counts": _fields(shortlist.get("counts", {}),
                                        ("cheap_worlds", "cheap_evaluations", "cheap_batches")),
                      "reuse": _fields(shortlist.get("successor_reuse", {}),
                                       ("root_actions", "leaf_hits", "leaf_completions", "peak_entries"))},
        "work": _fields(rec.get("work", {}), ("selection_rollouts", "report_rollouts", "total_rollouts")),
        "search_seconds": _number(rec.get("search_secs")),
        "evaluation_seconds": elapsed,
        "candidate_count": len(candidates), "candidates_truncated": len(indices) < len(candidates),
    }
