"""Shell handoff guards; these tests never contact systemd or launch a job."""
import subprocess
import hashlib
import json
import sys
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "queue_joint_grid_qualification.sh"
INVOCATION = "466bab077e1746c2b0560f4eded26450"


def run_guard(snapshot, suffix="read_snapshot; require_success"):
    definitions = SCRIPT.read_text().split("while true; do", 1)[0]
    stub = "\nsystemctl() { printf '%s\\n' \"$QUEUE_TEST_SNAPSHOT\"; }\n"
    return subprocess.run(
        ["bash", "-c", definitions + stub + suffix],
        env={"QUEUE_TEST_SNAPSHOT": snapshot}, capture_output=True, text=True,
    )


def snapshot(**changes):
    fields = dict(InvocationID=INVOCATION, ActiveState="inactive", Result="success",
                  ExecMainStatus="0", MainPID="0")
    fields.update(changes)
    return "\n".join(f"{k}={v}" for k, v in fields.items())


def test_terminal_success():
    assert run_guard(snapshot()).returncode == 0


@pytest.mark.parametrize("changes", [
    {"InvocationID": "replacement"}, {"InvocationID": ""},
    {"ActiveState": "active"}, {"ActiveState": "failed"},
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
    assert "--suite joint-grid-screen --qualify --run" in text


@pytest.mark.parametrize('damage', [None, 'directory', 'plan', 'incomplete', 'errors', 'aggregation'])
def test_output_identity_and_completion_guard(tmp_path, damage):
    # Execute the exact inline guard against a synthetic independently pinned
    # directory/plan. No live paths, services or models are touched.
    program = SCRIPT.read_text().split('<<\'PY\'\n', 1)[1].split('\nPY\n', 1)[0]
    plan = b'{"suite":"wk-screen"}'
    (tmp_path / 'launch-plan.json').write_bytes(plan)
    for arm in ('W4_K8', 'W16_K8', 'W4_K16'):
        folder = tmp_path / arm
        folder.mkdir()
        summary = {'complete': 800, 'expected': 800, 'errors': []}
        if arm == 'W16_K8':
            if damage == 'incomplete': summary['complete'] = 799
            if damage == 'errors': summary['errors'] = ['failure']
            if damage == 'aggregation': summary['aggregation_error'] = 'invalid'
        (folder / 'summary.json').write_text(json.dumps(summary))
    identity = tmp_path.stat()
    program = program.replace("Path('/root/codex-policy-wk-800-20260920')", f'Path({str(tmp_path)!r})')
    inode = identity.st_ino + int(damage == 'directory')
    program = program.replace('(2049, 784066)', repr((identity.st_dev, inode)))
    program = program.replace('c827bf36b0c86d0ca18c9333664d077032ab2fc1aeba26967bc8fd404ac7d352',
                              hashlib.sha256(plan).hexdigest())
    if damage == 'plan': (tmp_path / 'launch-plan.json').write_bytes(b'{}')
    result = subprocess.run([sys.executable, '-c', program], capture_output=True, text=True)
    assert (result.returncode == 0) == (damage is None), result.stderr
