"""The OPTIONAL paired lookahead tree on the pv-search bot ("PUCT v2", #436):
`train.pv_tree_search` / `train.pv_tree_config`, ``SHENGJI_PV_TREE_SIMS``.

Torch-free but for the last section: stub predictors and evaluators on real
rounds, the real legal enumeration, the real sampler and the real engine; the
last section runs the registered bot on a tiny real joint package (skipped
without torch).

Witnesses: (a) names -- unset, every served name (release 36, combo, release
38) is byte-identical and the served classes are built; set, ``-ts<S>`` and a
new digest; (b) IDENTITY -- with ``sims=0`` and release 38's rules the tree bot
plays the mode-off bot's action in every state of several whole deals, with an
equal record and sampler stream, and with ``sims>0`` its PV pass is the
mode-off bot's; (c) contender set edge cases; (d) the significance gate; (e)
pairing by world; (f) the lookahead on a hand-built position, terminal leaves;
(g) the budget skip and abort, the error path; (h) telemetry scalars survive
the screen trace filter; (i) determinism; (j) the real package.
"""
import copy
import math
import pickle
import random
import zlib

import numpy as np
import pytest

from shengji.ai.heuristic import HeuristicBot
from shengji.engine.game import Game
from shengji.harvest.legal import enumerate_legal
from shengji.train import pv_search_policy as pv
from shengji.train import pv_tree_search as tree
from shengji.train.policy_prior import CARD_INDEX
from shengji.train.pv_tree_config import (PVTreeConfig, PVTreeConfigError, TREE_DEFAULTS,
                                          tree_env, tree_token)
from test_policy_world_search import state
from test_pv_admission_rules import (PRODUCTION_ENV, PRODUCTION_NAME, PRODUCTION_SHA,
                                     predict, production_package)  # noqa: F401  (fixture)

COMBO_NAME = "pv-search-491ee4bf-w64-k8-div-rc-tb-rfb4dfc7c-bury-hybrid-9dba7b43087f"
RELEASE38_NAME = "pv-search-491ee4bf-w64-k8-div-rc-tb-la-r7092480e-bury-hybrid-5517ddbd7457"
COMBO_ENV = {**PRODUCTION_ENV, "SHENGJI_PV_ADMISSION_DIVERSITY": "1",
             "SHENGJI_PV_REFUSAL_CONSTRAINTS": "1", "SHENGJI_PV_TIEBREAK_POINTS": "1"}
RELEASE38_ENV = {**COMBO_ENV, "SHENGJI_PV_LEAD_ANCHOR": "1"}
RELEASE38_RULES = dict(admission_diversity=True, refusal_constraints=True,
                       tiebreak_points=True, lead_anchor=True)
SIMS = "SHENGJI_PV_TREE_SIMS"
TREE_KEYS = {"tree_sims", "tree_applied", "tree_skipped", "tree_skipped_budget",
             "tree_contenders", "tree_worlds", "tree_evaluations", "tree_pv_action",
             "tree_q_action", "tree_action", "tree_changed_action", "tree_override",
             "tree_override_blocked", "tree_delta", "tree_se", "tree_z", "tree_mean_abs_d",
             "tree_max_abs_d", "tree_policy_rows", "tree_forced_plays",
             "tree_multi_leads", "tree_refused_throws",
             "tree_terminal_leaves", "tree_value_batches", "tree_seconds"}


class HashEvaluator:
    """Deterministic and world-dependent: a small pseudo-random value per leaf
    (so near-ties are common) plus the root team's banked points."""
    backend = "numpy"
    max_batch = 128

    def __init__(self, scale=0.04):
        self.scale = scale
        self.seen = []

    def score(self, leaves, seat):
        self.seen.extend(leaves)
        out = []
        for r in leaves:
            key = repr((r.hands, len(r.history), r.attacker_points, r.phase)).encode()
            sign = 1.0 if r.is_attacker(seat) else -1.0
            out.append(zlib.crc32(key) / 2 ** 32 * self.scale + sign * r.attacker_points * 1e-3)
        return np.array(out)


def predict_x(X):
    """A policy that depends on its input row (so the acting seat's own
    perspective and world matter), deterministic."""
    X = np.asarray(X, dtype=np.float64)
    weights = np.sin(np.arange(54)[:, None] * 0.37 + np.arange(X.shape[1])[None, :] * 0.011)
    return X @ weights.T


def bot_of(tree_config=None, *, evaluator=None, worlds=4, seed=17, budget=None,
           policy=predict, **rules):
    config = pv.PVSearchConfig(checkpoint_sha256="f" * 64, worlds=worlds, candidates=8,
                               cap=4000, batch_size=128, serving_budget_seconds=budget,
                               tree=tree_config, **rules)
    cls = pv.PVSearchBot if tree_config is None else tree.PVTreeSearchBot
    return cls(policy, evaluator=HashEvaluator() if evaluator is None else evaluator,
               version=2, config=config, checkpoint="/dev/null", seed=seed)


def deal(seed):
    rnd = Game(random.Random(seed)).start_round()
    h = HeuristicBot()
    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        c = h.decide_declare(rnd, seat)
        if c:
            rnd.declare(seat, c)
    for seat in range(4):
        c = h.decide_declare(rnd, seat, final=True)
        if c:
            rnd.declare(seat, c)
    rnd.finalize_declare()
    rnd.bury(rnd.banker, h.decide_bury(rnd, rnd.banker))
    return rnd


def walk(rnd, plays):
    h = HeuristicBot()
    for _ in range(plays):
        rnd.play(rnd.turn, h.decide_play(rnd, rnd.turn))
    return rnd


def craft(bot, matrix_fn, lookahead_fn=None):
    """Replace the PV pass's scores (and optionally the lookahead) by crafted
    matrices; everything else -- admission, worlds, selection, record -- runs."""
    def score_leaves(rnd, seat, actions, worlds, check_budget=None, capture=None):
        matrix = np.asarray(matrix_fn(actions, worlds), dtype=np.float64)
        assert matrix.shape == (len(worlds), len(actions))
        if capture is not None:
            capture[:] = matrix
        return matrix.sum(axis=0), 1
    bot._score_leaves = score_leaves
    if lookahead_fn is not None:
        def lookahead(rnd, seat, actions, worlds, gate=None):
            values = np.asarray(lookahead_fn(actions, worlds), dtype=np.float64)
            assert values.shape == (len(worlds), len(actions))
            return values, {"tree_policy_rows": 0, "tree_forced_plays": 0,
                            "tree_multi_leads": 0, "tree_refused_throws": 0,
                            "tree_terminal_leaves": 0, "tree_value_batches": 1}
        bot._tree_lookahead = lookahead


