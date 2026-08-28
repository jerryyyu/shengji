"""Outcome-blind population bindings for the E3/E4 value experiment."""

from __future__ import annotations

import hashlib
import json
import os
import stat
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence

from .belief_contract import canonical_json_bytes
from .world_afterstate import (
    ACTOR_DECISION_SCHEMA, ROOT_REPLAY_SCHEMA, SUCCESSOR_SCHEMA,
    actor_visible_root_identity, reopen_afterstate_audit,
    replay_canonical_successor, replay_root_state)
from .world_afterstate_experiment import (
    FOLD_COUNTS, SOURCE_COUNTS, SOURCE_FOLD_COUNTS)


GROUP_SCHEMA = "world-afterstate-population-group-v0"
MANIFEST_SCHEMA = "world-afterstate-population-manifest-v0"
AUDIT_MANIFEST_SCHEMA = "world-afterstate-population-audit-manifest-v0"
FOLDS = tuple(FOLD_COUNTS)
SOURCES = tuple(SOURCE_COUNTS)
TRUMP_MODES = ("C", "D", "H", "S", "NT")
ROOT_ROLES = ("attacker", "defender")
PLAY_PHASES = ("early", "middle", "late")
POSITIONS = ("lead", "follow")
POINT_BUCKETS = ("0-39", "40-79", "80-119", "120-159", "160+")
MECHANICS_HARD_REASONS = (
    "multi-card-action", "wide-ballot", "late-high-points")
REQUIRED_AXIS_VALUES = {
    "trump_rank": tuple((
        "2", "3", "4", "5", "6", "7", "8", "9", "10",
        "J", "Q", "K", "A")),
    "trump_mode": TRUMP_MODES,
    "root_role": ROOT_ROLES,
    "play_phase": PLAY_PHASES,
    "position": POSITIONS,
}
FORBIDDEN_MANIFEST_TOKENS = (
    "attacker_points", "signed_level", "label", "logit",
    "prediction", "deal_seed", "hands", "buried",
)
POPULATION_AUTHORITY = {
    "continuation_authorized": False,
    "training_authorized": False,
    "report_opening_authorized": False,
    "gameplay_authorized": False,
    "strength_claim_authorized": False,
    "deployment_authorized": False,
}


class WorldAfterstatePopulationError(ValueError):
    """A decision identity, group, audit binding, or quota drifted."""


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _digest(value: object, label: str) -> str:
    if type(value) is not str or len(value) != 64 \
            or any(char not in "0123456789abcdef" for char in value):
        raise WorldAfterstatePopulationError(f"{label} drift")
    return value


def fold_for_deal_group(deal_group_sha256: str) -> str:
    """Assign a whole deal before outcomes; quotas are filled canonically."""
    _digest(deal_group_sha256, "deal group SHA-256")
    bucket = int(deal_group_sha256[:8], 16) % 100
    if bucket < 70:
        return "train"
    if bucket < 80:
        return "calibration"
    if bucket < 90:
        return "report"
    return "provider-audit"


def _phase(completed_tricks: int) -> str:
    if completed_tricks < 6:
        return "early"
    if completed_tricks < 14:
        return "middle"
    return "late"


def _point_bucket(attacker_points: int) -> str:
    if not 0 <= attacker_points:
        raise WorldAfterstatePopulationError(
            "population attacker-points drift")
    if attacker_points < 40:
        return "0-39"
    if attacker_points < 80:
        return "40-79"
    if attacker_points < 120:
        return "80-119"
    if attacker_points < 160:
        return "120-159"
    return "160+"


def _mechanics_hard_reasons(
        *, source: str, candidates: Sequence[Sequence[str]],
        completed_tricks: int, attacker_points: int) -> list[str]:
    if source != "mechanics-hard":
        return []
    reasons = []
    if any(len(action) > 1 for action in candidates):
        reasons.append("multi-card-action")
    if len(candidates) >= 8:
        reasons.append("wide-ballot")
    if _phase(completed_tricks) == "late" and attacker_points >= 120:
        reasons.append("late-high-points")
    return reasons


