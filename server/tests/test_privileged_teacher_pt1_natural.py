"""Focused PT1 natural-population coverage and leakage witnesses."""

from __future__ import annotations

import copy
from dataclasses import replace
import hashlib
import random

import pytest

from shengji.engine.cards import Ordering, make_deck
from shengji.engine.round import Round, Trick
from shengji.rl import privileged_teacher_pt1_natural as natural
from shengji.rl.privileged_teacher_pt1 import seal_true_world


SECRET = bytes(range(32))
SECRET_SHA = hashlib.sha256(SECRET).hexdigest()


def _design():
    return natural.NaturalPT1Design(capture_secret_sha256=SECRET_SHA)


def _captured(monkeypatch):
    design = _design()
    monkeypatch.setattr(natural, "_first_eligible",
                        lambda state, *, role, threshold: copy.deepcopy(state))
    return design, natural.capture_natural_states(
        design, capture_secret=SECRET, state_capture=_capture_callback)


def _round(rank: str, banker: int, role: str, threshold: int,
           *, hidden: int = 0) -> Round:
    deck = make_deck()
    actor = banker if role == "banker-team" else (banker + 1) % 4
    hands = [[deck[(seat * 10 + index + hidden) % len(deck)]
              for index in range(threshold)] for seat in range(4)]
    rnd = Round(rank, banker=banker, rng=random.Random(0))
    rnd.phase = "play"
    rnd.ordering = Ordering("H", rank)
    rnd.trump_suit = "H"
    rnd.trump_is_nt = False
    rnd.hands = hands
    rnd.buried = [deck[100], deck[101]]
    rnd.trick = Trick(leader=actor)
    rnd.turn = actor
    rnd.deck = deck
    return rnd


def _capture_callback(design, seed, rank, banker, role, threshold, replicate):
    # The seed-derived hidden offset makes distinct true worlds while keeping
    # actor-visible fields stable for same-cell hidden-twin checks.
    return _round(rank, banker, role, threshold, hidden=seed % 3)


def test_exact_416_coverage_and_distinct_round_clusters(monkeypatch):
    design = _design()
    monkeypatch.setattr(natural, "_first_eligible",
                        lambda state, *, role, threshold: copy.deepcopy(state))
    states = natural.capture_natural_states(
        design, capture_secret=SECRET, state_capture=_capture_callback)
    assert len(states) == 416
    assert set(states) == set(design.state_keys)
    assert len({state.capture_round_cluster_sha256 for state in states.values()}) == 416
    assert all("true_world" not in state.payload() and
               "round_seed" not in state.payload() for state in states.values())
    natural.validate_population(design, states)


def test_capture_is_deterministic(monkeypatch):
    design = _design()
    monkeypatch.setattr(natural, "_first_eligible",
                        lambda state, *, role, threshold: copy.deepcopy(state))
    first = natural.capture_natural_states(
        design, capture_secret=SECRET, state_capture=_capture_callback)
    second = natural.capture_natural_states(
        design, capture_secret=SECRET, state_capture=_capture_callback)
    assert [first[key].payload() for key in design.state_keys] == \
        [second[key].payload() for key in design.state_keys]


def test_public_identity_is_hidden_twin_invariant_true_world_changes():
    design = _design()
    first = _round("7", 0, "attacker-team", 3, hidden=0)
    second = _round("7", 0, "attacker-team", 3, hidden=1)
    # Restore the actor hand so only hidden hands differ.
    second.hands[1] = list(first.hands[1])
    left = natural._state_from_round(
        design, first, rank="7", banker=0, role="attacker-team",
        threshold=3, replicate=0, round_seed=1)
    right = natural._state_from_round(
        design, second, rank="7", banker=0, role="attacker-team",
        threshold=3, replicate=1, round_seed=2)
    assert left.public_state_sha256 == right.public_state_sha256
    assert left.true_world_sha256 != right.true_world_sha256

    burial_twin = copy.deepcopy(first)
    burial_twin.buried[1] = make_deck()[102]
    buried = natural._state_from_round(
        design, burial_twin, rank="7", banker=0, role="attacker-team",
        threshold=3, replicate=2, round_seed=3)
    assert left.public_state_sha256 == buried.public_state_sha256
    assert left.true_world_sha256 != buried.true_world_sha256


