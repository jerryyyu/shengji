"""Blocking a player (``block_player``, ``shengji.api.blocks``).

A block between two accounts is stored and outlives the game and the
process: the server relays none of the blocked player's chat to the blocker
in a later game, and the blocker's frames mark the seat ``blocked``. A guest's
blocks are held in memory. Deleting either account removes its stored
blocks. No frame names an account, and no block reaches a log. The waiting
table's chat leaves out a blocked sender's lines too, and its lines keep
their writer into the room, whoever holds that seat when the game starts.
"""
from __future__ import annotations

import json

import pytest

from tests.test_server_ws import _drain, _frames_until, client  # noqa: F401


@pytest.fixture()
def blocks_on(tmp_path, monkeypatch):
    """A private data dir and accounts store, and empty block lists."""
    from shengji.api import accounts, blocks

    monkeypatch.setenv("SHENGJI_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(accounts, "STORE", accounts.Store(tmp_path / "data" / "accounts.sqlite3"))
    blocks.reset()
    yield blocks
    blocks.reset()


def _cookie(accounts, sub, name):
    user = accounts.STORE.upsert_user({"sub": sub, "email": f"{sub}@example.com", "name": name})
    return user, f"{accounts.COOKIE}={accounts.STORE.create_session(user['id'])}"


def _no_account_fields(frames):
    """No frame carries an account field or a block's stored key."""
    for frame in frames:
        text = json.dumps(frame)
        for word in ("account", "user_id", "blocked_id", "blocker", "queue_id", "device"):
            assert word not in text, (word, frame)
        for player in frame.get("players", []) if frame.get("type") == "state" else []:
            assert player.get("blocked", True) is True


def _sit(client, ada_cookie, bea_cookie, *, ada_device=None):
    """Ada's and Bea's sockets, not yet open."""
    url = f"/ws?device={ada_device}" if ada_device else "/ws"
    a = client.websocket_connect(url, headers={"cookie": ada_cookie} if ada_cookie else {})
    b = client.websocket_connect("/ws", headers={"cookie": bea_cookie})
    return a, b


def _open_room(a, b):
    a.send_json({"type": "create_room", "name": "Ada"})
    code = _drain(a, "room")["room"]
    b.send_json({"type": "table_join", "expect": "room", "code": code, "name": "Bea", "seat": 2})
    _drain(b, "state")
    return code


def _until_own_line(ws, text):
    """Ada's frames up to her own line ``text``: whatever Bea said before it
    would have arrived first."""
    return _frames_until(ws, lambda m: m.get("type") == "chat" and m.get("text") == text,
                         repr(text))


def _chat_texts(frames):
    return [f["text"] for f in frames if f.get("type") == "chat"]


def test_the_store_keeps_blocks_and_drops_them_with_either_account(blocks_on):
    from shengji.api import accounts

    store = accounts.STORE
    ada = store.upsert_user({"sub": "g-a", "email": "a@example.com", "name": "Ada"})
    bea = store.upsert_user({"sub": "g-b", "email": "b@example.com", "name": "Bea"})
    cy = store.upsert_user({"sub": "g-c", "email": "c@example.com", "name": "Cy"})
    assert store.schema_version() == len(accounts.SCHEMA)
    store.set_block(ada["id"], bea["id"], True)
    store.set_block(ada["id"], bea["id"], True)          # once only
    store.set_block(ada["id"], cy["id"], True)
    store.set_block(cy["id"], ada["id"], True)
    store.set_block(ada["id"], 99_999, True)             # no such account: nothing
    assert sorted(store.blocked_ids(ada["id"])) == sorted([bea["id"], cy["id"]])
    store.set_block(ada["id"], cy["id"], False)
    assert store.blocked_ids(ada["id"]) == [bea["id"]]
    assert store.delete_user(bea["id"])
    assert store.blocked_ids(ada["id"]) == []            # the blocked side went
    assert store.blocked_ids(cy["id"]) == [ada["id"]]
    assert store.delete_user(ada["id"])
    assert store.blocked_ids(cy["id"]) == []             # and the blocker side


def test_a_block_hides_the_chat_now_and_in_a_later_game_after_a_restart(client, blocks_on):
    from shengji.api import accounts
    from shengji.api import server as srv

    ada, ada_cookie = _cookie(accounts, "g-a", "Ada Lovelace")
    bea, bea_cookie = _cookie(accounts, "g-b", "Bea Smith")
    a_cm, b_cm = _sit(client, ada_cookie, bea_cookie)
    seen = []
    with a_cm as a, b_cm as b:
        code = _open_room(a, b)
        b.send_json({"type": "table_chat", "text": "before the block"})
        seen += _frames_until(a, lambda m: m.get("type") == "chat"
                              and m.get("text") == "before the block", "Bea's line")
        a.send_json({"type": "block_player", "seat": 2, "on": True})
        history = _drain(a, "chat_history")
        assert history["room"] == code
        assert "before the block" not in [m["text"] for m in history["messages"]]
        state = _drain(a, "state")
        assert state["players"][2]["blocked"] is True
        assert not any("blocked" in p for i, p in enumerate(state["players"]) if i != 2)
        b.send_json({"type": "table_chat", "text": "you cannot hear me"})
        _drain(b, "chat")                                # Bea still sees her own line
        a.send_json({"type": "table_chat", "text": "ada here"})
        frames = _until_own_line(a, "ada here")
        assert "you cannot hear me" not in _chat_texts(frames)
        seen += [history, state, *frames]
        # Bea is told nothing: her frames carry no block
        bea_frames = _frames_until(b, lambda m: m.get("type") == "chat"
                                   and m.get("text") == "ada here", "Ada's line")
        assert not any("blocked" in json.dumps(f) for f in bea_frames)
        records = [json.loads(line) for line in
                   (srv.LOG_DIR / f"{code}.jsonl").read_text("utf-8").splitlines()]
        assert not any("block" in r["e"] or "blocked" in r or "account_id" in r for r in records)
    assert accounts.STORE.blocked_ids(ada["id"]) == [bea["id"]]

    blocks_on.reset()                                    # a restart: memory is gone
    a_cm, b_cm = _sit(client, ada_cookie, bea_cookie)
    with a_cm as a, b_cm as b:
        _open_room(a, b)
        state = _drain(a, "state")
        while state["players"][2]["name"] != "Bea":
            state = _drain(a, "state")
        assert state["players"][2]["blocked"] is True
        b.send_json({"type": "table_chat", "text": "a new game"})
        _drain(b, "chat")
        a.send_json({"type": "table_chat", "text": "still ada"})
        frames = _until_own_line(a, "still ada")
        assert "a new game" not in _chat_texts(frames)
        seen += frames
        # unblock: the lines come back, from now and before
        a.send_json({"type": "block_player", "seat": 2, "on": False})
        history = _drain(a, "chat_history")
        assert "a new game" in [m["text"] for m in history["messages"]]
        state = _drain(a, "state")
        assert "blocked" not in state["players"][2]
        b.send_json({"type": "table_chat", "text": "back again"})
        assert _drain(a, "chat")["text"] == "back again"
        seen += [history, state]
    assert accounts.STORE.blocked_ids(ada["id"]) == []
    _no_account_fields(seen)


def test_a_guest_blocks_for_this_device_in_memory_only(client, blocks_on):
    from shengji.api import accounts

    _, bea_cookie = _cookie(accounts, "g-b", "Bea Smith")
    device = "d" * 24
    a_cm, b_cm = _sit(client, None, bea_cookie, ada_device=device)
    with a_cm as a, b_cm as b:
        _open_room(a, b)
        a.send_json({"type": "block_player", "seat": 2})  # ``on`` defaults to a block
        _drain(a, "chat_history")
        assert _drain(a, "state")["players"][2]["blocked"] is True
    a_cm, b_cm = _sit(client, None, bea_cookie, ada_device=device)
    with a_cm as a, b_cm as b:
        _open_room(a, b)
        b.send_json({"type": "table_chat", "text": "guest cannot hear"})
        _drain(b, "chat")
        a.send_json({"type": "table_chat", "text": "guest line"})
        frames = _until_own_line(a, "guest line")
        assert "guest cannot hear" not in _chat_texts(frames)
        _no_account_fields(frames)
    with accounts.STORE._open() as conn:
        assert conn.execute("SELECT COUNT(*) FROM blocks").fetchone()[0] == 0


def test_a_bot_a_bad_seat_and_ones_own_seat_cannot_be_blocked(client, blocks_on):
    from shengji.api import accounts

    _, ada_cookie = _cookie(accounts, "g-a", "Ada Lovelace")
    _, bea_cookie = _cookie(accounts, "g-b", "Bea Smith")
    a_cm, b_cm = _sit(client, ada_cookie, bea_cookie)
    with a_cm as a, b_cm as b:
        _open_room(a, b)
        for msg, code in (({"seat": 1}, "block_bot"), ({"seat": 0}, "block_bad_seat"),
                          ({"seat": 7}, "block_bad_seat"), ({"seat": "2"}, "block_bad_seat")):
            a.send_json({"type": "block_player", **msg})
            assert _drain(a, "error")["code"] == code


def test_deleting_the_blocker_removes_its_blocks(client, blocks_on):
    from shengji.api import accounts

    ada, ada_cookie = _cookie(accounts, "g-a", "Ada Lovelace")
    bea, bea_cookie = _cookie(accounts, "g-b", "Bea Smith")
    a_cm, b_cm = _sit(client, ada_cookie, bea_cookie)
    with a_cm as a, b_cm as b:
        _open_room(a, b)
        a.send_json({"type": "block_player", "seat": 2, "on": True})
        _drain(a, "chat_history")
        b.send_json({"type": "block_player", "seat": 0, "on": True})
        _drain(b, "chat_history")
    assert accounts.STORE.blocked_ids(ada["id"]) == [bea["id"]]
    assert client.delete("/api/me", headers={"cookie": ada_cookie}).status_code == 204
    assert accounts.STORE.blocked_ids(bea["id"]) == []
    assert not blocks_on.hides(ada["id"], bea["id"])
    assert not blocks_on.hides(bea["id"], ada["id"])
    with accounts.STORE._open() as conn:
        assert conn.execute("SELECT COUNT(*) FROM blocks").fetchone()[0] == 0


def test_a_blocked_sender_is_left_out_of_a_waiting_tables_chat(blocks_on):
    from tests.test_matchmaking import Env, run

    async def go():
        env = Env()
        await env.join(1)
        await env.join(3, allow_joiners=False)           # alone, chatting
        await env.send(3, "table_chat", text="lone three")
        env.clock.advance(1.0)
        await env.send(1, "table_chat", text="first")
        env.clock.advance(1.0)
        await env.join(2)
        blocks_on.set_block(1, 3, True)
        await env.send(3, "table_allow_joiners", on=True)  # sits: its lines merge
        assert [m["text"] for m in env.conns[1].last("table_chat_history")["messages"]] == ["first"]
        assert [m["text"] for m in env.conns[2].last("table_chat_history")["messages"]] == [
            "lone three", "first"]
        await env.send(3, "table_chat", text="live three")
        assert env.conns[2].last("table_chat")["text"] == "live three"
        assert env.conns[1].last("table_chat")["text"] != "live three"
        # a guest (negative id) blocks the same way
        blocks_on.set_block(2, 1, True)
        await env.send(1, "table_chat", text="from one")
        assert env.conns[2].last("table_chat")["text"] == "live three"
        assert env.conns[3].last("table_chat")["text"] == "from one"
    run(go())


def test_a_snapshot_leaves_out_only_the_lines_of_senders_the_viewer_blocked():
    from shengji.api import blocks
    from shengji.api import server as srv

    blocks.reset()
    try:
        room = srv.Room(code="ABCD")
        viewer = srv.Seat(name="Ada", user_id=11)
        room.seats = [viewer]
        for i, (seat, sender) in enumerate(((0, 11), (2, 12), (None, None)), 1):
            room.chat.append({"seat": seat, "name": "x", "text": f"l{i}", "t": float(i),
                              "id": i, "room": "ABCD"})
            if sender is not None:
                room.chat_senders[i] = sender
        blocks.set_block(11, 12, True)
        assert [m["text"] for m in srv.chat_snapshot(room, viewer)["messages"]] == ["l1", "l3"]
        assert [m["text"] for m in srv.chat_snapshot(room, srv.Seat(name="Cy", user_id=13))
                ["messages"]] == ["l1", "l2", "l3"]
        assert srv.block_key(srv.Seat(name="Bot", is_bot=True)) is None
        guest = srv.Seat(name="G", device="e" * 24)
        assert srv.block_key(guest) == srv.guest_queue_id("e" * 24) < 0
        assert srv.block_key(srv.Seat(name="G")).startswith("seat:")
    finally:
        blocks.reset()


def _real_room_start(monkeypatch, env):
    """``env``'s matchmaker starts its rooms through the real
    ``start_matched_room``; only sockets, broadcasts and the game are stubbed."""
    from shengji.api import server as srv

    real_room = srv.Room
    monkeypatch.setattr(srv, "Room", lambda **kw: real_room(bot=object(), **kw))
    monkeypatch.setattr(srv, "rooms", {})
    monkeypatch.setattr(srv, "MATCHMAKER", env.mm)
    monkeypatch.setattr(srv, "_attach", lambda room, seat, ws: 0)

    async def noop(*args):
        pass

    monkeypatch.setattr(srv, "broadcast", noop)
    monkeypatch.setattr(srv, "handle_action", noop)
    monkeypatch.setattr(srv, "kick_bots", lambda room: None)
    env.mm.start_room = srv.start_matched_room
    return srv


def _snapshot_texts(srv, uid):
    (room,) = srv.rooms.values()
    viewer = next(s for s in room.seats if s is not None and s.queue_id == uid)
    return [m["text"] for m in srv.chat_snapshot(room, viewer)["messages"]]


@pytest.mark.parametrize("blocked", [2, 4])
def test_a_line_keeps_its_writer_across_a_seat_change_into_the_room(monkeypatch, blocks_on, blocked):
    """2 speaks and leaves, 4 takes 2's seat, the table starts: 1's room
    scrollback hides the line only if 1 blocked its writer, not whoever holds
    that seat now."""
    from tests.test_matchmaking import Env, run

    async def go():
        env = Env()
        for uid in (1, 2, 3):
            await env.join(uid)
        blocks_on.set_block(1, blocked, True)
        await env.send(2, "table_chat", text="said by two")
        await env.send(2, "queue_leave")
        await env.join(4)
        t = env.mm._entry(1).table
        assert t.seats[2] == 4
        await env.send(4, "table_chat", text="said by four")
        srv = _real_room_start(monkeypatch, env)
        for uid in (1, 3, 4):
            await env.send(uid, "table_start")
        mine = _snapshot_texts(srv, 1)
        hidden = "said by two" if blocked == 2 else "said by four"
        shown = "said by four" if blocked == 2 else "said by two"
        assert hidden not in mine and shown in mine
        assert {"said by two", "said by four"} <= set(_snapshot_texts(srv, 3))
        (room,) = srv.rooms.values()
        for line in room.chat:                  # the writer stays server-side
            assert set(line) == {"seat", "name", "text", "t", "id", "room"}
    run(go())


def test_a_duo_starting_alone_with_bots_keeps_each_lines_writer(monkeypatch, blocks_on):
    """The direct start (queue_start_bots) carries the writers too."""
    from tests.test_matchmaking import Env, run

    async def go():
        env = Env()
        await env.pair(3, 4)
        await env.send(3, "queue_join", allow_joiners=False)
        await env.send(4, "table_chat", text="partner line")
        await env.send(3, "table_chat", text="leader line")
        blocks_on.set_block(3, 4, True)
        srv = _real_room_start(monkeypatch, env)
        await env.send(3, "queue_start_bots")
        assert _snapshot_texts(srv, 3) == ["leader line"]
        assert _snapshot_texts(srv, 4) == ["partner line", "leader line"]
    run(go())
