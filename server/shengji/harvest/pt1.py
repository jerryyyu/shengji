"""Extractor: PT1 privileged-teacher evidence (416 natural endgame states x 4
policy seeds = 1,664 records).

Source: ``shengji-pt1-evidence-76508ec-r7/groups/group-*.json`` (schema
``privileged-teacher-pt1-execution-group-v1``).  A group carries
``round_seed`` + ``state_key = [trump_rank, banker, role, threshold,
replicate]`` and four ``privileged-teacher-pt1-search-record-v1`` records
(one per production seed 0..3) that share ``legal_ballot`` (the exhaustive
set from ``ai.endgame.exhaustive_legal_actions``), the exact per-action
``evaluation_action_utilities`` / ``evaluation_final_points`` and three arms:
A (public production ``mc-s0-report-lcb``), B (the same search sampling the
true world) and C (``ExactWorldSession`` argmax).

State reconstruction
--------------------
The group stores hashes, not the state.  The natural capture procedure
(``privileged_teacher_pt1_natural._capture_round`` at commit 76508ec9, no
longer on main) is replayed here: deal ``Round(rank, banker,
random.Random(round_seed))``, let four production bots seeded from the round
seed declare / bury / play, and stop at the first play state where the
acting seat has the requested role, the longest hand equals the threshold,
the exhaustive legal set has >= 2 actions and production would run a
contested search.  The rebuilt state is accepted only when its
``pt0_public_state_sha256`` and true-world hash equal the group's.  The
replay costs ~25 s per group (pure Python), so groups run in a process pool.

Record mapping: ``action`` = arm C's selected action (``policy =
"pt1:ExactWorldSession"``); ``ballot`` = the exact legal ballot C chose from;
``production_ballot`` = arm A's production ballot; ``action_values`` = the
exact utilities/points for every legal action plus the three arms'
selections; ``outcome`` = null (the natural round was not scored; the exact
continuation values are the value labels).  Hidden hands -> private split.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any, Sequence

from .common import PT1_ROOT, ExtractResult, InputRegistry, action_key
from .legal import enumerate_legal
from .rebuild import (RebuildError, actor_role, hands_snapshot, replay_prefix,
                      round_from_setup)
from .schema import canonical_json, finalize_record, split_record

GROUP_SCHEMA = "privileged-teacher-pt1-execution-group-v1"
RECORD_SCHEMA = "privileged-teacher-pt1-search-record-v1"
NATURAL_PT1_SCHEMA = "privileged-teacher-pt1-natural-population-v1"
PRODUCTION_POLICY = "mc-s0-report-lcb"
POLICY = "pt1:ExactWorldSession"


class PT1FormatError(ValueError):
    pass


def _canonical_bytes(value: Any) -> bytes:
    return (canonical_json(value) + "\n").encode("ascii")


def _bot_seed(round_seed: int, seat: int) -> int:
    return int.from_bytes(hashlib.sha256(
        _canonical_bytes([NATURAL_PT1_SCHEMA, round_seed, seat])).digest()[:8], "big")


def _role(rnd, seat: int) -> str:
    return "banker-team" if seat % 2 == rnd.banker % 2 else "attacker-team"


def _production_search_eligible(rnd, seat: int) -> bool:
    from ..ai.registry import make_bot
    from ..engine.combos import decompose
    bot = make_bot(PRODUCTION_POLICY, seed=0)
    if bot.TRACTOR_LOCK and not rnd.trick.plays:
        pick = bot.canonical_lead(rnd, seat)
        dec = decompose(pick, rnd.ordering)
        if len(dec.components) == 1 and dec.components[0].pair_len >= 2:
            return False
    return len(bot._candidates(rnd, seat)) > 1


def world_sha256(rnd) -> str:
    payload = {"hands": [sorted(h) for h in rnd.hands],
               "buried": sorted(rnd.buried), "banker": rnd.banker,
               "trump_rank": rnd.trump_rank, "turn": rnd.turn}
    return hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def replay_capture(round_seed: int, rank: str, banker: int, role: str,
                   threshold: int) -> dict[str, Any]:
    """Re-run the natural capture for one group; returns the raw state fields.

    Runs in a worker process.  ``SHENGJI_REQUIRE_VOIDS=1`` mirrors the
    capture runtime (``strict_voids: true`` in the freeze).
    """
    os.environ.setdefault("SHENGJI_REQUIRE_VOIDS", "1")
    from ..ai.endgame import exhaustive_legal_actions
    from ..ai.registry import make_bot
    from ..engine.round import Round
    rnd = Round(rank, banker=banker, rng=random.Random(round_seed))
    deck = list(rnd.deck)
    bots = [make_bot(PRODUCTION_POLICY, seed=_bot_seed(round_seed, s))
            for s in range(4)]
    declarations: list[dict] = []
    while rnd.phase == "deal":
        seat, _, _ = rnd.deal_next()
        d = bots[seat].decide_declare(rnd, seat)
        if d is not None:
            rnd.declare(seat, d)
            declarations.append({"seat": seat, "cards": list(d)})
    for seat in range(4):
        d = bots[seat].decide_declare(rnd, seat, final=True)
        if d is not None:
            rnd.declare(seat, d)
            declarations.append({"seat": seat, "cards": list(d)})
        else:
            rnd.pass_declare(seat)
    passed = sorted(rnd.passed)
    rnd.finalize_declare()
    buried = bots[rnd.banker].decide_bury(rnd, rnd.banker)
    rnd.bury(rnd.banker, buried)
    plays: list[dict] = []
    while rnd.phase == "play":
        seat = rnd.turn
        longest = max(len(h) for h in rnd.hands)
        if longest == threshold and _role(rnd, seat) == role:
            if (len(exhaustive_legal_actions(rnd, seat, max_hand_cards=threshold)) >= 2
                    and _production_search_eligible(rnd, seat)):
                return {"deck": deck, "declarations": declarations,
                        "passed": passed, "buried": sorted(buried),
                        "plays": plays, "hit": True, "seat": seat,
                        "world_sha256": world_sha256(rnd)}
        mv = bots[seat].decide_play(rnd, seat)
        plays.append({"seat": seat, "cards": list(mv)})
        rnd.play(seat, mv)
    return {"deck": deck, "declarations": declarations, "passed": passed,
            "buried": sorted(buried), "plays": plays, "hit": False}


def _worker(job: tuple) -> tuple:
    index, round_seed, rank, banker, role, threshold = job
    return index, replay_capture(round_seed, rank, banker, role, threshold)


def group_files(root: Path = PT1_ROOT) -> list[Path]:
    return sorted((Path(root) / "groups").glob("group-*.json"))


def load_group(path: Path, registry: InputRegistry) -> dict:
    group = registry.read_json(path)
    if group.get("schema") != GROUP_SCHEMA:
        raise PT1FormatError(f"{path}: group schema drift")
    if len(group.get("records") or []) != 4:
        raise PT1FormatError(f"{path}: expected 4 records")
    for record in group["records"]:
        if record.get("schema") != RECORD_SCHEMA:
            raise PT1FormatError(f"{path}: record schema drift")
        body = {k: v for k, v in record.items() if k != "record_sha256"}
        if hashlib.sha256(_canonical_bytes(body)).hexdigest() != record["record_sha256"]:
            raise PT1FormatError(f"{path}: record_sha256 drift")
    return group


def build_records(path: Path, group: dict, replay: dict, *, cap: int | None,
                  root: Path) -> list[tuple[dict, dict | None]]:
    """Public/private record pairs for one group given its replayed state."""
    from ..ai.endgame import exhaustive_legal_actions
    from .pt0_compat import pt0_public_state_sha256
    rank, banker, role, threshold, replicate = group["state_key"]
    if not replay.get("hit"):
        raise RebuildError(f"{path}: natural capture did not hit {role}/{threshold}")
    setup = {
        "trump_rank": rank, "banker": banker,
        "declarations": [dict(d) for d in replay["declarations"]],
        "passed": list(replay["passed"]),
        "declaration": None, "trump_suit": None, "trump_is_nt": False,
        "buried": list(replay["buried"]),
    }
    rnd = round_from_setup(replay["deck"], setup, check_trump=False)
    setup["declaration"] = None if rnd.declaration is None else dict(rnd.declaration)
    setup["trump_suit"] = rnd.trump_suit
    setup["trump_is_nt"] = bool(rnd.trump_is_nt)
    prefix = [dict(p) for p in replay["plays"]]
    replay_prefix(rnd, prefix)
    seat = rnd.turn
    if seat != replay["seat"] or rnd.phase != "play":
        raise RebuildError(f"{path}: replayed prefix does not reach the hit")
    if pt0_public_state_sha256(rnd, perspective_seat=seat) != group["public_state_sha256"]:
        raise RebuildError(f"{path}: public_state_sha256 drift")
    if world_sha256(rnd) != group["true_world_sha256"]:
        raise RebuildError(f"{path}: true_world_sha256 drift")
    exact = [list(a) for a in exhaustive_legal_actions(rnd, seat, max_hand_cards=threshold)]
    legal = enumerate_legal(rnd, seat, cap=cap)
    legal_ballot = [list(a) for a in group["records"][0]["legal_ballot"]]
    if {action_key(a) for a in exact} != {action_key(a) for a in legal_ballot}:
        raise RebuildError(f"{path}: legal_ballot drift vs exhaustive_legal_actions")
    if not legal.complete or legal.keys() != {action_key(a) for a in legal_ballot}:
        raise RebuildError(f"{path}: harvest enumerator disagrees with legal_ballot")
    hidden = hands_snapshot(rnd)
    ref_root = f"{Path(root).name}/groups/{path.name}"
    pairs = []
    for j, rec in enumerate(group["records"]):
        if [list(a) for a in rec["legal_ballot"]] != legal_ballot:
            raise PT1FormatError(f"{path}: legal_ballot differs across records")
        arms = {a["arm"]: a for a in rec["arms"]}
        if set(arms) != {"A", "B", "C"}:
            raise PT1FormatError(f"{path}: arm population drift")
        c_action = list(arms["C"]["selected_action"])
        values = [[list(a), int(v)] for a, v in rec["evaluation_action_utilities"]]
        points = [[list(a), int(p)] for a, p in rec["evaluation_final_points"]]
        seed = arms["C"]["seed"]
        action_values = {
            "unit": "signed_level_utility",
            "perspective": "acting-seat",
            "values": values,
            "final_attacker_points": points,
            "evaluator_identity": rec["evaluator_identity"],
            "c_regret": rec["c_regret"],
            "policy_seed": seed,
            "arms": [{
                "arm": name,
                "policy": arms[name]["policy"],
                "seed": arms[name]["seed"],
                "selected_action": list(arms[name]["selected_action"]),
                "selected_utility": next(v for n, v in rec["selected_utilities"] if n == name),
                "selected_points": next(p for n, p in rec["selected_points"] if n == name),
                "in_production_ballot": action_key(arms[name]["selected_action"]) in {
                    action_key(a) for a in arms["A"]["production_ballot"]},
            } for name in ("A", "B", "C")],
        }
        record = finalize_record({
            "source": "pt1",
            "source_ref": f"{ref_root}#records[{j}] capture={rec['capture_id_sha256'][:16]}",
            "policy": POLICY,
            "round_seed": int(group["round_seed"]),
            "deck": list(replay["deck"]),
            "setup": setup,
            "plays_prefix": prefix,
            "seat": seat,
            "ply": len(prefix),
            "trick": len(prefix) // 4,
            "role": actor_role(rnd, seat),
            "legal_actions": legal.actions,
            "legal_actions_complete": legal.complete,
            "legal_actions_count": legal.count,
            "ballot": legal_ballot,
            "production_ballot": [list(a) for a in arms["A"]["production_ballot"]],
            "allocation": None,
            "action_values": action_values,
            "action": c_action,
            "outcome": None,
            "authority": dict(rec.get("authority") or {}) or None,
            "hidden_hands": hidden,
        })
        if actor_role(rnd, seat) != role:
            raise RebuildError(f"{path}: role drift")
        pairs.append(split_record(record))
    return pairs


def extract_pt1(root: Path = PT1_ROOT, *, cap: int | None = 256,
                registry: InputRegistry | None = None,
                workers: int | None = None, limit: int | None = None,
                progress=None) -> ExtractResult:
    registry = registry or InputRegistry()
    result = ExtractResult("pt1")
    paths = group_files(root)
    if limit is not None:
        paths = paths[:limit]
    groups = [load_group(p, registry) for p in paths]
    for p, g in zip(paths, groups):
        if g["index"] != int(p.stem.split("-")[1]):
            raise PT1FormatError(f"{p}: index drift")
    freeze = Path(root) / "freeze.json"
    if freeze.is_file():
        registry.register(freeze)
    jobs = [(i, int(g["round_seed"]), *g["state_key"][:4]) for i, g in enumerate(groups)]
    replays: dict[int, dict] = {}
    workers = workers or min(8, os.cpu_count() or 1)
    if workers <= 1 or len(jobs) <= 1:
        for job in jobs:
            index, replay = _worker(job)
            replays[index] = replay
            if progress:
                progress(index, len(jobs))
    else:
        with ProcessPoolExecutor(max_workers=workers) as pool:
            for index, replay in pool.map(_worker, jobs, chunksize=1):
                replays[index] = replay
                if progress:
                    progress(index, len(jobs))
    counts = {"groups": len(groups), "rounds": len(groups), "decisions": 0,
              "states_reproduced": 0, "private_records": 0}
    for i, (path, group) in enumerate(zip(paths, groups)):
        pairs = build_records(path, group, replays[i], cap=cap, root=Path(root))
        counts["states_reproduced"] += 1
        for public, private in pairs:
            result.add(public, private)
            counts["decisions"] += 1
    counts["private_records"] = len(result.private)
    result.counts = counts
    result.inputs = registry.rows()
    result.notes.append("state rebuilt by replaying the natural capture "
                        "(privileged_teacher_pt1_natural@76508ec9) from "
                        "round_seed; accepted only on public/true-world hash match")
    return result


def group_summary(root: Path = PT1_ROOT) -> dict[str, int]:
    paths = group_files(root)
    records = 0
    for p in paths:
        records += len(json.loads(p.read_text())["records"])
    return {"groups": len(paths), "records": records}


__all__ = ["extract_pt1", "replay_capture", "build_records", "group_files",
           "load_group", "group_summary"]
