from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import luna_quality_compare as compare
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


def _source(tmp_path, count=4):
    secret = bytes(range(32))
    rows = [quality_panel.capture_coordinate(
        secret, coordinate, producer_factory=FastProduction)
            for coordinate in game.LunaDesign().root_coordinates[:count]]
    entries = []
    for row in rows:
        raw = canonical_json_bytes(row)
        path = quality_panel.shard_path(tmp_path, row["coordinate"])
        path.write_bytes(raw)
        entries.append({"coordinate": row["coordinate"],
                        "sha256": compare._sha_bytes(raw),
                        "status": row["status"]})
    manifest = {"schema": quality_panel.SCHEMA, "private": True,
                "shards": entries}
    (tmp_path / "manifest.json").write_bytes(canonical_json_bytes(manifest))
    return rows


def test_real_root_stage_rebuilds_exact_packet_and_ballot(tmp_path):
    rows = _source(tmp_path, 1)
    groups, missing = compare.build_groups(rows)
    assert sorted(groups) == [0, 12, 24, 36]
    assert missing[tuple(rows[0]["coordinate"])] == []
    packet = groups[0][0]
    stage = rows[0]["stages"][0]
    assert packet.state == stage["snapshot"]
    assert [list(cards) for cards in packet.candidates] == stage["candidate_ballot"]
    assert packet.decision_index == 0


def test_source_hash_and_ballot_mismatch_are_refused(tmp_path):
    rows = _source(tmp_path, 1)
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    manifest["shards"][0]["sha256"] = "0" * 64
    (tmp_path / "manifest.json").write_bytes(canonical_json_bytes(manifest))
    with pytest.raises(compare.QualityCompareError, match="hash"):
        compare._verify_panel(tmp_path)

    rows = _source(tmp_path, 1)
    rows[0]["stages"][0]["candidate_ballot"] = [["bogus"], ["bogus2"]]
    path = quality_panel.shard_path(tmp_path, rows[0]["coordinate"])
    path.write_bytes(canonical_json_bytes(rows[0]))
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    manifest["shards"][0]["sha256"] = compare._sha_bytes(path.read_bytes())
    (tmp_path / "manifest.json").write_bytes(canonical_json_bytes(manifest))
    _, loaded, _ = compare._verify_panel(tmp_path)
    with pytest.raises(compare.QualityCompareError, match="ballot"):
        compare.build_groups(loaded)


def test_fake_pilot_gets_distinct_sorted_groups_and_same_arm_packets(tmp_path):
    rows = _source(tmp_path, 4)
    calls = []

    class FakePilot:
        def __init__(self, args):
            self.args = args
            self.rows = []

        def configure(self, inputs):
            self.inputs = inputs

        def call(self, arm, index, packets):
            packets = tuple(packets)
            calls.append((arm, index, packets))
            row = {"arm": arm, "accepted": True, "decisions": [{}] * len(packets),
                   "usage": {"total_tokens": 1}}
            self.rows.append(row)
            return row, None

        def finish(self, extra):
            return extra

    result = compare.run_compare(tmp_path, tmp_path / "out",
                                 pilot_factory=FakePilot, require_population=False)
    assert result["actual_packet_count"] == 16
    for ordinal in quality_panel.REQUESTED_ORDINALS:
        stage_calls = [call for call in calls if call[1] // 1000 == ordinal]
        compact = [call for call in stage_calls if call[0] == "compact1"]
        batch = [call for call in stage_calls if call[0] == "batch4"]
        assert len(compact) == 4 and len(batch) == 1
        assert {call[2][0].sha256 for call in compact} == {
            packet.sha256 for packet in batch[0][2]}
    assert result["interpretation"].startswith("Independent-state")


def test_incomplete_deal_stages_are_retained_and_missing_is_reported(tmp_path):
    rows = _source(tmp_path, 1)
    rows[0]["stages"] = rows[0]["stages"][:1]
    path = quality_panel.shard_path(tmp_path, rows[0]["coordinate"])
    path.write_bytes(canonical_json_bytes(rows[0]))
    manifest = json.loads((tmp_path / "manifest.json").read_text())
    manifest["shards"][0]["sha256"] = compare._sha_bytes(path.read_bytes())
    (tmp_path / "manifest.json").write_bytes(canonical_json_bytes(manifest))
    _, loaded, _ = compare._verify_panel(tmp_path)
    groups, missing = compare.build_groups(loaded)
    assert len(groups[0]) == 1
    assert missing[tuple(rows[0]["coordinate"])] == [12, 24, 36]


def test_cli_requires_panel_and_output():
    with pytest.raises(SystemExit):
        compare.main(["--codex-binary", "codex"])


def test_empty_panel_refuses_before_provider_construction(tmp_path, monkeypatch):
    row = {"coordinate": ["2", 0, 0], "stages": []}
    monkeypatch.setattr(compare, "_verify_panel",
                        lambda *a, **k: ({"schema": quality_panel.SCHEMA}, [row], "a" * 64))
    def forbidden_provider(args):
        raise AssertionError("empty input must not construct provider")
    with pytest.raises(compare.QualityCompareError, match="no usable decisions"):
        compare.run_compare(tmp_path, tmp_path / "out", pilot_factory=forbidden_provider)
