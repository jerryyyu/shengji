"""Release 48 as served with the native latency switches on: the same decisions.

The served bot is built from ``fly.toml``'s [env] on the hash-pinned production
and release-48 belief packages, with every clock-dependent cut lifted (the
serving budget, the ``lgf`` deadline, the exact lead stage's seconds and the
belief preparation cap) so the host's speed cannot decide.  One seeded round is
played turn by turn through the server's own path: each bury and play turn is
snapshotted by `_snapshot_bot_turn` twice, searched by the plain bot copy and by
the copy with the native switches on (`NATIVE_SWITCHES`), and the plain result
is committed by `_commit_bot_turn`; halfway the committed bot is replaced by a
pickle round trip of itself.  Every turn the two copies play the same cards and
leave the same record (clock fields aside), sampler state and evaluator
counters, and the switched copy carries no finished leaf into the next turn's
snapshot.  The pure engine plays both copies without the exact stages (its
solvers take minutes per endgame unbudgeted).  The switches enter no name.
"""
import asyncio
import copy
import pickle
import random

import pytest

from shengji.ai.heuristic import HeuristicBot
from test_encoder_round_compat import pinned_production_package  # noqa: F401
from test_release48_fly_config import fly_env
from test_release48_fly_config import (RELEASE48, apply_to_process, local_env,  # noqa: F401
                                       pinned_release48_belief_package, served_entries)

#: the native latency switches, by bot attribute
NATIVE_SWITCHES = ("legal_native", "encode_native", "leaf_cache_release", "leaf_clone_fast",
                   "leaf_trick_cache", "world_fast")
CLOCK_SUFFIXES = ("seconds", "_ms")


def _comparable(record):
    if isinstance(record, dict):
        return {k: _comparable(v) for k, v in record.items()
                if not any(k.endswith(s) for s in CLOCK_SUFFIXES)}
    if isinstance(record, list):
        return [_comparable(v) for v in record]
    return record


def _counters(ev):
    return (ev.calls, ev.positions, ev.model_rows, ev.terminal_rows, ev.forward_calls)


def _lift(bot):
    bot.serving_budget_seconds = None
    bot.bury_serving_budget_seconds = None
    bot.leaf_greedy_deadline_ms = 0
    bot.exact_lead_max_seconds = 1e9
    return bot


def _room(bot, seed, log_dir):
    from shengji.api import server as srv
    from shengji.engine.game import Game
    room = srv.Room(code="NATIVE", bot=bot, log_dir=log_dir)
    room.game = Game(random.Random(seed))
    rnd = room.game.start_round()
    helper = HeuristicBot()
    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        card = helper.decide_declare(rnd, seat)
        if card:
            rnd.declare(seat, card)
    for seat in range(4):
        card = helper.decide_declare(rnd, seat, final=True)
        if card:
            rnd.declare(seat, card)
    rnd.finalize_declare()
    room.seats = [srv.Seat(name=f"Bot {seat}", is_bot=True) for seat in range(4)]
    room.ids = [dict(enumerate(hand)) for hand in rnd.hands]
    room._kitty_given = True
    room.log_event = lambda kind, **data: None
    return room


