"""One-round socket smoke for designated W32 rooms, not a strength screen.

Runs against an already-started server. Default target is loopback; a public
test needs --allow-remote. Access key comes only from the environment. The
client uses only its own hand/public trick and never calls a debug endpoint.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
from urllib.parse import urlparse

from websockets.asyncio.client import connect
from shengji.ai.heuristic import HeuristicBot
from shengji.engine.cards import Ordering


def emit(**fields):
    print(json.dumps(fields, sort_keys=True), flush=True)


async def send(ws, **message):
    await ws.send(json.dumps(message))


async def receive(ws, kind):
    while True:
        message = json.loads(await asyncio.wait_for(ws.recv(), 30))
        if message.get("type") == "error" and kind != "error":
            raise RuntimeError("server refused a smoke-test action")
        if message.get("type") == kind:
            return message


async def play_round(ws, room, experimental):
    for _ in range(3):
        await send(ws, type="add_bot")
        await receive(ws, "room")
    await send(ws, type="start_game")
    started, last_report = time.monotonic(), 0
    actions, phases, last_action_state = 0, set(), None
    helper = HeuristicBot()
    while True:
        try:
            message = json.loads(await asyncio.wait_for(ws.recv(), 20))
        except TimeoutError:
            emit(kind="waiting", room=room, elapsed_seconds=round(time.monotonic()-started, 1))
            continue
        if message.get("type") == "error":
            raise RuntimeError("server refused a smoke-test action")
        if message.get("type") != "state":
            continue
        assert (message.get("experimental_policy") == "w32") is experimental
        if "Model search failed" in (message.get("message") or ""):
            raise RuntimeError("model worker failed")
        phase, seat = message["phase"], message["you"]
        phases.add(phase)
        elapsed = time.monotonic() - started
        if elapsed - last_report >= 20:
            emit(kind="progress", room=room, phase=phase, client_actions=actions,
                 elapsed_seconds=round(elapsed, 1))
            last_report = elapsed
        if phase in {"round_end", "game_over"}:
            assert message["round_result"] is not None and actions > 0
            assert {"deal", "declare", "play"} <= phases
            emit(kind="round_complete", room=room, experimental=experimental,
                 client_actions=actions, phases=sorted(phases), elapsed_seconds=round(elapsed, 3))
            return
        signature = (phase, message["turn"], tuple(c["id"] for c in message["hand"]),
                     json.dumps(message["trick"], sort_keys=True), tuple(message["passed"]))
        if signature == last_action_state:
            continue
        command = None
        if phase == "declare" and seat not in message["passed"]:
            command = {"type": "pass_declare"}
        elif phase == "bury" and message["banker"] == seat:
            command = {"type": "bury", "card_ids": [c["id"] for c in message["hand"][:8]]}
        elif phase == "play" and message["turn"] == seat:
            pool = list(message["hand"])
            codes = [c["code"] for c in pool]
            plays = message["trick"]["plays"]
            trump = message["trump"]
            ordering = Ordering(None if trump["suit"] == "NT" else trump["suit"], trump["rank"])
            chosen = (helper._forced_follow(codes, plays[0]["cards"], ordering, prefer_points=False)
                      if plays else codes[:1])
            ids = []
            for code in chosen:
                index = next(i for i, card in enumerate(pool) if card["code"] == code)
                ids.append(pool.pop(index)["id"])
            command = {"type": "play", "card_ids": ids}
        if command:
            last_action_state = signature
            await ws.send(json.dumps(command))
            actions += 1


async def check(args):
    key = os.environ["SHENGJI_W32_TEST_ACCESS_KEY"]
    async with connect(args.url) as ordinary, connect(args.url) as test, connect(args.url) as extra:
        await send(test, type="create_room", name="W32 smoke", test_policy="w32", test_access_key="invalid")
        assert (await receive(test, "error"))["code"] == "test_room_unavailable"
        await send(ordinary, type="create_room", name="Ordinary smoke")
        ordinary_room = await receive(ordinary, "room")
        assert "experimental_policy" not in ordinary_room
        await send(test, type="create_room", name="W32 smoke", test_policy="w32", test_access_key=key)
        test_room = await receive(test, "room")
        assert test_room["experimental_policy"] == "w32"
        # Create the second allowed lobby, then verify that a third refuses.
        await send(extra, type="create_room", name="W32 gate smoke", test_policy="w32", test_access_key=key)
        assert (await receive(extra, "room"))["experimental_policy"] == "w32"
        async with connect(args.url) as excess:
            await send(excess, type="create_room", test_policy="w32", test_access_key=key)
            assert "limit" in (await receive(excess, "error"))["message"]
        await send(extra, type="leave_room")
        await receive(extra, "left")
        emit(kind="gate_pass", ordinary_room=ordinary_room["room"], test_room=test_room["room"])
        try:
            tasks = [play_round(test, test_room["room"], True)]
            if args.ordinary_round:
                tasks.append(play_round(ordinary, ordinary_room["room"], False))
            await asyncio.gather(*tasks)
        finally:
            for ws in (test, ordinary):
                await send(ws, type="leave_room")
                await receive(ws, "left")
        emit(kind="complete", scope="designated-room engineering smoke, not strength")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="ws://127.0.0.1:8000/ws")
    parser.add_argument("--allow-remote", action="store_true")
    parser.add_argument("--ordinary-round", action="store_true")
    args = parser.parse_args()
    target = urlparse(args.url)
    if target.scheme not in {"ws", "wss"} or (target.hostname not in {"127.0.0.1", "localhost", "::1"}
                                              and not args.allow_remote):
        parser.error("a non-loopback socket requires explicit --allow-remote")
    async def bounded():
        async with asyncio.timeout(1800):
            await check(args)
    asyncio.run(bounded())


if __name__ == "__main__":
    main()
