"""Mutation-falsifiable contract tests for the report-LCB teacher audit."""
from __future__ import annotations

import copy
import json
import random
import sys
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import teacher_v1_champion_audit as audit  # noqa: E402
from shengji.ai.registry import make_bot  # noqa: E402
from shengji.ai.smart import SmartBot  # noqa: E402
from shengji.engine.game import Game  # noqa: E402
from shengji.teacher_v1 import REPRESENTATIVE_CELLS, stable_digest  # noqa: E402


def parent_states() -> list[dict]:
    rows = []
    seed = 1
    for phase, role, decision in REPRESENTATIVE_CELLS:
        for index in range(8):
            rows.append({
                "state_id": f"r:{phase}:{role}:{decision}:{index}",
                "seed": seed,
                "kind": "representative",
                "phase": phase,
                "role": role,
                "decision": decision,
            })
            seed += 1
    for kind in ("boundary", "uncertainty"):
        for index in range(16):
            rows.append({
                "state_id": f"{kind}:{index}",
                "seed": seed,
                "kind": kind,
                "phase": ("early", "mid", "late")[index % 3],
                "role": ("attacker", "defender")[index % 2],
                "decision": ("lead", "follow")[index % 2],
            })
            seed += 1
    return rows


def test_audit_subset_is_exact_stratified_and_outcome_blind():
    rows = parent_states()
    selected, problems = audit.select_states(rows)
    assert problems == []
    assert len(selected) == audit.AUDIT_STATES
    counts = Counter(row["kind"] for row in selected)
    assert counts == {
        "representative": 48,
        "boundary": 8,
        "uncertainty": 8,
    }
    representative = Counter(
        (row["phase"], row["role"], row["decision"])
        for row in selected if row["kind"] == "representative"
    )
    assert all(representative[cell] == 4 for cell in REPRESENTATIVE_CELLS)

    outcome_mutation = copy.deepcopy(rows)
    for index, row in enumerate(outcome_mutation):
        row["future_n30_outcome"] = (-1) ** index * 999
    mutated, problems = audit.select_states(outcome_mutation)
    assert problems == []
    assert [row["state_id"] for row in mutated] == [
        row["state_id"] for row in selected]


def test_audit_selector_refuses_duplicate_state_or_deal():
    rows = parent_states()
    rows[1]["state_id"] = rows[0]["state_id"]
    rows[2]["seed"] = rows[0]["seed"]
    _, problems = audit.select_states(rows)
    assert "Stage-B parent has duplicate state identities" in problems
    assert "Stage-B parent has duplicate deal identities" in problems


def test_frozen_audit_state_actor_identity_is_exact_and_falsifiable():
    payload = {
        "git": audit.AUDIT_STATE_FREEZE_GIT,
        "tree_dirty": False,
        "source_digests": copy.deepcopy(audit.AUDIT_STATE_SOURCE_DIGESTS),
        "continuation_contract": audit.CONTINUATION_CONTRACT,
    }
    assert audit.audit_state_execution_lock_problems(payload) == []

    changed = copy.deepcopy(payload)
    changed["source_digests"]["compiled_engine"] = "0" * 64
    assert "audit state-set frozen source identity drift" in \
        audit.audit_state_execution_lock_problems(changed)


def test_audit_packet_recomputes_selection_and_exact_parent():
    parent = {
        "states": parent_states(),
        "states_digest": stable_digest(parent_states()),
    }
    selected, problems = audit.select_states(parent["states"])
    assert problems == []
    payload = {
        "schema": audit.AUDIT_STATE_SCHEMA,
        "audit_id": audit.AUDIT_ID,
        "complete": True,
        "stage_b_parent": {
            "sha256": audit.STAGE_B_STATE_SHA256,
            "states_digest": parent["states_digest"],
        },
        "selection_contract": {
            "method": "hash_smallest_within_frozen_stratum",
            "hash_domain": (
                "stable_digest(audit_id,purpose=state_selection,state_id)"),
            "representative_per_cell": 4,
            "boundary": 8,
            "uncertainty": 8,
            "label_outcomes_read": False,
        },
        "continuation_contract": audit.CONTINUATION_CONTRACT,
        "folds": audit.AUDIT_FOLDS,
        "selected": len(selected),
        "states": selected,
        "states_digest": stable_digest(selected),
    }
    assert audit.audit_state_set_problems(
        payload, parent, audit.STAGE_B_STATE_SHA256) == []

    mutated = copy.deepcopy(payload)
    mutated["states"][0], mutated["states"][1] = (
        mutated["states"][1], mutated["states"][0])
    mutated["states_digest"] = stable_digest(mutated["states"])
    assert "audit state selection recomputation drift" in \
        audit.audit_state_set_problems(
            mutated, parent, audit.STAGE_B_STATE_SHA256)

    assert "audit Stage-B parent SHA-256 drift" in \
        audit.audit_state_set_problems(
            payload, parent, stable_digest("different-parent"))


