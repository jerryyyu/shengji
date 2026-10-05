from pathlib import Path

import pytest

from shengji.luna import sol_memory_guard as guard


PRESSURE = (
    "some avg10=0.00 avg60=0.00 avg300=0.00 total=1\n"
    "full avg10=0.00 avg60=0.00 avg300=0.00 total=2\n"
)
MOUNTINFO = "36 29 0:32 / /sys/fs/cgroup rw,nosuid - cgroup2 cgroup rw\n"


def _files(relative="/job/leaf", *, available_kb=3 * 1024 * 1024,
           maximum="max", high="max", current="0"):
    files = {
        guard._PROC_PRESSURE_MEMORY: PRESSURE,
        guard._PROC_MEMINFO: (
            f"MemTotal:       {10 * 1024 * 1024} kB\n"
            f"MemAvailable:   {available_kb} kB\n"
        ),
        guard._PROC_MOUNTINFO: MOUNTINFO,
        guard._PROC_SELF_CGROUP: f"0::{relative}\n",
    }
    for ancestor in (relative, "/job"):
        path = guard._CGROUP_ROOT / ancestor.lstrip("/")
        files[path / "memory.max"] = maximum
        files[path / "memory.high"] = high
        files[path / "memory.current"] = current
    return files


def _install(monkeypatch, files):
    monkeypatch.setattr(guard.sys, "platform", "linux")
    monkeypatch.setattr(guard, "_read_text", lambda path: files[path])


def test_linux_guard_checks_host_cgroup_and_pressure_twice(monkeypatch):
    files = _files(maximum=str(5 * 1024**3), current=str(1024**3))
    pressure_reads = []

    def read(path):
        if path == guard._PROC_PRESSURE_MEMORY:
            pressure_reads.append(path)
        return files[path]

    monkeypatch.setattr(guard.sys, "platform", "linux")
    monkeypatch.setattr(guard, "_read_text", read)
    assert guard.assert_memory_headroom()
    assert len(pressure_reads) == 2


@pytest.mark.parametrize("snapshot", [
    PRESSURE.replace("full ", "some "),
    PRESSURE.replace("avg10=0.00", "avg10=-0.01", 1),
    PRESSURE.replace("avg60=0.00", "avg60=nan", 1),
    PRESSURE.replace(" total=1", " total=1 total=2", 1),
])
def test_linux_pressure_requires_two_zero_well_formed_rows(snapshot):
    with pytest.raises(ValueError):
        guard._linux_pressure_is_zero(snapshot)


@pytest.mark.parametrize("field", ["memory.max", "memory.high"])
def test_linux_cgroup_finite_limit_requires_headroom(field):
    files = _files(maximum="max", high="max", current=str(3 * 1024**3))
    files[guard._CGROUP_ROOT / "job" / field] = str(4 * 1024**3)
    reader = lambda path: files[path]
    assert guard._linux_cgroup_headroom("/job/leaf", reader) is False


def test_linux_cgroup_unlimited_limits_are_valid():
    files = _files()
    assert guard._linux_cgroup_headroom("/job/leaf", lambda path: files[path])


def test_linux_root_cgroup_uses_host_meminfo_only():
    assert guard._linux_cgroup_path("0::/\n") == "/"
    assert guard._linux_cgroup_headroom("/", lambda path: pytest.fail("root file probe"))


@pytest.mark.parametrize("mountinfo", [
    "36 29 0:32 /hidden /sys/fs/cgroup rw - cgroup2 cgroup rw\n",
    "36 29 0:32 / /sys/fs/cgroup rw - cgroup cgroup rw\n",
    "36 29 0:32 / /other rw - cgroup2 cgroup rw\n",
])
def test_linux_mount_namespace_and_v1_layouts_fail_closed(monkeypatch, mountinfo):
    files = _files()
    files[guard._PROC_MOUNTINFO] = mountinfo
    _install(monkeypatch, files)
    assert not guard.assert_memory_headroom()


def test_linux_second_pressure_read_can_reject(monkeypatch):
    files = _files()
    unsafe = PRESSURE.replace("avg10=0.00", "avg10=0.01", 1)
    pressures = iter((PRESSURE, unsafe))

    def read(path):
        return next(pressures) if path == guard._PROC_PRESSURE_MEMORY else files[path]

    monkeypatch.setattr(guard.sys, "platform", "linux")
    monkeypatch.setattr(guard, "_read_text", read)
    assert not guard.assert_memory_headroom()


def test_linux_probe_read_error_is_unsafe(monkeypatch):
    files = _files()
    _install(monkeypatch, files)
    files.pop(guard._PROC_MEMINFO)

    def read(path):
        if path not in files:
            raise OSError("missing")
        return files[path]

    monkeypatch.setattr(guard, "_read_text", read)
    assert not guard.assert_memory_headroom()


@pytest.mark.parametrize("available_kb,expected", [
    (2 * 1024**2 - 1, False), (2 * 1024**2, True),
])
def test_linux_host_headroom_boundary(monkeypatch, available_kb, expected):
    _install(monkeypatch, _files(available_kb=available_kb))
    assert guard.assert_memory_headroom() is expected


@pytest.mark.parametrize("snapshot", [
    "MemTotal: 100 kB\n", "MemTotal: 100 kB\nMemAvailable: 101 kB\n",
    "MemTotal: 100 kB\nMemAvailable: 10 MB\n",
    "MemTotal: 100 kB\nMemAvailable: 10 kB\nMemAvailable: 10 kB\n",
])
def test_linux_meminfo_rejects_invalid_snapshot(snapshot):
    with pytest.raises(ValueError):
        guard._linux_meminfo_available_bytes(snapshot)


@pytest.mark.parametrize("membership", [
    "0::/job/../other\n", "0:://job\n", "0::/job/\n",
    "0::/job\n1:memory:/job\n", "1:memory:/job\n",
])
def test_linux_bad_membership_fails_closed(monkeypatch, membership):
    files = _files()
    files[guard._PROC_SELF_CGROUP] = membership
    _install(monkeypatch, files)
    assert not guard.assert_memory_headroom()


@pytest.mark.parametrize("field,value", [
    ("memory.current", "max"), ("memory.max", "-1"),
    ("memory.high", "garbage"),
])
def test_linux_malformed_cgroup_fails_closed(monkeypatch, field, value):
    files = _files()
    files[guard._CGROUP_ROOT / "job/leaf" / field] = value
    _install(monkeypatch, files)
    assert not guard.assert_memory_headroom()
