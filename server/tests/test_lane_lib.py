"""Drive server/scripts/lanes/lane_lib.sh through a stub launcher and a stub producer in temporary directories.

Every case runs a real bash launcher that sources the library, with its own RELEASE, HOLD, gate, lock and output
paths under tmp_path; nothing touches a real host lock or lane.  The producer stub writes shard files slowly, records
each invocation, and starts a child in its own process group so a stop must reach the whole group.
"""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

SERVER = Path(__file__).resolve().parents[1]
LIB = Path(os.environ.get("LANE_LIB_UNDER_TEST") or SERVER / "scripts" / "lanes" / "lane_lib.sh")
BASH = "/bin/bash"
PY = sys.executable

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX process groups")

STUB = textwrap.dedent("""\
    import os, signal, subprocess, sys, time
    out, n, delay, marker, status = sys.argv[1], int(sys.argv[2]), float(sys.argv[3]), sys.argv[4], sys.argv[5]

    def on_term(signum, frame):
        # a slow shutdown, recorded in the lane status: the lock must not be released before this line
        time.sleep(0.5)
        with open(status, "a") as f:
            f.write("TL STUBEXIT t1 producer stopped\\n")
        os._exit(143)

    signal.signal(signal.SIGTERM, on_term)
    with open(marker, "a") as f:
        f.write(f"pid={os.getpid()} pgid={os.getpgid(0)}\\n")
    child = subprocess.Popen(["sleep", "300"])
    with open(marker + ".child", "w") as f:
        f.write(str(child.pid))
    os.makedirs(out, exist_ok=True)
    for i in range(n):
        p = os.path.join(out, f"shard-{i:04d}.json")
        if not os.path.exists(p):
            time.sleep(delay)
            with open(p, "w") as f:
                f.write("{}")
    child.terminate()
    child.wait()
    sys.exit(int(os.environ.get("STUB_RC", "0")))
""")

LAUNCHER = textwrap.dedent("""\
    #!/bin/bash
    set -u
    W=$(cd "$(dirname "$0")" && pwd)
    . "$LANE_LIB"
    . "$W/config.env"
    LANE_FILES=("$W/launcher.sh" "$LANE_LIB" "$W/config.env")
    lane_init
    lane_arm; g=$?
    [ "$g" = 3 ] && lane_pause "$LANE_MSG"
    [ "$g" = 0 ] || lane_abort 6 "$LANE_MSG"
    lane_lock_acquire; g=$?
    case "$g" in 0) ;; 3) lane_pause "$LANE_MSG" ;; 5) lane_abort 5 "$LANE_MSG" ;; *) lane_abort 6 "$LANE_MSG" ;; esac
    lane_admit after-wait; g=$?
    [ "$g" = 3 ] && lane_pause "$LANE_MSG"
    [ "$g" = 0 ] || lane_abort 6 "$LANE_MSG"
    lane_say CHECKED "$LANE_MSG"
    lane_supervise "$LANE_PY" "$W/stub.py" "$W/out" "$SHARDS" "$DELAY" "$W/PRODUCER_INVOKED" "$LANE_STATUS"; rc=$?
    [ "$rc" = 0 ] || lane_abort "$rc" "producer rc=$rc"
    n=$(lane_count_files "$W/out" 'shard-*.json')
    [ "$n" = "$SHARDS" ] || lane_abort 4 "rc 0 but shards=$n"
    lane_done "shards=$n"
""")


