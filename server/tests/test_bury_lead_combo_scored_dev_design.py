from __future__ import annotations

import ast
import copy
import hashlib
import importlib.util
import json
import math
import os
import subprocess
import sys
from pathlib import Path

import pytest


SERVER = Path(__file__).resolve().parents[1]
SCRIPT = SERVER / "scripts/bury_lead_combo_scored_dev_design.py"
SPEC = importlib.util.spec_from_file_location(
    "bury_lead_combo_scored_dev_design", SCRIPT)
DESIGN = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(DESIGN)

EXPECTED_FILE_SHA256 = (
    "a79743a711137493ea77e9c0695022e5527618b925dc78bab500c72560292b92")
EXPECTED_INTERNAL_SHA256 = (
    "298d07e363766a8ba2b2772b7d0c3b0e3e2ac8db44dd1974dda967aa4a0f9180")


def _raw(value=None) -> bytes:
    value = DESIGN.build_design() if value is None else value
    return DESIGN._canonical(value) + b"\n"


def _rehash(value: dict) -> dict:
    value = copy.deepcopy(value)
    value.pop("internal_sha256", None)
    value["internal_sha256"] = DESIGN._digest(value)
    return value


def _frozen(path: Path, raw: bytes | None = None) -> str:
    raw = _raw() if raw is None else raw
    path.write_bytes(raw)
    path.chmod(0o444)
    return hashlib.sha256(raw).hexdigest()


def test_canonical_design_identity_and_literal_population() -> None:
    design = DESIGN.build_design()
    raw = _raw(design)
    assert hashlib.sha256(raw).hexdigest() == EXPECTED_FILE_SHA256
    assert design["internal_sha256"] == EXPECTED_INTERNAL_SHA256
    assert DESIGN.design_problems(design) == []

    population = design["population"]
    rows = population["rows"]
    assert len(rows) == 64
    assert sum(row["combo_count"] for row in rows) == 26_640
    assert sum(row["selection_group"] == "shape_rich" for row in rows) == 32
    assert sum(
        row["selection_group"] == "hash_uniform_anchor" for row in rows
    ) == 32
    assert rows[0] == {
        "deal_seed": 136000457,
        "combo_count": 592,
        "selection_group": "shape_rich",
        "selection_reason": "combo_count",
    }
    assert rows[-1] == {
        "deal_seed": 136000386,
        "combo_count": 345,
        "selection_group": "hash_uniform_anchor",
        "selection_reason": "uniform_anchor",
    }


def test_capacity_evidence_and_missing_identity_condition_are_exact() -> None:
    design = DESIGN.build_design()
    provenance = design["provenance"]
    result = provenance["capacity_result"]
    assert result["file_sha256"] == DESIGN.CAPACITY_FILE_SHA256
    assert result["internal_sha256"] == DESIGN.CAPACITY_INTERNAL_SHA256
    assert result["runtime"] == DESIGN.CAPACITY_RUNTIME
    assert set(result["runtime"]) == {
        "git", "tree_dirty", "python", "fast_binary_sha256",
        "population_source_sha256", "scorer_source_sha256",
        "continuation_source_sha256", "journal_source_sha256",
        "controller_source_sha256",
    }
    review = provenance["capacity_result_review"]
    assert review["comment_id"] == 5_280_799_087
    assert review["body_sha256"] == DESIGN.CAPACITY_REVIEW_BODY_SHA256
    assert "five source identities" in review["required_followup"]

    runtime = design["execution_specification"]["runtime"]
    assert runtime["capacity_evidence_identity_required"] == \
        DESIGN.CAPACITY_RUNTIME
    assert runtime["unchanged_execution_components_required"] == {
        field: DESIGN.CAPACITY_RUNTIME[field]
        for field in (
            "fast_binary_sha256", "population_source_sha256",
            "scorer_source_sha256", "continuation_source_sha256",
            "journal_source_sha256",
        )
    }
    assert runtime["capacity_controller_is_evidence_only"] is True
    assert runtime["new_fold_scorer_sha256"] == \
        "POPULATE_AND_REVIEW_IN_PACKET"
    assert runtime["new_controller_sha256"] == \
        "POPULATE_AND_REVIEW_IN_PACKET"


def test_fold_and_work_contract_is_exact_and_capacity_bounded() -> None:
    design = DESIGN.build_design()
    spec = design["execution_specification"]
    assert spec["modes"] == ["baseline", "all_boss", "boss_near"]
    assert spec["selection"]["worlds"] == 30
    assert spec["selection"]["base_seed"] == 20_260_814
    assert spec["report"]["worlds"] == 30
    assert spec["report"]["base_seed"] == 20_260_815
    assert spec["report"]["same_fixed_slots_across_modes"] is True
    assert spec["report"]["same_world_commitment_across_slots_and_modes"] \
        is True
    assert spec["report"]["same_sampler_delta_and_rng_final_across_modes"] \
        is True
    assert spec["report"]["selection_and_report_worlds_disjoint"] is True
    assert spec["report"]["slot_duplicates_preserved_for_exact_work"] is True

    work = spec["work"]
    assert work["baseline_selection_candidate_rollouts"] == 799_200
    assert work["report_slot_rollouts_per_mode"] == 5_760
    assert work["report_modes"] == 3
    assert work["total_candidate_rollouts"] == 816_480
    assert work["max_state_selection_rollouts"] == 17_760
    assert work["max_state_report_rollouts_per_mode"] == 90
    projected = float(spec["runtime"]["capacity_projection_seconds"])
    assert math.isclose(projected, 457.77825452702854, rel_tol=1e-15)
    assert projected < spec["runtime"]["maximum_wall_seconds"]


