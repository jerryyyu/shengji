from concurrent.futures import ThreadPoolExecutor
import json
import threading

import pytest

from shengji.eval import s11_admission_once as module
from test_s11_schedule import PIN, slots, trajectory


@pytest.fixture(autouse=True)
def synthetic_plan_boundary(monkeypatch):
    # These unit tests isolate once/failure behavior. The real planner and
    # reader are joined in test_s11_input_bundle's synthetic corpus witness.
    monkeypatch.setattr(module, 'plan_s11_staging', lambda *a, **kw: None)


def run(path):
    return module.admit_s11_inputs_once('/unused/manifest.json', '/unused/root', path,
        manifest_sha256=PIN, packet_sha256='b' * 64, max_manifest_bytes=1024)


def test_success_is_silent_and_never_rereads(tmp_path, slots, monkeypatch, capsys):
    calls = []
    def manifest(*args):
        assert (tmp_path / 'started.json').is_file()
        calls.append(args)
        return b'{}'
    monkeypatch.setattr(module, '_manifest', manifest)
    monkeypatch.setattr(module, 'read_s11_inputs', lambda *a, **kw: slots)
    result = run(tmp_path)
    assert json.loads((tmp_path / 'receipt.json').read_bytes()) == result
    assert result['counts']['unattempted'] == 64
    with pytest.raises(ValueError, match='disposition'):
        run(tmp_path)
    assert len(calls) == 1
    assert capsys.readouterr() == ('', '')


@pytest.mark.parametrize('phase', ['manifest', 'reader', 'publication'])
def test_failure_retains_start_sanitizes_and_never_retries(tmp_path, monkeypatch, phase):
    def fail(*a, **kw):
        raise ValueError('winner=2 outcome_for=900 SECRET_RAW')
    monkeypatch.setattr(module, '_manifest', fail if phase == 'manifest' else lambda *a: b'{}')
    monkeypatch.setattr(module, 'read_s11_inputs', fail if phase == 'reader' else lambda *a, **kw: [])
    monkeypatch.setattr(module, 'publish_s11_input_bundle', fail)
    with pytest.raises(ValueError) as caught:
        run(tmp_path)
    assert caught.value.__context__ is None and caught.value.__cause__ is None
    assert 'SECRET_RAW' not in str(caught.value)
    assert {p.name for p in tmp_path.iterdir()} == {'started.json', 'failed.json'}
    assert 'SECRET_RAW' not in (tmp_path / 'failed.json').read_text()
    assert set(json.loads((tmp_path / 'failed.json').read_bytes())) == {
        'schema', 'packet_sha256', 'manifest_sha256', 'status', 'phase', 'reason'}
    monkeypatch.setattr(module, '_manifest', lambda *a: pytest.fail('retried raw access'))
    with pytest.raises(ValueError, match='disposition'):
        run(tmp_path)


def test_concurrent_attempt_cannot_duplicate_raw_access(tmp_path, slots, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    calls = []
    def manifest(*args):
        calls.append(args)
        entered.set()
        assert release.wait(5)
        return b'{}'
    monkeypatch.setattr(module, '_manifest', manifest)
    monkeypatch.setattr(module, 'read_s11_inputs', lambda *a, **kw: slots)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(run, tmp_path)
        assert entered.wait(5)
        try:
            with pytest.raises(ValueError, match='disposition'):
                run(tmp_path)
        finally:
            release.set()
        first.result()
    assert len(calls) == 1


@pytest.mark.parametrize('kind', ['oversized', 'symlink', 'fifo'])
def test_manifest_boundary(tmp_path, kind):
    import os
    path = tmp_path / 'manifest'
    if kind == 'symlink':
        path.symlink_to(tmp_path / 'absent')
    elif kind == 'fifo':
        os.mkfifo(path)
    else:
        path.write_bytes(b'123')
    with pytest.raises((ValueError, OSError)):
        module._manifest(path, 2)


@pytest.mark.parametrize('occupied', ['started.json', '.started.json.partial', 'receipt.json'])
def test_crash_artifacts_block_before_any_raw_access(tmp_path, monkeypatch, occupied):
    (tmp_path / occupied).touch()
    monkeypatch.setattr(module, '_manifest', lambda *a: pytest.fail('raw read'))
    with pytest.raises(ValueError, match='disposition'):
        run(tmp_path)
