"""Freeze a deal-grouped train/calibration/report split of the high-N corpus.

BALLOT_PLAN step 1 for using this corpus at all: "Freeze deal-grouped
train/calibration/report assignments before fitting anything." This script
exists so that instruction is enforceable rather than remembered.

Three properties it has to have, each because of a way the project has already
been burned:

  * **Deal-grouped.** All four rows sampled from one deal go to the same side.
    Rows from the same deal share a shuffle and a bury; splitting them lets
    information cross the boundary and makes a report number optimistic.
  * **Deterministic, not random.** Assignment is a stable hash of the seed, so
    the split is reproducible from the seed alone and cannot silently differ
    between two machines or two runs.
  * **Frozen.** Refuses to overwrite an existing split file. A split that can
    be regenerated after seeing results is not a split; it is a knob. Use
    --force only to create a NEW named version.

The report side is the scarce resource. Nothing may look at it until a
predeclared comparison is ready — every offline number that has been checked
against reality so far (three of three) failed to predict online strength, so
report rows are for rejecting a candidate, never for promoting one.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

#: dev sees everything; calibration tunes; report is touched once, at the end
FRACTIONS = (("dev", 60), ("calib", 20), ("report", 20))


def side_for(seed: int, salt: str) -> str:
    """Stable bucket for a deal seed. Salt lets a v2 split be independent."""
    h = hashlib.sha256(f"{salt}:{seed}".encode()).digest()
    x = int.from_bytes(h[:8], "big") % 100
    upto = 0
    for name, pct in FRACTIONS:
        upto += pct
        if x < upto:
            return name
    return FRACTIONS[-1][0]


def file_digest(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default="rl_data/highn_corpus_all.jsonl")
    ap.add_argument("--out", default="rl_data/corpus_split.v1.json")
    ap.add_argument("--salt", default="v1")
    ap.add_argument("--force", action="store_true",
                    help="create a NEW split version; never to redraw an old one")
    args = ap.parse_args()

    if os.path.exists(args.out) and not args.force:
        print(f"REFUSING: {args.out} already exists. A frozen split may not be "
              f"redrawn — that is how a report set stops being held out. To "
              f"create a genuinely new version, pass a new --out and --salt.")
        sys.exit(3)

    seeds, per_seed, plies = set(), Counter(), Counter()
    with open(args.corpus) as fh:
        for line in fh:
            d = json.loads(line)
            seeds.add(d["seed"])
            per_seed[d["seed"]] += 1
            plies[d["ply"]] += 1

    assign = {s: side_for(s, args.salt) for s in sorted(seeds)}
    by_side = Counter(assign.values())
    rows_by_side = Counter()
    for s, n in per_seed.items():
        rows_by_side[assign[s]] += n

    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                         capture_output=True, text=True).stdout.strip()
    payload = {
        "corpus": args.corpus,
        "corpus_digest": file_digest(args.corpus),
        "corpus_rows": sum(per_seed.values()),
        "salt": args.salt,
        "fractions": dict(FRACTIONS),
        "git": sha,
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        "deals_by_side": dict(by_side),
        "rows_by_side": dict(rows_by_side),
        "assign": {str(k): v for k, v in assign.items()},
    }
    tmp = args.out + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(payload, fh, indent=1)
    os.replace(tmp, args.out)

    print(f"corpus   {args.corpus}  digest {payload['corpus_digest']}")
    print(f"deals    {len(seeds):,}   rows {payload['corpus_rows']:,}")
    for name, _ in FRACTIONS:
        print(f"  {name:7} {by_side[name]:6,} deals  {rows_by_side[name]:7,} rows")
    late = sum(v for k, v in plies.items() if k >= 20)
    print(f"\nply>=20 rows in the whole corpus: {late:,} "
          f"({late / max(sum(plies.values()), 1) * 100:.1f}%) — the late-game "
          f"supplement is required before any late-ply claim.")
    print(f"\nwrote {args.out}")


def load_split(path: str = "rl_data/corpus_split.v1.json") -> dict:
    """{seed -> side}. Verifies the corpus has not changed underneath it."""
    with open(path) as fh:
        d = json.load(fh)
    if os.path.exists(d["corpus"]):
        live = file_digest(d["corpus"])
        if live != d["corpus_digest"]:
            raise RuntimeError(
                f"{d['corpus']} has changed since the split was frozen "
                f"({live} vs {d['corpus_digest']}). Rows may have moved between "
                f"sides; re-freeze as a new version rather than reusing this.")
    return {int(k): v for k, v in d["assign"].items()}


if __name__ == "__main__":
    main()
