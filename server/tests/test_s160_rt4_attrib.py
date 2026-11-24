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
ENTRY = SERVER / "runs" / "seed_windows.d" / "rt4-attrib-dev-2667000000.json"
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
    for f in ("s160.sh", "s160.cfg", "s160_run.sh", "make_recipe_s160.py", "s160_attrib.py", "s160_guard.py", "dispatch_s160.sh",
              "PREDECLARE_S160.md"):
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
        (tree / "server").mkdir()
        (tree / "server" / "f").write_text("x\n")
        subprocess.run(git + ["add", "server/f"], check=True)
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
             "s160_guard.py", "dispatch_s160.sh", "recipe.json", "clear/CLEARED")
    manifest = "".join(f"{_sha(z / n)}  {Path(n).name}\n" for n in names)
    assert p.stdout.strip() == hashlib.sha256(manifest.encode()).hexdigest()
    (z / "recipe.json").write_text('{"changed": 1}\n')
    assert _run(z, "identity").stdout != p.stdout           # the recipe is bound in the token


def test_unknown_mode_refuses(tmp_path):
    z = _stage(tmp_path, local_host=False)
    assert _run(z, "launch").returncode == 2


def test_run_refuses_without_a_release(tmp_path):
    z = _stage(tmp_path, local_host=True)
    ident = _run(z, "identity").stdout.strip()
    p = subprocess.run([BASH, str(z / "s160.sh"), "run", ident], capture_output=True, text=True, timeout=60)
    assert p.returncode == 6, p.stderr
    status = (z / "run.status").read_text()
    assert re.search(r"(?m)^S160 ABORT claude-s160-run \S+ rc=6 reason=.*RELEASE", status), status
    assert not (tmp_path / "host.lock").exists() and not (z / "out").exists()


def test_run_refuses_on_another_host(tmp_path):
    z = _stage(tmp_path, local_host=False)
    if socket.gethostname() == "Jerrys-Mac-Studio.local":
        pytest.skip("this is the lane host")
    ident = _run(z, "identity").stdout.strip()
    p = subprocess.run([BASH, str(z / "s160.sh"), "run", ident], capture_output=True, text=True, timeout=60)
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


GD = _load("s160_guard", LANE / "s160_guard.py")
SEALED = ("duel.jsonl", "duel.jsonl.resume.json", "duel.time", "manifest.json", "run.log")


def _row(seed, mirror, team):
    return dict(seed=seed, mirror=mirror, arm="identity", ex_team=team, ex_levels=1 if team else -1)


FAKE_READER = """
import hashlib, json, re
from pathlib import Path
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main(argv):
    recipe, arm, out = argv[1], argv[3], argv[5]
    rc = json.loads(Path(recipe).read_text()); ra = rc["arms"][arm]; root = Path(ra["out_root"])
    done = [l for l in Path(ra["status"]).read_text().splitlines() if l.startswith("UTD DONE ")][-1]
    json.dump(dict(schema="utx-read-r1", arm=arm, duel="UTX", reader_sha256=sha(__file__), validity=dict(verdict="VALID"),
                   binding=dict(recipe_sha256=sha(recipe), sums_sha256=sha(root / "SHA256SUMS"), duel_jsonl_sha256=sha(root / "duel.jsonl"),
                                terminal=done), outcome=dict(levels=dict(n=1000, mean=0.0, ci95=[0, 0], lb80=0.0))), open(out, "x"))
    return 0
"""


ARM_SEEDS = {"B4": (2667000000, 2667003000), "U4": (2667001000, 2667003020), "D4": (2667002000, 2667003040)}


