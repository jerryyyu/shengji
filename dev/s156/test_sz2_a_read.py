"""Exercise the reviewed UTH reader and saved decision on a sealed synthetic duel."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from sz2_reader_fixture import ARM, DEALS, REPO, SEED0, fixture_packet, make_row, sha


@pytest.fixture
def packet(tmp_path):
    kit = os.environ.get("SZ2_UTH_KIT")
    if not kit:
        pytest.fail("set SZ2_UTH_KIT to the pinned legacy UTH kit")
    return fixture_packet(tmp_path, Path(kit))


def test_saved_synthetic_duel_reaches_the_actual_decision_cli(packet):
    packet.seal()
    read = packet.read()
    assert read.returncode == 0, read.stderr
    result = json.loads(packet.result.read_text())
    assert result["validity"]["verdict"] == "VALID"
    command = [
        sys.executable, "-B", str(REPO / "server/scripts/sz2_duel_decision.py"),
        "--result", str(packet.result), "--result-sha256", sha(packet.result),
        "--recipe", str(packet.recipe_path), "--recipe-sha256", sha(packet.recipe_path),
        "--medium-sha256", packet.arm["ex_package_sha256"], "--small-sha256", packet.arm["def_package_sha256"],
    ]
    decision = subprocess.run(command, capture_output=True, text=True, timeout=20)
    assert decision.returncode == 0, decision.stderr
    got = json.loads(decision.stdout)
    assert got["decision"] == "SIZE-PAYS"
    assert got["paired_deals"] == DEALS
    assert got["mean_levels_per_round"] == result["outcome"]["levels"]["mean"]
    assert got["lb80_levels_per_round"] == result["outcome"]["levels"]["lb80"]


def test_reader_rejects_same_challenger_team_on_both_mirrors(packet):
    def rows():
        for i in range(DEALS):
            for mirror in (0, 1):
                row = make_row(packet.reader, i, 0 if i == 0 else mirror)
                row["mirror"] = mirror
                yield row

    packet.seal(rows())
    read = packet.read()
    assert read.returncode == 3, read.stderr
    result = json.loads(packet.result.read_text())
    assert result["validity"]["verdict"] == "DEV_INVALID"
    assert result["outcome"] is None
    completion = next(check for check in result["validity"]["checks"] if check["check"] == "completion")
    assert any("challenger team differs from the seat assignment" in reason for reason in completion["reasons"])


@pytest.mark.parametrize(("arm", "seed", "deals"), [
    ("SZ2-B", SEED0, DEALS),
    (ARM, SEED0 + 2000, DEALS),
    (ARM, SEED0, 999),
])
def test_reader_checks_decision_window_before_reading_status(packet, arm, seed, deals):
    packet.recipe["arms"][arm] = {**packet.arm, "seed0": seed, "deals": deals}
    packet.write_recipe()
    assert not packet.status.exists()
    read = packet.read("--arm", arm)
    assert read.returncode != 0
    assert "only the SZ2-A decision window can enter this reader" in read.stderr
    assert not packet.result.exists()
