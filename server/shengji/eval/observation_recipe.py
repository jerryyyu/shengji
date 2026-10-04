"""Pure binding for the reviewed M9 observation comparison command.

This module only validates an explicit recipe and constructs argv.  It is not
authorization, freshness, admission, symlink, or runtime proof; those checks
belong to the separately reviewed execution wrapper.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping


MODEL_SHA256 = "491ee4bf81abe783d14f1e004d31ceda1ff2679bd2e14b60a5a9fa96b57c2670"
FIXTURE_SHA256 = "448787c517ee85d47369652e5cd0e427f5eed37d808fc345b6ba29f892cdc29e"
SEEDS = (0, 1, 2)
FILL_SEED = 0
TIMEOUT_SECONDS = 600

_PATH_KEYS = ("python", "source_root", "model", "fixtures", "output", "evidence")
_KEYS = frozenset((*_PATH_KEYS, "seeds", "fill_seed", "timeout_seconds",
                   "model_sha256", "fixture_sha256"))


def _absolute_normalized(value: object, name: str) -> Path:
    try:
        raw = os.fspath(value)
    except TypeError as exc:
        raise ValueError(f"{name} must be an absolute normalized path") from exc
    if (not isinstance(raw, str) or not raw or not os.path.isabs(raw)
            or "\x00" in raw or raw.startswith("//")):
        raise ValueError(f"{name} must be an absolute normalized path")
    normalized = os.path.normpath(raw)
    if raw != normalized:
        raise ValueError(f"{name} must not contain dot or dot-dot aliases")
    path = Path(raw)
    if path == Path(path.anchor):
        raise ValueError(f"{name} must not be the filesystem root")
    return path


def _overlaps(left: Path, right: Path) -> bool:
    return left == right or left in right.parents or right in left.parents


def validate_recipe(recipe: Mapping[str, object]) -> None:
    """Validate the exact, pinned recipe mapping without filesystem access."""
    if not isinstance(recipe, Mapping) or set(recipe) != _KEYS:
        raise ValueError(f"recipe keys must be exactly {sorted(_KEYS)!r}")

    paths = {name: _absolute_normalized(recipe[name], name) for name in _PATH_KEYS}
    if type(recipe["seeds"]) not in (list, tuple) \
            or tuple(recipe["seeds"]) != SEEDS \
            or any(type(seed) is not int for seed in recipe["seeds"]):
        raise ValueError("seeds must be exactly [0, 1, 2]")
    if type(recipe["fill_seed"]) is not int or recipe["fill_seed"] != FILL_SEED:
        raise ValueError("fill_seed must be exactly 0")
    if type(recipe["timeout_seconds"]) is not int \
            or recipe["timeout_seconds"] != TIMEOUT_SECONDS:
        raise ValueError("timeout_seconds must be exactly 600")
    if recipe["model_sha256"] != MODEL_SHA256:
        raise ValueError("model_sha256 is not the pinned comparison package")
    if recipe["fixture_sha256"] != FIXTURE_SHA256:
        raise ValueError("fixture_sha256 is not the pinned observation fixture")

    output = paths["output"]
    evidence = paths["evidence"]
    derived = (output, Path(f"{output}.attempt"),
               output.with_name(f".{output.name}.partial"))
    inputs = tuple(paths[name] for name in _PATH_KEYS[:-2])
    if any(_overlaps(evidence, other) for other in inputs):
        raise ValueError("evidence overlaps an input")
    for generated in derived:
        for other in (*inputs, evidence):
            if _overlaps(generated, other):
                raise ValueError("output publication paths overlap an input or evidence")


def build_observation_command(recipe: Mapping[str, object]) -> tuple[str, ...]:
    """Return immutable argv for one pinned comparison recipe.

    Validation here is binding only; it does not authorize execution, establish
    freshness, inspect the host, or prove runtime/model identity.
    """
    validate_recipe(recipe)
    # Copy every caller-owned value before constructing the immutable argv.
    python = str(os.fspath(recipe["python"]))
    source_root = str(os.fspath(recipe["source_root"]))
    model = str(os.fspath(recipe["model"]))
    fixtures = str(os.fspath(recipe["fixtures"]))
    output = str(os.fspath(recipe["output"]))
    script = str(Path(source_root) / "server" / "scripts" / "tactical_report.py")
    return (python, "-I", "-B", script, "--compare-observations", "--ckpt", model,
            "--sha256", MODEL_SHA256, "--fixtures", fixtures, "--compare-seeds",
            "0,1,2", "--compare-fill-seed", "0", "--json", output)


__all__ = ["FIXTURE_SHA256", "FILL_SEED", "MODEL_SHA256", "SEEDS",
           "TIMEOUT_SECONDS", "build_observation_command",
           "validate_recipe"]
