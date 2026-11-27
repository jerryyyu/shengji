"""Watching a table (``/api/watch``): one round behind, never a round in play.

Rounds are played in-process through the server's own logging functions
(``_log_round_start``, ``bot_step``, which logs ``round_end`` through
``_finish_round``) with the heuristic bot on every seat, so the feed reads the
real record format from the real room log.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from tests.test_server_ws import client  # noqa: F401

FORBIDDEN = ("decision", "model_search", "bot_timing", "declare_decision", "bot_seed",
             "bot_policy", "chat", "secret-reasoning", "never-served-text", "user_id",
             "queue_id", "203.0.113.9")


class Table:
    """A registered room; seat 0 is a connected person, the rest bots."""

    def __init__(self, srv, code="WTCH", ranked=False, allow_joiners=True):
        from shengji.engine.game import Game

        self.srv = srv
        room = srv.Room(code=code)
        room.seats = [srv.Seat(name="Mei", user_id=41, connected=True)] + [
            srv.Seat(name=f"Bot {i}", is_bot=True) for i in range(1, 4)]
        room.matched = ranked
        room.allow_joiners = allow_joiners
        room.origin_ip = "203.0.113.9"
        bot = room.bot
        original = bot.decide_play

        def decide_play(rnd, seat):
            cards = original(rnd, seat)
            bot.last_decision_record = {"played": list(cards), "why": "secret-reasoning"}
            return cards

        bot.decide_play = decide_play
        room.game = Game(start_level="2", games_to_win=None)
        srv.rooms[code] = room
        self.room = room

    def deal(self):
        srv, room = self.srv, self.room
        room.game.start_round()
        room.index_round()
        srv._log_round_start(room)
        rnd = room.round
        while rnd.phase == "deal":
            seat, idx, code = rnd.deal_next()
            room.ids[seat][idx] = code

    def declare(self):
        srv, room = self.srv, self.room
        rnd = room.round
        rnd.finalize_declare()
        room.log_event("trump", suit=rnd.trump_suit or "NT", rank=rnd.trump_rank,
                       banker=rnd.banker, declared=rnd.declaration is not None)
        room.log_event("declare_decision", seat=0, record={"why": "secret-reasoning"}, bot=True)
        room.log_event("chat", seat=0, text="never-served-text", bot=False)

    def act(self, plays=None):
        srv, room = self.srv, self.room
        n = 0
        while room.round.phase in ("bury", "play") and (plays is None or n < plays):
            seat = room.round.banker if room.round.phase == "bury" else room.round.turn
            assert srv.bot_step(room, seat)
            room.log_event("model_search", seat=seat, mode="bot", why="secret-reasoning")
            room.log_event("bot_timing", seat=seat, phase="play", compute_seconds=0.1)
            n += 1

    def play_round(self):
        self.deal()
        self.declare()
        self.act()
        assert self.room.round.phase == "round_end"


@pytest.fixture()
def feed(client, monkeypatch):
    from shengji.api import server as srv, spectate

    monkeypatch.setenv(spectate.ENV, "1")
    monkeypatch.setattr(spectate, "_reruns", spectate.collections.deque(maxlen=spectate.KEEP_ROUNDS))
    monkeypatch.setattr(spectate, "_loaded", True)
    monkeypatch.setattr(spectate, "_DOCS", spectate.collections.OrderedDict())
    spectate.LIMITER.reset()
    return srv, spectate, client


def _watch(client, **params):
    return client.get("/api/watch", params=params)


def _deck_cards(doc):
    start = next(e for e in doc["events"] if e["e"] == "round_start")
    return start["deck"]


def test_the_feed_is_off_without_the_flag(client, monkeypatch):
    from shengji.api import server as srv, spectate

    monkeypatch.delenv(spectate.ENV, raising=False)
    t = Table(srv)
    t.play_round()
    t.deal()
    assert _watch(client).status_code == 404
    assert client.get(f"/api/watch/{t.room.watch.id}").status_code == 404
    assert spectate.presence() is None
    assert "watch" not in srv.MATCHMAKER.presence_payload()


def test_no_round_in_play_is_ever_served_at_any_phase(feed):
    srv, spectate, client = feed
    t = Table(srv)
    # the first round, at every phase: nothing has finished, so nothing to watch
    t.deal()
    assert _watch(client).status_code == 404
    t.declare()
    assert _watch(client).status_code == 404
    t.act(plays=1)                       # the bury
    assert _watch(client).status_code == 404
    t.act(plays=30)
    assert _watch(client).status_code == 404
    t.act()
    first = _watch(client)
    assert first.status_code == 200
    doc = first.json()
    assert doc["round"] == 1 and doc["waiting"] is False and doc["finished"] is True
    assert doc["events"][-1]["e"] == "round_end"
    assert all(c is not None for c in _deck_cards(doc))
    tid, token = doc["table"], doc["watcher"]

    # the second round, at every phase: round 1 is served, round 2 never is
    live_decks = []
    t.deal()
    live_decks.append(list(t.room.round.deck))
    for step in (t.declare, lambda: t.act(plays=1), lambda: t.act(plays=40)):
        again = _watch(client, w=token).json()
        assert again["round"] == 1
        assert _deck_cards(again) != list(t.room.round.deck)
        follow = client.get(f"/api/watch/{tid}", params={"after": 1, "w": token}).json()
        assert follow["waiting"] is True and "events" not in follow
        assert follow["live_round"] == 2
        step()
    t.act()
    done = client.get(f"/api/watch/{tid}", params={"after": 1, "w": token}).json()
    assert done["waiting"] is False and done["round"] == 2
    assert _deck_cards(done) == live_decks[0]


def test_a_round_without_its_end_record_is_refused_by_the_reader(feed):
    srv, spectate, _client = feed
    t = Table(srv)
    t.play_round()
    t.deal()
    t.declare()
    t.act(plays=20)
    # point the feed at the round in play, as a bug in the hooks would
    st = t.room.watch
    n, path, offset, _accounts = st.started
    live = spectate.Finished(path=path, start=offset, round=n, ranked=False)
    assert spectate.round_doc(live) is None
    assert spectate._is_over(t.room, n) is False
    assert spectate._is_over(t.room, n - 1) is True


def test_a_replaced_deal_serves_only_the_deal_that_finished(feed):
    srv, spectate, client = feed
    t = Table(srv)
    t.deal()
    replaced_at = t.room.watch.started[2]
    srv._log_round_start(t.room)          # the same round's deal logged again
    assert t.room.watch.started[2] > replaced_at
    t.declare()
    t.act()
    doc = _watch(client).json()
    assert doc["round"] == 1
    assert [e["e"] for e in doc["events"]].count("round_start") == 1
    assert _deck_cards(doc) == list(t.room.round.deck)


def test_a_record_that_missed_the_disk_leaves_the_round_unserved(feed, monkeypatch):
    srv, spectate, client = feed
    t = Table(srv)
    real = srv.Room.log_event

    def failing(self, kind, **data):
        return None if kind == "round_end" else real(self, kind, **data)

    monkeypatch.setattr(srv.Room, "log_event", failing)
    t.play_round()
    assert t.room.watch.last is None
    assert _watch(client).status_code == 404


def test_the_feed_carries_no_pii_and_no_hidden_log_fields(feed):
    srv, spectate, client = feed
    t = Table(srv, ranked=True)
    t.play_round()
    t.deal()
    doc = _watch(client).json()
    blob = json.dumps(doc)
    for word in FORBIDDEN:
        assert word not in blob
    assert "WTCH" not in blob                 # a ranked table never names its code
    assert doc["code"] is None
    start = next(e for e in doc["events"] if e["e"] == "round_start")
    assert all(set(p) == {"seat", "name", "is_bot"} for p in start["players"])
    assert doc["players"] == ["Mei", "Bot 1", "Bot 2", "Bot 3"]
    assert {e["e"] for e in doc["events"]} <= set(spectate.saved_games.PUBLIC_KEYS)
    assert all("room" not in e for e in doc["events"])


def test_a_casual_table_that_seats_joiners_names_its_code_for_take_a_seat(feed):
    srv, spectate, client = feed
    t = Table(srv, code="CSUL")
    t.play_round()
    t.deal()
    doc = _watch(client).json()
    assert doc["mode"] == "casual" and doc["code"] == "CSUL"


def test_watchable_tables_are_ranked_or_casual_with_joiners_and_someone_there(feed):
    srv, spectate, client = feed
    private = Table(srv, code="PRIV", allow_joiners=False)
    private.play_round()
    assert not spectate.watchable(private.room)
    assert _watch(client).status_code == 404
    ranked = Table(srv, code="RNKD", ranked=True, allow_joiners=False)
    ranked.play_round()
    assert spectate.watchable(ranked.room)
    ranked.room.seats[0].connected = False
    assert not spectate.watchable(ranked.room)
    assert spectate.presence() == {"watch": 0, "rerun": True}
    ranked.room.seats[0].connected = True
    assert spectate.presence() == {"watch": 1, "rerun": True}
    payload = srv.MATCHMAKER.presence_payload()
    assert payload["watch"] == 1 and payload["rerun"] is True


def test_picking_prefers_the_asked_mode_then_the_table_furthest_in_and_skips(feed):
    srv, spectate, client = feed
    casual = Table(srv, code="CAS1")
    casual.play_round()
    casual.deal()
    early = Table(srv, code="RNK1", ranked=True)
    early.play_round()
    early.deal()
    late = Table(srv, code="RNK2", ranked=True)
    late.play_round()
    late.play_round()
    late.deal()
    assert _watch(client, mode="ranked").json()["table"] == late.room.watch.id
    assert _watch(client, mode="casual").json()["table"] == casual.room.watch.id
    nxt = _watch(client, mode="ranked", skip=late.room.watch.id).json()
    assert nxt["table"] == early.room.watch.id


def test_every_watcher_up_to_the_cap_gets_the_live_table(feed, monkeypatch):
    srv, spectate, client = feed
    monkeypatch.setattr(spectate.LIMITER, "limit", 1000)
    t = Table(srv, ranked=True)
    t.play_round()
    t.deal()
    assert spectate.WATCH_CAP == 50
    docs = [_watch(client).json() for _ in range(spectate.WATCH_CAP)]
    # the 9th to the 50th as much as the first: this table, not a replay
    assert all(d["table"] == t.room.watch.id and d["rerun"] is False and d["round"] == 1
               for d in docs)
    tokens = [d["watcher"] for d in docs]
    assert len(set(tokens)) == spectate.WATCH_CAP
    assert t.room.watch.live_watchers(spectate.time.time()) == spectate.WATCH_CAP
    # one past the cap gets the rerun (this table's own round, from the log), not a place here
    over = _watch(client).json()
    assert over["rerun"] is True and over["table"] == spectate.RERUN_ID
    assert client.get(f"/api/watch/{t.room.watch.id}").status_code == 404
    # a watcher already counted keeps its place
    mine = client.get(f"/api/watch/{t.room.watch.id}", params={"w": tokens[0], "after": 1})
    assert mine.status_code == 200 and mine.json()["waiting"] is True
    # a watcher who stops polling frees its place
    for tok in tokens:
        t.room.watch.watchers[tok] -= spectate.WATCH_TTL + 1
    assert _watch(client).json()["table"] == t.room.watch.id


def test_reruns_play_the_latest_finished_ranked_round_after_its_table_closes(feed):
    srv, spectate, client = feed
    t = Table(srv, code="GONE", ranked=True)
    t.play_round()
    srv.rooms.pop("GONE")
    doc = _watch(client).json()
    assert doc["rerun"] is True and doc["round"] == 1 and doc["live_round"] is None
    assert doc["events"][-1]["e"] == "round_end"


def test_the_feed_is_rate_limited_per_address(feed):
    srv, spectate, client = feed
    t = Table(srv, ranked=True)
    t.play_round()
    for _ in range(spectate.LIMITER.limit):
        assert _watch(client).status_code == 200
    assert _watch(client).status_code == 429


# ------------------------------------------------------- the account allowlist
from tests.test_accounts import _claims, accounts_on, keypair  # noqa: E402,F401


def _account(store, sub):
    user = store.upsert_user(_claims(sub=sub, email=f"{sub}@example.com"))
    return user["id"], {"cookie": f"sj_session={store.create_session(user['id'])}"}


@pytest.fixture()
def listed(accounts_on, client, monkeypatch):
    from shengji.api import server as srv, spectate

    monkeypatch.delenv(spectate.ENV, raising=False)
    monkeypatch.setattr(spectate, "_reruns", spectate.collections.deque(maxlen=spectate.KEEP_ROUNDS))
    spectate.LIMITER.reset()
    store = accounts_on.STORE
    jerry, jerry_h = _account(store, "jerry")
    other, other_h = _account(store, "other")
    monkeypatch.setenv(spectate.ACCOUNTS_ENV, f" {jerry} ,not-an-id")
    return srv, spectate, client, (jerry, jerry_h), (other, other_h)


def test_an_allowlisted_account_watches_while_the_flag_is_off(listed):
    srv, spectate, client, (jerry, jerry_h), _other = listed
    t = Table(srv, ranked=True)
    t.play_round()
    t.deal()
    doc = client.get("/api/watch", headers=jerry_h)
    assert doc.status_code == 200 and doc.json()["round"] == 1
    tid = doc.json()["table"]
    assert client.get(f"/api/watch/{tid}", params={"after": 1}, headers=jerry_h).json()["waiting"]


def test_another_account_and_a_guest_are_refused_by_the_endpoints(listed):
    srv, spectate, client, _jerry, (_other, other_h) = listed
    t = Table(srv, ranked=True)
    t.play_round()
    t.deal()
    tid = t.room.watch.id
    for headers in (other_h, {}, {"cookie": "sj_session=forged"}):
        assert client.get("/api/watch", headers=headers).status_code == 404
        assert client.get(f"/api/watch/{tid}", headers=headers).status_code == 404
    assert t.room.watch.watchers == {}


def test_only_the_allowlisted_account_hears_the_watch_keys(listed):
    srv, spectate, client, (jerry, _h), (other, _o) = listed
    t = Table(srv, ranked=True)
    t.play_round()
    assert spectate.presence(jerry) == {"watch": 1, "rerun": True}
    assert spectate.presence(other) is None
    assert spectate.presence(None) is None
    assert srv.MATCHMAKER.presence_payload(jerry)["watch"] == 1
    for uid in (other, None):
        assert "watch" not in srv.MATCHMAKER.presence_payload(uid)
        assert "rerun" not in srv.MATCHMAKER.presence_payload(uid)


def test_an_allowlisted_account_may_watch_any_live_table(listed):
    srv, spectate, client, (jerry, jerry_h), _other = listed
    t = Table(srv, code="PRIV", allow_joiners=False)
    t.play_round()
    t.deal()
    assert spectate.presence(jerry) == {"watch": 1, "rerun": False}
    doc = client.get("/api/watch", headers=jerry_h).json()
    assert doc["table"] == t.room.watch.id and doc["code"] is None
    assert "PRIV" not in json.dumps(doc)


def test_with_no_flag_and_no_list_the_presence_line_is_unchanged(client, monkeypatch):
    from shengji.api import server as srv, spectate

    monkeypatch.delenv(spectate.ENV, raising=False)
    monkeypatch.delenv(spectate.ACCOUNTS_ENV, raising=False)
    t = Table(srv, ranked=True)
    t.play_round()
    assert spectate.presence_key() == ()
    assert spectate.presence(41) is None
    assert "watch" not in srv.MATCHMAKER.presence_payload(41)


# ------------------------------------------------------- after the read
def _during_read(monkeypatch, spectate, change):
    """Run ``change`` while the feed reads the log, as another request could.
    Only a read can be raced, so the built rounds are forgotten first."""
    spectate._DOCS.clear()
    real = spectate.round_doc

    def reading(f, listed=None):
        doc = real(f, listed)
        change()
        return doc

    monkeypatch.setattr(spectate, "round_doc", reading)


def test_allow_joiners_switched_off_during_the_read_serves_nothing(feed, monkeypatch):
    srv, spectate, client = feed
    t = Table(srv, code="CSUL")
    t.play_round()
    t.deal()
    token = _watch(client).json()["watcher"]
    _during_read(monkeypatch, spectate, lambda: setattr(t.room, "allow_joiners", False))
    assert _watch(client, w=token).status_code == 404
    t.room.allow_joiners = True
    spectate._DOCS.clear()
    tid = t.room.watch.id
    assert client.get(f"/api/watch/{tid}", params={"w": token}).status_code == 404


def test_a_room_replaced_during_the_read_serves_nothing(feed, monkeypatch):
    srv, spectate, client = feed
    t = Table(srv, code="CSUL")
    t.play_round()
    t.deal()

    def replace():
        srv.rooms["CSUL"] = srv.Room(code="CSUL")

    _during_read(monkeypatch, spectate, replace)
    assert _watch(client).status_code == 404


def test_the_last_seat_filling_during_the_read_drops_the_join_code(feed, monkeypatch):
    srv, spectate, client = feed
    t = Table(srv, code="CSUL")
    t.play_round()
    t.deal()

    def fill():
        for sd in t.room.seats:
            sd.is_bot, sd.connected = False, True

    _during_read(monkeypatch, spectate, fill)
    doc = _watch(client).json()
    assert doc["round"] == 1 and doc["code"] is None


def _drop_a_play(path, round_no):
    """Delete one interior play of ``round_no`` from the log, as a lost write would."""
    lines = path.read_bytes().splitlines(keepends=True)
    plays = [i for i, line in enumerate(lines)
             if json.loads(line).get("round") == round_no and json.loads(line).get("e") == "play"]
    del lines[plays[len(plays) // 2]]
    path.write_bytes(b"".join(lines))


def _lose_a_play(monkeypatch, srv, round_no, nth=20):
    """The ``nth`` play record of ``round_no`` misses the disk, as a lost write would."""
    real, seen = srv.Room.log_event, []

    def losing(self, kind, **data):
        if kind == "play" and self.game is not None and self.game.round_no == round_no:
            seen.append(kind)
            if len(seen) == nth:
                return None
        return real(self, kind, **data)

    monkeypatch.setattr(srv.Room, "log_event", losing)


def test_a_round_missing_an_interior_play_is_refused_and_the_last_good_round_kept(feed, monkeypatch):
    srv, spectate, client = feed
    t = Table(srv, ranked=True)
    t.play_round()
    first = _watch(client).json()
    assert first["round"] == 1
    _lose_a_play(monkeypatch, srv, 2)
    t.play_round()
    t.deal()
    broken = t.room.watch.last
    assert broken.round == 2 and spectate.round_doc(broken) is None
    again = _watch(client, w=first["watcher"]).json()
    assert again["round"] == 1 and again["waiting"] is False
    follow = client.get(f"/api/watch/{first['table']}", params={"after": 1, "w": first["watcher"]}).json()
    assert follow["waiting"] is True and "events" not in follow


def test_a_complete_round_passes_the_sequence_check(feed):
    srv, spectate, client = feed
    t = Table(srv)
    t.play_round()
    records = spectate._read(t.room.watch.last)
    assert spectate.complete_sequence(records) is True
    plays = [r for r in records if r["e"] == "play"]
    assert sum(len(p["cards"]) for p in plays) == 100


def test_a_closed_tables_rerun_keeps_its_last_whole_round(feed):
    srv, spectate, client = feed
    t = Table(srv, code="RRUN", ranked=True)
    t.play_round()
    assert _watch(client).json()["round"] == 1
    t.play_round()
    _drop_a_play(spectate._log_path(t.room), 2)
    srv.rooms.pop("RRUN")                   # the table closes; only the rerun is left
    doc = _watch(client).json()
    assert doc["rerun"] is True and doc["round"] == 1
    assert doc["events"][-1]["e"] == "round_end"
    assert [f.round for f in spectate._reruns] == [1]     # the broken round was dropped
    assert spectate.presence() == {"watch": 0, "rerun": True}


def test_a_rerun_names_its_players_by_seat_and_a_live_table_by_name(feed):
    srv, spectate, client = feed
    t = Table(srv, code="NAME", ranked=True)
    t.play_round()
    t.deal()
    live = _watch(client).json()
    assert live["rerun"] is False and live["players"] == ["Mei", "Bot 1", "Bot 2", "Bot 3"]
    srv.rooms.pop("NAME")
    rerun = _watch(client).json()
    assert rerun["rerun"] is True
    # Mei is not on the leaderboard: "Player 1"; the bots keep their names
    assert rerun["players"] == ["Player 1", "Bot 1", "Bot 2", "Bot 3"]
    start = next(e for e in rerun["events"] if e["e"] == "round_start")
    assert [p["name"] for p in start["players"]] == ["Player 1", "Bot 1", "Bot 2", "Bot 3"]
    assert "Mei" not in json.dumps(rerun)


def test_a_rerun_after_a_late_join_carries_no_players_name_anywhere(feed):
    srv, spectate, client = feed
    t = Table(srv, code="LATE", ranked=True)
    t.deal()
    t.declare()
    t.act(plays=10)
    # a newcomer takes a bot's seat mid-round, logged as the server logs it
    t.room.seats[2].name, t.room.seats[2].is_bot = "Zed Joiner", False
    t.room.log_event("seat_claimed", seat=2, name="Zed Joiner", bot=False)
    t.act()
    srv.rooms.pop("LATE")
    rerun = _watch(client).json()
    assert rerun["rerun"] is True and rerun["round"] == 1
    blob = json.dumps(rerun)
    for name in ("Mei", "Zed Joiner"):           # people not on the leaderboard
        assert name not in blob, name
    for name in ("Bot 1", "Bot 3"):               # bots keep their names
        assert name in blob, name
    claimed = [e for e in rerun["events"] if e["e"] == "seat_claimed"]
    assert claimed and all(e.get("name") in (None, f"Player {e['seat'] + 1}") for e in claimed)



def _rated(store, sub, name, visible=True):
    """An account with one rated round, listed on the leaderboard unless hidden."""
    from shengji.api import ratings

    uid = store.upsert_user(_claims(sub=sub, email=f"{sub}@example.com"))["id"]
    with store._open() as conn:
        conn.execute(
            """INSERT INTO rating_events(game_id, round_no, user_id, created_at, team, banker_team, won,
                   levels, game_won, expected, actual, k, rating_before, rating_after, delta)
               VALUES ('g', 1, ?, ?, 0, 1, 1, 1, 0, 0.5, 1, 20, 1000, 1003, 3)""", (uid, time.time() - 600))
        conn.commit()
    ratings.set_visible(store, uid, visible)
    return uid


def test_a_rerun_names_only_the_players_the_leaderboard_shows(accounts_on, feed):
    from shengji.api import ratings

    srv, spectate, client = feed
    store = accounts_on.STORE
    listed = _rated(store, "listed", "Mei")
    hidden = _rated(store, "hidden", "Hidey", visible=False)
    unrated = store.upsert_user(_claims(sub="unrated", email="unrated@example.com"))["id"]
    assert listed in ratings.listed_ids(store) and hidden not in ratings.listed_ids(store)
    t = Table(srv, code="LIST", ranked=True)
    t.room.seats = [srv.Seat(name="Mei", user_id=listed, connected=True),
                    srv.Seat(name="Bot 1", is_bot=True),
                    srv.Seat(name="Guesty", connected=True),
                    srv.Seat(name="Hidey", user_id=hidden, connected=True)]
    t.deal()
    t.declare()
    t.act(plays=10)
    # an account not on the leaderboard takes the bot's seat mid-round
    t.room.seats[1] = srv.Seat(name="Unrated Uma", user_id=unrated, connected=True)
    t.room.log_event("seat_claimed", seat=1, name="Unrated Uma", bot=False)
    t.act()
    srv.rooms.pop("LIST")
    rerun = _watch(client).json()
    assert rerun["rerun"] is True
    assert rerun["players"] == ["Mei", "Bot 1", "Player 3", "Player 4"]
    blob = json.dumps(rerun)
    assert "Mei" in blob
    for name in ("Guesty", "Hidey", "Unrated Uma"):
        assert name not in blob, name


def test_only_a_ranked_round_is_ever_a_rerun(feed):
    srv, spectate, client = feed
    casual = Table(srv, code="CASU")
    casual.play_round()
    srv.rooms.pop("CASU")
    assert list(spectate._reruns) == []
    assert _watch(client).status_code == 404


def _claim(srv, spectate, room, seat, name, user_id):
    """A person takes ``seat`` as the server's claim writers do: the seat, the
    record, and the claim's own account for the replay."""
    room.seats[seat] = srv.Seat(name=name, user_id=user_id, connected=True)
    spectate.claimed(room, room.log_event("seat_claimed", seat=seat, name=name, bot=False), user_id)


