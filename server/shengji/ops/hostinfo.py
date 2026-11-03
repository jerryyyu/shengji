"""Portable host probes for lane tooling on Linux and macOS.

Lane launchers, supervisors and copy tools need a handful of host facts:
process RSS, process-group membership, exact argv of live processes, free
memory, a new-session spawn, a kill-after-timeout and file digests.  Linux
answers from ``/proc``; macOS has no ``/proc``, no ``setsid`` binary and no
GNU ``timeout``/``sha256sum``, so it answers from ``ps``, ``sysctl`` and
``vm_stat``.  Every probe fails closed: an unreadable or malformed answer
raises :class:`HostProbeError` rather than reading as "nothing there".

The module imports only the standard library (plus the vm_stat parser of the
Sol memory guard) so a launcher can call it before any heavy import::

    python -m shengji.ops.hostinfo mem
    python -m shengji.ops.hostinfo group PGID
    python -m shengji.ops.hostinfo writers NEEDLE
    python -m shengji.ops.hostinfo run --wall 3600 --signal KILL -- CMD ...
    python -m shengji.ops.hostinfo detach -- CMD ...
    python -m shengji.ops.hostinfo sha256 FILE ...
    python -m shengji.ops.hostinfo remap PATH

Data manifests written on one host can name absolute directories of that
host.  :func:`remap_path` rewrites such a path through an explicit
``OLD=NEW`` map (``SHENGJI_PATH_MAP``, entries separated by ``;``) so a
consumer on another host finds the copied directory; with no map every path
is returned unchanged.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import signal as _signal
import subprocess
import sys
import time
from typing import Iterable, Mapping, Sequence

PATH_MAP_ENV = "SHENGJI_PATH_MAP"
TIMEOUT_STATUS = 124
_PS = "/bin/ps"
_SYSCTL = "/usr/sbin/sysctl"
_VM_STAT = "/usr/bin/vm_stat"
_PROBE_TIMEOUT_S = 10.0


class HostProbeError(RuntimeError):
    """A host fact could not be read completely; callers must treat it as unknown."""


def platform_kind() -> str:
    """``"linux"`` or ``"darwin"``; any other platform is refused."""
    if sys.platform.startswith("linux"):
        return "linux"
    if sys.platform == "darwin":
        return "darwin"
    raise HostProbeError(f"unsupported platform {sys.platform!r}")


@dataclass(frozen=True)
class ProcRow:
    pid: int
    ppid: int
    pgid: int
    rss_bytes: int
    state: str
    uid: int


def _run_text(argv: Sequence[str]) -> str:
    try:
        out = subprocess.run(list(argv), check=True, capture_output=True, text=True,
                             timeout=_PROBE_TIMEOUT_S).stdout
    except (OSError, subprocess.SubprocessError, UnicodeError) as exc:
        raise HostProbeError(f"{argv[0]} failed: {exc}") from exc
    return out


def _linux_stat_row(pid: int) -> ProcRow | None:
    base = Path("/proc") / str(pid)
    try:
        stat = (base / "stat").read_text()
        uid = base.stat().st_uid
    except (FileNotFoundError, ProcessLookupError):
        return None
    except OSError as exc:
        raise HostProbeError(f"/proc/{pid}/stat unreadable: {exc}") from exc
    head, sep, tail = stat.rpartition(")")
    fields = tail.split()
    if not sep or len(fields) < 22:
        raise HostProbeError(f"/proc/{pid}/stat malformed")
    # Fields after the comm: state ppid pgrp ... rss (field 24 overall) in pages.
    return ProcRow(pid=pid, ppid=int(fields[1]), pgid=int(fields[2]),
                   rss_bytes=int(fields[21]) * os.sysconf("SC_PAGE_SIZE"),
                   state=fields[0], uid=uid)


def parse_ps_table(text: str) -> dict[int, ProcRow]:
    """Parse ``ps -axo pid=,ppid=,pgid=,rss=,stat=,uid=`` (rss in KiB)."""
    if not text.endswith("\n"):
        raise HostProbeError("process census truncated")
    rows: dict[int, ProcRow] = {}
    for line in text.splitlines():
        fields = line.split()
        if len(fields) != 6:
            raise HostProbeError(f"process census row malformed: {line!r}")
        nums = [fields[i] for i in (0, 1, 2, 3, 5)]
        if not all(f.isascii() and f.isdigit() for f in nums):
            raise HostProbeError(f"process census row malformed: {line!r}")
        pid, ppid, pgid, rss_kib, uid = map(int, nums)
        if pid in rows:
            raise HostProbeError(f"process census repeats pid {pid}")
        rows[pid] = ProcRow(pid, ppid, pgid, rss_kib * 1024, fields[4], uid)
    if not rows:
        raise HostProbeError("process census empty")
    return rows


def process_table() -> dict[int, ProcRow]:
    """Every visible process: pid, parent, process group, RSS bytes, state, uid."""
    if platform_kind() == "linux":
        rows = {}
        for entry in Path("/proc").iterdir():
            if entry.name.isdecimal():
                row = _linux_stat_row(int(entry.name))
                if row is not None:
                    rows[row.pid] = row
        if not rows:
            raise HostProbeError("process census empty")
        return rows
    return parse_ps_table(_run_text([_PS, "-axo", "pid=,ppid=,pgid=,rss=,stat=,uid="]))


def process_rss_bytes(pid: int) -> int | None:
    """Resident set size of one process, or ``None`` when it no longer exists."""
    if platform_kind() == "linux":
        row = _linux_stat_row(pid)
        return None if row is None else row.rss_bytes
    row = process_table().get(pid)
    return None if row is None else row.rss_bytes


def group_members(pgid: int, table: Mapping[int, ProcRow] | None = None) -> list[ProcRow]:
    """Live (including zombie, not yet reaped) members of process group ``pgid``."""
    table = process_table() if table is None else table
    return sorted((r for r in table.values() if r.pgid == pgid), key=lambda r: r.pid)


def group_rss_bytes(pgid: int, table: Mapping[int, ProcRow] | None = None) -> int:
    return sum(r.rss_bytes for r in group_members(pgid, table))


def wait_group_quiescent(pgid: int, timeout_s: float, poll_s: float = 0.2) -> bool:
    """True once no process remains in ``pgid``; False if one remains at the deadline."""
    deadline = time.monotonic() + timeout_s
    while True:
        if not group_members(pgid):
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(min(poll_s, max(0.0, deadline - time.monotonic())))


def _darwin_argv(pid: int) -> tuple[str, ...] | None:
    """Exact argv through ``sysctl(KERN_PROCARGS2)``; ``None`` if unreadable."""
    import ctypes
    import ctypes.util
    libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
    ctl_kern, kern_argmax, kern_procargs2 = 1, 8, 49
    argmax = ctypes.c_int(0)
    size = ctypes.c_size_t(ctypes.sizeof(argmax))
    mib = (ctypes.c_int * 2)(ctl_kern, kern_argmax)
    if libc.sysctl(mib, 2, ctypes.byref(argmax), ctypes.byref(size), None, 0) != 0:
        raise HostProbeError("sysctl kern.argmax failed")
    buf = ctypes.create_string_buffer(argmax.value)
    size = ctypes.c_size_t(argmax.value)
    mib3 = (ctypes.c_int * 3)(ctl_kern, kern_procargs2, pid)
    if libc.sysctl(mib3, 3, buf, ctypes.byref(size), None, 0) != 0:
        return None
    raw = buf.raw[:size.value]
    if len(raw) < 4:
        return None
    argc = int.from_bytes(raw[:4], sys.byteorder)
    rest = raw[4:]
    end = rest.find(b"\0")
    if end < 0:
        return None
    pos = end
    while pos < len(rest) and rest[pos] == 0:
        pos += 1
    parts = rest[pos:].split(b"\0")
    if argc < 0 or len(parts) < argc:
        return None
    return tuple(p.decode("utf-8", errors="surrogateescape") for p in parts[:argc])


def process_argv(pid: int) -> tuple[str, ...] | None:
    """Exact argv elements of ``pid``; ``None`` when it is gone or has none (zombie, kernel thread)."""
    if platform_kind() == "linux":
        try:
            raw = (Path("/proc") / str(pid) / "cmdline").read_bytes()
        except (FileNotFoundError, ProcessLookupError):
            return None
        except OSError as exc:
            raise HostProbeError(f"/proc/{pid}/cmdline unreadable: {exc}") from exc
        if not raw:
            return None
        return tuple(raw.rstrip(b"\0").decode("utf-8", errors="surrogateescape").split("\0"))
    return _darwin_argv(pid)


def pids_with_argv_element(needle: str, *, program: str | None = None,
                           exclude: Iterable[int] = ()) -> list[int]:
    """Live pids whose argv holds ``needle`` as one exact element (a writer probe).

    ``program`` additionally requires ``basename(argv[0]) == program``.  The
    caller's own pid is always excluded so the probe never matches itself.
    On macOS only processes of the caller's uid are scanned (other users'
    argv is not readable there); a same-uid process whose argv cannot be read
    and that is not a zombie fails the probe.
    """
    skip = {os.getpid(), *exclude}
    hits = []
    kind = platform_kind()
    if kind == "linux":
        candidates = [int(e.name) for e in Path("/proc").iterdir() if e.name.isdecimal()]
        states: dict[int, str] = {}
    else:
        table = process_table()
        uid = os.getuid()
        candidates = [p for p, r in table.items() if r.uid == uid]
        states = {p: r.state for p, r in table.items()}
    for pid in candidates:
        if pid in skip:
            continue
        argv = process_argv(pid)
        if argv is None:
            if kind == "darwin" and not states.get(pid, "Z").startswith("Z") and _pid_alive(pid):
                raise HostProbeError(f"argv of live pid {pid} unreadable")
            continue
        if needle in argv and (program is None or os.path.basename(argv[0]) == program):
            hits.append(pid)
    return sorted(hits)


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def parse_meminfo(text: str) -> dict[str, int]:
    values = {}
    for line in text.splitlines():
        name, sep, rest = line.partition(":")
        if name in ("MemTotal", "MemAvailable"):
            parts = rest.split()
            if not sep or len(parts) != 2 or parts[1] != "kB" or not parts[0].isdigit() or name in values:
                raise HostProbeError(f"meminfo {name} malformed")
            values[name] = int(parts[0]) * 1024
    if set(values) != {"MemTotal", "MemAvailable"}:
        raise HostProbeError("meminfo incomplete")
    return {"total_bytes": values["MemTotal"], "available_bytes": values["MemAvailable"]}


def memory() -> dict[str, int]:
    """Total and available memory in bytes.

    Linux reports the kernel's ``MemAvailable``.  macOS reports free +
    speculative + inactive pages from ``vm_stat`` (reclaimable headroom, the
    estimate the Sol memory guard already uses) and ``hw.memsize`` as total.
    """
    if platform_kind() == "linux":
        try:
            return parse_meminfo(Path("/proc/meminfo").read_text())
        except OSError as exc:
            raise HostProbeError(f"/proc/meminfo unreadable: {exc}") from exc
    from shengji.luna.sol_memory_guard import available_memory_bytes
    total = _run_text([_SYSCTL, "-n", "hw.memsize"]).strip()
    if not total.isdigit():
        raise HostProbeError("hw.memsize malformed")
    try:
        available = available_memory_bytes(_run_text([_VM_STAT]))
    except ValueError as exc:
        raise HostProbeError(str(exc)) from exc
    return {"total_bytes": int(total), "available_bytes": available}


def load_and_cpus() -> dict[str, object]:
    return {"loadavg": list(os.getloadavg()), "cpus": os.cpu_count()}


def spawn_new_session(argv: Sequence[str], **popen_kw) -> subprocess.Popen:
    """Start ``argv`` as the leader of a new session and process group (no setsid binary)."""
    return subprocess.Popen(list(argv), start_new_session=True, **popen_kw)


def _signal_group(pgid: int, sig: int) -> None:
    try:
        os.killpg(pgid, sig)
    except ProcessLookupError:
        pass
    except PermissionError:
        # macOS refuses a signal to a group whose only members are zombies.
        if any(not r.state.startswith("Z") for r in group_members(pgid)):
            raise


def _exit_status(returncode: int) -> int:
    return 128 - returncode if returncode < 0 else returncode


def live_group_members(pgid: int) -> list[ProcRow]:
    """Members of ``pgid`` that can still run: zombies and dead entries are excluded."""
    return [r for r in group_members(pgid) if not r.state.startswith(("Z", "X"))]


class Cancellation:
    """An external stop request for :func:`run_with_timeout`, safe to call from a signal handler.

    The first request's signal is recorded and every request is forwarded to
    the command's process group; a request that arrives before the command
    starts is delivered as soon as it does.
    """

    def __init__(self) -> None:
        self.signum: int | None = None
        self._pgid: int | None = None

    def request(self, signum: int) -> None:
        if self.signum is None:
            self.signum = signum
        if self._pgid is not None:
            _killpg_quiet(self._pgid, signum)

    def attach(self, pgid: int) -> None:
        self._pgid = pgid
        if self.signum is not None:
            _killpg_quiet(pgid, self.signum)


def _killpg_quiet(pgid: int, sig: int) -> None:
    try:
        os.killpg(pgid, sig)
    except (ProcessLookupError, PermissionError):
        pass


def _wait_drained(child: subprocess.Popen, timeout_s: float | None, poll_s: float = 0.05) -> bool:
    """Reap the leader and wait until no live member remains in its group.

    ``timeout_s=None`` waits without a deadline.  Returns False when a live
    member remains at the deadline.
    """
    deadline = None if timeout_s is None else time.monotonic() + timeout_s
    while True:
        child.poll()
        if child.returncode is not None and not live_group_members(child.pid):
            return True
        if deadline is not None and time.monotonic() >= deadline:
            return False
        time.sleep(poll_s)


GROUP_NOT_DRAINED_STATUS = 125
DEFAULT_CANCEL_GRACE_S = 10.0
KILL_DRAIN_S = 10.0


class GroupNotDrained(HostProbeError):
    """Live members of the command's process group survived SIGKILL."""


