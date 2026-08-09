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
import sys
from collections import Counter, defaultdict
from pathlib import Path


SCRIPT = Path(__file__).resolve()
SERVER = SCRIPT.parents[1]
REPO = SCRIPT.parents[2]
sys.path.insert(0, str(SCRIPT.parent))

import live_champion_parent as LIVE_PARENT_AUTH  # noqa: E402

SCHEMA = "human-h0-counterfactual-design-v3"
CORPUS_SCHEMA = "human-decision-corpus-v1"
PACKET_ID = "human-v8-h0-counterfactual-pilot-v3"
SELECTION_DOMAIN = b"shengji-human-h0-selection-v1\0"
PLAY_TARGETS = {"DESIGN": 384, "AUDIT": 128}
BURY_TARGETS = {"DESIGN": 36, "AUDIT": 9}
MAX_PLAY_DECISIONS_PER_DEAL = 8
V2_PACKET_SHA256 = (
    "2cccf5803ca60cf41690f18dc0e85febaf36a88ce702587e8c86a67e2a358f2b"
)
V2_SELECTED_PLAY_ROWS_SHA256 = (
    "18673b20ca0a5b1a8e476f3bcf45cf9d08f90f4244f9c5ee07cb8bd8cd47711d"
)
LIVE_PARENT_AUTH_GIT = "5390019aef36f63150d7613b38bf56cf9cfebf8b"
LIVE_PARENT_AUTH_SHA256 = (
    "d6515d6db76290c3ad145f9194a7985d7d78223f688a30c78cdb520de41c521b"
)
V11PAIR_LOGICAL_PATH = "server/snapshots_v11pair/ep07.npz"
V11PAIR_SHA256 = (
    "cd89d6ed7e9d5f798d69ce546107c4dfbef682c5385de39af527026e39e1c003"
)
PROPOSAL_SEED_DOMAIN = b"shengji-human-h0-proposal-v3\0"
REFERENCE_WORLD_DOMAIN = b"shengji-human-h0-reference-world-v3\0"
SELECTION_WORLD_DOMAIN = b"shengji-human-h0-selection-world-v3\0"
REPORT_WORLD_DOMAIN = b"shengji-human-h0-report-world-v3\0"

LIVE_LEAD_MAX_CANDIDATES = 14
LIVE_FOLLOW_MAX_CANDIDATES = 12
PLAY_EXTRA_PROPOSALS = 3  # human, V11, and matched random.
PLAY_MAX_UNIQUE_CANDIDATES = LIVE_LEAD_MAX_CANDIDATES + PLAY_EXTRA_PROPOSALS
BURY_STRUCTURED_MAX_CANDIDATES = 32
BURY_MAX_UNIQUE_CANDIDATES = BURY_STRUCTURED_MAX_CANDIDATES + 1  # human.
PROPOSAL_WORLDS = 30
REPORT_WORLDS = 300
REPORT_MAX_ACTIONS = 3
REFERENCE_REPORT_MAX_ACTIONS = 2
PLAY_REFERENCE_MAX_CANDIDATE_WORLDS = (
    LIVE_LEAD_MAX_CANDIDATES * PROPOSAL_WORLDS
    + REFERENCE_REPORT_MAX_ACTIONS * REPORT_WORLDS
)
PLAY_PILOT_MAX_CANDIDATE_WORLDS = (
    PLAY_MAX_UNIQUE_CANDIDATES * PROPOSAL_WORLDS
    + REPORT_MAX_ACTIONS * REPORT_WORLDS
)
PLAY_MAX_CANDIDATE_WORLDS = (
    PLAY_REFERENCE_MAX_CANDIDATE_WORLDS
    + PLAY_PILOT_MAX_CANDIDATE_WORLDS
)
BURY_MAX_CANDIDATE_WORLDS = (
    BURY_MAX_UNIQUE_CANDIDATES * PROPOSAL_WORLDS
    + REPORT_MAX_ACTIONS * REPORT_WORLDS
)
TOTAL_MAX_CANDIDATE_WORLDS = (
    PLAY_TARGETS["DESIGN"] + PLAY_TARGETS["AUDIT"]
) * PLAY_MAX_CANDIDATE_WORLDS + sum(BURY_TARGETS.values()) * (
    BURY_MAX_CANDIDATE_WORLDS
)

