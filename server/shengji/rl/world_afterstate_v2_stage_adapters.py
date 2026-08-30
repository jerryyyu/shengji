"""Closed adapters from the execution ABI to reviewed V2 controllers.

Only adapters with a published, typed input envelope are executable.  This
module intentionally contains a reopen-only population adapter: the current
branch has no safe population-input envelope for fresh collection, so it can
recover an already sealed controller receipt but cannot invent one.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .belief_contract import canonical_json_bytes


ABI = "world-afterstate-v2-stage-adapter-supervisor-shards-v1"
INPUT_SCHEMA = "world-afterstate-v2-population-adapter-input-v1"


class StageAdapterUnavailable(ValueError):
    """A reviewed low-level producer has no composed typed adapter."""


def _sha(raw: bytes) -> str:
    import hashlib
    return hashlib.sha256(raw).hexdigest()


def _read_input(path: Path, *, expected_digest: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise StageAdapterUnavailable("population adapter input artifact missing")
    raw = path.read_bytes()
    if _sha(raw) != expected_digest:
        raise StageAdapterUnavailable("population adapter input artifact drift")
    try:
        value = json.loads(raw.decode("ascii"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StageAdapterUnavailable("population adapter input is not JSON") from exc
    if type(value) is not dict or canonical_json_bytes(value) != raw:
        raise StageAdapterUnavailable("population adapter input is not canonical")
    required = {"schema", "population_namespace_sha256", "max_attempts_per_slot"}
    if set(value) != required or value["schema"] != INPUT_SCHEMA:
        raise StageAdapterUnavailable("population adapter input schema unavailable")
    namespace = value["population_namespace_sha256"]
    if type(namespace) is not str or len(namespace) != 64 \
            or any(char not in "0123456789abcdef" for char in namespace):
        raise StageAdapterUnavailable("population adapter namespace drift")
    cap = value["max_attempts_per_slot"]
    if type(cap) is not int or cap < 1:
        raise StageAdapterUnavailable("population adapter attempt cap drift")
    return value


@dataclass(frozen=True)
class PopulationReopenAdapterV2:
    """Supervisor ABI adapter for the existing population reopen boundary."""

    freeze: Any
    repo: Path
    producer: Any
    __world_afterstate_v2_stage_adapter__: str = ABI

    def __call__(self, supervisor: Any, verified_shards: tuple[str, ...]) -> Any:
        del verified_shards
        binding = next((row for row in self.freeze.artifact_bindings
                        if row[0] == "population"), None)
        if binding is None:
            raise StageAdapterUnavailable("population adapter artifact binding missing")
        value = _read_input(self.repo / binding[1], expected_digest=binding[2])
        return self.producer(
            supervisor.root,
            freeze_sha256=self.freeze.sha256(),
            population_namespace_sha256=value["population_namespace_sha256"],
            admission_sha256=supervisor.admission.sha256(),
            max_attempts_per_slot=value["max_attempts_per_slot"])


def population_reopen_adapter(*, freeze: Any, repo: Path) -> PopulationReopenAdapterV2:
    from .world_afterstate_v2_population_controller import (
        reopen_population_collection_v2,
    )
    binding = next((row for row in freeze.artifact_bindings if row[0] == "population"), None)
    if binding is None:
        raise StageAdapterUnavailable("population adapter artifact binding missing")
    _read_input(repo / binding[1], expected_digest=binding[2])
    return PopulationReopenAdapterV2(freeze, repo, reopen_population_collection_v2)


__all__ = ["ABI", "INPUT_SCHEMA", "PopulationReopenAdapterV2",
           "StageAdapterUnavailable", "population_reopen_adapter"]
