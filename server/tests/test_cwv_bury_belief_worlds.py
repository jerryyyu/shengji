"""The OPTIONAL belief worlds of the wide value-only bury (``bury_belief_worlds``,
``SHENGJI_PV_BURY_BELIEF_WORLDS``, bury token ``bbw``;
`train.bury_wide_value.belief_bury_worlds`): the chooser's ``model_worlds``
worlds drawn by the play's belief package on the bury state's trick-1 twin
instead of the ``mc-s0-report-lcb`` helper's split sampler, with the helper's
worlds as the per-decision fallback, counted in ``bury_belief_fallbacks``.

Torch-free: the wide chooser's stub predictor and evaluators on the real
engine, ballot and leaf, and a random-weight `ai.belief_numpy.BeliefNumpy`.
Witnesses: (a) off: the names, the recipe, the bot's state, the record keys
and the wide chooser's frozen decision/record tape are unchanged and the belief
draw is never called; (b) on: the worlds are the belief proposal's on the twin
(a hand-built proposal reproduces them), complete, card-conserving, with the
banker's own hand and the declaration pins; the helper's sampler is not used;
the play sampler's RNG is untouched; the draw is seeded by the bot seed; (c)
the fallback: no package, a proposal error and an infeasible draw each fall
back to exactly the flag-off decision and count 1; a budget expiry inside the
draw is the heuristic fallback, never a belief fallback; (d) the token, the
identity, the env parsing and the refusals; (e) the served release-49 recipe
with the flag on the hash-pinned packages decides a bury with no fallback; (f)
the room's timing log carries the fallback count for a ``bbw`` bury only.
"""
import asyncio
import copy
import hashlib
import json
import random
from collections import Counter

import numpy as np
import pytest

from shengji.ai import belief_numpy as bn
from shengji.ai.history_legality import draw_constraints
from shengji.api import server
from shengji.engine.game import Game
from shengji.train import bury_wide_value as bwv
from shengji.train import cwv_bury_policy as bury_policy
from shengji.train import pv_search_policy as pv
from test_cwv_bury_wide_value import (BURY, RECORD_KEYS, RELEASE44_BWV64, SWAPS1_TAPE_SHA256,
                                      CountingPredict, TrickEvaluator, SMALL, bury_state,
                                      fly_env, jumping_clock, without_timing)  # noqa: F401
from test_pv_admission_rules import PRODUCTION_ENV, names, production_package  # noqa: F401
from test_encoder_round_compat import pinned_production_package  # noqa: F401
from test_release48_fly_config import local_env, pinned_release48_belief_package  # noqa: F401
from test_release49_fly_config import fly_env as release49_fly_env
from test_release49_fly_config import RELEASE49, served_bot

FLAG = "SHENGJI_PV_BURY_BELIEF_WORLDS"
WIDE = {"SHENGJI_PV_BURY_WIDE_VALUE": "1", "SHENGJI_PV_BURY_WIDE_K": "64"}
BELIEF_RULES = dict(world_history_legal=True, world_history_draw=True, belief_worlds=True,
                    belief_sha256="a" * 64)
ROOTS = tuple(range(60, 72))
BELIEF_FIELDS = ("bury_belief_worlds", "bury_belief_fallbacks", "bury_belief_error",
                 "bury_belief_ms")


def random_belief_model(seed=11):
    rng = np.random.default_rng(seed)
    config = {"d": 16, "heads": 2, "enc_layers": 1, "xattn_layers": 1, "x_hidden": 16,
              "card_self_attn": True}
    shapes = bn.expected_shapes(config, **bn.DIMS)
    # the 1-D weights are the layer norms' gains
    weights = {k: (np.ones(s) if k.endswith(".weight") and len(s) == 1
                   else rng.normal(0.0, 0.2, s)).astype(np.float32) for k, s in shapes.items()}
    return bn.BeliefNumpy(config, weights, {"temperature": 1.0})


MODEL = random_belief_model()


