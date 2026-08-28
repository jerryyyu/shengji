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
    def __init__(self, *, plan, root, ops, python, worker, boot_identity,
                 resume=False):
        self.python = python
        assert boot_identity == "b" * 64
        assert resume is False

    def request_stop(self, signum):
        raise AssertionError(f"unexpected signal {signum}")

    def run(self):
        print(self.python)

module.Supervisor = SupervisorProbe
module.build_supervisor_plan = lambda **_kwargs: object()
module._strict_json = lambda _path: {}
module._supervisor_boot_identity = lambda _root: "b" * 64
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


def test_supervisor_boot_identity_is_checked_against_live_freeze(
        tmp_path, monkeypatch):
    module = _load_supervisor()
    root = tmp_path / "root"
    root.mkdir()
    freeze_raw = b'{"schema":"freeze-probe"}\n'
    (root / "freeze.json").write_bytes(freeze_raw)
    freeze = SimpleNamespace(runtime=SimpleNamespace(boot_identity="b" * 64))
    monkeypatch.setattr(module, "stable_read_bytes", lambda path: (
        freeze_raw if path == root / "freeze.json" else
        (_ for _ in ()).throw(AssertionError(f"unexpected path {path}"))))
    monkeypatch.setattr(
        module, "execution_freeze_from_bytes",
        lambda raw: freeze if raw == freeze_raw else
        (_ for _ in ()).throw(AssertionError("unexpected freeze bytes")))
    monkeypatch.setattr(module, "_boot_identity", lambda: "b" * 64)

    assert module._supervisor_boot_identity(root) == "b" * 64

    monkeypatch.setattr(module, "_boot_identity", lambda: "c" * 64)
    with pytest.raises(
            module.BeliefV2SupervisorError,
            match="live boot identity drift"):
        module._supervisor_boot_identity(root)


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


