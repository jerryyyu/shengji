"""T3 ONLINE SCREEN — preregistered, per Codex 2026-08-04 07:31.

Question: when search is spent selectively, does WHERE you spend it need a
learned signal, or does a free rule do as well?

Arms, all playing SmartBot+override as the cheap path and escalating to full
MC on gated states:
  * full        — search every decision (the incumbent, `mc`)
  * v11         — escalate when the net's predicted gain clears a threshold
  * ncands      — escalate when the candidate count clears a threshold
  * random      — escalate with fixed probability (the null)
  * none        — never escalate (plain v11pair override, no search)

DESIGN, fixed before running:
  * Same 150 seed clusters per arm, mirrored (both seatings), so deal luck is
    controlled and arms are directly comparable seed by seed.
  * Budget is matched on MEASURED SEARCH WORK (rollouts), not call rate:
    search cost scales with candidates and worlds, so a candidate-count gate
    deliberately picks expensive states and equal call rates are NOT equal
    compute. Thresholds are calibrated in a pilot to land the gated arms
    within +/-15% of the same rollout budget; the achieved budget is reported
    with the result, and an arm that misses the band is reported as such
    rather than quietly compared.
  * Per-seed JSONL: seed, flip, arm, winner, signed level utility, search
    calls, rollouts, search seconds, fallbacks.
  * PRIMARY METRIC: paired signed LEVEL UTILITY (Codex's ruling). Round
    win-rate is reported as secondary.

This is a SCREEN. It can say "no arm is on the frontier" or "an arm is worth
confirming". It cannot confirm anything by itself.

    uv run python scripts/t3_gate_screen.py [clusters] [seed0]
"""
from __future__ import annotations

import json
import random
import sys
import time

sys.path.insert(0, ".")

from shengji.ai.env import play_round        # noqa: E402
from shengji.ai.mcbot import MCBot           # noqa: E402
from shengji.ai.registry import make_bot     # noqa: E402
from shengji.ai.smart import SmartBot        # noqa: E402
from shengji.engine.game import Game         # noqa: E402
from shengji.rl.encode import encode_action, encode_obs  # noqa: E402

OUT = "runs/logs/t3_gate_screen.jsonl"
CKPT = "snapshots_v11pair/ep07.pt"


class GatedBot(SmartBot):
    """SmartBot + learned override, escalating to MC when `gate` says so."""

    def __init__(self, gate: str, thr: float, seed: int | None = None):
        self.gate, self.thr = gate, thr
        self.rng = random.Random(seed)
        self.mc = MCBot(seed=seed)
        self.escalations = 0
        self.decisions = 0
        from shengji.rl.model import load_any_net
        self.net = load_any_net(CKPT) if gate in ("v11", "none") else None
        self._ballot = MCBot(seed=seed)

    # cumulative work, read after the round
    @property
    def rollouts(self) -> int:
        return self.mc.rollouts

    @property
    def search_calls(self) -> int:
        return self.mc.search_calls

    @property
    def search_secs(self) -> float:
        return self.mc.search_secs

    def _override(self, rnd, seat, actions, base):
        if self.net is None:
            return base
        obs = encode_obs(rnd, seat)
        enc = [encode_action(a, rnd) for a in actions]
        d = self.net.value_candidates(obs, enc)
        d = [float(x) - float(d[0]) for x in d]
        j = max(range(len(d)), key=lambda k: d[k])
        return (actions[j] if d[j] > 0.02 else base), max(d)

    def decide_play(self, rnd, seat):
        self.decisions += 1
        if self.gate == "full":
            return self.mc.decide_play(rnd, seat)
        base = SmartBot.decide_play(self, rnd, seat)
        actions = self._ballot._candidates(rnd, seat)
        if len(actions) <= 1:
            return base
        key = sorted(base)
        try:
            i0 = next(i for i, a in enumerate(actions) if sorted(a) == key)
        except StopIteration:
            return base
        actions = [actions[i0]] + actions[:i0] + actions[i0 + 1:]

        if self.gate == "v11":
            pick, conf = self._override(rnd, seat, actions, base)
            if conf > self.thr:
                self.escalations += 1
                return self.mc.decide_play(rnd, seat)
            return pick
        if self.gate == "none":
            return self._override(rnd, seat, actions, base)[0]
        if self.gate == "ncands":
            if len(actions) >= self.thr:
                self.escalations += 1
                return self.mc.decide_play(rnd, seat)
            return base
        if self.gate == "random":
            if self.rng.random() < self.thr:
                self.escalations += 1
                return self.mc.decide_play(rnd, seat)
            return base
        raise ValueError(self.gate)