def test_champion_contract_is_literal_deployed_report_lcb():
    assert audit.CONTINUATION_CONTRACT == {
        "policy": "mc-s0-report-lcb",
        "selection_worlds": 30,
        "report_worlds": 300,
        "report_rule": "lcb",
        "report_alpha": 0.05,
        "report_min_gain": 0.0,
        "report_t_critical": 1.70,
        "require_exact_work": True,
        "adaptive_allocation": False,
        "random_allocation": False,
        "admission": {
            "schema": "teacher-v3-champion-continuation-admission-v1",
            "accepted_worlds": {"selection": 30, "report": 300},
            "selection_attempt_cap": 1_200,
            "report_attempt_cap": 12_000,
            "allow_failed_determinization_retries": True,
            "require_full_accepted_dose": True,
            "refuse_attempt_cap_hit": True,
            "require_strict_voids": True,
            "score_failed_attempts": False,
            "counter_identity": (
                "sample_attempts=accepted_worlds+failed_worlds"),
        },
    }
    assert audit.live_continuation_contract() == audit.CONTINUATION_CONTRACT
    assert audit.AUDIT_FOLDS == {
        "champion_selection": 32,
        "champion_report": 32,
    }


def test_continuation_execution_lock_is_literal_and_mutation_falsifiable(
        monkeypatch):
    from shengji.ai import mcbot
    from shengji.engine import ballot

    expected = copy.deepcopy(audit.CONTINUATION_EXECUTION_LOCK)
    # Poison the ordinary process-local cache, then prove the audit boundary
    # derives the real identity from current source/native bytes.  A prior
    # preflight accidentally froze the stale value after replacing the native
    # binary in an already-imported interpreter.
    mcbot._cached_ballot_identity.cache_clear()
    with monkeypatch.context() as cache_patch:
        cache_patch.setattr(
            ballot, "source_digest", lambda *_args, **_kwargs: "f" * 16)
        poisoned = mcbot._ballot_identity(
            audit.make_bot(audit.CONTINUATION_POLICY, seed=1))
    assert poisoned["source_digest"] == "f" * 16

    # Bind the literal ballot to the real generator rather than proving only
    # that a mocked value agrees with itself.
    assert audit.live_continuation_execution_lock()["ballot"] == \
        expected["ballot"]
    monkeypatch.setattr(
        audit, "live_continuation_execution_lock", lambda: expected)
    assert audit.continuation_execution_lock_problems() == []

    changed = copy.deepcopy(expected)
    changed["ballot"]["config"][0][1] += 1
    monkeypatch.setattr(
        audit, "live_continuation_execution_lock", lambda: changed)
    assert "continuation execution ballot drift" in \
        audit.continuation_execution_lock_problems()

    changed = copy.deepcopy(expected)
    changed["source_sha256s"]["engine_round"] = "0" * 64
    monkeypatch.setattr(
        audit, "live_continuation_execution_lock", lambda: changed)
    assert "continuation execution source engine_round drift" in \
        audit.continuation_execution_lock_problems()


def test_receipt_entry_requires_exact_external_execution_predeclaration(
        monkeypatch):
    head = "a" * 40
    script_sha = "b" * 64
    monkeypatch.setattr(audit, "audit_transition_problems", lambda: [])
    monkeypatch.setattr(audit, "git_output", lambda *_args: head)
    monkeypatch.setattr(audit, "sha256_file", lambda _path: script_sha)

    assert audit.exact_execution_predeclaration_problems(
        head, script_sha) == []
    assert "audit execution exact git predeclaration" in \
        audit.exact_execution_predeclaration_problems("c" * 40, script_sha)
    assert "audit execution exact script predeclaration" in \
        audit.exact_execution_predeclaration_problems(head, "d" * 64)


def valid_champion_decision():
    candidates = [["A"], ["K"], ["Q"]]
    selection_rollouts = 30 * len(candidates)
    total_rollouts = selection_rollouts + 600
    sampler = {
        "sample_attempts": 330,
        "accepted_worlds": 330,
        "failed_worlds": 0,
        "rejected_worlds": 0,
        "impossible_worlds": 0,
        "short_search_decisions": 0,
        "zero_world_decisions": 0,
    }
    record = {
        "policy": audit.CONTINUATION_POLICY,
        "policy_class": audit.CONTINUATION_EXECUTION_LOCK["policy_class"],
        "code": {"mcbot_sha256": audit.CONTINUATION_EXECUTION_LOCK[
            "source_sha256s"]["ai_mcbot"]},
        "ballot": copy.deepcopy(
            audit.CONTINUATION_EXECUTION_LOCK["ballot"]),
        "n_determinizations": 30,
        "report_worlds_requested": 300,
        "report_rule": "lcb",
        "report_alpha": 0.05,
        "report_min_gain": 0.0,
        "adaptive_allocation": False,
        "random_allocation": False,
        "candidates": candidates,
        "n_by_candidate": [30, 30, 30],
        "worlds": 30,
        "alloc": {
            "mode": "uniform", "short": False, "worlds": 30,
            "attempts": 30, "attempt_cap": 1_200,
            "attempt_cap_hit": False,
            "budget": selection_rollouts,
            "rollouts": selection_rollouts,
            "decision_rollouts": selection_rollouts,
            "dummy_rollouts": 0,
            "n_by_candidate": [30, 30, 30],
        },
        "report_fold": {
            "fold": "report", "rule": "lcb", "worlds": 300,
            "attempts": 300, "rejected": 0, "complete": True,
            "critical": 1.70, "min_gain": 0.0,
        },
        "work": {
            "selection_budget": selection_rollouts,
            "selection_rollouts": selection_rollouts,
            "report_budget": 600, "report_rollouts": 600,
            "total_budget": total_rollouts,
            "total_rollouts": total_rollouts, "complete": True,
        },
        "reason": "report_lcb_below_min_gain",
        "played_index": 0,
        "played": candidates[0],
        "sampler_counters": {
            "delta": {name: sampler[name] for name in (
                "sample_attempts", "accepted_worlds", "failed_worlds",
                "rejected_worlds", "impossible_worlds")},
        },
    }
    policy = SimpleNamespace(
        last_decision_record=record, search_calls=1, rollouts=total_rollouts)
    return policy, sampler


