"""Actor-visible and bounded contracts for bury/first-lead exploration."""
from __future__ import annotations

import copy
import random
from collections import Counter

import pytest

from shengji.ai.bury_lead_combo import (
    action_key,
    build_bury_lead_combo_ballot,
)
from shengji.ai.registry import REGISTRY, make_bot
from shengji.engine.game import Game
from shengji.engine.legal import uniform_suit


def _bury_round(seed: int = 0):
    rnd = Game(random.Random(seed)).start_round()
    while rnd.phase == "deal":
        rnd.deal_next()
    rnd.finalize_declare()
    assert rnd.phase == "bury" and rnd.banker is not None
    return rnd, rnd.banker


def _build(rnd, seat, *, seed: int = 7):
    bot = make_bot("mc-s0-report-lcb", seed=seed)
    incumbent = bot.decide_bury(rnd, seat)
    rng_before = bot.rng.getstate()
    ballot = build_bury_lead_combo_ballot(
        rnd, seat, incumbent, live_lead_ballot=bot._candidates)
    assert bot.rng.getstate() == rng_before, \
        "actor-visible combo sourcing must not consume search RNG"
    return ballot, incumbent


def test_combo_source_protects_incumbent_and_exposes_shape_actions():
    rnd, seat = _bury_round(0)
    hand_before = list(rnd.hands[seat])
    phase_before = rnd.phase
    ballot, incumbent = _build(rnd, seat)

    assert ballot.schema == "bury-first-lead-combo-ballot-v1"
    assert action_key(ballot.groups[0].bury.cards) == action_key(incumbent)
    assert ballot.record()["candidate_zero"]["bury_cards"] == \
        list(ballot.groups[0].bury.cards)
    assert ballot.combo_count == sum(len(group.leads)
                                      for group in ballot.groups)
    assert ballot.combo_count <= ballot.max_combos
    assert ballot.record()["strength_claim"] is False
    assert ballot.record()["production_policy_registered"] is False
    assert rnd.hands[seat] == hand_before and rnd.phase == phase_before

    represented_voids = {
        suit for group in ballot.groups for suit in group.bury.voids_created}
    assert set(ballot.feasible_single_suit_voids) <= represented_voids
    assert ballot.feasible_single_suit_voids, \
        "seed zero remains the named suit-void coverage witness"
    assert any(group.structured_throw_ballot.candidates
               for group in ballot.groups), \
        "seed zero remains the named shuai-pai combo witness"

    for group in ballot.groups:
        lead_keys = {lead.cards for lead in group.leads}
        for card in group.retained_shape["pair_codes"]:
            assert (card, card) in lead_keys
        assert {
            candidate.cards
            for candidate in group.structured_throw_ballot.candidates
        } <= lead_keys
        assert any("live_ballot_candidate_zero" in lead.sources
                   for lead in group.leads[:1])


def test_every_combo_attempt_is_held_and_one_effective_suit():
    rnd, seat = _bury_round(0)
    ballot, _ = _build(rnd, seat)
    ordering = rnd.ordering
    assert ordering is not None
    original = Counter(rnd.hands[seat])
    for group in ballot.groups:
        retained = original - Counter(group.bury.cards)
        assert sum(retained.values()) == 25
        for lead in group.leads:
            assert not (Counter(lead.cards) - retained)
            assert uniform_suit(list(lead.cards), ordering) is not None
            if lead.structured_throw:
                assert lead.component_count >= 2


def test_source_is_invariant_to_opponent_hands_and_hidden_deck():
    rnd, seat = _bury_round(0)
    first, incumbent = _build(rnd, seat)
    altered = copy.deepcopy(rnd)
    for other in range(4):
        if other != seat:
            altered.hands[other] = ["BJ"] * len(altered.hands[other])
    altered.deck = ["LJ"] * len(altered.deck)
    bot = make_bot("mc-s0-report-lcb", seed=7)
    second = build_bury_lead_combo_ballot(
        altered, seat, incumbent, live_lead_ballot=bot._candidates)
    assert second.record() == first.record()


def test_source_is_permutation_stable_for_actor_hand_and_incumbent():
    rnd, seat = _bury_round(0)
    first, incumbent = _build(rnd, seat)
    permuted = copy.deepcopy(rnd)
    permuted.hands[seat] = list(reversed(permuted.hands[seat]))
    bot = make_bot("mc-s0-report-lcb", seed=7)
    second = build_bury_lead_combo_ballot(
        permuted, seat, list(reversed(incumbent)),
        live_lead_ballot=bot._candidates)
    assert second.record() == first.record()


def test_live_lead_cap_refuses_instead_of_silently_truncating():
    rnd, seat = _bury_round(0)
    incumbent = make_bot("mc-s0-report-lcb", seed=7).decide_bury(rnd, seat)

    def oversized(_view, _seat):
        return [["S2"]] * 15

    with pytest.raises(ValueError, match="exceeded cap"):
        build_bury_lead_combo_ballot(
            rnd, seat, incumbent, live_lead_ballot=oversized)


def test_combo_source_registers_no_policy():
    assert not any("bury-lead-combo" in name for name in REGISTRY)