@pytest.mark.parametrize("order", ["unlisted_then_listed", "listed_then_unlisted"])
def test_each_claim_is_named_by_its_own_claimer(accounts_on, feed, order):
    srv, spectate, client = feed
    store = accounts_on.STORE
    listed = _rated(store, "claim-listed", "Lena")
    unlisted = store.upsert_user(_claims(sub="claim-unlisted", email="cu@example.com"))["id"]
    t = Table(srv, code="CLAM", ranked=True)
    t.deal()
    t.declare()
    t.act(plays=8)
    first, second = ((("Una Unlisted", unlisted), ("Lena Listed", listed)) if order == "unlisted_then_listed"
                     else (("Lena Listed", listed), ("Una Unlisted", unlisted)))
    _claim(srv, spectate, t.room, 1, *first)
    t.act(plays=8)
    _claim(srv, spectate, t.room, 1, *second)
    t.act()
    srv.rooms.pop("CLAM")
    rerun = _watch(client).json()
    assert rerun["rerun"] is True
    blob = json.dumps(rerun)
    assert "Lena Listed" in blob
    assert "Una Unlisted" not in blob
    claims = [e for e in rerun["events"] if e["e"] == "seat_claimed"]
    assert [e["name"] for e in claims] == [("Player 2" if n == "Una Unlisted" else n) for n, _ in (first, second)]
    assert "_at" not in blob


