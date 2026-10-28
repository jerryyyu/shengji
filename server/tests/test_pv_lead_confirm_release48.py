"""Release 48 with the OPTIONAL held-out lead confirmation (``SHENGJI_PV_LEAD_CONFIRM=<k>``, ``-lcc<k>``) on the pinned packages.

Witnesses: off (unset, empty or ``0``), release 48's served name is byte for byte; the S71 arms (``lcc32``, ``lcc24``) have the
names below; and the ``lcc32`` arm, built from release 48's fly.toml env plus its one setting, plays a lead through the server's
snapshot and commit path on the real packages with the stage run to a status.  The package tests run in the CI package-gate step,
where the pinned production and S58 packages are fetched.
"""
import copy

from shengji.ai import belief_numpy as bn
from test_pv_belief_worlds import _SHAS, names, production_package  # noqa: F401
from test_encoder_round_compat import pinned_production_package  # noqa: F401
from test_release48_fly_config import RELEASE48, pinned_release48_belief_package, served_entries  # noqa: F401
from test_release46_fly_config import fly_env

LCC = "SHENGJI_PV_LEAD_CONFIRM"
R48_LCC32 = ("pv-search-491ee4bf-w64-k8-div-rc-whl-whd-bw-tb-ele-la-dtr-dtrx-vd-vdef-lgf-lgfx-lgfd2000-ed7-xf7-"
             "xfcompactlevel-lcc32-r9f8f5c05-bury-hybrid-bwv-d12d7acfc860")
R48_LCC24 = ("pv-search-491ee4bf-w64-k8-div-rc-whl-whd-bw-tb-ele-la-dtr-dtrx-vd-vdef-lgf-lgfx-lgfd2000-ed7-xf7-"
             "xfcompactlevel-lcc24-r9ebad48f-bury-hybrid-bwv-25ba2f71ba06")


def r48_names(env):
    return names({**env, "SHENGJI_PV_CKPT": "smv3out.npz", "SHENGJI_PV_BELIEF_CKPT": "s58.npz"})


def test_release48_name_unchanged_off_and_the_s71_arms(production_package):
    env = fly_env()
    _SHAS["s58.npz"] = env["SHENGJI_PV_BELIEF_SHA256"]
    try:
        assert r48_names(env) == [RELEASE48]
        assert r48_names({**env, LCC: "0"}) == [RELEASE48]
        assert r48_names({**env, LCC: ""}) == [RELEASE48]
        k32, = r48_names({**env, LCC: "32"})
        k24, = r48_names({**env, LCC: "24"})
    finally:
        _SHAS.pop("s58.npz")
    assert (k32, k24) == (R48_LCC32, R48_LCC24)


def test_release48_lcc32_plays_a_lead_through_the_server_path(
        pinned_production_package, pinned_release48_belief_package, tmp_path, monkeypatch):
    import asyncio
    import random
    from shengji.api import server as srv
    from shengji.engine.game import Game
    from test_pv_search_serving import _play_state

    monkeypatch.setattr(bn, "PREP_SECONDS", 60.0)
    env = {**fly_env(), LCC: "32"}
    _, name, factory = served_entries(pinned_production_package, pinned_release48_belief_package, env)
    assert "-xfcompactlevel-lcc32-r" in name
    bot = factory(seed=7)
    assert bot.lead_confirm == 32
    # wall clocks lifted so a slow CI runner cannot turn this witness into the stage's budget skip
    # (that branch is test_pv_lead_confirm's): the stage itself is what this test serves
    assert bot.leaf_greedy_deadline_ms == 2000 and bot.serving_budget_seconds == 3.0
    bot.leaf_greedy_deadline_ms = 0
    bot.serving_budget_seconds = None
    rnd = _play_state()
    seat = rnd.turn
    assert not rnd.trick.plays and max(map(len, rnd.hands)) > 7

    async def scenario():
        game = Game(random.Random(0))
        game.round = rnd
        room = srv.Room(code="LCC32", game=game, bot=bot,
                        seats=[srv.Seat(str(s), is_bot=True) for s in range(4)], log_dir=tmp_path)
        room.ids = [dict(enumerate(hand)) for hand in rnd.hands]
        room._kitty_given = True
        room.log_event = lambda kind, **data: None
        prepared = await srv._paced_bot_step(room, seat, minimum_turn_seconds=0)
        assert prepared is not None
        record = copy.deepcopy(prepared.decision.snapshot.bot_copy.last_decision_record)
        assert srv._commit_bot_turn(room, prepared)
        return record

    record = asyncio.run(scenario())
    assert record["work_complete"] and record["worlds"] == 64
    assert record["lead_confirm_status"] in ("applied", "rejected", "no_challenger")
    assert record["lead_confirm_pool"] == 24 and record["lead_confirm_screen_worlds"] == 32
    if record["lead_confirm_status"] != "no_challenger":
        assert record["lead_confirm_worlds"] == 128
    if record["lead_confirm_applied"]:
        assert record["selected_index"] == record["admitted_indices"][-1]
        assert sorted(record["played"]) == sorted(record["lead_confirm_to"])


