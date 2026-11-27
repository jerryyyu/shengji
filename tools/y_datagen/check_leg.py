#!/usr/bin/env python3
"""Check a sealed served-policy trajectory leg before admitting it to extraction."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

from archive_leg import sealed_members
from shard_quality import check_play as check_play, check_shard


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
        kinds, slow, values, replies = check_shard(path, side, digest)
        over_3s += slow
        value_rows += values
        reply_rows += replies
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