class Lane:
    def __init__(self, root: Path, **overrides):
        self.w = root
        (root / "pkg").mkdir()
        (root / "pkg" / "model.bin").write_text("weights\n")
        (root / "stub.py").write_text(STUB)
        (root / "launcher.sh").write_text(LAUNCHER)
        self.status = root / "t1.status"
        self.lock = root / "lock"
        self.hold = root / "HOLD"
        cfg = {
            "LANE_NAME": "t1", "LANE_PREFIX": "TL", "LANE_STATUS": str(self.status),
            "LANE_RELEASE": str(root / "RELEASE"), "LANE_HOLDS": f"'{self.hold} {root / 'HOLD.global'}'",
            "LANE_HOSTNAME": "$(hostname)", "LANE_LOCK": str(self.lock), "LANE_PY": PY,
            "LANE_LOG": str(root / "producer.log"), "LANE_POLL": "0.2", "LANE_MON_POLL": "0.2",
            "LANE_STOP_GRACE": "5", "LANE_WAIT_CEILING": "60", "LANE_MAX_SECONDS": "60",
            "LANE_PINS": f"'{sha(root / 'pkg' / 'model.bin')}  {root / 'pkg' / 'model.bin'}'",
            "SHARDS": "4", "DELAY": "0.05",
        }
        cfg.update(overrides)
        (root / "config.env").write_text("".join(f"{k}={v}\n" for k, v in cfg.items()))

    def env(self):
        return {**os.environ, "LANE_LIB": str(LIB)}

    def identity(self) -> str:
        cmd = (f'. "{LIB}"; lane_identity "{self.w}/launcher.sh" "{LIB}" "{self.w}/config.env"')
        return subprocess.run([BASH, "-c", cmd], check=True, capture_output=True, text=True).stdout.strip()

    def arm(self):
        (self.w / "RELEASE").write_text(self.identity() + "  armed by test\n")

    def start(self) -> subprocess.Popen:
        return subprocess.Popen([BASH, str(self.w / "launcher.sh")], env=self.env(),
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)

    def run(self, timeout=60) -> int:
        return subprocess.run([BASH, str(self.w / "launcher.sh")], env=self.env(), capture_output=True,
                              timeout=timeout).returncode

    def invocations(self) -> int:
        p = self.w / "PRODUCER_INVOKED"
        return p.read_text().count("pid=") if p.exists() else 0

    def lines(self):
        return self.status.read_text().splitlines() if self.status.exists() else []

    def terminal(self) -> str:
        t = [ln for ln in self.lines() if ln.split()[1:2] and ln.split()[1] in ("DONE", "PAUSED", "ABORT")]
        assert len(t) == 1, self.lines()
        return t[0]

    def words(self):
        return [ln.split()[1] for ln in self.lines()]

    def shards(self) -> int:
        d = self.w / "out"
        return len(list(d.glob("shard-*.json"))) if d.exists() else 0

    def pgid(self) -> int:
        line = (self.w / "PRODUCER_INVOKED").read_text().splitlines()[-1]
        return int(line.split("pgid=")[1])

    def fake_lock(self):
        self.lock.mkdir()
        (self.lock / "owner").write_text("1 other-lane 2026-01-01T00:00:00Z\n")

    def free_fake_lock(self):
        (self.lock / "owner").unlink()
        self.lock.rmdir()


def sha(p: Path) -> str:
    import hashlib
    return hashlib.sha256(p.read_bytes()).hexdigest()


def wait_for(pred, timeout=30.0):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.1)
    raise AssertionError("condition not reached")


def group_members(pgid: int) -> int:
    r = subprocess.run(["pgrep", "-g", str(pgid)], capture_output=True, text=True)
    return len(r.stdout.split())


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    # a zombie still answers kill 0; ps shows its state
    st = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
    return bool(st) and not st.startswith("Z")


@pytest.fixture
def lane(tmp_path):
    return lambda **kw: Lane(tmp_path, **kw)


# ---------------------------------------------------------------- admission

def test_positive_control(lane):
    ln = lane(); ln.arm()
    assert ln.run() == 0
    assert ln.terminal().startswith("TL DONE t1 ") and "shards=4 rc=0" in ln.terminal()
    assert ln.invocations() == 1 and not ln.lock.exists()
    assert ln.words().index("DONE") < ln.words().index("UNLOCKED")


def test_missing_release_refuses(lane):
    ln = lane()
    assert ln.run() == 6
    assert "ABORT" in ln.terminal() and "RELEASE" in ln.terminal()
    assert ln.invocations() == 0


def test_wrong_release_refuses(lane):
    ln = lane()
    (ln.w / "RELEASE").write_text("0" * 64 + "\n")
    assert ln.run() == 6
    assert "is not the launcher identity" in ln.terminal()
    assert ln.invocations() == 0


def test_symlink_release_refuses_even_with_the_right_token(lane):
    ln = lane()
    (ln.w / "token").write_text(ln.identity() + "\n")
    (ln.w / "RELEASE").symlink_to(ln.w / "token")
    assert ln.run() == 6
    assert "not a regular file" in ln.terminal()
    assert ln.invocations() == 0


def test_wrong_hostname_refuses(lane):
    ln = lane(LANE_HOSTNAME="not-this-host"); ln.arm()
    assert ln.run() == 6 and "hostname" in ln.terminal() and ln.invocations() == 0


