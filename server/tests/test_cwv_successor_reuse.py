"""Small witnesses for bounded duplicate-afterstate reuse."""
from __future__ import annotations

import copy

from shengji.ai import cwv_policy
from shengji.ai.cwv_successor_reuse import TensorInputCache, WorldSuccessorCache
from shengji.engine.round import actual_play_after
from shengji.harvest.legal import enumerate_legal
from shengji.rl.value_afterstate import tensors_from_round
from tests.test_world_shortlist import play_state


def _world(rnd):
    return [list(hand) for hand in rnd.hands], list(rnd.buried)


def _accepted_candidates(rnd):
    seat = rnd.turn
    world = _world(rnd)
    seen = {}
    unique = []
    duplicate = None
    for candidate in enumerate_legal(rnd, seat, cap=None).actions:
        clone = cwv_policy.afterstate(rnd, seat, *world, candidate,
                                      finish_trick=False)
        accepted = tuple(actual_play_after(clone, seat, rnd.last_trick))
        if accepted in seen and duplicate is None:
            duplicate = (seen[accepted], candidate, accepted)
        if accepted not in seen:
            seen[accepted] = candidate
            unique.append(candidate)
        if duplicate is not None and len(unique) >= 3:
            break
    assert duplicate is not None and len(unique) >= 3
    return seat, world, duplicate, unique[:3]


def _tensor_bytes(tensors):
    return tuple(getattr(tensors, name).tobytes()
                 for name in ("public", "history", "world", "perspective"))


def _round_signature(rnd):
    return (
        rnd.phase, rnd.turn, tuple(tuple(hand) for hand in rnd.hands),
        tuple(rnd.buried),
        tuple(tuple((play.seat, tuple(play.cards)) for play in trick.plays)
              for trick in rnd.history),
        None if rnd.trick is None else tuple(
            (play.seat, tuple(play.cards)) for play in rnd.trick.plays),
    )


def test_duplicate_submitted_throws_share_exact_finished_leaf_and_tensors(monkeypatch):
    rnd = play_state()
    seat, world, (first, second, accepted), _unique = _accepted_candidates(rnd)
    calls = []
    original_finisher = cwv_policy.finish_current_trick

    def counted_finisher(clone):
        calls.append(clone)
        return original_finisher(clone)

    monkeypatch.setattr(cwv_policy, "finish_current_trick", counted_finisher)
    root_before = _round_signature(rnd)
    cache = WorldSuccessorCache(rnd, seat, *world)
    first_leaf = cache.leaf(first)
    second_leaf = cache.leaf(second)
    assert first_leaf is second_leaf
    assert calls == [first_leaf]
    assert cache.counters["root_actions"] == 2
    assert cache.counters["leaf_completions"] == 1
    assert cache.counters["leaf_hits"] == 1
    assert _round_signature(rnd) == root_before

    expected = cwv_policy.afterstate(rnd, seat, *world, first,
                                     finish_trick=False)
    original_finisher(expected)
    assert tuple(actual_play_after(
        cwv_policy.afterstate(rnd, seat, *world, first,
                              finish_trick=False), seat, rnd.last_trick)) == accepted
    encoder_calls = []

    def encoder(leaf, encoder_seat):
        encoder_calls.append(leaf)
        return tensors_from_round(leaf, encoder_seat)

    tensor_cache = TensorInputCache()
    first_tensors = tensor_cache.encode(first_leaf, encoder, seat)
    assert tensor_cache.encode(second_leaf, encoder, seat) is first_tensors
    assert len(encoder_calls) == 1
    assert _tensor_bytes(first_tensors) == _tensor_bytes(
        tensors_from_round(expected, seat))


def test_world_and_root_instances_have_independent_leaf_namespaces():
    rnd = play_state()
    seat, world, (candidate, _other, _accepted), _unique = _accepted_candidates(rnd)
    first = WorldSuccessorCache(rnd, seat, *world).leaf(candidate)
    changed_world = copy.deepcopy(world)
    changed_world[0][(seat + 1) % 4][0], changed_world[0][(seat + 2) % 4][0] = (
        changed_world[0][(seat + 2) % 4][0], changed_world[0][(seat + 1) % 4][0])
    second = WorldSuccessorCache(rnd, seat, *changed_world).leaf(candidate)
    third = WorldSuccessorCache(copy.deepcopy(rnd), seat, *world).leaf(candidate)
    assert first is not second
    assert first is not third


