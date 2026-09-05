"""Seed-window registry: the committed ledger and the refusal of overlapping
deal windows (Run A/B: seed0 20260905 and 20260906 x 8,000 clusters shared
7,999 deals and Run B added nothing in training).

Witnesses: (a) ``require_disjoint`` on the A/B case names Run A and the
7,999-seed overlap; (b) a disjoint window passes and registers, a resume of
the same window passes; (c) ``trajectory.py --seed 20260910 --rounds 2``
refuses naming Run A/B and passes with ``--allow-seed-overlap`` recording
the conflicts; (d) ``cwv_duel run`` inside Run C's window refuses, at the
70260904 screen window refuses without the flag and passes with it,
recording the replicate; (e) the RED direction is ``test_red_*``.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
from pathlib import Path

import pytest

from shengji import seeds
from shengji.harvest import trajectory

SERVER = Path(__file__).resolve().parents[1]
COMMITTED = seeds.DEFAULT_REGISTRY

WORK = {"select_worlds": 2, "report_worlds": 30, "explore_rate": 0.0, "explore_k": 2}


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, SERVER / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def registry(tmp_path):
    """A scratch copy of the committed registry (the conftest already points
    SHENGJI_SEED_WINDOWS at a scratch file; fill it with the real windows)."""
    path = Path(os.environ["SHENGJI_SEED_WINDOWS"])
    shutil.copy(COMMITTED, path)
    return path


# ------------------------------------------------------------ the ledger

def test_committed_registry_holds_the_known_windows():
    reg = seeds.load(COMMITTED)
    by = {w["name"]: w for w in reg["windows"]}
    assert (by["run-A"]["seed0"], by["run-A"]["clusters"]) == (20260905, 8000)
    assert (by["run-B"]["seed0"], by["run-B"]["clusters"]) == (20260906, 8000)
    assert (by["run-C"]["seed0"], by["run-C"]["clusters"]) == (30260904, 32000)
    assert (by["run-D"]["seed0"], by["run-D"]["clusters"]) == (40260904, 32000)
    assert (by["run-E"]["seed0"], by["run-E"]["clusters"]) == (45260904, 16000)
    for s in (50260904, 60260904, 70260904, 80260904, 90260904):
        assert by[f"screen-{s}"]["purpose"] == "screen" and by[f"screen-{s}"]["clusters"] == 256
    assert by["calibration-70360904"]["clusters"] == 4
    assert by["calibration-88261904"]["clusters"] == 2
    assert by["calibration-89260904"]["clusters"] == 2
    assert by["screen-oneply-mini-70260904"]["seed0"] == 70260904
    assert by["screen-leaf-mini-70260904"]["seed0"] == 70260904
    assert "overlap" in by["run-B"]["note"].lower()
    for w in reg["windows"]:
        assert w["span"] == [w["seed0"], w["seed0"] + w["clusters"]]
        assert w["purpose"] in seeds.PURPOSES
    assert len(reg["windows"]) == 15


def test_window_and_overlap_span():
    assert seeds.window(20260905, 8000) == (20260905, 20268905)
    assert seeds.overlap_span((0, 10), (10, 20)) is None
    assert seeds.overlap_span((0, 10), (9, 20)) == (9, 10)
    with pytest.raises(seeds.SeedWindowError):
        seeds.window(1, 0)


# ------------------------------------------------- (a) the Run A/B case

def test_witness_a_run_b_overlaps_run_a_by_7999_seeds():
    reg = seeds.load(COMMITTED)
    with pytest.raises(seeds.SeedWindowError) as err:
        seeds.require_disjoint(reg, 20260906, 8000)
    text = str(err.value)
    assert "run-A" in text and "7999 deal seed(s) [20260906, 20268905)" in text
    assert "run-B" in text and "8000 deal seed(s)" in text
    hits = {h["name"]: h for h in seeds.overlaps(reg, 20260906, 8000)}
    assert hits["run-A"]["overlap_seeds"] == 7999
    assert hits["run-A"]["overlap"] == [20260906, 20268905]
    # a single shared seed (Run A's first, before Run B starts) is still an overlap
    assert [h["name"] for h in seeds.overlaps(reg, 20260905, 1)] == ["run-A"]
    assert seeds.overlaps(reg, 20268906, 1_000_000) == []


# ------------------------------- (b) disjoint passes/registers; resume passes

def test_witness_b_disjoint_registers_and_resume_reuses(registry):
    reg = seeds.load(registry)
    assert seeds.require_disjoint(reg, 99_000_000, 8000) == []
    receipt = seeds.check_and_register(name="run-F", purpose="trajectory", seed0=99_000_000,
                                       clusters=8000, refuse=None)
    assert receipt["conflicts"] == [] and receipt["span"] == [99_000_000, 99_008_000]
    entry = seeds.find(seeds.load(registry), "run-F")
    assert entry and set(entry) == set(seeds.ENTRY_KEYS)
    assert entry["host"] and entry["created_at"] and entry["git_head"]
    # the resume of the same window (name + seed0 + clusters) passes ...
    again = seeds.check_and_register(name="run-F", purpose="trajectory", seed0=99_000_000,
                                     clusters=8000, refuse=None, resume=True)
    assert again["resumed"] and again["conflicts"] == []
    assert len([w for w in seeds.load(registry)["windows"] if w["name"] == "run-F"]) == 1
    # ... a fresh run of the same name refuses (it would re-deal its own window)
    with pytest.raises(seeds.SeedWindowError, match="run-F"):
        seeds.check_and_register(name="run-F", purpose="trajectory", seed0=99_000_000,
                                 clusters=8000, refuse=None)
    # ... and a resume under that name with a different span refuses
    with pytest.raises(seeds.SeedWindowError, match="differs"):
        seeds.register(seeds.make_entry(name="run-F", purpose="trajectory",
                                        seed0=99_000_000, clusters=16000), registry, reuse=True)
    # the registry is append-only and atomic: every earlier entry survives verbatim
    before = seeds.load(COMMITTED)["windows"]
    assert seeds.load(registry)["windows"][:len(before)] == before
    assert not list(registry.parent.glob("*.tmp"))


def test_register_refuses_bad_entries(registry):
    with pytest.raises(seeds.SeedWindowError, match="purpose"):
        seeds.make_entry(name="x", purpose="training", seed0=1, clusters=1)
    bad = seeds.make_entry(name="x", purpose="other", seed0=1, clusters=1)
    bad["span"] = [1, 3]
    with pytest.raises(seeds.SeedWindowError, match="span"):
        seeds.register(bad, registry)
    registry.write_text("{}")
    with pytest.raises(seeds.SeedWindowError, match="not a"):
        seeds.load(registry)


# ------------------------------------------- (c) trajectory.py argument path

def _traj(out, *extra, seed=20260910):
    return ["--rounds", "2", "--seed", str(seed), "--out", str(out), "--workers", "1",
            "--select-worlds", "2", "--report-worlds", "30", "--explore-rate", "0",
            *extra]


def test_witness_c_trajectory_refuses_run_a_b_and_overrides_with_record(
        registry, tmp_path, capsys, monkeypatch):
    out = tmp_path / "traj"
    code = trajectory.main(_traj(out))
    err = capsys.readouterr().err
    assert code == 2 and "REFUSING" in err
    assert "run-A" in err and "run-B" in err and "[20260910, 20260911)" in err
    assert not out.exists(), "refused before any generation (no run.json, no shards)"
    assert seeds.find(seeds.load(registry), "traj-s20260910") is None

    # the explicit override deals the cluster and records the conflicts
    code = trajectory.main(_traj(out, "--allow-seed-overlap"))
    assert code == 0, capsys.readouterr()
    manifest = json.loads((out / "manifest.json").read_text())
    sw = manifest["seed_window"]
    assert sw["allow_seed_overlap"] and sw["seed0"] == 20260910 and sw["clusters"] == 1
    assert sw["name"] == manifest["run_id"] and sw["purpose"] == "trajectory"
    assert sorted(c["name"] for c in sw["conflicts"]) == ["run-A", "run-B"]
    assert all(c["overlap"] == [20260910, 20260911] and c["overlap_seeds"] == 1
               for c in sw["conflicts"])
    entry = seeds.find(seeds.load(registry), manifest["run_id"])
    assert entry and entry["purpose"] == "trajectory" and entry["span"] == [20260910, 20260911]

    # --resume of the same run accepts its own registered window ...
    code = trajectory.main(_traj(out, "--allow-seed-overlap", "--resume"))
    assert code == 0
    assert json.loads((out / "manifest.json").read_text())["seed_window"] == sw
    runtime = json.loads((out / "runtime.json").read_text())["seed_window"]
    assert runtime["resumed"] and runtime["registry"] == str(registry)
    # ... a fresh run of the same window in another directory refuses
    code = trajectory.main(_traj(tmp_path / "again", "--allow-seed-overlap"))
    assert code == 2 and manifest["run_id"] in capsys.readouterr().err


def test_trajectory_disjoint_seed_registers_without_the_flag(registry, tmp_path):
    out = tmp_path / "traj"
    assert trajectory.main(_traj(out, seed=99_500_000)) == 0
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["seed_window"]["conflicts"] == []
    assert not manifest["seed_window"]["allow_seed_overlap"]
    assert seeds.find(seeds.load(registry), manifest["run_id"])["seed0"] == 99_500_000
    assert trajectory.build_parser().parse_args(
        ["--rounds", "2", "--seed", "1", "--out", "x"]).allow_seed_overlap is False


# ------------------------------------------------------ (d) cwv_duel run

def _duel_args(seed0, *, clusters=4, allow=False, resume=None, out="runs/logs"):
    return argparse.Namespace(seed0=seed0, clusters=clusters, allow_seed_overlap=allow,
                              resume=resume, out=out, calibration="/nonexistent/calibration.json")


def test_witness_d_cwv_duel_refuses_trajectory_and_needs_flag_for_screen(registry, tmp_path):
    duel = _load_script("cwv_duel")
    out = tmp_path / "logs"
    # inside Run C's window: refused, before the calibration is even opened
    with pytest.raises(seeds.SeedWindowError, match="run-C"):
        duel.run(_duel_args(30_270_000, out=str(out)))
    with pytest.raises(seeds.SeedWindowError, match="run-C"):
        duel.run(_duel_args(30_270_000, allow=True, out=str(out)))   # no override for training deals
    # the 70260904 screen window: refused without the flag ...
    with pytest.raises(seeds.SeedWindowError) as err:
        duel.run(_duel_args(70260904, clusters=256, out=str(out)))
    assert "screen-70260904" in str(err.value) and "allow-seed-overlap" in str(err.value)
    assert not out.exists()
    # ... passes with it (it then fails on the missing calibration, i.e. AFTER
    # the seed check) and the replicate is recorded in the registered window
    with pytest.raises(FileNotFoundError):
        duel.run(_duel_args(70260904, clusters=256, allow=True, out=str(out)))
    receipt = duel.seed_window_for_run(_duel_args(70260904, clusters=256, allow=True,
                                                  out=str(out), resume=None), "cwv_test_run")
    assert receipt["allow_seed_overlap"]
    assert {c["name"] for c in receipt["conflicts"]} >= {"screen-70260904",
                                                         "screen-oneply-mini-70260904"}
    assert all(c["overlap_seeds"] == 256 for c in receipt["conflicts"])
    assert seeds.find(seeds.load(registry), "cwv_test_run")["purpose"] == "screen"
    # --resume RUN_ID reuses its own window
    again = duel.seed_window_for_run(_duel_args(70260904, clusters=256, allow=True,
                                                out=str(out), resume="cwv_test_run"),
                                     "cwv_test_run")
    assert again["resumed"] and "cwv_test_run" not in {c["name"] for c in again["conflicts"]}
    # the parser carries the flag; main() reports the refusal as REFUSING
    ns = duel.build_parser().parse_args(["run", "--calibration", "x", "--allow-seed-overlap"])
    assert ns.allow_seed_overlap
    assert duel.main(["run", "--calibration", "x", "--seed0", "30270000"]) == 3


def test_cwv_calibrate_registers_a_calibration_window(registry, tmp_path):
    duel = _load_script("cwv_duel")
    args = argparse.Namespace(seed0=70360904, deals=4, out=str(tmp_path / "calibration.json"),
                              trump_ranks="canonical", budgets="1x", plies=0, tree=False)
    # the default calibration seeds overlap the registered Codex calibration:
    # recorded, not refused (outcome blind); the window is registered
    receipt = seeds.check_and_register(
        name=f"cwv-calibrate:{args.out}", purpose="calibration", seed0=args.seed0,
        clusters=args.deals, refuse=("trajectory",), allow_overlap=True, resume=True)
    assert [c["name"] for c in receipt["conflicts"]] == ["calibration-70360904"]
    assert seeds.find(seeds.load(registry), f"cwv-calibrate:{args.out}")["purpose"] == "calibration"
    # a calibration inside a trajectory window refuses through the script
    with pytest.raises(seeds.SeedWindowError, match="run-D"):
        duel.calibrate(argparse.Namespace(**{**vars(args), "seed0": 40260904,
                                             "checkpoint": "/nonexistent"}))


# ------------------------------------------ vleaf / netroll screen wiring

@pytest.mark.parametrize("script", ["vleaf_screen", "netroll_screen"])
def test_screen_scripts_refuse_before_any_arm(registry, tmp_path, script):
    cli = _load_script(script)
    out = tmp_path / "screen"
    args = argparse.Namespace(seed0=45260904, clusters=4, allow_seed_overlap=False)
    with pytest.raises(seeds.SeedWindowError, match="run-E"):
        cli._screen_window(args, out)
    args = argparse.Namespace(seed0=70260904, clusters=256, allow_seed_overlap=False)
    with pytest.raises(seeds.SeedWindowError, match="screen-70260904"):
        cli._screen_window(args, out)
    args.allow_seed_overlap = True
    receipt = cli._screen_window(args, out)
    assert {c["name"] for c in receipt["conflicts"]} >= {"screen-70260904"}
    assert receipt["name"].startswith(script.split("_")[0] + "-screen:")
    assert cli._screen_window(args, out)["resumed"]            # the identical rerun
    cal = cli._calibration_window(argparse.Namespace(seed0=88261904, clusters=2), out / "cal")
    assert [c["name"] for c in cal["conflicts"]] == ["calibration-88261904"]
    assert json.loads((out / "cal" / "seed_window.json").read_text()) == cal
    ns = cli.parser().parse_args(["run", "--checkpoint", "x", "--out", "y",
                                  "--allow-seed-overlap"] + (["--prior", "p"] if script == "vleaf_screen" else []))
    assert ns.allow_seed_overlap


# ---------------------------------------------------------------- CLI

def test_seed_windows_cli(registry, capsys):
    cli = _load_script("seed_windows")
    assert cli.main(["list"]) == 0
    assert "run-A" in capsys.readouterr().out
    assert cli.main(["check", "20260906", "8000"]) == 2
    out = capsys.readouterr().out
    assert "run-A" in out and "7999" in out and "REFUSED" in out
    assert cli.main(["check", "70260904", "256", "--purpose", "screen"]) == 1
    assert "allow-seed-overlap" in capsys.readouterr().out
    assert cli.main(["check", "99000000", "10"]) == 0
    assert "disjoint" in capsys.readouterr().out


# ----------------------------------------------------------------- (e) RED

def test_red_without_the_check_run_b_would_be_dealt_again(registry, tmp_path, monkeypatch):
    """With the refusal disabled the A/B collision goes through unnoticed --
    the state before this change (the check lived only in a memory)."""
    monkeypatch.setattr(seeds, "require_disjoint",
                        lambda reg, s, c, **kw: seeds.overlaps(reg, s, c, **{
                            k: v for k, v in kw.items() if k in ("purposes", "exclude_name")}))
    duel = _load_script("cwv_duel")
    with pytest.raises(FileNotFoundError):        # got past the seed check
        duel.run(_duel_args(30_270_000, out=str(tmp_path)))
    reg = seeds.load(registry)
    assert seeds.overlaps(reg, 20260906, 8000)[0]["name"] == "run-A"
    assert seeds.require_disjoint(reg, 20260906, 8000)      # RED: no refusal
