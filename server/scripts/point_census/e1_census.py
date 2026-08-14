"""E1: manifest-pinned human-vs-SmartBot disagreement census (stdout only)."""
from __future__ import annotations

import argparse
import copy
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, "server")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (emit, identity_receipt, iter_decisions,  # noqa: E402
                    legal_point_actions, load_validated_manifest,
                    trick_context)
from shengji.ai.registry import make_bot  # noqa: E402
from shengji.engine.cards import points  # noqa: E402
from shengji.engine.legal import beats  # noqa: E402


def classify(rnd, seat, human, bot_action, smart):
    is_lead, winning, partner, tpts, _ = trick_context(rnd, seat)
    hpts = sum(points(c) for c in human)
    bpts = sum(points(c) for c in bot_action)
    if is_lead:
        return f"LEAD point-card human={hpts > 0}" if (hpts > 0) != (bpts > 0) else None
    _, inc_suit, inc_top = winning[0], winning[1], winning[2]
    lead = rnd.trick.plays[0].cards
    is_last = len(rnd.trick.plays) == 3
    if partner:
        if hpts != bpts and legal_point_actions(rnd, seat):
            return f"FEED h{'>' if hpts > bpts else '<'}b last={is_last}"
        return None
    o = rnd.ordering
    hw = beats(human, lead, inc_suit, inc_top, o)[0]
    bw = beats(bot_action, lead, inc_suit, inc_top, o)[0]
    if hw != bw:
        return (f"CONTEST human_win={hw} "
                f"tpts{'>=10' if tpts >= 10 else '<10'} last={is_last}")
    if not hw and hpts != bpts:
        return f"LOSING-DISCARD h{'>' if hpts > bpts else '<'}b"
    return None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--logs-dir", default="logs")
    ap.add_argument("--manifest",
                    default="server/scripts/point_census/manifest.json")
    ap.add_argument("--expected-manifest-sha256", required=True)
    args = ap.parse_args()
    manifest, ordered, manifest_sha = load_validated_manifest(
        args.manifest, args.logs_dir, args.expected_manifest_sha256)
    smart = make_bot("smart")
    n = agree = refused = 0
    classes: Counter = Counter()
    contexts: Counter = Counter()
    for file, rno, index, rnd, seat, human in iter_decisions(ordered):
        try:
            bot_action = smart.decide_play(copy.deepcopy(rnd), seat)
        except Exception:
            refused += 1
            continue
        n += 1
        is_lead, _, partner, _, _ = trick_context(rnd, seat)
        contexts["lead" if is_lead
                 else ("follow-partner" if partner else "follow-opp")] += 1
        if sorted(human) == sorted(bot_action):
            agree += 1
            continue
        key = classify(rnd, seat, human, bot_action, smart)
        if key:
            hand_n = len(rnd.hands[seat])
            phase = "end" if hand_n <= 8 else ("mid" if hand_n <= 17 else "early")
            classes[f"{key} | {phase}"] += 1
    emit({
        "schema": "point-census-e1-v2",
        "receipt": identity_receipt(manifest, manifest_sha, Path(__file__)),
        "decisions": n, "exact_agreement": agree,
        "replay_refusals": refused,
        "contexts": dict(contexts),
        "disagreement_classes": dict(sorted(classes.items())),
    })


if __name__ == "__main__":
    main()
