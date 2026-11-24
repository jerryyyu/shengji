"""The online soak harness (scripts/online_soak): its loopback-only guard, its
copy of the page's connection constants, its fault proxy, and the checks
behind its verdict, each on a constructed case. The soak run itself is a
script run by hand (``soak.py``), not a test."""
from __future__ import annotations

import argparse
import asyncio
import re
import socket
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server" / "scripts" / "online_soak"))

import audit  # noqa: E402
import client  # noqa: E402
import soak  # noqa: E402
from localonly import NotLocal, require_local, require_not_deployed, ws_url  # noqa: E402
from proxy import DOWN, UP, FaultProxy  # noqa: E402


@pytest.mark.parametrize("target", [
    "127.0.0.1", "localhost", "::1", "[::1]:8000", "127.0.0.1:8765",
    "ws://127.0.0.1:9/ws?device=x", "http://localhost:8000/healthz", "ws://[::1]:9/ws",
])
def test_loopback_is_accepted(target):
    assert require_local(target) == target


@pytest.mark.parametrize("target", [
    "wss://shengji.fly.dev/ws", "https://shengji.fly.dev", "ws://shengji.fly.dev/ws",
    "http://10.0.0.5:8000", "0.0.0.0", "192.168.1.2:8000", "example.com", "",
    "ws://127.0.0.1.example.com/ws", "ftp://127.0.0.1/",
])
def test_anything_else_is_refused(target):
    with pytest.raises(NotLocal):
        require_local(target)


def test_a_fly_machine_refuses_to_run(monkeypatch):
    monkeypatch.delenv("FLY_APP_NAME", raising=False)
    require_not_deployed()
    monkeypatch.setenv("FLY_APP_NAME", "shengji")
    with pytest.raises(NotLocal):
        require_not_deployed()


def test_the_soak_cli_refuses_a_non_local_bind_before_starting():
    with pytest.raises(NotLocal):
        soak.main(["--host", "0.0.0.0", "--minutes", "0.01"])


def _ws_ts() -> str:
    return (ROOT / "web" / "src" / "ws.ts").read_text(encoding="utf-8")


@pytest.mark.parametrize("name", ["TABLE_PING_MS", "TABLE_PONG_MS", "ANSWER_MS", "ACTION_PONG_MS",
                                  "CONNECT_MS", "LONG_LIVED_MS", "TABLE_RETRY_MAX_MS", "PROBE_MS"])
def test_the_client_model_keeps_the_page_s_timing(name):
    found = re.search(rf"const {name} = ([\d_]+);", _ws_ts())
    assert found, f"{name} is gone from ws.ts: update online_soak/client.py"
    assert getattr(client, name) == int(found.group(1).replace("_", "")), \
        f"ws.ts {name} changed: update online_soak/client.py to match"


def test_the_client_model_waits_on_the_same_answered_actions():
    block = re.search(r"const ANSWERED[^=]*= new Set<[^>]*>\(\[(.*?)\]\)", _ws_ts(), re.S)
    assert block
    assert set(re.findall(r'"([a-z_]+)"', block.group(1))) == set(client.ANSWERED)


def test_a_frame_key_names_one_decision_whatever_the_card_shape():
    trick = {"plays": [{"seat": 1, "cards": ["H5", "H5"]}]}
    as_objects = {"plays": [{"seat": 1, "cards": [{"code": "H5"}, {"code": "H5"}]}]}
    assert client.frame_key(["SA", "D3"], trick) == client.frame_key(["D3", "SA"], as_objects)
    assert client.frame_key(["SA"], None) != client.frame_key(["SA"], trick)


def _with_echo(test):
    async def run():
        async def echo(reader, writer):
            while data := await reader.read(4096):
                writer.write(data)
                await writer.drain()
            writer.close()
        server = await asyncio.start_server(echo, "127.0.0.1", 0)
        port = server.sockets[0].getsockname()[1]
        proxy = FaultProxy(port)
        try:
            await test(proxy, await proxy.start())
        finally:
            await proxy.close()
            server.close()
    asyncio.run(run())


def test_the_proxy_passes_bytes_and_a_pause_holds_them_until_it_ends():
    async def test(proxy, port):
        r, w = await asyncio.open_connection("127.0.0.1", port)
        w.write(b"one")
        assert await asyncio.wait_for(r.read(3), 2) == b"one"
        proxy.pause(DOWN)
        w.write(b"two")
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(r.read(3), 0.3)
        proxy.resume()
        assert await asyncio.wait_for(r.read(3), 2) == b"two"
        proxy.pause(UP)
        w.write(b"six")
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(r.read(3), 0.3)
        proxy.resume()
        assert await asyncio.wait_for(r.read(3), 2) == b"six"
        w.close()
    _with_echo(test)