def served_bury(evaluator=None, bury_budget=60.0, seed=17, belief=True, model=MODEL, **rules):
    wide = {k: rules.pop(k) for k in ("bury_wide_value", "bury_wide_k", "bury_wide_swaps",
                                      "bury_two_stage", "bury_kitty_charge",
                                      "bury_belief_worlds") if k in rules}
    config = pv.PVSearchConfig(checkpoint_sha256="f" * 64, **SMALL,
                               **(BELIEF_RULES if belief else {}), **rules)
    bot = pv.PVSearchBuryBot(CountingPredict(), evaluator=evaluator or TrickEvaluator(),
                             version=2, config=config, checkpoint="/dev/null", seed=seed,
                             bury_arm="hybrid", bury_config=BURY,
                             bury_serving_budget_seconds=bury_budget, **wide)
    if belief:
        bot.belief_model = model
    return bot


def bbw(**kw):
    return served_bury(bury_wide_value=True, bury_wide_k=64, bury_belief_worlds=True, **kw)


def decide(bot, index):
    rnd = bury_state(index)
    return bot.decide_bury(copy.deepcopy(rnd), rnd.banker), bot.last_bury_record


def untimed(record):
    wv = {key: v for key, v in record[bwv.RECORD_KEY].items() if key != "seconds"}
    return without_timing({**record, bwv.RECORD_KEY: wv})


def spy_worlds(monkeypatch):
    """The worlds the chooser hands its scorer, per call."""
    seen = []
    real = bwv.score_bury_candidates

    def spy(rnd, candidates, worlds, *a, **k):
        seen.append([tuple(tuple(h) for h in hands) for hands, _ in worlds])
        assert all(buried == [] for _, buried in worlds)
        return real(rnd, candidates, worlds, *a, **k)
    monkeypatch.setattr(bwv, "score_bury_candidates", spy)
    return seen


# ------------------------------------------------------------ (a) off

def test_off_names_recipe_and_state_are_unchanged(production_package):
    assert names({**fly_env(), **WIDE}) == [RELEASE44_BWV64]
    for raw in ("0", ""):
        assert names({**fly_env(), **WIDE, FLAG: raw}) == [RELEASE44_BWV64]
        assert "bury_belief_worlds" not in pv.pv_env_recipe({**PRODUCTION_ENV, **WIDE, FLAG: raw})
        assert "bury_belief_worlds" not in pv.pv_env_recipe({**PRODUCTION_ENV, FLAG: raw})
    assert pv.PVSearchBuryBot.bury_belief_worlds is False
    base = served_bury(bury_wide_value=True, bury_wide_k=64)
    for kw in ({}, {"bury_belief_worlds": False}):
        bot = served_bury(bury_wide_value=True, bury_wide_k=64, **kw)
        assert "bury_belief_worlds" not in vars(bot)
        assert vars(bot).keys() == vars(base).keys()


def test_off_decisions_and_records_reproduce_the_frozen_tape(monkeypatch):
    """The wide chooser's frozen tape (K=32 and K=64 on the DEV roots 60-71)
    with ``bury_belief_worlds=False``, and the belief draw is never called."""
    def never(*a, **k):
        raise AssertionError("the belief bury draw ran with the flag off")
    monkeypatch.setattr(bwv, "belief_bury_worlds", never)
    tape = []
    for index in ROOTS:
        for k in (32, 64):
            bot = served_bury(bury_wide_value=True, bury_wide_k=k, bury_belief_worlds=False,
                              belief=False, bury_budget=None)
            chosen, record = decide(bot, index)
            assert record.pop("model_ids") == bot.model_ids("bury")
            assert tuple(record) == RECORD_KEYS + (bwv.RECORD_KEY,)
            wv = {key: v for key, v in record[bwv.RECORD_KEY].items() if key != "seconds"}
            tape.append([index, k, chosen, without_timing({**record, bwv.RECORD_KEY: wv})])
    digest = hashlib.sha256(json.dumps(tape, sort_keys=True).encode()).hexdigest()
    assert digest == SWAPS1_TAPE_SHA256


