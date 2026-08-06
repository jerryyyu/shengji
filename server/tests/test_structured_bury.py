"""S3a structured-bury source and common-world scoring invariants."""
from __future__ import annotations

import copy
import json
import os
import random
import subprocess
import sys
from collections import Counter, defaultdict
from types import MethodType

import pytest

from shengji.ai.bury import structured_bury_ballot
from shengji.ai.mcbot import MCBot
from shengji.ai.smart import SmartBot
from shengji.engine.ballot import mc_ballot
from shengji.engine.cards import points
from shengji.engine.game import Game


def _bury_round(seed=0):
    rnd = Game(random.Random(seed)).start_round()
    while rnd.phase == "deal":
        rnd.deal_next()
    rnd.finalize_declare()
    assert rnd.phase == "bury" and rnd.banker is not None
    return rnd, rnd.banker


def _key(cards):
    return tuple(sorted(cards))


def test_fixed_challenge_is_broad_bounded_legal_and_keeps_incumbent():
    rnd, seat = _bury_round(0)
    hand = Counter(rnd.hands[seat])
    incumbent = SmartBot().decide_bury(rnd, seat)
    ballot = structured_bury_ballot(rnd.hands[seat], rnd.ordering, incumbent)

    assert 20 <= len(ballot.candidates) <= ballot.max_candidates == 32
    assert _key(ballot.candidates[0].cards) == _key(incumbent)
    keys = [_key(candidate.cards) for candidate in ballot.candidates]
    assert len(keys) == len(set(keys)), "candidate multisets must be deduplicated"
    for candidate in ballot.candidates:
        assert len(candidate.cards) == 8
        assert not (Counter(candidate.cards) - hand)
    sources = {source for candidate in ballot.candidates
               for source in candidate.sources}
    assert any("point_preserving" in source for source in sources)
    assert any("trump_preserving" in source for source in sources)
    assert any("pair_preserving" in source for source in sources)
    assert any(candidate.voids_created for candidate in ballot.candidates)
    assert min(candidate.point_total for candidate in ballot.candidates) == 0
    assert min(candidate.trumps_buried for candidate in ballot.candidates) == 0


def test_source_is_permutation_stable_and_does_not_mutate_inputs():
    rnd, seat = _bury_round(8)
    hand = list(rnd.hands[seat])
    incumbent = SmartBot().decide_bury(rnd, seat)
    first = structured_bury_ballot(hand, rnd.ordering, incumbent)
    reversed_hand = list(reversed(hand))
    second = structured_bury_ballot(reversed_hand, rnd.ordering,
                                    list(reversed(incumbent)))
    assert first.record() == second.record()
    assert hand == rnd.hands[seat]
    assert reversed_hand == list(reversed(hand))


def test_explicit_candidate_cap_truncates_after_the_incumbent():
    rnd, seat = _bury_round(8)
    incumbent = SmartBot().decide_bury(rnd, seat)
    full = structured_bury_ballot(rnd.hands[seat], rnd.ordering, incumbent)
    capped = structured_bury_ballot(
        rnd.hands[seat], rnd.ordering, incumbent, max_candidates=5)
    assert len(capped.candidates) == 5
    assert capped.generated_unique == full.generated_unique > 5
    assert capped.truncated is True
    assert capped.candidates[0].cards == full.candidates[0].cards


def test_candidate_source_cannot_read_opponent_hands_or_hidden_deck():
    rnd, seat = _bury_round(4)
    bot = type("Structured", (MCBot,), {
        "MC_BURY": True, "STRUCTURED_BURY": True,
    })(seed=1)
    incumbent = bot._canonical_bury(rnd, seat)
    first = bot._structured_bury_ballot(rnd, seat, incumbent).record()

    altered = copy.deepcopy(rnd)
    for other in range(4):
        if other != seat:
            altered.hands[other] = ["BJ"] * len(altered.hands[other])
    altered.deck = list(reversed(altered.deck))
    altered.kitty = ["LJ"] * len(altered.kitty)
    second = bot._structured_bury_ballot(altered, seat, incumbent).record()
    assert second == first, \
        "source output changed after only hidden opponent/deck data changed"


def test_structured_bury_is_not_part_of_the_lead_follow_ballot_identity():
    ordinary = MCBot(seed=1)
    structured = type("Structured", (MCBot,), {
        "MC_BURY": True, "STRUCTURED_BURY": True,
    })(seed=1)
    assert mc_ballot(ordinary).digest == mc_ballot(structured).digest