def test_a_cut_resets_the_connection_and_the_next_one_goes_through():
    async def test(proxy, port):
        r, w = await asyncio.open_connection("127.0.0.1", port)
        w.write(b"hi")
        assert await asyncio.wait_for(r.read(2), 2) == b"hi"
        proxy.cut()
        got = await asyncio.wait_for(r.read(2), 2)
        assert got == b""
        r2, w2 = await asyncio.open_connection("127.0.0.1", port)
        w2.write(b"ok")
        assert await asyncio.wait_for(r2.read(2), 2) == b"ok"
        assert proxy.connections == 2
        w2.close()
    _with_echo(test)


# one loopback family end to end

def test_the_soak_cli_refuses_localhost_whose_family_is_ambiguous():
    with pytest.raises(NotLocal):
        soak.main(["--host", "localhost", "--minutes", "0.01"])


def test_a_proxy_refuses_to_listen_on_one_family_and_dial_the_other():
    with pytest.raises(NotLocal):
        FaultProxy(9, "::1", listen_host="127.0.0.1")
    with pytest.raises(NotLocal):
        FaultProxy(9, "127.0.0.1", listen_host="::1")
    assert FaultProxy(9, "::1").listen_host == "::1"


def test_a_client_dials_the_run_s_family():
    assert ws_url("::1", 9, "/ws") == "ws://[::1]:9/ws"
    assert ws_url("127.0.0.1", 9, "/ws") == "ws://127.0.0.1:9/ws"
    c = client.SoakClient("a", "d", 9, 1.0, None, None, None, host="::1")
    assert c.url.startswith("ws://[::1]:9/")


def _ipv6_loopback() -> bool:
    try:
        with socket.socket(socket.AF_INET6) as s:
            s.bind(("::1", 0))
        return True
    except OSError:
        return False


@pytest.mark.skipif(not _ipv6_loopback(), reason="no IPv6 loopback on this machine")
def test_an_ipv6_run_passes_bytes_through_its_proxy():
    async def run():
        async def echo(reader, writer):
            while data := await reader.read(4096):
                writer.write(data)
                await writer.drain()
            writer.close()
        server = await asyncio.start_server(echo, "::1", 0)
        proxy = FaultProxy(server.sockets[0].getsockname()[1], "::1")
        try:
            port = await proxy.start()
            r, w = await asyncio.open_connection("::1", port)
            w.write(b"v6")
            assert await asyncio.wait_for(r.read(2), 2) == b"v6"
            w.close()
        finally:
            await proxy.close()
            server.close()
    asyncio.run(run())


# per-client addresses for the server's per-address limits

def test_each_client_names_its_own_address_and_the_server_keys_limits_by_it():
    from shengji.api import accounts
    a = client.SoakClient("a", "d1", 9, 1.0, None, None, None, client_ip=soak.client_ip(1))
    b = client.SoakClient("b", "d2", 9, 1.0, None, None, None, client_ip=soak.client_ip(2))
    assert a.headers["Fly-Client-IP"] != b.headers["Fly-Client-IP"]
    peer = SimpleNamespace(host="127.0.0.1")
    keys = {accounts.client_ip(SimpleNamespace(headers={k.lower(): v for k, v in c.headers.items()},
                                               client=peer)) for c in (a, b)}
    assert keys == {soak.client_ip(1), soak.client_ip(2)}
    shared = client.SoakClient("c", "d3", 9, 1.0, None, None, None)
    assert shared.headers == {}
    assert accounts.client_ip(SimpleNamespace(headers={}, client=peer)) == "127.0.0.1"


# the verdict: every fault accounted for, and a thin run is not a PASS

def _bare_soak(tmp_path, **floors) -> "soak.Soak":
    s = soak.Soak.__new__(soak.Soak)
    s.args = argparse.Namespace(host="127.0.0.1", shared_client_ip=False, min_rooms=floors.get("rooms", 3),
                                min_rounds=floors.get("rounds", 10), min_recoveries=floors.get("recoveries", 20),
                                min_resolved_share=floors.get("share", 0.8), min_faults=floors.get("faults", 0))
    s.rounds_logged = 0
    s.scale, s.clients, s.tmp = 4.0, [], tmp_path
    s.ledger, s.plays = audit.FaultLedger(), audit.PlayAudit()
    s.strikes, s.stuck, s.double, s.socket_faults, s.writer_errors = [], [], [], [], []
    s.writer_disconnects = []
    s.task_exits, s.harness_errors, s.refused, s.rooms_seen = [], [], {}, set()
    s.srv = SimpleNamespace(rooms={})
    return s


