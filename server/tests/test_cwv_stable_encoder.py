"""Cross-batch witnesses for stable versioned inference dispatch."""
import copy
from functools import partial

import numpy as np
import pytest

from scripts import cwv_prepared_lead_probe as probe
from shengji.ai import cwv_policy as policy
from shengji.ai.cwv_successor_reuse import TensorInputCache
from shengji.rl.value_model import ValueModelConfig, ValueNetwork
from shengji.train.cwv_shortlist import CWVShortlistBot, CWVShortlistConfig
from tests.test_cwv_successor_reuse import _accepted_candidates
from tests.test_cwv_v2_static_widen import _state_after
from tests.test_world_shortlist import play_state


def _evaluator(encoding="mlp-static", version=2):
    model = ValueNetwork(ValueModelConfig(
        architecture="mlp", width=8, feedforward_width=16, attention_heads=1,
        history_layers=1, public_dim=561 if version == 2 else 532,
        enc_version=version))
    return policy.CompleteWorldEvaluator(None, model=model, encoding=encoding,
                                         threads=1, max_batch=8)


@pytest.mark.parametrize("encoding", ["reference", "mlp-static"])
@pytest.mark.parametrize("seed,plies", [(61, 1), (62, 35), (63, 70)])
def test_real_scoring_reuses_same_leaf_across_batches_but_not_seats_or_worlds(encoding, seed, plies):
    rnd = _state_after(seed, plies)
    seat = rnd.turn
    evaluator = _evaluator(encoding)
    cache = TensorInputCache()
    first = evaluator.score([rnd], seat, tensor_cache=cache)
    second = evaluator.score([rnd], seat, tensor_cache=cache)
    np.testing.assert_array_equal(first, second)
    assert cache.counters == {"hits": 1, "completions": 1, "peak_entries": 1}
    # Identical-visible different world objects and different perspectives
    # must never become a cross-world or cross-seat cache hit.
    evaluator.score([copy.deepcopy(rnd)], seat, tensor_cache=cache)
    evaluator.score([rnd], (seat + 1) % 4, tensor_cache=cache)
    assert cache.counters == {"hits": 1, "completions": 3, "peak_entries": 3}
    assert evaluator.model_rows == 4  # This change does NOT cache model output.


def test_versioned_dispatch_tracks_mode_and_replaced_builder(monkeypatch):
    evaluator = _evaluator()
    static = evaluator.encoder
    assert static is evaluator.encoder
    assert static.func is policy.tensors_from_round_static
    assert static.keywords == {"version": 2}
    evaluator.encoding = "reference"
    reference = evaluator.encoder
    assert reference is evaluator.encoder and reference is not static
    assert reference.func is policy.tensors_from_round_v2
    evaluator.encoding = "mlp-static"
    assert evaluator.encoder is static

    original = policy.tensors_from_round_static
    calls = []

    def replacement(rnd, seat, *, version):
        calls.append(version)
        return original(rnd, seat, version=version)

    monkeypatch.setattr(policy, "tensors_from_round_static", replacement)
    replaced = evaluator.encoder
    assert replaced is not static and replaced is evaluator.encoder
    rnd = _state_after(61, 35)
    replaced(rnd, rnd.turn)
    assert calls == [2]


@pytest.mark.parametrize("encoding", ["reference", "mlp-static"])
def test_v1_dispatch_remains_the_original_callable(encoding):
    evaluator = _evaluator(encoding, version=1)
    expected = (policy.tensors_from_round_static if encoding == "mlp-static"
                else policy.tensors_from_round)
    assert evaluator.encoder is expected


def test_actual_shortlist_batch_loop_preserves_scores_and_restores_reuse(monkeypatch):
    rnd = play_state()
    seat, world, (first, second, _accepted), _ = _accepted_candidates(rnd)
    actions = [first, second, first, second]
    evaluator = _evaluator()
    config = CWVShortlistConfig(worlds=1, batch_size=1, selection_worlds=2)

    def run():
        bot = CWVShortlistBot(evaluator, seed=7, config=config, reuse_successors=True)
        values = bot._means(rnd, seat, actions, [world])
        return values, bot.last_successor_reuse, dict(bot.shortlist_counts)

    stable = policy._versioned_encoder
    with monkeypatch.context() as patcher:
        patcher.setattr(policy, "_versioned_encoder",
                        lambda builder, version: partial(builder, version=version))
        old_values, old_reuse, old_counts = run()
    assert policy._versioned_encoder is stable
    new_values, new_reuse, new_counts = run()
    np.testing.assert_array_equal(old_values, new_values)
    assert old_counts == new_counts  # Every original action/world row still scores.
    assert old_reuse["tensor_completions"] == 4 and old_reuse["tensor_hits"] == 0
    assert new_reuse["tensor_completions"] == 1 and new_reuse["tensor_hits"] == 3
    for key in ("root_actions", "leaf_hits", "leaf_completions", "peak_entries"):
        assert new_reuse[key] == old_reuse[key]


def test_dispatch_cache_is_bounded_and_retains_no_game_state():
    assert policy._versioned_encoder.cache_info().maxsize == 8
    def builder(rnd, seat, *, version):
        return rnd, seat, version
    for version in range(12):
        bound = policy._versioned_encoder(builder, version)
        assert bound.func is builder and bound.args == ()
        assert bound.keywords == {"version": version}
    assert policy._versioned_encoder.cache_info().currsize <= 8


def test_probe_switch_restores_dispatch_even_on_failure():
    stable = policy._versioned_encoder
    evaluator = _evaluator()
    with pytest.raises(RuntimeError, match="^injected probe failure$"):
        with probe._optimization_context("stable-v2-encoder", False):
            assert evaluator.encoder is not evaluator.encoder
            raise RuntimeError("injected probe failure")
    assert policy._versioned_encoder is stable
    with probe._optimization_context("stable-v2-encoder", True):
        assert evaluator.encoder is evaluator.encoder


def test_probe_comparison_exempts_only_the_three_named_tensor_counters():
    reuse = {"root_actions": 4, "leaf_completions": 1, "leaf_hits": 3,
             "tensor_completions": 4, "tensor_hits": 0, "peak_tensor_entries": 4}
    original = {"reuse": reuse, "shortlist": {"successor_reuse": reuse},
                "score_sha256": "score", "report": "report", "work": 4,
                "rng_sha256": "rng", "batches": {"1": 4}, "played": ["H2"]}
    changed = copy.deepcopy(original)
    changed["reuse"].update(tensor_completions=1, tensor_hits=3, peak_tensor_entries=1)
    compare = lambda row: probe._comparison_semantic(row, "stable-v2-encoder")
    assert compare(original) == compare(changed)
    assert original["reuse"]["tensor_completions"] == 4  # No artifact mutation.
    assert probe._comparison_semantic(original, "v2-static") != changed
    for key in ("score_sha256", "report", "work", "rng_sha256", "batches", "played"):
        mutated = copy.deepcopy(changed)
        mutated[key] = "drift"
        assert compare(original) != compare(mutated), key
    for container in ("reuse", "shortlist"):
        mutated = copy.deepcopy(changed)
        target = mutated[container]
        if container == "shortlist":
            target = target["successor_reuse"]
        target["leaf_completions"] = 0
        assert compare(original) != compare(mutated), container
