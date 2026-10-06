from __future__ import annotations

import copy

import pytest

from scripts.production_llm_tool_sensitivity import (
    PROPOSED_AMENDMENT,
    ToolSensitivityError,
    analyze_tool_sensitivity,
)
from test_benchmark_rollout_proof import _evidence


SEEDS = list(range(10))


def _complete(mode, seed, flip, score=1):
    return {
        "information": mode, "seed": seed, "flip": flip,
        "complete": True, "signed_levels": score,
        "calls": [], "events": [],
    }


def _pending(mode, seed, flip):
    return {
        "information": mode, "seed": seed, "flip": flip,
        "complete": False, "status": "not_run", "calls": [], "events": [],
    }


def _final_failure(mode, seed, flip):
    return {
        "information": mode, "seed": seed, "flip": flip,
        "complete": False, "error": "IllegalPlay: must follow",
        "events": [{"seat": flip, "attempted_cards": ["C2"]}], "calls": [],
        "failure": {
            "schema": "benchmark-action-failure-v1",
            "category": "model_illegal_action", "stage": "engine_play",
            "seat": flip, "attempted_cards": ["C2"], "event_index": 0,
        },
    }


def _schedule(*, pending=(), final_failures=(), tool=None, score=1):
    rows = []
    for mode in ("actor-only", "perfect"):
        for seed in SEEDS:
            for flip in (0, 1):
                identity = (mode, seed, flip)
                if identity in pending:
                    row = _pending(*identity)
                elif identity in final_failures:
                    row = _final_failure(*identity)
                else:
                    row = _complete(*identity, score=score)
                if tool is not None and identity == tool[:3]:
                    row = tool[3]
                rows.append(row)
    return rows


def _tool_schedule(tmp_path, *, mode="perfect", seed=0, flip=1):
    actual = _evidence(tmp_path, lead=False)
    row = copy.deepcopy(actual["row"])
    row.update(information=mode, seed=seed, flip=flip)
    rows = _schedule(tool=(mode, seed, flip, row))
    evidence = {(mode, seed, flip): {
        "packet_bytes": actual["packet_bytes"], "final_bytes": actual["final_bytes"],
    }}
    return rows, evidence


def test_actual_rollout_proof_drives_tool_sensitivity_and_drops_pair(tmp_path):
    rows, evidence = _tool_schedule(tmp_path)
    before = copy.deepcopy(rows)
    result = analyze_tool_sensitivity(rows, evidence=evidence, amendment=PROPOSED_AMENDMENT)
    mode = result["modes"]["perfect"]
    assert mode["counts"] == {
        "complete": 19, "final_action_illegal": 0,
        "tool_request_illegal": 1, "pending": 0,
    }
    assert mode["primary"]["count"] == 10
    assert mode["sensitivity"]["count"] == 9
    assert mode["dropped_tool_mirror_count"] == 1
    assert mode["dropped_pair_mirror_count"] == 2
    assert mode["dropped_tool_mirror_identities"] == [
        {"information": "perfect", "seed": 0, "flip": 1}
    ]
    assert mode["dropped_pair_mirror_identities"] == [
        {"information": "perfect", "seed": 0, "flip": 0},
        {"information": "perfect", "seed": 0, "flip": 1},
    ]
    assert mode["dropped_pair_seeds"] == [0]
    assert mode["retained_paired_seeds"] == list(range(1, 10))
    assert rows == before
    assert result["status"] == "scored-scenario"
    assert result["tier_comparison"] == "tier comparison unavailable; no ranking claim"


def test_final_action_forfeit_is_retained_by_sensitivity():
    rows = _schedule(final_failures={("actor-only", 0, 1)})
    result = analyze_tool_sensitivity(rows, evidence={}, amendment=PROPOSED_AMENDMENT)
    mode = result["modes"]["actor-only"]
    assert mode["counts"]["final_action_illegal"] == 1
    assert mode["primary"]["count"] == mode["sensitivity"]["count"] == 10
    assert mode["dropped_pair_count"] == 0


