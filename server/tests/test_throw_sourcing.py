"""S6 bounded throw-source falsification and KESP replay witnesses."""
from __future__ import annotations

import copy
import json
from collections import Counter
from pathlib import Path

import pytest

from shengji.ai.registry import make_bot
from shengji.ai.throw_sourcing import (MAX_CANDIDATES,
                                       structured_throw_ballot)
from shengji.engine.cards import TRUMP
from shengji.engine.combos import decompose
from shengji.engine.legal import uniform_suit
from shengji.rl.replay_log import rebuild_round


FIXTURE = Path(__file__).with_name("data") / \
    "s6_kesp_throw_witnesses.v1.json"


def _fixture() -> dict:
    value = json.loads(FIXTURE.read_text())
    assert value["schema"] == "s6-kesp-throw-witnesses-v1"
    assert value["source"] == {
        "room": "KESP",
        "captured_log_sha256":
            "df946364ccd871b8ba902ff1b667ed534ecbb4de4c93f765a5179eb6774376a6",
    }
    return value


def _state_for(witness_id: str):
    for round_record in _fixture()["rounds"]:
        witness = next((item for item in round_record["witnesses"]
                        if item["id"] == witness_id), None)
        if witness is None:
            continue
        rnd = rebuild_round(round_record["events"])
        assert rnd is not None
        target = tuple(sorted(witness["human_action"]))
        target_seen = False
        for event in round_record["events"]:
            if event["e"] != "play" or rnd.phase != "play":
                continue
            if (event["seat"] == witness["seat"]
                    and tuple(sorted(event["cards"])) == target):
                target_seen = True
                break
            rnd.play(event["seat"], list(event["cards"]))
        assert target_seen, f"fixture never reached {witness_id}"
        assert rnd.turn == witness["seat"]
        assert rnd.trick is not None and not rnd.trick.plays
        return rnd, witness
    raise AssertionError(f"unknown witness {witness_id}")


@pytest.mark.parametrize("witness_id", [
    "KESP:r4:jerry:partial-near-boss",
    "KESP:r5:jerry:boss-bundle-under-ruff-risk",
    "KESP:r5:jerry:whole-suit-evacuation",
])
def test_kesp_live_omission_and_bounded_source_are_exact(witness_id):
    rnd, witness = _state_for(witness_id)
    seat = witness["seat"]
    target = tuple(sorted(witness["human_action"]))

    live = make_bot("mc-s0-report-lcb", seed=0)._candidates(rnd, seat)
    assert live == witness["expected_live_ballot"]
    assert target not in {tuple(sorted(action)) for action in live}

    structured = structured_throw_ballot(rnd, seat)
    by_action = {candidate.cards: candidate
                 for candidate in structured.candidates}
    assert target in by_action
    candidate = by_action[target]
    assert witness["expected_source"] in candidate.sources
    assert candidate.ruff_risk is witness["expected_ruff_risk"]

    # The logged submission itself was legal and stood as the full throw.  A
    # fixture that only pins an unreachable or failed substitute is not a
    # useful ballot witness.
    clone = copy.deepcopy(rnd)
    clone.play(seat, list(witness["human_action"]))
    assert clone.message is None
    assert tuple(sorted(clone.trick.plays[0].cards)) == target


def test_source_is_permutation_stable_and_hidden_information_independent():
    rnd, witness = _state_for(
        "KESP:r5:jerry:boss-bundle-under-ruff-risk")
    seat = witness["seat"]
    first = structured_throw_ballot(rnd, seat).record()

    permuted = copy.deepcopy(rnd)
    permuted.hands[seat] = list(reversed(permuted.hands[seat]))
    for other in range(4):
        if other != seat:
            permuted.hands[other] = ["BJ"] * len(permuted.hands[other])
    permuted.deck = list(reversed(permuted.deck))
    permuted.kitty = ["LJ"] * len(permuted.kitty)
    assert structured_throw_ballot(permuted, seat).record() == first


def test_source_is_finite_deduped_and_only_emits_real_plain_suit_throws():
    rnd, witness = _state_for("KESP:r4:jerry:partial-near-boss")
    seat = witness["seat"]
    hand = Counter(rnd.hands[seat])
    ballot = structured_throw_ballot(rnd, seat)

    assert 0 < len(ballot.candidates) == ballot.generated_unique \
        <= ballot.max_candidates == MAX_CANDIDATES == 8
    assert len({candidate.cards for candidate in ballot.candidates}) \
        == len(ballot.candidates)
    for candidate in ballot.candidates:
        assert not (Counter(candidate.cards) - hand)
        assert uniform_suit(list(candidate.cards), rnd.ordering) \
            == candidate.effective_suit != TRUMP
        assert len(decompose(list(candidate.cards), rnd.ordering).components) \
            == candidate.component_count >= 2


def test_follow_positions_do_not_trigger_lead_throw_source():
    rnd, witness = _state_for("KESP:r4:jerry:partial-near-boss")
    rnd.play(witness["seat"], list(witness["human_action"]))
    assert rnd.trick is not None and rnd.trick.plays
    assert structured_throw_ballot(rnd, rnd.turn).candidates == ()


def test_wrong_or_nonacting_seat_is_refused_before_reading_a_hand():
    rnd, witness = _state_for("KESP:r4:jerry:partial-near-boss")
    with pytest.raises(ValueError, match="acting seat"):
        structured_throw_ballot(rnd, (witness["seat"] + 1) % 4)
