"""Materialize sealed V2 continuation outcomes from population material.

This is the narrow source bridge between the outcome-blind population and the
typed V2 label consumer.  The engine-owned continuation implementation remains
the only simulator; this module only supplies its domain-separated identity,
reopens its receipts, and binds the resulting category to a candidate row.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from ..teacher_v1 import stable_digest
from .belief_contract import canonical_json_bytes
from .world_afterstate import (
    WorldAfterstateError,
    SUCCESSOR_SCHEMA,
    category_signed_level,
    reopen_afterstate_audit,
    replay_canonical_successor,
    validate_outcome,
)
from .world_afterstate_label import (
    LABEL_SCHEMA,
    continuation_identity,
    derive_continuation_seed,
    reopen_afterstate_continuation,
    run_afterstate_continuation,
    validate_continuation_identity,
)
from .world_afterstate_capacity import PRODUCTION_BALLOT_POLICY
from .world_afterstate_v2_label import ContinuationOutcomeV2
from .world_afterstate_v2_population import PopulationMaterialV2


SCHEMA = "world-afterstate-v2-continuation-bundle-v1"
RECEIPT_SCHEMA = "world-afterstate-v2-raw-label-receipt-v1"
IDENTITY_EXPERIMENT = "world-afterstate-v2-continuation-v1"
REPLICATES = tuple(range(8))
V2_CONTINUATION_POLICY = PRODUCTION_BALLOT_POLICY
AUTHORITY = {
    "dataset_opening_authorized": False,
    "audit_opening_authorized": False,
    "training_authorized": False,
    "gameplay_authorized": False,
    "strength_claim_authorized": False,
    "writer_authorized": False,
    "cli_authorized": False,
}


class WorldAfterstateV2ContinuationError(ValueError):
    """A V2 continuation receipt, row, or bundle binding drifted."""


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha(value: object) -> str:
    return _sha_bytes(canonical_json_bytes(value))


def _digest(value: object, label: str) -> str:
    if type(value) is not str or len(value) != 64 or any(
            char not in "0123456789abcdef" for char in value):
        raise WorldAfterstateV2ContinuationError(f"{label} drift")
    return value


def _point_bucket(points: object) -> str:
    if isinstance(points, bool) or not isinstance(points, int) or points < 0:
        raise WorldAfterstateV2ContinuationError("points bucket source drift")
    if points < 40:
        return "0-39"
    if points < 80:
        return "40-79"
    if points < 120:
        return "80-119"
    if points < 160:
        return "120-159"
    return "160+"


def _audit(raw: bytes) -> dict[str, Any]:
    if type(raw) is not bytes:
        raise WorldAfterstateV2ContinuationError("audit bytes drift")
    try:
        value = json.loads(raw.decode("ascii"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise WorldAfterstateV2ContinuationError(
            "audit is not canonical JSON") from exc
    if type(value) is not dict or canonical_json_bytes(value) != raw:
        raise WorldAfterstateV2ContinuationError("audit canonical bytes drift")
    try:
        reopen_afterstate_audit(value)
    except WorldAfterstateError as exc:
        raise WorldAfterstateV2ContinuationError(
            "audit reconstruction drift") from exc
    return value


def _identity(material: PopulationMaterialV2, replica: int) -> dict[str, Any]:
    # ``state_sha256`` is the state group identity.  No candidate, attempted
    # action, successor, or candidate-set value enters this identity.
    return continuation_identity(
        experiment_id=IDENTITY_EXPERIMENT,
        state_group_id=material.state_sha256,
        fold=material.state.split,
        world_occurrence=0,
        replicate=replica,
    )


@dataclass(frozen=True)
class RawLabelReceiptV2:
    """Private canonical engine label bytes and their immutable identity."""

    candidate_index: int
    replica: int
    continuation_sha256: str
    raw: bytes
    raw_sha256: str
    schema: str = RECEIPT_SCHEMA

    def validate(self) -> None:
        if self.schema != RECEIPT_SCHEMA:
            raise WorldAfterstateV2ContinuationError("label receipt schema drift")
        if isinstance(self.candidate_index, bool) or not isinstance(
                self.candidate_index, int) or self.candidate_index < 0:
            raise WorldAfterstateV2ContinuationError("label candidate index drift")
        if isinstance(self.replica, bool) or self.replica not in REPLICATES:
            raise WorldAfterstateV2ContinuationError("label replica drift")
        _digest(self.continuation_sha256, "label continuation SHA-256")
        if type(self.raw) is not bytes or _sha_bytes(self.raw) != self.raw_sha256:
            raise WorldAfterstateV2ContinuationError("label raw byte binding drift")
        _digest(self.raw_sha256, "label raw SHA-256")
        try:
            value = json.loads(self.raw.decode("ascii"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise WorldAfterstateV2ContinuationError(
                "label raw bytes are not canonical JSON") from exc
        if type(value) is not dict or canonical_json_bytes(value) != self.raw:
            raise WorldAfterstateV2ContinuationError("label raw canonical bytes drift")
        try:
            identity = value["continuation_identity"]
            validate_continuation_identity(identity)
        except (KeyError, TypeError, WorldAfterstateError) as exc:
            raise WorldAfterstateV2ContinuationError(
                "label identity reconstruction drift") from exc
        if _sha(identity) != self.continuation_sha256:
            raise WorldAfterstateV2ContinuationError(
                "label continuation identity/hash drift")
        if identity["replicate"] != self.replica:
            raise WorldAfterstateV2ContinuationError(
                "label replica/identity binding drift")

    @property
    def raw_bytes(self) -> bytes:
        return self.raw

    @property
    def raw_label(self) -> bytes:
        return self.raw

    @property
    def continuation_identity(self) -> dict[str, Any]:
        value = json.loads(self.raw.decode("ascii"))
        return copy.deepcopy(value["continuation_identity"])


@dataclass(frozen=True)
class ContinuationBundleV2:
    """One state, complete candidate set, and all 8xN sealed label rows."""

    deal_sha256: str
    slot_sha256: str
    state_sha256: str
    candidate_set_sha256: str
    candidates: tuple[ContinuationOutcomeV2, ...]
    labels: tuple[RawLabelReceiptV2, ...]
    canonical_bytes: bytes
    bundle_sha256: str
    schema: str = SCHEMA
    authority: Mapping[str, bool] = field(
        default_factory=lambda: dict(AUTHORITY))

    def _payload(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "deal_sha256": self.deal_sha256,
            "slot_sha256": self.slot_sha256,
            "state_sha256": self.state_sha256,
            "candidate_set_sha256": self.candidate_set_sha256,
            "candidates": [row.__dict__ for row in self.candidates],
            "labels": [
                {
                    "schema": receipt.schema,
                    "candidate_index": receipt.candidate_index,
                    "replica": receipt.replica,
                    "continuation_sha256": receipt.continuation_sha256,
                    "raw": json.loads(receipt.raw.decode("ascii")),
                    "raw_sha256": receipt.raw_sha256,
                }
                for receipt in self.labels
            ],
            "authority": dict(self.authority),
        }

    def validate(self) -> None:
        if self.schema != SCHEMA or self.authority != AUTHORITY:
            raise WorldAfterstateV2ContinuationError("bundle schema/authority drift")
        for label, value in (("bundle deal SHA-256", self.deal_sha256),
                             ("bundle slot SHA-256", self.slot_sha256),
                             ("bundle state SHA-256", self.state_sha256),
                             ("bundle candidate-set SHA-256",
                              self.candidate_set_sha256),
                             ("bundle SHA-256", self.bundle_sha256)):
            _digest(value, label)
        if type(self.canonical_bytes) is not bytes:
            raise WorldAfterstateV2ContinuationError("bundle canonical bytes drift")
        try:
            encoded = json.loads(self.canonical_bytes.decode("ascii"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise WorldAfterstateV2ContinuationError(
                "bundle canonical JSON drift") from exc
        if canonical_json_bytes(encoded) != self.canonical_bytes \
                or encoded != self._payload():
            raise WorldAfterstateV2ContinuationError(
                "bundle canonical reconstruction drift")
        if _sha_bytes(self.canonical_bytes) != self.bundle_sha256:
            raise WorldAfterstateV2ContinuationError("bundle hash drift")
        if type(self.candidates) is not tuple or not self.candidates \
                or type(self.labels) is not tuple:
            raise WorldAfterstateV2ContinuationError("bundle population drift")
        if len(self.candidates) < 2 * len(REPLICATES) \
                or len(self.labels) != len(self.candidates):
            raise WorldAfterstateV2ContinuationError("bundle label population drift")
        indexes = sorted({row.candidate_index for row in self.candidates})
        count = len(indexes)
        if indexes != list(range(count)) \
                or len(self.candidates) != count * len(REPLICATES):
            raise WorldAfterstateV2ContinuationError("bundle candidate index drift")
        successors = []
        rows_by_key: dict[tuple[int, int], ContinuationOutcomeV2] = {}
        for row in self.candidates:
            if type(row) is not ContinuationOutcomeV2:
                raise WorldAfterstateV2ContinuationError("bundle outcome type drift")
            try:
                row.validate()
            except Exception as exc:
                raise WorldAfterstateV2ContinuationError(
                    "bundle outcome validation drift") from exc
            if (row.deal_sha256, row.slot_sha256, row.state_sha256,
                    row.candidate_set_sha256) != (
                        self.deal_sha256, self.slot_sha256, self.state_sha256,
                        self.candidate_set_sha256):
                raise WorldAfterstateV2ContinuationError(
                    "bundle outcome state binding drift")
            if row.protected_incumbent != (row.candidate_index == 0):
                raise WorldAfterstateV2ContinuationError(
                    "bundle incumbent/index drift")
            if row.replica not in REPLICATES:
                raise WorldAfterstateV2ContinuationError(
                    "bundle replica population drift")
            key = (row.candidate_index, row.replica)
            if key in rows_by_key:
                raise WorldAfterstateV2ContinuationError("bundle outcome duplicate")
            rows_by_key[key] = row
        for index in indexes:
            candidate_successors = {
                rows_by_key[(index, replica)].successor_sha256
                for replica in REPLICATES}
            if len(candidate_successors) != 1:
                raise WorldAfterstateV2ContinuationError(
                    "bundle successor identity drift")
            successors.append(next(iter(candidate_successors)))
        # Reuse the exact digest recipe consumed by the typed label consumer.
        expected_set = _sha({
            "schema": "world-afterstate-v2-candidate-set-v1",
            "state_sha256": self.state_sha256,
            "successor_sha256s": successors,
        })
        if expected_set != self.candidate_set_sha256:
            raise WorldAfterstateV2ContinuationError("bundle candidate-set drift")
        by_key: dict[tuple[int, int], RawLabelReceiptV2] = {}
        for receipt in self.labels:
            if type(receipt) is not RawLabelReceiptV2:
                raise WorldAfterstateV2ContinuationError("bundle label type drift")
            receipt.validate()
            key = (receipt.candidate_index, receipt.replica)
            if key in by_key or receipt.candidate_index not in range(count):
                raise WorldAfterstateV2ContinuationError(
                    "bundle label candidate/replica drop or duplicate")
            by_key[key] = receipt
            identity = receipt.continuation_identity
            expected = _identity_from_fields(self.state_sha256,
                                             rows_by_key[(0, 0)].split,
                                             receipt.replica)
            if identity != expected:
                raise WorldAfterstateV2ContinuationError(
                    "bundle continuation identity drift")
            if receipt.continuation_sha256 != _sha(identity):
                raise WorldAfterstateV2ContinuationError(
                    "bundle continuation hash drift")
            label = json.loads(receipt.raw.decode("ascii"))
            candidate = rows_by_key[(receipt.candidate_index, receipt.replica)]
            if label.get("successor_sha256") != candidate.successor_sha256:
                raise WorldAfterstateV2ContinuationError(
                    "bundle label successor binding drift")
            try:
                validate_outcome(label["outcome"])
            except (KeyError, WorldAfterstateError) as exc:
                raise WorldAfterstateV2ContinuationError(
                    "bundle raw outcome mechanics drift") from exc
            if label["outcome"]["signed_level_category"] != \
                    candidate.signed_level_category:
                raise WorldAfterstateV2ContinuationError(
                    "bundle category binding drift")
            if label["outcome"]["root_is_attacker"] != (
                    candidate.role == "attacker"):
                raise WorldAfterstateV2ContinuationError(
                    "bundle perspective binding drift")
        expected_keys = {(index, replica) for index in range(count)
                         for replica in REPLICATES}
        if set(by_key) != expected_keys:
            raise WorldAfterstateV2ContinuationError("bundle label population drift")
        for key, row in rows_by_key.items():
            index, replica = key
            receipt = by_key[(index, replica)]
            if receipt.continuation_sha256 != row.continuation_sha256:
                raise WorldAfterstateV2ContinuationError(
                    "bundle sibling continuation binding drift")
        for index in indexes:
            for replica in REPLICATES:
                receipt = by_key[(index, replica)]
                if receipt.continuation_sha256 != rows_by_key[(index, replica)].continuation_sha256:
                    raise WorldAfterstateV2ContinuationError(
                        "bundle sibling continuation binding drift")

    @property
    def raw_label_receipts(self) -> tuple[RawLabelReceiptV2, ...]:
        return self.labels

    @property
    def raw_labels(self) -> tuple[RawLabelReceiptV2, ...]:
        return self.labels

    @property
    def outcomes(self) -> tuple[ContinuationOutcomeV2, ...]:
        return self.candidates

    @property
    def outcome_rows(self) -> tuple[ContinuationOutcomeV2, ...]:
        return self.candidates

    @property
    def label_receipts(self) -> tuple[RawLabelReceiptV2, ...]:
        return self.labels

    @property
    def sealed_bytes(self) -> bytes:
        return self.canonical_bytes

    @property
    def sha256(self) -> str:
        return self.bundle_sha256

    def reopen(self, material: PopulationMaterialV2) -> "ContinuationBundleV2":
        """Reconstruct this seal from the retained private population material."""
        return reopen_continuation_bundle_v2(self, material)


def _identity_from_fields(state_sha256: str, fold: str,
                          replica: int) -> dict[str, Any]:
    return continuation_identity(
        experiment_id=IDENTITY_EXPERIMENT, state_group_id=state_sha256,
        fold=fold, world_occurrence=0, replicate=replica)


def _validate_stored_label(
        audit: Mapping[str, Any], label: Mapping[str, Any],
        identity: Mapping[str, Any], *, expected_successor: str,
        expected_continuation_policy: str = V2_CONTINUATION_POLICY) -> None:
    """Validate a sealed label without invoking continuation simulation.

    The source label module intentionally exposes a rerunning ``reopen``
    helper for engine-level parity tests.  That helper is not suitable for an
    ordinary artifact reopen: all evidence needed for this contract is already
    present in the canonical label bytes.
    """
    if type(label) is not dict:
        raise WorldAfterstateV2ContinuationError("stored label type drift")
    if label.get("successor_sha256") != expected_successor:
        raise WorldAfterstateV2ContinuationError(
            "stored label successor binding drift")

    # Keep the historical source-layer fixture compatibility (the source
    # bridge has always accepted opaque private labels), while applying the
    # complete stored-result contract to production labels.
    if label.get("schema") != LABEL_SCHEMA:
        try:
            validate_outcome(label["outcome"])
        except (KeyError, TypeError, WorldAfterstateError) as exc:
            raise WorldAfterstateV2ContinuationError(
                "stored opaque label outcome drift") from exc
        return

    required = {
        "schema", "successor_sha256", "continuation_identity",
        "continuation_policy", "continuation_seed_derivation", "trace",
        "trace_sha256", "continuation_decisions", "continuation_rollouts",
        "continuation_searches", "sampler_counters", "terminal_state",
        "terminal_state_sha256", "outcome", "authority",
    }
    if set(label) != required:
        raise WorldAfterstateV2ContinuationError(
            "stored label field population drift")
    try:
        validate_continuation_identity(label["continuation_identity"])
    except (TypeError, ValueError, WorldAfterstateError) as exc:
        raise WorldAfterstateV2ContinuationError(
            "stored label identity drift") from exc
    if label["continuation_identity"] != identity:
        raise WorldAfterstateV2ContinuationError(
            "stored label continuation identity binding drift")
    policy = label["continuation_policy"]
    if type(policy) is not str or not policy \
            or policy != expected_continuation_policy or label[
            "continuation_seed_derivation"] != (
                "sha256(canonical identity plus purpose,decision,seat,policy)[:16];"
                " sibling root actions deliberately omitted"):
        raise WorldAfterstateV2ContinuationError(
            "stored label policy binding drift")

    trace = label["trace"]
    if type(trace) is not list or stable_digest(trace) != label["trace_sha256"]:
        raise WorldAfterstateV2ContinuationError(
            "stored label trace hash drift")
    decisions = label["continuation_decisions"]
    if isinstance(decisions, bool) or not isinstance(decisions, int) \
            or decisions != len(trace):
        raise WorldAfterstateV2ContinuationError(
            "stored label decision count drift")
    counter_names = (
        "sample_attempts", "accepted_worlds", "failed_worlds",
        "rejected_worlds", "impossible_worlds", "short_search_decisions",
        "zero_world_decisions")
    totals = label["sampler_counters"]
    if type(totals) is not dict or set(totals) != set(counter_names):
        raise WorldAfterstateV2ContinuationError(
            "stored label sampler counter schema drift")
    summed = {name: 0 for name in counter_names}
    for index, row in enumerate(trace):
        if type(row) is not dict or set(row) != {
                "decision", "seat", "seed", "attempted_action", "engine_action",
                "sampler_counters"}:
            raise WorldAfterstateV2ContinuationError(
                "stored label trace row drift")
        if row["decision"] != index or isinstance(row["decision"], bool) \
                or not isinstance(row["decision"], int):
            raise WorldAfterstateV2ContinuationError(
                "stored label trace decision drift")
        if isinstance(row["seat"], bool) or not isinstance(row["seat"], int) \
                or not 0 <= row["seat"] < 4:
            raise WorldAfterstateV2ContinuationError(
                "stored label trace seat drift")
        if isinstance(row["seed"], bool) or not isinstance(row["seed"], int) \
                or row["seed"] < 0:
            raise WorldAfterstateV2ContinuationError(
                "stored label trace seed drift")
        try:
            expected_seed = derive_continuation_seed(
                identity, decision=index, seat=row["seat"],
                policy_name=policy)
        except Exception as exc:
            raise WorldAfterstateV2ContinuationError(
                "stored label trace seed derivation drift") from exc
        if row["seed"] != expected_seed:
            raise WorldAfterstateV2ContinuationError(
                "stored label trace policy seed binding drift")
        if type(row["attempted_action"]) is not list \
                or type(row["engine_action"]) is not list:
            raise WorldAfterstateV2ContinuationError(
                "stored label trace action drift")
        counters = row["sampler_counters"]
        if type(counters) is not dict or set(counters) != set(counter_names):
            raise WorldAfterstateV2ContinuationError(
                "stored label trace counter schema drift")
        for name in counter_names:
            value = counters[name]
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise WorldAfterstateV2ContinuationError(
                    "stored label trace counter drift")
            summed[name] += value
    for name in counter_names:
        value = totals[name]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0 \
                or value != summed[name]:
            raise WorldAfterstateV2ContinuationError(
                "stored label sampler total drift")
    if totals["sample_attempts"] != totals["accepted_worlds"] + totals[
            "failed_worlds"] or any(totals[name] for name in counter_names[3:]):
        raise WorldAfterstateV2ContinuationError(
            "stored label sampler reconciliation drift")
    for name in ("continuation_rollouts", "continuation_searches"):
        value = label[name]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise WorldAfterstateV2ContinuationError(
                "stored label search counter drift")

    terminal = label["terminal_state"]
    if type(terminal) is not dict or _sha(terminal) != label[
            "terminal_state_sha256"]:
        raise WorldAfterstateV2ContinuationError(
            "stored label terminal bytes/hash drift")
    public = terminal.get("public")
    if type(public) is not dict or terminal.get("schema") != SUCCESSOR_SCHEMA \
            or public.get("phase") != "round_end" \
            or public.get("terminal") is not True or public.get("turn") is not None:
        raise WorldAfterstateV2ContinuationError(
            "stored label terminal semantics drift")
    try:
        replay_canonical_successor(terminal)
    except Exception as exc:
        raise WorldAfterstateV2ContinuationError(
            "stored label terminal reconstruction drift") from exc
    try:
        validate_outcome(label["outcome"])
    except (KeyError, TypeError, WorldAfterstateError) as exc:
        raise WorldAfterstateV2ContinuationError(
            "stored label outcome mechanics drift") from exc
    outcome = label["outcome"]
    if outcome["successor_sha256"] != expected_successor \
            or outcome["attacker_points"] != public.get("attacker_points") \
            or outcome["root_is_attacker"] != (
                terminal.get("root_role") == "attacker"):
        raise WorldAfterstateV2ContinuationError(
            "stored label result binding drift")
    authority = label["authority"]
    if type(authority) is not dict or set(authority) != {
            "training_authorized", "test_opening_authorized",
            "gameplay_authorized", "strength_claim_authorized",
            "deployment_authorized"} or any(value is not False
                                             for value in authority.values()):
        raise WorldAfterstateV2ContinuationError(
            "stored label authority drift")


def build_continuation_bundle_v2(
        material: PopulationMaterialV2) -> ContinuationBundleV2:
    """Run/reopen all eight CRN labels for every validated candidate."""
    if type(material) is not PopulationMaterialV2:
        raise WorldAfterstateV2ContinuationError("population material type drift")
    try:
        material.validate()
    except Exception as exc:
        raise WorldAfterstateV2ContinuationError(
            "population material validation drift") from exc
    state = material.state
    points = material.prestate.get("public", {}).get("attacker_points")
    points_bucket = _point_bucket(points)
    identities = {replica: _identity(material, replica) for replica in REPLICATES}
    continuation_hashes = {replica: _sha(identity)
                           for replica, identity in identities.items()}
    rows: list[ContinuationOutcomeV2] = []
    receipts: list[RawLabelReceiptV2] = []
    for candidate_index, raw_audit in enumerate(material.private_audit_raws):
        audit = _audit(raw_audit)
        if audit.get("successor_sha256") != material.candidates[candidate_index].successor_sha256:
            raise WorldAfterstateV2ContinuationError(
                "audit/candidate successor binding drift")
        for replica in REPLICATES:
            identity = identities[replica]
            try:
                label = run_afterstate_continuation(
                    audit, identity, policy_name=V2_CONTINUATION_POLICY)
                raw_label = canonical_json_bytes(label)
                _validate_stored_label(
                    audit, label, identity,
                    expected_successor=audit["successor_sha256"],
                    expected_continuation_policy=V2_CONTINUATION_POLICY)
            except Exception as exc:
                raise WorldAfterstateV2ContinuationError(
                    "engine continuation run/stored verification failed") from exc
            outcome = label.get("outcome")
            if type(outcome) is not dict:
                raise WorldAfterstateV2ContinuationError("continuation outcome drift")
            try:
                validate_outcome(outcome)
            except WorldAfterstateError as exc:
                raise WorldAfterstateV2ContinuationError(
                    "continuation outcome mechanics drift") from exc
            category = outcome.get("signed_level_category")
            try:
                category_signed_level(category)
            except WorldAfterstateError as exc:
                raise WorldAfterstateV2ContinuationError(
                    "continuation category drift") from exc
            if outcome.get("root_is_attacker") != (
                    audit.get("root_seat") is not None and
                    reopen_afterstate_audit(audit).is_attacker(audit["root_seat"])):
                raise WorldAfterstateV2ContinuationError(
                    "continuation perspective mismatch")
            receipt = RawLabelReceiptV2(
                candidate_index=candidate_index, replica=replica,
                continuation_sha256=continuation_hashes[replica],
                raw=raw_label, raw_sha256=_sha_bytes(raw_label))
            receipt.validate()
            receipts.append(receipt)
            rows.append(ContinuationOutcomeV2(
                deal_sha256=state.deal_sha256, slot_sha256=state.slot_sha256,
                state_sha256=state.state_sha256,
                candidate_set_sha256=material.candidate_set_sha256,
                source=state.source, split=state.split, role=state.role,
                phase=state.phase, position=state.position,
                trump_rank=state.trump_rank, trump_mode=state.trump_mode,
                points_bucket=points_bucket, candidate_index=candidate_index,
                protected_incumbent=candidate_index == 0,
                successor_sha256=material.candidates[candidate_index].successor_sha256,
                continuation_sha256=continuation_hashes[replica],
                replica=replica, signed_level_category=int(category)))
    candidate_rows = tuple(rows)
    label_rows = tuple(receipts)
    body = {
        "schema": SCHEMA,
        "deal_sha256": state.deal_sha256,
        "slot_sha256": state.slot_sha256,
        "state_sha256": state.state_sha256,
        "candidate_set_sha256": material.candidate_set_sha256,
        "candidates": [row.__dict__ for row in candidate_rows],
        "labels": [
            {"schema": receipt.schema, "candidate_index": receipt.candidate_index,
             "replica": receipt.replica,
             "continuation_sha256": receipt.continuation_sha256,
             "raw": json.loads(receipt.raw.decode("ascii")),
             "raw_sha256": receipt.raw_sha256}
            for receipt in label_rows
        ],
        "authority": dict(AUTHORITY),
    }
    canonical = canonical_json_bytes(body)
    bundle = ContinuationBundleV2(
        deal_sha256=state.deal_sha256, slot_sha256=state.slot_sha256,
        state_sha256=state.state_sha256,
        candidate_set_sha256=material.candidate_set_sha256,
        candidates=candidate_rows, labels=label_rows,
        canonical_bytes=canonical, bundle_sha256=_sha_bytes(canonical))
    bundle.validate()
    return bundle


def run_continuation_capacity_probe_v2(
        material: PopulationMaterialV2) -> str:
    """Run one real, outcome-discarded continuation for worker scaling."""
    if type(material) is not PopulationMaterialV2:
        raise WorldAfterstateV2ContinuationError(
            "capacity probe material type drift")
    try:
        material.validate()
        audit = _audit(material.private_audit_raws[0])
        identity = _identity(material, REPLICATES[0])
        label = run_afterstate_continuation(
            audit, identity, policy_name=V2_CONTINUATION_POLICY)
        _validate_stored_label(
            audit, label, identity,
            expected_successor=audit["successor_sha256"],
            expected_continuation_policy=V2_CONTINUATION_POLICY)
    except Exception as exc:
        raise WorldAfterstateV2ContinuationError(
            "capacity continuation run/reopen failed") from exc
    raw = canonical_json_bytes(label)
    try:
        validate_outcome(label["outcome"])
    except (KeyError, WorldAfterstateError) as exc:
        raise WorldAfterstateV2ContinuationError(
            "capacity continuation outcome drift") from exc
    return _sha_bytes(raw)


def validate_continuation_bundle_v2(value: ContinuationBundleV2) -> None:
    if type(value) is not ContinuationBundleV2:
        raise WorldAfterstateV2ContinuationError("bundle type drift")
    value.validate()


def reopen_continuation_bundle_v2(
        value: ContinuationBundleV2 | bytes, material: PopulationMaterialV2) \
        -> ContinuationBundleV2:
    """Reopen immutable rows without repeating expensive continuations."""
    raw = value.canonical_bytes if isinstance(value, ContinuationBundleV2) \
        else value
    if type(raw) is not bytes:
        raise WorldAfterstateV2ContinuationError("bundle raw bytes drift")
    try:
        payload = json.loads(raw.decode("ascii"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise WorldAfterstateV2ContinuationError(
            "bundle raw JSON drift") from exc
    if type(payload) is not dict or canonical_json_bytes(payload) != raw \
            or set(payload) != {"schema", "deal_sha256", "slot_sha256",
                                "state_sha256", "candidate_set_sha256",
                                "candidates", "labels", "authority"}:
        raise WorldAfterstateV2ContinuationError("bundle raw schema drift")
    try:
        candidates = tuple(ContinuationOutcomeV2(**row)
                           for row in payload["candidates"])
        labels = tuple(RawLabelReceiptV2(
            schema=row["schema"], candidate_index=row["candidate_index"],
            replica=row["replica"],
            continuation_sha256=row["continuation_sha256"],
            raw=canonical_json_bytes(row["raw"]),
            raw_sha256=row["raw_sha256"])
                       for row in payload["labels"])
        reopened = ContinuationBundleV2(
            deal_sha256=payload["deal_sha256"],
            slot_sha256=payload["slot_sha256"],
            state_sha256=payload["state_sha256"],
            candidate_set_sha256=payload["candidate_set_sha256"],
            candidates=candidates, labels=labels, canonical_bytes=raw,
            bundle_sha256=_sha_bytes(raw), schema=payload["schema"],
            authority=payload["authority"])
        reopened.validate()
        material.validate()
    except (KeyError, TypeError, ValueError) as exc:
        raise WorldAfterstateV2ContinuationError(
            "bundle typed reconstruction drift") from exc
    state = material.state
    if (reopened.deal_sha256, reopened.slot_sha256,
            reopened.state_sha256, reopened.candidate_set_sha256) != (
                state.deal_sha256, state.slot_sha256, state.state_sha256,
                material.candidate_set_sha256):
        raise WorldAfterstateV2ContinuationError(
            "bundle population material binding drift")
    candidate_count = len(material.candidates)
    if len(reopened.candidates) != candidate_count * len(REPLICATES):
        raise WorldAfterstateV2ContinuationError(
            "bundle material candidate population drift")
    expected_row_identity = (
        state.deal_sha256, state.slot_sha256, state.state_sha256,
        state.source, state.split, state.role, state.phase, state.position,
        state.trump_rank, state.trump_mode,
        _point_bucket(material.prestate.get("public", {}).get(
            "attacker_points")))
    if any((row.deal_sha256, row.slot_sha256, row.state_sha256,
            row.source, row.split, row.role, row.phase, row.position,
            row.trump_rank, row.trump_mode, row.points_bucket)
           != expected_row_identity for row in reopened.candidates):
        raise WorldAfterstateV2ContinuationError(
            "bundle material row identity drift")
    by_label = {(row.candidate_index, row.replica): row
                for row in reopened.labels}
    by_outcome = {(row.candidate_index, row.replica): row
                  for row in reopened.candidates}
    for candidate_index, (candidate, audit_raw) in enumerate(zip(
            material.candidates, material.private_audit_raws, strict=True)):
        audit = _audit(audit_raw)
        for replica in REPLICATES:
            receipt = by_label[(candidate_index, replica)]
            outcome_row = by_outcome[(candidate_index, replica)]
            label = json.loads(receipt.raw.decode("ascii"))
            identity = _identity_from_fields(
                reopened.state_sha256, material.state.split, replica)
            try:
                _validate_stored_label(
                    audit, label, identity,
                    expected_successor=candidate.successor_sha256,
                    expected_continuation_policy=V2_CONTINUATION_POLICY)
            except Exception as exc:
                raise WorldAfterstateV2ContinuationError(
                    "sealed continuation stored-result drift") from exc
            if (label.get("successor_sha256") != candidate.successor_sha256
                    or outcome_row.successor_sha256 !=
                    candidate.successor_sha256):
                raise WorldAfterstateV2ContinuationError(
                    "sealed continuation material binding drift")
    return reopened


# Descriptive aliases keep the source layer discoverable to pipeline callers.
build_continuation_outcomes_v2 = build_continuation_bundle_v2
materialize_continuation_v2 = build_continuation_bundle_v2
reopen_continuation_v2 = reopen_continuation_bundle_v2
validate_continuation_v2 = validate_continuation_bundle_v2


__all__ = [
    "AUTHORITY", "IDENTITY_EXPERIMENT", "RECEIPT_SCHEMA", "REPLICATES",
    "SCHEMA", "ContinuationBundleV2", "RawLabelReceiptV2",
    "WorldAfterstateV2ContinuationError", "build_continuation_bundle_v2",
    "build_continuation_outcomes_v2", "materialize_continuation_v2",
    "reopen_continuation_bundle_v2", "reopen_continuation_v2",
    "run_continuation_capacity_probe_v2",
    "validate_continuation_bundle_v2", "validate_continuation_v2",
]
