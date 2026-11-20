"""Relaxed bots: a casual room's switch that seats ``server.RELAXED_BOT`` in place of the served bot.

Witnesses: a relaxed room builds RELAXED_BOT with its own seed and a default room the served name;
a matched (ranked) room refuses the switch, in the room and at ``start_matched_room``; every
``round_start`` names the policy that plays the bot seats and whether it is relaxed; the relaxed
bot plays through the server's snapshot path (``_paced_bot_step`` / ``_commit_bot_turn``), and a
seeded relaxed bot repeats its decisions; the production mistake dashboard leaves relaxed rounds
out of the bot-versus-human tallies.
"""
import asyncio
import json
import random
import time

import pytest

from shengji.ai import env as play_env
from shengji.ai.registry import REGISTRY, make_bot
from shengji.api import server
from shengji.engine.game import Game


def test_relaxed_bot_is_a_registered_policy_distinct_from_the_served_one():
    assert server.RELAXED_BOT == "mc-s0-report-lcb"
    assert server.RELAXED_BOT in REGISTRY
    bot = make_bot(server.RELAXED_BOT, seed=3)
    assert bot.policy_name == server.RELAXED_BOT
    assert bot.REPORT_RULE == "lcb" and bot.N_DETERMINIZATIONS == 30


def test_a_relaxed_room_builds_the_relaxed_bot_and_a_default_room_the_served_one(monkeypatch, tmp_path):
    calls = []

    def fake_make_bot(name, **kw):
        calls.append((name, kw))
        return server.HeuristicBot()
    monkeypatch.setattr(server, "make_bot", fake_make_bot)
    monkeypatch.setenv("SHENGJI_BOT", "heuristic")
    server.Room(code="AAAA", log_dir=tmp_path, bot_seed=5)
    server.Room(code="BBBB", log_dir=tmp_path, bot_seed=6, relaxed_bots=True)
    server.Room(code="CCCC", log_dir=tmp_path, bot_seed=7, matched=True)
    assert calls == [("heuristic", {"seed": 5}), (server.RELAXED_BOT, {"seed": 6}),
                     ("heuristic", {"seed": 7})]


def test_a_ranked_room_refuses_relaxed_bots(tmp_path):
    with pytest.raises(ValueError):
        server.Room(code="DDDD", log_dir=tmp_path, matched=True, relaxed_bots=True)
    with pytest.raises(ValueError):
        asyncio.run(server.start_matched_room(None, [], {}, mode="ranked", relaxed_bots=True))


def _round_start(room, tmp_path):
    room.game = Game(random.Random(3))
    room.game.start_round()
    room.seats = [server.Seat(str(s), is_bot=True) for s in range(4)]
    server._log_round_start(room)
    records = [json.loads(line) for line in (tmp_path / f"{room.code}.jsonl").open()]
    start, = [r for r in records if r["e"] == "round_start"]
    return start


def test_round_start_names_the_bot_policy_and_the_relaxed_switch(monkeypatch, tmp_path):
    monkeypatch.setenv("SHENGJI_BOT", "mc")
    served = _round_start(server.Room(code="EEEE", log_dir=tmp_path, bot_seed=1), tmp_path)
    relaxed = _round_start(server.Room(code="FFFF", log_dir=tmp_path, bot_seed=1,
                                       relaxed_bots=True), tmp_path)
    assert served["bot_policy"] == "mc" and served["relaxed_bots"] is False
    assert relaxed["bot_policy"] == server.RELAXED_BOT and relaxed["relaxed_bots"] is True
    assert relaxed["ranked"] is False


def test_the_room_table_frame_carries_the_setting(tmp_path):
    room = server.Room(code="GGGG", log_dir=tmp_path, bot=server.HeuristicBot(), relaxed_bots=True)
    room.seats = [server.Seat(str(s), is_bot=True) for s in range(4)]
    assert server.room_table_frame(room, 0)["settings"]["relaxed_bots"] is True


def _play_state(seed):
    """A round in its play phase, dealt, declared and buried by the relaxed bot."""
    game = Game(random.Random(seed))
    bot = make_bot(server.RELAXED_BOT, seed=seed)
    play_env.prepare_round(game, [bot] * 4)
    return game


def test_the_relaxed_bot_plays_through_the_server_path_and_repeats_its_decisions(tmp_path):
    async def scenario():
        game = _play_state(11)
        rnd = game.round
        room = server.Room(code="HHHH", game=game, log_dir=tmp_path, bot_seed=21, relaxed_bots=True,
                           seats=[server.Seat(str(s), is_bot=True) for s in range(4)])
        assert room.bot.policy_name == server.RELAXED_BOT
        room.ids = [dict(enumerate(hand)) for hand in rnd.hands]
        room._kitty_given = True
        played = []
        started = time.perf_counter()
        for _ in range(8):                  # two tricks: leads and follows
            seat = rnd.turn
            before = len(rnd.hands[seat])
            prepared = await server._paced_bot_step(room, seat, minimum_turn_seconds=0)
            assert prepared is not None
            assert prepared.decision.snapshot.bot_copy.policy_name == server.RELAXED_BOT
            cards = list(prepared.decision.cards)
            assert server._commit_bot_turn(room, prepared)
            server._log_bot_timing(room, prepared, acted=True)
            assert len(rnd.hands[seat]) < before
            played.append((seat, sorted(cards)))
        return played, time.perf_counter() - started

    first, seconds = asyncio.run(scenario())
    second, _ = asyncio.run(scenario())
    assert first == second
    # latency smoke: the measured mean is ~0.2 s a play on the compiled engine
    assert seconds / len(first) < 10.0
    records = [json.loads(line) for line in (tmp_path / "HHHH.jsonl").open()]
    timing = [r for r in records if r["e"] == "bot_timing"]
    assert timing and {r["policy"] for r in timing} == {server.RELAXED_BOT}


def test_the_mistake_dashboard_excludes_relaxed_rounds(tmp_path):
    from scripts import mistake_dashboard as md
    src = md.__file__.replace("scripts/mistake_dashboard.py", "tests/fixtures/mistake_dashboard/prod_rounds.jsonl")
    lines = [json.loads(line) for line in open(src)]
    base, _ = md.load_prod([src])
    assert base
    for rec in lines:
        if rec.get("e") == "round_start":
            rec["relaxed_bots"] = True
    relaxed = tmp_path / "relaxed.jsonl"
    relaxed.write_text("".join(json.dumps(r) + "\n" for r in lines))
    rounds, notes = md.load_prod([str(relaxed)])
    assert rounds == [] and notes["rounds excluded: relaxed bots"] >= len(base)
