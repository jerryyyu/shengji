import copy

import pytest

from scripts import luna_quality_games as collector
from scripts import luna_quality_games_analyze as readout
from shengji.luna import game, quality_panel


def _write_game(out, coordinate, mirror, points):
    root_sha = ("a" if coordinate[1] == 0 else "b") * 64
    receipt = game.TerminalReceipt(
        coordinate, mirror, root_sha, "c" * 64, points,
        game.signed_level_utility(points, banker_seat=coordinate[1],
                                  perspective_seat=0), True).payload()
    metadata = {
        "schema": collector.RESULT_SCHEMA + "-game-metadata",
        "comparison": "batch4-vs-compact1-play-only",
        "coordinate": list(coordinate), "mirror": mirror,
        "split": quality_panel.deal_split(coordinate), "root_sha256": root_sha,
        "agent_for_team": {"0": game.agent_for_team(mirror, 0),
                           "1": game.agent_for_team(mirror, 1)},
        "arms": {"agent0": "batch4", "agent1": "compact1"},
        "continuation": "play-only", "terminal_receipt_sha256": receipt["receipt_sha256"],
        "trajectory_sha256": receipt["trajectory_sha256"]}
    collector._publish(out / collector._game_name(coordinate, mirror, "terminal"), receipt)
    collector._publish(out / collector._game_name(coordinate, mirror, "metadata"), metadata)


def _run(tmp_path, *, mirrors=(0, 1)):
    coordinates = (("2", 0, 0), ("2", 1, 1))
    roster = [{"coordinate": list(c), "root_sha256": ("a" if c[1] == 0 else "b") * 64,
               "split": quality_panel.deal_split(c), "root_suit": "NT" if c[1] == 0 else "H"}
              for c in coordinates]
    collector._publish(tmp_path / "config.json", {"inputs": {
        "comparison": "batch4-vs-compact1-paired-gameplay-play-only",
        "agent_assignment": {
            "mirror0": {"team0": "batch4", "team1": "compact1"},
            "mirror1": {"team0": "compact1", "team1": "batch4"}},
        "root_split_roster": roster}})
    for c in coordinates:
        for mirror in mirrors:
            _write_game(tmp_path, c, mirror, 0 if mirror == 0 else 120)
    return coordinates


def test_signed_mirror_and_deal_cluster_readout(tmp_path):
    _run(tmp_path)
    result = readout.analyze(tmp_path)
    assert result["status"] == "complete-panel"
    assert result["completed_games"] == 4
    assert result["complete_pairs"] == 2
    assert [p["batch4_signed_levels"] for p in result["pairs"]] == [[3, 1], [-3, -1]]
    assert [p["mean_signed_levels"] for p in result["pairs"]] == [2, -2]
    assert result["batch4_signed_levels_per_game"]["mean"] == 0
    assert result["batch4_signed_levels_per_game"]["deals"] == 2  # Not four games.
    assert result["batch4_signed_levels_per_game"]["interval95"] == [-2, 2]
    assert result["batch4_game_win_rate"]["mean"] == .5
    assert result["paired_deal_wins_ties_losses"] == {"wins": 1, "ties": 0, "losses": 1}
    assert result["complete_pair_root_suits"] == {"H": 1, "NT": 1}
    assert result["complete_pair_splits"] == {"fit": 1, "validation": 1}


def test_missing_mirror_not_imputed_and_single_pair_has_no_interval(tmp_path):
    coordinates = _run(tmp_path, mirrors=(0,))
    _write_game(tmp_path, coordinates[0], 1, 120)
    result = readout.analyze(tmp_path)
    assert result["status"] == "partial-panel"
    assert result["completed_games"] == 3
    assert result["complete_pairs"] == 1
    assert result["batch4_signed_levels_per_game"] == {
        "mean": 2, "deals": 1, "interval95": None}
    assert result["missing_games"] == [{
        "coordinate": ["2", 1, 1], "mirror": 1,
        "terminal_present": False, "metadata_present": False}]
    collector._publish(tmp_path / "result.json", {"status": "paired-gameplay-complete"})
    with pytest.raises(collector.QualityGameplayError, match="completed gameplay is missing games"):
        readout.analyze(tmp_path)


@pytest.mark.parametrize("field,value", [
    ("arms", {"agent0": "compact1", "agent1": "batch4"}),
    ("split", "validation"), ("root_sha256", "d" * 64),
    ("trajectory_sha256", "d" * 64), ("continuation", "rollout-enabled"),
])
def test_metadata_refusals(tmp_path, field, value):
    coordinates = _run(tmp_path)
    path = tmp_path / collector._game_name(coordinates[0], 0, "metadata")
    body = collector._load_json(path)
    body[field] = copy.deepcopy(value)
    path.write_bytes(collector.canonical_json_bytes(body))
    with pytest.raises(collector.QualityGameplayError, match="gameplay metadata binding drift"):
        readout.analyze(tmp_path)


def test_progress_accounts_for_failures_without_reopening_provider_traces(tmp_path):
    _run(tmp_path, mirrors=(0,))
    collector._publish(tmp_path / "progress-00000007-abc.json", {
        "status": "stopped-on-refusal", "charged_tokens": 999,
        "pilot_arms": {"batch4": {"calls": 3, "failed_calls": 1}}})
    result = readout.analyze(tmp_path)
    assert result["reported_or_reserved_tokens"] == 999
    assert result["per_arm_costs_and_failures"] == {"batch4": {"calls": 3, "failed_calls": 1}}
    assert result["complete_pairs"] == 0
    assert result["batch4_signed_levels_per_game"] is None
