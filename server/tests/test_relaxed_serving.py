"""The relaxed level on the pinned production packages: the served bot (``fly.toml``) wrapped
with the pinned S136 scorer package (``server.RELAXED_SF_PACKAGE``, sha256 ``server.RELAXED_SF_SHA256``,
an asset of the ``serving-packages`` release).

A casual room with Standard bots builds the served name plus ``RELAXED_BOT``; the served bot still
declares and buries; through ``_paced_bot_step`` / ``_commit_bot_turn`` every play is a scorer
decision (no fallback), the room repeats itself from the same seed, and the served bot's own name and
decisions are untouched.  Fails, never skips, under ``SHENGJI_REQUIRE_PV_PACKAGE=1``.
"""
import asyncio
import hashlib
import os
import random
from pathlib import Path

import pytest

from test_encoder_round_compat import REQUIRE_PACKAGE
from test_release50_fly_config import release50_packages  # noqa: F401
from test_release53_fly_config import served_bot
from test_release55_fly_config import RELEASE55, release55_pair  # noqa: F401
from test_release46_fly_config import fly_env as served_env
from test_unified_serving import served_functions  # noqa: F401

SF_VAR = "SHENGJI_RELAXED_SF_PACKAGE_PATH"

pytestmark = pytest.mark.production_package


@pytest.fixture(scope="module")
def relaxed_package():
    from shengji.api import server
    value = os.environ.get(SF_VAR)
    if not value:
        if REQUIRE_PACKAGE:
            pytest.fail(f"SHENGJI_REQUIRE_PV_PACKAGE=1 but {SF_VAR} is unset")
        pytest.skip(f"set {SF_VAR} (and SHENGJI_REQUIRE_PV_PACKAGE=1 in CI)")
    path = Path(value)
    if not path.exists():
        pytest.fail(f"pinned relaxed scorer package is missing: {path}")
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    assert actual == server.RELAXED_SF_SHA256, f"scorer package is {actual[:12]}, not the pinned one"
    assert path.name == Path(server.RELAXED_SF_PACKAGE).name
    return path


def _play_state(bot, seed):
    from shengji.ai import env as play_env
    from shengji.engine.game import Game
    game = Game(random.Random(seed))
    play_env.prepare_round(game, [bot] * 4)
    return game


def test_a_relaxed_room_on_the_served_release_plays_the_scorer_through_the_server_path(
        release50_packages, release55_pair, relaxed_package, tmp_path, monkeypatch, served_functions):
    from shengji.api import server
    from shengji.train import relaxed_play as rp

    name, served = served_bot(release50_packages, release55_pair, monkeypatch, env=served_env())
    assert name == served.policy_name == RELEASE55 == os.environ["SHENGJI_BOT"]
    monkeypatch.setattr(server, "RELAXED_SF_PACKAGE", str(relaxed_package))
    relaxed_name = f"{name}-{server.RELAXED_BOT}"

    async def scenario(code):
        game = _play_state(served, 5)
        rnd = game.round
        room = server.Room(code=code, game=game, log_dir=tmp_path, bot_seed=9, bot_level="standard",
                           seats=[server.Seat(str(s), is_bot=True) for s in range(4)])
        assert room.bot_level == "standard" and room.bot.policy_name == relaxed_name
        assert room.bot.served.policy_name == name
        room.ids = [dict(enumerate(hand)) for hand in rnd.hands]
        room._kitty_given = True
        room.log_event = lambda kind, **data: None
        played, records = [], []
        for _ in range(8):
            seat = rnd.turn
            prepared = await server._paced_bot_step(room, seat, minimum_turn_seconds=0)
            assert prepared is not None
            records.append(dict(prepared.decision.snapshot.bot_copy.last_decision_record))
            played.append((seat, sorted(prepared.decision.cards)))
            assert server._commit_bot_turn(room, prepared)
        return played, records

    first, records = asyncio.run(scenario("R54A"))
    second, _ = asyncio.run(scenario("R54B"))
    assert first == second
    assert all(r["schema"] == rp.RECORD_SCHEMA and r["policy"] == relaxed_name for r in records)
    assert all(r.get("relaxed_inner_schema") != "search-free-fallback-v1" for r in records)
    assert all(r.get("top_margin", 0.0) <= rp.CASUAL_DELTA for r in records)
    assert rp.casual_model(relaxed_package).package_sha256 == server.RELAXED_SF_SHA256
