"""Host probes behave the same on Linux (CI) and macOS (the Mini and the Ultra)."""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import signal
import subprocess
import sys
import time

import pytest

from shengji.ops import hostinfo as hi

SERVER = Path(__file__).resolve().parents[1]
SLEEPER = "import time\ntime.sleep(60)"


def _cli(*args, **kw):
    env = dict(os.environ, PYTHONPATH=str(SERVER))
    env.update(kw.pop("env", {}))
    return subprocess.run([sys.executable, "-m", "shengji.ops.hostinfo", *args],
                          capture_output=True, text=True, env=env, timeout=60, **kw)


def _reap(child):
    try:
        os.killpg(child.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    child.wait()


def test_platform_is_supported():
    assert hi.platform_kind() in ("linux", "darwin")


def test_ps_table_parses_and_refuses_partial_census():
    rows = hi.parse_ps_table("  10  1 10  20 Ss 501\n  11 10 10  30 R+ 501\n")
    assert rows[11] == hi.ProcRow(11, 10, 10, 30 * 1024, "R+", 501)
    assert hi.group_rss_bytes(10, rows) == 50 * 1024
    for bad in ("", "10 1 10 20 S 501", "10 1 10 S 501\n", "10 1 10 -2 S 501\n",
                "10 1 10 20 S 501\n10 1 10 30 S 501\n"):
        with pytest.raises(hi.HostProbeError):
            hi.parse_ps_table(bad)


def test_meminfo_parse():
    text = "MemTotal:       32000 kB\nMemFree: 1 kB\nMemAvailable:   16000 kB\n"
    assert hi.parse_meminfo(text) == {"total_bytes": 32000 * 1024, "available_bytes": 16000 * 1024}
    for bad in ("MemTotal: 1 kB\n", "MemTotal: 1 kB\nMemAvailable: x kB\n",
                "MemTotal: 1 kB\nMemAvailable: 1 kB\nMemAvailable: 1 kB\n"):
        with pytest.raises(hi.HostProbeError):
            hi.parse_meminfo(bad)


def test_live_process_table_sees_this_process():
    row = hi.process_table()[os.getpid()]
    assert row.pgid == os.getpgrp() and row.ppid == os.getppid() and row.uid == os.getuid()
    assert row.rss_bytes > 1 << 20
    assert hi.process_rss_bytes(os.getpid()) > 1 << 20


def test_memory_and_load_are_sane():
    mem = hi.memory()
    assert 0 < mem["available_bytes"] <= mem["total_bytes"]
    load = hi.load_and_cpus()
    assert len(load["loadavg"]) == 3 and load["cpus"] >= 1


def test_new_session_group_census_and_quiescence():
    child = hi.spawn_new_session([sys.executable, "-c",
                                  "import subprocess,sys,time\n"
                                  f"subprocess.Popen([sys.executable,'-c',{SLEEPER!r}])\n"
                                  "time.sleep(60)"])
    try:
        assert os.getpgid(child.pid) == child.pid and os.getsid(child.pid) == child.pid
        deadline = time.monotonic() + 20
        while len(hi.group_members(child.pid)) < 2 and time.monotonic() < deadline:
            time.sleep(0.05)
        members = hi.group_members(child.pid)
        assert len(members) == 2 and child.pid in {r.pid for r in members}
        assert hi.group_rss_bytes(child.pid) > 0
        assert not hi.wait_group_quiescent(child.pid, 0.2)
    finally:
        _reap(child)
    assert hi.wait_group_quiescent(child.pid, 10)
    assert hi.process_rss_bytes(child.pid) is None


def test_exact_argv_and_writer_probe():
    needle = f"/tmp/partial dir {os.getpid()}/x"
    child = subprocess.Popen([sys.executable, "-c", SLEEPER, needle])
    try:
        deadline = time.monotonic() + 20
        while hi.process_argv(child.pid) is None or len(hi.process_argv(child.pid)) < 4:
            assert time.monotonic() < deadline
            time.sleep(0.05)
        assert hi.process_argv(child.pid)[1:] == ("-c", SLEEPER, needle)
        assert hi.pids_with_argv_element(needle) == [child.pid]
        assert hi.pids_with_argv_element(needle[:-1]) == []          # whole elements only
        assert hi.pids_with_argv_element(needle, program="tar") == []
        prog = os.path.basename(hi.process_argv(child.pid)[0])
        assert hi.pids_with_argv_element(needle, program=prog) == [child.pid]
        # The probe's own command line carries the needle but never matches itself.
        out = _cli("writers", "--hex", needle.encode().hex())
        assert out.returncode == 0 and json.loads(out.stdout) == [child.pid]
    finally:
        child.kill()
        child.wait()
    assert hi.pids_with_argv_element(needle) == []


def test_run_with_timeout_statuses_match_gnu_timeout():
    py = sys.executable
    assert hi.run_with_timeout([py, "-c", "raise SystemExit(3)"], 30) == 3
    assert hi.run_with_timeout([py, "-c", "import os,signal; os.kill(os.getpid(), signal.SIGTERM)"], 30) == 143
    start = time.monotonic()
    assert hi.run_with_timeout([py, "-c", SLEEPER], 0.5) == 124
    assert hi.run_with_timeout([py, "-c", SLEEPER], 0.5, sig=signal.SIGKILL) == 137
    ignore_term = "import signal,time\nsignal.signal(signal.SIGTERM, signal.SIG_IGN)\ntime.sleep(60)"
    assert hi.run_with_timeout([py, "-c", ignore_term], 0.5, kill_after_s=0.5) == 137
    assert time.monotonic() - start < 20


def test_timeout_stops_the_whole_group():
    marker = f"grandchild-{os.getpid()}-{time.time_ns()}"
    script = ("import subprocess,sys,time\n"
              f"subprocess.Popen([sys.executable,'-c',{SLEEPER!r},{marker!r}])\n"
              "time.sleep(60)")
    seen = {}
    assert hi.run_with_timeout([sys.executable, "-c", script], 1.5,
                               on_start=lambda c: seen.setdefault("pid", c.pid)) == 124
    assert hi.wait_group_quiescent(seen["pid"], 10)
    assert hi.pids_with_argv_element(marker) == []


def test_cli_run_and_detach():
    assert _cli("run", "--wall", "30", "--", sys.executable, "-c", "raise SystemExit(5)").returncode == 5
    assert _cli("run", "--wall", "0.5", "--signal", "KILL", "--", sys.executable, "-c", SLEEPER).returncode == 137
    probe = "import os; print(os.getsid(0) == os.getpid(), os.getpgrp() == os.getpid())"
    out = _cli("detach", "--", sys.executable, "-c", probe)
    assert out.returncode == 0 and out.stdout.split() == ["True", "True"]
    # Already a group leader: setsid(2) refuses, so the helper forks first like setsid(1).
    out = _cli("detach", "--", sys.executable, "-c", probe, start_new_session=True)
    assert out.returncode == 0 and out.stdout.split() == ["True", "True"]


def test_cli_probes_emit_json():
    mem = json.loads(_cli("mem").stdout)
    assert mem["total_bytes"] >= mem["available_bytes"] > 0
    group = json.loads(_cli("group", str(os.getpgrp())).stdout)
    assert os.getpid() in group["pids"] and group["rss_bytes"] > 0
    assert json.loads(_cli("rss", str(os.getpid())).stdout)["rss_bytes"] > 0


def test_sha256_matches_sha256sum_format(tmp_path):
    a = tmp_path / "a b.bin"
    a.write_bytes(b"shengji\n" * 1000)
    want = hashlib.sha256(a.read_bytes()).hexdigest()
    assert hi.sha256_file(a) == want
    out = _cli("sha256", str(a))
    assert out.stdout == f"{want}  {a}\n"
    assert _cli("sha256", input=a.read_text()).stdout == f"{want}  -\n"
    sums = tmp_path / "SUMS"
    sums.write_text(out.stdout)
    assert _cli("sha256", "-c", str(sums)).returncode == 0
    a.write_bytes(b"changed")
    bad = _cli("sha256", "-c", str(sums))
    assert bad.returncode == 1 and "FAILED" in bad.stdout


def test_path_map_parse_and_remap():
    m = hi.parse_path_map("/root=/Users/u/fleet;/root/traj-out=/Volumes/ssd/traj")
    assert [str(o) for o, _ in m] == ["/root/traj-out", "/root"]          # longest first
    assert hi.remap_path("/root/traj-out/runY/m.json", m) == Path("/Volumes/ssd/traj/runY/m.json")
    assert hi.remap_path("/root/g3/rows", m) == Path("/Users/u/fleet/g3/rows")
    assert hi.remap_path("/root", m) == Path("/Users/u/fleet")
    assert hi.remap_path("/rootless/x", m) == Path("/rootless/x")          # component boundary
    assert hi.remap_path("/data/x", m) == Path("/data/x")
    assert hi.remap_path("/root/x", ()) == Path("/root/x")
    assert hi.parse_path_map("") == () and hi.parse_path_map(None) == ()
    for bad in ("/root", "root=/x", "/root=x", "/root/../etc=/x", "/=/x", "/root=/a;/root=/b"):
        with pytest.raises(ValueError):
            hi.parse_path_map(bad)
    assert hi.path_map_from_env({hi.PATH_MAP_ENV: "/a=/b"}) == ((PurePosixPath("/a"), PurePosixPath("/b")),)
    out = _cli("remap", "/root/x", "/other", env={hi.PATH_MAP_ENV: "/root=/fleet"})
    assert out.stdout.split() == ["/fleet/x", "/other"]
