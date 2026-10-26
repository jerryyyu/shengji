"""The OPTIONAL capacity-aware draw of the S17 belief proposal
(``belief_capacity``, `train.belief_seq.sample_worlds_capacity` inside
`ai.belief_numpy.BeliefProposal`).

Witnesses: off, the production, release-45 and ``bw`` names and digests are
unchanged; on, the name gains ``-bwc`` after ``-bw`` and the digest names the
capacity proposal; the flag needs ``belief_worlds``; the draw keeps sizes, the
feasible mask and completability exactly, is seeded, and bounds the trumps a
non-banker's hidden kitty takes against the marginals' near-zero kitty mass
(a reweighting, not a hard cap: the leak is the forced tail, measured here
against the plain draw on the same copy orders); the served draw with the
flag is history-legal, seeded, recorded and reaches the live consumer.
"""
import copy
from collections import Counter

import numpy as np
import pytest

from shengji.ai import belief_numpy as bn
from shengji.ai import history_legality as HL
from shengji.ai.memory import Memory
from shengji.engine.cards import TRUMP
from shengji.rl.encode import CARD_INDEX
from shengji.train import belief_seq as bs
from shengji.train import pv_search_policy as pv
from test_refusal_constraints import PRODUCTION_ENV, PRODUCTION_NAME, PRODUCTION_SHA
from test_world_history_legal import RELEASE45_ENV, RELEASE45_NAME, W, fixture, served
from test_pv_belief_worlds import BELIEF_KEYS, _SHAS, names, package, production_package  # noqa: F401
from test_encoder_round_compat import pinned_production_package  # noqa: F401

#: the S17 package the v86 arm serves (`s17_full_h.npz`) and that arm's name
S17_SHA = "cb02e1b67ecd6910d44a5928bf626f54fbe22606a3f04404332c738246f33acb"
BW_NAME = "pv-search-491ee4bf-w64-k8-div-rc-whl-whd-bw-tb-la-dtr-vd-rf3d08fa0-bury-hybrid-bwv-358a544ea5fb"
FLAG = "SHENGJI_PV_BELIEF_CAPACITY"


def bw_env(ckpt, sha):
    return {**RELEASE45_ENV, "SHENGJI_PV_WORLD_HISTORY_LEGAL": "1",
            "SHENGJI_PV_WORLD_HISTORY_DRAW": "1", "SHENGJI_PV_BELIEF_WORLDS": "1",
            "SHENGJI_PV_BELIEF_CKPT": ckpt, "SHENGJI_PV_BELIEF_SHA256": sha}


def test_names_unchanged_off_and_distinct_on(production_package):
    _SHAS["s17_full_h.npz"] = S17_SHA
    assert names(PRODUCTION_ENV) == [PRODUCTION_NAME]
    assert names(RELEASE45_ENV) == [RELEASE45_NAME]
    bw = bw_env("s17_full_h.npz", S17_SHA)
    assert names(bw) == [BW_NAME]
    assert names({**bw, FLAG: "0"}) == [BW_NAME]
    bwc, = names({**bw, FLAG: "1"})
    assert "-whl-whd-bw-bwc-tb-" in bwc and bwc != BW_NAME
    assert bwc.split("-bury-")[1].startswith("hybrid-bwv-")
    _SHAS.pop("s17_full_h.npz")
    base = pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA, serving_budget_seconds=3.0,
                             world_history_legal=True, world_history_draw=True,
                             belief_worlds=True, belief_sha256=S17_SHA)
    on = pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA, serving_budget_seconds=3.0,
                           world_history_legal=True, world_history_draw=True,
                           belief_worlds=True, belief_sha256=S17_SHA, belief_capacity=True)
    pb, po = pv.recipe_payload(base), pv.recipe_payload(on)
    assert "belief_capacity" not in pb and po["belief_capacity"] is True
    assert pb["belief_worlds_package"]["proposal"] == bn.PROPOSAL
    assert po["belief_worlds_package"]["proposal"] == bn.PROPOSAL_CAPACITY
    assert {k: v for k, v in po["belief_worlds_package"].items() if k != "proposal"} == \
        {k: v for k, v in pb["belief_worlds_package"].items() if k != "proposal"}
    assert pv.recipe_digest(base) != pv.recipe_digest(on)
    assert pv.RULE_FLAGS["BELIEF_CAPACITY"] == "belief_capacity"
    assert pv.SAMPLER_DEFAULTS["belief_capacity"] is False
    assert pv.RULE_TOKENS[pv.RULE_TOKENS.index(("belief_worlds", "bw")) + 1] == \
        ("belief_capacity", "bwc")


