"""The exact stages' world subset (``SHENGJI_PV_EXACT_WORLD_SUBSET``, token
``exs<n>``): with more than ``n`` worlds drawn, the exact lead and exact follow
stages solve the first ``n`` in draw order, equally weighted; the value pass,
the selection rules and the doomed-throw test still read every world.  With
``n`` at least the drawn worlds it is the same search: no name, payload or
decision change.  Its strength is a separate question; nothing here claims it.

Torch-free and package-free except the registry-name test.  Witnesses: (a) the
no-op at W64 (and at any ``n >= W``): payload, digest, name, bot attributes and
seeded endgame decisions are the flag-off ones; (b) narrower than W: the exact
stages receive exactly the first ``n`` drawn worlds, the value pass all W, the
records name the subset; (c) refusals, env and name tokens.
"""
import copy

import pytest

from shengji.ai.heuristic import HeuristicBot

from shengji.train import pv_exact_deep, pv_exact_follow
from shengji.train import pv_search_policy as pv
from test_pv_admission_rules import names, production_package  # noqa: F401
from test_pv_doomed_throw_reselect import HashNoiseEvaluator
from test_pv_doomed_throw_reselect_exact_guard import R46_ENV, R46_NAME
from test_pv_leaf_greedy_finish import R46_RULES
from test_pv_single_candidate_fast import bot as _bot, comparable
from test_pv_small_joker_lead import _fresh_round

ENV = "SHENGJI_PV_EXACT_WORLD_SUBSET"
EXACT_RULES = dict(R46_RULES, exact_deep_cards=5, exact_follow=True)


def config(**kw):
    return pv.PVSearchConfig(checkpoint_sha256="f" * 64, **{**EXACT_RULES, **kw})


def bot(worlds, subset=0, seed=17):
    return _bot(False, dict(EXACT_RULES, exact_world_subset=subset), HashNoiseEvaluator(),
                worlds=worlds, seed=seed)


# ------------------------------------------------- (a) the no-op

@pytest.mark.parametrize("worlds,subset", [(64, 64), (64, 128), (8, 8), (8, 0)])
def test_a_subset_at_least_the_worlds_is_the_same_recipe(worlds, subset):
    base, flagged = config(worlds=worlds), config(worlds=worlds, exact_world_subset=subset)
    assert pv.recipe_payload(flagged) == pv.recipe_payload(base)
    assert "exact_world_subset" not in pv.recipe_payload(flagged)
    assert pv.recipe_digest(flagged) == pv.recipe_digest(base)
    assert pv.pv_policy_name("491ee4bf", flagged) == pv.pv_policy_name("491ee4bf", base)
    assert "exact_world_subset" not in vars(bot(worlds, subset))
    assert bot(worlds, subset)._exact_worlds(list(range(worlds))) == list(range(worlds))


@pytest.mark.parametrize("seed", [17, 23])
def test_at_w64_the_flag_decides_exactly_as_off_on_seeded_endgames(seed):
    """The heuristic walks the round into the exact stages' range; both bots
    then play every remaining decision."""
    off, on = bot(64, seed=seed), bot(64, 64, seed=seed)
    h = HeuristicBot()
    rnd = _fresh_round(seed)
    while max(map(len, rnd.hands)) > 5:
        rnd.play(rnd.turn, h.decide_play(rnd, rnd.turn))
    decisions = exact = 0
    while rnd.phase == "play":
        seat = rnd.turn
        a = off.decide_play(copy.deepcopy(rnd), seat)
        b = on.decide_play(copy.deepcopy(rnd), seat)
        assert a == b
        assert comparable(off.last_decision_record) == comparable(on.last_decision_record)
        assert off.sampler.rng.getstate() == on.sampler.rng.getstate()
        record = on.last_decision_record
        exact += bool(record.get("exact_follow_attempted")
                      or record.get("exact_lead_status") == "complete")
        assert "exact_lead_subset_worlds" not in record
        assert "exact_follow_subset_worlds" not in record
        decisions += 1
        rnd.play(seat, a)
    assert decisions >= 8 and exact >= 3


# ------------------------------------------------- (b) narrower than the worlds

