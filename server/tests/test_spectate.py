"""Watching a table (``/api/watch``): one round behind, never a round in play.

Rounds are played in-process through the server's own logging functions
(``_log_round_start``, ``bot_step``, which logs ``round_end`` through
``_finish_round``) with the heuristic bot on every seat, so the feed reads the
real record format from the real room log.
"""
from __future__ import annotations

import json

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
    n, path, offset = st.started
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


def test_at_most_eight_watchers_per_table(feed):
    srv, spectate, client = feed
    t = Table(srv, ranked=True)
    t.play_round()
    t.deal()
    tokens = [_watch(client).json()["watcher"] for _ in range(spectate.WATCH_CAP)]
    assert len(set(tokens)) == spectate.WATCH_CAP
    assert t.room.watch.live_watchers(spectate.time.time()) == spectate.WATCH_CAP
    # the ninth gets the rerun (this table's own round, from the log), not a place here
    ninth = _watch(client).json()
    assert ninth["rerun"] is True and ninth["table"] == spectate.RERUN_ID
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
    """Run ``change`` while the feed reads the log, as another request could."""
    real = spectate.round_doc

    def reading(f):
        doc = real(f)
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


def test_a_round_missing_an_interior_play_is_refused_and_the_last_good_round_kept(feed):
    srv, spectate, client = feed
    t = Table(srv, ranked=True)
    t.play_round()
    first = _watch(client).json()
    assert first["round"] == 1
    t.play_round()
    t.deal()
    _drop_a_play(spectate._log_path(t.room), 2)
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
    assert rerun["players"] == ["Player 1", "Player 2", "Player 3", "Player 4"]
    start = next(e for e in rerun["events"] if e["e"] == "round_start")
    assert [p["name"] for p in start["players"]] == ["Player 1", "Player 2", "Player 3", "Player 4"]
    assert "Mei" not in json.dumps(rerun)
