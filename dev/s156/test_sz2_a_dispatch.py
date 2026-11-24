"""Exercise SZ2-A dispatch through subprocesses and the frozen reader."""
import json
import shutil
import subprocess

import pytest

from sz2_reader_fixture import ARM, DEALS, REPO, SEED0, fixture_packet, make_row, sha, write_json


def git(tree, *args):
    return subprocess.check_output(["git", "-C", str(tree), *args], text=True).strip()


@pytest.fixture
def packet_factory(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(REPO / "server/scripts"))
    import sz2_a_dispatch as runner
    import sz2_a_recipe as recipes

    def build(failure=None):
        lane = tmp_path / "lane"
        packet = fixture_packet(lane)
        tree = tmp_path / "source"
        validity = tree / "server/scripts/expert_labels/validity.py"
        validity.parent.mkdir(parents=True)
        shutil.copyfile(REPO / validity.relative_to(tree), validity)
        git(tree, "init", "-q")
        git(tree, "add", str(validity.relative_to(tree)))
        git(tree, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
            "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null",
            "commit", "-qm", "Fixture validity source")

        reference = tmp_path / "legacy" / "recipe.h2h.json"
        kit = reference.parent / "kit"
        kit.mkdir(parents=True)
        shutil.copyfile(lane / "kit/ut_read.py", kit / "ut_read.py")
        monkeypatch.setattr(recipes, "REFERENCE", reference)
        monkeypatch.setattr(runner, "REFERENCE", reference)

        roles = ("defender", "exploiter")
        names = [packet.arm[f"{role}_name"] for role in roles]
        words = [packet.arm[f"{role}_words"] for role in roles]
        probe = kit / "probe_names.ut.py"
        adapter = kit / "ut_h2h_adapter.py"
        rows = kit / "fixture.jsonl"
        with rows.open("w") as out:
            stop = DEALS - 1 if failure == "short" else DEALS
            for index in range(stop):
                for mirror in (0, 1):
                    out.write(json.dumps(make_row(packet.reader, index, mirror)) + "\n")
        probe_names = names[::-1] if failure == "name" else names
        probe.write_text(
            "import json\n"
            "import sys\n"
            f"assert sys.argv[1:] == {[str(adapter), *[','.join(side) for side in words]]!r}\n"
            f"print(json.dumps({probe_names!r}))\n"
        )
        adapter.write_text(
            "import argparse\n"
            "import os\n"
            "from pathlib import Path\n"
            "import shutil\n"
            "p = argparse.ArgumentParser()\n"
            "for key in ('arm', 'seed0', 'deals', 'round-plan', 'out', 'workers'):\n"
            "    p.add_argument('--' + key, required=True)\n"
            "p.add_argument('--defender-env', action='append')\n"
            "p.add_argument('--exploiter-env', action='append')\n"
            "a = p.parse_args()\n"
            f"assert (a.arm, a.seed0, a.deals, a.round_plan, a.workers) == "
            f"{('identity', str(SEED0), str(DEALS), 'r2', '2')!r}\n"
            f"assert [a.defender_env, a.exploiter_env] == {words!r}\n"
            f"assert Path.cwd() == Path({str(tree / 'server')!r})\n"
            "assert os.environ['SHENGJI_FAST'] == '1'\n"
            "out = Path(a.out)\n"
            f"assert out == Path({str(lane / 'out' / ARM / 'duel.jsonl')!r})\n"
            f"shutil.copyfile({str(rows)!r}, out)\n"
            "out.with_name('duel.jsonl.resume.json').write_text('{}\\n')\n"
            f"raise SystemExit({9 if failure == 'child' else 0})\n"
        )
        legacy = dict(
            packet.recipe,
            tree=str(tree),
            tree_head=git(tree, "rev-parse", "HEAD"),
            round_plan="r2",
            pins={
                str(kit / "ut_read.py"): sha(lane / "kit/ut_read.py"),
                str(reference.parent / "ut_run_h2h.sh"): "historical",
                str(adapter): sha(adapter),
                str(probe): sha(probe),
                str(validity): sha(validity),
            },
        )
        write_json(reference, legacy)
        packet.recipe = recipes.decision_recipe(legacy, packet.arm, lane)
        packet.root = lane / "out" / ARM
        packet.status = lane / f"{ARM}.status"
        return packet, runner, lane

    return build


