"""Witnesses for transcript replay of sealed actor rounds.

Replay must reproduce capture's decision states byte-for-byte WITHOUT
invoking any play search, refuse loudly on any divergence from the sealed
evidence, and remain target-blind.  Every refusal branch has a test that
makes it fire, so no witness here can silently pass.
"""
from __future__ import annotations

import hashlib
import os
from collections import Counter
from dataclasses import replace

import pytest

from shengji.ai.heuristic import HeuristicBot
from shengji.ai.registry import make_bot
from shengji.ai.smart import SmartBot
from shengji.engine.legal import suit_cards, validate_lead
from shengji.rl import belief_contract as CONTRACT
from shengji.rl import belief_corpus as CORPUS
from shengji.rl.belief_b2_protocol import (
    b2_round_seeds,
    champion_policy_seeds,
)
from shengji.rl.belief_capture import (
    CHAMPION_POLICY,
    _capture_with_policies,
    capture_champion_actor_round,
)
from shengji.rl.belief_refc_replay import BeliefReplayError, replay_actor_round


class _NoSearchHeuristic(HeuristicBot):
    """Capture-identical declare/bury policy whose play search is forbidden."""

    def decide_play(self, rnd, seat):
        raise AssertionError("replay must never invoke play search")


class _NoDeclareFailedThrowBot(HeuristicBot):
    """Deterministically exercise the engine's failed-throw resolution."""

    def decide_declare(self, rnd, seat, final=False):
        return None

    def decide_play(self, rnd, seat):
        if not rnd.trick.plays:
            hand = rnd.hands[seat]
            for suit in "SHDC":
                suited = suit_cards(hand, suit, rnd.ordering)
                counts = Counter(suited)
                pair = next((card for card, count in counts.items()
                             if count >= 2), None)
                single = next((card for card in suited if card != pair), None)
                if pair is None or single is None:
                    continue
                attempted = [pair, pair, single]
                actual, message = validate_lead(
                    attempted, hand,
                    [rnd.hands[index] for index in range(4)
                     if index != seat],
                    rnd.ordering)
                if message is not None and len(actual) < len(attempted):
                    return attempted
        return super().decide_play(rnd, seat)


class _NoDeclareNoSearch(HeuristicBot):
    """Replay-side twin: preserve setup but make play search impossible."""

    def decide_declare(self, rnd, seat, final=False):
        return None

    def decide_play(self, rnd, seat):
        raise AssertionError("replay must never invoke play search")


def _capture(seed, policies):
    return _capture_with_policies(
        seed, CHAMPION_POLICY, champion_policy_seeds(seed), policies,
        actor_only=True)


def _replay(seed, sealed, *, policies=None, decision_observer=None,
            policy_name=CHAMPION_POLICY, policy_seeds=None):
    return replay_actor_round(
        round_seed=seed, policy_name=policy_name,
        policy_seeds=policy_seeds or champion_policy_seeds(seed),
        policies=policies or [_NoSearchHeuristic() for _ in range(4)],
        sealed=sealed, decision_observer=decision_observer)


@pytest.fixture(scope="module")
def sealed_round():
    seed = b2_round_seeds()[0]
    return seed, _capture(seed, [HeuristicBot() for _ in range(4)])


@pytest.fixture(scope="module")
def divergent_pair():
    """Same round seed captured under two policies whose declarations differ.

    The differing declarations make every actor row differ from decision 0
    while each capture stays internally valid, which is exactly the shape a
    spliced or wrong-policy replay must refuse.
    """
    for seed in b2_round_seeds()[:8]:
        a = _capture(seed, [HeuristicBot() for _ in range(4)])
        b = _capture(seed, [SmartBot() for _ in range(4)])
        if a.public_transcript.declarations != b.public_transcript.declarations:
            assert a.actor_rows[0] != b.actor_rows[0]
            return seed, a, b
    raise AssertionError(
        "no B2 seed in the first 8 separates HeuristicBot and SmartBot "
        "declarations; widen the search")


def test_replay_reproduces_sealed_round_without_play_search(sealed_round):
    seed, sealed = sealed_round
    seen = []

    def observer(rnd, seat, transcript, actor_row):
        assert rnd.phase == "play" and rnd.turn == seat
        seen.append((seat, len(transcript.plays),
                     hashlib.sha256(actor_row).hexdigest()))

    result = _replay(seed, sealed, decision_observer=observer)

    assert result == sealed
    assert result.actor_rows == sealed.actor_rows
    assert result.public_transcript == sealed.public_transcript
    expected = [
        (event.seat, index, hashlib.sha256(row).hexdigest())
        for index, (event, row) in enumerate(
            zip(sealed.public_transcript.plays, sealed.actor_rows,
                strict=True))]
    assert seen == expected


