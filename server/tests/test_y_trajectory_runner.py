"""The data runner binds its candidate to the deployed recipe."""
import importlib.util
from pathlib import Path

import pytest

from test_release50_fly_config import release50_packages  # noqa: F401
from test_release55_fly_config import release55_pair  # noqa: F401


_PATH = Path(__file__).resolve().parents[1] / "scripts" / "y_trajectory.py"
_SPEC = importlib.util.spec_from_file_location("y_trajectory", _PATH)
runner = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(runner)


def test_recipe_keeps_served_budgets_and_latency_switches(tmp_path):
    fly = _PATH.parents[2] / "fly.toml"
    env = runner.recipe_environment(fly, tmp_path)
    assert env["SHENGJI_PV_SERVING_BUDGET_SECONDS"] == "3"
    assert env["SHENGJI_PV_BURY_SERVING_BUDGET_SECONDS"] == "3"
    assert env["SHENGJI_PV_LEAF_GREEDY_DEADLINE"] == "2"
    assert env["SHENGJI_PV_ENCODE_NATIVE"] == "1"
    assert env["SHENGJI_PV_BELIEF_CKPT"] == str(tmp_path / "ut-rt4-belief-35e225cf.npz")
    assert env["SHENGJI_PV_UNIFIED_CKPT"] == str(tmp_path / "ut-rt4-e2951d35.npz")
    assert "SHENGJI_DATA_DIR" not in env
    assert not any(key.startswith("SHENGJI_CWV_") for key in env)


def test_capture_budgets_are_fly_tomls():
    """The runner, the trajectory capture guard and fly.toml name the same served budgets, so
    captured data is timed as production serves."""
    from shengji.harvest import trajectory

    env = runner.recipe_environment(_PATH.parents[2] / "fly.toml", Path("/unused"))
    assert (runner.PLAY_SECONDS, runner.BURY_SECONDS) == (
        trajectory.SERVED_PLAY_BUDGET_SECONDS, trajectory.SERVED_BURY_BUDGET_SECONDS)
    assert env["SHENGJI_PV_SERVING_BUDGET_SECONDS"] == str(trajectory.SERVED_PLAY_BUDGET_SECONDS)
    assert env["SHENGJI_PV_BURY_SERVING_BUDGET_SECONDS"] == str(trajectory.SERVED_BURY_BUDGET_SECONDS)


@pytest.mark.parametrize("old,new", [
    ("SHENGJI_PV_SERVING_BUDGET_SECONDS = '3'", "SHENGJI_PV_SERVING_BUDGET_SECONDS = '0'"),
    ("SHENGJI_PV_BURY_SERVING_BUDGET_SECONDS = '3'", "SHENGJI_PV_BURY_SERVING_BUDGET_SECONDS = '2'"),
    ("SHENGJI_PV_CANDIDATES = '8'", "SHENGJI_PV_CANDIDATES = '24'"),
    ("SHENGJI_PV_SINGLETON_CHALLENGER = '1'", "SHENGJI_PV_SINGLETON_CHALLENGER = '0'"),
    ("SHENGJI_PV_LEAD_CONFIRM = '0'", "SHENGJI_PV_LEAD_CONFIRM = '32'"),
    ("/data/models/g3a-e04-f4f4127e.npz", "/data/models/../g3a-e04-f4f4127e.npz"),
])
def test_recipe_refuses_budget_width_and_model_path_drift(tmp_path, old, new):
    text = (_PATH.parents[2] / "fly.toml").read_text()
    assert old in text
    changed = tmp_path / "fly.toml"
    changed.write_text(text.replace(old, new))
    with pytest.raises(ValueError):
        runner.recipe_environment(changed, tmp_path)


@pytest.mark.parametrize(("capture", "workers", "split"),
                         [(False, 1, False), (True, 1, False), (True, 2, False), (True, 2, True)],
                         ids=["False", "True", "whole-tail", "split-tail"])
