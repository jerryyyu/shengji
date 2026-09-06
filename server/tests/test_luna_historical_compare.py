import copy
import json

import pytest

from scripts import luna_historical_compare as compare
from scripts import luna_historical_panel as panel
from shengji.ai.heuristic import HeuristicBot
from shengji.luna import game
from shengji.luna.turn import DecisionPacket
from shengji.luna.transport import intent_output_schema, planner_prompt
from shengji.luna.turn import Intent, PlannerResponse, Usage


def fixture(coordinate=("2", 0, 0)):
    root = game.build_root(bytes(range(32)), coordinate)
    ballot_bot = game.WideHeuristicBallotBot(seed=0)
    while root.phase == "play":
        ballot = [list(action) for action in ballot_bot._candidates(root, root.turn)]
        if len(ballot) > 1:
            break
        root.play(root.turn, HeuristicBot().decide_play(root, root.turn))
    assert len(ballot) > 1
    team = root.turn % 2
    row = {"coordinate": list(coordinate), "treatment_team": team,
           "role": "banker-team" if team == root.banker % 2 else "attacker-team"}
    before = game._state_snapshot(root)
    chosen = ballot[-1]
    root.play(root.turn, chosen)
    position = {"snapshot": before, "state_after_action": game._state_snapshot(root),
                "candidate_ballot": [{"cards": a} for a in ballot],
                "chosen_action": {"cards": chosen, "candidate_index": len(ballot) - 1},
                "decision_ordinal": 0, "decision_sha256": "a" * 64,
                "thresholds": [0]}
    row["positions"] = [position]
    return row, position


def test_real_transition_to_real_transport_preserves_historical_ballot():
    row, position = fixture()
    packet = compare.prepare_position(row, position)
    assert packet.state == position["snapshot"]
    assert packet.candidates == tuple(tuple(a["cards"]) for a in position["candidate_ballot"])
    assert packet.memory.strategy_note == ""
    assert packet.decision_sha256 != position["decision_sha256"]
    assert DecisionPacket.from_mapping(packet.payload()) == packet
    schema = intent_output_schema(packet, allowed_kinds=("play",))
    assert schema
    assert planner_prompt(packet, policy_mode="play-only")
    assert position["chosen_action"]["cards"] == list(packet.candidates[-1])


@pytest.mark.parametrize("field,message", [
    ("state_after_action", "historical chosen transition drift"),
    ("chosen_action", "historical chosen action drift"),
    ("candidate_ballot", "historical candidate legality drift"),
])
def test_consumer_refuses_transition_action_and_candidate_drift(field, message):
    row, position = fixture()
    if field == "state_after_action":
        position[field]["attacker_points"] += 100
    elif field == "chosen_action":
        position[field]["cards"] = ["not-a-card"]
    else:
        position[field][0]["cards"] = ["not-a-card"]
    with pytest.raises(compare.HistoricalCompareError, match=f"^{message}$"):
        compare.prepare_position(row, position)


def test_role_binding_and_group_repeated_deal_refuse():
    row, position = fixture()
    row["treatment_team"] = 1 - row["treatment_team"]
    with pytest.raises(compare.HistoricalCompareError, match="^historical mover/team drift$"):
        compare.prepare_position(row, position)
    row, position = fixture()
    row["positions"].append(copy.deepcopy(position))
    with pytest.raises(compare.HistoricalCompareError, match="^historical duplicate position$"):
        compare.group_positions([row])


def test_threshold_dedup_and_grouping_independent_deals():
    row1, position1 = fixture()
    row2, _ = fixture(("3", 0, 0))
    position1["thresholds"] = [0, 6]
    groups = compare.group_positions([row1, row2])
    assert sum(map(len, groups.values())) == 2
    for packets in groups.values():
        assert len({p.coordinate for p in packets}) == len(packets)


def panel_fixture(root, count=4):
    binding = {"report_sha256": panel.REPORT_SHA256,
               "source": {"git_head": panel.ARCHIVED_HEAD},
               "thresholds": list(panel.THRESHOLDS)}
    shards = []
    for rank in ("2", "3", "4", "5")[:count]:
        row, _ = fixture((rank, 0, 0))
        row.update(schema=panel.SCHEMA, mode=panel.MODE, incomplete=False,
                   missing_thresholds=[6, 12, 18],
                   binding={**binding, "coordinate": row["coordinate"], "role": row["role"]})
        path = panel.shard_path(root, row["coordinate"], row["role"])
        panel._write_private(path, row)
        shards.append({**row, "path": path, "sha256": panel._sha_bytes(path.read_bytes())})
    manifest = panel._manifest(shards, binding=binding, incomplete=True)
    panel._write_private(root / "manifest.json", manifest)
    return manifest


