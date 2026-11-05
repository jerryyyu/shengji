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
        "doomed_throw_reselect_fallback_forced", "doomed_throw_reselect_exact_guarded",
        "doomed_throw_reselect_exact_floor_excluded"),
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
        "exact_lead_subset_worlds", "exact_deep_cards"),
    "exact_follow": (
        "exact_follow_attempted", "exact_follow_applied", "exact_follow_abandoned",
        "exact_follow_worlds", "exact_follow_nodes", "exact_follow_scores",
        "exact_follow_subset_worlds"),
    # the held-out lead confirmation; its challengers are card lists, shown as
    # text (`_card_texts`), and its abandon error (an exception name) stays out
    "lead_confirm": (
        "lead_confirm_status", "lead_confirm_applied", "lead_confirm_to", "lead_confirm_pool",
        "lead_confirm_screen_worlds", "lead_confirm_screen_margins", "lead_confirm_worlds",
        "lead_confirm_deltas", "lead_confirm_ses", "lead_confirm_seconds",
        "lead_confirm_abandon_reason"),
    "singleton_challenger": (
        "singleton_challenger_applied", "singleton_challenger_added",
        "singleton_challenger_removed", "singleton_probe_worlds",
        "singleton_probe_evaluations", "singleton_probe_margin"),
    "leaf_greedy": (
        "leaf_greedy_finish_applied", "leaf_greedy_finish_exact_skipped",
        "leaf_greedy_deadline_fired", "leaf_greedy_deadline_cut_leaves",
        "leaf_greedy_deadline_fired_lead_confirm", "leaf_greedy_deadline_fired_any",
        "leaf_greedy_uncached_leaves", "leaf_greedy_reply_plays",
        "leaf_greedy_reply_evaluations"),
    "history": (
        "history_follow_events", "history_rejections", "history_fallback_worlds",
        "history_unchecked_worlds", "history_fill_worlds",
        "history_fill_worlds_all_draws", "history_unchecked_worlds_all_draws"),
    "refusal": (
        "refusal_observations", "refusal_rejections", "refusal_fallback_worlds",
        "refusal_pinned_codes"),
    "small_joker": (
        "small_joker_guard_active", "small_joker_guard_anchor_replaced",
        "small_joker_guard_anchor_to", "small_joker_guard_big_jokers_out",
        "small_joker_guard_other_trumps"),
    "wide_lead": ("wide_lead_admission_applied", "wide_lead_admission_k"),
    # the belief proposal's summary only: its seed and snapshot stay in the log
    "belief": (
        "belief_fallback", "belief_proposed", "belief_ms", "belief_entropy_bits",
        "belief_top_mass", "belief_hidden_copies", "belief_fallback_all_draws",
        "belief_fallback_any"),
}
#: the per-stage draw tallies (`PVSearchBot._draw_tally_record`): small dicts of
#: counts keyed by the draw stage, shown as counts only
PV_DRAW_TALLIES = ("world_draws_by_stage", "belief_fallback_by_stage",
                   "history_fill_worlds_by_stage", "history_unchecked_worlds_by_stage")
#: the decision record's package ids (`PVSearchBot.model_ids`)
MODEL_ID_ROLES = ("value", "prior", "belief")
#: the sampler's per-decision counter deltas (`PVSearchBot.decide_play`)
PV_SAMPLING_DELTAS = ("impossible_worlds_delta", "rejected_worlds_delta")
#: the record flags that say a rule changed or extended this decision
PV_APPLIED_FLAGS = (
    "tiebreak_applied", "lead_tiebreak_applied", "lead_anchor_applied",
    "doomed_throw_swap_applied", "doomed_throw_reselect_applied",
    "adaptive_worlds_triggered", "exact_lead_changed", "exact_follow_applied",
    "wide_lead_admission_applied", "adaptive_k_applied",
    "singleton_challenger_applied", "lead_confirm_applied",
)
MAX_TEXT = 100
MAX_LIST = 64
#: a served policy name is the full recipe (release 50's is 179 characters)
MAX_POLICY = 240
_OMIT = object()


