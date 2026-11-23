"""Rating-graduated bots at a ranked table (``shengji.api.ranked_bots``).

Witnesses: the opposing bots play Standard when every person at the table
rates at most 1000 (a guest counts 1000) and Advanced otherwise; a person's
partner bot always plays Advanced, so people on both teams meet Advanced
everywhere; the level is chosen when the game starts and at a new game's
first round, never because a rating moved mid-game; a newcomer who takes a
Standard seat makes that team Advanced; a rated round against Standard
opponents uses ``ratings.STANDARD_BOT_RATING`` and gains less than the same
result against Advanced; casual tables are unchanged; no frame differs
between a Standard and an Advanced ranked table.
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


@pytest.fixture(autouse=True)
def fake_relaxed(monkeypatch):
    from shengji.api import server as srv

    FakeRelaxed.played = []
    monkeypatch.setattr(srv, "make_relaxed_bot", lambda served, seed: FakeRelaxed(served))
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


def test_a_guest_meets_standard():
    assert ranked_bots.standard_seats([S(None), B, B, B], _ratings({})) == {1, 3}


@pytest.mark.parametrize("a, b, standard", [(1000.0, 1000.0, {1, 3}), (1000.0, 1050.0, set()),
                                            (1050.0, 1000.0, set()), (900.0, 1000.0, {1, 3})])
def test_two_partners_meet_standard_only_when_both_rate_1000_or_less(a, b, standard):
    seats = [S(1), B, S(2), B]
    assert ranked_bots.standard_seats(seats, _ratings({1: a, 2: b})) == standard


def test_a_guest_partnering_an_account_counts_1000():
    assert ranked_bots.standard_seats([S(1), B, S(None), B], _ratings({1: 1000.0})) == {1, 3}
    assert ranked_bots.standard_seats([S(1), B, S(None), B], _ratings({1: 1001.0})) == set()


@pytest.mark.parametrize("a, b", [(1000.0, 1000.0), (800.0, 900.0)])
def test_people_on_both_teams_meet_advanced_everywhere(a, b):
    """Every bot partners someone, and a partner is always Advanced."""
    assert ranked_bots.standard_seats([S(1), S(2), B, B], _ratings({1: a, 2: b})) == set()
    assert ranked_bots.standard_seats([S(1), B, B, S(2)], _ratings({1: a, 2: b})) == set()


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


def test_no_frame_differs_between_a_standard_and_an_advanced_ranked_table():
    from shengji.api import server as srv
    from shengji.engine.game import Game

    game = Game(start_level="2", games_to_win=None)
    game.start_round()
    frames = []
    for rating in (1000.0, 1200.0):
        room = _room(srv, [7, "bot", 8, "bot"], code="SAME")
        room.game = copy.deepcopy(game)
        room.index_round()
        ranked_bots.choose(room, srv.make_relaxed_bot, _ratings({7: rating, 8: rating}))
        frames.append(_frames(srv, room))
        assert bool(ranked_bots.standard(room)) is (rating == 1000.0)
    assert frames[0] == frames[1]
    assert "standard" not in frames[0]


# -------------------------------------------------- when it is chosen
def test_the_queue_game_of_a_new_account_meets_standard_and_logs_it(env, monkeypatch):  # noqa: F811
    from tests.test_ratings import _ranked_solo

    srv, store, client = env
    srv.MATCHMAKER.reset()
    try:
        uid, headers = _user(store, "fresh", "Fresh")
        with client.websocket_connect("/ws", headers=headers) as a:
            code, _ = _ranked_solo(srv, a)
            room = srv.rooms[code]
            assert ranked_bots.standard(room) == {1, 3}
            assert room.bot_level == "advanced"
            assert room.ratings.anchors == [ratings.GUEST_RATING, ratings.STANDARD_BOT_RATING,
                                            ratings.GUEST_RATING, ratings.STANDARD_BOT_RATING]
        records = [json.loads(line) for line in (srv.LOG_DIR / f"{code}.jsonl").open()]
        start = next(r for r in records if r["e"] == "round_start")
        assert start["bot_level"] == "standard" and start["standard_seats"] == [1, 3]
        assert start["bot_policy"] == "fake-relaxed" and start["ranked"] is True
        uid2, headers2 = _user(store, "strong", "Strong")
        _set(store, uid2, 1001.0)
        with client.websocket_connect("/ws", headers=headers2) as b:
            code2, _ = _ranked_solo(srv, b)
            assert ranked_bots.standard(srv.rooms[code2]) == frozenset()
        records = [json.loads(line) for line in (srv.LOG_DIR / f"{code2}.jsonl").open()]
        start = next(r for r in records if r["e"] == "round_start")
        assert start["bot_level"] == "advanced" and "standard_seats" not in start
    finally:
        srv.MATCHMAKER.reset()


def test_a_guest_in_the_ranked_queue_meets_standard(env):  # noqa: F811
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
            assert ranked_bots.standard(room) == {1, 3}
    finally:
        srv.MATCHMAKER.reset()


def _next_round(srv, room):
    async def go():
        room.ready = {s for s, sd in enumerate(room.seats) if not sd.is_bot}
        assert await srv.advance_if_all_ready(room)
        room.deal_task.cancel()
        try:
            await room.deal_task
        except BaseException:   # noqa: BLE001 - the cancelled deal
            pass
    asyncio.run(go())


def test_the_level_is_fixed_for_the_game_and_chosen_again_at_a_new_game(env, monkeypatch):  # noqa: F811
    from shengji.engine.game import A_INDEX

    srv, store, _ = env
    uid, _ = _user(store, "mover")
    _force_outcome(monkeypatch, 30)               # the bankers (team 0) go up 2
    table = Table(srv, [uid, "bot", "bot", "bot"])
    room = table.room
    ranked_bots.choose(room, srv.make_relaxed_bot)
    assert ranked_bots.standard(room) == {1, 3}
    table.play_round(banker=0)
    assert store.user(uid)["rating"] > 1000       # the rating moved mid-game
    _set(store, uid, 1300.0)
    _next_round(srv, room)                        # same game: no re-choice
    assert ranked_bots.standard(room) == {1, 3}
    assert room.ratings.anchors[1] == ratings.STANDARD_BOT_RATING
    room.game.level_idx = [A_INDEX, A_INDEX]      # this round wins the game
    while room.round.phase == "deal":
        seat, idx, card = room.round.deal_next()
        room.ids[seat][idx] = card
    room.round.finalize_declare()
    room.round.banker = room.round.banker if room.round.banker is not None else 0
    table.finish()
    assert room.game.result.point_scored
    _next_round(srv, room)                        # a new game: chosen again, at 1300
    assert ranked_bots.standard(room) == frozenset()
    assert not isinstance(room.bot, ranked_bots.RankedBots)
    assert room.ratings.anchors == [ratings.GUEST_RATING] * 4


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


# ------------------------------------------------------------- rating
def test_standard_anchor_is_the_measured_offset():
    assert ratings.STANDARD_BOT_RATING == ratings.BOT_RATING - 59.0
    # S142's R54 team scored 0.5815 a round against Standard: about 57 Elo
    # by the plain logit, 58.8 with the banker advantage in the expectation
    plain = 400 * math.log10(0.5815 / (1 - 0.5815))
    assert 55 < plain < 59


@pytest.mark.parametrize("attacker_points, won", [(30, True), (200, False)])
def test_a_round_against_standard_is_rated_at_its_anchor_and_gains_less(
        env, monkeypatch, attacker_points, won):  # noqa: F811
    """The same result gains less (or loses more) against Standard."""
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
    team, opp = 1000.0 + ratings.BANKER_ADVANTAGE_PRESET, ratings.STANDARD_BOT_RATING
    assert e_std["expected"] == pytest.approx(ratings.expected_score(team, opp))
    assert e_std["expected"] > e_adv["expected"]
    assert e_std["actual"] == e_adv["actual"] and bool(e_std["won"]) is won
    assert e_std["delta"] < e_adv["delta"]
    if won:
        assert 0 < e_std["delta"]
    else:
        assert e_adv["delta"] < 0


def test_the_partner_counts_the_advanced_anchor_beside_standard_opponents():
    rec_anchors = [ratings.GUEST_RATING, ratings.STANDARD_BOT_RATING,
                   ratings.GUEST_RATING, ratings.STANDARD_BOT_RATING]
    strengths = ratings.team_strengths(rec_anchors, banker_team=0)
    assert strengths == (ratings.BOT_RATING + ratings.BANKER_ADVANTAGE_PRESET,
                         ratings.STANDARD_BOT_RATING)