def test_champion_decision_requires_complete_selection_report_and_counters():
    policy, sampler = valid_champion_decision()
    telemetry = audit.champion_decision_telemetry(policy, sampler)
    assert telemetry["decisions"] == 1
    assert telemetry["searched_decisions"] == 1
    assert telemetry["selection_candidate_rollouts"] == 90
    assert telemetry["report_candidate_rollouts"] == 600
    assert telemetry["accepted_worlds"] == 330

    for mutate in (
        lambda p, _s: p.last_decision_record["report_fold"].update(
            worlds=299),
        lambda p, _s: p.last_decision_record["work"].update(complete=False),
        lambda _p, s: s.update(accepted_worlds=329),
        lambda p, _s: p.last_decision_record.update(
            reason="selection_underfilled"),
    ):
        changed_policy, changed_sampler = valid_champion_decision()
        mutate(changed_policy, changed_sampler)
        with pytest.raises(audit.TeacherProtocolError):
            audit.champion_decision_telemetry(
                changed_policy, changed_sampler)

    for field in ("ballot", "code"):
        changed_policy, changed_sampler = valid_champion_decision()
        changed_policy.last_decision_record.pop(field)
        with pytest.raises(audit.TeacherProtocolError):
            audit.champion_decision_telemetry(
                changed_policy, changed_sampler)


def test_registered_champion_contract_uses_exact_work_and_all_reasons_are_typed():
    bot = make_bot(audit.CONTINUATION_POLICY, seed=1)
    assert bot.REQUIRE_EXACT_WORK is True
    assert audit.live_continuation_contract() == audit.CONTINUATION_CONTRACT
    assert audit.CHAMPION_DECISION_DISPOSITIONS == {
        "report_lcb_override": "accept_complete",
        "report_lcb_below_min_gain": "accept_complete",
        "selection_underfilled": "refuse_selection_underfilled",
        "no_report_challenger": "refuse_no_report_challenger",
        "report_underfilled": "refuse_report_underfilled",
    }
    for reason, expected in audit.CHAMPION_DECISION_DISPOSITIONS.items():
        assert audit.champion_decision_disposition({"reason": reason}) == expected
    with pytest.raises(audit.TeacherProtocolError, match="unclassified"):
        audit.champion_decision_disposition({"reason": "future_silent_path"})


def test_champion_refusals_name_score_free_branch_and_exact_failed_fields():
    policy, sampler = valid_champion_decision()
    policy.last_decision_record.update({
        "gap": 999.0,
        "played": ["SECRET-CARD"],
        "private_outcome": {"winner": 3},
    })
    diagnostic = audit.champion_decision_diagnostic(policy, sampler)
    encoded = json.dumps(diagnostic, sort_keys=True)
    assert diagnostic["schema"] == \
        "teacher-v1-champion-decision-refusal-v1"
    assert "SECRET-CARD" not in encoded
    assert "private_outcome" not in encoded
    assert '"gap"' not in encoded
    assert '"winner"' not in encoded

    # A completed report that needed one failed determinization retry preserves
    # the exact 300 accepted-world estimand and is counted rather than refused.
    policy, sampler = valid_champion_decision()
    policy.last_decision_record["report_fold"].update(
        attempts=301, rejected=1)
    sampler.update(
        sample_attempts=331, failed_worlds=1, rejected_worlds=1)
    policy.last_decision_record["sampler_counters"]["delta"].update({
        "sample_attempts": 331, "failed_worlds": 1,
        "rejected_worlds": 1})
    telemetry = audit.champion_decision_telemetry(policy, sampler)
    assert telemetry["accepted_worlds"] == 330
    assert telemetry["selection_sample_attempts"] == 30
    assert telemetry["report_sample_attempts"] == 301
    assert telemetry["retry_attempts"] == 1
    assert telemetry["failed_worlds"] == 1
    assert telemetry["rejected_worlds"] == 1

    # The same accounting applies when the retry occurs in selection.
    policy, sampler = valid_champion_decision()
    policy.last_decision_record["alloc"]["attempts"] = 31
    sampler.update(sample_attempts=331, failed_worlds=1)
    policy.last_decision_record["sampler_counters"]["delta"].update({
        "sample_attempts": 331, "failed_worlds": 1})
    telemetry = audit.champion_decision_telemetry(policy, sampler)
    assert telemetry["selection_sample_attempts"] == 31
    assert telemetry["report_sample_attempts"] == 300
    assert telemetry["retry_attempts"] == 1

    # A genuine short report has its own production reason and refusal code.
    policy, sampler = valid_champion_decision()
    policy.last_decision_record.update(reason="report_underfilled")
    policy.last_decision_record["report_fold"].update(
        worlds=299, attempts=12_000, rejected=11_701, complete=False)
    with pytest.raises(
            audit.TeacherProtocolError,
            match=r"refuse_report_underfilled: .*\"reason\":"
                  r"\"report_underfilled\""):
        audit.champion_decision_telemetry(policy, sampler)

    # Fixed statistical-policy parameters are contract drift, not underfill.
    policy, sampler = valid_champion_decision()
    policy.last_decision_record["report_fold"]["critical"] = 1.69
    with pytest.raises(
            audit.TeacherProtocolError,
            match="champion_report_contract_drift"):
        audit.champion_decision_telemetry(policy, sampler)


