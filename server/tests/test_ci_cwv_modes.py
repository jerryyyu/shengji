"""CI wiring: both modes overlap, both finish, either failure rejects."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

SCRIPT = Path(__file__).parents[1] / "scripts" / "ci_cwv_modes.sh"


def _shard1(script=SCRIPT):
    text = script.read_text()
    body = text.split("SHARD1=(", 1)[1].split(")", 1)[0]
    return body.split()


def _selection(server):
    return sorted({p.relative_to(server).as_posix() for p in (server / "tests").glob("test_*cwv*.py")}
                  | {"tests/test_encoder_bytes_golden.py"})


@pytest.mark.parametrize("fail", ["", "pure", "compiled", "pure,compiled"])
def test_parallel_mode_runner_propagates_each_failure_and_drains(tmp_path, fail):
    script = Path(__file__).parents[1] / "scripts" / "ci_cwv_modes.sh"
    binary = tmp_path / "uv"
    binary.write_text(f"#!{sys.executable}\n" + '''
import os, pathlib, sys, time
assert sys.argv[1:] == ["run", "python", "-B", "-m", "pytest", "-q", "--durations=20", "tests/test_fake_cwv.py", "tests/test_encoder_bytes_golden.py"]
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


def _shard_argv(tmp_path, shard):
    """Run one shard against empty copies of the real selection; return each mode's pytest argv."""
    work = tmp_path / f"shard{shard}"
    (work / "tests").mkdir(parents=True)
    for module in _selection(SCRIPT.parents[1]):
        (work / module).touch()
    binary = work / "uv"
    binary.write_text(f"#!{sys.executable}\n" + '''
import json, os, pathlib, sys
mode = "compiled" if os.environ.get("SHENGJI_FAST") == "1" else "pure"
pathlib.Path(mode + ".argv").write_text(json.dumps(sys.argv[1:]))
''')
    binary.chmod(0o700)
    result = subprocess.run(
        ["bash", str(SCRIPT), str(shard)], cwd=work, capture_output=True, text=True,
        env={**os.environ, "PATH": str(work) + os.pathsep + os.environ["PATH"]}, timeout=10)
    assert result.returncode == 0, result.stdout + result.stderr
    import json
    return {mode: json.loads((work / f"{mode}.argv").read_text()) for mode in ("pure", "compiled")}


def _ran(argv, selection):
    deselected = {argv[i + 1].removesuffix("::") for i, a in enumerate(argv) if a == "--deselect"}
    assert all(argv[i + 1].endswith("::") for i, a in enumerate(argv) if a == "--deselect")
    assert deselected <= set(selection)
    return set(selection) - deselected


def test_the_two_shards_partition_the_selection_in_both_modes(tmp_path):
    selection = _selection(SCRIPT.parents[1])
    assert set(_shard1()) <= set(selection)
    shards = {shard: _shard_argv(tmp_path, shard) for shard in (1, 2)}
    for mode in ("pure", "compiled"):
        one = _ran(shards[1][mode], selection)
        two = _ran(shards[2][mode], selection)
        assert one == set(_shard1())
        assert one.isdisjoint(two)
        assert one | two == set(selection)


def test_an_unknown_shard_or_a_missing_shard1_module_refuses(tmp_path):
    (tmp_path / "tests").mkdir()
    for args in (["3"], ["1"]):
        result = subprocess.run(["bash", str(SCRIPT), *args], cwd=tmp_path, capture_output=True,
                                text=True, timeout=10)
        assert result.returncode == 2, result.stdout + result.stderr


POLICY_SCRIPT = Path(__file__).parents[1] / "scripts" / "ci_policy_modes.sh"
POLICY_SELECTION = sorted([
    "tests/test_policy_*.py", "tests/test_exact_resume.py", "tests/test_harvest_trajectory_pv.py",
    "tests/test_runij_split_binding.py", "tests/test_screen_policy_arm.py",
    "tests/test_screen_deadline_child.py", "tests/test_screen_shadow_arm.py",
    "tests/test_search_policy.py", "tests/test_split_selector.py"])


def _policy_run(tmp_path, engine, fail=""):
    """Run ci_policy_modes.sh against a fake uv; return (result, {mode: [file lists]})."""
    binary = tmp_path / "uv"
    binary.write_text(f"#!{sys.executable}\n" + '''
import json, os, pathlib, sys, uuid
args = sys.argv[1:]
assert args[:7] == ["run", "python", "-B", "-m", "pytest", "-q", "--durations=10"], args
flag = os.environ.get("SHENGJI_FAST")
assert flag in (None, "1")
mode = "compiled" if flag == "1" else "pure"
pathlib.Path(f"{mode}.{uuid.uuid4().hex}.ran").write_text(json.dumps(args[7:]))
sys.exit(9 if mode in os.environ["FAIL_MODES"].split(",") else 0)
''')
    binary.chmod(0o700)
    (tmp_path / "tests").mkdir(exist_ok=True)     # no match: the glob reaches the fake literally
    result = subprocess.run(
        ["bash", str(POLICY_SCRIPT), *([engine] if engine else [])], cwd=tmp_path,
        capture_output=True, text=True,
        env={**os.environ, "PATH": str(tmp_path) + os.pathsep + os.environ["PATH"],
             "SHENGJI_FAST": "inherited-must-not-leak", "FAIL_MODES": fail}, timeout=10)
    ran: dict[str, list[list[str]]] = {}
    for p in tmp_path.glob("*.ran"):
        ran.setdefault(p.name.split(".")[0], []).append(json.loads(p.read_text()))
    return result, ran


@pytest.mark.parametrize("engine,modes", [
    ("pure", {"pure"}), ("compiled", {"compiled"}), ("both", {"pure", "compiled"}), ("", {"pure", "compiled"})])
@pytest.mark.parametrize("fail", ["", "pure", "compiled"])
def test_policy_runner_runs_exactly_the_named_engine_and_propagates_its_failure(tmp_path, engine, modes, fail):
    result, ran = _policy_run(tmp_path, engine, fail)
    assert set(ran) == modes, result.stdout + result.stderr
    assert result.returncode == (1 if fail in modes else 0), result.stdout + result.stderr


def test_each_engine_runs_the_whole_selection_in_two_disjoint_halves(tmp_path):
    result, ran = _policy_run(tmp_path, "both")
    assert result.returncode == 0, result.stdout + result.stderr
    for mode in ("pure", "compiled"):
        halves = ran[mode]
        assert len(halves) == 2
        assert not set(halves[0]) & set(halves[1])
        assert sorted(halves[0] + halves[1]) == POLICY_SELECTION


def test_policy_runner_refuses_an_unknown_engine(tmp_path):
    result, ran = _policy_run(tmp_path, "fast")
    assert result.returncode == 2 and not ran
    assert "unknown engine 'fast'" in result.stderr
