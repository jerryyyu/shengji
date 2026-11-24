"""Rating-graduated bots at a ranked table (``shengji.api.ranked_bots``).

Witnesses: the opposing bots play Beginner when every person at the table
rates at most 800 (a guest counts 800), Standard when every person rates at
most 1000 and not all at most 800, and Advanced otherwise; a person's
partner bot always plays Advanced, so people on both teams meet Advanced
everywhere; the level is chosen when the game starts and at a new game's
first round, never because a rating moved mid-game; a newcomer who takes a
Standard seat makes that team Advanced; a rated round against Standard
opponents uses ``ratings.STANDARD_BOT_RATING`` and one against Beginner
``ratings.BEGINNER_BOT_RATING``, both the same anchor as Advanced, so it is
rated exactly as the same result against Advanced; a missing scorer package
plays the served bot; casual tables are unchanged; no frame differs between
a Beginner, a Standard and an Advanced ranked table.
"""
from __future__ import annotations

import asyncio
import copy
import json
import math

import pytest

from shengji.ai.heuristic import HeuristicBot
from shengji.api import ranked_bots, ratings
from tests.test_accounts import _claims, accounts_on, keypair  # noqa: F401
from tests.test_ratings import Table, _events, _force_outcome, _set, _user, env  # noqa: F401
from tests.test_matchmaking import DEVICE_A, _guest_match, _wait_until, wsenv  # noqa: F401
from tests.test_server_ws import _drain, client  # noqa: F401


class FakeRelaxed:
    """Stands in for the relaxed wrap of ``served``: the heuristic's card
    play, every seat it played for recorded on the class (a deep copy of the
    room's bot shares it)."""
    played: list[int] = []
    policy_name = "fake-relaxed"

    def __init__(self, served):
        self.served = served
        self.last_decision_record = None

    def observe_public(self, rnd):
        observe = getattr(self.served, "observe_public", None)
        if observe is not None:
            observe(rnd)

    def decide_play(self, rnd, seat):
        FakeRelaxed.played.append(seat)
        return HeuristicBot.decide_play(self.served, rnd, seat)


class FakeBeginner(FakeRelaxed):
    """Stands in for the Beginner wrap; its plays are recorded on
    ``FakeBeginner.played`` (a list of its own)."""
    played: list[int] = []
    policy_name = "fake-beginner"

    def decide_play(self, rnd, seat):
        FakeBeginner.played.append(seat)
        return HeuristicBot.decide_play(self.served, rnd, seat)


@pytest.fixture(autouse=True)
def fake_relaxed(monkeypatch):
    from shengji.api import server as srv

    FakeRelaxed.played = []
    FakeBeginner.played = []
    monkeypatch.setattr(srv, "make_relaxed_bot", lambda served, seed: FakeRelaxed(served))
    monkeypatch.setattr(srv, "make_beginner_bot", lambda served, seed: FakeBeginner(served))
    return FakeRelaxed


class S:
    """A seat as ``standard_seats`` reads it."""

    def __init__(self, user_id=None, bot=False):
        self.user_id, self.is_bot = user_id, bot


B = S(bot=True)


def _ratings(table):
    return lambda uid: table[uid]


# ------------------------------------------------------------ the rule
def test_a_solo_player_at_1000_meets_standard_opponents_and_an_advanced_partner():
    seats = [S(1), B, B, B]
    assert ranked_bots.standard_seats(seats, _ratings({1: 1000.0})) == {1, 3}
    assert ranked_bots.standard_seats([B, S(1), B, B], _ratings({1: 1000.0})) == {0, 2}


def test_a_solo_player_above_1000_meets_advanced_opponents():
    assert ranked_bots.standard_seats([S(1), B, B, B], _ratings({1: 1000.01})) == set()
    assert ranked_bots.standard_seats([S(1), B, B, B], _ratings({1: 1001.0})) == set()


def test_a_guest_meets_a_relaxed_level():
    assert ranked_bots.standard_seats([S(None), B, B, B], _ratings({})) == {1, 3}


@pytest.mark.parametrize("a, b, standard", [(1000.0, 1000.0, {1, 3}), (1000.0, 1050.0, set()),
                                            (1050.0, 1000.0, set()), (900.0, 1000.0, {1, 3})])
def test_two_partners_meet_standard_only_when_both_rate_1000_or_less(a, b, standard):
    seats = [S(1), B, S(2), B]
    assert ranked_bots.standard_seats(seats, _ratings({1: a, 2: b})) == standard


def test_a_guest_partnering_an_account_counts_below_its_line():
    assert ranked_bots.standard_seats([S(1), B, S(None), B], _ratings({1: 1000.0})) == {1, 3}
    assert ranked_bots.standard_seats([S(1), B, S(None), B], _ratings({1: 1001.0})) == set()


@pytest.mark.parametrize("a, b", [(1000.0, 1000.0), (800.0, 900.0)])
def test_people_on_both_teams_meet_advanced_everywhere(a, b):
    """Every bot partners someone, and a partner is always Advanced."""
    assert ranked_bots.standard_seats([S(1), S(2), B, B], _ratings({1: a, 2: b})) == set()
    assert ranked_bots.standard_seats([S(1), B, B, S(2)], _ratings({1: a, 2: b})) == set()


