"""Profile-isolation tests for the expanded Stage-C composition wrappers."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "server" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import teacher_stage_c_composition_controller as BASE  # noqa: E402


def _python(code: str, **environment: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env.update(environment)
    env["PYTHONPATH"] = os.pathsep.join((
        str(ROOT / "server"), str(SCRIPTS), env.get("PYTHONPATH", "")))
    return subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, env=env,
        capture_output=True, text=True, check=False)


def test_expanded_controller_profile_is_namespaced_and_uses_wrappers():
    result = _python(
        "import json; import teacher_stage_c_expanded_composition_controller "
        "as c; print(json.dumps({'schema':c.SCHEMA,'run':c.RUN_ID,"
        "'report':c.REPORT_CTRL.__name__,'runtime':c.RUNTIME_SCRIPT_PATH,"
        "'sources':list(c.SOURCE_PATHS),'commands':c._commands(),"
        "'receipt':c.RUNTIME_RECEIPT_SCHEMA},sort_keys=True))")
    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    assert value["schema"] \
        == "teacher-stage-c-expanded-composition-screen-controller-v1"
    assert value["run"] \
        == "teacher-v3-hard-tail-stage-c-expanded-composition-screen-v1"
    assert value["report"] == "teacher_stage_c_expanded_report_controller"
    assert value["runtime"] \
        == "server/scripts/teacher_stage_c_expanded_composition_runtime.py"
    assert value["receipt"] \
        == "teacher-stage-c-expanded-composition-screen-receipt-v1"
    assert value["runtime"] in value["sources"]
    assert "server/scripts/teacher_stage_c_expanded_composition_controller.py" \
        in value["sources"]
    assert value["commands"]["capacity_preflight"][1] == value["runtime"]
    assert value["commands"]["supervise"][1] == value["runtime"]
    assert all(command[1] == value["runtime"] for command in
               value["commands"]["supervisor_child_shards"])


def test_expanded_runtime_imports_only_the_expanded_profile():
    result = _python(
        "import json; import teacher_stage_c_expanded_composition_runtime as "
        "w; r=w.BASE; print(json.dumps({'controller':r.CTRL.__name__,"
        "'schema':r.CTRL.SCHEMA,'admission':r.ADMISSION_SCHEMA,"
        "'aggregate':r.AGGREGATE_SCHEMA},sort_keys=True))")
    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    assert value == {
        "controller": "teacher_stage_c_expanded_composition_controller",
        "schema": "teacher-stage-c-expanded-composition-screen-controller-v1",
        "admission": "teacher-stage-c-expanded-composition-screen-admission-v1",
        "aggregate": "teacher-stage-c-expanded-composition-screen-result-v1",
    }


@pytest.mark.parametrize(("variable", "value", "module", "message"), (
    ("SHENGJI_STAGE_C_COMPOSITION_PROFILE", "unreviewed-profile",
     "teacher_stage_c_composition_controller",
     "unrecognized Stage-C composition profile"),
    ("SHENGJI_STAGE_C_REPORT_CONTROLLER", "pathlib",
     "teacher_stage_c_composition_controller",
     "unrecognized Stage-C composition REPORT controller"),
    ("SHENGJI_STAGE_C_COMPOSITION_CONTROLLER", "pathlib",
     "teacher_stage_c_composition_runtime",
     "unrecognized Stage-C composition controller module"),
))
def test_unknown_dynamic_profile_or_module_refuses_before_import(
    variable: str, value: str, module: str, message: str,
):
    result = _python(f"import {module}", **{variable: value})
    assert result.returncode != 0
    assert message in result.stderr


@pytest.mark.parametrize("environment", (
    {"SHENGJI_STAGE_C_COMPOSITION_PROFILE": "expanded-bury"},
    {"SHENGJI_STAGE_C_REPORT_CONTROLLER":
     "teacher_stage_c_expanded_report_controller"},
))
def test_composition_and_report_profiles_must_change_together(environment):
    result = _python(
        "import teacher_stage_c_composition_controller", **environment)
    assert result.returncode != 0
    assert "composition/report controller profiles disagree" in result.stderr


def test_external_checkpoint_root_requires_exact_clean_git(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    root = tmp_path / "training"
    root.mkdir()

    def clean_git(argv, *, cwd, check, capture_output, text):
        assert Path(cwd) == root
        assert check and capture_output and text
        return SimpleNamespace(
            stdout="abc123\n" if argv[1:3] == ["rev-parse", "HEAD"] else "")

    monkeypatch.setattr(BASE.subprocess, "run", clean_git)
    packet = {"parents": {"training_evidence": {
        "absolute_path": str(root), "git": "abc123"}}}
    assert BASE._checkpoint_root(packet) == root.resolve()

    def dirty_git(argv, *, cwd, check, capture_output, text):
        return SimpleNamespace(
            stdout="abc123\n" if argv[1:3] == ["rev-parse", "HEAD"]
            else " M checkpoint\n")

    monkeypatch.setattr(BASE.subprocess, "run", dirty_git)
    with pytest.raises(BASE.CompositionControllerRefused,
                       match="training-evidence Git drift"):
        BASE._checkpoint_root(packet)


def test_legacy_packet_keeps_local_checkpoint_root():
    assert BASE._checkpoint_root({"parents": {}}) == BASE.REPO


def test_checkpoint_manifest_cannot_escape_external_evidence_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(BASE, "_checkpoint_root", lambda _packet: tmp_path)
    monkeypatch.setattr(BASE, "MODEL_PATHS", ("unused-export.npz",))
    packet = {
        "selected_capability": {"surface": "bury"},
        "checkpoint_manifest": [{"checkpoint_path": "../outside.pt"}],
    }
    with pytest.raises(BASE.CompositionControllerRefused,
                       match="escapes evidence root"):
        BASE._export_models(packet, verify=False)