def flat(means):
    """A PV matrix with the given column means and NO world variance."""
    return lambda actions, worlds: np.tile(np.asarray(means[:len(actions)], dtype=np.float64),
                                           (len(worlds), 1))


def strip(record):
    return {k: v for k, v in record.items()
            if not k.startswith("tree_") and k not in ("seconds",)}


# ------------------------------------------------------------- (a) names, recipe

def names(env):
    return list(pv.pv_registry_entries(**pv.pv_env_recipe(env)))


def test_unset_every_served_name_is_unchanged_and_set_adds_the_token(production_package):
    assert names(PRODUCTION_ENV) == [PRODUCTION_NAME]
    assert names(COMBO_ENV) == [COMBO_NAME]
    assert names(RELEASE38_ENV) == [RELEASE38_NAME]
    assert names({**RELEASE38_ENV, SIMS: ""}) == [RELEASE38_NAME]
    assert "tree" not in pv.pv_env_recipe(RELEASE38_ENV)
    base = pv.PVSearchConfig(checkpoint_sha256=PRODUCTION_SHA)
    assert base.tree is None and "tree" not in pv.recipe_payload(base)
    seen = {RELEASE38_NAME}
    for sims in ("0", "64", "128"):
        name, = names({**RELEASE38_ENV, SIMS: sims})
        assert name.startswith(f"pv-search-491ee4bf-w64-k8-div-rc-tb-la-ts{sims}-r")
        assert "-bury-hybrid-" in name and name not in seen
        seen.add(name)
    name, = names({**PRODUCTION_ENV, SIMS: "64"})
    assert name.startswith("pv-search-491ee4bf-w64-k8-ts64-r") and name != PRODUCTION_NAME
    # the optional knobs move the digest; non-default eps / zmin also show in the name
    default, = names({**RELEASE38_ENV, SIMS: "64"})
    z2, = names({**RELEASE38_ENV, SIMS: "64", "SHENGJI_PV_TREE_ZMIN": "2"})
    z0, = names({**RELEASE38_ENV, SIMS: "64", "SHENGJI_PV_TREE_ZMIN": "0"})
    e1, = names({**RELEASE38_ENV, SIMS: "64", "SHENGJI_PV_TREE_EPS": "0.1"})
    bf, = names({**RELEASE38_ENV, SIMS: "64", "SHENGJI_PV_TREE_BUDGET_FRACTION": "0.4"})
    assert "-ts64-tz2-r" in z2 and "-ts64-tz0-r" in z0 and "-ts64-te0.1-r" in e1
    assert len({default, z2, z0, e1, bf}) == 5
    same, = names({**RELEASE38_ENV, SIMS: "64", "SHENGJI_PV_TREE_ZMIN": "1.0",
                   "SHENGJI_PV_TREE_EPS": "0.05"})
    assert same == default


def test_recipe_payload_carries_every_tree_field_only_when_on():
    config = pv.PVSearchConfig(checkpoint_sha256="f" * 64, tree=PVTreeConfig(sims=64))
    payload = pv.recipe_payload(config)
    assert payload["tree"] == {"sims": 64, "eps": 0.05, "zmin": 1.0, "max_contenders": 4,
                               "lookahead_tricks": 1, "budget_fraction": 0.5,
                               "budget_stop_fraction": 0.8, "schema": "pv-tree-recipe-v1"}
    off = pv.PVSearchConfig(checkpoint_sha256="f" * 64)
    assert pv.recipe_digest(config) != pv.recipe_digest(off)
    assert tree_token(None) == "" and tree_token(PVTreeConfig(sims=7)) == "-ts7"
    with pytest.raises(pv.PVSearchPolicyError):
        pv.recipe_payload(pv.PVSearchConfig(checkpoint_sha256="f" * 64, tree={"sims": 1}))


@pytest.mark.parametrize("env", [
    {SIMS: "-1"}, {SIMS: "1.5"}, {SIMS: "x"}, {SIMS: "5000"},
    {SIMS: "8", "SHENGJI_PV_TREE_EPS": "-0.1"}, {SIMS: "8", "SHENGJI_PV_TREE_EPS": "nan"},
    {SIMS: "8", "SHENGJI_PV_TREE_ZMIN": "-1"}, {SIMS: "8", "SHENGJI_PV_TREE_ZMIN": "x"},
    {SIMS: "8", "SHENGJI_PV_TREE_BUDGET_FRACTION": "0"},
    {SIMS: "8", "SHENGJI_PV_TREE_BUDGET_FRACTION": "0.9"},     # above the stop fraction
    {"SHENGJI_PV_TREE_EPS": "0.1"}, {"SHENGJI_PV_TREE_ZMIN": "2"},   # a knob without SIMS
])
def test_env_refuses_bad_tree_recipes(env):
    with pytest.raises(PVTreeConfigError):
        pv.pv_env_recipe({**PRODUCTION_ENV, **env})


def test_env_parses_the_tree_recipe_and_the_classes_follow():
    recipe = pv.pv_env_recipe({**RELEASE38_ENV, SIMS: "64", "SHENGJI_PV_TREE_ZMIN": "2",
                               "SHENGJI_PV_TREE_EPS": "0.1"})
    assert recipe["tree"] == PVTreeConfig(sims=64, eps=0.1, zmin=2.0)
    assert tree_env({}) is None and tree_env({SIMS: "0"}) == PVTreeConfig(sims=0)
    assert TREE_DEFAULTS["eps"] == 0.05 and TREE_DEFAULTS["zmin"] == 1.0
    assert tree.tree_bot_class(pv.PVSearchBot) is tree.PVTreeSearchBot
    assert tree.tree_bot_class(pv.PVSearchBuryBot) is tree.PVTreeSearchBuryBot
    assert issubclass(tree.PVTreeSearchBuryBot, pv.PVSearchBuryBot)
    with pytest.raises(pv.PVSearchPolicyError):
        tree.tree_bot_class(pv.PVSearchBot, bot_factory=pv.PVSearchBot)
    with pytest.raises(pv.PVSearchPolicyError):       # the tree class refuses a tree-less recipe
        tree.PVTreeSearchBot(predict, evaluator=HashEvaluator(), version=2, checkpoint="/dev/null",
                             config=pv.PVSearchConfig(checkpoint_sha256="f" * 64, worlds=2)
                             ).decide_play(state(), state().turn)


