import json
import os
from pathlib import Path
import subprocess
import sys
import socket
import launcher as implementation

import pytest

from launcher import LaunchRefused, _sha, packet_digest, render_wrapper, run_plan


def packet(tmp_path):
    root = tmp_path / "out"
    outputs = [str(root / f"w{i}-{i}") for i in range(20)]
    plan = dict(schema="s58combo-unarmed-window-plan-v1", dispatch_authorized=True,
                source_head=None, host_identity={"hostname": socket.gethostname()},
                host_lock=str(tmp_path / "lock"), hold="None", legacy_locks=[],
                arms={"candidate": {"environment": {"SHENGJI_TEST_PIN": "candidate", "SHENGJI_FAST": "0"}},
                      "comparator": {"environment": {"SHENGJI_TEST_PIN": "comparator", "SHENGJI_FAST": "0"}}},
                windows=[dict(output=out, side="candidate" if i < 10 else "comparator",
                              seed=i, argv=["--out", str(root), "--name", f"w{i}", "--seeds", str(i)])
                          for i, out in enumerate(outputs)])
    expected = {out: {"arm": "policy"} for out in outputs}
    return plan, expected


def source(tmp_path):
    root = tmp_path / "src"
    root.mkdir(exist_ok=True)
    if not (root / ".git").exists():
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        (root / "README").write_text("source\n")
        subprocess.run(["git", "add", "README"], cwd=root, check=True)
        subprocess.run(["git", "-c", "user.name=test", "-c", "user.email=test@example", "commit", "-qm", "init"], cwd=root, check=True)
    return root


def bound_source(tmp_path, plan):
    root = source(tmp_path)
    plan["source_path"] = str(root.resolve())
    plan["artifact_sha256"] = {str(root / 'README'): _sha(root / 'README')}
    plan["source_head"] = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    return root


def release(tmp_path, plan, expected, runner_file):
    bound_source(tmp_path, plan)
    launcher = tmp_path / "launcher.sh"
    launcher.write_text(render_wrapper(packet_digest(plan, expected), _sha(runner_file)), encoding="utf-8")
    launcher.chmod(0o755)
    token = tmp_path / "RELEASE"
    token.write_text(_sha(launcher) + "\n", encoding="utf-8")
    return launcher, token


def runner(fail=False):
    code = ("import os,sys,json; a=sys.argv; root=a[a.index('--out')+1]; name=a[a.index('--name')+1]; seed=a[a.index('--seeds')+1]; p=os.path.join(root,name+'-'+seed); os.makedirs(p); "
            "json.dump({'arm':'policy'},open(os.path.join(p,'config.json'),'w')); "
            "json.dump({'complete':True,'completed_clusters':520,'requested_clusters':520,'problems':[],'refused':[],'config':{'arm':'policy'}},open(os.path.join(p,'summary.json'),'w')); "
            "[open(os.path.join(p,f'cluster-{i:05}.json'),'w').close() for i in range(520)]" +
            ("; raise SystemExit(9)" if fail else ""))
    return (sys.executable, "-c", code)


def runner_creating_hold():
    code = ("import json,os,sys; a=sys.argv; root=a[a.index('--out')+1]; name=a[a.index('--name')+1]; seed=a[a.index('--seeds')+1]; p=os.path.join(root,name+'-'+seed); os.makedirs(p); "
            "cfg={'arm':'policy'}; json.dump(cfg,open(os.path.join(p,'config.json'),'w')); "
            "json.dump({'complete':True,'completed_clusters':520,'requested_clusters':520,'problems':[],'refused':[],'config':cfg},open(os.path.join(p,'summary.json'),'w')); "
            "[open(os.path.join(p,f'cluster-{i:05}.json'),'w').close() for i in range(520)]; open(os.environ['SHENGJI_HOLD_PATH'],'w').write('late')")
    return (sys.executable, "-c", code)


def live_runner():
    code = ("import os,subprocess,sys,time; root=sys.argv[sys.argv.index('--out')+1]; name=sys.argv[sys.argv.index('--name')+1]; seed=sys.argv[sys.argv.index('--seeds')+1]; p=os.path.join(root,name+'-'+seed); os.makedirs(p); "
            "c=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); "
            "open(os.path.join(p,'child.pid'),'w').write(str(c.pid))")
    return (sys.executable, "-c", code)