def test_completed_retry_contract_refuses_false_completion_and_bad_counters():
    # A short report cannot masquerade as complete merely by retaining the
    # production success reason.
    policy, sampler = valid_champion_decision()
    policy.last_decision_record["report_fold"].update(
        worlds=299, attempts=300, rejected=1, complete=True)
    with pytest.raises(
            audit.TeacherProtocolError,
            match="champion_report_dose_mismatch"):
        audit.champion_decision_telemetry(policy, sampler)

    # Complete accepted dose still refuses an impossible attempt count or an
    # internally inconsistent report retry count.
    policy, sampler = valid_champion_decision()
    policy.last_decision_record["report_fold"].update(
        attempts=12_001, rejected=11_701)
    with pytest.raises(
            audit.TeacherProtocolError,
            match="champion_report_attempt_mismatch"):
        audit.champion_decision_telemetry(policy, sampler)

    policy, sampler = valid_champion_decision()
    policy.last_decision_record["report_fold"].update(
        attempts=301, rejected=0)
    with pytest.raises(
            audit.TeacherProtocolError,
            match="champion_report_attempt_mismatch"):
        audit.champion_decision_telemetry(policy, sampler)

    # Live and record counters must reconcile with both fold attempt counts;
    # admitting retry semantics does not admit telemetry guessing.
    policy, sampler = valid_champion_decision()
    policy.last_decision_record["report_fold"].update(
        attempts=301, rejected=1)
    sampler.update(sample_attempts=330, failed_worlds=0)
    with pytest.raises(
            audit.TeacherProtocolError,
            match="champion_sampler_dose_mismatch"):
        audit.champion_decision_telemetry(policy, sampler)

    policy, sampler = valid_champion_decision()
    policy.last_decision_record["alloc"].update(
        attempts=1_201, attempt_cap_hit=False)
    with pytest.raises(
            audit.TeacherProtocolError,
            match="champion_selection_attempt_mismatch"):
        audit.champion_decision_telemetry(policy, sampler)


def test_live_report_lcb_decision_satisfies_champion_telemetry_contract():
    """The verifier must describe the real registered policy, not a mock.

    This is deliberately one decision rather than a duel.  It catches renamed
    record fields, changed dose/accounting, sampler fallbacks, and registry
    drift before an eight-shard audit spends hours only to refuse its first
    state at publication.
    """
    game = Game(random.Random(73))
    rnd = game.start_round()
    while rnd.phase == "deal":
        rnd.deal_next()
    smart = SmartBot()
    for seat in range(4):
        declaration = smart.decide_declare(rnd, seat, final=True)
        if declaration:
            rnd.declare(seat, declaration)
    rnd.finalize_declare()
    rnd.bury(rnd.banker, smart.decide_bury(rnd, rnd.banker))

    bot = make_bot(audit.CONTINUATION_POLICY, seed=9182)
    before = audit.teacher_label.sampler_snapshot(bot)
    bot.decide_play(rnd, rnd.turn)
    counters = audit.teacher_label.sampler_delta(before, bot)
    telemetry = audit.champion_decision_telemetry(bot, counters)

    assert telemetry["searched_decisions"] == 1
    assert telemetry["selection_worlds"] == 30
    assert telemetry["report_worlds"] == 300
    assert telemetry["accepted_worlds"] == 330
    assert telemetry["report_candidate_rollouts"] == 600


def test_champion_unsearched_decision_must_have_zero_work():
    zero = {name: 0 for name in audit.teacher_label.SAMPLER_COUNTERS}
    policy = SimpleNamespace(
        last_decision_record=None, search_calls=0, rollouts=0)
    telemetry = audit.champion_decision_telemetry(policy, zero)
    assert telemetry["decisions"] == 1
    assert telemetry["unsearched_decisions"] == 1
    assert telemetry["searched_decisions"] == 0

    policy.rollouts = 1
    with pytest.raises(audit.TeacherProtocolError):
        audit.champion_decision_telemetry(policy, zero)


def test_champion_fold_progress_is_periodic_and_artifact_neutral(monkeypatch):
    zero_counters = {
        name: 0 for name in audit.teacher_label.SAMPLER_COUNTERS}
    zero_telemetry = {name: 0 for name in audit.CHAMPION_TELEMETRY_FIELDS}
    zero_telemetry.update(decisions=1, unsearched_decisions=1)

    def fake_rollout(*_args, **kwargs):
        return (
            80.0 + 40.0 * kwargs["candidate_index"],
            zero_counters,
            stable_digest({"trace": kwargs["candidate_index"]}),
            1,
            zero_telemetry,
        )

    monkeypatch.setattr(audit, "rollout_champion", fake_rollout)
    rnd = SimpleNamespace(is_attacker=lambda _seat: True)
    state = {"experiment_id": "teacher-v1", "state_id": "audit-state",
             "seed": 149000000}
    worlds = [(None, None), (None, None)]
    candidates = [["A"], ["K"]]
    meta = {
        "requested_worlds": 2,
        "draw_ids": ["draw-0", "draw-1"],
        "world_digests": ["world-0", "world-1"],
    }
    events = []
    with_progress = audit.score_champion_fold(
        rnd, 0, candidates, worlds, meta, state=state,
        fold="champion_selection", progress=events.append)
    without_progress = audit.score_champion_fold(
        rnd, 0, candidates, worlds, meta, state=state,
        fold="champion_selection")
    assert with_progress == without_progress
    assert [event["worlds_complete"] for event in events] == [1, 2]
    assert all(event["state_id"] == "audit-state" for event in events)


