import json
import os
from pathlib import Path
import socket
import subprocess
import signal
import pytest

from capacity_probe import (CLUSTERS, WORKERS, LaunchRefused,
                            build_rehearsal_commands, run_rehearsal)
from shengji.train.screen_deadline import RECIPE


def plan():
    return {"python_executable": subprocess.sys.executable, "host_identity": {"hostname": socket.gethostname()},
            "source_head": None,
            "windows": [dict(seed=230060910 + i * 100000, argv=['--clusters', '520'])
                        for _ in range(2) for i in range(10)],
            "arms": {"candidate": {"name": "candidate", "identity": {"arm": "candidate"}, "environment": {"SHENGJI_FAST": "0"}},
                     "comparator": {"name": "comparator", "identity": {"arm": "comparator"}, "environment": {"SHENGJI_FAST": "0"}}}}


def git_source(tmp_path, plan_value):
    source = tmp_path / "source"
    source.mkdir()
    (source / "README").write_text("capacity witness\n")
    subprocess.run(["git", "init", "-q"], cwd=source, check=True)
    subprocess.run(["git", "add", "README"], cwd=source, check=True)
    subprocess.run(["git", "-c", "user.name=test", "-c", "user.email=test@example",
                    "commit", "-qm", "witness"], cwd=source, check=True)
    plan_value["source_path"] = str(source.resolve())
    plan_value["source_head"] = subprocess.check_output(
        ["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    from launcher import _sha
    plan_value["artifact_sha256"] = {str(source / "README"): _sha(source / "README")}
    plan_value["host_lock"] = str(tmp_path / "lock")
    plan_value["hold"] = "None"
    plan_value["legacy_locks"] = []
    return source


def fake_runner(wrong_identity=False, live_child=False, wrong_runtime=False):
    identity = "'wrong'" if wrong_identity else "arm"
    code = ("import json,os,sys; a=sys.argv; root=a[a.index('--out')+1]; "
            "name=a[a.index('--name')+1]; seed=a[a.index('--seeds')+1]; kind=a[a.index('--round-kind')+1]; "
            "p=os.path.join(root,name+'-'+seed); os.makedirs(p); "
            "arm=a[a.index('--arm-policy')+1]; ranks=['2'] if kind=='first' else '2,3,4,5,6,7,8,9,10,J,Q,K,A'.split(','); "
            "cfg={'arm_policy':arm,'arm_policy_identity':{'arm':" + identity + "},'seed0':int(seed),'clusters':14,'trump_ranks':ranks,'round_kind':kind,'decision_deadline':{'seconds':300.0,'version':'spawn-total-play-v1','fallback':'SmartBot-v1','rng_recovery':'rollback-uncommitted-play'}}; "
            "cfg['runtime']={'environment':{k:v for k,v in os.environ.items() if k.startswith('SHENGJI_') or k in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','VECLIB_MAXIMUM_THREADS','MKL_NUM_THREADS')}}; "
            + ("cfg['runtime']['environment']['SHENGJI_FAST']='wrong'; " if wrong_runtime else "") +
            "json.dump(cfg,open(os.path.join(p,'config.json'),'w')); "
            "json.dump({'complete':True,'completed_clusters':14,'requested_clusters':14,");
    code += "'problems':[],'refused':[],'config':cfg},open(os.path.join(p,'summary.json'),'w'));"
    code += "[open(os.path.join(p,f'cluster-{i:05}.json'),'w').close() for i in range(14)]"
    if live_child:
        code += "; import subprocess,time; subprocess.Popen(['sleep','30']); time.sleep(1)"
    return (subprocess.sys.executable, "-c", code)


def test_commands_are_pinned_and_score_free(tmp_path):
    commands = build_rehearsal_commands(plan(), output=tmp_path / "out")
    assert len(commands) == 4
    for command in commands:
        assert command["argv"][command["argv"].index("--workers") + 1] == str(WORKERS)
        assert command["argv"][command["argv"].index("--clusters") + 1] == str(CLUSTERS)
        assert "--score" not in command["argv"]
        assert command["seed"] not in range(230060910, 231060910)


@pytest.mark.parametrize("workers,clusters", [(13, 14), (14, 13)])
def test_fixed_capacity_cannot_drift(tmp_path, workers, clusters):
    with pytest.raises(ValueError):
        build_rehearsal_commands(plan(), output=tmp_path / "out", workers=workers, clusters=clusters)


def test_screen_seed_reuse_refused(tmp_path):
    with pytest.raises(ValueError, match="overlaps"):
        build_rehearsal_commands(plan(), output=tmp_path / "out", seeds=(230060910, 240060910, 250060910, 260060910))


def test_bad_plan_refused(tmp_path):
    bad = plan(); del bad["arms"]["comparator"]
    with pytest.raises(ValueError): build_rehearsal_commands(bad, output=tmp_path / "out")


def test_existing_output_and_hold_refused(tmp_path):
    out = tmp_path / "out"; out.mkdir()
    with pytest.raises(LaunchRefused, match="already exists"):
        run_rehearsal(plan(), source=tmp_path, output=out, host_lock=tmp_path / "lock")
    out.rmdir()
    hold = tmp_path / "HOLD"; hold.write_text("hold")
    with pytest.raises(LaunchRefused, match="HOLD"):
        run_rehearsal(plan(), source=tmp_path, output=tmp_path / "new", host_lock=tmp_path / "lock", hold=hold)


def test_synthetic_queue_rehearsal_records_metadata_only(tmp_path):
    from capacity_probe import run_rehearsal
    frozen = plan()
    source = git_source(tmp_path, frozen)
    result = run_rehearsal(frozen, source=source, output=tmp_path / "run",
                           host_lock=tmp_path / "lock", runner=fake_runner())
    assert result["status"] == "COMPLETE"
    assert result["completed_queues"] == 4
    assert result["max_rss_aggregate_kib"] >= 0
    data = json.loads((tmp_path / "run" / "capacity.json").read_text())
    assert data["clusters_per_arm"] == 14 and data["workers"] == 14
    assert (tmp_path / "run" / "READOUT_HOLD").exists()
    assert not (tmp_path / "lock").exists()


def test_config_identity_mismatch_is_typed_failure(tmp_path):
    frozen = plan(); source = git_source(tmp_path, frozen)
    with pytest.raises(LaunchRefused, match="config arm mismatch"):
        run_rehearsal(frozen, source=source, output=tmp_path / "bad",
                      host_lock=tmp_path / "lock", runner=fake_runner(wrong_identity=True))
    data = json.loads((tmp_path / "bad" / "capacity.json").read_text())
    assert data["status"] == "INTERRUPTED" and not (tmp_path / "lock").exists()


def test_live_child_preserves_typed_terminal_and_lock(tmp_path):
    frozen = plan(); source = git_source(tmp_path, frozen)
    with pytest.raises(LaunchRefused, match="still live"):
        run_rehearsal(frozen, source=source, output=tmp_path / "live",
                      host_lock=tmp_path / "lock", runner=fake_runner(live_child=True))
    data = json.loads((tmp_path / "live" / "capacity.json").read_text())
    assert data["status"] == "INTERRUPTED_LIVE_CHILD"
    assert (tmp_path / "lock").exists() and data["child_pid"]
    os.killpg(data["child_pid"], signal.SIGTERM)
    (tmp_path / "lock" / "owner").unlink()
    (tmp_path / "lock").rmdir()


def test_runtime_environment_mismatch_refused(tmp_path):
    frozen = plan(); source = git_source(tmp_path, frozen)
    with pytest.raises(LaunchRefused, match='runtime environment mismatch'):
        run_rehearsal(frozen, source=source, output=tmp_path / 'run',
                      host_lock=tmp_path / 'lock', runner=fake_runner(wrong_runtime=True))


def test_interpreter_mismatch_refused(tmp_path):
    frozen = plan(); frozen['python_executable'] = '/another/python'
    with pytest.raises(LaunchRefused, match='interpreter mismatch'):
        run_rehearsal(frozen, source=tmp_path, output=tmp_path/'out', host_lock=tmp_path/'lock')


@pytest.mark.parametrize('offset', [0, 14, 519, -13])
def test_rehearsal_rejects_entire_requested_window(tmp_path, offset):
    value = plan()
    for window in value['windows']:
        window['seed'] += 10_000_000
    with pytest.raises(ValueError, match='overlaps'):
        build_rehearsal_commands(value, output=tmp_path/'out',
            seeds=(240060910 + offset, 901001, 1001001, 1101001))


def test_rehearsal_requires_full_plan(tmp_path):
    value = plan()
    del value['windows']
    with pytest.raises(ValueError, match='inventory'):
        build_rehearsal_commands(value, output=tmp_path/'out')