def test_common_world_scoring_is_matched_and_respects_hard_work_cap():
    rnd, seat = _bury_round(0)
    cls = type("Structured", (MCBot,), {
        "MC_BURY": True,
        "STRUCTURED_BURY": True,
        "N_BURY_WORLDS": 3,
        "BURY_MAX_ROLLOUTS": 96,
    })
    bot = cls(seed=9)
    seen = []
    world = 0

    def fake_sample(self, _rnd, _seat, _mem):
        nonlocal world
        self.sample_attempts += 1
        self.accepted_worlds += 1
        result = ({"world": world}, [])
        world += 1
        return result

    def fake_rollout(self, _rnd, _seat, hands, candidate):
        seen.append((hands["world"], _key(candidate)))
        # Banker maximises the negative of this value: fewer buried points is
        # preferable in this deterministic challenge seam.
        return float(100 + sum(points(code) for code in candidate))

    bot._sample_hands = MethodType(fake_sample, bot)
    bot._rollout_from_bury = MethodType(fake_rollout, bot)
    hand_before = Counter(rnd.hands[seat])
    played = bot.decide_bury(rnd, seat)
    rec = bot.last_bury_record

    assert len(played) == 8 and not (Counter(played) - hand_before)
    assert rec["schema"] == "structured-bury-search-v1"
    assert rec["common_worlds"] is True
    assert rec["candidate_count"] == len(rec["candidates"])
    assert rec["work"]["worlds_used"] == 3
    assert rec["work"]["candidate_rollouts"] == 3 * rec["candidate_count"]
    assert rec["work"]["candidate_rollouts"] <= rec["work"]["cap"] == 96
    assert rec["work"]["complete"] is True
    assert rec["n_by_candidate"] == [3] * rec["candidate_count"]
    by_world = defaultdict(list)
    for w, candidate in seen:
        by_world[w].append(candidate)
    expected = [_key(candidate["cards"]) for candidate in rec["candidates"]]
    assert set(by_world) == {0, 1, 2}
    assert all(values == expected for values in by_world.values())
    assert rec["sampler_counters"]["delta"]["accepted_worlds"] == 3


def test_work_cap_too_small_for_one_common_world_refuses_before_sampling():
    rnd, seat = _bury_round(0)
    bot = type("Underfunded", (MCBot,), {
        "MC_BURY": True,
        "STRUCTURED_BURY": True,
        "BURY_MAX_ROLLOUTS": 4,
    })(seed=1)
    with pytest.raises(ValueError, match="at least one common world"):
        bot.decide_bury(rnd, seat)
    assert bot.sample_attempts == 0


def test_one_real_common_world_returns_an_engine_legal_bury():
    rnd, seat = _bury_round(0)
    bot = type("OneWorld", (MCBot,), {
        "MC_BURY": True,
        "STRUCTURED_BURY": True,
        "N_BURY_WORLDS": 1,
    })(seed=9)
    played = bot.decide_bury(rnd, seat)
    rec = bot.last_bury_record
    assert rec["candidate_count"] > 4
    assert rec["work"]["candidate_rollouts"] == rec["candidate_count"]
    assert rec["work"]["complete"] is True
    rnd.bury(seat, played)                 # engine legality is the assertion
    assert rnd.phase == "play" and len(rnd.hands[seat]) == 25


def test_underfilled_scoring_falls_back_and_is_loudly_counted():
    rnd, seat = _bury_round(0)
    bot = type("Failing", (MCBot,), {
        "MC_BURY": True,
        "STRUCTURED_BURY": True,
        "N_BURY_WORLDS": 2,
        "SAMPLE_ATTEMPT_FACTOR": 2,
    })(seed=3)

    def fail_sample(self, _rnd, _seat, _mem):
        self.sample_attempts += 1
        self.failed_worlds += 1
        return None

    bot._sample_hands = MethodType(fail_sample, bot)
    incumbent = bot._canonical_bury(rnd, seat)
    played = bot.decide_bury(rnd, seat)
    rec = bot.last_bury_record
    assert _key(played) == _key(incumbent)
    assert rec["reason"] == "bury_search_underfilled"
    assert rec["work"]["complete"] is False
    assert bot.bury_short_searches == 1
    assert bot.short_search_decisions == 1
    assert bot.zero_world_decisions == 1
    assert rec["sampler_counters"]["delta"]["failed_worlds"] == 4


def test_production_bury_path_is_unchanged_when_feature_is_off():
    rnd, seat = _bury_round(3)
    expected = SmartBot().decide_bury(rnd, seat)
    bot = MCBot(seed=11)
    assert bot.decide_bury(rnd, seat) == expected
    assert bot.last_bury_record is None
    assert bot.bury_search_calls == bot.bury_rollouts == 0


_PROCESS_SCRIPT = r"""
import json, random
from shengji.ai.bury import structured_bury_ballot
from shengji.ai.smart import SmartBot
from shengji.engine.game import Game
r = Game(random.Random(8)).start_round()
while r.phase == 'deal':
    r.deal_next()
r.finalize_declare()
b = SmartBot()
out = structured_bury_ballot(r.hands[r.banker], r.ordering,
                             b.decide_bury(r, r.banker))
print(json.dumps(out.record(), sort_keys=True))
"""


def test_source_is_hash_seed_independent_across_processes():
    outputs = []
    server = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for hash_seed in ("0", "8128"):
        env = dict(os.environ, PYTHONHASHSEED=hash_seed)
        proc = subprocess.run(
            [sys.executable, "-c", _PROCESS_SCRIPT], cwd=server, env=env,
            capture_output=True, text=True)
        assert proc.returncode == 0, proc.stderr
        outputs.append(json.loads(proc.stdout))
    assert outputs[0] == outputs[1]
