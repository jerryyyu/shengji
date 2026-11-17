"""The defenders' banker-void world weight (``banker_void_weight_centi``, ``bvw<100 lambda>``),
OFF BY DEFAULT.

With ``SHENGJI_PV_BANKER_VOID_WEIGHT=<lambda>`` a defender's world draw takes two production
draws and keeps one draw's worth, weighted by ``lambda ** (banker's void side suits)``.  Off,
release 52's name and payload are unchanged.  Correctness and identity witnesses only, not a
strength claim.
"""
import random

import pytest

from shengji.engine.cards import Ordering
from shengji.train import pv_search_policy as pv

SHA = "f" * 64


def test_off_leaves_payload_and_name_unchanged():
    off = pv.recipe_payload(pv.PVSearchConfig(checkpoint_sha256=SHA))
    assert "banker_void_weight" not in off and "banker_void_weight_centi" not in off
    assert pv.pv_policy_name("f4f4127e", pv.PVSearchConfig(checkpoint_sha256=SHA)) == \
        pv.pv_policy_name("f4f4127e", pv.PVSearchConfig(checkpoint_sha256=SHA, banker_void_weight_centi=0))


def test_on_enters_payload_and_name():
    config = pv.PVSearchConfig(checkpoint_sha256=SHA, banker_void_weight_centi=250)
    payload = pv.recipe_payload(config)
    assert payload["banker_void_weight"] == {"lambda_centi": 250, "pool_draws": 2,
                                             "rule": pv.BANKER_VOID_WEIGHT_RULE_ID}
    assert "-bvw250" in pv.pv_policy_name("f4f4127e", config)
    assert pv.recipe_payload(config) != pv.recipe_payload(pv.PVSearchConfig(checkpoint_sha256=SHA))


@pytest.mark.parametrize("centi", [100, 401, -1, True, 2.5])
def test_malformed_values_are_refused(centi):
    with pytest.raises(pv.PVSearchPolicyError):
        pv.recipe_payload(pv.PVSearchConfig(checkpoint_sha256=SHA, banker_void_weight_centi=centi))


def test_refused_with_the_oracle():
    with pytest.raises(pv.PVSearchPolicyError):
        pv.recipe_payload(pv.PVSearchConfig(checkpoint_sha256=SHA, banker_void_weight_centi=250,
                                            oracle_worlds=True))


def test_void_suits_ignore_trump_and_level_cards():
    order = Ordering("H", "5")
    hands = [[], ["S3", "H9", "C5", "BJ"], [], []]       # C5 is a level card: trump
    assert pv.banker_void_suits(hands, 1, order, "H") == 2   # void in C and D; H is trump
    assert pv.banker_void_suits(hands, 1, Ordering(None, "5"), None) == 2   # NT: void in C, D


def test_keep_size_order_and_tilt():
    rng = random.Random(3)
    counts = [0] * 64 + [2] * 64
    kept = pv.banker_void_keep(counts, 64, 2.5, rng)
    assert len(kept) == 64 and kept == sorted(kept) and len(set(kept)) == 64
    tilted = [sum(counts[i] for i in pv.banker_void_keep(counts, 64, 2.5, random.Random(s))) / 64
              for s in range(200)]
    flat = [sum(counts[i] for i in pv.banker_void_keep(counts, 64, 1.0, random.Random(s))) / 64
            for s in range(200)]
    assert sum(tilted) / 200 > 1.2 > sum(flat) / 200 > 0.8


def test_keep_refuses_a_short_pool():
    with pytest.raises(pv.PVSearchPolicyError):
        pv.banker_void_keep([0, 1], 3, 2.0, random.Random(0))


class _Round:
    banker = 0
    trump_suit = "S"
    ordering = Ordering("S", "2")

    def is_attacker(self, seat):
        return seat in (1, 3)


def _bot(centi):
    bot = object.__new__(pv.PVSearchBot)
    bot.banker_void_weight_centi = centi
    bot._banker_void = None
    bot.sampler = type("S", (), {"rng": random.Random(9)})()
    draws = []

    def draw(rnd, seat, check_budget=None):
        draws.append(seat)
        k = len(draws)
        # world k: the banker holds only spades (void in H, C, D) on even draws
        hands = [["S4"] if k % 2 == 0 else ["S4", "H4", "C4", "D4"], [], [], []]
        return [(hands, [])] * 4, 1
    bot._worlds_draw = draw
    return bot, draws


def test_defenders_draw_twice_bankers_once():
    bot, draws = _bot(250)
    worlds, attempts = bot._worlds(_Round(), 1)
    assert len(worlds) == 4 and draws == [1, 1] and attempts == 2
    assert bot._banker_void_record()["banker_void_draws"] == 1
    bot, draws = _bot(250)
    worlds, attempts = bot._worlds(_Round(), 2)        # the banker's partner
    assert draws == [2] and attempts == 1 and bot._banker_void is None


def test_off_draws_once_for_defenders():
    bot, draws = _bot(0)
    bot._worlds(_Round(), 1)
    assert draws == [1] and bot._banker_void_record() == {}


def test_env_parse(monkeypatch):
    env = {"SHENGJI_PV_CKPT": "/x.npz", "SHENGJI_PV_SHA256": SHA, "SHENGJI_PV_BANKER_VOID_WEIGHT": "2.5"}
    monkeypatch.setattr(pv, "file_sha256", lambda path: SHA)
    recipe = pv.pv_env_recipe(env)
    assert recipe["banker_void_weight_centi"] == 250
    for bad in ("x", "2.555", "5"):
        with pytest.raises(pv.PVSearchPolicyError):
            pv.pv_env_recipe({**env, "SHENGJI_PV_BANKER_VOID_WEIGHT": bad})
