import hashlib
import importlib.util
import json
from pathlib import Path

import pytest
from shengji.luna import benchmark_transport as adapter
from shengji.luna.transport import CODE_MODE_DISABLED_DIAGNOSTIC, CODEX_USAGE_KEYS

spec = importlib.util.spec_from_file_location('pt_acceptance', Path(__file__).with_name('acceptance.py'))
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)
NOTICE = ('Reconnecting... 1/5 (stream disconnected before completion: '
          'WebSocket protocol error: Connection reset without closing handshake)')


def trace(notice=NOTICE):
    final = '{"cards":["PRIVATE"],"evaluations":null,"memory":"SECRET"}'
    events = [dict(type='thread.started'),
              dict(type='item.completed', item=dict(id='d', type='error', message=CODE_MODE_DISABLED_DIAGNOSTIC)),
              dict(type='turn.started'), dict(type='error', message=notice),
              dict(type='item.completed', item=dict(type='agent_message', text=final)),
              dict(type='turn.completed', usage={k: 0 for k in CODEX_USAGE_KEYS})]
    return events, final.encode()


def encoded(events):
    return b'\n'.join(json.dumps(e).encode() for e in events)


def test_existing_parser_accepts_recovered_notice_and_bound_final():
    events, final = trace()
    assert p.project(encoded(events), final, adapter) == {'accepted': True}


@pytest.mark.parametrize('fault', ['unknown', 'failed', 'tool', 'ordering', 'attempt', 'extra-key', 'final', 'malformed'])
def test_refusal_reveals_only_class(fault):
    events, final = trace('PRIVATE' if fault == 'unknown' else NOTICE)
    if fault == 'failed': events[-1] = dict(type='turn.failed', error={'message': 'PRIVATE'})
    if fault == 'tool': events.insert(4, dict(type='item.completed', item=dict(type='command_execution', command='PRIVATE')))
    if fault == 'ordering': events[2], events[3] = events[3], events[2]
    if fault == 'attempt': events.insert(4, events[3].copy())
    if fault == 'extra-key': events[3]['secret'] = 'PRIVATE'
    if fault == 'final': final = b'{}'
    if fault == 'malformed': final = b'PRIVATE'
    result = p.project(encoded(events), final, adapter)
    assert result['accepted'] is False
    assert set(result) == {'accepted', 'refusal_class'}
    assert result['refusal_class'] in {'CodexTurnTransportError', 'CodexToolEventError'}
    assert 'PRIVATE' not in json.dumps(result) and 'SECRET' not in json.dumps(result)


def setup_files(tmp_path, monkeypatch):
    root = tmp_path/'root'; root.mkdir()
    directory = root/'one-call'; directory.mkdir()
    events, final = trace()
    (directory/'stdout.jsonl').write_bytes(encoded(events))
    (directory/'final.json').write_bytes(final)
    (root/'terminal.json').write_bytes(b'{}')
    (root/'benchmark').mkdir()
    mirror = json.dumps(dict(calls=[dict(error='CodexTurnTransportError: Codex trace event forbidden', evidence_path=str(directory))])).encode()
    (root/'benchmark'/p.TARGET).write_bytes(mirror)
    source = Path(__file__).resolve().parents[2]/'server'
    values = dict(ROOT=root, TRACE_DIR=directory, OUTPUT=tmp_path/'output', SOURCE=source,
                  PRODUCER_PIDS=(), TERMINAL_SHA=hashlib.sha256(b'{}').hexdigest(),
                  MIRROR_SHA=hashlib.sha256(mirror).hexdigest())
    for key, name in [('TRANSPORT_SHA', 'transport.py'), ('BENCHMARK_SHA', 'benchmark_transport.py')]:
        values[key] = hashlib.sha256((source/'shengji/luna'/name).read_bytes()).hexdigest()
    for key, value in values.items(): monkeypatch.setattr(p, key, value)
    return directory


def test_bound_files_to_result_once(tmp_path, monkeypatch, capsys):
    setup_files(tmp_path, monkeypatch)
    p.run()
    assert json.loads((p.OUTPUT/'result.json').read_text()) == {'accepted': True}
    assert {x.name for x in p.OUTPUT.iterdir()} == {'result.json'}
    assert capsys.readouterr() == ('', '')
    with pytest.raises(FileExistsError): p.run()


@pytest.mark.parametrize('fault', ['hold', 'symlink', 'mirror', 'adapter', 'parser', 'oversize', 'live'])
def test_guard_failure_cannot_publish_acceptance(tmp_path, monkeypatch, fault):
    directory = setup_files(tmp_path, monkeypatch)
    if fault == 'hold': (p.ROOT/'HOLD').touch()
    if fault == 'symlink':
        (directory/'stdout.jsonl').unlink()
        (directory/'stdout.jsonl').symlink_to(directory/'final.json')
    if fault == 'mirror': (p.ROOT/'benchmark'/p.TARGET).write_text('PRIVATE')
    if fault == 'adapter': monkeypatch.setattr(p, 'BENCHMARK_SHA', 'wrong')
    if fault == 'parser': monkeypatch.setattr(p, 'TRANSPORT_SHA', 'wrong')
    if fault == 'oversize': (directory/'stdout.jsonl').write_bytes(b'X' * (4 * 1024 * 1024 + 1))
    if fault == 'live':
        monkeypatch.setattr(p, 'PRODUCER_PIDS', ('self',))
        if not Path('/proc/self').exists(): pytest.skip('Linux producer guard')
    with pytest.raises(ValueError) as exc: p.run()
    assert 'PRIVATE' not in str(exc.value)
    assert not (p.OUTPUT/'result.json').exists()
