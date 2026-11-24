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


def test_saved_synthetic_duel_reaches_the_actual_decision_cli(packet, monkeypatch):
    sys.path.insert(0, str(REPO / "server/scripts"))
    import sz2_a_capture as capture
    import sz2_a_recipe as recipes

    lane = packet.root.parent
    reference = dict(packet.recipe, round_plan="r2", pins={
        str(recipes.REFERENCE.parent / "kit/ut_read.py"): sha(lane / "kit/ut_read.py"),
        str(recipes.REFERENCE.parent / "ut_run_h2h.sh"): "historical",
        str(recipes.REFERENCE.parent / "kit/ut_h2h_adapter.py"): "fixture",
    })
    side = {k: v for k, v in packet.arm.items() if k not in ("status", "out_root")}
    with pytest.raises(ValueError, match="unexpected SZ2-A decision window"):
        recipes.decision_recipe(reference, dict(side, seed0=SEED0 + 1000), lane)
    packet.recipe = recipes.decision_recipe(reference, side, lane)
    adapter, *args = packet.recipe["producer_argv"]
    assert adapter in packet.recipe["pins"]
    assert args[:10] == [
        "--arm", "identity", "--seed0", str(SEED0), "--deals", str(DEALS), "--round-plan", "r2",
        "--out", str(Path(packet.arm["out_root"]) / "duel.jsonl"),
    ]
    assert list(zip(args[10::2], args[11::2], strict=True)) == [
        *(("--defender-env", word) for word in side["defender_words"]),
        *(("--exploiter-env", word) for word in side["exploiter_words"]),
    ]
    packet.root = Path(packet.arm["out_root"])
    packet.status = Path(packet.arm["status"])
    digest = packet.write_recipe()
    monkeypatch.setattr(capture, "LANE", lane)

    def command(*args, expected=digest):
        monkeypatch.setattr(sys, "argv", ["capture", "--recipe", str(packet.recipe_path),
                                          "--recipe-sha256", expected, *args])
        capture.main()

    start = ("reserve", "--supervisor-pid", "1", "--workers", "2")
    with pytest.raises(ValueError, match="independent SHA"):
        command(*start, expected="0" * 64)
    assert not packet.status.exists()
    command(*start)
    with pytest.raises(ValueError, match="occupied"):
        command(*start)
    assert set(packet.recipe["arms"]) == {ARM}
    with pytest.raises(ValueError, match="already exists"):
        recipes.decision_recipe(reference, side, lane)
    with packet.status.open("a") as out:
        for kind, detail in [("LOCKED", "after 0s"), ("NAMES", "ok"), ("PRODUCER", "fixture")]:
            out.write(capture.event(kind, detail))
    with pytest.raises(ValueError, match="producer exited"):
        command("seal", "--producer-rc", "9")
    packet.write_producer_outputs(b"partial")
    with pytest.raises(ValueError, match="incomplete mirror rows"):
        command("seal", "--producer-rc", "0")
    assert (packet.root / "duel.jsonl").read_bytes() == b"partial"
    assert not (packet.root / "manifest.json").exists()
    packet.write_producer_outputs()
    command("seal", "--producer-rc", "0")
    with packet.status.open("a") as out:
        out.write(capture.event("UNLOCKED", "fixture"))

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


@pytest.mark.parametrize("occupied", ["resume", "status", "symlink"])
def test_reserve_preserves_existing_capture(packet, occupied, monkeypatch):
    monkeypatch.syspath_prepend(str(REPO / "server/scripts"))
    import sz2_a_capture as capture

    lane = packet.root.parent
    root, status = lane / "out" / ARM, lane / f"{ARM}.status"
    packet.arm.update(out_root=str(root), status=str(status))
    if occupied == "resume":
        root.mkdir()
        witness = root / "duel.jsonl.resume.json"
    elif occupied == "status":
        witness = status
    else:
        root.symlink_to(lane, target_is_directory=True)
        witness = lane / "existing"
    witness.write_bytes(b"preserved")
    with pytest.raises(ValueError, match="occupied|symlink"):
        capture.reserve(packet.recipe, packet.write_recipe(), lane, 1, 1)
    assert witness.read_bytes() == b"preserved"
    assert status.exists() == (occupied == "status")
