"""P1: boss-class table for feed opportunities — human games AND MC rollout
worlds, classified with public info (Memory).  P2: points_left at human
endgame decline states.  Stdout only.
"""
from __future__ import annotations

import argparse
import copy
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, "server")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (classify_boss, decision_key, emit,  # noqa: E402
                    identity_receipt, legal_point_actions,
                    load_validated_manifest, iter_decisions, sha256_bytes,
                    canonical, trick_context)
from shengji.ai.heuristic import HeuristicBot  # noqa: E402
from shengji.ai.memory import Memory  # noqa: E402
from shengji.ai.registry import make_bot  # noqa: E402
from shengji.engine.cards import points  # noqa: E402
from shengji.engine.legal import beats  # noqa: E402

TABLE_KEYS = ("literal", "inferred_strict", "inferred_loose", "open", "complex")


class CountingHeuristic(HeuristicBot):
    """Observe only opportunities with an engine-legal point action."""

    def __init__(self, tallies):
        super().__init__()
        self._point_census_tallies = tallies

    def _follow(self, rnd, seat):
        action = super()._follow(rnd, seat)
        t = rnd.trick
        if t is not None and 0 < len(t.plays) < 3:
            _, winning, partner, _, to_act = trick_context(rnd, seat)
            if partner and legal_point_actions(rnd, seat):
                cls, _ = classify_boss(
                    rnd, seat, winning[0], winning[1], winning[2], to_act)
                self._point_census_tallies[cls]["n"] += 1
                self._point_census_tallies[cls]["fed"] += \
                    sum(points(c) for c in action) > 0
        return action


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--logs-dir", default="logs")
    ap.add_argument("--manifest",
                    default="server/scripts/point_census/manifest.json")
    ap.add_argument("--expected-manifest-sha256", required=True)
    ap.add_argument("--rollout-states", type=int, default=12)
    args = ap.parse_args()
    manifest, ordered, manifest_sha = load_validated_manifest(
        args.manifest, args.logs_dir, args.expected_manifest_sha256)
    msha = sha256_bytes(canonical(manifest))
    smart = make_bot("smart")

    # P1a: human feed opportunities classified by boss class.
    human = {k: Counter() for k in TABLE_KEYS}
    rollout_sample = []
    decline_points_left = []
    for file, rno, index, rnd, seat, hcards in iter_decisions(ordered):
        is_lead, winning, partner, tpts, to_act = trick_context(rnd, seat)
        if not is_lead and partner and len(rnd.trick.plays) < 3 \
                and legal_point_actions(rnd, seat):
            cls, _ = classify_boss(rnd, seat, winning[0], winning[1],
                                   winning[2], to_act)
            fed = sum(points(c) for c in hcards) > 0
            human[cls]["n"] += 1
            human[cls]["fed"] += fed
        if not is_lead and not partner and len(rnd.hands[seat]) <= 8:
            try:
                b = smart.decide_play(copy.deepcopy(rnd), seat)
            except Exception:
                raise SystemExit("REFUSED: policy replay failed")
            if sorted(hcards) != sorted(b):
                o, lead = rnd.ordering, rnd.trick.plays[0].cards
                hw = beats(hcards, lead, winning[1], winning[2], o)[0]
                bw = beats(b, lead, winning[1], winning[2], o)[0]
                if bw and not hw and tpts < 10:
                    decline_points_left.append(Memory(rnd, seat).points_left())
        if (rnd.trick is not None and rnd.trick.plays
                and len(rollout_sample) < args.rollout_states
                and decision_key(msha, file, rno, index) % 149 == 0):
            rollout_sample.append((copy.deepcopy(rnd), seat,
                                   decision_key(msha, file, rno, index)))

    # P1b: rollout-policy feed behavior by boss class inside MC worlds.
    tallies = {k: Counter() for k in TABLE_KEYS}

    Base = type(make_bot("mc-s0-report-lcb", seed=0))
    for rnd, seat, key in rollout_sample:
        bot = Base(seed=key)
        bot.rollout_policy = CountingHeuristic(tallies)
        try:
            bot.decide_play(copy.deepcopy(rnd), seat)
        except Exception:
            raise SystemExit("REFUSED: rollout probe failed")

    decline_points_left.sort()
    emit({
        "schema": "point-census-p1p2-v2",
        "receipt": identity_receipt(manifest, manifest_sha, Path(__file__)),
        "p1_human_by_class": {k: dict(v) for k, v in human.items()},
        "p1_rollout_by_class": {k: dict(v) for k, v in tallies.items()},
        "p1_rollout_states": len(rollout_sample),
        "p2_decline_end": {
            "n": len(decline_points_left),
            "points_left_zero": sum(1 for p in decline_points_left if p == 0),
            "points_left_median": (decline_points_left[len(decline_points_left) // 2]
                                   if decline_points_left else None),
        },
    })


if __name__ == "__main__":
    main()
