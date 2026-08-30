"""Wiring-altitude tests for the Value V2 freeze-input builder CLI."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from scripts import build_world_afterstate_v2_freeze_inputs as cli


SOURCE = "a" * 40


class _Capacity:
    def __init__(self, source_sha256: str) -> None:
        self.source_sha256 = source_sha256


def _argv(tmp_path: Path) -> list[str]:
    capacity = tmp_path / "capacity.json"
    capacity.write_bytes(b"capacity\n")
    return [
        "--repo", str(cli.REPO), "--source-git", SOURCE,
        "--capacity", str(capacity),
        "--evidence-root", str(tmp_path / "unused-evidence"),
        "--deadline-seconds", "100", "--heartbeat-seconds", "10",
        "--max-attempts-per-slot", "3",
        "--out-dir", str(tmp_path / "inputs"),
    ]


def _git_clean(monkeypatch: pytest.MonkeyPatch) -> None:
    def git(_repo: Path, *args: str) -> str:
        if args == ("rev-parse", "HEAD"):
            return SOURCE
        if args == ("status", "--porcelain", "--untracked-files=all"):
            return ""
        raise AssertionError(args)
    monkeypatch.setattr(cli, "_git", git)


def test_cli_refuses_capacity_measured_by_different_source(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _git_clean(monkeypatch)
    monkeypatch.setattr(
        cli, "capacity_context",
        lambda _raw: (_Capacity("b" * 64), "D256", 4, 8))
    monkeypatch.setattr(cli, "capacity_source_sha256", lambda _repo: "c" * 64)
    reached = False

    def unexpected(**_kwargs):
        nonlocal reached
        reached = True
        raise AssertionError("mismatched receipt reached input derivation")

    monkeypatch.setattr(cli, "build_freeze_inputs_v2", unexpected)
    with pytest.raises(SystemExit, match="capacity receipt source differs"):
        cli.main(_argv(tmp_path))
    assert reached is False
    assert not (tmp_path / "inputs").exists()


def test_cli_threads_authenticated_receipt_into_one_exclusive_publication(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _git_clean(monkeypatch)
    source = "d" * 64
    monkeypatch.setattr(
        cli, "capacity_context",
        lambda _raw: (_Capacity(source), "D256", 4, 8))
    monkeypatch.setattr(cli, "capacity_source_sha256", lambda _repo: source)
    observed: dict[str, object] = {}
    values = {
        "protocol": b'{}\n', "population": b'{}\n', "config": b'{}\n',
        "seed": b'{}\n', "continuation-policy": b'{}\n'}

    def build(**kwargs):
        observed["build"] = kwargs
        return values

    def publish(directory, **kwargs):
        observed["publish"] = (directory, kwargs)
        return ()

    monkeypatch.setattr(cli, "build_freeze_inputs_v2", build)
    monkeypatch.setattr(cli, "publish_inputs_v2", publish)
    assert cli.main(_argv(tmp_path)) == 0
    assert observed["build"] == {
        "source_git": SOURCE, "capacity_raw": b"capacity\n",
        "evidence_root": str(tmp_path / "unused-evidence"),
        "deadline_seconds": 100, "heartbeat_seconds": 10,
        "max_attempts_per_slot": 3}
    directory, published = observed["publish"]
    assert directory == tmp_path / "inputs"
    assert set(published) == {
        "protocol", "population", "config", "seed", "continuation_policy"}


def test_cli_refuses_dirty_source_before_reading_capacity(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def git(_repo: Path, *args: str) -> str:
        if args == ("rev-parse", "HEAD"):
            return SOURCE
        if args == ("status", "--porcelain", "--untracked-files=all"):
            return " M server/shengji/rl/world_afterstate_v2_capacity.py"
        raise AssertionError(args)
    monkeypatch.setattr(cli, "_git", git)
    with pytest.raises(SystemExit, match="source Git differs"):
        cli.main(_argv(tmp_path))


def test_cli_refuses_foreign_repo_identity_before_capacity_open(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    foreign = tmp_path / "foreign"
    foreign.mkdir()
    argv = _argv(tmp_path)
    argv[1] = str(foreign)
    opened = False

    def unexpected(*_args, **_kwargs):
        nonlocal opened
        opened = True
        raise AssertionError("foreign repo reached Git/capacity")

    monkeypatch.setattr(cli, "_git", unexpected)
    with pytest.raises(SystemExit, match="source Git differs"):
        cli.main(argv)
    assert opened is False


@pytest.mark.parametrize(("script_name", "hostile_module", "message"), (
    ("world_afterstate_v2_capacity.py", "argparse.py",
     "Value V2 capacity refuses PYTHONPATH"),
    ("build_world_afterstate_v2_freeze_inputs.py", "pathlib.py",
     "Value V2 freeze-input builder refuses PYTHONPATH"),
    ("build_world_afterstate_v2_freeze.py", "pathlib.py",
     "Value V2 freeze builder refuses PYTHONPATH"),
    ("world_afterstate_v2_run.py", "argparse.py",
     "Value V2 scientific execution refuses PYTHONPATH"),
))
def test_cli_rejects_hostile_pythonpath_before_nonessential_import(
        tmp_path: Path, script_name: str, hostile_module: str,
        message: str) -> None:
    hostile = tmp_path / "hostile"
    hostile.mkdir()
    sentinel = tmp_path / "executed"
    (hostile / hostile_module).write_text(
        f"open({str(sentinel)!r}, 'w').write('bad')\n")
    script = Path(__file__).parents[1] / "scripts" / script_name
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(hostile)
    result = subprocess.run(
        (sys.executable, "-P", "-B", str(script), "--help"),
        env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, check=False)
    assert result.returncode != 0
    assert message in result.stderr
    assert not sentinel.exists()


@pytest.mark.parametrize(("script_name", "message"), (
    ("world_afterstate_v2_capacity.py",
     "Value V2 capacity refuses source bytecode artifacts"),
    ("build_world_afterstate_v2_freeze_inputs.py",
     "Value V2 freeze-input builder refuses source bytecode artifacts"),
    ("build_world_afterstate_v2_freeze.py",
     "Value V2 freeze builder refuses source bytecode artifacts"),
    ("world_afterstate_v2_run.py",
     "Value V2 scientific execution refuses source bytecode artifacts"),
))
def test_value_v2_preimport_clis_refuse_ignored_bytecode(
        tmp_path: Path, script_name: str, message: str) -> None:
    """Prove the bytecode guard runs before any project import is possible."""
    server = tmp_path / "server"
    scripts = server / "scripts"
    cache = server / "shengji" / "rl" / "__pycache__"
    scripts.mkdir(parents=True)
    cache.mkdir(parents=True)
    (cache / "shadow.pyc").write_bytes(b"unchecked-shadow")
    source = Path(__file__).parents[1] / "scripts" / script_name
    target = scripts / script_name
    shutil.copy2(source, target)
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    result = subprocess.run(
        (sys.executable, "-P", "-B", str(target)), env=environment,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        check=False)
    assert result.returncode != 0
    assert message in result.stderr
