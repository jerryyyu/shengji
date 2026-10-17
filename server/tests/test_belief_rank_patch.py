"""The OPTIONAL rank-aware kitty patch of the S17 belief proposal
(``belief_rank_patch``, ``SHENGJI_PV_BELIEF_RANK_PATCH``,
`ai.belief_numpy.rank_patch_marginals`).

Witnesses: off (unset, empty or ``0``), the served release-46 name from
``fly.toml`` is unchanged; on, the name gains ``-bwr`` after ``-bw`` and the
digest the patch's identity; the flag needs ``belief_worlds``.  The patch leaves
trump-rank-2 marginals untouched, gives each side 2 at another trump rank its
suit's donor kitty probability with the row renormalised, and changes a
rank-4 draw while leaving a rank-2 draw identical.  Correctness and identity
only, not a strength claim.
"""
import copy
import random

import numpy as np
import pytest

from shengji.ai import belief_numpy as bn
from shengji.ai.heuristic import HeuristicBot
from shengji.engine.game import Game
from shengji.train import pv_search_policy as pv
from test_release46_fly_config import BELIEF_SHA, BELIEF_VOLUME_PATH, RELEASE46, fly_env
from test_world_history_legal import served

FLAG = "SHENGJI_PV_BELIEF_RANK_PATCH"
PV_SHA = "491ee4bf81abe783d14f1e004d31ceda1ff2679bd2e14b60a5a9fa96b57c2670"
CODES = bn._codes()
IDX = {c: i for i, c in enumerate(CODES)}


@pytest.fixture
def served_packages(monkeypatch):
    import shengji.ai.cwv_policy as cwv
    monkeypatch.setattr(cwv, "checkpoint_id", lambda path: PV_SHA[:8])
    monkeypatch.setattr(pv, "file_sha256", lambda path: {BELIEF_VOLUME_PATH: BELIEF_SHA}[str(path)])


def names(env):
    return list(pv.pv_registry_entries(**pv.pv_env_recipe(env)))


# ------------------------------------------------------------------ identity

def test_served_name_unchanged_off_and_distinct_on(served_packages):
    env = fly_env()
    assert FLAG not in env
    for off in ({}, {FLAG: ""}, {FLAG: "0"}):
        assert names({**env, **off}) == [env["SHENGJI_BOT"]] == [RELEASE46]
    on, = names({**env, FLAG: "1"})
    assert on != RELEASE46
    assert "-whl-whd-bw-bwr-tb-" in on
    # only the token and the two digests differ
    assert on.replace("-bwr", "").split("-r")[0] == RELEASE46.split("-r")[0]
    assert on.split("-bury-")[0][-9:] != RELEASE46.split("-bury-")[0][-9:]
    tokens = [t for _, t in pv.RULE_TOKENS]
    assert tokens.index("bwr") == tokens.index("bw") + 1


def test_payload_carries_the_patch_only_when_on():
    base = dict(checkpoint_sha256="f" * 64, world_history_legal=True, world_history_draw=True,
                belief_worlds=True, belief_sha256="a" * 64)
    off = pv.recipe_payload(pv.PVSearchConfig(**base))
    assert "belief_rank_patch" not in off and "rank_patch" not in off["belief_worlds_package"]
    on = pv.recipe_payload(pv.PVSearchConfig(**base, belief_rank_patch=True))
    assert on == {**off, "belief_rank_patch": True,
                  "belief_worlds_package": {**off["belief_worlds_package"],
                                            "rank_patch": bn.RANK_PATCH}}
    assert pv.recipe_digest(pv.PVSearchConfig(**base)) != pv.recipe_digest(
        pv.PVSearchConfig(**base, belief_rank_patch=True))


def test_flag_contract():
    with pytest.raises(pv.PVSearchPolicyError, match="requires belief_worlds"):
        pv.recipe_payload(pv.PVSearchConfig(checkpoint_sha256="f" * 64, belief_rank_patch=True))
    with pytest.raises(pv.PVSearchPolicyError, match="requires belief_worlds"):
        served(belief_rank_patch=True)
    with pytest.raises(pv.PVSearchPolicyError, match="must be 0 or 1"):
        pv.pv_env_recipe({**fly_env(), FLAG: "yes"})
    bot = served(world_history_legal=True, world_history_draw=True, belief_worlds=True,
                 belief_sha256="a" * 64)
    assert "belief_rank_patch" not in vars(bot)


# ------------------------------------------------------------------ patch math

def trump_of(suit, rank):
    """A stand-in ``eff_suit``: ``T`` for the trump suit and the trump rank."""
    def eff(code):
        if code in ("LJ", "BJ") or code[1:] == rank or code[0] == suit:
            return "T"
        return code[0]
    return eff


def marginals(seed=3):
    rng = np.random.default_rng(seed)
    P = rng.random((54, 4))
    M = np.ones((54, 4), bool)
    P[IDX["D2"]] = [0.5, 0.3, 0.2, 0.0]        # a side 2 ruled out of the kitty
    P[IDX["S3"]] = 0.0                          # no hidden copy: a donor is skipped
    M[IDX["H2"], 3] = False                     # kitty infeasible: left as it is
    P[IDX["H2"], 3] = 0.0
    return P / np.maximum(P.sum(-1, keepdims=True), 1e-12), M


