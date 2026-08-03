"""A/A parity guards: optimizations must never change game outcomes.

Two layers (PERF.md rule: correctness of generated data outranks speed):
1. Optimized-vs-reference: every cached/fast-path primitive must equal
   its uncached/validated reference on the same inputs.
2. Golden histories: full seeded rounds must reproduce byte-identical
   play sequences against goldens recorded at adoption time. Any engine
   or bot change that alters these is either a bug or a deliberate
   behavior change — if deliberate, regenerate goldens IN THE SAME
   COMMIT and say why in its message.

Regenerate goldens:  uv run python tests/test_engine_parity.py --regen
"""

import json
import random
import sys
from pathlib import Path

sys.path.insert(0, ".")
from shengji.ai.env import play_round  # noqa: E402
from shengji.ai.heuristic import HeuristicBot  # noqa: E402
from shengji.ai.mcbot import MCBot  # noqa: E402
from shengji.ai.smart import SmartBot  # noqa: E402
from shengji.engine import combos  # noqa: E402
from shengji.engine.cards import make_deck  # noqa: E402
from shengji.engine.game import Game  # noqa: E402

GOLDEN = Path(__file__).parent / "golden_histories.json"


class _FastMC(MCBot):
    N_DETERMINIZATIONS = 3  # keep the test fast; determinism is what matters


def _play(bot_factory, seed):
    game = Game(random.Random(seed))
    bots = [bot_factory(i) for i in range(4)]
    play_round(game, bots)
    return [[p.seat, sorted(p.cards)] for t in game.round.history
            for p in t.plays]


def _histories():
    return {
        "heuristic-11": _play(lambda i: HeuristicBot(), 11),
        "smart-12": _play(lambda i: SmartBot(), 12),
        "mc-13": _play(lambda i: _FastMC(seed=i), 13),
    }


def test_cached_primitives_match_reference():
    rng = random.Random(0)
    game = Game(random.Random(99))
    play_round(game, [HeuristicBot() for _ in range(4)])  # deal => ordering
    o = game.round.ordering
    deck = make_deck()
    for _ in range(300):
        hand = rng.sample(deck, rng.randint(2, 12))
        suits = {}
        for c in hand:
            suits.setdefault(o.eff_suit(c), []).append(c)
        for cards in suits.values():
            assert combos.decompose(cards, o) == combos._decompose_uncached(
                cards, o)
            for k in (2, 3):
                assert (combos.find_tractor_runs(cards, o, k)
                        == combos._find_tractor_runs_uncached(cards, o, k))


def test_golden_histories():
    assert GOLDEN.exists(), "run --regen once to record goldens"
    golden = json.loads(GOLDEN.read_text())
    live = _histories()
    for name, hist in golden.items():
        assert live[name] == hist, f"engine behavior changed: {name}"


if __name__ == "__main__" and "--regen" in sys.argv:
    GOLDEN.write_text(json.dumps(_histories()))
    print(f"goldens written: {GOLDEN}")
