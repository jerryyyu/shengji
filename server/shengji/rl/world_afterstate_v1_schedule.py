"""Outcome-blind P1 fit/select split and root-grouped batch schedule.

The split consumes only public population identities, never V0 outcomes or V1
advantages.  All state groups from one deal remain indivisible.  The schedule
then joins the frozen split to authenticated natural pairs and packs complete
roots without exceeding an explicit pair cap.

This module grants no data opening, training execution, audit/report opening,
gameplay, strength, merge, promotion, deployment, retry, or R5 authority.
"""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from typing import Any, Mapping, Sequence

from .belief_contract import canonical_json_bytes
from .world_afterstate_v1_dataset import JoinedAdvantageV1
from .world_afterstate_v1_training import (
    AdvantageTrainingBatchV1, collate_training_pairs)


SUBSPLIT_SCHEMA = "world-afterstate-advantage-subsplit-v1"
SCHEDULE_SCHEMA = "world-afterstate-advantage-batch-schedule-v1"
SELECT_MODULUS = 5
SELECT_RESIDUES = (0,)
AUTHORITY = {
    "dataset_opening_authorized": False,
    "training_execution_authorized": False,
    "audit_opening_authorized": False,
    "report_opening_authorized": False,
    "world_twin_generation_authorized": False,
    "gameplay_authorized": False,
    "strength_claim_authorized": False,
    "merge_authorized": False,
    "promotion_authorized": False,
    "deployment_authorized": False,
    "retry_authorized": False,
    "r5_authorized": False,
}


class WorldAfterstateV1ScheduleError(ValueError):
    """A split identity, deal grouping, schedule, or batch drifted."""


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _digest(value: object, label: str) -> str:
    if type(value) is not str or len(value) != 64 \
            or any(char not in "0123456789abcdef" for char in value):
        raise WorldAfterstateV1ScheduleError(f"{label} drift")
    return value


def deal_subsplit(deal_group_sha256: str) -> str:
    """Return the fixed 80/20 deal-level split without reading outcomes."""
    _digest(deal_group_sha256, "subsplit deal-group SHA-256")
    bucket = int.from_bytes(hashlib.sha256(canonical_json_bytes({
        "namespace": "world-afterstate-v1-p1-subsplit",
        "deal_group_sha256": deal_group_sha256,
    })).digest()[:8], "big") % SELECT_MODULUS
    return "select" if bucket in SELECT_RESIDUES else "fit"


def build_subsplit_manifest(
        state_bindings: Sequence[Mapping[str, Any]], *,
        v0_population_manifest_sha256: str) -> dict[str, Any]:
    """Freeze state/deal identities only; outcome keys are structurally absent."""
    _digest(v0_population_manifest_sha256,
            "V0 population manifest SHA-256")
    if type(state_bindings) not in (list, tuple) or not state_bindings:
        raise WorldAfterstateV1ScheduleError(
            "subsplit state population drift")
    rows = []
    seen_states = set()
    split_by_deal = {}
    counts = Counter()
    for value in state_bindings:
        if type(value) is not dict or set(value) != {
                "deal_group_sha256", "state_group_id", "fold"} \
                or value.get("fold") != "train":
            raise WorldAfterstateV1ScheduleError(
                "subsplit state binding drift")
        deal = _digest(value["deal_group_sha256"],
                       "subsplit deal-group SHA-256")
        state = _digest(value["state_group_id"],
                        "subsplit state-group id")
        if state in seen_states:
            raise WorldAfterstateV1ScheduleError(
                "duplicate subsplit state group")
        seen_states.add(state)
        split = deal_subsplit(deal)
        previous = split_by_deal.setdefault(deal, split)
        if previous != split:
            raise WorldAfterstateV1ScheduleError(
                "subsplit divided one deal")
        counts[split] += 1
        rows.append({
            "deal_group_sha256": deal, "state_group_id": state,
            "split": split,
        })
    rows.sort(key=lambda row: row["state_group_id"])
    if not counts["fit"] or not counts["select"]:
        raise WorldAfterstateV1ScheduleError(
            "subsplit has an empty partition")
    body = {
        "schema": SUBSPLIT_SCHEMA,
        "v0_population_manifest_sha256": v0_population_manifest_sha256,
        "select_modulus": SELECT_MODULUS,
        "select_residues": list(SELECT_RESIDUES),
        "deal_count": len(split_by_deal),
        "state_count": len(rows),
        "fit_state_count": counts["fit"],
        "select_state_count": counts["select"],
        "states": rows,
        "outcome_fields_present": False,
        "authority": dict(AUTHORITY),
    }
    return {**body, "manifest_sha256": _sha(body)}