@pytest.mark.parametrize("rating, level", [
    (790.0, "beginner"), (800.0, "beginner"), (800.01, "standard"), (801.0, "standard"),
    (900.0, "standard"), (1000.0, "standard"), (1001.0, "advanced")])
def test_a_solo_players_rating_picks_the_opponents_level(rating, level):
    got, seats = ranked_bots.table_level([S(1), B, B, B], _ratings({1: rating}))
    assert got == level
    # the partner (seat 2) is never a relaxed seat
    assert seats == (set() if level == "advanced" else {1, 3})


@pytest.mark.parametrize("a, b, level", [
    (700.0, 900.0, "standard"), (700.0, 800.0, "beginner"), (800.0, 800.0, "beginner"),
    (700.0, 1000.0, "standard"), (700.0, 1001.0, "advanced")])
def test_two_partners_meet_the_level_both_qualify_for(a, b, level):
    got, seats = ranked_bots.table_level([S(1), B, S(2), B], _ratings({1: a, 2: b}))
    assert got == level and seats == (set() if level == "advanced" else {1, 3})


def test_a_guest_counts_800_for_the_level():
    assert ratings.GUEST_RATING == 800.0
    assert ranked_bots.table_level([S(None), B, B, B], _ratings({})) == ("beginner", {1, 3})
    assert ranked_bots.table_level([S(None), B, S(None), B], _ratings({})) == ("beginner", {1, 3})
    assert ranked_bots.table_level([S(1), B, S(None), B], _ratings({1: 700.0})) == ("beginner", {1, 3})
    assert ranked_bots.table_level([S(1), B, S(None), B], _ratings({1: 900.0})) == ("standard", {1, 3})
    assert ranked_bots.table_level([S(1), B, S(None), B], _ratings({1: 1200.0})) == ("advanced", set())


def test_an_unreadable_rating_plays_advanced():
    assert ranked_bots.standard_seats([S(1), B, B, B], _ratings({1: None})) == set()


# --------------------------------------------------------- in the room
def _room(srv, seats, ranked=True, code="GRAD"):
    room = srv.Room(code=code, matched=ranked, bot=HeuristicBot())
    room.bot_seed = 1
    room.seats = [srv.Seat(name=f"Bot {i}", is_bot=True) if s == "bot"
                  else srv.Seat(name=f"P{i}", user_id=s, connected=True)
                  for i, s in enumerate(seats)]
    return room


def test_the_ranked_bot_plays_standard_only_for_the_opposing_seats():
    from shengji.api import server as srv
    from shengji.ai import env as play_env
    from shengji.engine.game import Game
    import random

    room = _room(srv, [7, "bot", "bot", "bot"])
    served = room.bot
    ranked_bots.choose(room, srv.make_relaxed_bot, _ratings({7: 1000.0}))
    assert isinstance(room.bot, ranked_bots.RankedBots) and room.bot.served is served
    assert room.bot_level == "advanced" and ranked_bots.standard(room) == {1, 3}
    game = Game(random.Random(4))
    rnd = play_env.prepare_round(game, [HeuristicBot()] * 4)
    while rnd.phase == "play":
        seat = rnd.turn
        rnd.play(seat, copy.deepcopy(room.bot).decide_play(rnd, seat))
    assert FakeRelaxed.played and set(FakeRelaxed.played) == {1, 3}
    # one decision per trick for each opposing seat, none for the partner
    assert FakeRelaxed.played.count(1) == FakeRelaxed.played.count(3) == len(rnd.history)


def test_the_ranked_bot_plays_through_the_server_snapshot_path(tmp_path):
    """``_paced_bot_step`` / ``_commit_bot_turn`` with Standard opponents:
    the opposing seats' cards come from the relaxed bot, the partner's from
    the served one, and the committed copy keeps the room's seat levels."""
    import random

    from shengji.ai import env as play_env
    from shengji.api import server as srv
    from shengji.engine.game import Game

    async def scenario():
        game = Game(random.Random(11))
        play_env.prepare_round(game, [HeuristicBot()] * 4)
        rnd = game.round
        room = srv.Room(code="SNAP", game=game, log_dir=tmp_path, bot=HeuristicBot(), matched=True,
                        seats=[srv.Seat(str(s), is_bot=True) for s in range(4)])
        room.seats[0].is_bot = False
        room.seats[0].connected = True
        room.bot_seed = 2
        ranked_bots.choose(room, srv.make_relaxed_bot, _ratings({}))
        assert ranked_bots.standard(room) == {1, 3}
        room.seats[0].is_bot = True               # the bot plays the person's seat here too
        room.ids = [dict(enumerate(hand)) for hand in rnd.hands]
        room._kitty_given = True
        acted = []
        for _ in range(8):
            seat = rnd.turn
            prepared = await srv._paced_bot_step(room, seat, minimum_turn_seconds=0)
            assert prepared is not None and srv._commit_bot_turn(room, prepared)
            acted.append(seat)
            assert isinstance(room.bot, ranked_bots.RankedBots)
            assert room.bot.levels is room.bot_levels
        return acted

    acted = asyncio.run(scenario())
    assert sorted(set(acted)) == [0, 1, 2, 3]
    assert FakeRelaxed.played == [s for s in acted if s in (1, 3)]


