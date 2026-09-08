"""CI wiring: both modes overlap, both finish, either failure rejects."""
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.mark.parametrize("fail", ["", "pure", "compiled", "pure,compiled"])
def test_parallel_mode_runner_propagates_each_failure_and_drains(tmp_path, fail):
    script = Path(__file__).parents[1] / "scripts" / "ci_cwv_modes.sh"
    binary = tmp_path / "uv"
    binary.write_text(f"#!{sys.executable}\n" + '''
import os, pathlib, sys, time
assert sys.argv[1:] == ["run", "python", "-B", "-m", "pytest", "-q", "tests/test_fake_cwv.py"]
assert all(os.environ[k] == "1" for k in (
    "SHENGJI_REQUIRE_VOIDS", "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"))
flag = os.environ.get("SHENGJI_FAST")
assert flag in (None, "1")
mode = "compiled" if flag == "1" else "pure"
pathlib.Path(mode + ".started").touch()
other = pathlib.Path(("pure" if mode == "compiled" else "compiled") + ".started")
deadline = time.monotonic() + 3
while not other.exists():
    if time.monotonic() > deadline:
        raise RuntimeError("modes did not overlap")
    time.sleep(.01)
pathlib.Path(mode + ".finished").touch()
print(mode + " reached test runner")
sys.exit(9 if mode in os.environ["FAIL_MODES"].split(",") else 0)
''')
    binary.chmod(0o700)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_fake_cwv.py").touch()
    result = subprocess.run(
        ["bash", str(script)], cwd=tmp_path, capture_output=True, text=True,
        env={**os.environ, "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"],
             "SHENGJI_FAST": "inherited-must-not-leak", "FAIL_MODES": fail}, timeout=10)
    assert result.returncode == (1 if fail else 0), result.stdout + result.stderr
    assert {p.name for p in tmp_path.glob("*.finished")} == {"pure.finished", "compiled.finished"}
    assert "[pure] pure reached test runner" in result.stdout
    assert "[compiled] compiled reached test runner" in result.stdout
