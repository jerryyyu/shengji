"""Exercise SZ2-A admission and terminal handling with a synthetic capture."""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

import pytest

from sz2_reader_fixture import ARM, DEALS, REPO, SEED0, fixture_packet, make_row, sha, write_json


HERE = Path(__file__).resolve().parent
SEED_RESERVATION = {
    "name": "sz2-dev-2665000000", "purpose": "screen", "seed0": SEED0, "clusters": 2200,
    "span": [SEED0, SEED0 + 2200], "created_at": "2026-11-24T00:00:00Z",
    "host": "fixture", "git_head": None, "note": "",
}
PRODUCER = """
import argparse
import os
from pathlib import Path
import shutil
import sys
import time

from sz2_a_capture import destination, event, reserve, seal
from sz2_duel_decision import _pinned_json

parser = argparse.ArgumentParser()
parser.add_argument("--recipe", type=Path, required=True)
parser.add_argument("--recipe-sha256", required=True)
parser.add_argument("--workers", type=int, required=True)
args = parser.parse_args()
lane = args.recipe.parent
assert args.workers == 2
owner = lane.parent / ".claude-host.lock/owner"
assert owner.read_text().split()[:2] == [str(os.getppid()), "sz2-duel-a-v1"]
recipe = _pinned_json(args.recipe, args.recipe_sha256, "recipe")
root, status = destination(recipe, lane)
reserve(recipe, args.recipe_sha256, lane, os.getppid(), args.workers)
with status.open("a") as out:
    for kind, detail in (("LOCKED", "after 0s"), ("NAMES", "ok"), ("PRODUCER", "fixture")):
        out.write(event(kind, detail))
mode = (lane / "fixture-mode").read_text().strip()
if mode in ("fail", "hold"):
    (root / "duel.jsonl").write_bytes(b"partial fixture\\n")
    (lane / "fixture-running").touch()
    if mode == "hold":
        time.sleep(30)
    sys.exit(7)
shutil.copyfile(lane / "fixture.jsonl", root / "duel.jsonl")
for name in ("duel.jsonl.resume.json", "duel.time", "run.log"):
    (root / name).write_text("fixture\\n")
seal(recipe, args.recipe_sha256, lane, 0)
if mode == "blocked-release":
    owner.with_name("fixture-retained").write_text("held\\n")
"""


def git(tree, *args):
    return subprocess.check_output(["git", "-C", str(tree), *args], text=True).strip()


def commit_fixture(tree, *paths):
    git(tree, "init", "-q")
    git(tree, "add", *paths)
    git(tree, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
        "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null", "commit", "-qm", "Fixture source")


def events(path):
    return [line.split()[1] for line in path.read_text().splitlines()]


