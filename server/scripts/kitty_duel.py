"""Does the banker knowing its OWN burial actually help it play?

Re-run of the 2026-08-03 kitty experiment on fixed code. The first three
attempts were invalid: BANKER_KITTY had silently disabled banker search, so
they compared no-search against search (see
incidents/2026-08-03-banker-search-disabled.md).

Both arms are MCBot; they differ only in BANKER_KITTY. Mirrored, seeded
pairings so the duel reproduces exactly. Guards against a repeat of the
silent-fallback failure: every decision must sample a full set of worlds,
enforced by SHENGJI_STRICT_SAMPLING.

    uv run python scripts/kitty_duel.py [n_seeds] [seed0]
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("SHENGJI_STRICT_SAMPLING", "1")

sys.path.insert(0, ".")
from shengji.ai.mcbot import MCBot  # noqa: E402
from shengji.ai.tournament import play_pairing  # noqa: E402


class KittyOn(MCBot):
    BANKER_KITTY = True


class KittyOff(MCBot):
    BANKER_KITTY = False


def main() -> None:
    n_seeds = int(sys.argv[1]) if len(sys.argv) > 1 else 150
    seed0 = int(sys.argv[2]) if len(sys.argv) > 2 else 900_000
    print(f"kitty duel: BANKER_KITTY on vs off, {2 * n_seeds} rounds, "
          f"seed0={seed0}, strict sampling ON", flush=True)
    a, b = play_pairing(KittyOn, KittyOff, n_seeds, seed0)
    n = a + b
    pct = 100.0 * a / n if n else 0.0
    # Wilson 95% interval — the honest read on whether this beats a coin.
    z, p = 1.96, (a / n if n else 0.0)
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / denom
    print(f"RESULT BANKER_KITTY on vs off: {a}-{b} ({pct:.1f}%) n={n} "
          f"Wilson95=[{100 * (centre - half):.1f}%, {100 * (centre + half):.1f}%]",
          flush=True)
    if centre - half > 0.5:
        print("VERDICT: kitty knowledge helps (lower bound above 50%)")
    elif centre + half < 0.5:
        print("VERDICT: kitty knowledge HURTS (upper bound below 50%)")
    else:
        print("VERDICT: not distinguishable from 50% at this n")


if __name__ == "__main__":
    main()