def build_population_group(
        *, deal_group_sha256: str, source: str, fold: str,
        actor_identity: Mapping[str, Any],
        audit_raws: Sequence[bytes]) -> dict[str, Any]:
    """Bind one complete production ballot without publishing hidden bytes."""
    _digest(deal_group_sha256, "deal group SHA-256")
    if source not in SOURCES or SOURCE_COUNTS[source] <= 0 \
            or fold not in FOLDS or fold != fold_for_deal_group(
                deal_group_sha256) \
            or type(actor_identity) is not dict \
            or actor_identity.get("schema") != ACTOR_DECISION_SCHEMA \
            or type(audit_raws) not in (list, tuple) or not audit_raws:
        raise WorldAfterstatePopulationError(
            "population group identity drift")
    decision_sha = _digest(
        actor_identity.get("decision_sha256"), "actor decision SHA-256")
    if actor_identity != {
            **{key: value for key, value in actor_identity.items()
               if key != "decision_sha256"},
            "decision_sha256": _sha({
                key: value for key, value in actor_identity.items()
                if key != "decision_sha256"})}:
        raise WorldAfterstatePopulationError(
            "actor decision reconstruction drift")
    candidates = actor_identity.get("ordered_candidates")
    if type(candidates) is not list or len(candidates) != len(audit_raws):
        raise WorldAfterstatePopulationError(
            "population ballot/audit count drift")
    audits = []
    roots = set()
    for index, raw in enumerate(audit_raws):
        try:
            import json
            audit = json.loads(raw.decode("ascii"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise WorldAfterstatePopulationError(
                "population audit is not canonical JSON") from exc
        if type(audit) is not dict or canonical_json_bytes(audit) != raw:
            raise WorldAfterstatePopulationError(
                "population audit is not canonical JSON")
        reopened = reopen_afterstate_audit(audit)
        roots.add((audit["prestate_sha256"], audit["root_seat"]))
        if audit["attempted_action"] != candidates[index]:
            raise WorldAfterstatePopulationError(
                "population action/audit binding drift")
        audits.append({
            "candidate_index": index,
            "action_sha256": _sha(candidates[index]),
            "audit_sha256": hashlib.sha256(raw).hexdigest(),
            "successor_sha256": audit["successor_sha256"],
            "protected_incumbent": index == 0,
        })
    if len(roots) != 1:
        raise WorldAfterstatePopulationError(
            "population sibling root drift")
    first_raw = audit_raws[0]
    import json
    first = json.loads(first_raw.decode("ascii"))
    source_state = first["source_state"]
    if source_state.get("schema") == ROOT_REPLAY_SCHEMA:
        rnd = replay_root_state(source_state)
    elif source_state.get("schema") == SUCCESSOR_SCHEMA:
        if first["root_seat"] != 0:
            raise WorldAfterstatePopulationError(
                "population canonical snapshot root-seat drift")
        rnd = replay_canonical_successor(source_state)
    else:
        raise WorldAfterstatePopulationError(
            "population source-state schema drift")
    rebuilt_identity = actor_visible_root_identity(
        rnd, first["root_seat"], candidates)
    if canonical_json_bytes(rebuilt_identity) \
            != canonical_json_bytes(actor_identity):
        raise WorldAfterstatePopulationError(
            "population actor-visible identity drift")
    trump_mode = "NT" if rnd.trump_is_nt else rnd.trump_suit
    if trump_mode not in TRUMP_MODES:
        raise WorldAfterstatePopulationError(
            "population trump mode drift")
    completed = len(rnd.history)
    mechanics_reasons = _mechanics_hard_reasons(
        source=source, candidates=candidates, completed_tricks=completed,
        attacker_points=rnd.attacker_points)
    if source == "mechanics-hard" and not mechanics_reasons:
        raise WorldAfterstatePopulationError(
            "mechanics-hard state lacks a frozen hard-state reason")
    body = {
        "schema": GROUP_SCHEMA,
        "state_group_id": _sha({
            "deal_group_sha256": deal_group_sha256,
            "decision_sha256": decision_sha,
        }),
        "deal_group_sha256": deal_group_sha256,
        "decision_sha256": decision_sha,
        "selection_priority_sha256": _sha({
            "namespace": MANIFEST_SCHEMA,
            "decision_sha256": decision_sha,
        }),
        "source": source,
        "fold": fold,
        "trump_rank": rnd.trump_rank,
        "trump_mode": trump_mode,
        "root_role": actor_identity["root_role"],
        "play_phase": _phase(completed),
        "position": "lead" if not rnd.trick.plays else "follow",
        "points_bucket": _point_bucket(rnd.attacker_points),
        "mechanics_hard_reasons": mechanics_reasons,
        "candidate_count": len(audits),
        "candidates": audits,
        "complete_ballot": True,
        "protected_incumbent_index": 0,
        "outcome_opened": False,
        "model_input_contains_metadata": False,
    }
    return {**body, "group_sha256": _sha(body)}


def validate_population_group(value: Mapping[str, Any]) -> None:
    if type(value) is not dict or set(value) != {
            "schema", "state_group_id", "deal_group_sha256",
            "decision_sha256", "selection_priority_sha256", "source",
            "fold", "trump_rank", "trump_mode", "root_role",
            "play_phase", "position", "points_bucket",
            "mechanics_hard_reasons",
            "candidate_count", "candidates",
            "complete_ballot", "protected_incumbent_index",
            "outcome_opened", "model_input_contains_metadata",
            "group_sha256"}:
        raise WorldAfterstatePopulationError(
            "population group schema drift")
    for key in (
            "state_group_id", "deal_group_sha256", "decision_sha256",
            "selection_priority_sha256", "group_sha256"):
        _digest(value[key], key)
    candidates = value["candidates"]
    if value["schema"] != GROUP_SCHEMA or value["source"] not in SOURCES \
            or SOURCE_COUNTS[value["source"]] <= 0 \
            or value["fold"] not in FOLDS \
            or value["fold"] != fold_for_deal_group(
                value["deal_group_sha256"]) \
            or value["trump_rank"] not in (
                "2", "3", "4", "5", "6", "7", "8", "9", "10",
                "J", "Q", "K", "A") \
            or value["trump_mode"] not in TRUMP_MODES \
            or value["root_role"] not in ROOT_ROLES \
            or value["play_phase"] not in PLAY_PHASES \
            or value["position"] not in POSITIONS \
            or value["points_bucket"] not in POINT_BUCKETS \
            or type(value["mechanics_hard_reasons"]) is not list \
            or any(reason not in MECHANICS_HARD_REASONS
                   for reason in value["mechanics_hard_reasons"]) \
            or len(set(value["mechanics_hard_reasons"])) \
            != len(value["mechanics_hard_reasons"]) \
            or (value["source"] == "mechanics-hard") \
            != bool(value["mechanics_hard_reasons"]) \
            or isinstance(value["candidate_count"], bool) \
            or not isinstance(value["candidate_count"], int) \
            or value["candidate_count"] <= 0 \
            or type(candidates) is not list \
            or len(candidates) != value["candidate_count"] \
            or value["complete_ballot"] is not True \
            or value["protected_incumbent_index"] != 0 \
            or value["outcome_opened"] is not False \
            or value["model_input_contains_metadata"] is not False:
        raise WorldAfterstatePopulationError(
            "population group identity drift")
    if [row.get("candidate_index") for row in candidates] \
            != list(range(len(candidates))) \
            or [row.get("protected_incumbent") for row in candidates] \
            != [True] + [False] * (len(candidates) - 1) \
            or any(type(row) is not dict or set(row) != {
                "candidate_index", "action_sha256", "audit_sha256",
                "successor_sha256", "protected_incumbent"}
                for row in candidates):
        raise WorldAfterstatePopulationError(
            "population candidate identity drift")
    for row in candidates:
        for key in ("action_sha256", "audit_sha256", "successor_sha256"):
            _digest(row[key], key)
    if len({row["action_sha256"] for row in candidates}) != len(candidates) \
            or len({row["audit_sha256"] for row in candidates}) \
            != len(candidates):
        raise WorldAfterstatePopulationError(
            "population candidate duplicate drift")
    body = {key: item for key, item in value.items()
            if key != "group_sha256"}
    if value["state_group_id"] != _sha({
            "deal_group_sha256": value["deal_group_sha256"],
            "decision_sha256": value["decision_sha256"]}) \
            or value["selection_priority_sha256"] != _sha({
                "namespace": MANIFEST_SCHEMA,
                "decision_sha256": value["decision_sha256"]}) \
            or value["group_sha256"] != _sha(body):
        raise WorldAfterstatePopulationError(
            "population group reconstruction drift")


def build_population_manifest(groups: Sequence[Mapping[str, Any]]) \
        -> dict[str, Any]:
    if type(groups) not in (list, tuple):
        raise WorldAfterstatePopulationError(
            "population manifest group type drift")
    copied = [dict(group) for group in groups]
    for group in copied:
        validate_population_group(group)
    if len(copied) != sum(FOLD_COUNTS.values()) \
            or Counter(group["fold"] for group in copied) \
            != Counter(FOLD_COUNTS) \
            or Counter(group["source"] for group in copied) \
            != Counter(SOURCE_COUNTS):
        raise WorldAfterstatePopulationError(
            "population manifest quota drift")
    if Counter((group["fold"], group["source"]) for group in copied) \
            != Counter({(fold, source): count
                        for fold, counts in SOURCE_FOLD_COUNTS.items()
                        for source, count in counts.items()}):
        raise WorldAfterstatePopulationError(
            "population manifest source/fold quota drift")
    if len({group["state_group_id"] for group in copied}) != len(copied) \
            or len({group["decision_sha256"] for group in copied}) \
            != len(copied):
        raise WorldAfterstatePopulationError(
            "population manifest duplicate decision")
    deal_folds: dict[str, str] = {}
    for group in copied:
        previous = deal_folds.setdefault(
            group["deal_group_sha256"], group["fold"])
        if previous != group["fold"]:
            raise WorldAfterstatePopulationError(
                "population deal crossed folds")
    for axis, required in (
            ("trump_rank", set((
                "2", "3", "4", "5", "6", "7", "8", "9", "10",
                "J", "Q", "K", "A"))),
            ("trump_mode", set(TRUMP_MODES)),
            ("root_role", set(ROOT_ROLES)),
            ("play_phase", set(PLAY_PHASES)),
            ("position", set(POSITIONS))):
        if {group[axis] for group in copied} != required:
            raise WorldAfterstatePopulationError(
                f"population manifest {axis} coverage drift")
    # Every held-out decision surface is interpretable on its own; aggregate
    # coverage is not enough if one fold silently lacks no-trump or a role.
    for fold in FOLDS:
        rows = [group for group in copied if group["fold"] == fold]
        for axis, required in (
                ("trump_rank", set((
                    "2", "3", "4", "5", "6", "7", "8", "9", "10",
                    "J", "Q", "K", "A"))),
                ("trump_mode", set(TRUMP_MODES)),
                ("root_role", set(ROOT_ROLES)),
                ("play_phase", set(PLAY_PHASES)),
                ("position", set(POSITIONS))):
            if {group[axis] for group in rows} != required:
                raise WorldAfterstatePopulationError(
                    f"population manifest {fold}/{axis} coverage drift")
    ordered = sorted(copied, key=lambda row: row["state_group_id"])
    body = {
        "schema": MANIFEST_SCHEMA,
        "group_count": len(ordered),
        "candidate_count": sum(row["candidate_count"] for row in ordered),
        "fold_counts": dict(FOLD_COUNTS),
        "source_counts": dict(SOURCE_COUNTS),
        "source_fold_counts": {
            fold: dict(counts) for fold, counts in SOURCE_FOLD_COUNTS.items()
        },
        "groups": ordered,
        "outcome_opened": False,
        "model_input_contains_metadata": False,
    }
    raw = canonical_json_bytes(body).decode("ascii")
    if any(token in raw for token in FORBIDDEN_MANIFEST_TOKENS):
        raise WorldAfterstatePopulationError(
            "population manifest contains forbidden outcome/private data")
    return {**body, "manifest_sha256": _sha(body)}


def select_population_groups(
        inventory: Sequence[Mapping[str, Any]]) -> tuple[dict[str, Any], ...]:
    """Select the frozen quota population without reading any outcome.

    The production-policy stratum is deliberately responsible for complete
    decision-surface coverage in every fold.  It has the largest quota and is
    the deployment-relevant source, so PT/mechanics rows cannot accidentally
    satisfy a missing no-trump/rank/role cell while the natural source remains
    blind to it.  Selection is canonical and invariant to inventory order.
    """
    if type(inventory) not in (list, tuple):
        raise WorldAfterstatePopulationError(
            "population inventory type drift")
    rows = [dict(row) for row in inventory]
    for row in rows:
        validate_population_group(row)
    identities = [row["state_group_id"] for row in rows]
    decisions = [row["decision_sha256"] for row in rows]
    if len(identities) != len(set(identities)) \
            or len(decisions) != len(set(decisions)):
        raise WorldAfterstatePopulationError(
            "population inventory duplicate decision")
    buckets: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for fold, counts in SOURCE_FOLD_COUNTS.items():
        for source, required in counts.items():
            candidates = sorted(
                (row for row in rows
                 if row["fold"] == fold and row["source"] == source),
                key=lambda row: (
                    row["selection_priority_sha256"], row["state_group_id"]))
            if len(candidates) < required:
                raise WorldAfterstatePopulationError(
                    f"population inventory underfilled {fold}/{source}")
            buckets[(fold, source)] = candidates

    selected: list[dict[str, Any]] = []
    for fold in FOLDS:
        production = buckets[(fold, "production-policy")]
        production_quota = SOURCE_FOLD_COUNTS[fold]["production-policy"]
        missing = {(axis, value)
                   for axis, values in REQUIRED_AXIS_VALUES.items()
                   for value in values}
        chosen: list[dict[str, Any]] = []
        remaining = list(production)
        while missing:
            ranked = sorted(
                remaining,
                key=lambda row: (
                    -sum((axis, row[axis]) in missing
                         for axis in REQUIRED_AXIS_VALUES),
                    row["selection_priority_sha256"],
                    row["state_group_id"]))
            if not ranked:
                raise WorldAfterstatePopulationError(
                    f"population inventory lacks {fold} axis coverage")
            row = ranked[0]
            gain = {(axis, row[axis]) for axis in REQUIRED_AXIS_VALUES} \
                & missing
            if not gain or len(chosen) >= production_quota:
                raise WorldAfterstatePopulationError(
                    f"population inventory lacks {fold} axis coverage")
            chosen.append(row)
            remaining.remove(row)
            missing -= gain
        chosen_ids = {row["state_group_id"] for row in chosen}
        chosen.extend(row for row in production
                      if row["state_group_id"] not in chosen_ids)
        selected.extend(chosen[:production_quota])
        for source in SOURCES:
            if source == "production-policy":
                continue
            required = SOURCE_FOLD_COUNTS[fold].get(source, 0)
            if required == 0:
                continue
            selected.extend(buckets[(fold, source)][:required])

    # The manifest builder is the final exact quota, deal-split and coverage
    # authority.  Running it here proves selection did not merely count rows.
    manifest = build_population_manifest(selected)
    ordered_ids = {row["state_group_id"] for row in manifest["groups"]}
    return tuple(sorted(
        (row for row in selected if row["state_group_id"] in ordered_ids),
        key=lambda row: row["state_group_id"]))


def validate_population_manifest(value: Mapping[str, Any]) -> None:
    if type(value) is not dict or "manifest_sha256" not in value:
        raise WorldAfterstatePopulationError(
            "population manifest schema drift")
    expected = build_population_manifest(value.get("groups"))
    if canonical_json_bytes(dict(value)) != canonical_json_bytes(expected):
        raise WorldAfterstatePopulationError(
            "population manifest reconstruction drift")


def build_population_audit_manifest(
        population_manifest: Mapping[str, Any],
        materials: Sequence[tuple[Mapping[str, Any], Sequence[bytes]]]) \
        -> dict[str, Any]:
    """Bind every selected private audit without embedding hidden bytes."""
    validate_population_manifest(population_manifest)
    if type(materials) not in (list, tuple):
        raise WorldAfterstatePopulationError(
            "population audit material type drift")
    group_map = {group["state_group_id"]: group
                 for group in population_manifest["groups"]}
    seen = set()
    rows = []
    for group_value, audit_raws in materials:
        if type(group_value) is not dict:
            raise WorldAfterstatePopulationError(
                "population audit group type drift")
        group = group_map.get(group_value.get("state_group_id"))
        if group is None or canonical_json_bytes(group) \
                != canonical_json_bytes(group_value) \
                or type(audit_raws) not in (list, tuple) \
                or len(audit_raws) != group["candidate_count"]:
            raise WorldAfterstatePopulationError(
                "population audit group binding drift")
        if group["state_group_id"] in seen:
            raise WorldAfterstatePopulationError(
                "population audit duplicate group")
        seen.add(group["state_group_id"])
        parsed_audits = []
        for index, raw in enumerate(audit_raws):
            if type(raw) is not bytes \
                    or hashlib.sha256(raw).hexdigest() \
                    != group["candidates"][index]["audit_sha256"]:
                raise WorldAfterstatePopulationError(
                    "population audit byte binding drift")
            try:
                audit = json.loads(raw.decode("ascii"))
            except (UnicodeDecodeError, ValueError) as exc:
                raise WorldAfterstatePopulationError(
                    "population audit is not canonical JSON") from exc
            if type(audit) is not dict or canonical_json_bytes(audit) != raw:
                raise WorldAfterstatePopulationError(
                    "population audit is not canonical JSON")
            _ = reopen_afterstate_audit(audit)
            parsed_audits.append(audit)
            if audit["successor_sha256"] \
                    != group["candidates"][index]["successor_sha256"]:
                raise WorldAfterstatePopulationError(
                    "population audit successor binding drift")
            rows.append({
                "state_group_id": group["state_group_id"],
                "candidate_index": index,
                "relative_path": (
                    f"{group['state_group_id']}/{index:03d}.json"),
                "byte_count": len(raw),
                "audit_sha256": hashlib.sha256(raw).hexdigest(),
            })
        public = parsed_audits[0]["prestate"]["public"]
        expected_reasons = _mechanics_hard_reasons(
            source=group["source"],
            candidates=[audit["attempted_action"]
                        for audit in parsed_audits],
            completed_tricks=len(public["completed_tricks"]),
            attacker_points=public["attacker_points"])
        if expected_reasons != group["mechanics_hard_reasons"]:
            raise WorldAfterstatePopulationError(
                "population mechanics-hard reason binding drift")
    if seen != set(group_map):
        raise WorldAfterstatePopulationError(
            "population audit manifest incomplete group population")
    ordered = sorted(rows, key=lambda row: (
        row["state_group_id"], row["candidate_index"]))
    body = {
        "schema": AUDIT_MANIFEST_SCHEMA,
        "population_manifest_sha256": population_manifest["manifest_sha256"],
        "group_count": len(group_map),
        "audit_count": len(ordered),
        "total_bytes": sum(row["byte_count"] for row in ordered),
        "rows": ordered,
        "contains_private_complete_worlds": True,
        "outcome_opened": False,
        "authority": dict(POPULATION_AUTHORITY),
    }
    return {**body, "manifest_sha256": _sha(body)}


def validate_population_audit_manifest(
        value: Mapping[str, Any],
        population_manifest: Mapping[str, Any]) -> None:
    """Validate the private-file inventory without opening private bytes."""
    validate_population_manifest(population_manifest)
    required = {
        "schema", "population_manifest_sha256", "group_count",
        "audit_count", "total_bytes", "rows",
        "contains_private_complete_worlds", "outcome_opened", "authority",
        "manifest_sha256",
    }
    if type(value) is not dict or set(value) != required \
            or value.get("schema") != AUDIT_MANIFEST_SCHEMA \
            or value.get("population_manifest_sha256") \
            != population_manifest["manifest_sha256"] \
            or value.get("contains_private_complete_worlds") is not True \
            or value.get("outcome_opened") is not False \
            or value.get("authority") != POPULATION_AUTHORITY:
        raise WorldAfterstatePopulationError(
            "population audit manifest identity drift")
    groups = {group["state_group_id"]: group
              for group in population_manifest["groups"]}
    rows = value["rows"]
    if type(rows) is not list:
        raise WorldAfterstatePopulationError(
            "population audit manifest row population drift")
    seen = set()
    total_bytes = 0
    previous = None
    for row in rows:
        if type(row) is not dict or set(row) != {
                "state_group_id", "candidate_index", "relative_path",
                "byte_count", "audit_sha256"}:
            raise WorldAfterstatePopulationError(
                "population audit manifest row drift")
        group = groups.get(row["state_group_id"])
        index = row["candidate_index"]
        identity = (row["state_group_id"], index)
        expected_relative = f"{row['state_group_id']}/{index:03d}.json"
        if group is None or isinstance(index, bool) \
                or not isinstance(index, int) \
                or not 0 <= index < group["candidate_count"] \
                or identity in seen \
                or row["relative_path"] != expected_relative \
                or isinstance(row["byte_count"], bool) \
                or not isinstance(row["byte_count"], int) \
                or row["byte_count"] <= 0 \
                or row["audit_sha256"] \
                != group["candidates"][index]["audit_sha256"] \
                or (previous is not None and identity <= previous):
            raise WorldAfterstatePopulationError(
                "population audit manifest row identity drift")
        _digest(row["audit_sha256"], "population audit SHA-256")
        seen.add(identity)
        previous = identity
        total_bytes += row["byte_count"]
    expected = {
        (group["state_group_id"], index)
        for group in population_manifest["groups"]
        for index in range(group["candidate_count"])
    }
    body = {key: item for key, item in value.items()
            if key != "manifest_sha256"}
    if seen != expected or value["group_count"] != len(groups) \
            or value["audit_count"] != len(rows) \
            or value["total_bytes"] != total_bytes \
            or value["manifest_sha256"] != _sha(body):
        raise WorldAfterstatePopulationError(
            "population audit manifest reconstruction drift")


def _stable_audit_read(path: Path) -> bytes:
    if path.is_symlink():
        raise WorldAfterstatePopulationError(
            "population audit path is a symlink")
    try:
        with path.open("rb") as handle:
            before = os.fstat(handle.fileno())
            raw = handle.read()
            after = os.fstat(handle.fileno())
    except OSError as exc:
        raise WorldAfterstatePopulationError(
            "population audit file cannot be read") from exc
    if (before.st_dev, before.st_ino, before.st_size,
            before.st_mtime_ns, before.st_ctime_ns) != (
            after.st_dev, after.st_ino, after.st_size,
            after.st_mtime_ns, after.st_ctime_ns) \
            or before.st_size != len(raw) \
            or before.st_nlink != 1 \
            or stat.S_IMODE(before.st_mode) != 0o400 \
            or not stat.S_ISREG(before.st_mode):
        raise WorldAfterstatePopulationError(
            "population audit file is mutable or changed while read")
    return raw


def reopen_population_audit_manifest(
        value: Mapping[str, Any], population_manifest: Mapping[str, Any],
        audit_root: Path) -> dict[str, tuple[bytes, ...]]:
    """Open each exact private file once and parse only those bound bytes."""
    validate_population_audit_manifest(value, population_manifest)
    required = {
        "schema", "population_manifest_sha256", "group_count",
        "audit_count", "total_bytes", "rows",
        "contains_private_complete_worlds", "outcome_opened", "authority",
        "manifest_sha256",
    }
    if not isinstance(audit_root, Path) or not audit_root.is_dir() \
            or audit_root.is_symlink():
        raise WorldAfterstatePopulationError(
            "population audit manifest identity drift")
    group_map = {group["state_group_id"]: group
                 for group in population_manifest["groups"]}
    rows = value["rows"]
    if type(rows) is not list:
        raise WorldAfterstatePopulationError(
            "population audit manifest row population drift")
    expected_files = set()
    materials: dict[str, list[bytes | None]] = {
        key: [None] * group["candidate_count"]
        for key, group in group_map.items()}
    total = 0
    for row in rows:
        if type(row) is not dict or set(row) != {
                "state_group_id", "candidate_index", "relative_path",
                "byte_count", "audit_sha256"}:
            raise WorldAfterstatePopulationError(
                "population audit manifest row drift")
        group = group_map.get(row["state_group_id"])
        index = row["candidate_index"]
        expected_relative = f"{row['state_group_id']}/{index:03d}.json"
        if group is None or isinstance(index, bool) \
                or not isinstance(index, int) \
                or not 0 <= index < group["candidate_count"] \
                or row["relative_path"] != expected_relative \
                or materials[row["state_group_id"]][index] is not None:
            raise WorldAfterstatePopulationError(
                "population audit manifest row identity drift")
        path = audit_root / expected_relative
        expected_files.add(path)
        raw = _stable_audit_read(path)
        if len(raw) != row["byte_count"] \
                or hashlib.sha256(raw).hexdigest() != row["audit_sha256"] \
                or row["audit_sha256"] \
                != group["candidates"][index]["audit_sha256"]:
            raise WorldAfterstatePopulationError(
                "population audit manifest byte binding drift")
        try:
            audit = json.loads(raw.decode("ascii"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise WorldAfterstatePopulationError(
                "population audit file is not canonical JSON") from exc
        if type(audit) is not dict or canonical_json_bytes(audit) != raw:
            raise WorldAfterstatePopulationError(
                "population audit file is not canonical JSON")
        _ = reopen_afterstate_audit(audit)
        materials[row["state_group_id"]][index] = raw
        total += len(raw)
    observed_files = {path for path in audit_root.rglob("*") if path.is_file()}
    if expected_files != observed_files \
            or any(item is None for values in materials.values()
                   for item in values) \
            or value["group_count"] != len(group_map) \
            or value["audit_count"] != len(rows) \
            or value["total_bytes"] != total:
        raise WorldAfterstatePopulationError(
            "population audit manifest file population drift")
    body = {key: item for key, item in value.items()
            if key != "manifest_sha256"}
    if value["manifest_sha256"] != _sha(body):
        raise WorldAfterstatePopulationError(
            "population audit manifest reconstruction drift")
    return {key: tuple(raw for raw in values if raw is not None)
            for key, values in materials.items()}


__all__ = [
    "AUDIT_MANIFEST_SCHEMA", "FOLDS", "GROUP_SCHEMA", "MANIFEST_SCHEMA",
    "MECHANICS_HARD_REASONS", "POINT_BUCKETS", "POPULATION_AUTHORITY",
    "POSITIONS",
    "PLAY_PHASES", "ROOT_ROLES", "SOURCES", "TRUMP_MODES",
    "WorldAfterstatePopulationError", "build_population_group",
    "build_population_audit_manifest", "build_population_manifest",
    "fold_for_deal_group", "reopen_population_audit_manifest",
    "select_population_groups", "validate_population_group",
    "validate_population_audit_manifest", "validate_population_manifest",
]
