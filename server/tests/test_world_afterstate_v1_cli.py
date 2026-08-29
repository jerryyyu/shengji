from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


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
