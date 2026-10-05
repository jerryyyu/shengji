"""Failure-path witnesses using synthetic dependencies, never screen data."""
import importlib.util
import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def real_reader():
    path = Path(__file__).resolve().parents[1] / 'scripts/v52ec_recovery_reader.py'
    spec = importlib.util.spec_from_file_location('recovery_source_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_local_dependencies_match_pins(real_reader):
    for name, expected in [('v52ec_reader', real_reader.ORIGINAL_SHA),
                           ('v52ec_recovery_diagnostics', real_reader.DIAGNOSTICS_SHA)]:
        loaded = real_reader.local_module(name)
        assert loaded._source_sha256 == expected
        assert hashlib.sha256(Path(loaded.__file__).read_bytes()).hexdigest() == expected
    with pytest.raises(ValueError, match='unrecognized'):
        real_reader.local_module('../not-a-dependency')


def test_changed_diagnostics_refuse_before_execution_or_data_access(real_reader, monkeypatch, tmp_path):
    scripts = Path(real_reader.__file__).parent
    original = (scripts / 'v52ec_reader.py').read_bytes()
    (tmp_path / 'v52ec_reader.py').write_bytes(original)
    (tmp_path / 'v52ec_recovery_diagnostics.py').write_text(
        "raise AssertionError('unverified code executed')\n")
    monkeypatch.setattr(real_reader, '__file__', str(tmp_path / 'reader.py'))
    # None of these nonexistent inputs may be reached before source refusal.
    with pytest.raises(ValueError, match='local dependency source drift'):
        real_reader.analyze(tmp_path / 'NO-DATA', reservation=tmp_path / 'NO-RESERVATION',
            status=tmp_path / 'NO-STATUS', rc_path=tmp_path / 'NO-HELPER',
            support=tmp_path / 'NO-SUPPORT', reader_dir=tmp_path / 'NO-VALIDATOR',
            primary_path=tmp_path / 'NO-PRIMARY', report={'source_sha256': {}})


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


@pytest.mark.parametrize('success', [True, False])
def test_cli_binds_all_explicit_paths_and_exit_status(reader, monkeypatch, capsys, success):
    flags = ('reservation', 'status', 'rc-path', 'support', 'reader-dir', 'primary-path')
    argv = ['recovery', 'synthetic-root', 'synthetic-output']
    for flag in flags:
        argv.extend(['--' + flag, 'synthetic-' + flag])
    monkeypatch.setattr(sys, 'argv', argv)

    def run(output, **kwargs):
        assert output == Path('synthetic-output')
        assert kwargs == {'root': Path('synthetic-root'), **{
            f.replace('-', '_'): Path('synthetic-' + f) for f in flags}}
        return success

    monkeypatch.setattr(reader, 'run_once', run)
    assert reader.main() == (0 if success else 1)
    assert capsys.readouterr().out.strip() == (
        'DIAGNOSTICS_COMPLETE' if success else 'REFUSED: safe report preserved')
