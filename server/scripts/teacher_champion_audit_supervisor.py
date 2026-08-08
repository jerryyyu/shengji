#!/usr/bin/env python3
"""One-shot process supervisor for the frozen Teacher champion audit.

The result-producing implementation remains the independently frozen
``teacher_v1_champion_audit.py`` checkout.  This stdlib-only controller lives
outside that checkout and supplies the operational property that the detached
Stage-B launch lacked: it owns all eight children, records every wait status,
and will not invoke the terminal gate unless all eight label creators exited
zero and their exact final bytes are regular, complete, and reopenable.

The supervisor never retries, resumes, deletes, overwrites, chooses a state,
or changes an estimand.  Any collision, child failure, signal, identity drift,
or publication problem closes the attempt in place with its progress file
left ``.partial`` for diagnosis.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import stat
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Iterable


SCHEMA = "teacher-v1-champion-audit-supervisor-v1"
PREPARATION_SCHEMA = "teacher-v1-champion-audit-preparation-v1"
RECEIPT_EXIT_SCHEMA = "teacher-v1-champion-audit-receipt-exit-v1"
RECEIPT_SCHEMA = "teacher-v1-champion-audit-receipt-v1"
AUDIT_GIT = "1866132766c7f16542bc27e730622e2dfea639ae"
AUDIT_SCRIPT_SHA256 = (
    "c7b47a7a0305f6067129cc7b19517d9a983efff70085f83edc0d39475955d6cb"
)
EXPECTED_PYTHON_VERSION = "Python 3.14.6"
RUN_ID = "teacher-v3-report-lcb-audit-v2-149m"
NAMESPACE = Path("runs/logs/teacher-v1-entry-149m-v3")
AUDIT_SCRIPT = Path("scripts/teacher_v1_champion_audit.py")
RECEIPT_NAME = "champion_audit_receipt_v1.json"
RECEIPT_LOG_NAME = "champion_audit_receipt_v1.log"
RECEIPT_EXIT_NAME = "champion_audit_receipt_v1.exit.json"
PREPARATION_NAME = "champion_audit_preparation_v1.json"
PARENT_NAMES = (
    "stage_b_states.json",
    "stage_b_cheap_v2_receipt.json",
    "stage_b_gold_v2_receipt.json",
    *(f"stage_b_cheap_v2_shard{index:02d}.json"
      for index in range(8)),
    *(f"stage_b_gold_v2_shard{index:02d}.json"
      for index in range(8)),
    "stage_b_gate_v2.json",
)
SHARD_COUNT = 8
SELECTION_WORLDS = 32
REPORT_WORLDS = 32
LABEL_NAMES = tuple(
    f"champion_audit_v1_shard{index:02d}.json"
    for index in range(SHARD_COUNT)
)
GATE_NAME = "champion_audit_gate_v1.json"
PROGRESS_NAME = "champion_audit_supervisor_v1.jsonl"
EXPERIMENTAL_FLAGS = (
    "SHENGJI_WEIGHTED_SPLITS",
    "SHENGJI_UNIFORM_DEAL",
    "SHENGJI_PHYSICAL_FILLS",
    "SHENGJI_ALLOW_BALLOT_MISMATCH",
)


def expected_receipt_identity() -> dict[str, object]:
    """Return the receipt authority independently enforced at launch."""
    return {
        "schema": RECEIPT_SCHEMA,
        "complete": True,
        "run_id": RUN_ID,
        "execution_predeclaration": {
            "git": AUDIT_GIT,
            "audit_script_sha256": AUDIT_SCRIPT_SHA256,
        },
    }


class SupervisorRefusal(RuntimeError):
    """A fail-closed one-shot supervisor boundary was violated."""


@dataclass(frozen=True)
class Config:
    audit_root: Path
    python: Path
    expected_receipt_sha256: str
    expected_preparation_sha256: str
    expected_preparer_sha256: str
    expected_supervisor_sha256: str
    heartbeat_seconds: float = 60.0


@dataclass(frozen=True)
class Paths:
    root: Path
    namespace: Path
    audit_script: Path
    receipt: Path
    receipt_log: Path
    receipt_exit: Path
    preparation: Path
    labels: tuple[Path, ...]
    gate: Path
    progress_partial: Path
    progress_final: Path


@dataclass
class RunningJob:
    name: str
    argv: tuple[str, ...]
    process: subprocess.Popen
    log_handle: IO[str]
    log_partial: Path
    log_final: Path
    exit_final: Path
    output: Path
    finished: bool = False


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_sha256(value: object) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(character in "0123456789abcdef" for character in value))


def is_regular_unlinked(path: Path) -> bool:
    try:
        return stat.S_ISREG(path.lstat().st_mode)
    except FileNotFoundError:
        return False


def lexists(path: Path) -> bool:
    return os.path.lexists(path)


def artifact_partial(path: Path) -> Path:
    return Path(str(path) + ".partial")


def paths_for(root: Path) -> Paths:
    root = root.resolve()
    namespace = root / NAMESPACE
    return Paths(
        root=root,
        namespace=namespace,
        audit_script=root / AUDIT_SCRIPT,
        receipt=namespace / RECEIPT_NAME,
        receipt_log=namespace / RECEIPT_LOG_NAME,
        receipt_exit=namespace / RECEIPT_EXIT_NAME,
        preparation=namespace / PREPARATION_NAME,
        labels=tuple(namespace / name for name in LABEL_NAMES),
        gate=namespace / GATE_NAME,
        progress_partial=namespace / f"{PROGRESS_NAME}.partial",
        progress_final=namespace / PROGRESS_NAME,
    )


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, check=True,
        capture_output=True, text=True,
    ).stdout.strip()


def _exclusive_publish(partial: Path, final: Path) -> None:
    try:
        os.link(partial, final)
    except FileExistsError as exc:
        raise SupervisorRefusal(f"refusing to overwrite {final}") from exc
    os.unlink(partial)


def _write_json_exclusive(path: Path, payload: dict) -> None:
    partial = artifact_partial(path)
    try:
        with partial.open("x", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        _exclusive_publish(partial, path)
    except FileExistsError as exc:
        raise SupervisorRefusal(
            f"refusing existing status artifact {path}") from exc


class Progress:
    def __init__(self, paths: Paths):
        try:
            self._handle = paths.progress_partial.open("x", encoding="utf-8")
        except FileExistsError as exc:
            raise SupervisorRefusal(
                f"refusing existing progress {paths.progress_partial}") from exc
        self.paths = paths
        self.closed = False

    def event(self, phase: str, status: str, **fields: object) -> None:
        payload = {
            "schema": SCHEMA,
            "time_ns": time.time_ns(),
            "phase": phase,
            "status": status,
            **fields,
        }
        self._handle.write(json.dumps(
            payload, sort_keys=True, separators=(",", ":")) + "\n")
        self._handle.flush()
        os.fsync(self._handle.fileno())
        visible = {key: value for key, value in payload.items()
                   if key not in {"schema", "time_ns"}}
        print(json.dumps(visible, sort_keys=True), flush=True)

    def close(self) -> None:
        if not self.closed:
            self._handle.close()
            self.closed = True

    def publish(self) -> None:
        self.close()
        _exclusive_publish(self.paths.progress_partial,
                           self.paths.progress_final)


def _artifact_problems(path: Path, expected_sha256: str) -> list[str]:
    problems = []
    if not is_regular_unlinked(path):
        problems.append(f"missing/nonregular artifact {path}")
    elif sha256_file(path) != expected_sha256:
        problems.append(f"artifact SHA drift {path}")
    if lexists(artifact_partial(path)):
        problems.append(f"artifact partial exists {artifact_partial(path)}")
    return problems


def _load_json(path: Path) -> dict:
    try:
        payload = json.loads(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise SupervisorRefusal(f"artifact cannot reopen {path}: {exc}") \
            from exc
    if not isinstance(payload, dict):
        raise SupervisorRefusal(f"artifact is not an object {path}")
    return payload


def _preparation_problems(config: Config, paths: Paths) -> list[str]:
    if not is_sha256(config.expected_preparation_sha256):
        return ["expected preparation SHA is malformed"]
    problems = _artifact_problems(
        paths.preparation, config.expected_preparation_sha256)
    if problems:
        return problems
    try:
        preparation = _load_json(paths.preparation)
    except SupervisorRefusal as exc:
        return [str(exc)]
    expected_receipt = {
        "path": str(NAMESPACE / RECEIPT_NAME),
        "sha256": config.expected_receipt_sha256,
    }
    if (preparation.get("schema") != PREPARATION_SCHEMA
            or preparation.get("complete") is not True
            or preparation.get("audit_git") != AUDIT_GIT
            or preparation.get("audit_script_sha256")
            != AUDIT_SCRIPT_SHA256
            or preparation.get("python") != EXPECTED_PYTHON_VERSION
            or preparation.get("preparer_sha256")
            != config.expected_preparer_sha256
            or preparation.get("expected_supervisor_sha256")
            != config.expected_supervisor_sha256
            or preparation.get("receipt_identity")
            != expected_receipt_identity()
            or preparation.get("receipt") != expected_receipt
            or preparation.get("audit_labels_authorized") is not True
            or preparation.get("retry_authorized") is not False
            or preparation.get("production_promotion") is not False):
        problems.append("audit preparation authority/identity drift")
    expected_parents = {str(NAMESPACE / name) for name in PARENT_NAMES}
    copied = preparation.get("copied_parents")
    if (not isinstance(copied, list) or len(copied) != len(PARENT_NAMES)
            or {item.get("path") for item in copied
                if isinstance(item, dict)} != expected_parents
            or any(not isinstance(item, dict)
                   or not is_sha256(item.get("sha256")) for item in copied)):
        problems.append("audit preparation copied-parent population drift")
    else:
        for item in copied:
            problems += _artifact_problems(
                paths.root / str(item["path"]), str(item["sha256"]))
    for label, path, field in (
            ("receipt log", paths.receipt_log, "receipt_log"),
            ("receipt exit", paths.receipt_exit, "receipt_exit")):
        binding = preparation.get(field)
        if (not isinstance(binding, dict)
                or binding.get("path") != str(NAMESPACE / path.name)
                or not is_sha256(binding.get("sha256"))):
            problems.append(f"audit preparation {label} binding drift")
            continue
        problems += _artifact_problems(path, str(binding["sha256"]))
    try:
        exit_payload = _load_json(paths.receipt_exit)
    except SupervisorRefusal as exc:
        problems.append(str(exc))
    else:
        receipt_exit = preparation.get("receipt_exit")
        if (exit_payload.get("schema") != RECEIPT_EXIT_SCHEMA
                or exit_payload.get("complete") is not True
                or exit_payload.get("returncode") != 0
                or not isinstance(receipt_exit, dict)
                or receipt_exit.get("returncode") != 0):
            problems.append("audit receipt creator did not have exact zero exit")
    return sorted(set(problems))


def _receipt_identity_problems(paths: Paths) -> list[str]:
    try:
        receipt = _load_json(paths.receipt)
    except SupervisorRefusal as exc:
        return [str(exc)]
    expected = expected_receipt_identity()
    if any(receipt.get(key) != value for key, value in expected.items()):
        return ["audit receipt authority/identity drift"]
    return []


def _owned_names(paths: Paths) -> Iterable[Path]:
    yield paths.gate
    yield paths.progress_final
    yield paths.progress_partial
    for output in paths.labels:
        yield output
        yield output.with_suffix(".log")
        yield output.with_suffix(".exit.json")
    yield paths.gate.with_suffix(".log")
    yield paths.gate.with_suffix(".exit.json")


def preflight_problems(config: Config, paths: Paths) -> list[str]:
    problems = []
    try:
        head = _git(paths.root, "rev-parse", "HEAD")
        dirty = _git(
            paths.root, "status", "--porcelain", "--untracked-files=all")
    except (OSError, subprocess.SubprocessError) as exc:
        return [f"audit git inspection failed: {exc}"]
    if head != AUDIT_GIT:
        problems.append(f"audit git {head}, expected {AUDIT_GIT}")
    if dirty:
        problems.append("audit worktree is dirty")
    if not paths.namespace.is_dir():
        problems.append(f"audit namespace missing {paths.namespace}")
    if not is_regular_unlinked(paths.audit_script):
        problems.append("frozen audit script is missing/nonregular")
    elif sha256_file(paths.audit_script) != AUDIT_SCRIPT_SHA256:
        problems.append("frozen audit script SHA drift")
    if not config.python.is_file() or not os.access(config.python, os.X_OK):
        problems.append(f"audit Python is not executable {config.python}")
    else:
        try:
            version_run = subprocess.run(
                [str(config.python), "--version"], check=False,
                capture_output=True, text=True)
            version = (version_run.stdout or version_run.stderr).strip()
        except OSError as exc:
            problems.append(f"audit Python version check failed: {exc}")
        else:
            if (version_run.returncode != 0
                    or version != EXPECTED_PYTHON_VERSION):
                problems.append(
                    f"audit Python {version!r}, expected "
                    f"{EXPECTED_PYTHON_VERSION!r}")
    if (not is_sha256(config.expected_supervisor_sha256)
            or sha256_file(Path(__file__).resolve())
            != config.expected_supervisor_sha256):
        problems.append("external supervisor SHA predeclaration drift")
    if not is_sha256(config.expected_receipt_sha256):
        problems.append("expected receipt SHA is malformed")
    else:
        receipt_problems = _artifact_problems(
            paths.receipt, config.expected_receipt_sha256)
        problems += receipt_problems
        if not receipt_problems:
            problems += _receipt_identity_problems(paths)
    problems += _preparation_problems(config, paths)
    for path in _owned_names(paths):
        if lexists(path) or lexists(artifact_partial(path)):
            problems.append(f"one-shot output collision {path}")
    try:
        rows = subprocess.run(
            ["ps", "-axo", "command="], check=True,
            capture_output=True, text=True,
        ).stdout.splitlines()
    except (OSError, subprocess.SubprocessError) as exc:
        problems.append(f"process inspection failed: {exc}")
    else:
        target = paths.audit_script.name
        if any(target in row and " label " in f" {row} " for row in rows):
            problems.append("champion audit label worker already exists")
    return sorted(set(problems))


def child_environment() -> dict[str, str]:
    env = dict(os.environ)
    for name in EXPERIMENTAL_FLAGS:
        env.pop(name, None)
    env.update({
        "SHENGJI_FAST": "1",
        "SHENGJI_REQUIRE_VOIDS": "1",
        "PYTHONUNBUFFERED": "1",
    })
    return env


def label_command(config: Config, paths: Paths, shard: int) -> tuple[str, ...]:
    return (
        str(config.python), str(paths.audit_script), "label",
        "--receipt", str(paths.receipt),
        "--expected-receipt-sha256", config.expected_receipt_sha256,
        "--shard-index", str(shard),
        "--shard-count", str(SHARD_COUNT),
        "--selection-worlds", str(SELECTION_WORLDS),
        "--report-worlds", str(REPORT_WORLDS),
        "--out", str(paths.labels[shard]),
    )


def gate_command(config: Config, paths: Paths,
                 label_sha256s: tuple[str, ...]) -> tuple[str, ...]:
    argv = [
        str(config.python), str(paths.audit_script), "gate",
        "--receipt", str(paths.receipt),
        "--expected-receipt-sha256", config.expected_receipt_sha256,
    ]
    for path, digest in zip(paths.labels, label_sha256s, strict=True):
        argv.extend(("--input", str(path),
                     "--expected-input-sha256", digest))
    argv.extend(("--out", str(paths.gate)))
    return tuple(argv)


def _start_job(name: str, argv: tuple[str, ...], output: Path,
               *, paths: Paths, env: dict[str, str]) -> RunningJob:
    log_final = output.with_suffix(".log")
    log_partial = artifact_partial(log_final)
    exit_final = output.with_suffix(".exit.json")
    try:
        log_handle = log_partial.open("x", encoding="utf-8")
    except FileExistsError as exc:
        raise SupervisorRefusal(
            f"refusing existing child log {log_partial}") from exc
    try:
        process = subprocess.Popen(
            argv, cwd=paths.root, env=env, stdout=log_handle,
            stderr=subprocess.STDOUT, text=True,
        )
    except BaseException:
        log_handle.close()
        raise
    return RunningJob(
        name=name, argv=argv, process=process, log_handle=log_handle,
        log_partial=log_partial, log_final=log_final,
        exit_final=exit_final, output=output,
    )


def _finish_job(job: RunningJob, returncode: int) -> None:
    if job.finished:
        return
    job.log_handle.flush()
    os.fsync(job.log_handle.fileno())
    job.log_handle.close()
    _exclusive_publish(job.log_partial, job.log_final)
    _write_json_exclusive(job.exit_final, {
        "schema": SCHEMA,
        "job": job.name,
        "pid": job.process.pid,
        "returncode": returncode,
        "argv_sha256": hashlib.sha256(
            "\0".join(job.argv).encode("utf-8")).hexdigest(),
    })
    job.finished = True


def _stop_jobs(jobs: Iterable[RunningJob]) -> None:
    live = [job for job in jobs if job.process.poll() is None]
    for job in live:
        job.process.terminate()
    deadline = time.monotonic() + 10.0
    for job in live:
        remaining = max(0.0, deadline - time.monotonic())
        try:
            job.process.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            job.process.kill()
            job.process.wait()
    for job in jobs:
        code = job.process.poll()
        if code is not None and not job.finished:
            try:
                _finish_job(job, code)
            except Exception:
                # Preserve the first refusal; surviving .partial files are
                # intentional evidence that the attempt did not complete.
                pass


def _wait_labels(jobs: list[RunningJob], progress: Progress,
                 heartbeat_seconds: float) -> None:
    pending = {job.name: job for job in jobs}
    last_heartbeat = time.monotonic()
    interval = max(0.05, heartbeat_seconds)
    while pending:
        for name, job in list(pending.items()):
            code = job.process.poll()
            if code is None:
                continue
            _finish_job(job, code)
            progress.event("label", "exit", job=name, pid=job.process.pid,
                           returncode=code)
            del pending[name]
            if code != 0:
                raise SupervisorRefusal(f"{name} exited {code}; no gate")
            if not is_regular_unlinked(job.output):
                raise SupervisorRefusal(
                    f"{name} exited zero without regular final")
            if lexists(artifact_partial(job.output)):
                raise SupervisorRefusal(
                    f"{name} exited zero with surviving partial")
        now = time.monotonic()
        if pending and now - last_heartbeat >= interval:
            progress.event(
                "label", "heartbeat", live=len(pending),
                completed=SHARD_COUNT - len(pending),
                pids=[pending[name].process.pid for name in sorted(pending)],
            )
            last_heartbeat = now
        if pending:
            time.sleep(min(0.25, interval))


def _reopen_label(path: Path, shard_index: int) -> str:
    try:
        payload = json.loads(path.read_bytes())
    except (OSError, ValueError) as exc:
        raise SupervisorRefusal(
            f"label {shard_index} cannot reopen: {exc}") from exc
    if (payload.get("schema") != "teacher-v1-champion-audit-shard-v1"
            or payload.get("complete") is not True
            or payload.get("shard_index") != shard_index
            or payload.get("shard_count") != SHARD_COUNT):
        raise SupervisorRefusal(
            f"label {shard_index} publication identity drift")
    return sha256_file(path)


def _run_gate(config: Config, paths: Paths, progress: Progress,
              label_sha256s: tuple[str, ...], env: dict[str, str]
              ) -> tuple[int, str, str]:
    job = _start_job(
        "gate", gate_command(config, paths, label_sha256s), paths.gate,
        paths=paths, env=env)
    progress.event("gate", "started", pid=job.process.pid)
    try:
        code = job.process.wait()
        _finish_job(job, code)
    except BaseException:
        if job.process.poll() is None:
            job.process.terminate()
            try:
                job.process.wait(timeout=10.0)
            except subprocess.TimeoutExpired:
                job.process.kill()
                job.process.wait()
        stopped = job.process.poll()
        if stopped is not None and not job.finished:
            try:
                _finish_job(job, stopped)
            except Exception:
                pass
        raise
    if code not in (0, 4):
        raise SupervisorRefusal(f"terminal gate exited {code}")
    if not is_regular_unlinked(paths.gate):
        raise SupervisorRefusal("terminal gate lacks a regular final")
    if lexists(artifact_partial(paths.gate)):
        raise SupervisorRefusal("terminal gate left a partial")
    try:
        payload = json.loads(paths.gate.read_bytes())
    except (OSError, ValueError) as exc:
        raise SupervisorRefusal(f"terminal gate cannot reopen: {exc}") from exc
    verdict = payload.get("verdict")
    expected_pass = code == 0
    if (payload.get("schema") != "teacher-v1-champion-audit-gate-v1"
            or payload.get("complete") is not True
            or payload.get("terminal") is not True
            or payload.get("extension_authorized") is not False
            or verdict not in {"PASS", "FAIL", "INCONCLUSIVE"}
            or (verdict == "PASS") is not expected_pass
            or payload.get("champion_fidelity_qualified") is not expected_pass
            or payload.get("stage_c_authorized") is not expected_pass):
        raise SupervisorRefusal("terminal gate exit/verdict contract drift")
    digest = sha256_file(paths.gate)
    return code, str(verdict), digest


def run(config: Config) -> tuple[int, dict]:
    paths = paths_for(config.audit_root)
    problems = preflight_problems(config, paths)
    if problems:
        raise SupervisorRefusal("preflight: " + "; ".join(problems))
    progress = Progress(paths)
    jobs: list[RunningJob] = []
    env = child_environment()
    try:
        progress.event(
            "supervisor", "admitted", audit_git=AUDIT_GIT,
            run_id=RUN_ID,
            execution_predeclaration=expected_receipt_identity()[
                "execution_predeclaration"],
            audit_script_sha256=AUDIT_SCRIPT_SHA256,
            supervisor_sha256=config.expected_supervisor_sha256,
            receipt_sha256=config.expected_receipt_sha256,
            preparation_sha256=config.expected_preparation_sha256,
            preparer_sha256=config.expected_preparer_sha256,
            shard_count=SHARD_COUNT, selection_worlds=SELECTION_WORLDS,
            report_worlds=REPORT_WORLDS,
        )
        for shard, output in enumerate(paths.labels):
            job = _start_job(
                f"label-{shard:02d}",
                label_command(config, paths, shard), output,
                paths=paths, env=env)
            jobs.append(job)
            progress.event("label", "started", shard_index=shard,
                           pid=job.process.pid)
        _wait_labels(jobs, progress, config.heartbeat_seconds)
        label_sha256s = tuple(
            _reopen_label(path, shard)
            for shard, path in enumerate(paths.labels)
        )
        progress.event("label", "population_complete",
                       sha256s=list(label_sha256s))
        gate_code, verdict, gate_sha256 = _run_gate(
            config, paths, progress, label_sha256s, env)
        summary = {
            "schema": SCHEMA,
            "complete": True,
            "run_id": RUN_ID,
            "execution_predeclaration": expected_receipt_identity()[
                "execution_predeclaration"],
            "audit_git": AUDIT_GIT,
            "audit_script_sha256": AUDIT_SCRIPT_SHA256,
            "supervisor_sha256": config.expected_supervisor_sha256,
            "receipt_sha256": config.expected_receipt_sha256,
            "preparation_sha256": config.expected_preparation_sha256,
            "preparer_sha256": config.expected_preparer_sha256,
            "label_sha256s": list(label_sha256s),
            "gate_sha256": gate_sha256,
            "gate_verdict": verdict,
            "gate_returncode": gate_code,
            "retry_authorized": False,
        }
        progress.event("supervisor", "terminal", **summary)
        progress.publish()
        return gate_code, summary
    except BaseException:
        _stop_jobs(jobs)
        progress.close()
        raise


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser()
    ap.add_argument("--audit-root", required=True)
    ap.add_argument("--python", required=True)
    ap.add_argument("--expected-receipt-sha256", required=True)
    ap.add_argument("--expected-preparation-sha256", required=True)
    ap.add_argument("--expected-preparer-sha256", required=True)
    ap.add_argument("--expected-supervisor-sha256", required=True)
    ap.add_argument("--heartbeat-seconds", type=float, default=60.0)
    return ap


def main() -> None:
    args = parser().parse_args()
    root = Path(args.audit_root).resolve()
    python = Path(args.python).expanduser()
    if not python.is_absolute():
        python = (Path.cwd() / python).absolute()
    config = Config(
        audit_root=root,
        # Keep the venv path itself rather than resolving its interpreter
        # symlink; CPython uses that path to locate the venv's site packages.
        python=python,
        expected_receipt_sha256=args.expected_receipt_sha256,
        expected_preparation_sha256=args.expected_preparation_sha256,
        expected_preparer_sha256=args.expected_preparer_sha256,
        expected_supervisor_sha256=args.expected_supervisor_sha256,
        heartbeat_seconds=args.heartbeat_seconds,
    )

    def refuse_signal(signum, _frame) -> None:
        raise SupervisorRefusal(f"received signal {signum}")

    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, refuse_signal)
    try:
        code, summary = run(config)
    except (OSError, subprocess.SubprocessError, SupervisorRefusal) as exc:
        print(f"REFUSING: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(3)
    print(json.dumps(summary, indent=2, sort_keys=True), flush=True)
    raise SystemExit(code)


if __name__ == "__main__":
    main()