def test_champion_trace_digest_excludes_only_wall_time():
    record = {"played": ["A"], "search_secs": 1.0}
    changed = {"played": ["A"], "search_secs": 99.0}
    assert audit._decision_record_digest(record) == \
        audit._decision_record_digest(changed)
    changed["played"] = ["K"]
    assert audit._decision_record_digest(record) != \
        audit._decision_record_digest(changed)


def test_continuation_telemetry_reconciles_exact_report_lcb_dose():
    telemetry = {name: 0 for name in audit.CHAMPION_TELEMETRY_FIELDS}
    telemetry.update({
        "decisions": 5,
        "searched_decisions": 2,
        "unsearched_decisions": 3,
        "selection_worlds": 60,
        "report_worlds": 600,
        "selection_candidate_rollouts": 180,
        "report_candidate_rollouts": 1200,
        "total_candidate_rollouts": 1380,
        "selection_sample_attempts": 60,
        "report_sample_attempts": 600,
        "retry_attempts": 0,
        "sample_attempts": 660,
        "accepted_worlds": 660,
    })
    fold = {
        "continuation_execution_lock": audit.CONTINUATION_EXECUTION_LOCK,
        "continuation_telemetry": telemetry,
        "inner_sampler_counters": {
            name: telemetry[name]
            for name in audit.teacher_label.SAMPLER_COUNTERS},
    }
    assert audit.continuation_telemetry_problems(fold) == []

    changed = copy.deepcopy(fold)
    changed["continuation_telemetry"]["report_worlds"] -= 1
    assert "champion report-world dose" in \
        audit.continuation_telemetry_problems(changed)
    changed = copy.deepcopy(fold)
    changed["inner_sampler_counters"]["accepted_worlds"] -= 1
    assert "champion telemetry/inner-counter drift" in \
        audit.continuation_telemetry_problems(changed)

    # Retries survive fold aggregation without changing accepted-world dose.
    retried = copy.deepcopy(fold)
    retried["continuation_telemetry"].update({
        "report_sample_attempts": 602,
        "retry_attempts": 2,
        "sample_attempts": 662,
        "failed_worlds": 2,
        "rejected_worlds": 1,
    })
    retried["inner_sampler_counters"].update({
        "sample_attempts": 662,
        "failed_worlds": 2,
        "rejected_worlds": 1,
    })
    assert audit.continuation_telemetry_problems(retried) == []

    changed = copy.deepcopy(retried)
    changed["continuation_telemetry"]["retry_attempts"] = 1
    assert "champion retry accounting" in \
        audit.continuation_telemetry_problems(changed)


def test_retry_count_survives_synthetic_fold_shard_and_gate(monkeypatch):
    telemetry = {
        name: 0 for name in audit.CHAMPION_TELEMETRY_FIELDS}
    telemetry.update({
        "decisions": 1,
        "searched_decisions": 1,
        "selection_worlds": 30,
        "report_worlds": 300,
        "selection_candidate_rollouts": 90,
        "report_candidate_rollouts": 600,
        "total_candidate_rollouts": 690,
        "selection_sample_attempts": 30,
        "report_sample_attempts": 301,
        "retry_attempts": 1,
        "sample_attempts": 331,
        "accepted_worlds": 330,
        "failed_worlds": 1,
    })
    inner = {
        name: telemetry[name]
        for name in audit.teacher_label.SAMPLER_COUNTERS}
    fold = {
        "continuation_execution_lock": audit.CONTINUATION_EXECUTION_LOCK,
        "continuation_telemetry": telemetry,
        "inner_sampler_counters": inner,
    }
    assert audit.continuation_telemetry_problems(fold) == []

    monkeypatch.setattr(audit, "champion_regret", lambda *_args: {
        "passed": True, "inconclusive": False, "problems": []})
    receipt = {
        "run_id": "synthetic-v3",
        "audit_state_set": {"sha256": "a" * 64},
        "stage_b_state_set": {"sha256": "b" * 64},
    }
    receipt_binding = {"sha256": "c" * 64}
    context = {"parents": {
        "cheap_by": {}, "gold_by": {},
        "stage_b_gate_item": {"sha256": "d" * 64},
        "cheap_items": [], "gold_items": [],
    }}
    payload = audit.build_gate_payload(
        receipt=receipt,
        receipt_binding=receipt_binding,
        context=context,
        shard_items=[{"sha256": "e" * 64}],
        manifests=[{
            "continuation_telemetry": telemetry,
            "outer_candidate_world_work": 0,
            "continuation_candidate_rollouts": 690,
            "total_rollout_work": 690,
        }],
        records=[], input_problems=[], runtime={"tree_dirty": False},
        sources={"audit": "source"},
    )
    assert payload["continuation_telemetry"]["accepted_worlds"] == 330
    assert payload["continuation_telemetry"]["retry_attempts"] == 1
    assert payload["continuation_telemetry"]["failed_worlds"] == 1

    malformed = audit.build_gate_payload(
        receipt=receipt,
        receipt_binding=receipt_binding,
        context=context,
        shard_items=[{"sha256": "e" * 64}],
        manifests=[{
            "continuation_telemetry": {},
            "outer_candidate_world_work": 0,
            "continuation_candidate_rollouts": 690,
            "total_rollout_work": 690,
        }],
        records=[], input_problems=[], runtime={"tree_dirty": False},
        sources={"audit": "source"},
    )
    assert malformed["verdict"] == "INCONCLUSIVE"
    assert "audit gate continuation telemetry schema" in \
        malformed["problems"]

    missing_count = copy.deepcopy(payload)
    missing_count.pop("continuation_telemetry")
    assert "audit gate full recomputation drift" in \
        audit.gate_payload_problems(missing_count, payload)