def test_hold_at_arming_pauses(lane):
    ln = lane(); ln.arm(); (ln.w / "HOLD.global").touch()
    assert ln.run() == 1 and "PAUSED" in ln.terminal() and ln.invocations() == 0


@pytest.mark.parametrize("what", ["config", "launcher", "pin", "release"])
def test_change_during_the_wait_refuses_before_the_producer(lane, what):
    ln = lane(); ln.arm(); ln.fake_lock()
    p = ln.start()
    wait_for(lambda: "WAIT" in ln.words())
    if what == "config":
        with open(ln.w / "config.env", "a") as f:
            f.write("# edited\n")
    elif what == "launcher":
        with open(ln.w / "launcher.sh", "a") as f:
            f.write("# edited\n")
    elif what == "pin":
        (ln.w / "pkg" / "model.bin").write_text("other weights\n")
    else:
        (ln.w / "RELEASE").unlink()
    ln.free_fake_lock()
    assert p.wait(30) == 6
    t = ln.terminal()
    assert "ABORT" in t and "after-wait" in t, t
    assert ln.invocations() == 0
    assert not ln.lock.exists()


def test_re_released_change_during_the_wait_refuses(lane):
    """A RELEASE rewritten for an edited launcher does not admit the process armed with the old one."""
    ln = lane(); ln.arm(); ln.fake_lock()
    p = ln.start()
    wait_for(lambda: "WAIT" in ln.words())
    with open(ln.w / "config.env", "a") as f:
        f.write("# edited\n")
    ln.arm()
    ln.free_fake_lock()
    assert p.wait(30) == 6
    assert "changed since arming" in ln.terminal()
    assert ln.invocations() == 0


def test_hold_during_the_wait_pauses_and_leaves_the_other_lock(lane):
    ln = lane(); ln.arm(); ln.fake_lock()
    p = ln.start()
    wait_for(lambda: "WAIT" in ln.words())
    ln.hold.touch()
    assert p.wait(30) == 1
    assert "PAUSED" in ln.terminal() and "HOLD" in ln.terminal()
    assert ln.invocations() == 0
    assert (ln.lock / "owner").read_text().startswith("1 other-lane")


# ---------------------------------------------------------------- gates and the lock

def test_gate_waits_for_the_anchored_terminal_line(lane, tmp_path):
    pred = tmp_path / "pred.status"
    pred.write_text("2026-11-09T00:00:00Z X3B START\n")
    ln = lane(LANE_GATES=f"'{pred} ^[0-9TZ:-]+ X3B DONE( |$)'"); ln.arm()
    p = ln.start()
    wait_for(lambda: "WAIT" in ln.words())
    time.sleep(1.0)
    assert ln.invocations() == 0 and not ln.lock.exists()
    with open(pred, "a") as f:
        f.write("2026-11-09T01:00:00Z X3B DONE package=x\n")
    assert p.wait(30) == 0 and "DONE" in ln.terminal() and ln.invocations() == 1


def test_gate_stops_on_a_failed_predecessor_that_quotes_the_word(lane, tmp_path):
    pred = tmp_path / "pred.status"
    pred.write_text("2026-11-09T00:00:00Z X3B ABORT rc=1 no X3B DONE line\n")
    ln = lane(LANE_GATES=f"'{pred} ^[0-9TZ:-]+ X3B DONE( |$)'"); ln.arm()
    assert ln.run() == 6
    assert "ended without success" in ln.terminal() and ln.invocations() == 0


def test_gate_proceed_file_opens_predecessors(lane, tmp_path):
    pred = tmp_path / "pred.status"
    pred.write_text("2026-11-09T00:00:00Z SBX START\n")
    ln = lane(LANE_GATES=f"'{pred} ^[0-9TZ:-]+ SBX DONE( |$)'", LANE_GATE_PROCEED=str(tmp_path / "PROCEED"))
    ln.arm()
    p = ln.start()
    wait_for(lambda: "WAIT" in ln.words())
    assert ln.invocations() == 0
    (tmp_path / "PROCEED").touch()
    assert p.wait(30) == 0 and ln.invocations() == 1


