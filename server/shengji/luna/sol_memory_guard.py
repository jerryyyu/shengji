"""Read-only admission guard for the reviewed recovery packet."""
import math
from pathlib import Path
import re
import subprocess
import sys

MIN_AVAILABLE_MEMORY_BYTES = 2 * 1024 ** 3
_VM_HEADER = re.compile(r"Mach Virtual Memory Statistics: \(page size of ([0-9]+) bytes\)")
_VM_FIELDS = frozenset(("Pages free", "Pages speculative", "Pages inactive"))
_LINUX_PRESSURE_FIELDS = frozenset(("avg10", "avg60", "avg300", "total"))
_LINUX_MEMINFO_FIELDS = frozenset(("MemAvailable", "MemTotal"))
_CGROUP_ROOT = Path("/sys/fs/cgroup")
_PROC_MEMINFO = Path("/proc/meminfo")
_PROC_PRESSURE_MEMORY = Path("/proc/pressure/memory")
_PROC_SELF_CGROUP = Path("/proc/self/cgroup")
_PROC_MOUNTINFO = Path("/proc/self/mountinfo")


def available_memory_bytes(snapshot: str) -> int:
    """Parse one macOS vm_stat snapshot, not the interval/table format.

    This is a reclaimable-headroom estimate, not an allocation guarantee.
    vm_stat prints free_count MINUS speculative_count as 'Pages free', so
    adding its separate speculative line does not double count. Inactive
    pages can be reclaimed; pressure must independently remain normal.
    See Apple's system_cmds/vm_stat/vm_stat.c snapshot() implementation.
    """
    if not isinstance(snapshot, str):
        raise ValueError("vm_stat snapshot must be text")
    lines = snapshot.strip().splitlines()
    header = _VM_HEADER.fullmatch(lines[0].strip()) if lines else None
    if header is None:
        raise ValueError("missing or malformed vm_stat page size")
    page_size = int(header.group(1))
    if page_size not in (4096, 16384):
        raise ValueError("unsupported macOS page size")
    counts = {}
    for line in lines[1:]:
        name, separator, value = line.strip().partition(":")
        if name not in _VM_FIELDS:
            if line.strip().startswith("Mach Virtual Memory Statistics:"):
                raise ValueError("multiple vm_stat snapshots")
            continue
        if not separator or name in counts or re.fullmatch(r"[0-9]+\.", value.strip()) is None:
            raise ValueError("missing, duplicate or malformed vm_stat count")
        counts[name] = int(value.strip()[:-1])
    if set(counts) != _VM_FIELDS:
        raise ValueError("incomplete vm_stat counts")
    available = sum(counts.values()) * page_size
    if available > 2 ** 64 - 1:
        raise ValueError("vm_stat byte count out of range")
    return available


def _read_text(path: Path) -> str:
    """Read one proc/cgroup file; kept separate for deterministic tests."""
    return path.read_text()


def _linux_meminfo_available_bytes(snapshot: str) -> int:
    if not isinstance(snapshot, str):
        raise ValueError("meminfo must be text")
    values = {}
    for line in snapshot.splitlines():
        match = re.fullmatch(r"(MemAvailable|MemTotal):[ \t]+([0-9]+)[ \t]+kB[ \t]*", line)
        if match is None:
            if line.startswith(("MemAvailable", "MemTotal")):
                raise ValueError("malformed meminfo field")
            continue
        name, value = match.groups()
        if name in values:
            raise ValueError("duplicate meminfo field")
        values[name] = int(value)
    if set(values) != _LINUX_MEMINFO_FIELDS:
        raise ValueError("incomplete meminfo")
    available_kb = values["MemAvailable"]
    total_kb = values["MemTotal"]
    if not 0 <= available_kb <= total_kb:
        raise ValueError("invalid meminfo bounds")
    return available_kb * 1024


def _linux_pressure_is_zero(snapshot: str) -> bool:
    if not isinstance(snapshot, str):
        raise ValueError("pressure must be text")
    rows = {}
    for line in snapshot.splitlines():
        fields = line.split()
        if len(fields) != 5 or fields[0] not in ("some", "full") or fields[0] in rows:
            raise ValueError("malformed pressure rows")
        values = {}
        for field in fields[1:]:
            name, separator, value = field.partition("=")
            if not separator or name in values or name not in _LINUX_PRESSURE_FIELDS:
                raise ValueError("malformed pressure fields")
            values[name] = value
        if set(values) != _LINUX_PRESSURE_FIELDS:
            raise ValueError("incomplete pressure row")
        for name in ("avg10", "avg60", "avg300"):
            try:
                average = float(values[name])
            except (TypeError, ValueError, OverflowError):
                raise ValueError("malformed pressure average") from None
            if not math.isfinite(average) or average < 0.0 or average > 0.0:
                raise ValueError("unsafe pressure average")
        if re.fullmatch(r"[0-9]+", values["total"]) is None:
            raise ValueError("malformed pressure total")
        rows[fields[0]] = values
    if set(rows) != {"some", "full"}:
        raise ValueError("incomplete pressure rows")
    return True


def _safe_cgroup_relative_path(value: str) -> str:
    if not isinstance(value, str) or not value.startswith("/") or value.startswith("//"):
        raise ValueError("cgroup path is not absolute")
    if "\x00" in value or (value != "/" and value.endswith("/")):
        raise ValueError("unsafe cgroup path")
    if value == "/":
        return value
    components = value.split("/")[1:]
    if any(not component or component in (".", "..") for component in components):
        raise ValueError("unsafe cgroup path")
    return value


