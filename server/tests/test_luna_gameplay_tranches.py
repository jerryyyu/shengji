import copy
from pathlib import Path
from types import SimpleNamespace
import time

import pytest

from scripts import luna_quality_compare as compare
from scripts import luna_quality_games as gameplay
from scripts import luna_token_pilot as token_pilot
from shengji.luna import game, quality_panel
from shengji.luna.canonical import canonical_json_bytes

from test_luna_quality_games import FakePilot, FastProduction, SECRET


def _full_panel(path):
    rows = []
    entries = []
    for coordinate in game.LunaDesign().root_coordinates:
        row = quality_panel.capture_coordinate(
            SECRET, coordinate, producer_factory=FastProduction)
        rows.append(row)
        raw = canonical_json_bytes(row)
        quality_panel.shard_path(path, coordinate).write_bytes(raw)
        entries.append({"coordinate": list(coordinate),
                        "sha256": compare._sha_bytes(raw),
                        "status": row["status"]})
    path.joinpath("manifest.json").write_bytes(canonical_json_bytes({
        "schema": quality_panel.SCHEMA, "private": True, "shards": entries}))
    return rows


COORDINATES = [["2", 0, 0], ["3", 1, 1], ["4", 0, 0], ["5", 1, 1],
               ["6", 0, 0], ["7", 1, 1], ["8", 0, 0], ["9", 1, 1]]


def test_cli_coordinate_tranche_runs_16_games_and_binds_scope(tmp_path, monkeypatch):
    _full_panel(tmp_path)
    selector = tmp_path / "coordinates.json"
    selector.write_bytes(canonical_json_bytes(list(reversed(COORDINATES))))
    monkeypatch.setattr(gameplay.token_pilot, "Pilot", FakePilot)
    out = tmp_path / "out"
    assert gameplay.main([
        "--panel-root", str(tmp_path), "--coordinates-file", str(selector),
        "--out", str(out), "--codex-binary", "/usr/bin/true",
        "--tokens", "9000000", "--wall-seconds", "18000",
        "--call-seconds", "120"]) == 0

    result = gameplay._load_json(out / "result.json")
    assert result["status"] == "paired-gameplay-tranche-complete"
    assert result["scope"] == "bounded-coordinate-tranche"
    assert result["source_panel_count"] == 52
    assert result["selected_coordinate_count"] == 8
    assert result["completed_games"] == 16
    pilot = FakePilot.instances[-1]
    assert pilot.inputs["scope"] == "bounded-coordinate-tranche"
    assert pilot.inputs["source_panel_count"] == 52
    assert pilot.inputs["selected_coordinate_count"] == 8
    assert [row["coordinate"] for row in pilot.inputs["root_split_roster"]] == COORDINATES
    batch_calls = [packets for arm, _, packets in pilot.calls if arm == "batch4"]
    assert any(len(packets) == 4 for packets in batch_calls)
    for packets in batch_calls:
        assert 1 <= len(packets) <= 4
        assert len({packet.coordinate for packet in packets}) == len(packets)
        assert len({packet.mirror for packet in packets}) == 1

    from scripts import luna_quality_games_analyze as readout
    gameplay._publish(out / "config.json", {"inputs": pilot.inputs})
    analyzed = readout.analyze(out)
    assert analyzed["status"] == "complete-tranche"
    assert analyzed["scope"] == "bounded-coordinate-tranche"
    assert analyzed["source_panel_count"] == 52
    assert analyzed["planned_deals"] == 8
    assert analyzed["planned_games"] == 16
    assert analyzed["completed_games"] == 16
    assert analyzed["complete_pairs"] == 8
    (out / gameplay._game_name(tuple(COORDINATES[0]), 1, "terminal")).unlink()
    with pytest.raises(gameplay.QualityGameplayError,
                       match="^completed gameplay is missing games$"):
        readout.analyze(out)


def test_committed_first_tranche_roster_is_exact():
    path = Path(__file__).parents[1] / "runs/luna_quality_gameplay_tranche1_20260906.json"
    assert gameplay._load_json(path) == COORDINATES


def test_cli_null_selector_cannot_expand_to_full_panel(tmp_path, monkeypatch, capsys):
    selector = tmp_path / "coordinates.json"
    selector.write_bytes(canonical_json_bytes(None))
    def must_not_run(*args, **kwargs):
        raise AssertionError("null selector reached the full-panel collector")
    monkeypatch.setattr(gameplay, "run_gameplay", must_not_run)
    with pytest.raises(SystemExit) as exc:
        gameplay.main([
            "--panel-root", str(tmp_path), "--coordinates-file", str(selector),
            "--out", str(tmp_path / "out"), "--codex-binary", "/usr/bin/true",
            "--tokens", "9000000", "--wall-seconds", "18000",
            "--call-seconds", "120"])
    assert exc.value.code == 2
    assert "coordinate selection must be a non-empty array" in capsys.readouterr().err


@pytest.mark.parametrize("selection", [
    [],
    [["2", 0, 0], ["2", 0, 0]],
    [["2", 0, 99]],
    [["2", True, 0]],
    [["2", 0]],
])
def test_invalid_coordinate_selection_rejected_before_pilot(tmp_path, monkeypatch,
                                                            selection):
    _full_panel(tmp_path)
    called = []

    class MustNotConstruct:
        def __init__(self, args):
            called.append(args)
            raise AssertionError("pilot constructed for invalid selection")

    monkeypatch.setattr(gameplay.token_pilot, "Pilot", MustNotConstruct)
    with pytest.raises(gameplay.QualityGameplayError):
        gameplay.run_gameplay(tmp_path, tmp_path / "out",
                              coordinates=selection)
    assert not called


def test_changed_tranche_roster_is_rejected_by_real_pilot_configure(tmp_path):
    args = SimpleNamespace(mode="gameplay", arms=list(gameplay.ARMS),
                           tokens=9_000_000, wall_seconds=18_000,
                           call_seconds=120)
    pilot = object.__new__(token_pilot.Pilot)
    pilot.args = args
    pilot.root = tmp_path
    pilot.created = time.time()
    pilot.deadline_ns = time.monotonic_ns() + 18_000 * 1_000_000_000
    pilot.base = SimpleNamespace(runtime={"test": "fixed"},
                                 model=game.MODEL, reasoning_effort="medium")
    pilot.source = {"test": "fixed-source"}
    roster = [{"coordinate": ["2", 0, 0], "root_sha256": "a" * 64,
               "root_suit": "spades", "split": "fit",
               "row_sha256": "b" * 64}]
    inputs = gameplay._pilot_inputs(
        {"schema": quality_panel.SCHEMA}, "c" * 64, roster,
        source_panel_count=52)
    pilot.configure(inputs)
    changed = copy.deepcopy(inputs)
    changed["root_split_roster"][0]["coordinate"] = ["3", 0, 0]
    with pytest.raises(ValueError, match="inputs or implementation changed"):
        pilot.configure(changed)
