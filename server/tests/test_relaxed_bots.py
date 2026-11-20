"""Relaxed bots: a casual room's switch that seats the relaxed level (``server.RELAXED_BOT``: the
served bot's declare and bury, card play by the S136 search-free scorer with near-best softmax noise).

Witnesses: a relaxed room wraps the served bot with its own seed and a default room builds the served
bot alone; a missing scorer package plays the served bot and logs the room as served; a matched
(ranked) room refuses the switch, in the room and at ``start_matched_room``; every ``round_start``
names the policy that plays the bot seats and whether it is relaxed; the relaxed bot plays through
the server's snapshot path (``_paced_bot_step`` / ``_commit_bot_turn``), a seeded relaxed bot repeats
its decisions, and every play is one of the scorer's proposals within ``CASUAL_DELTA`` logits of its
best; the production mistake dashboard leaves relaxed rounds out of the bot-versus-human tallies.
The pinned scorer package on the release-54 served bot: ``test_relaxed_serving.py``.
"""
import asyncio
import copy
import json
import random
import time

import numpy as np
import pytest

from shengji.ai import belief_numpy as bn
from shengji.ai import env as play_env
from shengji.ai import unified_numpy as un
from shengji.ai.heuristic import HeuristicBot
from shengji.ai.registry import REGISTRY, make_bot
from shengji.api import server
from shengji.engine.game import Game
from shengji.train import relaxed_play as rp
from shengji.train import search_free_play as sf

SMALL = {"d": 16, "heads": 4, "enc_layers": 1, "xattn_layers": 1, "x_hidden": 16, "card_self_attn": True}
CONFIG = {"trunk": SMALL, "heads": {"q_hidden": 8, "policy_hidden": 8}}


def synthetic_package(directory):
    """``(path, sha256)`` of a small random-weight scorer package in ``directory``."""
    rng = np.random.default_rng(7)

    def w(shapes):
        return {k: (0.3 * rng.standard_normal(v)).astype(np.float32) for k, v in shapes.items()}
    path = directory / "sf-test.npz"
    sha = sf.save_package(path, CONFIG, w(bn.expected_shapes(SMALL, **bn.DIMS)), w(un.head_shapes(CONFIG)),
                          w(sf.cand_shapes(CONFIG)), {"note": "test"})
    return str(path), sha


@pytest.fixture(scope="module")
def package(tmp_path_factory):
    return synthetic_package(tmp_path_factory.mktemp("sf"))


@pytest.fixture
def relaxed_env(package, monkeypatch):
    """The relaxed level on the small package, over the cheap ``smart`` bot as the served one."""
    monkeypatch.setattr(server, "RELAXED_SF_PACKAGE", package[0])
    monkeypatch.setattr(server, "RELAXED_SF_SHA256", package[1])
    monkeypatch.setenv("SHENGJI_BOT", "smart")
    return "smart-" + rp.casual_suffix(package[1])


def test_the_relaxed_level_is_pinned_and_its_name_differs_from_the_served_one():
    assert server.RELAXED_SF_SHA256 == rp.CASUAL_SHA256
    assert server.RELAXED_BOT == rp.casual_suffix() == "relax-sf516617b8-t1-d4"
    assert server.RELAXED_SF_PACKAGE.endswith(rp.CASUAL_PACKAGE) and rp.CASUAL_SHA256[:8] in rp.CASUAL_PACKAGE
    assert (rp.CASUAL_TAU, rp.CASUAL_DELTA) == (1.0, 4.0)
    assert server.RELAXED_BOT not in REGISTRY


def test_a_relaxed_room_wraps_the_served_bot_and_a_default_room_builds_it_alone(monkeypatch, tmp_path):
    calls = []

    def fake_make_bot(name, **kw):
        calls.append((name, kw))
        return HeuristicBot()

    def fake_relaxed(served, seed):
        calls.append(("relaxed", seed))
        return HeuristicBot()
    monkeypatch.setattr(server, "make_bot", fake_make_bot)
    monkeypatch.setattr(server, "make_relaxed_bot", fake_relaxed)
    monkeypatch.setenv("SHENGJI_BOT", "heuristic")
    server.Room(code="AAAA", log_dir=tmp_path, bot_seed=5)
    room = server.Room(code="BBBB", log_dir=tmp_path, bot_seed=6, relaxed_bots=True)
    server.Room(code="CCCC", log_dir=tmp_path, bot_seed=7, matched=True)
    assert calls == [("heuristic", {"seed": 5}), ("heuristic", {"seed": 6}), ("relaxed", 6),
                     ("heuristic", {"seed": 7})]
    assert room.relaxed_bots


