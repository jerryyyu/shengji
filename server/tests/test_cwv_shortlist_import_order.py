"""The env-driven shortlist registration must not depend on import ORDER.

``registry`` registers from ``SHENGJI_CWV_SHORTLIST_CKPT`` at import time and
must import ``train.cwv_shortlist`` to do it, while ``train.cwv_shortlist``
imports ``REGISTRY`` from ``registry``.  Whichever module a caller happens to
reach first, both must finish importing and the policy must be registered.
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

SERVER = Path(__file__).resolve().parents[1]
CKPT = SERVER.parent  # any existing path; registration must not stat it at import


def _run(source: str, ckpt: str):
    env = dict(os.environ)
    env.update({"PYTHONPATH": str(SERVER), "SHENGJI_REQUIRE_VOIDS": "1",
                "PYTHONDONTWRITEBYTECODE": "1",
                "SHENGJI_CWV_SHORTLIST_CKPT": ckpt})
    env.pop("SHENGJI_NETROLL_CKPT", None)
    return subprocess.run([sys.executable, "-P", "-B", "-c", source],
                          capture_output=True, text=True, env=env, cwd=str(SERVER))


NAMES = ("from shengji.ai.registry import REGISTRY;"
         "print(sorted(n for n in REGISTRY if n.startswith('mc-shortlist-')))")


@pytest.fixture(scope="module")
def ckpt(tmp_path_factory):
    path = tmp_path_factory.mktemp("ck") / "best.pt"
    path.write_bytes(b"not a real checkpoint, only its sha8 is read at registration")
    return str(path)


@pytest.mark.parametrize("first", ["shengji.ai.registry",
                                   "shengji.train.cwv_shortlist",
                                   "shengji.harvest.trajectory"])
def test_the_shortlist_policy_registers_whichever_module_is_imported_first(first, ckpt):
    result = _run(f"import {first};" + NAMES, ckpt)
    assert result.returncode == 0, (
        f"importing {first} first raised:\n{result.stderr[-1200:]}")
    assert "mc-shortlist-" in result.stdout, (
        f"importing {first} first left the policy unregistered: {result.stdout!r}")


def test_no_env_leaves_the_registry_free_of_shortlist_policies(ckpt):
    env = dict(os.environ)
    env.update({"PYTHONPATH": str(SERVER), "SHENGJI_REQUIRE_VOIDS": "1",
                "PYTHONDONTWRITEBYTECODE": "1"})
    env.pop("SHENGJI_CWV_SHORTLIST_CKPT", None)
    env.pop("SHENGJI_NETROLL_CKPT", None)
    result = subprocess.run(
        [sys.executable, "-P", "-B", "-c", "import shengji.train.cwv_shortlist;" + NAMES],
        capture_output=True, text=True, env=env, cwd=str(SERVER))
    assert result.returncode == 0, result.stderr[-800:]
    assert result.stdout.strip() == "[]", result.stdout