def run_with_timeout(argv: Sequence[str], wall_s: float, *, sig: int = _signal.SIGTERM,
                     kill_after_s: float | None = None, on_start=None,
                     cancel: Cancellation | None = None, **popen_kw) -> int:
    """Run ``argv`` in its own process group and stop the whole group at ``wall_s``.

    Exit status follows GNU ``timeout``:

    * finished in time: the command's own status (128+N for death by signal N);
      members it left running in its group are not touched;
    * timed out: 124, or 137 when SIGKILL was sent (directly via ``sig`` or
      because a live member remained ``kill_after_s`` after ``sig``); with no
      ``kill_after_s`` the leader is awaited and its surviving members are
      killed;
    * cancelled through ``cancel``: the command's own status, or 137 when a
      live member remained ``kill_after_s`` (default
      ``DEFAULT_CANCEL_GRACE_S``) after the forwarded signal, even if the
      leader had already exited.

    A timed-out or cancelled run returns only once no live member remains in
    the group; if one survives SIGKILL for ``KILL_DRAIN_S`` it raises
    :class:`GroupNotDrained`.
    """
    if wall_s <= 0:
        raise ValueError("wall_s must be positive")
    child = spawn_new_session(argv, **popen_kw)
    if cancel is not None:
        cancel.attach(child.pid)
    if on_start is not None:
        on_start(child)
    deadline = time.monotonic() + wall_s
    while True:
        if cancel is not None and cancel.signum is not None:
            return _drain_cancelled(child, kill_after_s)
        if child.returncode is not None:
            return _exit_status(child.returncode)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            child.wait(timeout=min(remaining, 0.1))
        except subprocess.TimeoutExpired:
            pass
    _signal_group(child.pid, sig)
    killed = sig == _signal.SIGKILL
    if not killed and kill_after_s is not None and not _wait_drained(child, kill_after_s):
        _signal_group(child.pid, _signal.SIGKILL)
        killed = True
    if not killed:
        child.wait()
        # Members that outlived the leader still belong to the timed-out command.
        _signal_group(child.pid, _signal.SIGKILL)
    _require_drained(child)
    return 128 + _signal.SIGKILL if killed else TIMEOUT_STATUS


