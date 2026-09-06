from __future__ import annotations

import json
from concurrent.futures import Future

import pytest

from shengji.luna import game
from shengji.luna import quality_panel as panel
from shengji.ai.heuristic import HeuristicBot
from shengji.ai.registry import REGISTRY
from shengji.engine.cards import Ordering
from shengji.engine.round import Round, Trick


def test_coordinate_seed_and_stage_selection_are_outcome_free():
    secret = bytes(range(32))
    coord = game.LunaDesign().root_coordinates[0]
    assert panel.coordinate_tasks()[0] == ("2", 0, 0)
    assert len(panel.coordinate_tasks()) == 52
    assert game.root_seed(secret, coord) == 8615303199348998523
    assert game.root_seed(secret, coord) != game.root_seed(b"x" * 32, coord)
    root_a = game.build_root(secret, coord)
    root_b = game.build_root(secret, coord)
    root_other = game.build_root(b"x" * 32, coord)
    assert game.root_identity(root_a) == game.root_identity(root_b)
    assert game.root_identity(root_a) != game.root_identity(root_other)
    assert panel.deal_split(("2", 0, 0)) == "fit"
    assert panel.deal_split(("2", 0, 1)) == "validation"
    assert panel.select_stage(0, [["A"], ["K"]])
    assert not panel.select_stage(0, [["A"]])
    assert not panel.select_stage(1, [["A"], ["K"]])


def test_capture_fixture_has_panel_and_full_production_trajectory():
    # Avoid the expensive production search in this unit test while retaining
    # the real build_root and engine play mechanics.
    class FakeProducer:
        def __init__(self, seed=None):
            del seed

        def _candidates(self, rnd, seat):
            return [HeuristicBot().decide_play(rnd, seat)]

        def decide_play(self, rnd, seat):
            return HeuristicBot().decide_play(rnd, seat)

    class FakeWide(FakeProducer):
        def _candidates(self, rnd, seat):
            first = super()._candidates(rnd, seat)[0]
            return [first, first[:]]

    row = panel.capture_coordinate(bytes(range(32)), ("2", 0, 0),
                                   producer_factory=FakeProducer,
                                   ballot_factory=FakeWide)
    assert row["status"] == "complete"
    assert row["root_seed"] == game.root_seed(bytes(range(32)), ("2", 0, 0))
    assert row["source_continuation_policy"] == "mc-s0-report-lcb"
    assert {stage["decision_ordinal"] for stage in row["stages"]} == {0, 12, 24, 36}
    assert sum(len(event["engine_accepted_action"]) for event in row["trajectory"]) == 100
    assert all(event["engine_accepted"] for event in row["trajectory"])


def test_atomic_successes_resume_and_summary_are_order_independent(tmp_path, monkeypatch):
    secret = bytes(range(32))
    design = game.LunaDesign()
    coords = design.root_coordinates[:2]
    tiny = game.LunaDesign(namespace=design.namespace)
    monkeypatch.setattr(panel, "coordinate_tasks", lambda design=None: coords)

    def fake_capture(secret, coordinate, **kwargs):
        del secret, kwargs
        if coordinate[2] == 1:
            raise RuntimeError("synthetic task failure")
        return {"schema": panel.SCHEMA, "private": True,
                "coordinate": list(coordinate), "status": "complete",
                "split": panel.deal_split(coordinate), "source_tag": "production:mc-s0-report-lcb",
                "stages": [], "trajectory": []}

    monkeypatch.setattr(panel, "capture_coordinate", fake_capture)
    first = panel.run_panel(secret, tmp_path, design=tiny)
    shard = panel.shard_path(tmp_path, coords[0])
    saved = shard.read_bytes()
    failed = panel.shard_path(tmp_path, coords[1])
    assert json.loads(failed.read_text())["status"] == "incomplete"
    second = panel.run_panel(secret, tmp_path, workers=2, design=tiny)
    assert shard.read_bytes() == saved
    assert first["summary"] == second["summary"]
    assert panel.summarize([json.loads(shard.read_text()),
                            json.loads(panel.shard_path(tmp_path, coords[1]).read_text())]) == first["summary"]

    with pytest.raises(panel.QualityPanelError, match="conflicting"):
        panel.run_panel(b"x" * 32, tmp_path, design=tiny)


def test_capture_failure_distinguishes_attempted_and_accepted():
    row = panel.capture_failure(bytes(range(32)), ("2", 0, 0), RuntimeError("boom"))
    assert row["status"] == "incomplete"
    assert row["root_seed"] is None


def test_rejected_engine_throw_is_not_relabelled_as_accepted():
    # This is the engine's legal failed-throw witness: the submitted
    # six-card throw is accepted by Round.play but coerced to D7+D7.
    def failed_throw_root(secret, coordinate):
        del secret, coordinate
        rnd = Round("7", 0)
        rnd.phase = "play"
        rnd.turn = 0
        rnd.trump_suit = "H"
        rnd.trump_is_nt = False
        rnd.ordering = Ordering("H", "7")
        rnd.hands = [["C7", "C7", "D7", "D7", "H7", "H7", "S8"],
                     ["LJ", "LJ"], ["C8"], ["D8"]]
        rnd.kitty = []
        rnd.buried = []
        rnd.history = []
        rnd.trick = Trick(leader=0)
        return rnd

    witness = ["C7", "C7", "D7", "D7", "H7", "H7"]

    class ThrowProducer:
        def __init__(self, seed=None):
            del seed

        def _candidates(self, rnd, seat):
            del rnd, seat
            return [witness]

        def decide_play(self, rnd, seat):
            del rnd, seat
            return witness

    class Wide(ThrowProducer):
        def _candidates(self, rnd, seat):
            return [witness, ["C7", "C7"]]

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(panel.game, "build_root", failed_throw_root)
    row = panel.capture_coordinate(bytes(range(32)), ("7", 0, 0),
                                   producer_factory=ThrowProducer,
                                   ballot_factory=Wide)
    monkeypatch.undo()
    event = row["trajectory"][0]
    assert event["attempted_action"] == sorted(witness)
    assert event["engine_accepted_action"] == ["D7", "D7"]
    assert event["engine_accepted"] is True
    assert event["failed_throw"] is True


def test_real_production_registry_wiring_and_process_executor(monkeypatch, tmp_path):
    assert REGISTRY[panel.PRODUCTION_POLICY] is not None
    root = game.build_root(bytes(range(32)), ("2", 0, 0))
    bot = REGISTRY[panel.PRODUCTION_POLICY](seed=3)
    assert bot._candidates(root, root.turn)

    coords = game.LunaDesign().root_coordinates[:2]
    monkeypatch.setattr(panel, "coordinate_tasks", lambda design=None: coords)
    monkeypatch.setattr(panel, "capture_coordinate",
                        lambda secret, coordinate: {
                            "schema": panel.SCHEMA, "private": True,
                            "coordinate": list(coordinate), "status": "complete",
                            "split": panel.deal_split(coordinate),
                            "source_tag": panel.PRODUCTION_SOURCE_TAG,
                            "source_tags": [panel.PRODUCTION_SOURCE_TAG],
                            "stages": [], "trajectory": []})
    seen = {}

    class FakePool:
        def __init__(self, *, max_workers, initializer):
            seen["workers"] = max_workers
            initializer()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def submit(self, fn, payload):
            future = Future()
            try:
                future.set_result(fn(payload))
            except Exception as exc:
                future.set_exception(exc)
            return future

    monkeypatch.setattr(panel, "ProcessPoolExecutor", FakePool)
    panel.run_panel(bytes(range(32)), tmp_path, workers=2)
    assert seen["workers"] == 2
