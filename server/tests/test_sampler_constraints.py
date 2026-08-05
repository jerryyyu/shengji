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


def test_declared_pin_cannot_complete_a_forbidden_pair():
    """The declarer pin and the pair cap must agree about the SAME hand.

    Found by certification, not by these tests: a seat that declared one copy
    of a trump-rank card has it pinned into its sampled hand BEFORE dealing,
    and the deal counted only the cards it was placing. It handed over the
    second copy and built a pair the play history proves that seat cannot
    hold. Twelve such worlds in 28,800 at late ply, zero at early ply — the
    regime where nobody has failed a pair lead yet cannot expose it.
    """
    from shengji.engine.combos import pair_count

    checked = violations = 0
    for rnd, seat, mem in _states(n_rounds=30, seed0=98001000):
        pinned = {code: who for code, (who, _) in mem.known.items()}
        if not pinned:
            continue
        bot = make_bot("mc", seed=99)
        for _ in range(24):
            got = bot._sample_hands(rnd, seat, mem)
            if got is None:
                continue
            checked += 1
            for s, cards in got[0].items():
                per_suit: dict[str, list[str]] = {}
                for c in cards:
                    per_suit.setdefault(rnd.ordering.eff_suit(c), []).append(c)
                for suit, cs in per_suit.items():
                    cap = mem.max_pairs(s, suit)
                    if cap is not None and pair_count(cs) > cap:
                        violations += 1
    assert violations == 0, (
        f"{violations} sampled worlds exceeded a pair cap once pinned cards "
        f"were counted — the pin and the cap are looking at different hands")


def test_pair_cap_forward_check_prevents_a_rejected_world():
    """Regression for the state that stopped the first DEV-512 launch.

    `original:81002046:4`: 6 effective clubs over 4 codes (C10 and CQ doubled),
    seat 2 void in clubs, kitty full, and pair_cap 0 for every seat. A receiver
    given n cards from d distinct codes is FORCED to hold n-d pairs, so any
    split handing one seat 5 clubs is impossible however the cards shuffle.
    `place` forward-checked VOIDS only, proposed such splits, and `_deal_suit`
    exhausted its retries discovering it — after which the sampler fell back to
    IGNORING VOIDS and counted a rejected world, failing the run's protocol
    invariant.

    The world is sampled through the runner's own per-fold stream, because the
    bot's default RNG does not reach the failing draw (it is attempt 31 of the
    proposal stream) — a probe on the default stream reports zero and proves
    nothing.
    """
    import json
    import random
    import sys
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, os.path.join(root, "scripts"))
    import pilot_states as PS
    from shengji.ai.registry import make_bot
    from shengji.ai.memory import Memory
    from shengji.pilot_folds import stream_seed

    art = os.path.join(root, "rl_data", "pilot_dev512.v6.json")
    if not os.path.exists(art):
        pytest.skip("v6 gate artifact absent")
    st = next(s for s in json.load(open(art))["states"]
              if s["seed"] == 81002046 and s["ply"] == 4)
    corpus = {n: c for n, c, _ in PS.SOURCES}[st["source"]]
    row = next(json.loads(l) for l in open(corpus)
               if json.loads(l)["seed"] == st["seed"]
               and json.loads(l)["ply"] == st["ply"])
    rnd = PS.replay(row)
    seat = st["seat"]
    bot = make_bot("mc", seed=1)
    mem = Memory(rnd, seat)
    bot.rng = random.Random(
        stream_seed("pilot-run-v1", "original:81002046:4", "proposal"))
    bot.rejected_worlds = 0
    for _ in range(200):
        bot._sample_hands(rnd, seat, mem)
    assert bot.rejected_worlds == 0, (
        "the void-ignoring fallback fired; a constraint-correct world exists "
        "and the search must find it")