def test_completed_roster_required_before_provider_construction(tmp_path):
    panel_fixture(tmp_path)
    with pytest.raises(compare.HistoricalCompareError,
                       match="^historical complete population required$"):
        compare.run_compare(tmp_path, tmp_path / "out", tokens=100000,
                            wall_seconds=120, pilot_factory=lambda _: pytest.fail("provider created"))


def test_manifest_bound_bytes_refuse_and_missing_thresholds_survive(tmp_path):
    manifest = panel_fixture(tmp_path, 1)
    _, rows, _, groups = compare.prepare_panel(tmp_path, require_complete=False)
    description = compare.describe_panel(rows, groups)
    assert description["split"] == "opened-historical-not-fresh-fit-or-validation"
    assert list(description["missing_thresholds"].values()) == [[6, 12, 18]]
    assert description["historical_reference_token_usage"] is None
    path = tmp_path / manifest["shards"][0]["filename"]
    row = json.loads(path.read_bytes())
    row["positions"][0]["chosen_action"]["candidate_index"] = 999
    panel._write_private(path, row)
    with pytest.raises(compare.HistoricalCompareError,
                       match="^historical shard bytes or identity drift$"):
        compare.prepare_panel(tmp_path, require_complete=False)


@pytest.mark.parametrize("fail_first", [False, True])
def test_existing_pilot_journals_both_arms_and_reopens_without_redispatch(
        tmp_path, monkeypatch, fail_first):
    from shengji.luna import token_batch
    panel_fixture(tmp_path)
    dispatched = []

    class Transport:
        runtime = {"test": "offline"}
        model, reasoning_effort = "fixture-only", "medium"
        last_evidence = None

        def __init__(self, **_):
            pass

        def call_many(self, packets):
            dispatched.append(packets)
            assert len({p.coordinate for p in packets}) == len(packets)
            # The archived selected action must not appear as a label in inputs.
            assert all("chosen_action" not in p.payload() for p in packets)
            if fail_first and len(dispatched) == 1:
                raise RuntimeError("offline provider refusal")
            return tuple(PlannerResponse(
                Intent("play", p.decision_sha256, candidate_index=0,
                       confidence="low", planning_note="offline witness"),
                Usage(10, 0, 10, 1), team=p.team, packet_sha256=p.sha256,
                memory_sha256=p.memory.sha256) for p in packets)

    monkeypatch.setattr(compare.pilot_module, "CodexExecPlannerTransport", Transport)
    monkeypatch.setattr(token_batch, "CompactBatchTransport", Transport)
    out = tmp_path / "calls"
    args = dict(tokens=1_000_000, wall_seconds=1200, require_complete=False)
    result = compare.run_compare(tmp_path, out, **args)
    assert result["actual_call_count"] == len(dispatched) == 5
    assert result["failed_call_count"] == int(fail_first)
    assert result["panel"]["independent_deals"] == 4
    assert result["status"] == ("historical-comparison-complete-with-refusals"
                                 if fail_first else "historical-comparison-complete")
    compact = [json.loads(p.read_bytes()) for p in out.glob("compact1-*.json")]
    batches = [json.loads(p.read_bytes()) for p in out.glob("batch4-*.json")]
    assert len(compact) == 4 and len(batches) == 1
    assert {p for row in compact for p in row["packet_hashes"]} == set(batches[0]["packet_hashes"])
    if fail_first:
        failed = [row for row in compact if not row["accepted"]]
        assert len(failed) == 1 and failed[0]["usage"] is None
        assert failed[0]["charged_tokens"] == 30_000
    assert compare.run_compare(tmp_path, out, **args) == result
    assert len(dispatched) == 5
    assert all(p.stat().st_mode & 0o077 == 0 for p in out.glob("*.json"))


def test_zero_provider_prepare_is_cli_default(tmp_path, monkeypatch, capsys):
    panel_fixture(tmp_path, 1)
    prepare = compare.prepare_panel
    monkeypatch.setattr(compare, "prepare_panel", lambda root: prepare(root, require_complete=False))
    monkeypatch.setattr(compare.pilot_module, "Pilot", lambda _: pytest.fail("provider created"))
    assert compare.main(["--panel-root", str(tmp_path)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["positions"] == 1
    assert result["historical_reference_new_provider_calls"] == 0
