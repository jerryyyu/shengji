"""E2: production MC vs human on census classes.  E3: LEVEL_OBJECTIVE flips
with verified same-worlds binding (RNG/sampler/candidate equality), failing
closed on any refusal.  Stdout only.
"""
from __future__ import annotations

import argparse
import copy
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
    return {
        "rng": sha256_bytes(repr(bot.rng.getstate()).encode()),
        "sampler": bot._sampler_snapshot(),
        "counters": {name: int(getattr(bot, name, 0)) for name in (
            "rollouts", "search_calls", "short_search_decisions",
            "zero_world_decisions", "bury_rollouts", "bury_search_calls",
            "bury_short_searches", "exact_endgame_calls",
            "exact_endgame_attempts", "exact_endgame_refusals",
            "exact_endgame_budget_exceeded", "exact_endgame_sessions",
            "exact_endgame_nodes", "exact_endgame_cache_hits")},
    }


def _world_projection(sampled) -> dict:
    if sampled is None:
        return {"accepted": False}
    hands, buried = sampled
    return {
        "accepted": True,
        "hands": [[int(seat), list(hands[seat])] for seat in sorted(hands)],
        "buried": list(buried),
    }


def _record_binding(record) -> dict | None:
    if record is None:
        return None
    report = record.get("report_fold")
    report_work = (None if report is None else {
        key: report.get(key) for key in (
            "worlds", "attempts", "rejected", "complete", "seed")})
    return {
        "schema": record.get("schema"),
        "n_determinizations": record.get("n_determinizations"),
        "confidence_override": record.get("confidence_override"),
        "adaptive_allocation": record.get("adaptive_allocation"),
        "random_allocation": record.get("random_allocation"),
        "margin": record.get("margin"),
        "report_rule": record.get("report_rule"),
        "report_min_gain": record.get("report_min_gain"),
        "report_worlds_requested": record.get("report_worlds_requested"),
        "report_alpha": record.get("report_alpha"),
        "rng_state_sha256": sha256_bytes(
            repr(record.get("rng_state")).encode()),
        "report_seed": record.get("report_seed"),
        "allocation_seed": record.get("allocation_seed"),
        "candidates": record.get("candidates"),
        "eligible_indices": record.get("eligible_indices"),
        "n_by_candidate": record.get("n_by_candidate"),
        "worlds": record.get("worlds"),
        "alloc": record.get("alloc"),
        "work": record.get("work"),
        "report_work": report_work,
        "sampler_counters": record.get("sampler_counters"),
    }


def bound_decision(cls_maker, seed, rnd, seat):
    bot = cls_maker(seed=seed)
    before = snapshot(bot)
    worlds = []
    original_sample = bot._sample_hands

    def recording_sample(*args, **kwargs):
        sampled = original_sample(*args, **kwargs)
        worlds.append(_world_projection(sampled))
        return sampled

    bot._sample_hands = recording_sample
    action = bot.decide_play(copy.deepcopy(rnd), seat)
    after = snapshot(bot)
    return {
        "action": list(action),
        "binding": {
            "before": before,
            "after": after,
            "counter_delta": {
                key: after["counters"][key] - before["counters"][key]
                for key in before["counters"]},
            "sampler_delta": {
                key: after["sampler"][key] - before["sampler"][key]
                for key in before["sampler"]},
            "record": _record_binding(bot.last_decision_record),
            "world_commitment_count": len(worlds),
            "world_commitments_sha256": sha256_bytes(canonical(worlds)),
        },
    }


def require_same_binding(base: dict, level: dict) -> str:
    if base["binding"] != level["binding"]:
        raise SystemExit(
            "REFUSED: objective arms differ in RNG/world/work binding")
    return sha256_bytes(canonical(base["binding"]))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--logs-dir", default="logs")
    ap.add_argument("--manifest",
                    default="server/scripts/point_census/manifest.json")
    ap.add_argument("--expected-manifest-sha256", required=True)
    ap.add_argument("--cap-per-class", type=int, default=CAP)
    args = ap.parse_args()
    if not 0 <= args.cap_per_class <= CAP:
        raise SystemExit(f"REFUSED: --cap-per-class must be in [0,{CAP}]")
    manifest, ordered, manifest_sha = load_validated_manifest(
        args.manifest, args.logs_dir, args.expected_manifest_sha256)
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
                and len(per["FEED-EARLIER"]) < args.cap_per_class):
            per["FEED-EARLIER"].append(state)
        elif (not same and not is_lead and not partner and tpts < 10
              and len(rnd.hands[seat]) <= 8
              and len(per["DECLINE-END"]) < args.cap_per_class):
            o, lead = rnd.ordering, rnd.trick.plays[0].cards
            hw = beats(human, lead, winning[1], winning[2], o)[0]
            bw = beats(b, lead, winning[1], winning[2], o)[0]
            if bw and not hw:
                per["DECLINE-END"].append(state)
        if (key % 97 == 0
                and len(per["CONTROL"]) < min(30, args.cap_per_class)):
            per["CONTROL"].append(state)
        if (len(rnd.hands[seat]) <= 8 and key % 11 == 0
                and len(per["ENDGAME-ALL"]) < args.cap_per_class):
            per["ENDGAME-ALL"].append(state)

    out = {}
    for cls, states in per.items():
        row = Counter()
        for rnd, seat, human, b, key in states:
            base = bound_decision(Base, 90_000 + key, rnd, seat)
            level = bound_decision(Level, 90_000 + key, rnd, seat)
            binding_digest = require_same_binding(base, level)
            a_mc, a_lv = base["action"], level["action"]
            row["n"] += 1
            row["binding_verified"] += 1
            row[f"binding_digest:{binding_digest}"] += 1
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
        "receipt": identity_receipt(manifest, manifest_sha, Path(__file__)),
        "binding": ("same-seed twins require exact pre/post RNG, complete "
                    "sampled-world sequence commitment, candidates, allocation, "
                    "per-candidate/report work, sampler before/after/delta and "
                    "search counter deltas; any drift refuses the artifact"),
        "cap_per_class": args.cap_per_class,
        "classes": out,
    })


if __name__ == "__main__":
    main()
