from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from scripts import luna_historical_analyze as analyzer
from scripts import luna_historical_compare as compare
from shengji.ai.heuristic import HeuristicBot
from shengji.luna import game
from shengji.luna.canonical import canonical_json_bytes


def _historical_fixture(coordinate=("2", 0, 0), role="banker-team", chosen_index=0):
    root = game.build_root(bytes(range(32)), coordinate)
    ballot_bot = game.WideHeuristicBallotBot(seed=0)
    target_team = root.banker % 2 if role == "banker-team" else 1 - root.banker % 2
    while root.phase == "play":
        ballot = [list(action) for action in ballot_bot._candidates(root, root.turn)]
        if len(ballot) > 1 and root.turn % 2 == target_team:
            break
        root.play(root.turn, HeuristicBot().decide_play(root, root.turn))
    before = game._state_snapshot(root)
    chosen = ballot[chosen_index]
    root.play(root.turn, chosen)
    row = {"coordinate": list(coordinate), "role": role,
           "treatment_team": before["banker"] % 2 if role == "banker-team" else 1 - before["banker"] % 2}
    position = {"snapshot": before,
                "state_after_action": game._state_snapshot(root),
                "candidate_ballot": [{"cards": action} for action in ballot],
                "chosen_action": {"cards": chosen, "candidate_index": chosen_index},
                "decision_ordinal": 0, "decision_sha256": "a" * 64,
                "thresholds": [0]}
    row["positions"] = [position]
    packet = compare.prepare_position(row, position)
    return row, position, packet


def _call_fixture(tmp_path, packet, panel_sha, status="historical-comparison-complete"):
    calls = tmp_path / "calls"
    calls.mkdir()
    (calls / "config.json").write_bytes(canonical_json_bytes({
        "mode": "historical-snapshots",
        "inputs": {"panel_manifest_sha256": panel_sha}}))
    (calls / "result.json").write_bytes(canonical_json_bytes({
        "schema": "luna-token-pilot-v1",
        "status": status}))
    for arm in ("compact1", "batch4"):
        row = {"arm": arm, "index": 0, "packet_hashes": [packet.sha256],
               "packets": [packet.payload()], "accepted": True,
               "decisions": [{"packet_sha256": packet.sha256,
                              "candidate_index": 0, "confidence": "low",
                              "planning_note": "fixture"}],
               "usage": None}
        (calls / f"{arm}-0000.json").write_bytes(canonical_json_bytes(row))
    return calls


def _patch_panel(monkeypatch, row, packet, panel_sha):
    monkeypatch.setattr(compare, "prepare_panel",
                        lambda root, require_complete=True:
                        ({"schema": "fixture", "mode": analyzer.MODE}, [row], panel_sha,
                         {(row["role"], 0): (packet,)}))


def test_real_historical_packet_saved_calls_and_engine_score(tmp_path, monkeypatch):
    row, position, packet = _historical_fixture()
    panel_sha = "p" * 64
    _patch_panel(monkeypatch, row, packet, panel_sha)
    calls = _call_fixture(tmp_path, packet, panel_sha)
    result = analyzer.analyze(tmp_path / "panel", calls, tmp_path / "out")
    assert result["status"] == "complete"
    summary = result["summary"]
    assert summary["matched_positions"] == summary["scored_positions"] == 1
    assert summary["historical_reference_token_usage"] is None
    assert "engine/round.py" in result["recipe"]["runtime_binding"]["source_hashes"]
    assert "ai/heuristic.py" in result["recipe"]["runtime_binding"]["source_hashes"]
    assert summary["contrasts"]["historical_vs_compact1"]["smart-all"]["mean"] == 0
    assert json.loads((tmp_path / "out" / f"score-{packet.sha256}.json").read_text())["chosen"] == {
        "historical": 0, "compact1": 0, "batch4": 0,
        "coordinate": list(packet.coordinate), "role": row["role"]}


def test_altered_historical_choice_changes_fake_score_contrast():
    rows = [{"coordinate": ["2", 0, 0],
             "chosen": {"historical": 1, "compact1": 0, "batch4": 0},
             "scores": {"0": {"smart-all": 4, "heuristic-all": 4},
                        "1": {"smart-all": 9, "heuristic-all": 8}}}]
    summary = analyzer.summarize(rows)
    assert summary["historical_vs_compact1"]["smart-all"]["mean"] == 5
    assert summary["historical_vs_batch4"]["heuristic-all"]["mean"] == 4
    assert summary["compact1_vs_batch4"]["smart-all"]["mean"] == 0


def test_analyze_wires_historical_choice_into_score_payload(tmp_path, monkeypatch):
    row, _, packet = _historical_fixture(chosen_index=1)
    panel_sha = "p" * 64
    _patch_panel(monkeypatch, row, packet, panel_sha)
    calls = _call_fixture(tmp_path, packet, panel_sha)
    seen = []

    def fake_score(payload):
        chosen = payload[2]
        seen.append(chosen["historical"])
        assert chosen == {"historical": 1, "compact1": 0, "batch4": 0,
                          "coordinate": list(packet.coordinate),
                          "role": row["role"]}
        return {"schema": analyzer.SCHEMA, "mode": analyzer.MODE,
                "status": "ok", "packet_sha256": payload[0],
                "coordinate": list(packet.coordinate), "role": row["role"],
                "decision_ordinal": 0, "chosen": chosen,
                "scores": {"0": {"smart-all": 4, "heuristic-all": 4},
                           "1": {"smart-all": 9, "heuristic-all": 8}}}

    monkeypatch.setattr(analyzer, "_score_position", fake_score)
    result = analyzer.analyze(tmp_path / "panel", calls, tmp_path / "out")
    assert seen == [1]
    assert result["summary"]["contrasts"]["historical_vs_compact1"]["smart-all"]["mean"] == 5
    row["positions"][0]["chosen_action"]["candidate_index"] = 0
    with pytest.raises(compare.HistoricalCompareError, match="chosen index"):
        analyzer.analyze(tmp_path / "panel", calls, tmp_path / "out")


