"""Every game-server room builds its served bot with its own seed and logs it.

Witnesses: a room built without a bot calls the registry with ``seed=`` its
own ``bot_seed``, drawn per room; an explicit ``bot_seed`` is honoured; a bot
passed in is kept as it is (``bot_seed`` stays None); every ``round_start``
record carries the seed; the served policy's name does not depend on it.
"""
import json
import random

from shengji.api import server
from shengji.engine.game import Game


def test_each_default_room_builds_its_bot_with_its_own_seed(monkeypatch, tmp_path):
    calls = []
    draws = iter([11, 22])

    def fake_make_bot(name, **kw):
        calls.append((name, kw))
        return server.HeuristicBot()
    monkeypatch.setattr(server, "make_bot", fake_make_bot)
    monkeypatch.setattr(server.secrets, "randbits", lambda bits: next(draws))
    monkeypatch.setenv("SHENGJI_BOT", "heuristic")
    first = server.Room(code="AAAA", log_dir=tmp_path)
    second = server.Room(code="BBBB", log_dir=tmp_path)
    fixed = server.Room(code="CCCC", log_dir=tmp_path, bot_seed=7)
    assert (first.bot_seed, second.bot_seed, fixed.bot_seed) == (11, 22, 7)
    assert calls == [("heuristic", {"seed": 11}), ("heuristic", {"seed": 22}),
                     ("heuristic", {"seed": 7})]


def test_a_bot_passed_in_is_kept_and_has_no_room_seed(tmp_path):
    bot = server.HeuristicBot()
    room = server.Room(code="DDDD", log_dir=tmp_path, bot=bot)
    assert room.bot is bot and room.bot_seed is None


def test_the_seed_reaches_the_bot_and_every_round_start_record(monkeypatch, tmp_path):
    monkeypatch.setenv("SHENGJI_BOT", "mc")
    room = server.Room(code="EEEE", log_dir=tmp_path, bot_seed=12345)
    assert room.bot.rng.getstate() == random.Random(12345).getstate()
    room.game = Game(random.Random(3))
    room.game.start_round()
    room.seats = [server.Seat(str(s), is_bot=True) for s in range(4)]
    server._log_round_start(room)
    records = [json.loads(line) for path in tmp_path.iterdir() for line in path.open()]
    start, = [r for r in records if r["e"] == "round_start"]
    assert start["bot_seed"] == 12345


def test_the_served_policy_name_does_not_depend_on_the_seed():
    from shengji.ai.registry import make_bot
    from shengji.train import pv_search_policy as pv
    names = {make_bot("mc", seed=seed).policy_name for seed in (0, 1, 2**31 - 1)}
    assert names == {"mc"}
    # the pv-search recipe (name digest) has no seed field; the bury identity
    # carries the play name, not the seed
    assert "seed" not in pv.PVSearchConfig.__dataclass_fields__
