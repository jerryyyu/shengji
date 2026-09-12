"""Bury's actual rollout consumer must preserve every play, not just score."""
import copy

import pytest

from shengji.ai.heuristic import HeuristicBot
from shengji.ai.mcbot import MCBot
from shengji.engine import round as round_module
from shengji.train.cwv_bury_policy import CWVBuryConfig, make_cwv_bury_bot
from shengji.train import cwv_bury
from tests.test_cwv_bury_policy import _bury_state, _Evaluator
from tests.test_world_shortlist import round_signature


class ReferenceHeuristic(HeuristicBot):
    """Same decisions, deliberately not eligible for the exact-type fast path."""


@pytest.mark.parametrize("seed", [4, 7, 13, 19, 31, 52])
def test_bury_rollout_matches_validated_plays_and_kitty_score(seed, monkeypatch):
    rnd = _bury_state(seed)
    seat = rnd.banker
    sampled = {s: list(rnd.hands[s]) for s in range(4) if s != seat}
    candidates = [HeuristicBot().decide_bury(rnd, seat), rnd.hands[seat][:8]]
    before = round_signature(rnd)
    original_play = round_module.Round.play
    original_follow = round_module.validate_follow
    original_lead = round_module.validate_lead
    trace, counts = [], {"follow": 0, "lead": 0}

    def follow(*args, **kwargs):
        counts["follow"] += 1
        return original_follow(*args, **kwargs)

    def lead(*args, **kwargs):
        counts["lead"] += 1
        return original_lead(*args, **kwargs)

    def play(state, actor, cards):
        original_play(state, actor, cards)
        trick = state.trick if state.trick and state.trick.plays else state.last_trick
        trace.append((actor, tuple(cards), tuple(trick.plays[-1].cards),
                      state.attacker_points, state.turn, state.phase,
                      None if state.last_trick is None else state.last_trick.winner))

    monkeypatch.setattr(round_module, "validate_follow", follow)
    monkeypatch.setattr(round_module, "validate_lead", lead)
    monkeypatch.setattr(round_module.Round, "play", play)
    for candidate in candidates:
        results = []
        for policy in (ReferenceHeuristic(), HeuristicBot()):
            bot = MCBot(seed=123)
            bot.rollout_policy = policy
            rng = bot.rng.getstate()
            trace.clear()
            counts.update(follow=0, lead=0)
            value = bot._rollout_from_bury(rnd, seat, sampled, candidate)
            results.append((value, list(trace), dict(counts)))
            assert bot.rng.getstate() == rng
            assert round_signature(rnd) == before
            assert not getattr(rnd, "_trusted_rollout", False)
        reference, fast = results
        assert fast[:2] == reference[:2]
        assert reference[2]["follow"] > 0
        assert fast[2]["follow"] == 0
        assert fast[2]["lead"] == reference[2]["lead"] > 0


def test_hybrid_bury_wires_fast_rollout_without_changing_evidence(monkeypatch):
    rnd = _bury_state(7)
    config = CWVBuryConfig(max_candidates=8, model_worlds=2,
                           selection_worlds=2, alternatives=2)
    original = MCBot._rollout_from_bury
    seen = []

    def reference(self, *args, **kwargs):
        self.rollout_policy = ReferenceHeuristic()
        return original(self, *args, **kwargs)

    with monkeypatch.context() as m:
        m.setattr(MCBot, "_rollout_from_bury", reference)
        old = make_cwv_bury_bot(_Evaluator(), seed=123, arm="hybrid", bury_config=config)
        old_choice = old.decide_bury(copy.deepcopy(rnd), rnd.banker)

    real_play = round_module.Round.play

    def observe(state, *args, **kwargs):
        seen.append(bool(getattr(state, "_trusted_rollout", False)))
        return real_play(state, *args, **kwargs)

    monkeypatch.setattr(round_module.Round, "play", observe)
    new = make_cwv_bury_bot(_Evaluator(), seed=123, arm="hybrid", bury_config=config)
    assert new.decide_bury(copy.deepcopy(rnd), rnd.banker) == old_choice
    assert any(seen)
    assert new.rng.getstate() == old.rng.getstate()
    for key in ("candidates", "shortlist", "picked_index", "model_means",
                "mc_evidence", "world_counts", "counters"):
        assert new.last_bury_record[key] == old.last_bury_record[key]


def test_batched_ranking_validates_each_world_once_and_never_shares_hands(monkeypatch):
    rnd = _bury_state(7)
    worlds = [(copy.deepcopy(rnd.hands), []) for _ in range(2)]
    candidates = cwv_bury.bury_candidates(rnd, MCBot(seed=123))[:3]
    expected = []
    for hands, _ in worlds:
        for candidate in candidates:
            state = cwv_bury.post_bury_world(rnd, hands, candidate)
            for _ in range(4):
                state.play(state.turn, HeuristicBot().decide_play(state, state.turn))
            expected.append(round_signature(state))
    calls = []
    validate = cwv_bury._validated_world_hands

    def counted(*args):
        calls.append(1)
        return validate(*args)

    class MutatingRecorder:
        max_batch = 1

        def __init__(self):
            self.seen = []

        def score(self, positions, seat):
            self.seen.extend(round_signature(state) for state in positions)
            # A previous evaluator batch must not poison the canonical world
            # or a subsequent candidate through shared mutable hand lists.
            for state in positions:
                for hand in state.hands:
                    hand.clear()
            return [0.0] * len(positions)

    before = copy.deepcopy(worlds), round_signature(rnd)
    monkeypatch.setattr(cwv_bury, "_validated_world_hands", counted)
    evaluator = MutatingRecorder()
    result = cwv_bury.score_bury_candidates(
        rnd, candidates, worlds, evaluator, first_trick_policy=HeuristicBot())
    assert result.shape == (2, 3)
    assert evaluator.seen == expected
    assert len(calls) == len(worlds)
    assert (worlds, round_signature(rnd)) == before


def test_batched_ranking_still_refuses_invalid_later_world():
    rnd = _bury_state(7)
    good = copy.deepcopy(rnd.hands)
    bad = copy.deepcopy(good)
    bad[(rnd.banker + 1) % 4].pop()
    candidates = [HeuristicBot().decide_bury(rnd, rnd.banker)]
    with pytest.raises(cwv_bury.BuryValueError, match="invalid complete bury world"):
        cwv_bury.score_bury_candidates(rnd, candidates, [(good, []), (bad, [])], _Evaluator())
