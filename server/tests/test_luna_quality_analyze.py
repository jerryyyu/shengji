from __future__ import annotations

import json
from pathlib import Path
import random

import pytest

from scripts import luna_quality_analyze as analyzer
from shengji.ai.heuristic import HeuristicBot
from shengji.luna import game, quality_panel
from shengji.luna.canonical import canonical_json_bytes


class FastProduction:
    def __init__(self, seed=None):
        del seed

    def _candidates(self, rnd, seat):
        return [HeuristicBot().decide_play(rnd, seat)]

    def decide_play(self, rnd, seat):
        return HeuristicBot().decide_play(rnd, seat)


def _source(tmp_path: Path, count: int = 1):
    tmp_path.mkdir(parents=True, exist_ok=True)
    secret = bytes(range(32))
    rows = [quality_panel.capture_coordinate(
        secret, coordinate, producer_factory=FastProduction)
            for coordinate in game.LunaDesign().root_coordinates[:count]]
    # Make the first position prove that production is not inferred as index 0:
    # retain the real generated ballot but bind its second candidate as the
    # recorded production action in this synthetic source fixture.
    if rows[0]["stages"] and len(rows[0]["stages"][0]["candidate_ballot"]) >= 2:
        stage = rows[0]["stages"][0]
        stage["production_ballot"] = list(stage["candidate_ballot"][:2])
        stage["production_play_index"] = 1
        stage["attempted_action"] = list(stage["candidate_ballot"][1])
    entries = []
    for row in rows:
        raw = canonical_json_bytes(row)
        quality_panel.shard_path(tmp_path, row["coordinate"]).write_bytes(raw)
        entries.append({"coordinate": row["coordinate"],
                        "sha256": analyzer._sha_bytes(raw),
                        "status": row["status"]})
    manifest = {"schema": quality_panel.SCHEMA, "private": True,
                "shards": entries}
    (tmp_path / "manifest.json").write_bytes(canonical_json_bytes(manifest))
    return rows


