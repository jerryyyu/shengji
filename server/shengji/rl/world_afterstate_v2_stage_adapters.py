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


ABI = "world-afterstate-v2-stage-adapter-supervisor-shards-v1"
INPUT_SCHEMA = "world-afterstate-v2-population-adapter-input-v2"
POPULATION_INPUT_SCHEMA = INPUT_SCHEMA
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


__all__ = [
    "ABI", "INPUT_SCHEMA", "POPULATION_INPUT_SCHEMA",
    "PopulationCollectionAdapterV2", "PopulationReopenAdapterV2",
    "PopulationProductionAdapterV2",
    "StageAdapterUnavailable", "population_collection_adapter",
    "population_reopen_adapter", "population_production_adapter",
    "population_adapter",
]
