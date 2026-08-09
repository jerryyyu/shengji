"""Falsification tests for the score-redacted O0-v2 Air preflight."""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest


np = pytest.importorskip("numpy")
torch = pytest.importorskip("torch")

from shengji.rl.selfplay_contract import CheckpointRef  # noqa: E402
from shengji.rl import suphx_o0_v2_preflight as preflight  # noqa: E402


_LAUNCHER_PATH = Path(__file__).resolve().parents[1] \
    / "scripts" / "suphx_o0_v2_preflight.py"
_LAUNCHER_SPEC = importlib.util.spec_from_file_location(
    "suphx_o0_v2_preflight_launcher_test", _LAUNCHER_PATH)
assert _LAUNCHER_SPEC is not None and _LAUNCHER_SPEC.loader is not None
launcher = importlib.util.module_from_spec(_LAUNCHER_SPEC)
_LAUNCHER_SPEC.loader.exec_module(launcher)


def _runtime():
    return {
        "git": "a" * 40,
        "material_tree_clean": True,
        "host": "Jerrys-MacBook-Air.local",
        "machine": "arm64",
        "python": "3.14.6",
        "python_executable": "/test/python3.14",
        "numpy": np.__version__,
        "torch": torch.__version__,
        "device": "cpu",
        "cpu_count": 10,
        "torch_num_threads": 1,
        "torch_num_interop_threads": 1,
        "fast_engine": True,
        "require_voids": True,
    }


def _endpoint(cell, arm):
    return {
        "cell": cell,
        "arm": arm,
        "iterations": 1,
        "rounds": 1,
        "temporary_updates": 1,
        "samples": 88,
        "role_surface_counts": {
            "attacker_lead": 8,
            "attacker_follow": 36,
            "defender_lead": 8,
            "defender_follow": 36,
        },
        "elapsed_seconds": 0.5,
        "deal_seed": preflight.CrossedCRNStreams(
            preflight.PREFLIGHT_CRN_SPEC,
            preflight.PREFLIGHT_SEED_INDEX,
            0,
        ).deal_seed(),
        "first_public_decision_key": "b" * 64,
        "decision_count": 88,
        "complete": True,
    }


@pytest.fixture
def synthetic_preflight(tmp_path, monkeypatch):
    out = tmp_path / "preflight.json"
    monkeypatch.setattr(preflight, "EXPECTED_PREFLIGHT_PATH", out)
    monkeypatch.setattr(preflight, "runtime_identity", _runtime)
    monkeypatch.setattr(
        preflight, "source_identity",
        lambda: {"schema": "test-sources", "files": {"x": "c" * 64}},
    )
    monkeypatch.setattr(
        preflight, "_run_endpoint",
        lambda _root, *, cell, arm: _endpoint(cell, arm),
    )
    monkeypatch.setattr(
        preflight, "_run_evaluation_timing", lambda _model: [0.1] * 4)
    return out


def test_contract_is_disposable_redacted_and_non_authorizing():
    contract = preflight._contract()
    assert contract["iterations_per_endpoint"] == 1
    assert contract["registered_training_iterations"] == 64
    assert contract["registered_training_endpoints"] == 32
    assert contract["registered_evaluation_rounds"] == 12_288
    assert contract["disposable_training_deal_seed"] \
        == preflight.CrossedCRNStreams(
            preflight.PREFLIGHT_CRN_SPEC,
            preflight.PREFLIGHT_SEED_INDEX,
            0,
        ).deal_seed()
    assert contract["parallel_jobs"] == 8
    assert all(value is False for value in
               contract["artifact_redaction"].values())
    assert contract["authority"] == {
        "packet_freeze_and_review_only": True,
        "training": False,
        "o1": False,
        "strength": False,
        "production": False,
    }


def test_preimport_launcher_pins_threads_and_refuses_experimental_flags():
    clean = dict(launcher.REQUIRED_ENVIRONMENT)
    assert launcher.preimport_environment_problems(clean) == []
    assert launcher.preimport_environment_problems({})
    for name in launcher.REQUIRED_ENVIRONMENT:
        drifted = {**clean, name: "0"}
        assert any(name in problem
                   for problem in launcher.preimport_environment_problems(
                       drifted))
    for name in launcher.REFUSED_ENVIRONMENT_KEYS:
        drifted = {**clean, name: "0"}
        assert any(name in problem
                   for problem in launcher.preimport_environment_problems(
                       drifted))


def test_synthetic_preflight_publishes_capacity_without_scores(
        synthetic_preflight):
    ref = preflight.run_preflight(synthetic_preflight)
    payload = preflight.verify_preflight(synthetic_preflight)
    assert ref == CheckpointRef.capture(synthetic_preflight)
    assert payload["passed"] is True
    assert payload["packet_freeze_and_review_authorized"] is True
    assert payload["temporary_training_updates"] == 4
    assert payload["temporary_models_retained"] is False
    assert payload["training_authorized"] is False
    assert payload["o1_authorized"] is False
    assert payload["strength_claim"] is False
    assert payload["production_promotion"] is False
    assert preflight._forbidden_paths(payload) == []


