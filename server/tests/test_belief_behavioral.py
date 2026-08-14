"""Public behavioral-signal and separated-audit tests for BELIEF-V1."""

from __future__ import annotations

from collections import Counter
from dataclasses import replace

import pytest

from shengji.ai.heuristic import HeuristicBot
from shengji.engine.cards import LJ, Ordering, TRUMP, is_joker
from shengji.rl.belief_b2_protocol import (
    b2_round_seeds,
    champion_policy_seeds,
)
from shengji.rl.belief_behavioral import (
    DECLINED_POINT_FEED,
    FORCED_SINGLE_JOKER,
    UNFORCED_POINT_PLAY,
    BeliefBehavioralError,
    _classify_choice_signals,
    behavioral_signal_exposures,
    build_behavioral_signal_round,
    validate_behavioral_signal_round,
)
from shengji.rl.belief_capture import _capture_with_policies
from shengji.rl.belief_contract import (
    CapturedPlayEvent,
    PlayView,
    TrickView,
)
from shengji.rl.belief_corpus import reopen_actor_row


def _round(offset=0):
    seed = b2_round_seeds()[offset]
    return _capture_with_policies(
        seed, "mc-s0-report-lcb", champion_policy_seeds(seed),
        [HeuristicBot() for _ in range(4)])


def test_public_signal_and_private_alternative_audit_are_separate():
    captured = _round()
    result = build_behavioral_signal_round(captured)
    validate_behavioral_signal_round(captured, result)
    assert result.public_signals
    kinds = {row.signal_kind for row in result.public_signals}
    assert {DECLINED_POINT_FEED, UNFORCED_POINT_PLAY} <= kinds
    assert any(row.signal_kind == UNFORCED_POINT_PLAY
               and audit.alternative_available is True
               for row, audit in zip(
                   result.public_signals, result.privileged_audits,
                   strict=True))
    public = result.public_bytes()
    privileged = result.privileged_bytes()
    assert b'"eligible_point_card_count"' not in public
    assert b'"preplay_trump_count"' not in public
    assert b'"source_actor_observation_sha256"' not in public
    assert b'"eligible_point_card_count"' in privileged
    assert b'"runtime_input":false' in privileged
    assert all(row.information_tag == "probabilistic_policy_conditioned"
               for row in result.public_signals)


def test_declined_feed_public_pattern_does_not_claim_private_alternative():
    captured = _round(2)
    result = build_behavioral_signal_round(captured)
    confirmed = [
        (signal, audit) for signal, audit in zip(
            result.public_signals, result.privileged_audits, strict=True)
        if signal.signal_kind == DECLINED_POINT_FEED
        and audit.alternative_available is True
    ]
    assert confirmed
    signal, audit = confirmed[0]
    assert signal.to_dict()["logical_fact_claimed"] is False
    assert audit.eligible_point_card_count > 0
    assert audit.source_actor_observation_sha256.encode() not in (
        result.public_bytes())


def test_trump_pair_single_joker_branch_reports_length_only_in_audit():
    captured = _round()
    pair = captured.pairs[0]
    actor, metadata = reopen_actor_row(pair.actor_bytes)
    ordering = Ordering(actor.trump_suit, actor.trump_rank)
    nonjoker_trump = next(
        card for card, _ in actor.deductions.unseen
        if not is_joker(card) and ordering.eff_suit(card) == TRUMP)
    lead_pair = next(
        card for card, _ in actor.deductions.unseen
        if ordering.eff_suit(card) == TRUMP and not is_joker(card))
    forged_hand = Counter(dict(actor.actor_hand))
    forged_hand[LJ] += 1
    forged_hand[nonjoker_trump] += 1
    forged = replace(
        actor, actor_hand=tuple(sorted(forged_hand.items())),
        current_trick=TrickView(
            leader_relative=3,
            plays=(PlayView(
                seat_relative=3,
                failed_throw=False,
                attempted_cards=(lead_pair, lead_pair),
                cards=(lead_pair, lead_pair)),),
            winner_relative=None, points=0))
    event = CapturedPlayEvent(
        seat=metadata["actor_seat"],
        attempted_cards=(LJ, nonjoker_trump),
        actual_cards=(LJ, nonjoker_trump))
    classified = _classify_choice_signals(forged, metadata, event)
    signal, audit = next(
        row for row in classified if row[0].signal_kind == FORCED_SINGLE_JOKER)
    assert signal.to_dict()["contains_actor_hand"] is False
    assert audit.alternative_available is None
    assert audit.preplay_trump_count >= 2
    assert audit.preplay_trump_pair_type_count >= 0
    assert b'"preplay_trump_count"' not in signal.canonical_bytes()


def test_signal_round_refuses_public_or_private_rehash_drift():
    captured = _round()
    result = build_behavioral_signal_round(captured)
    changed_public = replace(
        result.public_signals[0], public_context_sha256="0" * 64)
    with pytest.raises(BeliefBehavioralError, match="derivation drift"):
        validate_behavioral_signal_round(captured, replace(
            result, public_signals=(changed_public,
                                    *result.public_signals[1:])))
    changed_audit = replace(
        result.privileged_audits[0], alternative_available=None)
    with pytest.raises(BeliefBehavioralError, match="derivation drift"):
        validate_behavioral_signal_round(captured, replace(
            result, privileged_audits=(changed_audit,
                                       *result.privileged_audits[1:])))


def test_signal_exposure_is_natural_next_orbit_and_evaluator_only():
    captured = _round()
    result = build_behavioral_signal_round(captured)
    exposures = behavioral_signal_exposures(captured, result)
    assert exposures
    by_signal = {}
    for row in exposures:
        by_signal.setdefault(row.source_signal_sha256, []).append(row)
        payload = row.to_dict()
        assert payload["privileged_evaluation_artifact"] is True
        assert payload["runtime_input"] is False
        assert row.receiver in {
            "seat-relative-1", "seat-relative-2", "seat-relative-3"}
    for signal in result.public_signals:
        rows = by_signal.get(signal.sha256(), [])
        next_source_action = next((
            index for index, event in enumerate(
                captured.public_transcript.plays[signal.decision_index + 1:],
                start=signal.decision_index + 1)
            if event.seat == signal.acting_seat), len(captured.pairs))
        assert all(signal.decision_index < row.decision_index
                   < next_source_action for row in rows)
        assert all(row.source_acting_seat == signal.acting_seat
                   for row in rows)
