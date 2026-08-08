"""Falsification tests for the score-redacted Suphx O0 runtime gate."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


pytest.importorskip("numpy")
pytest.importorskip("torch")

from shengji.rl import suphx_o0_preflight as preflight  # noqa: E402
from shengji.rl.exact_resume import state_digest  # noqa: E402


def _launcher():
    path = Path(__file__).parents[1] / "scripts" / \
        "suphx_o0_runtime_preflight.py"
    spec = importlib.util.spec_from_file_location("suphx_o0_launcher", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _endpoint(name: str, keep_probability: float) -> dict:
    deal_seed_digest = state_digest([
        preflight.derive_deal_seed(
            preflight.DEAL_STREAM_ROOT_SEED, sequence, 0)
        for sequence in range(preflight.PREFLIGHT_ITERATIONS)
    ])
    return {
        "name": name,
        "keep_probability": keep_probability,
        "iterations": preflight.PREFLIGHT_ITERATIONS,
        "rounds": preflight.PREFLIGHT_ITERATIONS,
        "temporary_training_updates": preflight.PREFLIGHT_ITERATIONS,
        "samples_by_iteration": [80, 82, 78],
        "samples_total": 240,
        "role_surface_counts": {
            key: 60 for key in preflight.EXPECTED_SURFACES},
        "deal_seed_digest": deal_seed_digest,
        "elapsed_seconds_by_iteration": [1.0, 1.1, 0.9],
        "collect_seconds_by_iteration": [0.7, 0.8, 0.6],
        "update_seconds_by_iteration": [0.2, 0.2, 0.2],
        "publication_seconds_by_iteration": [0.1, 0.1, 0.1],
        "total_elapsed_seconds": 3.1,
        "terminal_progress": {
            "next_iteration": preflight.PREFLIGHT_ITERATIONS,
            "next_batch": preflight.PREFLIGHT_ITERATIONS,
        },
        "complete": True,
    }


def _valid_payload() -> dict:
    sources = {
        "schema": "suphx-o0-material-source-identity-v1",
        "files": {"source.py": "a" * 64},
    }
    endpoints = [
        _endpoint("oracle", 1.0),
        _endpoint("public", 0.0),
    ]
    contract = preflight.preflight_contract(sources)
    payload = {
        "schema": preflight.PREFLIGHT_SCHEMA,
        "claim": (
            "score-redacted fixed-dose runtime mechanics only; "
            "recommendation is not launch authority"
        ),
        "complete": True,
        "score_redacted": True,
        "source_identity": sources,
        "contract": contract,
        "contract_sha256": state_digest(contract),
        "runtime": {
            "git": "b" * 40,
            "material_tree_clean": True,
            "host": "mini",
        },
        "initial_model_state_sha256": "c" * 64,
        "endpoints": endpoints,
        "preflight_elapsed_seconds": 6.5,
        "dose_recommendation": preflight._expected_dose(endpoints),
        "criteria": {},
        "passed": False,
        "temporary_training_updates": (
            preflight.PREFLIGHT_ITERATIONS * len(preflight.ENDPOINTS)),
        "terminal_candidates_retained": False,
        "o0_launch_authorized": False,
        "o1_authorized": False,
        "training_authorized": False,
        "production_promotion": False,
    }
    payload["criteria"] = preflight._expected_criteria(payload)
    payload["passed"] = all(payload["criteria"].values())
    return payload


def test_launcher_refuses_flags_before_importing_behavior_modules():
    launcher = _launcher()
    clean = {
        "SHENGJI_FAST": "1",
        "SHENGJI_REQUIRE_VOIDS": "1",
    }
    assert launcher.preimport_environment_problems(clean) == []
    for name in launcher.REFUSED_ENVIRONMENT_KEYS:
        problems = launcher.preimport_environment_problems({
            **clean, name: "0"})
        assert any(name in problem for problem in problems)
    assert launcher.preimport_environment_problems({})
    assert launcher.preimport_environment_problems({
        **clean, "SHENGJI_FAST": "0"})


def test_dose_formula_is_fixed_conservative_and_bounded():
    assert preflight.recommended_iterations(
        [100.0] * 3, [100.0] * 3) == 8
    assert preflight.recommended_iterations(
        [0.1] * 3, [0.1] * 3) == \
        preflight.MAX_RECOMMENDED_ITERATIONS
    with pytest.raises(preflight.SuphxO0PreflightError):
        preflight.recommended_iterations([1.0], [1.0])
    with pytest.raises(preflight.SuphxO0PreflightError):
        preflight.recommended_iterations([1.0, 0.0, 1.0], [1.0] * 3)


def test_valid_artifact_recomputes_every_gate_and_contains_no_result():
    payload = _valid_payload()
    assert payload["passed"] is True
    assert preflight.artifact_problems(payload) == []
    assert preflight._forbidden_result_paths(payload) == []
    assert payload["dose_recommendation"]["launch_authorized"] is False


@pytest.mark.parametrize(
    ("mutate", "needle"),
    [
        (lambda value: value.update(training_authorized=True), "authority"),
        (lambda value: value.update(terminal_candidates_retained=True),
         "authority"),
        (lambda value: value["dose_recommendation"].update(
            iterations_per_arm=63), "dose arithmetic"),
        (lambda value: value["endpoints"][0].update(loss=1.0),
         "result fields"),
        (lambda value: value["contract"].update(learning_rate=2e-3),
         "contract/source"),
    ],
)
def test_artifact_refuses_authority_arithmetic_results_and_contract_drift(
        mutate, needle):
    payload = _valid_payload()
    mutate(payload)
    assert any(needle in problem
               for problem in preflight.artifact_problems(payload))


def test_criteria_can_record_valid_terminal_fail_without_forging_pass():
    payload = _valid_payload()
    payload["endpoints"][1]["deal_seed_digest"] = "e" * 64
    payload["criteria"] = preflight._expected_criteria(payload)
    payload["passed"] = all(payload["criteria"].values())
    assert payload["criteria"]["shared_causal_deal_sequence"] is False
    assert payload["passed"] is False
    assert preflight.artifact_problems(payload) == []


def test_exclusive_publication_reopens_and_never_overwrites(tmp_path):
    payload = _valid_payload()
    output = tmp_path / "preflight.json"
    preflight._write_exclusive(output, payload)
    assert output.is_file()
    assert not Path(str(output) + ".partial").exists()
    with pytest.raises(
            preflight.SuphxO0PreflightError, match="already exists"):
        preflight._write_exclusive(output, payload)


def test_timing_validation_refuses_nonfinite_and_zero_iterations():
    payload = _valid_payload()
    payload["endpoints"][0]["elapsed_seconds_by_iteration"][0] = 0.0
    payload["dose_recommendation"] = preflight._expected_dose(
        payload["endpoints"])
    payload["criteria"] = preflight._expected_criteria(payload)
    payload["passed"] = all(payload["criteria"].values())
    assert payload["criteria"]["finite_score_redacted_timings"] is False
    assert payload["passed"] is False
    assert preflight.artifact_problems(payload) == []


def test_work_accounting_and_fixed_deal_identity_are_recomputed():
    payload = _valid_payload()
    payload["endpoints"][0]["samples_total"] += 1
    payload["criteria"] = preflight._expected_criteria(payload)
    payload["passed"] = all(payload["criteria"].values())
    assert payload["criteria"]["exact_work_accounting"] is False
    assert preflight.artifact_problems(payload) == []

    payload = _valid_payload()
    for endpoint in payload["endpoints"]:
        endpoint["deal_seed_digest"] = "f" * 64
    payload["criteria"] = preflight._expected_criteria(payload)
    payload["passed"] = all(payload["criteria"].values())
    assert payload["criteria"]["shared_causal_deal_sequence"] is False
    assert preflight.artifact_problems(payload) == []


def test_malformed_artifact_is_refused_without_validator_exception():
    assert preflight.artifact_problems({"endpoints": [{"name": []}]})
    assert preflight._verification_problems([]) == [
        "preflight artifact is not an object"]
