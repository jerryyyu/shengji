"""Run one SZ2 training segment under an admitted host supervisor."""
import argparse
from contextlib import contextmanager, nullcontext
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time

SCRIPTS = Path(__file__).resolve().parent
DARKBLOOM = Path.home() / ".darkbloom/bin/darkbloom"
PAUSE = Path.home() / "darkbloom-dash/keepalive.pause"
PROVIDER_CONFIG = Path.home() / ".config/darkbloom/provider.toml"
PROVIDER_SHA256 = "72f6b444134b379709afe8c08b816d4e974d538669183702b96f5e4c90e0b2fe"
SERVING_MODE = "Darkbloom network only — this Mac has no local API"
MODEL_FILTER = {
    "gemma-4-26b-qat-4bit", "gpt-oss-20b", "qwen3.5-35b-a3b", "Qwen3.5-9B", "qwen3.6-35b-a3b-vl-mtp-mxfp8",
}
SYSCTL = "/usr/sbin/sysctl"
LAUNCHCTL = "/bin/launchctl"
PS = "/bin/ps"
FOOTPRINT = "/usr/bin/footprint"
POLL_SECONDS = 10
FOOTPRINT_INTERVAL = 60
FOOTPRINT_TIMEOUT = 10
RESTORE_SECONDS = 360
DRAIN_SECONDS = 600
STOP_GRACE = 25
JOBS = {"io.darkbloom.provider", "io.darkbloom.watchdog"}


def command(*argv, timeout=5):
    return subprocess.run(argv, check=True, text=True, stdout=subprocess.PIPE,
                          stdin=subprocess.DEVNULL, timeout=timeout).stdout


def provider_digest(expected_sha=None):
    digest = PROVIDER_SHA256 if expected_sha is None else expected_sha
    if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise ValueError("--provider-sha256 requires 64 lowercase hexadecimal digits")
    return digest


def verify_darkbloom_identity(status, expected_sha=None):
    fields = {}
    for label in ("Serving", "Enabled model filter"):
        values = [line[len(label) + 1:].strip() for line in status.splitlines()
                  if line.startswith(f"{label}:")]
        if len(values) != 1:
            raise RuntimeError(f"Darkbloom status must have exactly one {label} field")
        fields[label] = values[0]
    if fields["Serving"] != SERVING_MODE:
        raise RuntimeError("Darkbloom serving mode differs from the reviewed mode")
    model_ids = [model.strip() for model in fields["Enabled model filter"].split(",")]
    if len(model_ids) != len(MODEL_FILTER) or set(model_ids) != MODEL_FILTER:
        raise RuntimeError("Darkbloom model filter differs from the reviewed filter")
    with PROVIDER_CONFIG.open("rb") as config:
        digest = hashlib.file_digest(config, "sha256").hexdigest()
    if digest != provider_digest(expected_sha):
        raise RuntimeError(f"Darkbloom provider.toml SHA differs from the reviewed SHA: {digest}")


def darkbloom_ready(status, expected_sha=None):
    expected_sha = provider_digest(expected_sha)
    if not all(re.search(rf"^{line}(?:[ \t]|$)", status, re.MULTILINE)
               for line in ("Daemon: running", "Traffic: eligible")):
        return False
    jobs = {line.split()[-1] for line in command(LAUNCHCTL, "list").splitlines() if line.strip()}
    if not JOBS <= jobs:
        return False
    verify_darkbloom_identity(status, expected_sha)
    return True


class RestoreUnverified(RuntimeError):
    pass


def restore_darkbloom(expected_sha=None):
    expected_sha = provider_digest(expected_sha)
    try:
        command(DARKBLOOM, "restart", "--timeout", str(DRAIN_SECONDS), timeout=DRAIN_SECONDS + 30)
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"Darkbloom restart command failed: {exc}", file=sys.stderr, flush=True)
    deadline = time.monotonic() + RESTORE_SECONDS
    while True:
        status = ""
        detail = "provider is not ready"
        try:
            status = command(DARKBLOOM, "status")
            if darkbloom_ready(status, expected_sha):
                print("Darkbloom running and eligible with reviewed serving mode and model filter "
                      f"provider_sha256={expected_sha}", flush=True)
                return
        except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
            detail = str(exc)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            for line in status.splitlines():
                if line.startswith(("Daemon:", "Traffic:", "Model switch:")):
                    print(line, file=sys.stderr, flush=True)
            raise RestoreUnverified(f"Darkbloom restoration could not be verified: {detail}; operator action needed")
        time.sleep(min(POLL_SECONDS, remaining))


