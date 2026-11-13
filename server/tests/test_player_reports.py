"""Player reports (``report_player``, ``shengji.api.reports``).

A report is stored as one JSON line with the room, round, both seats and the
last chat lines; a guest reporter, a bot or guest target, a bad seat or
reason, and a reporter over the hourly limit are refused and store nothing.
The socket test drives the real message through ``/ws``.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from tests.test_server_ws import _drain, client  # noqa: F401


@pytest.fixture()
def reports_on(tmp_path, monkeypatch):
    """A private data dir, a private accounts store and a fresh limiter."""
    from shengji.api import accounts, reports

    monkeypatch.setenv("SHENGJI_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(accounts, "STORE", accounts.Store(tmp_path / "data" / "accounts.sqlite3"))
    monkeypatch.setattr(reports, "LIMITER", accounts.RateLimiter(limit=5, window=3600.0))
    return reports


def _stored(reports) -> list[dict]:
    path = reports.reports_path()
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text("utf-8").splitlines()]


def _seat(name, user_id=None, is_bot=False):
    return SimpleNamespace(name=name, user_id=user_id, is_bot=is_bot)


def _room(chat_lines=25):
    chat = [{"seat": i % 4, "name": f"p{i % 4}", "text": f"line {i}", "t": float(i), "id": i + 1,
             "room": "ABCD"} for i in range(chat_lines)]
    return SimpleNamespace(code="ABCD", matched=True, game=SimpleNamespace(round_no=3),
                           seats=[_seat("Ada", 11), _seat("Bot 1", is_bot=True),
                                  _seat("Bea", 12), _seat("Guest")],
                           chat=chat)


def test_a_report_stores_room_round_both_seats_and_the_last_twenty_lines(reports_on):
    from shengji.api import accounts

    reporter = accounts.STORE.upsert_user({"sub": "g-1", "email": "a@example.com", "name": "Ada Lovelace"})
    target = accounts.STORE.upsert_user({"sub": "g-2", "email": "b@example.com", "name": "Bea Smith"})
    room = _room()
    room.seats[0].user_id, room.seats[2].user_id = reporter["id"], target["id"]
    record = reports_on.build(room, 0, reporter["id"], {"seat": 2, "reason": "abuse"}, now=100.0)
    reports_on.store(record)
    [rec] = _stored(reports_on)
    assert rec["room"] == "ABCD" and rec["round"] == 3 and rec["matched"] is True
    assert rec["reason"] == "abuse" and rec["ts"] == 100.0
    assert rec["reporter"] == {"seat": 0, "name": "Ada", "account_id": reporter["id"],
                               "account_name": "Ada"}
    assert rec["reported"] == {"seat": 2, "name": "Bea", "account_id": target["id"],
                               "account_name": "Bea"}
    assert [line["text"] for line in rec["chat"]] == [f"line {i}" for i in range(5, 25)]
    assert set(rec["chat"][0]) == {"seat", "name", "text", "t"}
    assert reports_on.reports_path().name == "player_reports.jsonl"


@pytest.mark.parametrize("reporter_account, msg, code", [
    (None, {"seat": 2, "reason": "abuse"}, "report_sign_in"),
    (11, {"seat": 1, "reason": "abuse"}, "report_bot"),
    (11, {"seat": 3, "reason": "abuse"}, "report_guest"),
    (11, {"seat": 0, "reason": "abuse"}, "report_bad_seat"),
    (11, {"seat": 4, "reason": "abuse"}, "report_bad_seat"),
    (11, {"seat": True, "reason": "abuse"}, "report_bad_seat"),
    (11, {"seat": "2", "reason": "abuse"}, "report_bad_seat"),
    (11, {"seat": 2, "reason": "rude"}, "report_bad_reason"),
    (11, {"seat": 2}, "report_bad_reason"),
])
def test_refused_reports_store_nothing_and_spend_no_budget(reports_on, reporter_account, msg, code):
    with pytest.raises(reports_on.ReportRefused) as refused:
        reports_on.build(_room(), 0, reporter_account, msg)
    assert refused.value.code == code
    assert _stored(reports_on) == []
    for _ in range(5):
        reports_on.build(_room(), 0, 11, {"seat": 2, "reason": "spam"})


def test_reports_are_limited_per_account(reports_on):
    room = _room()
    for i in range(5):
        reports_on.build(room, 0, 11, {"seat": 2, "reason": "spam"}, now=1000.0 + i)
    with pytest.raises(reports_on.ReportRefused) as refused:
        reports_on.build(room, 0, 11, {"seat": 2, "reason": "spam"}, now=1010.0)
    assert refused.value.code == "report_rate_limited"
    # another account has its own budget, and the window frees the first
    reports_on.build(room, 2, 12, {"seat": 0, "reason": "spam"}, now=1010.0)
    reports_on.build(room, 0, 11, {"seat": 2, "reason": "spam"}, now=1000.0 + 3600.5)


def _cookie(accounts, sub, name):
    user = accounts.STORE.upsert_user({"sub": sub, "email": f"{sub}@example.com", "name": name})
    return user, f"{accounts.COOKIE}={accounts.STORE.create_session(user['id'])}"


def test_report_over_the_socket_is_stored_and_confirmed_to_the_reporter(client, reports_on):
    from shengji.api import accounts
    from shengji.api import server as srv

    ada, ada_cookie = _cookie(accounts, "g-a", "Ada Lovelace")
    bea, bea_cookie = _cookie(accounts, "g-b", "Bea Smith")
    with client.websocket_connect("/ws", headers={"cookie": ada_cookie}) as a, \
            client.websocket_connect("/ws", headers={"cookie": bea_cookie}) as b:
        a.send_json({"type": "create_room", "name": "Ada"})
        code = _drain(a, "room")["room"]
        b.send_json({"type": "join_room", "room": code, "name": "Bea"})
        _drain(b, "room")
        a.send_json({"type": "add_bot"})
        b.send_json({"type": "chat", "text": "you are terrible"})
        _drain(a, "chat")
        # Bea joined in the host's partner seat; the bot took seat 1
        a.send_json({"type": "report_player", "seat": 2, "reason": "abuse"})
        ack = _drain(a, "report_received")
        assert ack["seat"] == 2 and "Bea" in ack["message"]
        a.send_json({"type": "report_player", "seat": 1, "reason": "abuse"})
        err = _drain(a, "error")
        assert err["code"] == "report_bot"
    [rec] = _stored(reports_on)
    assert rec["room"] == code
    assert rec["reporter"]["account_id"] == ada["id"]
    assert rec["reported"]["account_id"] == bea["id"] and rec["reported"]["name"] == "Bea"
    assert any(line["text"] == "you are terrible" for line in rec["chat"])
    assert code in srv.rooms


def test_a_guest_cannot_report_over_the_socket(client, reports_on):
    from shengji.api import accounts

    _, bea_cookie = _cookie(accounts, "g-b", "Bea Smith")
    with client.websocket_connect("/ws") as a, \
            client.websocket_connect("/ws", headers={"cookie": bea_cookie}) as b:
        a.send_json({"type": "create_room", "name": "Guest"})
        code = _drain(a, "room")["room"]
        b.send_json({"type": "join_room", "room": code, "name": "Bea"})
        _drain(b, "room")
        a.send_json({"type": "report_player", "seat": 1, "reason": "abuse"})
        assert _drain(a, "error")["code"] == "report_sign_in"
        # and a signed-in player cannot report a guest
        b.send_json({"type": "report_player", "seat": 0, "reason": "abuse"})
        assert _drain(b, "error")["code"] == "report_guest"
    assert _stored(reports_on) == []