def _guard_lane(tmp_path: Path, teams=(0, 1), kind="pilot", arm="B4", lane=None, garbage=False, reader_src=None, arms=None):
    """A lane with sealed outputs laid out exactly as s160_run.sh seals them, and a recipe naming every arm."""
    lane = lane or tmp_path / "glane"
    arms = arms or (arm,)
    reader = lane / "kit" / "ut_mix_read.py"
    reader.parent.mkdir(parents=True, exist_ok=True)
    reader.write_text(reader_src or "raise SystemExit('the pinned reader must not be reached')\n")
    ras = {a: dict(seed0=ARM_SEEDS[a][0], deals=1000, pilot_seed0=ARM_SEEDS[a][1], out_root=str(lane / "out" / a), status=str(lane / f"{a}.status"))
           for a in arms}
    recipe = lane / "recipe.json"
    recipe.write_text(json.dumps(dict(schema="utd-mix-recipe-r1", lane="S160", tree=str(tmp_path), tree_head="h" * 40,
                                      reader=str(reader), reader_sha256=_sha(reader), arms=ras)))
    rsha = _sha(recipe)
    first = None
    for a in arms:
        seed0, deals = (ARM_SEEDS[a][1], 20) if kind == "pilot" else (ARM_SEEDS[a][0], 1000)
        mode = f"pilot{a}" if kind == "pilot" else a
        out = lane / mode if kind == "pilot" else lane / "out" / a
        status = lane / f"{mode}.status"
        out.mkdir(parents=True)
        rows = [_row(seed0 + i, m, teams[m]) for i in range(deals) for m in (0, 1)]
        (out / "duel.jsonl").write_text("not json: raw rows cannot be parsed\n" if garbage else "".join(json.dumps(r) + "\n" for r in rows))
        for f in ("duel.jsonl.resume.json", "duel.time", "run.log"):
            (out / f).write_text(f"{f}\n")
        (out / "manifest.json").write_text(json.dumps(dict(schema="utd-manifest-r1", mode=mode, arm=a, recipe_sha256=rsha, seed0=seed0,
                                                           deals=deals, tree_head="h" * 40, rc=0)))
        (out / "SHA256SUMS").write_text("".join(f"{_sha(out / f)}  ./{f}\n" for f in SEALED))
        ts = "2026-11-24T00:00:00Z"
        status.write_text(f"UTD START {ts} mode={mode} arm={a} pid=1 seed0={seed0} deals={deals} workers=24 recipe={rsha}\n"
                          f"UTD LOCKED {ts} after 0s (co-run)\nUTD NAMES {ts} ok\nUTD PRODUCER {ts} load=x\n"
                          f"UTD DONE {ts} recipe={rsha} rows={2 * deals} sums={_sha(out / 'SHA256SUMS')} rc=0\nUTD UNLOCKED {ts} (lock not held by this run)\n")
        first = first or (out, status)
    return lane, recipe, first[0], first[1]


def test_mirror_teams_requires_the_producers_ordered_mapping():
    assert GD.mirror_teams([_row(5, 0, 0), _row(5, 1, 1)], 5, 1) == []
    assert GD.mirror_teams([_row(5, 0, 1), _row(5, 1, 0)], 5, 1)        # reversed: the sign of the pair flips
    assert GD.mirror_teams([_row(5, 0, 0), _row(5, 1, 0)], 5, 1)        # the same team twice
    assert GD.mirror_teams([_row(5, 0, False), _row(5, 1, True)], 5, 1)  # not the producer's integers
    assert GD.mirror_teams([_row(5, 0, 0)], 5, 1)


@pytest.mark.parametrize("teams", [(0, 0), (1, 0), (1, 1)])
def test_pilot_check_refuses_a_bad_mirror_mapping_before_the_reader(tmp_path, teams):
    _, recipe, _, _ = _guard_lane(tmp_path, teams=teams)
    code, res = GD.pilot_check(str(recipe), "B4")
    assert code == 3 and res["validity"] == "DEV_INVALID" and res["failing"][0][0] == "mirror_teams"


@pytest.mark.parametrize("teams", [(0, 0), (1, 0), (1, 1)])
def test_read_refuses_a_bad_mirror_mapping_with_no_outcome(tmp_path, teams):
    lane, recipe, _, _ = _guard_lane(tmp_path, teams=teams, kind="duel")
    (lane / "readout").mkdir()
    out = lane / "readout" / "B4.read.json"
    assert GD.main(["read", str(recipe), "B4", str(out)]) == 3
    assert not out.exists() and not (lane / "readout" / "B4.read.bind.json").exists()


