"""Run one SZ2 smoke under an admitted host supervisor."""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
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


def verify_darkbloom_identity(status):
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
    if digest != PROVIDER_SHA256:
        raise RuntimeError(f"Darkbloom provider.toml SHA differs from the reviewed SHA: {digest}")


def darkbloom_ready():
    status = command(DARKBLOOM, "status")
    if not all(re.search(rf"^{line}(?:[ \t]|$)", status, re.MULTILINE)
               for line in ("Daemon: running", "Traffic: eligible")):
        return False
    jobs = {line.split()[-1] for line in command(LAUNCHCTL, "list").splitlines() if line.strip()}
    if not JOBS <= jobs:
        return False
    verify_darkbloom_identity(status)
    return True


def restore_darkbloom():
    try:
        command(DARKBLOOM, "restart", timeout=240)
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"Darkbloom restart command failed: {exc}", file=sys.stderr, flush=True)
    deadline = time.monotonic() + RESTORE_SECONDS
    while True:
        try:
            if darkbloom_ready():
                print("Darkbloom running and eligible with reviewed serving mode and model filter "
                      f"provider_sha256={PROVIDER_SHA256}", flush=True)
                return
        except (OSError, subprocess.SubprocessError):
            pass
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError("Darkbloom restoration could not be verified")
        time.sleep(min(POLL_SECONDS, remaining))


@contextmanager
def darkbloom_stopped(check_signal):
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
            if not darkbloom_ready():
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
                    restore_darkbloom()
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


def monitor(child, baseline, check_signal, verify_stopped):
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
            if pressure >= 4 or swap - baseline >= 8192:
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
                    if footprint > 65536:
                        raise RuntimeError("trainer footprint exceeds 65536 MiB")
            rc = child.poll()
            if rc is not None:
                if rc:
                    raise RuntimeError(f"smoke trainer exited {rc}")
                return
            time.sleep(POLL_SECONDS)
    finally:
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=STOP_GRACE)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=5)


def smoke(root, check_signal):
    root = root.resolve(strict=True)
    output = root / "smoke"
    if os.path.lexists(output):
        raise RuntimeError(f"smoke output already exists: {output}")
    argv = json.loads(command(sys.executable, "-B", SCRIPTS / "sz2_joint_segment.py", "smoke", "--root",
                              root, timeout=60))
    if not isinstance(argv, list) or not argv or not all(isinstance(item, str) for item in argv):
        raise ValueError("invalid smoke trainer argv")
    _, pressure = memory_sample()
    if pressure >= 4:
        raise RuntimeError("memory pressure too high to start smoke")
    check_signal()
    output.mkdir()
    with darkbloom_stopped(check_signal) as verify_stopped:
        baseline, pressure = memory_sample()
        if pressure >= 4:
            raise RuntimeError("memory pressure too high to start smoke")
        verify_stopped()
        check_signal()
        child = subprocess.Popen(argv, cwd=SCRIPTS.parent, env={**os.environ, "OMP_NUM_THREADS": "4"},
                                 stdin=subprocess.DEVNULL)
        monitor(child, baseline, check_signal, verify_stopped)
    check_signal()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
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
        smoke(args.root, check_signal)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"SZ2 smoke failed: {exc}", file=sys.stderr, flush=True)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
