"""The served accumulator must not move when the probe captures per-world values (#625).

Codex's acceptance list for this refactor, made executable.  The reference in every
differential test is a verbatim copy of the loop as it stood BEFORE `_score_leaves`
existed, so "unchanged" is checked against the old code rather than against a
description of it.

Why bit-equality rather than `allclose`: the search argmaxes over candidate values, so
a reordered float sum that shifts a near-tie changes the card played.  `allclose` would
hide exactly the failure that matters.
"""

from __future__ import annotations

import numpy as np
import pytest

from shengji.train.pv_search_policy import PVSearchBot, PVSearchPolicyError


# --------------------------------------------------------------------- harness

class _Evaluator:
    """Scores leaves by the cell they came from, and records the call pattern."""

    def __init__(self, value):
        self.value = value          # (world, action) -> float
        self.calls = []             # batch sizes, in order

    def score(self, leaves, seat):
        self.calls.append(len(leaves))
        return [self.value(w, a) for (w, a) in leaves]


class _Harness(PVSearchBot):
    """The real `_score_leaves` on a stub: a leaf IS its (world, action) cell."""

    def __init__(self, evaluator, batch_size):
        self.evaluator = evaluator
        self.batch_size = batch_size

    def _leaf(self, rnd, seat, hands, buried, action, world_index):
        return (world_index, action)


def _legacy_value_means(bot, rnd, seat, actions, worlds, check_budget=None):
    """The loop exactly as it was before the refactor. The differential reference."""
    sums = np.zeros(len(actions), dtype=np.float64)
    pending, indices = [], []
    batches = 0

    def flush():
        nonlocal batches
        if not pending:
            return
        if check_budget is not None:
            check_budget()
        scores = np.asarray(bot.evaluator.score(pending, seat), dtype=np.float64)
        if scores.shape != (len(pending),) or not np.isfinite(scores).all():
            raise ValueError("value evaluator requires one finite root-team score per leaf")
        np.add.at(sums, indices, scores)
        batches += 1
        pending.clear()
        indices.clear()
        if check_budget is not None:
            check_budget()

    for world_index, (hands, buried) in enumerate(worlds):
        for index, action in enumerate(actions):
            pending.append(bot._leaf(rnd, seat, hands, buried, action, world_index))
            indices.append(index)
            if len(pending) == bot.batch_size:
                flush()
    flush()
    return sums / len(worlds), batches


def _worlds(n):
    return [([], []) for _ in range(n)]


SHAPES = [(1, 1, 1), (1, 8, 128), (3, 2, 1), (4, 3, 5), (5, 4, 7),
          (64, 8, 128), (9, 7, 63), (7, 9, 64), (2, 5, 9)]


# ----------------------------------------------------------------- differential

@pytest.mark.parametrize("n_worlds,n_actions,batch", SHAPES)
def test_served_means_are_bit_identical_with_and_without_capture(n_worlds, n_actions, batch):
    rng = np.random.default_rng(17)
    table = rng.normal(size=(n_worlds, n_actions))
    value = lambda w, a: float(table[w, a])
    actions, worlds = list(range(n_actions)), _worlds(n_worlds)

    ref = _Harness(_Evaluator(value), batch)
    got = _Harness(_Evaluator(value), batch)
    legacy_means, legacy_batches = _legacy_value_means(ref, None, 0, actions, worlds)
    matrix, sums, batches = got.value_matrix(None, 0, actions, worlds)

    assert (sums / n_worlds).tobytes() == legacy_means.tobytes()
    assert batches == legacy_batches
    assert got.evaluator.calls == ref.evaluator.calls


@pytest.mark.parametrize("n_worlds,n_actions,batch", SHAPES)
def test_capture_does_not_move_the_plain_value_means_path(n_worlds, n_actions, batch):
    rng = np.random.default_rng(23)
    table = rng.normal(size=(n_worlds, n_actions))
    value = lambda w, a: float(table[w, a])
    actions, worlds = list(range(n_actions)), _worlds(n_worlds)

    a = _Harness(_Evaluator(value), batch)
    b = _Harness(_Evaluator(value), batch)
    means_a, batches_a = a._value_means(None, 0, actions, worlds)
    means_b, batches_b = _legacy_value_means(b, None, 0, actions, worlds)
    assert means_a.tobytes() == means_b.tobytes()
    assert batches_a == batches_b
    assert a.evaluator.calls == b.evaluator.calls


def test_cancellation_prone_scores_still_match_the_legacy_sum():
    # values that cancel catastrophically: the sum's ORDER decides the result
    n_worlds, n_actions, batch = 12, 3, 5
    def value(w, a):
        return (1e16 if w % 2 == 0 else -1e16) + (w + a) * 1e-3
    actions, worlds = list(range(n_actions)), _worlds(n_worlds)
    ref, got = _Harness(_Evaluator(value), batch), _Harness(_Evaluator(value), batch)
    legacy, _ = _legacy_value_means(ref, None, 0, actions, worlds)
    _, sums, _ = got.value_matrix(None, 0, actions, worlds)
    assert (sums / n_worlds).tobytes() == legacy.tobytes()