def test_every_claim_writer_records_its_claimer():
    import re
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "shengji" / "api" / "server.py").read_text()
    writes = re.findall(r'.*log_event\("seat_claimed".*', src)
    assert len(writes) == 3
    assert all("spectate.claimed(" in line for line in writes), writes


# ------------------------------------------------------- capacity and the cache
def test_the_count_leaves_out_a_full_table(feed, monkeypatch):
    srv, spectate, client = feed
    monkeypatch.setattr(spectate.LIMITER, "limit", 1000)
    t = Table(srv, ranked=True)
    t.play_round()
    t.deal()
    for _ in range(spectate.WATCH_CAP - 1):
        _watch(client)
    assert spectate.presence() == {"watch": 1, "rerun": True}
    _watch(client)
    # full: the line offers the replay, not a live table it cannot give
    assert spectate.presence() == {"watch": 0, "rerun": True}
    assert spectate.presence_key() == (0, 0, True)
    for tok in list(t.room.watch.watchers):
        t.room.watch.watchers[tok] -= spectate.WATCH_TTL + 1
    assert spectate.presence() == {"watch": 1, "rerun": True}


def test_a_finished_round_is_read_once_and_served_as_the_same_bytes(feed, monkeypatch):
    srv, spectate, client = feed
    t = Table(srv, code="CACH", ranked=True)
    reads = []
    real = spectate.round_doc

    def counting(f, listed=None):
        reads.append((f.round, listed is None))
        return real(f, listed)

    monkeypatch.setattr(spectate, "round_doc", counting)
    t.play_round()
    t.deal()
    assert reads == [(1, True)]           # read once, at the round's end
    first, second = _watch(client), _watch(client)
    assert first.json()["watcher"] != second.json()["watcher"]

    def body(resp):
        doc = resp.json()
        doc.pop("watcher")
        doc.pop("watchers", None)       # the second reader is counted too
        return json.dumps(doc, sort_keys=True)

    assert body(first) == body(second)
    tid = first.json()["table"]
    follow = client.get(f"/api/watch/{tid}", params={"after": 0, "w": first.json()["watcher"]})
    assert follow.json()["events"] == first.json()["events"]
    assert reads == [(1, True)]
    # a rerun is built once per leaderboard mask as well
    srv.rooms.pop("CACH")
    r1, r2 = _watch(client), _watch(client)
    assert body(r1) == body(r2) and r1.json()["rerun"] is True
    assert reads == [(1, True), (1, False)]