def test_selected_parent_join_binds_state_candidates_and_frozen_indices():
    states, problems = audit.select_states(parent_states())
    assert problems == []
    cheap = [{
        "state_id": state["state_id"], "state": state,
        "candidates": [["A"], ["K"]], "cheap_selected_index": 0,
    } for state in states]
    gold = [{
        "state_id": state["state_id"], "state": state,
        "candidates": [["A"], ["K"]], "gold_reference_index": 1,
    } for state in states]
    joined = audit.selected_parent_records(states, cheap, gold)
    assert len(joined) == audit.AUDIT_STATES

    changed = copy.deepcopy(gold)
    changed[0]["candidates"].reverse()
    with pytest.raises(audit.TeacherProtocolError, match="candidate order"):
        audit.selected_parent_records(states, cheap, changed)
    changed = copy.deepcopy(gold)
    changed[0]["gold_reference_index"] = 2
    with pytest.raises(audit.TeacherProtocolError, match="action index"):
        audit.selected_parent_records(states, cheap, changed)


def test_audit_record_uses_audit_domain_and_disjoint_reference_fold(
        monkeypatch):
    state = {
        "experiment_id": "teacher-v1",
        "state_id": "149000001:1:0",
        "seed": 149000001,
        "seat": 0,
        "split": "train",
        "kind": "representative",
        "phase": "early",
        "role": "attacker",
        "decision": "lead",
    }
    cheap = {
        "state_id": state["state_id"], "deal_seed": state["seed"],
        "split": state["split"], "kind": state["kind"],
        "stratum": {"phase": "early", "role": "attacker",
                    "decision": "lead"},
        "state": state, "replay_digest": stable_digest(state),
        "ballot_spec": {"digest": "ballot"},
        "candidates": [["A"], ["K"]], "candidate_count": 2,
        "cheap_selected_index": 0,
    }
    gold = {
        "state_id": state["state_id"], "state": state,
        "candidates": [["A"], ["K"]], "gold_reference_index": 1,
    }
    seen = []

    def fake_draw(_sampler, _rnd, _seat, count, **identity):
        seen.append(identity)
        return [(None, None)] * count, {
            "requested_worlds": count,
            "stream": {"seed": len(seen)},
            "draw_ids": [f"{identity['fold']}-{i}" for i in range(count)],
            "world_digests": [f"world-{i}" for i in range(count)],
            "sampler_counters": {
                "sample_attempts": count, "accepted_worlds": count,
                "failed_worlds": 0, "rejected_worlds": 0,
                "impossible_worlds": 0, "short_search_decisions": 0,
                "zero_world_decisions": 0,
            },
        }

    def fake_score(_rnd, _seat, _candidates, _worlds, meta, *, fold,
                   **_kwargs):
        utility = [[0.0, 1.0], [0.0, 1.0]]
        return {
            **meta,
            "tensor": {"signed_level_utility": utility},
            "inner_sampler_counters": {
                name: 0 for name in audit.teacher_label.SAMPLER_COUNTERS},
            "continuation_telemetry": {
                name: 0 for name in audit.CHAMPION_TELEMETRY_FIELDS},
            "fold": fold,
        }

    monkeypatch.setattr(audit.teacher_label, "replay_state", lambda _state: object())
    monkeypatch.setattr(audit.teacher_label, "ballot_problems", lambda *_args: [])
    monkeypatch.setattr(audit.teacher_label, "draw_common_worlds", fake_draw)
    monkeypatch.setattr(audit, "score_champion_fold", fake_score)
    record = audit.audit_record(
        cheap, gold, object(), {
            "champion_selection": 2, "champion_report": 2})
    assert [identity["experiment_id"] for identity in seen] == [
        audit.AUDIT_ID, audit.AUDIT_ID]
    assert [identity["fold"] for identity in seen] == [
        "champion_selection", "champion_report"]
    assert record["champion_reference_index"] == 1
    assert record["champion_report_regret"]["cheap"]["mean"] == 1.0
    assert record["champion_report_regret"]["n30"]["mean"] == 0.0


def audit_gate_records(cheap_regret: float, n30_regret: float) -> list[dict]:
    selected, problems = audit.select_states(parent_states())
    assert problems == []
    return [{
        "state_id": state["state_id"],
        "deal_seed": state["seed"],
        "kind": state["kind"],
        "stratum": {
            "phase": state["phase"], "role": state["role"],
            "decision": state["decision"],
        },
        "champion_report_regret": {
            "cheap": {"mean": cheap_regret},
            "n30": {"mean": n30_regret},
        },
    } for state in selected]


def test_champion_gate_requires_both_choices_on_all_and_representative(
        monkeypatch):
    monkeypatch.setattr(audit, "audit_record_problems", lambda *_args: [])
    records = audit_gate_records(0.05, 0.02)
    cheap_by = {record["state_id"]: {} for record in records}
    gold_by = {record["state_id"]: {} for record in records}
    result = audit.champion_regret(records, cheap_by, gold_by)
    assert result["passed"] is True
    assert result["choices"]["cheap"]["all_64"]["upper_95"] == 0.05
    assert result["choices"]["n30"]["representative_48"]["passed"] is True

    changed = copy.deepcopy(records)
    for record in changed:
        if record["kind"] == "representative":
            record["champion_report_regret"]["n30"]["mean"] = 0.20
    result = audit.champion_regret(changed, cheap_by, gold_by)
    assert result["passed"] is False
    assert result["choices"]["n30"]["representative_48"]["passed"] is False


