from __future__ import annotations

import copy
import json

import pytest

from scripts import production_llm_panel_readout as readout
from scripts.production_llm_tool_sensitivity import (
    PROPOSED_AMENDMENT,
    ToolSensitivityError,
    analyze_panel_tool_sensitivity,
)

from test_benchmark_rollout_proof import _evidence
from test_production_llm_panel_readout import ROOTS, SEEDS, SOURCE_SHA, _panel


def _decoded_panel(tmp_path):
    locations = _panel(tmp_path)
    reports = {
        policy: json.loads((location / "result.json").read_text())
        for policy, location in locations.items()
    }
    contexts = {
        policy: {
            "seeds": list(SEEDS),
            "source_result_sha256": SOURCE_SHA,
            "root_hashes": dict(ROOTS),
        }
        for policy in readout.POLICIES
    }
    return reports, contexts


def _empty_evidence():
    return {policy: {} for policy in readout.POLICIES}


def _row(report, information, seed, flip):
    return next(
        row
        for row in report["mirrors"]
        if row["information"] == information
        and row["seed"] == seed
        and row["flip"] == flip
    )


def _install_tool_row(reports, policy, seed, proof):
    report = reports[policy]
    original = _row(report, "perfect", seed, 1)
    index = report["mirrors"].index(original)
    # Keep the producer-owned mirror identity while importing the actual
    # diagnostic/call receipt from the real fake-provider transport fixture.
    replacement = {
        key: copy.deepcopy(value)
        for key, value in original.items()
        if key != "signed_levels"
    }
    replacement.update(copy.deepcopy(proof["row"]))
    replacement.update(
        schema=original["schema"],
        key=original["key"],
        arm=original["arm"],
        model=original["model"],
        information="perfect",
        seed=seed,
        flip=1,
    )
    report["mirrors"][index] = replacement
    return {
        ("perfect", seed, 1): {
            "packet_bytes": proof["packet_bytes"],
            "final_bytes": proof["final_bytes"],
        }
    }


def _comparison(result, left, right):
    return next(
        item
        for item in result["row_differences"]
        if item["left"] == left and item["right"] == right
    )


def test_decoded_panel_has_exact_baseline_contrasts_without_filesystem_access(
    tmp_path, monkeypatch
):
    reports, contexts = _decoded_panel(tmp_path)
    # Exercise seed-keyed joins even though every decoded producer report is
    # complete: each policy has a different mirror order.
    for index, policy in enumerate(readout.POLICIES):
        reports[policy]["mirrors"] = (
            reports[policy]["mirrors"][index:]
            + reports[policy]["mirrors"][:index]
        )
    evidence = _empty_evidence()
    before = (copy.deepcopy(reports), copy.deepcopy(contexts), copy.deepcopy(evidence))

    def filesystem_forbidden(*args, **kwargs):
        raise AssertionError("panel sensitivity must consume decoded reports only")

    monkeypatch.setattr(readout, "_read_json", filesystem_forbidden)
    baseline = readout.analyze_panel_reports(reports, contexts)
    result = analyze_panel_tool_sensitivity(
        reports,
        contexts,
        evidence=evidence,
        amendment=PROPOSED_AMENDMENT,
    )

    assert result["baseline"] == baseline
    assert len(result["row_differences"]) == 36
    for expected, actual in zip(baseline["row_differences"], result["row_differences"]):
        assert (actual["left"], actual["right"]) == (expected["left"], expected["right"])
        for mode in ("sol", "pt_sol"):
            endpoint = actual[mode]
            assert endpoint["primary"] == expected[mode]
            assert endpoint["sensitivity"] == expected[mode]
            assert endpoint["primary_paired_seeds"] == SEEDS
            assert endpoint["sensitivity_paired_seeds"] == SEEDS
            assert endpoint["excluded_tool_pair_seeds"] == []
            assert endpoint["mean_sign_change"] is False
    assert (reports, contexts, evidence) == before


