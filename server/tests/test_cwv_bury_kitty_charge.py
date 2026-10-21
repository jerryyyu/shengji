"""The OPTIONAL kitty charge of the wide value-only bury (``bury_kitty_charge``,
``SHENGJI_PV_BURY_KITTY_CHARGE``, bury token ``bkc``; `train.bury_kitty_charge`):
the chooser's argmax over the value means less each candidate kitty's expected
bonus, ``total_points(kitty) x P_ATTACKERS_LAST x MULTIPLIER x LEVELS_PER_POINT``.

Torch-free and package-free (the wide chooser's stub predictor and evaluators on
the real engine, ballot, sampler and leaf), except the registry names on the
production-package id stub.  Witnesses: (a) off: the names, the recipe, the
bot's state, and the wide chooser's frozen decision/record tape are unchanged
and the charge is never computed; (b) on: a constructed point-bury preference
smaller than the charge moves the bury to a zero-point kitty, a larger one keeps
it, and the record carries the charge; (c) the arithmetic; (d) the token,
identity, env parsing and refusals.
"""
import hashlib
import json

import numpy as np
import pytest

from shengji.engine.cards import total_points
from shengji.train import bury_kitty_charge as bkc
from shengji.train import bury_wide_value as bwv
from shengji.train import pv_search_policy as pv
from test_cwv_bury_wide_value import (BURY, RECORD_KEYS, RELEASE44_BWV64, SWAPS1_TAPE_SHA256,
                                      CountingPredict, TrickEvaluator, SMALL, bury_state,
                                      decide, fly_env, without_timing)  # noqa: F401
from test_pv_admission_rules import PRODUCTION_ENV, names, production_package  # noqa: F401

FLAG = "SHENGJI_PV_BURY_KITTY_CHARGE"
WIDE = {"SHENGJI_PV_BURY_WIDE_VALUE": "1", "SHENGJI_PV_BURY_WIDE_K": "64"}
ROOTS = tuple(range(60, 72))


def served_bury(evaluator=None, bury_budget=60.0, seed=17, **rules):
    wide = {k: rules.pop(k) for k in ("bury_wide_value", "bury_wide_k", "bury_wide_swaps",
                                      "bury_two_stage", "bury_kitty_charge") if k in rules}
    config = pv.PVSearchConfig(checkpoint_sha256="f" * 64, **SMALL, **rules)
    return pv.PVSearchBuryBot(CountingPredict(), evaluator=evaluator or TrickEvaluator(),
                              version=2, config=config, checkpoint="/dev/null", seed=seed,
                              bury_arm="hybrid", bury_config=BURY,
                              bury_serving_budget_seconds=bury_budget, **wide)


def charged(k=64, **kw):
    return served_bury(bury_wide_value=True, bury_wide_k=k, bury_kitty_charge=True, **kw)


class PointLover(TrickEvaluator):
    """``slope`` signed levels per kitty point, plus a small distinct value
    from the kitty (below a 5-point step at the slopes used here)."""

    def __init__(self, slope):
        super().__init__()
        self.slope = slope

    def score(self, positions, seat):
        self.calls += 1
        return np.array([self.slope * total_points(p.buried)
                         + (hash(tuple(sorted(p.buried))) % 97) / 1e5 for p in positions])


# ------------------------------------------------------------ (a) off

def test_off_names_recipe_and_state_are_unchanged(production_package):
    assert names({**fly_env(), **WIDE}) == [RELEASE44_BWV64]
    for raw in ("0", ""):
        assert names({**fly_env(), **WIDE, FLAG: raw}) == [RELEASE44_BWV64]
        assert "bury_kitty_charge" not in pv.pv_env_recipe({**PRODUCTION_ENV, **WIDE, FLAG: raw})
    assert pv.PVSearchBuryBot.bury_kitty_charge is False
    base = served_bury(bury_wide_value=True, bury_wide_k=64)
    for kw in ({}, {"bury_kitty_charge": False}):
        bot = served_bury(bury_wide_value=True, bury_wide_k=64, **kw)
        assert "bury_kitty_charge" not in vars(bot)
        assert vars(bot).keys() == vars(base).keys()