def _linux_cgroup_path(cgroup_text: str) -> str:
    if not isinstance(cgroup_text, str):
        raise ValueError("cgroup membership must be text")
    lines = cgroup_text.splitlines()
    if len(lines) != 1:
        raise ValueError("non-unified or duplicate cgroup membership")
    hierarchy, separator, relative = lines[0].partition(":")
    controllers, separator2, relative = relative.partition(":") if separator else ("", "", "")
    if hierarchy != "0" or controllers != "" or not separator2:
        raise ValueError("non-unified cgroup membership")
    return _safe_cgroup_relative_path(relative)


def _mountinfo_path(value: str) -> str:
    # mountinfo escapes whitespace and backslashes as octal sequences.
    def replace(match):
        number = int(match.group(1), 8)
        if number == 0 or number > 255:
            raise ValueError("invalid mountinfo escape")
        return chr(number)

    if not isinstance(value, str) or "\\" not in value:
        return value
    return re.sub(r"\\([0-7]{3})", replace, value)


def _linux_unified_cgroup_mount(mountinfo: str) -> None:
    if not isinstance(mountinfo, str):
        raise ValueError("mountinfo must be text")
    found = False
    for line in mountinfo.splitlines():
        if not line or line.count(" - ") != 1:
            raise ValueError("malformed mountinfo")
        left, _separator, right = line.partition(" - ")
        left_fields = left.split()
        right_fields = right.split()
        if len(left_fields) < 6 or len(right_fields) < 3:
            raise ValueError("malformed mountinfo")
        root = _mountinfo_path(left_fields[3])
        mountpoint = _mountinfo_path(left_fields[4])
        filesystem = right_fields[0]
        if filesystem == "cgroup" or filesystem == "cgroup2":
            if filesystem != "cgroup2" or root != "/" or mountpoint != str(_CGROUP_ROOT) or found:
                raise ValueError("unsupported cgroup mount layout")
            found = True
    if not found:
        raise ValueError("missing unified cgroup mount")


def _linux_cgroup_headroom(relative: str, read_text) -> bool:
    relative = _safe_cgroup_relative_path(relative)
    current = _CGROUP_ROOT / relative.lstrip("/") if relative != "/" else _CGROUP_ROOT
    while current != _CGROUP_ROOT:
        values = {}
        for name in ("memory.max", "memory.high", "memory.current"):
            text = read_text(current / name)
            if not isinstance(text, str):
                raise ValueError("cgroup file must be text")
            value = text.strip()
            if name != "memory.current" and value == "max":
                values[name] = None
            elif re.fullmatch(r"[0-9]+", value):
                values[name] = int(value)
            else:
                raise ValueError("malformed cgroup value")
        if values["memory.current"] is None:
            raise ValueError("memory.current cannot be unlimited")
        for name in ("memory.max", "memory.high"):
            cap = values[name]
            if cap is not None:
                headroom = cap - values["memory.current"]
                if headroom < MIN_AVAILABLE_MEMORY_BYTES:
                    return False
        current = current.parent
    return True


def _linux_memory_headroom_safe() -> bool:
    """Perform Linux admission checks with no subprocess or bypass path."""
    reader = _read_text
    # Read pressure on both sides of all other checks to avoid admitting during
    # a newly developing stall. Linux PSI's zero recent-stall threshold is a
    # deliberately conservative admission policy, not a macOS equivalence.
    _linux_pressure_is_zero(reader(_PROC_PRESSURE_MEMORY))
    available = _linux_meminfo_available_bytes(reader(_PROC_MEMINFO))
    _linux_unified_cgroup_mount(reader(_PROC_MOUNTINFO))
    relative = _linux_cgroup_path(reader(_PROC_SELF_CGROUP))
    cgroup_safe = _linux_cgroup_headroom(relative, reader)
    _linux_pressure_is_zero(reader(_PROC_PRESSURE_MEMORY))
    return available >= MIN_AVAILABLE_MEMORY_BYTES and cgroup_safe


def assert_memory_headroom() -> bool:
    """Return whether the host has headroom to admit another recovery row.

    Any unsupported platform, command, or parse failure is deliberately
    treated as unknown (therefore unsafe).
    """
    if sys.platform == "linux":
        try:
            return _linux_memory_headroom_safe()
        except (OSError, TypeError, UnicodeError, ValueError, OverflowError):
            return False
    if sys.platform != "darwin":
        return False
    try:
        pressure_command = ["/usr/sbin/sysctl", "-n", "kern.memorystatus_vm_pressure_level"]
        def normal_pressure():
            value = subprocess.run(pressure_command, check=True, capture_output=True,
                                   text=True, timeout=5).stdout
            return isinstance(value, str) and value.strip() == "1"
        if not normal_pressure():
            return False
        snapshot = subprocess.run(["/usr/bin/vm_stat"], check=True,
                                  capture_output=True, text=True, timeout=5).stdout
        return available_memory_bytes(snapshot) >= MIN_AVAILABLE_MEMORY_BYTES and normal_pressure()
    except (OSError, TypeError, ValueError, subprocess.SubprocessError):
        return False
