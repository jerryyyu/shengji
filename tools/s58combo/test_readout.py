"""Exercise sealed producer output through one-shot saved-result publication."""
import json
from pathlib import Path

import pytest
import launcher
import readout
from test_sealed_input import completed


@pytest.fixture
def invocation(completed, monkeypatch):
    plan, expected, pins = completed
    root = pins['root']
    plan_path, expected_path = root / 'plan.json', root / 'expected.json'
    plan_path.write_text(json.dumps(plan))
    expected_path.write_text(json.dumps(expected))
    monkeypatch.setattr(readout.subprocess, 'check_output',
                        lambda argv, **kw: 'a' * 40 if 'rev-parse' in argv else '')
    args = dict(source=Path(readout.__file__).resolve().parents[2], source_head='a' * 40,
                plan_path=plan_path, expected_path=expected_path,
                packet_sha=launcher.packet_digest(plan, expected), root=root,
                terminal_sha=pins['terminal_sha'], reader_sha=launcher._sha(Path(readout.__file__)),
                result_path=root / 'readout.json')
    return args


def test_sealed_producer_to_saved_result_once(invocation, monkeypatch):
    import outcome_gate
    args = invocation
    (args['root'] / 'READOUT_HOLD').unlink()
    def consume(plan, expected, configs, shards):
        assert configs == expected
        assert sum(map(len, shards.values())) == 10400
        return dict(status='STAGE_OUTCOME_CHECKED_ONLY', pending=['sealed input binding', 'review'])
    monkeypatch.setattr(outcome_gate, 'outcome_checked_result', consume)
    result = readout.read_once(**args)
    assert result['pending'] == ['review']
    saved = args['result_path'].read_bytes()
    assert json.loads(saved) == result
    with pytest.raises(FileExistsError):
        readout.read_once(**args)
    assert args['result_path'].read_bytes() == saved


@pytest.mark.parametrize('defect', ['hold', 'packet', 'reader', 'source'])
def test_refusal_before_consumption(invocation, defect):
    args = invocation
    if defect != 'hold':
        (args['root'] / 'READOUT_HOLD').unlink()
        args[{'packet': 'packet_sha', 'reader': 'reader_sha', 'source': 'source_head'}[defect]] = '0' * 64
    with pytest.raises(ValueError):
        readout.read_once(**args)
    assert not args['result_path'].exists()
    assert not (args['root'] / 'READOUT_CONSUMED.json').exists()


def test_failure_is_saved_without_retry(invocation, monkeypatch):
    args = invocation
    (args['root'] / 'READOUT_HOLD').unlink()
    def fail(*args, **kwargs):
        raise ValueError('synthetic consumer failure')
    monkeypatch.setattr(readout, 'sealed_outcome_checked_result', fail)
    result = readout.read_once(**args)
    assert result['status'] == 'READOUT_FAILED'
    assert json.loads(args['result_path'].read_text()) == result
    with pytest.raises(FileExistsError):
        readout.read_once(**args)


def test_aliased_root_refused_before_publication(invocation):
    args = invocation
    (args['root'] / 'READOUT_HOLD').unlink()
    alias = args['root'].with_name('alias')
    alias.symlink_to(args['root'], target_is_directory=True)
    args.update(root=alias, result_path=alias / 'readout.json')
    with pytest.raises(ValueError, match='unaliased'):
        readout.read_once(**args)
    assert not args['result_path'].exists()
    assert not (args['root'] / 'READOUT_CONSUMED.json').exists()


@pytest.mark.parametrize('status', ['STAGE_OUTCOME_CHECKED_ONLY', 'READOUT_FAILED', 'OUTCOME_INVALID', 'DECISION_INVALID',
    'EXACT_INVALID', 'OPTIONAL_STAGE_INVALID', 'GREEDY_INVALID', 'DTRX_INVALID'])
def test_cli_invalid_results_exit_nonzero(monkeypatch, status):
    flags = ('source', 'source-head', 'plan-path', 'expected-path', 'packet-sha',
             'root', 'terminal-sha', 'reader-sha', 'result-path')
    monkeypatch.setattr(readout.sys, 'argv', ['readout.py',
        *[part for flag in flags for part in ('--' + flag, 'unused')]])
    monkeypatch.setattr(readout, 'read_once', lambda **kwargs: dict(status=status))
    assert readout.main() == 1


def test_memory_refusal_leaves_no_saved_result_or_consumption(invocation, monkeypatch):
    import resource_gate
    args = invocation
    (args['root'] / 'READOUT_HOLD').unlink()
    monkeypatch.setattr(resource_gate, 'available_memory', lambda: 0)
    with pytest.raises(ValueError, match='memory'):
        readout.read_once(**args)
    assert not args['result_path'].exists()
    assert not (args['root'] / 'READOUT_CONSUMED.json').exists()


def test_cli_only_valid_screen_exits_zero(monkeypatch):
    flags = ('source', 'source-head', 'plan-path', 'expected-path', 'packet-sha',
             'root', 'terminal-sha', 'reader-sha', 'result-path')
    monkeypatch.setattr(readout.sys, 'argv', ['readout.py',
        *[part for flag in flags for part in ('--' + flag, 'unused')]])
    monkeypatch.setattr(readout, 'read_once', lambda **kwargs: dict(status='SCREEN_VALID'))
    assert readout.main() == 0
