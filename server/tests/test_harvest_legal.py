"""Exhaustive legal-action enumerator: brute-force cross-check against
``Round.play`` on >= 200 sampled natural states, agreement with the engine's
bounded ``exhaustive_legal_actions``, exact counting, caps."""
import random
from collections import Counter
from itertools import combinations

import pytest

from shengji.ai.endgame import exhaustive_legal_actions
from shengji.harvest import legal
from shengji.harvest.common import REPO
from shengji.harvest.room_log import log_files, read_rounds
from shengji.harvest.common import InputRegistry
from shengji.rl.replay_log import rebuild_round

N_STATES = 240


def _sampled_states(n=N_STATES, seed=11):
    """Natural decision states from the room logs (clones, acting seat)."""
    rng = random.Random(seed)
    registry = InputRegistry()
    states = []
    files = log_files(REPO)
    rng.shuffle(files)
    for path in files:
        rounds, _ = read_rounds(path, registry)
        for rno in sorted(rounds):
            evs = rounds[rno]
            rnd = rebuild_round(evs)
            if rnd is None:
                continue
            for e in evs:
                if e.get("e") != "play" or rnd.phase != "play":
                    continue
                if rnd.turn == e["seat"] and rng.random() < 0.1:
                    states.append(legal.clone_for_probe(rnd))
                try:
                    rnd.play(e["seat"], e["cards"])
                except Exception:
                    break
            if len(states) >= n:
                return states[:n]
    return states


@pytest.fixture(scope="module")
def states():
    s = _sampled_states()
    assert len(s) >= 200
    return s


def test_brute_force_cross_check(states):
    rng = random.Random(5)
    leads = follows = complete_full = 0
    for rnd in states:
        seat = rnd.turn
        full = legal.enumerate_legal(rnd, seat, cap=None)
        assert full.complete and full.count == len(full.actions)
        assert len(full.keys()) == len(full.actions)          # no duplicates
        for a in full.actions:
            assert a == sorted(a)
        if full.kind == "lead":
            leads += 1
            # every sub-multiset of size <= 3: enumerator <=> engine accepts
            bf = legal.brute_force_legal(rnd, seat, max_size=3)
            assert bf == {a for a in full.keys() if len(a) <= 3}
            if len(rnd.hands[seat]) <= 9:                      # whole hand
                assert legal.brute_force_legal(rnd, seat) == full.keys()
                complete_full += 1
        else:
            follows += 1
            n = len(rnd.trick.plays[0].cards)
            cands = list(legal.multiset_subsets(rnd.hands[seat], n))
            if len(cands) > 3000:
                cands = rng.sample(cands, 3000)
            else:
                complete_full += 1
            for c in cands:
                assert legal.engine_accepts(rnd, seat, c) == (c in full.keys()), c
    print(f"brute-force cross-check: {len(states)} states ({leads} leads, "
          f"{follows} follows), {complete_full} fully enumerated by brute force")
    assert leads >= 40 and follows >= 100


def test_agrees_with_engine_endgame_enumerator(states):
    """The engine's bounded brute-force enumerator is the reference where it
    is defined (hands of at most max_hand_cards)."""
    checked = 0
    for rnd in states:
        seat = rnd.turn
        cap = max(len(h) for h in rnd.hands)
        if cap > 8:
            continue
        ref = {tuple(a) for a in exhaustive_legal_actions(rnd, seat, max_hand_cards=cap)}
        assert legal.enumerate_legal(rnd, seat, cap=None).keys() == ref
        checked += 1
    assert checked >= 5


def test_cap_prefix_and_must_include(states):
    for rnd in states:
        seat = rnd.turn
        full = legal.enumerate_legal(rnd, seat, cap=None)
        capped = legal.enumerate_legal(rnd, seat, cap=8)
        assert capped.count == full.count
        assert capped.actions == full.actions[:8]
        assert capped.complete == (full.count <= 8)
        last = full.actions[-1]
        with_extra = legal.enumerate_legal(rnd, seat, cap=8, must_include=[last])
        assert tuple(last) in with_extra.keys()
        if not with_extra.complete:
            assert with_extra.actions[:8] == full.actions[:8]
        # an illegal must_include is refused, never silently listed
        hand = rnd.hands[seat]
        bad = ["BJ"] * 3
        if Counter(hand)["BJ"] < 3 and not with_extra.complete:
            with pytest.raises(ValueError):
                legal.enumerate_legal(rnd, seat, cap=8, must_include=[bad])


def test_multiset_counting_matches_brute_force():
    rng = random.Random(2)
    for _ in range(60):
        codes = [f"c{i}" for i in range(rng.randint(1, 7))]
        cards = [c for c in codes for _ in range(rng.randint(1, 3))]
        counts = list(Counter(cards).values())
        for size in range(0, len(cards) + 1):
            expected = {tuple(sorted(cards[i] for i in idx))
                        for idx in combinations(range(len(cards)), size)}
            assert legal.count_multiset_subsets(counts, size) == len(expected)
            listed = list(legal.multiset_subsets(cards, size))
            assert set(listed) == expected and len(listed) == len(expected)
            assert listed == sorted(listed)
        assert legal.count_nonempty_submultisets(counts) == sum(
            legal.count_multiset_subsets(counts, k) for k in range(1, len(cards) + 1))


def test_lead_order_structured_first(states):
    """Singles, then pairs, then tractors, then throws by size."""
    for rnd in states:
        if rnd.trick.plays:
            continue
        seat = rnd.turn
        full = legal.enumerate_legal(rnd, seat, cap=None)
        sizes = [len(a) for a in full.actions]
        n_single = sum(1 for s in sizes if s == 1)
        assert sizes[:n_single] == [1] * n_single
        pairs = [a for a in full.actions if len(a) == 2 and a[0] == a[1]]
        if pairs:
            first_pair = full.actions.index(pairs[0])
            assert first_pair == n_single


def test_bury_count():
    assert legal.bury_action_count(["a"] * 8) == 1
    assert legal.bury_action_count([f"c{i}" for i in range(10)]) == 45
