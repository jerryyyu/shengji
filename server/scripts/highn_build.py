"""Build the HIGH-N DIAGNOSTIC SET — raw states + independently evaluated
candidate values with standard errors.

Why this exists (Codex, 2026-08-04): every encoded shard we have carries the
teacher's own finite-world estimates, so `max_i Q_i` inherits a winner's-curse
bias that GROWS with candidate count. That bias silently contaminated the gate
screen, and it blocks three separate lines — an unbiased stakes/oracle
estimate, the representation diagnostic, and the ceiling-vs-undertrained
data-scaling study. None can be fixed from the existing shards.

Why it matters for the GOAL (beating mc): a net distilled from mc's own
N=10/30 preferences is trained to imitate mc, so it cannot systematically
exceed it. Labels from a much larger search ARE better than the deployed
mc(N=10) — this set is the first thing in the project that is stronger than
the thing we are trying to beat.

Each record stores the state in REBUILDABLE raw form (deck, banker, trump
rank, declarations, burial, plays so far) rather than an encoding, so it can
be re-evaluated later at any N, under any encoder, with any policy.

Per candidate it stores mean value, standard error, and the world count, so a
later analysis can (a) correct for selection optimism and (b) keep only states
where the best/baseline gap is significant.

    uv run python scripts/highn_build.py [n_states] [n_worlds] [seed0] [out]
"""
from __future__ import annotations

import json
import math
import random
import sys
import time

sys.path.insert(0, ".")

from shengji.ai.heuristic import HeuristicBot   # noqa: E402
from shengji.ai.mcbot import MCBot              # noqa: E402
from shengji.ai.memory import Memory            # noqa: E402
from shengji.ai.smart import SmartBot           # noqa: E402
from shengji.engine.game import Game            # noqa: E402


def evaluate_high_n(rnd, seat, n_worlds: int, seed: int):
    """Per-candidate (mean, stderr) over `n_worlds` INDEPENDENT determinizations.

    Deliberately not MCBot.decide_play: we need the per-world spread, and the
    worlds must be shared across candidates (paired sampling) so the
    DIFFERENCES between candidates are far better resolved than each absolute
    value is.
    """
    bot = MCBot(seed=seed)
    cands = bot._candidates(rnd, seat)
    if len(cands) < 2:
        return None
    mem = Memory(rnd, seat, own_kitty=True)
    i_attack = rnd.is_attacker(seat)
    # Keep the full worlds x candidates matrix. Candidates share worlds, so the
    # DIFFERENCE between two candidates is far better resolved than either
    # absolute value: on a smoke run the absolute SE was ~3.9 while real gaps
    # were ~2, which would declare nothing significant. Paired differencing is
    # the whole reason to sample worlds jointly, and throwing it away by
    # combining marginal SEs wastes the sampling design.
    rows: list[list[float]] = []
    for _ in range(n_worlds):
        sampled = bot._sample_hands(rnd, seat, mem)
        if sampled is None:
            continue
        hands, buried = sampled
        row = []
        for cand in cands:
            v = bot._score(bot._rollout(rnd, seat, hands, buried, cand))
            row.append(v if i_attack else -v)
        rows.append(row)
    used = len(rows)
    if used < 2:
        return None
    k = len(cands)
    means = [sum(r[i] for r in rows) / used for i in range(k)]
    ses = []
    for i in range(k):
        var = sum((r[i] - means[i]) ** 2 for r in rows) / (used - 1)
        ses.append(math.sqrt(var / used))
    # Paired SE of (candidate i - candidate 0), the quantity that actually
    # decides an override.
    paired_se = []
    for i in range(k):
        d = [r[i] - r[0] for r in rows]
        md = sum(d) / used
        var = sum((x - md) ** 2 for x in d) / (used - 1)
        paired_se.append(math.sqrt(var / used))
    return cands, means, ses, paired_se, used