def test_one_dropped_fault_with_no_workload_is_not_a_pass(tmp_path):
    s = _bare_soak(tmp_path)
    s.ledger.open("drop", "Soak-1", 0.0)
    s.ledger.censor_open("shutdown")
    out = s.report(60.0)
    assert out["fault_ledger"]["censored"] == 1 and out["fault_ledger"]["open"] == 0
    assert out["verdict"]["status"] == "INCONCLUSIVE"
    assert set(out["verdict"]["under_floor"]) == {"rooms", "rounds", "recoveries", "resolved_share"}


def test_a_failed_fault_or_a_harness_error_fails_the_run_whatever_the_coverage(tmp_path):
    s = _bare_soak(tmp_path, rooms=0, rounds=0, recoveries=0, share=0.0)
    rec = s.ledger.open("stall", "Soak-1", 0.0)
    audit.FaultLedger.close(rec, "failed", reason="deadline")
    assert s.report(60.0)["verdict"]["failed"] == ["faults_failed"]
    s = _bare_soak(tmp_path, rooms=0, rounds=0, recoveries=0, share=0.0)
    s.harness_errors.append({"task": "chaos Soak-1", "error": "KeyError: 3"})
    assert s.report(60.0)["verdict"]["status"] == "FAIL"
    s = _bare_soak(tmp_path, rooms=0, rounds=0, recoveries=0, share=0.0)
    s.clients = [SimpleNamespace(name="Soak-1", rec=client.ClientRecord(errors={"rate_limited": 3}))]
    out = s.report(60.0)
    assert out["unexpected_refusals"] == ["rate_limited"] and out["verdict"]["status"] == "FAIL"


def test_a_covered_clean_run_passes(tmp_path):
    s = _bare_soak(tmp_path, rooms=1, rounds=0, recoveries=1, share=0.5)
    s.rooms_seen = {"R1"}
    rec = s.ledger.open("drop", "Soak-1", 0.0)
    audit.FaultLedger.close(rec, "recovered", secs=0.4)
    assert s.report(60.0)["verdict"]["status"] == "PASS"


def test_round_floor_counts_only_successfully_logged_round_end_events(tmp_path):
    from shengji.api import server

    class Room(server.Room):
        pass

    s = _bare_soak(tmp_path, rounds=2)
    s.progress = {}
    s.srv = SimpleNamespace(Room=Room, handle_action=server.handle_action,
                            _count_timeout=server._count_timeout, _sync_move_timer=server._sync_move_timer)
    s._hook()
    room = Room(code="SOAK", bot=object(), log_dir=tmp_path)
    assert room.log_event("round_end") == 0
    room.log_event("chat", seat=0, text="round_end")
    room.log_event("play_refused", seat=0, phase="round_end")
    assert s.report(1, brief=True)["rounds_logged"] == 1
    room.log_dir = tmp_path / "SOAK.jsonl"
    assert room.log_event("round_end") is None
    assert "rounds" in s.report(1)["verdict"]["under_floor"]
    room.log_dir = tmp_path
    room.log_event("round_end")
    assert "rounds" not in s.report(1)["verdict"]["under_floor"]


def test_fault_floor_includes_censored_injections(tmp_path):
    s = _bare_soak(tmp_path, rooms=0, rounds=0, recoveries=1, share=0.5, faults=2)
    fault = s.ledger.open("drop", "Soak-1", 0)
    audit.FaultLedger.close(fault, "recovered", secs=1.0)
    assert s.report(1)["verdict"]["under_floor"] == ["faults"]
    s.ledger.open("stall", "Soak-1", 2)
    s.ledger.censor_open("shutdown")
    assert s.report(3)["verdict"]["status"] == "PASS"


def test_a_fault_closes_once():
    led = audit.FaultLedger()
    rec = led.open("drop", "a", 0.0)
    audit.FaultLedger.close(rec, "recovered", secs=1.0)
    audit.FaultLedger.close(rec, "failed")
    led.censor_open()
    assert led.summary()["recovered"] == 1 and led.summary()["failed"] == 0
    with pytest.raises(ValueError):
        audit.FaultLedger.close(led.open("x", "a", 0.0), "fine")


# recovery needs a post-fault state for that seat

_ST = {"room": "R1", "you": 2, "phase": "play", "turn": 2,
       "hand": [{"id": 7, "code": "SA"}, {"id": 8, "code": "D3"}], "trick": None}


def _recovered(**kw):
    base = dict(fault_end=10.0, state_at=11.0, client_view=audit.state_view(_ST),
                server_view=audit.state_view(_ST), ws_open=True, seat_connected=True, seat_bot=False)
    return audit.recovered(**{**base, **kw})


