"""Linux-only isolated S10 CLI integration with a staged synthetic identity.

The staged checkout is test-owned: its recipe/model/fixture/saved-readout
identity constants are rebound to a tiny synthetic package and bundle. The
repository production constants and source are never changed. Historical
collection controls remain the separate synthetic witnesses made by the
authenticated-bundle helper; only the new rank runtime is captured from the
staged source and repinned before the CLI run.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import pytest

from scripts import panel_rank_worker as worker
from shengji.eval import m9_panel_plan, m9_panel_recipe, observation_runtime, tactical

from test_cwv_puct_package_prior import _write_joint_package
from test_panel_rank_worker_authenticated_integration import (
    _complete_authenticated_bundle,
)
import test_panel_rank_worker_reader_integration as reader_fixture
import test_m9_panel_plan
import test_m9_panel_readout


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode()


def _pin(path: Path, value: object) -> dict[str, str]:
    raw = _canonical(value)
    path.write_bytes(raw)
    return {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest()}


def _source_inventory(server: Path) -> dict[str, str]:
    return {
        path.relative_to(server).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for folder in ("scripts", "shengji")
        for path in (server / folder).rglob("*")
        if path.is_file() and path.suffix in (".py", ".so")
    }


def _stage_server(tmp_path: Path, identity: dict[str, str]) -> Path:
    source = Path(worker.__file__).parents[1]
    staged = tmp_path / "staged" / "server"
    for directory in ("scripts", "shengji"):
        shutil.copytree(source / directory, staged / directory,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))

    recipe_path = staged / "shengji" / "eval" / "m9_panel_recipe.py"
    recipe = recipe_path.read_text()
    recipe, count = re.subn(
        r'(?m)^SAVED_READOUT_SHA256 = "[0-9a-f]{64}"$',
        f'SAVED_READOUT_SHA256 = "{identity["saved"]}"', recipe)
    if count != 1:
        raise AssertionError("saved-readout identity assignment changed")
    marker = "    FIXTURE_SHA256, MODEL_SHA256, _absolute_normalized, _overlaps,\n)"
    replacement = (marker + "\n\n# Test-only staged synthetic identity; production constants are untouched.\n"
                   f'MODEL_SHA256 = "{identity["model"]}"\n'
                   f'FIXTURE_SHA256 = "{identity["fixture"]}"')
    if marker not in recipe:
        raise AssertionError("m9 panel recipe import marker changed")
    recipe_path.write_text(recipe.replace(marker, replacement))

    plan_path = staged / "shengji" / "eval" / "m9_panel_plan.py"
    plan = plan_path.read_text()
    plan, count = re.subn(
        r'(?m)^CHECKPOINT_SHA256 = "[0-9a-f]{64}"$',
        f'CHECKPOINT_SHA256 = "{identity["model"]}"', plan)
    if count != 1:
        raise AssertionError("checkpoint identity assignment changed")
    plan_path.write_text(plan)
    return staged


def _capture_current_runtime(tmp_path: Path, staged: Path, env: dict[str, str]):
    inventory = _source_inventory(staged)
    baseline = _pin(tmp_path / "rank-baseline.json", {
        "schema": "shengji-m9-runtime-v1",
        "source_root": str(staged),
        "source_files": inventory,
        "environment": dict(observation_runtime.ENVIRONMENT),
    })
    command = [sys.executable, "-I", "-B", str(staged / "scripts" / "panel_rank_worker.py")]
    bootstrap_sha = inventory["scripts/m9_panel_readout_worker.py"]
    helper_sha = inventory["scripts/observation_worker.py"]
    captured = tmp_path / "captured-rank-runtime.json"
    result = subprocess.run(
        command + ["--capture-runtime", baseline["path"], baseline["sha256"],
                   bootstrap_sha, helper_sha, str(captured)],
        env=env, capture_output=True, text=True, timeout=180)
    assert result.returncode == 0, result.stderr
    return ({"path": str(captured),
             "sha256": hashlib.sha256(captured.read_bytes()).hexdigest()},
            bootstrap_sha, helper_sha)


def _repin_rank_runtime(bundle: dict, runtime_pin: dict[str, str]) -> None:
    spec = bundle["spec"]
    spec["runtime"] = runtime_pin
    invocation_pin = _pin(Path(bundle["invocation_pin"]["path"]), spec)
    release_pin = _pin(Path(bundle["release_pin"]["path"]), {
        "schema": "panel-rank-release-v1", "decision": "RELEASE",
        "invocation_sha256": invocation_pin["sha256"],
        "ownership_dir": spec["ownership_dir"],
        "packet_sha256": spec["packet_sha256"], "index": spec["index"],
    })
    bundle["invocation_pin"] = invocation_pin
    bundle["release_pin"] = release_pin


@pytest.mark.skipif(not sys.platform.startswith("linux"),
                    reason="requires isolated Linux subprocess")
@pytest.mark.parametrize("drift", [False, True])
def test_real_isolated_rank_cli_success_and_runtime_drift(tmp_path, monkeypatch, drift):
    if not list((Path(worker.__file__).parents[1] / "shengji" / "engine").glob("_fast*.so")):
        pytest.skip("compiled native engine required")

    # Build the retained reader witness around a tiny real NumPy package. The
    # monkeypatches here only prepare test-owned bytes; the subprocess below
    # imports and executes the staged source without monkeypatches.
    model_path = tmp_path / "tiny-joint.npz"
    model_sha = _write_joint_package(model_path, 3)
    for module in (m9_panel_plan, test_m9_panel_plan,
                   test_m9_panel_readout, reader_fixture):
        monkeypatch.setattr(module, "CHECKPOINT_SHA256", model_sha)
    env_for_bot = tactical.observation_comparison_environs(
        str(model_path), model_sha)[m9_panel_recipe.POLICY]
    _, supplied_bot = tactical.bot_from_environ(env_for_bot, seed=0)
    bundle = _complete_authenticated_bundle(
        tmp_path, monkeypatch, supplied_bot=supplied_bot,
        model_bytes=model_path.read_bytes())

    recipe = bundle["packet"]["recipe"]
    identity = {
        "model": recipe["model_sha256"],
        "fixture": recipe["fixture_sha256"],
        "saved": recipe["saved_readout_sha256"],
    }
    staged = _stage_server(tmp_path, identity)
    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("SHENGJI_", "PYTHON", "OMP_", "OPENBLAS_",
                                  "MKL_", "VECLIB_", "NUMEXPR_", "LC_",
                                  "LD_", "DYLD_", "BLIS_", "GOTO_", "KMP_"))}
    env.update({"SHENGJI_FAST": "1", "OMP_NUM_THREADS": "1",
                "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
                "VECLIB_MAXIMUM_THREADS": "1", "NUMEXPR_NUM_THREADS": "1",
                "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"})
    runtime_pin, bootstrap_sha, helper_sha = _capture_current_runtime(
        tmp_path, staged, env)
    _repin_rank_runtime(bundle, runtime_pin)

    if drift:
        target = staged / "shengji" / "eval" / "panel_rank_root.py"
        target.write_bytes(target.read_bytes() + b"\n# test-only current source drift\n")

    args = [str(staged / "scripts" / "panel_rank_worker.py"),
            bundle["invocation_pin"]["path"], bundle["invocation_pin"]["sha256"],
            bundle["release_pin"]["path"], bundle["release_pin"]["sha256"],
            bootstrap_sha, helper_sha]
    result = subprocess.run([sys.executable, "-I", "-B", *args], env=env,
                            capture_output=True, text=True, timeout=180)
    output = Path(bundle["spec"]["output_dir"])
    ownership = Path(bundle["spec"]["ownership_dir"])
    if drift:
        assert result.returncode != 0
        assert "ValueError" in result.stderr
        assert not output.exists()
        assert not ownership.exists()
        return

    assert result.returncode == 0, result.stderr
    result_path = output / "result.json"
    receipt_path = output / "receipt.json"
    published = json.loads(result_path.read_bytes())
    receipt = json.loads(receipt_path.read_bytes())
    assert set(published["projections"]) == {"control", "treatment"}
    assert receipt["result_sha256"] == hashlib.sha256(result_path.read_bytes()).hexdigest()
    assert receipt["provenance_verified"] is False
    assert receipt["model_sha256"] == bundle["packet"]["recipe"]["model_sha256"]
    assert receipt["fixture_sha256"] == bundle["packet"]["recipe"]["fixture_sha256"]
    assert receipt["runtime"] == bundle["spec"]["runtime"]
    assert receipt["release"] == bundle["release_pin"]
    assert not (output / "refusal.json").exists()
