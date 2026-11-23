"""UI telemetry: the allow-list, the caps, and a sink apart from the game logs."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from shengji.api import telemetry
from tests.test_accounts import accounts_on, keypair  # noqa: F401
from tests.test_device_accounts_link import _cookie, _device, _google, linking  # noqa: F401
from tests.test_server_ws import _drain, _room_with_bots, client  # noqa: F401


@pytest.fixture()
def sink(tmp_path, monkeypatch):
    out = tmp_path / "telemetry"
    monkeypatch.setenv("SHENGJI_TELEMETRY_DIR", str(out))
    return out


def _records_of(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def _records(directory: Path) -> list[dict]:
    rows: list[dict] = []
    for f in sorted(directory.glob("ui-*.jsonl")):
        rows.extend(json.loads(line) for line in f.read_text().splitlines())
    return rows


class _Sock:
    """A stand-in socket object: telemetry keeps its state on it."""


# allow-list

def test_unknown_fields_and_free_text_are_dropped():
    ev = telemetry.clean_event({"e": "tap", "t": 1200, "id": "play", "name": "Jerry",
                                "room": "ABCD", "card": "S5", "text": "hello"})
    assert ev == {"e": "tap", "t": 1200, "id": "play"}


@pytest.mark.parametrize("raw", [
    {"e": "tap", "id": "Jerry"},                          # not a known tap id
    {"e": "notice", "code": "You must follow suit."},     # server message text
    {"e": "notice", "code": "S5"},                        # a card code
    {"e": "screen", "name": "room ABCD"},
    {"e": "chat", "text": "hi"},                          # unknown event
    {"e": "ui_tap", "id": "play"},
    {"id": "play"},
    "tap",
])
def test_events_outside_the_allow_list_are_dropped(raw):
    assert telemetry.clean_event(raw) is None


def test_bounded_ints_refuse_bools_and_out_of_range():
    ev = telemetry.clean_event({"e": "turn_done", "phase": "play", "need": True,
                                "nth_turn": 31, "ms_total": -1, "sel_changes": 3,
                                "coach": 1, "by": "you", "lead": "pair"})
    assert ev == {"e": "turn_done", "phase": "play", "sel_changes": 3, "by": "you",
                  "lead": "pair"}


def test_connection_notices_keep_their_cause_and_time_down():
    down = telemetry.clean_event({"e": "notice", "t": 5, "code": "disconnected",
                                  "where": "table", "cause": "no_pong"})
    assert down == {"e": "notice", "t": 5, "code": "disconnected", "where": "table",
                    "cause": "no_pong"}
    back = telemetry.clean_event({"e": "notice", "code": "reconnected", "ms": 4400})
    assert back == {"e": "notice", "code": "reconnected", "ms": 4400}
    odd = telemetry.clean_event({"e": "notice", "code": "disconnected",
                                 "cause": "Wi-Fi at home", "ms": -1})
    assert odd == {"e": "notice", "code": "disconnected"}


def test_message_stamps_only_known_forms():
    events, stamps = telemetry.clean_message(
        {"type": "client_event", "v": 1, "form": "phone-land", "first_visit": True,
         "events": [{"e": "tap", "id": "next_round"}]})
    assert events == [{"e": "tap", "id": "next_round"}]
    assert stamps == {"form": "phone-land", "first_visit": True}
    _, stamps = telemetry.clean_message({"v": 1, "form": "Jerry's iPhone", "events": []})
    assert stamps == {}


# caps

def test_at_most_50_events_per_message():
    msg = {"v": 1, "events": [{"e": "tap", "id": "play"}] * 60}
    events, _ = telemetry.clean_message(msg, raw_bytes=100)
    assert len(events) == telemetry.MAX_EVENTS_PER_MESSAGE == 50


def test_a_message_over_2kb_is_dropped_whole():
    msg = {"v": 1, "events": [{"e": "tap", "id": "play", "pad": "x" * 2100}]}
    assert telemetry.clean_message(msg) == ([], {})
    assert telemetry.clean_message({"v": 1, "events": [{"e": "tap", "id": "play"}]})[0]


def test_wrong_version_is_dropped():
    assert telemetry.clean_message({"v": 2, "events": [{"e": "tap", "id": "play"}]}) == ([], {})


def test_600_events_per_socket_per_hour(sink):
    sock = _Sock()
    msg = {"v": 1, "events": [{"e": "tap", "id": "play"}] * 20}
    written = sum(telemetry.receive(sock, msg, "guest") for _ in range(40))
    assert written == telemetry.MAX_EVENTS_PER_HOUR == 600
    assert len(_records(sink)) == 600
    st = telemetry.state_for(sock)
    # a new hour; a second past it, since (t + 3600.0) - t can round below 3600.0
    assert st.take(5, now=st.window_start + telemetry.HOUR + 1) == 5


# sink

def test_sink_is_off_without_its_env_var(monkeypatch):
    monkeypatch.delenv("SHENGJI_TELEMETRY_DIR", raising=False)
    assert telemetry.telemetry_dir() is None
    assert telemetry.write([{"e": "tap", "id": "play"}]) is False


def test_sink_refuses_the_game_log_tree(tmp_path, monkeypatch):
    logs = tmp_path / "logs"
    monkeypatch.setenv("SHENGJI_LOG_DIR", str(logs))
    for inside in (logs, logs / "telemetry", Path("/data/logs"), Path("/data/logs/ui")):
        monkeypatch.setenv("SHENGJI_TELEMETRY_DIR", str(inside))
        assert telemetry.telemetry_dir() is None, inside
    monkeypatch.setenv("SHENGJI_TELEMETRY_DIR", str(tmp_path / "telemetry"))
    assert telemetry.telemetry_dir() == (tmp_path / "telemetry").resolve()


def test_records_are_date_named_and_carry_no_identity(sink):
    sock = _Sock()
    n = telemetry.receive(sock, {"v": 1, "form": "wide", "first_visit": False,
                                 "events": [{"e": "screen", "t": 5, "name": "table",
                                             "prev": "room", "ms_on_prev": 900}]},
                          "linked")
    assert n == 1
    (f,) = sink.glob("ui-*.jsonl")
    assert len(f.name) == len("ui-YYYYMMDD.jsonl")
    (rec,) = _records(sink)
    assert set(rec) == {"e", "t", "name", "prev", "ms_on_prev", "form", "first_visit",
                        "sid", "who", "build", "ts"}
    assert rec["who"] == "linked" and len(rec["sid"]) == 16


# retention

def _ts(day: str, hour: int = 12) -> float:
    from datetime import datetime, timezone
    return datetime.strptime(day, "%Y%m%d").replace(hour=hour, tzinfo=timezone.utc).timestamp()


def test_day_files_older_than_90_days_are_removed_and_newer_kept(sink, monkeypatch, caplog):
    monkeypatch.setattr(telemetry, "_pruned", None)
    sink.mkdir(parents=True)
    now = _ts("20261116")
    # day 20260817 ended exactly 90 days before 20261116 00:00, so it goes at
    # noon; 20260818 ends 12 h later and stays
    for day in ("20250101", "20260816", "20260817", "20260818", "20261115"):
        (sink / f"ui-{day}.jsonl").write_text('{"e":"tap"}\n')
    (sink / "notes.txt").write_text("not a day file")
    with caplog.at_level("INFO", logger="shengji.api.telemetry"):
        assert telemetry.write([{"e": "tap", "id": "play"}], now=now)
    assert sorted(p.name for p in sink.iterdir()) == [
        "notes.txt", "ui-20260818.jsonl", "ui-20261115.jsonl", "ui-20261116.jsonl"]
    assert "removed 3 day files" in caplog.text
    # once a day: a file that ages out later the same day waits for tomorrow
    (sink / "ui-20250102.jsonl").write_text("{}\n")
    telemetry.write([{"e": "tap", "id": "play"}], now=now + 3600)
    assert (sink / "ui-20250102.jsonl").exists()
    telemetry.write([{"e": "tap", "id": "play"}], now=now + telemetry.DAY)
    assert not (sink / "ui-20250102.jsonl").exists()
    assert telemetry.RETENTION_DAYS == 90


def test_a_retention_pass_is_bounded_and_the_backlog_drains_on_later_writes(sink, monkeypatch):
    monkeypatch.setattr(telemetry, "_pruned", None)
    monkeypatch.setattr(telemetry, "MAX_PRUNE_PER_PASS", 2)
    sink.mkdir(parents=True)
    for d in range(1, 6):
        (sink / f"ui-202501{d:02d}.jsonl").write_text("{}\n")
    assert telemetry.prune(sink, now=_ts("20261116"), limit=2) == (2, True)
    assert len(list(sink.glob("ui-2025*.jsonl"))) == 3
    now = _ts("20261116")
    telemetry.write([{"e": "tap", "id": "play"}], now=now)
    assert len(list(sink.glob("ui-2025*.jsonl"))) == 1
    telemetry.write([{"e": "tap", "id": "play"}], now=now + 1)
    assert list(sink.glob("ui-2025*.jsonl")) == []
    assert (sink / "ui-20261116.jsonl").exists()


def test_queue_events_share_the_socket_sid(sink):
    sock = _Sock()
    telemetry.receive(sock, {"v": 1, "events": [{"e": "tap", "id": "play"}]}, "guest")
    assert telemetry.queue_event(sock, "join", who="guest", size=1, wait=0.0, queued=3,
                                 name="Jerry")
    assert not telemetry.queue_event(sock, "chat")
    tap, q = _records(sink)
    assert q["sid"] == tap["sid"]
    assert q == {"e": "queue", "q": "join", "who": "guest", "size": 1, "wait": 0.0,
                 "queued": 3, "sid": tap["sid"], "build": q["build"], "ts": q["ts"]}


# over the socket

def test_client_events_reach_the_sink_and_never_a_room_log(client, sink, tmp_path,
                                                           monkeypatch):
    from shengji.api import server as srv

    async def paused_deal(room):
        await asyncio.Future()

    # Keep unrelated deal frames out of the telemetry dispatch barrier.
    monkeypatch.setattr(srv, "run_deal", paused_deal)

    kinds: list[str] = []
    real = srv.Room.log_event

    def spy(self, kind, **data):
        kinds.append(kind)
        return real(self, kind, **data)

    monkeypatch.setattr(srv.Room, "log_event", spy)
    with client.websocket_connect("/ws") as ws:
        _room_with_bots(ws)          # create_room starts the game: one state frame
        ws.send_json({"type": "client_event", "v": 1, "form": "phone",
                      "events": [{"e": "tap", "t": 10, "id": "table_start", "name": "jerry"},
                                 {"e": "screen", "t": 20, "name": "table", "prev": "room",
                                  "ms_on_prev": 4000}]})
        ws.send_json({"type": "ping", "nonce": 7})
        _drain(ws, "pong")
    rows = _records(sink)
    assert [r["e"] for r in rows] == ["tap", "screen"]
    assert all("name" not in r or r["e"] == "screen" for r in rows)
    assert all(r["who"] == "guest" and r["form"] == "phone" for r in rows)
    assert kinds and not [k for k in kinds if k.startswith("ui_") or k == "client_event"]
    logs = (tmp_path / "logs").resolve()
    assert logs not in sink.resolve().parents
    for f in logs.rglob("*"):
        if f.is_file():
            assert "client_event" not in f.read_text(errors="ignore")
            assert "table_start" not in f.read_text(errors="ignore")


# platform, account kind and the sign-in funnel

def test_platform_is_stamped_from_its_enum_and_anything_else_dropped():
    for platform in ("ios_app", "pwa", "web"):
        _, stamps = telemetry.clean_message({"v": 1, "platform": platform,
                                             "events": [{"e": "tap", "id": "play"}]})
        assert stamps == {"platform": platform}
    for bad in ("android", "iOS 18.2", "", 1, True, None, {"os": "ios"}):
        _, stamps = telemetry.clean_message({"v": 1, "platform": bad,
                                             "events": [{"e": "tap", "id": "play"}]})
        assert "platform" not in stamps, bad


def test_signin_open_keeps_its_entry_point_and_drops_any_other():
    for where in ("play_line", "chip", "me_row", "leaderboard_row", "round_end", "lapsed", "report"):
        assert telemetry.clean_event({"e": "tap", "id": "signin_open", "from": where}) == {
            "e": "tap", "id": "signin_open", "from": where}
    assert telemetry.clean_event({"e": "tap", "id": "signin_open", "from": "jerry@example.com"}) == {
        "e": "tap", "id": "signin_open"}


def test_signin_and_device_account_steps_are_enums_only():
    assert telemetry.clean_event({"e": "signin", "t": 3, "step": "done", "provider": "apple"}) == {
        "e": "signin", "t": 3, "step": "done", "provider": "apple"}
    for step in ("provider_tap", "error", "closed"):
        assert telemetry.clean_event({"e": "signin", "step": step})["step"] == step
    for step in ("created", "restored", "fell_back_guest", "linked", "conflict_shown", "switched"):
        assert telemetry.clean_event({"e": "device_account", "step": step}) == {
            "e": "device_account", "step": step}
    # a token, an email, a name or a message never survives; an unknown step drops the event
    assert telemetry.clean_event({"e": "signin", "step": "done", "provider": "facebook",
                                  "credential": "eyJhbGciOi", "email": "a@b.c",
                                  "name": "Mei", "message": "Sign-in rejected (nonce)."}) == {
        "e": "signin", "step": "done"}
    assert telemetry.clean_event({"e": "signin", "step": "eyJhbGciOi"}) is None
    assert telemetry.clean_event({"e": "signin", "provider": "google"}) is None
    assert telemetry.clean_event({"e": "device_account", "step": "created", "token": "abc"}) == {
        "e": "device_account", "step": "created"}
    assert telemetry.clean_event({"e": "device_account", "step": "deleted"}) is None


def test_who_is_one_of_three_and_anything_else_reads_as_guest(sink):
    sock = _Sock()
    for kind in ("guest", "device", "linked", "account", "user:7", None):
        telemetry.receive(sock, {"v": 1, "events": [{"e": "tap", "id": "play"}]}, kind)
    assert [r["who"] for r in _records(sink)] == [
        "guest", "device", "linked", "guest", "guest", "guest"]


def _who_over_the_socket(client, sink, cookie=None):
    headers = {"cookie": cookie} if cookie else {}
    client.cookies.clear()
    with client.websocket_connect("/ws", headers=headers) as ws:
        ws.send_json({"type": "client_event", "v": 1, "platform": "ios_app",
                      "events": [{"e": "tap", "id": "play"}]})
        ws.send_json({"type": "ping", "nonce": 1})
        _drain(ws, "pong")
    rec = [r for r in _records(sink) if r["e"] == "tap"][-1]
    assert rec["platform"] == "ios_app"
    return rec["who"]


def test_the_server_derives_who_from_the_handshake_account(linking, client, keypair, sink):  # noqa: F811
    assert _who_over_the_socket(client, sink) == "guest"
    _token, cookie, _user = _device(client)
    assert _who_over_the_socket(client, sink, cookie) == "device"
    resp = _google(client, keypair, cookie=cookie, sub="g-new")
    assert resp.status_code == 200
    assert _who_over_the_socket(client, sink, _cookie(resp)) == "linked"
    # no record carries an account id or anything from the account
    for rec in _records(sink):
        if rec["e"] == "tap":
            assert set(rec) == {"e", "id", "platform", "sid", "who", "build", "ts"}
        else:
            assert set(rec) == {"e", "provider", "new", "build"}


def test_a_successful_sign_in_is_counted_with_no_sid(linking, client, keypair, sink, monkeypatch):  # noqa: F811
    assert _google(client, keypair, sub="g-1").status_code == 200       # a new account
    assert _google(client, keypair, sub="g-1").status_code == 200       # the same one again
    _token, cookie, _user = _device(client)
    assert _google(client, keypair, cookie=cookie, sub="g-2").status_code == 200   # linked in place
    private_pem, _ = keypair
    from tests.test_accounts import _claims, _sign
    client.cookies.clear()
    bad = client.post("/api/auth/google", json={"credential": _sign(private_pem, _claims(sub="g-3"))[:-4]})
    assert bad.status_code == 401
    counts = [r for r in _records(sink) if r["e"] == "signin_count"]
    assert [(r["provider"], r["new"]) for r in counts] == [
        ("google", True), ("google", False), ("google", False)]
    # Apple counts the same way
    from tests import test_apple_signin as ta
    from tests.test_device_accounts_link import _apple
    import tests.test_device_accounts_link as tl
    _apple(monkeypatch)
    client.cookies.clear()
    resp = client.post("/api/auth/apple", json={
        "identity_token": ta._sign(tl._RSA, ta._claims(sub="apple-1")), "nonce": ta.RAW_NONCE})
    assert resp.status_code == 200
    assert [(r["provider"], r["new"]) for r in _records(sink) if r["e"] == "signin_count"][-1] == (
        "apple", True)
    for r in counts:
        assert set(r) == {"e", "provider", "new", "build"}


def test_the_sign_in_count_takes_only_its_enum_and_a_bool(sink):
    assert telemetry.signin_count("google", True)
    assert not telemetry.signin_count("facebook", True)
    assert not telemetry.signin_count("apple", 1)
    assert [r["provider"] for r in _records(sink)] == ["google"]


def test_an_identity_batch_is_kept_to_the_hour_whole_and_apart(sink, monkeypatch):
    now = 1_790_000_000.4                                          # 14:13:20 UTC
    monkeypatch.setattr(telemetry.time, "time", lambda: now)
    sock = _Sock()
    telemetry.receive(sock, {"v": 1, "events": [
        {"e": "screen", "t": 800, "name": "me"},
        {"e": "tap", "t": 900, "id": "signin_open", "from": "chip"},
        {"e": "signin", "t": 950, "step": "done", "provider": "google"},
        {"e": "tap", "t": 1000, "id": "play"},
    ]}, "guest")
    for one in ({"e": "device_account", "t": 990, "step": "created"},
                {"e": "tap", "t": 1, "id": "signin_open", "from": "me_row"}):
        telemetry.receive(sock, {"v": 1, "events": [{"e": "screen", "t": 5, "name": "play"}, one]}, "guest")
    telemetry.receive(sock, {"v": 1, "events": [{"e": "screen", "t": 1100, "name": "table"}]}, "guest")
    telemetry.signin_count("google", True)
    hour = 1_790_000_000 - 1_790_000_000 % 3600
    day = "20260921"
    plain = _records_of(sink / f"ui-{day}.jsonl")
    ident = _records_of(sink / f"ui-id-{day}.jsonl")
    # the batch with no identity event keeps its second and offsets, alone in the day file
    assert [(r["e"], r["ts"], r.get("t")) for r in plain] == [("screen", 1_790_000_000, 1100)]
    # every row of an identity batch, the screens and the play tap with it too,
    # carries the hour and no offset; nothing in the identity file has a second
    assert [(r["e"], r.get("id") or r.get("name") or r.get("step")) for r in ident] == [
        ("screen", "me"), ("tap", "signin_open"), ("signin", "done"), ("tap", "play"),
        ("screen", "play"), ("device_account", "created"), ("screen", "play"), ("tap", "signin_open"),
        ("signin_count", None)]
    for r in ident:
        assert "t" not in r
        assert r.get("ts", hour) == hour
    assert int((sink / f"ui-id-{day}.jsonl").stat().st_mtime) == hour


def test_a_quota_cut_identity_event_still_marks_the_rows_kept(sink, monkeypatch):
    now = 1_790_000_000.4
    monkeypatch.setattr(telemetry.time, "time", lambda: now)
    sock = _Sock()
    st = telemetry.state_for(sock)
    st.take(telemetry.MAX_EVENTS_PER_HOUR - 1)                    # one slot left this hour
    telemetry.receive(sock, {"v": 1, "events": [
        {"e": "screen", "t": 800, "name": "me"},
        {"e": "signin", "t": 950, "step": "done", "provider": "google"},
    ]}, "guest")
    hour = 1_790_000_000 - 1_790_000_000 % 3600
    day = "20260921"
    assert not (sink / f"ui-{day}.jsonl").exists()
    ident = _records_of(sink / f"ui-id-{day}.jsonl")
    assert [(r["e"], r["ts"], r.get("t")) for r in ident] == [("screen", hour, None)]


def test_an_identity_batch_over_the_socket_keeps_no_second(client, sink):  # noqa: F811
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "client_event", "v": 1, "events": [
            {"e": "screen", "t": 10, "name": "name_sheet"},
            {"e": "signin", "t": 20, "step": "provider_tap", "provider": "apple"}]})
        ws.send_json({"type": "client_event", "v": 1, "events": [{"e": "tap", "t": 30, "id": "play"}]})
        ws.send_json({"type": "ping", "nonce": 1})
        _drain(ws, "pong")
    (ident_file,) = sink.glob("ui-id-*.jsonl")
    ident = _records_of(ident_file)
    assert [r["e"] for r in ident] == ["screen", "signin"]
    assert all("t" not in r and r["ts"] % 3600 == 0 for r in ident)
    (plain_file,) = sink.glob("ui-2*.jsonl")
    assert [(r["e"], r["t"]) for r in _records_of(plain_file)] == [("tap", 30)]


@pytest.mark.parametrize("provider", ["google", "apple"])
def test_two_simultaneous_first_sign_ins_make_one_new_account(tmp_path, provider):
    import threading

    from shengji.api import accounts
    from tests.test_accounts import _claims
    store = accounts.Store(tmp_path / "accounts.sqlite3")
    store.schema_version()
    start = threading.Barrier(2)
    results: list[tuple[dict, bool]] = []

    def sign_in() -> None:
        start.wait()
        if provider == "google":
            got = store.upsert_user_outcome(_claims(sub="g-race"), unique_name=False)
        else:
            got = store.upsert_apple_user_outcome("apple-race", None, "Race", unique_name=False)
        results.append(got)

    threads = [threading.Thread(target=sign_in) for _ in range(2)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert sorted(new for _user, new in results) == [False, True]
    assert len({user["id"] for user, _new in results}) == 1
    # the plain upserts still return the row alone, and an existing account is not new
    if provider == "google":
        assert store.upsert_user(_claims(sub="g-race"))["id"] == results[0][0]["id"]
        assert store.upsert_user_outcome(_claims(sub="g-race"))[1] is False
    else:
        assert store.upsert_apple_user("apple-race", None, None)["id"] == results[0][0]["id"]
        assert store.upsert_apple_user_outcome("apple-race", None, None)[1] is False
