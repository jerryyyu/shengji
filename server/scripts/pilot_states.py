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
    # The captured reservoir. The mined corpora hold only 3 DEV deals with a
    # lead at trick >= 12, so the registered late band is unreachable without
    # it. Its split is immutable and REPORT is never selected from here.
    ("deep", "rl_data/deep_leads.v1.jsonl", "rl_data/deep_lead_split.v1.json"),
]

#: Registered composition per Codex: 512 = 170 early + 171 mid + 171 late.
BAND_QUOTA = {"early": 170, "mid": 171, "late": 171}

#: REGISTERED candidate-size allocation, identical for DEV and CALIB.
#: These are the rounded pooled midpoint of the already-visible v3 metadata
#: (Codex); no action values or outcomes were inspected to derive them. They
#: are deliberately NOT even across bands: candidate count is close to
#: determined by depth, so late leads cannot supply `wide` at all and early
#: leads barely supply `small`. A census of the DEV corpus confirms every cell
#: below is satisfiable (late/wide needs 0 and 0 exist; early/small needs 0 and
#: 5 exist), whereas an even 56/57/57 split is infeasible in three cells.
SIZE_QUOTA = {
    "early": {"small": 0,   "med": 72,  "wide": 98},
    "mid":   {"small": 11,  "med": 131, "wide": 29},
    "late":  {"small": 152, "med": 19,  "wide": 0},
}

#: REGISTERED role marginals per band. Exact band-level marginals, not
#: role-by-size cells — inventing joint targets would be a post-hoc stratum.
ROLE_QUOTA = {
    "early": {"attacker": 85, "defender": 85},
    "mid":   {"attacker": 86, "defender": 85},
    "late":  {"attacker": 86, "defender": 85},
}


def size_of(row) -> str:
    return row["stratum"].split("/")[-1]


def publish_or_refuse(payload, out, tmp, violations):
    """Write the artifact, or refuse and leave NOTHING behind.

    Separated from `main` so the refusal is callable in a test. The failure
    this closes is specific: a shortage used to be recorded in a payload field
    and written anyway, exiting 0, which is indistinguishable from a complete
    freeze at the point of use. The temp file is removed too — a half-written
    `.tmp` beside the target is how a later run gets promoted by accident.
    """
    if violations:
        print("REFUSING to publish — contract violated:")
        for v in violations:
            print(f"  - {v}")
        print("Nothing written. A short or unbalanced gate set must FAIL, not "
              "be published with its shortfall recorded in a field nobody "
              "reads at the point of use.")
        if os.path.exists(tmp):
            os.remove(tmp)
        raise SystemExit(4)
    with open(tmp, "w") as fh:
        json.dump(payload, fh, indent=1)
    os.replace(tmp, out)
    return out


