"""End-to-end WebSocket smoke test: human client + 3 bots, brute-force legal
plays from the client side (no engine knowledge), one full round."""

import asyncio
import itertools
import json
import threading
import time

import uvicorn
import websockets

from shengji.api import server as srv

PORT = 8765


def run_server():
    uvicorn.run(srv.app, host="127.0.0.1", port=PORT, log_level="warning")


async def recv_msg(ws, timeout=10):
    return json.loads(await asyncio.wait_for(ws.recv(), timeout))


async def main():
    threading.Thread(target=run_server, daemon=True).start()
    time.sleep(1.0)
    async with websockets.connect(f"ws://127.0.0.1:{PORT}/ws") as ws:
        await ws.send(json.dumps({"type": "create_room", "name": "Smoke"}))
        msg = await recv_msg(ws)
        assert msg["type"] == "room", msg
        for _ in range(3):
            await ws.send(json.dumps({"type": "add_bot"}))
            msg = await recv_msg(ws)
        assert len(msg["players"]) == 4, msg
        await ws.send(json.dumps({"type": "start_game"}))

        state, actions, errors = None, 0, 0
        pending_try = None  # iterator of candidate plays while brute-forcing

        while actions < 400:
            msg = await recv_msg(ws, timeout=15)
            if msg["type"] == "error":
                errors += 1
                assert pending_try is not None, f"unexpected error: {msg}"
                await ws.send(json.dumps({"type": "play",
                                          "card_ids": next(pending_try)}))
                continue
            if msg["type"] != "state":
                continue
            state = msg
            if state["phase"] == "round_end":
                print(f"round complete: attackers {state['attacker_points']} pts, "
                      f"result={state['round_result']['winner_team']} wins "
                      f"+{state['round_result']['level_change']}, "
                      f"{actions} human actions, {errors} rejected tries")
                return
            if state["phase"] == "declare" and state["you"] not in state["passed"]:
                await ws.send(json.dumps({"type": "pass_declare"}))
                continue
            if state["turn"] != state["you"]:
                continue
            pending_try = None
            actions += 1
            if state["phase"] == "bury":
                ids = [c["id"] for c in state["hand"][:8]]
                await ws.send(json.dumps({"type": "bury", "card_ids": ids}))
            elif state["phase"] == "play":
                n = 1
                if state["trick"] and state["trick"]["plays"]:
                    n = len(state["trick"]["plays"][0]["cards"])
                ids = [c["id"] for c in state["hand"]]
                pending_try = (list(c) for c in itertools.combinations(ids, n))
                await ws.send(json.dumps({"type": "play",
                                          "card_ids": next(pending_try)}))
        raise AssertionError("round did not finish in 400 actions")


asyncio.run(main())
import os
import sys
sys.stdout.flush()
os._exit(0)  # skip teardown of the daemonized uvicorn thread