def validate_subsplit_manifest(value: object) -> None:
    required = {
        "schema", "v0_population_manifest_sha256", "select_modulus",
        "select_residues", "deal_count", "state_count", "fit_state_count",
        "select_state_count", "states", "outcome_fields_present",
        "authority", "manifest_sha256",
    }
    if type(value) is not dict or set(value) != required \
            or value.get("schema") != SUBSPLIT_SCHEMA \
            or value.get("select_modulus") != SELECT_MODULUS \
            or value.get("select_residues") != list(SELECT_RESIDUES) \
            or value.get("outcome_fields_present") is not False \
            or value.get("authority") != AUTHORITY:
        raise WorldAfterstateV1ScheduleError("subsplit manifest schema drift")
    _digest(value.get("v0_population_manifest_sha256"),
            "V0 population manifest SHA-256")
    _digest(value.get("manifest_sha256"), "subsplit manifest SHA-256")
    states = value.get("states")
    integer_names = (
        "deal_count", "state_count", "fit_state_count",
        "select_state_count",
    )
    if type(states) is not list \
            or any(isinstance(value.get(name), bool)
                   or not isinstance(value.get(name), int)
                   or value[name] <= 0 for name in integer_names):
        raise WorldAfterstateV1ScheduleError(
            "subsplit manifest population drift")
    previous = None
    seen_states = set()
    split_by_deal = {}
    counts = Counter()
    for row in states:
        if type(row) is not dict or set(row) != {
                "deal_group_sha256", "state_group_id", "split"} \
                or row.get("split") not in ("fit", "select"):
            raise WorldAfterstateV1ScheduleError(
                "subsplit manifest state drift")
        deal = _digest(row["deal_group_sha256"],
                       "subsplit deal-group SHA-256")
        state = _digest(row["state_group_id"],
                        "subsplit state-group id")
        if state in seen_states or previous is not None and state <= previous \
                or row["split"] != deal_subsplit(deal):
            raise WorldAfterstateV1ScheduleError(
                "subsplit manifest state order/derivation drift")
        seen_states.add(state)
        previous = state
        if split_by_deal.setdefault(deal, row["split"]) != row["split"]:
            raise WorldAfterstateV1ScheduleError(
                "subsplit manifest divided one deal")
        counts[row["split"]] += 1
    body = {key: item for key, item in value.items()
            if key != "manifest_sha256"}
    if value["deal_count"] != len(split_by_deal) \
            or value["state_count"] != len(states) \
            or value["fit_state_count"] != counts["fit"] \
            or value["select_state_count"] != counts["select"] \
            or value["manifest_sha256"] != _sha(body):
        raise WorldAfterstateV1ScheduleError(
            "subsplit manifest reconstruction drift")


def build_training_batches(
        joined: Sequence[JoinedAdvantageV1], *,
        subsplit_manifest: Mapping[str, Any], split: str,
        pair_cap: int, schedule_seed: int, epoch: int) \
        -> tuple[tuple[AdvantageTrainingBatchV1, ...], dict[str, Any]]:
    """Pack shuffled complete roots; a root is never split across batches."""
    validate_subsplit_manifest(subsplit_manifest)
    if type(joined) not in (list, tuple) or not joined \
            or split not in ("fit", "select") \
            or isinstance(pair_cap, bool) or not isinstance(pair_cap, int) \
            or pair_cap <= 0 \
            or isinstance(schedule_seed, bool) \
            or not isinstance(schedule_seed, int) \
            or not 0 <= schedule_seed < 2**63 \
            or isinstance(epoch, bool) or not isinstance(epoch, int) \
            or epoch <= 0:
        raise WorldAfterstateV1ScheduleError(
            "advantage schedule request drift")
    split_by_state = {
        row["state_group_id"]: row["split"]
        for row in subsplit_manifest["states"]
    }
    roots: dict[str, list[JoinedAdvantageV1]] = defaultdict(list)
    for value in joined:
        if type(value) is not JoinedAdvantageV1:
            raise WorldAfterstateV1ScheduleError(
                "advantage schedule pair type drift")
        value.validate()
        state = value.pair.state_group_id
        if value.pair.fold != "train" or state not in split_by_state:
            raise WorldAfterstateV1ScheduleError(
                "advantage schedule pair/subsplit binding drift")
        if split_by_state[state] == split:
            roots[state].append(value)
    expected_states = {
        state for state, assigned in split_by_state.items()
        if assigned == split
    }
    if set(roots) != expected_states or not roots:
        raise WorldAfterstateV1ScheduleError(
            "advantage schedule incomplete split population")
    for state, rows in roots.items():
        rows.sort(key=lambda value: value.key())
        # The natural collator independently proves candidate/replicate
        # completeness before any schedule is accepted.
        _ = collate_training_pairs(rows, split=split)
        if len(rows) > pair_cap:
            raise WorldAfterstateV1ScheduleError(
                "advantage root exceeds the batch pair cap")
    ordered_states = sorted(roots, key=lambda state: (
        hashlib.sha256(canonical_json_bytes({
            "namespace": "world-afterstate-v1-root-schedule",
            "schedule_seed": schedule_seed, "epoch": epoch,
            "state_group_id": state,
        })).hexdigest(), state))
    chunks = []
    pending = []
    pending_count = 0
    for state in ordered_states:
        if pending and pending_count + len(roots[state]) > pair_cap:
            chunks.append(pending)
            pending = []
            pending_count = 0
        pending.extend(roots[state])
        pending_count += len(roots[state])
    if pending:
        chunks.append(pending)
    batches = tuple(collate_training_pairs(chunk, split=split)
                    for chunk in chunks)
    used_keys = [key for batch in batches for key in batch.pair_keys]
    expected_keys = [
        f"{value.pair.state_group_id}:{value.pair.candidate_index}:"
        f"{value.pair.replicate}"
        for state in expected_states for value in roots[state]
    ]
    if len(used_keys) != len(set(used_keys)) \
            or set(used_keys) != set(expected_keys) \
            or any(len(batch.pair_keys) > pair_cap for batch in batches):
        raise WorldAfterstateV1ScheduleError(
            "advantage schedule output population drift")
    schedule_rows = [list(batch.pair_keys) for batch in batches]
    body = {
        "schema": SCHEDULE_SCHEMA,
        "subsplit_manifest_sha256": subsplit_manifest["manifest_sha256"],
        "split": split, "schedule_seed": schedule_seed, "epoch": epoch,
        "pair_cap": pair_cap, "root_count": len(roots),
        "pair_count": len(used_keys), "batch_count": len(batches),
        "batch_pair_keys": schedule_rows,
        "root_groups_never_split": True,
        "authority": dict(AUTHORITY),
    }
    return batches, {**body, "schedule_sha256": _sha(body)}


