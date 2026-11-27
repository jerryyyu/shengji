"""Rebuild selected offline reply roots from a pinned trajectory test shard."""
from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from ..ai.refusal import Refusal
from ..engine.round import Round
from .belief_labels import BeliefLabelError, deal_key, iter_decisions, split_of
from .belief_tree_backup import root_reply_backup


@dataclass(frozen=True)
class RootTarget:
    """The cluster-wide extract row identity and the corresponding table turn."""

    decision_index: int
    mirror: int
    ply: int
    seat: int


@dataclass(frozen=True)
class TrancheRoot:
    """Detached state for a paired comparison on one recorded decision."""

    target: RootTarget
    deal_key: str
    round: Round
    refusals: tuple[Refusal, ...]

    def backup(self, actions, root_worlds, **options):
        return root_reply_backup(
            self.round, actions, root_worlds, refusals=self.refusals, **options,
        )


def replay_tranche_roots(
    shard: str | Path,
    *,
    shard_sha256: str,
    run_id: str,
    cluster: int,
    round_seed: int,
    policy: str,
    expected_deal_key: str,
    calib: float,
    test: float,
    min_tricks: int,
    targets: Sequence[RootTarget],
) -> tuple[TrancheRoot, ...]:
    """Load a selected test cluster and return roots in the requested order.

    The split and exact shard pin come from the caller's approved bank. The
    two mirrors use the same deck identity and accumulate separate ledgers.
    Lead eligibility uses the caller's minimum number of completed tricks.
    """
    if (not re.fullmatch(r"deck:[0-9a-f]{64}", expected_deal_key)
            or not (0 <= calib < 1 and 0 < test < 1 and calib + test < 1)
            or split_of(expected_deal_key, calib, test) != "test"):
        raise BeliefLabelError("expected a deal in the bound test split")
    if (not re.fullmatch(r"[0-9a-f]{64}", shard_sha256) or not run_id or not policy
            or any(type(value) is not int or value < 0 for value in (cluster, round_seed, min_tricks))):
        raise BeliefLabelError("invalid trajectory shard or eligibility pin")
    selected = {target.decision_index: target for target in targets}
    if (not selected or len(selected) != len(targets)
            or len({(t.mirror, t.ply) for t in targets}) != len(targets)
            or any(any(type(v) is not int for v in (t.decision_index, t.mirror, t.ply, t.seat))
                   or t.decision_index < 0 or t.mirror not in (0, 1) or t.ply < 4 * min_tricks
                   or t.ply % 4 or t.seat not in range(4) for t in targets)):
        raise BeliefLabelError("invalid or duplicate trajectory lead targets")

    path = Path(shard)
    if path.name != f"cluster-{cluster:06d}.jsonl":
        raise BeliefLabelError("shard path disagrees with cluster")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != shard_sha256:
        raise BeliefLabelError("trajectory shard digest mismatch")
    rows = [json.loads(line) for line in raw.splitlines() if line.strip()]
    mirrors = _ordered_plays(rows, run_id, cluster, round_seed, policy, expected_deal_key)

    found = {}
    previous = None
    for decision in iter_decisions(mirrors[0] + mirrors[1], ordered=True):
        if (previous is not None and decision.round_index != previous.round_index
                and previous.rnd.phase != "round_end"):
            raise BeliefLabelError("trajectory mirror ends before round completion")
        previous = decision
        index = decision.decision_index
        if index not in selected:
            continue
        target = selected[index]
        actual = RootTarget(index, decision.round_index, decision.record["ply"], decision.seat)
        if target != actual:
            raise BeliefLabelError("selected decision disagrees with mirror, ply or actor")
        rnd = decision.rnd
        if rnd.trick is None or rnd.trick.plays or len(rnd.history) < min_tricks:
            raise BeliefLabelError("selected decision is outside the required lead depth")
        found[index] = TrancheRoot(target, expected_deal_key, copy.deepcopy(rnd), decision.refusals)
    if previous is None or previous.rnd.phase != "round_end":
        raise BeliefLabelError("trajectory mirror ends before round completion")
    if found.keys() != selected.keys():
        raise BeliefLabelError("selected decision is absent from the trajectory")
    return tuple(found[target.decision_index] for target in targets)


def _ordered_plays(rows, run_id, cluster, seed, policy, expected_deal_key):
    mirrors = [{}, {}]
    if not rows or deal_key(rows[0]["deck"]) != expected_deal_key:
        raise BeliefLabelError("trajectory shard disagrees with the full deal key")
    deck = rows[0]["deck"]
    for row in rows:
        ref = row["source_ref"].rsplit(":", 4)
        if (len(ref) != 5 or ref[:2] != [run_id, str(cluster)] or ref[2] not in ("0", "1")
                or type(row["seat"]) is not int or row["seat"] not in range(4)
                or ref[3] != str(row["seat"]) or row["deck"] != deck
                or type(row["round_seed"]) is not int or row["round_seed"] != seed
                or row["source"] != "trajectory" or row["policy"] != policy):
            raise BeliefLabelError("mixed trajectory run, cluster, mirror, actor, deal or policy")
        if row["decision_kind"] == "bury" and ref[4] == "bury":
            continue
        ply = row["ply"]
        if (row["decision_kind"] != "play" or type(ply) is not int or ply < 0 or ref[4] != str(ply)
                or row["trick"] != ply // 4 or len(row["plays_prefix"]) != ply):
            raise BeliefLabelError("invalid trajectory play identity")
        plays = mirrors[int(ref[2])]
        if ply in plays:
            raise BeliefLabelError("duplicate trajectory mirror and ply")
        plays[ply] = row
    ordered = []
    for plays in mirrors:
        if not plays or set(plays) != set(range(len(plays))):
            raise BeliefLabelError("missing trajectory mirror or ply")
        mirror = [plays[ply] for ply in range(len(plays))]
        setup = mirror[0]["setup"]
        prefix = []
        for row in mirror:
            if row["setup"] != setup or row["plays_prefix"] != prefix:
                raise BeliefLabelError("trajectory setup or public prefix drift")
            prefix.append({"seat": row["seat"], "cards": row.get("engine_play") or row["action"]})
        ordered.append(mirror)
    return ordered