def test_yield_to_a_released_run_but_not_to_itself_or_a_finished_one(lane, tmp_path):
    q = tmp_path / "queue"; q.mkdir()
    ln = lane(LANE_YIELD_DIR=str(q), LANE_YIELD_GLOB="'claude_x2duel_*.RELEASE'",
              LANE_RELEASE=str(q / "claude_x2duel_SELF.RELEASE"))
    (q / "claude_x2duel_SELF.RELEASE").write_text(ln.identity() + "\n")
    (q / "claude_x2duel_OLD.RELEASE").write_text("tok\n")
    (q / "claude_x2duel_OLD.status").write_text("2026-11-09T01:00:00Z X2DUEL DONE OLD rc=0\n")
    (q / "claude_x2duel_CBX.RELEASE").write_text("tok\n")
    p = ln.start()
    wait_for(lambda: "WAIT" in ln.words())
    time.sleep(1.0)
    assert ln.invocations() == 0 and "claude_x2duel_CBX.RELEASE" in ln.lines()[-1]
    (q / "claude_x2duel_CBX.status").write_text("2026-11-09T02:00:00Z X2DUEL START CBX\n")
    time.sleep(1.0)
    assert ln.invocations() == 0
    with open(q / "claude_x2duel_CBX.status", "a") as f:
        f.write("2026-11-09T03:00:00Z X2DUEL FAILED CBX rc=1\n")
    assert p.wait(30) == 0 and ln.invocations() == 1


def gate_of(**cfg):
    """rc and message of lane_gate under CFG, in a bare shell with the library sourced."""
    sets = "; ".join(f"{k}={v}" for k, v in cfg.items())
    out = subprocess.run([BASH, "-c", f'. "{LIB}"; {sets}; lane_gate; echo "$? $LANE_MSG"'],
                         capture_output=True, text=True, check=True).stdout.strip()
    rc, _, msg = out.partition(" ")
    return int(rc), msg


def finished_lane(lane, **overrides):
    """A real lane run to its terminal: the status file the library itself wrote, ending in UNLOCKED."""
    ln = lane(**overrides); ln.arm()
    rc = ln.run()
    assert ln.words()[-1] == "UNLOCKED", ln.lines()
    return ln, rc


SUCCESS = "'^TL DONE '"


def test_real_done_then_unlocked_opens_the_successor_gate(lane):
    ln, rc = finished_lane(lane)
    assert rc == 0 and ln.words()[-2] == "DONE"
    assert gate_of(LANE_GATES=f"'{ln.status} ^TL DONE '")[0] == 0


def test_real_done_then_unlocked_lets_a_waiting_successor_run(lane, tmp_path):
    pred, _ = finished_lane(lane)
    succ_root = tmp_path / "succ"; succ_root.mkdir()
    succ = Lane(succ_root, LANE_NAME="t2", LANE_GATES=f"'{pred.status} ^TL DONE '")
    succ.arm()
    assert succ.run() == 0 and "DONE" in succ.terminal() and succ.invocations() == 1


def test_real_abort_then_unlocked_stops_the_successor(lane):
    ln, rc = finished_lane(lane, **{"export STUB_RC": "3"})
    assert rc == 3 and ln.words()[-2] == "ABORT"
    assert gate_of(LANE_GATES=f"'{ln.status} ^TL DONE '")[0] == 2


def test_real_wall_ceiling_pause_then_unlocked_is_waited_on_never_admitted(lane):
    ln, rc = finished_lane(lane, DELAY="5", LANE_MAX_SECONDS="1")
    assert rc == 1 and ln.words()[-2] == "PAUSED"
    g, msg = gate_of(LANE_GATES=f"'{ln.status} ^TL (DONE|PAUSED) '")
    assert g == 1 and "paused" in msg
    assert gate_of(LANE_GATES=f"'{ln.status} ^TL DONE '")[0] == 1


def test_new_start_after_an_earlier_done_hides_the_old_done(lane):
    ln, _ = finished_lane(lane)
    with open(ln.status, "a") as f:
        f.write("TL START t1 2026-11-09T23:00:00Z pid=1 host=x\n")
    g, msg = gate_of(LANE_GATES=f"'{ln.status} ^TL DONE '")
    assert g == 1 and "START" in msg


