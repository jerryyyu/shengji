"""Release 50 as served is unchanged by the rules-profile switch: production's
env names no profile, the profile is outside the recipe and the name, an
explicitly empty profile decides as main, and a profile installed then removed
leaves no trace in the next decision.  On the hash-pinned release-50 packages,
pure and compiled.  An identity witness only; no strength claim."""
from collections import Counter

import pytest

import r50_flag_positions as P
from shengji.engine import rules_profile as rp
from test_r50_flag_off_parity import PINS, assert_decision
from test_release50_fly_config import fly_env
from test_release50_fly_config import (BELIEF_SHA, BELIEF_VOLUME_PATH, PRIOR_SHA,  # noqa: F401
                                       PRIOR_VOLUME_PATH, RELEASE50, VALUE_SHA, VALUE_VOLUME_PATH,
                                       release50_packages, served_bot)

#: the late WJLB position: the exact stages run, over a kitty holding points
POSITION = ("WJLB2", 18, 1)


@pytest.fixture(autouse=True)
def lift_belief_preparation_clock(monkeypatch):
    """Identity checks compare complete model draws regardless of host load."""
    from shengji.ai import belief_numpy

    monkeypatch.setattr(belief_numpy, "PREP_SECONDS", 600.0)


def test_production_env_names_no_rules_profile():
    assert rp.ENV not in fly_env()
    assert rp.active() == rp.DEFAULT


def test_the_profile_is_outside_the_recipe_and_the_name(monkeypatch):
    from shengji.ai import cwv_policy
    from shengji.train import pv_search_policy as pv

    env = fly_env()
    by_path = {VALUE_VOLUME_PATH: VALUE_SHA, PRIOR_VOLUME_PATH: PRIOR_SHA,
               BELIEF_VOLUME_PATH: BELIEF_SHA}
    monkeypatch.setattr(cwv_policy, "checkpoint_id", lambda path: by_path[str(path)][:8])
    monkeypatch.setattr(pv, "file_sha256", lambda path: by_path[str(path)])
    recipe = pv.pv_env_recipe(env)
    for value in (rp.DEFAULT, rp.SHENGJIORG):
        assert pv.pv_env_recipe({**env, rp.ENV: value}) == recipe
    assert list(pv.singleton_registry_entries(**recipe)) == [RELEASE50]


def test_the_position_buries_points():
    from shengji.engine.cards import total_points

    assert total_points(P.replay(*POSITION).buried) > 0


def test_an_empty_profile_decides_as_main(release50_packages, monkeypatch):
    name, bot = served_bot(release50_packages, monkeypatch, env={**fly_env(), rp.ENV: ""},
                           seed=P.SEED)
    assert name == bot.policy_name == RELEASE50
    rp.install_from_env()
    assert rp.active() == rp.DEFAULT
    assert_decision(P.decision(P.lift(bot), P.replay(*POSITION)), PINS["decisions"][P.label(*POSITION)])


def test_a_removed_profile_leaves_the_served_decision(release50_packages, monkeypatch):
    rp.install(rp.SHENGJIORG)
    try:
        name, bot = served_bot(release50_packages, monkeypatch, seed=P.SEED)
        assert name == bot.policy_name == RELEASE50
        rnd = P.replay(*POSITION)
        hand = Counter(rnd.hands[rnd.turn])
        profiled = P.decision(P.lift(bot), rnd)
        assert profiled["cards"] and not Counter(profiled["cards"]) - hand
    finally:
        rp.uninstall()
    _, bot = served_bot(release50_packages, monkeypatch, seed=P.SEED)
    assert_decision(P.decision(P.lift(bot), P.replay(*POSITION)), PINS["decisions"][P.label(*POSITION)])
