"""The ``pv-search`` production wrapper (`train.pv_search_policy`) on a real joint NumPy
package, through the server's snapshot/commit path.

Witnesses: the registry name and type guard; the env recipe refuses an unpinned package;
the wrapper's decision is IDENTICAL to the screened harness (`PolicyValueBot`) on the same
state, seed and package; the bot survives ``copy.deepcopy`` inside `_paced_bot_step` and
commits through `_commit_bot_turn` with the live RNG untouched and the numpy model-serving
branch taken; an expired serving budget returns the heuristic anchor with a fallback record
and restores the sampler stream; the encoder version comes from the package.
"""
import asyncio
import copy
import random

import numpy as np
import pytest

from shengji.ai.heuristic import HeuristicBot
from shengji.ai.registry import REGISTRY, make_bot, register_pv_search_policies
from shengji.api import server as srv
from shengji.engine.game import Game
from shengji.train import pv_search_policy as pv


@pytest.fixture(scope="module")
def package(tmp_path_factory):
    """A tiny #425-shaped joint net exported as ONE v2 NumPy package (value + policy head)."""
    torch = pytest.importorskip("torch")
    from scripts.export_cwv_numpy import export_cwv_numpy
    from shengji.ai.cwv_policy import file_sha256, local_encoder_identity
    from shengji.rl.value_checkpoint import save_checkpoint
    from shengji.rl.value_model import ValueModelConfig, ValueNetwork
    d = tmp_path_factory.mktemp("pv")
    torch.manual_seed(11)
    net = ValueNetwork(ValueModelConfig(architecture="mlp", width=32, feedforward_width=64,
                                        public_dim=561, enc_version=2, attention_heads=1,
                                        trunk_block="residual", trunk_layers=2,
                                        search_head=True, policy_head=True))
    net.eval()
    ckpt = d / "joint.pt"
    save_checkpoint(ckpt, net, metadata={"encoder": local_encoder_identity(2),
                                         "sees_hidden_hands": True})
    pkg = d / "joint.npz"
    export_cwv_numpy(ckpt, pkg)
    return str(pkg), file_sha256(pkg)


def _play_state(seed: int = 625091990):
    rnd = Game(random.Random(seed)).start_round()
    h = HeuristicBot()
    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        c = h.decide_declare(rnd, seat)
        if c:
            rnd.declare(seat, c)
    for seat in range(4):
        c = h.decide_declare(rnd, seat, final=True)
        if c:
            rnd.declare(seat, c)
    rnd.finalize_declare()
    rnd.bury(rnd.banker, h.decide_bury(rnd, rnd.banker))
    assert rnd.phase == "play"
    return rnd


SMALL = dict(worlds=3, candidates=4, cap=400, batch_size=16)


@pytest.fixture
def registered(package):
    path, sha = package
    names = register_pv_search_policies(path, sha256=sha, **SMALL)
    try:
        yield names
    finally:
        for name in names:
            REGISTRY.pop(name, None)


# --------------------------------------------------------------- registry

def test_registered_name_pins_the_recipe_and_builds_the_wrapper(package, registered):
    path, sha = package
    name, = registered
    config = pv.PVSearchConfig(checkpoint_sha256=sha, **SMALL)
    assert name == f"pv-search-{sha[:8]}-w3-k4-r{pv.recipe_digest(config)}"
    bot = make_bot(name, seed=5)
    assert isinstance(bot, pv.PVSearchBot) and bot.policy_name == name
    assert bot.worlds == 3 and bot.candidates == 4 and bot.cap == 400 and bot.batch_size == 16
    assert bot.checkpoint_sha256 == sha and bot.version == 2
    assert bot.evaluator.backend == "numpy"
    assert isinstance(bot.predict, pv.NumpyPriorPredict)
    # the seed is a run parameter: a different seed keeps the name
    assert make_bot(name, seed=6).policy_name == name
    # the recipe digest excludes the seed and moves with any recipe field
    other = pv.PVSearchConfig(checkpoint_sha256=sha, **{**SMALL, "worlds": 4})
    assert pv.recipe_digest(other) != pv.recipe_digest(config)


def test_wrapper_refuses_an_unpinned_or_mismatched_package(package, tmp_path):
    path, sha = package
    with pytest.raises(pv.PVSearchPolicyError, match="SHA256 mismatch"):
        pv.make_pv_search_bot(path, sha256="0" * 64, **SMALL)
    with pytest.raises(pv.PVSearchPolicyError, match="NumPy package"):
        pv.make_pv_search_bot(str(tmp_path / "x.pt"), sha256=sha, **SMALL)
    with pytest.raises(pv.PVSearchPolicyError, match="on disk"):
        pv.pv_registry_entries(path, sha256="1" * 64, **SMALL)


def test_env_recipe_requires_the_full_sha_and_parses_the_knobs(package):
    path, sha = package
    with pytest.raises(pv.PVSearchPolicyError, match="SHENGJI_PV_CKPT"):
        pv.pv_env_recipe({})
    with pytest.raises(pv.PVSearchPolicyError, match="full sha256"):
        pv.pv_env_recipe({"SHENGJI_PV_CKPT": path, "SHENGJI_PV_SHA256": sha[:8]})
    recipe = pv.pv_env_recipe({"SHENGJI_PV_CKPT": path, "SHENGJI_PV_SHA256": sha,
                               "SHENGJI_PV_WORLDS": "64", "SHENGJI_PV_CANDIDATES": "8",
                               "SHENGJI_PV_SERVING_BUDGET_SECONDS": "2.5"})
    assert recipe == dict(checkpoint=path, sha256=sha, worlds=64, candidates=8,
                          serving_budget_seconds=2.5)
    entries = pv.pv_registry_entries(**recipe)
    name, = entries
    assert name.startswith(f"pv-search-{sha[:8]}-w64-k8-r")
    bad = pv.pv_env_recipe({"SHENGJI_PV_CKPT": path, "SHENGJI_PV_SHA256": sha,
                            "SHENGJI_PV_SERVING_BUDGET_SECONDS": "0"})
    with pytest.raises(ValueError, match="finite and positive"):
        pv.pv_registry_entries(**bad)


