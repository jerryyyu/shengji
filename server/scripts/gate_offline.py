"""Offline gate T2/T3 (Codex overnight plan): is v11's stakes signal actually
a better place to spend search than trivial alternatives?

The online screen showed mc-gate-v11pair at 53.3% vs mc for ~55% of the
wall-clock. That is one duel at n=300 with a timing number extrapolated from a
separate run, so it is a screen, not a result. Before it earns a 1,000-cluster
confirmation it has to beat the obvious cheap gates OFFLINE, at the SAME
search rate, on data the net never trained on.

The quantity that matters is MISSED OPPORTUNITY. Searching a state costs
compute and yields (approximately) the teacher's best action; not searching
keeps SmartBot's candidate 0 and forfeits Q(best) - Q(a0). So for a fixed
budget of searched states, a gate is good exactly insofar as it spends that
budget on the states where keeping a0 is most expensive.

Gates compared at matched rate:
  * v11      — rank by the net's predicted gain over candidate 0
  * random   — the null: any gate must beat this or it knows nothing
  * ncands   — rank by candidate count, i.e. "complex decisions matter"
  * oracle   — rank by TRUE forfeited value; the ceiling, not a contender

Reported per block at several matched rates.

LIMITS, stated because this screen was over-read once already (Codex,
2026-08-04):
  * `forfeit` uses gen-v4 teacher estimates, and taking max_i Q_i over
    candidates carries a winner's-curse bias that GROWS with candidate count —
    so candidate count is mechanically correlated with the very target used to
    judge it. Neither the ncands result nor the oracle headroom is truth
    without independent higher-N labels.
  * Matching the FRACTION OF STATES searched is not matching compute: search
    cost scales with candidate count, so a candidate-count gate deliberately
    picks expensive states and 12% vs 12% is not equal work.
  * The blocks are array_split over two validation shards, not independent
    shard blocks, and there is no calibrate-on-A / report-on-B split.
  * Candidate-count ties are broken by input order.
This is a SCREEN (runbook stage T2). It can say "not earned"; it cannot say
"the learned signal is explained"

    uv run python scripts/gate_offline.py [n_states] [blocks]
"""
from __future__ import annotations

import sys

import numpy as np

sys.path.insert(0, ".")


def load_scored(limit: int):
    """(forfeit, predicted_gain, n_candidates) per valued held-out state."""
    from scripts.residual_eval import load_states, val_shards
    from shengji.rl.model import load_any_net

    net = load_any_net("snapshots_v11pair/ep07.pt")
    rows = []
    for ob, enc, qt, is_choice in load_states(val_shards("rl_data/gen_v4_all"),
                                              limit):
        if is_choice:
            continue
        qt = np.asarray(qt, dtype=np.float64)
        qp = np.asarray(net.value_candidates(ob, list(enc)), dtype=np.float64)
        gain = qp - qp[0]
        rows.append((float(qt.max() - qt[0]),          # forfeited if we skip
                     float(gain.max()),                # what v11 predicts
                     len(qt)))                         # candidate count
    return np.array(rows, dtype=np.float64)


def residual(forfeit: np.ndarray, score: np.ndarray, k: int) -> float:
    """Total forfeited value after searching the top-k states by `score`."""
    if k <= 0:
        return float(forfeit.sum())
    idx = np.argsort(-score)[:k]
    keep = np.ones(len(forfeit), dtype=bool)
    keep[idx] = False
    return float(forfeit[keep].sum())


def main() -> None:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 3000
    n_blocks = int(sys.argv[2]) if len(sys.argv) > 2 else 3

    rows = load_scored(limit)
    print(f"{len(rows)} valued held-out states, {n_blocks} blocks", flush=True)
    blocks = np.array_split(rows, n_blocks)

    rng = np.random.default_rng(20260804)
    rates = (0.05, 0.12, 0.25)
    verdicts = []

    for rate in rates:
        print(f"\n=== search rate {100 * rate:.0f}% of states ===")
        print("  block |    v11 |  random |  ncands |  oracle | v11 vs random"
              " | v11 vs ncands")
        per_block = []
        for bi, b in enumerate(blocks):
            forfeit, gain, ncand = b[:, 0], b[:, 1], b[:, 2]
            k = int(round(rate * len(b)))
            base = float(forfeit.sum())
            r_v11 = residual(forfeit, gain, k)
            r_rand = float(np.mean([residual(forfeit, rng.random(len(b)), k)
                                    for _ in range(25)]))
            r_ncand = residual(forfeit, ncand.astype(float), k)
            r_oracle = residual(forfeit, forfeit, k)
            # Reduction in missed opportunity, relative to each rival.
            red_rand = 100 * (r_rand - r_v11) / max(r_rand, 1e-9)
            red_ncand = 100 * (r_ncand - r_v11) / max(r_ncand, 1e-9)
            per_block.append((red_rand, red_ncand))
            print(f"  {bi:5d} | {r_v11:6.0f} | {r_rand:7.0f} | {r_ncand:7.0f} "
                  f"| {r_oracle:7.0f} | {red_rand:+12.1f}% | {red_ncand:+12.1f}%"
                  f"   (skip-all {base:.0f})")
        ok_rand = all(r > 15.0 for r, _ in per_block)
        ok_ncand = all(n > 15.0 for _, n in per_block)
        verdicts.append((rate, ok_rand, ok_ncand))
        print(f"  >=15% better than random in EVERY block: {ok_rand}")
        print(f"  >=15% better than ncands in EVERY block: {ok_ncand}")

    print("\nGATE (Codex T3): v11 must beat random AND candidate-count by >=15%"
          " consistently.")
    passed = any(a and b for _, a, b in verdicts)
    for rate, a, b in verdicts:
        print(f"  rate {100 * rate:>3.0f}%: random {'PASS' if a else 'FAIL'}, "
              f"ncands {'PASS' if b else 'FAIL'}")
    print("VERDICT:", "PASS — the confirmation run is earned"
          if passed else
          "FAIL — do not spend a 1,000-cluster run on this gate")


if __name__ == "__main__":
    main()