def _policy(bot):
    return str(getattr(bot, "policy_name", type(bot).__name__))[:MAX_POLICY]


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


def _card_texts(value):
    """A list of card lists as bounded text, one string per play."""
    if not isinstance(value, (list, tuple)):
        return None
    out = []
    for play in value[:MAX_LIST]:
        if not isinstance(play, (list, tuple)) or not all(isinstance(c, str) for c in play):
            return None
        out.append(" ".join(play)[:MAX_TEXT])
    return out


def model_ids(rec):
    """The record's package ids (value / prior / belief sha256 prefixes), or None
    for a record written before the field existed."""
    ids = rec.get("model_ids") if isinstance(rec, dict) else None
    if not isinstance(ids, dict):
        return None
    return {role: (ids[role][:16] if isinstance(ids.get(role), str) else None)
            for role in MODEL_ID_ROLES}


def _draw_tallies(rec):
    out = {}
    for name in PV_DRAW_TALLIES:
        table = rec.get(name)
        if isinstance(table, dict):
            out[name] = {str(k)[:32]: _number(v) for k, v in list(table.items())[:8]}
    return out


def _text(value):
    """A play as text: a card list joined, a string kept, anything else None."""
    if isinstance(value, (list, tuple)) and all(isinstance(c, str) for c in value):
        return " ".join(value)[:MAX_TEXT]
    if isinstance(value, str):
        return value[:MAX_TEXT]
    return None


def _warning(code, text, severity="degraded"):
    return {"code": code, "severity": severity, "text": text[:200]}


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