def test_receipt_contract_binds_runtime_sources_and_exact_parents():
    runtime = {
        "git": "a" * 40, "tree_dirty": False, "promotable": True,
        "host": "air", "python": "3.14.6", "fast_engine": True,
        "require_voids": True, "experimental_sampler_ballot_flags": [],
    }
    items = [{
        "path": f"shard-{index}.json",
        "sha256": stable_digest({"shard": index}),
        "shard_index": index,
    } for index in range(audit.AUDIT_SHARDS)]
    sources = {"audit_script": "1" * 64}
    payload = {
        "schema": audit.AUDIT_RECEIPT_SCHEMA,
        "audit_id": audit.AUDIT_ID,
        "complete": True,
        "run_id": "audit-run-0001",
        "nonce": "b" * 64,
        "shard_count": audit.AUDIT_SHARDS,
        "folds": audit.AUDIT_FOLDS,
        "continuation_contract": audit.CONTINUATION_CONTRACT,
        "continuation_execution_lock": audit.CONTINUATION_EXECUTION_LOCK,
        "state_selection_read_label_outcomes": False,
        **runtime,
        "source_digests": sources,
        "execution_predeclaration": {
            "git": runtime["git"],
            "audit_script_sha256": sources["audit_script"],
        },
        "stage_b_state_set": {
            "path": "stage-b.json", "sha256": audit.STAGE_B_STATE_SHA256},
        "audit_state_set": {
            "path": "audit-states.json", "sha256": "c" * 64},
        "stage_b_gate": {"path": "stage-b-gate.json", "sha256": "d" * 64},
        "cheap_inputs": items,
        "n30_inputs": copy.deepcopy(items),
    }
    assert audit.audit_receipt_problems(
        payload, runtime=runtime, sources=sources) == []
    changed = copy.deepcopy(payload)
    changed["n30_inputs"][0]["sha256"] = "not-a-hash"
    assert "audit receipt n30_inputs" in audit.audit_receipt_problems(
        changed, runtime=runtime, sources=sources)
    changed = copy.deepcopy(payload)
    changed["state_selection_read_label_outcomes"] = True
    assert "audit receipt outcome-blind state-selection claim" in \
        audit.audit_receipt_problems(
            changed, runtime=runtime, sources=sources)
    changed = copy.deepcopy(payload)
    changed["execution_predeclaration"]["git"] = "f" * 40
    assert "audit receipt exact execution predeclaration" in \
        audit.audit_receipt_problems(
            changed, runtime=runtime, sources=sources)


def test_receipt_creator_reopens_its_own_post_link_partial(
        tmp_path, monkeypatch):
    runtime = {
        "git": "a" * 40, "tree_dirty": True, "promotable": False,
        "host": "smoke", "python": "3.14.6", "fast_engine": True,
        "require_voids": True, "experimental_sampler_ballot_flags": [],
    }
    sources = {"audit_script": "b" * 64}
    parents = {
        "stage_b_gate_item": {"path": "gate.json", "sha256": "c" * 64},
        "cheap_items": [], "gold_items": [],
    }
    context = {
        "audit_state_set": {"states": []},
        "parents": parents,
    }
    monkeypatch.setattr(audit, "runtime_contract", lambda **_kwargs: runtime)
    monkeypatch.setattr(audit, "source_digests", lambda: sources)
    monkeypatch.setattr(audit, "load_audit_context", lambda **_kwargs: context)
    monkeypatch.setattr(
        audit, "context_from_receipt", lambda *_args, **_kwargs: context)
    monkeypatch.setattr(
        audit, "audit_receipt_problems", lambda *_args, **_kwargs: [])

    output = tmp_path / "receipt.json"
    audit.create_receipt(SimpleNamespace(
        smoke=True,
        run_id="audit-publication-smoke",
        stage_b_state_set="stage-b-states.json",
        expected_stage_b_state_set_sha256="d" * 64,
        audit_state_set="audit-states.json",
        expected_audit_state_set_sha256="e" * 64,
        cheap=[], expected_cheap_sha256=[],
        n30=[], expected_n30_sha256=[],
        stage_b_gate="stage-b-gate.json",
        expected_stage_b_gate_sha256="f" * 64,
        expected_audit_git=None,
        expected_audit_script_sha256=None,
        out=str(output),
    ))

    assert output.is_file()
    assert not Path(str(output) + ".partial").exists()


def test_receipt_publication_reopen_rejects_unrelated_partial(tmp_path):
    output = tmp_path / "receipt.json"
    partial = tmp_path / "receipt.json.partial"
    raw = b'{"complete":true}\n'
    output.write_bytes(raw)
    partial.write_bytes(raw)

    with pytest.raises(
            audit.TeacherProtocolError,
            match="artifact final/partial are not one hard-link pair"):
        audit.load_pinned_publication_pair(
            str(output), audit.sha256_file(output))