def test_lead_confirm_keeps_its_server_decision_with_native_paths(
        pinned_production_package, pinned_release48_belief_package, tmp_path, monkeypatch):
    """Release 48 off and with ``lcc32``: the native latency switches change no card, record or sampler stream of a lead
    through the server's snapshot path (the stage's fresh draws included)."""
    import random
    from shengji.api import server as srv
    from shengji.engine.game import Game
    from shengji.train import pv_search_policy as pv
    from test_pv_native_release48 import NATIVE_SWITCHES, _comparable, _counters
    from test_release48_fly_config import apply_to_process, local_env
    from test_pv_search_serving import _play_state

    monkeypatch.setattr(bn, "PREP_SECONDS", 60.0)
    for k in (0, 32):
        env = {**fly_env(), LCC: str(k)}
        apply_to_process(monkeypatch, local_env(
            pinned_production_package, pinned_release48_belief_package, env))
        results = []
        for native in (False, True):
            flags = {pv.LATENCY_SWITCH_ENV[attr]: str(int(native)) for attr in NATIVE_SWITCHES}
            for key, value in flags.items():
                monkeypatch.setenv(key, value)
            _, name, factory = served_entries(
                pinned_production_package, pinned_release48_belief_package, {**env, **flags})
            bot = factory(seed=7)
            assert bot.lead_confirm == k
            assert (name == RELEASE48) is (k == 0)
            assert all(getattr(bot, attr) is native for attr in NATIVE_SWITCHES)
            bot.leaf_greedy_deadline_ms = 0
            bot.serving_budget_seconds = None
            rnd = _play_state()
            game = Game(random.Random(0))
            game.round = rnd
            room = srv.Room(code="LCCN", game=game, bot=bot,
                            seats=[srv.Seat(str(s), is_bot=True) for s in range(4)], log_dir=tmp_path)
            room.ids = [dict(enumerate(hand)) for hand in rnd.hands]
            room._kitty_given = True
            room.log_event = lambda kind, **data: None
            decision = srv._compute_bot_turn(srv._snapshot_bot_turn(room, rnd.turn, "bot"))
            searched = decision.snapshot.bot_copy
            record = searched.last_decision_record
            assert record["work_complete"] and record["worlds"] == 64
            assert ("lead_confirm_status" in record) is bool(k)
            results.append((name, list(decision.cards), _comparable(record),
                            searched.sampler.rng.getstate(), _counters(searched.evaluator)))
            prepared = srv._PreparedBotTurn(decision=decision, compute_seconds=0.0,
                                            pacing_seconds=0.0, turn_seconds=0.0)
            assert srv._commit_bot_turn(room, prepared)
        assert results[0] == results[1], k
