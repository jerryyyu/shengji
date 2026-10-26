"""Release 48 with the OPTIONAL greedy-finish top-m restriction (``SHENGJI_PV_LEAF_GREEDY_TOP``, ``-lgft<m>``) and the lead admission
width (``SHENGJI_PV_WIDE_LEAD_K`` with ``SHENGJI_PV_WIDE_LEAD_ADMISSION=1``, ``-wla`` / ``-wla<k>``) on the pinned packages.

Witnesses: off (unset or ``0``), release 48's served name is byte for byte; the two bet-1 arms (``lgft3`` with ``wla24``, ``lgft3``
with ``wla``) have the names below; and the K=32 arm, built from release 48's fly.toml env plus its three settings, plays a lead
through the server's snapshot and commit path on the real packages with the restriction applied.  The package tests run in the CI
package-gate step, where the pinned production and S58 packages are fetched.
"""
import copy

from shengji.ai import belief_numpy as bn
from test_pv_belief_worlds import _SHAS, names, production_package  # noqa: F401
from test_encoder_round_compat import pinned_production_package  # noqa: F401
from test_release48_fly_config import RELEASE48, pinned_release48_belief_package, served_entries  # noqa: F401
from test_release46_fly_config import fly_env

TOP = "SHENGJI_PV_LEAF_GREEDY_TOP"
WLA = "SHENGJI_PV_WIDE_LEAD_ADMISSION"
K = "SHENGJI_PV_WIDE_LEAD_K"
#: release 48 + lgft3 + wla24 and release 48 + lgft3 + wla (K=32)
R48_LGFT3_WLA24 = ("pv-search-491ee4bf-w64-k8-div-rc-whl-whd-bw-tb-ele-wla24-la-dtr-dtrx-vd-vdef-lgf-lgfx-"
                   "lgfd2000-lgft3-ed7-xf7-xfcompactlevel-rfa0358a8-bury-hybrid-bwv-f8bdbc73edd2")
R48_LGFT3_WLA32 = ("pv-search-491ee4bf-w64-k8-div-rc-whl-whd-bw-tb-ele-wla-la-dtr-dtrx-vd-vdef-lgf-lgfx-"
                   "lgfd2000-lgft3-ed7-xf7-xfcompactlevel-r254b2b25-bury-hybrid-bwv-df1710a8bf8c")


def r48_names(env):
    return names({**env, "SHENGJI_PV_CKPT": "smv3out.npz", "SHENGJI_PV_BELIEF_CKPT": "s58.npz"})


def test_release48_name_unchanged_off_and_the_bet1_arms(production_package):
    env = fly_env()
    _SHAS["s58.npz"] = env["SHENGJI_PV_BELIEF_SHA256"]
    try:
        assert r48_names(env) == [RELEASE48]
        assert r48_names({**env, TOP: "0"}) == [RELEASE48]
        assert r48_names({**env, TOP: ""}) == [RELEASE48]
        k24, = r48_names({**env, TOP: "3", WLA: "1", K: "24"})
        k32, = r48_names({**env, TOP: "3", WLA: "1"})
        assert r48_names({**env, TOP: "3", WLA: "1", K: "32"}) == [k32]
    finally:
        _SHAS.pop("s58.npz")
    assert (k24, k32) == (R48_LGFT3_WLA24, R48_LGFT3_WLA32)


def test_release48_lgft3_wla32_plays_a_lead_through_the_server_path(
        pinned_production_package, pinned_release48_belief_package, tmp_path, monkeypatch):
    import asyncio
    import random
    from shengji.api import server as srv
    from shengji.engine.game import Game
    from test_pv_search_serving import _play_state

    monkeypatch.setattr(bn, "PREP_SECONDS", 60.0)
    env = {**fly_env(), TOP: "3", WLA: "1"}
    _, name, factory = served_entries(pinned_production_package, pinned_release48_belief_package, env)
    assert "-wla-" in name and "-lgfd2000-lgft3-" in name
    bot = factory(seed=7)
    assert bot.leaf_greedy_top == 3 and bot.wide_lead_admission is True
    rnd = _play_state()
    seat = rnd.turn
    assert not rnd.trick.plays

    async def scenario():
        game = Game(random.Random(0))
        game.round = rnd
        room = srv.Room(code="LGFT3", game=game, bot=bot,
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
    assert record["wide_lead_admission_k"] == 32 and len(record["admitted"]) > 3
    assert record["leaf_greedy_top_applied"] is True and len(record["leaf_greedy_top_kept"]) == 3
    assert record["admitted_indices"].index(record["selected_index"]) in record["leaf_greedy_top_kept"] \
        or record.get("doomed_throw_reselect_applied") or record.get("exact_lead_status") == "complete"
