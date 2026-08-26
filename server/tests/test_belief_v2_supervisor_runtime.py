"""Runtime-path witnesses for the recoverable R5 supervisor."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import venv

import pytest


SCRIPT = (Path(__file__).parents[1] / "scripts" /
          "belief_v2_supervisor.py")
PATH_PROBE = """
import importlib.util
from pathlib import Path
import sys

spec = importlib.util.spec_from_file_location("belief_v2_supervisor", sys.argv[1])
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
print(module._absolute_python_path(Path(sys.argv[2])))
"""

MAIN_PROBE = """
import importlib.util
from pathlib import Path
import sys

spec = importlib.util.spec_from_file_location("belief_v2_supervisor", sys.argv[1])
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class SupervisorProbe:
    def __init__(self, *, plan, root, ops, python, worker, resume=False):
        self.python = python
        assert resume is False

    def request_stop(self, signum):
        raise AssertionError(f"unexpected signal {signum}")

    def run(self):
        print(self.python)

module.Supervisor = SupervisorProbe
module.build_supervisor_plan = lambda **_kwargs: object()
module._strict_json = lambda _path: {}
sys.argv = [
    str(sys.argv[1]),
    "--root", sys.argv[3],
    "--ops", sys.argv[4],
    "--python", sys.argv[2],
    "--worker", str(Path(sys.argv[1]).with_name("belief_v2_worker.py")),
    "--human-sources", sys.argv[5],
    "--group-split", sys.argv[6],
]
module.main()
"""


def test_supervisor_preserves_venv_python_symlink_for_workers(tmp_path):
    environment = tmp_path / "worker-venv"
    venv.EnvBuilder(with_pip=False).create(environment)
    python = environment / "bin" / "python"
    if not python.is_symlink():
        python.unlink()
        python.symlink_to(Path(sys.executable).resolve())
    site_packages = next((environment / "lib").glob("python*/site-packages"))
    (site_packages / "belief_worker_probe.py").write_text(
        "VALUE = 'venv-loaded'\n", encoding="ascii")

    probe = subprocess.run(
        [sys.executable, "-P", "-B", "-c", PATH_PROBE,
         str(SCRIPT), str(python)],
        check=True, capture_output=True, text=True)
    selected = Path(probe.stdout.strip())

    assert selected == python
    assert selected.resolve() == Path(sys.executable).resolve()
    completed = subprocess.run(
        [str(selected), "-P", "-B", "-c",
         "import belief_worker_probe; print(belief_worker_probe.VALUE)"],
        check=True, capture_output=True, text=True)
    assert completed.stdout == "venv-loaded\n"


def test_supervisor_main_passes_venv_python_symlink_to_worker_runner(tmp_path):
    environment = tmp_path / "worker-venv"
    venv.EnvBuilder(with_pip=False).create(environment)
    python = environment / "bin" / "python"
    if not python.is_symlink():
        python.unlink()
        python.symlink_to(Path(sys.executable).resolve())
    human_sources = tmp_path / "human-sources"
    human_sources.mkdir()
    group_split = tmp_path / "group-split.json"
    group_split.write_text("{}\n", encoding="ascii")
    child_env = os.environ.copy()
    child_env.pop("PYTHONPATH", None)

    completed = subprocess.run(
        [sys.executable, "-P", "-B", "-c", MAIN_PROBE,
         str(SCRIPT), str(python), str(tmp_path / "root"),
         str(tmp_path / "ops"), str(human_sources), str(group_split)],
        check=True, capture_output=True, text=True, env=child_env)

    selected = Path(completed.stdout.strip())
    assert selected == python
    assert selected.resolve() == Path(sys.executable).resolve()


def _load_supervisor():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "belief_v2_supervisor_recovery_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _FakePlan:
    def __init__(self):
        task = SimpleNamespace(name="only-task", arguments=("fake-task",))
        self.stages = (
            SimpleNamespace(name="fake-stage", concurrency=1, tasks=(task,)),)

    def canonical_summary_bytes(self):
        return b'{"schema":"fake-plan"}\n'

    def execution_sha256(self):
        return "e" * 64


def _recovery_fixture(tmp_path, *, state="interrupted", running=None):
    module = _load_supervisor()
    root = (tmp_path / "root").resolve()
    root.mkdir(parents=True)
    ops = (tmp_path / "ops").resolve()
    ops.mkdir(mode=0o700)
    (ops / "logs").mkdir(mode=0o700)
    worker = (tmp_path / "fake_worker.py").resolve()
    worker.write_text(
        """from pathlib import Path