def test_a_surviving_socket_with_only_a_pre_fault_state_is_not_recovered():
    # the only state is from 9.0, before the fault that ended at 10.0
    assert _recovered(state_at=9.0) is None
    # a pong at 12.0 on a surviving socket, but the server has moved on: stale
    assert _recovered(state_at=9.0, rx_at=12.0, same_socket=True,
                      server_view=audit.state_view({**_ST, "turn": 3})) is None
    # a pong on a replaced socket proves nothing about the pre-fault state
    assert _recovered(state_at=9.0, rx_at=12.0, same_socket=False) is None
    # no frame through the surviving socket since the fault
    assert _recovered(state_at=9.0, rx_at=9.5, same_socket=True) is None
    assert _recovered() == "state"
    # the surviving socket answered since the fault and the held state is the server's decision
    assert _recovered(state_at=9.0, rx_at=12.0, same_socket=True) == "same_socket"


def test_a_post_fault_state_that_is_not_the_server_s_decision_is_not_recovered():
    later = {**_ST, "turn": 3}
    assert _recovered(server_view=audit.state_view(later)) is None
    assert _recovered(client_view=audit.state_view({**_ST, "you": 1})) is None
    assert _recovered(seat_connected=False) is None
    assert _recovered(ws_open=False) is None
    assert _recovered(server_view=None) is None


# a play is checked against the decision of its first send

_T1 = {"plays": [{"seat": 1, "cards": ["H5"]}]}
_T2 = {"plays": [{"seat": 1, "cards": ["C9"]}]}


def _client_that_sent_at(trick):
    c = client.SoakClient("Soak-1", "d1", 9, 1.0, None, None, None)
    wire = []

    async def send(msg):
        wire.append(msg)
        return True
    c._send = send
    c.gen, c.room, c.seat = 1, "R1", 2
    c.state = {**_ST, "trick": trick}
    p = client.Pending("play", [7], ["SA"], (7, 8), 2, 1, did=1, key=audit.frame_key(["SA", "D3"], trick))
    c.pending = p
    wire.append(c._play_msg(p))
    return c, wire


def test_a_resend_after_the_trick_changed_is_flagged_even_with_the_same_cards():
    async def run():
        c, wire = _client_that_sent_at(_T1)
        c.gen = 2                                   # a new socket
        c._on_state({**_ST, "trick": _T2})          # same hand ids and turn, a different trick
        await asyncio.sleep(0)
        return c, wire
    c, wire = asyncio.run(run())
    assert len(wire) == 2 and wire[0]["card_ids"] == wire[1]["card_ids"]
    first, again = wire[0]["_soak"], wire[1]["_soak"]
    assert first["did"] == again["did"] and (first["gen"], again["gen"]) == (1, 2)
    assert c.rec.sent[1].resend and c.rec.sent[1].key == c.rec.sent[0].key
    plays = audit.PlayAudit()
    assert plays.check(c.name, c.rec.sent, again, audit.frame_key(["SA", "D3"], _T2)) == "stale_decision"


def test_a_resend_applied_at_its_own_decision_is_right():
    async def run():
        c, wire = _client_that_sent_at(_T1)
        c.gen = 2
        c._on_state({**_ST, "trick": _T1})
        await asyncio.sleep(0)
        return c, wire
    c, wire = asyncio.run(run())
    plays = audit.PlayAudit()
    assert plays.check(c.name, c.rec.sent, wire[1]["_soak"], audit.frame_key(["SA", "D3"], _T1)) is None
    # the same decision cannot apply twice, an untagged or unsent play is wrong
    assert plays.check(c.name, c.rec.sent, wire[0]["_soak"], audit.frame_key(["SA", "D3"], _T1)) == "applied_twice"
    assert plays.check(c.name, c.rec.sent, None, ()) == "untagged"
    assert plays.check(c.name, c.rec.sent, {"did": 1, "gen": 9, "seq": 1}, ()) == "never_sent"


def test_sends_on_one_socket_apply_in_order():
    S = client.Sent
    sends = [S("play", [1], ["SA"], ("k1",), 0.0, did=1, gen=1, seq=1),
             S("play", [2], ["SK"], ("k2",), 0.0, did=2, gen=1, seq=2)]
    plays = audit.PlayAudit()
    assert plays.check("a", sends, {"did": 2, "gen": 1, "seq": 2}, ("k2",)) is None
    assert plays.check("a", sends, {"did": 1, "gen": 1, "seq": 1}, ("k1",)) == "out_of_order"


# one owner, one human seat, across every room; connected seats on live sockets

