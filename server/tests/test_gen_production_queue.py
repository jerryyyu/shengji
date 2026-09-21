import importlib.util
import hashlib
import json
from pathlib import Path
import subprocess

import pytest


SCRIPT = Path(__file__).parents[1] / 'scripts' / 'queue_gen_production_qualifications.py'
spec = importlib.util.spec_from_file_location('gen_queue', SCRIPT)
queue = importlib.util.module_from_spec(spec)
spec.loader.exec_module(queue)


def completed(stdout='', returncode=0, stderr=''):
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


@pytest.fixture(autouse=True)
def expected_boot(monkeypatch):
    monkeypatch.setattr(queue, 'current_boot_id', lambda: queue.EXPECTED_BOOT_ID)


def retained_snapshot(**changes):
    fields = {
        'LoadState': 'loaded', 'InvocationID': queue.EXPECTED_INVOCATION,
        'ActiveState': 'inactive', 'Result': 'success',
        'ExecMainStatus': '0', 'MainPID': '0'}
    fields.update(changes)
    return ''.join(f'{key}={value}\n' for key, value in fields.items())


def unloaded_snapshot(**changes):
    return retained_snapshot(LoadState='not-found', InvocationID='', **changes)


def journal_entry(**changes):
    entry = {'_PID': '1', 'UNIT': queue.UNIT,
             '_SYSTEMD_UNIT': queue.SYSTEMD_MANAGER_SCOPE,
             'INVOCATION_ID': queue.EXPECTED_INVOCATION,
             '_BOOT_ID': queue.EXPECTED_BOOT_ID,
             'MESSAGE_ID': queue.UNIT_LOG_SUCCESS}
    entry.update(changes)
    return json.dumps(entry) + '\n'


def test_retained_terminal_success_is_accepted(monkeypatch):
    monkeypatch.setattr(queue, '_run',
                        lambda command, **kwargs: completed(retained_snapshot()))
    assert queue.classify_snapshot(queue.service_snapshot()) == 'success'


def test_unloaded_unit_requires_matching_success_journal(monkeypatch):
    def fake(command, **kwargs):
        if command[0] == 'systemctl':
            return completed(unloaded_snapshot())
        return completed(journal_entry())
    monkeypatch.setattr(queue, '_run', fake)
    assert queue.classify_snapshot(queue.service_snapshot()) == 'success'


@pytest.mark.parametrize('entry', [
    '', 'not-json\n', journal_entry(_PID='2'), journal_entry(UNIT='other.service'),
    journal_entry(INVOCATION_ID='wrong-invocation'),
    journal_entry(_BOOT_ID='wrong-boot'), journal_entry(MESSAGE_ID='wrong-message')])
def test_unloaded_unit_rejects_absent_or_mismatched_journal(monkeypatch, entry):
    def fake(command, **kwargs):
        if command[0] == 'systemctl':
            return completed(unloaded_snapshot())
        return completed(entry, returncode=0 if entry else 1)
    monkeypatch.setattr(queue, '_run', fake)
    with pytest.raises(queue.QueueRefusal):
        queue.classify_snapshot(queue.service_snapshot())


def test_failed_systemctl_without_structured_state_refuses_even_with_valid_journal(monkeypatch):
    def fake(command, **kwargs):
        if command[0] == 'systemctl':
            return completed('', returncode=1, stderr='Unit not found.')
        return completed(journal_entry())
    monkeypatch.setattr(queue, '_run', fake)
    with pytest.raises(queue.QueueRefusal):
        queue.classify_snapshot(queue.service_snapshot())


def test_current_boot_mismatch_rejects_retained_success(monkeypatch):
    monkeypatch.setattr(queue, 'current_boot_id', lambda: 'wrong-boot')
    with pytest.raises(queue.QueueRefusal):
        queue.classify_snapshot(queue._fields(retained_snapshot()))


@pytest.mark.parametrize('changes', [
    {'InvocationID': 'replacement', 'ActiveState': 'active'},
    {'InvocationID': 'replacement', 'ActiveState': 'inactive'},
    {'ActiveState': 'failed', 'Result': 'failed'},
    {'ActiveState': 'inactive', 'Result': 'exit-code'},
])
def test_replacement_and_failed_predecessors_fail_closed(changes):
    with pytest.raises(queue.QueueRefusal):
        queue.classify_snapshot(queue._fields(retained_snapshot(**changes)))


def test_observation_timeout_is_a_refusal(monkeypatch):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs.get('timeout'))
    monkeypatch.setattr(queue.subprocess, 'run', timeout)
    with pytest.raises(queue.QueueRefusal):
        queue.service_snapshot()