# ------------------------------------------------- parity with the harness

def test_wrapper_decision_equals_the_screened_harness(package):
    """Same package, seed and state: the production wrapper plays exactly what
    `PolicyValueBot` (the screened design) plays, with the same record shape."""
    from shengji.train.policy_value_search import PolicyValueBot
    path, sha = package
    bot = pv.make_pv_search_bot(path, sha256=sha, seed=17, **SMALL)
    harness = PolicyValueBot.from_checkpoint(path, sha, evaluator=bot.evaluator, seed=17,
                                             worlds=3, candidates=4, cap=400, batch_size=16)
    rnd = _play_state()
    seat = rnd.turn
    ours = bot.decide_play(copy.deepcopy(rnd), seat)
    theirs = harness.decide_play(copy.deepcopy(rnd), seat)
    assert ours == theirs
    a, b = bot.last_decision_record, harness.last_decision_record
    assert a["schema"] == pv.RECORD_SCHEMA and a["work_complete"] is True
    assert a["admitted_indices"] == b["admitted_indices"]
    assert a["selected_index"] == b["selected_index"]
    np.testing.assert_allclose(a["value_means"], b["value_means"])
    assert a["encoder_version"] == 2


# ------------------------------------------------ the server snapshot path

def test_wrapper_survives_server_snapshot_and_commit(package, tmp_path):
    """Release-25 lesson: the server deep-copies the whole bot before any search.
    The wrapper's predictor is a module-level object, so the copy holds a working
    model, the live RNG is untouched, the numpy model-serving branch is taken,
    and the decision commits."""
    path, sha = package
    bot = pv.make_pv_search_bot(path, sha256=sha, seed=23, serving_budget_seconds=30, **SMALL)
    bot.policy_name = "pv-search-test"

    async def scenario():
        rnd = _play_state()
        game = Game(random.Random(7))
        game.round = rnd
        room = srv.Room(code="PVSRCH", game=game, bot=bot,
                        seats=[srv.Seat(str(i), is_bot=True) for i in range(4)],
                        log_dir=tmp_path)
        room.ids = [dict(enumerate(hand)) for hand in rnd.hands]
        room._kitty_given = True
        events = []
        room.log_event = lambda kind, **data: events.append(kind)
        seat = rnd.turn
        before = bot.sampler.rng.getstate()
        direct = pv.make_pv_search_bot(path, sha256=sha, seed=23, serving_budget_seconds=30, **SMALL)
        expected = direct.decide_play(copy.deepcopy(rnd), seat)
        prepared = await srv._paced_bot_step(room, seat, minimum_turn_seconds=0)
        assert prepared is not None and room.bot is bot
        assert bot.sampler.rng.getstate() == before          # live bot never searched
        copied = prepared.decision.snapshot.bot_copy
        assert copied is not bot and copied.sampler is not bot.sampler
        assert isinstance(copied.predict, pv.NumpyPriorPredict) and copied.predict is not bot.predict
        assert copied.last_decision_record["schema"] == pv.RECORD_SCHEMA
        assert list(prepared.decision.cards) == expected
        assert any(kind == "model_search" for kind in events), events
        hand_before = len(rnd.hands[seat])
        assert srv._commit_bot_turn(room, prepared)
        assert len(rnd.hands[seat]) == hand_before - len(expected)   # the cards left the live hand

    asyncio.run(scenario())


# --------------------------------------------------------- the play budget

def test_expired_budget_returns_the_anchor_and_restores_the_sampler(package):
    path, sha = package
    bot = pv.make_pv_search_bot(path, sha256=sha, seed=29, serving_budget_seconds=1e-9, **SMALL)
    rnd = _play_state()
    seat = rnd.turn
    before = bot.sampler.rng.getstate()
    anchor = HeuristicBot().decide_play(copy.deepcopy(rnd), seat)
    played = bot.decide_play(copy.deepcopy(rnd), seat)
    assert played == list(anchor)
    record = bot.last_decision_record
    assert record["schema"] == pv.FALLBACK_SCHEMA and record["reason"] == "budget"
    assert record["work_complete"] is False and record["action"] == list(anchor)
    assert bot.sampler.rng.getstate() == before
    # the same bot with a generous budget completes the search
    bot.serving_budget_seconds = 60.0
    bot.decide_play(copy.deepcopy(rnd), seat)
    assert bot.last_decision_record["schema"] == pv.RECORD_SCHEMA


def test_search_error_falls_back_and_is_labelled(package, monkeypatch):
    path, sha = package
    bot = pv.make_pv_search_bot(path, sha256=sha, seed=31, serving_budget_seconds=60, **SMALL)
    rnd = _play_state()
    seat = rnd.turn
    monkeypatch.setattr(bot, "_value_means", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    anchor = HeuristicBot().decide_play(copy.deepcopy(rnd), seat)
    assert bot.decide_play(copy.deepcopy(rnd), seat) == list(anchor)
    assert bot.last_decision_record["reason"] == "search-error"
    assert bot.last_decision_record["error_class"] == "RuntimeError"
    # without a budget the error is NOT hidden
    strict = pv.make_pv_search_bot(path, sha256=sha, seed=31, **SMALL)
    monkeypatch.setattr(strict, "_value_means", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError, match="boom"):
        strict.decide_play(copy.deepcopy(rnd), seat)
