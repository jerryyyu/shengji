"""Run the pinned S61 identity harness with RT3-FT on both sides and S149 on ex.

Place exploit_duel_s61.py and hypotheses.py from the RT3FS kit on PYTHONPATH.
Pass S149_UNIFIED_CKPT and S149_BELIEF_CKPT via both harness side overrides,
and S149_ACTION_CKPT via --exploiter-env only. The underlying harness binds
these paths and bytes into its resume identity.
"""
from functools import lru_cache
import json
import os
from pathlib import Path

import exploit_duel_s61 as duel
import duel_arm
import duel_rows

original_play = duel.play_mirror
original_binding = duel._source_binding
if (duel._sha256(duel.HERE) != "813e6ed64fbb80d81d7ec064096ec6846ed9ca47e90ad2c6632d9451e2c8bd1d"
        or duel._sha256(Path(duel.H.__file__)) != "4365a15d6c868263eaa64fca0038168342f2ebd96689da36f46be4e2082e49ce"):
    raise ValueError("unexpected S61 duel kit")


@lru_cache(maxsize=2)
def build(side, words):
    paths = dict(words)
    keys = {"S149_UNIFIED_CKPT", "S149_BELIEF_CKPT"}
    if side == "ex":
        keys.add("S149_ACTION_CKPT")
    if set(paths) != keys or len(words) != len(keys):
        raise ValueError(f"{side}: incorrect S149 package arguments")
    maps = dict(item.split("=", 1) for item in os.environ["FIND_GAPS_PATH_MAP"].split(";") if item)
    return duel_arm.arm_factory(mappings=maps, unified_path=paths["S149_UNIFIED_CKPT"],
                                belief_path=paths["S149_BELIEF_CKPT"], action_path=paths.get("S149_ACTION_CKPT"))


def play_mirror(arm, deal_seed, mirror, keep_history, defender_env, exploiter_env, plan_entry):
    if arm != "identity" or defender_env == exploiter_env:
        raise ValueError("S149 requires identity and distinct control and challenger arguments")
    buries = []
    observations = {"r45": [], "ex": []}

    def variant(words):
        side = "r45" if words == defender_env else "ex"
        name, factory = build(side, tuple(words))

        def make(seed):
            bot = factory(seed)
            duel_rows.record_bury(bot, side, buries)
            return duel_rows.record_play(bot, observations[side])

        return name, make

    previous = duel.variant_factory
    duel.variant_factory = variant
    try:
        row = original_play(arm, deal_seed, mirror, keep_history, defender_env, exploiter_env, plan_entry)
    finally:
        duel.variant_factory = previous
    row["s149_bury"] = buries
    row["s149"] = observations
    duel_rows.validate_row(row)
    return row


def source_binding(denv=(), eenv=()):
    sources = original_binding(denv, eenv)
    for path in map(Path, (__file__, duel_rows.__file__, duel_arm.__file__)):
        sources[path.name] = duel._sha256(path)
    return sources


def read_rows(out, *, arm, seed0, deals, plan):
    done = set()
    if not out.exists():
        return done
    with out.open("rb") as source:
        for line in source:
            if not line.endswith(b"\n"):
                raise ValueError("incomplete S149 row")
            row = json.loads(line)
            fresh = duel._validate_batch([row], arm=arm, seed0=seed0, deals=deals, plan=plan, expected=done)
            duel_rows.validate_row(row)
            done.update(fresh)
    return done


duel._read_rows = read_rows
duel.play_mirror = play_mirror
duel._source_binding = source_binding

if __name__ == "__main__":
    duel.main()