# ------------------------------------------------------- reruns across a restart
def _restart(spectate, monkeypatch):
    """What a new process has: nothing in memory, the index on disk."""
    monkeypatch.setattr(spectate, "_reruns", spectate.collections.deque(maxlen=spectate.KEEP_ROUNDS))
    monkeypatch.setattr(spectate, "_DOCS", spectate.collections.OrderedDict())
    monkeypatch.setattr(spectate, "_loaded", False)


def test_reruns_survive_a_restart(feed, monkeypatch):
    srv, spectate, client = feed
    t = Table(srv, code="KEEP", ranked=True)
    t.play_round()
    t.play_round()
    srv.rooms.pop("KEEP")
    before = _watch(client).json()
    index = spectate._index_path()
    assert index == srv.LOG_DIR.parent / "spectate" / "replays.json"
    text = index.read_text()
    saved = json.loads(text)
    assert saved["schema"] == spectate.INDEX_SCHEMA and [e["round"] for e in saved["rounds"]] == [1, 2]
    assert saved["rounds"][0]["start_accounts"] == [41, None, None, None]
    assert "Mei" not in text and "Bot 1" not in text      # ids only, never a name
    assert not list(index.parent.glob("*.tmp"))

    _restart(spectate, monkeypatch)
    assert spectate.presence() == {"watch": 0, "rerun": True}
    after = _watch(client).json()
    assert after["rerun"] is True and after["round"] == 2
    assert after["events"] == before["events"] and after["players"] == before["players"]