def _bound_read(tmp_path, monkeypatch, lane=None, arms=("B4",)):
    """A successful read through the guard on each sealed arm whose raw rows cannot be parsed afterwards."""
    lane, recipe, out, status = _guard_lane(tmp_path, kind="duel", lane=lane, garbage=True, reader_src=FAKE_READER, arms=arms)
    (lane / "readout").mkdir(exist_ok=True)
    for a in arms:
        good = [_row(ARM_SEEDS[a][0] + i, m, m) for i in range(1000) for m in (0, 1)]
        monkeypatch.setattr(GD, "rows_of", lambda _out, good=good: good)   # the rows as the producer wrote them, for the one read
        assert GD.main(["read", str(recipe), a, str(lane / "readout" / f"{a}.read.json")]) == 0
    rj = lane / "readout" / f"{arms[0]}.read.json"
    monkeypatch.undo()
    with pytest.raises(ValueError):                           # raw row parsing now fails
        GD.rows_of(out)
    return lane, recipe, rj


def test_a_saved_read_is_accepted_only_through_its_binding(tmp_path, monkeypatch):
    lane, recipe, rj = _bound_read(tmp_path, monkeypatch)
    bd = rj.with_name("B4.read.bind.json")
    rec = json.loads(bd.read_text())
    assert rec["mirror_teams"] == {"verdict": "ok", "deals_checked": 1000} and rec["read_sha256"] == _sha(rj)
    assert GD.main(["verify-read", str(recipe), "B4", str(rj)]) == 0
    bd.write_text(json.dumps(dict(rec, read_sha256="0" * 64)))
    assert GD.main(["verify-read", str(recipe), "B4", str(rj)]) == 1
    bd.unlink()
    assert GD.main(["verify-read", str(recipe), "B4", str(rj)]) == 1


def _recovery_lane(tmp_path, monkeypatch, arms=("B4",)):
    z = _stage(tmp_path, local_host=True)
    _bound_read(tmp_path, monkeypatch, lane=z, arms=arms)
    ro = z / "readout"
    for a in arms:
        (ro / f"{a}.read.claim").write_text("claude s160 test claim\n")
        (ro / f"{a}.read.rc").write_text("0\n")
        (ro / f"{a}.read.out").write_text("{}\n")
        (ro / f"{a}.read.err").write_text("")
    return z, ro


def _lock_payloads(z: Path, arms):
    """Raw opens disallowed: every sealed payload of the arms is made unreadable (the directory listing stays)."""
    for a in arms:
        for f in SEALED:
            (z / "out" / a / f).chmod(0)


def _bound_attrib(z: Path, ro: Path):
    at = z / "s160_attrib.py"
    d = dict(schema="s160-attrib-r1", attrib_sha256=_sha(at), recipe_sha256=_sha(z / "recipe.json"), label="NEITHER-CARRIES",
             reads={a: _sha(ro / f"{a}.read.json") for a in ("B4", "U4")})
    (ro / "ATTRIB.json").write_text(json.dumps(d))
    for f, t in (("ATTRIB.claim", "claim\n"), ("ATTRIB.rc", "0\n"), ("ATTRIB.out", "{}\n"), ("ATTRIB.err", "")):
        (ro / f).write_text(t)


def test_recovery_accepts_a_bound_read_without_parsing_rows(tmp_path, monkeypatch):
    z, _ = _recovery_lane(tmp_path, monkeypatch)
    assert _run(z, "check").returncode == 0
    status = (z / "check.status").read_text()
    assert re.search(r"(?m)^S160 CHECKED claude-s160-check \S+ saved results: none or valid$", status), status


@pytest.mark.parametrize("damage", ["missing", "mismatched"])
def test_recovery_refuses_a_missing_or_mismatched_binding(tmp_path, monkeypatch, damage):
    z, ro = _recovery_lane(tmp_path, monkeypatch)
    bd = ro / "B4.read.bind.json"
    if damage == "missing":
        bd.unlink()
    else:
        bd.write_text(json.dumps(dict(json.loads(bd.read_text()), seal={"sums_sha256": "0" * 64})))
    assert _run(z, "check").returncode == 0
    status = (z / "check.status").read_text()
    assert re.search(r"(?m)^S160 NOTE claude-s160-check \S+ saved results: a claimed attempt .*read binding", status), status