@pytest.fixture
def lane_fixture(tmp_path):
    home = tmp_path / "host"
    fleet = home / "fleet"
    lane = fleet / "codex-sz2-duel-a-v1"
    packet = fixture_packet(lane)
    packet.root = lane / "out" / ARM
    packet.status = lane / f"{ARM}.status"
    packet.arm.update(out_root=str(packet.root), status=str(packet.status))
    packet.recipe.update(reader=packet.reader.__file__, round_plan="r2")

    seed_tree = home / "current-main"
    worktrees = home / "worktrees"
    tree = worktrees / "setup"
    scripts = tree / "server/scripts"
    shutil.copytree(REPO / "server/scripts/lanes", scripts / "lanes")
    validity = scripts / "expert_labels/validity.py"
    validity.parent.mkdir()
    shutil.copyfile(REPO / "server/scripts/expert_labels/validity.py", validity)
    for source in (REPO / "server/scripts").glob("sz2_*.py"):
        shutil.copyfile(source, scripts / source.name)
    (scripts / "sz2_a_dispatch.py").write_text(PRODUCER)
    predeclare = tree / "dev/s156/SZ2_A_DECISION.md"
    predeclare.parent.mkdir(parents=True)
    shutil.copyfile(HERE / predeclare.name, predeclare)
    source = (HERE / "run_duel_a.sh").read_text()
    # Adapt only the fixed host paths and polling latency to exercise the supervised path locally.
    source = source.replace("/Users/jeryyu/Projects/shengji/server/.venv/bin/python", sys.executable)
    source = source.replace("/Users/jeryyu/Projects/shengji-wt", str(worktrees))
    source = source.replace("/Users/jeryyu/Projects/shengji", str(seed_tree))
    source = source.replace("/Users/jeryyu/fleet", str(fleet))
    source = source.replace("LANE_POLL=1\n", "LANE_POLL=1\nLANE_MON_POLL=0.05\n")
    run = lane / "run_duel_a.sh"
    run.write_text(source)
    shutil.copyfile(run, predeclare.parent / run.name)
    dispatch = "dispatch_duel_a.sh"
    shutil.copyfile(HERE / dispatch, lane / dispatch)
    shutil.copyfile(lane / dispatch, predeclare.parent / dispatch)
    commit_fixture(tree, "server", "dev")
    head = git(tree, "rev-parse", "HEAD")
    tree = tree.rename(worktrees / f"codex-sz2-duel-a-{head[:8]}")
    packet.recipe.update(tree=str(tree), tree_head=head)

    fixture_rows = lane / "fixture.jsonl"
    with fixture_rows.open("w") as out:
        for index in range(DEALS):
            for mirror in (0, 1):
                out.write(json.dumps(make_row(packet.reader, index, mirror)) + "\n")

    for arm in ("S", "M"):
        status = fleet / f"codex-sz2-post-{arm}-v1/capture/launcher.status"
        status.parent.mkdir(parents=True)
        status.write_text(f"LANE DONE sz2-post-{arm}-v1 2026-11-24T06:00:00Z selected package parity verified rc=0\n"
                          f"LANE UNLOCKED sz2-post-{arm}-v1 2026-11-24T06:00:00Z {fleet}/.claude-host.lock\n")
    d1 = lane / "d1.json"
    recipe_sha = packet.write_recipe()
    write_json(d1, {
        "schema": "sz2-a-exposure-r1", "verdict": "CLEAR", "recipe_sha256": recipe_sha,
        "arm": ARM, "seed0": SEED0, "deals": DEALS, "unresolved": 0, "overlaps": 0,
        **{f"{kind}_sha256": {tag: packet.arm[f"{tag}_{kind}_sha256"] for tag in ("ex", "def")}
           for kind in ("package", "belief")},
    })
    (lane / "packet.pins").write_text(f"{head} {recipe_sha} {sha(d1)} 2 1 20\n")
    (lane / "fixture-mode").write_text("success\n")

    seed_server = seed_tree / "server"
    for relative in ("scripts/seed_windows.py", "shengji/seeds.py"):
        dest = seed_server / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / "server" / relative, dest)
    (seed_server / "shengji/__init__.py").touch()
    fragment_dir = seed_server / "runs/seed_windows.d"
    fragment_dir.mkdir(parents=True)
    write_json(fragment_dir.parent / "seed_windows.json", {"schema": "shengji-seed-windows-v1", "windows": []})
    write_json(fragment_dir / f"{SEED_RESERVATION['name']}.json", SEED_RESERVATION)
    commit_fixture(seed_tree, "server")
    git(seed_tree, "update-ref", "refs/remotes/origin/main", "HEAD")

    bins = home / "bin"
    bins.mkdir()
    hostname = bins / "hostname"
    hostname.write_text("#!/bin/bash\necho Jerrys-Mac-Studio.local\n")
    hostname.chmod(0o755)
    run = lane / "run_duel_a.sh"
    cmd = ["bash", str(run)]
    env = {"HOME": str(home), "PATH": os.pathsep.join((str(bins), os.defpath))}
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    def launch(*args):
        return subprocess.run([*cmd, *args], env=env, capture_output=True, text=True, timeout=25)

    identity = launch("--identity")
    assert identity.returncode == 0 and re.fullmatch(r"[0-9a-f]{64}\n", identity.stdout), identity
    release = lane / "launcher.RELEASE"
    release.write_text(identity.stdout)
    return packet, fleet, launch, identity.stdout.strip(), cmd, env


def test_supervisor_seals_and_unlocks_before_readout(lane_fixture):
    packet, fleet, launch, identity, _, _ = lane_fixture
    result = launch("--run", identity)
    assert result.returncode == 0, result
    assert events(packet.status) == ["START", "LOCKED", "NAMES", "PRODUCER", "DONE", "UNLOCKED"]
    assert not (fleet / ".claude-host.lock").exists()
    assert events(packet.status.parent / "supervisor/launcher.status")[-2:] == ["UNLOCKED", "DONE"]
    result = packet.read()
    assert result.returncode == 0, result.stderr
    assert json.loads(packet.result.read_text())["validity"]["verdict"] == "VALID"


def test_failed_worker_preserves_partial_and_cannot_be_resumed(lane_fixture):
    packet, fleet, launch, identity, _, _ = lane_fixture
    lane = packet.status.parent
    (lane / "fixture-mode").write_text("fail\n")
    result = launch("--run", identity)
    assert result.returncode == 7, result
    status = packet.status.read_bytes()
    assert events(packet.status)[-2:] == ["ABORT", "UNLOCKED"]
    assert events(lane / "supervisor/launcher.status")[-2:] == ["ABORT", "UNLOCKED"]
    assert not (fleet / ".claude-host.lock").exists()
    assert not (packet.root / "SHA256SUMS").exists()
    assert launch("--run", identity).returncode != 0
    assert packet.status.read_bytes() == status
    assert (packet.root / "duel.jsonl").read_bytes() == b"partial fixture\n"
    assert packet.read().returncode != 0
    assert not packet.result.exists()


