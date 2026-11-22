"""A TCP pass-through between one soak client and the local server, with faults.

A fault acts on the bytes as a bad network does: ``cut`` resets every open
connection (both ends see it at once); ``pause`` stops one or both directions
without closing anything (the kernel buffers, as on a stalled or half-open
link, and the endpoints' own heartbeats decide when to give up); ``delay``
holds every chunk back for a while. Nothing is dropped from inside a
stream, so the WebSocket framing stays intact whatever the fault.
"""
from __future__ import annotations

import asyncio
import contextlib

from localonly import require_local, require_same_family

UP, DOWN = "up", "down"     # client -> server, server -> client


class FaultProxy:
    def __init__(self, upstream_port: int, upstream_host: str = "127.0.0.1",
                 listen_host: str | None = None) -> None:
        self.listen_host = listen_host or upstream_host
        require_same_family(self.listen_host, upstream_host)
        self.upstream = (require_local(upstream_host), upstream_port)
        self.port = 0
        self._server: asyncio.base_events.Server | None = None
        self._open: set[asyncio.StreamWriter] = set()
        self._gate = {UP: asyncio.Event(), DOWN: asyncio.Event()}
        for g in self._gate.values():
            g.set()
        self.delay = 0.0
        self.connections = 0

    async def start(self) -> int:
        self._server = await asyncio.start_server(self._accept, require_local(self.listen_host), 0)
        self.port = self._server.sockets[0].getsockname()[1]
        return self.port

    async def close(self) -> None:
        self.cut()
        if self._server is not None:
            self._server.close()
            with contextlib.suppress(Exception):
                await self._server.wait_closed()

    def cut(self) -> None:
        """Reset every open connection through this proxy."""
        for w in list(self._open):
            w.transport.abort()
        self._open.clear()

    def pause(self, *directions: str) -> None:
        for d in directions or (UP, DOWN):
            self._gate[d].clear()

    def resume(self) -> None:
        for g in self._gate.values():
            g.set()

    async def _accept(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            up_reader, up_writer = await asyncio.open_connection(*self.upstream)
        except OSError:
            writer.transport.abort()
            return
        self.connections += 1
        self._open.update((writer, up_writer))
        await asyncio.gather(self._pump(reader, up_writer, UP), self._pump(up_reader, writer, DOWN),
                             return_exceptions=True)
        for w in (writer, up_writer):
            self._open.discard(w)
            w.transport.abort()

    async def _pump(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, direction: str) -> None:
        try:
            while True:
                data = await reader.read(65536)
                if not data:
                    break
                await self._gate[direction].wait()
                if self.delay > 0:
                    await asyncio.sleep(self.delay)
                if writer.transport.is_closing():
                    break
                writer.write(data)
                await writer.drain()
        except (ConnectionError, OSError, asyncio.CancelledError):
            pass
        finally:
            writer.transport.abort()
