"""Paired analysis of two `sampler_posterior.py` arms — REFUSES if unpaired.

A paired per-state test assumes the two arms measured THE SAME STATES. Equal
seed labels do not establish that: `toy_states()` self-plays to reach its
positions, so any sampler flag left active during generation changes which
states come out, and the seeds still line up. That failure produced a published
`+0.018 +/- 0.045` over 24 states that shared 0 of 24 state spaces (Codex).

The assumption is checkable, because each row records the exact enumerated
legal set. So check it, and fail closed rather than report a number whose
meaning depends on it.

    uv run python scripts/paired_posterior.py before after
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys


def load(name: str) -> dict:
    path = name if os.path.exists(name) else f"runs/logs/post24_{name}.json"
    with open(path) as fh:
        return json.load(fh)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("baseline")
    ap.add_argument("arm")
    ap.add_argument("--metric", default="tv_excess")
    args = ap.parse_args()

    a, b = load(args.baseline), load(args.arm)
    ra = {r["seed"]: r for r in a["rows"]}
    rb = {r["seed"]: r for r in b["rows"]}

    print(f"  baseline mode: {a.get('mode')}")
    print(f"  arm      mode: {b.get('mode')}")
    ma, mb = a.get("mode") or {}, b.get("mode") or {}
    if not ma or not mb:
        print("REFUSING: a run has no `mode` provenance, so what it measured "
              "cannot be established.")
        sys.exit(3)
    # `mode != mode` only proves SOMETHING differed. Requiring exactly one
    # differing flag proves the comparison isolates the flag it claims to
    # (Codex): two flags moving at once is a different experiment.
    diff = sorted(k for k in set(ma) | set(mb) if ma.get(k) != mb.get(k))
    if len(diff) != 1:
        print(f"REFUSING: {len(diff)} sampler flags differ between the arms "
              f"({diff or 'none'}). A single-factor contrast must differ in "
              "exactly one; otherwise the effect cannot be attributed.")
        sys.exit(3)
    print(f"  isolated factor: {diff[0]} "
          f"({ma.get(diff[0])} -> {mb.get(diff[0])})")

    # Duplicate seeds must be caught BEFORE the dict comprehensions above hide
    # them: `{r["seed"]: r for r in rows}` silently keeps the last of a
    # repeated seed, so a run with a duplicated state would compare a different
    # row than the one counted (Codex).
    for tag, d in (("baseline", a), ("arm", b)):
        seeds = [r["seed"] for r in d["rows"]]
        if len(seeds) != len(set(seeds)):
            dup = sorted({x for x in seeds if seeds.count(x) > 1})
            print(f"REFUSING: {tag} has duplicate seeds {dup}; the paired "
                  "statistic would silently use only the last row of each.")
            sys.exit(3)

    # Seed sets must be IDENTICAL, not merely overlapping. Intersecting lets a
    # run that dropped states still report a confident-looking interval over
    # whatever happened to survive, which is a different estimand.
    if set(ra) != set(rb):
        only_a = sorted(set(ra) - set(rb))
        only_b = sorted(set(rb) - set(ra))
        print(f"REFUSING: seed sets differ — {len(only_a)} only in baseline "
              f"{only_a[:5]}, {len(only_b)} only in arm {only_b[:5]}. Compare "
              "complete matching blocks, not their intersection.")
        sys.exit(3)
    shared = sorted(ra)
    if not shared:
        print("REFUSING: no shared seeds.")
        sys.exit(3)

    # The load-bearing check. `legal_keys` is the enumerated legal world set for
    # that state; if it differs, the two arms are describing different states
    # and no per-seed difference between them is a paired measurement.
    missing = [k for k in shared
               if "legal_keys" not in ra[k] or "legal_keys" not in rb[k]]
    if missing:
        print(f"REFUSING: {len(missing)} rows predate `legal_keys` recording, "
              "so pairing cannot be verified. Re-run both arms.")
        sys.exit(3)
    paired = [k for k in shared if ra[k]["legal_keys"] == rb[k]["legal_keys"]]
    print(f"  shared seeds {len(shared)}   VERIFIED PAIRED "
          f"{len(paired)}/{len(shared)}")
    if len(paired) != len(shared):
        print(f"REFUSING: {len(shared) - len(paired)} seed(s) label the same "
              "state but enumerate DIFFERENT legal worlds. A sampler flag was "
              "almost certainly active during state generation — neutralise "
              "it in SAMPLER_FLAGS and re-run.")
        sys.exit(3)

    d = [rb[k][args.metric] - ra[k][args.metric] for k in paired]
    n = len(d)
    m = sum(d) / n
    if n < 2:
        print(f"  n={n}: no interval computable")
        sys.exit(0)
    sd = math.sqrt(sum((x - m) ** 2 for x in d) / (n - 1))
    ci = 1.96 * sd / math.sqrt(n)
    neg = sum(1 for x in d if x < -1e-9)
    pos = sum(1 for x in d if x > 1e-9)
    if m + ci < 0:
        v = "CONFIRMED reduction"
    elif m - ci > 0:
        v = "CONFIRMED increase"
    else:
        v = "not distinguishable from 0"
    print(f"\n  paired d{args.metric}: {m:+.4f} +/- {ci:.4f}  (n={n})")
    print(f"  signs: {neg} negative, {n - neg - pos} zero, {pos} positive")
    print(f"  -> {v}")
    print(f"\n  reference: {a.get('reference', 'UNRECORDED')}")
    print("  A reduction toward a WRONG reference is not a reduction in bias.")


if __name__ == "__main__":
    main()