@pytest.mark.parametrize("index", ROOTS[:4])
def test_off_with_a_belief_package_bound_is_the_plain_chooser(index, monkeypatch):
    """A bot that has the play's belief proposal (production) but not this flag
    buries exactly as before: same choice, record and play-sampler state."""
    monkeypatch.setattr(bwv, "belief_bury_worlds",
                        lambda *a, **k: pytest.fail("belief bury draw ran with the flag off"))
    plain = served_bury(bury_wide_value=True, bury_wide_k=64)
    off = served_bury(bury_wide_value=True, bury_wide_k=64, bury_belief_worlds=False)
    a, ra = decide(plain, index)
    b, rb = decide(off, index)
    assert a == b and untimed(ra) == untimed(rb)
    assert not set(BELIEF_FIELDS) & set(rb)
    assert plain.sampler.rng.getstate() == off.sampler.rng.getstate()


# ------------------------------------------------------------ (b) on

def twin_reference(bot, index):
    """The DEV packet's construction, by hand: the proposal on the twin, each
    world the banker's own hand plus the three drawn hands, sorted."""
    rnd = bury_state(index)
    seat = rnd.banker
    incumbent = list(super(bury_policy.CWVBuryMixin, bot).decide_bury(copy.deepcopy(rnd), seat))
    twin = copy.deepcopy(rnd)
    twin.bury(seat, incumbent)
    prop = bn.BeliefProposal(bot.belief_model, twin, seat, (), seed=bwv.belief_seed(bot),
                             batch=BURY.model_worlds, forbidden=draw_constraints(twin, seat))
    out = []
    for _ in range(BURY.model_worlds):
        hands, buried = prop(twin, seat, None)
        assert Counter(buried) == Counter(incumbent)
        out.append(tuple(tuple(sorted(rnd.hands[s] if s == seat else hands[s]))
                         for s in range(4)))
    return rnd, incumbent, out


@pytest.mark.parametrize("index", ROOTS[:6])
def test_on_the_worlds_are_the_belief_proposal_on_the_twin(index, monkeypatch):
    monkeypatch.setattr(bwv, "_worlds",
                        lambda *a, **k: pytest.fail("the helper's sampler ran with the flag on"))
    seen = spy_worlds(monkeypatch)
    bot = bbw()
    before = bot.sampler.rng.getstate()
    chosen, record = decide(bot, index)
    assert record.pop("model_ids") == bot.model_ids("bury")
    assert record["schema"] == "cwv-bury-policy-v1"
    assert (record["bury_belief_worlds"], record["bury_belief_fallbacks"],
            record["bury_belief_error"]) == (True, 0, None)
    assert record["bury_belief_ms"] >= 0
    assert tuple(record) == RECORD_KEYS + (bwv.RECORD_KEY,) + BELIEF_FIELDS
    assert record["world_counts"]["model_attempts"] == BURY.model_worlds
    assert bot.sampler.rng.getstate() == before
    rnd, incumbent, reference = twin_reference(bot, index)
    assert seen == [reference]
    for world in reference:
        assert Counter(c for hand in world for c in hand) == Counter(rnd.deck)
        assert list(world[rnd.banker]) == sorted(rnd.hands[rnd.banker])
        for s in range(4):
            assert len(world[s]) == len(rnd.hands[s])
        if rnd.declaration is not None:
            holder = rnd.declaration["seat"]
            assert not Counter(rnd.declaration["cards"]) - Counter(world[holder])


def test_on_the_draw_is_seeded_by_the_bot_seed_and_deterministic():
    _, rnd_a = decide(bbw(seed=3), 64)
    _, rnd_b = decide(bbw(seed=3), 64)
    assert rnd_a["model_means"] == rnd_b["model_means"]
    assert bwv.belief_seed(bbw(seed=3)) == bwv.belief_seed(bbw(seed=3))
    assert bwv.belief_seed(bbw(seed=3)) != bwv.belief_seed(bbw(seed=4))


def test_on_the_belief_worlds_change_the_scores():
    _, off = decide(served_bury(bury_wide_value=True, bury_wide_k=64), 62)
    _, on = decide(bbw(), 62)
    assert off["candidates"] == on["candidates"]
    assert off["model_means"] != on["model_means"]


# ------------------------------------------------------------ (c) the fallback