# ------------------------------------------------------------- (b) identity

@pytest.mark.parametrize("rules", [RELEASE38_RULES, {}], ids=["release38", "release36"])
def test_sims0_plays_the_mode_off_action_in_every_state_of_whole_deals(rules):
    """The differential witness: three bots per seat (mode off, sims=0, sims=64)
    with the same seed decide every state of whole deals.  sims=0: the same
    action, the same record (tree fields aside) and the same sampler stream.
    sims=64: the same PV pass (ballot, means) and ``tree_pv_action`` = the
    mode-off selection, so the tree only ever moves OFF a known PV decision."""
    deals = range(71001, 71007) if rules else range(71001, 71004)
    states = applied = changed = 0
    for deal_seed in deals:
        rnd = deal(deal_seed)
        rng = random.Random(deal_seed)
        h = HeuristicBot()
        kw = dict(worlds=4, budget=1e9, **rules)
        off = [bot_of(seed=100 + s, **kw) for s in range(4)]
        ts0 = [bot_of(PVTreeConfig(sims=0), seed=100 + s, **kw) for s in range(4)]
        ts64 = [bot_of(PVTreeConfig(sims=64, zmin=0.0), seed=100 + s, **kw) for s in range(4)]
        while rnd.phase == "play":
            seat = rnd.turn
            a_off = off[seat].decide_play(copy.deepcopy(rnd), seat)
            a_0 = ts0[seat].decide_play(copy.deepcopy(rnd), seat)
            a_64 = ts64[seat].decide_play(copy.deepcopy(rnd), seat)
            r_off, r_0, r_64 = (b[seat].last_decision_record for b in (off, ts0, ts64))
            assert r_off["schema"] == r_0["schema"] == r_64["schema"] == pv.RECORD_SCHEMA
            assert a_0 == a_off
            assert strip(r_0) == strip(r_off)
            assert r_0["tree_skipped"] == "sims0" and r_0["tree_applied"] is False
            assert r_0["tree_action"] == r_0["tree_pv_action"]
            assert r_0["admitted_indices"][r_0["tree_pv_action"]] == r_off["selected_index"]
            state_off = off[seat].sampler.rng.getstate()
            assert ts0[seat].sampler.rng.getstate() == state_off
            assert ts64[seat].sampler.rng.getstate() == state_off
            # sims=64: the PV pass is untouched and the PV decision is the mode-off one
            for key in ("admitted_indices", "value_means", "worlds", "sample_attempts",
                        "value_batches", "value_evaluations"):
                assert r_64[key] == r_off[key], key
            assert r_64["admitted_indices"][r_64["tree_pv_action"]] == r_off["selected_index"]
            assert (a_64 != a_off) == r_64["tree_changed_action"]
            assert r_64["played"] == r_64["admitted"][r_64["tree_action"]] == a_64
            states += 1
            applied += r_64["tree_applied"]
            changed += r_64["tree_changed_action"]
            rnd.play(seat, a_off if rng.random() < 0.7 else h.decide_play(rnd, seat))
    assert states >= (400 if rules else 200), states
    assert applied > states // 10 and changed > 0     # the tree was really exercised


# ------------------------------------------------------------- (c) contender set

def test_contender_set_edges():
    f = tree.contender_set
    assert f([0.3], 0, 0.05, 4) == [0]                                   # K = 1
    assert f([0.5, 0.3, 0.1], 0, 0.05, 4) == [0]                         # one within eps
    assert f([0.5, 0.46, 0.1], 0, 0.05, 4) == [0, 1]
    assert f([0.5, 0.45, 0.1], 0, 0.05, 4) == [0, 1]                     # the boundary is inclusive
    # the cap: the PV decision + the next best by mean (ties by admission order)
    means = [0.50, 0.49, 0.48, 0.47, 0.46, 0.455]
    assert f(means, 0, 0.05, 4) == [0, 1, 2, 3]
    assert f(means, 5, 0.05, 4) == [0, 1, 2, 5]      # b outside the top 4 is still a member
    assert f([0.5, 0.5, 0.5, 0.5, 0.5], 4, 0.05, 4) == [0, 1, 2, 4]
    # b outside eps (possible only with eps below the tie-break epsilon): still a member
    assert f([0.5, 0.49, 0.4], 2, 0.05, 4) == [0, 1, 2]
    assert f([0.5, float("-inf"), 0.49], 0, 0.05, 4) == [0, 2]           # non-finite never joins


def test_k1_and_single_contender_skip_the_tree_and_play_pv():
    rnd = state(); seat = rnd.turn
    bot = bot_of(PVTreeConfig(sims=64), worlds=4)
    craft(bot, flat([0.5, 0.3, 0.2, 0.1, 0.0, -0.1, -0.2, -0.3]),
          lambda a, w: pytest.fail("the lookahead must not run"))
    played = bot.decide_play(copy.deepcopy(rnd), seat)
    record = bot.last_decision_record
    assert record["tree_skipped"] == "single" and record["tree_applied"] is False
    assert record["tree_contenders"] == 1 and record["tree_action"] == 0
    assert played == record["admitted"][0]
    # K = 1 (a forced follow): one admitted candidate
    rnd = walk(state(), 50)
    while len(enumerate_legal(rnd, rnd.turn, cap=4000).actions) != 1:
        walk(rnd, 1)
    seat = rnd.turn
    bot = bot_of(PVTreeConfig(sims=64), worlds=4)
    played = bot.decide_play(copy.deepcopy(rnd), seat)
    record = bot.last_decision_record
    assert len(record["admitted"]) == 1 and record["tree_skipped"] == "single"
    assert played == record["admitted"][0]