# --- pair-cap prune: necessary AND sufficient -------------------------------
# Codex accepted `n_r <= D + cap_r` as NECESSARY and left completeness open.
# It is also SUFFICIENT, and the proof is short:
#
#   Necessity  — a receiver given n_r cards drawn from D distinct codes must
#                double at least n_r - D of them, so n_r - D <= cap_r.
#   Sufficiency— with multiplicity <= 2, N = D + P where P is the number of
#                doubled codes, so N <= 2D. Two receivers both above D would
#                need n_A + n_B > 2D >= N, impossible. So AT MOST ONE receiver
#                exceeds D, and for it n_r - D <= N - D = P, i.e. enough
#                doubled codes exist to supply the pairs it is forced into.
#
# The tests below check the claim by brute force rather than trusting the
# argument, because the argument is exactly the kind of thing I have been wrong
# about before.

def _suit_assignment_exists(mults, quotas, caps):
    """Brute force: hit every quota without exceeding any pair cap."""
    import itertools
    R = len(quotas)

    def rec(i, rem_q, rem_cap):
        if i == len(mults):
            return all(q == 0 for q in rem_q)
        m = mults[i]
        for combo in itertools.product(range(m + 1), repeat=R):
            if sum(combo) != m:
                continue
            if any(c > rem_q[r] for r, c in enumerate(combo)):
                continue
            pairs = [1 if c == 2 else 0 for c in combo]
            if any(pairs[r] > rem_cap[r] for r in range(R)):
                continue
            if rec(i + 1, tuple(rem_q[r] - combo[r] for r in range(R)),
                   tuple(rem_cap[r] - pairs[r] for r in range(R))):
                return True
        return False

    return rec(0, tuple(quotas), tuple(caps))


def _prune_condition(mults, quotas, caps):
    D = len(mults)
    return all(q - D <= c for q, c in zip(quotas, caps))


def test_pair_cap_condition_is_necessary_and_sufficient_exhaustively():
    import itertools
    checked = 0
    for ncodes in range(1, 5):
        for mults in itertools.product((1, 2), repeat=ncodes):
            N = sum(mults)
            for R in (2, 3, 4):
                for quotas in itertools.product(range(N + 1), repeat=R):
                    if sum(quotas) != N:
                        continue
                    for caps in itertools.product(range(3), repeat=R):
                        checked += 1
                        assert (_prune_condition(mults, quotas, caps)
                                == _suit_assignment_exists(mults, quotas, caps)), \
                            f"mults={mults} quotas={quotas} caps={caps}"
    assert checked > 170000, checked   # the bound actually claimed


def test_pair_cap_condition_holds_at_realistic_suit_sizes():
    import random
    rng = random.Random(20260805)
    for _ in range(20000):
        D = rng.randint(1, 11)
        mults = tuple(rng.choice((1, 2)) for _ in range(D))
        N = sum(mults)
        R = rng.randint(2, 4)
        cuts = sorted(rng.randint(0, N) for _ in range(R - 1))
        quotas = [b - a for a, b in zip([0] + cuts, cuts + [N])]
        caps = [rng.randint(0, 3) for _ in range(R)]
        assert (_prune_condition(mults, quotas, caps)
                == _suit_assignment_exists(mults, quotas, caps)), \
            f"mults={mults} quotas={quotas} caps={caps}"


def test_the_condition_does_NOT_characterize_the_production_dealer():
    """The sufficiency proof holds in a REDUCED MODEL only (Codex).

    `_assign` computes D over FREE cards, having removed declared `pre` pins,
    while `_deal_suit` enforces the cap on `pre + chunk`. So a receiver already
    pinned one H7, offered one free H7 with n=1, D=1, cap 0, satisfies
    `n - D <= cap` and still cannot be dealt. `run_cap` is a second omitted
    failure class. The check therefore remains a SAFE NECESSARY prune — it
    never removes a feasible split — but it is not an exact characterization of
    production feasibility, and any constructive dealer built from the proof
    must cover pins and run caps.
    """
    from collections import Counter
    from unittest.mock import MagicMock
    from shengji.ai.mcbot import MCBot
    bot = MCBot(seed=1)
    mem = MagicMock()
    mem.max_pairs.return_value = 0
    mem.max_run.return_value = None
    mem.o = None
    assert _prune_condition((1,), [1], [0]) is True
    assert bot._deal_suit(["H7"], 1, 0, "H", mem, Counter({"H7": 1})) is None