def _seat(name, device=None, **kw):
    base = dict(name=name, device=device, is_bot=False, left_by_choice=False, removed=False, connected=True,
                ws=object(), writer=SimpleNamespace(done=lambda: False), writer_exit=None, writer_error=None)
    return SimpleNamespace(**{**base, **kw})


def _bot():
    return _seat("Bot", is_bot=True, connected=False, ws=None, writer=None)


def test_a_device_seated_in_two_rooms_is_flagged(tmp_path):
    s = _bare_soak(tmp_path)
    s.srv.rooms = {"R1": SimpleNamespace(seats=[_seat("Soak-1", "dev1"), _bot(), _bot(), _bot()]),
                   "R2": SimpleNamespace(seats=[_bot(), _seat("Soak-1", "dev1"), _bot(), _bot()])}
    s._check_seats({})
    assert s.double == [{"owner": "dev1", "seats": [("R1", 0), ("R2", 1)]}]


def test_a_seat_its_owner_left_does_not_count_as_held(tmp_path):
    s = _bare_soak(tmp_path)
    s.srv.rooms = {"R1": SimpleNamespace(seats=[_seat("Soak-1", "dev1", left_by_choice=True), _bot(), _bot(), _bot()]),
                   "R2": SimpleNamespace(seats=[_bot(), _seat("Soak-1", "dev1"), _bot(), _bot()])}
    s._check_seats({})
    assert s.double == []


def test_a_connected_seat_without_a_live_writer_or_socket_is_flagged_when_it_holds(tmp_path):
    s = _bare_soak(tmp_path)
    dead = SimpleNamespace(done=lambda: True)
    s.srv.rooms = {"R1": SimpleNamespace(seats=[_seat("Soak-1", writer=dead), _seat("Soak-2", ws=None),
                                                _seat("Soak-3", writer_exit="error", writer_error="OSError: x"),
                                                _seat("Soak-4", connected=False, ws=None, writer_exit="error",
                                                      writer_error="WebSocketDisconnect: ")])}
    seen: dict = {}
    s._check_seats(seen)
    assert s.socket_faults == [] and len(s.writer_errors) == 1
    s._check_seats(seen)
    assert {(f["seat"], f["fault"]) for f in s.socket_faults} == {
        (0, "connected_without_writer"), (1, "connected_without_socket")}
    assert len(s.writer_errors) == 1 and len(s.writer_disconnects) == 1


# a fault is resolved against the seat it hit, through chaos -> _recovered -> FaultLedger

class _Proxy:
    delay = 0.0

    def cut(self):
        pass

    def pause(self, *d):
        pass

    def resume(self):
        pass


class _WS:
    async def send(self, raw):
        return None


def _table(code, seat_no, owner):
    seats = [_bot() for _ in range(4)]
    seats[seat_no] = _seat("Soak-1", owner)
    rnd = SimpleNamespace(phase="play", turn=seat_no, hands={seat_no: ["SA", "D3"]}, trick=None, ordering=None)
    return SimpleNamespace(code=code, game=SimpleNamespace(game_over=False), round=rnd, seats=seats)


def _frame(code, seat_no):
    return {"room": code, "you": seat_no, "phase": "play", "turn": seat_no, "trick": None,
            "hand": [{"id": 7, "code": "SA"}, {"id": 8, "code": "D3"}]}


def _run_one_fault(tmp_path, monkeypatch, during):
    """One stall on the client seated at AAAA seat 2; ``during(soak, client)``
    runs inside the outage. Returns the closed ledger record."""
    monkeypatch.setattr(soak, "FAULTS", ("stall",))
    monkeypatch.setattr(soak, "STALL_SECS", (0.2,))
    s = _bare_soak(tmp_path)
    s.scale = 1.0
    s.args.fault_gap = (0.0, 0.0)
    s.rng = __import__("random").Random(1)
    s.srv = SimpleNamespace(rooms={"AAAA": _table("AAAA", 2, "dev1")}, trick_json=lambda t, o: t)
    c = client.SoakClient("Soak-1", "dev1", 9, 1.0, None, None, None)
    c.ws, c.gen, c.room, c.seat = _WS(), 1, "AAAA", 2
    c.state, c.state_at, c.state_gen = _frame("AAAA", 2), 0.0, c.gen

    async def run():
        import time as _t
        until = _t.monotonic() + 5
        task = asyncio.create_task(s.chaos(c, _Proxy(), until))
        await asyncio.sleep(0.05)
        await during(s, c)
        while not s.ledger.faults or s.ledger.faults[0]["outcome"] is None:
            await asyncio.sleep(0.02)
        c.stop = True
        task.cancel()
    asyncio.run(run())
    return s.ledger.faults[0]