@pytest.mark.parametrize('bad', ['aggregation', 'incomplete', 'error', 'plan', 'missing'])
def test_artifact_identity_plan_and_both_clean_summaries(tmp_path, monkeypatch, bad):
    root = tmp_path / 'predecessor'
    for arm in queue.PREDECESSOR_ARMS:
        arm_dir = root / arm
        arm_dir.mkdir(parents=True)
        (arm_dir / 'summary.json').write_text(
            json.dumps({'expected': 800, 'complete': 800, 'errors': []}))
    plan = root / 'launch-plan.json'
    plan.write_text('{"suite":"joint-production-screen"}\n')
    identity = root.stat()
    monkeypatch.setattr(queue, 'PREDECESSOR_OUTPUT', root)
    monkeypatch.setattr(queue, 'PREDECESSOR_DEV', identity.st_dev)
    monkeypatch.setattr(queue, 'PREDECESSOR_INO', identity.st_ino)
    monkeypatch.setattr(queue, 'PREDECESSOR_PLAN_SHA256',
                        hashlib.sha256(plan.read_bytes()).hexdigest())
    queue.validate_predecessor_artifacts()
    summary = root / queue.PREDECESSOR_ARMS[1] / 'summary.json'
    if bad == 'plan':
        plan.write_text('{}')
    elif bad == 'missing':
        summary.unlink()
    else:
        summary.write_text(json.dumps({
            'expected': 800, 'complete': 799 if bad == 'incomplete' else 800,
            'errors': ['timeout'] if bad == 'error' else [],
            'aggregation_error': 'bad' if bad == 'aggregation' else None}))
    with pytest.raises(queue.QueueRefusal):
        queue.validate_predecessor_artifacts()


def test_artifact_inode_mismatch_rejects(tmp_path, monkeypatch):
    root = tmp_path / 'predecessor'
    root.mkdir()
    monkeypatch.setattr(queue, 'PREDECESSOR_OUTPUT', root)
    monkeypatch.setattr(queue, 'PREDECESSOR_DEV', root.stat().st_dev)
    monkeypatch.setattr(queue, 'PREDECESSOR_INO', root.stat().st_ino + 1)
    with pytest.raises(queue.QueueRefusal):
        queue.validate_predecessor_artifacts()


def test_exact_successor_commands_are_qualification_only():
    gen4 = queue.launcher_command(queue.GEN4)
    assert gen4[gen4.index('--suite'):] == [
        '--suite', 'gen4-production-qualify', '--qualify',
        '--production-worlds', '64', '--production-checkpoint',
        '/root/codex-production-js-m1-0d17fd03.npz', '--run']
    assert gen4[gen4.index('--source') + 1] == str(queue.RUNTIME_SOURCE)
    assert '--strength-screen' not in gen4
    gen3 = queue.launcher_command(queue.GEN3)
    assert gen3[gen3.index('--suite') + 1] == 'gen3-production-qualify'
    assert gen3[gen3.index('--qualify') + 1] == '--production-worlds'


def test_gen4_failure_prevents_gen3(monkeypatch):
    calls = []
    monkeypatch.setattr(queue, 'wait_for_predecessor', lambda: {})
    monkeypatch.setattr(queue, 'validate_predecessor_artifacts', lambda: None)
    monkeypatch.setattr(queue, 'service_snapshot', lambda: {})
    monkeypatch.setattr(queue, 'classify_snapshot', lambda snapshot: 'success')

    def run(config):
        calls.append(config['name'])
        if config['name'] == 'gen4':
            raise queue.QueueRefusal('gen4 failed')

    monkeypatch.setattr(queue, 'run_successor', run)
    with pytest.raises(queue.QueueRefusal):
        queue.main(['--run'])
    assert calls == ['gen4']


def test_success_handoff_runs_gen4_then_gen3_once(monkeypatch):
    calls = []
    monkeypatch.setattr(queue, 'wait_for_predecessor', lambda: calls.append('wait'))
    monkeypatch.setattr(queue, 'validate_predecessor_artifacts', lambda: calls.append('artifacts'))
    monkeypatch.setattr(queue, 'service_snapshot', lambda: {})
    monkeypatch.setattr(queue, 'classify_snapshot', lambda snapshot: 'success')
    monkeypatch.setattr(queue, 'run_successor', lambda config: calls.append(config['name']))
    assert queue.main(['--run']) == 0
    assert calls == ['wait', 'artifacts', 'gen4', 'gen3']


def test_deactivating_is_not_terminal_even_with_main_pid_zero():
    snapshot = queue._fields(retained_snapshot(ActiveState='deactivating'))
    assert queue.classify_snapshot(snapshot) == 'running'


@pytest.mark.parametrize('bad', ['head', 'dirty', 'git-error'])
def test_launcher_identity_refuses_changes(monkeypatch, bad):
    def fake(command, **kwargs):
        if 'rev-parse' in command:
            return completed('wrong' if bad == 'head' else queue.GEN4['head'],
                             returncode=1 if bad == 'git-error' else 0)
        return completed(' M changed.py' if bad == 'dirty' else '')
    monkeypatch.setattr(queue, '_run', fake)
    with pytest.raises(queue.QueueRefusal):
        queue.validate_launcher(queue.GEN4)


def test_default_is_status_only(monkeypatch, capsys):
    monkeypatch.setattr(queue, 'status', lambda: {'ActiveState': 'active'})
    monkeypatch.setattr(queue, 'run_successor',
                        lambda config: pytest.fail('launch'))
    assert queue.main([]) == 0
    assert json.loads(capsys.readouterr().out) == {'ActiveState': 'active'}