@contextmanager
def darkbloom_stopped(check_signal, expected_sha=None):
    expected_sha = provider_digest(expected_sha)
    pause = PAUSE
    with pause.open("x", encoding="utf-8") as lease:
        identity = os.fstat(lease.fileno())
        token = f"sz2 smoke pid={os.getpid()} start={time.time_ns()}\n"
        stopping = False

        def still_owned():
            try:
                return os.path.samestat(identity, pause.lstat()) and pause.read_text() == token
            except FileNotFoundError:
                return False

        def verify_stopped():
            if not still_owned():
                raise RuntimeError(f"Darkbloom pause ownership changed: {pause}")
            if not re.search(r"^Daemon: not running(?:[ \t]|$)",
                             command(DARKBLOOM, "status"), re.MULTILINE):
                raise RuntimeError("Darkbloom is not confirmed stopped")

        try:
            lease.write(token)
            lease.flush()
            if not darkbloom_ready(command(DARKBLOOM, "status"), expected_sha):
                raise RuntimeError("Darkbloom initial state is not ready")
            check_signal()
            if not still_owned():
                raise RuntimeError(f"Darkbloom pause ownership changed: {pause}")
            stopping = True
            for attempt in range(2):
                stop = subprocess.run([DARKBLOOM, "stop", "--timeout", str(DRAIN_SECONDS)],
                                      stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                      stdin=subprocess.DEVNULL, timeout=DRAIN_SECONDS + 10)
                if stop.stdout:
                    print(stop.stdout.rstrip(), flush=True)
                if stop.returncode == 0:
                    break
                unfinished = re.search(r"^Error: Drain did not complete: [1-9][0-9]* unfinished request\(s\),"
                                       r" coordinator acknowledgement (?:true|false)\.", stop.stdout, re.MULTILINE)
                if attempt or stop.returncode != 64 or unfinished is None:
                    stop.check_returncode()
                check_signal()
                if not still_owned():
                    raise RuntimeError(f"Darkbloom pause ownership changed: {pause}")
                print("Darkbloom still draining accepted work; one graceful stop remains", flush=True)
            verify_stopped()
            print("Darkbloom stopped with keepalive suspended", flush=True)
            check_signal()
            yield verify_stopped
        finally:
            if not still_owned():
                raise RuntimeError(f"Darkbloom pause ownership changed: {pause}")
            try:
                if stopping:
                    restore_darkbloom(expected_sha)
            finally:
                if still_owned():
                    pause.unlink()
                else:
                    raise RuntimeError(f"Darkbloom pause ownership changed: {pause}")


def memory_sample():
    swap = command(SYSCTL, "-n", "vm.swapusage")
    match = re.search(r"\bused\s*=\s*(\d+(?:\.\d+)?)([KMGT])\b", swap)
    if match is None:
        raise ValueError("unreadable swap usage")
    amount, unit = match.groups()
    swap_mib = float(amount) * {"K": 1 / 1024, "M": 1, "G": 1024, "T": 1024 ** 2}[unit]
    pressure = int(command(SYSCTL, "-n", "kern.memorystatus_vm_pressure_level").strip())
    if pressure not in (1, 2, 4):
        raise ValueError(f"unrecognized memory pressure level {pressure}")
    return swap_mib, pressure


def footprint_mib(pid):
    try:
        output = command(FOOTPRINT, "-p", str(pid), timeout=FOOTPRINT_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return None
    match = re.search(r"\bFootprint:[ \t]+(\d+(?:\.\d+)?)[ \t]+([KMG]B)\b", output)
    if match is None:
        return None
    magnitude, unit = match.groups()
    return float(magnitude) * {"KB": 1 / 1024, "MB": 1, "GB": 1024}[unit]


def monitor(child, baseline, check_signal, verify_stopped, *, pressure_limit=4, swap_limit=8192,
            footprint_limit=65536):
    started = time.monotonic()
    next_footprint = started
    previous_footprint = None
    unavailable = 0
    try:
        while True:
            check_signal()
            verify_stopped()
            swap, pressure = memory_sample()
            rc = child.poll()
            rss = "-"
            if rc is None:
                try:
                    rss = command(PS, "-o", "rss=", "-p", str(child.pid)).strip()
                except subprocess.CalledProcessError:
                    if child.poll() is None:
                        raise
            print(f"smoke pid={child.pid} elapsed_s={time.monotonic() - started:.1f} "
                  f"rss_kib={rss} swap_mib={swap:g} baseline_mib={baseline:g} pressure={pressure}", flush=True)
            if pressure >= pressure_limit or swap - baseline >= swap_limit:
                raise RuntimeError("memory guard exceeded")
            if child.poll() is None and time.monotonic() >= next_footprint:
                footprint = footprint_mib(child.pid)
                sampled = time.monotonic()
                next_footprint = sampled + FOOTPRINT_INTERVAL
                if footprint is None:
                    if child.poll() is None:
                        unavailable += 1
                        print(f"smoke pid={child.pid} footprint_mib=NA consecutive={unavailable}", flush=True)
                        if unavailable >= 3:
                            raise RuntimeError("trainer footprint unavailable for three consecutive samples")
                else:
                    unavailable = 0
                    slope = "-"
                    if previous_footprint is not None:
                        when, value = previous_footprint
                        slope = f"{60 * (footprint - value) / (sampled - when):.1f}"
                    previous_footprint = sampled, footprint
                    print(f"smoke pid={child.pid} footprint_mib={footprint:g} "
                          f"footprint_slope_mib_per_min={slope}", flush=True)
                    if footprint > footprint_limit:
                        raise RuntimeError(f"trainer footprint exceeds {footprint_limit} MiB")
            rc = child.poll()
            if rc is not None:
                return rc
            time.sleep(POLL_SECONDS)
    finally:
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=STOP_GRACE)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=5)


