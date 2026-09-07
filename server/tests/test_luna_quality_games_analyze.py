import copy
import hashlib
import json

import pytest

from scripts import luna_quality_games as collector
from scripts import luna_quality_games_analyze as readout
from shengji.luna import game, quality_panel


def _root_sha(coordinate):
    return hashlib.sha256(repr(coordinate).encode()).hexdigest()


def _write_game(out, coordinate, mirror, points):
    root_sha = _root_sha(coordinate)
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


def _run(tmp_path, *, mirrors=(0, 1), coordinates=(("2", 0, 0), ("2", 1, 1))):
    roster = [{"coordinate": list(c), "root_sha256": _root_sha(c),
               "split": quality_panel.deal_split(c), "root_suit": "NT" if c[1] == 0 else "H"}
              for c in coordinates]
    collector._publish(tmp_path / "config.json", {"inputs": {
        "comparison": "batch4-vs-compact1-paired-gameplay-play-only",
        "agent_assignment": {
            "mirror0": {"team0": "batch4", "team1": "compact1"},
            "mirror1": {"team0": "compact1", "team1": "batch4"}},
        "wave_size": 8, "root_split_roster": roster}})
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


def _tranche(path, coordinates, *, decisions=1, tokens=100, mirrors=(0, 1)):
    _run(path, coordinates=coordinates, mirrors=mirrors)
    config_path = path / "config.json"
    config = collector._load_json(config_path)
    config.update({"arms": list(collector.ARMS), "call_seconds": 120,
                   "mode": "gameplay", "model": "gpt-5.6-luna", "effort": "medium",
                   "runtime": {"binary_sha256": "a" * 64}, "source": {"collector": "b" * 64},
                   "provider_concurrency": 1, "tokens": tokens * 100,
                   "wall_seconds": 18000, "created_unix": 1000})
    config["inputs"].update({"scope": "bounded-coordinate-tranche", "source_panel_count": 52,
                              "selected_coordinate_count": len(coordinates),
                              "panel_manifest_sha256": "c" * 64,
                              "transport": {"tools": "disabled", "policy_mode": "play-only"}})
    config_path.write_bytes(collector.canonical_json_bytes(config))
    arm = {"calls": decisions, "accepted_decisions": decisions, "failed_calls": 0,
           "unknown_usage_calls": 0,
           "usage": {"input_tokens": tokens, "cached_input_tokens": 0, "output_tokens": 0,
                     "reasoning_output_tokens": 0, "total_tokens": tokens, "wall_ms": 1000}}
    collector._publish(path / "progress-00000001-test.json", {
        "status": "running", "charged_tokens": 2 * tokens,
        "pilot_arms": {name: copy.deepcopy(arm) for name in collector.ARMS}})


def test_pool_weights_deals_not_tranches_and_sums_costs_before_ratios(tmp_path, monkeypatch, capsys):
    first, second = tmp_path / "first", tmp_path / "second"
    _tranche(first, (("2", 0, 0), ("2", 1, 1)))  # paired means +2,-2
    _tranche(second, (("3", 0, 0),), decisions=9, tokens=450)  # paired mean +2

    def no_replay(*_args, **_kwargs):
        raise AssertionError("readout must not call a provider or replay games")

    monkeypatch.setattr(game, "_replay_trajectory", no_replay)
    monkeypatch.setattr(collector, "run_gameplay", no_replay)
    result = readout.analyze_many([first, second])
    assert result["status"] == "complete-requested-tranches"
    assert result["covers_source_panel"] is False
    assert result["complete_pairs"] == 3
    assert result["batch4_signed_levels_per_game"]["mean"] == pytest.approx(2 / 3)
    assert result["batch4_signed_levels_per_game"]["deals"] == 3
    assert result["reported_or_reserved_tokens"] == 1100
    assert result["cost_accounting_complete"] is True
    assert result["per_arm_costs_and_failures"]["batch4"]["reported_tokens_per_accepted_decision"] == 55
    assert result["per_arm_costs_and_failures"]["batch4"]["serial_decisions_per_minute"] == 300
    assert [r["readout"]["complete_pairs"] for r in result["runs"]] == [2, 1]
    assert readout.main(["--run", str(first), "--run", str(second)]) == 0
    assert json.loads(capsys.readouterr().out)["batch4_signed_levels_per_game"]["mean"] == pytest.approx(2 / 3)