def run_arm(gate: str, thr: float, clusters: int, seed0: int, fh=None):
    wins = losses = 0
    util = 0
    rollouts = calls = 0
    secs = 0.0
    t0 = time.perf_counter()
    for c in range(clusters):
        seed = seed0 + c
        for flip in (0, 1):
            a1 = GatedBot(gate, thr, seed)
            a2 = GatedBot(gate, thr, seed + 500_000)
            b1 = make_bot("mc", seed=seed + 1_000_000)
            b2 = make_bot("mc", seed=seed + 1_500_000)
            pol = [a1, b1, a2, b2] if flip == 0 else [b1, a1, b2, a2]
            game = Game(random.Random(seed))
            log = play_round(game, pol)
            a_team = 0 if flip == 0 else 1
            won = log.winner_team == a_team
            signed = (1 if won else -1) * max(1, int(log.level_change))
            wins += won
            losses += not won
            util += signed
            for bot in (a1, a2):
                rollouts += bot.rollouts
                calls += bot.search_calls
                secs += bot.search_secs
            if fh:
                fh.write(json.dumps({
                    "arm": gate, "thr": thr, "seed": seed, "flip": flip,
                    "won": int(won), "level_utility": signed,
                    "rollouts": a1.rollouts + a2.rollouts,
                    "search_calls": a1.search_calls + a2.search_calls,
                    "search_secs": round(a1.search_secs + a2.search_secs, 4),
                    "escalations": a1.escalations + a2.escalations,
                    "decisions": a1.decisions + a2.decisions}) + "\n")
        if c and c % 25 == 0:
            print(f"    {gate}: {2*c}/{2*clusters} rounds, "
                  f"{wins}-{losses}, util {util:+d}", flush=True)
    return {"arm": gate, "thr": thr, "wins": wins, "losses": losses,
            "util": util, "rollouts": rollouts, "calls": calls,
            "secs": round(secs, 1), "wall": round(time.perf_counter() - t0, 1)}


def main() -> None:
    clusters = int(sys.argv[1]) if len(sys.argv) > 1 else 150
    seed0 = int(sys.argv[2]) if len(sys.argv) > 2 else 31_000_000

    print("T3 SCREEN — pilot: calibrating gates to a matched ROLLOUT budget",
          flush=True)
    pilot = max(8, clusters // 12)
    full = run_arm("full", 0.0, pilot, seed0 - 900_000)
    target = full["rollouts"] * 0.30      # aim gated arms near 30% of full
    print(f"  full: {full['rollouts']} rollouts over {2*pilot} rounds "
          f"=> target {target:.0f} for gated arms", flush=True)

    thrs = {"v11": 0.02, "ncands": 8, "random": 0.12}
    for gate in ("v11", "ncands", "random"):
        for _ in range(4):
            r = run_arm(gate, thrs[gate], pilot, seed0 - 900_000)
            ratio = r["rollouts"] / max(target, 1)
            print(f"  {gate} thr={thrs[gate]}: {r['rollouts']} rollouts "
                  f"({ratio:.2f}x target)", flush=True)
            if 0.85 <= ratio <= 1.15:
                break
            # Direction differs by gate: for v11 and ncands a HIGHER threshold
            # means FEWER escalations, but for random a higher probability
            # means MORE. Getting this backwards drove the random arm away
            # from the budget instead of toward it.
            too_much = ratio > 1
            if gate == "ncands":
                thrs[gate] = max(2, thrs[gate] + (1 if too_much else -1))
            elif gate == "v11":
                thrs[gate] *= 1.6 if too_much else 0.65
            else:  # random: probability of escalating
                thrs[gate] = min(1.0, thrs[gate] * (0.65 if too_much else 1.6))

    print(f"\ncalibrated thresholds: {thrs}", flush=True)
    print(f"MEASURING {2*clusters} rounds per arm, seeds {seed0}+\n", flush=True)

    results = []
    budget_target = target * (clusters / pilot)   # scale the pilot budget
    with open(OUT, "a") as fh:
        for gate, thr in [("full", 0.0), ("v11", thrs["v11"]),
                          ("ncands", thrs["ncands"]),
                          ("random", thrs["random"]), ("none", 0.0)]:
            print(f"  arm {gate} (thr={thr})", flush=True)
            results.append(run_arm(gate, thr, clusters, seed0, fh))

    n = 2 * clusters
    print(f"\n{'arm':8} {'win%':>6} {'level util':>11} {'rollouts':>10} "
          f"{'vs budget':>10} {'search s':>9} {'wall s':>8}  comparable")
    for r in results:
        if r["arm"] == "full":
            band, ok = "  (ref)", "reference"
        elif r["arm"] == "none":
            band, ok = "  (zero)", "reference"
        else:
            ratio = r["rollouts"] / max(budget_target, 1)
            band = f"{ratio:9.2f}x"
            ok = "YES" if 0.85 <= ratio <= 1.15 else "NO — OUT OF BAND"
        print(f"{r['arm']:8} {100*r['wins']/n:5.1f}% {r['util']:+11d} "
              f"{r['rollouts']:10d} {band:>10} {r['secs']:9.1f} "
              f"{r['wall']:8.1f}  {ok}")
    print("\nPRIMARY = paired signed level utility. Budgets are matched on "
          "measured ROLLOUTS, not call rate. An arm marked OUT OF BAND spent "
          "materially different compute and must NOT be read as a comparison.")
    print(f"per-seed records: {OUT}")


if __name__ == "__main__":
    main()
