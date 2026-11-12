"""The offline-server parity fixture is current, deterministic and covers the flows.

``web/src/offline/fixtures/server_sessions.jsonl.gz`` holds, per seeded solo
game, digests of every frame ``ws_endpoint`` sends the human's socket
(``scripts/gen_offline_server_fixtures.py``); the TypeScript local server is
held to it in vitest. Regenerating here and comparing byte for byte catches a
server, engine or bot change that leaves the fixture stale, and under
``SHENGJI_FAST=1`` also holds the compiled engine to the same frames.
"""

import gzip
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import gen_offline_server_fixtures as gen  # noqa: E402

FIXTURE = (Path(__file__).resolve().parents[2] / "web" / "src" / "offline"
           / "fixtures" / "server_sessions.jsonl.gz")


def _committed() -> str:
    return gzip.decompress(FIXTURE.read_bytes()).decode("utf-8")


def test_committed_sessions_regenerate_identically():
    text = _committed()
    header = json.loads(text.split("\n", 1)[0])
    assert header["format"] == gen.FORMAT
    assert gen.sessions_text(header["games"], header["rounds"], header["seed"]) == text


def test_committed_sessions_cover_the_server_flows():
    header = json.loads(_committed().split("\n", 1)[0])
    stats = header["stats"]
    assert header["games"] >= 200 and header["rounds"] >= 2
    assert set(header["normalized"]) == {"room", "token", "t"}
    for key in ("frames_state", "frames_room", "frames_left", "notice_frames",
                "point_scored_rounds", "human_bury_frames", "human_declared_frames"):
        assert stats[key] > 0, key
    assert stats["round_end_frames"] == header["games"] * header["rounds"]


def test_a_session_is_deterministic_and_only_normalizes_environment():
    config = gen.game_config(1)
    a = gen.play_session(12345, 1, config)
    b = gen.play_session(12345, 1, config)
    assert a == b
    assert a[0] == {"type": "resume", "token": "TOKEN", "gen": 1}
    assert a[-1] == {"type": "left"}
    assert all(f.get("room", "ROOM") == "ROOM" for f in a)


def test_deck_rng_matches_its_typescript_port():
    # mulberry32's first outputs for seed 1 (web/src/offline/server/rng.ts)
    rng = gen.DeckRng(1)
    assert [rng.next_u32() for _ in range(3)] == [2693262067, 11749833, 2265367787]
