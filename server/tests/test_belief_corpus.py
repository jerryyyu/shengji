"""B1 split and privileged-separation tests for BELIEF-V1 corpus rows."""

from __future__ import annotations

import hashlib
import json
import random

import pytest

from shengji.ai.smart import SmartBot
from shengji.engine.game import Game
from shengji.engine.round import actual_play_after
from shengji.rl.belief_contract import PublicTranscriptV1, canonical_json_bytes
from shengji.rl.belief_corpus import (
    ACTOR_ROW_SCHEMA,
    MAX_DECISIONS_PER_ROUND,
    MAX_ROUND_SEED,
    SPLITS,
    SPLIT_SCHEMA,
    TARGET_ROW_SCHEMA,
    BeliefCorpusError,
    capture_corpus_pair,
    decision_key,
    split_for_round_seed,
    validate_corpus_pair,
)


def _play_state(seed: int = 9201):
    game = Game(random.Random(seed))
    rnd = game.start_round()
    while rnd.phase == "deal":
        rnd.deal_next()
    bot = SmartBot()
    transcript = PublicTranscriptV1()
    for seat in range(4):
        declaration = bot.decide_declare(rnd, seat, final=True)
        if declaration:
            rnd.declare(seat, declaration)
            accepted = rnd.declaration
            transcript = transcript.with_declaration(
                accepted["seat"], accepted["cards"], accepted["strength"])
    rnd.finalize_declare()
    rnd.bury(rnd.banker, bot.decide_bury(rnd, rnd.banker))
    return rnd, bot, transcript


def _play_and_record(rnd, bot, transcript):
    seat = rnd.turn
    attempted = bot.decide_play(rnd, seat)
    previous_last = rnd.last_trick
    rnd.play(seat, attempted)
    return transcript.with_play(
        seat, attempted, actual_play_after(rnd, seat, previous_last))


def _rewrite(record: dict, **changes) -> bytes:
    changed = dict(record)
    changed.update(changes)
    changed.pop("artifact_sha256", None)
    import hashlib
    changed["artifact_sha256"] = hashlib.sha256(
        canonical_json_bytes(changed)).hexdigest()
    return canonical_json_bytes(changed)


def test_split_is_round_bound_deterministic_and_populates_all_folds():
    seen = {split_for_round_seed(seed) for seed in range(1000)}
    assert seen == set(SPLITS)
    for seed in range(100):
        split = split_for_round_seed(seed)
        assert split == split_for_round_seed(seed)
        assert split in SPLITS
    assert SPLIT_SCHEMA == "belief-v1-round-seed-sha256-80-10-10-v1"


@pytest.mark.parametrize("value", [-1, MAX_ROUND_SEED + 1, True, 1.0, "1"])
def test_split_and_key_refuse_noncanonical_identifiers(value):
    with pytest.raises(BeliefCorpusError, match="round seed"):
        split_for_round_seed(value)
    with pytest.raises(BeliefCorpusError):
        decision_key(value, 0, 0)


@pytest.mark.parametrize("value", [-1, MAX_DECISIONS_PER_ROUND, True, 1.0,
                                   "1"])
def test_key_refuses_out_of_range_decision_indices(value):
    with pytest.raises(BeliefCorpusError, match="decision index"):
        decision_key(1, value, 0)


def test_training_capture_requires_complete_external_transcript():
    rnd, _, transcript = _play_state(9202)
    with pytest.raises(BeliefCorpusError, match="information partition"):
        capture_corpus_pair(
            rnd, rnd.turn, round_seed=9202, decision_index=0,
            transcript=PublicTranscriptV1())
    pair = capture_corpus_pair(
        rnd, rnd.turn, round_seed=9202, decision_index=0,
        transcript=transcript)
    actor, _ = validate_corpus_pair(pair.actor_bytes, pair.target_bytes)
    assert actor["actor"]["declaration_history_complete"] is True
    assert actor["actor"]["attempted_play_history_complete"] is True


def test_capture_separates_actor_and_privileged_payloads():
    rnd, _, transcript = _play_state()
    pair = capture_corpus_pair(
        rnd, rnd.turn, round_seed=9201, decision_index=0,
        transcript=transcript)
    actor, target = validate_corpus_pair(pair.actor_bytes, pair.target_bytes)
    assert actor["schema"] == ACTOR_ROW_SCHEMA
    assert target["schema"] == TARGET_ROW_SCHEMA
    assert actor["contains_privileged_targets"] is False
    assert target["runtime_input"] is False
    assert "target" not in actor and "other_hands" not in actor["actor"]
    assert target["target"]["other_hands"]
    assert target["actor_file_sha256"] == pair.actor_file_sha256
    assert len(pair.target_file_sha256) == 64