def validate_schedule_receipt(value: object) -> None:
    required = {
        "schema", "subsplit_manifest_sha256", "split", "schedule_seed",
        "epoch", "pair_cap", "root_count", "pair_count", "batch_count",
        "batch_pair_keys", "root_groups_never_split", "authority",
        "schedule_sha256",
    }
    if type(value) is not dict or set(value) != required \
            or value.get("schema") != SCHEDULE_SCHEMA \
            or value.get("split") not in ("fit", "select") \
            or value.get("root_groups_never_split") is not True \
            or value.get("authority") != AUTHORITY:
        raise WorldAfterstateV1ScheduleError("schedule receipt schema drift")
    _digest(value.get("subsplit_manifest_sha256"),
            "schedule subsplit manifest SHA-256")
    _digest(value.get("schedule_sha256"), "schedule SHA-256")
    integers = (
        "schedule_seed", "epoch", "pair_cap", "root_count", "pair_count",
        "batch_count",
    )
    if any(isinstance(value.get(name), bool)
           or not isinstance(value.get(name), int) for name in integers) \
            or not 0 <= value["schedule_seed"] < 2**63 \
            or any(value[name] <= 0 for name in integers[1:]) \
            or type(value.get("batch_pair_keys")) is not list \
            or len(value["batch_pair_keys"]) != value["batch_count"]:
        raise WorldAfterstateV1ScheduleError(
            "schedule receipt population drift")
    keys = []
    state_to_batch = {}
    for batch_index, batch in enumerate(value["batch_pair_keys"]):
        if type(batch) is not list or not batch or len(batch) > value["pair_cap"] \
                or any(type(key) is not str or key.count(":") != 2
                       for key in batch):
            raise WorldAfterstateV1ScheduleError(
                "schedule receipt batch drift")
        for key in batch:
            state = key.split(":", 1)[0]
            if state in state_to_batch and state_to_batch[state] != batch_index:
                raise WorldAfterstateV1ScheduleError(
                    "schedule receipt split one root")
            state_to_batch[state] = batch_index
            keys.append(key)
    body = {key: item for key, item in value.items()
            if key != "schedule_sha256"}
    if len(keys) != len(set(keys)) or len(keys) != value["pair_count"] \
            or len(state_to_batch) != value["root_count"] \
            or value["schedule_sha256"] != _sha(body):
        raise WorldAfterstateV1ScheduleError(
            "schedule receipt reconstruction drift")


__all__ = [
    "AUTHORITY", "WorldAfterstateV1ScheduleError", "build_subsplit_manifest",
    "build_training_batches", "deal_subsplit", "validate_schedule_receipt",
    "validate_subsplit_manifest",
]
