"""One sequential host campaign; optional bounded capacity-only call retries.

Never retries a failed row or overwrites a previous campaign.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys
import time

from shengji.luna.benchmark_transport import CAPACITY_RETRY_DELAYS
from shengji.luna.benchmark_failure_protocol import PRESERVE_ILLEGAL
from shengji.luna import sol_memory_guard as benchmark_batch


ROWS = ("smv3-pv", "soft-pv", "js-m1-shortlist", "m1-prior", "w32-original",
        "mc-lcb", "mc-strong", "mc", "smart")
RECOVERY_SCHEMA = "sol-six-row-recovery-v1"
RECOVERY_ROWS = ROWS[3:]
STAGE1_SCHEMA = "sol-feedback-on-stage1-v1"
STAGE1_ROWS = ("smv3-pv", "m1-prior")
STAGE2_SCHEMA = "sol-feedback-on-stage2-v1"
STAGE2_ROWS = ("smart", "mc-lcb", "soft-pv", "js-m1-shortlist",
               "w32-original", "mc-strong", "mc")
RECOVERY_MEMORY_WAIT = {"timeout_seconds": 1800, "poll_seconds": 60}
def default_reservation_path(platform):
    # Linux fleet screens use this same atomic directory reservation. A
    # Sol-only name cannot exclude an already-running screen on that host.
    if platform == "linux":
        return Path("/root/.claude-host.lock")
    return Path("/private/tmp/shengji-sol-panel-mini.lock")


LOCK = default_reservation_path(sys.platform)
SOURCE_SUFFIXES = frozenset({".py", ".so"})

CONTROL_FLAGS = {
    'capacity_retries': '--retry-provider-capacity',
    'accept_recovered_reconnects': '--accept-recovered-reconnects',
    'invalid_action_feedback': '--invalid-action-feedback',
    'classify_final_action_failures': '--classify-final-action-failures',
}


def recovery_control_args(config):
    controls = config.get('recovery_controls')
    if (type(controls) is not dict or set(controls) != set(CONTROL_FLAGS)
            or any(type(v) is not bool for v in controls.values())
            or not controls['classify_final_action_failures']):
        raise ValueError('explicit strict-bool recovery controls with attribution required')
    expected = list(CAPACITY_RETRY_DELAYS) if controls['capacity_retries'] else []
    if config.get('provider_capacity_retry_delays', []) != expected:
        raise ValueError('recovery retry declaration mismatch')
    return [flag for key, flag in CONTROL_FLAGS.items() if controls[key]]


class StampSet(dict):
    """Validated stamps plus the exact frozen source inventory."""

    source_root: Path | None = None
    source_inventory: frozenset[str] = frozenset()


def publish(path, value):
    raw = json.dumps(value, sort_keys=True, allow_nan=False).encode()
    temporary = path.with_name(path.name + ".partial")
    with temporary.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    os.link(temporary, path)
    temporary.unlink()


def stamp(path):
    info = path.lstat()
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"regular file required: {path}")
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


def source_inventory(root):
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("source root must be a regular directory")
    inventory = {}
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"source inventory symlink: {path}")
        if path.is_file() and path.suffix in SOURCE_SUFFIXES:
            inventory[path.relative_to(root).as_posix()] = path
    return inventory


def validate(config_path, expected):
    raw = config_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError("campaign config hash mismatch")
    config = json.loads(raw)
    schema = config.get("schema")
    recovery = schema == RECOVERY_SCHEMA
    stage1 = schema in (STAGE1_SCHEMA, STAGE2_SCHEMA)
    stage_rows = STAGE2_ROWS if schema == STAGE2_SCHEMA else STAGE1_ROWS
    controlled = recovery or stage1
    retries = config.get("provider_capacity_retry_delays", [])
    if controlled:
        recovery_control_args(config)
    if stage1 and config['recovery_controls'] != {
            'capacity_retries': True, 'accept_recovered_reconnects': False,
            'invalid_action_feedback': True, 'classify_final_action_failures': True}:
        raise ValueError('stage1 feedback/control recipe drift')
    expected_retries = (list(CAPACITY_RETRY_DELAYS)
                        if schema == "sol-nine-policy-campaign-v2" or
                        (controlled and config['recovery_controls']['capacity_retries']) else [])
    if (schema not in ("sol-nine-policy-campaign-v1", "sol-nine-policy-campaign-v2", RECOVERY_SCHEMA, STAGE1_SCHEMA, STAGE2_SCHEMA)
            or type(retries) is not list
            or any(type(delay) is not int for delay in retries)
            or retries != expected_retries
            or config.get("rows") != list(stage_rows if stage1 else RECOVERY_ROWS if recovery else ROWS)
            or config.get("row_wall_seconds") != 43200
            or config.get("row_soft_tokens") != 45000000
            or config.get("provider_call_seconds") != 300):
        raise ValueError("campaign recipe drift")
    if stage1:
        if (config.get("failure_protocol") != PRESERVE_ILLEGAL
                or type(config.get("illegal_failure_limit")) is not int
                or config['illegal_failure_limit'] != 8
                or 'retention' in config or 'memory_wait' in config):
            raise ValueError('stage1 requires fresh rows and bounded failure protocol')
    elif recovery:
        if (config.get("failure_protocol") != PRESERVE_ILLEGAL
                or type(config.get("illegal_failure_limit")) is not int
                or config["illegal_failure_limit"] != 8
                or type(config.get("retention")) is not dict
                or set(config["retention"]) != {"m1-prior"}
                or type(config["retention"]["m1-prior"]) is not dict
                or set(config["retention"]["m1-prior"]) != {"plan", "sha256"}):
            raise ValueError("recovery protocol or retention recipe drift")
        if "memory_wait" in config:
            memory_wait = config["memory_wait"]
            if (type(memory_wait) is not dict
                    or set(memory_wait) != set(RECOVERY_MEMORY_WAIT)
                    or any(type(memory_wait[key]) is not int
                           for key in RECOVERY_MEMORY_WAIT)
                    or memory_wait != RECOVERY_MEMORY_WAIT):
                raise ValueError("recovery memory_wait recipe drift")
    elif any(key in config for key in
             ("failure_protocol", "illegal_failure_limit", "retention", "memory_wait", "recovery_controls")):
        raise ValueError("recovery fields require recovery schema")
    seeds = config["seeds"]
    if (len(seeds) != 10 or len(set(seeds)) != 10
            or any(type(seed) is not int or seed < 0 for seed in seeds)):
        raise ValueError("exactly ten distinct fresh seeds required")
    root = Path(config["source_root"])
    inventory = source_inventory(root)
    source_files = config["source_files"]
    if not isinstance(source_files, dict) or set(source_files) != set(inventory):
        raise ValueError("source inventory drift")
    stamps = StampSet()
    if recovery:
        retained = config["retention"]["m1-prior"]
        plan = Path(retained["plan"])
        if not plan.is_absolute():
            raise ValueError("retention plan must be absolute")
        stamps[plan] = stamp(plan)
        if hashlib.sha256(plan.read_bytes()).hexdigest() != retained["sha256"]:
            raise ValueError("retention plan hash mismatch")
        # The runner authenticates the source and mirror contents before any
        # provider work. This fence also catches changes between dispatches.
        retention = json.loads(plan.read_bytes())
        source = Path(retention["source_directory"])
        if not source.is_absolute() or source.is_symlink() or not source.is_dir():
            raise ValueError("invalid retention source directory")
        for path in (source / "result.json", *source.glob("mirror-*.json")):
            stamps[path] = stamp(path)
    stamps.source_root = root
    stamps.source_inventory = frozenset(inventory)
    for relative, digest in source_files.items():
        relative = Path(relative)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("source manifest path escape")
        path = inventory[relative.as_posix()]
        stamps[path] = stamp(path)
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError(f"source drift: {path}")
    for path in (Path(config["model_assets"]), Path(config["prepared_roots"]) / "result.json",
                 Path(config["codex_binary"]), Path(config["python"]).resolve()):
        stamps[path] = stamp(path)
    # Recovery packets must bind the executable, not merely its path. Honor
    # declared pins on historical packets too, while allowing their old schema
    # without this field. Hash once; the existing row fences detect later edits.
    if controlled or "codex_binary_sha256" in config:
        digest = config.get("codex_binary_sha256")
        if (type(digest) is not str or len(digest) != 64
                or any(char not in "0123456789abcdef" for char in digest)):
            raise ValueError("Codex binary SHA256 pin required")
        binary = Path(config["codex_binary"])
        with binary.open("rb") as handle:
            actual = hashlib.file_digest(handle, "sha256").hexdigest()
        if actual != digest or stamp(binary) != stamps[binary]:
            raise ValueError("Codex binary hash or identity drift")
    if hashlib.sha256(Path(config["model_assets"]).read_bytes()).hexdigest() != config["model_assets_sha256"]:
        raise ValueError("model mapping drift")
    assets = json.loads(Path(config["model_assets"]).read_bytes())
    for path in assets.values():
        stamps[Path(path)] = stamp(Path(path))
    # Full model identity is verified by the existing recipe factory on first
    # use in each row; do not add a second campaign-wide model read here.
    for path in Path(config["prepared_roots"]).glob("root-*.json"):
        stamps[path] = stamp(path)
    if hashlib.sha256((Path(config["prepared_roots"]) / "result.json").read_bytes()).hexdigest() != config["prepared_roots_sha256"]:
        raise ValueError("root-source drift")
    return config, stamps


def fence(stamps):
    if isinstance(stamps, StampSet) and stamps.source_root is not None:
        current = source_inventory(stamps.source_root)
        if frozenset(current) != stamps.source_inventory:
            raise ValueError("source inventory changed after validation")
    if any(stamp(path) != original for path, original in stamps.items()):
        raise ValueError("campaign source/assets changed after validation")


def _require_recovery_memory(stage: str) -> None:
    """Fail closed on the reviewed recovery-only memory admission gate."""
    try:
        safe = benchmark_batch.assert_memory_headroom()
    except BaseException as exc:
        raise ValueError(
            f"recovery memory headroom check failed before {stage}") from exc
    if safe is not True:
        raise ValueError(f"recovery memory headroom unsafe before {stage}")


def _require_recovery_release(config_path, expected) -> None:
    """Require the recovery RELEASE marker to bind this exact config digest."""
    if (type(expected) is not str
            or re.fullmatch(r"[0-9a-f]{64}", expected) is None):
        raise ValueError("invalid recovery RELEASE digest")
    release = Path(config_path).parent / "RELEASE"
    flags = os.O_RDONLY
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    if not nofollow:
        raise ValueError("recovery RELEASE requires O_NOFOLLOW support")
    flags |= nofollow
    nonblock = getattr(os, "O_NONBLOCK", 0)
    if nonblock:
        flags |= nonblock
    fd = None
    try:
        fd = os.open(release, flags)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("recovery RELEASE must be a regular file")
        payload = os.read(fd, 67)
    except (OSError, ValueError) as exc:
        raise ValueError("missing, malformed, or unsafe recovery RELEASE") from exc
    finally:
        if fd is not None:
            os.close(fd)
    if payload.endswith(b"\n"):
        payload = payload[:-1]
    if payload != expected.encode("ascii"):
        raise ValueError("recovery RELEASE digest mismatch")


def _wait_for_recovery_row_memory(config, hold, stage: str, *, log=None) -> None:
    """Wait for memory only between completed recovery rows."""
    wait = config.get("memory_wait")
    if wait is None:
        _require_recovery_memory(stage)
        return
    started = time.monotonic()
    deadline = started + wait["timeout_seconds"]
    polls = 0

    def event(kind, **fields):
        if log is not None:
            print(json.dumps({"event": kind, "stage": stage,
                              "elapsed_seconds": time.monotonic() - started,
                              "polls": polls, **fields}), file=log, flush=True)

    event("memory-wait-start", **wait)
    while True:
        if os.path.lexists(hold):
            event("memory-wait-outcome", outcome="hold")
            raise ValueError("HOLD before row dispatch")
        # A check exactly at the deadline is permitted; an overslept poll is
        # not allowed to extend the bounded admission window.
        if time.monotonic() > deadline:
            event("memory-wait-outcome", outcome="timeout")
            raise ValueError(f"recovery memory headroom unsafe before {stage}")
        try:
            polls += 1
            safe = benchmark_batch.assert_memory_headroom()
        except BaseException as exc:
            event("memory-wait-outcome", outcome="probe-error", error_type=type(exc).__name__)
            raise ValueError(
                f"recovery memory headroom check failed before {stage}") from exc
        event("memory-wait-poll", safe=safe is True)
        if os.path.lexists(hold):
            event("memory-wait-outcome", outcome="hold")
            raise ValueError("HOLD before row dispatch")
        if safe is True:
            # The probe itself must not extend the bounded admission window.
            if time.monotonic() <= deadline:
                event("memory-wait-outcome", outcome="admitted")
                return
            event("memory-wait-outcome", outcome="timeout")
            raise ValueError(f"recovery memory headroom unsafe before {stage}")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            event("memory-wait-outcome", outcome="timeout")
            raise ValueError(f"recovery memory headroom unsafe before {stage}")
        time.sleep(min(wait["poll_seconds"], remaining))


@contextmanager
def reservation(path, *, shared_host=False):
    path.mkdir(mode=0o700)  # No waiting through or replacing another owner.
    identity = path.stat().st_dev, path.stat().st_ino
    try:
        publish(path / "owner.json", {"pid": os.getpid(), "campaign": "sol-nine-policy"})
        if shared_host:
            # Screen launchers display the first field of this text file as
            # the owner PID. They arbitrate by mkdir, not by this metadata.
            with (path / "owner").open("x") as handle:
                handle.write(f"{os.getpid()} sol-nine-policy\n")
        yield
    finally:
        if path.exists() and (path.stat().st_dev, path.stat().st_ino) == identity:
            (path / "owner.json").unlink(missing_ok=True)
            if shared_host:
                owner = path / "owner"
                if (not owner.is_symlink() and owner.is_file()
                        and owner.read_text() == f"{os.getpid()} sol-nine-policy\n"):
                    owner.unlink()
            path.rmdir()  # Unexpected peer contents refuse destructive cleanup.


def _start_contained_process(command, *, cwd, env, log, python):
    """Start one row behind the shared parent-death watchdog wrapper."""
    read_fd, watchdog_fd = os.pipe()
    wrapper = [python, "-B", "-m", "shengji.luna.watchdog",
               str(read_fd), *command]
    try:
        return subprocess.Popen(
            wrapper, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=log,
            stderr=subprocess.STDOUT, start_new_session=True,
            pass_fds=(read_fd,)), watchdog_fd
    except BaseException:
        os.close(watchdog_fd)
        raise
    finally:
        os.close(read_fd)


def supervise(command, *, cwd, env, log, row, output, wall=43200, python=sys.executable):
    start = time.monotonic()
    child, watchdog_fd = _start_contained_process(
        command, cwd=cwd, env=env, log=log, python=python)
    timed_out = False
    try:
        while child.poll() is None:
            remaining = wall - (time.monotonic() - start)
            if remaining <= 0:
                timed_out = True
                break
            try:
                child.wait(timeout=min(30, remaining))
            except subprocess.TimeoutExpired:
                completed = len(list(output.glob("mirror-*.json"))) if output.exists() else 0
                print(json.dumps({"event": "row-live", "row": row, "pid": child.pid,
                                  "completed_attempts": completed, "total": 40,
                                  "elapsed_seconds": time.monotonic() - start}), flush=True)
    finally:
        try:
            if child.poll() is None:
                # The transport's parent-death pipe also terminates its owned
                # RPC group if a provider call was active when this worker was
                # killed.
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    # The worker can exit between poll() and killpg().  Its
                    # process group is then already gone.
                    pass
                child.wait()
        finally:
            os.close(watchdog_fd)
    return {"row": row, "pid": child.pid, "returncode": child.returncode,
            "status": "deadline" if timed_out else "exited",
            "elapsed_seconds": time.monotonic() - start}


def run(config_path, expected, *, arm=False):
    config, stamps = validate(config_path, expected)
    recovery = config.get("schema") == RECOVERY_SCHEMA
    stage1 = config.get("schema") in (STAGE1_SCHEMA, STAGE2_SCHEMA)
    stage = 2 if config.get("schema") == STAGE2_SCHEMA else 1
    controlled = recovery or stage1
    rows = (STAGE2_ROWS if stage == 2 else STAGE1_ROWS) if stage1 else RECOVERY_ROWS if recovery else ROWS
    output = Path(config["output"])
    hold = config_path.parent / "HOLD"
    if os.path.lexists(hold) or os.path.lexists(output):
        raise ValueError("HOLD or existing campaign output; no retry")
    if not arm:
        return {"status": "unarmed", "rows": len(rows), "rounds": 40 * len(rows)}
    if os.nice(0) < 10:
        raise ValueError("campaign requires nice >=10")
    if controlled:
        _require_recovery_memory("reservation")
        _require_recovery_release(config_path, expected)
    env = {k: v for k, v in os.environ.items() if not k.startswith("SHENGJI_")}
    env.pop("PYTHONPATH", None)
    env.update(SHENGJI_FAST="1", PYTHONDONTWRITEBYTECODE="1", PYTHONUNBUFFERED="1")
    for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS"):
        env[key] = "1"
    results = []
    terminal = {"status": "failed", "config_sha256": expected, "rows": results}
    with reservation(LOCK, shared_host=sys.platform == "linux"):
        output.mkdir(mode=0o700)
        publish(output / "config.json", config)
        try:
            for row in rows:
                if os.path.lexists(hold):
                    raise ValueError("HOLD before row dispatch")
                if recovery:
                    stage = f"row {row} dispatch"
                    if results and "memory_wait" in config:
                        with (output / f"{row}.memory-wait.jsonl").open("x") as wait_log:
                            _wait_for_recovery_row_memory(config, hold, stage, log=wait_log)
                fence(stamps)
                if controlled and (not results or "memory_wait" not in config):
                    _require_recovery_memory(f"row {row} dispatch")
                if os.path.lexists(hold):
                    raise ValueError("HOLD before row dispatch")
                row_output = output / row
                command = [config["python"], "-B", "-m", "scripts.production_llm_panel",
                           "--row", row, "--model-assets", config["model_assets"],
                           "--prepared-roots-from", config["prepared_roots"],
                           "--prepared-roots-sha256", config["prepared_roots_sha256"],
                           "--seeds", *map(str, config["seeds"]), "--output", str(row_output),
                           "--codex-binary", config["codex_binary"], "--run"]
                if not controlled and config.get("provider_capacity_retry_delays"):
                    command.append("--retry-provider-capacity")
                if controlled:
                    command.extend(recovery_control_args(config))
                    command.extend(["--failure-protocol", PRESERVE_ILLEGAL])
                    if recovery and row in config["retention"]:
                        retained = config["retention"][row]
                        command.extend(["--retention-plan", retained["plan"],
                                        "--retention-plan-sha256", retained["sha256"]])
                print(json.dumps({"event": "row-start", "row": row}), flush=True)
                with (output / f"{row}.log").open("x") as log:
                    if controlled:
                        _require_recovery_release(config_path, expected)
                    result = supervise(command, cwd=config["source_root"], env=env,
                                       log=log, row=row, output=row_output, python=config["python"])
                results.append(result)
                publish(output / f"{row}.terminal.json", result)
                if result["returncode"] != 0 or result["status"] == "deadline":
                    raise ValueError("row terminated; preserve partials, no retry or further spend")
                report = json.loads((row_output / "result.json").read_bytes())
                if stage1 and report.get('config', {}).get('invalid_action_feedback') is not True:
                    raise ValueError('stage1 terminal must declare feedback ON')
                if controlled:
                    from shengji.luna.benchmark_terminal import validate_scheduled_terminal
                    fence(stamps)
                    retention_binding = None
                    if recovery and row in config['retention']:
                        retained = config['retention'][row]
                        plan = json.loads(Path(retained['plan']).read_bytes())
                        retention_binding = {
                            'source': plan['source_directory'],
                            'result_sha256': plan['result_sha256'],
                            'plan_sha256': retained['sha256'],
                        }
                    accounting = validate_scheduled_terminal(
                        report, seeds=config["seeds"], retention_binding=retention_binding)
                    publish(output / f"{row}.accounting.json", accounting)
                else:
                    mirrors = report["mirrors"]
                    if len(mirrors) != 40 or any(r.get("complete") is not True for r in mirrors):
                        raise ValueError("incomplete row; preserve results and stop campaign without retry")
                fence(stamps)
                print(json.dumps({"event": "row-terminal" if controlled else "row-complete",
                                  "row": row, "completed": len(results),
                                  "total": len(rows)}), flush=True)
            terminal["status"] = "scheduled-terminal" if controlled else "complete"
        except BaseException as exc:
            terminal.update(error_type=type(exc).__name__, error=str(exc))
            raise
        finally:
            publish(output / "terminal.json", terminal)
            # Scoring is a separate terminal consumer: an analysis refusal
            # must never erase or relabel the already-sealed game evidence.
            if stage1:
                publish(output / f"stage{stage}-summary.json", {
                    "schema": f"sol-feedback-on-stage{stage}-summary-v1",
                    "config_sha256": expected,
                    "status": terminal['status'],
                    "scientific_readout": f"pending-feedback-on-stage{stage}-reader",
                    "required_prior_rows": list(STAGE1_ROWS) if stage == 2 else [],
                    "rows": {
                        row: (json.loads((output / f"{row}.accounting.json").read_bytes())
                              if (output / f"{row}.accounting.json").exists()
                              else {"status": "not-terminally-validated"})
                        for row in rows},
                })
            elif recovery:
                # Six recovery rows cannot satisfy the nine-policy reader.
                # Publish operational accounting only. Scientific comparison
                # must bind the three original rows plus these six rows in a
                # separately reviewed, pinned readout (including forfeits).
                publish(output / "recovery-summary.json", {
                    "schema": "sol-six-row-recovery-summary-v1",
                    "config_sha256": expected,
                    "status": terminal["status"],
                    "scientific_readout": "pending-aligned-nine-row-reader",
                    "required_prior_rows": list(ROWS[:3]),
                    "rows": {
                        row: (json.loads((output / f"{row}.accounting.json").read_bytes())
                              if (output / f"{row}.accounting.json").exists()
                              else {"status": "not-terminally-validated"})
                        for row in rows},
                })
            else:
                try:
                    from scripts.production_llm_panel_readout import analyze_panel
                    readout = analyze_panel({row: str(output / row) for row in rows})
                    publish(output / "panel-readout.json", readout)
                except Exception as exc:
                    publish(output / "readout-error.json", {
                        "error_type": type(exc).__name__, "error": str(exc)})
    return terminal


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--arm", action="store_true")
    args = parser.parse_args()
    def interrupted(signum, frame):
        raise KeyboardInterrupt(f"signal {signum}")
    signal.signal(signal.SIGTERM, interrupted)
    print(json.dumps(run(args.config, args.sha256, arm=args.arm)), flush=True)


if __name__ == "__main__":
    main()