def run_segment(root, phase, check_signal, expected_sha=None, min_free_gib=None):
    expected_sha = provider_digest(expected_sha)
    root = root.resolve(strict=True)
    smoke = phase in ("smoke", "L-smoke")
    output = root / ("L-smoke" if phase == "L-smoke" else "smoke")
    sz3 = phase in ("L-smoke", "M", "L-prefix", "L-finish")
    emitter = "sz3_joint_recipe.py" if sz3 else "sz2_joint_segment.py"
    if smoke and os.path.lexists(output):
        raise RuntimeError(f"smoke output already exists: {output}")
    if sz3 and (min_free_gib is None or min_free_gib <= 0):
        raise ValueError(f"{phase} requires a positive --min-free-gib")

    def guard():
        check_signal()
        if min_free_gib is not None:
            free = shutil.disk_usage(root).free
            print(f"disk free_bytes={free} floor_gib={min_free_gib} path={root}", flush=True)
            if free < min_free_gib * 1024 ** 3:
                raise RuntimeError(f"disk guard: {free} bytes free at {root}, floor {min_free_gib} GiB")

    guard()
    try:
        argv = json.loads(command(sys.executable, "-B", SCRIPTS / emitter, phase,
                                  "--root", root, timeout=60))
    except subprocess.CalledProcessError as exc:
        if phase in ("medium-finish", "L-finish") and exc.returncode == 8:
            return 8
        raise
    if not isinstance(argv, list) or not argv or not all(isinstance(item, str) for item in argv):
        raise ValueError("invalid trainer argv")
    _, pressure = memory_sample()
    if pressure >= 4:
        raise RuntimeError("memory pressure too high to start trainer")
    guard()
    if smoke:
        output.mkdir()
    gpu = phase != "small"
    provider = darkbloom_stopped(guard, expected_sha) if gpu else nullcontext(check_signal)
    with provider as verify_stopped:
        baseline, pressure = memory_sample()
        if pressure >= 4:
            raise RuntimeError("memory pressure too high to start trainer")

        def train(command_line):
            verify_stopped()
            guard()
            child = subprocess.Popen(command_line, cwd=SCRIPTS.parent,
                                     env={**os.environ, "OMP_NUM_THREADS": "4" if gpu else "16"},
                                     stdin=subprocess.DEVNULL)
            return monitor(child, baseline, guard, verify_stopped)

        if phase == "L-smoke":
            rc = train([*argv, "--pause-at-report"])
            if rc != 7:
                raise RuntimeError(f"L-smoke trainer exited {rc} before its checkpoint pause")
            directory = output / "train"
            last = (directory / "status.log").read_text().splitlines()
            if not last or not re.fullmatch(
                    r"\S+ UTR PAUSED at epoch 1 buffer 1/[1-9][0-9]* \(report boundary\); checkpoint saved", last[-1]):
                raise RuntimeError("L-smoke lacks the expected trainer pause")
            if os.path.lexists(directory / "STOP"):
                raise RuntimeError("L-smoke operator STOP present before continuation")
            argv = [*argv, "--expect-resume-buffer", "1"]
        rc = train(argv)
    guard()
    if not smoke and rc == 3:
        return 3
    if phase in ("medium-prefix", "L-prefix") and rc == 7:
        return 7
    if rc or phase in ("medium-prefix", "L-prefix"):
        raise RuntimeError(f"{phase} trainer exited {rc}")
    if phase == "L-smoke":
        from sz3_joint_recipe import smoke_result
        print(json.dumps(smoke_result(output / "train"), allow_nan=False), flush=True)
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--phase", choices=("smoke", "L-smoke", "M", "L-prefix", "L-finish", "small", "medium-prefix", "medium-finish"), default="smoke")
    parser.add_argument("--min-free-gib", type=int, help="minimum free space on the training volume")
    parser.add_argument("--provider-sha256", help="reviewed SHA256 of the provider configuration")
    args = parser.parse_args()
    if args.min_free_gib is not None and args.min_free_gib <= 0:
        parser.error("--min-free-gib must be positive")
    received = None

    def mark_signal(signum, _frame):
        nonlocal received
        received = signum

    def check_signal():
        if received is not None:
            raise RuntimeError(f"smoke received {signal.Signals(received).name}")

    for signum in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        signal.signal(signum, mark_signal)
    try:
        return run_segment(args.root, args.phase, check_signal, args.provider_sha256, args.min_free_gib)
    except RestoreUnverified as exc:
        print(exc, file=sys.stderr, flush=True)
        return 9
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"SZ2 smoke failed: {exc}", file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
