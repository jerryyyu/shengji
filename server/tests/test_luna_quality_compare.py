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


def test_opt_in_refusal_continues_fixed_schedule_and_loses_batch_slots(tmp_path):
    rows = _source(tmp_path, 4)
    calls = []

    class RefusalPilot:
        def __init__(self, args):
            self.args = args
            self.rows = []

        def configure(self, inputs):
            self.inputs = inputs

        def call(self, arm, index, packets):
            packets = tuple(packets)
            calls.append((arm, index, packets))
            if arm == "batch4" and not any(not row["accepted"] for row in self.rows):
                row = {"arm": arm, "index": index,
                       "packet_hashes": [packet.sha256 for packet in packets],
                       "accepted": False, "decisions": [], "usage": None,
                       "error": "cached refusal"}
            else:
                row = {"arm": arm, "index": index,
                       "packet_hashes": [packet.sha256 for packet in packets],
                       "accepted": True,
                       "decisions": [{} for _ in packets],
                       "usage": {"total_tokens": len(packets)}}
            self.rows.append(row)
            return row, None

        def finish(self, extra):
            return extra

    result = compare.run_compare(
        tmp_path, tmp_path / "out", pilot_factory=RefusalPilot,
        require_population=False, continue_independent_refusals=True)
    assert result["status"] == "comparison-panel-complete-with-refusals"
    assert result["continue_independent_refusals"] is True
    assert result["failed_call_count"] == 1
    assert result["refused_packet_count"] == 4
    assert result["actual_packet_count"] == 16
    assert result["processed_packet_count"] == 28
    assert result["actual_call_count"] == len(calls) == 20
    assert len({(arm, index) for arm, index, _packets in calls}) == len(calls)
    assert any(index > 0 for _arm, index, _packets in calls)


def test_refusal_continuation_policy_is_absent_by_default_and_default_stops(tmp_path):
    _source(tmp_path, 1)

    class StopPilot:
        def __init__(self, args):
            self.args = args
            self.rows = []

        def configure(self, inputs):
            self.inputs = inputs

        def call(self, arm, index, packets):
            row = {"arm": arm, "index": index,
                   "packet_hashes": [packet.sha256 for packet in packets],
                   "accepted": False, "decisions": [], "usage": None,
                   "error": "cached refusal"}
            self.rows.append(row)
            return row, None

        def finish(self, extra):
            self.result = extra
            return extra

    holder = []

    def factory(args):
        instance = StopPilot(args)
        holder.append(instance)
        return instance

    result = compare.run_compare(tmp_path, tmp_path / "out", pilot_factory=factory,
                                 require_population=False)
    assert result["status"] == "stopped-on-refusal"
    assert "refusal_policy" not in holder[0].inputs
    assert result["actual_call_count"] == 1


def test_real_pilot_reuses_refusal_and_unsettled_reservation_without_redispatch(tmp_path):
    import time
    from types import SimpleNamespace
    from scripts import luna_token_pilot as pilot_module

    rows = _source(tmp_path, 2)
    groups, _ = compare.build_groups(rows)
    out = tmp_path / "out"
    out.mkdir(mode=0o700)
    (out / "pending").mkdir(mode=0o700)
    expected_charge = 0
    saved_bytes = {}
    for ordinal, packets in groups.items():
        for arm in compare.ARMS:
            batches = [(p,) for p in packets] if arm == "compact1" else [packets]
            for slot, batch in enumerate(batches):
                index = ordinal * 1000 + slot
                failed = ordinal == 0 and (arm == "batch4" or slot == 1)
                record = {"arm": arm, "index": index, "packet_hashes": [p.sha256 for p in batch],
                          "accepted": not failed, "decisions": [] if failed else [{} for _ in batch],
                          "usage": None if failed else {"total_tokens": 13},
                          "error": "saved refusal" if failed else None,
                          "charged_tokens": 30000 if failed else 13}
                directory = out / "pending" if arm == "compact1" and failed else out
                path = directory / f"{arm}-{index:04d}.json"
                path.write_bytes(canonical_json_bytes(record))
                saved_bytes[path] = path.read_bytes()
                expected_charge += record["charged_tokens"]
    dispatches = []
    instances = []

    def forbidden(*args):
        dispatches.append(args)
        raise AssertionError("a saved or unsettled call must not be redispatched")

    class CachedPilot(pilot_module.Pilot):
        def __init__(self, args):
            self.args, self.root = args, args.out
            self.rows, self.charged = [], 0
            self.created = time.time()
            self.deadline_ns = time.monotonic_ns() + args.wall_seconds * 10**9
            self.base = SimpleNamespace(runtime={"fixed": True}, model=game.MODEL,
                                        reasoning_effort="medium")
            self.source = {"fixture": "same-source"}
            self.compact = SimpleNamespace(call_many=forbidden)
            instances.append(self)

    result = compare.run_compare(tmp_path, out, pilot_factory=CachedPilot,
                                 require_population=False, continue_independent_refusals=True)
    assert result["status"] == "comparison-panel-complete-with-refusals"
    assert result["actual_call_count"] == 12
    assert result["processed_packet_count"] == 13
    assert result["refused_packet_count"] == 3
    assert result["failed_call_count"] == result["unknown_usage_calls"] == 2
    assert result["known_usage_calls"] == 10
    assert result["charged_tokens"] == expected_charge
    assert not dispatches
    assert instances[0].root == out
    assert json.loads((out / "config.json").read_text())["inputs"]["refusal_policy"]["retry"] is False
    for path, original in saved_bytes.items():
        assert path.read_bytes() == original
