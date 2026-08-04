"""End-to-end: a human joins a running game and takes a bot's seat."""
import asyncio, json, sys
sys.path.insert(0, "server")
import websockets

async def main():
    uri = "ws://localhost:8899/ws"
    async with websockets.connect(uri) as a:
        await a.send(json.dumps({"type": "create_room", "name": "jerry"}))
        room = None
        for _ in range(5):
            m = json.loads(await a.recv())
            if m.get("type") == "room":
                room = m["room"]; break
        await a.send(json.dumps({"type": "add_bot"}))
        await a.send(json.dumps({"type": "add_bot"}))
        await a.send(json.dumps({"type": "add_bot"}))
        await asyncio.sleep(0.5)
        await a.send(json.dumps({"type": "start_game"}))
        await asyncio.sleep(2.0)
        # second human joins the RUNNING game
        async with websockets.connect(uri) as b:
            await b.send(json.dumps({"type": "join_room", "room": room, "name": "james"}))
            got = None
            for _ in range(8):
                m = json.loads(await asyncio.wait_for(b.recv(), timeout=5))
                if m.get("type") == "state":
                    got = m; break
            assert got, "no state for the joiner"
            mine = [p for p in got["players"] if p["seat"] == got["you"]][0]
            print(f"JOINED room {room} as seat {got['you']} name={mine['name']} "
                  f"is_bot={mine['is_bot']} hand={len(got.get('hand', []))} cards")
            assert not mine["is_bot"] and mine["name"] == "james"
            assert len(got.get("hand", [])) > 0, "joiner got no hand"
            print("PASS: mid-game seat takeover works, hand delivered")
asyncio.run(main())