def _fresh(c, code, seat_no):
    import time as _t
    c.state_gen = c.gen
    c.state, c.state_at, c.last_rx = _frame(code, seat_no), _t.monotonic() + 1.0, _t.monotonic() + 1.0


def test_a_seat_lost_during_the_fault_fails_it(tmp_path, monkeypatch):
    async def during(s, c):
        c.room = c.seat = c.state = None        # an error ended the table for this client; AAAA goes on
    rec = _run_one_fault(tmp_path, monkeypatch, during)
    assert (rec["outcome"], rec["reason"]) == ("failed", "seat_lost")
    assert rec["origin"]["room"] == "AAAA" and rec["origin"]["seat"] == 2 and rec["origin"]["owner"] == "dev1"


def test_a_fresh_state_at_another_room_does_not_recover_the_original_seat(tmp_path, monkeypatch):
    async def during(s, c):
        s.srv.rooms["BBBB"] = _table("BBBB", 1, "dev1")
        c.room, c.seat = "BBBB", 1
        _fresh(c, "BBBB", 1)
    rec = _run_one_fault(tmp_path, monkeypatch, during)
    assert (rec["outcome"], rec["reason"]) == ("failed", "seat_lost")


def test_a_voluntary_leave_during_the_fault_censors_it(tmp_path, monkeypatch):
    async def during(s, c):
        await c._send({"type": "table_leave"})
        s.srv.rooms["AAAA"].seats[2].left_by_choice = True
        c._forget_room()
    rec = _run_one_fault(tmp_path, monkeypatch, during)
    assert (rec["outcome"], rec["reason"]) == ("censored", "left_table")


def test_the_original_room_ending_censors_it_even_after_a_rejoin_elsewhere(tmp_path, monkeypatch):
    async def during(s, c):
        del s.srv.rooms["AAAA"]
        s.srv.rooms["BBBB"] = _table("BBBB", 1, "dev1")
        c.room, c.seat = "BBBB", 1
        _fresh(c, "BBBB", 1)
    rec = _run_one_fault(tmp_path, monkeypatch, during)
    assert (rec["outcome"], rec["reason"]) == ("censored", "table_ended")


def test_another_owner_on_the_original_seat_fails_it(tmp_path, monkeypatch):
    async def during(s, c):
        s.srv.rooms["AAAA"].seats[2] = _seat("Soak-9", "dev9")
        _fresh(c, "AAAA", 2)
    rec = _run_one_fault(tmp_path, monkeypatch, during)
    assert (rec["outcome"], rec["reason"]) == ("failed", "seat_lost")


def test_the_original_seat_recovers_by_a_fresh_state_or_its_surviving_socket(tmp_path, monkeypatch):
    async def during(s, c):
        _fresh(c, "AAAA", 2)
    rec = _run_one_fault(tmp_path, monkeypatch, during)
    assert rec["outcome"] == "recovered" and rec["trace"]["via"] == "state"

    async def quiet(s, c):
        import time as _t
        c.last_rx = _t.monotonic() + 1.0        # a pong after the fault; the held state is pre-fault
    rec = _run_one_fault(tmp_path, monkeypatch, quiet)
    assert rec["outcome"] == "recovered" and rec["trace"]["via"] == "same_socket"


# a Leave excuses a loss only when it was sent for the original seat

def test_a_leave_at_another_room_does_not_excuse_losing_the_original_seat(tmp_path, monkeypatch):
    async def during(s, c):
        c.room = c.seat = c.state = None        # AAAA/2 lost while AAAA goes on
        s.srv.rooms["BBBB"] = _table("BBBB", 1, "dev1")
        c.room, c.seat = "BBBB", 1
        await c._send({"type": "table_leave"})  # a Leave, but for BBBB
        c._forget_room()
    rec = _run_one_fault(tmp_path, monkeypatch, during)
    assert (rec["outcome"], rec["reason"]) == ("failed", "seat_lost")


def test_a_replacement_occupant_s_leave_does_not_speak_for_the_original_one(tmp_path, monkeypatch):
    async def during(s, c):
        s.srv.rooms["AAAA"].seats[2] = _seat("Soak-9", "dev9", left_by_choice=True)
        c._forget_room()
    rec = _run_one_fault(tmp_path, monkeypatch, during)
    assert (rec["outcome"], rec["reason"]) == ("failed", "seat_lost")


# the client's down time runs from the socket's loss to the next open socket