def test_off_decisions_and_records_reproduce_the_frozen_tape(monkeypatch):
    """The wide chooser's frozen tape (K=32 and K=64 on the DEV roots 60-71)
    with ``bury_kitty_charge=False``, and the charge is never computed."""
    def never(*a, **k):
        raise AssertionError("the kitty charge ran with the flag off")
    monkeypatch.setattr(bwv, "charged_choice", never)
    tape = []
    for index in ROOTS:
        for k in (32, 64):
            bot = served_bury(bury_wide_value=True, bury_wide_k=k, bury_kitty_charge=False)
            chosen, record = decide(bot, index)
            assert tuple(record) == RECORD_KEYS + (bwv.RECORD_KEY,)
            wv = {key: v for key, v in record[bwv.RECORD_KEY].items() if key != "seconds"}
            tape.append([index, k, chosen, without_timing({**record, bwv.RECORD_KEY: wv})])
    digest = hashlib.sha256(json.dumps(tape, sort_keys=True).encode()).hexdigest()
    assert digest == SWAPS1_TAPE_SHA256


# ------------------------------------------------------------ (b) on

@pytest.mark.parametrize("index", ROOTS)
def test_a_point_preference_below_the_charge_moves_the_bury_to_zero_points(index):
    """The value head prefers points in the kitty by 0.01 levels a point, less
    than the 0.0285 charge: off buries the most points, on buries none."""
    off = served_bury(bury_wide_value=True, bury_wide_k=64, evaluator=PointLover(0.01))
    off_chosen, off_record = decide(off, index)
    points = [total_points(c) for c in off_record["candidates"]]
    assert max(points) > 0 and min(points) == 0              # both kinds are on the ballot
    assert total_points(off_chosen) == max(points)
    bot = charged(evaluator=PointLover(0.01))
    chosen, record = decide(bot, index)
    assert record["candidates"] == off_record["candidates"]
    assert record["model_means"] == off_record["model_means"]   # the means stay uncharged
    assert total_points(chosen) == 0
    kc = record[bkc.RECORD_KEY]
    assert kc["per_point"] == pytest.approx(0.0285)
    assert kc["charges"] == pytest.approx([p * bkc.PER_POINT for p in points])
    assert kc["charged_means"] == pytest.approx(
        [m - c for m, c in zip(record["model_means"], kc["charges"])])
    assert kc["uncharged_index"] == off_record["picked_index"]
    assert kc["changed"] is True
    assert record["picked_index"] == record[bwv.RECORD_KEY]["chosen_index"]
    assert chosen == record["candidates"][record["picked_index"]]
    assert record["picked_index"] == int(np.argmax(kc["charged_means"]))
    assert tuple(record) == RECORD_KEYS + (bwv.RECORD_KEY, bkc.RECORD_KEY)
    assert json.dumps(record)


@pytest.mark.parametrize("index", ROOTS[:4])
def test_a_point_preference_above_the_charge_keeps_the_point_bury(index):
    off_chosen, off_record = decide(
        served_bury(bury_wide_value=True, bury_wide_k=64, evaluator=PointLover(0.05)), index)
    chosen, record = decide(charged(evaluator=PointLover(0.05)), index)
    assert total_points(off_chosen) > 0
    assert chosen == off_chosen and record[bkc.RECORD_KEY]["changed"] is False


def test_the_charge_does_not_consume_the_play_sampler():
    bot = charged()
    before = bot.sampler.rng.getstate()
    decide(bot, 66)
    assert bot.sampler.rng.getstate() == before


# ------------------------------------------------------------ (c) arithmetic

