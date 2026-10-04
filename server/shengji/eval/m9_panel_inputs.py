"""Load the panel's retained analysis and public fixtures from pinned bytes.

This is an input boundary for an authenticated worker, NOT its bootstrap or
launch guard. It never constructs models, samples worlds, runs a collection,
or accepts science. Source/runtime, model identity, ownership, RELEASE and
deadlines remain the outer worker/admission packet's responsibility.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass
import hashlib
from pathlib import Path

from . import observation_queue as guards
from .m9_panel_plan import ROOTS, build_m9_panel_plan
from .m9_panel_recipe import validate_panel_recipe
from .m9_panel_readout import _saved_choices
from .observation_lease import file_stamp


MAX_INPUT_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True)
class LoadedPanelInputs:
    analysis: dict
    fixtures: tuple
    input_sha256: dict[str, str]
    _stamps: tuple[tuple[Path, tuple[int, int, int, int, int]], ...]

    def check_unchanged(self) -> None:
        """Cheap metadata recheck; not a fresh hash or adversarial race fence."""
        for path, mark in self._stamps:
            if file_stamp(path) != mark:
                raise ValueError(f"panel input changed after authentication: {path}")


def _parse_utf8(raw: bytes) -> dict:
    # json.loads(bytes) also accepts UTF16/32; panel files require UTF8.
    return guards._parse_finite_object(raw.decode("utf-8"))


def load_panel_inputs(recipe) -> LoadedPanelInputs:
    """Authenticate both inputs before parsing either; retain loaded objects.

    Parsing uses the exact buffered bytes whose SHA was checked, never a
    second path-open. Returned objects are detached from the recipe but are
    not immutable science seals. The worker must protect its own state and
    call check_unchanged at its existing dispatch checkpoints.
    """
    spec = copy.deepcopy(recipe)
    validate_panel_recipe(spec)
    buffers, stamps, hashes = {}, [], {}
    for key, sha_key in (("saved_readout", "saved_readout_sha256"),
                         ("fixtures", "fixture_sha256")):
        path = guards._canonical_absolute(spec[key], key)
        raw, mark = guards._stable_read(path, MAX_INPUT_BYTES)
        digest = hashlib.sha256(raw).hexdigest()
        if digest != spec[sha_key]:
            raise ValueError(f"panel {key} hash mismatch")
        buffers[key] = raw
        stamps.append((path, mark))
        hashes[key] = digest
    readout = _parse_utf8(buffers["saved_readout"])
    if (set(readout) != {"analysis", "provenance"}
            or type(readout["analysis"]) is not dict
            or type(readout["provenance"]) is not dict):
        raise ValueError("exact saved readout analysis/provenance objects required")
    analysis = readout["analysis"]
    for job in build_m9_panel_plan(analysis):
        _saved_choices(analysis, job)  # refuse an unusable later reader join now
    from .tactical import OBSERVATION_CATEGORY, fixture_from_json

    fixtures = []
    for line in buffers["fixtures"].decode("utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        fixtures.append(fixture_from_json(_parse_utf8(line.encode("utf-8"))))
    ids = [fixture.id for fixture in fixtures]
    if len(ids) != len(ROOTS) or set(ids) != set(ROOTS):
        raise ValueError("exact four M9 fixture ids required")
    if any(fixture.category != OBSERVATION_CATEGORY or fixture.current_bot is not None
           for fixture in fixtures):
        raise ValueError("public observation fixtures without correctness labels required")
    loaded = LoadedPanelInputs(analysis, tuple(fixtures), hashes, tuple(stamps))
    loaded.check_unchanged()
    return loaded


__all__ = ["LoadedPanelInputs", "load_panel_inputs"]