def test_down_time_covers_the_retry_backoff_and_ends_at_the_reconnect(monkeypatch):
    import time as _t

    class WS:
        def __init__(self, live):
            self.live, self.transport = live, SimpleNamespace(abort=lambda: None)

        async def send(self, raw):
            return None

        def __aiter__(self):
            return self

        async def __anext__(self):
            if not self.live:
                raise StopAsyncIteration
            await asyncio.sleep(3600)

    opened = []

    async def connect(*a, **k):
        opened.append(_t.monotonic())
        return WS(live=len(opened) > 1)
    monkeypatch.setattr(client.websockets, "connect", connect)

    async def idle(c):
        return None

    async def run():
        c = client.SoakClient("Soak-1", "dev1", 9, 1.0, None, None, idle)
        c.backoff = 0.5
        task = asyncio.create_task(c.run(_t.monotonic() + 10))
        while c.rec.drops < 1:
            await asyncio.sleep(0.005)
        lost = _t.monotonic()
        await asyncio.sleep(0.3)                    # a decision window wholly inside the backoff
        inside = c.down_since(lost + 0.05)
        while c.rec.sockets < 2:
            await asyncio.sleep(0.005)
        up = _t.monotonic()
        await asyncio.sleep(0.2)                    # a decision window wholly after the reconnect
        after = c.down_since(up + 0.01)
        c.stop = True
        await task
        return inside, after
    inside, after = asyncio.run(run())
    assert inside >= 0.2
    assert after == 0.0


# the client keeps the page's socket URL and taps Next again on a resumed round end

def test_the_client_socket_url_has_socketurl_s_parameters():
    from urllib.parse import parse_qsl, urlsplit
    found = re.search(r"function socketUrl\(\): string \{\s*return `\$\{wsUrl\(\)\}\?([^`]*)`", _ws_ts())
    assert found, "socketUrl() changed shape in ws.ts: update online_soak/client.py"
    page = [tuple(p.split("=", 1)) for p in found.group(1).split("&")]
    c = client.SoakClient("a", "dev1", 9, 1.0, None, None, None)
    mine = parse_qsl(urlsplit(c.url).query)
    assert [k for k, _ in mine] == [k for k, _ in page]
    for (k, v), (_, pv) in zip(mine, page):
        assert v == (pv if not pv.startswith("${") else "dev1"), k


def test_a_resumed_round_end_that_still_shows_next_untapped_sends_next_again():
    async def run():
        c = client.SoakClient("Soak-1", "dev1", 9, 1.0, None, None, None)
        wire = []

        async def send(msg):
            wire.append(msg["type"])
            return True
        c._send = send
        end = {**_frame("AAAA", 2), "phase": "round_end", "ready": []}
        c.gen, c.room, c.seat = 1, "AAAA", 2
        c._on_state(end)
        await asyncio.sleep(0)
        c._on_state({**end, "ready": [0]})          # the same socket: no second tap
        await asyncio.sleep(0)
        c.gen = 2                                   # the Next was lost with the socket
        c._on_state(end)
        await asyncio.sleep(0)
        return wire
    assert asyncio.run(run()) == ["next_round", "next_round"]


# a strike is read against the server's record of the seat's presence

def _strike_soak(tmp_path):
    s = _bare_soak(tmp_path)
    clock = SimpleNamespace(t=0.0)
    s.srv = SimpleNamespace(rooms={}, now=lambda: clock.t, MOVE_TIMER=60.0, RETURN_MIN=15.0, MOVE_TIMER_POLL=0.5,
                              AWAY_PAUSE_MAX=20.0)
    s.presence, s.decision_at, s.by_seat = {}, {}, {}
    room = SimpleNamespace(code="AAAA", matched=True, seats=[_seat("Soak-1", "dev1", turn_started=None,
                                                                      away=False) for _ in range(4)])
    return s, clock, room


def test_a_strike_on_a_seat_connected_the_whole_decision_is_not_time_away(tmp_path):
    s, clock, room = _strike_soak(tmp_path)
    before = [None] * 4
    room.seats[3].turn_started = 0.0
    s._decision_starts(room, before)
    clock.t = 60.4
    s._strike(room, 3)
    assert s.strikes[0]["time_away"] is False and s.strikes[0]["connected_secs"] == pytest.approx(60.4)