def test_flag_contract(production_package):
    with pytest.raises(pv.PVSearchPolicyError, match="requires belief_worlds"):
        pv.recipe_payload(pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA,
                                            belief_capacity=True))
    with pytest.raises(pv.PVSearchPolicyError, match="requires belief_worlds"):
        pv.recipe_payload(pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA,
                                            world_history_legal=True, world_history_draw=True,
                                            belief_capacity=True))
    with pytest.raises(pv.PVSearchPolicyError, match="requires belief_worlds"):
        served(world_history_legal=True, world_history_draw=True, belief_capacity=True)
    with pytest.raises(pv.PVSearchPolicyError, match="must be 0 or 1"):
        pv.pv_env_recipe({**PRODUCTION_ENV, FLAG: "yes"})
    with pytest.raises(pv.PVSearchPolicyError, match="requires belief_worlds"):
        names({**RELEASE45_ENV, FLAG: "1"})
    assert "belief_capacity" not in pv.pv_env_recipe({**RELEASE45_ENV, FLAG: "0"})
    assert served(world_history_legal=True, world_history_draw=True, belief_worlds=True,
                  belief_sha256=S17_SHA).belief_capacity is False
    assert served(world_history_legal=True, world_history_draw=True, belief_worlds=True,
                  belief_sha256=S17_SHA, belief_capacity=True).belief_capacity is True


# ------------------------------------------------------------------ the draw

def starved_kitty():
    """50 unknown copies for three 14-card hands and an 8-card kitty, every
    copy feasible everywhere; the first 20 ("trumps") have NO kitty mass, the
    other 30 are uniform.  Projected, the marginals expect ~0 kitty trumps."""
    n_c = np.zeros(bs.N_CARDS, np.int64)
    n_c[:50] = 1
    M = np.zeros((bs.N_CARDS, bs.N_RECV), bool)
    M[:50] = True
    sizes = np.array([14, 14, 14, 8])
    P = np.zeros((bs.N_CARDS, bs.N_RECV))
    P[:20] = [1 / 3, 1 / 3, 1 / 3, 0.0]
    P[20:50] = 0.25
    Q = bs.project_sizes(P, n_c, sizes, M)
    assert (Q[:20, 3] * n_c[:20]).sum() < 1e-6
    return Q, n_c, M, sizes


def test_capacity_draw_keeps_sizes_mask_and_completability_and_is_seeded():
    Q, n_c, M, sizes = starved_kitty()
    for seed in (9, 10):
        worlds = bs.sample_worlds_capacity(Q, n_c, M, sizes, 50, np.random.default_rng(seed))
        assert worlds.shape == (50, bs.N_CARDS, bs.N_RECV) and worlds.dtype == np.int16
        assert (worlds.sum(-1) == n_c[None]).all()
        assert (worlds.sum(1) == sizes[None]).all()
        assert not (worlds[:, ~M] > 0).any()
    a = bs.sample_worlds_capacity(Q, n_c, M, sizes, 50, np.random.default_rng(9))
    b = bs.sample_worlds_capacity(Q, n_c, M, sizes, 50, np.random.default_rng(9))
    c = bs.sample_worlds_capacity(Q, n_c, M, sizes, 50, np.random.default_rng(10))
    assert (a == b).all() and not (a == c).all()
    # a receiver no copy may fill is an infeasible state, as for the plain draw
    tight = M.copy()
    tight[:, 3] = False
    with pytest.raises(bs.BeliefSeqError, match="infeasible"):
        bs.sample_worlds_capacity(np.where(tight, Q, 0.0), n_c, tight, sizes, 4,
                                  np.random.default_rng(0))
    with pytest.raises(bs.BeliefSeqError, match="nonnegative"):
        bs.sample_worlds_capacity(np.where(M, -1.0, 0.0), n_c, M, sizes, 4,
                                  np.random.default_rng(0))