import sys
assert '--recover-existing' in sys.argv
root = Path(sys.argv[sys.argv.index('--root') + 1])
(root / 'recovery-command-observed').write_text('yes\\n', encoding='ascii')
""", encoding="ascii")
    plan = _FakePlan()
    supervisor = module.Supervisor(
        plan=plan, root=root, ops=ops, python=Path(sys.executable),
        worker=worker, resume=True)
    started = {
        "schema": module.START_SCHEMA,
        "started_unix_seconds": 1,
        "started_monotonic_nanoseconds": 123456,
        "pid": 999999,
        "plan_summary_sha256": module.hashlib.sha256(
            plan.canonical_summary_bytes()).hexdigest(),
        "execution_plan_sha256": plan.execution_sha256(),
        "retry_authorized": False,
        "resume_authorized": True,
    }
    status = dict(supervisor.state)
    status.update({
        "state": state,
        "current_stage": "fake-stage",
        "stage_index": 1,
        "running_tasks": sorted((running or {}).keys()),
        "running_processes": dict(running or {}),
        "updated_unix_seconds": 2,
    })
    (ops / "started.json").write_bytes(
        module.canonical_json_bytes(started))
    (ops / "status.json").write_bytes(module.canonical_json_bytes(status))
    return module, supervisor, root, ops


def test_supervisor_recovery_replays_plan_without_retry_and_preserves_start(
        tmp_path):
    module, supervisor, root, ops = _recovery_fixture(tmp_path)
    started_raw = (ops / "started.json").read_bytes()

    supervisor.run()

    status = module._strict_json(ops / "status.json")
    receipt = module._strict_json(ops / "resume-01.json")
    assert (root / "recovery-command-observed").read_text(
        encoding="ascii") == "yes\n"
    assert (ops / "started.json").read_bytes() == started_raw
    assert status["state"] == "complete"
    assert status["completed_task_names"] == ["only-task"]
    assert status["resume_count"] == 1
    assert status["resume_mode"] is True
    assert status["retry_authorized"] is False
    assert receipt["original_started_monotonic_nanoseconds"] == 123456
    assert receipt["retry_authorized"] is False
    assert receipt["test_split_open_authorized"] is False
    assert (ops / "logs" / "only-task.resume-01.stdout.log").is_file()


def test_supervisor_recovery_marks_previously_completed_task_as_reopen_only(
        tmp_path):
    _, supervisor, _, _ = _recovery_fixture(tmp_path)
    supervisor.recover_existing = True
    supervisor.state["completed_task_names"] = ["only-task"]

    command = supervisor._worker_command(supervisor.plan.stages[0].tasks[0])

    assert "--recover-existing" in command
    assert "--require-existing-final" in command


def test_supervisor_recovery_refuses_failed_attempt_and_live_worker(tmp_path):
    module, failed, _, ops = _recovery_fixture(
        tmp_path / "failed", state="failed")
    with pytest.raises(
            module.BeliefV2SupervisorError,
            match="recovery status drift"):
        failed.run()
    assert not (ops / "resume-01.json").exists()


def test_supervisor_recovery_reuses_exact_receipt_after_status_write_crash(
        tmp_path, monkeypatch):
    module, interrupted, root, ops = _recovery_fixture(tmp_path)
    original_status = (ops / "status.json").read_bytes()
    real_getpid = module.os.getpid
    monkeypatch.setattr(module.os, "getpid", lambda: 12345)
    interrupted._acquire_lock()
    interrupted._update_status = lambda **_changes: (_ for _ in ()).throw(
        RuntimeError("injected status write crash"))
    with pytest.raises(RuntimeError, match="injected status write crash"):
        interrupted._prepare_resume()
    interrupted._release_lock()
    receipt_raw = (ops / "resume-01.json").read_bytes()
    assert (ops / "status.json").read_bytes() == original_status
    monkeypatch.setattr(module.os, "getpid", real_getpid)

    resumed = module.Supervisor(
        plan=interrupted.plan, root=root, ops=ops,
        python=interrupted.python, worker=interrupted.worker, resume=True)
    resumed.run()

    assert (ops / "resume-01.json").read_bytes() == receipt_raw
    assert not (ops / "resume-02.json").exists()
    assert module._strict_json(ops / "status.json")["state"] == "complete"


def test_supervisor_recovery_lock_refuses_symlink(tmp_path):
    module, supervisor, _, ops = _recovery_fixture(tmp_path)
    target = tmp_path / "lock-target"
    target.write_bytes(b"")
    target.chmod(0o600)
    (ops / "supervisor.lock").symlink_to(target)

    with pytest.raises(
            module.BeliefV2SupervisorError,
            match="lock open refused"):
        supervisor.run()

    assert not (ops / "resume-01.json").exists()

    module, live, _, ops = _recovery_fixture(
        tmp_path / "live", running={"only-task": os.getpid()})
    with pytest.raises(
            module.BeliefV2SupervisorError,
            match="recovery worker is still active"):
        live.run()
    assert not (ops / "resume-01.json").exists()