def test_a_strike_after_time_away_is_flagged_from_the_server_s_presence_record(tmp_path):
    s, clock, room = _strike_soak(tmp_path)
    room.seats[3].turn_started = 0.0
    s._decision_starts(room, [None] * 4)
    clock.t = 10.0
    s._presence(room, "seat_disconnected", {"seat": 3})
    clock.t = 30.0
    s._presence(room, "seat_reconnected", {"seat": 3})
    room.seats[3].turn_started = -20.0              # the server rebases the clock for the return
    s._decision_starts(room, [None, None, None, -20.0])   # and its next sync changes nothing
    assert s.decision_at[("AAAA", 3)][0] == 0.0     # the decision still started at 0
    clock.t = 60.4                                  # struck with 40.4 s connected
    s._strike(room, 3)
    assert s.strikes[0]["time_away"] is True and s.strikes[0]["connected_secs"] == pytest.approx(40.4)
    clock.t = 40.0                                  # struck 10 s after a return
    s._strike(room, 3)
    assert s.strikes[1]["time_away"] is True and s.strikes[1]["since_return_secs"] == pytest.approx(10.0)


def test_a_strike_after_a_return_past_the_away_pause_is_not_time_away(tmp_path):
    """Away 25 s, past the 20 s pause: 5 s of it ran on the clock, and the
    return has no RETURN_MIN floor, so a strike once the clock is out is the
    player's own."""
    s, clock, room = _strike_soak(tmp_path)
    room.seats[3].turn_started = 0.0
    s._decision_starts(room, [None] * 4)
    clock.t = 55.0                                  # 5 s left at the drop
    s._presence(room, "seat_disconnected", {"seat": 3})
    clock.t = 80.0                                  # back 25 s later, 0 s left
    s._presence(room, "seat_reconnected", {"seat": 3})
    clock.t = 80.6
    s._strike(room, 3)
    first = s.strikes[0]
    assert first["time_away"] is False
    assert first["connected_secs"] == pytest.approx(55.6)
    assert first["charged_secs"] == pytest.approx(60.6)
    assert first["since_return_secs"] == pytest.approx(0.6)


def test_a_strike_before_a_run_down_clock_is_out_is_still_time_away(tmp_path):
    """Back after 25 s with 45 s left: a strike 30 s later came early."""
    s, clock, room = _strike_soak(tmp_path)
    room.seats[3].turn_started = 0.0
    s._decision_starts(room, [None] * 4)
    clock.t = 10.0
    s._presence(room, "seat_disconnected", {"seat": 3})
    clock.t = 35.0
    s._presence(room, "seat_reconnected", {"seat": 3})
    clock.t = 65.0
    s._strike(room, 3)
    assert s.strikes[0]["time_away"] is True
    assert s.strikes[0]["charged_secs"] == pytest.approx(45.0)
    clock.t = 80.4                                  # the run-down clock's own end
    s._strike(room, 3)
    assert s.strikes[1]["time_away"] is False


def test_a_state_on_a_socket_opened_after_the_last_cut_recovers():
    assert _recovered(state_at=9.0, new_socket=True) == "new_socket"
    assert _recovered(state_at=9.0, new_socket=True, server_view=audit.state_view({**_ST, "turn": 3})) is None


@pytest.mark.parametrize("current_gen", [2, 3])
def test_a_state_during_a_stall_requires_evidence_after_it_ends(tmp_path, monkeypatch, current_gen):
    import time

    monkeypatch.setattr(soak, "RECOVERY_DEADLINE_SECS", 0.05)

    async def during(s, c):
        c.gen = 2
        c.socket_opened[c.gen] = time.monotonic()
        c.state, c.state_gen, c.state_at = _frame("AAAA", 2), c.gen, time.monotonic()
        c.gen = current_gen
        c.last_rx = c.state_at

    rec = _run_one_fault(tmp_path, monkeypatch, during)
    assert (rec["outcome"], rec["reason"]) == ("failed", "deadline")


@pytest.mark.parametrize("current_gen, outcome", [(2, "recovered"), (3, "failed")])
def test_recovery_after_the_last_cut_uses_the_current_socket(tmp_path, monkeypatch, current_gen, outcome):
    import time

    s = _bare_soak(tmp_path)
    s.scale = 1.0
    s.srv = SimpleNamespace(rooms={"AAAA": _table("AAAA", 2, "dev1")}, trick_json=lambda t, o: t)
    c = client.SoakClient("Soak-1", "dev1", 9, 1.0, None, None, None)
    c.ws, c.gen, c.room, c.seat = _WS(), 1, "AAAA", 2
    origin = s._origin(c)
    c.gen = 2
    c.socket_opened[2] = time.monotonic()
    c.state, c.state_gen, c.state_at = _frame("AAAA", 2), 2, time.monotonic()
    c.gen = current_gen
    monkeypatch.setattr(soak, "RECOVERY_DEADLINE_SECS", 0.03)
    end = time.monotonic()
    trace = {}
    result = asyncio.run(s._recovered(c, end, end + 1, True, trace, origin))
    assert result[0] == outcome
    if outcome == "recovered":
        assert trace["via"] == "new_socket"
