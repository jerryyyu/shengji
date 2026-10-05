"""Read-only macOS admission guard, extracted from the reviewed recovery packet."""
import re
import subprocess
import sys

MIN_AVAILABLE_MEMORY_BYTES = 2 * 1024 ** 3
_VM_HEADER = re.compile(r"Mach Virtual Memory Statistics: \(page size of ([0-9]+) bytes\)")
_VM_FIELDS = frozenset(("Pages free", "Pages speculative", "Pages inactive"))


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


def assert_memory_headroom() -> bool:
    """Return whether the host is safe to admit another Mini row.

    The production gate is defined for macOS. Any other platform, command, or
    parse failure is deliberately treated as unknown (therefore unsafe).
    """
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
