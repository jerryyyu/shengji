"""Pure input binding for the fixed M9 follow-up panel, not admission.

Unlike the original tactical comparison, this recipe names an already-read
analysis file and an exclusive output DIRECTORY. No filesystem, model, worker,
or process is accessed here. A separately reviewed packet must authenticate
these bytes/paths and bind source, runtime, deadlines, ownership and RELEASE.
"""
from __future__ import annotations

from collections.abc import Mapping

from .observation_recipe import (
    FIXTURE_SHA256, MODEL_SHA256, _absolute_normalized, _overlaps,
)


SCHEMA = "m9-panel-recipe-v1"
SAVED_READOUT_SHA256 = "de870f2f2a77377303d8bf476fa6d2654d532a7502bb77985834def6e6ee2a5c"
POLICY = "div+rc+tb+la"
_PATHS = ("python", "source_root", "model", "fixtures", "saved_readout",
          "output_dir", "evidence")
_KEYS = frozenset((*_PATHS, "schema", "model_sha256", "fixture_sha256",
                   "saved_readout_sha256", "seeds", "fill_seed",
                   "runtime_profile", "policy"))


def validate_panel_recipe(recipe: Mapping[str, object]) -> None:
    """Bind the fixed population inputs; do not infer execution authority."""
    if not isinstance(recipe, Mapping) or set(recipe) != _KEYS:
        raise ValueError("exact M9 panel recipe keys required")
    pins = {
        "schema": SCHEMA,
        "model_sha256": MODEL_SHA256,
        "fixture_sha256": FIXTURE_SHA256,
        "saved_readout_sha256": SAVED_READOUT_SHA256,
        "runtime_profile": "panel",
        "policy": POLICY,
    }
    for key, expected in pins.items():
        if type(recipe[key]) is not str or recipe[key] != expected:
            raise ValueError(f"panel {key} differs from frozen recipe")
    if (type(recipe["seeds"]) is not list or recipe["seeds"] != [0, 1, 2]
            or any(type(seed) is not int for seed in recipe["seeds"])):
        raise ValueError("panel seeds must be exactly [0, 1, 2]")
    if type(recipe["fill_seed"]) is not int or recipe["fill_seed"] != 0:
        raise ValueError("panel fill_seed must be exactly 0")
    paths = {key: _absolute_normalized(recipe[key], key) for key in _PATHS}
    inputs = [paths[key] for key in _PATHS[:-2]]
    output, evidence = paths["output_dir"], paths["evidence"]
    if _overlaps(output, evidence):
        raise ValueError("panel output directory overlaps process evidence")
    for generated in (output, evidence):
        if any(_overlaps(generated, source) for source in inputs):
            raise ValueError("panel publication overlaps an input")


def panel_model_environ(recipe: Mapping[str, object]) -> dict[str, str]:
    """Return the frozen refusal-enabled treatment environment, no model load.

    Both fresh and history-primed tapes use this recipe: fresh refusal history
    is empty by construction, not by turning the refusal rule off. The outer
    worker must pass an explicit seed to tactical.bot_from_environ and use its
    bot result (not the returned name/bot tuple), once per factory invocation.
    """
    validate_panel_recipe(recipe)
    from .tactical import observation_comparison_environs

    return observation_comparison_environs(
        str(recipe["model"]), MODEL_SHA256)[POLICY]


__all__ = ["SCHEMA", "SAVED_READOUT_SHA256", "POLICY",
           "validate_panel_recipe", "panel_model_environ"]
