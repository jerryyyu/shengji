"""One-shot filesystem boundary for the Value-Afterstate V2 audit.

The pure :mod:`world_afterstate_v2_audit_derivation` function is intentionally
not a filesystem API.  This module supplies that missing boundary: all
target-free manifests and receipts are reopened before an exclusive
``terminal.partial`` slot is created, then (and only then) private audit and
continuation bytes are reopened.  A failed derivation permanently occupies
the slot.

The controller reopens every selected four-member checkpoint aggregate and
its six sealed prediction manifests.  It does not retrain models or recompute
predictions: those are already immutable scientific inputs, while immediate
independent reconstruction reopens and re-scores the same exact bytes.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import platform
import sys
from typing import Any, Mapping, Sequence

from .belief_artifacts import publish_exclusive_bytes, stable_read_bytes
from .belief_contract import canonical_json_bytes
from .world_afterstate_v2_audit_attempt import reopen_audit_attempt_bytes
from .world_afterstate_v2_artifacts import (
    AUTHORITY as ARTIFACT_AUTHORITY,
    CONTINUATION_MANIFEST_SCHEMA, checkpoint_manifest_path,
    reopen_checkpoint_manifest, reopen_continuation_manifest,
)
from .world_afterstate_v2_audit_derivation import (
    AUDIT_COHORTS, AuditDerivationInputV2, derive_audit_v2,
)
from .world_afterstate_v2_controls import validate_control_evidence
from .world_afterstate_v2_inference import (
    validate_prediction_population_manifest_v2,
)
from .world_afterstate_v2_population_artifacts import (
    AUTHORITY as POPULATION_AUTHORITY, reopen_population_audit_subset,
)
from .world_afterstate_v2_reopen import (
    reopen_evaluation_result_v2, reopen_jeffreys_prior_v2,
    reopen_model_selector_power_v2, reopen_optimizer_canary_v2,
)
from .world_afterstate_v2_result import (
    DECISIONS, WorldAfterstateV2TerminalEvidence,
    WorldAfterstateV2TerminalResult, derive_terminal_result,
)
from .world_afterstate_v2_terminal_provenance import (
    AUTHORITY, COHORT_LABELS, DOSE_LABELS, AuditProvenanceV2,
    IndependentReconstructionReceiptV2,
    validate_independent_reconstruction_v2,
)
from .world_afterstate_v2_training_controller import validate_cohort_manifest
from .world_afterstate_v2_label import validate_precision_label


ATTEMPT_NAME = "attempt.json"
PROVENANCE_NAME = "provenance.json"
RESULT_NAME = "terminal.json"
RECONSTRUCTION_NAME = "independent-reconstruction.json"
ATTEMPT_SCHEMA = "world-afterstate-v2-terminal-attempt-v1"
EARLY_ATTEMPT_SCHEMA = "world-afterstate-v2-early-terminal-attempt-v1"
EARLY_ROUTE_SCHEMA = "world-afterstate-v2-early-route-evidence-v1"
EARLY_STAGES = ("p0", "training", "precision-select")
EARLY_DECISIONS = DECISIONS[:7]
CONTROLLER_AUTHORITY = dict(AUTHORITY)


class WorldAfterstateV2TerminalControllerError(ValueError):
    """A V2 terminal input, filesystem slot, or reconstruction drifted."""


def _sha_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _sha(value: object) -> str:
    return _sha_bytes(canonical_json_bytes(value))


def _digest(value: object, label: str) -> str:
    if type(value) is not str or len(value) != 64 \
            or any(c not in "0123456789abcdef" for c in value):
        raise WorldAfterstateV2TerminalControllerError(f"{label} drift")
    return value


def _path(value: object, label: str) -> Path:
    if not isinstance(value, Path) or value.is_symlink():
        raise WorldAfterstateV2TerminalControllerError(f"{label} path drift")
    return value


def _strict_json(raw: bytes, label: str) -> dict[str, Any]:
    if type(raw) is not bytes or not raw:
        raise WorldAfterstateV2TerminalControllerError(f"{label} is empty")
    try:
        value = json.loads(raw.decode("ascii"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WorldAfterstateV2TerminalControllerError(
            f"{label} is not canonical JSON") from exc
    if type(value) is not dict or canonical_json_bytes(value) != raw:
        raise WorldAfterstateV2TerminalControllerError(
            f"{label} canonical bytes drift")
    return value


def _read_json(path: Path, label: str) -> tuple[dict[str, Any], bytes]:
    _path(path, label)
    try:
        raw = stable_read_bytes(path)
    except Exception as exc:
        raise WorldAfterstateV2TerminalControllerError(
            f"{label} stable read refused") from exc
    return _strict_json(raw, label), raw


def _ordered_paths(value: object, labels: tuple[str, ...], label: str) \
        -> tuple[tuple[str, Path], ...]:
    if type(value) is not tuple or len(value) != len(labels):
        raise WorldAfterstateV2TerminalControllerError(f"{label} population drift")
    result = []
    for row, expected in zip(value, labels, strict=True):
        if type(row) is not tuple or len(row) != 2 or row[0] != expected:
            raise WorldAfterstateV2TerminalControllerError(f"{label} order drift")
        result.append((expected, _path(row[1], f"{label} {expected}")))
    return tuple(result)


def build_early_route_evidence_bytes(
        *, freeze_sha256: str, admission_sha256: str, source_stage: str,
        resource_incomplete: bool = False,
        resource_cap_exceeded: bool = False,
        mechanics_failure: bool = False) -> bytes:
    """Build the target-free stage-status receipt consumed by early routing."""
    _digest(freeze_sha256, "early-route freeze SHA-256")
    _digest(admission_sha256, "early-route admission SHA-256")
    if source_stage not in EARLY_STAGES or any(type(value) is not bool for value in (
            resource_incomplete, resource_cap_exceeded, mechanics_failure)):
        raise WorldAfterstateV2TerminalControllerError(
            "early-route evidence field drift")
    body = {
        "schema": EARLY_ROUTE_SCHEMA,
        "freeze_sha256": freeze_sha256,
        "admission_sha256": admission_sha256,
        "source_stage": source_stage,
        "resource_incomplete": resource_incomplete,
        "resource_cap_exceeded": resource_cap_exceeded,
        "mechanics_failure": mechanics_failure,
        "audit_opened_count": 0,
        "authority": dict(CONTROLLER_AUTHORITY),
    }
    return canonical_json_bytes({**body, "evidence_sha256": _sha(body)})


@dataclass(frozen=True)
class EarlyTerminalInputPathsV2:
    """Closed receipt set for a pre-audit terminal route.

    Optional paths are permitted only because the first-match route can stop
    before those artifacts exist.  Their allowed population is rederived from
    ``source_stage`` and the pure terminal router; a caller cannot omit a
    required receipt and still obtain its requested route.
    """

    freeze_sha256: str
    admission_sha256: str
    expected_route: str
    route_evidence_path: Path
    p0_report_path: Path | None = None
    optimizer_canary_path: Path | None = None
    precision_select_result_path: Path | None = None
    model_selector_power_path: Path | None = None
    cohort_manifest_paths: tuple[tuple[str, Path], ...] = ()

    def validate_shape(self) -> None:
        _digest(self.freeze_sha256, "early terminal freeze SHA-256")
        _digest(self.admission_sha256, "early terminal admission SHA-256")
        if self.expected_route not in EARLY_DECISIONS:
            raise WorldAfterstateV2TerminalControllerError(
                "early terminal route drift")
        _path(self.route_evidence_path, "early route evidence")
        for value, label in (
                (self.p0_report_path, "early P0 report"),
                (self.optimizer_canary_path, "early optimizer canary"),
                (self.precision_select_result_path,
                 "early precision-select result"),
                (self.model_selector_power_path,
                 "early model-selector power")):
            if value is not None:
                _path(value, label)
        if type(self.cohort_manifest_paths) is not tuple \
                or len({label for label, _ in self.cohort_manifest_paths}) != len(
                    self.cohort_manifest_paths):
            raise WorldAfterstateV2TerminalControllerError(
                "early cohort manifest population drift")
        allowed = set(COHORT_LABELS)
        for row in self.cohort_manifest_paths:
            if type(row) is not tuple or len(row) != 2 or row[0] not in allowed:
                raise WorldAfterstateV2TerminalControllerError(
                    "early cohort manifest identity drift")
            _path(row[1], f"early cohort manifest {row[0]}")
        if tuple(label for label, _ in self.cohort_manifest_paths) != tuple(
                label for label in COHORT_LABELS
                if label in {row[0] for row in self.cohort_manifest_paths}):
            raise WorldAfterstateV2TerminalControllerError(
                "early cohort manifest order drift")


@dataclass(frozen=True)
class TerminalInputPathsV2:
    """Closed path/hash contract consumed by the terminal supervisor.

    Every ordered tuple is deliberately represented as ``(fixed-label,
    value)``.  A caller cannot silently drop or reorder one of the six
    scientific cohorts or three control-dose receipts.
    """

    freeze_sha256: str
    admission_sha256: str
    audit_population_root: Path
    audit_population_namespace_sha256: str
    audit_population_tier: str
    audit_attempt_path: Path
    continuation_root: Path
    prediction_manifest_paths: tuple[tuple[str, Path], ...]
    cohort_manifest_paths: tuple[tuple[str, Path], ...]
    checkpoint_roots: tuple[tuple[str, Path], ...]
    p0_report_path: Path
    optimizer_canary_path: Path
    precision_select_result_path: Path
    model_selector_power_path: Path
    prior_path: Path
    control_dose_receipt_paths: tuple[tuple[str, Path], ...]

    # Descriptive aliases make the contract convenient for integration code
    # without adding alternate mutable fields to its canonical shape.
    @property
    def population_manifest_root(self) -> Path:
        return self.audit_population_root

    @property
    def aggregate_continuation_root(self) -> Path:
        return self.continuation_root

    def validate_shape(self) -> None:
        for value, label in ((self.freeze_sha256, "external freeze SHA-256"),
                             (self.admission_sha256, "admission SHA-256"),
                             (self.audit_population_namespace_sha256,
                              "audit population namespace SHA-256")):
            _digest(value, label)
        for value, label in ((self.audit_population_root, "audit population"),
                             (self.audit_attempt_path, "audit attempt"),
                             (self.continuation_root, "continuation"),
                             (self.p0_report_path, "P0 report"),
                             (self.optimizer_canary_path, "optimizer canary"),
                             (self.precision_select_result_path,
                              "precision-select result"),
                             (self.model_selector_power_path,
                              "model-selector power"),
                             (self.prior_path, "Jeffreys prior")):
            _path(value, label)
        if type(self.audit_population_tier) is not str \
                or not self.audit_population_tier:
            raise WorldAfterstateV2TerminalControllerError(
                "audit population tier drift")
        _ordered_paths(self.prediction_manifest_paths, COHORT_LABELS,
                       "prediction manifest")
        _ordered_paths(self.cohort_manifest_paths, COHORT_LABELS,
                       "cohort manifest")
        _ordered_paths(self.checkpoint_roots, COHORT_LABELS,
                       "checkpoint root")
        _ordered_paths(self.control_dose_receipt_paths, DOSE_LABELS,
                       "control dose")


# The longer name reads naturally in callers and keeps old integration code
# from needing a compatibility import.
AuditTerminalInputV2 = TerminalInputPathsV2
WorldAfterstateV2TerminalInputs = TerminalInputPathsV2
TerminalInputV2 = TerminalInputPathsV2


def _preflight_population(root: Path, expected_freeze: str,
                          expected_namespace: str, expected_tier: str) \
        -> tuple[dict[str, Any], bytes]:
    """Read only the public population manifest before the audit slot opens."""
    _path(root, "audit population")
    path = root / "population" / "manifest.json"
    value, raw = _read_json(path, "audit population manifest")
    required = {"schema", "authority", "freeze_sha256",
                "population_namespace_sha256", "tier", "split", "source",
                "rows", "population_sha256", "manifest_sha256"}
    if set(value) != required or value["freeze_sha256"] != expected_freeze \
            or value["population_namespace_sha256"] != expected_namespace \
            or value["tier"] != expected_tier or value["split"] not in (
                "audit", "mixed") or type(value["rows"]) is not list \
            or not value["rows"] or value["authority"] != POPULATION_AUTHORITY:
        raise WorldAfterstateV2TerminalControllerError(
            "audit population manifest identity drift")
    _digest(value["population_sha256"], "audit population SHA-256")
    _digest(value["manifest_sha256"], "audit population manifest SHA-256")
    body = {key: item for key, item in value.items()
            if key not in ("population_sha256", "manifest_sha256")}
    if value["population_sha256"] != _sha(body) \
            or value["manifest_sha256"] != _sha({
                **body, "population_sha256": value["population_sha256"]}):
        raise WorldAfterstateV2TerminalControllerError(
            "audit population manifest hash drift")
    rows = value["rows"]
    identities = [(row.get("tier"), row.get("split"), row.get("source"),
                   row.get("ordinal"), row.get("deal_sha256"))
                  for row in rows if type(row) is dict]
    if len(identities) != len(rows) or len(set(identities)) != len(rows) \
            or identities != sorted(identities):
        raise WorldAfterstateV2TerminalControllerError(
            "audit population manifest row order drift")
    commitment = root / "population" / "population.commitment"
    try:
        committed = stable_read_bytes(commitment)
    except Exception as exc:
        raise WorldAfterstateV2TerminalControllerError(
            "audit population commitment read refused") from exc
    if committed != (value["population_sha256"] + "\n").encode("ascii"):
        raise WorldAfterstateV2TerminalControllerError(
            "audit population commitment drift")
    return value, raw


def _preflight_continuation_manifest(root: Path, deals: set[str]) -> tuple[str, bytes]:
    path = root / "continuations" / "manifest.json"
    value, raw = _read_json(path, "audit continuation manifest")
    required = {"schema", "authority", "rows", "manifest_sha256"}
    if set(value) != required or value["schema"] != CONTINUATION_MANIFEST_SCHEMA \
            or value["authority"] != ARTIFACT_AUTHORITY \
            or type(value["rows"]) is not list or not value["rows"]:
        raise WorldAfterstateV2TerminalControllerError(
            "audit continuation manifest schema drift")
    _digest(value["manifest_sha256"], "audit continuation manifest SHA-256")
    if value["manifest_sha256"] != _sha({
            key: item for key, item in value.items()
            if key != "manifest_sha256"}):
        raise WorldAfterstateV2TerminalControllerError(
            "audit continuation manifest hash drift")
    rows = value["rows"]
    required_row = {"schema", "relative_path", "deal_sha256", "slot_sha256",
                    "state_sha256", "candidate_set_sha256", "byte_count",
                    "sha256", "bundle_sha256"}
    observed = set()
    for row in rows:
        if type(row) is not dict or set(row) != required_row \
                or row["schema"] != "world-afterstate-v2-continuation-artifact-v1":
            raise WorldAfterstateV2TerminalControllerError(
                "audit continuation manifest row drift")
        deal = _digest(row["deal_sha256"], "continuation deal SHA-256")
        if deal in observed or deal not in deals:
            raise WorldAfterstateV2TerminalControllerError(
                "audit continuation deal population drift")
        observed.add(deal)
        for key in ("slot_sha256", "state_sha256", "candidate_set_sha256",
                    "sha256", "bundle_sha256"):
            _digest(row[key], f"continuation {key}")
        if row["relative_path"] != f"continuations/deal-{deal}.bin":
            raise WorldAfterstateV2TerminalControllerError(
                "audit continuation path drift")
    if observed != deals:
        raise WorldAfterstateV2TerminalControllerError(
            "audit continuation deal drop/extra")
    expected_names = {"manifest.json", *(f"deal-{deal}.bin" for deal in deals)}
    directory = root / "continuations"
    if _path(root, "continuation root").is_dir() is False \
            or {item.name for item in directory.iterdir()} != expected_names:
        raise WorldAfterstateV2TerminalControllerError(
            "audit continuation file population drift")
    return value["manifest_sha256"], raw


def _preflight(inputs: TerminalInputPathsV2) -> dict[str, Any]:
    inputs.validate_shape()
    try:
        audit_attempt_raw = stable_read_bytes(inputs.audit_attempt_path)
        audit_attempt = reopen_audit_attempt_bytes(
            audit_attempt_raw, expected_freeze_sha256=inputs.freeze_sha256,
            expected_admission_sha256=inputs.admission_sha256)
    except Exception as exc:
        raise WorldAfterstateV2TerminalControllerError(
            "durable audit attempt refused") from exc
    population, population_raw = _preflight_population(
        inputs.audit_population_root, inputs.freeze_sha256,
        inputs.audit_population_namespace_sha256, inputs.audit_population_tier)
    deals = {row["deal_sha256"] for row in population["rows"]}
    continuation_sha, continuation_raw = _preflight_continuation_manifest(
        inputs.continuation_root, deals)
    predictions = []
    prediction_raws = []
    for label, path in _ordered_paths(inputs.prediction_manifest_paths,
                                      COHORT_LABELS, "prediction manifest"):
        value, raw = _read_json(path, f"prediction manifest {label}")
        try:
            validate_prediction_population_manifest_v2(value)
        except Exception as exc:
            raise WorldAfterstateV2TerminalControllerError(
                f"prediction manifest {label} refused") from exc
        name, block = next((name, block) for wanted, name, block in AUDIT_COHORTS
                           if wanted == label)
        if (value["split"], value["control_name"], value["seed_block"]) != (
                "audit", name, block):
            raise WorldAfterstateV2TerminalControllerError(
                f"prediction manifest {label} binding drift")
        predictions.append((label, value)); prediction_raws.append(raw)
    cohorts = []
    cohort_raws = []
    for label, path in _ordered_paths(inputs.cohort_manifest_paths,
                                      COHORT_LABELS, "cohort manifest"):
        value, raw = _read_json(path, f"cohort manifest {label}")
        try:
            validate_cohort_manifest(value)
        except Exception as exc:
            raise WorldAfterstateV2TerminalControllerError(
                f"cohort manifest {label} refused") from exc
        name, block = next((name, block) for wanted, name, block in AUDIT_COHORTS
                           if wanted == label)
        if (value["cohort_name"], value["seed_block"],
                value["freeze_sha256"]) != (name, block, inputs.freeze_sha256):
            raise WorldAfterstateV2TerminalControllerError(
                f"cohort manifest {label} binding drift")
        cohorts.append((label, value)); cohort_raws.append(raw)
    checkpoint_ids = []
    checkpoint_raws = []
    for (label, root), (_, cohort) in zip(
            _ordered_paths(inputs.checkpoint_roots, COHORT_LABELS,
                           "checkpoint root"), cohorts, strict=True):
        selected_epoch = cohort["common_epoch"]["selected_epoch"]
        schedules = tuple(
            member["epoch_receipts"][selected_epoch - 1]["schedule_sha256"]
            for member in cohort["members"])
        try:
            reopen_checkpoint_manifest(
                root, cohort=cohort["cohort_name"],
                seed_block=cohort["seed_block"], epoch=selected_epoch,
                expected_freeze_sha256=inputs.freeze_sha256,
                expected_config_sha256=cohort["config_sha256"],
                expected_population_sha256=cohort["training_population_sha256"],
                expected_schedule_sha256s=schedules,
                expected_common_epoch_sha256=cohort["common_epoch_sha256"])
            manifest_path = checkpoint_manifest_path(
                root, cohort["cohort_name"], cohort["seed_block"],
                selected_epoch)
            _manifest, raw = _read_json(
                manifest_path, f"checkpoint manifest {label}")
        except Exception as exc:
            raise WorldAfterstateV2TerminalControllerError(
                f"checkpoint manifest {label} refused") from exc
        checkpoint_ids.append((label, _sha_bytes(raw)))
        checkpoint_raws.append(raw)
    p0, p0_raw = _read_json(inputs.p0_report_path, "P0 report")
    try:
        validate_precision_label(p0)
    except Exception as exc:
        raise WorldAfterstateV2TerminalControllerError("P0 report refused") from exc
    canary_payload, canary_raw = _read_json(inputs.optimizer_canary_path,
                                            "optimizer canary")
    precision_payload, precision_raw = _read_json(
        inputs.precision_select_result_path, "precision-select result")
    power_payload, power_raw = _read_json(inputs.model_selector_power_path,
                                           "model-selector power")
    prior_payload, prior_raw = _read_json(inputs.prior_path, "Jeffreys prior")
    dose_rows = []
    dose_raws = []
    for label, path in _ordered_paths(inputs.control_dose_receipt_paths,
                                      DOSE_LABELS, "control dose"):
        value, raw = _read_json(path, f"control dose {label}")
        try:
            validate_control_evidence(value)
        except Exception as exc:
            raise WorldAfterstateV2TerminalControllerError(
                f"control dose {label} refused") from exc
        expected = {"association": "action-association-permutation",
                    "label": "label-permutation",
                    "world": "complete-world-shuffle"}[label]
        if value.get("control_name") != expected:
            raise WorldAfterstateV2TerminalControllerError(
                f"control dose {label} binding drift")
        dose_rows.append((label, value)); dose_raws.append(raw)
    try:
        canary = reopen_optimizer_canary_v2(canary_payload)
        precision = reopen_evaluation_result_v2(precision_payload)
        power = reopen_model_selector_power_v2(power_payload)
        prior = reopen_jeffreys_prior_v2(prior_payload)
    except Exception as exc:
        raise WorldAfterstateV2TerminalControllerError(
            "typed target-free receipt reconstruction refused") from exc
    return {
        "audit_attempt": audit_attempt,
        "audit_attempt_raw": audit_attempt_raw,
        "population": population, "population_raw": population_raw,
        "continuation_sha": continuation_sha, "continuation_raw": continuation_raw,
        "predictions": tuple(predictions), "prediction_raws": tuple(prediction_raws),
        "cohorts": tuple(cohorts), "cohort_raws": tuple(cohort_raws),
        "checkpoint_ids": tuple(checkpoint_ids),
        "checkpoint_raws": tuple(checkpoint_raws),
        "p0": p0, "p0_raw": p0_raw, "canary": canary, "canary_raw": canary_raw,
        "precision": precision, "precision_raw": precision_raw,
        "power": power, "power_raw": power_raw, "prior": prior, "prior_raw": prior_raw,
        "doses": tuple(dose_rows), "dose_raws": tuple(dose_raws),
    }


def _attempt_payload(inputs: TerminalInputPathsV2, preflight: Mapping[str, Any]) \
        -> dict[str, Any]:
    return {
        "schema": ATTEMPT_SCHEMA, "freeze_sha256": inputs.freeze_sha256,
        "admission_sha256": inputs.admission_sha256,
        "audit_attempt_sha256": preflight["audit_attempt"]["attempt_sha256"],
        "audit_population_manifest_sha256": preflight["population"]["manifest_sha256"],
        "audit_population_sha256": preflight["population"]["population_sha256"],
        "continuation_manifest_sha256": preflight["continuation_sha"],
        "prediction_manifest_sha256s": [
            [label, value["manifest_sha256"]]
            for label, value in preflight["predictions"]],
        "cohort_manifest_sha256s": [
            [label, value["manifest_sha256"]]
            for label, value in preflight["cohorts"]],
        "checkpoint_manifest_sha256s": [list(row)
                                         for row in preflight["checkpoint_ids"]],
        # This is the terminal-decision attempt, not the audit-opening marker.
        # The shared audit-attempt record above is the sole artifact allowed to
        # claim publication before labels.
        "audit_opened_count": 1,
        "authority": dict(CONTROLLER_AUTHORITY),
    }


def _publish_attempt(partial: Path, parent: Path, payload: dict[str, Any]) -> tuple[bytes, str]:
    raw = canonical_json_bytes(payload)
    try:
        publish_exclusive_bytes(partial / ATTEMPT_NAME, raw)
        descriptor = os.open(parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except Exception as exc:
        raise WorldAfterstateV2TerminalControllerError(
            "durable terminal attempt publication refused") from exc
    return raw, _sha_bytes(raw)


def _reopen_audit(inputs: TerminalInputPathsV2, preflight: Mapping[str, Any]) \
        -> tuple[AuditDerivationInputV2, Any]:
    try:
        materials = reopen_population_audit_subset(
            inputs.audit_population_root,
            expected_freeze_sha256=inputs.freeze_sha256,
            expected_population_namespace_sha256=(
                inputs.audit_population_namespace_sha256),
            expected_tier=inputs.audit_population_tier,
            expected_split="audit", expected_source=None)
        material_map = {item.deal_sha256: item for item in materials}
        bundles = reopen_continuation_manifest(
            inputs.continuation_root, material_map)
    except Exception as exc:
        raise WorldAfterstateV2TerminalControllerError(
            "audit population or continuation reopen refused") from exc
    outcomes = tuple(row for bundle in bundles for row in bundle.candidates)
    if not outcomes or len({row.state_sha256 for row in outcomes}) != len(
            {item.state_sha256 for item in materials}):
        raise WorldAfterstateV2TerminalControllerError(
            "audit common outcome population drift")
    result_input = AuditDerivationInputV2(
        freeze_sha256=inputs.freeze_sha256,
        admission_sha256=inputs.admission_sha256,
        audit_attempt_sha256=preflight["audit_attempt"]["attempt_sha256"],
        continuation_manifest_sha256=preflight["continuation_sha"],
        prediction_manifests=tuple(preflight["predictions"]),
        checkpoint_manifest_sha256s=preflight["checkpoint_ids"],
        cohort_manifests=tuple(preflight["cohorts"]), p0_report=preflight["p0"],
        optimizer_canary=preflight["canary"],
        precision_select_result=preflight["precision"],
        model_selector_power=preflight["power"], audit_outcomes=outcomes,
        prior=preflight["prior"],
        control_dose_evidence=dict(preflight["doses"]))
    return result_input, materials


def _result_payload(result: WorldAfterstateV2TerminalResult) -> dict[str, Any]:
    result.validate()
    return {**result.payload(), "result_sha256": result.result_sha256}


def _reopen_result(value: Mapping[str, Any]) -> WorldAfterstateV2TerminalResult:
    required = {"schema", "stage_reached", "audit_opened_count",
                "input_receipt_hashes", "decision", "authority",
                "result_sha256"}
    if type(value) is not dict or set(value) != required \
            or type(value["input_receipt_hashes"]) is not list:
        raise WorldAfterstateV2TerminalControllerError("terminal result schema drift")
    try:
        result = WorldAfterstateV2TerminalResult(
            schema=value["schema"], stage_reached=value["stage_reached"],
            audit_opened_count=value["audit_opened_count"],
            input_receipt_hashes=tuple(tuple(row) for row in value[
                "input_receipt_hashes"]), decision=value["decision"],
            authority=value["authority"], result_sha256=value["result_sha256"])
        result.validate()
    except Exception as exc:
        raise WorldAfterstateV2TerminalControllerError(
            "terminal result reconstruction refused") from exc
    if _result_payload(result) != value:
        raise WorldAfterstateV2TerminalControllerError(
            "terminal result canonical reconstruction drift")
    return result


def _early_route_evidence(inputs: EarlyTerminalInputPathsV2) \
        -> tuple[WorldAfterstateV2TerminalEvidence,
                 WorldAfterstateV2TerminalResult,
                 tuple[tuple[str, str], ...]]:
    """Reopen every receipt available at the claimed pre-audit stage."""
    inputs.validate_shape()
    route_value, route_raw = _read_json(
        inputs.route_evidence_path, "early route evidence")
    required = {
        "schema", "freeze_sha256", "admission_sha256", "source_stage",
        "resource_incomplete", "resource_cap_exceeded", "mechanics_failure",
        "audit_opened_count", "authority", "evidence_sha256",
    }
    if set(route_value) != required \
            or route_value["schema"] != EARLY_ROUTE_SCHEMA \
            or route_value["freeze_sha256"] != inputs.freeze_sha256 \
            or route_value["admission_sha256"] != inputs.admission_sha256 \
            or route_value["source_stage"] not in EARLY_STAGES \
            or any(type(route_value[name]) is not bool for name in (
                "resource_incomplete", "resource_cap_exceeded",
                "mechanics_failure")) \
            or route_value["audit_opened_count"] != 0 \
            or route_value["authority"] != CONTROLLER_AUTHORITY:
        raise WorldAfterstateV2TerminalControllerError(
            "early route evidence contract drift")
    route_body = {key: item for key, item in route_value.items()
                  if key != "evidence_sha256"}
    if route_value["evidence_sha256"] != _sha(route_body):
        raise WorldAfterstateV2TerminalControllerError(
            "early route evidence hash drift")

    source_rows: list[tuple[str, str]] = [
        ("route-evidence", _sha_bytes(route_raw))]
    p0 = None
    if inputs.p0_report_path is not None:
        p0, raw = _read_json(inputs.p0_report_path, "early P0 report")
        try:
            validate_precision_label(p0)
        except Exception as exc:
            raise WorldAfterstateV2TerminalControllerError(
                "early P0 report refused") from exc
        source_rows.append(("p0", _sha_bytes(raw)))
    canary = None
    if inputs.optimizer_canary_path is not None:
        value, raw = _read_json(inputs.optimizer_canary_path,
                                "early optimizer canary")
        try:
            canary = reopen_optimizer_canary_v2(value)
        except Exception as exc:
            raise WorldAfterstateV2TerminalControllerError(
                "early optimizer canary refused") from exc
        source_rows.append(("optimizer-canary", _sha_bytes(raw)))
    precision = None
    if inputs.precision_select_result_path is not None:
        value, raw = _read_json(inputs.precision_select_result_path,
                                "early precision-select result")
        try:
            precision = reopen_evaluation_result_v2(value)
        except Exception as exc:
            raise WorldAfterstateV2TerminalControllerError(
                "early precision-select result refused") from exc
        source_rows.append(("precision-select", _sha_bytes(raw)))
    power = None
    if inputs.model_selector_power_path is not None:
        value, raw = _read_json(inputs.model_selector_power_path,
                                "early model-selector power")
        try:
            power = reopen_model_selector_power_v2(value)
        except Exception as exc:
            raise WorldAfterstateV2TerminalControllerError(
                "early model-selector power refused") from exc
        source_rows.append(("model-selector-power", _sha_bytes(raw)))
    manifests = []
    for label, path in inputs.cohort_manifest_paths:
        value, raw = _read_json(path, f"early cohort manifest {label}")
        try:
            validate_cohort_manifest(value)
        except Exception as exc:
            raise WorldAfterstateV2TerminalControllerError(
                f"early cohort manifest {label} refused") from exc
        manifests.append(value)
        source_rows.append((f"cohort:{label}", _sha_bytes(raw)))

    stage = route_value["source_stage"]
    evidence = WorldAfterstateV2TerminalEvidence(
        p0_report=p0, optimizer_canary=canary,
        precision_select_result=precision, model_selector_power=power,
        cohort_manifests=tuple(manifests),
        cohort_truncated=any(
            row.get("truncated_by_deadline") is True for row in manifests),
        resource_incomplete=route_value["resource_incomplete"],
        resource_stage=stage if route_value["resource_incomplete"]
        or route_value["resource_cap_exceeded"]
        or any(row.get("truncated_by_deadline") is True for row in manifests)
        else None,
        resource_cap_exceeded=route_value["resource_cap_exceeded"],
        mechanics_failure=route_value["mechanics_failure"],
        mechanics_stage=stage if route_value["mechanics_failure"] else None,
        audit_opened_count=0)
    try:
        result = derive_terminal_result(evidence)
    except Exception as exc:
        raise WorldAfterstateV2TerminalControllerError(
            "early terminal result derivation refused") from exc
    if result.decision != inputs.expected_route \
            or result.decision not in EARLY_DECISIONS \
            or result.audit_opened_count != 0:
        raise WorldAfterstateV2TerminalControllerError(
            "early terminal expected route differs")
    return evidence, result, tuple(source_rows)


def _early_attempt_payload(inputs: EarlyTerminalInputPathsV2,
                           source_rows: tuple[tuple[str, str], ...]) \
        -> dict[str, Any]:
    return {
        "schema": EARLY_ATTEMPT_SCHEMA,
        "freeze_sha256": inputs.freeze_sha256,
        "admission_sha256": inputs.admission_sha256,
        "expected_route": inputs.expected_route,
        "source_receipt_sha256s": [list(row) for row in source_rows],
        "audit_opened_count": 0,
        "authority": dict(CONTROLLER_AUTHORITY),
    }


def _independent_reconstruct_early_terminal_v2(
        root: Path, inputs: EarlyTerminalInputPathsV2,
        *, publish: bool = True) -> dict[str, Any]:
    root = _path(root, "early terminal root")
    if not root.is_dir() or root.name != "terminal":
        raise WorldAfterstateV2TerminalControllerError(
            "early terminal root drift")
    _evidence, derived, source_rows = _early_route_evidence(inputs)
    attempt_value, attempt_raw = _read_json(
        root / ATTEMPT_NAME, "early terminal attempt")
    if attempt_value != _early_attempt_payload(inputs, source_rows):
        raise WorldAfterstateV2TerminalControllerError(
            "early terminal attempt reconstruction drift")
    result_value, result_raw = _read_json(root / RESULT_NAME,
                                          "early terminal result")
    sealed = _reopen_result(result_value)
    receipt = IndependentReconstructionReceiptV2(
        provenance_sha256=_sha_bytes(attempt_raw),
        sealed_terminal_result_sha256=sealed.result_sha256,
        independently_derived_terminal_result_sha256=derived.result_sha256,
        matched=sealed.result_sha256 == derived.result_sha256,
        verifier_sha256=_sha({
            "module": "world_afterstate_v2_terminal_controller",
            "purpose": "early-independent-reconstruction"}),
        source_sha256=_sha({label: digest for label, digest in source_rows}),
        runtime_sha256=_sha({"python": platform.python_version(),
                             "implementation": platform.python_implementation(),
                             "sys": sys.version_info[:3]}))
    validate_independent_reconstruction_v2(receipt)
    if canonical_json_bytes(_result_payload(sealed)) != result_raw:
        raise WorldAfterstateV2TerminalControllerError(
            "early terminal result byte reconstruction drift")
    if publish:
        try:
            publish_exclusive_bytes(
                root / RECONSTRUCTION_NAME, receipt.canonical_bytes())
        except Exception as exc:
            raise WorldAfterstateV2TerminalControllerError(
                "early independent reconstruction publication refused") from exc
    if not receipt.matched:
        raise WorldAfterstateV2TerminalControllerError(
            "early independent terminal result differs")
    return receipt.payload()


def _run_early_terminal_v2(root: Path,
                           inputs: EarlyTerminalInputPathsV2) -> dict[str, Any]:
    if not isinstance(root, Path) or root.is_symlink():
        raise WorldAfterstateV2TerminalControllerError(
            "early terminal destination drift")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    final = root / "terminal"
    partial = root / "terminal.partial"
    if final.exists() or partial.exists() or final.is_symlink() \
            or partial.is_symlink():
        raise WorldAfterstateV2TerminalControllerError(
            "terminal decision slot occupied")
    _evidence, result, source_rows = _early_route_evidence(inputs)
    try:
        partial.mkdir(mode=0o700, exist_ok=False)
        descriptor = os.open(root, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except FileExistsError as exc:
        raise WorldAfterstateV2TerminalControllerError(
            "terminal decision slot occupied") from exc
    attempt = _early_attempt_payload(inputs, source_rows)
    _publish_attempt(partial, root, attempt)
    try:
        publish_exclusive_bytes(
            partial / RESULT_NAME,
            canonical_json_bytes(_result_payload(result)))
        descriptor = os.open(partial, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.rename(partial, final)
        descriptor = os.open(root, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except BaseException:
        raise
    return _independent_reconstruct_early_terminal_v2(final, inputs)


def _reopen_provenance(value: Mapping[str, Any]) -> AuditProvenanceV2:
    if type(value) is not dict:
        raise WorldAfterstateV2TerminalControllerError("provenance schema drift")
    try:
        result = AuditProvenanceV2(
            **{key: tuple(tuple(row) for row in value[key])
               if key.endswith("sha256s") else value[key]
               for key in ("freeze_sha256", "admission_sha256",
                           "audit_attempt_sha256", "audit_opened_count",
                           "continuation_manifest_sha256",
                           "prediction_manifest_sha256s",
                           "checkpoint_manifest_sha256s",
                           "cohort_manifest_sha256s", "evaluation_result_sha256s",
                           "upstream_receipt_sha256s", "comparison_sha256s",
                           "dose_sha256s", "authority", "schema")})
        result.validate()
    except Exception as exc:
        raise WorldAfterstateV2TerminalControllerError(
            "provenance reconstruction refused") from exc
    if result.payload() != value:
        raise WorldAfterstateV2TerminalControllerError(
            "provenance canonical reconstruction drift")
    return result


def _derive_from_inputs(inputs: TerminalInputPathsV2, preflight: Mapping[str, Any],
                        _terminal_attempt_sha: str) -> tuple[AuditProvenanceV2,
                                                   WorldAfterstateV2TerminalResult]:
    derivation, _materials = _reopen_audit(inputs, preflight)
    try:
        derived = derive_audit_v2(derivation)
        terminal = derive_terminal_result(derived.evidence)
    except Exception as exc:
        raise WorldAfterstateV2TerminalControllerError(
            "terminal evidence/result derivation refused") from exc
    return derived.provenance, terminal


def _source_sha(inputs: TerminalInputPathsV2, preflight: Mapping[str, Any]) -> str:
    return _sha({
        "freeze_sha256": inputs.freeze_sha256,
        "admission_sha256": inputs.admission_sha256,
        "population_sha256": preflight["population"]["population_sha256"],
        "continuation_manifest_sha256": preflight["continuation_sha"],
        "prediction_manifest_sha256s": [
            [label, value["manifest_sha256"]]
            for label, value in preflight["predictions"]],
    })


def independent_reconstruct_terminal_v2(
        root: Path, inputs: TerminalInputPathsV2 | EarlyTerminalInputPathsV2,
        *, publish: bool = True) \
        -> dict[str, Any]:
    """Reopen sealed inputs, rederive once, and publish a reconstruction receipt."""
    if isinstance(inputs, EarlyTerminalInputPathsV2):
        return _independent_reconstruct_early_terminal_v2(
            root, inputs, publish=publish)
    root = _path(root, "terminal root")
    if not root.is_dir() or root.name != "terminal":
        raise WorldAfterstateV2TerminalControllerError(
            "terminal root must be published terminal directory")
    preflight = _preflight(inputs)
    attempt_value, attempt_raw = _read_json(root / ATTEMPT_NAME, "terminal attempt")
    expected_attempt = _attempt_payload(inputs, preflight)
    if attempt_value != expected_attempt:
        raise WorldAfterstateV2TerminalControllerError(
            "terminal attempt reconstruction drift")
    attempt_sha = _sha_bytes(attempt_raw)
    provenance_value, provenance_raw = _read_json(root / PROVENANCE_NAME,
                                                  "terminal provenance")
    terminal_value, terminal_raw = _read_json(root / RESULT_NAME,
                                              "terminal result")
    sealed_provenance = _reopen_provenance(provenance_value)
    sealed_terminal = _reopen_result(terminal_value)
    derived_provenance, derived_terminal = _derive_from_inputs(
        inputs, preflight, attempt_sha)
    if sealed_provenance != derived_provenance:
        raise WorldAfterstateV2TerminalControllerError(
            "terminal provenance reconstruction drift")
    sealed_sha = sealed_terminal.result_sha256
    independent_sha = derived_terminal.result_sha256
    receipt = IndependentReconstructionReceiptV2(
        provenance_sha256=derived_provenance.sha256(),
        sealed_terminal_result_sha256=sealed_sha,
        independently_derived_terminal_result_sha256=independent_sha,
        matched=sealed_sha == independent_sha,
        verifier_sha256=_sha({"module": "world_afterstate_v2_terminal_controller",
                              "purpose": "independent-reconstruction"}),
        source_sha256=_source_sha(inputs, preflight),
        runtime_sha256=_sha({"python": platform.python_version(),
                             "implementation": platform.python_implementation(),
                             "sys": sys.version_info[:3]}))
    validate_independent_reconstruction_v2(receipt)
    receipt_path = root / RECONSTRUCTION_NAME
    if type(publish) is not bool:
        raise WorldAfterstateV2TerminalControllerError("reconstruction publish flag drift")
    if publish:
        try:
            publish_exclusive_bytes(receipt_path, receipt.canonical_bytes())
        except Exception as exc:
            raise WorldAfterstateV2TerminalControllerError(
                "independent reconstruction publication refused") from exc
    if not receipt.matched:
        raise WorldAfterstateV2TerminalControllerError(
            "independent terminal result hash differs")
    return receipt.payload()


def verify_terminal_artifact_v2(
        root: Path, inputs: TerminalInputPathsV2 | EarlyTerminalInputPathsV2,
        *, rescore: bool = False) \
        -> dict[str, Any]:
    """Read a receipt by default; explicitly requested ``rescore`` reopens all inputs."""
    root = _path(root, "terminal root")
    if not root.is_dir() or root.name != "terminal":
        raise WorldAfterstateV2TerminalControllerError("terminal root drift")
    receipt_value, _ = _read_json(root / RECONSTRUCTION_NAME,
                                  "independent reconstruction")
    try:
        receipt = IndependentReconstructionReceiptV2(**receipt_value)
        validate_independent_reconstruction_v2(receipt)
    except Exception as exc:
        raise WorldAfterstateV2TerminalControllerError(
            "independent reconstruction receipt refused") from exc
    terminal_value, terminal_raw = _read_json(root / RESULT_NAME, "terminal result")
    terminal = _reopen_result(terminal_value)
    if terminal.result_sha256 != receipt.sealed_terminal_result_sha256 \
            or _sha_bytes(terminal_raw) != _sha_bytes(canonical_json_bytes(
                terminal_value)):
        raise WorldAfterstateV2TerminalControllerError(
            "sealed terminal result differs from reconstruction receipt")
    if rescore:
        return independent_reconstruct_terminal_v2(root, inputs, publish=False)
    return receipt.payload()


def run_terminal_v2(
        root: Path, inputs: TerminalInputPathsV2 | EarlyTerminalInputPathsV2) \
        -> dict[str, Any]:
    """Run the scientific audit once, then perform its one immediate verifier call."""
    if isinstance(inputs, EarlyTerminalInputPathsV2):
        return _run_early_terminal_v2(root, inputs)
    if not isinstance(root, Path) or root.is_symlink():
        raise WorldAfterstateV2TerminalControllerError("terminal destination drift")
    if root.exists() and not root.is_dir():
        raise WorldAfterstateV2TerminalControllerError("terminal destination drift")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    final = root / "terminal"
    partial = root / "terminal.partial"
    if final.exists() or partial.exists() or final.is_symlink() \
            or partial.is_symlink():
        raise WorldAfterstateV2TerminalControllerError("terminal decision slot occupied")
    preflight = _preflight(inputs)
    try:
        partial.mkdir(mode=0o700, exist_ok=False)
        parent_descriptor = os.open(root, os.O_RDONLY)
        try:
            os.fsync(parent_descriptor)
        finally:
            os.close(parent_descriptor)
    except FileExistsError as exc:
        raise WorldAfterstateV2TerminalControllerError(
            "terminal decision slot occupied") from exc
    attempt = _attempt_payload(inputs, preflight)
    attempt_raw, attempt_sha = _publish_attempt(partial, root, attempt)
    try:
        provenance, terminal = _derive_from_inputs(inputs, preflight, attempt_sha)
        _write = ((partial / PROVENANCE_NAME, provenance.canonical_bytes()),
                  (partial / RESULT_NAME, canonical_json_bytes(
                      _result_payload(terminal))))
        for path, raw in _write:
            publish_exclusive_bytes(path, raw)
        descriptor = os.open(partial, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.rename(partial, final)
        descriptor = os.open(root, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except BaseException:
        # This is intentionally not cleaned up: a derivation failure consumes
        # the one scientific opening and leaves the durable attempt witness.
        raise
    # Exactly one immediate independent verifier call.  Later callers use the
    # receipt-only verifier unless they explicitly request rescoring.
    return independent_reconstruct_terminal_v2(final, inputs)


# Integration-friendly names used by scripts and review harnesses.
run_open_audit_v2 = run_terminal_v2
run_v2_terminal = run_terminal_v2
independent_verify_terminal_v2 = independent_reconstruct_terminal_v2
reconstruct_terminal_v2 = independent_reconstruct_terminal_v2
open_terminal_v2 = run_terminal_v2
verify_terminal_artifact = verify_terminal_artifact_v2


__all__ = [
    "ATTEMPT_NAME", "ATTEMPT_SCHEMA", "AuditTerminalInputV2",
    "CONTROLLER_AUTHORITY", "IndependentReconstructionReceiptV2",
    "PROVENANCE_NAME", "RECONSTRUCTION_NAME", "RESULT_NAME",
    "TerminalInputPathsV2", "WorldAfterstateV2TerminalControllerError",
    "TerminalInputV2", "WorldAfterstateV2TerminalInputs",
    "independent_reconstruct_terminal_v2",
    "independent_verify_terminal_v2", "run_open_audit_v2", "run_terminal_v2",
    "run_v2_terminal", "open_terminal_v2", "reconstruct_terminal_v2",
    "verify_terminal_artifact", "verify_terminal_artifact_v2",
]
