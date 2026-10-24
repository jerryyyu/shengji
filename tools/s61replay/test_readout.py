import hashlib
import json
from pathlib import Path
import sys

import pytest
sys.path.insert(0, str(Path(__file__).resolve().parent))
from readout import TERMINAL, extract_once
from test_selector import source
from locator import bind_locator


def inputs(tmp_path):
    locator, raw = source()
    data, terminal, hold, output = [tmp_path / name for name in ('data', 'terminal', 'HOLD', 'output')]
    data.write_bytes(raw)
    terminal.write_text('2026-10-24T00:00:00Z ' + TERMINAL + '\n')
    output.mkdir()
    return data, dict(source_sha=hashlib.sha256(raw).hexdigest(), terminal=terminal,
        terminal_sha=hashlib.sha256(terminal.read_bytes()).hexdigest(), hold=hold,
        output=output, locator=locator, expected_rows=3)


def test_saved_prefix_reaches_replay_and_cannot_be_consumed_twice(tmp_path):
    data, kwargs = inputs(tmp_path)
    result = extract_once(data, **kwargs)
    prefix = json.loads(result.read_text())
    _, witness = bind_locator(prefix['locator'], prefix['rows'])
    assert witness['play_index'] == 0
    assert 'FORBIDDEN_OUTCOME' not in result.read_text()
    with pytest.raises(FileExistsError):
        extract_once(data, **kwargs)


@pytest.mark.parametrize('defect', ['hold', 'terminal_seal', 'terminal_status'])
def test_gate_refuses_before_source_open(tmp_path, monkeypatch, defect):
    data, kwargs = inputs(tmp_path)
    if defect == 'hold': kwargs['hold'].touch()
    elif defect == 'terminal_seal': kwargs['terminal_sha'] = '0' * 64
    else:
        kwargs['terminal'].write_text('RUNNING\n')
        kwargs['terminal_sha'] = hashlib.sha256(kwargs['terminal'].read_bytes()).hexdigest()
    original = Path.open
    def guarded(path, *args, **kw):
        assert path != data, 'source opened before gates'
        return original(path, *args, **kw)
    monkeypatch.setattr(Path, 'open', guarded)
    with pytest.raises(ValueError): extract_once(data, **kwargs)
    assert not (kwargs['output'] / 'consumed.json').exists()


def test_failure_preserves_claim_and_refuses_retry(tmp_path):
    data, kwargs = inputs(tmp_path)
    kwargs['source_sha'] = '0' * 64
    with pytest.raises(ValueError, match='seal'):
        extract_once(data, **kwargs)
    assert (kwargs['output'] / 'consumed.json').exists()
    assert not (kwargs['output'] / 'prefix.json').exists()
    with pytest.raises(FileExistsError): extract_once(data, **kwargs)
