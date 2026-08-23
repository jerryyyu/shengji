"""THE evaluator, as a library. Every strength claim goes through this.

Three claims died in one day — vleaf 60%, v11pair 52%, root-prior racing 54.8%
— and none of them died from a bad idea. They died because a screen on
UNPAIRED blocks looked good and several blocks agreeing was read as
reproduction. Rounds inside a mirrored pair, and inside a seed cluster, are
correlated; binomial intervals do not know that, so agreeing blocks can be
correlated draws from a distribution wide enough to produce them by luck.

What this enforces, rather than describes:

  * the arm, its CONTROL, and an opponent-vs-opponent reference all play the
    SAME mirrored deals — a control on different deals proves nothing;
  * the primary statistic is PAIRED per-seed level utility, clustered BY SEED,
    because the two flips of a seed share a deal;
  * a bar must be declared BEFORE the run and is recorded in the manifest — a
    bar chosen after seeing the number is not a bar;
  * the manifest records the git SHA, whether the tree was DIRTY, the digest of
    the CLI *and of this module*, and of every checkpoint, so a run cannot
    claim provenance it does not have;
  * per-seed/flip records go to an exclusive file that reruns cannot mix into;
  * the verdict is CONFIRMED or NOT CONFIRMED. There is no "promising".

This lives in the package rather than in `scripts/` because six duel runners
had each grown their own copy of seed handling and interval arithmetic, and a
seed-dropping lambda survived in five of them at once. Seeds, manifests,
contrasts, counters and sharding exist here once.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import random
import re
import subprocess
import time
from dataclasses import dataclass, field

from .ai.env import play_round
from .ai.registry import make_bot
from .engine.game import Game


def digest(path: str | None) -> str | None:
    if not path or not os.path.exists(path):
        return None
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()[:16]


def arm_ballots(names) -> dict:
    """Which ballot each arm enumerates, recorded so a mismatch is visible.

    Every failure here is fatal. An earlier version swallowed a construction
    error with `continue` (silently dropping an arm from the manifest) and fell
    back to "unknown" otherwise. Codex showed the result was worse than
    useless: `smart`, `heuristic`, `mc` and the narrow historical
    `mc-20260802am` all reported the same ballot, so the manifest looked
    authoritative while being false. A manifest that cannot establish what was
    on the ballot has not recorded the experiment.
    """
    from .engine.ballot import ballot_for_policy
    out = {}
    for n in names:
        try:
            out[n] = str(ballot_for_policy(n))
        except Exception as exc:
            raise ProtocolFailure(
                f"cannot determine the ballot for arm {n!r}: "
                f"{type(exc).__name__}: {exc}. An experiment whose action sets "
                f"are unknown cannot support a strength claim.") from exc
    return out


class ProtocolFailure(RuntimeError):
    """A condition that makes the run incapable of supporting a claim."""


def counters(bots) -> dict:
    return {"rollouts": sum(getattr(b, "rollouts", 0) for b in bots),
            "searches": sum(getattr(b, "search_calls", 0) for b in bots),
            "search_secs": round(sum(getattr(b, "search_secs", 0.0)
                                     for b in bots), 4),
            "void_fallbacks": sum(getattr(b, "impossible_worlds", 0)
                                  for b in bots),
            # A world the constraint-correct sampler REFUSED to build. Absent
            # until 2026-08-05, which made the N=60 lane a policy-as-run
            # comparison rather than proof of an exact accepted dose: an arm
            # whose worlds were silently rejected searched fewer than N of
            # them and nothing recorded it (Codex).
            "rejected_worlds": sum(getattr(b, "rejected_worlds", 0)
                                   for b in bots),
            "sample_attempts": sum(getattr(b, "sample_attempts", 0)
                                   for b in bots),
            "accepted_worlds": sum(getattr(b, "accepted_worlds", 0)
                                   for b in bots),
            "failed_worlds": sum(getattr(b, "failed_worlds", 0)
                                 for b in bots),
            "short_searches": sum(getattr(b, "short_search_decisions", 0)
                                  for b in bots),
            "zero_world": sum(getattr(b, "zero_world_decisions", 0)
                              for b in bots),
            "exact_endgames": sum(getattr(b, "exact_endgame_calls", 0)
                                  for b in bots),
            "exact_endgame_attempts": sum(
                getattr(b, "exact_endgame_attempts", 0) for b in bots),
            "exact_endgame_refusals": sum(
                getattr(b, "exact_endgame_refusals", 0) for b in bots),
            "exact_endgame_budget_exceeded": sum(
                getattr(b, "exact_endgame_budget_exceeded", 0) for b in bots),
            "exact_endgame_sessions": sum(
                getattr(b, "exact_endgame_sessions", 0) for b in bots),
            "exact_endgame_nodes": sum(
                getattr(b, "exact_endgame_nodes", 0) for b in bots),
            "exact_endgame_cache_hits": sum(
                getattr(b, "exact_endgame_cache_hits", 0) for b in bots)}


def run_arm(label, policy, opponent, clusters, seed0, fh, run_id,
            progress=True, progress_scores=True,
            policy_telemetry_fn=None) -> list:
    """Play `clusters` mirrored pairs of `policy` against `opponent`.

    Both flips of a seed use the same deal, and every arm in a comparison is
    given the same seed0, so arms are paired on deals rather than merely
    sampled from the same distribution.
    """
    recs = []
    for c in range(clusters):
        seed = seed0 + c
        for flip in (0, 1):
            a1 = make_bot(policy, seed=seed)
            a2 = make_bot(policy, seed=seed + 500_000)
            b1 = make_bot(opponent, seed=seed + 1_000_000)
            b2 = make_bot(opponent, seed=seed + 1_500_000)
            pol = [a1, b1, a2, b2] if flip == 0 else [b1, a1, b2, a2]
            log = play_round(Game(random.Random(seed)), pol)
            won = int(log.winner_team == (0 if flip == 0 else 1))
            arm_counters = counters([a1, a2])
            opp_counters = counters([b1, b2])
            if policy_telemetry_fn is not None:
                # Opt-in only: frozen protocols that require the historical
                # exact counter shape keep it by using the default.  New
                # protocols can carry policy-specific activation witnesses
                # without teaching this shared evaluator their semantics.
                arm_counters["policy_telemetry"] = policy_telemetry_fn(
                    [a1, a2])
                opp_counters["policy_telemetry"] = policy_telemetry_fn(
                    [b1, b2])
            # Margin/bracket recording (STRENGTH_STACK_PROPOSAL.md stage 1).
            # Measurement-only: binary `won` still gates everything; these
            # fields exist so margin/bracket composites can be analysed
            # offline and, if Jerry adopts power option (b), pre-registered
            # as gates. Brackets follow the engine's scoring thresholds
            # (attacker points 0 / <40 / <80 / 80+ / 120+ / ...): the arm's
            # seats attack when the banker sits on the opposing team for
            # this flip.
            arm_attacking = int(log.banker % 2 != (0 if flip == 0 else 1))
            pts = int(log.attacker_points)
            # Same bracket convention as MCBot's LEVEL_OBJECTIVE mapping
            # (mcbot.py _level_score): 0 -> -3, 1-39 -> -2, 40-79 -> -1,
            # 80-119 -> 0, then +1 per 40, capped at 3.
            bracket = (min(3, (pts - 80) // 40) if pts >= 80
                       else -3 if pts == 0 else -(1 + (79 - pts) // 40))
            rec = {"run": run_id, "label": label, "policy": policy,
                   "seed": seed, "flip": flip, "won": won,
                   "level_utility": (1 if won else -1) * max(1, int(log.level_change)),
                   "attacker_points": pts,
                   "arm_attacking": arm_attacking,
                   "attacker_bracket": bracket,
                   "arm_point_margin": (pts - 80) * (1 if arm_attacking
                                                     else -1),
                   "level_change": int(log.level_change),
                   "arm": arm_counters, "opp": opp_counters}
            recs.append(rec)
            fh.write(json.dumps(rec) + "\n")
        if progress and c and c % 50 == 0:
            suffix = ""
            if progress_scores:
                w = sum(r["won"] for r in recs)
                suffix = f", {w}-{len(recs)-w}"
            print(f"    {label}: {2*c}/{2*clusters} rounds{suffix}", flush=True)
    return recs


def paired_by_seed(a_recs, b_recs):
    """Mean per-SEED difference in level utility, with a clustered interval.

    Clustering by seed is the whole point: the two flips of a seed share a
    deal, so treating 2*clusters rounds as independent understates the spread.
    """
    by = {}
    for r in a_recs:
        by.setdefault(r["seed"], [0, 0])[0] += r["level_utility"]
    for r in b_recs:
        by.setdefault(r["seed"], [0, 0])[1] += r["level_utility"]
    d = [x - y for x, y in by.values()]
    n = len(d)
    if not d:
        return 0.0, float("inf"), 0
    m = sum(d) / n
    if n < 2:
        # The mean IS computable from one cluster; the SPREAD is not. Returning
        # 0.0 for the mean here (as this did) hands a caller that reads `m`
        # without checking `n` a silently wrong number. An infinite interval
        # says the right thing: known centre, unknown precision, cannot clear
        # any bar.
        return m, float("inf"), n
    var = sum((v - m) ** 2 for v in d) / (n - 1)
    return m, 1.96 * math.sqrt(var / n), n


def clustered_win_rate(recs):
    """Win rate averaged per seed, so correlated flips are not double-counted."""
    by = {}
    for x in recs:
        by.setdefault(x["seed"], []).append(x["won"])
    per = [sum(v) / len(v) for v in by.values()]
    value = sum(per) / len(per)
    var = sum((p - value) ** 2 for p in per) / max(len(per) - 1, 1)
    return value, 1.96 * math.sqrt(var / len(per))


def parse_bar(bar: str):
    """A bar must be machine-checkable or it gates nothing."""
    mt = re.match(r"\s*(paired_utility|win_rate)\s*>\s*(-?[\d.]+)\s*$", bar)
    if not mt:
        raise ProtocolFailure(
            "--bar must be enforceable, e.g. 'paired_utility > 0' or "
            "'win_rate > 0.5'. Free text cannot gate anything, and a bar that "
            "is recorded but not applied is theatre (Codex).")
    return mt.group(1), float(mt.group(2))


@dataclass
class Result:
    run_id: str
    confirmed: bool
    value: float
    half: float
    metric: str
    threshold: float
    problems: list = field(default_factory=list)
    stats: dict = field(default_factory=dict)
    records_path: str = ""
    manifest_path: str = ""


def evaluate(arm, opponent, *, clusters=250, seed0=None, control=None, bar,
             ckpts=(), allow_no_control=False, allow_lenient_voids=False,
             cli_path=None, outdir="runs/logs") -> Result:
    """Run the full protocol and return its verdict."""
    metric, threshold = parse_bar(bar)          # fail before spending compute
    if seed0 is None:
        seed0 = int(time.time()) % 5_000_000 * 7
    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                         capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain"],
                           capture_output=True, text=True).stdout.strip()
    plan_names = [arm, opponent] + ([control] if control else [])
    # Second-resolution ids COLLIDE when parallel shards start in the same
    # second, and the manifest is opened with "x" — so a six-shard launch would
    # fail or overwrite (Codex). Include the pid.
    run_id = f"eval_{int(time.time())}_{os.getpid()}_{sha}"
    manifest = {
        "run": run_id, "arm": arm, "opponent": opponent, "control": control,
        "clusters": clusters, "seed0": seed0, "declared_bar": bar,
        "git": sha, "tree_dirty": bool(dirty),
        "dirty_files": dirty.split("\n")[:20] if dirty else [],
        # BOTH digests. The logic lives in this module now, so recording only
        # the CLI would silently weaken provenance exactly when the code moved.
        "cli_sha256_16": digest(cli_path),
        "library_sha256_16": digest(__file__),
        "ckpt_digests": {c: digest(c) for c in ckpts},
        "ballots": arm_ballots(plan_names),
        "fast_engine": bool(os.environ.get("SHENGJI_FAST")),
        "require_voids": bool(os.environ.get("SHENGJI_REQUIRE_VOIDS")),
        "started": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    t_start = time.time()
    os.makedirs(outdir, exist_ok=True)
    manifest_path = f"{outdir}/{run_id}.manifest.json"
    with open(manifest_path, "x") as mf:
        json.dump(manifest, mf, indent=2)
    print(json.dumps(manifest, indent=2), flush=True)
    if dirty:
        print("\nWARNING: tree is DIRTY — this run's git SHA does not describe "
              "the code that ran. Recorded in the manifest.", flush=True)

    plan = [("arm", arm), ("reference", opponent)]
    if control:
        plan.append(("control", control))
    out = f"{outdir}/{run_id}.jsonl"
    results = {}
    with open(out, "x") as fh:
        for label, policy in plan:
            print(f"\n  {label}: {policy} vs {opponent}", flush=True)
            results[label] = run_arm(label, policy, opponent, clusters, seed0,
                                     fh, run_id)

    ref = results["reference"]
    print(f"\n{'':10} {'win%':>7} {'paired level utility/seed':>28} "
          f"{'rollouts':>10} {'search s':>9}")
    stats = {}
    for label, _ in plan:
        r = results[label]
        w = sum(x["won"] for x in r)
        m, ci, _ = paired_by_seed(r, ref)
        stats[label] = (m, ci)
        print(f"{label:10} {100*w/len(r):6.1f}% {m:+16.3f} +/- {ci:6.3f} "
              f"{sum(x['arm']['rollouts'] for x in r):10d} "
              f"{sum(x['arm']['search_secs'] for x in r):9.1f}")

    if metric == "paired_utility":
        value, half = stats["arm"]
    else:
        value, half = clustered_win_rate(results["arm"])
    clears = value - half > threshold

    problems = []
    if not control and not allow_no_control:
        problems.append("no control: a positive result is unattributable")
    if not os.environ.get("SHENGJI_REQUIRE_VOIDS") and not allow_lenient_voids:
        problems.append("SHENGJI_REQUIRE_VOIDS unset: sampled worlds may "
                        "violate observed voids")
    if not ckpts and any(("rl" in p or "v11" in p) for _, p in plan):
        problems.append("a net arm ran with no checkpoint digest recorded")
    if dirty:
        problems.append("tree was DIRTY: the git SHA does not describe the run")
    all_counts = [side for r in results.values() for x in r
                  for side in (x["arm"], x["opp"])]
    unreconciled = sum(abs(c.get("sample_attempts", 0)
                           - c.get("accepted_worlds", 0)
                           - c.get("failed_worlds", 0)) for c in all_counts)
    if unreconciled:
        problems.append(f"sampler accounting is unreconciled by {unreconciled} "
                        "attempts")
    short = sum(c.get("short_searches", 0) for c in all_counts)
    if short:
        problems.append(f"{short} search decisions failed to consume their "
                        "registered selection/report dose")
    zw = sum(x["arm"]["zero_world"] + x["opp"]["zero_world"]
             for r in results.values() for x in r)
    if zw:
        problems.append(f"{zw} decisions searched ZERO worlds and fell back to "
                        f"candidate 0 — the search did not run there")

    print(f"\nDECLARED BAR: {metric} > {threshold}")
    print(f"MEASURED:     {value:+.3f} +/- {half:.3f}  -> "
          f"{'clears' if clears else 'does NOT clear'}")
    if control:
        cm, cci = stats["control"]
        # The DIRECT contrast, paired on the same seeds. Reporting each arm
        # against the reference leaves the actual question — is the arm better
        # than the control? — uncomputed. Codex had to work it out by hand for
        # the v13 duel (v13 minus v7 = -0.028 +/- 0.185), which is exactly the
        # number that should have been printed here.
        dm, dci, _ = paired_by_seed(results["arm"], results["control"])
        print(f"ARM MINUS CONTROL (paired, same seeds): {dm:+.3f} +/- {dci:.3f}"
              + ("  <-- excludes 0: the arm genuinely differs from its control"
                 if abs(dm) - dci > 0 else
                 "  <-- includes 0: arm and control are not distinguishable"))
        if abs(dm) - dci <= 0:
            problems.append("arm and control are not distinguishable")
        if cm - cci > threshold:
            print(f"CONTROL {control}: {cm:+.3f} +/- {cci:.3f}  <-- ALSO "
                  f"clears; the effect is not attributable to the arm")
            problems.append("the control clears the same bar")
        else:
            print(f"CONTROL {control}: {cm:+.3f} +/- {cci:.3f} (does not clear)")
    if problems:
        print("\nPROTOCOL FAILURES — verdict forced to NOT CONFIRMED:")
        for p_ in problems:
            print(f"  - {p_}")
    confirmed = clears and not problems
    print(f"\nVERDICT: {'CONFIRMED' if confirmed else 'NOT CONFIRMED'}")
    fb = sum(x["arm"]["void_fallbacks"] + x["opp"]["void_fallbacks"]
             for r in results.values() for x in r)
    sr = sum(x["arm"]["searches"] + x["opp"]["searches"]
             for r in results.values() for x in r)
    print(f"void fallbacks: {fb} over {sr} searches | wall "
          f"{(time.time()-t_start)/60:.1f} min")
    print(f"records: {out}\nmanifest: {manifest_path}")
    return Result(run_id=run_id, confirmed=confirmed, value=value, half=half,
                  metric=metric, threshold=threshold, problems=problems,
                  stats=stats, records_path=out, manifest_path=manifest_path)
