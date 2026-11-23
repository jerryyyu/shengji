"""Run one SZ2 smoke under an admitted host supervisor."""
import argparse
from contextlib import contextmanager
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
SYSCTL = "/usr/sbin/sysctl"
LAUNCHCTL = "/bin/launchctl"
PS = "/bin/ps"
FOOTPRINT = "/usr/bin/footprint"
POLL_SECONDS = 10
FOOTPRINT_INTERVAL = 60
FOOTPRINT_TIMEOUT = 10
RESTORE_SECONDS = 360
STOP_GRACE = 25
JOBS = {"io.darkbloom.provider", "io.darkbloom.watchdog"}


def command(*argv, timeout=5):
    return subprocess.run(argv, check=True, text=True, stdout=subprocess.PIPE,
                          stdin=subprocess.DEVNULL, timeout=timeout).stdout


def darkbloom_ready():
    status = command(DARKBLOOM, "status")
    if not all(re.search(rf"^{line}(?:[ \t]|$)", status, re.MULTILINE)
               for line in ("Daemon: running", "Traffic: eligible")):
        return False
    jobs = {line.split()[-1] for line in command(LAUNCHCTL, "list").splitlines() if line.strip()}
    return JOBS <= jobs


def restore_darkbloom():
    try:
        command(DARKBLOOM, "restart", timeout=240)
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"Darkbloom restart command failed: {exc}", file=sys.stderr, flush=True)
    deadline = time.monotonic() + RESTORE_SECONDS
    while True:
        try:
            if darkbloom_ready():
                print("Darkbloom running and eligible", flush=True)
                return
        except (OSError, subprocess.SubprocessError):
            pass
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError("Darkbloom restoration could not be verified")
        time.sleep(min(POLL_SECONDS, remaining))


@contextmanager
def darkbloom_paused(check_signal):
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

        try:
            lease.write(token)
            lease.flush()
            if not darkbloom_ready():
                raise RuntimeError("Darkbloom initial state is not ready")
            check_signal()
            if not still_owned():
                raise RuntimeError(f"Darkbloom pause ownership changed: {pause}")
            stopping = True
            command(DARKBLOOM, "stop", "--timeout", "180", timeout=190)
            if not re.search(r"^Daemon: not running(?:[ \t]|$)",
                             command(DARKBLOOM, "status"), re.MULTILINE):
                raise RuntimeError("Darkbloom stop could not be verified")
            check_signal()
            yield
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


def monitor(child, baseline, check_signal):
    started = time.monotonic()
    next_footprint = started
    previous_footprint = None
    unavailable = 0
    try:
        while True:
            check_signal()
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
    with darkbloom_paused(check_signal):
        baseline, pressure = memory_sample()
        if pressure >= 4:
            raise RuntimeError("memory pressure too high to start smoke")
        check_signal()
        child = subprocess.Popen(argv, cwd=SCRIPTS.parent, env={**os.environ, "OMP_NUM_THREADS": "4"},
                                 stdin=subprocess.DEVNULL)
        monitor(child, baseline, check_signal)
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
