from __future__ import annotations

import copy
import os
from pathlib import Path
import subprocess
import sys

import pytest

import teacher_stage_c_expanded_uncertainty_report_controller as CTRL


def _diagnostic(candidate_count: int = 2) -> dict:
    means = [10.0, 15.0, *([9.0] * (candidate_count - 2))]
    return {
        "schema": "teacher-stage-c-uncertainty-selection-v1",
        "selection_only": True,
        "may_train_or_label": False,
        "evaluation_complete": True,
        "worlds": 30,
        "attempts": 30,
        "candidate_worlds": 30 * candidate_count,
        "sampler_counters": {
            "accepted_worlds": 30,
            "failed_worlds": 0,
            "impossible_worlds": 0,
            "rejected_worlds": 0,
            "sample_attempts": 30,
        },
        "means": means,
        "raw_best_index": 1,
        "paired_gap_vs_candidate0": 5.0,
        "paired_se_vs_candidate0": 1.0,
        "production_margin": 5.0,
        "margin_window": 2.5,
        "eligible": True,
    }


def _states() -> list[dict]:
    values = []
    for index in range(CTRL.TARGET_STATES):
        values.append({
            "state_id": f"uncertainty-{index:03d}",
            "seed": index,
            "split": "REPORT",
            "surface_type": "play",
            "stratum": CTRL.TARGET_STRATUM,
            "phase": ("early", "mid", "late")[index % 3],
            "role": ("attacker", "defender")[index % 2],
            "surface": ("lead", "follow")[index % 2],
            "candidates": [
                {"cards": ["C2"], "sources": ["live_production_ballot"]},
                {"cards": ["C3"], "sources": ["v11pair_top_proposal"]},
            ],
            "selection_diagnostic": _diagnostic(),
        })
    return values


def test_uncertainty_state_requires_exact_public_selection_predicate() -> None:
    state = _states()[0]
    CTRL._validate_uncertainty_state(state)

    mutation = copy.deepcopy(state)
    mutation["selection_diagnostic"]["raw_best_index"] = 0
    with pytest.raises(
            CTRL.ReportControllerRefused, match="capture predicate drift"):
        CTRL._validate_uncertainty_state(mutation)

    mutation = copy.deepcopy(state)
    mutation["candidates"][0]["sources"] = ["different_incumbent"]
    with pytest.raises(
            CTRL.ReportControllerRefused, match="candidate source drift"):
        CTRL._validate_uncertainty_state(mutation)


def test_report_schedule_spends_all_219_states_once(monkeypatch) -> None:
    states = _states()
    monkeypatch.setattr(CTRL, "_candidate_world_ceiling", lambda _state: 7)
    schedule = CTRL.build_report_schedule(states, surface="play")
    assert [shard["state_count"] for shard in schedule["shards"]] \
        == [28, 28, 28, 27, 27, 27, 27, 27]
    assert schedule["candidate_world_ceiling"] == 219 * 7
    assert schedule["stratum"] == CTRL.TARGET_STRATUM
    assert schedule["schedule_sha256"] == CTRL._manifest_hash({
        key: value for key, value in schedule.items()
        if key != "schedule_sha256"
    })

    with pytest.raises(CTRL.ReportControllerRefused, match="surface drift"):
        CTRL.build_report_schedule(states, surface="bury")


def test_power_summary_exposes_break_even_and_projected_power() -> None:
    summary = CTRL._value_summary([0.1, 0.2, 0.3, 0.4], report_supply=219)
    assert summary["mean"] == pytest.approx(0.25)
    assert summary["one_sided_95_lcb"] > 0
    assert summary["plugin_break_even_states"] >= 2
    assert summary["untouched_report_supply"] == 219
    assert summary["projected_normal_power"] > 0.99

    zero = CTRL._value_summary([0.0, 0.0], report_supply=219)
    assert zero["plugin_break_even_states"] is None
    assert zero["projected_normal_power"] == 0.0


def test_scope_contract_requires_online_public_reproduction() -> None:
    contract = CTRL.scope_policy_contract(_states())
    assert contract["report_evaluation_baseline_index"] == 0
    assert contract["capture_predicate"]["evaluator"] == "mc-strong"
    assert contract["capture_predicate"][
        "common_worlds_across_candidate_union"] == 30
    assert contract["candidate_source_contract"]["proposal_sources"] == [
        "v11pair_top_proposal",
        "named_structured_lead_or_follow_mechanism",
        "same_budget_random_diversifier",
    ]
    downstream = contract["downstream_composition_requirements"]
    assert downstream["recompute_predicate_online_from_public_information"] \
        is True
    assert downstream["model_direct_play_authorized"] is False
    assert downstream["scope_trigger_precedes_stage_c_model_proposal"] is True
    assert downstream["outside_scope_policy"] == "unchanged_mc_s0_report_lcb"
    assert downstream["preserve_complete_live_report_lcb_candidate_ballot"] \
        is True
    assert downstream["unchanged_live_policy_is_literal_fallback"] is True
    assert downstream["fresh_whole_game_screen_required"] is True


@pytest.mark.parametrize(("wrapper", "expressions", "expected"), [
    (
        "teacher_stage_c_expanded_uncertainty_report_runtime",
        ("wrapper.BASE.CTRL.RUN_ID", "wrapper.BASE.RECEIPT_SCHEMA"),
        (CTRL.RUN_ID, CTRL.RUNTIME_RECEIPT_SCHEMA),
    ),
    (
        "teacher_stage_c_expanded_uncertainty_report_supervisor",
        ("wrapper.BASE.CTRL.RUN_ID", "wrapper.BASE.SCHEMA",
         "wrapper.BASE.REVIEW_MARKER"),
        (CTRL.RUN_ID, CTRL.SUPERVISOR_SCHEMA,
         CTRL.SUPERVISOR_REVIEW_MARKER),
    ),
])
def test_wrappers_select_uncertainty_controller(
        wrapper: str, expressions: tuple[str, ...],
        expected: tuple[str, ...]) -> None:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join((
        str(CTRL.REPO / "server"), str(CTRL.REPO / "server/scripts")))
    code = f"import {wrapper} as wrapper; " + "; ".join(
        f"print({expression})" for expression in expressions)
    completed = subprocess.run(
        [sys.executable, "-c", code], cwd=CTRL.REPO, check=True,
        capture_output=True, text=True, env=env)
    assert tuple(completed.stdout.splitlines()) == expected


def test_runtime_contract_refuses_unreviewed_python(monkeypatch) -> None:
    monkeypatch.setattr(CTRL.BASE, "runtime_contract", lambda: {
        "host": "mini", "python": "3.14.3", "torch": "2.13.0",
        "numpy": "2.5.1", "device": "cpu", "cpu_threads": 1,
        "supervisor_signal_contract": {},
    })
    with pytest.raises(
            CTRL.ReportControllerRefused, match="Python 3.14.6"):
        CTRL.runtime_contract()
