"""mc-gate-v11pair vs mc: strength AND wall-clock, since the whole claim is
"near-mc strength at a fraction of the compute". Reporting one without the
other would be meaningless.
"""
import sys, time
sys.path.insert(0, ".")
from shengji.ai.registry import make_bot          # noqa: E402
from shengji.ai.tournament import play_pairing    # noqa: E402


def wilson(w, n):
    z, p = 1.96, w / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return p, c - h, c + h


n = int(sys.argv[1]) if len(sys.argv) > 1 else 150
seed0 = int(sys.argv[2]) if len(sys.argv) > 2 else 5_700_000
print(f"gate duel: mc-gate-v11pair vs mc, {2*n} rounds, seed0={seed0}", flush=True)
t0 = time.time()
a, b = play_pairing(lambda **k: make_bot("mc-gate-v11pair"),
                    lambda **k: make_bot("mc"), n, seed0)
gate_t = time.time() - t0
p, lo, hi = wilson(a, a + b)
print(f"RESULT gate vs mc: {a}-{b} ({100*p:.1f}%) n={a+b} "
      f"Wilson95=[{100*lo:.1f}%, {100*hi:.1f}%]  wall={gate_t/60:.1f}m", flush=True)

t0 = time.time()
play_pairing(lambda **k: make_bot("mc"), lambda **k: make_bot("mc"),
             max(n // 4, 10), seed0 + 777)
mc_t = (time.time() - t0) * (n / max(n // 4, 10))
print(f"TIMING all-mc equivalent wall={mc_t/60:.1f}m  => gate table runs at "
      f"{100*gate_t/mc_t:.0f}% of an all-mc table", flush=True)