def test_capacity_draw_bounds_the_kitty_trumps_the_plain_draw_forces():
    """The plain draw fills an under-filled kitty at the end with whatever is
    left, so copies with no kitty mass land there; the capacity draw raises
    the kitty's weight while it runs behind, so the forced tail is rare.  On
    the same 16 copy orders (seeded), per order and in all."""
    Q, n_c, M, sizes = starved_kitty()
    plain, capacity, worst = [], [], 0
    for seed in range(16):
        p = bs.sample_worlds(Q, n_c, M, sizes, 200, np.random.default_rng(seed))[:, :20, 3].sum(1)
        c = bs.sample_worlds_capacity(Q, n_c, M, sizes, 200,
                                      np.random.default_rng(seed))[:, :20, 3].sum(1)
        assert c.mean() <= p.mean()
        plain.append(p.mean())
        capacity.append(c.mean())
        worst = max(worst, int(c.max()))
    assert np.mean(plain) > 0.2
    assert np.mean(capacity) < 0.15
    assert np.mean(capacity) < np.mean(plain) / 2
    assert worst <= 3


class NoKittyTrumps:
    """A stand-in belief model: uniform over each copy's feasible receivers,
    except that a trump has no kitty mass (what the S17 marginals say at a
    non-banker's early decision)."""

    def __init__(self, rnd):
        codes = sorted(CARD_INDEX, key=CARD_INDEX.get)
        self.trump = np.array([rnd.ordering.eff_suit(c) == TRUMP for c in codes])

    def marginals(self, inp):
        P = np.asarray(inp["M"], bool).astype(float)
        P[self.trump, 3] = 0.0
        s = P.sum(-1, keepdims=True)
        return np.where(s > 0, P / np.where(s > 0, s, 1.0), 0.0)


def test_served_proposal_with_capacity_leaks_fewer_kitty_trumps_on_real_states():
    """Through `BeliefProposal` (real inputs, mask, projection, constraints):
    on every non-banker state with a hidden kitty, 64 worlds per draw."""
    from test_world_history_draw import states
    trumps = {False: [], True: []}
    for rnd, seat in states(n_games=6):
        if seat == rnd.banker:
            continue
        model = NoKittyTrumps(rnd)
        constraints = HL.draw_constraints(rnd, seat)
        mem = Memory(rnd, seat, own_kitty=True)
        for capacity in (False, True):
            propose = bn.BeliefProposal(model, rnd, seat, (), seed=3, batch=64,
                                        forbidden=constraints, capacity=capacity)
            assert propose.kitty_hidden
            for _ in range(64):
                hands, buried = propose(rnd, seat, mem)
                assert len(buried) == len(rnd.buried)
                trumps[capacity].append(sum(rnd.ordering.eff_suit(c) == TRUMP for c in buried))
    assert len(trumps[True]) == len(trumps[False]) >= 40 * 64
    plain, capacity = np.mean(trumps[False]), np.mean(trumps[True])
    assert capacity < plain
    assert capacity < 0.2


def test_the_capacity_proposal_never_deals_a_forbidden_twin(package):
    from test_world_history_draw import breaks_constraints, states
    model = bn.load_belief_numpy(package["path"], package["sha256"])
    checked = constrained = 0
    for rnd, seat in states(n_games=4):
        constraints = HL.draw_constraints(rnd, seat)
        propose = bn.BeliefProposal(model, rnd, seat, (), seed=3, batch=16, forbidden=constraints,
                                    capacity=True)
        mem = Memory(rnd, seat, own_kitty=True)
        for _ in range(16):
            hands, _ = propose(rnd, seat, mem)
            full = [hands.get(s, rnd.hands[s]) for s in range(4)]
            assert not breaks_constraints(constraints, full, rnd.ordering)
            for s in range(4):
                assert len(full[s]) == len(rnd.hands[s])
            checked += 1
        constrained += bool(constraints)
    assert checked > 100 and constrained > 3


# ------------------------------------------------------------------ the served draw

def belief_bot(package, seed=7, capacity=True):
    bot = served(seed=seed, world_history_legal=True, world_history_draw=True, belief_worlds=True,
                 belief_sha256=package["sha256"], belief_capacity=capacity)
    bot.belief_model = bn.load_belief_numpy(package["path"], package["sha256"])
    return bot