def test_failure_that_quotes_done_is_a_failure(lane, tmp_path):
    st = tmp_path / "pred.status"
    st.write_text("TL ABORT t0 2026-11-09T23:00:00Z rc=4 reason=no TL DONE shards\n"
                  "TL UNLOCKED t0 2026-11-09T23:00:01Z /lock\n")
    assert gate_of(LANE_GATES=f"'{st} ^TL DONE '")[0] == 2
    assert gate_of(LANE_GATES=f"'{st} DONE'")[0] == 0  # an unanchored ERE is the caller's error, as documented


def _released(tmp_path, name, status_text):
    q = tmp_path / "queue"; q.mkdir(exist_ok=True)
    (q / f"{name}.RELEASE").write_text("tok\n")
    if status_text is not None:
        (q / f"{name}.status").write_text(status_text)
    return q


def test_yield_releases_a_real_done_then_unlocked_run(lane, tmp_path):
    ln, _ = finished_lane(lane)
    q = _released(tmp_path, "other", ln.status.read_text())
    assert gate_of(LANE_YIELD_DIR=str(q))[0] == 0


def test_yield_releases_a_real_paused_then_unlocked_run(lane, tmp_path):
    ln, _ = finished_lane(lane, DELAY="5", LANE_MAX_SECONDS="1")
    q = _released(tmp_path, "other", ln.status.read_text())
    assert gate_of(LANE_YIELD_DIR=str(q))[0] == 0


def test_yield_waits_for_a_new_attempt_after_an_old_done(lane, tmp_path):
    ln, _ = finished_lane(lane)
    q = _released(tmp_path, "other", ln.status.read_text() + "TL START t1 2026-11-09T23:00:00Z note=DONE\n")
    g, msg = gate_of(LANE_YIELD_DIR=str(q))
    assert g == 1 and "other.RELEASE" in msg


def test_held_lock_waits_then_takes_it_with_an_owner_line(lane):
    ln = lane(DELAY="0.5"); ln.arm(); ln.fake_lock()
    p = ln.start()
    wait_for(lambda: "WAIT" in ln.words())
    time.sleep(1.0)
    assert ln.invocations() == 0
    ln.free_fake_lock()
    wait_for(lambda: ln.invocations() == 1)
    owner = (ln.lock / "owner").read_text().split()
    assert owner[0] == str(p.pid) and owner[1] == "t1"
    assert p.wait(30) == 0 and not ln.lock.exists()


def test_wait_ceiling_aborts_and_leaves_the_other_lock(lane):
    ln = lane(LANE_WAIT_CEILING="2"); ln.arm(); ln.fake_lock()
    assert ln.run() == 5
    assert "ceiling" in ln.terminal() and ln.invocations() == 0
    assert (ln.lock / "owner").read_text().startswith("1 other-lane")


def test_lock_is_released_only_by_its_owner(lane):
    ln = lane(SHARDS="20", DELAY="0.2"); ln.arm()
    p = ln.start()
    wait_for(lambda: ln.invocations() == 1)
    (ln.lock / "owner").write_text("1 someone-else\n")
    assert p.wait(30) == 0
    assert ln.lock.exists() and "WARNING" in ln.words()


# ---------------------------------------------------------------- supervision

@pytest.mark.skipif(sys.platform != "darwin", reason="macOS power assertions")
@pytest.mark.parametrize("hold", [False, True])
def test_mac_producer_owns_sleep_assertions_until_completion_or_hold(lane, hold):
    ln = lane(SHARDS="30", DELAY="0.1"); ln.arm()
    p = ln.start()
    try:
        wait_for(lambda: ln.invocations() == 1)
        pgid = ln.pgid()
        members = subprocess.run(["pgrep", "-g", str(pgid)], check=True,
                                 capture_output=True, text=True).stdout.split()
        assertions = subprocess.run(["pmset", "-g", "assertions"], check=True,
                                    capture_output=True, text=True).stdout
        owned = [line for line in assertions.splitlines()
                 if any(f"pid {pid}(" in line for pid in members)]
        assert any("PreventUserIdleSystemSleep" in line for line in owned), owned
        assert any("PreventSystemSleep" in line for line in owned), owned
        if hold:
            ln.hold.touch()
        assert p.wait(30) == (1 if hold else 0)
        assert group_members(pgid) == 0
        assert ("PAUSED" if hold else "DONE") in ln.terminal()
        assert not ln.lock.exists()
    finally:
        if p.poll() is None:
            p.terminate()
            p.wait(30)