def test_wrong_panel_binding_refuses_before_call_consumption(tmp_path, monkeypatch):
    row, _, packet = _historical_fixture()
    _patch_panel(monkeypatch, row, packet, "p" * 64)
    calls = _call_fixture(tmp_path, packet, "q" * 64)
    with pytest.raises(analyzer.HistoricalAnalyzeError, match="config binding"):
        analyzer.analyze(tmp_path / "panel", calls, tmp_path / "out")


def test_nonterminal_call_collection_refuses_before_scoring(tmp_path, monkeypatch):
    row, _, packet = _historical_fixture()
    panel_sha = "p" * 64
    _patch_panel(monkeypatch, row, packet, panel_sha)
    calls = _call_fixture(tmp_path, packet, panel_sha, status="stopped")
    with pytest.raises(analyzer.HistoricalAnalyzeError, match="not terminal"):
        analyzer.analyze(tmp_path / "panel", calls, tmp_path / "out")


def test_resume_reuses_completed_score_without_reevaluation(tmp_path, monkeypatch):
    row, _, packet = _historical_fixture()
    panel_sha = "p" * 64
    _patch_panel(monkeypatch, row, packet, panel_sha)
    calls = _call_fixture(tmp_path, packet, panel_sha)
    out = tmp_path / "out"
    analyzer.analyze(tmp_path / "panel", calls, out)
    monkeypatch.setattr(analyzer, "_score_position",
                        lambda payload: pytest.fail("score replayed"))
    result = analyzer.analyze(tmp_path / "panel", calls, out)
    assert result["status"] == "complete"


def test_runtime_activation_change_refuses_resume_before_rescoring(tmp_path, monkeypatch):
    row, _, packet = _historical_fixture()
    panel_sha = "p" * 64
    _patch_panel(monkeypatch, row, packet, panel_sha)
    calls = _call_fixture(tmp_path, packet, panel_sha)
    out = tmp_path / "out"
    analyzer.analyze(tmp_path / "panel", calls, out)
    original = analyzer._runtime_binding
    monkeypatch.setattr(analyzer, "_runtime_binding",
                        lambda: {**original(), "engine_fast_active":
                                 not original()["engine_fast_active"]})
    monkeypatch.setattr(analyzer, "_score_position",
                        lambda payload: pytest.fail("score replayed"))
    with pytest.raises(analyzer.HistoricalAnalyzeError, match="resume recipe"):
        analyzer.analyze(tmp_path / "panel", calls, out)


def test_all_failed_scores_are_complete_with_errors_and_not_retried(tmp_path, monkeypatch):
    row, _, packet = _historical_fixture()
    panel_sha = "p" * 64
    _patch_panel(monkeypatch, row, packet, panel_sha)
    calls = _call_fixture(tmp_path, packet, panel_sha)
    monkeypatch.setattr(analyzer, "_score_position",
                        lambda payload: (_ for _ in ()).throw(RuntimeError("score unavailable")))
    out = tmp_path / "out"
    result = analyzer.analyze(tmp_path / "panel", calls, out)
    assert result["status"] == "complete-with-errors"
    assert result["summary"]["error_positions"] == 1
    monkeypatch.setattr(analyzer, "_score_position",
                        lambda payload: pytest.fail("failed score retried"))
    resumed = analyzer.analyze(tmp_path / "panel", calls, out)
    assert resumed["status"] == "complete-with-errors"


def test_both_roles_count_as_one_independent_deal(tmp_path, monkeypatch):
    banker, _, banker_packet = _historical_fixture(("2", 0, 0), "banker-team")
    attacker, _, attacker_packet = _historical_fixture(("2", 0, 0), "attacker-team")
    panel_sha = "p" * 64
    monkeypatch.setattr(compare, "prepare_panel",
                        lambda root, require_complete=True:
                        ({}, [banker, attacker], panel_sha,
                         {("banker-team", 0): (banker_packet,),
                          ("attacker-team", 0): (attacker_packet,)}))
    calls = tmp_path / "calls"
    calls.mkdir()
    (calls / "config.json").write_bytes(canonical_json_bytes({
        "mode": "historical-snapshots", "inputs": {"panel_manifest_sha256": panel_sha}}))
    (calls / "result.json").write_bytes(canonical_json_bytes({
        "schema": "luna-token-pilot-v1", "status": "historical-comparison-complete"}))
    for n, packet in enumerate((banker_packet, attacker_packet)):
        for arm in ("compact1", "batch4"):
            row = {"arm": arm, "index": n, "packet_hashes": [packet.sha256],
                   "packets": [packet.payload()], "accepted": True,
                   "decisions": [{"packet_sha256": packet.sha256,
                                  "candidate_index": 0, "confidence": "low",
                                  "planning_note": "fixture"}], "usage": None}
            (calls / f"{arm}-{n:04d}.json").write_bytes(canonical_json_bytes(row))
    result = analyzer.analyze(tmp_path / "panel", calls, tmp_path / "out")
    assert result["summary"]["role_games"] == 2
    assert result["summary"]["independent_deals"] == 1
