"""Release 46's served bot with both latency switches on
(``SHENGJI_PV_ENCODE_PREFIX_CACHE=1``, ``SHENGJI_PV_SINGLE_CANDIDATE_FAST=1``)
decides exactly as with them off, on the hash-pinned production and belief
packages.

The bot is built from the repo's ``fly.toml`` as the server builds it
(`test_release46_fly_config.served_entries`).  Over two seeded rounds every
play decision of the switched bot is the plain bot's: the cards played, the
decision record (the skipped pass's own fields aside on a one-candidate
decision), the sampler state after it, and, with the encoding switch alone, the
value evaluator's row and call counters too.  Neither switch, nor an exact
world subset as wide as the drawn worlds, changes the served name.  Package
tests fail, never skip, under ``SHENGJI_REQUIRE_PV_PACKAGE=1``.
"""
import copy

import pytest

from test_encoder_round_compat import pinned_production_package  # noqa: F401
from test_pv_search_serving import _play_state
from test_release46_fly_config import RELEASE46, pinned_belief_package, served_entries  # noqa: F401

PREFIX = "SHENGJI_PV_ENCODE_PREFIX_CACHE"
SINGLE = "SHENGJI_PV_SINGLE_CANDIDATE_FAST"
SKIPPED = ("value_means", "value_batches", "value_evaluations", "single_candidate_fast")


def comparable(record, skipped=False):
    out = {k: v for k, v in record.items() if not k.endswith("seconds") and not k.endswith("_ms")}
    if skipped:
        for key in SKIPPED:
            out.pop(key, None)
    return out


def counters(ev):
    return (ev.calls, ev.positions, ev.model_rows, ev.terminal_rows, ev.forward_calls)


def build(monkeypatch, factory, switches):
    for name in (PREFIX, SINGLE):
        monkeypatch.delenv(name, raising=False)
    for name in switches:
        monkeypatch.setenv(name, "1")
    bot = factory(seed=17)
    for name in (PREFIX, SINGLE):
        monkeypatch.delenv(name, raising=False)
    return bot


@pytest.mark.parametrize("switches", [(PREFIX,), (PREFIX, SINGLE)], ids=["prefix", "prefix+single"])
def test_the_switched_release46_bot_decides_exactly_as_the_plain_one(
        monkeypatch, pinned_production_package, pinned_belief_package, switches):  # noqa: F811
    env, name, factory = served_entries(pinned_production_package, pinned_belief_package)
    assert name == RELEASE46
    plain = build(monkeypatch, factory, ())
    fast = build(monkeypatch, factory, switches)
    assert fast.encode_prefix_cache and fast.single_candidate_fast == (SINGLE in switches)
    assert "encode_prefix_cache" not in vars(plain)
    decisions = skipped_count = rows = 0
    card_counts = set()
    for seed in (17, 23):
        rnd = _play_state(seed)
        while rnd.phase == "play":
            seat = rnd.turn
            card_counts.add(len(rnd.hands[seat]))
            before = counters(plain.evaluator)
            a = plain.decide_play(copy.deepcopy(rnd), seat)
            delta_plain = [x - y for x, y in zip(counters(plain.evaluator), before)]
            before = counters(fast.evaluator)
            b = fast.decide_play(copy.deepcopy(rnd), seat)
            delta_fast = [x - y for x, y in zip(counters(fast.evaluator), before)]
            assert a == b, (seed, len(rnd.history))
            skipped = bool(fast.last_decision_record.get("single_candidate_fast"))
            skipped_count += skipped
            assert comparable(plain.last_decision_record, skipped) \
                == comparable(fast.last_decision_record, skipped), (seed, len(rnd.history))
            assert plain.sampler.rng.getstate() == fast.sampler.rng.getstate()
            if SINGLE not in switches:
                assert delta_plain == delta_fast
                rows += delta_fast[2]
            rnd.play(seat, a)
            decisions += 1
    assert decisions > 100 and len(card_counts) >= 20
    assert (skipped_count > 0) == (SINGLE in switches)
    assert (rows > 0) == (SINGLE not in switches)


def test_the_switches_leave_the_served_name_unchanged(monkeypatch, pinned_production_package,
                                                      pinned_belief_package):  # noqa: F811
    from shengji.train import pv_search_policy as pv
    from test_release46_fly_config import PACKAGE_SHA, fly_env

    base = {**fly_env(), "SHENGJI_PV_CKPT": str(pinned_production_package),
            "SHENGJI_PV_SHA256": PACKAGE_SHA,
            "SHENGJI_PV_BELIEF_CKPT": str(pinned_belief_package)}
    for extra in ({}, {PREFIX: "1"}, {SINGLE: "1"}, {PREFIX: "1", SINGLE: "1"},
                  {"SHENGJI_PV_EXACT_WORLD_SUBSET": "64"}):
        recipe = pv.pv_env_recipe({**base, **extra})
        assert list(pv.pv_registry_entries(**recipe)) == [RELEASE46]


def test_the_harvest_refuses_the_inherited_switch_and_harvests_finite_means_without_it(
        monkeypatch, pinned_production_package, pinned_belief_package):  # noqa: F811
    """The real release-46 factory under the trajectory harvest: with the
    switch inherited from the environment it refuses before building; without
    it a one-candidate decision harvests a finite action value."""
    import math
    import random
    from shengji.harvest import trajectory

    env, name, factory = served_entries(pinned_production_package, pinned_belief_package)
    monkeypatch.setattr(trajectory, "make_bot", lambda policy, seed: factory(seed=seed))
    config = {"policy": name, "explore_rate": 0.0, "explore_k": 0, "cap": 256}
    monkeypatch.setenv(SINGLE, "1")
    with pytest.raises(trajectory.TrajectoryError, match=SINGLE):
        trajectory.make_trajectory_bot(config, seed=17, explore_rng=random.Random(0))
    monkeypatch.delenv(SINGLE)
    harvest = trajectory.make_trajectory_bot(config, seed=17, explore_rng=random.Random(0))
    rnd = _play_state(17)
    singles = 0
    while rnd.phase == "play" and singles < 2:
        seat = rnd.turn
        played = harvest.decide_play(copy.deepcopy(rnd), seat)
        record = harvest.last_decision_record
        _, _, values = trajectory.pv_fields_from_record(record, harvest.last_ballot)
        assert all(math.isfinite(m) for m in values["means"])
        singles += len(record["admitted"]) == 1
        rnd.play(seat, played)
    assert singles == 2
