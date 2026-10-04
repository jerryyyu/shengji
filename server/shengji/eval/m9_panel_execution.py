"""Fixed panel child body for an already authenticated, admitted process.

No CLI, bootstrap, owner claim, RELEASE creation, retry or lease management.
The outer worker must authenticate this source before import and supply its
live admission guard and deadline callback. Calling this with real inputs is
scientific collection and requires the reviewed packet and external RELEASE.
"""
from __future__ import annotations

import copy
from pathlib import Path
import sys

from . import tactical
from .m9_panel_inputs import load_panel_inputs
from .m9_panel_persistence import run_m9_panel_collection
from .m9_panel_recipe import panel_model_environ, validate_panel_recipe
from .observation_admission import _hash_file
from .observation_lease import file_stamp
from .observation_queue import _canonical_absolute
from .observation_runtime import ObservationRuntime


def run_panel_body(recipe, runtime_manifest, *, check_admission, check_budget):
    """Run once after admission, retaining persistence's partial evidence.

    check_admission must return exactly True or raise; it owns the packet's
    live claim/RELEASE/lease/queue gates. check_budget must raise on expiry.
    Runtime/input/model checks happen before each model construction and after
    collection. Inner scoring uses only the cheap deadline callback. Neither
    collection terminal='complete' nor a returned receipt accepts the science.
    """
    if not callable(check_admission) or not callable(check_budget):
        raise ValueError("explicit admission guard and deadline callback required")

    def admission():
        check_budget()
        if check_admission() is not True:
            raise ValueError("panel live admission guard refused")

    admission()
    spec = copy.deepcopy(recipe)
    validate_panel_recipe(spec)
    manifest = copy.deepcopy(runtime_manifest)
    if (type(manifest) is not dict
            or manifest.get("source_root") != str(Path(spec["source_root"]) / "server")):
        raise ValueError("panel runtime source binding mismatch")
    if Path(spec["python"]).resolve() != Path(sys.executable).resolve():
        raise ValueError("panel interpreter binding mismatch")
    runtime = ObservationRuntime(manifest, profile="panel")
    loaded = load_panel_inputs(spec)
    model = _canonical_absolute(spec["model"], "model")
    digest, model_stamp = _hash_file(model)
    if digest != spec["model_sha256"]:
        raise ValueError("panel model hash mismatch")
    environment = panel_model_environ(spec)

    def checkpoint():
        admission()
        loaded.check_unchanged()
        if file_stamp(model) != model_stamp:
            raise ValueError("panel model changed after authentication")
        if not runtime.check():
            raise ValueError("panel runtime drift")

    def factory(seed):
        if type(seed) is not int or seed not in (0, 1, 2):
            raise ValueError("fixed panel seed required")
        checkpoint()
        _name, bot = tactical.bot_from_environ(dict(environment), seed=seed)
        checkpoint()
        return bot

    checkpoint()
    output = _canonical_absolute(spec["output_dir"], "panel output directory")
    # Persistence exclusively mkdirs this path before invoking any factory;
    # an occupied output never starts another collection and is not repaired.
    result = run_m9_panel_collection(
        loaded.analysis, loaded.fixtures, factory, output_dir=output,
        check_budget=check_budget)
    checkpoint()
    return result


__all__ = ["run_panel_body"]