@pytest.mark.parametrize("content", [None, b"", b"{not json", b"[]", b'{"schema": 99, "rounds": []}',
                                     b'{"schema": 1, "rounds": [{"path": 3}, "x", null]}',
                                     b"\x00" * (300 * 1024)],
                         ids=["missing", "empty", "not-json", "a-list", "other-schema",
                              "bad-entries", "oversize"])
def test_a_missing_or_corrupt_index_starts_empty(feed, monkeypatch, content):
    srv, spectate, client = feed
    index = spectate._index_path()
    index.parent.mkdir(parents=True, exist_ok=True)
    if content is not None:
        index.write_bytes(content)
    _restart(spectate, monkeypatch)
    assert spectate.presence() == {"watch": 0, "rerun": False}
    assert list(spectate._reruns) == []
    assert _watch(client).status_code == 404
    # the next ranked round end writes a good index over it
    t = Table(srv, code="NEXT", ranked=True)
    t.play_round()
    assert [e["round"] for e in json.loads(index.read_text())["rounds"]] == [1]


def test_an_entry_whose_log_is_gone_or_cut_is_dropped_on_load(feed, monkeypatch):
    srv, spectate, client = feed
    gone = Table(srv, code="GONE", ranked=True)
    gone.play_round()
    cut = Table(srv, code="CUTS", ranked=True)
    cut.play_round()
    kept = Table(srv, code="KEPT", ranked=True)
    kept.play_round()
    for code in ("GONE", "CUTS", "KEPT"):
        srv.rooms.pop(code)
    spectate._log_path(gone.room).unlink()
    _drop_a_play(spectate._log_path(cut.room), 1)
    _restart(spectate, monkeypatch)
    spectate.load()
    assert [Path(f.path).name for f in spectate._reruns] == ["KEPT.jsonl"]
    saved = json.loads(spectate._index_path().read_text())
    assert [Path(e["path"]).name for e in saved["rounds"]] == ["KEPT.jsonl"]
    doc = _watch(client).json()
    assert doc["rerun"] is True and doc["events"][-1]["e"] == "round_end"