def test_an_advanced_table_keeps_the_served_bot_itself():
    from shengji.api import server as srv

    room = _room(srv, [7, "bot", "bot", "bot"])
    served = room.bot
    ranked_bots.choose(room, srv.make_relaxed_bot, _ratings({7: 1001.0}))
    assert room.bot is served and ranked_bots.standard(room) == frozenset()


@pytest.mark.parametrize("rating, level, fake", [
    (790.0, "beginner", FakeBeginner), (800.0, "beginner", FakeBeginner),
    (801.0, "standard", FakeRelaxed)])
def test_the_ranked_bot_plays_its_level_only_for_the_opposing_seats(rating, level, fake):
    from shengji.api import server as srv
    from shengji.ai import env as play_env
    from shengji.engine.game import Game
    import random

    room = _room(srv, [7, "bot", "bot", "bot"])
    served = room.bot
    ranked_bots.choose(room, srv.make_relaxed_bot, _ratings({7: rating}), srv.make_beginner_bot)
    assert isinstance(room.bot, ranked_bots.RankedBots) and room.bot.served is served
    assert type(room.bot.relaxed) is fake and room.bot.level == level
    assert [ranked_bots.level_of(room, s) for s in range(4)] == ["advanced", level, "advanced", level]
    game = Game(random.Random(4))
    rnd = play_env.prepare_round(game, [HeuristicBot()] * 4)
    while rnd.phase == "play":
        seat = rnd.turn
        bot = copy.deepcopy(room.bot)
        rnd.play(seat, bot.decide_play(rnd, seat))
        assert ranked_bots.played_level(bot) == (level if seat in (1, 3) else "advanced")
    assert set(fake.played) == {1, 3}
    other = FakeRelaxed if fake is FakeBeginner else FakeBeginner
    assert other.played == []


def test_a_new_game_at_another_level_rebuilds_the_relaxed_bot():
    from shengji.api import server as srv

    room = _room(srv, [7, "bot", "bot", "bot"])
    ranked_bots.choose(room, srv.make_relaxed_bot, _ratings({7: 790.0}), srv.make_beginner_bot)
    assert type(room.bot.relaxed) is FakeBeginner
    ranked_bots.choose(room, srv.make_relaxed_bot, _ratings({7: 850.0}), srv.make_beginner_bot)
    assert type(room.bot.relaxed) is FakeRelaxed and ranked_bots.level_of(room, 1) == "standard"


def test_without_a_beginner_builder_a_beginner_table_plays_standard():
    from shengji.api import server as srv

    room = _room(srv, [7, "bot", "bot", "bot"])
    ranked_bots.choose(room, srv.make_relaxed_bot, _ratings({7: 700.0}))
    assert type(room.bot.relaxed) is FakeRelaxed and ranked_bots.level_of(room, 1) == "standard"


def test_beginner_bots_are_rated_at_the_advanced_anchor():
    assert ratings.BEGINNER_BOT_RATING == ratings.BOT_RATING == 1000.0
    assert ratings.RELAXED_BOT_RATINGS == {"standard": 1000.0, "beginner": 1000.0}


def test_a_round_against_beginner_starts_with_the_beginner_anchor():
    from shengji.api import server as srv
    from shengji.engine.game import Game

    room = _room(srv, [7, "bot", "bot", "bot"])
    room.game = Game(start_level="2", games_to_win=None)
    room.game.start_round()
    room.index_round()
    ranked_bots.choose(room, srv.make_relaxed_bot, _ratings({7: 700.0}), srv.make_beginner_bot)
    room.ratings = ratings.RoomRatings(game_id="g")
    ratings.round_started(room)
    assert room.ratings.anchors == [ratings.BOT_RATING, ratings.BEGINNER_BOT_RATING,
                                    ratings.BOT_RATING, ratings.BEGINNER_BOT_RATING]


def test_a_missing_beginner_package_plays_the_served_bot_with_the_warning(monkeypatch, tmp_path, caplog):
    import logging

    from shengji.api import server as srv
    from shengji.train import relaxed_play

    monkeypatch.undo()          # the real builders
    monkeypatch.setattr(srv, "RELAXED_SF_PACKAGE", str(tmp_path / "missing.npz"))
    served = HeuristicBot()
    with caplog.at_level(logging.WARNING, logger=srv.__name__):
        assert srv.make_beginner_bot(served, 3) is served
    assert any("beginner bots unavailable" in r.getMessage() for r in caplog.records)
    room = _room(srv, [7, "bot", "bot", "bot"])
    room.bot = served
    ranked_bots.choose(room, srv.make_relaxed_bot, _ratings({7: 700.0}), srv.make_beginner_bot)
    assert room.bot is served and ranked_bots.standard(room) == frozenset()
    assert ranked_bots.level_of(room, 1) == "advanced"
    assert relaxed_play.BEGINNER_TAU == 3.0 and relaxed_play.BEGINNER_DELTA == 8.0


def test_the_beginner_bot_names_its_level():
    from shengji.api import server as srv
    from shengji.train import relaxed_play

    assert srv.BEGINNER_BOT == relaxed_play.casual_suffix(
        srv.RELAXED_SF_SHA256, relaxed_play.BEGINNER_TAU, relaxed_play.BEGINNER_DELTA)
    assert srv.BEGINNER_BOT != srv.RELAXED_BOT