def test_wrapper_embeds_packet_and_runner_hashes():
    text = render_wrapper("a" * 64, "b" * 64)
    assert "a" * 64 in text and "b" * 64 in text and "--packet" in text


@pytest.mark.parametrize('defect', ['host', 'guard', 'runner', 'artifact', 'release'])
def test_bound_guards_refuse_before_output(tmp_path, defect):
    plan, expected = packet(tmp_path)
    root = bound_source(tmp_path, plan)
    file = Path(implementation.__file__)
    if defect == 'host':
        plan['host_identity']['hostname'] = 'another-host'
    elif defect == 'guard':
        plan['host_lock'] = str(tmp_path / 'other-lock')
    launch, token = release(tmp_path, plan, expected, file)
    if defect == 'runner':
        file = tmp_path / 'impostor.py'
        file.write_text('different runner')
    elif defect == 'artifact':
        plan['artifact_sha256'][str(root / 'README')] = '0' * 64
        launch.write_text(render_wrapper(packet_digest(plan, expected), _sha(file)))
        token.write_text(_sha(launch))
    elif defect == 'release':
        token.write_text('0' * 64)
    with pytest.raises(LaunchRefused):
        run_plan(plan, expected, source=root, output=tmp_path / 'out', release=token,
                 launcher=launch, host_lock=tmp_path / 'lock', runner=runner(),
                 runner_sha=_sha(file), runner_file=file)
    assert not (tmp_path / 'out').exists() and not (tmp_path / 'lock').exists()


