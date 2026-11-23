"""Exercise post-training admission and terminal handling without touching the fleet."""
import hashlib
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

import pytest


PACKET = Path(__file__).resolve().parent
SERVER = PACKET.parents[1] / "server"
HEAD = "e" * 40
JOINT_DONE = "LANE DONE sz2-joint-v1 t joint arms complete rc=0"
JOINT_REFUSED = "LANE DONE sz2-joint-v1 t FAIL-OFFLINE at buffer 400 rc=0"
PRODUCER = """
import hashlib
import os
from pathlib import Path
import sys

fleet = Path.home() / "fleet"
arm = sys.argv[1]
config = Path.home() / ".config/darkbloom/provider.toml"
assert sys.argv[2:] == ["--provider-sha256", hashlib.sha256(config.read_bytes()).hexdigest()]
assert (fleet / ".claude-host.lock/owner").read_text().split()[1] == f"sz2-post-{arm}-v1"
with (fleet / "calls").open("a") as calls:
    print(arm, file=calls)
sys.exit(int(os.environ.get("FIXTURE_EXIT", "0")))
"""


@pytest.fixture
def fleet(tmp_path):
    home = tmp_path / "host"
    fleet = home / "fleet"
    config = home / ".config/darkbloom/provider.toml"
    config.parent.mkdir(parents=True)
    config.write_text('model = "fixture"\n')
    tree = home / "Projects/shengji-wt" / f"codex-sz2-post-{HEAD[:8]}"
    scripts = tree / "server/scripts"
    (scripts / "lanes").mkdir(parents=True)
    shutil.copyfile(SERVER / "scripts/lanes/lane_lib.sh", scripts / "lanes/lane_lib.sh")
    for name in ("sz2_export_arm", "sz2_export_parity", "sz2_gpu_smoke", "sz2_cache_arm", "sz2_polish_arm", "sz2_joint_segment"):
        (scripts / f"{name}.py").write_text("")
    (scripts / "sz2_post_arm.py").write_text(PRODUCER)
    train = tree / "server/shengji/train"
    train.mkdir(parents=True)
    (train / "unified_readout.py").write_text("")

    bins = home / "bin"
    bins.mkdir()
    commands = {
        "hostname": "echo Jerrys-Mac-Studio.local",
        "git": f'[ "$1" = -C ] && [ "$2" = "{tree}" ] || exit 1\n'
               f'case "$3" in rev-parse) echo "{HEAD}";; status) exit 0;; *) exit 1;; esac',
        "df": 'printf "Filesystem 1024-blocks Used Available Capacity Mounted\nfixture 700000000 200000000 500000000 30%% /\n"',
    }
    for name, command in commands.items():
        path = bins / name
        path.write_text("#!/bin/bash\n" + command + "\n")
        path.chmod(0o755)

    source = (PACKET / "run_post.sh").read_text()
    for relpath in ("codex-sz2-small-capacity-v1/small_capacity.py",):
        path = fleet / relpath
        path.parent.mkdir(parents=True)
        path.write_text(f"# fixture {path.name}\n")
        fixture_pin = hashlib.sha256(path.read_bytes()).hexdigest()
        source, count = re.subn(r"[0-9a-f]{64}(  [^\n\"]+/" + re.escape(path.name) + r")",
                                lambda match: fixture_pin + match[1], source)
        assert count == 1
    release_pin = re.search(r'\[ "\$\{joint_id%% \*\}" = ([0-9a-f]{64}) \]', source)
    assert release_pin
    joint = fleet / "codex-sz2-joint-v1"
    (joint / "capture").mkdir(parents=True)
    (joint / "launcher.RELEASE").write_text(release_pin[1] + "\n")
    joint_status = joint / "capture/launcher.status"
    joint_status.write_text(JOINT_DONE + "\nLANE UNLOCKED sz2-joint-v1 t /fixture/lock\n")

    # Exercise the launcher with only the location, host pins and polling interval adapted.
    source = source.replace("/Users/jeryyu/Projects/shengji/server/.venv/bin/python", sys.executable)
    source = source.replace("/Users/jeryyu", str(home))
    source = source.replace("LANE_POLL=1", "LANE_POLL=1\nLANE_MON_POLL=0.05")
    for arm in ("S", "M"):
        packet = fleet / f"codex-sz2-post-{arm}-v1"
        packet.mkdir()
        (packet / "source").write_text(f"{arm} {HEAD}\n")
        (packet / "run_post.sh").write_text(source)
        shutil.copyfile(PACKET / "dispatch_post.sh", packet / "dispatch_post.sh")

    def launch(arm, *flags, worker_rc=0):
        packet = fleet / f"codex-sz2-post-{arm}-v1"
        env = {"HOME": str(home), "PATH": os.pathsep.join((str(bins), os.defpath)), "FIXTURE_EXIT": str(worker_rc)}
        return subprocess.run(["bash", str(packet / "run_post.sh"), arm, *flags],
                              env=env, capture_output=True, text=True, timeout=20)

    def release(arm, *, wrong=False):
        result = launch(arm, "--identity")
        assert result.returncode == 0 and re.fullmatch(r"[a-f0-9]{64}\n", result.stdout), result
        packet = fleet / f"codex-sz2-post-{arm}-v1"
        (packet / "launcher.RELEASE").write_text("0" * 64 + "\n" if wrong else result.stdout)
        return packet / "capture"

    return fleet, joint_status, launch, release