def test_a_missing_standard_package_plays_and_rates_advanced():
    from shengji.api import server as srv

    room = _room(srv, [7, "bot", "bot", "bot"])
    served = room.bot
    ranked_bots.choose(room, lambda bot, seed: bot, _ratings({7: 900.0}))
    assert room.bot is served and ranked_bots.standard(room) == frozenset()


def test_a_casual_table_is_unchanged():
    from shengji.api import server as srv

    room = _room(srv, [7, "bot", "bot", "bot"], ranked=False)
    served = room.bot
    ranked_bots.choose(room, srv.make_relaxed_bot, _ratings({7: 900.0}))
    assert room.bot is served and room.bot_levels is None and room.bot_level == "advanced"
    casual = srv.Room(code="CASU", bot=HeuristicBot(), bot_level="standard")
    ranked_bots.choose(casual, srv.make_relaxed_bot, _ratings({}))
    assert casual.bot_levels is None and casual.bot_level == "standard"


def test_a_ranked_room_still_refuses_a_bots_setting(tmp_path):
    from shengji.api import server as srv

    with pytest.raises(ValueError):
        srv.Room(code="DDDD", log_dir=tmp_path, matched=True, bot_level="standard")


# ------------------------------------------------------------ invisible
def _frames(srv, room):
    out = {"room": srv.room_json(room, 0), "table": srv.room_table_frame(room, 0)}
    for s in range(4):
        out[f"state{s}"] = srv.state_for(room, s)
    return json.dumps(out, sort_keys=True, default=str)


def test_no_frame_differs_between_a_beginner_a_standard_and_an_advanced_ranked_table():
    from shengji.api import server as srv
    from shengji.engine.game import Game

    game = Game(start_level="2", games_to_win=None)
    game.start_round()
    frames = []
    for rating, level in ((700.0, "beginner"), (1000.0, "standard"), (1200.0, "advanced")):
        room = _room(srv, [7, "bot", 8, "bot"], code="SAME")
        room.game = copy.deepcopy(game)
        room.index_round()
        ranked_bots.choose(room, srv.make_relaxed_bot, _ratings({7: rating, 8: rating}),
                           srv.make_beginner_bot)
        frames.append(_frames(srv, room))
        assert ranked_bots.level_of(room, 1) == level
    assert frames[0] == frames[1] == frames[2]
    assert "standard" not in frames[0] and "beginner" not in frames[0]


# -------------------------------------------------- when it is chosen
def test_the_queue_game_of_a_1000_account_meets_standard_and_logs_it(env, monkeypatch):  # noqa: F811
    from tests.test_ratings import _ranked_solo

    srv, store, client = env
    srv.MATCHMAKER.reset()
    try:
        uid, headers = _user(store, "fresh", "Fresh")
        with client.websocket_connect("/ws", headers=headers) as a:
            code, _ = _ranked_solo(srv, a)
            room = srv.rooms[code]
            _settled(room)
            assert ranked_bots.standard(room) == {1, 3}
            assert room.bot_level == "advanced"
            assert room.ratings.anchors == [ratings.BOT_RATING, ratings.STANDARD_BOT_RATING,
                                            ratings.BOT_RATING, ratings.STANDARD_BOT_RATING]
        records = [json.loads(line) for line in (srv.LOG_DIR / f"{code}.jsonl").open()]
        chosen = next(r for r in records if r["e"] == "bot_levels")
        assert chosen["level"] == "standard" and chosen["standard_seats"] == [1, 3]
        uid2, headers2 = _user(store, "strong", "Strong")
        _set(store, uid2, 1001.0)
        with client.websocket_connect("/ws", headers=headers2) as b:
            code2, _ = _ranked_solo(srv, b)
            _settled(srv.rooms[code2])
            assert ranked_bots.standard(srv.rooms[code2]) == frozenset()
        records = [json.loads(line) for line in (srv.LOG_DIR / f"{code2}.jsonl").open()]
        chosen = next(r for r in records if r["e"] == "bot_levels")
        assert chosen["level"] == "advanced" and chosen["standard_seats"] == []
    finally:
        srv.MATCHMAKER.reset()


def test_the_queue_game_of_a_new_account_meets_beginner_and_logs_it(env):  # noqa: F811
    from shengji.api import accounts
    from tests.test_ratings import _ranked_solo

    srv, store, client = env
    srv.MATCHMAKER.reset()
    try:
        assert accounts.START_RATING <= ranked_bots.BEGINNER_UP_TO
        uid, headers = _user(store, "fresh", "Fresh", rating=accounts.START_RATING)
        with client.websocket_connect("/ws", headers=headers) as a:
            code, _ = _ranked_solo(srv, a)
            room = srv.rooms[code]
            _settled(room)
            assert ranked_bots.standard(room) == {1, 3}
            assert [ranked_bots.level_of(room, s) for s in range(4)] == [
                "advanced", "beginner", "advanced", "beginner"]
            assert type(room.bot.relaxed) is FakeBeginner
            assert room.bot_level == "advanced"
            assert room.ratings.anchors == [ratings.BOT_RATING, ratings.BEGINNER_BOT_RATING,
                                            ratings.BOT_RATING, ratings.BEGINNER_BOT_RATING]
            assert room.ratings.anchors[1] == 1000.0
        records = [json.loads(line) for line in (srv.LOG_DIR / f"{code}.jsonl").open()]
        chosen = next(r for r in records if r["e"] == "bot_levels")
        assert chosen["level"] == "beginner" and chosen["standard_seats"] == [1, 3]
        # the record names seats and the level only, no account
        assert set(chosen) <= {"e", "t", "room", "round", "level", "standard_seats"}
    finally:
        srv.MATCHMAKER.reset()