def test_tool_pair_exclusion_is_union_keyed_and_preserves_arithmetic(tmp_path):
    reports, contexts = _decoded_panel(tmp_path)
    left_proof = _evidence(tmp_path, lead=False)
    right_proof = _evidence(tmp_path, lead=False)
    evidence = _empty_evidence()
    evidence["smv3-pv"] = _install_tool_row(reports, "smv3-pv", 0, left_proof)
    evidence["soft-pv"] = _install_tool_row(reports, "soft-pv", 1, right_proof)
    before = (copy.deepcopy(reports), copy.deepcopy(contexts), copy.deepcopy(evidence))

    result = analyze_panel_tool_sensitivity(
        reports,
        contexts,
        evidence=evidence,
        amendment=PROPOSED_AMENDMENT,
    )
    comparison = _comparison(result, "smv3-pv", "soft-pv")

    # The real proof fixture is a perfect-information mirror, so only the
    # pt-Sol endpoint has the two tool-affected pair seeds.
    assert comparison["sol"]["primary_paired_seeds"] == SEEDS
    assert comparison["sol"]["sensitivity_paired_seeds"] == SEEDS
    assert comparison["sol"]["excluded_tool_pair_seeds"] == []
    assert comparison["sol"]["primary"] == readout._contrast([1.0] * 10)
    assert comparison["sol"]["sensitivity"] == readout._contrast([1.0] * 10)
    assert comparison["pt_sol"]["primary_paired_seeds"] == SEEDS
    assert comparison["pt_sol"]["sensitivity_paired_seeds"] == list(range(2, 10))
    assert comparison["pt_sol"]["excluded_tool_pair_seeds"] == [0, 1]
    assert comparison["pt_sol"]["primary"] == readout._contrast([-1.0, 0.0] + [-1.0] * 8)
    assert comparison["pt_sol"]["sensitivity"] == readout._contrast([-1.0] * 8)
    assert comparison["pt_sol"]["mean_sign_change"] is False
    assert result["policies"]["smv3-pv"]["modes"]["perfect"]["primary_paired_seeds"] == SEEDS
    assert result["policies"]["soft-pv"]["modes"]["perfect"]["primary_paired_seeds"] == SEEDS
    assert (reports, contexts, evidence) == before


def test_pending_pair_is_not_imputed(tmp_path):
    reports, contexts = _decoded_panel(tmp_path)
    pending = _row(reports["smv3-pv"], "actor-only", 3, 1)
    pending.update(complete=False, status="not_run", calls=[], events=[])
    pending.pop("signed_levels")

    result = analyze_panel_tool_sensitivity(
        reports,
        contexts,
        evidence=_empty_evidence(),
        amendment=PROPOSED_AMENDMENT,
    )
    mode = result["policies"]["smv3-pv"]["modes"]["actor-only"]
    comparison = _comparison(result, "smv3-pv", "soft-pv")["sol"]
    assert mode["primary_paired_seeds"] == [seed for seed in SEEDS if seed != 3]
    assert mode["sensitivity"]["count"] == 9
    assert comparison["primary_paired_seeds"] == [seed for seed in SEEDS if seed != 3]
    assert comparison["primary"]["count"] == 9
    assert 3 not in comparison["primary"]["values"]


@pytest.mark.parametrize("mutation", ["mismatched-root", "missing-policy", "extra-evidence"])
def test_panel_shape_and_identity_mismatches_refuse(tmp_path, mutation):
    reports, contexts = _decoded_panel(tmp_path)
    evidence = _empty_evidence()
    if mutation == "mismatched-root":
        contexts["smart"]["root_hashes"]["0"] = "b" * 64
    elif mutation == "missing-policy":
        reports.pop("smart")
    else:
        evidence["unexpected"] = {}
    with pytest.raises(ValueError):
        analyze_panel_tool_sensitivity(
            reports,
            contexts,
            evidence=evidence,
            amendment=PROPOSED_AMENDMENT,
        )


def test_unknown_failure_without_structured_proof_refuses(tmp_path):
    reports, contexts = _decoded_panel(tmp_path)
    row = _row(reports["smv3-pv"], "actor-only", 0, 0)
    row.update(complete=False, error="RuntimeError: provider")
    row.pop("signed_levels")
    with pytest.raises(ToolSensitivityError):
        analyze_panel_tool_sensitivity(
            reports,
            contexts,
            evidence=_empty_evidence(),
            amendment=PROPOSED_AMENDMENT,
        )


def test_pairwise_mean_sign_warning_and_pending_exclusion(tmp_path):
    reports, contexts = _decoded_panel(tmp_path)
    for policy, score in (("smv3-pv", -.1), ("soft-pv", -.12)):
        for row in reports[policy]["mirrors"]:
            row["signed_levels"] = score
    evidence = _empty_evidence()
    evidence["smv3-pv"] = _install_tool_row(
        reports, "smv3-pv", 0, _evidence(tmp_path, lead=False))
    result = analyze_panel_tool_sensitivity(
        reports, contexts, evidence=evidence, amendment=PROPOSED_AMENDMENT)
    endpoint = _comparison(result, "smv3-pv", "soft-pv")["pt_sol"]
    assert endpoint["primary"]["mean"] == pytest.approx(.025)
    assert endpoint["sensitivity"]["mean"] == pytest.approx(-.02)
    assert endpoint["mean_sign_change"] is True
    assert endpoint["removed_scored_pair_seeds"] == [0]

    pending = _row(reports["soft-pv"], "perfect", 0, 0)
    pending.update(complete=False, status="not_run", calls=[], events=[])
    pending.pop("signed_levels")
    result = analyze_panel_tool_sensitivity(
        reports, contexts, evidence=evidence, amendment=PROPOSED_AMENDMENT)
    endpoint = _comparison(result, "smv3-pv", "soft-pv")["pt_sol"]
    assert endpoint["excluded_tool_pair_seeds"] == [0]
    assert endpoint["removed_scored_pair_seeds"] == []
    assert endpoint["primary"]["count"] == endpoint["sensitivity"]["count"] == 9
    assert endpoint["primary"] == endpoint["sensitivity"]
