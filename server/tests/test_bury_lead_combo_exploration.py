"""Cheap contracts for the reusable bury/first-lead DEV scorer."""
from __future__ import annotations

import random
import sys
from collections import Counter
from pathlib import Path
from types import MethodType

import pytest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import bury_lead_combo_exploration as E  # noqa: E402

from shengji.ai.registry import make_bot  # noqa: E402
from shengji.engine.game import Game  # noqa: E402


def _bury_round(seed: int = 0):
    rnd = Game(random.Random(seed)).start_round()
    while rnd.phase == "deal":
        rnd.deal_next()
    rnd.finalize_declare()
    assert rnd.phase == "bury" and rnd.banker is not None
    return rnd, rnd.banker


def _bot_and_incumbent(rnd, seat):
    bot = make_bot("mc-s0-report-lcb", seed=17)
    return bot, bot.decide_bury(rnd, seat)


def _install_sampler(bot, results):
    queue = list(results)

    def sample(self, _rnd, _seat, _memory):
        self.sample_attempts += 1
        result = queue.pop(0) if queue else None
        if result is None:
            self.failed_worlds += 1
            return None
        self.accepted_worlds += 1
        return result, []

    bot._sample_hands = MethodType(sample, bot)


def test_scorer_uses_exact_common_world_work_and_descriptive_winner(monkeypatch):
    rnd, seat = _bury_round()
    bot, incumbent = _bot_and_incumbent(rnd, seat)
    worlds = [{"world": 0}, {"world": 1}]
    _install_sampler(bot, worlds)
    calls = []

    def rollout(_bot, _rnd, _seat, sampled, bury, lead):
        world = sampled["world"]
        calls.append((world, tuple(sorted(bury)), tuple(sorted(lead))))
        # Deterministic but non-constant values make the raw ranking useful.
        return float(world * 10 + len(lead) + sum(
            1 for card in bury if card.endswith("5"))), True

    monkeypatch.setattr(E, "_rollout_bury_lead", rollout)
    result = E.score_state(
        rnd, seat, bot=bot, incumbent_bury=incumbent, worlds=2,
        max_candidate_rollouts=10_000)

    count = result["candidate_count"]
    assert result["status"] == "COMPLETE_EXPLORATION"
    assert result["work"] == {
        "worlds_requested": 2,
        "worlds_used": 2,
        "attempts": 2,
        "attempt_cap": 80,
        "candidate_rollouts": count * 2,
        "requested_candidate_rollouts": count * 2,
        "candidate_rollout_cap": 10_000,
        "common_worlds": True,
        "complete": True,
    }
    assert [world for world, *_ in calls[:count]] == [0] * count
    assert [world for world, *_ in calls[count:]] == [1] * count
    assert all(candidate["worlds"] == 2
               for candidate in result["candidates"])
    assert result["candidates"][0]["paired_gap_vs_candidate_zero"] == 0
    assert result["candidates"][0]["paired_se_vs_candidate_zero"] == 0
    assert result["raw_winner_index"] is not None
    references = result["raw_descriptive_winners"]
    assert references["incumbent_live_menu_index"] is not None
    assert references["incumbent_widened_menu_index"] is not None
    assert references["expanded_menu_index"] == result["raw_winner_index"]
    assert references["post_selection_coverage"] is False
    assert references["widened_lead_minus_live_lead"]["worlds"] == 2
    live_index = references["incumbent_live_menu_index"]
    widened_index = references["incumbent_widened_menu_index"]
    assert result["candidates"][live_index]["incumbent_bury"] is True
    assert result["candidates"][live_index]["live_lead"] is True
    assert result["candidates"][widened_index]["incumbent_bury"] is True
    assert "not the production bot's final searched first lead" in \
        result["reference_contract"]["candidate_zero"]
    assert result["winner_selection_corrected"] is False
    assert result["confirmatory_inference"] is False
    assert result["strength_claim"] is False
    assert result["production_deployment"] is False
    assert result["sampler_counters"]["delta"] == {
        "sample_attempts": 2,
        "accepted_worlds": 2,
        "failed_worlds": 0,
        "rejected_worlds": 0,
        "impossible_worlds": 0,
    }


def test_sampler_underfill_keeps_completed_dev_learning(monkeypatch):
    rnd, seat = _bury_round()
    bot, incumbent = _bot_and_incumbent(rnd, seat)
    _install_sampler(bot, [{"world": 7}, None, None, None, None, None])
    calls = []

    def rollout(_bot, _rnd, _seat, sampled, bury, lead):
        calls.append((sampled["world"], tuple(bury), tuple(lead)))
        return float(len(bury) + len(lead)), True

    monkeypatch.setattr(E, "_rollout_bury_lead", rollout)
    result = E.score_state(
        rnd, seat, bot=bot, incumbent_bury=incumbent, worlds=3,
        attempt_factor=2, max_candidate_rollouts=10_000)

    count = result["candidate_count"]
    assert result["status"] == "PARTIAL_EXPLORATION"
    assert result["work"]["complete"] is False
    assert result["work"]["worlds_used"] == 1
    assert result["work"]["attempts"] == 6
    assert result["work"]["candidate_rollouts"] == count
    assert len(calls) == count
    assert all(candidate["worlds"] == 1
               and candidate["mean_banker_value"] is not None
               for candidate in result["candidates"])
    assert result["strength_claim"] is False
    assert result["sampler_counters"]["delta"]["failed_worlds"] == 5


def test_candidate_world_cap_refuses_before_sampling(monkeypatch):
    rnd, seat = _bury_round()
    bot, incumbent = _bot_and_incumbent(rnd, seat)
    before = bot._sampler_snapshot()

    def forbidden(*_args, **_kwargs):
        raise AssertionError("sampler or rollout ran before cap admission")

    monkeypatch.setattr(bot, "_sample_hands", forbidden)
    monkeypatch.setattr(E, "_rollout_bury_lead", forbidden)
    with pytest.raises(E.ComboExplorationRefused, match="exceeds cap"):
        E.score_state(
            rnd, seat, bot=bot, incumbent_bury=incumbent, worlds=1,
            max_candidate_rollouts=1)
    assert bot._sampler_snapshot() == before


def test_one_real_world_preserves_card_conservation_and_throw_resolution():
    """A tiny integration witness exercises the real engine, not fleet compute."""
    rnd, seat = _bury_round()
    bot, incumbent = _bot_and_incumbent(rnd, seat)
    sampled = {
        other: list(rnd.hands[other])
        for other in range(4) if other != seat
    }
    ballot = E.build_bury_lead_combo_ballot(
        rnd, seat, incumbent, live_lead_ballot=bot._candidates)
    group = ballot.groups[0]
    lead = next((candidate for candidate in group.leads
                 if candidate.structured_throw), group.leads[0])
    attacker_points, succeeded = E._rollout_bury_lead(
        bot, rnd, seat, sampled, group.bury.cards, lead.cards)
    assert 0 <= attacker_points <= 800
    assert isinstance(succeeded, bool)
    assert Counter(rnd.hands[seat]) >= Counter(group.bury.cards)
    assert rnd.phase == "bury", "integration rollout must not mutate input"