def _boom(*a, **k):
    raise RuntimeError("injected")


@pytest.mark.parametrize("break_it, error", [
    ("model", "BeliefNumpyError"),
    ("proposal", "RuntimeError"),
    ("kitty", "BuryPolicyError"),
])
@pytest.mark.parametrize("index", ROOTS[:3])
def test_a_failed_draw_falls_back_to_the_flag_off_worlds_and_is_counted(index, break_it, error,
                                                                       monkeypatch):
    off_chosen, off_record = decide(served_bury(bury_wide_value=True, bury_wide_k=64), index)
    if break_it == "proposal":
        monkeypatch.setattr(bn, "BeliefProposal", _boom)
    if break_it == "kitty":
        real = bn.BeliefProposal

        class MovedKitty(real):
            def __call__(self, rnd, seat, mem):
                hands, buried = super().__call__(rnd, seat, mem)
                return hands, list(buried[1:]) + ["SJ"]
        monkeypatch.setattr(bn, "BeliefProposal", MovedKitty)
    bot = bbw(model=None) if break_it == "model" else bbw()
    before = bot.sampler.rng.getstate()
    chosen, record = decide(bot, index)
    assert record.pop("model_ids") == bot.model_ids("bury")
    assert record["schema"] == "cwv-bury-policy-v1"
    assert (record["bury_belief_fallbacks"], record["bury_belief_error"]) == (1, error)
    assert chosen == off_chosen
    assert record["model_means"] == off_record["model_means"]
    assert record["world_counts"] == off_record["world_counts"]
    assert bot.sampler.rng.getstate() == before


def test_a_budget_expiry_inside_the_draw_is_the_heuristic_fallback(jumping_clock, monkeypatch):
    real = bn.BeliefProposal

    class Expiring(real):
        def __init__(self, *a, **k):
            jumping_clock["expired"] = True
            super().__init__(*a, **k)
    monkeypatch.setattr(bn, "BeliefProposal", Expiring)
    monkeypatch.setattr(bwv, "_worlds", lambda *a, **k: pytest.fail("fell back to the sampler"))
    bot = bbw(bury_budget=2.0)
    before = bot.sampler.rng.getstate()
    rnd = bury_state(61)
    incumbent = list(super(bury_policy.CWVBuryMixin, bot).decide_bury(copy.deepcopy(rnd),
                                                                      rnd.banker))
    chosen = bot.decide_bury(copy.deepcopy(rnd), rnd.banker)
    record = bot.last_bury_record
    assert record["schema"] == "cwv-bury-fallback-v1" and record["reason"] == "budget"
    assert chosen == incumbent and "bury_belief_fallbacks" not in record
    assert bot.sampler.rng.getstate() == before


# ------------------------------------------------------------ (d) names, env, refusals

def belief_env(env):
    return {**env, "SHENGJI_PV_WORLD_HISTORY_LEGAL": "1", "SHENGJI_PV_WORLD_HISTORY_DRAW": "1",
            "SHENGJI_PV_BELIEF_WORLDS": "1", "SHENGJI_PV_BELIEF_CKPT": "/dev/null",
            "SHENGJI_PV_BELIEF_SHA256": "b" * 64}


@pytest.fixture
def belief_package(production_package, monkeypatch):
    monkeypatch.setattr(pv, "file_sha256", lambda path: "b" * 64)


def test_the_token_follows_bwv_and_bkc_and_the_identity_carries_the_source(belief_package):
    plain, = names(belief_env({**fly_env(), **WIDE}))
    on, = names(belief_env({**fly_env(), **WIDE, FLAG: "1"}))
    play = plain[:plain.index("-bury-")]
    assert on.startswith(play + "-bury-hybrid-bwv-bbw-") and on != plain
    assert len(on) == len(play) + len("-bury-hybrid-bwv-bbw-") + 12
    assert names(belief_env({**fly_env(), **WIDE, FLAG: "0"})) == [plain]
    both, = names(belief_env({**fly_env(), **WIDE, FLAG: "1",
                              "SHENGJI_PV_BURY_KITTY_CHARGE": "1"}))
    assert "-bury-hybrid-bwv-bkc-bbw-" in both
    swaps2, = names(belief_env({**fly_env(), **WIDE, "SHENGJI_PV_BURY_WIDE_SWAPS": "2", FLAG: "1"}))
    assert "-bury-hybrid-bwv2-bbw-" in swaps2
    (name, factory), = pv.pv_registry_entries(
        **pv.pv_env_recipe(belief_env({**fly_env(), **WIDE, FLAG: "1"}))).items()
    assert name == on
    assert bwv.TOKEN_BELIEF_WORLDS == "bbw"
    assert bwv.BELIEF_WORLDS_SOURCE == "belief-proposal-trick1-twin-v1"