def test_a_player_who_leaves_the_leaderboard_is_masked_on_the_next_serve(accounts_on, feed, monkeypatch):
    from shengji.api import ratings

    srv, spectate, client = feed
    store = accounts_on.STORE
    mei = _rated(store, "leaver", "Mei")
    t = Table(srv, code="LEFT", ranked=True)
    t.room.seats[0] = srv.Seat(name="Mei", user_id=mei, connected=True)
    t.play_round()
    srv.rooms.pop("LEFT")
    assert _watch(client).json()["players"][0] == "Mei"
    _restart(spectate, monkeypatch)
    assert _watch(client).json()["players"][0] == "Mei"     # named again from the log
    ratings.set_visible(store, mei, False)
    hidden = _watch(client).json()
    assert hidden["players"][0] == "Player 1"
    assert "Mei" not in json.dumps(hidden)
    ratings.set_visible(store, mei, True)
    assert _watch(client).json()["players"][0] == "Mei"


def _blank_line_at(path, offset):
    """The log line at ``offset`` rewritten, same length, to parse as JSON null."""
    data = bytearray(path.read_bytes())
    end = data.index(b"\n", offset)
    data[offset:end] = b"null" + b" " * (end - offset - 4)
    path.write_bytes(bytes(data))


def test_a_damaged_replay_drops_alone_and_the_healthy_one_still_plays(feed, monkeypatch):
    srv, spectate, client = feed
    null = Table(srv, code="NULL", ranked=True)
    null.play_round()
    good = Table(srv, code="GOOD", ranked=True)
    good.play_round()
    casual = Table(srv, code="CASL")
    casual.play_round()
    for code in ("NULL", "GOOD", "CASL"):
        srv.rooms.pop(code)
    _blank_line_at(spectate._log_path(null.room), null.room.watch.last.start)
    # an entry naming a casual round, as a wrong offset or a hand edit could
    index = spectate._index_path()
    saved = json.loads(index.read_text())
    stray = dict(saved["rounds"][-1], path=str(spectate._log_path(casual.room)),
                 start=casual.room.watch.last.start)
    saved["rounds"] = [saved["rounds"][0], stray, saved["rounds"][1]]
    index.write_text(json.dumps(saved))
    _restart(spectate, monkeypatch)
    for _ in range(3):                    # the first request and the ones after it
        resp = _watch(client)
        assert resp.status_code == 200
        doc = resp.json()
        assert doc["rerun"] is True and doc["round"] == 1
        assert _deck_cards(doc) == list(good.room.round.deck)
        assert spectate.presence() == {"watch": 0, "rerun": True}
    assert [Path(f.path).name for f in spectate._reruns] == ["GOOD.jsonl"]
    assert [Path(e["path"]).name for e in json.loads(index.read_text())["rounds"]] == ["GOOD.jsonl"]


def test_a_live_table_with_no_whole_round_is_neither_counted_nor_held(feed, monkeypatch):
    srv, spectate, client = feed
    gone = Table(srv, code="OLDR", ranked=True)
    gone.play_round()
    srv.rooms.pop("OLDR")
    _lose_a_play(monkeypatch, srv, 1)
    live = Table(srv, code="LIVE", ranked=True)
    live.play_round()
    live.deal()
    assert spectate.watchable(live.room)          # a table with someone there ...
    assert spectate.presence() == {"watch": 0, "rerun": True}   # ... but nothing whole to show
    doc = _watch(client).json()
    assert doc["rerun"] is True and doc["table"] == spectate.RERUN_ID
    assert live.room.watch.watchers == {}         # the replay viewer holds no live place
    assert spectate.presence() == {"watch": 0, "rerun": True}


def test_an_undealt_room_beside_a_live_table_does_not_break_the_pick(feed):
    srv, spectate, client = feed
    srv.rooms["UNDL"] = srv.Room(code="UNDL")             # a lobby: no game, no watch
    t = Table(srv, code="SERV", ranked=True)
    t.play_round()
    t.deal()
    srv.rooms["UND2"] = srv.Room(code="UND2")
    assert spectate.presence() == {"watch": 1, "rerun": True}
    for params in ({}, {"mode": "ranked"}, {"mode": "casual"}, {"skip": "nope"}):
        resp = _watch(client, **params)
        assert resp.status_code == 200, params
        assert resp.json()["table"] == t.room.watch.id and resp.json()["rerun"] is False


def test_an_incomplete_ranked_round_is_never_kept_to_replay(feed, monkeypatch):
    srv, spectate, client = feed
    _lose_a_play(monkeypatch, srv, 1)
    t = Table(srv, code="BRKN", ranked=True)
    t.play_round()
    srv.rooms.pop("BRKN")
    assert list(spectate._reruns) == []
    index = spectate._index_path()
    assert not index.exists() or json.loads(index.read_text())["rounds"] == []
    assert spectate.presence() == {"watch": 0, "rerun": False}
    assert _watch(client).status_code == 404               # and nothing promised it


def test_an_incomplete_round_never_pushes_out_a_good_replay(feed, monkeypatch):
    srv, spectate, client = feed
    good = Table(srv, code="GOOD", ranked=True)
    good.play_round()
    srv.rooms.pop("GOOD")
    for i in range(spectate.KEEP_ROUNDS + 1):
        with monkeypatch.context() as m:
            _lose_a_play(m, srv, 1)
            bad = Table(srv, code=f"BAD{i}", ranked=True)
            bad.play_round()
        srv.rooms.pop(f"BAD{i}")
    assert [Path(f.path).name for f in spectate._reruns] == ["GOOD.jsonl"]
    assert [Path(e["path"]).name for e in json.loads(spectate._index_path().read_text())["rounds"]] \
        == ["GOOD.jsonl"]
    assert spectate.presence() == {"watch": 0, "rerun": True}
    doc = _watch(client).json()
    assert doc["rerun"] is True and _deck_cards(doc) == list(good.room.round.deck)


# ------------------------------------------------------- presence and serve agree
STATES = ("lobby", "undealt", "mid_first", "finished", "finished_next", "incomplete", "closed",
          "closed_incomplete")


