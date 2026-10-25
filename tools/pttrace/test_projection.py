import hashlib
import importlib.util
import json
from pathlib import Path
import pytest
from shengji.luna.transport import _events_and_usage, CODE_MODE_DISABLED_DIAGNOSTIC, CODEX_USAGE_KEYS

spec = importlib.util.spec_from_file_location('pt_projection', Path(__file__).with_name('projection.py'))
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)


def trace(kind='error', final='{"cards":["PRIVATE"],"memory":"SECRET"}'):
    events = [dict(type='thread.started'),
              dict(type='item.completed', item=dict(id='d', type='error', message=CODE_MODE_DISABLED_DIAGNOSTIC)),
              dict(type='turn.started'), dict(type=kind, message='PRIVATE'),
              dict(type='item.completed', item=dict(type='agent_message', text=final)),
              dict(type='turn.completed', usage={k:0 for k in CODEX_USAGE_KEYS})]
    return b'\n'.join(json.dumps(e).encode() for e in events), final.encode()


@pytest.mark.parametrize('kind', ['error', 'turn.failed', 'unknown.lifecycle'])
def test_projection_does_not_classify_recoverability(kind):
    raw, final = trace(kind)
    result = p.project(raw, final, _events_and_usage)
    assert result == dict(first_rejected_type=kind, first_rejected_index=3,
                          completed_before=False, completed_after=True,
                          completion_valid_after_removing_rejected_events=True,
                          final_file_agrees=True)
    assert 'PRIVATE' not in json.dumps(result) and 'SECRET' not in json.dumps(result)


def test_mismatch_and_invalid_completion():
    raw, _ = trace()
    assert p.project(raw, b'{}', _events_and_usage)['final_file_agrees'] is False
    raw = raw.rsplit(b'\n', 1)[0]
    assert p.project(raw, b'{}', _events_and_usage)['completion_valid_after_removing_rejected_events'] is False


def test_prior_tool_refusal_not_mislabeled():
    raw, final = trace()
    events = [json.loads(x) for x in raw.splitlines()]
    events.insert(3, dict(type='item.completed', item=dict(type='command_execution')))
    with pytest.raises(ValueError, match='different first refusal'):
        p.project(b'\n'.join(json.dumps(e).encode() for e in events), final, _events_and_usage)


def setup_files(tmp_path, monkeypatch):
    root = tmp_path / 'root'; root.mkdir()
    directory = root / 'one-call'; directory.mkdir()
    raw, final = trace()
    (directory/'stdout.jsonl').write_bytes(raw)
    (directory/'final.json').write_bytes(final)
    (root/'terminal.json').write_bytes(b'{}')
    (root/'benchmark').mkdir()
    mirror = json.dumps(dict(calls=[dict(error='CodexTurnTransportError: Codex trace event forbidden', evidence_path=str(directory))])).encode()
    (root/'benchmark'/p.TARGET).write_bytes(mirror)
    source = Path(__file__).resolve().parents[2]/'server'
    for key, value in dict(ROOT=root, TRACE_DIR=directory, OUTPUT=tmp_path/'output', SOURCE=source,
                           TERMINAL_SHA=hashlib.sha256(b'{}').hexdigest(), MIRROR_SHA=hashlib.sha256(mirror).hexdigest(),
                           TRANSPORT_SHA=hashlib.sha256((source/'shengji/luna/transport.py').read_bytes()).hexdigest()).items():
        monkeypatch.setattr(p, key, value)
    return directory


def test_files_to_bounded_result_once(tmp_path, monkeypatch):
    setup_files(tmp_path, monkeypatch)
    p.run()
    assert json.loads((p.OUTPUT/'result.json').read_text())['final_file_agrees'] is True
    with pytest.raises(FileExistsError): p.run()


@pytest.mark.parametrize('fault', ['hold', 'symlink', 'mirror'])
def test_refuses_without_disclosing_private_text(tmp_path, monkeypatch, fault):
    directory = setup_files(tmp_path, monkeypatch)
    if fault == 'hold': (p.ROOT/'HOLD').touch()
    if fault == 'symlink':
        (directory/'stdout.jsonl').unlink()
        (directory/'stdout.jsonl').symlink_to(directory/'final.json')
    if fault == 'mirror': (p.ROOT/'benchmark'/p.TARGET).write_text('PRIVATE')
    with pytest.raises(ValueError) as exc: p.run()
    assert 'PRIVATE' not in str(exc.value)
    assert not (p.OUTPUT/'result.json').exists()
