"""In-memory transcript ownership tests for BELIEF-V1 capture."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from shengji.ai.heuristic import HeuristicBot
from shengji.rl.belief_contract import CapturedPlayEvent
from shengji.rl import belief_capture as CAPTURE
from shengji.rl.belief_capture import (
    CHAMPION_POLICY,
    BeliefCaptureError,
    capture_champion_round,
    validate_captured_round,
)
from shengji.rl.belief_corpus import validate_corpus_pair


def _fast_champion_capture(monkeypatch, *, seed=9502):
    calls = []

    def factory(name, *, seed):
        calls.append((name, seed))
        return HeuristicBot()

    monkeypatch.setattr(CAPTURE, "make_bot", factory)
    policy_seeds = (101, 103, 107, 109)
    captured = capture_champion_round(seed, policy_seeds)
    assert calls == [(CHAMPION_POLICY, value) for value in policy_seeds]
    return captured


def test_full_round_capture_owns_complete_ordered_transcript(monkeypatch):
    captured = _fast_champion_capture(monkeypatch)
    validate_captured_round(captured)
    assert 70 <= len(captured.pairs) <= 100
    assert len(captured.public_transcript.declarations) >= 1
    assert len(captured.manifest_sha256()) == 64
    manifest = json.loads(captured.manifest_bytes())
    assert manifest["policy_name"] == CHAMPION_POLICY
    assert manifest["decision_count"] == len(captured.pairs)
    assert manifest["public_play_count"] == len(captured.pairs)
    assert manifest["contains_round_outcome"] is False
    assert manifest["privileged_rows_are_runtime_inputs"] is False
    assert not ({"winner", "attacker_points", "level_change"} & set(manifest))

    declaration_lengths = []
    play_lengths = []
    for index, pair in enumerate(captured.pairs):
        actor, target = validate_corpus_pair(
            pair.actor_bytes, pair.target_bytes)
        assert actor["decision_index"] == target["decision_index"] == index
        assert actor["round_seed"] == target["round_seed"] == 9502
        declaration_lengths.append(len(actor["actor"]["declaration_history"]))
        play_count = sum(len(trick["plays"])
                         for trick in actor["actor"]["completed_tricks"])
        play_count += len(actor["actor"]["current_trick"]["plays"])
        play_lengths.append(play_count)
        assert actor["actor"]["declaration_history_complete"] is True
        assert actor["actor"]["attempted_play_history_complete"] is True
        assert "target" not in actor
    assert declaration_lengths == sorted(declaration_lengths)
    assert play_lengths == list(range(len(captured.pairs)))


@pytest.mark.parametrize("seeds", [
    (1, 2, 3),
    (1, 2, 3, 3),
    (1, 2, 3, True),
    (1, 2, 3, -1),
    [1, 2, 3, 4],
])
def test_capture_refuses_noncanonical_policy_seed_population(seeds):
    with pytest.raises(BeliefCaptureError, match="four distinct exact"):
        capture_champion_round(9502, seeds)


def test_capture_manifest_and_row_sequence_are_bound(monkeypatch):
    captured = _fast_champion_capture(monkeypatch, seed=9511)
    with pytest.raises(BeliefCaptureError, match="exact champion"):
        validate_captured_round(replace(captured, policy_name="heuristic"))
    with pytest.raises(BeliefCaptureError, match="row sequence"):
        validate_captured_round(replace(
            captured,
            pairs=(captured.pairs[1], captured.pairs[0],
                   *captured.pairs[2:]),
        ))
    with pytest.raises(BeliefCaptureError, match="decision count"):
        validate_captured_round(replace(captured, public_transcript=replace(
            captured.public_transcript,
            plays=captured.public_transcript.plays[:-1])))

    first = captured.public_transcript.plays[0]
    changed_card = next(card for card in ("C2", "D2", "H2")
                        if (card,) != first.actual_cards)
    changed_event = CapturedPlayEvent(
        seat=first.seat,
        attempted_cards=(changed_card,),
        actual_cards=(changed_card,),
    )
    with pytest.raises(BeliefCaptureError, match="play prefix"):
        validate_captured_round(replace(captured, public_transcript=replace(
            captured.public_transcript,
            plays=(changed_event, *captured.public_transcript.plays[1:]))))
