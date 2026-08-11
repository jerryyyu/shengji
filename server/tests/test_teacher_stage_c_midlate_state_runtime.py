from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from types import SimpleNamespace


sys.path.insert(0, str(Path(__file__).parents[1] / "scripts"))
import teacher_stage_c_midlate_state_runtime as RUNTIME  # noqa: E402


def _packet() -> dict:
    return {
        "producer": {"git": "head", "sources": {"source": "hash"}},
        "packet_sha256": "d" * 64,
    }


def test_selection_consumes_admission_before_scanning(
        monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(RUNTIME, "REPO", tmp_path)
    packet_path = tmp_path / "packet.json"
    packet_path.write_text("packet\n")
    packet_sha = RUNTIME.sha256_file(packet_path)
    review = tmp_path / "controller-review.md"
    review.write_text("review\n")
    out = tmp_path / RUNTIME.CTRL.POPULATION_PATH
    slot = tmp_path / RUNTIME.CTRL.SELECTION_ADMISSION_PATH
    packet = _packet()
    monkeypatch.setattr(
        RUNTIME, "_packet", lambda *_args: (packet, [], object()))
    monkeypatch.setattr(
        RUNTIME, "_controller_review",
        lambda *_args: {"one_selection_execution_authorized": True})
    monkeypatch.setattr(
        RUNTIME, "_factories", lambda *_args: (object(), object(), object()))
    monkeypatch.setattr(RUNTIME.CTRL, "_source_sha256s",
                        lambda: {"source": "hash"})
    monkeypatch.setattr(RUNTIME.CAPTURE, "validate_population",
                        lambda *_args, **_kwargs: None)

    population = {
        "selected_states": 256, "deals_scanned": 400,
        "complete": True, "population_sha256": "a" * 64,
    }

    def scan(**kwargs):
        assert slot.is_file()
        assert kwargs["seed0"] == RUNTIME.CTRL.SEED0
        assert kwargs["scan_deals"] == RUNTIME.CTRL.SCAN_DEALS
        return copy.deepcopy(population)

    monkeypatch.setattr(RUNTIME.CAPTURE, "scan_population", scan)
    result = RUNTIME.select_population(
        packet_path=packet_path, expected_packet_sha256=packet_sha,
        expected_git="head", controller_review_record=review, out=out)
    assert out.is_file()
    assert result["evaluation_opened"] is False
    assert result["population"] == population
    assert json.loads(slot.read_bytes())[
        "consumed_before_fresh_evidence"] is True


def test_evaluation_consumes_distinct_admission_before_first_world(
        monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(RUNTIME, "REPO", tmp_path)
    packet_path = tmp_path / "packet.json"
    packet_path.write_text("packet\n")
    packet_sha = RUNTIME.sha256_file(packet_path)
    population_path = tmp_path / RUNTIME.CTRL.POPULATION_PATH
    population_path.parent.mkdir(parents=True, exist_ok=True)
    population_path.write_text("population\n")
    population_sha = RUNTIME.sha256_file(population_path)
    controller_review = tmp_path / "controller-review.md"
    controller_review.write_text("controller\n")
    selection_review = tmp_path / "selection-review.md"
    selection_review.write_text("selection\n")
    out = tmp_path / RUNTIME.CTRL.RESULT_PATH
    slot = tmp_path / RUNTIME.CTRL.EVALUATION_ADMISSION_PATH
    packet = _packet()
    entries = [
        {"state": {"state_id": "a"}, "selection": {"id": "a"}},
        {"state": {"state_id": "b"}, "selection": {"id": "b"}},
    ]
    selection = {
        "selection_result_sha256": "e" * 64,
        "population": {"entries": entries},
    }
    monkeypatch.setattr(
        RUNTIME, "_packet", lambda *_args: (packet, [], object()))
    monkeypatch.setattr(RUNTIME, "_controller_review", lambda *_args: {})
    monkeypatch.setattr(RUNTIME, "_selection_population",
                        lambda **_kwargs: selection)
    monkeypatch.setattr(
        RUNTIME, "_selection_review",
        lambda *_args, **_kwargs: {
            "one_evaluation_execution_authorized": True})

    calls = []

    def evaluate(state, selected, **_kwargs):
        assert slot.is_file()
        calls.append((state, selected))
        return {"record": state["state_id"]}

    aggregate = {
        "decision": "SELECT_NONE",
        "whole_game_screen_design_authorized": False,
    }
    monkeypatch.setattr(RUNTIME.SCREEN, "evaluate_selected", evaluate)
    monkeypatch.setattr(RUNTIME.SCREEN, "aggregate",
                        lambda *_args, **_kwargs: aggregate)
    result = RUNTIME.evaluate_population(
        packet_path=packet_path, expected_packet_sha256=packet_sha,
        expected_git="head", controller_review_record=controller_review,
        selection_population_path=population_path,
        expected_selection_population_sha256=population_sha,
        selection_review_record=selection_review, out=out)
    assert len(calls) == 2
    assert out.is_file()
    assert result["aggregate"] == aggregate
    assert result["whole_game_launch_authorized"] is False
    assert json.loads(slot.read_bytes())["kind"] == "evaluation"