def test_pending_is_not_imputed_and_empty_sensitivity_is_none():
    pending = {("actor-only", seed, flip)
               for seed in SEEDS for flip in (0, 1)}
    rows = _schedule(pending=pending)
    result = analyze_tool_sensitivity(rows, evidence={}, amendment=PROPOSED_AMENDMENT)
    mode = result["modes"]["actor-only"]
    assert mode["counts"]["pending"] == 20
    assert mode["primary"]["count"] == 0
    assert mode["sensitivity"]["count"] == 0
    assert mode["sensitivity"]["mean"] is None
    assert result["status"] == "partial"


def test_no_tool_parity_uses_reader_contrast_exactly():
    from scripts import production_llm_panel_readout as readout

    result = analyze_tool_sensitivity(
        _schedule(score=1), evidence={}, amendment=PROPOSED_AMENDMENT)
    mode = result["modes"]["actor-only"]
    expected = readout._contrast([-1.0] * 10)
    assert mode["primary"] == expected
    assert mode["sensitivity"] == expected
    assert mode["mean_sign_change"] is False


def test_tool_scenario_can_reverse_mean_sign_without_approval(tmp_path):
    actual = _evidence(tmp_path, lead=False)
    rows = _schedule(score=0.1)
    evidence = {}
    for seed in range(4):
        identity = ("perfect", seed, 1)
        row = copy.deepcopy(actual["row"])
        row.update(information="perfect", seed=seed, flip=1)
        rows[20 + 2 * seed + 1] = row
        evidence[identity] = {
            "packet_bytes": actual["packet_bytes"],
            "final_bytes": actual["final_bytes"],
        }
    result = analyze_tool_sensitivity(rows, evidence=evidence, amendment=PROPOSED_AMENDMENT)
    mode = result["modes"]["perfect"]
    assert mode["primary"]["mean"] > 0
    assert mode["sensitivity"]["mean"] < 0
    assert mode["mean_sign_change"] is True


@pytest.mark.parametrize("mutate", [
    lambda rows: rows.pop(),
    lambda rows: rows.append(copy.deepcopy(rows[0])),
    lambda rows: rows[0].update(seed=True),
])
def test_schedule_shape_refuses(mutate):
    rows = _schedule()
    mutate(rows)
    with pytest.raises(ToolSensitivityError):
        analyze_tool_sensitivity(rows, evidence={}, amendment=PROPOSED_AMENDMENT)


def test_evidence_missing_extra_corrupt_and_bool_key_refuse(tmp_path):
    rows, evidence = _tool_schedule(tmp_path)
    with pytest.raises(ToolSensitivityError):
        analyze_tool_sensitivity(rows, evidence={}, amendment=PROPOSED_AMENDMENT)
    extra = dict(evidence)
    extra[("perfect", 0, 0)] = dict(next(iter(evidence.values())))
    with pytest.raises(ToolSensitivityError):
        analyze_tool_sensitivity(rows, evidence=extra, amendment=PROPOSED_AMENDMENT)
    corrupt = {key: dict(value) for key, value in evidence.items()}
    corrupt[next(iter(corrupt))]["packet_bytes"] += b" "
    with pytest.raises(ToolSensitivityError):
        analyze_tool_sensitivity(rows, evidence=corrupt, amendment=PROPOSED_AMENDMENT)
    with pytest.raises(ToolSensitivityError):
        analyze_tool_sensitivity(rows, evidence={("perfect", 0, True): next(iter(evidence.values()))},
                                 amendment=PROPOSED_AMENDMENT)


def test_unknown_generic_mixed_and_history_failures_refuse():
    rows = _schedule()
    rows[0].update(complete=False, error="RuntimeError: provider")
    with pytest.raises(ToolSensitivityError):
        analyze_tool_sensitivity(rows, evidence={}, amendment=PROPOSED_AMENDMENT)
    rows = _schedule()
    rows[0].update(complete=False, status="not_run", rollout_diagnostic={})
    with pytest.raises(ToolSensitivityError):
        analyze_tool_sensitivity(rows, evidence={}, amendment=PROPOSED_AMENDMENT)