def test_seal_is_bound_to_the_done_digest_and_the_output_set(tmp_path):
    _, recipe, out, status = _guard_lane(tmp_path)
    assert GD.seal(str(recipe), "B4", "pilot")["sums_sha256"] == _sha(out / "SHA256SUMS")
    (out / "extra.txt").write_text("x\n")                    # an unlisted file in the output
    with pytest.raises(GD.Refusal):
        GD.seal(str(recipe), "B4", "pilot")
    (out / "extra.txt").unlink()
    (out / "SHA256SUMS").write_text((out / "SHA256SUMS").read_text() + f"{_sha(out / 'run.log')}  ./extra.txt\n")
    with pytest.raises(GD.Refusal):                           # a re-written sums file no longer hashes to the DONE line
        GD.seal(str(recipe), "B4", "pilot")


def test_a_two_field_pilot_verdict_is_not_a_saved_pilot_check(tmp_path):
    lane, recipe, _, _ = _guard_lane(tmp_path)
    chk = lane / "pilotB4.check.json"
    chk.write_text(json.dumps(dict(validity="VALID", failing=[])))
    with pytest.raises(GD.Refusal):
        GD.verify_pilot(str(recipe), "B4", str(chk))
    good = dict(schema="s160-pilot-check-r1", arm="B4", recipe_sha256=_sha(recipe), checker_sha256=_sha(LANE / "s160_guard.py"),
                reader_sha256=json.loads(recipe.read_text())["reader_sha256"], seal=GD.seal(str(recipe), "B4", "pilot"),
                validity="VALID", failing=[], mirror_teams="ok")
    chk.write_text(json.dumps(good))
    GD.verify_pilot(str(recipe), "B4", str(chk))
    chk.write_text(json.dumps(dict(good, arm="U4")))
    with pytest.raises(GD.Refusal):
        GD.verify_pilot(str(recipe), "B4", str(chk))


def test_a_saved_attribution_is_bound_to_the_accepted_reads(tmp_path, monkeypatch):
    ro = tmp_path / "readout"
    ro.mkdir()
    recipe = tmp_path / "recipe.json"
    recipe.write_text("{}\n")
    for arm in ("B4", "U4"):
        (ro / f"{arm}.read.json").write_text(json.dumps({"arm": arm}))
    monkeypatch.setattr(GD, "verify_read", lambda *a: None)
    at = LANE / "s160_attrib.py"
    d = dict(schema="s160-attrib-r1", attrib_sha256=_sha(at), recipe_sha256=_sha(recipe), label="NEITHER-CARRIES",
             reads={arm: _sha(ro / f"{arm}.read.json") for arm in ("B4", "U4")})
    (ro / "ATTRIB.json").write_text(json.dumps(d))
    GD.verify_attrib(str(recipe), str(ro / "ATTRIB.json"), at)
    (ro / "ATTRIB.json").write_text(json.dumps(dict(d, reads=dict(d["reads"], U4="0" * 64))))
    with pytest.raises(GD.Refusal):
        GD.verify_attrib(str(recipe), str(ro / "ATTRIB.json"), at)


@pytest.mark.parametrize("files", [("B4.read.out",), ("B4.read.claim",), ("B4.read.claim", "B4.read.out", "B4.read.err"),
                                   ("ATTRIB.claim",), ("ATTRIB.err",)])
def test_a_partial_read_attempt_stops_the_chain(tmp_path, files):
    z = _stage(tmp_path, local_host=True)
    (z / "readout").mkdir()
    for f in files:
        (z / "readout" / f).write_text("partial\n")
    assert _run(z, "check").returncode == 0
    status = (z / "check.status").read_text()
    assert re.search(r"(?m)^S160 NOTE claude-s160-check \S+ saved results: .*(without an attempt claim|no fully verified result)", status), status


def _release(z: Path, tmp_path: Path) -> str:
    ident = _run(z, "identity").stdout.strip()
    (tmp_path / "claude_s160.RELEASE").write_text(ident + "\n")
    return ident