def test_at_most_one_receiver_can_exceed_the_distinct_code_count():
    """The lemma sufficiency rests on. N = D + P <= 2D."""
    import random
    rng = random.Random(7)
    for _ in range(200000):
        D = rng.randint(1, 13)
        mults = [rng.choice((1, 2)) for _ in range(D)]
        N = sum(mults)
        R = rng.randint(2, 4)
        cuts = sorted(rng.randint(0, N) for _ in range(R - 1))
        quotas = [b - a for a, b in zip([0] + cuts, cuts + [N])]
        assert sum(1 for q in quotas if q > D) <= 1, (mults, quotas)


def test_certifier_counts_rows_it_cannot_rebuild():
    """A silent skip lets a certifier certify whatever happened to work.

    Both replay loops in `certify_sampler` swallow exceptions and `continue`.
    That is defensible — an unrebuildable row cannot be certified — but it must
    be COUNTED and reported, or the certified population is whatever survived.
    """
    import os
    import sys
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, os.path.join(root, "scripts"))
    import certify_sampler as CS

    CS.reset_certification_skips()
    assert all(v == 0 for v in CS.certification_skips().values())
    assert set(CS.certification_skips()) >= {
        "toy_state_replay", "corpus_row_replay",
        "corpus_deck_mismatch", "corpus_wrong_seat_or_phase"}
    # drive the counted path directly: the swallow sites increment these
    CS.SKIPPED["corpus_row_replay"] += 1
    assert CS.certification_skips()["corpus_row_replay"] == 1, \
        "the skip counter is not observable"
    CS.reset_certification_skips()
    assert CS.certification_skips()["corpus_row_replay"] == 0


def test_certifier_skip_counters_are_wired_to_the_swallow_sites():
    """Guards against the counters existing but never being incremented.

    Uses the AST, not string proximity. My first version asserted
    `"except Exception:" in src[before-200:before]`, which STILL PASSED when the
    increment was moved outside the handler — the except line remained inside
    the window. That is the vacuous-mechanism pattern this test exists to
    prevent, so it is checked structurally: the increment must be a descendant
    of an `ExceptHandler` node.
    """
    import ast
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    tree = ast.parse(open(os.path.join(root, "scripts",
                                       "certify_sampler.py")).read())

    def increments_in_handlers():
        found = set()
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            for sub in ast.walk(node):
                if isinstance(sub, ast.AugAssign) and \
                        isinstance(sub.target, ast.Subscript) and \
                        isinstance(sub.target.value, ast.Name) and \
                        sub.target.value.id == "SKIPPED":
                    key = sub.target.slice
                    if isinstance(key, ast.Constant):
                        found.add(key.value)
        return found

    inside = increments_in_handlers()
    for key in ("toy_state_replay", "corpus_row_replay"):
        assert key in inside, (
            f"SKIPPED[{key!r}] is not incremented INSIDE an except handler; a "
            f"counter no failure path touches counts nothing")


def test_certified_is_false_when_the_population_was_incomplete():
    """`certified: true` must not survive silent drops.

    It previously depended only on invalid-world / reachability / witness
    counts, so a run that skipped rows it could not rebuild still certified
    (Codex). Asserted structurally: the skip check must appear inside the
    `certified` expression.
    """
    import ast
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(root, "scripts", "certify_sampler.py")).read()
    tree = ast.parse(src)
    found = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for k, v in zip(node.keys, node.values):
            if isinstance(k, ast.Constant) and k.value == "certified":
                calls = [n.func.id for n in ast.walk(v)
                         if isinstance(n, ast.Call)
                         and isinstance(n.func, ast.Name)]
                assert "any" in calls and "certification_skips" in calls, (
                    "`certified` does not consult the skip counters")
                found = True
    assert found, "no `certified` key found to check"


def test_every_skip_site_has_its_own_named_counter():
    """Each silent drop must be counted separately, not lumped or omitted.

    Codex found deck-mismatch and wrong-seat/phase drops still uncounted after
    the first pass; this pins all four so a new silent `continue` is visible.
    """
    import os
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = open(os.path.join(root, "scripts", "certify_sampler.py")).read()
    for key in ("toy_state_replay", "corpus_row_replay",
                "corpus_deck_mismatch", "corpus_wrong_seat_or_phase"):
        assert f'SKIPPED["{key}"] += 1' in src, f"{key} is never incremented"