def test_a_guest_in_the_ranked_queue_meets_beginner(env):  # noqa: F811
    srv, store, client = env
    srv.MATCHMAKER.reset()
    try:
        with client.websocket_connect("/ws?device=" + "G" * 22) as g:
            g.send_json({"type": "queue_join", "name": "Guesty"})
            _drain(g, "queue_state")
            g.send_json({"type": "table_start_bots"})
            started = _drain(g, "match_started")
            room = srv.rooms[started["room"]]
            assert room.matched and room.seats[0].user_id is None
            _settled(room)
            assert ranked_bots.standard(room) == {1, 3}
            assert ranked_bots.level_of(room, 1) == "beginner"
            assert room.ratings.anchors == [ratings.GUEST_RATING, ratings.BEGINNER_BOT_RATING,
                                            ratings.BOT_RATING, ratings.BEGINNER_BOT_RATING]
    finally:
        srv.MATCHMAKER.reset()


def _settled(room, timeout=10.0):
    """Wait (the server's loop runs in the test client's thread) until the
    game's level has been read."""
    _wait_until(lambda: room.bot_levels is not None and _quiet(room), timeout)


def _quiet(room):
    levels = room.bot_levels
    return not getattr(levels, "pending_game", False) and not getattr(levels, "checks", 0)


def _bot_levels_records(srv, room):
    path = srv.LOG_DIR / f"{room.code}.jsonl"
    return [r for r in map(json.loads, path.open()) if r["e"] == "bot_levels"]


async def _advance_and_settle(srv, room):
    room.ready = {s for s, sd in enumerate(room.seats) if not sd.is_bot}
    async with room.lock:
        assert await srv.advance_if_all_ready(room)
    for _ in range(1000):
        if _quiet(room):
            break
        await asyncio.sleep(0.01)
    room.deal_task.cancel()
    try:
        await room.deal_task
    except BaseException:   # noqa: BLE001 - the cancelled deal
        pass


def _play_out(srv, room, level_idx=None):
    """Deal the round in play and play it out with the room's bots."""
    if level_idx is not None:
        room.game.level_idx = level_idx
    rnd = room.round
    while rnd.phase == "deal":
        seat, idx, card = rnd.deal_next()
        room.ids[seat][idx] = card
    rnd.finalize_declare()
    if rnd.banker is None:
        rnd.banker = 0
    while rnd.phase in ("bury", "play"):
        assert srv.bot_step(room, rnd.banker if rnd.phase == "bury" else rnd.turn)
    return room.game.result


def test_a_new_game_reads_the_ratings_after_the_last_round_is_settled(env, monkeypatch):  # noqa: F811
    """The round that scores the point is written late; the next game's
    level and anchors still come from the rating after that write."""
    import threading
    from shengji.engine.game import A_INDEX

    srv, store, _ = env
    uid, _ = _user(store, "settle")
    _force_outcome(monkeypatch, 30)               # the bankers (team 0) go up 2
    table = Table(srv, [uid, "bot", "bot", "bot"], code="SETL")
    room = table.room
    release = threading.Event()
    real = ratings.apply_round

    def late(store_, rec, now=None):
        release.wait(5)
        return real(store_, rec, now)
    monkeypatch.setattr(ratings, "apply_round", late)

    async def scenario():
        room.game.start_round()
        room.index_round()
        room.saved_game = None
        ranked_bots.choose(room, srv.make_relaxed_bot, _ratings({uid: 1000.0}))
        ratings.start(room)
        assert ranked_bots.standard(room) == {1, 3}     # 1000 at the start
        result = _play_out(srv, room, [A_INDEX, A_INDEX])
        assert result.point_scored and result.winner_team == 0
        asyncio.get_running_loop().call_later(0.2, release.set)   # the write lands later
        await _advance_and_settle(srv, room)
    asyncio.run(scenario())
    ratings.flush()
    assert store.user(uid)["rating"] > 1000
    assert ranked_bots.standard(room) == frozenset()
    assert not isinstance(room.bot, ranked_bots.RankedBots)
    assert room.ratings.anchors == [ratings.BOT_RATING] * 4
    assert [r["level"] for r in _bot_levels_records(srv, room)] == ["advanced"]


def test_the_level_is_fixed_for_the_game(env, monkeypatch):  # noqa: F811
    srv, store, _ = env
    uid, _ = _user(store, "mover")
    _force_outcome(monkeypatch, 30)
    table = Table(srv, [uid, "bot", "bot", "bot"], code="FIXD")
    room = table.room

    async def scenario():
        room.game.start_round()
        room.index_round()
        room.saved_game = None
        ranked_bots.choose(room, srv.make_relaxed_bot, _ratings({uid: 1000.0}))
        ratings.start(room)
        assert ranked_bots.standard(room) == {1, 3}
        result = _play_out(srv, room)
        assert not result.point_scored
        await asyncio.wrap_future(ratings._EXECUTOR.submit(lambda: None))
        _set(store, uid, 1300.0)                  # the rating moved mid-game
        await _advance_and_settle(srv, room)
    asyncio.run(scenario())
    assert ranked_bots.standard(room) == {1, 3}
    assert room.ratings.anchors[1] == ratings.STANDARD_BOT_RATING