ROLLOUT_POLICY_LOGICAL_PATH = "server/shengji/ai/heuristic.py"
ROLLOUT_POLICY_SHA256 = (
    "a99dfb089fd17e7c17ddcc4d76542552d317598fbe233269c3e7c0501b9b15ef"
)
ANALYSIS_ACTIONS_LOGICAL_PATH = "server/shengji/rl/actions.py"
ANALYSIS_ACTIONS_SHA256 = (
    "a109031cac72c683716f46133769a0cba2762857b60779ff0e5be0af5fd28edc"
)
STRUCTURED_BURY_LOGICAL_PATH = "server/shengji/ai/bury.py"
STRUCTURED_BURY_SHA256 = (
    "2fd2ca71ed7594b99e907d5dbcb65bb95302a7b8c16660769115ed4ddfafe610"
)

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


def live_parent_contract() -> dict:
    """Bind the portable live-champion reopener, not its obsolete v1 bytes."""
    if sha256_file(LIVE_PARENT_AUTH.__file__) != LIVE_PARENT_AUTH_SHA256:
        raise H0PacketError("live-parent authenticator source drift")
    try:
        parent = LIVE_PARENT_AUTH.require_parent_payload(
            LIVE_PARENT_AUTH.expected_parent())
    except LIVE_PARENT_AUTH.ProtocolRefused as exc:
        raise H0PacketError(f"live-parent contract refused: {exc}") from exc
    if parent.get("champion_policy") != "mc-s0-report-lcb":
        raise H0PacketError("live-parent policy drift")
    return {
        "policy": parent["champion_policy"],
        "authenticator_schema": LIVE_PARENT_AUTH.SCHEMA,
        "authenticator_git": LIVE_PARENT_AUTH_GIT,
        "authenticator_script_sha256": LIVE_PARENT_AUTH_SHA256,
        "expected_parent": parent,
        "must_reopen_portably_at_controller_freeze": True,
        "must_reopen_portably_before_each_execution": True,
    }


def validate_v11_checkpoint(path: Path) -> dict:
    """Require the executable, corrected-encoder V11 artifact by bytes."""
    try:
        info = path.lstat()
    except OSError as exc:
        raise H0PacketError(f"cannot stat V11 checkpoint: {exc}") from exc
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink < 1
            or path.is_symlink()):
        raise H0PacketError("V11 checkpoint is not a regular file")
    actual = sha256_file(path)
    if actual != V11PAIR_SHA256:
        raise H0PacketError(
            f"V11 checkpoint SHA-256 drift: {actual}")
    return {
        "logical_path": V11PAIR_LOGICAL_PATH,
        "sha256": actual,
        "bytes": info.st_size,
        "format": "numpy-npz",
        "encoder_contract": "reviewed-public-no-private-kitty-v1",
    }


def validate_source(logical_path: str, expected_sha256: str) -> dict:
    """Bind an executable source file that the portable parent omitted."""
    if not _is_sha256(expected_sha256):
        raise H0PacketError("invalid expected source SHA-256")
    path = REPO / logical_path
    try:
        info = path.lstat()
    except OSError as exc:
        raise H0PacketError(f"cannot stat source {logical_path}: {exc}") from exc
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink < 1
            or path.is_symlink()):
        raise H0PacketError(f"source is not a regular file: {logical_path}")
    actual = sha256_file(path)
    if actual != expected_sha256:
        raise H0PacketError(f"source SHA-256 drift: {logical_path}: {actual}")
    return {"logical_path": logical_path, "sha256": actual,
            "bytes": info.st_size}


