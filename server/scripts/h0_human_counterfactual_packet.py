#!/usr/bin/env python3
"""Freeze a score-free H0 human-action counterfactual design packet.

The reviewed human corpus is a proposal source, not a strength label.  This
tool verifies its exact publication boundary, derives player/deal connected
components, freezes an honest DESIGN/AUDIT/RESERVE assignment, and selects a
bounded decision population without reading returns or evaluating any action.

The resulting packet authorizes review only.  A separate, hash-pinned review
and execution controller is required before sampling worlds or producing a
counterfactual label.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
from collections import Counter, defaultdict
from pathlib import Path


SCHEMA = "human-h0-counterfactual-design-v1"
CORPUS_SCHEMA = "human-decision-corpus-v1"
PACKET_ID = "human-v8-h0-counterfactual-pilot-v1"
SELECTION_DOMAIN = b"shengji-human-h0-selection-v1\0"
PLAY_TARGETS = {"DESIGN": 384, "AUDIT": 128}
MAX_PLAY_DECISIONS_PER_DEAL = 8
LIVE_PARENT = {
    "policy": "mc-s0-report-lcb",
    "authenticator_git": "05ea1d10f8386b4e8826fbf51e2895ff3c9ba554",
    "must_reopen_at_execution": True,
}
V11PAIR_SHA256 = "0260ad67deb7a89577411fafc822bc1ea196884be177fde253705db0d544455e"

# Early/mid cells are intentionally balanced across role and lead/follow.
# Every late and off-ballot row is mandatory.  Late cell targets are therefore
# derived from the reviewed corpus rather than guessed in this table.
CELL_TARGETS = {
    "DESIGN": {
        ("early", "follow", "attacker"): 28,
        ("early", "follow", "defender"): 28,
        ("early", "lead", "attacker"): 27,
        ("early", "lead", "defender"): 28,
        ("mid", "follow", "attacker"): 28,
        ("mid", "follow", "defender"): 28,
        ("mid", "lead", "attacker"): 27,
        ("mid", "lead", "defender"): 28,
    },
    "AUDIT": {
        ("early", "follow", "attacker"): 14,
        ("early", "follow", "defender"): 14,
        ("early", "lead", "attacker"): 13,
        ("early", "lead", "defender"): 14,
        ("mid", "follow", "attacker"): 14,
        ("mid", "follow", "defender"): 14,
        ("mid", "lead", "attacker"): 13,
        ("mid", "lead", "defender"): 13,
    },
}


class H0PacketError(RuntimeError):
    """The corpus or proposed design is not the frozen H0 estimand."""


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"))
            + "\n").encode()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: str | os.PathLike[str]) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_sha256(value: object) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(c in "0123456789abcdef" for c in value))


def _load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise H0PacketError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise H0PacketError(f"JSON root is not an object: {path}")
    return value


def _load_jsonl(path: Path) -> list[dict]:
    try:
        values = [json.loads(line) for line in path.read_text().splitlines()
                  if line.strip()]
    except (OSError, ValueError) as exc:
        raise H0PacketError(f"cannot read JSONL {path}: {exc}") from exc
    if any(not isinstance(value, dict) for value in values):
        raise H0PacketError(f"non-object JSONL row: {path}")
    return values


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def producer_identity(*, smoke: bool) -> dict:
    git = _git("rev-parse", "HEAD")
    dirty = bool(_git("status", "--porcelain"))
    if dirty and not smoke:
        raise H0PacketError("real H0 freeze refuses a dirty tree")
    return {
        "git": git,
        "tree_dirty": dirty,
        "script_sha256": sha256_file(__file__),
        "promotable": not smoke,
    }


def _artifact_map(manifest: dict) -> dict[str, dict]:
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        raise H0PacketError("corpus artifact inventory")
    result: dict[str, dict] = {}
    for item in artifacts:
        if (not isinstance(item, dict) or not isinstance(item.get("name"), str)
                or not _is_sha256(item.get("sha256"))):
            raise H0PacketError("malformed corpus artifact")
        if item["name"] in result:
            raise H0PacketError("duplicate corpus artifact")
        result[item["name"]] = item
    return result


def validate_corpus(corpus_dir: Path, expected_manifest_sha256: str
                    ) -> tuple[dict, list[dict], list[dict]]:
    manifest_path = corpus_dir / "manifest.json"
    if not _is_sha256(expected_manifest_sha256):
        raise H0PacketError("invalid expected corpus manifest SHA-256")
    if sha256_file(manifest_path) != expected_manifest_sha256:
        raise H0PacketError("corpus manifest SHA-256 drift")
    manifest = _load_json(manifest_path)
    if (manifest.get("schema") != CORPUS_SCHEMA
            or manifest.get("producer_tree_dirty") is not False
            or manifest.get("training_authorized") is not False
            or manifest.get("strength_claim") is not False
            or not _is_sha256(manifest.get("source_manifest_sha256"))):
        raise H0PacketError("corpus publication/authority contract")

    artifacts = _artifact_map(manifest)
    required = {"play_decisions.jsonl", "bury_decisions.jsonl",
                "shard_00000.npz"}
    if set(artifacts) != required:
        raise H0PacketError("unexpected corpus artifact population")
    for name, item in artifacts.items():
        path = corpus_dir / name
        if (not path.is_file() or path.stat().st_size != item.get("bytes")
                or sha256_file(path) != item["sha256"]):
            raise H0PacketError(f"corpus artifact drift: {name}")

    plays = _load_jsonl(corpus_dir / "play_decisions.jsonl")
    buries = _load_jsonl(corpus_dir / "bury_decisions.jsonl")
    stats = manifest.get("stats", {})
    if (stats.get("play_decisions_accepted") != len(plays)
            or stats.get("bury_decisions_accepted") != len(buries)):
        raise H0PacketError("sidecar population does not reconcile")

    source_names = {item.get("name") for item in manifest.get("sources", [])}
    play_keys = set()
    for row in plays:
        key = play_key(row)
        if key in play_keys:
            raise H0PacketError("duplicate human play replay key")
        play_keys.add(key)
        if (row.get("source") not in source_names
                or row.get("surface") not in {"lead", "follow"}
                or row.get("role") not in {"attacker", "defender"}
                or not isinstance(row.get("player_id"), str)
                or not isinstance(row.get("trick"), int)):
            raise H0PacketError("malformed human play sidecar row")
    for row in buries:
        if (row.get("source") not in source_names
                or not isinstance(row.get("player_id"), str)
                or not isinstance(row.get("round"), int)):
            raise H0PacketError("malformed human bury sidecar row")
    return manifest, plays, buries


def deal_key(row: dict) -> str:
    return f"{row['source']}:round-{int(row['round'])}"


def play_key(row: dict) -> str:
    return (f"{deal_key(row)}:event-{int(row['event_index'])}:"
            f"seat-{int(row['seat'])}")


class _UnionFind:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def find(self, item: str) -> str:
        self.parent.setdefault(item, item)
        if self.parent[item] != item:
            self.parent[item] = self.find(self.parent[item])
        return self.parent[item]

    def union(self, left: str, right: str) -> None:
        left_root, right_root = self.find(left), self.find(right)
        if left_root != right_root:
            self.parent[max(left_root, right_root)] = min(left_root, right_root)


def derive_components(plays: list[dict], buries: list[dict]) -> list[dict]:
    union = _UnionFind()
    for row in [*plays, *buries]:
        union.union(f"player:{row['player_id']}", f"deal:{deal_key(row)}")

    groups: dict[str, dict[str, set[str]]] = defaultdict(
        lambda: {"players": set(), "deals": set()})
    for node in union.parent:
        group = groups[union.find(node)]
        kind, value = node.split(":", 1)
        group[f"{kind}s"].add(value)

    play_counts = Counter(union.find(f"player:{row['player_id']}")
                          for row in plays)
    bury_counts = Counter(union.find(f"player:{row['player_id']}")
                          for row in buries)
    result = []
    for root, group in groups.items():
        result.append({
            "players": sorted(group["players"]),
            "deals": sorted(group["deals"]),
            "play_rows": play_counts[root],
            "bury_rows": bury_counts[root],
        })
    return sorted(
        result,
        key=lambda item: (-(item["play_rows"] + item["bury_rows"]),
                          item["players"], item["deals"]),
    )


def phase(row: dict) -> str:
    trick = int(row["trick"])
    if trick <= 8:
        return "early"
    if trick <= 17:
        return "mid"
    return "late"


def cell(row: dict) -> tuple[str, str, str]:
    return phase(row), str(row["surface"]), str(row["role"])


def _rank(row: dict) -> str:
    return sha256_bytes(SELECTION_DOMAIN + play_key(row).encode())


def select_rows(rows: list[dict], *, target: int,
                cell_targets: dict[tuple[str, str, str], int],
                max_per_deal: int = MAX_PLAY_DECISIONS_PER_DEAL) -> list[dict]:
    if target <= 0 or max_per_deal <= 0:
        raise H0PacketError("invalid H0 selection geometry")
    if len({play_key(row) for row in rows}) != len(rows):
        raise H0PacketError("selection population has duplicate keys")

    targets = dict(cell_targets)
    for row in rows:
        if phase(row) == "late":
            targets[cell(row)] = targets.get(cell(row), 0) + 1
    if sum(targets.values()) != target:
        raise H0PacketError(
            f"cell targets sum to {sum(targets.values())}, expected {target}")

    selected: dict[str, dict] = {}
    by_deal: Counter[str] = Counter()
    by_cell: Counter[tuple[str, str, str]] = Counter()

    mandatory = sorted(
        (row for row in rows
         if phase(row) == "late" or row.get("human_action_appended") is True),
        key=_rank,
    )
    for row in mandatory:
        key, deal, row_cell = play_key(row), deal_key(row), cell(row)
        if by_deal[deal] >= max_per_deal:
            raise H0PacketError("mandatory rows exceed per-deal cap")
        if by_cell[row_cell] >= targets.get(row_cell, 0):
            raise H0PacketError("mandatory rows exceed frozen cell target")
        selected[key] = row
        by_deal[deal] += 1
        by_cell[row_cell] += 1

    pools: dict[tuple[tuple[str, str, str], str], list[dict]] = defaultdict(list)
    for row in rows:
        if play_key(row) not in selected:
            pools[(cell(row), deal_key(row))].append(row)
    for pool in pools.values():
        pool.sort(key=_rank)

    # Solve the remaining cell/deal allocation as an integral max-flow.  A
    # greedy cell order can falsely claim infeasibility by consuming a deal's
    # cap before a scarce lead/role cell reaches it.
    source, sink = "SOURCE", "SINK"
    capacity: dict[tuple[object, object], int] = {}
    adjacency: dict[object, list[object]] = defaultdict(list)

    def add_edge(left: object, right: object, amount: int) -> None:
        if amount <= 0:
            return
        if (left, right) not in capacity:
            adjacency[left].append(right)
            adjacency[right].append(left)
            capacity[(left, right)] = 0
            capacity[(right, left)] = 0
        capacity[(left, right)] += amount

    deficits = {row_cell: targets[row_cell] - by_cell[row_cell]
                for row_cell in targets}
    for row_cell in sorted(deficits):
        add_edge(source, ("cell", row_cell), deficits[row_cell])
    deals = sorted({deal for _, deal in pools})
    for deal in deals:
        add_edge(("deal", deal), sink, max_per_deal - by_deal[deal])
    original_cell_deal: dict[tuple[tuple[str, str, str], str], int] = {}
    for (row_cell, deal), pool in sorted(pools.items()):
        amount = len(pool)
        add_edge(("cell", row_cell), ("deal", deal), amount)
        original_cell_deal[(row_cell, deal)] = amount

    total_flow = 0
    while True:
        parent: dict[object, object | None] = {source: None}
        queue = [source]
        for node in queue:
            for nxt in adjacency[node]:
                if nxt not in parent and capacity.get((node, nxt), 0) > 0:
                    parent[nxt] = node
                    queue.append(nxt)
                    if nxt == sink:
                        break
            if sink in parent:
                break
        if sink not in parent:
            break
        amount = target
        node: object = sink
        while parent[node] is not None:
            previous = parent[node]
            amount = min(amount, capacity[(previous, node)])
            node = previous
        node = sink
        while parent[node] is not None:
            previous = parent[node]
            capacity[(previous, node)] -= amount
            capacity[(node, previous)] += amount
            node = previous
        total_flow += amount

    if total_flow != sum(deficits.values()):
        raise H0PacketError("frozen H0 quotas infeasible under deal cap")
    for (row_cell, deal), original in sorted(original_cell_deal.items()):
        used = original - capacity[(("cell", row_cell), ("deal", deal))]
        for row in pools[(row_cell, deal)][:used]:
            selected[play_key(row)] = row
            by_deal[deal] += 1
            by_cell[row_cell] += 1

    if by_cell != Counter(targets):
        raise H0PacketError("selected cell population drift")
    selected_rows = sorted(selected.values(), key=play_key)
    if len(selected_rows) != target:
        raise H0PacketError("selected row population drift")
    return selected_rows


def _row_record(row: dict) -> dict:
    return {
        "replay_key": play_key(row),
        "deal_key": deal_key(row),
        "player_id": row["player_id"],
        "source": row["source"],
        "round": row["round"],
        "event_index": row["event_index"],
        "seat": row["seat"],
        "role": row["role"],
        "surface": row["surface"],
        "phase": phase(row),
        "trick": row["trick"],
        "cards_remaining": row["cards_remaining"],
        "candidate_count": row["candidate_count"],
        "human_action": row["chosen"],
        "human_action_off_analysis_ballot": bool(row["human_action_appended"]),
    }


def _component_record(component: dict, assignment: str) -> dict:
    return {
        "assignment": assignment,
        "players": component["players"],
        "deals": component["deals"],
        "play_rows": component["play_rows"],
        "bury_rows": component["bury_rows"],
    }


def build_packet(corpus_dir: Path, expected_manifest_sha256: str,
                 *, smoke: bool) -> dict:
    manifest, plays, buries = validate_corpus(
        corpus_dir, expected_manifest_sha256)
    components = derive_components(plays, buries)
    if len(components) < 3:
        raise H0PacketError("too few independent player/deal components")

    assignments = [
        _component_record(components[0], "DESIGN"),
        _component_record(components[1], "AUDIT"),
        *(_component_record(component, "RESERVE")
          for component in components[2:]),
    ]
    player_assignment = {
        player: component["assignment"]
        for component in assignments for player in component["players"]
    }
    split_rows = {
        split: [row for row in plays
                if player_assignment[row["player_id"]] == split]
        for split in ("DESIGN", "AUDIT")
    }
    selected = {
        split: select_rows(
            split_rows[split], target=PLAY_TARGETS[split],
            cell_targets=CELL_TARGETS[split])
        for split in ("DESIGN", "AUDIT")
    }

    for split in ("DESIGN", "AUDIT"):
        selected_keys = {play_key(row) for row in selected[split]}
        off_ballot_keys = {play_key(row) for row in split_rows[split]
                           if row["human_action_appended"] is True}
        late_keys = {play_key(row) for row in split_rows[split]
                     if phase(row) == "late"}
        if not off_ballot_keys <= selected_keys or not late_keys <= selected_keys:
            raise H0PacketError("mandatory H0 coverage drift")

    artifacts = _artifact_map(manifest)
    packet = {
        "schema": SCHEMA,
        "packet_id": PACKET_ID,
        "producer": producer_identity(smoke=smoke),
        "human_corpus": {
            "manifest_sha256": expected_manifest_sha256,
            "source_manifest_sha256": manifest["source_manifest_sha256"],
            "producer_git": manifest["producer_git"],
            "producer_sha256": manifest["producer_sha256"],
            "encoder": manifest["encoder"],
            "play_ballot": manifest["play_ballot"],
            "artifacts": {name: item["sha256"]
                          for name, item in sorted(artifacts.items())},
        },
        "population": {
            "play_rows": len(plays),
            "bury_rows": len(buries),
            "components": assignments,
            "strict_three_way_report_feasible": False,
            "formal_report_source": "fresh-bot-paired-and-human-c1-only",
        },
        "split_contract": {
            "component_assignment_rule": (
                "largest=DESIGN, second-largest=AUDIT, remainder=RESERVE; "
                "components link pseudonymous players and source/round deals"
            ),
            "phase_bands": {"early": "tricks 1-8", "mid": "tricks 9-17",
                            "late": "tricks 18+"},
            "selection_domain_sha256": sha256_bytes(SELECTION_DOMAIN),
            "max_play_decisions_per_deal": MAX_PLAY_DECISIONS_PER_DEAL,
            "all_late_selected": True,
            "all_off_analysis_ballot_selected": True,
            "selected": {
                split: [_row_record(row) for row in selected[split]]
                for split in ("DESIGN", "AUDIT")
            },
            "bury_surface": {
                "DESIGN": components[0]["bury_rows"],
                "AUDIT": components[1]["bury_rows"],
                "selection": "all reviewed buries in each split",
                "estimand_separate_from_play": True,
            },
        },
        "proposal_contract": {
            "play_union": [
                "human_action",
                "live_champion_action",
                "live_champion_analysis_ballot",
                "v11pair_top_proposal",
                "same_budget_random_diversifier",
            ],
            "bury_union": [
                "human_bury",
                "live_smart_bury",
                "s3a_structured_bury",
                "same_budget_random_structured_bury",
            ],
            "live_parent": LIVE_PARENT,
            "v11pair_checkpoint_sha256": V11PAIR_SHA256,
            "human_action_is_truth": False,
            "off_ballot_actions_must_be_replayed_legal": True,
        },
        "counterfactual_execution_required": {
            "belief_sampler": "strict-public-history-v1",
            "proposal_worlds": 30,
            "report_worlds_per_fixed_pair": 300,
            "proposal_and_report_worlds_disjoint": True,
            "common_random_worlds_within_pair": True,
            "primary_metric": "acting-team-signed-level-utility",
            "cluster": "deal",
            "production_continuation": "mc-s0-report-lcb",
            "alternate_s4_continuation": (
                "allowed only after a separate terminal S4 PASS"
            ),
            "required_outputs": [
                "candidate_recall",
                "human_minus_champion_paired_utility",
                "off_ballot_support",
                "continuation_ranking_flips",
                "per-player-and-surface-heterogeneity",
                "exact-work-and-replay-refusal-counters",
            ],
        },
        "authority": {
            "score_free": True,
            "outcomes_computed": False,
            "design_review_authorized": True,
            "counterfactual_execution_authorized": False,
            "labels_authorized": False,
            "training_authorized": False,
            "strength_claim": False,
            "production_promotion": False,
            "human_evaluation_data_may_train_or_select": False,
        },
    }
    packet["packet_sha256"] = sha256_bytes(canonical_json(packet))
    return packet


def packet_problems(packet: dict, expected: dict) -> list[str]:
    problems = []
    if packet != expected:
        problems.append("packet full recomputation drift")
    authority = packet.get("authority", {})
    if (authority.get("score_free") is not True
            or authority.get("outcomes_computed") is not False
            or authority.get("counterfactual_execution_authorized") is not False
            or authority.get("labels_authorized") is not False
            or authority.get("training_authorized") is not False
            or authority.get("strength_claim") is not False
            or authority.get("production_promotion") is not False):
        problems.append("packet authority widened")
    return sorted(set(problems))


def publish_exclusive(path: Path, payload: dict) -> None:
    partial = Path(str(path) + ".partial")
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.path.lexists(path) or os.path.lexists(partial):
        raise H0PacketError("refusing existing packet or partial")
    try:
        with partial.open("xb") as handle:
            handle.write(canonical_json(payload))
            handle.flush()
            os.fsync(handle.fileno())
        os.link(partial, path)
        partial.unlink()
    except Exception:
        if partial.exists() and not path.exists():
            partial.unlink()
        raise
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise H0PacketError("published packet is not regular/unlinked")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("freeze", "verify"):
        child = sub.add_parser(command)
        child.add_argument("--corpus", required=True)
        child.add_argument("--expected-corpus-sha256", required=True)
        child.add_argument("--packet", required=True)
        child.add_argument("--expected-git")
        child.add_argument("--smoke", action="store_true")
    return parser


def main() -> None:
    args = _parser().parse_args()
    if args.expected_git and _git("rev-parse", "HEAD") != args.expected_git:
        raise H0PacketError("producer Git differs from expected Git")
    expected = build_packet(
        Path(args.corpus), args.expected_corpus_sha256, smoke=args.smoke)
    packet_path = Path(args.packet)
    if args.command == "freeze":
        publish_exclusive(packet_path, expected)
        print(json.dumps({
            "status": "FROZEN_FOR_REVIEW",
            "packet": str(packet_path),
            "sha256": sha256_file(packet_path),
            "rows": {split: len(rows) for split, rows in
                     expected["split_contract"]["selected"].items()},
            "execution_authorized": False,
        }, sort_keys=True))
        return
    actual = _load_json(packet_path)
    problems = packet_problems(actual, expected)
    if problems:
        raise H0PacketError("; ".join(problems))
    print(json.dumps({
        "status": "VERIFIED_FOR_DESIGN_REVIEW",
        "packet": str(packet_path),
        "sha256": sha256_file(packet_path),
        "execution_authorized": False,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