def _drain_cancelled(child: subprocess.Popen, kill_after_s: float | None) -> int:
    grace = DEFAULT_CANCEL_GRACE_S if kill_after_s is None else kill_after_s
    if _wait_drained(child, grace):
        return _exit_status(child.returncode)
    _signal_group(child.pid, _signal.SIGKILL)
    _require_drained(child)
    return 128 + _signal.SIGKILL


def _require_drained(child: subprocess.Popen) -> None:
    if not _wait_drained(child, KILL_DRAIN_S):
        live = [r.pid for r in live_group_members(child.pid)]
        raise GroupNotDrained(f"process group {child.pid} still has live members {live} after SIGKILL")


def sha256_file(path: str | os.PathLike) -> str:
    with open(path, "rb") as fh:
        return hashlib.file_digest(fh, "sha256").hexdigest()


def sha256_stream(stream) -> str:
    return hashlib.file_digest(stream, "sha256").hexdigest()


def parse_path_map(text: str | None) -> tuple[tuple[PurePosixPath, PurePosixPath], ...]:
    """``OLD=NEW[;OLD=NEW...]`` into (old, new) pairs, longest ``OLD`` first.

    Both sides must be absolute, normalised POSIX paths without ``..``; an
    ``OLD`` may appear once.  Empty or unset text is the empty map.
    """
    if not text:
        return ()
    pairs: dict[PurePosixPath, PurePosixPath] = {}
    for entry in text.split(";"):
        if not entry:
            continue
        old, sep, new = entry.partition("=")
        if not sep:
            raise ValueError(f"path map entry {entry!r} is not OLD=NEW")
        sides = []
        for raw in (old, new):
            p = PurePosixPath(raw)
            if not p.is_absolute() or ".." in p.parts or str(p) != raw.rstrip("/") or raw == "/":
                raise ValueError(f"path map side {raw!r} must be an absolute normalised path other than /")
            sides.append(p)
        if sides[0] in pairs:
            raise ValueError(f"path map repeats {old!r}")
        pairs[sides[0]] = sides[1]
    return tuple(sorted(pairs.items(), key=lambda kv: len(kv[0].parts), reverse=True))