@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGINT, signal.SIGHUP])
def test_signal_to_the_supervisor_stops_the_group_then_pauses_then_unlocks(lane, sig):
    ln = lane(SHARDS="200", DELAY="0.2"); ln.arm()
    p = ln.start()
    wait_for(lambda: ln.shards() >= 2)
    pgid = ln.pgid()
    child = int((ln.w / "PRODUCER_INVOKED.child").read_text())
    p.send_signal(sig)
    assert p.wait(30) == 1
    assert group_members(pgid) == 0 and not pid_alive(child)
    t = ln.terminal()
    assert "PAUSED" in t and "signal" in t, t
    w = ln.words()
    assert w.index("STUBEXIT") < w.index("PAUSED") < w.index("UNLOCKED") and not ln.lock.exists()
    assert ln.shards() >= 2


def test_sigterm_to_the_leg_aborts_cleans_the_group_and_unlocks(lane):
    ln = lane(SHARDS="200", DELAY="0.2"); ln.arm()
    p = ln.start()
    wait_for(lambda: ln.shards() >= 1)
    pgid = ln.pgid()
    child = int((ln.w / "PRODUCER_INVOKED.child").read_text())
    os.kill(pgid, signal.SIGTERM)
    assert p.wait(30) != 0
    t = ln.terminal()
    assert "ABORT" in t and "producer rc=" in t, t
    assert not pid_alive(child) and group_members(pgid) == 0 and not ln.lock.exists()


def test_wall_ceiling_pauses_with_the_group_gone(lane):
    ln = lane(SHARDS="200", DELAY="0.2", LANE_MAX_SECONDS="2"); ln.arm()
    assert ln.run() == 1
    t = ln.terminal()
    assert "PAUSED" in t and "timeout" in t, t
    w = ln.words()
    assert w.index("STUBEXIT") < w.index("PAUSED") < w.index("UNLOCKED")
    assert group_members(ln.pgid()) == 0 and not ln.lock.exists()
    assert 0 < ln.shards() < 200


def test_hold_while_running_pauses(lane):
    ln = lane(SHARDS="200", DELAY="0.2"); ln.arm()
    p = ln.start()
    wait_for(lambda: ln.shards() >= 1)
    ln.hold.touch()
    assert p.wait(30) == 1
    assert "PAUSED" in ln.terminal() and "HOLD" in ln.terminal()
    assert group_members(ln.pgid()) == 0 and not ln.lock.exists()
    w = ln.words()
    assert w.index("STUBEXIT") < w.index("PAUSED") < w.index("UNLOCKED")


def disk_probe(lane, tmp_path, mode, **overrides):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    state = tmp_path / "disk-mode"
    state.write_text(mode)
    df = bin_dir / "df"
    df.write_text("#!/bin/bash\n"
                  f'mode=$(cat "{state}")\n'
                  'case "$mode" in\n'
                  ' failed) exit 1;;\n'
                  ' empty) exit 0;;\n'
                  ' malformed) free=unknown;;\n'
                  ' low) free=0;;\n'
                  ' *) free=10485760;;\n'
                  'esac\n'
                  'printf "Filesystem 1024-blocks Used Available Capacity Mounted on\\n"\n'
                  'printf "disk 20971520 10485760 %s 50%% /\\n" "$free"\n')
    df.chmod(0o755)
    ln = lane(PATH=f"'{bin_dir}:{os.environ['PATH']}'", LANE_DISK_DIR=str(tmp_path),
              LANE_MIN_FREE_GIB="1", **overrides)
    ln.arm()
    return ln, state


@pytest.mark.parametrize("mode", ["failed", "empty", "malformed", "low"])
def test_disk_guard_refuses_before_producer(lane, tmp_path, mode):
    ln, _ = disk_probe(lane, tmp_path, mode)
    assert ln.run() == 1
    assert ln.invocations() == 0 and ln.shards() == 0
    assert "PAUSED" in ln.terminal() and "disk free" in ln.terminal()
    assert ln.words().index("PAUSED") < ln.words().index("UNLOCKED")
    assert not ln.lock.exists()


def test_disk_guard_rejects_missing_real_path(lane, tmp_path):
    ln = lane(LANE_DISK_DIR=str(tmp_path / "missing"), LANE_MIN_FREE_GIB="1")
    ln.arm()
    assert ln.run() == 1 and ln.invocations() == 0
    assert "disk free unavailable" in ln.terminal() and not ln.lock.exists()


