import json

import pytest

import seed_worker as worker
from test_paired import bot_for_fixture, eight_card_last_seat

ENV = {"SHENGJI_BOT": "fixture"}


def test_worker_publishes_complete_fixture_once(monkeypatch, tmp_path):
    bots = [bot_for_fixture() for _ in range(4)]
    for bot in bots:
        bot.last_bury_record = {"fallback_reason": None}
    rnd = eight_card_last_seat()

    def prepare(game, players):
        game.round = rnd
        for seat, bot in enumerate(players):
            bot.decide_declare(rnd, seat)
        return rnd

    for bot in bots:
        def declare(r, s, final=False, bot=bot):
            bot.last_declare_record = dict(evaluated=True, worlds_completed=bot.value_declare_worlds,
                                           worlds=bot.value_declare_worlds, fallback_reason=None)
        bot.decide_declare = declare
    monkeypatch.setattr(worker, "prepare_round", prepare)
    monkeypatch.setattr(worker.releases, "_build", lambda env, full, seed: ("fixture", bots[seed % 10]))
    monkeypatch.setattr(worker, "FIRST_SEED", 100)
    seed = 100
    worker.write_seed(seed, tmp_path, ENV)
    path = tmp_path / str(seed) / "result.json"
    rec = json.loads(path.read_text())
    assert rec["status"] == "complete" and rec["seed"] == seed
    assert len(rec["declares"]) == 4 and rec["world_counts"] == {"64": 5}
    assert rec["bury_fallback"] is None and rec["belief_fallbacks"] == 0
    assert rec["decisions"] == 5 and len(rec["eligible"]) == 1
    assert rec["attacker_points"] == rnd.attacker_points
    import readout
    monkeypatch.setattr(readout, "FIRST_SEED", seed)
    monkeypatch.setattr(readout, "DEALS", 1)
    verdict = readout.analyze({seed: rec}, arm_name=ENV["SHENGJI_BOT"])
    assert verdict["verdict"] == "FAIL" and verdict["eligible"] == 1
    with pytest.raises(FileExistsError):
        worker.write_seed(seed, tmp_path, ENV)


def test_solver_fault_stays_in_its_seed_slot(monkeypatch, tmp_path):
    def fail(*_):
        raise RuntimeError("full-reference node cap")
    monkeypatch.setattr(worker, "play_seed", fail)
    monkeypatch.setattr(worker, "FIRST_SEED", 100)
    with pytest.raises(RuntimeError, match="node cap"):
        worker.write_seed(100, tmp_path, ENV)
    rec = json.loads((tmp_path / "100/result.json").read_text())
    assert rec["status"] == "fault" and rec["seed"] == 100
    with pytest.raises(FileExistsError):
        worker.write_seed(100, tmp_path, ENV)
    with pytest.raises(ValueError, match="outside"):
        worker.write_seed(99, tmp_path, ENV)
