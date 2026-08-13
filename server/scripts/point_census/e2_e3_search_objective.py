"""E2: production MC vs human on census classes.  E3: LEVEL_OBJECTIVE flips
with verified same-worlds binding (RNG/sampler/candidate equality), failing
closed on any refusal.  Stdout only.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, "server")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (canonical, decision_key, emit,  # noqa: E402
                    identity_receipt, legal_point_actions,
                    load_validated_manifest, iter_decisions, sha256_bytes,
                    trick_context)
from shengji.ai.registry import make_bot  # noqa: E402
from shengji.engine.cards import points  # noqa: E402
from shengji.engine.legal import beats  # noqa: E402

CAP = 40


def snapshot(bot) -> dict:
    return {"rng": sha256_bytes(repr(bot.rng.getstate()).encode()),
            "sampler": bot._sampler_snapshot(),
            "rollouts": int(getattr(bot, "rollouts", 0))}


def bound_decision(cls_maker, seed, rnd, seat):
    bot = cls_maker(seed=seed)
    before = snapshot(bot)
    action = bot.decide_play(copy.deepcopy(rnd), seat)
    record = bot.last_decision_record
    candidates = tuple(tuple(c) for c in record["candidates"]) if record else None
    return action, before, snapshot(bot), candidates


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--logs-dir", default="logs")
    ap.add_argument("--manifest",
                    default="server/scripts/point_census/manifest.json")
    args = ap.parse_args()
    manifest, ordered = load_validated_manifest(args.manifest, args.logs_dir)
    msha = sha256_bytes(canonical(manifest))
    smart = make_bot("smart")
    Base = type(make_bot("mc-s0-report-lcb", seed=0))
    Level = type("Level", (Base,), {"LEVEL_OBJECTIVE": True})

    per: dict[str, list] = {"FEED-EARLIER": [], "DECLINE-END": [],
                            "CONTROL": [], "ENDGAME-ALL": []}
    for file, rno, index, rnd, seat, human in iter_decisions(ordered):
        key = decision_key(msha, file, rno, index)
        is_lead, winning, partner, tpts, _ = trick_context(rnd, seat)
        try:
            b = smart.decide_play(copy.deepcopy(rnd), seat)
        except Exception:
            raise SystemExit("REFUSED: policy replay failed")
        same = sorted(human) == sorted(b)
        hpts = sum(points(c) for c in human)
        bpts = sum(points(c) for c in b)
        state = (copy.deepcopy(rnd), seat, human, b, key)
        if (not same and not is_lead and partner and hpts > bpts
                and len(rnd.trick.plays) < 3 and legal_point_actions(rnd, seat)
                and len(per["FEED-EARLIER"]) < CAP):
            per["FEED-EARLIER"].append(state)
        elif not same and not is_lead and not partner and tpts < 10 \
                and len(rnd.hands[seat]) <= 8 and len(per["DECLINE-END"]) < CAP:
            o, lead = rnd.ordering, rnd.trick.plays[0].cards
            hw = beats(human, lead, winning[1], winning[2], o)[0]
            bw = beats(b, lead, winning[1], winning[2], o)[0]
            if bw and not hw:
                per["DECLINE-END"].append(state)
        if key % 97 == 0 and len(per["CONTROL"]) < 30:
            per["CONTROL"].append(state)
        if (len(rnd.hands[seat]) <= 8 and key % 11 == 0
                and len(per["ENDGAME-ALL"]) < CAP):
            per["ENDGAME-ALL"].append(state)

    out = {}
    for cls, states in per.items():
        row = Counter()
        for rnd, seat, human, b, key in states:
            a_mc, pre1, post1, cand1 = bound_decision(Base, 90_000 + key, rnd, seat)
            a_lv, pre2, post2, cand2 = bound_decision(Level, 90_000 + key, rnd, seat)
            if pre1["rng"] != pre2["rng"]:
                raise SystemExit("REFUSED: pre-decision RNG states differ")
            binding_ok = (cand1 == cand2
                          and post1["sampler"] == post2["sampler"]
                          and post1["rollouts"] == post2["rollouts"])
            row["n"] += 1
            row["binding_verified"] += binding_ok
            if not binding_ok:
                row["binding_failures"] += 1
                continue
            if sorted(a_mc) == sorted(human):
                row["mc_matches_human"] += 1
            elif sorted(a_mc) == sorted(b):
                row["mc_matches_smart"] += 1
            else:
                row["mc_other"] += 1
            if sorted(a_lv) != sorted(a_mc):
                row["level_flips"] += 1
                row["flips_to_human"] += sorted(a_lv) == sorted(human)
        out[cls] = dict(row)
    emit({
        "schema": "point-census-e2e3-v2",
        "receipt": identity_receipt(manifest),
        "binding": ("same-seed twins verified by pre-RNG hash, candidate-list "
                    "equality, sampler snapshot and rollout-counter equality; "
                    "binding failures are counted, never silently skipped"),
        "classes": out,
    })


if __name__ == "__main__":
    main()
