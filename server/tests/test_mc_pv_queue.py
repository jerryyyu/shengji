"""Shell handoff guards; these tests never contact systemd or launch a job."""
import subprocess
import hashlib
import json
import sys
import shlex
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "queue_mc_pv_qualification.sh"
INVOCATION = "351a23df37674a4d9af7f0e20de0c401"


def run_guard(snapshot, suffix="read_snapshot; require_success"):
    definitions = SCRIPT.read_text().split("while true; do", 1)[0]
    stub = "\nsystemctl() { printf '%s\\n' \"$QUEUE_TEST_SNAPSHOT\"; }\n"
    return subprocess.run(
        ["bash", "-c", definitions + stub + suffix],
        env={"QUEUE_TEST_SNAPSHOT": snapshot}, capture_output=True, text=True,
    )


def snapshot(**changes):
    fields = dict(InvocationID=INVOCATION, ActiveState="active", SubState="exited", Result="success",
                  ExecMainStatus="0", MainPID="0")
    fields.update(changes)
    return "\n".join(f"{k}={v}" for k, v in fields.items())


def test_terminal_success():
    assert run_guard(snapshot()).returncode == 0


@pytest.mark.parametrize("changes", [
    {"InvocationID": "replacement"}, {"InvocationID": ""},
    {"SubState": "running"}, {"ActiveState": "inactive"}, {"ActiveState": "failed"},
    {"Result": "exit-code"}, {"ExecMainStatus": "1"}, {"MainPID": "123"},
])
def test_terminal_guard_refuses(changes):
    assert run_guard(snapshot(**changes)).returncode != 0


def test_snapshot_fields_do_not_survive_a_missing_response():
    result = run_guard(snapshot(), "read_snapshot; require_success; "
                       "QUEUE_TEST_SNAPSHOT=''; read_snapshot; require_success")
    assert result.returncode != 0


def test_replacement_detected_at_final_snapshot():
    result = run_guard(snapshot(), "read_snapshot; require_success; "
                       "QUEUE_TEST_SNAPSHOT='InvocationID=replacement'; "
                       "read_snapshot; require_success")
    assert result.returncode != 0


def test_final_guard_precedes_qualification_only_exec():
    text = SCRIPT.read_text()
    assert 'read_snapshot\nrequire_success\nexec "$python" "$launcher"' in text
    assert "--suite mc-pv-qualify --qualify --run" in text


@pytest.mark.parametrize('damage', [None, 'directory', 'plan', 'incomplete', 'errors', 'aggregation'])
def test_output_identity_and_completion_guard(tmp_path, damage):
    # Execute the exact inline guard against a synthetic independently pinned
    # directory/plan. No live paths, services or models are touched.
    program = SCRIPT.read_text().split('<<\'PY\'\n', 1)[1].split('\nPY\n', 1)[0]
    plan = b'{"suite":"joint-grid-screen"}'
    (tmp_path / 'launch-plan.json').write_bytes(plan)
    for arm in ('JS_M1_W4_K8', 'JS_G1_W4_K8'):
        folder = tmp_path / arm
        folder.mkdir()
        summary = {'complete': 800, 'expected': 800, 'errors': []}
        if arm == 'JS_G1_W4_K8':
            if damage == 'incomplete': summary['complete'] = 799
            if damage == 'errors': summary['errors'] = ['failure']
            if damage == 'aggregation': summary['aggregation_error'] = 'invalid'
        (folder / 'summary.json').write_text(json.dumps(summary))
    identity = tmp_path.stat()
    program = program.replace("Path('/root/codex-joint-grid-800-20260920')", f'Path({str(tmp_path)!r})')
    inode = identity.st_ino + int(damage == 'directory')
    program = program.replace('(2049, 2986010)', repr((identity.st_dev, inode)))
    program = program.replace('14cacf0e0aadc25e0b019a8c939f682f551d7b4a09d10794d16b1720e48d3c73',
                              hashlib.sha256(plan).hexdigest())
    if damage == 'plan': (tmp_path / 'launch-plan.json').write_bytes(b'{}')
    result = subprocess.run([sys.executable, '-c', program], capture_output=True, text=True)
    assert (result.returncode == 0) == (damage is None), result.stderr


@pytest.mark.parametrize('scenario', ['success', 'replaced_final', 'failed', 'missing', 'deadline'])
def test_full_queue_flow(tmp_path, scenario):
    root = tmp_path / 'predecessor'
    root.mkdir()
    plan = b'{"suite":"joint-grid-screen"}'
    (root / 'launch-plan.json').write_bytes(plan)
    for arm in ('JS_M1_W4_K8', 'JS_G1_W4_K8'):
        (root / arm).mkdir()
        (root / arm / 'summary.json').write_text(json.dumps(
            {'complete': 800, 'expected': 800, 'errors': []}))
    calls = tmp_path / 'calls'
    calls.write_text('0')
    launched = tmp_path / 'launched.json'
    launcher = tmp_path / 'launcher.py'
    launcher.write_text('import json,sys\nfrom pathlib import Path\n'
                        f'Path({str(launched)!r}).write_text(json.dumps(sys.argv[1:]))\n')
    active = snapshot(ActiveState='active', SubState='running', MainPID='3725830')
    first = (snapshot(ActiveState='failed', Result='exit-code') if scenario == 'failed'
             else '' if scenario == 'missing' else active)
    final = snapshot(InvocationID='replacement') if scenario == 'replaced_final' else snapshot()
    # Counter is persisted because command substitution executes systemctl in
    # a subshell. Exercise actual while loop and final exec, without sleeping.
    stub = f'''systemctl() {{
        local n
        read -r n < {shlex.quote(str(calls))} || true
        n=$((n + 1))
        printf '%s\\n' "$n" > {shlex.quote(str(calls))}
        case "$n" in
            1) printf '%s\\n' {shlex.quote(first)} ;;
            2) printf '%s\\n' {shlex.quote(snapshot())} ;;
            *) printf '%s\\n' {shlex.quote(final)} ;;
        esac
    }}
    sleep() {{ :; }}
'''
    script = SCRIPT.read_text().replace('read_snapshot() {', stub + '\nread_snapshot() {', 1)
    script = script.replace('python=/root/gen-hybrid/server/.venv/bin/python',
                            f'python={shlex.quote(sys.executable)}')
    script = script.replace('launcher=/root/codex-mc-pv-launcher-20260920/server/scripts/policy_abc_launcher.py',
                            f'launcher={shlex.quote(str(launcher))}')
    script = script.replace("Path('/root/codex-joint-grid-800-20260920')", f'Path({str(root)!r})')
    identity = root.stat()
    script = script.replace('(2049, 2986010)', repr((identity.st_dev, identity.st_ino)))
    script = script.replace('14cacf0e0aadc25e0b019a8c939f682f551d7b4a09d10794d16b1720e48d3c73',
                            hashlib.sha256(plan).hexdigest())
    if scenario == 'deadline':
        script = script.replace('SECONDS + 24000', 'SECONDS - 1')
    result = subprocess.run(['bash', '-c', script], capture_output=True, text=True, timeout=10)
    if scenario == 'success':
        assert result.returncode == 0, result.stderr
        args = json.loads(launched.read_text())
        assert args[-4:] == ['--suite', 'mc-pv-qualify', '--qualify', '--run']
        assert int(calls.read_text()) == 3
    else:
        assert result.returncode != 0
        assert not launched.exists()