def test_design_refuses_nonproduction_policy():
    with pytest.raises(natural.NaturalPT1Error, match="mc-s0-report-lcb"):
        natural.NaturalPT1Design(
            capture_secret_sha256=SECRET_SHA, production_policy="heuristic")


def test_capture_requires_actual_multi_candidate_production_search(monkeypatch):
    from shengji.ai import endgame, registry

    rnd = _round("7", 0, "attacker-team", 3)
    monkeypatch.setattr(endgame, "exhaustive_legal_actions",
                        lambda *_args, **_kwargs: (("C2",), ("D2",)))

    class FakeBot:
        TRACTOR_LOCK = False

        def _candidates(self, _rnd, _seat):
            return [["C2"]]

    monkeypatch.setattr(registry, "make_bot", lambda *_args, **_kwargs: FakeBot())
    assert natural._first_eligible(
        rnd, role="attacker-team", threshold=3) is None

    FakeBot._candidates = lambda self, _rnd, _seat: [["C2"], ["D2"]]
    accepted = natural._first_eligible(
        rnd, role="attacker-team", threshold=3)
    assert accepted is not None and accepted is not rnd


def test_capture_rejects_production_tractor_lock_early_return(monkeypatch):
    from types import SimpleNamespace
    from shengji.ai import endgame, registry
    from shengji.engine import combos

    rnd = _round("7", 0, "attacker-team", 3)
    monkeypatch.setattr(endgame, "exhaustive_legal_actions",
                        lambda *_args, **_kwargs: (("C2",), ("D2",)))
    monkeypatch.setattr(
        combos, "decompose",
        lambda *_args, **_kwargs: SimpleNamespace(
            components=(SimpleNamespace(pair_len=2),)))

    class FakeBot:
        TRACTOR_LOCK = True

        def canonical_lead(self, _rnd, _seat):
            return ["C2", "C2"]

        def _candidates(self, _rnd, _seat):
            return [["C2"], ["D2"]]

    monkeypatch.setattr(registry, "make_bot", lambda *_args, **_kwargs: FakeBot())
    assert natural._first_eligible(
        rnd, role="attacker-team", threshold=3) is None


def test_population_rejects_every_load_bearing_identity_mutation(monkeypatch):
    design, states = _captured(monkeypatch)
    key = design.state_keys[0]
    original = states[key]
    mutations = {
        "schema": "wrong-schema",
        "rank": "A",
        "banker": 1,
        "role": "attacker-team",
        "remaining_hand_threshold": 4,
        "replicate": 1,
        "round_seed": original.round_seed + 1,
        "capture_round_cluster_sha256": "a" * 64,
        "capture_id_sha256": "b" * 64,
        "public_state_sha256": "c" * 64,
        "true_world_sha256": "d" * 64,
    }
    for field, value in mutations.items():
        mutated = dict(states)
        mutated[key] = replace(original, **{field: value})
        with pytest.raises(natural.NaturalPT1Error):
            natural.validate_population(design, mutated)

    changed_world = copy.deepcopy(original.true_world.verify())
    changed_world.buried[1] = make_deck()[102]
    mutated = dict(states)
    mutated[key] = replace(
        original, true_world=seal_true_world(changed_world))
    with pytest.raises(natural.NaturalPT1Error, match="true-world"):
        natural.validate_population(design, mutated)


def test_incomplete_and_duplicate_population_refuse(monkeypatch):
    design = _design()
    monkeypatch.setattr(natural, "_first_eligible",
                        lambda state, *, role, threshold: copy.deepcopy(state))

    def missing(design, seed, rank, banker, role, threshold, replicate):
        if rank == design.trump_ranks[0] and banker == 0 and role == "banker-team" \
                and threshold == 3 and replicate == 0:
            return None
        return _capture_callback(design, seed, rank, banker, role, threshold, replicate)

    with pytest.raises(natural.NaturalPT1Error, match="incomplete"):
        natural.capture_natural_states(
            design, capture_secret=SECRET, state_capture=missing)

    monkeypatch.setattr(natural, "_capture_round_seed", lambda *args: 1)
    with pytest.raises(natural.NaturalPT1Error, match="seed collision"):
        natural.capture_natural_states(
            design, capture_secret=SECRET, state_capture=_capture_callback)