def test_a_missing_scorer_package_plays_the_served_bot_and_logs_the_room_served(monkeypatch, tmp_path, package):
    monkeypatch.setenv("SHENGJI_BOT", "smart")
    monkeypatch.setattr(server, "RELAXED_SF_PACKAGE", str(tmp_path / "absent.npz"))
    room = server.Room(code="MISS", log_dir=tmp_path, bot_seed=3, relaxed_bots=True)
    assert room.bot.policy_name == "smart" and room.relaxed_bots is False
    monkeypatch.setattr(server, "RELAXED_SF_PACKAGE", package[0])
    monkeypatch.setattr(server, "RELAXED_SF_SHA256", "0" * 64)          # wrong hash: refused
    room = server.Room(code="BADH", log_dir=tmp_path, bot_seed=3, relaxed_bots=True)
    assert room.bot.policy_name == "smart" and room.relaxed_bots is False


def test_a_ranked_room_refuses_relaxed_bots(tmp_path):
    with pytest.raises(ValueError):
        server.Room(code="DDDD", log_dir=tmp_path, matched=True, relaxed_bots=True)
    with pytest.raises(ValueError):
        asyncio.run(server.start_matched_room(None, [], {}, mode="ranked", relaxed_bots=True))


def _round_start(room, tmp_path):
    room.game = Game(random.Random(3))
    room.game.start_round()
    room.seats = [server.Seat(str(s), is_bot=True) for s in range(4)]
    server._log_round_start(room)
    records = [json.loads(line) for line in (tmp_path / f"{room.code}.jsonl").open()]
    start, = [r for r in records if r["e"] == "round_start"]
    return start


def test_round_start_names_the_bot_policy_and_the_relaxed_switch(relaxed_env, tmp_path):
    served = _round_start(server.Room(code="EEEE", log_dir=tmp_path, bot_seed=1), tmp_path)
    relaxed = _round_start(server.Room(code="FFFF", log_dir=tmp_path, bot_seed=1,
                                       relaxed_bots=True), tmp_path)
    assert served["bot_policy"] == "smart" and served["relaxed_bots"] is False
    assert relaxed["bot_policy"] == relaxed_env != "smart" and relaxed["relaxed_bots"] is True
    assert relaxed["ranked"] is False


def test_the_room_table_frame_carries_the_setting(tmp_path):
    room = server.Room(code="GGGG", log_dir=tmp_path, bot=server.HeuristicBot(), relaxed_bots=True)
    room.seats = [server.Seat(str(s), is_bot=True) for s in range(4)]
    assert server.room_table_frame(room, 0)["settings"]["relaxed_bots"] is True


def _play_state(seed):
    """A round in its play phase, dealt, declared and buried by the served (``smart``) bot."""
    game = Game(random.Random(seed))
    bot = make_bot("smart", seed=seed)
    play_env.prepare_round(game, [bot] * 4)
    return game


def test_the_relaxed_bot_plays_through_the_server_path_and_repeats_its_decisions(relaxed_env, tmp_path):
    async def scenario(code):
        game = _play_state(11)
        rnd = game.round
        room = server.Room(code=code, game=game, log_dir=tmp_path, bot_seed=21, relaxed_bots=True,
                           seats=[server.Seat(str(s), is_bot=True) for s in range(4)])
        assert room.relaxed_bots and room.bot.policy_name == relaxed_env
        room.ids = [dict(enumerate(hand)) for hand in rnd.hands]
        room._kitty_given = True
        played = []
        started = time.perf_counter()
        for _ in range(8):                  # two tricks: leads and follows
            seat = rnd.turn
            before = len(rnd.hands[seat])
            prepared = await server._paced_bot_step(room, seat, minimum_turn_seconds=0)
            assert prepared is not None
            assert prepared.decision.snapshot.bot_copy.policy_name == relaxed_env
            cards = list(prepared.decision.cards)
            assert server._commit_bot_turn(room, prepared)
            server._log_bot_timing(room, prepared, acted=True)
            assert len(rnd.hands[seat]) < before
            played.append((seat, sorted(cards)))
        return played, time.perf_counter() - started

    first, seconds = asyncio.run(scenario("HHHH"))
    second, _ = asyncio.run(scenario("HHHI"))
    assert first == second
    # latency smoke: a relaxed play is one small forward
    assert seconds / len(first) < 10.0
    records = [json.loads(line) for line in (tmp_path / "HHHH.jsonl").open()]
    timing = [r for r in records if r["e"] == "bot_timing"]
    assert timing and {r["policy"] for r in timing} == {relaxed_env}


