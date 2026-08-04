"""The world sampler must respect every constraint the history proves.

The old sampler was a greedy first-fit over a shuffled pool: it gave each card
to a random seat that still had room. That dead-ends on states where a legal
world plainly exists — place two off-suit cards early and the only seat that
can take the next suit is full. Fourteen such dead-ends landed inside the
determinization confirmation blocks, each forcing `PROTOCOL FAILURES` and
invalidating the run it appeared in.

It also never consumed `pair_cap`, which Codex raised four times.
"""
from __future__ import annotations

import random
from collections import Counter

import pytest

from shengji.ai.env import play_round
from shengji.ai.memory import Memory
from shengji.ai.registry import make_bot
from shengji.engine.game import Game


def _states(n_rounds=12, seed0=770000):
    """Real mid-round states, with the memory each acting seat would have."""
    out = []
    for s in range(n_rounds):
        game = Game(random.Random(seed0 + s))
        bots = [make_bot("smart") for _ in range(4)]
        rnd = game.start_round()
        while rnd.phase == "deal":
            seat, _, _ = rnd.deal_next()
            cards = bots[seat].decide_declare(rnd, seat)
            if cards:
                rnd.declare(seat, cards)
        rnd.finalize_declare()
        rnd.bury(rnd.banker, bots[rnd.banker].decide_bury(rnd, rnd.banker))
        while rnd.phase == "play":
            seat = rnd.turn
            if seat is None:
                break
            if len(rnd.history) >= 3:
                out.append((rnd, seat, Memory(rnd, seat)))
                break
            rnd.play(seat, bots[seat].decide_play(rnd, seat))
    return out


def test_failing_a_tractor_lead_proves_zero_pairs_remain():
    """A REAL history, not three integers asserted against themselves.

    My first version of this test assigned literals to a dict and asserted the
    same literals — it could not have failed, and it was defending an inference
    that was itself wrong (Codex). The engine enforces
    `need_pairs = min(lead_pairs, pair_count(their_suit))`, so a follower who
    shows fewer pairs than were led has played EVERY pair they had: what
    remains is zero, whether a pair or a tractor was led.

    The assertion here is derived from the RULE (via validate_follow), not from
    Memory, so producer and validator do not share the disputed inference.
    """
    from shengji.engine.cards import Ordering
    from shengji.engine.combos import pair_count
    from shengji.engine.legal import IllegalPlay, validate_follow

    o = Ordering("H", "7")
    lead = ["S3", "S3", "S4", "S4"]                  # a two-pair tractor
    hand = ["S9", "S9", "SK", "SQ", "S2"]            # exactly ONE pair, 5 cards
    play = ["S9", "S9", "SK", "SQ"]                  # gives up that pair
    validate_follow(play, hand, lead, o)             # legal
    assert pair_count([c for c in play if o.eff_suit(c) == "S"]) == 1 < 2

    # Keeping the pair back is ILLEGAL — which is exactly why the remaining
    # hand provably has none.
    with pytest.raises(IllegalPlay):
        validate_follow(["SK", "SQ", "S2", "S9"], hand, lead, o)

    left = list(hand)
    for c in play:
        left.remove(c)
    assert pair_count([c for c in left if o.eff_suit(c) == "S"]) == 0