def kinds(packet):
    return [line.split()[1] for line in packet.status.read_text().splitlines()]


def test_dispatch_to_frozen_reader(packet_factory):
    packet, runner, lane = packet_factory()
    from sz2_a_capture import event
    runner.dispatch(packet.recipe_path, packet.write_recipe(), lane, 2, 1)
    assert kinds(packet) == ["START", "LOCKED", "NAMES", "PRODUCER", "DONE"]
    with packet.status.open("a") as out:
        out.write(event("UNLOCKED", "fixture"))
    result = packet.read()
    assert result.returncode == 0, result.stderr
    assert json.loads(packet.result.read_text())["validity"]["verdict"] == "VALID"


@pytest.mark.parametrize(("failure", "stage", "error", "has_rows"), [
    ("name", "names", ValueError, False),
    ("child", "producer", subprocess.CalledProcessError, True),
    ("short", "seal", ValueError, True),
])
def test_dispatch_failure_preserves_partial_output(packet_factory, failure, stage, error, has_rows):
    packet, runner, lane = packet_factory(failure)
    with pytest.raises(error):
        runner.dispatch(packet.recipe_path, packet.write_recipe(), lane, 2, 1)
    assert packet.status.read_text().splitlines()[-1].endswith(f"reason={stage}")
    events = kinds(packet)
    assert events[-1] == "ABORT"
    assert "DONE" not in events
    raw = packet.root / "duel.jsonl"
    assert raw.exists() == has_rows
    if has_rows:
        fixture_rows = runner.REFERENCE.parent / "kit/fixture.jsonl"
        assert sha(raw) == sha(fixture_rows)
    assert not (packet.root / "SHA256SUMS").exists()


def test_dispatch_leaves_existing_capture_intact(packet_factory):
    packet, runner, lane = packet_factory()
    packet.root.mkdir()
    partial = packet.root / "duel.jsonl"
    partial.write_bytes(b"preserve")
    with pytest.raises(ValueError, match="occupied"):
        runner.dispatch(packet.recipe_path, packet.write_recipe(), lane, 2, 1)
    assert partial.read_bytes() == b"preserve"
    assert not packet.status.exists()


@pytest.mark.parametrize(("drift", "error"), [
    ("dirty", "source tree differs"),
    ("pin", "pin changed"),
    ("argv", "unexpected duel producer or arguments"),
])
def test_dispatch_refuses_preflight_drift(packet_factory, drift, error):
    packet, runner, lane = packet_factory()
    if drift == "dirty":
        (lane.parent / "source/extra").touch()
    elif drift == "pin":
        (runner.REFERENCE.parent / "kit/probe_names.ut.py").write_text("raise SystemExit(9)\n")
    else:
        packet.recipe["producer_argv"] += ["--workers", "99"]

    with pytest.raises(ValueError, match=error):
        runner.dispatch(packet.recipe_path, packet.write_recipe(), lane, 2, 1)
    assert kinds(packet) == ["START", "LOCKED", "ABORT"]
    assert list(packet.root.iterdir()) == []


def test_command_requires_its_supervisor_lock(packet_factory, monkeypatch):
    packet, runner, lane = packet_factory()
    monkeypatch.setattr(runner, "LANE", lane)
    lock = lane.parent / ".claude-host.lock"
    lock.mkdir()
    (lock / "owner").write_text(f"{runner.os.getppid()} sz2-post-S-v1 fixture")
    args = ["--recipe", str(packet.recipe_path), "--recipe-sha256", packet.write_recipe(), "--workers", "2"]
    with pytest.raises(ValueError, match="own the host lock"):
        runner.main(args)
    assert not packet.status.exists()
    (lock / "owner").write_text(f"{runner.os.getppid()} sz2-duel-a-v1 fixture")
    runner.main(args)
    assert kinds(packet)[-1] == "DONE"