def test_pool_preserves_incomplete_pairs_and_missing_accounting(tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    _tranche(first, (("2", 0, 0),))
    _tranche(second, (("3", 0, 0),), mirrors=(0,))
    (second / "progress-00000001-test.json").unlink()
    result = readout.analyze_many([first, second])
    assert result["status"] == "partial-requested-tranches"
    assert result["planned_games"] == 4 and result["completed_games"] == 3
    assert result["complete_pairs"] == 1
    assert len(result["missing_games"]) == 1
    assert result["batch4_signed_levels_per_game"]["interval95"] is None
    assert result["per_arm_costs_and_failures"] is None
    assert result["reported_or_reserved_tokens"] is None
    assert result["cost_accounting_complete"] is False


def test_pool_rejects_overlap_even_when_no_pair_is_complete(tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    for path in (first, second):
        _tranche(path, (("2", 0, 0),), mirrors=(0,))
    with pytest.raises(collector.QualityGameplayError, match="^overlapping pooled gameplay deals$"):
        readout.analyze_many([first, second])


def test_full_52_deal_pool_keeps_26_fit_and_26_validation_roots(tmp_path):
    roster = list(game.LunaDesign().root_coordinates)
    first, second = tmp_path / "first", tmp_path / "second"
    _tranche(first, tuple(roster[:8]))
    _tranche(second, tuple(roster[8:]))
    result = readout.analyze_many([first, second])
    assert result["covers_source_panel"] is True
    assert result["status"] == "complete-requested-tranches"
    assert result["complete_pairs"] == result["planned_deals"] == 52
    assert result["completed_games"] == result["planned_games"] == 104
    assert result["complete_pair_splits"] == {"fit": 26, "validation": 26}
    assert set(result["complete_pair_ranks"].values()) == {4}
    assert [run["readout"]["complete_pairs"] for run in result["runs"]] == [8, 44]
    wave = result["wave_dependence_sensitivity"]
    assert wave["planned_waves"] == wave["waves_with_complete_pairs"] == 7
    assert [block["planned_deals"] for block in wave["blocks"]] == [8] * 6 + [4]
    assert len({block["run_config_sha256"] for block in wave["blocks"]}) == 2
    assert [block["wave_index"] for block in wave["blocks"]] == [0, 0, 1, 2, 3, 4, 5]


def test_single_wave_has_no_sensitivity_range_and_original_deal_ci_is_unchanged(tmp_path):
    _run(tmp_path)
    result = readout.analyze(tmp_path)
    wave = result["wave_dependence_sensitivity"]
    assert wave["planned_waves"] == wave["waves_with_complete_pairs"] == 1
    assert wave["blocks"][0]["complete_pairs"] == 2
    assert wave["leave_one_wave_out_ranges"] == {
        "batch4_signed_levels_per_game": None, "batch4_game_win_rate": None}
    assert result["batch4_signed_levels_per_game"]["interval95"] == [-2, 2]


def test_wave_sensitivity_uses_published_order_and_size_not_survivors(tmp_path, monkeypatch):
    # Deliberately not sorted. Remove the first member of wave zero: regrouping
    # only survivors would move the negative deal out of its original wave.
    coordinates = (("4", 0, 0), ("3", 0, 0), ("2", 1, 1), ("5", 0, 0), ("6", 0, 0))
    _run(tmp_path, coordinates=coordinates)
    path = tmp_path / "config.json"
    config = collector._load_json(path)
    config["inputs"]["wave_size"] = 2
    path.write_bytes(collector.canonical_json_bytes(config))
    (tmp_path / collector._game_name(coordinates[0], 1, "terminal")).unlink()
    monkeypatch.setattr(collector, "WAVE_SIZE", 99)
    result = readout.analyze(tmp_path)
    wave = result["wave_dependence_sensitivity"]
    assert wave["planned_waves"] == wave["waves_with_complete_pairs"] == 3
    assert [b["planned_coordinates"] for b in wave["blocks"]] == [
        [list(c) for c in coordinates[:2]], [list(c) for c in coordinates[2:4]],
        [list(coordinates[4])]]
    assert [b["complete_pairs"] for b in wave["blocks"]] == [1, 2, 1]
    assert [b["signed_levels_sum"] for b in wave["blocks"]] == [2, 0, 2]
    assert result["batch4_signed_levels_per_game"]["mean"] == 1
    assert wave["leave_one_wave_out_ranges"] == {
        "batch4_signed_levels_per_game": [2 / 3, 2],
        "batch4_game_win_rate": [2 / 3, 1]}
    assert "not confidence intervals" in wave["interpretation"]


@pytest.mark.parametrize("recorded", [None, True, 0, -1, "8"])
def test_unknown_wave_size_does_not_invent_precision_or_block_old_readout(tmp_path, recorded):
    _run(tmp_path)
    path = tmp_path / "config.json"
    config = collector._load_json(path)
    config["inputs"]["wave_size"] = recorded
    path.write_bytes(collector.canonical_json_bytes(config))
    result = readout.analyze(tmp_path)
    assert result["wave_dependence_sensitivity"]["available"] is False
    assert result["batch4_signed_levels_per_game"]["mean"] == 0


@pytest.mark.parametrize("field,value", [
    ("model", "gpt-5.6-sol"), ("effort", "high"), ("source", {"collector": "d" * 64}),
    ("runtime", {"binary_sha256": "d" * 64}), ("provider_concurrency", 2),
    ("inputs.transport", {"tools": "enabled", "policy_mode": "rollout-enabled"}),
    ("inputs.panel_manifest_sha256", "d" * 64),
])
def test_pool_refuses_recipe_runtime_or_panel_drift(tmp_path, field, value):
    first, second = tmp_path / "first", tmp_path / "second"
    _tranche(first, (("2", 0, 0),))
    _tranche(second, (("3", 0, 0),))
    path = second / "config.json"
    config = collector._load_json(path)
    target = config
    if field.startswith("inputs."):
        target = config["inputs"]
        field = field.removeprefix("inputs.")
    target[field] = value
    path.write_bytes(collector.canonical_json_bytes(config))
    with pytest.raises(collector.QualityGameplayError, match="^pooled gameplay recipe or panel drift$"):
        readout.analyze_many([first, second])
