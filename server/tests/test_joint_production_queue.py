"""Execute the queue shell against isolated service/output fixtures, never fleet."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


@pytest.fixture
def queue_fixture(tmp_path):
    root = tmp_path / 'predecessor'
    arm = root / 'SOFT_W64_K8'
    arm.mkdir(parents=True)
    plan = root / 'launch-plan.json'
    plan.write_text('{"fixture": true}')
    summary = arm / 'summary.json'
    summary.write_text(json.dumps(dict(complete=800, expected=800, errors=[])))
    marker = tmp_path / 'launched.json'
    launcher = tmp_path / 'launcher.py'
    launcher.write_text('import json,sys\nfrom pathlib import Path\n'
                       f'Path({str(marker)!r}).write_text(json.dumps(sys.argv[1:]))\n')
    bindir = tmp_path / 'bin'
    bindir.mkdir()
    service = bindir / 'systemctl'
    service.write_text('#!/bin/sh\n'
        'printf "%s\\n" "InvocationID=${TEST_INVOCATION}" '
        '"ActiveState=${TEST_STATE}" "Result=${TEST_RESULT}" '
        '"ExecMainStatus=${TEST_EXIT}" "MainPID=${TEST_PID}"\n')
    service.chmod(0o755)
    source = (Path(__file__).parents[1] / 'scripts' /
              'queue_joint_production_qualification.sh').read_text()
    source = source.replace('/root/gen-hybrid/server/.venv/bin/python', sys.executable)
    source = source.replace('/root/codex-joint-production-launcher-20260921/server/scripts/policy_abc_launcher.py', str(launcher))
    source = source.replace('/root/codex-pv-production-w64-screen-20260921', str(root))
    source = source.replace('(2049, 1052663)', repr((root.stat().st_dev, root.stat().st_ino)))
    source = source.replace('4138b06d8ddd2e5db16d350c5cae50c27cdde9090daabc3d2cad126686646e26',
                            hashlib.sha256(plan.read_bytes()).hexdigest())
    script = tmp_path / 'queue.sh'
    script.write_text(source)
    env = dict(os.environ, PATH=str(bindir) + os.pathsep + os.environ['PATH'],
               TEST_INVOCATION='0eb17d68e7b34437b8221e2d826dbaab',
               TEST_STATE='inactive', TEST_RESULT='success', TEST_EXIT='0', TEST_PID='0')
    return script, env, marker, summary, plan


def test_success_handoff_invokes_only_joint_qualification(queue_fixture):
    script, env, marker, _, _ = queue_fixture
    run = subprocess.run(['bash', str(script)], env=env, capture_output=True, text=True, timeout=5)
    assert run.returncode == 0, run.stderr
    args = json.loads(marker.read_text())
    assert args[args.index('--suite') + 1] == 'joint-production-qualify'
    assert '--qualify' in args and '--run' in args
    assert args[args.index('--production-worlds') + 1] == '64'


@pytest.mark.parametrize('change', [dict(TEST_INVOCATION='replaced'),
    dict(TEST_STATE='failed'), dict(TEST_RESULT='exit-code'),
    dict(TEST_EXIT='1'), dict(TEST_PID='123')])
def test_bad_service_never_launches(queue_fixture, change):
    script, env, marker, _, _ = queue_fixture
    run = subprocess.run(['bash', str(script)], env={**env, **change},
                         capture_output=True, timeout=5)
    assert run.returncode != 0
    assert not marker.exists()


@pytest.mark.parametrize('bad_output', ['incomplete', 'error', 'plan', 'missing'])
def test_bad_output_never_launches(queue_fixture, bad_output):
    script, env, marker, summary, plan = queue_fixture
    if bad_output == 'plan':
        plan.write_text('{}')
    elif bad_output == 'missing':
        summary.unlink()
    else:
        summary.write_text(json.dumps(dict(complete=799 if bad_output == 'incomplete' else 800,
            expected=800, errors=['timeout'] if bad_output == 'error' else [])))
    run = subprocess.run(['bash', str(script)], env=env, capture_output=True, timeout=5)
    assert run.returncode != 0
    assert not marker.exists()