def _recovery_fixture(
        tmp_path, *, state="interrupted", running=None,
        observed_monotonic_nanoseconds=None):
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
    observed = ([1_000_000_000_000_000]
                if observed_monotonic_nanoseconds is None
                else observed_monotonic_nanoseconds)
    supervisor = module.Supervisor(
        plan=plan, root=root, ops=ops, python=Path(sys.executable),
        worker=worker, boot_identity="b" * 64, resume=True,
        monotonic_ns=lambda: observed[0])
    started_monotonic = observed[0] - 1
    supervisor._bind_supervisor_deadline(started_monotonic)
    supervisor._test_observed_monotonic_nanoseconds = observed
    started = {
        "schema": module.START_SCHEMA,
        "started_unix_seconds": 1,
        "started_monotonic_nanoseconds": started_monotonic,
        "pid": 999999,
        "plan_summary_sha256": module.hashlib.sha256(
            plan.canonical_summary_bytes()).hexdigest(),
        "execution_plan_sha256": plan.execution_sha256(),
        "boot_identity": "b" * 64,
        "supervisor_wall_cap_nanoseconds": (
            module.SUPERVISOR_WALL_CAP_NANOSECONDS),
        "hard_deadline_monotonic_nanoseconds": (
            started_monotonic
            + module.SUPERVISOR_WALL_CAP_NANOSECONDS),
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
    started = module._strict_json(ops / "started.json")
    assert (root / "recovery-command-observed").read_text(
        encoding="ascii") == "yes\n"
    assert (ops / "started.json").read_bytes() == started_raw
    assert status["state"] == "complete"
    assert status["completed_task_names"] == ["only-task"]
    assert status["resume_count"] == 1
    assert status["resume_mode"] is True
    assert status["retry_authorized"] is False
    assert receipt["original_started_monotonic_nanoseconds"] \
        == started["started_monotonic_nanoseconds"]
    assert receipt["boot_identity"] == "b" * 64
    assert receipt["supervisor_wall_cap_nanoseconds"] \
        == module.SUPERVISOR_WALL_CAP_NANOSECONDS
    assert receipt["hard_deadline_monotonic_nanoseconds"] \
        == started["hard_deadline_monotonic_nanoseconds"]
    assert receipt["retry_authorized"] is False
    assert receipt["test_split_open_authorized"] is False
    assert (ops / "logs" / "only-task.resume-01.stdout.log").is_file()


def test_supervisor_recovery_refuses_expired_original_deadline_before_receipt(
        tmp_path):
    module, supervisor, _, ops = _recovery_fixture(tmp_path)
    observed = supervisor._test_observed_monotonic_nanoseconds
    started = module._strict_json(ops / "started.json")
    status = module._strict_json(ops / "status.json")
    started_at = observed[0] - module.SUPERVISOR_WALL_CAP_NANOSECONDS
    hard = started_at + module.SUPERVISOR_WALL_CAP_NANOSECONDS
    started["started_monotonic_nanoseconds"] = started_at
    started["hard_deadline_monotonic_nanoseconds"] = hard
    status["hard_deadline_monotonic_nanoseconds"] = hard
    (ops / "started.json").write_bytes(
        module.canonical_json_bytes(started))
    (ops / "status.json").write_bytes(module.canonical_json_bytes(status))

    with pytest.raises(
            module.BeliefV2SupervisorError,
            match="absolute deadline exhausted"):
        supervisor.run()

    assert not (ops / "resume-01.json").exists()
    assert module._strict_json(ops / "status.json")["state"] == "failed"


def test_supervisor_recovery_refuses_changed_boot_before_receipt(tmp_path):
    module, supervisor, _, ops = _recovery_fixture(tmp_path)
    started = module._strict_json(ops / "started.json")
    started["boot_identity"] = "c" * 64
    (ops / "started.json").write_bytes(
        module.canonical_json_bytes(started))

    with pytest.raises(
            module.BeliefV2SupervisorError,
            match="recovery start binding drift"):
        supervisor.run()

    assert not (ops / "resume-01.json").exists()


def test_supervisor_kills_active_work_at_original_absolute_deadline(
        tmp_path):
    module = _load_supervisor()
    root = (tmp_path / "root").resolve()
    root.mkdir()
    ops = (tmp_path / "ops").resolve()
    worker = (tmp_path / "slow_worker.py").resolve()
    worker.write_text(
        "from pathlib import Path\n"
        "import sys\n"
        "import time\n"
        "time.sleep(30)\n"
        "root = Path(sys.argv[sys.argv.index('--root') + 1])\n"
        "(root / 'slow-worker-finished').write_text('yes\\n')\n",
        encoding="ascii")
    observed = [1_000_000_000_000_000]
    plan = _FakePlan()
    supervisor = module.Supervisor(
        plan=plan, root=root, ops=ops, python=Path(sys.executable),
        worker=worker, boot_identity="b" * 64,
        monotonic_ns=lambda: observed[0])
    real_start = supervisor._start_task

    def start_then_expire(task):
        real_start(task)
        observed[0] += module.SUPERVISOR_WALL_CAP_NANOSECONDS

    supervisor._start_task = start_then_expire
    with pytest.raises(
            module.BeliefV2SupervisorError,
            match="absolute deadline exhausted"):
        supervisor.run()

    status = module._strict_json(ops / "status.json")
    assert status["state"] == "failed"
    assert status["current_stage"] != "complete"
    assert status["failure"] == (
        "BeliefV2SupervisorError: BELIEF V2 supervisor absolute "
        "deadline exhausted")
    assert not supervisor.active or all(
        process.poll() is not None for process in supervisor.active.values())
    assert not (root / "slow-worker-finished").exists()

    resumed = module.Supervisor(
        plan=plan, root=root, ops=ops, python=Path(sys.executable),
        worker=worker, boot_identity="b" * 64, resume=True,
        monotonic_ns=lambda: observed[0])
    with pytest.raises(
            module.BeliefV2SupervisorError,
            match="absolute deadline exhausted"):
        resumed.run()
    assert not (ops / "resume-01.json").exists()


def test_supervisor_deadline_refuses_complete_after_final_stage(tmp_path):
    module = _load_supervisor()
    root = (tmp_path / "root").resolve()
    root.mkdir()
    ops = (tmp_path / "ops").resolve()
    worker = (tmp_path / "worker.py").resolve()
    worker.write_text("pass\n", encoding="ascii")
    observed = [1_000_000_000_000_000]
    supervisor = module.Supervisor(
        plan=_FakePlan(), root=root, ops=ops, python=Path(sys.executable),
        worker=worker, boot_identity="b" * 64,
        monotonic_ns=lambda: observed[0])
    run_stage = supervisor._run_stage

    def expire_after_final_stage(stage_index):
        run_stage(stage_index)
        observed[0] += module.SUPERVISOR_WALL_CAP_NANOSECONDS

    supervisor._run_stage = expire_after_final_stage
    with pytest.raises(
            module.BeliefV2SupervisorError,
            match="absolute deadline exhausted"):
        supervisor.run()

    status = module._strict_json(ops / "status.json")
    assert status["state"] == "failed"
    assert status["current_stage"] != "complete"


def test_supervisor_deadline_blocks_partial_concurrency_launch(tmp_path):
    module = _load_supervisor()
    first = SimpleNamespace(name="first", arguments=("first",))
    second = SimpleNamespace(name="second", arguments=("second",))

    class ParallelPlan:
        stages = (SimpleNamespace(
            name="parallel", concurrency=2, tasks=(first, second)),)

        @staticmethod
        def canonical_summary_bytes():
            return b'{"schema":"parallel-plan"}\n'

        @staticmethod
        def execution_sha256():
            return "a" * 64

    root = (tmp_path / "root").resolve()
    root.mkdir()
    ops = (tmp_path / "ops").resolve()
    worker = (tmp_path / "slow-worker.py").resolve()
    worker.write_text("import time\ntime.sleep(30)\n", encoding="ascii")
    observed = [1_000_000_000_000_000]
    supervisor = module.Supervisor(
        plan=ParallelPlan(), root=root, ops=ops,
        python=Path(sys.executable), worker=worker,
        boot_identity="b" * 64, monotonic_ns=lambda: observed[0])
    start_task = supervisor._start_task

    def expire_after_first_launch(task):
        start_task(task)
        if task.name == "first":
            observed[0] += module.SUPERVISOR_WALL_CAP_NANOSECONDS

    supervisor._start_task = expire_after_first_launch
    with pytest.raises(
            module.BeliefV2SupervisorError,
            match="absolute deadline exhausted"):
        supervisor.run()

    assert (ops / "logs" / "first.stdout.log").exists()
    assert not (ops / "logs" / "second.stdout.log").exists()


def test_supervisor_deadline_blocks_next_stage_and_complete_seal(tmp_path):
    module = _load_supervisor()
    first = SimpleNamespace(name="first", arguments=("first",))
    test = SimpleNamespace(name="open-test", arguments=("open-test",))

    class TwoStagePlan:
        stages = (
            SimpleNamespace(name="calibration", concurrency=1, tasks=(first,)),
            SimpleNamespace(
                name="single-test-opening", concurrency=1, tasks=(test,)),
        )

        @staticmethod
        def canonical_summary_bytes():
            return b'{"schema":"two-stage-plan"}\n'

        @staticmethod
        def execution_sha256():
            return "f" * 64

    root = (tmp_path / "root").resolve()
    root.mkdir()
    ops = (tmp_path / "ops").resolve()
    worker = (tmp_path / "worker.py").resolve()
    worker.write_text(
        "from pathlib import Path\n"
        "import sys\n"
        "root = Path(sys.argv[sys.argv.index('--root') + 1])\n"
        "(root / (sys.argv[1] + '-ran')).write_text('yes\\n')\n",
        encoding="ascii")
    observed = [1_000_000_000_000_000]
    supervisor = module.Supervisor(
        plan=TwoStagePlan(), root=root, ops=ops,
        python=Path(sys.executable), worker=worker,
        boot_identity="b" * 64, monotonic_ns=lambda: observed[0])
    run_stage = supervisor._run_stage

    def expire_after_first_stage(stage_index):
        run_stage(stage_index)
        if stage_index == 1:
            observed[0] += module.SUPERVISOR_WALL_CAP_NANOSECONDS

    supervisor._run_stage = expire_after_first_stage
    with pytest.raises(
            module.BeliefV2SupervisorError,
            match="absolute deadline exhausted"):
        supervisor.run()

    status = module._strict_json(ops / "status.json")
    assert (root / "first-ran").read_text(encoding="ascii") == "yes\n"
    assert not (root / "open-test-ran").exists()
    assert status["state"] == "failed"
    assert status["current_stage"] != "complete"


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
        python=interrupted.python, worker=interrupted.worker,
        boot_identity=interrupted.boot_identity, resume=True,
        monotonic_ns=interrupted.monotonic_ns)
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
