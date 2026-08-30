"""Engine-derived mechanics witnesses for the Value-Afterstate V2 P0 gate.

The public label builder intentionally accepts arbitrary digest pairs.  This
adapter is the closed source boundary for that API: all pairs are derived from
the retained population material and continuation bundle, so callers cannot
assert mechanics observations or expectations themselves.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping, Sequence

from .belief_contract import canonical_json_bytes
from .world_afterstate import (
    WorldAfterstateError,
    build_afterstate_tensors,
    build_outcome,
    build_root_rotated_afterstate_tensors,
    canonical_successor,
    reopen_afterstate_audit,
    validate_outcome,
)
from .world_afterstate_label import (
    run_afterstate_continuation,
)
from .world_afterstate_v2_continuation import (
    ContinuationBundleV2,
    RawLabelReceiptV2,
)
from .world_afterstate_v2_label import (
    ContinuationOutcomeV2,
    build_p0_mechanics_evidence,
)
from .world_afterstate_v2_population import PopulationMaterialV2


MECHANICS_SURFACES = ("transition", "continuation", "perspective", "symmetry")
REPLICATES = tuple(range(8))


class WorldAfterstateV2P0MechanicsError(ValueError):
    """A retained P0 material or engine witness could not be reconstructed."""


def _sha(value: object) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _digest(value: object, label: str) -> str:
    if type(value) is not str or len(value) != 64 \
            or any(char not in "0123456789abcdef" for char in value):
        raise WorldAfterstateV2P0MechanicsError(f"{label} drift")
    return value


def _sequence(value: object, label: str) -> tuple[Any, ...]:
    if type(value) not in (tuple, list) or not value:
        raise WorldAfterstateV2P0MechanicsError(f"{label} population drift")
    return tuple(value)


def _bound_digest(surface: str, case: Mapping[str, Any], value: object) -> str:
    """Hash a witness with its surface and case identity in the hash body."""
    if surface not in MECHANICS_SURFACES or type(case) is not dict:
        raise WorldAfterstateV2P0MechanicsError("mechanics case identity drift")
    return _sha({
        "schema": "world-afterstate-v2-p0-mechanics-witness-v1",
        "surface": surface,
        "case": case,
        "value": value,
    })


def _tensor_fingerprint(tensors: Any) -> str:
    """Canonical fingerprint shared by the base and rotated tensor witnesses."""
    try:
        tensors.validate()
        body = {
            "public_shape": list(tensors.public.shape),
            "public_sha256": _sha_bytes(tensors.public.tobytes(order="C")),
            "history_shape": list(tensors.history.shape),
            "history_sha256": _sha_bytes(tensors.history.tobytes(order="C")),
            "world_shape": list(tensors.world.shape),
            "world_sha256": _sha_bytes(tensors.world.tobytes(order="C")),
            "perspective_shape": list(tensors.perspective.shape),
            "perspective_sha256": _sha_bytes(
                tensors.perspective.tobytes(order="C")),
        }
    except Exception as exc:
        raise WorldAfterstateV2P0MechanicsError(
            "mechanics tensor reconstruction failed") from exc
    return _sha(body)


def _audit(raw: bytes) -> dict[str, Any]:
    if type(raw) is not bytes:
        raise WorldAfterstateV2P0MechanicsError("mechanics audit bytes drift")
    try:
        value = json.loads(raw.decode("ascii"))
        if type(value) is not dict or canonical_json_bytes(value) != raw:
            raise ValueError("non-canonical audit")
        reopen_afterstate_audit(value)
    except WorldAfterstateV2P0MechanicsError:
        raise
    except Exception as exc:
        raise WorldAfterstateV2P0MechanicsError(
            "mechanics audit reopen failed") from exc
    return value


def _validate_pair(material: PopulationMaterialV2,
                   bundle: ContinuationBundleV2) -> None:
    """Require one exact bundle for one exact material, including each row."""
    if type(material) is not PopulationMaterialV2 \
            or type(bundle) is not ContinuationBundleV2:
        raise WorldAfterstateV2P0MechanicsError("material/bundle type drift")
    try:
        material.validate()
        bundle.validate()
    except Exception as exc:
        raise WorldAfterstateV2P0MechanicsError(
            "material or bundle seal refused") from exc
    state = material.state
    if (bundle.deal_sha256, bundle.slot_sha256, bundle.state_sha256,
            bundle.candidate_set_sha256) != (
                state.deal_sha256, state.slot_sha256, state.state_sha256,
                material.candidate_set_sha256):
        raise WorldAfterstateV2P0MechanicsError(
            "material/bundle state binding drift")
    expected_count = len(material.candidates) * len(REPLICATES)
    if len(bundle.candidates) != expected_count \
            or len(bundle.labels) != expected_count:
        raise WorldAfterstateV2P0MechanicsError(
            "material/bundle candidate population drift")
    outcomes: dict[tuple[int, int], ContinuationOutcomeV2] = {}
    for row in bundle.candidates:
        if type(row) is not ContinuationOutcomeV2:
            raise WorldAfterstateV2P0MechanicsError("bundle outcome type drift")
        key = (row.candidate_index, row.replica)
        if key in outcomes:
            raise WorldAfterstateV2P0MechanicsError("bundle outcome duplicate")
        outcomes[key] = row
        candidate = material.candidates[row.candidate_index] \
            if row.candidate_index < len(material.candidates) else None
        if candidate is None or row.successor_sha256 != candidate.successor_sha256 \
                or row.protected_incumbent != (row.candidate_index == 0):
            raise WorldAfterstateV2P0MechanicsError(
                "material/bundle candidate binding drift")
        if (row.deal_sha256, row.slot_sha256, row.state_sha256,
            row.candidate_set_sha256, row.source, row.split, row.role,
                row.phase, row.position, row.trump_rank, row.trump_mode) != (
                    state.deal_sha256, state.slot_sha256, state.state_sha256,
                    material.candidate_set_sha256, state.source, state.split,
                    state.role, state.phase, state.position, state.trump_rank,
                    state.trump_mode):
            raise WorldAfterstateV2P0MechanicsError(
                "material/bundle outcome identity drift")
    expected_keys = {(index, replica)
                     for index in range(len(material.candidates))
                     for replica in REPLICATES}
    if set(outcomes) != expected_keys:
        raise WorldAfterstateV2P0MechanicsError(
            "material/bundle candidate rows are not one-to-one")
    receipts: dict[tuple[int, int], RawLabelReceiptV2] = {}
    for receipt in bundle.labels:
        if type(receipt) is not RawLabelReceiptV2:
            raise WorldAfterstateV2P0MechanicsError("bundle receipt type drift")
        key = (receipt.candidate_index, receipt.replica)
        if key in receipts or key not in expected_keys:
            raise WorldAfterstateV2P0MechanicsError("bundle receipt duplicate")
        receipts[key] = receipt
        if receipt.continuation_sha256 != outcomes[key].continuation_sha256:
            raise WorldAfterstateV2P0MechanicsError(
                "material/bundle continuation identity drift")
    if set(receipts) != expected_keys:
        raise WorldAfterstateV2P0MechanicsError(
            "material/bundle receipts are not one-to-one")


def _ordered_pairs(materials: object, bundles: object) \
        -> tuple[tuple[PopulationMaterialV2, ContinuationBundleV2], ...]:
    material_rows = _sequence(materials, "material")
    bundle_rows = _sequence(bundles, "bundle")
    if len(material_rows) != len(bundle_rows):
        raise WorldAfterstateV2P0MechanicsError(
            "material/bundle population mismatch")
    typed_materials: list[PopulationMaterialV2] = []
    typed_bundles: list[ContinuationBundleV2] = []
    for material in material_rows:
        if type(material) is not PopulationMaterialV2:
            raise WorldAfterstateV2P0MechanicsError("material type drift")
        typed_materials.append(material)
    for bundle in bundle_rows:
        if type(bundle) is not ContinuationBundleV2:
            raise WorldAfterstateV2P0MechanicsError("bundle type drift")
        typed_bundles.append(bundle)
    if len({material.state_sha256 for material in typed_materials}) != len(typed_materials):
        raise WorldAfterstateV2P0MechanicsError("duplicate material state")
    if len({bundle.state_sha256 for bundle in typed_bundles}) != len(typed_bundles):
        raise WorldAfterstateV2P0MechanicsError("duplicate bundle state")
    by_state = {bundle.state_sha256: bundle for bundle in typed_bundles}
    result = []
    for material in sorted(typed_materials, key=lambda item: item.state_sha256):
        bundle = by_state.get(material.state_sha256)
        if bundle is None:
            raise WorldAfterstateV2P0MechanicsError(
                "material/bundle state population is not one-to-one")
        _validate_pair(material, bundle)
        result.append((material, bundle))
    return tuple(result)


def _checks(materials: object, bundles: object) \
        -> dict[str, tuple[tuple[str, str], ...]]:
    pairs = _ordered_pairs(materials, bundles)
    rows: dict[str, list[tuple[str, str]]] = {
        surface: [] for surface in MECHANICS_SURFACES}
    for material, bundle in pairs:
        state = material.state
        audits = tuple(_audit(raw) for raw in material.private_audit_raws)
        outcomes = {(row.candidate_index, row.replica): row
                    for row in bundle.candidates}
        receipts = {(row.candidate_index, row.replica): row
                    for row in bundle.labels}
        for candidate_index, audit in enumerate(audits):
            candidate = material.candidates[candidate_index]
            if audit.get("successor_sha256") != candidate.successor_sha256:
                raise WorldAfterstateV2P0MechanicsError(
                    "material audit/candidate successor binding drift")
            case = {"state_sha256": state.state_sha256,
                    "candidate_index": candidate_index}
            try:
                reopened = reopen_afterstate_audit(audit)
                expected_successor = canonical_successor(
                    reopened, audit["root_seat"])
            except Exception as exc:
                raise WorldAfterstateV2P0MechanicsError(
                    "mechanics successor reconstruction failed") from exc
            observed_value = _digest(candidate.successor_sha256,
                                     "sealed successor SHA-256")
            expected_value = _sha(expected_successor)
            rows["transition"].append((
                _bound_digest("transition", case, observed_value),
                _bound_digest("transition", case, expected_value)))

            try:
                base = _tensor_fingerprint(build_afterstate_tensors(audit))
            except Exception as exc:
                if isinstance(exc, WorldAfterstateV2P0MechanicsError):
                    raise
                raise WorldAfterstateV2P0MechanicsError(
                    "mechanics base tensor reconstruction failed") from exc
            for offset in (1, 2, 3):
                symmetry_case = {**case, "offset": offset}
                try:
                    rotated = _tensor_fingerprint(
                        build_root_rotated_afterstate_tensors(audit, offset))
                except Exception as exc:
                    raise WorldAfterstateV2P0MechanicsError(
                        "mechanics rotation reconstruction failed") from exc
                rows["symmetry"].append((
                    _bound_digest("symmetry", symmetry_case, base),
                    _bound_digest("symmetry", symmetry_case, rotated)))

            for replica in REPLICATES:
                row = outcomes[(candidate_index, replica)]
                receipt = receipts[(candidate_index, replica)]
                try:
                    sealed_label = json.loads(receipt.raw.decode("ascii"))
                    sealed_outcome = sealed_label["outcome"]
                    validate_outcome(sealed_outcome)
                    root_is_attacker = reopened.is_attacker(audit["root_seat"])
                    # The final attacker score is an outcome label, not a
                    # property of the immediate successor.  Re-derive only
                    # the mechanically checkable perspective/category mapping
                    # while retaining the sealed terminal score.  Using
                    # reopened.attacker_points here would compare a partial
                    # game score with the completed continuation outcome and
                    # reject every ordinary nonterminal afterstate.
                    rebuilt_outcome = build_outcome(
                        audit["successor_sha256"],
                        sealed_outcome["attacker_points"], root_is_attacker)
                except Exception as exc:
                    raise WorldAfterstateV2P0MechanicsError(
                        "mechanics perspective reconstruction failed") from exc
                perspective_case = {**case, "replica": replica}
                rows["perspective"].append((
                    _bound_digest("perspective", perspective_case,
                                  sealed_outcome),
                    _bound_digest("perspective", perspective_case,
                                  rebuilt_outcome)))

        # This is intentionally fixed and not a caller-selected integrity
        # dose.  It is the sole expensive continuation rerun at this boundary.
        fixed_key = (0, 0)
        fixed_audit = audits[0]
        fixed_receipt = receipts[fixed_key]
        try:
            sealed_identity = json.loads(
                fixed_receipt.raw.decode("ascii"))["continuation_identity"]
            rerun = run_afterstate_continuation(fixed_audit, sealed_identity)
            sealed_hash = _sha(json.loads(fixed_receipt.raw.decode("ascii")))
            rerun_hash = _sha(rerun)
        except Exception as exc:
            raise WorldAfterstateV2P0MechanicsError(
                "fixed continuation rerun failed") from exc
        continuation_case = {"state_sha256": state.state_sha256,
                            "candidate_index": 0, "replica": 0}
        rows["continuation"].append((
            _bound_digest("continuation", continuation_case, sealed_hash),
            _bound_digest("continuation", continuation_case, rerun_hash)))

    # The label builder sorts rows itself, but sorting here makes the derived
    # mapping deterministic and independently canonical for direct consumers.
    return {surface: tuple(sorted(values))
            for surface, values in rows.items()}


def derive_p0_engine_mechanics_checks(
        materials: Sequence[PopulationMaterialV2],
        bundles: Sequence[ContinuationBundleV2]) \
        -> dict[str, tuple[tuple[str, str], ...]]:
    """Derive all four P0 mechanics surfaces from sealed engine artifacts."""
    try:
        return _checks(materials, bundles)
    except WorldAfterstateV2P0MechanicsError:
        raise
    except Exception as exc:
        raise WorldAfterstateV2P0MechanicsError(
            "P0 mechanics derivation failed") from exc


def build_engine_p0_mechanics_evidence(
        outcomes: Sequence[ContinuationOutcomeV2], *,
        required_slots: Mapping[str, Any], natural_fit_population: Sequence[Any],
        tier: Any, materials: Sequence[PopulationMaterialV2],
        bundles: Sequence[ContinuationBundleV2]) -> dict[str, Any]:
    """Build ordinary P0 evidence using only engine-derived check pairs."""
    checks = derive_p0_engine_mechanics_checks(materials, bundles)
    try:
        return build_p0_mechanics_evidence(
            outcomes, required_slots=required_slots,
            natural_fit_population=natural_fit_population, tier=tier,
            checks=checks)
    except Exception as exc:
        if isinstance(exc, WorldAfterstateV2P0MechanicsError):
            raise
        raise WorldAfterstateV2P0MechanicsError(
            "P0 mechanics evidence construction failed") from exc


__all__ = [
    "WorldAfterstateV2P0MechanicsError",
    "derive_p0_engine_mechanics_checks",
    "build_engine_p0_mechanics_evidence",
]
