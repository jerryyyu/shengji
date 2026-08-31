from __future__ import annotations

import os
import runpy
import subprocess
import sys
from pathlib import Path

import pytest


def test_multiprocessing_reentry_scans_bytecode_before_project_import():
    server = Path(__file__).parents[1]
    script = (server / "scripts" / "world_afterstate_v2_run.py").resolve()
    cache = server / "shengji" / "rl" / "__pycache__"
    shadow = cache / "spawn-shadow.pyc"
    cache.mkdir(exist_ok=True)
    shadow.write_bytes(b"unchecked-shadow")
    prior_fast = os.environ.get("SHENGJI_FAST")
    prior_voids = os.environ.get("SHENGJI_REQUIRE_VOIDS")
    os.environ["SHENGJI_FAST"] = "1"
    os.environ["SHENGJI_REQUIRE_VOIDS"] = "1"
    try:
        with pytest.raises(
                RuntimeError,
                match="scientific execution refuses source bytecode"):
            runpy.run_path(str(script), run_name="__mp_main__")
    finally:
        if prior_fast is None:
            os.environ.pop("SHENGJI_FAST", None)
        else:
            os.environ["SHENGJI_FAST"] = prior_fast
        if prior_voids is None:
            os.environ.pop("SHENGJI_REQUIRE_VOIDS", None)
        else:
            os.environ["SHENGJI_REQUIRE_VOIDS"] = prior_voids
        shadow.unlink(missing_ok=True)
        try:
            cache.rmdir()
        except OSError:
            pass


def test_cli_run_and_resume_thread_durable_progress_callback(tmp_path):
    """Exercise the command wrapper's real run/resume constructor paths."""
    script = (Path(__file__).parents[1] / "scripts" /
              "world_afterstate_v2_run.py").resolve()
    freeze = (tmp_path / "freeze.json").resolve()
    freeze.write_bytes(b"probe")
    root = (tmp_path / "evidence").resolve()
    probe = f'''\
import argparse, runpy
ns = runpy.run_path({str(script)!r}, run_name="cli_progress_probe")
seen = []
class Freeze: pass
class Admission: pass
freeze = Freeze()
admission = Admission()
class Sink:
    def __init__(self, root, *, freeze, admission):
        seen.append(("sink", root, freeze, admission, self))
ns["execution_freeze_from_bytes"] = lambda raw: freeze
ns["validate_production_stage_set"] = lambda **kwargs: ()
ns["initialize_admission"] = lambda *args, **kwargs: admission
ns["authenticate_review_commit"] = lambda *args, **kwargs: b"marker"
ns["build_admission"] = lambda *args, **kwargs: admission
ns["DurableProgressSinkV2"] = Sink
class Supervisor:
    def __init__(self, *args, **kwargs):
        seen.append(("supervisor", kwargs.get("progress_callback")))
ns["StageSupervisorV2"] = Supervisor
def reopen(*args, **kwargs):
    seen.append(("reopen", kwargs.get("progress_callback")))
    return Supervisor()
ns["reopen_supervisor"] = reopen
ns["production_stage_controllers"] = lambda **kwargs: {{}}
def pipeline(supervisor, operations):
    seen.append(("pipeline", supervisor, operations))
ns["run_v2_pipeline"] = pipeline
# runpy returns a namespace copy on some Python versions; update the function
# globals as well so this probe exercises the wrapper functions themselves.
globals_ = ns["_run"].__globals__
globals_.update({{key: value for key, value in ns.items()
                  if key in ("execution_freeze_from_bytes",
                             "validate_production_stage_set",
                             "initialize_admission",
                             "authenticate_review_commit",
                             "build_admission", "DurableProgressSinkV2",
                             "StageSupervisorV2", "reopen_supervisor",
                             "production_stage_controllers", "run_v2_pipeline")}})
args = argparse.Namespace(freeze={str(freeze)!r}, root={str(root)!r},
    review_commit="review", canonical_ref="ref", remote_url="remote")
ns["_run"](args)
ns["_resume"](args)
assert seen[0][0] == "sink" and seen[1] == ("supervisor", seen[0][4])
assert seen[2][0] == "pipeline"
assert seen[3][0] == "sink" and seen[4] == ("reopen", seen[3][4])
assert seen[5][0] == "supervisor" and seen[6][0] == "pipeline"
'''
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env["SHENGJI_FAST"] = "1"
    env["SHENGJI_REQUIRE_VOIDS"] = "1"
    subprocess.run((sys.executable, "-P", "-B", "-c", probe),
                   check=True, env=env)
