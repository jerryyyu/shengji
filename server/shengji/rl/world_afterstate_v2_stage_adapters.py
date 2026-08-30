"""Closed adapters from the execution ABI to reviewed V2 controllers.

The population adapter is the one production adapter currently available.  Its
configuration is an authenticated, freeze-bound input artifact; callers do
not provide a driver or override any of the frozen values.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .belief_artifacts import stable_read_bytes
from .belief_contract import canonical_json_bytes
from .world_afterstate_v2_population_controller import (
    WORKER_ARMS, collect_population_v2,
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
from .world_afterstate_v2_protocol import (
    TIER_SPECS, build_population_slot_ledger, select_p0_population)
from .world_afterstate_v2_p0_mechanics import build_engine_p0_mechanics_evidence
from .world_afterstate_v2_reopen import (
    reopen_optimizer_canary_v2,
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
_STAGE_CONFIG_FIELDS = frozenset({
    "schema", "artifact_root", "population_namespace_sha256",
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


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise StageAdapterUnavailable("population input duplicate key")
        value[key] = item
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


def _natural_fit_inputs(supervisor: Any, freeze: Any, repo: Path,
                        schema: str) -> tuple[Any, ...]:
    """Reopen the exact natural-fit materials and continuations from root."""
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
        bundles = reopen_continuation_manifest(root, materials)
    except StageAdapterUnavailable:
        raise
    except Exception as exc:
        raise StageAdapterUnavailable("P0 sealed input reopen refused") from exc
    if len(materials) != 128 or len(bundles) != 128:
        raise StageAdapterUnavailable("P0 natural-fit input population drift")
    return tuple(zip(materials, bundles, strict=True))


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
            return self.producer(
                supervisor.root, freeze_sha256=freeze_sha,
                population_namespace_sha256=config["population_namespace_sha256"],
                admission_sha256=admission_sha,
                max_attempts_per_slot=config["max_attempts_per_slot"],
                workers=config["workers"], deadline_seconds=config["deadline_seconds"],
                heartbeat_seconds=config["heartbeat_seconds"],
                progress_callback=progress)
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
        if supervisor.verified_shards("p0-labels-gates"):
            return _register_or_reopen(supervisor, "p0-labels-gates", {})
        supervisor.emit_progress(stage="p0-labels-gates", completed=0, total=1, force=True)
        try:
            pairs = _natural_fit_inputs(supervisor, self.freeze, self.repo,
                                        P0_INPUT_SCHEMA)
            all_materials = tuple(material for material, _bundle in pairs)
            selected_states = select_p0_population(
                tuple(item.state for item in all_materials), tier=TIER_SPECS[0])
            selected_deals = {state.deal_sha256 for state in selected_states}
            # The population producer seals 128 natural-fit rows.  P0 is the
            # frozen 96-deal canonical subset, selected by the reviewed
            # outcome-blind protocol helper.
            selected = tuple((material, bundle) for material, bundle in pairs
                             if material.deal_sha256 in selected_deals)
            if len(selected) != 96:
                raise StageAdapterUnavailable("P0 canonical 128-to-96 selection drift")
            materials = tuple(material for material, _bundle in selected)
            bundles = tuple(bundle for _material, bundle in selected)
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
            pairs = _natural_fit_inputs(supervisor, self.freeze, self.repo,
                                        OPTIMIZER_INPUT_SCHEMA)
            population = OptimizerCanaryInputV2(
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


def p0_labels_gates_adapter(*, freeze: Any, repo: Path) -> P0LabelsGatesAdapterV2:
    _read_stage_config(repo, freeze, P0_INPUT_SCHEMA)
    return P0LabelsGatesAdapterV2(freeze, repo)


def optimizer_canary_adapter(*, freeze: Any, repo: Path) -> OptimizerCanaryAdapterV2:
    _read_stage_config(repo, freeze, OPTIMIZER_INPUT_SCHEMA)
    return OptimizerCanaryAdapterV2(freeze, repo)


def nested_curve_adapter(*, freeze: Any, repo: Path) -> Any:
    del freeze, repo
    raise StageAdapterUnavailable(
        "nested curve adapter unavailable: reviewed training/evaluation composition "
        "does not expose a supervisor-bound 25/50/100% prefix boundary")


__all__ = [
    "ABI", "INPUT_SCHEMA", "POPULATION_INPUT_SCHEMA",
    "PopulationCollectionAdapterV2", "PopulationReopenAdapterV2",
    "PopulationProductionAdapterV2",
    "P0_INPUT_SCHEMA", "OPTIMIZER_INPUT_SCHEMA", "NESTED_INPUT_SCHEMA",
    "P0LabelsGatesAdapterV2", "OptimizerCanaryAdapterV2",
    "p0_labels_gates_adapter", "optimizer_canary_adapter", "nested_curve_adapter",
    "StageAdapterUnavailable", "population_collection_adapter",
    "population_reopen_adapter", "population_production_adapter",
    "population_adapter",
]