def _room_in(srv, monkeypatch, code, state, ranked, joiners, connected):
    if state == "lobby":
        srv.rooms[code] = srv.Room(code=code)
        return None
    t = Table(srv, code=code, ranked=ranked, allow_joiners=joiners)
    t.room.seats[0].connected = connected
    if state == "undealt":
        return t
    if state == "mid_first":
        t.deal()
        t.declare()
        t.act(plays=7)
        return t
    if state in ("incomplete", "closed_incomplete"):
        with monkeypatch.context() as m:
            _lose_a_play(m, srv, 1, nth=11)
            t.play_round()
    else:
        t.play_round()
    if state in ("finished_next", "incomplete"):
        t.deal()
    if state.startswith("closed"):
        srv.rooms.pop(code)
    return t


@pytest.mark.parametrize("seed", range(30))
def test_presence_and_serve_agree_over_random_rooms(feed, monkeypatch, seed):
    import random

    srv, spectate, client = feed
    monkeypatch.setattr(spectate.LIMITER, "limit", 10 ** 6)
    rng = random.Random(seed)
    for i in range(rng.randint(1, 5)):
        _room_in(srv, monkeypatch, f"FZ{i:02d}", rng.choice(STATES), rng.random() < 0.6,
                 rng.random() < 0.5, rng.random() < 0.8)
    for _ in range(rng.randint(1, 4)):
        watch, rerun = spectate.presence()["watch"], spectate.presence()["rerun"]
        mode = rng.choice([None, "ranked", "casual"])
        resp = _watch(client, **({"mode": mode} if mode else {}))
        assert resp.status_code in (200, 404), resp.text
        held = {tok for r in spectate._rooms() if r.watch is not None for tok in r.watch.watchers}
        if watch > 0:
            # a live table promised: the feed gives one (any mode falls back to it)
            doc = resp.json()
            assert resp.status_code == 200 and doc["rerun"] is False, (seed, watch, doc.get("table"))
            follow = client.get(f"/api/watch/{doc['table']}", params={"w": doc["watcher"]})
            assert follow.status_code == 200 and follow.json()["round"] == doc["round"]
            assert doc["watcher"] in held
        elif rerun:
            assert resp.status_code == 200 and resp.json()["rerun"] is True, seed
            assert resp.json()["watcher"] not in held
        else:
            assert resp.status_code == 404, seed
        if resp.status_code == 200:
            events = resp.json()["events"]
            assert events[0]["e"] == "round_start" and events[-1]["e"] == "round_end"


# ------------------------------------------------------- the players are told
@pytest.fixture()
def told(feed, monkeypatch):
    """The feed, with each announcement run by the test: ``run()`` tells the
    players now, as the scheduled one does once its gap has passed."""
    import asyncio

    srv, spectate, client = feed
    scheduled, pushed = [], []
    monkeypatch.setattr(spectate, "_schedule", lambda room: scheduled.append(room))

    async def broadcast(room):
        pushed.append({s: srv.state_for(room, s) for s, sd in enumerate(room.seats)
                       if sd is not None and not sd.is_bot})

    monkeypatch.setattr(srv, "_broadcast_locked", broadcast)

    def run(room):
        asyncio.run(spectate._announce(room, 0))
        return pushed[-1] if pushed else None

    return srv, spectate, client, scheduled, pushed, run


def _watcher(store, sub, name, listed=True):
    uid = _rated(store, sub, name, visible=listed)
    store.set_display_name(uid, name)
    return {"cookie": f"sj_session={store.create_session(uid)}"}


def test_the_players_count_their_watchers_up_and_down(told, monkeypatch):
    srv, spectate, client, scheduled, _, _ = told
    t = Table(srv, ranked=True)
    t.play_round()
    t.deal()
    assert srv.state_for(t.room, 0)["watchers"]["count"] == 0
    first = _watch(client).json()
    assert first["watchers"] == 1                     # the watcher reads the count too
    second = _watch(client).json()
    assert second["watchers"] == 2
    assert srv.state_for(t.room, 0)["watchers"]["count"] == 2
    # following again is the same watcher: no new count, no new toast
    client.get(f"/api/watch/{first['table']}", params={"after": first["round"], "w": first["watcher"]})
    assert srv.state_for(t.room, 0)["watchers"]["count"] == 2
    assert len(scheduled) == 2
    # a watcher counts until WATCH_TTL passes without a read
    t.room.watch.watchers[first["watcher"]] -= spectate.WATCH_TTL + 1
    assert srv.state_for(t.room, 0)["watchers"]["count"] == 1
    assert first["watcher"] not in t.room.watch.who
    t.room.watch.watchers[second["watcher"]] -= spectate.WATCH_TTL + 1
    assert srv.state_for(t.room, 0)["watchers"]["count"] == 0


def test_a_listed_watcher_is_named_and_anyone_else_is_not(accounts_on, told):
    srv, spectate, client, _, _, run = told
    store = accounts_on.STORE
    mei = _watcher(store, "w-mei", "Mei Listed")
    hidden = _watcher(store, "w-hid", "Hana Hidden", listed=False)
    t = Table(srv, code="TOLD", ranked=True)
    t.play_round()
    t.deal()
    client.get("/api/watch", headers=hidden)
    client.get("/api/watch")                          # a guest
    client.get("/api/watch", headers=mei)
    frames = run(t.room)
    w = frames[0]["watchers"]
    assert w["count"] == 3 and w["told"] == 1
    assert w["joined"] == [None, None, {"name": "Mei Listed"}]
    assert w["named"] == ["Mei Listed"]
    # nothing names the unlisted account or carries an account id, anywhere
    blob = json.dumps(frames)
    assert "Hana Hidden" not in blob and "Hana" not in blob
    # the field holds a count, a number, and names: no id in any shape
    assert set(w) == {"count", "told", "joined", "named"}
    assert all(j is None or set(j) == {"name"} for j in w["joined"])
    assert all(isinstance(n, str) for n in w["named"])
    # no toast when nobody new arrived
    assert run(t.room) is frames
    assert srv.state_for(t.room, 0)["watchers"]["told"] == 1


