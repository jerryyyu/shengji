"""Profile one seeded MC round with the fast path active (dev aid).

    cd server && uv run python scripts/profile_fast_round.py [--pure]
"""

import cProfile
import pstats
import random
import sys

sys.path.insert(0, ".")
from shengji.engine import fast  # noqa: E402

if "--pure" not in sys.argv:
    assert fast.activate(), "extension not built"

from shengji.ai.env import play_round  # noqa: E402
from shengji.ai.mcbot import MCBot  # noqa: E402
from shengji.engine.game import Game  # noqa: E402

game = Game(random.Random(7))
pr = cProfile.Profile()
pr.enable()
play_round(game, [MCBot(seed=i) for i in range(4)])
pr.disable()
pstats.Stats(pr).sort_stats("cumulative").print_stats(35)