def test_disk_guard_healthy_reading_completes(lane, tmp_path):
    ln, _ = disk_probe(lane, tmp_path, "healthy")
    assert ln.run() == 0 and ln.shards() == 4
    assert "DONE" in ln.terminal() and not ln.lock.exists()


@pytest.mark.parametrize("mode", ["failed", "empty", "malformed", "low"])
def test_disk_guard_runtime_failure_stops_group_before_unlock(lane, tmp_path, mode):
    ln, state = disk_probe(lane, tmp_path, "healthy", SHARDS="200", DELAY="0.2")
    p = ln.start()
    try:
        wait_for(lambda: ln.shards() >= 2)
        pgid = ln.pgid()
        child = int((ln.w / "PRODUCER_INVOKED.child").read_text())
        state.write_text(mode)
        assert p.wait(30) == 1
        assert group_members(pgid) == 0 and not pid_alive(child)
        assert "PAUSED" in ln.terminal() and "disk free" in ln.terminal()
        words = ln.words()
        assert words.index("STUBEXIT") < words.index("PAUSED") < words.index("UNLOCKED")
        assert not ln.lock.exists() and 2 <= ln.shards() < 200
    finally:
        if p.poll() is None:
            p.terminate()
            p.wait(30)


# ---------------------------------------------------------------- deletion and counting

DELETER = textwrap.dedent("""\
    set -u
    . "$LANE_LIB"
    LANE_NAME=t1; LANE_STATUS=$1/del.status; LANE_HOLDS="$1/HOLD"
    lane_hold_check_before_delete "$1/store"; rc=$?
    [ "$rc" = 0 ] && rm -rf "$1/store"
    exit "$rc"
""")


@pytest.mark.parametrize("held", [True, False])
def test_hold_before_delete(tmp_path, held):
    (tmp_path / "store").mkdir(); (tmp_path / "store" / "a").write_text("x")
    if held:
        (tmp_path / "HOLD").touch()
    rc = subprocess.run([BASH, "-c", DELETER, "del", str(tmp_path)], env={**os.environ, "LANE_LIB": str(LIB)}).returncode
    if held:
        assert rc == 3 and (tmp_path / "store" / "a").exists()
        assert "DELETE_HELD" in (tmp_path / "del.status").read_text()
    else:
        assert rc == 0 and not (tmp_path / "store").exists()


def test_count_files_uses_find_past_arg_max(tmp_path):
    d = tmp_path / "shards"; d.mkdir()
    # 10,000 names of ~240 bytes exceed ARG_MAX (1 MiB on macOS, 2 MiB on Linux) as one ls argument list
    for i in range(10000):
        (d / f"cluster-{i:06d}-{'x' * 220}.json").touch()
    (d / "other.txt").touch()
    out = subprocess.run([BASH, "-c", f'. "{LIB}"; lane_count_files "$1" "cluster-*.json"; lane_count_files "$1/none" "*"',
                          "c", str(d)], capture_output=True, text=True, check=True).stdout.split()
    assert out == ["10000", "0"]


def test_identity_refuses_a_missing_file_or_a_repeated_basename(tmp_path):
    (tmp_path / "a").mkdir(); (tmp_path / "b").mkdir()
    (tmp_path / "a" / "x.sh").write_text("1"); (tmp_path / "b" / "x.sh").write_text("2")
    r = subprocess.run([BASH, "-c", f'. "{LIB}"; lane_identity "$1/a/x.sh" "$1/b/x.sh"', "i", str(tmp_path)],
                       capture_output=True, text=True)
    assert r.returncode != 0 and r.stdout == ""
    r = subprocess.run([BASH, "-c", f'. "{LIB}"; lane_identity "$1/a/x.sh" "$1/missing"', "i", str(tmp_path)],
                       capture_output=True, text=True)
    assert r.returncode != 0 and r.stdout == ""


# ---------------------------------------------------------------- seed registration

def _window(name, purpose, seed0, clusters):
    import json
    return json.dumps({"name": name, "purpose": purpose, "seed0": seed0, "clusters": clusters,
                       "span": [seed0, seed0 + clusters], "created_at": "2026-11-09T00:00:00Z",
                       "host": "test", "git_head": None, "note": ""})


class SeedTree(os.PathLike):
    def __init__(self, path: Path, git):
        self.path, self.git = path, git

    def __fspath__(self):
        return str(self.path)

    def __truediv__(self, other):
        return self.path / other