def play_and_sample(seed: int, n_worlds: int, want: int, fh, stats):
    """Play one round with mixed policies, evaluating sampled decisions."""
    game = Game(random.Random(seed))
    rnd = game.start_round()
    hb = HeuristicBot()
    # Mixed table so the state distribution is not one policy's idiosyncrasy.
    pol = [MCBot(seed=seed + 7), SmartBot(), MCBot(seed=seed + 11), SmartBot()]
    declared = []
    while rnd.phase == "deal":
        s, _, _ = rnd.deal_next()
        cards = pol[s].decide_declare(rnd, s)
        if cards:
            rnd.declare(s, cards)
            declared.append({"seat": s, "cards": list(cards)})
    for s in range(4):
        cards = pol[s].decide_declare(rnd, s, final=True)
        if cards:
            rnd.declare(s, cards)
            declared.append({"seat": s, "cards": list(cards)})
    rnd.finalize_declare()
    assert rnd.banker is not None
    buried = pol[rnd.banker].decide_bury(rnd, rnd.banker)
    rnd.bury(rnd.banker, buried)

    setup = {"deck": list(rnd.deck), "banker": rnd.banker,
             "trump_rank": rnd.trump_rank, "declarations": declared,
             "buried": list(buried)}
    plays: list[dict] = []
    rng = random.Random(seed ^ 0x5EED)
    n_saved = 0
    while rnd.phase == "play" and n_saved < want:
        s = rnd.turn
        # Sample ~1 in 3 decisions: consecutive decisions in one round are
        # highly correlated, so taking every one buys little diversity.
        take = rng.random() < 0.34
        if take:
            t0 = time.perf_counter()
            got = evaluate_high_n(rnd, s, n_worlds, seed * 31 + len(plays))
            if got is not None:
                cands, means, ses, paired_se, used = got
                order = sorted(range(len(cands)), key=lambda i: -means[i])
                best = order[0]
                gap = means[best] - means[0]
                se_gap = paired_se[best]      # paired, not marginal
                fh.write(json.dumps({
                    "seed": seed, "ply": len(plays), "seat": s,
                    "setup": setup, "plays": plays,
                    "candidates": [list(c) for c in cands],
                    "mean": [round(m, 4) for m in means],
                    "stderr": [round(e, 4) for e in ses],
                    "paired_se": [round(e, 4) for e in paired_se],
                    "worlds": used,
                    "best": best, "gap": round(gap, 4),
                    "gap_se": round(se_gap, 4),
                    "significant": bool(gap > 2 * se_gap),
                    "secs": round(time.perf_counter() - t0, 2)}) + "\n")
                fh.flush()
                n_saved += 1
                stats["saved"] += 1
                stats["sig"] += int(gap > 2 * se_gap)
        mv = pol[s].decide_play(rnd, s)
        plays.append({"seat": s, "cards": list(mv)})
        rnd.play(s, mv)
    return n_saved


def main() -> None:
    n_states = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    n_worlds = int(sys.argv[2]) if len(sys.argv) > 2 else 200
    seed0 = int(sys.argv[3]) if len(sys.argv) > 3 else 61_000_000
    out = sys.argv[4] if len(sys.argv) > 4 else "rl_data/highn_diag.jsonl"

    print(f"HIGH-N DIAGNOSTIC SET: {n_states} states at N={n_worlds} worlds, "
          f"seeds {seed0}+ -> {out}", flush=True)
    print("  paired worlds across candidates; storing mean, stderr, and the "
          "rebuildable raw state", flush=True)
    stats = {"saved": 0, "sig": 0}
    t0 = time.perf_counter()
    with open(out, "a") as fh:
        r = 0
        while stats["saved"] < n_states:
            play_and_sample(seed0 + r, n_worlds,
                            min(4, n_states - stats["saved"]), fh, stats)
            r += 1
            if stats["saved"] and r % 5 == 0:
                el = time.perf_counter() - t0
                print(f"  {stats['saved']}/{n_states} states "
                      f"({100*stats['sig']/max(stats['saved'],1):.0f}% with a "
                      f"significant best-vs-baseline gap), "
                      f"{el/60:.1f}m", flush=True)
    el = time.perf_counter() - t0
    print(f"DONE {stats['saved']} states in {el/60:.1f}m; "
          f"{stats['sig']} ({100*stats['sig']/max(stats['saved'],1):.0f}%) have "
          f"a best-vs-baseline gap exceeding 2 SE", flush=True)


if __name__ == "__main__":
    main()
