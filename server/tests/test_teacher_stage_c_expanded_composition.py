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
import teacher_stage_c_composition_runtime as RUNTIME  # noqa: E402


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
        "'report':c.REPORT_CTRL.__name__,"
        "'report_runtime':c.REPORT_RUNTIME.CTRL.__name__,"
        "'report_supervisor':c.REPORT_SUPERVISOR.CTRL.__name__,"
        "'runtime':c.RUNTIME_SCRIPT_PATH,"
        "'preflight_seed0':c.PREFLIGHT_SEED0,'screen_seed0':c.SCREEN_SEED0,"
        "'sources':list(c.SOURCE_PATHS),'commands':c._commands(),"
        "'receipt':c.RUNTIME_RECEIPT_SCHEMA},sort_keys=True))")
    assert result.returncode == 0, result.stderr
    value = json.loads(result.stdout)
    assert value["schema"] \
        == "teacher-stage-c-expanded-play-composition-screen-controller-v1"
    assert value["run"] \
        == "teacher-v3-hard-tail-stage-c-expanded-play-composition-screen-v1"
    assert value["report"] \
        == "teacher_stage_c_expanded_play_report_controller"
    assert value["report_runtime"] \
        == "teacher_stage_c_expanded_play_report_controller"
    assert value["report_supervisor"] \
        == "teacher_stage_c_expanded_play_report_controller"
    assert value["runtime"] \
        == "server/scripts/teacher_stage_c_expanded_composition_runtime.py"
    assert value["receipt"] \
        == "teacher-stage-c-expanded-play-composition-screen-receipt-v1"
    assert value["preflight_seed0"] == 184_000_000
    assert value["screen_seed0"] == 185_000_000
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
        "schema":
            "teacher-stage-c-expanded-play-composition-screen-controller-v1",
        "admission":
            "teacher-stage-c-expanded-play-composition-screen-admission-v1",
        "aggregate":
            "teacher-stage-c-expanded-play-composition-screen-result-v1",
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
    {"SHENGJI_STAGE_C_COMPOSITION_PROFILE": "expanded-play"},
    {"SHENGJI_STAGE_C_REPORT_CONTROLLER":
     "teacher_stage_c_expanded_play_report_controller"},
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


def test_external_checkpoint_root_inherits_git_from_capability_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    root = tmp_path / "training"
    root.mkdir()
    capability_path = tmp_path / "capability.json"
    capability = {
        "parents": {"training_evidence": {
            "absolute_path": str(root), "git": "abc123"}},
    }
    capability["packet_sha256"] = BASE.self_hash(
        capability, "packet_sha256")
    capability_path.write_bytes(BASE.canonical_json(capability))
    packet = {"parents": {
        "training_evidence": {"absolute_path": str(root)},
        "capability_packet": {
            "absolute_path": str(capability_path),
            "external_sha256": BASE.sha256_file(capability_path),
            "internal_sha256": capability["packet_sha256"],
        },
    }}

    def clean_git(argv, *, cwd, check, capture_output, text):
        assert Path(cwd) == root
        assert check and capture_output and text
        return SimpleNamespace(
            stdout="abc123\n" if argv[1:3] == ["rev-parse", "HEAD"] else "")

    monkeypatch.setattr(BASE.subprocess, "run", clean_git)
    assert BASE._checkpoint_root(packet) == root.resolve()

    packet["parents"]["capability_packet"]["external_sha256"] = "0" * 64
    with pytest.raises(BASE.CompositionControllerRefused,
                       match="capability parent path/SHA drift"):
        BASE._checkpoint_root(packet)


def test_legacy_packet_keeps_local_checkpoint_root():
    assert BASE._checkpoint_root({"parents": {}}) == BASE.REPO


def test_checkpoint_manifest_cannot_escape_external_evidence_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(BASE, "_checkpoint_root", lambda _packet: tmp_path)
    monkeypatch.setattr(BASE, "MODEL_PATHS", ("unused-export.npz",))
    packet = {
        "selected_capability": {"surface": "play"},
        "checkpoint_manifest": [{"checkpoint_path": "../outside.pt"}],
    }
    with pytest.raises(BASE.CompositionControllerRefused,
                       match="escapes evidence root"):
        BASE._export_models(packet, verify=False)


def test_external_parent_refs_are_pinned_and_traversal_safe(
    tmp_path: Path,
):
    evidence = tmp_path / "evidence"
    artifact = evidence / "server" / "runs" / "result.json"
    artifact.parent.mkdir(parents=True)
    payload = {"schema": "example", "value": 7}
    artifact.write_bytes(BASE.canonical_json(payload))

    ref = BASE._external_ref(
        artifact, BASE.sha256_file(artifact), "example",
        evidence_root=evidence)
    assert ref == {
        "evidence_root_absolute_path": str(evidence.resolve()),
        "logical_path": "server/runs/result.json",
        "external_sha256": BASE.sha256_file(artifact),
    }
    path, reopened = RUNTIME._artifact(ref, "example")
    assert path == artifact.resolve()
    assert reopened == payload

    review = tmp_path / "review.md"
    review.write_text("review\n")
    absolute = BASE._external_ref(
        review, BASE.sha256_file(review), "review", evidence_root=None)
    assert RUNTIME._path_from_ref(absolute, "review") == review.resolve()

    escaped = dict(ref)
    escaped["logical_path"] = "../outside.json"
    with pytest.raises(RUNTIME.CompositionRuntimeRefused,
                       match="evidence reference drift"):
        RUNTIME._path_from_ref(escaped, "example")
