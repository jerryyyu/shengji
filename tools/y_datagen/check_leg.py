#!/usr/bin/env python3
"""Check a sealed served-policy trajectory leg before admitting it to extraction."""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path

from archive_leg import sealed_members


def check_play(decision):
    if decision.get("reason") or decision["schema"] != "pv-search-decision-v1":
        raise ValueError("play fallback")
    stages = decision["belief_fallback_by_stage"]
    if (any(decision[key] != 0 for key in ("belief_fallback", "belief_fallback_any", "belief_fallback_all_draws"))
            or any(stages[stage] != 0 for stage in ("base", "adaptive_worlds", "lead_confirm"))):
        raise ValueError("play belief fallback")
    unified = decision["unified"]
    if unified["shared"] != 1 or any(unified[k] != 0 for k in ("missed", "trunk", "value_left", "reply_left")):
        raise ValueError("incomplete unified play coverage")
    if any(type(unified[k]) is not int or unified[k] < 0 for k in ("value_rows", "reply_rows")):
        raise ValueError("invalid unified row counts")
    seconds = decision["seconds"]
    if type(seconds) not in (float, int) or not math.isfinite(seconds) or seconds < 0:
        raise ValueError("invalid play time")
    return seconds


def check_leg(store, terminal, expected_sha):
    members, seal = sealed_members(store, terminal, expected_sha)
    total = Counter()
    over_3s = 0
    value_rows = reply_rows = 0
    for name, digest in members.items():
        if not name.endswith(".jsonl"):
            continue
        path = store / name
        side_name = str(Path(name).with_suffix(".json"))
        side_bytes = (store / side_name).read_bytes()
        if hashlib.sha256(side_bytes).hexdigest() != members[side_name]:
            raise ValueError("sidecar differs from seal")
        side = json.loads(side_bytes)
        counts = side["counts"]
        if any(counts.get(k, 0) for k in ("short_searches", "play_fallback", "bury_fallback", "bury_belief_fallbacks")):
            raise ValueError("short search or fallback in shard")
        kinds = Counter()
        actual = hashlib.sha256()
        with path.open("rb") as stream:
            for line in stream:
                actual.update(line)
                row = json.loads(line)
                kind = row["decision_kind"]
                kinds[kind] += 1
                if kind == "play":
                    decision = row["allocation"]["serving_decision"]
                    over_3s += check_play(decision) >= 3
                    value_rows += decision["unified"]["value_rows"]
                    reply_rows += decision["unified"]["reply_rows"]
                elif kind == "bury":
                    allocation = row["allocation"]
                    serving = allocation["serving_decision"]
                    if (allocation.get("reason") == "serving_budget_fallback" or serving.get("fallback_reason")
                            or serving.get("bury_belief_error") or serving["bury_belief_fallbacks"] != 0):
                        raise ValueError("bury fallback")
                else:
                    raise ValueError("unknown decision kind")
        if actual.hexdigest() != digest:
            raise ValueError("trajectory differs from seal")
        if (kinds["bury"] != 2 or kinds["play"] <= 0 or kinds["play"] != counts["decisions"]
                or sum(kinds.values()) != side["records"]):
            raise ValueError("incomplete mirrored play or bury coverage")
        total.update(kinds)
    if total["bury"] != seal["rounds"] or min(value_rows, reply_rows) <= 0:
        raise ValueError("incomplete leg")
    return {"status": "PASS", "terminal_sha256": expected_sha, "run_id": seal["run_id"],
            "rounds": seal["rounds"], "play_rows": total["play"], "play_over_3s": over_3s,
            "value_rows": value_rows, "reply_rows": reply_rows}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("store", type=Path)
    parser.add_argument("terminal", type=Path)
    parser.add_argument("terminal_sha256")
    args = parser.parse_args()
    print(json.dumps(check_leg(args.store, args.terminal, args.terminal_sha256)))
