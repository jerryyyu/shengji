"""`PVSearchBuryBot`: release 27/28's value-guided bury arms on the policy/value-search
package (Jerry 2026-09-21: "we should use value guided hybrid").

Witnesses: the hybrid pick is IDENTICAL to `CWVBuryBot`'s on the same state, package, seed
and bury config (the bury search is the mixin, unchanged); the record is the shipped
`cwv-bury-policy-v1`; the play RNG is not consumed by a bury; the budget fallback returns
the heuristic incumbent and restores the play sampler's RNG; the registry name binds the
bury identity; the bot survives the server's bury snapshot/commit path.
"""
import asyncio
import copy
import random

import pytest

from shengji.ai.heuristic import HeuristicBot
from shengji.ai.registry import REGISTRY, register_pv_search_policies, make_bot
from shengji.api import server as srv
from shengji.engine.game import Game
from shengji.train import cwv_bury_policy as policy
from shengji.train import pv_search_policy as pv
from shengji.train.cwv_bury_diagnostic import capture_state, reopen_state
from test_pv_search_serving import package  # noqa: F401

SMALL = dict(worlds=3, candidates=4, cap=400, batch_size=16)
BURY = policy.CWVBuryConfig(max_candidates=4, model_worlds=2, selection_worlds=2, alternatives=1)


def _bury_state(index=65):
    rnd = reopen_state(capture_state(index))
    assert rnd.phase == "bury"
    return rnd


def test_hybrid_bury_matches_the_shortlist_wrapper_on_the_same_package(package):
    """Same package (value head), seed and bury config: the pv wrapper's hybrid pick and
    record equal `CWVBuryBot`'s — the bury search is shared code, not a reimplementation."""
    from shengji.ai.cwv_policy import shared_evaluator
    path, sha = package
    ours = pv.make_pv_search_bot(path, sha256=sha, seed=73, bury_arm="hybrid", bury_config=BURY, **SMALL)
    theirs = policy.CWVBuryBot(shared_evaluator(path, threads=1, max_batch=16, encoding="mlp-static"),
                               seed=73, arm="hybrid", bury_config=BURY)
    rnd = _bury_state()
    a = ours.decide_bury(copy.deepcopy(rnd), rnd.banker)
    b = theirs.decide_bury(copy.deepcopy(rnd), rnd.banker)
    assert a == b
    ra, rb = ours.last_bury_record, theirs.last_bury_record
    assert ra["schema"] == rb["schema"] == "cwv-bury-policy-v1" and ra["arm"] == "hybrid"
    assert ra["candidates"] == rb["candidates"] and ra["shortlist"] == rb["shortlist"]
    assert ra["picked_index"] == rb["picked_index"] and ra["model_means"] == rb["model_means"]
    assert ra["mc_evidence"] == rb["mc_evidence"]


def test_bury_does_not_consume_the_play_sampler_and_the_budget_falls_back(package):
    path, sha = package
    bot = pv.make_pv_search_bot(path, sha256=sha, seed=11, bury_arm="hybrid", bury_config=BURY,
                                bury_serving_budget_seconds=60, **SMALL)
    rnd = _bury_state()
    before = bot.sampler.rng.getstate()
    bot.decide_bury(copy.deepcopy(rnd), rnd.banker)
    assert bot.last_bury_record["schema"] == "cwv-bury-policy-v1"
    assert bot.sampler.rng.getstate() == before            # helper bots own the bury streams
    expired = pv.make_pv_search_bot(path, sha256=sha, seed=11, bury_arm="hybrid", bury_config=BURY,
                                    bury_serving_budget_seconds=1e-9, **SMALL)
    incumbent = HeuristicBot().decide_bury(copy.deepcopy(rnd), rnd.banker)
    assert expired.decide_bury(copy.deepcopy(rnd), rnd.banker) == list(incumbent)
    assert expired.last_bury_record["schema"] == "cwv-bury-fallback-v1"
    assert expired.last_bury_record["reason"] == "budget"
    assert expired.sampler.rng.getstate() == before
    # the play budget is a separate knob
    assert expired.serving_budget_seconds is None and expired.bury_serving_budget_seconds == 1e-9


def test_registry_name_binds_the_bury_identity(package):
    path, sha = package
    names = register_pv_search_policies(path, sha256=sha, bury_arm="hybrid", bury_config=BURY,
                                        bury_serving_budget_seconds=2, **SMALL)
    try:
        name, = names
        play = pv.pv_policy_name(sha[:8], pv.PVSearchConfig(checkpoint_sha256=sha, **SMALL))
        assert name.startswith(play + "-bury-hybrid-") and len(name) == len(play) + len("-bury-hybrid-") + 12
        bot = make_bot(name, seed=3)
        assert isinstance(bot, pv.PVSearchBuryBot) and bot.policy_name == name
        assert bot.bury_recipe_identity["play_policy"] == play
        assert bot.bury_recipe_identity["fallback"] == "heuristic-on-error-or-budget"
        plain, = pv.pv_registry_entries(path, sha256=sha, **SMALL)
        assert plain == play                                  # no bury → no suffix
    finally:
        for n in names:
            REGISTRY.pop(n, None)


def test_bury_survives_server_snapshot_and_commit(package, tmp_path):
    path, sha = package
    bot = pv.make_pv_search_bot(path, sha256=sha, seed=29, bury_arm="hybrid", bury_config=BURY,
                                bury_serving_budget_seconds=30, **SMALL)
    bot.policy_name = "pv-search-bury-test"

    async def scenario():
        rnd = _bury_state()
        game = Game(random.Random(7))
        game.round = rnd
        room = srv.Room(code="PVBURY", game=game, bot=bot,
                        seats=[srv.Seat(str(i), is_bot=True) for i in range(4)], log_dir=tmp_path)
        room.ids = [dict(enumerate(hand)) for hand in rnd.hands]
        room._kitty_given = True
        before = bot.sampler.rng.getstate()
        prepared = await srv._paced_bot_step(room, rnd.banker, minimum_turn_seconds=0)
        assert prepared is not None and room.bot is bot and rnd.phase == "bury"
        assert bot.sampler.rng.getstate() == before
        copied = prepared.decision.snapshot.bot_copy
        assert copied is not bot and isinstance(copied, pv.PVSearchBuryBot)
        assert copied.last_bury_record["schema"] == "cwv-bury-policy-v1"
        assert srv._commit_bot_turn(room, prepared)
        assert rnd.phase == "play" and len(rnd.buried) == 8

    asyncio.run(scenario())