def test_post_arm_requires_joint_success(fleet):
    root, joint_status, launch, release = fleet
    capture = release("S")
    joint_status.write_text(JOINT_REFUSED + "\nLANE UNLOCKED sz2-joint-v1 t /fixture/lock\n")
    assert launch("S", "--preflight").returncode != 0
    assert launch("S").returncode == 6
    assert not capture.exists()
    assert not (root / "calls").exists()
    assert not (root / ".claude-host.lock").exists()


def test_medium_post_arm_requires_successful_small_post_arm(fleet):
    root, _, launch, release = fleet
    small = release("S")
    medium = release("M")
    assert launch("M", "--preflight").returncode != 0
    assert launch("M").returncode == 6
    assert not medium.exists()
    assert not (root / "calls").exists()

    for arm, capture in (("S", small), ("M", medium)):
        if arm == "M":
            # A finished S from another source revision cannot admit this M.
            small_source = small.parent / "source"
            expected_source = small_source.read_text()
            small_source.write_text(f"S {'0' * 40}\n")
            assert launch("M", "--preflight").returncode != 0
            assert launch("M").returncode == 6
            assert not medium.exists()
            small_source.write_text(expected_source)
            small_cache = root / "codex-sz2-cache-v1/S/identity/train-0000.npz"
            small_cache.parent.mkdir(parents=True)
            small_cache.touch()
            assert launch("M", "--preflight").returncode != 0
            assert launch("M").returncode == 6
            assert not medium.exists()
            small_cache.rename(root / "offloaded-cache.npz")
        assert launch(arm, "--preflight").returncode == 0
        result = launch(arm)
        status = (capture / "launcher.status").read_text().splitlines()
        assert result.returncode == 0, result.stderr
        assert f"LANE DONE sz2-post-{arm}-v1 " in status[-2]
        assert status[-2].endswith("selected package parity verified rc=0")
        assert status[-1].startswith(f"LANE UNLOCKED sz2-post-{arm}-v1 ")
        assert not (root / ".claude-host.lock").exists()
    assert (root / "calls").read_text().splitlines() == ["S", "M"]


def test_wrong_post_release_never_starts_worker(fleet):
    root, _, launch, release = fleet
    capture = release("S", wrong=True)
    assert launch("S").returncode == 6
    assert not capture.exists()
    assert not (root / "calls").exists()
    assert not (root / ".claude-host.lock").exists()


def test_nonzero_post_worker_aborts_and_keeps_capture(fleet):
    root, _, launch, release = fleet
    capture = release("S")
    assert launch("S", worker_rc=7).returncode == 7
    status = (capture / "launcher.status").read_text().splitlines()
    assert status[-2].startswith("LANE ABORT sz2-post-S-v1 ")
    assert status[-2].endswith("rc=7 reason=post-training worker failed")
    assert status[-1].startswith("LANE UNLOCKED sz2-post-S-v1 ")
    assert (root / "calls").read_text().splitlines() == ["S"]
    assert not (root / ".claude-host.lock").exists()


def test_provider_drift_after_release_refuses_preflight_and_worker(fleet):
    root, _, launch, release = fleet
    preflight = launch("S", "--preflight")
    assert preflight.returncode == 0
    capture = release("S")
    release_file = capture.parent / "launcher.RELEASE"
    released = release_file.read_text()
    assert released == preflight.stdout
    assert launch("S", "--preflight").returncode == 0

    config = root.parent / ".config/darkbloom/provider.toml"
    config.write_text('model = "drifted"\n')
    current = launch("S", "--identity")
    assert current.returncode == 0 and current.stdout != released
    assert launch("S", "--preflight").returncode == 6
    assert launch("S").returncode == 6
    assert not capture.exists()
    assert not (root / "calls").exists()
    assert not (root / ".claude-host.lock").exists()
    assert release_file.read_text() == released
    assert config.read_text() == 'model = "drifted"\n'