def test_a_1200_partner_joining_a_998_host_through_the_queue_promotes(wsenv, monkeypatch):  # noqa: F811
    srv, store, client, clock = wsenv
    monkeypatch.setattr(srv, "BOT_DELAY", 0.0)
    host, host_headers = _user(store, "host", "Host")
    joiner, joiner_headers = _user(store, "joiner", "Joiner")
    _set(store, host, 998.0)
    _set(store, joiner, 1200.0)
    with client.websocket_connect("/ws", headers=host_headers) as h, \
            client.websocket_connect("/ws", headers=joiner_headers) as a:
        h.send_json({"type": "queue_join"})
        _drain(h, "queue_state")
        h.send_json({"type": "table_start_bots"})
        code = _drain(h, "match_started")["room"]
        room = srv.rooms[code]
        _settled(room)
        assert ranked_bots.standard(room) == {1, 3}
        room.seats[0].away = True                 # the bot plays the host's seat too
        client.portal.call(srv.kick_bots, room)
        _wait_until(lambda: room.round is not None and room.round.phase == "play")
        clock.advance(60)                         # past the rating window
        a.send_json({"type": "queue_join"})
        offer = _drain(a, "queue_state")["offer"]
        assert offer["room"] == code and offer["pick"] == 2
        a.send_json({"type": "open_table_join", "room": code, "seat": 2})
        assert _drain(a, "match_started")["joining"] is True
        _wait_until(lambda: room.seats[2].user_id == joiner)
        _settled(room)
        assert ranked_bots.standard(room) == frozenset()
        assert ranked_bots.level_of(room, 1) == ranked_bots.level_of(room, 3) == "advanced"


def test_a_guest_seat_resumed_as_a_1200_account_promotes(wsenv, monkeypatch):  # noqa: F811
    srv, store, client, clock = wsenv
    monkeypatch.setattr(srv, "BOT_DELAY", 0.0)
    code, token = _guest_match(client)
    room = srv.rooms[code]
    _settled(room)
    assert ranked_bots.standard(room) == {1, 3}
    uid, headers = _user(store, "signer", "Acct Person")
    _set(store, uid, 1200.0)
    with client.websocket_connect(f"/ws?device={DEVICE_A}", headers=headers) as a:
        a.send_json({"type": "table_join", "expect": "room", "code": code, "token": token})
        _drain(a, "state")
        assert room.seats[0].user_id == uid
        _settled(room)
        assert ranked_bots.standard(room) == frozenset()


def test_a_reconnect_by_the_same_account_keeps_standard(env, monkeypatch):  # noqa: F811
    from shengji.api import server as srv

    room = _room(srv, [7, "bot", "bot", "bot"])
    ranked_bots.choose(room, srv.make_relaxed_bot, _ratings({7: 1000.0}))
    ranked_bots.seat_changed(room, 0, 7)
    assert ranked_bots.standard(room) == {1, 3} and _quiet(room)


@pytest.mark.parametrize("acting, taken", [(1, 3), (3, 1)])
def test_a_handover_between_search_and_commit_replays_the_turn_at_advanced(tmp_path, acting, taken):
    """A Standard search finished, then a guest took the other Standard seat:
    the acting seat is the guest's Advanced partner now, so the Standard card
    is discarded and the next committed card is the served bot's."""
    import random

    from shengji.ai import env as play_env
    from shengji.api import server as srv
    from shengji.engine.game import Game

    async def scenario():
        game = Game(random.Random(11))
        play_env.prepare_round(game, [HeuristicBot()] * 4)
        rnd = game.round
        room = srv.Room(code="HAND", game=game, log_dir=tmp_path, bot=HeuristicBot(), matched=True,
                        seats=[srv.Seat(str(s), is_bot=True) for s in range(4)])
        room.seats[0].is_bot, room.seats[0].connected = False, True
        ranked_bots.choose(room, srv.make_relaxed_bot, _ratings({}))
        room.seats[0].is_bot = True
        room.ids = [dict(enumerate(hand)) for hand in rnd.hands]
        room._kitty_given = True
        while rnd.turn != acting:
            prepared = await srv._paced_bot_step(room, rnd.turn, minimum_turn_seconds=0)
            assert srv._commit_bot_turn(room, prepared)
        FakeRelaxed.played = []
        prepared = await srv._paced_bot_step(room, acting, minimum_turn_seconds=0)
        assert FakeRelaxed.played == [acting]
        guest = room.seats[taken]
        guest.is_bot, guest.name, guest.connected = False, "Guest", True
        if hasattr(ranked_bots, "seat_changed"):
            ranked_bots.seat_changed(room, taken)
        else:
            ranked_bots.seat_taken(room, taken)
        assert ranked_bots.standard(room) == frozenset()
        guest.is_bot = True                       # its bot plays on for the test
        assert not srv._commit_bot_turn(room, prepared)
        assert rnd.turn == acting
        again = await srv._paced_bot_step(room, acting, minimum_turn_seconds=0)
        assert srv._commit_bot_turn(room, again)
        assert FakeRelaxed.played == [acting]     # the committed card was not Standard's
    asyncio.run(scenario())