def test_arrivals_within_the_gap_are_told_together(told, monkeypatch):
    srv, spectate, client, scheduled, pushed, _ = told
    t = Table(srv, ranked=True)
    t.play_round()
    t.deal()
    clock = [1000.0]
    monkeypatch.setattr(spectate.time, "time", lambda: clock[0])
    st = t.room.watch
    for tok in ("a" * 16, "b" * 16):
        st.watchers[tok] = clock[0]
        st.arrivals.append(tok)
    assert spectate.announcement(st, set(), clock[0]) is True
    assert st.told == 1 and st.joined == [None, None]
    # one more arrives 5 s later: it waits for the rest of the gap
    clock[0] += 5
    st.watchers["c" * 16] = clock[0]
    st.arrivals.append("c" * 16)
    assert st.told_at + spectate.ANNOUNCE_GAP - clock[0] == pytest.approx(25.0)
    # a watcher who left before its turn is not told of
    st.watchers["d" * 16] = clock[0]
    st.arrivals.append("d" * 16)
    st.drop("d" * 16)
    clock[0] += 25
    assert spectate.announcement(st, set(), clock[0]) is True
    assert st.told == 2 and st.joined == [None]


def test_the_scheduled_announcement_waits_out_the_gap(feed, monkeypatch):
    import asyncio

    srv, spectate, client = feed
    t = Table(srv, ranked=True)
    t.play_round()
    t.deal()
    st = t.room.watch
    waits, pushed = [], []

    async def sleep(s):
        waits.append(s)

    async def broadcast(room):
        pushed.append(st.told)

    monkeypatch.setattr(spectate.asyncio, "sleep", sleep)
    monkeypatch.setattr(srv, "_broadcast_locked", broadcast)
    monkeypatch.setattr(spectate, "_listed", lambda: set())

    async def scenario():
        st.watchers["a" * 16] = time.time()
        st.arrivals.append("a" * 16)
        spectate._schedule(t.room)
        await st.announcing
        assert pushed == [1] and waits == []          # the first is told at once
        st.watchers["b" * 16] = time.time()
        st.arrivals.append("b" * 16)
        spectate._schedule(t.room)
        spectate._schedule(t.room)                    # one wait, however many arrive
        await st.announcing
        assert pushed == [1, 2] and len(waits) == 1
        assert waits[0] == pytest.approx(spectate.ANNOUNCE_GAP, abs=1.0)

    asyncio.run(scenario())


def test_a_watcher_leaving_tells_the_players_nothing(told):
    srv, spectate, client, scheduled, pushed, run = told
    t = Table(srv, ranked=True)
    t.play_round()
    t.deal()
    first = _watch(client).json()
    run(t.room)
    assert len(pushed) == 1
    t.room.watch.watchers[first["watcher"]] -= spectate.WATCH_TTL + 1
    assert run(t.room) is pushed[0] and len(pushed) == 1
    assert srv.state_for(t.room, 0)["watchers"] == {"count": 0, "told": 1, "joined": [None], "named": []}


def test_a_rerun_carries_no_watcher_count(feed):
    srv, spectate, client = feed
    t = Table(srv, code="GONE", ranked=True)
    t.play_round()
    srv.rooms.pop("GONE")
    rerun = _watch(client).json()
    assert rerun["rerun"] is True and "watchers" not in rerun


def test_an_announcement_cancelled_in_its_wait_tells_nothing(feed, monkeypatch):
    """LIFECYCLE_CHECKLIST 1: cancelled at an await, it commits nothing."""
    import asyncio

    srv, spectate, client = feed
    t = Table(srv, ranked=True)
    t.play_round()
    t.deal()
    st = t.room.watch
    st.watchers["a" * 16] = time.time()
    st.arrivals.append("a" * 16)
    pushed = []

    async def broadcast(room):
        pushed.append(room)

    monkeypatch.setattr(srv, "_broadcast_locked", broadcast)

    async def scenario():
        task = asyncio.ensure_future(spectate._announce(t.room, 5.0))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(scenario())
    assert st.told == 0 and st.joined == [] and pushed == []
    assert st.arrivals == ["a" * 16]                  # told by the next announcement


def test_a_table_closed_during_the_wait_is_sent_nothing(feed, monkeypatch):
    """LIFECYCLE_CHECKLIST 2: the room may be gone after the wait."""
    import asyncio

    srv, spectate, client = feed
    t = Table(srv, code="SHUT", ranked=True)
    t.play_round()
    t.deal()
    st = t.room.watch
    st.watchers["a" * 16] = time.time()
    st.arrivals.append("a" * 16)
    sent = []
    monkeypatch.setattr(srv, "enqueue", lambda seat, frame: sent.append(frame))
    monkeypatch.setattr(spectate, "_listed", lambda: set())
    srv.rooms.pop("SHUT")
    asyncio.run(spectate._announce(t.room, 0))
    assert sent == []


@pytest.mark.parametrize("route", ["watch", "follow"])
def test_a_table_gone_during_the_account_read_is_not_served(feed, monkeypatch, route):
    """LIFECYCLE_CHECKLIST 2: the account read is an await; a table that
    stops being watchable during it is not answered as live, and counts nobody."""
    srv, spectate, client = feed
    t = Table(srv, code="GOAW", ranked=True)
    t.play_round()
    t.deal()
    first = None
    if route == "follow":
        first = _watch(client).json()
        t.room.watch.drop(first["watcher"])           # a reader new to the table again
    scheduled = []
    monkeypatch.setattr(spectate, "_schedule", lambda room: scheduled.append(room))
    real = spectate._viewer

    async def viewer(request):
        user = await real(request)
        t.room.aborted = True                          # the table ends while its account is read
        return user

    monkeypatch.setattr(spectate, "_viewer", viewer)
    if route == "watch":
        resp = _watch(client)
        assert resp.status_code == 404 or resp.json().get("rerun") is True
    else:
        resp = client.get(f"/api/watch/{first['table']}", params={"after": first["round"], "w": first["watcher"]})
        assert resp.status_code == 404
    assert t.room.watch.watchers == {} and scheduled == []


def test_a_watcher_reading_through_a_long_round_stays_counted_and_is_told_once(told, monkeypatch):
    srv, spectate, client, scheduled, _, _ = told
    t = Table(srv, ranked=True)
    t.play_round()
    t.deal()
    clock = [time.time()]
    monkeypatch.setattr(spectate.time, "time", lambda: clock[0])
    first = _watch(client).json()
    # the watch screen's foreground poll every 15 s while the round plays back
    for _ in range(12):
        clock[0] += 15
        r = client.get(f"/api/watch/{first['table']}", params={"after": first["round"], "w": first["watcher"]})
        assert r.status_code == 200
        assert srv.state_for(t.room, 0)["watchers"]["count"] == 1
    assert len(scheduled) == 1 and t.room.watch.arrivals == [first["watcher"]]
