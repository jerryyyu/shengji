"""T3 ONLINE SCREEN — where should selective search be spent?

Every arm plays the SAME cheap policy (the v11 override on the production
numpy path) and differs ONLY in when it escalates to full MC:

  * full    — escalate always (the incumbent, `mc`)
  * v11     — escalate when the override's own predicted gain clears a bar
  * ncands  — escalate when the candidate count clears a bar
  * random  — escalate with fixed probability (the null)
  * none    — never escalate

The first version of this runner let the v11 arm play its learned pick while
ncands/random fell back to plain SmartBot, which confounded WHERE to search
with WHAT TO DO when not searching (Codex, 2026-08-04). One frozen cheap
policy is the whole point: any difference between arms is then attributable
to the gate.

Discipline this runner enforces rather than merely describing:
  * budgets matched on MEASURED ROLLOUTS, not call rate — search cost scales
    with candidate count, so a candidate-count gate deliberately selects
    expensive states;
  * an arm outside the frozen band is reported NOT COMPARABLE and the run
    exits non-zero;
  * impossible-world fallbacks (worlds buildable only by ignoring observed
    voids) are counted, and refused entirely under strict sampling;
  * PAIRED per-seed differences against the `full` arm, with uncertainty
    clustered by seed (the two flips of a seed share a deal and are not
    independent);
  * an exclusive per-run output file plus a manifest carrying the git SHA,
    checkpoint digest, arguments and environment — reruns cannot silently mix.

PRIMARY METRIC: paired signed level utility. Round win-rate is secondary.
This is a SCREEN: it can say "nothing is on the frontier" or "worth
confirming". It cannot confirm.

    uv run python scripts/t3_gate_screen.py [clusters] [seed0] [--replay FILE]
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import subprocess
import sys
import time

sys.path.insert(0, ".")

from shengji.ai.env import play_round        # noqa: E402
from shengji.ai.mcbot import MCBot           # noqa: E402
from shengji.ai.smart import SmartBot        # noqa: E402
from shengji.engine.game import Game         # noqa: E402
from shengji.rl.encode import encode_action, encode_obs  # noqa: E402

CKPT_NPZ = "snapshots_v11pair/ep07.npz"
OVERRIDE_MARGIN = 0.02        # frozen: the deployed rule
BAND = 0.15                   # +/- tolerance on the matched rollout budget
ARMS = ("full", "v11", "ncands", "random", "none")
# Disjoint, process-stable RNG streams per gate.
GATE_STREAM = {"full": 11, "v11": 23, "ncands": 37, "random": 53, "none": 71}

_NET = None


def net():
    """The PRODUCTION numpy path, loaded once — not a fresh Torch load per bot,
    which would make measured wall time meaningless as deployment latency."""
    global _NET
    if _NET is None:
        from shengji.rl.npnet import NpNet
        _NET = NpNet(CKPT_NPZ)
    return _NET


class Arm(SmartBot):
    """One frozen cheap policy + a gate that decides when to pay for search."""

    def __init__(self, gate: str, thr: float, seed: int):
        self.gate, self.thr = gate, thr
        self.mc = MCBot(seed=seed)
        # Gate randomness gets its OWN stream: sharing a seed with the world
        # sampler couples which states are searched to how they are sampled.
        # Offsets are FIXED INTEGERS, not hash() of a string — Python
        # randomizes string hashing per process, so the first version of this
        # line made the random arm irreproducible across runs. The replay gate
        # caught it immediately; the same bug class (hash-ordered iteration)
        # already cost this project a day on 2026-08-02.
        self.gate_rng = random.Random(seed * 1_000_003 + GATE_STREAM[gate])
        self.escalations = self.decisions = self.cheap_calls = 0
        self.net_secs = 0.0

    @property
    def rollouts(self):
        return self.mc.rollouts

    @property
    def search_calls(self):
        return self.mc.search_calls

    @property
    def search_secs(self):
        return self.mc.search_secs

    @property
    def impossible_worlds(self):
        return self.mc.impossible_worlds

    @property
    def rejected_worlds(self):
        return self.mc.rejected_worlds

    def _cheap(self, rnd, seat):
        """The frozen cheap policy: SmartBot + the v11 override. Returns
        (action, confidence) so a gate may reuse the same forward pass."""
        base = SmartBot.decide_play(self, rnd, seat)
        actions = self.mc._candidates(rnd, seat)
        if len(actions) <= 1:
            return base, 0.0
        key = sorted(base)
        try:
            i0 = next(i for i, a in enumerate(actions) if sorted(a) == key)
        except StopIteration:
            return base, 0.0
        actions = [actions[i0]] + actions[:i0] + actions[i0 + 1:]
        t0 = time.perf_counter()
        obs = encode_obs(rnd, seat)
        enc = [encode_action(a, rnd) for a in actions]
        d = net().value_candidates(obs, enc)
        d = [float(x) - float(d[0]) for x in d]
        self.net_secs += time.perf_counter() - t0
        self.cheap_calls += 1
        j = max(range(len(d)), key=lambda k: d[k])
        conf = d[j]
        return (actions[j] if conf > OVERRIDE_MARGIN else base), conf

    def _should_escalate(self, rnd, seat, conf, n_cands) -> bool:
        if self.gate == "full":
            return True
        if self.gate == "none":
            return False
        if self.gate == "v11":
            return conf > self.thr
        if self.gate == "ncands":
            return n_cands >= self.thr
        if self.gate == "random":
            return self.gate_rng.random() < self.thr
        raise ValueError(self.gate)

    def decide_play(self, rnd, seat):
        self.decisions += 1
        cheap, conf = self._cheap(rnd, seat)
        n_cands = len(self.mc._candidates(rnd, seat))
        if n_cands <= 1:
            return cheap
        if self._should_escalate(rnd, seat, conf, n_cands):
            self.escalations += 1
            return self.mc.decide_play(rnd, seat)
        return cheap


def run_arm(gate, thr, clusters, seed0, fh=None, run_id=""):
    recs = []
    t0 = time.perf_counter()
    for c in range(clusters):
        seed = seed0 + c
        for flip in (0, 1):
            a1, a2 = Arm(gate, thr, seed), Arm(gate, thr, seed + 500_000)
            b1 = MCBot(seed=seed + 1_000_000)
            b2 = MCBot(seed=seed + 1_500_000)
            pol = [a1, b1, a2, b2] if flip == 0 else [b1, a1, b2, a2]
            log = play_round(Game(random.Random(seed)), pol)
            a_team = 0 if flip == 0 else 1
            won = int(log.winner_team == a_team)
            rec = {
                "run": run_id, "arm": gate, "thr": thr, "seed": seed,
                "flip": flip, "won": won,
                "level_utility": (1 if won else -1) * max(1, int(log.level_change)),
                "rollouts": a1.rollouts + a2.rollouts,
                "search_calls": a1.search_calls + a2.search_calls,
                "escalations": a1.escalations + a2.escalations,
                "decisions": a1.decisions + a2.decisions,
                "cheap_calls": a1.cheap_calls + a2.cheap_calls,
                "impossible_worlds": a1.impossible_worlds + a2.impossible_worlds,
                "rejected_worlds": a1.rejected_worlds + a2.rejected_worlds,
            }
            timing = {"search_secs": round(a1.search_secs + a2.search_secs, 4),
                      "net_secs": round(a1.net_secs + a2.net_secs, 4)}
            recs.append(rec)
            if fh:
                fh.write(json.dumps({**rec, **timing}) + "\n")
        if c and c % 25 == 0:
            print(f"    {gate}: {2*c}/{2*clusters} rounds", flush=True)
    for r in recs:
        r["_wall"] = 0.0
    return recs, time.perf_counter() - t0


def totals(recs):
    return {
        "wins": sum(r["won"] for r in recs), "n": len(recs),
        "util": sum(r["level_utility"] for r in recs),
        "rollouts": sum(r["rollouts"] for r in recs),
        "escalations": sum(r["escalations"] for r in recs),
        "decisions": sum(r["decisions"] for r in recs),
        "impossible": sum(r["impossible_worlds"] for r in recs),
        "rejected": sum(r["rejected_worlds"] for r in recs),
    }


def paired_vs_full(arm_recs, full_recs):
    """Mean paired level-utility difference vs `full`, clustered BY SEED.

    The two flips of a seed share a deal, so treating 2*clusters rounds as
    independent understates the interval.
    """
    import math
    by_seed = {}
    for r in full_recs:
        by_seed.setdefault(r["seed"], [0, 0])[0] += r["level_utility"]
    for r in arm_recs:
        by_seed.setdefault(r["seed"], [0, 0])[1] += r["level_utility"]
    diffs = [b - a for a, b in by_seed.values()]
    n = len(diffs)
    if n < 2:
        return 0.0, 0.0
    m = sum(diffs) / n
    var = sum((d - m) ** 2 for d in diffs) / (n - 1)
    return m, 1.96 * math.sqrt(var / n)


def main() -> None:
    clusters = int(sys.argv[1]) if len(sys.argv) > 1 else 150
    seed0 = int(sys.argv[2]) if len(sys.argv) > 2 else 31_000_000

    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                         capture_output=True, text=True).stdout.strip()
    digest = hashlib.sha256(open(CKPT_NPZ, "rb").read()).hexdigest()[:16] \
        if os.path.exists(CKPT_NPZ) else "MISSING"
    run_id = f"t3_{int(time.time())}_{sha}"
    out = f"runs/logs/{run_id}.jsonl"
    manifest = {
        "run": run_id, "git": sha, "ckpt": CKPT_NPZ, "ckpt_sha256_16": digest,
        "clusters": clusters, "seed0": seed0, "arms": list(ARMS),
        "override_margin": OVERRIDE_MARGIN, "band": BAND,
        "strict_sampling": bool(os.environ.get("SHENGJI_STRICT_SAMPLING")),
        "fast_engine": bool(os.environ.get("SHENGJI_FAST")),
        "started": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    with open(f"runs/logs/{run_id}.manifest.json", "x") as mf:
        json.dump(manifest, mf, indent=2)
    print(json.dumps(manifest, indent=2), flush=True)

    # ---- calibrate gated arms onto one measured rollout budget ----
    pilot = max(6, clusters // 12)
    full_pilot, _ = run_arm("full", 0.0, pilot, seed0 - 900_000)
    target = totals(full_pilot)["rollouts"] * 0.30
    print(f"\npilot: full spent {totals(full_pilot)['rollouts']} rollouts "
          f"=> gated target {target:.0f} (+/-{100*BAND:.0f}%)", flush=True)

    thrs = {"v11": 0.02, "ncands": 8, "random": 0.12}
    for gate in ("v11", "ncands", "random"):
        for _ in range(6):
            recs, _ = run_arm(gate, thrs[gate], pilot, seed0 - 900_000)
            ratio = totals(recs)["rollouts"] / max(target, 1)
            print(f"  {gate} thr={thrs[gate]:.4g}: {ratio:.2f}x target",
                  flush=True)
            if abs(ratio - 1) <= BAND:
                break
            over = ratio > 1
            if gate == "ncands":
                thrs[gate] = max(2, thrs[gate] + (1 if over else -1))
            elif gate == "v11":          # higher bar => LESS search
                thrs[gate] *= 1.5 if over else 0.7
            else:                        # random: higher p => MORE search
                thrs[gate] = min(1.0, thrs[gate] * (0.7 if over else 1.5))

    print(f"\ncalibrated: {thrs}\nMEASURING {2*clusters} rounds/arm -> {out}\n",
          flush=True)

    results = {}
    with open(out, "x") as fh:
        for gate in ARMS:
            thr = thrs.get(gate, 0.0)
            print(f"  arm {gate} (thr={thr:.4g})", flush=True)
            recs, wall = run_arm(gate, thr, clusters, seed0, fh, run_id)
            results[gate] = (recs, wall)

    full_recs = results["full"][0]
    ft = totals(full_recs)
    budget = ft["rollouts"] * 0.30
    print(f"\n{'arm':8} {'win%':>6} {'util':>7} {'paired vs full':>22} "
          f"{'rollouts':>10} {'band':>7} {'esc%':>6} {'wall s':>8}")
    out_of_band = []
    for gate in ARMS:
        recs, wall = results[gate]
        t = totals(recs)
        m, ci = paired_vs_full(recs, full_recs)
        if gate in ("full", "none"):
            band = "  ref"
        else:
            ratio = t["rollouts"] / max(budget, 1)
            band = f"{ratio:6.2f}x"
            if abs(ratio - 1) > BAND:
                out_of_band.append(gate)
        esc = 100 * t["escalations"] / max(t["decisions"], 1)
        print(f"{gate:8} {100*t['wins']/t['n']:5.1f}% {t['util']:+7d} "
              f"{m:+8.3f} +/- {ci:6.3f}  {t['rollouts']:10d} {band:>7} "
              f"{esc:5.1f}% {wall:8.1f}")

    imp = sum(totals(r)["impossible"] for r, _ in results.values())
    rej = sum(totals(r)["rejected"] for r, _ in results.values())
    print(f"\nimpossible worlds USED: {imp}"
          + ("" if imp == 0 else "  <-- built by IGNORING observed voids")
          + f"   |   REJECTED under strict sampling: {rej}")
    print("PRIMARY = paired signed level utility vs full, clustered by seed.")
    print(f"manifest: runs/logs/{run_id}.manifest.json")
    if out_of_band:
        print(f"\nNOT COMPARABLE — outside the +/-{100*BAND:.0f}% compute band: "
              f"{', '.join(out_of_band)}")
        sys.exit(2)


if __name__ == "__main__":
    main()