@pytest.mark.parametrize("seed", [1026_301])
def test_the_native_switches_decide_exactly_as_release48_through_the_server_path(
        seed, pinned_production_package, pinned_release48_belief_package,  # noqa: F811
        monkeypatch, tmp_path):
    from shengji.ai import belief_numpy as bn
    from shengji.api import server as srv
    from shengji.engine import legal
    from shengji.train import pv_native
    from shengji.train import pv_search_policy as pv

    if not pv_native.HAVE_NATIVE:
        pytest.skip("train/_pv_fast is not built")
    compiled = legal.validate_follow.__module__ == "shengji.engine._fast"
    monkeypatch.setattr(bn, "PREP_SECONDS", 1e9)
    for key in pv.LATENCY_SWITCH_ENV.values():
        monkeypatch.delenv(key, raising=False)
    env = local_env(pinned_production_package, pinned_release48_belief_package)
    apply_to_process(monkeypatch, env)
    for attr in NATIVE_SWITCHES:
        assert env[pv.LATENCY_SWITCH_ENV[attr]] == "1"
        monkeypatch.delenv(pv.LATENCY_SWITCH_ENV[attr], raising=False)
    _, name, factory = served_entries(pinned_production_package, pinned_release48_belief_package)
    assert name == RELEASE48 == fly_env()["SHENGJI_BOT"]
    bot = _lift(factory(seed=seed))
    if not compiled:
        # the pure engine's exact solvers take minutes per endgame unbudgeted:
        # both copies play without the exact stages there
        bot.exact_lead_endgame = bot.exact_follow = False
    assert not set(NATIVE_SWITCHES) & set(vars(bot))
    room = _room(bot, seed, tmp_path)
    turns = plays = applied = released = 0

    def take(switched):
        snapshot = srv._snapshot_bot_turn(room, seat, "bot")
        if switched:
            for attr in NATIVE_SWITCHES:
                setattr(snapshot.bot_copy, attr, True)
        before = _counters(snapshot.bot_copy.evaluator)
        decision = srv._compute_bot_turn(snapshot)
        searched = snapshot.bot_copy
        record = searched.last_bury_record if phase == "bury" else searched.last_decision_record
        delta = [x - y for x, y in zip(_counters(searched.evaluator), before)]
        return decision, (list(decision.cards), _comparable(record),
                          searched.sampler.rng.getstate(), delta), searched

    rnd = room.round
    while rnd.phase in ("bury", "play"):
        phase = rnd.phase
        seat = rnd.banker if phase == "bury" else rnd.turn
        decision, plain, _ = take(False)
        _, native, searched = take(True)
        assert native == plain, (phase, turns)
        if phase == "play":
            applied += bool(plain[1].get("leaf_greedy_finish_applied"))
            if searched._leaf_greedy is not None:
                assert searched._leaf_greedy["cache"] == {}
                released += 1
        prepared = srv._PreparedBotTurn(decision=decision, compute_seconds=0.0,
                                        pacing_seconds=0.0, turn_seconds=0.0)
        assert srv._commit_bot_turn(room, prepared)
        rnd = room.round
        turns += 1
        if phase == "play":
            plays += 1
            if plays == 40:
                room.bot = pickle.loads(pickle.dumps(room.bot))
    print(f"\nnative switches on release 48: turns={turns} lgf applied={applied}")
    assert turns >= 50 and applied >= 10 and released >= 10


def test_the_native_switches_enter_no_name(pinned_production_package,  # noqa: F811
                                           pinned_release48_belief_package, monkeypatch):
    from shengji.train import pv_search_policy as pv

    flags = {pv.LATENCY_SWITCH_ENV[attr]: "1" for attr in NATIVE_SWITCHES}
    env = local_env(pinned_production_package, pinned_release48_belief_package)
    assert pv.pv_env_recipe({**env, **flags}) == pv.pv_env_recipe(env)
    for key in pv.LATENCY_SWITCH_ENV.values():
        monkeypatch.delenv(key, raising=False)
    apply_to_process(monkeypatch, {**env, **flags})
    entries = pv.pv_registry_entries(**pv.pv_env_recipe(env))
    (name, factory), = entries.items()
    assert name == RELEASE48
    bot = factory(seed=3)
    assert all(vars(bot)[attr] is True for attr in NATIVE_SWITCHES)
    assert copy.deepcopy(bot).legal_native is True


def test_world_fast_keeps_an_instance_completion_override_on_the_served_bot(
        pinned_production_package, pinned_release48_belief_package,  # noqa: F811
        monkeypatch):
    """The served bot's world draw (``_belief_worlds`` -> `world_completion` ->
    `sample_worlds_history_legal`) with ``world_fast`` on: an override set on
    the sampler instance (a bound method, a plain function) is the completion
    that runs, as with the switch off, and the decision is the same."""
    from types import MethodType
    from shengji.ai import belief_numpy as bn
    from shengji.train import pv_search_policy as pv
    from test_pv_search_serving import _play_state

    monkeypatch.setattr(bn, "PREP_SECONDS", 1e9)
    for key in pv.LATENCY_SWITCH_ENV.values():
        monkeypatch.delenv(key, raising=False)
    apply_to_process(monkeypatch, local_env(pinned_production_package,
                                            pinned_release48_belief_package))
    _, _, factory = served_entries(pinned_production_package, pinned_release48_belief_package)
    rnd = _play_state(1026_302)
    seat = rnd.turn
    outcomes = {}
    for fast in (False, True):
        for kind in ("bound", "function"):
            bot = _lift(factory(seed=11))
            bot.world_fast = fast
            calls = []
            reference = bot.sampler._complete_determinized_hands

            def counted(*args, **kwargs):
                calls.append(1)
                return reference(*args, **kwargs)
            if kind == "bound":
                bot.sampler._complete_determinized_hands = MethodType(
                    lambda self, *a, **k: counted(*a, **k), bot.sampler)
            else:
                bot.sampler._complete_determinized_hands = counted
            cards = bot.decide_play(copy.deepcopy(rnd), seat)
            record = bot.last_decision_record
            assert record["belief_fallback"] == 0 and len(calls) >= record["worlds"]
            outcomes[fast, kind] = (cards, _comparable(record), len(calls),
                                    bot.sampler.rng.getstate())
    for kind in ("bound", "function"):
        assert outcomes[True, kind] == outcomes[False, kind]
