"""Freeze the 512-state lead-ballot pilot set.

BALLOT_PLAN Phase 2 / BACKLOG: "at most one state per deal, a frozen DEV-only
original/late split". This selects that set once and commits it, so every arm
in the pilot is measured on the same states and the selection cannot drift
after results are seen.

Four properties, each because of a specific way this project has been burned:

  * **DEV only.** CALIB decides which arm earns an online duel; REPORT is
    touched once, at the end. Drawing pilot states from either would let the
    arm be tuned on the set that judges it.
  * **One state per deal.** Four states from one deal share a shuffle and a
    bury. Treating them as four independent observations is the same
    correlated-cluster error that killed six strength claims.
  * **LEAD states only.** The pilot measures lead sourcing. Follows are
    structurally solved (0.9% structured omission against 51.2% for leads),
    so spending pilot budget on them measures nothing.
  * **Stratified**, across role (banker/attacker), ply, and candidate count,
    so the set is not dominated by the early-ply states the original corpus
    over-represents. The late supplement carries its own immutable split
    (`corpus_split_late.v1.json`), never merged with the original's.

Only STATES are selected here. No values are computed, no worlds are sampled,
nothing is scored — the proposal / oracle-selection / report world folds are
drawn later and must stay disjoint.

    uv run python scripts/pilot_states.py [--n 512]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import subprocess
import sys
import time
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shengji.ai.mcbot import MCBot            # noqa: E402
from shengji.ai.smart import SmartBot         # noqa: E402
from shengji.engine.game import Game          # noqa: E402

SOURCES = [
    ("original", "rl_data/highn_corpus_all.jsonl", "rl_data/corpus_split.v1.json"),
    ("late", "rl_data/highn_late_air.jsonl", "rl_data/corpus_split_late.v1.json"),
]


def dirty_at_start() -> bool:
    return bool(subprocess.run(["git", "status", "--porcelain"],
                               capture_output=True, text=True).stdout.strip())


def digest(path):
    if not path or not os.path.exists(path):
        return None
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def replay(row):
    """Rebuild a corpus row to its decision point, verified against the deck."""
    seed = row["seed"]
    game = Game(random.Random(seed))
    rnd = game.start_round()
    pol = [MCBot(seed=seed + 7), SmartBot(), MCBot(seed=seed + 11), SmartBot()]
    while rnd.phase == "deal":
        s, _, _ = rnd.deal_next()
        cs = pol[s].decide_declare(rnd, s)
        if cs:
            rnd.declare(s, cs)
    for s in range(4):
        cs = pol[s].decide_declare(rnd, s, final=True)
        if cs:
            rnd.declare(s, cs)
    rnd.finalize_declare()
    if list(rnd.deck) != list(row["setup"]["deck"]):
        raise ValueError("deck mismatch")
    rnd.bury(rnd.banker, list(row["setup"]["buried"]))
    for p in row["plays"]:
        rnd.play(p["seat"], list(p["cards"]))
    if rnd.turn != row["seat"] or rnd.phase != "play":
        raise ValueError("replay landed elsewhere")
    return rnd


def stratum(rnd, seat, n_cands):
    """Role x ply band x ballot size. Coarse on purpose: fine strata with one
    member each are not strata, they are a shuffled list.

    The role label is the TEAM, not the seat. It said "banker" while meaning
    `not is_attacker`, i.e. the whole defending pair — the banker's partner was
    labelled banker too (Codex).
    """
    role = "defender" if not rnd.is_attacker(seat) else "attacker"
    ply = len(rnd.history)
    band = "early" if ply < 5 else ("mid" if ply < 12 else "late")
    size = "small" if n_cands <= 4 else ("med" if n_cands <= 9 else "wide")
    return f"{role}/{band}/{size}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=512)
    ap.add_argument("--out", default="rl_data/pilot_states.v1.json")
    ap.add_argument("--salt", default="pilot-v1")
    args = ap.parse_args()

    if dirty_at_start():
        print("REFUSING: the tree is dirty. A frozen artifact from a dirty "
              "tree cannot be tied to the code that produced it — the previous "
              "version recorded tree_dirty=true and was not promotion-grade "
              "(Codex). Commit first.")
        sys.exit(3)
    if os.path.exists(args.out):
        print(f"REFUSING: {args.out} exists. A frozen pilot set is never "
              f"redrawn in place — a set reselected after seeing results is "
              f"not a set, it is a knob. Use a new --out and --salt.")
        sys.exit(3)

    bot = MCBot(seed=1)
    by_deal: dict[int, list] = defaultdict(list)
    errors = skipped_follow = skipped_dupe = 0

    for source, corpus, split_path in SOURCES:
        with open(split_path) as fh:
            split = {int(k): v for k, v in json.load(fh)["assign"].items()}
        with open(corpus) as fh:
            for line in fh:
                row = json.loads(line)
                if split.get(row["seed"]) != "dev":
                    continue
                # NOT skipped here. Marking a deal seen at its FIRST eligible
                # row meant later lead states from that deal never competed for
                # selection, which is why v2 held 229 early / 281 mid / 2 LATE
                # states under the trick-index unit while its raw-play summary
                # called it late-heavy (Codex). Gather every eligible row per
                # deal, then choose one.
                try:
                    rnd = replay(row)
                except Exception:
                    errors += 1
                    continue
                seat = row["seat"]
                if rnd.trick is not None and rnd.trick.plays:
                    skipped_follow += 1
                    continue          # LEADS only
                try:
                    n_cands = len(bot._candidates(rnd, seat))
                except Exception:
                    errors += 1
                    continue
                st = stratum(rnd, seat, n_cands)
                by_deal[row["seed"]].append({
                    "source": source, "seed": row["seed"], "ply": row["ply"],
                    "seat": seat, "n_candidates": n_cands,
                    # recorded ON the row: the previous artifact reported strata
                    # computed AFTER selection popped rows, so the figure
                    # described the residual pool, not the selected set (Codex)
                    "stratum": st, "is_banker_seat": seat == rnd.banker,
                    "tricks": len(rnd.history),
                    "band": ("early" if len(rnd.history) < 5 else
                             "mid" if len(rnd.history) < 12 else "late"),
                })

    # One state per DEAL, chosen to fill explicitly named trick-index bands.
    rng = random.Random(int(hashlib.sha256(args.salt.encode()).hexdigest()[:8], 16))
    BANDS = ("early", "mid", "late")
    # Which deals can supply which band
    deals_for: dict[str, list] = {b: [] for b in BANDS}
    for seed, rows in by_deal.items():
        for b in {r["band"] for r in rows}:
            deals_for[b].append(seed)
    available = {b: len(v) for b, v in deals_for.items()}
    for v in deals_for.values():
        v.sort()
        rng.shuffle(v)

    picked, used_deals = [], set()
    i = 0
    while len(picked) < args.n and any(deals_for[b] for b in BANDS):
        b = BANDS[i % len(BANDS)]
        i += 1
        while deals_for[b]:
            seed = deals_for[b].pop()
            if seed in used_deals:
                continue
            options = [r for r in by_deal[seed] if r["band"] == b]
            if not options:
                continue
            options.sort(key=lambda d: (d["tricks"], d["ply"], d["seat"]))
            used_deals.add(seed)
            picked.append(options[rng.randrange(len(options))])
            break
    skipped_dupe = sum(len(v) for v in by_deal.values()) - len(picked)

    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                         capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain"],
                           capture_output=True, text=True).stdout.strip()
    from shengji.engine.ballot import mc_ballot
    payload = {
        "git": sha, "tree_dirty": bool(dirty), "salt": args.salt,
        "created": time.strftime("%Y-%m-%d %H:%M:%S"),
        "script_sha256_16": digest(os.path.abspath(__file__)),
        "ballot_at_selection": str(mc_ballot(bot)),
        "sources": {name: {"corpus": c, "corpus_sha256_16": digest(c),
                           "split": sp, "split_sha256_16": digest(sp)}
                    for name, c, sp in SOURCES},
        "requested": args.n, "selected": len(picked),
        "one_state_per_deal": True, "side": "dev", "leads_only": True,
        "band_deals_available": available,
        "bands_selected": dict(Counter(p["band"] for p in picked)),
        "tricks_histogram": dict(Counter(p["tricks"] // 5 * 5 for p in picked)),
        "strata_selected": dict(Counter(p["stratum"] for p in picked)),
        "picked_by_source_ply": dict(Counter(
            f'{p["source"]}/{"early" if p["ply"] < 5 else ("mid" if p["ply"] < 12 else "late")}'
            for p in picked)),
        "skipped_follows": skipped_follow, "skipped_same_deal": skipped_dupe,
        "replay_errors": errors,
        "states": picked,
    }
    tmp = args.out + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(payload, fh, indent=1)
    os.replace(tmp, args.out)

    print(f"selected {len(picked)} / {args.n} lead states, DEV only, "
          f"one per deal")
    print(f"  replay errors {errors}   follows skipped {skipped_follow}   "
          f"same-deal skipped {skipped_dupe}")
    print(f"  by source/ply: {payload['picked_by_source_ply']}")
    print(f"  BANDS selected (trick index): {payload['bands_selected']}")
    print(f"  deals available per band     : {payload['band_deals_available']}")
    print(f"  ballot at selection: {payload['ballot_at_selection']}")
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
