"""Closed adapters from the execution ABI to reviewed V2 controllers.

Each adapter owns its frozen inputs and all low-level producer choices.  The
execution supervisor can therefore obtain only a reviewed operation through
``production_stage_adapter``; callers cannot inject callbacks or resource
overrides.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .belief_artifacts import stable_read_bytes
from .belief_contract import canonical_json_bytes
from .world_afterstate_v2_population_controller import (
    WORKER_ARMS, collect_population_v2, reopen_population_receipt_v2,
)

# These are deliberately imported as the producer objects (rather than
# looked up by name at call time).  StageControllerV2 compares the identity of
# this property with the execution-side production lookup.
from .world_afterstate_v2_label import evaluate_precision_label
from .world_afterstate_v2_diagnostic_producers import (
    OptimizerCanaryInputV2, produce_optimizer_canary_v2,
)
from .world_afterstate_v2_population_artifacts import reopen_population_manifest
from .world_afterstate_v2_artifacts import reopen_continuation_manifest
from .world_afterstate_v2_label_controller import (
    build_continuation_population_v2, reopen_label_stage_receipt)
from .world_afterstate_v2_protocol import (
    TIER_SPECS, build_population_slot_ledger, select_p0_population)
from .world_afterstate_v2_p0_mechanics import build_engine_p0_mechanics_evidence
from .world_afterstate_v2_reopen import (
    reopen_optimizer_canary_v2,
)
from .world_afterstate_v2_training_stage_adapters import (
    production_training_stage_adapter,
)
from .world_afterstate_v2_late_stage_adapters import (
    evaluate_precision_select_v2, publish_audit_attempt,
    production_stage_adapter as production_late_stage_adapter,
)


ABI = "world-afterstate-v2-stage-adapter-supervisor-shards-v1"
INPUT_SCHEMA = "world-afterstate-v2-population-adapter-input-v2"
POPULATION_INPUT_SCHEMA = INPUT_SCHEMA
STAGE_INPUT_SCHEMA = "world-afterstate-v2-early-stage-adapters-input-v1"
# The six-label freeze ABI has one config artifact.  These aliases are kept
# public for callers that name the stage, but all three resolve the same
# unified envelope and are never three independent config artifacts.
P0_INPUT_SCHEMA = STAGE_INPUT_SCHEMA
OPTIMIZER_INPUT_SCHEMA = STAGE_INPUT_SCHEMA
NESTED_INPUT_SCHEMA = STAGE_INPUT_SCHEMA
P0_CONTINUATION_ROOT = "p0-continuations"
FIT_SELECT_CONTINUATION_ROOT = "fit-select-continuations"
_STAGE_CONFIG_FIELDS = frozenset({
    "schema", "artifact_root", "population_namespace_sha256",
    "label_workers", "label_deadline_seconds",
    "p0-labels-gates", "optimizer-canary", "nested-curve",
})
_INPUT_FIELDS = frozenset({
    "schema", "population_namespace_sha256", "max_attempts_per_slot",
    "workers", "deadline_seconds", "heartbeat_seconds",
})


class StageAdapterUnavailable(ValueError):
    """A reviewed low-level producer has no composed typed adapter."""


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _digest(value: object, label: str) -> str:
    if type(value) is not str or len(value) != 64 \
            or any(char not in "0123456789abcdef" for char in value):
        raise StageAdapterUnavailable(f"{label} drift")
    return value


def _absolute_stage_deadline(supervisor: Any, freeze: Any,
                             stage_seconds: int) -> int:
    """Return one absolute deadline capped by the original admission wall.

    A resumed or later stage may consume only the headroom left from the
    supervisor's persisted start; it never receives a fresh full-stage wall.
    """
    try:
        now = supervisor.clock()
        started = int(supervisor._started)
        global_deadline = (
            started + int(freeze.deadline_seconds) * 1_000_000_000)
        value = min(now + stage_seconds * 1_000_000_000, global_deadline)
    except (AttributeError, TypeError, ValueError) as exc:
        raise StageAdapterUnavailable(
            "stage absolute deadline binding unavailable") from exc
    if value <= now:
        raise StageAdapterUnavailable("stage absolute deadline exhausted")
    return value


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise StageAdapterUnavailable("population input duplicate key")
        value[key] = item
    return value


def _strict_json(raw: bytes) -> dict[str, Any]:
    try:
        value = json.loads(raw.decode("ascii"), object_pairs_hook=_strict_object)
    except StageAdapterUnavailable:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StageAdapterUnavailable("population receipt JSON drift") from exc
    if type(value) is not dict or canonical_json_bytes(value) != raw:
        raise StageAdapterUnavailable("population receipt canonical drift")
    return value


def _read_input(path: Path, *, expected_digest: str,
                freeze_deadline: int) -> dict[str, Any]:
    if not isinstance(path, Path) or path.is_symlink() or not path.is_file():
        raise StageAdapterUnavailable("population adapter input artifact missing")
    try:
        raw = stable_read_bytes(path)
    except (OSError, ValueError) as exc:
        raise StageAdapterUnavailable("population adapter input artifact drift") from exc
    if _sha(raw) != _digest(expected_digest, "population input artifact SHA-256"):
        raise StageAdapterUnavailable("population adapter input artifact drift")
    try:
        value = json.loads(raw.decode("ascii"), object_pairs_hook=_strict_object)
    except StageAdapterUnavailable:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StageAdapterUnavailable("population adapter input is not JSON") from exc
    if type(value) is not dict or canonical_json_bytes(value) != raw \
            or set(value) != _INPUT_FIELDS or value["schema"] != INPUT_SCHEMA:
        raise StageAdapterUnavailable("population adapter input schema drift")
    namespace = _digest(value["population_namespace_sha256"],
                        "population adapter namespace SHA-256")
    cap = value["max_attempts_per_slot"]
    workers = value["workers"]
    deadline = value["deadline_seconds"]
    heartbeat = value["heartbeat_seconds"]
    for item, label in ((cap, "attempt cap"), (workers, "workers"),
                        (deadline, "deadline seconds"), (heartbeat, "heartbeat seconds")):
        if isinstance(item, bool) or not isinstance(item, int) or item < 1:
            raise StageAdapterUnavailable(f"population adapter {label} drift")
    if workers not in WORKER_ARMS:
        raise StageAdapterUnavailable("population adapter workers drift")
    if heartbeat > 60:
        raise StageAdapterUnavailable("population adapter heartbeat drift")
    if isinstance(freeze_deadline, bool) or not isinstance(freeze_deadline, int) \
            or freeze_deadline < 1:
        raise StageAdapterUnavailable("population adapter freeze deadline drift")
    if deadline > freeze_deadline:
        raise StageAdapterUnavailable("population adapter deadline exceeds freeze")
    return {
        "population_namespace_sha256": namespace,
        "max_attempts_per_slot": cap, "workers": workers,
        "deadline_seconds": deadline, "heartbeat_seconds": heartbeat,
    }


def _population_binding(freeze: Any) -> tuple[str, str, str]:
    bindings = getattr(freeze, "artifact_bindings", None)
    if type(bindings) not in (tuple, list):
        raise StageAdapterUnavailable("population adapter artifact binding missing")
    matches = [row for row in bindings
               if type(row) is tuple and len(row) == 3
               and row[0] == "population"]
    if len(matches) == 1:
        _label, relative, digest = matches[0]
        if type(relative) is not str or not relative or Path(relative).is_absolute() \
                or "\\" in relative or any(part in ("", ".", "..")
                                             for part in Path(relative).parts) \
                or Path(relative).as_posix() != relative:
            raise StageAdapterUnavailable("population adapter artifact path drift")
        _digest(digest, "population input artifact SHA-256")
        return matches[0]
    raise StageAdapterUnavailable("population adapter artifact binding missing")


def _config_binding(freeze: Any) -> tuple[str, str, str]:
    """Return the one freeze-bound configuration artifact.

    The freeze ABI intentionally has one config slot.  Early-stage adapters
    consume a stage-specific envelope in that slot; they never accept a
    caller-provided path or producer.
    """
    bindings = getattr(freeze, "artifact_bindings", None)
    matches = [row for row in (bindings or ())
               if type(row) is tuple and len(row) == 3 and row[0] == "config"]
    if len(matches) != 1:
        raise StageAdapterUnavailable("stage adapter config binding missing")
    _label, relative, digest = matches[0]
    if (type(relative) is not str or not relative or Path(relative).is_absolute()
            or "\\" in relative or Path(relative).as_posix() != relative
            or any(part in ("", ".", "..") for part in Path(relative).parts)):
        raise StageAdapterUnavailable("stage adapter config path drift")
    _digest(digest, "stage adapter config SHA-256")
    return matches[0]


def _read_stage_config(repo: Path, freeze: Any, schema: str) -> dict[str, Any]:
    if not isinstance(repo, Path) or repo.is_symlink() or not repo.is_dir():
        raise StageAdapterUnavailable("stage adapter repository drift")
    _label, relative, digest = _config_binding(freeze)
    path = repo / relative
    if path.is_symlink() or not path.is_file():
        raise StageAdapterUnavailable("stage adapter config artifact missing")
    try:
        raw = stable_read_bytes(path)
        value = json.loads(raw.decode("ascii"), object_pairs_hook=_strict_object)
    except StageAdapterUnavailable:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StageAdapterUnavailable("stage adapter config artifact drift") from exc
    if _sha(raw) != digest or type(value) is not dict \
            or value.get("schema") != STAGE_INPUT_SCHEMA \
            or set(value) != _STAGE_CONFIG_FIELDS:
        raise StageAdapterUnavailable("stage adapter config schema drift")
    if canonical_json_bytes(value) != raw:
        raise StageAdapterUnavailable("stage adapter config is not canonical")
    workers = value["label_workers"]
    deadline = value["label_deadline_seconds"]
    freeze_deadline = getattr(freeze, "deadline_seconds", None)
    if (isinstance(workers, bool) or not isinstance(workers, int)
            or not 1 <= workers <= (os.cpu_count() or 1)
            or isinstance(deadline, bool) or not isinstance(deadline, int)
            or deadline < 1 or isinstance(freeze_deadline, bool)
            or not isinstance(freeze_deadline, int) or freeze_deadline < 1
            or deadline > freeze_deadline):
        raise StageAdapterUnavailable("stage adapter label resource binding drift")
    # The currently implemented population controller is deliberately D256.
    # The score-free tier gate must therefore make larger tiers ineligible;
    # an adapter may not silently run D256 under a larger frozen tier.
    if getattr(freeze, "population_tier", None) != "D256" \
            or value["artifact_root"] != str(Path(freeze.evidence_root)) \
            or type(value["p0-labels-gates"]) is not dict \
            or type(value["optimizer-canary"]) is not dict \
            or type(value["nested-curve"]) is not dict \
            or value["p0-labels-gates"] != {} \
            or value["optimizer-canary"] != {} \
            or value["nested-curve"] != {}:
        raise StageAdapterUnavailable("stage adapter config binding drift")
    return value


def _population_materials(freeze: Any, repo: Path, *, split: str,
                          source: str | None = None) -> tuple[Any, ...]:
    """Reopen only the frozen population material split requested by a stage."""
    config = _read_stage_config(repo, freeze, STAGE_INPUT_SCHEMA)
    namespace = _digest(config["population_namespace_sha256"],
                        "stage population namespace SHA-256")
    root = Path(freeze.evidence_root)
    try:
        values = reopen_population_manifest(
            root, expected_freeze_sha256=freeze.sha256(),
            expected_population_namespace_sha256=namespace,
            expected_tier="D256", expected_split=split,
            expected_source=source)
    except Exception as exc:
        raise StageAdapterUnavailable("stage population material reopen refused") from exc
    return tuple(values)


def _optimizer_canary_inputs(supervisor: Any, freeze: Any, repo: Path,
                             schema: str) -> tuple[tuple[Any, ...], tuple[Any, ...]]:
    """Reopen all 128 pre-label states and only the 96 sealed P0 labels."""
    del supervisor
    config = _read_stage_config(repo, freeze, schema)
    try:
        namespace = _digest(config["population_namespace_sha256"],
                            "P0 population namespace SHA-256")
        root = Path(freeze.evidence_root)
        if root.is_symlink() or not root.is_dir():
            raise StageAdapterUnavailable("P0 artifact root binding drift")
        materials = reopen_population_manifest(
            root, expected_freeze_sha256=freeze.sha256(),
            expected_population_namespace_sha256=namespace,
            expected_tier="D256", expected_split="fit", expected_source="natural")
        selected_states = select_p0_population(
            tuple(material.state for material in materials), tier=TIER_SPECS[0])
        selected_deals = {state.deal_sha256 for state in selected_states}
        selected = tuple(material for material in materials
                         if material.deal_sha256 in selected_deals)
        bundles = reopen_continuation_manifest(
            root / P0_CONTINUATION_ROOT, selected)
    except StageAdapterUnavailable:
        raise
    except Exception as exc:
        raise StageAdapterUnavailable("P0 sealed input reopen refused") from exc
    if len(materials) != 128 or len(selected) != 96 or len(bundles) != 96:
        raise StageAdapterUnavailable("P0 natural-fit input population drift")
    return tuple(materials), tuple(zip(selected, bundles, strict=True))


def _p0_reuse_source(
        fit: tuple[Any, ...], freeze: Any
        ) -> tuple[Path, tuple[Any, ...]]:
    """Derive the canonical P0 materials used by FitSelect reuse.

    The label controller reopens the returned source root only after its
    final-target manifest check, so an already complete FitSelect target keeps
    the normal authoritative reopener path.
    """
    natural = tuple(material for material in fit
                    if getattr(material.state, "source", None) == "natural")
    if len(natural) != 128:
        raise StageAdapterUnavailable("P0 natural-fit material population drift")
    try:
        selected_states = select_p0_population(
            tuple(material.state for material in natural), tier=TIER_SPECS[0])
    except Exception as exc:
        raise StageAdapterUnavailable("P0 canonical selection refused") from exc
    selected_deals = {state.deal_sha256 for state in selected_states}
    selected = tuple(material for material in natural
                     if material.deal_sha256 in selected_deals)
    if len(selected) != 96:
        raise StageAdapterUnavailable("P0 canonical 128-to-96 selection drift")
    return Path(freeze.evidence_root) / P0_CONTINUATION_ROOT, selected


def _label_progress(supervisor: Any, stage: str, split: str):
    def progress(value: dict[str, Any]) -> None:
        if type(value) is not dict:
            raise StageAdapterUnavailable("label progress drift")
        try:
            supervisor.emit_progress(
                stage=stage, substage=f"{split}-labels",
                completed=value["completed_deals"], total=value["total_deals"],
                active_workers=value["active_workers"], active_threads=0,
                sealed_shards=value["immutable_shards"])
        except (KeyError, TypeError, ValueError) as exc:
            raise StageAdapterUnavailable("label progress drift") from exc
    return progress


def _stage_label_resources(config: dict[str, Any], freeze: Any) -> tuple[int, int]:
    workers = config["label_workers"]
    deadline = config["label_deadline_seconds"]
    freeze_deadline = getattr(freeze, "deadline_seconds", None)
    if (isinstance(workers, bool) or not isinstance(workers, int)
            or not 1 <= workers <= (os.cpu_count() or 1)
            or isinstance(deadline, bool) or not isinstance(deadline, int)
            or deadline < 1 or isinstance(freeze_deadline, bool)
            or not isinstance(freeze_deadline, int) or freeze_deadline < 1
            or deadline > freeze_deadline):
        raise StageAdapterUnavailable("stage adapter label resource binding drift")
    return workers, deadline


def _register_or_reopen(supervisor: Any, stage: str, receipt: Any) -> Any:
    """Seal one receipt shard, or reopen the already sealed compatible one."""
    existing = tuple(supervisor.verified_shards(stage))
    if existing:
        if existing != ("receipt",):
            raise StageAdapterUnavailable(f"{stage} sealed output population drift")
        path = supervisor.root / "shards" / stage / "receipt.bin"
        try:
            raw = stable_read_bytes(path)
            value = json.loads(raw.decode("ascii"), object_pairs_hook=_strict_object)
            if canonical_json_bytes(value) != raw:
                raise ValueError("non-canonical sealed output")
            if stage == "optimizer-canary":
                return reopen_optimizer_canary_v2(value)
            if stage == "fit-select-labels":
                return reopen_label_stage_receipt(value)
            from .world_afterstate_v2_label import validate_precision_label
            validate_precision_label(value)
            return value
        except Exception as exc:
            raise StageAdapterUnavailable(f"{stage} sealed output drift") from exc
    try:
        payload = receipt if type(receipt) is dict else receipt.payload()
        raw = canonical_json_bytes(payload)
        supervisor.register_verified_shard(stage, "receipt", raw)
    except Exception as exc:
        raise StageAdapterUnavailable(f"{stage} output publication refused") from exc
    return receipt


def _population_receipt(supervisor: Any, *, freeze_sha: str,
                        admission_sha: str, namespace: str,
                        max_attempts: int, receipt: Any | None = None) -> Any:
    """Reopen or publish the controller's authoritative population receipt.

    The controller owns the receipt under ``population-controller``.  The
    execution supervisor separately needs the exact same bytes as its
    ``population/receipt.bin`` shard, so promotion happens only after the
    controller payload has passed its typed reopener.
    """
    existing = tuple(supervisor.verified_shards("population"))
    if existing:
        if existing != ("receipt",):
            raise StageAdapterUnavailable("population sealed output population drift")
        path = supervisor.root / "shards" / "population" / "receipt.bin"
        try:
            value = _strict_json(stable_read_bytes(path))
            reopened = reopen_population_receipt_v2(value)
        except Exception as exc:
            raise StageAdapterUnavailable("population sealed receipt reopen refused") from exc
    else:
        if receipt is None:
            raise StageAdapterUnavailable("population controller receipt missing")
        try:
            payload = receipt.payload()
            if type(payload) is not dict:
                raise ValueError("population controller receipt payload drift")
            raw = canonical_json_bytes(payload)
            reopened = reopen_population_receipt_v2(payload)
            if reopened.payload() != payload:
                raise ValueError("population controller receipt reconstruction drift")
        except Exception as exc:
            raise StageAdapterUnavailable("population controller receipt reopen refused") from exc
    if (reopened.freeze_sha256, reopened.population_namespace_sha256,
            reopened.admission_sha256, reopened.max_attempts_per_slot) != (
                freeze_sha, namespace, admission_sha, max_attempts):
        raise StageAdapterUnavailable("population receipt identity drift")
    if existing:
        return reopened
    try:
        supervisor.register_verified_shard("population", "receipt", raw)
    except Exception as exc:
        raise StageAdapterUnavailable("population receipt publication refused") from exc
    return reopened


@dataclass(frozen=True)
class PopulationCollectionAdapterV2:
    """Supervisor ABI adapter for real D256 population collection/resume."""

    freeze: Any
    repo: Path
    __world_afterstate_v2_stage_adapter__: str = ABI

    @property
    def producer(self) -> Callable[..., Any]:
        return collect_population_v2

    def __call__(self, supervisor: Any, verified_shards: tuple[str, ...]) -> Any:
        del verified_shards
        if not callable(getattr(supervisor, "emit_progress", None)):
            raise StageAdapterUnavailable("population adapter supervisor progress unavailable")
        try:
            freeze_sha = self.freeze.sha256()
            admission_sha = supervisor.admission.sha256()
            freeze_deadline = self.freeze.deadline_seconds
        except (AttributeError, TypeError, ValueError) as exc:
            raise StageAdapterUnavailable("population adapter identity unavailable") from exc
        _digest(freeze_sha, "population adapter freeze SHA-256")
        _digest(admission_sha, "population adapter admission SHA-256")
        if isinstance(freeze_deadline, bool) or not isinstance(freeze_deadline, int) \
                or freeze_deadline < 1:
            raise StageAdapterUnavailable("population adapter freeze deadline drift")
        _label, relative, digest = _population_binding(self.freeze)
        config = _read_input(self.repo / relative, expected_digest=digest,
                             freeze_deadline=freeze_deadline)

        try:
            population_shards = supervisor.verified_shards("population")
        except Exception as exc:
            raise StageAdapterUnavailable(
                "population sealed shard registry drift") from exc
        if population_shards:
            return _population_receipt(
                supervisor, freeze_sha=freeze_sha, admission_sha=admission_sha,
                namespace=config["population_namespace_sha256"],
                max_attempts=config["max_attempts_per_slot"])

        def progress(value: dict[str, Any]) -> None:
            if type(value) is not dict:
                raise StageAdapterUnavailable("population progress drift")
            try:
                supervisor.emit_progress(
                    stage=value["stage"], substage=value["substage"],
                    completed=value["completed_slots"], total=value["total_slots"],
                    active_workers=value["active_workers"],
                    sealed_shards=value["immutable_shards"])
            except (KeyError, TypeError, ValueError) as exc:
                raise StageAdapterUnavailable("population progress drift") from exc

        try:
            receipt = self.producer(
                supervisor.root, freeze_sha256=freeze_sha,
                population_namespace_sha256=config["population_namespace_sha256"],
                admission_sha256=admission_sha,
                max_attempts_per_slot=config["max_attempts_per_slot"],
                workers=config["workers"], deadline_seconds=config["deadline_seconds"],
                heartbeat_seconds=config["heartbeat_seconds"],
                progress_callback=progress)
            return _population_receipt(
                supervisor, freeze_sha=freeze_sha, admission_sha=admission_sha,
                namespace=config["population_namespace_sha256"],
                max_attempts=config["max_attempts_per_slot"], receipt=receipt)
        except StageAdapterUnavailable:
            raise
        except (OSError, TypeError, ValueError) as exc:
            raise StageAdapterUnavailable("population producer refused") from exc


# Compatibility name retained for the execution-side binding while its
# operation is now the progressive collect-or-reopen producer.
PopulationReopenAdapterV2 = PopulationCollectionAdapterV2


def population_collection_adapter(*, freeze: Any, repo: Path) -> PopulationCollectionAdapterV2:
    if not isinstance(repo, Path):
        raise StageAdapterUnavailable("population adapter repository drift")
    _label, relative, digest = _population_binding(freeze)
    try:
        freeze_deadline = freeze.deadline_seconds
    except AttributeError as exc:
        raise StageAdapterUnavailable("population adapter freeze deadline unavailable") from exc
    _read_input(repo / relative, expected_digest=digest,
                freeze_deadline=freeze_deadline)
    # This is the exact reviewed producer imported from the population
    # controller.  No caller-supplied function or attempt driver is accepted.
    return PopulationCollectionAdapterV2(freeze, repo)


population_reopen_adapter = population_collection_adapter
population_production_adapter = population_collection_adapter
population_adapter = population_collection_adapter
PopulationProductionAdapterV2 = PopulationCollectionAdapterV2


@dataclass(frozen=True)
class P0LabelsGatesAdapterV2:
    freeze: Any
    repo: Path
    __world_afterstate_v2_stage_adapter__: str = ABI

    @property
    def producer(self) -> Callable[..., Any]:
        return evaluate_precision_label

    def __call__(self, supervisor: Any, verified_shards: tuple[str, ...]) -> Any:
        del verified_shards
        if not callable(getattr(supervisor, "emit_progress", None)):
            raise StageAdapterUnavailable("P0 adapter supervisor progress unavailable")
        supervisor.emit_progress(stage="p0-labels-gates", completed=0, total=1, force=True)
        try:
            config = _read_stage_config(self.repo, self.freeze, P0_INPUT_SCHEMA)
            workers, deadline = _stage_label_resources(config, self.freeze)
            all_materials = _population_materials(
                self.freeze, self.repo, split="fit", source="natural")
            if len(all_materials) != 128:
                raise StageAdapterUnavailable("P0 natural-fit material population drift")
            selected_states = select_p0_population(
                tuple(item.state for item in all_materials), tier=TIER_SPECS[0])
            selected_deals = {state.deal_sha256 for state in selected_states}
            selected = tuple(material for material in all_materials
                             if material.deal_sha256 in selected_deals)
            if len(selected) != 96:
                raise StageAdapterUnavailable("P0 canonical 128-to-96 selection drift")
            # P0 labels are spent only inside their dedicated continuation root;
            # the fit/select root is never touched by this adapter.
            label_root = Path(self.freeze.evidence_root) / P0_CONTINUATION_ROOT
            label_receipt = build_continuation_population_v2(
                label_root, selected, split="fit-select", workers=workers,
                deadline_monotonic_ns=_absolute_stage_deadline(
                    supervisor, self.freeze, deadline),
                progress=_label_progress(supervisor, "p0-labels-gates", "p0"))
            label_receipt.payload()
            bundles = reopen_continuation_manifest(label_root, selected)
            if supervisor.verified_shards("p0-labels-gates"):
                return _register_or_reopen(supervisor, "p0-labels-gates", None)
            materials = selected
            outcomes = tuple(row for bundle in bundles for row in bundle.candidates)
            natural_slots = {
                slot.slot_sha256: slot
                for slot in build_population_slot_ledger(TIER_SPECS[0])
                if slot.group == "natural-fit"
            }
            slots = {
                state.deal_sha256: natural_slots[state.slot_sha256]
                for state in selected_states
            }
            all_states = tuple(item.state for item in all_materials)
            evidence = build_engine_p0_mechanics_evidence(
                outcomes, required_slots=slots,
                natural_fit_population=all_states,
                tier=TIER_SPECS[0], materials=materials, bundles=bundles)
            result = self.producer(
                outcomes, required_slots=slots,
                natural_fit_population=all_states,
                tier=TIER_SPECS[0], mechanics_evidence=evidence)
            from .world_afterstate_v2_label import validate_precision_label
            validate_precision_label(result)
            result = _register_or_reopen(supervisor, "p0-labels-gates", result)
            decision = result.get("decision")
            if decision != "PASS_P0_PRECISION":
                if decision not in (
                        "STOP_NO_REPRODUCIBLE_VALUE_LABEL",
                        "STOP_BELOW_WORTHWHILE_VALUE_FLOOR",
                        "REFUSE_MECHANICS_OR_CONTROL"):
                    raise StageAdapterUnavailable("P0 terminal route drift")
                supervisor.terminal(decision)
        except StageAdapterUnavailable:
            raise
        except Exception as exc:
            raise StageAdapterUnavailable("P0 labels/gates producer refused") from exc
        supervisor.emit_progress(stage="p0-labels-gates", completed=1, total=1, force=True)
        return result


@dataclass(frozen=True)
class OptimizerCanaryAdapterV2:
    freeze: Any
    repo: Path
    __world_afterstate_v2_stage_adapter__: str = ABI

    @property
    def producer(self) -> Callable[..., Any]:
        return produce_optimizer_canary_v2

    def __call__(self, supervisor: Any, verified_shards: tuple[str, ...]) -> Any:
        del verified_shards
        if not callable(getattr(supervisor, "emit_progress", None)):
            raise StageAdapterUnavailable("optimizer adapter supervisor progress unavailable")
        if supervisor.verified_shards("optimizer-canary"):
            return _register_or_reopen(supervisor, "optimizer-canary", {})
        supervisor.emit_progress(stage="optimizer-canary", completed=0, total=1, force=True)
        try:
            natural_fit, pairs = _optimizer_canary_inputs(
                supervisor, self.freeze, self.repo, OPTIMIZER_INPUT_SCHEMA)
            population = OptimizerCanaryInputV2(
                natural_fit,
                tuple(material for material, _bundle in pairs),
                tuple(bundle for _material, bundle in pairs))
            result = self.producer(population)
            result.validate()
            result = _register_or_reopen(supervisor, "optimizer-canary", result)
            if result.passed is not True:
                supervisor.terminal("REFUSE_TRAINING_RECIPE")
        except StageAdapterUnavailable:
            raise
        except Exception as exc:
            raise StageAdapterUnavailable("optimizer canary producer refused") from exc
        supervisor.emit_progress(stage="optimizer-canary", completed=1, total=1, force=True)
        return result


build_fit_select_continuations_v2 = build_continuation_population_v2


@dataclass(frozen=True)
class FitSelectLabelsAdapterV2:
    """Build the fit and epoch-select labels, excluding precision-select."""

    freeze: Any
    repo: Path
    __world_afterstate_v2_stage_adapter__: str = ABI

    @property
    def producer(self) -> Callable[..., Any]:
        return build_fit_select_continuations_v2

    def __call__(self, supervisor: Any,
                 verified_shards: tuple[str, ...]) -> Any:
        del verified_shards
        if not callable(getattr(supervisor, "emit_progress", None)):
            raise StageAdapterUnavailable(
                "fit-select labels supervisor progress unavailable")
        state = getattr(supervisor, "state", None)
        completed = getattr(state, "completed_stages", ())
        if state is None or not {"p0-labels-gates", "optimizer-canary"}.issubset(
                set(completed)):
            raise StageAdapterUnavailable(
                "fit-select labels require completed P0 and optimizer stages")
        config = _read_stage_config(self.repo, self.freeze, STAGE_INPUT_SCHEMA)
        workers, deadline = _stage_label_resources(config, self.freeze)
        try:
            fit = _population_materials(
                self.freeze, self.repo, split="fit", source=None)
            select = _population_materials(
                self.freeze, self.repo, split="select", source="natural")
            epoch_select = tuple(
                material for material in select
                if material.state.select_subfold == "epoch-select")
            if len(fit) != 160 or len(epoch_select) != 24:
                raise StageAdapterUnavailable(
                    "fit-select label material population drift")
            values = (*fit, *epoch_select)
            reuse_root, reuse_materials = _p0_reuse_source(fit, self.freeze)
            label_root = Path(self.freeze.evidence_root) / FIT_SELECT_CONTINUATION_ROOT
            receipt = self.producer(
                label_root, values, split="fit-select", workers=workers,
                deadline_monotonic_ns=_absolute_stage_deadline(
                    supervisor, self.freeze, deadline),
                progress=_label_progress(supervisor, "fit-select-labels", "fit-select"),
                reuse_root=reuse_root, reuse_materials=reuse_materials)
            reopen_continuation_manifest(label_root, values)
            result = _register_or_reopen(supervisor, "fit-select-labels",
                                         receipt.payload())
            supervisor.emit_progress(
                stage="fit-select-labels", substage="fit-select-labels",
                completed=len(values), total=len(values),
                active_workers=0, active_threads=0, sealed_shards=len(values),
                force=True)
            return result
        except StageAdapterUnavailable:
            raise
        except Exception as exc:
            raise StageAdapterUnavailable(
                "fit-select labels producer refused") from exc


def p0_labels_gates_adapter(*, freeze: Any, repo: Path) -> P0LabelsGatesAdapterV2:
    _read_stage_config(repo, freeze, P0_INPUT_SCHEMA)
    return P0LabelsGatesAdapterV2(freeze, repo)


def optimizer_canary_adapter(*, freeze: Any, repo: Path) -> OptimizerCanaryAdapterV2:
    _read_stage_config(repo, freeze, OPTIMIZER_INPUT_SCHEMA)
    return OptimizerCanaryAdapterV2(freeze, repo)


def nested_curve_adapter(*, freeze: Any, repo: Path) -> Any:
    return production_training_stage_adapter(
        "nested-curve", freeze=freeze, repo=repo)


def fit_select_labels_adapter(*, freeze: Any, repo: Path) -> FitSelectLabelsAdapterV2:
    _read_stage_config(repo, freeze, STAGE_INPUT_SCHEMA)
    return FitSelectLabelsAdapterV2(freeze, repo)


def production_stage_adapter(stage: str, *, freeze: Any,
                             repo: Path) -> Any:
    """Return only an implemented closed adapter for ``stage``."""
    if type(stage) is not str or not stage:
        raise StageAdapterUnavailable("stage adapter stage drift")
    if freeze is None or repo is None:
        raise StageAdapterUnavailable("stage adapter requires freeze and repo")
    factories = {
        "population": population_collection_adapter,
        "p0-labels-gates": p0_labels_gates_adapter,
        "optimizer-canary": optimizer_canary_adapter,
        "fit-select-labels": fit_select_labels_adapter,
    }
    factory = factories.get(stage)
    if factory is not None:
        return factory(freeze=freeze, repo=repo)
    if stage in {
            "block-1-natural", "nested-curve", "block-1-controls",
            "block-2-natural", "block-2-controls"}:
        return production_training_stage_adapter(
            stage, freeze=freeze, repo=repo)
    if stage in {
            "precision-select-power", "audit-attempt", "terminal",
            "reconstruction"}:
        return production_late_stage_adapter(
            stage, freeze=freeze, repo=repo)
    raise StageAdapterUnavailable(
        f"stage adapter unavailable for {stage}: no composed producer")


__all__ = [
    "ABI", "INPUT_SCHEMA", "POPULATION_INPUT_SCHEMA",
    "PopulationCollectionAdapterV2", "PopulationReopenAdapterV2",
    "PopulationProductionAdapterV2",
    "P0_INPUT_SCHEMA", "OPTIMIZER_INPUT_SCHEMA", "NESTED_INPUT_SCHEMA",
    "P0LabelsGatesAdapterV2", "OptimizerCanaryAdapterV2",
    "FitSelectLabelsAdapterV2", "p0_labels_gates_adapter",
    "optimizer_canary_adapter", "nested_curve_adapter",
    "fit_select_labels_adapter", "build_fit_select_continuations_v2",
    "production_stage_adapter",
    "evaluate_precision_select_v2", "publish_audit_attempt",
    "StageAdapterUnavailable", "population_collection_adapter",
    "population_reopen_adapter", "population_production_adapter",
    "population_adapter",
]
