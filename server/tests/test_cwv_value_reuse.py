from types import SimpleNamespace
import gc
import weakref

import numpy as np
import pytest
from tests.test_cwv_numpy_joint import joint  # noqa: F401

from shengji.ai.cwv_value_reuse import SuccessorValueCache


class Leaf:
    def __init__(self, value): self.value = value


class Evaluator:
    def __init__(self): self.calls = []
    def score(self, states, seat, **kwargs):
        self.calls.append((list(states), seat, kwargs))
        return np.asarray([s.value + seat for s in states])


def test_dedup_order_multiplicity_and_perspective():
    evaluator = Evaluator()
    cache = SuccessorValueCache(evaluator)
    a, b = Leaf(2), Leaf(7)
    assert cache.score([b, a, b, a], 0).tolist() == [7, 2, 7, 2]
    assert evaluator.calls[0][0] == [b, a]
    assert cache.score([a, b], 0).tolist() == [2, 7]
    assert len(evaluator.calls) == 1
    assert cache.score([a, b], 1).tolist() == [3, 8]
    assert cache.rows == 8 and cache.forwarded_rows == 4


def test_distinct_equal_objects_are_not_coalesced():
    evaluator = Evaluator()
    cache = SuccessorValueCache(evaluator)
    cache.score([Leaf(1), Leaf(1)], 0)
    assert cache.forwarded_rows == 2


def test_eviction_retains_live_identity_and_releases_evicted_objects():
    evaluator = SimpleNamespace(score=lambda states, seat: [s.value for s in states])
    cache = SuccessorValueCache(evaluator, max_entries=1)
    a, b = Leaf(2), Leaf(7)
    ref = weakref.ref(a)
    cache.score([a], 0)
    del a
    gc.collect()
    assert ref() is not None
    cache.score([b], 0)
    gc.collect()
    assert ref() is None
    assert cache.peak_entries == 1


def test_batch_larger_than_cache_scatter_and_recompute():
    evaluator = Evaluator()
    cache = SuccessorValueCache(evaluator, max_entries=1)
    a, b = Leaf(2), Leaf(7)
    assert cache.score([a, b, a], 0).tolist() == [2, 7, 2]
    cache.score([a], 0)
    assert cache.forwarded_rows == 3


@pytest.mark.parametrize("bad", [[float('nan')], [1, 2], [[1]]])
def test_invalid_result_not_cached(bad):
    evaluator = SimpleNamespace(score=lambda states, seat: bad)
    cache = SuccessorValueCache(evaluator)
    with pytest.raises(ValueError, match="finite scalar"):
        cache.score([Leaf(1)], 0)
    assert not cache._entries and cache.rows == 0


def test_cache_scope_new_decision_reads_current_state_and_evaluator():
    state = Leaf(1)
    a = SuccessorValueCache(Evaluator())
    assert a.score([state], 0).tolist() == [1]
    # Mutation is allowed between decisions, never while an old cache is used.
    state.value = 8
    b = SuccessorValueCache(Evaluator())
    assert b.score([state], 0).tolist() == [8]


def test_tensor_cache_forwarded_and_empty_batch():
    evaluator = Evaluator()
    cache = SuccessorValueCache(evaluator)
    token = object()
    cache.score([Leaf(1)], 0, tensor_cache=token)
    assert evaluator.calls[0][2] == {"tensor_cache": token}
    assert cache.score([], 0).shape == (0,)


@pytest.mark.parametrize("limit", [True, 0, -1, 1.5])
def test_invalid_bound(limit):
    with pytest.raises(ValueError): SuccessorValueCache(Evaluator(), max_entries=limit)


def test_recipe_is_opt_in_and_preserves_old_digest():
    from shengji.train.cwv_shortlist import resolved_recipe, recipe_digest
    old = resolved_recipe(reuse_successors=True)
    assert "reuse_values" not in old
    assert resolved_recipe(reuse_successors=True, reuse_values=False) == old
    assert recipe_digest(32, old) != recipe_digest(32, dict(old, reuse_values=True))
    with pytest.raises(ValueError): resolved_recipe(reuse_values=True, reuse_successors=False)
    with pytest.raises(ValueError): resolved_recipe(reuse_values="true")


def test_shortlist_constructor_requires_successor_ownership():
    from shengji.train.cwv_shortlist import CWVShortlistBot
    with pytest.raises(ValueError, match="immutable"):
        CWVShortlistBot(Evaluator(), reuse_values=True)


def test_actual_joint_factory_binds_name_and_preserves_shortlist(joint):
    from shengji.train.cwv_shortlist import make_shortlist_bot
    from tests.test_policy_prior import _round_in_play
    _, _, package, _ = joint
    state = _round_in_play(41, 4)
    bots, selected = [], []
    for enabled in (False, True):
        bot = make_shortlist_bot(package, seed=13, worlds=2, report_worlds=30,
            encoding="mlp-static", reuse_successors=True, reuse_values=enabled,
            prior_checkpoint=package, prior_threshold=1000, prior_top=8)
        selected.append(bot._candidates(state, state.turn))
        bots.append(bot)
    assert bots[0].policy_name != bots[1].policy_name
    assert selected[0] == selected[1]
    assert bots[0].rng.getstate() == bots[1].rng.getstate()
    np.testing.assert_allclose(bots[0].last_shortlist["shortlist_means"],
        bots[1].last_shortlist["shortlist_means"], rtol=0, atol=1e-12)
    assert bots[0].last_value_reuse is None
    assert bots[1].last_value_reuse["peak_entries"] <= 128
    # A second sweep starts a fresh cache, not a stale-score continuation.
    bots[1]._candidates(state, state.turn)
    assert bots[1].last_value_reuse["forwarded_rows"] > 0
    with pytest.raises(ValueError, match="derived"):
        make_shortlist_bot(package, reuse_successors=True, reuse_values=True,
                           name=bots[0].policy_name)


def test_registry_carries_opt_in_to_joint_consumer(joint):
    from shengji.train.cwv_shortlist import shortlist_registry_entries
    _, _, package, _ = joint
    common = dict(reuse_successors=True, prior_checkpoint=package,
                  prior_threshold=1000, prior_top=8)
    old = shortlist_registry_entries(package, [2], **common)
    enabled = shortlist_registry_entries(package, [2], reuse_values=True, **common)
    assert set(old).isdisjoint(enabled)
    name, factory = next(iter(enabled.items()))
    bot = factory(seed=13)
    assert bot.reuse_values is True
    assert bot.policy_name == name
    assert next(iter(old.values()))(seed=13).reuse_values is False