def path_map_from_env(env: Mapping[str, str] | None = None):
    return parse_path_map((os.environ if env is None else env).get(PATH_MAP_ENV))


def remap_path(path: str | os.PathLike, mapping=None) -> Path:
    """``path`` with its longest mapped prefix (whole components) replaced.

    ``mapping`` defaults to ``SHENGJI_PATH_MAP``.  A path no entry covers is
    returned unchanged, so an empty map is the identity.
    """
    mapping = path_map_from_env() if mapping is None else mapping
    p = PurePosixPath(os.fspath(path))
    for old, new in mapping:
        if p.parts[:len(old.parts)] == old.parts:
            return Path(new.joinpath(*p.parts[len(old.parts):]))
    return Path(os.fspath(path))


def _detach(argv: Sequence[str]) -> None:
    """``setsid CMD``: become a session leader (forking first if already a group leader), then exec."""
    try:
        os.setsid()
    except PermissionError:
        if os.fork() != 0:
            os._exit(0)
        os.setsid()
    os.execvp(argv[0], list(argv))


def _check_sums(listing: str) -> int:
    """``sha256sum -c``: 0 only when at least one record was checked and every line is a matching record."""
    bad = checked = 0
    for line in listing.splitlines():
        if not line.strip():
            continue
        digest, sep, name = line.partition(" ")
        if not sep or len(digest) != 64 or name[:1] not in (" ", "*"):
            print(f"malformed line: {line}", file=sys.stderr)
            bad += 1
            continue
        name = name[1:]
        try:
            ok = sha256_file(name) == digest.lower()
        except OSError:
            ok = False
        print(f"{name}: {'OK' if ok else 'FAILED'}")
        checked += 1
        bad += not ok
    if not checked:
        print("no checksum records to check", file=sys.stderr)
        return 1
    return 1 if bad else 0


