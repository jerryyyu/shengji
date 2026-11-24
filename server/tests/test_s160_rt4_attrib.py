"""The S160 RT4 attribution packet (server/scripts/lanes/s160): seeds, the predeclared bar, the attribution's refusals and the
launcher's identity / check / refusal paths, in temporary lane copies.  Nothing here touches a host lock or a real lane."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import shutil
import socket
import subprocess
import sys
from pathlib import Path

import pytest

SERVER = Path(__file__).resolve().parents[1]
LANE = SERVER / "scripts" / "lanes" / "s160"
LIB = SERVER / "scripts" / "lanes" / "lane_lib.sh"
ENTRY = SERVER / "runs" / "seed_windows.d" / "rt4-attrib-dev-2666000000.json"
BASH = "/bin/bash"

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX shell launcher")


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


MR = _load("make_recipe_s160", LANE / "make_recipe_s160.py")
AT = _load("s160_attrib", LANE / "s160_attrib.py")


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_registry_entry_is_the_recipe_block():
    e = json.loads(ENTRY.read_text())
    name, seed0, n = MR.BLOCK
    assert (e["name"], e["seed0"], e["clusters"], e["span"]) == (name, seed0, n, [seed0, seed0 + n])
    assert e["purpose"] == "screen"


def test_every_dealt_span_is_inside_the_block_and_disjoint():
    _, seed0, n = MR.BLOCK
    spans = sorted(MR.arm_spans(), key=lambda s: s[2])
    assert len(spans) == 9
    for _, _, lo, hi in spans:
        assert seed0 <= lo < hi <= seed0 + n
    for a, b in zip(spans, spans[1:]):
        assert a[3] <= b[2], (a, b)
    assert {a for a, kind, lo, hi in spans if kind == "duel" and hi - lo == MR.DEALS} == {"B4", "U4", "D4"}


def test_arms_are_the_predeclared_swaps():
    assert MR.ARMS["B4"][:2] == (("R54", "RT4", "root"), ("R54", "R54", "shared"))
    assert MR.ARMS["U4"][:2] == (("RT4", "R54", "root"), ("R54", "R54", "shared"))
    assert MR.ARMS["D4"][:2] == (("RT4", "RT4", "shared"), ("RT2", "RT2", "shared"))
    text = (LANE / "PREDECLARE_S160.md").read_text()
    for arm, (_, _, seed0, pseed, _) in MR.ARMS.items():
        assert f"[{seed0}, {seed0 + MR.DEALS})" in text and f"[{pseed}, +20)" in text, arm


def _lv(mean, lb80, half=0.028):
    return dict(n=1000, mean=mean, ci95=[mean - half, mean + half], lb80=lb80, lb95_one_sided=lb80 - 0.01)


@pytest.mark.parametrize("b, u, label", [
    ((0.05, 0.03), (0.01, -0.005), "BELIEF-CARRIES"),
    ((0.01, -0.005), (0.06, 0.04), "HEADS-CARRY"),
    ((0.045, 0.03), (0.042, 0.03), "BOTH-CARRY"),
    ((0.03, 0.015), (0.03, 0.015), "NEITHER-CARRIES"),
    ((0.05, 0.0), (0.0, -0.02), "NEITHER-CARRIES"),          # LB80 must be strictly above 0
])
def test_the_slot_bar(b, u, label):
    res = AT.attribute(_lv(*b), _lv(*u), AT.JOINT_MEAN)
    assert res["label"] == label
    assert res["threshold"] == pytest.approx(0.6 * 0.06887755102040816)
    assert res["interaction"]["point"] == pytest.approx(AT.JOINT_MEAN - b[0] - u[0])
    assert res["next_retrain"] == ("no change" if label == "NEITHER-CARRIES" else "see label")


def test_the_bar_is_inclusive_at_sixty_percent():
    t = AT.CARRY_SHARE * AT.JOINT_MEAN
    assert AT.carries(_lv(t, 0.001), AT.JOINT_MEAN)
    assert not AT.carries(_lv(t - 1e-9, 0.001), AT.JOINT_MEAN)


def _attrib_fixture(tmp_path: Path, monkeypatch, b4_valid=True):
    reader = tmp_path / "reader.py"
    reader.write_text("# reader\n")
    recipe = tmp_path / "recipe.json"
    recipe.write_text(json.dumps(dict(schema="utd-mix-recipe-r1", lane="S160", reader_sha256=_sha(reader), predeclare_sha256="p")))
    ref = tmp_path / "R4H.read.json"
    ref.write_text(json.dumps(dict(outcome=dict(all=dict(levels=dict(mean=AT.JOINT_MEAN))))))
    monkeypatch.setattr(AT, "JOINT_REF_SHA256", _sha(ref))
    ro = tmp_path / "readout"
    ro.mkdir()
    for arm, lv in (("B4", _lv(0.05, 0.03)), ("U4", _lv(0.01, -0.005))):
        ok = b4_valid or arm != "B4"
        (ro / f"{arm}.read.json").write_text(json.dumps(dict(
            schema="utx-read-r1", arm=arm, duel="UTX", reader_sha256=_sha(reader), binding=dict(recipe_sha256=_sha(recipe)),
            validity=dict(verdict="VALID" if ok else "DEV_INVALID"), outcome=dict(levels=lv) if ok else None)))
    argv = ["--recipe", str(recipe), "--readout", str(ro), "--ref-joint", str(ref), "--out", str(tmp_path / "ATTRIB.json")]
    return argv, tmp_path / "ATTRIB.json"


def test_attribution_runs_once_on_valid_reads(tmp_path, monkeypatch):
    argv, out = _attrib_fixture(tmp_path, monkeypatch)
    assert AT.main(argv) == 0
    d = json.loads(out.read_text())
    assert d["schema"] == "s160-attrib-r1" and d["label"] == "BELIEF-CARRIES" and set(d["reads"]) == {"B4", "U4"}
    assert AT.main(argv) == 2           # the output exists: it never runs twice


def test_attribution_refuses_an_invalid_read(tmp_path, monkeypatch):
    argv, out = _attrib_fixture(tmp_path, monkeypatch, b4_valid=False)
    assert AT.main(argv) == 2 and not out.exists()


def test_attribution_refuses_an_unpinned_joint(tmp_path, monkeypatch):
    argv, out = _attrib_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(AT, "JOINT_REF_SHA256", "0" * 64)
    assert AT.main(argv) == 2 and not out.exists()


def _stage(tmp_path: Path, *, local_host: bool) -> Path:
    """A lane copy whose cfg points at tmp paths (and, with local_host, at this host, this python and a clean git tree)."""
    z = tmp_path / "lane"
    (z / "lanes").mkdir(parents=True)
    (z / "clear").mkdir()
    for f in ("s160.sh", "s160.cfg", "s160_run.sh", "make_recipe_s160.py", "s160_attrib.py", "PREDECLARE_S160.md"):
        shutil.copy2(LANE / f, z / f)
    shutil.copy2(LIB, z / "lanes" / "lane_lib.sh")
    (z / "recipe.json").write_text("{}\n")
    (z / "clear" / "CLEARED").write_text("CLEAR test fixture\n")
    cfg = (z / "s160.cfg").read_text()
    cfg = re.sub(r"(?m)^S=.*$", f"S={z}", cfg)
    cfg = re.sub(r"(?m)^LANE_HOLDS=.*$", f'LANE_HOLDS="{tmp_path}/claude_s160.HOLD"', cfg)
    cfg = re.sub(r"(?m)^LANE_LOCK=.*$", f"LANE_LOCK={tmp_path}/host.lock", cfg)
    cfg = re.sub(r"(?m)^S160_RELEASE=.*$", f"S160_RELEASE={tmp_path}/claude_s160.RELEASE", cfg)
    cfg = re.sub(r"(?m)^LANE_DISK_DIR=.*$", f"LANE_DISK_DIR={tmp_path}", cfg)
    if local_host:
        tree = tmp_path / "tree"
        tree.mkdir()
        git = ["git", "-C", str(tree), "-c", "user.name=t", "-c", "user.email=t@t"]
        subprocess.run(["git", "init", "-q", str(tree)], check=True)
        (tree / "f").write_text("x\n")
        subprocess.run(git + ["add", "f"], check=True)
        subprocess.run(git + ["commit", "-q", "-m", "t"], check=True)
        head = subprocess.run(["git", "-C", str(tree), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
        cfg = re.sub(r"(?m)^T=.*$", f"T={tree}", cfg)
        cfg = re.sub(r"(?m)^TREE_HEAD=.*$", f"TREE_HEAD={head}", cfg)
        cfg = re.sub(r"(?m)^PY=.*$", f"PY={sys.executable}", cfg)
        cfg = re.sub(r"(?m)^LANE_HOSTNAME=.*$", f"LANE_HOSTNAME={socket.gethostname()}", cfg)
        cfg = re.sub(r'(?ms)^S160_PINS=".*?"$', f'S160_PINS="{z}/PREDECLARE_S160.md {_sha(z / "PREDECLARE_S160.md")}"', cfg)
        cfg = re.sub(r"(?m)^LANE_SEED_TREE=.*$", f"LANE_SEED_TREE={tmp_path}/no-seed-tree", cfg)
    (z / "s160.cfg").write_text(cfg)
    return z


def _run(z: Path, mode: str):
    return subprocess.run([BASH, str(z / "s160.sh"), mode], capture_output=True, text=True, timeout=120)


def test_identity_is_the_manifest_of_the_lane_files(tmp_path):
    z = _stage(tmp_path, local_host=False)
    p = _run(z, "identity")
    assert p.returncode == 0 and re.fullmatch(r"[0-9a-f]{64}\n", p.stdout), p.stderr
    names = ("s160.sh", "lanes/lane_lib.sh", "s160.cfg", "PREDECLARE_S160.md", "make_recipe_s160.py", "s160_run.sh", "s160_attrib.py",
             "recipe.json", "clear/CLEARED")
    manifest = "".join(f"{_sha(z / n)}  {Path(n).name}\n" for n in names)
    assert p.stdout.strip() == hashlib.sha256(manifest.encode()).hexdigest()
    (z / "recipe.json").write_text('{"changed": 1}\n')
    assert _run(z, "identity").stdout != p.stdout           # the recipe is bound in the token


def test_unknown_mode_refuses(tmp_path):
    z = _stage(tmp_path, local_host=False)
    assert _run(z, "launch").returncode == 2


def test_run_refuses_without_a_release(tmp_path):
    z = _stage(tmp_path, local_host=True)
    p = _run(z, "run")
    assert p.returncode == 6, p.stderr
    status = (z / "run.status").read_text()
    assert re.search(r"(?m)^S160 ABORT claude-s160-run \S+ rc=6 reason=.*RELEASE", status), status
    assert not (tmp_path / "host.lock").exists() and not (z / "out").exists()


def test_run_refuses_on_another_host(tmp_path):
    z = _stage(tmp_path, local_host=False)
    if socket.gethostname() == "Jerrys-Mac-Studio.local":
        pytest.skip("this is the lane host")
    p = _run(z, "run")
    assert p.returncode == 6
    assert re.search(r"(?m)^S160 ABORT claude-s160-run \S+ rc=6 reason=.*hostname", (z / "run.status").read_text())


def test_check_mode_is_a_dry_run(tmp_path):
    z = _stage(tmp_path, local_host=True)
    p = _run(z, "check")
    assert p.returncode == 0, p.stderr
    status = (z / "check.status").read_text()
    assert re.search(r"(?m)^S160 DONE claude-s160-check \S+ identity=[0-9a-f]{64} mode=check rc=0$", status), status
    assert "S160 NOTE" in status                             # the seed block is not admissible without the merged registry
    assert not (tmp_path / "host.lock").exists() and not (z / "out").exists() and not (z / "readout").exists()


def test_check_mode_reports_a_failed_pilot_check(tmp_path):
    z = _stage(tmp_path, local_host=True)
    (z / "pilotB4.check.invalid.json").write_text("{}\n")
    p = _run(z, "check")
    assert p.returncode == 0
    assert re.search(r"(?m)^S160 NOTE claude-s160-check \S+ saved results: pilotB4 has a failed", (z / "check.status").read_text())


def test_lane_scripts_pass_the_lane_checker():
    p = subprocess.run([sys.executable, str(SERVER / "scripts" / "check_lane_scripts.py"), "--strict", str(LANE)],
                       capture_output=True, text=True)
    assert p.returncode == 0, p.stdout + p.stderr