def test_follow_and_terminal_resolution_use_actual_play_after():
    follow = play_state()
    follow.play(follow.turn, cwv_policy.default_finisher().decide_play(
        follow, follow.turn))
    seat = follow.turn
    candidate = enumerate_legal(follow, seat, cap=None).actions[0]
    cache = WorldSuccessorCache(follow, seat, *_world(follow))
    leaf = cache.leaf(candidate)
    assert len(leaf.history) == 1
    expected = cwv_policy.afterstate(follow, seat, *_world(follow), candidate,
                                     finish_trick=False)
    accepted = tuple(actual_play_after(expected, seat, follow.last_trick))
    assert accepted == tuple(actual_play_after(leaf, seat, follow.last_trick))

    near_end = copy.deepcopy(play_state())
    # Use the real policy to create a state with three plays in the final trick.
    while len(near_end.history) < 24:
        action = next(action for action in enumerate_legal(
            near_end, near_end.turn, cap=None).actions if len(action) == 1)
        near_end.play(near_end.turn, action)
    while len(near_end.trick.plays) < 3:
        action = next(action for action in enumerate_legal(
            near_end, near_end.turn, cap=None).actions if len(action) == 1)
        near_end.play(near_end.turn, action)
    seat = near_end.turn
    candidate = enumerate_legal(near_end, seat, cap=None).actions[0]
    cache = WorldSuccessorCache(near_end, seat, *_world(near_end))
    raw = cwv_policy.afterstate(near_end, seat, *_world(near_end), candidate,
                                finish_trick=False)
    accepted = tuple(actual_play_after(raw, seat, near_end.last_trick))
    terminal = cache.leaf(candidate)
    assert terminal.phase == "round_end"
    assert accepted == tuple(actual_play_after(terminal, seat, near_end.last_trick))


def test_small_lru_eviction_preserves_leaf_output(monkeypatch):
    rnd = play_state()
    seat, world, _duplicate, unique = _accepted_candidates(rnd)
    calls = []
    original = cwv_policy.finish_current_trick

    def counted(clone):
        calls.append(clone)
        return original(clone)

    monkeypatch.setattr(cwv_policy, "finish_current_trick", counted)
    cache = WorldSuccessorCache(rnd, seat, *world, max_entries=2)
    leaves = [cache.leaf(candidate) for candidate in unique]
    assert cache.entries == 2 and cache.peak_entries == 2
    again = cache.leaf(unique[0])
    assert cache.entries == 2
    assert len(calls) == 4
    assert _tensor_bytes(tensors_from_round(again, seat)) == _tensor_bytes(
        tensors_from_round(leaves[0], seat))


def test_tensor_cache_is_separate_bounded_and_encoder_identity_sensitive():
    rnd = play_state()
    seat, world, (candidate, _other, _accepted), unique = _accepted_candidates(rnd)
    world_cache = WorldSuccessorCache(rnd, seat, *world, max_entries=2)
    leaf = world_cache.leaf(candidate)
    tensor_cache = TensorInputCache(max_entries=2)
    calls = []

    def encoder_one(value, encoder_seat):
        calls.append("one")
        return tensors_from_round(value, encoder_seat)

    def encoder_two(value, encoder_seat):
        calls.append("two")
        return tensors_from_round(value, encoder_seat)

    first = tensor_cache.encode(leaf, encoder_one, seat)
    assert tensor_cache.encode(leaf, encoder_one, seat) is first
    other_seat = (seat + 1) % 4
    other = tensor_cache.encode(leaf, encoder_one, other_seat)
    second = tensor_cache.encode(leaf, encoder_two, seat)
    assert other is not first and second is not first
    assert calls == ["one", "one", "two"]
    assert not first.public.flags.writeable
    for extra in unique[1:]:
        tensor_cache.encode(world_cache.leaf(extra), encoder_one, seat)
    assert tensor_cache.entries <= 2
    completions_before = tensor_cache.completions
    evicted = tensor_cache.encode(leaf, encoder_one, seat)
    assert tensor_cache.completions == completions_before + 1
    assert _tensor_bytes(evicted) == _tensor_bytes(first)