def test_near_ties_pick_the_same_winner_as_the_legacy_reducer():
    # two actions separated by one ulp-ish margin after averaging
    n_worlds, batch = 32, 7
    def value(w, a):
        return 1.0 + (1e-13 if a == 1 else 0.0) + (w % 3) * 1e-9
    actions, worlds = [0, 1], _worlds(n_worlds)
    ref, got = _Harness(_Evaluator(value), batch), _Harness(_Evaluator(value), batch)
    legacy, _ = _legacy_value_means(ref, None, 0, actions, worlds)
    matrix, sums, _ = got.value_matrix(None, 0, actions, worlds)
    assert int(np.argmax(sums / n_worlds)) == int(np.argmax(legacy))
    # and the matrix's own re-sum is NOT guaranteed to agree: that is why the
    # control arm must reduce with `sums`, not with the matrix (Codex, #625)
    assert (sums / n_worlds).tobytes() == legacy.tobytes()


# -------------------------------------------------------------------- alignment

def test_every_cell_holds_its_own_world_and_action_value():
    n_worlds, n_actions, batch = 6, 4, 5     # 24 leaves, partial final batch
    value = lambda w, a: w * 100.0 + a
    actions, worlds = list(range(n_actions)), _worlds(n_worlds)
    matrix, sums, _ = _Harness(_Evaluator(value), batch).value_matrix(None, 0, actions, worlds)
    for w in range(n_worlds):
        for a in range(n_actions):
            assert matrix[w, a] == w * 100.0 + a
    assert np.allclose(sums, matrix.sum(axis=0))


def test_partial_final_batch_fills_every_cell():
    for n_worlds, n_actions, batch in ((5, 3, 4), (7, 2, 13), (3, 3, 2)):
        actions, worlds = list(range(n_actions)), _worlds(n_worlds)
        matrix, _, _ = _Harness(_Evaluator(lambda w, a: 1.0), batch).value_matrix(
            None, 0, actions, worlds)
        assert np.isfinite(matrix).all()
        assert matrix.shape == (n_worlds, n_actions)


# --------------------------------------------------------------------- refusals

def test_non_finite_evaluator_output_refuses_in_both_paths():
    actions, worlds = [0, 1], _worlds(2)
    bad = lambda w, a: np.inf if (w, a) == (1, 0) else 1.0
    with pytest.raises(ValueError):
        _Harness(_Evaluator(bad), 128)._value_means(None, 0, actions, worlds)
    with pytest.raises(ValueError):
        _Harness(_Evaluator(bad), 128).value_matrix(None, 0, actions, worlds)


def test_wrong_length_evaluator_output_refuses():
    class Short(_Evaluator):
        def score(self, leaves, seat):
            super().score(leaves, seat)
            return [1.0] * (len(leaves) - 1)
    actions, worlds = [0, 1], _worlds(2)
    with pytest.raises(ValueError):
        _Harness(Short(lambda w, a: 1.0), 128).value_matrix(None, 0, actions, worlds)


def test_budget_failure_propagates_mid_batch_and_post_batch():
    actions, worlds = [0, 1], _worlds(8)        # 16 leaves, batch 4 -> 4 batches

    class Stop(RuntimeError):
        pass

    for fire_on in (1, 2, 5, 8):                # pre-score and post-score checks alternate
        calls = {"n": 0}

        def check_budget():
            calls["n"] += 1
            if calls["n"] == fire_on:
                raise Stop("deadline")

        with pytest.raises(Stop):
            _Harness(_Evaluator(lambda w, a: 1.0), 4).value_matrix(
                None, 0, actions, worlds, check_budget=check_budget)


def test_an_unfilled_cell_is_refused_rather_than_returned_as_nan():
    # an evaluator that silently drops a leaf's score cannot produce a complete matrix
    class Sneaky(_Evaluator):
        def score(self, leaves, seat):
            super().score(leaves, seat)
            return [float("nan")] * len(leaves)
    actions, worlds = [0, 1], _worlds(2)
    with pytest.raises(ValueError):             # non-finite is caught first
        _Harness(Sneaky(lambda w, a: 1.0), 128).value_matrix(None, 0, actions, worlds)


def test_default_serving_allocates_no_matrix():
    # `_value_means` must not build a capture array: the stub records any allocation
    seen = {}
    class Watch(_Harness):
        def _score_leaves(self, rnd, seat, actions, worlds, check_budget=None, capture=None):
            seen["capture"] = capture
            return super()._score_leaves(rnd, seat, actions, worlds, check_budget, capture)
    Watch(_Evaluator(lambda w, a: 1.0), 128)._value_means(None, 0, [0], _worlds(2))
    assert seen["capture"] is None