def _pv_play_analysis(bot, pick, rec, *, elapsed, context=None):
    admitted = [list(c) for c in rec.get("admitted") or []]
    means = rec.get("value_means") or []
    odds = rec.get("policy_log_odds_admitted") or []
    indices = list(rec.get("admitted_indices") or [])
    selected = rec.get("selected_index")
    selected_pos = indices.index(selected) if selected in indices else None
    chosen_key = tuple(sorted(pick))
    anchor_replaced = rec.get("lead_anchor_applied") is True
    worlds = _number(rec.get("worlds"))
    exact_lead_done = rec.get("exact_lead_status") == "complete"
    base_means = rec.get("exact_lead_base_value_means") if exact_lead_done else None
    exact_scores = rec.get("exact_follow_scores") if rec.get("exact_follow_abandoned") is None else None
    confirm_texts = _card_texts(rec.get("lead_confirm_challengers")) or []
    confirm_deltas = rec.get("lead_confirm_deltas") or []
    confirm_ses = rec.get("lead_confirm_ses") or []
    confirmed = rec.get("lead_confirm_applied") is True
    singleton = _text(rec.get("singleton_challenger_added")) \
        if rec.get("singleton_challenger_applied") is True else None
    ranked = sorted((i for i in range(min(len(admitted), len(means))) if _number(means[i]) is not None),
                    key=lambda i: (-means[i], i))
    rank_of = {i: r + 1 for r, i in enumerate(ranked)}
    rows = []
    for i, cards in enumerate(admitted[:MAX_CANDIDATES]):
        key = tuple(sorted(cards))
        level = _number(means[i]) if i < len(means) else None
        text = " ".join(cards)
        extra = {"rank": rank_of.get(i)}
        if base_means is not None and i < len(base_means):
            # an exact lead pass replaced the means with exact-solved levels;
            # the search's own value for the same candidate
            extra["search_value"] = _number(base_means[i])
        if isinstance(exact_scores, list) and i < len(exact_scores):
            extra["exact_score"] = _number(exact_scores[i])
        if confirmed and i == len(admitted) - 1:
            extra["lead_confirm_challenger"] = True
        if text in confirm_texts:
            j = confirm_texts.index(text)
            extra["lead_confirm_delta"] = _number(confirm_deltas[j]) if j < len(confirm_deltas) else None
            extra["lead_confirm_se"] = _number(confirm_ses[j]) if j < len(confirm_ses) else None
        if singleton is not None and text == singleton:
            extra["singleton_added"] = True
        rows.append({**extra,
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
    if "lead_confirm" in stages and confirm_texts:
        stages["lead_confirm"]["lead_confirm_challengers"] = confirm_texts
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
        "policy": _policy(bot),
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
        "model_ids": model_ids(rec),
        "draws": _draw_tallies(rec),
        "verdict": _pv_verdict(rec, rows, pick, admitted, context),
    }


#: the top-ranked candidates the verdict lists
TOP_N = 5
#: the stages of a pv-search decision in the order they run (`PVSearchBot._search`):
#: each later stage may replace the play an earlier one settled
PV_PIPELINE = ("anchor", "admission", "singleton_challenger", "search", "tiebreak",
               "doomed_throw", "exact_lead", "lead_confirm", "exact_follow")


def _fmt(value, digits=3):
    value = _number(value)
    return "n/a" if value is None else f"{value:+.{digits}f}"


def _secs(value):
    value = _number(value)
    return "n/a" if value is None else f"{value:.3f}s"


def _top(rows):
    scored = sorted((r for r in rows if r.get("acting_team_levels") is not None),
                    key=lambda r: (-r["acting_team_levels"], r["index"]))
    top = []
    for k, row in enumerate(scored[:TOP_N]):
        following = scored[k + 1]["acting_team_levels"] if k + 1 < len(scored) else None
        top.append({"play": row["play"], "value": row["acting_team_levels"],
                    "prior_log_odds": row.get("policy_log_odds"),
                    "margin_to_next": (None if following is None
                                       else row["acting_team_levels"] - following),
                    "anchor": row.get("anchor") is True, "bot_plays": row.get("bot_plays") is True})
    return top


def _stage(name, status, *, changed=False, play=None, detail=""):
    return {"stage": name, "status": status, "changed": bool(changed),
            "play": _text(play), "detail": detail[:240]}


def _search_pick(rec, admitted):
    """The base value pass's argmax (lowest position on a tie): the exact lead
    stage's record keeps the base means when it replaced them."""
    means = rec.get("exact_lead_base_value_means") \
        if rec.get("exact_lead_status") == "complete" else rec.get("value_means")
    means = [(_number(v) if i < len(admitted) else None) for i, v in enumerate(means or [])]
    scored = [i for i, v in enumerate(means) if v is not None]
    if not scored:
        return None, None
    best = min(scored, key=lambda i: (-means[i], i))
    return best, means[best]


def _pv_pipeline(rec, admitted, pick, context):
    """Every stage of the decision, in order, with what it did."""
    out = []
    anchor = admitted[0] if admitted else None
    if rec.get("lead_anchor_applied") is True:
        out.append(_stage("anchor", "replaced", changed=True, play=anchor,
                          detail=f"heuristic {_text(rec.get('lead_anchor_from'))} replaced by "
                                 f"{_text(rec.get('lead_anchor_to'))} "
                                 f"({_text(rec.get('lead_anchor_source')) or 'n/a'})"))
    else:
        out.append(_stage("anchor", "heuristic", play=anchor, detail="the heuristic's play, slot 0"))
    legal = _number(rec.get("legal_count"))
    listed = "" if rec.get("legal_complete") is not False else f", listing capped at {_number(rec.get('cap'))}"
    skipped = len(rec.get("diversity_skipped") or [])
    # a confirmed lead is appended after the admission
    admitted_count = len(admitted) - (rec.get("lead_confirm_applied") is True)
    out.append(_stage("admission", "complete",
                      detail=f"{admitted_count} admitted of {legal if legal is not None else 'n/a'} legal"
                             f"{listed}; diversity skipped {skipped}"))
    if rec.get("singleton_challenger_applied") is True:
        out.append(_stage("singleton_challenger", "applied", changed=True,
                          play=rec.get("singleton_challenger_added"),
                          detail=f"sc8 admitted {_text(rec.get('singleton_challenger_added'))} in place of "
                                 f"{_text(rec.get('singleton_challenger_removed'))}; probe margin "
                                 f"{_fmt(rec.get('singleton_probe_margin'))} on "
                                 f"{_number(rec.get('singleton_probe_worlds'))} worlds"))
    elif "singleton_probe_margin" in rec:
        out.append(_stage("singleton_challenger", "kept",
                          detail=f"sc8 probed: best omitted singleton {_fmt(rec.get('singleton_probe_margin'))} "
                                 f"vs the ballot on {_number(rec.get('singleton_probe_worlds'))} worlds"))
    elif "singleton_challenger_applied" in rec:
        following = context is not None and context.get("following")
        out.append(_stage("singleton_challenger", "not_probed",
                          detail="a follow" if following else
                          "sc8 probes leads above 7 cards with an omitted singleton only"))
    best, value = _search_pick(rec, admitted)
    leaf = ("greedy-finished leaves" if rec.get("leaf_greedy_finish_applied") is True
            else "plain leaves")
    if rec.get("leaf_greedy_deadline_fired") is True:
        leaf += f", deadline cut {_number(rec.get('leaf_greedy_deadline_cut_leaves'))} leaves"
    out.append(_stage("search", "complete" if rec.get("work_complete") else "incomplete",
                      changed=best not in (None, 0), play=admitted[best] if best is not None else None,
                      detail=f"value argmax {_fmt(value)} on {_number(rec.get('worlds'))} worlds, {leaf}"))
    if rec.get("tiebreak_applied") is True:
        out.append(_stage("tiebreak", "tiebreak", changed=True,
                          detail=f"near-tied set {_scalar(rec.get('tiebreak_near_set'))} decided on "
                                 f"points {_scalar(rec.get('tiebreak_points'))}"))
    if rec.get("lead_tiebreak_applied") is True:
        out.append(_stage("tiebreak", "lead_tiebreak", changed=True, play=rec.get("lead_tiebreak_to"),
                          detail=f"lead tiebreak {_text(rec.get('lead_tiebreak_from'))} -> "
                                 f"{_text(rec.get('lead_tiebreak_to'))} (value gap "
                                 f"{_fmt(rec.get('lead_tiebreak_value_gap'))})"))
    for name in ("doomed_throw_reselect", "doomed_throw_swap"):
        if rec.get(f"{name}_applied") is True:
            out.append(_stage("doomed_throw", name, changed=True, play=rec.get(f"{name}_to"),
                              detail=f"doomed throw {_text(rec.get(f'{name}_from'))} -> "
                                     f"{_text(rec.get(f'{name}_to'))}"
                                     + (" (exact-floored)" if rec.get(f"{name}_exact_guarded") else "")))
    status = rec.get("exact_lead_status")
    if status == "complete":
        out.append(_stage("exact_lead", "complete", changed=rec.get("exact_lead_changed") is True,
                          play=pick if rec.get("exact_lead_changed") else None,
                          detail=f"{_text(rec.get('exact_lead_change_kind')) or 'n/a'}: exact level "
                                 f"{_fmt(rec.get('exact_lead_selected_level_mean'))} vs the search's play "
                                 f"{_text(rec.get('exact_lead_base_played'))} "
                                 f"{_fmt(rec.get('exact_lead_base_level_mean'))}; "
                                 f"{_number(rec.get('exact_lead_worlds_completed'))} worlds, "
                                 f"{_number(rec.get('exact_lead_nodes'))} nodes, "
                                 f"{_secs(rec.get('exact_lead_seconds'))}"))
    elif status == "ineligible":
        following = context is not None and context.get("following")
        out.append(_stage("exact_lead", "ineligible",
                          detail="a follow" if following else
                          f"a lead with every hand <= {_number(rec.get('exact_deep_cards')) or 'n/a'} cards only"))
    elif status is not None:
        out.append(_stage("exact_lead", _text(status),
                          detail=_text(rec.get("exact_lead_abandon_reason")) or ""))
    status = rec.get("lead_confirm_status")
    if status == "applied":
        out.append(_stage("lead_confirm", "applied", changed=True, play=rec.get("lead_confirm_to"),
                          detail=f"lcc replaced the search's lead; {_number(rec.get('lead_confirm_worlds'))} "
                                 f"fresh worlds: {_lcc_evidence(rec)} (pool {_number(rec.get('lead_confirm_pool'))}, "
                                 f"{_secs(rec.get('lead_confirm_seconds'))})"))
    elif status == "rejected":
        out.append(_stage("lead_confirm", "rejected",
                          detail=f"challengers did not confirm: {_lcc_evidence(rec)}"))
    elif status is not None:
        details = {"no_challenger": "no pool lead beat the played lead on the screen worlds",
                   "no_pool": "no unadmitted lead to screen",
                   "exact": "the exact lead stage decides this lead",
                   "override": "a doomed-throw override played a component",
                   "single_candidate": "one admitted candidate",
                   "skipped_budget": "skipped: the decision used its start fraction of the budget",
                   "abandoned": f"abandoned: {_text(rec.get('lead_confirm_abandon_reason')) or 'n/a'}"}
        out.append(_stage("lead_confirm", _text(status),
                          detail=details.get(status, "") +
                          (f" (pool {_number(rec.get('lead_confirm_pool'))})" if status == "no_challenger" else "")))
    if rec.get("exact_follow_attempted") is True:
        abandoned = rec.get("exact_follow_abandoned")
        out.append(_stage("exact_follow", "abandoned" if abandoned else
                          "applied" if rec.get("exact_follow_applied") else "unchanged",
                          changed=rec.get("exact_follow_applied") is True,
                          play=pick if rec.get("exact_follow_applied") else None,
                          detail=(f"abandoned: {_text(abandoned)}" if abandoned else
                                  f"{_number(rec.get('exact_follow_worlds'))} worlds, "
                                  f"{_number(rec.get('exact_follow_nodes'))} nodes")))
    elif context is not None and context.get("following"):
        out.append(_stage("exact_follow", "ineligible",
                          detail=f"largest hand {context.get('max_hand')} cards; the exact follow "
                                 "takes more than one candidate and every hand within its bound"))
    return out


def _lcc_evidence(rec):
    texts = _card_texts(rec.get("lead_confirm_challengers")) or []
    deltas = rec.get("lead_confirm_deltas") or []
    ses = rec.get("lead_confirm_ses") or []
    if not deltas:
        margins = rec.get("lead_confirm_screen_margins") or []
        return "; ".join(f"{t} screen {_fmt(m)}" for t, m in zip(texts, margins)) or "n/a"
    return "; ".join(f"{t} delta {_fmt(d)} +/- {_fmt(e).lstrip('+')}" for t, d, e in zip(texts, deltas, ses))


def _pv_warnings(rec):
    warn = []
    if rec.get("work_complete") is False:
        warn.append(_warning("work_incomplete", "the search did not complete its work"))
    by_stage = rec.get("belief_fallback_by_stage")
    if rec.get("belief_fallback_any") == 1 or (_number(rec.get("belief_fallback")) or 0) > 0:
        where = (", ".join(f"{k} {v}" for k, v in by_stage.items() if v)
                 if isinstance(by_stage, dict) else "base")
        warn.append(_warning("belief_fallback",
                             f"belief draw fell back to the sampler ({where})"))
    if rec.get("leaf_greedy_deadline_fired_any") is True or rec.get("leaf_greedy_deadline_fired") is True:
        warn.append(_warning("leaf_deadline",
                             f"greedy-finish deadline fired: {_number(rec.get('leaf_greedy_deadline_cut_leaves'))} "
                             f"base leaves cut"
                             + (", lead confirmation cut" if rec.get("leaf_greedy_deadline_fired_lead_confirm") else "")))
    for name, label in (("lead_confirm", "lead confirmation"), ("exact_lead", "exact lead")):
        status = rec.get(f"{name}_status")
        if status == "abandoned":
            warn.append(_warning(f"{name}_abandoned",
                                 f"{label} abandoned ({_text(rec.get(f'{name}_abandon_reason')) or 'n/a'})"))
        elif status == "skipped_budget":
            warn.append(_warning(f"{name}_skipped_budget", f"{label} skipped for the budget"))
    if rec.get("exact_follow_abandoned"):
        warn.append(_warning("exact_follow_abandoned",
                             f"exact follow abandoned ({_text(rec.get('exact_follow_abandoned'))})"))
    for name in ("tiebreak", "doomed_throw_swap", "doomed_throw_reselect", "adaptive_worlds"):
        if rec.get(f"{name}_abandoned"):
            warn.append(_warning(f"{name}_abandoned", f"{name} abandoned"))
    for name, label in (("refusal_fallback_worlds", "refusal constraints"),
                        ("history_fallback_worlds", "history legality")):
        count = _number(rec.get(name)) or 0
        if count > 0:
            warn.append(_warning(name, f"{count} worlds fell back from {label}"))
    if rec.get("legal_complete") is False:
        warn.append(_warning("legal_capped", f"legal listing capped at {_number(rec.get('cap'))} of "
                             f"{_number(rec.get('legal_count'))}", "info"))
    if model_ids(rec) is None:
        warn.append(_warning("no_model_ids", "the record names no package ids", "info"))
    return warn


def _pv_verdict(rec, rows, pick, admitted, context):
    """At a glance: what was played, which stage settled it, the top
    candidates, whether anything degraded and which packages decided."""
    pipeline = _pv_pipeline(rec, admitted, pick, context)
    changed = [s for s in pipeline if s["changed"]]
    if rec.get("legal_count") == 1:
        decided_by = "forced"
    else:
        decided_by = changed[-1]["stage"] if changed else "anchor"
    top = _top(rows)
    chosen_row = next((r for r in rows if r.get("bot_plays")), None)
    chosen_value = chosen_row.get("acting_team_levels") if chosen_row else None
    others = [r["acting_team_levels"] for r in rows
              if r.get("acting_team_levels") is not None and not r.get("bot_plays")]
    margin = (chosen_value - max(others)) if chosen_value is not None and others else None
    warnings = _pv_warnings(rec)
    if decided_by == "forced":
        detail = "the only legal play"
    elif chosen_row is not None and chosen_value is None and "lead_confirm_delta" in chosen_row:
        detail = f"lcc delta {_fmt(chosen_row['lead_confirm_delta'])} vs the search's lead"
    else:
        unit = "exact level" if rec.get("exact_lead_status") == "complete" else "value"
        detail = f"{unit} {_fmt(chosen_value)}, {_fmt(margin)} vs the next best"
        if chosen_row is not None and chosen_row.get("exact_score") is not None:
            detail += f"; exact follow score {_fmt(chosen_row['exact_score'])}"
    label = {"anchor": "search kept the heuristic anchor", "forced": "forced"}.get(decided_by, decided_by)
    return {
        "played": list(pick), "decided_by": decided_by,
        "summary": f"played {_text(pick)}: {label}; {detail}"[:240],
        "chosen_value": chosen_value, "margin_to_next": margin,
        "top": top, "pipeline": pipeline, "warnings": warnings,
        "degraded": any(w["severity"] == "degraded" for w in warnings),
        "model_ids": model_ids(rec),
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
        "policy": _policy(bot),
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
        "model_ids": model_ids(rec),
        "draws": {},
        "verdict": {
            "played": list(pick), "decided_by": "fallback",
            "summary": f"played {_text(pick)}: the heuristic, the search fell back "
                       f"({str(rec.get('reason', 'fallback'))[:MAX_TEXT]})",
            "chosen_value": None, "margin_to_next": None, "top": [],
            "pipeline": [_stage("anchor", "heuristic", play=pick, detail="the heuristic's play"),
                         _stage("search", "fallback", detail=str(rec.get("error_class") or "")[:MAX_TEXT])],
            "warnings": [_warning("search_fallback",
                                  f"search fell back to the heuristic: {str(rec.get('reason', 'fallback'))[:MAX_TEXT]}"
                                  f" ({str(rec.get('error_class') or 'n/a')[:MAX_TEXT]})")],
            "degraded": True, "model_ids": model_ids(rec),
        },
    }


def play_analysis(bot, pick, *, is_attacker, elapsed, context=None):
    """``context`` is public state the verdict reads (``following``, ``max_hand``)."""
    rec = getattr(bot, "last_decision_record", None) or {}
    schema = rec.get("schema")
    if schema == PV_SCHEMA:
        return _pv_play_analysis(bot, pick, rec, elapsed=elapsed, context=context)
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
        "policy": _policy(bot),
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
