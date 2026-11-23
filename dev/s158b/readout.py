"""Stage B analysis on decoded seed slots supplied by the sealed reader."""
from collections import Counter
import math

import numpy as np

from scripts.expert_labels import validity
from shengji.engine.cards import RANKS
from seed_worker import FIRST_SEED, DEALS


def _int(value, lo, hi):
    return type(value) is int and lo <= value <= hi


def _check_follow(row, banker, decisions):
    actions = row["admitted"]
    points = row["pi_attacker_points"]
    if (not isinstance(actions, list) or len(actions) < 2 or not isinstance(points, list)
            or len(points) != len(actions) or not all(_int(p, 0, 4200) and p % 5 == 0 for p in points)
            or not all(isinstance(a, list) and a and all(isinstance(c, str) for c in a) for a in actions)
            or len({tuple(sorted(a)) for a in actions}) != len(actions)):
        raise ValueError("invalid PI ballot")
    last = len(actions) - 1
    censored = row["full_censored"]
    if (not _int(row["seat"], 0, 3) or row["attacker"] is not (row["seat"] % 2 != banker % 2)
            or not _int(row["play_index"], 0, decisions - 1) or not _int(row["worlds"], 64, 64)
            or not all(_int(row[k], 0, last) for k in ("arm", "served"))
            or type(censored) is not bool or (censored != (row["full"] is None))
            or (not censored and not _int(row["full"], 0, last))):
        raise ValueError("unpaired pick or wrong acting side")
    reason, done, skipped = row["abandoned"], row["completed_worlds"], row["skipped_worlds"]
    if (reason not in (None, "soft_budget", "hard_budget")
            or (reason and row["arm"] != row["served"])
            or type(row["stage_seconds"]) not in (int, float)
            or not math.isfinite(row["stage_seconds"]) or row["stage_seconds"] < 0):
        raise ValueError("invalid stage result")
    if reason == "hard_budget":
        if done is not None or skipped is not None:
            raise ValueError("hard abandon published partial counts")
    elif (not _int(done, 0, 64) or not _int(skipped, 0, 64 - done)
          or ((reason is None) != (done >= 12))):
        raise ValueError("inconsistent number of completed worlds")


def _validate(slots, arm_name):
    if set(slots) != set(range(FIRST_SEED, FIRST_SEED + DEALS)):
        raise ValueError("incomplete or unexpected seed reservation")
    counts = Counter()
    declares, searches, outcomes, rows = [], [], [], []
    for seed in range(FIRST_SEED, FIRST_SEED + DEALS):
        rec = slots[seed]
        if (rec["schema"] != "s158b-seed-v1" or rec["status"] != "complete"
                or not _int(rec["seed"], seed, seed) or rec["release"] != 55
                or rec["arm_name"] != arm_name or rec["rank"] != RANKS[(seed - FIRST_SEED) % 12]):
            raise ValueError(f"slot {seed} has a fault or wrong identity")
        if not isinstance(rec["eligible"], list) or not isinstance(rec["declares"], list):
            raise ValueError(f"slot {seed} has malformed decision lists")
        n = rec["decisions"]
        if (not _int(n, 1, 100) or rec["world_counts"] != {"64": n}
                or type(rec["world_counts"]["64"]) is not int
                or not _int(rec["belief_fallbacks"], 0, n)
                or rec["bury_fallback"] is not None and not isinstance(rec["bury_fallback"], str)):
            raise ValueError(f"slot {seed} has invalid base decision counts")
        counts.update(decisions=n, search=n, buries=1, declares=len(rec["declares"]),
                      play_fallback=0, belief_fallback=rec["belief_fallbacks"],
                      bury_fallback=int(rec["bury_fallback"] is not None))
        for d in rec["declares"]:
            if (not _int(d["seat"], 0, 3) or d["evaluated"] != (d["fallback_reason"] is None)):
                raise ValueError("inconsistent declaration fallback")
            counts["declare_abandon"] += int(not d["evaluated"])
            declares.append(d)
        searches.append((seed, "shared", "search", 64))
        outcomes.append((seed, rec))
        seen = set()
        for row in rec["eligible"]:
            _check_follow(row, rec["banker"], n)
            if row["play_index"] in seen:
                raise ValueError("duplicate eligible play")
            seen.add(row["play_index"])
            rows.append((seed, row))
    # The three picks share every base decision, including all declaration and bury work.
    limits = dict(validity.DEFAULT_CEILINGS, play_fallback=0)
    checks = [validity.arm_fault_ceilings({"shared": counts}, limits, arms=("shared",)),
              validity.worlds_delivered(searches, {"shared": 64}),
              validity.completion_shape(declares, expected_worlds_by_arm={"shared": 64}),
              validity.outcome_consistency(outcomes)]
    for check in checks:
        if check["verdict"] != "VALID":
            raise ValueError(check["reasons"])
    if not rows or 100 * sum(row["full_censored"] for _, row in rows) > len(rows):
        raise ValueError("empty eligible set or full-reference censoring above 1%")
    return rows


def _interval(groups):
    clusters = np.array(list(groups.values()), dtype=np.int64)
    rng = np.random.default_rng(1)
    means = []
    for _ in range(100):
        draws = rng.integers(len(clusters), size=(100, len(clusters)))
        totals = clusters[draws].sum(axis=1)
        means.extend(totals[:, 0] / totals[:, 1])
    ordered = sorted(means)
    return dict(mean=float(clusters[:, 0].sum() / clusters[:, 1].sum()),
                lower95=float(ordered[250]), upper95=float(ordered[9749]))


def analyze(slots, *, arm_name):
    """Validate the entire reservation before computing either paired contrast."""
    try:
        rows = _validate(slots, arm_name)
    except (KeyError, TypeError, ValueError) as exc:
        return dict(verdict="INVALID", reason=str(exc))
    contrasts = {}
    for name in ("served", "full"):
        groups = {}
        for seed, r in rows:
            index = r[name]
            if index is None:
                continue
            pts = r["pi_attacker_points"]
            delta = pts[index] - pts[r["arm"]]
            group = groups.setdefault(seed, [0, 0])
            group[0] += delta if r["attacker"] else -delta
            group[1] += 1
        contrasts[name] = _interval(groups)
    n = len(rows)
    abandons = sum(r["abandoned"] is not None for _, r in rows)
    seconds = sorted(r["stage_seconds"] for _, r in rows)
    p99 = seconds[math.ceil(.99 * n) - 1]
    passed = (100 * abandons <= 2 * n and p99 <= 2.0
              and contrasts["full"]["upper95"] <= .1 and contrasts["served"]["upper95"] < 0)
    return dict(verdict="PASS" if passed else "FAIL", eligible=n, abandons=abandons,
                full_censored=sum(r["full_censored"] for _, r in rows), stage_p99_seconds=p99,
                regret=contrasts)