def test_the_factory_binds_the_flag_and_the_identity_carries_the_source(belief_package,
                                                                        monkeypatch):
    (_, factory), = pv.pv_registry_entries(
        **pv.pv_env_recipe(belief_env({**fly_env(), **WIDE, FLAG: "1"}))).items()
    seen = {}

    def capture(*a, **kw):
        seen.update(kw)
        return bbw()
    monkeypatch.setattr(pv, "make_pv_search_bot", capture)
    monkeypatch.setattr(pv, "_require_pv_search", lambda bot, name: bot)
    bot = factory(seed=0)
    assert seen["bury_belief_worlds"] is True
    assert bot.bury_recipe_identity["wide_value"]["belief_worlds"] == {
        "source": bwv.BELIEF_WORLDS_SOURCE, "proposal": bn.PROPOSAL}
    (_, plain), = pv.pv_registry_entries(
        **pv.pv_env_recipe(belief_env({**fly_env(), **WIDE}))).items()
    seen.clear()
    assert "belief_worlds" not in plain(seed=0).bury_recipe_identity["wide_value"]
    assert seen["bury_belief_worlds"] is False


def test_env_parses_the_flag_and_refuses_bad_values():
    recipe = pv.pv_env_recipe({**PRODUCTION_ENV, **WIDE, FLAG: "1"})
    assert recipe["bury_belief_worlds"] is True
    for bad in ("2", "true", " 1"):
        with pytest.raises(pv.PVSearchPolicyError, match="must be 0 or 1"):
            pv.pv_env_recipe({**PRODUCTION_ENV, **WIDE, FLAG: bad})
    with pytest.raises(pv.PVSearchPolicyError, match="needs bury_wide_value and belief_worlds"):
        pv.pv_env_recipe({**PRODUCTION_ENV, FLAG: "1"})


def test_the_registry_refuses_without_the_belief_proposal_and_with_choosers_it_misses(
        production_package, belief_package):
    with pytest.raises(pv.PVSearchPolicyError, match="needs bury_wide_value and belief_worlds"):
        names({**fly_env(), **WIDE, FLAG: "1"})
    with pytest.raises(pv.PVSearchPolicyError, match="exclusive"):
        names(belief_env({**fly_env(), **WIDE, FLAG: "1", "SHENGJI_PV_BURY_TWO_STAGE": "1"}))


def test_the_constructor_refusals():
    with pytest.raises(pv.PVSearchPolicyError, match="must be a bool"):
        served_bury(bury_wide_value=True, bury_belief_worlds=1)
    with pytest.raises(pv.PVSearchPolicyError, match="needs bury_wide_value"):
        served_bury(bury_belief_worlds=True)
    with pytest.raises(pv.PVSearchPolicyError, match="needs bury_wide_value and belief_worlds"):
        served_bury(bury_wide_value=True, bury_belief_worlds=True, belief=False)
    from shengji.train import bury_two_stage as bts
    with pytest.raises(pv.PVSearchPolicyError, match="exclusive"):
        served_bury(bury_wide_value=True, bury_belief_worlds=True,
                    bury_two_stage=bts.TwoStageConfig())
    with pytest.raises(pv.PVSearchPolicyError, match="exclusive"):
        served_bury(bury_wide_value=True, bury_belief_worlds=True, value_declare=True,
                    value_declare_served_bury=True)
    with pytest.raises(pv.PVSearchPolicyError, match="needs bury_wide_value"):
        pv.pv_registry_entries("/dev/null", sha256="f" * 64, bury_arm="hybrid",
                               bury_belief_worlds=True)
    assert vars(bbw())["bury_belief_worlds"] is True


