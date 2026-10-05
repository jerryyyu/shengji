"""Failure-path witnesses using synthetic dependencies, never screen data."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def reader(monkeypatch):
    path = Path(__file__).resolve().parents[1] / 'scripts/v52ec_recovery_reader.py'
    spec = importlib.util.spec_from_file_location('recovery_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def claim(output):
        if output.exists():
            raise FileExistsError('output exists')
        with Path(str(output) + '.claim').open('x') as handle:
            handle.write('synthetic claim')

    monkeypatch.setattr(module, 'local_module', lambda name:
        SimpleNamespace(helper=lambda path: SimpleNamespace(claim_output=claim)))
    return module


@pytest.mark.parametrize('error', [ValueError, SystemExit])
def test_durable_safe_diagnostics_before_refusal(reader, monkeypatch, tmp_path, error):
    calls = []

    def fail(*, report, **kwargs):
        calls.append(True)
        report['stage'] = 'window_diagnostics'
        report['windows'].append({'seed0': 123, 'se_zero': True})
        raise error('secret utility 123456789')

    monkeypatch.setattr(reader, 'analyze', fail)
    output = tmp_path / 'result.json'
    assert reader.run_once(output, rc_path='synthetic') is False
    result = json.loads(output.read_text())
    assert result['recovery_status'] == 'REFUSED'
    assert result['windows'] == [{'seed0': 123, 'se_zero': True}]
    assert result['stage'] == 'window_diagnostics'
    assert '123456789' not in output.read_text()
    assert result['original_primary'] == 'UNAVAILABLE'
    with pytest.raises(FileExistsError):
        reader.run_once(output, rc_path='synthetic')
    assert len(calls) == 1


def test_claim_alone_prevents_second_access(reader, monkeypatch, tmp_path):
    output = tmp_path / 'result.json'
    Path(str(output) + '.claim').write_text('prior interrupted invocation')
    monkeypatch.setattr(reader, 'analyze', lambda **kw: pytest.fail('second access'))
    with pytest.raises(FileExistsError):
        reader.run_once(output, rc_path='synthetic')
    assert not output.exists()


def test_success_does_not_restore_primary(reader, monkeypatch, tmp_path):
    monkeypatch.setattr(reader, 'analyze', lambda report, **kw: report.update(stage='complete'))
    output = tmp_path / 'result.json'
    assert reader.run_once(output, rc_path='synthetic') is True
    result = json.loads(output.read_text())
    assert result['recovery_status'] == 'DIAGNOSTICS_COMPLETE'
    assert result['original_primary'] == 'UNAVAILABLE'
    assert result['outcome_blind'] is False
    assert 'verdict' not in result
