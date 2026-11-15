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

import pytest

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


def test_committed_start_flow_sessions_regenerate_identically():
    path = FIXTURE.with_name(gen.FIXTURE_NAMES["start"])
    text = gzip.decompress(path.read_bytes()).decode("utf-8")
    header = json.loads(text.split("\n", 1)[0])
    assert header["format"] == gen.FORMAT
    assert gen.sessions_text(header["games"], header["rounds"], header["seed"],
                             flow="start") == text


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


@pytest.mark.parametrize("failure", [True, False])
def test_endpoint_failure_or_early_exit_does_not_wait_forever(monkeypatch, failure):
    async def broken_endpoint(ws):
        assert ws.query_params == {}
        if failure:
            raise ValueError("injected endpoint failure")
    monkeypatch.setattr(gen.server, "ws_endpoint", broken_endpoint)
    error = ValueError if failure else RuntimeError
    message = "injected endpoint failure" if failure else "endpoint ended before"
    with pytest.raises(error, match=message):
        gen.play_session(12345, 1, gen.game_config(1))


# A two-round session takes about 130 virtual seconds.
VIRTUAL_CEILING = 3600.0


class _BoundedLoop(gen.VirtualTimeLoop):
    """Fails a session that stops making progress (nothing ready and no timer
    due, or virtual time far past any real session) instead of waiting forever."""

    def _run_once(self) -> None:
        if not getattr(self, "_stalled", False):
            if not self._ready and not self._scheduled:
                self._stalled = True
                raise RuntimeError("session stalled: nothing left to run")
            if self._virtual_now > VIRTUAL_CEILING:
                self._stalled = True
                raise RuntimeError("session stalled: virtual time ceiling")
        super()._run_once()


def _first_state(frames: list[dict]) -> int:
    return next(i for i, f in enumerate(frames) if f["type"] == "state")


# ``create_room`` with ``start: true`` stands for the client's create, add_bot
# to four seats, start_game chain: from the first state frame on the human
# gets the chain's frames, and before it only the chain's first room frame.
# game_config cycles the driver variations: index 1 leads throws, index 3
# starts at A.
@pytest.mark.parametrize("seed,config_index", [(1, 0), (2, 1), (3, 2), (4, 3), (12345, 1)])
def test_start_flow_matches_the_add_bot_start_game_chain(monkeypatch, seed, config_index):
    monkeypatch.setattr(gen, "VirtualTimeLoop", _BoundedLoop)
    config = gen.game_config(config_index)
    chain = gen.play_session(seed, 2, config, flow="chain")
    start = gen.play_session(seed, 2, config, flow="start")
    c, s = _first_state(chain), _first_state(start)
    assert start[s:] == chain[c:]
    assert [f["type"] for f in start[:s]] == ["resume", "chat_history", "room"]
    assert start[:s] == chain[:s]
    assert [f["type"] for f in chain[s:c]] == ["room"] * (c - s)
    assert start[-1] == {"type": "left"}


def test_an_unknown_flow_is_refused():
    with pytest.raises(ValueError, match="unknown flow"):
        gen.play_session(1, 1, gen.game_config(0), flow="other")
