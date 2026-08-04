"""Static audit: what does the deployed ballot leave off the table, and where?

BALLOT_PLAN immediate item 4 — a no-rollout coverage and determinism audit on
the frozen DEV split. No values are computed and nothing is promoted here.
Two prior offline metrics predicted online strength and both were wrong, so
this measures only what is structurally true: which legal actions the deployed
`MCBot._candidates()` never offers, bucketed by archetype.

Why leads: the deployed ballot misses 15.5% of human leads against 2.0% of
follows, and leads carry 3x the forfeit of follows (2.96 vs 1.01 points). Two
independent measurements pointing at one surface.

The audit rebuilds each state by REPLAY from its seed and then asserts the
rebuilt deck matches the deck recorded in the row. A silent rebuild drift
would make every number here fiction, and this corpus has already been read
through a stale partial file once.

    uv run python scripts/ballot_coverage.py [--limit N] [--side dev]
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shengji.ai.mcbot import MCBot            # noqa: E402
from shengji.ai.smart import SmartBot         # noqa: E402
from shengji.engine.combos import decompose   # noqa: E402
from shengji.engine.game import Game          # noqa: E402
from shengji.rl.actions import enumerate_actions  # noqa: E402


def _digest_file(path):
    """Provenance for every input an audit number depends on."""
    import hashlib
    if not path or not os.path.exists(path):
        return None
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


class RebuildMismatch(RuntimeError):
    pass


def rebuild(row) -> tuple:
    """Replay a corpus row back to its decision point. Verified, not trusted."""
    seed = row["seed"]
    game = Game(random.Random(seed))
    rnd = game.start_round()
    pol = [MCBot(seed=seed + 7), SmartBot(), MCBot(seed=seed + 11), SmartBot()]
    while rnd.phase == "deal":
        s, _, _ = rnd.deal_next()
        cards = pol[s].decide_declare(rnd, s)
        if cards:
            rnd.declare(s, cards)
    for s in range(4):
        cards = pol[s].decide_declare(rnd, s, final=True)
        if cards:
            rnd.declare(s, cards)
    rnd.finalize_declare()
    if list(rnd.deck) != list(row["setup"]["deck"]):
        raise RebuildMismatch(f"seed {seed}: deck differs from the recorded row")
    if rnd.banker != row["setup"]["banker"]:
        raise RebuildMismatch(f"seed {seed}: banker differs")
    rnd.bury(rnd.banker, list(row["setup"]["buried"]))
    for p in row["plays"]:
        rnd.play(p["seat"], list(p["cards"]))
    if rnd.turn != row["seat"]:
        raise RebuildMismatch(
            f"seed {seed} ply {row['ply']}: replay lands on seat {rnd.turn}, "
            f"row says {row['seat']}")
    return rnd, rnd.turn


def structured(cards, rnd) -> bool:
    """A single, a pair, or a TRUE tractor — one component under the engine.

    `include_throws` enumerates the whole combinatorial multi-card throw space,
    most of which no sane ballot would offer. Measuring omission against THAT
    makes the deployed ballot look 92% incomplete while saying nothing about
    lost value. The structured subset is the honest denominator for "what is a
    quota arm actually competing to add".

    Defining it as "every code multiplicity is 2" was wrong: that also accepts
    two UNRELATED pairs thrown together, which is a throw, not a tractor
    (Codex). The engine already knows the difference, so ask it — a structured
    action decomposes into exactly one component.
    """
    if len(cards) == 1:
        return True
    o = rnd.ordering
    if o is None:
        return False
    try:
        return len(decompose(list(cards), o).components) == 1
    except Exception:
        return False


def archetype(cards, rnd, seat) -> str:
    """Coarse structural bucket — what KIND of action was omitted."""
    n = len(cards)
    if n >= 3:
        return "throw/tractor (3+)"
    if n == 2:
        return "pair" if cards[0] == cards[1] else "throw (2 distinct)"
    c = cards[0]
    o = rnd.ordering
    is_trump = bool(o and o.is_trump(c))
    pts = c[1:] in ("5", "10", "K")
    if is_trump:
        return "single trump"
    return "single point card" if pts else "single non-point"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default="rl_data/highn_corpus_all.jsonl")
    ap.add_argument("--split", default="rl_data/corpus_split.v1.json")
    ap.add_argument("--side", default="dev")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", default="runs/logs/ballot_coverage.json")
    args = ap.parse_args()

    from corpus_split import load_split
    split = load_split(args.split)

    bot = MCBot(seed=1)
    from shengji.engine.ballot import mc_ballot
    print(f"deployed ballot: {mc_ballot(bot)}", flush=True)

    seen = miss_states = errors = 0
    missed_by_arch: Counter = Counter()
    offered_by_arch: Counter = Counter()
    miss_frac_lead, miss_frac_follow = [], []
    s_lead, s_follow = [], []
    per_ply = defaultdict(lambda: [0, 0])
    t0 = time.time()

    with open(args.corpus) as fh:
        for line in fh:
            row = json.loads(line)
            if split.get(row["seed"]) != args.side:
                continue
            try:
                rnd, seat = rebuild(row)
            except RebuildMismatch as exc:
                errors += 1
                if errors <= 3:
                    print(f"  REBUILD FAILED: {exc}", flush=True)
                continue
            except Exception:
                errors += 1
                continue
            is_lead = rnd.trick is None or not rnd.trick.plays
            # The wide analysis enumeration is the reference action space. It
            # is a DIAGNOSTIC ballot, never a play-time one.
            try:
                wide = enumerate_actions(rnd, seat, exhaustive_follows=True,
                                         include_throws=True)
                offered = bot._candidates(rnd, seat)
            except Exception:
                errors += 1
                continue
            key = lambda a: tuple(sorted(a))            # noqa: E731
            off = {key(a) for a in offered}
            missing = [a for a in wide if key(a) not in off]
            seen += 1
            frac = len(missing) / max(len(wide), 1)
            (miss_frac_lead if is_lead else miss_frac_follow).append(frac)
            s_wide = [a for a in wide if structured(a, rnd)]
            s_missing = [a for a in s_wide if key(a) not in off]
            s_frac = len(s_missing) / max(len(s_wide), 1)
            (s_lead if is_lead else s_follow).append(s_frac)
            per_ply[row["ply"] // 5 * 5][0] += len(s_missing)
            per_ply[row["ply"] // 5 * 5][1] += len(s_wide)
            if missing:
                miss_states += 1
            if is_lead:
                for a in missing:
                    missed_by_arch[archetype(a, rnd, seat)] += 1
                for a in offered:
                    offered_by_arch[archetype(list(a), rnd, seat)] += 1
            if args.limit and seen >= args.limit:
                break
            if seen % 250 == 0:
                print(f"  {seen} states, {time.time()-t0:.0f}s", flush=True)

    def mean(v):
        return sum(v) / len(v) if v else 0.0

    print(f"\nstates audited {seen:,}   rebuild/enumeration errors {errors}")
    print(f"states with >=1 omitted legal action: {miss_states:,} "
          f"({miss_states/max(seen,1)*100:.1f}%)")
    print(f"\nmean fraction of the DIAGNOSTIC reference space omitted")
    print(f"  (enumerate_actions caps exhaustive follows at 64 and bounds\n   throw generation, so this is a diagnostic reference, NOT the legal universe)")
    print(f"  leads   {mean(miss_frac_lead)*100:5.1f}%  (n={len(miss_frac_lead)})")
    print(f"  follows {mean(miss_frac_follow)*100:5.1f}%  (n={len(miss_frac_follow)})")
    print(f"\nSTRUCTURED actions only (singles/pairs/tractors) — the honest number")
    print(f"  leads   {mean(s_lead)*100:5.1f}%  (n={len(s_lead)})")
    print(f"  follows {mean(s_follow)*100:5.1f}%  (n={len(s_follow)})")
    print(f"\nomitted LEAD actions by archetype (what a quota arm would add)")
    tot = sum(missed_by_arch.values()) or 1
    for k, v in missed_by_arch.most_common():
        print(f"  {k:22} {v:7,}  {v/tot*100:5.1f}%   "
              f"(currently offered: {offered_by_arch.get(k,0):,})")
    print(f"\nomitted STRUCTURED fraction by ply bucket")
    for p in sorted(per_ply):
        m, w = per_ply[p]
        print(f"  ply {p:2}-{p+4:<2} {m/max(w,1)*100:5.1f}%  ({w:,} legal actions)")

    os.makedirs("runs/logs", exist_ok=True)
    with open(args.out, "w") as fh:
        import subprocess
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True).stdout.strip()
        from shengji.engine.ballot import mc_ballot as _mb
        json.dump({
            "git": sha,
            "tree_dirty": bool(subprocess.run(["git", "status", "--porcelain"],
                                              capture_output=True,
                                              text=True).stdout.strip()),
            "script_sha256_16": _digest_file(os.path.abspath(__file__)),
            "corpus": args.corpus, "corpus_sha256_16": _digest_file(args.corpus),
            "split": args.split, "split_sha256_16": _digest_file(args.split),
            "ballot": str(_mb(bot)),
            "side": args.side, "states": seen, "errors": errors,
            "miss_states": miss_states,
            "mean_omitted_lead": mean(miss_frac_lead),
            "mean_omitted_follow": mean(miss_frac_follow),
            "mean_omitted_lead_structured": mean(s_lead),
            "mean_omitted_follow_structured": mean(s_follow),
            "missed_lead_by_archetype": dict(missed_by_arch),
            "offered_lead_by_archetype": dict(offered_by_arch),
            "by_ply": {str(k): v for k, v in per_ply.items()},
        }, fh, indent=2)
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
