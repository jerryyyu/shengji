"""E5: observational feed outcomes with legality filter and actor attribution.

An opportunity requires at least one LEGAL point-bearing follow (engine
ballot).  Actor-contributed points are reported separately from total trick
value.  Hold rates carry Wilson 95% intervals; no causal claim is made.
Stdout only.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, "server")
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (emit, group_events, identity_receipt,  # noqa: E402
                    legal_point_actions, load_validated_manifest, log_events,
                    trick_context, wilson)
from shengji.engine.cards import points  # noqa: E402
from shengji.rl.replay_log import EXCLUDE_PLAYERS, rebuild_round  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--logs-dir", default="logs")
    ap.add_argument("--manifest",
                    default="server/scripts/point_census/manifest.json")
    ap.add_argument("--expected-manifest-sha256", required=True)
    args = ap.parse_args()
    manifest, ordered, manifest_sha = load_validated_manifest(
        args.manifest, args.logs_dir, args.expected_manifest_sha256)
    groups = {g: {"n": 0, "held": 0, "actor_pts_played": 0,
                  "trick_pts_kept": 0, "trick_pts_lost": 0}
              for g in ("FED", "HELD")}
    for item in ordered:
        events = log_events(item.raw, item.name)
        first = next((event for event in events
                      if event.get("e") == "round_start"), None)
        if not first:
            continue
        excluded = {p["seat"] for p in first["players"]
                    if p["name"] in EXCLUDE_PLAYERS}
        for rno, evs in sorted(group_events(events, item.name).items()):
            rnd = rebuild_round(evs)
            if rnd is None:
                continue
            plays = [e for e in evs if e["e"] == "play"]
            tricks = [e for e in evs if e["e"] == "trick"]
            in_trick, ti, pending = 0, 0, []
            for e in plays:
                seat, cards = e["seat"], e["cards"]
                if (0 < in_trick < 3 and not e.get("bot")
                        and seat not in excluded):
                    is_lead, winning, partner, _, _ = trick_context(rnd, seat)
                    if not is_lead and partner and legal_point_actions(rnd, seat):
                        played_pts = sum(points(c) for c in cards)
                        pending.append(
                            ("FED" if played_pts > 0 else "HELD",
                             seat, ti, played_pts))
                try:
                    rnd.play(seat, list(cards))
                except Exception:
                    pending = []
                    break
                in_trick += 1
                if in_trick == 4:
                    in_trick, ti = 0, ti + 1
            for grp, seat, k, played_pts in pending:
                if k >= len(tricks):
                    continue
                trick = tricks[k]
                held = trick["winner"] % 2 == seat % 2
                g = groups[grp]
                g["n"] += 1
                g["held"] += held
                g["actor_pts_played"] += played_pts
                g["trick_pts_kept" if held else "trick_pts_lost"] += trick["points"]
    for g in groups.values():
        g["hold_rate_wilson95"] = wilson(g["held"], g["n"])
    emit({
        "schema": "point-census-e5-v2",
        "receipt": identity_receipt(manifest, manifest_sha, Path(__file__)),
        "note": ("observational only; opportunity requires a legal "
                 "point-bearing follow; trick totals include points "
                 "contributed by other seats"),
        "groups": groups,
    })


if __name__ == "__main__":
    main()
