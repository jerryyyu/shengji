"""Mutation-falsifiable contract tests for the report-LCB teacher audit."""
from __future__ import annotations

import copy
import json
import sys
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import teacher_v1_champion_audit as audit  # noqa: E402
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
    }
    assert audit.live_continuation_contract() == audit.CONTINUATION_CONTRACT
    assert audit.AUDIT_FOLDS == {
        "champion_selection": 32,
        "champion_report": 32,
    }


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