def test_selection_precedes_report_and_continuation_is_sensitivity_only() -> None:
    design = DESIGN.build_design()
    selection = design["execution_specification"]["selection"]
    report = design["execution_specification"]["report"]
    estimands = design["estimands"]
    assert selection["mode"] == "baseline"
    assert selection["candidate_zero_preserved"] is True
    assert selection["all_menu_slots_nonempty"] is True
    assert selection["menu_nesting_required"] == (
        "incumbent_live subset incumbent_widened subset expanded")
    assert report["slots"] == [
        "incumbent_live", "incumbent_widened", "expanded"]
    assert estimands["post_selection_report_values_only"] is True
    assert "same fixed report slots" in estimands["continuation_sensitivity"]
    assert design["decision_rule"]["advance_scope"].startswith(
        "design a fresh live-versus-source-versus-candidate-count-matched-random"
    )
    sealed = design["sealed_output_contract"]
    assert sealed["source_outcomes_read"] is False
    assert sealed["new_outcomes_computed"] is True
    assert sealed["new_outcomes_sealed_until_review"] is True
    assert sealed["attempted_and_actual_play_committed"] is True
    assert sealed["failed_throw_uses_engine_actual_result"] is True
    assert sealed["selected_slot_actions_only_hashed_in_supervisor"] is True
    assert sealed["interrupted_run_status"] == "HOLD"
    assert sealed["missing_only_resume_authorized"] is False
    assert sealed["aggregate_terminal_review_required"] is True
    scoring = estimands["scoring_contract"]
    assert scoring == {
        "bot_class": "MCS0ReportLCB",
        "baseline_rollout_policy_class": "HeuristicBot",
        "alternative_rollout_policy_class": "S6ThrowRolloutPolicy",
        "continuation_actor_visible": True,
        "recursive_mc_continuation": False,
        "level_objective": False,
        "exact_endgame": False,
        "perspective": "banker_value_is_negative_attacker_objective",
        "nonbaseline_play_calls_required_positive": True,
        "baseline_dose_required_null": True,
    }


def test_two_gate_sign_threshold_is_literal_and_conservative() -> None:
    design = DESIGN.build_design()
    rule = design["decision_rule"]
    assert rule["primary_gates"] == ["lead_source", "joint_bury_source"]
    assert rule["positive_state_threshold_each_gate"] == 41
    tail = sum(math.comb(64, index) for index in range(41, 65)) / 2**64
    assert tail == pytest.approx(0.0163828795494116)
    assert tail < 0.05 / 2
    assert "Bonferroni alpha 0.025" in rule["threshold_basis"]


@pytest.mark.parametrize(
    "field",
    sorted(DESIGN.CAPACITY_RUNTIME),
)
def test_each_capacity_runtime_identity_is_load_bearing(field: str) -> None:
    value = DESIGN.build_design()
    runtime = value["provenance"]["capacity_result"]["runtime"]
    runtime[field] = True if field == "tree_dirty" else "0" * 64
    value = _rehash(value)
    assert DESIGN.design_problems(value)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value["provenance"]["capacity_result"].__setitem__(
            "file_sha256", "0" * 64),
        lambda value: value["provenance"]["capacity_result_review"].__setitem__(
            "body_sha256", "0" * 64),
        lambda value: value["population"]["rows"][0].__setitem__(
            "deal_seed", value["population"]["rows"][1]["deal_seed"]),
        lambda value: value["population"]["rows"][0].__setitem__(
            "combo_count", 591),
        lambda value: value["population"]["rows"][0].__setitem__(
            "selection_group", "hash_uniform_anchor"),
        lambda value: value["population"].__setitem__(
            "selection_rows_sha256", "0" * 64),
        lambda value: value["execution_specification"]["modes"].reverse(),
        lambda value: value["execution_specification"]["selection"].__setitem__(
            "worlds", 29),
        lambda value: value["execution_specification"]["report"].__setitem__(
            "base_seed", 20_260_814),
        lambda value: value["execution_specification"]["report"].__setitem__(
            "same_world_commitment_across_slots_and_modes", False),
        lambda value: value["execution_specification"]["report"].__setitem__(
            "same_sampler_delta_and_rng_final_across_modes", False),
        lambda value: value["execution_specification"]["report"].__setitem__(
            "slot_duplicates_preserved_for_exact_work", False),
        lambda value: value["execution_specification"]["selection"].__setitem__(
            "menu_nesting_required", "none"),
        lambda value: value["execution_specification"]["work"].__setitem__(
            "total_candidate_rollouts", 816_479),
        lambda value: value["sealed_output_contract"].__setitem__(
            "supervisor_final_review_before_record_open", False),
        lambda value: value["sealed_output_contract"].__setitem__(
            "missing_only_resume_authorized", True),
        lambda value: value["sealed_output_contract"].__setitem__(
            "attempted_and_actual_play_committed", False),
        lambda value: value["estimands"].__setitem__(
            "post_selection_report_values_only", False),
        lambda value: value["estimands"]["scoring_contract"].__setitem__(
            "exact_endgame", True),
        lambda value: value["decision_rule"].__setitem__(
            "positive_state_threshold_each_gate", 40),
    ],
)
def test_rehashed_science_and_provenance_mutations_refuse(mutation) -> None:
    value = DESIGN.build_design()
    mutation(value)
    assert DESIGN.design_problems(_rehash(value))


