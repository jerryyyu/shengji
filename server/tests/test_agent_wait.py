"""agent_wait.sh: a blocking waiter reports only changes after its start, then exits."""
import os
import subprocess
import threading
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "agent_wait.sh"


def fake_bus(tmp_path: Path, log: Path) -> Path:
    bus = tmp_path / "agent-bus"
    bus.write_text(f'#!/bin/sh\n[ "$1" = log ] && cat "{log}"\n')
    bus.chmod(0o755)
    return bus


def run(tmp_path, args, env_extra, after=None, delay=0.0):
    env = {**os.environ, **env_extra, "AGENT_WAIT_PROJECT": str(tmp_path)}
    proc = subprocess.Popen(["bash", str(SCRIPT), "--interval", "5", *args],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
    if after is not None:
        threading.Timer(delay, after).start()
    out, err = proc.communicate(timeout=60)
    return proc.returncode, out, err


@pytest.fixture
def bus(tmp_path):
    log = tmp_path / "bus.log"
    log.write_text("NON_AUTHORITATIVE 10:00:00 claude->codex fyi old\n")
    return log, fake_bus(tmp_path, log)


def test_a_new_peer_line_on_the_bus_is_an_event(tmp_path, bus):
    log, exe = bus
    def append():
        with log.open("a") as f:
            f.write("NON_AUTHORITATIVE 10:01:00 claude->codex verdict new\n")
    rc, out, _ = run(tmp_path, ["--timeout", "30"], {"AGENT_BUS": str(exe)}, append, 2)
    assert rc == 0 and out.startswith("EVENT bus ") and "verdict new" in out


def test_lines_to_another_agent_and_preexisting_lines_are_not_events(tmp_path, bus):
    log, exe = bus
    def append():
        with log.open("a") as f:
            f.write("NON_AUTHORITATIVE 10:01:00 codex->claude ask-ready mine\n")
    rc, out, _ = run(tmp_path, ["--timeout", "12"], {"AGENT_BUS": str(exe)}, append, 2)
    assert rc == 2 and out.strip().startswith("TIMEOUT")


def test_a_file_source_fires_only_on_a_new_matching_line(tmp_path, bus):
    _, exe = bus
    status = tmp_path / "RT4.status"
    status.write_text("RT4 START x\n")
    def append():
        with status.open("a") as f:
            f.write("RT4 SEGMENT ignored\n")
            f.flush()
            time.sleep(6)
            f.write("RT4 TRAINED device=mps\n")
    t0 = time.time()
    rc, out, _ = run(tmp_path, ["--timeout", "40", "--file", f"{status}:TRAINED|ABORT"],
                     {"AGENT_BUS": str(exe)}, append, 1)
    assert rc == 0 and "EVENT file:" in out and "RT4 TRAINED device=mps" in out
    assert time.time() - t0 >= 6       # the SEGMENT line alone did not fire


def test_bad_arguments_refuse(tmp_path, bus):
    _, exe = bus
    for args in (["--interval", "1"], ["--timeout", "x"], ["--nope"]):
        p = subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True,
                           env={**os.environ, "AGENT_BUS": str(exe), "AGENT_WAIT_PROJECT": str(tmp_path)})
        assert p.returncode == 3
