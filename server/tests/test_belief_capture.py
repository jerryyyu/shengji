"""In-memory transcript ownership tests for BELIEF-V1 capture."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from shengji.ai.heuristic import HeuristicBot
from shengji.rl.belief_contract import CapturedPlayEvent, canonical_json_bytes
from shengji.rl import belief_capture as CAPTURE
from shengji.rl.belief_capture import (
    CHAMPION_POLICY,
    BeliefCaptureError,
    CapturedRoundArtifactsV1,
    capture_champion_round,
    captured_round_artifacts,
    reopen_captured_round_artifacts,
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


def test_capture_observer_is_target_blind_and_cannot_mutate_round(monkeypatch):
    calls = []

    def factory(_name, *, seed):
        del seed
        return HeuristicBot()

    def observer(_rnd, _seat, _transcript, pair):
        calls.append(pair.actor_file_sha256)

    monkeypatch.setattr(CAPTURE, "make_bot", factory)
    captured = capture_champion_round(
        9517, (101, 103, 107, 109), decision_observer=observer)
    assert calls == [pair.actor_file_sha256 for pair in captured.pairs]

    def mutate(rnd, _seat, _transcript, _pair):
        rnd.attacker_points += 1

    with pytest.raises(BeliefCaptureError, match="observer mutated"):
        capture_champion_round(
            9517, (101, 103, 107, 109), decision_observer=mutate)


def test_capture_artifacts_round_trip_with_public_privileged_separation(
        monkeypatch):
    captured = _fast_champion_capture(monkeypatch, seed=9521)
    artifacts = captured_round_artifacts(captured)
    reopened = reopen_captured_round_artifacts(artifacts)
    assert reopened.manifest_bytes() == captured.manifest_bytes()
    assert reopened.public_transcript == captured.public_transcript
    assert tuple(pair.actor_bytes for pair in reopened.pairs) \
        == artifacts.actor_rows
    assert tuple(pair.target_bytes for pair in reopened.pairs) \
        == artifacts.target_rows
    assert all(b'"target"' not in raw for raw in artifacts.actor_rows)
    assert all(b'"runtime_input":false' in raw
               for raw in artifacts.target_rows)


def test_capture_artifacts_refuse_noncanonical_and_manifest_drift(monkeypatch):
    artifacts = captured_round_artifacts(
        _fast_champion_capture(monkeypatch, seed=9523))
    duplicate = artifacts.manifest_bytes.replace(
        b"{", b'{"schema":"duplicate",', 1)
    with pytest.raises(BeliefCaptureError, match="duplicate key"):
        reopen_captured_round_artifacts(replace(
            artifacts, manifest_bytes=duplicate))
    with pytest.raises(BeliefCaptureError, match="canonical JSON"):
        reopen_captured_round_artifacts(replace(
            artifacts,
            transcript_bytes=artifacts.transcript_bytes[:-1] + b" \n"))

    manifest = json.loads(artifacts.manifest_bytes)
    manifest["winner"] = 0
    with pytest.raises(BeliefCaptureError, match="field population"):
        reopen_captured_round_artifacts(replace(
            artifacts, manifest_bytes=canonical_json_bytes(manifest)))
    manifest.pop("winner")
    manifest["actor_row_sha256s"][0] = "0" * 64
    with pytest.raises(BeliefCaptureError, match="manifest bytes drift"):
        reopen_captured_round_artifacts(replace(
            artifacts, manifest_bytes=canonical_json_bytes(manifest)))


def test_capture_artifacts_refuse_row_rebinding_and_type_drift(monkeypatch):
    artifacts = captured_round_artifacts(
        _fast_champion_capture(monkeypatch, seed=9533))
    with pytest.raises(BeliefCaptureError, match="corpus row refused"):
        reopen_captured_round_artifacts(replace(
            artifacts,
            target_rows=(artifacts.target_rows[1], artifacts.target_rows[0],
                         *artifacts.target_rows[2:]),
        ))
    changed = artifacts.target_rows[0].replace(
        b'"runtime_input":false', b'"runtime_input":true')
    with pytest.raises(BeliefCaptureError, match="corpus row refused"):
        reopen_captured_round_artifacts(replace(
            artifacts, target_rows=(changed, *artifacts.target_rows[1:])))
    with pytest.raises(BeliefCaptureError, match="population drift"):
        reopen_captured_round_artifacts(CapturedRoundArtifactsV1(
            manifest_bytes=artifacts.manifest_bytes,
            transcript_bytes=artifacts.transcript_bytes,
            actor_rows=list(artifacts.actor_rows),
            target_rows=artifacts.target_rows,
        ))
