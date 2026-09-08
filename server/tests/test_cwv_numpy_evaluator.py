import copy
import asyncio
import os
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest

from shengji.ai.cwv_policy import CompleteWorldEvaluator, shared_evaluator
from shengji.ai.cwv_numpy_evaluator import NumpyCompleteWorldEvaluator
from shengji.train.cwv_shortlist import make_shortlist_bot, CWVShortlistBot
from tests.test_cwv_numpy import _actual_export
from tests.test_cwv_static_public import _state_after


@pytest.mark.parametrize("version", [1, 2])
def test_actual_evaluator_uses_same_states_perspectives_and_shared_immutable_weights(tmp_path, version):
    package, net = _actual_export(tmp_path, version)
    numpy_eval = shared_evaluator(package, encoding="mlp-static", max_batch=2)
    torch_eval = CompleteWorldEvaluator(None, model=net, encoding="mlp-static", max_batch=2)
    states = [_state_after(41, ply) for ply in (1, 35, 70)]
    for seat in range(4):
        np.testing.assert_allclose(numpy_eval.score(states, seat), torch_eval.score(states, seat),
                                   rtol=0, atol=2e-5)
    another = shared_evaluator(package, encoding="mlp-static", max_batch=2)
    assert numpy_eval is not another and another.calls == 0
    assert numpy_eval.model._weights is another.model._weights
    numpy_eval.metadata["encoder"]["local-note"] = "not shared"
    assert "local-note" not in another.metadata["encoder"]
    cloned = copy.deepcopy(numpy_eval)
    assert cloned.model._weights is numpy_eval.model._weights
    cloned.calls += 1
    assert cloned.calls == numpy_eval.calls + 1
    assert numpy_eval.identity()["checkpoint_sha256"] == numpy_eval.model.package_sha256


def test_registered_consumer_can_load_package_without_torch(tmp_path):
    package, _ = _actual_export(tmp_path)
    code = '''
import sys
class BlockTorch:
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "torch" or fullname.startswith("torch."):
            raise RuntimeError("serving attempted to import torch")
sys.meta_path.insert(0, BlockTorch())
from shengji.ai.registry import register_cwv_shortlist_policies, make_bot
from shengji.train.cwv_shortlist import CWVShortlistBot
names = register_cwv_shortlist_policies(sys.argv[1], [32])
bot = make_bot(names[0], seed=4)
assert type(bot) is CWVShortlistBot
assert bot.evaluator.backend == "numpy"
assert bot.shortlist_config.worlds == 32
assert bot.REPORT_FOLD_WORLDS == 300
assert "torch" not in sys.modules
'''
    env = {"PATH": os.environ["PATH"], "PYTHONPATH": str(Path(__file__).parents[1])}
    subprocess.run([sys.executable, "-c", code, str(package)], env=env, check=True, timeout=30)


def test_numpy_shortlist_keeps_rng_and_action_on_bounded_consumer_fixture(tmp_path):
    package, _ = _actual_export(tmp_path)
    options = dict(seed=5, worlds=2, selection_worlds=30, report_worlds=30)
    numpy_bot = make_shortlist_bot(package, **options)
    torch_bot = make_shortlist_bot(tmp_path / "source-v1.pt", **options)
    assert type(numpy_bot) is CWVShortlistBot
    state = _state_after(41, 60)
    seat = (state.trick.leader + len(state.trick.plays)) % 4
    assert numpy_bot.decide_play(copy.deepcopy(state), seat) == torch_bot.decide_play(copy.deepcopy(state), seat)
    assert numpy_bot.rng.getstate() == torch_bot.rng.getstate()


def test_actual_room_uses_admission_telemetry_and_discards_stale_numpy_decision(tmp_path):
    from shengji.api import server as srv
    from tests.test_bot_scheduler import _real_room
    package, _ = _actual_export(tmp_path)
    room = _real_room()
    room.game.round = _state_after(41, 60)
    room.bot = make_shortlist_bot(package, seed=5, worlds=2,
                                 selection_worlds=30, report_worlds=30)
    events = []
    room.log_event = lambda kind, **fields: events.append((kind, fields))
    before = room.bot.rng.getstate()
    seat = room.round.turn
    async def scenario():
        prepared = await srv._paced_bot_step(room, seat, minimum_turn_seconds=0)
        assert prepared is not None
        assert [f["event"] for k, f in events if k == "model_search"] == ["queued", "running", "completed"]
        assert room.bot.rng.getstate() == before
        assert prepared.decision.snapshot.bot_copy.evaluator.model._weights is room.bot.evaluator.model._weights
        room.seats[seat].is_bot = False
        assert not srv._commit_bot_turn(room, prepared)
        assert room.bot.rng.getstate() == before
    asyncio.run(scenario())


def test_model_failure_is_visible_and_never_commits_snapshot(tmp_path, monkeypatch):
    from shengji.api import server as srv
    from tests.test_bot_scheduler import _real_room
    package, _ = _actual_export(tmp_path)
    room = _real_room()
    room.bot = make_shortlist_bot(package, seed=5, worlds=2,
                                 selection_worlds=30, report_worlds=30)
    before = room.bot.rng.getstate()
    events, broadcasts = [], []
    room.log_event = lambda kind, **fields: events.append((kind, fields))
    async def fail(snapshot):
        snapshot.bot_copy.rng.random()
        raise RuntimeError("private hidden cards must not leak")
    async def broadcast(r):
        broadcasts.append(r.round.message)
    monkeypatch.setattr(srv, "_compute_bot_turn_off_loop", fail)
    monkeypatch.setattr(srv, "broadcast", broadcast)
    async def scenario():
        with pytest.raises(RuntimeError):
            await srv._paced_bot_step(room, room.round.turn, minimum_turn_seconds=0)
    asyncio.run(scenario())
    assert room.bot.rng.getstate() == before
    assert len(broadcasts) == 1 and "Model search failed" in broadcasts[0]
    assert [f["event"] for k, f in events] == ["queued", "running", "error"]
    assert "private hidden" not in repr(events) + repr(broadcasts)