@pytest.fixture
def seed_tree(tmp_path):
    t = tmp_path / "tree"
    (t / "server" / "scripts").mkdir(parents=True)
    (t / "server" / "shengji").mkdir()
    (t / "server" / "runs" / "seed_windows.d").mkdir(parents=True)
    shutil.copy(SERVER / "scripts" / "seed_windows.py", t / "server" / "scripts")
    shutil.copy(SERVER / "shengji" / "seeds.py", t / "server" / "shengji")
    (t / "server" / "shengji" / "__init__.py").write_text("")
    (t / "server" / "runs" / "seed_windows.json").write_text('{"schema": "shengji-seed-windows-v1", "windows": []}\n')
    d = t / "server" / "runs" / "seed_windows.d"
    (d / "corpus-a.json").write_text(_window("corpus-a", "trajectory", 1000, 500))
    (d / "corpus-b.json").write_text(_window("corpus-b", "trajectory", 1500, 500))
    (d / "screen-c.json").write_text(_window("screen-c", "screen", 5000, 100))

    def git(*a):
        subprocess.run(["git", "-c", "commit.gpgsign=false", "-C", str(t), *a], check=True, capture_output=True,
                       env={**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})
    git("init", "-q")
    git("add", "-A")
    git("commit", "-q", "-m", "registry")
    git("update-ref", "refs/remotes/origin/main", "HEAD")
    return SeedTree(t, git)


def seeds(tree, seed0, clusters, **env):
    script = '. "$LANE_LIB"; lane_require_registered_seeds "$1" "$2"; rc=$?; echo "$LANE_MSG"; exit $rc'
    e = {**os.environ, "LANE_LIB": str(LIB), "LANE_SEED_TREE": os.fspath(tree), "LANE_PY": PY, **env}
    e["SHENGJI_SEED_WINDOWS"] = "/nonexistent/registry.json"
    r = subprocess.run([BASH, "-c", script, "s", str(seed0), str(clusters)], env=e, capture_output=True, text=True)
    return r.returncode, r.stdout.strip()


def test_seed_block_inside_one_reservation_passes(seed_tree):
    rc, msg = seeds(seed_tree, 1100, 200)
    assert rc == 0 and "corpus-a" in msg, msg
    rc, msg = seeds(seed_tree, 1000, 500, LANE_SEED_PURPOSE="trajectory")
    assert rc == 0, msg


@pytest.mark.parametrize("seed0,clusters,why", [
    (3000, 100, "in no registered window"),          # disjoint: check exits 0, which is NOT registered
    (1400, 200, "overlaps 2 registered windows"),    # straddles two reservations
    (900, 200, "only partly inside"),                # check says "shares 100 deal seed(s)": overlap, not reserved
    (1450, 10, None),                                # control for the straddle case: inside corpus-a only
])
def test_seed_block_not_inside_one_reservation_refuses(seed_tree, seed0, clusters, why):
    rc, msg = seeds(seed_tree, seed0, clusters)
    if why is None:
        assert rc == 0, msg
    else:
        assert rc == 6 and why in msg, msg


def test_seed_purpose_mismatch_refuses(seed_tree):
    rc, msg = seeds(seed_tree, 5000, 50, LANE_SEED_PURPOSE="trajectory")
    assert rc == 6 and "screen window" in msg, msg


def test_seed_uncommitted_reservation_refuses(seed_tree):
    (seed_tree / "server" / "runs" / "seed_windows.d" / "local.json").write_text(_window("local", "trajectory", 9000, 10))
    rc, msg = seeds(seed_tree, 9000, 10)
    assert rc == 6 and "differs from its HEAD" in msg, msg


def test_seed_head_not_on_main_refuses(seed_tree):
    (seed_tree / "server" / "runs" / "seed_windows.d" / "branch.json").write_text(_window("branch", "trajectory", 9000, 10))
    seed_tree.git("add", "-A")
    seed_tree.git("commit", "-q", "-m", "unmerged reservation")
    rc, msg = seeds(seed_tree, 9000, 10)
    assert rc == 6 and "is not on origin/main" in msg, msg
    seed_tree.git("update-ref", "refs/remotes/origin/main", "HEAD")
    assert seeds(seed_tree, 9000, 10)[0] == 0
