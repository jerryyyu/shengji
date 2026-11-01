"""Release 48 with the OPTIONAL capacity-aware belief draw (``SHENGJI_PV_BELIEF_CAPACITY=1``, ``-bwc``) on the pinned packages.

Witnesses: off (unset or ``0``), release 48's served name is byte for byte; on, only ``-bwc`` after ``-bw`` and the recipe and bury
digests move; on the real S58 package the capacity draw puts fewer trumps in a non-banker's hidden kitty than the plain draw; and
release 48's fly.toml env plus the flag serves the capacity proposal through the server's snapshot and commit path.  The package tests
run in the CI package-gate step, where the pinned production and S58 packages are fetched (no torch there: nothing here exports a
package).
"""
import copy

import numpy as np

from shengji.ai import belief_numpy as bn
from shengji.ai import history_legality as HL
from shengji.ai.memory import Memory
from shengji.engine.cards import TRUMP
from shengji.train import belief_seq as bs
from shengji.train import pv_search_policy as pv
from test_pv_belief_worlds import _SHAS, names, production_package  # noqa: F401
from test_encoder_round_compat import pinned_production_package  # noqa: F401

FLAG = "SHENGJI_PV_BELIEF_CAPACITY"

from test_release48_fly_config import RELEASE48, pinned_release48_belief_package, served_entries  # noqa: E402,F401
from test_release48_fly_config import fly_env  # noqa: E402


#: release 48 with ``SHENGJI_PV_BELIEF_CAPACITY=1``
R48_BWC = ("pv-search-491ee4bf-w64-k8-div-rc-whl-whd-bw-bwc-tb-ele-la-dtr-dtrx-vd-vdef-lgf-lgfx-"
           "lgfd2000-ed7-xf7-xfcompactlevel-red111e2f-bury-hybrid-bwv-9125072c7686")


def r48_names(env):
    return names({**env, "SHENGJI_PV_CKPT": "smv3out.npz", "SHENGJI_PV_BELIEF_CKPT": "s58.npz"})


def test_release48_name_unchanged_off_and_bwc_on(production_package):
    """Off (unset or 0), release 48's served name is byte for byte; on, only
    ``-bwc`` after ``-bw`` and the recipe digest move."""
    env = fly_env()
    _SHAS["s58.npz"] = env["SHENGJI_PV_BELIEF_SHA256"]
    try:
        assert r48_names(env) == [RELEASE48]
        assert r48_names({**env, FLAG: "0"}) == [RELEASE48]
        on, = r48_names({**env, FLAG: "1"})
    finally:
        _SHAS.pop("s58.npz")
    assert on == R48_BWC
    # the name moves only in the token after ``-bw`` and the recipe and bury digests
    assert on.split("-r")[0] == RELEASE48.split("-r")[0]
    assert on.replace("-bw-bwc-", "-bw-").split("-xfcompactlevel-")[0] == \
        RELEASE48.split("-xfcompactlevel-")[0]


def test_release48_s58_capacity_draw_cuts_the_kitty_trump_leak(pinned_release48_belief_package):
    """The real S58 package (release 48's belief) on heuristic non-banker states
    with a hidden kitty: the plain draw puts trumps in the kitty (there are none
    in these deals), the capacity draw puts in fewer on the same seeds."""
    from test_world_history_draw import states
    model = bn.load_belief_numpy(str(pinned_release48_belief_package))
    trumps = {False: [], True: []}
    true = 0
    for rnd, seat in states(n_games=6):
        if seat == rnd.banker:
            continue
        true += sum(rnd.ordering.eff_suit(c) == TRUMP for c in rnd.buried)
        constraints = HL.draw_constraints(rnd, seat)
        mem = Memory(rnd, seat, own_kitty=True)
        for capacity in (False, True):
            propose = bn.BeliefProposal(model, rnd, seat, (), seed=3, batch=64,
                                        forbidden=constraints, capacity=capacity)
            for _ in range(64):
                _, buried = propose(rnd, seat, mem)
                trumps[capacity].append(sum(rnd.ordering.eff_suit(c) == TRUMP for c in buried))
    assert true == 0 and len(trumps[True]) >= 40 * 64
    plain, capacity = np.mean(trumps[False]), np.mean(trumps[True])
    assert plain > 0.1
    assert capacity < 0.7 * plain


def test_release48_with_bwc_plays_through_the_server_path(
        pinned_production_package, pinned_release48_belief_package, tmp_path, monkeypatch):
    """Release 48's fly.toml env plus the flag, on the pinned packages: the
    capacity proposal is the one served, with no belief fallback, through
    ``_paced_bot_step`` / ``_commit_bot_turn``."""
    import asyncio
    import random
    from shengji.api import server as srv
    from shengji.engine.game import Game
    from test_pv_search_serving import _play_state

    monkeypatch.setattr(bn, "PREP_SECONDS", 60.0)
    env = {**fly_env(), FLAG: "1"}
    _, name, factory = served_entries(pinned_production_package, pinned_release48_belief_package, env)
    assert "-whl-whd-bw-bwc-tb-" in name and name != RELEASE48
    bot = factory(seed=7)
    assert bot.belief_capacity is True and bot.config.belief_capacity is True
    assert pv.recipe_payload(bot.config)["belief_worlds_package"]["proposal"] == bn.PROPOSAL_CAPACITY
    calls = []
    real = bs.sample_worlds_capacity
    monkeypatch.setattr(bs, "sample_worlds_capacity", lambda *a, **k: calls.append(1) or real(*a, **k))
    rnd = _play_state()
    seat = rnd.turn

    async def scenario():
        game = Game(random.Random(0))
        game.round = rnd
        room = srv.Room(code="BWC48", game=game, bot=bot,
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
    assert record["belief_fallback"] == 0 and record["belief_proposed"] >= 64
    assert calls