def test_emitted_wrapper_invocation_runs_pinned_queue(tmp_path):
    plan, expected = packet(tmp_path)
    source_root = source(tmp_path)
    package = source_root / "server" / "shengji" / "train"
    package.mkdir(parents=True)
    (source_root / "server" / "shengji" / "__init__.py").write_text("")
    (source_root / "server" / "shengji" / "train" / "__init__.py").write_text("")
    (package / "cwv_screen_queue.py").write_text(
        "import json, os, sys\n"
        "a=sys.argv; root=a[a.index('--out')+1]; name=a[a.index('--name')+1]; seed=a[a.index('--seeds')+1]\n"
        "p=os.path.join(root, name+'-'+seed); os.makedirs(p)\n"
        "cfg={'arm':'policy'}; json.dump(cfg, open(os.path.join(p,'config.json'),'w'))\n"
        "json.dump({'complete':True,'completed_clusters':520,'requested_clusters':520,'problems':[],'refused':[],'config':cfg}, open(os.path.join(p,'summary.json'),'w'))\n"
        "[open(os.path.join(p, f'cluster-{i:05}.json'),'w').close() for i in range(520)]\n"
    )
    subprocess.run(["git", "-C", str(source_root), "add", "server"], check=True)
    subprocess.run(["git", "-C", str(source_root), "-c", "user.name=test", "-c", "user.email=test@example", "commit", "-qm", "queue"], check=True)
    plan["source_head"] = subprocess.check_output(["git", "-C", str(source_root), "rev-parse", "HEAD"], text=True).strip()
    runner_file = Path(implementation.__file__)
    launch, token = release(tmp_path, plan, expected, runner_file)
    packet_file = tmp_path / "packet.json"; packet_file.write_text(json.dumps(plan))
    expected_file = tmp_path / "expected.json"; expected_file.write_text(json.dumps(expected))
    result = subprocess.run(
        [str(launch), str(packet_file), str(expected_file), str(token), str(runner_file), str(source_root), str(tmp_path / "lock")],
        cwd=tmp_path, text=True, capture_output=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["status"] == "LANE_DONE"
    assert json.loads((tmp_path / "out" / "terminal.json").read_text())["readout"] == "HOLD"


def test_refuses_unapproved_plan_and_hold(tmp_path):
    plan, expected = packet(tmp_path); plan["dispatch_authorized"] = False
    runner_file = Path(implementation.__file__)
    launch, token = release(tmp_path, plan, expected, runner_file)
    with pytest.raises(LaunchRefused, match="not authorized"):
        run_plan(plan, expected, source=bound_source(tmp_path, plan), output=tmp_path / "out",
                 release=token, launcher=launch, host_lock=tmp_path / "lock", runner=runner(), runner_sha=_sha(runner_file), runner_file=runner_file)
    plan["dispatch_authorized"] = True
    hold = tmp_path / "HOLD"; hold.write_text("hold")
    plan["hold"] = str(hold)
    launch, token = release(tmp_path, plan, expected, runner_file)
    with pytest.raises(LaunchRefused, match="HOLD"):
        run_plan(plan, expected, source=bound_source(tmp_path, plan), output=tmp_path / "out",
                 release=token, launcher=launch, hold=hold, host_lock=tmp_path / "lock", runner=runner(), runner_sha=_sha(runner_file), runner_file=runner_file)


def test_dispatch_preserves_readout_hold_and_cleans_own_lock(tmp_path):
    plan, expected = packet(tmp_path); runner_file = Path(implementation.__file__); launch, token = release(tmp_path, plan, expected, runner_file)
    result = run_plan(plan, expected, source=bound_source(tmp_path, plan), output=tmp_path / "out",
                      release=token, launcher=launch, host_lock=tmp_path / "lock", runner=runner(), runner_sha=_sha(runner_file), runner_file=runner_file)
    assert result["status"] == "LANE_DONE" and result["readout"] == "HOLD"
    assert (tmp_path / "out" / "reservation.json").exists()
    assert json.loads((tmp_path / "out" / "terminal.json").read_text())["readout"] == "HOLD"
    assert not (tmp_path / "lock").exists()
    with pytest.raises(LaunchRefused, match="output root"):
        run_plan(plan, expected, source=bound_source(tmp_path, plan), output=tmp_path / "out",
                 release=token, launcher=launch, host_lock=tmp_path / "lock", runner=runner(), runner_sha=_sha(runner_file), runner_file=runner_file)


def test_late_hold_stops_before_second_window(tmp_path):
    plan, expected = packet(tmp_path)
    hold = tmp_path / "HOLD"
    plan["hold"] = str(hold)
    plan["arms"]["candidate"]["environment"]["SHENGJI_HOLD_PATH"] = str(hold)
    runner_file = Path(implementation.__file__)
    launch, token = release(tmp_path, plan, expected, runner_file)
    with pytest.raises(LaunchRefused, match="HOLD marker"):
        run_plan(plan, expected, source=bound_source(tmp_path, plan), output=tmp_path / "out",
                 release=token, launcher=launch, hold=hold, host_lock=tmp_path / "lock",
                 runner=runner_creating_hold(), runner_sha=_sha(runner_file), runner_file=runner_file)
    assert (tmp_path / "out" / "w0-0" / "summary.json").exists()
    assert not (tmp_path / "out" / "w1-1").exists()


def test_failed_window_keeps_partial_output_and_cleans_lock(tmp_path):
    plan, expected = packet(tmp_path); runner_file = Path(implementation.__file__); launch, token = release(tmp_path, plan, expected, runner_file)
    with pytest.raises(LaunchRefused, match="window failed"):
        run_plan(plan, expected, source=bound_source(tmp_path, plan), output=tmp_path / "out",
                 release=token, launcher=launch, host_lock=tmp_path / "lock", runner=runner(True), runner_sha=_sha(runner_file), runner_file=runner_file)
    assert (tmp_path / "out" / "terminal.json").exists()
    assert not (tmp_path / "lock").exists()


def test_foreign_lock_is_preserved(tmp_path):
    plan, expected = packet(tmp_path); runner_file = Path(implementation.__file__); launch, token = release(tmp_path, plan, expected, runner_file)
    lock = tmp_path / "lock"; lock.mkdir(); (lock / "owner").write_text("foreign\n")
    with pytest.raises(LaunchRefused, match="host lock"):
        run_plan(plan, expected, source=bound_source(tmp_path, plan), output=tmp_path / "out",
                 release=token, launcher=launch, host_lock=lock, runner=runner(), runner_sha=_sha(runner_file), runner_file=runner_file)
    assert (lock / "owner").read_text() == "foreign\n"


def test_live_descendant_keeps_host_lock(tmp_path):
    plan, expected = packet(tmp_path); runner_file = Path(implementation.__file__); launch, token = release(tmp_path, plan, expected, runner_file)
    lock = tmp_path / "lock"
    with pytest.raises(LaunchRefused, match="process group"):
        run_plan(plan, expected, source=bound_source(tmp_path, plan), output=tmp_path / "out",
                 release=token, launcher=launch, host_lock=lock, runner=live_runner(), runner_sha=_sha(runner_file), runner_file=runner_file)
    child = int((tmp_path / "out" / "w0-0" / "child.pid").read_text())
    assert lock.exists()
    os.kill(child, 15)
    owner = lock / "owner"
    if owner.exists():
        owner.unlink()
    lock.rmdir()


def test_packet_drift_is_refused_before_output(tmp_path):
    plan, expected = packet(tmp_path)
    runner_file = Path(implementation.__file__)
    launch, token = release(tmp_path, plan, expected, runner_file)
    digest = packet_digest(plan, expected)
    expected[next(iter(expected))] = {"arm": "drift"}
    with pytest.raises(LaunchRefused, match="packet digest"):
        run_plan(plan, expected, source=bound_source(tmp_path, plan), output=tmp_path / "out",
                 release=token, launcher=launch, host_lock=tmp_path / "lock", runner=runner(),
                 runner_sha=_sha(runner_file), runner_file=runner_file, packet_sha=digest)
    assert not (tmp_path / "out").exists()


def test_rc0_empty_window_is_rejected(tmp_path):
    plan, expected = packet(tmp_path)
    runner_file = Path(implementation.__file__)
    launch, token = release(tmp_path, plan, expected, runner_file)
    bound_source(tmp_path, plan)
    with pytest.raises(LaunchRefused, match="completion metadata"):
        run_plan(plan, expected, source=tmp_path / "src", output=tmp_path / "out",
                 release=token, launcher=launch, host_lock=tmp_path / "lock", runner=(sys.executable, "-c", "import os,sys; os.makedirs(os.path.join(sys.argv[sys.argv.index('--out')+1], 'w0-0'))"),
                 runner_sha=_sha(runner_file), runner_file=runner_file)
    assert not (tmp_path / "lock").exists()


def test_interruption_preserves_lock(monkeypatch, tmp_path):
    plan, expected = packet(tmp_path)
    runner_file = Path(implementation.__file__)
    launch, token = release(tmp_path, plan, expected, runner_file)
    bound_source(tmp_path, plan)
    class Interrupted:
        pid = 4242
        def wait(self):
            raise KeyboardInterrupt
        def poll(self):
            return None
    monkeypatch.setattr("launcher.subprocess.Popen", lambda *args, **kwargs: Interrupted())
    monkeypatch.setattr("launcher._live_group", lambda pid: True)
    monkeypatch.setattr("launcher._require_clean_source", lambda *args: None)
    with pytest.raises(KeyboardInterrupt):
        run_plan(plan, expected, source=tmp_path / "src", output=tmp_path / "out",
                 release=token, launcher=launch, host_lock=tmp_path / "lock", runner=runner(),
                 runner_sha=_sha(runner_file), runner_file=runner_file)
    assert (tmp_path / "lock").exists()
    (tmp_path / "lock" / "owner").unlink(); (tmp_path / "lock").rmdir()


def test_output_reservation_race_preserves_foreign_output(tmp_path, monkeypatch):
    plan, expected = packet(tmp_path)
    file = Path(implementation.__file__)
    launch, token = release(tmp_path, plan, expected, file)
    original_lock = implementation._lock
    output = tmp_path / 'out'
    def competing_reservation(path):
        original_lock(path)
        output.mkdir()
        (output / 'terminal.json').write_text('foreign terminal')
    monkeypatch.setattr(implementation, '_lock', competing_reservation)
    with pytest.raises(FileExistsError):
        run_plan(plan, expected, source=tmp_path / 'src', output=output,
                 release=token, launcher=launch, runner_file=file,
                 host_lock=tmp_path / 'lock', runner=runner())
    assert (output / 'terminal.json').read_text() == 'foreign terminal'
    assert not (tmp_path / 'lock').exists()


@pytest.mark.parametrize('mode', ['0', '1'])
def test_dispatch_environment_keeps_pinned_engine_despite_parent(tmp_path, monkeypatch, mode):
    monkeypatch.setenv('SHENGJI_FAST', '0' if mode == '1' else '1')
    monkeypatch.setenv('SHENGJI_UNRELATED', 'leak')
    env = implementation._clean_env({'environment': {'SHENGJI_FAST': mode}}, tmp_path)
    result = subprocess.run([sys.executable, '-c',
        'import os; print(os.environ["SHENGJI_FAST"]); assert "SHENGJI_UNRELATED" not in os.environ'],
        env=env, capture_output=True, text=True, check=True)
    assert result.stdout.strip() == mode


def test_dispatch_refuses_unpinned_engine(tmp_path):
    with pytest.raises(LaunchRefused, match='explicit engine'):
        implementation._clean_env({'environment': {}}, tmp_path)