def proposal_contract(live_parent: dict, v11: dict) -> dict:
    """Return the bounded candidate-source contract for both surfaces."""
    return {
        "play_union": [
            "live_production_ballot",
            "human_action_if_novel",
            "v11pair_top_exhaustive_proposal_if_novel",
            "same_budget_random_exhaustive_proposal_if_novel",
        ],
        "production_ballot": {
            "source": "MCBot._candidates from exact live parent",
            "lead_max_candidates": LIVE_LEAD_MAX_CANDIDATES,
            "follow_max_candidates": LIVE_FOLLOW_MAX_CANDIDATES,
            "must_preserve_order_and_candidate_zero": True,
            "full_exhaustive_universe_is_not_added_to_union": True,
        },
        "analysis_action_universe": {
            **validate_source(
                ANALYSIS_ACTIONS_LOGICAL_PATH, ANALYSIS_ACTIONS_SHA256),
            "function": "enumerate_actions",
            "config": {"exhaustive_follows": True,
                       "include_throws": True},
            "uses": ["v11pair_top_one", "matched_random_one"],
            "all_actions_evaluated_by_pilot": False,
        },
        "novel_proposal_pool": {
            "definition": (
                "replay-legal exhaustive actions outside the deduplicated "
                "live production ballot and human action"
            ),
            "shared_by_v11_and_random": True,
            "v11_and_random_may_name_same_action_then_deduplicate": True,
            "on_empty": "record-no-novel-proposal-for-both-sources",
        },
        "play_source_maxima": {
            "live_production_ballot": LIVE_LEAD_MAX_CANDIDATES,
            "human_action": 1,
            "v11pair_top_proposal": 1,
            "matched_random_proposal": 1,
            "max_unique_after_deduplication": PLAY_MAX_UNIQUE_CANDIDATES,
        },
        "bury_union": [
            "s3a_structured_ballot_including_live_smart_candidate_zero",
            "human_bury_if_novel",
        ],
        "structured_bury_ballot": {
            **validate_source(
                STRUCTURED_BURY_LOGICAL_PATH, STRUCTURED_BURY_SHA256),
            "function": "build_bury_ballot",
            "max_candidates": BURY_STRUCTURED_MAX_CANDIDATES,
            "candidate_zero": "live_smart_bury",
            "max_unique_after_human_deduplication":
                BURY_MAX_UNIQUE_CANDIDATES,
            "matched_random_arm": (
                "not part of H0; S3a owns the separately controlled "
                "structured-bury mechanism claim"
            ),
        },
        "live_parent": live_parent,
        "v11pair_checkpoint": v11,
        "v11pair_top_proposal": {
            "action_universe": "shared-novel-proposal-pool",
            "proposals_per_decision": 1,
            "choice": "finite raw argmax with canonical-index tie break",
            "outside_training_ballot_is_diagnostic": True,
            "must_compare_novelty_and_report_value_with_matched_random": True,
            "threshold_applied": False,
            "scalar_leaf_use": False,
            "checkpoint_must_reopen_before_each_execution": True,
        },
        "random_diversifier": {
            "proposals_per_decision": 1,
            "action_universe": "shared-novel-proposal-pool",
            "choice": "uniform by canonical index from an independent stream",
            "stream_domain_sha256": sha256_bytes(PROPOSAL_SEED_DOMAIN),
            "stream_key": "split,replay_key,surface,source",
            "on_empty_novel_pool": "record-no-novel-proposal-for-both-sources",
            "cannot_advance_reference_selection_or_report_rng": True,
        },
        "candidate_identity": "sorted-card-multiset",
        "duplicate_source_attribution": "retain-all-sources-on-one-action",
        "human_action_is_truth": False,
        "off_ballot_actions_must_be_replayed_legal": True,
    }