def test_a_newcomer_on_the_standard_team_makes_it_advanced():
    from shengji.api import server as srv

    room = _room(srv, [7, "bot", "bot", "bot"])
    ranked_bots.choose(room, srv.make_relaxed_bot, _ratings({7: 1000.0}))
    ranked_bots.seat_taken(room, 2)               # the partner's seat: no change
    assert ranked_bots.standard(room) == {1, 3}
    ranked_bots.seat_taken(room, 1)
    assert ranked_bots.standard(room) == frozenset()
    # every copy of the room's bot reads the change
    copied = copy.deepcopy(room.bot)
    assert copied.levels is room.bot.levels and not copied.levels.standard


def test_a_guest_joining_a_relaxed_team_keeps_its_level():
    from shengji.api import server as srv

    room = _room(srv, [7, "bot", "bot", "bot"])
    ranked_bots.choose(room, srv.make_relaxed_bot, _ratings({7: 700.0}), srv.make_beginner_bot)
    room.seats[2] = srv.Seat(name="Guest", connected=True)   # a guest takes the partner's seat
    ranked_bots.seat_changed(room, 2, None)
    assert ranked_bots.standard(room) == {1, 3}      # a guest counts 800
    room = _room(srv, [7, "bot", "bot", "bot"])
    ranked_bots.choose(room, srv.make_relaxed_bot, _ratings({7: 900.0}), srv.make_beginner_bot)
    room.seats[2] = srv.Seat(name="Guest", connected=True)
    ranked_bots.seat_changed(room, 2, None)
    assert ranked_bots.standard(room) == {1, 3}


@pytest.mark.parametrize("rating, kept", [(800.0, True), (900.0, False)])
def test_an_account_joining_a_beginner_team_is_checked_against_800(monkeypatch, rating, kept):
    from shengji.api import server as srv

    async def read(user_ids):
        return {uid: (rating, 5) for uid in user_ids}

    monkeypatch.setattr(ranked_bots, "_ordered_read", read)

    async def scenario():
        room = _room(srv, [7, "bot", "bot", "bot"])
        ranked_bots.choose(room, srv.make_relaxed_bot, _ratings({7: 700.0}), srv.make_beginner_bot)
        room.seats[2] = srv.Seat(name="P9", user_id=9, connected=True)
        ranked_bots.seat_changed(room, 2, None)
        assert ranked_bots.level_of(room, 1) == "advanced"     # while it is read
        while room.bot_levels.checks:
            await asyncio.sleep(0)
        return room

    room = asyncio.run(scenario())
    assert ranked_bots.level_of(room, 1) == ("beginner" if kept else "advanced")


# ------------------------------------------------------------- rating
def test_standard_bots_are_rated_at_the_advanced_anchor():
    assert ratings.STANDARD_BOT_RATING == ratings.BOT_RATING


@pytest.mark.parametrize("attacker_points, won", [(30, True), (200, False)])
def test_a_round_against_standard_is_rated_as_the_same_round_against_advanced(
        env, monkeypatch, attacker_points, won):  # noqa: F811
    """The same result moves the rating by the same amount against Standard."""
    srv, store, _ = env
    a, _ = _user(store, "vsstd")
    b, _ = _user(store, "vsadv")
    _force_outcome(monkeypatch, attacker_points)   # the human's team banks
    std = Table(srv, [a, "bot", "bot", "bot"], code="STD1")
    ranked_bots.choose(std.room, srv.make_relaxed_bot, _ratings({a: 1000.0}))
    assert ranked_bots.standard(std.room) == {1, 3}
    std.play_round(banker=0)
    adv = Table(srv, [b, "bot", "bot", "bot"], code="ADV1")
    adv.play_round(banker=0)
    e_std, = _events(store, "SELECT * FROM rating_events WHERE user_id = ?", a)
    e_adv, = _events(store, "SELECT * FROM rating_events WHERE user_id = ?", b)
    assert e_adv["expected"] == pytest.approx(0.557312, abs=1e-6)
    assert e_std["expected"] == pytest.approx(e_adv["expected"])
    assert e_std["actual"] == e_adv["actual"] and bool(e_std["won"]) is won
    assert e_std["delta"] == pytest.approx(e_adv["delta"])


def test_the_partner_counts_the_advanced_anchor_beside_standard_opponents():
    rec_anchors = [ratings.BOT_RATING, ratings.STANDARD_BOT_RATING,
                   ratings.BOT_RATING, ratings.STANDARD_BOT_RATING]
    strengths = ratings.team_strengths(rec_anchors, banker_team=0)
    assert strengths == (ratings.BOT_RATING + ratings.BANKER_ADVANTAGE_PRESET,
                         ratings.STANDARD_BOT_RATING)