def test_audit_shard_recomputes_partition_and_totals(monkeypatch):
    monkeypatch.setattr(audit, "audit_record_problems", lambda *_args: [])
    selected, problems = audit.select_states(parent_states())
    assert problems == []
    shard_states = audit.teacher_label.canonical_state_partition(
        selected, 0, audit.AUDIT_SHARDS)
    zero_counters = {
        name: 0 for name in audit.teacher_label.SAMPLER_COUNTERS}
    zero_telemetry = {
        name: 0 for name in audit.CHAMPION_TELEMETRY_FIELDS}
    records = [{
        "state_id": state["state_id"],
        "outer_sampler_counters": zero_counters,
        "inner_sampler_counters": zero_counters,
        "continuation_telemetry": zero_telemetry,
        "outer_candidate_world_work": 0,
        "continuation_candidate_rollouts": 0,
        "total_rollout_work": 0,
    } for state in shard_states]
    runtime = {
        "git": "a" * 40, "tree_dirty": False, "promotable": True,
        "host": "air", "python": "3.14.6", "fast_engine": True,
        "require_voids": True, "experimental_sampler_ballot_flags": [],
    }
    receipt_binding = {
        "path": "receipt.json", "sha256": "e" * 64,
        "run_id": "audit-run-0001", "nonce": "f" * 64,
    }
    receipt = {
        "run_id": receipt_binding["run_id"],
        "audit_state_set": {"path": "states.json", "sha256": "b" * 64},
    }
    parents = {
        "stage_b_gate_item": {"path": "gate.json", "sha256": "c" * 64},
        "cheap_items": [], "gold_items": [],
        "cheap_by": {state["state_id"]: {} for state in selected},
        "gold_by": {state["state_id"]: {} for state in selected},
    }
    context = {
        "audit_state_set": {"states": selected}, "parents": parents}
    ids = [record["state_id"] for record in records]
    payload = {
        "schema": audit.AUDIT_SHARD_SCHEMA,
        "audit_id": audit.AUDIT_ID,
        "complete": True,
        **runtime,
        "source_digests": {"audit": "source"},
        "target_schema": audit.teacher_label.TARGET_SCHEMA,
        "producer_run_id": receipt["run_id"],
        "producer_receipt": receipt_binding,
        "audit_state_set": receipt["audit_state_set"],
        "stage_b_gate": parents["stage_b_gate_item"],
        "cheap_inputs": [], "n30_inputs": [],
        "folds_contract": audit.AUDIT_FOLDS,
        "continuation_contract": audit.CONTINUATION_CONTRACT,
        "continuation_execution_lock": audit.CONTINUATION_EXECUTION_LOCK,
        "shard_index": 0, "shard_count": audit.AUDIT_SHARDS,
        "state_partition": {
            "assignment": "sorted_state_id_then_interleaved_position",
            "shard_index": 0, "shard_count": audit.AUDIT_SHARDS,
            "state_ids": ids, "state_ids_sha256": stable_digest(ids),
        },
        "n_records": len(records), "records": records,
        "records_digest": audit.audit_records_digest(records),
        "outer_sampler_counters": zero_counters,
        "inner_sampler_counters": zero_counters,
        "continuation_telemetry": zero_telemetry,
        "outer_candidate_world_work": 0,
        "continuation_candidate_rollouts": 0,
        "total_rollout_work": 0,
    }
    assert audit.audit_shard_problems(
        payload, receipt=receipt, receipt_binding=receipt_binding,
        context=context, runtime=runtime, sources={"audit": "source"},
        smoke=False) == []

    changed = copy.deepcopy(payload)
    changed["records"][0], changed["records"][1] = (
        changed["records"][1], changed["records"][0])
    changed["records_digest"] = audit.audit_records_digest(changed["records"])
    assert "audit shard exact state partition" in audit.audit_shard_problems(
        changed, receipt=receipt, receipt_binding=receipt_binding,
        context=context, runtime=runtime, sources={"audit": "source"},
        smoke=False)


def test_audit_freeze_publishes_and_reopens_exact_bytes(tmp_path, monkeypatch):
    rows = parent_states()
    parent = {
        "schema": audit.STATE_SET_SCHEMA,
        "packet_id": audit.CAPTURE_PACKET_ID,
        "stage": "b", "complete": True,
        "states": rows, "states_digest": stable_digest(rows),
    }
    parent_path = tmp_path / "stage-b.json"
    parent_path.write_text(json.dumps(parent, sort_keys=True) + "\n")
    parent_sha = audit.sha256_file(parent_path)
    output = tmp_path / "audit-states.json"
    runtime = {
        "git": "a" * 40, "tree_dirty": True, "promotable": False,
        "host": "smoke", "python": "3.14.6", "fast_engine": True,
        "require_voids": True, "experimental_sampler_ballot_flags": [],
    }
    monkeypatch.setattr(audit, "STAGE_B_STATE_SHA256", parent_sha)
    monkeypatch.setattr(audit, "runtime_contract", lambda **_kwargs: runtime)
    monkeypatch.setattr(audit, "source_digests", lambda: {"audit": "source"})
    monkeypatch.setattr(
        audit.teacher_label, "state_set_problems", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(audit.teacher_label, "replay_state", lambda _state: None)
    audit.freeze(SimpleNamespace(
        smoke=True,
        stage_b_state_set=str(parent_path),
        expected_stage_b_state_set_sha256=parent_sha,
        out=str(output),
    ))
    assert output.exists()
    assert not Path(str(output) + ".partial").exists()
    payload = json.loads(output.read_text())
    assert payload["selected"] == 64
    assert payload["stage_b_parent"]["sha256"] == parent_sha
    assert audit.audit_state_set_problems(payload, parent, parent_sha) == []