def test_cap_of_four_and_sims_rounding():
    rnd = state(); seat = rnd.turn
    seen = {}

    def lookahead(actions, worlds):
        seen["shape"] = (len(worlds), len(actions))
        return np.zeros((len(worlds), len(actions)))
    bot = bot_of(PVTreeConfig(sims=30), worlds=16)
    craft(bot, flat([0.50, 0.49, 0.48, 0.47, 0.46, 0.455, 0.0, 0.0]), lookahead)
    bot.decide_play(copy.deepcopy(rnd), seat)
    record = bot.last_decision_record
    assert record["tree_contenders"] == 4 and seen["shape"] == (7, 4)     # 30 // 4 worlds
    assert record["tree_worlds"] == 7 and record["tree_evaluations"] == 28
    # worlds used never exceed W
    bot = bot_of(PVTreeConfig(sims=4096), worlds=16)
    craft(bot, flat([0.50, 0.49, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]), lookahead)
    bot.decide_play(copy.deepcopy(rnd), seat)
    assert seen["shape"] == (16, 2) and bot.last_decision_record["tree_worlds"] == 16
    # fewer sims than contenders: nothing to pair
    bot = bot_of(PVTreeConfig(sims=1), worlds=16)
    craft(bot, flat([0.50, 0.49, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
          lambda a, w: pytest.fail("the lookahead must not run"))
    bot.decide_play(copy.deepcopy(rnd), seat)
    assert bot.last_decision_record["tree_skipped"] == "sims0"


# ------------------------------------------------------------- (d) the significance gate

def test_paired_override_arithmetic():
    v0 = np.array([[0.50, 0.49], [0.52, 0.47], [0.48, 0.51], [0.50, 0.49]])
    d = np.array([[0.0, 0.2], [0.0, 0.25], [0.0, 0.15]])
    out = tree.paired_override(v0, d, 1, 0, 1.0)
    base, deep = v0[:, 1] - v0[:, 0], d[:, 1] - d[:, 0]
    assert out["delta"] == pytest.approx(base.mean() + deep.mean())
    assert out["se"] == pytest.approx(math.sqrt(base.var(ddof=1) / 4 + deep.var(ddof=1) / 3))
    assert out["z"] == pytest.approx(out["delta"] / out["se"]) and out["override"] is True
    assert tree.paired_override(v0, d, 1, 0, 100.0)["override"] is False
    # |V| = 1: the variance is undefined, se is infinite, b stands -- unless zmin == 0
    one = tree.paired_override(v0, d[:1], 1, 0, 1.0)
    assert one["se"] == math.inf and one["override"] is False and one["z"] == 0.0
    assert tree.paired_override(v0, d[:1], 1, 0, 0.0)["override"] is True
    # zmin == 0 is the sign of delta
    assert tree.paired_override(v0, -d, 1, 0, 0.0)["override"] is False


def _gate_bot(zmin, noise, sims=64, worlds=16):
    """PV: candidate 0 leads candidate 1 by 0.01 in every world.  Lookahead:
    candidate 1 gains ``0.1 +- noise`` (alternating by world), candidate 0 nothing."""
    bot = bot_of(PVTreeConfig(sims=sims, zmin=zmin), worlds=worlds)

    def lookahead(actions, worlds_):
        values = np.tile([0.50, 0.49], (len(worlds_), 1))
        values[:, 1] += 0.1 + noise * np.where(np.arange(len(worlds_)) % 2, 1.0, -1.0)
        return values
    craft(bot, flat([0.50, 0.49, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]), lookahead)
    return bot


def test_override_needs_a_significant_paired_difference():
    rnd = state(); seat = rnd.turn
    # large delta against its se: the tree overrides PV
    bot = _gate_bot(zmin=1.0, noise=0.05)
    played = bot.decide_play(copy.deepcopy(rnd), seat)
    r = bot.last_decision_record
    assert r["tree_applied"] and r["tree_pv_action"] == 0 and r["tree_q_action"] == 1
    assert r["tree_override"] is True and r["tree_override_blocked"] is False
    assert r["tree_action"] == 1 and r["tree_changed_action"] is True
    assert played == r["admitted"][1] == r["played"]
    assert r["selected_index"] == r["admitted_indices"][1] and r["anchor_selected"] is False
    assert r["tree_delta"] == pytest.approx(0.09) and r["tree_z"] > 1.0
    assert r["tree_se"] == pytest.approx(math.sqrt(np.var([0.15, 0.05] * 8, ddof=1) / 16))
    assert r["tree_mean_abs_d"] == pytest.approx(0.05) and r["tree_max_abs_d"] == pytest.approx(0.15)
    assert r["tree_worlds"] == 16 and r["tree_contenders"] == 2
    # the same delta buried in noise: PV stands and the block is recorded
    bot = _gate_bot(zmin=1.0, noise=2.0)
    played = bot.decide_play(copy.deepcopy(rnd), seat)
    r = bot.last_decision_record
    assert r["tree_applied"] and r["tree_q_action"] == 1 and r["tree_action"] == 0
    assert r["tree_override"] is False and r["tree_override_blocked"] is True
    assert r["tree_changed_action"] is False and played == r["admitted"][0]
    assert 0 < r["tree_z"] < 1.0 and r["selected_index"] == r["admitted_indices"][0]
    # zmin = 0 on the same noise: the plain argmax of Q
    bot = _gate_bot(zmin=0.0, noise=2.0)
    assert bot.decide_play(copy.deepcopy(rnd), seat) == r["admitted"][1]
    assert bot.last_decision_record["tree_override"] is True
    # one visited world (sims = 2 over 2 contenders): se infinite, PV stands
    bot = _gate_bot(zmin=1.0, noise=0.0, sims=2)
    assert bot.decide_play(copy.deepcopy(rnd), seat) == r["admitted"][0]
    r1 = bot.last_decision_record
    assert r1["tree_worlds"] == 1 and r1["tree_override_blocked"] is True
    assert r1["tree_se"] is None and r1["tree_z"] == 0.0 and r1["tree_delta"] == pytest.approx(0.09)
    # ... and zmin = 0 still reproduces argmax-Q there
    bot = _gate_bot(zmin=0.0, noise=0.0, sims=2)
    assert bot.decide_play(copy.deepcopy(rnd), seat) == r["admitted"][1]


def test_tree_agreeing_with_pv_and_exact_q_ties_keep_pv():
    rnd = state(); seat = rnd.turn
    bot = bot_of(PVTreeConfig(sims=64, zmin=0.0, eps=1.0), worlds=8)
    # binary-exact numbers: Q = 0.5 + 0 and 0.25 + 0.25 tie exactly at 0.5
    craft(bot, flat([0.5, 0.25, -2.0, -2.0, -2.0, -2.0, -2.0, -2.0]),
          lambda a, w: np.tile([0.5, 0.5], (len(w), 1)))
    bot.decide_play(copy.deepcopy(rnd), seat)
    r = bot.last_decision_record
    assert r["tree_applied"] and r["tree_q_action"] == r["tree_pv_action"] == r["tree_action"] == 0
    assert not r["tree_override"] and not r["tree_override_blocked"] and r["tree_delta"] == 0.0


def test_pv_tiebreak_choice_is_always_a_contender_and_the_reference():
    """With the points tie-break on, the PV decision b may not be the argmax of
    the means; it is still a contender (even under the cap) and the override is
    measured against it."""
    rnd = state(); seat = rnd.turn
    bot = bot_of(PVTreeConfig(sims=64, zmin=1.0), worlds=8, tiebreak_points=True)
    seen = {}

    def lookahead(actions, worlds):
        seen["actions"] = [list(a) for a in actions]
        return np.tile([0.5] * len(actions), (len(worlds), 1))
    # five within eps; serving's own selection decides b
    craft(bot, flat([0.50, 0.50, 0.50, 0.50, 0.495, 0.0, 0.0, 0.0]), lookahead)
    reference = bot_of(None, worlds=8, tiebreak_points=True)
    craft(reference, flat([0.50, 0.50, 0.50, 0.50, 0.495, 0.0, 0.0, 0.0]))
    b_action = reference.decide_play(copy.deepcopy(rnd), seat)
    played = bot.decide_play(copy.deepcopy(rnd), seat)
    r = bot.last_decision_record
    assert r["admitted"][r["tree_pv_action"]] == b_action and b_action in seen["actions"]
    assert len(seen["actions"]) == 4 and played == b_action
    assert r["tiebreak_near_set"] == reference.last_decision_record["tiebreak_near_set"]


# ------------------------------------------------------------- (e) pairing

def test_every_contender_is_evaluated_in_the_same_visited_worlds(monkeypatch):
    rnd = state(); seat = rnd.turn
    bot = bot_of(PVTreeConfig(sims=7, zmin=0.0), worlds=8)
    craft(bot, flat([0.50, 0.49, 0.48, 0.0, 0.0, 0.0, 0.0, 0.0]))
    sampled = {}
    real_worlds = bot._worlds

    def worlds(rnd_, seat_, check_budget=None):
        out = real_worlds(rnd_, seat_, check_budget)
        sampled["worlds"] = out[0]
        return out
    bot._worlds = worlds
    calls = []
    real = tree.afterstate

    def spy(rnd_, seat_, hands, buried, action, **kw):
        index = next(i for i, (h, _) in enumerate(sampled["worlds"]) if h is hands)
        calls.append((index, tuple(action)))
        assert kw == {"finish_trick": False}
        return real(rnd_, seat_, hands, buried, action, **kw)
    monkeypatch.setattr(tree, "afterstate", spy)
    bot.decide_play(copy.deepcopy(rnd), seat)
    r = bot.last_decision_record
    contenders = [tuple(r["admitted"][i]) for i in (0, 1, 2)]
    # 7 sims over 3 contenders = 2 worlds, the FIRST two, each contender once per world
    assert calls == [(w, a) for w in (0, 1) for a in contenders]
    assert r["tree_worlds"] == 2 and r["tree_evaluations"] == 6 and r["tree_contenders"] == 3
    # the depth correction is read against the SAME world's v0
    leaves = bot.evaluator.seen[-6:]
    deep = bot.evaluator.score(leaves, seat).reshape(2, 3)
    d = deep - np.array([[0.50, 0.49, 0.48]] * 2)
    assert r["tree_mean_abs_d"] == pytest.approx(np.abs(d).mean())
    q = np.array([0.50, 0.49, 0.48]) + d.mean(axis=0)
    assert r["tree_q_action"] == int(np.argmax(q))


# ------------------------------------------------------------- (f) the lookahead

def endgame(cards_each):
    """The fixture round walked by the heuristic to the lead with ``cards_each``
    cards per hand.  Trump is spades / rank 2, the banker is seat 0.
    3 cards: seat 1 leads; hands [D2 S2 D2] [DQ D8 C2] [SQ SA C2] [HQ D5 H5].
    2 cards: seat 0 leads; hands [S2 D2] [DQ C2] [SA C2] [HQ H5]."""
    rnd = state()
    h = HeuristicBot()
    while not (len(rnd.hands[0]) == cards_each and not rnd.trick.plays):
        rnd.play(rnd.turn, h.decide_play(rnd, rnd.turn))
    return rnd


def test_lookahead_plays_the_known_policy_continuation_on_a_hand_built_position():
    """``predict`` gives every card its index as log-odds (S 0-12, H 13-25,
    D 26-38, C 39-51 by rank 2..A), so the policy's top action is the legal
    action with the largest index sum.  Seat 1 leads D8:
      seat 2 (void in diamonds: SQ SA C2) plays C2 (39 > 12 > 10) and ruffs;
      seat 3 must follow D5; seat 0 (void: D2 S2 D2) plays D2 (26 > 0);
      C2 was the first rank-2 trump, so seat 2 wins and leads the next trick:
      its top action is the throw [SA SQ] (22), which the engine refuses
      (seat 0 holds higher trumps) and forces down to SQ;
      seat 3 (no trump: HQ H5) plays HQ (23 > 16); seat 0 plays D2 (26 > 0);
      seat 1 must follow trump with C2; seat 0's D2 wins.
    The value head is read there: 14 tricks done, one card each, seat 0 to lead."""
    rnd = endgame(3); seat = rnd.turn
    assert seat == 1 and len(rnd.history) == 12
    assert sorted(rnd.hands[1]) == ["C2", "D8", "DQ"] and sorted(rnd.hands[2]) == ["C2", "SA", "SQ"]
    assert (CARD_INDEX["C2"], CARD_INDEX["SA"], CARD_INDEX["SQ"], CARD_INDEX["D2"],
            CARD_INDEX["S2"], CARD_INDEX["HQ"], CARD_INDEX["H5"]) == (39, 12, 10, 26, 0, 23, 16)
    bot = bot_of(PVTreeConfig(sims=8), worlds=2)
    world = ([list(h) for h in rnd.hands], list(rnd.buried))
    values, stats = bot._tree_lookahead(rnd, seat, [["D8"]], [world])
    leaf, = bot.evaluator.seen
    assert values.shape == (1, 1) and values[0, 0] == bot.evaluator.score([leaf], seat)[0]
    assert len(leaf.history) == 14 and leaf.phase == "play" and leaf.turn == 0
    assert not leaf.trick.plays                                  # a trick boundary
    assert [(p.seat, p.cards) for p in leaf.history[12].plays] == \
        [(1, ["D8"]), (2, ["C2"]), (3, ["D5"]), (0, ["D2"])]
    assert leaf.history[12].winner == 2
    assert [(p.seat, p.cards) for p in leaf.history[13].plays] == \
        [(2, ["SQ"]), (3, ["HQ"]), (0, ["D2"]), (1, ["C2"])]
    assert leaf.history[13].winner == 0
    assert [sorted(h) for h in leaf.hands] == [["S2"], ["DQ"], ["SA"], ["H5"]]
    # seats 2, 0 (trick 13), 2, 3, 0 (trick 14) chose by the model; seat 3's D5 and
    # seat 1's C2 were forced
    assert stats == {"tree_policy_rows": 5, "tree_forced_plays": 2,
                     "tree_multi_leads": 1, "tree_refused_throws": 1,
                     "tree_terminal_leaves": 0, "tree_value_batches": 1}
    # the root round is untouched
    assert len(rnd.history) == 12 and sorted(rnd.hands[1]) == ["C2", "D8", "DQ"]
    # lookahead_tricks = 0 stops when the current trick resolves
    bot0 = bot_of(PVTreeConfig(sims=8, lookahead_tricks=0), worlds=2)
    bot0._tree_lookahead(rnd, seat, [["D8"]], [world])
    leaf0, = bot0.evaluator.seen
    assert len(leaf0.history) == 13 and leaf0.turn == 2 and not leaf0.trick.plays


def test_lookahead_choice_is_the_admissions_scoring_path_from_the_acting_seat():
    """For a clone mid-trick the chosen action is the argmax of serving's own
    `scores` for THAT seat on the clone's own world (first maximum)."""
    rnd = walk(state(), 9)
    bot = bot_of(PVTreeConfig(sims=8), worlds=2, policy=predict_x)
    checked = 0
    for _ in range(12):
        seat = rnd.turn
        clone = copy.deepcopy(rnd)
        (choice,), rows = bot._tree_policy_choices([clone])
        legal = enumerate_legal(clone, seat, cap=bot.cap).actions
        scores = bot.scores(clone, seat, legal, [(clone.hands, clone.buried)])[0]
        assert choice == list(legal[int(np.argmax(scores))])
        assert rows == (len(legal) > 1)
        checked += len(legal) > 1
        walk(rnd, 1)
    assert checked >= 6
    # batched == one at a time (the batch does not leak between clones)
    clones = [walk(copy.deepcopy(state()), n) for n in (3, 4, 5, 9, 10)]
    together, _ = bot._tree_policy_choices(clones)
    assert together == [bot._tree_policy_choices([c])[0][0] for c in clones]


def test_closed_form_top_action_equals_the_enumerated_argmax(monkeypatch):
    """`_tree_top_action` against the reference -- the first maximum of the
    admission's score over `enumerate_legal` -- on states reached by RANDOM
    legal play (so multi-card leads, short and void follows all occur), with
    random real-valued log-odds (the closed forms decide) and with integer
    log-odds full of ties (the enumeration decides)."""
    used = {"lead": 0, "fill": 0, "none": 0}
    real_lead, real_fill = tree.top_lead, tree.top_fill

    def lead(*args):
        out = real_lead(*args)
        used["lead" if out is not None else "none"] += 1
        return out

    def fill(*args):
        out = real_fill(*args)
        used["fill" if out is not None else "none"] += 1
        return out
    monkeypatch.setattr(tree, "top_lead", lead)
    monkeypatch.setattr(tree, "top_fill", fill)
    bot = bot_of(PVTreeConfig(sims=8), worlds=2)
    rng = random.Random(7)
    nprng = np.random.default_rng(7)
    checked = multi = capped = 0
    for deal_seed in (71201, 71202, 71203, 71204):
        rnd = deal(deal_seed)
        while rnd.phase == "play":
            seat = rnd.turn
            legal = enumerate_legal(rnd, seat, cap=bot.cap)
            capped += not legal.complete
            multiplicity = np.zeros((len(legal.actions), 54))
            for i, action in enumerate(legal.actions):
                for card in action:
                    multiplicity[i, CARD_INDEX[card]] += 1
            rows = [nprng.normal(size=54), nprng.normal(size=54) - 1.5,
                    np.arange(54, dtype=np.float64), np.zeros(54),
                    np.round(nprng.normal(size=54))]
            for row in rows:
                want = list(legal.actions[int(np.argmax(multiplicity @ row))])
                assert bot._tree_top_action(rnd, seat, row) == want
                assert bot._tree_top_action(rnd, seat, row, {}) == want
                checked += 1
            forced = bot._tree_forced(rnd, seat, {})
            assert forced == (list(legal.actions[0]) if len(legal.actions) == 1 else None)
            # the follow listing is `enumerate_legal`'s
            assert bot._tree_legal(rnd, seat, None)[0] == [list(a) for a in legal.actions]
            action = rng.choice(legal.actions[:200])
            multi += len(action) > 1 and not rnd.trick.plays
            rnd.play(seat, list(action))
    assert checked > 1000 and multi > 20 and capped > 0
    assert used["lead"] > 100 and used["fill"] > 100 and used["none"] > 100
    # a capped listing is never decided in closed form
    rnd = state(); seat = rnd.turn
    small = bot_of(PVTreeConfig(sims=8), worlds=2)
    small.cap = 50
    row = nprng.normal(size=54)
    legal = enumerate_legal(rnd, seat, cap=50)
    assert not legal.complete and tree.top_lead(rnd.hands[seat], rnd.ordering, row, 50) is None
    scores = small.scores(rnd, seat, legal.actions, [(rnd.hands, rnd.buried)])
    assert small._tree_top_action(rnd, seat, row) == list(legal.actions[int(np.argmax(
        [sum(row[CARD_INDEX[c]] for c in a) for a in legal.actions]))])
    assert scores.shape == (1, 50)


def test_the_legal_set_cache_changes_nothing():
    """Within a decision the legal set is cached per (hand, lead); the lookahead
    with the cache equals the lookahead that enumerates every time."""
    for plays in (0, 9, 22, 35):
        rnd = walk(state(), plays); seat = rnd.turn
        bot = bot_of(PVTreeConfig(sims=8), worlds=6, seed=3, policy=predict_x)
        worlds, _ = bot._worlds(rnd, seat)
        actions = enumerate_legal(rnd, seat, cap=4000).actions[:3]
        cached, stats = bot._tree_lookahead(rnd, seat, actions, worlds)
        plain = bot_of(PVTreeConfig(sims=8), worlds=6, seed=3, policy=predict_x)
        real = plain._tree_legal
        plain._tree_legal = lambda clone, seat_, cache: real(clone, seat_, None)
        uncached, stats2 = plain._tree_lookahead(rnd, seat, actions, worlds)
        assert np.array_equal(cached, uncached) and stats == stats2
        assert [[(p.seat, p.cards) for t in leaf.history for p in t.plays]
                for leaf in bot.evaluator.seen] == \
            [[(p.seat, p.cards) for t in leaf.history for p in t.plays]
             for leaf in plain.evaluator.seen]


def test_terminal_leaves_stop_the_lookahead_and_reach_the_evaluator_as_round_end():
    rnd = endgame(2); seat = rnd.turn
    assert seat == 0 and sorted(rnd.hands[0]) == ["D2", "S2"]
    bot = bot_of(PVTreeConfig(sims=8), worlds=2)
    world = ([list(h) for h in rnd.hands], list(rnd.buried))
    values, stats = bot._tree_lookahead(rnd, seat, [["D2"], ["S2"]], [world])
    assert values.shape == (1, 2)
    assert [leaf.phase for leaf in bot.evaluator.seen] == ["round_end", "round_end"]
    assert all(len(leaf.history) == 15 and not any(leaf.hands) for leaf in bot.evaluator.seen)
    assert stats["tree_terminal_leaves"] == 2
    # a whole decision at the last trick but one runs through the same path
    bot = bot_of(PVTreeConfig(sims=64, zmin=0.0, eps=10.0), worlds=4)
    bot.decide_play(copy.deepcopy(rnd), seat)
    r = bot.last_decision_record
    assert r["tree_applied"] and r["tree_terminal_leaves"] == r["tree_evaluations"] > 0


# ------------------------------------------------------------- (g) budget, errors

def test_budget_skip_when_the_pv_pass_used_the_trees_share(monkeypatch):
    rnd = state(); seat = rnd.turn
    clock = [0.0]
    monkeypatch.setattr(pv.time, "perf_counter", lambda: clock[0])
    bot = bot_of(PVTreeConfig(sims=64, zmin=0.0), worlds=8, budget=10.0)
    means = [0.50, 0.49, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]

    def slow(actions, worlds):
        clock[0] += 6.0                       # 60% of the budget > budget_fraction 0.5
        return flat(means)(actions, worlds)
    craft(bot, slow, lambda a, w: pytest.fail("the lookahead must not run"))
    played = bot.decide_play(copy.deepcopy(rnd), seat)
    r = bot.last_decision_record
    assert r["schema"] == pv.RECORD_SCHEMA and r["work_complete"] is True      # not a fallback
    assert r["tree_skipped"] == "budget" and r["tree_skipped_budget"] is True
    assert r["tree_applied"] is False and r["tree_action"] == r["tree_pv_action"] == 0
    assert played == r["admitted"][0]
    # under the fraction the tree runs
    clock[0] = 0.0
    bot = bot_of(PVTreeConfig(sims=64, zmin=0.0), worlds=8, budget=10.0)
    craft(bot, flat(means), lambda a, w: np.tile([0.5, 0.9], (len(w), 1)))
    assert bot.decide_play(copy.deepcopy(rnd), seat) == r["admitted"][1]
    assert bot.last_decision_record["tree_skipped_budget"] is False


def test_tree_that_would_overrun_abandons_itself_for_the_pv_decision(monkeypatch):
    """The real lookahead under a mocked clock: every policy forward costs 3 s
    of a 10 s budget, so the stop fraction (0.8) is reached inside the tree.
    Nothing of the partial tree is used: the PV decision is played with an
    ordinary record, and the sampler stream is the mode-off bot's."""
    rnd = state(); seat = rnd.turn
    clock = [0.0]
    monkeypatch.setattr(pv.time, "perf_counter", lambda: clock[0])
    calls = []

    def slow_predict(X):
        if calls:                 # the first call is the admission's own forward
            clock[0] += 3.0
        calls.append(len(X))
        return predict(X)
    bot = bot_of(PVTreeConfig(sims=64, zmin=0.0), worlds=8, budget=10.0, policy=slow_predict)
    craft(bot, flat([0.50, 0.49, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]))
    played = bot.decide_play(copy.deepcopy(rnd), seat)
    r = bot.last_decision_record
    assert r["schema"] == pv.RECORD_SCHEMA and r["tree_skipped"] == "budget"
    assert r["tree_skipped_budget"] is True and r["tree_applied"] is False
    assert r["tree_worlds"] == 0 and played == r["admitted"][0]
    assert 3 <= len(calls) <= 4 and clock[0] <= 9.0          # stopped at the first boundary >= 8 s
    off = bot_of(None, worlds=8, budget=10.0)
    craft(off, flat([0.50, 0.49, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]))
    clock[0] = 0.0
    assert off.decide_play(copy.deepcopy(rnd), seat) == played
    assert off.sampler.rng.getstate() == bot.sampler.rng.getstate()
    # no serving budget: no gate, the tree completes whatever the clock says
    clock[0] = 0.0; calls.clear()
    free = bot_of(PVTreeConfig(sims=64, zmin=0.0), worlds=8, policy=slow_predict)
    craft(free, flat([0.50, 0.49, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]))
    free.decide_play(copy.deepcopy(rnd), seat)
    assert free.last_decision_record["tree_applied"] is True


def test_an_error_inside_the_tree_keeps_the_pv_decision_and_is_labelled():
    rnd = state(); seat = rnd.turn
    bot = bot_of(PVTreeConfig(sims=64), worlds=8, budget=1e9)
    craft(bot, flat([0.50, 0.49, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]))

    def broken(*args, **kwargs):
        raise RuntimeError("boom")
    bot._tree_lookahead = broken
    played = bot.decide_play(copy.deepcopy(rnd), seat)
    r = bot.last_decision_record
    assert r["schema"] == pv.RECORD_SCHEMA and played == r["admitted"][0]
    assert r["tree_skipped"] == "error" and r["tree_error"] == "RuntimeError"
    assert r["tree_applied"] is False and r["tree_skipped_budget"] is False


def test_an_expired_serving_budget_is_still_servings_anchor_fallback():
    rnd = state(); seat = rnd.turn
    bot = bot_of(PVTreeConfig(sims=64), worlds=8, budget=1e-9)
    before = bot.sampler.rng.getstate()
    played = bot.decide_play(copy.deepcopy(rnd), seat)
    r = bot.last_decision_record
    assert r["schema"] == pv.FALLBACK_SCHEMA and r["reason"] == "budget"
    assert played == HeuristicBot().decide_play(copy.deepcopy(rnd), seat)
    assert bot.sampler.rng.getstate() == before and not any(k.startswith("tree_") for k in r)


# ------------------------------------------------------------- (h) telemetry

def test_tree_fields_are_scalars_and_survive_the_screen_trace_filter():
    try:      # the screen module needs torch; the scalar contract is checked without it
        from shengji.train.search_screen import trace_fields
    except ImportError:
        def trace_fields(record):
            return {k: v for k, v in record.items()
                    if isinstance(v, (str, int, float, bool, type(None)))}
    rnd = state(); seat = rnd.turn
    for bot in (_gate_bot(1.0, 0.05), _gate_bot(1.0, 2.0), _gate_bot(1.0, 0.0, sims=2),
                bot_of(PVTreeConfig(sims=0)), bot_of(PVTreeConfig(sims=64), **RELEASE38_RULES)):
        bot.decide_play(copy.deepcopy(rnd), seat)
        record = bot.last_decision_record
        assert TREE_KEYS <= set(record)
        kept = trace_fields(record)
        for key in TREE_KEYS:
            assert isinstance(record[key], (str, int, float, bool, type(None))), key
            assert key in kept and kept[key] == record[key]
        assert type(record["tree_applied"]) is bool and type(record["tree_override"]) is bool
        assert record["tree_seconds"] >= 0.0
    # mode off: no tree key at all
    off = bot_of(None, **RELEASE38_RULES)
    off.decide_play(copy.deepcopy(rnd), seat)
    assert not any(k.startswith("tree_") for k in off.last_decision_record)


# ------------------------------------------------------------- (i) determinism

def test_fixed_seed_decisions_and_records_are_reproducible():
    rnd = walk(state(), 8); seat = rnd.turn
    records = []
    for _ in range(2):
        bot = bot_of(PVTreeConfig(sims=64, zmin=0.0, eps=1.0), worlds=8, seed=5,
                     policy=predict_x, **RELEASE38_RULES)
        played = [bot.decide_play(copy.deepcopy(rnd), seat) for _ in range(2)]
        record = dict(bot.last_decision_record)
        assert record["tree_applied"] is True
        record.pop("seconds"); record.pop("tree_seconds")
        records.append((played, record))
    assert records[0] == records[1]
    # the bot survives the server's snapshot (deepcopy) and the screen's pickle
    bot = bot_of(PVTreeConfig(sims=16), worlds=4, seed=5)
    bot.decide_play(copy.deepcopy(rnd), seat)
    twin = copy.deepcopy(bot)
    assert twin.decide_play(copy.deepcopy(rnd), seat) == bot.decide_play(copy.deepcopy(rnd), seat)
    state_ = pickle.loads(pickle.dumps({k: v for k, v in vars(bot).items()
                                        if k not in ("evaluator", "predict")}))
    assert state_["config"].tree == PVTreeConfig(sims=16)


# ------------------------------------------------------------- (j) the real package

from test_pv_search_serving import package  # noqa: E402,F401  (module fixture; needs torch)


def test_registered_tree_bot_on_a_real_package_plays_a_whole_deal(package):
    path, sha = package
    small = dict(worlds=6, candidates=4, cap=400, batch_size=16, bury_arm="hybrid",
                 serving_budget_seconds=60.0, bury_serving_budget_seconds=60.0, **RELEASE38_RULES)
    off_name, = pv.pv_registry_entries(path, sha256=sha, **small)
    entries = pv.pv_registry_entries(path, sha256=sha, tree=PVTreeConfig(sims=12, zmin=0.0, eps=0.5),
                                     **small)
    (name, factory), = entries.items()
    assert "-ts12-te0.5-tz0-r" in name and name != off_name
    (zero_name, zero_factory), = pv.pv_registry_entries(
        path, sha256=sha, tree=PVTreeConfig(sims=0), **small).items()
    off_factory = pv.pv_registry_entries(path, sha256=sha, **small)[off_name]
    rnd = deal(71090)
    bots = [factory(seed=40 + s) for s in range(4)]
    zeros = [zero_factory(seed=40 + s) for s in range(4)]
    offs = [off_factory(seed=40 + s) for s in range(4)]
    assert type(bots[0]) is tree.PVTreeSearchBuryBot and bots[0].policy_name == name
    assert type(offs[0]) is pv.PVSearchBuryBot and type(zeros[0]) is tree.PVTreeSearchBuryBot
    assert bots[0].bury_recipe_identity["play_policy"] in name
    applied = terminal = changed = 0
    while rnd.phase == "play":
        seat = rnd.turn
        action = bots[seat].decide_play(copy.deepcopy(rnd), seat)
        record = bots[seat].last_decision_record
        assert record["schema"] == pv.RECORD_SCHEMA and TREE_KEYS <= set(record)
        assert "tree_error" not in record and record["tree_skipped"] in ("", "single")
        a_off = offs[seat].decide_play(copy.deepcopy(rnd), seat)
        assert zeros[seat].decide_play(copy.deepcopy(rnd), seat) == a_off
        assert strip(zeros[seat].last_decision_record) == \
            {**strip(offs[seat].last_decision_record), "policy": zero_name}
        assert record["admitted"][record["tree_pv_action"]] == a_off
        applied += record["tree_applied"]
        terminal += record["tree_terminal_leaves"]
        changed += record["tree_changed_action"]
        rnd.play(seat, action)
    assert applied > 5 and terminal > 0
    # the served evaluator scores a terminal position exactly, never by the model
    from shengji.rl.value_afterstate import terminal_distribution
    assert rnd.phase == "round_end"
    evaluator = bots[0].evaluator
    rows = evaluator.model_rows
    for seat in range(4):
        assert evaluator.score([rnd], seat)[0] == \
            float(terminal_distribution(rnd, seat) @ evaluator.support)
    assert evaluator.model_rows == rows
