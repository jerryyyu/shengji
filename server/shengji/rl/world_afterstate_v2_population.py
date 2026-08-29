"""Outcome-blind Value-Afterstate V2 population materialization.

This is deliberately a bridge, not a driver.  A caller supplies one exact
attempt identity and a seed-free, complete-world play snapshot.  The engine
then derives the state stratum and constructs the immutable candidate ballot.
No terminal result, continuation, label, or model-facing proposal metadata is
accepted or emitted.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from ..ai.registry import make_bot
from .belief_contract import canonical_json_bytes
from .world_afterstate import (
    WorldAfterstateError, build_afterstate_audit_from_snapshot, canonical_successor,
    replay_canonical_successor, reopen_afterstate_audit,
)
from .world_afterstate_v2_protocol import (
    ATTEMPT_SCHEMA, PopulationSlotV2, StateCandidateV2,
    WorldAfterstateV2ProtocolError, select_one_state_per_deal,
)
from .actions import enumerate_actions
from .world_afterstate_sources import (
    PRODUCTION_BALLOT_POLICY, production_ballot_identity_from_snapshot,
)


SCHEMA = "world-afterstate-v2-population-material-v1"
CANDIDATE_SCHEMA = "world-afterstate-v2-population-candidate-v1"
MATERIAL_SCHEMA = SCHEMA
FORBIDDEN_TOKENS = (
    "outcome", "utility", "prediction", "continuation", "label",
    "terminal_outcome", "signed_level", "raw_seed", "gameplay",
)


class WorldAfterstateV2PopulationError(ValueError):
    """A V2 attempted deal, snapshot, ballot, or material binding drifted."""


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _digest(value: object, label: str) -> str:
    if type(value) is not str or len(value) != 64 or any(
            char not in "0123456789abcdef" for char in value):
        raise WorldAfterstateV2PopulationError(f"{label} drift")
    return value


def _action_key(action: Sequence[str]) -> tuple[str, ...]:
    return tuple(sorted(action))


def _candidate_set_sha256(state_sha256: str,
                          successors: Sequence[str]) -> str:
    """Exactly the candidate-set digest used by the V2 label contract."""
    _digest(state_sha256, "candidate-set state SHA-256")
    if type(successors) not in (list, tuple) or len(successors) < 2:
        raise WorldAfterstateV2PopulationError("candidate-set population drift")
    if any(type(value) is not str or len(value) != 64 or any(
            char not in "0123456789abcdef" for char in value)
           for value in successors) or len(set(successors)) != len(successors):
        raise WorldAfterstateV2PopulationError("candidate-set successor drift")
    return _sha({"schema": "world-afterstate-v2-candidate-set-v1",
                 "state_sha256": state_sha256,
                 "successor_sha256s": list(successors)})


def _seed_for_deal(deal_sha256: str) -> int:
    # This is a derived policy stream identity, not an input or a persisted
    # seed.  The closed material schema intentionally never contains it.
    return int.from_bytes(hashlib.sha256(canonical_json_bytes({
        "namespace": "world-afterstate-v2-production-ballot-v1",
        "deal_sha256": deal_sha256,
    })).digest()[:8], "big") & ((1 << 63) - 1)


def _production_ballot_with_incumbent(
        snapshot: Mapping[str, Any], rnd: Any, *, policy_seed: int) \
        -> tuple[tuple[str, ...], ...]:
    """Return the complete ballot with the actual production play first.

    ``MCBot._candidates`` puts its heuristic prior first, but production may
    override that prior after search.  V2's protected incumbent and action-
    usefulness estimand are the action production would play, not merely the
    first proposal supplied to production search.
    """
    _identity, ballot, _digest_value = production_ballot_identity_from_snapshot(
        snapshot, policy_seed=policy_seed)
    policy = make_bot(PRODUCTION_BALLOT_POLICY, seed=policy_seed)
    try:
        incumbent = _action_key(policy.decide_play(copy.deepcopy(rnd), 0))
    except Exception as exc:
        raise WorldAfterstateV2PopulationError(
            "production incumbent derivation drift") from exc
    keys = tuple(_action_key(action) for action in ballot)
    if incumbent not in keys or len(set(keys)) != len(keys):
        raise WorldAfterstateV2PopulationError(
            "production incumbent/ballot binding drift")
    return (incumbent, *(action for action in keys if action != incumbent))


def _validate_attempt(value: Mapping[str, Any], slot: PopulationSlotV2) -> str:
    if type(value) is not dict or set(value) != {
            "schema", "population_namespace_sha256", "slot_sha256",
            "attempt_index", "deal_sha256", "engine_seed"} \
            or value.get("schema") != ATTEMPT_SCHEMA:
        raise WorldAfterstateV2PopulationError("attempt identity schema drift")
    slot.validate()
    namespace = _digest(value["population_namespace_sha256"],
                        "population namespace SHA-256")
    _digest(value["deal_sha256"], "attempted deal SHA-256")
    if value["slot_sha256"] != slot.slot_sha256:
        raise WorldAfterstateV2PopulationError("attempt slot binding drift")
    index = value["attempt_index"]
    if isinstance(index, bool) or not isinstance(index, int) or index < 0:
        raise WorldAfterstateV2PopulationError("attempt index drift")
    body = {"schema": ATTEMPT_SCHEMA,
            "population_namespace_sha256": namespace,
            "slot_sha256": slot.slot_sha256, "attempt_index": index}
    expected = hashlib.sha256(canonical_json_bytes(body)).hexdigest()
    if value["deal_sha256"] != expected:
        raise WorldAfterstateV2PopulationError("attempt deal derivation drift")
    # engine_seed is checked only as the attempted-deal helper's derivation;
    # it is never copied into the closed material contract.
    if (isinstance(value["engine_seed"], bool)
            or not isinstance(value["engine_seed"], int)
            or not 0 <= value["engine_seed"] < 2**63
            or value["engine_seed"] != int(expected[:16], 16) & ((1 << 63) - 1)):
        raise WorldAfterstateV2PopulationError("attempt engine identity drift")
    return expected


def _stratum(rnd: Any, candidate_count: int) -> tuple[str, str, str, str,
                                                        str, tuple[str, ...]]:
    if rnd.phase != "play" or rnd.trick is None or rnd.turn != 0:
        raise WorldAfterstateV2PopulationError("snapshot is not a root play state")
    phase = "early" if len(rnd.history) < 6 else (
        "middle" if len(rnd.history) < 14 else "late")
    position = "lead" if not rnd.trick.plays else "follow"
    role = "attacker" if rnd.is_attacker(0) else "defender"
    mode = "NT" if rnd.trump_is_nt else rnd.trump_suit
    if mode not in ("S", "H", "D", "C", "NT"):
        raise WorldAfterstateV2PopulationError("snapshot trump mode drift")
    surfaces: list[str] = []
    # These surfaces are pure mechanics witnesses.  They are recomputed from
    # the engine state and final ballot, never accepted as caller claims.
    if candidate_count and candidate_count >= 8:
        surfaces.append("wide-ballot")
    if phase == "late" and rnd.attacker_points >= 120:
        surfaces.append("late/high-point")
    return (phase, position, role, rnd.trump_rank, mode, tuple(surfaces))


@dataclass(frozen=True)
class PopulationCandidateV2:
    """Public candidate identity; the action itself remains private audit data."""

    candidate_index: int
    action_sha256: str
    audit_sha256: str
    successor_sha256: str
    origin: str
    protected_incumbent: bool
    schema: str = CANDIDATE_SCHEMA

    def validate(self) -> None:
        if self.schema != CANDIDATE_SCHEMA:
            raise WorldAfterstateV2PopulationError("candidate schema drift")
        if isinstance(self.candidate_index, bool) or not isinstance(
                self.candidate_index, int) or self.candidate_index < 0:
            raise WorldAfterstateV2PopulationError("candidate index drift")
        _digest(self.action_sha256, "candidate action SHA-256")
        _digest(self.audit_sha256, "candidate audit SHA-256")
        _digest(self.successor_sha256, "candidate successor SHA-256")
        if self.origin not in ("production-ballot", "legal-tail", "played-action"):
            raise WorldAfterstateV2PopulationError("candidate origin drift")
        if type(self.protected_incumbent) is not bool \
                or self.protected_incumbent != (self.candidate_index == 0):
            raise WorldAfterstateV2PopulationError("candidate incumbent drift")


@dataclass(frozen=True)
class PopulationMaterialV2:
    """One state candidate plus canonical private audit bytes for its ballot."""

    state: StateCandidateV2
    candidate_set_sha256: str
    candidates: tuple[PopulationCandidateV2, ...]
    audit_raws: tuple[bytes, ...]
    prestate: dict[str, Any]
    schema: str = MATERIAL_SCHEMA

    def validate(self) -> None:
        if self.schema != MATERIAL_SCHEMA:
            raise WorldAfterstateV2PopulationError("material schema drift")
        self.state.validate()
        _digest(self.candidate_set_sha256, "candidate-set SHA-256")
        if type(self.candidates) is not tuple or len(self.candidates) < 2 \
                or type(self.audit_raws) is not tuple \
                or len(self.audit_raws) != len(self.candidates) \
                or type(self.prestate) is not dict:
            raise WorldAfterstateV2PopulationError("material population drift")
        for index, (candidate, raw) in enumerate(zip(self.candidates,
                                                       self.audit_raws)):
            candidate.validate()
            if candidate.candidate_index != index or type(raw) is not bytes:
                raise WorldAfterstateV2PopulationError("material candidate bytes drift")
            if hashlib.sha256(raw).hexdigest() != candidate.audit_sha256:
                raise WorldAfterstateV2PopulationError("material audit bytes drift")
            try:
                audit = json.loads(raw.decode("ascii"))
            except (UnicodeDecodeError, ValueError) as exc:
                raise WorldAfterstateV2PopulationError(
                    "material audit is not canonical JSON") from exc
            if type(audit) is not dict or canonical_json_bytes(audit) != raw \
                    or _sha(audit.get("attempted_action")) != candidate.action_sha256 \
                    or audit.get("successor_sha256") != candidate.successor_sha256:
                raise WorldAfterstateV2PopulationError("material candidate bytes drift")
            try:
                reopen_afterstate_audit(audit)
            except WorldAfterstateError as exc:
                raise WorldAfterstateV2PopulationError(
                    "material audit reconstruction drift") from exc
        if self.candidates[0].protected_incumbent is not True \
                or len({c.successor_sha256 for c in self.candidates}) != len(self.candidates):
            raise WorldAfterstateV2PopulationError("material successor drift")
        expected = _candidate_set_sha256(
            self.state.state_sha256,
            tuple(c.successor_sha256 for c in self.candidates))
        if expected != self.candidate_set_sha256:
            raise WorldAfterstateV2PopulationError("material candidate-set drift")
        if canonical_json_bytes(self.prestate) != canonical_json_bytes(
                json.loads(self.audit_raws[0].decode("ascii"))["prestate"]):
            raise WorldAfterstateV2PopulationError("material prestate drift")
        if _sha(self.prestate) != self.state.state_sha256:
            raise WorldAfterstateV2PopulationError("material state hash drift")
        for raw in self.audit_raws:
            audit = json.loads(raw.decode("ascii"))
            if audit.get("prestate_sha256") != self.state.state_sha256 \
                    or audit.get("root_seat") != 0:
                raise WorldAfterstateV2PopulationError(
                    "material audit state binding drift")

    @property
    def state_candidate(self) -> StateCandidateV2:
        return self.state

    @property
    def state_sha256(self) -> str:
        return self.state.state_sha256

    @property
    def deal_sha256(self) -> str:
        return self.state.deal_sha256

    @property
    def slot_sha256(self) -> str:
        return self.state.slot_sha256

    @property
    def successor_sha256s(self) -> tuple[str, ...]:
        return tuple(candidate.successor_sha256 for candidate in self.candidates)

    @property
    def private_audit_raws(self) -> tuple[bytes, ...]:
        return self.audit_raws


# Descriptive aliases used by callers that distinguish a candidate row from
# the complete (private-audit-bearing) material bundle.
StateMaterialV2 = PopulationMaterialV2
CandidateMaterialV2 = PopulationCandidateV2


def build_population_material_v2(
        deal_identity: Mapping[str, Any], slot: PopulationSlotV2,
        snapshot: Mapping[str, Any], *, played_action: Sequence[str] | None = None,
        source: str | None = None) -> PopulationMaterialV2:
    """Materialize one V2 state from an exact complete-world snapshot.

    ``source`` and ``played_action`` are proposal provenance only.  Source is
    checked against the assigned slot; all state fields are derived by replay.
    """
    deal = _validate_attempt(deal_identity, slot)
    if type(snapshot) is not dict:
        raise WorldAfterstateV2PopulationError("snapshot object drift")
    if source is not None and source != slot.source:
        raise WorldAfterstateV2PopulationError("source/slot binding drift")
    source = slot.source
    if source not in ("natural", "pt-sol", "pt-luna", "human", "mechanics"):
        raise WorldAfterstateV2PopulationError("source drift")
    try:
        rnd = replay_canonical_successor(copy.deepcopy(snapshot))
    except WorldAfterstateError as exc:
        raise WorldAfterstateV2PopulationError("snapshot replay drift") from exc
    if rnd.phase != "play" or rnd.turn != 0:
        raise WorldAfterstateV2PopulationError("snapshot is not a root decision")
    prestate = canonical_successor(rnd, 0)
    if canonical_json_bytes(prestate) != canonical_json_bytes(snapshot):
        raise WorldAfterstateV2PopulationError("snapshot canonical derivation drift")

    try:
        production = _production_ballot_with_incumbent(
            snapshot, rnd, policy_seed=_seed_for_deal(deal))
        legal = enumerate_actions(rnd, 0)
    except Exception as exc:
        raise WorldAfterstateV2PopulationError("production ballot derivation drift") from exc
    production_keys = {_action_key(a) for a in production}
    if not production or _action_key(production[0]) not in production_keys:
        raise WorldAfterstateV2PopulationError("production ballot is empty")
    # The legal tail is a single deterministic member from the reviewed,
    # bounded legal proposal pool.  No exhaustive action expansion occurs.
    outside = sorted({_action_key(a) for a in legal} - production_keys)
    tail = []
    if outside:
        tail = [list(min(outside, key=lambda key: _sha({
            "namespace": "world-afterstate-v2-legal-tail-v1",
            "state_sha256": _sha(prestate), "action": list(key)})))]
    actions = [list(a) for a in production] + tail
    origins = ["production-ballot"] * len(production) + \
        (["legal-tail"] if tail else [])
    external_source = source in ("pt-sol", "pt-luna", "human")
    if external_source != (played_action is not None):
        raise WorldAfterstateV2PopulationError(
            "source played-action presence drift")
    if external_source:
        assert played_action is not None
        played = sorted(played_action)
        if _action_key(played) not in {_action_key(a) for a in actions}:
            try:
                candidate_audit = build_afterstate_audit_from_snapshot(
                    snapshot, played)
            except WorldAfterstateError as exc:
                raise WorldAfterstateV2PopulationError(
                    "source played action is not legal") from exc
            if candidate_audit is None:  # defensive against contract drift
                raise WorldAfterstateV2PopulationError(
                    "source played action is not legal")
            actions.append(played)
            origins.append("played-action")
    if len(actions) < 2 or len({_action_key(a) for a in actions}) != len(actions):
        raise WorldAfterstateV2PopulationError("candidate ballot lacks comparison actions")
    audits = []
    for action in actions:
        try:
            audit = build_afterstate_audit_from_snapshot(snapshot, action)
        except WorldAfterstateError as exc:
            raise WorldAfterstateV2PopulationError("candidate action legality drift") from exc
        audits.append(audit)
    successor_shas = tuple(_sha(audit["successor"]) for audit in audits)
    if len(set(successor_shas)) != len(successor_shas):
        raise WorldAfterstateV2PopulationError("candidate successor collision")
    state_sha = _sha(prestate)
    phase, position, role, rank, mode, surfaces = _stratum(rnd, len(actions))
    # Mechanics multi-card is a state-derived witness and does not rely on a
    # proposal-origin claim.
    if any(len(action) > 1 for action in actions):
        surfaces = tuple([*surfaces, "multi-card"])
    surfaces = tuple(dict.fromkeys(surfaces))
    if slot.source == "mechanics":
        if slot.mechanics_surface not in surfaces:
            raise WorldAfterstateV2PopulationError("mechanics surface mismatch")
    elif slot.cell != (phase, position, role):
        raise WorldAfterstateV2PopulationError("state slot stratum mismatch")
    if slot.trump_rank != rank or slot.trump_mode != mode:
        raise WorldAfterstateV2PopulationError("state rank/mode mismatch")
    state = StateCandidateV2(
        deal_sha256=deal, slot_sha256=slot.slot_sha256, state_sha256=state_sha,
        source=slot.source, split=slot.split, phase=phase, position=position,
        role=role, trump_rank=rank, trump_mode=mode,
        mechanics_surfaces=surfaces, legal_candidate_count=len(actions))
    candidate_rows = []
    for index, (action, audit, origin) in enumerate(
            zip(actions, audits, origins, strict=True)):
        candidate_rows.append(PopulationCandidateV2(
            candidate_index=index, action_sha256=hashlib.sha256(
                canonical_json_bytes(audit["attempted_action"])).hexdigest(),
            audit_sha256=hashlib.sha256(
                canonical_json_bytes(audit)).hexdigest(),
            successor_sha256=successor_shas[index], origin=origin,
            protected_incumbent=index == 0))
    raws = tuple(canonical_json_bytes(audit) for audit in audits)
    # Candidate action hashes are intentionally hashes of canonical audit
    # action bytes, matching the private bytes retained below.
    material = PopulationMaterialV2(
        state=state,
        candidate_set_sha256=_candidate_set_sha256(state_sha, successor_shas),
        candidates=tuple(candidate_rows), audit_raws=raws,
        prestate=copy.deepcopy(prestate))
    material.validate()
    return material


# Short aliases make the bridge easy to discover without creating a second
# contract surface.
build_state_material_v2 = build_population_material_v2
materialize_state_v2 = build_population_material_v2


def select_one_material_per_deal(
        materials: Sequence[PopulationMaterialV2], *,
        required_slots: Mapping[str, PopulationSlotV2]) \
        -> tuple[PopulationMaterialV2, ...]:
    """Select canonical states and return their matching complete material."""
    if type(materials) not in (list, tuple) or not materials \
            or type(required_slots) is not dict or not required_slots:
        raise WorldAfterstateV2PopulationError("material selection request drift")
    by_state: dict[str, PopulationMaterialV2] = {}
    state_candidates: list[StateCandidateV2] = []
    for material in materials:
        if type(material) is not PopulationMaterialV2:
            raise WorldAfterstateV2PopulationError("material type drift")
        material.validate()
        if material.state.state_sha256 in by_state:
            raise WorldAfterstateV2PopulationError("duplicate material state")
        by_state[material.state.state_sha256] = material
        state_candidates.append(material.state)
    try:
        selected = select_one_state_per_deal(
            state_candidates, required_slots=required_slots)
    except WorldAfterstateV2ProtocolError as exc:
        raise WorldAfterstateV2PopulationError(str(exc)) from exc
    result = tuple(by_state[row.state_sha256] for row in selected)
    if len(result) != len(required_slots) or len({m.state.deal_sha256 for m in result}) != len(result):
        raise WorldAfterstateV2PopulationError("material selection population drift")
    return result


select_one_state_material_per_deal = select_one_material_per_deal
select_population_materials = select_one_material_per_deal
select_one_state_per_deal_with_material = select_one_material_per_deal


def validate_population_material_v2(value: PopulationMaterialV2) -> None:
    if type(value) is not PopulationMaterialV2:
        raise WorldAfterstateV2PopulationError("material type drift")
    value.validate()


__all__ = [
    "CANDIDATE_SCHEMA", "MATERIAL_SCHEMA", "PopulationCandidateV2",
    "CandidateMaterialV2", "PopulationMaterialV2", "StateMaterialV2",
    "WorldAfterstateV2PopulationError",
    "build_population_material_v2", "build_state_material_v2",
    "materialize_state_v2", "select_one_material_per_deal",
    "select_one_state_material_per_deal", "select_population_materials",
    "select_one_state_per_deal_with_material",
    "validate_population_material_v2",
]