def _decision_states(seed, every=3):
    """Play states of a heuristic round, each just before a decision."""
    bots = [HeuristicBot() for _ in range(4)]
    game = Game(random.Random(seed))
    rnd = play_env.prepare_round(game, bots)
    k = 0
    while rnd.phase == "play":
        seat = rnd.turn
        if k % every == 0:
            yield copy.deepcopy(rnd), seat
        k += 1
        rnd.play(seat, bots[seat].decide_play(rnd, seat))
        play_env.observe_committed_play(rnd, bots)


def test_every_relaxed_play_is_a_proposal_within_delta_of_the_scorers_best(package):
    from shengji.ai.belief_numpy import decision_inputs
    from shengji.ai.refusal import RefusalLedger
    model = rp.casual_model(package[0], package[1])
    redrawn = checked = 0
    for seed in (31, 32, 33):
        for rnd, seat in _decision_states(seed):
            bot = rp.build_casual(HeuristicBot(), package[0], seed=seed, sha256=package[1])
            played = sorted(bot.decide_play(copy.deepcopy(rnd), seat))
            anchor = list(HeuristicBot().decide_play(rnd, seat))
            inp = decision_inputs(rnd, seat, RefusalLedger().observe(rnd))
            states = model.trunk_states(inp)
            actions = sf.propose(rnd, seat, anchor, states["card_logits"], cap=sf.CAP)["actions"]
            assert played in [sorted(a) for a in actions]          # never a non-proposed play
            if len(actions) == 1:
                continue
            _, logits = model.score(inp, states, [sf.candidate_token(rnd, seat, a) for a in actions])
            v = logits[[sorted(a) for a in actions].index(played)]
            assert v >= logits.max() - rp.CASUAL_DELTA - 1e-5      # never outside the near-best set
            checked += 1
            redrawn += v < logits.max()
    assert checked >= 20 and redrawn >= 1                          # the noise is live


def test_the_mistake_dashboard_excludes_relaxed_rounds(tmp_path):
    from scripts import mistake_dashboard as md
    src = md.__file__.replace("scripts/mistake_dashboard.py", "tests/fixtures/mistake_dashboard/prod_rounds.jsonl")
    lines = [json.loads(line) for line in open(src)]
    base, _ = md.load_prod([src])
    assert base
    for rec in lines:
        if rec.get("e") == "round_start":
            rec["relaxed_bots"] = True
    relaxed = tmp_path / "relaxed.jsonl"
    relaxed.write_text("".join(json.dumps(r) + "\n" for r in lines))
    rounds, notes = md.load_prod([str(relaxed)])
    assert rounds == [] and notes["rounds excluded: relaxed bots"] >= len(base)


def test_a_relaxed_room_is_never_an_open_table_but_its_code_still_seats(tmp_path):
    def room(code, relaxed):
        game = Game(random.Random(5))
        game.start_round()
        r = server.Room(code=code, game=game, log_dir=tmp_path, bot=server.HeuristicBot(),
                        relaxed_bots=relaxed, allow_joiners=True,
                        seats=[server.Seat("Ann")] + [server.Seat(f"Bot {i}", is_bot=True) for i in (1, 2, 3)])
        r.seats[0].connected = True
        server.rooms[code] = r
        return r
    try:
        plain, relaxed = room("PLNA", False), room("RLXA", True)
        assert server._open_seats(plain) == [1, 2, 3]
        assert server._open_seats(relaxed) == []                       # never offered
        assert server._open_seats(relaxed, invite=True) == [1, 2, 3]   # the code joins
        assert "RLXA" not in {t["code"] for t in server.open_tables()}
        assert "PLNA" in {t["code"] for t in server.open_tables()}
    finally:
        server.rooms.pop("PLNA", None)
        server.rooms.pop("RLXA", None)