def execution_contract() -> dict:
    """Name folds, continuation semantics, estimands, and hard work ceilings."""
    return {
        "belief_sampler": "strict-public-history-v1",
        "play_root_reference": {
            "policy": "mc-s0-report-lcb",
            "purpose": "generate the fixed counterfactual champion action",
            "selection_worlds": PROPOSAL_WORLDS,
            "report_worlds": REPORT_WORLDS,
            "selection_candidate_cap": LIVE_LEAD_MAX_CANDIDATES,
            "report_action_cap": REFERENCE_REPORT_MAX_ACTIONS,
            "max_candidate_world_rollouts_per_play":
                PLAY_REFERENCE_MAX_CANDIDATE_WORLDS,
            "separate_from_pilot_selection_and_report_folds": True,
        },
        "bury_root_reference": {
            "policy": "live_smart_bury",
            "candidate_world_rollouts": 0,
            "must_equal_structured_ballot_candidate_zero": True,
        },
        "rollout_continuation": {
            **validate_source(
                ROLLOUT_POLICY_LOGICAL_PATH, ROLLOUT_POLICY_SHA256),
            "policy": "HeuristicBot",
            "use": "continuation after each fixed root action",
            "report_lcb_is_not_recursive_continuation": True,
        },
        "rng_folds": {
            "master_key": "split,replay_key,surface",
            "reference_world_domain_sha256":
                sha256_bytes(REFERENCE_WORLD_DOMAIN),
            "pilot_selection_world_domain_sha256":
                sha256_bytes(SELECTION_WORLD_DOMAIN),
            "pilot_report_world_domain_sha256":
                sha256_bytes(REPORT_WORLD_DOMAIN),
            "all_three_world_folds_pairwise_disjoint": True,
            "common_random_worlds_across_actions_within_each_fold": True,
        },
        "pilot_selection": {
            "worlds": PROPOSAL_WORLDS,
            "evaluate": "bounded-unique-union-candidates",
            "play_candidate_cap": PLAY_MAX_UNIQUE_CANDIDATES,
            "bury_candidate_cap": BURY_MAX_UNIQUE_CANDIDATES,
            "objective": "acting-team-signed-level-utility",
            "rule": "largest finite mean",
            "tie_break": "canonical candidate index",
            "candidate_sources_cannot_read_pilot_world_outcomes": True,
        },
        "pilot_report": {
            "worlds": REPORT_WORLDS,
            "fixed_actions": [
                "root_reference_action",
                "human_action",
                "pilot_selection_winner",
            ],
            "max_actions_after_deduplication": REPORT_MAX_ACTIONS,
            "action_deduplication": "sorted-card-multiset",
            "cannot_select_or_change_candidate_union": True,
        },
        "work_ceiling": {
            "play_reference_candidate_worlds":
                PLAY_REFERENCE_MAX_CANDIDATE_WORLDS,
            "play_pilot_candidate_worlds":
                PLAY_PILOT_MAX_CANDIDATE_WORLDS,
            "play_total_candidate_worlds_per_row":
                PLAY_MAX_CANDIDATE_WORLDS,
            "bury_total_candidate_worlds_per_row":
                BURY_MAX_CANDIDATE_WORLDS,
            "selected_play_rows": sum(PLAY_TARGETS.values()),
            "selected_bury_rows": sum(BURY_TARGETS.values()),
            "all_rows_max_candidate_worlds": TOTAL_MAX_CANDIDATE_WORLDS,
            "actual_exact_work_must_be_recomputed_from_deduplicated_actions":
                True,
        },
        "row_completion": {
            "no_replacement_or_resampling_of_selected_rows": True,
            "every_row_terminal_state": "COMPLETE or named score-free refusal",
            "partial_action_or_world_dose_cannot_publish_a_utility_row": True,
            "controller_review_must_predeclare_completion_gate": True,
            "refusal_counts_reported_by_split_surface_phase_role_and_reason":
                True,
        },
        "outputs": {
            "source_membership": [
                "human-in-production-ballot",
                "v11-proposal-novel",
                "random-proposal-novel",
                "selected-winner-source-attribution",
            ],
            "report_estimands": [
                "human-minus-reference-paired-utility",
                "selected-minus-reference-paired-utility",
                "selected-minus-human-paired-utility",
            ],
            "diagnostics": [
                "off-production-ballot-support",
                "per-player-surface-phase-role-heterogeneity",
                "exact-work-and-replay-refusal-counters",
            ],
            "candidate_recall_claimed": False,
        },
        "design_and_audit_launch_together_under_one_frozen_packet": True,
        "audit_outcomes_cannot_tune_design_recipe": True,
        "cluster": "deal",
        "primary_metric": "acting-team-signed-level-utility",
        "alternate_s4_continuation": (
            "separate future diagnostic only after a terminal full-game S4 "
            "PASS and a new reviewed execution packet"
        ),
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
    bury_keys = set()
    for row in buries:
        key = bury_key(row)
        if key in bury_keys:
            raise H0PacketError("duplicate human bury replay key")
        bury_keys.add(key)
        if (row.get("source") not in source_names
                or not isinstance(row.get("player_id"), str)
                or not isinstance(row.get("round"), int)
                or not isinstance(row.get("seat"), int)
                or not isinstance(row.get("chosen"), list)):
            raise H0PacketError("malformed human bury sidecar row")
    return manifest, plays, buries


def deal_key(row: dict) -> str:
    return f"{row['source']}:round-{int(row['round'])}"


def play_key(row: dict) -> str:
    return (f"{deal_key(row)}:event-{int(row['event_index'])}:"
            f"seat-{int(row['seat'])}")


def bury_key(row: dict) -> str:
    return f"{deal_key(row)}:bury-seat-{int(row['seat'])}"


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


def _bury_record(row: dict) -> dict:
    return {
        "replay_key": bury_key(row),
        "deal_key": deal_key(row),
        "player_id": row["player_id"],
        "source": row["source"],
        "round": row["round"],
        "seat": row["seat"],
        "banker": row["banker"],
        "trump_rank": row["trump_rank"],
        "trump_suit": row["trump_suit"],
        "trump_is_nt": row["trump_is_nt"],
        "human_bury": row["chosen"],
        "point_total": row["point_total"],
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
                 v11_checkpoint: Path, *, smoke: bool) -> dict:
    manifest, plays, buries = validate_corpus(
        corpus_dir, expected_manifest_sha256)
    v11 = validate_v11_checkpoint(v11_checkpoint)
    live_parent = live_parent_contract()
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
    split_buries = {
        split: sorted(
            (row for row in buries
             if player_assignment[row["player_id"]] == split),
            key=bury_key,
        )
        for split in ("DESIGN", "AUDIT")
    }
    selected = {
        split: select_rows(
            split_rows[split], target=PLAY_TARGETS[split],
            cell_targets=CELL_TARGETS[split])
        for split in ("DESIGN", "AUDIT")
    }
    split_component = {item["assignment"]: item for item in assignments}
    for split, target in BURY_TARGETS.items():
        if (split_component[split]["bury_rows"] != target
                or len(split_buries[split]) != target):
            raise H0PacketError(f"{split} bury population drift")

    selected_records = {
        split: [_row_record(row) for row in selected[split]]
        for split in ("DESIGN", "AUDIT")
    }
    selected_play_rows_sha256 = sha256_bytes(canonical_json(selected_records))
    if selected_play_rows_sha256 != V2_SELECTED_PLAY_ROWS_SHA256:
        raise H0PacketError("v2 selected play population drift")
    selected_bury_records = {
        split: [_bury_record(row) for row in split_buries[split]]
        for split in ("DESIGN", "AUDIT")
    }
    selected_bury_rows_sha256 = sha256_bytes(
        canonical_json(selected_bury_records))

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
        "supersedes": {
            "schema": "human-h0-counterfactual-design-v2",
            "packet_id": "human-v8-h0-counterfactual-pilot-v2",
            "packet_sha256": V2_PACKET_SHA256,
            "selected_play_rows_sha256": V2_SELECTED_PLAY_ROWS_SHA256,
            "reason": (
                "v2 repaired model identity but did not bound its analysis "
                "ballot, conflated the root report-LCB rule with rollout "
                "continuation, and requested undefined candidate recall"
            ),
            "v2_outcomes_computed": False,
        },
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
            "selected": selected_records,
            "selected_play_rows_sha256": selected_play_rows_sha256,
            "bury_surface": {
                "DESIGN": components[0]["bury_rows"],
                "AUDIT": components[1]["bury_rows"],
                "selection": "all reviewed buries in each split",
                "estimand_separate_from_play": True,
                "selected": selected_bury_records,
                "selected_bury_rows_sha256": selected_bury_rows_sha256,
            },
        },
        "proposal_contract": proposal_contract(live_parent, v11),
        "counterfactual_execution_required": execution_contract(),
        "authority": {
            "score_free": True,
            "outcomes_computed": False,
            "design_review_authorized": True,
            "execution_controller_implementation_authorized": False,
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
            or authority.get("execution_controller_implementation_authorized")
            is not False
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
        child.add_argument("--v11-checkpoint", required=True)
        child.add_argument("--packet", required=True)
        child.add_argument("--expected-git")
        child.add_argument("--smoke", action="store_true")
    return parser


def main() -> None:
    args = _parser().parse_args()
    if args.expected_git and _git("rev-parse", "HEAD") != args.expected_git:
        raise H0PacketError("producer Git differs from expected Git")
    expected = build_packet(
        Path(args.corpus), args.expected_corpus_sha256,
        Path(args.v11_checkpoint), smoke=args.smoke)
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
