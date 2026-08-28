"""Engine-owned continuation labels for ``V_world_after``.

The reviewed engine applies the root action before this module starts.  Every
later decision is made by the same actor-visible continuation policy from the
perspective of the seat on turn.  The engine owns terminal attacker points;
``world_afterstate`` mechanically derives the 204-class signed-level label.

This module is pure source mechanics.  It has no population selector, writer,
CLI, retry, checkpoint, training, test-opening, strength, or deployment
authority.
"""

from __future__ import annotations

import copy
import hashlib
from collections import Counter
from typing import Any, Mapping

from ..ai.registry import make_bot
from ..engine.round import actual_play_after
from ..teacher_v1 import (SAMPLER_COUNTERS, sampler_delta,
                          sampler_snapshot, stable_digest, stable_json)
from .belief_contract import canonical_json_bytes
from .world_afterstate import (WorldAfterstateError, build_outcome,
                               canonical_successor, reopen_afterstate_audit,
                               validate_outcome)


LABEL_SCHEMA = "world-afterstate-continuation-label-v0"
IDENTITY_SCHEMA = "world-afterstate-continuation-identity-v0"
CONTINUATION_POLICY = "mc-strong"
FORBIDDEN_COUNTERS = (
    "failed_worlds", "rejected_worlds", "impossible_worlds",
    "short_search_decisions", "zero_world_decisions",
)


class WorldAfterstateLabelError(WorldAfterstateError):
    """A continuation stream, trace, counter, or engine outcome drifted."""


def _sha256(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(dict(value))).hexdigest()


def continuation_identity(
        *, experiment_id: str, state_group_id: str, fold: str,
        world_occurrence: int, replicate: int) -> dict[str, Any]:
    """Closed identity shared by sibling actions for common random numbers."""
    if any(type(value) is not str or not value or not value.isascii()
           for value in (experiment_id, state_group_id, fold)):
        raise WorldAfterstateLabelError("continuation text identity drift")
    for label, value in (("world occurrence", world_occurrence),
                         ("replicate", replicate)):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise WorldAfterstateLabelError(
                f"continuation {label} identity drift")
    return {
        "schema": IDENTITY_SCHEMA,
        "experiment_id": experiment_id,
        "state_group_id": state_group_id,
        "fold": fold,
        "world_occurrence": world_occurrence,
        "replicate": replicate,
    }


def validate_continuation_identity(value: Mapping[str, Any]) -> None:
    if type(value) is not dict or set(value) != {
        "schema", "experiment_id", "state_group_id", "fold",
        "world_occurrence", "replicate",
    } or value.get("schema") != IDENTITY_SCHEMA:
        raise WorldAfterstateLabelError("continuation identity schema drift")
    expected = continuation_identity(
        experiment_id=value["experiment_id"],
        state_group_id=value["state_group_id"], fold=value["fold"],
        world_occurrence=value["world_occurrence"],
        replicate=value["replicate"])
    if canonical_json_bytes(expected) != canonical_json_bytes(value):
        raise WorldAfterstateLabelError("continuation identity derivation drift")


def derive_continuation_seed(
        identity: Mapping[str, Any], *, decision: int, seat: int) -> int:
    """Derive an action-independent policy seed for one downstream decision."""
    validate_continuation_identity(identity)
    if isinstance(decision, bool) or not isinstance(decision, int) \
            or decision < 0:
        raise WorldAfterstateLabelError("continuation decision identity drift")
    if isinstance(seat, bool) or not isinstance(seat, int) or not 0 <= seat < 4:
        raise WorldAfterstateLabelError("continuation seat identity drift")
    payload = {
        **identity,
        "purpose": "actor-visible-post-root-continuation",
        "decision": decision,
        "seat": seat,
        "policy": CONTINUATION_POLICY,
    }
    return int.from_bytes(hashlib.sha256(stable_json(payload)).digest()[:16],
                          "big")


def _counter_delta(policy, before: dict[str, int]) -> dict[str, int]:
    delta = sampler_delta(before, policy)
    if delta["sample_attempts"] != (
            delta["accepted_worlds"] + delta["failed_worlds"]):
        raise WorldAfterstateLabelError(
            "continuation sampler attempts do not reconcile")
    forbidden = {name: delta[name] for name in FORBIDDEN_COUNTERS
                 if delta[name]}
    if forbidden:
        raise WorldAfterstateLabelError(
            f"continuation sampler strict-counter failure {forbidden}")
    return delta


