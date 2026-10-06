import fcntl
import hashlib
import json
import os

import pytest

from shengji.eval import s11_once as module
from shengji.eval.s11_public_view import public_s11_fixture
from test_s11_collection import factory
from test_s11_public_view import trajectory


@pytest.fixture
def fixture(trajectory):
    return public_s11_fixture(trajectory, 98, root_id='once-synthetic')


def run(tmp_path, fixture, build, **kw):
    return module.collect_s11_once(tmp_path, build, fixture,
        packet_sha256='a' * 64, seed=17, **kw)


def root(tmp_path, fixture):
    return tmp_path / hashlib.sha256(fixture.id.encode()).hexdigest()


def test_real_collect_save_reuse_without_model_call(tmp_path, fixture):
    calls = dict(leaves=0, policy=[], bots=[])
    build = factory(calls)
    def guarded():
        assert (root(tmp_path, fixture) / 'started.json').is_file()
        return build()
    first = run(tmp_path, fixture, guarded)
    saved = run(tmp_path, fixture, lambda: pytest.fail('repeated inference'))
    assert saved == json.loads(json.dumps(first))
    assert calls['policy'] == [64]


@pytest.mark.parametrize('error', [ValueError('fixture failure'), KeyboardInterrupt()])
def test_failed_or_interrupted_root_never_restarts(tmp_path, fixture, error):
    def fail():
        raise error
    with pytest.raises(type(error)):
        run(tmp_path, fixture, fail)
    state = root(tmp_path, fixture)
    assert (state / 'started.json').exists()
    assert (state / 'failed.json').exists() == isinstance(error, Exception)
    if isinstance(error, Exception):
        assert json.loads((state / 'failed.json').read_text())['error_type'] == 'ValueError'
    with pytest.raises(ValueError, match='explicit disposition'):
        run(tmp_path, fixture, lambda: pytest.fail('retried failed root'))


def test_concurrent_root_owner_refused_before_inference(tmp_path, fixture):
    state = root(tmp_path, fixture)
    state.mkdir()
    fd = os.open(state / 'owner.lock', os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError):
            run(tmp_path, fixture, lambda: pytest.fail('overlapping inference'))
    finally:
        os.close(fd)


def test_expired_before_start_remains_untouched(tmp_path, fixture):
    def expired():
        raise TimeoutError('budget')
    with pytest.raises(TimeoutError):
        run(tmp_path, fixture, lambda: pytest.fail('inference'), check_budget=expired)
    assert not (root(tmp_path, fixture) / 'started.json').exists()


def test_partial_publication_never_recomputes(tmp_path, fixture, monkeypatch):
    def partial(path, result, **kw):
        path.with_name('.completed.json.partial').write_bytes(b'{')
        raise OSError('interrupted publication')
    monkeypatch.setattr(module, 'save_s11_root', partial)
    with pytest.raises(OSError):
        run(tmp_path, fixture, factory(dict(leaves=0, policy=[], bots=[])))
    with pytest.raises(ValueError, match='explicit recovery'):
        run(tmp_path, fixture, lambda: pytest.fail('recomputed completed work'))


def test_published_completion_survives_post_publish_exception(tmp_path, fixture, monkeypatch):
    original = module.save_s11_root
    def saved_then_crash(*args, **kw):
        original(*args, **kw)
        raise OSError('after publication')
    monkeypatch.setattr(module, 'save_s11_root', saved_then_crash)
    with pytest.raises(OSError, match='after publication'):
        run(tmp_path, fixture, factory(dict(leaves=0, policy=[], bots=[])))
    assert not (root(tmp_path, fixture) / 'failed.json').exists()
    assert run(tmp_path, fixture, lambda: pytest.fail('repeated work'))['root_id'] == fixture.id


def test_failed_journal_does_not_mask_original_failure(tmp_path, fixture, monkeypatch):
    original = module.publish_exclusive_bytes
    def publish(path, raw):
        if path.name == 'failed.json':
            raise OSError('disk failure')
        return original(path, raw)
    monkeypatch.setattr(module, 'publish_exclusive_bytes', publish)
    def fail():
        raise RuntimeError('model failure')
    with pytest.raises(RuntimeError, match='model failure') as caught:
        run(tmp_path, fixture, fail)
    assert 'OSError' in caught.value.__notes__[0]
    with pytest.raises(ValueError, match='explicit disposition'):
        run(tmp_path, fixture, lambda: pytest.fail('retry'))


def test_completed_context_drift_refuses_without_model_call(tmp_path, fixture):
    run(tmp_path, fixture, factory(dict(leaves=0, policy=[], bots=[])))
    with pytest.raises(ValueError, match='context mismatch'):
        run(tmp_path, fixture, lambda: pytest.fail('model called'), fill_seed=1)


@pytest.mark.parametrize('damage', ['absent', 'different-context', 'malformed'])
def test_completion_requires_matching_durable_start(tmp_path, fixture, damage):
    run(tmp_path, fixture, factory(dict(leaves=0, policy=[], bots=[])))
    started = root(tmp_path, fixture) / 'started.json'
    if damage == 'absent':
        started.unlink()
    else:
        data = json.loads(started.read_text())
        data['context']['seed'] = 18
        started.chmod(0o600)
        started.write_text(json.dumps(data) if damage == 'different-context' else '{')
        started.chmod(0o400)
    with pytest.raises((ValueError, OSError)):
        run(tmp_path, fixture, lambda: pytest.fail('inference'))


def test_root_directory_durability_failure_prevents_start(tmp_path, fixture, monkeypatch):
    def fail(fd):
        raise OSError('directory fsync failed')
    monkeypatch.setattr(module.os, 'fsync', fail)
    with pytest.raises(OSError, match='directory fsync failed'):
        run(tmp_path, fixture, lambda: pytest.fail('inference'))
    assert not (root(tmp_path, fixture) / 'started.json').exists()