def _calls(tmp_path: Path, positions, selected=None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    selected = sorted(positions)[:1] if selected is None else selected
    for arm in ("compact1", "batch4"):
        for index, packet_hash in enumerate(selected):
            packet = positions[packet_hash].packet
            row = {"arm": arm, "index": index,
                   "packet_hashes": [packet.sha256], "packets": [packet.payload()],
                   "accepted": True,
                   "decisions": [{"packet_sha256": packet.sha256,
                                  "candidate_index": 1 if arm == "compact1" else 0,
                                  "confidence": "low", "planning_note": ""}],
                   "usage": {"total_tokens": 2}}
            (tmp_path / f"{arm}-{index:04d}.json").write_bytes(
                canonical_json_bytes(row))


def test_real_engine_position_and_production_action_index(tmp_path):
    rows = _source(tmp_path)
    _, positions, _ = analyzer.panel_positions(tmp_path, require_population=False)
    position = next(iter(positions.values()))
    assert analyzer.production_index(position) == 1
    _calls(tmp_path, positions)
    result = analyzer.analyze(tmp_path, tmp_path, tmp_path / "out",
                              require_population=False)
    assert result["summary"]["positions"] == 1
    assert result["summary"]["continuations"] == {
        "primary": "smart-all", "sensitivity": "heuristic-all"}


def test_teacher_match_survives_missing_production_equivalent(tmp_path):
    rows = _source(tmp_path / "panel")
    stage = rows[0]["stages"][0]
    stage["production_ballot"] = []
    stage["production_play_index"] = None
    stage["attempted_action"] = ["missing-production-card"]
    panel_path = quality_panel.shard_path(tmp_path / "panel", rows[0]["coordinate"])
    panel_path.write_bytes(canonical_json_bytes(rows[0]))
    manifest = json.loads((tmp_path / "panel" / "manifest.json").read_text())
    manifest["shards"][0]["sha256"] = analyzer._sha_bytes(panel_path.read_bytes())
    (tmp_path / "panel" / "manifest.json").write_bytes(canonical_json_bytes(manifest))
    _, positions, _ = analyzer.panel_positions(tmp_path / "panel", require_population=False)
    missing_hash = next(packet_hash for packet_hash, position in positions.items()
                        if analyzer.production_index(position) is None)
    _calls(tmp_path / "calls", positions, [missing_hash])
    result = analyzer.analyze(tmp_path / "panel", tmp_path / "calls", tmp_path / "out",
                              require_population=False)
    assert result["summary"]["positions"] == 1
    assert result["summary"]["missing_production_positions"] == 1


def test_serial_parallel_parity_and_unchanged_input(tmp_path):
    rows = _source(tmp_path / "panel", count=2)
    _, positions, _ = analyzer.panel_positions(tmp_path / "panel",
                                               require_population=False)
    selected = [next(packet_hash for packet_hash, position in positions.items()
                     if list(position.packet.coordinate) == row["coordinate"])
                for row in rows]
    assert len(selected) == 2 and len(set(selected)) == 2
    _calls(tmp_path / "calls", positions, selected)
    one = analyzer.analyze(tmp_path / "panel", tmp_path / "calls", tmp_path / "one",
                           require_population=False)
    two = analyzer.analyze(tmp_path / "panel", tmp_path / "calls", tmp_path / "two",
                           workers=2, require_population=False)
    assert one["summary"] == two["summary"]
    assert one["summary"]["positions"] == two["summary"]["positions"] == 2
    assert one["summary"]["deals"] == two["summary"]["deals"] == 2
    assert positions[next(iter(positions))].packet.state == rows[0]["stages"][0]["snapshot"]


def test_invalid_saved_decisions_and_duplicates_refuse(tmp_path):
    _source(tmp_path / "panel")
    _, positions, _ = analyzer.panel_positions(tmp_path / "panel", require_population=False)
    calls = tmp_path / "calls"
    calls.mkdir()
    _calls(calls, positions)
    path = calls / "compact1-0000.json"
    row = json.loads(path.read_text())
    row["decisions"][0]["candidate_index"] = 999
    path.write_bytes(canonical_json_bytes(row))
    with pytest.raises(analyzer.QualityAnalyzeError, match="candidate index"):
        analyzer.saved_decisions(calls, positions)

    _calls(calls, positions)
    row = json.loads(path.read_text())
    (calls / "compact1-0001.json").write_bytes(canonical_json_bytes(row))
    with pytest.raises(analyzer.QualityAnalyzeError, match="duplicate arm"):
        analyzer.saved_decisions(calls, positions)


def test_real_packet_sha_mismatch_refuses(tmp_path):
    _source(tmp_path / "panel")
    _, positions, _ = analyzer.panel_positions(tmp_path / "panel", require_population=False)
    calls = tmp_path / "calls"
    _calls(calls, positions)
    path = calls / "compact1-0000.json"
    row = json.loads(path.read_text())
    row["packet_hashes"] = ["0" * 64]
    path.write_bytes(canonical_json_bytes(row))
    with pytest.raises(analyzer.QualityAnalyzeError, match="SHA"):
        analyzer.saved_decisions(calls, positions)


def test_resume_reuses_quality_shard_and_refuses_call_drift(tmp_path, monkeypatch):
    _source(tmp_path / "panel")
    _, positions, _ = analyzer.panel_positions(tmp_path / "panel", require_population=False)
    _calls(tmp_path / "calls", positions)
    out = tmp_path / "out"
    analyzer.analyze(tmp_path / "panel", tmp_path / "calls", out,
                     require_population=False)
    monkeypatch.setattr(analyzer, "_evaluate_position",
                        lambda payload: (_ for _ in ()).throw(AssertionError("replayed")))
    analyzer.analyze(tmp_path / "panel", tmp_path / "calls", out,
                     require_population=False)
    call_path = tmp_path / "calls" / "compact1-0000.json"
    call = json.loads(call_path.read_text())
    call["index"] = 9
    call_path.write_bytes(canonical_json_bytes(call))
    with pytest.raises(analyzer.QualityAnalyzeError, match="resume recipe"):
        analyzer.analyze(tmp_path / "panel", tmp_path / "calls", out,
                         require_population=False)


def test_interrupted_progress_preserves_success_and_resume_skips_it(tmp_path,
                                                                     monkeypatch):
    _source(tmp_path / "panel", count=2)
    _, positions, _ = analyzer.panel_positions(tmp_path / "panel", require_population=False)
    _calls(tmp_path / "calls", positions, sorted(positions)[:2])
    out = tmp_path / "out"

    def interrupt(progress):
        if progress["completed"] == 1:
            raise RuntimeError("interrupted progress sink")

    with pytest.raises(RuntimeError, match="interrupted progress"):
        analyzer.analyze(tmp_path / "panel", tmp_path / "calls", out,
                         progress_sink=interrupt, require_population=False)
    assert len(list(out.glob("quality-*.json"))) == 1
    calls = []
    original = analyzer._evaluate_position

    def counted(payload):
        calls.append(payload[0])
        return original(payload)

    monkeypatch.setattr(analyzer, "_evaluate_position", counted)
    # The remaining position is computed, while the already-published first
    # shard is loaded and not replayed.
    result = analyzer.analyze(tmp_path / "panel", tmp_path / "calls", out,
                              require_population=False)
    assert result["summary"]["positions"] == 2
    assert len(calls) == 1


@pytest.mark.parametrize("deadline", [float("nan"), float("inf")])
def test_nonfinite_deadline_refused_before_input_reads(tmp_path, deadline):
    with pytest.raises(analyzer.QualityAnalyzeError, match="positive"):
        analyzer.analyze(tmp_path / "missing-panel", tmp_path / "missing-calls",
                         tmp_path / "out", max_seconds=deadline)


def test_cli_nonfinite_deadline_refused(tmp_path):
    with pytest.raises(SystemExit):
        analyzer.main(["--panel-root", str(tmp_path / "panel"),
                       "--calls-root", str(tmp_path / "calls"),
                       "--out", str(tmp_path / "out"),
                       "--max-seconds", "nan"])


def test_deadline_partial_then_resume_publishes_final_and_reuses_shard(tmp_path,
                                                                        monkeypatch):
    _source(tmp_path / "panel", count=2)
    _, positions, _ = analyzer.panel_positions(tmp_path / "panel", require_population=False)
    _calls(tmp_path / "calls", positions, sorted(positions)[:2])
    out = tmp_path / "out"
    ticks = iter((0.0, 0.0, 2.0))
    monkeypatch.setattr(analyzer, "_now", lambda: next(ticks, 0.0))
    partial = analyzer.analyze(tmp_path / "panel", tmp_path / "calls", out,
                               max_seconds=1.0, require_population=False)
    assert partial.get("status") == "incomplete"
    assert partial["summary"]["positions"] == 1
    assert partial["summary"]["deadline_uncomputed_positions"] == 1
    assert len(list(out.glob("quality-*.json"))) == 1
    assert not (out / "manifest.json").exists()
    calls = []
    original = analyzer._evaluate_position

    def counted(payload):
        calls.append(payload[0])
        return original(payload)

    monkeypatch.setattr(analyzer, "_evaluate_position", counted)
    complete = analyzer.analyze(tmp_path / "panel", tmp_path / "calls", out,
                                max_seconds=30, require_population=False)
    assert complete["summary"]["positions"] == 2
    assert (out / "manifest.json").exists()
    assert len(calls) == 1
    monkeypatch.setattr(analyzer, "_evaluate_position",
                        lambda payload: (_ for _ in ()).throw(AssertionError("replayed")))
    analyzer.analyze(tmp_path / "panel", tmp_path / "calls", out,
                     require_population=False)


def test_equal_weight_bootstrap_is_per_deal_and_continuations_are_separate():
    rows = []
    for coord, values in [(('2', 0, 0), (2, 4)), (('2', 1, 0), (10, 14))]:
        for value in values:
            rows.append({"coordinate": list(coord),
                         "chosen": {"compact1": 1, "batch4": 0},
                         "production_index": 0,
                         "scores": {"0": {"smart-all": 0, "heuristic-all": 0},
                                    "1": {"smart-all": value,
                                          "heuristic-all": value + 1}}})
    summary = analyzer.summarize(rows)
    assert summary["deals"] == 2
    assert summary["arms_vs_production"]["compact1"]["vs_production:smart-all"]["mean"] == 7.5
    assert summary["arms_vs_production"]["compact1"]["vs_production:heuristic-all"]["mean"] == 8.5
    assert summary["compact1_vs_batch4"]["smart-all"]["deals"] == 2
    assert summary["bootstrap"]["replicates"] == 10_000


def test_52_unequal_position_counts_bootstrap_exactly_equal_deals():
    rows = []
    for deal_index, coordinate in enumerate(game.LunaDesign().root_coordinates):
        for _ in range((deal_index % 3) + 1):
            rows.append({"coordinate": list(coordinate),
                         "chosen": {"compact1": 1, "batch4": 0},
                         "production_index": 0,
                         "split": "fit" if coordinate[2] == 0 else "validation",
                         "scores": {"0": {"smart-all": 0, "heuristic-all": 0},
                                    "1": {"smart-all": deal_index,
                                          "heuristic-all": deal_index + 1}}})
    first = analyzer.summarize(rows)
    second = analyzer.summarize(rows)
    assert first == second
    shuffled = list(rows)
    random.Random(20260906).shuffle(shuffled)
    reversed_summary = analyzer.summarize(list(reversed(rows)))
    shuffled_summary = analyzer.summarize(shuffled)
    assert canonical_json_bytes(first) == canonical_json_bytes(reversed_summary)
    assert canonical_json_bytes(first) == canonical_json_bytes(shuffled_summary)
    assert first["deals"] == 52
    assert first["arms_vs_production"]["compact1"]["vs_production:smart-all"]["mean"] == 25.5
    assert first["arms_vs_production"]["compact1"]["vs_production:smart-all"]["deals"] == 52
    assert first["bootstrap"]["replicates"] == 10_000