def test_the_charge_is_points_times_the_three_factors():
    assert bkc.PER_POINT == pytest.approx(0.38 * 3.0 / 40)
    kitties = [["S3", "S4", "S6", "S7", "S8", "S9", "D3", "D4"],      # 0 points
               ["S5", "S4", "S6", "S7", "S8", "S9", "D3", "D4"],      # 5
               ["S5", "S10", "SK", "S7", "S8", "S9", "D3", "D4"]]      # 25
    assert bkc.kitty_charges(kitties).tolist() == pytest.approx([0.0, 5 * 0.0285, 25 * 0.0285])
    picked, record = bkc.charged_choice(kitties, [0.0, 0.1, 0.8])
    assert picked == 2 and record["uncharged_index"] == 2 and record["changed"] is False
    picked, record = bkc.charged_choice(kitties, [0.0, 0.1, 0.5])
    assert picked == 0 and record["changed"] is True            # charged: 0, -0.0425, -0.2125
    picked, _ = bkc.charged_choice(kitties, [0.0, 5 * 0.0285, 0.0])
    assert picked == 0                                           # a tie keeps the lower index
    with pytest.raises(ValueError, match="misaligned"):
        bkc.charged_choice(kitties, [0.0, 0.1])


# ------------------------------------------------------------ (d) names, env, refusals

def test_the_token_follows_bwv_and_the_identity_carries_the_factors(production_package):
    on, = names({**fly_env(), **WIDE, FLAG: "1"})
    play = RELEASE44_BWV64[:RELEASE44_BWV64.index("-bury-")]
    assert on.startswith(play + "-bury-hybrid-bwv-bkc-") and on != RELEASE44_BWV64
    assert len(on) == len(play) + len("-bury-hybrid-bwv-bkc-") + 12
    swaps2, = names({**fly_env(), **WIDE, "SHENGJI_PV_BURY_WIDE_SWAPS": "2", FLAG: "1"})
    assert "-bury-hybrid-bwv2-bkc-" in swaps2
    entries = pv.pv_registry_entries(**pv.pv_env_recipe({**fly_env(), **WIDE, FLAG: "1"}))
    assert list(entries) == [on]
    assert bkc.identity() == {"p_attackers_last": 0.38, "multiplier": 3.0,
                              "levels_per_point": 0.025}
    assert bkc.TOKEN == "bkc" and bkc.RECORD_KEY == "kitty_charge"


def test_env_parses_the_flag_and_refuses_bad_values():
    recipe = pv.pv_env_recipe({**PRODUCTION_ENV, **WIDE, FLAG: "1"})
    assert recipe["bury_kitty_charge"] is True
    for bad in ("2", "true", " 1"):
        with pytest.raises(pv.PVSearchPolicyError, match="must be 0 or 1"):
            pv.pv_env_recipe({**PRODUCTION_ENV, **WIDE, FLAG: bad})
    with pytest.raises(pv.PVSearchPolicyError, match="needs bury_wide_value"):
        pv.pv_env_recipe({**PRODUCTION_ENV, FLAG: "1"})
    with pytest.raises(pv.PVSearchPolicyError, match="exclusive"):
        pv.pv_registry_entries(**pv.pv_env_recipe(
            {**PRODUCTION_ENV, **WIDE, FLAG: "1", "SHENGJI_PV_BURY_TWO_STAGE": "1"}))


def test_the_constructor_refusals():
    with pytest.raises(pv.PVSearchPolicyError, match="must be a bool"):
        served_bury(bury_wide_value=True, bury_kitty_charge=1)
    with pytest.raises(pv.PVSearchPolicyError, match="needs bury_wide_value"):
        served_bury(bury_kitty_charge=True)
    from shengji.train import bury_two_stage as bts
    with pytest.raises(pv.PVSearchPolicyError, match="exclusive"):
        served_bury(bury_wide_value=True, bury_kitty_charge=True,
                    bury_two_stage=bts.TwoStageConfig())
    with pytest.raises(pv.PVSearchPolicyError, match="exclusive"):
        served_bury(bury_wide_value=True, bury_kitty_charge=True, value_declare=True,
                    value_declare_served_bury=True)
    with pytest.raises(pv.PVSearchPolicyError, match="needs bury_wide_value"):
        pv.pv_registry_entries("/dev/null", sha256="f" * 64, bury_arm="hybrid",
                               bury_kitty_charge=True)
    bot = charged()
    assert vars(bot)["bury_kitty_charge"] is True