def test_replay_reproduces_genuine_failed_throw_without_play_search():
    seed = b2_round_seeds()[0]
    sealed = _capture(
        seed, [_NoDeclareFailedThrowBot() for _ in range(4)])
    failed = [
        event for event in sealed.public_transcript.plays
        if event.attempted_cards != event.actual_cards
    ]
    assert failed, "fixture must execute an engine-resolved failed throw"
    assert all(Counter(event.actual_cards) <= Counter(event.attempted_cards)
               and len(event.actual_cards) < len(event.attempted_cards)
               for event in failed)

    result = _replay(
        seed, sealed,
        policies=[_NoDeclareNoSearch() for _ in range(4)])

    assert result == sealed
    assert any(event.attempted_cards != event.actual_cards
               for event in result.public_transcript.plays)


@pytest.mark.skipif(
    os.environ.get("SHENGJI_FAST") != "1",
    reason="exact champion replay witness is pinned to production fast mode",
)
def test_replay_reproduces_one_exact_champion_round():
    seed = b2_round_seeds()[0]
    policy_seeds = champion_policy_seeds(seed)
    sealed = capture_champion_actor_round(seed, policy_seeds)
    policies = [make_bot(CHAMPION_POLICY, seed=policy_seed)
                for policy_seed in policy_seeds]

    result = replay_actor_round(
        round_seed=seed, policy_name=CHAMPION_POLICY,
        policy_seeds=policy_seeds, policies=policies, sealed=sealed)

    assert result == sealed
    assert result.actor_rows == sealed.actor_rows


def test_replay_refuses_identity_mismatch(sealed_round):
    seed, sealed = sealed_round
    seeds = champion_policy_seeds(seed)
    for overrides in (
            {"seed": seed + 1},
            {"policy_name": CHAMPION_POLICY + "-drift"},
            {"policy_seeds": (seeds[0] + 1, *seeds[1:])},
    ):
        with pytest.raises(BeliefReplayError, match="identity does not match"):
            _replay(overrides.get("seed", seed), sealed,
                    policy_name=overrides.get(
                        "policy_name", CHAMPION_POLICY),
                    policy_seeds=overrides.get("policy_seeds", seeds))


def test_replay_refuses_spliced_sealed_row(divergent_pair):
    seed, a, b = divergent_pair
    spliced = replace(a, actor_rows=(b.actor_rows[0], *a.actor_rows[1:]))
    with pytest.raises(BeliefReplayError, match="sealed actor row 0"):
        _replay(seed, spliced)


def test_replay_refuses_divergent_replay_policies(divergent_pair):
    seed, a, _b = divergent_pair
    with pytest.raises(BeliefReplayError, match="declarations diverge"):
        _replay(seed, a, policies=[SmartBot() for _ in range(4)])


def test_replay_refuses_tampered_play_resolution(sealed_round):
    seed, sealed = sealed_round
    plays = sealed.public_transcript.plays
    index = next(
        i for i, event in enumerate(plays)
        if len(event.attempted_cards) >= 2
        and event.actual_cards == event.attempted_cards)
    tampered_event = replace(
        plays[index], actual_cards=plays[index].actual_cards[:1])
    tampered = replace(sealed, public_transcript=replace(
        sealed.public_transcript,
        plays=(*plays[:index], tampered_event, *plays[index + 1:])))
    with pytest.raises(
            BeliefReplayError,
            match=f"resolution diverges from transcript at decision {index}"):
        _replay(seed, tampered)


def test_replay_refuses_observer_mutating_observable_state(sealed_round):
    seed, sealed = sealed_round

    def vandal(rnd, seat, transcript, actor_row):
        rnd.hands[seat].pop()

    with pytest.raises(BeliefReplayError, match="observer mutated round"):
        _replay(seed, sealed, decision_observer=vandal)


def test_replay_refuses_observer_mutating_hidden_state(sealed_round):
    """A hidden-hand mutation is invisible to the target-blind observation at
    the decision itself, so the same-decision guard cannot see it — but the
    corruption must still surface as a replay refusal, never an unwrapped
    crash or a silently wrong round."""
    seed, sealed = sealed_round

    def vandal(rnd, seat, transcript, actor_row):
        victim = next(s for s in range(4) if s != seat and rnd.hands[s])
        rnd.hands[victim].pop()

    with pytest.raises(BeliefReplayError,
                       match="diverges|recaptured|mutated"):
        _replay(seed, sealed, decision_observer=vandal)


def test_replay_constructs_no_privileged_targets(sealed_round, monkeypatch):
    seed, sealed = sealed_round

    def forbid(*_args, **_kwargs):
        raise AssertionError(
            "replay must never construct a privileged target")

    monkeypatch.setattr(CONTRACT, "build_belief_targets", forbid)
    monkeypatch.setattr(CONTRACT, "build_information_partition", forbid)
    monkeypatch.setattr(CONTRACT.BeliefTargetsV1, "__init__", forbid)
    monkeypatch.setattr(CORPUS, "capture_corpus_pair", forbid)

    observed = []
    result = _replay(seed, sealed,
                     decision_observer=lambda *args: observed.append(1))
    assert result == sealed
    assert len(observed) == len(sealed.actor_rows)