# ------------------------------------------- an account signs in at the deal
@pytest.mark.parametrize("rating, standard", [(998.0, {1, 3}), (1000.0, {1, 3}), (1001.0, set())])
def test_a_guest_who_signs_in_during_the_opening_deal_is_read_as_the_account(
        wsenv, monkeypatch, rating, standard):  # noqa: F811
    """The guest's seat changes account while the game's level is pending:
    the level is read for the account now seated, on both sides of 1000."""
    srv, store, client, clock = wsenv
    monkeypatch.setattr(srv, "DEAL_DELAY", 0.03)          # an opening deal of ~3 s
    code, token = _guest_match(client)
    room = srv.rooms[code]
    assert room.bot_levels.pending_game and room.round.phase == "deal"
    uid, headers = _user(store, "signer", "Acct Person")
    _set(store, uid, rating)
    with client.websocket_connect(f"/ws?device={DEVICE_A}", headers=headers) as a:
        a.send_json({"type": "table_join", "expect": "room", "code": code, "token": token})
        _drain(a, "state")
        assert room.seats[0].user_id == uid
        assert room.bot_levels.pending_game              # still the opening deal
        _settled(room)
        assert ranked_bots.standard(room) == standard
        anchor = ratings.STANDARD_BOT_RATING if standard else ratings.BOT_RATING
        assert room.ratings.anchors == [ratings.BOT_RATING, anchor, ratings.BOT_RATING, anchor]


def test_a_seat_that_changes_during_the_settling_read_is_read_again(env, monkeypatch):  # noqa: F811
    from shengji.api import server as srv

    _, store, _ = env
    low, _ = _user(store, "low")
    high, _ = _user(store, "high")
    _set(store, low, 990.0)
    _set(store, high, 1200.0)
    table = Table(srv, [None, "bot", "bot", "bot"], code="RETR")
    room = table.room
    reads = []
    real = ranked_bots._ordered_read

    def read(uids):
        reads.append(list(uids))
        if len(reads) == 1:
            room.seats[0].user_id = high          # the seat changed hands during the read
        return real(uids)
    monkeypatch.setattr(ranked_bots, "_ordered_read", read)

    async def scenario():
        room.game.start_round()
        room.index_round()
        room.saved_game = None
        ranked_bots.begin_game(room)
        ratings.start(room)
        room.seats[0].user_id = low               # signed in after the round's read
        await ranked_bots.settle_game(room, srv.make_relaxed_bot)
    asyncio.run(scenario())
    assert reads == [[low], [high]]
    assert ranked_bots.standard(room) == frozenset()


# ------------------------------------------ the policy the search played
@pytest.mark.parametrize("partner_rating, commits", [(1000.0, True), (1200.0, False)])
def test_a_search_plays_the_level_of_its_snapshot_through_a_pending_check(
        env, tmp_path, partner_rating, commits):  # noqa: F811
    """Seat 3 snapshots at Standard; a partner joins and its rating read is
    pending while the search runs; the read ends before the commit. The
    search played Standard (its snapshot's level), so it commits only when
    the seat is Standard again, and the committed card's level is the live one."""
    import random

    from shengji.ai import env as play_env
    from shengji.api import server as srv
    from shengji.engine.game import Game

    _, store, _ = env
    partner, _ = _user(store, "partner")
    _set(store, partner, partner_rating)

    async def scenario():
        game = Game(random.Random(11))
        play_env.prepare_round(game, [HeuristicBot()] * 4)
        rnd = game.round
        room = srv.Room(code="PINS", game=game, log_dir=tmp_path, bot=HeuristicBot(), matched=True,
                        seats=[srv.Seat(str(s), is_bot=True) for s in range(4)])
        room.seats[0].is_bot, room.seats[0].connected = False, True
        ranked_bots.choose(room, srv.make_relaxed_bot, _ratings({}))
        room.seats[0].is_bot = True
        room.ids = [dict(enumerate(hand)) for hand in rnd.hands]
        room._kitty_given = True
        while rnd.turn != 3:
            prepared = await srv._paced_bot_step(room, rnd.turn, minimum_turn_seconds=0)
            assert srv._commit_bot_turn(room, prepared)
        FakeRelaxed.played = []
        snapshot = srv._snapshot_bot_turn(room, 3, "bot")
        assert snapshot.level == "standard"
        joiner = room.seats[2]
        joiner.is_bot, joiner.user_id, joiner.connected = False, partner, True
        ranked_bots.seat_changed(room, 2, None)
        assert room.bot_levels.checks == 1 and ranked_bots.level_of(room, 3) == "advanced"
        decision = srv._compute_bot_turn(snapshot)        # while the read is pending
        await asyncio.gather(*list(ranked_bots._TASKS))
        live = ranked_bots.level_of(room, 3)
        assert live == ("standard" if commits else "advanced")
        joiner.is_bot = True                              # its bot plays on for the test
        played = list(FakeRelaxed.played)
        acted = srv._commit_bot_turn(room, srv._PreparedBotTurn(decision, 0.0, 0.0, 0.0))
        assert acted is commits
        if not acted:
            again = await srv._paced_bot_step(room, 3, minimum_turn_seconds=0)
            assert srv._commit_bot_turn(room, again)
            decision = again.decision
        assert played == [3] and decision.level == live
        assert room.bot._pinned is None
        assert FakeRelaxed.played == [3]                  # a re-search played Advanced
    asyncio.run(scenario())
