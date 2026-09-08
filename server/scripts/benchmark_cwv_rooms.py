"""Bounded, loopback-only real W32 room/WebSocket diagnostic; no gameplay screen.

Uses private saved states at indices 0 and 2 (wide lead and ordinary follow).
Run in an isolated process with one BLAS thread and an outer memory/wall limit.
No output files, provider calls, public listener, or production room access.
"""
from __future__ import annotations

import argparse
import asyncio
import copy
import hashlib
import json
import os
from pathlib import Path
import random
import resource
import signal
import socket
import sys
import time


async def measure(args):
    class BlockTorch:
        def find_spec(self, fullname, path=None, target=None):
            if fullname == "torch" or fullname.startswith("torch."):
                raise RuntimeError("serving imported Torch")
    sys.meta_path.insert(0, BlockTorch())
    import uvicorn
    from websockets import connect
    from shengji.ai.registry import make_bot, register_cwv_shortlist_policies
    from shengji.api import server as srv
    from shengji.engine.game import Game
    from shengji.luna.game import _round_from_snapshot, _state_snapshot

    if os.environ.get("SHENGJI_MODEL_SEARCH_CONCURRENCY", "1") != "1":
        raise ValueError("this measurement exercises concurrency=1")
    if not srv._fast_active():
        raise RuntimeError("compiled engine required")
    names = register_cwv_shortlist_policies(args.checkpoint, [32], batch_size=128)
    raw = Path(args.states).read_bytes()
    states = json.loads(raw)
    events, running, max_running = [], set(), 0

    def state_hash(rnd):
        return hashlib.sha256(json.dumps(_state_snapshot(rnd), sort_keys=True).encode()).hexdigest()

    def record(code, kind, **fields):
        nonlocal max_running
        if kind != "model_search":
            return
        event = fields["event"]
        if event == "running":
            running.add(code)
            max_running = max(max_running, len(running))
        elif event in {"completed", "error", "cancelled"}:
            running.discard(code)
        row = {"room": code, "kind": kind, **fields}
        events.append(row)
        print(json.dumps(row, sort_keys=True), flush=True)

    def room(code, index):
        rnd = _round_from_snapshot(states[index])
        r = srv.Room(code=code, bot=make_bot(names[0], seed=89260904 + index))
        r.game = Game(random.Random(91))
        r.game.round = rnd
        r.seats = [srv.Seat(name=f"Bot {seat}", is_bot=True) for seat in range(4)]
        r.ids = [{i * 4 + seat: card for i, card in enumerate(rnd.hands[seat])}
                 for seat in range(4)]
        r._kitty_given = True
        r.log_event = lambda kind, **fields: record(code, kind, **fields)
        srv.rooms[code] = r
        return r

    wide, ordinary = room("WIDE", 0), room("TINY", 2)
    if wide.bot.evaluator.model._weights is not ordinary.bot.evaluator.model._weights:
        raise AssertionError("rooms do not share immutable weights")
    if copy.deepcopy(wide.bot).evaluator.model._weights is not wide.bot.evaluator.model._weights:
        raise AssertionError("snapshot copies weights")
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(16)
    listener.setblocking(False)
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(srv.app, log_level="error", access_log=False,
                                         lifespan="off", ws="websockets"))
    serving = asyncio.create_task(server.serve(sockets=[listener]))
    tasks = []
    latencies = []
    try:
        while not server.started:
            if serving.done():
                await serving
                raise RuntimeError("server exited before listening")
            await asyncio.sleep(.01)
        async with connect(f"ws://127.0.0.1:{port}/ws") as client:
            before = [(state_hash(r.round), r.bot.rng.getstate()) for r in (wide, ordinary)]
            tasks = [asyncio.create_task(srv._paced_bot_step(r, r.round.turn,
                                                           minimum_turn_seconds=0))
                     for r in (wide, ordinary)]
            while not all(t.done() for t in tasks):
                start = time.perf_counter()
                await client.send(json.dumps({"type": "peek_room", "room": "TINY"}))
                reply = json.loads(await asyncio.wait_for(client.recv(), timeout=5))
                if reply.get("type") != "room_seats" or reply.get("room") != "TINY":
                    raise AssertionError("real WebSocket room query failed")
                latencies.append(time.perf_counter() - start)
                await asyncio.sleep(.05)
            prepared = await asyncio.gather(*tasks)
            for r, step, original in zip((wide, ordinary), prepared, before):
                assert step is not None
                assert original == (state_hash(r.round), r.bot.rng.getstate())
                assert srv._commit_bot_turn(r, step), "actual engine commit refused"
            assert max_running == 1
            wide_done = next(i for i, e in enumerate(events)
                             if e["room"] == "WIDE" and e["event"] == "completed")
            tiny_start = next(i for i, e in enumerate(events)
                              if e["room"] == "TINY" and e["event"] == "running")
            assert wide_done < tiny_start, "second room bypassed admission"

            stale = room("OLD", 2)
            original = (state_hash(stale.round), stale.bot.rng.getstate())
            seat = stale.round.turn
            step = await srv._paced_bot_step(stale, seat, minimum_turn_seconds=0)
            stale.seats[seat].is_bot = False
            assert not srv._commit_bot_turn(stale, step)
            assert original == (state_hash(stale.round), stale.bot.rng.getstate())

            failed = room("FAIL", 2)
            original = (state_hash(failed.round), failed.bot.rng.getstate())
            compute = srv._compute_bot_turn_off_loop
            async def injected_failure(snapshot):
                snapshot.bot_copy.rng.random()
                raise RuntimeError("synthetic private failure")
            srv._compute_bot_turn_off_loop = injected_failure
            try:
                try:
                    await srv._paced_bot_step(failed, failed.round.turn, minimum_turn_seconds=0)
                except RuntimeError:
                    pass
                else:
                    raise AssertionError("worker failure swallowed")
            finally:
                srv._compute_bot_turn_off_loop = compute
            assert failed.bot.rng.getstate() == original[1]
            assert failed.round.message == "Model search failed; claim this seat or contact the host."
            assert "synthetic private failure" not in repr(events)
            assert [e["event"] for e in events if e["room"] == "FAIL"] == ["queued", "running", "error"]
            peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
            print(json.dumps({"kind": "complete", "scope": "loopback room diagnostic, not strength",
                              "policy": names[0], "states_sha256": hashlib.sha256(raw).hexdigest(),
                              "peak_rss_bytes": peak if sys.platform == "darwin" else peak * 1024,
                              "max_running_searches": max_running, "websocket_queries": len(latencies),
                              "websocket_max_seconds": max(latencies),
                              "websocket_mean_seconds": sum(latencies) / len(latencies),
                              "stale_refused": True, "error_visible": True,
                              "ordinary_and_wide_committed": True, "torch_loaded": "torch" in sys.modules}), flush=True)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        server.should_exit = True
        await serving
        listener.close()
        srv.rooms.clear()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("checkpoint")
    parser.add_argument("states")
    args = parser.parse_args()
    def expired(*_):
        raise TimeoutError("180-second room measurement expired")
    signal.signal(signal.SIGALRM, expired)
    signal.alarm(180)
    asyncio.run(measure(args))
    signal.alarm(0)


if __name__ == "__main__":
    main()