def test_the_exact_stages_solve_the_first_n_worlds_and_the_value_pass_all(monkeypatch):
    seen = {"lead": [], "follow": []}
    real_lead, real_follow = pv_exact_deep.exact_root_means, pv_exact_follow.rerank_follow

    def lead(rnd, seat, actions, worlds, *args, **kw):
        seen["lead"].append(list(worlds))
        return real_lead(rnd, seat, actions, worlds, *args, **kw)

    def follow(rnd, seat, admitted, worlds, **kw):
        seen["follow"].append(list(worlds))
        return real_follow(rnd, seat, admitted, worlds, **kw)

    monkeypatch.setattr(pv_exact_deep, "exact_root_means", lead)
    monkeypatch.setattr(pv_exact_follow, "rerank_follow", follow)
    b = bot(12, 4)
    assert b.exact_world_subset == 4
    drawn = []
    real_worlds = b._worlds

    def worlds(rnd, seat, check_budget=None):
        out = real_worlds(rnd, seat, check_budget)
        drawn.append(out[0])
        return out

    b._worlds = worlds
    rnd = _fresh_round(23)
    lead_records = follow_records = 0
    while rnd.phase == "play":
        seat = rnd.turn
        played = b.decide_play(copy.deepcopy(rnd), seat)
        record = b.last_decision_record
        assert record["worlds"] == 12
        if record.get("exact_lead_status") == "complete":
            assert record["exact_lead_subset_worlds"] == 4
            assert record["exact_lead_worlds_completed"] == 4
            lead_records += 1
        if record.get("exact_follow_attempted") and record.get("exact_follow_abandoned") is None:
            assert record["exact_follow_subset_worlds"] == 4 and record["exact_follow_worlds"] == 4
            follow_records += 1
        if len(record.get("admitted") or []) > 1 and "value_evaluations" in record:
            assert record["value_evaluations"] == 12 * len(record["admitted"])
        rnd.play(seat, played)
    assert lead_records >= 1 and follow_records >= 1
    for solved in seen["lead"] + seen["follow"]:
        assert len(solved) == 4
        assert any(all(s is w for s, w in zip(solved, full[:4])) for full in drawn)


# ------------------------------------------------- (c) refusals, env and names

def test_an_active_subset_enters_the_payload_and_the_name():
    active = config(worlds=128, exact_world_subset=64)
    payload = pv.recipe_payload(active)
    assert payload["exact_world_subset"] == {"worlds": 64, **pv.EXACT_WORLD_SUBSET_RULE}
    assert pv.EXACT_WORLD_SUBSET_RULE == {"selection": "first-n-in-draw-order",
                                          "weights": "uniform", "other_rules": "every-world"}
    name = pv.pv_policy_name("491ee4bf", active)
    assert "-xf4-exs64-r" in name
    assert name != pv.pv_policy_name("491ee4bf", config(worlds=128))


@pytest.mark.parametrize("bad", [True, -1, 513, 1.5, "64"])
def test_a_malformed_subset_refuses(bad):
    with pytest.raises(pv.PVSearchPolicyError, match="exact_world_subset"):
        pv.recipe_payload(config(worlds=128, exact_world_subset=bad))


def test_an_active_subset_without_an_exact_stage_refuses():
    plain = pv.PVSearchConfig(checkpoint_sha256="f" * 64, worlds=128, exact_world_subset=64)
    with pytest.raises(pv.PVSearchPolicyError, match="needs an exact stage"):
        pv.recipe_payload(plain)
    same = pv.PVSearchConfig(checkpoint_sha256="f" * 64, worlds=64, exact_world_subset=64)
    assert pv.recipe_payload(same) == pv.recipe_payload(
        pv.PVSearchConfig(checkpoint_sha256="f" * 64, worlds=64))


def test_env_parsing():
    env = {**R46_ENV, "SHENGJI_PV_CKPT": "/x.npz", "SHENGJI_PV_SHA256": "f" * 64}
    assert "exact_world_subset" not in pv.pv_env_recipe(env)
    for off in ("", "0"):
        assert pv.pv_env_recipe({**env, ENV: off}) == pv.pv_env_recipe(env)
    assert pv.pv_env_recipe({**env, ENV: "64"})["exact_world_subset"] == 64
    with pytest.raises(pv.PVSearchPolicyError, match=ENV):
        pv.pv_env_recipe({**env, ENV: "sixty-four"})


def test_registry_names(production_package):  # noqa: F811
    assert names({**R46_ENV, ENV: "64"}) == [R46_NAME]
    wide, = names({**R46_ENV, ENV: "64", "SHENGJI_PV_WORLDS": "128"})
    plain, = names({**R46_ENV, "SHENGJI_PV_WORLDS": "128"})
    assert wide != plain and "-xfcompactlevel-exs64-r" in wide
    assert wide.startswith("pv-search-491ee4bf-w128-k8-")
