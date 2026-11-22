"""The online soak harness (scripts/online_soak): its loopback-only guard, its
copy of the page's connection constants, and its fault proxy. The soak run
itself is a script run by hand (``soak.py``), not a test."""
from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "server" / "scripts" / "online_soak"))

import client  # noqa: E402
from localonly import NotLocal, require_local, require_not_deployed  # noqa: E402
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
    sys.path.insert(0, str(ROOT / "server" / "scripts" / "online_soak"))
    import soak
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