# ------------------------------------------------------------ (e) the served recipe

def test_the_served_recipe_with_the_flag_buries_on_belief_worlds(
        pinned_production_package, pinned_release48_belief_package, monkeypatch):
    """Release 49's fly.toml plus the flag on the hash-pinned packages, built as
    the server builds it: the name is release 49's with ``-bbw`` in the bury
    segment, and a bury completes on belief worlds with no fallback.  Flag
    ``0`` builds release 49 itself."""
    env = release49_fly_env()
    name0, _ = served_bot(pinned_production_package, pinned_release48_belief_package,
                          monkeypatch, env={**env, FLAG: "0"})
    assert name0 == RELEASE49
    local = local_env(pinned_production_package, pinned_release48_belief_package, env)
    (on_name, _), = pv.pv_registry_entries(**pv.pv_env_recipe({**local, FLAG: "1"})).items()
    head, tail = RELEASE49.split("-bury-hybrid-bwv-")
    assert on_name.startswith(head + "-bury-hybrid-bwv-bbw-") and on_name != RELEASE49
    name, bot = served_bot(pinned_production_package, pinned_release48_belief_package,
                           monkeypatch, env={**env, FLAG: "1", "SHENGJI_BOT": on_name + "-sc8"})
    assert name == bot.policy_name == on_name + "-sc8"
    assert bot.bury_belief_worlds is True and bot.belief_model is not None
    bot.bury_serving_budget_seconds = 120.0        # a cold or slow runner never expires it
    chosen, record = decide(bot, 63)
    assert record["schema"] == "cwv-bury-policy-v1"
    assert (record["bury_belief_fallbacks"], record["bury_belief_error"]) == (0, None)
    assert record["world_counts"]["model_attempts"] == bot.bury_config.model_worlds
    assert len(chosen) == 8


# ------------------------------------------------------------ (f) the room log

@pytest.mark.parametrize("mode", ["off", "clean", "fallback"])
def test_the_room_log_carries_the_fallback_count_only_for_a_bbw_bury(tmp_path, mode):
    """Through the server's own snapshot, commit and timing log: a ``bbw`` bury
    that fell back (no package bound) logs ``bury_belief_fallbacks`` 1; any
    other bury logs exactly the fields it logged before."""
    async def scenario():
        rnd = bury_state(65)
        game = Game(random.Random(7))
        game.round = rnd
        player = (bbw(model=None) if mode == "fallback" else bbw() if mode == "clean" else
                  served_bury(bury_wide_value=True, bury_wide_k=64))
        room = server.Room(code="BBWTEST", game=game, bot=player,
                           seats=[server.Seat(str(i), is_bot=True) for i in range(4)],
                           log_dir=tmp_path)
        room.ids = [dict(enumerate(hand)) for hand in rnd.hands]
        room._kitty_given = True
        events = []
        room.log_event = lambda kind, **fields: events.append({"kind": kind, **fields})
        prepared = await server._paced_bot_step(room, rnd.banker, minimum_turn_seconds=0)
        acted = server._commit_bot_turn(room, prepared)
        server._log_bot_timing(room, prepared, acted=acted)
        assert acted and rnd.phase == "play"
        from scripts.cwv_serving_smoke import budget_turn
        snapshot_bot = prepared.decision.snapshot.bot_copy
        measured = budget_turn("bury", snapshot_bot, 0.1,
                               {"SHENGJI_PV_BURY_SERVING_BUDGET_SECONDS": "60"})
        return [e for e in events if e["kind"] == "bot_timing"][-1], measured

    timing, measured = asyncio.run(scenario())
    assert timing["bury_search_status"] == "complete"
    if mode != "off":
        assert timing["bury_belief_fallbacks"] == int(mode == "fallback")
    else:
        assert "bury_belief_fallbacks" not in timing
    assert measured["failures"] == (["bury_belief_fallback_or_missing"]
                                    if mode == "fallback" else [])