def test_all_decisions_from_one_round_stay_in_one_split():
    rnd, bot, transcript = _play_state(9203)
    splits = set()
    decision_index = 0
    while rnd.phase == "play":
        pair = capture_corpus_pair(
            rnd, rnd.turn, round_seed=9203,
            decision_index=decision_index, transcript=transcript)
        actor, target = validate_corpus_pair(
            pair.actor_bytes, pair.target_bytes)
        splits.add(actor["split"])
        assert actor["split"] == target["split"]
        transcript = _play_and_record(rnd, bot, transcript)
        decision_index += 1
    assert splits == {split_for_round_seed(9203)}
    assert decision_index >= 70


def test_target_from_another_decision_cannot_be_repaired_by_self_rehash():
    rnd, bot, transcript = _play_state(9205)
    first = capture_corpus_pair(
        rnd, rnd.turn, round_seed=9205, decision_index=0,
        transcript=transcript)
    transcript = _play_and_record(rnd, bot, transcript)
    second = capture_corpus_pair(
        rnd, rnd.turn, round_seed=9205, decision_index=1,
        transcript=transcript)
    with pytest.raises(BeliefCorpusError, match="metadata mismatch"):
        validate_corpus_pair(first.actor_bytes, second.target_bytes)


def test_rehashed_split_authority_and_payload_mutations_refuse():
    rnd, _, transcript = _play_state(9207)
    pair = capture_corpus_pair(
        rnd, rnd.turn, round_seed=9207, decision_index=0,
        transcript=transcript)
    actor = json.loads(pair.actor_bytes)
    target = json.loads(pair.target_bytes)

    wrong_split = next(split for split in SPLITS if split != actor["split"])
    with pytest.raises(BeliefCorpusError, match="frozen split"):
        validate_corpus_pair(_rewrite(actor, split=wrong_split),
                             pair.target_bytes)
    changed_actor = _rewrite(actor, contains_privileged_targets=True)
    changed_target = _rewrite(
        target,
        actor_file_sha256=hashlib.sha256(changed_actor).hexdigest(),
    )
    with pytest.raises(BeliefCorpusError, match="authority boundary"):
        validate_corpus_pair(changed_actor, changed_target)
    with pytest.raises(BeliefCorpusError, match="authority boundary"):
        validate_corpus_pair(pair.actor_bytes,
                             _rewrite(target, runtime_input=True))

    actor_payload = dict(actor["actor"])
    actor_payload["schema"] = "forged-actor-schema"
    actor_schema_drift = _rewrite(
        actor, actor=actor_payload,
        actor_sha256=hashlib.sha256(
            canonical_json_bytes(actor_payload)).hexdigest())
    rebound_target = _rewrite(
        target,
        actor_file_sha256=hashlib.sha256(actor_schema_drift).hexdigest(),
        actor_sha256=json.loads(actor_schema_drift)["actor_sha256"],
    )
    with pytest.raises(BeliefCorpusError, match="internal schema"):
        validate_corpus_pair(actor_schema_drift, rebound_target)

    target_payload = dict(target["target"])
    target_payload["schema"] = "forged-target-schema"
    target_schema_drift = _rewrite(
        target, target=target_payload,
        target_sha256=hashlib.sha256(
            canonical_json_bytes(target_payload)).hexdigest())
    with pytest.raises(BeliefCorpusError, match="internal schema"):
        validate_corpus_pair(pair.actor_bytes, target_schema_drift)

    actor_payload = dict(actor["actor"])
    actor_payload["declaration_history_complete"] = False
    incomplete_actor = _rewrite(
        actor, actor=actor_payload,
        actor_sha256=hashlib.sha256(
            canonical_json_bytes(actor_payload)).hexdigest())
    rebound_target = _rewrite(
        target,
        actor_file_sha256=hashlib.sha256(incomplete_actor).hexdigest(),
        actor_sha256=json.loads(incomplete_actor)["actor_sha256"],
    )
    with pytest.raises(BeliefCorpusError, match="incomplete public history"):
        validate_corpus_pair(incomplete_actor, rebound_target)

    changed_target = _rewrite(target, actor_sha256="0" * 64,
                              partition_sha256="1" * 64)
    with pytest.raises(BeliefCorpusError, match="actor payload binding"):
        validate_corpus_pair(pair.actor_bytes, changed_target)


def test_noncanonical_duplicate_trailing_and_nonfinite_json_refuse():
    rnd, _, transcript = _play_state(9209)
    pair = capture_corpus_pair(
        rnd, rnd.turn, round_seed=9209, decision_index=0,
        transcript=transcript)
    duplicate = pair.actor_bytes.replace(
        b'{', b'{"schema":"duplicate",', 1)
    with pytest.raises(BeliefCorpusError, match="duplicate JSON key"):
        validate_corpus_pair(duplicate, pair.target_bytes)
    with pytest.raises(BeliefCorpusError, match="canonical JSON"):
        validate_corpus_pair(pair.actor_bytes[:-1] + b" \n",
                             pair.target_bytes)
    nonfinite = pair.actor_bytes.replace(b'"actor_seat":',
                                         b'"foreign":NaN,"actor_seat":', 1)
    with pytest.raises(BeliefCorpusError, match="non-finite"):
        validate_corpus_pair(nonfinite, pair.target_bytes)