def _signal_number(name: str) -> int:
    name = name.upper()
    if name.isdigit():
        return int(name)
    return int(getattr(_signal, name if name.startswith("SIG") else "SIG" + name))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m shengji.ops.hostinfo", description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("mem", help="total and available memory (JSON)")
    sub.add_parser("load", help="load average and CPU count (JSON)")
    p = sub.add_parser("rss", help="RSS bytes of one pid (JSON; null if gone)")
    p.add_argument("pid", type=int)
    p = sub.add_parser("group", help="members and RSS of a process group (JSON)")
    p.add_argument("pgid", type=int)
    p = sub.add_parser("quiesce", help="wait until a process group is empty; rc 1 if not by the deadline")
    p.add_argument("pgid", type=int)
    p.add_argument("--timeout", type=float, required=True)
    p = sub.add_parser("writers", help="pids whose argv holds NEEDLE as one exact element (JSON)")
    p.add_argument("needle")
    p.add_argument("--program")
    p.add_argument("--hex", action="store_true", help="NEEDLE is hex-encoded UTF-8")
    p = sub.add_parser("run", help="GNU timeout replacement: run CMD in its own group under a wall ceiling")
    p.add_argument("--wall", type=float, required=True)
    p.add_argument("--signal", default="TERM")
    p.add_argument("--kill-after", type=float,
                   help="seconds after the stop signal (timeout or a forwarded TERM/INT/HUP) before SIGKILL; "
                        f"a forwarded signal defaults to {DEFAULT_CANCEL_GRACE_S:g}")
    p.add_argument("command", nargs=argparse.REMAINDER)
    p = sub.add_parser("detach", help="setsid replacement: exec CMD as a new session leader")
    p.add_argument("command", nargs=argparse.REMAINDER)
    p = sub.add_parser("sha256", help="sha256sum replacement: 'HEX  NAME' lines; '-' or no file reads stdin")
    p.add_argument("files", nargs="*")
    p.add_argument("-c", "--check", action="store_true")
    p = sub.add_parser("remap", help="apply SHENGJI_PATH_MAP to each PATH")
    p.add_argument("paths", nargs="+")
    args = parser.parse_args(argv)

    def emit(value) -> int:
        print(json.dumps(value, sort_keys=True))
        return 0

    try:
        if args.cmd == "mem":
            return emit(memory())
        if args.cmd == "load":
            return emit(load_and_cpus())
        if args.cmd == "rss":
            return emit({"pid": args.pid, "rss_bytes": process_rss_bytes(args.pid)})
        if args.cmd == "group":
            members = group_members(args.pgid)
            return emit({"pgid": args.pgid, "pids": [r.pid for r in members],
                         "states": [r.state for r in members],
                         "rss_bytes": sum(r.rss_bytes for r in members)})
        if args.cmd == "quiesce":
            return 0 if wait_group_quiescent(args.pgid, args.timeout) else 1
        if args.cmd == "writers":
            needle = bytes.fromhex(args.needle).decode() if args.hex else args.needle
            return emit(pids_with_argv_element(needle, program=args.program))
        if args.cmd in ("run", "detach"):
            command = args.command[1:] if args.command[:1] == ["--"] else args.command
            if not command:
                parser.error(f"{args.cmd} needs a command after --")
            if args.cmd == "detach":
                _detach(command)
            sig = _signal_number(args.signal)
            cancel = Cancellation()
            for s in (_signal.SIGTERM, _signal.SIGINT, _signal.SIGHUP):
                _signal.signal(s, lambda signum, _frame: cancel.request(signum))
            try:
                return run_with_timeout(command, args.wall, sig=sig, kill_after_s=args.kill_after,
                                        cancel=cancel)
            except GroupNotDrained as exc:
                print(f"hostinfo: {exc}", file=sys.stderr)
                return GROUP_NOT_DRAINED_STATUS
        if args.cmd == "sha256":
            if args.check:
                listing = "".join(Path(f).read_text() if f != "-" else sys.stdin.read()
                                  for f in (args.files or ["-"]))
                return _check_sums(listing)
            for name in args.files or ["-"]:
                digest = sha256_stream(sys.stdin.buffer) if name == "-" else sha256_file(name)
                print(f"{digest}  {name}")
            return 0
        if args.cmd == "remap":
            mapping = path_map_from_env()
            for path in args.paths:
                print(remap_path(path, mapping))
            return 0
    except HostProbeError as exc:
        print(f"hostinfo: {exc}", file=sys.stderr)
        return 2
    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    sys.exit(main())