def test_coupling_requires_both_cells_and_exact_first_public_context():
    endpoints = [
        _endpoint(cell, arm)
        for cell in preflight.CELLS for arm in preflight.ARMS
    ]
    coupling = preflight._coupling(endpoints)
    assert all(all(values.values()) for values in coupling.values())
    changed = copy.deepcopy(endpoints)
    changed[0]["first_public_decision_key"] = "0" * 64
    coupling = preflight._coupling(changed)
    assert not coupling[changed[0]["cell"]][
        "first_public_decision_key_equal"]
    with pytest.raises(preflight.SuphxO0V2PreflightError):
        preflight._coupling(endpoints[:-1])


def test_criteria_reject_cross_cell_key_drift_and_wrong_disposable_deal():
    endpoints = [
        _endpoint(cell, arm)
        for cell in preflight.CELLS for arm in preflight.ARMS
    ]
    coupling = preflight._coupling(endpoints)
    _, criteria = preflight._projection_and_criteria(
        endpoints, [0.1] * 4, 1.0, coupling)
    assert all(criteria.values())

    cross_cell_key = copy.deepcopy(endpoints)
    for endpoint in cross_cell_key:
        if endpoint["cell"] == preflight.CELL_MARGIN:
            endpoint["first_public_decision_key"] = "a" * 64
    _, criteria = preflight._projection_and_criteria(
        cross_cell_key, [0.1] * 4, 1.0,
        preflight._coupling(cross_cell_key))
    assert criteria["both_cells_share_first_deal_and_public_key"] is False

    wrong_deal = copy.deepcopy(endpoints)
    for endpoint in wrong_deal:
        endpoint["deal_seed"] += 1
    _, criteria = preflight._projection_and_criteria(
        wrong_deal, [0.1] * 4, 1.0, preflight._coupling(wrong_deal))
    assert criteria["disposable_deals_are_fresh_and_disjoint"] is False


def test_projection_uses_maximum_timings_and_refuses_bad_shapes():
    endpoints = [
        _endpoint(cell, arm)
        for cell in preflight.CELLS for arm in preflight.ARMS
    ]
    endpoints[-1]["elapsed_seconds"] = 2.0
    projection, _ = preflight._projection_and_criteria(
        endpoints, [0.1, 0.2, 0.3, 0.4], 1.0,
        preflight._coupling(endpoints))
    assert projection["maximum_training_iteration_seconds"] == 2.0
    assert projection["maximum_evaluation_round_seconds"] == 0.4
    assert projection["training_seconds_with_safety"] \
        == 2.0 * preflight.ITERATIONS * preflight.TRAINING_ENDPOINTS \
        / preflight.PARALLEL_JOBS * preflight.TIMING_SAFETY_FACTOR

    bad = copy.deepcopy(endpoints)
    bad[0]["unexpected"] = True
    _, criteria = preflight._projection_and_criteria(
        bad, [0.1] * 4, 1.0, preflight._coupling(bad))
    assert criteria["exact_four_endpoint_grid"] is False
    with pytest.raises(preflight.SuphxO0V2PreflightError):
        preflight._projection_and_criteria(
            endpoints, [0.1, -1.0, 0.1, 0.1], 1.0,
            preflight._coupling(endpoints))


@pytest.mark.parametrize("key", [
    "mean_score", "reward", "action_cards", "loss", "behavior_value",
    "terminal_model_state_sha256", "mean_entropy", "top_two_margin",
])
def test_recursive_redaction_detects_result_shaped_injections(key):
    assert preflight._forbidden_paths({"nested": [{key: 1.0}]}) == [
        f"$.nested[0].{key}"]


def test_output_path_and_existing_final_are_fail_closed(
        synthetic_preflight, tmp_path, monkeypatch):
    with pytest.raises(preflight.SuphxO0V2PreflightError):
        preflight.run_preflight(tmp_path / "wrong.json")
    preflight.run_preflight(synthetic_preflight)
    monkeypatch.setattr(
        preflight, "_payload",
        lambda: pytest.fail("existing final must refuse before doing work"),
    )
    with pytest.raises(FileExistsError):
        preflight.run_preflight(synthetic_preflight)


@pytest.mark.parametrize("mutation", [
    lambda value: value.update(claim="strength evidence"),
    lambda value: value["projection"].update(
        total_wall_seconds_with_safety=0.0),
    lambda value: value["criteria"].update(
        projected_total_with_safety_within_8_hours=False),
    lambda value: value.update(training_authorized=True),
    lambda value: value["endpoints"][0]["role_surface_counts"].pop(
        "attacker_lead"),
])
def test_verifier_recomputes_identity_projection_work_and_authority(
        synthetic_preflight, mutation):
    payload = preflight._payload()
    mutation(payload)
    synthetic_preflight.write_text(
        json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(preflight.SuphxO0V2PreflightError):
        preflight.verify_preflight(synthetic_preflight)
