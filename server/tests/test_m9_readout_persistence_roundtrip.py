from __future__ import annotations

import copy
import json
from types import SimpleNamespace

from shengji.eval import m9_panel_persistence as persistence
from shengji.eval import m9_panel_worker as worker
from shengji.eval.m9_panel_plan import ROOTS, build_m9_panel_plan
from shengji.eval.m9_panel_readout import summarize_m9_panels
from test_m9_panel_readout import _records


def _strict_json_load(path):
    def reject_constant(value):
        raise AssertionError(f"non-JSON constant persisted in {path}: {value}")

    return json.loads(path.read_text(), parse_constant=reject_constant)


def test_saved_m9_panels_roundtrip_from_validated_json_to_readout(monkeypatch, tmp_path):
    analysis, synthetic_records = _records()
    for root in analysis["roots"]:
        for seed in root["seeds"]:
            for arm in ("control", "treatment"):
                decision = seed[arm]["decision"]
                decision["policy_log_odds_admitted"] = [
                    -float(index) for index in range(len(decision["admitted"]))
                ]
                decision["seconds"] = 0.0
    saved_analysis = json.loads(json.dumps(analysis, allow_nan=False))
    required_decision_fields = {
        "admitted_indices", "selected_index", "value_means", "admitted",
        "policy_log_odds_admitted", "seconds", "work_complete",
    }
    for root in saved_analysis["roots"]:
        for seed in root["seeds"]:
            for arm in ("control", "treatment"):
                assert required_decision_fields <= set(seed[arm]["decision"])

    expected = summarize_m9_panels(saved_analysis, synthetic_records)
    planned = build_m9_panel_plan(saved_analysis)
    fixtures = [SimpleNamespace(id=root_id, seat=0) for root_id in reversed(ROOTS)]
    calls = []

    def collect_without_model(_factory, fixture, control, treatment, **kwargs):
        index = len(calls)
        job = planned[index]
        assert fixture.id == job["fixture_id"]
        assert control == job["control_ballot"]
        assert treatment == job["treatment_ballot"]
        assert kwargs["mode"] == job["mode"]
        assert kwargs["seed"] == job["seed"]
        calls.append(index)
        return copy.deepcopy(synthetic_records[index]["panel"])

    monkeypatch.setattr(worker, "collect_public_fixture_panel", collect_without_model)
    output = tmp_path / "saved-m9-attempt"

    def no_model_factory(seed):
        raise AssertionError(f"model factory unexpectedly called for seed {seed}")

    receipt = persistence.run_m9_panel_collection(
        saved_analysis,
        fixtures,
        no_model_factory,
        output_dir=output,
    )

    validated = [
        _strict_json_load(output / f"validated-{index:03d}.json")
        for index in range(15)
    ]
    assert calls == list(range(15))
    assert summarize_m9_panels(saved_analysis, validated) == expected

    terminal = _strict_json_load(output / "terminal.json")
    assert terminal["status"] == "complete"
    assert terminal["collected_count"] == terminal["validated_count"] == 15
    assert terminal["receipt"]["completed_panels"] == 15
    assert terminal["receipt"]["primary_panels"] == 3
    assert terminal["receipt"]["secondary_panels"] == 12
    assert terminal == receipt
