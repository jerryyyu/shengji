"""An interpreter without pytest never runs ``scripts/test_checkout.py``'s
tests: the script re-executes under the checkout virtualenv, once, or refuses
with a nonzero status."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "test_checkout.py"
MARKER = "SHENGJI_TEST_CHECKOUT_REEXEC"

FAKE_PYTEST = (
    "import os, sys\n"
    "def main(args):\n"
    "    print('fake pytest args:', repr(args))\n"
    "    print('fake pytest prefix:', os.path.realpath(sys.prefix))\n"
    "    print('fake pytest fast:', repr(os.environ.get('SHENGJI_FAST')))\n"
    "    print('fake pytest marker:', repr(os.environ.get('" + MARKER + "')))\n"
    "    return 0\n"
)


def _clean_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items()
           if k not in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", MARKER, "SHENGJI_FAST")}
    env["PYTHONNOUSERSITE"] = "1"
    return env


def _make_venv(path: Path) -> Path:
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(path)],
                   check=True, env=_clean_env(), capture_output=True)
    python = path / "bin" / "python"
    probe = subprocess.run([str(python), "-c", "import pytest"], env=_clean_env(),
                           capture_output=True, text=True, check=False)
    assert probe.returncode != 0, f"{python} unexpectedly imports pytest"
    return python


def _purelib(python: Path) -> Path:
    out = subprocess.run([str(python), "-c",
                          "import sysconfig; print(sysconfig.get_path('purelib'))"],
                         env=_clean_env(), capture_output=True, text=True, check=True)
    return Path(out.stdout.strip())


@pytest.fixture(scope="module")
def bare_python(tmp_path_factory) -> Path:
    """An interpreter that cannot import pytest (the plain ``python3`` case)."""
    return _make_venv(tmp_path_factory.mktemp("bare") / "venv")


def _fake_checkout(root: Path, *, venv: str, compiled: bool = False) -> Path:
    """A checkout copy of the script with a minimal ``shengji`` package and a
    ``server/.venv`` that is ``"pytest"`` (fake pytest installed), ``"bare"``
    (no pytest) or ``"missing"``."""
    server = root / "checkout" / "server"
    (server / "scripts").mkdir(parents=True)
    engine = server / "shengji" / "engine"
    engine.mkdir(parents=True)
    shutil.copy2(SCRIPT, server / "scripts" / SCRIPT.name)
    (server / "shengji" / "__init__.py").write_text("")
    (engine / "__init__.py").write_text("")
    if compiled:
        (engine / "legal.py").write_text("from ._fast import validate_follow\n")
        (engine / "_fast.py").write_text("def validate_follow(*args):\n    return None\n")
        (engine / "fast.py").write_text("from . import _fast\nHAVE_FAST = True\n")
    else:
        (engine / "legal.py").write_text("def validate_follow(*args):\n    return None\n")
    if venv != "missing":
        python = _make_venv(server / ".venv")
        if venv == "pytest":
            (_purelib(python) / "pytest.py").write_text(FAKE_PYTEST)
    return server / "scripts" / SCRIPT.name


def _run(python: Path, script: Path, *args: str, env: dict[str, str] | None = None):
    return subprocess.run([str(python), str(script), *args], cwd=script.parents[2],
                          env=env or _clean_env(), text=True, capture_output=True,
                          check=False)


def test_interpreter_without_pytest_reexecs_into_checkout_venv(tmp_path, bare_python):
    script = _fake_checkout(tmp_path, venv="pytest")
    venv = (script.parents[1] / ".venv").resolve()

    result = _run(bare_python, script, "--engine", "pure", "--", "-q", "tests/x.py")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "ModuleNotFoundError" not in result.stderr
    assert result.stderr.count("re-executing under") == 1
    assert "fake pytest args: ['-q', 'tests/x.py']" in result.stdout
    assert f"fake pytest prefix: {venv}" in result.stdout
    assert "fake pytest fast: None" in result.stdout
    assert "fake pytest marker: '1'" in result.stdout
    assert "engine mode: pure" in result.stdout


def test_reexec_passes_compiled_engine_through(tmp_path, bare_python):
    script = _fake_checkout(tmp_path, venv="pytest", compiled=True)

    result = _run(bare_python, script, "--engine", "compiled", "--", "-q")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "engine mode: compiled" in result.stdout
    assert "fake pytest fast: '1'" in result.stdout
    assert "fake pytest args: ['-q']" in result.stdout


def test_missing_checkout_venv_refuses_with_message(tmp_path, bare_python):
    script = _fake_checkout(tmp_path, venv="missing")

    result = _run(bare_python, script, "--engine", "pure", "--", "-q")

    assert result.returncode != 0
    assert "ModuleNotFoundError" not in result.stderr
    assert "test checkout refused: pytest is not importable" in result.stderr
    assert str(script.parents[1] / ".venv" / "bin" / "python") in result.stderr
    assert "is missing" in result.stderr
    assert "fake pytest" not in result.stdout


def test_venv_without_pytest_refuses_once_instead_of_looping(tmp_path, bare_python):
    script = _fake_checkout(tmp_path, venv="bare")

    result = _run(bare_python, script, "--engine", "pure", "--", "-q")

    assert result.returncode != 0
    assert result.stderr.count("re-executing under") == 1
    assert "test checkout refused: pytest is not importable" in result.stderr
    assert "ModuleNotFoundError" not in result.stderr


def test_running_the_venv_interpreter_never_reexecs(tmp_path):
    script = _fake_checkout(tmp_path, venv="bare")

    result = _run(script.parents[1] / ".venv" / "bin" / "python", script,
                  "--engine", "pure", "--", "-q")

    assert result.returncode != 0
    assert "re-executing under" not in result.stderr
    assert "test checkout refused: pytest is not importable" in result.stderr


def test_marker_already_set_refuses_without_reexec(tmp_path, bare_python):
    script = _fake_checkout(tmp_path, venv="pytest")
    env = _clean_env()
    env[MARKER] = "1"

    result = _run(bare_python, script, "--engine", "pure", "--", "-q", env=env)

    assert result.returncode != 0
    assert "re-executing under" not in result.stderr
    assert "fake pytest" not in result.stdout


def test_interpreter_with_pytest_does_not_reexec(tmp_path):
    script = _fake_checkout(tmp_path, venv="pytest")
    fake = tmp_path / "fake-pytest"
    fake.mkdir()
    (fake / "pytest.py").write_text(FAKE_PYTEST)
    env = _clean_env()
    env["PYTHONPATH"] = str(fake)

    result = _run(Path(sys.executable), script, "--engine", "pure", "--", "-q", env=env)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "re-executing under" not in result.stderr
    assert "fake pytest marker: None" in result.stdout