def check_contract(picked, requested, errors, *, band_quota=None,
                   size_quota=None, role_quota=None):
    """Every way this freeze can be WRONG, as a list of violations.

    Split out from the writer so it is callable — and therefore testable —
    without running a full selection. The previous code enforced nothing here:
    when a band ran out of deals the fill loop simply exited, the payload was
    written with fewer states than requested, and the process exited 0. A short
    artifact that reports its own shortness in a field nobody reads is
    indistinguishable from a complete one at the point of use.
    """
    band_quota = BAND_QUOTA if band_quota is None else band_quota
    size_quota = SIZE_QUOTA if size_quota is None else size_quota
    bad = []
    if errors:
        bad.append(f"{errors} replay error(s): a state that does not replay "
                   f"cannot be scored, so the set is not usable")
    if len(picked) != requested:
        bad.append(f"selected {len(picked)}, requested {requested}")
    for b, want in band_quota.items():
        got = sum(1 for p in picked if p["band"] == b)
        if got != want:
            bad.append(f"band {b}: {got} selected, quota {want}")
    for b, wants in size_quota.items():
        have = Counter(p["stratum"].split("/")[-1]
                       for p in picked if p["band"] == b)
        for size, want in wants.items():
            if have.get(size, 0) != want:
                bad.append(f"band {b} size {size}: {have.get(size, 0)} "
                           f"selected, quota {want}")
    for b, wants in (ROLE_QUOTA if role_quota is None else role_quota).items():
        have = Counter(p.get("role") for p in picked if p["band"] == b)
        for role, want in wants.items():
            if have.get(role, 0) != want:
                bad.append(f"band {b} role {role}: {have.get(role, 0)} "
                           f"selected, quota {want}")
    seeds = [p["seed"] for p in picked]
    if len(seeds) != len(set(seeds)):
        bad.append("duplicate deal seeds: one-state-per-deal violated")
    return bad


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
    if row.get("schema") == "deep-lead-state-v1":
        from shengji.state_replay import replay_deep_lead
        return replay_deep_lead(row)
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
    ap.add_argument("--dry-run", action="store_true",
                    help="select and report contract compliance; write nothing")
    ap.add_argument("--census", action="store_true",
                    help="report (band,size) availability and exit without "
                         "writing; answers whether a size quota is feasible")
    ap.add_argument("--side", default="dev", choices=("dev", "calib"),
                    help="REPORT is never selectable here: it is reserved for a "
                         "single preregistered audit and must not be inspected "
                         "during design.")
    args = ap.parse_args()

    if args.n != 512:
        print(f"REFUSING: --n {args.n}. The registered band/size/role quotas "
              f"are a 512-STATE CONTRACT (170/171/171); any other n would "
              f"satisfy no declared allocation.")
        sys.exit(3)
    if not (args.census or args.dry_run) and dirty_at_start():
        print("REFUSING: the tree is dirty. A frozen artifact from a dirty "
              "tree cannot be tied to the code that produced it — the previous "
              "version recorded tree_dirty=true and was not promotion-grade "
              "(Codex). Commit first.")
        sys.exit(3)
    if not (args.census or args.dry_run) and os.path.exists(args.out):
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
                if split.get(row["seed"]) != args.side:
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
                    # Carried onto the row. Without it the role-balancing loop
                    # below found no matching options, fell through to its
                    # "take any remaining deal" fallback every iteration, and
                    # reported `?` in the manifest — a mechanism that looked
                    # implemented and was not.
                    "role": "attacker" if rnd.is_attacker(seat) else "defender",
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
    if getattr(args, "census", False):
        # Availability BEFORE selection. Whether a predeclared size quota is
        # satisfiable at all is a property of the corpus, not of the selector,
        # and guessing a quota that the corpus cannot supply would make the
        # freezer refuse forever. Reports and exits without writing.
        cens = defaultdict(Counter)
        for seed, rows in by_deal.items():
            for r in rows:
                cens[r["band"]][r["stratum"].split("/")[-1]] += 1
        deals = defaultdict(Counter)
        for seed, rows in by_deal.items():
            for b in {r["band"] for r in rows}:
                sizes = {r["stratum"].split("/")[-1]
                         for r in rows if r["band"] == b}
                for sz in sizes:
                    deals[b][sz] += 1
        print(f"CENSUS side={args.side}  deals={len(by_deal)}  "
              f"replay_errors={errors}")
        print(f"  {'band':6} {'quota':>6} | rows small/med/wide | "
              f"DEALS able to supply small/med/wide")
        for b in ("early", "mid", "late"):
            q = BAND_QUOTA.get(b, 0)
            print(f"  {b:6} {q:>6} | "
                  f"{cens[b]['small']:5d}/{cens[b]['med']:5d}/"
                  f"{cens[b]['wide']:5d} | "
                  f"{deals[b]['small']:5d}/{deals[b]['med']:5d}/"
                  f"{deals[b]['wide']:5d}")
        print("\n  DEALS is the binding column: one state per deal, so a band "
              "can only fill a size bucket from distinct deals able to supply "
              "it.")
        short = [(b, sz, deals[b][sz], w)
                 for b, ws in SIZE_QUOTA.items() for sz, w in ws.items()
                 if deals[b][sz] < w]
        if short:
            print("  INFEASIBLE cells for the current SIZE_QUOTA:")
            for b, sz, have, want in short:
                print(f"    {b}/{sz}: {have} deals available, quota {want}")
        else:
            print("  current SIZE_QUOTA is satisfiable on availability")
        sys.exit(0)

    # Fill each band by chasing the LIVE (size, role) deficit.
    #
    # The previous selector chose a deal first — by role, first-fit — and only
    # then picked the least-held size among that deal's rows. Size therefore
    # never influenced WHICH deal was taken, so the size stratum was recorded
    # rather than enforced and the v3 sets came out with 0 early/small and 151
    # late/small (Codex). Here the scarcest unmet size cell selects the deal.
    #
    # Scarcity, not need, drives the order: a cell with 19 needed from 33
    # available must be served before one needing 98 from 2346, or the deals
    # that could have satisfied it get consumed by the abundant cell first.
    need_size = {b: dict(SIZE_QUOTA.get(b, {})) for b in BANDS}
    need_role = {b: dict(ROLE_QUOTA.get(b, {})) for b in BANDS}

    supply = defaultdict(lambda: defaultdict(list))   # band -> size -> [seed]
    for seed, rows in by_deal.items():
        for r in rows:
            supply[r["band"]][size_of(r)].append(seed)

    for b in BANDS:
        while sum(need_size[b].values()) > 0:
            live = {sz: [d for d in supply[b][sz] if d not in used_deals]
                    for sz, n in need_size[b].items() if n > 0}
            if not live:
                break
            # slack = how many spare deals this cell has; smallest slack first
            sz = min(live, key=lambda z: (len(live[z]) - need_size[b][z], z))
            if len(live[sz]) < need_size[b][sz]:
                break                      # unsatisfiable; contract will refuse
            short_roles = [r for r, n in need_role[b].items() if n > 0]
            chosen = None
            for seed in live[sz]:
                rows = [r for r in by_deal[seed]
                        if r["band"] == b and size_of(r) == sz]
                pref = [r for r in rows if r.get("role") in short_roles]
                if pref:
                    chosen = (seed, sorted(
                        pref, key=lambda d: (d["tricks"], d["ply"],
                                             d["seat"]))[0])
                    break
            if chosen is None:
                seed = live[sz][0]
                rows = sorted((r for r in by_deal[seed]
                               if r["band"] == b and size_of(r) == sz),
                              key=lambda d: (d["tricks"], d["ply"], d["seat"]))
                chosen = (seed, rows[0])
            seed, row = chosen
            used_deals.add(seed)
            picked.append(row)
            need_size[b][sz] -= 1
            if row.get("role") in need_role[b]:
                need_role[b][row["role"]] -= 1

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
        "one_state_per_deal": True, "side": args.side, "leads_only": True,
        "band_quota": BAND_QUOTA,
        "band_deals_available": available,
        "bands_selected": dict(Counter(p["band"] for p in picked)),
        "roles_selected": dict(Counter(p.get("role", "?") for p in picked)),
        "roles_by_band": {b: dict(Counter(p.get("role", "?") for p in picked
                                          if p["band"] == b)) for b in BANDS},
        "sizes_by_band": {b: dict(Counter(p["stratum"].split("/")[-1]
                                          for p in picked if p["band"] == b))
                          for b in BANDS},
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
    violations = check_contract(picked, args.n, errors)
    if getattr(args, "dry_run", False):
        print(f"DRY RUN side={args.side}  picked={len(picked)}  "
              f"replay_errors={errors}")
        for b in BANDS:
            sz = Counter(size_of(p) for p in picked if p["band"] == b)
            ro = Counter(p.get("role") for p in picked if p["band"] == b)
            print(f"  {b:6} n={sum(1 for p in picked if p['band']==b):3d} "
                  f"size {dict(sz)}  role {dict(ro)}")
        print(f"  contract violations: {len(violations)}")
        for v in violations:
            print(f"   - {v}")
        sys.exit(0 if not violations else 5)

    publish_or_refuse(payload, args.out, tmp, violations)

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