def test_every_authority_bit_is_load_bearing() -> None:
    expected = DESIGN.build_design()
    authority = expected["maximum_pass_scope"]
    assert authority["controller_implementation_design_authorized"] is True
    assert all(
        item is False for key, item in authority.items()
        if key != "controller_implementation_design_authorized"
    )
    for field in authority:
        value = DESIGN.build_design()
        value["maximum_pass_scope"][field] = not authority[field]
        assert DESIGN.design_problems(_rehash(value))


@pytest.mark.parametrize(
    "field",
    ["actions", "hands", "buried", "attacker_points", "winner", "scores",
     "utility", "candidate_values", "world_values"],
)
def test_nested_outcome_aliases_refuse_even_when_rehashed(field: str) -> None:
    value = DESIGN.build_design()
    value["population"]["rows"][0][field] = 0
    problems = DESIGN.design_problems(_rehash(value))
    assert any("forbidden design field" in problem for problem in problems)


def test_design_module_has_no_gameplay_launch_or_write_surface() -> None:
    tree = ast.parse(SCRIPT.read_text())
    imported = set()
    called_attributes = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            called_attributes.add(node.func.attr)
    assert not any(
        name.startswith("shengji") or name.startswith("bury_lead_combo")
        for name in imported
    )
    assert "subprocess" not in imported
    assert not ({"write_bytes", "write_text", "mkdir", "link", "unlink",
                 "rename", "replace", "system", "popen"}
                & called_attributes)


def test_verify_accepts_only_exact_frozen_canonical_bytes(tmp_path: Path) -> None:
    path = tmp_path / "design.json"
    digest = _frozen(path)
    assert digest == EXPECTED_FILE_SHA256
    assert DESIGN.verify_design(path, digest) == DESIGN.build_design()

    path.chmod(0o644)
    with pytest.raises(DESIGN.DesignRefused, match="nonwritable"):
        DESIGN.verify_design(path, digest)


def test_verify_refuses_links_noncanonical_and_digest_drift(
        tmp_path: Path) -> None:
    source = tmp_path / "source.json"
    digest = _frozen(source)
    hardlink = tmp_path / "hard.json"
    os.link(source, hardlink)
    with pytest.raises(DESIGN.DesignRefused, match="unlinked"):
        DESIGN.verify_design(source, digest)
    hardlink.unlink()

    symlink = tmp_path / "sym.json"
    symlink.symlink_to(source)
    with pytest.raises(DESIGN.DesignRefused, match="cannot open design"):
        DESIGN.verify_design(symlink, digest)

    pretty = tmp_path / "pretty.json"
    raw = json.dumps(DESIGN.build_design(), indent=2).encode() + b"\n"
    pretty_digest = _frozen(pretty, raw)
    with pytest.raises(DESIGN.DesignRefused, match="not canonical"):
        DESIGN.verify_design(pretty, pretty_digest)

    exact = tmp_path / "exact.json"
    _frozen(exact)
    with pytest.raises(DESIGN.DesignRefused, match="SHA drifted"):
        DESIGN.verify_design(exact, "0" * 64)


@pytest.mark.parametrize(
    "raw, message",
    [
        (b'{"schema":"a","schema":"b"}\n', "duplicate JSON key"),
        (b'{"schema":NaN}\n', "non-finite JSON constant"),
    ],
)
def test_verify_refuses_duplicate_and_nonfinite_json(
        tmp_path: Path, raw: bytes, message: str) -> None:
    path = tmp_path / "bad.json"
    digest = _frozen(path, raw)
    with pytest.raises(DESIGN.DesignRefused, match=message):
        DESIGN.verify_design(path, digest)


def test_cli_build_is_byte_identical() -> None:
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "build"],
        check=True, capture_output=True)
    assert completed.stdout == _raw()
    assert completed.stderr == b""
