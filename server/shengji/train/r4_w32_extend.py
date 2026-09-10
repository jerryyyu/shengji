"""Append missing admitted actions on retained worlds without resampling.

Old rollout columns remain unchanged. New folds are published separately; the
weight diagnostic binds its weights to those augmented folds before reduction.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import time

from .r4_w32_mc import BASE, reopen_state, require_capture_binding, _publish


def extend_matrix(old_indices, matrix, requested, score):
    """Call score(world-index, action-index) only for absent columns."""
    if len(set(old_indices)) != len(old_indices) or any(len(r) != len(old_indices) for r in matrix):
        raise ValueError("retained action matrix shape differs")
    missing = sorted(set(requested)-set(old_indices))
    indices = list(old_indices)+missing
    return indices, [list(row)+[score(wi, action) for action in missing]
                     for wi, row in enumerate(matrix)]


def extend(root: Path, ranking: dict, out: Path):
    capture_path = root/"private-world-values.json"
    capture = json.loads(capture_path.read_bytes())
    require_capture_binding(capture_path, ranking, root/"r4-marginals.json")
    raw = Path(capture["record_path"]).read_bytes()
    if hashlib.sha256(raw).hexdigest() != capture["record_sha256"]:
        raise ValueError("saved source trajectory changed")
    row = json.loads(raw)
    rnd = reopen_state(row["state"])
    rnd.bury(rnd.banker, row["buried"])
    for play in row["transcript"][:capture["decision"]]:
        rnd.play(play["seat"], play["attempted"])
    seat = rnd.turn
    if seat != capture["seat"]:
        raise ValueError("reopened acting seat differs")
    requested = set(ranking["baseline_shortlist"]).union(
        *(set(a["shortlist"]) for a in ranking["arms"].values()))
    for fold, n in (("selection", 30), ("report", 300)):
        parent = root/"mc"/fold/"private-world-values.json"
        parent_raw = parent.read_bytes()
        old = json.loads(parent_raw)
        parent_sha = hashlib.sha256(parent_raw).hexdigest()
        if (old["actor_sha256"] != capture["actor_sha256"] or old["fold"] != fold
                or len(old["worlds"]) != n or len(old["values_world_major"]) != n):
            raise ValueError("retained fold identity or population differs")
        expected = old["union_indices"]+sorted(requested-set(old["union_indices"]))
        target = out/fold/"private-world-values.json"
        if target.exists():
            saved = json.loads(target.read_bytes())
            if saved["extension_parent_sha256"] != parent_sha or saved["union_indices"] != expected:
                raise ValueError("completed extension differs from requested inputs")
            continue
        bot = BASE(seed=old["world_seed"])
        started = time.monotonic()

        def score(wi, action):
            hands, buried = old["worlds"][wi]
            sampled = {other: hands[other] for other in range(4) if other != seat}
            value = bot._score(bot._rollout(rnd, seat, sampled, buried,
                capture["actions"][action], exact_session=bot._new_exact_world_session(rnd, buried)))
            return value if rnd.is_attacker(seat) else -value

        if score(0, old["union_indices"][0]) != old["values_world_major"][0][0]:
            raise ValueError("extension continuation differs from retained rollout witness")
        indices, matrix = extend_matrix(old["union_indices"], old["values_world_major"], requested, score)
        result = {**old, "union_indices": indices, "actions": [capture["actions"][i] for i in indices],
                  "values_world_major": matrix, "means": [sum(r[i] for r in matrix)/n for i in range(len(indices))],
                  "extension_parent_sha256": parent_sha, "extension_parent": str(parent),
                  "extension_rollouts": n*(len(indices)-len(old["union_indices"])),
                  "extension_witness_rollouts": 1,
                  "extension_wall_s": time.monotonic()-started, "extension_new_worlds": 0}
        target.parent.mkdir(parents=True, exist_ok=True)
        _publish(target.parent/"actor.json", json.loads((root/"actor.json").read_bytes()))
        _publish(target, result)