def _derive_label(
        audit: Mapping[str, Any], identity: Mapping[str, Any]) \
        -> dict[str, Any]:
    validate_continuation_identity(identity)
    clone = reopen_afterstate_audit(audit)
    root_seat = audit["root_seat"]
    root_is_attacker = clone.is_attacker(root_seat)
    trace = []
    totals = Counter({name: 0 for name in SAMPLER_COUNTERS})
    continuation_rollouts = 0
    continuation_searches = 0
    decision = 0
    while clone.phase == "play":
        actor_seat = clone.turn
        if actor_seat is None:
            raise WorldAfterstateLabelError(
                "play continuation has no actor seat")
        seed = derive_continuation_seed(
            identity, decision=decision, seat=actor_seat)
        policy = make_bot(CONTINUATION_POLICY, seed=seed)
        before = sampler_snapshot(policy)
        attempted = policy.decide_play(clone, actor_seat)
        delta = _counter_delta(policy, before)
        totals.update(delta)
        continuation_rollouts += int(getattr(policy, "rollouts", 0))
        continuation_searches += int(getattr(policy, "search_calls", 0))
        previous_last = clone.last_trick
        clone.play(actor_seat, list(attempted))
        actual = actual_play_after(clone, actor_seat, previous_last)
        trace.append({
            "decision": decision,
            "seat": actor_seat,
            "seed": seed,
            "attempted_action": list(attempted),
            "engine_action": actual,
            "sampler_counters": delta,
        })
        decision += 1
    terminal = canonical_successor(clone, root_seat)
    outcome = build_outcome(
        audit["successor_sha256"], int(clone.attacker_points),
        root_is_attacker)
    return {
        "schema": LABEL_SCHEMA,
        "successor_sha256": audit["successor_sha256"],
        "continuation_identity": copy.deepcopy(identity),
        "continuation_policy": CONTINUATION_POLICY,
        "continuation_seed_derivation": (
            "sha256(canonical identity plus purpose,decision,seat,policy)[:16];"
            " sibling root actions deliberately omitted"),
        "trace": trace,
        "trace_sha256": stable_digest(trace),
        "continuation_decisions": len(trace),
        "continuation_rollouts": continuation_rollouts,
        "continuation_searches": continuation_searches,
        "sampler_counters": dict(totals),
        "terminal_state": terminal,
        "terminal_state_sha256": _sha256(terminal),
        "outcome": outcome,
        "authority": {
            "training_authorized": False,
            "test_opening_authorized": False,
            "gameplay_authorized": False,
            "strength_claim_authorized": False,
            "deployment_authorized": False,
        },
    }


def run_afterstate_continuation(
        audit: Mapping[str, Any], identity: Mapping[str, Any]) \
        -> dict[str, Any]:
    """Run and return one deterministic raw engine continuation outcome."""
    return _derive_label(audit, identity)


def reopen_afterstate_continuation(
        audit: Mapping[str, Any], value: Mapping[str, Any]) -> dict[str, Any]:
    """Rerun the continuation and byte-compare the complete label record."""
    if type(value) is not dict or value.get("schema") != LABEL_SCHEMA:
        raise WorldAfterstateLabelError("continuation label schema drift")
    required = {
        "schema", "successor_sha256", "continuation_identity",
        "continuation_policy", "continuation_seed_derivation", "trace",
        "trace_sha256", "continuation_decisions", "continuation_rollouts",
        "continuation_searches", "sampler_counters", "terminal_state",
        "terminal_state_sha256", "outcome", "authority",
    }
    if set(value) != required:
        raise WorldAfterstateLabelError(
            "continuation label field population drift")
    if value["successor_sha256"] != audit.get("successor_sha256"):
        raise WorldAfterstateLabelError("continuation successor binding drift")
    validate_outcome(value["outcome"])
    expected = _derive_label(audit, value["continuation_identity"])
    if canonical_json_bytes(expected) != canonical_json_bytes(value):
        raise WorldAfterstateLabelError("continuation label reconstruction drift")
    return expected
