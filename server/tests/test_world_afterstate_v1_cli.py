from __future__ import annotations

import os
import runpy
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import shengji.rl.world_afterstate_v1_capacity as capacity


def test_target_free_cli_refuses_label_bearing_path_surface(tmp_path):
    server = Path(__file__).resolve().parents[1]
    script = server / "scripts" / "world_afterstate_v1_run.py"
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    environment.update({
        "PYTHONDONTWRITEBYTECODE": "1", "PYTHONHASHSEED": "0",
        "SHENGJI_FAST": "1", "SHENGJI_REQUIRE_VOIDS": "1",
    })
    result = subprocess.run((
        sys.executable, "-P", "-B", str(script), "seal-predictions",
        "--root", str(tmp_path / "missing-root"),
        "--expected-git", "a" * 40,
        "--population", str(tmp_path / "population.json"),
        "--audit-manifest", str(tmp_path / "audit.json"),
        "--audit-root", str(tmp_path / "audits"),
        "--dataset-manifest", str(tmp_path / "labels.json"),
        "--row-root", str(tmp_path / "label-rows"),
    ), cwd=server, env=environment, capture_output=True, text=True)
    assert result.returncode != 0
    assert "target-free prediction argument drift" in result.stderr


def test_initialize_checks_live_runtime_before_spending_admission(
        monkeypatch, tmp_path):
    server = Path(__file__).resolve().parents[1]
    script = server / "scripts" / "world_afterstate_v1_run.py"
    namespace = runpy.run_path(str(script))
    script_globals = namespace["_initialize"].__globals__
    freeze = {"source_git": "a" * 40}
    events = []
    script_globals["_canonical_read"] = \
        lambda _path, _label: (b"{}\n", freeze)
    monkeypatch.setattr(
        capacity, "reopen_capacity_directory", lambda _path: object())

    def refuse_live(_freeze, _expected_git):
        events.append("strict-live")
        raise RuntimeError("fixture live drift")

    script_globals["_strict_live"] = refuse_live
    script_globals["initialize_scientific_root"] = lambda *_args, **_kwargs: \
        events.append("initialize")
    args = SimpleNamespace(
        freeze=str(tmp_path / "freeze.json"),
        capacity=str(tmp_path / "capacity"),
        root=str(tmp_path / "scientific"), expected_git="a" * 40,
        review_commit="b" * 40)
    with pytest.raises(RuntimeError, match="^fixture live drift$"):
        namespace["_initialize"](args)
    assert events == ["strict-live"]
    assert not (tmp_path / "scientific").exists()
