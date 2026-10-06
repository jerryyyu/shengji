"""Subprocess checks for the checkout-safe pytest entrypoint."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "test_checkout.py"
SERVER = SCRIPT.parents[1]


def _fake_import_roots(tmp_path: Path) -> tuple[Path, Path, Path]:
    fake = tmp_path / "fake"
    wrong = tmp_path / "wrong"
    foreign = tmp_path / "foreign"
    fake.mkdir()
    wrong_pkg = wrong / "shengji"
    wrong_pkg.mkdir(parents=True)
    foreign.mkdir()
    (wrong_pkg / "__init__.py").write_text(
        "raise AssertionError('wrong editable shengji was imported')\n"
    )
    (fake / "pytest.py").write_text(
        "import os\n"
        "import shengji\n"
        "from shengji.engine import legal\n"
        "\n"
        "def main(args):\n"
        "    print('fake pytest args:', repr(args))\n"
        "    print('fake pytest cwd:', os.getcwd())\n"
        "    print('fake pytest fast:', repr(os.environ.get('SHENGJI_FAST')))\n"
        "    print('fake pytest shengji:', shengji.__file__)\n"
        "    print('fake pytest legal:', legal.__file__)\n"
        "    print('fake pytest follow:', legal.validate_follow.__module__)\n"
        "    if os.environ.get('CHECK_CHILD_IMPORT'):\n"
        "        import subprocess, sys\n"
        "        child = subprocess.run([sys.executable, '-P', '-B', '-c',\n"
        "            'import shengji; from shengji.engine import legal; '\n"
        "            'print(shengji.__file__); print(legal.validate_follow.__module__)'],\n"
        "            cwd=os.environ['CHILD_CWD'], capture_output=True, text=True)\n"
        "        assert child.returncode == 0, child.stderr\n"
        "        assert child.stdout.splitlines() == [shengji.__file__, legal.validate_follow.__module__]\n"
        "    return int(os.environ.get('FAKE_PYTEST_EXIT', '0'))\n"
    )
    return fake, wrong, foreign


def _fake_checkout(tmp_path: Path, *, compiled: bool = False) -> Path:
    server = tmp_path / "fake-checkout" / "server"
    (server / "scripts").mkdir(parents=True)
    package = server / "shengji" / "engine"
    package.mkdir(parents=True)
    shutil.copy2(SCRIPT, server / "scripts" / SCRIPT.name)
    (server / "shengji" / "__init__.py").write_text("")
    (server / "shengji" / "engine" / "__init__.py").write_text("")
    (server / "shengji" / "engine" / "legal.py").write_text(
        "from ._fast import validate_follow\n"
    )
    (server / "shengji" / "engine" / "_fast.py").write_text(
        "def validate_follow(*args):\n    return None\n"
    )
    (server / "shengji" / "engine" / "fast.py").write_text(
        f"from . import _fast\nHAVE_FAST = {compiled!r}\n"
    )
    return server / "scripts" / SCRIPT.name


def _run(
    tmp_path: Path,
    *args: str,
    fast: str = "0",
    script: Path = SCRIPT,
    pytest_exit: int = 0,
    child: bool = False,
    relative_pythonpath: bool = False,
) -> subprocess.CompletedProcess[str]:
    fake, wrong, foreign = _fake_import_roots(tmp_path)
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join((str(wrong), str(fake)))
    if relative_pythonpath:
        env["PYTHONPATH"] = os.pathsep.join(
            os.path.relpath(path, foreign) for path in (wrong, fake)
        )
    env["SHENGJI_FAST"] = fast
    env["FAKE_PYTEST_EXIT"] = str(pytest_exit)
    if child:
        env["CHECK_CHILD_IMPORT"] = "1"
        env["CHILD_CWD"] = str(foreign)
    return subprocess.run(
        [sys.executable, str(script), *args],
        cwd=foreign,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_pure_mode_uses_checkout_from_foreign_cwd_and_consumes_pytest_args(tmp_path):
    result = _run(tmp_path, "--engine", "pure", "--", "-q", "fake_target.py")

    assert result.returncode == 0, result.stderr
    assert f"checkout source: {SERVER}" in result.stdout
    assert "engine mode: pure" in result.stdout
    assert "fake pytest cwd: " + str(SERVER) in result.stdout
    assert "fake pytest fast: None" in result.stdout
    assert "fake pytest args: ['-q', 'fake_target.py']" in result.stdout
    assert f"fake pytest shengji: {SERVER / 'shengji' / '__init__.py'}" in result.stdout
    assert "wrong editable shengji was imported" not in result.stderr


def test_compiled_mode_refuses_unavailable_engine_instead_of_falling_back(tmp_path):
    result = _run(tmp_path, "--engine", "compiled", script=_fake_checkout(tmp_path))

    assert result.returncode != 0
    assert "compiled engine unavailable" in result.stderr
    assert "fake pytest" not in result.stdout


def test_compiled_mode_requires_and_reports_the_compiled_source(tmp_path):
    result = _run(
        tmp_path,
        "--engine",
        "compiled",
        "--",
        "-q",
        script=_fake_checkout(tmp_path, compiled=True),
    )

    assert result.returncode == 0, result.stderr
    assert "engine mode: compiled" in result.stdout
    assert "fake pytest fast: '1'" in result.stdout
    assert "fake pytest args: ['-q']" in result.stdout


def test_pytest_exit_status_is_propagated(tmp_path):
    result = _run(tmp_path, "--engine", "pure", pytest_exit=7)

    assert result.returncode == 7


@pytest.mark.parametrize("engine", ["pure", "compiled"])
@pytest.mark.parametrize("relative_pythonpath", [False, True])
def test_child_python_inherits_checkout_over_foreign_pythonpath(
        tmp_path, engine, relative_pythonpath):
    script = _fake_checkout(tmp_path, compiled=True) if engine == "compiled" else SCRIPT
    result = _run(tmp_path, "--engine", engine, script=script, child=True,
                  relative_pythonpath=relative_pythonpath)
    assert result.returncode == 0, result.stdout + result.stderr


def test_engine_is_required(tmp_path):
    result = _run(tmp_path)

    assert result.returncode != 0
    assert "--engine" in result.stderr


@pytest.mark.parametrize("args", [
    ["--engine", "pure", "tests/x.py", "--", "-q"],
    ["--engine", "pure", "-q", "--", "tests/x.py"],
    ["--eng", "pure", "--", "tests/x.py"],
    ["--engine", "pure", "tests/x.py"],
])
def test_only_wrapper_options_are_allowed_before_separator(tmp_path, args):
    result = _run(tmp_path, *args)
    assert result.returncode == 2
    assert "fake pytest" not in result.stdout


def test_suffix_is_forwarded_exactly_after_first_separator(tmp_path):
    result = _run(tmp_path, "--engine", "pure", "--", "-q", "--", "tests/x.py")
    assert result.returncode == 0, result.stderr
    assert "fake pytest args: ['-q', '--', 'tests/x.py']" in result.stdout
