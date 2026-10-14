"""The production_package hook: a required package test may never skip.

Each case runs a throwaway pytest session in a scratch directory with only the
``production_package_gate`` plugin loaded (not the suite's conftest).
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap

TESTS = Path(__file__).resolve().parent
SERVER = TESTS.parent

CASES = textwrap.dedent(
    """
    import pytest

    @pytest.fixture(scope="module")
    def pinned_production_package():
        pytest.skip("package not provisioned")

    @pytest.fixture
    def torch_first():
        pytest.skip("could not import 'torch'")

    @pytest.fixture
    def decision_package(request, torch_first):
        # The #993 shape: the package is requested dynamically, after a skip.
        return request.getfixturevalue("pinned_production_package")

    def test_direct(pinned_production_package):
        pass

    def test_dynamic(decision_package):
        pass

    @pytest.mark.production_package
    def test_marked_call_skip():
        pytest.skip("skipped inside the body")

    @pytest.mark.production_package
    def test_marked_passes():
        pass

    def test_unmarked_skip():
        pytest.skip("unrelated optional dependency")

    @pytest.mark.production_package
    @pytest.mark.xfail(reason="known")
    def test_marked_xfail():
        assert False
    """
)


def _run(tmp_path: Path, *args: str, flag: str | None) -> subprocess.CompletedProcess:
    (tmp_path / "test_cases.py").write_text(CASES)
    env = {k: v for k, v in os.environ.items() if k != "SHENGJI_REQUIRE_PV_PACKAGE"}
    if flag is not None:
        env["SHENGJI_REQUIRE_PV_PACKAGE"] = flag
    env["PYTHONPATH"] = os.pathsep.join([str(TESTS), env.get("PYTHONPATH", "")])
    return subprocess.run(
        [sys.executable, "-B", "-m", "pytest", "-p", "production_package_gate",
         "-p", "no:cacheprovider", "-v", "-rA", "--color=no", "--strict-markers", "test_cases.py", *args],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120,
    )


def _outcomes(stdout: str) -> dict[str, str]:
    """Per-test outcome from the ``-v`` progress lines."""
    outcomes = {}
    for line in stdout.splitlines():
        if line.startswith("test_cases.py::"):
            words = line[len("test_cases.py::"):].split()
            if len(words) >= 2:
                outcomes[words[0]] = words[1]
    return outcomes


def test_marked_skips_fail_under_the_flag(tmp_path):
    result = _run(tmp_path, flag="1")
    assert result.returncode == 1, result.stdout + result.stderr
    outcomes = _outcomes(result.stdout)
    # Setup-time skips become setup errors; a call-time skip becomes a failure.
    assert outcomes["test_direct"] == "ERROR"
    assert outcomes["test_dynamic"] == "ERROR"
    assert outcomes["test_marked_call_skip"] == "FAILED"
    assert outcomes["test_marked_passes"] == "PASSED"
    assert outcomes["test_unmarked_skip"] == "SKIPPED"
    assert outcomes["test_marked_xfail"] == "XFAIL"
    assert "SHENGJI_REQUIRE_PV_PACKAGE=1: required production-package test" in result.stdout
    assert "package not provisioned" in result.stdout
    assert "could not import 'torch'" in result.stdout


def test_without_the_flag_marked_tests_still_skip(tmp_path):
    for flag in (None, "0"):
        scratch = tmp_path / f"flag-{flag}"
        scratch.mkdir()
        result = _run(scratch, flag=flag)
        assert result.returncode == 0, result.stdout + result.stderr
        outcomes = _outcomes(result.stdout)
        assert outcomes["test_direct"] == "SKIPPED"
        assert outcomes["test_dynamic"] == "SKIPPED"
        assert outcomes["test_marked_call_skip"] == "SKIPPED"
        assert outcomes["test_unmarked_skip"] == "SKIPPED"
        assert "required production-package test" not in result.stdout


def test_the_marker_is_applied_automatically(tmp_path):
    # -qq: the helper passes -v, so this nets to -q (one node id per line).
    result = _run(tmp_path, "--collect-only", "-qq", "-m", "production_package", flag=None)
    assert result.returncode == 0, result.stdout + result.stderr
    selected = {line.split("::")[-1] for line in result.stdout.splitlines() if "::" in line}
    assert selected == {"test_direct", "test_dynamic", "test_marked_call_skip",
                        "test_marked_passes", "test_marked_xfail"}


def test_the_real_production_package_tests_are_marked():
    env = {k: v for k, v in os.environ.items() if k != "SHENGJI_REQUIRE_PV_PACKAGE"}
    result = subprocess.run(
        [sys.executable, "-B", "-m", "pytest", "-p", "no:cacheprovider", "--collect-only",
         "-q", "-m", "production_package", "tests/test_encoder_round_compat.py",
         "tests/test_pv_finish_lead.py"],
        cwd=SERVER, env=env, capture_output=True, text=True, timeout=300,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    selected = {line.split("::")[-1] for line in result.stdout.splitlines() if "::" in line}
    assert {
        "test_the_production_package_constructs_a_served_bot",
        "test_production_package_value_declare_server_smoke[3.0]",
        "test_production_package_value_declare_server_smoke[1e-12]",
        "test_value_declare_full_deal_admits_only_gated_decisions",
        "test_current_recipe_candidate_survives_server_snapshot_and_commit[False]",
        "test_current_recipe_candidate_survives_server_snapshot_and_commit[True]",
    } <= selected
    assert not any(name.startswith("test_tiny_recipe") for name in selected)
