"""Bounded, allowlisted view of one isolated play evaluation, not replay data."""
from __future__ import annotations

import math

MAX_CANDIDATES = 32


def _number(value):
    return value if isinstance(value, (int, float)) and math.isfinite(value) else None


def _fields(source, names):
    return {k: _number(source[k]) for k in names if k in source}


def play_analysis(bot, pick, *, is_attacker, elapsed):
    rec = getattr(bot, "last_decision_record", None) or {}
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
    def at(name, i):
        values = rec.get(name, [])
        return _number(values[i]) if i < len(values) else None
    rows = []
    for i in indices:
        key = tuple(sorted(candidates[i]))
        mean = _number(means[i]) if i < len(means) else None
        rows.append({
            "index": i, "play": list(candidates[i]),
            "attackers_avg": None if mean is None else mean * (1 if is_attacker else -1),
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
    evaluator = getattr(bot, "evaluator", None)
    model = None
    if evaluator is not None:
        identity = evaluator.identity()
        model = {k: identity.get(k) for k in (
            "backend", "checkpoint_sha256", "source_checkpoint_sha256", "encoding",
            "effective_encoding", "max_batch", "device")}
        model["encoder_version"] = _number(getattr(evaluator, "enc_version", None))
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
        "model": model,
        "model_score_units": "expected signed levels for acting team",
        "selection_score_units": "expected final attacker points",
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