def test_memory_records_zero_after_a_short_pair_answer():
    """Memory's inference must match the rule-derived conclusion above."""
    import random

    from shengji.ai.memory import Memory
    from shengji.engine.combos import pair_count

    for seed in range(25):
        game = Game(random.Random(600000 + seed))
        bots = [make_bot("smart") for _ in range(4)]
        rnd = game.start_round()
        while rnd.phase == "deal":
            seat, _, _ = rnd.deal_next()
            cards = bots[seat].decide_declare(rnd, seat)
            if cards:
                rnd.declare(seat, cards)
        rnd.finalize_declare()
        rnd.bury(rnd.banker, bots[rnd.banker].decide_bury(rnd, rnd.banker))
        while rnd.phase == "play":
            seat = rnd.turn
            if seat is None:
                break
            rnd.play(seat, bots[seat].decide_play(rnd, seat))
            mem = Memory(rnd, 0)
            for s in range(4):
                for suit, cap in mem.pair_cap[s].items():
                    assert cap == 0, (
                        f"seat {s} suit {suit}: cap {cap}. A short pair answer "
                        f"proves ZERO pairs remain; any other value is a "
                        f"weaker claim than the rule supports.")
                    # and the truth, checked against the real hidden hand
                    held = [c for c in rnd.hands[s]
                            if rnd.ordering.eff_suit(c) == suit]
                    assert pair_count(held) == 0, (
                        f"seat {s} actually holds {pair_count(held)} pairs in "
                        f"{suit} — the inference is UNSOUND, not merely weak")
    assert True


def test_sampled_worlds_never_violate_a_proven_void():
    bot = make_bot("mc", seed=3)
    checked = 0
    for rnd, seat, mem in _states():
        for _ in range(20):
            got = bot._sample_hands(rnd, seat, mem)
            if got is None:
                continue
            hands, _ = got
            for s, cards in hands.items():
                for c in cards:
                    assert rnd.ordering.eff_suit(c) not in mem.voids[s], (
                        f"seat {s} was dealt {c} in a suit it is proven void in")
            checked += 1
    assert checked > 50, f"only {checked} worlds sampled; test is not exercising"


def test_sampled_worlds_never_exceed_a_proven_pair_cap():
    """The constraint `pair_cap` exists for, finally consumed."""
    bot = make_bot("mc", seed=5)
    checked = violations = 0
    for rnd, seat, mem in _states(n_rounds=16):
        for _ in range(20):
            got = bot._sample_hands(rnd, seat, mem)
            if got is None:
                continue
            hands, _ = got
            for s, cards in hands.items():
                per_suit: dict[str, list[str]] = {}
                for c in cards:
                    per_suit.setdefault(rnd.ordering.eff_suit(c), []).append(c)
                for suit, cs in per_suit.items():
                    cap = mem.max_pairs(s, suit)
                    if cap is None:
                        continue
                    pairs = sum(v // 2 for v in Counter(cs).values())
                    if pairs > cap:
                        violations += 1
            checked += 1
    assert checked > 50
    assert violations == 0, f"{violations} worlds exceeded a proven pair cap"


def test_conservation_holds_in_every_sampled_world():
    bot = make_bot("mc", seed=7)
    for rnd, seat, mem in _states():
        for _ in range(10):
            got = bot._sample_hands(rnd, seat, mem)
            if got is None:
                continue
            hands, extra = got
            for s, cards in hands.items():
                assert len(cards) == len(rnd.hands[s]), \
                    f"seat {s} got {len(cards)} cards, needs {len(rnd.hands[s])}"
            dealt = Counter()
            for cards in hands.values():
                dealt.update(cards)
            if seat != rnd.banker:
                dealt.update(extra)
            assert dealt == mem.unseen, "sampled world does not use the pool exactly"


@pytest.mark.parametrize("require", [True, False])
def test_search_never_loses_all_worlds(require, monkeypatch):
    """The gate that matters: a decision must never fall back with zero worlds.

    Zero-world decisions are a protocol failure in the evaluator, so a sampler
    that produces them poisons whatever run it appears in.
    """
    if require:
        monkeypatch.setenv("SHENGJI_REQUIRE_VOIDS", "1")
    else:
        monkeypatch.delenv("SHENGJI_REQUIRE_VOIDS", raising=False)
    zero = 0
    for s in range(6):
        pol = [make_bot("mc", seed=s + i * 100) for i in range(4)]
        play_round(Game(random.Random(91_000_000 + s)), pol)
        zero += sum(b.zero_world_decisions for b in pol)
    assert zero == 0, f"{zero} decisions searched no worlds at all"