@pytest.mark.parametrize("blocker", ["release", "identity", "hold", "lock", "recipe", "d1", "predecessor", "occupied"])
def test_admission_refuses_before_worker(lane_fixture, blocker):
    packet, fleet, launch, identity, _, _ = lane_fixture
    lane = packet.status.parent
    lock = fleet / ".claude-host.lock"
    if blocker == "release":
        (lane / "launcher.RELEASE").write_text("0" * 64 + "\n")
    elif blocker == "identity":
        identity = "0" * 64
    elif blocker == "hold":
        (lane / "launcher.HOLD").touch()
    elif blocker == "lock":
        lock.mkdir()
        (lock / "owner").write_text("42 foreign fixture\n")
    elif blocker == "recipe":
        write_json(packet.recipe_path, {"drifted": True})
    elif blocker == "d1":
        write_json(lane / "d1.json", {"drifted": True})
    elif blocker == "predecessor":
        with (fleet / "codex-sz2-post-M-v1/capture/launcher.status").open("a") as out:
            out.write("LANE START sz2-post-M-v1 2026-11-24T07:00:00Z later uncompleted attempt\n")
    elif blocker == "occupied":
        packet.root.mkdir()
        (packet.root / "duel.jsonl").write_bytes(b"previous fixture\n")
    assert launch("--run", identity).returncode != 0
    assert not packet.status.exists()
    if blocker == "lock":
        assert (lock / "owner").read_text() == "42 foreign fixture\n"
    else:
        assert not lock.exists()
    if blocker == "occupied":
        assert (packet.root / "duel.jsonl").read_bytes() == b"previous fixture\n"
    else:
        assert not packet.root.exists()


def test_runtime_hold_preserves_partial_before_unlock(lane_fixture):
    packet, fleet, _, identity, cmd, env = lane_fixture
    lane = packet.status.parent
    (lane / "fixture-mode").write_text("hold\n")
    with subprocess.Popen([*cmd, "--run", identity], env=env, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, text=True) as process:
        deadline = time.monotonic() + 10
        running = lane / "fixture-running"
        while not running.exists() and process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.025)
        (lane / "launcher.HOLD").touch()
        output = process.communicate(timeout=22)
        assert running.exists(), output
        assert process.returncode != 0, output
    assert events(packet.status)[-2:] == ["ABORT", "UNLOCKED"]
    assert events(lane / "supervisor/launcher.status")[-2:] == ["PAUSED", "UNLOCKED"]
    assert not (fleet / ".claude-host.lock").exists()
    assert not (packet.root / "SHA256SUMS").exists()
    assert (packet.root / "duel.jsonl").read_bytes() == b"partial fixture\n"


def test_failed_unlock_prevents_a_successful_readout(lane_fixture):
    packet, fleet, launch, identity, _, _ = lane_fixture
    lane = packet.status.parent
    (lane / "fixture-mode").write_text("blocked-release\n")
    result = launch("--run", identity)
    assert result.returncode == 6, result
    assert events(packet.status)[-2:] == ["DONE", "ABORT"]
    assert events(lane / "supervisor/launcher.status")[-2:] == ["WARNING", "ABORT"]
    assert (fleet / ".claude-host.lock/fixture-retained").read_text() == "held\n"
    assert (packet.root / "SHA256SUMS").is_file()
    assert packet.read().returncode != 0
    assert not packet.result.exists()



def test_semantically_wrong_clearance_refuses_even_when_pinned(lane_fixture):
    packet, fleet, launch, _, _, _ = lane_fixture
    lane = packet.status.parent
    d1 = lane / "d1.json"
    receipt = json.loads(d1.read_text())
    receipt["package_sha256"]["ex"] = "0" * 64
    write_json(d1, receipt)
    config = lane / "packet.pins"
    parts = config.read_text().split()
    parts[2] = sha(d1)
    config.write_text(" ".join(parts) + "\n")
    identity = launch("--identity")
    assert identity.returncode == 0, identity
    (lane / "launcher.RELEASE").write_text(identity.stdout)
    result = launch("--run", identity.stdout.strip())
    assert result.returncode != 0, result
    assert "D1 attestation" in result.stderr
    assert not packet.status.exists()
    assert not packet.root.exists()
    assert not (fleet / ".claude-host.lock").exists()
