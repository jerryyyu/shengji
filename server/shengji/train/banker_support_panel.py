"""Cheap retained-bury-corpus support census and paired sampler cost probe.

No gameplay/retraining: read existing DEV bury records, count false hand pins,
and sample at the first opponent decision on the first fixed N records.
Population counts describe this corpus only, never live human frequency.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import time

from ..ai.cwv_policy import sample_worlds
from ..ai.memory import Memory
from ..ai.registry import REGISTRY
from .banker_kitty_sampler import supported_bot_class
from .cwv_bury_diagnostic import reopen_state, derived_seed


def support_census(rows):
    result = {"rounds": len(rows), "banker_declarer_rounds": 0,
              "declared_card_buried_rounds": 0, "false_hand_pin_rounds": 0}
    for row in rows:
        state = row["state"]
        declaration = state["setup"].get("declaration")
        if not declaration or declaration["seat"] != state["initial_banker"]:
            continue
        result["banker_declarer_rounds"] += 1
        shown = Counter(declaration["cards"])
        kitty = Counter(row["buried"])
        remaining = Counter(state["banker_hand"]) - kitty
        result["declared_card_buried_rounds"] += int(any(kitty[c] for c in shown))
        result["false_hand_pin_rounds"] += int(any(remaining[c] < n for c, n in shown.items()))
    return result


def sample_record(row, worlds):
    rnd = reopen_state(row["state"])
    rnd.bury(rnd.banker, row["buried"])
    first = row["transcript"][0]
    rnd.play(first["seat"], first["attempted"])
    if rnd.turn == rnd.banker:
        raise ValueError("expected first opponent decision")
    mem = Memory(rnd, rnd.turn)
    base = REGISTRY["mc-s0-report-lcb"]
    counts = {}
    for name, cls in (("baseline", base), ("union-support", supported_bot_class(base))):
        bot = cls(seed=derived_seed("banker-support-sampler-cost-v1", row["state"]["index"]))
        start, cpu = time.perf_counter(), time.process_time()
        samples, attempts = sample_worlds(bot, rnd, rnd.turn, worlds, mem=mem)
        counts[name] = {"worlds": len(samples), "requested": worlds,
                        "attempts": attempts, "wall_seconds": time.perf_counter() - start,
                        "cpu_seconds": time.process_time() - cpu,
                        "sampler": bot._sampler_snapshot()}
    return {"index": row["state"]["index"], "actor": rnd.turn,
            "banker_declarer": rnd.declaration is not None and rnd.declaration["seat"] == rnd.banker,
            "arms": counts}


def main(argv=None):
    import os
    from .search_screen import _publish
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--sample-states", type=int, default=52)
    parser.add_argument("--worlds", type=int, default=32)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.sample_states < 1 or args.worlds < 1 or os.environ.get("SHENGJI_REQUIRE_VOIDS") != "1":
        parser.error("positive sample-states/worlds and SHENGJI_REQUIRE_VOIDS=1 required")
    if args.out.exists():
        parser.error("choose a fresh output file")
    paths = sorted(args.archive.glob("arm-*-hybrid.json"))
    rows = [json.loads(p.read_text()) for p in paths]
    if len(rows) < args.sample_states or len({r["state"]["index"] for r in rows}) != len(rows):
        parser.error("insufficient or duplicated corpus states")
    rows.sort(key=lambda row: row["state"]["index"])
    result = {"scope": "existing hybrid-bury DEV corpus; no new gameplay result",
              "source_root": str(args.archive.resolve()), "census": support_census(rows),
              "sample_selection": "first N indices, no selection on support/outcomes",
              "samples": [sample_record(row, args.worlds) for row in rows[:args.sample_states]]}
    result["totals"] = {
        arm: {key: sum(row["arms"][arm][key] for row in result["samples"])
              for key in ("worlds", "requested", "attempts", "wall_seconds", "cpu_seconds")}
        for arm in ("baseline", "union-support")}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    _publish(args.out, result)
    print(json.dumps({k: v for k, v in result.items() if k != "samples"}, indent=2))


if __name__ == "__main__":
    main()