def test_runner_constructs_exact_served_bot(release50_packages, release55_pair, tmp_path, capture, workers, split):
    import json
    import os
    import subprocess
    import sys
    import tomllib

    fly = _PATH.parents[2] / "fly.toml"
    env = tomllib.loads(fly.read_text())["env"]
    models = tmp_path / "models"
    models.mkdir()
    packages = {"SHENGJI_PV_CKPT": release50_packages["value"],
                "SHENGJI_PV_PRIOR_CKPT": release50_packages["prior"],
                "SHENGJI_PV_BELIEF_CKPT": release55_pair["belief"],
                "SHENGJI_PV_UNIFIED_CKPT": release55_pair["unified"]}
    for key, package in packages.items():
        (models / Path(env[key]).name).symlink_to(package)
    from test_harvest_trajectory import _seed_windows
    output = tmp_path / "store"
    registry = _seed_windows(output)
    registry.write_text(json.dumps({"schema": "shengji-seed-windows-v1", "windows": []}))
    options = (["--rounds", "2", "--workers", str(workers), "--seed", "4300000",
                "--out", str(output), "--cap", "256"] if capture else ["--inspect"])
    if split:
        options.append("--split-tail-mirrors")
    result = subprocess.run([
        sys.executable, str(_PATH), "--fly", str(fly), "--models", str(models),
        "--seed-registry", str(registry), *options,
    ], env={"PATH": os.environ["PATH"], "SHENGJI_PV_LEAD_CONFIRM": "32",
            "SHENGJI_PV_SINGLETON_CHALLENGER": "0"}, text=True,
        capture_output=True, timeout=180)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout.splitlines()[0])
    assert report["candidate"] == report["baseline"] == env["SHENGJI_BOT"]
    assert report["environment"]["SHENGJI_PV_BURY_BELIEF_WORLDS"] == "1"
    assert report["environment"]["SHENGJI_PV_PRIOR_SHA256"] == env["SHENGJI_PV_PRIOR_SHA256"]
    assert report["play_seconds"] == 3 and report["bury_seconds"] == 3

    if capture:
        from shengji.train.belief_labels import extract_cluster
        from shengji.train.cwv_data import bridge_record, search_means_points
        manifest = json.loads((output / "manifest.json").read_text())
        assert manifest["config"]["policy"] == env["SHENGJI_BOT"]
        if workers > 1:
            runtime = json.loads((output / "runtime.json").read_text())
            assert runtime.get("split_tail_mirrors", False) is split
            timing = runtime["per_cluster"]["0"]
            assert ("worker_wall_secs" in timing) is split
            if split:
                assert timing["worker_wall_secs"] > 0
        shard = output / manifest["shards"][0]["path"]
        records = [json.loads(line) for line in shard.read_text().splitlines()]
        plays = [row for row in records if row["decision_kind"] == "play"]
        buries = [row for row in records if row["decision_kind"] == "bury"]
        assert len(buries) == 2 and plays
        for row in plays:
            assert bridge_record(row) is not None
            search_means_points(row)
        labels = extract_cluster(shard, store_index=0, cluster_index=0,
                                 calib=0.0, test=0.0, windows=[],
                                 sampler_worlds=0, sampler_splits=[])
        assert labels is not None and len(labels["X"]) == len(plays)
        assert all(row["allocation"]["serving_decision"]["bury_belief_worlds"] for row in buries)
        assert manifest["counts"]["bury_belief_worlds"] == 2
        assert manifest["counts"]["bury_belief_fallbacks"] == sum(
            row["allocation"]["serving_decision"]["bury_belief_fallbacks"] for row in buries)


def test_runner_refuses_legal_capture_cap_drift(tmp_path):
    with pytest.raises(SystemExit):
        runner.main(["--fly", str(tmp_path / "absent.toml"), "--models", str(tmp_path),
                     "--seed-registry", str(tmp_path / "absent.json"), "--cap", "1"])