def test_rank_two_is_untouched():
    P, M = marginals()
    out, changed = bn.rank_patch_marginals(P, M, "2", trump_of("C", "2"))
    assert changed == 0 and np.array_equal(out, P)


def test_side_twos_take_the_donor_kitty_mass():
    P, M = marginals()
    out, changed = bn.rank_patch_marginals(P, M, "4", trump_of("C", "4"))
    # C2 is a trump (trump suit), H2's kitty is infeasible: S2 and D2 change
    assert changed == 2
    for code in ("C2", "H2"):
        assert np.array_equal(out[IDX[code]], P[IDX[code]])
    # S3 has no hidden copy and 4 is the trump rank: S2's donor is S5
    assert out[IDX["S2"], 3] == pytest.approx(P[IDX["S5"], 3])
    assert out[IDX["D2"], 3] == pytest.approx(P[IDX["D3"], 3])
    for code in ("S2", "D2"):
        row, old = out[IDX[code]], P[IDX[code]]
        assert row.sum() == pytest.approx(1.0)
        # the hand receivers keep their ratios
        np.testing.assert_allclose(row[:3] / row[:3].sum(), old[:3] / old[:3].sum())
    others = [i for i in range(54) if CODES[i] not in ("S2", "D2")]
    assert np.array_equal(out[others], P[others])
    # the trump rank 3 is skipped as a donor
    out3, _ = bn.rank_patch_marginals(P, M, "3", trump_of("C", "3"))
    assert out3[IDX["D2"], 3] == pytest.approx(P[IDX["D4"], 3])
    # no trump suit: every 2 is a side card (H2 still infeasible)
    _, nt = bn.rank_patch_marginals(P, M, "4", trump_of(None, "4"))
    assert nt == 3


# ------------------------------------------------------------------ integration

class NoKittyTwos:
    """A stand-in model with S17's rank-2 habit: feasible receivers uniform,
    except that no 2 is ever in the kitty."""

    def marginals(self, inp):
        M = np.asarray(inp["M"], bool)
        P = M.astype(np.float64)
        for s in "SHDC":
            P[IDX[s + "2"], 3] = 0.0
        return P / np.maximum(P.sum(-1, keepdims=True), 1.0)


def position(level):
    """A heuristic round dealt at trump ``level``, a few tricks in, at the turn
    of a seat that does not know the kitty and, at a trump rank other than 2,
    with a side 2 the kitty may hold."""
    from shengji.engine.cards import TRUMP
    for game_seed in range(60):
        h = HeuristicBot()
        rnd = Game(random.Random(game_seed), start_level=level).start_round()
        while rnd.phase == "deal":
            seat, _, _ = rnd.deal_next()
            cards = h.decide_declare(rnd, seat)
            if cards:
                rnd.declare(seat, cards)
        for seat in range(4):
            cards = h.decide_declare(rnd, seat, final=True)
            if cards:
                rnd.declare(seat, cards)
        rnd.finalize_declare()
        rnd.bury(rnd.banker, h.decide_bury(rnd, rnd.banker))
        while rnd.phase == "play" and len(rnd.history) < 3:
            rnd.play(rnd.turn, h.decide_play(rnd, rnd.turn))
        seat = rnd.turn
        if rnd.phase != "play" or seat == rnd.banker:
            continue
        inp = bn.decision_inputs(rnd, seat)
        if level == "2" or any(inp["M"][IDX[s + "2"], 3] and rnd.ordering.eff_suit(s + "2") != TRUMP
               for s in "SHDC"):
            return rnd, seat
    raise AssertionError("no fixture position")


def belief_bot(rank_patch):
    rules = dict(world_history_legal=True, world_history_draw=True, belief_worlds=True,
                 belief_sha256="a" * 64)
    if rank_patch:
        rules["belief_rank_patch"] = True
    bot = served(seed=11, **rules)
    bot.belief_model = NoKittyTwos()
    return bot


@pytest.mark.parametrize("level,changes", [("4", True), ("2", False)])
def test_the_patch_changes_only_a_rank_other_than_two(level, changes):
    rnd, seat = position(level)
    off_worlds, _ = belief_bot(False)._worlds(copy.deepcopy(rnd), seat)
    bot = belief_bot(True)
    on_worlds, _ = bot._worlds(copy.deepcopy(rnd), seat)
    stats = bot._last_sampling
    assert stats["belief_fallback"] == 0
    assert (stats["belief_rank_patched"] > 0) is changes
    assert (on_worlds != off_worlds) is changes
    if changes:
        # the off draw never buries a side 2; the patched draw does
        def kitty_twos(worlds):
            return sum(c[1:] == "2" and rnd.ordering.eff_suit(c) != "T"
                       for _, buried in worlds for c in buried)
        assert kitty_twos(off_worlds) == 0 < kitty_twos(on_worlds)
    off_bot = belief_bot(False)
    off_bot._worlds(copy.deepcopy(rnd), seat)
    assert "belief_rank_patched" not in off_bot._last_sampling