def test_served_draw_with_capacity_is_history_legal_seeded_and_recorded(package):
    _, now, seat = fixture()
    bot = belief_bot(package)
    worlds, _ = bot._worlds(copy.deepcopy(now), seat)
    stats = bot._last_sampling
    assert len(worlds) == W
    assert stats["belief_fallback"] == 0 and stats["belief_proposed"] >= W
    mem = Memory(now, seat, own_kitty=True)
    hidden = sum((Counter(h) for s, h in enumerate(worlds[0][0]) if s != seat), Counter())
    for hands, buried in worlds:
        assert hands[seat] == sorted(now.hands[seat])
        for s in range(4):
            assert len(hands[s]) == len(now.hands[s])
            if s != seat:
                assert not any(now.ordering.eff_suit(c) in mem.voids[s] for c in hands[s])
        assert HL.history_legal(now, seat, hands)
    assert sum(hidden.values()) == sum(len(now.hands[s]) for s in range(4) if s != seat)
    again, _ = belief_bot(package)._worlds(copy.deepcopy(now), seat)
    assert again == worlds
    # the flag changes the draw, not the proposal's stream: the plain arm's
    # worlds on the same seed are a different legal sample of the same state
    plain, _ = belief_bot(package, capacity=False)._worlds(copy.deepcopy(now), seat)
    assert len(plain) == W and plain != worlds
    bot.decide_play(copy.deepcopy(now), seat)
    record = bot.last_decision_record
    assert BELIEF_KEYS <= set(record) and record["belief_fallback"] == 0
    snap = copy.deepcopy(bot)
    assert snap.belief_model is bot.belief_model and snap.belief_capacity is True


def test_any_error_falls_back_to_the_history_legal_draw(package, monkeypatch):
    _, now, seat = fixture()
    bot = belief_bot(package)
    monkeypatch.setattr(bs, "sample_worlds_capacity",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    worlds, _ = bot._worlds(copy.deepcopy(now), seat)
    assert len(worlds) == W
    assert bot._last_sampling["belief_fallback"] == 1
    assert bot._last_sampling["belief_error"] == "RuntimeError"
    assert all(HL.history_legal(now, seat, hands) for hands, _ in worlds)


def test_budget_expiry_is_not_swallowed(package):
    _, now, seat = fixture()
    bot = belief_bot(package)

    def expired():
        raise pv.PVSearchBudgetExceeded("pv-search serving budget expired")
    with pytest.raises(pv.PVSearchBudgetExceeded):
        bot._worlds(copy.deepcopy(now), seat, check_budget=expired)


def test_pinned_serving_factory_snapshot_and_commit(pinned_production_package, package, tmp_path):
    """No stub model or sampler: the enabled env recipe reaches the live
    consumer through the server's snapshot and commit path."""
    import asyncio
    import random
    import tomllib
    from pathlib import Path
    from shengji.api import server as srv
    from shengji.engine.game import Game
    env = tomllib.loads((Path(__file__).resolve().parents[2] / "fly.toml").read_text())["env"]
    env.update(SHENGJI_PV_CKPT=str(pinned_production_package),
               SHENGJI_PV_WORLD_HISTORY_LEGAL="1", SHENGJI_PV_WORLD_HISTORY_DRAW="1",
               SHENGJI_PV_BELIEF_WORLDS="1", SHENGJI_PV_BELIEF_CAPACITY="1",
               SHENGJI_PV_BELIEF_CKPT=package["path"], SHENGJI_PV_BELIEF_SHA256=package["sha256"])
    entries = pv.pv_registry_entries(**pv.pv_env_recipe(env))
    name, = entries
    bot = entries[name](seed=7)
    assert bot.belief_worlds and bot.belief_capacity and "-whl-whd-bw-bwc-" in name
    assert bot.belief_model.package_sha256 == package["sha256"]
    _, rnd, seat = fixture()

    async def scenario():
        game = Game(random.Random(0))
        game.round = rnd
        room = srv.Room(code="BWC", game=game, bot=bot,
                        seats=[srv.Seat(str(s), is_bot=True) for s in range(4)], log_dir=tmp_path)
        room.ids = [dict(enumerate(hand)) for hand in rnd.hands]
        room._kitty_given = True
        room.log_event = lambda kind, **data: None
        before = list(rnd.hands[seat])
        prepared = await srv._paced_bot_step(room, seat, minimum_turn_seconds=0)
        assert prepared is not None
        record = prepared.decision.snapshot.bot_copy.last_decision_record
        assert record["schema"] == pv.RECORD_SCHEMA and record["work_complete"]
        assert record["worlds"] == 64 and BELIEF_KEYS <= record.keys()
        assert record["belief_fallback"] == 0 and record["belief_proposed"] >= 64
        assert srv._commit_bot_turn(room, prepared)
        assert len(rnd.hands[seat]) == len(before) - len(prepared.decision.cards)

    asyncio.run(scenario())


# ------------------------------------------------------------------ release 48

from test_release48_fly_config import (RELEASE48, local_env, pinned_release48_belief_package,  # noqa: E402,F401
                                       served_entries)
from test_release46_fly_config import fly_env  # noqa: E402


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