def test_limits_scores_types_and_amendment():
    rows = _schedule(final_failures={
        (mode, seed, flip)
        for mode in ("actor-only", "perfect")
        for seed, flip in ((0, 0), (0, 1), (1, 0), (1, 1))
    })
    result = analyze_tool_sensitivity(rows, evidence={}, amendment=PROPOSED_AMENDMENT)
    assert result["failed"] == 8 and result["stop_required"] is True
    rows = _schedule(final_failures={
        ("actor-only", seed, flip)
        for seed in range(4) for flip in (0, 1)
    } | {("perfect", 0, 0)})
    with pytest.raises(ToolSensitivityError):
        analyze_tool_sensitivity(rows, evidence={}, amendment=PROPOSED_AMENDMENT)
    rows = _schedule()
    rows[0]["signed_levels"] = 10 ** 1000
    with pytest.raises(ToolSensitivityError):
        analyze_tool_sensitivity(rows, evidence={}, amendment=PROPOSED_AMENDMENT)
    with pytest.raises(ToolSensitivityError):
        analyze_tool_sensitivity(rows, evidence={}, amendment="adopted-v1")


def test_tool_row_with_non_null_status_or_final_failure_mixed_proof_refuses(tmp_path):
    rows, evidence = _tool_schedule(tmp_path)
    rows[0]["rollout_diagnostic"] = {}
    with pytest.raises(ToolSensitivityError):
        analyze_tool_sensitivity(rows, evidence=evidence, amendment=PROPOSED_AMENDMENT)


@pytest.mark.parametrize("change", [
    {"complete": True, "signed_levels": 1},
    {"status": "not_run", "calls": [], "events": []},
    {"failure": {}},
])
def test_mixed_tool_record_refuses_with_exact_evidence(tmp_path, change):
    rows, evidence = _tool_schedule(tmp_path)
    rows[21].update(change)
    with pytest.raises(ToolSensitivityError):
        analyze_tool_sensitivity(rows, evidence=evidence, amendment=PROPOSED_AMENDMENT)


def test_tool_plus_final_failures_share_ceiling_and_empty_sensitivity(tmp_path):
    rows, evidence = _tool_schedule(tmp_path)
    # Seven final-action failures plus one proven tool failure consume eight.
    for index in range(7):
        rows[index] = _final_failure("actor-only", index // 2, index % 2)
    for seed in range(1, 10):
        for flip in (0, 1):
            rows[20 + 2 * seed + flip] = _pending("perfect", seed, flip)
    result = analyze_tool_sensitivity(rows, evidence=evidence, amendment=PROPOSED_AMENDMENT)
    assert result["failed"] == 8 and result["stop_required"]
    arm = result["modes"]["perfect"]
    assert arm["primary"]["count"] == 1
    assert arm["sensitivity"]["count"] == 0
    assert arm["sensitivity"]["mean"] is None
    assert arm["mean_sign_change"] is None
    rows[7] = _final_failure("actor-only", 3, 1)
    with pytest.raises(ToolSensitivityError, match="shared failure limit"):
        analyze_tool_sensitivity(rows, evidence=evidence, amendment=PROPOSED_AMENDMENT)


@pytest.mark.parametrize("change", [
    lambda rows: rows.__setitem__(1, copy.deepcopy(rows[0])),
    lambda rows: rows[0].update(flip=2),
    lambda rows: rows[0].update(information="perfect"),
])
def test_same_length_schedule_corruption_refuses(change):
    rows = _schedule()
    change(rows)
    with pytest.raises(ToolSensitivityError):
        analyze_tool_sensitivity(rows, evidence={}, amendment=PROPOSED_AMENDMENT)


def test_tool_non_null_status_refuses(tmp_path):
    rows, evidence = _tool_schedule(tmp_path)
    tool = next(row for row in rows if row["information"] == "perfect" and row["seed"] == 0 and row["flip"] == 1)
    tool["status"] = "setup_failed"
    with pytest.raises(ToolSensitivityError):
        analyze_tool_sensitivity(rows, evidence=evidence, amendment=PROPOSED_AMENDMENT)