def test_run_refuses_a_held_lock_instead_of_waiting(tmp_path):
    z = _stage(tmp_path, local_host=True)
    ident = _release(z, tmp_path)
    (tmp_path / "host.lock").mkdir()
    (tmp_path / "host.lock" / "owner").write_text("999 another-lane t\n")
    p = subprocess.run([BASH, str(z / "s160.sh"), "run", ident], capture_output=True, text=True, timeout=60)
    assert p.returncode == 5, p.stderr
    assert re.search(r"(?m)^S160 ABORT claude-s160-run \S+ rc=5 reason=host lock held .*direct admission", (z / "run.status").read_text())
    assert (tmp_path / "host.lock" / "owner").read_text() == "999 another-lane t\n"


def test_run_needs_its_identity_as_the_argument(tmp_path):
    z = _stage(tmp_path, local_host=True)
    _release(z, tmp_path)
    p = subprocess.run([BASH, str(z / "s160.sh"), "run"], capture_output=True, text=True, timeout=60)
    assert p.returncode == 6 and not (z / "run.status").exists()


def test_dispatch_hands_over_only_to_the_queued_identity():
    text = (LANE / "dispatch_s160.sh").read_text()
    assert 'next=$(env -u FLEET_QUEUE python3 "$tools/fleet_queue.py" next ultra)' in text
    assert '[ "$next" = "$name:released sha=${identity:0:8}" ]' in text
    assert "name=s160-rt4attrib-v1" in text and "run $identity" in text


needs_unreadable = pytest.mark.skipif(hasattr(__import__("os"), "geteuid") and __import__("os").geteuid() == 0, reason="root reads mode-0 files")


@needs_unreadable
def test_reuse_reads_only_metadata_with_raw_opens_disallowed(tmp_path, monkeypatch):
    z, ro = _recovery_lane(tmp_path, monkeypatch, arms=("B4", "U4"))
    _bound_attrib(z, ro)
    _lock_payloads(z, ("B4", "U4"))
    with pytest.raises(PermissionError):
        (z / "out" / "B4" / "duel.jsonl").read_bytes()
    recipe = str(z / "recipe.json")
    assert GD.main(["verify-read", recipe, "B4", str(ro / "B4.read.json")]) == 0
    assert GD.main(["verify-attrib", recipe, str(ro / "ATTRIB.json")]) == 0
    p = _run(z, "check")                                     # the launcher's preflight and its arm / attribution reuse decision
    assert p.returncode == 0, p.stderr
    status = (z / "check.status").read_text()
    for line in ("saved results: none or valid", "arm B4: bound read reused from metadata", "arm U4: bound read reused from metadata",
                 "attribution: bound result reused from metadata"):
        assert re.search(rf"(?m)^S160 CHECKED claude-s160-check \S+ {line}$", status), (line, status)


@needs_unreadable
@pytest.mark.parametrize("damage", ["sums", "done-digest", "read", "binding-reader"])
def test_reuse_refuses_corrupt_metadata_or_a_changed_result(tmp_path, monkeypatch, damage):
    z, ro = _recovery_lane(tmp_path, monkeypatch)
    _lock_payloads(z, ("B4",))
    out, st = z / "out" / "B4", z / "B4.status"
    if damage == "sums":
        out.joinpath("SHA256SUMS").write_text(out.joinpath("SHA256SUMS").read_text().replace("./run.log", "./run.lg"))
    elif damage == "done-digest":
        st.write_text(re.sub(r"sums=[0-9a-f]{64}", "sums=" + "0" * 64, st.read_text()))
    elif damage == "read":
        d = json.loads((ro / "B4.read.json").read_text())
        d["outcome"]["levels"]["mean"] = 0.5
        (ro / "B4.read.json").write_text(json.dumps(d))
    else:
        b = json.loads((ro / "B4.read.bind.json").read_text())
        (ro / "B4.read.bind.json").write_text(json.dumps(dict(b, reader_sha256="0" * 64)))
    assert GD.main(["verify-read", str(z / "recipe.json"), "B4", str(ro / "B4.read.json")]) == 1
    assert _run(z, "check").returncode == 0
    assert re.search(r"(?m)^S160 NOTE claude-s160-check \S+ saved results: a claimed attempt", (z / "check.status").read_text())
