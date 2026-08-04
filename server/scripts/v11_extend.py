"""Extension for the v11pair anchors on FRESH seeds (no reuse with 3.3M).

First block: 57.8% vs smart (Wilson [50.5, 64.8] — lower bound barely above
50) and 52.2% vs mc. Borderline results get extended before they are claimed;
that rule exists because of the v5-hybrid mirage and the vleaf 60% headline.
"""
import sys
sys.path.insert(0, ".")
from shengji.ai.registry import make_bot          # noqa: E402
from shengji.ai.tournament import play_pairing    # noqa: E402


def wilson(w, n):
    z, p = 1.96, w / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return p, c - h, c + h


opp = sys.argv[1]
n = int(sys.argv[2]) if len(sys.argv) > 2 else 150
seed0 = int(sys.argv[3]) if len(sys.argv) > 3 else 8_800_000
print(f"EXTENSION rl-override-v11pair vs {opp}, {2*n} rounds, seed0={seed0}",
      flush=True)
a, b = play_pairing(lambda **k: make_bot("rl-override-v11pair"),
                    lambda **k: make_bot(opp), n, seed0)
p, lo, hi = wilson(a, a + b)
print(f"RESULT v11pair vs {opp}: {a}-{b} ({100*p:.1f}%) n={a+b} "
      f"Wilson95=[{100*lo:.1f}%, {100*hi:.1f}%]", flush=True)