def test_launcher_hold_then_guarded_resume_preserves_completed_shard(release50_packages, release55_pair, tmp_path,
                                                                  monkeypatch):
    import json
    import subprocess
    import sys
    import tomllib
    import hashlib

    source = _PATH.parents[2]
    module_spec = importlib.util.spec_from_file_location('resume_launcher', source/'tools/y_datagen/launch.py')
    launcher = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(launcher)
    fly = source/'fly.toml'
    env = tomllib.loads(fly.read_text())['env']
    models = tmp_path/'models'
    models.mkdir()
    packages = {'SHENGJI_PV_CKPT': release50_packages['value'], 'SHENGJI_PV_PRIOR_CKPT': release50_packages['prior'],
                'SHENGJI_PV_BELIEF_CKPT': release55_pair['belief'], 'SHENGJI_PV_UNIFIED_CKPT': release55_pair['unified']}
    for key, package in packages.items():
        (models/Path(env[key]).name).symlink_to(package)
    registry = tmp_path/'seeds.json'
    registry.write_text(json.dumps({'schema': 'shengji-seed-windows-v1', 'windows': []}))
    out, hold, release = tmp_path/'store', tmp_path/'HOLD', tmp_path/'RELEASE'
    head = subprocess.check_output(['git', '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    spec = dict(host=launcher.socket.gethostname(), source_dir=str(source), source_git_head=head,
                python=sys.executable, fly_path=str(fly), models_path=str(models), seed_registry=str(registry),
                rounds=4, seed=4300000, workers=1, max_seconds=120,
                holds=[str(hold)], foreign_locks=[], output=str(out), admit_disk_gib=0, stop_disk_gib=0,
                files={str(_PATH): launcher.sha256(_PATH)}, lock=str(tmp_path/'lock'), release=str(release))
    spec['seal_policy'] = env['SHENGJI_BOT']
    # Test isolation substitutes the host census and allows an in-progress checkout.
    monkeypatch.setattr(launcher, '_census', lambda: None)
    real_output = subprocess.check_output
    def checked_output(args, **kw):
        if args[:1] == ['git'] and 'status' in args:
            return ''
        return real_output(args, **kw)
    monkeypatch.setattr(launcher.subprocess, 'check_output', checked_output)
    real_sleep = launcher.time.sleep
    def hold_after_shard(seconds):
        if (out/'shards/cluster-000000.json').exists():
            hold.touch()
        real_sleep(min(seconds, .05))
    monkeypatch.setattr(launcher.time, 'sleep', hold_after_shard)
    launch_path = Path(launcher.__file__)
    def released_run():
        spec_sha = hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()
        release.write_text(json.dumps({'launcher_sha256': launcher.sha256(launch_path), 'spec_sha256': spec_sha}))
        return launcher.execute(spec, spec_sha, launch_path)
    assert released_run() == 1
    terminal0 = Path(str(out)+'.terminal.0.json')
    old_terminal = terminal0.read_bytes()
    assert json.loads(old_terminal)['status'] == 'held'
    assert not (out/'manifest.json').exists()
    kept = {p.name: p.read_bytes() for p in (out/'shards').glob('cluster-000000.*')}
    assert len(kept) == 2
    spec.update(resume=True, run_id=json.loads((out/'run.json').read_text())['run_id'],
                workers=2, split_tail_mirrors=True)
    monkeypatch.setattr(launcher.time, 'sleep', real_sleep)
    hold.unlink()
    assert released_run() == 0
    runtime = json.loads((out/'runtime.json').read_text())
    assert runtime['split_tail_mirrors'] and runtime['clusters']['reused'] == [0]
    assert runtime['per_cluster']['1']['worker_wall_secs'] > 0
    assert terminal0.read_bytes() == old_terminal
    assert all((out/'shards'/name).read_bytes() == data for name, data in kept.items())
    assert json.loads(Path(str(out)+'.terminal.1.json').read_text())['status'] == 'completed'
    manifest = json.loads((out/'manifest.json').read_text())
    assert manifest['run_id'] == spec['run_id'] and len(manifest['shards']) == 2
    assert not Path(spec['lock']).exists()

    seal = json.loads(Path(str(out)+'.terminal.1.json').read_text())['leg_seal']
    assert seal['manifest_sha256'] == launcher.sha256(out/'manifest.json')
    assert seal['rounds'] == 4 and seal['run_id'] == spec['run_id']
    with pytest.raises(launcher.Refused, match='leg identity'):
        launcher.seal_leg(dict(spec, seed=spec['seed']+1), out)
    terminal = Path(str(out)+'.terminal.1.json')
    extract_dir = tmp_path/'rt4-extract'
    prepare = [sys.executable, str(source/'server/scripts/prepare_belief_cache.py'),
               '--store', str(out), '--out', str(extract_dir), '--workers', '1',
               '--sealed-rt4-leg', str(terminal)]
    refused = subprocess.run([*prepare, '0' * 64], capture_output=True, text=True)
    assert refused.returncode and 'terminal digest differs' in refused.stderr and not extract_dir.exists()
    shard = out/manifest['shards'][0]['path']
    original = shard.read_bytes()
    mode = shard.stat().st_mode
    shard.chmod(0o600)
    try:
        shard.write_bytes(b'X' + original[1:])
        refused = subprocess.run([*prepare, launcher.sha256(terminal)], capture_output=True, text=True)
        assert refused.returncode and 'sha256 drift' in refused.stderr and not extract_dir.exists()
    finally:
        shard.write_bytes(original)
        shard.chmod(mode)
    prepared = json.loads(subprocess.check_output([*prepare, launcher.sha256(terminal)]))
    assert prepared['consumer_rows'] == manifest['counts']['decisions'] > 0
    assert json.loads((extract_dir/'manifest.json').read_bytes())['split']['test'] == 0.04
    side = out/manifest['shards'][0]['sidecar']
    saved = side.read_bytes()
    mode = side.stat().st_mode
    side.chmod(0o600)
    try:
        side.write_bytes(saved + b' ')
        refused = subprocess.run([*prepare, launcher.sha256(terminal), '--resume'], capture_output=True, text=True)
        assert refused.returncode and 'sidecar sha256 differs' in refused.stderr
    finally:
        side.write_bytes(saved)
        side.chmod(mode)
    archive = tmp_path/'leg.tar.zst'
    # macOS fleet operators invoke the archive consumer with the system interpreter.
    archive_python = '/usr/bin/python3' if sys.platform == 'darwin' else sys.executable
    archive_cmd = [archive_python, str(source/'tools/y_datagen/archive_leg.py'),
                   str(out), str(terminal), launcher.sha256(terminal)]
    receipt = json.loads(subprocess.check_output([*archive_cmd, str(archive)]))
    assert receipt['verified_members'] == 7
    assert receipt['raw_member_bytes'] > receipt['compressed_bytes'] == archive.stat().st_size
    # Exercise the same producer and consumer with a tranche-bound external mount.
    monkeypatch.syspath_prepend(str(source/'tools/y_datagen'))
    import archive_leg
    ssd = tmp_path/'external'
    ssd.mkdir()
    def external_volume(uuid, *, internal):
        assert (uuid, internal) == ('test-ssd', False)
        return ssd
    monkeypatch.setattr(archive_leg, '_volume', external_volume)
    tranche = dict(spec, tranche_volumes={'archive_uuid': 'test-ssd'})
    sealed = json.loads(terminal.read_bytes())
    sealed['leg_seal'] = launcher.seal_leg(tranche, out)
    bound = tmp_path/'bound.terminal.json'
    bound.write_text(json.dumps(sealed))
    pin = launcher.sha256(bound)
    dest = ssd/'leg.tar.zst'
    assert archive_leg.archive_leg(out, bound, pin, dest)['verified_members'] == 7
    with pytest.raises(ValueError, match='outside the sealed archive volume'):
        archive_leg.archive_leg(out, bound, pin, archive)
    alias = ssd/'redirect'
    alias.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match='outside the sealed archive volume'):
        archive_leg.archive_leg(out, bound, pin, alias/'misplaced.tar.zst')
    assert not (tmp_path/'misplaced.tar.zst.lock').exists()
    mounts = iter([ssd, models])
    monkeypatch.setattr(archive_leg, '_volume', lambda *args, **kwargs: next(mounts))
    interrupted = ssd/'interrupted.tar.zst'
    with pytest.raises(ValueError, match='outside the sealed archive volume'):
        archive_leg.archive_leg(out, bound, pin, interrupted)
    assert not interrupted.exists() and dest.is_file()
    published = archive.stat().st_ino
    assert json.loads(subprocess.check_output([*archive_cmd, str(archive)])) == receipt
    assert archive.stat().st_ino == published
    shard = out / manifest['shards'][0]['path']
    data = shard.read_bytes()
    shard.chmod(0o600)
    shard.write_bytes(b'X' + data[1:])
    with pytest.raises(launcher.Refused, match='trajectory digest differs'):
        launcher.seal_leg(spec, out)
    rejected_archive = tmp_path/'drift.tar.zst'
    refused = subprocess.run([*archive_cmd, str(rejected_archive)], capture_output=True, text=True)
    assert refused.returncode and 'restored member differs' in refused.stderr
    assert not rejected_archive.exists()
    archive.write_bytes(b'truncated')
    refused = subprocess.run([*archive_cmd, str(archive)], capture_output=True)
    assert refused.returncode and archive.read_bytes() == b'truncated'
